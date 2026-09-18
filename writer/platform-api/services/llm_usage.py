"""Shared LLM / paid-API usage ledger writer.

Records one row per instrumented call into public.llm_usage (migration
20260918130000), which the cost_events view unions so the spend surfaces in the
admin Cost & Usage report. This is the capture point for LLM spend that has no
natural per-deliverable row (AI Visibility scans, KW-research LLM layers, the
conversational agents, …).

Best-effort by construction (mirrors services/qa_cost.py): a recording failure is
logged and swallowed — instrumentation must NEVER break the work it meters. A
call with no tokens and no cost records nothing.

Context: many call sites are deep (an engine executor inside a scan cell) and
lack the client/actor context. `usage_context(...)` sets a contextvar that
`record(...)` merges in, so a caller wraps the operation once and the leaf call
sites stay one-liners. Explicit kwargs on record() always win over the context.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from typing import Any, Iterator, Optional

from db.supabase_client import get_supabase
from services import llm_pricing

logger = logging.getLogger(__name__)

_SERVICE = "platform-api"

# {client_id, actor_id, source, metadata} merged into every record() in scope.
_ctx: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("llm_usage_ctx", default=None)


@contextlib.contextmanager
def usage_context(
    *, source: Optional[str] = None, client_id: Any = None, actor_id: Any = None,
    metadata: Optional[dict] = None,
) -> Iterator[None]:
    """Set the ambient recording context for the duration of the block. Nested
    contexts merge (inner wins). Never raises."""
    base = _ctx.get() or {}
    merged = dict(base)
    if source is not None:
        merged["source"] = source
    if client_id is not None:
        merged["client_id"] = str(client_id)
    if actor_id is not None:
        merged["actor_id"] = str(actor_id)
    if metadata:
        merged["metadata"] = {**(base.get("metadata") or {}), **metadata}
    token = _ctx.set(merged)
    try:
        yield
    finally:
        _ctx.reset(token)


def record(
    *, provider: str, model: Optional[str] = None,
    input_tokens: int = 0, output_tokens: int = 0,
    source: Optional[str] = None, operation: Optional[str] = None,
    client_id: Any = None, actor_id: Any = None,
    cost_usd: Optional[float] = None, priced: Optional[bool] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Append one usage row. `cost_usd` is computed from the model price when not
    given (unknown model → 0 with priced=False). Merges the ambient
    usage_context() for source/client/actor/metadata. Never raises."""
    try:
        ctx = _ctx.get() or {}
        src = source or ctx.get("source")
        if not src:
            return  # no source → not an instrumented operation; record nothing
        it = int(input_tokens or 0)
        ot = int(output_tokens or 0)
        if cost_usd is None:
            cost, computed_priced = llm_pricing.compute_cost(model, it, ot)
        else:
            cost, computed_priced = float(cost_usd), True
        if priced is None:
            priced = computed_priced
        if it == 0 and ot == 0 and (cost or 0) == 0:
            return  # nothing to record
        cid = client_id if client_id is not None else ctx.get("client_id")
        aid = actor_id if actor_id is not None else ctx.get("actor_id")
        meta = {**(ctx.get("metadata") or {}), **(metadata or {})}
        row = {
            "service": _SERVICE,
            "source": src,
            "operation": operation,
            "provider": provider,
            "model": model,
            "client_id": str(cid) if cid else None,
            "actor_id": str(aid) if aid else None,
            "input_tokens": it,
            "output_tokens": ot,
            "cost_usd": round(float(cost), 6),
            "priced": bool(priced),
            "metadata": meta,
        }
        get_supabase().table("llm_usage").insert(row).execute()
    except Exception as exc:  # pragma: no cover - best effort, must never raise
        logger.warning("llm_usage.record_failed", extra={"error": str(exc), "source": source})


# ── usage extractors for the various SDK/response shapes ─────────────────────

def anthropic_usage(resp: Any) -> tuple[int, int]:
    """(input_tokens, output_tokens) from an Anthropic messages response."""
    u = getattr(resp, "usage", None)
    if not u:
        return 0, 0
    return int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)


def openai_usage(resp: Any) -> tuple[int, int]:
    """(input, output) from an OpenAI response — handles both the Responses API
    (input_tokens/output_tokens) and Chat Completions (prompt/completion_tokens)."""
    u = getattr(resp, "usage", None)
    if not u:
        return 0, 0
    it = getattr(u, "input_tokens", None)
    ot = getattr(u, "output_tokens", None)
    if it is None:
        it = getattr(u, "prompt_tokens", 0)
    if ot is None:
        ot = getattr(u, "completion_tokens", 0)
    return int(it or 0), int(ot or 0)


def gemini_usage(data: Any) -> tuple[int, int]:
    """(prompt, candidates) tokens from a Gemini generateContent JSON dict."""
    if not isinstance(data, dict):
        return 0, 0
    um = data.get("usageMetadata") or {}
    return int(um.get("promptTokenCount") or 0), int(um.get("candidatesTokenCount") or 0)


def openai_usage_dict(data: Any) -> tuple[int, int]:
    """(input, output) from a raw JSON usage dict (Perplexity/OpenAI-shaped)."""
    if not isinstance(data, dict):
        return 0, 0
    u = data.get("usage") or {}
    it = u.get("input_tokens", u.get("prompt_tokens", 0))
    ot = u.get("output_tokens", u.get("completion_tokens", 0))
    return int(it or 0), int(ot or 0)
