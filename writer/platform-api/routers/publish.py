"""Publish endpoint — publishes a finished run to the client's Google Drive
folder (a Google Doc via the Apps Script webhook) or directly to the client's
WordPress site (the WP REST API via an Application Password)."""

from __future__ import annotations

import logging
from html import escape
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth
from services.blog_jsonld import (
    build_blog_jsonld,
    faqs_from_article,
    inline_jsonld_script,
)
from services.github_publish import GitHubPublishError, publish_to_github
from services.google_docs import GoogleDocError, create_google_doc, resolve_drive_folder
from services.markdown_html import markdown_to_gutenberg, markdown_to_html
from services.wordpress_publish import WordPressPublishError, publish_to_wordpress

logger = logging.getLogger(__name__)

router = APIRouter(tags=["publish"])


class PublishRequest(BaseModel):
    # Default keeps the original Google Docs behavior for callers that POST {}.
    destination: Literal["google_docs", "wordpress", "github"] = "google_docs"
    # WordPress only: draft (default, safe) or publish (live).
    status: Literal["draft", "publish"] = "draft"


class FeaturedImageRequest(BaseModel):
    # The public wordpress_images URL to attach, or null/empty to clear it.
    url: Optional[str] = None


@router.put("/runs/{run_id}/featured-image", response_model=dict)
async def set_run_featured_image(
    run_id: UUID,
    body: FeaturedImageRequest,
    auth: dict = Depends(require_auth),
) -> dict:
    """Attach (or clear) a run's featured/hero image."""
    supabase = get_supabase()
    result = (
        supabase.table("runs")
        .update({"featured_image_url": body.url or None})
        .eq("id", str(run_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="run_not_found")
    return {"featured_image_url": body.url or None}


@router.get("/runs/{run_id}/github-publish/status", response_model=dict)
async def github_publish_status(
    run_id: UUID,
    job_id: str,
    auth: dict = Depends(require_auth),
) -> dict:
    """Poll a blog GitHub-publish job (image generation + atomic commit)."""
    supabase = get_supabase()
    row = (
        supabase.table("async_jobs")
        .select("id, status, result, error")
        .eq("id", job_id)
        .eq("entity_id", str(run_id))
        .single()
        .execute()
    )
    if not row.data:
        raise HTTPException(status_code=404, detail="job_not_found")
    return {
        "job_id": job_id,
        "status": row.data.get("status"),
        "result": row.data.get("result"),
        "error": row.data.get("error"),
    }


@router.get("/runs/{run_id}/images", response_model=dict)
async def list_run_images(run_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """The images generated for a run (for the review UI)."""
    supabase = get_supabase()
    rows = (
        supabase.table("run_images")
        .select("id, role, kind, position, anchor_heading, alt, preview_url, repo_path, status")
        .eq("run_id", str(run_id))
        .order("role")
        .order("position")
        .execute()
    ).data or []
    return {"images": rows}


def _sections_to_markdown(article: list[dict]) -> str:
    """Reconstruct markdown from the sources_cited enriched_article sections."""
    if not isinstance(article, list):
        return ""
    sections = sorted(
        [s for s in article if isinstance(s, dict)],
        key=lambda s: s.get("order", 0),
    )
    parts = []
    for s in sections:
        heading = s.get("heading") or ""
        body = s.get("body") or ""
        if heading:
            parts.append(f"## {heading}\n\n{body}")
        else:
            parts.append(body)
    return "\n\n".join(parts)


def _resolve_content(supabase, run_id: UUID, content_type: str) -> tuple[str, str, str | None]:
    """Return (doc_html, wp_html, seo_title) for the run's publishable content.

    `doc_html` is semantic HTML (headings/paragraphs/lists/tables) for the Google
    Docs path — the Apps Script imports it as a natively-formatted Doc that
    copy-pastes into WordPress. `wp_html` is the WordPress body: Gutenberg block
    markup so the post lands as native, editable blocks. `seo_title` is the page's
    own SEO title where the rendering carries one (service/location pages), else
    None (blog posts source their title from the brief).
    """
    if content_type in ("service_page", "location_page"):
        sw_result = (
            supabase.table("module_outputs")
            .select("output_payload, attempt_number")
            .eq("run_id", str(run_id))
            .eq("module", "service_writer")
            .eq("status", "complete")
            .order("attempt_number", desc=True)
            .execute()
        )
        rows = sw_result.data or []
        if not rows:
            raise HTTPException(status_code=422, detail="page_not_available")
        payload = rows[0].get("output_payload") or {}
        renderings = payload.get("renderings") or {}
        markdown = renderings.get("markdown") or ""
        if not markdown.strip():
            markdown = _sections_to_markdown(payload.get("sections") or [])
        if not markdown.strip():
            raise HTTPException(status_code=422, detail="page_is_empty")
        # Docs get semantic HTML; WordPress gets the native Gutenberg rendering.
        doc_html = renderings.get("html") or markdown_to_html(markdown)
        wp_html = renderings.get("wordpress") or renderings.get("html") or markdown_to_html(markdown)
        seo_title = (payload.get("title") or "").strip() or None
        return doc_html, wp_html, seo_title

    sc_result = (
        supabase.table("module_outputs")
        .select("output_payload")
        .eq("run_id", str(run_id))
        .eq("module", "sources_cited")
        .eq("status", "complete")
        .execute()
    )
    rows = sc_result.data or []
    if not rows:
        raise HTTPException(status_code=422, detail="article_not_available")
    payload = rows[0].get("output_payload") or {}
    article = (payload.get("enriched_article") or {}).get("article") or []
    markdown = _sections_to_markdown(article)
    if not markdown.strip():
        raise HTTPException(status_code=422, detail="article_is_empty")
    return markdown_to_html(markdown), markdown_to_gutenberg(markdown), None


def _resolve_blog_title_h1(supabase, run_id: UUID) -> tuple[str | None, str | None]:
    """SEO title + on-page H1 from the Brief Generator output (v2.0 Step 3.5).

    These are deliberately separate: `title` is the SEO/meta title (browser tab,
    SERP, and the WordPress slug); `h1` is the visible on-page main heading.
    Either may be None when the brief didn't populate it."""
    res = (
        supabase.table("module_outputs")
        .select("output_payload, attempt_number")
        .eq("run_id", str(run_id))
        .eq("module", "brief")
        .eq("status", "complete")
        .order("attempt_number", desc=True)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None, None
    p = rows[0].get("output_payload") or {}
    title = (p.get("title") or "").strip() or None
    h1 = (p.get("h1") or "").strip() or None
    return title, h1


def _resolve_markdown(supabase, run_id: UUID, content_type: str) -> str:
    """The run's content as Markdown (for the GitHub content-file body)."""
    if content_type in ("service_page", "location_page"):
        rows = (
            supabase.table("module_outputs")
            .select("output_payload, attempt_number")
            .eq("run_id", str(run_id)).eq("module", "service_writer").eq("status", "complete")
            .order("attempt_number", desc=True).execute()
        ).data or []
        if not rows:
            return ""
        payload = rows[0].get("output_payload") or {}
        renderings = payload.get("renderings") or {}
        return renderings.get("markdown") or _sections_to_markdown(payload.get("sections") or [])

    rows = (
        supabase.table("module_outputs")
        .select("output_payload").eq("run_id", str(run_id))
        .eq("module", "sources_cited").eq("status", "complete").execute()
    ).data or []
    if not rows:
        return ""
    article = ((rows[0].get("output_payload") or {}).get("enriched_article") or {}).get("article") or []
    return _sections_to_markdown(article)


def _resolve_schema(supabase, run_id: UUID, content_type: str) -> str:
    """The run's JSON-LD (@graph string) for service / location pages, read from
    the `schema_jsonld` the service_writer output carries. Blog posts build their
    BlogPosting + FAQPage graph at publish time via `_resolve_blog_schema`."""
    if content_type not in ("service_page", "location_page"):
        return ""
    rows = (
        supabase.table("module_outputs")
        .select("output_payload, attempt_number")
        .eq("run_id", str(run_id)).eq("module", "service_writer").eq("status", "complete")
        .order("attempt_number", desc=True).execute()
    ).data or []
    if not rows:
        return ""
    return (rows[0].get("output_payload") or {}).get("schema_jsonld") or ""


def _resolve_blog_faqs(supabase, run_id: UUID) -> list[dict[str, str]]:
    """The blog post's FAQ question/answer pairs (for the FAQPage node), read
    from the sources_cited enriched article — the same source `_resolve_content`
    reads for the body."""
    rows = (
        supabase.table("module_outputs")
        .select("output_payload").eq("run_id", str(run_id))
        .eq("module", "sources_cited").eq("status", "complete").execute()
    ).data or []
    if not rows:
        return []
    article = ((rows[0].get("output_payload") or {}).get("enriched_article") or {}).get("article") or []
    return faqs_from_article(article)


def _iso_date(value: str | None) -> str | None:
    """The date portion (YYYY-MM-DD) of a Supabase ISO timestamp, or None."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    return value[:10]


def _resolve_blog_schema(
    supabase,
    run_id: UUID,
    *,
    client: dict,
    run: dict,
    title: str,
    image_url: str | None,
) -> str:
    """Build the blog post's BlogPosting + FAQPage JSON-LD @graph.

    Deterministic, publish-time: title/FAQs come from the run's module outputs,
    publisher/site from the client, dates from the run (published_at falls back to
    created_at; dateModified is today)."""
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    date_published = _iso_date(run.get("published_at")) or _iso_date(run.get("created_at")) or today
    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else {}
    # sameAs: link the brand to its known profiles (the Google Business Profile).
    same_as = [u for u in [gbp.get("google_maps_uri")] if u and str(u).strip()]
    return build_blog_jsonld(
        title=title,
        faqs=_resolve_blog_faqs(supabase, run_id),
        brand_name=client.get("name") or "",
        # Prefer the client's canonical website; the WP site is only a fallback, so
        # a post published to Astro/GitHub (no WP URL) still gets a brand URL/@id.
        site_url=client.get("website_url") or client.get("wordpress_site_url") or "",
        logo_url=client.get("logo_url") or gbp.get("logo") or None,
        same_as=same_as or None,
        telephone=gbp.get("phone") or None,
        image_url=image_url,
        date_published=date_published,
        date_modified=today,
    )


@router.post("/runs/{run_id}/publish", response_model=dict)
async def publish_run(
    run_id: UUID,
    body: PublishRequest = PublishRequest(),
    auth: dict = Depends(require_auth),
) -> dict:
    supabase = get_supabase()

    run_result = (
        supabase.table("runs")
        .select("id, client_id, keyword, status, content_type, featured_image_url, created_at, published_at")
        .eq("id", str(run_id))
        .single()
        .execute()
    )
    if not run_result.data:
        raise HTTPException(status_code=404, detail="run_not_found")
    run = run_result.data
    content_type = run.get("content_type") or "blog_post"

    if run["status"] != "complete":
        raise HTTPException(status_code=409, detail="run_not_complete")

    client_result = (
        supabase.table("clients")
        .select(
            "name, google_drive_folder_id, drive_folders, website_url, logo_url, "
            "wordpress_site_url, wordpress_username, wordpress_app_password, "
            "github_repo, github_branch, github_content_path, github_content_paths, "
            "github_inferred_patterns, business_location, target_cities, gbp"
        )
        .eq("id", run["client_id"])
        .single()
        .execute()
    )
    if not client_result.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    client = client_result.data

    doc_html, wp_html, page_seo_title = _resolve_content(supabase, run_id, content_type)
    fallback_title = f"{run['keyword']} — {client['name']}"
    # WordPress post title + optional SEOPress meta title, resolved per type.
    wp_post_title = fallback_title
    wp_seo_title: str | None = None
    if content_type in ("service_page", "location_page"):
        # Service/location pages carry their own H1 inside their rendering, so we
        # only set the post title here (no body-H1 injection), using the page's
        # own SEO title when present.
        title = page_seo_title or fallback_title
        wp_post_title = title
    else:
        # Blog posts: the on-page H1 becomes the WordPress post title (the theme
        # renders it as the visible <h1>) and the distinct SEO title is routed to
        # SEOPress's meta-title field, so the <title> tag differs from the H1.
        seo_title, h1 = _resolve_blog_title_h1(supabase, run_id)
        # Document title (Docs / GitHub): prefer the SEO title, else the fallback.
        title = seo_title or fallback_title
        wp_post_title = h1 or seo_title or fallback_title
        wp_seo_title = seo_title
        # The Google Doc has no separate title/H1 concept, so inject the H1 as a
        # heading at the top of the doc body. The WP body gets no injected H1 —
        # the post title supplies the page's heading (avoids a duplicate H1).
        if h1:
            doc_html = f"<h1>{escape(h1)}</h1>\n{doc_html}"
    featured_image_url = run.get("featured_image_url")

    # Structured data (JSON-LD @graph). Service/location pages carry their own in
    # the service_writer output; blog posts get a BlogPosting + FAQPage graph built
    # here at publish time. Threaded to GitHub (frontmatter) and WordPress (an
    # inline <script>); the Google Docs path omits it (Docs strips <script>).
    if content_type == "blog_post":
        schema_jsonld = _resolve_blog_schema(
            supabase, run_id,
            client=client, run=run, title=title, image_url=featured_image_url,
        )
    else:
        schema_jsonld = _resolve_schema(supabase, run_id, content_type)

    if body.destination == "wordpress":
        # Append the JSON-LD as an inline <script> at the end of the body. Note:
        # WordPress keeps <script> in post content only for users with the
        # `unfiltered_html` capability (administrators on single-site); on a
        # locked-down/multisite install KSES may strip it, in which case the
        # site's SEO plugin schema still applies.
        if schema_jsonld:
            wp_html = f"{wp_html}\n{inline_jsonld_script(schema_jsonld)}"
        try:
            result = await publish_to_wordpress(
                client=client,
                title=wp_post_title,
                seo_title=wp_seo_title,
                strip_leading_h1=True,
                html=wp_html,
                status=body.status,
                content_type=content_type,
                featured_image_url=featured_image_url,
            )
        except WordPressPublishError as exc:
            # Client-fixable config/validation errors are 422; upstream/transport
            # failures are 502.
            client_errors = {
                "wordpress_not_configured",
                "invalid_wordpress_site_url",
                "wordpress_site_url_must_be_https",
                "invalid_status",
                "content_is_empty",
                # Site-side REST breakage the user fixes on their WordPress install
                # (permalinks / an intercepting plugin) — actionable, not our fault.
                "wordpress_rest_not_json",
                "wordpress_rest_redirect",
            }
            status = 422 if str(exc) in client_errors else 502
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        # Persist the site URL so the content lists can show a durable "published
        # to website" badge (best-effort — the post is already live, so a failed
        # write must not fail the publish).
        try:
            supabase.table("runs").update({
                "published_url": result.get("link"),
                "published_at": "now()",
            }).eq("id", str(run_id)).execute()
        except Exception as exc:  # noqa: BLE001 — non-fatal bookkeeping
            logger.warning("wp_publish_persist_failed", extra={"run_id": str(run_id), "error": str(exc)})
        # Close the native "Review & publish" task, if the producer opened one.
        from services import task_producers

        task_producers.on_run_published(str(run_id))
        logger.info(
            "wordpress_published",
            extra={
                "run_id": str(run_id),
                "post_id": result.get("post_id"),
                "status": result.get("status"),
                "user_id": auth["user_id"],
            },
        )
        return {
            "success": True,
            "destination": "wordpress",
            "post_id": result.get("post_id"),
            "url": result.get("link"),
            "edit_url": result.get("edit_link"),
            "status": result.get("status"),
        }

    if body.destination == "github":
        # Blog posts publish through an async job that generates a hero + body
        # images with gpt-image-1 and commits the markdown + image bytes to the
        # repo in one commit — too slow to hang the request. Service/location
        # pages (no generated images) keep the synchronous single-file commit.
        use_async_images = (
            content_type == "blog_post"
            and settings.blog_image_generation_enabled
            and bool(settings.openai_api_key)
            and bool(settings.github_publish_token)
        )
        if use_async_images:
            if not (client.get("github_repo") or "").strip():
                raise HTTPException(status_code=422, detail="github_repo_not_set")
            from services.blog_image_publish import enqueue_blog_github_publish

            job_id = enqueue_blog_github_publish(str(run_id), auth["user_id"])
            logger.info(
                "github_publish_enqueued",
                extra={"run_id": str(run_id), "job_id": job_id, "user_id": auth["user_id"]},
            )
            return {
                "success": True,
                "destination": "github",
                "status": "generating",
                "job_id": job_id,
            }

        markdown = _resolve_markdown(supabase, run_id, content_type)
        if not markdown.strip():
            raise HTTPException(status_code=422, detail="content_is_empty")
        try:
            result = await publish_to_github(
                client=client, title=title, body=markdown, slug=run["keyword"],
                content_type=content_type, hero_image=featured_image_url,
                schema=schema_jsonld,
            )
        except GitHubPublishError as exc:
            client_errors = {"github_not_configured", "github_repo_not_set", "content_is_empty"}
            code = 422 if str(exc) in client_errors else 502
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        logger.info(
            "github_published",
            extra={"run_id": str(run_id), "path": result.get("path"), "user_id": auth["user_id"]},
        )
        return {
            "success": True,
            "destination": "github",
            "url": result.get("html_url"),
            "path": result.get("path"),
        }

    # Google Docs (default).
    if not settings.google_apps_script_url:
        raise HTTPException(
            status_code=503,
            detail="publish_not_configured: GOOGLE_APPS_SCRIPT_URL is not set",
        )
    folder_id = resolve_drive_folder(client, content_type)
    if not folder_id:
        raise HTTPException(
            status_code=422,
            detail="missing_google_drive_folder_id: client has no Drive folder configured",
        )
    # Send semantic HTML (not markdown) so the Apps Script builds a natively-
    # formatted Doc that copy-pastes cleanly into WordPress. Render the hero image
    # at the top of the doc (WordPress handles it as the post's featured image
    # instead, so it's only injected on the Docs path).
    if featured_image_url:
        doc_html = f'<p><img src="{escape(featured_image_url, quote=True)}" /></p>\n{doc_html}'
    try:
        result = await create_google_doc(folder_id, title, doc_html, content_format="html")
    except GoogleDocError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Persist the publish target so the UI can show an "already published" badge +
    # a link to the Doc (best-effort — the Doc already exists, so a failed write
    # must not fail the publish).
    try:
        supabase.table("runs").update({
            "published_doc_id": result.get("doc_id"),
            "published_doc_url": result.get("doc_url"),
            "published_at": "now()",
        }).eq("id", str(run_id)).execute()
    except Exception as exc:  # noqa: BLE001 — non-fatal bookkeeping
        logger.warning("doc_publish_persist_failed", extra={"run_id": str(run_id), "error": str(exc)})
    # Close the native "Review & publish" task, if the producer opened one.
    from services import task_producers

    task_producers.on_run_published(str(run_id))

    logger.info(
        "doc_published",
        extra={"run_id": str(run_id), "doc_id": result.get("doc_id"), "user_id": auth["user_id"]},
    )
    return {
        "success": True,
        "destination": "google_docs",
        "doc_id": result.get("doc_id"),
        "doc_url": result.get("doc_url"),
    }
