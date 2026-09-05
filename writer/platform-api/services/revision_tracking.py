"""Admin Activity Report → Revisions.

How often deliverables get sent back "for revision" (the In Review status —
client rejected → rework). A per-task counter (tasks.revision_count, bumped on
each transition into the revision status) lets us see repeat offenders: a task
revised 2–3+ times is a deliverable that keeps missing client expectations.

This is a current-state read over `tasks` (all-time revision counts, plus what's
in revision right now), not a historical event stream. Bucketing + rollup are
pure (unit-tested); only `build_revision_report` reads the DB.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

BUCKETS = ("1×", "2×", "3+×")
_UNASSIGNED = "Unassigned"
_NO_CLIENT = "No client / internal"


def revision_bucket(count: int) -> Optional[str]:
    """Bucket a task's revision count. None for 0 (never revised). Pure."""
    if count <= 0:
        return None
    if count == 1:
        return BUCKETS[0]
    if count == 2:
        return BUCKETS[1]
    return BUCKETS[2]


def summarize_revisions(
    tasks: list[dict],
    revision_status_key: str,
    client_names: dict[str, str],
    member_names: dict[str, str],
    most_revised_limit: int = 15,
) -> dict[str, Any]:
    """Roll revised tasks up: totals, repeat count, currently-in-revision, a
    1×/2×/3+× bucket histogram, revisions by client + assignee (Σ counts), and
    the most-revised tasks. Pure — names resolved by the caller.

    `tasks` should already be the revised set (revision_count > 0)."""
    total_requests = 0          # Σ revision_count — total times work was bounced back
    tasks_revised = 0           # distinct tasks ever revised
    repeat_revised = 0          # tasks revised ≥ 2×
    in_revision_now = 0         # open tasks sitting in the revision status
    by_bucket = {b: 0 for b in BUCKETS}
    by_client: dict[Optional[str], int] = {}
    by_member: dict[str, int] = {}
    most_revised: list[dict] = []

    for t in tasks:
        count = int(t.get("revision_count") or 0)
        if count <= 0:
            continue
        tasks_revised += 1
        total_requests += count
        if count >= 2:
            repeat_revised += 1
        bucket = revision_bucket(count)
        if bucket:
            by_bucket[bucket] += 1
        if t.get("status_key") == revision_status_key and not t.get("completed"):
            in_revision_now += 1

        cid = str(t["client_id"]) if t.get("client_id") else None
        by_client[cid] = by_client.get(cid, 0) + count

        assignee = (t.get("assignee_name") or "").strip()
        if assignee:
            member = assignee
        elif t.get("created_by"):
            member = member_names.get(str(t["created_by"]), "Unknown user")
        else:
            member = _UNASSIGNED
        by_member[member] = by_member.get(member, 0) + count

        most_revised.append({
            "task_id": str(t.get("id")),
            "name": t.get("name") or "(untitled)",
            "client_name": client_names.get(cid, _NO_CLIENT) if cid else _NO_CLIENT,
            "revision_count": count,
        })

    most_revised.sort(key=lambda r: (-r["revision_count"], r["name"].lower()))
    bucket_rows = [{"bucket": b, "count": by_bucket[b]} for b in BUCKETS]
    client_rows = sorted(
        (
            {
                "client_id": cid,
                "client_name": client_names.get(cid, _NO_CLIENT) if cid else _NO_CLIENT,
                "revisions": n,
            }
            for cid, n in by_client.items()
        ),
        key=lambda r: (-r["revisions"], r["client_name"].lower()),
    )
    member_rows = sorted(
        ({"member": m, "revisions": n} for m, n in by_member.items()),
        key=lambda r: (-r["revisions"], r["member"] == _UNASSIGNED, r["member"].lower()),
    )

    return {
        "total_requests": total_requests,
        "tasks_revised": tasks_revised,
        "repeat_revised": repeat_revised,
        "in_revision_now": in_revision_now,
        "by_bucket": bucket_rows,
        "by_client": client_rows,
        "by_member": member_rows,
        "most_revised": most_revised[:most_revised_limit],
    }


# ── impure: read revised tasks ───────────────────────────────────────────────

def _client_names(supabase, client_ids: set[str]) -> dict[str, str]:
    if not client_ids:
        return {}
    try:
        rows = (supabase.table("clients").select("id, name").in_("id", list(client_ids)).execute()).data or []
        return {str(r["id"]): r.get("name") or "Client" for r in rows}
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("revision_tracking.client_names_failed", extra={"error": str(exc)})
        return {}


def _member_names(supabase, profile_ids: set[str]) -> dict[str, str]:
    if not profile_ids:
        return {}
    try:
        rows = (supabase.table("profiles").select("id, full_name, email").in_("id", list(profile_ids)).execute()).data or []
        return {str(r["id"]): (r.get("full_name") or r.get("email") or "Unknown user") for r in rows}
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("revision_tracking.member_names_failed", extra={"error": str(exc)})
        return {}


def build_revision_report(client_id: Optional[str] = None) -> dict[str, Any]:
    """Revision counts across tasks (all-time), optionally scoped to one client.
    Includes completed tasks — a shipped deliverable that was revised repeatedly
    still tells us it missed expectations."""
    from config import settings

    revision_key = settings.revision_status_key
    supabase = get_supabase()

    tasks: list[dict] = []
    try:
        q = (
            supabase.table("tasks")
            .select("id, name, client_id, status_key, assignee_name, created_by, revision_count, completed")
            .is_("deleted_at", "null")
            .is_("parent_task_id", "null")
            .gt("revision_count", 0)
        )
        if client_id:
            q = q.eq("client_id", client_id)
        tasks = (q.limit(5000).execute()).data or []
    except Exception as exc:
        logger.error("revision_tracking.query_failed", extra={"error": str(exc)})

    client_ids = {str(t["client_id"]) for t in tasks if t.get("client_id")}
    names = _client_names(supabase, client_ids)
    profile_ids = {
        str(t["created_by"]) for t in tasks
        if t.get("created_by") and not (t.get("assignee_name") or "").strip()
    }
    member_names = _member_names(supabase, profile_ids)

    report = summarize_revisions(tasks, revision_key, names, member_names)
    report["client_id"] = client_id
    report["revision_status_key"] = revision_key
    return report
