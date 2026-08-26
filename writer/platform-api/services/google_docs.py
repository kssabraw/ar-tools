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

import asyncio
import logging
import secrets

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


async def _apps_script_request_once(body: dict) -> dict:
    """One POST to the Apps Script webhook. Raises httpx errors on transport /
    HTTP failure and GoogleDocError on an app-level success=false / odd body."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
        response = await http.post(settings.google_apps_script_url, json=body)
        response.raise_for_status()
        result = response.json()
    # Validate here so a non-dict/odd body can't AttributeError out uncaught; a
    # legit success=false surfaces as a (non-retryable) app-level error.
    if not isinstance(result, dict) or not result.get("success"):
        err = result.get("error", "unknown") if isinstance(result, dict) else "non_object_response"
        raise GoogleDocError(f"apps_script_returned_error: {err}")
    return result


async def _call_apps_script(body: dict) -> dict:
    """POST `body` to the Apps Script webhook and return the parsed result dict,
    retrying the transient band (5xx + timeouts/transport drops) with backoff.

    Raises GoogleDocError on missing config, an app-level error (success=false —
    not retried, a bad folder won't self-heal), or an exhausted transient failure,
    so callers can map it to their own error envelope (HTTP route vs. async job)."""
    if not settings.google_apps_script_url:
        raise GoogleDocError("publish_not_configured: GOOGLE_APPS_SCRIPT_URL is not set")
    attempt = 0
    while True:
        try:
            return await _apps_script_request_once(body)
        except GoogleDocError:
            raise  # config / success=false / non-object body — not transient
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 or attempt >= settings.google_docs_max_retries:
                logger.error("apps_script_http_error",
                             extra={"status": exc.response.status_code, "body": exc.response.text[:300]})
                raise GoogleDocError("apps_script_http_error") from exc
            last: Exception = exc
        except Exception as exc:  # timeout / transport / decode
            if attempt >= settings.google_docs_max_retries:
                logger.error("apps_script_call_failed", extra={"error": str(exc)})
                raise GoogleDocError(f"apps_script_call_failed: {exc}") from exc
            last = exc
        attempt += 1
        delay = settings.google_docs_retry_base_seconds * (2 ** (attempt - 1)) * (
            0.5 + secrets.randbelow(1000) / 1000.0
        )
        logger.warning("apps_script_transient_retry",
                       extra={"attempt": attempt, "delay_s": round(delay, 1), "error": str(last)[:200]})
        await asyncio.sleep(delay)


async def create_google_doc(
    folder_id: str,
    title: str,
    content: str,
    *,
    content_format: str = "markdown",
    share: str = "private",
    dedupe_by_name: bool = False,
) -> dict:
    """Create a Google Doc in `folder_id`; returns {doc_id, doc_url}.

    `content_format` is "markdown" (default) or "html" — see the module docstring.
    `share` is one of SHARE_MODES — "private" (default, unchanged), "link"
    (anyone with the link can view), or "public" (findable/indexable by search
    engines). Sharing requires a webhook deployment that honours the `share`
    field; older deployments ignore it and the Doc stays private.

    `dedupe_by_name` makes the create idempotent for callers that can be retried
    after an interrupted request: the webhook returns the existing Doc of that
    title in the folder instead of a second copy. Same deployment caveat — an
    older webhook ignores the field and creates as before, so the caller gets
    today's behaviour rather than an error."""
    if not folder_id:
        raise GoogleDocError("missing_google_drive_folder_id")
    body = {
        "folder_id": folder_id,
        "title": title,
        "content": content,
        "format": content_format,
        "share": share if share in SHARE_MODES else "private",
    }
    if dedupe_by_name:
        body["dedupe_by_name"] = True
    result = await _call_apps_script(body)
    return {
        "doc_id": result.get("doc_id"),
        "doc_url": result.get("doc_url"),
        "reused": bool(result.get("reused")),
    }


async def upload_pdf(folder_id: str, title: str, pdf: bytes) -> dict:
    """Save a PDF file into `folder_id`; returns {file_id, file_url}.

    Sends the bytes base64-encoded as `type: "pdf"`. Requires a webhook
    deployment with the PDF branch (see writer/apps-script/publish_webhook.gs).
    An OLD deployment ignores `type` and makes a Doc from the base64 text — we
    treat a missing `file_id` as a hard error (`pdf_not_supported`) so callers
    fail loudly instead of recording a phantom Drive copy."""
    import base64

    if not folder_id:
        raise GoogleDocError("missing_google_drive_folder_id")
    body = {
        "type": "pdf",
        "folder_id": folder_id,
        "title": title,
        "content_base64": base64.b64encode(pdf).decode(),
    }
    result = await _call_apps_script(body)
    file_id = result.get("file_id")
    if not file_id:
        raise GoogleDocError("pdf_not_supported: redeploy the Apps Script webhook (no file_id returned)")
    return {"file_id": file_id, "file_url": result.get("file_url")}


async def create_google_sheet(
    folder_id: str,
    title: str,
    rows: list[list[str]],
    *,
    share: str = "private",
    dedupe_by_name: bool = False,
) -> dict:
    """Create a Google Sheet in `folder_id` from `rows`; returns {sheet_id, sheet_url}.

    `rows` is a list of rows, each a list of cell strings, written top-to-bottom.
    `share` matches create_google_doc. Requires a webhook deployment that handles
    `type: "sheet"` + the Sheets/Drive scopes (see writer/apps-script/
    publish_webhook.gs). An OLD deployment ignores `type` and silently makes a Doc
    instead (no `sheet_id` in the reply); we treat a missing `sheet_id` as a hard
    error (`sheet_not_supported`) so the caller fails loudly rather than recording
    a phantom 'published' Sheet — the signal to redeploy the webhook."""
    if not folder_id:
        raise GoogleDocError("missing_google_drive_folder_id")
    body = {
        "type": "sheet",
        "folder_id": folder_id,
        "title": title,
        "rows": rows,
        "share": share if share in SHARE_MODES else "private",
    }
    if dedupe_by_name:
        body["dedupe_by_name"] = True
    result = await _call_apps_script(body)
    sheet_id = result.get("sheet_id")
    if not sheet_id:
        # success=true but no sheet_id ⇒ the deployed webhook predates the Sheets
        # support and made a Doc. Fail clearly so the item is marked failed.
        raise GoogleDocError("sheet_not_supported: redeploy the Apps Script webhook (no sheet_id returned)")
    return {
        "sheet_id": sheet_id,
        "sheet_url": result.get("sheet_url"),
        "reused": bool(result.get("reused")),
    }
