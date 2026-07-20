"""QA — the conversational reviewer persona (the /qa sidebar surface).

The quality-gate sibling of SerMaStr (`/assistant`, "are we winning?") and PACE
(`/pace`, "is the work getting done?"). QA answers **"is the work that got done
actually good?"** — it QAs a live page on demand, QAs a board task's deliverable,
and reports recent QA verdicts.

Positioning vs the QA agent plan: the plan deliberately did NOT spin up a third
conversational persona — it folded QA's one action into PACE. This surface adds a
*dedicated reviewer chat* (owner request, 2026-07-20) without disturbing that:

- **Scoped to its own /qa surface only.** Unlike PACE, QA is NOT wired into the
  shared Slack `handle_message` / `/assistant/chat` first-refusal chain — that
  would create a three-way routing contest. `routers/qa.py` calls
  ``maybe_handle_web(..., force=True)`` directly, so SerMaStr + PACE routing are
  byte-for-byte unchanged.
- **Reuses the existing rails.** `pace_auth` for the actor + actor-bound
  confirmation; `slack_assistant.llm._one_llm_call` for the Anthropic primitive;
  `qa_service` for the deterministic checks (both the bare-URL path and the
  existing task-review job). No new infra, no new auth model.

Two tools:
- ``qa_url`` — runs a bare-URL review inline (read-only; nothing on the board
  changes), returns the verdict. No confirm.
- ``run_qa_review`` — enqueues the full task review for a named board task; that
  review can bounce the task + open rework subtasks, so it's confirm-gated and
  actor-bound (only the requester can confirm).

Gated on ``qa_chat_enabled``; while off the router 503s and the sidebar entry is
hidden.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import pace_auth, qa_service
from services import qa_signals as sig
from services.pace_auth import ActionContext

logger = logging.getLogger(__name__)

# Web confirm store for the one confirm-gated action (task review). Mirrors
# PACE's best-effort _pace_web_pending: opaque token → staged entry, TTL-evicted.
_web_pending: dict[str, dict] = {}
_WEB_PENDING_TTL = 900.0
_WEB_PENDING_MAX = 500

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def first_url(text: Optional[str]) -> Optional[str]:
    """The first http(s) URL in a message, trailing punctuation stripped. Pure."""
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(".,;:!?)") if m else None


_VERDICT_LABEL = {
    sig.PASS: "✅ Pass", sig.FAIL: "❌ Fail",
    sig.NEEDS_HUMAN: "⚠️ Needs a human", sig.SKIPPED: "⏭️ Skipped",
}


def format_review(review: dict, subject: str) -> str:
    """Render a review payload (from ``qa_service.review_url`` or a persisted
    row) as a chat-friendly markdown summary. Pure."""
    verdict = review.get("verdict") or sig.NEEDS_HUMAN
    lines = [f"*{_VERDICT_LABEL.get(verdict, verdict)}* — {subject}"]
    composite = review.get("composite")
    if composite is not None:
        lines[0] += f"  ·  fidelity {float(composite):.0f}/100"
    checks = review.get("checks") or []
    failed = [c for c in checks if c.get("blocking") and c.get("ok") is False]
    unknown = [c for c in checks if c.get("blocking") and c.get("ok") is None]
    advisories = [c for c in checks if not c.get("blocking") and c.get("ok") is False]
    if failed:
        lines.append("\n*Blocking issues to fix:*")
        lines.extend(f"• {c.get('label')}" + (f" — {c['note']}" if c.get("note") else "") for c in failed)
    if unknown:
        lines.append("\n*Couldn't verify (needs a human):*")
        lines.extend(f"• {c.get('label')}" + (f" — {c['note']}" if c.get("note") else "") for c in unknown)
    if advisories:
        lines.append("\n*Advisory (non-blocking):*")
        lines.extend(f"• {c.get('label')}" + (f" — {c['note']}" if c.get("note") else "") for c in advisories)
    if verdict == sig.PASS and not (failed or unknown):
        oks = sum(1 for c in checks if c.get("ok") is True)
        lines.append(f"\nAll {oks} check(s) passed.")
    if review.get("narrative"):
        lines.append(f"\n{review['narrative']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Context (deterministic QA digests — the LLM's grounding, no LLM/paid calls)
# ---------------------------------------------------------------------------
def build_qa_context(client_id: str) -> dict:
    """Recent QA verdicts for one client (reuses the SerMaStr `_ctx_qa`
    provider so the numbers match). No paid calls."""
    from services.slack_assistant.context import _ctx_qa

    try:
        ctx = _ctx_qa(get_supabase(), client_id, date.today())
    except Exception as exc:
        logger.warning("qa_context_failed", extra={"client_id": client_id, "error": str(exc)})
        ctx = None
    return {"client_id": client_id, "recent_qa": ctx or "no QA reviews in the last 30 days"}


def build_qa_portfolio(today: Optional[date] = None) -> dict:
    """Whole-agency QA digest: reviews needing attention (fail / needs_human) in
    the last 30 days, newest first, with task + client names. No paid calls."""
    today = today or date.today()
    since = (today - timedelta(days=30)).isoformat()
    supabase = get_supabase()
    rows = (
        supabase.table("qa_reviews")
        .select("task_id, client_id, rubric, verdict, issues, created_at")
        .gte("created_at", since).order("created_at", desc=True).limit(200).execute()
    ).data or []
    # latest per task
    latest: dict[str, dict] = {}
    for r in rows:
        latest.setdefault(r["task_id"], r)
    reviews = list(latest.values())
    by_verdict: dict[str, int] = {}
    for r in reviews:
        by_verdict[r.get("verdict") or "unknown"] = by_verdict.get(r.get("verdict") or "unknown", 0) + 1
    attention = [r for r in reviews if r.get("verdict") in (sig.FAIL, sig.NEEDS_HUMAN)][:12]
    names = _task_names([r["task_id"] for r in attention])
    cnames = _client_names([r.get("client_id") for r in attention])
    return {
        "reviewed_tasks_30d": len(reviews),
        "by_verdict": by_verdict,
        "needs_attention": [
            {"task": names.get(r["task_id"]) or r["task_id"],
             "client": cnames.get(r.get("client_id"), "unknown"),
             "verdict": r.get("verdict"), "issues": (r.get("issues") or [])[:4]}
            for r in attention
        ],
    }


def _task_names(task_ids: list) -> dict:
    ids = sorted({t for t in task_ids if t})
    if not ids:
        return {}
    rows = (get_supabase().table("tasks").select("id, name").in_("id", ids).execute()).data or []
    return {r["id"]: r.get("name") for r in rows}


def _client_names(client_ids: list) -> dict:
    ids = sorted({c for c in client_ids if c})
    if not ids:
        return {}
    rows = (get_supabase().table("clients").select("id, name").in_("id", ids).execute()).data or []
    return {r["id"]: r.get("name") for r in rows}


def _all_clients() -> list[dict]:
    return (get_supabase().table("clients").select("id, name, website_url").execute()).data or []


# ---------------------------------------------------------------------------
# Deterministic brief (the /qa empty state — no LLM)
# ---------------------------------------------------------------------------
def brief_text() -> str:
    """Recent QA that needs attention across the agency, for the /qa page's empty
    state. Deterministic; no LLM, no paid call."""
    try:
        digest = build_qa_portfolio()
    except Exception as exc:
        logger.warning("qa_brief_failed", extra={"error": str(exc)})
        return ""
    attention = digest.get("needs_attention") or []
    if not attention:
        n = digest.get("reviewed_tasks_30d") or 0
        return (f"No QA failures in the last 30 days — {n} deliverable(s) reviewed clean. 🎉"
                if n else "No QA reviews yet. Paste a page URL and I'll QA it, or name a board task.")
    lines = ["*Needs attention (last 30 days):*"]
    for r in attention[:8]:
        v = "failed" if r["verdict"] == sig.FAIL else "needs a human"
        issue = f" — {r['issues'][0]}" if r.get("issues") else ""
        lines.append(f"• {r['task']} ({r['client']}) — {v}{issue}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM tools + system prompt
# ---------------------------------------------------------------------------
_QA_TOOLS = [
    {
        "name": "qa_url",
        "description": "QA a live page by URL — runs the real deterministic checks and returns a verdict. Read-only; nothing on the board changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The page URL to QA."},
                "page_kind": {"type": "string", "description": "What kind of page: 'page' (website/landing/service/location), 'guest post', 'niche edit', 'press release', 'citation', or 'map embed'. Defaults to a website page."},
            },
            "required": ["url"],
        },
    },
    {
        "name": "run_qa_review",
        "description": "QA a board task's deliverable — runs the full task review, which can bounce the task and open rework subtasks. Confirm-gated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_name": {"type": "string", "description": "The task whose deliverable to QA (part of its name)."},
            },
            "required": ["task_name"],
        },
    },
]

_QA_SYSTEM = (
    "You are QA, the quality reviewer for an SEO agency — the gate between "
    "\"a VA marked it done\" and \"it goes to the client.\" You judge deliverables "
    "against the agency's QA checklists; you never invent a standard.\n\n"
    "WHAT YOU DO:\n"
    "• QA a live page on demand. When the teammate gives you a URL (or says \"QA "
    "this page / guest post / citation / press release / map embed\"), call "
    "`qa_url` with the URL and the page kind. It runs the real deterministic "
    "checks (meta, internal link, NAP, assets, rendered screenshot) and returns a "
    "verdict — read-only, nothing on the board changes.\n"
    "• QA a board task's deliverable. When they name a task (\"QA the Inner West "
    "page\"), call `run_qa_review` — this runs the full review and can bounce the "
    "task with rework items, so the system asks for a confirmation first. Don't "
    "ask permission before calling the tool; the confirm step IS the permission.\n"
    "• Report recent QA. Answer \"how did QA go on X\", \"what failed QA\" from the "
    "QA data you're given — LIST the actual tasks, their verdict, and the open "
    "issues. Never re-judge a deliverable yourself; cite the recorded verdict.\n\n"
    "VOICE: concrete, first-pass reviewer. State the verdict plainly (pass / fail "
    "/ needs a human), then the blocking issues to fix, then offer the next step. "
    "Don't hedge and don't soften a fail.\n\n"
    "GROUNDING: only state verdicts, tasks, and issues present in the data or "
    "returned by a check you ran. The pass/fail is computed deterministically — "
    "you phrase it, you never change it.\n\n"
    "NOT THE STRATEGIST OR THE PM: campaign strategy is SerMaStr's; chasing rework "
    "and moving board work is PACE's. If asked those, say so and offer the handoff "
    "— but judging whether a deliverable is good is yours."
)

_QA_TOOL_ROUNDS = 2


async def interpret_qa(question: str, client: Optional[dict], context: dict,
                       history: Optional[list[dict]] = None, on_event=None,
                       scope: str = "portfolio") -> tuple[str, object]:
    """One QA turn over a bounded tool loop. Returns ("url", args) for a bare-URL
    review, ("task_review", args) for a task review, else ("text", reply).
    Sonnet (`qa_chat_model`)."""
    import json

    import anthropic

    from services.slack_assistant.llm import _one_llm_call, format_history

    blocks = []
    if history:
        blocks.append("Conversation so far:\n" + format_history(history))
    if scope == "client":
        blocks.append(f"Scope: the client *{client.get('name') if client else 'this client'}*.")
    else:
        blocks.append("Scope: the whole agency (every client's QA reviews).")
    blocks.append("QA data (JSON):\n" + json.dumps(context, default=str, ensure_ascii=False))
    blocks.append(f"Latest message: {question}")
    api = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=60.0, max_retries=2)
    messages = [{"role": "user", "content": "\n\n".join(blocks)}]

    async def on_text(delta: str) -> None:
        await on_event({"type": "text", "text": delta})

    def _kw(final: bool) -> dict:
        kw = {"model": settings.qa_chat_model, "max_tokens": settings.qa_chat_max_tokens}
        if final:
            kw["tool_choice"] = {"type": "none"}
        return kw

    resp = None
    try:
        for round_no in range(_QA_TOOL_ROUNDS):
            final = round_no == _QA_TOOL_ROUNDS - 1
            resp = await _one_llm_call(
                api, _QA_SYSTEM, messages, [] if final else _QA_TOOLS,
                _kw(final), on_text if on_event else None,
            )
            for b in resp.content:
                if getattr(b, "type", None) != "tool_use":
                    continue
                if b.name == "qa_url":
                    return ("url", dict(b.input or {}))
                if b.name == "run_qa_review":
                    return ("task_review", dict(b.input or {}))
            break
    except anthropic.APIStatusError as exc:
        if exc.status_code in (429, 529, 503):
            return ("text", "QA is busy right now — try again in a moment.")
        raise

    parts = [b.text for b in (resp.content if resp else []) if getattr(b, "type", None) == "text"]
    return ("text", "\n".join(parts).strip() or "I couldn't work that out — try rephrasing.")


# ---------------------------------------------------------------------------
# Scope + turn resolution
# ---------------------------------------------------------------------------
def _resolve_scope(question: str, sticky_client_id: Optional[str]) -> tuple[str, Optional[dict], dict]:
    """client (named / sticky) → its recent QA; else the whole-agency portfolio.
    Blocking DB reads — call via a runner."""
    from services.slack_assistant import resolve_client

    clients = _all_clients()
    named = resolve_client(question, clients)
    if named:
        return "client", named, build_qa_context(named["id"])
    if sticky_client_id:
        sticky = next((c for c in clients if c["id"] == sticky_client_id), None)
        if sticky:
            return "client", sticky, build_qa_context(sticky["id"])
    return "portfolio", None, build_qa_portfolio()


def _resolve_task(task_name: str) -> tuple[Optional[dict], Optional[str]]:
    """Resolve a named open task across every board → ({id, name, client_id}, None)
    or (None, reply) on no-match / ambiguity spanning clients."""
    from services.slack_assistant.actions import match_open_tasks

    query = (task_name or "").strip()
    if not query:
        return None, "Which task? Give me (part of) its name."
    rows = (
        get_supabase().table("tasks").select("id, name, client_id")
        .eq("completed", False).is_("deleted_at", "null").is_("parent_task_id", "null")
        .execute()
    ).data or []
    matches = match_open_tasks(rows, query)
    if not matches:
        return None, f"No open task matches “{query}”."
    if len({m.get("client_id") for m in matches}) > 1:
        cnames = _client_names([m.get("client_id") for m in matches])
        which = ", ".join(sorted(cnames.get(cid, "unknown") for cid in {m.get("client_id") for m in matches}))
        return None, f"“{query}” matches tasks on more than one client ({which}) — which client?"
    return matches[0], None


def _client_row(client_id: Optional[str]) -> Optional[dict]:
    if not client_id:
        return None
    rows = (
        get_supabase().table("clients")
        .select("id, name, website_url, gbp, page_structures")
        .eq("id", client_id).limit(1).execute()
    ).data
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Web entry (the /qa surface — force=True, never returns None)
# ---------------------------------------------------------------------------
def _store_web_pending(task: dict, requester: Optional[str]) -> str:
    import uuid

    now = time.time()
    for tok, e in list(_web_pending.items()):
        if now - e["created"] > _WEB_PENDING_TTL:
            _web_pending.pop(tok, None)
    while len(_web_pending) >= _WEB_PENDING_MAX:
        _web_pending.pop(min(_web_pending, key=lambda t: _web_pending[t]["created"]), None)
    token = uuid.uuid4().hex
    _web_pending[token] = {"task_id": task["id"], "task_name": task.get("name"),
                           "client_id": task.get("client_id"), "requester": requester, "created": now}
    return token


async def maybe_handle_web(message: str, history: list[dict], sticky_client_id: Optional[str],
                           pending_token: Optional[str], actor: ActionContext,
                           on_event=None, force: bool = True) -> dict:
    """One QA web-chat turn. `force` is always True on the dedicated /qa surface
    (QA answers every turn), so this never returns None. Reads that block on
    Supabase I/O are pushed to a threadpool to keep the request loop free."""
    from fastapi.concurrency import run_in_threadpool

    from services.slack_assistant import is_affirmative

    # 1) Confirm a staged task review (actor-bound).
    if pending_token and pending_token in _web_pending:
        entry = _web_pending.pop(pending_token)
        if is_affirmative(message):
            if not pace_auth.confirm_actor_ok(entry.get("requester"), actor):
                return {"reply": "Only the person who requested this can confirm it."}
            try:
                job_id = await run_in_threadpool(
                    qa_service.enqueue_qa_review, entry["task_id"], trigger="manual"
                )
            except Exception as exc:
                logger.warning("qa_enqueue_failed", extra={"task_id": entry["task_id"], "error": str(exc)})
                job_id = None
            reply = (f"Running QA on *{entry.get('task_name')}* now — the verdict lands on the task's "
                     "QA panel, and I'll flag it here if it fails."
                     if job_id else "Sorry — I couldn't start that review. Try again.")
            base = {"reply": reply}
            if entry.get("client_id"):
                base["client_id"] = entry["client_id"]
            return base
        # Non-affirmative supersedes; fall through to normal handling.

    try:
        scope, subject, ctx = await run_in_threadpool(_resolve_scope, message, sticky_client_id)
        client = subject if scope == "client" else None
        base = {"client_id": client["id"], "client_name": client.get("name")} if client else {}

        kind, payload = await interpret_qa(message, client, ctx, history, on_event, scope=scope)

        if kind == "text":
            return {**base, "reply": payload}

        if kind == "url":
            url = qa_service_first_url(payload.get("url"), message)
            if not url:
                return {**base, "reply": "Give me the full page URL (starting with http) and I'll QA it."}
            rubric = qa_service.resolve_url_rubric(payload.get("page_kind"))
            if on_event:
                await on_event({"type": "status", "label": "Fetching and checking the page"})
            client_row = client or await run_in_threadpool(_client_row, sticky_client_id)
            review = await qa_service.review_url(url, client_row, rubric)
            return {**base, "reply": format_review(review, url)}

        # A task review — resolve, then confirm-gate (actor-bound).
        task, reply = await run_in_threadpool(_resolve_task, payload.get("task_name", ""))
        if reply:
            return {**base, "reply": reply}
        token = _store_web_pending(task, actor.profile_id)
        cname = _client_names([task.get("client_id")]).get(task.get("client_id"), "the client")
        out = {"reply": f"This will run a full QA review on *{task.get('name')}* for **{cname}** — it can "
                        "bounce the task and open rework items. Confirm to proceed.",
               "pending_token": token}
        if task.get("client_id"):
            out["client_id"] = task["client_id"]
            out["client_name"] = cname
        return out
    except Exception as exc:
        logger.warning("qa_web_failed", extra={"error": str(exc)})
        return {"reply": "Sorry — QA hit an error. Try again in a moment."}


def qa_service_first_url(tool_url: Optional[str], message: str) -> Optional[str]:
    """Prefer the URL the model passed; fall back to the first URL in the raw
    message (the model occasionally paraphrases the link). Pure."""
    cand = (tool_url or "").strip()
    if cand.lower().startswith(("http://", "https://")):
        return cand.rstrip(".,;:!?)")
    return first_url(message)
