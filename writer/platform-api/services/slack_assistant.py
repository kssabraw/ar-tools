"""Slack conversational assistant — "SerMastr".

Two-way Slack: when someone @mentions the bot in a channel, Slack POSTs an
`app_mention` event to `/slack/events`. We resolve which client the question is
about, assemble a compact context from the rank tracker's data (current ranks +
status, open drops, the latest Action Plan, GSC opportunities), ask Claude, and
post the answer back **in-thread**.

Read-only Q&A — the assistant only reads and explains; it never triggers work
(that's a later, carefully-authed step). Anyone in the workspace can ask
(per the product decision); inbound requests are verified by Slack's request
signature so the public endpoint can't be spoofed.

Split: pure helpers (signature verify, mention stripping, client resolution) are
import-light and unit-tested; the context build + Claude call + Slack post do I/O.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from datetime import date
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
_TIMEOUT = 20.0
_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
_SIG_MAX_SKEW_SECONDS = 60 * 5  # reject events older than 5 min (replay guard)

_SYSTEM = (
    "You are SerMastr, an in-house SEO strategist for an agency, answering a "
    "teammate in Slack. You are given structured data about ONE client's search "
    "performance (tracked keywords with current rank and trend, open ranking-drop "
    "alerts, the latest reoptimization Action Plan, and Search Console "
    "opportunities). Answer the question using ONLY that data. Be concise and "
    "direct — a few sentences or a short list, Slack-friendly (you may use *bold* "
    "and bullet points). Lead with the answer. If the data doesn't cover the "
    "question, say so plainly and suggest what to open in AR Tools. Never invent "
    "numbers."
)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — unit-tested.
# ---------------------------------------------------------------------------
def verify_slack_signature(
    signing_secret: str, timestamp: str, raw_body: str, signature: str, now_ts: int
) -> bool:
    """True iff the Slack request signature is valid and recent. Pure.

    Slack signs `v0:{timestamp}:{body}` with HMAC-SHA256 over the signing secret.
    Fail-closed: a missing secret/signature/timestamp, a stale timestamp (replay),
    or any parse error returns False.
    """
    if not (signing_secret and timestamp and signature):
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(now_ts - ts) > _SIG_MAX_SKEW_SECONDS:
        return False
    basestring = f"v0:{timestamp}:{raw_body}".encode()
    expected = "v0=" + hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def strip_mention(text: str) -> str:
    """Remove Slack user mentions (`<@U123>`) and collapse whitespace. Pure."""
    return _MENTION_RE.sub("", text or "").strip()


def resolve_client(message: str, clients: list[dict]) -> Optional[dict]:
    """Pick the client a message is about by matching client names. Pure.

    Prefers the longest client name that appears as a whole-word substring of the
    message (so "Acme Plumbing" wins over "Acme" when both exist). Falls back to a
    token-overlap match (any distinctive name word present). Returns None when
    nothing matches — the caller then asks the user to name the client.
    """
    msg = (message or "").lower()
    if not msg:
        return None
    # 1) Whole-name substring, longest name first.
    named = sorted(
        (c for c in clients if (c.get("name") or "").strip()),
        key=lambda c: len(c["name"]),
        reverse=True,
    )
    for c in named:
        name = c["name"].lower()
        if re.search(rf"\b{re.escape(name)}\b", msg):
            return c
    # 2) Distinctive-token overlap (ignore generic words).
    stop = {"the", "and", "of", "for", "co", "inc", "llc", "ltd", "group", "services", "service"}
    best, best_hits = None, 0
    for c in named:
        tokens = {t for t in re.split(r"\W+", c["name"].lower()) if len(t) > 2 and t not in stop}
        hits = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", msg))
        if hits > best_hits:
            best, best_hits = c, hits
    return best if best_hits else None


def format_context(client: dict, context: dict) -> str:
    """Compact JSON-ish context block for the LLM prompt. Pure."""
    payload = {
        "client": {"name": client.get("name"), "website": client.get("website_url")},
        **context,
    }
    return json.dumps(payload, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Context assembly (DB reads).
# ---------------------------------------------------------------------------
def build_context(client_id: str, today: Optional[date] = None) -> dict:
    """Gather the client's current rank picture for the assistant. Best-effort —
    a failing section is omitted, never fatal."""
    from services import rank_status

    supabase = get_supabase()
    today = today or date.today()
    ctx: dict = {}

    try:
        kws = (
            supabase.table("tracked_keywords")
            .select("id, keyword, status")
            .eq("client_id", client_id)
            .eq("active", True)
            .order("keyword")
            .limit(settings.slack_assistant_max_keywords)
            .execute()
        ).data or []
        kw_ids = [k["id"] for k in kws]
        metrics: dict[str, list[dict]] = {}
        if kw_ids:
            cutoff = date.fromordinal(today.toordinal() - 90).isoformat()
            for r in (
                supabase.table("rank_keyword_metrics")
                .select("keyword_id, date, gsc_position, tracked_rank")
                .in_("keyword_id", kw_ids)
                .gte("date", cutoff)
                .execute()
            ).data or []:
                metrics.setdefault(r["keyword_id"], []).append(r)
        keywords = []
        for k in kws:
            s = rank_status.compute_keyword_summary(
                metrics.get(k["id"], []), today, settings.rank_gsc_coverage_days
            )
            keywords.append(
                {
                    "keyword": k["keyword"],
                    "status": k.get("status"),
                    "current_rank": s.get("today_rank"),
                    "avg_30d": s.get("avg_30"),
                    "direction": s.get("direction"),
                }
            )
        ctx["keywords"] = keywords
        ctx["keyword_count"] = len(keywords)
    except Exception as exc:
        logger.warning("slack_ctx_keywords_failed", extra={"client_id": client_id, "error": str(exc)})

    try:
        alerts = (
            supabase.table("rank_alerts")
            .select("keyword, alert_type, message")
            .eq("client_id", client_id)
            .is_("resolved_at", "null")
            .execute()
        ).data or []
        ctx["open_drop_alerts"] = alerts
    except Exception as exc:
        logger.warning("slack_ctx_alerts_failed", extra={"client_id": client_id, "error": str(exc)})

    try:
        plan = (
            supabase.table("reopt_plans")
            .select("summary, items, action_count, created_at")
            .eq("client_id", client_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data
        if plan:
            p = plan[0]
            items = p.get("items") or []
            ctx["action_plan"] = {
                "summary": p.get("summary"),
                "action_count": p.get("action_count"),
                "top_actions": [
                    {"keyword": a.get("keyword"), "recommendation": a.get("recommendation")}
                    for a in items[:8]
                ],
            }
    except Exception as exc:
        logger.warning("slack_ctx_plan_failed", extra={"client_id": client_id, "error": str(exc)})

    try:
        gsc = (
            supabase.table("gsc_research_runs")
            .select("cannibalization, hidden_wins, quick_wins, created_at")
            .eq("client_id", client_id)
            .eq("status", "complete")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data
        if gsc:
            g = gsc[0]
            ctx["gsc_opportunities"] = {
                "cannibalization": len(g.get("cannibalization") or []),
                "quick_wins": len(g.get("quick_wins") or []),
                "hidden_wins": len(g.get("hidden_wins") or []),
            }
    except Exception as exc:
        logger.warning("slack_ctx_gsc_failed", extra={"client_id": client_id, "error": str(exc)})

    return ctx


# ---------------------------------------------------------------------------
# Claude + Slack I/O.
# ---------------------------------------------------------------------------
async def answer_question(question: str, client: dict, context: dict) -> str:
    """Ask Claude the question against the assembled context. Returns reply text."""
    import anthropic

    user = f"Question: {question}\n\nClient data (JSON):\n{format_context(client, context)}"
    api = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    resp = await api.messages.create(
        model=settings.slack_assistant_model,
        max_tokens=settings.slack_assistant_max_tokens,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip() or "I couldn't generate an answer just now — try rephrasing."


async def post_message(channel: str, text: str, thread_ts: Optional[str] = None) -> None:
    """Post a message to a channel (optionally threaded) via chat.postMessage."""
    body: dict = {"channel": channel, "text": text, "mrkdwn": True}
    if thread_ts:
        body["thread_ts"] = thread_ts
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            _SLACK_POST_URL,
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"slack_error: {data.get('error')}")


async def handle_app_mention(event: dict) -> None:
    """Process one app_mention event end-to-end. Best-effort; logs and bails on error."""
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    question = strip_mention(event.get("text", ""))
    if not channel:
        return
    try:
        if not question:
            await post_message(
                channel,
                "Hi, I'm SerMastr 👋 Ask me about a client's rankings — e.g. "
                "“how is *Acme Plumbing* doing?” or “any drops for *Acme*?”",
                thread_ts,
            )
            return

        supabase = get_supabase()
        clients = (
            supabase.table("clients").select("id, name, website_url").execute()
        ).data or []
        client = resolve_client(question, clients)
        if not client:
            names = ", ".join(c["name"] for c in clients[:8] if c.get("name"))
            await post_message(
                channel,
                "I'm not sure which client you mean — name them in your question. "
                + (f"For example: {names}." if names else ""),
                thread_ts,
            )
            return

        context = build_context(client["id"])
        answer = await answer_question(question, client, context)
        await post_message(channel, answer, thread_ts)
    except Exception as exc:
        logger.warning("slack_assistant_failed", extra={"channel": channel, "error": str(exc)})
        try:
            await post_message(channel, "Sorry — I hit an error answering that.", thread_ts)
        except Exception:
            pass
