"""Unit tests for the ecommerce public-spec auto-research module.

Pure + offline — no network, no Anthropic. Covers the public/vendor safety
line, the researched-fact validation/dedupe, the authoritative prompt block,
the gap-focus extraction, and the gap safety-net filter.
Run with `pytest writer/nlp-api/tests/` or `python -m pytest`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ecommerce_facts as ef  # noqa: E402


# --- classify_gap: the public/vendor safety line ---------------------------

def test_classify_public_specs():
    for missing in [
        "CAS number for retatrutide",
        "Molecular weight (~4859.5 Da) and molecular formula",
        "Amino acid sequence and sequence length",
        "Solubility data (e.g. solubility in water or DMSO)",
        "Post-reconstitution stability window",
        "Recommended diluent and reconstitution volume",
    ]:
        assert ef.classify_gap({"category": "Molecular specifications", "missing": missing}) == "public"


def test_classify_store_specs():
    for cat, missing in [
        ("Pricing — variant breakdown", "Exact price for the 30mg vial"),
        ("Third-party laboratory", "Name and ISO 17025 accreditation of the testing lab"),
        ("Shipping details", "Delivery timeframe (ships within 1-2 business days)"),
        ("Returns and guarantee", "Explicit returns/refund policy"),
        ("Review data", "Customer review count and average rating"),
    ]:
        assert ef.classify_gap({"category": cat, "missing": missing}) == "store"


def test_classify_ambiguous_defaults_store():
    # No clear public signal -> gate to the user (never auto-research).
    assert ef.classify_gap({"category": "Extras", "missing": "Anything else worth adding"}) == "store"
    assert ef.classify_gap({}) == "store"
    # A vendor hint beats a public hint (a lab's stability CoA is still vendor).
    mixed = {"category": "Stability", "missing": "stability per your certificate of analysis (CoA)"}
    assert ef.classify_gap(mixed) == "store"


def test_public_gap_labels_dedupes_and_filters():
    gaps = [
        {"category": "Molecular specifications", "missing": "CAS number"},
        {"category": "Molecular specifications", "missing": "cas number"},  # dup (case)
        {"category": "Pricing", "missing": "Exact price for 30mg"},          # store -> excluded
        {"category": "Solubility", "missing": "Solubility in DMSO"},
    ]
    labels = ef.public_gap_labels(gaps)
    assert labels == ["CAS number", "Solubility in DMSO"]


# --- parse_researched_facts: validation + dedupe ---------------------------

def _fact(**kw):
    base = {"field": "CAS number", "value": "2381089-83-2",
            "source_url": "https://pubchem.ncbi.nlm.nih.gov/compound/x", "confidence": "high"}
    base.update(kw)
    return base


def test_parse_keeps_valid_high_medium():
    facts = ef.parse_researched_facts([
        _fact(),
        _fact(field="Molecular weight", value="4731.32", unit="Da", confidence="medium"),
    ])
    assert [f["field"] for f in facts] == ["CAS number", "Molecular weight"]
    assert facts[1]["unit"] == "Da"


def test_parse_drops_low_confidence_and_missing_source():
    facts = ef.parse_researched_facts([
        _fact(confidence="low"),                       # low -> dropped
        _fact(field="Formula", source_url=""),          # no source -> dropped
        _fact(field="Seq", value=""),                   # no value -> dropped
        _fact(field="Bad", source_url="ftp://x/y"),     # non-http -> dropped
    ])
    assert facts == []


def test_parse_dedupes_by_field_first_wins():
    facts = ef.parse_researched_facts([
        _fact(value="2381089-83-2"),
        _fact(value="9999-99-9", confidence="medium"),  # same field -> dropped
    ])
    assert len(facts) == 1
    assert facts[0]["value"] == "2381089-83-2"


def test_parse_caps_count():
    many = [_fact(field=f"spec {i}") for i in range(30)]
    assert len(ef.parse_researched_facts(many)) == ef._MAX_FACTS


def test_parse_handles_junk():
    assert ef.parse_researched_facts(None) == []
    assert ef.parse_researched_facts(["not a dict", 5, {}]) == []


# --- render_researched_facts_block ------------------------------------------

def test_render_empty_is_blank():
    assert ef.render_researched_facts_block([]) == ""


def test_render_block_has_values_and_sources():
    block = ef.render_researched_facts_block(ef.parse_researched_facts([
        _fact(source_name="PubChem"),
        _fact(field="Molecular weight", value="4731.32", unit="Da", source_name="DrugBank"),
    ]))
    assert "VERIFIED PUBLIC SPECIFICATIONS" in block
    assert "CONTENT_GAPS_REPORT" in block  # instructs the writer not to gap these
    assert "2381089-83-2" in block
    assert "4731.32 Da" in block           # unit appended when not already present
    assert "PubChem" in block and "DrugBank" in block
    assert "https://pubchem" in block


def test_render_no_double_unit():
    block = ef.render_researched_facts_block(ef.parse_researched_facts([
        _fact(field="Molecular weight", value="4731.32 Da", unit="Da"),
    ]))
    assert block.count("Da") == 1


# --- build_research_user_prompt --------------------------------------------

def test_user_prompt_includes_entity_and_focus():
    p = ef.build_research_user_prompt("retatrutide", "product", focus=["CAS number", "Solubility"])
    assert "retatrutide" in p
    assert "CAS number" in p and "Solubility" in p


def test_user_prompt_without_focus():
    p = ef.build_research_user_prompt("retatrutide", "product")
    assert "retatrutide" in p
    assert "Prioritise" not in p


# --- filter_researched_gaps: safety net ------------------------------------

def test_filter_drops_covered_public_gaps_keeps_store():
    facts = ef.parse_researched_facts([_fact(field="CAS number"), _fact(field="Molecular weight", value="4731")])
    gaps = [
        {"category": "Molecular specifications", "missing": "CAS number for retatrutide"},   # covered -> drop
        {"category": "Pricing", "missing": "Exact price for the 30mg vial"},                  # store -> keep
        {"category": "Solubility", "missing": "Solubility in DMSO"},                          # public, uncovered -> keep
    ]
    kept = ef.filter_researched_gaps(gaps, facts)
    kept_missing = [g["missing"] for g in kept]
    assert "CAS number for retatrutide" not in kept_missing
    assert "Exact price for the 30mg vial" in kept_missing
    assert "Solubility in DMSO" in kept_missing


def test_filter_no_facts_is_identity():
    gaps = [{"category": "Pricing", "missing": "price"}]
    assert ef.filter_researched_gaps(gaps, []) == gaps
