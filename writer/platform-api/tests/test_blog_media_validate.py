"""Unit tests for app-side media-plan validation (blog_media.validate) and the
planner prompt fill + JSON parse helpers."""
from services.blog_media.article_html import IdIndex
from services.blog_media import validate as v
from services.blog_media.planner import parse_plan_json
from services.blog_media.planner_prompt import fill_prompt


def _idx():
    return IdIndex(
        anchor_ids={"section-001", "section-002", "paragraph-001", "paragraph-002", "paragraph-003"},
        section_ids={"section-001", "section-002"},
        id_to_index={"section-001": 0, "paragraph-001": 1, "paragraph-002": 2, "section-002": 3, "paragraph-003": 4},
        paragraph_section={"paragraph-001": "section-001", "paragraph-002": "section-001", "paragraph-003": "section-002"},
    )


def _hero(**over):
    base = {
        "status": "create", "prompt": "A confident editorial hero scene", "alt_text": "A hero",
        "filename": "hero-google-ai-overview.webp", "width": 2048, "height": 1152, "confidence": 0.9,
    }
    base.update(over)
    return base


def _image_asset(asset_id="inline-1", anchor="paragraph-002", filename="ai-overview-sources.webp", conf=0.82, **gi_over):
    gi = {
        "status": "create", "prompt": "A structured source-authority scene", "alt_text": "Authority signals",
        "filename": filename, "width": 1200, "height": 900, "confidence": conf,
    }
    gi.update(gi_over)
    return {
        "asset_id": asset_id, "asset_type": "generated_image",
        "placement": {"anchor_type": "paragraph", "anchor_id": anchor, "position": "after"},
        "generated_image": gi,
        "chart": {"status": "skip", "type": "none", "series": []},
    }


# ── filenames ────────────────────────────────────────────────────────────────


def test_valid_filename_rules():
    assert v.valid_filename("google-ai-overview.webp", "webp")
    assert v.valid_filename("chart-1.svg", "svg")
    assert not v.valid_filename("Bad_Name.webp", "webp")     # underscore + uppercase
    assert not v.valid_filename("spaces here.webp", "webp")
    assert not v.valid_filename("image.png", "webp")          # wrong ext
    assert not v.valid_filename(("x" * 78) + ".webp", "webp")  # 83 chars > 80


# ── hero ─────────────────────────────────────────────────────────────────────


def test_hero_valid_is_kept():
    r = v.validate_and_clean({"hero_image": _hero(), "inline_assets": []}, idx=_idx(),
                             max_inline=2, allow_charts=False, hero_min=0.75, inline_min=0.75, chart_min=0.90)
    assert r.hero_ok and r.hero["asset_id"] == "hero" and not r.errors


def test_hero_low_confidence_flags_error_and_no_hero():
    r = v.validate_and_clean({"hero_image": _hero(confidence=0.5), "inline_assets": []}, idx=_idx(),
                             max_inline=2, allow_charts=False, hero_min=0.75, inline_min=0.75, chart_min=0.90)
    assert not r.hero_ok and r.hero is None
    assert any("hero_confidence_below" in e for e in r.errors)


def test_hero_bad_filename_flags_error():
    r = v.validate_and_clean({"hero_image": _hero(filename="hero.png"), "inline_assets": []}, idx=_idx(),
                             max_inline=2, allow_charts=False, hero_min=0.75, inline_min=0.75, chart_min=0.90)
    assert "hero_filename_invalid" in r.errors


# ── inline images ────────────────────────────────────────────────────────────


def test_inline_image_kept_when_valid():
    r = v.validate_and_clean({"hero_image": _hero(), "inline_assets": [_image_asset()]}, idx=_idx(),
                             max_inline=2, allow_charts=False, hero_min=0.75, inline_min=0.75, chart_min=0.90)
    assert len(r.inline) == 1 and r.inline[0]["asset_type"] == "image"


def test_inline_dropped_when_anchor_unknown():
    r = v.validate_and_clean(
        {"hero_image": _hero(), "inline_assets": [_image_asset(anchor="paragraph-999")]},
        idx=_idx(), max_inline=2, allow_charts=False, hero_min=0.75, inline_min=0.75, chart_min=0.90,
    )
    # unresolvable placement (no section_id, no fallback) → dropped
    assert r.inline == []
    assert any("placement_unresolvable" in w for w in r.warnings)


def test_inline_kept_when_anchor_bad_but_fallback_present():
    a = _image_asset(anchor="paragraph-999")
    a["placement"]["fallback_excerpt"] = "some verbatim excerpt from the article body here"
    r = v.validate_and_clean({"hero_image": _hero(), "inline_assets": [a]}, idx=_idx(),
                             max_inline=2, allow_charts=False, hero_min=0.75, inline_min=0.75, chart_min=0.90)
    assert len(r.inline) == 1


def test_inline_budget_enforced():
    assets = [_image_asset("inline-1", filename="a.webp"),
              _image_asset("inline-2", anchor="paragraph-003", filename="b.webp"),
              _image_asset("inline-3", filename="c.webp")]
    r = v.validate_and_clean({"hero_image": _hero(), "inline_assets": assets}, idx=_idx(),
                             max_inline=2, allow_charts=False, hero_min=0.75, inline_min=0.75, chart_min=0.90)
    assert len(r.inline) == 2
    assert any("over_inline_budget" in w for w in r.warnings)


def test_duplicate_filename_dropped():
    assets = [_image_asset("inline-1", filename="dup.webp"),
              _image_asset("inline-2", anchor="paragraph-003", filename="dup.webp")]
    r = v.validate_and_clean({"hero_image": _hero(), "inline_assets": assets}, idx=_idx(),
                             max_inline=2, allow_charts=False, hero_min=0.75, inline_min=0.75, chart_min=0.90)
    assert len(r.inline) == 1
    assert any("duplicate_filename" in w for w in r.warnings)


def test_low_confidence_inline_dropped():
    r = v.validate_and_clean({"hero_image": _hero(), "inline_assets": [_image_asset(conf=0.6)]}, idx=_idx(),
                             max_inline=2, allow_charts=False, hero_min=0.75, inline_min=0.75, chart_min=0.90)
    assert r.inline == []
    assert any("confidence_below_threshold" in w for w in r.warnings)


# ── charts (phase 1 defers) ──────────────────────────────────────────────────


def test_chart_deferred_in_phase_1():
    chart_asset = {
        "asset_id": "inline-1", "asset_type": "chart",
        "placement": {"anchor_id": "paragraph-002"},
        "generated_image": {"status": "skip"},
        "chart": {"status": "create", "type": "bar", "filename": "c.svg", "confidence": 0.95, "series": []},
    }
    r = v.validate_and_clean({"hero_image": _hero(), "inline_assets": [chart_asset]}, idx=_idx(),
                             max_inline=2, allow_charts=False, hero_min=0.75, inline_min=0.75, chart_min=0.90)
    assert r.inline == []
    assert any("charts_deferred_to_phase_2" in w for w in r.warnings)


def test_only_one_chart_kept_when_enabled():
    def chart(aid, fn):
        return {
            "asset_id": aid, "asset_type": "chart",
            "placement": {"anchor_id": "paragraph-002"},
            "generated_image": {"status": "skip"},
            "chart": {"status": "create", "type": "bar", "filename": fn, "confidence": 0.95, "series": []},
        }
    r = v.validate_and_clean(
        {"hero_image": _hero(), "inline_assets": [chart("inline-1", "c1.svg"), chart("inline-2", "c2.svg")]},
        idx=_idx(), max_inline=2, allow_charts=True, hero_min=0.75, inline_min=0.75, chart_min=0.90,
    )
    assert len([a for a in r.inline if a["asset_type"] == "chart"]) == 1
    assert any("dropped_second_chart" in w for w in r.warnings)


# ── prompt fill + json parse ─────────────────────────────────────────────────


def test_fill_prompt_substitutes_tokens():
    out = fill_prompt(
        article_title="My Title", article_html="<p id=\"paragraph-001\">hi</p>",
        article_plain_text="hi there", word_count=1500, brand_personality="professional, direct",
        hero_width=2048, hero_height=1152, inline_width=1200, inline_height=900, allow_derived=True,
    )
    assert "{{ARTICLE_TITLE}}" not in out and "My Title" in out
    assert "1500" in out and "professional, direct" in out
    assert '"width": 2048' in out and '"width": 1200' in out
    assert "true" in out  # allow_derived


def test_parse_plan_json_handles_fences_and_prose():
    assert parse_plan_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_plan_json('Here is the plan:\n{"a": 2}\nDone.') == {"a": 2}
    assert parse_plan_json('{"a": 3}') == {"a": 3}


def test_malformed_width_degrades_instead_of_crashing():
    r = v.validate_and_clean(
        {"hero_image": _hero(width="2048x1152"),
         "inline_assets": [_image_asset(width="1200x900")]},
        idx=_idx(), max_inline=2, allow_charts=False,
        hero_min=0.75, inline_min=0.75, chart_min=0.90,
    )
    assert r.hero_ok and r.hero["width"] is None       # falls back to config default
    assert len(r.inline) == 1 and r.inline[0]["width"] is None


def test_budget_trim_prefers_chart_over_image():
    chart_asset = {
        "asset_id": "inline-2", "asset_type": "chart",
        "placement": {"anchor_id": "paragraph-003"},
        "generated_image": {"status": "skip"},
        "chart": {"status": "create", "type": "bar", "filename": "c.svg",
                  "confidence": 0.95, "series": []},
    }
    # Model returns [image, chart] but budget is 1 → the chart must win the slot.
    r = v.validate_and_clean(
        {"hero_image": _hero(), "inline_assets": [_image_asset("inline-1"), chart_asset]},
        idx=_idx(), max_inline=1, allow_charts=True,
        hero_min=0.75, inline_min=0.75, chart_min=0.90,
    )
    assert len(r.inline) == 1 and r.inline[0]["asset_type"] == "chart"


def test_second_asset_in_same_section_dropped():
    assets = [_image_asset("inline-1", anchor="paragraph-001", filename="a.webp"),
              _image_asset("inline-2", anchor="paragraph-002", filename="b.webp")]  # both section-001
    r = v.validate_and_clean({"hero_image": _hero(), "inline_assets": assets}, idx=_idx(),
                             max_inline=2, allow_charts=False, hero_min=0.75, inline_min=0.75, chart_min=0.90)
    assert len(r.inline) == 1
    assert any("same_section" in w for w in r.warnings)
