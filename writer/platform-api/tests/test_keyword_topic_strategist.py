"""Unit tests for the strategist-grade Topic Research layer's pure logic."""

from services import keyword_topic_strategist as ks


def _raw_plan():
    return {
        "assessment": "  Strong in catastrophe, thin on compliance.  ",
        "pillars": [
            {
                "pillar": "Catastrophe Claims",
                "rationale": "client ranks adjacent; competitors cover it",
                "clusters": [
                    {"title": "Cut claims leakage", "buyer_problem": "bp",
                     "search_intent": "Informational", "funnel_stage": "mofu",
                     "target_keywords": ["claims leakage", "reduce leakage"],
                     "questions": ["what causes leakage"], "priority": "High",
                     "rationale": "320 vol, competitor gap"},
                    {"title": "", "buyer_problem": "x"},          # dropped: no title
                ],
            },
            {"pillar": "", "clusters": []},                        # dropped: no pillar
            {"pillar": "Empty pillar", "clusters": []},            # dropped: no clusters
        ],
    }


def test_sanitize_plan_keeps_valid_normalizes_fields():
    plan = ks.sanitize_plan(_raw_plan())
    assert plan["assessment"] == "Strong in catastrophe, thin on compliance."
    assert len(plan["pillars"]) == 1
    cl = plan["pillars"][0]["clusters"]
    assert len(cl) == 1
    assert cl[0]["search_intent"] == "informational"   # lowercased
    assert cl[0]["funnel_stage"] == "MOFU"             # uppercased
    assert cl[0]["priority"] == "high"                 # lowercased


def test_sanitize_plan_defaults_priority_medium():
    raw = {"assessment": "a", "pillars": [{"pillar": "P", "clusters": [
        {"title": "T", "target_keywords": ["k"]}]}]}
    plan = ks.sanitize_plan(raw)
    assert plan["pillars"][0]["clusters"][0]["priority"] == "medium"


def test_flatten_plan_to_cards_enriches_volume_and_carries_metadata():
    plan = ks.sanitize_plan(_raw_plan())
    evidence = {"mined": [{"suggestions": [
        {"keyword": "Claims Leakage", "volume": 320},   # case-insensitive match
        {"keyword": "reduce leakage", "volume": 110},
    ]}]}
    cards = ks.flatten_plan_to_cards(plan, evidence)
    assert len(cards) == 1
    c = cards[0]
    assert c["volume_total"] == 430                     # both enriched from evidence
    assert c["pillar"] == "Catastrophe Claims"
    assert c["priority"] == 0.9 and c["priority_label"] == "high"
    assert c["search_intent"] == "informational" and c["funnel_stage"] == "MOFU"
    assert c["title"] == "Cut claims leakage"


def test_flatten_orders_by_priority():
    plan = {"assessment": "a", "pillars": [{"pillar": "P", "clusters": [
        {"title": "low one", "target_keywords": [], "priority": "low"},
        {"title": "high one", "target_keywords": [], "priority": "high"},
    ]}]}
    cards = ks.flatten_plan_to_cards(plan, {"mined": []})
    assert [c["title"] for c in cards] == ["high one", "low one"]


def test_volume_lookup_takes_max_per_keyword():
    evidence = {"mined": [
        {"suggestions": [{"keyword": "x", "volume": 10}]},
        {"suggestions": [{"keyword": "X", "volume": 90}]},
    ]}
    assert ks._volume_lookup(evidence)["x"] == 90


def test_render_evidence_and_sop_block_are_empty_safe():
    assert isinstance(ks.render_evidence({}), str)
    assert isinstance(ks.content_sop_block(16000), str)
