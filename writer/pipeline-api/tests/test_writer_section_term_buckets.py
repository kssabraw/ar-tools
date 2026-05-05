"""Bucket-aware per-section term selection (sections._terms_for_section).

The prior single combined cap (top 10 from a score-mixed list) was
crowding entities out of section prompts — articles shipped with only
3-5 distinct entities used even when SIE supplied 15+. The bucket-
aware cap takes top N from each of (entities / related keywords /
keyword variants) independently.
"""

from __future__ import annotations

from modules.writer.reconciliation import FilteredSIETerms, ReconciledTerm
from modules.writer.sections import _terms_for_section


def _term(name: str, *, is_entity: bool = False, is_seed_fragment: bool = False) -> ReconciledTerm:
    return ReconciledTerm(
        term=name,
        zone_usage_target=1,
        zone_usage_min=0,
        zone_usage_max=2,
        effective_target=1,
        effective_max=2,
        reconciliation_action="keep",
        zones=[],
        is_entity=is_entity,
        entity_category=None,
        is_seed_fragment=is_seed_fragment,
    )


def _filtered(*terms: ReconciledTerm) -> FilteredSIETerms:
    f = FilteredSIETerms()
    f.required = list(terms)
    return f


def test_empty_input_returns_empty():
    required, excluded, avoid = _terms_for_section(_filtered())
    assert required == []
    assert excluded == []
    assert avoid == []


def test_buckets_independently_capped():
    """20 entities + 20 related + 20 variants in the pool. With caps
    of 5/5/5, the result must be exactly 5 of each — not 15 of one
    bucket because they happened to come first in SIE's score order."""
    pool = (
        [_term(f"ent_{i}", is_entity=True) for i in range(20)]
        + [_term(f"rel_{i}") for i in range(20)]
        + [_term(f"var_{i}", is_seed_fragment=True) for i in range(20)]
    )
    required, _, _ = _terms_for_section(
        _filtered(*pool),
        max_entities=5,
        max_related_keywords=5,
        max_keyword_variants=5,
    )
    entities = [t for t in required if t.is_entity]
    variants = [t for t in required if t.is_seed_fragment]
    related = [t for t in required if not t.is_entity and not t.is_seed_fragment]
    assert len(entities) == 5
    assert len(related) == 5
    assert len(variants) == 5


def test_entities_first_in_returned_list():
    """Order matters: the section prompt iterates `required_terms` to
    print REQUIRED_TERMS at the top of the prompt. Entities-first puts
    the user's primary signal at the top so the LLM sees it before the
    related keywords / variants."""
    pool = [
        _term("rel_1"),
        _term("ent_1", is_entity=True),
        _term("var_1", is_seed_fragment=True),
        _term("rel_2"),
        _term("ent_2", is_entity=True),
    ]
    required, _, _ = _terms_for_section(_filtered(*pool))
    # Output order: entities, then related, then variants.
    names = [t.term for t in required]
    assert names == ["ent_1", "ent_2", "rel_1", "rel_2", "var_1"]


def test_within_bucket_score_order_preserved():
    """SIE sorts the required pool by recommendation_score descending.
    Within each bucket, that order must be preserved — taking the top
    N by SIE score is the whole point of "top N per bucket"."""
    pool = [
        _term("ent_high", is_entity=True),
        _term("ent_mid", is_entity=True),
        _term("ent_low", is_entity=True),
        _term("ent_lowest", is_entity=True),
    ]
    required, _, _ = _terms_for_section(
        _filtered(*pool),
        max_entities=2,
        max_related_keywords=15,
        max_keyword_variants=15,
    )
    entity_names = [t.term for t in required if t.is_entity]
    assert entity_names == ["ent_high", "ent_mid"]


def test_underfilled_bucket_does_not_steal_from_other_buckets():
    """If only 3 entities exist but the cap is 15, the related-keyword
    bucket does NOT get the leftover 12 slots. Each bucket is
    independent — that's the whole point of the redesign vs the
    prior combined cap."""
    pool = (
        [_term(f"ent_{i}", is_entity=True) for i in range(3)]
        + [_term(f"rel_{i}") for i in range(20)]
    )
    required, _, _ = _terms_for_section(
        _filtered(*pool),
        max_entities=15,
        max_related_keywords=15,
        max_keyword_variants=15,
    )
    entities = [t for t in required if t.is_entity]
    related = [t for t in required if not t.is_entity and not t.is_seed_fragment]
    assert len(entities) == 3   # all 3 available
    assert len(related) == 15   # capped at 15, NOT 27 (15+leftover-12)


def test_user_failure_pattern_more_entities_now_surface():
    """Regression: simulate the user's reported pattern. SIE pool of
    20 mixed terms, sorted by score with entities scattered through
    mid-band. Prior combined cap of 10 surfaced ~3 entities; new
    bucket cap of 15 surfaces all 8 entities in the pool."""
    # SIE-score order: high-scoring related keywords dominate the top.
    pool = (
        [_term(f"rel_top_{i}") for i in range(7)]
        + [_term("ent_1", is_entity=True), _term("ent_2", is_entity=True)]
        + [_term(f"rel_mid_{i}") for i in range(3)]
        + [_term(f"ent_{i+3}", is_entity=True) for i in range(6)]  # ent_3..ent_8
        + [_term("var_1", is_seed_fragment=True), _term("var_2", is_seed_fragment=True)]
    )
    required, _, _ = _terms_for_section(
        _filtered(*pool),
        max_entities=15,
        max_related_keywords=15,
        max_keyword_variants=15,
    )
    entities = [t.term for t in required if t.is_entity]
    # Old behavior (top 10 mixed by SIE order) would have given:
    #   rel_top_0..rel_top_6 (7), ent_1, ent_2, rel_mid_0 (3 entities visible)
    # New behavior gives all 8 entities because the entity bucket is
    # filled independently from its own slice of the pool.
    assert len(entities) == 8
    assert "ent_1" in entities and "ent_8" in entities


def test_excluded_and_avoid_pass_through_unchanged():
    """The bucket-aware change only affects the `required` selection.
    `excluded` (terms classified out for brand conflict) and `avoid`
    (terms the brand explicitly forbids) must remain unchanged in
    structure and content."""
    f = FilteredSIETerms()
    f.required = [_term("ent_1", is_entity=True)]
    f.excluded = [{"term": "x", "reason": "exclude_due_to_brand_conflict"}]
    f.avoid = ["banned_phrase", "another"]
    required, excluded, avoid = _terms_for_section(f)
    assert excluded == ["x"]
    assert avoid == ["banned_phrase", "another"]


def test_cap_of_zero_yields_empty_bucket():
    """Operator-tunable to zero — useful for ablation runs that want to
    test sections with NO entities (or no related keywords, etc.)."""
    pool = [
        _term("ent_1", is_entity=True),
        _term("rel_1"),
        _term("var_1", is_seed_fragment=True),
    ]
    required, _, _ = _terms_for_section(
        _filtered(*pool),
        max_entities=0,
        max_related_keywords=15,
        max_keyword_variants=15,
    )
    assert all(not t.is_entity for t in required)
    assert any(t.is_seed_fragment for t in required)
