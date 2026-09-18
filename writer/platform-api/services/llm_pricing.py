"""USD-per-token pricing for the LLM usage ledger (services/llm_usage.py).

Substring-matched (lowercased) so a dated model id (…-4-5-20251001) still
resolves. A model not in the table is recorded with its TOKENS but no dollar
cost (priced=False) — volume stays visible and the rate can be back-filled.

Anthropic list prices are from the claude-api skill (cached 2026-06-24); the
OpenAI "Luna" rate is the one already modelled in nlp-api/_MODEL_PRICING. The
other OpenAI models (gpt-5.4 / gpt-5.4-mini), Gemini, and Perplexity models the
AI-Visibility scanner uses have no confirmed rate here yet, so they capture
tokens unpriced until the owner supplies the per-1M numbers — add them to
`register_prices` (or the tables below) and past rows re-price on the next read
of the report's derived cost (the stored cost_usd stays as first written).
"""

from __future__ import annotations

from typing import Optional

# USD per 1M tokens (input, output). Order matters: more specific keys first.
_ANTHROPIC: dict[str, tuple[float, float]] = {
    "haiku": (1.00, 5.00),
    "sonnet-4-6": (3.00, 15.00),
    "sonnet-5": (2.00, 10.00),
    "sonnet": (3.00, 15.00),   # default Sonnet tier when unversioned
    "opus": (5.00, 25.00),
}
_OPENAI: dict[str, tuple[float, float]] = {
    "gpt-5.6-luna": (0.20, 1.20),   # confirmed (OpenAI published, 2026-09-14)
}
_OTHER: dict[str, tuple[float, float]] = {}  # gemini/perplexity/etc — owner-supplied


def register_prices(prices: dict[str, tuple[float, float]]) -> None:
    """Add/override per-1M (input, output) rates by model-id substring. Lets the
    owner supply OpenAI/Gemini/Perplexity rates without a code change."""
    _OTHER.update({k.lower(): (float(v[0]), float(v[1])) for k, v in prices.items()})


def price_for(model: Optional[str]) -> Optional[tuple[float, float]]:
    """(input, output) per-1M rate for a model id, or None if unknown. Pure."""
    if not model:
        return None
    m = model.lower()
    for table in (_OTHER, _OPENAI, _ANTHROPIC):
        for key, price in table.items():
            if key in m:
                return price
    return None


def compute_cost(model: Optional[str], input_tokens: int, output_tokens: int) -> tuple[float, bool]:
    """(cost_usd, priced) for a token count. Unknown model → (0.0, False). Pure."""
    p = price_for(model)
    if not p:
        return 0.0, False
    cost = (input_tokens / 1_000_000.0) * p[0] + (output_tokens / 1_000_000.0) * p[1]
    return round(cost, 6), True
