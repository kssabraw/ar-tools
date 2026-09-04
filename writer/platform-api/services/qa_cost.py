"""Per-review LLM cost + token accounting for the QA agent.

QA makes a few cheap Anthropic calls per review (the map-embed assertion judge,
the fail/needs-human narrative, the visual render check) but historically
persisted neither cost nor tokens, so QA spend was invisible in the Cost & Usage
report. This mirrors modules/brief/cost.py: a contextvar holds a per-review tally
that each ``messages.create`` site increments via ``record_from_message``;
``run_review`` starts it and writes the totals onto the ``qa_reviews`` row.

Best-effort by construction: recording is a no-op when accounting wasn't started
(so a stray call outside a review records nothing), and a malformed usage object
is ignored — QA must never fail because it couldn't meter itself.
"""

from __future__ import annotations

import contextvars
from typing import Any, Optional

# USD per 1M tokens (input, output) — Anthropic list prices, matching
# pipeline-api/modules/brief/cost.py. Substring-matched so a dated model id
# (…-4-5) still resolves; unknown models fall back to Haiku (QA's default tier).
_PRICES: dict[str, tuple[float, float]] = {
    "haiku": (1.00, 5.00),
    "sonnet": (3.00, 15.00),
    "opus": (5.00, 25.00),
}

# [cost_usd, input_tokens, output_tokens]
_acc: contextvars.ContextVar[Optional[list[float]]] = contextvars.ContextVar("qa_cost", default=None)


def start_accounting() -> None:
    """Begin a fresh per-review tally (call once at the top of run_review)."""
    _acc.set([0.0, 0, 0])


def _price_for(model: str) -> tuple[float, float]:
    m = (model or "").lower()
    for key, price in _PRICES.items():
        if key in m:
            return price
    return _PRICES["haiku"]


def record_from_message(msg: Any, model: str) -> None:
    """Add one Anthropic response's usage to the active tally. No-op if unstarted
    or if the message carries no usable usage. Never raises."""
    bucket = _acc.get()
    if bucket is None:
        return
    try:
        usage = getattr(msg, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
    except (TypeError, ValueError):
        return
    in_price, out_price = _price_for(model)
    bucket[0] += (in_tok / 1_000_000) * in_price + (out_tok / 1_000_000) * out_price
    bucket[1] += in_tok
    bucket[2] += out_tok


def total_cost() -> float:
    """Accumulated cost in USD (0.0 if unstarted)."""
    bucket = _acc.get()
    return round(bucket[0], 6) if bucket else 0.0


def total_tokens() -> dict[str, int]:
    """Accumulated {input_tokens, output_tokens} (zeros if unstarted)."""
    bucket = _acc.get()
    if not bucket:
        return {"input_tokens": 0, "output_tokens": 0}
    return {"input_tokens": int(bucket[1]), "output_tokens": int(bucket[2])}
