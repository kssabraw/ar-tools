"""Publish endpoint — publishes a finished run to the client's Google Drive
folder (a Google Doc via the Apps Script webhook) or directly to the client's
WordPress site (the WP REST API via an Application Password)."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth
from services.google_docs import GoogleDocError, create_google_doc
from services.markdown_html import markdown_to_html
from services.wordpress_publish import WordPressPublishError, publish_to_wordpress

logger = logging.getLogger(__name__)

router = APIRouter(tags=["publish"])


class PublishRequest(BaseModel):
    # Default keeps the original Google Docs behavior for callers that POST {}.
    destination: Literal["google_docs", "wordpress"] = "google_docs"
    # WordPress only: draft (default, safe) or publish (live).
    status: Literal["draft", "publish"] = "draft"


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


def _resolve_content(supabase, run_id: UUID, content_type: str) -> tuple[str, str]:
    """Return (markdown, html) for the run's publishable content.

    Markdown feeds the Google Docs path; HTML feeds WordPress. Service/location
    pages already carry deterministic Markdown + WordPress(Gutenberg)/HTML
    renderings; blog posts only have Markdown, so HTML is derived from it.
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
        # Prefer the Gutenberg block markup, fall back to semantic HTML, then to
        # markdown-derived HTML.
        html = renderings.get("wordpress") or renderings.get("html") or ""
        if not html.strip():
            html = markdown_to_html(markdown)
        return markdown, html

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
    return markdown, markdown_to_html(markdown)


@router.post("/runs/{run_id}/publish", response_model=dict)
async def publish_run(
    run_id: UUID,
    body: PublishRequest = PublishRequest(),
    auth: dict = Depends(require_auth),
) -> dict:
    supabase = get_supabase()

    run_result = (
        supabase.table("runs")
        .select("id, client_id, keyword, status, content_type")
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
            "name, google_drive_folder_id, "
            "wordpress_site_url, wordpress_username, wordpress_app_password"
        )
        .eq("id", run["client_id"])
        .single()
        .execute()
    )
    if not client_result.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    client = client_result.data

    markdown, html = _resolve_content(supabase, run_id, content_type)
    title = f"{run['keyword']} — {client['name']}"

    if body.destination == "wordpress":
        try:
            result = await publish_to_wordpress(
                client=client,
                title=title,
                html=html,
                status=body.status,
                content_type=content_type,
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

    # Google Docs (default).
    if not settings.google_apps_script_url:
        raise HTTPException(
            status_code=503,
            detail="publish_not_configured: GOOGLE_APPS_SCRIPT_URL is not set",
        )
    folder_id = client.get("google_drive_folder_id")
    if not folder_id:
        raise HTTPException(
            status_code=422,
            detail="missing_google_drive_folder_id: client has no Drive folder configured",
        )
    try:
        result = await create_google_doc(folder_id, title, markdown)
    except GoogleDocError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

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
