"""Tests for the schedule's `max_articles` production ceiling
(fanout.api.schedules) and the ordering it slices from
(fanout.writer.schedule_planner.order_clusters).

A 1000-article ceiling used to happen by accident: `list_clusters` was an
unpaged select, and PostgREST silently truncates those at 1000 rows, so a
whole-session schedule could never exceed 1000 targets however big the plan was.
semaglutide (1,594 clusters) and retatrutide (1,413) were both capped that way
without anyone choosing it, and *which* 1000 was arbitrary — clusters are
bulk-inserted, so the `created_at` sort tied across a whole batch.

Paging the read (#533) removed the accidental ceiling. The ceiling itself is
still wanted, so it is now explicit: `max_articles` trims the target list AFTER
pillars-first ordering, so the kept slice is the most important articles rather
than an arbitrary one, and the remainder stays in the plan.
"""

from __future__ import annotations

from fanout.writer.schedule_planner import (
    apply_max_articles as _cap,
    order_clusters,
    resolve_max_articles,
)


# --- the trim ---------------------------------------------------------------

def test_cap_trims_to_the_ceiling():
    targets = [f"c{i}" for i in range(3896)]  # the real tirzepatide plan size
    kept = _cap(targets, 1000)
    assert len(kept) == 1000
    assert kept[0] == "c0" and kept[-1] == "c999"


def test_no_cap_schedules_everything():
    targets = [f"c{i}" for i in range(3896)]
    assert len(_cap(targets, None)) == 3896


def test_cap_above_the_plan_size_is_a_no_op():
    targets = [f"c{i}" for i in range(50)]
    assert _cap(targets, 1000) == targets


def test_cap_of_zero_schedules_nothing():
    """0 is a real value, not 'unset' — the endpoint rejects an empty target list
    with a 400 rather than silently scheduling the whole plan."""
    assert _cap([f"c{i}" for i in range(10)], 0) == []


# --- what gets kept ---------------------------------------------------------

def test_cap_takes_pillars_first_when_an_architecture_exists():
    """The whole point of trimming after ordering: a capped schedule must keep the
    structurally important articles, not an arbitrary slice."""
    all_ids = [f"c{i}" for i in range(10)]
    architecture = {
        "pillars": [
            {"supporting_article_ids": ["c7", "c9"]},
            {"supporting_article_ids": ["c2"]},
        ]
    }

    ordered = order_clusters(architecture, all_ids)
    kept = _cap(ordered, 3)

    assert kept == ["c7", "c9", "c2"], "pillar-supporting articles must come first"
    # The unpicked ones are still in the plan — capping schedules less, it doesn't
    # delete anything.
    assert set(all_ids) - set(kept) == {"c0", "c1", "c3", "c4", "c5", "c6", "c8"}


def test_cap_without_architecture_falls_back_to_plan_order():
    """order_clusters documents "No architecture -> input order", so a cap applied
    before the architecture step takes the first N as planned rather than by
    priority. The estimate reports ordered_by='plan_order' so the UI can warn."""
    all_ids = [f"c{i}" for i in range(10)]

    ordered = order_clusters(None, all_ids)
    assert _cap(ordered, 3) == ["c0", "c1", "c2"]


def test_ordering_is_stable_and_lossless():
    """Every cluster appears exactly once regardless of architecture coverage —
    so a cap of N always yields exactly N distinct articles."""
    all_ids = [f"c{i}" for i in range(10)]
    architecture = {"pillars": [{"supporting_article_ids": ["c5", "c5", "c1"]}]}

    ordered = order_clusters(architecture, all_ids)

    assert len(ordered) == len(all_ids)
    assert len(set(ordered)) == len(all_ids)
    assert ordered[:2] == ["c5", "c1"]  # deduped, pillar order preserved


# --- where the ceiling comes from -------------------------------------------
#
# The 2026-07-31 regression: the 1000 default lived only in the frontend, so a
# browser still running a bundle from before the deploy sent no `max_articles`
# at all and scheduled the whole 3,896-article plan. A safety ceiling has to sit
# server-side, where a stale client cannot bypass it — and that requires telling
# "field absent" apart from "explicitly no limit", which `is None` cannot do.


def test_absent_field_gets_the_server_default():
    """The stale-client case. A request that never mentions max_articles must be
    capped, not treated as unlimited."""
    assert resolve_max_articles(
        field_present=False, requested=None, server_default=1000
    ) == 1000


def test_explicit_null_means_no_limit():
    """A current client saying 'no limit' must be honoured, and must not be
    confused with the absent case above — the parsed value is None in BOTH."""
    assert resolve_max_articles(
        field_present=True, requested=None, server_default=1000
    ) is None


def test_explicit_value_wins_over_the_default():
    for requested in (250, 2500):
        assert resolve_max_articles(
            field_present=True, requested=requested, server_default=1000
        ) == requested, "including a value above the default"


def test_default_can_be_disabled():
    assert resolve_max_articles(
        field_present=False, requested=None, server_default=None
    ) is None


def test_absent_field_actually_trims_the_targets():
    """The regression in one assertion, end to end through both helpers."""
    targets = [f"c{i}" for i in range(3896)]
    kept = _cap(targets, resolve_max_articles(
        field_present=False, requested=None, server_default=1000
    ))
    assert len(kept) == 1000, "a request omitting max_articles must not schedule the whole plan"


def test_negative_ceiling_is_ignored_not_reversed():
    """targets[:-5] would silently drop the LAST five instead of capping."""
    targets = [f"c{i}" for i in range(10)]
    assert _cap(targets, -5) == targets


def test_pydantic_distinguishes_absent_from_explicit_null():
    """Contract test for the assumption the whole fix rests on.

    `_effective_max_articles` in fanout/api/schedules.py reads
    `"max_articles" in body.model_fields_set` because the parsed value is None in
    BOTH the absent and explicit-null cases. If a pydantic upgrade ever stopped
    distinguishing them, the server default would start overriding a deliberate
    "no limit" — silently, and in the safe direction, so nothing would fail
    loudly. Pinned here rather than in the router, which can't be imported
    without the whole job graph.
    """
    from pydantic import BaseModel

    class _Body(BaseModel):
        mode: str
        max_articles: int | None = None

    absent = _Body.model_validate({"mode": "weekly"})
    explicit_null = _Body.model_validate({"mode": "weekly", "max_articles": None})

    assert absent.max_articles is None and explicit_null.max_articles is None
    assert "max_articles" not in absent.model_fields_set
    assert "max_articles" in explicit_null.model_fields_set


def test_architecture_referencing_deleted_clusters_is_ignored():
    """A stale architecture can name clusters a re-plan removed; those must not
    consume cap slots."""
    all_ids = ["c1", "c2", "c3"]
    architecture = {"pillars": [{"supporting_article_ids": ["gone-1", "c3", "gone-2"]}]}

    ordered = order_clusters(architecture, all_ids)
    kept = _cap(ordered, 2)

    assert "gone-1" not in ordered and "gone-2" not in ordered
    assert kept == ["c3", "c1"]
