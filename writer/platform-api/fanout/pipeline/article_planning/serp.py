"""SERP fetch for candidate primary keywords (PRD §7.10.1.3).

The MMR representative of each statistical grouping is treated as a candidate
primary keyword; a SERP (top-10 organic URLs) is fetched for each. These URLs
feed the orchestrator's intent inference and SERP-overlap merge/split decisions.

Parallel + time-budgeted, mirroring competitor mining (§7.4): a per-keyword
failure degrades only that candidate, leaving the rest of the plan intact.
"""

import logging
import time
from concurrent.futures import as_completed
from dataclasses import dataclass, field

from fanout.concurrency import ContextThreadPoolExecutor as ThreadPoolExecutor
from fanout.dataforseo import DataForSEOClient

logger = logging.getLogger(__name__)


@dataclass
class SerpFetchResult:
    per_keyword: dict[str, list[str]] = field(default_factory=dict)
    degraded_notes: list[str] = field(default_factory=list)
    timed_out: bool = False


def fetch_candidate_serps(
    *,
    keywords: list[str],
    dfs: DataForSEOClient,
    top_n: int = 10,
    max_workers: int = 8,
    time_budget_s: float = 120.0,
) -> SerpFetchResult:
    """Fetch top-`top_n` organic URLs for each candidate primary keyword.

    `keywords` is deduped by the caller's intent but deduped again here so two
    groupings sharing a representative don't pay for the SERP twice.
    """
    result = SerpFetchResult()
    unique = list(dict.fromkeys(k for k in keywords if k))
    if not unique:
        return result

    deadline = time.monotonic() + time_budget_s
    exec_ = ThreadPoolExecutor(max_workers=max_workers)
    futures = {exec_.submit(dfs.serp_top_urls, kw, top_n): kw for kw in unique}
    try:
        for fut in as_completed(futures, timeout=max(0.0, deadline - time.monotonic())):
            kw = futures[fut]
            try:
                result.per_keyword[kw] = fut.result()
            except Exception as exc:  # noqa: BLE001 — degrade this candidate only
                result.degraded_notes.append(
                    f"SERP lookup for candidate primary “{kw}” unavailable."
                )
                logger.warning(
                    "degraded",
                    extra={"event": "degraded", "step": "candidate_serp",
                           "keyword": kw, "reason": str(exc)},
                )
    except TimeoutError:
        result.timed_out = True
    finally:
        exec_.shutdown(wait=False, cancel_futures=True)

    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "candidate_serp",
               "requested": len(unique), "fetched": len(result.per_keyword),
               "degraded": bool(result.degraded_notes),
               "timed_out": result.timed_out},
    )
    return result
