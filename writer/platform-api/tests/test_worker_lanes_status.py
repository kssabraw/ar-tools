"""`worker_lanes.lane_status()` observability read — shape + fairness breakdown.

Minimal fake Supabase: every count query returns the same count, the per-client
`entity_id` query returns fixed rows. Asserts the assembled shape (main's four
lanes), not live numbers.
"""

from services import worker_lanes


class _Exec:
    def __init__(self, count=0, data=None):
        self.count = count
        self.data = data or []


class _Q:
    def __init__(self, store):
        self.store = store
        self._is_count = False

    def select(self, *cols, count=None):
        self._is_count = count == "exact"
        return self

    def eq(self, col, val):
        return self

    def in_(self, col, vals):
        return self

    def gte(self, col, val):
        return self

    def lte(self, col, val):
        return self

    @property
    def not_(self):
        return self

    def execute(self):
        return _Exec(count=self.store["count"]) if self._is_count else _Exec(data=self.store["rows"])


class _SB:
    def __init__(self, count, rows):
        self.store = {"count": count, "rows": rows}

    def table(self, name):
        return _Q(self.store)


def test_lane_status_shape_and_fairness_breakdown(monkeypatch):
    rows = [{"entity_id": "A"}, {"entity_id": "A"}, {"entity_id": "B"}]
    monkeypatch.setattr(worker_lanes, "get_supabase", lambda: _SB(count=4, rows=rows))

    out = worker_lanes.lane_status()

    lanes = {l["name"]: l for l in out["lanes"]}
    assert set(lanes) == {"main", "interactive", "fanout", "bulk"}
    assert lanes["bulk"]["pending"] == 4 and lanes["bulk"]["running"] == 4
    # Only the bulk lane carries the per-client breakdown + the fairness cap.
    assert lanes["bulk"]["per_client_running"] == {"A": 2, "B": 1}
    assert "per_client_running" not in lanes["interactive"]
    assert "max_per_client" in lanes["bulk"]
    # Priority legend is surfaced (background < interactive).
    assert out["priorities"]["background"] < out["priorities"]["interactive"]


def test_lane_status_count_failure_is_advisory(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("db down")

    monkeypatch.setattr(worker_lanes, "get_supabase", lambda: _Boom())
    out = worker_lanes.lane_status()  # must not raise
    assert out["lanes"][0]["pending"] == -1
