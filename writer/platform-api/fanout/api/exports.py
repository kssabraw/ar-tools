"""CSV export endpoints (PRD §12).

Generate one of three CSV formats live from current Postgres state, freeze a
snapshot to the private `csv-snapshots` Storage bucket, record it in
`csv_exports`, and return a short-lived signed download URL. Export is in the
§11.2 capability matrix for BOTH roles, so these are `require_user` (not owner-
only) and scoped to sessions the caller can see via RLS (`_require_session`).

Generation is synchronous: a few thousand keyword rows render in well under a
second, so unlike the pipeline this needs no background job (PRD §12 / §15.1).
The CSV content is built by the pure functions in `app.csv_export` (tested with
no egress); only the Storage upload + signed-URL steps (`app.storage.exports`)
are deploy-only.
"""

import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from fanout.auth import AuthedUser, require_user
from fanout.config import get_settings
from fanout.csv_export import (
    build_architecture_csv,
    build_flat_csv,
    build_linking_csv,
    build_topic_grouped_csvs,
    snapshot_timestamp,
    zip_named_csvs,
)
from fanout.logging import bind_session_id
from fanout.storage import exports as export_store
from fanout.storage import silo as store

logger = logging.getLogger(__name__)
router = APIRouter(tags=["exports"])

_FORMATS = ("flat", "topic_grouped", "architecture", "linking")
_EXT_BY_FORMAT = {"flat": "csv", "topic_grouped": "zip", "architecture": "csv", "linking": "csv"}
_CONTENT_TYPE_BY_FORMAT = {
    "flat": "text/csv",
    "topic_grouped": "application/zip",
    "architecture": "text/csv",
    "linking": "text/csv",
}

# Slug rules for the download filename. Non-alnum collapses to a single hyphen,
# the whole thing lowercases, leading/trailing hyphens drop, and we cap at 80
# chars so a pathological seed can't produce a filename the OS rejects.
_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LEN = 80


def _slug_seed(seed: str | None) -> str:
    """Lowercase, hyphenate, length-cap a seed keyword into a filesystem-safe
    slug. Returns "fanout" as a fallback for None / empty / pure-punctuation."""
    if not seed:
        return "fanout"
    slug = _SLUG_NON_ALNUM.sub("-", seed.lower()).strip("-")
    if not slug:
        return "fanout"
    return slug[:_MAX_SLUG_LEN].rstrip("-") or "fanout"


def _require_session(user: AuthedUser, session_id: str) -> dict:
    session = store.session_visible_to_user(user.access_token, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def _download_filename(fmt: str, seed: str | None) -> str:
    """Friendly attachment name handed to Storage at signing time so the browser
    downloads (rather than displays) the file, cross-origin-reliably. Built from
    the seed keyword so the user sees `{seed}-{format}.{ext}` in their downloads
    folder instead of an opaque "fanout-flat.csv"."""
    ext = _EXT_BY_FORMAT.get(fmt, "csv")
    return f"{_slug_seed(seed)}-{fmt}.{ext}"


def _build_payload(session_id: str, fmt: str) -> bytes:
    """Build the CSV/zip bytes for a session in the requested format from current
    Postgres state. Raises HTTP 400 if the format's prerequisite data is absent
    (e.g. an architecture export with no generated architecture)."""
    if fmt in ("flat", "topic_grouped"):
        topic_name = {t["id"]: t["name"] for t in store.list_topics(session_id)}
        keywords = store.list_surviving_keywords(session_id)
        clusters = store.list_clusters(session_id)
        cluster_name = {c["id"]: c["name"] for c in clusters}
        if fmt == "flat":
            return build_flat_csv(keywords, topic_name, cluster_name).encode("utf-8")
        named = build_topic_grouped_csvs(keywords, topic_name, cluster_name)
        return zip_named_csvs(named)

    # architecture / linking — both formats share the architecture fetch + the
    # name-resolution dictionaries, only the builder differs.
    arch = store.get_architecture(session_id)
    if not arch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No site architecture to export. Generate the architecture first.",
        )
    architecture_json = arch.get("architecture_json") or {}
    clusters = store.list_clusters(session_id)
    article_name_by_id = {c["id"]: c["name"] for c in clusters}
    # Pillar title keyed by its silo (topic) id, for parent + lateral resolution.
    pillar_title_by_topic = {
        p.get("topic_id"): (p.get("title") or p.get("silo_name") or "")
        for p in (architecture_json.get("pillars") or [])
    }
    if fmt == "linking":
        return build_linking_csv(
            architecture_json, article_name_by_id, pillar_title_by_topic,
        ).encode("utf-8")
    h2s_by_article = {c["id"]: (c.get("suggested_h2s") or []) for c in clusters}
    # Resolve each article's target keyword (its cluster's primary keyword text).
    primary_ids = [c["primary_keyword_id"] for c in clusters if c.get("primary_keyword_id")]
    kw_texts = store.get_keyword_texts(primary_ids)
    target_kw_by_article = {
        c["id"]: kw_texts.get(c.get("primary_keyword_id") or "", "")
        for c in clusters
    }
    return build_architecture_csv(
        architecture_json,
        article_name_by_id,
        pillar_title_by_topic,
        target_kw_by_article,
        h2s_by_article,
    ).encode("utf-8")


@router.post("/sessions/{session_id}/export")
def create_export(
    session_id: str,
    format: str,
    user: AuthedUser = Depends(require_user),
) -> dict:
    """Generate + snapshot a CSV export and return a signed download URL (PRD §12).
    `format` is one of flat / topic_grouped / architecture. Available to both
    roles (§11.2); scoped to a session the caller can see."""
    if format not in _FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"format must be one of {', '.join(_FORMATS)}.",
        )
    session = _require_session(user, session_id)
    bind_session_id(session_id)

    data = _build_payload(session_id, format)
    ext = _EXT_BY_FORMAT[format]
    content_type = _CONTENT_TYPE_BY_FORMAT[format]
    # Unique object key per snapshot (PRD §12 path shape). The random suffix
    # guards against two concurrent exports landing on the same timestamp and
    # silently overwriting each other's frozen snapshot.
    object_path = f"{user.id}/{session_id}/{snapshot_timestamp()}-{uuid.uuid4().hex[:8]}.{ext}"

    export_store.upload_snapshot(object_path, data, content_type)
    # Record the snapshot; if that fails, remove the just-uploaded object so we
    # don't leave an orphan in Storage with no tracking row.
    try:
        row = export_store.insert_export(session_id, user.id, format, object_path)
    except Exception:
        export_store.remove_object(object_path)
        raise
    download_url = export_store.create_signed_url(
        object_path,
        get_settings().csv_signed_url_ttl_s,
        _download_filename(format, session.get("seed_keyword")),
    )
    logger.info(
        "csv_export_created",
        extra={"event": "csv_export_created", "format": format, "bytes": len(data)},
    )
    return {
        "export_id": row["id"],
        "session_id": session_id,
        "format": format,
        "storage_path": object_path,
        "generated_at": row["generated_at"],
        "download_url": download_url,
    }


class ExportSelectedBody(BaseModel):
    # Hard cap so a runaway client can't ask us to render an arbitrarily large
    # CSV in-request. 10k rows lines up with the per-silo cap × ~10 silos
    # (covers the comprehensive case) and renders well under a second.
    keyword_ids: list[str] = Field(min_length=1, max_length=10000)


@router.post("/sessions/{session_id}/export-selected")
def export_selected(
    session_id: str,
    body: ExportSelectedBody,
    user: AuthedUser = Depends(require_user),
) -> Response:
    """Stream a flat CSV of just the selected keywords (§9.1 bulk action). Unlike
    /export, this is transient: no Storage snapshot, no `csv_exports` row — the
    selection is ad-hoc and the body is returned directly as a downloadable CSV.

    Available to both roles (§11.2 "Export" is checked for both); RLS-scoped to
    a session the caller can see. Stale or cross-session keyword ids silently
    drop (the storage helper filters on session_id), so a selection containing
    an out-of-session id just yields fewer rows rather than 400 — matches how
    the bulk-status helper handles unknown ids."""
    session = _require_session(user, session_id)
    bind_session_id(session_id)

    topic_name = {t["id"]: t["name"] for t in store.list_topics(session_id)}
    keywords = store.list_keywords_by_ids(session_id, body.keyword_ids)
    if not keywords:
        # Selection had ids but none resolved in this session — likely a stale
        # UI selection after a re-gate or move. Surface this clearly rather
        # than handing back a header-only CSV the user can't tell from data.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="None of the selected keywords are still in this session. "
            "Refresh the table and re-select.",
        )
    cluster_name = {c["id"]: c["name"] for c in store.list_clusters(session_id)}
    csv_text = build_flat_csv(keywords, topic_name, cluster_name)
    payload = csv_text.encode("utf-8")
    filename = f"{_slug_seed(session.get('seed_keyword'))}-selected-{snapshot_timestamp()}.csv"
    logger.info(
        "csv_export_selected",
        extra={"event": "csv_export_selected", "rows": len(keywords),
               "requested": len(body.keyword_ids), "bytes": len(payload)},
    )
    return Response(
        content=payload,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Defeat any intermediate caching: the selection is ephemeral.
            "Cache-Control": "no-store",
        },
    )


@router.get("/sessions/{session_id}/exports")
def list_exports(
    session_id: str, user: AuthedUser = Depends(require_user)
) -> list[dict]:
    """Past CSV snapshots for a session, newest first (the Exports tab, PRD §12).
    RLS-scoped: a VA sees only their own sessions' exports."""
    _require_session(user, session_id)
    return export_store.list_exports(user.access_token, session_id)


@router.get("/exports/{export_id}/download")
def download_export(
    export_id: str, user: AuthedUser = Depends(require_user)
) -> dict:
    """Re-issue a fresh signed URL for a past snapshot (PRD §12: snapshots can be
    re-downloaded). RLS-scoped via the user client; a fresh URL is minted each
    time because an old one may have expired."""
    row = export_store.get_export_visible(user.access_token, export_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    # Refetch the parent session for its seed_keyword so the re-issued download
    # name matches the one the user got at create time. RLS-scoped (the user
    # could already see the export so the session is reachable too); on the
    # rare race where the session has been deleted, fall back to the generic
    # "fanout" slug rather than 500ing.
    session = store.session_visible_to_user(user.access_token, row["session_id"])
    seed = (session or {}).get("seed_keyword")
    download_url = export_store.create_signed_url(
        row["storage_path"],
        get_settings().csv_signed_url_ttl_s,
        _download_filename(row["format"], seed),
    )
    return {
        "export_id": row["id"],
        "session_id": row["session_id"],
        "format": row["format"],
        "generated_at": row["generated_at"],
        "download_url": download_url,
    }
