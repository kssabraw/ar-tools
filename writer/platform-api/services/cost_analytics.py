"""Admin Cost & Usage Report — agency-wide spend + LLM token analytics.

Sibling of services.deliverables_analytics: it reads the normalized
`public.cost_events` view (migration 20260904140000) and rolls it up the same
three ways — **by type**, **by client**, and **by team member** — over a date
range, but summing **cost (USD)** and **LLM tokens** instead of counting rows,
with the same previous-period comparison.

Cost is recorded across the suite; tokens only on the two LLM page generators
(Local SEO, Ecommerce), so token totals cover those sources and read 0
elsewhere. The view is a spend ledger (any positive recorded cost), so totals
reflect money actually spent.

Shared, stable helpers (member attribution, previous-window math, client/profile
name resolution) are reused from deliverables_analytics so the two reports
agree; only the metric (sum vs count) and labels differ.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from db.supabase_client import get_supabase
from services import deliverables_analytics as da

logger = logging.getLogger(__name__)

_PAGE = 1000
_MAX_EVENTS = 200_000

# ── type presentation ─────────────────────────────────────────────────────────
TYPE_LABELS: dict[str, str] = {
    "blog_post": "Blog post",
    "service_page": "Service page",
    "location_page": "Location page",
    "local_seo_page": "Local SEO page",
    "local_seo_reoptimize": "Local SEO reoptimize",
    "ecommerce_product": "Ecommerce product page",
    "ecommerce_collection": "Ecommerce collection page",
    "ecommerce_reoptimize": "Ecommerce reoptimize",
    "keyword_research": "Keyword research",
    "keyword_topic_research": "Topic research",
    "domain_intel": "Domain intel",
    "autonomy_run": "Autonomy run",
    "strategist_review": "Strategist review",
    "qa_review": "QA review",
    "leadoff_scout": "LeadOff scout",
    "leadoff_tryout": "LeadOff tryout",
    "leadoff_city_finder": "LeadOff city finder",
    "leadoff_ai_probe": "LeadOff AI probe",
}
_PAGE_TYPES = {
    "blog_post", "service_page", "location_page", "local_seo_page",
    "local_seo_reoptimize", "ecommerce_product", "ecommerce_collection",
    "ecommerce_reoptimize",
}
_RESEARCH_TYPES = {"keyword_research", "keyword_topic_research", "domain_intel"}
_AGENT_TYPES = {"autonomy_run", "strategist_review", "qa_review"}


def label_for(cost_type: str) -> str:
    """Human label for a type key, readable fallback for unmapped keys. Pure."""
    if cost_type in TYPE_LABELS:
        return TYPE_LABELS[cost_type]
    if cost_type.startswith("leadoff_"):
        rest = cost_type[len("leadoff_"):].replace("_", " ").strip()
        return f"LeadOff {rest}" if rest else "LeadOff"
    return cost_type.replace("_", " ").title()


def group_for(cost_type: str) -> str:
    """Coarse section a type belongs to. Pure."""
    if cost_type in _PAGE_TYPES:
        return "Content pages"
    if cost_type in _RESEARCH_TYPES:
        return "Research"
    if cost_type.startswith("leadoff_"):
        return "Market research"
    if cost_type in _AGENT_TYPES:
        return "Agents"
    return "Other"


# ── pure aggregation ─────────────────────────────────────────────────────────

def _blank() -> dict[str, float]:
    return {"cost": 0.0, "input_tokens": 0, "output_tokens": 0, "events": 0}


def _acc(bucket: dict[str, float], cost: float, tin: int, tout: int) -> None:
    bucket["cost"] += cost
    bucket["input_tokens"] += tin
    bucket["output_tokens"] += tout
    bucket["events"] += 1


def aggregate(events: list[dict]) -> dict[str, Any]:
    """Sum cost + tokens by type, client, member, and day. Pure — names keyed by
    id here, resolved by the caller. Returns raw buckets + a total."""
    by_type: dict[str, dict] = {}
    by_client: dict[Optional[str], dict] = {}
    by_member: dict[tuple[str, Optional[str]], dict] = {}
    by_day: dict[str, dict] = {}
    total = _blank()

    for ev in events:
        cost = float(ev.get("cost_usd") or 0)
        tin = int(ev.get("input_tokens") or 0)
        tout = int(ev.get("output_tokens") or 0)

        _acc(by_type.setdefault(ev.get("cost_type") or "unknown", _blank()), cost, tin, tout)
        cid = str(ev["client_id"]) if ev.get("client_id") else None
        _acc(by_client.setdefault(cid, _blank()), cost, tin, tout)
        _acc(by_member.setdefault(da.member_key(ev), _blank()), cost, tin, tout)
        day = da._occurred_date(ev.get("occurred_at"))  # reuse the shared parser
        if day:
            _acc(by_day.setdefault(day, _blank()), cost, tin, tout)
        _acc(total, cost, tin, tout)

    return {"by_type": by_type, "by_client": by_client, "by_member": by_member, "by_day": by_day, "total": total}


def _metrics(cur: dict, prev: dict) -> dict[str, Any]:
    """Shared cost+token metric block (current, previous, deltas). Pure."""
    tokens = cur["input_tokens"] + cur["output_tokens"]
    prev_tokens = prev["input_tokens"] + prev["output_tokens"]
    return {
        "cost": round(cur["cost"], 4),
        "prev_cost": round(prev["cost"], 4),
        "cost_delta": round(cur["cost"] - prev["cost"], 4),
        "input_tokens": cur["input_tokens"],
        "output_tokens": cur["output_tokens"],
        "tokens": tokens,
        "prev_tokens": prev_tokens,
        "tokens_delta": tokens - prev_tokens,
        "events": cur["events"],
    }


def build_type_rows(by_type: dict, prev_by_type: Optional[dict] = None) -> list[dict]:
    """By-type rows with label + group + cost/token metrics and deltas. Pure."""
    prev = prev_by_type or {}
    rows = []
    for t in set(by_type) | set(prev):
        m = _metrics(by_type.get(t, _blank()), prev.get(t, _blank()))
        rows.append({"type": t, "label": label_for(t), "group": group_for(t), **m})
    rows.sort(key=lambda r: (-r["cost"], -r["tokens"], r["label"]))
    return rows


def build_client_rows(by_client: dict, names: dict[str, str], prev_by_client: Optional[dict] = None) -> list[dict]:
    """By-client rows with resolved names + metrics/deltas. Pure."""
    prev = prev_by_client or {}
    rows = []
    for cid in set(by_client) | set(prev):
        m = _metrics(by_client.get(cid, _blank()), prev.get(cid, _blank()))
        rows.append({
            "client_id": cid,
            "client_name": names.get(cid, da._NO_CLIENT) if cid else da._NO_CLIENT,
            **m,
        })
    rows.sort(key=lambda r: (-r["cost"], -r["tokens"], r["client_name"].lower()))
    return rows


def _member_display_agg(by_member: dict, profile_names: dict[str, str]) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for (kind, key), b in by_member.items():
        if kind == "profile":
            display = profile_names.get(key or "", "Unknown user")
        elif kind == "name":
            display = key or "Unknown"
        else:
            display = da._SYSTEM_MEMBER
        tgt = merged.setdefault(display, _blank())
        tgt["cost"] += b["cost"]
        tgt["input_tokens"] += b["input_tokens"]
        tgt["output_tokens"] += b["output_tokens"]
        tgt["events"] += b["events"]
    return merged


def build_member_rows(by_member: dict, profile_names: dict[str, str], prev_by_member: Optional[dict] = None) -> list[dict]:
    """By-member rows (one display name per bucket) + metrics/deltas. Pure."""
    cur = _member_display_agg(by_member, profile_names)
    prev = _member_display_agg(prev_by_member or {}, profile_names)
    rows = []
    for m in set(cur) | set(prev):
        metrics = _metrics(cur.get(m, _blank()), prev.get(m, _blank()))
        rows.append({"member": m, **metrics})
    rows.sort(key=lambda r: (-r["cost"], -r["tokens"], r["member"] == da._SYSTEM_MEMBER, r["member"].lower()))
    return rows


def build_daily_series(by_day: dict, start: date, end: date) -> list[dict]:
    """Zero-filled per-day cost+token series (sparse for a huge range). Pure."""
    span = (end - start).days
    if 0 <= span <= 366:
        out = []
        d = start
        while d <= end:
            iso = d.isoformat()
            b = by_day.get(iso)
            out.append({
                "date": iso,
                "cost": round(b["cost"], 4) if b else 0.0,
                "tokens": (b["input_tokens"] + b["output_tokens"]) if b else 0,
            })
            d += timedelta(days=1)
        return out
    return [
        {"date": k, "cost": round(b["cost"], 4), "tokens": b["input_tokens"] + b["output_tokens"]}
        for k, b in sorted(by_day.items())
    ]


def total_block(cur_total: dict, prev_total: dict) -> dict[str, Any]:
    """The headline total metric block. Pure."""
    return _metrics(cur_total, prev_total)


# ── impure: pull the view + resolve names ────────────────────────────────────

def _fetch_events(supabase, start: date, end: date, client_id: Optional[str]) -> tuple[list[dict], bool]:
    lo = datetime(start.year, start.month, start.day, tzinfo=timezone.utc).isoformat()
    hi = (datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)).isoformat()
    events: list[dict] = []
    offset = 0
    truncated = False
    while True:
        q = (
            supabase.table("cost_events")
            .select("event_id, cost_type, client_id, actor_id, actor_name, occurred_at, cost_usd, input_tokens, output_tokens")
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


_EMPTY = {"by_type": {}, "by_client": {}, "by_member": {}, "by_day": {}, "total": _blank()}


def build_report(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    client_id: Optional[str] = None,
    compare: bool = True,
) -> dict[str, Any]:
    """The admin Cost & Usage Report payload for a date range (defaults to the
    last 30 days), optionally scoped to one client, with a previous-period
    comparison when `compare`."""
    start = da._parse_date(date_from)
    end = da._parse_date(date_to)
    if not start or not end:
        d_start, d_end = da._default_range()
        start = start or d_start
        end = end or d_end
    if end < start:
        start, end = end, start

    supabase = get_supabase()
    events, truncated = _fetch_events(supabase, start, end, client_id)
    tallies = aggregate(events)

    prev_start = prev_end = None
    prev = dict(_EMPTY)
    prev_truncated = False
    if compare:
        prev_start, prev_end = da.previous_window(start, end)
        prev_events, prev_truncated = _fetch_events(supabase, prev_start, prev_end, client_id)
        prev = aggregate(prev_events)

    client_ids = {c for c in tallies["by_client"] if c} | {c for c in prev["by_client"] if c}
    names = da._client_names(supabase, client_ids)
    profile_ids = (
        {k for (kind, k) in tallies["by_member"] if kind == "profile" and k}
        | {k for (kind, k) in prev["by_member"] if kind == "profile" and k}
    )
    profile_names = da._profile_names(supabase, profile_ids)

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "prev_from": prev_start.isoformat() if prev_start else None,
        "prev_to": prev_end.isoformat() if prev_end else None,
        "compare": compare,
        "client_id": client_id,
        "total": total_block(tallies["total"], prev["total"]),
        "truncated": truncated or prev_truncated,
        "by_type": build_type_rows(tallies["by_type"], prev["by_type"]),
        "by_client": build_client_rows(tallies["by_client"], names, prev["by_client"]),
        "by_member": build_member_rows(tallies["by_member"], profile_names, prev["by_member"]),
        "daily": build_daily_series(tallies["by_day"], start, end),
    }
