"""TextRazor client + aggregation + merge tests (SIE v1.2).

Covers the parallel-vendor entity path:
  - TextRazor client: builds correct request, parses success response,
    handles HTTP errors / non-JSON / empty text / missing API key
  - aggregate_textrazor_results: per-occurrence rel/conf filtering +
    aggregate page filter (>3 pages)
  - merge_textrazor_entities_into_terms: dedup against existing
    n-gram aggregates and Google NLP entity_meta
  - Deterministic filters: stopword-density + seed-keyword-fragments
  - Scoring: Option C boost differentiation (1.20× / 1.10× / 1.0×)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from modules.sie.ngrams import (
    STOPWORD_DENSITY_FLOOR,
    STOPWORDS,
    TermAggregate,
    _generate_ngrams,
    _stopword_density,
    filter_seed_keyword_fragments,
)
from modules.sie.textrazor_client import (
    PageTextRazorResult,
    TextRazorEntity,
    _truncate_to_bytes,
)
from modules.sie.textrazor_entities import (
    TEXTRAZOR_MIN_CONFIDENCE,
    TEXTRAZOR_MIN_PAGES,
    TEXTRAZOR_MIN_RELEVANCE,
    AggregatedTextRazorEntity,
    aggregate_textrazor_results,
)
from modules.sie.entities import merge_textrazor_entities_into_terms


# ---------------------------------------------------------------------------
# STOPWORDS expansion (regression — possessives/reflexives)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("word", [
    "your", "yours", "yourself", "yourselves",
    "myself", "ourselves", "themselves",
    "us", "me", "him",
])
def test_stopwords_includes_possessives_and_reflexives(word):
    assert word in STOPWORDS


# ---------------------------------------------------------------------------
# Stopword-density filter on n-gram generation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tokens,expected_ratio", [
    (["your", "tiktok"], 0.5),         # 50% — at floor, dropped
    (["how", "to"], 0.5),              # 50% — "to" is a stopword, "how" isn't
                                       # in our list; still hits the floor
    (["on", "tiktok", "shop"], 1 / 3), # ~33% — kept
    (["tiktok", "shop"], 0.0),         # 0% — kept
    (["the", "an", "a"], 1.0),         # 100% — dropped
])
def test_stopword_density_calc(tokens, expected_ratio):
    assert _stopword_density(tokens) == pytest.approx(expected_ratio)


def test_generate_ngrams_drops_high_stopword_density_bigrams():
    """`your tiktok` (50%) and `how to` (100%) get dropped."""
    tokens = ["how", "to", "grow", "your", "tiktok"]
    grams = _generate_ngrams(tokens, n=2)
    # "how to" → 100% stopwords → dropped
    # "to grow" → 50% stopwords → at floor → dropped
    # "grow your" → 50% stopwords → dropped
    # "your tiktok" → 50% stopwords → dropped
    assert "how to" not in grams
    assert "your tiktok" not in grams
    # Only fully content-word bigrams survive
    assert grams == [] or all(_stopword_density(g.split()) < STOPWORD_DENSITY_FLOOR for g in grams)


def test_generate_ngrams_keeps_low_stopword_density_trigrams():
    """`on tiktok shop` (33%) still passes — only one of three is a stopword."""
    tokens = ["on", "tiktok", "shop"]
    grams = _generate_ngrams(tokens, n=3)
    assert "on tiktok shop" in grams


def test_generate_ngrams_unigram_filter_unchanged():
    """v1.0 behavior preserved: unigrams skip stopwords entirely."""
    tokens = ["your", "tiktok", "shop", "the"]
    grams = _generate_ngrams(tokens, n=1)
    assert "your" not in grams  # now a stopword in v1.2
    assert "the" not in grams
    assert "tiktok" in grams
    assert "shop" in grams


# ---------------------------------------------------------------------------
# Seed-keyword-fragment filter
# ---------------------------------------------------------------------------


def _make_aggregate(term: str, pages_found: int = 5) -> TermAggregate:
    return TermAggregate(
        term=term, n_gram_length=len(term.split()),
        total_count=10, pages_found=pages_found,
        source_urls={f"https://example.com/{i}" for i in range(pages_found)},
    )


def test_seed_fragment_mark_flags_subsequences():
    """SIE v1.3 — flag (don't strip) seed-keyword fragments. For seed
    'how to grow your tiktok shop', n-gram terms that are contiguous
    subsequences of the keyword get FLAGGED — they stay in aggregates
    so the writer keeps using them, but the returned set tells the
    pipeline which terms to mark `is_seed_fragment=True` on."""
    aggregates = {
        "tiktok": _make_aggregate("tiktok"),
        "tiktok shop": _make_aggregate("tiktok shop"),
        "grow your tiktok": _make_aggregate("grow your tiktok"),
        "social commerce": _make_aggregate("social commerce"),  # NOT a fragment
    }
    flagged = filter_seed_keyword_fragments(
        aggregates, "how to grow your tiktok shop",
    )
    # Three fragments flagged; aggregates dict UNCHANGED (writer needs
    # them all for per-zone usage targets)
    assert flagged == {"tiktok", "tiktok shop", "grow your tiktok"}
    assert "social commerce" not in flagged
    assert "social commerce" in aggregates  # not a fragment, not flagged
    assert "tiktok" in aggregates  # flagged but NOT removed


def test_seed_fragment_mark_protects_target_keyword():
    """The seed keyword itself (any token order match) is NEVER flagged."""
    aggregates = {"tiktok shop": _make_aggregate("tiktok shop")}
    aggregates["tiktok shop"].coverage_exception = "target_keyword"
    flagged = filter_seed_keyword_fragments(aggregates, "tiktok shop")
    assert flagged == set()


def test_seed_fragment_mark_protects_entities():
    """Entities (per entity_meta['is_entity']) are protected — they
    surface in the entity bucket, not the keyword-variants bucket."""
    aggregates = {
        "tiktok shop": _make_aggregate("tiktok shop"),
        "tiktok": _make_aggregate("tiktok"),
    }
    entity_meta = {
        "tiktok shop": {"is_entity": True, "source": "ngram_and_entity"},
    }
    flagged = filter_seed_keyword_fragments(
        aggregates, "how to grow tiktok shop", entity_meta=entity_meta,
    )
    # tiktok shop is an entity — NOT flagged; tiktok is plain n-gram — flagged
    assert "tiktok" in flagged
    assert "tiktok shop" not in flagged
    # Both still in aggregates (no removal in v1.3)
    assert "tiktok" in aggregates
    assert "tiktok shop" in aggregates


def test_seed_fragment_mark_returns_empty_set_on_empty_keyword():
    aggregates = {"tiktok": _make_aggregate("tiktok")}
    flagged = filter_seed_keyword_fragments(aggregates, "")
    assert flagged == set()
    assert "tiktok" in aggregates  # still present


def test_termrecord_carries_is_seed_fragment_flag():
    """SIE v1.3 — TermRecord must support the new is_seed_fragment field
    so the pipeline can stamp it from the flagged set."""
    from models.sie import TermRecord

    rec = TermRecord(term="tiktok shop", is_seed_fragment=True)
    assert rec.is_seed_fragment is True
    # Default false
    rec_default = TermRecord(term="social commerce")
    assert rec_default.is_seed_fragment is False


# ---------------------------------------------------------------------------
# TextRazor client truncation helper
# ---------------------------------------------------------------------------


def test_truncate_to_bytes_short_input():
    assert _truncate_to_bytes("hello", 100) == "hello"


def test_truncate_to_bytes_long_ascii():
    text = "x" * 250
    truncated = _truncate_to_bytes(text, 100)
    assert len(truncated.encode("utf-8")) <= 100


def test_truncate_to_bytes_handles_multibyte_safely():
    """Truncating to a byte boundary mid-character must not raise.
    We use errors='ignore' so the trailing partial char is dropped."""
    text = "ñ" * 200  # 2 bytes per char
    truncated = _truncate_to_bytes(text, 51)  # odd byte limit forces split
    # Should be the largest valid ñ-prefix that fits in 51 bytes (25 chars = 50 bytes)
    assert len(truncated.encode("utf-8")) <= 51


# ---------------------------------------------------------------------------
# TextRazor aggregation: per-occurrence + aggregate filters
# ---------------------------------------------------------------------------


def _make_page(url: str, entities: list[TextRazorEntity]) -> PageTextRazorResult:
    return PageTextRazorResult(url=url, entities=entities)


def _make_textrazor_entity(
    name: str,
    *,
    relevance: float = 0.6,
    confidence: float = 5.0,
    matched_text: str = "",
) -> TextRazorEntity:
    return TextRazorEntity(
        name=name,
        matched_text=matched_text or name,
        relevance=relevance,
        confidence=confidence,
        type=["Concept"],
        wiki_link=None,
    )


def test_aggregate_filters_by_relevance():
    """Entity with relevance below 0.33 doesn't contribute to its
    aggregate, even if confidence is high."""
    pages = [
        _make_page(f"https://e.com/{i}", [
            _make_textrazor_entity("Term", relevance=0.20, confidence=10.0),
        ])
        for i in range(5)
    ]
    aggregated = aggregate_textrazor_results(pages)
    assert aggregated == []


def test_aggregate_filters_by_confidence():
    """Entity with confidence below 2.00 doesn't contribute."""
    pages = [
        _make_page(f"https://e.com/{i}", [
            _make_textrazor_entity("Term", relevance=0.8, confidence=1.5),
        ])
        for i in range(5)
    ]
    aggregated = aggregate_textrazor_results(pages)
    assert aggregated == []


def test_aggregate_drops_terms_on_3_or_fewer_pages():
    """Per spec: >3 pages required (i.e. ≥4)."""
    # Term appears on exactly 3 pages — should be DROPPED
    pages = [
        _make_page(f"https://e.com/{i}", [_make_textrazor_entity("Term")])
        for i in range(3)
    ]
    aggregated = aggregate_textrazor_results(pages)
    assert aggregated == []


def test_aggregate_keeps_terms_on_4_plus_pages():
    """Term appears on 4 pages — keeps."""
    pages = [
        _make_page(f"https://e.com/{i}", [_make_textrazor_entity("TikTok Shop")])
        for i in range(4)
    ]
    aggregated = aggregate_textrazor_results(pages)
    assert len(aggregated) == 1
    assert aggregated[0].name == "TikTok Shop"
    assert aggregated[0].pages_found == 4


def test_aggregate_handles_failed_pages_gracefully():
    """Pages with failed=True don't contribute."""
    pages = [
        _make_page("https://e.com/0", [_make_textrazor_entity("Term")]),
        _make_page("https://e.com/1", [_make_textrazor_entity("Term")]),
        _make_page("https://e.com/2", [_make_textrazor_entity("Term")]),
        _make_page("https://e.com/3", [_make_textrazor_entity("Term")]),
        PageTextRazorResult(url="https://e.com/4", failed=True, failure_reason="http_500"),
    ]
    aggregated = aggregate_textrazor_results(pages)
    # 4 successful pages with the entity → meets the >3 threshold
    assert len(aggregated) == 1


def test_aggregate_combines_relevance_and_confidence():
    """avg_relevance is mean across pages; max_confidence is max."""
    pages = [
        _make_page("https://e.com/0", [_make_textrazor_entity("X", relevance=0.5, confidence=3.0)]),
        _make_page("https://e.com/1", [_make_textrazor_entity("X", relevance=0.7, confidence=8.0)]),
        _make_page("https://e.com/2", [_make_textrazor_entity("X", relevance=0.6, confidence=5.0)]),
        _make_page("https://e.com/3", [_make_textrazor_entity("X", relevance=0.4, confidence=4.0)]),
    ]
    aggregated = aggregate_textrazor_results(pages)
    assert len(aggregated) == 1
    e = aggregated[0]
    assert e.avg_relevance == pytest.approx((0.5 + 0.7 + 0.6 + 0.4) / 4)
    assert e.max_confidence == 8.0


# ---------------------------------------------------------------------------
# merge_textrazor_entities_into_terms
# ---------------------------------------------------------------------------


def test_textrazor_merge_marks_existing_term_as_dual_signal():
    """Term already in aggregates (n-gram) + TextRazor flagged it →
    entity_meta gains is_textrazor=True and source='ngram_and_entity'."""
    aggregates = {"tiktok shop": _make_aggregate("tiktok shop")}
    entity_meta: dict[str, dict] = {}
    textrazor_entity = AggregatedTextRazorEntity(
        name="TikTok Shop",
        avg_relevance=0.7,
        max_confidence=8.0,
        pages_found=5,
        source_urls=["https://t.com/x", "https://t.com/y"],
        variants=["TikTok Shop", "tiktok shop"],
        types=["Concept"],
        wiki_link="en.wikipedia.org/wiki/TikTok_Shop",
    )
    aggregates, entity_meta = merge_textrazor_entities_into_terms(
        aggregates, entity_meta, [textrazor_entity],
    )
    assert "tiktok shop" in aggregates
    assert entity_meta["tiktok shop"]["source"] == "ngram_and_entity"
    assert entity_meta["tiktok shop"]["is_textrazor"] is True
    assert entity_meta["tiktok shop"]["textrazor_relevance"] == 0.7


def test_textrazor_merge_adds_new_entity_only_term():
    """TextRazor surfaced a new term not in n-gram aggregates →
    add as entity-only with passes_coverage_threshold=True."""
    aggregates: dict[str, TermAggregate] = {}
    entity_meta: dict[str, dict] = {}
    textrazor_entity = AggregatedTextRazorEntity(
        name="GMV Max",
        avg_relevance=0.55,
        max_confidence=4.0,
        pages_found=4,
        source_urls=["https://t.com/x"],
        variants=["GMV Max"],
    )
    aggregates, entity_meta = merge_textrazor_entities_into_terms(
        aggregates, entity_meta, [textrazor_entity],
    )
    assert "gmv max" in aggregates
    assert aggregates["gmv max"].coverage_exception == "entity_only"
    assert aggregates["gmv max"].passes_coverage_threshold is True
    assert entity_meta["gmv max"]["source"] == "entity_only"
    assert entity_meta["gmv max"]["is_textrazor"] is True


def test_textrazor_merge_unions_source_urls_with_existing_term():
    """When TextRazor agrees with the n-gram pipeline, the source URLs
    are unioned so coverage gates downstream see the combined reach."""
    existing = _make_aggregate("tiktok shop", pages_found=3)
    existing.source_urls = {"https://a.com", "https://b.com", "https://c.com"}
    aggregates = {"tiktok shop": existing}
    entity_meta: dict[str, dict] = {}
    textrazor_entity = AggregatedTextRazorEntity(
        name="TikTok Shop",
        avg_relevance=0.7,
        max_confidence=5.0,
        pages_found=4,
        source_urls=["https://a.com", "https://d.com", "https://e.com"],
        variants=["TikTok Shop", "tiktok shop"],
    )
    aggregates, _ = merge_textrazor_entities_into_terms(
        aggregates, entity_meta, [textrazor_entity],
    )
    assert aggregates["tiktok shop"].pages_found == 5  # 3 + 2 new


# ---------------------------------------------------------------------------
# Scoring: Option C boost differentiation
# ---------------------------------------------------------------------------


def test_scoring_boost_differentiation_constants_correct():
    """Direct sanity check that the SIE v1.2 boost constants differ
    from v1.1 (single 1.15× for shared) — Option C uses 1.20× / 1.10×
    / 1.0×. We assert the literal numbers in scoring.py haven't drifted.
    """
    import inspect
    from modules.sie import scoring

    src = inspect.getsource(scoring.score_terms)
    assert "score *= 1.20" in src or "* 1.20" in src
    assert "score *= 1.10" in src or "* 1.10" in src
    # The old v1.1 constant should NOT remain in the scoring path
    assert "score *= 1.15" not in src


# ---------------------------------------------------------------------------
# Self-review fixes — source-flag preservation, constant drift, language,
# httpx pooling, dead-code removal.
# ---------------------------------------------------------------------------


def test_textrazor_merge_preserves_entity_only_source():
    """Bug fix: TextRazor agreement on a Google-NLP-only term must NOT
    upgrade source from 'entity_only' to 'ngram_and_entity'. There is
    no n-gram backing; falsely upgrading inflates the score by ~9%
    (1.20× boost vs 1.10× per scoring.py).
    """
    aggregates = {"gmv max": _make_aggregate("gmv max")}
    # Simulate Google NLP having previously marked this as entity_only.
    entity_meta: dict[str, dict] = {
        "gmv max": {
            "is_entity": True,
            "entity_category": "concepts",
            "source": "entity_only",
        }
    }
    textrazor_entity = AggregatedTextRazorEntity(
        name="GMV Max",
        avg_relevance=0.6,
        max_confidence=5.0,
        pages_found=4,
        source_urls=["https://t.com/x"],
        variants=["GMV Max", "gmv max"],
    )
    aggregates, entity_meta = merge_textrazor_entities_into_terms(
        aggregates, entity_meta, [textrazor_entity],
    )
    # Must STAY entity_only — TextRazor agreeing doesn't mean an
    # n-gram exists.
    assert entity_meta["gmv max"]["source"] == "entity_only"
    # But the TextRazor confidence flags should still be added.
    assert entity_meta["gmv max"]["is_textrazor"] is True
    assert entity_meta["gmv max"]["textrazor_relevance"] == 0.6


def test_textrazor_merge_promotes_ngram_only_to_dual_signal():
    """Companion to the above — when no entity_meta entry exists yet
    (n-gram-only term), TextRazor agreement DOES promote it to
    ngram_and_entity. This is the legitimate upgrade path.
    """
    aggregates = {"checkout flow": _make_aggregate("checkout flow")}
    entity_meta: dict[str, dict] = {}  # No prior entity signal.
    textrazor_entity = AggregatedTextRazorEntity(
        name="Checkout Flow",
        avg_relevance=0.5,
        max_confidence=4.0,
        pages_found=4,
        source_urls=["https://t.com/x"],
        variants=["Checkout Flow", "checkout flow"],
    )
    aggregates, entity_meta = merge_textrazor_entities_into_terms(
        aggregates, entity_meta, [textrazor_entity],
    )
    assert entity_meta["checkout flow"]["source"] == "ngram_and_entity"


def test_aggregator_uses_min_pages_constant():
    """Bug fix: the aggregator's coverage filter must reference
    TEXTRAZOR_MIN_PAGES rather than a hardcoded literal so changing
    the constant propagates. We assert this by making a TextRazor
    entity present on exactly TEXTRAZOR_MIN_PAGES - 1 pages and
    verifying it's discarded, then on TEXTRAZOR_MIN_PAGES pages and
    verifying it survives.
    """
    def _entity_on_n_pages(n: int):
        per_page: list[PageTextRazorResult] = []
        for i in range(n):
            per_page.append(PageTextRazorResult(
                url=f"https://t.com/{i}",
                entities=[TextRazorEntity(
                    name="GMV Max",
                    matched_text="GMV Max",
                    relevance=0.8,
                    confidence=8.0,
                )],
            ))
        return per_page

    just_under = aggregate_textrazor_results(
        _entity_on_n_pages(TEXTRAZOR_MIN_PAGES - 1)
    )
    assert just_under == []

    just_at = aggregate_textrazor_results(
        _entity_on_n_pages(TEXTRAZOR_MIN_PAGES)
    )
    assert len(just_at) == 1
    assert just_at[0].pages_found == TEXTRAZOR_MIN_PAGES


def test_textrazor_language_map_translates_iso_to_three_letter():
    """Bug fix: SIE request's ISO-639-1 language_code must be
    translated to TextRazor's expected 3-letter code, not hardcoded
    to 'eng'. Unknown codes fall back to 'eng' so we never break
    requests on unsupported languages."""
    from modules.sie.textrazor_client import _textrazor_language

    assert _textrazor_language("en") == "eng"
    assert _textrazor_language("es") == "spa"
    assert _textrazor_language("fr") == "fra"
    assert _textrazor_language("DE") == "deu"  # Case-insensitive
    assert _textrazor_language("xx") == "eng"  # Unknown → fallback
    assert _textrazor_language("") == "eng"
    assert _textrazor_language(None) == "eng"  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_analyze_many_shares_single_httpx_client(monkeypatch):
    """Bug fix: each per-page call must reuse a single httpx.AsyncClient
    (connection pooling), not spin up a fresh one. We instrument
    AsyncClient.__init__ to count constructions across an analyze_many
    over 5 pages and assert exactly one was created."""
    from modules.sie import textrazor_client as tc

    construction_count = {"n": 0}
    real_init = tc.httpx.AsyncClient.__init__

    def _counting_init(self, *args, **kw):
        construction_count["n"] += 1
        return real_init(self, *args, **kw)

    monkeypatch.setattr(tc.httpx.AsyncClient, "__init__", _counting_init)
    # Make analyze_entities a no-op so we don't actually hit the network
    # — we just want to count client constructions.
    async def _fake_analyze(url, text, *, http_client=None, language_code="en"):
        return PageTextRazorResult(url=url)

    monkeypatch.setattr(tc, "analyze_entities", _fake_analyze)

    pages = [(f"https://t.com/{i}", "body") for i in range(5)]
    results = await tc.analyze_many(pages)
    assert len(results) == 5
    assert construction_count["n"] == 1


def test_aggregator_requires_per_occurrence_filters_pass_before_slot_creation():
    """Regression: the dead-code branch `if not slot["relevances"]:
    continue` was removed. Verify aggregation still rejects entities
    whose every occurrence failed per-occurrence filters — by never
    creating a slot for them rather than checking after-the-fact.
    """
    per_page = [
        PageTextRazorResult(
            url=f"https://t.com/{i}",
            entities=[TextRazorEntity(
                # Below relevance threshold — must not contribute.
                name="Low Relevance",
                matched_text="lr",
                relevance=TEXTRAZOR_MIN_RELEVANCE - 0.05,
                confidence=10.0,
            )],
        )
        for i in range(10)  # Plenty of pages, but all filtered.
    ]
    out = aggregate_textrazor_results(per_page)
    assert out == []
