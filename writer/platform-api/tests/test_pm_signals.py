"""Tests for the PACE deterministic signal layer (Phase 0A).

Pure helpers only — staleness (incl. the reopen clock reset), month-pace (both
modes + suppressions), unacted-on producer detection, untriaged grace, and the
business-day math. No DB, no LLM.
"""

from __future__ import annotations

from datetime import date

from services import pm_signals as S

THRESHOLDS = {"blocked": 3, "in_review": 5, "sent_to_client": 5, "in_progress": 10}
CATEGORY_FALLBACK = {"blocked": 3, "in_progress": 10}


# ---------------------------------------------------------------------------
# Date + business-day helpers
# ---------------------------------------------------------------------------
def test_to_date_variants():
    assert S.to_date("2026-07-11") == date(2026, 7, 11)
    assert S.to_date("2026-07-11T03:52:58.7+00:00") == date(2026, 7, 11)
    assert S.to_date(date(2026, 7, 11)) == date(2026, 7, 11)
    assert S.to_date(None) is None
    assert S.to_date("not-a-date") is None


def test_business_day_math():
    # July 2026: 1st is a Wednesday; 23 weekdays in the month.
    assert S.business_days_in_month(2026, 7) == 23
    # Through Fri Jul 3 → Wed,Thu,Fri = 3 business days.
    assert S.business_days_elapsed(date(2026, 7, 3)) == 3
    # Through Mon Jul 6 → +Mon = 4 (Sat/Sun skipped).
    assert S.business_days_elapsed(date(2026, 7, 6)) == 4


# ---------------------------------------------------------------------------
# Staleness — incl. the reopen clock reset (the headline edge case)
# ---------------------------------------------------------------------------
def test_status_clock_resets_on_reopen():
    today = date(2026, 7, 20)
    task = {"created_at": "2026-01-01", "status_key": "in_progress"}
    activities = [
        {"kind": "created", "created_at": "2026-01-01"},
        {"kind": "status_changed", "created_at": "2026-01-05"},
        {"kind": "completed", "created_at": "2026-01-10"},   # NOT a reset
        {"kind": "reopened", "created_at": "2026-07-19"},     # resets the clock
    ]
    # Clock starts at the reopen, so ~1 day in status — not ~6 months.
    assert S.status_clock_start(task, activities) == date(2026, 7, 19)
    assert S.days_in_status(task, activities, today) == 1


def test_status_clock_fallback_to_created():
    today = date(2026, 7, 20)
    task = {"created_at": "2026-07-10"}
    assert S.days_in_status(task, [], today) == 10


def test_stale_threshold_key_then_category_fallback():
    # Per-key override wins.
    assert S.stale_threshold("blocked", "blocked", THRESHOLDS, CATEGORY_FALLBACK) == 3
    # Unknown key, known category → fallback.
    assert S.stale_threshold("on_hold", "blocked", THRESHOLDS, CATEGORY_FALLBACK) == 3
    # Unknown key + unknown/none category → no threshold (never stale on a timer).
    assert S.stale_threshold("weird", "not_started", THRESHOLDS, CATEGORY_FALLBACK) is None


def test_is_stale():
    assert S.is_stale(4, 3) is True
    assert S.is_stale(3, 3) is True
    assert S.is_stale(2, 3) is False
    assert S.is_stale(10, None) is False   # no threshold → never stale
    assert S.is_stale(None, 3) is False


# ---------------------------------------------------------------------------
# Month-pace heuristic — both modes + suppressions
# ---------------------------------------------------------------------------
def _tasks(n_total, n_done=0, dated=0, dated_due="2026-07-01"):
    tasks = []
    for i in range(n_total):
        t = {"parent_task_id": None, "completed": i < n_done, "due_date": None}
        if i < dated:
            t["due_date"] = dated_due
        tasks.append(t)
    return tasks


def test_month_pace_suppress_small_board():
    r = S.month_pace(_tasks(3), date(2026, 7, 20), grace=0.15, min_tasks=4, suppress_business_days=3)
    assert r["applicable"] is False and r["reason"] == "too_few_tasks"


def test_month_pace_suppress_early_month():
    # Jul 2 = 2nd business day → suppressed.
    r = S.month_pace(_tasks(10), date(2026, 7, 2), grace=0.15, min_tasks=4, suppress_business_days=3)
    assert r["applicable"] is False and r["reason"] == "early_month"


def test_month_pace_calendar_mode_behind():
    # Few due dates → calendar proxy. Jul 20: ~65% business-days elapsed, 10% done → behind.
    r = S.month_pace(_tasks(10, n_done=1, dated=0), date(2026, 7, 20),
                     grace=0.15, min_tasks=4, suppress_business_days=3)
    assert r["applicable"] and r["mode"] == "calendar" and r["behind"] is True


def test_month_pace_due_weighted_mode():
    # ≥ half dated → due-weighted. 10 dated: 8 due on/before today, 2 in the
    # future; 2 completed. expected = 8/10 = 0.8; actual = 2/10 = 0.2;
    # 0.2 + 0.15 < 0.8 → behind.
    tasks = []
    for i in range(10):
        due = "2026-07-05" if i < 8 else "2026-07-31"  # 8 past, 2 future
        tasks.append({"parent_task_id": None, "completed": i < 2, "due_date": due})
    r = S.month_pace(tasks, date(2026, 7, 20), grace=0.15, min_tasks=4, suppress_business_days=3)
    assert r["mode"] == "due_weighted"
    assert r["expected"] == 0.8 and r["actual"] == 0.2 and r["behind"] is True


def test_month_pace_due_weighted_on_track():
    # All dated in the future → nothing expected yet → not behind.
    r = S.month_pace(_tasks(10, n_done=0, dated=10, dated_due="2026-07-31"), date(2026, 7, 20),
                     grace=0.15, min_tasks=4, suppress_business_days=3)
    assert r["mode"] == "due_weighted" and r["expected"] == 0.0 and r["behind"] is False


# ---------------------------------------------------------------------------
# Triage signals
# ---------------------------------------------------------------------------
def test_unacted_producer_task():
    base = {"source": "rank_drop", "completed": False}
    # Only 'created' → unacted.
    assert S.is_unacted_producer_task(base, [{"kind": "created"}]) is True
    assert S.is_unacted_producer_task(base, []) is True
    # Someone assigned/changed it → acted.
    assert S.is_unacted_producer_task(base, [{"kind": "created"}, {"kind": "assigned"}]) is False
    # Manual task → not a producer signal.
    assert S.is_unacted_producer_task({"source": "manual", "completed": False}, [{"kind": "created"}]) is False
    # Completed producer task → not surfaced.
    assert S.is_unacted_producer_task({"source": "rank_drop", "completed": True}, [{"kind": "created"}]) is False


def test_select_untriaged_grace_and_flags():
    today = date(2026, 7, 20)
    tasks = [
        {"id": "a", "name": "Old unassigned", "completed": False, "parent_task_id": None,
         "assignee_gid": None, "due_date": "2026-07-25", "created_at": "2026-07-01"},
        {"id": "b", "name": "Fresh unassigned", "completed": False, "parent_task_id": None,
         "assignee_gid": None, "due_date": "2026-07-25", "created_at": "2026-07-19"},   # too fresh
        {"id": "c", "name": "No due date", "completed": False, "parent_task_id": None,
         "assignee_gid": "g1", "due_date": None, "created_at": "2026-07-01"},
        {"id": "d", "name": "Done", "completed": True, "parent_task_id": None,
         "assignee_gid": None, "due_date": None, "created_at": "2026-07-01"},           # excluded
    ]
    r = S.select_untriaged(tasks, today, grace_days=2)
    assert [t["id"] for t in r["unassigned"]] == ["a"]   # b too fresh, d done
    assert [t["id"] for t in r["no_due"]] == ["c"]
