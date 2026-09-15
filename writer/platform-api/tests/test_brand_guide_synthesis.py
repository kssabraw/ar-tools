"""Unit tests for the Phase-2 synthesis orchestration.

Pure helpers (pull_assets / corpus / sanitizers / usage / assemble) are tested
directly; the two LLM calls are mocked and the module flags are monkeypatched so
`run_synthesis_for_guide` runs end-to-end offline — asserting the regulated
`awaiting_signoff` gate, the non-regulated `done` path, the disabled short-circuit,
and best-effort degradation when a call fails.
"""

from __future__ import annotations

import pytest

from services import brand_guide_synthesis as S


# ---------------------------------------------------------------------------
# pull_assets (§4.4)
# ---------------------------------------------------------------------------
class TestPullAssets:
    def test_reads_converged_assets(self):
        client = {
            "name": "Nova Life",
            "website_url": "https://nova.example",
            "brand_voice": {"raw_text": "Confident, clinical, precise."},
            "detected_icp": {"raw_text": "Biohackers aged 30-50."},
            "differentiators": [{"claim": "Third-party tested", "mechanism": "COA per batch"}],
            "voice_card": {"card": {"brand_name": "Nova", "never_use_terms": ["cheap"]}},
            "logo_url": "https://nova.example/logo.svg",
        }
        a = S.pull_assets(client)
        assert a["business_name"] == "Nova Life"
        assert "Confident, clinical" in a["brand_voice_text"]
        assert "Biohackers" in a["icp_text"]
        assert a["voice_card"]["brand_name"] == "Nova"
        assert a["differentiators"][0]["claim"] == "Third-party tested"
        assert a["logo_url"] == "https://nova.example/logo.svg"

    def test_gbp_logo_fallback_and_empty(self):
        a = S.pull_assets({"gbp": {"logo": "https://x/g.png"}})
        assert a["logo_url"] == "https://x/g.png"
        empty = S.pull_assets({})
        assert empty["brand_voice_text"] == "" and empty["logo_url"] is None
        assert empty["differentiators"] == []

    def test_tolerates_garbage(self):
        assert S.pull_assets(None)["business_name"] == ""


# ---------------------------------------------------------------------------
# corpus builder
# ---------------------------------------------------------------------------
class TestCorpus:
    def test_assembles_sections(self):
        assets = {
            "business_name": "Nova", "website": "https://n.example",
            "brand_voice_text": "Confident.", "icp_text": "Biohackers.",
            "differentiators": [{"claim": "Tested", "mechanism": "COA"}],
        }
        captured = {"pages": [{"dom_digest": {"title": "Nova — Peptides", "h1": "Research peptides", "meta_description": ""}}]}
        corpus = S.build_synthesis_corpus(assets, captured)
        assert "Business: Nova" in corpus
        assert "Nova — Peptides" in corpus and "Research peptides" in corpus
        assert "BRAND VOICE ON FILE" in corpus and "Confident." in corpus
        assert "AUDIENCE (ICP) ON FILE" in corpus
        assert "Tested (mechanism: COA)" in corpus

    def test_empty_captured(self):
        assert S.build_synthesis_corpus({"business_name": "X"}, None) == "Business: X"


# ---------------------------------------------------------------------------
# sanitizers
# ---------------------------------------------------------------------------
CENSUS = {
    "colors": [
        {"hex": "#1a2b6d", "css_hex": "#1a2b6d", "share": 0.6, "source": "both", "hsl": [230, 61, 26]},
        {"hex": "#e63946", "css_hex": None, "share": 0.2, "source": "pixel", "hsl": [355, 78, 56]},
    ],
    "type_scale": [{"px": 48, "count": 3}, {"px": 16, "count": 40}],
}


class TestSanitizeNaming:
    def test_anchors_to_census_and_drops_invented_hex(self):
        raw = {
            "swatches": [
                {"hex": "#1a2b6d", "name": "Midnight Navy", "role": "primary"},
                {"hex": "#e63946", "name": "Signal Red", "role": "accent"},
                {"hex": "#00ff00", "name": "Invented", "role": "primary"},  # not in census → ignored
            ],
            "type_scale": [{"px": 48, "name": "H1", "usage": "headlines"}],
            "iconography": "line icons",
            "tagline_options": ["Peptides, perfected", "  "],
        }
        out = S.sanitize_naming(raw, CENSUS)
        hexes = [s["hex"] for s in out["swatches"]]
        assert hexes == ["#1a2b6d", "#e63946"]  # census order, invented dropped
        assert out["swatches"][0]["name"] == "Midnight Navy" and out["swatches"][0]["role"] == "primary"
        assert out["swatches"][0]["is_recommendation"] is False
        # type scale: LLM-named where matched, positional fallback otherwise.
        assert out["type_scale"][0]["name"] == "H1"
        assert out["type_scale"][1]["name"] == "H1" or out["type_scale"][1]["name"]  # positional fallback present
        assert out["tagline_options"] == ["Peptides, perfected"]

    def test_invalid_role_becomes_other(self):
        out = S.sanitize_naming({"swatches": [{"hex": "#1a2b6d", "name": "N", "role": "zzz"}]}, CENSUS)
        assert out["swatches"][0]["role"] == "other"

    def test_empty_census_yields_no_swatches(self):
        out = S.sanitize_naming({"swatches": [{"hex": "#1a2b6d", "name": "N", "role": "primary"}]}, {})
        assert out["swatches"] == []


class TestSanitizeMessaging:
    def test_caps_and_shapes(self):
        raw = {
            "positioning_statement": "For biohackers who want tested peptides.",
            "tagline": "Peptides, perfected",
            "voice_examples": {"headline": "H", "cta": "Shop", "product_blurb": "", "email_opener": "Hi"},
            "we_say_we_dont": [{"we_say": "research-grade", "we_dont": "miracle"}] * 20,
            "key_messages": [f"m{i}" for i in range(20)],
            "boilerplate": {"short": "s", "long": "l"},
            "section_gaps": [{"section": "color", "gap": "consolidate grays"}],
        }
        out = S.sanitize_messaging(raw)
        assert out["positioning_statement"].startswith("For biohackers")
        assert "product_blurb" not in out["voice_examples"]  # empty dropped
        assert len(out["we_say_we_dont"]) == S._MAX_WE_SAY
        assert len(out["key_messages"]) == S._MAX_KEY_MESSAGES
        assert out["boilerplate"] == {"short": "s", "long": "l"}
        assert out["section_gaps"][0]["section"] == "color"

    def test_empty_boilerplate_dropped(self):
        out = S.sanitize_messaging({"positioning_statement": "x", "boilerplate": {"short": "", "long": ""}})
        assert out["boilerplate"] == {}


class TestUsageRatios:
    def test_groups_by_role(self):
        swatches = [
            {"hex": "#1", "role": "primary"}, {"hex": "#2", "role": "secondary"},
            {"hex": "#3", "role": "accent"}, {"hex": "#4", "role": "other"},
        ]
        r = S.usage_ratios_from_roles(swatches)
        assert r["roles"]["primary"]["hexes"] == ["#1"]
        assert r["roles"]["primary"]["share"] == "~60%"
        assert r["roles"]["accent"]["share"] == "~10%"
        assert "other" in r["roles"]  # present but no fixed ratio


class TestAssemble:
    def test_none_when_nothing(self):
        assert S.assemble_synthesized(None, None, coherence_flags=[], pairings=[], provenance={}) is None

    def test_deterministic_only_still_assembles(self):
        out = S.assemble_synthesized(
            None, None, coherence_flags=[{"code": "neutral_sprawl"}], pairings=[], provenance={"x": 1}
        )
        assert out is not None and out["coherence"]["flags"]

    def test_merges_both_halves(self):
        naming = {"swatches": [{"hex": "#1a2b6d", "role": "primary", "name": "Navy"}],
                  "tagline_options": ["A", "B"], "type_scale": [{"px": 48, "name": "H1"}],
                  "imagery_direction": {"subjects": "labs"}, "iconography": "line"}
        messaging = {"tagline": "Final tag", "positioning_statement": "pos", "palette_usage": "60/30/10",
                     "voice_examples": {"headline": "H"}, "coherence_narrative": "reads premium"}
        out = S.assemble_synthesized(
            naming, messaging, coherence_flags=[{"code": "x"}],
            pairings=[{"background": "#1a2b6d"}], provenance={"regulated": False},
        )
        assert out["tagline"] == "Final tag"  # messaging wins over the naming option
        assert out["color"]["swatches"][0]["name"] == "Navy"
        assert out["color"]["usage_ratios"]["roles"]["primary"]["hexes"] == ["#1a2b6d"]
        assert out["color"]["pairings"][0]["background"] == "#1a2b6d"
        assert out["coherence"]["narrative"] == "reads premium"

    def test_tagline_falls_back_to_naming_option(self):
        out = S.assemble_synthesized(
            {"tagline_options": ["Only option"]}, {"positioning_statement": "p"},
            coherence_flags=[], pairings=[], provenance={},
        )
        assert out["tagline"] == "Only option"


# ---------------------------------------------------------------------------
# run_synthesis_for_guide (orchestration, LLM mocked)
# ---------------------------------------------------------------------------
@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(S.settings, "brand_guide_enabled", True)
    monkeypatch.setattr(S.settings, "brand_guide_synthesis_enabled", True)


def _mock_calls(monkeypatch, naming=None, messaging=None):
    async def _n(user):
        return naming

    async def _m(user):
        return messaging

    monkeypatch.setattr(S, "_run_naming", _n)
    monkeypatch.setattr(S, "_run_messaging", _m)


NAMING = {"swatches": [{"hex": "#1a2b6d", "name": "Navy", "role": "primary"}]}
MESSAGING = {"positioning_statement": "For biohackers.", "tagline": "Perfected"}


class TestRunSynthesis:
    async def test_disabled_short_circuits(self, monkeypatch):
        monkeypatch.setattr(S.settings, "brand_guide_enabled", False)
        synth, note, status = await S.run_synthesis_for_guide({}, census=CENSUS)
        assert synth is None and status == "done" and "disabled" in note

    async def test_non_regulated_done_with_synthesized(self, enabled, monkeypatch):
        _mock_calls(monkeypatch, NAMING, MESSAGING)
        client = {"name": "Nova", "content_compliance_mode": "off"}
        synth, note, status = await S.run_synthesis_for_guide(client, census=CENSUS, vibe_read=None, captured=None)
        assert status == "done" and synth is not None
        assert synth["positioning_statement"] == "For biohackers."
        assert synth["color"]["swatches"][0]["name"] == "Navy"
        assert note == "synthesis complete"
        assert synth["provenance"]["regulated"] is False

    async def test_regulated_awaiting_signoff(self, enabled, monkeypatch):
        _mock_calls(monkeypatch, NAMING, MESSAGING)
        client = {"name": "Nova", "content_compliance_mode": "peptide",
                  "brand_voice": {"raw_text": "Our peptides boost recovery. We sound clinical."}}
        synth, note, status = await S.run_synthesis_for_guide(client, census=CENSUS)
        assert status == "awaiting_signoff" and synth is not None
        assert synth["provenance"]["regulated"] is True
        # the claim sentence was excised from the corpus before synthesis
        assert synth["provenance"]["excised_sentences"] >= 1
        assert "sign-off" in note

    async def test_partial_when_messaging_fails(self, enabled, monkeypatch):
        _mock_calls(monkeypatch, NAMING, None)  # messaging returned nothing
        synth, note, status = await S.run_synthesis_for_guide({"content_compliance_mode": "off"}, census=CENSUS)
        assert synth is not None and "partial" in note
        assert synth["color"]["swatches"]  # naming survived
        assert synth["provenance"]["messaging_ok"] is False

    async def test_both_fail_but_coherence_survives(self, enabled, monkeypatch):
        _mock_calls(monkeypatch, None, None)
        # A census that trips a coherence flag → deterministic layer still stored.
        census = {"colors": [{"hex": f"#{i:02x}{i:02x}{i:02x}", "rgb": [i, i, i], "hsl": [0, 2, 40]} for i in range(5)],
                  "fonts": [], "type_scale": []}
        synth, note, status = await S.run_synthesis_for_guide({"content_compliance_mode": "off"}, census=census)
        assert synth is not None and synth["coherence"]["flags"]
        assert status == "done"

    async def test_both_fail_empty_census_returns_none(self, enabled, monkeypatch):
        _mock_calls(monkeypatch, None, None)
        synth, note, status = await S.run_synthesis_for_guide(
            {"content_compliance_mode": "off"}, census={"colors": [], "fonts": [], "type_scale": []}
        )
        assert synth is None and status == "done"
