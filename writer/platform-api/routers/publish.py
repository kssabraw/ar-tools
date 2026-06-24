"""Publish endpoint — creates a Google Doc in the client's Drive folder
via the Apps Script webhook."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth
from services.google_docs import GoogleDocError, create_google_doc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["publish"])


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


@router.post("/runs/{run_id}/publish", response_model=dict)
async def publish_to_google_docs(
    run_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict:
    if not settings.google_apps_script_url:
        raise HTTPException(
            status_code=503,
            detail="publish_not_configured: GOOGLE_APPS_SCRIPT_URL is not set",
        )

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
        .select("name, google_drive_folder_id")
        .eq("id", run["client_id"])
        .single()
        .execute()
    )
    if not client_result.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    client = client_result.data
    folder_id = client.get("google_drive_folder_id")
    if not folder_id:
        raise HTTPException(
            status_code=422,
            detail="missing_google_drive_folder_id: client has no Drive folder configured",
        )

    # Resolve the publishable Markdown from the right module output for the
    # run's content type. Blog posts pull from sources_cited's enriched
    # article; service + location pages pull the service_writer's Markdown
    # rendering (latest attempt — reoptimize adds higher attempts).
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
        markdown = (payload.get("renderings") or {}).get("markdown") or ""
        if not markdown.strip():
            # Fallback: reconstruct from the structured sections.
            markdown = _sections_to_markdown(payload.get("sections") or [])
        if not markdown.strip():
            raise HTTPException(status_code=422, detail="page_is_empty")
    else:
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

    title = f"{run['keyword']} — {client['name']}"
    try:
        result = await create_google_doc(folder_id, title, markdown)
    except GoogleDocError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info(
        "doc_published",
        extra={"run_id": str(run_id), "doc_id": result.get("doc_id"), "user_id": auth["user_id"]},
    )

    return {"success": True, "doc_id": result.get("doc_id"), "doc_url": result.get("doc_url")}
