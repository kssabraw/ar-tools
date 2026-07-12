"""Claude + Slack I/O — the interpret loop (tools, SOP grounding, streaming),
the live-data tools (fetch_live_gsc), and end-to-end message handling.

Part of the `services.slack_assistant` package; see its docstring for the
full picture."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase
from services.slack_assistant.actions import _ACTION_TOOLS, _ACTIONS, _pending
from services.slack_assistant.context import (
    _MEMORY_TOOL,
    _run_remember,
    build_context,
    build_portfolio_context,
)
from services.slack_assistant.helpers import (
    format_context,
    format_history,
    is_affirmative,
    resolve_client,
    sop_domains,
    strip_mention,
    wants_sop_grounding,
)
from services.slack_assistant.prompts import _PORTFOLIO_SYSTEM, _SYSTEM, _WEB_STYLE

logger = logging.getLogger(__name__)

_SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
_SLACK_REPLIES_URL = "https://slack.com/api/conversations.replies"
_TIMEOUT = 20.0
_LLM_TIMEOUT = 120.0  # bound the Claude call (server-side web search lengthens turns)
_PAUSE_TURN_CONTINUATIONS = 3  # max re-sends when server-side search pauses the turn
# The SDK default (2 retries, ~2s total backoff) can't outlast a burst of
# long-running background LLM jobs (maps reports, strategist runs) holding the
# account's concurrent-connection budget — an interactive turn should back off
# and wait rather than surface an error.
_LLM_MAX_RETRIES = 5
_BUSY_REPLY = (
    "I'm briefly at capacity — several background AI jobs are running right now. "
    "Give it a minute and ask me again."
)
_CAPACITY_STATUS_CODES = (429, 529)  # rate-limited / API overloaded
_THREAD_HISTORY_LIMIT = 12  # prior thread messages folded into context for continuity


def _read_sop_tool() -> dict:
    """The read_sop tool definition, with the live doc catalog in the description
    so the model knows what exists (docs are static per deploy)."""
    from services import sop_library

    docs = ", ".join(sorted(sop_library.load_sop_docs())) or "none available"
    return {
        "name": "read_sop",
        "description": (
            "Fetch one agency SOP doc (or one section of it) to ground a strategy/"
            "process answer. Use this whenever the question touches strategy, plans, "
            "forecasts, budgets, drops, links, GBP/Maps, AI visibility or on-page "
            "work and the SOP LIBRARY block doesn't already cover it. Available "
            f"docs: {docs}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doc": {"type": "string", "description": "SOP filename (or a distinctive part of it)."},
                "section": {"type": "string", "description": "Optional heading substring to fetch just one section."},
            },
            "required": ["doc"],
        },
    }


# ---------------------------------------------------------------------------
# Live-data tools — answer-time reads, distinct from actions. fetch_live_gsc is
# free (Search Console API), so Claude may call it mid-answer with no confirm;
# paid live reads (DataForSEO) stay confirm-gated actions (`check_live_serp`).
# ---------------------------------------------------------------------------
_LIVE_GSC_ROUNDS = 2  # tool-use rounds before the answer is forced from what's fetched
_LIVE_GSC_TOP = 15  # rows surfaced per pull
_LIVE_GSC_RESULT_CHARS = 4000

_LIVE_GSC_TOOL = {
    "name": "fetch_live_gsc",
    "description": (
        "Pull LIVE Google Search Console data for this client's verified property "
        "(free — no confirmation needed). Use for current/latest search performance: "
        "top queries or pages by clicks/impressions, a specific keyword's or page's "
        "numbers, or daily totals. Fresher than the stored context (which is a daily "
        "ingest). Returns window totals plus the top rows."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dimension": {
                "type": "string",
                "enum": ["query", "page", "date"],
                "description": "Group rows by search query, by page URL, or by day.",
            },
            "days": {
                "type": "integer",
                "description": "Lookback window in days (default 28, max 180).",
            },
            "search": {
                "type": "string",
                "description": "Optional case-insensitive substring filter on the dimension value (a keyword or URL fragment).",
            },
        },
        "required": ["dimension"],
    },
}


async def _run_live_gsc(client_id: str, args: dict) -> str:
    """Execute one live Search Console pull; returns a JSON summary string.

    Errors return an explanatory string (never raise) so Claude can tell the
    teammate why live data isn't available."""
    import asyncio

    from services import gsc_service, rank_materialize

    if not gsc_service.is_configured():
        return "Live GSC unavailable: the agency service-account key is not configured."
    prop = rank_materialize._verified_property(get_supabase(), client_id)
    if not prop:
        return (
            "Live GSC unavailable: no verified Search Console property for this "
            "client — connect one on the Rankings page."
        )
    dim = args.get("dimension") or "query"
    if dim not in ("query", "page", "date"):
        dim = "query"
    days = max(1, min(int(args.get("days") or 28), 180))
    end = date.today() - timedelta(days=2)  # GSC data lags ~2 days
    start = end - timedelta(days=days)
    try:
        rows = await asyncio.to_thread(
            gsc_service.fetch_search_analytics,
            prop["site_url"], [dim], start.isoformat(), end.isoformat(),
        )
    except Exception as exc:
        return f"Live GSC pull failed: {exc}"
    needle = (args.get("search") or "").strip().lower()
    if needle:
        rows = [r for r in rows if needle in str((r.get("keys") or [""])[0]).lower()]
    clicks = sum(int(r.get("clicks") or 0) for r in rows)
    impressions = sum(int(r.get("impressions") or 0) for r in rows)
    pos_num = sum(float(r.get("position") or 0) * int(r.get("impressions") or 0) for r in rows)
    top = sorted(rows, key=lambda r: (r.get("clicks") or 0, r.get("impressions") or 0), reverse=True)
    if dim == "date":
        top = sorted(rows, key=lambda r: (r.get("keys") or [""])[0])
    payload = {
        "property": prop["site_url"],
        "window": {"start": start.isoformat(), "end": end.isoformat(), "note": "GSC data lags ~2 days"},
        "dimension": dim,
        "filter": needle or None,
        "totals": {
            "rows": len(rows),
            "clicks": clicks,
            "impressions": impressions,
            "avg_position": round(pos_num / impressions, 1) if impressions else None,
        },
        "top_rows": [
            {
                dim: (r.get("keys") or [""])[0],
                "clicks": r.get("clicks"),
                "impressions": r.get("impressions"),
                "ctr": round(float(r.get("ctr") or 0), 4),
                "position": round(float(r.get("position") or 0), 1),
            }
            for r in top[:_LIVE_GSC_TOP]
        ],
    }
    return json.dumps(payload, default=str)[:_LIVE_GSC_RESULT_CHARS]


# ---------------------------------------------------------------------------
# Non-indexed pages — inspect the client's known pages via the GSC URL
# Inspection API and report those Google hasn't indexed, each with its reason.
# GSC exposes NO bulk index-coverage API (the Page Indexing report is UI-only),
# so we discover the client's pages from its sitemap and inspect each one — a
# bounded, one-call-per-URL sweep. Free (Search Console API), so no confirm.
# ---------------------------------------------------------------------------
_NONINDEXED_DEFAULT = 40   # URLs inspected per call when the model doesn't specify
_NONINDEXED_MAX = 80       # hard cap (URL Inspection quota + latency bound)
_NONINDEXED_CONCURRENCY = 5
_NONINDEXED_RESULT_CHARS = 6000

_LIST_NONINDEXED_TOOL = {
    "name": "list_nonindexed_pages",
    "description": (
        "List this client's pages that Google has NOT indexed, each with the "
        "reason from Search Console (the coverageState — e.g. 'Crawled - currently "
        "not indexed', 'Discovered - currently not indexed', 'Page with redirect', "
        "'Duplicate, Google chose different canonical than user', 'Excluded by "
        "noindex tag', 'URL is unknown to Google'). Free — no confirmation. "
        "Discovers the client's pages from its sitemap and runs GSC URL Inspection "
        "on each. Bounded: GSC has no bulk index-coverage API, so it inspects up to "
        f"{_NONINDEXED_MAX} URLs per call and reports how many it checked and "
        "whether the list was truncated. Use for questions like 'which pages aren't "
        "indexed and why', 'is anything deindexed', or 'why isn't <page> indexed'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "search": {
                "type": "string",
                "description": "Optional case-insensitive URL substring to inspect a subset (e.g. '/blog/' or a specific slug).",
            },
            "limit": {
                "type": "integer",
                "description": f"Max pages to inspect (default {_NONINDEXED_DEFAULT}, hard max {_NONINDEXED_MAX}).",
            },
        },
    },
}


async def _run_list_nonindexed(client_id: str, args: dict) -> str:
    """Inspect the client's sitemap pages and return the non-indexed ones with
    their GSC coverage reason. Returns a JSON summary string; errors return an
    explanatory string (never raises) so Claude can explain the gap."""
    from services import gsc_service, rank_materialize, site_page_index
    from services.dataforseo_rank import extract_domain, location_code_for

    if not gsc_service.is_configured():
        return "Non-indexed check unavailable: the agency Search Console service-account key is not configured."
    supabase = get_supabase()
    prop = rank_materialize._verified_property(supabase, client_id)
    if not prop:
        return (
            "Non-indexed check unavailable: no verified Search Console property for "
            "this client — connect one on the Rankings page. (URL Inspection needs a "
            "verified property.)"
        )
    try:
        rows = (
            supabase.table("clients").select("*").eq("id", client_id).limit(1).execute()
        ).data or []
    except Exception as exc:
        return f"Non-indexed check failed reading the client: {exc}"
    client_row = rows[0] if rows else {}
    website = (client_row.get("website_url") or "").strip()
    if not website:
        return "No website on file for this client, so there are no pages to inspect."

    location_code = location_code_for(client_row)
    try:
        urls, source = await site_page_index.discover_site_urls(website, location_code)
    except Exception as exc:
        return f"Non-indexed check failed discovering pages: {exc}"
    if not urls:
        return (
            f"Couldn't discover any pages for {extract_domain(website) or website} "
            "(no readable sitemap and no indexed-URL fallback), so there's nothing to inspect."
        )

    needle = (args.get("search") or "").strip().lower()
    if needle:
        urls = [u for u in urls if needle in u.lower()]
        if not urls:
            return f"No discovered pages matched the filter '{needle}'."
    cap = max(1, min(int(args.get("limit") or _NONINDEXED_DEFAULT), _NONINDEXED_MAX))
    to_inspect = urls[:cap]
    truncated = len(urls) > cap

    site_url = prop["site_url"]
    sem = asyncio.Semaphore(_NONINDEXED_CONCURRENCY)

    async def _inspect(u: str) -> tuple:
        async with sem:
            try:
                r = await asyncio.to_thread(gsc_service.inspect_url, site_url, u)
                return (u, r.get("verdict"), r.get("coverage_state"), None)
            except Exception as exc:  # one bad URL never sinks the sweep
                return (u, None, None, str(exc)[:120])

    results = await asyncio.gather(*[_inspect(u) for u in to_inspect])
    nonindexed = [
        {"url": u, "verdict": v, "reason": cov or "unknown"}
        for (u, v, cov, err) in results
        if err is None and v != "PASS"
    ]
    errors = [{"url": u, "error": err} for (u, v, cov, err) in results if err]
    payload = {
        "property": site_url,
        "website": website,
        "url_source": source,  # "sitemap" | "google_index"
        "discovered": len(urls),
        "inspected": len(to_inspect),
        "truncated": truncated,
        "filter": needle or None,
        "indexed_count": sum(1 for (_u, v, _c, err) in results if err is None and v == "PASS"),
        "nonindexed_count": len(nonindexed),
        "nonindexed": nonindexed,
        "inspection_errors": errors[:5] or None,
        "note": (
            "GSC has no bulk index-coverage API — this inspects sitemap-discovered URLs "
            "one at a time via URL Inspection, so coverage is bounded by the inspect cap. "
            "'reason' is Google's coverageState; benign states (redirect / duplicate / "
            "alternate canonical) mean the page is on Google under a different URL, not lost."
        ),
    }
    return json.dumps(payload, default=str)[:_NONINDEXED_RESULT_CHARS]


def build_llm_tools() -> list[dict]:
    """The tool list for the assistant's Claude call.

    Action tools always; plus Anthropic's server-side web_search tool when
    enabled — it runs on Anthropic's infrastructure inside the same request
    (no client-side loop), giving SerMastr internet access for public info
    (third-party reviews, competitor sites, industry news). `max_uses` bounds
    the per-question search spend. The `_20260209` tool type requires a 4.6+
    model — the default `slack_assistant_model` qualifies.
    """
    tools: list[dict] = list(_ACTION_TOOLS)
    if settings.slack_assistant_web_search_enabled:
        tools.append(
            {
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": settings.slack_assistant_web_search_max_uses,
            }
        )
    return tools


async def _one_llm_call(
    api, system: str, messages: list[dict], tools: list[dict],
    kwargs: dict, on_text=None,
):
    """One messages call — plain create, or a token stream when `on_text` is set.

    `on_text` (an async callable taking a text delta) receives the answer as it
    generates — the dashboard chat's SSE path. The returned message is the same
    final object either way, so callers are stream-agnostic."""
    call_kwargs = {
        "model": settings.slack_assistant_model,
        "max_tokens": settings.slack_assistant_max_tokens,
        "system": system,
        "messages": messages,
        **({"tools": tools} if tools else {}),
        **kwargs,
    }
    if on_text is None:
        return await api.messages.create(**call_kwargs)
    async with api.messages.stream(**call_kwargs) as stream:
        async for delta in stream.text_stream:
            await on_text(delta)
        return await stream.get_final_message()


async def _create_with_continuation(
    api, system: str, messages: list[dict], tools: list[dict],
    tool_choice: Optional[dict] = None, on_text=None,
):
    """messages call with bounded `pause_turn` continuation.

    A server-side web-search loop can pause a long turn (`stop_reason ==
    "pause_turn"`); re-sending the conversation with the assistant content
    appended resumes it server-side. Interim paused assistant turns are
    appended to `messages` IN PLACE so an outer tool-round loop (read_sop /
    fetch_live_gsc) keeps a consistent history. Bounded so a pathological
    turn can't spin forever — on exhaustion the last response is used as-is."""
    kwargs = {"tool_choice": tool_choice} if tool_choice else {}
    resp = await _one_llm_call(api, system, messages, tools, kwargs, on_text)
    for _ in range(_PAUSE_TURN_CONTINUATIONS):
        if getattr(resp, "stop_reason", None) != "pause_turn":
            break
        messages.append({"role": "assistant", "content": resp.content})
        resp = await _one_llm_call(api, system, messages, tools, kwargs, on_text)
    return resp


def extract_interpretation(content: list) -> tuple[str, object]:
    """Map a Claude response's content blocks to (kind, payload). Pure.

    An ACTION tool call (type "tool_use", name in the registry) wins; server
    tool blocks (`server_tool_use`/`web_search_tool_result` — type differs)
    never match, so a searched answer still lands as text. Text blocks are
    joined (a search turn may interleave several around the tool results)."""
    for b in content:
        if getattr(b, "type", None) == "tool_use" and b.name in _ACTIONS:
            return ("action", {"name": b.name, "args": dict(b.input or {})})
    parts = [b.text for b in content if getattr(b, "type", None) == "text"]
    return ("text", "\n".join(parts).strip() or "I couldn't generate an answer just now — try rephrasing.")


async def interpret(
    question: str, client: dict, context: dict, history: Optional[list[dict]] = None,
    style: str = "slack", on_event=None,
) -> tuple[str, object]:
    """Decide whether the message is a question or an action request.

    Returns ("action", {"name": tool_name, "args": tool_input}) when the
    teammate is asking to trigger one of the available actions, else
    ("text", answer). Claude sees the cross-module context + thread history, the
    action tools, the server-side web_search tool (when enabled), and two
    in-answer client tools — `read_sop` (SOP grounding) and the free
    `fetch_live_gsc` (live Search Console pull) — executed inline over bounded
    rounds and folded back into the answer; web-search turns additionally
    resume through `pause_turn` continuations. An action call ⇒ ("action", …).
    `style="web"` swaps the Slack-mrkdwn voice for dashboard-chat Markdown.
    `on_event` (async callable) streams the turn: {"type":"text","text":delta}
    token deltas plus {"type":"status","label":…} tool-activity markers.
    """
    import anthropic

    from services import sop_library

    blocks = []
    if history:
        blocks.append("Conversation so far (oldest first):\n" + format_history(history))
    blocks.append(f"Latest message: {question}")
    blocks.append(f"Client data (JSON):\n{format_context(client, context)}")
    # Strategy-shaped question → the relevant SOPs ride along in the prompt
    # (the read_sop tool covers anything the gate/selection missed).
    if wants_sop_grounding(question):
        sops = sop_library.select_sops_text(
            sop_domains(question, context),
            budget_chars=settings.slack_assistant_sop_budget_chars,
        )
        if sops:
            blocks.append(
                "SOP LIBRARY (ground strategy/process advice in these; cite doc + "
                "section):\n" + sops
            )
    user = "\n\n".join(blocks)
    api = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=_LLM_TIMEOUT,
        max_retries=_LLM_MAX_RETRIES,
    )
    messages: list[dict] = [{"role": "user", "content": user}]
    tools = build_llm_tools() + [_read_sop_tool(), _LIVE_GSC_TOOL, _LIST_NONINDEXED_TOOL, _MEMORY_TOOL]
    # Bounded tool loop: read_sop / fetch_live_gsc calls are answered
    # in-conversation; an action call returns immediately (actions never mix
    # with in-answer tool reads — first wins).
    max_rounds = max(settings.slack_assistant_sop_rounds, _LIVE_GSC_ROUNDS)
    system = _SYSTEM + (_WEB_STYLE if style == "web" else "")

    async def on_text(delta: str) -> None:
        await on_event({"type": "text", "text": delta})

    for round_no in range(max_rounds + 1):
        final_round = round_no == max_rounds
        try:
            resp = await _create_with_continuation(
                api, system, messages, tools,
                tool_choice={"type": "none"} if final_round else None,
                on_text=on_text if on_event else None,
            )
        except anthropic.APIStatusError as exc:
            # Capacity exhaustion (retries included) is transient, not a fault —
            # degrade to a friendly "try again shortly" instead of erroring the turn.
            if exc.status_code in _CAPACITY_STATUS_CODES:
                logger.warning(
                    "assistant_llm_capacity",
                    extra={"status_code": exc.status_code, "client_id": client.get("id")},
                )
                return ("text", _BUSY_REPLY)
            raise
        for b in resp.content:
            if getattr(b, "type", None) == "tool_use" and b.name in _ACTIONS:
                return ("action", {"name": b.name, "args": dict(b.input or {})})
        tool_calls = [
            b for b in resp.content
            if getattr(b, "type", None) == "tool_use"
            and b.name in ("read_sop", _LIVE_GSC_TOOL["name"], _LIST_NONINDEXED_TOOL["name"], _MEMORY_TOOL["name"])
        ]
        if not tool_calls or final_round:
            break
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in tool_calls:
            args = dict(b.input or {})
            if on_event:
                label = {
                    "read_sop": f"Reading SOP: {args.get('doc', '')}".strip().rstrip(":"),
                    _LIVE_GSC_TOOL["name"]: "Pulling live Search Console data",
                    _LIST_NONINDEXED_TOOL["name"]: "Checking Search Console for non-indexed pages",
                    _MEMORY_TOOL["name"]: "Saving a note to memory",
                }.get(b.name, "Working")
                await on_event({"type": "status", "label": label})
            if b.name == "read_sop":
                text = sop_library.read_sop(args.get("doc", ""), args.get("section"))
            elif b.name == _MEMORY_TOOL["name"]:
                text = await asyncio.to_thread(
                    _run_remember, client["id"], args,
                    "slack" if style == "slack" else "chat",
                )
            elif b.name == _LIST_NONINDEXED_TOOL["name"]:
                text = await _run_list_nonindexed(client["id"], args)
            else:
                text = await _run_live_gsc(client["id"], args)
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": text})
        if round_no == max_rounds - 1:
            results.append(
                {"type": "text", "text": "Tool budget exhausted — answer now with what you have."}
            )
        messages.append({"role": "user", "content": results})
    kind, payload = extract_interpretation(resp.content)
    if kind == "text" and getattr(resp, "stop_reason", None) == "max_tokens":
        # Ran out of room — close cleanly instead of stopping mid-sentence. The
        # truncated reply stays in history, so "continue" picks the thought up.
        payload = str(payload).rstrip() + "\n\n_…I hit my reply-length limit — say “continue” and I'll pick up where I left off._"
    return (kind, payload)


async def interpret_portfolio(
    question: str, portfolio: dict, history: Optional[list[dict]] = None,
    style: str = "slack", on_event=None,
) -> str:
    """Answer an agency-wide question (no client named) from the cross-client
    snapshot. One call, no tools — the snapshot is counts; per-client depth and
    actions route through the single-client path once a client is named."""
    import anthropic

    blocks = []
    if history:
        blocks.append("Conversation so far (oldest first):\n" + format_history(history))
    blocks.append(f"Latest message: {question}")
    blocks.append(
        "Portfolio snapshot (JSON):\n"
        + json.dumps(portfolio, default=str, ensure_ascii=False)
    )
    api = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=_LLM_TIMEOUT,
        max_retries=_LLM_MAX_RETRIES,
    )
    system = _PORTFOLIO_SYSTEM + (_WEB_STYLE if style == "web" else "")

    async def on_text(delta: str) -> None:
        await on_event({"type": "text", "text": delta})

    try:
        resp = await _one_llm_call(
            api, system, [{"role": "user", "content": "\n\n".join(blocks)}], [],
            {}, on_text if on_event else None,
        )
    except anthropic.APIStatusError as exc:
        if exc.status_code in _CAPACITY_STATUS_CODES:
            return _BUSY_REPLY
        raise
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    reply = "\n".join(parts).strip() or "I couldn't generate an answer just now — try rephrasing."
    if getattr(resp, "stop_reason", None) == "max_tokens":
        reply += "\n\n_…I hit my reply-length limit — say “continue” and I'll pick up where I left off._"
    return reply


async def _run_action(name: str, client_id: str, args: Optional[dict]) -> str:
    """Invoke an action runner, awaiting it when async."""
    import inspect

    out = _ACTIONS[name]["run"](client_id, args or {})
    if inspect.isawaitable(out):
        out = await out
    return out


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


async def fetch_thread_history(channel: str, thread_ts: str, skip_ts: Optional[str]) -> list[dict]:
    """Recent prior messages of a thread as [{role, content}], oldest first.

    `role` is "assistant" for SerMastr's own posts (any bot message) and "user"
    otherwise. The triggering message (`skip_ts`) is excluded. Best-effort — any
    failure returns []."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            _SLACK_REPLIES_URL,
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
            params={"channel": channel, "ts": thread_ts, "limit": _THREAD_HISTORY_LIMIT},
        )
        resp.raise_for_status()
        data = resp.json()
    if not data.get("ok"):
        return []
    out: list[dict] = []
    for m in data.get("messages", []):
        if skip_ts and m.get("ts") == skip_ts:
            continue
        text = strip_mention(m.get("text", ""))
        if not text:
            continue
        out.append({"role": "assistant" if m.get("bot_id") else "user", "content": text})
    return out


async def handle_message(event: dict) -> None:
    """Process one channel message end-to-end (channel mode: no @mention needed).

    The router has already filtered to plain human messages. We answer every one:
    resolve the client, build cross-module context, fold in thread history for
    continuity, ask Claude, and reply in-thread. Best-effort; logs and bails on error.
    """
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    question = strip_mention(event.get("text", ""))
    if not (channel and question):
        return

    # 0) PACE (delivery PM) gets first refusal — but only when enabled (default
    # off → this branch is inert and SerMaStr is byte-for-byte unchanged).
    #  - Dedicated PACE channel set (§10.2): in THAT channel PACE owns every
    #    message (force) and SerMaStr is excluded; in any other channel PACE
    #    stays out entirely.
    #  - No dedicated channel: shared-channel shape-routing — PACE handles only
    #    project-management-shaped messages + its own confirms, else falls through.
    if settings.pace_enabled:
        try:
            from services import pace_agent, pace_auth

            pace_channel = settings.pace_slack_channel
            if pace_channel:
                if channel == pace_channel:
                    actor = pace_auth.resolve_slack_actor(event.get("user"), channel)
                    await pace_agent.maybe_handle_slack(event, actor, force=True)
                    return  # PACE owns its channel; SerMaStr never runs here
                # else: a non-PACE channel while a dedicated channel is set → skip
                # PACE; SerMaStr handles below.
            else:
                actor = pace_auth.resolve_slack_actor(event.get("user"), channel)
                if await pace_agent.maybe_handle_slack(event, actor):
                    return
        except Exception as exc:  # PACE must never break the SerMaStr path
            logger.warning("pace_slack_delegate_failed", extra={"channel": channel, "error": str(exc)})

    try:
        # 1) Confirmation of a pending paid action ("yes") — runs the stored action
        # (which carries its own client_id, so the "yes" needn't name a client).
        pend_key = (channel, thread_ts)
        pending = _pending.get(pend_key)
        if pending and is_affirmative(question):
            _pending.pop(pend_key, None)
            reply = await _run_action(pending["action"], pending["client_id"], pending.get("args"))
            await post_message(channel, reply, thread_ts)
            return
        if pending:  # a different message supersedes the pending confirmation
            _pending.pop(pend_key, None)

        supabase = get_supabase()
        clients = (
            supabase.table("clients").select("id, name, website_url").execute()
        ).data or []
        client = resolve_client(question, clients)
        if not client:
            # Portfolio mode — a Director answers agency-wide questions instead
            # of demanding a client name; the prompt asks "which client?" itself
            # when the question is really about one it can't identify.
            history = []
            if event.get("thread_ts") and event.get("thread_ts") != event.get("ts"):
                try:
                    history = await fetch_thread_history(channel, event["thread_ts"], event.get("ts"))
                except Exception as exc:
                    logger.warning("slack_thread_history_failed", extra={"channel": channel, "error": str(exc)})
            portfolio = build_portfolio_context()
            reply = await interpret_portfolio(question, portfolio, history)
            await post_message(channel, reply, thread_ts)
            return

        history: list[dict] = []
        if event.get("thread_ts") and event.get("thread_ts") != event.get("ts"):
            try:
                history = await fetch_thread_history(channel, event["thread_ts"], event.get("ts"))
            except Exception as exc:  # memory is best-effort
                logger.warning("slack_thread_history_failed", extra={"channel": channel, "error": str(exc)})

        context = build_context(client["id"])
        kind, payload = await interpret(question, client, context, history)
        if kind == "action":
            name, args = payload["name"], payload["args"]
            meta = _ACTIONS[name]
            confirm_phrase = None
            if meta.get("stage"):
                # Resolve the target BEFORE the confirm (exact task, matched
                # assignee) — guards / ambiguity answer immediately instead.
                outcome, staged = await meta["stage"](client["id"], args)
                if outcome == "reply":
                    await post_message(channel, staged, thread_ts)
                    return
                args = staged
                confirm_phrase = args.pop("_confirm", None)
            if meta["paid"]:
                # 2) Stage confirm-gated actions behind an explicit reply-*yes*
                # (guards spend + external side effects).
                _pending[pend_key] = {"action": name, "client_id": client["id"], "args": args}
                # A staged confirm phrase already names the exact target (and
                # carries its own severity wording), so the generic note only
                # accompanies the generic label.
                phrase = confirm_phrase or f"{meta['label']} ({meta.get('note', 'uses API budget')})"
                await post_message(
                    channel,
                    f"This will {phrase} for *{client['name']}*. Reply *yes* to proceed.",
                    thread_ts,
                )
            else:
                await post_message(channel, await _run_action(name, client["id"], args), thread_ts)
            return
        await post_message(channel, payload, thread_ts)
    except Exception as exc:
        logger.warning("slack_assistant_failed", extra={"channel": channel, "error": str(exc)})
        try:
            await post_message(channel, "Sorry — I hit an error answering that.", thread_ts)
        except Exception:
            pass
