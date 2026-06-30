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
    default — so a client with no per-type config still publishes everywhere.

    Values are stripped; a blank/whitespace-only or non-string entry is treated
    as unset (falls through to the default, then to None) so a malformed value
    can't be sent to the webhook as a bogus folder ID."""
    folders = client.get("drive_folders")
    if content_type and isinstance(folders, dict):
        specific = folders.get(content_type)
        if isinstance(specific, str) and specific.strip():
            return specific.strip()
    default = client.get("google_drive_folder_id")
    if isinstance(default, str) and default.strip():
        return default.strip()
    return None


# Valid `share` values understood by the Apps Script webhook. "private" keeps the
# legacy behaviour (no sharing change); "link" = anyone with the link can view;
# "public" = anyone on the internet can find + view (search-discoverable).
SHARE_MODES = ("private", "link", "public")


async def _call_apps_script(body: dict) -> dict:
    """POST `body` to the Apps Script webhook and return the parsed result dict.

    Raises GoogleDocError on missing config or a webhook/transport failure so
    callers can map it to their own error envelope (HTTP route vs. async job)."""
    if not settings.google_apps_script_url:
        raise GoogleDocError("publish_not_configured: GOOGLE_APPS_SCRIPT_URL is not set")
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
    return result


async def create_google_doc(
    folder_id: str,
    title: str,
    content: str,
    *,
    content_format: str = "markdown",
    share: str = "private",
) -> dict:
    """Create a Google Doc in `folder_id`; returns {doc_id, doc_url}.

    `content_format` is "markdown" (default) or "html" — see the module docstring.
    `share` is one of SHARE_MODES — "private" (default, unchanged), "link"
    (anyone with the link can view), or "public" (findable/indexable by search
    engines). Sharing requires a webhook deployment that honours the `share`
    field; older deployments ignore it and the Doc stays private."""
    if not folder_id:
        raise GoogleDocError("missing_google_drive_folder_id")
    body = {
        "folder_id": folder_id,
        "title": title,
        "content": content,
        "format": content_format,
        "share": share if share in SHARE_MODES else "private",
    }
    result = await _call_apps_script(body)
    return {"doc_id": result.get("doc_id"), "doc_url": result.get("doc_url")}


async def create_google_sheet(
    folder_id: str,
    title: str,
    rows: list[list[str]],
    *,
    share: str = "private",
) -> dict:
    """Create a Google Sheet in `folder_id` from `rows`; returns {sheet_id, sheet_url}.

    `rows` is a list of rows, each a list of cell strings, written top-to-bottom.
    `share` matches create_google_doc. Requires a webhook deployment that handles
    `type: "sheet"` + the Sheets/Drive scopes (see writer/apps-script/
    publish_webhook.gs); older deployments raise apps_script_returned_error."""
    if not folder_id:
        raise GoogleDocError("missing_google_drive_folder_id")
    body = {
        "type": "sheet",
        "folder_id": folder_id,
        "title": title,
        "rows": rows,
        "share": share if share in SHARE_MODES else "private",
    }
    result = await _call_apps_script(body)
    return {"sheet_id": result.get("sheet_id"), "sheet_url": result.get("sheet_url")}
