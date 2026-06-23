"""Save an article to Google Drive as a Google Doc (OAuth-as-user). Personal Gmail has no
Shared Drives, so a service account can't own files there — we act on the owner's behalf via a
long-lived OAuth refresh token (scope `drive.file` = only files this app creates). The article
HTML is converted to a Google Doc by Drive's import, so it opens formatted. Dormant until the
OAuth creds are set."""

from __future__ import annotations

import logging

from fanout.config import get_settings

logger = logging.getLogger(__name__)

_TOKEN_URI = "https://oauth2.googleapis.com/token"
_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DrivePublishError(RuntimeError):
    """A Drive save failed / isn't configured — the API maps it to a clear error."""


def _service():
    """Build a Drive v3 client from the OAuth refresh token (lazy imports keep the google libs
    out of the import path until used)."""
    s = get_settings()
    if not (s.google_oauth_client_id and s.google_oauth_client_secret and s.google_oauth_refresh_token):
        raise DrivePublishError("Google Drive saving isn't configured on the server (no OAuth refresh token).")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None, refresh_token=s.google_oauth_refresh_token,
        client_id=s.google_oauth_client_id, client_secret=s.google_oauth_client_secret,
        token_uri=_TOKEN_URI, scopes=_SCOPES,
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def create_doc_from_html(*, name: str, html: str, folder_id: str | None = None) -> dict:
    """Convert article HTML into a Google Doc in the user's Drive (optionally in `folder_id`).
    Returns {doc_id, url}. Raises DrivePublishError on failure."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaInMemoryUpload

    service = _service()
    body: dict = {"name": name or "Article", "mimeType": "application/vnd.google-apps.document"}
    if folder_id:
        body["parents"] = [folder_id]
    media = MediaInMemoryUpload((html or "").encode("utf-8"), mimetype="text/html", resumable=False)
    try:
        f = (service.files().create(body=body, media_body=media,
                                    fields="id, webViewLink", supportsAllDrives=True).execute())
    except HttpError as exc:
        raise DrivePublishError(f"Drive create failed ({exc.status_code}): {exc.reason}") from exc
    except Exception as exc:  # noqa: BLE001 — surface auth/refresh failures as a clean error
        raise DrivePublishError(f"Drive create failed: {exc}") from exc
    return {"doc_id": f.get("id"), "url": f.get("webViewLink")}
