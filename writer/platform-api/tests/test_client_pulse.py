"""Tests for the Weekly Pulse (copy-paste client update) — pure builders."""

from __future__ import annotations

from datetime import date

from services import client_pulse as P

CATS = {"content": "Content", "link_building": "Link Building", "gbp_authority": "GBP Authority"}
ITEMIZE = {"content", "gbp_authority"}


def test_week_start_of():
    assert P.week_start_of(date(2026, 7, 15)) == date(2026, 7, 13)  # Wed → Mon
    assert P.week_start_of(date(2026, 7, 13)) == date(2026, 7, 13)  # Mon → itself
    assert P.week_start_of(date(2026, 7, 19)) == date(2026, 7, 13)  # Sun → prior Mon


def test_split_by_category_filter():
    tasks = [
        {"name": "Write blog post", "category": "content"},
        {"name": "Update GBP hours", "category": "gbp_authority"},
        {"name": "PBN order batch 3", "category": "link_building"},   # internal — never itemized
        {"name": "Vendor citation buy", "category": "link_building"},
        {"name": "Mystery work", "category": None},                    # unknown → summarized
    ]
    itemized, summaries = P.split_by_category(tasks, ITEMIZE, CATS)
    assert itemized == ["Write blog post", "Update GBP hours"]
    assert "2 Link Building actions" in summaries
    assert any(s.startswith("1 other action") for s in summaries)
    assert not any("PBN" in s or "Vendor" in s for s in summaries)  # names stay internal


def test_render_pulse_full():
    body = P.render_pulse(
        "Acme Roofing", date(2026, 7, 13),
        done_items=["Update GBP hours"], done_summaries=["3 Link Building actions"],
        published=["“best roof repair” (blog post)"],
        upcoming_items=["Service page: roof repair Fort Lauderdale"],
        upcoming_summaries=["2 Link Building actions"],
        agency_name="Amazing Rankings",
    )
    assert body.startswith("Weekly update — Acme Roofing")
    assert "Done last week:" in body and "On tap this week:" in body
    assert "• Published: “best roof repair” (blog post)" in body
    assert "• Update GBP hours — completed" in body
    assert "• 3 Link Building actions completed" in body
    assert "• Service page: roof repair Fort Lauderdale" in body
    assert "• 2 Link Building actions planned" in body
    assert body.rstrip().endswith("— Amazing Rankings")
    # Plain text — no markdown bold/underscore syntax that would paste badly.
    assert "*" not in body and "_" not in body


def test_render_pulse_quiet_week_stays_positive():
    body = P.render_pulse("Acme", date(2026, 7, 13), [], [], [], [], [], "Agency")
    assert "Groundwork and ongoing optimization" in body
    assert "Continuing the monthly plan" in body


def test_render_pulse_caps_long_sections():
    many = [f"Task {i}" for i in range(12)]
    body = P.render_pulse("Acme", date(2026, 7, 13), many, [], [], [], [], "Agency")
    assert "…and 4 more" in body


# ---------------------------------------------------------------------------
# Context enrichment: describe_task + business_context
# ---------------------------------------------------------------------------
def test_describe_task_note_beats_blurb_beats_name():
    blurbs = {"gbp posts": "Keeps your listing active and gives searchers a reason to choose you."}
    # A task-specific client note wins.
    assert P.describe_task(
        {"name": "GBP Posts", "client_note": "Posted your July storm-damage special",
         "library_task_name": "GBP Posts"}, blurbs,
    ) == "GBP Posts — Posted your July storm-damage special"
    # No note → the library blurb (matched via library_task_name).
    assert P.describe_task(
        {"name": "GBP Posts (June)", "client_note": None, "library_task_name": "GBP Posts"}, blurbs,
    ) == "GBP Posts (June) — why it matters: Keeps your listing active and gives searchers a reason to choose you."
    # No note, no blurb match → just the name. The INTERNAL description never appears.
    assert P.describe_task(
        {"name": "One-off fix", "description": "internal diagnosis, deep link"}, blurbs,
    ) == "One-off fix"


def test_split_by_category_threads_blurbs():
    blurbs = {"blog post title": "Targets a question your customers actually search."}
    tasks = [{"name": "Blog Post Title", "category": "content", "library_task_name": "Blog Post Title"}]
    itemized, _ = P.split_by_category(tasks, ITEMIZE, CATS, blurbs)
    assert itemized == ["Blog Post Title — why it matters: Targets a question your customers actually search."]


def test_business_context():
    client = {
        "gbp": {"gbp_category": "Roofing contractor", "address": "Columbus, OH"},
        "business_location": "Columbus, OH",
        "detected_icp": None, "differentiators": None, "icp_text": "Homeowners with storm damage",
    }
    ctx = P.business_context(client)
    assert "Roofing contractor" in ctx and "Columbus, OH" in ctx
    assert "Homeowners with storm damage" in ctx
    # Nothing known → empty, never fabricated.
    assert P.business_context({"gbp": None}) == ""


def test_narrative_facts_include_business_block():
    facts = P.narrative_facts("Acme", date(2026, 7, 13), [], [], [], [], [],
                              "Agency", business="Business type: Roofing contractor")
    assert "BUSINESS CONTEXT:" in facts and "Roofing contractor" in facts


# ---------------------------------------------------------------------------
# Narrative mode — grounded facts + fallback
# ---------------------------------------------------------------------------
def test_narrative_facts_carry_only_filtered_data():
    facts = P.narrative_facts(
        "Acme Roofing", date(2026, 7, 13),
        done_items=["Update GBP hours"], done_summaries=["3 Link Building actions"],
        published=["“best roof repair” (blog post)"],
        upcoming_items=["Service page: roof repair"], upcoming_summaries=[],
        agency_name="Amazing Rankings",
    )
    assert "WORK COMPLETED LAST WEEK:" in facts and "PLANNED THIS WEEK:" in facts
    assert "Update GBP hours" in facts and "best roof repair" in facts
    # Summarized categories arrive as counts with the summarize instruction —
    # never as task names (the model can't leak what it never sees).
    assert "3 Link Building actions (summarize as ongoing authority/technical work)" in facts
    assert "Amazing Rankings" in facts


def test_narrative_facts_quiet_week():
    facts = P.narrative_facts("Acme", date(2026, 7, 13), [], [], [], [], [], "Agency")
    assert "ongoing groundwork week" in facts and "continuing the monthly plan" in facts


def test_narrate_pulse_disabled_returns_none(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "pulse_narrative_enabled", False)
    assert P.narrate_pulse("facts") is None
    monkeypatch.setattr(settings, "pulse_narrative_enabled", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert P.narrate_pulse("facts") is None  # no key → clean fallback


def test_build_pulse_falls_back_to_bullets_on_narrative_failure(monkeypatch):
    # narrate_pulse → None must yield the deterministic bullet body, not crash.
    monkeypatch.setattr(P, "narrate_pulse", lambda facts: None)

    class _Q:
        def __init__(self, data): self._d = data
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def is_(self, *a, **k): return self
        def gte(self, *a, **k): return self
        def lt(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def order(self, *a, **k): return self
        def upsert(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": self._d})()

    class _SB:
        def table(self, name):
            if name == "clients":
                return _Q([{"id": "c1", "name": "Acme"}])
            return _Q([])

    monkeypatch.setattr(P, "get_supabase", lambda: _SB())
    body = P.build_pulse("c1", date(2026, 7, 15))
    assert body.startswith("Weekly update — Acme")  # the bullet fallback


def test_build_pulse_prefers_narrative(monkeypatch):
    monkeypatch.setattr(P, "narrate_pulse", lambda facts: "Hi [First name],\n\nGreat week…")

    class _Q:
        def __init__(self, data): self._d = data
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def is_(self, *a, **k): return self
        def gte(self, *a, **k): return self
        def lt(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def order(self, *a, **k): return self
        def upsert(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": self._d})()

    class _SB:
        def table(self, name):
            if name == "clients":
                return _Q([{"id": "c1", "name": "Acme"}])
            return _Q([])

    monkeypatch.setattr(P, "get_supabase", lambda: _SB())
    body = P.build_pulse("c1", date(2026, 7, 15))
    assert body.startswith("Hi [First name],")
