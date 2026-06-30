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
from services import brand_alerts, reopt_planner

logger = logging.getLogger("strategy_engine")

LLM_GAP_MAX = 10

_MODULE_LABELS = {"organic": "organic", "maps": "Maps", "ai_visibility": "LLM", "cross": "cross-channel"}
_SEVERITY_WEIGHT = {"high": 8, "medium": 4, "low": 1}

# reopt_planner emits one action dict per signal, tagged source ∈ {organic, maps}
# with a rich `kind`. The Strategy Engine consumes that single source of truth
# (so the Action Plan and the cross-module plan never drift) and maps each into a
# unified strategy_actions row. Per-kind: the suite module, the strategy category,
# a concise title template, and the role that does the craft.
_REOPT_MODULE = {"organic": "organic", "maps": "maps"}
_REOPT_CATEGORY = {
    "rank_drop": "onpage", "quick_win": "page", "cannibalization": "internal_link",
    "opportunity": "onpage", "backlink_gap": "backlink", "brand_search_decline": "reviews",
    "maps_decline": "gbp", "maps_competitor": "gbp", "maps_weak_area": "page",
    "maps_solv_drop": "gbp", "gbp_gap": "gbp", "review_gap": "reviews",
    "local_relevance": "gbp", "content_gap": "page",
}
_REOPT_ROLE = {
    "rank_drop": "writer", "quick_win": "writer", "opportunity": "writer",
    "content_gap": "writer", "maps_weak_area": "writer", "cannibalization": "seo_tech",
    "local_relevance": "seo_tech", "backlink_gap": "link_builder", "review_gap": "va",
    "gbp_gap": "account_manager", "maps_decline": "account_manager",
    "maps_competitor": "account_manager", "maps_solv_drop": "account_manager",
    "brand_search_decline": "account_manager",
}
# Concise title per kind (keyword interpolated). Falls back to the cta_label.
_REOPT_TITLE = {
    "rank_drop": "Fix ranking drop: {kw}", "quick_win": "Quick win: {kw}",
    "cannibalization": "Resolve cannibalization: {kw}", "opportunity": "Push to page 1: {kw}",
    "backlink_gap": "Close backlink authority gap", "brand_search_decline": "Invest in brand-building",
    "maps_decline": "Strengthen local pack: {kw}", "maps_competitor": "Counter local-pack competitor: {kw}",
    "maps_weak_area": "Build local coverage: {kw}", "maps_solv_drop": "Win back local market share",
    "gbp_gap": "Strengthen Google Business Profile", "review_gap": "Grow & manage reviews",
    "local_relevance": "Improve local relevance: {kw}", "content_gap": "Expand page content: {kw}",
}


# ── pure mappers (unit-tested) ───────────────────────────────────────────────
def reopt_to_action(a: dict) -> dict:
    """Map a reopt_planner action dict → a unified strategy_actions row (no plan_id).

    Preserves reopt's careful cross-tier `sort` as the unified `priority`, so the
    organic + Maps ordering main computed survives into the engagement plan. Pure.
    """
    kind = a.get("kind") or "page"
    kw = a.get("keyword") or ""
    title = _REOPT_TITLE.get(kind, "{cta}: {kw}").format(kw=kw, cta=a.get("cta_label") or kind)
    diagnosis = a.get("diagnosis") or ""
    recommendation = a.get("recommendation") or ""
    rationale = f"{diagnosis} — {recommendation}".strip(" —") if (diagnosis or recommendation) else None
    return {
        "module": _REOPT_MODULE.get(a.get("source"), "organic"),
        "category": _REOPT_CATEGORY.get(kind, "page"),
        "kind": kind,
        "title": title,
        "rationale": rationale,
        "target": {"keyword": kw, "severity": a.get("severity", "info")},
        "priority": int(a.get("sort") or 0),
        "execution_mode": "assigned",
        "assignee_role": _REOPT_ROLE.get(kind, "writer"),
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
def _reopt_actions(client_id: str) -> list[dict]:
    """Organic + Maps actions, delegated to reopt_planner.gather_actions (the
    single source of truth — it reads rank_alerts, maps_alerts, and every intel
    signal), mapped into unified strategy_actions rows."""
    return [reopt_to_action(a) for a in reopt_planner.gather_actions(client_id)]


def build_llm_actions(
    client_id: str, curr: dict, prev: "dict | None", kw_name: dict
) -> list[dict]:
    """Turn an `index_batch` of the latest brand scan (curr) + the previous one
    (prev, optional) into LLM strategy actions, reusing brand_alerts' diff logic
    so the plan reflects the SAME regressions main alerts on. Pure (unit-tested):

      - llm_misinfo (critical) — an AI engine newly stated wrong business info.
      - llm_regression (warning) — a keyword lost AI visibility on ≥1 engine since
        the last scan (but isn't fully invisible — that's superseded below).
      - llm_content_gap (warning) — a standing gap: invisible across every engine.
    """
    base = {
        "module": "ai_visibility", "category": "llm_tactic", "execution_mode": "assigned",
        "assignee_role": "writer", "source": "initial_plan", "status": "proposed",
        "deep_link": f"clients/{client_id}/ai-visibility",
    }
    # Per-keyword found/total over this batch's cells.
    per_kw: dict[str, list[int]] = {}
    for (kid, _engine), found in curr.get("cells", {}).items():
        agg = per_kw.setdefault(kid, [0, 0])
        agg[1] += 1
        agg[0] += 1 if found else 0
    invisible = {kid for kid, (f, t) in per_kw.items() if t > 0 and f == 0}

    changes = brand_alerts.detect_changes(prev, curr) if prev else None
    actions: list[dict] = []

    # 1) Misinformation — most serious; dedup by (keyword, field).
    if changes:
        seen: set = set()
        for m in changes["new_misinfo"]:
            key = (m["keyword_id"], m.get("field"))
            if key in seen:
                continue
            seen.add(key)
            kw = kw_name.get(m["keyword_id"], "a tracked query")
            actions.append({
                **base, "kind": "llm_misinfo",
                "title": f"Correct AI misinformation about your business ({kw})",
                "rationale": f"An AI engine stated an incorrect {m.get('field')} "
                             f"(said “{m.get('stated')}”, should be “{m.get('actual')}”).",
                "target": {"keyword": kw, "keyword_id": m["keyword_id"],
                           "engine": m.get("engine"), "field": m.get("field"), "severity": "critical"},
                "priority": 140,
            })

    # 2) Regressions — lost visibility on some engine, but not fully invisible
    # (the invisible-everywhere action below supersedes those keywords).
    if changes:
        regressed: dict[str, int] = {}
        for (kid, _engine) in changes["lost_cells"]:
            if kid in invisible:
                continue
            regressed[kid] = regressed.get(kid, 0) + 1
        for kid, n in regressed.items():
            kw = kw_name.get(kid, "a tracked query")
            actions.append({
                **base, "kind": "llm_regression",
                "title": f"Recover lost AI visibility for '{kw}'",
                "rationale": f"Lost AI-assistant visibility on {n} engine{'s' if n != 1 else ''} "
                             "since the last scan.",
                "target": {"keyword": kw, "keyword_id": kid, "severity": "warning"},
                "priority": 120 + n,
            })

    # 3) Standing invisible-everywhere gaps.
    for kid in invisible:
        kw = kw_name.get(kid, "a tracked query")
        engines = per_kw[kid][1]
        actions.append({
            **base, "kind": "llm_content_gap",
            "title": f"Earn AI-assistant visibility for '{kw}'",
            "rationale": f"Invisible across all {engines} engines in the latest scan.",
            "target": {"keyword": kw, "keyword_id": kid, "severity": "warning"},
            "priority": 100 + engines,
        })

    actions.sort(key=lambda a: a["priority"], reverse=True)
    return actions[:LLM_GAP_MAX]


def _llm_actions(client_id: str) -> list[dict]:
    """AI-Visibility actions, reusing brand_alerts' batch indexing + regression
    diff (the same logic the brand-alert notifications fire on) so the plan stays
    consistent with main's alerting rather than re-deriving its own signals."""
    supabase = get_supabase()
    latest = (
        supabase.table("brand_mention_history").select("scan_batch_id, created_at")
        .eq("client_id", client_id).eq("status", "completed").eq("is_competitor_scan", False)
        .order("created_at", desc=True).limit(1).execute()
    ).data
    if not latest:
        return []
    batch_id = latest[0]["scan_batch_id"]
    curr = brand_alerts.index_batch(brand_alerts._batch_rows(supabase, client_id, batch_id))
    prev_id = brand_alerts._previous_batch_id(supabase, client_id, batch_id)
    prev = (
        brand_alerts.index_batch(brand_alerts._batch_rows(supabase, client_id, prev_id))
        if prev_id else None
    )
    kw_name = {
        k["id"]: k["keyword"]
        for k in (
            supabase.table("brand_tracked_keywords").select("id, keyword")
            .eq("client_id", client_id).execute()
        ).data or []
    }
    return build_llm_actions(client_id, curr, prev, kw_name)


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
    """A single `backlink` prospect-list action from a backlink_gap audit.

    Distinct from reopt_planner's authority-gap action (kind `backlink_gap`, "you're
    N DR behind"): this is the per-domain *prospect list* (the specific domains to
    pursue) — the follow-up backlink_intel explicitly defers. Kept on its own kind
    (`backlink_prospects`) so both can coexist in the plan as complementary signals.
    """
    gaps = result.get("gaps") or []
    if not gaps:
        return []
    top = gaps[:10]
    return [{
        "module": "organic", "category": "backlink", "kind": "backlink_prospects",
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
    for reader in (_reopt_actions, _llm_actions):
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
