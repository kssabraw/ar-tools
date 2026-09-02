"""Local SEO matrix — the drip release schedule (plan §5.2, Phase 4).

Publish an immediate batch, then release N more cells per day / week / month
until the matrix is filled. Mirrors the Website Builder's release schedule
(`services/website_release.py`) and REUSES its pure cadence helpers —
`normalize_anchors`, `next_run_after`, `advance` — rather than re-deriving
calendar math; the only new pure code maps between the matrix's `release_*`
columns and the shape those helpers speak.

Each release GENERATES then PUBLISHES its cells just-in-time: it enqueues the
same `local_seo_generate` job as the immediate run, with `publish_after` set,
so no page is generated ahead of its slot and every page still clears the
freeze + quality gates. Two rules keep it correct (as in the Website Builder):

  * **A cell is released exactly once.** `released_at` is the claim, stamped
    BEFORE the job is enqueued, so a manual "Generate now" and a scheduled
    release can't both pick a cell in the window before its job finishes. A
    released cell whose job FAILS keeps its claim — the drip must not loop on
    a persistent failure — and is re-run by hand from the grid (`failed` is
    runnable there).
  * **Location-major order.** `core.select_release_batch` walks every service
    for one location before the next, so a location's silo completes sooner and
    its sibling links resolve earlier.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import local_seo_matrix as core
from services import local_seo_matrix_store as store
from services.freeze import is_frozen
from services.website_release import VALID_MODES, advance, next_run_after, normalize_anchors

logger = logging.getLogger(__name__)

# ── pure ──────────────────────────────────────────────────────────────────────

# matrix column ↔ the key `website_release.advance` reads / writes.
_COLUMN_FOR = {
    "mode": "release_mode",
    "weekday": "release_weekday",
    "day_of_month": "release_day_of_month",
    "status": "release_status",
    "next_run_at": "release_next_run_at",
    "last_run_at": "release_last_run_at",
}


def schedule_of(matrix: dict) -> dict:
    """The matrix's schedule in the shape the shared cadence helpers read."""
    return {
        "mode": matrix.get("release_mode") or "daily",
        "weekday": matrix.get("release_weekday"),
        "day_of_month": matrix.get("release_day_of_month"),
    }


def to_matrix_patch(patch: dict) -> dict:
    """Map an `advance`-style patch (`status` / `next_run_at` / `last_run_at` …)
    onto the matrix's `release_*` columns."""
    return {_COLUMN_FOR.get(k, k): v for k, v in patch.items()}


def schedule_view(matrix: dict) -> dict:
    """The schedule as the API returns it."""
    return {
        "enabled": bool(matrix.get("release_enabled")),
        "mode": matrix.get("release_mode") or "daily",
        "weekday": matrix.get("release_weekday"),
        "day_of_month": matrix.get("release_day_of_month"),
        "per_release_count": int(matrix.get("release_per_count") or 1),
        "status": matrix.get("release_status") or "active",
        "next_run_at": matrix.get("release_next_run_at"),
        "last_run_at": matrix.get("release_last_run_at"),
    }


def releasable_count(cells: Iterable[dict]) -> int:
    """How many cells a release could still claim: runnable and unclaimed."""
    cells = list(cells)
    return len(core.select_release_batch(cells, len(cells)))


def validate_body(body: dict, now: datetime) -> dict:
    """Normalise a schedule request → the column values to store. Raises
    ValueError('invalid_release_mode') on a bad mode."""
    mode = (body.get("mode") or "daily").strip().lower()
    if mode not in VALID_MODES:
        raise ValueError("invalid_release_mode")
    weekday, day_of_month = normalize_anchors(mode, body.get("weekday"), body.get("day_of_month"), now)
    return {
        "release_enabled": bool(body.get("enabled", True)),
        "release_mode": mode,
        "release_weekday": weekday,
        "release_day_of_month": day_of_month,
        "release_per_count": max(1, int(body.get("per_release_count") or 1)),
        "release_status": "active",
        "release_next_run_at": next_run_after(mode, weekday, day_of_month, now).isoformat(),
    }


# ── impure ────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _patch_matrix(matrix_id: str, patch: dict) -> None:
    get_supabase().table("local_seo_matrices").update({**patch, "updated_at": "now()"}).eq(
        "id", matrix_id
    ).execute()


def get_release(matrix_id: str, client_id: str) -> dict:
    matrix = store._matrix_row(matrix_id, client_id)
    store.reconcile(matrix_id)
    return {"schedule": schedule_view(matrix), "releasable": releasable_count(store._cells(matrix_id)), "released_now": []}


def run_release(matrix_id: str, client_id: str, count: int, user_id: str) -> dict:
    """Claim + enqueue (generate → publish) the next `count` cells. Returns
    ``{released: [cell ids], remaining}``. Refuses for a frozen client."""
    if is_frozen(client_id):
        raise HTTPException(status_code=409, detail="client_frozen")
    matrix = store._matrix_row(matrix_id, client_id)
    store.reconcile(matrix_id)
    cells = store._cells(matrix_id)
    batch = core.select_release_batch(cells, count)
    if not batch:
        return {"released": [], "remaining": releasable_count(cells)}

    ids = [c["id"] for c in batch]
    now_iso = _now().isoformat()
    get_supabase().table("local_seo_matrix_cells").update(
        {"released_at": now_iso, "updated_at": "now()"}
    ).in_("id", ids).execute()
    for c in batch:
        c["released_at"] = now_iso

    store.enqueue_cells(matrix, batch, cells, user_id, publish_after=True)
    # The batch cells carry their claim in memory now, so they're already excluded.
    remaining = releasable_count(cells)
    logger.info(
        "local_seo_matrix.released",
        extra={"matrix_id": matrix_id, "count": len(ids), "remaining": remaining},
    )
    return {"released": ids, "remaining": remaining}


def set_release(matrix_id: str, client_id: str, body: dict, user_id: str) -> dict:
    """Create/replace the schedule and fire the immediate batch. If nothing is
    left after that batch the schedule is recorded complete rather than ticking
    against an empty grid."""
    matrix = store._matrix_row(matrix_id, client_id)
    now = _now()
    try:
        columns = validate_body(body, now)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _patch_matrix(matrix_id, columns)

    released: list[str] = []
    immediate = max(0, int(body.get("immediate_count") or 0))
    if columns["release_enabled"] and immediate > 0:
        result = run_release(matrix_id, client_id, immediate, user_id or matrix.get("created_by") or "")
        released = result["released"]
        if result["remaining"] <= 0:
            _patch_matrix(matrix_id, to_matrix_patch(advance(schedule_of({**matrix, **columns}), 0, now)))

    fresh = store._matrix_row(matrix_id, client_id)
    return {"schedule": schedule_view(fresh), "releasable": releasable_count(store._cells(matrix_id)), "released_now": released}


def clear_release(matrix_id: str, client_id: str) -> dict:
    """Stop the drip. Cells already released keep going; nothing new is enqueued."""
    store._matrix_row(matrix_id, client_id)
    _patch_matrix(matrix_id, {"release_enabled": False, "release_status": "paused", "release_next_run_at": None})
    return {"deleted": True}


def enqueue_due_matrix_releases() -> int:
    """Shared-scheduler tick: release the per-tick batch for every due matrix.
    Self-gated on `local_seo_matrix_enabled`; a frozen client's matrix is skipped
    (the freeze pauses content creation) and re-tried next tick; a matrix that
    empties its grid is marked complete via the shared `advance`."""
    if not settings.local_seo_matrix_enabled:
        return 0
    now = _now()
    due = (
        get_supabase()
        .table("local_seo_matrices")
        .select(store._MATRIX_COLS)
        .eq("release_enabled", True)
        .eq("release_status", "active")
        .lte("release_next_run_at", now.isoformat())
        .execute()
        .data
        or []
    )
    fired = 0
    for matrix in due:
        matrix_id, client_id = matrix["id"], matrix["client_id"]
        if is_frozen(client_id):
            logger.info("local_seo_matrix.release_skipped_frozen", extra={"matrix_id": matrix_id})
            continue
        try:
            result = run_release(
                matrix_id, client_id, int(matrix.get("release_per_count") or 1),
                matrix.get("created_by") or "",
            )
            _patch_matrix(matrix_id, to_matrix_patch(advance(schedule_of(matrix), result["remaining"], now)))
            fired += 1
        except Exception as exc:  # noqa: BLE001 — one bad matrix must not stop the sweep
            logger.warning(
                "local_seo_matrix.release_tick_failed",
                extra={"matrix_id": matrix_id, "error": str(exc)[:200]},
            )
    return fired


__all__ = [
    "schedule_of", "to_matrix_patch", "schedule_view", "releasable_count", "validate_body",
    "get_release", "run_release", "set_release", "clear_release", "enqueue_due_matrix_releases",
]

# Re-exported for callers that want the cadence helpers from one place.
_ = (Optional,)
