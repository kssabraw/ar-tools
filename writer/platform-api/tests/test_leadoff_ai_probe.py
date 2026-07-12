"""Unit tests for the AI-lane probe's pure helpers (no network/DB)."""
import pytest

from services.leadoff_ai_probe import (
    PROBE_HARD_CAP,
    _Tally,
    classify_domain,
    clip,
    summarize_aio,
)


class TestCitationClassification:
    def test_directory_vs_local(self):
        assert classify_domain("https://www.yelp.com/biz/x") == ("yelp.com", "directory")
        assert classify_domain("https://harryslocksmith.com/about") == \
            ("harryslocksmith.com", "local_site")
        assert classify_domain(None) == (None, "local_site")

    def test_summarize_no_aio(self):
        assert summarize_aio([{"type": "organic"}]) == {"aio": False}

    def test_summarize_with_references(self):
        items = [{"type": "ai_overview", "references": [
            {"url": "https://www.yelp.com/search"},
            {"url": "https://www.angi.com/x"},
            {"url": "https://localplumberco.com/"},
        ]}]
        s = summarize_aio(items)
        assert s["aio"] is True and s["citations"] == 3
        assert s["directories"] == ["angi.com", "yelp.com"]
        assert s["local_sites"] == ["localplumberco.com"]
        assert s["has_open_citation_slot"] is False

    def test_open_citation_slot_when_directories_only(self):
        items = [{"type": "ai_overview", "references": [
            {"url": "https://yelp.com/a"}, {"url": "https://reddit.com/r/x"}]}]
        assert summarize_aio(items)["has_open_citation_slot"] is True


class TestTally:
    def test_accumulates_envelope_costs(self):
        t = _Tally(cap=1.0)
        t.pay({"cost": 0.004}, "a")
        t.pay({"cost": 0.02}, "b")
        assert t.spent == 0.024 and len(t.lines) == 2

    def test_hard_cap_raises(self):
        t = _Tally(cap=0.01)
        with pytest.raises(RuntimeError, match="probe_hard_cap_reached"):
            t.pay({"cost": 0.02}, "too much")

    def test_default_cap_is_five(self):
        assert PROBE_HARD_CAP == 5.0


def test_clip_passthrough_and_truncation():
    assert clip({"a": 1}) == {"a": 1}
    big = {"a": "x" * 10_000}
    out = clip(big, limit=100)
    assert isinstance(out, str) and out.endswith("…[clipped]")
