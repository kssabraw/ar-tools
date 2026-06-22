"""Tests for AI Overview capture (parse_aio_insights, PRD §X.1).

Side-channel only: degrades to available=False, never raises. Fixtures
mirror the DataForSEO organic/advanced `ai_overview` item shape.
"""

from __future__ import annotations

from modules.brief.parsers import parse_aio_insights


def _organic(url: str = "https://example.com") -> dict:
    return {"type": "organic", "rank_absolute": 1, "url": url, "title": "T"}


def test_aio_absent_returns_unavailable():
    items = [_organic(), {"type": "people_also_ask", "items": []}]
    aio = parse_aio_insights(items)
    assert aio.available is False
    assert aio.answer_text == ""
    assert aio.cited_domains == []


def test_aio_inline_elements_extracted():
    items = [
        _organic(),
        {
            "type": "ai_overview",
            "asynchronous_ai_overview": False,
            "items": [
                {"type": "ai_overview_element", "title": "Overview",
                 "text": "Magnesium glycinate supports sleep."},
                {"type": "ai_overview_element", "text": "It is highly absorbable."},
                {"type": "ai_overview_reference", "domain": "Healthline.com",
                 "url": "https://healthline.com/x"},
            ],
            "references": [
                {"domain": "webmd.com", "url": "https://webmd.com/y"},
            ],
        },
    ]
    aio = parse_aio_insights(items)
    assert aio.available is True
    assert "Magnesium glycinate supports sleep." in aio.answer_text
    assert "highly absorbable" in aio.answer_text
    # references nested + top-level, lowercased, deduped
    assert set(aio.cited_domains) == {"healthline.com", "webmd.com"}
    assert aio.asynchronous is False


def test_aio_prefers_markdown_when_present():
    items = [{
        "type": "ai_overview",
        "markdown": "Full markdown answer.",
        "items": [{"type": "ai_overview_element", "text": "ignored fragment"}],
    }]
    aio = parse_aio_insights(items)
    assert aio.answer_text == "Full markdown answer."


def test_aio_question_titles_become_fanout():
    items = [{
        "type": "ai_overview",
        "items": [
            {"type": "ai_overview_element", "title": "What is creatine?",
             "text": "Creatine is a compound."},
        ],
    }]
    aio = parse_aio_insights(items)
    assert "What is creatine?" in aio.fanout_questions


def test_aio_asynchronous_with_no_inline_text_is_unavailable():
    # AIO present but text deferred to a follow-up fetch: capture the flag,
    # but available=False because there's no usable answer_text inline.
    items = [{
        "type": "ai_overview",
        "asynchronous_ai_overview": True,
        "items": [],
    }]
    aio = parse_aio_insights(items)
    assert aio.asynchronous is True
    assert aio.available is False
