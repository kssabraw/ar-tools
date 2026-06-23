"""Google Docs publishing — shared helper around the Apps Script webhook.

Creates a Google Doc from Markdown in a client's Drive folder. Used by the Blog
Writer publish route and the Maps Local Rank Analysis report. The Apps Script
endpoint takes `{folder_id, title, content}` and returns `{success, doc_id,
doc_url}`.
"""

from __future__ import annotations

import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)


class GoogleDocError(RuntimeError):
    """Raised when the Apps Script webhook is unconfigured or fails."""


async def create_google_doc(folder_id: str, title: str, markdown: str) -> dict:
    """Create a Google Doc in `folder_id`; returns {doc_id, doc_url}.

    Raises GoogleDocError on missing config or a webhook/transport failure so
    callers can map it to their own error envelope (HTTP route vs. async job)."""
    if not settings.google_apps_script_url:
        raise GoogleDocError("publish_not_configured: GOOGLE_APPS_SCRIPT_URL is not set")
    if not folder_id:
        raise GoogleDocError("missing_google_drive_folder_id")

    body = {"folder_id": folder_id, "title": title, "content": markdown}
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
            response = await http.post(settings.google_apps_script_url, json=body)
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error("apps_script_http_error", extra={"status": exc.response.status_code, "body": exc.response.text[:300]})
        raise GoogleDocError("apps_script_http_error") from exc
    except Exception as exc:
        logger.error("apps_script_call_failed", extra={"error": str(exc)})
        raise GoogleDocError(f"apps_script_call_failed: {exc}") from exc

    if not result.get("success"):
        raise GoogleDocError(f"apps_script_returned_error: {result.get('error', 'unknown')}")

    return {"doc_id": result.get("doc_id"), "doc_url": result.get("doc_url")}
