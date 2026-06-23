"""Site architecture generation (PRD §7.11, prompt B.3).

The final pipeline step. Each accepted silo (that produced at least one article)
becomes a pillar: a higher-level overview page that links down to a few of its
supporting articles. Everything here is now **deterministic — no LLM** (owner
decision 2026-06-09: the writer module owns all pillar editorial). The pillar's
title + summary are left as a placeholder / empty for the writer; only the SEO
target keyword is derived (the silo's head term). The *linking matrix* is likewise
assembled deterministically so the §15.2 acceptance rules hold by construction:

  1. one pillar per accepted (article-bearing) silo;
  2. every supporting article links up to its pillar (mandatory);
  3. no orphans — every supporting article receives ≥1 inbound link via the
     within-silo article cycle (each article links to a successor), independent of
     how few children the pillar links down to;
  4. pillars link laterally only where topic-embedding cosine > the threshold;
  5. ≤5 outbound internal links per page (owner rule): pillar = ≤3 down-links +
     ≤2 peer pillars; article = 1 up-link + ≤4 laterals.

This mirrors M5's cross-topic dedup, which was likewise made deterministic
(reproducible + testable). Divergence from B.3 (which has the model emit the
editorial fields + link structure) is intentional and flagged. Dropping the
per-pillar Opus call removes its cost, latency, and rate-limit/degradation
handling — a pillar can no longer be 'degraded'.
"""

import logging

import numpy as np

from .models import (
    ArchitectureResult,
    ArticleInput,
    Pillar,
    PillarInput,
    SupportingArticle,
)

logger = logging.getLogger(__name__)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _pillar_content(pillar: PillarInput) -> dict:
    """Deterministic pillar editorial fields — NO LLM (owner decision 2026-06-09:
    the writer module owns all pillar editorial). The title and summary are left as
    a placeholder / empty for the writer to fill at write time; only the SEO target
    keyword is derived deterministically (the silo's head term). Dropping the
    per-pillar Opus call also removes the rate-limit / degradation handling the
    parallel calls needed — a pillar can no longer be 'degraded'."""
    return {
        "title": pillar.silo_name,           # placeholder; the writer titles the pillar
        "target_keyword": pillar.silo_name.lower(),
        "summary": "",                        # writer owns the summary
        "h2_outline": [],                     # writer owns the outline
        "degraded": False,
    }


def _lateral_pillar_links(
    pillar_topic_ids: list[str],
    topic_embeddings: dict[str, list[float] | None],
    threshold: float,
    max_per_pillar: int,
) -> dict[str, list[str]]:
    """topic_id -> peer topic_ids whose topic-embedding cosine exceeds `threshold`
    (PRD §7.11 / §15.2 #4), with each pillar's outbound list capped at the top
    `max_per_pillar` peers by cosine. Silos without an embedding get no links.

    Note: the cap is applied per-pillar, so the resulting graph may be mildly
    asymmetric — A's list can include B while B's top-N omits A if B sits at
    the center of a denser neighborhood. That's the right call: each pillar
    points at its most-related peers, not at every peer above the bar."""
    vecs = {
        tid: np.asarray(topic_embeddings[tid], dtype=np.float32)
        for tid in pillar_topic_ids
        if topic_embeddings.get(tid) is not None
    }
    # First pass: collect (cosine, peer) for every above-threshold pair.
    scored: dict[str, list[tuple[float, str]]] = {tid: [] for tid in pillar_topic_ids}
    ids = list(vecs.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            cos = _cosine(vecs[ids[i]], vecs[ids[j]])
            if cos > threshold:
                scored[ids[i]].append((cos, ids[j]))
                scored[ids[j]].append((cos, ids[i]))
    # Per pillar, keep its top-N peers by cosine (descending). max_per_pillar
    # <= 0 disables the cap (returns every above-threshold peer).
    links: dict[str, list[str]] = {}
    for tid, peers in scored.items():
        peers.sort(reverse=True)
        if max_per_pillar and max_per_pillar > 0:
            peers = peers[:max_per_pillar]
        links[tid] = [pid for _, pid in peers]
    return links


def _pillar_down_links(
    articles: list[ArticleInput],
    cluster_centroids: dict[str, list[float] | None],
    *,
    max_links: int,
) -> list[str]:
    """The pillar's outbound down-links: up to `max_links` of the silo's most
    central articles (nearest the silo's mean cluster centroid), so a big silo no
    longer emits 60+ links. A silo with ≤ max_links articles links to all of them.
    Falls back to article order when centroids are unavailable.

    NOTE: this is the pillar's *link* list, not its membership — the full child set
    is recoverable from each article's `parent_pillar_topic_id`. The articles the
    pillar does not link to still receive an inbound link via the within-silo
    article cycle (see `_lateral_article_links` `successor`), so none are orphaned."""
    ids = [a.id for a in articles]
    if max_links <= 0:
        return []
    if len(ids) <= max_links:
        return ids
    vecs = [
        np.asarray(cluster_centroids[a.id], dtype=np.float32)
        for a in articles
        if cluster_centroids.get(a.id) is not None
    ]
    if not vecs:
        return ids[:max_links]
    mean = np.mean(np.stack(vecs), axis=0)
    scored: list[tuple[float, str]] = []
    for a in articles:
        v = cluster_centroids.get(a.id)
        if v is not None:
            scored.append((_cosine(mean, np.asarray(v, dtype=np.float32)), a.id))
    scored.sort(reverse=True)
    chosen = [aid for _, aid in scored[:max_links]]
    # Articles without a centroid couldn't be scored — pad by order if there's room.
    for aid in ids:
        if len(chosen) >= max_links:
            break
        if aid not in chosen:
            chosen.append(aid)
    return chosen


def _lateral_article_links(
    article: ArticleInput,
    same_silo_ids: set[str],
    cluster_centroids: dict[str, list[float] | None],
    *,
    max_links: int,
    successor: str | None = None,
) -> list[str]:
    """Lateral links to peer supporting articles (PRD §7.11). `successor` is the
    article's within-silo cycle edge: prepended first so every article is some
    peer's successor and therefore receives ≥1 inbound link — the no-orphan
    guarantee now that the pillar links to only a few children. Then the
    orchestrator/dedup `peer_article_links`, then nearest same-silo peers by
    centroid cosine. Capped at `max_links`."""
    chosen: list[str] = []
    seen = {article.id}
    # Coverage edge first: the within-silo successor (the no-orphan guarantee).
    if successor and successor not in seen:
        chosen.append(successor)
        seen.add(successor)
    # Priority: existing peer links (may cross silos — from cross-topic dedup).
    for pid in article.peer_article_links:
        if pid not in seen and len(chosen) < max_links:
            chosen.append(pid)
            seen.add(pid)
    if len(chosen) >= max_links:
        return chosen
    # Top up with nearest same-silo peers by centroid similarity.
    own = cluster_centroids.get(article.id)
    if own is not None:
        own_vec = np.asarray(own, dtype=np.float32)
        scored: list[tuple[float, str]] = []
        for cid in same_silo_ids:
            if cid in seen:
                continue
            vec = cluster_centroids.get(cid)
            if vec is None:
                continue
            scored.append((_cosine(own_vec, np.asarray(vec, dtype=np.float32)), cid))
        scored.sort(reverse=True)
        for _, cid in scored:
            if len(chosen) >= max_links:
                break
            chosen.append(cid)
            seen.add(cid)
    return chosen


def run_architecture_generation(
    *,
    seed: str,
    audience: str,
    pillars_input: list[PillarInput],
    topic_embeddings: dict[str, list[float] | None],
    cluster_centroids: dict[str, list[float] | None],
    skipped_silos: list[str] | None = None,
    pillar_lateral_cosine_threshold: float = 0.55,
    pillar_lateral_links_max: int = 2,
    pillar_down_links_max: int = 3,
    lateral_article_links_max: int = 4,
) -> ArchitectureResult:
    """Full §7.11 pass: derive each pillar's editorial fields deterministically
    (no LLM — the writer owns the title/summary), then assemble the linking matrix
    deterministically. Persistence is the caller's job."""
    result = ArchitectureResult(
        seed_keyword=seed, detected_audience=audience,
        skipped_silos=list(skipped_silos or []),
    )
    if not pillars_input:
        return result

    # ---- deterministic pillar editorial fields (no LLM) ------------------
    content = {p.topic_id: _pillar_content(p) for p in pillars_input}

    # ---- deterministic linking matrix ------------------------------------
    pillar_topic_ids = [p.topic_id for p in pillars_input]
    lateral_pillars = _lateral_pillar_links(
        pillar_topic_ids,
        topic_embeddings,
        pillar_lateral_cosine_threshold,
        pillar_lateral_links_max,
    )

    for p in pillars_input:
        c = content[p.topic_id]
        article_ids = [a.id for a in p.articles]
        n = len(article_ids)
        result.pillars.append(
            Pillar(
                topic_id=p.topic_id,
                silo_name=p.silo_name,
                title=c["title"],
                target_keyword=c["target_keyword"],
                summary=c["summary"],
                h2_outline=c["h2_outline"],
                # Pillar links DOWN to its most-central children only (capped); the
                # rest stay reachable via the article cycle below (≤5-link rule).
                supporting_article_ids=_pillar_down_links(
                    p.articles, cluster_centroids, max_links=pillar_down_links_max,
                ),
                lateral_pillar_links=lateral_pillars.get(p.topic_id, []),
                degraded=c["degraded"],
            )
        )
        same_silo_ids = set(article_ids)
        for i, a in enumerate(p.articles):
            # Within-silo cycle: each article links to the next (last -> first), so
            # every article is some peer's successor => receives ≥1 inbound link.
            # The no-orphan guarantee (§15.2 #3), independent of the pillar's links.
            successor = article_ids[(i + 1) % n] if n >= 2 else None
            result.supporting_articles.append(
                SupportingArticle(
                    article_id=a.id,
                    name=a.name,
                    intent=a.intent,
                    parent_pillar_topic_id=p.topic_id,  # links UP to its pillar (#2)
                    lateral_article_links=_lateral_article_links(
                        a, same_silo_ids, cluster_centroids,
                        max_links=lateral_article_links_max,
                        successor=successor,
                    ),
                )
            )

    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "site_architecture", **result.counts()},
    )
    return result
