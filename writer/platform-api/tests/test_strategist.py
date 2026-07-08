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


def test_sanitize_grounds_verified_tool_op():
    # a geo-grid scan is now a researched, verified tool op → real dollars.
    out = strategist.sanitize_review(
        {"assessment": "a", "proposals": [
            _proposal(cost_basis="operational", costed_items=[{"task_type": "geo_grid_scan", "quantity": 3}]),
        ]},
        frozen=False,
    )
    p = out["proposals"][0]
    assert p["est_cost_usd"] == round(3 * 0.37, 2)   # 3 keyword-scans @ $0.37
    assert p["cost_basis"] == "operational"


def test_sanitize_unpriced_operational_shows_no_dollar():
    # an operational proposal that names no known priced op → "tool cost", never $0.
    out = strategist.sanitize_review(
        {"assessment": "a", "proposals": [
            _proposal(cost_basis="operational", costed_items=[{"task_type": "some_new_tool", "quantity": 1}]),
        ]},
        frozen=False,
    )
    p = out["proposals"][0]
    assert p["est_cost_usd"] is None          # not $0 — unknown/unpriced
    assert p["cost_basis"] == "operational"   # preserved from the declared basis
    assert p["costed_items"] == []            # the unknown task_type is filtered out


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
    assert "content_page" in pl and "$5" in pl        # a real deliverable price
    assert "geo_grid_scan" in pl and "$0.37" in pl    # a researched tool op
    assert "keyword_research" in pl and "$0.50" in pl  # LLM op now priced
    assert "price pending" not in pl                  # everything is researched now


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
        asyncio.run(strategist.run_strategy_review_job(job))

    assert any(u.get("error") == "strategist_disabled" and u.get("status") == "failed" for u in updates)
    # Both the job row and the pre-created review row are closed out.
    assert len([u for u in updates if u.get("status") == "failed"]) == 2


# ---------------------------------------------------------------------------
# opportunity sweep — proactive runs for QUIET clients (no active signals)
# ---------------------------------------------------------------------------
def test_opportunity_sweep_targets_quiet_clients_not_recently_run(monkeypatch):
    from unittest.mock import MagicMock

    def fake_table(name):
        m = MagicMock()
        if name == "clients":
            m.select.return_value.eq.return_value.execute.return_value.data = [
                {"id": "a"}, {"id": "b"}, {"id": "c"},
            ]
        else:  # strategy_reviews within the interval
            m.select.return_value.gte.return_value.execute.return_value.data = [
                {"client_id": "b"},
            ]
        return m

    supabase = MagicMock()
    supabase.table.side_effect = fake_table
    monkeypatch.setattr(strategist, "get_supabase", lambda: supabase)

    # a is active (excluded), b ran recently (excluded) → only c is due
    assert strategist.clients_due_opportunity_sweep({"a"}, 28) == {"c"}


def test_clients_scheduled_within_durable_weekly_guard(monkeypatch):
    from unittest.mock import MagicMock

    # days <= 0 → disabled, no DB touched
    assert strategist.clients_scheduled_within(0) == set()

    supabase = MagicMock()
    chain = supabase.table.return_value
    chain.select.return_value.eq.return_value.gte.return_value.execute.return_value.data = [
        {"client_id": "a"}, {"client_id": "b"}, {"client_id": None},
    ]
    monkeypatch.setattr(strategist, "get_supabase", lambda: supabase)

    assert strategist.clients_scheduled_within(6) == {"a", "b"}
    # scoped to the scheduled trigger so escalation/on-demand runs don't count
    chain.select.return_value.eq.assert_called_once_with("trigger", "scheduled")


def test_weekly_pass_skips_active_clients_run_this_week(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "strategist_enabled", True)
    monkeypatch.setattr(strategist, "clients_with_active_signals", lambda: {"a", "b"})
    # b already had a scheduled run this week → only a is still due
    monkeypatch.setattr(strategist, "clients_scheduled_within", lambda days: {"b"})
    monkeypatch.setattr(
        strategist, "clients_due_opportunity_sweep", lambda active, interval: set()
    )
    # every due client is assigned to today's weekday (3)
    monkeypatch.setattr(strategist, "client_weekday_map", lambda ids: {c: 3 for c in ids})
    enqueued: list[tuple] = []
    monkeypatch.setattr(
        strategist,
        "enqueue_strategy_review",
        lambda cid, trigger="on_demand": (enqueued.append((cid, trigger)), "rid")[1],
    )

    assert strategist.enqueue_due_strategy_reviews(3) == 1
    assert enqueued == [("a", "scheduled")]


def test_weekly_pass_staggers_by_assigned_weekday(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "strategist_enabled", True)
    monkeypatch.setattr(strategist, "clients_with_active_signals", lambda: {"a", "b", "c"})
    monkeypatch.setattr(strategist, "clients_scheduled_within", lambda days: set())
    monkeypatch.setattr(
        strategist, "clients_due_opportunity_sweep", lambda active, interval: set()
    )
    # a → Mon(0), b → Tue(1), c → Mon(0)
    monkeypatch.setattr(
        strategist, "client_weekday_map", lambda ids: {"a": 0, "b": 1, "c": 0}
    )
    enqueued: list[tuple] = []
    monkeypatch.setattr(
        strategist,
        "enqueue_strategy_review",
        lambda cid, trigger="on_demand": (enqueued.append((cid, trigger)), "rid")[1],
    )

    # On Monday only a and c fire; b waits for Tuesday.
    assert strategist.enqueue_due_strategy_reviews(0) == 2
    assert enqueued == [("a", "scheduled"), ("c", "scheduled")]


def test_client_weekday_map_falls_back_to_global_default(monkeypatch):
    from unittest.mock import MagicMock
    from config import settings

    monkeypatch.setattr(settings, "strategist_weekly_weekday", 1)
    supabase = MagicMock()
    chain = supabase.table.return_value
    # a has an explicit day (4); b is unset (null); c isn't returned at all
    chain.select.return_value.in_.return_value.execute.return_value.data = [
        {"id": "a", "strategist_weekday": 4},
        {"id": "b", "strategist_weekday": None},
    ]
    monkeypatch.setattr(strategist, "get_supabase", lambda: supabase)

    result = strategist.client_weekday_map({"a", "b", "c"})
    assert result == {"a": 4, "b": 1, "c": 1}

    # empty input never touches the DB
    supabase2 = MagicMock()
    monkeypatch.setattr(strategist, "get_supabase", lambda: supabase2)
    assert strategist.client_weekday_map(set()) == {}
    supabase2.table.assert_not_called()


def test_opportunity_sweep_disabled_and_no_quiet(monkeypatch):
    from unittest.mock import MagicMock

    # interval <= 0 → off, no DB touched
    assert strategist.clients_due_opportunity_sweep({"a"}, 0) == set()

    # every client active → nothing to sweep (reviews table never queried)
    supabase = MagicMock()
    clients_m = MagicMock()
    clients_m.select.return_value.eq.return_value.execute.return_value.data = [{"id": "a"}]
    supabase.table.return_value = clients_m
    monkeypatch.setattr(strategist, "get_supabase", lambda: supabase)
    assert strategist.clients_due_opportunity_sweep({"a"}, 28) == set()
    supabase.table.assert_called_once_with("clients")
