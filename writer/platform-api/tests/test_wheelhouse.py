"""Unit tests for the WheelHouse IT page poster — pure logic only.

No network: the LLM generation, Supabase writes, and WordPress calls are not
exercised here. Covers the field schema integrity, validation, supplied-vs-
generated merge, slug/title composition, and the zero-write dry-run path.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
    # Variadic → serves any depth (2-level city page).
    assert wp.build_slug_path("florida", "miami") == "/florida/miami/"


def test_city_title_and_dispatch():
    assert wg.compose_city_title("Miami") == "Miami IT Support Company"
    assert wg.title_for("city", "Florida", "Miami", "ignored") == "Miami IT Support Company"
    assert wg.title_for("service", "Florida", "Miami", "Managed IT") == "Managed IT in Miami, FL"


def test_local_seo_title_and_generation():
    # A local SEO page is 3-level (/city/<leaf>/); the leaf (carried in `service`)
    # names it and IS the WP title.
    assert wg.title_for("local_seo", "Florida", "Miami", "IT Support Boca Raton") == "IT Support Boca Raton"
    assert wg.title_for("local_seo", "Florida", "Miami", "  ") == "IT Support"
    good = {n: "word word word" for n in wf.GENERATED_FIELD_NAMES}
    with patch.object(wg.report_llm, "run_forced_tool", new=AsyncMock(return_value=good)):
        res = asyncio.run(wg.generate_fields(
            state="Florida", city="Miami", service="IT Support Boca Raton", page_type="local_seo"))
    assert res["title"] == "IT Support Boca Raton"
    assert res["generation_failed"] is False


# The distinctive injected-block headers (bare "CLIENT BRAND VOICE" / "TARGET
# AUDIENCE" also appear in the RULES line, so tests key on the full header).
_VOICE_HEADER = "CLIENT BRAND VOICE (authoritative"
_ICP_HEADER = "TARGET AUDIENCE / ICP (write for"


def test_strip_em_dashes_unicode_and_entities():
    assert wf.strip_em_dashes("fast—reliable IT") == "fast-reliable IT"
    assert wf.strip_em_dashes("a – b") == "a - b"                     # en dash
    assert wf.strip_em_dashes("x&mdash;y &#8212; z &#x2014; w") == "x-y - z - w"
    assert wf.strip_em_dashes("plain hyphen - stays") == "plain hyphen - stays"
    assert wf.strip_em_dashes("") == ""


def test_merge_supplied_strips_em_dashes_from_generated_only():
    generated = {n: "word word word" for n in wf.GENERATED_FIELD_NAMES}
    generated["hero_headline"] = "Fast—reliable IT support"          # generated → stripped
    supplied = {"hero_body": "We keep it — verbatim"}                # user text → kept
    acf, sources = wf.merge_supplied(generated, supplied)
    assert "—" not in acf["hero_headline"] and acf["hero_headline"] == "Fast-reliable IT support"
    assert "—" in acf["hero_body"]                                   # supplied dash untouched
    assert sources["hero_body"] == "supplied"


def test_generated_acf_has_no_em_dashes_end_to_end():
    good = {n: "clean copy here" for n in wf.GENERATED_FIELD_NAMES}
    good["valueband_body"] = "<p>Downtime hurts—we fix it.</p>"
    with patch.object(wg.report_llm, "run_forced_tool", new=AsyncMock(return_value=good)):
        res = asyncio.run(wg.generate_fields(state="Florida", city="Miami", service="Managed IT"))
    assert all("—" not in v for v in res["acf"].values() if isinstance(v, str))


def test_system_prompt_forbids_em_dashes():
    assert "em-dashes" in wg.build_system().lower() or "em-dash" in wg.build_system().lower()


def test_build_system_injects_client_voice_and_icp():
    sys_prompt = wg.build_system(
        brand_voice="Warm, plainspoken, no jargon.",
        icp="IT directors at 50-200 seat law firms who hate downtime.",
    )
    assert _VOICE_HEADER in sys_prompt
    assert "Warm, plainspoken, no jargon." in sys_prompt
    assert _ICP_HEADER in sys_prompt
    assert "law firms" in sys_prompt
    # The client's real voice replaces the static fallback line.
    assert f"VOICE: {wf.GLOBAL_VOICE}" not in sys_prompt
    # Hard proof points are always present.
    assert "BRAND FACTS" in sys_prompt


def test_build_system_falls_back_to_static_voice_when_absent():
    sys_prompt = wg.build_system()
    assert f"VOICE: {wf.GLOBAL_VOICE}" in sys_prompt
    assert _VOICE_HEADER not in sys_prompt
    assert _ICP_HEADER not in sys_prompt
    assert "BRAND FACTS" in sys_prompt


def test_build_system_clips_overlong_assets():
    long_voice = "START" + "v" * (wg._BRAND_VOICE_CHAR_CAP + 500) + "VOICE_END"
    long_icp = "BEGIN" + "i" * (wg._ICP_CHAR_CAP + 500) + "ICP_END"
    sys_prompt = wg.build_system(brand_voice=long_voice, icp=long_icp)
    # Heads survive, tails are dropped past the cap, an ellipsis marks the cut.
    assert "START" in sys_prompt and "VOICE_END" not in sys_prompt
    assert "BEGIN" in sys_prompt and "ICP_END" not in sys_prompt
    assert "…" in sys_prompt


def test_generate_fields_threads_voice_icp_into_system_prompt():
    good = {n: "word word word" for n in wf.GENERATED_FIELD_NAMES}
    mock = AsyncMock(return_value=good)
    with patch.object(wg.report_llm, "run_forced_tool", new=mock):
        asyncio.run(wg.generate_fields(
            state="Florida", city="Miami", service="Managed IT",
            brand_voice="Warm, plainspoken.", icp="Law-firm IT directors.",
        ))
    system = mock.await_args.kwargs["system"]
    assert "CLIENT BRAND VOICE" in system and "Warm, plainspoken." in system
    assert "TARGET AUDIENCE / ICP" in system and "Law-firm IT directors." in system


def test_generate_fields_city_uses_fixed_service_and_title():
    good = {n: "word word word" for n in wf.GENERATED_FIELD_NAMES}
    with patch.object(wg.report_llm, "run_forced_tool", new=AsyncMock(return_value=good)):
        res = asyncio.run(wg.generate_fields(
            state="Florida", city="Miami", service="", page_type="city"))
    assert res["title"] == "Miami IT Support Company"
    assert res["generation_failed"] is False


# ── dry-run makes zero writes and needs no WP config ─────────────────────────

def test_acf_write_ok_detects_dropped_payload():
    # Sent content but WP echoed no acf → the field group isn't REST-exposed.
    assert wp.acf_write_ok({"hero_headline": "x"}, {"hero_headline": "x"}) is True
    assert wp.acf_write_ok({"hero_headline": "x"}, None) is False
    assert wp.acf_write_ok({"hero_headline": "x"}, {}) is False
    # Sent nothing meaningful → nothing to drop, always ok.
    assert wp.acf_write_ok({"a": "", "b": "  "}, None) is True
    assert wp.acf_write_ok({}, None) is True


def test_merge_edit_sources_preserves_provenance():
    prev_acf = {"hero_headline": "Old H", "hero_body": "<p>b</p>"}
    prev_sources = {"hero_headline": "generated", "hero_body": "generated"}
    new_acf = {"hero_headline": "Old H", "hero_body": "<p>changed</p>", "switch_headline": "Brand new"}
    out = wf.merge_edit_sources(new_acf, prev_acf, prev_sources)
    assert out["hero_headline"] == "generated"   # unchanged → keep provenance
    assert out["hero_body"] == "supplied"        # changed → supplied
    assert out["switch_headline"] == "supplied"  # newly filled → supplied
    assert out["valueband_eyebrow"] == "generated"  # empty, no prior → generated
    assert set(out.keys()) == set(wf.FIELD_NAMES)


def test_generate_fields_flags_failure_and_keeps_defaults():
    # Empty LLM return → generation_failed True, but the 33-field shape + link
    # defaults still assemble (never a hard crash).
    with patch.object(wg.report_llm, "run_forced_tool", new=AsyncMock(return_value={})):
        res = asyncio.run(wg.generate_fields(state="Florida", city="Miami", service="Managed IT"))
    assert res["generation_failed"] is True
    assert set(res["acf"].keys()) == set(wf.FIELD_NAMES)
    assert res["acf"]["otherservices_link_01"] == "IT Consulting"


def test_generate_fields_success_not_flagged():
    good = {n: "word word word" for n in wf.GENERATED_FIELD_NAMES}
    with patch.object(wg.report_llm, "run_forced_tool", new=AsyncMock(return_value=good)):
        res = asyncio.run(wg.generate_fields(state="Florida", city="Miami", service="Managed IT"))
    assert res["generation_failed"] is False


def test_generate_fields_reraises_transient_swallows_terminal():
    class Boom(Exception):
        pass

    # Transient exhaustion → propagate (so a mass job can be re-queued).
    with patch.object(wg.report_llm, "run_forced_tool", new=AsyncMock(side_effect=Boom())), \
         patch.object(wg.report_llm, "is_transient_llm_error", return_value=True):
        try:
            asyncio.run(wg.generate_fields(state="Florida", city="Miami", service="Managed IT"))
            raise AssertionError("expected transient error to propagate")
        except Boom:
            pass

    # Terminal error → swallowed, degrades to an empty flagged draft.
    with patch.object(wg.report_llm, "run_forced_tool", new=AsyncMock(side_effect=Boom())), \
         patch.object(wg.report_llm, "is_transient_llm_error", return_value=False):
        res = asyncio.run(wg.generate_fields(state="Florida", city="Miami", service="Managed IT"))
    assert res["generation_failed"] is True


def _levels(*parts):
    return [{"slug": wp.slugify(p), "title": p} for p in parts]


def test_dry_run_zero_writes_without_config_service():
    client = {"id": "c1"}  # no wordpress_* creds → lookups skipped, no network
    out = asyncio.run(wp.dry_run_hierarchy(
        client=client, levels=_levels("Florida", "Miami", "Managed IT"),
        acf={"hero_headline": "x"}, status="draft",
    ))
    assert out["writes"] == 0
    assert out["parents_resolved"] is False
    assert out["slug_path"] == "/florida/miami/managed-it/"
    assert out["leaf_payload"]["slug"] == "managed-it"
    assert out["leaf_payload"]["acf"] == {"hero_headline": "x"}
    assert out["chain"][0]["parent"] == 0
    assert len(out["chain"]) == 3


def test_dry_run_zero_writes_city_two_level():
    client = {"id": "c1"}
    out = asyncio.run(wp.dry_run_hierarchy(
        client=client, levels=_levels("Florida", "Miami"),
        acf={"hero_headline": "y"}, status="draft",
    ))
    assert out["writes"] == 0
    assert out["slug_path"] == "/florida/miami/"
    assert out["leaf_payload"]["slug"] == "miami"
    assert len(out["chain"]) == 2
    assert out["chain"][0]["parent"] == 0
