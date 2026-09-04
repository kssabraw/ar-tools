"""Per-request LLM cost accounting for the blog pipeline modules.

The blog modules (brief / sie / research / writer / sources_cited) all share the
``modules/brief/llm.py`` transport, which — unlike the service_brief/service_writer
transport — never recorded token usage, so every blog ``module_outputs.cost_usd``
persisted as $0 and blog Claude spend was invisible in the DB (and in the
token-spend profiler). This mirrors ``modules/service_brief/cost.py``: a
``contextvar`` holds a per-request tally that the shared transport increments on
every Anthropic call, and an ASGI middleware (main.py, scoped to the blog paths)
starts the tally per request and surfaces the total as ``cost_usd`` on the JSON
response — which the orchestrator already reads into ``module_outputs.cost_usd``.

The tally is a single-element list so child coroutines that inherit a copied
context (the modules fan out LLM calls with ``asyncio.gather``) still mutate the
same accumulator.
"""

from __future__ import annotations

import contextvars
from typing import Optional

# Anthropic list prices, USD per 1M tokens (input, output), current as of
# 2026-09. Matches the model tiers the blog modules use — Sonnet 4.6 for
# generation, Haiku 4.5 for cheap steps, Opus 4.8 for the answer-contract
# reasoning step. Substring-matched, so a dated model id (…-4-6) still resolves.
_PRICES: dict[str, tuple[float, float]] = {
    "haiku": (1.00, 5.00),
    "sonnet": (3.00, 15.00),
    "opus": (5.00, 25.00),
}

_cost_accumulator: contextvars.ContextVar[Optional[list[float]]] = contextvars.ContextVar(
    "blog_pipeline_cost", default=None
)
# Token tally parallel to the cost tally: [input_tokens, output_tokens]. Same
# single-mutable-container trick so gathered child coroutines accumulate into it.
_token_accumulator: contextvars.ContextVar[Optional[list[int]]] = contextvars.ContextVar(
    "blog_pipeline_tokens", default=None
)


def start_accounting() -> None:
    """Begin a fresh per-request cost + token tally (once per blog module request)."""
    _cost_accumulator.set([0.0])
    _token_accumulator.set([0, 0])


def _price_for(model: str) -> tuple[float, float]:
    m = (model or "").lower()
    for key, price in _PRICES.items():
        if key in m:
            return price
    return _PRICES["sonnet"]


def record_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    """Add one Anthropic call's cost to the active tally.

    A no-op when accounting wasn't started (bucket is None) — so a non-blog
    request that happens to reuse this transport records nothing, and the hook is
    safe to leave in the shared choke point unconditionally.
    """
    bucket = _cost_accumulator.get()
    if bucket is None:
        return
    in_price, out_price = _price_for(model)
    bucket[0] += (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price
    tokens = _token_accumulator.get()
    if tokens is not None:
        tokens[0] += int(input_tokens or 0)
        tokens[1] += int(output_tokens or 0)


def total_cost() -> float:
    """Return the accumulated cost in USD (0.0 if accounting wasn't started)."""
    bucket = _cost_accumulator.get()
    return round(bucket[0], 6) if bucket else 0.0


def total_tokens() -> dict[str, int]:
    """Return the accumulated {input_tokens, output_tokens} (zeros if unstarted)."""
    tokens = _token_accumulator.get()
    if not tokens:
        return {"input_tokens": 0, "output_tokens": 0}
    return {"input_tokens": tokens[0], "output_tokens": tokens[1]}
