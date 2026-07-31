"""Cost estimation, the pre-flight abort gate, and cost_ledger writes.

Brief §4 says the ledger must record "real reported cost, not estimates", and §5 asks for
reconciliation against the Outscraper dashboard within 5%. The API does not appear to return a
per-request cost, so that criterion is not meetable as written (ISSUES I-022). The agreed
substitute: the ledger stores units x the configured rate, reconciled MANUALLY against the
dashboard once per cycle. Nothing elaborate is built to chase an unachievable check.

That makes `outscraper_cost_per_1000_places_cents` load-bearing. The abort gate is exactly as
honest as that number, so it must be set from the real plan before any production run.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

PROVIDER_OUTSCRAPER = "outscraper"

STAGE_INGEST = "a1_ingest"
STAGE_FILTER = "a2_filter"


class CostLimitExceeded(RuntimeError):
    """Pre-flight projection exceeded max_market_run_cost_cents. The paid stage did not run."""

    def __init__(self, projected_cents: int, limit_cents: int) -> None:
        self.projected_cents = projected_cents
        self.limit_cents = limit_cents
        super().__init__(
            f"projected cost {projected_cents}c exceeds max_market_run_cost_cents "
            f"{limit_cents}c — aborting before the paid stage"
        )


@dataclass(frozen=True)
class CostEstimate:
    tiles: int
    places_per_tile: int
    projected_units: int
    projected_cents: int
    limit_cents: int

    @property
    def within_limit(self) -> bool:
        return self.projected_cents <= self.limit_cents


def estimate_ingest_cost(
    *,
    tiles: int,
    places_per_tile: int,
    cost_per_1000_places_cents: int,
    limit_cents: int,
) -> CostEstimate:
    """Worst-case projection for the base pull.

    Deliberately assumes every tile returns a full page. Real pulls come in well under this
    because most tiles are not saturated, but a gate that estimates optimistically is not a gate.
    Rounds up — a projection that rounds down can slip past the limit by a fraction of a cent per
    tile and land over it in aggregate.
    """
    projected_units = max(0, tiles) * max(0, places_per_tile)
    projected_cents = math.ceil(projected_units * cost_per_1000_places_cents / 1000)

    return CostEstimate(
        tiles=tiles,
        places_per_tile=places_per_tile,
        projected_units=projected_units,
        projected_cents=projected_cents,
        limit_cents=limit_cents,
    )


def enforce_limit(estimate: CostEstimate) -> None:
    """Raise before the paid stage runs if the projection is over budget."""
    if not estimate.within_limit:
        raise CostLimitExceeded(estimate.projected_cents, estimate.limit_cents)

    logger.info(
        "cost pre-flight passed",
        extra={
            "projected_cents": estimate.projected_cents,
            "limit_cents": estimate.limit_cents,
            "tiles": estimate.tiles,
        },
    )


def actual_cost_cents(units: int, cost_per_1000_places_cents: int) -> int:
    """Cost for units actually returned. Rounded up, same reasoning as the estimate."""
    return math.ceil(max(0, units) * cost_per_1000_places_cents / 1000)


class LedgerWriter(Protocol):
    def __call__(self, row: dict[str, Any]) -> Any: ...


def build_ledger_row(
    *,
    market_id: str | None,
    cycle_number: int | None,
    stage: str,
    provider: str,
    units: int,
    cost_cents: int,
) -> dict[str, Any]:
    """One cost_ledger row. Written per stage per provider (brief §2)."""
    return {
        "market_id": market_id,
        "cycle_number": cycle_number,
        "stage": stage,
        "provider": provider,
        "units": units,
        "cost_cents": cost_cents,
    }
