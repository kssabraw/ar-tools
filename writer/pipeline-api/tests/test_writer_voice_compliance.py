"""Unit tests for modules.writer.voice_compliance.

Pure + offline. These are the checks that make "the article follows the brand
guide" a verifiable statement rather than a hope: banned terms are already
hard-enforced elsewhere, and these cover the two ways a guide was being ignored
without anyone noticing — grammatical person and preferred phrasing.
"""

from models.writer import BrandVoiceCard
from modules.writer import voice_compliance as vc


FIRST_PERSON_BODY = " ".join(["We restore roofs and our crew protects the home."] * 25)
THIRD_PERSON_BODY = " ".join(["Acme Roofing restores tile roofs in Melbourne."] * 30)


# --- check_person ----------------------------------------------------------

def test_person_check_is_silent_when_the_guide_is_silent():
    assert vc.check_person(THIRD_PERSON_BODY, "") is None
    assert vc.check_person(THIRD_PERSON_BODY, "plural") is None


def test_person_first_flags_a_third_person_article():
    finding = vc.check_person(THIRD_PERSON_BODY, "first")
    assert finding is not None
    assert finding["check"] == "person"
    assert finding["severity"] == "warning"
    assert "first person" in finding["message"]


def test_person_first_passes_a_first_person_article():
    assert vc.check_person(FIRST_PERSON_BODY, "first") is None


def test_person_third_flags_a_we_heavy_article():
    finding = vc.check_person(FIRST_PERSON_BODY, "third")
    assert finding is not None
    assert "third person" in finding["message"]


def test_person_third_passes_a_third_person_article():
    assert vc.check_person(THIRD_PERSON_BODY, "third") is None


def test_person_check_skipped_on_short_text():
    """Density over 20 words is noise. A check that fires on noise gets ignored."""
    assert vc.check_person("Acme restores roofs.", "first") is None


def test_person_check_tolerates_occasional_we_in_a_third_person_article():
    """One "our" in 300 words is not a guide violation."""
    body = THIRD_PERSON_BODY + " Our team is licensed."
    assert vc.check_person(body, "third") is None


# --- check_preferred_terms -------------------------------------------------

def test_preferred_terms_all_present():
    assert vc.check_preferred_terms("We offer roof restoration today.", ["roof restoration"]) is None


def test_preferred_terms_missing_is_reported():
    finding = vc.check_preferred_terms("We offer roof repair.", ["roof restoration", "Colorbond"])
    assert finding["check"] == "preferred_terms"
    assert finding["severity"] == "warning"
    assert finding["terms"] == ["roof restoration", "Colorbond"]


def test_preferred_terms_matching_is_word_boundaried():
    assert vc.check_preferred_terms("restoration work", ["restore"]) is not None
    assert vc.check_preferred_terms("we restore roofs", ["restore"]) is None


def test_preferred_terms_empty_list_is_a_no_op():
    assert vc.check_preferred_terms("anything", []) is None
    assert vc.check_preferred_terms("anything", None) is None


# --- check_article ---------------------------------------------------------

class _Section:
    def __init__(self, heading, body):
        self.heading = heading
        self.body = body


def test_check_article_without_a_card_reports_nothing():
    assert vc.check_article(THIRD_PERSON_BODY, None) == []


def test_check_article_with_empty_text_reports_nothing():
    assert vc.check_article("", BrandVoiceCard(person="first")) == []


def test_check_article_collects_every_finding():
    card = BrandVoiceCard(person="first", preferred_terms=["Colorbond"])
    findings = vc.check_article(THIRD_PERSON_BODY, card)
    assert {f["check"] for f in findings} == {"person", "preferred_terms"}
    assert all(f["severity"] == "warning" for f in findings)


def test_check_article_clean_when_the_guide_is_followed():
    card = BrandVoiceCard(person="first", preferred_terms=["roofs"])
    assert vc.check_article(FIRST_PERSON_BODY, card) == []


# --- article_text ----------------------------------------------------------

def test_article_text_includes_title_headings_and_bodies():
    text = vc.article_text("The Title", [_Section("A Heading", "Some body.")])
    assert "The Title" in text
    assert "A Heading" in text
    assert "Some body." in text


def test_article_text_skips_empty_parts():
    text = vc.article_text("", [_Section("", ""), _Section("H", "B")])
    assert text == "H\nB"


def test_article_text_handles_no_sections():
    assert vc.article_text("Title", []) == "Title"
    assert vc.article_text("Title", None) == "Title"
