"""Unit tests for services.feedback_service — the pure normalization helpers."""

from __future__ import annotations

from services import feedback_service as fs


# ---------------------------------------------------------------------------
# clean_labels
# ---------------------------------------------------------------------------
def test_clean_labels_trims_dedupes_and_drops_blanks():
    assert fs.clean_labels(["  Rank Tracker ", "rank tracker", "", "  ", "Maps"]) == [
        "Rank Tracker",
        "Maps",
    ]


def test_clean_labels_none_and_empty():
    assert fs.clean_labels(None) == []
    assert fs.clean_labels([]) == []


def test_clean_labels_caps_length_and_count():
    long = "x" * 100
    assert fs.clean_labels([long])[0] == "x" * 60
    many = [f"label{i}" for i in range(30)]
    assert len(fs.clean_labels(many)) == 20


# ---------------------------------------------------------------------------
# build_insert_row
# ---------------------------------------------------------------------------
def test_build_insert_row_normalizes():
    row = fs.build_insert_row(
        {"kind": "bug", "title": "  broken  ", "body": "  ", "labels": ["A", "a"]},
        created_by="user-1",
    )
    assert row == {
        "kind": "bug",
        "title": "broken",
        "body": None,          # blank body → None
        "priority": "medium",  # default filled in
        "labels": ["A"],       # cleaned + deduped
        "created_by": "user-1",
    }


def test_build_insert_row_keeps_priority_and_body():
    row = fs.build_insert_row(
        {"kind": "wishlist", "title": "new tool", "body": "please", "priority": "high"},
        created_by=None,
    )
    assert row["priority"] == "high"
    assert row["body"] == "please"
    assert row["created_by"] is None


# ---------------------------------------------------------------------------
# build_update_patch — the resolved_at boundary + updated_at bump
# ---------------------------------------------------------------------------
def test_update_patch_stamps_resolved_on_terminal_status():
    for status in ("done", "declined"):
        patch = fs.build_update_patch({"status": status})
        assert patch["resolved_at"] == "now()"
        assert patch["updated_at"] == "now()"


def test_update_patch_clears_resolved_on_reopen():
    for status in ("new", "triaged", "in_progress"):
        patch = fs.build_update_patch({"status": status})
        assert patch["resolved_at"] is None


def test_update_patch_without_status_does_not_touch_resolved():
    patch = fs.build_update_patch({"priority": "low"})
    assert "resolved_at" not in patch
    assert patch["updated_at"] == "now()"


def test_update_patch_normalizes_labels_and_text():
    patch = fs.build_update_patch({"title": "  hi ", "body": "   ", "labels": ["X", "x"]})
    assert patch["title"] == "hi"
    assert patch["body"] is None
    assert patch["labels"] == ["X"]


def test_update_patch_allows_explicit_null_body():
    # An explicit None (clear the field) is preserved, not coerced to a string.
    patch = fs.build_update_patch({"body": None})
    assert patch["body"] is None
