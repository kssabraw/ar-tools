"""Tests for aggregation.aggregate_candidates (Brief Generator v2.0 Step 4)."""

from __future__ import annotations

import pytest

from modules.brief.aggregation import (
    LEVENSHTEIN_DEDUP_THRESHOLD,
    aggregate_candidates,
)
from modules.brief.graph import Candidate


def _serp_stats(*entries) -> dict[str, dict]:
    """entries: tuples of (norm_key, text, freq, position, urls)."""
    out = {}
    for norm, text, freq, position, urls in entries:
        out[norm] = {
            "representative_text": text,
            "serp_frequency": freq,
            "avg_serp_position": position,
            "source_urls": list(urls),
            "raw_text": text,
        }
    return out


# ----------------------------------------------------------------------
# SERP-only path
# ----------------------------------------------------------------------

def test_serp_only_produces_candidates_with_signal():
    cands = aggregate_candidates(
        serp_stats=_serp_stats(
            ("how it works", "How TikTok Shop Works", 12, 3.5, ["https://a.com"]),
            ("setup guide", "How to Set Up TikTok Shop", 4, 7.0, ["https://b.com"]),
        ),
        paa_questions=[],
        autocomplete=[],
        keyword_suggestions=[],
        llm_fanout_by_source={},
        llm_response_by_source={},
    )
    assert len(cands) == 2
    works = next(c for c in cands if "Works" in c.text)
    assert works.source == "serp"
    assert works.serp_frequency == 12
    assert works.avg_serp_position == 3.5
    assert works.source_urls == ["https://a.com"]
    # Non-LLM source → consensus stays 0
    assert works.llm_fanout_consensus == 0


# ----------------------------------------------------------------------
# Non-SERP sources arrive sanitized; freq stays 0; position stays None
# ----------------------------------------------------------------------

def test_paa_autocomplete_keyword_suggestions_carry_no_serp_signal():
    cands = aggregate_candidates(
        serp_stats={},
        paa_questions=["What is TikTok Shop?"],
        autocomplete=["tiktok shop how it works"],
        keyword_suggestions=["tiktok shop setup"],
        llm_fanout_by_source={},
        llm_response_by_source={},
    )
    by_src = {c.source: c for c in cands}
    assert by_src["paa"].serp_frequency == 0
    assert by_src["paa"].avg_serp_position is None
    assert by_src["autocomplete"].serp_frequency == 0
    assert by_src["keyword_suggestion"].serp_frequency == 0


# ----------------------------------------------------------------------
# Levenshtein dedup collapses near-paraphrases
# ----------------------------------------------------------------------

def test_levenshtein_dedup_collapses_near_paraphrase():
    """SERP entry + autocomplete near-paraphrase should merge into one."""
    cands = aggregate_candidates(
        serp_stats=_serp_stats(
            ("what is tiktok shop", "What is TikTok Shop", 18, 2.0, ["https://a.com"]),
        ),
        paa_questions=[],
        autocomplete=["What's TikTok Shop"],  # near-paraphrase
        keyword_suggestions=[],
        llm_fanout_by_source={},
        llm_response_by_source={},
    )
    # Should collapse into a single entry
    assert len(cands) == 1
    # SERP wins identity (higher serp_frequency)
    assert cands[0].source == "serp"
    assert cands[0].serp_frequency == 18


def test_levenshtein_dedup_url_union_after_merge():
    """Merging keeps URL evidence from both sides."""
    cands = aggregate_candidates(
        serp_stats=_serp_stats(
            ("setup guide", "How to Set Up TikTok Shop", 8, 4.0, ["https://a.com"]),
            # Note: stats keys must be unique; second SERP entry comes via
            # a different normalized form so it survives until dedup.
            ("setup tiktok", "How to set up tiktok shop", 3, 6.0, ["https://b.com"]),
        ),
        paa_questions=[],
        autocomplete=[],
        keyword_suggestions=[],
        llm_fanout_by_source={},
        llm_response_by_source={},
    )
    assert len(cands) == 1
    merged = cands[0]
    # URL set was unioned
    assert "https://a.com" in merged.source_urls
    assert "https://b.com" in merged.source_urls
    # Higher-frequency wins identity
    assert merged.serp_frequency == 8


# ----------------------------------------------------------------------
# LLM consensus tracking
# ----------------------------------------------------------------------

def test_llm_consensus_counts_distinct_llms():
    """4 distinct LLMs surface the same query → consensus = 4."""
    # Identical strings (modulo punctuation - sanitize_heading + normalize
    # collapse them) so all four merge into one candidate.
    same = "How does TikTok Shop work for sellers"
    cands = aggregate_candidates(
        serp_stats={},
        paa_questions=[],
        autocomplete=[],
        keyword_suggestions=[],
        llm_fanout_by_source={
            "llm_fanout_chatgpt": [same],
            "llm_fanout_claude": [same],
            "llm_fanout_gemini": [same],
        },
        llm_response_by_source={
            "llm_response_perplexity": [same],
        },
    )
    assert len(cands) == 1
    assert cands[0].llm_fanout_consensus == 4


def test_llm_consensus_does_not_double_count_same_llm():
    """Fan-out + response from the same LLM count as one."""
    cands = aggregate_candidates(
        serp_stats={},
        paa_questions=[],
        autocomplete=[],
        keyword_suggestions=[],
        llm_fanout_by_source={
            "llm_fanout_chatgpt": ["What is TikTok Shop"],
        },
        llm_response_by_source={
            "llm_response_chatgpt": ["What's TikTok Shop"],  # near-paraphrase
        },
    )
    assert len(cands) == 1
    # Both come from chatgpt → consensus = 1, not 2
    assert cands[0].llm_fanout_consensus == 1


def test_llm_consensus_zero_for_pure_serp():
    cands = aggregate_candidates(
        serp_stats=_serp_stats(("x", "TikTok Shop Overview", 10, 2.0, [])),
        paa_questions=[],
        autocomplete=[],
        keyword_suggestions=[],
        llm_fanout_by_source={},
        llm_response_by_source={},
    )
    assert cands[0].llm_fanout_consensus == 0


def test_llm_consensus_bumps_when_llm_merges_into_existing_serp_entry():
    """SERP entry + LLM near-paraphrase: SERP wins identity, consensus bumps."""
    # Use exact-match paraphrases of the SERP heading so the Levenshtein
    # gate (≤ 0.15) collapses them. Larger differences fall outside the
    # threshold and would form separate candidates - tested elsewhere.
    cands = aggregate_candidates(
        serp_stats=_serp_stats(
            ("what is tiktok shop", "What is TikTok Shop", 18, 2.0, []),
        ),
        paa_questions=[],
        autocomplete=[],
        keyword_suggestions=[],
        llm_fanout_by_source={
            "llm_fanout_chatgpt": ["What is TikTok Shop?"],
            "llm_fanout_claude": ["What is TikTok Shop"],
        },
        llm_response_by_source={},
    )
    assert len(cands) == 1
    assert cands[0].source == "serp"
    assert cands[0].llm_fanout_consensus == 2


# ----------------------------------------------------------------------
# Persona gap questions enter on a second pass
# ----------------------------------------------------------------------

def test_persona_gap_questions_appear_as_candidates():
    cands = aggregate_candidates(
        serp_stats={},
        paa_questions=[],
        autocomplete=[],
        keyword_suggestions=[],
        llm_fanout_by_source={},
        llm_response_by_source={},
        persona_gap_questions=[
            "Does TikTok Shop charge a setup fee?",
            "Is TikTok Shop available outside the US?",
        ],
    )
    assert len(cands) == 2
    assert all(c.source == "persona_gap" for c in cands)
    assert all(c.serp_frequency == 0 for c in cands)
    assert all(c.llm_fanout_consensus == 0 for c in cands)


def test_persona_gap_question_merges_with_existing_paraphrase():
    """A persona gap question similar to a SERP entry collapses; SERP wins identity."""
    cands = aggregate_candidates(
        serp_stats=_serp_stats(
            ("how it works", "How TikTok Shop Works", 8, 3.0, ["https://a.com"]),
        ),
        paa_questions=[],
        autocomplete=[],
        keyword_suggestions=[],
        llm_fanout_by_source={},
        llm_response_by_source={},
        persona_gap_questions=["How TikTok Shop work"],  # near-paraphrase
    )
    assert len(cands) == 1
    # SERP identity wins (frequency 8 > 0)
    assert cands[0].source == "serp"
    assert cands[0].serp_frequency == 8


# ----------------------------------------------------------------------
# Empty inputs
# ----------------------------------------------------------------------

def test_all_empty_inputs_return_empty():
    cands = aggregate_candidates(
        serp_stats={},
        paa_questions=[],
        autocomplete=[],
        keyword_suggestions=[],
        llm_fanout_by_source={},
        llm_response_by_source={},
    )
    assert cands == []


def test_pure_punctuation_dropped_real_question_kept():
    """A pure-punctuation string is rejected by sanitization."""
    cands = aggregate_candidates(
        serp_stats={},
        paa_questions=["??!", "How do I set up a TikTok Shop account?"],
        autocomplete=[],
        keyword_suggestions=[],
        llm_fanout_by_source={},
        llm_response_by_source={},
    )
    # Sanitization rejects "??!" (S9 too-short / non-descriptive).
    # The real question survives the ≥3-word minimum.
    assert len(cands) == 1
    assert "TikTok Shop" in cands[0].text


# ----------------------------------------------------------------------
# Consensus threshold cap
# ----------------------------------------------------------------------

def test_levenshtein_threshold_constant_matches_prd():
    """Sanity: PRD §5 Step 4 specifies 0.15 - ensure we don't drift."""
    assert LEVENSHTEIN_DEDUP_THRESHOLD == 0.15


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

def test_logs_complete_summary(caplog):
    with caplog.at_level("INFO", logger="modules.brief.aggregation"):
        aggregate_candidates(
            serp_stats=_serp_stats(("x", "Some Heading", 5, 2.0, [])),
            paa_questions=["A real question?"],
            autocomplete=[],
            keyword_suggestions=[],
            llm_fanout_by_source={},
            llm_response_by_source={},
            persona_gap_questions=["Will it integrate with Shopify?"],
        )
    assert any(
        r.message == "brief.aggregation.complete" for r in caplog.records
    )
