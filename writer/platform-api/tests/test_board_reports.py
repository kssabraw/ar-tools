"""Tests for the department-head board reports (services/board_reports/).

Pure helpers only — RAG/delta/render, the three assemblers' deterministic
verdict + section logic. No DB, no LLM (attach_narrative is not exercised).
"""

from __future__ import annotations

from datetime import date

from services.board_reports import client_board, common, director_board, pace_board

MON = date(2026, 9, 14)  # a Monday


# ---------------------------------------------------------------------------
# common
# ---------------------------------------------------------------------------
def test_worst_rag():
    assert common.worst_rag(["green", "green"]) == "green"
    assert common.worst_rag(["green", "yellow"]) == "yellow"
    assert common.worst_rag(["green", "yellow", "red"]) == "red"
    assert common.worst_rag([]) == "green"


def test_pct_delta():
    assert common.pct_delta(12, 10) == "+2 (+20%)"
    assert common.pct_delta(8, 10) == "−2 (−20%)"
    assert common.pct_delta(10, 10) == "flat"
    assert common.pct_delta(5, 0) == "+5"        # no baseline → no percent
    assert common.pct_delta(None, 10) is None
    assert common.pct_delta(10, None) is None


def test_week_dedupe_key_stable():
    assert common.week_dedupe_key("PACE", MON) == common.week_dedupe_key("PACE", date(2026, 9, 18))
    assert common.week_dedupe_key("PACE", MON) != common.week_dedupe_key("DORA", MON)


def test_render_report_sections_and_none_asks():
    report = {
        "title": "T", "verdict": "all good", "rag": "green", "as_of": "2026-09-14",
        "scorecard": [{"label": "Completed", "value": "7", "delta": "+2 (+40%)"}],
        "wins": ["shipped a lot"], "risks": [], "asks": [], "outlook": "steady",
    }
    out = common.render_report(report)
    assert "🟢 all good" in out
    assert "*Scorecard*" in out and "Completed: *7* (+2 (+40%))" in out
    assert "*Wins*" in out
    assert "*Risks & actions*" not in out           # empty risks → section omitted
    assert "None this week." in out                  # empty asks → explicit line
    assert "*Outlook*\nsteady" in out


def test_render_report_rows_and_narrative_lead():
    report = {
        "title": "T", "verdict": "v", "rag": "red", "as_of": "2026-09-14",
        "narrative": "This is the memo.",
        "scorecard": [], "rows": {"title": "Clients", "items": [
            {"rag": "red", "name": "Acme", "line": "frozen"},
        ]},
        "risks": [{"issue": "Acme frozen", "severity": "critical", "action": "escalate", "owner": "Kyle"}],
        "asks": ["decide budget"], "wins": [],
    }
    out = common.render_report(report)
    assert out.index("This is the memo.") < out.index("*Clients*")  # memo leads
    assert "🔴 *Acme* — frozen" in out
    assert "[critical] Acme frozen → escalate (Kyle)" in out


# ---------------------------------------------------------------------------
# PACE
# ---------------------------------------------------------------------------
def test_pace_verdict_for():
    assert pace_board.verdict_for(overloaded=1, behind_pace=0, overdue=0, stuck=0,
                                  unassigned=0, unacted=0)[0] == "red"
    assert pace_board.verdict_for(overloaded=0, behind_pace=2, overdue=0, stuck=0,
                                  unassigned=0, unacted=0)[0] == "red"
    assert pace_board.verdict_for(overloaded=0, behind_pace=0, overdue=3, stuck=0,
                                  unassigned=0, unacted=0)[0] == "yellow"
    assert pace_board.verdict_for(overloaded=0, behind_pace=0, overdue=0, stuck=0,
                                  unassigned=0, unacted=0)[0] == "green"


def test_pace_build_report():
    rep = {
        "completed_count": 12, "overdue": 6, "stuck": 1, "unassigned": 0,
        "unacted": 0, "behind_pace": 1,
        "throughput_by_person": {"Ivy": 7, "Sam": 5},
        "throughput_by_category": {"Content": 8},
    }
    workload = {"members": [
        {"name": "Ivy", "weekly_hours": 30, "open_hours": 40, "overloaded": True, "utilization_pct": 120},
        {"name": "Sam", "weekly_hours": 30, "open_hours": 10, "overloaded": False, "utilization_pct": 40},
    ]}
    r = pace_board.build_report(MON, rep=rep, prev_completed=8, workload=workload)
    assert r["rag"] == "red"                      # Ivy over capacity + a behind-pace client
    labels = {s["label"]: s for s in r["scorecard"]}
    assert labels["Completed (7d)"]["value"] == "12"
    assert labels["Completed (7d)"]["delta"] == "+4 (+50%)"
    assert labels["Team utilization (logged)"]["value"] == "80%"   # (120+40)/2
    assert labels["Over capacity"]["value"] == "1"
    assert any("over capacity" in risk["issue"] for risk in r["risks"])
    assert any("Ivy" in a for a in r["asks"])     # capacity ask names the over-capacity person
    assert r["outlook"] and "capacity" in r["outlook"]


def test_pace_utilization_falls_back_to_estimate_label():
    rep = {"completed_count": 3, "overdue": 0, "stuck": 0, "unassigned": 0,
           "unacted": 0, "behind_pace": 0, "throughput_by_person": {}, "throughput_by_category": {}}
    workload = {"members": [{"name": "Ivy", "weekly_hours": 30, "open_hours": 10, "overloaded": False}]}
    r = pace_board.build_report(MON, rep=rep, prev_completed=3, workload=workload)
    assert r["rag"] == "green"
    labels = {s["label"]: s for s in r["scorecard"]}
    assert "Team utilization (estimate)" in labels          # no logged hours → estimate basis
    assert labels["Team utilization (estimate)"]["value"] == "n/a"


# ---------------------------------------------------------------------------
# DORA
# ---------------------------------------------------------------------------
def test_dora_reliability():
    pace_audit = {"decisions": {"approved": 8, "approved_with_modifications": 1,
                                "denied": 1, "deferred": 0, "cancelled": 0, "reverted": 2}}
    sermastr_audit = {"decisions": {"approved": 6, "dismissed": 2, "worked": 3,
                                    "partial": 1, "no_effect": 2}}
    qa = {"verdict_mix": {"pass": 7, "advisory": 1, "revisions": 2}, "reviews_considered": 10}
    rel = director_board.reliability(pace_audit, sermastr_audit, qa)
    assert rel["pace_approved_pct"] == 90          # (8+1)/10
    assert rel["pace_reverted"] == 2
    assert rel["sermastr_approved_pct"] == 75       # 6/8
    assert rel["sermastr_worked_pct"] == 50         # 3/6
    assert rel["qa_pass_pct"] == 80                 # (7+1)/10


def test_dora_reliability_empty_is_none():
    rel = director_board.reliability(None, None, None)
    assert rel["pace_approved_pct"] is None
    assert rel["qa_pass_pct"] is None


def test_dora_build_report_red_on_degraded_seam():
    model = {
        "flow": {"flags": [
            {"seam": "content_shipped_degraded", "client_id": "c1"},
            {"seam": "qa_idle", "client_id": None},
        ]},
        "autonomy": {"executed": 2, "proposed": 6, "escalated": 0},
        "pace_audit": {"decisions": {"approved": 9, "approved_with_modifications": 0,
                                     "denied": 1, "reverted": 0}},
        "sermastr_audit": {"decisions": {"approved": 4, "dismissed": 1, "worked": 2,
                                         "partial": 0, "no_effect": 1}},
        "qa": {"verdict_mix": {"pass": 5}, "reviews_considered": 5},
        "interventions": {"by_verdict": {"worked": 2, "partial": 0, "no_effect": 1}},
        "assignment": {"open_holds": [{"name": "t1", "client_id": "c1"}]},
    }
    r = director_board.build_report(MON, model=model, names={"c1": "Acme"})
    assert r["rag"] == "red"                         # content_shipped_degraded is a red seam
    assert any("content shipped off-brand" in risk["issue"] for risk in r["risks"])
    assert any("Acme" in risk["issue"] for risk in r["risks"])
    # autonomy proposed(6) >> executed(2) → a governance ask
    assert any("autonomy" in a.lower() for a in r["asks"])
    assert any("capacity hold" in a for a in r["asks"])


def test_dora_build_report_green_when_clean():
    model = {"flow": {"flags": []}, "autonomy": {"executed": 3, "proposed": 0, "escalated": 0}}
    r = director_board.build_report(MON, model=model, names={})
    assert r["rag"] == "green"
    assert any("Zero cross-agent" in w for w in r["wins"])
    assert r["asks"] == []


# ---------------------------------------------------------------------------
# Client Health (SerMaStr)
# ---------------------------------------------------------------------------
def test_client_rag():
    assert client_board.client_rag({"frozen": True}) == "red"
    assert client_board.client_rag({"goals_overdue": 1}) == "red"
    assert client_board.client_rag({"at_risk": 2}) == "red"
    assert client_board.client_rag({"goals_behind": 1}) == "yellow"
    assert client_board.client_rag({"alerts": 3}) == "yellow"
    assert client_board.client_rag({"dropping": 2, "climbing": 1}) == "yellow"
    assert client_board.client_rag({"dropping": 1, "climbing": 3}) == "green"
    assert client_board.client_rag({}) == "green"


def test_client_line_only_includes_present_parts():
    line = client_board.client_line({
        "goals_total": 3, "goals_ok": 2, "page_one": 5, "avg_position": 8.4,
        "maps_pct": 42.0, "ai_pct": 60, "alerts": 1, "frozen": True,
    })
    assert "goals 2/3 on track" in line
    assert "organic: 5 on p1, avg #8" in line
    assert "maps 42% pack" in line and "AI 60%" in line
    assert "1 alert" in line and "❄️ FROZEN" in line
    assert client_board.client_line({}) == "no data yet"


def test_client_build_report_portfolio():
    rows = [
        {"name": "Acme", "frozen": True, "goals_total": 2, "goals_ok": 0, "goals_overdue": 1,
         "page_one": 1, "at_risk": 0, "striking": 0, "alerts": 2, "climbing": 0, "dropping": 1},
        {"name": "Beta", "goals_total": 3, "goals_ok": 3, "page_one": 9, "avg_position": 6.2,
         "at_risk": 0, "striking": 4, "alerts": 0, "climbing": 3, "dropping": 0,
         "top_gainer": {"keyword": "roof repair", "delta": 5.0, "position": 3}},
        {"name": "Gamma", "goals_total": 1, "goals_ok": 0, "goals_behind": 1, "page_one": 2,
         "at_risk": 0, "striking": 1, "alerts": 0, "climbing": 1, "dropping": 0},
    ]
    r = client_board.build_report(MON, rows)
    assert r["rag"] == "red"                          # Acme frozen
    assert "1 of 3 clients on track" in r["verdict"]  # only Beta green
    labels = {s["label"]: s["value"] for s in r["scorecard"]}
    assert labels["Clients"] == "1 🟢 / 1 🟡 / 1 🔴"
    assert labels["Goals on track"] == "3/6"
    assert labels["Frozen"] == "1"
    assert labels["Page-1 keywords (portfolio)"] == "12"
    assert labels["Quick wins (striking distance)"] == "5"
    # rows sorted worst-first
    assert [it["name"] for it in r["rows"]["items"]] == ["Acme", "Gamma", "Beta"]
    # biggest climber surfaced as a win
    assert any("roof repair" in w for w in r["wins"])
    # red account named in risks + asks
    assert any("Acme" in risk["issue"] for risk in r["risks"])
    assert any("Acme" in a for a in r["asks"])
    assert r["outlook"] and "striking distance" in r["outlook"]


def test_client_build_report_all_green():
    rows = [{"name": "Beta", "goals_total": 1, "goals_ok": 1, "page_one": 9,
             "at_risk": 0, "striking": 0, "alerts": 0, "climbing": 1, "dropping": 0}]
    r = client_board.build_report(MON, rows)
    assert r["rag"] == "green"
    assert any("Every client green" in w for w in r["wins"])
    assert r["asks"] == []


# ---------------------------------------------------------------------------
# HTML render (PDF copy) + PDF publish gate
# ---------------------------------------------------------------------------
def test_render_html_is_a_full_doc_with_sections_and_escaping():
    report = {
        "title": "PACE board report <b>", "verdict": "all good", "rag": "green",
        "as_of": "2026-09-14",
        "scorecard": [{"label": "Completed", "value": "7", "delta": "+2 (+40%)"}],
        "rows": {"title": "Clients", "items": [{"rag": "red", "name": "Acme & Co", "line": "frozen"}]},
        "wins": ["shipped a lot"],
        "risks": [{"issue": "Acme frozen", "severity": "critical", "action": "escalate"}],
        "asks": [], "outlook": "steady",
    }
    html = common.render_html(report)
    assert html.startswith("<!doctype html>") and "</html>" in html
    assert "PACE board report &lt;b&gt;" in html      # title escaped, no raw tag injected
    assert "Acme &amp; Co" in html
    assert "Scorecard" in html and "Completed" in html
    assert "Risks &amp; actions" in html and "[critical]" in html
    assert "None this week." in html                   # empty asks
    assert "Outlook" in html and "steady" in html


def test_emit_report_pdf_only_by_default(monkeypatch):
    from services import notifications

    calls = {"emit": 0, "pdf": 0}
    monkeypatch.setattr(notifications, "emit", lambda **kw: calls.__setitem__("emit", calls["emit"] + 1))
    monkeypatch.setattr(common, "maybe_publish_pdf",
                        lambda report: calls.__setitem__("pdf", calls["pdf"] + 1) or {"published": True})
    report = {"agent": "PACE", "title": "T", "verdict": "v", "rag": "green"}

    # Slack off (the default per the 2026-09-14 ruling) → PDF only, no notification.
    monkeypatch.setattr(common.settings, "board_reports_slack_enabled", False)
    r = common.emit_report(report, kind="pace_board_report", today=MON, link="/x")
    assert calls == {"emit": 0, "pdf": 1}
    assert r["slack"] is False and r["emitted"] is False and r["pdf"]["published"] is True

    # Slack on → also post the notification.
    monkeypatch.setattr(common.settings, "board_reports_slack_enabled", True)
    common.emit_report(report, kind="pace_board_report", today=MON, link="/x")
    assert calls == {"emit": 1, "pdf": 2}


def test_run_weekly_force_bypasses_disabled(monkeypatch):
    from services import board_reports as br
    from services.board_reports import client_board, director_board, pace_board

    monkeypatch.setattr(br.settings, "board_reports_enabled", False)
    for m in (pace_board, director_board, client_board):
        monkeypatch.setattr(m, "run", lambda today: {"emitted": True})
    # Scheduled path (force=False) respects the disabled flag.
    assert br.run_weekly_board_reports(MON, force=False)["reason"] == "disabled"
    # On-demand path (force=True) runs all three regardless of the flag.
    out = br.run_weekly_board_reports(MON, force=True)
    assert out["emitted"] is True and set(out["reports"]) == {"pace", "director", "client"}


def test_maybe_publish_pdf_gated_off_when_unconfigured(monkeypatch):
    monkeypatch.setattr(common.settings, "board_reports_drive_folder_id", "")
    monkeypatch.setattr(common.settings, "google_apps_script_url", "https://example/webhook")
    assert common.maybe_publish_pdf({"title": "x"})["reason"] == "not_configured"
    # Folder set but no webhook → still gated (no phantom publish attempt).
    monkeypatch.setattr(common.settings, "board_reports_drive_folder_id", "FOLDER")
    monkeypatch.setattr(common.settings, "google_apps_script_url", "")
    assert common.maybe_publish_pdf({"title": "x"})["reason"] == "not_configured"
