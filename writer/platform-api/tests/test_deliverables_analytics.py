"""Unit tests for the admin Activity Report pure aggregation helpers.

No network — only labelling, grouping, member attribution, and the by-type /
by-client / by-member / daily rollups are exercised (build_report's DB reads
are covered by integration against the deliverable_events view).
"""

from __future__ import annotations

import sys
import types
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The service imports `from db.supabase_client import get_supabase` at module
# load. These pure tests never touch the DB, so stub that module (and its `db`
# package) before import — avoids requiring the supabase package / live env.
if "db.supabase_client" not in sys.modules:
    sys.modules.setdefault("db", types.ModuleType("db"))
    _fake_db = types.ModuleType("db.supabase_client")
    _fake_db.get_supabase = lambda: None  # type: ignore[attr-defined]
    sys.modules["db.supabase_client"] = _fake_db

from services import deliverables_analytics as da  # noqa: E402


def _ev(dtype, client_id=None, actor_id=None, actor_name=None, occurred_at=None):
    return {
        "deliverable_type": dtype,
        "client_id": client_id,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "occurred_at": occurred_at,
    }


# ── labels + groups ─────────────────────────────────────────────────────────

def test_label_for_known_and_fallback():
    assert da.label_for("gbp_post") == "GBP post"
    assert da.label_for("local_seo_page") == "Local SEO page"
    # unmapped future task category → readable Task — X
    assert da.label_for("task_citations") == "Task — Citations"
    assert da.label_for("task_") == "Task"
    # unmapped non-task → title-cased
    assert da.label_for("some_new_thing") == "Some New Thing"


def test_group_for():
    assert da.group_for("blog_post") == "Content pages"
    assert da.group_for("ecommerce_reoptimize") == "Content pages"
    assert da.group_for("website_page") == "Content pages"
    assert da.group_for("gbp_post") == "GBP posts"
    assert da.group_for("task_link_building") == "Tasks"
    assert da.group_for("task_other") == "Tasks"
    assert da.group_for("client_report") == "Reports"
    assert da.group_for("rank_keyword_report") == "Reports"
    assert da.group_for("maps_scan") == "Research & scans"
    assert da.group_for("keyword_research") == "Research & scans"


# ── member attribution precedence ────────────────────────────────────────────

def test_member_key_assignee_wins_then_profile_then_system():
    assert da.member_key(_ev("task_content", actor_id="p1", actor_name="Ivy")) == ("name", "Ivy")
    assert da.member_key(_ev("blog_post", actor_id="p1")) == ("profile", "p1")
    assert da.member_key(_ev("maps_scan")) == ("system", None)
    # blank/whitespace assignee is not a name
    assert da.member_key(_ev("task_other", actor_id="p2", actor_name="   ")) == ("profile", "p2")


# ── aggregation ──────────────────────────────────────────────────────────────

def test_aggregate_counts_all_dimensions():
    events = [
        _ev("blog_post", client_id="c1", actor_id="p1", occurred_at="2026-09-01T10:00:00Z"),
        _ev("blog_post", client_id="c1", actor_id="p1", occurred_at="2026-09-01T12:00:00Z"),
        _ev("gbp_post", client_id="c2", occurred_at="2026-09-02T09:00:00Z"),
        _ev("task_link_building", client_id="c1", actor_name="Minda", occurred_at="2026-09-02T09:30:00Z"),
        _ev("maps_scan", client_id=None, occurred_at="2026-09-03T00:00:00Z"),
    ]
    agg = da.aggregate(events)
    assert agg["total"] == 5
    assert agg["by_type"] == {"blog_post": 2, "gbp_post": 1, "task_link_building": 1, "maps_scan": 1}
    assert agg["by_client"] == {"c1": 3, "c2": 1, None: 1}
    assert agg["by_member"] == {
        ("profile", "p1"): 2,
        ("system", None): 2,   # gbp_post + maps_scan (no actor)
        ("name", "Minda"): 1,
    }
    assert agg["by_day"] == {"2026-09-01": 2, "2026-09-02": 2, "2026-09-03": 1}


def test_aggregate_bad_timestamp_skips_day_only():
    agg = da.aggregate([_ev("blog_post", client_id="c1", occurred_at="not-a-date")])
    assert agg["total"] == 1
    assert agg["by_type"] == {"blog_post": 1}
    assert agg["by_day"] == {}


# ── row builders ─────────────────────────────────────────────────────────────

def test_build_type_rows_sorted_with_label_and_group():
    rows = da.build_type_rows({"gbp_post": 1, "blog_post": 3})
    assert [r["type"] for r in rows] == ["blog_post", "gbp_post"]  # count desc
    assert rows[0] == {"type": "blog_post", "label": "Blog post", "group": "Content pages", "count": 3}


def test_build_client_rows_resolves_names_and_internal_bucket():
    rows = da.build_client_rows({"c1": 5, None: 2, "c2": 5}, {"c1": "Acme", "c2": "Beta"})
    # count desc, then name asc for the tie between Acme(5) and Beta(5)
    assert [r["client_name"] for r in rows] == ["Acme", "Beta", da._NO_CLIENT]
    assert rows[2]["client_id"] is None


def test_build_member_rows_merges_and_orders_system_last():
    by_member = {
        ("profile", "p1"): 2,
        ("name", "Ivy"): 2,
        ("system", None): 2,
        ("profile", "p2"): 1,
    }
    rows = da.build_member_rows(by_member, {"p1": "Kyle Sabraw", "p2": "Ryan"})
    # three buckets tie at 2 — the automated bucket sorts last among them
    assert rows[-1]["member"] == da._SYSTEM_MEMBER or rows[2]["member"] == da._SYSTEM_MEMBER
    members = {r["member"]: r["count"] for r in rows}
    assert members["Kyle Sabraw"] == 2
    assert members["Ivy"] == 2
    assert members["Ryan"] == 1
    assert members[da._SYSTEM_MEMBER] == 2


def test_build_member_rows_missing_profile_name_falls_back():
    rows = da.build_member_rows({("profile", "ghost"): 1}, {})
    assert rows == [{"member": "Unknown user", "count": 1}]


# ── daily series ─────────────────────────────────────────────────────────────

def test_daily_series_zero_filled_for_short_range():
    series = da.build_daily_series({"2026-09-02": 3}, date(2026, 9, 1), date(2026, 9, 3))
    assert series == [
        {"date": "2026-09-01", "count": 0},
        {"date": "2026-09-02", "count": 3},
        {"date": "2026-09-03", "count": 0},
    ]


def test_daily_series_sparse_for_huge_range():
    series = da.build_daily_series(
        {"2020-01-01": 1, "2026-09-02": 3}, date(2020, 1, 1), date(2026, 9, 2)
    )
    assert series == [{"date": "2020-01-01", "count": 1}, {"date": "2026-09-02", "count": 3}]
