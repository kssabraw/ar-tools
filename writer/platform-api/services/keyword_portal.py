"""Unified Keyword Portal — fan one keyword list out to the three trackers.

Enter keywords once → add them to the organic rank tracker (`tracked_keywords`),
the Maps geo-grid keyword set (`maps_keywords`), and the AI-Visibility / brand
keyword set (`brand_tracked_keywords`) in a single call, deduping per tracker,
and (optionally) kick off the first scans. Each target is isolated: a failure or
"blocked" state in one tracker never aborts the others (best-effort,
degraded-note — the suite's standing pattern).

Behaviour per target:
  - organic — upsert keywords; new keywords always start the standard backfill
    (GSC materialize + market data), mirroring the rank tracker's own add path.
  - maps    — upsert keywords; on run_scans, trigger a grid scan *iff* the grid
    is configured (else `scan="blocked"`, blocker="maps_not_configured"). The
    keywords are added regardless.
  - brand   — bulk-add new keywords; on run_scans, scan only the *new* keywords
    across all six engines (avoids redundant paid calls on tracked terms).

Phase 1 / PR1 of the managed-engagement build plan.
"""

from __future__ import annotations

import logging
import re

from db.supabase_client import get_supabase
from services import brand_service, keyword_market, local_dominator, rank_materialize

logger = logging.getLogger("keyword_portal")

VALID_TARGETS = ("organic", "maps", "brand")


# ── pure helpers (independently unit-tested) ─────────────────────────────────
def split_keywords(raw: list[str]) -> list[str]:
    """Split a bulk payload on newlines/commas, trim, dedupe (first-seen), drop blanks."""
    seen: dict[str, None] = {}
    for chunk in raw:
        for part in re.split(r"[\n,]+", chunk):
            kw = part.strip()
            if kw:
                seen.setdefault(kw, None)
    return list(seen)


def partition_new(keywords: list[str], existing_lower: set[str]) -> tuple[list[str], int]:
    """Split requested keywords into (new, skipped_count) vs existing (lowercased)."""
    new = [k for k in keywords if k.strip().lower() not in existing_lower]
    return new, len(keywords) - len(new)


def _result(added: int, skipped: int, scan: str = "n/a", blocker: str | None = None) -> dict:
    return {"added": added, "skipped_duplicates": skipped, "scan": scan, "blocker": blocker}


def _existing_lower(table: str, client_id: str) -> set[str]:
    rows = (
        get_supabase().table(table).select("keyword").eq("client_id", client_id).execute().data
        or []
    )
    return {(r.get("keyword") or "").strip().lower() for r in rows}


# ── per-target adders ────────────────────────────────────────────────────────
def add_to_organic(client_id: str, keywords: list[str], user_id: str | None, run_scans: bool) -> dict:
    new, skipped = partition_new(keywords, _existing_lower("tracked_keywords", client_id))
    if not new:
        return _result(0, skipped, "skipped")
    payload = [
        {"client_id": client_id, "keyword": kw, "source": "gsc", "created_by": user_id}
        for kw in new
    ]
    get_supabase().table("tracked_keywords").upsert(
        payload, on_conflict="client_id,keyword", ignore_duplicates=True
    ).execute()
    # Organic's "scan" is the standard backfill (GSC materialize + market data),
    # always started on add — mirrors routers/rank.py::add_keywords.
    rank_materialize.enqueue_materialize(client_id)
    keyword_market.enqueue_keyword_market(client_id)
    return _result(len(new), skipped, "enqueued")


def add_to_maps(client_id: str, keywords: list[str], run_scans: bool) -> dict:
    new, skipped = partition_new(keywords, _existing_lower("maps_keywords", client_id))
    if new:
        rows = [{"client_id": client_id, "keyword": kw} for kw in new]
        get_supabase().table("maps_keywords").upsert(
            rows, on_conflict="client_id,keyword", ignore_duplicates=True
        ).execute()
    if not run_scans:
        return _result(len(new), skipped, "skipped")
    # Trigger a scan only when the grid is configured — same gate as
    # routers/maps.py::run_scan. Keywords were added regardless.
    cfg = (
        get_supabase().table("maps_scan_configs")
        .select("google_place_id, center_lat, center_lng")
        .eq("client_id", client_id).limit(1).execute().data
    )
    c = cfg[0] if cfg else None
    if not c or not c.get("google_place_id") or c.get("center_lat") is None or c.get("center_lng") is None:
        return _result(len(new), skipped, "blocked", "maps_not_configured")
    local_dominator.enqueue_maps_scan(client_id, trigger="manual")
    return _result(len(new), skipped, "enqueued")


def add_to_brand(client_id: str, keywords: list[str], user_id: str | None, run_scans: bool) -> dict:
    created = brand_service.add_keywords(client_id, keywords)
    added = len(created)
    skipped = len(keywords) - added
    if not added or not run_scans:
        return _result(added, skipped, "skipped")
    # Scan only the newly-added keywords (all six engines) to avoid redundant
    # paid calls on already-tracked terms.
    brand_service.start_scan(client_id, [c["id"] for c in created], None, False, user_id)
    return _result(added, skipped, "enqueued")


# ── orchestration ────────────────────────────────────────────────────────────
def run_portal(
    client_id: str, keywords: list[str], targets: list[str], run_scans: bool, user_id: str | None
) -> dict:
    """Fan out to each selected target, isolating failures so one never aborts another."""
    runners = {
        "organic": lambda: add_to_organic(client_id, keywords, user_id, run_scans),
        "maps": lambda: add_to_maps(client_id, keywords, run_scans),
        "brand": lambda: add_to_brand(client_id, keywords, user_id, run_scans),
    }
    out: dict = {}
    for target in targets:
        runner = runners.get(target)
        if runner is None:
            continue
        try:
            out[target] = runner()
        except Exception as exc:  # noqa: BLE001 — one tracker failing must not abort the rest
            logger.warning(
                "keyword_portal.target_error", extra={"target": target, "error": str(exc)}
            )
            out[target] = _result(0, 0, "error", "internal_error")
    return out
