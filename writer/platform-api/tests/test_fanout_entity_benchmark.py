"""Fanout blog writer entity-density (Option A) — pure-logic units.

Covers the most-aggressive-competitor entity benchmark and the writer-prompt
entity selection sized to it (both in `fanout.sie.entities`).
"""

from fanout.sie.entities import (
    RawEntity,
    aggressive_entity_target,
    select_key_entities,
)


def _raw(name, urls, variants=None):
    return RawEntity(name=name, source_urls=list(urls), ner_variants=list(variants or [name]))


# --- aggressive_entity_target ---------------------------------------------

def test_target_is_max_distinct_per_competitor():
    # p1 carries 3 distinct entities, p2 carries 2, p3 carries 1 → aggressive = 3.
    raw = [
        _raw("A", ["p1", "p2", "p3"]),
        _raw("B", ["p1", "p2"]),
        _raw("C", ["p1"]),
    ]
    assert aggressive_entity_target(raw) == 3


def test_target_excludes_spam_outlier():
    # spam page has 5 distinct entities; four normal pages have 1 each.
    # counts = [5,1,1,1,1], median 1, 5 > 3×1 dropped → max of the rest = 1.
    raw = [_raw(f"E{i}", ["spam"]) for i in range(5)]
    raw += [_raw(f"N{i}", [f"n{i}"]) for i in range(4)]
    assert aggressive_entity_target(raw) == 1


def test_target_kept_names_filter():
    raw = [
        _raw("Kept", ["p1", "p2"]),
        _raw("Junk", ["p1", "p2", "p3"]),  # dropped by pass-2 categorization
    ]
    assert aggressive_entity_target(raw) == 2                 # unfiltered: p1=2, p2=2
    assert aggressive_entity_target(raw, {"kept"}) == 1       # only kept: p1=1, p2=1


def test_target_zero_when_empty():
    assert aggressive_entity_target([]) == 0


# --- select_key_entities ---------------------------------------------------

class _E:
    def __init__(self, term, score):
        self.term = term
        self.recommendation_score = score


def test_select_sizes_to_benchmark_and_orders_by_score():
    ents = [_E("a", 0.2), _E("b", 0.9), _E("c", 0.5), _E("d", 0.7)]
    assert select_key_entities(ents, benchmark=2, default=12, cap=30) == ["b", "d"]


def test_select_falls_back_to_default_when_benchmark_zero():
    ents = [_E(f"e{i}", 1.0 - i * 0.01) for i in range(20)]
    assert len(select_key_entities(ents, benchmark=0, default=5, cap=30)) == 5


def test_select_clamps_to_available_and_cap():
    many = [_E(f"e{i}", 1.0) for i in range(40)]
    assert len(select_key_entities(many, benchmark=100, default=12, cap=30)) == 30
    few = [_E("a", 1.0), _E("b", 0.9), _E("c", 0.8)]
    assert len(select_key_entities(few, benchmark=5, default=12, cap=30)) == 3


def test_select_skips_blank_terms():
    ents = [_E("  ", 1.0), _E("real", 0.5)]
    assert select_key_entities(ents, benchmark=2, default=12, cap=30) == ["real"]
