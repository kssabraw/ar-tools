"""Unit tests for the QA verdict-accuracy feedback loop's pure core
(services/qa_feedback.py): event assembly, the disposition classifier (every
branch, incl. the subsequent-review window close), and the accuracy rollup.

The sweep + report are impure (DB) and covered by integration; the decision
logic that says "humans overturned this verdict" is locked here.
"""

from services import qa_feedback as fb


def _status(to, at):
    return {"type": "status", "status": to, "_at": at}


def _review(verdict, at):
    return {"type": "review", "verdict": verdict, "_at": at}


# ---------------------------------------------------------------------------
# build_events
# ---------------------------------------------------------------------------
def test_build_events_filters_sorts_and_reads_to():
    acts = [
        {"kind": "status_changed", "detail": {"field": "status_key", "to": "for_revision"},
         "created_at": "2026-09-01T10:00:00+00:00"},
        {"kind": "status_changed", "detail": {"field": "status_key", "to": "sent_to_client"},
         "created_at": "2026-09-03T10:00:00+00:00"},
        # at/before the review timestamp → excluded
        {"kind": "status_changed", "detail": {"field": "status_key", "to": "in_qa"},
         "created_at": "2026-08-30T10:00:00+00:00"},
    ]
    reviews = [
        {"id": "R0", "verdict": "revisions", "created_at": "2026-08-31T00:00:00+00:00"},  # self → excluded
        {"id": "R1", "verdict": "pass", "created_at": "2026-09-02T10:00:00+00:00"},
    ]
    ev = fb.build_events(acts, reviews, "R0", "2026-08-31T00:00:00+00:00")
    # for_revision(09-01), pass review(09-02), sent_to_client(09-03) — in order;
    # the 08-30 status and the self review R0 are dropped.
    assert [e.get("status") or e.get("verdict") for e in ev] == ["for_revision", "pass", "sent_to_client"]


def test_build_events_unparsable_cutoff_is_empty():
    assert fb.build_events([], [], "R", "not-a-date") == []


# ---------------------------------------------------------------------------
# classify_disposition — shippable (pass / advisory)
# ---------------------------------------------------------------------------
def test_shippable_no_events_pending():
    assert fb.classify_disposition("pass", [])["disposition"] == fb.PENDING


def test_shippable_advanced_is_upheld():
    r = fb.classify_disposition("advisory", [_status("sent_to_client", 1)])
    assert r["disposition"] == fb.UPHELD


def test_shippable_bounced_to_revision_is_overturned_too_lenient():
    r = fb.classify_disposition("pass", [_status("for_revision", 1)])
    assert r["disposition"] == fb.OVERTURNED and r["direction"] == fb.TOO_LENIENT


def test_shippable_rereview_flagged_is_overturned():
    r = fb.classify_disposition("pass", [_review("fail", 1)])
    assert r["disposition"] == fb.OVERTURNED and r["direction"] == fb.TOO_LENIENT


def test_shippable_rereview_agreed_is_upheld():
    assert fb.classify_disposition("pass", [_review("pass", 1)])["disposition"] == fb.UPHELD


# ---------------------------------------------------------------------------
# classify_disposition — flagged (fail / revisions)
# ---------------------------------------------------------------------------
def test_flagged_shipped_without_rereview_is_overturned_too_strict():
    r = fb.classify_disposition("fail", [_status("complete", 1)])
    assert r["disposition"] == fb.OVERTURNED and r["direction"] == fb.TOO_STRICT


def test_flagged_happy_path_rework_then_pass_is_upheld():
    # The rework loop: re-review passes, THEN the task advances. The re-review
    # closes the window, so the later shipped move is not counted as an override.
    ev = [_review("pass", 1), _status("sent_to_client", 2)]
    assert fb.classify_disposition("revisions", ev)["disposition"] == fb.UPHELD


def test_flagged_rereview_still_flagged_is_upheld():
    assert fb.classify_disposition("fail", [_review("revisions", 1)])["disposition"] == fb.UPHELD


def test_flagged_sitting_is_pending():
    assert fb.classify_disposition("revisions", [_status("in_progress", 1)])["disposition"] == fb.PENDING


# ---------------------------------------------------------------------------
# classify_disposition — needs_human + skipped
# ---------------------------------------------------------------------------
def test_needs_human_resolutions():
    assert fb.classify_disposition("needs_human", [_status("complete", 1)])["disposition"] == fb.RESOLVED_ACCEPT
    assert fb.classify_disposition("needs_human", [_status("for_revision", 1)])["disposition"] == fb.RESOLVED_REJECT
    assert fb.classify_disposition("needs_human", [_review("pass", 1)])["disposition"] == fb.RESOLVED_ACCEPT
    assert fb.classify_disposition("needs_human", [])["disposition"] == fb.PENDING


def test_skipped_and_unknown_not_applicable():
    assert fb.classify_disposition("skipped", [_status("complete", 1)])["disposition"] == fb.NOT_APPLICABLE
    assert fb.classify_disposition("weird", [])["disposition"] == fb.NOT_APPLICABLE


def test_window_closes_at_first_review_shipped_after_is_ignored():
    # A shipped move AFTER a re-review belongs to the re-review's window, not
    # this one — so a flagged verdict whose re-review passed is UPHELD even
    # though the task later shipped.
    ev = [_review("pass", 1), _status("complete", 2), _status("sent_to_client", 3)]
    assert fb.classify_disposition("fail", ev)["disposition"] == fb.UPHELD


# ---------------------------------------------------------------------------
# accuracy_stats
# ---------------------------------------------------------------------------
def _row(rubric, verdict, disp):
    return {"rubric": rubric, "verdict": verdict, "human_disposition": disp}


def test_accuracy_stats_counts_and_rates():
    rows = [
        _row("blog_article", "fail", fb.OVERTURNED),      # false alarm
        _row("blog_article", "revisions", fb.UPHELD),
        _row("website_page", "pass", fb.OVERTURNED),      # missed defect
        _row("website_page", "pass", fb.UPHELD),
        _row("citations", "needs_human", fb.RESOLVED_ACCEPT),  # resolved, not decided
        _row("blog_article", "fail", fb.PENDING),         # pending, not decided
        _row("gbp_posts", "skipped", fb.NOT_APPLICABLE),  # n/a
    ]
    s = fb.accuracy_stats(rows, min_samples=3)
    assert s["decided"] == 4
    assert s["overturned"] == 2
    assert s["false_alarms"] == 1        # flagged overturned
    assert s["missed_defects"] == 1      # shippable overturned
    assert s["pending"] == 1 and s["resolved"] == 1 and s["not_applicable"] == 1
    assert s["overturn_rate"] == 0.5
    assert s["by_class"]["flagged"]["overturn_rate"] == 0.5
    assert s["by_class"]["shippable"]["overturn_rate"] == 0.5
    assert s["by_rubric"]["blog_article"] == {"decided": 2, "overturned": 1}
    assert "headline" in s


def test_accuracy_stats_headline_suppressed_below_min_samples():
    rows = [_row("blog_article", "fail", fb.OVERTURNED)]
    s = fb.accuracy_stats(rows, min_samples=3)
    assert s["decided"] == 1
    assert "headline" not in s          # one decided review is noise, no rate headline


def test_accuracy_stats_empty():
    s = fb.accuracy_stats([])
    assert s["decided"] == 0 and s["overturn_rate"] is None and "headline" not in s
