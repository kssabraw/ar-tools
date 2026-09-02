"""Unit tests for the second-Anthropic-account failover primitive
(services/anthropic_failover.py). No real Anthropic client is ever built — the
per-call runner is a plain callable and `build_async_clients` is monkeypatched to
fakes. Backoff is neutralized via `anthropic_key_failover_max_retries = 0`."""

import httpx
import pytest

from config import settings
from services import anthropic_failover as af


def _transient() -> Exception:
    return httpx.HTTPStatusError(
        "rate limited",
        request=httpx.Request("POST", "http://x"),
        response=httpx.Response(429),
    )


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(af.settings, "anthropic_api_key", "a", raising=False)
    monkeypatch.setattr(af.settings, "anthropic_api_key_secondary", "b", raising=False)
    monkeypatch.setattr(af.settings, "anthropic_key_failover_enabled", True, raising=False)
    monkeypatch.setattr(af.settings, "anthropic_key_failover_max_retries", 0, raising=False)


# ── key resolution ───────────────────────────────────────────────────────────
def test_anthropic_keys_and_has_secondary():
    assert af.anthropic_keys() == ["a", "b"]
    assert af.has_secondary_key() is True


def test_keys_no_secondary(monkeypatch):
    monkeypatch.setattr(af.settings, "anthropic_api_key_secondary", "", raising=False)
    assert af.anthropic_keys() == ["a"]
    assert af.has_secondary_key() is False


def test_keys_disabled(monkeypatch):
    monkeypatch.setattr(af.settings, "anthropic_key_failover_enabled", False, raising=False)
    assert af.anthropic_keys() == ["a"]


def test_keys_dedup_identical_secondary(monkeypatch):
    monkeypatch.setattr(af.settings, "anthropic_api_key_secondary", "a", raising=False)
    assert af.anthropic_keys() == ["a"]


# ── call_failover ────────────────────────────────────────────────────────────
async def test_switches_account_on_transient():
    seen = []

    async def make(client):
        seen.append(client)
        if client == "c1":
            raise _transient()
        return "ok"

    out = await af.call_failover(["c1", "c2"], make)
    assert out == "ok"
    assert seen == ["c1", "c2"]  # switched to the second account


async def test_first_account_success_no_switch():
    seen = []

    async def make(client):
        seen.append(client)
        return "ok"

    out = await af.call_failover(["c1", "c2"], make)
    assert out == "ok"
    assert seen == ["c1"]  # primary succeeded; secondary untouched


async def test_non_transient_does_not_switch():
    seen = []

    async def make(client):
        seen.append(client)
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        await af.call_failover(["c1", "c2"], make)
    assert seen == ["c1"]  # a real error surfaces immediately


async def test_all_accounts_transient_raises_last():
    async def make(client):
        raise _transient()

    with pytest.raises(httpx.HTTPStatusError):
        await af.call_failover(["c1", "c2"], make)


async def test_no_clients_raises():
    async def make(client):  # pragma: no cover - never called
        return "x"

    with pytest.raises(RuntimeError):
        await af.call_failover([], make)


# ── FailoverAsyncAnthropic drop-in wrapper ───────────────────────────────────
async def test_wrapper_fails_over_create(monkeypatch):
    class _FakeMessages:
        def __init__(self, key):
            self.key = key

        async def create(self, **kwargs):
            if self.key == "a":
                raise _transient()
            return {"account": self.key, "kwargs": kwargs}

    class _FakeClient:
        def __init__(self, key):
            self.messages = _FakeMessages(key)

    monkeypatch.setattr(af, "build_async_clients", lambda **kw: [_FakeClient("a"), _FakeClient("b")])
    client = af.FailoverAsyncAnthropic()
    out = await client.messages.create(model="claude-x", max_tokens=10)
    assert out["account"] == "b"  # second account served the call
    assert out["kwargs"] == {"model": "claude-x", "max_tokens": 10}


# ── key pool (2026-09-02) ────────────────────────────────────────────────────
def test_account_keys_pool_merges_and_dedupes():
    from services.report_llm import anthropic_account_keys, parse_key_pool

    assert parse_key_pool(" c , d,,c ") == ["c", "d"]
    assert anthropic_account_keys("a", "b", "c,d", True) == ["a", "c", "d", "b"]
    assert anthropic_account_keys("a", "a", "a,c", True) == ["a", "c"]
    assert anthropic_account_keys("a", "b", "c", False) == ["a"]
    assert anthropic_account_keys("", "", "", True) == [""]  # primary slot always kept


def test_client_keys_read_the_pool_setting(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "a", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key_secondary", "b", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_keys", "c,d", raising=False)
    monkeypatch.setattr(settings, "anthropic_key_failover_enabled", True, raising=False)
    assert af._client_keys() == ["a", "c", "d", "b"]
    assert af.has_secondary_key()
