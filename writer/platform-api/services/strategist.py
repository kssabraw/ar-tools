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
from datetime import datetime, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import notifications, sop_library, strategy_digest

logger = logging.getLogger(__name__)

_LLM_TIMEOUT = 180.0
VALID_TRIGGERS = ("scheduled", "escalation", "on_demand")

# §3.2 mandatory human passthroughs — a proposal that lands in this territory
# is briefed, never decided: force requires="senior" regardless of what the
# model set. Patterns are deliberately narrow (decision territory, not mere
# topic mentions of e.g. "margin").
_SENIOR_PATTERNS = re.compile(
    r"(freeze|unfreeze|lift the freeze|manual action|deindex"
    r"|suspension|suspended listing|duplicate listing"
    r"|separate entity|second entity|new entity|dba"
    r"|overclock|hydra|das v2"
    r"|below 50% margin|margin below 50|sub-50% margin)",
    re.IGNORECASE,
)
_DISAVOW = re.compile(r"disavow", re.IGNORECASE)

_EMIT_TOOL = {
    "name": "emit_strategy_review",
    "description": (
        "Emit the final strategy review. Call this exactly once when your analysis is "
        "complete (after any drill-downs). This ENDS the run."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "assessment": {
                "type": "string",
                "description": "The one-paragraph strategic read of this client's whole search surface.",
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
            "proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "action": {"type": "string", "description": "What a human would do, concretely."},
                        "rationale": {"type": "string"},
                        "sop_citation": {"type": "string"},
                        "est_cost_usd": {"type": "number"},
                        "effort": {"type": "string", "enum": ["low", "medium", "high"]},
                        "assignee_hint": {
                            "type": "string",
                            "description": "Per the roles matrix (Kyle/Ryan/Minda/Ivy) or 'UNSTAFFED'.",
                        },
                        "requires": {"type": "string", "enum": ["none", "approval", "senior"]},
                    },
                    "required": ["title", "action", "rationale"],
                },
            },
            "questions": {
                "type": "array", "items": {"type": "string"},
                "description": "Halt-and-ask items: decisions no SOP owns, SOP conflicts, missing inputs.",
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
1. Cross-domain synthesis — signals that only mean something together (e.g. organic + maps \
declining + heavy off-topic content = vector confusion, not three separate problems).
2. Conflicting or unusual signal patterns the deterministic B1–B5 / playbook rules don't cover.
3. "The plan says X but the context suggests Y" — challenge the Recipe Engine / Action Plan \
when the evidence points elsewhere, with the evidence.
4. Escalation briefs — when a 6-week episode escalates, prepare the case file: what was \
tried, what moved, what you recommend the seniors decide.
Do NOT restate the Action Plan back — it's in your input. Add judgment, not inventory. An \
empty review is a valid review: if the deterministic layer already has it right, say so \
briefly and emit no proposals.

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

HOW TO READ THE INSTRUMENTS: module cards are included in your input — follow them exactly \
(they exist because the common failure is misreading, not mis-reasoning: average_rank without \
found_pins, a null GSC position read as a rank loss, one AI answer-flip read as a trend).

DRILL-DOWNS: you may call the provided read-only tools when the digest genuinely isn't \
enough — they are capped per run (the cap is in your input); the paid audit_page tighter \
still. Prefer emitting with what you have over burning drill-downs on curiosity.

When done, call emit_strategy_review exactly once."""


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
        if _DISAVOW.search(blob):
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
        est = p.get("est_cost_usd")
        proposals.append(
            {
                "title": title,
                "action": action,
                "rationale": (p.get("rationale") or "").strip(),
                "sop_citation": (p.get("sop_citation") or "").strip(),
                "est_cost_usd": float(est) if isinstance(est, (int, float)) else None,
                "effort": effort,
                "assignee_hint": (p.get("assignee_hint") or "").strip() or None,
                "status": "proposed",
                "requires": requires,
            }
        )

    if frozen and proposals:
        questions.append(
            f"[client frozen] {len(proposals)} proposal(s) withheld — a freeze pauses decide+output; "
            "this review is observation-only until the freeze lifts."
        )
        proposals = []

    return {
        "assessment": assessment,
        "findings": findings,
        "proposals": proposals,
        "questions": questions,
    }


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
) -> str:
    """Assemble the single user message for the run. Pure."""
    parts = [
        f"TRIGGER: {trigger}"
        + (" — prepare the escalation brief for the senior review (what was tried, what moved, "
           "what you recommend they decide)." if trigger == "escalation" else ""),
    ]
    if escalation_context:
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
    title = (
        f"Escalation brief ready: {client_name}"
        if trigger == "escalation"
        else f"Strategist review: {client_name} — {', '.join(bits)}"
    )
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
) -> dict:
    """Execute one strategist run and persist the strategy_reviews row.
    Returns the completed row. Raises on hard failure (caller marks the job)."""
    import anthropic

    from services import strategist_tools

    supabase = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
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
    digest_budget = max(20_000, total_chars - len(sops_text) - len(cards_text))
    digest_json = strategy_digest.render_digest(digest, digest_budget)

    max_dd = settings.strategist_max_drilldowns
    max_paid = settings.strategist_max_paid_drilldowns
    user = build_run_prompt(
        digest_json, sops_text, cards_text,
        trigger=trigger, frozen=frozen, max_drilldowns=max_dd, max_paid=max_paid,
        escalation_context=escalation_context,
    )

    tools = strategist_tools.anthropic_tool_defs() + [_EMIT_TOOL]
    api = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=_LLM_TIMEOUT)
    messages: list[dict] = [{"role": "user", "content": user}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    drilldowns: list[dict] = []
    paid_used = 0
    emitted: Optional[dict] = None

    # loop bound: every non-emit round consumes ≥1 drill-down, +2 slack rounds
    for round_no in range(max_dd + 3):
        force_emit = round_no >= max_dd + 1 or len(drilldowns) >= max_dd
        resp = await api.messages.create(
            model=settings.strategist_model,
            max_tokens=settings.strategist_max_tokens,
            system=_SYSTEM,
            tools=tools,
            tool_choice={"type": "tool", "name": "emit_strategy_review"} if force_emit else {"type": "auto"},
            messages=messages,
        )
        usage["input_tokens"] += getattr(resp.usage, "input_tokens", 0) or 0
        usage["output_tokens"] += getattr(resp.usage, "output_tokens", 0) or 0

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        emit_block = next((b for b in tool_uses if b.name == "emit_strategy_review"), None)
        if emit_block is not None:
            emitted = emit_block.input or {}
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

    # The stored input_digest is the structured digest (not the SOP text — that
    # would 5× the row for content already versioned in the repo).
    updated = (
        supabase.table("strategy_reviews")
        .update(
            {
                "status": "complete",
                "assessment": review_body["assessment"],
                "findings": review_body["findings"],
                "proposals": review_body["proposals"],
                "questions": review_body["questions"],
                "input_digest": digest,
                "token_usage": usage,
                "completed_at": now,
            }
        )
        .eq("id", review_id)
        .execute()
    ).data[0]

    # Digest notification (Slack rides the notifications service). Scheduled +
    # escalation runs only — an on-demand run means a human is already looking.
    if trigger in ("scheduled", "escalation"):
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
        },
    )
    return updated


# ─────────────────────────────────────────────────────────────────────────────
# Enqueue + job handler (async_jobs job_type='strategy_review')
# ─────────────────────────────────────────────────────────────────────────────
def enqueue_strategy_review(
    client_id: str,
    trigger: str = "on_demand",
    escalation_context: Optional[dict] = None,
) -> Optional[str]:
    """Create the strategy_reviews row (status=running, so the UI can show it
    immediately) and enqueue the job. Deduped against an in-flight run for the
    client. Returns the review id, or None when deduped/disabled."""
    if not settings.strategist_enabled:
        return None
    if trigger not in VALID_TRIGGERS:
        trigger = "on_demand"
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "strategy_review")
        .eq("entity_id", client_id)
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
    supabase.table("async_jobs").insert(
        {"job_type": "strategy_review", "entity_id": client_id, "payload": payload}
    ).execute()
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
