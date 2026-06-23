"""Dataclasses for M5 article planning (PRD §7.10)."""

from dataclasses import dataclass, field

# The article-intent enum (PRD §13 clusters.intent). Mirrors the DB enum so the
# orchestrator's output can be validated before it ever reaches Postgres.
INTENTS = (
    "informational",
    "commercial",
    "transactional",
    "comparison",
    "navigational",
)
DEFAULT_INTENT = "informational"


@dataclass
class GroupingInput:
    """One §7.9 Louvain grouping, as read back from statistical_clustering_log."""
    id: str
    representative: str
    cohesion: float
    size: int
    keywords: list[str]


@dataclass
class TopicInput:
    """Everything the orchestrator needs for one topic."""
    id: str
    name: str
    rationale: str
    relationship_type: str
    embedding: list[float] | None
    groupings: list[GroupingInput]
    # keyword -> relevance_score (cosine to silo anchor) for the active
    # keywords routed to this topic. Used by orphan promotion to enforce a
    # quality floor; the orchestrator itself doesn't consume scores. Empty
    # dict if the caller didn't supply them (orphan promotion then falls back
    # to its old gate-floor behavior).
    keyword_relevance: dict[str, float] = field(default_factory=dict)


@dataclass
class DroppedKeyword:
    keyword: str
    reason: str


@dataclass
class ArticleRecord:
    """One planned article (becomes a `clusters` row). Keyword references are by
    text at this stage; they're resolved to keyword-row ids at persistence."""
    topic_id: str
    primary_keyword: str
    supporting_keywords: list[str]
    intent: str
    suggested_h2s: list[str]
    source_statistical_grouping_id: str | None
    orchestrator_notes: str
    serp_top_urls: list[str] = field(default_factory=list)
    # Resolved after all clusters are inserted (cross-topic dedup §7.10.4). These
    # are peer keyword *texts* until persistence maps them to cluster ids.
    peer_primary_keywords: list[str] = field(default_factory=list)


@dataclass
class CoverageGapRecord:
    suggested_title: str
    target_keyword: str | None
    rationale: str


@dataclass
class TopicPlan:
    topic_id: str
    articles: list[ArticleRecord] = field(default_factory=list)
    gaps: list[CoverageGapRecord] = field(default_factory=list)
    dropped: list[DroppedKeyword] = field(default_factory=list)
    degraded: bool = False
    log: dict = field(default_factory=dict)


@dataclass
class PlanResult:
    per_topic: list[TopicPlan] = field(default_factory=list)
    degraded_notes: list[str] = field(default_factory=list)
    timed_out: bool = False
    dedup_log: dict = field(default_factory=dict)

    def orchestrator_log(self) -> dict:
        """JSON-serializable form for sessions.orchestrator_log."""
        return {
            "topics": {p.topic_id: p.log for p in self.per_topic},
            "dedup": self.dedup_log,
            "degraded_notes": self.degraded_notes,
            "timed_out": self.timed_out,
        }

    def counts(self) -> dict[str, int]:
        return {
            "articles": sum(len(p.articles) for p in self.per_topic),
            "gaps": sum(len(p.gaps) for p in self.per_topic),
            "dropped": sum(len(p.dropped) for p in self.per_topic),
        }
