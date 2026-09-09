"""Provider-aware prose generation for the content writers (owner request 2026-09).

The blog + service Writer's PROSE steps — title, intro, body sections (the main
article content), key takeaways, FAQ, conclusion — call :func:`prose_json`
instead of ``claude_json`` so a single run can route its DRAFT to OpenAI
(``content_writer_openai_model``, default ``gpt-5.6-luna``) while every
post-draft quality gate (voice scoring, ICP/banned-term/QA judges, term
reconciliation, heading polish) stays on Claude — their thresholds are calibrated
to Claude's behaviour, so grading stays consistent no matter who wrote the draft.

Selection is per-request via a contextvar set once at the top of ``run_writer``
from the run's resolved ``content_writer_provider``. The default is Anthropic, so
an unset contextvar makes :func:`prose_json` a byte-for-byte drop-in for
``claude_json`` (same parsed-JSON contract, same transient-retry behaviour).

Contextvars are copied into child tasks at creation, so the body-section fan-out
(``asyncio.gather``) inherits the request's provider automatically.

OpenAI notes:
  * GPT-5-class models are called via ``chat.completions`` with
    ``max_completion_tokens`` and ``response_format={"type": "json_object"}``
    (the same shape the suite already uses for gpt-5.4 text in report_llm).
  * ``temperature`` is deliberately NOT sent — GPT-5 reasoning models reject a
    non-default temperature (as Opus 4.8 rejects it on the Claude side).
  * A missing ``OPENAI_API_KEY`` degrades to Claude rather than failing the run —
    a run must never fail to produce a draft because the alternate provider is
    unconfigured.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import secrets
from typing import Any, Optional

from config import settings

from modules.brief import cost
from modules.brief.llm import (
    _STRICT_JSON_SUFFIX,
    _extract_json_payload,
    claude_json,
)

logger = logging.getLogger(__name__)

# "anthropic" (default) | "openai". Set per-request at the top of run_writer.
_provider_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "content_writer_provider", default="anthropic"
)


def normalize_provider(provider: Optional[str]) -> str:
    """Coerce a provider selection to a known value, defaulting to Anthropic.

    Pure. An unknown / empty value resolves to "anthropic" so a bad column value
    can never route a run to a nonexistent provider."""
    p = (provider or "").strip().lower()
    return "openai" if p == "openai" else "anthropic"


def set_prose_provider(provider: Optional[str]) -> contextvars.Token:
    """Select the prose provider for the current request. Returns a token to pass
    to :func:`reset_prose_provider` in a finally block."""
    return _provider_var.set(normalize_provider(provider))


def reset_prose_provider(token: contextvars.Token) -> None:
    _provider_var.reset(token)


def current_prose_provider() -> str:
    """The provider prose will actually be written with, accounting for a missing
    OpenAI key (which degrades to Anthropic)."""
    provider = _provider_var.get()
    if provider == "openai" and not settings.openai_api_key:
        return "anthropic"
    return provider


def effective_prose_model() -> Optional[str]:
    """The concrete model id that will write the prose when OpenAI is the
    effective provider, else None (Claude prose uses the module default)."""
    return settings.content_writer_openai_model if current_prose_provider() == "openai" else None


async def prose_json(
    system: str,
    user: str,
    max_tokens: int = 1500,
    temperature: Optional[float] = 0.2,
    model: Optional[str] = None,
) -> Any:
    """Generate one JSON prose response with the request's selected provider.

    Anthropic path is ``claude_json`` verbatim (so ``model``/``temperature`` keep
    their existing meaning). OpenAI path calls :func:`openai_json`, which mirrors
    the parsed-JSON contract. A run selecting OpenAI with no key configured falls
    back to Claude.
    """
    if current_prose_provider() == "openai":
        return await openai_json(system, user, max_tokens=max_tokens, temperature=temperature)
    return await claude_json(system, user, max_tokens=max_tokens, temperature=temperature, model=model)


# ---- OpenAI transport (mirrors modules/brief/llm.py::_create_message) ----

_openai_client: Any = None
_openai_semaphore: Optional[asyncio.Semaphore] = None


def _get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI  # lazy so a missing SDK never breaks import

        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


def _get_openai_semaphore() -> asyncio.Semaphore:
    global _openai_semaphore
    if _openai_semaphore is None:
        _openai_semaphore = asyncio.Semaphore(settings.openai_max_concurrency)
    return _openai_semaphore


def _is_transient_openai_error(exc: Exception) -> bool:
    """Retryable OpenAI failures: 429 rate limit, 5xx overload, connection drops.
    Auth/bad-request errors fail fast. Lazy-imports the SDK so this stays safe
    even if openai weren't installed."""
    try:
        import openai
    except Exception:  # noqa: BLE001
        return False
    if isinstance(exc, (openai.RateLimitError, openai.APIConnectionError)):
        return True
    if isinstance(exc, openai.APIStatusError):
        code = getattr(exc, "status_code", None) or 0
        return code == 429 or code >= 500
    return False


async def openai_json(
    system: str,
    user: str,
    max_tokens: int = 1500,
    temperature: Optional[float] = None,
    record_usage=None,
) -> Any:
    """Call the OpenAI content-writer model and parse the response as JSON.

    Mirrors ``claude_json``'s contract: returns a parsed JSON value, tolerates a
    prose/fence-wrapped payload via the shared ``_extract_json_payload``, records
    token usage into the per-request cost tally, and retries transient failures
    (429 / 5xx / connection drops) with bounded exponential backoff + jitter
    under a concurrency semaphore (the body-section step fans out).

    ``record_usage`` is the cost hook (``record_usage(model, in_tok, out_tok)``);
    it defaults to the blog pipeline's tally, and the service writer passes its
    own so service-page OpenAI spend lands in the right accounting bucket.

    ``temperature`` is accepted for signature parity but NOT forwarded — GPT-5
    models reject a non-default temperature.
    """
    _record = record_usage or cost.record_usage
    client = _get_openai()
    semaphore = _get_openai_semaphore()
    model = settings.content_writer_openai_model
    # json_object mode requires the word "json" to appear in the prompt; the
    # strict suffix carries it and reinforces "JSON only" (same as claude_json's
    # retry addendum).
    sys_prompt = system + _STRICT_JSON_SUFFIX

    attempt = 0
    while True:
        try:
            async with semaphore:
                resp = await client.chat.completions.create(
                    model=model,
                    max_completion_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                )
            usage = getattr(resp, "usage", None)
            if usage is not None:
                _record(
                    model,
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                )
            choice = (resp.choices or [None])[0]
            text = ""
            if choice is not None and getattr(choice, "message", None) is not None:
                text = choice.message.content or ""
            finish = getattr(choice, "finish_reason", None) if choice else None
            if finish == "length":
                logger.warning(
                    "openai_json.truncated",
                    extra={"max_tokens": max_tokens, "model": model, "response_chars": len(text)},
                )
            try:
                return _extract_json_payload(text)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "openai_json parse failed: %s - finish=%s response head=%r",
                    exc,
                    finish,
                    text[:500],
                )
                raise
        except Exception as exc:  # noqa: BLE001 — classify, re-raise if terminal
            if attempt >= settings.anthropic_max_retries or not _is_transient_openai_error(exc):
                raise
            delay = settings.anthropic_retry_base_seconds * (2 ** attempt) * (
                0.5 + secrets.randbelow(1000) / 1000.0
            )
            logger.warning(
                "openai_transient_retry",
                extra={"attempt": attempt + 1, "delay_s": round(delay, 1), "error": str(exc)[:200]},
            )
            await asyncio.sleep(delay)
            attempt += 1
