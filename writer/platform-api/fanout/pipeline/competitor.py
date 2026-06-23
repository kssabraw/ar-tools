"""SERP competitor mining (PRD §7.4), gated topics only.

For each topic the user gated for deep-mining: run a SERP on the topic anchor,
take the top N organic URLs (5 in standard mode, 10 in comprehensive), reduce
them to their distinct domains, and pull each domain's `ranked_keywords` for
organic positions 1..20. Surfaced keywords are tagged `competitor`.

A per-domain failure degrades that slice only — the rest still land (§7.4
acceptance criteria, §16.2). Mining is the largest single contributor to the
candidate pool (~3,000–7,500 keywords at the default budget).
"""

import logging
import time
from concurrent.futures import as_completed
from dataclasses import dataclass, field

from fanout.concurrency import ContextThreadPoolExecutor as ThreadPoolExecutor
from fanout.dataforseo import DataForSEOClient

logger = logging.getLogger(__name__)


@dataclass
class MineTopic:
    id: str
    anchor: str
    name: str = ""  # friendly silo name for UI messages; falls back to anchor


@dataclass
class CompetitorResult:
    # topic_id -> {normalized_keyword: ["competitor"]}
    per_topic: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    degraded_notes: list[str] = field(default_factory=list)
    timed_out: bool = False

    @property
    def total_keywords(self) -> int:
        return sum(len(kws) for kws in self.per_topic.values())


def _normalize(kw: str) -> str:
    return " ".join(kw.strip().lower().split())


def run_competitor_mining(
    *,
    topics: list[MineTopic],
    dfs: DataForSEOClient,
    top_n: int = 5,
    ranked_keywords_limit: int = 500,
    max_position: int = 20,
    max_workers: int = 8,
    time_budget_s: float = 240.0,
) -> CompetitorResult:
    """Mine competitor ranked keywords for the gated `topics`. Returns the same
    per-topic shape as expansion so the two pools merge cleanly before the gate."""
    result = CompetitorResult()
    pools: dict[str, dict[str, set[str]]] = {t.id: {} for t in topics}
    if not topics:
        result.per_topic = {}
        return result

    deadline = time.monotonic() + time_budget_s

    # Phase 1: resolve each gated topic's top organic URLs -> distinct domains.
    # A SERP failure degrades that topic only.
    serp_exec = ThreadPoolExecutor(max_workers=max_workers)
    serp_futures = {
        serp_exec.submit(dfs.serp_top_urls, t.anchor, top_n): t for t in topics
    }
    # topic_id -> ordered distinct domains
    topic_domains: dict[str, list[str]] = {t.id: [] for t in topics}
    try:
        for fut in as_completed(serp_futures, timeout=max(0.0, deadline - time.monotonic())):
            topic = serp_futures[fut]
            try:
                urls = fut.result()
            except Exception as exc:
                label = topic.name or topic.anchor
                result.degraded_notes.append(
                    f"Competitor mining for silo “{label}”: SERP lookup unavailable."
                )
                logger.warning(
                    "degraded",
                    extra={"event": "degraded", "step": "competitor_mining",
                           "topic": label, "phase": "serp", "reason": str(exc)},
                )
                continue
            seen: set[str] = set()
            for url in urls:
                dom = dfs.domain_of(url)
                if dom and dom not in seen:
                    seen.add(dom)
                    topic_domains[topic.id].append(dom)
    except TimeoutError:
        result.timed_out = True
    finally:
        serp_exec.shutdown(wait=False, cancel_futures=True)

    # Phase 2: ranked_keywords per (topic, domain), in parallel. A per-domain
    # failure degrades just that domain.
    rk_exec = ThreadPoolExecutor(max_workers=max_workers)
    rk_futures = {}
    for t in topics:
        for dom in topic_domains[t.id]:
            fut = rk_exec.submit(dfs.ranked_keywords, dom, ranked_keywords_limit, max_position)
            rk_futures[fut] = (t, dom)
    try:
        for fut in as_completed(rk_futures, timeout=max(0.0, deadline - time.monotonic())):
            topic, dom = rk_futures[fut]
            try:
                keywords = fut.result()
            except Exception as exc:
                label = topic.name or topic.anchor
                result.degraded_notes.append(
                    f"Competitor mining for silo “{label}”: {dom} unavailable."
                )
                logger.warning(
                    "degraded",
                    extra={"event": "degraded", "step": "competitor_mining",
                           "topic": label, "phase": "ranked_keywords",
                           "domain": dom, "reason": str(exc)},
                )
                continue
            for kw in keywords:
                if not isinstance(kw, str):
                    continue
                norm = _normalize(kw)
                if norm:
                    pools[topic.id].setdefault(norm, set()).add("competitor")
    except TimeoutError:
        result.timed_out = True
    finally:
        rk_exec.shutdown(wait=False, cancel_futures=True)

    result.per_topic = {
        tid: {kw: sorted(sources) for kw, sources in kws.items()}
        for tid, kws in pools.items()
    }
    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "competitor_mining",
               "topic_count": len(topics), "keyword_count": result.total_keywords,
               "degraded": bool(result.degraded_notes)},
    )
    return result
