"""Unit tests for services.keyword_portal — the Unified Keyword Portal fan-out."""

from __future__ import annotations

from unittest.mock import patch

from services import keyword_portal as kp


# ── fake supabase (chainable query builder) ──────────────────────────────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, select_data):
        self._select_data = select_data
        self._is_select = False

    def select(self, *a, **k):
        self._is_select = True
        return self

    def upsert(self, *a, **k):
        self._is_select = False
        return self

    def insert(self, *a, **k):
        self._is_select = False
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        return _Resp(self._select_data if self._is_select else [])


class _Supabase:
    def __init__(self, tables):
        self._tables = tables  # table name -> rows returned by a select

    def table(self, name):
        return _Table(self._tables.get(name, []))


# ── pure helpers ─────────────────────────────────────────────────────────────
def test_split_keywords_splits_dedupes_trims():
    out = kp.split_keywords(
        ["plumber near me, emergency plumber\nplumber near me", "  ", "hvac"]
    )
    assert out == ["plumber near me", "emergency plumber", "hvac"]


def test_partition_new_case_insensitive():
    new, skipped = kp.partition_new(["A", "b", "C"], {"a", "c"})
    assert new == ["b"]
    assert skipped == 2


# ── run_portal orchestration / isolation ─────────────────────────────────────
def test_run_portal_fans_out_to_selected_targets_only():
    with patch.object(kp, "add_to_organic", return_value=kp._result(2, 0, "enqueued")) as org, \
         patch.object(kp, "add_to_maps",
                      return_value=kp._result(2, 0, "blocked", "maps_not_configured")) as mp, \
         patch.object(kp, "add_to_brand") as br:
        out = kp.run_portal("c1", ["a", "b"], ["organic", "maps"], True, "u1")
    assert set(out) == {"organic", "maps"}
    org.assert_called_once()
    mp.assert_called_once()
    br.assert_not_called()  # brand not selected
    assert out["maps"]["blocker"] == "maps_not_configured"


def test_run_portal_isolates_a_failing_target():
    with patch.object(kp, "add_to_organic", side_effect=RuntimeError("boom")), \
         patch.object(kp, "add_to_brand", return_value=kp._result(1, 0, "enqueued")):
        out = kp.run_portal("c1", ["a"], ["organic", "brand"], True, "u1")
    assert out["organic"]["scan"] == "error"
    assert out["brand"]["scan"] == "enqueued"  # the other target still ran


# ── organic ──────────────────────────────────────────────────────────────────
def test_add_to_organic_enqueues_backfill_for_new_only():
    fake = _Supabase({"tracked_keywords": [{"keyword": "old"}]})
    with patch.object(kp, "get_supabase", return_value=fake), \
         patch.object(kp.rank_materialize, "enqueue_materialize") as mat, \
         patch.object(kp.keyword_market, "enqueue_keyword_market") as mkt:
        res = kp.add_to_organic("c1", ["old", "new1"], "u1", run_scans=True)
    assert res["added"] == 1 and res["skipped_duplicates"] == 1
    assert res["scan"] == "enqueued"
    mat.assert_called_once_with("c1")
    mkt.assert_called_once_with("c1")


def test_add_to_organic_skips_when_nothing_new():
    fake = _Supabase({"tracked_keywords": [{"keyword": "old"}]})
    with patch.object(kp, "get_supabase", return_value=fake), \
         patch.object(kp.rank_materialize, "enqueue_materialize") as mat, \
         patch.object(kp.keyword_market, "enqueue_keyword_market") as mkt:
        res = kp.add_to_organic("c1", ["old"], "u1", run_scans=True)
    assert res["scan"] == "skipped" and res["added"] == 0
    mat.assert_not_called()
    mkt.assert_not_called()


# ── maps (added regardless; scan gated on config) ────────────────────────────
def test_add_to_maps_blocked_but_added_when_unconfigured():
    fake = _Supabase({"maps_keywords": [], "maps_scan_configs": []})
    with patch.object(kp, "get_supabase", return_value=fake), \
         patch.object(kp.local_dominator, "enqueue_maps_scan") as scan:
        res = kp.add_to_maps("c1", ["plumber"], run_scans=True)
    assert res["added"] == 1  # keyword still added
    assert res["scan"] == "blocked" and res["blocker"] == "maps_not_configured"
    scan.assert_not_called()


def test_add_to_maps_enqueues_when_configured():
    fake = _Supabase({
        "maps_keywords": [],
        "maps_scan_configs": [{"google_place_id": "p", "center_lat": 1.0, "center_lng": 2.0}],
    })
    with patch.object(kp, "get_supabase", return_value=fake), \
         patch.object(kp.local_dominator, "enqueue_maps_scan") as scan:
        res = kp.add_to_maps("c1", ["plumber"], run_scans=True)
    assert res["scan"] == "enqueued"
    scan.assert_called_once_with("c1", trigger="manual")


# ── brand (scan only the new keyword ids) ────────────────────────────────────
def test_add_to_brand_scans_only_new_keywords():
    created = [{"id": "k1", "keyword": "new1"}, {"id": "k2", "keyword": "new2"}]
    with patch.object(kp.brand_service, "add_keywords", return_value=created), \
         patch.object(kp.brand_service, "start_scan") as scan:
        res = kp.add_to_brand("c1", ["new1", "new2", "dup"], "u1", run_scans=True)
    assert res["added"] == 2 and res["skipped_duplicates"] == 1
    assert res["scan"] == "enqueued"
    scan.assert_called_once_with("c1", ["k1", "k2"], None, False, "u1")


def test_add_to_brand_no_scan_when_nothing_new():
    with patch.object(kp.brand_service, "add_keywords", return_value=[]), \
         patch.object(kp.brand_service, "start_scan") as scan:
        res = kp.add_to_brand("c1", ["dup"], "u1", run_scans=True)
    assert res["scan"] == "skipped" and res["added"] == 0
    scan.assert_not_called()
