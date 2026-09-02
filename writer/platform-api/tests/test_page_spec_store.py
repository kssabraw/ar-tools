"""Tests for the page-spec store's pure parts + its resolution rule
(edits stick; identical rebuilds don't create versions; material changes do)."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import page_spec as ps  # noqa: E402
from services import page_spec_store as store  # noqa: E402

_SERP = {"serp_word_target": 1058, "serp_avg_word_count": 882, "serp_urls": ["a"] * 15}
_CLIENT = {"id": "client-1", "page_structures": {}}


def _spec(serp=_SERP):
    return ps.build_spec(client_id="client-1", keyword="k", location="L", location_code=1,
                         serp_analysis=serp, reference_entry=None, reference_page_type=None,
                         fallback_target=1200)


def test_materially_different_ignores_timestamps_but_sees_band_changes():
    a, b = _spec(), _spec()
    b["generated_at"] = "2030-01-01T00:00:00+00:00"
    b["provenance"]["serp"]["from_cache"] = True
    assert not store.materially_different(a, b)
    c = _spec({"serp_word_target": 1571, "serp_avg_word_count": 1309, "serp_urls": ["a"] * 15})
    assert store.materially_different(a, c)
    d = _spec()
    d["sections"][0]["max_words"] += 10
    assert store.materially_different(a, d)
    assert store.materially_different(None, a) and not store.materially_different(None, None)


def test_pick_reference_prefers_the_first_usable_type_else_first_present():
    good = {"status": "complete", "url": "https://x.com/a/",
            "analysis": {"outline": [{"level": "H2", "heading": "h", "intent": "hero", "word_count": 120}] * 4}}
    bad = {"status": "complete", "url": "https://staging.x.com/", "analysis": {"outline": [{"level": "H2", "heading": "h", "word_count": 400}] * 4}}
    assert store.pick_reference({"local_landing": bad, "location": good}) == (good, "location")
    assert store.pick_reference({"local_landing": bad}) == (bad, "local_landing")
    assert store.pick_reference({}) == (None, None)
    assert store.pick_reference(None) == (None, None)


def test_public_spec_carries_row_identity():
    row = {"id": "spec-1", "version": 3, "edited_at": None, "spec": _spec()}
    out = store.public_spec(row)
    assert out["id"] == "spec-1" and out["version"] == 3 and out["edited_at"] is None
    assert out["total"] == row["spec"]["total"]
    assert "id" not in row["spec"]  # never mutates the stored document


def test_resolve_spec_uses_an_edited_active_spec_verbatim():
    edited = {"id": "spec-9", "version": 2, "edited_at": "2026-09-02T00:00:00+00:00", "spec": _spec()}
    with patch.object(store, "get_active", return_value=edited), \
         patch.object(store, "save_new_version") as save:
        out = store.resolve_spec(_CLIENT, "k", "L", 1, {"serp_word_target": 2400, "serp_urls": ["a"] * 9}, 1200)
    assert out["id"] == "spec-9" and out["total"]["target"] == 1058
    save.assert_not_called()


def test_resolve_spec_keeps_an_identical_unedited_spec_and_saves_a_changed_one():
    active = {"id": "spec-1", "version": 1, "edited_at": None, "spec": _spec()}
    with patch.object(store, "get_active", return_value=active), \
         patch.object(store, "save_new_version") as save:
        out = store.resolve_spec(_CLIENT, "k", "L", 1, _SERP, 1200)
    assert out["id"] == "spec-1"
    save.assert_not_called()
    changed = {"serp_word_target": 1571, "serp_avg_word_count": 1309, "serp_urls": ["a"] * 15}
    with patch.object(store, "get_active", return_value=active), \
         patch.object(store, "save_new_version", side_effect=lambda *a, **k: {"id": "spec-2", "version": 2, "edited_at": None, "spec": a[4]}) as save:
        out = store.resolve_spec(_CLIENT, "k", "L", 1, changed, 1200)
    assert out["id"] == "spec-2" and out["total"]["target"] == 1571
    assert save.call_args.kwargs["previous"] is active


def test_resolve_spec_force_rebuild_ignores_the_edit():
    edited = {"id": "spec-9", "version": 2, "edited_at": "2026-09-02T00:00:00+00:00", "spec": _spec()}
    with patch.object(store, "get_active", return_value=edited) as get_active, \
         patch.object(store, "save_new_version", side_effect=lambda *a, **k: {"id": "spec-10", "version": 3, "edited_at": None, "spec": a[4]}):
        out = store.resolve_spec(_CLIENT, "k", "L", 1, _SERP, 1200, force_rebuild=True)
    get_active.assert_not_called()
    assert out["id"] == "spec-10" and out["edited_at"] is None


def test_save_edit_rejects_an_infeasible_spec_without_saving():
    bad = _spec()
    bad["sections"] = [dict(s, min_words=900) for s in bad["sections"]]
    with patch.object(store, "save_new_version") as save:
        out, errors = store.save_edit(_CLIENT, "k", "L", 1, bad, "user-1")
    assert "section_minimums_exceed_page_max" in errors
    save.assert_not_called()
    good = _spec()
    with patch.object(store, "save_new_version", side_effect=lambda *a, **k: {"id": "e1", "version": 2, "edited_at": "now", "spec": a[4]}) as save:
        out, errors = store.save_edit(_CLIENT, "k", "L", 1, good, "user-1")
    assert errors == [] and out["id"] == "e1"
    assert save.call_args.kwargs["edited"] is True and save.call_args.kwargs["edited_by"] == "user-1"


def test_summarize_lengths_rolls_up_target_vs_actual():
    from services import page_spec_service as svc
    rows = [
        {"id": "a", "keyword": "k1", "target_words": 1000, "actual_words": 1050, "length_status": "in_band", "created_at": "t1"},
        {"id": "b", "keyword": "k2", "target_words": 1000, "actual_words": 1500, "length_status": "over_length", "created_at": "t2"},
        {"id": "c", "keyword": "k3", "target_words": None, "actual_words": None, "length_status": None, "created_at": "t3"},
    ]
    out = svc.summarize_lengths(rows)
    assert out["pages"] == 3 and out["with_spec"] == 2
    assert out["in_band"] == 1 and out["over_length"] == 1 and out["under_length"] == 0
    assert out["in_band_pct"] == 50.0
    assert out["avg_overage_pct"] == 27.5   # (+5% + 50%) / 2
    assert [r["id"] for r in out["recent"]] == ["a", "b"]
    assert svc.summarize_lengths([])["in_band_pct"] is None
