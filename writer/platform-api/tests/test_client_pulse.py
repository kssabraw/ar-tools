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
