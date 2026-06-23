"""Background execution for the long pipeline operations.

`/expand`, `/plan-articles`, and `/regate` exceed Railway's ~5-min edge cap when
run inside the request, so the endpoints claim the run (atomic status flip),
submit the work here, and return 202 immediately. The frontend polls session
status. Each job owns its terminal status: it sets `awaiting_article_planning` /
`complete` on success, or `error` + `last_error` on failure.

A bounded pool caps concurrent pipeline runs per process; the per-session run
guard (try_mark_running) prevents the same session running twice. Jobs use the
service client (no user token — the request already authorized the caller).

Caveat (accepted for v1, real fix = a durable queue): a process restart mid-job
strands the session at status='running'. Recovery is a new session until M7's
resume lands.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache, wraps

from fanout import cancellation
from fanout.cancellation import CancelledByUser
from fanout.config import get_settings
from fanout.cost_attribution import metered_run
from fanout.dataforseo import get_dataforseo
from fanout.llm import get_llm, get_orchestrator
from fanout.logging import bind_session_id
from fanout.pipeline.language import make_language_filter
from fanout.pipeline.llm_router import build_llm_router
from fanout.pipeline.metrics import enrich_keywords
from fanout.pipeline.architecture import (
    ArticleInput,
    PillarInput,
    run_architecture_generation,
)
from fanout.pipeline.article_planning.models import GroupingInput, TopicInput
from fanout.pipeline.article_planning.orchestrate_articles import (
    all_degraded,
    run_article_planning,
)
from fanout.pipeline.orchestrate import (
    PipelineTopic,
    gate_and_cluster,
    run_refinement_pipeline,
)
from fanout.pipeline.recursive_fanout import (
    derive_sub_anchors,
    merge_into_pool,
    run_recursive_expansion,
)
from fanout.storage import silo as store
from fanout import prepublish_rank

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pipeline")


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


@lru_cache(maxsize=4)
def _build_language_filter(enabled: bool, confidence: float):
    """Cache the lingua detector across jobs. lingua's builder allocates and
    its model data loads lazily on first use; rebuilding for every expand /
    regate / fanout call is wasted work (the same threshold + flag yields the
    same closure). Keyed by (enabled, confidence) so a settings change at
    runtime — e.g. lowering the threshold for an A/B — still rebuilds."""
    if not enabled:
        return None
    return make_language_filter(confidence_threshold=confidence)


def _maybe_language_filter():
    """Build (or reuse) the gate's language filter from settings. Returns None
    when the flag is off OR lingua-py is unavailable, so callers can pass
    through."""
    s = get_settings()
    return _build_language_filter(s.language_filter_enabled,
                                  s.language_filter_confidence)


def _maybe_enrich_metrics(session: dict, per_topic_gated) -> None:
    """If the session opted into §7.8 metrics enrichment, fetch volume / CPC /
    KD / competition for the active pool and persist onto the keyword rows.
    Cost-bearing — the active_per_silo_cap bounds it (~$0.40 for 5 silos at
    list price). Degrades quietly: any failure logs + writes nothing, the run
    still completes."""
    settings = session.get("settings") or {}
    if not settings.get("enrich_with_metrics"):
        return
    s = get_settings()
    active_keywords = sorted({
        g.keyword
        for kws in per_topic_gated.values()
        for g in kws
        if g.status == "active"
    })
    if not active_keywords:
        return
    result = enrich_keywords(
        keywords=active_keywords,
        dfs=get_dataforseo(store.session_location_code(session)),
        batch_size=s.metrics_batch_size,
        max_workers=s.metrics_max_workers,
        time_budget_s=float(s.metrics_time_budget_s),
    )
    if result.metrics:
        store.update_keyword_metrics(session["id"], result.metrics)


def _maybe_llm_router(seed: str, topics: list[dict]):
    """Build the LLM router for ambiguous keywords if enabled; None otherwise."""
    s = get_settings()
    if not s.llm_routing_enabled:
        return None
    return build_llm_router(
        seed=seed,
        silos=[{"id": t["id"], "name": t.get("name"),
                "rationale": t.get("rationale")} for t in topics],
        llm=get_llm(),
        batch_size=s.llm_routing_batch_size,
        max_workers=s.llm_routing_max_workers,
    )


def _metered(step: str):
    """Wrap a job so its external-API spend is metered and flushed to
    `actual_cost_usd` + `cost_breakdown` live (PRD §16.4). The meter is bound on
    the job thread and inherited by the pipeline's nested workers via
    `ContextThreadPoolExecutor`. `session_id` is always the first argument."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(session_id: str, *args, **kwargs):
            with metered_run(session_id, step):
                return fn(session_id, *args, **kwargs)

        return wrapper

    return decorator


def _cancellable(fn):
    """Register the session's cancellation event for the job's lifetime and
    convert `CancelledByUser` into a clean `status='cancelled'` finish.

    Bypasses the per-stage `except Exception` blocks in the pipeline (it's a
    BaseException), so an in-flight stage doesn't degrade — the whole run aborts
    here, the terminal status write is conditional-on-running so it doesn't race
    the /cancel endpoint's own write, and `metered_run` (outer decorator) flushes
    the partial spend on the way out. Clear the event so the next run starts
    fresh."""

    @wraps(fn)
    def wrapper(session_id: str, *args, **kwargs):
        cancellation.register(session_id)
        try:
            return fn(session_id, *args, **kwargs)
        except CancelledByUser:
            logger.info(
                "step_cancelled",
                extra={"event": "step_cancelled", "step": fn.__name__},
            )
            # The /cancel endpoint has likely already set status='cancelled' via
            # try_mark_cancelled; this is the catch-up write for a worker that
            # raced past the endpoint's update. Conditional-on-running so it
            # doesn't overwrite a fresh user-initiated state.
            from fanout.storage import silo as _store
            _store.try_finalize_running(
                session_id,
                {"status": "cancelled", "last_error": "Cancelled by user"},
            )
            return None
        finally:
            cancellation.clear(session_id)

    return wrapper


def submit_expand(session_id: str) -> None:
    _EXECUTOR.submit(run_expand_job, session_id)


def submit_plan(session_id: str, direct: bool = False) -> None:
    _EXECUTOR.submit(run_plan_job, session_id, direct)


def submit_regate(
    session_id: str,
    threshold: float,
    edge_threshold: float,
    resolution: float,
    active_per_silo_cap: int,
    seed_terms: list[str],
    peer_terms: list[str],
) -> None:
    _EXECUTOR.submit(run_regate_job, session_id, threshold, edge_threshold,
                     resolution, active_per_silo_cap, seed_terms, peer_terms)


def submit_fanout(
    session_id: str,
    threshold: float,
    edge_threshold: float,
    resolution: float,
    active_per_silo_cap: int,
    seed_terms: list[str],
    peer_terms: list[str],
) -> None:
    _EXECUTOR.submit(run_fanout_job, session_id, threshold, edge_threshold,
                     resolution, active_per_silo_cap, seed_terms, peer_terms)


def submit_architecture(session_id: str) -> None:
    _EXECUTOR.submit(run_architecture_job, session_id)


@_metered("expand")
@_cancellable
def run_expand_job(session_id: str) -> None:
    """§7.3–§7.9: expansion + competitor mining + relevance gate + clustering."""
    bind_session_id(session_id)
    try:
        session = store.get_session(session_id)
        topics = store.list_topics(session_id)
        embeddings = store.get_topic_embeddings(session_id)
        s = get_settings()
        coverage_mode = (session.get("settings") or {}).get("coverage_mode", "standard")
        top_n = (
            s.competitor_top_n_comprehensive
            if coverage_mode == "comprehensive"
            else s.competitor_top_n_standard
        )
        seed = session["seed_keyword"]
        result = run_refinement_pipeline(
            seed=seed,
            topics=[
                PipelineTopic(
                    id=t["id"],
                    name=t["name"],
                    embedding=embeddings.get(t["id"]),
                    gated=bool(t.get("is_gated_for_competitor_mining")),
                )
                for t in topics
            ],
            dfs=get_dataforseo(store.session_location_code(session)),
            embed_fn=get_llm().embed,
            seed_terms=[seed, *(session.get("aliases") or [])],
            peer_terms=session.get("peer_entities") or [],
            assign_best_silo=s.relevance_assign_best_silo,
            keyword_ideas_limit=s.keyword_ideas_limit,
            keyword_suggestions_limit=s.keyword_suggestions_limit,
            query_fanouts_limit=s.query_fanouts_limit,
            paa_tier1_seeds=s.paa_tier1_seeds,
            paa_tier2_cap=s.paa_tier2_cap,
            autocomplete_max=s.autocomplete_max,
            expansion_max_workers=s.expansion_max_workers,
            expansion_time_budget_s=s.expansion_time_budget_s,
            competitor_top_n=top_n,
            ranked_keywords_limit=s.ranked_keywords_limit,
            competitor_max_position=s.competitor_max_position,
            competitor_max_workers=s.competitor_max_workers,
            competitor_time_budget_s=s.competitor_time_budget_s,
            relevance_threshold=s.relevance_threshold,
            relevance_embed_batch=s.relevance_embed_batch,
            clustering_edge_threshold=s.clustering_edge_threshold,
            clustering_resolution=s.clustering_resolution,
            clustering_max_nodes=s.clustering_max_nodes,
            active_per_silo_cap=s.active_per_silo_cap,
            llm_router=_maybe_llm_router(seed, topics),
            llm_router_margin=s.llm_routing_margin_threshold,
            language_filter=_maybe_language_filter(),
        )
        store.delete_keywords_for_session(session_id)
        store.insert_classified_keywords(session_id, result.per_topic_gated)
        _maybe_enrich_metrics(session, result.per_topic_gated)
        store.try_finalize_running(
            session_id,
            {
                "statistical_clustering_log": result.clustering_log,
                "status": "awaiting_article_planning",
            },
        )
        logger.info(
            "step_complete",
            extra={"event": "step_complete", "step": "expand_job", **result.counts()},
        )
    except Exception as exc:  # noqa: BLE001 — terminal status carries the failure
        logger.error(
            "step_failed",
            extra={"event": "step_failed", "step": "expand_job", "reason": repr(exc)},
        )
        store.try_finalize_running(
            session_id, {"status": "error", "last_error": _short(exc)}
        )


@_metered("article_planning")
@_cancellable
def run_plan_job(session_id: str, direct: bool = False) -> None:
    """§7.10: SERP for candidate primaries + per-silo orchestrator + dedup.
    With direct=True, skips the orchestrator (groupings -> articles + dedup)."""
    bind_session_id(session_id)
    try:
        session = store.get_session(session_id)
        log_topics = (session.get("statistical_clustering_log") or {}).get("topics") or {}
        topics_meta = {t["id"]: t for t in store.list_topics(session_id)}
        embeddings = store.get_topic_embeddings(session_id)
        relevance_by_topic = store.get_active_keyword_relevance(session_id)
        topic_inputs = [
            TopicInput(
                id=tid,
                name=meta.get("name") or "",
                rationale=meta.get("rationale") or "",
                relationship_type=meta.get("relationship_type") or "",
                embedding=embeddings.get(tid),
                groupings=[
                    GroupingInput(
                        id=str(g.get("id") or f"{tid}:g{i}"),
                        representative=str(g.get("representative") or ""),
                        cohesion=float(g.get("cohesion") or 0.0),
                        size=int(g.get("size") or len(g.get("keywords") or [])),
                        keywords=[str(k) for k in (g.get("keywords") or [])],
                    )
                    for i, g in enumerate((log_topics.get(tid) or {}).get("groupings") or [])
                ],
                keyword_relevance=relevance_by_topic.get(tid, {}),
            )
            for tid, meta in topics_meta.items()
        ]
        s = get_settings()
        result = run_article_planning(
            topics=topic_inputs,
            dfs=get_dataforseo(store.session_location_code(session)),
            orchestrator=get_orchestrator(),
            embed_fn=get_llm().embed,
            candidate_serp_top_n=s.candidate_serp_top_n,
            candidate_serp_max_workers=s.candidate_serp_max_workers,
            candidate_serp_time_budget_s=s.candidate_serp_time_budget_s,
            groupings_per_call=s.orchestrator_groupings_per_call,
            max_workers=s.orchestrator_max_workers,
            dedup_primary_cosine_threshold=s.dedup_primary_cosine_threshold,
            dedup_serp_overlap_min=s.dedup_serp_overlap_min,
            direct=direct,
            split_oversized=s.split_oversized_articles,
            split_min_keywords=s.split_min_keywords,
            split_resolution=s.split_resolution,
            split_edge_threshold=s.split_edge_threshold,
            split_min_subarticle_size=s.split_min_subarticle_size,
            peer_grouping=s.peer_entity_grouping,
            peer_min_keywords=s.peer_min_keywords,
            seed_terms=[session["seed_keyword"], *(session.get("aliases") or [])],
            peer_terms=session.get("peer_entities") or [],
            promote_orphan_keywords=s.promote_orphan_keywords,
            orphan_promotion_min_score=s.orphan_promotion_min_score,
        )
        if all_degraded(result):
            # Clear any stale prior plan so an errored run doesn't leave clusters
            # behind that disagree with status=error (review M5).
            store.reset_article_planning(session_id)
            store.try_finalize_running(
                session_id,
                {
                    "status": "error",
                    "orchestrator_log": result.orchestrator_log(),
                    "last_error": "Article planning failed on every silo "
                    "(orchestrator unavailable). Statistical clustering preserved.",
                },
            )
            return
        store.reset_article_planning(session_id)
        store.persist_article_plan(session_id, result, get_llm().embed)
        store.try_finalize_running(
            session_id,
            {"orchestrator_log": result.orchestrator_log(), "status": "complete"},
        )
        logger.info(
            "step_complete",
            extra={"event": "step_complete", "step": "plan_job", **result.counts()},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "step_failed",
            extra={"event": "step_failed", "step": "plan_job", "reason": repr(exc)},
        )
        store.try_finalize_running(
            session_id, {"status": "error", "last_error": _short(exc)}
        )


@_metered("regate")
@_cancellable
def run_regate_job(
    session_id: str, threshold: float, edge_threshold: float, resolution: float,
    active_per_silo_cap: int, seed_terms: list[str], peer_terms: list[str],
) -> None:
    """Re-gate + re-cluster a session's stored keyword pool at a new threshold and
    clustering granularity, skipping DataForSEO. Clears any prior article plan."""
    bind_session_id(session_id)
    try:
        session = store.get_session(session_id)
        pool = store.list_all_keyword_pool(session_id)
        topics = store.list_topics(session_id)
        topic_names = {t["id"]: t["name"] for t in topics}
        topic_embeddings = store.get_topic_embeddings(session_id)
        s = get_settings()
        gc = gate_and_cluster(
            per_topic_lists=pool,
            topic_names=topic_names,
            topic_embeddings=topic_embeddings,
            embed_fn=get_llm().embed,
            relevance_threshold=threshold,
            relevance_embed_batch=s.relevance_embed_batch,
            clustering_edge_threshold=edge_threshold,
            clustering_resolution=resolution,
            clustering_max_nodes=s.clustering_max_nodes,
            active_per_silo_cap=active_per_silo_cap,
            seed_terms=seed_terms,
            peer_terms=peer_terms,
            assign_best_silo=s.relevance_assign_best_silo,
            llm_router=_maybe_llm_router(session["seed_keyword"], topics),
            llm_router_margin=s.llm_routing_margin_threshold,
            language_filter=_maybe_language_filter(),
        )
        store.reset_article_planning(session_id)
        store.delete_keywords_for_session(session_id)
        store.insert_classified_keywords(session_id, gc.per_topic_gated)
        _maybe_enrich_metrics(session, gc.per_topic_gated)
        store.try_finalize_running(
            session_id,
            {
                "statistical_clustering_log": gc.clustering_log,
                "orchestrator_log": None,
                "status": "awaiting_article_planning",
            },
        )
        logger.info(
            "step_complete",
            extra={"event": "step_complete", "step": "regate_job",
                   "threshold": threshold, **gc.counts()},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "step_failed",
            extra={"event": "step_failed", "step": "regate_job", "reason": repr(exc)},
        )
        store.try_finalize_running(
            session_id, {"status": "error", "last_error": _short(exc)}
        )


@_metered("recursive_fanout")
@_cancellable
def run_fanout_job(
    session_id: str, threshold: float, edge_threshold: float, resolution: float,
    active_per_silo_cap: int, seed_terms: list[str], peer_terms: list[str],
) -> None:
    """§7.7 Recursive Fanout (Phase 1): re-expand each silo's top cluster
    representatives as sub-anchors, merge the new keywords into the stored pool,
    then re-run the gate + clustering on the enlarged pool. Mining stays off at
    this level. Depth is capped at 1 — this never recurses on its own output."""
    bind_session_id(session_id)
    try:
        session = store.get_session(session_id)
        topics = store.list_topics(session_id)
        topic_names = {t["id"]: t["name"] for t in topics}
        topic_ids = [t["id"] for t in topics]
        s = get_settings()
        seed = session["seed_keyword"]

        sub_anchors = derive_sub_anchors(
            clustering_log=session.get("statistical_clustering_log") or {},
            topic_ids=topic_ids,
            per_silo=s.fanout_subanchors_per_silo,
        )
        total_sub_anchors = sum(len(v) for v in sub_anchors.values())
        time_budget = min(
            float(s.fanout_time_budget_cap_s),
            max(s.fanout_time_budget_floor_s,
                s.fanout_time_budget_per_anchor_s * total_sub_anchors),
        )
        recursive_pool, degraded, _timed_out = run_recursive_expansion(
            seed=seed,
            sub_anchors=sub_anchors,
            dfs=get_dataforseo(store.session_location_code(session)),
            keyword_ideas_limit=s.keyword_ideas_limit,
            paa_tier1_seeds=s.paa_tier1_seeds,
            paa_tier2_cap=s.paa_tier2_cap,
            autocomplete_max=s.autocomplete_max,
            max_workers=s.fanout_subanchor_max_workers,
            time_budget_s=time_budget,
        )

        pool = store.list_all_keyword_pool(session_id)
        merged = merge_into_pool(pool, recursive_pool)
        topic_embeddings = store.get_topic_embeddings(session_id)
        gc = gate_and_cluster(
            per_topic_lists=merged,
            topic_names=topic_names,
            topic_embeddings=topic_embeddings,
            embed_fn=get_llm().embed,
            relevance_threshold=threshold,
            relevance_embed_batch=s.relevance_embed_batch,
            clustering_edge_threshold=edge_threshold,
            clustering_resolution=resolution,
            clustering_max_nodes=s.clustering_max_nodes,
            active_per_silo_cap=active_per_silo_cap,
            seed_terms=seed_terms,
            peer_terms=peer_terms,
            assign_best_silo=s.relevance_assign_best_silo,
            llm_router=_maybe_llm_router(session["seed_keyword"], topics),
            llm_router_margin=s.llm_routing_margin_threshold,
            language_filter=_maybe_language_filter(),
        )
        store.reset_article_planning(session_id)
        store.delete_keywords_for_session(session_id)
        store.insert_classified_keywords(session_id, gc.per_topic_gated)
        _maybe_enrich_metrics(session, gc.per_topic_gated)
        new_settings = {**(session.get("settings") or {}), "recursive_fanout": True}
        store.try_finalize_running(
            session_id,
            {
                "settings": new_settings,
                "statistical_clustering_log": gc.clustering_log,
                "orchestrator_log": None,
                "status": "awaiting_article_planning",
            },
        )
        logger.info(
            "step_complete",
            extra={"event": "step_complete", "step": "fanout_job",
                   "sub_anchors": total_sub_anchors, "time_budget_s": time_budget,
                   "degraded": bool(degraded), **gc.counts()},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "step_failed",
            extra={"event": "step_failed", "step": "fanout_job", "reason": repr(exc)},
        )
        store.try_finalize_running(
            session_id, {"status": "error", "last_error": _short(exc)}
        )


@_metered("architecture")
@_cancellable
def run_architecture_job(session_id: str) -> None:
    """§7.11 Site Architecture: one pillar per article-bearing silo + the internal
    linking matrix, persisted to site_architecture. Reads the article plan
    produced by /plan-articles; never re-plans. Idempotent — re-running upserts
    the architecture row (PRD §9.3 "Regenerate architecture")."""
    bind_session_id(session_id)
    try:
        session = store.get_session(session_id)
        clusters = store.list_clusters(session_id)
        topics = store.list_topics(session_id)
        kw_texts = store.get_keyword_texts(
            [c["primary_keyword_id"] for c in clusters if c.get("primary_keyword_id")]
        )

        by_topic: dict[str, list[ArticleInput]] = {}
        for c in clusters:
            by_topic.setdefault(c["topic_id"], []).append(
                ArticleInput(
                    id=c["id"],
                    name=c["name"],
                    primary_keyword=kw_texts.get(c.get("primary_keyword_id") or "")
                    or c["name"],
                    intent=c.get("intent") or "informational",
                    peer_article_links=c.get("peer_article_links") or [],
                )
            )

        pillars_input: list[PillarInput] = []
        skipped: list[str] = []
        for t in topics:
            arts = by_topic.get(t["id"]) or []
            if not arts:
                skipped.append(t["name"])
                continue
            pillars_input.append(
                PillarInput(
                    topic_id=t["id"],
                    silo_name=t["name"],
                    rationale=t.get("rationale") or "",
                    relationship_type=t.get("relationship_type") or "",
                    articles=arts,
                )
            )

        s = get_settings()
        # Architecture generation is fully deterministic now (no architect LLM —
        # the writer owns pillar editorial), so there is no all-degraded failure
        # mode to guard against; DB/embedding read failures are caught below.
        result = run_architecture_generation(
            seed=session["seed_keyword"],
            audience=session.get("detected_audience") or "",
            pillars_input=pillars_input,
            topic_embeddings=store.get_topic_embeddings(session_id),
            cluster_centroids=store.get_cluster_centroids(session_id),
            skipped_silos=skipped,
            pillar_lateral_cosine_threshold=s.architecture_pillar_lateral_cosine,
            pillar_lateral_links_max=s.architecture_pillar_lateral_links_max,
            pillar_down_links_max=s.architecture_pillar_down_links_max,
            lateral_article_links_max=s.architecture_lateral_article_links_max,
        )
        store.persist_architecture(session_id, result.architecture_json())
        store.try_finalize_running(session_id, {"status": "complete"})
        # No-orphan / no-dangling invariant audit (§15.2 #3) on the live graph, not
        # just by construction. A non-zero count means a regression — surface it.
        health = result.link_health()
        if health["orphan_articles"] or health["orphan_pillars"] or health["dangling_links"]:
            logger.warning(
                "architecture_link_health_violation",
                extra={"event": "architecture_link_health_violation", **health},
            )
        logger.info(
            "step_complete",
            extra={
                "event": "step_complete", "step": "architecture_job",
                **result.counts(), **health,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "step_failed",
            extra={"event": "step_failed", "step": "architecture_job", "reason": repr(exc)},
        )
        store.try_finalize_running(
            session_id, {"status": "error", "last_error": _short(exc)}
        )


# ----- M12 SIE Term & Entity analysis ---------------------------------------
def submit_sie(
    session_id: str, cluster_id: str, keyword: str, location_code: int,
    *, language_code: str = "en", outlier_mode: str = "safe", force_refresh: bool = False,
) -> None:
    _EXECUTOR.submit(
        run_sie_job, session_id, cluster_id, keyword, location_code,
        language_code, outlier_mode, force_refresh,
    )


@_metered("sie_analysis")
@_cancellable
def run_sie_job(
    session_id: str, cluster_id: str, keyword: str, location_code: int,
    language_code: str = "en", outlier_mode: str = "safe", force_refresh: bool = False,
) -> None:
    """Run the SIE pipeline for one cluster keyword and cache the result
    (docs/sie-module-plan.md §3). Metered under the `sie_analysis` phase. On
    failure, logs and leaves the cache empty (the report GET then 404s)."""
    from fanout.cost_meter import current_meter
    from fanout.sie import cache as sie_cache
    from fanout.sie import pipeline as sie_pipeline

    # Race guard: a fresh row may have landed between the endpoint's miss and here.
    if not force_refresh and sie_cache.get_fresh_analysis(keyword, location_code):
        return
    meter = current_meter()
    before = meter.snapshot()[0] if meter else 0.0
    try:
        deps = sie_pipeline.build_deps(location_code)
        output = sie_pipeline.analyze(
            keyword, location_code=location_code, language_code=language_code,
            outlier_mode=outlier_mode, deps=deps,
        )
    except Exception as exc:  # noqa: BLE001 — SIE is a side analysis; never crash the worker
        logger.error(
            "step_failed",
            extra={"event": "step_failed", "step": "sie_job",
                   "keyword": keyword, "reason": repr(exc)},
        )
        return
    cost = round((meter.snapshot()[0] if meter else 0.0) - before, 6)
    sie_cache.save_analysis(
        keyword=keyword, location_code=location_code, language_code=language_code,
        outlier_mode=outlier_mode, output_json=output.model_dump(), cost_usd=cost,
        session_id=session_id, cluster_id=cluster_id,
    )
    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "sie_job", "keyword": keyword,
               "required_terms": len(output.terms.required), "cost_usd": cost},
    )


# ----- M13 Brief Generator (answer-engine-first) ----------------------------
def submit_brief(
    session_id: str, cluster_id: str, keyword: str, location_code: int,
    *, language_code: str = "en", force_refresh: bool = False,
) -> None:
    _EXECUTOR.submit(
        run_brief_job, session_id, cluster_id, keyword, location_code,
        language_code, force_refresh,
    )


def _cluster_intent_override(cluster_id: str) -> tuple[str | None, bool]:
    """(intent_override, locked) for a cluster: the override is the cluster's intent only
    when the owner deliberately locked it (intent_locked)."""
    from fanout.storage import silo as store
    cluster = store.get_cluster(cluster_id)
    if cluster and cluster.get("intent_locked"):
        return cluster.get("intent"), True
    return None, False


def _sync_cluster_intent(cluster_id: str, brief_output: dict, locked: bool) -> None:
    """Write the brief's classified intent back to the cluster (cosmetic UI sync) unless
    the owner locked it. Never fails the job."""
    if locked:
        return
    intent = brief_output.get("intent_type")
    if not intent:
        return
    try:
        from fanout.storage import silo as store
        store.sync_cluster_intent(cluster_id, intent)
    except Exception:  # noqa: BLE001 — cosmetic sync; never fail the job
        pass


@_metered("brief_generation")
@_cancellable
def run_brief_job(
    session_id: str, cluster_id: str, keyword: str, location_code: int,
    language_code: str = "en", force_refresh: bool = False,
) -> None:
    """Run the Brief Generator for one cluster keyword and cache the v2.6 BriefOutput
    (Writer Input A) in `fanout.briefs`. Mirrors `run_sie_job`: metered under the
    `brief_generation` phase, runs lazily at write time only. `generate_brief` raises
    on a load-bearing failure (no degraded-brief fallback, owner rule) — caught here so
    the worker survives; the cache stays empty and the report GET then 404s."""
    from fanout.briefgen import cache as brief_cache
    from fanout.briefgen.pipeline import build_brief_deps, generate_brief
    from fanout.cost_meter import current_meter

    override, locked = _cluster_intent_override(cluster_id)
    # Race/staleness guard: a fresh row is reusable unless a locked override now disagrees
    # with its intent (then regenerate). Sync the dropdown even on a reuse.
    existing = brief_cache.get_fresh_brief(keyword, location_code)
    if not force_refresh and existing and not (
        override and existing["output_json"].get("intent_type") != override
    ):
        _sync_cluster_intent(cluster_id, existing["output_json"], locked)
        return
    meter = current_meter()
    before = meter.snapshot()[0] if meter else 0.0
    try:
        from fanout.storage import silo as store

        supporting = store.get_cluster_supporting_keywords(cluster_id)
        deps = build_brief_deps(location_code)
        output = generate_brief(
            keyword, location_code=location_code, deps=deps, intent_override=override,
            supporting_keywords=supporting)
    except Exception as exc:  # noqa: BLE001 — brief is a side analysis; never crash the worker
        logger.error(
            "step_failed",
            extra={"event": "step_failed", "step": "brief_job",
                   "keyword": keyword, "reason": repr(exc)},
        )
        return
    cost = round((meter.snapshot()[0] if meter else 0.0) - before, 6)
    brief_cache.save_brief(
        keyword=keyword, location_code=location_code, language_code=language_code,
        output_json=output.model_dump(), cost_usd=cost,
        session_id=session_id, cluster_id=cluster_id,
    )
    _sync_cluster_intent(cluster_id, output.model_dump(), locked)
    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "brief_job", "keyword": keyword,
               "headings": len(output.heading_structure), "cost_usd": cost},
    )


# ----- M14 Content Writer (article generation) ------------------------------
# Per-cluster in-process guard so a double-submit doesn't run two generations
# concurrently (single Railway instance; survives within one process only — flagged).
_article_inflight: set[str] = set()
_article_lock = threading.Lock()


def article_inflight(cluster_id: str) -> bool:
    with _article_lock:
        return cluster_id in _article_inflight


def submit_article(
    session_id: str, cluster_id: str, keyword: str, location_code: int,
    *, force_refresh: bool = False,
) -> bool:
    """Claim the cluster + submit. Returns False if that cluster is already generating."""
    with _article_lock:
        if cluster_id in _article_inflight:
            return False
        _article_inflight.add(cluster_id)
    _EXECUTOR.submit(run_article_job, session_id, cluster_id, keyword, location_code, force_refresh)
    return True


def _inject_internal_links(session_id: str, cluster_id: str, article) -> None:
    """M15 — wrap the M6 architecture link graph into the article as absolute internal
    links, then re-serialize. No-op when the session has no `site_base_url` or no generated
    architecture. Enrichment only — any failure is swallowed (the article still ships)."""
    try:
        from fanout.storage import silo as store
        from fanout.writer.link_injector import inject_links
        from fanout.writer.link_targets import build_targets
        from fanout.writer.serialize import to_html, to_markdown

        session = store.get_session(session_id)
        base_url = (session or {}).get("site_base_url")
        arch_row = store.get_architecture(session_id)
        if not base_url or not arch_row:
            return
        architecture = arch_row["architecture_json"]
        slugs = store.ensure_session_slugs(session_id)
        clusters = store.list_clusters_link_info(session_id)
        clusters_by_id = {c["id"]: {**c, "slug": slugs.get(c["id"], c.get("slug"))} for c in clusters}
        topics_by_id = {t["id"]: t for t in store.list_topics(session_id)}
        keywords_by_id = store.get_keyword_texts(
            [c["primary_keyword_id"] for c in clusters if c.get("primary_keyword_id")])

        targets, is_pillar = build_targets(
            cluster_id, architecture=architecture, clusters_by_id=clusters_by_id,
            topics_by_id=topics_by_id, keywords_by_id=keywords_by_id, base_url=base_url)
        if not targets:
            return
        result = inject_links(article.article, targets, is_pillar=is_pillar)
        article.article = result.article
        article.article_markdown = to_markdown(result.article)
        article.article_html = to_html(result.article)
        article.metadata["internal_links"] = {
            "linked": result.linked,
            "related_fallback": [t.url for t in result.related],
            "target_count": len(targets),
        }
    except Exception as exc:  # noqa: BLE001 — linking is enrichment; never fail the article
        logger.warning(
            "internal_link_injection_failed",
            extra={"event": "internal_link_injection_failed", "cluster_id": cluster_id,
                   "reason": repr(exc)},
        )


def _attach_unused_keywords(cluster_id: str, brief_json: dict, article) -> None:
    """Copy the brief coverage audit's uncovered keywords onto article.metadata.unused_keywords
    (the source for the in-app 'write these as separate articles?' prompt). No-op on an
    auto-split child cluster — its keywords are its own topic, so it never re-prompts."""
    try:
        from fanout.storage import silo as store

        cluster = store.get_cluster(cluster_id)
        if cluster and cluster.get("auto_split"):
            return
        cov = (brief_json.get("metadata") or {}).get("cluster_keyword_coverage") or {}
        uncovered = [u.get("keyword") for u in cov.get("uncovered", []) if u.get("keyword")]
        if uncovered:
            article.metadata["unused_keywords"] = uncovered
    except Exception as exc:  # noqa: BLE001 — annotation only; never fail the article
        logger.warning(
            "unused_keyword_attach_failed",
            extra={"event": "unused_keyword_attach_failed", "cluster_id": cluster_id,
                   "reason": repr(exc)},
        )


def split_uncovered_and_write(
    session_id: str, cluster_id: str, keyword: str, location_code: int,
) -> dict:
    """Owner-confirmed: group the cluster's uncovered keywords (cosine ~0.85 so near-dupes
    share one article, never one-per-keyword), split each group into a new auto-split article,
    and queue it for generation. Returns the created articles + counts. Recursion-guarded by
    the auto_split flag; uncapped (owner choice)."""
    from fanout.briefgen import cache as brief_cache
    from fanout.briefgen.coverage import _dedupe, greedy_group
    from fanout.config import get_settings
    from fanout.llm import get_llm
    from fanout.storage import silo as store

    brief_row = brief_cache.get_fresh_brief(keyword, location_code)
    cov = ((brief_row or {}).get("output_json", {}).get("metadata") or {}).get(
        "cluster_keyword_coverage") or {}
    uncovered_texts = _dedupe([u.get("keyword") for u in cov.get("uncovered", []) if u.get("keyword")])
    if not uncovered_texts:
        return {"created": [], "submitted": 0, "uncovered": 0}

    # Map uncovered texts -> the cluster's actual keyword rows (non-primary members).
    rows = store.get_cluster_keyword_rows(cluster_id)
    id_by_text = {
        r["keyword"].strip().lower(): r["id"]
        for r in rows if r.get("keyword") and not r.get("is_primary_for_cluster")
    }
    pairs = [(t, id_by_text[t.strip().lower()]) for t in uncovered_texts if t.strip().lower() in id_by_text]
    if not pairs:
        return {"created": [], "submitted": 0, "uncovered": len(uncovered_texts)}

    texts = [t for t, _ in pairs]
    vecs = get_llm().embed(texts)
    groups = greedy_group(texts, vecs, threshold=get_settings().auto_split_group_threshold)
    id_of = {t: kid for t, kid in pairs}

    created: list[dict] = []
    for group in groups:
        # Representative = the longest phrasing (most specific) -> the new article's primary + name.
        rep = max(group, key=lambda t: (len(t.split()), len(t)))
        group_ids = [id_of[t] for t in group]
        try:
            new_cluster = store.split_cluster(cluster_id, group_ids, new_name=rep, new_primary_id=id_of[rep])
        except ValueError:
            continue
        store.mark_cluster_auto_split(new_cluster["id"])
        submitted = submit_article(session_id, new_cluster["id"], rep, location_code)
        created.append({"cluster_id": new_cluster["id"], "name": rep,
                        "keywords": group, "submitted": submitted})

    return {
        "created": created,
        "submitted": sum(1 for c in created if c["submitted"]),
        "uncovered": len(uncovered_texts),
    }


@_metered("article_generation")
@_cancellable
def run_article_job(
    session_id: str, cluster_id: str, keyword: str, location_code: int,
    force_refresh: bool = False,
) -> None:
    """Ad-hoc article generation (the Generate button). Thin wrapper: meter-bind + the
    per-cluster inflight guard; the body lives in `generate_article_core` (shared with the
    scheduler worker)."""
    try:
        generate_article_core(session_id, cluster_id, keyword, location_code, force_refresh)
    finally:
        with _article_lock:
            _article_inflight.discard(cluster_id)


def generate_article_core(
    session_id: str, cluster_id: str, keyword: str, location_code: int,
    force_refresh: bool = False, *, scheduled_article_run_id: str | None = None,
) -> bool:
    """Generate one article for a cluster's keyword and persist it. Stage 1 ensures the Brief
    (Input A) and SIE (Input C) exist (running them on a miss), then the Writer runs the
    degraded 1.7-no-context flow and the result is persisted to `fanout.article_outputs`.
    Returns True on success; on a WriterAbort / load-bearing failure logs, persists nothing,
    and returns False. The caller owns metering + any inflight guard."""
    from fanout.briefgen import cache as brief_cache
    from fanout.cost_meter import current_meter
    from fanout.sie import cache as sie_cache
    from fanout.writer.adapter import build_writer_inputs
    from fanout.writer.models import WriterAbort
    from fanout.writer.pipeline import build_writer_deps, generate_article

    s = get_settings()
    meter = current_meter()
    before = meter.snapshot()[0] if meter else 0.0
    try:
        # Stage 1a — ensure the Brief. A locked owner intent overrides classification and
        # forces a regenerate if the cached brief disagrees; otherwise sync the cluster
        # dropdown to the brief's classified intent.
        override, locked = _cluster_intent_override(cluster_id)
        brief_row = brief_cache.get_fresh_brief(keyword, location_code)
        if brief_row and override and brief_row["output_json"].get("intent_type") != override:
            brief_row = None
        if not brief_row:
            from fanout.briefgen.pipeline import build_brief_deps, generate_brief
            from fanout.storage import silo as store
            b = generate_brief(
                keyword, location_code=location_code,
                deps=build_brief_deps(location_code), intent_override=override,
                supporting_keywords=store.get_cluster_supporting_keywords(cluster_id))
            brief_row = brief_cache.save_brief(
                keyword=keyword, location_code=location_code, language_code="en",
                output_json=b.model_dump(), cost_usd=None, session_id=session_id,
                cluster_id=cluster_id,
            )
        _sync_cluster_intent(cluster_id, brief_row["output_json"], locked)
        # Stage 1b — ensure the SIE analysis.
        sie_row = sie_cache.get_fresh_analysis(keyword, location_code)
        if not sie_row:
            from fanout.sie import pipeline as sie_pipeline
            out = sie_pipeline.analyze(
                keyword, location_code=location_code, language_code="en",
                outlier_mode="safe", deps=sie_pipeline.build_deps(location_code),
            )
            sie_row = sie_cache.save_analysis(
                keyword=keyword, location_code=location_code, language_code="en",
                outlier_mode="safe", output_json=out.model_dump(), cost_usd=None,
                session_id=session_id, cluster_id=cluster_id,
            )
        # Stage 2 — Writer.
        brief, sie, warnings = build_writer_inputs(
            brief_row["output_json"], sie_row["output_json"],
        )
        article = generate_article(
            brief, sie, warnings=warnings, deps=build_writer_deps(),
            word_budget=s.writer_word_budget, coverage_enabled=s.writer_claim_coverage_enabled,
            timeout_s=s.writer_timeout_s, adherence_threshold=s.writer_adherence_threshold,
        )
        # M15 — deterministic internal-link injection (enrichment; never fails the article).
        _inject_internal_links(session_id, cluster_id, article)
        # Surface the clustered keywords no heading covered, so the UI can prompt the owner
        # to write them as separate articles. Suppressed on auto-split children (recursion guard).
        _attach_unused_keywords(cluster_id, brief_row["output_json"], article)
    except WriterAbort as exc:
        logger.error(
            "step_failed",
            extra={"event": "step_failed", "step": "article_job", "keyword": keyword,
                   "reason": f"{exc.code}: {exc.message}"},
        )
        return False
    except Exception as exc:  # noqa: BLE001 — side analysis; never crash the worker
        logger.error(
            "step_failed",
            extra={"event": "step_failed", "step": "article_job", "keyword": keyword,
                   "reason": repr(exc)},
        )
        return False

    cost = round((meter.snapshot()[0] if meter else 0.0) - before, 6)
    from fanout.writer import store as article_store
    article_store.save_article(
        cluster_id=cluster_id, session_id=session_id, article_json=article.model_dump(),
        article_markdown=article.article_markdown, article_html=article.article_html,
        total_word_count=article.metadata.get("total_word_count"), cost_usd=cost,
        schema_version_effective=article.client_context_summary.get(
            "schema_version_effective", "1.7-no-context"),
        scheduled_article_run_id=scheduled_article_run_id,
    )
    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "article_job", "keyword": keyword,
               "words": article.metadata.get("total_word_count"),
               "sections": article.metadata.get("section_count"), "cost_usd": cost},
    )
    return True


# ---- Pre-publish ranking check (per client) -------------------------------
def submit_prepublish_rank_check(session_id: str) -> None:
    """Run the pre-publish ranking check off the request path. Orthogonal to the
    pipeline status machine — it writes only `sessions.prepublish_rank_check`, so
    the content map stays visible while it runs (the frontend polls /summary)."""
    _EXECUTOR.submit(run_prepublish_rank_check_job, session_id)


def _utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


@_metered("prepublish_rank_check")
def run_prepublish_rank_check_job(session_id: str) -> None:
    """For every planned article's target keyword (supporting clusters + pillars),
    determine whether the client already ranks top-10: GSC first (free, instant),
    DataForSEO SERP for the residue. Persist the per-keyword result on the session
    so the cluster/architecture review renders badges without re-fetching."""
    bind_session_id(session_id)
    store.update_session(
        session_id,
        {"prepublish_rank_check": {"status": "running", "as_of": _utcnow_iso()}},
    )
    try:
        session = store.get_session(session_id) or {}
        client_id = session.get("client_id")

        # Targets: supporting articles (clusters) + pillars (architecture).
        targets: list[dict] = [
            {"cluster_id": c["id"], "keyword": c["name"]}
            for c in store.list_clusters(session_id)
            if c.get("name") and not c.get("is_gap_placeholder")
        ]
        arch = store.get_architecture(session_id)
        if arch:
            for p in (arch.get("architecture_json") or {}).get("pillars", []):
                kw = (p.get("target_keyword") or "").strip()
                if kw:
                    targets.append({"cluster_id": None, "keyword": kw,
                                    "topic_id": p.get("topic_id"), "is_pillar": True})

        keywords = sorted({prepublish_rank.norm_keyword(t["keyword"]) for t in targets})

        # 1) GSC (bulk, free). 2) DataForSEO for the residue (location-aware).
        gsc = prepublish_rank.gsc_lookup(client_id, keywords) if client_id else {}
        residue = [k for k in keywords if k not in gsc]
        domain = prepublish_rank.client_domain(client_id) if client_id else None
        dfs_map: dict[str, dict] = {}
        if residue and domain:
            dfs = get_dataforseo(store.session_location_code(session))
            dfs_map = prepublish_rank.dataforseo_lookup(dfs, domain, residue)

        results: list[dict] = []
        ranked = 0
        for t in targets:
            nk = prepublish_rank.norm_keyword(t["keyword"])
            hit = gsc.get(nk) or dfs_map.get(nk)
            if hit:
                ranked += 1
            results.append({
                "cluster_id": t.get("cluster_id"),
                "keyword": t["keyword"],
                "is_pillar": t.get("is_pillar", False),
                "ranked": bool(hit),
                "position": hit["position"] if hit else None,
                "url": hit["url"] if hit else None,
                "source": hit["source"] if hit else None,
            })

        store.update_session(session_id, {"prepublish_rank_check": {
            "status": "complete",
            "as_of": _utcnow_iso(),
            "checked": len(results),
            "ranked": ranked,
            "gsc_connected": bool(gsc) or bool(client_id),
            "results": results,
        }})
        logger.info(
            "step_complete",
            extra={"event": "step_complete", "step": "prepublish_rank_check",
                   "checked": len(results), "ranked": ranked,
                   "dataforseo_swept": len(dfs_map)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "step_failed",
            extra={"event": "step_failed", "step": "prepublish_rank_check",
                   "reason": _short(exc)},
        )
        store.update_session(session_id, {"prepublish_rank_check": {
            "status": "error", "as_of": _utcnow_iso(), "error": _short(exc),
        }})
