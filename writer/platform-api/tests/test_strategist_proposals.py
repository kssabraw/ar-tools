"""Unit tests for services.strategist_proposals — the extracted proposal-decision
core (approve/dismiss side-effects) and the bulk open-proposal handoff.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import strategist_proposals as sp


# ---------------------------------------------------------------------------
# Pure
# ---------------------------------------------------------------------------
def test_open_proposal_indices():
    proposals = [
        {"status": "approved"},
        {"status": "proposed"},
        {},                       # no status → treated as still-open
        {"status": "dismissed"},
        {"status": "proposed"},
    ]
    assert sp.open_proposal_indices(proposals) == [1, 2, 4]


# ---------------------------------------------------------------------------
# apply_decision
# ---------------------------------------------------------------------------
def _fake_supabase(review_row: dict):
    """A fake honouring the two tables apply_decision touches. Captures the
    strategy_reviews update payload in ``captured``."""
    captured: dict = {}

    def table(name):
        mock = MagicMock()
        mock.select.return_value = mock
        mock.eq.return_value = mock
        mock.limit.return_value = mock
        if name == "strategy_reviews":
            mock.execute.return_value = MagicMock(data=[review_row])

            def _update(payload):
                captured["proposals"] = payload.get("proposals")
                return mock
            mock.update.side_effect = _update
        elif name == "clients":
            mock.execute.return_value = MagicMock(data=[{"name": "Acme"}])
        return mock

    sb = MagicMock()
    sb.table.side_effect = table
    return sb, captured


async def test_apply_decision_invalid_status_raises():
    with pytest.raises(sp.ProposalError) as exc:
        await sp.apply_decision("r1", 0, "bogus", actor_id="u1", actor_role="admin")
    assert exc.value.code == "invalid_status"


async def test_apply_decision_senior_gate_blocks_non_admin():
    review = {"id": "r1", "client_id": "c1", "trigger": "on_demand",
              "proposals": [{"title": "P", "requires": "senior", "status": "proposed"}]}
    sb, _ = _fake_supabase(review)
    with patch.object(sp, "get_supabase", return_value=sb):
        with pytest.raises(sp.ProposalError) as exc:
            await sp.apply_decision("r1", 0, "approved", actor_id="u1", actor_role="staff")
    assert exc.value.code == "senior_approval_required"


async def test_apply_decision_approve_pushes_places_and_persists():
    review = {"id": "r1", "client_id": "c1", "trigger": "on_demand",
              "proposals": [{"title": "Fund a link round", "requires": "approval", "status": "proposed"}]}
    sb, captured = _fake_supabase(review)
    with (
        patch.object(sp, "get_supabase", return_value=sb),
        patch("services.asana_push.push_proposal", new=AsyncMock(return_value={"gid": "task-1", "url": "/t"})) as push,
        patch("services.interventions.source_ref_for_proposal", return_value="sr"),
        patch("services.interventions.register_from_proposal", return_value="iid"),
        patch("services.sermastr_audit.record_decision") as audit,
        patch("services.agent_bus.post"), patch("services.agent_bus.mark_acted"),
    ):
        res = await sp.apply_decision("r1", 0, "approved", actor_id="u1", actor_role="staff")

    push.assert_awaited_once()
    audit.assert_called_once()
    assert res["status"] == "approved" and res["asana_task"] == {"gid": "task-1", "url": "/t"}
    # Persisted with the proposal now approved + its task attached.
    assert captured["proposals"][0]["status"] == "approved"
    assert captured["proposals"][0]["asana_task"] == {"gid": "task-1", "url": "/t"}


async def test_apply_decision_review_not_found():
    sb, _ = _fake_supabase(None)
    # strategy_reviews returns [] → not found.
    sb.table.side_effect = lambda name: MagicMock(
        select=lambda *a, **k: MagicMock(eq=lambda *a, **k: MagicMock(
            limit=lambda *a, **k: MagicMock(execute=lambda: MagicMock(data=[]))))
    )
    with patch.object(sp, "get_supabase", return_value=sb):
        with pytest.raises(sp.ProposalError) as exc:
            await sp.apply_decision("r1", 0, "approved", actor_id="u1", actor_role="admin")
    assert exc.value.code == "review_not_found"


# ---------------------------------------------------------------------------
# handoff_open_proposals
# ---------------------------------------------------------------------------
async def test_handoff_open_proposals_skips_senior_and_tallies():
    review = {"id": "r1", "proposals": [
        {"title": "A", "requires": "approval", "status": "proposed"},
        {"title": "B", "requires": "senior", "status": "proposed"},
        {"title": "C", "requires": "approval", "status": "approved"},  # already done → not open
        {"title": "D", "requires": "approval", "status": "proposed"},
    ]}

    async def _apply(review_id, idx, decision, **kw):
        if idx == 1:  # the senior one
            raise sp.ProposalError("senior_approval_required")
        return {"asana_task": {"gid": f"t{idx}"}}

    with (
        patch.object(sp, "_latest_review_with_proposals", return_value=review),
        patch.object(sp, "apply_decision", side_effect=_apply) as apply_fn,
    ):
        result = await sp.handoff_open_proposals("c1", actor_id=None, actor_role=None)

    # Open indices are 0, 1, 3 (2 is already approved). 1 is senior → skipped.
    assert result["open"] == 3
    assert result["approved"] == 2 and result["skipped_senior"] == 1 and result["failed"] == 0
    assert result["tasks"] == [{"gid": "t0"}, {"gid": "t3"}]
    assert apply_fn.await_count == 3


async def test_handoff_open_proposals_no_review():
    with patch.object(sp, "_latest_review_with_proposals", return_value=None):
        result = await sp.handoff_open_proposals("c1", actor_id=None, actor_role=None)
    assert result["status"] == "no_review" and result["approved"] == 0


def test_superseded_is_closed_not_open():
    from services import strategist_proposals as sp

    props = [{"status": "proposed"}, {"status": "superseded"}, {"status": "approved"}, {}]
    assert sp.open_proposal_indices(props) == [0, 3]


def test_apply_decision_refuses_superseded_and_invalid(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock
    from services import strategist_proposals as sp

    supabase = MagicMock()
    chain = supabase.table.return_value
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=[{
        "id": "r", "client_id": "c", "trigger": "goal_recovery",
        "proposals": [{"title": "x", "status": "superseded"}],
    }])
    monkeypatch.setattr(sp, "get_supabase", lambda: supabase)

    try:
        asyncio.run(sp.apply_decision("r", 0, "approved", actor_id="u", actor_role="admin"))
        assert False, "expected ProposalError"
    except sp.ProposalError as exc:
        assert exc.code == "proposal_superseded"
    try:
        asyncio.run(sp.apply_decision("r", 0, "superseded", actor_id="u", actor_role="admin"))
        assert False, "expected ProposalError"
    except sp.ProposalError as exc:
        assert exc.code == "invalid_status"
