"""Multi-account Anthropic **failover + rotation** for the nlp service.

``main.py`` builds an ``AsyncAnthropic`` per generation/scoring call and relies on
the SDK's own ``max_retries`` for transient 429/5xx recovery on ONE account. This
module adds a **pool** of accounts (each its own API key, same Claude models):

* **Failover** — when the current account's SDK retries can't clear a transient
  concurrency/rate limit, the same non-streaming ``messages.create`` is retried
  on the next account in the pool. Pure capacity headroom — the model is
  identical, so scores/output are unchanged.
* **Rotation (2026-09-02)** — failover alone never adds throughput: a saturated
  primary burns its whole backoff before the second account sees a request. So
  each incoming HTTP request is stamped with a rotation *slot* (see
  ``begin_request_slot`` + the ASGI middleware in ``main.py``) and every client
  built during that request starts the pool at that slot. **Sticky per request,
  spread across requests**: one page generation keeps every call on one
  account (its cached generation prompt stays warm — prompt caches are per
  account), while successive page generations divide a batch's concurrent load
  across the pool from the first request instead of after a backoff.
* **429 diagnostics** — the ``anthropic-ratelimit-*`` / ``retry-after`` headers
  are logged whenever an account is failed over or exhausted, so the limit
  that actually binds (output tokens/min, requests/min, …) is visible in the
  service logs and the pool can be sized from measurement, not guesswork.

Kept as a small sibling module (like ``blog_structure``/``ecommerce_facts``) so
the logic is unit-testable without importing the 9k-line ``main`` and its heavy
dependency chain. ``main._anthropic_client`` delegates here, so every call site
keeps its shape and only its constructor name changed.

Config (env on the ``nlp`` service):
``ANTHROPIC_API_KEY`` (primary, always slot 0),
``ANTHROPIC_API_KEYS`` (comma-separated pool of further account keys, any
length — the canonical form), ``ANTHROPIC_API_KEY_SECONDARY`` (the original
two-account form, still honoured and merged into the pool),
``ANTHROPIC_KEY_FAILOVER_ENABLED`` (default true; false ⇒ primary only) and
``ANTHROPIC_KEY_ROTATION_ENABLED`` (default true; false ⇒ every request starts
at the primary, i.e. reactive failover only — the pre-2026-09-02 behaviour).
"""

from __future__ import annotations

import contextvars
import itertools
import logging
import os

logger = logging.getLogger(__name__)

# Response headers worth logging on a rate limit: the per-limit remaining/limit/
# reset triplets plus Retry-After. Matched case-insensitively by prefix.
RATELIMIT_HEADER_PREFIX = "anthropic-ratelimit-"


# ── key resolution ───────────────────────────────────────────────────────────
def parse_pool(raw: str | None) -> list[str]:
    """Comma-separated key list → ordered, de-duplicated, whitespace-stripped.
    Pure."""
    out: list[str] = []
    for part in (raw or "").split(","):
        key = part.strip()
        if key and key not in out:
            out.append(key)
    return out


def account_keys(primary: str, secondary: str, enabled: bool, pool: str | None = "") -> list[str]:
    """Account keys to build clients for, primary first. The primary slot is
    ALWAYS kept (so a call site that built one client still builds one); the
    pool keys and the legacy secondary are appended, de-duplicated, only when
    failover is enabled. Pure."""
    keys = [primary]
    if not enabled:
        return keys
    for key in [*parse_pool(pool), secondary]:
        if key and key not in keys:
            keys.append(key)
    return keys


def env_keys() -> list[str]:
    """The account keys resolved from the process environment (read lazily so a
    test — or a runtime env change — is honoured)."""
    return account_keys(
        os.environ.get("ANTHROPIC_API_KEY", ""),
        os.environ.get("ANTHROPIC_API_KEY_SECONDARY", ""),
        os.environ.get("ANTHROPIC_KEY_FAILOVER_ENABLED", "true").lower() != "false",
        pool=os.environ.get("ANTHROPIC_API_KEYS", ""),
    )


# ── per-request rotation ─────────────────────────────────────────────────────
_request_slot: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "anthropic_account_slot", default=None
)
_slot_counter = itertools.count()


def begin_request_slot() -> int:
    """Stamp the current context (one HTTP request, in the ASGI middleware) with
    the next rotation slot. Every client built in this context starts the pool
    at that slot, so all of a request's calls share one account."""
    slot = next(_slot_counter)
    _request_slot.set(slot)
    return slot


def current_slot() -> int | None:
    return _request_slot.get()


def rotation_enabled() -> bool:
    return os.environ.get("ANTHROPIC_KEY_ROTATION_ENABLED", "true").lower() != "false"


def rotate(keys: list[str], slot: int | None) -> list[str]:
    """Rotate the pool so index ``slot % len`` comes first; failover order
    continues round the pool. No slot (a call outside any request) or a
    single-key pool ⇒ unchanged. Pure."""
    keys = list(keys)
    if slot is None or len(keys) < 2:
        return keys
    i = slot % len(keys)
    return keys[i:] + keys[:i]


def ordered_keys(keys: list[str] | None = None) -> list[str]:
    """The pool in the order THIS context should try it: env keys (or the
    injected ``keys``) rotated to the request's slot when rotation is on."""
    resolved = list(keys) if keys is not None else env_keys()
    return rotate(resolved, current_slot()) if rotation_enabled() else resolved


# ── transient classification + diagnostics ───────────────────────────────────
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


def ratelimit_headers(exc: Exception) -> dict[str, str]:
    """The ``anthropic-ratelimit-*`` + ``retry-after`` headers carried by an SDK
    status error (``exc.response.headers``), lower-cased. Empty when the error
    has no response (a connection drop) or the headers can't be read. Pure."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return {}
    try:
        items = list(headers.items())
    except Exception:  # noqa: BLE001 — diagnostics must never raise
        return {}
    out: dict[str, str] = {}
    for key, value in items:
        lower = str(key).lower()
        if lower.startswith(RATELIMIT_HEADER_PREFIX) or lower == "retry-after":
            out[lower] = str(value)
    return out


# ── the client ───────────────────────────────────────────────────────────────
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
                if not is_transient(exc):
                    raise
                headers = ratelimit_headers(exc)
                if idx < len(self._clients) - 1:
                    last_exc = exc
                    logger.warning(
                        "anthropic_account_failover from account %s of %s: %s ratelimit=%s",
                        idx + 1, len(self._clients), str(exc)[:200], headers,
                    )
                    continue
                logger.warning(
                    "anthropic_account_exhausted (%s of %s tried): %s ratelimit=%s",
                    idx + 1, len(self._clients), str(exc)[:200], headers,
                )
                raise
        raise last_exc  # unreachable: the last account re-raises above


class FailoverAsyncAnthropic:
    """Drop-in for ``AsyncAnthropic`` exposing ``.messages.create`` with
    multi-account failover. Construction mirrors the SDK (``api_key`` ignored —
    account keys come from the environment) so call sites change only the
    constructor name. ``keys`` is injectable for tests. The pool is rotated to
    the current request's slot (see ``ordered_keys``)."""

    def __init__(self, *, api_key=None, keys: list | None = None, **client_kwargs):
        import anthropic

        self.keys = ordered_keys(keys)
        self.messages = _MessagesFailover(
            [anthropic.AsyncAnthropic(api_key=key, **client_kwargs) for key in self.keys]
        )


def client(**client_kwargs) -> FailoverAsyncAnthropic:
    """Build a failover-capable async Anthropic client. ``client_kwargs``
    (max_retries, timeout, …) apply to every account's underlying SDK client."""
    return FailoverAsyncAnthropic(**client_kwargs)
