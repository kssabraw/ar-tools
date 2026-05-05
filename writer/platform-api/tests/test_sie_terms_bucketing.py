"""Tests for `bucket_sie_required_terms` — the helper that splits the
SIE module_output's `terms.required[]` into the three v1.4 buckets
(entities / related_keywords / keyword_variants) for the UI.

Mirrors the writer's prompt-side bucketing rules so the categories
the frontend displays match what the writer actually treats each term
as.
"""

from __future__ import annotations

from models.runs import bucket_sie_required_terms


def test_buckets_split_by_flags():
    required = [
        {"term": "TikTok Shop", "is_entity": True, "is_seed_fragment": False},
        {"term": "GMV Max", "is_entity": True, "is_seed_fragment": False},
        {"term": "checkout flow", "is_entity": False, "is_seed_fragment": False},
        {"term": "conversion rate", "is_entity": False, "is_seed_fragment": False},
        {"term": "roi", "is_entity": False, "is_seed_fragment": True},
        {"term": "tiktok shop roi", "is_entity": False, "is_seed_fragment": True},
    ]
    result = bucket_sie_required_terms(required)
    assert result.entities == ["TikTok Shop", "GMV Max"]
    assert result.related_keywords == ["checkout flow", "conversion rate"]
    assert result.keyword_variants == ["roi", "tiktok shop roi"]


def test_entity_takes_precedence_over_fragment_flag():
    """Mirrors the writer's _classify_term — if a term is somehow
    flagged as both is_entity AND is_seed_fragment, entity wins."""
    required = [
        {"term": "tiktok shop", "is_entity": True, "is_seed_fragment": True},
    ]
    result = bucket_sie_required_terms(required)
    assert result.entities == ["tiktok shop"]
    assert result.keyword_variants == []


def test_handles_missing_flags_as_related_keyword():
    """Pre-v1.3 SIE responses don't carry is_seed_fragment; pre-v1.0
    didn't carry is_entity. Both default to False → related_keyword."""
    required = [
        {"term": "checkout"},
        {"term": "scaling"},
    ]
    result = bucket_sie_required_terms(required)
    assert result.entities == []
    assert result.keyword_variants == []
    assert result.related_keywords == ["checkout", "scaling"]


def test_skips_malformed_entries():
    """Defensive: non-dict entries, empty/missing term strings, and
    whitespace-only terms are all dropped silently."""
    required = [
        "not a dict",
        None,
        {"is_entity": True},  # missing term
        {"term": "", "is_entity": True},  # empty term
        {"term": "   ", "is_entity": True},  # whitespace-only term
        {"term": "valid entity", "is_entity": True},
    ]
    result = bucket_sie_required_terms(required)
    assert result.entities == ["valid entity"]
    assert result.related_keywords == []
    assert result.keyword_variants == []


def test_strips_whitespace_from_terms():
    required = [
        {"term": "  TikTok Shop  ", "is_entity": True},
    ]
    result = bucket_sie_required_terms(required)
    assert result.entities == ["TikTok Shop"]


def test_empty_required_returns_empty_buckets():
    result = bucket_sie_required_terms([])
    assert result.entities == []
    assert result.related_keywords == []
    assert result.keyword_variants == []


def test_none_required_returns_empty_buckets():
    """Defensive: None input (e.g., SIE payload missing terms.required)
    must not raise."""
    result = bucket_sie_required_terms(None)
    assert result.entities == []
    assert result.related_keywords == []
    assert result.keyword_variants == []
