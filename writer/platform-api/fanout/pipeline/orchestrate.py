"""Full M4 refinement pipeline (PRD §7.3–§7.9 composition).

Wires the per-stage modules into one run:

  1. §7.3/§7.5 expansion + autocomplete  -> per-topic candidate pool
  2. §7.4 competitor mining               -> gated silos' anchors + the seed
                                             (the seed is always mined; its
                                             keywords fan to every silo)
  3. §7.6 relevance gate + junk filter    -> active / filtered_* per topic
  4. §7.9 statistical clustering          -> per-topic Louvain groupings

Autocomplete (§7.5) is run inside expansion on the expansion pool only;
competitor keywords are already real ranked keywords and are not re-autocompleted
(a minor, documented deviation from §7.5's "after 7.3 and 7.4" ordering).

The run is synchronous and compounds the per-stage time budgets — a large run can
outrun the gateway. Background execution is deferred to M11 (handoff §4).
"""

import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from fanout.dataforseo import DataForSEOClient
from fanout.pipeline.clustering import run_clustering
from fanout.pipeline.competitor import MineTopic, run_competitor_mining
from fanout.pipeline.expansion import ExpansionTopic, build_anchor, run_expansion
from fanout.pipeline.relevance import GatedKeyword, run_relevance_gate

logger = logging.getLogger(__name__)


def _cos(a, b) -> float:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def simulate_best_silo_clustering(
    *,
    per_topic_lists: dict[str, dict[str, list[str]]],
    topic_names: dict[str, str],
    topic_embeddings: dict[str, list[float] | None],
    embed_fn,
    relevance_threshold: float,
    edge_threshold: float,
    resolution: float,
    clustering_max_nodes: int = 2500,
    examples_per_silo: int = 6,
    seed_terms: list[str] | None = None,
    peer_terms: list[str] | None = None,
    language_filter: Callable[[str], bool] | None = None,
) -> dict:
    """Read-only dry run of Lever 3. Gates the pool, then assigns each unique
    active keyword to its single best silo (argmax raw cosine to the rationale
    anchor) and *actually clusters* each silo's reassigned set — reporting the
    per-silo grouping counts and multi-keyword (>=2) cluster counts, which
    predict the article distribution. No persistence; this measures the Lever-3
    outcome before committing to it."""
    gate = run_relevance_gate(
        per_topic=per_topic_lists,
        topic_embeddings=topic_embeddings,
        embed_fn=embed_fn,
        topic_names=topic_names,
        threshold=relevance_threshold,
        seed_terms=seed_terms,
        peer_terms=peer_terms,
        language_filter=language_filter,
    )
    anchors = {
        tid: np.asarray(v, dtype=np.float64)
        for tid, v in topic_embeddings.items() if v
    }
    # one embedding per unique active keyword (reused across whichever silos it
    # was active in)
    kw_emb: dict[str, np.ndarray] = {}
    for gks in gate.per_topic.values():
        for g in gks:
            if g.status == "active" and g.embedding is not None and g.keyword not in kw_emb:
                kw_emb[g.keyword] = np.asarray(g.embedding, dtype=np.float64)

    assigned: dict[str, list[tuple[str, np.ndarray]]] = {tid: [] for tid in anchors}
    for kw, e in kw_emb.items():
        best = max(anchors, key=lambda tid: _cos(e, anchors[tid]))
        assigned[best].append((kw, e))

    per_kw = {tid: [kw for kw, _ in items][:clustering_max_nodes] for tid, items in assigned.items()}
    per_emb = {tid: [e for _, e in items][:clustering_max_nodes] for tid, items in assigned.items()}
    cluster = run_clustering(
        per_topic_keywords=per_kw, per_topic_embeddings=per_emb,
        edge_threshold=edge_threshold, resolution=resolution,
    )

    silos = []
    for tid, name in topic_names.items():
        groupings = cluster.per_topic.get(tid, [])
        sizes = sorted(g.size for g in groupings)
        # Example article candidates: the largest multi-keyword groupings, each
        # shown as primary (medoid) + the rest of its keywords.
        multi = sorted((g for g in groupings if g.size >= 2),
                       key=lambda g: g.size, reverse=True)
        examples = [
            {"primary": g.representative, "size": g.size, "keywords": g.keywords[:15]}
            for g in multi[:examples_per_silo]
        ]
        silos.append({
            "silo": name,
            "assigned_keywords": len(assigned.get(tid, [])),
            "groupings": len(groupings),
            "multi_kw_groupings": sum(1 for s in sizes if s >= 2),
            "singletons": sum(1 for s in sizes if s == 1),
            "median_size": sizes[len(sizes) // 2] if sizes else 0,
            "example_articles": examples,
        })
    silos.sort(key=lambda s: s["multi_kw_groupings"], reverse=True)
    return {
        "relevance_threshold": relevance_threshold,
        "edge_threshold": edge_threshold,
        "resolution": resolution,
        "total_active_unique": len(kw_emb),
        "silos": silos,
    }


def routing_diagnostic(
    *,
    seed: str,
    topics: list[tuple[str, str]],
    rationale_embeddings: dict[str, list[float] | None],
    active_by_topic: dict[str, list[str]],
    probes: list[str],
    embed_fn,
) -> dict:
    """Read-only investigation of how to route a keyword to its correct silo.

    Compares candidate per-silo "anchor" representations by routing each probe
    keyword to its argmax-cosine silo under each strategy, plus the resulting
    per-silo spread when every active keyword is routed. No persistence — this is
    purely diagnostic, to pick the routing signal empirically rather than guess.

    Strategies:
      - rationale_anchor : the current embed(seed+rationale+audience)
      - silo_name        : embed(name)
      - seed_plus_name   : embed(f"{seed} {name}")
      - keyword_centroid : mean embedding of the silo's own active keywords
    """
    ids = [tid for tid, _ in topics]
    names = [name for _, name in topics]

    name_vecs = embed_fn(names)
    seedname_vecs = embed_fn([f"{seed} {name}" for name in names])

    centroid_vecs: dict[str, np.ndarray | None] = {}
    all_active: list[str] = []
    for tid in ids:
        kws = active_by_topic.get(tid) or []
        all_active.extend(kws)
    # Embed every sampled active keyword once; reuse for centroids + spread.
    active_emb: dict[str, np.ndarray] = {}
    if all_active:
        uniq = list(dict.fromkeys(all_active))
        vecs = embed_fn(uniq)
        active_emb = {kw: np.asarray(v, dtype=np.float64) for kw, v in zip(uniq, vecs)}
    for tid in ids:
        kws = [k for k in (active_by_topic.get(tid) or []) if k in active_emb]
        centroid_vecs[tid] = (
            np.mean(np.stack([active_emb[k] for k in kws]), axis=0) if kws else None
        )

    strategies: dict[str, list] = {
        "rationale_anchor": [rationale_embeddings.get(tid) for tid in ids],
        "silo_name": list(name_vecs),
        "seed_plus_name": list(seedname_vecs),
        "keyword_centroid": [centroid_vecs[tid] for tid in ids],
    }

    def route(vec, anchors) -> str | None:
        best_idx, best_score = None, -2.0
        for idx, a in enumerate(anchors):
            if a is None:
                continue
            sc = _cos(vec, a)
            if sc > best_score:
                best_score, best_idx = sc, idx
        return names[best_idx] if best_idx is not None else None

    probe_vecs = embed_fn(probes) if probes else []
    probe_routing = [
        {"keyword": p, **{strat: route(pv, anchors) for strat, anchors in strategies.items()}}
        for p, pv in zip(probes, probe_vecs)
    ]

    # Per-silo spread when every sampled active keyword is routed (a good signal
    # spreads keywords across silos; a bad one dumps them into one).
    spread: dict[str, dict[str, int]] = {}
    for strat, anchors in strategies.items():
        counts = {name: 0 for name in names}
        for kw, vec in active_emb.items():
            dest = route(vec, anchors)
            if dest is not None:
                counts[dest] += 1
        spread[strat] = counts

    return {"silos": names, "probe_routing": probe_routing, "active_spread": spread,
            "active_sampled": len(active_emb)}

_SEED_MINE_ID = "__seed__"


@dataclass
class PipelineTopic:
    id: str
    name: str
    embedding: list[float] | None = None
    gated: bool = False


@dataclass
class PipelineResult:
    per_topic_gated: dict[str, list[GatedKeyword]] = field(default_factory=dict)
    clustering_log: dict = field(default_factory=dict)
    degraded_notes: list[str] = field(default_factory=list)
    timed_out: bool = False

    def counts(self) -> dict[str, int]:
        out = {"active": 0, "filtered_relevance": 0,
               "filtered_junk": 0, "filtered_language": 0}
        for kws in self.per_topic_gated.values():
            for k in kws:
                out[k.status] = out.get(k.status, 0) + 1
        return out


def _merge(base: dict[str, dict[str, set[str]]], add: dict[str, dict[str, list[str]]]) -> None:
    for tid, kws in add.items():
        target = base.get(tid)
        if target is None:
            continue
        for kw, sources in kws.items():
            target.setdefault(kw, set()).update(sources)


def gate_and_cluster(
    *,
    per_topic_lists: dict[str, dict[str, list[str]]],
    topic_names: dict[str, str],
    topic_embeddings: dict[str, list[float] | None],
    embed_fn,
    relevance_threshold: float = 0.62,
    relevance_embed_batch: int = 1000,
    clustering_edge_threshold: float = 0.55,
    clustering_resolution: float = 1.0,
    clustering_max_nodes: int = 2500,
    active_per_silo_cap: int = 0,
    seed_terms: list[str] | None = None,
    peer_terms: list[str] | None = None,
    assign_best_silo: bool = False,
    llm_router=None,
    llm_router_margin: float = 0.04,
    language_filter: Callable[[str], bool] | None = None,
) -> PipelineResult:
    """Relevance gate (§7.6) + statistical clustering (§7.9) over an already-built
    per-topic candidate pool. Shared by the full pipeline and the re-gate path
    (which reuses a session's stored keyword pool, skipping DataForSEO).

    `active_per_silo_cap` (0 = no cap) demotes active keywords beyond the top-N
    by relevance to `filtered_relevance`, applied BEFORE clustering so the cap
    shapes the active pool the user sees, not just what reaches the similarity
    graph."""
    result = PipelineResult()

    gate = run_relevance_gate(
        per_topic=per_topic_lists,
        topic_embeddings=topic_embeddings,
        embed_fn=embed_fn,
        topic_names=topic_names,
        threshold=relevance_threshold,
        batch_size=relevance_embed_batch,
        seed_terms=seed_terms,
        peer_terms=peer_terms,
        assign_best_silo=assign_best_silo,
        llm_router=llm_router,
        llm_router_margin=llm_router_margin,
        language_filter=language_filter,
    )
    result.degraded_notes.extend(gate.degraded_notes)
    cap_log = _cap_active_per_silo(gate.per_topic, active_per_silo_cap)
    result.per_topic_gated = gate.per_topic

    active_keywords, active_embeddings = _active_for_clustering(
        gate.per_topic, clustering_max_nodes
    )
    cluster = run_clustering(
        per_topic_keywords=active_keywords,
        per_topic_embeddings=active_embeddings,
        edge_threshold=clustering_edge_threshold,
        resolution=clustering_resolution,
    )
    result.clustering_log = cluster.to_log()
    if cap_log:
        # Per-topic capped counts surface in the Owner debug view + structured
        # logs so a tightening of the cap is auditable run-over-run.
        result.clustering_log["active_per_silo_cap"] = {
            "cap": active_per_silo_cap,
            "capped_per_topic": cap_log,
            "total_capped": sum(cap_log.values()),
        }
    return result


def _cap_active_per_silo(
    per_topic_gated: dict[str, list[GatedKeyword]], cap: int
) -> dict[str, int]:
    """Keep the top-`cap` active keywords per silo (by relevance_score, descending)
    and demote the rest to `filtered_relevance` in place. Returns the per-topic
    demoted count for the clustering log. cap <= 0 disables (no-op)."""
    if cap <= 0:
        return {}
    capped_counts: dict[str, int] = {}
    for tid, gated in per_topic_gated.items():
        active_idx = [
            (i, g.relevance_score if g.relevance_score is not None else 0.0)
            for i, g in enumerate(gated)
            if g.status == "active"
        ]
        if len(active_idx) <= cap:
            continue
        active_idx.sort(key=lambda x: x[1], reverse=True)
        keep = {i for i, _ in active_idx[:cap]}
        demoted = 0
        for i, g in enumerate(gated):
            if g.status == "active" and i not in keep:
                g.status = "filtered_relevance"
                g.embedding = None  # match how the gate emits filtered_relevance
                demoted += 1
        if demoted:
            capped_counts[tid] = demoted
    return capped_counts


def _active_for_clustering(per_topic_gated, clustering_max_nodes):
    """Active keywords + their gate-computed embeddings, per topic, capped at the
    most-relevant `clustering_max_nodes` (the similarity graph is O(n^2))."""
    active_keywords: dict[str, list[str]] = {}
    active_embeddings: dict[str, list[list[float]]] = {}
    for tid, gated_kws in per_topic_gated.items():
        scored = [
            (g.relevance_score if g.relevance_score is not None else 0.0, g.keyword, g.embedding)
            for g in gated_kws
            if g.status == "active" and g.embedding is not None
        ]
        if len(scored) > clustering_max_nodes:
            scored.sort(key=lambda x: x[0], reverse=True)
            scored = scored[:clustering_max_nodes]
        active_keywords[tid] = [kw for _, kw, _ in scored]
        active_embeddings[tid] = [emb for _, _, emb in scored]
    return active_keywords, active_embeddings


def cluster_preview(
    *,
    per_topic_lists: dict[str, dict[str, list[str]]],
    topic_names: dict[str, str],
    topic_embeddings: dict[str, list[float] | None],
    embed_fn,
    relevance_threshold: float,
    configs: list[tuple[float, float]],
    relevance_embed_batch: int = 1000,
    clustering_max_nodes: int = 2500,
    seed_terms: list[str] | None = None,
    peer_terms: list[str] | None = None,
    assign_best_silo: bool = False,
    language_filter: Callable[[str], bool] | None = None,
) -> dict:
    """Embed + gate once, then cluster under each (edge_threshold, resolution)
    config and report granularity stats — without persisting anything. The
    granularity sweep tool: one embed pass, many configs, so we can find the
    settings that yield ~150-200 substantial groupings before committing a run."""
    gate = run_relevance_gate(
        per_topic=per_topic_lists,
        topic_embeddings=topic_embeddings,
        embed_fn=embed_fn,
        topic_names=topic_names,
        threshold=relevance_threshold,
        batch_size=relevance_embed_batch,
        seed_terms=seed_terms,
        peer_terms=peer_terms,
        assign_best_silo=assign_best_silo,
        language_filter=language_filter,
    )
    active_keywords, active_embeddings = _active_for_clustering(
        gate.per_topic, clustering_max_nodes
    )
    active_total = sum(len(v) for v in active_keywords.values())

    results = []
    for edge_threshold, resolution in configs:
        cluster = run_clustering(
            per_topic_keywords=active_keywords,
            per_topic_embeddings=active_embeddings,
            edge_threshold=edge_threshold,
            resolution=resolution,
        )
        sizes = [g.size for groupings in cluster.per_topic.values() for g in groupings]
        sizes.sort()
        n = len(sizes)
        median = sizes[n // 2] if n else 0
        results.append({
            "edge_threshold": edge_threshold,
            "resolution": resolution,
            "groupings": n,
            "median_size": median,
            "singletons": sum(1 for s in sizes if s == 1),
            "size_buckets": {
                "1": sum(1 for s in sizes if s == 1),
                "2-4": sum(1 for s in sizes if 2 <= s <= 4),
                "5-9": sum(1 for s in sizes if 5 <= s <= 9),
                "10-19": sum(1 for s in sizes if 10 <= s <= 19),
                "20+": sum(1 for s in sizes if s >= 20),
            },
        })
    return {
        "relevance_threshold": relevance_threshold,
        "active_keywords": active_total,
        "configs": results,
    }


def run_refinement_pipeline(
    *,
    seed: str,
    topics: list[PipelineTopic],
    dfs: DataForSEOClient,
    embed_fn,
    # expansion (§7.3/§7.5)
    keyword_ideas_limit: int = 1000,
    keyword_suggestions_limit: int = 500,
    query_fanouts_limit: int = 300,
    paa_tier1_seeds: int = 8,
    paa_tier2_cap: int = 40,
    autocomplete_max: int = 1500,
    expansion_max_workers: int = 8,
    expansion_time_budget_s: float = 240.0,
    # competitor mining (§7.4)
    competitor_top_n: int = 5,
    ranked_keywords_limit: int = 500,
    competitor_max_position: int = 20,
    competitor_max_workers: int = 8,
    competitor_time_budget_s: float = 240.0,
    # relevance gate (§7.6) + clustering (§7.9)
    relevance_threshold: float = 0.62,
    relevance_embed_batch: int = 1000,
    clustering_edge_threshold: float = 0.55,
    clustering_resolution: float = 1.0,
    clustering_max_nodes: int = 2500,
    active_per_silo_cap: int = 0,
    seed_terms: list[str] | None = None,
    peer_terms: list[str] | None = None,
    assign_best_silo: bool = False,
    llm_router=None,
    llm_router_margin: float = 0.04,
    language_filter: Callable[[str], bool] | None = None,
) -> PipelineResult:
    result = PipelineResult()
    topic_names = {t.id: t.name for t in topics}
    topic_embeddings = {t.id: t.embedding for t in topics}

    # ----- 1. Expansion (+ autocomplete) -----------------------------------
    exp = run_expansion(
        seed=seed,
        topics=[ExpansionTopic(id=t.id, anchor=build_anchor(seed, t.name), name=t.name)
                for t in topics],
        dfs=dfs,
        keyword_ideas_limit=keyword_ideas_limit,
        keyword_suggestions_limit=keyword_suggestions_limit,
        query_fanouts_limit=query_fanouts_limit,
        paa_tier1_seeds=paa_tier1_seeds,
        paa_tier2_cap=paa_tier2_cap,
        autocomplete_max=autocomplete_max,
        max_workers=expansion_max_workers,
        time_budget_s=expansion_time_budget_s,
    )
    result.degraded_notes.extend(exp.degraded_notes)
    result.timed_out = result.timed_out or exp.timed_out

    # Merge pools (keyword -> set of sources) per topic.
    pools: dict[str, dict[str, set[str]]] = {t.id: {} for t in topics}
    _merge(pools, exp.per_topic)

    # ----- 2. Competitor mining (gated silos + the always-mined seed) ------
    gated = [t for t in topics if t.gated]
    if gated:
        cm = run_competitor_mining(
            topics=[MineTopic(id=t.id, anchor=build_anchor(seed, t.name), name=t.name)
                    for t in gated],
            dfs=dfs,
            top_n=competitor_top_n,
            ranked_keywords_limit=ranked_keywords_limit,
            max_position=competitor_max_position,
            max_workers=competitor_max_workers,
            time_budget_s=competitor_time_budget_s,
        )
        result.degraded_notes.extend(cm.degraded_notes)
        result.timed_out = result.timed_out or cm.timed_out
        _merge(pools, cm.per_topic)

    # The seed itself is always mined (§7.2); its competitor keywords fan to
    # every silo, and the relevance gate sorts them per-silo.
    seed_cm = run_competitor_mining(
        topics=[MineTopic(id=_SEED_MINE_ID, anchor=seed, name=seed)],
        dfs=dfs,
        top_n=competitor_top_n,
        ranked_keywords_limit=ranked_keywords_limit,
        max_position=competitor_max_position,
        max_workers=competitor_max_workers,
        time_budget_s=competitor_time_budget_s,
    )
    result.degraded_notes.extend(seed_cm.degraded_notes)
    result.timed_out = result.timed_out or seed_cm.timed_out
    seed_keywords = seed_cm.per_topic.get(_SEED_MINE_ID, {})
    if seed_keywords:
        fanned = {t.id: seed_keywords for t in topics}
        _merge(pools, fanned)

    # ----- 3+4. Relevance gate + statistical clustering --------------------
    per_topic_lists = {
        tid: {kw: sorted(sources) for kw, sources in kws.items()}
        for tid, kws in pools.items()
    }
    gc = gate_and_cluster(
        per_topic_lists=per_topic_lists,
        topic_names=topic_names,
        topic_embeddings=topic_embeddings,
        embed_fn=embed_fn,
        relevance_threshold=relevance_threshold,
        relevance_embed_batch=relevance_embed_batch,
        clustering_edge_threshold=clustering_edge_threshold,
        clustering_resolution=clustering_resolution,
        clustering_max_nodes=clustering_max_nodes,
        active_per_silo_cap=active_per_silo_cap,
        seed_terms=seed_terms,
        peer_terms=peer_terms,
        assign_best_silo=assign_best_silo,
        llm_router=llm_router,
        llm_router_margin=llm_router_margin,
        language_filter=language_filter,
    )
    result.degraded_notes.extend(gc.degraded_notes)
    result.per_topic_gated = gc.per_topic_gated
    result.clustering_log = gc.clustering_log

    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "refinement_pipeline",
               **result.counts(), "degraded": bool(result.degraded_notes),
               "timed_out": result.timed_out},
    )
    return result
