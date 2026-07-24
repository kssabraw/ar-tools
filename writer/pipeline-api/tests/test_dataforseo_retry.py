"""Unit tests for the DataForSEO transient retry in modules/brief/dataforseo.py —
transient-error classification and the backoff loop around a single request.

The Brief and SIE modules share this client, so a transient DataForSEO SERP blip
("Internal SE Server Error", status_code 50000+) that used to abort the whole run
with an opaque HTTP 500 is now retried before it surfaces.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from config import settings
from modules.brief import dataforseo as dfs


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://x")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_is_transient_classifies():
    # DataForSEO server-side band (50000+) is retryable; client band is not.
    assert dfs._is_transient_dataforseo_error(dfs.DataForSEOError("x", retryable=True))
    assert not dfs._is_transient_dataforseo_error(dfs.DataForSEOError("x", retryable=False))
    # HTTP status errors: 5xx retryable, 4xx (incl. the llm_responses 404) not.
    assert dfs._is_transient_dataforseo_error(_http_status_error(500))
    assert dfs._is_transient_dataforseo_error(_http_status_error(503))
    assert not dfs._is_transient_dataforseo_error(_http_status_error(404))
    assert not dfs._is_transient_dataforseo_error(_http_status_error(400))
    # Timeouts / connection drops are retryable.
    assert dfs._is_transient_dataforseo_error(httpx.ReadTimeout("t"))
    assert dfs._is_transient_dataforseo_error(httpx.ConnectError("c"))
    # Everything else fails fast.
    assert not dfs._is_transient_dataforseo_error(ValueError("boom"))


def test_server_error_status_is_retryable():
    """A task-level 50000+ status parses to a retryable DataForSEOError."""
    body = {
        "status_code": 20000,
        "tasks": [
            {"status_code": 50000, "status_message": "Internal SE Server Error."}
        ],
    }

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return body

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, *a, **k):
            return _Resp()

    async def run():
        with pytest.raises(dfs.DataForSEOError) as ei:
            await dfs._request_once("/v3/serp", [{}], timeout=1.0)
        assert ei.value.retryable is True

    orig = dfs.httpx.AsyncClient
    dfs.httpx.AsyncClient = lambda *a, **k: _Client()
    try:
        asyncio.run(run())
    finally:
        dfs.httpx.AsyncClient = orig


def test_client_error_status_is_not_retryable():
    body = {"status_code": 20000, "tasks": [{"status_code": 40501, "status_message": "Invalid Field."}]}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return body

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, *a, **k):
            return _Resp()

    async def run():
        with pytest.raises(dfs.DataForSEOError) as ei:
            await dfs._request_once("/v3/serp", [{}], timeout=1.0)
        assert ei.value.retryable is False

    orig = dfs.httpx.AsyncClient
    dfs.httpx.AsyncClient = lambda *a, **k: _Client()
    try:
        asyncio.run(run())
    finally:
        dfs.httpx.AsyncClient = orig


class _FlakyRequest:
    def __init__(self, failures: int, exc_factory):
        self.failures = failures
        self.exc_factory = exc_factory
        self.calls = 0

    async def __call__(self, path, payload, timeout):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc_factory()
        return {"ok": True, "path": path}


async def _no_sleep(_delay):
    return None


def test_post_retries_transient_then_succeeds(monkeypatch):
    flaky = _FlakyRequest(
        failures=2,
        exc_factory=lambda: dfs.DataForSEOError("Internal SE Server Error.", retryable=True),
    )
    monkeypatch.setattr(dfs, "_request_once", flaky)
    monkeypatch.setattr(dfs.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(settings, "dataforseo_max_retries", 3)

    out = asyncio.run(dfs._post("/v3/serp", [{}]))
    assert out["ok"] is True
    assert flaky.calls == 3  # failed twice, succeeded third


def test_post_gives_up_after_budget(monkeypatch):
    flaky = _FlakyRequest(
        failures=99,
        exc_factory=lambda: dfs.DataForSEOError("Internal SE Server Error.", retryable=True),
    )
    monkeypatch.setattr(dfs, "_request_once", flaky)
    monkeypatch.setattr(dfs.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(settings, "dataforseo_max_retries", 2)

    with pytest.raises(dfs.DataForSEOError):
        asyncio.run(dfs._post("/v3/serp", [{}]))
    assert flaky.calls == 3  # initial + 2 retries


def test_post_terminal_error_not_retried(monkeypatch):
    flaky = _FlakyRequest(
        failures=99,
        exc_factory=lambda: dfs.DataForSEOError("no results", retryable=False),
    )
    monkeypatch.setattr(dfs, "_request_once", flaky)
    monkeypatch.setattr(dfs.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(settings, "dataforseo_max_retries", 4)

    with pytest.raises(dfs.DataForSEOError):
        asyncio.run(dfs._post("/v3/serp", [{}]))
    assert flaky.calls == 1  # fail fast, no retries
