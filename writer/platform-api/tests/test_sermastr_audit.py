"""Tests for the SerMaStr action log (services/sermastr_audit.py).

Pure helpers (proposal_kind routing, proposal_row projection, decision-rate +
learning rollups, the track-record prompt block, the weekly digest, history
formatting) + the impure ``log_proposals`` / ``record_decision`` /
``run_outcome_sweep`` flow with Supabase mocked — proving idempotent proposal
logging, decision upsert (create-if-missing), outcome enrichment from the reused
interventions verdict, gating, and best-effort (a DB error never surfaces). Plus
a wiring test that the strategist run prompt carries the track-record block iff
it's non-empty.
"""

from __future__ import annotations

import pytest

from services import sermastr_audit


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_proposal_kind_prefers_tactic_type():
    assert sermastr_audit.proposal_kind(
        {"target": {"tactic_type": "link_building"}, "sop_citation": "X §1"}
    ) == "link_building"
    assert sermastr_audit.proposal_kind(
        {"target": {"tactic_type": "reoptimization"}}
    ) == "reoptimization"


def test_proposal_kind_falls_back_to_sop_doc_token():
    # Leading doc token, section marker stripped.
    assert sermastr_audit.proposal_kind(
        {"sop_citation": "Link_Building_Recipe_Engine §4"}
    ) == "Link_Building_Recipe_Engine"
    assert sermastr_audit.proposal_kind(
        {"sop_citation": "On_Page_Criteria_and_Coverage — R4"}
    ) == "On_Page_Criteria_and_Coverage"
    # A non-tactic target doesn't hijack the kind.
    assert sermastr_audit.proposal_kind(
        {"target": {"tactic_type": "nonsense"}, "sop_citation": "Maps_SOP §2"}
    ) == "Maps_SOP"


def test_proposal_kind_defaults_general():
    assert sermastr_audit.proposal_kind({}) == "general"
    assert sermastr_audit.proposal_kind(None) == "general"
    assert sermastr_audit.proposal_kind({"sop_citation": ""}) == "general"


def test_proposal_kind_strips_md_extension():
    # A citation with the ".md" extension collapses to the same learning key as
    # one without it, so a playbook's track record isn't split in two.
    assert sermastr_audit.proposal_kind(
        {"sop_citation": "Link_Building_Recipe_Engine.md §4"}
    ) == "Link_Building_Recipe_Engine"
    assert sermastr_audit.proposal_kind({"sop_citation": "_ORCHESTRATOR.md"}) == "_ORCHESTRATOR"
    # Case-insensitive on the extension; a non-.md token is untouched.
    assert sermastr_audit.proposal_kind({"sop_citation": "Rank_Drop_Mitigation_SOP_Maps.MD"}) \
        == "Rank_Drop_Mitigation_SOP_Maps"
    assert sermastr_audit.proposal_kind({"sop_citation": "AIO_AEO_SOP"}) == "AIO_AEO_SOP"


def test_proposal_row_projection():
    row = sermastr_audit.proposal_row(
        "rev1", 2, "c1", "Acme", "scheduled",
        {"title": "Build 3 links", "action": "run a link round",
         "sop_citation": "Link_Building_Recipe_Engine §4", "rationale": "RD gap",
         "requires": "approval", "est_cost_usd": 405,
         "target": {"tactic_type": "link_building", "keyword": "roof repair"}},
    )
    assert row["source_ref"] == "strategy_proposal:rev1:2"
    assert row["review_id"] == "rev1" and row["proposal_idx"] == 2
    assert row["client_id"] == "c1" and row["client_name"] == "Acme"
    assert row["trigger"] == "scheduled"
    assert row["proposal_kind"] == "link_building"
    assert row["title"] == "Build 3 links" and row["requires"] == "approval"
    assert row["est_cost_usd"] == 405
    assert row["target"]["keyword"] == "roof repair"
    # A bad requires value is clamped to 'approval'.
    assert sermastr_audit.proposal_row("r", 0, None, None, None,
                                       {"requires": "weird"})["requires"] == "approval"


def test_source_ref_matches_interventions_key():
    # Must be byte-identical to interventions.source_ref_for_proposal so the
    # outcome sweep joins by it.
    from services import interventions

    assert sermastr_audit.source_ref("rev9", 3) == interventions.source_ref_for_proposal("rev9", 3)


def test_decision_stats_rollup():
    rows = [
        {"proposal_kind": "link_building", "decision": "approved", "outcome_verdict": "worked", "decided_by": "u1"},
        {"proposal_kind": "link_building", "decision": "dismissed", "outcome_verdict": None, "decided_by": "u1"},
        {"proposal_kind": "content", "decision": None, "outcome_verdict": None, "decided_by": None},
        {"proposal_kind": "content", "decision": "approved", "outcome_verdict": "no_effect", "decided_by": "u2"},
    ]
    stats = sermastr_audit.decision_stats(rows)
    ov = stats["overall"]
    assert ov["total"] == 4 and ov["approved"] == 2 and ov["dismissed"] == 1 and ov["pending"] == 1
    assert ov["worked"] == 1 and ov["no_effect"] == 1
    assert stats["by_kind"]["link_building"]["approved"] == 1
    assert stats["by_kind"]["link_building"]["dismissed"] == 1
    # Pending rows carry no actor bucket.
    assert set(stats["by_actor"]) == {"u1", "u2"}


def test_learning_signals_rates():
    rows = [
        {"proposal_kind": "link_building", "client_id": "c1", "decision": "dismissed", "outcome_verdict": None},
        {"proposal_kind": "link_building", "client_id": "c1", "decision": "dismissed", "outcome_verdict": None},
        {"proposal_kind": "link_building", "client_id": "c1", "decision": "approved", "outcome_verdict": "no_effect"},
        {"proposal_kind": "content", "client_id": "c1", "decision": "approved", "outcome_verdict": "worked"},
    ]
    sig = sermastr_audit.learning_signals(rows)
    lb = sig["by_kind"]["link_building"]
    assert lb["decided"] == 3 and lb["dismiss_rate"] == round(2 / 3, 3)
    assert lb["graded"] == 1 and lb["ineffective_rate"] == 1.0
    content = sig["by_client_kind"]["c1::content"]
    assert content["approved"] == 1 and content["worked"] == 1 and content["dismiss_rate"] == 0.0


def test_format_history():
    text = sermastr_audit.format_history([
        {"created_at": "2026-09-01T10:00:00", "client_name": "Acme",
         "proposal_kind": "link_building", "decision": "approved",
         "title": "Build 3 links", "outcome_verdict": "worked"},
        {"created_at": "2026-09-01T11:00:00", "client_name": "Beta",
         "proposal_kind": "content", "decision": None, "requires": "senior",
         "title": "Rewrite hub"},
    ])
    assert "Acme · link_building · approved: Build 3 links [worked]" in text
    assert "senior-required" in text
    assert sermastr_audit.format_history([]).startswith("No SerMaStr proposals")


# ---------------------------------------------------------------------------
# Track-record prompt block (pure, gated by min-samples)
# ---------------------------------------------------------------------------
def test_track_record_block_empty_signals():
    assert sermastr_audit.build_track_record_block({}, "c1") == ""
    assert sermastr_audit.build_track_record_block({"by_kind": {}, "by_client_kind": {}}, "c1") == ""


def test_track_record_block_silent_under_min_samples(monkeypatch):
    monkeypatch.setattr(sermastr_audit.settings, "sermastr_audit_learning_min_samples", 3)
    monkeypatch.setattr(sermastr_audit.settings, "sermastr_audit_learning_dismiss_threshold", 0.6)
    sig = sermastr_audit.learning_signals([
        {"proposal_kind": "link_building", "client_id": "c1", "decision": "dismissed", "outcome_verdict": None},
    ])  # only 1 decided — below min
    assert sermastr_audit.build_track_record_block(sig, "c1") == ""


def test_track_record_block_flags_avoid_and_favour(monkeypatch):
    monkeypatch.setattr(sermastr_audit.settings, "sermastr_audit_learning_min_samples", 3)
    monkeypatch.setattr(sermastr_audit.settings, "sermastr_audit_learning_dismiss_threshold", 0.6)
    rows = (
        [{"proposal_kind": "link_building", "client_id": "c1", "decision": "dismissed", "outcome_verdict": None}] * 3
        + [{"proposal_kind": "content", "client_id": "c1", "decision": "approved", "outcome_verdict": "worked"}] * 3
    )
    block = sermastr_audit.build_track_record_block(sermastr_audit.learning_signals(rows), "c1")
    assert "YOUR TRACK RECORD" in block
    assert "Avoid" in block and "link_building" in block
    assert "Favour" in block and "content" in block


def test_track_record_block_falls_back_to_agency_when_client_thin(monkeypatch):
    monkeypatch.setattr(sermastr_audit.settings, "sermastr_audit_learning_min_samples", 3)
    monkeypatch.setattr(sermastr_audit.settings, "sermastr_audit_learning_dismiss_threshold", 0.6)
    # 3 agency-wide dismissals of link_building, none for THIS client → uses agency.
    rows = [{"proposal_kind": "link_building", "client_id": "other", "decision": "dismissed", "outcome_verdict": None}] * 3
    block = sermastr_audit.build_track_record_block(sermastr_audit.learning_signals(rows), "c1")
    assert "agency-wide" in block and "link_building" in block


# ---------------------------------------------------------------------------
# Weekly digest (pure)
# ---------------------------------------------------------------------------
def test_build_learning_digest_empty():
    assert sermastr_audit.build_learning_digest([]) == ""


def test_build_learning_digest_content():
    rows = (
        [{"proposal_kind": "link_building", "client_id": "c1", "decision": "dismissed", "outcome_verdict": None}] * 2
        + [{"proposal_kind": "content", "client_id": "c1", "decision": "approved", "outcome_verdict": "no_effect"}] * 2
    )
    body = sermastr_audit.build_learning_digest(rows)
    assert "SerMaStr learning digest" in body
    assert "Most-dismissed" in body and "link_building" in body
    assert "Not moving the metric" in body and "content" in body


# ---------------------------------------------------------------------------
# Impure I/O — fakes
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, data=None, count=None):
        self.data = data if data is not None else []
        self.count = count


class _FakeQuery:
    def __init__(self, table):
        self.t = table

    def select(self, *a, **k):
        self.t.count = k.get("count") and len(self.t.select_data)
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    @property
    def not_(self):
        return self

    def upsert(self, rows, **k):
        self.t.upserts.append((rows, k))
        return self

    def insert(self, row):
        self.t.inserts.append(row)
        return self

    def update(self, patch):
        self.t.updates.append(patch)
        return self

    def execute(self):
        return _Resp(self.t.select_data, self.t.count)


class _FakeTable:
    def __init__(self, select_data=None):
        self.select_data = select_data or []
        self.upserts: list = []
        self.inserts: list = []
        self.updates: list = []
        self.count = None

    def __getattr__(self, name):  # every query verb dispatches through a fresh query
        return getattr(_FakeQuery(self), name)


class _FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return self.tables.setdefault(name, _FakeTable())


def _mk(monkeypatch, tables, enabled=True):
    monkeypatch.setattr(sermastr_audit.settings, "sermastr_audit_enabled", enabled)
    monkeypatch.setattr(sermastr_audit, "get_supabase", lambda: _FakeSupabase(tables))


def test_log_proposals_idempotent_upsert(monkeypatch):
    tables = {"sermastr_action_log": _FakeTable()}
    _mk(monkeypatch, tables)
    sermastr_audit.log_proposals(
        "rev1", "c1", "Acme", "scheduled",
        [{"title": "A", "action": "a", "target": {"tactic_type": "link_building"}},
         {"title": "B", "action": "b", "sop_citation": "Maps_SOP §1"}],
    )
    (rows, kwargs), = tables["sermastr_action_log"].upserts
    assert len(rows) == 2
    assert kwargs["on_conflict"] == "source_ref" and kwargs["ignore_duplicates"] is True
    assert [r["source_ref"] for r in rows] == ["strategy_proposal:rev1:0", "strategy_proposal:rev1:1"]
    assert rows[0]["proposal_kind"] == "link_building" and rows[1]["proposal_kind"] == "Maps_SOP"


def test_log_proposals_gated_off(monkeypatch):
    tables = {"sermastr_action_log": _FakeTable()}
    _mk(monkeypatch, tables, enabled=False)
    sermastr_audit.log_proposals("rev1", "c1", "Acme", "scheduled", [{"title": "A", "action": "a"}])
    assert tables["sermastr_action_log"].upserts == []


def test_log_proposals_best_effort(monkeypatch):
    monkeypatch.setattr(sermastr_audit.settings, "sermastr_audit_enabled", True)

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(sermastr_audit, "get_supabase", _boom)
    # Must not raise.
    sermastr_audit.log_proposals("rev1", "c1", "Acme", "scheduled", [{"title": "A", "action": "a"}])


def test_record_decision_upserts_with_decision_fields(monkeypatch):
    tables = {"sermastr_action_log": _FakeTable()}
    _mk(monkeypatch, tables)
    sermastr_audit.record_decision(
        review_id="rev1", idx=0, proposal={"title": "A", "action": "a",
                                           "target": {"tactic_type": "link_building"}},
        client_id="c1", client_name="Acme", trigger="scheduled", decision="approved",
        actor_profile_id="u1", actor_role="admin", actor_source="web",
    )
    (row, kwargs), = tables["sermastr_action_log"].upserts
    assert kwargs["on_conflict"] == "source_ref"
    # Create-if-missing carries the full proposal projection AND the decision.
    assert row["source_ref"] == "strategy_proposal:rev1:0"
    assert row["decision"] == "approved" and row["decided_by"] == "u1"
    assert row["actor_role"] == "admin" and row["decided_at"]
    assert row["proposal_kind"] == "link_building" and row["client_name"] == "Acme"
    # It does NOT write an outcome verdict (a later sweep owns that column).
    assert "outcome_verdict" not in row


def test_record_decision_strips_none_to_not_clobber_snapshot(monkeypatch):
    # A re-decision after the client was deleted arrives with client_name=None
    # (review.client_id → null). The merge must NOT null the pending row's
    # snapshotted client_name, so None-valued keys are dropped from the upsert.
    tables = {"sermastr_action_log": _FakeTable()}
    _mk(monkeypatch, tables)
    sermastr_audit.record_decision(
        review_id="rev1", idx=0, proposal={"title": "A", "action": "a"},
        client_id=None, client_name=None, trigger=None, decision="dismissed",
        actor_profile_id=None, actor_role=None,
    )
    (row, _), = tables["sermastr_action_log"].upserts
    assert "client_name" not in row and "client_id" not in row and "trigger" not in row
    assert "decided_by" not in row and "actor_role" not in row  # None actor fields dropped
    # But the decision itself and the identity key are always written.
    assert row["decision"] == "dismissed" and row["source_ref"] == "strategy_proposal:rev1:0"
    assert row["decided_at"] and row["actor_source"] == "web"


def test_record_decision_ignores_bad_decision(monkeypatch):
    tables = {"sermastr_action_log": _FakeTable()}
    _mk(monkeypatch, tables)
    sermastr_audit.record_decision(review_id="rev1", idx=0, proposal={"title": "A"},
                                   decision="maybe")
    assert tables["sermastr_action_log"].upserts == []


def test_run_outcome_sweep_stamps_verdict(monkeypatch):
    tables = {
        "sermastr_action_log": _FakeTable([
            {"id": "row1", "source_ref": "strategy_proposal:rev1:0"},
            {"id": "row2", "source_ref": "strategy_proposal:rev1:1"},
        ]),
        "interventions": _FakeTable([
            {"id": "iv1", "source_ref": "strategy_proposal:rev1:0",
             "verdict": "worked", "evaluated_at": "2026-09-01T00:00:00"},
            # rev1:1 has no committed verdict → not stamped.
        ]),
    }
    _mk(monkeypatch, tables)
    result = sermastr_audit.run_outcome_sweep()
    assert result["checked"] == 2 and result["stamped"] == 1
    patch, = tables["sermastr_action_log"].updates
    assert patch["outcome_verdict"] == "worked" and patch["intervention_id"] == "iv1"


def test_run_outcome_sweep_gated_off(monkeypatch):
    _mk(monkeypatch, {}, enabled=False)
    assert sermastr_audit.run_outcome_sweep()["reason"] == "disabled"


def test_maybe_emit_weekly_learning_not_due(monkeypatch):
    monkeypatch.setattr(sermastr_audit.settings, "strategist_enabled", True)
    monkeypatch.setattr(sermastr_audit.settings, "sermastr_audit_enabled", True)
    monkeypatch.setattr(sermastr_audit.settings, "sermastr_audit_digest_weekday", None)
    assert sermastr_audit.maybe_emit_weekly_learning()["reason"] == "not_due"


def test_maybe_emit_weekly_learning_gated_off(monkeypatch):
    monkeypatch.setattr(sermastr_audit.settings, "strategist_enabled", False)
    assert sermastr_audit.maybe_emit_weekly_learning()["reason"] == "disabled"


# ---------------------------------------------------------------------------
# Prompt wiring — build_run_prompt carries the block iff non-empty
# ---------------------------------------------------------------------------
def test_build_run_prompt_track_record_in_and_out():
    from services import strategist

    with_block = strategist.build_run_prompt(
        "{}", "", "", trigger="scheduled", frozen=False, max_drilldowns=4, max_paid=1,
        track_record="YOUR TRACK RECORD (weigh): Avoid `link_building`",
    )
    assert "YOUR TRACK RECORD" in with_block
    without = strategist.build_run_prompt(
        "{}", "", "", trigger="scheduled", frozen=False, max_drilldowns=4, max_paid=1,
    )
    assert "YOUR TRACK RECORD" not in without


# ---------------------------------------------------------------------------
# WS1 self-analysis — tactic_performance + report (pure)
# ---------------------------------------------------------------------------
def _row(kind, decision=None, verdict=None, client_id=None, trigger="scheduled"):
    return {"proposal_kind": kind, "decision": decision, "outcome_verdict": verdict,
            "client_id": client_id, "trigger": trigger}


def test_tactic_performance_ranks_measured_above_approval_only():
    rows = (
        # reoptimization: 3 approved + worked → measured, worked_rate 1.0
        [_row("reoptimization", "approved", "worked") for _ in range(3)]
        # link_building: 3 approved, no outcome → approval-only, discounted 0.7
        + [_row("link_building", "approved") for _ in range(3)]
    )
    perf = sermastr_audit.tactic_performance(rows, min_samples=2)
    kinds = [l["kind"] for l in perf["leaders"]]
    assert kinds[:2] == ["reoptimization", "link_building"]
    reopt = next(l for l in perf["leaders"] if l["kind"] == "reoptimization")
    lb = next(l for l in perf["leaders"] if l["kind"] == "link_building")
    assert reopt["signal"] == "measured" and reopt["rank_score"] == 1.0
    assert lb["signal"] == "approval-only" and lb["rank_score"] == 0.7


def test_tactic_performance_thin_excluded_and_underperformers():
    rows = (
        [_row("general", "approved")]  # 1 decided < min 2 → thin, no leader
        + [_row("citations", "approved", "no_effect") for _ in range(2)]  # measured, 0 worked
    )
    perf = sermastr_audit.tactic_performance(rows, min_samples=2)
    assert "general" not in [l["kind"] for l in perf["leaders"]]
    assert "citations" in [u["kind"] for u in perf["underperformers"]]
    assert "citations" not in [l["kind"] for l in perf["leaders"]]  # 0 worked → not a leader


def test_tactic_performance_slices_by_client_type_and_trigger():
    rows = [
        _row("reoptimization", "approved", "worked", client_id="c1", trigger="scheduled"),
        _row("reoptimization", "approved", "worked", client_id="c2", trigger="escalation"),
    ]
    perf = sermastr_audit.tactic_performance(
        rows, client_types={"c1": "local", "c2": "enterprise"}, min_samples=1)
    assert set(perf["by_client_type"]) == {"local", "enterprise"}
    assert set(perf["by_trigger"]) == {"scheduled", "escalation"}
    assert perf["by_client_type"]["local"]["worked_rate"] == 1.0


def test_build_self_analysis_report_leaders_and_empty():
    rows = [_row("reoptimization", "approved", "worked") for _ in range(2)]
    perf = sermastr_audit.tactic_performance(rows, min_samples=2)
    report = sermastr_audit.build_self_analysis_report(perf)
    assert "Leaders" in report and "reoptimization" in report
    # All-thin history → nothing worth saying → "".
    thin = sermastr_audit.tactic_performance([_row("x", "approved")], min_samples=5)
    assert sermastr_audit.build_self_analysis_report(thin) == ""


def test_build_self_analysis_report_folds_in_dismissed():
    rows = ([_row("reoptimization", "approved", "worked") for _ in range(2)]
            + [_row("press_release", "dismissed") for _ in range(2)])
    perf = sermastr_audit.tactic_performance(rows, min_samples=2)
    learn = sermastr_audit.learning_signals(rows)
    report = sermastr_audit.build_self_analysis_report(perf, learn)
    assert "Most-dismissed" in report and "press_release" in report


def test_decision_stats_counts_superseded_separately():
    rows = [
        {"decision": "approved"}, {"decision": "dismissed"},
        {"decision": "superseded"}, {"decision": None},
    ]
    stats = sermastr_audit.decision_stats(rows)["overall"]
    assert stats["approved"] == 1 and stats["dismissed"] == 1
    assert stats["superseded"] == 1 and stats["pending"] == 1 and stats["total"] == 4


def test_learning_rates_ignore_superseded():
    rows = [
        {"decision": "approved", "proposal_kind": "k", "client_id": "c"},
        {"decision": "superseded", "proposal_kind": "k", "client_id": "c"},
        {"decision": "superseded", "proposal_kind": "k", "client_id": "c"},
    ]
    sig = sermastr_audit.learning_signals(rows)
    k = sig["by_kind"]["k"]
    assert k["dismiss_rate"] == 0.0


def test_record_superseded_writes_a_system_decision(monkeypatch):
    from unittest.mock import MagicMock
    from config import settings

    monkeypatch.setattr(settings, "sermastr_audit_enabled", True)
    supabase = MagicMock()
    captured = {}
    chain = supabase.table.return_value
    chain.upsert.side_effect = lambda row, **kw: (captured.update(row), chain)[1]
    monkeypatch.setattr(sermastr_audit, "get_supabase", lambda: supabase)

    sermastr_audit.record_superseded(review_id="r", idx=1, proposal={"title": "t", "action": "a"},
                                     client_id="c", client_name="Acme", trigger="goal_recovery")
    assert captured["decision"] == "superseded"
    assert captured["actor_source"] == "system"
    assert "decided_by" not in captured  # None keys stripped
    assert captured["source_ref"] == "strategy_proposal:r:1"
