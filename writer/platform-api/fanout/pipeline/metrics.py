"""§7.8 keyword metrics enrichment.

After the relevance gate + per-silo cap settle the active pool, this module
fetches per-keyword search volume, CPC, keyword difficulty, and competition
index from DataForSEO Labs `keyword_overview` in parallel batches. Results are
returned as `{keyword: {volume, cpc_usd, keyword_difficulty, competition_index}}`
for the caller (jobs.py) to persist via `storage.update_keyword_metrics`.

Cost: DataForSEO bills per call (the cost meter picks up `task["cost"]`); a
single call handles up to ~700 keywords. With the 1000/silo cap × N silos, a
typical 5-silo run = ~5000 keywords = ~8 calls, ~$0.40 at list price.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import as_completed
from dataclasses import dataclass, field

from fanout.concurrency import ContextThreadPoolExecutor as ThreadPoolExecutor

logger = logging.getLogger(__name__)

# DataForSEO Labs keyword_overview caps at ~700 keywords/task; stay well clear
# so a payload-size guard upstream never trips.
_BATCH_SIZE = 500


@dataclass
class EnrichmentResult:
    metrics: dict[str, dict] = field(default_factory=dict)
    degraded_notes: list[str] = field(default_factory=list)
    timed_out: bool = False
    requested: int = 0
    enriched: int = 0


def enrich_keywords(
    *,
    keywords: list[str],
    dfs,
    batch_size: int = _BATCH_SIZE,
    max_workers: int = 4,
    time_budget_s: float = 120.0,
) -> EnrichmentResult:
    """Fetch metrics for the unique keywords, in parallel batches. A per-batch
    failure degrades just that slice (the rest are still returned); hitting the
    time budget surfaces as `timed_out=True` and partial results — the same
    degrade-don't-halt pattern §16.2 uses for expansion / mining."""
    result = EnrichmentResult()
    unique = list(dict.fromkeys(k for k in keywords if isinstance(k, str) and k))
    result.requested = len(unique)
    if not unique:
        return result

    batches = [unique[i : i + batch_size] for i in range(0, len(unique), batch_size)]
    deadline = time.monotonic() + time_budget_s
    ex = ThreadPoolExecutor(max_workers=max(1, max_workers))
    futures = {ex.submit(dfs.keyword_overview, b): b for b in batches}
    try:
        for fut in as_completed(futures, timeout=max(0.0, deadline - time.monotonic())):
            batch = futures[fut]
            try:
                row_map = fut.result()
            except Exception as exc:  # noqa: BLE001 — degrade this batch
                result.degraded_notes.append(
                    f"Metrics enrichment: a batch of {len(batch)} keywords "
                    f"was unavailable ({type(exc).__name__})."
                )
                logger.warning(
                    "degraded",
                    extra={"event": "degraded", "step": "metrics",
                           "batch_size": len(batch), "reason": str(exc)},
                )
                continue
            if isinstance(row_map, dict):
                result.metrics.update(row_map)
    except TimeoutError:
        # Hit the overall budget — keep what landed.
        result.timed_out = True
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    result.enriched = len(result.metrics)
    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "metrics_enrichment",
               "requested": result.requested, "enriched": result.enriched,
               "batches": len(batches), "timed_out": result.timed_out,
               "degraded": bool(result.degraded_notes)},
    )
    return result
