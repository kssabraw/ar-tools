"""Unit tests for services.content_compliance — the regulated-content guardrail.

Pure detector tests: real excerpts from the peptide blog posts that triggered
the guardrail (human dosing, branded-drug equivalence, guaranteed results,
advocacy) must produce critical findings, and the false-positive guards
(descriptive trial doses, safe medical advice, drug-vs-drug education, product
specs, non-medical CTAs) must NOT block.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from services import content_compliance as cc

PEPTIDE = "peptide"


def _cats(result) -> set[str]:
    return {f.category for f in result.findings if f.severity == "critical"}


# ---------------------------------------------------------------------------
# human dosing — must block
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Most MOTS-c protocols use 5-10 mg per week, split across two to three injections.",
    "A weight-based starting estimate of 0.05 mg per kilogram per injection is used.",
    "How to reconstitute a 10mg MOTS-c vial with bacteriostatic water.",
    "Where should I inject MOTS-c peptide? Inject subcutaneously into the abdomen.",
    "Retatrutide titration schedule: 2mg to 12mg every 4 weeks.",  # dose range
    "Follow a loading phase, then move to a maintenance dose.",     # imperative regimen
    "Your starting dose is 250 mcg, taken daily.",
    "Take 500 mcg of BPC-157 each morning.",
    "You can stack BPC-157 with TB-500 for faster recovery.",
    "Doses escalate from 0.5 mg to 12 mg over the cycle.",          # dose range
])
def test_human_dosing_blocks(text):
    result = cc.scan_text(text, PEPTIDE)
    assert not result.passed, text
    assert "human_dosing" in _cats(result), text


@pytest.mark.parametrize("text", [
    # Educational dosing *vocabulary* with no reader-directed amount, range, or
    # how-to: surfaced as a warning for review, but not blocked.
    "The drug uses a gradual titration to improve tolerability.",
    "Retatrutide follows a dose-escalation approach in trials.",
    "Rodent dosing protocols do not transfer directly to humans.",
])
def test_educational_dosing_vocabulary_warns_not_blocks(text):
    result = cc.scan_text(text, PEPTIDE)
    assert result.passed, text            # no critical → publishable
    assert result.warning_count >= 1, text


@pytest.mark.parametrize("text", [
    # Descriptive trial dose — reported, not directed at a reader.
    "In the TRIUMPH trial, participants received up to 12 mg administered weekly.",
    "Doses studied in the phase 2 trial ranged widely.",
])
def test_descriptive_trial_dose_does_not_block(text):
    result = cc.scan_text(text, PEPTIDE)
    # It may warn, but it must not raise a critical block.
    assert "human_dosing" not in _cats(result), text


def test_dose_per_frequency_is_warning_not_block():
    result = cc.scan_text(
        "The trial used 12 mg per week in the highest arm.", PEPTIDE)
    assert result.passed
    assert result.warning_count >= 1


def test_product_spec_milligrams_do_not_block():
    # A vial size on a product page is a spec, not dosing guidance.
    result = cc.scan_text(
        "Each vial contains 10 mg of lyophilized powder. Store at -20C.", PEPTIDE)
    assert "human_dosing" not in _cats(result)


@pytest.mark.parametrize("text", [
    "Fasting glucose 100–125 mg/dL indicates prediabetes.",   # lab range, not a dose
    "HbA1c correlated with fasting glucose of 100-125 mg/dl.",
    "Vitamin B12 levels of 200-900 pg/mL are normal.",
])
def test_lab_concentration_ranges_do_not_block(text):
    result = cc.scan_text(text, PEPTIDE)
    assert "human_dosing" not in _cats(result), text


def test_injectable_as_adjective_is_not_injection_technique():
    # "the injectable subcutaneous formulation" describes the drug's form; it is
    # not an instruction to inject subcutaneously.
    result = cc.scan_text(
        "Semaglutide is available as an injectable subcutaneous formulation.", PEPTIDE)
    assert "human_dosing" not in _cats(result)


# ---------------------------------------------------------------------------
# branded equivalence — must block
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Our peptide is just as good as Ozempic for weight loss.",
    "This is a cheaper alternative to Mounjaro.",
    "Retatrutide works just like semaglutide but costs less.",
    "A budget version of Wegovy without the price tag.",
    "It delivers the same results as tirzepatide.",
])
def test_branded_equivalence_blocks(text):
    result = cc.scan_text(text, PEPTIDE)
    assert not result.passed, text
    assert "branded_equivalence" in _cats(result), text


def test_negated_guarantee_does_not_block():
    # A disclaimer is the opposite of a guaranteed-results claim.
    for text in (
        "Results aren't guaranteed, and evidence remains limited.",
        "There is no guarantee of results with this compound.",
        "Weight loss is not guaranteed.",
    ):
        result = cc.scan_text(text, PEPTIDE)
        assert "guaranteed_results" not in _cats(result), text


def test_drug_vs_drug_comparison_is_warning_not_block():
    # Educational comparison of two drugs is not a claim about the vendor's product.
    result = cc.scan_text(
        "Clinical trials suggest tirzepatide is more effective than semaglutide "
        "for weight loss.", PEPTIDE)
    assert result.passed  # only a warning
    assert result.warning_count >= 1


def test_generic_inn_is_not_a_knockoff_claim():
    # "generic liraglutide" is a real generic of the INN, not a knockoff of the
    # vendor's product — must not block. "generic Ozempic" (a brand name has no
    # generic) IS a knockoff-positioning claim — must block.
    assert cc.scan_text(
        "The arrival of generic liraglutide changes the cost calculus.", PEPTIDE).passed
    assert not cc.scan_text("Get generic Ozempic for less.", PEPTIDE).passed


def test_bare_alternative_to_brand_warns_not_blocks():
    result = cc.scan_text(
        "This article covers the best alternative to tirzepatide for weight loss.",
        PEPTIDE)
    assert result.passed
    assert result.warning_count >= 1


def test_combining_with_non_compound_is_not_stacking():
    # "combining MOTS-c with regular exercise" — one compound + a non-compound.
    result = cc.scan_text(
        "MOTS-c is complementary — combining exogenous MOTS-c with regular "
        "exercise may help.", PEPTIDE)
    assert "human_dosing" not in {f.category for f in result.findings if f.severity == "critical"}
    # But combining two actual compounds is stacking and blocks.
    assert not cc.scan_text(
        "Consider combining MOTS-c with retatrutide for better results.", PEPTIDE).passed


# ---------------------------------------------------------------------------
# guaranteed results — must block
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Guaranteed results or your money back.",
    "You will lose 20 pounds in your first month.",
    "Clinically proven to melt belly fat.",
    "This peptide will cure your metabolic issues.",
    "Our formula has no side effects and is 100% safe.",
])
def test_guaranteed_results_block(text):
    result = cc.scan_text(text, PEPTIDE)
    assert not result.passed, text
    assert "guaranteed_results" in _cats(result), text


# ---------------------------------------------------------------------------
# advocacy — must block
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "You should try MOTS-c today.",
    "We recommend you take BPC-157 for recovery.",
    "Buy now and start seeing results.",
    "Order yours today.",
    "Start your weight-loss journey with our peptides.",
])
def test_advocacy_blocks(text):
    result = cc.scan_text(text, PEPTIDE)
    assert not result.passed, text
    assert "advocacy" in _cats(result), text


def test_safe_advice_is_not_advocacy():
    # "you should consider talking to a doctor" must not trip advocacy.
    result = cc.scan_text(
        "You should consider talking to a licensed physician before use.", PEPTIDE)
    assert "advocacy" not in _cats(result)


def test_non_medical_cta_does_not_block():
    result = cc.scan_text("Contact us today to learn more about our services.", PEPTIDE)
    assert result.passed


# ---------------------------------------------------------------------------
# clean educational content passes
# ---------------------------------------------------------------------------
def test_educational_mechanism_content_passes():
    text = (
        "MOTS-c is a mitochondrial-derived peptide that activates the AMPK "
        "pathway. Research in animal models suggests it may influence fat "
        "oxidation. No large human clinical trial has confirmed these effects, "
        "and it is not approved by the FDA."
    )
    result = cc.scan_text(text, PEPTIDE)
    assert result.passed
    assert result.critical_count == 0


# ---------------------------------------------------------------------------
# mode scoping
# ---------------------------------------------------------------------------
def test_off_mode_never_flags():
    text = "Take 500 mcg of BPC-157 daily; it's just as good as Ozempic."
    result = cc.scan_text(text, "off")
    assert result.passed
    assert result.findings == []


def test_unknown_mode_reads_as_off():
    result = cc.scan_text("Take 500 mcg daily.", "banana")
    assert result.passed


def test_resolve_mode_and_is_enabled():
    assert cc.resolve_mode({"content_compliance_mode": "peptide"}) == "peptide"
    assert cc.resolve_mode({"content_compliance_mode": "PEPTIDE"}) == "peptide"
    assert cc.resolve_mode({"content_compliance_mode": "off"}) == "off"
    assert cc.resolve_mode({"content_compliance_mode": None}) == "off"
    assert cc.resolve_mode({}) == "off"
    assert cc.resolve_mode(None) == "off"
    assert cc.is_enabled({"content_compliance_mode": "peptide"}) is True
    assert cc.is_enabled({}) is False


# ---------------------------------------------------------------------------
# normalization: HTML + markdown are seen through
# ---------------------------------------------------------------------------
def test_html_and_markdown_are_normalized():
    assert not cc.scan_text("<p>Take <strong>500 mcg</strong> daily.</p>", PEPTIDE).passed
    assert not cc.scan_text("**Reconstitute** the vial with bacteriostatic water.", PEPTIDE).passed


# ---------------------------------------------------------------------------
# evidence is populated
# ---------------------------------------------------------------------------
def test_findings_carry_evidence():
    result = cc.scan_text("Take 500 mcg of BPC-157 each morning.", PEPTIDE)
    assert result.findings
    assert all(f.evidence.strip() for f in result.findings)


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------
def test_assert_publishable_raises_on_critical():
    result = cc.scan_text("Take 500 mcg of BPC-157 daily.", PEPTIDE)
    with pytest.raises(HTTPException) as exc:
        cc.assert_publishable(result)
    assert exc.value.status_code == 409
    assert "content_compliance_violation" in str(exc.value.detail)


def test_assert_publishable_force_bypasses():
    result = cc.scan_text("Take 500 mcg of BPC-157 daily.", PEPTIDE)
    cc.assert_publishable(result, force=True)  # no raise


def test_assert_publishable_warning_only_passes():
    result = cc.scan_text("The trial used 12 mg per week.", PEPTIDE)
    assert result.warning_count >= 1
    cc.assert_publishable(result)  # no raise — warnings don't block


def test_assert_content_publishable_off_client_is_noop():
    # An unregulated client's content is never scanned/blocked.
    res = cc.assert_content_publishable(
        {"content_compliance_mode": "off"},
        title="Take 500 mcg of BPC-157",
        body="Reconstitute with bacteriostatic water.",
    )
    assert res.passed


def test_assert_content_publishable_blocks_regulated_client():
    with pytest.raises(HTTPException):
        cc.assert_content_publishable(
            {"content_compliance_mode": "peptide"},
            title="MOTS-c Dosing Protocol",
            body="Take 500 mcg subcutaneously each day.",
        )
