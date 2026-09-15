"""PAA → SEO Neo Phase 3 — pure helpers for the Service PAA Campaign + the
automated single-variable gate.

The v1 workflow (``docs/modules/paa-seo-neo/single-variable-scan-verify-workflow.md``)
is a MANUAL loop: create posts → settle ~1 wk → single-keyword Maps geo-grid scan
→ read the branch (moved / drill / HALT) → rinse per service. Phase 3 makes that a
state machine with a clock and an automated gate read (PRD §12). This module holds
the PURE (no-I/O) pieces — the transition function, the gate evaluator, the
drill/HALT decision, the cadence math, and the "next action" descriptor — all
independently unit-testable. The I/O (creating the set + posts, kicking scans,
reading ``maps_scan_results``, notifications, the manifest hand-off) lives in
``services/paa_campaign_service.py``.

Autonomy (owner-locked, PRD §12.2 fork 1): **hybrid propose-confirm**. The
cheap/free steps advance automatically; the two PAID/content steps — kicking a
paid geo-grid scan and creating a drill round of posts — advance to a ``*_ready``
state and a HUMAN confirms. This module encodes the transitions; the service layer
performs the confirmed actions.

PERMANENT GUARDRAIL (PRD §9): the campaign ORCHESTRATES + TRACKS the loop and hands
off the (Phase-2) manifest — the suite NEVER executes the SEO Neo authority layer.
The "moved" branch only builds/costs/QAs the manifest; there is no execute path
here. HALT is a STOP ("more PAAs won't fix it — re-check on-page/entity"), never
"keep writing." Confidence tags (``[PROVEN]``/``[THEORY]``/``[BELIEF]``) are
carried into every surfaced string — this is one local-SEO group's working model,
not Google guidance.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

__all__ = [
    "SETTLE_DAYS",
    "RINSE_DAYS",
    "DRILL_CAP",
    "MOVE_MIN_POSITIONS",
    "MOVE_MIN_TOP3_PINS",
    "STATES",
    "GATE_BRANCHES",
    "GATE_CONFIDENCE_NOTE",
    "settle_until",
    "next_rinse_at",
    "is_settle_elapsed",
    "is_rinse_due",
    "evaluate_gate",
    "state_for_branch",
    "record_transition",
    "next_action",
    "drill_seed_questions",
    "gate_summary_text",
]

# ── cadence + thresholds (borrowed from response_episodes' constants) ─────────
# The load-bearing settle wait (reference §5.2 — content moves are readable in
# ~a week; the wait makes the next scan attributable, single-variable).
SETTLE_DAYS = 7
# The rinse/maintenance cadence (reference §5.2 — "rinse every 6 weeks – 3 months"
# as Google shrinks map proximity). 6 weeks is the conservative default.
RINSE_DAYS = 42
# Drill deeper ≤ ~4 levels (reference §5.3); at the cap with no movement → HALT.
DRILL_CAP = 4
# "Moved" thresholds. Geo-grid average_rank is 1-based, lower = better — same
# direction + magnitude as response_episodes.IMPROVE_MIN_POSITIONS. top3 pins are
# a corroborating signal (more local-pack coverage).
MOVE_MIN_POSITIONS = 2.0
MOVE_MIN_TOP3_PINS = 2

STATES = (
    "draft", "content", "settling", "scan_ready", "scanning",
    "evaluating", "moved", "drill_ready", "halted", "maintenance",
)
GATE_BRANCHES = ("moved", "drill", "halt", "no_data")

# Carried into every gate/next-action string surfaced to a user (PRD §9).
GATE_CONFIDENCE_NOTE = (
    "[PROVEN model] The single-variable gate (change content only, then scan, so "
    "the cause is attributable) is the methodology's measurement discipline — one "
    "local-SEO group's working model, not Google guidance."
)


# ── cadence math ──────────────────────────────────────────────────────────────


def _as_utc(value) -> Optional[datetime]:
    """Parse a timestamptz-ish value to an aware UTC datetime. Pure."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def settle_until(now: datetime, settle_days: int = SETTLE_DAYS) -> datetime:
    """When the content for a drill level has settled enough to scan. Pure."""
    return now + timedelta(days=settle_days)


def next_rinse_at(now: datetime, rinse_days: int = RINSE_DAYS) -> datetime:
    """When the maintenance loop should re-evaluate a moved campaign. Pure."""
    return now + timedelta(days=rinse_days)


def is_settle_elapsed(campaign: dict, now: datetime) -> bool:
    """True once a settling campaign's settle window has elapsed. Pure."""
    su = _as_utc(campaign.get("settle_until"))
    return su is not None and now >= su


def is_rinse_due(campaign: dict, now: datetime) -> bool:
    """True once a maintenance campaign's next re-evaluation is due. Pure."""
    na = _as_utc(campaign.get("next_action_at"))
    return na is not None and now >= na


# ── the single-variable gate (deterministic) ──────────────────────────────────


def evaluate_gate(
    baseline_rank: Optional[float],
    current_rank: Optional[float],
    *,
    baseline_top3: Optional[int] = None,
    current_top3: Optional[int] = None,
    drill_level: int = 0,
    cap: int = DRILL_CAP,
    move_min_positions: float = MOVE_MIN_POSITIONS,
    move_min_top3_pins: int = MOVE_MIN_TOP3_PINS,
) -> dict:
    """Read a completed single-variable scan and branch (reference §5.3). Pure.

    Returns ``{branch, improved, reason, rank_delta, top3_delta}`` where ``branch``
    is one of ``GATE_BRANCHES``:
      * ``moved``   — the content moved the needle → proceed (next service).
      * ``drill``   — no movement but there's drill headroom → drill deeper.
      * ``halt``    — no movement at the drill cap → STOP + re-check on-page/entity.
      * ``no_data`` — can't judge (no baseline / no current rank) → the caller
        re-measures rather than mis-branching.

    Geo-grid ``average_rank`` is 1-based, lower = better, so improvement is
    ``baseline - current``. The top-3 pin count is a corroborating signal: a gain
    of ``move_min_top3_pins`` counts as movement even if the average is flat (more
    local-pack coverage). A campaign that dropped OFF the grid entirely
    (``current_rank`` None but a baseline existed) is treated as no movement."""
    if baseline_rank is None:
        return {"branch": "no_data", "improved": False,
                "reason": "no baseline rank captured yet", "rank_delta": None,
                "top3_delta": None}

    rank_delta: Optional[float] = None
    top3_delta: Optional[int] = None
    improved = False
    if current_rank is not None:
        rank_delta = round(float(baseline_rank) - float(current_rank), 2)
        if rank_delta >= move_min_positions:
            improved = True
    if baseline_top3 is not None and current_top3 is not None:
        top3_delta = int(current_top3) - int(baseline_top3)
        if top3_delta >= move_min_top3_pins:
            improved = True

    if improved:
        return {"branch": "moved", "improved": True,
                "reason": _moved_reason(rank_delta, top3_delta),
                "rank_delta": rank_delta, "top3_delta": top3_delta}

    if drill_level < cap:
        return {"branch": "drill", "improved": False,
                "reason": (f"no movement after level {drill_level} — drill deeper "
                           f"(sub-PAAs, level {drill_level + 1} of {cap})"),
                "rank_delta": rank_delta, "top3_delta": top3_delta}

    return {"branch": "halt", "improved": False,
            "reason": (f"no movement after {cap} drill levels — STOP adding content "
                       "and re-check on-page/entity (the service page itself, the "
                       "entity signals); more PAAs will not fix it"),
            "rank_delta": rank_delta, "top3_delta": top3_delta}


def _moved_reason(rank_delta: Optional[float], top3_delta: Optional[int]) -> str:
    bits = []
    if rank_delta is not None and rank_delta > 0:
        bits.append(f"average rank improved {rank_delta:g} position(s)")
    if top3_delta is not None and top3_delta > 0:
        bits.append(f"+{top3_delta} top-3 pin(s)")
    return "content moved the needle" + (f" ({'; '.join(bits)})" if bits else "")


def state_for_branch(branch: str) -> str:
    """Map a gate branch to the campaign state it drives. Pure."""
    return {
        "moved": "moved",
        "drill": "drill_ready",
        "halt": "halted",
        "no_data": "scan_ready",  # re-measure rather than mis-branch
    }.get(branch, "scan_ready")


# ── transition log ────────────────────────────────────────────────────────────


def record_transition(
    history: Optional[list], from_state: str, to_state: str, now: datetime,
    note: Optional[str] = None, *, cap: int = 100,
) -> list:
    """Append one transition to the (append-only) campaign history. Pure —
    returns a NEW list, newest last, bounded to ``cap`` entries."""
    entries = list(history or [])
    entries.append({
        "at": now.isoformat(),
        "from": from_state,
        "to": to_state,
        "note": note,
    })
    return entries[-cap:]


# ── next-action descriptor (UI + notification) ────────────────────────────────


def next_action(campaign: dict) -> dict:
    """The campaign's current call-to-action for the UI + notifications. Pure.

    Returns ``{action, label, confirm, when}`` where ``confirm`` is True for the
    two human-gated (paid/content) steps — the hybrid propose-confirm posture
    (PRD §12.2 fork 1). ``action='none'`` when the campaign is auto-advancing or
    terminal."""
    state = campaign.get("state")
    if state == "draft":
        return {"action": "create_posts", "label": "Create the PAA posts to start "
                "the campaign", "confirm": True, "when": None}
    if state == "content":
        return {"action": "await_content", "label": "PAA posts are being written — "
                "waiting for them to finish + verify", "confirm": False, "when": None}
    if state == "settling":
        return {"action": "settling", "label": "Content is settling before the "
                f"single-variable scan (waits ~{SETTLE_DAYS} days — the wait is "
                "load-bearing, [PROVEN methodology])", "confirm": False,
                "when": campaign.get("settle_until")}
    if state == "scan_ready":
        return {"action": "confirm_scan", "label": "Ready to scan — confirm to run "
                "a single-keyword Maps geo-grid for the service keyword", "confirm": True,
                "when": None}
    if state == "scanning":
        return {"action": "await_scan", "label": "Geo-grid scan in flight — reading "
                "the gate when it completes", "confirm": False, "when": None}
    if state == "drill_ready":
        return {"action": "confirm_drill", "label": "No movement — confirm to drill "
                f"deeper (sub-PAAs, level {int(campaign.get('drill_level') or 0) + 1} "
                f"of {DRILL_CAP})", "confirm": True, "when": None}
    if state == "moved":
        return {"action": "handoff", "label": "It moved — build/refresh the prep-sheet "
                "manifest to hand off the authority layer (tracked, never executed), "
                "and consider the next topically-related service", "confirm": False,
                "when": None}
    if state == "maintenance":
        return {"action": "maintenance", "label": "Ranking holding — re-checks on the "
                f"rinse cadence (~{RINSE_DAYS} days)", "confirm": False,
                "when": campaign.get("next_action_at")}
    if state == "halted":
        return {"action": "review", "label": campaign.get("halted_reason")
                or "Halted — re-check on-page/entity; more PAAs will not fix it",
                "confirm": False, "when": None}
    return {"action": "none", "label": "", "confirm": False, "when": None}


# ── drilling ──────────────────────────────────────────────────────────────────


def drill_seed_questions(items: list[dict], drill_level: int) -> list[str]:
    """The seed questions a drill round pulls sub-PAAs from: the chosen questions
    at the CURRENT (deepest) drill level (the natural PAA tree — pull each
    question's own People-Also-Ask children). Pure.

    Falls back to every chosen question when none carry a drill_level (e.g. a v1
    set adopted into a campaign)."""
    at_level = [
        (i.get("question") or "").strip()
        for i in items or []
        if i.get("chosen") and int(i.get("drill_level") or 0) == drill_level
        and (i.get("question") or "").strip()
    ]
    if at_level:
        return at_level
    return [
        (i.get("question") or "").strip()
        for i in items or []
        if i.get("chosen") and (i.get("question") or "").strip()
    ]


# ── surfaced copy ─────────────────────────────────────────────────────────────


def gate_summary_text(campaign: dict, gate: dict) -> str:
    """One-line human summary of a gate read, carrying the confidence tag. Pure."""
    branch = gate.get("branch")
    reason = gate.get("reason") or ""
    head = {
        "moved": "Moved",
        "drill": "No movement — drill",
        "halt": "HALT",
        "no_data": "No data",
    }.get(branch, branch or "")
    return f"{head}: {reason}. {GATE_CONFIDENCE_NOTE}"
