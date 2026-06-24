"""Per-request LLM cost accounting for the Service Page Brief Generator.

The orchestrator reads `metadata.cost_usd` off the module response into
`module_outputs.cost_usd`, so the brief should report a real figure rather
than a placeholder. A `contextvar` holds a per-request tally that
`llm.claude_json_model` increments on every Anthropic call (Haiku teardown +
Sonnet synthesis), and `pipeline.run_service_brief` reads the total for
assembly. The tally is a single-element list so child coroutines that inherit
a copied context still mutate the same accumulator.
"""

from __future__ import annotations

import contextvars
from typing import Optional

# Approximate Anthropic prices in USD per 1M tokens (input, output). Matches the
# tiers used elsewhere in the suite; adjust if Anthropic pricing changes.
_PRICES: dict[str, tuple[float, float]] = {
    "haiku": (0.80, 4.00),
    "sonnet": (3.00, 15.00),
    "opus": (15.00, 75.00),
}

_cost_accumulator: contextvars.ContextVar[Optional[list[float]]] = contextvars.ContextVar(
    "service_brief_cost", default=None
)


def start_accounting() -> None:
    """Begin a fresh per-request cost tally (call once per brief run)."""
    _cost_accumulator.set([0.0])


def _price_for(model: str) -> tuple[float, float]:
    m = (model or "").lower()
    for key, price in _PRICES.items():
        if key in m:
            return price
    return _PRICES["sonnet"]


def record_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    """Add one Anthropic call's cost to the active tally (no-op if unstarted)."""
    bucket = _cost_accumulator.get()
    if bucket is None:
        return
    in_price, out_price = _price_for(model)
    bucket[0] += (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price


def total_cost() -> float:
    """Return the accumulated cost in USD (0.0 if accounting wasn't started)."""
    bucket = _cost_accumulator.get()
    return round(bucket[0], 6) if bucket else 0.0
