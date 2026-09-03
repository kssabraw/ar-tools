"""Anthropic **prompt caching** helpers (``cache_control``).

The suite's agentic loops (SerMaStr strategist, the Slack/web assistant, PACE,
QA, DORA) each build a large, mostly-invariant prompt — a system prompt plus a
first user message carrying the whole cross-module *context* (a client digest,
board JSON, a read model) — and then re-send that same prefix on every round of
a bounded tool-use loop. Anthropic's ephemeral prompt cache lets the first round
write that prefix to a 5-minute cache and later rounds read it at ≈10% of the
input price instead of re-billing the full ~10k–40k tokens each round. The
invariant system prompt is additionally reused across the *bursty* back-to-back
calls of a weekly strategist fan-out.

The only knob is a cache *breakpoint*: a content block carrying
``cache_control: {"type": "ephemeral"}``. Everything from the start of the
request up to and including that block becomes one cached prefix (the API caches
in ``tools`` → ``system`` → ``messages`` order), so a breakpoint on the system
block caches ``tools + system`` and a breakpoint on the first user message
caches ``tools + system + that message``.

This module is a *pure formatting* seam — it turns a plain string into the block
list that carries the breakpoint. It never reorders or edits prompt content
(only the model-facing wording matters for behaviour, and that is unchanged), so
the change is transparent to output: it only affects cost. Two safety
properties make it drop-in everywhere:

* **Gated.** ``settings.prompt_cache_enabled`` (default True) is a kill switch —
  when off, every helper returns the plain string unchanged, i.e. the exact
  prior request shape.
* **Idempotent / total.** A non-string (already-structured content) or an empty
  string is returned unchanged, so a helper can be applied at a call site
  without first proving the input is a bare string, and double-application is a
  no-op.

A block below the model's minimum cacheable size (1024 tokens for Sonnet/Opus,
2048 for Haiku) is *not* cached by the API — the ``cache_control`` is ignored
rather than erroring — so it is safe to wrap a small system prompt too; it only
starts paying off once it is large enough to cache.
"""

from __future__ import annotations

from typing import Optional, Union

from config import settings

# One ephemeral cache breakpoint, reused for every wrapped block.
_EPHEMERAL = {"type": "ephemeral"}


def _enabled(override: Optional[bool]) -> bool:
    """The effective on/off state: an explicit ``override`` (used by tests) wins,
    else the config flag."""
    return settings.prompt_cache_enabled if override is None else override


def cache_text(text: Union[str, list, None], *, enabled: Optional[bool] = None):
    """Return ``text`` as a one-element ephemeral-cached content-block list,
    marking a cache breakpoint at its end.

    Returns the input **unchanged** when caching is disabled, when ``text`` is
    empty, or when it is not a bare string (already a block list / None) — so
    this is safe to apply unconditionally at a call site and is a no-op if
    applied twice. Usable for both a ``system`` prompt and a message's
    ``content`` (both accept the block-list shape).
    """
    if not _enabled(enabled) or not isinstance(text, str) or not text:
        return text
    return [{"type": "text", "text": text, "cache_control": _EPHEMERAL}]


# ---------------------------------------------------------------------------
# Measurement — make the cache's effect observable.
#
# Caching only pays when the cache is actually *read*: a warm loop should show
# `cache_read_input_tokens` dominating regular `input_tokens`, with
# `cache_creation_input_tokens` (the 1.25×/2× write) roughly one prefix's worth.
# The API returns these on `response.usage`; the helpers below extract them (an
# empty read across repeated calls is the signature of a silent invalidator).
# ---------------------------------------------------------------------------
_CACHE_USAGE_KEYS = ("cache_read_input_tokens", "cache_creation_input_tokens")


def usage_cache_fields(usage) -> dict:
    """The cache-accounting token counts off an Anthropic response ``usage``
    object (or None), zero-filled when absent. Pure — no SDK import, tolerant of
    a mock/None so a call site can capture unconditionally."""
    out: dict = {}
    for key in _CACHE_USAGE_KEYS:
        try:
            out[key] = int(getattr(usage, key, 0) or 0)
        except (TypeError, ValueError):
            out[key] = 0
    return out


def add_cache_usage(acc: dict, usage) -> dict:
    """Accumulate a response's cache-token counts into ``acc`` in place (keys
    zero-initialised on first use), and return it. Lets a multi-round loop total
    its cache reads/writes alongside the input/output tokens it already sums, so
    the hit rate is visible in the persisted usage. Pure/best-effort."""
    for key, val in usage_cache_fields(usage).items():
        acc[key] = acc.get(key, 0) + val
    return acc
