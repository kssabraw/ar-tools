"""Second-Anthropic-account failover for the nlp service.

``main.py`` builds an ``AsyncAnthropic`` per generation/scoring call and relies on
the SDK's own ``max_retries`` for transient 429/5xx recovery on ONE account. This
module adds a second account (its own API key, same Claude models): when the
primary account's SDK retries can't clear a transient concurrency/rate limit, the
same non-streaming ``messages.create`` is retried on the secondary account. Pure
capacity headroom — the model is identical, so scores/output are unchanged.

Kept as a small sibling module (like ``blog_structure``/``ecommerce_facts``) so
the logic is unit-testable without importing the 9k-line ``main`` and its heavy
dependency chain. ``main._anthropic_client`` delegates here, so every call site
keeps its shape and only its constructor name changed.

Config (env on the ``nlp`` service): ``ANTHROPIC_API_KEY`` (primary),
``ANTHROPIC_API_KEY_SECONDARY`` (empty ⇒ primary only), and
``ANTHROPIC_KEY_FAILOVER_ENABLED`` (default true).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def account_keys(primary: str, secondary: str, enabled: bool) -> list[str]:
    """Account keys to build clients for, primary first. The primary slot is
    ALWAYS kept (so a call site that built one client still builds one); the
    secondary is appended only when failover is enabled and its key is set +
    distinct."""
    keys = [primary]
    if enabled and secondary and secondary != primary:
        keys.append(secondary)
    return keys


def env_keys() -> list[str]:
    """The account keys resolved from the process environment (read lazily so a
    test — or a runtime env change — is honoured)."""
    return account_keys(
        os.environ.get("ANTHROPIC_API_KEY", ""),
        os.environ.get("ANTHROPIC_API_KEY_SECONDARY", ""),
        os.environ.get("ANTHROPIC_KEY_FAILOVER_ENABLED", "true").lower() != "false",
    )


def is_transient(exc: Exception) -> bool:
    """Retryable Anthropic failures worth failing an account over: 429 rate/
    concurrency, 5xx/529 overload, connection drops. Auth/bad-request fail fast."""
    import anthropic

    if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        code = getattr(exc, "status_code", 0) or 0
        return code == 429 or code >= 500
    return False


class _MessagesFailover:
    """Mimics ``client.messages`` — the only surface this service uses (all calls
    are non-streaming ``create``). Retries on the next account on a transient
    limit the current account's SDK retries couldn't clear."""

    def __init__(self, clients: list):
        self._clients = clients

    async def create(self, **kwargs):
        last_exc = None
        for idx, client in enumerate(self._clients):
            try:
                return await client.messages.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 — switch account only on transient
                if is_transient(exc) and idx < len(self._clients) - 1:
                    last_exc = exc
                    logger.warning(
                        "anthropic_account_failover from account %s: %s", idx + 1, str(exc)[:200]
                    )
                    continue
                raise
        raise last_exc  # every account exhausted transiently


class FailoverAsyncAnthropic:
    """Drop-in for ``AsyncAnthropic`` exposing ``.messages.create`` with
    second-account failover. Construction mirrors the SDK (``api_key`` ignored —
    account keys come from the environment) so call sites change only the
    constructor name. ``keys`` is injectable for tests."""

    def __init__(self, *, api_key=None, keys: list | None = None, **client_kwargs):
        import anthropic

        resolved = keys if keys is not None else env_keys()
        self.messages = _MessagesFailover(
            [anthropic.AsyncAnthropic(api_key=key, **client_kwargs) for key in resolved]
        )


def client(**client_kwargs) -> FailoverAsyncAnthropic:
    """Build a failover-capable async Anthropic client. ``client_kwargs``
    (max_retries, timeout, …) apply to every account's underlying SDK client."""
    return FailoverAsyncAnthropic(**client_kwargs)
