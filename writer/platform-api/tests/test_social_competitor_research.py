"""Unit tests for the competitor-research engine's pure helpers + the best-effort
LLM rollup (services/social/competitor_research.py). External calls mocked."""

from datetime import datetime, timezone

import pytest

from services.social import competitor_research as cr


def _post(url="u", *, likes=0, comments=0, shares=0, views=0, caption="", media="image", when=None):
    return {"url": url, "caption": caption, "likes": likes, "comments": comments,
            "shares": shares, "views": views, "media_type": media, "published_at": when}


# ── deterministic aggregation ─────────────────────────────────────────────────

def test_engagement_of_sums_likes_comments_shares_not_views():
    assert cr.engagement_of(_post(likes=10, comments=3, shares=2, views=999)) == 15


def test_aggregate_formats_dominant():
    posts = [_post(media="video"), _post(media="video"), _post(media="image"), _post(media="unknown")]
    f = cr.aggregate_formats(posts)
    assert f["video"] == 2 and f["image"] == 1 and f["unknown"] == 1
    assert f["dominant"] == "video"
    # unknown never wins the dominant slot
    assert cr.aggregate_formats([_post(media="unknown")])["dominant"] is None
    assert cr.aggregate_formats([])["dominant"] is None


def test_aggregate_cadence_per_week():
    posts = [
        _post(when="2026-09-01T00:00:00+00:00"),
        _post(when="2026-09-08T00:00:00+00:00"),
        _post(when="2026-09-15T00:00:00+00:00"),
        _post(when=None),  # undated — counted in posts, not in cadence math
    ]
    c = cr.aggregate_cadence(posts)
    assert c["posts"] == 4 and c["dated_posts"] == 3 and c["span_days"] == 14
    assert c["per_week"] == pytest.approx(1.5)
    # fewer than two dated posts → no rate
    assert cr.aggregate_cadence([_post(when="2026-09-01T00:00:00+00:00")])["per_week"] is None
    # all same day → span 0, no divide-by-zero
    same = cr.aggregate_cadence([_post(when="2026-09-01T00:00:00+00:00"),
                                 _post(when="2026-09-01T10:00:00+00:00")])
    assert same["span_days"] == 0 and same["per_week"] is None


def test_top_performers_ranks_and_strips_identity():
    posts = [
        _post("a", likes=5, caption="secret caption", media="image"),
        _post("b", likes=100, comments=10, caption="author name here", media="video"),
        _post("c", likes=50),
        _post(None, likes=999),  # url-less dropped even though highest engagement
    ]
    top = cr.top_performers(posts, 2)
    assert [t["url"] for t in top] == ["b", "c"]
    assert top[0]["engagement"] == 110
    # links + numbers only — no caption / author text leaks through
    assert "caption" not in top[0] and "author" not in top[0]
    assert set(top[0]) == {"url", "engagement", "likes", "comments", "shares", "views",
                           "published_at", "media_type"}


def test_captions_for_rollup_orders_by_engagement_caps_and_truncates():
    posts = [
        _post(likes=1, caption="low"),
        _post(likes=100, caption="high " * 200),
        _post(likes=50, caption=""),   # empty caption skipped
        _post(likes=10, caption="mid"),
    ]
    caps = cr.captions_for_rollup(posts, cap=2, per_caption_chars=20)
    assert len(caps) == 2
    assert caps[0].startswith("high")       # highest-engagement first
    assert len(caps[0]) == 20               # per-caption truncation
    assert caps[1] == "mid"


# ── rollup sanitize + signal row ──────────────────────────────────────────────

def test_sanitize_rollup_partial_and_garbage():
    out = cr.sanitize_rollup({"themes": ["a", "", "b", None], "whats_working": "  works  "})
    assert out["themes"] == ["a", "b"]
    assert out["hook_patterns"] == []      # missing key → empty
    assert out["whats_working"] == "works"
    assert cr.sanitize_rollup(None) == {"themes": [], "hook_patterns": [], "whats_working": ""}
    # caps to 6 items
    assert len(cr.sanitize_rollup({"themes": [str(i) for i in range(20)]})["themes"]) == 6


def test_build_signal_row_ok_vs_insufficient():
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    posts = [_post("a", likes=10, caption="x", when="2026-09-01T00:00:00+00:00"),
             _post("b", likes=20, caption="y", when="2026-09-08T00:00:00+00:00")]
    row = cr.build_signal_row("c1", "comp1", "Instagram", posts,
                              {"themes": ["t"], "hook_patterns": ["h"], "whats_working": "w"}, now)
    assert row["client_id"] == "c1" and row["competitor_id"] == "comp1"
    assert row["platform"] == "instagram" and row["status"] == "ok"
    assert row["themes"] == ["t"] and row["whats_working"] == "w"
    assert row["formats"]["dominant"] == "image"
    assert len(row["top_performers"]) == 2

    empty = cr.build_signal_row("c1", "comp1", "instagram", [], None, now)
    assert empty["status"] == "insufficient_data"
    assert empty["top_performers"] == [] and empty["whats_working"] is None


# ── angle grounding ───────────────────────────────────────────────────────────

def test_select_signals_for_angles_latest_per_pair_drops_insufficient():
    signals = [
        {"competitor_id": "1", "platform": "instagram", "status": "ok",
         "captured_at": "2026-09-01T00:00:00+00:00", "themes": ["old"]},
        {"competitor_id": "1", "platform": "instagram", "status": "ok",
         "captured_at": "2026-09-10T00:00:00+00:00", "themes": ["new"]},
        {"competitor_id": "1", "platform": "facebook", "status": "insufficient_data",
         "captured_at": "2026-09-10T00:00:00+00:00"},
        {"competitor_id": "2", "platform": "instagram", "status": "ok",
         "captured_at": "2026-09-05T00:00:00+00:00", "themes": ["b"]},
    ]
    out = cr.select_signals_for_angles(signals, cap=10)
    # one per (competitor, platform); the insufficient_data row is dropped
    pairs = {(s["competitor_id"], s["platform"]) for s in out}
    assert pairs == {("1", "instagram"), ("2", "instagram")}
    ig1 = next(s for s in out if s["competitor_id"] == "1")
    assert ig1["themes"] == ["new"]        # latest wins
    # cap respected
    assert len(cr.select_signals_for_angles(signals, cap=1)) == 1


def test_render_competitor_signals_block_empty_and_populated():
    assert cr.render_competitor_signals_block([]) == ""
    assert cr.render_competitor_signals_block(
        [{"competitor_id": "1", "platform": "facebook", "status": "insufficient_data"}]
    ) == ""
    block = cr.render_competitor_signals_block([{
        "competitor_id": "1", "competitor_name": "Rival Co", "platform": "instagram", "status": "ok",
        "captured_at": "2026-09-10T00:00:00+00:00", "themes": ["tips", "proof"],
        "hook_patterns": ["question opener"], "whats_working": "Short how-tos do well.",
    }])
    assert "Rival Co on instagram" in block
    assert "tips, proof" in block and "question opener" in block
    assert "Short how-tos do well." in block
    assert "transform, never copy" in block  # the guardrail line is present


def test_research_gate_open(monkeypatch):
    monkeypatch.setattr(cr.settings, "social_enabled", True)
    monkeypatch.setattr(cr.settings, "social_competitor_research_enabled", True)
    monkeypatch.setattr(cr.settings, "apify_api_token", "tok")
    assert cr.research_gate_open() is True
    monkeypatch.setattr(cr.settings, "apify_api_token", "")
    assert cr.research_gate_open() is False  # no token → closed
    monkeypatch.setattr(cr.settings, "apify_api_token", "tok")
    monkeypatch.setattr(cr.settings, "social_competitor_research_enabled", False)
    assert cr.research_gate_open() is False


# ── LLM rollup (mocked) ───────────────────────────────────────────────────────

async def test_run_signal_rollup_empty_captions_short_circuits():
    out = await cr.run_signal_rollup("instagram", [], {"dominant": "image"}, {})
    assert out == {"themes": [], "hook_patterns": [], "whats_working": ""}


async def test_run_signal_rollup_success(monkeypatch):
    async def fake_forced_tool(**kwargs):
        assert "instagram" in kwargs["user"]
        return {"themes": ["a"], "hook_patterns": ["b"], "whats_working": "works"}

    import services.report_llm as report_llm
    monkeypatch.setattr(report_llm, "run_forced_tool", fake_forced_tool)
    out = await cr.run_signal_rollup("instagram", ["caption one"], {"dominant": "image"}, {"per_week": 3})
    assert out == {"themes": ["a"], "hook_patterns": ["b"], "whats_working": "works"}


async def test_run_signal_rollup_failure_degrades(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("provider down")

    import services.report_llm as report_llm
    monkeypatch.setattr(report_llm, "run_forced_tool", boom)
    out = await cr.run_signal_rollup("instagram", ["caption"], {}, {})
    assert out == {"themes": [], "hook_patterns": [], "whats_working": ""}
