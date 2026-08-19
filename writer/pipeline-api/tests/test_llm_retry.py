"""Unit tests for the Claude transport retry in modules/brief/llm.py —
transient-error classification and the backoff loop around messages.create."""

from __future__ import annotations

import asyncio

import anthropic
import pytest

from config import settings
from modules.brief import llm


async def _no_sleep(_delay):
    return None


def _rate_limit_error() -> Exception:
    return anthropic.RateLimitError.__new__(anthropic.RateLimitError)


def _status_error(code: int) -> Exception:
    exc = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
    exc.status_code = code
    return exc


def test_is_transient_classifies():
    assert llm._is_transient_anthropic_error(_rate_limit_error())
    assert llm._is_transient_anthropic_error(
        anthropic.APIConnectionError.__new__(anthropic.APIConnectionError)
    )
    assert llm._is_transient_anthropic_error(_status_error(529))  # overloaded
    assert llm._is_transient_anthropic_error(_status_error(500))
    assert not llm._is_transient_anthropic_error(_status_error(400))
    assert not llm._is_transient_anthropic_error(_status_error(401))
    assert not llm._is_transient_anthropic_error(ValueError("boom"))


class _FlakyMessages:
    def __init__(self, failures: int, exc_factory):
        self.failures = failures
        self.exc_factory = exc_factory
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc_factory()
        return {"ok": True, "kwargs": kwargs}


class _FakeClient:
    def __init__(self, messages):
        self.messages = messages


def test_create_message_retries_429_then_succeeds(monkeypatch):
    messages = _FlakyMessages(failures=2, exc_factory=_rate_limit_error)
    monkeypatch.setattr(llm.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(settings, "anthropic_max_retries", 4)

    out = asyncio.run(llm._create_message(_FakeClient(messages), {"model": "m"}))
    assert out["ok"] is True
    assert messages.calls == 3  # failed twice, succeeded third


def test_create_message_gives_up_after_budget(monkeypatch):
    messages = _FlakyMessages(failures=99, exc_factory=_rate_limit_error)
    monkeypatch.setattr(llm.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(settings, "anthropic_max_retries", 2)

    with pytest.raises(anthropic.RateLimitError):
        asyncio.run(llm._create_message(_FakeClient(messages), {"model": "m"}))
    assert messages.calls == 3  # initial + 2 retries


def test_create_message_terminal_error_not_retried(monkeypatch):
    messages = _FlakyMessages(failures=99, exc_factory=lambda: _status_error(400))
    monkeypatch.setattr(llm.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(settings, "anthropic_max_retries", 4)

    with pytest.raises(anthropic.APIStatusError):
        asyncio.run(llm._create_message(_FakeClient(messages), {"model": "m"}))
    assert messages.calls == 1  # fail fast, no retries


# ── second Anthropic account failover ────────────────────────────────────────
def test_get_anthropic_secondary_resolution(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "a", raising=False)
    monkeypatch.setattr(settings, "anthropic_key_failover_enabled", True, raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key_secondary", "", raising=False)
    llm._anthropic_secondary = None
    assert llm.get_anthropic_secondary() is None  # no secondary configured
    monkeypatch.setattr(settings, "anthropic_api_key_secondary", "b", raising=False)
    llm._anthropic_secondary = None
    assert llm.get_anthropic_secondary() is not None  # distinct secondary → client
    monkeypatch.setattr(settings, "anthropic_key_failover_enabled", False, raising=False)
    llm._anthropic_secondary = None
    assert llm.get_anthropic_secondary() is None  # disabled
    monkeypatch.setattr(settings, "anthropic_key_failover_enabled", True, raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key_secondary", "a", raising=False)
    llm._anthropic_secondary = None
    assert llm.get_anthropic_secondary() is None  # identical to primary → skip
    llm._anthropic_secondary = None


def test_create_message_fails_over_to_second_account(monkeypatch):
    primary = _FlakyMessages(failures=99, exc_factory=_rate_limit_error)  # always 429
    secondary = _FlakyMessages(failures=0, exc_factory=_rate_limit_error)  # succeeds
    monkeypatch.setattr(llm.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(settings, "anthropic_max_retries", 2)
    monkeypatch.setattr(llm, "get_anthropic_secondary", lambda: _FakeClient(secondary))

    out = asyncio.run(llm._create_message(_FakeClient(primary), {"model": "m"}))
    assert out["ok"] is True
    assert primary.calls == 3    # initial + 2 retries on the primary account
    assert secondary.calls == 1  # then the second account served the call


def test_create_message_both_accounts_exhausted_raises(monkeypatch):
    primary = _FlakyMessages(failures=99, exc_factory=_rate_limit_error)
    secondary = _FlakyMessages(failures=99, exc_factory=_rate_limit_error)
    monkeypatch.setattr(llm.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(settings, "anthropic_max_retries", 1)
    monkeypatch.setattr(llm, "get_anthropic_secondary", lambda: _FakeClient(secondary))

    with pytest.raises(anthropic.RateLimitError):
        asyncio.run(llm._create_message(_FakeClient(primary), {"model": "m"}))
    assert primary.calls == 2    # initial + 1 retry
    assert secondary.calls == 2  # both accounts fully exhausted


def test_create_message_terminal_error_does_not_fail_over(monkeypatch):
    primary = _FlakyMessages(failures=99, exc_factory=lambda: _status_error(400))
    secondary = _FlakyMessages(failures=0, exc_factory=_rate_limit_error)
    monkeypatch.setattr(llm.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(llm, "get_anthropic_secondary", lambda: _FakeClient(secondary))

    with pytest.raises(anthropic.APIStatusError):
        asyncio.run(llm._create_message(_FakeClient(primary), {"model": "m"}))
    assert primary.calls == 1    # a real error surfaces immediately
    assert secondary.calls == 0  # no failover on a non-transient error
