"""Unit tests for the Brand Guide Phase-4 edit/adopt/download/suggest core.

Pure over dicts — no DB / network. Covers the structured-field edit ops (§9), the
`edited`-setting no-op distinction, swatch curation keeping the usage map honest,
the logo-candidate guard (§12 Q1), the profile download path resolution (§4.7),
and the suggest-only voice text builder (§4.8)."""

from __future__ import annotations

import pytest

from services import brand_guide_edit as E


def _synth():
    return {
        "tagline": "Old tagline",
        "positioning_statement": "Old positioning",
        "mission": "Old mission",
        "voice_examples": {"headline": "Old headline", "cta": "Buy now"},
        "we_say_we_dont": [{"we_say": "clear", "we_dont": "jargon"}],
        "key_messages": ["fast", "trusted"],
        "boilerplate": {"short": "Short bp", "long": "Long bp"},
        "color": {
            "swatches": [
                {"hex": "#01162F", "name": "Navy", "role": "primary"},
                {"hex": "#FFFFFF", "name": "White", "role": "neutral"},
                {"hex": "#FF0000", "name": "Red", "role": "accent"},
            ],
            "usage_ratios": {"roles": {}},
        },
    }


# ── validate_ops ──────────────────────────────────────────────────────────────
def test_validate_rejects_empty_and_unknown():
    with pytest.raises(E.EditError):
        E.validate_ops([])
    with pytest.raises(E.EditError):
        E.validate_ops([{"op": "nope"}])
    with pytest.raises(E.EditError):
        E.validate_ops([{"op": "set_field", "field": "not_a_field", "value": "x"}])
    with pytest.raises(E.EditError):
        E.validate_ops([{"op": "set_voice_example", "key": "bogus", "value": "x"}])
    with pytest.raises(E.EditError):
        E.validate_ops([{"op": "swatch_drop"}])  # missing hex
    with pytest.raises(E.EditError):
        E.validate_ops([{"op": "swatch_rename", "hex": "#01162F"}])  # missing name


def test_validate_accepts_good_ops():
    ops = E.validate_ops([
        {"op": "set_field", "field": "tagline", "value": "New"},
        {"op": "set_voice_example", "key": "cta", "value": "Go"},
        {"op": "swatch_rename", "hex": "#01162F", "name": "Deep Navy"},
        {"op": "swatch_drop", "hex": "#FF0000"},
        {"op": "swatch_flag_not_brand", "hex": "#FFFFFF"},
    ])
    assert len(ops) == 5


# ── apply_edits ───────────────────────────────────────────────────────────────
def test_set_field_and_purity():
    src = _synth()
    out, applied = E.apply_edits(src, [{"op": "set_field", "field": "tagline", "value": "Fresh"}])
    assert applied == 1
    assert out["tagline"] == "Fresh"
    assert src["tagline"] == "Old tagline"  # input untouched (deep-copied)


def test_set_field_empty_clears():
    out, applied = E.apply_edits(_synth(), [{"op": "set_field", "field": "mission", "value": ""}])
    assert applied == 1 and out["mission"] == ""


def test_set_voice_example_add_and_clear():
    out, _ = E.apply_edits(_synth(), [{"op": "set_voice_example", "key": "cta", "value": ""}])
    assert "cta" not in out["voice_examples"]
    out2, _ = E.apply_edits(_synth(), [{"op": "set_voice_example", "key": "email_opener", "value": "Hi there"}])
    assert out2["voice_examples"]["email_opener"] == "Hi there"


def test_swatch_rename_flag_drop():
    out, applied = E.apply_edits(_synth(), [
        {"op": "swatch_rename", "hex": "#01162f", "name": "Deep Navy"},  # case-insensitive match
        {"op": "swatch_flag_not_brand", "hex": "#FFFFFF"},
        {"op": "swatch_drop", "hex": "#FF0000"},
    ])
    assert applied == 3
    sw = {s["hex"]: s for s in out["color"]["swatches"]}
    assert "#FF0000" not in sw
    assert sw["#01162F"]["name"] == "Deep Navy"
    assert sw["#FFFFFF"]["not_brand"] is True
    # A flagged / dropped swatch drops out of the recomputed usage map.
    roles = out["color"]["usage_ratios"]["roles"]
    assert "#01162F" in roles.get("primary", {}).get("hexes", [])
    assert "#FFFFFF" not in roles.get("neutral", {}).get("hexes", [])  # flagged not_brand


def test_swatch_op_no_match_is_not_applied():
    out, applied = E.apply_edits(_synth(), [{"op": "swatch_drop", "hex": "#123456"}])
    assert applied == 0
    assert len(out["color"]["swatches"]) == 3


def test_apply_edits_handles_missing_synth():
    out, applied = E.apply_edits(None, [{"op": "set_field", "field": "tagline", "value": "x"}])
    assert applied == 1 and out["tagline"] == "x"


# ── logo candidate guard ──────────────────────────────────────────────────────
def test_pick_logo_candidate():
    census = {"logo_candidates": [
        {"url": "https://x.com/logo.png", "source": "og_image", "score": 9},
        {"url": "https://x.com/fav.ico", "source": "favicon", "score": 2},
    ]}
    assert E.pick_logo_candidate(census, "https://x.com/logo.png")["source"] == "og_image"
    assert E.pick_logo_candidate(census, "https://x.com/other.png") is None
    assert E.pick_logo_candidate(census, "") is None
    assert E.pick_logo_candidate({}, "https://x.com/logo.png") is None


# ── download path resolution ──────────────────────────────────────────────────
def test_resolve_render_path():
    guide = {
        "storage_path": "c/brand-guide/g-client.pdf",
        "renders": {
            "internal": {"storage_path": "c/brand-guide/g-internal.pdf"},
            "client": {"storage_path": "c/brand-guide/g-client.pdf"},
        },
    }
    assert E.resolve_render_path(guide, "internal") == "c/brand-guide/g-internal.pdf"
    assert E.resolve_render_path(guide, "client") == "c/brand-guide/g-client.pdf"
    assert E.resolve_render_path(guide, "bogus") is None
    # Client falls back to the top-level mirror when renders is absent.
    assert E.resolve_render_path({"storage_path": "top.pdf"}, "client") == "top.pdf"
    assert E.resolve_render_path({"storage_path": "top.pdf"}, "internal") is None


# ── suggest-only voice text (§4.8) ────────────────────────────────────────────
def test_build_voice_suggestion_text():
    text = E.build_voice_suggestion_text(_synth())
    assert "Positioning: Old positioning" in text
    assert "Tagline: Old tagline" in text
    assert "Headline: Old headline" in text
    assert "We say:" in text and "Key messages:" in text
    assert "Boilerplate (short): Short bp" in text


def test_build_voice_suggestion_text_empty():
    assert E.build_voice_suggestion_text({}) == ""
    assert E.build_voice_suggestion_text(None) == ""
