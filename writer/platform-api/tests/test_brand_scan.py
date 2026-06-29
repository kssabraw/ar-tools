"""Unit tests for services.brand_scan — the AI Visibility scan engine.

No network: the per-provider citation extractors and the regex fallback are pure;
the classifier and dispatch are monkeypatched for the orchestration tests.
"""

from __future__ import annotations

import asyncio

import pytest

from services import brand_scan as bs
from services.brand_scan import ProviderError, ScanFailed


# ── citation / text extraction ───────────────────────────────────────────────
def test_extract_openai_pulls_text_and_url_citations():
    output = [
        {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "Top: Acme Plumbing, Joe Pipes.",
             "annotations": [
                 {"type": "url_citation", "url": "https://a.com"},
                 {"type": "url_citation", "url": "https://a.com"},  # dup ignored
                 {"type": "other"},
             ]},
        ]},
    ]
    text, citations = bs._extract_openai(output)
    assert "Acme Plumbing" in text
    assert citations == ["https://a.com"]


def test_extract_gemini_uses_grounding_chunks():
    data = {"candidates": [{
        "content": {"parts": [{"text": "Hello "}, {"text": "world"}]},
        "groundingMetadata": {"groundingChunks": [
            {"web": {"uri": "https://g.com"}}, {"web": {"uri": "https://g.com"}},
        ]},
    }]}
    text, citations = bs._extract_gemini(data)
    assert text == "Hello world"
    assert citations == ["https://g.com"]


def test_extract_claude_reads_text_and_web_search_results():
    content = [
        {"type": "text", "text": "Acme appears. ", "citations": [{"url": "https://c1.com"}]},
        {"type": "web_search_tool_result", "content": [
            {"type": "web_search_result", "url": "https://c2.com"},
        ]},
    ]
    text, citations = bs._extract_claude(content)
    assert text == "Acme appears. "
    assert citations == ["https://c1.com", "https://c2.com"]


def test_extract_dataforseo_empty_returns_not_visible_message():
    text, citations = bs._extract_dataforseo_ai([], "burst pipe sydney", "Acme", "AI Overview")
    assert "No Google AI Overview" in text
    assert "Acme" in text
    assert citations == []


def test_extract_dataforseo_pulls_ai_overview_text_and_refs():
    items = [{"type": "ai_overview",
              "items": [{"text": "Acme Plumbing is great.",
                         "references": [{"url": "https://r.com"}]}]}]
    text, citations = bs._extract_dataforseo_ai(items, "kw", "Acme", "AI Overview")
    assert "Acme Plumbing is great." in text
    assert citations == ["https://r.com"]


# ── regex fallback classifier ────────────────────────────────────────────────
def test_fallback_detects_explicit_negative():
    r = bs._fallback_analysis("Acme Plumbing does not appear in the results.", "Acme Plumbing", [], "raw")
    assert r["mention_found"] is False
    assert r["mention_type"] == "none"
    assert r["confidence_score"] == 0.85


def test_fallback_rejects_query_restatement_only():
    # Brand appears ONLY in the AI's restatement of the query — not a real mention.
    text = "I'll search for Acme Plumbing. Here are the results: Joe Pipes, Bob Drains."
    r = bs._fallback_analysis(text, "Acme Plumbing", [], "raw")
    assert r["mention_found"] is False


def test_fallback_direct_mention_positive_sentiment():
    text = "Top providers: Acme Plumbing is highly recommended and trusted."
    r = bs._fallback_analysis(text, "Acme Plumbing", [], "raw")
    assert r["mention_found"] is True
    assert r["mention_type"] == "direct"
    assert r["sentiment"] > 0


def test_analyze_mention_without_openai_key_uses_fallback(monkeypatch):
    # No OpenAI key configured → classifier short-circuits to the regex fallback.
    monkeypatch.setattr(bs.settings, "openai_api_key", "")
    r = asyncio.run(bs.analyze_mention("Acme does not appear in the results.", "Acme", [], "raw"))
    assert r["mention_found"] is False
    assert "[Fallback]" in r["reasoning"]


# ── scan_keyword_engine orchestration ────────────────────────────────────────
def _stub_analyze(found=True):
    async def _fn(response_text, brand, citations, raw_response):
        return {
            "mention_found": found, "mention_type": "direct" if found else "none",
            "sentiment": 0.5, "confidence_score": 0.9, "snippet": "snip",
            "citations": citations, "reasoning": "ok", "raw_response": raw_response,
        }
    return _fn


def test_scan_keyword_engine_happy_path_with_competitors(monkeypatch):
    async def fake_dispatch(engine, keyword, brand):
        return ("Acme Plumbing leads. Rival Co also listed.", ["https://x.com"])

    monkeypatch.setattr(bs, "_dispatch", fake_dispatch)
    monkeypatch.setattr(bs, "analyze_mention", _stub_analyze(found=True))

    result = asyncio.run(bs.scan_keyword_engine("kw", "Acme Plumbing", "chatgpt", ["Rival Co"]))
    assert result["mention_found"] is True
    assert result["retry_count"] == 0
    assert len(result["competitor_results"]) == 1
    assert result["competitor_results"][0]["name"] == "Rival Co"


def test_scan_keyword_engine_terminal_error_raises(monkeypatch):
    async def fake_dispatch(engine, keyword, brand):
        raise ProviderError(429, "rate limited")

    monkeypatch.setattr(bs, "_dispatch", fake_dispatch)
    with pytest.raises(ScanFailed):
        asyncio.run(bs.scan_keyword_engine("kw", "Acme", "perplexity", []))


def test_scan_keyword_engine_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def flaky_dispatch(engine, keyword, brand):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderError(500, "transient")
        return ("Acme is listed.", [])

    monkeypatch.setattr(bs, "_dispatch", flaky_dispatch)
    monkeypatch.setattr(bs, "analyze_mention", _stub_analyze(found=True))

    result = asyncio.run(bs.scan_keyword_engine("kw", "Acme", "gemini", []))
    assert calls["n"] == 2
    assert result["retry_count"] == 1


def test_scan_keyword_engine_retries_on_transient_exception(monkeypatch):
    # A connection reset / timeout (not a ProviderError) should be retried, not
    # fail the cell outright.
    calls = {"n": 0}

    async def flaky(engine, keyword, brand):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection reset by peer")
        return ("Acme is listed.", [])

    monkeypatch.setattr(bs, "_dispatch", flaky)
    monkeypatch.setattr(bs, "analyze_mention", _stub_analyze(found=True))
    result = asyncio.run(bs.scan_keyword_engine("kw", "Acme", "gemini", []))
    assert calls["n"] == 2
    assert result["retry_count"] == 1


def test_scan_keyword_engine_config_error_is_terminal(monkeypatch):
    # ScanFailed (e.g. missing API key) must NOT be retried.
    calls = {"n": 0}

    async def cfg(engine, keyword, brand):
        calls["n"] += 1
        raise ScanFailed("Gemini API not configured")

    monkeypatch.setattr(bs, "_dispatch", cfg)
    with pytest.raises(ScanFailed):
        asyncio.run(bs.scan_keyword_engine("kw", "Acme", "gemini", []))
    assert calls["n"] == 1


def test_scan_keyword_engine_empty_responses_fail(monkeypatch):
    async def empty_dispatch(engine, keyword, brand):
        return ("", [])

    monkeypatch.setattr(bs, "_dispatch", empty_dispatch)
    with pytest.raises(ScanFailed):
        asyncio.run(bs.scan_keyword_engine("kw", "Acme", "chatgpt", []))


# ── auto-diagnosis (per not-found cell, during the scan) ──────────────────────
def test_autodiagnose_returns_diagnosis_on_success(monkeypatch):
    async def fake_diagnose(brand, keyword, raw, block):
        assert brand == "Acme" and keyword == "kw" and raw == "raw answer"
        assert "4.6★ from 30 reviews" in block  # gathered signals reach the prompt
        return "Here is why you're invisible…"

    monkeypatch.setattr(
        "services.brand_insights.gather_client_signals",
        lambda cid, kw: {"gbp": {"rating": 4.6, "review_count": 30,
                                 "has_website": True, "has_description": True}},
    )
    monkeypatch.setattr("services.brand_insights.diagnose_invisibility", fake_diagnose)
    out = asyncio.run(bs._autodiagnose("c1", "Acme", "kw", "raw answer"))
    assert out == "Here is why you're invisible…"


def test_autodiagnose_returns_none_when_openai_unavailable(monkeypatch):
    from services import brand_insights

    async def boom(brand, keyword, raw, block):
        raise brand_insights.InsightUnavailable("openai_not_configured")

    monkeypatch.setattr("services.brand_insights.gather_client_signals", lambda cid, kw: {})
    monkeypatch.setattr("services.brand_insights.diagnose_invisibility", boom)
    assert asyncio.run(bs._autodiagnose("c1", "Acme", "kw", "raw")) is None


def test_autodiagnose_swallows_unexpected_errors(monkeypatch):
    async def boom(brand, keyword, raw, block):
        raise RuntimeError("transient blip")

    monkeypatch.setattr("services.brand_insights.gather_client_signals", lambda cid, kw: {})
    monkeypatch.setattr("services.brand_insights.diagnose_invisibility", boom)
    # Best-effort: a diagnosis failure must never bubble up and fail the cell.
    assert asyncio.run(bs._autodiagnose("c1", "Acme", "kw", "raw")) is None


# ── enqueue validation ───────────────────────────────────────────────────────
def test_enqueue_rejects_unknown_engine():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        bs.enqueue_brand_scan("c1", ["k1"], ["chatgpt", "bing"], False, None)


def test_enqueue_rejects_empty_scan():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        bs.enqueue_brand_scan("c1", [], ["chatgpt"], False, None)
