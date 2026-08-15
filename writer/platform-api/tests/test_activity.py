"""Unit tests for the cross-module Activity awareness pure helpers.

No network — only the batch-isolation / summary / notification-copy logic is
exercised (the live queries + emit hit Supabase and are covered by integration).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import activity  # noqa: E402


def _row(status, created_at, error=None):
    return {"status": status, "error": error, "created_at": created_at}


def test_family_and_content_types():
    assert activity.family_for("ecommerce_generate") == "ecommerce"
    assert activity.family_for("ecommerce_reoptimize_url") == "ecommerce"
    assert activity.family_for("local_seo_generate") == "local_seo"
    assert activity.family_for("local_seo_reoptimize_url") == "local_seo"
    # scoring / planning jobs are NOT content
    assert activity.family_for("ecommerce_action") is None
    assert activity.family_for("local_seo_silo") is None
    assert activity.family_for(None) is None
    assert activity.CONTENT_JOB_TYPES == {
        "ecommerce_generate",
        "ecommerce_reoptimize_url",
        "local_seo_generate",
        "local_seo_reoptimize_url",
    }


def test_latest_batch_splits_on_gap():
    rows = [
        _row("complete", "2026-07-14T03:00:00+00:00"),
        _row("failed", "2026-07-14T03:00:01+00:00", "boom"),
        _row("failed", "2026-07-14T03:00:02+00:00", "cancelled_by_user"),
        # earlier batch, >5min gap — must be excluded
        _row("complete", "2026-07-14T01:00:00+00:00"),
        _row("complete", "2026-07-14T00:59:59+00:00"),
    ]
    latest = activity._latest_batch(rows)
    assert len(latest) == 3
    # only the recent cluster
    assert all("03:00" in r["created_at"] for r in latest)


def test_latest_batch_single_and_empty():
    assert activity._latest_batch([]) == []
    one = [_row("complete", "2026-07-14T03:00:00+00:00")]
    assert activity._latest_batch(one) == one


def test_summarize_batch_counts_cancelled_separately():
    rows = [
        _row("complete", "t"),
        _row("complete", "t"),
        _row("failed", "t", "boom"),
        _row("failed", "t", "cancelled_by_user"),
    ]
    c = activity.summarize_batch(rows)
    assert c == {"done": 2, "failed": 1, "cancelled": 1, "total": 4}


def test_build_batch_notification_copy():
    note = activity.build_batch_notification(
        "ecommerce", "Nova Life Peptides", {"done": 66, "failed": 3, "cancelled": 0, "total": 69}
    )
    assert note["title"] == "Ecommerce pages finished"
    assert "Nova Life Peptides" in note["summary"]
    assert "66 done" in note["summary"] and "3 failed" in note["summary"]


def test_build_batch_notification_singular_and_local_seo():
    note = activity.build_batch_notification(
        "local_seo", "Acme", {"done": 1, "failed": 0, "cancelled": 0, "total": 1}
    )
    assert note["title"] == "Local SEO page finished"  # singular
    assert "local seo batch for acme" in note["summary"].lower()


def test_build_batch_notification_all_cancelled_is_silent():
    # A wholly-cancelled batch produces no notification (user already knows).
    assert (
        activity.build_batch_notification(
            "ecommerce", "Acme", {"done": 0, "failed": 0, "cancelled": 40, "total": 40}
        )
        is None
    )


def test_build_batch_notification_reports_failures_only():
    note = activity.build_batch_notification(
        "ecommerce", "Acme", {"done": 0, "failed": 2, "cancelled": 0, "total": 2}
    )
    assert note is not None
    assert "0 done" in note["summary"] and "2 failed" in note["summary"]


# ── single-job registry + completion notification ───────────────────────────

def test_activity_job_types_union():
    # The indicator reads content page jobs + every registered single job.
    assert activity.CONTENT_JOB_TYPES <= activity.ACTIVITY_JOB_TYPES
    assert "keyword_research" in activity.ACTIVITY_JOB_TYPES
    assert "domain_overview" in activity.ACTIVITY_JOB_TYPES
    # A single-job type is not a content family.
    assert activity.family_for("keyword_research") is None


def test_single_job_notification_complete():
    note = activity.single_job_notification("keyword_research", "Acme", "complete")
    assert note["title"] == "Keyword research finished"
    assert "acme" in note["summary"].lower()
    assert note["severity"] == "info"


def test_single_job_notification_failed_is_warning_with_reason():
    note = activity.single_job_notification("domain_overview", "Acme", "failed", "boom")
    assert note["title"] == "Domain overview failed"
    assert note["severity"] == "warning"
    assert "boom" in note["summary"]


def test_single_job_notification_cancelled_is_silent():
    assert activity.single_job_notification(
        "keyword_research", "Acme", "failed", "cancelled_by_user"
    ) is None


def test_single_job_notification_unregistered_or_running_is_none():
    # Content page jobs are handled by the batch path, not this one.
    assert activity.single_job_notification("local_seo_generate", "Acme", "complete") is None
    # A non-terminal status never notifies.
    assert activity.single_job_notification("keyword_research", "Acme", "running") is None
    # An unknown type is inert.
    assert activity.single_job_notification("nope", "Acme", "complete") is None


def test_fanout_blog_reoptimize_notifies_on_completion():
    note = activity.single_job_notification("fanout_blog_reoptimize", "Acme", "complete")
    assert note is not None
    assert "reoptimization" in note["title"].lower()
    assert "acme" in note["summary"].lower()


def test_fanout_reopt_registered_but_score_stays_silent():
    # The multi-minute reoptimize is a registered walk-away job (pings + activity
    # feed); the fast, inline score is deliberately NOT registered (no ping, no
    # feed entry).
    assert "fanout_blog_reoptimize" in activity.ACTIVITY_JOB_TYPES
    assert "fanout_blog_score" not in activity.ACTIVITY_JOB_TYPES
    assert activity.single_job_notification("fanout_blog_score", "Acme", "complete") is None


def test_job_item_single_registered():
    job = {
        "id": "j1", "job_type": "keyword_research", "entity_id": "c1",
        "payload": {"user_id": "u1"}, "status": "running",
        "created_at": "2026-08-08T00:00:00+00:00",
    }
    item = activity._job_item(job, {"c1": "Acme"})
    assert item["family"] == "task"
    assert item["kind_label"] == "Keyword research"
    assert item["href"] == "/clients/c1/keyword-research"
    assert item["client_name"] == "Acme"
