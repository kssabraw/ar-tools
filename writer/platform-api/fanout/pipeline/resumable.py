"""Resumable Fanout expansion (issue #686 Phase 2).

Phase 1 made a deploy-interrupted expand run auto-recover, but a requeue re-ran
the whole 6-10 min expansion from scratch — re-paying the DataForSEO spend. This
checkpoints the expensive work per silo (+ the shared seed-level work once) into
`sessions.expansion_checkpoint`, so a requeue rehydrates the silos that already
finished and only re-pays the unfinished ones plus the cheap autocomplete/gate
tail.

Isolation (important): the production `run_expansion` / `run_competitor_mining`
are reused UNCHANGED — each silo is one `run_expansion([silo], include_seed_level
=False)` call (its autocomplete runs per-silo) plus, if gated, one
`run_competitor_mining([silo])`; the seed-level phrase endpoints + seed mine run
once. Nothing in the non-resumable (flag-off) path is touched, so it stays
byte-identical. The whole thing is gated behind `fanout_resumable_expand_enabled`.

Known, deliberate difference from the non-resumable pool: autocomplete runs
per-silo on that silo's ideas+PAA rather than once on the fully-merged pool
(incl. the fanned seed-level keywords), so autocomplete coverage differs
slightly. The gate/cluster stage is identical. Validate on a live flagged run
before trusting it — the pipeline can't be exercised in the sandbox.

The heavy pipeline imports are deferred into the compute functions so the pure
checkpoint helpers below (and their tests) load without the DataForSEO/pipeline
dependency chain.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure checkpoint helpers (no external deps — unit-tested)
# ---------------------------------------------------------------------------
def _normalize(kw: str) -> str:
    """Match expansion._normalize / competitor._normalize so seed-level keywords
    fetched directly here key-collide with the pipeline's normalized keywords."""
    return " ".join(kw.strip().lower().split())


def merge_source_lists(
    a: dict[str, list[str]], b: dict[str, list[str]]
) -> dict[str, list[str]]:
    """Union two {keyword: [sources]} maps into one with per-keyword sources
    deduped and sorted (the shape gate_and_cluster consumes)."""
    out: dict[str, set[str]] = {}
    for src_map in (a, b):
        for kw, sources in (src_map or {}).items():
            out.setdefault(kw, set()).update(sources or [])
    return {kw: sorted(s) for kw, s in out.items()}


def pending_topic_ids(topic_ids: list[str], checkpoint: dict) -> list[str]:
    """Run-scope topics whose per-silo expansion isn't checkpointed yet — the ones
    a (re)start still has to (re-)expand. Order preserved."""
    done = set((checkpoint or {}).get("topics") or {})
    return [tid for tid in topic_ids if tid not in done]


def assemble_pool(
    topic_ids: list[str], checkpoint: dict
) -> dict[str, dict[str, list[str]]]:
    """Fan the shared seed-level pool into every run-scope silo's own pool — the
    full per-topic candidate pool gate_and_cluster expects. Pure over the
    checkpoint (all silos must be present, i.e. call only once expansion is
    complete)."""
    cp = checkpoint or {}
    topics = cp.get("topics") or {}
    seed_pool = cp.get("seed_pool") or {}
    return {tid: merge_source_lists(topics.get(tid) or {}, seed_pool) for tid in topic_ids}


def expansion_complete(topic_ids: list[str], checkpoint: dict) -> bool:
    """True once the seed unit and every run-scope silo are checkpointed."""
    cp = checkpoint or {}
    if not cp.get("seed_done"):
        return False
    return not pending_topic_ids(topic_ids, cp)


# ---------------------------------------------------------------------------
# Config passed to the (impure) compute functions
# ---------------------------------------------------------------------------
@dataclass
class ExpandParams:
    keyword_ideas_limit: int
    keyword_suggestions_limit: int
    query_fanouts_limit: int
    paa_tier1_seeds: int
    paa_tier2_cap: int
    autocomplete_max: int
    expansion_max_workers: int
    expansion_time_budget_s: float
    competitor_top_n: int
    ranked_keywords_limit: int
    competitor_max_position: int
    competitor_max_workers: int
    competitor_time_budget_s: float


@dataclass
class ResumableTopic:
    id: str
    name: str
    gated: bool


# ---------------------------------------------------------------------------
# Impure compute units (reuse the production pipeline functions unchanged)
# ---------------------------------------------------------------------------
def _compute_seed_pool(seed: str, dfs, params: ExpandParams) -> tuple[dict[str, list[str]], list[str]]:
    """The shared seed-level pool: the phrase/seed-match endpoints
    (keyword_suggestions + query_fanouts) plus the always-mined seed's competitor
    keywords. Computed once; fanned to every silo at assembly. Best-effort per
    source (a failing endpoint degrades that source only)."""
    from fanout.pipeline.competitor import run_competitor_mining, MineTopic
    from fanout.pipeline.orchestrate import _SEED_MINE_ID

    pool: dict[str, set[str]] = {}
    notes: list[str] = []
    for fn, source, limit in (
        (dfs.keyword_suggestions, "keyword_suggestions", params.keyword_suggestions_limit),
        (dfs.query_fanouts, "query_fanouts", params.query_fanouts_limit),
    ):
        try:
            for kw in fn(seed, limit):
                if isinstance(kw, str):
                    norm = _normalize(kw)
                    if norm:
                        pool.setdefault(norm, set()).add(source)
        except Exception as exc:  # noqa: BLE001 — degrade this source only
            notes.append(f"Partial expansion: {source} unavailable.")
            logger.warning(
                "degraded", extra={"event": "degraded", "step": "resumable_seed",
                                   "source": source, "reason": str(exc)})

    cm = run_competitor_mining(
        topics=[MineTopic(id=_SEED_MINE_ID, anchor=seed, name=seed)],
        dfs=dfs,
        top_n=params.competitor_top_n,
        ranked_keywords_limit=params.ranked_keywords_limit,
        max_position=params.competitor_max_position,
        max_workers=params.competitor_max_workers,
        time_budget_s=params.competitor_time_budget_s,
    )
    for kw, sources in cm.per_topic.get(_SEED_MINE_ID, {}).items():
        pool.setdefault(kw, set()).update(sources)
    notes.extend(cm.degraded_notes)
    return {kw: sorted(s) for kw, s in pool.items()}, notes


def _compute_topic_pool(
    seed: str, topic: ResumableTopic, dfs, params: ExpandParams, autocomplete_cap: int
) -> tuple[dict[str, list[str]], list[str]]:
    """One silo's own pool: ideas + PAA + per-silo autocomplete (via the
    production run_expansion, seed-level suppressed) plus, if gated, its
    competitor keywords."""
    from fanout.pipeline.expansion import run_expansion, ExpansionTopic, build_anchor
    from fanout.pipeline.competitor import run_competitor_mining, MineTopic

    anchor = build_anchor(seed, topic.name)
    exp = run_expansion(
        seed=seed,
        topics=[ExpansionTopic(id=topic.id, anchor=anchor, name=topic.name)],
        dfs=dfs,
        keyword_ideas_limit=params.keyword_ideas_limit,
        keyword_suggestions_limit=params.keyword_suggestions_limit,
        query_fanouts_limit=params.query_fanouts_limit,
        paa_tier1_seeds=params.paa_tier1_seeds,
        paa_tier2_cap=params.paa_tier2_cap,
        autocomplete_max=autocomplete_cap,
        max_workers=params.expansion_max_workers,
        time_budget_s=params.expansion_time_budget_s,
        include_seed_level=False,
    )
    pool: dict[str, set[str]] = {
        kw: set(sources) for kw, sources in exp.per_topic.get(topic.id, {}).items()
    }
    notes = list(exp.degraded_notes)
    if topic.gated:
        cm = run_competitor_mining(
            topics=[MineTopic(id=topic.id, anchor=anchor, name=topic.name)],
            dfs=dfs,
            top_n=params.competitor_top_n,
            ranked_keywords_limit=params.ranked_keywords_limit,
            max_position=params.competitor_max_position,
            max_workers=params.competitor_max_workers,
            time_budget_s=params.competitor_time_budget_s,
        )
        for kw, sources in cm.per_topic.get(topic.id, {}).items():
            pool.setdefault(kw, set()).update(sources)
        notes.extend(cm.degraded_notes)
    return {kw: sorted(s) for kw, s in pool.items()}, notes


def run_resumable_expansion(
    *,
    seed: str,
    topics: list[ResumableTopic],
    dfs,
    params: ExpandParams,
    checkpoint: dict,
    save,
    raise_if_cancelled=None,
) -> tuple[dict[str, dict[str, list[str]]], list[str]]:
    """Build the full per-topic raw pool, checkpointing after the shared seed
    unit and after each silo so a requeue skips finished work. `save(checkpoint)`
    persists the (mutated) checkpoint dict; `raise_if_cancelled` (optional) is
    checked between units so a /cancel still aborts promptly. Returns
    (per_topic_lists, degraded_notes) ready for gate_and_cluster."""
    checkpoint.setdefault("topics", {})
    checkpoint.setdefault("degraded_notes", [])

    if not checkpoint.get("seed_done"):
        if raise_if_cancelled:
            raise_if_cancelled()
        seed_pool, notes = _compute_seed_pool(seed, dfs, params)
        checkpoint["seed_pool"] = seed_pool
        checkpoint["seed_done"] = True
        checkpoint["degraded_notes"].extend(notes)
        save(checkpoint)

    # Split the global autocomplete budget across silos so the total is bounded
    # to roughly the non-resumable run's cap (which interleaved round-robin).
    n = max(1, len(topics))
    autocomplete_cap = max(0, params.autocomplete_max // n)

    for topic in topics:
        if topic.id in checkpoint["topics"]:
            continue
        if raise_if_cancelled:
            raise_if_cancelled()
        pool, notes = _compute_topic_pool(seed, topic, dfs, params, autocomplete_cap)
        checkpoint["topics"][topic.id] = pool
        checkpoint["degraded_notes"].extend(notes)
        save(checkpoint)

    per_topic_lists = assemble_pool([t.id for t in topics], checkpoint)
    return per_topic_lists, list(checkpoint["degraded_notes"])
