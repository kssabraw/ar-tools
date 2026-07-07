"""Unit tests for the SOP task delivery-time catalog."""

from datetime import date

from services import task_catalog


def test_parse_turnaround_concrete_units():
    assert task_catalog.parse_turnaround("10 days") == 10
    assert task_catalog.parse_turnaround("2 weeks") == 14
    assert task_catalog.parse_turnaround("45 days") == 45
    assert task_catalog.parse_turnaround("1 week") == 7
    assert task_catalog.parse_turnaround("4 weeks") == 28


def test_parse_turnaround_non_concrete_is_none():
    for cell in ("weekly", "monthly", "varies", "—", "", "  "):
        assert task_catalog.parse_turnaround(cell) is None


def test_due_date_for_concrete_task():
    today = date(2026, 7, 7)
    result = task_catalog.due_date_for("Niche edit", today)
    assert result is not None
    due, delivery, label = result
    assert due == date(2026, 7, 21)  # +2 weeks
    assert delivery == "2 weeks"
    assert label == "Niche edit"


def test_due_date_for_is_case_insensitive():
    today = date(2026, 7, 7)
    result = task_catalog.due_date_for("gbp blast", today)
    assert result is not None
    due, _, label = result
    assert due == date(2026, 7, 14)  # +7 days
    assert label == "GBP Blast"


def test_due_date_for_recurring_cadence_is_none():
    # "monthly" / "varies" / "—" carry no concrete turnaround → ask instead.
    today = date(2026, 7, 7)
    assert task_catalog.due_date_for("Monthly reporting (per client)", today) is None
    assert task_catalog.due_date_for("Site build", today) is None
    assert task_catalog.due_date_for("GBP post (each)", today) is None


def test_due_date_for_unknown_task_is_none():
    assert task_catalog.due_date_for("Fix GBP categories", date(2026, 7, 7)) is None
    assert task_catalog.due_date_for("", date(2026, 7, 7)) is None


def test_catalog_labels_cover_known_entries():
    labels = task_catalog.catalog_labels()
    assert "Guest post" in labels
    assert "Citations (per 40-batch)" in labels
    assert len(labels) == len(set(labels))  # no dupes
