"""Unit tests for services.brand_scan — the AI Visibility scan engine.

No network: the per-provider citation extractors and the regex fallback are pure;
the classifier and dispatch are monkeypatched for the orchestration tests.
"""

from __future__ import annotations

import asyncio
import json

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
    text, citations, present = bs._extract_dataforseo_ai([], "burst pipe sydney", "Acme", "AI Overview")
    assert "No Google AI Overview" in text
    assert "Acme" in text
    assert citations == []
    assert present is False  # the feature didn't fire


def test_extract_dataforseo_pulls_ai_overview_text_and_refs():
    items = [{"type": "ai_overview",
              "items": [{"text": "Acme Plumbing is great.",
                         "references": [{"url": "https://r.com"}]}]}]
    text, citations, present = bs._extract_dataforseo_ai(items, "kw", "Acme", "AI Overview")
    assert "Acme Plumbing is great." in text
    assert citations == ["https://r.com"]
    assert present is True  # the AI Overview fired


def test_extract_aio_domains_splits_inline_links_from_references():
    items = [{
        "type": "ai_overview",
        # Top-level references = the sources/citations strip.
        "references": [{"domain": "directory.com", "url": "https://directory.com/x"}],
        "items": [
            {
                # An inline content link inside the generated answer.
                "text": "Acme is a top pick. [Acme Plumbing](https://acme.com/services)",
                "links": [{"domain": "partner.com", "url": "https://partner.com"}],
                "references": [{"url": "https://refonly.com/a"}],
            },
        ],
    }]
    inline, refs = bs._extract_aio_domains(items)
    assert "acme.com" in inline          # markdown link in the answer text
    assert "partner.com" in inline       # inline links[] array
    assert "directory.com" in refs and "refonly.com" in refs
    assert "acme.com" not in refs        # not double-counted as a citation


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
    async def _fn(response_text, brand, citations, raw_response, extract_rich=False,
                  competitor_names=None):
        out = {
            "mention_found": found, "mention_type": "direct" if found else "none",
            "sentiment": 0.5, "confidence_score": 0.9, "snippet": "snip",
            "citations": citations, "reasoning": "ok", "raw_response": raw_response,
        }
        if extract_rich:
            out["rich"] = {"businesses": [], "mention_rank": 1 if found else None}
        # Mirror the real analyze_mention: competitor classification is folded
        # into this single call (no per-competitor round-trips).
        if competitor_names:
            out["competitor_results"] = [
                {"name": n, "found": True, "mention_type": "direct",
                 "sentiment": 0.1, "confidence": 0.8, "snippet": "snip"}
                for n in competitor_names
            ]
        return out
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


# ── folded competitor classification (one call, not N) ───────────────────────
def test_clean_competitor_results_shapes_and_fills_missing():
    raw = [
        {"name": "Rival Co", "mention_found": True, "mention_type": "direct",
         "sentiment": 0.5, "confidence": 0.9, "evidence_snippet": "x" * 400},
        {"name": "", "mention_found": True},   # blank name → dropped
        "garbage",                              # non-dict → dropped
    ]
    out = bs._clean_competitor_results(raw, ["Rival Co", "Missing Inc"])
    assert [c["name"] for c in out] == ["Rival Co", "Missing Inc"]
    assert out[0]["found"] is True
    assert len(out[0]["snippet"]) == 300        # snippet clamped to 300 chars
    assert out[1]["found"] is False             # name the model omitted → degraded


def test_analyze_mention_folds_competitors_into_one_call(monkeypatch):
    # The single rich classifier call classifies the brand AND every competitor;
    # there must be exactly ONE create() call, not one-per-competitor.
    calls = {"n": 0, "messages": None}
    tool_args = json.dumps({
        "mention_found": True, "mention_type": "direct", "sentiment": 0.5,
        "confidence": 0.9, "evidence_snippet": "Acme listed", "reasoning": "ok",
        "businesses": [{"name": "Acme"}, {"name": "Rival Co"}],
        "competitors": [
            {"name": "Rival Co", "mention_found": True, "mention_type": "direct",
             "sentiment": 0.2, "confidence": 0.8, "evidence_snippet": "Rival listed"},
            {"name": "Ghost LLC", "mention_found": False, "mention_type": "none",
             "sentiment": 0, "confidence": 0.6, "evidence_snippet": "absent"},
        ],
    })

    class _Fn:
        name = "report_brand_visibility"
        arguments = tool_args

    class _TC:
        function = _Fn()

    class _Completions:
        async def create(self, **kwargs):
            calls["n"] += 1
            calls["messages"] = kwargs["messages"]
            msg = type("M", (), {"tool_calls": [_TC()]})()
            choice = type("C", (), {"message": msg})()
            return type("R", (), {"choices": [choice]})()

    class _FakeClient:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": _Completions()})()

    import openai
    monkeypatch.setattr(bs.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(bs.settings, "brand_scan_max_competitors", 5)
    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)

    r = asyncio.run(bs.analyze_mention(
        "Acme Plumbing leads. Rival Co also listed.", "Acme", [], "raw",
        extract_rich=True, competitor_names=["Rival Co", "Ghost LLC"],
    ))
    assert calls["n"] == 1                       # ONE call covers brand + 2 competitors
    comp = {c["name"]: c for c in r["competitor_results"]}
    assert comp["Rival Co"]["found"] is True
    assert comp["Ghost LLC"]["found"] is False
    assert "Rival Co" in calls["messages"][1]["content"]   # names reach the prompt


def test_scan_keyword_engine_competitors_via_regex_fallback_when_no_key(monkeypatch):
    # No OpenAI key → analyze_mention falls back to regex (no API call), and
    # scan_keyword_engine still produces competitor_results via the regex path.
    async def fake_dispatch(engine, keyword, brand):
        return ("Acme Plumbing leads. Rival Co also listed.", [])

    monkeypatch.setattr(bs, "_dispatch", fake_dispatch)
    monkeypatch.setattr(bs.settings, "openai_api_key", "")
    result = asyncio.run(bs.scan_keyword_engine("kw", "Acme Plumbing", "chatgpt", ["Rival Co"]))
    names = [c["name"] for c in result["competitor_results"]]
    assert names == ["Rival Co"]                 # complete matrix, zero extra API calls


def test_scan_keyword_engine_terminal_error_raises(monkeypatch):
    async def fake_dispatch(engine, keyword, brand):
        raise ProviderError(429, "rate limited")

    monkeypatch.setattr(bs, "_dispatch", fake_dispatch)
    with pytest.raises(ScanFailed):
        asyncio.run(bs.scan_keyword_engine("kw", "Acme", "perplexity", []))


def test_scan_keyword_engine_terminal_surfaces_provider_reason(monkeypatch):
    # A 403 from Google carries the real reason in the body; it must reach the
    # user-facing ScanFailed.reason instead of a generic catch-all.
    body = json.dumps({
        "error": {
            "code": 403,
            "status": "PERMISSION_DENIED",
            "message": "Generative Language API has not been used in project 123 or it is disabled.",
        }
    })

    async def fake_dispatch(engine, keyword, brand):
        raise ProviderError(403, body)

    monkeypatch.setattr(bs, "_dispatch", fake_dispatch)
    with pytest.raises(ScanFailed) as exc:
        asyncio.run(bs.scan_keyword_engine("kw", "Acme", "gemini", []))
    assert "gemini" in exc.value.reason
    assert "HTTP 403" in exc.value.reason
    assert "has not been used" in exc.value.reason


def test_scan_keyword_engine_invalid_key_400_is_terminal(monkeypatch):
    # An invalid Gemini key is a 400 (API_KEY_INVALID) — terminal, not a
    # retry-until-exhausted "no valid response" masking the real cause.
    calls = {"n": 0}
    body = json.dumps({
        "error": {"code": 400, "status": "INVALID_ARGUMENT",
                  "message": "API key not valid. Please pass a valid API key."}
    })

    async def bad_key(engine, keyword, brand):
        calls["n"] += 1
        raise ProviderError(400, body)

    monkeypatch.setattr(bs, "_dispatch", bad_key)
    with pytest.raises(ScanFailed) as exc:
        asyncio.run(bs.scan_keyword_engine("kw", "Acme", "gemini", []))
    assert calls["n"] == 1  # terminal → no retries
    assert "API key not valid" in exc.value.reason


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
