"""Tests for the per-zone term usage analyzer.

Validates:
- Zone partitioning (title / h1 / subheadings / body)
- Related-keyword vs entity classification (driven by SIE is_entity flag)
- Whole-word matching (substring inside larger word doesn't count)
- Quadgram extraction with stopword filtering
- Citation marker stripping before quadgram extraction
"""

from __future__ import annotations

from modules.writer.term_usage import (
    ZONES,
    _count_term_in_text,
    _quadgrams,
    compute_term_usage_by_zone,
)


# -----------------------------------------------------------------------
# Pure helpers
# -----------------------------------------------------------------------

def test_count_term_is_case_insensitive():
    assert _count_term_in_text("TikTok Shop", "tiktok shop and TIKTOK SHOP and TikTok Shop") == 3


def test_count_term_uses_word_boundaries():
    # "art" should NOT match inside "smart" or "artist"
    assert _count_term_in_text("art", "smart artist art") == 1


def test_count_term_handles_multiword_phrases():
    assert _count_term_in_text("paid amplification", "paid amplification works for paid amplification campaigns") == 2


def test_count_term_empty_inputs():
    assert _count_term_in_text("", "anything") == 0
    assert _count_term_in_text("term", "") == 0


def test_quadgrams_basic():
    text = "the quick brown fox jumps over the lazy dog. the quick brown fox is fast."
    out = _quadgrams(text, top_n=5)
    phrases = [q.phrase for q in out]
    # "quick brown fox jumps" appears 1x, "the quick brown fox" appears 2x
    assert "the quick brown fox" in phrases
    counts = {q.phrase: q.count for q in out}
    assert counts["the quick brown fox"] == 2


def test_quadgrams_filters_all_stopword_phrases():
    # "in the of and" is all stopwords - filtered out.
    out = _quadgrams("in the of and in the of and", top_n=5)
    assert all("in the of and" != q.phrase for q in out)


def test_quadgrams_returns_empty_for_short_text():
    assert _quadgrams("only three words", top_n=5) == []


# -----------------------------------------------------------------------
# Full compute_term_usage_by_zone
# -----------------------------------------------------------------------

def _article_fixture():
    return [
        {"order": 1, "level": "H1", "type": "content",
         "heading": "How to Increase TikTok Shop ROI", "body": ""},
        {"order": 2, "level": "none", "type": "intro",
         "heading": None,
         "body": "TikTok Shop is a discovery-driven commerce channel where creators drive sales."},
        {"order": 3, "level": "H2", "type": "content",
         "heading": "Affiliate Strategy for TikTok Shop",
         "body": "Run a structured affiliate program with paid amplification.{{cit_001}} Brands using paid amplification see better ROI."},
        {"order": 4, "level": "H3", "type": "content",
         "heading": "Commission Rates by Vertical",
         "body": "Beauty brands typically pay 15% commission. Wellness brands pay 12%."},
        {"order": 5, "level": "H2", "type": "faq-header",
         "heading": "Frequently Asked Questions", "body": ""},
        {"order": 6, "level": "H3", "type": "faq-question",
         "heading": "Does TikTok Shop work for B2B?",
         "body": "TikTok Shop is primarily a B2C channel."},
        {"order": 7, "level": "none", "type": "conclusion",
         "heading": None,
         "body": "TikTok Shop ROI requires creator content plus paid amplification."},
    ]


def _sie_fixture():
    required = [
        {"term": "TikTok Shop", "is_entity": True, "entity_category": "ORGANIZATION"},
        {"term": "paid amplification", "is_entity": False},
        {"term": "ROI", "is_entity": False},
        {"term": "creator content", "is_entity": False},
        {"term": "Beauty", "is_entity": True, "entity_category": "OTHER"},
    ]
    exploratory = [
        {"term": "commission", "is_entity": False},
    ]
    return required, exploratory


def test_compute_returns_all_zones():
    required, exploratory = _sie_fixture()
    out = compute_term_usage_by_zone(
        title="How to Increase TikTok Shop ROI",
        h1="How to Increase TikTok Shop ROI: Tactics That Actually Work",
        article=_article_fixture(),
        sie_terms_required=required,
        sie_terms_exploratory=exploratory,
    )
    assert set(out.keys()) == set(ZONES)
    for zone in ZONES:
        assert "related_keywords" in out[zone]
        assert "entities" in out[zone]
        assert "quadgrams" in out[zone]


def test_title_zone_counts_terms():
    required, exploratory = _sie_fixture()
    out = compute_term_usage_by_zone(
        title="How to Increase TikTok Shop ROI",
        h1="",
        article=[],
        sie_terms_required=required,
        sie_terms_exploratory=exploratory,
    )
    # TikTok Shop is an entity → bucketed in entities, not related_keywords
    title_entities = {t["term"] for t in out["title"]["entities"]}
    title_related = {t["term"] for t in out["title"]["related_keywords"]}
    assert "TikTok Shop" in title_entities
    assert "ROI" in title_related
    # Ensure entity isn't double-counted as related keyword
    assert "TikTok Shop" not in title_related


def test_subheadings_zone_aggregates_h2_h3():
    required, exploratory = _sie_fixture()
    out = compute_term_usage_by_zone(
        title="t",
        h1="h",
        article=_article_fixture(),
        sie_terms_required=required,
        sie_terms_exploratory=exploratory,
    )
    # "Affiliate Strategy for TikTok Shop" + "Commission Rates by Vertical"
    # + FAQ heading + FAQ question heading.
    sh_entities = {t["term"]: t["count"] for t in out["subheadings"]["entities"]}
    assert sh_entities.get("TikTok Shop", 0) >= 2  # H2 heading + FAQ Q
    sh_related = {t["term"]: t["count"] for t in out["subheadings"]["related_keywords"]}
    assert sh_related.get("commission", 0) >= 1


def test_body_zone_excludes_subheading_text():
    """Body counts only paragraph text, NOT heading text. A term that
    appears only in subheadings should not show up in body counts."""
    article = [
        {"order": 1, "level": "H2", "type": "content",
         "heading": "Beauty Strategy", "body": "Wellness brands focus on retention."},
    ]
    out = compute_term_usage_by_zone(
        title="t", h1="h", article=article,
        sie_terms_required=[{"term": "Beauty", "is_entity": True}],
        sie_terms_exploratory=[],
    )
    body_entities = {t["term"] for t in out["body"]["entities"]}
    sh_entities = {t["term"] for t in out["subheadings"]["entities"]}
    assert "Beauty" in sh_entities  # in heading
    assert "Beauty" not in body_entities  # NOT in body prose


def test_body_quadgrams_strip_citation_markers():
    """{{cit_NNN}} markers must not appear in extracted quadgrams."""
    article = [
        {"order": 1, "level": "H2", "type": "content", "heading": "X",
         "body": "Brands using paid amplification see better ROI.{{cit_005}}"},
    ]
    out = compute_term_usage_by_zone(
        title="t", h1="h", article=article,
        sie_terms_required=[], sie_terms_exploratory=[],
    )
    for q in out["body"]["quadgrams"]:
        assert "cit_" not in q["phrase"]


def test_zero_count_terms_omitted():
    """Terms that don't appear in a zone should not be reported there."""
    out = compute_term_usage_by_zone(
        title="Plain title with nothing matching",
        h1="",
        article=[],
        sie_terms_required=[
            {"term": "TikTok Shop", "is_entity": True},
            {"term": "ROI", "is_entity": False},
        ],
        sie_terms_exploratory=[],
    )
    assert out["title"]["entities"] == []
    assert out["title"]["related_keywords"] == []


def test_empty_article_returns_empty_zones():
    out = compute_term_usage_by_zone(
        title="", h1="", article=[],
        sie_terms_required=[], sie_terms_exploratory=[],
    )
    for zone in ZONES:
        assert out[zone]["related_keywords"] == []
        assert out[zone]["entities"] == []
        assert out[zone]["quadgrams"] == []


def test_results_sorted_by_count_desc_then_alpha():
    article = [
        {"order": 1, "level": "H2", "type": "content", "heading": "X",
         "body": "ROI ROI ROI commission Beauty"},
    ]
    out = compute_term_usage_by_zone(
        title="t", h1="h", article=article,
        sie_terms_required=[
            {"term": "ROI", "is_entity": False},
            {"term": "commission", "is_entity": False},
            {"term": "Beauty", "is_entity": False},
        ],
        sie_terms_exploratory=[],
    )
    related = out["body"]["related_keywords"]
    # Sorted: ROI (3), then alphabetical between Beauty(1) and commission(1)
    assert related[0]["term"] == "ROI"
    assert related[0]["count"] == 3
    assert related[1]["term"] == "Beauty"
    assert related[2]["term"] == "commission"


def test_dedupes_terms_across_required_and_exploratory():
    """If the same term appears in both required and exploratory, count
    it once (using the first occurrence's metadata)."""
    article = [
        {"order": 1, "level": "H2", "type": "content", "heading": "X",
         "body": "TikTok Shop ROI"},
    ]
    out = compute_term_usage_by_zone(
        title="t", h1="h", article=article,
        sie_terms_required=[{"term": "TikTok Shop", "is_entity": True}],
        sie_terms_exploratory=[{"term": "TikTok Shop", "is_entity": True}],
    )
    entities = out["body"]["entities"]
    matching = [e for e in entities if e["term"] == "TikTok Shop"]
    assert len(matching) == 1  # not duplicated
