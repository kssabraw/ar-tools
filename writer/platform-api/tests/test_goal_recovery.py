"""Unit tests for services.goal_recovery — the pure core of the chronic-goal
recovery run (PRD: docs/modules/sermastr-autonomous-recovery-plans-prd-v1_0.md):
tier parsing/ceilings/assignment, the budget snapshot, the recovery prompt block,
the goal_chronic notification, superseding, and the per-tick cap ordering. The
impure enqueue/after-persist paths are covered with fakes at the bottom."""

from __future__ import annotations

from datetime import date

from services import goal_recovery as gr


def _p(title, cost, **over):
    p = {"title": title, "action": "do it", "rationale": "because", "sop_citation": "SOP §1",
         "est_cost_usd": cost, "cost_basis": "recipe" if cost is not None else "none",
         "status": "proposed", "requires": "approval"}
    p.update(over)
    return p


# ---------------------------------------------------------------------------
# tiers
# ---------------------------------------------------------------------------
def test_parse_tiers_sorts_dedupes_and_falls_back():
    assert gr.parse_tiers("0.50, 0.25,1.00,0.25") == [0.25, 0.5, 1.0]
    assert gr.parse_tiers("") == list(gr.DEFAULT_TIERS)
    assert gr.parse_tiers("nope,-1,0") == list(gr.DEFAULT_TIERS)
    assert gr.parse_tiers([0.1, 0.2]) == [0.1, 0.2]


def test_tier_ceilings_over_deployable_and_no_envelope():
    c = gr.tier_ceilings(340.0, [0.25, 0.5, 1.0])
    assert c == {"within_budget": 340.0, "plus_25": 425.0, "plus_50": 510.0, "plus_100": 680.0}
    none = gr.tier_ceilings(None, [0.25])
    assert none == {"within_budget": None, "plus_25": None}
    assert gr.tier_ceilings(0, [0.25])["within_budget"] is None


def test_assign_tiers_by_running_total_in_priority_order():
    props = [_p("a", 100), _p("b", 200), _p("c", 100), _p("d", 200), _p("e", 500)]
    out, summary = gr.assign_tiers(props, 340.0, [0.25, 0.5, 1.0])
    assert [p["tier"] for p in out] == ["within_budget", "within_budget", "plus_25", "plus_100", "over"]
    assert [p["cumulative_cost_usd"] for p in out] == [100.0, 300.0, 400.0, 600.0, 1100.0]
    assert summary["fundable_count"] == 2
    assert summary["total_cost_usd"] == 1100.0
    assert summary["by_tier"] == {"within_budget": 2, "plus_25": 1, "plus_100": 1, "over": 1}
    # input untouched (pure)
    assert "tier" not in props[0]


def test_assign_tiers_unpriced_rides_the_running_tier_and_no_envelope_is_unbudgeted():
    out, _ = gr.assign_tiers([_p("a", 300), _p("b", None), _p("c", 100)], 340.0, [0.25])
    assert [p["tier"] for p in out] == ["within_budget", "within_budget", "plus_25"]
    out, summary = gr.assign_tiers([_p("a", 300)], None, [0.25])
    assert out[0]["tier"] == "unbudgeted" and summary["fundable_count"] == 0


def test_tier_rank_orders_labels():
    tiers = [0.25, 0.5]
    assert gr.tier_rank("within_budget", tiers) < gr.tier_rank("plus_25", tiers) < gr.tier_rank("plus_50", tiers) < gr.tier_rank("over", tiers)
    assert gr.tier_rank("bogus", tiers) > gr.tier_rank("over", tiers)


# ---------------------------------------------------------------------------
# snapshot + context + prompt block
# ---------------------------------------------------------------------------
def test_budget_snapshot_records_what_the_plan_was_costed_against():
    _, summary = gr.assign_tiers([_p("a", 100)], 340.0, [0.25])
    snap = gr.budget_snapshot({"deployable": 340.0}, summary, "  Metropolitan +68 pins in the north ", [{"goal_id": "g1"}], [0.25])
    assert snap["envelope"] == {"deployable": 340.0}
    assert snap["tiers"]["plus_25"] == 425.0
    assert snap["tier_steps"] == [0.25]
    assert snap["fundable_count"] == 1 and snap["total_cost_usd"] == 100.0
    assert snap["root_cause"] == "Metropolitan +68 pins in the north"
    assert snap["goals"] == [{"goal_id": "g1"}]


def _row_goal():
    row = {"id": "esc-1", "goal_id": "g1", "behind_since": "2026-06-15", "worst_value": 5.7}
    g = {"id": "g1", "goal_type": "maps_pack_presence", "label": "35% local-pack presence",
         "status": "behind", "baseline_value": 19.6, "current_value": 6.2, "effective_target": 35.0}
    return row, g


def test_goals_context_carries_weeks_and_escalation_id():
    ctx = gr.goals_context([_row_goal()], date(2026, 9, 2))
    assert len(ctx) == 1
    g = ctx[0]
    assert g["goal_id"] == "g1" and g["escalation_id"] == "esc-1"
    assert g["weeks_behind"] == 11
    assert g["worst_value"] == 5.7 and g["target_value"] == 35.0 and g["label"].startswith("35%")


def test_recovery_block_names_goals_budget_tiers_and_prior_plan():
    goals = gr.goals_context([_row_goal()], date(2026, 9, 2))
    env = {"retainer_monthly": 1000, "deployable": 340.0, "margin_used": 0.34,
           "reporting_cost": 150.0, "baseline_stack_cost": 135.0, "discretionary": 55.0}
    block = gr.build_recovery_block(
        goals, [{"title": "GBP Sniper", "est_cost_usd": 10, "age_days": 14, "status": "proposed"}],
        env, gr.tier_ceilings(340.0, [0.25, 0.5, 1.0]), [0.25, 0.5, 1.0],
    )
    assert "CHRONIC-GOAL RECOVERY CONTEXT" in block
    assert "35% local-pack presence" in block and "11 week(s)" in block
    assert "deployable $340" in block and "discretionary $55" in block
    assert "+25% ≤ $425" in block and "+100% ≤ $680" in block
    assert "GBP Sniper" in block and "14d old" in block


def test_recovery_block_without_prior_plan_or_goals():
    block = gr.build_recovery_block([], [], None, gr.tier_ceilings(None, [0.25]), [0.25])
    assert "first recovery plan" in block
    assert "none listed" in block
    assert "n/a" in block


# ---------------------------------------------------------------------------
# notification
# ---------------------------------------------------------------------------
def test_recovery_notification_carries_alarm_root_cause_plan_and_link():
    goals = gr.goals_context([_row_goal()], date(2026, 9, 2))
    props = [_p("Publish the 12 suburb pages", 60), _p("GBP Sniper on the north", 10),
             _p("Retainer conversation", None, requires="senior")]
    props, summary = gr.assign_tiers(props, 55.0, [0.25, 0.5, 1.0])
    budget = gr.budget_snapshot({"deployable": 55.0}, summary, "Metropolitan Roof Repairs +68 pins north.", goals, [0.25, 0.5, 1.0])
    note = gr.build_recovery_notification("First Class Roofing", goals, {"id": "r-9", "proposals": props}, budget, "clients/c1/action-plan")
    assert note["title"].startswith("STILL CRITICAL (week 11): First Class Roofing — 35% local-pack presence")
    assert note["severity"] == "critical"
    s = note["summary"]
    assert "behind for 11 weeks — now 6.2 vs target 35" in s
    assert "Root cause: Metropolitan Roof Repairs +68 pins north." in s
    assert "Recovery plan (3 proposals, 0 within budget of $55 deployable" in s
    assert "+25% covers 1" in s and "+50% covers 3" in s
    assert "1. Publish the 12 suburb pages — $60 · +25%" in s
    assert "2. GBP Sniper on the north — $10 · +50%" in s
    assert "3. Retainer conversation — no cost · +50% · Kyle/Ryan only" in s
    assert "Approve a proposal (or a whole tier)" in s
    assert note["payload"]["link"] == "clients/c1/action-plan"
    assert note["payload"]["review_id"] == "r-9"
    assert note["payload"]["goal_ids"] == ["g1"] and note["payload"]["proposal_count"] == 3


def test_recovery_notification_caps_listed_proposals_and_names_the_rest():
    goals = gr.goals_context([_row_goal()], date(2026, 9, 2))
    props, summary = gr.assign_tiers([_p(f"p{i}", 10) for i in range(8)], 340.0, [0.25])
    budget = gr.budget_snapshot({"deployable": 340.0}, summary, "", goals, [0.25])
    note = gr.build_recovery_notification("Acme", goals, {"id": "r", "proposals": props}, budget, "x")
    assert "6. " not in note["summary"] and "… 3 more on the Action Plan card." in note["summary"]
    assert "Root cause" not in note["summary"]


def test_recovery_notification_with_no_proposals_says_so():
    goals = gr.goals_context([_row_goal()], date(2026, 9, 2))
    budget = gr.budget_snapshot(None, {"fundable_count": 0}, "", goals, [0.25])
    note = gr.build_recovery_notification("Acme", goals, {"id": "r", "proposals": []}, budget, "x")
    assert "produced NO proposals" in note["summary"]


def test_recovery_notification_multiple_goals_title():
    row, g = _row_goal()
    g2 = {**g, "id": "g2", "label": "3 keywords in the top 10"}
    goals = gr.goals_context([(row, g), ({**row, "id": "esc-2", "goal_id": "g2", "behind_since": "2026-08-20"}, g2)], date(2026, 9, 2))
    note = gr.build_recovery_notification("Acme", goals, {"id": "r", "proposals": []}, {"root_cause": ""}, "x")
    assert "(+1 more)" in note["title"] and "week 11" in note["title"]


# ---------------------------------------------------------------------------
# supersede + cap ordering + prior proposals
# ---------------------------------------------------------------------------
def test_mark_superseded_only_touches_proposed():
    props = [_p("a", 1), _p("b", 1, status="approved"), _p("c", 1, status="dismissed"), _p("d", 1)]
    out, changed = gr.mark_superseded(props)
    assert changed == [0, 3]
    assert [p["status"] for p in out] == ["superseded", "approved", "dismissed", "superseded"]
    assert props[0]["status"] == "proposed"  # pure


def test_order_for_cap_oldest_behind_first():
    cands = [
        {"client_id": "c-new", "goals": [{"behind_since": "2026-08-20"}]},
        {"client_id": "c-old", "goals": [{"behind_since": "2026-06-01"}, {"behind_since": "2026-08-01"}]},
        {"client_id": "c-mid", "goals": [{"behind_since": "2026-07-10"}]},
        {"client_id": "c-none", "goals": []},
    ]
    selected, deferred = gr.order_for_cap(cands, 2)
    assert [c["client_id"] for c in selected] == ["c-old", "c-mid"]
    assert [c["client_id"] for c in deferred] == ["c-new", "c-none"]
    assert gr.order_for_cap(cands, 0) == ([], sorted(cands, key=lambda c: (gr.oldest_behind(c["goals"]) or "9999-12-31", c["client_id"])))


def test_prior_open_recovery_proposals_filters_by_trigger():
    digest_section = {"items": [
        {"trigger": "goal_recovery", "title": "keep"},
        {"trigger": "scheduled", "title": "weekly"},
    ]}
    assert [p["title"] for p in gr.prior_open_recovery_proposals(digest_section)] == ["keep"]
    assert gr.prior_open_recovery_proposals(None) == []


# ---------------------------------------------------------------------------
# apply_budget + impure paths with fakes
# ---------------------------------------------------------------------------
def test_apply_budget_tiers_proposals_and_snapshots():
    body = {"assessment": "a", "findings": [], "questions": [], "root_cause": "rc",
            "proposals": [_p("x", 300), _p("y", 100)]}
    recovery = {"envelope": {"deployable": 340.0}, "goals": [{"goal_id": "g1"}], "tiers": [0.25]}
    out, budget = gr.apply_budget(body, recovery)
    assert [p["tier"] for p in out["proposals"]] == ["within_budget", "plus_25"]
    assert budget["root_cause"] == "rc" and budget["goals"] == [{"goal_id": "g1"}]
    assert budget["fundable_count"] == 1


def test_gate_open_requires_all_three_flags(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "goal_recovery_enabled", True)
    monkeypatch.setattr(settings, "goal_escalation_enabled", True)
    monkeypatch.setattr(settings, "strategist_enabled", False)
    assert gr.gate_open() is False
    monkeypatch.setattr(settings, "strategist_enabled", True)
    assert gr.gate_open() is True
    monkeypatch.setattr(settings, "goal_recovery_enabled", False)
    assert gr.gate_open() is False


def test_enqueue_recovery_run_statuses(monkeypatch):
    from config import settings
    from services import strategist

    monkeypatch.setattr(settings, "goal_recovery_enabled", True)
    monkeypatch.setattr(settings, "goal_escalation_enabled", True)
    monkeypatch.setattr(settings, "strategist_enabled", False)
    assert gr.enqueue_recovery_run("c1", []) == ("disabled", None)

    monkeypatch.setattr(settings, "strategist_enabled", True)
    monkeypatch.setattr(strategist, "_strategist_excluded", lambda cid: True)
    assert gr.enqueue_recovery_run("c1", []) == ("disabled", None)

    monkeypatch.setattr(strategist, "_strategist_excluded", lambda cid: False)
    captured = {}

    def _enqueue(cid, trigger="on_demand", escalation_context=None, notify=False):
        captured.update({"cid": cid, "trigger": trigger, "ctx": escalation_context})
        return "r-1"

    monkeypatch.setattr(strategist, "enqueue_strategy_review", _enqueue)
    assert gr.enqueue_recovery_run("c1", [{"goal_id": "g1"}]) == ("enqueued", "r-1")
    assert captured["trigger"] == "goal_recovery"
    assert captured["ctx"] == {"kind": "goal_chronic", "goals": [{"goal_id": "g1"}]}

    monkeypatch.setattr(strategist, "enqueue_strategy_review", lambda *a, **k: None)
    assert gr.enqueue_recovery_run("c1", []) == ("in_flight", None)

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(strategist, "enqueue_strategy_review", _boom)
    assert gr.enqueue_recovery_run("c1", []) == ("failed", None)


def test_load_recovery_context_uses_sweep_goals_and_digest_client(monkeypatch):
    digest = {
        "client": {"retainer_monthly": 1000, "is_sab": False},
        "open_proposals": {"items": [{"trigger": "goal_recovery", "title": "prior"}, {"trigger": "scheduled"}]},
    }
    ctx = gr.load_recovery_context("c1", {"goals": [{"goal_id": "g1"}]}, digest)
    assert ctx["goals"] == [{"goal_id": "g1"}]
    assert ctx["prior_proposals"] == [{"trigger": "goal_recovery", "title": "prior"}]
    assert ctx["envelope"]["deployable"] == 340.0
    assert ctx["ceilings"]["within_budget"] == 340.0
    assert ctx["tiers"] == [0.25, 0.5, 1.0]


class _FakeQuery:
    def __init__(self, table, store):
        self.table_name, self.store = table, store
        self._update = None

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def neq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def update(self, patch):
        self.store["updates"].append((self.table_name, patch))
        return self

    def execute(self):
        return type("R", (), {"data": self.store["reads"].get(self.table_name, [])})()


class _FakeSB:
    def __init__(self, store): self.store = store
    def table(self, name): return _FakeQuery(name, self.store)


def test_supersede_prior_recovery_marks_and_logs(monkeypatch):
    from services import sermastr_audit

    store = {"reads": {"strategy_reviews": [
        {"id": "old-1", "proposals": [_p("a", 1), _p("b", 1, status="approved")]},
        {"id": "old-2", "proposals": [_p("c", 1, status="dismissed")]},
    ]}, "updates": []}
    monkeypatch.setattr(gr, "get_supabase", lambda: _FakeSB(store))
    logged = []
    monkeypatch.setattr(sermastr_audit, "record_superseded", lambda **kw: logged.append(kw))

    n = gr.supersede_prior_recovery("c1", "new-1", "Acme")
    assert n == 1
    assert len(store["updates"]) == 1
    tbl, patch = store["updates"][0]
    assert tbl == "strategy_reviews"
    assert [p["status"] for p in patch["proposals"]] == ["superseded", "approved"]
    assert logged and logged[0]["review_id"] == "old-1" and logged[0]["idx"] == 0
    assert logged[0]["trigger"] == "goal_recovery"


def test_stamp_escalations_bumps_count(monkeypatch):
    from datetime import datetime, timezone

    store = {"reads": {"goal_escalations": [{"id": "esc-1", "escalation_count": 2}]}, "updates": []}
    monkeypatch.setattr(gr, "get_supabase", lambda: _FakeSB(store))
    n = gr.stamp_escalations([{"escalation_id": "esc-1"}, {"escalation_id": None}], datetime.now(timezone.utc))
    assert n == 1
    tbl, patch = store["updates"][0]
    assert tbl == "goal_escalations" and patch["escalation_count"] == 3 and "last_escalated_at" in patch


def test_after_persist_emits_one_goal_chronic_even_if_supersede_fails(monkeypatch):
    from services import notifications

    def _boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(gr, "supersede_prior_recovery", _boom)
    monkeypatch.setattr(gr, "stamp_escalations", lambda goals, now: 0)
    emitted = []
    monkeypatch.setattr(notifications, "emit", lambda **kw: emitted.append(kw))
    goals = gr.goals_context([_row_goal()], date(2026, 9, 2))
    props, summary = gr.assign_tiers([_p("a", 10)], 340.0, [0.25])
    budget = gr.budget_snapshot({"deployable": 340.0}, summary, "rc", goals, [0.25])
    gr.after_persist("c1", {"id": "r-1", "proposals": props}, {"goals": goals}, budget, "Acme")
    assert len(emitted) == 1
    e = emitted[0]
    assert e["kind"] == "goal_chronic" and e["severity"] == "critical" and e["client_id"] == "c1"
    assert e["payload"]["link"] == "clients/c1/action-plan"
