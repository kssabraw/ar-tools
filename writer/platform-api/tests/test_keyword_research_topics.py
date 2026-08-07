"""Unit tests for the Keyword Research topical-research module's pure logic."""

from services import keyword_research_topics as top


def test_slug_to_phrase_dehyphenates_and_trims_digits():
    assert top._slug_to_phrase("third-party-claims-administration") == \
        "third party claims administration"
    assert top._slug_to_phrase("workers_comp_tpa_2024") == "workers comp tpa"


def test_topics_from_urls_takes_specific_slug_drops_generic():
    urls = [
        "https://x.com/services/workers-comp-tpa",
        "https://x.com/blog/2024/01/what-is-a-tpa",
        "https://x.com/about",
        "https://x.com/services/self-insured-employers",
    ]
    topics = top.topics_from_urls(urls, cap=10)
    assert "workers comp tpa" in topics
    assert "self insured employers" in topics
    assert "what is a tpa" in topics       # last meaningful slug, digits dropped
    assert "about" not in topics           # structural segment


def test_topics_from_urls_dedupes_and_caps():
    urls = [f"https://x.com/services/roof-repair" for _ in range(5)] + [
        "https://x.com/services/gutter-cleaning"]
    topics = top.topics_from_urls(urls, cap=1)
    assert topics == ["roof repair"]       # deduped to one, capped at 1


def test_topics_from_urls_skips_pure_numeric_or_empty():
    urls = ["https://x.com/blog/2024", "https://x.com/", "https://x.com/p/12345"]
    assert top.topics_from_urls(urls) == []


def test_build_anchors_combines_in_order_and_dedupes():
    anchors = top.build_anchors(
        ["third party claims administrator"],
        ["workers comp tpa", "Third Party Claims Administrator"],  # dup (case-insensitive)
        ["self insured employers"],
        "Business name: BSA Claims",
    )
    assert anchors == [
        "third party claims administrator",
        "workers comp tpa",
        "self insured employers",
        "Business name: BSA Claims",
    ]


def test_build_anchors_handles_empty_groups():
    assert top.build_anchors(["a"], [], [], None) == ["a"]
