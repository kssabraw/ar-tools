"""Unit tests for the social Angle fan-out + angle-proposal pure helpers."""

from services.social import creator, fanout


# ── fan-out pure helpers ─────────────────────────────────────────────────────

def test_resolve_platforms_filters_dedupes_orders():
    avail = ["facebook", "instagram", "twitter"]
    assert fanout.resolve_platforms(["Instagram", "facebook", "instagram"], avail) == ["instagram", "facebook"]
    # unavailable requested platform is dropped
    assert fanout.resolve_platforms(["pinterest", "facebook"], avail) == ["facebook"]
    # empties / blanks ignored
    assert fanout.resolve_platforms(["", "  ", "twitter"], avail) == ["twitter"]
    assert fanout.resolve_platforms([], avail) == []


def test_build_source_ref_per_type():
    assert fanout.build_source_ref("topic", None, None) == {"type": "topic"}
    assert fanout.build_source_ref("url", None, "https://x.io/a") == {"type": "url", "url": "https://x.io/a"}
    assert fanout.build_source_ref("blog_run", "run-1", None) == {"type": "blog_run", "run_id": "run-1"}
    assert fanout.build_source_ref("local_seo_page", "pg-1", None) == {"type": "local_seo_page", "page_id": "pg-1"}
    # unknown type falls back to topic
    assert fanout.build_source_ref("mystery", "x", None) == {"type": "topic"}


def test_draft_status():
    assert fanout.draft_status(has_media=False, requires_image=False, generation_ok=True) == "ready"
    assert fanout.draft_status(has_media=True, requires_image=True, generation_ok=True) == "ready"
    assert fanout.draft_status(has_media=False, requires_image=True, generation_ok=True) == "needs_image"
    assert fanout.draft_status(has_media=True, requires_image=True, generation_ok=False) == "generation_failed"
    assert fanout.draft_status(has_media=False, requires_image=False, generation_ok=False) == "generation_failed"


def test_image_description_for_angle_fallback_chain():
    assert fanout.image_description_for_angle("angle hook", "title", "src") == "angle hook"
    assert fanout.image_description_for_angle("", "title", "src") == "title"
    assert fanout.image_description_for_angle(None, None, "src title") == "src title"
    assert fanout.image_description_for_angle(None, None, None) == "brand social media image"
    assert len(fanout.image_description_for_angle("x" * 900, None, None)) == 400  # capped


# ── angle-proposal pure helpers (creator) ────────────────────────────────────

def test_sanitize_angles_drops_empty_caps_and_titles():
    raw = [
        {"title": "Myth-bust", "hook": "Most people think X", "description": "d1"},
        {"title": "", "hook": "A strong hook with no title", "description": ""},
        {"title": "", "hook": ""},                      # dropped (no title, no hook)
        "not a dict",                                    # dropped
        {"title": "Extra", "hook": "h", "description": "d"},
    ]
    out = creator.sanitize_angles(raw, count=4)
    assert len(out) == 3
    assert out[0] == {"title": "Myth-bust", "hook": "Most people think X", "description": "d1"}
    # title falls back to a hook prefix when missing
    assert out[1]["title"] == "A strong hook with no title"[:60]
    assert out[1]["hook"] == "A strong hook with no title"


def test_sanitize_angles_respects_count_cap():
    raw = [{"title": f"A{i}", "hook": "h"} for i in range(10)]
    assert len(creator.sanitize_angles(raw, count=3)) == 3
    assert len(creator.sanitize_angles(raw, count=0)) == 1  # floor of 1
    assert creator.sanitize_angles(None, count=4) == []


def test_build_angles_prompt_with_and_without_source():
    with_src = creator.build_angles_prompt("Business: Acme", "Roof 101", "We fix roofs.", "VOICE: say we", 4)
    assert "Business: Acme" in with_src
    assert "--- SOURCE ---" in with_src and "We fix roofs." in with_src
    assert "Propose 4 distinct" in with_src
    assert with_src.rstrip().endswith("VOICE: say we")  # voice block appended last

    topic_only = creator.build_angles_prompt("Business: Acme", "Spring promo", "", "", 3)
    assert "--- SOURCE ---" not in topic_only
    assert "Topic: Spring promo" in topic_only
