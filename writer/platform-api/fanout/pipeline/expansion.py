"""Per-silo keyword expansion (PRD §7.3) + autocomplete enrichment (§7.5).

keyword_ideas and PAA (two tiers deep) run per silo on the silo anchor.
keyword_suggestions and query_fanouts are phrase/seed-match endpoints that only
yield volume on a real, searched keyword, so they run once on the bare seed and
their results attach to every silo (the M4 relevance gate sorts them per-silo).
All of this runs in parallel; the deduped pool is then enriched via
autocomplete. A failure on one endpoint degrades that pool but never blocks the
others (§16.2).

M3 stops here: keywords are persisted raw with source attribution. Relevance
gating, competitor mining, and clustering are M4.
"""

import logging
import time
from concurrent.futures import as_completed
from dataclasses import dataclass, field

from fanout.concurrency import ContextThreadPoolExecutor as ThreadPoolExecutor
from fanout.dataforseo import DataForSEOClient

logger = logging.getLogger(__name__)


@dataclass
class ExpansionTopic:
    id: str
    anchor: str
    name: str = ""  # friendly silo name for UI messages; falls back to anchor


@dataclass
class ExpansionResult:
    # topic_id -> {normalized_keyword: sorted list of source tags}
    per_topic: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    degraded_notes: list[str] = field(default_factory=list)
    timed_out: bool = False  # hit the time budget (logged; not surfaced to the user)

    @property
    def total_keywords(self) -> int:
        return sum(len(kws) for kws in self.per_topic.values())


def _normalize(kw: str) -> str:
    return " ".join(kw.strip().lower().split())


def build_anchor(seed: str, silo_name: str) -> str:
    """Seed-qualify the expansion anchor so DataForSEO returns seed-relevant
    keywords. If the silo name already contains the seed (e.g. "how retatrutide
    works") it's used as-is; otherwise the seed is prepended (e.g. "weight loss
    use" -> "retatrutide weight loss use")."""
    seed = seed.strip()
    silo_name = silo_name.strip()
    if seed.lower() in silo_name.lower():
        return silo_name
    return f"{seed} {silo_name}".strip()


def _add(pool: dict[str, set[str]], keyword: str, source: str) -> None:
    if not isinstance(keyword, str):
        return  # tolerate a malformed (non-string) element in a source result
    norm = _normalize(keyword)
    if norm:
        pool.setdefault(norm, set()).add(source)


def run_expansion(
    *,
    seed: str,
    topics: list[ExpansionTopic],
    dfs: DataForSEOClient,
    keyword_ideas_limit: int = 1000,
    keyword_suggestions_limit: int = 500,
    query_fanouts_limit: int = 300,
    paa_tier1_seeds: int = 8,
    paa_tier2_cap: int = 40,
    autocomplete_max: int = 1500,
    max_workers: int = 8,
    time_budget_s: float = 240.0,
    include_seed_level: bool = True,
) -> ExpansionResult:
    result = ExpansionResult()
    deadline = time.monotonic() + time_budget_s
    capped = False
    # topic_id -> {keyword: set(sources)}
    pools: dict[str, dict[str, set[str]]] = {t.id: {} for t in topics}

    def paa_two_tier(anchor: str) -> tuple[list[str], list[str]]:
        tier1 = dfs.people_also_ask(anchor)
        tier2: list[str] = []
        for q in tier1[:paa_tier1_seeds]:
            if len(tier2) >= paa_tier2_cap:
                break
            try:
                tier2.extend(dfs.people_also_ask(q))
            except Exception:
                continue
        return tier1, tier2[:paa_tier2_cap]

    # ----- Phase 1: base expansion (parallel) -------------------------------
    # keyword_ideas (broad ideation) and PAA run per silo on the broad silo
    # anchor. keyword_suggestions and query_fanouts are phrase/seed-match
    # endpoints that only yield volume on a real, searched keyword (the bare
    # seed) — a silo-qualified anchor returns near-zero — so they run once on
    # the seed and attach to every silo; M4's relevance gate sorts them
    # per-silo. A None topic in `futures` means "attach to all silos".
    pool_exec = ThreadPoolExecutor(max_workers=max_workers)
    futures = {}
    for t in topics:
        futures[pool_exec.submit(dfs.keyword_ideas, t.anchor, keyword_ideas_limit)] = (
            t, "keyword_ideas")
        futures[pool_exec.submit(paa_two_tier, t.anchor)] = (t, "paa")
    # keyword_suggestions / query_fanouts are bare-seed phrase-match endpoints.
    # Recursive fanout already ran them on the seed in the first pass, so it skips
    # them here (include_seed_level=False) — re-running the same seed only
    # re-pays for identical results.
    if include_seed_level:
        futures[pool_exec.submit(dfs.keyword_suggestions, seed, keyword_suggestions_limit)] = (
            None, "keyword_suggestions")
        futures[pool_exec.submit(dfs.query_fanouts, seed, query_fanouts_limit)] = (
            None, "query_fanouts")

    try:
        for fut in as_completed(futures, timeout=max(0.0, deadline - time.monotonic())):
            topic, source = futures[fut]
            try:
                data = fut.result()
            except Exception as exc:
                # Any failure (HTTP error, non-JSON body, unexpected result
                # shape) degrades this source only; the others still land (§16.2).
                label = (topic.name or topic.anchor) if topic else None
                result.degraded_notes.append(
                    f"Partial expansion for silo “{label}”: {source} unavailable."
                    if label
                    else f"Partial expansion: {source} unavailable."
                )
                logger.warning(
                    "degraded",
                    extra={"event": "degraded", "step": "expansion",
                           "topic": label or "*", "source": source, "reason": str(exc)},
                )
                continue
            if source == "paa":
                tier1, tier2 = data
                for kw in tier1:
                    _add(pools[topic.id], kw, "paa_t1")
                for kw in tier2:
                    _add(pools[topic.id], kw, "paa_t2")
            elif topic is None:
                # Seed-level source (keyword_suggestions / query_fanouts):
                # attach to every silo's pool; the M4 relevance gate sorts them.
                for tid in pools:
                    for kw in data:
                        _add(pools[tid], kw, source)
            else:
                for kw in data:
                    _add(pools[topic.id], kw, source)
    except TimeoutError:
        # Hit the overall time budget. Keep what completed; abandon the rest.
        capped = True
    finally:
        pool_exec.shutdown(wait=False, cancel_futures=True)

    # ----- Phase 2: autocomplete on the deduped pool (§7.5) -----------------
    # (topic_id, keyword) pairs, capped globally to bound cost. Interleave
    # round-robin across topics so the cap is shared fairly (a large first silo
    # doesn't starve later silos of autocomplete).
    per_topic_keys = [(tid, list(kws.keys())) for tid, kws in pools.items()]
    seeds: list[tuple[str, str]] = []
    longest = max((len(ks) for _, ks in per_topic_keys), default=0)
    for i in range(longest):
        if len(seeds) >= autocomplete_max:
            break
        for tid, ks in per_topic_keys:
            if i < len(ks):
                seeds.append((tid, ks[i]))
    seeds = seeds[:autocomplete_max]

    # Only enrich if the time budget hasn't already been spent on base expansion.
    if seeds and not capped and (deadline - time.monotonic()) > 1.0:
        ok = 0
        fail = 0
        ac_additions: list[tuple[str, str]] = []
        ac_exec = ThreadPoolExecutor(max_workers=max_workers)
        ac_futures = {ac_exec.submit(dfs.autocomplete, kw): tid for tid, kw in seeds}
        try:
            for fut in as_completed(ac_futures, timeout=max(0.0, deadline - time.monotonic())):
                tid = ac_futures[fut]
                try:
                    suggestions = fut.result()
                    ok += 1
                except Exception:
                    fail += 1
                    continue
                for sug in suggestions:
                    ac_additions.append((tid, sug))
        except TimeoutError:
            capped = True
        finally:
            ac_exec.shutdown(wait=False, cancel_futures=True)

        # On a clean finish, skip autocomplete entirely if a majority failed
        # (§16.2). On a time-cap, keep whatever completed.
        if not capped and fail and fail / (ok + fail) > 0.5:
            result.degraded_notes.append("Autocomplete enrichment unavailable for this run.")
        else:
            for tid, sug in ac_additions:
                _add(pools[tid], sug, "autocomplete")
    elif seeds and (capped or (deadline - time.monotonic()) <= 1.0):
        capped = True

    if capped:
        result.timed_out = True
        logger.info("step_capped", extra={"event": "step_capped", "step": "expansion"})

    result.per_topic = {
        tid: {kw: sorted(sources) for kw, sources in kws.items()}
        for tid, kws in pools.items()
    }
    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "expansion",
               "topic_count": len(topics), "keyword_count": result.total_keywords,
               "degraded": bool(result.degraded_notes)},
    )
    return result
