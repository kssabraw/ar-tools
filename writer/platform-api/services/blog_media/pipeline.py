"""Media pipeline orchestration (Phase 1): the async job that turns a completed
blog run into an images-enriched GitHub commit.

Flow (app-owned end to end):
  assemble article Markdown → assign stable IDs + build the anchor index →
  media plan (model proposes) → app-side validate → render hero + inline images
  (gpt-image-2 → WebP) → resolve placements → insert <figure> blocks
  idempotently → commit Markdown + image bytes atomically → record per-asset
  states.

Resilient throughout: an invalid/failed hero falls back to the client hero image
(Option B); a failed/unresolvable inline asset is dropped; nothing blocks the
publish. Charts are deferred to Phase 2 (validation drops them).
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from config import settings
from db.supabase_client import get_supabase
from services.blog_jsonld import build_blog_jsonld, faqs_from_article
from services.blog_media import article_html as ah
from services.blog_media.charts import render_chart_svg, validate_chart_spec
from services.blog_media.planner import plan_media
from services.blog_media.render import render_image, upload_preview, upload_svg_preview
from services.blog_media.validate import validate_and_clean
from services.blog_media.visual_profile import extract_brand_personality
from services.github_publish import (
    GitHubPublishError,
    publish_blog_with_images_to_github,
    slugify,
)

logger = logging.getLogger(__name__)


def enqueue_blog_media_publish(run_id: str, user_id: str | None = None) -> str:
    """Queue the media-publish job (reuses the blog_github_publish job type).
    Reuses an already-pending job for the run if present."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "blog_github_publish").eq("entity_id", run_id).eq("status", "pending")
        .limit(1).execute()
    )
    if existing.data:
        return existing.data[0]["id"]
    row = (
        supabase.table("async_jobs").insert({
            "job_type": "blog_github_publish", "entity_id": run_id,
            "payload": {"run_id": run_id, "user_id": user_id},
        }).execute()
    )
    return row.data[0]["id"]


def _sources_cited_article(supabase, run_id: str) -> list[dict]:
    rows = (
        supabase.table("module_outputs").select("output_payload")
        .eq("run_id", run_id).eq("module", "sources_cited").eq("status", "complete").execute()
    ).data or []
    if not rows:
        return []
    return ((rows[0].get("output_payload") or {}).get("enriched_article") or {}).get("article") or []


def _article_markdown(article: list[dict]) -> str:
    """Reconstruct the post Markdown from the sources_cited sections."""
    parts: list[str] = []
    for s in sorted((x for x in article if isinstance(x, dict)), key=lambda s: s.get("order", 0)):
        heading = (s.get("heading") or "").strip()
        body = (s.get("body") or "").rstrip()
        if heading:
            parts.append(f"## {heading}\n\n{body}".rstrip())
        elif body:
            parts.append(body)
    return "\n\n".join(p for p in parts if p).strip() + "\n"


def _brief_seo_title(supabase, run_id: str) -> str | None:
    rows = (
        supabase.table("module_outputs").select("output_payload, attempt_number")
        .eq("run_id", run_id).eq("module", "brief").eq("status", "complete")
        .order("attempt_number", desc=True).execute()
    ).data or []
    if not rows:
        return None
    return ((rows[0].get("output_payload") or {}).get("title") or "").strip() or None


def _plain_text(markdown: str) -> str:
    text = re.sub(r"<[^>]+>", " ", markdown or "")
    text = re.sub(r"[*_`#>|]", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def _site_url(repo_path: str) -> str:
    p = repo_path.lstrip("/")
    return "/" + (p[len("public/"):] if p.startswith("public/") else p)


def _iso_date(v) -> str | None:
    return v[:10] if isinstance(v, str) and len(v) >= 10 else None


def _blog_schema(supabase, run_id, *, client, run, title, image_url) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    date_published = _iso_date(run.get("published_at")) or _iso_date(run.get("created_at")) or today
    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else {}
    same_as = [u for u in [gbp.get("google_maps_uri")] if u and str(u).strip()]
    return build_blog_jsonld(
        title=title, faqs=faqs_from_article(_sources_cited_article(supabase, run_id)),
        brand_name=client.get("name") or "",
        site_url=client.get("website_url") or client.get("wordpress_site_url") or "",
        logo_url=client.get("logo_url") or gbp.get("logo") or None,
        same_as=same_as or None, telephone=gbp.get("phone") or None,
        image_url=image_url, date_published=date_published, date_modified=today,
    )


def _record_assets(run_id: str, rows: list[dict]) -> None:
    supabase = get_supabase()
    try:
        supabase.table("blog_media_assets").delete().eq("run_id", run_id).execute()
        if rows:
            supabase.table("blog_media_assets").insert(rows).execute()
    except Exception as exc:  # noqa: BLE001 — bookkeeping
        logger.warning("blog_media.record_assets_failed", extra={"run_id": run_id, "error": str(exc)})


async def run_blog_media_publish_job(job: dict) -> None:
    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    run_id = payload.get("run_id")
    logger.info("blog_media_publish_started", extra={"job_id": job_id, "run_id": run_id})

    def _fail(code: str) -> None:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": code[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

    try:
        run = (
            supabase.table("runs")
            .select("id, client_id, keyword, status, content_type, featured_image_url, created_at, published_at, published_url")
            .eq("id", run_id).single().execute()
        ).data
        if not run:
            return _fail("run_not_found")
        if run.get("status") != "complete":
            return _fail("run_not_complete")

        client = (
            supabase.table("clients").select(
                "name, website_url, logo_url, wordpress_site_url, github_repo, github_branch, "
                "github_content_path, github_content_paths, github_inferred_patterns, "
                "business_location, target_cities, gbp, brand_voice, blog_hero_fallback_url"
            ).eq("id", run["client_id"]).single().execute()
        ).data
        if not client:
            return _fail("client_not_found")

        article = _sources_cited_article(supabase, run_id)
        if not article:
            return _fail("article_not_available")

        markdown = _article_markdown(article)

        # Article-revision cost control: if this run was already published with
        # media from the identical article TO THE SAME repo/branch, short-circuit
        # — no re-render, no new paid image calls. A changed article OR a changed
        # publish target yields a new hash → regenerate (so a client migrating
        # repos still gets a real commit).
        target_repo = (client.get("github_repo") or "").strip()
        target_branch = (client.get("github_branch") or settings.github_default_branch or "main").strip()
        content_hash = hashlib.sha256(
            f"{target_repo}@{target_branch}\n{markdown}".encode("utf-8")
        ).hexdigest()
        prev = (
            supabase.table("blog_media_assets").select("content_hash")
            .eq("run_id", run_id).eq("status", "inserted").limit(1).execute()
        ).data or []
        if prev and prev[0].get("content_hash") == content_hash and run.get("published_at"):
            logger.info("blog_media_publish_reused", extra={"job_id": job_id, "run_id": run_id})
            supabase.table("async_jobs").update({
                "status": "complete",
                # Carry the existing publish link so the UI still shows/opens it.
                "result": {"reused": True, "reason": "article_unchanged",
                           "html_url": run.get("published_url")},
                "completed_at": "now()",
            }).eq("id", job_id).execute()
            return

        blocks = ah.assign_ids(ah.parse_blocks(markdown))
        idx = ah.build_id_index(blocks)
        html_with_ids = ah.render_html_with_ids(blocks)
        words = ah.word_count(markdown)
        budget = ah.inline_budget(words)

        title = _brief_seo_title(supabase, run_id) or f"{run['keyword']} — {client['name']}"
        slug = slugify(run["keyword"])
        base = settings.blog_media_repo_path

        # Plan (best-effort — degrade to hero-only on failure). The plain text is
        # kept for chart-quote validation: quotes must be checked against the
        # exact view the model copied them from.
        plain_text = _plain_text(markdown)
        try:
            plan = await plan_media(
                article_title=title, article_html=html_with_ids,
                article_plain_text=plain_text, word_count=words,
                brand_personality=extract_brand_personality(client.get("brand_voice")),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("blog_media.plan_failed", extra={"run_id": run_id, "error": str(exc)})
            plan = {}

        vr = validate_and_clean(
            plan, idx=idx, max_inline=budget, allow_charts=True,
            hero_min=settings.blog_media_hero_min_confidence,
            inline_min=settings.blog_media_inline_min_confidence,
            chart_min=settings.blog_media_chart_min_confidence,
        )

        image_files: dict[str, bytes] = {}
        asset_rows: list[dict] = []

        # ── Hero (Option B resilient) ─────────────────────────────────────────
        hero_site_url: str | None = None
        hero_preview: str | None = None
        used_fallback = False
        hero = vr.hero
        if hero:
            data = await render_image(
                hero["prompt"], width=hero.get("width") or settings.blog_media_hero_width,
                height=hero.get("height") or settings.blog_media_hero_height,
            )
            if data:
                repo_path = f"{base}/{slug}/{hero['filename']}"
                image_files[repo_path] = data
                hero_site_url = _site_url(repo_path)
                hero_preview = upload_preview(data, hero["filename"])
                asset_rows.append(_asset_row(run_id, hero, status="inserted", repo_path=repo_path,
                                             preview_url=hero_preview, used_fallback=False))
        if hero_site_url is None:
            # Fallback image (never a broken hero); may be None if unconfigured.
            fallback = (client.get("blog_hero_fallback_url") or "").strip() or None
            if fallback:
                hero_site_url = fallback
                hero_preview = fallback
                used_fallback = True
            asset_rows.append(_asset_row(run_id, hero or {"asset_id": "hero"},
                                         status="failed" if not fallback else "skipped",
                                         repo_path=None, preview_url=hero_preview, used_fallback=used_fallback,
                                         error=None if fallback else "hero_render_failed_no_fallback"))

        # ── Inline assets (images + charts) ───────────────────────────────────
        figures: list[ah.ResolvedFigure] = []
        for asset in vr.inline:
            # Resolve placement first — never pay to render/build an asset that
            # cannot be inserted (addendum: verify anchor before generation).
            pos = ah.resolve_placement(asset["placement"], blocks, idx, markdown)
            if pos is None:
                asset_rows.append(_asset_row(run_id, asset, status="skipped", skip_reason="placement_unresolved"))
                continue

            if asset["asset_type"] == "chart":
                chart = asset["chart"]
                # Validate against the SAME plain-text view the planner received
                # (the model copies source_quotes from ARTICLE_PLAIN_TEXT; raw
                # markdown carries <sup> citation HTML that would false-fail
                # quotes spanning a citation).
                ok, reason = validate_chart_spec(
                    chart, article_text=plain_text,
                    allow_derived=settings.blog_media_allow_derived_values,
                )
                # Targeted recovery: a chart dropped ONLY because a value's quote
                # was left blank (e.g. a number stated only in a table) gets one
                # re-grounding pass, then is re-validated the same way — never a
                # weakened rule, just a second chance to cite existing data.
                if not ok and reason == "missing_source_quote" and settings.blog_media_chart_reground_enabled:
                    regrounded = await _reground_chart(chart, plain_text)
                    if regrounded is not None:
                        ok2, reason2 = validate_chart_spec(
                            regrounded, article_text=plain_text,
                            allow_derived=settings.blog_media_allow_derived_values,
                        )
                        if ok2:
                            chart, ok, reason = regrounded, True, None
                        else:
                            reason = f"{reason}>reground:{reason2}"
                if not ok:
                    asset_rows.append(_asset_row(
                        run_id, {**asset, "chart": chart}, status="skipped", skip_reason=f"chart:{reason}"))
                    continue
                svg = render_chart_svg(chart)
                repo_path = f"{base}/{slug}/{asset['filename']}"
                image_files[repo_path] = svg.encode("utf-8")
                preview = upload_svg_preview(svg, asset["filename"])
                css_class = "article-chart"
                asset = {**asset, "chart": chart}  # persist the grounded spec
            else:
                data = await render_image(
                    asset["prompt"], width=asset.get("width") or settings.blog_media_inline_width,
                    height=asset.get("height") or settings.blog_media_inline_height,
                )
                if not data:
                    asset_rows.append(_asset_row(run_id, asset, status="failed", error="render_failed"))
                    continue
                repo_path = f"{base}/{slug}/{asset['filename']}"
                image_files[repo_path] = data
                preview = upload_preview(data, asset["filename"])
                css_class = "article-inline-image"

            figures.append(ah.ResolvedFigure(
                block_index=pos,
                position=(asset["placement"].get("position") or "after"),
                media_id=asset["asset_id"],
                markup=ah.figure_markdown(
                    media_id=asset["asset_id"], src=_site_url(repo_path),
                    alt=asset["alt"], caption=asset["caption"], css_class=css_class,
                ),
            ))
            asset_rows.append(_asset_row(run_id, asset, status="inserted", repo_path=repo_path, preview_url=preview))

        body_markdown = ah.insert_figures(markdown, blocks, figures)
        schema = _blog_schema(supabase, run_id, client=client, run=run, title=title, image_url=hero_preview)

        # Stale-image cleanup: previously-committed asset files this republish no
        # longer references are deleted in the same commit (best-effort inside
        # the commit — rejected deletions never fail the publish).
        try:
            prior_rows = (
                supabase.table("blog_media_assets").select("repo_path")
                .eq("run_id", run_id).eq("status", "inserted").execute()
            ).data or []
        except Exception:  # noqa: BLE001 — cleanup is optional
            prior_rows = []
        stale_paths = [
            r["repo_path"] for r in prior_rows
            if r.get("repo_path") and r["repo_path"] not in image_files
        ]

        gh = await publish_blog_with_images_to_github(
            client=client, title=title, body=body_markdown, image_files=image_files,
            slug=run["keyword"], content_type=run.get("content_type") or "blog_post",
            hero_image=hero_site_url, schema=schema, delete_paths=stale_paths,
        )

        for r in asset_rows:
            r["content_hash"] = content_hash
        _record_assets(run_id, asset_rows)
        try:
            upd = {"published_url": gh.get("html_url"), "published_at": "now()"}
            if hero_preview:
                upd["featured_image_url"] = hero_preview
            supabase.table("runs").update(upd).eq("id", str(run_id)).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("blog_media.run_update_failed", extra={"run_id": run_id, "error": str(exc)})
        try:
            from services import task_producers
            task_producers.on_run_published(str(run_id))
        except Exception:  # noqa: BLE001
            pass

        supabase.table("async_jobs").update({
            "status": "complete",
            "result": {
                "path": gh.get("path"), "html_url": gh.get("html_url"), "commit_sha": gh.get("commit_sha"),
                "hero": bool(hero_site_url), "hero_fallback": used_fallback,
                "inline": len(figures), "warnings": vr.warnings,
            },
            "completed_at": "now()",
        }).eq("id", job_id).execute()
        _notify(
            run["client_id"],
            kind="blog_published",
            title=f"Blog post published to GitHub: {run['keyword']}",
            summary=(
                f"{len(figures)} inline visual(s), hero "
                + ("via fallback image" if used_fallback else ("generated" if hero_site_url else "omitted"))
                + f" — {gh.get('path')}"
            ),
            severity="info",
            payload={"url": gh.get("html_url"), "run_id": str(run_id)},
            dedupe_key=f"blog_published:{job_id}",
        )
        logger.info("blog_media_publish_complete",
                    extra={"job_id": job_id, "run_id": run_id, "inline": len(figures), "hero_fallback": used_fallback})
    except GitHubPublishError as exc:
        logger.warning("blog_media_publish_gh_error", extra={"job_id": job_id, "run_id": run_id, "error": str(exc)})
        _fail(str(exc))
        _notify_failure(run_id, str(exc), job_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("blog_media_publish_failed", extra={"job_id": job_id, "run_id": run_id, "error": str(exc)})
        _fail(f"internal_error: {exc}")
        _notify_failure(run_id, "internal_error", job_id)


async def _reground_chart(chart: dict, article_plain: str) -> dict | None:
    """One targeted re-grounding pass for a chart dropped on `missing_source_quote`.

    Asks the planner model to return the EXACT verbatim article sentence/table row
    that states each unquoted value. The result is merged back (pure `apply_quotes`)
    and RE-VALIDATED by the caller — so a fabricated or wrong quote is still
    rejected. Returns the updated chart, or None on any failure (caller keeps the
    original skip). Never raises."""
    from services import report_llm
    from services.blog_media.charts import apply_quotes, missing_quote_labels, points
    from services.blog_media.planner import parse_plan_json

    labels = set(missing_quote_labels(chart))
    if not labels:
        return None
    value_lines = [
        f'- "{str(d.get("label") or d.get("date") or "")}": value {d.get("display_value") or d.get("value")}'
        for d in points(chart)
        if str(d.get("label") or d.get("date") or "") in labels
    ]
    system = (
        "You attach source evidence to chart values. For each value, return the "
        "EXACT verbatim sentence or table row from the article that states that "
        "value — quoted character-for-character, never paraphrased or invented. "
        "If the article does not state a value anywhere, return an empty string for it."
    )
    user = (
        f"ARTICLE:\n{article_plain}\n\nVALUES NEEDING A VERBATIM SOURCE QUOTE:\n"
        + "\n".join(value_lines)
        + '\n\nReturn ONLY JSON mapping each label to its verbatim quote: '
        '{"<label>": "<verbatim quote>", ...}'
    )
    try:
        raw = await report_llm.generate_text(
            provider="anthropic", model=settings.blog_media_planner_model,
            system=system, user=user, max_tokens=1500, log_tag="blog_media_chart_reground",
        )
        quotes = parse_plan_json(raw)
        if not isinstance(quotes, dict):
            return None
        return apply_quotes(chart, {str(k): str(v) for k, v in quotes.items() if v})
    except Exception as exc:  # noqa: BLE001 — best-effort recovery
        logger.warning("blog_media.chart_reground_failed", extra={"error": str(exc)})
        return None


def _notify(client_id, **kwargs) -> None:
    """Best-effort notification through the shared service (in-app + Slack)."""
    try:
        from services import notifications

        notifications.emit(str(client_id) if client_id else None, **kwargs)
    except Exception as exc:  # noqa: BLE001 — never break the publish over a ping
        logger.warning("blog_media.notify_failed", extra={"error": str(exc)})


def _notify_failure(run_id, code: str, job_id: str) -> None:
    """Failure notification (best-effort; resolves client_id itself since the
    failure may have occurred before the run row was loaded)."""
    try:
        supabase = get_supabase()
        row = (
            supabase.table("runs").select("client_id, keyword").eq("id", run_id).single().execute()
        ).data or {}
        _notify(
            row.get("client_id"),
            kind="blog_publish_failed",
            title=f"GitHub publish failed: {row.get('keyword') or run_id}",
            summary=f"Reason: {code}. Re-publish from the run page to retry.",
            severity="warning",
            payload={"run_id": str(run_id)},
            dedupe_key=f"blog_publish_failed:{job_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("blog_media.notify_failed", extra={"error": str(exc)})


def _asset_row(run_id: str, asset: dict, *, status: str, repo_path: str | None = None,
               preview_url: str | None = None, used_fallback: bool = False,
               error: str | None = None, skip_reason: str | None = None) -> dict:
    return {
        "run_id": run_id,
        "asset_id": asset.get("asset_id") or "hero",
        "role": asset.get("role") or ("hero" if (asset.get("asset_id") == "hero") else "inline"),
        "asset_type": asset.get("asset_type") or "image",
        "status": status,
        "placement": asset.get("placement"),
        "concept": asset.get("concept"),
        "prompt": asset.get("prompt"),
        "alt_text": asset.get("alt"),
        "caption": asset.get("caption"),
        "filename": asset.get("filename"),
        "repo_path": repo_path,
        "preview_url": preview_url,
        "width": asset.get("width"),
        "height": asset.get("height"),
        "model": settings.blog_media_image_model,
        "confidence": asset.get("confidence"),
        "used_fallback": used_fallback,
        "error": error,
        "skip_reason": skip_reason,
        # Audit trail: the chart spec (values + the source_quotes the model
        # supplied) so a skip is inspectable without re-running the planner.
        "plan": asset.get("chart"),
    }
