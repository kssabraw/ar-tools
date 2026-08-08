"""Unit tests for Topic Research coverage tagging (pure logic)."""

from services import keyword_topic_coverage as cov


def test_is_covered_on_shared_topic_tokens():
    card = {"title": "How to Reduce Claims Leakage", "theme": "Claims Leakage"}
    existing = [cov.keyword_research.token_set("reducing claims leakage from to under")]
    assert cov.is_covered(card, existing)


def test_is_covered_false_when_below_overlap():
    card = {"title": "TPA Vendor Selection Criteria", "theme": "TPA Selection"}
    existing = [cov.keyword_research.token_set("reducing claims leakage")]
    assert not cov.is_covered(card, existing)


def test_tag_coverage_labels_and_counts():
    cards = [
        {"title": "How to Reduce Claims Leakage", "theme": "Claims Leakage"},
        {"title": "AI and Drone Technology in CAT Claims", "theme": "Technology"},
        {"title": "TPA Vendor Selection Criteria", "theme": "TPA Selection"},
    ]
    existing = ["reducing claims leakage from to under",
                "ai and drone technology catastrophic claims"]
    tagged, report = cov.tag_coverage(cards, existing)
    tags = {c["title"]: c["coverage"] for c in tagged}
    assert tags["How to Reduce Claims Leakage"] == "covered"
    assert tags["AI and Drone Technology in CAT Claims"] == "covered"
    assert tags["TPA Vendor Selection Criteria"] == "gap"
    assert report == {"gap": 1, "covered": 2}


def test_tag_coverage_all_gap_when_no_existing():
    cards = [{"title": "New Topic", "theme": "Fresh"}]
    tagged, report = cov.tag_coverage(cards, [])
    assert tagged[0]["coverage"] == "gap"
    assert report == {"gap": 1, "covered": 0}


def test_card_tokens_thin_title_never_matches():
    # A single-token title can't reach the 2-token overlap floor.
    assert not cov.is_covered({"title": "Claims", "theme": ""},
                              [cov.keyword_research.token_set("claims management")])
