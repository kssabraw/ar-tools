"""Organic Rank Analysis — the per-keyword deep-dive (Organic Rank Tracker #4).

The organic analogue of the Maps "Local Rank Analysis" report. Where the
geo-grid report runs deterministic geometry over a grid of pins (ring × octant
rollups, weak-zone scoring) before a narrative, this assembles the two dense
measurements organic already captures — the client's **rank trajectory** (the
materialized GSC/DataForSEO date axis) and the **competitive SERP landscape**
(the latest Competitive SERP Snapshot: top-10 with UR/DR/RD, targeting, topical
focus, AIO, intent) — into one dated per-keyword picture, then hands a
fully-computed snapshot to Claude for observational narrative.

The analytical dimensions (all deterministic, the LLM never does the arithmetic):
  * TRAJECTORY (the "distance rings" analog) — status taxonomy + rolling
    positions + a forecast slope/projection: is the keyword climbing, stalling,
    or declining, and how fast (`trajectory_verdict`).
  * COMPETITIVE LANDSCAPE (the "compass octants" analog) — the top-10 decomposed
    by *why each competitor above the client is ahead*: authority (RD/UR/DR),
    targeting, topical focus, AIO squeeze (`build_competitor_breakdown`).
  * WINNABILITY — the rankability score + factors (reused from `rankability`).
  * GAP-TO-CLOSE WORK ORDER (the "weak-area priority" analog) — the ranked list
    of blockers between the client and top-3, each with a leverage score and a
    CTA into the tool that closes it (`authority_gap` + `build_work_order`).
  * WHAT CHANGED (the "weak-area names" analog) — SERP timeline deltas + drop
    classification if an alert is open.

The pure helpers (no I/O) are unit-tested; `build_keyword_analysis` does the
reads and assembles the `report_analytics` blob that both the LLM narrative and
the frontend render from. Heuristic + tunable — weights/thresholds are module
constants (a subset is promoted to config where the report job needs them).
"""

from __future__ import annotations

import logging
from datetime import date
from statistics import median
from typing import Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# --- Tunable thresholds (module constants; start conservative) --------------
# An authority advantage counts as the *primary* reason a competitor is ahead
# only when it clears both an absolute and a relative bar (so small-profile
# noise and large-profile parity don't misattribute).
_RD_ADVANTAGE_ABS = 10      # referring-domain lead in absolute count
_RD_ADVANTAGE_MULT = 1.5    # ...and ≥1.5× the client's RD

# Striking-distance band (below the fold → page 2): the sweet spot where a
# push has the most leverage. Mirrors forecasting._STRIKING_DISTANCE.
_STRIKING_LO, _STRIKING_HI = 4.0, 20.0

# Urgency multipliers on the priority score by trajectory/alert state.
_URGENCY = {
    "alert": 1.5,       # an open rank-drop alert — intervene now
    "dropping": 1.4,
    "striking": 1.25,   # in the striking-distance band — close to a win
    "volatile": 1.15,
    "stable": 1.0,
    "climbing": 0.85,   # already moving the right way — less need to intervene
    "won": 0.5,         # stable in the top 3 — defend only
}


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def _num(v) -> bool:
    """True for real numeric values (ints/floats), excluding bool."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _med(nums) -> Optional[float]:
    vals = [n for n in nums if _num(n)]
    return round(float(median(vals)), 1) if vals else None


def trajectory_verdict(summary: dict, forecast: dict, status: Optional[str]) -> dict:
    """The trajectory story — the organic analog of the geo-grid performance
    horizon. Fuses the status taxonomy with the forecast slope/projection into
    a single direction + velocity read. Pure.

    `summary` is a rank_status.compute_keyword_summary dict, `forecast` a
    forecasting.forecast_keyword dict, `status` the tracked_keywords.status label.
    """
    source = summary.get("primary_source")
    current = forecast.get("current_position")
    trend = forecast.get("trend_per_week")  # negative = improving (position falling)

    # Velocity label from the weekly slope (positions/week). None slope = flat.
    if trend is None:
        velocity = "flat"
    elif trend <= -2.0:
        velocity = "improving_fast"
    elif trend < -0.3:
        velocity = "improving"
    elif trend >= 2.0:
        velocity = "declining_fast"
    elif trend > 0.3:
        velocity = "declining"
    else:
        velocity = "holding"

    return {
        "status": status,
        "primary_source": source,
        "current_position": current,
        "avg_7": summary.get("avg_7"),
        "avg_30": summary.get("avg_30"),
        "avg_90": summary.get("avg_90"),
        "clicks_30d": summary.get("clicks_30d"),
        "impressions_30d": summary.get("impressions_30d"),
        "ctr_30d": summary.get("ctr_30d"),
        "trend_per_week": trend,
        "velocity": velocity,
        "projected_position_30d": forecast.get("projected_position_30d"),
        "projected_position_90d": forecast.get("projected_position_90d"),
        "confidence": forecast.get("confidence"),
        "sparkline": summary.get("sparkline") or [],
    }


def _classify_advantage(
    comp_rd: Optional[float], comp_targeted: Optional[bool], comp_focus: Optional[str],
    client_rd: Optional[float], client_targeted: bool, client_focus: Optional[str],
) -> str:
    """Why is one top-10 competitor ahead of the client? Single primary reason.

    Precedence: a clear backlink lead → 'authority'; a dedicated/targeted page
    the client lacks → 'targeting'; a topic specialist over a generalist client
    → 'topical'; otherwise an established incumbent → 'established'. Pure.
    """
    if _num(comp_rd) and (
        comp_rd >= (client_rd or 0) * _RD_ADVANTAGE_MULT
        and comp_rd - (client_rd or 0) >= _RD_ADVANTAGE_ABS
    ):
        return "authority"
    if comp_targeted and not client_targeted:
        return "targeting"
    if comp_focus == "specialist" and client_focus == "generalist":
        return "topical"
    return "established"


def build_competitor_breakdown(
    client_rank: Optional[int],
    top_results: list[dict],
    dr_by_domain: dict[str, Optional[float]],
    client_authority: dict,
) -> list[dict]:
    """The top-10 competitors ranking ABOVE the client, each decomposed by why
    they're ahead. When the client isn't in the top-10, every top-10 competitor
    is 'above'. Ordered by position (closest to #1 first). Pure.

    `top_results` are serp_snapshot_results rows (position, url, domain, is_client,
    targeted, topical_focus, url_rating, referring_domains). `dr_by_domain` maps a
    domain → its domain_rating. `client_authority` carries the client's rd/ur/dr
    and whether its ranking page is targeted, for the gap deltas.
    """
    ceiling = client_rank if client_rank is not None else 11
    client_rd = client_authority.get("rd")
    client_targeted = bool(client_authority.get("targeted"))
    client_focus = client_authority.get("topical_focus")

    out: list[dict] = []
    for r in sorted(top_results, key=lambda x: x.get("position") or 99):
        pos = r.get("position")
        if pos is None or pos >= ceiling or r.get("is_client"):
            continue
        rd = r.get("referring_domains")
        ur = r.get("url_rating")
        dr = dr_by_domain.get(r.get("domain"))
        reason = _classify_advantage(
            rd, r.get("targeted"), r.get("topical_focus"),
            client_rd, client_targeted, client_focus,
        )
        out.append({
            "position": pos,
            "domain": r.get("domain"),
            "url": r.get("url"),
            "referring_domains": rd,
            "url_rating": ur,
            "domain_rating": dr,
            "targeted": r.get("targeted"),
            "topical_focus": r.get("topical_focus"),
            "rd_gap": (rd - client_rd) if (_num(rd) and _num(client_rd)) else None,
            "primary_reason": reason,
        })
    return out


def authority_gap(client_authority: dict, competitors: list[dict]) -> dict:
    """The backlink authority the client must close to match the top-10 — the
    deterministic 'gap to close' number. Medians over the competitors above the
    client (RD/UR/DR), and the deficit vs the client's own strongest page. Pure.
    """
    m_rd = _med([c.get("referring_domains") for c in competitors])
    m_ur = _med([c.get("url_rating") for c in competitors])
    m_dr = _med([c.get("domain_rating") for c in competitors])
    c_rd = client_authority.get("rd")
    c_ur = client_authority.get("ur")
    c_dr = client_authority.get("dr")
    return {
        "median_competitor_rd": m_rd,
        "median_competitor_ur": m_ur,
        "median_competitor_dr": m_dr,
        "client_rd": c_rd,
        "client_ur": c_ur,
        "client_dr": c_dr,
        # Referring domains the client needs to reach the median incumbent (the
        # single most actionable figure — the link-building target).
        "rd_to_match": (
            max(0, round(m_rd - (c_rd or 0))) if _num(m_rd) else None
        ),
        "ur_deficit": (round(m_ur - (c_ur or 0)) if _num(m_ur) else None),
        "dr_deficit": (round(m_dr - (c_dr or 0)) if _num(m_dr) else None),
    }


def urgency_key(status: Optional[str], has_open_alert: bool, position: Optional[float]) -> str:
    """The urgency bucket that scales the priority score. Pure."""
    if has_open_alert:
        return "alert"
    if status == "dropping":
        return "dropping"
    if status == "volatile":
        return "volatile"
    if _num(position) and position <= 3 and status in ("stable", "climbing", None):
        return "won"
    if _num(position) and _STRIKING_LO <= position <= _STRIKING_HI:
        return "striking"
    if status == "climbing":
        return "climbing"
    return "stable"


def compute_priority(
    rankability_score: Optional[int], est_value: Optional[float], urgency: str,
) -> Optional[float]:
    """The keyword's headline priority: winnability × potential value × urgency.
    The organic analog of the geo-grid weak-area opportunity score. Pure.

    winnability = rankability/100 (how realistically we can win it); est_value is
    the modelled monthly value at top-3; urgency floats a dropping/high-value
    keyword up and dampens one already won. None when unscorable.
    """
    if rankability_score is None or est_value is None:
        return None
    mult = _URGENCY.get(urgency, 1.0)
    return round(rankability_score / 100.0 * est_value * mult, 2)


def build_work_order(
    trajectory: dict,
    gap: dict,
    competitors: list[dict],
    winnability: dict,
    aio_present: bool,
    aio_sources: list[dict],
    client_rank: Optional[int],
    client_page_count: int,
    drop_classification: Optional[dict],
) -> list[dict]:
    """The ranked gap-to-close work order — for THIS keyword, what stands between
    the client and top-3, decomposed per blocker and ordered by leverage. The
    organic analog of the geo-grid's ranked weak areas. Pure.

    Each item: {type, headline, detail, severity (0-100), leverage (0-100), cta}.
    Leverage weights how much closing the gap should move the ranking; severity
    is the raw size of the gap. Sorted by leverage desc.
    """
    items: list[dict] = []

    # 1) Authority — the RD deficit vs the median incumbent. Highest leverage
    # when the client is close (striking distance) but out-linked.
    rd_to_match = gap.get("rd_to_match")
    if _num(rd_to_match) and rd_to_match > 0:
        pos = trajectory.get("current_position")
        close = _num(pos) and pos <= _STRIKING_HI
        severity = min(100, round(rd_to_match))
        leverage = min(100, round(rd_to_match * (1.6 if close else 1.0)))
        items.append({
            "type": "authority",
            "headline": f"Build ~{rd_to_match} referring domains to match the top-10",
            "detail": (
                f"The median top-10 page has {gap.get('median_competitor_rd')} referring "
                f"domains vs the client's {gap.get('client_rd') or 0}."
            ),
            "severity": severity,
            "leverage": leverage,
            "cta": "link_building",
        })

    # 2) Targeting — no dedicated/targeted client page, or a loose match ranking.
    targeting_competitors = [c for c in competitors if c.get("primary_reason") == "targeting"]
    if client_rank is None:
        items.append({
            "type": "targeting",
            "headline": "Create a page purpose-built for this query",
            "detail": "The client doesn't rank in the top-10 — no page is targeting this keyword.",
            "severity": 80,
            "leverage": 75,
            "cta": "create_page",
        })
    elif targeting_competitors:
        items.append({
            "type": "targeting",
            "headline": "Tighten the ranking page's on-page targeting",
            "detail": (
                f"{len(targeting_competitors)} competitor(s) above the client rank with a "
                "page tightly written for this query while the client's is a looser match."
            ),
            "severity": 55,
            "leverage": 60,
            "cta": "reoptimize_page",
        })

    # 3) Topical — incumbents are specialists (harder) or the client is the
    # specialist among generalists (an opening worth naming).
    focus = winnability.get("client_topical_focus")
    specialist_incumbents = [c for c in competitors if c.get("primary_reason") == "topical"]
    if focus == "specialist" and any(c.get("topical_focus") == "generalist" for c in competitors):
        items.append({
            "type": "topical_opening",
            "headline": "Lean into topical authority — incumbents are generalists",
            "detail": "The client is a topic specialist against generalist incumbents; content depth can offset weaker backlinks.",
            "severity": 30,
            "leverage": 50,
            "cta": "create_page",
        })
    elif specialist_incumbents:
        items.append({
            "type": "topical_gap",
            "headline": "Deepen topical coverage to compete with specialists",
            "detail": f"{len(specialist_incumbents)} incumbent(s) above the client are topic specialists.",
            "severity": 45,
            "leverage": 40,
            "cta": "create_page",
        })

    # 4) AIO squeeze — an AI Overview is taking click real-estate.
    if aio_present:
        cited = ", ".join(sorted({(s.get("domain") or "") for s in (aio_sources or []) if s.get("domain")})[:5])
        items.append({
            "type": "aio",
            "headline": "Target AI Overview citation",
            "detail": (
                "An AI Overview is present on this SERP"
                + (f"; cited sources include {cited}." if cited else ".")
            ),
            "severity": 40,
            "leverage": 35,
            "cta": "reoptimize_page",
        })

    # 5) Cannibalization — multiple client pages ranking, or a classified B1 drop.
    cannibalized = client_page_count > 1 or (drop_classification or {}).get("classification") == "B1"
    if cannibalized:
        items.append({
            "type": "cannibalization",
            "headline": "Consolidate competing client pages",
            "detail": (
                f"{client_page_count} of the client's own pages rank for this query — "
                "Google is splitting authority across them."
            ) if client_page_count > 1 else "Cannibalization detected in GSC Research for this query.",
            "severity": 50,
            "leverage": 55,
            "cta": "consolidate",
        })

    items.sort(key=lambda i: i["leverage"], reverse=True)
    return items


# ----------------------------------------------------------------------------
# DB assembly.
# ----------------------------------------------------------------------------
def _latest_snapshot(supabase, keyword_id: str) -> Optional[dict]:
    rows = (
        supabase.table("serp_snapshots")
        .select("id, keyword_id, captured_at, status, query_intent, intent_probabilities, "
                "local_intent, intent_signals, aio_present, aio_sources, targeted_count, "
                "keyword_topic, generalist_count, client_topical_focus, client_rank, client_url")
        .eq("keyword_id", keyword_id)
        .in_("status", ["complete", "partial"])
        .order("captured_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    return rows[0] if rows else None


def _open_alert(supabase, keyword_id: str) -> Optional[dict]:
    rows = (
        supabase.table("rank_alerts")
        .select("id, alert_type, from_position, to_position, delta, message, triggered_on")
        .eq("keyword_id", keyword_id)
        .in_("status", ["unread", "read"])
        .order("triggered_on", desc=True)
        .limit(1)
        .execute()
    ).data or []
    return rows[0] if rows else None


def build_keyword_analysis(
    client_id: str, keyword_id: str, today: Optional[date] = None,
) -> Optional[dict]:
    """Assemble the full deterministic per-keyword analysis blob (no LLM).

    Returns None if the keyword doesn't belong to the client. When no SERP
    snapshot exists yet, `has_snapshot` is False and the competitive-landscape
    sections are empty — the caller (report job / router) decides whether to
    prompt for a capture first.
    """
    from config import settings
    from services import forecasting, rank_status, rankability, serp_trends
    from services.dataforseo_rank import location_code_for
    from services.keyword_market import estimate_monthly_value, fetch_cached_market

    supabase = get_supabase()
    today = today or date.today()

    kw = (
        supabase.table("tracked_keywords")
        .select("id, keyword, client_id, status, canonical_url, index_status")
        .eq("id", keyword_id).eq("client_id", client_id).limit(1).execute()
    ).data
    if not kw:
        return None
    keyword = kw[0]["keyword"]
    status = kw[0].get("status")

    client = (
        supabase.table("clients")
        .select("id, name, website_url, gbp, rank_tracking_location_code")
        .eq("id", client_id).limit(1).execute()
    ).data or [{}]
    client = client[0]

    # --- Trajectory (materialized date axis → summary + forecast) -----------
    cutoff = date.fromordinal(today.toordinal() - 90).isoformat()
    metric_rows = (
        supabase.table("rank_keyword_metrics")
        .select("keyword_id, date, gsc_position, tracked_rank, clicks, impressions")
        .eq("keyword_id", keyword_id).gte("date", cutoff).execute()
    ).data or []
    summary = rank_status.compute_keyword_summary(
        metric_rows, today, settings.rank_gsc_coverage_days
    )
    source = summary.get("primary_source")
    field = "gsc_position" if source == "gsc" else "tracked_rank"
    points = [
        (date.fromisoformat(str(r["date"])[:10]).toordinal(), r.get(field))
        for r in metric_rows if r.get("date") and r.get(field) is not None
    ]
    current = summary.get("avg_7") if source == "gsc" else summary.get("today_rank")

    # --- Market + value -----------------------------------------------------
    location_code = location_code_for(client)
    try:
        market = fetch_cached_market(supabase, [keyword], location_code)
    except Exception:
        market = {}
    m = market.get(keyword.lower(), {})
    volume, cpc = m.get("search_volume"), m.get("cpc")
    est_value = estimate_monthly_value(volume, 3.0, cpc)

    forecast = forecasting.forecast_keyword(
        keyword=keyword,
        points=points,
        current_position=float(current) if current is not None else None,
        actual_clicks_30d=summary.get("clicks_30d") if source == "gsc" else None,
        volume=volume,
        cpc=cpc,
        clicks_source="gsc" if source == "gsc" else "ctr_model",
    )

    # --- Competitive landscape (latest snapshot) ----------------------------
    snap = _latest_snapshot(supabase, keyword_id)
    landscape: dict = {"has_snapshot": bool(snap)}
    competitors: list[dict] = []
    gap: dict = {}
    winnability = {"score": None, "band": None, "factors": []}
    client_page_count = 0

    if snap:
        results = (
            supabase.table("serp_snapshot_results")
            .select("position, url, domain, title, is_client, targeted, topical_focus, "
                    "url_rating, referring_domains")
            .eq("snapshot_id", snap["id"]).execute()
        ).data or []
        domains = (
            supabase.table("serp_snapshot_domains")
            .select("domain, is_client, domain_rating, referring_domains")
            .eq("snapshot_id", snap["id"]).execute()
        ).data or []
        dr_by_domain = {d["domain"]: d.get("domain_rating") for d in domains}

        top = [r for r in results if _num(r.get("position")) and r["position"] <= 10]
        client_rows = [r for r in results if r.get("is_client")]
        client_page_count = len({r.get("url") for r in client_rows if r.get("url")})
        client_best = max(client_rows, key=lambda r: (r.get("url_rating") or -1), default=None)
        client_dr_row = next((d for d in domains if d.get("is_client")), None)
        client_authority = {
            "rd": (client_best or {}).get("referring_domains"),
            "ur": (client_best or {}).get("url_rating"),
            "dr": (client_dr_row or {}).get("domain_rating"),
            "targeted": bool((client_best or {}).get("targeted")),
            "topical_focus": snap.get("client_topical_focus"),
        }
        client_rank = snap.get("client_rank")

        competitors = build_competitor_breakdown(client_rank, top, dr_by_domain, client_authority)
        gap = authority_gap(client_authority, competitors)

        comp_only = [r for r in top if not r.get("is_client")]
        scored = rankability.score_keyword({
            "top_ur": [r.get("url_rating") for r in comp_only],
            "top_rd": [r.get("referring_domains") for r in comp_only],
            "competitor_dr": [d.get("domain_rating") for d in domains if not d.get("is_client")],
            "targeted_count": snap.get("targeted_count") or 0,
            "top_count": len(top),
            "client_ur": client_authority["ur"],
            "client_rd": client_authority["rd"],
            "client_dr": client_authority["dr"],
            "aio_present": bool(snap.get("aio_present")),
            "signals": snap.get("intent_signals") or [],
            "generalist_count": snap.get("generalist_count"),
            "client_topical_focus": snap.get("client_topical_focus"),
            "client_rank": client_rank,
        })
        winnability = {
            **scored,
            "client_topical_focus": snap.get("client_topical_focus"),
            "generalist_count": snap.get("generalist_count"),
        }
        landscape = {
            "has_snapshot": True,
            "snapshot_id": snap["id"],
            "captured_at": snap.get("captured_at"),
            "client_rank": client_rank,
            "client_url": snap.get("client_url"),
            "client_page_count": client_page_count,
            "query_intent": snap.get("query_intent"),
            "local_intent": bool(snap.get("local_intent")),
            "intent_signals": snap.get("intent_signals") or [],
            "aio_present": bool(snap.get("aio_present")),
            "aio_sources": snap.get("aio_sources") or [],
            "keyword_topic": snap.get("keyword_topic"),
            "targeted_count": snap.get("targeted_count"),
            "generalist_count": snap.get("generalist_count"),
            "client_topical_focus": snap.get("client_topical_focus"),
            "client_authority": client_authority,
            "top_results": [
                {k: r.get(k) for k in (
                    "position", "url", "domain", "title", "is_client", "targeted",
                    "topical_focus", "url_rating", "referring_domains")}
                for r in sorted(top, key=lambda x: x.get("position") or 99)
            ],
        }

    # --- What changed + drop classification ---------------------------------
    what_changed = None
    try:
        timeline = serp_trends.get_keyword_timeline(keyword_id)
        pts = (timeline or {}).get("points") or []
        if pts:
            what_changed = pts[-1]  # newest, already carries deltas vs previous
    except Exception as exc:
        logger.warning("rank_analysis.timeline_failed", extra={"keyword_id": keyword_id, "error": str(exc)})

    alert = _open_alert(supabase, keyword_id)
    drop_classification = None
    if alert:
        try:
            from services import drop_classifier

            # classify_client_drops mutates the drop dict in place (adds
            # `classification`/`classification_reason`/`response`) and returns a
            # summary — read the classified fields back off the mutated dict.
            drop = {"keyword_id": keyword_id, "keyword": keyword, **alert}
            drop_classifier.classify_client_drops(client_id, [drop])
            if drop.get("classification"):
                drop_classification = {
                    "classification": drop.get("classification"),
                    "reason": drop.get("classification_reason"),
                    "response": drop.get("response"),
                }
        except Exception as exc:
            logger.warning("rank_analysis.drop_classify_failed", extra={"keyword_id": keyword_id, "error": str(exc)})

    # --- Verdict + priority + work order ------------------------------------
    trajectory = trajectory_verdict(summary, forecast, status)
    urgency = urgency_key(status, bool(alert), trajectory.get("current_position"))
    priority = compute_priority(winnability.get("score"), est_value, urgency)
    work_order = build_work_order(
        trajectory=trajectory,
        gap=gap,
        competitors=competitors,
        winnability=winnability,
        aio_present=bool((snap or {}).get("aio_present")),
        aio_sources=(snap or {}).get("aio_sources") or [],
        client_rank=(snap or {}).get("client_rank"),
        client_page_count=client_page_count,
        drop_classification=drop_classification,
    )

    return {
        "keyword_id": keyword_id,
        "keyword": keyword,
        "client_id": client_id,
        "client_name": client.get("name"),
        "generated_for": today.isoformat(),
        "index_status": kw[0].get("index_status"),
        "canonical_url": kw[0].get("canonical_url"),
        "market": {"search_volume": volume, "cpc": cpc, "est_value": est_value},
        "trajectory": trajectory,
        "landscape": landscape,
        "competitor_breakdown": competitors,
        "authority_gap": gap,
        "winnability": winnability,
        "forecast": forecast,
        "what_changed": what_changed,
        "open_alert": alert,
        "drop_classification": drop_classification,
        "urgency": urgency,
        "priority": priority,
        "work_order": work_order,
    }
