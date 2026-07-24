"""Unit tests for the Keyword Research → Content Scheduler handoff (pure parts)."""

from services import keyword_research_handoff as h


def test_prepare_selection_dedupes_and_caps():
    sel = h.prepare_selection(["Roof Repair", "roof repair", "  ", "gutter cleaning"], cap=10)
    assert sel == ["Roof Repair", "gutter cleaning"]  # case-insensitive dedupe, blanks dropped


def test_prepare_selection_respects_cap():
    assert h.prepare_selection(["a", "b", "c", "d"], cap=2) == ["a", "b"]


def test_prepare_selection_empty():
    assert h.prepare_selection([], cap=10) == []
    assert h.prepare_selection(None, cap=10) == []


def test_prepare_selection_non_positive_cap_yields_nothing():
    # The setting is a maximum: 0 means "none", never "unlimited".
    assert h.prepare_selection(["a", "b"], cap=0) == []
    assert h.prepare_selection(["a", "b"], cap=-5) == []


def test_dedupe_keywords_preserves_order_without_capping():
    assert h.dedupe_keywords(["b", "B", "a", "", None, "c"]) == ["b", "a", "c"]


def test_map_intent_maps_dataforseo_values_through():
    # DataForSEO's search_intent vocabulary is a subset of fanout.cluster_intent,
    # so every measured value survives — this drives CTA/section/length choices.
    for v in ("transactional", "commercial", "informational", "navigational"):
        assert h.map_intent(v) == v
    assert h.map_intent("COMMERCIAL") == "commercial"
    assert h.map_intent(" transactional ") == "transactional"


def test_map_intent_falls_back_for_unknown_or_missing():
    for v in (None, "", "nonsense", "buy-now"):
        assert h.map_intent(v) == "informational"


def test_build_handoff_rows_carries_measured_intent():
    metrics = {
        "buy roof restoration": {"search_intent": "transactional"},
        "roof restoration cost": {"search_intent": "commercial"},
        "what is roof restoration": {},          # no intent stored -> default
    }
    _, clusters = h.build_handoff_rows(
        ["buy roof restoration", "roof restoration cost", "what is roof restoration"],
        metrics, "sess-1", "topic-1")
    assert [c["intent"] for c in clusters] == [
        "transactional", "commercial", "informational"]
    assert all(c["intent"] in h.VALID_CLUSTER_INTENTS for c in clusters)


def test_build_handoff_rows_one_cluster_per_keyword_linked():
    metrics = {"emergency plumber": {"volume": 800, "cpc_usd": 12.0,
                                     "keyword_difficulty": 25, "competition_index": 60}}
    kw_rows, cluster_rows = h.build_handoff_rows(
        ["emergency plumber", "blocked drain"], metrics, "sess-1", "topic-1")
    assert len(kw_rows) == len(cluster_rows) == 2

    # Each cluster's primary_keyword_id points at its keyword row; names match.
    for kw, cl in zip(kw_rows, cluster_rows):
        assert cl["primary_keyword_id"] == kw["id"]
        assert cl["name"] == kw["keyword"]
        assert cl["intent"] == "informational"          # no search_intent in metrics
        assert cl["topic_id"] == "topic-1"
        assert kw["session_id"] == "sess-1"
        assert kw["is_primary_for_cluster"] is True
        assert kw["sources"] == ["keyword_research"]

    # Metrics carried where present, null otherwise.
    ep = next(k for k in kw_rows if k["keyword"] == "emergency plumber")
    assert ep["volume"] == 800 and ep["keyword_difficulty"] == 25
    bd = next(k for k in kw_rows if k["keyword"] == "blocked drain")
    assert bd["volume"] is None

    # Ids are distinct across keywords and clusters (FK cycle resolved up front).
    ids = [k["id"] for k in kw_rows] + [c["id"] for c in cluster_rows]
    assert len(set(ids)) == len(ids)
