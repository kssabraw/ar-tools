"""Google Docs publishing — shared helper around the Apps Script webhook.

Creates a Google Doc in a client's Drive folder. Used by the Blog Writer publish
route, the Local SEO page publish, and the Maps/rank reports. The Apps Script
endpoint takes `{folder_id, title, content, format}` and returns `{success,
doc_id, doc_url}`.

`format` is `"markdown"` (default) or `"html"`. The HTML format makes the Apps
Script build the Doc with **native** Google Docs formatting (real heading
styles, bold runs, bullet/numbered lists, hyperlinks) via Drive's HTML import,
so the content modules' Docs copy-paste cleanly into the WordPress block editor.
Reports keep the default markdown format (they don't need WordPress paste), so
older Apps Script deployments that ignore `format` stay unaffected.
"""

from __future__ import annotations

import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)


class GoogleDocError(RuntimeError):
    """Raised when the Apps Script webhook is unconfigured or fails."""


def resolve_drive_folder(client: dict, content_type: str | None) -> str | None:
    """Pick the Drive folder a piece of content publishes into.

    Clients carry a per-content-type folder map (`drive_folders`, keyed by
    content_type slug) plus a single default folder (`google_drive_folder_id`).
    Return the type-specific folder when one is set, otherwise fall back to the
    default — so a client with no per-type config still publishes everywhere."""
    folders = client.get("drive_folders")
    if content_type and isinstance(folders, dict):
        specific = folders.get(content_type)
        if specific:
            return specific
    return client.get("google_drive_folder_id")


async def create_google_doc(
    folder_id: str, title: str, content: str, *, content_format: str = "markdown"
) -> dict:
    """Create a Google Doc in `folder_id`; returns {doc_id, doc_url}.

    `content_format` is "markdown" (default) or "html" — see the module docstring.
    Raises GoogleDocError on missing config or a webhook/transport failure so
    callers can map it to their own error envelope (HTTP route vs. async job)."""
    if not settings.google_apps_script_url:
        raise GoogleDocError("publish_not_configured: GOOGLE_APPS_SCRIPT_URL is not set")
    if not folder_id:
        raise GoogleDocError("missing_google_drive_folder_id")

    body = {"folder_id": folder_id, "title": title, "content": content, "format": content_format}
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
            response = await http.post(settings.google_apps_script_url, json=body)
            response.raise_for_status()
            result = response.json()
        # Validate inside the try so a non-dict/odd body can't AttributeError out
        # uncaught; a legit success=false is re-raised below without re-wrapping.
        if not isinstance(result, dict) or not result.get("success"):
            err = result.get("error", "unknown") if isinstance(result, dict) else "non_object_response"
            raise GoogleDocError(f"apps_script_returned_error: {err}")
    except GoogleDocError:
        raise
    except httpx.HTTPStatusError as exc:
        logger.error("apps_script_http_error", extra={"status": exc.response.status_code, "body": exc.response.text[:300]})
        raise GoogleDocError("apps_script_http_error") from exc
    except Exception as exc:
        logger.error("apps_script_call_failed", extra={"error": str(exc)})
        raise GoogleDocError(f"apps_script_call_failed: {exc}") from exc

    return {"doc_id": result.get("doc_id"), "doc_url": result.get("doc_url")}
