"""SerMaStr — the Search Marketing Strategist Agent (docs/modules/
seo-strategist-agent-plan-v1_0.md). Phase 1: the strategist run.

ONE run per client per trigger (weekly scheduled / escalation event /
on-demand): digest in (services/strategy_digest — signal envelopes, keyword
passports, staleness, SOP + module-card retrieval), a bounded Claude tool-use
loop over the drill-down tools (services/strategist_tools), one
``strategy_reviews`` row out — an assessment, findings with SOP citations,
**proposals staged for human Approve/Dismiss (the strategist proposes, never
executes)**, and questions for anything no SOP owns.

Hard boundaries (spec §3) are enforced in BOTH the system prompt and code:
  * every tool is read-only; drill-downs are capped per run (the paid
    ``audit_page`` capped tighter);
  * mandatory human passthroughs (freeze, GBP suspension, sub-50% margin,
    separate-entity calls, overclock, the 6-week review itself) — matching
    proposals are force-marked ``requires: senior`` in ``sanitize_review``;
  * a frozen client gets an observation-only briefing — code drops any
    proposals;
  * "we never disavow" — a disavow proposal is dropped to a question.

Everything is gated on ``settings.strategist_enabled`` (default FALSE — the
smoke gate). Pure helpers (``sanitize_review``) are unit-tested.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import notifications, sop_library, sop_store, strategy_digest

logger = logging.getLogger(__name__)

_LLM_TIMEOUT = 180.0
VALID_TRIGGERS = ("scheduled", "escalation", "on_demand", "monthly_plan_review", "goal_recovery")

# §3.2 mandatory human passthroughs — a proposal that lands in this territory
# is briefed, never decided: force requires="senior" regardless of what the
# model set. Patterns are deliberately narrow (decision territory, not mere
# topic mentions of e.g. "margin").
_SENIOR_PATTERNS = re.compile(
    r"(freeze|unfreeze|lift the freeze|manual action|deindex|reconsideration"
    r"|suspension|suspended listing|reinstatement|duplicate listing"
    r"|separate entity|second entity|new entity|dba"
    r"|overclock|hydra|das v2"
    r"|below 50% margin|margin below 50|sub-50% margin)",
    re.IGNORECASE,
)
# Checked against title+action only (what the proposal would DO) — a rationale
# that merely mentions disavow to rule it out must not kill the proposal.
_DISAVOW = re.compile(r"disavow", re.IGNORECASE)

# In-scope tactics for the intervention-outcome loop (mirrors
# interventions.TACTIC_TYPES — kept here so sanitize_review stays pure/DB-free).
_INTERVENTION_TACTICS = ("link_building", "reoptimization")


def sanitize_proposal_target(raw) -> Optional[dict]:
    """The sanitized intervention ``target`` off a raw emit proposal, or None. Pure.

    Honored only when it names an in-scope tactic AND at least one concrete
    anchor (keyword or page_url); otherwise dropped, so the proposal behaves
    exactly as an untargeted one (no intervention is ever registered)."""
    if not isinstance(raw, dict):
        return None
    tactic = raw.get("tactic_type")
    if tactic not in _INTERVENTION_TACTICS:
        return None
    keyword = (raw.get("keyword") or "").strip()
    page_url = (raw.get("page_url") or "").strip()
    if not (keyword or page_url):
        return None
    return {"tactic_type": tactic, "keyword": keyword or None, "page_url": page_url or None}


_EMIT_TOOL = {
    "name": "emit_strategy_review",
    "description": (
        "Emit the final strategy review. Call this exactly once when your analysis is "
        "complete (after any drill-downs). This ENDS the run. Write the fields in the "
        "order given: assessment, then PROPOSALS and QUESTIONS, then findings — the "
        "actionable parts first, so nothing actionable is lost if the output runs long."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "assessment": {
                "type": "string",
                "description": "The one-paragraph strategic read of this client's whole search surface.",
            },
            "root_cause": {
                "type": "string",
                "description": "REQUIRED on a goal_recovery run, optional otherwise: two sentences naming "
                "the SPECIFIC driver of the behind goal — the competitor(s), the sector/quadrant, and "
                "what they built or did (from the competitors + maps sections). Never 'a competitor "
                "is surging'.",
            },
            "proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "action": {"type": "string", "description": "What a human would do, concretely."},
                        "rationale": {"type": "string"},
                        "sop_citation": {"type": "string"},
                        "cost_basis": {
                            "type": "string", "enum": ["recipe", "operational", "none"],
                            "description": "How this proposal is costed: 'recipe' = costed agency deliverable "
                            "tactics (name them in costed_items); 'operational' = a paid tool/API run "
                            "(scan / research / backlink pull — name the operation in costed_items); 'none' = "
                            "labor/variable, not costable. NEVER write a dollar figure — the system computes it.",
                        },
                        "costed_items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "task_type": {"type": "string", "description": "A task_type from the AGENCY PRICE LIST in your input."},
                                    "quantity": {"type": "number"},
                                },
                                "required": ["task_type", "quantity"],
                            },
                            "description": "The costed tactics/operations this proposal entails, by task_type "
                            "from the AGENCY PRICE LIST. The system computes the dollar total from the real "
                            "price list — do not put dollar amounts here or anywhere.",
                        },
                        "effort": {"type": "string", "enum": ["low", "medium", "high"]},
                        "assignee_hint": {
                            "type": "string",
                            "description": "Per the roles matrix (Kyle/Ryan/Minda/Ivy) or 'UNSTAFFED'.",
                        },
                        "requires": {"type": "string", "enum": ["none", "approval", "senior"]},
                        "target": {
                            "type": "object",
                            "description": "OPTIONAL — set ONLY for a link-building or "
                            "reoptimization proposal aimed at moving a specific tracked "
                            "keyword / page that is tied to a campaign goal. This enrolls "
                            "the proposal in the intervention-outcome loop, which later "
                            "measures whether the work actually moved the metric. Omit for "
                            "everything else (an untargeted proposal is unaffected).",
                            "properties": {
                                "tactic_type": {"type": "string", "enum": ["link_building", "reoptimization"]},
                                "keyword": {"type": "string", "description": "the tracked keyword this targets, verbatim from the digest"},
                                "page_url": {"type": "string", "description": "the page being reoptimized / built to, if applicable"},
                            },
                            "required": ["tactic_type"],
                        },
                    },
                    "required": ["title", "action", "rationale"],
                },
            },
            "questions": {
                "type": "array", "items": {"type": "string"},
                "description": "Halt-and-ask items: decisions no SOP owns, SOP conflicts, missing inputs.",
            },
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "signal_refs": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Which digest signals this synthesis rests on (keyword/module refs).",
                        },
                        "synthesis": {"type": "string", "description": "The cross-signal insight itself."},
                        "sop_citation": {"type": "string", "description": "The SOP doc/section that frames it ('' if none)."},
                    },
                    "required": ["synthesis"],
                },
            },
        },
        "required": ["assessment"],
    },
}

_SYSTEM = """You are SerMaStr, the in-house Search Marketing STRATEGIST for an SEO agency. \
The deterministic layer already detects, classifies, plans and verifies; you are the middle \
tier of judgment — the calls the SOPs assign to "the SEO running the campaign" that don't \
require the senior owners' authority. Your scope is the client's ENTIRE search surface: \
organic SERPs, the local pack / Maps, AI-answer visibility, content, links/offpage, budget.

WHAT YOU'RE FOR (in priority order):
0. Goal accountability — when the digest carries campaign_goals, open your assessment with \
progress against them (their status is precomputed — achieved/on_track/behind/overdue; \
report it, never re-derive it) and aim findings/proposals at the goals that are behind. A \
behind goal with no proposal addressing it is a gap in your review. If instead campaign_goals \
reads {"no_goals": true}, this client has NO success metric defined — raise that as a finding \
or a question: recommend defining one measurable campaign goal so progress can be judged, and \
suggest a fitting metric from what the client is actually measured on in the digest (organic \
rank position, GBP calls, impressions/clicks, AI visibility, or maps pack presence). The digest's forecast \
section carries deterministic trajectory numbers (goal_projections, quick-win value) — cite \
them verbatim with their linear-extrapolation caveat; never compute your own projections. \
When the digest carries intervention_outcomes, read it as evidence of what has actually \
WORKED for this client: it is the per-tactic effectiveness of past goal-linked link-building \
/ reoptimization work (worked/partial/no_effect at each intervention's 6-week mark). Cite it \
to favour tactics with a track record and to justify pausing ones that haven't moved the \
metric — but it is REPORT-ONLY context, small-sample, never a hard rule; weigh it, don't \
mechanically obey it, and don't invent a verdict the rollup doesn't show.
When proposing a link-building or reoptimization action aimed at a specific tracked keyword / \
page that maps to a campaign goal, set the proposal's optional `target` (tactic_type + the \
keyword and/or page_url) so the outcome loop can later measure whether it worked. Omit it for \
any other proposal.
1. Cross-domain synthesis — signals that only mean something together (e.g. organic + maps \
declining + heavy off-topic content = vector confusion, not three separate problems).
2. Conflicting or unusual signal patterns the deterministic B1–B5 / playbook rules don't cover.
3. "The plan says X but the context suggests Y" — challenge the Recipe Engine / Action Plan \
when the evidence points elsewhere, with the evidence.
4. Escalation briefs — when a 6-week episode escalates, prepare the case file: what was \
tried, what moved, what you recommend the seniors decide.
5. Proactive opportunity mining — problems announce themselves (alerts, drops, behind \
goals); OPPORTUNITIES don't, and finding them is your job. Sweep EVERYTHING in the digest \
for under-used raw material and unexploited gaps, cross-referencing sections:
  - Customer voice (reviews): a theme recurring in the CLIENT's reviews (a praised amenity, \
speed, a differentiator like free parking) is marketing material — propose the content that \
leverages it (GBP posts, page-copy angles, AEO/AI-answer content), naming the theme and \
count. A theme in a COMPETITOR's reviews is a positioning gap or an unmatched weapon.
  - Competitive intelligence (competitors + gbp_audit): a competitor's recent_pages push \
with no answer from us, category_gaps most competitors carry, the review deficit, an \
organic-overlap keyword they hold that we don't cover — each maps to a concrete proposal.
  - Coverage (content vs client): hold the content inventory against the ICP/ \
differentiators and target_cities — a service the ICP names with no page, a served city \
with no location page, a differentiator no content mentions, is a gap worth a proposal.
  - Timing (trends + forecast): rising seasonal demand is when content/GBP pushes land \
hardest; quick-win keywords say where effort converts fastest.
  - Demand realized (gbp_metrics + ga4): these measure whether visibility is turning into \
attention and action — GBP profile views + calls/clicks/directions, and GA4 sessions/ \
conversions by channel. Read them AGAINST rank: rising positions with flat organic \
sessions/GBP views is a CTR/SERP-feature or listing-prominence problem, not a ranking one; \
falling views/sessions with steady rank points at seasonality (cross-check trends), not a \
drop. A strong action metric (e.g. calls up sharply) is proof a lever worked — name it.
Heed each section's TRAP note; propose only what the evidence in front of you supports; \
cite the owning SOP as usual, and if no SOP owns the action surface it as a question.
Do NOT restate the Action Plan back — it's in your input. Add judgment, not inventory. \
EMPTY PROPOSALS ARE VALID ONLY when every behind/overdue goal already has an OPEN proposal \
addressing it — the digest's open_proposals section lists your own still-unactioned \
proposals with their age and cost; read it before deciding there is nothing new. Otherwise \
re-propose: refreshed against today's numbers and re-costed, saying which earlier proposals \
still stand rather than duplicating them. A behind goal with no open proposal is never \
"nothing to add".

HARD RULES (enforced in code too — violations are stripped):
- You PROPOSE; you never execute. Every proposal is an advice object a human approves.
- Cite the owning SOP on findings/proposals (doc + section). A decision NO SOP owns must be \
a QUESTION, never a proposal. If two SOPs appear to conflict, report the conflict as a \
question — don't pick a side silently.
- Mandatory human passthroughs (brief, never decide): manual action / deindexing (Freeze \
Protocol), GBP suspension or duplicate listings, margin below 50%, separate-entity/DBA \
recommendations, overclock diagrams outside their pre-push gates, and the 6-week strategy \
review itself. Mark any such proposal requires="senior".
- FROZEN client: observation-only briefing. No proposals at all (a freeze pauses decide + \
output; you are part of "decide").
- We NEVER disavow. Never propose it.
- SOP claims labeled "(working model)" are the agency's operating theory — cite them as \
theory, not fact.
- Never invent numbers, keywords, or modules. A signal marked STALE is not current truth. \
"insufficient_data" means exactly that.
- COSTING: never write a dollar amount. For each proposal set cost_basis and, for recipe/ \
operational proposals, name the costed task_types + quantities from the AGENCY PRICE LIST in \
your input; the system computes the real cost. If a proposal doesn't map to a priced item, \
use cost_basis="none".

HOW TO READ THE INSTRUMENTS: module cards are included in your input — follow them exactly \
(they exist because the common failure is misreading, not mis-reasoning: average_rank without \
found_pins, a null GSC position read as a rank loss, one AI answer-flip read as a trend). \
The client section's local_campaign flag says whether this client runs a LOCAL campaign at \
all — when false, local-only setup (target_cities, GBP) reads n/a; that is the correct state \
for a non-local client, never a gap or a finding.

DRILL-DOWNS: you may call the provided read-only tools when the digest genuinely isn't \
enough — they are capped per run (the cap is in your input); the paid audit_page tighter \
still. Prefer emitting with what you have over burning drill-downs on curiosity.

When done, call emit_strategy_review exactly once."""


# ─────────────────────────────────────────────────────────────────────────────
# Cost grounding — the LLM never writes a dollar figure. It names costed
# task_types (from the merged price list); the code computes the money from the
# Recipe Engine's real deliverable prices + the tool_costs API/tool prices. A
# tool op whose price isn't researched yet is kept (so the proposal still shows
# what it maps to) but contributes no dollars — rendered "tool cost", never $0.
# ─────────────────────────────────────────────────────────────────────────────
def _cost_catalog() -> dict:
    """Merged {task_type: {..., unit_cost, unit, kind, verified}} across the
    Recipe Engine deliverables (always real/verified) and the tool_costs API
    operations (verified only once researched). Pure."""
    from services import recipe_engine, tool_costs

    catalog: dict = {}
    for tt, entry in recipe_engine.price_catalog().items():
        catalog[tt] = {**entry, "kind": "recipe", "verified": True}
    for tt, entry in tool_costs.tool_catalog().items():
        catalog.setdefault(tt, {**entry, "kind": "tool"})
    return catalog


def ground_proposal_cost(raw_items, declared_basis=None) -> tuple:
    """(est_cost_usd, costed_items, cost_basis) for one proposal. Pure.

    - costed_items: the model's items filtered to real catalog task_types with a
      positive quantity;
    - est_cost_usd: the dollar total over the VERIFIED entries only (None when
      nothing priced maps — an un-researched tool op yields None, not $0);
    - cost_basis: derived from what the items map to (recipe if any deliverable,
      else operational if any tool op), falling back to the model's declared
      basis, else 'none'.
    """
    from services import recipe_engine

    catalog = _cost_catalog()
    costed_items = []
    for it in raw_items or []:
        if not isinstance(it, dict):
            continue
        tt = it.get("task_type")
        if tt not in catalog:
            continue
        try:
            qty = float(it.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        costed_items.append({"task_type": str(tt), "quantity": qty})

    verified = {tt: e for tt, e in catalog.items() if e.get("verified")}
    est = recipe_engine.cost_of(costed_items, verified)

    kinds = {catalog[it["task_type"]]["kind"] for it in costed_items}
    if "recipe" in kinds:
        basis = "recipe"
    elif "tool" in kinds:
        basis = "operational"
    else:
        basis = declared_basis if declared_basis in ("recipe", "operational", "none") else "none"
    return est, costed_items, basis


def render_price_list() -> str:
    """The AGENCY PRICE LIST block for the run prompt — the task_types the model
    may reference in costed_items, with real prices (tool ops show 'price
    pending' until researched). Pure."""
    from services import recipe_engine, tool_costs

    lines = [
        "Ground every proposal cost by naming task_types from this list in costed_items — "
        "the SYSTEM computes the dollars; never write a $ figure yourself.",
        "",
        "Deliverable tactics (real agency prices):",
    ]
    for tt, e in recipe_engine.price_catalog().items():
        lines.append(f"- {tt}: {e['label']} — ${e['unit_cost']:.0f}/{e['unit']}")
    lines += ["", "Tool / API operations (per run; some prices are pending research — still "
              "name them, the system labels un-priced ones 'tool cost'):"]
    for tt, e in tool_costs.tool_catalog().items():
        price = f"${e['unit_cost']:.2f}/{e['unit']}" if e["verified"] else "price pending"
        lines.append(f"- {tt}: {e['label']} — {price}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Output-limit truncation guard. From mid-August 2026 every scheduled review
# hit max_tokens=4096 on its emit round: findings (then first in the schema)
# consumed the budget, proposals/questions were cut off, and the partial tool
# input was persisted as a 'complete' review with 0 proposals — portfolio-wide,
# silently. The schema now puts proposals/questions first; on stop_reason
# max_tokens the run retries the emit ONCE with an explicit "you were cut off"
# turn, and a review still truncated after that is flagged, never silent.
# ─────────────────────────────────────────────────────────────────────────────
_MAX_TRUNCATION_RETRIES = 1

TRUNCATION_QUESTION = (
    "[truncated] The model's output hit the token limit even after a retry — "
    "proposals/questions may be incomplete. Re-run this review (and check "
    "strategist_max_tokens) before acting on it as a full picture."
)

_TRUNCATION_FOLLOWUP_TEXT = (
    "Your emit_strategy_review call was CUT OFF by the output limit and was NOT "
    "recorded. Call emit_strategy_review again now, and write it compactly: "
    "assessment, then ALL proposals and questions, then at most 5 findings of at "
    "most 2 sentences each. Do not call any other tool."
)


def is_truncated(resp) -> bool:
    """Whether an Anthropic response ended on the output limit. Pure."""
    return getattr(resp, "stop_reason", None) == "max_tokens"


def truncation_followup(tool_uses: list) -> "list[dict] | str":
    """The user turn that asks for a compact re-emit after a truncated round. Pure.

    Every tool_use block the cut-off assistant turn carried needs a tool_result
    in the next user turn (API contract), so the follow-up rides as one
    tool_result per block; with no tool_use block it is a plain text turn."""
    if not tool_uses:
        return _TRUNCATION_FOLLOWUP_TEXT
    return [
        {"type": "tool_result", "tool_use_id": block.id, "content": _TRUNCATION_FOLLOWUP_TEXT}
        for block in tool_uses
    ]


def _assistant_turn(content) -> dict:
    """The assistant message to append for a response — a truncated response can
    carry zero content blocks, which the API rejects as an empty turn."""
    blocks = list(content or [])
    if not blocks:
        blocks = [{"type": "text", "text": "[output cut off]"}]
    return {"role": "assistant", "content": blocks}


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested)
# ─────────────────────────────────────────────────────────────────────────────
def sanitize_review(raw: dict, *, frozen: bool) -> dict:
    """Enforce the §3 output contract on the model's emit payload. Pure.

    - lists coerced; per-proposal status='proposed'; requires defaulted to
      'approval' and clamped to the enum;
    - passthrough-territory proposals force-marked requires='senior';
    - disavow proposals dropped and surfaced as a question instead;
    - frozen client → proposals emptied (observation-only), noted in questions.
    """
    assessment = (raw.get("assessment") or "").strip()
    root_cause = (raw.get("root_cause") or "").strip() if isinstance(raw.get("root_cause"), str) else ""
    findings = []
    for f in raw.get("findings") or []:
        if not isinstance(f, dict) or not (f.get("synthesis") or "").strip():
            continue
        findings.append(
            {
                "signal_refs": [str(s) for s in (f.get("signal_refs") or []) if s],
                "synthesis": f["synthesis"].strip(),
                "sop_citation": (f.get("sop_citation") or "").strip(),
            }
        )
    questions = [str(q).strip() for q in (raw.get("questions") or []) if str(q).strip()]

    proposals = []
    for p in raw.get("proposals") or []:
        if not isinstance(p, dict):
            continue
        title = (p.get("title") or "").strip()
        action = (p.get("action") or "").strip()
        if not (title and action):
            continue
        blob = f"{title} {action} {p.get('rationale') or ''}"
        if _DISAVOW.search(f"{title} {action}"):
            questions.append(
                f"[dropped proposal — we never disavow] {title}: {action} — if link toxicity is "
                "the real concern, the SOP levers are anchor dilution / velocity throttling / "
                "stopping builds; flag to the senior SEOs."
            )
            continue
        requires = p.get("requires") if p.get("requires") in ("none", "approval", "senior") else "approval"
        if _SENIOR_PATTERNS.search(blob):
            requires = "senior"
        effort = p.get("effort") if p.get("effort") in ("low", "medium", "high") else None
        # Cost is GROUNDED, never taken from the model: it names costed task_types
        # and the code computes the dollars from the real price list.
        est, costed_items, cost_basis = ground_proposal_cost(
            p.get("costed_items"), p.get("cost_basis")
        )
        proposal = {
            "title": title,
            "action": action,
            "rationale": (p.get("rationale") or "").strip(),
            "sop_citation": (p.get("sop_citation") or "").strip(),
            "est_cost_usd": est,
            "cost_basis": cost_basis,
            "costed_items": costed_items,
            "effort": effort,
            "assignee_hint": (p.get("assignee_hint") or "").strip() or None,
            "status": "proposed",
            "requires": requires,
        }
        # Intervention-outcome loop: carry a sanitized target through so approval
        # can register the intervention. Only added when valid — absent target
        # means the proposal is untargeted (no measurement enrollment).
        target = sanitize_proposal_target(p.get("target"))
        if target:
            proposal["target"] = target
        proposals.append(proposal)

    if frozen and proposals:
        questions.append(
            f"[client frozen] {len(proposals)} proposal(s) withheld — a freeze pauses decide+output; "
            "this review is observation-only until the freeze lifts."
        )
        proposals = []

    body = {
        "assessment": assessment,
        "findings": findings,
        "proposals": proposals,
        "questions": questions,
    }
    if root_cause:
        body["root_cause"] = root_cause
    return body


def build_run_prompt(
    digest_json: str,
    sops_text: str,
    cards_text: str,
    *,
    trigger: str,
    frozen: bool,
    max_drilldowns: int,
    max_paid: int,
    escalation_context: Optional[dict] = None,
    price_list: str = "",
    track_record: str = "",
    recovery_block: str = "",
) -> str:
    """Assemble the single user message for the run. Pure.

    ``track_record`` (optional) is the action-log learning block — SerMaStr's own
    approve/dismiss + worked/no_effect history, injected only when the dark
    ``sermastr_audit_learning_enabled`` flag is on. Empty string → the prompt is
    byte-identical to today."""
    _MONTHLY_ORIENTATION = (
        " — MONTHLY TASK-PLAN REVIEW. This runs a few days BEFORE next month's "
        "task plan is generated. Read the current monthly task plan in the digest "
        "(task_plan: its tasks, diagnosis, deployable/remaining budget, and flags) "
        "alongside the campaign's real position, and propose the specific "
        "ADDITIONS and MODIFICATIONS next month's plan needs — a new/expanded "
        "task to close a diagnosed gap, a reprioritised or dropped task that the "
        "data no longer supports, a shifted budget allocation. Each change is a "
        "PROPOSAL (advice only): a human approves it, and PACE then assigns the "
        "approved work to the right person under their capacity — so make each "
        "proposal a concrete, assignable task with its rationale, not a vague "
        "theme. Stay within the deployable budget the plan already shows."
    )
    _RECOVERY_ORIENTATION = (
        " — CHRONIC-GOAL RECOVERY PLAN. A campaign goal has been critically behind for weeks "
        "and the alarm has already been raised; your job now is the SOLUTION. You MUST emit "
        "proposals: a concrete, multi-tactic recovery plan for the goal(s) in the RECOVERY "
        "CONTEXT block, each proposal SOP-cited and costed via costed_items, ordered by "
        "priority (highest leverage per dollar first — the SYSTEM assigns budget tiers from "
        "the running total in YOUR order, so the order is the plan). You MUST set root_cause, "
        "naming the specific competitor(s), the sector/quadrant, and what they built or did. "
        "Proposals may reallocate the current monthly task plan (name what to drop and what "
        "to fund with it). If the within-budget set is thin, add ONE budget-adequacy proposal "
        "(drop-month margin / retainer conversation) marked requires='senior'. Refresh and "
        "re-cost the prior recovery plan's open proposals rather than duplicating them; "
        "anything you do not re-emit is superseded. Findings stay short — the plan is the "
        "deliverable."
    )
    parts = [
        f"TRIGGER: {trigger}"
        + (" — prepare the escalation brief for the senior review (what was tried, what moved, "
           "what you recommend they decide)." if trigger == "escalation" else "")
        + (_MONTHLY_ORIENTATION if trigger == "monthly_plan_review" else "")
        + (_RECOVERY_ORIENTATION if trigger == "goal_recovery" else ""),
    ]
    if recovery_block:
        parts.append(recovery_block)
    if escalation_context and trigger != "goal_recovery":
        import json as _json

        parts.append("ESCALATION EVENT:\n" + _json.dumps(escalation_context, default=str))
    if frozen:
        parts.append(
            "⚠️ THIS CLIENT IS FROZEN. Observation-only briefing: assess and note findings/"
            "questions, but emit NO proposals."
        )
    parts.append(f"DRILL-DOWN BUDGET: at most {max_drilldowns} tool calls this run "
                 f"(audit_page at most {max_paid}).")
    if cards_text:
        parts.append("MODULE CARDS (how to read each instrument):\n" + cards_text)
    if sops_text:
        parts.append("AGENCY SOPs (selected for this client's active signals):\n" + sops_text)
    if price_list:
        parts.append("AGENCY PRICE LIST:\n" + price_list)
    if track_record:
        parts.append(track_record)
    parts.append("CLIENT DIGEST (JSON — every status is precomputed; staleness is flagged):\n" + digest_json)
    return "\n\n".join(parts)


def review_notification(review: dict, client_name: str) -> Optional[dict]:
    """The Slack/in-app digest for a completed run, or None when the review is
    empty/confirmatory (an empty review posts nothing — spec §4). Pure."""
    proposals = review.get("proposals") or []
    questions = review.get("questions") or []
    findings = review.get("findings") or []
    if not (proposals or questions or findings):
        return None
    trigger = review.get("trigger") or "on_demand"
    n_prop = len(proposals)
    n_q = len(questions)
    senior = sum(1 for p in proposals if p.get("requires") == "senior")
    bits = []
    if n_prop:
        bits.append(f"{n_prop} proposal{'s' if n_prop != 1 else ''}"
                    + (f" ({senior} senior-only)" if senior else ""))
    if n_q:
        bits.append(f"{n_q} open question{'s' if n_q != 1 else ''}")
    if not bits and findings:
        bits.append(f"{len(findings)} finding{'s' if len(findings) != 1 else ''}")
    if trigger == "escalation":
        title = f"Escalation brief ready: {client_name}"
    elif trigger == "monthly_plan_review":
        title = f"Monthly plan review: {client_name} — {', '.join(bits)}"
    else:
        title = f"Strategist review: {client_name} — {', '.join(bits)}"
    assessment = (review.get("assessment") or "").strip()
    summary = assessment[:400] + ("…" if len(assessment) > 400 else "")
    severity = "warning" if (trigger == "escalation" or senior) else "info"
    return {"title": title, "summary": summary, "severity": severity}


# ─────────────────────────────────────────────────────────────────────────────
# The run
# ─────────────────────────────────────────────────────────────────────────────
async def run_strategy_review(
    client_id: str,
    trigger: str = "on_demand",
    review_id: Optional[str] = None,
    escalation_context: Optional[dict] = None,
    notify: bool = False,
) -> dict:
    """Execute one strategist run and persist the strategy_reviews row.
    Returns the completed row. Raises on hard failure (caller marks the job)."""
    from services import strategist_tools

    supabase = get_supabase()
    if review_id is None:
        review_id = (
            supabase.table("strategy_reviews")
            .insert({"client_id": client_id, "trigger": trigger, "status": "running",
                     "model": settings.strategist_model})
            .execute()
        ).data[0]["id"]

    digest = strategy_digest.build_strategy_digest(client_id)
    frozen = bool((digest.get("client") or {}).get("frozen"))
    domains = set(digest.get("active_domains") or [])

    total_chars = settings.strategist_digest_budget_tokens * 4
    cards_text = sop_library.load_module_cards()
    sops_text = sop_library.select_sops_text(domains, budget_chars=min(36_000, total_chars // 3))
    # The DB sop_store layer too (spec §2): agency-wide uploads + PER-CLIENT
    # overrides — the strategist must see the same playbook the Action Plan
    # enrichment honors, not just the repo corpus. Best-effort ('' on failure).
    db_sops = sop_store.resolve_sops_text(client_id, budget_chars=12_000)
    if db_sops:
        sops_text = (sops_text + "\n\n### UPLOADED SOPs (DB store — per-client entries "
                     "take precedence over the repo corpus)\n" + db_sops).strip()
    digest_budget = max(20_000, total_chars - len(sops_text) - len(cards_text))
    digest_json = strategy_digest.render_digest(digest, digest_budget)

    max_dd = settings.strategist_max_drilldowns
    max_paid = settings.strategist_max_paid_drilldowns
    # Self-learning (dark): steer proposals with SerMaStr's own track record —
    # approve/dismiss + worked/no_effect rates per proposal kind. Best-effort +
    # gated: flag off (or thin history) → "" → the prompt is unchanged.
    track_record = ""
    if settings.sermastr_audit_learning_enabled:
        try:
            from services import sermastr_audit

            track_record = sermastr_audit.build_track_record_block(
                sermastr_audit._learning_signals_window(), client_id
            )
        except Exception as exc:  # never let the learning read break a review
            logger.warning("sermastr_track_record_failed",
                           extra={"client_id": client_id, "error": str(exc)})
    recovery: Optional[dict] = None
    recovery_block = ""
    if trigger == "goal_recovery":
        from services import goal_recovery

        try:
            recovery = goal_recovery.load_recovery_context(client_id, escalation_context, digest)
            recovery_block = goal_recovery.build_recovery_block(
                recovery["goals"], recovery["prior_proposals"], recovery["envelope"],
                recovery["ceilings"], recovery["tiers"],
            )
        except Exception as exc:  # the run still happens on the plain digest
            logger.warning("goal_recovery.context_failed",
                           extra={"client_id": client_id, "error": str(exc)})
            recovery = None
    user = build_run_prompt(
        digest_json, sops_text, cards_text,
        trigger=trigger, frozen=frozen, max_drilldowns=max_dd, max_paid=max_paid,
        escalation_context=escalation_context, price_list=render_price_list(),
        track_record=track_record, recovery_block=recovery_block,
    )

    tools = strategist_tools.anthropic_tool_defs() + [_EMIT_TOOL]
    from services import anthropic_failover

    clients = anthropic_failover.build_async_clients(timeout=_LLM_TIMEOUT)
    messages: list[dict] = [{"role": "user", "content": user}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    drilldowns: list[dict] = []
    paid_used = 0
    emitted: Optional[dict] = None

    # Transient-retry each round AND fail over to the secondary Anthropic account
    # (same model): a single 429 (the primary account saturates under scan/report
    # bursts) previously failed the entire review job — one of the most expensive
    # artifacts in the suite to lose.
    truncation_retries = 0
    truncated = False
    # loop bound: every non-emit round consumes ≥1 drill-down, +2 slack rounds,
    # +1 for the single truncation retry
    for round_no in range(max_dd + 3 + _MAX_TRUNCATION_RETRIES):
        force_emit = (
            round_no >= max_dd + 1 or len(drilldowns) >= max_dd or truncation_retries > 0
        )
        resp = await anthropic_failover.call_failover(
            clients,
            lambda c: c.messages.create(
                model=settings.strategist_model,
                max_tokens=settings.strategist_max_tokens,
                system=_SYSTEM,
                tools=tools,
                tool_choice={"type": "tool", "name": "emit_strategy_review"} if force_emit else {"type": "auto"},
                messages=messages,
            ),
            log_tag="strategist",
        )
        usage["input_tokens"] += getattr(resp.usage, "input_tokens", 0) or 0
        usage["output_tokens"] += getattr(resp.usage, "output_tokens", 0) or 0

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        emit_block = next((b for b in tool_uses if b.name == "emit_strategy_review"), None)
        cut_off = is_truncated(resp)
        if cut_off and truncation_retries < _MAX_TRUNCATION_RETRIES:
            # The partial emit (or a cut-off drill-down turn) is discarded; ask
            # for a compact re-emit and force the tool on the next round.
            truncation_retries += 1
            logger.warning(
                "strategist.emit_truncated_retry",
                extra={"client_id": client_id, "review_id": review_id, "round": round_no,
                       "had_emit_block": emit_block is not None},
            )
            messages.append(_assistant_turn(resp.content))
            messages.append({"role": "user", "content": truncation_followup(tool_uses)})
            continue
        if emit_block is not None:
            emitted = emit_block.input or {}
            truncated = cut_off
            break
        if not tool_uses:
            # No tool call and no emit — nudge once, then the force_emit round closes it.
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": "Call emit_strategy_review now."})
            continue

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in tool_uses:
            name, args = block.name, (block.input or {})
            spec = strategist_tools.TOOLS.get(name)
            if spec is None:
                out = f"Unknown tool {name}."
            elif len(drilldowns) >= max_dd:
                out = "Drill-down cap reached — call emit_strategy_review with what you have."
            elif spec["paid"] and paid_used >= max_paid:
                out = "Paid-call cap reached for this run — proceed without it."
            else:
                try:
                    out = await spec["run"](client_id, args)
                except Exception as exc:  # a tool failure never kills the run
                    out = f"{name} failed: {exc}"
                drilldowns.append({"tool": name, "args": args})
                if spec["paid"]:
                    paid_used += 1
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
        messages.append({"role": "user", "content": results})

    review_body = sanitize_review(emitted or {}, frozen=frozen)
    if not review_body["assessment"]:
        review_body["assessment"] = (
            "Run ended without a model assessment — treat as failed and re-run."
        )
    usage["drilldowns"] = drilldowns
    if truncated:
        # Still cut off after the retry: keep what parsed (the findings are
        # worth having) but never let it read as a complete picture.
        usage["truncated"] = True
        review_body["questions"].append(TRUNCATION_QUESTION)
        logger.warning(
            "strategist.emit_truncated_final",
            extra={"client_id": client_id, "review_id": review_id,
                   "proposals": len(review_body["proposals"])},
        )

    budget: Optional[dict] = None
    if trigger == "goal_recovery":
        from services import goal_recovery

        try:
            review_body, budget = goal_recovery.apply_budget(
                review_body, recovery or goal_recovery.load_recovery_context(client_id, None, digest)
            )
        except Exception as exc:  # untiered proposals are still proposals
            logger.warning("goal_recovery.budget_failed",
                           extra={"client_id": client_id, "error": str(exc)})

    # The stored input_digest is the structured digest (not the SOP text — that
    # would 5× the row for content already versioned in the repo).
    update_row = {
        "status": "complete",
        "assessment": review_body["assessment"],
        "findings": review_body["findings"],
        "proposals": review_body["proposals"],
        "questions": review_body["questions"],
        "input_digest": digest,
        "token_usage": usage,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    if budget is not None:
        update_row["budget"] = budget
    updated = (
        supabase.table("strategy_reviews")
        .update(update_row)
        .eq("id", review_id)
        .execute()
    ).data[0]

    # Action log (audit + learning): one pending row per proposal, at the
    # strategist's OWN completion seam. Best-effort — never breaks the review.
    try:
        from services import sermastr_audit

        sermastr_audit.log_proposals(
            review_id, client_id,
            (digest.get("client") or {}).get("name"),
            trigger, review_body["proposals"],
        )
    except Exception as exc:
        logger.warning("sermastr_audit_log_failed",
                       extra={"client_id": client_id, "review_id": review_id, "error": str(exc)})

    # Digest notification (Slack rides the notifications service). Scheduled +
    # escalation runs only — an on-demand run from the UI means a human is
    # already looking. `notify` forces it (Slack-triggered on-demand runs, so
    # the answer comes back to the channel that asked).
    if trigger == "goal_recovery":
        # The FINISHED recovery run sends the ONE goal_chronic message (alarm +
        # root cause + plan), supersedes the prior plan and stamps the
        # escalation rows — see services/goal_recovery.after_persist.
        from services import goal_recovery

        goal_recovery.after_persist(
            client_id, {**updated, "id": review_id, "proposals": review_body["proposals"]},
            recovery or {}, budget or {}, (digest.get("client") or {}).get("name"),
        )
    elif trigger in ("scheduled", "escalation", "monthly_plan_review") or notify:
        note = review_notification({**updated, "trigger": trigger},
                                   (digest.get("client") or {}).get("name") or "client")
        if note:
            notifications.emit(
                client_id=client_id,
                kind="strategy_review",
                title=note["title"],
                summary=note["summary"],
                severity=note["severity"],
                payload={"link": f"clients/{client_id}/action-plan", "review_id": review_id},
            )

    logger.info(
        "strategy_review_complete",
        extra={
            "client_id": client_id, "trigger": trigger, "review_id": review_id,
            "proposals": len(review_body["proposals"]),
            "questions": len(review_body["questions"]),
            "drilldowns": len(drilldowns), "frozen": frozen,
            "truncated": truncated, "truncation_retries": truncation_retries,
        },
    )
    return updated


# ─────────────────────────────────────────────────────────────────────────────
# Weekly scheduling (Phase 2) — active-signal clients only (spec §9 default:
# quiet clients skip → cost + noise control). Runs the day after the weekly
# reopt-plan build so the strategist reads a fresh Action Plan.
# ─────────────────────────────────────────────────────────────────────────────
def clients_with_active_signals() -> set[str]:
    """Client ids with anything open: rank/maps/offpage alerts, open or
    escalated response episodes, or a flagged latest monthly task plan.
    Best-effort per source — one failing read never empties the set."""
    supabase = get_supabase()
    ids: set[str] = set()
    for table in ("rank_alerts", "maps_alerts", "offpage_alerts"):
        try:
            rows = (
                supabase.table(table).select("client_id")
                .is_("resolved_at", "null").execute()
            ).data or []
            ids |= {r["client_id"] for r in rows if r.get("client_id")}
        except Exception as exc:
            logger.warning("strategist.active_signals_read_failed", extra={"table": table, "error": str(exc)})
    try:
        rows = (
            supabase.table("response_episodes").select("client_id")
            .in_("status", ["open", "escalated"]).execute()
        ).data or []
        ids |= {r["client_id"] for r in rows if r.get("client_id")}
    except Exception as exc:
        logger.warning("strategist.active_signals_read_failed", extra={"table": "response_episodes", "error": str(exc)})
    try:
        # Latest plan per client (newest-first, first-seen wins); flagged → active.
        rows = (
            supabase.table("monthly_task_plans")
            .select("client_id, flags, created_at")
            .order("created_at", desc=True).limit(200).execute()
        ).data or []
        seen: set[str] = set()
        for r in rows:
            cid = r.get("client_id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            if r.get("flags"):
                ids.add(cid)
    except Exception as exc:
        logger.warning("strategist.active_signals_read_failed", extra={"table": "monthly_task_plans", "error": str(exc)})
    # A behind/overdue campaign goal is an open problem too — the yardstick the
    # whole strategist stack judges against — so fold it in (self-guarded, returns
    # an empty set on any failure so it can never empty the alert-driven signals).
    ids |= clients_with_behind_goals()
    return ids


def clients_with_behind_goals() -> set[str]:
    """Client ids with at least one campaign goal currently behind or overdue.

    Priority-0 of a strategist review is goal accountability, but the
    active-signal set that decides WHICH clients get a weekly review only ever
    looked at alerts/episodes/flagged plans — so a goal quietly going behind
    with no matching rank-drop alert never summoned a review; it reached one
    only via the ~monthly opportunity sweep. Folding behind/overdue goals into
    the active-signal set makes a slipping goal drive the normal weekly cadence.

    Guardrails:
      * a goal counts only when it has a captured ``baseline_value`` — without a
        baseline ``evaluate_goal`` can return "behind" as a MEASUREMENT ARTIFACT
        (a keyword goal made before the keyword was tracked reads behind with a
        null progress_pct), and that must not perpetually summon reviews;
      * only clients that actually have an active goal are assessed (one distinct
        scan first), each in its own try/except — a failing measurement for one
        client never empties the set;
      * gated on ``strategist_goal_trigger_enabled`` so the added per-goal reads
        can be switched off. Best-effort: any failure → empty set.
    """
    if not settings.strategist_goal_trigger_enabled:
        return set()
    from services import campaign_goals

    supabase = get_supabase()
    try:
        rows = (
            supabase.table("campaign_goals").select("client_id")
            .eq("active", True).execute()
        ).data or []
    except Exception as exc:
        logger.warning("strategist.goal_signal_read_failed", extra={"error": str(exc)})
        return set()
    client_ids = {r["client_id"] for r in rows if r.get("client_id")}
    behind: set[str] = set()
    for cid in client_ids:
        try:
            assessed = campaign_goals.assess_goals(cid)
        except Exception as exc:  # one client's failure never drops the rest
            logger.warning("strategist.goal_assess_failed", extra={"client_id": cid, "error": str(exc)})
            continue
        if any(
            g.get("status") in ("behind", "overdue") and g.get("baseline_value") is not None
            for g in assessed
        ):
            behind.add(cid)
    return behind


def clients_due_opportunity_sweep(active: set[str], interval_days: int) -> set[str]:
    """QUIET clients due a proactive opportunity run.

    The active-signal gate keys the weekly pass to open PROBLEMS — but the
    strategist also mines opportunities (review themes, competitor gaps,
    coverage holes), and those exist precisely on clients with nothing on
    fire. Quiet clients therefore still get a scheduled run when their last
    strategist run (any trigger) is older than `interval_days` — proactive
    mining reaches every client at least ~monthly, at a bounded cost of one
    extra run per quiet client per interval. `interval_days <= 0` disables."""
    if interval_days <= 0:
        return set()
    supabase = get_supabase()
    quiet = {
        r["id"]
        for r in (
            supabase.table("clients").select("id").eq("archived", False).execute()
        ).data or []
    } - active
    if not quiet:
        return set()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=interval_days)).isoformat()
    recently_run = {
        r["client_id"]
        for r in (
            supabase.table("strategy_reviews").select("client_id")
            .gte("created_at", cutoff).execute()
        ).data or []
        if r.get("client_id")
    }
    return quiet - recently_run


def clients_scheduled_within(days: int) -> set[str]:
    """Client ids with a `scheduled`-trigger strategist run inside the last
    `days` days. The durable "already ran this week" guard: the weekly weekday
    gate lives in process memory, so without this a redeploy on the strategist
    weekday re-fires the whole active-signal pass. `days <= 0` disables."""
    if days <= 0:
        return set()
    supabase = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return {
        r["client_id"]
        for r in (
            supabase.table("strategy_reviews").select("client_id")
            .eq("trigger", "scheduled")
            .gte("created_at", cutoff).execute()
        ).data or []
        if r.get("client_id")
    }


def client_weekday_map(client_ids: set[str]) -> dict[str, int]:
    """Map each client id to its assigned strategist weekday (0=Mon..6=Sun),
    falling back to the global `strategist_weekly_weekday` when the client has
    none set. Drives per-client staggering of the weekly pass."""
    default = settings.strategist_weekly_weekday
    result = {cid: default for cid in client_ids}
    if not client_ids:
        return result
    supabase = get_supabase()
    rows = (
        supabase.table("clients")
        .select("id, strategist_weekday")
        .in_("id", list(client_ids))
        .execute()
    ).data or []
    for r in rows:
        wd = r.get("strategist_weekday")
        if wd is not None:
            result[r["id"]] = wd
    return result


def enqueue_due_strategy_reviews(today_weekday: Optional[int] = None) -> int:
    """Daily scheduler pass: one scheduled strategist run per active-signal
    client whose assigned strategist day is today, plus quiet clients due the
    opportunity sweep (see `clients_due_opportunity_sweep`). Runs are staggered
    per client via `clients.strategist_weekday` (unset → global default), so
    this is called every day and filters to today's clients rather than gating
    on one global weekday. No-ops entirely while strategist_enabled is false."""
    if not settings.strategist_enabled:
        return 0
    if today_weekday is None:
        today_weekday = datetime.now(timezone.utc).weekday()
    active = clients_with_active_signals()
    # Durable weekly guard: drop active clients that already had a scheduled run
    # this week so a redeploy (or the daily re-check) can't re-fire the pass.
    # (Quiet clients are already interval-gated inside the opportunity sweep.)
    try:
        recent = clients_scheduled_within(settings.strategist_weekly_interval_days)
    except Exception as exc:  # a failed read must never silence the weekly pass
        logger.warning("strategist.recent_scheduled_read_failed", extra={"error": str(exc)})
        recent = set()
    due = set(active) - recent
    try:
        due |= clients_due_opportunity_sweep(
            active, settings.strategist_opportunity_interval_days
        )
    except Exception as exc:  # the sweep must never break the weekly pass
        logger.warning("strategist.opportunity_sweep_failed", extra={"error": str(exc)})
    # Per-client staggering: only enqueue clients whose assigned day is today.
    try:
        weekday_map = client_weekday_map(due)
        due = {cid for cid in due if weekday_map.get(cid) == today_weekday}
    except Exception as exc:  # a failed read must not drop the whole pass — the
        # durable weekly guard still bounds it to once per client per week.
        logger.warning("strategist.weekday_map_read_failed", extra={"error": str(exc)})
    enqueued = 0
    for client_id in sorted(due):
        if enqueue_strategy_review(client_id, trigger="scheduled"):
            enqueued += 1
    if enqueued:
        logger.info("strategist.weekly_enqueued", extra={"clients": enqueued})
    return enqueued


# ─────────────────────────────────────────────────────────────────────────────
# Monthly plan review → PACE assignment handoff
#   A once-a-month strategist run, `_lead_days` before task generation, that
#   proposes ADDITIONS/MODIFICATIONS to next month's Recipe-Engine task plan.
#   Advice + proposals only; an approved proposal is auto-placed capacity-aware
#   by PACE (asana_push.push_proposal → pm_assign.place_task — already wired).
#   Ships dark (strategist_monthly_plan_review_enabled).
# ─────────────────────────────────────────────────────────────────────────────
def _days_in_month(year: int, month: int) -> int:
    import calendar

    return calendar.monthrange(year, month)[1]


def is_monthly_review_day(today: date, generate_day: int, lead_days: int) -> bool:
    """Pure. True on the single day each month that sits `lead_days` before the
    monthly task-generation day (`asana_month_generate_day`, clamped to the
    target month's length). `today + lead_days` landing exactly on the (clamped)
    generation day-of-month handles month boundaries and short months with no
    special-casing — a lead that crosses into the prior month just works."""
    if lead_days < 0:
        return False
    gen = today + timedelta(days=lead_days)
    clamped = min(max(generate_day, 1), _days_in_month(gen.year, gen.month))
    return gen.day == clamped


def _monthly_review_allowlist() -> set[str]:
    """Parse the optional comma-separated pilot allowlist. Empty → empty set
    (no restriction — every eligible client)."""
    raw = settings.strategist_monthly_plan_review_client_ids or ""
    return {c.strip() for c in raw.split(",") if c.strip()}


def clients_reviewed_within(trigger: str, days: int) -> set[str]:
    """Client ids with a run of `trigger` inside the last `days` days — the
    durable "already ran this month" guard (the day gate lives in process
    memory, so a redeploy on the review day would otherwise re-fire). `days <= 0`
    disables."""
    if days <= 0:
        return set()
    supabase = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return {
        r["client_id"]
        for r in (
            supabase.table("strategy_reviews").select("client_id")
            .eq("trigger", trigger)
            .gte("created_at", cutoff).execute()
        ).data or []
        if r.get("client_id")
    }


def clients_due_monthly_plan_review() -> set[str]:
    """Non-archived retainer clients (retainer_monthly > 0) eligible for the
    monthly plan review, narrowed to the pilot allowlist when one is set.
    Best-effort — a read blip returns an empty set (skip this cycle) rather than
    raising into the scheduler."""
    supabase = get_supabase()
    try:
        rows = (
            supabase.table("clients")
            .select("id, retainer_monthly")
            .eq("archived", False)
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("strategist.monthly_review_client_read_failed", extra={"error": str(exc)})
        return set()
    eligible = {
        r["id"] for r in rows
        if r.get("id") and (r.get("retainer_monthly") or 0) > 0
    }
    allow = _monthly_review_allowlist()
    if allow:
        eligible &= allow
    return eligible


def enqueue_due_monthly_plan_reviews(today: Optional[date] = None) -> int:
    """Daily scheduler pass: on the monthly-review day, enqueue one
    `monthly_plan_review` strategist run per eligible retainer client. No-ops
    entirely while strategist_enabled OR strategist_monthly_plan_review_enabled
    is false. `_strategist_excluded` (opted-out properties) is applied inside
    `enqueue_strategy_review`; a client already reviewed this month is dropped by
    the durable guard."""
    if not (settings.strategist_enabled and settings.strategist_monthly_plan_review_enabled):
        return 0
    if today is None:
        today = datetime.now(timezone.utc).date()
    if not is_monthly_review_day(
        today,
        settings.asana_month_generate_day,
        settings.strategist_monthly_plan_review_lead_days,
    ):
        return 0
    due = clients_due_monthly_plan_review()
    try:
        recent = clients_reviewed_within("monthly_plan_review", 20)
    except Exception as exc:  # a failed read must never silence the pass
        logger.warning("strategist.monthly_review_recent_read_failed", extra={"error": str(exc)})
        recent = set()
    due -= recent
    enqueued = 0
    for client_id in sorted(due):
        if enqueue_strategy_review(client_id, trigger="monthly_plan_review"):
            enqueued += 1
    if enqueued:
        logger.info("strategist.monthly_plan_review_enqueued", extra={"clients": enqueued})
    return enqueued


# ─────────────────────────────────────────────────────────────────────────────
# Enqueue + job handler (async_jobs job_type='strategy_review')
# ─────────────────────────────────────────────────────────────────────────────
def _strategist_excluded(client_id: str) -> bool:
    """Whether SerMastr's scheduled strategist skips this client.

    Agency-owned website properties (`clients.kind='owned_property'`) opt out by
    default via `clients.strategist_enabled=false`; a real client is included
    unless someone turned it off. Fail open on a read blip — never silence a real
    client's review over a transient error (`strategist_enabled` is only false
    when explicitly set)."""
    try:
        rows = (
            get_supabase()
            .table("clients")
            .select("strategist_enabled")
            .eq("id", client_id)
            .limit(1)
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001 — fail open
        logger.warning("strategist.excluded_read_failed", extra={"client_id": client_id, "error": str(exc)})
        return False
    return bool(rows) and rows[0].get("strategist_enabled") is False


def enqueue_strategy_review(
    client_id: str,
    trigger: str = "on_demand",
    escalation_context: Optional[dict] = None,
    notify: bool = False,
) -> Optional[str]:
    """Create the strategy_reviews row (status=running, so the UI can show it
    immediately) and enqueue the job. Deduped against an in-flight run for the
    client. Returns the review id, or None when deduped/disabled."""
    if not settings.strategist_enabled:
        return None
    if trigger not in VALID_TRIGGERS:
        trigger = "on_demand"
    # Excluded clients (a website property opted out) skip the AUTOMATED triggers.
    # An explicit on_demand run is a deliberate human act and still allowed.
    if trigger != "on_demand" and _strategist_excluded(client_id):
        logger.info("strategist.client_excluded", extra={"client_id": client_id, "trigger": trigger})
        return None
    supabase = get_supabase()
    # Dedup per trigger, not globally: an escalation brief must not be silently
    # swallowed because the weekly scheduled run happens to be in flight (the
    # single worker serializes them anyway).
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "strategy_review")
        .eq("entity_id", client_id)
        .eq("payload->>trigger", trigger)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return None
    review = (
        supabase.table("strategy_reviews")
        .insert({"client_id": client_id, "trigger": trigger, "status": "running",
                 "model": settings.strategist_model})
        .execute()
    ).data[0]
    payload: dict = {"client_id": client_id, "trigger": trigger, "review_id": review["id"]}
    if escalation_context:
        payload["escalation_context"] = escalation_context
    if notify:
        payload["notify"] = True
    try:
        supabase.table("async_jobs").insert(
            {"job_type": "strategy_review", "entity_id": client_id, "payload": payload}
        ).execute()
    except Exception:
        # Don't orphan the review row as 'running' forever — no worker will
        # ever pick it up if the job insert failed.
        supabase.table("strategy_reviews").update(
            {"status": "failed", "error": "job_enqueue_failed", "completed_at": "now()"}
        ).eq("id", review["id"]).execute()
        raise
    return review["id"]


async def run_strategy_review_job(job: dict) -> None:
    """async_jobs handler for job_type='strategy_review'."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    trigger = payload.get("trigger", "on_demand")
    review_id = payload.get("review_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    if not settings.strategist_enabled:
        # A job enqueued before the flag flipped off: fail it cleanly.
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "strategist_disabled", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        if review_id:
            supabase.table("strategy_reviews").update(
                {"status": "failed", "error": "strategist_disabled", "completed_at": "now()"}
            ).eq("id", review_id).execute()
        return
    try:
        result = await run_strategy_review(
            client_id, trigger=trigger, review_id=review_id,
            escalation_context=payload.get("escalation_context"),
            notify=bool(payload.get("notify")),
        )
    except Exception as exc:
        logger.warning(
            "strategy_review_job_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        if review_id:
            supabase.table("strategy_reviews").update(
                {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
            ).eq("id", review_id).execute()
        return
    supabase.table("async_jobs").update(
        {
            "status": "complete",
            "result": {"review_id": result.get("id"), "proposals": len(result.get("proposals") or [])},
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()
