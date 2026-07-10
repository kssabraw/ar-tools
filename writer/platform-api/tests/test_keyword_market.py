"""Unit tests for keyword market data + estimated-value (Module #4)."""

from __future__ import annotations

from services import keyword_market


def test_ctr_curve_known_positions():
    assert keyword_market.ctr_for_position(1) == 0.281
    assert keyword_market.ctr_for_position(10) == 0.017


def test_ctr_curve_buckets_and_absent():
    assert keyword_market.ctr_for_position(15) == 0.015
    assert keyword_market.ctr_for_position(35) == 0.005
    assert keyword_market.ctr_for_position(80) == 0.001
    assert keyword_market.ctr_for_position(None) == 0.0
    assert keyword_market.ctr_for_position(150) == 0.0


def test_ctr_rounds_fractional_position():
    # 3.2 → position 3
    assert keyword_market.ctr_for_position(3.2) == 0.106


def test_estimate_value_happy():
    # 1000 vol × CTR@3 (0.106) × $4 ≈ 424.0
    assert keyword_market.estimate_monthly_value(1000, 3.0, 4.0) == 424.0


def test_estimate_value_none_when_missing_inputs():
    assert keyword_market.estimate_monthly_value(None, 3.0, 4.0) is None
    assert keyword_market.estimate_monthly_value(1000, None, 4.0) is None
    assert keyword_market.estimate_monthly_value(1000, 3.0, None) is None
    assert keyword_market.estimate_monthly_value(0, 3.0, 4.0) is None


# --- batch shaping: eligibility + chunking ----------------------------------
# A single keyword over DataForSEO's caps fails the WHOLE request ("Invalid
# Field: 'keywords'"), so ineligible keywords are filtered pre-call; >1000
# keywords are chunked into multiple requests.

def test_market_eligible_accepts_normal_keywords():
    assert keyword_market.market_eligible("emergency plumber sydney")
    assert keyword_market.market_eligible("who's the best plumber")
    assert keyword_market.market_eligible("a a a a a a a a a a")  # exactly 10 words


def test_market_eligible_rejects_over_caps():
    # The live failure case: a full conversational question.
    assert not keyword_market.market_eligible(
        "Who's the best IT support company near me for a law firm with strict compliance needs"
    )
    assert not keyword_market.market_eligible("x" * 81)                 # > 80 chars
    assert not keyword_market.market_eligible(" ".join(["word"] * 11))  # > 10 words
    assert not keyword_market.market_eligible("")
    assert not keyword_market.market_eligible("   ")


def test_partition_keeps_order_and_splits():
    long_kw = "x" * 100
    wordy_kw = " ".join(["w"] * 12)
    eligible, skipped = keyword_market.partition_market_keywords(
        ["good one", long_kw, "another good", wordy_kw]
    )
    assert eligible == ["good one", "another good"]
    assert skipped == [long_kw, wordy_kw]


def test_chunk_keywords_respects_cap():
    kws = [f"kw {i}" for i in range(2500)]
    chunks = keyword_market.chunk_keywords(kws, size=1000)
    assert [len(c) for c in chunks] == [1000, 1000, 500]
    assert chunks[0][0] == "kw 0" and chunks[2][-1] == "kw 2499"
    assert keyword_market.chunk_keywords([], size=1000) == []
    assert keyword_market.chunk_keywords(["a"], size=1000) == [["a"]]


# --- rate-limit retry -------------------------------------------------------
# DataForSEO throttling arrives as HTTP 429 OR as an HTTP 200 whose task body
# says "Too many requests" (the observed live failure) — both retry.

def test_is_rate_limited_body_detects_task_message():
    assert keyword_market.is_rate_limited_body(
        {"tasks": [{"status_code": 40202, "status_message": "Too many requests."}]}
    )
    assert keyword_market.is_rate_limited_body({"status_message": "TOO MANY REQUESTS"})
    assert not keyword_market.is_rate_limited_body(
        {"tasks": [{"status_code": 20000, "status_message": "Ok."}]}
    )
    assert not keyword_market.is_rate_limited_body({})


class _StubResponse:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._body


class _StubClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def post(self, *args, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


def test_post_volume_retries_http_429_then_succeeds(monkeypatch):
    import asyncio

    async def no_sleep(_):
        return None

    monkeypatch.setattr(keyword_market.asyncio, "sleep", no_sleep)
    ok_body = {"tasks": [{"status_code": 20000, "result": []}]}
    client = _StubClient([_StubResponse(429), _StubResponse(200, ok_body)])
    body = asyncio.run(keyword_market._post_volume(client, [{}]))
    assert body == ok_body
    assert client.calls == 2


def test_post_volume_retries_body_level_throttle(monkeypatch):
    import asyncio

    async def no_sleep(_):
        return None

    monkeypatch.setattr(keyword_market.asyncio, "sleep", no_sleep)
    throttled = {"tasks": [{"status_code": 40202, "status_message": "Too many requests."}]}
    ok_body = {"tasks": [{"status_code": 20000, "result": []}]}
    client = _StubClient([_StubResponse(200, throttled), _StubResponse(200, ok_body)])
    body = asyncio.run(keyword_market._post_volume(client, [{}]))
    assert body == ok_body
    assert client.calls == 2


def test_post_volume_returns_throttled_body_after_budget(monkeypatch):
    # Persistent body-level throttle: after the retry budget the throttled body
    # is returned so fetch_market's >=40000 validation raises the same error as
    # before (job failed, re-enqueued by the daily scheduler).
    import asyncio

    async def no_sleep(_):
        return None

    monkeypatch.setattr(keyword_market.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(keyword_market, "_DFS_MAX_RETRIES", 2)
    throttled = {"tasks": [{"status_code": 40202, "status_message": "Too many requests."}]}
    client = _StubClient([_StubResponse(200, throttled)] * 3)
    body = asyncio.run(keyword_market._post_volume(client, [{}]))
    assert keyword_market.is_rate_limited_body(body)
    assert client.calls == 3  # initial + 2 retries


def test_parse_market_items():
    history = [{"year": 2025, "month": 6, "search_volume": 2600}]
    items = [
        {"keyword": "HVAC Repair", "search_volume": 2400, "cpc": 12.5, "competition": "HIGH",
         "monthly_searches": history},
        {"keyword": "no volume"},  # partial
        {"search_volume": 10},     # no keyword → skipped
    ]
    parsed = keyword_market.parse_market_items(items)
    assert parsed["hvac repair"] == {
        "search_volume": 2400, "cpc": 12.5, "competition": "HIGH",
        "monthly_searches": history,
    }
    assert parsed["no volume"]["search_volume"] is None
    assert "search_volume" not in parsed  # the keyword-less item didn't create a bogus key
