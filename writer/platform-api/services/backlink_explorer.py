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
from services import backlinks_api, notifications

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Raised when a paid backlink call would exceed the daily budget."""


# DataForSEO filter expressions for the link-list tabs.
_LINK_FILTERS = {
    "all": None,
    "dofollow": [["dofollow", "=", True]],
    "nofollow": [["dofollow", "=", False]],
    "new": [["is_new", "=", True]],
    "lost": [["is_lost", "=", True]],
    "broken": [["is_broken", "=", True]],
}

# A refresh fires the four cheap endpoints; a link-list page is one call.
_REFRESH_CALL_COST = 4


# ----------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ----------------------------------------------------------------------------
def diff_domains(prev_domains, cur_domains) -> dict:
    """Referring domains gained/lost between two snapshots. Pure.

    ``prev_domains``/``cur_domains`` are iterables of domain strings. Returns
    ``{"new": [...], "lost": [...]}`` sorted. The caller treats a target with no
    previous snapshot as a baseline (no gains/losses) rather than "all new"."""
    prev = {d for d in prev_domains if d}
    cur = {d for d in cur_domains if d}
    return {"new": sorted(cur - prev), "lost": sorted(prev - cur)}


def should_alert(new_count: int, lost_count: int) -> bool:
    """Whether a tracked target's gained/lost domain counts clear the alert bar."""
    return (new_count >= settings.backlink_alert_new_domains_min
            or lost_count >= settings.backlink_alert_lost_domains_min)


def net_rd_change(prev_total, cur_total):
    """Net change in TOTAL referring domains between snapshots (cur − prev), or
    None when either total is missing. Pure. The total is the unbounded summary
    count — unlike the top-N window the new/lost diff is drawn from."""
    if prev_total is None or cur_total is None:
        return None
    return cur_total - prev_total


def should_alert_gated(new_count: int, lost_count: int, net_rd) -> bool:
    """should_alert, but corroborated by the net TOTAL-RD movement so window
    churn doesn't false-alarm. The new/lost diff comes from the top-N referring
    domains by DR; a domain sliding across that boundary looks gained+lost while
    the true total barely moves. Requiring the net total to move in the alert's
    direction suppresses that. ``net_rd`` None (no prior total) → fall back to
    the raw thresholds. Pure."""
    if not should_alert(new_count, lost_count):
        return False
    if net_rd is None:
        return True
    if lost_count >= settings.backlink_alert_lost_domains_min and net_rd < 0:
        return True
    if new_count >= settings.backlink_alert_new_domains_min and net_rd > 0:
        return True
    return False


def is_recent(captured_at, max_age_days: int, now: Optional[datetime] = None) -> bool:
    """Whether a snapshot timestamp is within ``max_age_days`` of ``now`` (default
    utcnow). Pure given ``now``. Guards temporally-stale enrichment (a lost-domain
    sample from months ago must not be attached to a fresh drop alert)."""
    if not captured_at:
        return False
    try:
        cap = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if cap.tzinfo is None:
        cap = cap.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - cap) <= timedelta(days=max_age_days)


def _diff_for_snapshot(prev_snapshot_id, rd_ok: bool, prev_domains, cur_domains) -> dict:
    """The gained/lost diff to record on a snapshot. Pure.

    Suppressed (no gains/losses) when there is no previous snapshot (baseline)
    OR the referring-domains fetch FAILED (``rd_ok`` False) — an empty result
    from an API outage must NOT read as "every referring domain was lost" and
    fire a false loss alert. A genuinely-empty successful fetch still diffs."""
    if prev_snapshot_id is None or not rd_ok:
        return {"new": [], "lost": []}
    return diff_domains(prev_domains, cur_domains)


def match_own_domain_target(targets: list, client_domain: Optional[str]) -> Optional[dict]:
    """The tracked target row that IS the client's own domain (bare-domain type),
    or None. Pure — the agent-layer read of a client's own backlink monitoring."""
    if not client_domain:
        return None
    cd = client_domain.lower()
    for t in targets:
        if t.get("target_type") == "domain" and (t.get("target") or "").lower() == cd:
            return t
    return None


# ----------------------------------------------------------------------------
# Daily paid-call budget
# ----------------------------------------------------------------------------
def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def budget_remaining() -> int:
    """Paid backlink calls left in today's budget (a large number when the guard
    is disabled)."""
    cap = settings.backlink_daily_call_budget
    if cap <= 0:
        return 10 ** 9
    try:
        rows = get_supabase().table("backlink_usage").select("calls").eq("day", _today()).limit(1).execute().data
    except Exception:
        return cap
    used = rows[0]["calls"] if rows else 0
    return max(0, cap - used)


def _reserve_budget(n: int) -> None:
    """Reserve ``n`` paid calls against today's budget, or raise BudgetExceeded.

    Uses the atomic ``reserve_backlink_calls`` RPC (single check-and-increment
    UPDATE) so concurrent reservations serialize on the row lock and can never
    overshoot the cap — the old read-modify-write here could. An RPC failure is
    fail-open (accounting must never block work)."""
    cap = settings.backlink_daily_call_budget
    if cap <= 0:
        return
    try:
        res = get_supabase().rpc(
            "reserve_backlink_calls", {"p_day": _today(), "p_n": n, "p_cap": cap}
        ).execute()
        fit = res.data
    except Exception as exc:
        logger.warning("backlink_budget_accounting_failed", extra={"error": str(exc)})
        return
    if fit is False:
        raise BudgetExceeded(f"backlink_budget_exceeded: cap {cap} reached today")


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
        # The full URL target (scheme-less), as DataForSEO expects. A trailing
        # slash is always stripped so ".../a/" and ".../a" dedupe to one target.
        cleaned = raw.split("//", 1)[-1].rstrip("/")
        return cleaned, "url"
    if not host:
        raise ValueError("invalid_target")
    labels = host.split(".")
    return host, ("subdomain" if len(labels) >= 3 else "domain")


def _ttl() -> timedelta:
    return timedelta(hours=max(1, settings.backlink_cache_ttl_hours))


def _find_target(target: str, target_type: str, client_id: Optional[str]) -> Optional[dict]:
    """The existing target row (read-only, no create), or None."""
    sb = get_supabase()
    q = sb.table("backlink_targets").select("*").eq("target", target).eq("target_type", target_type)
    q = q.is_("client_id", "null") if client_id is None else q.eq("client_id", client_id)
    rows = q.limit(1).execute().data
    return rows[0] if rows else None


def get_or_create_target(
    target: str, target_type: str, client_id: Optional[str] = None, created_by: Optional[str] = None
) -> dict:
    found = _find_target(target, target_type, client_id)
    if found:
        return found
    try:
        return (
            get_supabase().table("backlink_targets")
            .insert({"target": target, "target_type": target_type, "client_id": client_id, "created_by": created_by})
            .execute()
        ).data[0]
    except Exception as exc:
        # A concurrent create won the unique index — re-select the winner instead
        # of surfacing a duplicate-key 500 to one of two simultaneous lookups.
        again = _find_target(target, target_type, client_id)
        if again:
            return again
        raise


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


def _previous_domains(target_id: str) -> tuple[Optional[str], set]:
    """The (snapshot_id, referring-domain set) of the target's most recent prior
    snapshot — the baseline for new/lost diffing. (None, empty) if none yet."""
    sb = get_supabase()
    prev = (
        sb.table("backlink_snapshots").select("id")
        .eq("target_id", target_id).order("captured_at", desc=True).limit(1).execute()
    ).data
    if not prev:
        return None, set()
    prev_id = prev[0]["id"]
    rows = (
        sb.table("backlink_referring_domains").select("domain")
        .eq("snapshot_id", prev_id).eq("is_lost", False).execute()
    ).data or []
    return prev_id, {r["domain"] for r in rows if r.get("domain")}


async def _refresh(target: str, target_type: str, target_id: str) -> dict:
    """Fire the four cheap endpoints concurrently, persist a snapshot + children.
    Degrades per-endpoint — a single failure never aborts the whole refresh.
    Diffs referring domains vs the previous snapshot for gained/lost tracking."""
    _reserve_budget(_REFRESH_CALL_COST)
    prev_snapshot_id, prev_domains = _previous_domains(target_id)
    summary_r, rd_r, anchors_r, history_r = await asyncio.gather(
        backlinks_api.fetch_summary(target, target_type),
        backlinks_api.fetch_referring_domains(target, target_type, limit=settings.backlink_referring_domains_limit),
        backlinks_api.fetch_anchors(target, target_type, limit=settings.backlink_anchors_limit),
        backlinks_api.fetch_history(target, target_type),
        return_exceptions=True,
    )
    summary = summary_r if isinstance(summary_r, dict) else {}
    rd_ok = isinstance(rd_r, list)
    referring_domains = rd_r if rd_ok else []
    anchors = anchors_r if isinstance(anchors_r, list) else []
    history = history_r if isinstance(history_r, list) else []
    for label, res in (("summary", summary_r), ("referring_domains", rd_r), ("anchors", anchors_r), ("history", history_r)):
        if isinstance(res, Exception):
            logger.warning("backlink_refresh_partial", extra={"target": target, "view": label, "error": str(res)})

    # Diff referring domains vs the previous snapshot. A target's first snapshot
    # is a baseline (no gains/losses) so it never reads as "all N are new".
    cur_domains = [rd.get("domain") for rd in referring_domains]
    diff = _diff_for_snapshot(prev_snapshot_id, rd_ok, prev_domains, cur_domains)
    new_set = set(diff["new"])
    lost = diff["lost"]

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
            "new_domains": len(diff["new"]),
            "lost_domains": len(lost),
            "raw": {"summary": summary, "history": history,
                    "new_domains": diff["new"][:100], "lost_domains": lost[:100]},
        }).execute()
    ).data[0]
    snapshot_id = snap["id"]

    if referring_domains:
        sb.table("backlink_referring_domains").insert(
            [{"snapshot_id": snapshot_id, "domain": rd.get("domain"),
              "domain_rating": rd.get("domain_rating"), "backlinks": rd.get("backlinks"),
              "dofollow": rd.get("dofollow"), "first_seen": rd.get("first_seen"),
              "last_seen": rd.get("last_seen"),
              "is_new": rd.get("domain") in new_set, "is_lost": False}
             for rd in referring_domains]
        ).execute()
    # Synthetic is_lost rows so the Referring Domains table + the Lost filter can
    # show domains that dropped off (they're absent from the current API result).
    if lost:
        sb.table("backlink_referring_domains").insert(
            [{"snapshot_id": snapshot_id, "domain": d, "is_lost": True, "is_new": False}
             for d in lost[: settings.backlink_lost_rows_cap]]
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
    row = _find_target(target, target_type, client_id)
    snapshot = _latest_snapshot(row["id"]) if row else None
    cached = _is_fresh(snapshot) and not force
    if not cached:
        # Fail fast on an exhausted budget BEFORE creating a target row, so a
        # 429'd lookup doesn't leave an orphan target with no snapshot.
        if budget_remaining() < _REFRESH_CALL_COST:
            raise BudgetExceeded(f"backlink_budget_exceeded: cap {settings.backlink_daily_call_budget} reached today")
        if row is None:
            row = get_or_create_target(target, target_type, client_id=client_id, created_by=created_by)
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
    _reserve_budget(1)
    result = await backlinks_api.fetch_backlinks(
        target, target_type, mode=mode, limit=limit, offset=max(0, offset), filters=filters,
    )
    return {"target": target, "target_type": target_type, "filter": filter_key,
            "mode": mode, "limit": limit, "offset": offset, **result}


# ----------------------------------------------------------------------------
# Tracked targets — scheduled re-snapshots + new/lost alerts (client-scoped)
# ----------------------------------------------------------------------------
def enqueue_snapshot(target_id: str) -> bool:
    """Enqueue a backlink_snapshot job for a target (dedup against in-flight)."""
    sb = get_supabase()
    existing = (
        sb.table("async_jobs").select("id")
        .eq("job_type", "backlink_snapshot").eq("entity_id", target_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    ).data
    if existing:
        return False
    sb.table("async_jobs").insert(
        {"job_type": "backlink_snapshot", "entity_id": target_id, "payload": {"target_id": target_id}}
    ).execute()
    return True


def track_target(client_id: str, raw_target: str, label: Optional[str] = None, created_by: Optional[str] = None) -> dict:
    """Mark a target tracked for a client (its own domain or a competitor's) and
    kick an immediate first capture."""
    target, target_type = normalize_target(raw_target)
    row = get_or_create_target(target, target_type, client_id=client_id, created_by=created_by)
    updated = (
        get_supabase().table("backlink_targets")
        .update({"tracked": True, "label": label}).eq("id", row["id"]).execute()
    ).data[0]
    enqueue_snapshot(row["id"])
    return updated


def untrack_target(client_id: str, target_id: str) -> None:
    get_supabase().table("backlink_targets").update({"tracked": False}) \
        .eq("id", target_id).eq("client_id", client_id).execute()


_LATEST_FIELDS = ("referring_domains", "backlinks", "domain_rating", "new_domains", "lost_domains", "captured_at")


def list_tracked(client_id: str) -> list[dict]:
    """Tracked targets for a client + each one's latest snapshot summary. One
    batched snapshot read (was one query per target)."""
    sb = get_supabase()
    targets = (
        sb.table("backlink_targets").select("*")
        .eq("client_id", client_id).eq("tracked", True)
        .order("created_at", desc=True).execute()
    ).data or []
    if not targets:
        return []
    target_ids = [t["id"] for t in targets]
    snaps = (
        sb.table("backlink_snapshots").select("target_id, " + ", ".join(_LATEST_FIELDS))
        .in_("target_id", target_ids).order("captured_at", desc=True).execute()
    ).data or []
    latest_by_target: dict = {}
    for s in snaps:
        latest_by_target.setdefault(s["target_id"], s)  # first seen = latest (desc order)
    out = []
    for t in targets:
        snap = latest_by_target.get(t["id"])
        out.append({**t, "latest": ({k: snap.get(k) for k in _LATEST_FIELDS} if snap else None)})
    return out


def _prior_total(target_id: str, exclude_snapshot_id: str) -> Optional[int]:
    """The total referring_domains of the target's snapshot just before the given
    one — the baseline for the net-RD alert gate."""
    rows = (
        get_supabase().table("backlink_snapshots").select("id, referring_domains")
        .eq("target_id", target_id).order("captured_at", desc=True).limit(2).execute()
    ).data or []
    for r in rows:
        if r["id"] != exclude_snapshot_id:
            return r.get("referring_domains")
    return None


def client_own_domain_change(client_id: str) -> Optional[dict]:
    """The client's own-domain backlink link-velocity from the Backlink Explorer,
    for the agent layer (offpage enrichment, strategist digest). Returns the
    latest tracked snapshot's gained/lost referring domains (+ samples) or None
    when the client hasn't tracked their own domain. Best-effort — never raises."""
    try:
        from services.dataforseo_rank import extract_domain

        sb = get_supabase()
        client = (sb.table("clients").select("website_url").eq("id", client_id).limit(1).execute()).data
        if not client:
            return None
        domain = extract_domain(client[0].get("website_url") or "")
        if not domain:
            return None
        targets = (
            sb.table("backlink_targets").select("*")
            .eq("client_id", client_id).eq("tracked", True).execute()
        ).data or []
        target = match_own_domain_target(targets, domain)
        if not target:
            return None
        snap = _latest_snapshot(target["id"])
        if not snap:
            return None
        raw = snap.get("raw") or {}
        return {
            "domain": domain,
            "domain_rating": snap.get("domain_rating"),
            "referring_domains": snap.get("referring_domains"),
            "new_domains": snap.get("new_domains") or 0,
            "lost_domains": snap.get("lost_domains") or 0,
            "lost_sample": (raw.get("lost_domains") or [])[:10],
            "new_sample": (raw.get("new_domains") or [])[:10],
            "captured_at": snap.get("captured_at"),
        }
    except Exception as exc:
        logger.warning("backlink_own_domain_change_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def _emit_backlink_alert(target_row: dict, new_count: int, lost_count: int) -> None:
    client_id = target_row.get("client_id")
    if not client_id:
        return
    label = target_row.get("label") or target_row.get("target")
    if lost_count >= settings.backlink_alert_lost_domains_min and lost_count >= new_count:
        severity = "warning"
        title = f"Backlinks: {lost_count} referring domains lost — {label}"
        summary = (f"{label} lost {lost_count} referring domains since the last check"
                   + (f" (and gained {new_count})" if new_count else "") + ".")
    else:
        severity = "info"
        title = f"Backlinks: {new_count} new referring domains — {label}"
        summary = (f"{label} gained {new_count} referring domains since the last check"
                   + (f" (and lost {lost_count})" if lost_count else "") + ".")
    notifications.emit(client_id, kind="backlink_change", title=title, summary=summary,
                       severity=severity, payload={"target": target_row.get("target"),
                                                   "new_domains": new_count, "lost_domains": lost_count})


async def run_backlink_snapshot_job(job: dict) -> None:
    """async_jobs handler: re-snapshot a (tracked) target, then alert its client
    when gained/lost referring domains clear the threshold."""
    payload = job.get("payload") or {}
    target_id = payload.get("target_id")
    sb = get_supabase()
    job_id = job["id"]
    if not target_id:
        sb.table("async_jobs").update(
            {"status": "failed", "error": "missing target_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        row = (sb.table("backlink_targets").select("*").eq("id", target_id).limit(1).execute()).data
        if not row:
            raise RuntimeError("target_not_found")
        target_row = row[0]
        snap = await _refresh(target_row["target"], target_row["target_type"], target_id)
        new_count = snap.get("new_domains") or 0
        lost_count = snap.get("lost_domains") or 0
        # Gate on the net total-RD movement so top-N window churn (a domain
        # sliding across the diff boundary, looking gained+lost while the true
        # total is flat) doesn't false-alarm.
        net = net_rd_change(_prior_total(target_id, snap["id"]), snap.get("referring_domains"))
        if target_row.get("tracked") and should_alert_gated(new_count, lost_count, net):
            _emit_backlink_alert(target_row, new_count, lost_count)
        sb.table("async_jobs").update({"status": "complete", "completed_at": "now()"}).eq("id", job_id).execute()
    except BudgetExceeded as exc:
        # Daily budget exhausted — the cap won't free until the date rolls, so
        # retrying intra-day is futile. Mark terminal (NOT re-pending: the claim
        # increments attempts and refuses past max_attempts, which would strand
        # the job as un-runnable AND block re-enqueue via the pending/running
        # dedup). enqueue_due_backlink_snapshots re-enqueues a fresh job (attempts
        # reset) on the next daily tick, since last_refreshed_at stayed old.
        logger.info("backlink_snapshot_deferred_budget", extra={"target_id": target_id, "reason": str(exc)})
        sb.table("async_jobs").update(
            {"status": "failed", "error": "budget_exceeded", "completed_at": "now()"}
        ).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("backlink_snapshot_failed", extra={"target_id": target_id, "error": str(exc)})
        sb.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def enqueue_due_backlink_snapshots() -> int:
    """Weekly per tracked target: re-snapshot when the latest is older than the
    tracking interval. Cheap DB reads; the paid pull happens in the job (drawing
    from the daily budget)."""
    if not settings.backlink_tracking_enabled:
        return 0
    from datetime import datetime, timedelta, timezone
    sb = get_supabase()
    targets = (sb.table("backlink_targets").select("id, last_refreshed_at").eq("tracked", True).execute()).data or []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, settings.backlink_tracking_interval_days))
    enqueued = 0
    for t in targets:
        lr = t.get("last_refreshed_at")
        if lr:
            try:
                when = datetime.fromisoformat(str(lr).replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                if when > cutoff:
                    continue
            except ValueError:
                pass
        if enqueue_snapshot(t["id"]):
            enqueued += 1
    return enqueued
