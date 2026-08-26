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


def test_select_relevant_site_topics_keeps_verbatim_members_in_order():
    site = ["parcel audit services", "supply chain awards", "carrier negotiation",
            "pros to know"]
    # The LLM returns the on-mission subset (one case-mismatched, one hallucinated).
    returned = ["Parcel Audit Services", "carrier negotiation", "made up topic"]
    kept = top.select_relevant_site_topics(returned, site)
    assert kept == ["parcel audit services", "carrier negotiation"]  # verbatim, discovered order
    assert "supply chain awards" not in kept   # off-mission slug excluded
    assert "made up topic" not in kept         # hallucination rejected


def test_select_relevant_site_topics_empty_inputs():
    assert top.select_relevant_site_topics([], ["a"]) == []
    assert top.select_relevant_site_topics(["a"], []) == []


def test_domain_anchored_requires_shared_seed_token():
    from services import keyword_research as kr
    seed_tokens = set()
    for s in ["third party claims administrator", "catastrophe claims management"]:
        seed_tokens |= kr.token_set(s)
    # shares a seed token → anchored
    assert top.domain_anchored("flood claims expertise", seed_tokens)       # "claim"
    assert top.domain_anchored("catastrophe adjuster deployment", seed_tokens)  # "catastrophe"
    # the real drift case: shares NO seed token → not anchored
    assert not top.domain_anchored("commercial property valuation", seed_tokens)
    # no seeds to anchor against → never gate
    assert top.domain_anchored("anything", set())


def test_clean_expansion_seeds_drops_out_of_domain_seed():
    seeds = ["third party claims administrator", "catastrophe claims management"]
    out = top.clean_expansion_seeds(
        ["flood claims expertise", "commercial property valuation",
         "catastrophe adjuster deployment"],
        seeds, "BSA Claims", cap=10)
    assert "commercial property valuation" not in out   # jumped to real-estate domain
    assert "flood claims expertise" in out
    assert "catastrophe adjuster deployment" in out
