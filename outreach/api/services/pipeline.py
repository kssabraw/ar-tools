"""Phase 1 orchestration — Stage A1 (ingest) then Stage A2 (filter).

No scoring. `prospect_score` is not written, and neither is `scan_snapshot` or `grid_result`.
Ordering for inspection, if any is wanted, is by review count — see queries/phase1-dod.sql.
"""

from __future__ import annotations

import asyncio
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
from .paging import fetch_all
from .parser import parse_place, unmapped_fields
from .suppression import load_suppression_index
from .tiling import DedupeStats, Submarket, build_tiles, nearest_submarket

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
    region: str = "",
    cycle_number: int | None = None,
    raw_landing_dir: str | None = None,
) -> IngestReport:
    """Stage A1 — the paid base pull.

    Order is load-bearing: estimate and enforce the cost gate BEFORE any request is submitted,
    persist raw before parsing, dedupe on place_id across overlapping tiles.
    """
    report = IngestReport(market_id=market_id)

    tiles = build_tiles(
        categories=categories,
        submarkets=submarkets,
        market_name=market_name,
        region=region,
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
    #
    # Tiles run CONCURRENTLY and each one is PERSISTED THE MOMENT IT LANDS. Both properties were
    # learned the expensive way: the first real LA run pulled 12 of 14 tiles sequentially over
    # ~4 minutes, was terminated mid-poll, and wrote nothing — every paid call discarded because
    # the insert only happened after the last tile.
    #
    # Paid work must be durable at the granularity it is paid for. An interruption should cost
    # the tile in flight, not the twelve already bought. This is the brief's own principle
    # ("re-parsing from stored raw is free, re-pulling is not") applied per tile rather than
    # per run.
    #
    # Concurrency also shortens the exposure window: 14 sequential tiles at ~20s each is ~5
    # minutes of wall time to be interrupted in; four at a time is closer to 90 seconds.
    seen: dict[str, str] = {}  # place_id -> first tile label, for dedupe across tiles
    seen_unmapped: set[str] = set()
    semaphore = asyncio.Semaphore(max(1, settings.outscraper_tile_concurrency))

    async def fetch_tile(tile: TileRequest) -> tuple[TileRequest, list[dict[str, Any]] | None, str]:
        async with semaphore:
            try:
                request_id = await outscraper.submit_maps_search(tile)
                body = await outscraper.fetch_result(request_id)
                _landing_write(raw_landing_dir, request_id, body)
                return tile, extract_places(body), ""
            except OutscraperError as exc:
                # One dead tile is a hole in coverage, not a reason to lose the other thirteen.
                return tile, None, str(exc)

    async with OutscraperClient(settings) as outscraper:
        pending = [asyncio.create_task(fetch_tile(tile)) for tile in tiles]

        for finished in asyncio.as_completed(pending):
            tile, places, error = await finished
            label = tile.label or tile.query

            if places is None:
                report.tiles_failed += 1
                report.tile_errors.append(f"{label}: {error}")
                logger.error("tile failed", extra={"tile": label, "error": error})
                continue

            report.tiles_submitted += 1
            report.stats.per_tile_counts[label] = len(places)

            rows: list[dict[str, Any]] = []
            for raw in places:
                report.stats.total_returned += 1
                place = parse_place(raw)

                if place is None:
                    # No place_id or no name. Never fabricate one — grid results join on
                    # place_id, so an invented value silently matches nothing forever.
                    report.stats.unparseable += 1
                    continue

                if place.place_id in seen:
                    report.stats.duplicates_dropped += 1
                    continue

                seen[place.place_id] = label
                seen_unmapped.update(unmapped_fields(place.raw))

                # `raw` carries the untouched provider dict. The only thing read out of it
                # before the row lands is place_id and name, which are NOT NULL on the table —
                # every other column is derived from the stored copy and can be re-derived for
                # free against a corrected alias map.
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
                        "latest_review_at": None,  # review recency deferred — DECISIONS.md
                        "lat": place.lat,
                        "lng": place.lng,
                        "business_status": place.business_status,
                        "raw": place.raw,
                    }
                )

            if rows:
                client.table("prospect").upsert(rows, on_conflict="place_id").execute()
                report.prospects_written += len(rows)

            # Ledger per tile, for the same durability reason: an interrupted run must not
            # under-report what it actually spent. The DoD query sums these.
            tile_cost = cost.actual_cost_cents(
                len(places), settings.outscraper_cost_per_1000_places_cents
            )
            report.cost_cents += tile_cost
            client.table("cost_ledger").insert(
                cost.build_ledger_row(
                    market_id=market_id,
                    cycle_number=cycle_number,
                    stage=cost.STAGE_INGEST,
                    provider=cost.PROVIDER_OUTSCRAPER,
                    units=len(places),
                    cost_cents=tile_cost,
                )
            ).execute()

            logger.info(
                "tile persisted",
                extra={
                    "tile": label,
                    "returned": len(places),
                    "written": len(rows),
                    "running_total": report.prospects_written,
                },
            )

    report.stats.unique_places = len(seen)
    report.unmapped_raw_fields = sorted(seen_unmapped)

    if report.unmapped_raw_fields:
        logger.info(
            "provider returned fields no alias claims — check parser.FIELD_ALIASES",
            extra={"fields": report.unmapped_raw_fields},
        )

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

    # Paged: an unbounded select stops at 1000 rows with no error, which silently left 215 of
    # 1388 LA prospects unfiltered on the first run (ISSUES I-036).
    prospects = fetch_all(
        lambda: client.table("prospect")
        .select("id,place_id,name,phone,website,rating,review_count,review_count_inferred_zero,franchise_status,lat,lng,business_status,raw")
        .eq("market_id", market_id)
    )

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
            # Read from the COLUMN, not from `place` — `place` is re-parsed from stored raw, and
            # raw is the provider's untouched payload, which by definition does not carry our
            # inference about it (ISSUES I-041).
            inferred_zero=bool(row.get("review_count_inferred_zero")),
            # The COLUMN, not the re-parsed payload. At ingest the two agree; when they diverge
            # the column holds a count obtained outside the provider (a manual verification, or
            # the I-045 geogrid backfill), and re-parsing raw would silently discard it.
            review_count_override=row.get("review_count"),
            franchise_decision=row.get("franchise_status"),
        )

        report.evaluated += 1
        if verdict.excluded:
            report.excluded += 1
        else:
            report.survived += 1

        if verdict.franchise_flagged:
            report.franchise_flagged += 1
            if row.get("franchise_status") not in (
                "confirmed_franchise",
                "confirmed_independent",
            ):
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
    #
    # And never over a confirmation either, which is the half this originally missed: a reviewer
    # who recorded confirmed_independent (or the stronger confirmed_franchise) had it silently
    # reset to 'flagged' by the next routine filter run. Skipped here so the intent is legible at
    # the call site; the database guard enforces it regardless of caller (ISSUES I-054).
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
