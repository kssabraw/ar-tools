"""Unit tests for the DataForSEO Maps geo-grid provider (Module #5 switchover).

All pure / mocked — never hits the API. The key regression guard is the
competitor parity test: the DataForSEO per-pin builders must produce output
FIELD-FOR-FIELD identical to the proven Local Dominator builders when fed the
same underlying scan.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings  # noqa: E402
from services import local_dominator as ld  # noqa: E402
from services import maps_dataforseo as m  # noqa: E402
from services import maps_grid  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# in_circle / build_pin_tasks — circle masking + request bodies
# ---------------------------------------------------------------------------
def test_in_circle_counts_match_presets():
    # 3/5/7-mile radii → 7/11/15 grids → 37/97/177 in-circle pins.
    for radius, n, expected in ((3, 7, 37), (5, 11, 97), (7, 15, 177)):
        pts = maps_grid.generate_grid_points(40.0, -80.0, radius)
        count = sum(1 for p in pts if m.in_circle(p.row, p.col, n))
        assert count == expected, (radius, count)


def test_build_pin_tasks_masks_and_shapes_body():
    pts = maps_grid.generate_grid_points(40.0, -80.0, 3)  # n=7
    bodies = m.build_pin_tasks({"serp_device": "desktop"}, ["plumber"], pts, "15z", scan_id="SCAN")
    assert len(bodies) == 37  # in-circle only
    b = bodies[0]
    assert b["location_coordinate"].endswith(",15z")
    assert b["depth"] == settings.maps_dfs_depth
    assert b["device"] == "desktop"
    assert b["os"] == "windows"
    assert b["language_code"] == settings.dataforseo_default_language_code
    # tag = "<scan_id>:<kw_idx>:<row>:<col>"
    assert b["tag"].startswith("SCAN:0:")
    assert len(b["tag"].split(":")) == 4


def test_build_pin_tasks_multi_keyword_and_device_map():
    pts = maps_grid.generate_grid_points(40.0, -80.0, 3)  # 37 in-circle
    assert len(m.build_pin_tasks({}, ["k1", "k2"], pts, "15z")) == 74
    assert m.build_pin_tasks({"serp_device": "mobile"}, ["k"], pts, "15z")[0]["device"] == "mobile"
    # 'both' collapses to desktop (no mobile expansion in v1)
    assert m.build_pin_tasks({"serp_device": "both"}, ["k"], pts, "15z")[0]["device"] == "desktop"


# ---------------------------------------------------------------------------
# parse_pin_items
# ---------------------------------------------------------------------------
def _biz(rec):
    return dict(zip(m._PIN_FIELDS, rec))


def test_parse_pin_items_rank_ordering_and_client_position():
    items = [
        {"type": "maps_search", "rank_group": 2, "place_id": "B", "title": "B",
         "rating": {"value": 4.0, "votes_count": 50}, "category": "Roofer",
         "domain": "b.com", "url": "https://b.com/x", "phone": "2",
         "latitude": 1.1, "longitude": 2.2},
        {"type": "maps_search", "rank_group": 1, "place_id": "US", "title": "Us",
         "rating": {"value": 5.0, "votes_count": 10}, "category": "Roofer",
         "domain": "us.com", "phone": "1", "latitude": 1.0, "longitude": 2.0},
        {"type": "local_pack", "place_id": "X"},  # non-maps_search → ignored
        {"type": "maps_search", "rank_group": 3, "place_id": "C", "title": "C", "rating": {}},
    ]
    rank, ordered = m.parse_pin_items(items, "US")
    assert rank == 1  # US is the rank_group=1 item → position 0 → rank 1
    assert [r[0] for r in ordered] == ["US", "B", "C"]  # ordered by rank_group
    # website prefers full url, falls back to bare domain
    assert _biz(ordered[1])["website"] == "https://b.com/x"
    assert _biz(ordered[0])["website"] == "us.com"
    # lat/lng carried
    assert _biz(ordered[0])["lat"] == 1.0 and _biz(ordered[0])["lng"] == 2.0
    assert _biz(ordered[1])["reviews"] == 50 and _biz(ordered[1])["rating"] == 4.0


def test_parse_pin_items_client_absent_is_none():
    items = [{"type": "maps_search", "rank_group": 1, "place_id": "A", "title": "A", "rating": {}}]
    rank, ordered = m.parse_pin_items(items, "US")
    assert rank is None
    assert [r[0] for r in ordered] == ["A"]


def test_parse_pin_items_gps_coordinates_fallback():
    items = [{"type": "maps_search", "rank_group": 1, "place_id": "G", "title": "G",
              "rating": {}, "gps_coordinates": {"latitude": 9.0, "longitude": 8.0}}]
    _, ordered = m.parse_pin_items(items, None)
    assert _biz(ordered[0])["lat"] == 9.0 and _biz(ordered[0])["lng"] == 8.0


def test_parse_pin_items_empty():
    assert m.parse_pin_items([], "US") == (None, [])


# ---------------------------------------------------------------------------
# assemble_rank_grid / summarize_rank_grid
# ---------------------------------------------------------------------------
def test_assemble_rank_grid_places_ranks_and_holes():
    pin_rows = [
        {"row_idx": 0, "col_idx": 1, "client_rank": 2},
        {"row_idx": 1, "col_idx": 1, "client_rank": 1},
        {"row_idx": 2, "col_idx": 1, "client_rank": None},  # unranked/failed → hole
    ]
    grid = m.assemble_rank_grid(pin_rows, 3)
    assert grid[0][1] == 2 and grid[1][1] == 1 and grid[2][1] is None
    assert grid[0][0] is None  # cell with no pin row → null


def test_summarize_rank_grid_counts_average_incircle_only():
    grid = [[None, 2, None], [None, 1, None], [None, None, None]]  # n=3 → all in-circle
    s = m.summarize_rank_grid(grid)
    assert s["total_pins"] == 9
    assert s["found_pins"] == 2
    assert s["top3_pins"] == 2 and s["top10_pins"] == 2
    assert s["computed_average"] == 1.5


def test_summarize_rank_grid_excludes_out_of_circle():
    grid = [[None] * 5 for _ in range(5)]
    grid[0][0] = 1  # a corner — outside the inscribed circle for n=5
    s = m.summarize_rank_grid(grid)
    assert s["total_pins"] == 21  # 25 minus 4 corners
    assert s["found_pins"] == 0   # the corner rank is ignored


def test_summarize_rank_grid_empty():
    assert m.summarize_rank_grid([])["computed_average"] is None


# ---------------------------------------------------------------------------
# Competitor parity — the key regression guard.
# Express the SAME scan two ways (LD compressed_grid/detailsArray vs DataForSEO
# per-pin lists) and require the two builder families to agree field-for-field.
# ---------------------------------------------------------------------------
_BIZ = {
    "US": {"place_id": "US", "name": "Our Biz", "rating": 5.0, "reviews": 10,
           "primary_category": "Roofer", "website": "https://us.example",
           "phone": "111", "lat": -37.80, "lng": 144.90},
    "A": {"place_id": "A", "name": "Comp A", "rating": 4.5, "reviews": 100,
          "primary_category": "Roofer", "website": "https://a.example",
          "phone": "222", "lat": -37.81, "lng": 144.91},
    "B": {"place_id": "B", "name": "Comp B", "rating": 4.0, "reviews": 50,
          "primary_category": "Roofer", "website": "https://b.example",
          "phone": "333", "lat": -37.82, "lng": 144.92},
}
# Per in-circle pin (row,col): the business id order (rank order) at that pin.
_ORDER = {
    (0, 1): ["A", "US", "B"],
    (1, 0): ["US", "A", "B"],
    (1, 1): ["B", "A", "US"],
    (1, 2): ["A", "B", "US"],
    (2, 1): ["US", "B", "A"],
}


def _ld_details(b):
    return {"placeId": b["place_id"], "name": b["name"], "rating": b["rating"],
            "ratingCount": b["reviews"], "primaryCategory": b["primary_category"],
            "websiteURL": b["website"], "location": {"latitude": b["lat"], "longitude": b["lng"]}}


def _compact(b):
    # A business dict → the compact pin_data record (in _PIN_FIELDS order).
    return [b["place_id"], b["name"], b["rating"], b["reviews"],
            b["primary_category"], b["website"], b["phone"], b["lat"], b["lng"]]


def _ld_element():
    idx = {"US": 0, "A": 1, "B": 2}
    details = [_ld_details(_BIZ["US"]), _ld_details(_BIZ["A"]), _ld_details(_BIZ["B"])]
    grid = [[[9, 9, 9] for _ in range(3)] for _ in range(3)]  # corners = junk indices
    for (r, c), order in _ORDER.items():
        grid[r][c] = [idx[b] for b in order]
    return {"detailsArray": details, "compressed_grid": grid}


def _dfs_pin_rows():
    return [
        {"row_idx": r, "col_idx": c, "pin_data": [_compact(_BIZ[b]) for b in order]}
        for (r, c), order in _ORDER.items()
    ]


def test_competitor_summary_parity_with_local_dominator():
    ld_out = ld.build_competitor_summary(_ld_element(), our_place_id="US")
    dfs_out = m.build_competitor_summary_dfs(_dfs_pin_rows(), our_place_id="US")
    assert dfs_out == ld_out
    # sanity: our own business excluded, both competitors present
    assert {c["place_id"] for c in dfs_out} == {"A", "B"}


def test_competitors_above_parity_with_local_dominator():
    ld_out = ld.build_competitors_above(_ld_element(), our_place_id="US")
    dfs_out = m.build_competitors_above_dfs(_dfs_pin_rows(), grid_size=3, our_place_id="US")
    assert dfs_out == ld_out


def test_competitor_summary_excludes_client_and_orders():
    out = m.build_competitor_summary_dfs(_dfs_pin_rows(), our_place_id="US")
    # A: positions across the 5 pins → ranks 1,2,2,1,3 (found 5, top3 5, avg 1.8)
    a = next(c for c in out if c["place_id"] == "A")
    assert a["found_pins"] == 5 and a["top3_pins"] == 5 and a["avg_rank"] == 1.8
    assert a["reviews"] == 100 and a["name"] == "Comp A"
    assert [c["place_id"] for c in out] == ["A", "B"]  # A leads on tie-break


# ---------------------------------------------------------------------------
# Pin retry state machine (_handle_posted_pin) — async, no DB.
# ---------------------------------------------------------------------------
_PIN = {"scan_id": "s", "keyword": "k", "row_idx": 1, "col_idx": 1,
        "lat": 1.0, "lng": 2.0, "task_id": "t", "status": "posted", "attempts": 0}


def test_handle_done_stores_rank_and_data(monkeypatch):
    async def fake_fetch(_tid):
        return "done", [{"type": "maps_search", "rank_group": 1, "place_id": "US",
                          "title": "U", "rating": {}}]
    monkeypatch.setattr(m, "fetch_task_result", fake_fetch)
    row = _run(m._handle_posted_pin(dict(_PIN), "US", "15z", 20, "desktop", "s"))
    assert row["status"] == "done" and row["client_rank"] == 1
    assert row["pin_data"][0][0] == "US"


def test_handle_transient_error_leaves_posted(monkeypatch):
    async def fake_fetch(_tid):
        raise RuntimeError("429 rate limit")
    monkeypatch.setattr(m, "fetch_task_result", fake_fetch)
    assert _run(m._handle_posted_pin(dict(_PIN), "US", "15z", 20, "desktop", "s")) is None


def test_handle_pending_leaves_posted(monkeypatch):
    async def fake_fetch(_tid):
        return "pending", None
    monkeypatch.setattr(m, "fetch_task_result", fake_fetch)
    assert _run(m._handle_posted_pin(dict(_PIN), "US", "15z", 20, "desktop", "s")) is None


def test_handle_terminal_error_reposts_until_max(monkeypatch):
    monkeypatch.setattr(settings, "maps_dfs_pin_max_attempts", 3, raising=False)

    async def fake_fetch(_tid):
        return "error", None

    async def fake_post(_bodies):
        return ["newtid"]
    monkeypatch.setattr(m, "fetch_task_result", fake_fetch)
    monkeypatch.setattr(m, "post_pin_tasks", fake_post)

    # attempts 0 → 1 < 3 → repost with a fresh task id
    row = _run(m._handle_posted_pin({**_PIN, "attempts": 0}, "US", "15z", 20, "desktop", "s"))
    assert row["status"] == "posted" and row["task_id"] == "newtid" and row["attempts"] == 1

    # attempts 2 → 3 == max → give up, mark failed (renders as a null hole)
    row = _run(m._handle_posted_pin({**_PIN, "attempts": 2}, "US", "15z", 20, "desktop", "s"))
    assert row["status"] == "failed" and row["attempts"] == 3 and row["error"] == "task_error"


def test_handle_error_repost_failure_keeps_posted(monkeypatch):
    async def fake_fetch(_tid):
        return "error", None

    async def fake_post(_bodies):
        return [None]  # repost couldn't create a task
    monkeypatch.setattr(m, "fetch_task_result", fake_fetch)
    monkeypatch.setattr(m, "post_pin_tasks", fake_post)
    row = _run(m._handle_posted_pin({**_PIN, "attempts": 0}, "US", "15z", 20, "desktop", "s"))
    assert row["status"] == "posted" and row["attempts"] == 1  # retry the old task next tick


# ---------------------------------------------------------------------------
# timeout_completes — partial-complete threshold
# ---------------------------------------------------------------------------
def test_timeout_completes_threshold():
    assert m.timeout_completes(90, 100) is True
    assert m.timeout_completes(89, 100) is False
    assert m.timeout_completes(10, 10) is True
    assert m.timeout_completes(0, 0) is False


# ---------------------------------------------------------------------------
# post_pin_tasks — batching + order alignment (mocked HTTP)
# ---------------------------------------------------------------------------
def test_post_pin_tasks_aligns_ids_by_order(monkeypatch):
    posted_batches = []

    class _Resp:
        def __init__(self, bodies):
            self._bodies = bodies

        def raise_for_status(self):
            return None

        def json(self):
            # Echo one task per submitted body, in order, each with an id + tag.
            return {"tasks": [{"id": f"id-{b['tag']}", "status_code": 20100,
                               "data": {"tag": b["tag"]}} for b in self._bodies]}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, _url, headers=None, json=None):
            posted_batches.append(len(json))
            return _Resp(json)

    monkeypatch.setattr(m.httpx, "AsyncClient", _Client)
    bodies = [{"tag": f"S:0:{i}:0", "keyword": "k"} for i in range(150)]
    ids = _run(m.post_pin_tasks(bodies))
    assert len(ids) == 150
    assert ids[0] == "id-S:0:0:0" and ids[149] == "id-S:0:149:0"
    assert posted_batches == [100, 50]  # batched at 100/request


# ---------------------------------------------------------------------------
# fetch_task_result — status-code mapping (mocked HTTP)
# ---------------------------------------------------------------------------
def _patch_get(monkeypatch, payload):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, _url, headers=None):
            return _Resp()

    monkeypatch.setattr(m.httpx, "AsyncClient", _Client)


def test_fetch_task_result_done(monkeypatch):
    _patch_get(monkeypatch, {"tasks": [{"status_code": 20000,
        "result": [{"items": [{"type": "maps_search", "place_id": "US"}]}]}]})
    status, items = _run(m.fetch_task_result("t"))
    assert status == "done" and items[0]["place_id"] == "US"


def test_fetch_task_result_pending(monkeypatch):
    _patch_get(monkeypatch, {"tasks": [{"status_code": 40601, "result": None}]})
    assert _run(m.fetch_task_result("t")) == ("pending", None)


def test_fetch_task_result_error(monkeypatch):
    _patch_get(monkeypatch, {"tasks": [{"status_code": 40501, "result": None}]})
    assert _run(m.fetch_task_result("t")) == ("error", None)


# ---------------------------------------------------------------------------
# Step-0 fixture (auto-validates the real DataForSEO field names once captured).
# ---------------------------------------------------------------------------
def test_parse_against_step0_fixture_if_present():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "dataforseo_maps_pin.json")
    if not os.path.exists(path):
        pytest.skip("step-0 fixture not captured yet (run the field-verification call)")
    body = json.load(open(path))
    task = (body.get("tasks") or [{}])[0]
    items = ((task.get("result") or [{}])[0] or {}).get("items") or []
    rank, ordered = m.parse_pin_items(items, "ChIJBRHqLKgA2YgRPl6DE4WgScM")
    assert ordered, "expected maps_search items in the fixture"
    assert all(r[0] for r in ordered), "every parsed business needs a place_id"
    # The client (WheelHouse IT) should appear for its own branded local query.
    assert any(r[0] == "ChIJBRHqLKgA2YgRPl6DE4WgScM" for r in ordered), \
        "client place_id not found verbatim — verify google_place_id vs DataForSEO place_id"
