"""Context assembly (DB reads) — the cross-module client context, the
portfolio snapshot, and the durable-memory store.

Every module SerMastr can see is a provider in `_CONTEXT_PROVIDERS`; see
`build_context` for the extension recipe.

Part of the `services.slack_assistant` package; see its docstring for the
full picture."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services.slack_assistant.helpers import (
    build_maps_trend,
    group_maps_series,
    is_local_client,
    weak_cities,
)

_MAPS_TREND_SCANS = 4  # completed scans folded into the per-keyword trend summary

logger = logging.getLogger(__name__)


def build_context(client_id: str, today: Optional[date] = None) -> dict:
    """Assemble a per-client, cross-module context for the assistant.

    Runs every registered module provider (see `_CONTEXT_PROVIDERS`), each isolated
    so one module's failure or empty result never breaks the answer. A provider
    returning a falsy value is omitted entirely, so the LLM can tell "no data for
    this module" from real data.

    **To give SerMastr a new module:** write a `_ctx_<module>(supabase, client_id,
    today)` provider returning a compact dict (or None), and append it to
    `_CONTEXT_PROVIDERS`. It flows into every answer automatically — no other change.
    """
    supabase = get_supabase()
    today = today or date.today()
    ctx: dict = {}
    for key, provider in _CONTEXT_PROVIDERS:
        try:
            section = provider(supabase, client_id, today)
            if section:
                ctx[key] = section
        except Exception as exc:
            logger.warning(
                "slack_ctx_provider_failed",
                extra={"client_id": client_id, "ctx_module": key, "error": str(exc)},
            )
    return ctx


def build_portfolio_context() -> dict:
    """Cross-client attention snapshot for portfolio-mode turns (no client named).

    Counts only — cheap batch reads, one per table, each isolated so a missing
    table/column never breaks the turn. The per-client detail stays in
    `build_context`; this answers "who needs attention?" at agency altitude.
    """
    supabase = get_supabase()
    clients = (
        supabase.table("clients").select("id, name, website_url").order("name").execute()
    ).data or []

    def _counts(table: str, filters) -> dict[str, int]:
        try:
            q = supabase.table(table).select("client_id")
            rows = filters(q).execute().data or []
        except Exception as exc:
            logger.warning("portfolio_ctx_read_failed", extra={"table": table, "error": str(exc)})
            return {}
        out: dict[str, int] = {}
        for r in rows:
            cid = r.get("client_id")
            if cid:
                out[cid] = out.get(cid, 0) + 1
        return out

    rank_drops = _counts("rank_alerts", lambda q: q.is_("resolved_at", "null"))
    maps_alerts = _counts("maps_alerts", lambda q: q.is_("resolved_at", "null"))
    offpage = _counts("offpage_alerts", lambda q: q.is_("resolved_at", "null"))
    unread = _counts("notifications", lambda q: q.eq("status", "unread"))
    open_goals = _counts("campaign_goals", lambda q: q.is_("achieved_at", "null"))
    frozen = set(_counts("client_freezes", lambda q: q.eq("status", "active")))

    return {
        "clients": [
            {
                "name": c.get("name"),
                "frozen": c["id"] in frozen,
                "open_rank_drops": rank_drops.get(c["id"], 0),
                "open_maps_alerts": maps_alerts.get(c["id"], 0),
                "open_offpage_alerts": offpage.get(c["id"], 0),
                "open_goals": open_goals.get(c["id"], 0),
                "unread_notifications": unread.get(c["id"], 0),
            }
            for c in clients
        ],
        "client_count": len(clients),
    }


# --- Module context providers (each: (supabase, client_id, today) -> dict|None) ---
def _ctx_organic_rank(supabase, client_id: str, today: date) -> Optional[dict]:
    """Organic rank tracker: keywords + rank/trend, open drops, Action Plan, GSC."""
    from services import rank_status

    out: dict = {}
    kws = (
        supabase.table("tracked_keywords")
        .select("id, keyword, status")
        .eq("client_id", client_id)
        .eq("active", True)
        .order("keyword")
        .limit(settings.slack_assistant_max_keywords)
        .execute()
    ).data or []
    if kws:
        kw_ids = [k["id"] for k in kws]
        metrics: dict[str, list[dict]] = {}
        cutoff = date.fromordinal(today.toordinal() - 90).isoformat()
        for r in (
            supabase.table("rank_keyword_metrics")
            .select("keyword_id, date, gsc_position, tracked_rank")
            .in_("keyword_id", kw_ids)
            .gte("date", cutoff)
            .execute()
        ).data or []:
            metrics.setdefault(r["keyword_id"], []).append(r)
        out["keywords"] = [
            {
                "keyword": k["keyword"],
                "status": k.get("status"),
                "current_rank": (s := rank_status.compute_keyword_summary(
                    metrics.get(k["id"], []), today, settings.rank_gsc_coverage_days
                )).get("today_rank"),
                "avg_30d": s.get("avg_30"),
                "direction": s.get("direction"),
            }
            for k in kws
        ]
        out["keyword_count"] = len(kws)

    alerts = (
        supabase.table("rank_alerts")
        .select("keyword, alert_type, message")
        .eq("client_id", client_id)
        .is_("resolved_at", "null")
        .execute()
    ).data or []
    if alerts:
        out["open_drop_alerts"] = alerts

    plan = (
        supabase.table("reopt_plans")
        .select("summary, items, action_count, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if plan:
        p = plan[0]
        out["action_plan"] = {
            "summary": p.get("summary"),
            "action_count": p.get("action_count"),
            "top_actions": [
                {"keyword": a.get("keyword"), "recommendation": a.get("recommendation")}
                for a in (p.get("items") or [])[:8]
            ],
        }

    gsc = (
        supabase.table("gsc_research_runs")
        .select("cannibalization, hidden_wins, quick_wins, created_at")
        .eq("client_id", client_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if gsc:
        g = gsc[0]
        cann = g.get("cannibalization") or []
        quick = g.get("quick_wins") or []
        hidden = g.get("hidden_wins") or []
        out["gsc_opportunities"] = {
            "counts": {
                "cannibalization": len(cann),
                "quick_wins": len(quick),
                "hidden_wins": len(hidden),
            },
            "cannibalization": [
                {"query": c.get("query"), "competing_pages": len(c.get("pages") or [])}
                for c in cann[:5]
            ],
            "quick_wins": [
                {"keyword": w.get("keyword"), "position": w.get("position"),
                 "impressions": w.get("impressions"), "page": w.get("page")}
                for w in quick[:8]
            ],
            "hidden_wins": [
                {"keyword": w.get("keyword"), "position": w.get("position"),
                 "impressions": w.get("impressions"), "page": w.get("page")}
                for w in hidden[:8]
            ],
        }
    return out or None


def _ctx_maps(supabase, client_id: str, today: date) -> Optional[dict]:
    """Maps geo-grid: latest scan status + per-keyword average rank / pin coverage."""
    scan = (
        supabase.table("maps_scans")
        .select("id, status, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not scan:
        return None
    s = scan[0]
    out: dict = {"latest_scan_status": s.get("status"), "latest_scan_at": s.get("created_at")}
    results = (
        supabase.table("maps_scan_results")
        .select("keyword, average_rank, top3_pins, top10_pins, report_weak_locations")
        .eq("scan_id", s["id"])
        .limit(15)
        .execute()
    ).data or []
    if results:
        out["keywords"] = [
            {
                "keyword": r.get("keyword"),
                "average_rank": r.get("average_rank"),
                "top3_pins": r.get("top3_pins"),
                "top10_pins": r.get("top10_pins"),
            }
            for r in results
        ]
        weak: list[str] = []
        for r in results:
            for city in weak_cities(r.get("report_weak_locations")):
                if city not in weak:
                    weak.append(city)
        if weak:
            out["weak_coverage_areas"] = weak[:10]
    # Trend: last few COMPLETED scans → per-keyword pack-presence direction, so
    # the assistant can see movement, not just the latest snapshot. The full
    # series lives behind the maps_history tool; this is the at-a-glance read.
    completed = (
        supabase.table("maps_scans")
        .select("id, completed_at")
        .eq("client_id", client_id)
        .eq("status", "complete")
        .order("completed_at", desc=True)
        .limit(_MAPS_TREND_SCANS)
        .execute()
    ).data or []
    if len(completed) >= 2:
        rows = (
            supabase.table("maps_scan_results")
            .select("scan_id, keyword, average_rank, found_pins, total_pins, top3_pins")
            .in_("scan_id", [c["id"] for c in completed])
            .execute()
        ).data or []
        series = group_maps_series(completed, rows)
        trend = [build_maps_trend(kw, series[kw]) for kw in sorted(series) if len(series[kw]) >= 2]
        if trend:
            out["trend"] = trend[:15]
            out["trend_note"] = (
                "pack_presence_pct (top-3 pins / total) is the honest coverage number — read "
                "it first; average_rank is over FOUND pins only. Negative average_rank_delta / "
                "positive pack_presence_delta = improvement. Call the maps_history tool for the "
                "full dated series and older scans."
            )
    alerts = (
        supabase.table("maps_alerts")
        .select("keyword, alert_type, message, triggered_on")
        .eq("client_id", client_id)
        .is_("resolved_at", "null")
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    ).data or []
    if alerts:
        out["open_alerts"] = alerts
    return out


def _ctx_ai_visibility(supabase, client_id: str, today: date) -> Optional[dict]:
    """AI Visibility: tracked-keyword count + latest scan's per-engine visibility."""
    kw_count = (
        supabase.table("brand_tracked_keywords")
        .select("id", count="exact")
        .eq("client_id", client_id)
        .eq("is_active", True)
        .execute()
    ).count or 0
    # Pin the latest batch id first, then fetch that whole batch — a batch is
    # (keywords × engines) rows, so a single capped query could truncate it and
    # undercount visibility for clients with many tracked keywords.
    newest = (
        supabase.table("brand_mention_history")
        .select("scan_batch_id, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not (kw_count or newest):
        return None
    out: dict = {"keywords_tracked": kw_count}
    if newest:
        latest_batch = newest[0]["scan_batch_id"]
        batch = (
            supabase.table("brand_mention_history")
            .select("keyword_id, engine, mention_found")
            .eq("client_id", client_id)
            .eq("scan_batch_id", latest_batch)
            .execute()
        ).data or []
        out["latest_scan_at"] = newest[0].get("created_at")
        per_engine: dict[str, dict] = {}
        for r in batch:
            e = per_engine.setdefault(r.get("engine") or "?", {"found": 0, "total": 0})
            e["total"] += 1
            if r.get("mention_found"):
                e["found"] += 1
        out["per_engine_visibility"] = {k: f"{v['found']}/{v['total']}" for k, v in per_engine.items()}
        seen, visible = set(), set()
        for r in batch:
            seen.add(r.get("keyword_id"))
            if r.get("mention_found"):
                visible.add(r.get("keyword_id"))
        out["invisible_keyword_count"] = len(seen - visible)
    return out


def _ctx_content(supabase, client_id: str, today: date) -> Optional[dict]:
    """Content produced: completed blog/service/location runs + Local SEO pages.

    Uses `count="exact"` + limit(1) (one-row transfer) — these counts can grow
    large for an active client and we only need the totals. NOT head=True: the
    pinned postgrest discards the count on HEAD responses (always reads 0).
    """
    out: dict = {}
    by_type: dict[str, int] = {}
    for t in ("blog_post", "service_page", "location_page"):
        n = (
            supabase.table("runs")
            .select("id", count="exact")
            .eq("client_id", client_id)
            .eq("status", "complete")
            .eq("content_type", t)
            .limit(1)
            .execute()
        ).count or 0
        if n:
            by_type[t] = n
    if by_type:
        out["completed_runs_by_type"] = by_type

    saved = (
        supabase.table("local_seo_pages")
        .select("id", count="exact")
        .eq("client_id", client_id)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    ).count or 0
    if saved:
        published = (
            supabase.table("local_seo_pages")
            .select("id", count="exact")
            .eq("client_id", client_id)
            .is_("deleted_at", "null")
            .not_.is_("published_doc_id", "null")
            .limit(1)
            .execute()
        ).count or 0
        out["local_seo_pages_saved"] = saved
        out["local_seo_pages_published"] = published

    recent_runs = (
        supabase.table("runs")
        .select("keyword, content_type, created_at")
        .eq("client_id", client_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(8)
        .execute()
    ).data or []
    if recent_runs:
        out["recent_completed_runs"] = recent_runs
    recent_pages = (
        supabase.table("local_seo_pages")
        .select("keyword, created_at")
        .eq("client_id", client_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=True)
        .limit(8)
        .execute()
    ).data or []
    if recent_pages:
        out["recent_local_seo_pages"] = recent_pages
    return out or None


def _ctx_keyword_research(supabase, client_id: str, today: date) -> Optional[dict]:
    """Topic Fanout keyword-research sessions (vendored fanout schema)."""
    from fanout.storage.supabase_client import get_service_client

    rows = (
        get_service_client()
        .table("sessions")
        .select("seed_keyword, status, created_at")
        .eq("client_id", client_id)
        .eq("archived", False)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    ).data or []
    if not rows:
        return None
    return {
        "session_count": len(rows),
        "recent_seeds": [r.get("seed_keyword") for r in rows[:5] if r.get("seed_keyword")],
    }


def _ctx_setup(supabase, client_id: str, today: date) -> Optional[dict]:
    """The client's full configured business profile.

    Everything captured on the client row goes in — the whole GBP profile
    (address, coordinates, phone, categories, rating, hours, service area…),
    target cities, campaign settings, ICP — except bulky raw assets (the GBP
    reviews array, the full brand guide), which stay presence flags so one
    client's context can't swamp the prompt.

    Local-only settings (target cities) are reported only when the client
    actually runs a local campaign (`is_local_client`); otherwise they read
    "n/a" so the model never flags an empty list as a setup gap for a
    national/non-local client.
    """
    rows = (
        supabase.table("clients")
        .select(
            "website_url, gbp, gbp_place_id, brand_voice, detected_icp, "
            "differentiators, icp_text, target_cities, retainer_monthly, "
            "is_sab, client_type, business_location"
        )
        .eq("id", client_id)
        .limit(1)
        .execute()
    ).data
    if not rows:
        return None
    c = rows[0]
    gbp = c.get("gbp") or {}
    local = is_local_client(c)
    if not local:
        # Nothing local on the client row itself — check for actual local work
        # before concluding suburb-level targeting doesn't apply.
        pages = (
            supabase.table("local_seo_pages")
            .select("id", count="exact")
            .eq("client_id", client_id)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        ).count or 0
        scans = (
            supabase.table("maps_scans")
            .select("id", count="exact")
            .eq("client_id", client_id)
            .limit(1)
            .execute()
        ).count or 0
        local = is_local_client(c, pages, scans)
    out: dict = {
        "website": c.get("website_url"),
        "client_type": c.get("client_type"),
        "is_sab": bool(c.get("is_sab")),
        "retainer_monthly": c.get("retainer_monthly"),
        "local_campaign": local,
        "target_cities": (c.get("target_cities") or [])[:12]
        if local
        else "n/a — no local campaign; suburb-level targeting does not apply",
        "has_brand_voice": bool(c.get("brand_voice")),
        "has_icp": bool(c.get("detected_icp") or c.get("differentiators")),
    }
    try:
        from services import icp_service

        icp = icp_service.resolve_icp_text(c) or ""
        if icp:
            out["icp_summary"] = icp[:1500]
    except Exception:
        pass
    try:
        from services.brand_voice_service import render_brand_voice_text

        bv = render_brand_voice_text(c.get("brand_voice")) or ""
        if bv:
            out["brand_voice_summary"] = bv[:800]
    except Exception:
        pass
    if gbp:
        out["gbp"] = {
            "business_name": gbp.get("business_name"),
            "place_id": c.get("gbp_place_id") or gbp.get("place_id"),
            "address": gbp.get("address"),
            "address_hidden": gbp.get("address_hidden"),
            "latitude": gbp.get("latitude"),
            "longitude": gbp.get("longitude"),
            "phone": gbp.get("phone"),
            "website": gbp.get("website"),
            "category": gbp.get("gbp_category"),
            "categories": (gbp.get("gbp_categories") or [])[:8],
            "rating": gbp.get("gbp_rating"),
            "review_count": gbp.get("gbp_review_count"),
            "hours": gbp.get("hours"),
            "google_maps_uri": gbp.get("google_maps_uri"),
            "service_area_places": (gbp.get("service_area_places") or [])[:10],
            "description": (gbp.get("description") or "")[:500] or None,
        }
    else:
        out["has_gbp"] = False
    return out


def _ctx_campaign_goals(supabase, client_id: str, today: date) -> Optional[dict]:
    """The client's success targets with deterministic status — lets 'how is
    the campaign going' lead with progress vs what was promised."""
    from services import campaign_goals

    assessed = campaign_goals.assess_goals(client_id, today=today)
    if not assessed:
        return None
    return {
        "goals": [
            {
                "label": g.get("label"),
                "status": g.get("status"),
                "current_value": g.get("current_value"),
                "target_value": g.get("target_value"),
                "progress_pct": g.get("progress_pct"),
                "due_date": g.get("due_date"),
                "note": g.get("note"),
            }
            for g in assessed
        ],
    }


def _ctx_backlinks(supabase, client_id: str, today: date) -> Optional[dict]:
    """Backlink Explorer — tracked domains' authority (DR / referring domains /
    pages) + the client's own-domain link velocity (gained/lost since the
    previous weekly snapshot, with domain names)."""
    from services import backlink_explorer

    tracked = backlink_explorer.list_tracked(client_id)
    if not tracked:
        return None
    out: dict = {
        "tracked_domains": [
            {
                "domain": t.get("label") or t.get("target"),
                "dr": (t.get("latest") or {}).get("domain_rating"),
                "referring_domains": (t.get("latest") or {}).get("referring_domains"),
                "backlinks": (t.get("latest") or {}).get("backlinks"),
                "linked_pages": (t.get("latest") or {}).get("pages_count"),
                "new_domains_last_check": (t.get("latest") or {}).get("new_domains"),
                "lost_domains_last_check": (t.get("latest") or {}).get("lost_domains"),
                "as_of": (t.get("latest") or {}).get("captured_at"),
            }
            for t in tracked[:6]
        ],
        "note": "DR/RD are DataForSEO tool reads; new/lost counts are vs the previous weekly snapshot",
    }
    velocity = backlink_explorer.client_own_domain_change(client_id)
    if velocity and (velocity.get("new_sample") or velocity.get("lost_sample")):
        out["own_domain_velocity"] = {
            "new_sample": velocity.get("new_sample"),
            "lost_sample": velocity.get("lost_sample"),
            "as_of": velocity.get("captured_at"),
        }
    return out


def _ctx_competitors(supabase, client_id: str, today: date) -> Optional[dict]:
    """Assembled competitor profiles so competitive questions get real data."""
    from services import competitor_intel

    assembled = competitor_intel.build_profiles(client_id, today=today)
    profiles = assembled.get("competitors") or []
    if not profiles:
        return None
    return {
        "client_comparison": assembled.get("client"),
        "competitors": [
            {
                "name": p.get("name"),
                "domain": p.get("domain"),
                "local_pack": p.get("local_pack"),
                "gbp": p.get("gbp"),
                "backlinks": p.get("backlinks"),
                "organic": p.get("organic"),
                "review_velocity_30d": p.get("review_velocity_30d"),
                "new_pages_30d": p.get("new_pages_30d"),
            }
            for p in profiles[:6]
        ],
    }


def _ctx_domain_intel(supabase, client_id: str, today: date) -> Optional[dict]:
    """Competitor keyword + backlink gaps (Domain Intelligence) so competitive
    'what should we target' questions get concrete, data-grounded answers."""
    kw = (
        supabase.table("domain_keyword_gaps")
        .select("keyword, competitor_domain, competitor_position, client_position, volume, gap_type, opportunity_score")
        .eq("client_id", client_id).order("opportunity_score", desc=True).limit(10).execute()
    ).data or []
    links = (
        supabase.table("domain_link_gaps")
        .select("referring_domain, linking_to, referring_domain_rank")
        .eq("client_id", client_id)
        .order("referring_domain_rank", desc=True, nullsfirst=False).limit(8).execute()
    ).data or []
    if not kw and not links:
        return None
    return {
        "keyword_gaps": kw,
        "link_gaps": links,
        "note": ("keywords/referring domains competitors have that the client lacks; opportunity_score "
                 "higher = pursue first. gap_type missing = client absent, weak = ranks poorly."),
    }


def _ctx_forecast(supabase, client_id: str, today: date) -> Optional[dict]:
    """Deterministic projections so 'where is this heading / what's it worth'
    questions get computed numbers, never invented ones."""
    from services import forecasting

    fc = forecasting.build_forecast(client_id, today=today)
    if not fc.get("keyword_count"):
        return None
    return {
        "note": fc.get("note"),
        "portfolio": fc.get("portfolio"),
        "gsc_clicks_trajectory": fc.get("gsc_clicks_trajectory"),
        "quick_wins_summary": {
            k: v for k, v in (fc.get("quick_wins") or {}).items() if k != "keywords"
        },
        "quick_wins_top": (fc.get("quick_wins") or {}).get("keywords", [])[:6],
        "goal_projections": fc.get("goal_projections"),
    }


def _ctx_trends(supabase, client_id: str, today: date) -> Optional[dict]:
    """Cross-client algo-update events + this client's seasonal demand read."""
    from services import trend_watch

    events = trend_watch.recent_algo_events()
    outlook = None
    try:
        outlook = trend_watch.build_demand_outlook(client_id, today=today)
    except Exception:
        pass
    if not events and not outlook:
        return None
    return {
        "algo_events": [
            {
                "window_start": e.get("window_start"),
                "window_end": e.get("window_end"),
                "clients_affected": e.get("clients_affected"),
                "clients_total": e.get("clients_total"),
            }
            for e in events[:3]
        ],
        "demand_outlook": outlook,
    }


def _ctx_task_plan(supabase, client_id: str, today: date) -> Optional[dict]:
    """Latest Recipe Engine monthly task plan — budget, flags, assigned lines."""
    rows = (
        supabase.table("monthly_task_plans")
        .select("month, margin_used, deployable, spent, remaining, flags, plan, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not rows:
        return None
    p = rows[0]
    plan = p.get("plan") or {}
    return {
        "month": p.get("month"),
        "margin_used": p.get("margin_used"),
        "deployable": p.get("deployable"),
        "spent": p.get("spent"),
        "remaining": p.get("remaining"),
        "flags": p.get("flags") or [],
        "diagnosis": plan.get("diagnosis"),
        "tasks": [
            {
                "task": t.get("label"),
                "quantity": t.get("quantity"),
                "line_cost": t.get("line_cost"),
                "assignee": t.get("assignee"),
            }
            for t in (plan.get("tasks") or [])[:15]
        ],
    }


def _ctx_qa(supabase, client_id: str, today: date) -> Optional[dict]:
    """QA Agent — recent deliverable-review verdicts (last 30 days, latest per
    task): counts by verdict plus the failing / needs-human tasks with their
    open issues, so 'how did QA go on X' answers from real reviews."""
    since = (today - timedelta(days=30)).isoformat()
    rows = (
        supabase.table("qa_reviews")
        .select("task_id, rubric, verdict, issues, narrative, created_at")
        .eq("client_id", client_id)
        .gte("created_at", since)
        .order("created_at", desc=True)
        .limit(60)
        .execute()
    ).data or []
    if not rows:
        return None
    latest: dict[str, dict] = {}
    for r in rows:  # newest-first → first seen per task wins
        latest.setdefault(r["task_id"], r)
    by_verdict: dict[str, int] = {}
    for r in latest.values():
        by_verdict[r.get("verdict") or "unknown"] = by_verdict.get(r.get("verdict") or "unknown", 0) + 1
    out: dict = {"reviewed_tasks": len(latest), "by_verdict": by_verdict}
    attention = [r for r in latest.values() if r.get("verdict") in ("fail", "needs_human")]
    if attention:
        ids = [r["task_id"] for r in attention[:6]]
        names = {
            t["id"]: t.get("name")
            for t in (
                supabase.table("tasks").select("id, name").in_("id", ids).execute()
            ).data or []
        }
        out["needs_attention"] = [
            {
                "task": names.get(r["task_id"]) or r["task_id"],
                "verdict": r.get("verdict"),
                "issues": (r.get("issues") or [])[:4],
            }
            for r in attention[:6]
        ]
    return out


def _ctx_citations(supabase, client_id: str, today: date) -> Optional[dict]:
    """Citation liveness — status counts plus the currently-dead URLs."""
    rows = (
        supabase.table("client_citations")
        .select("url, status, last_checked_at")
        .eq("client_id", client_id)
        .execute()
    ).data or []
    if not rows:
        return None
    by_status: dict[str, int] = {}
    for r in rows:
        s = r.get("status") or "unknown"
        by_status[s] = by_status.get(s, 0) + 1
    out: dict = {"total": len(rows), "by_status": by_status}
    dead = [r["url"] for r in rows if r.get("status") == "dead"]
    if dead:
        out["dead_urls"] = dead[:8]
    return out


def _ctx_syndication(supabase, client_id: str, today: date) -> Optional[dict]:
    """Content syndication — config plus discovered/published item counts."""
    cfg = (
        supabase.table("syndication_config")
        .select("enabled, share_mode, last_scan_date")
        .eq("client_id", client_id)
        .limit(1)
        .execute()
    ).data
    by_status: dict[str, int] = {}
    for s in ("discovered", "rewriting", "published", "failed", "skipped"):
        n = (
            supabase.table("syndication_items")
            .select("id", count="exact")
            .eq("client_id", client_id)
            .eq("status", s)
            .limit(1)
            .execute()
        ).count or 0
        if n:
            by_status[s] = n
    if not (cfg or by_status):
        return None
    out: dict = {"items_by_status": by_status}
    if cfg:
        c = cfg[0]
        out["enabled"] = c.get("enabled")
        out["share_mode"] = c.get("share_mode")
        out["last_scan_date"] = c.get("last_scan_date")
    return out


def _ctx_reports(supabase, client_id: str, today: date) -> Optional[dict]:
    """Client reports — recent generated reports + the delivery schedule."""
    reports = (
        supabase.table("client_reports")
        .select("report_type, status, title, period_start, period_end, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    ).data or []
    cfg = (
        supabase.table("client_report_settings")
        .select("*")
        .eq("client_id", client_id)
        .limit(1)
        .execute()
    ).data
    if not (reports or cfg):
        return None
    out: dict = {}
    if reports:
        out["recent_reports"] = reports
    if cfg:
        c = cfg[0]
        out["schedule"] = {
            "cadence": c.get("cadence"),
            "recipient_count": len(c.get("recipients") or []),
            "email_enabled": c.get("email_enabled"),
            "drive_enabled": c.get("drive_enabled"),
            "coverage": c.get("coverage"),
            "next_run_at": c.get("next_run_at"),
        }
    return out


def _ctx_sops(supabase, client_id: str, today: date) -> Optional[dict]:
    """Loaded SOPs — titles only (the Action Plan/strategist consume the bodies)."""
    from services import sop_store

    rows = sop_store.list_sops(client_id)
    if not rows:
        return None
    return {
        "count": len(rows),
        "sops": [
            {
                "title": r.get("title"),
                "category": r.get("category"),
                "scope": "client" if r.get("client_id") else "agency",
            }
            for r in rows[:20]
        ],
    }


def _ctx_asana(supabase, client_id: str, today: date) -> Optional[dict]:
    """Asana setup — whether a project is mapped + the monthly task templates."""
    proj = (
        supabase.table("asana_client_projects")
        .select("project_gid")
        .eq("client_id", client_id)
        .limit(1)
        .execute()
    ).data
    templates = (
        supabase.table("asana_client_task_templates")
        .select("name, assignee_name, category_name")
        .eq("client_id", client_id)
        .eq("active", True)
        .order("sort_order")
        .limit(20)
        .execute()
    ).data or []
    if not (proj or templates):
        return None
    out: dict = {"project_mapped": bool(proj)}
    if templates:
        out["monthly_task_templates"] = templates
    return out


def _ctx_health(supabase, client_id: str, today: date) -> Optional[dict]:
    """Campaign health guards — freeze state, open response episodes, offpage alerts."""
    out: dict = {}
    try:
        from services import freeze

        fr = freeze.active_freeze(client_id)
        if fr:
            out["freeze"] = {
                "reason": fr.get("reason"),
                "since": fr.get("created_at"),
                "note": fr.get("note"),
            }
    except Exception:
        pass
    episodes = (
        supabase.table("response_episodes")
        .select("channel, keyword, classification, status, opened_at, last_checked_at")
        .eq("client_id", client_id)
        .in_("status", ["open", "escalated"])
        .order("opened_at", desc=True)
        .limit(10)
        .execute()
    ).data or []
    if episodes:
        out["response_episodes"] = episodes
    offpage = (
        supabase.table("offpage_alerts")
        .select("alert_type, message, from_rd, to_rd, delta_pct, triggered_on")
        .eq("client_id", client_id)
        .is_("resolved_at", "null")
        .execute()
    ).data or []
    if offpage:
        out["offpage_alerts"] = offpage
    return out or None


def _ctx_strategist(supabase, client_id: str, today: date) -> Optional[dict]:
    """Latest completed strategist review — assessment, proposals, open questions."""
    rows = (
        supabase.table("strategy_reviews")
        .select("assessment, proposals, questions, trigger, created_at")
        .eq("client_id", client_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not rows:
        return None
    r = rows[0]
    return {
        "reviewed_at": r.get("created_at"),
        "trigger": r.get("trigger"),
        "assessment": (r.get("assessment") or "")[:1200] or None,
        "proposals": [
            {"title": p.get("title"), "status": p.get("status"), "requires": p.get("requires")}
            for p in (r.get("proposals") or [])[:8]
        ],
        "questions": (r.get("questions") or [])[:5],
    }


# --- Durable memory (the `remember` tool + the memories context module) -----
_MEMORY_CONTEXT_LIMIT = 30  # newest notes folded into each answer's context
_MEMORY_KEEP = 100  # hard per-client cap — oldest rows trimmed past this

_MEMORY_TOOL = {
    "name": "remember",
    "description": (
        "Save one short durable note about this client to your long-term memory "
        "(free — no confirmation; it appears in the `memories` module of every "
        "future conversation about them). Use it when the conversation produces "
        "something worth recalling weeks later: a decision, a commitment ('we'll "
        "push location pages next month'), a client fact the suite doesn't track, "
        "a teammate/owner preference, a deadline. Don't save data the suite "
        "already tracks (ranks, alerts, goals) or conversational trivia."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "The note — one short, self-contained sentence.",
            }
        },
        "required": ["note"],
    },
}


def _run_remember(client_id: str, args: dict, source: str) -> str:
    """Persist one memory note; trims the store past the per-client cap."""
    note = str(args.get("note") or "").strip()
    if not note:
        return "Nothing to save — pass a short note."
    supabase = get_supabase()
    supabase.table("assistant_memories").insert(
        {"client_id": client_id, "content": note[:500], "source": source}
    ).execute()
    overflow = (
        supabase.table("assistant_memories")
        .select("id")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .range(_MEMORY_KEEP, _MEMORY_KEEP + 50)
        .execute()
    ).data or []
    if overflow:
        supabase.table("assistant_memories").delete().in_(
            "id", [r["id"] for r in overflow]
        ).execute()
    return "Saved to memory."


def _ctx_memories(supabase, client_id: str, today: date) -> Optional[dict]:
    """Durable notes saved by the `remember` tool in past conversations."""
    rows = (
        supabase.table("assistant_memories")
        .select("content, source, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(_MEMORY_CONTEXT_LIMIT)
        .execute()
    ).data or []
    if not rows:
        return None
    return {
        "notes": [
            {
                "note": r["content"],
                "when": str(r.get("created_at") or "")[:10],
                "source": r.get("source"),
            }
            for r in rows
        ]
    }


# Registry — append a provider here to give SerMastr a new module (see build_context).
_CONTEXT_PROVIDERS = [
    ("campaign_goals", _ctx_campaign_goals),
    ("memories", _ctx_memories),
    ("competitors", _ctx_competitors),
    ("domain_intel", _ctx_domain_intel),
    ("backlinks", _ctx_backlinks),
    ("forecast", _ctx_forecast),
    ("trends", _ctx_trends),
    ("organic_rank", _ctx_organic_rank),
    ("maps_geogrid", _ctx_maps),
    ("ai_visibility", _ctx_ai_visibility),
    ("content", _ctx_content),
    ("keyword_research", _ctx_keyword_research),
    ("task_plan", _ctx_task_plan),
    ("qa", _ctx_qa),
    ("citations", _ctx_citations),
    ("syndication", _ctx_syndication),
    ("reports", _ctx_reports),
    ("sops", _ctx_sops),
    ("asana", _ctx_asana),
    ("health", _ctx_health),
    ("strategist_review", _ctx_strategist),
    ("setup", _ctx_setup),
]
