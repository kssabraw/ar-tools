"""Async job: publish a blog run to GitHub with generated images.

The GitHub publish of a blog_post enqueues one `blog_github_publish` job instead
of committing synchronously — generating a hero + N body images with gpt-image-1
and committing them (bytes + markdown) atomically takes longer than a request
should hang. The job:

  1. reads the finished run + client,
  2. generates the images (best-effort — degrades to markdown-only),
  3. commits markdown + image bytes in one commit,
  4. records each image on `run_images`, sets the run's featured image, and
     persists the published URL,
  5. closes the native "Review & publish" task if one was opened.

Kept separate from `routers/publish.py` so the worker doesn't import the router.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db.supabase_client import get_supabase
from services import image_generation
from services.blog_jsonld import build_blog_jsonld, faqs_from_article
from services.github_publish import (
    GitHubPublishError,
    publish_blog_with_images_to_github,
    slugify,
)

logger = logging.getLogger(__name__)


def enqueue_blog_github_publish(run_id: str, user_id: str | None = None) -> str:
    """Queue a blog_github_publish job. Returns the job id. Idempotent-ish: if an
    unstarted job for this run already exists, reuse it rather than piling up."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "blog_github_publish")
        .eq("entity_id", run_id)
        .eq("status", "pending")
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]
    row = (
        supabase.table("async_jobs")
        .insert(
            {
                "job_type": "blog_github_publish",
                "entity_id": run_id,
                "payload": {"run_id": run_id, "user_id": user_id},
            }
        )
        .execute()
    )
    return row.data[0]["id"]


def _sources_cited_article(supabase, run_id: str) -> list[dict]:
    rows = (
        supabase.table("module_outputs")
        .select("output_payload")
        .eq("run_id", run_id)
        .eq("module", "sources_cited")
        .eq("status", "complete")
        .execute()
    ).data or []
    if not rows:
        return []
    return ((rows[0].get("output_payload") or {}).get("enriched_article") or {}).get("article") or []


def _brief_title_h1(supabase, run_id: str) -> tuple[str | None, str | None]:
    rows = (
        supabase.table("module_outputs")
        .select("output_payload, attempt_number")
        .eq("run_id", run_id)
        .eq("module", "brief")
        .eq("status", "complete")
        .order("attempt_number", desc=True)
        .execute()
    ).data or []
    if not rows:
        return None, None
    p = rows[0].get("output_payload") or {}
    return (p.get("title") or "").strip() or None, (p.get("h1") or "").strip() or None


def _iso_date(value) -> str | None:
    return value[:10] if isinstance(value, str) and len(value) >= 10 else None


def _blog_schema(supabase, run_id: str, *, client: dict, run: dict, title: str, image_url: str | None) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    date_published = _iso_date(run.get("published_at")) or _iso_date(run.get("created_at")) or today
    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else {}
    same_as = [u for u in [gbp.get("google_maps_uri")] if u and str(u).strip()]
    return build_blog_jsonld(
        title=title,
        faqs=faqs_from_article(_sources_cited_article(supabase, run_id)),
        brand_name=client.get("name") or "",
        site_url=client.get("website_url") or client.get("wordpress_site_url") or "",
        logo_url=client.get("logo_url") or gbp.get("logo") or None,
        same_as=same_as or None,
        telephone=gbp.get("phone") or None,
        image_url=image_url,
        date_published=date_published,
        date_modified=today,
    )


def _persist_images(run_id: str, slots: list[image_generation.ImageSlot]) -> None:
    """Replace the run's image rows with the committed set (best-effort)."""
    supabase = get_supabase()
    try:
        supabase.table("run_images").delete().eq("run_id", run_id).execute()
        rows = [
            {
                "run_id": run_id,
                "role": s.role,
                "kind": s.kind,
                "position": s.position,
                "anchor_heading": s.anchor_heading,
                "alt": s.alt,
                "prompt": s.prompt,
                "preview_url": s.preview_url,
                "repo_path": s.repo_path,
                "status": "committed",
            }
            for s in slots
        ]
        if rows:
            supabase.table("run_images").insert(rows).execute()
    except Exception as exc:  # noqa: BLE001 — bookkeeping
        logger.warning("blog_image.persist_rows_failed", extra={"run_id": run_id, "error": str(exc)})


async def run_blog_github_publish_job(job: dict) -> None:
    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    run_id = payload.get("run_id")
    logger.info("blog_github_publish_started", extra={"job_id": job_id, "run_id": run_id})

    def _fail(code: str) -> None:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": code[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

    try:
        run = (
            supabase.table("runs")
            .select("id, client_id, keyword, status, content_type, featured_image_url, created_at, published_at")
            .eq("id", run_id)
            .single()
            .execute()
        ).data
        if not run:
            return _fail("run_not_found")
        if run.get("status") != "complete":
            return _fail("run_not_complete")

        client = (
            supabase.table("clients")
            .select(
                "name, website_url, logo_url, wordpress_site_url, "
                "github_repo, github_branch, github_content_path, github_content_paths, "
                "github_inferred_patterns, business_location, target_cities, gbp"
            )
            .eq("id", run["client_id"])
            .single()
            .execute()
        ).data
        if not client:
            return _fail("client_not_found")

        article = _sources_cited_article(supabase, run_id)
        if not article:
            return _fail("article_not_available")

        seo_title, _h1 = _brief_title_h1(supabase, run_id)
        title = seo_title or f"{run['keyword']} — {client['name']}"
        slug = slugify(run["keyword"])

        # 1–2. Generate images + assemble the markdown that references them.
        result = await image_generation.generate_blog_images(title=title, article=article, slug=slug)

        hero = result.hero
        hero_site_url = hero.site_url if hero else None
        # Frontmatter hero: the committed image's site path if generated, else any
        # manually-attached featured image (bucket URL) already on the run.
        frontmatter_hero = hero_site_url or run.get("featured_image_url")
        hero_preview = hero.preview_url if hero else run.get("featured_image_url")

        schema = _blog_schema(
            supabase, run_id, client=client, run=run, title=title, image_url=hero_preview
        )

        image_files = {s.repo_path: s.data for s in result.committable if s.data}

        # 3. Atomic commit (markdown + all image bytes).
        gh = await publish_blog_with_images_to_github(
            client=client,
            title=title,
            body=result.markdown,
            image_files=image_files,
            slug=run["keyword"],
            content_type=run.get("content_type") or "blog_post",
            hero_image=frontmatter_hero,
            schema=schema,
        )

        # 4. Bookkeeping (best-effort — the commit already landed).
        _persist_images(run_id, result.committable)
        try:
            update = {"published_url": gh.get("html_url"), "published_at": "now()"}
            if hero_preview:
                update["featured_image_url"] = hero_preview
            supabase.table("runs").update(update).eq("id", str(run_id)).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("blog_image.run_update_failed", extra={"run_id": run_id, "error": str(exc)})

        # 5. Close the native "Review & publish" task if one was opened.
        try:
            from services import task_producers

            task_producers.on_run_published(str(run_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("blog_image.task_close_failed", extra={"run_id": run_id, "error": str(exc)})

        supabase.table("async_jobs").update(
            {
                "status": "complete",
                "result": {
                    "path": gh.get("path"),
                    "html_url": gh.get("html_url"),
                    "commit_sha": gh.get("commit_sha"),
                    "image_count": len(image_files),
                    "hero": bool(hero),
                },
                "completed_at": "now()",
            }
        ).eq("id", job_id).execute()
        logger.info(
            "blog_github_publish_complete",
            extra={"job_id": job_id, "run_id": run_id, "images": len(image_files), "path": gh.get("path")},
        )
    except GitHubPublishError as exc:
        logger.warning("blog_github_publish_gh_error", extra={"job_id": job_id, "run_id": run_id, "error": str(exc)})
        _fail(str(exc))
    except Exception as exc:  # noqa: BLE001 — job boundary
        logger.error("blog_github_publish_failed", extra={"job_id": job_id, "run_id": run_id, "error": str(exc)})
        _fail(f"internal_error: {exc}")
