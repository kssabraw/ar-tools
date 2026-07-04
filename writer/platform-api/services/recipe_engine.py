"""Link Building & Campaign Recipe Engine — retainer + diagnosis → a costed,
assigned monthly task plan (docs/sops/Link_Building_Recipe_Engine.md §1–§5).

The decision engine that operates on the SOP library:

  1. Deployable = Retainer × margin  (66% margin target → ×0.34; a stagnating /
     dropping client *may* run at 50% margin → ×0.50; anything past that is a
     hard stop — escalate).
  2. − $150 reporting (every client, every month)
  3. − special-project labor (if any this month)
  4. − the Baseline Stack (every client, every month; SABs skip the GBP Blast)
  5. Remaining → Diagnose-and-Fund: spend on the deficient variables in the
     client-type funding order (local → RD first; enterprise → Entity first),
     cheapest-effective tools first, then sink the remainder into on-vector
     content pages (capped by production capacity).

`allocate` is **pure** (no I/O) and conformance-tested against the SOP §4
worked example. `build_diagnosis` derives the deficient variables from suite
data (GBP review count, open rank/maps alerts, backlink profiles); the router
runs diagnosis → allocate → persist synchronously (pure math, no job needed).

Assignees come from the roles matrix (_ORCHESTRATOR.md §6). Unstaffed tasks are
flagged, never guessed. A frozen client gets an empty plan + a `frozen` flag —
content creation and link building both stop under a freeze.

RD note: the SOP compares the client's *known-true* RD (build records) to
competitor tool-reads ×10. The app has no build records, so `build_diagnosis`
compares tool-read to tool-read (client DataForSEO RD vs page-1 avg × 1.5) —
an approximation flagged in the plan's diagnosis block.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# ── SOP constants (§1–§3 + the Link Building master table) ──────────────────
REPORTING_COST = 150.0
DEFAULT_MARGIN = 0.34           # 66% margin target
DROP_MARGIN = 0.50              # stagnating / ranking drop — needs explicit opt-in
REVIEW_THRESHOLD = 25           # Maps SOP Part 3 entry threshold
REVIEW_UNIT_COST = 15.0
CONTENT_PAGE_COST = 5.0
CONTENT_PAGE_CAP = 40           # production-capacity cap on the content remainder sink

# Baseline Stack (§2) — every client, every month. (Agency Assassin is flexible,
# not mandatory — recommended separately for ≥$1,200 retainers.)
BASELINE_STACK = [
    {"task_type": "map_embeds", "label": "Map Embeds (1 run)", "quantity": 1, "unit_cost": 5.0, "assignee": "Ivy"},
    {"task_type": "citations", "label": "40 Citations", "quantity": 1, "unit_cost": 40.0, "assignee": "Minda"},
    {"task_type": "das_v2", "label": "4× DAS v2", "quantity": 4, "unit_cost": 10.0, "assignee": "Minda → Ivy"},
    {"task_type": "blog_post", "label": "1 Blog Post", "quantity": 1, "unit_cost": 5.0, "assignee": "Minda / Ivy"},
    {"task_type": "gbp_blast", "label": "GBP Blast (physical/hybrid only)", "quantity": 1, "unit_cost": 5.0,
     "assignee": "Minda → Ivy", "sab_excluded": True},
    {"task_type": "gbp_posting", "label": "GBP posting 5×/wk (~20 posts)", "quantity": 20, "unit_cost": 2.0,
     "assignee": "Minda"},
]

AGENCY_ASSASSIN_COST = 85.0
AGENCY_ASSASSIN_MIN_RETAINER = 1200.0

# Diagnose-and-Fund tool menu (§3), cheapest-effective first per variable.
# v1 funds one unit per tool in order while budget lasts — the worked example's
# shape (baseline DAS already covers the bulk; these top up the deficiency).
FUNDING_MENU: dict[str, list[dict]] = {
    # DAS v2 is already in the baseline; these top up the RD deficiency (the §4
    # worked example's shape). RD100 stays off the default menu — it's an
    # overclock-adjacent tool reserved for large gaps at the operator's call.
    "referring_domains": [
        {"task_type": "respect_mah_authoritay_v2", "label": "Respect Mah Authoritay v2", "unit_cost": 10.0,
         "assignee": "Minda → Ivy"},
        {"task_type": "cloud_stack", "label": "Cloud Stack (Elias)", "unit_cost": 10.0, "assignee": "Minda → Ivy"},
    ],
    "link_juice": [
        {"task_type": "cloud_stack", "label": "Cloud Stack (Elias)", "unit_cost": 10.0, "assignee": "Minda → Ivy"},
        {"task_type": "google_stack", "label": "Google Stack", "unit_cost": 30.0, "assignee": "Minda → Ivy"},
        {"task_type": "niche_edit", "label": "Niche edit", "unit_cost": 75.0, "assignee": "Kyle"},
    ],
    "relevance": [
        {"task_type": "cloud_stack", "label": "Cloud Stack (Elias)", "unit_cost": 10.0, "assignee": "Minda → Ivy"},
        {"task_type": "niche_edit", "label": "Niche edit", "unit_cost": 75.0, "assignee": "Kyle"},
    ],
    "entity": [
        {"task_type": "social_post", "label": "Reddit / LinkedIn / Medium post", "unit_cost": 10.0,
         "assignee": "Minda / Ivy"},
        {"task_type": "google_stack", "label": "Google Stack", "unit_cost": 30.0, "assignee": "Minda → Ivy"},
    ],
}

# §3 funding order by client type.
FUNDING_ORDER = {
    "local": ["referring_domains", "link_juice", "relevance", "entity"],
    "enterprise": ["entity", "link_juice", "referring_domains", "relevance"],
}

GBP_SNIPER_COST = 10.0


# ─────────────────────────────────────────────────────────────────────────────
# Pure allocation engine (§1–§5) — conformance-tested against the worked example
# ─────────────────────────────────────────────────────────────────────────────
def allocate(
    retainer: float,
    diagnosis: dict,
    *,
    margin: float = DEFAULT_MARGIN,
    special_projects_cost: float = 0.0,
    is_sab: bool = False,
    client_type: str = "local",
    content_page_cap: int = CONTENT_PAGE_CAP,
) -> dict:
    """Run the §1 allocation formula and §3 Diagnose-and-Fund. Pure.

    `diagnosis` keys (all optional):
      deficient: list[str] of FUNDING_MENU variables
      review_gap: int (reviews needed to reach the 25 threshold / pack floor)
      maps_drop: bool (open maps alert → GBP Sniper run)
      organic_drop: bool
      frozen: bool
    """
    flags: list[str] = []
    tasks: list[dict] = []
    rank = 0

    def _add(task_type: str, label: str, quantity: float, unit_cost: float,
             assignee: Optional[str], rationale: str) -> float:
        nonlocal rank
        rank += 1
        line = round(quantity * unit_cost, 2)
        tasks.append(
            {
                "task_type": task_type,
                "label": label,
                "quantity": quantity,
                "unit_cost": unit_cost,
                "line_cost": line,
                "assignee": assignee,
                "priority_rank": rank,
                "rationale": rationale,
            }
        )
        if not assignee:
            flags.append("unstaffed_task")
        return line

    if margin > DROP_MARGIN + 1e-9:
        # Spending past the 50% margin floor is a hard stop (§1).
        flags.append("escalate_margin_below_50")
        margin = DROP_MARGIN

    if diagnosis.get("frozen"):
        # Freeze Protocol: link building and content creation both stop.
        return {
            "margin_used": margin,
            "deployable": 0.0,
            "spent": 0.0,
            "remaining": 0.0,
            "tasks": [],
            "flags": ["frozen"],
            "diagnosis": diagnosis,
        }

    deployable = round((retainer or 0.0) * margin, 2)
    budget = deployable

    # §1 steps 2–3: reporting + special projects come off the top (not tasks —
    # they're fixed costs, but reporting is surfaced as a line for visibility).
    budget -= REPORTING_COST
    budget -= special_projects_cost
    _add("reporting", "Monthly reporting", 1, REPORTING_COST, "—",
         "Every client, every month (§1)")
    if special_projects_cost > 0:
        _add("special_projects", "Special-project labor", 1, special_projects_cost, "Ryan",
             "Web dev / redesign / extra meetings this month (§1)")

    # §1 step 4: Baseline Stack.
    for item in BASELINE_STACK:
        if is_sab and item.get("sab_excluded"):
            continue
        cost = _add(item["task_type"], item["label"], item["quantity"], item["unit_cost"],
                    item["assignee"], "Baseline stack (§2)")
        budget -= cost

    if budget < 0:
        flags.append("under_funded")
        return {
            "margin_used": margin,
            "deployable": deployable,
            "spent": round(deployable - budget, 2),
            "remaining": round(budget, 2),
            "tasks": tasks,
            "flags": sorted(set(flags)),
            "diagnosis": diagnosis,
        }

    # §3 Diagnose-and-Fund.
    # Reviews first when below threshold — cheap and gating (worked example §4).
    review_gap = int(diagnosis.get("review_gap") or 0)
    if review_gap > 0:
        qty = min(review_gap, int(budget // REVIEW_UNIT_COST))
        if qty > 0:
            budget -= _add("reviews", "Reviews to threshold (GBP + Trustpilot)", qty, REVIEW_UNIT_COST,
                           "Minda", f"Below the 25-review threshold by {review_gap} (Maps SOP Part 3)")
        if qty < review_gap:
            flags.append("under_funded")

    # Deficient variables in the client-type order, cheapest-effective first.
    order = FUNDING_ORDER.get(client_type, FUNDING_ORDER["local"])
    deficient = [v for v in order if v in set(diagnosis.get("deficient") or [])]
    for variable in deficient:
        for tool in FUNDING_MENU.get(variable, []):
            if budget < tool["unit_cost"]:
                continue
            budget -= _add(tool["task_type"], tool["label"], 1, tool["unit_cost"], tool["assignee"],
                           f"Fund deficient variable: {variable.replace('_', ' ')} (§3)")

    # Maps drop → GBP Sniper run (campaign start + on drops — Maps SOP Part 7).
    if diagnosis.get("maps_drop") and budget >= GBP_SNIPER_COST:
        budget -= _add("gbp_sniper", "GBP Sniper (drop → 1 run)", 1, GBP_SNIPER_COST, "Minda → Ivy",
                       "Open maps drop — Sniper re-run per Maps SOP Part 7")

    # Remainder → on-vector content pages, capped by production capacity (§4).
    pages = min(int(budget // CONTENT_PAGE_COST), content_page_cap)
    if pages > 0:
        budget -= _add("content_page", "On-vector content pages", pages, CONTENT_PAGE_COST, "Minda / Ivy",
                       "Remainder sink — entity/content build-out (§3 knowledge-graph build-out)")
        if pages == content_page_cap:
            flags.append("capacity_capped")

    # Agency Assassin recommendation (flexible, not mandatory — §2 note).
    if (retainer or 0) >= AGENCY_ASSASSIN_MIN_RETAINER and budget >= AGENCY_ASSASSIN_COST:
        budget -= _add("agency_assassin", "Agency Assassin (CTR)", 1, AGENCY_ASSASSIN_COST, "Kyle",
                       "Retainer ≥ $1,200 and budget allows (§2 note)")

    spent = round(deployable - budget, 2)
    return {
        "margin_used": margin,
        "deployable": deployable,
        "spent": spent,
        "remaining": round(budget, 2),
        "tasks": tasks,
        "flags": sorted(set(flags)),
        "diagnosis": diagnosis,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Auto-diagnosis from suite data
# ─────────────────────────────────────────────────────────────────────────────
def build_diagnosis(client_id: str) -> dict:
    """Derive the Diagnose-and-Fund inputs from what the suite already knows.

    Best-effort per signal — a missing table/scan contributes nothing rather
    than failing the plan. Every conclusion carries its evidence in `signals`.
    """
    from services.freeze import is_frozen

    supabase = get_supabase()
    diagnosis: dict = {"deficient": [], "signals": {}}

    diagnosis["frozen"] = is_frozen(client_id)

    # Reviews vs the 25 threshold (Maps SOP Part 3).
    try:
        client = (
            supabase.table("clients")
            .select("gbp_review_count, retainer_monthly, is_sab, client_type")
            .eq("id", client_id)
            .single()
            .execute()
        ).data or {}
        reviews = client.get("gbp_review_count")
        if reviews is not None and reviews < REVIEW_THRESHOLD:
            diagnosis["review_gap"] = REVIEW_THRESHOLD - int(reviews)
            diagnosis["signals"]["reviews"] = f"GBP review count {reviews} < {REVIEW_THRESHOLD}"
    except Exception as exc:
        logger.warning("recipe.diagnosis_reviews_failed", extra={"client_id": client_id, "error": str(exc)})

    # Open drops (episode = resolved_at is null).
    try:
        organic_open = (
            supabase.table("rank_alerts").select("id", count="exact")
            .eq("client_id", client_id).is_("resolved_at", "null").execute()
        ).count or 0
        maps_open = (
            supabase.table("maps_alerts").select("id", count="exact")
            .eq("client_id", client_id).is_("resolved_at", "null").execute()
        ).count or 0
        diagnosis["organic_drop"] = organic_open > 0
        diagnosis["maps_drop"] = maps_open > 0
        diagnosis["signals"]["open_alerts"] = {"organic": organic_open, "maps": maps_open}
    except Exception as exc:
        logger.warning("recipe.diagnosis_alerts_failed", extra={"client_id": client_id, "error": str(exc)})

    # RD vs competition from the latest backlink profiles (tool-to-tool
    # approximation — see module docstring).
    try:
        rows = (
            supabase.table("backlink_profiles")
            .select("is_client, referring_domains, captured_at")
            .eq("client_id", client_id)
            .order("captured_at", desc=True)
            .limit(30)
            .execute()
        ).data or []
        client_rd = next((r["referring_domains"] for r in rows if r["is_client"]
                          and r.get("referring_domains") is not None), None)
        comp_rds = [r["referring_domains"] for r in rows if not r["is_client"]
                    and r.get("referring_domains") is not None][:10]
        if client_rd is not None and comp_rds:
            comp_avg = sum(comp_rds) / len(comp_rds)
            target = comp_avg * 1.5  # RD target rule (Link Building SOP)
            if client_rd < target:
                diagnosis["deficient"].append("referring_domains")
                diagnosis["signals"]["rd"] = {
                    "client_rd": client_rd,
                    "competitor_avg_rd": round(comp_avg, 1),
                    "target": round(target, 1),
                    "note": "tool-to-tool comparison (no build records for a true-count read)",
                }
    except Exception as exc:
        logger.warning("recipe.diagnosis_rd_failed", extra={"client_id": client_id, "error": str(exc)})

    # Offpage agent: an open aggregate RD-loss alert marks referring_domains
    # deficient outright (SOP §A.5 — lost links get a replacement plan).
    try:
        from services.offpage_agent import open_offpage_alerts

        for a in open_offpage_alerts(client_id):
            if a.get("alert_type") == "rd_loss" and "referring_domains" not in diagnosis["deficient"]:
                diagnosis["deficient"].append("referring_domains")
                diagnosis["signals"]["rd_loss"] = a.get("message")
    except Exception as exc:
        logger.warning("recipe.diagnosis_offpage_failed", extra={"client_id": client_id, "error": str(exc)})

    # A drop with no identified RD gap → fund link juice (strength) next.
    if (diagnosis.get("organic_drop") or diagnosis.get("maps_drop")) and \
            "referring_domains" not in diagnosis["deficient"]:
        diagnosis["deficient"].append("link_juice")
        diagnosis["signals"]["link_juice"] = "open drop with RD on target — fund strength (§3 order)"

    return diagnosis


# ─────────────────────────────────────────────────────────────────────────────
# Persistence + entry point
# ─────────────────────────────────────────────────────────────────────────────
def build_plan(
    client_id: str,
    *,
    month: Optional[date] = None,
    margin: Optional[float] = None,
    special_projects_cost: float = 0.0,
    created_by: Optional[str] = None,
) -> dict:
    """Diagnose → allocate → persist. Returns the stored plan row."""
    supabase = get_supabase()
    client = (
        supabase.table("clients")
        .select("id, name, retainer_monthly, is_sab, client_type")
        .eq("id", client_id)
        .single()
        .execute()
    ).data
    if not client:
        raise ValueError("client_not_found")

    diagnosis = build_diagnosis(client_id)
    # Stagnating-or-drop may run at 50% margin — only on explicit request (§1
    # says "may"); the default stays the 66% target and the plan records the
    # suggestion so the operator can rerun at 0.50.
    used_margin = margin if margin is not None else DEFAULT_MARGIN
    plan = allocate(
        float(client.get("retainer_monthly") or 0),
        diagnosis,
        margin=used_margin,
        special_projects_cost=special_projects_cost,
        is_sab=bool(client.get("is_sab")),
        client_type=client.get("client_type") or "local",
    )
    if not client.get("retainer_monthly"):
        plan["flags"] = sorted(set(plan["flags"] + ["no_retainer_configured"]))
    if (diagnosis.get("organic_drop") or diagnosis.get("maps_drop")) and used_margin == DEFAULT_MARGIN:
        plan["margin_suggestion"] = DROP_MARGIN

    plan_month = (month or date.today()).replace(day=1)
    row = (
        supabase.table("monthly_task_plans")
        .insert(
            {
                "client_id": client_id,
                "month": plan_month.isoformat(),
                "margin_used": plan["margin_used"],
                "deployable": plan["deployable"],
                "spent": plan["spent"],
                "remaining": plan["remaining"],
                "flags": plan["flags"],
                "plan": plan,
                "created_by": created_by,
            }
        )
        .execute()
    ).data[0]
    logger.info(
        "recipe.plan_built",
        extra={"client_id": client_id, "month": plan_month.isoformat(),
               "deployable": plan["deployable"], "spent": plan["spent"], "flags": plan["flags"]},
    )
    return row
