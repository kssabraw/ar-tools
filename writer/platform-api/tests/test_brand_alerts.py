"""Unit tests for services.brand_alerts — pure scan-regression diff/digest."""

from __future__ import annotations

from services import brand_alerts as ba


def _row(kid, engine, found, *, status="completed", competitor=False, flags=None):
    return {
        "keyword_id": kid, "engine": engine, "mention_found": found, "status": status,
        "is_competitor_scan": competitor,
        "response_analysis": {"accuracy_flags": flags} if flags else None,
    }


def test_index_batch_summarizes_completed_brand_rows():
    rows = [
        _row("k1", "chatgpt", True),
        _row("k1", "claude", False, flags=[{"field": "phone", "stated": "1", "actual": "2"}]),
        _row("k1", "gemini", True, status="failed"),       # excluded
        _row("k1", "chatgpt", True, competitor=True),       # excluded
    ]
    idx = ba.index_batch(rows)
    assert idx["cells"] == {("k1", "chatgpt"): True, ("k1", "claude"): False}
    assert idx["overall"] == (1, 2)
    assert idx["engines"]["chatgpt"] == (1, 1)
    assert idx["misinfo"][0]["field"] == "phone"


def test_detect_changes_only_compares_shared_cells():
    prev = ba.index_batch([_row("k1", "chatgpt", True), _row("k2", "claude", True)])
    # k2/claude missing this scan (different scope); k1/chatgpt flipped to not-found.
    curr = ba.index_batch([_row("k1", "chatgpt", False)])
    ch = ba.detect_changes(prev, curr)
    assert ch["overall_prev_pct"] == 100.0 and ch["overall_curr_pct"] == 0.0
    assert ch["drop_pct"] == 100.0
    assert ch["lost_cells"] == [("k1", "chatgpt")]
    assert ch["engines_dark"] == ["chatgpt"]  # claude not compared (not in both)


def test_detect_changes_new_misinformation_only():
    flag = [{"field": "status", "stated": "permanently closed", "actual": "open"}]
    prev = ba.index_batch([_row("k1", "chatgpt", True)])  # no flags
    curr = ba.index_batch([_row("k1", "chatgpt", True, flags=flag)])
    ch = ba.detect_changes(prev, curr)
    assert len(ch["new_misinfo"]) == 1 and ch["engines_dark"] == [] and ch["drop_pct"] == 0.0


def test_detect_changes_misinfo_not_new_when_present_before():
    flag = [{"field": "phone", "stated": "1", "actual": "2"}]
    prev = ba.index_batch([_row("k1", "chatgpt", True, flags=flag)])
    curr = ba.index_batch([_row("k1", "chatgpt", True, flags=flag)])
    assert ba.detect_changes(prev, curr)["new_misinfo"] == []


def test_summarize_returns_none_when_no_regression():
    prev = ba.index_batch([_row("k1", "chatgpt", True)])
    curr = ba.index_batch([_row("k1", "chatgpt", True)])
    assert ba.summarize_changes(ba.detect_changes(prev, curr), 15) is None


def test_summarize_visibility_drop_warning():
    prev = ba.index_batch([_row("k1", "chatgpt", True), _row("k2", "chatgpt", True)])
    curr = ba.index_batch([_row("k1", "chatgpt", True), _row("k2", "chatgpt", False)])
    digest = ba.summarize_changes(ba.detect_changes(prev, curr), 15)
    assert digest["severity"] == "warning"
    assert "dropped" in digest["title"]
    # 50% drop, but the engine still has one keyword found → not "dark".
    assert digest["triggers"] == ["visibility_drop"]


def test_summarize_drop_below_threshold_alone_is_silent():
    # 10-point drop with the engine still visible → below the 15-pt threshold.
    prev = ba.index_batch([_row(f"k{i}", "chatgpt", True) for i in range(10)])
    curr = ba.index_batch([_row(f"k{i}", "chatgpt", i != 0) for i in range(10)])  # 1/10 lost = 10pt
    ch = ba.detect_changes(prev, curr)
    assert ch["drop_pct"] == 10.0 and ch["engines_dark"] == []  # engine still has 9 found
    assert ba.summarize_changes(ch, 15) is None


def test_summarize_misinformation_is_critical_with_keyword_labels():
    flag = [{"field": "phone", "stated": "1", "actual": "2"}]
    prev = ba.index_batch([_row("k1", "chatgpt", True)])
    curr = ba.index_batch([_row("k1", "chatgpt", True, flags=flag)])
    digest = ba.summarize_changes(ba.detect_changes(prev, curr), 15, {"k1": "burst pipe"})
    assert digest["severity"] == "critical"
    assert "misinformation" in digest["title"].lower()
    assert "burst pipe" in digest["summary"] and "ChatGPT" in digest["summary"]
