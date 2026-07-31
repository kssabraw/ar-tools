"""Phase 1 orchestration — Stage A1 (ingest) then Stage A2 (filter).

No scoring. `prospect_score` is not written, and neither is `scan_snapshot` or `grid_result`.
Ordering for inspection, if any is wanted, is by review count — see queries/phase1-dod.sql.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ..config import Settings
from . import cost
from .filters import ALL_RULES, FilterVerdict, SuppressionIndex, evaluate
from .outscraper_client import (
    OutscraperClient,
    OutscraperError,
    TileRequest,
    extract_places,
)
from .parser import parse_place, unmapped_fields
from .suppression import load_suppression_index
from .tiling import DedupeStats, Submarket, build_tiles, dedupe_on_place_id, nearest_submarket

logger = logging.getLogger(__name__)


@dataclass
class IngestReport:
    market_id: str
    tiles_submitted: int = 0
    tiles_failed: int = 0
    stats: DedupeStats = field(default_factory=DedupeStats)
    prospects_written: int = 0
    cost_cents: int = 0
    tile_errors: list[str] = field(default_factory=list)
    unmapped_raw_fields: list[str] = field(default_factory=list)


@dataclass
class FilterReport:
    market_id: str
    evaluated: int = 0
    excluded: int = 0
    survived: int = 0
    franchise_flagged: int = 0
    failures_by_rule: dict[str, int] = field(default_factory=dict)


def _landing_write(settings_dir: str | None, request_id: str, body: dict[str, Any]) -> None:
    """Drop the untouched archive body on disk before anything reads it.

    Outscraper retains a completed response for two hours and re-pulling costs money, so this is
    a cheap hedge against a crash between fetch and insert. Opt-in: unset means no landing, which
    is fine for a smoke test and unwise for a real market run.
    """
    if not settings_dir:
        return

    directory = Path(settings_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (directory / f"{stamp}-{request_id}.json").write_text(json.dumps(body), encoding="utf-8")


async def run_ingest(
    *,
    client: Any,
    settings: Settings,
    market_id: str,
    market_name: str,
    categories: Sequence[str],
    submarkets: Sequence[Submarket],
    cycle_number: int | None = None,
    raw_landing_dir: str | None = None,
) -> IngestReport:
    """Stage A1 — the paid base pull.

    Order is load-bearing: estimate and enforce the cost gate BEFORE any request is submitted,
    persist raw before parsing, dedupe on place_id across overlapping tiles.
    """
    report = IngestReport(market_id=market_id)

    tiles = build_tiles(
        categories=categories, submarkets=submarkets, market_name=market_name
    )

    # -- cost gate, before the first paid call --------------------------------------------
    estimate = cost.estimate_ingest_cost(
        tiles=len(tiles),
        places_per_tile=settings.outscraper_places_per_query_limit,
        cost_per_1000_places_cents=settings.outscraper_cost_per_1000_places_cents,
        limit_cents=settings.max_market_run_cost_cents,
    )
    cost.enforce_limit(estimate)  # raises CostLimitExceeded; nothing paid has happened yet

    # -- fan out ---------------------------------------------------------------------------
    tile_places: list[tuple[TileRequest, list[dict[str, Any]]]] = []

    async with OutscraperClient(settings) as outscraper:
        for tile in tiles:
            try:
                request_id = await outscraper.submit_maps_search(tile)
                report.tiles_submitted += 1

                body = await outscraper.fetch_result(request_id)
                _landing_write(raw_landing_dir, request_id, body)

                tile_places.append((tile, extract_places(body)))
            except OutscraperError as exc:
                # One dead tile is a hole in coverage, not a reason to lose the other forty.
                report.tiles_failed += 1
                report.tile_errors.append(f"{tile.label or tile.query}: {exc}")
                logger.error(
                    "tile failed", extra={"tile": tile.label or tile.query, "error": str(exc)}
                )

    # -- dedupe on place_id across overlapping tiles ---------------------------------------
    deduped, stats = dedupe_on_place_id(tile_places, parse=parse_place)
    report.stats = stats

    # -- persist ---------------------------------------------------------------------------
    # `raw` carries the untouched provider dict. The only thing read out of it before the row
    # lands is place_id and name, which are NOT NULL on the table — every other column is
    # derived from the stored copy and can be re-derived for free against a corrected alias map.
    rows: list[dict[str, Any]] = []
    seen_unmapped: set[str] = set()

    for entry in deduped.values():
        place = entry.place
        seen_unmapped.update(unmapped_fields(place.raw))

        rows.append(
            {
                "market_id": market_id,
                "submarket_id": nearest_submarket(place.lat, place.lng, submarkets),
                "place_id": place.place_id,
                "name": place.name,
                "category": place.category,
                "address": place.address,
                "phone": place.phone,
                "phone_type": place.phone_type,  # always 'unknown' in Phase 1
                "website": place.website,
                "rating": place.rating,
                "review_count": place.review_count,
                "latest_review_at": None,  # review recency deferred — see DECISIONS.md
                "lat": place.lat,
                "lng": place.lng,
                "business_status": place.business_status,
                "raw": place.raw,
            }
        )

    if rows:
        client.table("prospect").upsert(rows, on_conflict="place_id").execute()

    report.prospects_written = len(rows)
    report.unmapped_raw_fields = sorted(seen_unmapped)

    if report.unmapped_raw_fields:
        logger.info(
            "provider returned fields no alias claims — check parser.FIELD_ALIASES",
            extra={"fields": report.unmapped_raw_fields},
        )

    # -- ledger ----------------------------------------------------------------------------
    report.cost_cents = cost.actual_cost_cents(
        stats.total_returned, settings.outscraper_cost_per_1000_places_cents
    )
    client.table("cost_ledger").insert(
        cost.build_ledger_row(
            market_id=market_id,
            cycle_number=cycle_number,
            stage=cost.STAGE_INGEST,
            provider=cost.PROVIDER_OUTSCRAPER,
            units=stats.total_returned,
            cost_cents=report.cost_cents,
        )
    ).execute()

    return report


def run_filter(
    *,
    client: Any,
    settings: Settings,
    market_id: str,
    today: date | None = None,
    suppression: SuppressionIndex | None = None,
) -> FilterReport:
    """Stage A2 — free. Reads prospects back out and writes the full rule matrix.

    Every rule is written for every prospect, including the ones it passed and the ones that were
    not evaluated. That is what makes "which rules did this business fail" answerable from SQL.
    """
    report = FilterReport(market_id=market_id)
    today = today or date.today()
    index = suppression if suppression is not None else load_suppression_index(client)

    response = (
        client.table("prospect")
        .select("id,place_id,name,phone,website,rating,review_count,lat,lng,business_status,raw")
        .eq("market_id", market_id)
        .execute()
    )
    prospects = response.data or []

    filter_rows: list[dict[str, Any]] = []
    franchise_updates: list[str] = []

    for row in prospects:
        place = parse_place(row.get("raw") or {})
        if place is None:
            logger.warning("stored raw no longer parses", extra={"prospect_id": row.get("id")})
            continue

        verdict: FilterVerdict = evaluate(
            place,
            suppression=index,
            franchise_patterns=settings.franchise_patterns,
            min_review_count=settings.filter_min_review_count,
            review_recency_months=settings.filter_review_recency_months,
            today=today,
            exclude_closed=settings.filter_exclude_closed,
            require_phone=settings.filter_require_phone,
            check_suppression=settings.filter_check_suppression,
            min_review_count_enabled=settings.filter_min_review_count_enabled,
            review_recency_enabled=settings.filter_review_recency_enabled,
        )

        report.evaluated += 1
        if verdict.excluded:
            report.excluded += 1
        else:
            report.survived += 1

        if verdict.franchise_flagged:
            report.franchise_flagged += 1
            franchise_updates.append(row["id"])

        for outcome in verdict.outcomes:
            if not outcome.passed:
                report.failures_by_rule[outcome.rule] = (
                    report.failures_by_rule.get(outcome.rule, 0) + 1
                )

            filter_rows.append(
                {
                    "prospect_id": row["id"],
                    "rule": outcome.rule,
                    "passed": outcome.passed,
                    "observed_value": outcome.observed_value,
                }
            )

    if filter_rows:
        client.table("filter_result").upsert(
            filter_rows, on_conflict="prospect_id,rule"
        ).execute()

    # Flag only — never 'confirmed_franchise'. Confirmation is a human act.
    if franchise_updates:
        client.table("prospect").update({"franchise_status": "flagged"}).in_(
            "id", franchise_updates
        ).execute()

    # The filter stage is free; the ledger row records that explicitly rather than omitting it,
    # so "what did this market cost" sums every stage rather than the paid ones.
    client.table("cost_ledger").insert(
        cost.build_ledger_row(
            market_id=market_id,
            cycle_number=None,
            stage=cost.STAGE_FILTER,
            provider="internal",
            units=report.evaluated,
            cost_cents=0,
        )
    ).execute()

    for rule in ALL_RULES:
        report.failures_by_rule.setdefault(rule, 0)

    return report
