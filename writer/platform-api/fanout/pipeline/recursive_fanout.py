"""Recursive Fanout (PRD §7.7, Phase 1) — deepen each silo one level.

After a normal expansion + clustering pass, each silo has statistical groupings
whose medoid representatives are concrete, on-niche sub-topics of that silo. RF
treats those representatives as **sub-anchors** and runs the existing keyword
expansion on each, attaching the new keywords back to the parent silo. The
enlarged pool then flows through the unchanged relevance gate + clustering +
planning.

Phase 1 only (see `docs/recursive-fanout-spec.md`): no sub-silo *discovery*, no
hierarchy, no schema change. Sub-anchors come from the first pass's cluster
representatives (the owner's chosen source); competitor mining at this level is
off (M5 finding: mining adds noise the gate rejects). Depth is hard-capped at 1
by construction — RF reads representatives once and never recurses on its own
output.
"""

import logging

from fanout.dataforseo import DataForSEOClient
from fanout.pipeline.expansion import ExpansionTopic, build_anchor, run_expansion

logger = logging.getLogger(__name__)

# Separator for the synthetic per-(silo, sub-anchor) topic ids handed to
# run_expansion; chosen so it can't collide with a real uuid topic id.
_SUB = "::sub::"

RECURSIVE_SOURCE = "recursive"


def derive_sub_anchors(
    *,
    clustering_log: dict,
    topic_ids: list[str],
    per_silo: int,
) -> dict[str, list[str]]:
    """Pick each silo's top `per_silo` cluster representatives as sub-anchors.

    Representatives are taken from the first pass's `statistical_clustering_log`,
    ranked by grouping size (largest groupings = the most substantial sub-topics
    worth deepening). Singleton groupings are skipped — a one-keyword grouping is
    a leaf, not a sub-topic to fan out. Returns {topic_id: [representative, ...]}
    with empty lists for silos that have no multi-keyword groupings.
    """
    log_topics = (clustering_log or {}).get("topics") or {}
    out: dict[str, list[str]] = {}
    for tid in topic_ids:
        groupings = (log_topics.get(tid) or {}).get("groupings") or []
        ranked = sorted(
            (g for g in groupings if int(g.get("size") or 0) >= 2),
            key=lambda g: int(g.get("size") or 0),
            reverse=True,
        )
        anchors: list[str] = []
        seen: set[str] = set()
        for g in ranked:
            rep = str(g.get("representative") or "").strip()
            key = rep.lower()
            if rep and key not in seen:
                anchors.append(rep)
                seen.add(key)
            if len(anchors) >= per_silo:
                break
        out[tid] = anchors
    return out


def count_sub_anchors(sub_anchors: dict[str, list[str]]) -> int:
    return sum(len(v) for v in sub_anchors.values())


def run_recursive_expansion(
    *,
    seed: str,
    sub_anchors: dict[str, list[str]],
    dfs: DataForSEOClient,
    keyword_ideas_limit: int = 1000,
    paa_tier1_seeds: int = 8,
    paa_tier2_cap: int = 40,
    autocomplete_max: int = 500,
    max_workers: int = 8,
    time_budget_s: float = 240.0,
) -> tuple[dict[str, dict[str, list[str]]], list[str], bool]:
    """Expand every sub-anchor and collect the keywords under its parent silo.

    Reuses `run_expansion`: each (silo, sub-anchor) becomes a synthetic expansion
    topic with a unique id, so keyword_ideas + PAA run per sub-anchor; results are
    then remapped onto the real parent silo id. Seed-level endpoints
    (keyword_suggestions / query_fanouts) are skipped — they already ran on the
    bare seed in the first pass. Every recursive keyword is tagged
    `RECURSIVE_SOURCE` for provenance.

    Returns (per_topic {topic_id: {keyword: [sources]}}, degraded_notes, timed_out).
    """
    synthetic: list[ExpansionTopic] = []
    parent_of: dict[str, str] = {}
    for tid, anchors in sub_anchors.items():
        for i, anchor in enumerate(anchors):
            sid = f"{tid}{_SUB}{i}"
            parent_of[sid] = tid
            synthetic.append(
                ExpansionTopic(id=sid, anchor=build_anchor(seed, anchor), name=anchor)
            )

    if not synthetic:
        return {tid: {} for tid in sub_anchors}, [], False

    exp = run_expansion(
        seed=seed,
        topics=synthetic,
        dfs=dfs,
        keyword_ideas_limit=keyword_ideas_limit,
        paa_tier1_seeds=paa_tier1_seeds,
        paa_tier2_cap=paa_tier2_cap,
        autocomplete_max=autocomplete_max,
        max_workers=max_workers,
        time_budget_s=time_budget_s,
        include_seed_level=False,
    )

    per_topic: dict[str, dict[str, set[str]]] = {tid: {} for tid in sub_anchors}
    for sid, kws in exp.per_topic.items():
        parent = parent_of.get(sid)
        if parent is None:
            continue
        bucket = per_topic.setdefault(parent, {})
        for kw, sources in kws.items():
            tags = bucket.setdefault(kw, set())
            tags.update(sources)
            tags.add(RECURSIVE_SOURCE)

    result = {
        tid: {kw: sorted(tags) for kw, tags in kws.items()}
        for tid, kws in per_topic.items()
    }
    logger.info(
        "step_complete",
        extra={
            "event": "step_complete",
            "step": "recursive_expansion",
            "sub_anchor_count": len(synthetic),
            "keyword_count": sum(len(v) for v in result.values()),
            "degraded": bool(exp.degraded_notes),
            "timed_out": exp.timed_out,
        },
    )
    return result, exp.degraded_notes, exp.timed_out


def merge_into_pool(
    base: dict[str, dict[str, list[str]]],
    add: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, list[str]]]:
    """Union recursive keywords into the stored pre-gate pool, merging source
    tags for keywords that already exist. Returns a new merged pool."""
    merged: dict[str, dict[str, set[str]]] = {
        tid: {kw: set(srcs) for kw, srcs in kws.items()} for tid, kws in base.items()
    }
    for tid, kws in add.items():
        bucket = merged.setdefault(tid, {})
        for kw, srcs in kws.items():
            bucket.setdefault(kw, set()).update(srcs)
    return {tid: {kw: sorted(s) for kw, s in kws.items()} for tid, kws in merged.items()}
