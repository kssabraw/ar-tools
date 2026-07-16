"""Tests for PACE structural-autonomy pure helpers (v1.5).

`pace_batch` owns the selector→targets expansion, the batch confirm renderer,
and the drill-down formatter — all pure. The impure staging/reads live in
`pace_agent` and are covered in test_pace_agent.py.
"""

from __future__ import annotations

from services import pace_batch


# ---------------------------------------------------------------------------
# select_targets — selector → concrete {client_id, client_name, task_name}
# ---------------------------------------------------------------------------
def test_select_targets_client_scope():
    ctx = {"overdue": [{"id": "t1", "name": "GBP audit"}, {"id": "t2", "name": "Blog"}],
           "stale": [{"id": "t3", "name": "Stuck page"}]}
    subject = {"id": "c1", "name": "Acme"}
    targets, overflow = pace_batch.select_targets("client", subject, ctx, "overdue")
    assert overflow == 0
    assert targets == [
        {"client_id": "c1", "client_name": "Acme", "task_name": "GBP audit"},
        {"client_id": "c1", "client_name": "Acme", "task_name": "Blog"},
    ]
    # "stuck" reads the stale list.
    stuck, _ = pace_batch.select_targets("client", subject, ctx, "stuck")
    assert [t["task_name"] for t in stuck] == ["Stuck page"]


def test_select_targets_member_scope_carries_client_id():
    ctx = {"member": "Ivy",
           "overdue": [{"name": "GBP audit", "client_id": "c1", "client": "Acme"},
                       {"name": "Meta rewrite", "client_id": "c2", "client": "Globex"}]}
    targets, _ = pace_batch.select_targets("member", None, ctx, "overdue")
    assert targets == [
        {"client_id": "c1", "client_name": "Acme", "task_name": "GBP audit"},
        {"client_id": "c2", "client_name": "Globex", "task_name": "Meta rewrite"},
    ]
    # member scope has no per-person staleness → "stuck" resolves empty.
    assert pace_batch.select_targets("member", None, ctx, "stuck")[0] == []


def test_select_targets_portfolio_and_truncation_marker_dropped():
    ctx = {"clients": [
        {"client_id": "c1", "client_name": "Acme",
         "overdue": [{"id": "t1", "name": "GBP audit"}, {"_truncated": 5}]},
        {"client_id": "c2", "client_name": "Globex", "overdue": [{"id": "t9", "name": "Sitemap"}]},
    ]}
    targets, _ = pace_batch.select_targets("portfolio", None, ctx, "overdue")
    # The {"_truncated": 5} marker has no name → dropped.
    assert targets == [
        {"client_id": "c1", "client_name": "Acme", "task_name": "GBP audit"},
        {"client_id": "c2", "client_name": "Globex", "task_name": "Sitemap"},
    ]


def test_select_targets_dedupes_and_caps():
    rows = [{"id": f"t{i}", "name": f"task {i}"} for i in range(5)]
    rows.append({"id": "dup", "name": "task 0"})  # same (client, name) as the first
    ctx = {"overdue": rows}
    subject = {"id": "c1", "name": "Acme"}
    targets, overflow = pace_batch.select_targets("client", subject, ctx, "overdue", cap=3)
    assert len(targets) == 3 and overflow == 2   # 5 unique after dedupe, capped to 3
    names = [t["task_name"] for t in targets]
    assert len(set(names)) == 3                  # no duplicate task 0


# ---------------------------------------------------------------------------
# render_batch
# ---------------------------------------------------------------------------
def test_render_batch_slack_and_web_bold():
    items = [{"index": 1, "reason": "nudge Ivy about “GBP audit”", "client_name": "Acme"},
             {"index": 2, "reason": "nudge Ivy about “Meta rewrite”", "client_name": "Globex"}]
    slack = pace_batch.render_batch(items, ["“Old page” — unassigned"], overflow=3)
    assert slack.startswith("*PACE — 2 staged actions*")
    assert "reply *yes* for all" in slack
    assert "1. nudge Ivy about “GBP audit” — _Acme_" in slack
    assert "⚠️ “Old page” — unassigned" in slack
    assert "and 3 more held back" in slack
    web = pace_batch.render_batch(items, [], bold="**")
    assert web.startswith("**PACE — 2 staged actions**")


def test_render_batch_singular():
    out = pace_batch.render_batch([{"index": 1, "reason": "unblock x", "client_name": "Acme"}], [])
    assert "1 staged action*" in out and "actions" not in out.split("\n")[0]


# ---------------------------------------------------------------------------
# format_drill
# ---------------------------------------------------------------------------
def test_format_drill_full():
    task = {
        "name": "GBP audit", "assignee_name": "Ivy", "status_key": "in_progress", "due_date": "2026-01-01",
        "subtasks": [{"name": "Pull categories", "completed": True},
                     {"name": "Fix NAP", "completed": False}],
        "activity": [{"created_at": "2026-07-15T10:00:00Z", "kind": "status_changed", "detail": {"to": "in_progress"}},
                     {"created_at": "2026-07-10T09:00:00Z", "kind": "created"}],
    }
    comments = [{"body": "Waiting on client   logo\nassets"}]
    out = pace_batch.format_drill(task, comments, days_in_status=6)
    assert "Task: GBP audit" in out
    assert "Assignee: Ivy" in out
    assert "Status: in_progress (6d in this status)" in out
    assert "Subtasks: 1/2 done" in out
    assert "Open subtasks: Fix NAP" in out
    assert "2026-07-15 status_changed" in out
    assert "Waiting on client logo assets" in out   # whitespace collapsed


def test_format_drill_minimal():
    out = pace_batch.format_drill({"name": "Bare", "status_key": "not_started"}, [], None)
    assert out == "Task: Bare\nStatus: not_started"
