"""Unit tests for the client-facing "content ready" Slack ping pure helpers.

No network — only batch-isolation / summarize / message-copy logic is exercised
(the live queries + emit hit Supabase and are covered by integration, mirroring
tests/test_activity.py's split)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import content_ready  # noqa: E402


def _row(status, created_at, error=None):
    return {"status": status, "error": error, "created_at": created_at}


def test_job_types_are_creation_only():
    # Reoptimize jobs are deliberately excluded — this pings on new content,
    # not edits to existing pages.
    assert set(content_ready.JOB_TYPES) == {
        "local_seo_generate", "ecommerce_generate", "website_page_generate",
    }
    assert "local_seo_reoptimize_url" not in content_ready.JOB_TYPES
    assert "ecommerce_reoptimize_url" not in content_ready.JOB_TYPES


def test_latest_batch_splits_on_gap():
    rows = [
        _row("complete", "2026-07-14T03:00:00+00:00"),
        _row("complete", "2026-07-14T02:59:30+00:00"),
        # > 300s gap starts an earlier, separate batch
        _row("complete", "2026-07-14T02:00:00+00:00"),
    ]
    batch = content_ready.latest_batch(rows)
    assert len(batch) == 2
    assert all(r["created_at"] in ("2026-07-14T03:00:00+00:00", "2026-07-14T02:59:30+00:00") for r in batch)


def test_latest_batch_empty():
    assert content_ready.latest_batch([]) == []


def test_summarize_jobs_counts_cancelled_via_error_marker():
    rows = [
        _row("complete", "t1"),
        _row("complete", "t2"),
        _row("failed", "t3", error="cancelled_by_user"),
        _row("failed", "t4", error="boom"),
    ]
    counts = content_ready.summarize(rows)
    assert counts == {"done": 2, "failed": 1, "cancelled": 1, "total": 4}


def test_summarize_runs_counts_cancelled_via_status():
    rows = [
        _row("complete", "t1"),
        _row("cancelled", "t2"),
        _row("failed", "t3"),
    ]
    counts = content_ready.summarize(rows, cancelled_status="cancelled")
    assert counts == {"done": 1, "failed": 1, "cancelled": 1, "total": 3}


def test_build_note_none_when_all_cancelled():
    counts = {"done": 0, "failed": 0, "cancelled": 3, "total": 3}
    assert content_ready.build_note("Local SEO", "Acme", counts) is None


def test_build_note_singular_page():
    counts = {"done": 1, "failed": 0, "cancelled": 0, "total": 1}
    note = content_ready.build_note("Local SEO", "Acme", counts)
    assert note["title"] == "Local SEO page ready"
    assert note["summary"] == "Local SEO content for Acme finished — 1 done."


def test_build_note_plural_and_failures():
    counts = {"done": 4, "failed": 1, "cancelled": 2, "total": 7}
    note = content_ready.build_note("Ecommerce", "Acme", counts)
    assert note["title"] == "Ecommerce pages ready"
    assert note["summary"] == (
        "Ecommerce content for Acme finished — 4 done, 1 failed, 2 cancelled."
    )


def test_build_note_run_label_uses_article_unit():
    counts = {"done": 2, "failed": 0, "cancelled": 0, "total": 2}
    note = content_ready.build_note(content_ready.RUN_LABEL, "Acme", counts)
    assert note["title"] == "Blog & Service articles ready"


def test_content_ready_kind_routes_to_client_channel():
    from services import notifications

    assert "content_ready" in notifications.PACE_CHANNEL_KINDS
    assert "content_ready" in notifications.CLIENT_SCOPED_PACE_KINDS
