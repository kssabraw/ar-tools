"""Unit tests for the navigational + competitor-brand filter (pure logic)."""

from services import keyword_research_navigational as nav

_BSA_COMPETITORS = [
    {"name": "Sedgwick Claims Management Services", "domain": "sedgwick.com"},
    {"name": "Gold Star Adjusters", "domain": "goldstaradjusters.com"},
    {"name": "First Coast Claim Consultants", "domain": "firstcoastclaims.com"},
    {"name": "Cedrick Jones & Associates Public Insurance Adjusters Firm LLC", "domain": None},
    {"name": "Florida Best Public Adjusters Jacksonville", "domain": "flbestpublicadjusters.com"},
]


def test_navigational_catches_support_lookups_any_brand():
    # The exact keywords that leaked through on the live buyer-seed run — caught
    # regardless of whether the brand is a registered competitor.
    assert nav.is_navigational("sedgwick phone number")
    assert nav.is_navigational("gallagher bassett phone number")       # not registered
    assert nav.is_navigational("progressive insurance claims phone number")
    assert nav.is_navigational("sedgwick login")
    assert nav.is_navigational("check claim status")


def test_navigational_leaves_content_keywords():
    assert not nav.is_navigational("claims management services")
    assert not nav.is_navigational("what is a third party administrator")
    assert not nav.is_navigational("third party administrator in insurance")
    assert not nav.is_navigational("catastrophe claims management")


def test_brand_matchers_are_distinctive_and_safe():
    m = nav.brand_matchers(_BSA_COMPETITORS)
    # Distinctive brands match; the run's own topic + generic/geo words do not.
    assert nav.is_competitor_brand("what is sedgwick", m)
    assert nav.is_competitor_brand("gold star adjusters reviews", m)
    assert nav.is_competitor_brand("first coast claim consultants", m)
    assert not nav.is_competitor_brand("third party administrator in insurance", m)
    assert not nav.is_competitor_brand("florida claims adjuster", m)   # geo, not a matcher
    assert not nav.is_competitor_brand("first notice of loss", m)      # not the "first coast" phrase


def test_competitor_comparison_is_rescued():
    m = nav.brand_matchers(_BSA_COMPETITORS)
    # A challenger WANTS to rank for these — they must survive.
    assert nav.classify_intent("sedgwick alternatives", m) == "keep"
    assert nav.classify_intent("sedgwick vs crawford", m) == "keep"
    assert nav.classify_intent("what is sedgwick", m) == "competitor"


def test_apply_navigational_drops_and_reports():
    m = nav.brand_matchers(_BSA_COMPETITORS)
    rows = [
        {"keyword": "sedgwick phone number"},
        {"keyword": "what is sedgwick"},
        {"keyword": "sedgwick alternatives"},
        {"keyword": "claims management services"},
        {"keyword": "gallagher bassett phone number"},
        {"keyword": "third party administrator"},
    ]
    kept, report = nav.apply_navigational(rows, m)
    kept_kw = {r["keyword"] for r in kept}
    assert kept_kw == {"sedgwick alternatives", "claims management services",
                       "third party administrator"}
    assert report["dropped_navigational"] == 2
    assert report["dropped_competitor"] == 1


def test_competitor_drop_can_be_disabled():
    m = nav.brand_matchers(_BSA_COMPETITORS)
    rows = [{"keyword": "what is sedgwick"}, {"keyword": "sedgwick phone number"}]
    kept, report = nav.apply_navigational(rows, m, drop_competitor=False)
    # Navigational still dropped; the bare competitor lookup is kept.
    assert {r["keyword"] for r in kept} == {"what is sedgwick"}
    assert report["dropped_competitor"] == 0
