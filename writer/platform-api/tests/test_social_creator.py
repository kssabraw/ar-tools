"""Unit tests for the social Creator's pure copy helpers (no DB / network / LLM)."""

from services.social import creator

FB = {"platform": "facebook", "char_limit": 63206}
IG = {"platform": "instagram", "char_limit": 2200}
X = {"platform": "twitter", "char_limit": 280}
PIN = {"platform": "pinterest", "char_limit": 500}


def test_source_version_stable_and_sensitive():
    a = creator.source_version_of("hello world")
    assert a == creator.source_version_of("hello world")   # stable
    assert a != creator.source_version_of("hello world!")  # sensitive
    assert len(a) == 16
    assert creator.source_version_of("") == creator.source_version_of(None or "")


def test_clamp_copy_under_limit_untouched():
    assert creator.clamp_copy("  hi there  ", 280) == "hi there"
    assert creator.clamp_copy("hi", None) == "hi"


def test_clamp_copy_trims_on_word_boundary():
    text = "word " * 100  # 500 chars
    out = creator.clamp_copy(text, 280)
    assert len(out) <= 280
    assert not out.endswith("wor")     # didn't slice a word mid-way (space was near)
    assert out.split()[-1] == "word"


def test_clamp_copy_hard_cut_when_no_nearby_space():
    long_word = "x" * 400
    out = creator.clamp_copy(long_word, 280)
    assert len(out) == 280


def test_sections_to_text_flattens_and_caps():
    sections = [
        {"heading": "Roof Repair", "body": "<p>We fix <b>leaks</b> fast.</p>"},
        {"heading": "Coverage", "body": "<p>Serving the whole metro.</p>"},
    ]
    out = creator.sections_to_text(sections, 10_000)
    assert "Roof Repair" in out and "We fix leaks fast" in out
    assert "<p>" not in out and "<b>" not in out          # HTML stripped
    assert "Coverage" in out
    # cap applies
    assert len(creator.sections_to_text(sections, 12)) == 12
    assert creator.sections_to_text([], 100) == ""


def test_platform_guidance_x_warns_against_links_and_limits():
    g = creator.platform_guidance("twitter", X, include_hashtags=True)
    assert "280" in g and "link" in g.lower()


def test_platform_guidance_instagram_link_in_bio():
    g = creator.platform_guidance("instagram", IG, include_hashtags=True)
    assert "link in bio" in g.lower() and "hashtag" in g.lower()


def test_platform_guidance_respects_no_hashtags():
    g = creator.platform_guidance("facebook", FB, include_hashtags=False)
    assert "hashtag" in g.lower()  # it says NOT to add them
    assert "Do NOT add hashtags" in g


def test_platform_guidance_unknown_platform_falls_back():
    g = creator.platform_guidance("mastodon", None, include_hashtags=True)
    assert "native social post" in g.lower()


def test_build_copy_prompt_grounds_on_source_and_appends_voice_last():
    system, user = creator.build_copy_prompt(
        platform="facebook", spec=FB, source_title="Roof Repair 101",
        source_text="We fix leaks fast in the metro.", angle="lead with speed",
        tone="warm", fmt="feed", include_hashtags=True,
        client_context="Business: Acme Roofing", voice_block="VOICE RULES: say 'we'.",
    )
    assert "senior social media copywriter" in system.lower()
    assert "Acme Roofing" in user
    assert "--- SOURCE ---" in user and "We fix leaks fast" in user
    assert "lead with speed" in user and "warm" in user.lower()
    # the voice block wins by being appended last
    assert user.rstrip().endswith("VOICE RULES: say 'we'.")


def test_build_copy_prompt_topic_without_source_body():
    system, user = creator.build_copy_prompt(
        platform="twitter", spec=X, source_title="Spring roof check",
        source_text="", angle=None, tone=None, fmt="feed", include_hashtags=True,
        client_context="Business: Acme", voice_block="",
    )
    assert "--- SOURCE ---" not in user
    assert "Topic: Spring roof check" in user


def test_build_copy_prompt_mentions_format_when_reel():
    _system, user = creator.build_copy_prompt(
        platform="instagram", spec=IG, source_title=None, source_text="hi",
        angle=None, tone=None, fmt="reel", include_hashtags=True,
        client_context="Business: Acme", voice_block="",
    )
    assert "reel" in user.lower()
