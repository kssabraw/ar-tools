import type { RelationshipType } from "./api";

export const RELATIONSHIP_LABELS: Record<RelationshipType, string> = {
  property_or_mechanism: "Property / mechanism",
  use_case: "Use case",
  effect_or_outcome: "Effect / outcome",
  practical_commercial: "Practical / commercial",
  research_or_trial: "Research / trial",
  broader_class: "Broader class",
  peer_entity: "Peer entity",
};

// Options for the "add custom silo" picker. peer_entity is included because a
// user may assert one (PRD Q17), even though the LLM never proposes it.
export const RELATIONSHIP_OPTIONS = Object.keys(
  RELATIONSHIP_LABELS,
) as RelationshipType[];
