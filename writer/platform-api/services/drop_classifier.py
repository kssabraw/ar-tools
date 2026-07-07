"""Rank-drop signal classifier — the "rank tracking agent" classification layer
from the Organic Rank Drop SOP (docs/sops/Rank_Drop_Mitigation_SOP_Organic.md).

The SOP's premise: the agent fires a *classified* signal, not a raw drop —
  * Scope: sitewide vs page/keyword-specific
  * GSC triage: position drop vs impressions drop vs CTR drop
  * Flags: cannibalization (B1), SERP-shape / intent shift (B2)
— and each classification has its own response protocol (§B1–§B5; §A sitewide).

This module classifies every open rank-drop alert from data the suite already
stores (rank_keyword_metrics daily series, serp_snapshots AIO/intent, the latest
GSC-Research cannibalization set) and attaches the SOP's response, which the
reoptimization planner renders instead of its generic "diagnose & reoptimize"
text. Recommend-only, same as the planner: classification changes the *advice*,
not what executes.

Pure helpers (`summarize_window`, `triage_gsc`, `detect_serp_shift`,
`detect_scope`, `classify_drop`) are unit-tested without a DB;
`classify_client_drops` does the reads (best-effort per signal — a missing
snapshot or empty metric series degrades to the B5 standard diagnostic, never
fails the plan).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# ── Tuning (module constants) ────────────────────────────────────────────────
SITEWIDE_MIN_ALERTS = 5        # this many open drops → sitewide regardless of share
SITEWIDE_MIN_SHARE = 0.30      # …or ≥30% of tracked keywords dropping
WINDOW_DAYS = 14               # recent window vs the prior window of equal length
STABLE_POSITION_DELTA = 3.0    # |Δposition| under this = "position stable"
POSITION_DROP_MIN = 3.0        # positions worsened by ≥ this = position drop
IMPRESSIONS_DROP_PCT = 50.0    # relative impressions fall ≥ this = impressions drop
CTR_DROP_PCT = 30.0            # relative CTR fall ≥ this (position stable) = CTR drop
MIN_PRIOR_IMPRESSIONS = 20     # below this the windows are noise — don't triage


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested)
# ─────────────────────────────────────────────────────────────────────────────
def detect_scope(open_drop_count: int, tracked_count: int) -> str:
    """Sitewide (§A) vs page/keyword-specific (§B). Pure."""
    if open_drop_count >= SITEWIDE_MIN_ALERTS:
        return "sitewide"
    if tracked_count > 0 and open_drop_count / tracked_count >= SITEWIDE_MIN_SHARE:
        return "sitewide"
    return "specific"


def summarize_window(rows: list[dict]) -> Optional[dict]:
    """Aggregate rank_keyword_metrics rows into one window read:
    {impressions, clicks, ctr, position}. Position is the impressions-weighted
    mean of gsc_position (falls back to tracked_rank), None when no reads.
    Pure."""
    if not rows:
        return None
    impressions = sum(r.get("impressions") or 0 for r in rows)
    clicks = sum(r.get("clicks") or 0 for r in rows)
    pos_num = pos_den = 0.0
    for r in rows:
        pos = r.get("gsc_position")
        if pos is None:
            pos = r.get("tracked_rank")
        if pos is None:
            continue
        w = max(r.get("impressions") or 0, 1)
        pos_num += float(pos) * w
        pos_den += w
    return {
        "impressions": impressions,
        "clicks": clicks,
        "ctr": (clicks / impressions) if impressions else 0.0,
        "position": (pos_num / pos_den) if pos_den else None,
    }


def triage_gsc(recent: Optional[dict], prior: Optional[dict]) -> Optional[str]:
    """The SOP's GSC triage: 'position_drop' | 'impressions_drop' | 'ctr_drop' |
    None (insufficient data → the caller falls back to B5's standard
    diagnostic). Pure.

    Order matters: a real position drop explains the other two, so it wins;
    an impressions collapse with stable/absent position is an indexing/
    visibility problem (B4); a CTR collapse with both stable is a snippet
    problem (B3)."""
    if not recent or not prior:
        return None
    if (prior.get("impressions") or 0) < MIN_PRIOR_IMPRESSIONS:
        return None

    r_pos, p_pos = recent.get("position"), prior.get("position")
    position_worsened = (
        r_pos is not None and p_pos is not None and (r_pos - p_pos) >= POSITION_DROP_MIN
    )
    position_stable = (
        r_pos is not None and p_pos is not None and abs(r_pos - p_pos) < STABLE_POSITION_DELTA
    )
    if position_worsened:
        return "position_drop"

    imp_fall_pct = 0.0
    if prior["impressions"]:
        imp_fall_pct = (prior["impressions"] - recent["impressions"]) / prior["impressions"] * 100
    if imp_fall_pct >= IMPRESSIONS_DROP_PCT and (position_stable or r_pos is None):
        return "impressions_drop"

    ctr_fall_pct = 0.0
    if prior["ctr"]:
        ctr_fall_pct = (prior["ctr"] - recent["ctr"]) / prior["ctr"] * 100
    if ctr_fall_pct >= CTR_DROP_PCT and position_stable:
        return "ctr_drop"
    return None


def detect_serp_shift(latest: Optional[dict], prior: Optional[dict]) -> dict:
    """Compare a keyword's two most recent SERP snapshots for the B2 signals:
    an AI Overview appearing, or the query intent flipping. Pure."""
    shift = {"aio_appeared": False, "intent_changed": False,
             "intent_from": None, "intent_to": None}
    if not latest or not prior:
        return shift
    if latest.get("aio_present") and not prior.get("aio_present"):
        shift["aio_appeared"] = True
    li, pi = latest.get("query_intent"), prior.get("query_intent")
    if li and pi and li != pi:
        shift["intent_changed"] = True
        shift["intent_from"], shift["intent_to"] = pi, li
    return shift


def classify_drop(
    alert: dict,
    *,
    cannibalized: Optional[set] = None,
    serp_shift: Optional[dict] = None,
    triage: Optional[str] = None,
) -> dict:
    """Classify one open drop per the SOP's §B order. Pure.

    Precedence: a deindexed alert is an indexing problem outright (B4);
    cannibalization (B1) beats SERP-shift (B2) — fix your own house first;
    then the GSC triage (B3/B4); everything else is B5's standard ladder."""
    kw = (alert.get("keyword") or "").lower()
    serp_shift = serp_shift or {}

    if alert.get("alert_type") == "deindexed":
        return {"classification": "B4", "reason": "deindexed_alert", "serp_shift": serp_shift}
    if cannibalized and kw in cannibalized:
        return {"classification": "B1", "reason": "cannibalization_flag", "serp_shift": serp_shift}
    if serp_shift.get("aio_appeared") or serp_shift.get("intent_changed"):
        return {"classification": "B2", "reason": "serp_shift_flag", "serp_shift": serp_shift}
    if triage == "ctr_drop":
        return {"classification": "B3", "reason": "gsc_triage", "serp_shift": serp_shift}
    if triage == "impressions_drop":
        return {"classification": "B4", "reason": "gsc_triage", "serp_shift": serp_shift}
    return {"classification": "B5", "reason": "standard_diagnostic", "serp_shift": serp_shift}


# The SOP's response protocols, rendered as planner guidance (§B1–§B5).
# cta_kind → resolved to a client path by the planner.
RESPONSE_PLAYBOOK: dict[str, dict] = {
    "B1": {
        "label": "Cannibalization",
        "recommendation": (
            "Two or more of the client's own pages compete for this keyword (SOP §B1): "
            "1) identify which page should own it per the silo structure; "
            "2) differentiate the competing page's title/H1/content toward its own keyword; "
            "3) true duplicates with no distinct intent → consolidate + 301 to the owning page."
        ),
        "cta_label": "GSC Research",
        "cta_kind": "gsc_research",
    },
    "B2": {
        "label": "SERP-shape / intent shift",
        "recommendation": (
            "Google changed what this SERP rewards (SOP §B2): "
            "1) re-check intent — what page *types* rank now; "
            "2) intent flipped → re-optimize the existing page to the new intent (default; a sibling "
            "page is the exception); "
            "3) an AI Overview is absorbing clicks → run the AIO defensive play (cited vs excluded — "
            "AIO SOP Part 3); "
            "4) CTR collapsed from a title rewrite → rewrite title/meta to be rewrite-resistant."
        ),
        "cta_label": "SERP snapshots",
        "cta_kind": "rankings",
    },
    "B3": {
        "label": "CTR drop, position stable",
        "recommendation": (
            "A snippet problem, not a ranking problem (SOP §B3): rewrite title/meta (front-load, match "
            "query phrasing); check the SERP for new features pushing the result down the fold; confirm "
            "rich results (schema) still render."
        ),
        "cta_label": "Open rank tracker",
        "cta_kind": "rankings",
    },
    "B4": {
        "label": "Impressions drop / indexing",
        "recommendation": (
            "An indexing/visibility problem (SOP §B4): URL-inspect the page (indexed? canonical "
            "honored?); confirm sitemap presence; check internal links (not orphaned) and that the "
            "silo is intact. Then request indexing via GSC URL Inspection."
        ),
        "cta_label": "Open rank tracker",
        "cta_kind": "rankings",
    },
    "B5": {
        "label": "Position drop",
        "recommendation": (
            "Standard diagnostic, in order — stop at the first cause found (SOP §B5): "
            "1) technical (200, not redirected, not orphaned, CWV on par); "
            "2) on-page — run the page-type on-page agent (composite ≥90 continues, <90 → rewrite); "
            "3) schema matches the page type's template; "
            "4) silo built out and interlinked; "
            "5) backlinks vs competition (×10 tool discount, within-25% gate) → deficient → fund via "
            "the Recipe Engine; "
            "6) competitor movement."
        ),
        "cta_label": "Open rank tracker",
        "cta_kind": "rankings",
    },
}

# §A sitewide response — rendered as one banner action above the per-keyword rows.
SITEWIDE_PLAYBOOK = {
    "label": "Sitewide decline",
    "recommendation": (
        "Many keywords are down together — work the §A ladder, in order (SOP): "
        "1) manual actions / security issues in GSC → Freeze Protocol; "
        "2) algo update → hold major changes until it settles (notify the senior SEO); "
        "3) sitewide technical accident (robots/noindex regressions, canonical breakage, migration "
        "side-effects, hosting/CDN, CWV regression); "
        "4) entity-vector confusion — heavy off-topic content (vector-confusion remediation); "
        "5) aggregate link loss or an unnatural RD spike → replacement plan via the Recipe Engine; "
        "6) content decay / freshness."
    ),
    "cta_label": "Open rank tracker",
    "cta_kind": "rankings",
}

CTA_PATHS = {
    "rankings": "clients/{client_id}/rankings",
    "gsc_research": "clients/{client_id}/gsc-research",
    "action_plan": "clients/{client_id}/action-plan",
}


def cta_path(kind: str, client_id: str) -> str:
    return CTA_PATHS.get(kind, CTA_PATHS["rankings"]).format(client_id=client_id)


# ─────────────────────────────────────────────────────────────────────────────
# Data gathering (best-effort per signal)
# ─────────────────────────────────────────────────────────────────────────────
def _cannibalized_queries(supabase, client_id: str) -> set:
    try:
        rows = (
            supabase.table("gsc_research_runs")
            .select("cannibalization")
            .eq("client_id", client_id)
            .eq("status", "complete")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
        cann = (rows[0].get("cannibalization") or []) if rows else []
        return {(c.get("query") or "").lower() for c in cann if c.get("query")}
    except Exception as exc:
        logger.warning("drop_classifier.cannibalization_read_failed",
                       extra={"client_id": client_id, "error": str(exc)})
        return set()


def _keyword_serp_shift(supabase, keyword_id: str) -> dict:
    try:
        snaps = (
            supabase.table("serp_snapshots")
            .select("aio_present, query_intent, captured_at")
            .eq("keyword_id", keyword_id)
            .eq("status", "complete")
            .order("captured_at", desc=True)
            .limit(2)
            .execute()
        ).data or []
        if len(snaps) < 2:
            return detect_serp_shift(None, None)
        return detect_serp_shift(snaps[0], snaps[1])
    except Exception:
        return detect_serp_shift(None, None)


def _keyword_triage(supabase, keyword_id: str) -> Optional[str]:
    try:
        since = (date.today() - timedelta(days=WINDOW_DAYS * 2)).isoformat()
        rows = (
            supabase.table("rank_keyword_metrics")
            .select("date, clicks, impressions, gsc_position, tracked_rank")
            .eq("keyword_id", keyword_id)
            .gte("date", since)
            .order("date")
            .execute()
        ).data or []
        if not rows:
            return None
        split = (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()
        prior = summarize_window([r for r in rows if r["date"] < split])
        recent = summarize_window([r for r in rows if r["date"] >= split])
        return triage_gsc(recent, prior)
    except Exception:
        return None


def classify_client_drops(client_id: str, drops: list[dict]) -> dict:
    """Classify every open drop + detect scope. Mutates each drop dict in place
    (adds `classification`, `response`) and returns
    {scope, sitewide: bool, classified: int}. Best-effort throughout — an
    unclassifiable drop keeps the planner's generic guidance."""
    supabase = get_supabase()

    tracked_count = 0
    try:
        tracked_count = (
            supabase.table("tracked_keywords")
            .select("id", count="exact")
            .eq("client_id", client_id)
            .execute()
        ).count or 0
    except Exception:
        pass

    scope = detect_scope(len(drops), tracked_count)
    cannibalized = _cannibalized_queries(supabase, client_id)

    classified = 0
    for d in drops:
        try:
            keyword_id = d.get("keyword_id")
            shift = _keyword_serp_shift(supabase, keyword_id) if keyword_id else {}
            triage = _keyword_triage(supabase, keyword_id) if keyword_id else None
            result = classify_drop(d, cannibalized=cannibalized, serp_shift=shift, triage=triage)
            playbook = RESPONSE_PLAYBOOK[result["classification"]]
            d["classification"] = result["classification"]
            d["classification_reason"] = result["reason"]
            d["response"] = {
                "label": playbook["label"],
                "recommendation": playbook["recommendation"],
                "cta_label": playbook["cta_label"],
                "cta_path": cta_path(playbook["cta_kind"], client_id),
            }
            if result["serp_shift"].get("intent_changed"):
                d["response"]["recommendation"] += (
                    f" (Intent shifted {result['serp_shift']['intent_from']} → "
                    f"{result['serp_shift']['intent_to']}.)"
                )
            classified += 1
        except Exception as exc:
            logger.warning("drop_classifier.classify_failed",
                           extra={"client_id": client_id, "keyword": d.get("keyword"),
                                  "error": str(exc)})

    return {"scope": scope, "sitewide": scope == "sitewide", "classified": classified,
            "open_drops": len(drops), "tracked_count": tracked_count}
