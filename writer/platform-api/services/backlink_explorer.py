"""Backlink explorer orchestration — the read/refresh layer over
``backlinks_api`` (DataForSEO) + the ``backlink_*`` tables.

Any domain/subdomain/url can be looked up. A lookup:
  1. normalizes the raw input → (target, target_type),
  2. upserts a ``backlink_targets`` row (client_id null for ad-hoc lookups),
  3. serves the most-recent snapshot if it is within the TTL (no paid call),
     else fires the cheap endpoints (summary + referring_domains + anchors +
     history) concurrently, persists a snapshot + its child rows, and serves it.

The expensive per-link list (``list_links``) is fetched on demand, defaults to
``one_per_domain`` to bound the billed rows, and is NOT persisted.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from config import settings
from db.supabase_client import get_supabase
from services import backlinks_api

logger = logging.getLogger(__name__)

# DataForSEO filter expressions for the link-list tabs.
_LINK_FILTERS = {
    "all": None,
    "dofollow": [["dofollow", "=", True]],
    "nofollow": [["dofollow", "=", False]],
    "new": [["is_new", "=", True]],
    "lost": [["is_lost", "=", True]],
    "broken": [["is_broken", "=", True]],
}


def normalize_target(raw: str) -> tuple[str, str]:
    """(target, target_type) from free-form input.

    A path → ``url``; a bare host with a subdomain (3+ labels, www stripped) →
    ``subdomain``; otherwise ``domain``.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("empty_target")
    parsed = urlparse(raw if "//" in raw else f"//{raw}")
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path or ""
    if path and path.strip("/"):
        # Keep the full URL target (scheme-less), as DataForSEO expects.
        cleaned = raw.split("//", 1)[-1]
        return cleaned.rstrip("/") if cleaned.count("/") <= 1 else cleaned, "url"
    if not host:
        raise ValueError("invalid_target")
    labels = host.split(".")
    return host, ("subdomain" if len(labels) >= 3 else "domain")


def _ttl() -> timedelta:
    return timedelta(hours=max(1, settings.backlink_cache_ttl_hours))


def get_or_create_target(
    target: str, target_type: str, client_id: Optional[str] = None, created_by: Optional[str] = None
) -> dict:
    sb = get_supabase()
    q = sb.table("backlink_targets").select("*").eq("target", target).eq("target_type", target_type)
    q = q.is_("client_id", "null") if client_id is None else q.eq("client_id", client_id)
    existing = q.limit(1).execute().data
    if existing:
        return existing[0]
    return (
        sb.table("backlink_targets")
        .insert({"target": target, "target_type": target_type, "client_id": client_id, "created_by": created_by})
        .execute()
    ).data[0]


def _latest_snapshot(target_id: str) -> Optional[dict]:
    rows = (
        get_supabase().table("backlink_snapshots").select("*")
        .eq("target_id", target_id).order("captured_at", desc=True).limit(1).execute()
    ).data
    return rows[0] if rows else None


def _is_fresh(snapshot: Optional[dict]) -> bool:
    if not snapshot or not snapshot.get("captured_at"):
        return False
    try:
        cap = datetime.fromisoformat(str(snapshot["captured_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    if cap.tzinfo is None:
        cap = cap.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - cap < _ttl()


async def _refresh(target: str, target_type: str, target_id: str) -> dict:
    """Fire the four cheap endpoints concurrently, persist a snapshot + children.
    Degrades per-endpoint — a single failure never aborts the whole refresh."""
    summary_r, rd_r, anchors_r, history_r = await asyncio.gather(
        backlinks_api.fetch_summary(target, target_type),
        backlinks_api.fetch_referring_domains(target, target_type, limit=settings.backlink_referring_domains_limit),
        backlinks_api.fetch_anchors(target, target_type, limit=settings.backlink_anchors_limit),
        backlinks_api.fetch_history(target, target_type),
        return_exceptions=True,
    )
    summary = summary_r if isinstance(summary_r, dict) else {}
    referring_domains = rd_r if isinstance(rd_r, list) else []
    anchors = anchors_r if isinstance(anchors_r, list) else []
    history = history_r if isinstance(history_r, list) else []
    for label, res in (("summary", summary_r), ("referring_domains", rd_r), ("anchors", anchors_r), ("history", history_r)):
        if isinstance(res, Exception):
            logger.warning("backlink_refresh_partial", extra={"target": target, "view": label, "error": str(res)})

    sb = get_supabase()
    snap = (
        sb.table("backlink_snapshots").insert({
            "target_id": target_id,
            "referring_domains": summary.get("referring_domains"),
            "backlinks": summary.get("backlinks"),
            "dofollow": summary.get("dofollow"),
            "nofollow": summary.get("nofollow"),
            "broken_backlinks": summary.get("broken_backlinks"),
            "referring_ips": summary.get("referring_ips"),
            "referring_subnets": summary.get("referring_subnets"),
            "domain_rating": summary.get("domain_rating"),
            "raw": {"summary": summary, "history": history},
        }).execute()
    ).data[0]
    snapshot_id = snap["id"]

    if referring_domains:
        sb.table("backlink_referring_domains").insert(
            [{"snapshot_id": snapshot_id, **{k: rd.get(k) for k in
              ("domain", "domain_rating", "backlinks", "dofollow", "first_seen", "last_seen", "is_new", "is_lost")}}
             for rd in referring_domains]
        ).execute()
    if anchors:
        sb.table("backlink_anchors").insert(
            [{"snapshot_id": snapshot_id, **{k: a.get(k) for k in
              ("anchor", "backlinks", "referring_domains", "dofollow", "first_seen")}}
             for a in anchors]
        ).execute()

    sb.table("backlink_targets").update(
        {"last_refreshed_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", target_id).execute()
    return snap


def _read_children(snapshot_id: str) -> tuple[list[dict], list[dict]]:
    sb = get_supabase()
    rds = (
        sb.table("backlink_referring_domains").select("*")
        .eq("snapshot_id", snapshot_id).order("domain_rating", desc=True).execute()
    ).data or []
    anchors = (
        sb.table("backlink_anchors").select("*")
        .eq("snapshot_id", snapshot_id).order("backlinks", desc=True).execute()
    ).data or []
    return rds, anchors


async def lookup(
    raw_target: str, client_id: Optional[str] = None, created_by: Optional[str] = None, force: bool = False
) -> dict:
    """The Overview + Referring Domains + Anchors + History payload for a target,
    served from cache when a snapshot is within the TTL (unless ``force``)."""
    target, target_type = normalize_target(raw_target)
    row = get_or_create_target(target, target_type, client_id=client_id, created_by=created_by)
    snapshot = _latest_snapshot(row["id"])
    cached = _is_fresh(snapshot) and not force
    if not cached:
        snapshot = await _refresh(target, target_type, row["id"])
    referring_domains, anchors = _read_children(snapshot["id"])
    raw = snapshot.get("raw") or {}
    return {
        "target": target,
        "target_type": target_type,
        "target_id": row["id"],
        "client_id": client_id,
        "cached": cached,
        "captured_at": snapshot.get("captured_at"),
        "overview": {k: snapshot.get(k) for k in
                     ("referring_domains", "backlinks", "dofollow", "nofollow",
                      "broken_backlinks", "referring_ips", "referring_subnets", "domain_rating")},
        "referring_domains": referring_domains,
        "anchors": anchors,
        "history": raw.get("history") or [],
    }


async def list_links(
    raw_target: str, filter_key: str = "all", mode: str = "one_per_domain",
    limit: int = 100, offset: int = 0,
) -> dict:
    """On-demand individual-link list (not persisted). `filter_key` ∈
    all|dofollow|nofollow|new|lost|broken."""
    target, target_type = normalize_target(raw_target)
    filters = _LINK_FILTERS.get(filter_key)
    limit = max(1, min(limit, settings.backlink_links_max_limit))
    result = await backlinks_api.fetch_backlinks(
        target, target_type, mode=mode, limit=limit, offset=max(0, offset), filters=filters,
    )
    return {"target": target, "target_type": target_type, "filter": filter_key,
            "mode": mode, "limit": limit, "offset": offset, **result}
