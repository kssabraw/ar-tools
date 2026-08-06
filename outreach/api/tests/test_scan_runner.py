"""Submission and collection orderings — the parts that decide what an interruption costs.

The pure parsing lives in `test_maps_scan.py`. What is tested here is sequencing, because every
failure this layer can have is a failure of ORDER: rows written after money is spent, a task
marked done before its rows land, a month derived from the clock instead of the snapshot. None of
those show up in a happy-path run, and all of them are expensive exactly once.

The fake below records the order of operations rather than only their results, because "did it
write the rows" is a weaker claim than "did it write the rows FIRST".
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from api.services import maps_scan, scan_runner
from api.services.maps_scan import CODE_IN_QUEUE, CODE_OK, CODE_TASK_CREATED

SNAP = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


# --- a fake that remembers the order ---------------------------------------------------------


class _Result:
    def __init__(self, data):
        self.data = data


class _Executable:
    """supabase-py's rpc() returns something you still have to .execute()."""

    def __init__(self, data):
        self._data = data

    def execute(self):
        return _Result(self._data)


class _Query:
    def __init__(self, db, name, op, payload=None):
        self.db, self.name, self.op, self.payload = db, name, op, payload
        self.filters = []
        self._limit = None

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def lt(self, column, value):
        self.filters.append(("lt", column, value))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matches(self, row):
        for kind, column, value in self.filters:
            actual = row.get(column)
            if kind == "eq" and str(actual) != str(value):
                return False
            if kind == "lt" and not (actual is not None and str(actual) < str(value)):
                return False
        return True

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            written = []
            for row in payload:
                row = dict(row)
                row.setdefault("id", f"{self.name}-{len(rows) + len(written)}")
                written.append(row)
            rows.extend(written)
            self.db.log.append(("insert", self.name, len(written)))
            return _Result(written)
        if self.op == "update":
            hit = [r for r in rows if self._matches(r)]
            for row in hit:
                row.update(self.payload)
            self.db.log.append(("update", self.name, self.payload.get("status")))
            return _Result(hit)
        found = [r for r in rows if self._matches(r)]
        if self._limit is not None:
            found = found[: self._limit]
        return _Result(found)


class _FakeDB:
    def __init__(self):
        self.tables = {}
        self.log = []
        self.rpcs = []

    def table(self, name):
        return _Query(self, name, "select")

    def rpc(self, name, params):
        self.rpcs.append((name, params))
        return _Executable([])

    # the two shapes _Query needs to distinguish
    def _op(self, name, op, payload):
        return _Query(self, name, op, payload)


def _patch_ops():
    """`insert`/`update` are methods on the query object in supabase-py; wire them here rather
    than in _Query so the fake reads as the shape it is imitating."""
    _Query.insert = lambda self, payload: _Query(self.db, self.name, "insert", payload)
    _Query.update = lambda self, payload: _Query(self.db, self.name, "update", payload)


_patch_ops()


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeHTTP:
    """Returns queued responses in order and records what was asked for."""

    def __init__(self, posts=None, gets=None):
        self.posts = list(posts or [])
        self.gets = list(gets or [])
        self.post_bodies = []
        self.get_urls = []

    async def post(self, url, headers=None, json=None):
        self.post_bodies.append(json)
        return self.posts.pop(0)

    async def get(self, url, headers=None):
        self.get_urls.append(url)
        return self.gets.pop(0)

    async def aclose(self):
        return None


class _Settings:
    dataforseo_login = "u"
    dataforseo_password = "p"
    dataforseo_request_timeout_seconds = 30.0
    dataforseo_default_language_code = "en"
    scan_zoom = 13
    scan_depth = 20
    scan_device = "desktop"
    scan_completeness_threshold = 0.98
    scan_collect_fallback_days = 3
    scan_collect_fallback_limit = 500
    scan_collect_alert_days = 5
    dataforseo_cost_per_request_cents = 1  # the I-086 ledger write reads this


def _submarket(radius=5.0, spacing=5.0):
    """Spacing 5 on radius 5 gives a 5-point grid — small enough to assert on exhaustively, and
    it exercises the same generator the real 81-point grid uses."""
    return {
        "id": "sub-1",
        "name": "Woodland Hills",
        "center_lat": 34.16,
        "center_lng": -118.60,
        "grid_radius_miles": radius,
        "grid_spacing_miles": spacing,
    }


def _keyword():
    return {"id": "kw-1", "term": "plumber"}


def _post_ok(bodies):
    return _FakeResponse(
        {
            "tasks": [
                {"id": f"task-{i}", "status_code": CODE_TASK_CREATED,
                 "data": {"tag": body["tag"]}}
                for i, body in enumerate(bodies)
            ]
        }
    )


# --- submission -------------------------------------------------------------------------------


def test_task_rows_are_written_before_the_provider_is_paid():
    """The ordering that decides what a crash costs. Rows first means a lost response leaves work
    to redo; money first means paid tasks with no record that they exist."""
    db = _FakeDB()
    bodies = [
        b
        for _, b in maps_scan.build_grid_tasks(
            SNAP, "plumber", scan_runner.generate_points(34.16, -118.60, 5.0, 5.0),
            zoom=13, depth=20, language_code="en",
        )
    ]
    http = _FakeHTTP(posts=[_post_ok(bodies)])

    asyncio.run(
        scan_runner.submit_scan(db, _Settings(), _submarket(), _keyword(), client=http)
    )

    inserts = [entry for entry in db.log if entry[0] == "insert"]
    assert inserts[0][1] == "scan_snapshot"
    assert inserts[1][1] == "scan_task"
    # And the tasks existed before anything was posted.
    assert len(db.tables["scan_task"]) == len(bodies)


def test_every_posted_point_is_marked_submitted_with_its_id():
    db = _FakeDB()
    points = scan_runner.generate_points(34.16, -118.60, 5.0, 5.0)
    bodies = [b for _, b in maps_scan.build_grid_tasks(
        SNAP, "plumber", points, zoom=13, depth=20, language_code="en")]
    http = _FakeHTTP(posts=[_post_ok(bodies)])

    report = asyncio.run(
        scan_runner.submit_scan(db, _Settings(), _submarket(), _keyword(), client=http)
    )

    assert report.posted == len(points)
    assert report.unposted == 0
    rows = db.tables["scan_task"]
    assert all(r["status"] == "submitted" for r in rows)
    assert all(r["provider_task_id"] for r in rows)


def test_a_submission_writes_its_cost_to_the_ledger():
    """I-086: the geogrid was the only paid path with no cost_ledger row. Units are tasks
    POSTED — an unposted batch cost nothing and must not be billed to the ledger either."""
    db = _FakeDB()
    points = scan_runner.generate_points(34.16, -118.60, 5.0, 5.0)
    bodies = [b for _, b in maps_scan.build_grid_tasks(
        SNAP, "plumber", points, zoom=13, depth=20, language_code="en")]
    http = _FakeHTTP(posts=[_post_ok(bodies)])

    sub = dict(_submarket(), market_id="market-1")
    report = asyncio.run(
        scan_runner.submit_scan(db, _Settings(), sub, _keyword(), client=http)
    )

    rows = db.tables.get("cost_ledger", [])
    assert len(rows) == 1
    assert rows[0]["stage"] == "b1_geogrid"
    assert rows[0]["provider"] == "dataforseo"
    assert rows[0]["units"] == report.posted == len(points)
    assert rows[0]["cost_cents"] == len(points) * _Settings.dataforseo_cost_per_request_cents
    assert rows[0]["market_id"] == "market-1"


def test_a_fully_failed_post_writes_no_ledger_row():
    """Nothing posted, nothing billed, nothing to reconcile."""
    class _Refuses:
        async def post(self, url, headers=None, json=None):
            import httpx
            raise httpx.ConnectError("network")

        async def aclose(self):
            return None

    db = _FakeDB()
    report = asyncio.run(
        scan_runner.submit_scan(db, _Settings(), _submarket(), _keyword(), client=_Refuses())
    )

    assert report.posted == 0
    assert db.tables.get("cost_ledger", []) == []


def test_a_failed_post_leaves_the_points_pending_rather_than_lost():
    """`pending` is the recoverable state. The batch can be reposted for the price of the batch;
    marking it submitted would leave the collector waiting on ids that were never issued."""
    class _Boom(_FakeHTTP):
        async def post(self, url, headers=None, json=None):
            import httpx
            raise httpx.ConnectError("network")

    db = _FakeDB()
    report = asyncio.run(
        scan_runner.submit_scan(db, _Settings(), _submarket(), _keyword(), client=_Boom())
    )

    assert report.posted == 0
    assert report.unposted == report.expected_points
    assert all(r["status"] == "pending" for r in db.tables["scan_task"])
    assert report.problems


def test_the_snapshot_records_expected_points_before_the_scan_runs():
    """A denominator derived afterwards from what came back would make every scan complete by
    construction, which is the one thing the completeness gate must not do."""
    db = _FakeDB()
    points = scan_runner.generate_points(34.16, -118.60, 5.0, 5.0)
    bodies = [b for _, b in maps_scan.build_grid_tasks(
        SNAP, "plumber", points, zoom=13, depth=20, language_code="en")]
    asyncio.run(
        scan_runner.submit_scan(
            db, _Settings(), _submarket(), _keyword(), client=_FakeHTTP(posts=[_post_ok(bodies)])
        )
    )
    snapshot = db.tables["scan_snapshot"][0]
    assert snapshot["expected_points"] == len(points)
    assert snapshot["actual_points"] == 0
    assert snapshot["complete"] is False


def test_the_snapshot_records_the_centre_the_points_were_generated_from():
    """ISSUES I-078. Coordinates are not stored, so a heatmap regenerates them from the snapshot's
    parameters — and the centre was not among them, which meant Phase 3 would read
    `submarket.center_lat/lng` instead. That column is immutable only by enforcement, so a
    submarket whose centre is ever corrected would re-render every historical heatmap against
    coordinates that were never scanned: the exact failure `geometry_version` exists to prevent,
    arriving through the one door the pin does not cover.

    Asserted against the SAME values passed to the generator, not against the fixture's literals.
    Reading the submarket twice would record a centre that merely happens to be equal today, and
    the whole value of storing it is that it stays true afterwards.
    """
    db = _FakeDB()
    submarket = _submarket()
    points = scan_runner.generate_points(34.16, -118.60, 5.0, 5.0)
    bodies = [b for _, b in maps_scan.build_grid_tasks(
        SNAP, "plumber", points, zoom=13, depth=20, language_code="en")]
    asyncio.run(
        scan_runner.submit_scan(
            db, _Settings(), submarket, _keyword(), client=_FakeHTTP(posts=[_post_ok(bodies)])
        )
    )
    snapshot = db.tables["scan_snapshot"][0]
    assert snapshot["center_lat"] == submarket["center_lat"]
    assert snapshot["center_lng"] == submarket["center_lng"]


# --- the month --------------------------------------------------------------------------------


def test_scan_month_comes_from_the_snapshot_not_the_clock():
    """ISSUES I-044, and the collector is what makes it live: collection happens hours or days
    after submission, so a run that used the clock would be correct until a collection landed on
    the far side of a month boundary — then one snapshot spans two partitions."""
    assert scan_runner.month_of("2026-01-31T23:30:00+00:00").isoformat() == "2026-01-01"
    assert scan_runner.month_of("2026-02-01T00:30:00Z").isoformat() == "2026-02-01"


# --- collection -------------------------------------------------------------------------------


def _seed_submitted(
    db, task_ids, snapshot_id="snap-1", scanned_at="2026-03-15T12:00:00+00:00", submitted_at=None
):
    """Tasks posted just now, by default.

    `submitted_at` is deliberately recent and separate from the snapshot's `scanned_at`: an
    old timestamp puts every row past the fallback threshold, so the collector would take the
    aged-off-the-ready-list path instead of the normal one and the test would be measuring
    recovery while claiming to measure collection.
    """
    submitted_at = submitted_at or datetime.now(timezone.utc).isoformat()
    db.tables["scan_snapshot"] = [
        {"id": snapshot_id, "scanned_at": scanned_at, "expected_points": len(task_ids)}
    ]
    db.tables["scan_task"] = [
        {
            "id": f"t{i}",
            "snapshot_id": snapshot_id,
            "point_seq": i,
            "provider_task_id": task_id,
            "status": "submitted",
            "submitted_at": submitted_at,
        }
        for i, task_id in enumerate(task_ids)
    ]


def _ready(entries):
    return _FakeResponse(
        {"tasks": [{"status_code": CODE_OK, "result": [dict(e) for e in entries]}]}
    )


def _grid(items):
    return _FakeResponse({"tasks": [{"status_code": CODE_OK, "result": [{"items": items}]}]})


def test_rows_are_written_before_the_task_is_marked_collected():
    """A crash between them re-collects a task that costs nothing to re-collect. The reverse
    order marks a point done whose rows never landed, and the snapshot finalizes with a hole
    nothing downstream can detect."""
    db = _FakeDB()
    _seed_submitted(db, ["task-a"])
    http = _FakeHTTP(
        gets=[
            _ready([{"id": "task-a", "tag": f"{SNAP}:0"}]),
            _grid([{"place_id": "A", "rank_absolute": 1}]),
            _ready([]),
        ]
    )

    asyncio.run(scan_runner.collect_ready(db, _Settings(), client=http, max_rounds=2))

    ops = [e for e in db.log if e[1] in ("grid_result", "scan_task")]
    grid_write = next(i for i, e in enumerate(ops) if e[1] == "grid_result")
    collected_mark = next(
        i for i, e in enumerate(ops) if e[1] == "scan_task" and e[2] == "collected"
    )
    assert grid_write < collected_mark


def test_grid_rows_carry_the_snapshots_month():
    db = _FakeDB()
    _seed_submitted(db, ["task-a"], scanned_at="2026-03-31T23:00:00+00:00")
    http = _FakeHTTP(
        gets=[
            _ready([{"id": "task-a", "tag": f"{SNAP}:0"}]),
            _grid([{"place_id": "A", "rank_absolute": 1}]),
            _ready([]),
        ]
    )
    asyncio.run(scan_runner.collect_ready(db, _Settings(), client=http, max_rounds=2))
    assert db.tables["grid_result"][0]["scan_month"] == "2026-03-01"


def test_a_point_that_returned_nothing_is_collected_not_failed():
    """An empty pack is an answer — 'nobody ranks here' is frequently the strongest finding in a
    grid. Recording it as a failure would make a submarket's real dead zones look like a broken
    scan and hold the snapshot below the completeness threshold every cycle."""
    db = _FakeDB()
    _seed_submitted(db, ["task-a"])
    http = _FakeHTTP(gets=[_ready([{"id": "task-a", "tag": f"{SNAP}:0"}]), _grid([]), _ready([])])

    report = asyncio.run(scan_runner.collect_ready(db, _Settings(), client=http, max_rounds=2))

    assert report.collected == 1
    assert report.rows_written == 0
    row = db.tables["scan_task"][0]
    assert row["status"] == "collected"
    assert row["result_count"] == 0


def test_a_still_queued_task_stays_submitted_for_the_next_tick():
    db = _FakeDB()
    _seed_submitted(db, ["task-a"])
    http = _FakeHTTP(
        gets=[
            _ready([{"id": "task-a", "tag": f"{SNAP}:0"}]),
            _FakeResponse({"tasks": [{"status_code": CODE_IN_QUEUE}]}),
            _ready([]),
        ]
    )

    report = asyncio.run(scan_runner.collect_ready(db, _Settings(), client=http, max_rounds=2))

    assert report.still_pending == 1
    assert db.tables["scan_task"][0]["status"] == "submitted"


def test_a_result_whose_id_we_never_stored_is_recovered_through_the_tag():
    """The window the tag exists to close: the provider accepted (and billed) the request, and
    the response carrying the id never reached us."""
    db = _FakeDB()
    db.tables["scan_snapshot"] = [
        {"id": SNAP, "scanned_at": "2026-03-15T12:00:00+00:00", "expected_points": 1}
    ]
    db.tables["scan_task"] = [
        {"id": "t0", "snapshot_id": SNAP, "point_seq": 0, "provider_task_id": None,
         "status": "pending", "submitted_at": None}
    ]
    http = _FakeHTTP(
        gets=[
            _ready([{"id": "orphan-task", "tag": f"{SNAP}:0"}]),
            _grid([{"place_id": "A", "rank_absolute": 1}]),
            _ready([]),
        ]
    )

    report = asyncio.run(scan_runner.collect_ready(db, _Settings(), client=http, max_rounds=2))

    assert report.recovered_by_tag == 1
    assert report.collected == 1
    assert db.tables["scan_task"][0]["provider_task_id"] == "orphan-task"


def test_another_tools_tasks_are_left_alone():
    """The ready list is account-wide. Collecting somebody else's task would clear it from their
    list, and they would never know why their results vanished."""
    db = _FakeDB()
    _seed_submitted(db, ["task-a"])
    http = _FakeHTTP(gets=[_ready([{"id": "not-ours", "tag": "some-other-system"}])])

    report = asyncio.run(scan_runner.collect_ready(db, _Settings(), client=http, max_rounds=3))

    assert report.foreign == 1
    assert report.collected == 0
    assert http.get_urls == [f"{scan_runner.BASE_URL}{maps_scan.TASKS_READY_PATH}"]


def test_a_task_that_aged_off_the_ready_list_is_still_collected_by_id():
    """PRD §B1.3. The ready list holds a task ~3 days; results stay retrievable for 30. Without
    this path a collector outage of one long weekend would silently discard every paid task in
    flight — and the ready list would come back empty, so the next run would look clean."""
    db = _FakeDB()
    old = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    _seed_submitted(db, ["aged-task"], submitted_at=old)
    http = _FakeHTTP(gets=[_ready([]), _grid([{"place_id": "A", "rank_absolute": 1}])])

    report = asyncio.run(scan_runner.collect_ready(db, _Settings(), client=http, max_rounds=1))

    assert report.collected == 1
    assert db.tables["scan_task"][0]["status"] == "collected"


def test_a_task_uncollected_past_the_alert_age_is_reported():
    """§B1.4. At this age the COLLECTOR'S SCHEDULE is wrong, not this task's luck — a distinction
    invisible from any single run, which is why it is surfaced rather than retried in silence."""
    db = _FakeDB()
    old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    _seed_submitted(db, ["stuck"], submitted_at=old)
    http = _FakeHTTP(gets=[_ready([]), _FakeResponse({"tasks": [{"status_code": CODE_IN_QUEUE}]})])

    report = asyncio.run(scan_runner.collect_ready(db, _Settings(), client=http, max_rounds=1))

    assert any("uncollected" in p for p in report.problems)


# --- finalization -----------------------------------------------------------------------------


def test_a_snapshot_with_work_outstanding_does_not_finalize():
    db = _FakeDB()
    _seed_submitted(db, ["a", "b"])
    db.tables["scan_task"][0]["status"] = "collected"
    assert scan_runner.finalize_snapshot(db, _Settings(), "snap-1") is False


def test_actual_points_counts_points_collected_not_rows_written():
    """A point with 20 businesses and a point with none are both one scanned point. Counting
    rows would make a dense submarket look complete and a sparse one look broken — the same
    correction the rollup's completion marker needed (I-069)."""
    db = _FakeDB()
    _seed_submitted(db, ["a", "b"])
    for row in db.tables["scan_task"]:
        row["status"] = "collected"
    db.tables["scan_task"][0]["result_count"] = 20
    db.tables["scan_task"][1]["result_count"] = 0

    assert scan_runner.finalize_snapshot(db, _Settings(), "snap-1") is True
    snapshot = db.tables["scan_snapshot"][0]
    assert snapshot["actual_points"] == 2
    assert snapshot["complete"] is True


def test_a_snapshot_below_the_threshold_is_marked_incomplete():
    db = _FakeDB()
    _seed_submitted(db, [f"t{i}" for i in range(10)])
    for row in db.tables["scan_task"][:9]:
        row["status"] = "collected"
    db.tables["scan_task"][9]["status"] = "failed"

    assert scan_runner.finalize_snapshot(db, _Settings(), "snap-1") is True
    assert db.tables["scan_snapshot"][0]["actual_points"] == 9
    assert db.tables["scan_snapshot"][0]["complete"] is False


def test_finalizing_asserts_the_month_rather_than_assuming_it():
    """The check that catches a writer using the clock. It refuses rather than repairs, because
    the repair (rewriting a partition key) is the expensive half."""
    db = _FakeDB()
    _seed_submitted(db, ["a"])
    db.tables["scan_task"][0]["status"] = "collected"

    scan_runner.finalize_snapshot(db, _Settings(), "snap-1")

    assert ("assert_snapshot_month", {"p_snapshot_id": "snap-1"}) in db.rpcs


def test_a_failing_month_assertion_raises_rather_than_reporting_success():
    class _Angry(_FakeDB):
        def rpc(self, name, params):
            raise RuntimeError("rows outside the snapshot's month")

    db = _Angry()
    _seed_submitted(db, ["a"])
    db.tables["scan_task"][0]["status"] = "collected"

    with pytest.raises(RuntimeError):
        scan_runner.finalize_snapshot(db, _Settings(), "snap-1")
