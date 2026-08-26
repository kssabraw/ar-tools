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
    client = af.FailoverAsyncAnthropic(keys=["a", "b"], max_retries=5)
    assert built == ["a", "b"]  # one underlying client per account key
    out = _run(client.messages.create(model="m"))
    assert out["ok"] is True
