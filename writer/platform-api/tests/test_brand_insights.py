"""Unit tests for services.brand_insights pure helpers (no network)."""

from __future__ import annotations

from services import brand_insights as bi


def test_parse_keyword_list_plain_json():
    out = bi._parse_keyword_list('["a", "b", "c"]')
    assert out == ["a", "b", "c"]


def test_parse_keyword_list_tolerates_fences_and_prose():
    text = 'Here are the keywords:\n```json\n["plumber near me", "Acme reviews"]\n```'
    assert bi._parse_keyword_list(text) == ["plumber near me", "Acme reviews"]


def test_parse_keyword_list_caps_at_five_and_drops_blanks():
    out = bi._parse_keyword_list('["a","b","c","d","e","f"]')
    assert out == ["a", "b", "c", "d", "e"]
    assert bi._parse_keyword_list('["x", "", "  "]') == ["x"]


def test_parse_keyword_list_bad_input_returns_empty():
    assert bi._parse_keyword_list("not json at all") == []
    assert bi._parse_keyword_list("") == []


def test_prompts_include_context():
    d = bi._diagnosis_prompt("Acme", "burst pipe sydney", "Joe Pipes, Bob Drains")
    assert "Acme" in d and "burst pipe sydney" in d and "Joe Pipes" in d
    s = bi._suggest_prompt("Acme", ["Plumber"], "123 St, Sydney")
    assert "Acme" in s and "Plumber" in s and "123 St, Sydney" in s
