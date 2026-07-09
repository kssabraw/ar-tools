"""Term-coverage enforcement (owner spec 2026-07-09).

Quadgram rule: tracked corpus 4-grams must each appear >= 1x; any
required term above the occurrence cap flags as stuffing. Entity rule:
EITHER 75% bar missed (unique coverage / total vs targets) triggers one
auto-rewrite of the weakest sections, then flags if still short.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from models.writer import ArticleSection
from modules.writer.reconciliation import FilteredSIETerms, ReconciledTerm
from modules.writer.sections import SectionWriteResult
from modules.writer.term_coverage import (
    compute_term_coverage,
    enforce_term_coverage,
)


def _entity(term: str, target: int = 2) -> ReconciledTerm:
    return ReconciledTerm(term=term, is_entity=True, effective_target=target)


def _kw(term: str) -> ReconciledTerm:
    return ReconciledTerm(term=term, is_entity=False, effective_target=1)


def _section(order: int, heading: str, body: str) -> ArticleSection:
    return ArticleSection(order=order, level="H2", type="content", heading=heading, body=body)


# ---------------------------------------------------------------------------
# compute_term_coverage - pure math
# ---------------------------------------------------------------------------

def test_full_entity_coverage_does_not_trigger():
    terms = FilteredSIETerms(required=[_entity("freight audit", 1), _entity("parcel invoice", 1)])
    article = [_section(1, "Overview", "A freight audit reviews every parcel invoice.")]
    stats = compute_term_coverage(article, terms)
    assert stats.entity_unique_coverage_pct == 1.0
    assert stats.entity_total_coverage_pct == 1.0
    assert stats.entity_rewrite_triggered is False
    assert stats.entities_missing == []


def test_unique_bar_failing_alone_triggers():
    """1 of 4 unique entities used (25%) triggers even when the used one
    saturates its target (either-bar rule)."""
    terms = FilteredSIETerms(required=[
        _entity("freight audit", 10),
        _entity("carrier contract", 0),
        _entity("rate benchmarking", 0),
        _entity("invoice recovery", 0),
    ])
    body = " ".join(["freight audit does things."] * 10)
    stats = compute_term_coverage([_section(1, "H", body)], terms)
    assert stats.entity_unique_coverage_pct == 0.25
    assert stats.entity_total_coverage_pct == 1.0
    assert stats.entity_rewrite_triggered is True
    assert set(stats.entities_missing) == {"carrier contract", "rate benchmarking", "invoice recovery"}


def test_total_bar_failing_alone_triggers():
    """Every entity appears once (unique 100%) but totals sit far below
    the summed targets."""
    terms = FilteredSIETerms(required=[_entity("freight audit", 5), _entity("parcel invoice", 5)])
    article = [_section(1, "H", "One freight audit and one parcel invoice.")]
    stats = compute_term_coverage(article, terms)
    assert stats.entity_unique_coverage_pct == 1.0
    assert stats.entity_total_coverage_pct == 0.2  # 2 of 10
    assert stats.entity_rewrite_triggered is True


def test_boundary_75_pct_passes():
    """Exactly 75% is NOT below the bar (strictly less-than)."""
    terms = FilteredSIETerms(required=[
        _entity("alpha corp", 1), _entity("beta corp", 1),
        _entity("gamma corp", 1), _entity("delta corp", 1),
    ])
    article = [_section(1, "H", "alpha corp beta corp gamma corp did fine. alpha corp again.")]
    stats = compute_term_coverage(article, terms)
    assert stats.entity_unique_coverage_pct == 0.75
    assert stats.entity_total_coverage_pct == 1.0  # 4 of 4, clamped
    assert stats.entity_rewrite_triggered is False


def test_no_entities_never_triggers():
    terms = FilteredSIETerms(required=[_kw("cost recovery")])
    stats = compute_term_coverage([_section(1, "H", "nothing relevant")], terms)
    assert stats.entity_unique_coverage_pct is None
    assert stats.entity_rewrite_triggered is False


def test_quadgrams_tracked_and_missing():
    terms = FilteredSIETerms(required=[
        _kw("freight audit and payment"),        # 4-gram, used
        _kw("parcel invoice audit software"),    # 4-gram, missing
        _kw("cost recovery"),                    # 2-gram - not tracked
        _entity("global supply chain services", 1),  # entity 4-gram - not tracked
    ])
    article = [_section(1, "H", "Freight Audit AND Payment providers vary.")]
    stats = compute_term_coverage(article, terms)
    assert stats.quadgrams_tracked == [
        "freight audit and payment", "parcel invoice audit software",
    ]
    assert stats.quadgrams_missing == ["parcel invoice audit software"]


def test_quadgram_tracking_caps_at_max():
    # Each is exactly 4 tokens: "unique phrase number N"
    quads = [_kw(f"unique phrase number {i}") for i in range(15)]
    terms = FilteredSIETerms(required=quads)
    stats = compute_term_coverage(
        [_section(1, "H", "no phrases here")], terms, quadgram_track_max=10,
    )
    assert len(stats.quadgrams_tracked) == 10


def test_occurrence_cap_flags_stuffing():
    terms = FilteredSIETerms(required=[_kw("cost recovery")])
    body = " ".join(["cost recovery matters."] * 11)
    stats = compute_term_coverage([_section(1, "H", body)], terms, occurrence_cap=10)
    assert stats.terms_over_cap == [{"term": "cost recovery", "count": 11, "cap": 10}]


# ---------------------------------------------------------------------------
# enforce_term_coverage - the auto-rewrite pass
# ---------------------------------------------------------------------------

# The same (h2_item, h3_items) pairs the section loop wrote from -
# positionally aligned with the article's content H2 groups.
_H2_GROUPS = [
    ({"order": 3, "level": "H2", "text": "Weak Section", "type": "content"}, []),
    ({"order": 5, "level": "H2", "text": "Strong Section", "type": "content"}, []),
]


def _trigger_terms() -> FilteredSIETerms:
    return FilteredSIETerms(required=[
        _entity("freight audit", 2),
        _entity("carrier contract", 2),
        _entity("rate benchmarking", 2),
        _entity("invoice recovery", 2),
    ])


def _trigger_article() -> list[ArticleSection]:
    return [
        _section(3, "Weak Section", "Nothing relevant here at all."),
        _section(5, "Strong Section", "A freight audit reviews spend. freight audit twice."),
    ]


@pytest.mark.asyncio
async def test_rewrite_targets_weakest_section_and_resolves():
    fixed_body = (
        "freight audit freight audit carrier contract carrier contract "
        "rate benchmarking rate benchmarking invoice recovery invoice recovery"
    )
    # Fresh sections per call (like the real write_h2_group) - the splice
    # re-stamps orders in place, so a shared object would alias across calls.
    fn = AsyncMock(side_effect=lambda **kw: SectionWriteResult(
        sections=[_section(3, "Weak Section", fixed_body)],
    ))
    result = await enforce_term_coverage(
        _trigger_article(),
        keyword="kw", intent="listicle",
        h2_groups=_H2_GROUPS,
        section_budgets={3: 200, 5: 200},
        filtered_terms=_trigger_terms(),
        citations=[], brand_voice_card=None, banned_regex=None,
        write_h2_group_fn=fn,
    )
    assert result.sections_retried >= 1
    assert result.rewrite_resolved is True
    assert result.stats.entity_rewrite_triggered is True  # the trigger is preserved
    # The weakest section (order 3, zero entities) is retried first, with
    # the missing entities named in the directive.
    first_call = fn.await_args_list[0].kwargs
    assert first_call["h2_item"]["order"] == 3
    directive = first_call["term_retry_directive"]
    assert "carrier contract" in directive and "invoice recovery" in directive
    # The rewritten body was spliced into the returned article.
    weak = next(s for s in result.validated_article if s.order == 3)
    assert "carrier contract" in weak.body


@pytest.mark.asyncio
async def test_no_trigger_means_no_rewrite_calls():
    fn = AsyncMock()
    terms = FilteredSIETerms(required=[_entity("freight audit", 1)])
    article = [_section(3, "H", "A freight audit works.")]
    result = await enforce_term_coverage(
        article,
        keyword="kw", intent="listicle",
        h2_groups=_H2_GROUPS,
        section_budgets={3: 200},
        filtered_terms=terms,
        citations=[], brand_voice_card=None, banned_regex=None,
        write_h2_group_fn=fn,
    )
    fn.assert_not_awaited()
    assert result.rewrite_resolved is None
    assert result.stats.entity_rewrite_triggered is False


@pytest.mark.asyncio
async def test_rewrite_disabled_flags_without_retry(monkeypatch):
    from modules.writer import term_coverage as tc
    monkeypatch.setattr(tc.settings, "writer_entity_rewrite_enabled", False)
    fn = AsyncMock()
    result = await enforce_term_coverage(
        _trigger_article(),
        keyword="kw", intent="listicle",
        h2_groups=_H2_GROUPS,
        section_budgets={3: 200, 5: 200},
        filtered_terms=_trigger_terms(),
        citations=[], brand_voice_card=None, banned_regex=None,
        write_h2_group_fn=fn,
    )
    fn.assert_not_awaited()
    assert result.stats.entity_rewrite_triggered is True
    assert result.rewrite_resolved is None


@pytest.mark.asyncio
async def test_retry_failure_still_flags():
    fn = AsyncMock(side_effect=RuntimeError("llm down"))
    result = await enforce_term_coverage(
        _trigger_article(),
        keyword="kw", intent="listicle",
        h2_groups=_H2_GROUPS,
        section_budgets={3: 200, 5: 200},
        filtered_terms=_trigger_terms(),
        citations=[], brand_voice_card=None, banned_regex=None,
        write_h2_group_fn=fn,
    )
    assert result.sections_retried == 0
    assert result.rewrite_resolved is False
    assert result.stats.entity_rewrite_triggered is True
