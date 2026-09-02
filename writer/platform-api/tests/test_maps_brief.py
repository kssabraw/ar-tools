"""Unit tests for the local-pack collapse brief (pure helpers + gating)."""

from __future__ import annotations

from config import settings
from services import maps_brief


_ALERTS = [
    {
        "alert_type": "lost_pack",
        "message": '"roof restoration melbourne" visibility collapsed — appears '
        "on 12.4% of pins, down 78.3 points from 90.7%.",
    },
    {
        "alert_type": "competitor_surge",
        "message": 'Metropolitan Roof Repairs surged on "roof restoration near me" '
        "— now outranks you on 74 pins, up 68 from 6 last scan.",
    },
    {
        "alert_type": "area_decline",
        "message": '"roof restoration melbourne" weakened to the North — average '
        "rank there slipped 8.5 spots (from 4.0 to 12.5).",
    },
]


# ---------------------------------------------------------------------------
# alert_facts
# ---------------------------------------------------------------------------
def test_alert_facts_renders_each_message_as_a_bullet():
    facts = maps_brief.alert_facts(_ALERTS)
    assert facts.count("\n") == 2  # 3 bullets, 2 newlines
    assert "Metropolitan Roof Repairs surged" in facts
    assert facts.startswith("- ")


def test_alert_facts_dedupes_and_preserves_order():
    dup = [{"message": "same"}, {"message": "same"}, {"message": "other"}]
    assert maps_brief.alert_facts(dup) == "- same\n- other"


def test_alert_facts_empty_when_no_messages():
    assert maps_brief.alert_facts([{"alert_type": "x"}]) == ""
    assert maps_brief.alert_facts([]) == ""


# ---------------------------------------------------------------------------
# build_brief_prompt
# ---------------------------------------------------------------------------
def test_build_brief_prompt_grounds_on_facts_and_names_client():
    system, user = maps_brief.build_brief_prompt("First Class Roofing", _ALERTS)
    assert "local pack" in system.lower()
    assert "First Class Roofing" in user
    # The measured facts (the only numbers the model may cite) are in the prompt.
    assert "Metropolitan Roof Repairs surged" in user
    assert "down 78.3 points" in user


def test_build_brief_prompt_handles_missing_facts():
    system, user = maps_brief.build_brief_prompt("", [])
    assert "this client" in user
    assert "no per-alert detail" in user


# ---------------------------------------------------------------------------
# generate_brief — gating (no network)
# ---------------------------------------------------------------------------
def test_generate_brief_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "maps_brief_enabled", False)
    assert maps_brief.generate_brief("Acme", _ALERTS) is None


def test_generate_brief_returns_none_when_no_facts(monkeypatch):
    monkeypatch.setattr(settings, "maps_brief_enabled", True)
    assert maps_brief.generate_brief("Acme", [{"alert_type": "x"}]) is None


def test_generate_brief_returns_trimmed_text(monkeypatch):
    monkeypatch.setattr(settings, "maps_brief_enabled", True)
    captured = {}

    def _fake(**kwargs):
        captured.update(kwargs)
        return "  Metropolitan surged in the north; fund GBP reviews.  \n"

    import services.report_llm as report_llm

    monkeypatch.setattr(report_llm, "generate_text_sync", _fake)
    out = maps_brief.generate_brief("Acme", _ALERTS)
    assert out == "Metropolitan surged in the north; fund GBP reviews."
    # Runs on the configured provider/model with a bounded budget.
    assert captured["provider"] == settings.maps_brief_provider
    assert captured["model"] == settings.maps_brief_model
    assert captured["max_tokens"] == settings.maps_brief_max_tokens


def test_generate_brief_swallows_llm_error(monkeypatch):
    monkeypatch.setattr(settings, "maps_brief_enabled", True)

    def _boom(**kwargs):
        raise RuntimeError("provider down")

    import services.report_llm as report_llm

    monkeypatch.setattr(report_llm, "generate_text_sync", _boom)
    assert maps_brief.generate_brief("Acme", _ALERTS) is None


def test_generate_brief_returns_none_on_empty_llm_text(monkeypatch):
    monkeypatch.setattr(settings, "maps_brief_enabled", True)

    import services.report_llm as report_llm

    monkeypatch.setattr(report_llm, "generate_text_sync", lambda **k: "   ")
    assert maps_brief.generate_brief("Acme", _ALERTS) is None
