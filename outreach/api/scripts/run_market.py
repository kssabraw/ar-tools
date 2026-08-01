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
import signal
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
    from api.services.paging import fetch_all

    rows = fetch_all(lambda: client.table("submarket").select("*").eq("market_id", market_id))
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


def cmd_verify_reviews(args) -> int:
    """PAID, tiny, read-only: does a null review count mean zero? (ISSUES I-041)

    Reports; never acts. It does not write review_count, does not set
    review_count_inferred_zero, and excludes nothing — applying the flag is a human decision made
    once, on evidence, and a verifier that applied its own findings would delete the step where
    someone looks at them.

    Note the result is bounded by asking the SAME provider whose convention is under test: see
    services/review_verify for why the review sub-objects rather than the count field carry the
    evidence, and why DataForSEO is the next step if this comes back ambiguous.
    """
    import asyncio as _asyncio

    from api.services.review_verify import verify_review_counts

    definition = seeding.MarketDefinition.from_file(args.definition)
    client = _client()
    market_id = _market_id(client, definition.name)

    try:
        report = _asyncio.run(
            verify_review_counts(
                client=client,
                settings=get_settings(),
                market_id=market_id,
                limit=args.limit,
                group=args.group,
            )
        )
    except CostLimitExceeded as exc:
        print(f"ABORTED before spending: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "requested": report.requested,
                "by_verdict": report.by_verdict,
                "counts_found": report.counts_found,
                "recommendation": report.recommendation(),
                "results": [
                    {
                        "place_id": r.place_id,
                        "name": r.name,
                        "verdict": r.verdict,
                        "review_count": r.review_count,
                        "rating": r.rating,
                        "has_histogram": r.has_histogram,
                        "inline_reviews": r.inline_reviews,
                        "error": r.error,
                    }
                    for r in report.results
                ],
            },
            indent=2,
        )
    )
    return 0


def cmd_run(args) -> int:
    for step in (cmd_seed, cmd_ingest, cmd_filter):
        code = step(args)
        if code != 0:
            return code
    return 0


# Env vars that may carry the deployed commit. Railway sets RAILWAY_GIT_COMMIT_SHA; the others
# are conventional and cost nothing to check.
_SHA_VARS = ("OUTREACH_BUILD_SHA", "RAILWAY_GIT_COMMIT_SHA", "SOURCE_COMMIT", "GIT_COMMIT")


def build_identity(env: dict[str, str], commands: "list[str]") -> str:
    """One line saying WHICH code is running, printed before anything else happens.

    A deploy that built the wrong commit is otherwise invisible until it fails at something, and
    then only by inference: `verify-reviews` was rejected as an invalid choice, and working out
    that the container held a commit from a merged branch took reading the deployment metadata.
    That should have been line one.

    The command list is part of the identity on purpose, and is the half that always works. A SHA
    can come back `unknown` — Railway does not expose its git vars to every service — but the
    subcommands the binary actually accepts are read from the running code, so a stale image is
    self-evident from the banner whether or not the SHA resolved.
    """
    sha = next((env[k] for k in _SHA_VARS if env.get(k)), None)
    return (
        f"OUTREACH_BUILD sha={sha[:12] if sha else 'unknown'} "
        f"branch={env.get('RAILWAY_GIT_BRANCH') or 'unknown'} "
        f"commands={','.join(commands)}"
    )


def _install_sigterm_marker() -> None:
    """Print the result marker if the platform terminates us.

    Python's default SIGTERM handling kills the process immediately with no traceback and no
    output, which is exactly what the first real LA run looked like: 12 paid tiles, then silence,
    and a deployment still reporting SUCCESS. A handler makes an external kill self-evident.
    """

    def _handler(signum, _frame):  # noqa: ANN001
        print(
            f"OUTREACH_RESULT status=failed reason=terminated signal={signum}",
            flush=True,
        )
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, _handler)


def main() -> int:
    _install_sigterm_marker()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    import os

    print(
        build_identity(
            dict(os.environ),
            ["seed", "ingest", "filter", "run", "calibrate", "verify-reviews"],
        ),
        flush=True,
    )

    parser = argparse.ArgumentParser(description="Outreach pipeline — Phase 1")
    parser.add_argument(
        "command",
        choices=["seed", "ingest", "filter", "run", "calibrate", "verify-reviews"],
    )
    parser.add_argument("definition", help="path to a market definition JSON file")
    parser.add_argument("--cycle", type=int, default=None, help="cycle number for cost_ledger")
    parser.add_argument(
        "--limit", type=int, default=20,
        help="places per query (calibrate); prospects to look up (verify-reviews)",
    )
    parser.add_argument(
        "--group", choices=["both_null", "rating_present"], default="both_null",
        help="verify-reviews: which I-041 group to sample",
    )
    parser.add_argument(
        "--allow-geometry-change",
        action="store_true",
        help="permit geometry edits to submarkets that have NOT been scanned",
    )
    handlers = {
        "seed": cmd_seed,
        "ingest": cmd_ingest,
        "filter": cmd_filter,
        "run": cmd_run,
        "calibrate": cmd_calibrate,
        "verify-reviews": cmd_verify_reviews,
    }

    # Railway reports a crashed job as deployment status SUCCESS when restartPolicy is NEVER —
    # observed twice: `filter` died on a missing credential, and `verify-reviews` was rejected as
    # an invalid choice. Both showed green. For a job that runs unattended twice a month the
    # deployment status is therefore NOT a success signal. This marker is, and it is greppable.
    #
    # ARGPARSE IS INSIDE THE TRY, which is the half this originally missed. `parse_args` raises
    # SystemExit on a bad argument, and SystemExit derives from BaseException rather than
    # Exception — so a marker guarding only `Exception` never printed for exactly the failure an
    # unattended misconfiguration produces: a wrong OUTREACH_COMMAND. The process did exit
    # non-zero; the silence was the missing half, not the exit code.
    command = "(unparsed)"
    try:
        args = parser.parse_args()
        command = args.command
        code = handlers[command](args)
    except SystemExit as exc:
        # argparse's bad-argument exit, or an explicit SystemExit("message") from a command.
        raw = exc.code
        code = raw if isinstance(raw, int) else (0 if raw is None else 1)
        reason = "" if isinstance(raw, (int, type(None))) else f" reason={raw!r}"
        status = "ok" if code == 0 else "failed"
        print(
            f"OUTREACH_RESULT status={status} command={command} exit={code}{reason}",
            flush=True,
        )
        return code
    except Exception as exc:  # noqa: BLE001 — the marker must outlive any failure mode
        print(f"OUTREACH_RESULT status=failed command={command} error={exc!r}", flush=True)
        raise

    status = "ok" if code == 0 else "failed"
    print(f"OUTREACH_RESULT status={status} command={command} exit={code}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
