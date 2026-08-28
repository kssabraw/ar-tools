"""Autonomous SEO agent — the policy / boundary engine (plan §2.2).

The heart of the safety model, and deliberately PURE: given a proposed action,
the client's effective tier, the remaining budget, freeze state, and the week's
content rate, decide whether the autonomy executor may **auto-approve** it,
must **propose** it to a human, or must **escalate** it. No I/O, so the whole
boundary is unit-testable without a database.

Phase 2 ships this as a library; the Phase 3 executor calls `classify` per
candidate proposal. While `autonomy_enabled` is False nothing calls it at all.

Outcomes:
- ``auto``     — in tier, in budget, under the rate cap: the executor may act.
- ``propose``  — allowed in principle but out of tier / over budget / rate-
                 capped: surface it for a human to approve (today's behaviour).
- ``escalate`` — safety boundary: frozen client, senior/passthrough territory,
                 or an action the engine doesn't recognise. Never auto, never a
                 routine "propose"; it goes to a human with the reason.

Precedence is safety-first: freeze → senior/passthrough → requires-approval →
unknown action → out-of-tier → over-budget → rate cap → auto.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Action class → the lowest tier at which it may be auto-approved. Higher tiers
# include lower. Keep in lockstep with the plan's Tier table and the registry.
ACTION_TIERS: dict[str, int] = {
    # Tier 1 — owned & reversible
    "rebuild_action_plan": 1,
    "create_task": 1,
    "schedule_gbp_posts": 1,        # posts to an owned GBP profile
    "run_maps_scan": 1,             # a scan within budget — data, reversible
    "run_gsc_research": 1,
    "run_ai_visibility_scan": 1,
    "generate_client_report": 1,    # internal report
    # Tier 2 — drafts + owned content
    "start_content_run": 2,
    "generate_local_seo_page": 2,
    "reoptimize_page": 2,
    # Tier 3 — client-site-facing / irreversible (held for a later decision)
    "publish_to_client_site": 3,
}

# The content actions the weekly rate cap applies to.
CONTENT_ACTIONS: frozenset[str] = frozenset(
    {"start_content_run", "generate_local_seo_page", "reoptimize_page"}
)

# Passthrough territory (_ORCHESTRATOR.md §3): decisions the agent may brief but
# never make. A proposal naming one of these — or flagged requires="senior" —
# always escalates, whatever the tier or budget.
HALT_AND_ASK: frozenset[str] = frozenset(
    {"disavow", "freeze", "unfreeze", "separate_entity", "dba_recommendation",
     "gbp_suspension", "manual_action"}
)

_AUTO = "auto"
_PROPOSE = "propose"
_ESCALATE = "escalate"


@dataclass(frozen=True)
class PolicyDecision:
    outcome: str   # auto | propose | escalate
    reason: str

    @property
    def is_auto(self) -> bool:
        return self.outcome == _AUTO


def effective_tier(client_tier: Optional[int], max_tier: int) -> int:
    """The tier actually in force: the client's opt-in, capped by the global
    ceiling (v1 = 2, so Tier 3 is never auto-approved even if a client is set
    higher). Missing / negative reads as 0 (off)."""
    t = int(client_tier or 0)
    if t < 0:
        t = 0
    return min(t, int(max_tier))


def action_tier(action: str) -> Optional[int]:
    """The tier an action class belongs to, or None if unknown."""
    return ACTION_TIERS.get(action)


def classify(
    proposal: dict,
    *,
    client_tier: int,
    budget_left: Optional[float] = None,
    freeze: bool = False,
    content_this_week: int = 0,
    content_cap: int = 3,
) -> PolicyDecision:
    """Decide the fate of one proposed action. Pure.

    ``proposal`` carries at least ``action`` (the registry action name); it may
    also carry ``requires`` (none|approval|senior, mirroring strategist
    proposals) and ``cost_usd`` (the action's estimated spend). ``client_tier``
    is the EFFECTIVE tier (already capped — see ``effective_tier``).

    INVARIANT for callers: the budget check here is ADVISORY — a pre-filter on
    the ``budget_left`` snapshot, NOT the spend gate. A caller that will actually
    spend money MUST additionally reserve it atomically via
    ``autonomy_budget.reserve`` and proceed only when that returns True. An
    ``auto`` verdict is necessary but NOT sufficient to spend (two reads can't be
    atomic; only the reservation RPC is).
    """
    action = str(proposal.get("action") or proposal.get("name") or "").strip()
    requires = str(proposal.get("requires") or "none").strip().lower()
    try:
        cost = float(proposal.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0

    # 1. Frozen client — never act; freeze pauses decide + output.
    if freeze:
        return PolicyDecision(_ESCALATE, "client frozen — observation only")

    # 2. Senior / passthrough territory — brief, never decide.
    if requires == "senior" or action in HALT_AND_ASK:
        return PolicyDecision(_ESCALATE, "senior / passthrough territory")

    # 3. Human-approval-required (a strategist proposal flagged requires=approval)
    #    — surface it, never auto-run, whatever the tier/budget.
    if requires == "approval":
        return PolicyDecision(_PROPOSE, "requires human approval")

    # 4. Unknown action class — never auto-approve something we can't reason about.
    tier = ACTION_TIERS.get(action)
    if tier is None:
        return PolicyDecision(_ESCALATE, f"unknown action class: {action or '?'}")

    # 5. Above the client's effective tier — a human may still do it.
    if tier > client_tier:
        return PolicyDecision(_PROPOSE, f"tier {tier} above effective tier {client_tier}")

    # 6. Over the remaining autonomous budget.
    if budget_left is not None and cost > 0 and cost > budget_left:
        return PolicyDecision(_PROPOSE, "over remaining autonomous budget")

    # 7. Weekly content rate cap.
    if action in CONTENT_ACTIONS and content_this_week >= content_cap:
        return PolicyDecision(_PROPOSE, "weekly content rate cap reached")

    # 8. In tier, in budget, under the cap.
    return PolicyDecision(_AUTO, "in tier, in budget, under rate cap")
