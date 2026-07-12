"""Shared LLM transport with **cross-provider fallback**.

Historically this module only backed the narrative report generators (maps_report,
rank_analysis_report) with a provider-selectable forced-tool-use call. It is now
the suite's shared LLM transport for the non-agentic call sites, adding automatic
**provider fallback**: when a call's primary provider (usually Anthropic) hits a
*transient* failure that outlasts its per-provider retry budget — a 429 rate /
concurrency limit, a 5xx overload, or a connection drop — the same call is retried
on the next provider in the chain (OpenAI, then Gemini) instead of failing.

Non-transient errors (bad request, auth) do NOT fall back — they surface
immediately so real bugs aren't masked. Providers with no configured API key are
skipped. The chain and per-provider fallback models are config-driven
(`llm_fallback_*` in config.py), so the whole behavior is one env change to tune
or disable.

Two shapes are supported, each in an async and a sync flavour:
  * `run_forced_tool` / `run_forced_tool_sync` — one forced tool call, returns the
    tool arguments dict (raises when no provider emitted the tool).
  * `generate_text` / `generate_text_sync` — one plain completion, returns text.

The agentic multi-turn tool-use loops (Slack assistant, strategist, PACE) rely on
Anthropic-specific server tools (web_search) and are NOT routed through here; they
keep their own Anthropic-only retry.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transient-error classification + retry (shared by every single-call service).
# ---------------------------------------------------------------------------
async def retry_transient(fn, *, max_retries: int = 4, base_seconds: float = 2.0, log_tag: str = "llm"):
    """Run `await fn()` retrying transient provider failures (429 rate limit,
    5xx/529 overloaded, connection drops) with exponential backoff + jitter.
    Non-transient errors re-raise immediately. Shared by every service whose
    single Claude/OpenAI call previously died on the first 429."""
    import asyncio
    import secrets

    attempt = 0
    while True:
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 — classify, re-raise if terminal
            if attempt >= max_retries or not is_transient_llm_error(exc):
                raise
            delay = base_seconds * (2 ** attempt) * (0.5 + secrets.randbelow(1000) / 1000.0)
            logger.warning(
                f"{log_tag}_transient_retry",
                extra={"attempt": attempt + 1, "delay_s": round(delay, 1), "error": str(exc)[:200]},
            )
            await asyncio.sleep(delay)
            attempt += 1


def retry_transient_sync(fn, *, max_retries: int = 4, base_seconds: float = 2.0, log_tag: str = "llm"):
    """Synchronous twin of :func:`retry_transient` for the sync call sites."""
    import secrets
    import time

    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — classify, re-raise if terminal
            if attempt >= max_retries or not is_transient_llm_error(exc):
                raise
            delay = base_seconds * (2 ** attempt) * (0.5 + secrets.randbelow(1000) / 1000.0)
            logger.warning(
                f"{log_tag}_transient_retry",
                extra={"attempt": attempt + 1, "delay_s": round(delay, 1), "error": str(exc)[:200]},
            )
            time.sleep(delay)
            attempt += 1


def is_transient_llm_error(exc: Exception) -> bool:
    """True for retryable provider failures on ANY provider: rate limit (429),
    transient 5xx (overloaded), and connection drops. Covers the Anthropic/OpenAI
    SDK exception hierarchies AND raw `httpx` errors (the Gemini REST fallback
    uses httpx directly). Lazy-imports each SDK so the pure helpers stay
    import-free and a missing SDK never breaks the check."""
    for mod_name in ("anthropic", "openai"):
        try:
            mod = __import__(mod_name)
        except Exception:  # noqa: BLE001 — SDK not installed / import error
            continue
        rate_limit = getattr(mod, "RateLimitError", None)
        conn_err = getattr(mod, "APIConnectionError", None)
        status_err = getattr(mod, "APIStatusError", None)
        if rate_limit and isinstance(exc, rate_limit):
            return True
        if conn_err and isinstance(exc, conn_err):
            return True
        if status_err and isinstance(exc, status_err):
            code = getattr(exc, "status_code", None) or 0
            if code == 429 or code >= 500:
                return True
    try:
        import httpx  # lazy

        if isinstance(exc, httpx.HTTPStatusError):
            resp = getattr(exc, "response", None)
            code = getattr(resp, "status_code", 0) or 0
            if code == 429 or code >= 500:
                return True
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError)):
            return True
    except Exception:  # noqa: BLE001 — httpx missing / unexpected shape
        pass
    return False


# ---------------------------------------------------------------------------
# Provider chain: primary + configured fallbacks, key-gated, model-resolved.
# ---------------------------------------------------------------------------
_FALLBACK_MODEL_DEFAULTS = {
    "anthropic": lambda: settings.llm_fallback_anthropic_model,
    "openai": lambda: settings.llm_fallback_openai_model,
    "gemini": lambda: settings.llm_fallback_gemini_model,
}


def _provider_chain(primary: str) -> list[str]:
    """The ordered provider list to try: the call's primary first, then each
    configured fallback (deduped). Fallback disabled → the primary alone."""
    primary = (primary or "anthropic").strip().lower()
    if not settings.llm_fallback_enabled:
        return [primary]
    chain = [primary]
    for p in (settings.llm_fallback_providers or "").split(","):
        p = p.strip().lower()
        if p and p not in chain:
            chain.append(p)
    return chain


def _provider_key_ok(provider: str) -> bool:
    return bool({
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
    }.get(provider))


def _model_for(provider: str, primary: str, primary_model: Optional[str], overrides: Optional[dict]) -> str:
    """The model to use for `provider`: an explicit override wins; the primary
    provider keeps the caller's model; a fallback provider uses its config
    default (or the caller's model as a last resort)."""
    if overrides and overrides.get(provider):
        return overrides[provider]
    if provider == primary and primary_model:
        return primary_model
    default = _FALLBACK_MODEL_DEFAULTS.get(provider)
    return (default() if default else None) or primary_model or ""


async def _chain_async(
    *, primary: str, primary_model: Optional[str], fallback_models: Optional[dict],
    log_tag: str, call: Callable, empty_check: Callable, empty_detail: Callable,
):
    """Drive an async LLM `call(provider, model)` across the provider chain.

    Each provider is retried on transient failures (bounded, so the chain
    advances quickly); a transient exhaustion OR an empty/unusable result moves
    to the next provider; a non-transient error re-raises immediately. Raises the
    last failure when every provider is exhausted."""
    chain = _provider_chain(primary)
    last_exc: Optional[Exception] = None
    tried_any = False
    for provider in chain:
        if not _provider_key_ok(provider):
            continue
        tried_any = True
        model = _model_for(provider, primary, primary_model, fallback_models)
        try:
            result = await retry_transient(
                lambda p=provider, m=model: call(p, m),
                max_retries=settings.llm_fallback_max_retries_per_provider,
                log_tag=f"{log_tag}:{provider}",
            )
        except Exception as exc:  # noqa: BLE001 — classify: fall back only on transient
            if is_transient_llm_error(exc):
                last_exc = exc
                logger.warning(
                    "llm_fallback_provider_exhausted",
                    extra={"log_tag": log_tag, "provider": provider, "error": str(exc)[:200]},
                )
                continue
            raise
        if empty_check(result):
            last_exc = RuntimeError(empty_detail(provider))
            logger.warning("llm_fallback_empty_result", extra={"log_tag": log_tag, "provider": provider})
            continue
        if provider != chain[0]:
            logger.info("llm_fallback_used", extra={"log_tag": log_tag, "provider": provider})
        return result
    if last_exc:
        raise last_exc
    raise RuntimeError(f"{log_tag}_no_provider_available (no configured API key)" if not tried_any else f"{log_tag}_all_providers_failed")


def _chain_sync(
    *, primary: str, primary_model: Optional[str], fallback_models: Optional[dict],
    log_tag: str, call: Callable, empty_check: Callable, empty_detail: Callable,
):
    """Synchronous twin of :func:`_chain_async`."""
    chain = _provider_chain(primary)
    last_exc: Optional[Exception] = None
    tried_any = False
    for provider in chain:
        if not _provider_key_ok(provider):
            continue
        tried_any = True
        model = _model_for(provider, primary, primary_model, fallback_models)
        try:
            result = retry_transient_sync(
                lambda p=provider, m=model: call(p, m),
                max_retries=settings.llm_fallback_max_retries_per_provider,
                log_tag=f"{log_tag}:{provider}",
            )
        except Exception as exc:  # noqa: BLE001
            if is_transient_llm_error(exc):
                last_exc = exc
                logger.warning(
                    "llm_fallback_provider_exhausted",
                    extra={"log_tag": log_tag, "provider": provider, "error": str(exc)[:200]},
                )
                continue
            raise
        if empty_check(result):
            last_exc = RuntimeError(empty_detail(provider))
            logger.warning("llm_fallback_empty_result", extra={"log_tag": log_tag, "provider": provider})
            continue
        if provider != chain[0]:
            logger.info("llm_fallback_used", extra={"log_tag": log_tag, "provider": provider})
        return result
    if last_exc:
        raise last_exc
    raise RuntimeError(f"{log_tag}_no_provider_available (no configured API key)" if not tried_any else f"{log_tag}_all_providers_failed")


# ---------------------------------------------------------------------------
# Per-provider runners — forced single tool-use → (arguments dict | None, stop).
# ---------------------------------------------------------------------------
async def _run_anthropic(
    *, model: str, system: str, user: str, tool_name: str,
    tool_description: str, input_schema: dict, max_tokens: int,
) -> tuple[Optional[dict], object]:
    import anthropic  # lazy

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        tools=[{"name": tool_name, "description": tool_description, "input_schema": input_schema}],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user}],
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return (block.input or {}), response.stop_reason
    return None, response.stop_reason


async def _run_openai(
    *, model: str, system: str, user: str, tool_name: str,
    tool_description: str, input_schema: dict, max_tokens: int,
) -> tuple[Optional[dict], object]:
    import openai  # lazy

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=model,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=[{
            "type": "function",
            "function": {"name": tool_name, "description": tool_description, "parameters": input_schema},
        }],
        tool_choice={"type": "function", "function": {"name": tool_name}},
    )
    choice = response.choices[0]
    calls = choice.message.tool_calls or []
    if not calls or calls[0].function.name != tool_name:
        return None, choice.finish_reason
    try:
        return json.loads(calls[0].function.arguments), choice.finish_reason
    except (ValueError, TypeError):
        return None, choice.finish_reason


async def _run_gemini(
    *, model: str, system: str, user: str, tool_name: str,
    tool_description: str, input_schema: dict, max_tokens: int,
) -> tuple[Optional[dict], object]:
    body = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "tools": [{"function_declarations": [{
            "name": tool_name, "description": tool_description,
            "parameters": _to_gemini_schema(input_schema),
        }]}],
        "tool_config": {"function_calling_config": {"mode": "ANY", "allowed_function_names": [tool_name]}},
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        body["system_instruction"] = {"parts": [{"text": system}]}
    data = await _gemini_post(model, body)
    return _gemini_function_args(data, tool_name), _gemini_finish(data)


# ---------------------------------------------------------------------------
# Per-provider runners — plain text completion → str.
# ---------------------------------------------------------------------------
async def _run_anthropic_text(*, model: str, system: str, user: str, max_tokens: int) -> str:
    import anthropic  # lazy

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": user}]}
    if system:
        kwargs["system"] = system
    resp = await client.messages.create(**kwargs)
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


async def _run_openai_text(*, model: str, system: str, user: str, max_tokens: int) -> str:
    import openai  # lazy

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    resp = await client.chat.completions.create(model=model, max_completion_tokens=max_tokens, messages=messages)
    return (resp.choices[0].message.content or "").strip()


async def _run_gemini_text(*, model: str, system: str, user: str, max_tokens: int) -> str:
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        body["system_instruction"] = {"parts": [{"text": system}]}
    data = await _gemini_post(model, body)
    return _gemini_text(data)


# ---------------------------------------------------------------------------
# Sync per-provider runners (for the handful of sync call sites).
# ---------------------------------------------------------------------------
def _run_anthropic_sync(
    *, model: str, system: str, user: str, tool_name: str,
    tool_description: str, input_schema: dict, max_tokens: int,
) -> tuple[Optional[dict], object]:
    import anthropic  # lazy

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        tools=[{"name": tool_name, "description": tool_description, "input_schema": input_schema}],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user}],
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return (block.input or {}), response.stop_reason
    return None, response.stop_reason


def _run_openai_sync(
    *, model: str, system: str, user: str, tool_name: str,
    tool_description: str, input_schema: dict, max_tokens: int,
) -> tuple[Optional[dict], object]:
    import openai  # lazy

    client = openai.OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=model,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=[{
            "type": "function",
            "function": {"name": tool_name, "description": tool_description, "parameters": input_schema},
        }],
        tool_choice={"type": "function", "function": {"name": tool_name}},
    )
    choice = response.choices[0]
    calls = choice.message.tool_calls or []
    if not calls or calls[0].function.name != tool_name:
        return None, choice.finish_reason
    try:
        return json.loads(calls[0].function.arguments), choice.finish_reason
    except (ValueError, TypeError):
        return None, choice.finish_reason


def _run_gemini_sync(
    *, model: str, system: str, user: str, tool_name: str,
    tool_description: str, input_schema: dict, max_tokens: int,
) -> tuple[Optional[dict], object]:
    body = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "tools": [{"function_declarations": [{
            "name": tool_name, "description": tool_description,
            "parameters": _to_gemini_schema(input_schema),
        }]}],
        "tool_config": {"function_calling_config": {"mode": "ANY", "allowed_function_names": [tool_name]}},
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        body["system_instruction"] = {"parts": [{"text": system}]}
    data = _gemini_post_sync(model, body)
    return _gemini_function_args(data, tool_name), _gemini_finish(data)


def _run_anthropic_text_sync(*, model: str, system: str, user: str, max_tokens: int) -> str:
    import anthropic  # lazy

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": user}]}
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


def _run_openai_text_sync(*, model: str, system: str, user: str, max_tokens: int) -> str:
    import openai  # lazy

    client = openai.OpenAI(api_key=settings.openai_api_key)
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    resp = client.chat.completions.create(model=model, max_completion_tokens=max_tokens, messages=messages)
    return (resp.choices[0].message.content or "").strip()


def _run_gemini_text_sync(*, model: str, system: str, user: str, max_tokens: int) -> str:
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        body["system_instruction"] = {"parts": [{"text": system}]}
    data = _gemini_post_sync(model, body)
    return _gemini_text(data)


# ---------------------------------------------------------------------------
# Gemini REST helpers (no SDK dependency — mirrors services/brand_scan.py).
# ---------------------------------------------------------------------------
def _gemini_endpoint(model: str) -> str:
    return (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={settings.gemini_api_key}"
    )


async def _gemini_post(model: str, body: dict) -> dict:
    import httpx  # lazy

    async with httpx.AsyncClient(timeout=90) as http:
        resp = await http.post(_gemini_endpoint(model), json=body)
    resp.raise_for_status()  # 429/5xx → httpx.HTTPStatusError → treated as transient
    return resp.json()


def _gemini_post_sync(model: str, body: dict) -> dict:
    import httpx  # lazy

    with httpx.Client(timeout=90) as http:
        resp = http.post(_gemini_endpoint(model), json=body)
    resp.raise_for_status()
    return resp.json()


def _gemini_text(data: dict) -> str:
    cands = data.get("candidates") or []
    if not cands:
        return ""
    parts = (cands[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()


def _gemini_function_args(data: dict, tool_name: str) -> Optional[dict]:
    cands = data.get("candidates") or []
    if not cands:
        return None
    parts = (cands[0].get("content") or {}).get("parts") or []
    for p in parts:
        if not isinstance(p, dict):
            continue
        fc = p.get("functionCall") or p.get("function_call")
        if fc and (not tool_name or fc.get("name") == tool_name):
            return fc.get("args") or {}
    return None


def _gemini_finish(data: dict) -> object:
    cands = data.get("candidates") or []
    return cands[0].get("finishReason") if cands else None


_GEMINI_TYPES = {
    "string": "STRING", "integer": "INTEGER", "number": "NUMBER",
    "boolean": "BOOLEAN", "array": "ARRAY", "object": "OBJECT", "null": "STRING",
}
_GEMINI_DROP_KEYS = {"additionalProperties", "$schema", "title", "default", "examples", "$ref", "definitions"}


def _to_gemini_schema(schema):
    """Best-effort JSON-Schema → Gemini function-declaration Schema: uppercase
    the OpenAPI `type` enum, recurse into properties/items, and drop keys the
    Gemini schema doesn't accept. Gemini is the last-ditch fallback, so an
    imperfect transform on an exotic schema simply fails that provider (the
    overall call then raises — the same as having no fallback at all)."""
    if not isinstance(schema, dict):
        return schema
    out: dict = {}
    for k, v in schema.items():
        if k in _GEMINI_DROP_KEYS:
            continue
        if k == "type":
            if isinstance(v, list):  # e.g. ["string", "null"] → the non-null type
                v = next((t for t in v if t != "null"), "string")
            out["type"] = _GEMINI_TYPES.get(v, str(v).upper())
        elif k == "properties" and isinstance(v, dict):
            out["properties"] = {pk: _to_gemini_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out["items"] = _to_gemini_schema(v)
        elif isinstance(v, dict):
            out[k] = _to_gemini_schema(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Public entrypoints.
# ---------------------------------------------------------------------------
async def run_forced_tool(
    *,
    provider: str = "anthropic",
    model: str,
    system: str,
    user: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
    max_tokens: int,
    fallback_models: Optional[dict] = None,
    log_tag: str = "forced_tool",
) -> dict:
    """One forced tool call on `provider`, falling back to the configured
    providers on a transient failure. Returns the tool arguments dict. Raises
    RuntimeError('report_no_tool_use ...') only when NO provider emitted the tool
    (the caller decides whether that's retryable)."""
    async def call(p: str, m: str):
        runner = {"openai": _run_openai, "gemini": _run_gemini}.get(p, _run_anthropic)
        out, _stop = await runner(
            model=m, system=system, user=user, tool_name=tool_name,
            tool_description=tool_description, input_schema=input_schema, max_tokens=max_tokens,
        )
        return out

    return await _chain_async(
        primary=provider, primary_model=model, fallback_models=fallback_models, log_tag=log_tag,
        call=call, empty_check=lambda out: out is None,
        empty_detail=lambda p: f"report_no_tool_use (provider={p})",
    )


def run_forced_tool_sync(
    *,
    provider: str = "anthropic",
    model: str,
    system: str,
    user: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
    max_tokens: int,
    fallback_models: Optional[dict] = None,
    log_tag: str = "forced_tool",
) -> dict:
    """Synchronous twin of :func:`run_forced_tool`."""
    def call(p: str, m: str):
        runner = {"openai": _run_openai_sync, "gemini": _run_gemini_sync}.get(p, _run_anthropic_sync)
        out, _stop = runner(
            model=m, system=system, user=user, tool_name=tool_name,
            tool_description=tool_description, input_schema=input_schema, max_tokens=max_tokens,
        )
        return out

    return _chain_sync(
        primary=provider, primary_model=model, fallback_models=fallback_models, log_tag=log_tag,
        call=call, empty_check=lambda out: out is None,
        empty_detail=lambda p: f"report_no_tool_use (provider={p})",
    )


async def generate_text(
    *,
    user: str,
    max_tokens: int,
    system: str = "",
    provider: str = "anthropic",
    model: Optional[str] = None,
    fallback_models: Optional[dict] = None,
    log_tag: str = "llm_text",
) -> str:
    """One plain completion on `provider`, falling back to the configured
    providers on a transient failure. Returns the response text (raises when
    every provider fails or all returned empty text)."""
    async def call(p: str, m: str):
        runner = {"openai": _run_openai_text, "gemini": _run_gemini_text}.get(p, _run_anthropic_text)
        return await runner(model=m, system=system, user=user, max_tokens=max_tokens)

    return await _chain_async(
        primary=provider, primary_model=model, fallback_models=fallback_models, log_tag=log_tag,
        call=call, empty_check=lambda s: not (s or "").strip(),
        empty_detail=lambda p: f"{log_tag}_empty_text (provider={p})",
    )


def generate_text_sync(
    *,
    user: str,
    max_tokens: int,
    system: str = "",
    provider: str = "anthropic",
    model: Optional[str] = None,
    fallback_models: Optional[dict] = None,
    log_tag: str = "llm_text",
) -> str:
    """Synchronous twin of :func:`generate_text`."""
    def call(p: str, m: str):
        runner = {"openai": _run_openai_text_sync, "gemini": _run_gemini_text_sync}.get(p, _run_anthropic_text_sync)
        return runner(model=m, system=system, user=user, max_tokens=max_tokens)

    return _chain_sync(
        primary=provider, primary_model=model, fallback_models=fallback_models, log_tag=log_tag,
        call=call, empty_check=lambda s: not (s or "").strip(),
        empty_detail=lambda p: f"{log_tag}_empty_text (provider={p})",
    )
