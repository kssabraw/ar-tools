"""SIE v1.1 — hybrid entity scoring + promotion.

Covers the seven scenarios from the implementation brief:

1. Low-salience but high-recurrence entity is retained/promoted
2. High-salience one-off entity behavior is deterministic
3. Navigational entities are still filtered (at NLP-extract time)
4. LLM cannot introduce unseen entities (regression)
5. Merge semantics unchanged (`ngram_and_entity` vs `entity_only`)
6. Reason flags attached correctly
7. Backward compat — entity_meta keys/structure preserved
"""

from __future__ import annotations

import pytest

from modules.sie.entities import (
    AggregatedEntity,
    _classify_promotion,
    _noise_penalty,
    aggregate_ner_results,
    llm_dedupe_and_categorize,
    merge_entities_into_terms,
    score_and_promote_entities,
)
from modules.sie.google_nlp import NEREntity, PageNERResult, _is_navigational
from modules.sie.ngrams import TermAggregate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agg(
    name: str,
    *,
    avg_salience: float = 0.30,
    pages_found: int = 1,
    total_mentions: int = 1,
    ner_variants: list[str] | None = None,
) -> AggregatedEntity:
    return AggregatedEntity(
        name=name,
        avg_salience=avg_salience,
        pages_found=pages_found,
        source_urls=[f"https://example.com/{i}" for i in range(pages_found)],
        ner_variants=ner_variants or [name],
        total_mentions=total_mentions,
    )


def _mock_call(response):
    async def _call(system, user, **kw):
        if isinstance(response, Exception):
            raise response
        return response
    return _call


# ---------------------------------------------------------------------------
# 1. Low-salience high-recurrence → promoted via override
# ---------------------------------------------------------------------------


def test_low_salience_high_recurrence_promoted():
    """A low-salience (0.18) entity appearing on 4/5 pages must survive
    via the recurrence override path — the v1.0 hard 0.40 gate would
    have dropped it at extraction time."""
    ents = [
        _agg("GMV Max", avg_salience=0.18, pages_found=4, total_mentions=8),
        _agg("Random One-Off", avg_salience=0.05, pages_found=1, total_mentions=1),
    ]
    promoted = score_and_promote_entities(ents, total_pages=5)
    names = {e.name: e for e in promoted}
    assert "GMV Max" in names
    assert names["GMV Max"].promotion_reason == "high_recurrence_low_salience"


# ---------------------------------------------------------------------------
# 2. High-salience one-off — deterministic
# ---------------------------------------------------------------------------


def test_high_salience_one_off_promoted_with_correct_reason():
    """A single-page entity with strong salience (0.70) is promoted as
    'high_salience_low_recurrence' — captures the 'one source nailed
    this' case."""
    ents = [
        _agg("Niche Authority Source", avg_salience=0.70, pages_found=1, total_mentions=3),
    ]
    promoted = score_and_promote_entities(ents, total_pages=5)
    assert len(promoted) == 1
    assert promoted[0].promotion_reason == "high_salience_low_recurrence"


def test_dual_signal_strong_when_both_dimensions_high():
    """Recurrence >= override AND salience >= 0.30 → 'dual_signal_strong'."""
    ents = [_agg("Core Topic", avg_salience=0.55, pages_found=4, total_mentions=10)]
    promoted = score_and_promote_entities(ents, total_pages=5)
    assert promoted[0].promotion_reason == "dual_signal_strong"


def test_entity_only_promoted_via_composite_score():
    """An entity that doesn't hit the recurrence override OR the high
    salience floor but has a strong COMPOSITE score is promoted as
    'entity_only_promoted'. Constructed: pages 2/5, mid-salience, high
    relative mentions → composite score crosses threshold."""
    ents = [
        # The mention-share leader: 100% of mentions go to this candidate
        _agg("Topic A", avg_salience=0.35, pages_found=2, total_mentions=20),
        # Comparison candidate that sets max_mentions
        _agg("Topic B", avg_salience=0.10, pages_found=1, total_mentions=1),
    ]
    promoted = score_and_promote_entities(ents, total_pages=5)
    a = next((e for e in promoted if e.name == "Topic A"), None)
    assert a is not None
    assert a.promotion_reason == "entity_only_promoted"


# ---------------------------------------------------------------------------
# 3. Navigational entities filtered at NLP-extract time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "menu", "Facebook", "Twitter", "navigation", "homepage",
    "linkedin", "subscribe", "newsletter", "tiktok.com",
])
def test_navigational_names_caught_by_filter(name):
    assert _is_navigational(name) is True


@pytest.mark.parametrize("name", [
    "TikTok Shop", "GMV Max", "Beauty Bay", "Procter & Gamble",
])
def test_real_entities_pass_navigational_filter(name):
    assert _is_navigational(name) is False


# ---------------------------------------------------------------------------
# 4. LLM cannot invent entities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_dedupe_drops_invented_names():
    """Anti-hallucination contract: any entity in the LLM response whose
    `name` does NOT match an input entity is dropped silently."""
    ents = [
        _agg("Real Entity A", avg_salience=0.5, pages_found=2),
        _agg("Real Entity B", avg_salience=0.4, pages_found=2),
    ]
    response = {"entities": [
        {"name": "Real Entity A", "category": "concepts", "example_context": "..."},
        # The LLM hallucinated a third entity not in the input
        {"name": "Invented Entity Z", "category": "concepts", "example_context": "..."},
    ]}
    refined = await llm_dedupe_and_categorize(ents, llm_json_fn=_mock_call(response))
    names = {e.name for e in refined}
    assert "Real Entity A" in names
    assert "Invented Entity Z" not in names


@pytest.mark.asyncio
async def test_llm_failure_returns_raw_aggregates():
    """If the LLM call raises, fall back to the raw aggregates rather
    than dropping all entities."""
    ents = [_agg("Real Entity A", avg_salience=0.5, pages_found=2)]
    refined = await llm_dedupe_and_categorize(
        ents, llm_json_fn=_mock_call(RuntimeError("boom")),
    )
    assert len(refined) == 1


# ---------------------------------------------------------------------------
# 5. Merge semantics
# ---------------------------------------------------------------------------


def test_merge_existing_term_routes_to_ngram_and_entity():
    """When an entity's normalized name matches an existing n-gram,
    the term gets `source = 'ngram_and_entity'`."""
    aggregates = {
        "tiktok shop": TermAggregate(
            term="tiktok shop", n_gram_length=2,
            total_count=10, pages_found=3,
            source_urls={"https://a.com", "https://b.com"},
        ),
    }
    ents = [_agg("TikTok Shop", avg_salience=0.55, pages_found=3, total_mentions=8)]
    ents[0].promotion_reason = "dual_signal_strong"

    updated, meta = merge_entities_into_terms(aggregates, ents)
    assert "tiktok shop" in meta
    assert meta["tiktok shop"]["source"] == "ngram_and_entity"


def test_merge_new_entity_routes_to_entity_only():
    """An entity with no matching n-gram is added as `entity_only`."""
    aggregates: dict[str, TermAggregate] = {}
    ents = [_agg("Brand New Concept", avg_salience=0.45, pages_found=2, total_mentions=4)]
    ents[0].promotion_reason = "entity_only_promoted"

    updated, meta = merge_entities_into_terms(aggregates, ents)
    norm = "brand new concept"
    assert norm in updated
    assert meta[norm]["source"] == "entity_only"
    assert updated[norm].coverage_exception == "entity_only"
    assert updated[norm].passes_coverage_threshold is True


# ---------------------------------------------------------------------------
# 6. Reason flags attached
# ---------------------------------------------------------------------------


def test_promotion_reason_surfaces_in_entity_meta():
    """Every promoted entity carries its `promotion_reason` through to
    `entity_meta` so dashboards can surface why it was selected."""
    aggregates: dict[str, TermAggregate] = {}
    ent = _agg("Recurrent Low Salience", avg_salience=0.18, pages_found=4, total_mentions=6)
    ent.promotion_reason = "high_recurrence_low_salience"
    ent.entity_score = 0.34

    _, meta = merge_entities_into_terms(aggregates, [ent])
    norm = "recurrent low salience"
    assert meta[norm]["promotion_reason"] == "high_recurrence_low_salience"
    assert meta[norm]["entity_score"] == 0.34


def test_classify_promotion_returns_none_below_thresholds():
    """An entity with weak signals on every axis is NOT promoted."""
    ent = _agg("Weak Signal", avg_salience=0.10, pages_found=1, total_mentions=1)
    ent.entity_score = 0.05
    reason = _classify_promotion(
        ent, score_threshold=0.30, recurrence_override=3,
    )
    assert reason is None


# ---------------------------------------------------------------------------
# 7. Backward compat — entity_meta shape
# ---------------------------------------------------------------------------


def test_entity_meta_preserves_v1_0_fields_and_adds_v1_1_fields():
    """The original v1.0 keys (is_entity, entity_category, avg_salience,
    ner_variants, source, example_context) must still be present so any
    existing consumer reading them keeps working. v1.1 additions
    (entity_score, promotion_reason, pages_found, total_mentions) are
    additive."""
    aggregates: dict[str, TermAggregate] = {}
    ent = _agg("Concept", avg_salience=0.45, pages_found=2, total_mentions=4)
    ent.promotion_reason = "entity_only_promoted"
    ent.entity_score = 0.42
    ent.category = "concepts"
    ent.example_context = "Used across pages..."

    _, meta = merge_entities_into_terms(aggregates, [ent])
    norm = "concept"
    expected_v1_0 = {"is_entity", "entity_category", "avg_salience",
                     "ner_variants", "source", "example_context"}
    expected_v1_1 = {"entity_score", "promotion_reason",
                     "pages_found", "total_mentions"}
    actual = set(meta[norm].keys())
    assert expected_v1_0.issubset(actual)
    assert expected_v1_1.issubset(actual)


# ---------------------------------------------------------------------------
# Noise penalty unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,expected", [
    ("a", 1.0),                # too short
    ("ab", 1.0),               # too short
    ("2024", 1.0),             # pure numeric
    ("$50.00", 0.9),           # currency
    ("January 5", 0.9),        # date-like
    ("data", 0.5),             # generic
    ("TikTok Shop", 0.0),      # real entity
])
def test_noise_penalty_scoring(name, expected):
    ent = _agg(name, avg_salience=0.5, pages_found=2)  # high pages so single-page heuristic doesn't apply
    assert _noise_penalty(ent) == pytest.approx(expected)


def test_noise_penalty_single_page_low_salience():
    ent = _agg("Some Entity", avg_salience=0.20, pages_found=1)
    assert _noise_penalty(ent) == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Aggregation tracks total_mentions
# ---------------------------------------------------------------------------


def test_aggregate_ner_results_carries_total_mentions():
    pages = [
        PageNERResult(url="https://a.com", entities=[
            NEREntity(name="Topic", type="OTHER", salience=0.3, mentions=3),
        ]),
        PageNERResult(url="https://b.com", entities=[
            NEREntity(name="Topic", type="OTHER", salience=0.4, mentions=5),
        ]),
    ]
    aggregated = aggregate_ner_results(pages)
    assert len(aggregated) == 1
    assert aggregated[0].total_mentions == 8
    assert aggregated[0].pages_found == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_score_and_promote_with_empty_input():
    assert score_and_promote_entities([], total_pages=5) == []


def test_score_and_promote_with_zero_total_pages():
    """Defensive: total_pages=0 returns empty (no division by zero)."""
    ents = [_agg("Topic", avg_salience=0.5, pages_found=2)]
    assert score_and_promote_entities(ents, total_pages=0) == []
