"""Strategy Engine v1 — the cross-module recommendation brain.

Generalizes the organic `reopt_planner` into one unified, **engagement-scoped**
plan spanning organic + Maps + AI-Visibility. Recommend-only: every action
carries a deep link + assignee; nothing is auto-executed in this phase.

Per-module signal readers are isolated (a failing or empty module never breaks
the plan), so the Maps and LLM readers can deepen as their richer signals
(winnability, alerts, goal gaps — Phase 5) come online. Today they read what's
already stored: Maps weak-area coverage gaps, and LLM keywords invisible across
every engine in the latest scan.

Phase 2 / PR-B of the managed-engagement build
(docs/managed-engagement-and-strategy-engine-design-v1_0.md §6.1, §6.9).
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from db.supabase_client import get_supabase
from services import rankability, reopt_planner

logger = logging.getLogger("strategy_engine")

MAPS_AREA_MAX = 8
LLM_GAP_MAX = 10

_MODULE_LABELS = {"organic": "organic", "maps": "Maps", "ai_visibility": "LLM", "cross": "cross-channel"}
_SEVERITY_WEIGHT = {"high": 8, "medium": 4, "low": 1}

# Organic reopt kind → unified action (category + the role that does the craft).
_ORGANIC_CATEGORY = {
    "rank_drop": "onpage", "quick_win": "page",
    "cannibalization": "internal_link", "opportunity": "onpage",
}
_ORGANIC_ROLE = {
    "rank_drop": "writer", "quick_win": "writer",
    "cannibalization": "seo_tech", "opportunity": "writer",
}


# ── pure mappers (unit-tested) ───────────────────────────────────────────────
def organic_to_action(client_id: str, a: dict) -> dict:
    """Map a reopt_planner action dict → a unified strategy_actions row (no plan_id)."""
    kind = a.get("kind") or "page"
    return {
        "module": "organic",
        "category": _ORGANIC_CATEGORY.get(kind, "page"),
        "kind": kind,
        "title": a.get("recommendation") or kind,
        "rationale": a.get("diagnosis"),
        "target": {"keyword": a.get("keyword"), "severity": a.get("severity", "info")},
        "priority": int(a.get("sort") or 0),
        "execution_mode": "assigned",
        "assignee_role": _ORGANIC_ROLE.get(kind, "writer"),
        "source": "initial_plan",
        "status": "proposed",
        "deep_link": a.get("cta_path"),
    }


def summarize(actions: list[dict]) -> dict:
    """{headline, counts, severity, action_count} for the plan. Pure."""
    counts: dict[str, int] = {}
    for a in actions:
        counts[a["module"]] = counts.get(a["module"], 0) + 1
    parts = [
        f"{counts[m]} {_MODULE_LABELS[m]}"
        for m in ("organic", "maps", "ai_visibility", "cross")
        if counts.get(m)
    ]
    headline = " · ".join(parts) if parts else "No actions right now — everything looks healthy."
    severities = {(a.get("target") or {}).get("severity", "info") for a in actions}
    severity = (
        "critical" if "critical" in severities
        else "warning" if "warning" in severities
        else "info"
    )
    return {"headline": headline, "counts": counts, "severity": severity, "action_count": len(actions)}


# ── per-module signal readers (best-effort, isolated) ────────────────────────
def _organic_actions(client_id: str) -> list[dict]:
    supabase = get_supabase()
    drops = (
        supabase.table("rank_alerts")
        .select("keyword_id, keyword, alert_type, message")
        .eq("client_id", client_id).is_("resolved_at", "null").execute()
    ).data or []
    try:
        items = rankability.get_client_rankability(client_id).get("items", [])
    except Exception as exc:  # best-effort input
        logger.warning("strategy_engine.rankability_failed", extra={"error": str(exc)})
        items = []
    gsc_row = (
        supabase.table("gsc_research_runs")
        .select("cannibalization, hidden_wins, created_at")
        .eq("client_id", client_id).eq("status", "complete")
        .order("created_at", desc=True).limit(1).execute()
    ).data
    gsc = gsc_row[0] if gsc_row else {}
    raw = reopt_planner.build_actions(client_id, drops, items, gsc)
    return [organic_to_action(client_id, a) for a in raw]


def _maps_actions(client_id: str) -> list[dict]:
    supabase = get_supabase()
    scan = (
        supabase.table("maps_scans").select("id")
        .eq("client_id", client_id).eq("status", "complete")
        .order("completed_at", desc=True).limit(1).execute()
    ).data
    if not scan:
        return []
    results = (
        supabase.table("maps_scan_results")
        .select("keyword, report_weak_locations").eq("scan_id", scan[0]["id"]).execute()
    ).data or []
    actions: list[dict] = []
    for r in results:
        keyword = r.get("keyword")
        for area in ((r.get("report_weak_locations") or {}).get("weak_areas") or [])[:3]:
            city = area.get("city") or "a nearby area"
            actions.append({
                "module": "maps",
                "category": "page",
                "kind": "maps_coverage_gap",
                "title": f"Build a local page for {city} ({keyword})",
                "rationale": (
                    f"Weak local-pack coverage near {city} — {area.get('pins')} weak pins, "
                    f"worst rank {area.get('worst_rank')}."
                ),
                "target": {"keyword": keyword, "city": city, "priority": area.get("priority")},
                "priority": int(area.get("priority") or 0),
                "execution_mode": "assigned",
                "assignee_role": "writer",
                "source": "initial_plan",
                "status": "proposed",
                "deep_link": f"clients/{client_id}/maps",
            })
    actions.sort(key=lambda a: a["priority"], reverse=True)
    return actions[:MAPS_AREA_MAX]


def _llm_actions(client_id: str) -> list[dict]:
    supabase = get_supabase()
    latest = (
        supabase.table("brand_mention_history").select("scan_batch_id, created_at")
        .eq("client_id", client_id).eq("status", "completed")
        .order("created_at", desc=True).limit(1).execute()
    ).data
    if not latest:
        return []
    rows = (
        supabase.table("brand_mention_history")
        .select("keyword_id, engine, mention_found, status")
        .eq("client_id", client_id).eq("scan_batch_id", latest[0]["scan_batch_id"]).execute()
    ).data or []
    agg: dict[str, dict] = {}
    for row in rows:
        if row.get("status") != "completed" or not row.get("keyword_id"):
            continue
        a = agg.setdefault(row["keyword_id"], {"engines": 0, "found": 0})
        a["engines"] += 1
        if row.get("mention_found"):
            a["found"] += 1
    kw_name = {
        k["id"]: k["keyword"]
        for k in (
            supabase.table("brand_tracked_keywords").select("id, keyword")
            .eq("client_id", client_id).execute()
        ).data or []
    }
    actions: list[dict] = []
    for kid, a in agg.items():
        if a["engines"] > 0 and a["found"] == 0:  # invisible across every engine this batch
            kw = kw_name.get(kid, "a tracked query")
            actions.append({
                "module": "ai_visibility",
                "category": "llm_tactic",
                "kind": "llm_content_gap",
                "title": f"Earn AI-assistant visibility for '{kw}'",
                "rationale": f"Invisible across all {a['engines']} engines in the latest scan.",
                "target": {"keyword": kw, "keyword_id": kid},
                "priority": 100 + a["engines"],  # more engines missing → slightly higher
                "execution_mode": "assigned",
                "assignee_role": "writer",
                "source": "initial_plan",
                "status": "proposed",
                "deep_link": f"clients/{client_id}/ai-visibility",
            })
    actions.sort(key=lambda a: a["priority"], reverse=True)
    return actions[:LLM_GAP_MAX]


# ── audit → action mappers (pure; from audit_runs results) ───────────────────
def site_audit_actions(result: dict) -> list[dict]:
    """Group a site_technical audit's issues by type → `technical_fix` actions (top 8)."""
    by_type: dict[str, dict] = {}
    for i in result.get("issues") or []:
        info = by_type.setdefault(
            i["type"], {"count": 0, "severity": i.get("severity", "low"), "detail": i.get("detail", i["type"]), "urls": []}
        )
        info["count"] += 1
        if len(info["urls"]) < 10:
            info["urls"].append(i.get("url"))
    actions = []
    for itype, info in by_type.items():
        n = info["count"]
        actions.append({
            "module": "cross", "category": "technical_fix", "kind": "technical_fix",
            "title": f"Fix: {info['detail']} ({n} page{'s' if n != 1 else ''})",
            "rationale": f"Site audit flagged {n} page(s) — {itype} ({info['severity']}).",
            "target": {"issue_type": itype, "count": n, "urls": info["urls"]},
            "priority": _SEVERITY_WEIGHT.get(info["severity"], 1) * n,
            "execution_mode": "assigned", "assignee_role": "seo_tech",
            "source": "initial_plan", "status": "proposed",
        })
    actions.sort(key=lambda a: a["priority"], reverse=True)
    return actions[:8]


def backlink_audit_actions(result: dict) -> list[dict]:
    """A single `backlink` prospect-list action from a backlink_gap audit."""
    gaps = result.get("gaps") or []
    if not gaps:
        return []
    top = gaps[:10]
    return [{
        "module": "organic", "category": "backlink", "kind": "backlink_gap",
        "title": f"Pursue {result.get('gap_count', len(gaps))} link prospects competitors have and you don't",
        "rationale": "Top: " + ", ".join(g["referring_domain"] for g in top[:5]),
        "target": {"prospects": top},
        "priority": int(result.get("gap_count") or len(gaps)),
        "execution_mode": "assigned", "assignee_role": "link_builder",
        "source": "initial_plan", "status": "proposed",
    }]


def citation_audit_actions(result: dict) -> list[dict]:
    """A single `citation` action listing the directories the client is missing from."""
    missing = result.get("missing") or []
    if not missing:
        return []
    return [{
        "module": "maps", "category": "citation", "kind": "citation_gap",
        "title": f"Get listed on {len(missing)} missing director{'ies' if len(missing) != 1 else 'y'}",
        "rationale": "Missing: " + ", ".join(missing[:8]),
        "target": {"missing": missing},
        "priority": len(missing) * 5,
        "execution_mode": "assigned", "assignee_role": "va",
        "source": "initial_plan", "status": "proposed",
    }]


_AUDIT_MAPPERS = {
    "site_technical": site_audit_actions,
    "backlink_gap": backlink_audit_actions,
    "local_citation": citation_audit_actions,
}


def _audit_actions(engagement_id: str) -> list[dict]:
    """Read the latest completed audit_runs for the engagement → strategy actions."""
    runs = (
        get_supabase().table("audit_runs").select("kind, result, created_at")
        .eq("engagement_id", engagement_id).eq("status", "complete")
        .order("created_at", desc=True).execute()
    ).data or []
    latest: dict[str, dict] = {}
    for r in runs:
        latest.setdefault(r["kind"], r)  # newest-first → first seen per kind is latest
    out: list[dict] = []
    for kind, mapper in _AUDIT_MAPPERS.items():
        if kind in latest:
            out.extend(mapper(latest[kind].get("result") or {}))
    return out


def build_actions(client_id: str, engagement_id: "str | None" = None) -> list[dict]:
    """Gather actions across every module; isolate each reader so one never aborts the rest."""
    out: list[dict] = []
    # Per-client readers resolved per call (via module globals) so each is patchable in tests.
    for reader in (_organic_actions, _maps_actions, _llm_actions):
        try:
            out.extend(reader(client_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "strategy_engine.reader_failed",
                extra={"reader": getattr(reader, "__name__", "reader"), "error": str(exc)},
            )
    if engagement_id:  # engagement-scoped audit findings → technical_fix / backlink / citation
        try:
            out.extend(_audit_actions(engagement_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("strategy_engine.audit_reader_failed", extra={"error": str(exc)})
    out.sort(key=lambda a: a["priority"], reverse=True)
    return out


# ── DB assembly + persistence ────────────────────────────────────────────────
def build_plan(engagement_id: str) -> dict:
    """Build a fresh recommend-only plan for an engagement, superseding the prior proposed one."""
    supabase = get_supabase()
    eng = (
        supabase.table("engagements").select("id, client_id")
        .eq("id", engagement_id).limit(1).execute()
    ).data
    if not eng:
        raise HTTPException(status_code=404, detail="engagement_not_found")
    client_id = eng[0]["client_id"]

    actions = build_actions(client_id, engagement_id)
    summary = summarize(actions)

    # Supersede any prior still-proposed plan so "latest proposed" is unambiguous.
    supabase.table("strategy_plans").update({"status": "superseded"}) \
        .eq("engagement_id", engagement_id).eq("status", "proposed").execute()

    plan = (
        supabase.table("strategy_plans")
        .insert({"engagement_id": engagement_id, "status": "proposed", "summary": summary})
        .execute()
    ).data[0]

    if actions:
        rows = [{**a, "plan_id": plan["id"]} for a in actions]
        supabase.table("strategy_actions").insert(rows).execute()

    supabase.table("engagements").update(
        {"current_plan_id": plan["id"], "updated_at": "now()"}
    ).eq("id", engagement_id).execute()

    logger.info(
        "strategy_plan_built",
        extra={"engagement_id": engagement_id, "actions": len(actions)},
    )
    return {"plan_id": plan["id"], "action_count": len(actions), "summary": summary}


def get_latest_plan(engagement_id: str) -> "dict | None":
    """The most recent plan for an engagement + its actions (priority desc)."""
    supabase = get_supabase()
    plans = (
        supabase.table("strategy_plans").select("*")
        .eq("engagement_id", engagement_id).order("created_at", desc=True)
        .limit(1).execute()
    ).data
    if not plans:
        return None
    plan = plans[0]
    plan["actions"] = (
        supabase.table("strategy_actions").select("*")
        .eq("plan_id", plan["id"]).order("priority", desc=True).execute()
    ).data or []
    return plan
