"""Dataclasses for M6 site architecture generation (PRD §7.11)."""

from dataclasses import dataclass, field


@dataclass
class ArticleInput:
    """One planned article (a `clusters` row) the architecture organizes. This is
    what the pillar's silo "links down to"; the architecture step never re-plans
    it (PRD §7.11)."""
    id: str
    name: str
    primary_keyword: str
    intent: str
    # Existing peer links set by the orchestrator / cross-topic dedup (cluster
    # ids). Seeds the lateral-link assembly (PRD §7.11 "prioritizing the
    # peer_article_links already set").
    peer_article_links: list[str] = field(default_factory=list)


@dataclass
class PillarInput:
    """One silo with its planned articles — the unit the LLM writes a pillar for.
    Only silos that have at least one article become pillars (a childless pillar
    has nothing to link down to)."""
    topic_id: str
    silo_name: str
    rationale: str
    relationship_type: str
    articles: list[ArticleInput]


@dataclass
class Pillar:
    """A pillar overview page (PRD §7.11). Editorial fields come from the LLM;
    the links are assembled deterministically so the §15.2 acceptance rules hold by
    construction. `supporting_article_ids` are the pillar's outbound DOWN-LINKS
    (capped at the most-central children — NOT the full child set, which is
    recoverable from each article's `parent_pillar_topic_id`); `lateral_pillar_links`
    are peer pillars. Down + lateral ≤ 5 (the per-page internal-link budget)."""
    topic_id: str
    silo_name: str
    title: str
    target_keyword: str
    summary: str
    h2_outline: list[str]
    supporting_article_ids: list[str]
    lateral_pillar_links: list[str]  # peer topic_ids (cosine > threshold)
    degraded: bool = False

    def to_json(self) -> dict:
        return {
            "topic_id": self.topic_id,
            "silo_name": self.silo_name,
            "title": self.title,
            "target_keyword": self.target_keyword,
            "summary": self.summary,
            "h2_outline": self.h2_outline,
            "supporting_article_ids": self.supporting_article_ids,
            "lateral_pillar_links": self.lateral_pillar_links,
            "degraded": self.degraded,
        }


@dataclass
class SupportingArticle:
    """A supporting article node in the site map. `parent_pillar_topic_id` is the
    mandatory up-link; `lateral_article_links` are 2-3 peer articles."""
    article_id: str
    name: str
    intent: str
    parent_pillar_topic_id: str
    lateral_article_links: list[str]

    def to_json(self) -> dict:
        return {
            "article_id": self.article_id,
            "name": self.name,
            "intent": self.intent,
            "parent_pillar_topic_id": self.parent_pillar_topic_id,
            "lateral_article_links": self.lateral_article_links,
        }


@dataclass
class ArchitectureResult:
    seed_keyword: str
    detected_audience: str
    pillars: list[Pillar] = field(default_factory=list)
    supporting_articles: list[SupportingArticle] = field(default_factory=list)
    # silos that had no articles, so no pillar was created (PRD §7.11 builds
    # pillars only where there's something to link down to).
    skipped_silos: list[str] = field(default_factory=list)

    def architecture_json(self) -> dict:
        """The full structure stored in site_architecture.architecture_json."""
        return {
            "seed_keyword": self.seed_keyword,
            "detected_audience": self.detected_audience,
            "pillars": [p.to_json() for p in self.pillars],
            "supporting_articles": [a.to_json() for a in self.supporting_articles],
            "skipped_silos": self.skipped_silos,
            # Persisted so the owner Debug view can show it without recomputing.
            "link_health": self.link_health(),
        }

    def counts(self) -> dict[str, int]:
        return {
            "pillars": len(self.pillars),
            "supporting_articles": len(self.supporting_articles),
            "degraded_pillars": sum(1 for p in self.pillars if p.degraded),
            "skipped_silos": len(self.skipped_silos),
        }

    def link_health(self) -> dict[str, int]:
        """Audit the assembled link graph (§15.2 #3), so the no-orphan / no-dangling
        invariants are checked on every live run rather than only by the unit tests
        + the "by construction" argument:

        - `orphan_articles` — supporting articles with NO inbound link. Should be 0:
          the within-silo article cycle gives every article an inbound (its
          predecessor's successor edge), and small silos also get a pillar down-link.
        - `orphan_pillars` — pillars with no inbound. Should be 0: a pillar always
          receives up-links from its (≥1) articles.
        - `dangling_links` — link targets that aren't real nodes (e.g. a cross-silo
          `peer_article_link` pointing at a dropped/skipped cluster). Should be 0.

        A non-zero count is a regression signal — the caller logs a warning."""
        article_ids = {a.article_id for a in self.supporting_articles}
        pillar_ids = {p.topic_id for p in self.pillars}
        nodes = article_ids | pillar_ids
        inbound: set[str] = set()
        dangling = 0
        for p in self.pillars:
            for aid in p.supporting_article_ids:  # pillar -> article down-links
                inbound.add(aid)
                if aid not in nodes:
                    dangling += 1
            for tid in p.lateral_pillar_links:  # pillar -> pillar laterals
                inbound.add(tid)
                if tid not in nodes:
                    dangling += 1
        for a in self.supporting_articles:
            inbound.add(a.parent_pillar_topic_id)  # article -> pillar up-link
            if a.parent_pillar_topic_id not in nodes:
                dangling += 1
            for lid in a.lateral_article_links:  # article -> article laterals
                inbound.add(lid)
                if lid not in nodes:
                    dangling += 1
        return {
            "orphan_articles": sum(1 for aid in article_ids if aid not in inbound),
            "orphan_pillars": sum(1 for pid in pillar_ids if pid not in inbound),
            "dangling_links": dangling,
        }
