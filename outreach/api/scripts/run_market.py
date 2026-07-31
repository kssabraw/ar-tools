"""CLI: define a market, then run Phase 1 against it.

    python -m api.scripts.run_market seed    markets/kansas-city-plumbing.json
    python -m api.scripts.run_market ingest  markets/kansas-city-plumbing.json
    python -m api.scripts.run_market filter  markets/kansas-city-plumbing.json
    python -m api.scripts.run_market run     markets/kansas-city-plumbing.json

`seed` is idempotent and safe to re-run. It refuses to change the geometry of a scanned
submarket; pass --allow-geometry-change to edit one that has not been scanned yet.

`ingest` is the only paid command. It estimates cost and aborts before spending anything if the
projection exceeds max_market_run_cost_cents.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.config import get_settings  # noqa: E402
from api.services import seeding  # noqa: E402
from api.services.cost import CostLimitExceeded  # noqa: E402
from api.services.pipeline import run_filter, run_ingest  # noqa: E402


def _client():
    """Imported lazily — `calibrate` touches no database and must not require one."""
    from api.db import get_client

    return get_client()


def _market_id(client, name: str) -> str:
    rows = client.table("market").select("id").eq("name", name).limit(1).execute().data
    if not rows:
        raise SystemExit(f"market {name!r} not found — run `seed` first")
    return rows[0]["id"]


def _submarkets(client, market_id: str):
    rows = client.table("submarket").select("*").eq("market_id", market_id).execute().data or []
    return seeding.submarket_rows_to_tiling(rows)


def cmd_seed(args) -> int:
    definition = seeding.MarketDefinition.from_file(args.definition)
    client = _client()

    try:
        report = seeding.seed_market(
            client, definition, allow_geometry_change=args.allow_geometry_change
        )
    except seeding.GeometryLocked as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "market_id": report.market_id,
                "market_created": report.market_created,
                "submarkets_created": report.submarkets_created,
                "submarkets_updated": report.submarkets_updated,
                "keywords_upserted": report.keywords_upserted,
                "geometry_changes": report.geometry_changes,
                "warnings": report.problems,
            },
            indent=2,
        )
    )
    return 0


def cmd_ingest(args) -> int:
    definition = seeding.MarketDefinition.from_file(args.definition)
    settings = get_settings()
    client = _client()

    market_id = _market_id(client, definition.name)
    submarkets = _submarkets(client, market_id)

    if not submarkets:
        print(
            "REFUSED: no submarkets defined. Without them the tiler falls back to one query per "
            "category, which Google caps at ~400 results — you would get a partial market and no "
            "signal that it was partial. Run `seed` with submarkets first.",
            file=sys.stderr,
        )
        return 2

    try:
        report = asyncio.run(
            run_ingest(
                client=client,
                settings=settings,
                market_id=market_id,
                market_name=definition.name,
                categories=definition.categories,
                submarkets=submarkets,
                region=definition.region,
                cycle_number=args.cycle,
                raw_landing_dir=settings.raw_landing_dir,
            )
        )
    except CostLimitExceeded as exc:
        print(f"ABORTED before spending: {exc}", file=sys.stderr)
        return 3

    print(
        json.dumps(
            {
                "tiles_submitted": report.tiles_submitted,
                "tiles_failed": report.tiles_failed,
                "rows_returned": report.stats.total_returned,
                "unique_places": report.stats.unique_places,
                "duplicates_dropped": report.stats.duplicates_dropped,
                "overlap_rate": round(report.stats.overlap_rate, 3),
                "unparseable": report.stats.unparseable,
                "prospects_written": report.prospects_written,
                "cost_cents": report.cost_cents,
                "unmapped_raw_fields": report.unmapped_raw_fields,
                "tile_errors": report.tile_errors,
            },
            indent=2,
        )
    )

    if report.stats.overlap_rate < 0.05 and len(submarkets) > 1:
        print(
            "\nWARNING: tile overlap is near zero. Adjacent tiles returned almost no places in "
            "common, which means the tiling is probably too sparse to treat this as full market "
            "coverage (ISSUES I-017). Consider more submarkets or closer centroids.",
            file=sys.stderr,
        )

    if report.unmapped_raw_fields:
        print(
            f"\nNOTE: {len(report.unmapped_raw_fields)} provider fields matched no alias. "
            f"Check parser.FIELD_ALIASES against these (ISSUES I-018).",
            file=sys.stderr,
        )

    return 0


def cmd_filter(args) -> int:
    definition = seeding.MarketDefinition.from_file(args.definition)
    client = _client()
    market_id = _market_id(client, definition.name)

    report = run_filter(client=client, settings=get_settings(), market_id=market_id)

    print(
        json.dumps(
            {
                "evaluated": report.evaluated,
                "survived": report.survived,
                "excluded": report.excluded,
                "franchise_flagged": report.franchise_flagged,
                "failures_by_rule": report.failures_by_rule,
            },
            indent=2,
        )
    )
    return 0


def cmd_calibrate(args) -> int:
    """One tiny paid pull to settle the response field names and the billing rate.

    Lives here rather than as a separate start command because Railway resolves the start command
    from the deployment being re-run, not from the current service config — so overriding it per
    run silently re-executes the previous one. One entrypoint driven by OUTREACH_COMMAND is the
    only shape that reliably does what the variable says.
    """
    import asyncio as _asyncio

    from api.scripts.calibrate import calibrate
    from api.services.tiling import Submarket, build_tiles

    definition = seeding.MarketDefinition.from_file(args.definition)

    # Build the tile the same way the ingest does, so the calibration measures the request that
    # actually runs — including coordinates and the region qualifier.
    subs = [
        Submarket(id="calib", name=s.name, center_lat=s.center_lat, center_lng=s.center_lng)
        for s in definition.submarkets[:1]
    ]
    tile = build_tiles(
        categories=definition.categories[:1] or ["plumber"],
        submarkets=subs,
        market_name=definition.name,
        region=definition.region,
    )[0]

    return _asyncio.run(calibrate(tile.query, args.limit, tile.coordinates))


def cmd_run(args) -> int:
    for step in (cmd_seed, cmd_ingest, cmd_filter):
        code = step(args)
        if code != 0:
            return code
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    parser = argparse.ArgumentParser(description="Outreach pipeline — Phase 1")
    parser.add_argument("command", choices=["seed", "ingest", "filter", "run", "calibrate"])
    parser.add_argument("definition", help="path to a market definition JSON file")
    parser.add_argument("--cycle", type=int, default=None, help="cycle number for cost_ledger")
    parser.add_argument(
        "--limit", type=int, default=20, help="places per query, calibrate only"
    )
    parser.add_argument(
        "--allow-geometry-change",
        action="store_true",
        help="permit geometry edits to submarkets that have NOT been scanned",
    )
    args = parser.parse_args()

    handler = {
        "seed": cmd_seed,
        "ingest": cmd_ingest,
        "filter": cmd_filter,
        "run": cmd_run,
        "calibrate": cmd_calibrate,
    }[args.command]

    # Railway reports a crashed job as deployment status SUCCESS when restartPolicy is NEVER —
    # observed: `filter` died on a missing credential and the deployment still showed green.
    # For a job that runs unattended twice a month, the deployment status is therefore NOT a
    # success signal. This marker is, and it is greppable from the logs.
    try:
        code = handler(args)
    except Exception as exc:  # noqa: BLE001 — the marker must outlive any failure mode
        print(f"OUTREACH_RESULT status=failed command={args.command} error={exc!r}", flush=True)
        raise

    status = "ok" if code == 0 else "failed"
    print(f"OUTREACH_RESULT status={status} command={args.command} exit={code}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
