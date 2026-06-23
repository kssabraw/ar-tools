"""Peer-entity-aware article grouping (owner-requested follow-up to §7.10).

Background: the orchestrator clusters by keyword embedding similarity. Keywords
that name DIFFERENT peer entities (e.g. `switching from tirzepatide to retatrutide`
vs. `switching from zepbound to retatrutide`) embed nearly identically — only the
peer-name token differs, and the model sees those tokens as semantically close —
so Louvain bundles them as one community and the orchestrator inherits one
combined article. But editorially they are DIFFERENT articles: each names a
different peer.

This pass uses the deterministic peer-entity list (already produced by grounding
at session creation, used by the §7.6 off-niche filter) to partition the
planner's articles by the peer entity each keyword names. **Cross-topic**:
keywords naming the same peer collapse into exactly one article across the
ENTIRE plan (not one per topic), so there's nothing duplicate for cross-topic
dedup to chew on — which is what hollowed out the smaller silos in the
per-topic implementation.

Each peer article's home topic is the one that contributed the most keywords to
its bucket (ties broken deterministically by first occurrence). Multi-peer
keywords (`X vs Y vs Z`) form their own multi-peer bucket.

Design choices:
- **Cross-topic, single home topic per peer.** No duplicate peer articles -> no
  dedup elimination cascade. The smaller silos keep their non-peer articles.
- **Configurable minimum size (`min_keywords`).** A peer mention is a
  deterministic signal, but a bucket with too few keywords (e.g. a lone
  `cagrisema vs retatrutide`) makes a thin single-keyword stub. Buckets below
  the threshold fold into ONE "retatrutide vs competitors" comparison roundup
  instead of littering the plan with per-competitor stubs; substantial buckets
  (e.g. `retatrutide vs ozempic`) still get their own article. `min_keywords=1`
  disables folding (every bucket stands alone — the original behavior).
- **Whole-word peer match** (substring-safe), case-insensitive.
- **Runs BEFORE the salience split**, so peer-entity (stronger signal) gets
  first dibs; salience split then handles any oversized leftover non-peer articles.
"""

import logging
import re

from .models import ArticleRecord, PlanResult

logger = logging.getLogger(__name__)


def _peer_regex(peer_terms: list[str]) -> re.Pattern | None:
    cleaned = [p.strip().lower() for p in (peer_terms or []) if p and p.strip()]
    if not cleaned:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(p) for p in cleaned) + r")\b")


def _detect_peers(keyword: str, peer_lower: list[str]) -> frozenset[str]:
    """Return the set of peer entities the keyword names (whole-word, lowercase)."""
    kw_lower = keyword.lower()
    return frozenset(
        p for p in peer_lower if re.search(r"\b" + re.escape(p) + r"\b", kw_lower)
    )


def _pick_peer_primary(keywords: list[str], seed_lower: list[str], peer: str) -> str:
    """Prefer the cleanest `seed vs peer` / `peer vs seed` form; else shortest."""
    versus_candidates: list[str] = []
    for kw in keywords:
        kw_lower = kw.lower()
        for seed in seed_lower:
            if (re.search(rf"\b{re.escape(seed)}\s+vs\.?\s+{re.escape(peer)}\b", kw_lower)
                or re.search(rf"\b{re.escape(peer)}\s+vs\.?\s+{re.escape(seed)}\b", kw_lower)):
                versus_candidates.append(kw)
                break
    pool = versus_candidates or keywords
    return min(pool, key=lambda k: (len(k), k))


def _unique_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _home_topic(sources: list[tuple[str, str]]) -> str:
    """The topic that contributed the most keywords to a bucket; ties broken by
    first occurrence (deterministic)."""
    topic_counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for tid, _kw in sources:
        topic_counts[tid] = topic_counts.get(tid, 0) + 1
        first_seen.setdefault(tid, len(first_seen))
    return max(topic_counts, key=lambda t: (topic_counts[t], -first_seen[t]))


def _bucket_label(peer_key: frozenset) -> str:
    return next(iter(peer_key)) if len(peer_key) == 1 else ", ".join(sorted(peer_key))


def group_by_peer_entity(
    result: PlanResult,
    *,
    seed_terms: list[str],
    peer_terms: list[str],
    min_keywords: int = 1,
) -> None:
    """Mutate `result` in place: cross-topic peer-entity partition (PRD §7.10).

    Every keyword that names a peer entity across the *entire* plan is pulled
    into a per-peer bucket; each bucket becomes exactly ONE article, assigned to
    the silo that contributed the most keywords (the bucket's home topic). All
    other articles keep their non-peer keywords; if an article's primary was
    peer-named, a non-peer keyword is promoted. Articles whose every keyword
    was peer-named dissolve into the cross-topic peer buckets."""
    if not peer_terms:
        return
    regex = _peer_regex(peer_terms)
    if regex is None:
        return
    peer_lower = [p.strip().lower() for p in peer_terms if p and p.strip()]
    seed_lower = [s.strip().lower() for s in (seed_terms or []) if s and s.strip()]

    # Cross-topic peer buckets: peer_key -> ordered list of (source_topic, kw).
    peer_buckets: dict[frozenset, list[tuple[str, str]]] = {}
    # Each topic's surviving NON-peer parent articles.
    topic_articles: dict[str, list[ArticleRecord]] = {p.topic_id: [] for p in result.per_topic}
    original_counts: dict[str, int] = {p.topic_id: len(p.articles) for p in result.per_topic}

    for plan in result.per_topic:
        for art in plan.articles:
            all_kws = _unique_preserving_order(
                [art.primary_keyword, *art.supporting_keywords]
            )
            non_peer: list[str] = []
            for kw in all_kws:
                peers = _detect_peers(kw, peer_lower)
                if peers:
                    peer_buckets.setdefault(peers, []).append((plan.topic_id, kw))
                else:
                    non_peer.append(kw)

            if not non_peer:
                continue  # every keyword was peer-named — parent dissolves

            if art.primary_keyword in non_peer:
                primary = art.primary_keyword
                notes = art.orchestrator_notes
                suggested_h2s = art.suggested_h2s
                serp = art.serp_top_urls
            else:
                # Original primary was peer-named (gone to a peer bucket); promote
                # a non-peer keyword as the parent's new primary. The original
                # H2 outline / SERP referred to the old primary, so blank them.
                primary = min(non_peer, key=lambda k: (len(k), k))
                notes = (
                    (art.orchestrator_notes or "")
                    + " | primary promoted after peer-entity grouping"
                ).strip(" |")
                suggested_h2s = []
                serp = []

            topic_articles[plan.topic_id].append(ArticleRecord(
                topic_id=plan.topic_id,
                primary_keyword=primary,
                supporting_keywords=[k for k in non_peer if k != primary],
                intent=art.intent,
                suggested_h2s=suggested_h2s,
                source_statistical_grouping_id=art.source_statistical_grouping_id,
                orchestrator_notes=notes,
                serp_top_urls=serp,
                peer_primary_keywords=art.peer_primary_keywords,
            ))

    # Materialize peer articles — cross-topic, single home topic each. A bucket
    # with >= min_keywords becomes its own per-competitor article; smaller ones
    # are set aside and folded into a single comparison roundup below, so a lone
    # `cagrisema vs retatrutide` doesn't ship as its own single-keyword stub.
    folded_sources: list[tuple[str, str]] = []
    folded_labels: list[str] = []
    for peer_key, sources in peer_buckets.items():
        unique_kws = _unique_preserving_order([kw for _, kw in sources])
        if len(unique_kws) < min_keywords:
            folded_sources.extend(sources)
            folded_labels.append(_bucket_label(peer_key))
            continue
        home_topic = _home_topic(sources)
        if len(peer_key) == 1:
            (peer,) = peer_key
            primary = _pick_peer_primary(unique_kws, seed_lower, peer)
        else:
            primary = min(unique_kws, key=lambda k: (len(k), k))

        topic_articles.setdefault(home_topic, []).append(ArticleRecord(
            topic_id=home_topic,
            primary_keyword=primary,
            supporting_keywords=[k for k in unique_kws if k != primary],
            intent="comparison",
            suggested_h2s=[],
            source_statistical_grouping_id=None,
            orchestrator_notes=f"Grouped by peer entity: {_bucket_label(peer_key)}",
        ))

    # Fold the sub-threshold buckets into ONE "retatrutide vs competitors"
    # roundup (one home topic, one article). If only a single small bucket
    # existed this is just that one article — no worse than before; the win is
    # when several stubs consolidate.
    if folded_sources:
        home_topic = _home_topic(folded_sources)
        unique_kws = _unique_preserving_order([kw for _, kw in folded_sources])
        primary = min(unique_kws, key=lambda k: (len(k), k))
        topic_articles.setdefault(home_topic, []).append(ArticleRecord(
            topic_id=home_topic,
            primary_keyword=primary,
            supporting_keywords=[k for k in unique_kws if k != primary],
            intent="comparison",
            suggested_h2s=[],
            source_statistical_grouping_id=None,
            orchestrator_notes=(
                f"Comparison roundup: folded {len(folded_labels)} small peer "
                f"bucket(s) ({', '.join(sorted(folded_labels))})"
            ),
        ))

    # Write back to per-topic plans. Delta can be negative for a topic that lost
    # articles to a peer bucket whose home was elsewhere — that's expected.
    total_added = 0
    for plan in result.per_topic:
        new_articles = topic_articles.get(plan.topic_id, [])
        delta = len(new_articles) - original_counts[plan.topic_id]
        plan.articles = new_articles
        if delta:
            plan.log["peer_entity_grouped_delta"] = delta
            total_added += max(delta, 0)

    if total_added:
        logger.info(
            "step_complete",
            extra={"event": "step_complete", "step": "peer_entity_grouping",
                   "articles_added": total_added},
        )
