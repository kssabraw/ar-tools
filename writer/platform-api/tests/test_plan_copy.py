"""Unit tests for fanout.writer.plan_copy — the pure row-builders that remap a
session's topics/clusters/primary-keywords onto a new session with fresh ids.

No network / no DB: the four build_* helpers are pure. The orchestrator's IO
(create_session + chunked insert/upsert) is covered by integration testing."""

from __future__ import annotations

from itertools import count

import pytest

from fanout.writer import plan_copy


@pytest.fixture
def id_fn():
    """Deterministic id generator so remapping is assertable."""
    c = count(1)
    return lambda: f"new-{next(c)}"


# ── topics ──────────────────────────────────────────────────────────────────


def test_build_topic_rows_remaps_and_preserves_fields(id_fn):
    topics = [
        {"id": "t1", "name": "Uses", "rationale": "why", "relationship_type": "use_case",
         "source": "llm_proposed", "is_broader_class": False,
         "is_gated_for_competitor_mining": True, "supporting_evidence": "ev"},
    ]
    rows, tmap = plan_copy.build_topic_rows(topics, "sess-new", id_fn=id_fn)
    assert tmap == {"t1": "new-1"}
    assert rows[0] == {
        "id": "new-1", "session_id": "sess-new", "name": "Uses", "rationale": "why",
        "relationship_type": "use_case", "source": "llm_proposed",
        "is_broader_class": False, "is_gated_for_competitor_mining": True,
        "supporting_evidence": "ev",
    }


def test_build_topic_rows_defaults_required_enums(id_fn):
    rows, _ = plan_copy.build_topic_rows(
        [{"id": "t1", "name": "X"}], "sess-new", id_fn=id_fn)
    assert rows[0]["relationship_type"] == "property_or_mechanism"
    assert rows[0]["source"] == "llm_proposed"


# ── clusters ────────────────────────────────────────────────────────────────


def test_build_cluster_rows_nulls_primary_and_maps_topic(id_fn):
    tmap = {"t1": "T1"}
    clusters = [
        {"id": "c1", "topic_id": "t1", "name": "A", "primary_keyword_id": "k1",
         "intent": "commercial", "suggested_h2s": ["h"], "slug": "a"},
    ]
    rows, cmap, pkmap = plan_copy.build_cluster_rows(clusters, tmap, id_fn=id_fn)
    assert cmap == {"c1": "new-1"}
    assert pkmap == {"k1": "new-2"}
    row = rows[0]
    assert row["id"] == "new-1"
    assert row["topic_id"] == "T1"
    # primary_keyword_id is deferred to the back-fill pass.
    assert row["primary_keyword_id"] is None
    assert row["intent"] == "commercial"
    assert row["suggested_h2s"] == ["h"]
    assert row["slug"] == "a"


def test_build_cluster_rows_skips_unmapped_topic(id_fn):
    rows, cmap, pkmap = plan_copy.build_cluster_rows(
        [{"id": "c1", "topic_id": "ghost", "name": "A", "primary_keyword_id": "k1"}],
        {"t1": "T1"}, id_fn=id_fn)
    assert rows == [] and cmap == {} and pkmap == {}


def test_build_cluster_rows_gap_placeholder_has_no_primary(id_fn):
    rows, cmap, pkmap = plan_copy.build_cluster_rows(
        [{"id": "c1", "topic_id": "t1", "name": "gap", "primary_keyword_id": None,
          "is_gap_placeholder": True}],
        {"t1": "T1"}, id_fn=id_fn)
    assert pkmap == {}
    assert rows[0]["primary_keyword_id"] is None
    assert rows[0]["is_gap_placeholder"] is True
    assert cmap == {"c1": "new-1"}


# ── keywords ────────────────────────────────────────────────────────────────


def test_build_keyword_rows_remaps_all_refs():
    tmap = {"t1": "T1"}
    cmap = {"c1": "C1"}
    pkmap = {"k1": "K1"}
    kws = [
        {"id": "k1", "topic_id": "t1", "cluster_id": "c1", "keyword": "retatrutide dosage",
         "volume": 90, "cpc_usd": 1.2, "status": "active", "sources": ["labs"]},
    ]
    rows = plan_copy.build_keyword_rows(kws, "sess-new", tmap, cmap, pkmap)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "K1"
    assert row["session_id"] == "sess-new"
    assert row["topic_id"] == "T1"
    assert row["cluster_id"] == "C1"
    assert row["keyword"] == "retatrutide dosage"
    assert row["is_primary_for_cluster"] is True
    assert row["volume"] == 90


def test_build_keyword_rows_skips_unmapped():
    # A keyword not in pk_map (not a primary we copied) is dropped.
    rows = plan_copy.build_keyword_rows(
        [{"id": "kX", "topic_id": "t1", "cluster_id": "c1", "keyword": "x"}],
        "s", {"t1": "T1"}, {"c1": "C1"}, {"k1": "K1"})
    assert rows == []


# ── back-fill wiring (the two sides meet) ───────────────────────────────────


def test_build_primary_backfill_wires_cluster_to_new_keyword():
    clusters = [
        {"id": "c1", "topic_id": "t1", "primary_keyword_id": "k1"},
        {"id": "c2", "topic_id": "t1", "primary_keyword_id": None},   # no primary
    ]
    cmap = {"c1": "C1", "c2": "C2"}
    pkmap = {"k1": "K1"}
    backfill = plan_copy.build_primary_backfill([], clusters, cmap, pkmap)
    assert backfill == [{"id": "C1", "primary_keyword_id": "K1"}]


def test_end_to_end_ids_are_consistent(id_fn):
    """The cluster the copy inserts and the keyword it points at share the remapped id —
    the invariant the scheduler relies on (cluster.primary_keyword_id -> keywords.id)."""
    topics = [{"id": "t1", "name": "Uses"}]
    clusters = [{"id": "c1", "topic_id": "t1", "name": "A", "primary_keyword_id": "k1"}]
    keywords = [{"id": "k1", "topic_id": "t1", "cluster_id": "c1", "keyword": "kw"}]

    _, tmap = plan_copy.build_topic_rows(topics, "S", id_fn=id_fn)
    _, cmap, pkmap = plan_copy.build_cluster_rows(clusters, tmap, id_fn=id_fn)
    kw_rows = plan_copy.build_keyword_rows(keywords, "S", tmap, cmap, pkmap)
    backfill = plan_copy.build_primary_backfill([], clusters, cmap, pkmap)

    new_kw_id = kw_rows[0]["id"]
    assert backfill[0]["primary_keyword_id"] == new_kw_id
    assert backfill[0]["id"] == cmap["c1"]
