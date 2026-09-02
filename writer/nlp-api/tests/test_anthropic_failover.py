"""Unit tests for the second-Anthropic-account failover (anthropic_failover.py).

Pure + offline — no network. Fake message clients stand in for AsyncAnthropic,
and async paths are driven on an isolated event loop (no pytest-asyncio dependency,
and the process-global loop is left untouched so sibling suites that use
asyncio.get_event_loop() are unaffected). Run with `python -m pytest writer/nlp-api/tests/`.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic  # noqa: E402
import pytest  # noqa: E402

import anthropic_failover as af  # noqa: E402


def _run(coro):
    """Drive a coroutine on a dedicated loop, leaving the process-global event
    loop untouched (asyncio.run resets it to None, which would break sibling
    suites that use asyncio.get_event_loop())."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _rate_limit() -> Exception:
    return anthropic.RateLimitError.__new__(anthropic.RateLimitError)


def _status(code: int) -> Exception:
    exc = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
    exc.status_code = code
    return exc


class _FakeMessages:
    def __init__(self, fail_transient: bool):
        self.fail_transient = fail_transient
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.fail_transient:
            raise _rate_limit()
        return {"ok": True, "kwargs": kwargs}


class _FakeClient:
    def __init__(self, messages):
        self.messages = messages


# ── key resolution ───────────────────────────────────────────────────────────
def test_account_keys():
    assert af.account_keys("a", "", True) == ["a"]          # no secondary
    assert af.account_keys("a", "b", True) == ["a", "b"]    # distinct secondary
    assert af.account_keys("a", "b", False) == ["a"]        # disabled
    assert af.account_keys("a", "a", True) == ["a"]         # duplicate deduped


def test_env_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.delenv("ANTHROPIC_API_KEY_SECONDARY", raising=False)
    monkeypatch.setenv("ANTHROPIC_KEY_FAILOVER_ENABLED", "true")
    assert af.env_keys() == ["a"]
    monkeypatch.setenv("ANTHROPIC_API_KEY_SECONDARY", "b")
    assert af.env_keys() == ["a", "b"]
    monkeypatch.setenv("ANTHROPIC_KEY_FAILOVER_ENABLED", "false")
    assert af.env_keys() == ["a"]


# ── transient classification ─────────────────────────────────────────────────
def test_is_transient():
    assert af.is_transient(_rate_limit())
    assert af.is_transient(_status(429))
    assert af.is_transient(_status(503))
    assert af.is_transient(anthropic.APIConnectionError.__new__(anthropic.APIConnectionError))
    assert not af.is_transient(_status(400))
    assert not af.is_transient(_status(401))
    assert not af.is_transient(ValueError("boom"))


# ── create() failover ────────────────────────────────────────────────────────
def test_failover_switches_account_on_transient():
    primary = _FakeMessages(fail_transient=True)
    secondary = _FakeMessages(fail_transient=False)
    mf = af._MessagesFailover([_FakeClient(primary), _FakeClient(secondary)])
    out = _run(mf.create(model="m"))
    assert out["ok"] is True
    assert primary.calls == 1    # primary raised
    assert secondary.calls == 1  # secondary served it


def test_no_failover_when_first_account_succeeds():
    primary = _FakeMessages(fail_transient=False)
    secondary = _FakeMessages(fail_transient=False)
    mf = af._MessagesFailover([_FakeClient(primary), _FakeClient(secondary)])
    _run(mf.create(model="m"))
    assert primary.calls == 1
    assert secondary.calls == 0


def test_terminal_error_does_not_fail_over():
    class _Terminal:
        def __init__(self):
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            raise _status(400)

    primary = _Terminal()
    secondary = _FakeMessages(fail_transient=False)
    mf = af._MessagesFailover([_FakeClient(primary), _FakeClient(secondary)])
    with pytest.raises(anthropic.APIStatusError):
        _run(mf.create(model="m"))
    assert primary.calls == 1
    assert secondary.calls == 0  # a real error surfaces immediately


def test_both_accounts_exhausted_raises_last():
    primary = _FakeMessages(fail_transient=True)
    secondary = _FakeMessages(fail_transient=True)
    mf = af._MessagesFailover([_FakeClient(primary), _FakeClient(secondary)])
    with pytest.raises(anthropic.RateLimitError):
        _run(mf.create(model="m"))
    assert primary.calls == 1
    assert secondary.calls == 1


def test_single_account_reraises():
    primary = _FakeMessages(fail_transient=True)
    mf = af._MessagesFailover([_FakeClient(primary)])
    with pytest.raises(anthropic.RateLimitError):
        _run(mf.create(model="m"))
    assert primary.calls == 1


# ── FailoverAsyncAnthropic wiring (keys injected; no real network) ────────────
def test_failover_client_builds_one_client_per_key(monkeypatch):
    built = []

    class _FakeAsyncAnthropic:
        def __init__(self, api_key=None, **kwargs):
            built.append(api_key)
            self.messages = _FakeMessages(fail_transient=False)

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeAsyncAnthropic)
    af.clear_client_cache()
    client = af.FailoverAsyncAnthropic(keys=["a", "b"], max_retries=5)
    assert built == ["a", "b"]  # one underlying client per account key
    af.clear_client_cache()
    out = _run(client.messages.create(model="m"))
    assert out["ok"] is True


# ── key pool (2026-09-02) ────────────────────────────────────────────────────
def test_parse_pool_strips_dedupes_and_ignores_blanks():
    assert af.parse_pool("") == []
    assert af.parse_pool(None) == []
    assert af.parse_pool(" k1 , k2,,k1 , ") == ["k1", "k2"]


def test_account_keys_merges_pool_and_legacy_secondary():
    # primary first, pool next, legacy secondary last, all de-duplicated
    assert af.account_keys("a", "b", True, pool="c,d") == ["a", "c", "d", "b"]
    assert af.account_keys("a", "c", True, pool="c,a") == ["a", "c"]
    # disabled ⇒ primary only, whatever else is set
    assert af.account_keys("a", "b", False, pool="c") == ["a"]
    # the primary slot is always kept, even when empty
    assert af.account_keys("", "b", True, pool="c") == ["", "c", "b"]


def test_env_keys_reads_pool(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("ANTHROPIC_API_KEYS", "c, d")
    monkeypatch.setenv("ANTHROPIC_API_KEY_SECONDARY", "b")
    monkeypatch.setenv("ANTHROPIC_KEY_FAILOVER_ENABLED", "true")
    assert af.env_keys() == ["a", "c", "d", "b"]


# ── per-request rotation ─────────────────────────────────────────────────────
def test_rotate_is_sticky_to_slot_and_wraps():
    keys = ["a", "b", "c"]
    assert af.rotate(keys, None) == ["a", "b", "c"]     # no slot ⇒ unchanged
    assert af.rotate(keys, 0) == ["a", "b", "c"]
    assert af.rotate(keys, 1) == ["b", "c", "a"]        # failover continues round
    assert af.rotate(keys, 2) == ["c", "a", "b"]
    assert af.rotate(keys, 4) == ["b", "c", "a"]        # wraps
    assert af.rotate(["a"], 7) == ["a"]                 # single key ⇒ unchanged
    assert af.rotate([], 3) == []


def test_ordered_keys_rotates_to_the_request_slot(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_KEY_ROTATION_ENABLED", "true")
    keys = ["a", "b", "c"]

    def in_fresh_context(fn):
        import contextvars
        return contextvars.copy_context().run(fn)

    # outside any request: no slot ⇒ the primary leads
    assert in_fresh_context(lambda: af.ordered_keys(keys)) == ["a", "b", "c"]

    # successive requests get successive slots; each request is sticky
    def one_request():
        af.begin_request_slot()
        first = af.ordered_keys(keys)
        second = af.ordered_keys(keys)  # a second client in the same request
        assert first == second
        return first

    seen = [in_fresh_context(one_request) for _ in range(3)]
    # three consecutive requests start on three different accounts
    assert {order[0] for order in seen} == {"a", "b", "c"}


def test_ordered_keys_rotation_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_KEY_ROTATION_ENABLED", "false")
    import contextvars

    def one_request():
        af.begin_request_slot(); af.begin_request_slot()  # slot ≥ 1
        return af.ordered_keys(["a", "b"])

    assert contextvars.copy_context().run(one_request) == ["a", "b"]


def test_client_uses_rotated_keys(monkeypatch):
    """FailoverAsyncAnthropic builds its per-account clients in rotated order."""
    import contextvars
    monkeypatch.setenv("ANTHROPIC_KEY_ROTATION_ENABLED", "true")
    built = []

    class _Stub:
        def __init__(self, *, api_key=None, **kw):
            built.append(api_key)
            self.messages = _FakeMessages(fail_transient=False)

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _Stub)
    af.clear_client_cache()

    def one_request():
        af.begin_request_slot()
        return af.FailoverAsyncAnthropic(keys=["a", "b", "c"]).keys

    orders = [contextvars.copy_context().run(one_request) for _ in range(3)]
    assert {o[0] for o in orders} == {"a", "b", "c"}
    assert sorted(built) == ["a", "b", "c"]  # cached: one SDK client per key, not per construction
    af.clear_client_cache()


# ── 429 diagnostics ──────────────────────────────────────────────────────────
class _Headers(dict):
    pass


def test_ratelimit_headers_extracts_only_limit_headers():
    exc = _status(429)
    exc.response = type("R", (), {})()
    exc.response.headers = _Headers({
        "Anthropic-RateLimit-Output-Tokens-Remaining": "0",
        "anthropic-ratelimit-output-tokens-limit": "80000",
        "Retry-After": "12",
        "content-type": "application/json",
    })
    assert af.ratelimit_headers(exc) == {
        "anthropic-ratelimit-output-tokens-remaining": "0",
        "anthropic-ratelimit-output-tokens-limit": "80000",
        "retry-after": "12",
    }


def test_ratelimit_headers_tolerates_missing_response():
    assert af.ratelimit_headers(_rate_limit()) == {}
    assert af.ratelimit_headers(ValueError("x")) == {}


def test_failover_walks_a_three_account_pool():
    a = _FakeMessages(fail_transient=True)
    b = _FakeMessages(fail_transient=True)
    c = _FakeMessages(fail_transient=False)
    mf = af._MessagesFailover([_FakeClient(a), _FakeClient(b), _FakeClient(c)])
    out = _run(mf.create(model="m"))
    assert out["ok"] is True
    assert (a.calls, b.calls, c.calls) == (1, 1, 1)


def test_pool_exhausted_reraises_last_transient():
    a = _FakeMessages(fail_transient=True)
    b = _FakeMessages(fail_transient=True)
    mf = af._MessagesFailover([_FakeClient(a), _FakeClient(b)])
    with pytest.raises(anthropic.RateLimitError):
        _run(mf.create(model="m"))
    assert (a.calls, b.calls) == (1, 1)


# ── rotation only on generation paths (review fix) ───────────────────────────
def test_should_rotate_path_only_for_generation_routes():
    assert af.should_rotate_path("/generate-page")
    assert af.should_rotate_path("/reoptimize-page")
    assert af.should_rotate_path("/generate-ecommerce-page")
    assert af.should_rotate_path("/reoptimize-ecommerce-page")
    assert not af.should_rotate_path("/score-page")
    assert not af.should_rotate_path("/healthz")
    assert not af.should_rotate_path("/")
    assert not af.should_rotate_path("")
    assert not af.should_rotate_path(None)


# ── per-key client cache (review fix) ─────────────────────────────────────────
def test_sdk_clients_are_cached_per_key_and_kwargs(monkeypatch):
    built = []

    class _Stub:
        def __init__(self, *, api_key=None, **kw):
            built.append((api_key, kw.get("max_retries")))
            self.messages = _FakeMessages(fail_transient=False)

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _Stub)
    monkeypatch.setenv("ANTHROPIC_KEY_ROTATION_ENABLED", "false")
    af.clear_client_cache()
    c1 = af.FailoverAsyncAnthropic(keys=["a"], max_retries=5)
    c2 = af.FailoverAsyncAnthropic(keys=["a"], max_retries=5)
    assert built == [("a", 5)]                       # second construction reused the client
    assert c1.messages._clients[0] is c2.messages._clients[0]
    af.FailoverAsyncAnthropic(keys=["a"], max_retries=1)
    assert len(built) == 2                           # different transport kwargs ⇒ new client
    af.clear_client_cache()


# ── pool retry budget (review fix) ───────────────────────────────────────────
def test_effective_client_kwargs_clamps_retries_only_for_a_pool(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_POOL_MAX_RETRIES", "2")
    assert af.effective_client_kwargs({"max_retries": 5}, pool_size=1) == {"max_retries": 5}
    assert af.effective_client_kwargs({"max_retries": 5}, pool_size=3) == {"max_retries": 2}
    assert af.effective_client_kwargs({"max_retries": 1}, pool_size=3) == {"max_retries": 1}
    assert af.effective_client_kwargs({}, pool_size=3) == {}          # nothing to clamp
    monkeypatch.setenv("ANTHROPIC_POOL_MAX_RETRIES", "garbage")
    assert af.pool_max_retries() == 2


def test_pool_clients_get_the_clamped_retry_budget(monkeypatch):
    built = []

    class _Stub:
        def __init__(self, *, api_key=None, **kw):
            built.append(kw.get("max_retries"))
            self.messages = _FakeMessages(fail_transient=False)

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _Stub)
    monkeypatch.setenv("ANTHROPIC_KEY_ROTATION_ENABLED", "false")
    monkeypatch.setenv("ANTHROPIC_POOL_MAX_RETRIES", "2")
    af.clear_client_cache()
    af.FailoverAsyncAnthropic(keys=["a", "b"], max_retries=5)
    assert built == [2, 2]
    af.clear_client_cache()
    af.FailoverAsyncAnthropic(keys=["a"], max_retries=5)
    assert built[-1] == 5                            # single account keeps the full budget
    af.clear_client_cache()
