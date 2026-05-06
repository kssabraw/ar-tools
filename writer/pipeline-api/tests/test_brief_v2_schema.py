"""Schema validation tests for Brief Generator v2.0 models.

These tests cover only the typed-model layer - they assert that the
models accept valid v2.0 payloads, reject extras (additionalProperties:
false per PRD §12), and enforce the new field constraints. Pipeline
behavior tests come in later stages.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.brief import (
    BriefMetadata,
    BriefRequest,
    BriefResponse,
    DiscardedHeading,
    FAQItem,
    HeadingItem,
    PersonaInfo,
    SiloCandidate,
    SiloSourceHeading,
)


# ---- BriefRequest ----

def test_brief_request_minimum_valid():
    req = BriefRequest(run_id="r1", keyword="what is tiktok shop")
    assert req.location_code == 2840
    assert req.client_id is None
    assert req.force_refresh is False
    assert req.intent_override is None


def test_brief_request_with_client_and_refresh():
    req = BriefRequest(
        run_id="r1",
        keyword="what is tiktok shop",
        client_id="11111111-1111-1111-1111-111111111111",
        force_refresh=True,
    )
    assert req.client_id == "11111111-1111-1111-1111-111111111111"
    assert req.force_refresh is True


def test_brief_request_rejects_extras():
    with pytest.raises(ValidationError):
        BriefRequest(run_id="r1", keyword="x", unexpected="boom")


def test_brief_request_rejects_long_keyword():
    with pytest.raises(ValidationError):
        BriefRequest(run_id="r1", keyword="x" * 151)


def test_brief_request_rejects_empty_keyword():
    with pytest.raises(ValidationError):
        BriefRequest(run_id="r1", keyword="")


# ---- HeadingItem ----

def test_heading_item_carries_v2_fields():
    h = HeadingItem(
        level="H2",
        text="What TikTok Shop Is",
        type="content",
        source="serp",
        title_relevance=0.71,
        information_gain_score=0.30,
        heading_priority=0.62,
        region_id="region_3",
        scope_classification="in_scope",
        order=2,
    )
    assert h.title_relevance == 0.71
    assert h.region_id == "region_3"
    assert h.scope_classification == "in_scope"


def test_heading_item_rejects_legacy_semantic_score_field():
    with pytest.raises(ValidationError):
        HeadingItem(
            level="H2",
            text="x",
            type="content",
            source="serp",
            semantic_score=0.5,  # v1.7 field, removed in v2.0
        )


def test_heading_item_accepts_persona_gap_source():
    h = HeadingItem(
        level="H2",
        text="How does the algorithm decide what to show me",
        type="content",
        source="persona_gap",
    )
    assert h.source == "persona_gap"


def test_heading_item_rejects_unknown_scope_classification():
    with pytest.raises(ValidationError):
        HeadingItem(
            level="H2",
            text="x",
            type="content",
            source="serp",
            scope_classification="not-a-real-value",  # type: ignore[arg-type]
        )


# ---- DiscardedHeading ----

@pytest.mark.parametrize("reason", [
    "below_relevance_floor",
    "above_restatement_ceiling",
    "region_off_topic",
    "region_restates_title",
    "below_priority_threshold",
    "global_cap_exceeded",
    "duplicate",
    "low_cluster_coherence",
    "scope_verification_out_of_scope",
])
def test_discard_reasons_v2(reason):
    d = DiscardedHeading(
        text="x",
        source="serp",
        title_relevance=0.5,
        discard_reason=reason,  # type: ignore[arg-type]
    )
    assert d.discard_reason == reason


def test_legacy_v1_discard_reasons_rejected():
    for legacy in [
        "below_semantic_threshold",
        "semantic_duplicate_of_higher_priority_h2",
        "definitional_restatement",
        "too_short_after_sanitization",
    ]:
        with pytest.raises(ValidationError):
            DiscardedHeading(
                text="x",
                source="serp",
                discard_reason=legacy,  # type: ignore[arg-type]
            )


# ---- FAQItem ----

def test_faq_persona_gap_source_allowed():
    f = FAQItem(question="Does it cost money?", source="persona_gap", faq_score=0.6)
    assert f.source == "persona_gap"


def test_faq_unknown_source_rejected():
    with pytest.raises(ValidationError):
        FAQItem(question="x", source="autocomplete", faq_score=0.6)  # type: ignore[arg-type]


# ---- SiloCandidate ----

def test_silo_routed_from_required():
    silo = SiloCandidate(
        suggested_keyword="tiktok shop algorithm tactics",
        cluster_coherence_score=0.72,
        review_recommended=False,
        recommended_intent="how-to",
        routed_from="scope_verification",
        source_headings=[
            SiloSourceHeading(
                text="How to optimize for the TikTok Shop algorithm",
                source="serp",
                title_relevance=0.74,
                heading_priority=0.65,
                discard_reason="scope_verification_out_of_scope",
            )
        ],
    )
    assert silo.routed_from == "scope_verification"
    assert silo.source_headings[0].discard_reason == "scope_verification_out_of_scope"


def test_silo_routed_from_must_be_known_value():
    with pytest.raises(ValidationError):
        SiloCandidate(
            suggested_keyword="x",
            cluster_coherence_score=0.7,
            recommended_intent="informational",
            routed_from="random",  # type: ignore[arg-type]
        )


# ---- PersonaInfo ----

def test_persona_info_defaults():
    p = PersonaInfo()
    assert p.description == ""
    assert p.background_assumptions == []
    assert p.primary_goal == ""


def test_persona_info_rejects_extras():
    with pytest.raises(ValidationError):
        PersonaInfo(description="x", brand_voice="warm")


# ---- BriefMetadata ----

def test_metadata_defaults_match_prd_thresholds():
    m = BriefMetadata()
    assert m.embedding_model == "text-embedding-3-large"
    assert m.relevance_floor_threshold == 0.55
    assert m.restatement_ceiling_threshold == 0.78
    assert m.inter_heading_threshold == 0.75
    assert m.edge_threshold == 0.65
    assert m.mmr_lambda == 0.7
    # Step 8.6 thresholds - PRD v2.2 / Phase 2 raised the floor 0.60 → 0.65.
    assert m.parent_relevance_floor_threshold == 0.65
    assert m.parent_restatement_ceiling_threshold == 0.85
    assert m.inter_h3_threshold == 0.78
    # v2.4 lowered the singleton silo demand threshold 0.30 → 0.15
    # because the original cluster-tuned threshold was rejecting nearly
    # every singleton candidate, leaving production with zero silos.
    assert m.silo_search_demand_threshold == 0.15
    assert m.h3_count_average == 0.0
    assert m.h2s_with_zero_h3s == 0
    assert m.silo_candidates_rejected_by_discard_reason == 0
    assert m.silo_candidates_rejected_by_search_demand == 0
    assert m.silo_candidates_rejected_by_viability_check == 0
    assert m.silo_viability_fallback_applied is False
    assert m.schema_version == "2.6"


def test_heading_item_carries_step_8_6_fields():
    h = HeadingItem(
        level="H3",
        text="Setup process",
        type="content",
        source="serp",
        parent_h2_text="How TikTok Shop Works",
        parent_relevance=0.72,
    )
    assert h.parent_h2_text == "How TikTok Shop Works"
    assert h.parent_relevance == 0.72


@pytest.mark.parametrize("reason", [
    "h3_below_parent_relevance_floor",
    "h3_above_parent_restatement_ceiling",
    "displaced_by_authority_gap_h3",
])
def test_step_8_6_discard_reasons_accepted(reason):
    d = DiscardedHeading(
        text="x",
        source="serp",
        discard_reason=reason,  # type: ignore[arg-type]
    )
    assert d.discard_reason == reason


def test_silo_candidate_carries_step_12_fields():
    s = SiloCandidate(
        suggested_keyword="tiktok shop algorithm tactics",
        cluster_coherence_score=0.72,
        review_recommended=False,
        recommended_intent="how-to",
        routed_from="scope_verification",
        discard_reason_breakdown={"scope_verification_out_of_scope": 1},
        search_demand_score=0.55,
        viable_as_standalone_article=True,
        viability_reasoning="Distinct intent vs the parent definitional brief",
        estimated_intent="how-to",
        cross_brief_occurrence_count=1,
    )
    assert s.discard_reason_breakdown == {"scope_verification_out_of_scope": 1}
    assert s.search_demand_score == 0.55
    assert s.viable_as_standalone_article is True
    assert s.viability_reasoning.startswith("Distinct intent")
    assert s.estimated_intent == "how-to"
    assert s.cross_brief_occurrence_count == 1


def test_silo_candidate_defaults_for_step_12_fields():
    s = SiloCandidate(
        suggested_keyword="x",
        recommended_intent="informational",
        routed_from="non_selected_region",
    )
    assert s.discard_reason_breakdown == {}
    assert s.search_demand_score == 0.0
    assert s.viable_as_standalone_article is True
    assert s.viability_reasoning == ""
    assert s.estimated_intent == "informational"
    assert s.cross_brief_occurrence_count == 1


def test_metadata_rejects_legacy_fields():
    # Fields that lived on v1.7/v1.8 metadata but are removed in v2.0
    for legacy in [
        "semantic_filter_threshold",
        "semantic_dedup_threshold",
        "semantic_dedup_collapses_count",
        "soft_cluster_pairs_examined",
        "spin_off_articles_count",
    ]:
        with pytest.raises(ValidationError):
            BriefMetadata(**{legacy: 0})


def test_metadata_embedding_model_locked_to_large():
    # Pydantic Literal enforces this - small no longer accepted.
    with pytest.raises(ValidationError):
        BriefMetadata(embedding_model="text-embedding-3-small")  # type: ignore[arg-type]


# ---- BriefResponse - full envelope ----

def _minimal_response() -> BriefResponse:
    return BriefResponse(
        keyword="what is tiktok shop",
        title="What TikTok Shop Is and How It Works in 2026",
        scope_statement=(
            "Defines TikTok Shop, explains how the system functions for "
            "both sellers and buyers, and orients readers to the major "
            "components of the platform. Does not cover advanced seller "
            "tactics, algorithm optimization, or inventory management."
        ),
        title_rationale="Top SERP titles converge on definitional framing.",
        intent_type="informational",
        intent_confidence=0.92,
        metadata=BriefMetadata(),
    )


def test_brief_response_minimum_valid():
    r = _minimal_response()
    assert r.title.startswith("What TikTok Shop Is")
    assert r.metadata.schema_version == "2.6"
    assert r.persona.description == ""
    assert r.heading_structure == []


def test_brief_response_requires_title_and_scope():
    with pytest.raises(ValidationError):
        BriefResponse(
            keyword="x",
            intent_type="informational",
            metadata=BriefMetadata(),
        )


def test_brief_response_rejects_legacy_spin_off_articles():
    with pytest.raises(ValidationError):
        BriefResponse(
            keyword="x",
            title="t",
            scope_statement="s",
            intent_type="informational",
            metadata=BriefMetadata(),
            spin_off_articles=[],  # v1.8 field, removed in v2.0
        )


def test_brief_response_serializes_round_trip():
    r = _minimal_response()
    r.heading_structure.append(HeadingItem(
        level="H2",
        text="How TikTok Shop Works",
        type="content",
        source="serp",
        title_relevance=0.71,
        region_id="region_1",
        scope_classification="in_scope",
        order=1,
    ))
    payload = r.model_dump()
    parsed = BriefResponse.model_validate(payload)
    assert parsed.heading_structure[0].region_id == "region_1"
    assert parsed.metadata.schema_version == "2.6"
