"""Second-Anthropic-account **failover** for direct Anthropic call sites.

The suite already has cross-*provider* fallback (Anthropic → OpenAI → Gemini) in
``services/report_llm.py`` for the non-agentic single-shot calls. This module adds
the *other* axis the owner asked for: a **second Anthropic account** (its own API
key, same Claude models) that a call fails over to when the primary account hits a
*transient* concurrency/rate limit (429) or 5xx overload that outlasts its
per-key retry budget. Because the model is identical, output quality is unchanged
— this is pure capacity headroom, distinct from the model-swapping provider chain.

Two seams, matching the two shapes of Anthropic call in the codebase:

* :class:`FailoverAsyncAnthropic` — a drop-in for the many single-call sites that
  do ``client = anthropic.AsyncAnthropic(...)`` then ``await client.messages.create(...)``.
  Swapping the constructor is the whole change; the ``.messages.create`` call
  stays byte-identical and now fails over across accounts.
* :func:`call_failover` — for the agentic tool-use loops (Slack/SerMastr,
  strategist, PACE) that build one client and reuse it across a stateful,
  streaming, multi-round loop. Wrap each model-call invocation (a whole
  ``_create_with_continuation`` / ``messages.create`` / ``messages.stream``
  consumption) so a transient failure on the primary account re-runs that one
  round on the secondary account. Each round is idempotent — tool side-effects
  run only *after* a successful response — so re-issuing a failed round is safe.

Everything is a no-op when ``anthropic_api_key_secondary`` is unset (the client
list is just the primary), so it is safe to leave enabled everywhere. Transient
classification and backoff are reused from ``report_llm`` so "what counts as
retryable" is defined once for the whole suite.

Streaming caveat: a transient limit almost always trips at stream *open* (before
any tokens), so a re-run on the second key re-opens cleanly. In the rare case a
stream dies mid-emit, a re-run re-emits from the start — which is strictly better
than today's hard failure, and the only realistic exposure is a duplicated
partial token burst on an SSE surface.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from config import settings
from services.report_llm import anthropic_account_keys, is_transient_llm_error, retry_transient

logger = logging.getLogger(__name__)


def _client_keys() -> list[str]:
    """Account keys to build clients for, in failover order. The primary slot is
    ALWAYS kept (even when its value is empty) so the client list is never empty
    and construction mirrors the old ``AsyncAnthropic(api_key=settings.anthropic_api_key)``
    exactly — a call site that used to build one client still builds one. The
    secondary account is appended only when failover is enabled and its key is
    set and distinct."""
    return anthropic_account_keys(
        settings.anthropic_api_key,
        settings.anthropic_api_key_secondary,
        getattr(settings, "anthropic_api_keys", ""),
        settings.anthropic_key_failover_enabled,
    )


def anthropic_keys() -> list[str]:
    """The non-empty account keys among :func:`_client_keys` (primary first).
    Used for reporting whether a real secondary account exists — distinct from
    the client-build list, which always keeps the primary slot."""
    return [k for k in _client_keys() if k]


def has_secondary_key() -> bool:
    """True when a distinct, enabled secondary account key is configured."""
    return len(anthropic_keys()) > 1


def build_async_clients(**client_kwargs):
    """One ``anthropic.AsyncAnthropic`` per account key (:func:`_client_keys`), in
    failover order. ``client_kwargs`` (timeout, max_retries, …) apply to every
    client, so each site keeps its own transport tuning. Never empty — returns a
    single primary client when no secondary key is configured."""
    import anthropic  # lazy — keep import cost off module load

    return [anthropic.AsyncAnthropic(api_key=key, **client_kwargs) for key in _client_keys()]


async def call_failover(
    clients: list,
    make_awaitable: Callable[[object], Awaitable],
    *,
    log_tag: str = "anthropic",
):
    """Run ``await make_awaitable(client)`` against each account's client in
    order, switching accounts only on a *transient* failure that outlasts that
    account's retry budget. A non-transient error (bad request, auth, missing
    tool block raised by the caller) surfaces immediately — real bugs aren't
    masked. Raises the last transient failure when every account is exhausted.

    ``make_awaitable`` must return a *fresh* awaitable on each call (it is invoked
    per retry and per account), e.g. ``lambda c: c.messages.create(**kwargs)``.
    """
    if not clients:
        raise RuntimeError(f"{log_tag}_no_anthropic_key (no configured Anthropic API key)")

    last_exc: Optional[Exception] = None
    for idx, client in enumerate(clients):
        try:
            return await retry_transient(
                lambda c=client: make_awaitable(c),
                max_retries=settings.anthropic_key_failover_max_retries,
                log_tag=f"{log_tag}:acct{idx + 1}",
            )
        except Exception as exc:  # noqa: BLE001 — classify: switch account only on transient
            if is_transient_llm_error(exc) and idx < len(clients) - 1:
                last_exc = exc
                logger.warning(
                    "anthropic_key_failover_switch",
                    extra={"log_tag": log_tag, "from_account": idx + 1, "error": str(exc)[:200]},
                )
                continue
            raise
        finally:
            pass
    # Unreachable unless the last account also raised transiently.
    raise last_exc  # type: ignore[misc]


class _MessagesNamespace:
    """Mimics ``client.messages`` for the surface the direct sites use."""

    def __init__(self, clients: list, log_tag: str):
        self._clients = clients
        self._log_tag = log_tag

    async def create(self, **kwargs):
        return await call_failover(
            self._clients,
            lambda c: c.messages.create(**kwargs),
            log_tag=f"{self._log_tag}.create",
        )


class FailoverAsyncAnthropic:
    """Drop-in replacement for ``anthropic.AsyncAnthropic`` that transparently
    fails an ``await client.messages.create(...)`` over to the secondary account
    on a transient limit. Constructed with the same kwargs (``api_key`` is
    ignored — the account keys come from config); only the non-streaming
    ``messages.create`` path is wrapped, which is the only shape the direct sites
    use. Streaming loops use :func:`call_failover` directly instead."""

    def __init__(self, *, log_tag: str = "messages", **client_kwargs):
        client_kwargs.pop("api_key", None)  # keys are config-owned; ignore any passed
        self._clients = build_async_clients(**client_kwargs)
        self.messages = _MessagesNamespace(self._clients, log_tag)
