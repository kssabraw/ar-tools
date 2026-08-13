"""Unit tests for the WheelHouse IT page poster — pure logic only.

No network: the LLM generation, Supabase writes, and WordPress calls are not
exercised here. Covers the field schema integrity, validation, supplied-vs-
generated merge, slug/title composition, and the zero-write dry-run path.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import wheelhouse_fields as wf  # noqa: E402
from services import wheelhouse_generate as wg  # noqa: E402
from services import wheelhouse_pages as wp  # noqa: E402


# The 33 ACF field names, in ACF group order (from the field-group export).
_EXPECTED_FIELDS = [
    "hero_headline", "hero_body",
    "valueband_eyebrow", "valueband_headline", "valueband_body",
    "diff_eyebrow", "diff_headline", "diff_intro",
    "diff_item_1_title", "diff_item_1_body", "diff_item_2_title", "diff_item_2_body",
    "diff_item_3_title", "diff_item_3_body", "diff_item_4_title", "diff_item_4_body",
    "industry_headline",
    "security_eyebrow", "security_headline", "security_body",
    "switch_headline", "switch_intro",
    "otherservices_eyebrow", "otherservices_headline", "otherservices_intro",
    "otherservices_link_01", "otherservices_link_02", "otherservices_link_03",
    "otherservices_link_04", "otherservices_link_05", "otherservices_link_06",
    "otherservices_link_07", "otherservices_link_08",
]


# ── field schema integrity ───────────────────────────────────────────────────

def test_field_schema_matches_acf_export():
    assert wf.FIELD_NAMES == _EXPECTED_FIELDS
    assert len(wf.FIELD_SPEC) == 33
    # 25 generated + 8 canonical link fields.
    assert len(wf.GENERATED_FIELD_NAMES) == 25
    assert len(wf.LINK_FIELD_NAMES) == 8
    assert wf.LINK_FIELD_NAMES == [f"otherservices_link_{i:02d}" for i in range(1, 9)]


def test_canonical_link_defaults():
    defaults = wf.default_link_fields()
    assert defaults["otherservices_link_01"] == "IT Consulting"
    assert defaults["otherservices_link_08"] == "Cloud Services"
    assert len(defaults) == 8


def test_generation_schema_excludes_links_and_supplied():
    schema = wf.generation_schema()
    props = schema["properties"]
    # Link fields never generated.
    assert "otherservices_link_01" not in props
    # All 25 generated fields present + required.
    assert len(props) == 25
    assert set(schema["required"]) == set(props.keys())
    # Excluding a supplied field drops it from the schema.
    trimmed = wf.generation_schema(exclude={"hero_headline"})
    assert "hero_headline" not in trimmed["properties"]
    assert len(trimmed["properties"]) == 24


# ── text helpers ─────────────────────────────────────────────────────────────

def test_strip_html_and_word_count():
    assert wf.strip_html("<p>Managed IT in <b>Miami</b></p>") == "Managed IT in Miami"
    assert wf.word_count("<p>one two three</p>", is_html=True) == 3
    assert wf.word_count("one two three four") == 4
    assert wf.word_count("") == 0


def test_coerce_wysiwyg_wraps_plain_text():
    assert wf.coerce_wysiwyg("<p>already html</p>") == "<p>already html</p>"
    assert wf.coerce_wysiwyg("para one\n\npara two") == "<p>para one</p><p>para two</p>"
    assert wf.coerce_wysiwyg("single line") == "<p>single line</p>"
    assert wf.coerce_wysiwyg("") == ""


# ── validation (warn, don't fail) ────────────────────────────────────────────

def test_validate_flags_short_long_empty():
    acf = {name: "" for name in wf.FIELD_NAMES}
    acf["hero_headline"] = "Too short"          # 2 words, min 6 → short
    acf["diff_eyebrow"] = "one two three four five six"  # 6 words, max 5 → long
    warnings = {w["field"]: w["issue"] for w in wf.validate_fields(acf)}
    assert warnings["hero_headline"] == "short"
    assert warnings["diff_eyebrow"] == "long"
    assert warnings["hero_body"] == "empty"


def test_validate_passes_in_range():
    acf = {name: "" for name in wf.FIELD_NAMES}
    acf["hero_headline"] = "Managed IT Support Services in Miami Florida"  # 7 words (6–9)
    hits = [w for w in wf.validate_fields(acf) if w["field"] == "hero_headline"]
    assert hits == []


# ── merge (supplied precedence + sources) ────────────────────────────────────

def test_merge_supplied_precedence_and_sources():
    generated = {"hero_headline": "Generated headline here", "hero_body": "Body text para"}
    supplied = {"hero_headline": "Supplied wins"}
    acf, sources = wf.merge_supplied(generated, supplied)
    assert acf["hero_headline"] == "Supplied wins"
    assert sources["hero_headline"] == "supplied"
    assert sources["hero_body"] == "generated"
    # wysiwyg generated value is coerced to HTML.
    assert acf["hero_body"] == "<p>Body text para</p>"
    # Link fields fall back to canonical defaults.
    assert acf["otherservices_link_02"] == "Managed IT"
    assert sources["otherservices_link_02"] == "default"
    # Every field present.
    assert set(acf.keys()) == set(wf.FIELD_NAMES)


# ── title + slug composition ─────────────────────────────────────────────────

def test_state_abbrev_and_title():
    assert wg.state_abbrev("Florida") == "FL"
    assert wg.state_abbrev("fl") == "FL"
    assert wg.state_abbrev("Nowhere") is None
    assert wg.compose_title("Florida", "Miami", "Managed IT") == "Managed IT in Miami, FL"
    # Unknown state → city only, no dangling comma.
    assert wg.compose_title("Atlantis", "Rapture", "Cybersecurity") == "Cybersecurity in Rapture"


def test_slugify_and_slug_path():
    assert wp.slugify("Managed IT") == "managed-it"
    assert wp.slugify("St. Petersburg") == "st-petersburg"
    assert wp.build_slug_path("florida", "miami", "managed-it") == "/florida/miami/managed-it/"


# ── dry-run makes zero writes and needs no WP config ─────────────────────────

def test_dry_run_zero_writes_without_config():
    client = {"id": "c1"}  # no wordpress_* creds → lookups skipped, no network
    out = asyncio.run(wp.dry_run_leaf(
        client=client, state="Florida", city="Miami", service="Managed IT",
        title="Managed IT in Miami, FL", acf={"hero_headline": "x"}, status="draft",
    ))
    assert out["writes"] == 0
    assert out["parents_resolved"] is False
    assert out["slug_path"] == "/florida/miami/managed-it/"
    assert out["leaf_payload"]["slug"] == "managed-it"
    assert out["leaf_payload"]["acf"] == {"hero_headline": "x"}
    assert out["chain"]["state"]["parent"] == 0
