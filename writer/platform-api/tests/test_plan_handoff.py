"""Unit tests for services.plan_handoff — the on-demand plan → PACE board handoff.

Pure eligibility/summary/confirm helpers, plus the mocked Action Plan half
(create + place), the combined engine's scope routing + native gate, and the
enqueue dedupe.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services import plan_handoff as ph


# ---------------------------------------------------------------------------
# Pure eligibility
# ---------------------------------------------------------------------------
def test_eligible_actions_skips_drop_kinds_and_caps():
    items = [
        {"kind": "rank_drop", "keyword": "a"},        # skipped (alert producer owns it)
        {"kind": "maps_decline", "keyword": "b"},     # skipped
        {"kind": "sitewide_decline", "keyword": "c"}, # skipped
        {"kind": "quick_win", "keyword": "d"},
        {"kind": "opportunity", "keyword": "e"},
        {"kind": "cannibalization", "keyword": "f"},
    ]
    with patch.object(ph.settings, "plan_handoff_max_actions", 2):
        elig = ph._eligible_actions(items)
    assert [a["keyword"] for a in elig] == ["d", "e"]  # drop kinds gone, capped at 2


# ---------------------------------------------------------------------------
# Action Plan half (create + place)
# ---------------------------------------------------------------------------
def _run_action_plan(items, place_side_effect, create_side_effect=None):
    created_calls = []

    def _create(name, **kw):
        created_calls.append({"name": name, **kw})
        if create_side_effect:
            return create_side_effect(name, kw)
        return {"id": f"task-{len(created_calls)}"}

    with (
        patch.object(ph, "_latest_plan_items", return_value=items),
        patch("services.task_monthly.ensure_month_section", return_value={"id": "sec-1"}),
        patch("services.task_service.create_task", side_effect=_create),
        patch("services.pm_assign.place_task", side_effect=place_side_effect),
    ):
        result = ph.handoff_action_plan("c1", actor_id="u1")
    return result, created_calls


def test_handoff_action_plan_creates_and_places():
    items = [
        {"kind": "quick_win", "keyword": "roof repair", "recommendation": "Reoptimize the page",
         "cta_path": "/x", "diagnosis": "striking distance"},
        {"kind": "opportunity", "keyword": "roofers near me", "cta_label": "Create a page",
         "cta_path": "/y", "diagnosis": "no page yet"},
    ]
    result, created = _run_action_plan(items, place_side_effect=lambda tid, actor_id=None: {"gid": "m1", "name": "Ivy"})

    assert result["status"] == "ok"
    assert result["created"] == 2 and result["existing"] == 0
    assert result["placed"] == 2 and result["held"] == 0
    # Each task carries source='action_plan' + the producer's stable source_ref, so
    # it composes with the auto-producer (no duplicates).
    from services.task_producers import action_source_ref
    assert created[0]["source"] == "action_plan"
    assert created[0]["source_ref"] == action_source_ref("c1", items[0])
    assert created[0]["name"] == "Reoptimize the page"


def test_handoff_action_plan_counts_existing_and_held():
    items = [
        {"kind": "quick_win", "keyword": "a", "recommendation": "Do A"},
        {"kind": "opportunity", "keyword": "b", "recommendation": "Do B"},
    ]

    def _create(name, kw):
        # first is a brand-new task, second already exists (producer made it).
        if name == "Do B":
            return {"id": "task-existing", "_existing": True}
        return {"id": "task-new"}

    # 'Do A' places; 'Do B' held (team at capacity).
    def _place(tid, actor_id=None):
        return {"gid": "m1", "name": "Ivy"} if tid == "task-new" else {"gid": None, "held": True, "reason": "team_at_capacity"}

    result, _ = _run_action_plan(items, place_side_effect=_place, create_side_effect=_create)
    assert result["created"] == 1 and result["existing"] == 1
    assert result["placed"] == 1 and result["held"] == 1


def test_handoff_action_plan_empty():
    with patch.object(ph, "_latest_plan_items", return_value=[]):
        result = ph.handoff_action_plan("c1")
    assert result["status"] == "empty" and result["total"] == 0


def test_handoff_action_plan_one_item_failure_does_not_abort_batch():
    items = [{"kind": "quick_win", "keyword": "a", "recommendation": "Do A"},
             {"kind": "opportunity", "keyword": "b", "recommendation": "Do B"}]

    def _create(name, kw):
        if name == "Do A":
            raise RuntimeError("boom")
        return {"id": "task-b"}

    result, _ = _run_action_plan(items, place_side_effect=lambda tid, actor_id=None: {"gid": "m1", "name": "Ivy"},
                                 create_side_effect=_create)
    # A failed, B created + placed — the batch survived.
    assert result["created"] == 1 and result["placed"] == 1


# ---------------------------------------------------------------------------
# Combined engine: native gate + scope routing
# ---------------------------------------------------------------------------
async def test_run_handoff_native_disabled_short_circuits():
    with patch.object(ph, "native_enabled", return_value=False):
        result = await ph.run_handoff("c1", scope="both")
    assert result == {"status": "native_disabled"}


async def test_run_handoff_both_calls_both_halves():
    ap_result = {"status": "ok", "created": 1, "existing": 0, "placed": 1, "held": 0, "total": 1}
    prop_result = {"status": "ok", "approved": 2, "skipped_senior": 0, "failed": 0, "tasks": []}
    with (
        patch.object(ph, "native_enabled", return_value=True),
        patch.object(ph, "handoff_action_plan", return_value=ap_result) as ap_fn,
        patch("services.strategist_proposals.handoff_open_proposals", return_value=prop_result) as pr_fn,
    ):
        result = await ph.run_handoff("c1", scope="both", actor_id="u1", actor_role="admin")

    ap_fn.assert_called_once()
    pr_fn.assert_awaited_once()
    assert result["action_plan"] == ap_result and result["proposals"] == prop_result


async def test_run_handoff_scope_action_plan_only():
    with (
        patch.object(ph, "native_enabled", return_value=True),
        patch.object(ph, "handoff_action_plan", return_value={"status": "empty"}) as ap_fn,
        patch("services.strategist_proposals.handoff_open_proposals") as pr_fn,
    ):
        result = await ph.run_handoff("c1", scope="action_plan")
    ap_fn.assert_called_once()
    pr_fn.assert_not_called()
    assert "proposals" not in result


# ---------------------------------------------------------------------------
# Summary + confirm text
# ---------------------------------------------------------------------------
def test_summarize_shapes():
    assert "isn't enabled" in ph.summarize({"status": "native_disabled"})
    s = ph.summarize({"action_plan": {"status": "ok", "created": 2, "existing": 1, "placed": 2, "held": 1},
                      "proposals": {"status": "ok", "approved": 1, "skipped_senior": 1}})
    assert "3 Action Plan task(s)" in s and "2 assigned" in s and "1 held" in s
    assert "1 proposal(s) approved" in s and "senior" in s


def test_confirm_phrase_pluralizes():
    with patch.object(ph, "preview_counts", return_value={"action_plan": 1, "proposals": 3}):
        phrase = ph.confirm_phrase("c1", "both")
    assert "1 Action Plan item " in phrase and "3 open proposals" in phrase
    assert "PACE to assign" in phrase


# ---------------------------------------------------------------------------
# Enqueue dedupe
# ---------------------------------------------------------------------------
def test_enqueue_dedupes_in_flight():
    sb = MagicMock()
    chain = sb.table.return_value
    for m in ("select", "eq", "in_", "limit"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = MagicMock(data=[{"id": "job-existing"}])
    with patch.object(ph, "get_supabase", return_value=sb):
        job_id = ph.enqueue_plan_handoff("c1", scope="both")
    assert job_id == "job-existing"
    chain.insert.assert_not_called()
