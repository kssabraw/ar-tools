"""Unit tests for fanout.storage.write_retry — the bounded retry that keeps a
transient Supabase transport drop from aborting the pipeline's terminal writes
(the failure mode that stranded session BPC-157, 2026-08-14)."""

import pytest

from fanout.storage.write_retry import (
    call_with_transport_retry,
    is_transient_transport_error,
)


class RemoteProtocolError(Exception):
    """Stand-in named exactly like httpx's, so the name-based classifier matches
    it without httpx installed (mirrors the httpx-less unit-test env)."""


def _no_sleep(_seconds):
    pass


def test_is_transient_matches_transport_error_by_name():
    assert is_transient_transport_error(RemoteProtocolError("Server disconnected"))


def test_is_transient_rejects_application_errors():
    assert not is_transient_transport_error(ValueError("bad request"))
    assert not is_transient_transport_error(KeyError("nope"))


def test_returns_value_without_retry_on_success():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return "ok"

    assert call_with_transport_retry(fn, sleeper=_no_sleep) == "ok"
    assert calls["n"] == 1


def test_retries_transient_then_succeeds():
    attempts = {"n": 0}
    retried = []

    def fn():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RemoteProtocolError("Server disconnected")
        return "recovered"

    result = call_with_transport_retry(
        fn, attempts=3, sleeper=_no_sleep,
        on_retry=lambda exc, n: retried.append(n),
    )
    assert result == "recovered"
    assert attempts["n"] == 3
    assert retried == [2, 3]  # on_retry fires before attempts 2 and 3


def test_gives_up_after_max_attempts_on_persistent_transient():
    attempts = {"n": 0}

    def fn():
        attempts["n"] += 1
        raise RemoteProtocolError("Server disconnected")

    with pytest.raises(RemoteProtocolError):
        call_with_transport_retry(fn, attempts=3, sleeper=_no_sleep)
    assert attempts["n"] == 3  # original + 2 retries, no more


def test_non_transient_error_is_not_retried():
    attempts = {"n": 0}

    def fn():
        attempts["n"] += 1
        raise ValueError("PostgREST 400")

    with pytest.raises(ValueError):
        call_with_transport_retry(fn, attempts=5, sleeper=_no_sleep)
    assert attempts["n"] == 1  # raised on the first attempt, never retried


def test_backoff_is_exponential_and_capped():
    delays = []

    def fn():
        raise RemoteProtocolError("Server disconnected")

    with pytest.raises(RemoteProtocolError):
        call_with_transport_retry(
            fn, attempts=5, base_sleep=1.0, max_sleep=4.0,
            sleeper=lambda s: delays.append(s),
        )
    # 4 sleeps between 5 attempts: 1, 2, 4, then capped at 4.
    assert delays == [1.0, 2.0, 4.0, 4.0]
