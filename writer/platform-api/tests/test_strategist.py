"""Unit tests for services.strategist — the pure output-contract enforcement
(sanitize_review: §3 passthroughs, disavow rule, frozen observation-only),
prompt assembly, and the digest-notification gate. No DB / no LLM (the run
loop's I/O is covered by integration testing, per repo convention)."""

from __future__ import annotations

from services import strategist


def _proposal(**over) -> dict:
    p = {
        "title": "Fund a link round",
        "action": "Add 10 niche edits to the money page",
        "rationale": "RD gap vs page-1 median",
        "sop_citation": "Link Building SOP §Referring Domains",
        "requires": "approval",
    }
    p.update(over)
    return p


# ---------------------------------------------------------------------------
# sanitize_review
# ---------------------------------------------------------------------------
def test_sanitize_defaults_and_status():
    out = strategist.sanitize_review(
        {"assessment": " read ", "proposals": [_proposal(requires="bogus")]},
        frozen=False,
    )
    assert out["assessment"] == "read"
    p = out["proposals"][0]
    assert p["status"] == "proposed"
    assert p["requires"] == "approval"  # bogus enum → default


def test_sanitize_forces_senior_on_passthrough_territory():
    cases = [
        _proposal(title="Lift the freeze", action="Unfreeze the client and resume links"),
        _proposal(title="GBP recovery", action="File a reinstatement for the suspended listing"),
        _proposal(title="Entity split", action="Spin up a separate entity / DBA for the HVAC side"),
        _proposal(title="Push harder", action="Run an overclock Hydra diagram at the money page"),
        _proposal(title="Budget call", action="Accept a margin below 50% this month to fund recovery"),
    ]
    out = strategist.sanitize_review({"assessment": "a", "proposals": cases}, frozen=False)
    assert len(out["proposals"]) == 5
    assert all(p["requires"] == "senior" for p in out["proposals"])


def test_sanitize_ordinary_proposal_keeps_model_requires():
    out = strategist.sanitize_review(
        {"assessment": "a", "proposals": [_proposal(requires="none")]}, frozen=False
    )
    assert out["proposals"][0]["requires"] == "none"


def test_sanitize_drops_disavow_to_question():
    out = strategist.sanitize_review(
        {"assessment": "a", "proposals": [
            _proposal(title="Clean up links", action="Submit a disavow file for the spam domains"),
            _proposal(),  # a normal one survives
        ]},
        frozen=False,
    )
    assert len(out["proposals"]) == 1
    assert any("never disavow" in q for q in out["questions"])


def test_sanitize_frozen_client_is_observation_only():
    out = strategist.sanitize_review(
        {"assessment": "a", "proposals": [_proposal(), _proposal(title="Other")]},
        frozen=True,
    )
    assert out["proposals"] == []
    assert any("frozen" in q for q in out["questions"])


def test_sanitize_skips_malformed_entries():
    out = strategist.sanitize_review(
        {
            "assessment": "a",
            "proposals": [{"title": "no action"}, "not a dict", _proposal()],
            "findings": [{"synthesis": ""}, {"synthesis": "real", "signal_refs": ["kw:x"]}],
            "questions": ["", "  real q  "],
        },
        frozen=False,
    )
    assert len(out["proposals"]) == 1
    assert len(out["findings"]) == 1 and out["findings"][0]["synthesis"] == "real"
    assert out["questions"] == ["real q"]


def test_sanitize_coerces_effort():
    out = strategist.sanitize_review(
        {"assessment": "a", "proposals": [
            _proposal(effort="massive"),
            _proposal(effort="low"),
        ]},
        frozen=False,
    )
    assert out["proposals"][0]["effort"] is None
    assert out["proposals"][1]["effort"] == "low"


# ---------------------------------------------------------------------------
# cost grounding — the LLM never writes a dollar; the code computes it from the
# real price list (Recipe Engine deliverables + tool_costs API ops).
# ---------------------------------------------------------------------------
def test_sanitize_grounds_recipe_cost():
    # 5 content/location pages @ $5 each = $25, from the Recipe Engine price list.
    out = strategist.sanitize_review(
        {"assessment": "a", "proposals": [
            _proposal(cost_basis="recipe", costed_items=[{"task_type": "content_page", "quantity": 5}]),
        ]},
        frozen=False,
    )
    p = out["proposals"][0]
    assert p["est_cost_usd"] == 25.0
    assert p["cost_basis"] == "recipe"
    assert p["costed_items"] == [{"task_type": "content_page", "quantity": 5.0}]


def test_sanitize_unverified_tool_op_shows_no_dollar():
    # a geo-grid scan is a tool op whose price isn't researched yet → no $0.
    out = strategist.sanitize_review(
        {"assessment": "a", "proposals": [
            _proposal(cost_basis="operational", costed_items=[{"task_type": "geo_grid_scan", "quantity": 1}]),
        ]},
        frozen=False,
    )
    p = out["proposals"][0]
    assert p["est_cost_usd"] is None          # not $0 — unpriced
    assert p["cost_basis"] == "operational"
    assert p["costed_items"] == [{"task_type": "geo_grid_scan", "quantity": 1.0}]


def test_sanitize_ignores_unknown_task_type_and_bad_qty():
    out = strategist.sanitize_review(
        {"assessment": "a", "proposals": [
            _proposal(cost_basis="recipe", costed_items=[
                {"task_type": "made_up_tactic", "quantity": 3},
                {"task_type": "content_page", "quantity": 0},   # non-positive dropped
                {"task_type": "content_page", "quantity": 2},
            ]),
        ]},
        frozen=False,
    )
    p = out["proposals"][0]
    assert p["costed_items"] == [{"task_type": "content_page", "quantity": 2.0}]
    assert p["est_cost_usd"] == 10.0


def test_sanitize_no_items_defaults_cost_none():
    out = strategist.sanitize_review(
        {"assessment": "a", "proposals": [_proposal()]}, frozen=False
    )
    p = out["proposals"][0]
    assert p["est_cost_usd"] is None
    assert p["cost_basis"] == "none"
    assert p["costed_items"] == []


def test_render_price_list_has_both_catalogs():
    pl = strategist.render_price_list()
    assert "content_page" in pl and "$5" in pl          # a real deliverable price
    assert "geo_grid_scan" in pl and "price pending" in pl   # an unverified tool op


# ---------------------------------------------------------------------------
# build_run_prompt
# ---------------------------------------------------------------------------
def test_run_prompt_carries_all_blocks_in_order():
    prompt = strategist.build_run_prompt(
        '{"d": 1}', "SOPS", "CARDS",
        trigger="scheduled", frozen=False, max_drilldowns=4, max_paid=1,
    )
    assert prompt.index("TRIGGER: scheduled") < prompt.index("MODULE CARDS")
    assert prompt.index("MODULE CARDS") < prompt.index("AGENCY SOPs")
    assert prompt.index("AGENCY SOPs") < prompt.index("CLIENT DIGEST")
    assert "at most 4 tool calls" in prompt and "audit_page at most 1" in prompt


def test_run_prompt_frozen_and_escalation():
    prompt = strategist.build_run_prompt(
        "{}", "", "", trigger="escalation", frozen=True, max_drilldowns=4, max_paid=1,
        escalation_context={"kind": "episode_escalated", "keyword": "plumber"},
    )
    assert "escalation brief" in prompt
    assert "FROZEN" in prompt and "NO proposals" in prompt
    assert "episode_escalated" in prompt


# ---------------------------------------------------------------------------
# review_notification (the "empty review posts nothing" gate)
# ---------------------------------------------------------------------------
def test_empty_review_posts_nothing():
    assert strategist.review_notification(
        {"trigger": "scheduled", "assessment": "All quiet.", "findings": [], "proposals": [], "questions": []},
        "Acme",
    ) is None


def test_review_notification_counts_and_severity():
    note = strategist.review_notification(
        {
            "trigger": "scheduled",
            "assessment": "x" * 500,
            "proposals": [
                {"title": "a", "requires": "senior"},
                {"title": "b", "requires": "approval"},
            ],
            "questions": ["q"],
            "findings": [],
        },
        "Acme",
    )
    assert "2 proposals (1 senior-only)" in note["title"]
    assert "1 open question" in note["title"]
    assert note["severity"] == "warning"  # senior-only present
    assert len(note["summary"]) <= 401


def test_escalation_review_titled_as_brief():
    note = strategist.review_notification(
        {"trigger": "escalation", "assessment": "brief", "findings": [{"synthesis": "s"}],
         "proposals": [], "questions": []},
        "Acme",
    )
    assert note["title"].startswith("Escalation brief ready")
    assert note["severity"] == "warning"


def test_findings_only_review_still_posts_info():
    note = strategist.review_notification(
        {"trigger": "scheduled", "assessment": "a", "findings": [{"synthesis": "s"}],
         "proposals": [], "questions": []},
        "Acme",
    )
    assert note is not None and note["severity"] == "info"
    assert "1 finding" in note["title"]


# ---------------------------------------------------------------------------
# strategist_enabled gating (the smoke-gate safety rail): with the flag off —
# its default — every trigger path no-ops before touching the DB.
# ---------------------------------------------------------------------------
def test_enqueue_returns_none_while_disabled():
    from config import settings

    assert settings.strategist_enabled is False  # the shipped default
    # No DB mock on purpose: a DB touch would blow up, proving the gate is
    # checked first.
    assert strategist.enqueue_strategy_review("client-1") is None


def test_weekly_pass_noops_while_disabled():
    assert strategist.enqueue_due_strategy_reviews() == 0


def test_job_handler_fails_cleanly_while_disabled():
    import asyncio
    from unittest.mock import MagicMock, patch

    supabase = MagicMock()
    updates: list[dict] = []
    chain = supabase.table.return_value
    chain.update.side_effect = lambda payload: (updates.append(payload), chain)[1]
    chain.eq.return_value = chain
    chain.execute.return_value = MagicMock(data=[])

    job = {"id": "job-1", "payload": {"client_id": "c-1", "review_id": "r-1"}}
    with patch.object(strategist, "get_supabase", return_value=supabase):
        asyncio.get_event_loop().run_until_complete(strategist.run_strategy_review_job(job))

    assert any(u.get("error") == "strategist_disabled" and u.get("status") == "failed" for u in updates)
    # Both the job row and the pre-created review row are closed out.
    assert len([u for u in updates if u.get("status") == "failed"]) == 2
