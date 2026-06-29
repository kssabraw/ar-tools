"""Publish HTML content into a linked AR Tools client's Google Drive folder via
the suite's shared Apps Script webhook (`services.google_docs`).

This is the bridge that lets Fanout content publish exactly like the rest of the
suite — into the *client's* configured Drive folder, using the creds already live
for the blog writer / Local SEO pages — instead of Fanout's per-session
Drive-OAuth path. Fanout is mounted inside platform-api, so importing the suite
service here is safe (the suite never imports fanout).

Used by the per-article "Save to Drive" endpoint and by the scheduler's opt-in
auto-publish-on-completion.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resolve_client_folder(client_id: str, content_type: str = "blog_post") -> str | None:
    """The client's Drive folder for `content_type` (type-specific folder, else the
    default), or None when the client has none configured."""
    from services.google_docs import resolve_drive_folder
    from fanout.writer.publish.client_targets import resolve_client_publish_targets

    drive = (resolve_client_publish_targets(client_id).get("drive")) or {}
    client_view = {
        "google_drive_folder_id": drive.get("folder_id"),
        "drive_folders": drive.get("folders") or {},
    }
    return resolve_drive_folder(client_view, content_type)


async def publish_html_to_client_drive(
    client_id: str, title: str, html: str, *, content_type: str = "blog_post"
) -> dict | None:
    """Create a Google Doc from `html` in the client's Drive folder. Returns the
    Fanout-shaped {doc_id, url} on success, or None when the client has no Drive
    folder configured (the caller decides whether to fall back). Raises
    `services.google_docs.GoogleDocError` on a webhook/transport failure."""
    from services.google_docs import create_google_doc

    folder_id = resolve_client_folder(client_id, content_type)
    if not folder_id:
        return None
    res = await create_google_doc(folder_id, title, html, content_format="html")
    # Normalize the suite's {doc_id, doc_url} to Fanout's {doc_id, url}.
    return {"doc_id": res.get("doc_id"), "url": res.get("doc_url")}
