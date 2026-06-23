"""Live per-run cost attribution (PRD §16.4).

Every external API call increments a per-worker accumulator (the `CostMeter`),
bound on the job thread via a contextvar and propagated into the pipeline's
nested worker threads by `ContextThreadPoolExecutor`. The job periodically
flushes the running total to `sessions.actual_cost_usd` + the per-step
`cost_breakdown` jsonb (see `app/cost_attribution.py`), so the UI's live cost
banner (§8.4) updates while the pipeline runs.

Cost is *metered*, not estimated:
- DataForSEO returns a real per-call `cost` in its task envelope — used directly.
- LLM (OpenAI / Anthropic) cost is derived from the real token usage on each
  response via the rate table below. The token counts are real; the $/token
  rates are estimates and should be recalibrated after the first ~10 production
  runs (same caveat as the §8.1 estimate table in `app/cost.py`).
"""

import logging
import threading
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# USD per 1,000,000 tokens, (input, output).
# Anthropic rates are the published Opus 4.7/4.8 list price ($5 in / $25 out per
# 1M tok); calibrated 2026-06-09 against live metered sessions, which surfaced the
# prior (15/75) estimate overcharging Opus LLM cost by 3x. The gpt-5.4 rate remains
# an estimate (OpenAI list price not re-verified here) but silo_discovery meters
# within a few cents of the §8.1 estimate, so it is in the right range.
_LLM_RATES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "gpt-5.4": (5.0, 15.0),
}
_DEFAULT_LLM_RATE = (5.0, 15.0)

# USD per 1,000,000 tokens for embedding models. ESTIMATE.
_EMBED_RATES: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    # Google AI Studio list price ($0.15/1M input; $0.075 batch). Tokens are
    # estimated from input length (Gemini's embed response carries no usage).
    "gemini-embedding-001": 0.15,
    # Embedding 2 (preview) — $0.20/1M ($0.10 batch). The bare "gemini-embedding-2"
    # key prefix-matches the "-preview" (and future) variants via _match_rate.
    "gemini-embedding-2": 0.20,
}
_DEFAULT_EMBED_RATE = 0.02


def _match_rate(model: str, table: dict) -> object:
    """Exact match, else longest known prefix, else None."""
    if model in table:
        return table[model]
    best = None
    for key in table:
        if model.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return table[best] if best is not None else None


def llm_token_cost(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """USD for an LLM call from its real token usage. None if tokens are
    unavailable (so the caller logs `cost_usd: null` rather than a wrong 0)."""
    if input_tokens is None and output_tokens is None:
        return None
    rate = _match_rate(model, _LLM_RATES) or _DEFAULT_LLM_RATE
    in_rate, out_rate = rate  # type: ignore[misc]
    return round(
        (input_tokens or 0) / 1_000_000 * in_rate
        + (output_tokens or 0) / 1_000_000 * out_rate,
        6,
    )


def embedding_token_cost(model: str, total_tokens: int | None) -> float | None:
    if total_tokens is None:
        return None
    rate = _match_rate(model, _EMBED_RATES)
    rate = rate if rate is not None else _DEFAULT_EMBED_RATE
    return round(total_tokens / 1_000_000 * float(rate), 6)  # type: ignore[arg-type]


class CostMeter:
    """Thread-safe running cost for one pipeline run, broken down by step.

    Shared across the job thread and the pipeline's nested worker threads, so all
    mutation goes through the lock. `step` defaults to whatever the job bound; an
    individual call can override it (rarely needed at this granularity)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total: float = 0.0
        self._breakdown: dict[str, float] = {}
        self._calls: int = 0

    def add(self, cost: float | None, step: str) -> None:
        if cost is None:
            return
        with self._lock:
            self._total = round(self._total + cost, 6)
            self._breakdown[step] = round(self._breakdown.get(step, 0.0) + cost, 6)
            self._calls += 1

    def snapshot(self) -> tuple[float, dict[str, float]]:
        with self._lock:
            return self._total, dict(self._breakdown)


_meter: ContextVar[CostMeter | None] = ContextVar("cost_meter", default=None)
_step: ContextVar[str] = ContextVar("cost_step", default="other")


def bind_meter(meter: CostMeter | None) -> None:
    _meter.set(meter)


def current_meter() -> CostMeter | None:
    return _meter.get()


def set_step(step: str) -> None:
    _step.set(step)


def get_step() -> str:
    return _step.get()


def record_cost(cost: float | None) -> None:
    """Add a call's cost to the bound meter (no-op outside a metered run, e.g. a
    plain request). Called from the external-API clients at each call site."""
    meter = _meter.get()
    if meter is not None:
        meter.add(cost, _step.get())
