"""Pipeline data models for silo discovery (M2)."""

from enum import Enum

from pydantic import BaseModel, Field


class RelationshipType(str, Enum):
    property_or_mechanism = "property_or_mechanism"
    use_case = "use_case"
    effect_or_outcome = "effect_or_outcome"
    practical_commercial = "practical_commercial"
    research_or_trial = "research_or_trial"
    broader_class = "broader_class"
    peer_entity = "peer_entity"


# relationship_types the LLM is allowed to propose. peer_entity is filtered out
# before display; broader_class is allowed but flagged (PRD §5.1).
PROPOSABLE_TYPES = {t for t in RelationshipType if t is not RelationshipType.peer_entity}


class GroundingResult(BaseModel):
    """Output of the pre-discovery grounding pass (PRD §7.1.1 / §7.1.2)."""

    summary: str = ""
    subject_category: str | None = None
    detected_audience: str | None = None
    is_ambiguous: bool = False
    interpretations: list[str] = Field(default_factory=list)
    # Seed nicknames/abbreviations and peer/competitor entities, used by the
    # generic peer-entity filter in the relevance gate (§5.1, §7.6).
    aliases: list[str] = Field(default_factory=list)
    peer_entities: list[str] = Field(default_factory=list)


class ProposedSilo(BaseModel):
    """A silo proposed by the LLM or asserted by the user (PRD §7.1.3)."""

    name: str
    rationale: str = ""
    relationship_type: RelationshipType = RelationshipType.property_or_mechanism
    supporting_evidence: str | None = None
    is_broader_class: bool = False


class SiloDiscoveryResult(BaseModel):
    """The outcome the API returns after running silo discovery."""

    detected_audience: str | None = None
    needs_disambiguation: bool = False
    interpretations: list[str] = Field(default_factory=list)
    silos: list[ProposedSilo] = Field(default_factory=list)
    # Human-readable degraded-mode notes surfaced to the UI (PRD §16.2).
    degraded_notes: list[str] = Field(default_factory=list)
    # Per-seed peer-entity filter inputs (seed nicknames + competitor entities).
    aliases: list[str] = Field(default_factory=list)
    peer_entities: list[str] = Field(default_factory=list)
