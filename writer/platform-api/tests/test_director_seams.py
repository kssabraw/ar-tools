"""Unit tests for services.director.seams — pure predicates over the read
model (build spec §5, §12). No DB, no mocks: each predicate is a pure
function over a hand-built model dict."""

from __future__ import annotations

from datetime import date

from services.director import seams as S

TODAY = date(2026, 8, 28)


def test_age_days_handles_date_and_timestamp_and_none():
    assert S.age_days("2026-08-20", TODAY) == 8
    assert S.age_days("2026-08-20T10:00:00Z", TODAY) == 8
    assert S.age_days(None, TODAY) is None
    assert S.age_days("not-a-date", TODAY) is None


def test_strategist_approved_unplaced_fires_at_threshold_silent_below():
    model = {
        "strategy": {
            "approved_unplaced": [
                {"review_id": "r1", "client_id": "c1", "proposal_index": 0,
                 "title": "Fund a link round", "since": "2026-08-25"},   # 3 days old
                {"review_id": "r2", "client_id": "c2", "proposal_index": 1,
                 "title": "Reoptimize page", "since": "2026-08-27"},     # 1 day old
            ]
        }
    }
    flags = S.strategist_approved_unplaced(model, TODAY, threshold_days=3)
    assert len(flags) == 1
    flag = flags[0]
    assert flag["seam"] == "strategist_approved_unplaced"
    assert flag["client_id"] == "c1"
    assert flag["ident"] == "r1:0"
    assert flag["evidence"]["days_unplaced"] == 3
    assert flag["evidence"]["title"] == "Fund a link round"


def test_strategist_approved_unplaced_ignores_missing_since():
    model = {"strategy": {"approved_unplaced": [
        {"review_id": "r1", "client_id": "c1", "proposal_index": 0, "title": "x", "since": None},
    ]}}
    assert S.strategist_approved_unplaced(model, TODAY, threshold_days=3) == []


def test_autonomy_proposed_unactioned_fires_at_threshold():
    model = {
        "autonomy": {
            "proposed_unactioned": [
                {"run_id": "run1", "client_id": "c1", "action": "reoptimize_page",
                 "keyword": "roof repair", "since": "2026-08-20"},   # 8 days old, threshold 7
                {"run_id": "run2", "client_id": "c2", "action": "generate_local_seo_page",
                 "keyword": "plumber", "since": "2026-08-24"},       # 4 days old
            ]
        }
    }
    flags = S.autonomy_proposed_unactioned(model, TODAY, threshold_days=7)
    assert len(flags) == 1
    assert flags[0]["client_id"] == "c1"
    assert flags[0]["ident"] == "run1:reoptimize_page"
    assert flags[0]["evidence"]["keyword"] == "roof repair"


def test_qa_idle_none_provider_produces_no_flag():
    assert S.qa_idle({"qa": None}, TODAY, threshold_days=7) is None


def test_qa_idle_silent_when_entries_recorded():
    model = {"qa": {"entered_in_qa_count": 2, "last_entered_at": "2026-08-27",
                     "reviews_considered": 5}}
    assert S.qa_idle(model, TODAY, threshold_days=7) is None


def test_qa_idle_fires_when_nothing_entered_past_threshold():
    model = {"qa": {"entered_in_qa_count": 0, "last_entered_at": "2026-08-01",
                     "reviews_considered": 3}}
    flag = S.qa_idle(model, TODAY, threshold_days=7)
    assert flag is not None
    assert flag["seam"] == "qa_idle"
    assert flag["client_id"] is None  # portfolio-scoped, never a client
    assert flag["ident"] == "portfolio"


def test_qa_idle_fires_when_nothing_ever_recorded():
    model = {"qa": {"entered_in_qa_count": 0, "last_entered_at": None, "reviews_considered": 0}}
    flag = S.qa_idle(model, TODAY, threshold_days=7)
    assert flag is not None
    assert flag["evidence"]["last_entered_at"] is None


def test_qa_idle_silent_when_recent_entry_under_threshold():
    model = {"qa": {"entered_in_qa_count": 0, "last_entered_at": "2026-08-25", "reviews_considered": 1}}
    # 3 days old, entered_in_qa_count is 0 in this window's tail but the most
    # recent entry is inside the threshold — not idle yet.
    assert S.qa_idle(model, TODAY, threshold_days=7) is None


def test_content_shipped_degraded_shapes_pre_gathered_evidence():
    model = {"content": {"degraded": [
        {"client_id": "c1", "ident": "run:abc", "kind": "degraded_run",
         "keyword": "roof repair", "schema_version": "1.9-degraded", "since": "2026-08-28"},
    ]}}
    flags = S.content_shipped_degraded(model)
    assert len(flags) == 1
    assert flags[0]["seam"] == "content_shipped_degraded"
    assert flags[0]["threshold_days"] == 0  # immediate — no dwell
    assert flags[0]["evidence"]["kind"] == "degraded_run"


def test_duplicate_target_shapes_pre_gathered_evidence():
    model = {"duplicates": {"duplicates": [
        {"client_id": "c1", "target_key": "kw:roof repair",
         "items": [{"kind": "task", "id": "t1", "source": "action_plan"},
                   {"kind": "task", "id": "t2", "source": "strategy_proposal"}]},
    ]}}
    flags = S.duplicate_target(model)
    assert len(flags) == 1
    assert flags[0]["seam"] == "duplicate_target"
    assert flags[0]["ident"] == "kw:roof repair"
    assert len(flags[0]["evidence"]["items"]) == 2


def test_unwatched_seam_e1_never_silently_dropped():
    model = {"producers": {"unwatched_seam": {"weird_new_source": 3}}}
    flags = S.unwatched_seam(model)
    assert len(flags) == 1
    assert flags[0]["seam"] == "unwatched_seam"
    assert flags[0]["client_id"] is None
    assert flags[0]["evidence"] == {"source": "weird_new_source", "open_count": 3}


def test_unwatched_seam_empty_when_none_unwatched():
    assert S.unwatched_seam({"producers": {"unwatched_seam": None}}) == []
    assert S.unwatched_seam({"producers": {}}) == []


def test_compute_flags_assembles_every_predicate():
    model = {
        "strategy": {"approved_unplaced": [
            {"review_id": "r1", "client_id": "c1", "proposal_index": 0, "title": "x", "since": "2026-08-20"},
        ]},
        "autonomy": {"proposed_unactioned": []},
        "qa": {"entered_in_qa_count": 1, "last_entered_at": "2026-08-27", "reviews_considered": 1},
        "content": {"degraded": []},
        "duplicates": {"duplicates": []},
        "producers": {"unwatched_seam": {"mystery": 1}},
    }
    thresholds = {"approved_unplaced_days": 3, "qa_idle_days": 7, "autonomy_unactioned_days": 7}
    result = S.compute_flags(model, TODAY, thresholds)
    seams_seen = {f["seam"] for f in result["flags"]}
    assert seams_seen == {"strategist_approved_unplaced", "unwatched_seam"}
    assert result["count"] == 2
