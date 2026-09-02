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


# ---------------------------------------------------------------------------
# intervention-outcome target passthrough (sanitize_proposal_target)
# ---------------------------------------------------------------------------
def test_sanitize_passes_valid_intervention_target():
    out = strategist.sanitize_review(
        {"assessment": "a", "proposals": [
            _proposal(target={"tactic_type": "link_building", "keyword": "emergency plumber"}),
        ]},
        frozen=False,
    )
    tgt = out["proposals"][0].get("target")
    assert tgt == {"tactic_type": "link_building", "keyword": "emergency plumber", "page_url": None}


def test_sanitize_drops_out_of_scope_or_anchorless_target():
    out = strategist.sanitize_review(
        {"assessment": "a", "proposals": [
            _proposal(target={"tactic_type": "gbp_post", "keyword": "x"}),   # out-of-scope tactic
            _proposal(target={"tactic_type": "reoptimization"}),            # no anchor
            _proposal(),                                                     # no target at all
        ]},
        frozen=False,
    )
    assert all("target" not in p for p in out["proposals"])


def test_sanitize_proposal_target_pure():
    assert strategist.sanitize_proposal_target(None) is None
    assert strategist.sanitize_proposal_target({"tactic_type": "reoptimization"}) is None
    assert strategist.sanitize_proposal_target(
        {"tactic_type": "reoptimization", "page_url": "https://x/y"}
    ) == {"tactic_type": "reoptimization", "keyword": None, "page_url": "https://x/y"}


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
# Monthly plan review → PACE assignment handoff
# ---------------------------------------------------------------------------
def test_run_prompt_monthly_plan_review_orientation():
    prompt = strategist.build_run_prompt(
        "{}", "", "", trigger="monthly_plan_review",
        frozen=False, max_drilldowns=4, max_paid=1,
    )
    assert "TRIGGER: monthly_plan_review" in prompt
    assert "MONTHLY TASK-PLAN REVIEW" in prompt
    # It must steer toward assignable proposals (PACE places approved ones) and
    # not appear on other triggers.
    assert "PROPOSAL" in prompt and "capacity" in prompt
    other = strategist.build_run_prompt(
        "{}", "", "", trigger="scheduled",
        frozen=False, max_drilldowns=4, max_paid=1,
    )
    assert "MONTHLY TASK-PLAN REVIEW" not in other


def test_monthly_plan_review_notification_title():
    note = strategist.review_notification(
        {"trigger": "monthly_plan_review", "assessment": "plan tweaks",
         "proposals": [{"title": "add a link round", "requires": "approval"}],
         "questions": [], "findings": []},
        "Acme",
    )
    assert note is not None
    assert note["title"].startswith("Monthly plan review: Acme")
    assert "1 proposal" in note["title"]


def test_monthly_plan_review_is_a_valid_trigger():
    assert "monthly_plan_review" in strategist.VALID_TRIGGERS


def test_is_monthly_review_day_lead_lands_on_generation_day():
    from datetime import date

    # generate_day=1, lead=3 → review fires on the last-3rd day of the prior
    # month (Aug 29 precedes Sep 1 generation).
    assert strategist.is_monthly_review_day(date(2026, 8, 29), 1, 3) is True
    assert strategist.is_monthly_review_day(date(2026, 8, 28), 1, 3) is False
    assert strategist.is_monthly_review_day(date(2026, 8, 30), 1, 3) is False


def test_is_monthly_review_day_mid_month_and_short_month_clamp():
    from datetime import date

    # generate_day=15, lead=2 → fires on the 13th, in the same month.
    assert strategist.is_monthly_review_day(date(2026, 6, 13), 15, 2) is True
    assert strategist.is_monthly_review_day(date(2026, 6, 14), 15, 2) is False
    # generate_day=31, lead=1 → clamps to the month's real length; Feb 2026 has
    # 28 days, so the review fires Feb 27 (→ clamped gen day 28).
    assert strategist.is_monthly_review_day(date(2026, 2, 27), 31, 1) is True
    assert strategist.is_monthly_review_day(date(2026, 2, 26), 31, 1) is False


def test_is_monthly_review_day_zero_lead_is_generation_day_itself():
    from datetime import date

    assert strategist.is_monthly_review_day(date(2026, 9, 1), 1, 0) is True
    assert strategist.is_monthly_review_day(date(2026, 9, 2), 1, 0) is False


def test_monthly_review_allowlist_parses_and_trims(monkeypatch):
    monkeypatch.setattr(
        strategist.settings, "strategist_monthly_plan_review_client_ids",
        " a , b ,, c ",
    )
    assert strategist._monthly_review_allowlist() == {"a", "b", "c"}
    monkeypatch.setattr(
        strategist.settings, "strategist_monthly_plan_review_client_ids", "",
    )
    assert strategist._monthly_review_allowlist() == set()


def test_enqueue_monthly_reviews_noops_when_flag_off(monkeypatch):
    # Both gates must be on; with the feature flag off it returns 0 without
    # touching the DB (no supabase call needed).
    monkeypatch.setattr(strategist.settings, "strategist_enabled", True)
    monkeypatch.setattr(
        strategist.settings, "strategist_monthly_plan_review_enabled", False,
    )
    assert strategist.enqueue_due_monthly_plan_reviews() == 0


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


class TestClientsWithBehindGoals:
    """A behind/overdue campaign goal (with a real baseline) is an active signal
    that summons the weekly review; a null-baseline 'behind' artifact is not."""

    @staticmethod
    def _sb(client_ids, monkeypatch):
        from unittest.mock import MagicMock

        supabase = MagicMock()
        chain = supabase.table.return_value
        chain.select.return_value.eq.return_value.execute.return_value.data = [
            {"client_id": cid} for cid in client_ids
        ]
        monkeypatch.setattr(strategist, "get_supabase", lambda: supabase)
        return supabase

    def test_disabled_by_flag(self, monkeypatch):
        from config import settings

        monkeypatch.setattr(settings, "strategist_goal_trigger_enabled", False)
        # returns immediately, never touches the DB
        supabase_calls: list = []
        monkeypatch.setattr(
            strategist, "get_supabase",
            lambda: supabase_calls.append(1) or (_ for _ in ()).throw(AssertionError("db touched")),
        )
        assert strategist.clients_with_behind_goals() == set()
        assert supabase_calls == []

    def test_behind_with_baseline_included_artifact_excluded(self, monkeypatch):
        from config import settings
        from services import campaign_goals

        monkeypatch.setattr(settings, "strategist_goal_trigger_enabled", True)
        self._sb(["a", "b", "c", "d"], monkeypatch)

        assessed = {
            "a": [{"status": "behind", "baseline_value": 20.0}],       # real behind
            "b": [{"status": "overdue", "baseline_value": 5.0}],       # real overdue
            "c": [{"status": "behind", "baseline_value": None}],       # null-baseline artifact
            "d": [{"status": "on_track", "baseline_value": 3.0},
                  {"status": "manual", "baseline_value": None}],       # nothing behind
        }
        monkeypatch.setattr(campaign_goals, "assess_goals", lambda cid, **kw: assessed[cid])
        assert strategist.clients_with_behind_goals() == {"a", "b"}

    def test_one_client_measure_failure_never_drops_the_rest(self, monkeypatch):
        from config import settings
        from services import campaign_goals

        monkeypatch.setattr(settings, "strategist_goal_trigger_enabled", True)
        self._sb(["a", "boom"], monkeypatch)

        def fake_assess(cid, **kw):
            if cid == "boom":
                raise RuntimeError("measure blew up")
            return [{"status": "overdue", "baseline_value": 1.0}]

        monkeypatch.setattr(campaign_goals, "assess_goals", fake_assess)
        assert strategist.clients_with_behind_goals() == {"a"}


class TestStrategistExcluded:
    """A website property (clients.strategist_enabled=false) opts out of the
    automated strategist; the check fails open so a read blip never silences a
    real client."""

    @staticmethod
    def _sb(data=None, boom=False):
        from unittest.mock import MagicMock

        supabase = MagicMock()
        if boom:
            supabase.table.side_effect = RuntimeError("db down")
            return supabase
        chain = supabase.table.return_value
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(data=data or [])
        return supabase

    def test_excluded_when_flag_is_false(self, monkeypatch):
        monkeypatch.setattr(strategist, "get_supabase", lambda: self._sb([{"strategist_enabled": False}]))
        assert strategist._strategist_excluded("c1") is True

    def test_included_when_flag_is_true(self, monkeypatch):
        monkeypatch.setattr(strategist, "get_supabase", lambda: self._sb([{"strategist_enabled": True}]))
        assert strategist._strategist_excluded("c1") is False

    def test_included_when_row_missing(self, monkeypatch):
        monkeypatch.setattr(strategist, "get_supabase", lambda: self._sb([]))
        assert strategist._strategist_excluded("c1") is False

    def test_fails_open_on_read_error(self, monkeypatch):
        monkeypatch.setattr(strategist, "get_supabase", lambda: self._sb(boom=True))
        assert strategist._strategist_excluded("c1") is False


# ---------------------------------------------------------------------------
# Output-limit truncation guard (PRD: sermastr-autonomous-recovery-plans §3 PR 1)
# From mid-August 2026 every scheduled review hit max_tokens on its emit round
# and persisted as 'complete' with 0 proposals. These pin the three pieces of
# the fix: schema order, the one forced retry, and the never-silent flag.
# ---------------------------------------------------------------------------
def test_emit_schema_writes_proposals_and_questions_before_findings():
    props = list(strategist._EMIT_TOOL["input_schema"]["properties"])
    assert props.index("assessment") < props.index("proposals")
    assert props.index("proposals") < props.index("findings")
    assert props.index("questions") < props.index("findings")


def test_is_truncated_reads_stop_reason():
    from types import SimpleNamespace

    assert strategist.is_truncated(SimpleNamespace(stop_reason="max_tokens")) is True
    assert strategist.is_truncated(SimpleNamespace(stop_reason="tool_use")) is False
    assert strategist.is_truncated(SimpleNamespace()) is False


def test_truncation_followup_answers_every_tool_use_or_is_plain_text():
    from types import SimpleNamespace

    plain = strategist.truncation_followup([])
    assert isinstance(plain, str) and "CUT OFF" in plain

    blocks = [SimpleNamespace(id="tu-1"), SimpleNamespace(id="tu-2")]
    results = strategist.truncation_followup(blocks)
    assert [r["tool_use_id"] for r in results] == ["tu-1", "tu-2"]
    assert all(r["type"] == "tool_result" and "CUT OFF" in r["content"] for r in results)


def test_assistant_turn_never_empty():
    turn = strategist._assistant_turn([])
    assert turn["role"] == "assistant" and turn["content"]
    turn = strategist._assistant_turn(["block"])
    assert turn["content"] == ["block"]


class _Block:
    def __init__(self, name, input, id):
        self.type = "tool_use"
        self.name = name
        self.input = input
        self.id = id


def _resp(stop_reason, blocks, out_tokens=100):
    from types import SimpleNamespace

    return SimpleNamespace(
        stop_reason=stop_reason,
        content=blocks,
        usage=SimpleNamespace(input_tokens=10, output_tokens=out_tokens),
    )


def _run_with_responses(monkeypatch, responses, trigger="on_demand"):
    """Drive run_strategy_review against scripted Anthropic responses. Returns
    (recorded create() kwargs, persisted update payloads, emitted notifications)."""
    import asyncio
    from unittest.mock import MagicMock

    from services import anthropic_failover, sermastr_audit, strategist_tools

    calls: list[dict] = []
    queue = list(responses)

    class _Messages:
        async def create(self, **kw):
            calls.append(kw)
            return queue.pop(0)

    class _Client:
        messages = _Messages()

    async def _fake_call(clients, make_awaitable, *, log_tag="anthropic"):
        return await make_awaitable(clients[0])

    monkeypatch.setattr(anthropic_failover, "build_async_clients", lambda **kw: [_Client()])
    monkeypatch.setattr(anthropic_failover, "call_failover", _fake_call)
    monkeypatch.setattr(strategist_tools, "anthropic_tool_defs", lambda: [])
    monkeypatch.setattr(strategist_tools, "TOOLS", {})
    monkeypatch.setattr(sermastr_audit, "log_proposals", lambda *a, **k: None)
    monkeypatch.setattr(
        strategist.strategy_digest, "build_strategy_digest",
        lambda cid: {"client": {"name": "Acme"}, "active_domains": []},
    )
    monkeypatch.setattr(strategist.strategy_digest, "render_digest", lambda d, b: "{}")
    monkeypatch.setattr(strategist.sop_library, "load_module_cards", lambda: "")
    monkeypatch.setattr(strategist.sop_library, "select_sops_text", lambda *a, **k: "")
    monkeypatch.setattr(strategist.sop_store, "resolve_sops_text", lambda *a, **k: "")
    monkeypatch.setattr(strategist, "render_price_list", lambda: "")
    notes: list[dict] = []
    monkeypatch.setattr(strategist.notifications, "emit", lambda **kw: notes.append(kw))

    supabase = MagicMock()
    updates: list[dict] = []
    chain = supabase.table.return_value
    chain.update.side_effect = lambda payload: (updates.append(payload), chain)[1]
    chain.eq.return_value = chain
    chain.execute.return_value = MagicMock(data=[{"id": "r-1"}])
    monkeypatch.setattr(strategist, "get_supabase", lambda: supabase)

    asyncio.run(strategist.run_strategy_review("c-1", trigger=trigger, review_id="r-1"))
    return calls, updates, notes


def test_run_retries_once_on_truncated_emit_and_keeps_the_full_one(monkeypatch):
    cut = _resp("max_tokens", [_Block(
        "emit_strategy_review", {"assessment": "cut", "findings": [{"synthesis": "x"}]}, "tu-1",
    )], out_tokens=4096)
    full = _resp("tool_use", [_Block(
        "emit_strategy_review",
        {"assessment": "full", "proposals": [_proposal()], "questions": ["q?"]},
        "tu-2",
    )])
    calls, updates, _ = _run_with_responses(monkeypatch, [cut, full])

    assert len(calls) == 2
    # The retry forces the emit tool and answers the cut-off tool_use block
    # with the "cut off — re-emit compactly" tool_result.
    assert calls[1]["tool_choice"] == {"type": "tool", "name": "emit_strategy_review"}
    followup = calls[1]["messages"][-1]
    assert followup["role"] == "user"
    assert followup["content"][0]["tool_use_id"] == "tu-1"
    assert "CUT OFF" in followup["content"][0]["content"]
    # The partial emit was discarded; the full one is what persisted.
    done = next(u for u in updates if u.get("status") == "complete")
    assert done["assessment"] == "full"
    assert len(done["proposals"]) == 1
    assert done["questions"] == ["q?"]
    assert "truncated" not in done["token_usage"]


def test_run_flags_review_still_truncated_after_the_retry(monkeypatch):
    cut1 = _resp("max_tokens", [_Block(
        "emit_strategy_review", {"assessment": "cut", "findings": [{"synthesis": "x"}]}, "tu-1",
    )], out_tokens=4096)
    cut2 = _resp("max_tokens", [_Block(
        "emit_strategy_review", {"assessment": "still cut", "findings": [{"synthesis": "y"}]}, "tu-2",
    )], out_tokens=4096)
    calls, updates, _ = _run_with_responses(monkeypatch, [cut1, cut2])

    assert len(calls) == 2  # exactly one retry, never a loop
    done = next(u for u in updates if u.get("status") == "complete")
    assert done["token_usage"]["truncated"] is True
    assert done["assessment"] == "still cut"
    assert done["findings"] and done["proposals"] == []
    assert strategist.TRUNCATION_QUESTION in done["questions"]


def test_run_retries_when_truncation_dropped_the_tool_block(monkeypatch):
    """A cut-off turn can arrive with no tool_use block at all — the retry is a
    plain text turn, and the run still lands the full emit."""
    cut = _resp("max_tokens", [], out_tokens=4096)
    full = _resp("tool_use", [_Block(
        "emit_strategy_review", {"assessment": "full", "proposals": [_proposal()]}, "tu-2",
    )])
    calls, updates, _ = _run_with_responses(monkeypatch, [cut, full])

    assert len(calls) == 2
    assert isinstance(calls[1]["messages"][-1]["content"], str)
    assert calls[1]["messages"][-2]["role"] == "assistant"  # never an empty turn
    done = next(u for u in updates if u.get("status") == "complete")
    assert done["assessment"] == "full" and len(done["proposals"]) == 1


def test_run_untruncated_emit_is_unchanged(monkeypatch):
    full = _resp("tool_use", [_Block(
        "emit_strategy_review", {"assessment": "full", "proposals": [_proposal()]}, "tu-1",
    )])
    calls, updates, _ = _run_with_responses(monkeypatch, [full])

    assert len(calls) == 1
    assert calls[0]["max_tokens"] >= 16_000
    done = next(u for u in updates if u.get("status") == "complete")
    assert "truncated" not in done["token_usage"]
    assert strategist.TRUNCATION_QUESTION not in done["questions"]


# ---------------------------------------------------------------------------
# goal_recovery trigger (PRD PR 2)
# ---------------------------------------------------------------------------
def test_goal_recovery_is_a_valid_trigger_and_has_root_cause_field():
    assert "goal_recovery" in strategist.VALID_TRIGGERS
    props = strategist._EMIT_TOOL["input_schema"]["properties"]
    assert "root_cause" in props and props["root_cause"]["type"] == "string"


def test_sanitize_carries_root_cause_only_when_present():
    body = strategist.sanitize_review({"assessment": "a", "root_cause": "  Metro +68 pins  "}, frozen=False)
    assert body["root_cause"] == "Metro +68 pins"
    body = strategist.sanitize_review({"assessment": "a"}, frozen=False)
    assert "root_cause" not in body
    body = strategist.sanitize_review({"assessment": "a", "root_cause": 42}, frozen=False)
    assert "root_cause" not in body


def test_run_prompt_recovery_orientation_and_block():
    prompt = strategist.build_run_prompt(
        "{}", "", "", trigger="goal_recovery", frozen=False, max_drilldowns=4, max_paid=1,
        escalation_context={"kind": "goal_chronic", "goals": [{"goal_id": "g1"}]},
        recovery_block="CHRONIC-GOAL RECOVERY CONTEXT\n- goal x",
    )
    assert "TRIGGER: goal_recovery — CHRONIC-GOAL RECOVERY PLAN" in prompt
    assert "You MUST emit proposals" in prompt and "You MUST set root_cause" in prompt
    assert "CHRONIC-GOAL RECOVERY CONTEXT" in prompt
    # the raw escalation JSON is NOT duplicated for a recovery run
    assert "ESCALATION EVENT" not in prompt


def test_system_prompt_empty_proposals_rule_points_at_open_proposals():
    assert "EMPTY PROPOSALS ARE VALID ONLY" in strategist._SYSTEM
    assert "open_proposals" in strategist._SYSTEM
    assert "emit no proposals" not in strategist._SYSTEM


def test_run_goal_recovery_tiers_stores_budget_and_notifies_once(monkeypatch):
    """A goal_recovery run: proposals get tiers, `budget` rides the persisted
    row, and the finished run sends ONE goal_chronic (no strategy_review note)."""
    from services import goal_recovery

    monkeypatch.setattr(
        goal_recovery, "load_recovery_context",
        lambda cid, ctx, digest: {
            "goals": [{"goal_id": "g1", "escalation_id": "e1", "label": "Maps", "weeks_behind": 10,
                       "status": "behind", "current_value": 6.2, "target_value": 35.0}],
            "prior_proposals": [], "envelope": {"deployable": 340.0},
            "ceilings": goal_recovery.tier_ceilings(340.0, [0.25]), "tiers": [0.25],
        },
    )
    monkeypatch.setattr(goal_recovery, "supersede_prior_recovery", lambda *a, **k: 0)
    monkeypatch.setattr(goal_recovery, "stamp_escalations", lambda goals, now: 1)

    full = _resp("tool_use", [_Block(
        "emit_strategy_review",
        {"assessment": "full", "root_cause": "Metro built suburb pages north",
         "proposals": [_proposal(costed_items=[{"task_type": "gbp_sniper", "quantity": 1}]),
                       _proposal(title="Big link round", costed_items=[{"task_type": "gbp_sniper", "quantity": 40}])]},
        "tu-1",
    )])
    calls, updates, notes = _run_with_responses(monkeypatch, [full], trigger="goal_recovery")

    assert "CHRONIC-GOAL RECOVERY PLAN" in calls[0]["messages"][0]["content"]
    done = next(u for u in updates if u.get("status") == "complete")
    assert done["budget"]["root_cause"] == "Metro built suburb pages north"
    assert done["budget"]["envelope"] == {"deployable": 340.0}
    tiers = [p["tier"] for p in done["proposals"]]
    assert tiers[0] == "within_budget" and tiers[1] in ("plus_25", "over")
    assert len(notes) == 1
    assert notes[0]["kind"] == "goal_chronic" and notes[0]["severity"] == "critical"
    assert "Root cause: Metro built suburb pages north" in notes[0]["summary"]
    assert notes[0]["payload"]["link"] == "clients/c-1/action-plan"
