"""Unit tests for on-site content comparison pure helpers (no network)."""

from __future__ import annotations

from services import content_intel


def test_extract_outline_word_count_and_headings():
    html = """
    <html><body>
      <h1>Emergency Plumber Sydney</h1>
      <script>ignore me</script>
      <h2>Burst Pipe Repair</h2>
      <p>We fix burst pipes fast across the whole metro area every day.</p>
      <h3>Blocked Drains</h3>
      <h2>Burst Pipe Repair</h2>  <!-- duplicate heading deduped -->
    </body></html>
    """
    out = content_intel.extract_outline(html)
    assert out["word_count"] > 5
    assert "burst pipe repair" in out["headings"]
    assert "blocked drains" in out["headings"]
    assert out["headings"].count("burst pipe repair") == 1   # deduped
    assert "ignore me" not in " ".join(out["headings"])


def test_extract_outline_empty():
    assert content_intel.extract_outline("") == {"word_count": 0, "headings": []}
    assert content_intel.extract_outline(None) == {"word_count": 0, "headings": []}


def test_compare_content_depth_and_topic_gaps():
    client = {"word_count": 400, "headings": ["overview"]}
    competitors = [
        {"word_count": 1000, "headings": ["overview", "pricing", "faq"]},
        {"word_count": 1200, "headings": ["pricing", "faq", "areas served"]},
        {"word_count": 800, "headings": ["pricing", "warranty"]},
    ]
    cmp = content_intel.compare_content(client, competitors)
    assert cmp["client_word_count"] == 400
    assert cmp["competitor_median_word_count"] == 1000
    assert cmp["depth_behind"] == 600
    # "pricing" on 3/3 and "faq" on 2/3 (>= ceil(3/2)=2) are gaps; "overview" the client has.
    assert "pricing" in cmp["topic_gaps"]
    assert "faq" in cmp["topic_gaps"]
    assert "overview" not in cmp["topic_gaps"]
    assert "warranty" not in cmp["topic_gaps"]   # only 1/3


def test_compare_content_no_depth_gap_when_client_longer():
    client = {"word_count": 2000, "headings": ["a", "b"]}
    competitors = [{"word_count": 800, "headings": ["a"]}]
    cmp = content_intel.compare_content(client, competitors)
    assert cmp["depth_behind"] is None


def test_detect_content_gap_thresholds():
    cmp = {"depth_behind": 600, "topic_gaps": ["pricing", "faq"], "keyword": "plumber"}
    assert content_intel.detect_content_gap(cmp, min_depth_behind=300, min_topic_gaps=3) is not None  # depth fires
    thin = {"depth_behind": 50, "topic_gaps": ["pricing"], "keyword": "x"}
    assert content_intel.detect_content_gap(thin, 300, 3) is None
    topics = {"depth_behind": None, "topic_gaps": ["a", "b", "c", "d"], "keyword": "x"}
    assert content_intel.detect_content_gap(topics, 300, 3) is not None   # topic count fires


def test_domain_helper():
    assert content_intel._domain("https://www.ace.com/x") == "ace.com"
    assert content_intel._domain("http://b.ace.com") == "b.ace.com"
    assert content_intel._domain("") == ""
