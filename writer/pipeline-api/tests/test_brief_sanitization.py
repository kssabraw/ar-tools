"""Tests for SERP heading sanitization (CQ PRD v1.0 R2)."""

from __future__ import annotations

import pytest

from modules.brief.sanitization import sanitize_heading


# ---- Cases pulled from production output (the audited tiktok_shop run) ----

@pytest.mark.parametrize(
    "raw,expected_substring,note",
    [
        (
            "What exactly is tiktok shop ? : r/TikTokshop",
            "What exactly is tiktok shop",
            "S1 - strip subreddit suffix",
        ),
        (
            "What is TikTok Shop and How is it Different ...",
            "What is TikTok Shop and How is it Different",
            "S2 - strip trailing ellipsis (three periods)",
        ),
        (
            "What is TikTok Shop…",
            "What is TikTok Shop",
            "S2 - strip unicode horizontal-ellipsis",
        ),
    ],
)
def test_audited_serp_artifact_examples(raw, expected_substring, note):
    cleaned = sanitize_heading(raw)
    assert cleaned is not None, f"{note}: should not be discarded"
    assert expected_substring in cleaned, f"{note}: expected substring not found"
    assert "r/" not in cleaned, f"{note}: subreddit ref leaked"
    assert "..." not in cleaned, f"{note}: ellipsis leaked"
    assert "…" not in cleaned, f"{note}: unicode ellipsis leaked"


def test_pipe_separated_tagline_drops_trailing_segment():
    """`Title | Marketing Tagline` - drop the tagline."""
    cleaned = sanitize_heading(
        "TikTok Shop | Discover the Future of Social Commerce",
    )
    # In this case the leading 'TikTok Shop' is just two words → S10
    # non-descriptive → discarded entirely. Both behaviors (kept-without-tail
    # OR discarded) are acceptable; what's NOT acceptable is leaving the
    # tagline in the output.
    assert cleaned is None or "Discover the Future" not in cleaned


def test_pipe_separated_tagline_with_meaningful_lead_keeps_lead():
    cleaned = sanitize_heading(
        "How TikTok Shop Works | Shopify Blog",
        source_url="https://shopify.com/blog/tiktok-shop",
    )
    assert cleaned == "How TikTok Shop Works"


def test_pipe_separated_question_tail_preserved():
    """`Title | How does it work?` - trailing segment is question-shaped, keep it."""
    cleaned = sanitize_heading(
        "Choosing a Plan: How Long Does It Take? | Shopify",
        source_url="https://shopify.com/x",
    )
    assert "How Long Does It Take" in cleaned


# ---- Sanitization rule coverage ----

def test_s4_leading_site_name_with_domain_match():
    cleaned = sanitize_heading(
        "Forbes: How TikTok Shop Changed E-Commerce",
        source_url="https://forbes.com/article",
    )
    # Domain prefix stripped; E-Commerce hyphen preserved (not a separator)
    assert cleaned == "How TikTok Shop Changed E-Commerce"


def test_s5_continue_reading_suffix():
    assert sanitize_heading("How TikTok Shop Works | Continue Reading") == "How TikTok Shop Works"
    assert sanitize_heading("How TikTok Shop Works | Read More") == "How TikTok Shop Works"


def test_s6_html_entities_and_tags_decoded_and_stripped():
    cleaned = sanitize_heading("How <strong>TikTok Shop</strong> &amp; Sellers Work")
    assert cleaned == "How TikTok Shop & Sellers Work"


def test_s7_whitespace_collapsed():
    cleaned = sanitize_heading("What  is  TikTok   Shop?")
    assert cleaned == "What is TikTok Shop?"


def test_s8_trailing_punctuation_runs_reduced():
    cleaned = sanitize_heading("How does TikTok Shop work?!?")
    # Reduces multiple terminal marks to a single one (the first match
    # in the run is preserved).
    assert cleaned is not None
    assert cleaned.count("?") == 1
    assert "!" not in cleaned


def test_s9_too_short_after_sanitization_returns_none():
    # "TikTok Shop" alone - 2 words, S9 discards
    assert sanitize_heading("TikTok Shop") is None
    assert sanitize_heading("Shop") is None
    assert sanitize_heading("...") is None


def test_s10_non_descriptive_brand_returns_none():
    assert sanitize_heading("Forbes Inc") is None
    assert sanitize_heading("Salesforce") is None


def test_leading_numbering_stripped():
    assert sanitize_heading("1. Getting Started With TikTok Shop") == "Getting Started With TikTok Shop"
    assert sanitize_heading("12) The Future of TikTok Shop") == "The Future of TikTok Shop"
    assert sanitize_heading("• How TikTok Shop Differs") == "How TikTok Shop Differs"


def test_markdown_emphasis_stripped():
    assert sanitize_heading("**What is** TikTok Shop?") == "What is TikTok Shop?"
    assert sanitize_heading("`What is` TikTok Shop?") == "What is TikTok Shop?"
    assert sanitize_heading("__What is__ TikTok Shop?") == "What is TikTok Shop?"


def test_inline_dash_inside_short_title_preserved():
    """`Pros - Cons of X` is a legitimate inline use, not a separator."""
    cleaned = sanitize_heading("Pros - Cons of TikTok Shop")
    assert cleaned == "Pros - Cons of TikTok Shop"


def test_dash_separated_strips_when_lead_has_3plus_words():
    cleaned = sanitize_heading(
        "How TikTok Shop Works - A Complete Guide",
    )
    assert cleaned == "How TikTok Shop Works"


def test_dash_separated_preserves_when_lead_too_short():
    cleaned = sanitize_heading("Definitions - TikTok Shop")
    # Leading "Definitions" is 1 word → don't reduce to it; preserve original
    assert cleaned == "Definitions - TikTok Shop"


def test_empty_and_none_inputs():
    assert sanitize_heading(None) is None  # type: ignore[arg-type]
    assert sanitize_heading("") is None
    assert sanitize_heading("   ") is None


def test_clean_heading_passes_through_unchanged():
    assert sanitize_heading("How TikTok Shop affects creator earnings") == "How TikTok Shop affects creator earnings"
