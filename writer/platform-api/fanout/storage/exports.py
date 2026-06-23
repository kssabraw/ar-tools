"""Supabase Storage + `csv_exports` table operations for CSV export (PRD §12).

This is the thin, separately-mockable I/O layer that sits under the pure CSV
builders in `app.csv_export`. The Storage upload + signed-URL calls here CANNOT
be exercised in the sandbox (no Supabase egress) — they are validated only on
the deployed stack. The CSV *content* is generated + tested upstream.

Snapshots live in the private `csv-snapshots` bucket under the object key
`{user_id}/{session_id}/{timestamp}.{ext}` (PRD §12 path shape; the bucket name
is the `csv-snapshots` prefix). Downloads are served via a short-lived signed URL
the backend mints with the service role — the frontend never touches Storage
directly (CLAUDE.md "no browser storage APIs for app data").
"""

from __future__ import annotations

import logging

from fanout.config import get_settings
from fanout.storage.supabase_client import get_service_client, get_user_client

logger = logging.getLogger(__name__)

BUCKET = "csv-snapshots"

# Columns returned to the API for the Exports tab.
_EXPORT_COLS = "id, session_id, user_id, format, storage_path, generated_at"


def upload_snapshot(object_path: str, data: bytes, content_type: str) -> None:
    """Write a frozen snapshot to the private bucket via the service client. The
    object key is unique (timestamped) so this never collides; upsert is set so a
    retry on the same key is idempotent rather than erroring. Deploy-only path."""
    get_service_client().storage.from_(BUCKET).upload(
        path=object_path,
        file=data,
        file_options={"content-type": content_type, "upsert": "true"},
    )


def create_signed_url(
    object_path: str, expires_in: int, download_name: str | None = None
) -> str:
    """Mint a time-limited signed download URL for a snapshot (PRD §12: "served
    from Storage"). Re-issued fresh on every download (an old URL may have
    expired). When `download_name` is given, Storage stamps the response with a
    `Content-Disposition: attachment; filename=…` so the browser downloads rather
    than displays — set server-side at signing time so it holds cross-origin.
    Normalizes the storage3 response shape across versions and resolves a relative
    path against the project URL. Deploy-only path."""
    bucket = get_service_client().storage.from_(BUCKET)
    if download_name:
        res = bucket.create_signed_url(object_path, expires_in, {"download": download_name})
    else:
        res = bucket.create_signed_url(object_path, expires_in)
    url = None
    if isinstance(res, dict):
        url = res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
    if not url:
        raise RuntimeError("Storage did not return a signed URL")
    if url.startswith("/"):
        url = get_settings().supabase_url.rstrip("/") + url
    return url


def remove_object(object_path: str) -> None:
    """Best-effort delete of a snapshot object (used to clean up after a failed
    export so Storage doesn't accumulate orphans). Swallows errors — the caller is
    already handling a failure and a leftover object is harmless. Deploy-only."""
    try:
        get_service_client().storage.from_(BUCKET).remove([object_path])
    except Exception as exc:  # noqa: BLE001 — cleanup is best-effort
        logger.warning(
            "csv_snapshot_cleanup_failed",
            extra={"event": "csv_snapshot_cleanup_failed", "reason": repr(exc)},
        )


def insert_export(
    session_id: str, user_id: str, fmt: str, storage_path: str
) -> dict:
    """Record a snapshot in `csv_exports` (PRD §12 / §13). Service client — the
    API has already verified the caller owns the session (RLS would also allow
    it). Returns the inserted row for the Exports tab."""
    res = (
        get_service_client()
        .table("csv_exports")
        .insert(
            {
                "session_id": session_id,
                "user_id": user_id,
                "format": fmt,
                "storage_path": storage_path,
            }
        )
        .execute()
    )
    return res.data[0]


def list_exports(access_token: str, session_id: str) -> list[dict]:
    """Past snapshots for a session, newest first (the Exports tab, PRD §12).
    User-scoped client so RLS enforces visibility — a VA sees only their own
    sessions' exports, the Owner sees all (PRD §13)."""
    res = (
        get_user_client(access_token)
        .table("csv_exports")
        .select(_EXPORT_COLS)
        .eq("session_id", session_id)
        .order("generated_at", desc=True)
        .execute()
    )
    return res.data or []


def get_export_visible(access_token: str, export_id: str) -> dict | None:
    """Fetch a single export row if RLS lets the caller see it, else None. Used by
    the re-download path to re-sign a fresh URL for a past snapshot (PRD §12)."""
    res = (
        get_user_client(access_token)
        .table("csv_exports")
        .select(_EXPORT_COLS)
        .eq("id", export_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None
