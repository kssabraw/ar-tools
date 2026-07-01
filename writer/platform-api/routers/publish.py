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


@router.post("/runs/{run_id}/publish", response_model=dict)
async def publish_run(
    run_id: UUID,
    body: PublishRequest = PublishRequest(),
    auth: dict = Depends(require_auth),
) -> dict:
    supabase = get_supabase()

    run_result = (
        supabase.table("runs")
        .select("id, client_id, keyword, status, content_type, featured_image_url")
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
            "name, google_drive_folder_id, drive_folders, "
            "wordpress_site_url, wordpress_username, wordpress_app_password, "
            "github_repo, github_branch, github_content_path"
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
    if content_type in ("service_page", "location_page"):
        # Service/location pages carry their own H1 inside their rendering, so we
        # only set the post title here (no body-H1 injection), using the page's
        # own SEO title when present.
        title = page_seo_title or fallback_title
    else:
        # Blog posts: the SEO title becomes the WordPress post title (and the
        # meta <title> + slug); the distinct on-page H1 is injected at the top of
        # each body so it renders as the visible heading, separate from the title.
        seo_title, h1 = _resolve_blog_title_h1(supabase, run_id)
        title = seo_title or fallback_title
        if h1:
            heading = escape(h1)
            doc_html = f"<h1>{heading}</h1>\n{doc_html}"
            wp_html = (
                f'<!-- wp:heading {{"level":1}} -->\n<h1>{heading}</h1>\n'
                f"<!-- /wp:heading -->\n\n{wp_html}"
            )
    featured_image_url = run.get("featured_image_url")

    if body.destination == "wordpress":
        try:
            result = await publish_to_wordpress(
                client=client,
                title=title,
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
            }
            status = 422 if str(exc) in client_errors else 502
            raise HTTPException(status_code=status, detail=str(exc)) from exc
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
        markdown = _resolve_markdown(supabase, run_id, content_type)
        if not markdown.strip():
            raise HTTPException(status_code=422, detail="content_is_empty")
        try:
            result = await publish_to_github(
                client=client, title=title, body=markdown, slug=run["keyword"],
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
