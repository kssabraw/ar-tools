"""Admin Activity Report → Overdue tasks.

A live snapshot (as of today) of open, past-due native tasks, broken down by
how far overdue they are (1–2d / 3–4d / 5–6d / 7+d) and by CAUSE — internal
(the team owns the next action) vs external (waiting on the client). Unlike the
deliverable_events / cost_events views this is not a historical event stream but
a current-state read, so it lives in its own service + endpoint rather than a
view.

Overdue = a top-level task that is not completed, not deleted, and whose
due_date is before today. Cause is derived from the task's status: a status in
`external_status_keys` (default: Sent to Client) means the ball is in the
client's court; everything else is internal. Bucketing + classification are
pure (unit-tested); only `build_overdue_report` reads the DB.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Age buckets, in ascending order. Thresholds at 1/3/5/7 days overdue.
BUCKETS = ("1–2 days", "3–4 days", "5–6 days", "7+ days")
_UNASSIGNED = "Unassigned"
_NO_CLIENT = "No client / internal"


def age_bucket(days_overdue: int) -> Optional[str]:
    """Bucket a positive days-overdue count. None if not overdue (≤0). Pure."""
    if days_overdue <= 0:
        return None
    if days_overdue <= 2:
        return BUCKETS[0]
    if days_overdue <= 4:
        return BUCKETS[1]
    if days_overdue <= 6:
        return BUCKETS[2]
    return BUCKETS[3]


def classify_cause(status_key: Optional[str], external_status_keys: set[str]) -> str:
    """'external' when the task is waiting on the client (status in the external
    set), else 'internal'. Pure."""
    return "external" if (status_key or "") in external_status_keys else "internal"


def _parse_due(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None


def summarize_overdue(
    tasks: list[dict],
    today: date,
    external_status_keys: set[str],
    client_names: dict[str, str],
    member_names: dict[str, str],
) -> dict[str, Any]:
    """Roll overdue tasks up by age bucket (with internal/external split), by
    cause, by client, and by assignee. Pure — names resolved by the caller.

    A task with no parseable/here-past due_date is skipped (defensive; the query
    already filters to overdue, but this keeps the pure fn self-consistent)."""
    # bucket -> {internal, external, total}
    by_bucket: dict[str, dict[str, int]] = {b: {"internal": 0, "external": 0, "total": 0} for b in BUCKETS}
    cause_totals = {"internal": 0, "external": 0}
    by_client: dict[Optional[str], int] = {}
    by_member: dict[str, int] = {}
    total = 0

    for t in tasks:
        due = _parse_due(t.get("due_date"))
        if not due:
            continue
        days = (today - due).days
        bucket = age_bucket(days)
        if not bucket:
            continue
        cause = classify_cause(t.get("status_key"), external_status_keys)

        by_bucket[bucket][cause] += 1
        by_bucket[bucket]["total"] += 1
        cause_totals[cause] += 1
        total += 1

        cid = str(t["client_id"]) if t.get("client_id") else None
        by_client[cid] = by_client.get(cid, 0) + 1

        assignee = (t.get("assignee_name") or "").strip()
        if assignee:
            member = assignee
        elif t.get("created_by"):
            member = member_names.get(str(t["created_by"]), "Unknown user")
        else:
            member = _UNASSIGNED
        by_member[member] = by_member.get(member, 0) + 1

    bucket_rows = [{"bucket": b, **by_bucket[b]} for b in BUCKETS]
    cause_rows = [
        {"cause": "internal", "label": "Internal (team)", "count": cause_totals["internal"]},
        {"cause": "external", "label": "External (waiting on client)", "count": cause_totals["external"]},
    ]
    client_rows = sorted(
        (
            {
                "client_id": cid,
                "client_name": client_names.get(cid, _NO_CLIENT) if cid else _NO_CLIENT,
                "count": n,
            }
            for cid, n in by_client.items()
        ),
        key=lambda r: (-r["count"], r["client_name"].lower()),
    )
    member_rows = sorted(
        ({"member": m, "count": n} for m, n in by_member.items()),
        key=lambda r: (-r["count"], r["member"] == _UNASSIGNED, r["member"].lower()),
    )

    return {
        "total": total,
        "internal": cause_totals["internal"],
        "external": cause_totals["external"],
        "by_bucket": bucket_rows,
        "by_cause": cause_rows,
        "by_client": client_rows,
        "by_member": member_rows,
    }


# ── impure: read the open overdue tasks ──────────────────────────────────────

def _client_names(supabase, client_ids: set[str]) -> dict[str, str]:
    if not client_ids:
        return {}
    try:
        rows = (supabase.table("clients").select("id, name").in_("id", list(client_ids)).execute()).data or []
        return {str(r["id"]): r.get("name") or "Client" for r in rows}
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("overdue_tasks.client_names_failed", extra={"error": str(exc)})
        return {}


def _member_names(supabase, profile_ids: set[str]) -> dict[str, str]:
    if not profile_ids:
        return {}
    try:
        rows = (supabase.table("profiles").select("id, full_name, email").in_("id", list(profile_ids)).execute()).data or []
        return {str(r["id"]): (r.get("full_name") or r.get("email") or "Unknown user") for r in rows}
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("overdue_tasks.member_names_failed", extra={"error": str(exc)})
        return {}


def build_overdue_report(client_id: Optional[str] = None) -> dict[str, Any]:
    """Current overdue open tasks, bucketed by age and split internal/external,
    optionally scoped to one client."""
    from config import settings

    today = datetime.now(timezone.utc).date()
    external_keys = set(settings.overdue_external_status_keys or [])
    supabase = get_supabase()

    tasks: list[dict] = []
    try:
        q = (
            supabase.table("tasks")
            .select("id, client_id, status_key, due_date, assignee_name, created_by")
            .eq("completed", False)
            .is_("deleted_at", "null")
            .is_("parent_task_id", "null")
            .not_.is_("due_date", "null")
            .lt("due_date", today.isoformat())
        )
        if client_id:
            q = q.eq("client_id", client_id)
        tasks = (q.limit(5000).execute()).data or []
    except Exception as exc:
        logger.error("overdue_tasks.query_failed", extra={"error": str(exc)})

    client_ids = {str(t["client_id"]) for t in tasks if t.get("client_id")}
    names = _client_names(supabase, client_ids)
    profile_ids = {
        str(t["created_by"]) for t in tasks
        if t.get("created_by") and not (t.get("assignee_name") or "").strip()
    }
    member_names = _member_names(supabase, profile_ids)

    report = summarize_overdue(tasks, today, external_keys, names, member_names)
    report["client_id"] = client_id
    report["as_of"] = today.isoformat()
    report["external_status_keys"] = sorted(external_keys)
    return report
