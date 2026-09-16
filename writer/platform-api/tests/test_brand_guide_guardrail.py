"""Unit tests for the Phase-2 regulated claim-shape input-filter (pure).

The filter excises claim-shape sentences from the synthesis corpus BEFORE
synthesis, but ONLY for a regulated client (`content_compliance_mode != 'off'`).
For an ordinary client it is a no-op (the universal prompt hygiene carries the
weight there). Reuses `content_compliance` for the marketing/dosing shapes and
adds the broader efficacy-verb + health-outcome net.
"""

from __future__ import annotations

from services import brand_guide_guardrail as GD


class TestSplitSentences:
    def test_splits_on_punct_and_newlines(self):
        assert GD.split_sentences("A big claim. Another one!\nA third line") == [
            "A big claim.", "Another one!", "A third line",
        ]

    def test_empty(self):
        assert GD.split_sentences("") == []
        assert GD.split_sentences("   \n  ") == []


class TestClaimShape:
    def test_efficacy_plus_health_outcome_hits(self):
        assert GD.claim_shape_reason("This peptide supports muscle recovery.") == "efficacy_health_claim"
        assert GD.claim_shape_reason("It reduces inflammation and boosts energy.") == "efficacy_health_claim"

    def test_clinical_signal_hits_alone(self):
        assert GD.claim_shape_reason("Clinically proven results.") == "clinical_claim"
        assert GD.claim_shape_reason("Shown to work in trials.") == "clinical_claim"

    def test_efficacy_verb_without_health_outcome_is_safe(self):
        # A plumber / SaaS voice line — efficacy verb, no health object → not a claim.
        assert GD.claim_shape_reason("We support local homeowners.") is None
        assert GD.claim_shape_reason("Boost your brand's visibility.") is None

    def test_plain_brand_line_is_safe(self):
        assert GD.claim_shape_reason("Bold, clinical, and modern.") is None


class TestSentenceExciseReason:
    def test_dosing_caught_via_content_compliance(self):
        reason = GD.sentence_excise_reason("Reconstitute with bacteriostatic water before use.", "peptide")
        assert reason is not None and reason.startswith("compliance:")

    def test_brand_line_kept(self):
        assert GD.sentence_excise_reason("Our voice is confident and precise.", "peptide") is None


class TestFilterCorpus:
    CORPUS = (
        "Nova is a modern peptide brand.\n"
        "Our peptides support muscle recovery and boost energy.\n"
        "We speak with a clinical, confident tone.\n"
        "Reconstitute with bacteriostatic water.\n"
        "The palette is navy and electric violet."
    )

    def test_off_mode_is_noop(self):
        filtered, excised = GD.filter_synthesis_corpus(self.CORPUS, "off")
        assert filtered == self.CORPUS and excised == []

    def test_unknown_mode_is_noop(self):
        filtered, excised = GD.filter_synthesis_corpus(self.CORPUS, "")
        assert filtered == self.CORPUS and excised == []

    def test_regulated_excises_claim_sentences_keeps_brand(self):
        filtered, excised = GD.filter_synthesis_corpus(self.CORPUS, "peptide")
        # The two claim-shape sentences are gone; the three brand/visual lines stay.
        assert "support muscle recovery" not in filtered
        assert "bacteriostatic" not in filtered
        assert "modern peptide brand" in filtered
        assert "clinical, confident tone" in filtered
        assert "navy and electric violet" in filtered
        reasons = {e["reason"] for e in excised}
        assert "efficacy_health_claim" in reasons
        assert any(r.startswith("compliance:") for r in reasons)
        assert len(excised) == 2

    def test_empty_corpus(self):
        assert GD.filter_synthesis_corpus("", "peptide") == ("", [])
