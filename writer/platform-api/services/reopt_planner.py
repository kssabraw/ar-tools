"""Reoptimization planner — turns the rank tracker's signals into a ranked,
client-scoped list of recommended actions, each with a deep link into the tool
that does it.

Signals (all reads we already produce):
  - open rank-drop alerts (rank_alerts)         → "diagnose & reoptimize" / "confirm indexing"
  - rankability Quick wins (services.rankability)→ "reoptimize the page" / "create a page"
  - GSC-Research opportunities (gsc_research_runs):
        cannibalization → "consolidate/canonicalize"
        hidden wins     → "refresh & expand to reach page 1"

build_actions (pure) does the diagnosis→action mapping + ranking; build_plan does
the reads, stores a reopt_plans row, and (on the weekly cadence) pushes a digest
through the notifications service. Recommend-only — every action routes a human
into an existing tool; nothing is auto-executed.
"""

from __future__ import annotations

import logging

from db.supabase_client import get_supabase
from services import notifications, rankability

logger = logging.getLogger(__name__)

# Tuning (module constants).
QUICK_WIN_BANDS = {"Easy", "Moderate"}
QUICK_WIN_MIN_SCORE = 50
QUICK_WIN_MAX = 10
CANNIBAL_MAX = 5
HIDDEN_MAX = 8
STRIKING_DISTANCE_MAX = 20  # client_rank ≤ this → reoptimize existing vs create new
TOTAL_MAX = 25

# Sort is tiered: a category base keeps the four kinds in a strict priority order
# (drops → cannibalization → quick wins → hidden wins), and a bounded within-tier
# term ranks members of the same kind by their own signal strength without ever
# crossing into the next tier. (A huge-value quick win must not leapfrog an
# urgent drop, and same-kind rows must not all tie.)
_TIER = 10_000
_WITHIN_MAX = 9_999          # within-tier term is clamped to [0, _WITHIN_MAX]
_SORT_DROP = 5 * _TIER
_SORT_DEINDEX_BONUS = _TIER  # deindex sits in its own band above ordinary drops
_SORT_CANNIBAL = 3 * _TIER
_SORT_QUICK = 2 * _TIER
_SORT_HIDDEN = 1 * _TIER


def _within(value: float) -> float:
    """Clamp a within-tier ranking term so it can't bleed into another tier."""
    return max(0.0, min(float(value), _WITHIN_MAX))


def _plan_path(client_id: str) -> str:
    return f"clients/{client_id}/action-plan"


def build_actions(
    client_id: str,
    drops: list[dict],
    rankability_items: list[dict],
    gsc: dict,
) -> list[dict]:
    """Map the signals to a ranked, deduped action list. Pure (unit-tested)."""
    actions: list[dict] = []
    dropped_keywords: set[str] = set()

    # 1) Open rank-drop alerts — urgent.
    for d in drops:
        kw = d.get("keyword") or ""
        dropped_keywords.add(kw.lower())
        deindex = d.get("alert_type") == "deindexed"
        actions.append(
            {
                "kind": "rank_drop",
                "keyword": kw,
                "diagnosis": d.get("message") or "Ranking dropped.",
                "recommendation": (
                    "Confirm indexing — run URL Inspection and check robots/noindex/canonical, then resubmit."
                    if deindex
                    else "Diagnose & reoptimize — capture a SERP snapshot to see what changed (AI Overview, "
                    "a stronger competitor, an intent shift), then reoptimize the ranking page."
                ),
                "cta_label": "Open rank tracker",
                "cta_path": f"clients/{client_id}/rankings",
                "severity": "critical" if deindex else "warning",
                "sort": _SORT_DROP + (_SORT_DEINDEX_BONUS if deindex else 0),
            }
        )

    # 2) Rankability Quick wins — winnable + valuable (skip keywords already
    # surfaced as a drop; the drop action supersedes).
    winnable = [
        i for i in rankability_items
        if i.get("has_snapshot") and i.get("score") is not None
        and i.get("band") in QUICK_WIN_BANDS and i["score"] >= QUICK_WIN_MIN_SCORE
        and (i.get("keyword") or "").lower() not in dropped_keywords
    ]
    winnable.sort(key=lambda i: (i.get("priority") or 0, i["score"]), reverse=True)
    for i in winnable[:QUICK_WIN_MAX]:
        rank = i.get("client_rank")
        striking = rank is not None and rank <= STRIKING_DISTANCE_MAX
        value = i.get("est_value")
        value_str = f" · est. ${round(value):,}/mo" if value else ""
        actions.append(
            {
                "kind": "quick_win",
                "keyword": i.get("keyword") or "",
                "diagnosis": f"Rankability {i['band']} ({i['score']}/100){value_str}.",
                "recommendation": (
                    f"Reoptimize the existing page — you're #{rank} and this SERP is winnable."
                    if striking
                    else "Create a purpose-built page — the SERP is winnable and you don't have a strong page yet."
                ),
                "cta_label": "Reoptimize" if striking else "Create page",
                "cta_path": f"clients/{client_id}/local-seo",
                "severity": "info",
                "sort": _SORT_QUICK + _within(i.get("priority") or i["score"]),
            }
        )

    # 3) GSC-Research cannibalization — wasted authority across split pages.
    for c in (gsc.get("cannibalization") or [])[:CANNIBAL_MAX]:
        actions.append(
            {
                "kind": "cannibalization",
                "keyword": c.get("query") or "",
                "diagnosis": f"{c.get('page_count', 0)} pages split this query "
                f"({c.get('total_impressions', 0):,} impressions).",
                "recommendation": "Consolidate — pick the canonical page, 301/canonical the rest, "
                "and concentrate internal links so Google can rank one.",
                "cta_label": "GSC Research",
                "cta_path": f"clients/{client_id}/gsc-research",
                "severity": "warning",
                "sort": _SORT_CANNIBAL + _within(c.get("total_impressions") or 0),
            }
        )

    # 4) GSC-Research hidden wins — page-2 terms with demand.
    for h in (gsc.get("hidden_wins") or [])[:HIDDEN_MAX]:
        kw = h.get("keyword") or ""
        if kw.lower() in dropped_keywords:
            continue
        pos = h.get("position")
        actions.append(
            {
                "kind": "opportunity",
                "keyword": kw,
                "diagnosis": f"Position {round(pos) if pos else '—'} with {h.get('impressions', 0):,} "
                "impressions — sitting on page 2.",
                "recommendation": "Refresh & expand the page (more depth, internal links, freshness) "
                "to push it onto page 1.",
                "cta_label": "GSC Research",
                "cta_path": f"clients/{client_id}/gsc-research",
                "severity": "info",
                "sort": _SORT_HIDDEN + _within(h.get("impressions") or 0),
            }
        )

    actions.sort(key=lambda a: a["sort"], reverse=True)
    return actions[:TOTAL_MAX]


def summarize_plan(actions: list[dict]) -> dict:
    """{summary, severity} for the plan + its notification. Pure."""
    by_kind: dict[str, int] = {}
    for a in actions:
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1
    parts = []
    if by_kind.get("rank_drop"):
        n = by_kind["rank_drop"]
        parts.append(f"{n} drop{'s' if n != 1 else ''} to fix")
    wins = by_kind.get("quick_win", 0)
    if wins:
        parts.append(f"{wins} quick win{'s' if wins != 1 else ''}")
    other = by_kind.get("cannibalization", 0) + by_kind.get("opportunity", 0)
    if other:
        parts.append(f"{other} other opportunit{'ies' if other != 1 else 'y'}")
    summary = ", ".join(parts) if parts else "No actions right now — rankings look healthy."
    severities = {a["severity"] for a in actions}
    severity = "critical" if "critical" in severities else "warning" if "warning" in severities else "info"
    return {"summary": summary, "severity": severity}


# ----------------------------------------------------------------------------
# DB assembly + persistence.
# ----------------------------------------------------------------------------
def build_plan(client_id: str, trigger: str = "manual") -> dict:
    """Gather signals, build the ranked plan, store it, and (on the weekly
    cadence) push a digest notification. Returns the stored plan summary."""
    supabase = get_supabase()

    drops = (
        supabase.table("rank_alerts")
        .select("keyword_id, keyword, alert_type, message")
        .eq("client_id", client_id)
        .is_("resolved_at", "null")
        .execute()
    ).data or []

    try:
        rankability_items = rankability.get_client_rankability(client_id).get("items", [])
    except Exception as exc:  # rankability is best-effort input
        logger.warning("reopt_plan_rankability_failed", extra={"client_id": client_id, "error": str(exc)})
        rankability_items = []

    gsc_row = (
        supabase.table("gsc_research_runs")
        .select("cannibalization, hidden_wins, created_at")
        .eq("client_id", client_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    gsc = gsc_row[0] if gsc_row else {}

    actions = build_actions(client_id, drops, rankability_items, gsc)
    digest = summarize_plan(actions)

    plan = (
        supabase.table("reopt_plans")
        .insert(
            {
                "client_id": client_id,
                "trigger": trigger,
                "summary": digest["summary"],
                "items": actions,
                "action_count": len(actions),
            }
        )
        .execute()
    ).data[0]

    # Notify only the routine weekly digest — an on-drop refresh rides the
    # rank-drop notification that already fired; a manual run means the user is
    # already looking. Don't ping for an empty plan.
    if trigger == "scheduled" and actions:
        notifications.emit(
            client_id=client_id,
            kind="reopt_plan",
            title=f"Action plan: {len(actions)} recommendation{'s' if len(actions) != 1 else ''}",
            summary=digest["summary"],
            severity=digest["severity"],
            payload={"link": _plan_path(client_id), "plan_id": plan["id"]},
        )

    logger.info(
        "reopt_plan_built",
        extra={"client_id": client_id, "trigger": trigger, "actions": len(actions)},
    )
    return {"plan_id": plan["id"], "action_count": len(actions), "summary": digest["summary"]}


def enqueue_reopt_plan(client_id: str, trigger: str = "manual") -> None:
    """Enqueue a reopt_plan job (deduped against any in-flight one for the client)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "reopt_plan")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "reopt_plan", "entity_id": client_id, "payload": {"client_id": client_id, "trigger": trigger}}
    ).execute()


async def run_reopt_plan_job(job: dict) -> None:
    """async_jobs handler for job_type='reopt_plan'."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    trigger = payload.get("trigger", "scheduled")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        result = build_plan(client_id, trigger=trigger)
    except Exception as exc:
        # The worker loop only logs unhandled errors; a handler must mark its own
        # job failed (else it sits 'running' until the stale reaper sweeps it).
        logger.warning("reopt_plan_job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
