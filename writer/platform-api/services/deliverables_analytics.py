"""Admin Activity Report — agency-wide "what was produced" analytics.

Reads the normalized `public.deliverable_events` view (migration
20260904130000) and rolls it up three ways for the admin dashboard:
count of produced deliverables **by type**, **by client**, and **by team
member**, over a date range, plus a per-day time series.

The view already encodes "produced only" (completed / published / live /
non-deleted) so this layer never re-derives status; it just aggregates. The
aggregation helpers are pure (unit-tested); only `build_report` touches the DB
(reading the view + resolving client/profile names).

Attribution ("by team member"): content pages/reports carry a `created_by`
profile id; native tasks carry the doer as a free-text `assignee_name`;
scheduled/automated work carries neither. `member_key` resolves that into one
display bucket per event — assignee name wins, then the creator's profile,
then "Automated / scheduled".
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_PAGE = 1000
# Hard ceiling on rows pulled for one report, so an "all time" range on a large
# property can't run away. The response flags truncation when hit.
_MAX_EVENTS = 100_000
_SYSTEM_MEMBER = "Automated / scheduled"
_NO_CLIENT = "No client / internal"

# ── deliverable-type presentation (labels + coarse grouping) ─────────────────
# The view emits stable type keys; human labels + the section a type belongs to
# live here so they can change without a migration.
TYPE_LABELS: dict[str, str] = {
    "blog_post": "Blog post",
    "service_page": "Service page",
    "location_page": "Location page",
    "local_seo_page": "Local SEO page",
    "local_seo_reoptimize": "Local SEO reoptimize",
    "ecommerce_product": "Ecommerce product page",
    "ecommerce_collection": "Ecommerce collection page",
    "ecommerce_reoptimize": "Ecommerce reoptimize",
    "website_page": "Website page (published)",
    "gbp_post": "GBP post",
    "task_content": "Task — Content",
    "task_link_building": "Task — Link building",
    "task_gbp_authority": "Task — GBP authority",
    "task_strategy": "Task — Strategy",
    "task_other": "Task — Other",
    "client_report": "Client report",
    "keyword_research_report": "Keyword research report",
    "rank_keyword_report": "Rank analysis report",
    "keyword_report_fanout": "Fanout keyword report",
    "maps_scan": "Maps geo-grid scan",
    "ai_visibility_scan": "AI visibility scan",
    "gsc_research": "GSC research",
    "keyword_research": "Keyword research",
    "domain_intel": "Domain intel snapshot",
}

_PAGE_TYPES = {
    "blog_post", "service_page", "location_page", "local_seo_page",
    "local_seo_reoptimize", "ecommerce_product", "ecommerce_collection",
    "ecommerce_reoptimize", "website_page",
}
_REPORT_TYPES = {
    "client_report", "keyword_research_report", "rank_keyword_report",
    "keyword_report_fanout",
}
_RESEARCH_TYPES = {
    "maps_scan", "ai_visibility_scan", "gsc_research", "keyword_research",
    "domain_intel",
}


def label_for(deliverable_type: str) -> str:
    """Human label for a type key, with a readable fallback for unmapped keys
    (e.g. a future task category). Pure."""
    if deliverable_type in TYPE_LABELS:
        return TYPE_LABELS[deliverable_type]
    if deliverable_type.startswith("task_"):
        rest = deliverable_type[len("task_"):].replace("_", " ").strip()
        return f"Task — {rest.title()}" if rest else "Task"
    return deliverable_type.replace("_", " ").title()


def group_for(deliverable_type: str) -> str:
    """Coarse section a type belongs to, for grouping the by-type breakdown. Pure."""
    if deliverable_type == "gbp_post":
        return "GBP posts"
    if deliverable_type.startswith("task_"):
        return "Tasks"
    if deliverable_type in _PAGE_TYPES:
        return "Content pages"
    if deliverable_type in _REPORT_TYPES:
        return "Reports"
    if deliverable_type in _RESEARCH_TYPES:
        return "Research & scans"
    return "Other"


# ── pure aggregation ─────────────────────────────────────────────────────────

def member_key(event: dict) -> tuple[str, Optional[str]]:
    """Resolve one team-member bucket for an event. Pure.

    Assignee name (the task doer) wins, then the creator's profile id, then the
    automated/scheduled bucket. Returns ('name', <str>) | ('profile', <id>) |
    ('system', None) so the impure layer can resolve profile ids to names."""
    name = (event.get("actor_name") or "").strip()
    if name:
        return ("name", name)
    actor_id = event.get("actor_id")
    if actor_id:
        return ("profile", str(actor_id))
    return ("system", None)


def _occurred_date(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.date().isoformat()


def aggregate(events: list[dict]) -> dict[str, Any]:
    """Roll events up by type, client, member, and day. Pure — names are keyed
    by id here and resolved to display strings by the caller.

    Returns raw tallies:
      by_type:   {type: count}
      by_client: {client_id|None: count}
      by_member: {(kind, key): count}
      by_day:    {iso_date: count}
      total:     int
    """
    by_type: dict[str, int] = {}
    by_client: dict[Optional[str], int] = {}
    by_member: dict[tuple[str, Optional[str]], int] = {}
    by_day: dict[str, int] = {}

    for ev in events:
        dtype = ev.get("deliverable_type") or "unknown"
        by_type[dtype] = by_type.get(dtype, 0) + 1

        cid = ev.get("client_id")
        cid = str(cid) if cid else None
        by_client[cid] = by_client.get(cid, 0) + 1

        mk = member_key(ev)
        by_member[mk] = by_member.get(mk, 0) + 1

        day = _occurred_date(ev.get("occurred_at"))
        if day:
            by_day[day] = by_day.get(day, 0) + 1

    return {
        "by_type": by_type,
        "by_client": by_client,
        "by_member": by_member,
        "by_day": by_day,
        "total": len(events),
    }


def build_type_rows(by_type: dict[str, int]) -> list[dict[str, Any]]:
    """Sorted (count desc, label asc) by-type rows with label + group. Pure."""
    rows = [
        {"type": t, "label": label_for(t), "group": group_for(t), "count": n}
        for t, n in by_type.items()
    ]
    rows.sort(key=lambda r: (-r["count"], r["label"]))
    return rows


def build_client_rows(
    by_client: dict[Optional[str], int], names: dict[str, str]
) -> list[dict[str, Any]]:
    """Sorted by-client rows with resolved names. Pure. Null client → internal."""
    rows = []
    for cid, n in by_client.items():
        rows.append({
            "client_id": cid,
            "client_name": names.get(cid, _NO_CLIENT) if cid else _NO_CLIENT,
            "count": n,
        })
    rows.sort(key=lambda r: (-r["count"], r["client_name"].lower()))
    return rows


def build_member_rows(
    by_member: dict[tuple[str, Optional[str]], int], profile_names: dict[str, str]
) -> list[dict[str, Any]]:
    """Sorted by-member rows with a single display name per bucket. Pure.

    A profile-id bucket resolves through profile_names; a name bucket is used
    verbatim; the system bucket is the automated/scheduled label."""
    merged: dict[str, int] = {}
    for (kind, key), n in by_member.items():
        if kind == "profile":
            display = profile_names.get(key or "", "Unknown user")
        elif kind == "name":
            display = key or "Unknown"
        else:
            display = _SYSTEM_MEMBER
        merged[display] = merged.get(display, 0) + n
    rows = [{"member": m, "count": n} for m, n in merged.items()]
    # Keep the automated bucket last among equal counts — it's context, not a person.
    rows.sort(key=lambda r: (-r["count"], r["member"] == _SYSTEM_MEMBER, r["member"].lower()))
    return rows


def build_daily_series(by_day: dict[str, int], start: date, end: date) -> list[dict[str, Any]]:
    """Zero-filled per-day series over [start, end] when the span is reasonable,
    else just the days with activity (sorted). Pure — keeps a huge all-time
    range from returning tens of thousands of zero buckets."""
    span = (end - start).days
    if 0 <= span <= 366:
        out = []
        d = start
        while d <= end:
            iso = d.isoformat()
            out.append({"date": iso, "count": by_day.get(iso, 0)})
            d += timedelta(days=1)
        return out
    return [{"date": k, "count": v} for k, v in sorted(by_day.items())]


# ── impure: pull the view + resolve names ────────────────────────────────────

def _default_range() -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    return today - timedelta(days=29), today


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def _fetch_events(
    supabase, start: date, end: date, client_id: Optional[str]
) -> tuple[list[dict], bool]:
    """Page the deliverable_events view for [start, end] (end inclusive). Returns
    (events, truncated)."""
    # end is inclusive of the whole day → strict upper bound at end + 1 day.
    lo = datetime(start.year, start.month, start.day, tzinfo=timezone.utc).isoformat()
    hi = (datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)).isoformat()
    events: list[dict] = []
    offset = 0
    truncated = False
    while True:
        q = (
            supabase.table("deliverable_events")
            .select("event_id, source, deliverable_type, client_id, actor_id, actor_name, occurred_at")
            .gte("occurred_at", lo)
            .lt("occurred_at", hi)
        )
        if client_id:
            q = q.eq("client_id", client_id)
        rows = (
            q.order("occurred_at", desc=False)
            .order("event_id", desc=False)
            .range(offset, offset + _PAGE - 1)
            .execute()
        ).data or []
        events.extend(rows)
        if len(rows) < _PAGE:
            break
        offset += _PAGE
        if len(events) >= _MAX_EVENTS:
            truncated = True
            break
    return events, truncated


def _client_names(supabase, client_ids: set[str]) -> dict[str, str]:
    if not client_ids:
        return {}
    try:
        rows = (
            supabase.table("clients").select("id, name").in_("id", list(client_ids)).execute()
        ).data or []
        return {str(r["id"]): r.get("name") or "Client" for r in rows}
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("deliverables_analytics.client_names_failed", extra={"error": str(exc)})
        return {}


def _profile_names(supabase, profile_ids: set[str]) -> dict[str, str]:
    if not profile_ids:
        return {}
    try:
        rows = (
            supabase.table("profiles").select("id, full_name, email").in_("id", list(profile_ids)).execute()
        ).data or []
        out: dict[str, str] = {}
        for r in rows:
            out[str(r["id"])] = (r.get("full_name") or r.get("email") or "Unknown user")
        return out
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("deliverables_analytics.profile_names_failed", extra={"error": str(exc)})
        return {}


def build_report(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    client_id: Optional[str] = None,
) -> dict[str, Any]:
    """The admin Activity Report payload for a date range (defaults to the last
    30 days), optionally scoped to one client."""
    start = _parse_date(date_from)
    end = _parse_date(date_to)
    if not start or not end:
        d_start, d_end = _default_range()
        start = start or d_start
        end = end or d_end
    if end < start:
        start, end = end, start

    supabase = get_supabase()
    events, truncated = _fetch_events(supabase, start, end, client_id)
    tallies = aggregate(events)

    client_ids = {c for c in tallies["by_client"] if c}
    names = _client_names(supabase, client_ids)
    profile_ids = {key for (kind, key) in tallies["by_member"] if kind == "profile" and key}
    profile_names = _profile_names(supabase, profile_ids)

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "client_id": client_id,
        "total": tallies["total"],
        "truncated": truncated,
        "by_type": build_type_rows(tallies["by_type"]),
        "by_client": build_client_rows(tallies["by_client"], names),
        "by_member": build_member_rows(tallies["by_member"], profile_names),
        "daily": build_daily_series(tallies["by_day"], start, end),
    }
