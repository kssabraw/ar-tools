"""Pure-helper tests for PAA → SEO Neo Phase 3 (services/paa_campaign.py) — the
single-variable gate, cadence math, the transition log, the next-action
descriptor, and drill seeding. No I/O (per the repo's conventions)."""

from datetime import datetime, timedelta, timezone

from services import paa_campaign as pc


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


# ── the gate (reference §5.3) ─────────────────────────────────────────────────


def test_gate_moved_on_rank_improvement():
    # baseline 8th, current 5th → improved by 3 ≥ MOVE_MIN_POSITIONS (2).
    g = pc.evaluate_gate(8.0, 5.0, drill_level=0)
    assert g["branch"] == "moved"
    assert g["improved"] is True
    assert g["rank_delta"] == 3.0


def test_gate_moved_on_top3_pins_even_if_rank_flat():
    # average rank unchanged, but +2 top-3 pins → movement (more local-pack cover).
    g = pc.evaluate_gate(6.0, 6.0, baseline_top3=1, current_top3=3, drill_level=1)
    assert g["branch"] == "moved"
    assert g["top3_delta"] == 2


def test_gate_no_movement_drills_when_under_cap():
    g = pc.evaluate_gate(6.0, 5.5, drill_level=0, cap=4)  # +0.5 < 2 → no move
    assert g["branch"] == "drill"
    assert g["improved"] is False


def test_gate_halts_at_cap_with_no_movement():
    g = pc.evaluate_gate(6.0, 6.0, drill_level=4, cap=4)
    assert g["branch"] == "halt"
    assert "re-check on-page/entity" in g["reason"]


def test_gate_worse_rank_is_no_movement_not_moved():
    # current worse than baseline (10 vs 6) → not moved; drill if headroom.
    g = pc.evaluate_gate(6.0, 10.0, drill_level=1, cap=4)
    assert g["branch"] == "drill"
    assert g["rank_delta"] == -4.0


def test_gate_no_data_when_no_baseline():
    g = pc.evaluate_gate(None, 5.0, drill_level=0)
    assert g["branch"] == "no_data"


def test_gate_dropped_off_grid_is_no_movement():
    # baseline existed, current None (didn't rank at all) → no movement → halt at cap.
    g = pc.evaluate_gate(5.0, None, drill_level=4, cap=4)
    assert g["branch"] == "halt"


def test_state_for_branch_mapping():
    assert pc.state_for_branch("moved") == "moved"
    assert pc.state_for_branch("drill") == "drill_ready"
    assert pc.state_for_branch("halt") == "halted"
    assert pc.state_for_branch("no_data") == "scan_ready"


# ── cadence math ──────────────────────────────────────────────────────────────


def test_settle_and_rinse_windows():
    assert pc.settle_until(NOW, 7) == NOW + timedelta(days=7)
    assert pc.next_rinse_at(NOW, 42) == NOW + timedelta(days=42)


def test_is_settle_elapsed():
    past = {"settle_until": (NOW - timedelta(days=1)).isoformat()}
    future = {"settle_until": (NOW + timedelta(days=1)).isoformat()}
    assert pc.is_settle_elapsed(past, NOW) is True
    assert pc.is_settle_elapsed(future, NOW) is False
    assert pc.is_settle_elapsed({"settle_until": None}, NOW) is False


def test_is_rinse_due():
    due = {"next_action_at": (NOW - timedelta(hours=1)).isoformat()}
    assert pc.is_rinse_due(due, NOW) is True
    assert pc.is_rinse_due({"next_action_at": None}, NOW) is False


# ── transition log ────────────────────────────────────────────────────────────


def test_record_transition_appends_and_caps():
    hist = []
    hist = pc.record_transition(hist, "draft", "content", NOW, "created")
    hist = pc.record_transition(hist, "content", "settling", NOW, "settling")
    assert len(hist) == 2
    assert hist[-1]["from"] == "content" and hist[-1]["to"] == "settling"
    # cap
    big = pc.record_transition([{"x": i} for i in range(200)], "a", "b", NOW, cap=100)
    assert len(big) == 100


# ── next-action descriptor (hybrid propose-confirm) ───────────────────────────


def test_next_action_confirm_flags():
    assert pc.next_action({"state": "scan_ready"})["confirm"] is True
    assert pc.next_action({"state": "drill_ready", "drill_level": 1})["confirm"] is True
    assert pc.next_action({"state": "draft"})["confirm"] is True
    # auto-advancing / terminal states never ask for a confirm
    assert pc.next_action({"state": "settling", "settle_until": None})["confirm"] is False
    assert pc.next_action({"state": "scanning"})["confirm"] is False
    assert pc.next_action({"state": "maintenance", "next_action_at": None})["confirm"] is False
    assert pc.next_action({"state": "halted", "halted_reason": "stuck"})["confirm"] is False


def test_next_action_halted_surfaces_reason():
    na = pc.next_action({"state": "halted", "halted_reason": "re-check the service page"})
    assert na["action"] == "review"
    assert na["label"] == "re-check the service page"


# ── drilling ──────────────────────────────────────────────────────────────────


def test_drill_seed_questions_uses_current_level():
    items = [
        {"chosen": True, "question": "root q", "drill_level": 0},
        {"chosen": True, "question": "sub q1", "drill_level": 1},
        {"chosen": True, "question": "sub q2", "drill_level": 1},
        {"chosen": False, "question": "unchosen", "drill_level": 1},
    ]
    assert pc.drill_seed_questions(items, 1) == ["sub q1", "sub q2"]


def test_drill_seed_questions_falls_back_to_all_chosen():
    items = [{"chosen": True, "question": "q1"}, {"chosen": True, "question": "q2"}]
    # asking for a level with no items → falls back to every chosen question
    assert pc.drill_seed_questions(items, 3) == ["q1", "q2"]


# ── surfaced copy carries the confidence tag ──────────────────────────────────


def test_gate_summary_carries_confidence_tag():
    g = pc.evaluate_gate(8.0, 5.0, drill_level=0)
    text = pc.gate_summary_text({"service_keyword": "metal roof repair"}, g)
    assert "[PROVEN model]" in text
    assert text.startswith("Moved")
