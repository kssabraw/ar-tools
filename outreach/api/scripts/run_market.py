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

    Defaults to --provider dataforseo, which is independent of the hypothesis: it is queried by
    place_id and returns the reviews themselves, and a reviews_count of 0 is a positive assertion
    of zero rather than an absence to interpret. --provider outscraper re-asks the vendor whose
    convention is under test and is bounded accordingly (I-050) — kept because the COMPARISON is
    the result.
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
                provider=args.provider,
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
                        "form": r.form,
                        "error": r.error,
                    }
                    for r in report.results
                ],
            },
            indent=2,
        )
    )
    return 0


def cmd_probe_dataforseo(args) -> int:
    """Which DataForSEO endpoints actually exist? FREE — every probe task is deliberately invalid.

    Exists because `/v3/business_data/google/reviews/live` was asserted to be production-proven on
    the strength of appearing in platform-api's gbp_service. It is called there; it also 404s, and
    that call site swallows the failure — being CALLED is not being WORKING. This measures rather
    than infers.

    With --sample-place-id, follows up with ONE real request against each surviving path to learn
    the response shape. That part BILLS, a few cents, and is still cheaper than another wrong
    guess about a response body.
    """
    import asyncio as _asyncio

    from api.services.dataforseo_client import probe_endpoints, sample_endpoint

    settings = get_settings()
    results = _asyncio.run(probe_endpoints(settings))

    print(json.dumps(
        {
            "probe": [
                {
                    "path": r.path,
                    "http_status": r.http_status,
                    "task_status": r.task_status,
                    "task_message": r.task_message,
                    "exists": r.exists,
                    "error": r.error,
                }
                for r in results
            ],
            "exists": [r.path for r in results if r.exists],
        },
        indent=2,
    ))

    if args.sample_place_id:
        for r in results:
            if not r.exists:
                continue
            print(f"--- SAMPLE {r.path} ---", flush=True)
            try:
                out = _asyncio.run(sample_endpoint(settings, r.path, args.sample_place_id))
                print(json.dumps(out, indent=2)[:4000], flush=True)
            except Exception as exc:  # noqa: BLE001
                print(json.dumps({"path": r.path, "error": str(exc)}, indent=2), flush=True)

    return 0


def cmd_scan(args) -> int:
    """Post one geogrid: one submarket x one keyword, 81 points. BILLS.

    Deliberately narrow. The owner's ruling for the first live run is one submarket and one
    keyword, so that a wrong response envelope costs one batch rather than a market — the same
    reasoning that left the review `task_get` envelope to be proven on a small first batch rather
    than on a synthetic test that could only confirm the shape we already assumed.

    A market-wide sweep is a later command, and it should be written after this one has run for
    real, not before.
    """
    import asyncio as _asyncio

    from api.services import scan_runner

    definition = seeding.MarketDefinition.from_file(args.definition)
    settings = get_settings()
    client = _client()

    from api.services.dataforseo_client import missing_dataforseo_vars

    absent = missing_dataforseo_vars(settings)
    if absent:
        print(f"REFUSED: missing credentials: {', '.join(absent)}", file=sys.stderr)
        return 2

    market_id = _market_id(client, definition.name)

    submarkets = (
        client.table("submarket").select("*").eq("market_id", market_id).execute().data or []
    )
    if args.submarket:
        submarkets = [s for s in submarkets if s["name"].lower() == args.submarket.lower()]
    if not submarkets:
        names = ", ".join(
            sorted(
                s["name"]
                for s in (
                    client.table("submarket")
                    .select("name")
                    .eq("market_id", market_id)
                    .execute()
                    .data
                    or []
                )
            )
        )
        print(f"REFUSED: no submarket matched --submarket. Known: {names}", file=sys.stderr)
        return 2
    if len(submarkets) > 1:
        print(
            "REFUSED: this command scans ONE submarket. Pass --submarket. Scanning a whole "
            "market before the envelope has been proven once is what the one-submarket ruling "
            "exists to prevent.",
            file=sys.stderr,
        )
        return 2

    keywords = (
        client.table("keyword").select("*").eq("market_id", market_id).execute().data or []
    )
    if args.keyword:
        keywords = [k for k in keywords if k["term"].lower() == args.keyword.lower()]
    else:
        keywords = [k for k in keywords if k.get("is_primary")] or keywords[:1]
    if len(keywords) != 1:
        terms = ", ".join(sorted(k["term"] for k in keywords))
        print(f"REFUSED: pass --keyword to pick exactly one of: {terms}", file=sys.stderr)
        return 2

    report = _asyncio.run(
        scan_runner.submit_scan(client, settings, submarkets[0], keywords[0])
    )
    print(
        json.dumps(
            {
                "snapshot_id": report.snapshot_id,
                "submarket": report.submarket,
                "keyword": report.keyword,
                "expected_points": report.expected_points,
                "posted": report.posted,
                "unposted": report.unposted,
                "problems": report.problems,
            },
            indent=2,
        )
    )
    # Posting nothing while believing a scan happened is the worst outcome available here: the
    # snapshot exists, the collector will find no tasks, and it finalizes as complete-with-zero.
    return 0 if report.posted else 1


def cmd_scan_organic(args) -> int:
    """Capture ONE organic SERP for a submarket x keyword's latest rolled-up snapshot. BILLS one request.

    The report's "organic ranking vs competitors" signal (outreach ISSUES I-095, increment 2). It
    attaches to the maps `scan_snapshot` the report already reads (I-084 — DECISIONS 2026-08-08), so
    the organic and coverage reads come off the same snapshot. Idempotent per snapshot: a re-run on a
    snapshot that already has an organic row is free and stores nothing.

    Targets a ROLLED-UP snapshot deliberately — that is the one the per-prospect report reads — via
    the same resolver the heatmap uses (`--snapshot`, or `--submarket` + optional `--keyword`).
    """
    import asyncio as _asyncio

    from api.services import organic_scan
    from api.services.dataforseo_client import missing_dataforseo_vars

    definition = seeding.MarketDefinition.from_file(args.definition)
    settings = get_settings()
    client = _client()

    absent = missing_dataforseo_vars(settings)
    if absent:
        print(f"REFUSED: missing credentials: {', '.join(absent)}", file=sys.stderr)
        return 2

    market_id = _market_id(client, definition.name)
    snapshot = _resolve_rollup_snapshot(client, market_id, args)
    if snapshot is None:
        return 2

    kw = (
        client.table("keyword").select("term").eq("id", snapshot["keyword_id"]).limit(1).execute().data
    )
    keyword_term = kw[0]["term"] if kw else ""
    if not keyword_term:
        print("REFUSED: snapshot's keyword could not be resolved", file=sys.stderr)
        return 2
    if snapshot.get("center_lat") is None or snapshot.get("center_lng") is None:
        print("REFUSED: snapshot has no recorded centre — cannot anchor the organic SERP", file=sys.stderr)
        return 2

    report = _asyncio.run(
        organic_scan.capture_organic(
            client, settings, snapshot, keyword_term, market_id=market_id
        )
    )
    print(
        json.dumps(
            {
                "snapshot_id": report.snapshot_id,
                "keyword": report.keyword,
                "stored": report.stored,
                "already_captured": report.already_captured,
                "results": report.results,
                "ai_overview_present": report.ai_overview_present,
                "problems": report.problems,
            },
            indent=2,
        )
    )
    # already_captured is a successful no-op; only a genuine failure to store is non-zero.
    return 0 if (report.stored or report.already_captured) else 1


def cmd_collect(args) -> int:
    """Drain the ready list and store whatever is done. FREE, and safe to run on any tick."""
    import asyncio as _asyncio

    from api.services import coverage_rollup, scan_runner
    from api.services.dataforseo_client import missing_dataforseo_vars

    settings = get_settings()
    absent = missing_dataforseo_vars(settings)
    if absent:
        print(f"REFUSED: missing credentials: {', '.join(absent)}", file=sys.stderr)
        return 2

    client = _client()
    report = _asyncio.run(scan_runner.collect_ready(client, settings))

    # The rollup rides this tick rather than taking a schedule of its own.
    #
    # Storage spec §7 asks for a daily `rollup_coverage` pg_cron job, and that is not buildable:
    # the rollup needs point distances from the PINNED Python geometry generator, and pg_cron
    # cannot call it. The alternatives were a THIRD Railway schedule or this. HANDOFF §11 already
    # records that the collector's second schedule is the one most likely to be skipped, and a
    # third would be worse — so the rollup runs where a snapshot has just been finalized, which is
    # the only moment new work exists.
    #
    # Guarded, and reported rather than raised: collection is the paid work being rescued here, and
    # a rollup failure must never cost a collected task. `rollup` standalone clears any backlog.
    rollup_summary: dict = {}
    if not args.no_rollup:
        try:
            rolled = coverage_rollup.run_rollup(
                client, settings, limit=settings.rollup_batch_limit
            )
            rollup_summary = {
                "considered": rolled.considered,
                "rolled_up": rolled.rolled_up,
                "prospect_rows": rolled.prospect_rows,
                "problems": rolled.problems,
            }
        except Exception as exc:  # noqa: BLE001 — never lose a collection to a rollup
            rollup_summary = {"error": repr(exc)}
            logging.getLogger(__name__).error(
                "rollup after collect failed", extra={"error": str(exc)[:500]}
            )

    print(
        json.dumps(
            {
                "ready_seen": report.ready_seen,
                "collected": report.collected,
                "rows_written": report.rows_written,
                "still_pending": report.still_pending,
                "failed": report.failed,
                "foreign_tasks": report.foreign,
                "recovered_by_tag": report.recovered_by_tag,
                "snapshots_finalized": report.snapshots_finalized,
                "problems": report.problems,
                "rollup": rollup_summary,
            },
            indent=2,
        )
    )
    # A collector that found nothing is the NORMAL case between cycles, so it exits zero. The
    # failure worth reporting is one that saw work and could not do it.
    return 1 if report.problems and not report.collected else 0


def cmd_tick(args) -> int:
    """One heartbeat: collect (always, free) + execute at most ONE scan order + at most ONE
    onboard order.

    This is what the §11 cron runs. It replaces nothing — `collect` remains the pure free
    command — it drains the `scan_request` orders the UI places (DECISIONS.md 2026-08-06) and the
    `onboard_request` orders the "City + Business type" form places (DECISIONS.md 2026-08-08:
    discover → filter → scan for a typed city). `tick` is deliberately NOT in PAID_COMMANDS: its
    spend is authorized per-run by the order row (signed, single-use), the evidence an accidental
    deploy cannot manufacture. Requiring the env token here would make every cron tick refuse —
    the §8a collect-gating mistake wearing a new name.

    Order within the tick: collect FIRST (rescue paid work already in flight), then the quick scan
    drain, then the onboard drain LAST because it runs a multi-minute Outscraper pull — the newly
    posted scan it opens is collected on the NEXT tick, exactly like a scan order's. The claim on
    each queue is conditional, so an onboard tick that runs long cannot be double-processed by the
    next heartbeat starting before it finishes.
    """
    import asyncio as _asyncio

    from api.services import onboard_queue, scan_queue

    code = cmd_collect(args)

    settings = get_settings()
    client = _client()
    drained = _asyncio.run(scan_queue.drain_one(client, settings))
    onboarded = _asyncio.run(onboard_queue.drain_one(client, settings))
    print(
        json.dumps(
            {
                "scan": {
                    "orders_claimed": drained.claimed,
                    "order_id": drained.order_id,
                    "submarket": drained.submarket,
                    "keyword": drained.keyword,
                    "outcome": drained.outcome,
                    "snapshot_id": drained.snapshot_id,
                    "posted": drained.posted,
                    "error": drained.error,
                    "problems": drained.problems,
                },
                "onboard": {
                    "orders_claimed": onboarded.claimed,
                    "order_id": onboarded.order_id,
                    "submarket": onboarded.submarket,
                    "keyword": onboarded.keyword,
                    "category": onboarded.category,
                    "stage": onboarded.stage,
                    "outcome": onboarded.outcome,
                    "prospects_ingested": onboarded.prospects_ingested,
                    "prospects_survived": onboarded.prospects_survived,
                    "snapshot_id": onboarded.snapshot_id,
                    "posted": onboarded.posted,
                    "error": onboarded.error,
                },
            },
            indent=2,
        )
    )
    # A failed ORDER (either queue) exits non-zero even though the tick itself survived: an
    # unattended queue whose orders quietly fail is the "green badge over a crashed job" shape
    # (§6.2), and the exit code is the only summary a cron run leaves besides its logs.
    return 1 if "failed" in (drained.outcome, onboarded.outcome) else code


def cmd_rollup(args) -> int:
    """Roll finalized snapshots into `prospect_coverage`. FREE — no provider is contacted.

    Storage spec §4. One transaction per snapshot, ending in `finalize_snapshot_rollup()`, so a
    rollup that cannot write every prospect's `rank_vector` writes nothing at all rather than
    leaving summary numbers behind with no picture to check them against.

    `collect` already does this for the snapshots it finalizes. This command exists for the two
    cases that misses: a backlog left by a rollup that failed for a fixable reason, and re-running
    one named snapshot after fixing it. Both are idempotent — a snapshot with a completion marker
    is refused, not rewritten.

    `--verify` recomputes every coverage statistic FROM the stored vectors and reports
    disagreements (storage spec §12). Nothing is written, so it is safe to run against anything.
    """
    from api.services import coverage_rollup

    settings = get_settings()
    client = _client()

    if args.verify:
        snapshot_ids = [args.snapshot] if args.snapshot else [
            r["snapshot_id"]
            for r in (client.table("snapshot_rollup").select("snapshot_id").execute().data or [])
        ]
        results = [coverage_rollup.verify_rollup(client, sid) for sid in snapshot_ids]
        print(json.dumps({"verified": len(results), "snapshots": results}, indent=2))
        return 1 if any(r["problems"] for r in results) else 0

    report = coverage_rollup.run_rollup(
        client,
        settings,
        snapshot_ids=[args.snapshot] if args.snapshot else None,
        limit=args.limit if args.snapshot is None else None,
    )
    print(
        json.dumps(
            {
                "considered": report.considered,
                "rolled_up": report.rolled_up,
                "already_rolled_up": report.already_done,
                "prospect_rows": report.prospect_rows,
                "results": report.results,
                "problems": report.problems,
            },
            indent=2,
        )
    )
    # Nothing pending is the NORMAL state between scans, so an empty run exits zero. A snapshot
    # that was considered and could not be rolled up is the failure worth reporting: it means a
    # partition will never drop, and fail-closed retention is only safe while somebody knows.
    return 1 if report.problems else 0


def cmd_probe_ai_granularity(args) -> int:
    """The I-004 spike: does the place name in an AI prompt change the answer? BILLS a few cents.

    Nine chat completions — three place names x three samples — against one engine. The question
    is not "is the model right"; it is whether a finer name actually narrows the answer, or whether
    the model silently answers the metro question while we believe we asked a specific one. See
    `api/services/ai_granularity.py` for why that third case is the one worth paying to detect.

    The three names are supplied rather than derived. I-073's free evidence run already narrowed
    which LA names are worth testing, and choosing among them is a judgement about the market, not
    something a script should guess from a definition file.
    """
    import asyncio as _asyncio

    from api.services import ai_granularity as aig

    definition = seeding.MarketDefinition.from_file(args.definition)

    keyword = args.keyword
    if not keyword:
        primary = [k for k in definition.keywords if k.get("is_primary")]
        pool = primary or definition.keywords
        keyword = str(pool[0]["term"]) if pool else ""
    if not keyword:
        print("REFUSED: no keyword — pass --keyword", file=sys.stderr)
        return 2

    missing = [
        flag
        for flag, value in (
            ("--metro", args.metro),
            ("--suburb", args.suburb),
            ("--neighbourhood", args.neighbourhood),
        )
        if not value
    ]
    if missing:
        print(
            "REFUSED: the three place names are a deliberate choice, not a default — pass "
            f"{', '.join(missing)}. For the LA market, I-073's free evidence run suggests "
            "--metro 'Los Angeles' --suburb 'Woodland Hills' --neighbourhood 'Hollywood' "
            "(Hollywood is the risky case: real neighbourhood, businesses addressed "
            "'Los Angeles').",
            file=sys.stderr,
        )
        return 2

    settings = get_settings()
    absent = aig.missing_openai_vars(settings)
    if absent:
        print(f"REFUSED: missing credentials: {', '.join(absent)}", file=sys.stderr)
        return 2

    report = _asyncio.run(
        aig.run_spike(
            settings,
            keyword=keyword,
            metro=args.metro,
            suburb=args.suburb,
            neighbourhood=args.neighbourhood,
            model=settings.ai_granularity_model,
        )
    )

    summary = aig.summarize(report)
    summary["model"] = settings.ai_granularity_model
    print(json.dumps(summary, indent=2), flush=True)

    # The raw replies, after the summary, because they are evidence rather than result — and
    # because a summary computed from unreadable answers is the failure this spike is about.
    print("--- RAW SAMPLES ---", flush=True)
    for sample in report.samples:
        print(
            json.dumps(
                {
                    "level": sample.level,
                    "place": sample.place,
                    "sample": sample.sample_index,
                    "businesses": list(sample.businesses),
                    "error": sample.error,
                    "raw": sample.raw[:600],
                },
                indent=2,
            ),
            flush=True,
        )

    # A run where every call failed produced no evidence and must not read as a completed spike.
    if summary["errors"] == len(report.samples):
        print("REFUSED: every sample errored — no evidence gathered", file=sys.stderr)
        return 1
    return 0


def _resolve_rollup_snapshot(client, market_id: str, args):
    """The snapshot to render, or None with a printed reason. It MUST be rolled up.

    A snapshot with no `snapshot_rollup` marker has no `prospect_coverage` rows to read (the rollup
    writes them), so rendering one would produce nothing — refused rather than drawn blank.
    """
    from api.services.paging import fetch_all

    rolled = {
        r["snapshot_id"]
        for r in fetch_all(lambda: client.table("snapshot_rollup").select("snapshot_id"))
    }

    if args.snapshot:
        rows = (
            client.table("scan_snapshot").select("*").eq("id", args.snapshot).limit(1).execute().data
        )
        if not rows:
            print(f"REFUSED: snapshot {args.snapshot} not found", file=sys.stderr)
            return None
        if rows[0]["id"] not in rolled:
            print(
                f"REFUSED: snapshot {args.snapshot} has no rollup marker — nothing to render. "
                f"Run `rollup` first.",
                file=sys.stderr,
            )
            return None
        return rows[0]

    if not args.submarket:
        print(
            "REFUSED: pass --snapshot <id>, or --submarket (+ optional --keyword) to render that "
            "submarket's latest rolled-up snapshot.",
            file=sys.stderr,
        )
        return None

    subs = (
        client.table("submarket").select("id, name").eq("market_id", market_id).execute().data or []
    )
    match = [s for s in subs if s["name"].lower() == args.submarket.lower()]
    if not match:
        print(f"REFUSED: no submarket named {args.submarket!r}", file=sys.stderr)
        return None

    snaps = [
        s
        for s in (
            client.table("scan_snapshot").select("*").eq("submarket_id", match[0]["id"]).execute().data
            or []
        )
        if s["id"] in rolled
    ]
    if args.keyword:
        kws = (
            client.table("keyword").select("id, term").eq("market_id", market_id).execute().data or []
        )
        wanted = {k["id"] for k in kws if k["term"].lower() == args.keyword.lower()}
        snaps = [s for s in snaps if s["keyword_id"] in wanted]
    if not snaps:
        print("REFUSED: no rolled-up snapshot for that submarket/keyword yet", file=sys.stderr)
        return None

    # scanned_at then id, so a tie between two snapshots written in one transaction is broken
    # deterministically (now() is transaction time — HANDOFF §6.14), the same tie-break the
    # placeholder-score view uses.
    snaps.sort(key=lambda s: (str(s.get("scanned_at") or ""), s["id"]), reverse=True)
    return snaps[0]


def cmd_render_heatmap(args) -> int:
    """Render the coverage heatmap for prospects in one snapshot. FREE — no provider is contacted.

    Reporting-layer-spec §4. Reads `prospect_coverage.rank_vector` + the snapshot's STORED geometry
    (never the current default — CLAUDE.md) and writes one deterministic SVG per prospect to
    `artifact_dir`, keyed by content_hash, with a `report_artifact` provenance row. Renders one
    business with --prospect, or every business holding a coverage row in the snapshot otherwise.
    """
    import os

    from api.services import heatmap
    from api.services.paging import fetch_all

    definition = seeding.MarketDefinition.from_file(args.definition)
    settings = get_settings()
    client = _client()
    market_id = _market_id(client, definition.name)

    snapshot = _resolve_rollup_snapshot(client, market_id, args)
    if snapshot is None:
        return 2

    sub = (
        client.table("submarket").select("name").eq("id", snapshot["submarket_id"]).limit(1).execute().data
    )
    kw = (
        client.table("keyword").select("term").eq("id", snapshot["keyword_id"]).limit(1).execute().data
    )
    sub_name = sub[0]["name"] if sub else "?"
    kw_term = kw[0]["term"] if kw else "?"
    subtitle = f"{kw_term} · {sub_name} · scanned {str(snapshot.get('scanned_at') or '')[:10]}"

    coverage_rows = fetch_all(
        lambda: client.table("prospect_coverage")
        .select("prospect_id, coverage_pct, rank_vector")
        .eq("snapshot_id", snapshot["id"])
    )
    if args.prospect:
        coverage_rows = [r for r in coverage_rows if r["prospect_id"] == args.prospect]

    prospects: dict[str, dict] = {}
    ids = [r["prospect_id"] for r in coverage_rows]
    if ids:
        for row in fetch_all(
            lambda: client.table("prospect").select("id, name, phone, lat, lng").in_("id", ids)
        ):
            prospects[row["id"]] = row

    out_dir = settings.artifact_dir
    os.makedirs(out_dir, exist_ok=True)

    artifacts: list[dict] = []
    problems: list[str] = []
    for cov in coverage_rows:
        pr = prospects.get(cov["prospect_id"], {})
        try:
            inputs = heatmap.build_inputs(
                snapshot=snapshot,
                coverage=cov,
                title=f"{pr.get('name') or 'This business'} — Google Maps coverage",
                subtitle=subtitle,
                business_lat=pr.get("lat"),
                business_lng=pr.get("lng"),
            )
            svg = heatmap.render_heatmap(inputs)
            digest = heatmap.content_hash(svg)
            path = os.path.join(out_dir, f"{digest}.svg")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(svg)

            # Idempotent by content_hash (reporting §6): re-rendering identical inputs is a no-op
            # rather than a duplicate provenance row.
            client.table("report_artifact").upsert(
                {
                    "kind": "heatmap",
                    "subject_type": "prospect",
                    "subject_id": cov["prospect_id"],
                    "snapshot_id": snapshot["id"],
                    "generator_version": heatmap.GENERATOR_VERSION,
                    "geometry_version": snapshot["geometry_version"],
                    "storage_path": path,
                    "content_hash": digest,
                },
                on_conflict="content_hash",
                ignore_duplicates=True,
            ).execute()

            artifacts.append(
                {
                    "prospect_id": cov["prospect_id"],
                    "name": pr.get("name"),
                    "coverage_pct": cov.get("coverage_pct"),
                    "content_hash": digest,
                    "path": path,
                }
            )
        except Exception as exc:  # noqa: BLE001 — one bad row must not stop the batch
            problems.append(f"prospect {cov['prospect_id']}: {exc}")

    print(
        json.dumps(
            {
                "snapshot_id": snapshot["id"],
                "submarket": sub_name,
                "keyword": kw_term,
                "coverage_rows": len(coverage_rows),
                "rendered": len(artifacts),
                "artifacts": artifacts,
                "problems": problems,
            },
            indent=2,
        )
    )
    return 1 if problems and not artifacts else 0


def _snapshot_by_id(client, snapshot_id: str) -> dict | None:
    """One snapshot row with the geometry the renderer needs, or None."""
    rows = (
        client.table("scan_snapshot")
        .select(
            "id, submarket_id, keyword_id, center_lat, center_lng, grid_radius_miles, "
            "grid_spacing_miles, geometry_version, scanned_at"
        )
        .eq("id", snapshot_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def cmd_render_delta(args) -> int:
    """Render the per-point CHANGE heatmap between two snapshots. FREE — no provider is contacted.

    Reporting-layer-spec §4.3. Takes an explicit AFTER (`--snapshot`) and BEFORE
    (`--compare-snapshot`) — no auto-resolution, so the operator names exactly which two scans the
    before/after compares. Renders a `heatmap_delta` per prospect holding a coverage row in BOTH
    snapshots, enforcing every delta guard first (span / provider / drift / matching geometry). A
    guard refusal is reported per prospect, never a blank picture.
    """
    import os

    from api.services import heatmap
    from api.services.paging import fetch_all

    settings = get_settings()
    client = _client()

    if not args.snapshot or not args.compare_snapshot:
        print(
            json.dumps(
                {"error": "render-delta requires --snapshot (after) and --compare-snapshot (before)"}
            )
        )
        return 2

    after = _snapshot_by_id(client, args.snapshot)
    before = _snapshot_by_id(client, args.compare_snapshot)
    if after is None or before is None:
        missing = args.snapshot if after is None else args.compare_snapshot
        print(json.dumps({"error": f"snapshot not found: {missing}"}))
        return 2

    sub = (
        client.table("submarket").select("name").eq("id", after["submarket_id"]).limit(1).execute().data
    )
    kw = client.table("keyword").select("term").eq("id", after["keyword_id"]).limit(1).execute().data
    sub_name = sub[0]["name"] if sub else "?"
    kw_term = kw[0]["term"] if kw else "?"
    before_day = str(before.get("scanned_at") or "")[:10]
    after_day = str(after.get("scanned_at") or "")[:10]
    subtitle = f"{kw_term} · {sub_name} · {before_day} → {after_day}"

    # A prospect needs coverage in BOTH snapshots to have a change to show.
    def _coverage(snapshot_id: str) -> dict[str, dict]:
        return {
            r["prospect_id"]: r
            for r in fetch_all(
                lambda: client.table("prospect_coverage")
                .select("prospect_id, rank_vector")
                .eq("snapshot_id", snapshot_id)
            )
        }

    cov_before = _coverage(before["id"])
    cov_after = _coverage(after["id"])
    shared_ids = sorted(set(cov_before) & set(cov_after))
    if args.prospect:
        shared_ids = [pid for pid in shared_ids if pid == args.prospect]

    prospects: dict[str, dict] = {}
    if shared_ids:
        for row in fetch_all(
            lambda: client.table("prospect").select("id, name, lat, lng").in_("id", shared_ids)
        ):
            prospects[row["id"]] = row

    out_dir = settings.artifact_dir
    os.makedirs(out_dir, exist_ok=True)

    artifacts: list[dict] = []
    problems: list[str] = []
    for pid in shared_ids:
        pr = prospects.get(pid, {})
        try:
            inputs = heatmap.build_delta_inputs(
                snapshot_before=before,
                coverage_before=cov_before[pid],
                snapshot_after=after,
                coverage_after=cov_after[pid],
                title=f"{pr.get('name') or 'This business'} — change in Google Maps coverage",
                subtitle=subtitle,
                max_span_days=settings.max_delta_span_days,
                business_lat=pr.get("lat"),
                business_lng=pr.get("lng"),
            )
            svg = heatmap.render_delta(inputs)
            digest = heatmap.content_hash(svg)
            path = os.path.join(out_dir, f"{digest}.svg")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(svg)

            client.table("report_artifact").upsert(
                {
                    "kind": "heatmap_delta",
                    "subject_type": "prospect",
                    "subject_id": pid,
                    "snapshot_id": after["id"],
                    "compare_snapshot_id": before["id"],
                    "generator_version": heatmap.GENERATOR_VERSION,
                    "geometry_version": after["geometry_version"],
                    "storage_path": path,
                    "content_hash": digest,
                },
                on_conflict="content_hash",
                ignore_duplicates=True,
            ).execute()

            artifacts.append({"prospect_id": pid, "name": pr.get("name"),
                              "content_hash": digest, "path": path})
        except heatmap.DeltaNotRenderable as exc:
            # A refused delta is a real, expected outcome (guard fired), not a crash — report the
            # machine-readable reason so the operator sees WHY the picture was withheld.
            problems.append(f"prospect {pid}: refused ({exc.reason})")
        except Exception as exc:  # noqa: BLE001 — one bad row must not stop the batch
            problems.append(f"prospect {pid}: {exc}")

    print(
        json.dumps(
            {
                "after_snapshot_id": after["id"],
                "before_snapshot_id": before["id"],
                "submarket": sub_name,
                "keyword": kw_term,
                "shared_prospects": len(shared_ids),
                "rendered": len(artifacts),
                "artifacts": artifacts,
                "problems": problems,
            },
            indent=2,
        )
    )
    return 1 if problems and not artifacts else 0


def cmd_run(args) -> int:
    for step in (cmd_seed, cmd_ingest, cmd_filter):
        code = step(args)
        if code != 0:
            return code
    return 0


# Env vars that may carry the deployed commit. Railway sets RAILWAY_GIT_COMMIT_SHA; the others
# are conventional and cost nothing to check.
_SHA_VARS = ("OUTREACH_BUILD_SHA", "RAILWAY_GIT_COMMIT_SHA", "SOURCE_COMMIT", "GIT_COMMIT")

# The commands that spend money. `probe-dataforseo` is deliberately absent: its discovery pass
# sends only deliberately-invalid tasks, which DataForSEO does not bill. It becomes paid ONLY
# with --sample-place-id, which is handled as an explicit override rather than by listing it
# here, because "this command is free except when it isn't" is exactly the kind of thing a
# static set states wrongly.
#
# `probe-ai-granularity` IS listed despite costing well under a cent for the whole run. The gate's
# rule is "spends money requires an affirmative confirmation", and carving out an exemption for
# small amounts turns a mechanical test into a judgement about size — which is how a paid command
# ends up unconfirmed once someone's estimate is wrong.
#
# `tick` is deliberately absent, and it is the one absence that is a DESIGN rather than a fact
# about billing (DECISIONS.md 2026-08-06). A tick CAN spend — but only when a signed
# `scan_request` order exists, and the order is the affirmative confirmation: single-use, named
# to one submarket x keyword, attributed to the admin who clicked. The env token guards the
# config-driven path; the order row guards the UI path; each is evidence its accidental
# counterpart cannot manufacture. Listing `tick` here would make every cron heartbeat refuse,
# which is the §8a collect-gating mistake with a different spelling.
PAID_COMMANDS = frozenset(
    {"ingest", "run", "calibrate", "verify-reviews", "probe-ai-granularity", "scan", "scan-organic"}
)

SAFE_COMMAND = "filter"


def resolve_command(env: "dict[str, str]") -> str:
    """The command a run will execute, with ABSENCE resolving to the free one.

    `filter` is the safe state, so it is what you get by default, by omission, and by blanking
    the variable. A paid command must be an affirmative act — never a leftover.
    """
    return (env.get("OUTREACH_COMMAND") or "").strip() or SAFE_COMMAND


def spend_denial(
    command: str, env: "dict[str, str]", *, bills: "bool | None" = None
) -> "str | None":
    """Why this paid command may NOT run, or None if it is authorized.

    **Why a token that repeats the command name rather than a boolean.** A boolean
    (`OUTREACH_CONFIRM_SPEND=true`) authorizes whatever happens to be set, which is precisely the
    failure this guards: a stale config snapshot replayed a `verify-reviews` intent as the
    20-lookup default and spent ~$0.11 nobody asked for. Matching the token to the command name
    means the confirmation carries the INTENT, so a replayed or half-updated config cannot spend
    — the leftover token names a different command than the one about to run, and the run refuses.

    It also makes the two variables fail in the safe direction independently: change the command
    and forget the token → refused; leave a token behind and the command reverts to `filter` →
    nothing paid to authorize.
    """
    pays = bills if bills is not None else command in PAID_COMMANDS
    if not pays:
        return None
    token = (env.get("OUTREACH_CONFIRM_SPEND") or "").strip()
    if not token:
        return (
            f"{command!r} spends money and OUTREACH_CONFIRM_SPEND is not set. "
            f"Set OUTREACH_CONFIRM_SPEND={command} on the same config change that sets "
            f"OUTREACH_COMMAND={command}, or leave OUTREACH_COMMAND unset to run {SAFE_COMMAND}."
        )
    if token != command:
        return (
            f"OUTREACH_CONFIRM_SPEND={token!r} does not authorize {command!r}. The confirmation "
            f"names the command it authorizes, so a stale one cannot approve a different run. "
            f"Set OUTREACH_CONFIRM_SPEND={command} if this run is intended."
        )
    return None


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
    # NOTE the branch label is NOT trustworthy on Railway: a deployment of main's HEAD was
    # observed reporting branch=claude/phase-1-outscraper-ingestion-llje34, the stale connected
    # branch, alongside the correct SHA. The SHA and the command list are the signals; the branch
    # is context.
    sha = next((env[k] for k in _SHA_VARS if env.get(k)), None)
    # The resolved command and the confirm token ride the identity line because what a run is
    # ABOUT TO DO belongs beside which code is running. Reading them from a later log line meant
    # a wrong-command run was only visible after it had started working — and for a paid command,
    # after it had started spending. Neither is a secret: both are command names, and printing
    # the token verbatim is the point, since a mismatch is the thing worth seeing.
    command = resolve_command(env)
    token = (env.get("OUTREACH_CONFIRM_SPEND") or "").strip()
    return (
        f"OUTREACH_BUILD sha={sha[:12] if sha else 'unknown'} "
        f"branch={env.get('RAILWAY_GIT_BRANCH') or 'unknown'} "
        f"command={command}{' PAID' if command in PAID_COMMANDS else ''} "
        f"confirm={token or '(unset)'} "
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


# Everything a LogRecord carries by default. Anything else on a record came from `extra=`.
_STANDARD_RECORD_FIELDS = set(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}


class _ExtraFormatter(logging.Formatter):
    """Print `extra=` payloads, which the plain format string silently dropped.

    Seventeen call sites across this codebase put the entire content of their log line in `extra`
    — the place_id of a failed lookup, the row count behind the I-036 truncation guard, the
    projected spend before a paid run — and every one of them rendered as a bare sentence with the
    facts removed. "outscraper host unreachable, failing over" without the host. The logs looked
    fine, which is why nobody noticed.

    Fixed here rather than by inlining the values at each call site: this is a formatting bug, the
    call sites are correct, and a fix at the formatter also covers the ones not yet written.
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS
        }
        return f"{base} {extras}" if extras else base


def main() -> int:
    _install_sigterm_marker()
    handler = logging.StreamHandler()
    handler.setFormatter(_ExtraFormatter("%(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    import os

    print(
        build_identity(
            dict(os.environ),
            [
                "seed", "ingest", "filter", "run", "calibrate", "verify-reviews",
                "probe-dataforseo", "probe-ai-granularity", "scan", "scan-organic", "collect", "rollup", "tick",
                "render-heatmap", "render-delta",
            ],
        ),
        flush=True,
    )

    parser = argparse.ArgumentParser(description="Outreach pipeline — Phase 1")
    parser.add_argument(
        "command",
        choices=[
            "seed", "ingest", "filter", "run", "calibrate", "verify-reviews",
            "probe-dataforseo", "probe-ai-granularity", "scan", "scan-organic", "collect", "rollup", "tick",
            "render-heatmap", "render-delta",
        ],
    )
    parser.add_argument("definition", help="path to a market definition JSON file")
    parser.add_argument("--cycle", type=int, default=None, help="cycle number for cost_ledger")
    parser.add_argument(
        "--limit", type=int, default=20,
        help=(
            "places per query (calibrate); prospects to look up (verify-reviews); snapshots to "
            "roll up in one invocation (rollup — the command is idempotent, so a larger backlog "
            "just needs another run)"
        ),
    )
    parser.add_argument(
        "--group", choices=["both_null", "rating_present", "control"], default="both_null",
        help="verify-reviews: which I-041 group to sample",
    )
    parser.add_argument(
        "--sample-place-id", default=None,
        help=(
            "probe-dataforseo: after discovery, send ONE real request per surviving path with "
            "this place_id to learn the response shape. This BILLS (a few cents)."
        ),
    )
    parser.add_argument(
        "--provider", choices=["outscraper", "dataforseo"], default="dataforseo",
        help=(
            "verify-reviews: who to ask. Defaults to dataforseo because it is INDEPENDENT of the "
            "hypothesis — re-asking Outscraper returns the ambiguous value either way (I-050)."
        ),
    )
    parser.add_argument(
        "--keyword", default=None,
        help="probe-ai-granularity: the service asked about. Defaults to the market's primary "
             "keyword.",
    )
    parser.add_argument(
        "--metro", default=None,
        help="probe-ai-granularity: the coarse place name, e.g. 'Los Angeles'.",
    )
    parser.add_argument(
        "--suburb", default=None,
        help="probe-ai-granularity: the mid place name, e.g. 'Woodland Hills'.",
    )
    parser.add_argument(
        "--neighbourhood", default=None,
        help=(
            "probe-ai-granularity: the fine place name, e.g. 'Hollywood'. Pick the name you most "
            "suspect the model will not recognise — that is the case worth paying to detect."
        ),
    )
    parser.add_argument(
        "--submarket", default=None,
        help="scan: the ONE submarket to scan, by name. Required — see cmd_scan.",
    )
    parser.add_argument(
        "--allow-geometry-change",
        action="store_true",
        help="permit geometry edits to submarkets that have NOT been scanned",
    )
    parser.add_argument(
        "--snapshot", default=None,
        help=(
            "rollup / render-heatmap: one snapshot id, instead of everything awaiting a rollup. "
            "render-delta: the AFTER snapshot (required)."
        ),
    )
    parser.add_argument(
        "--compare-snapshot", default=None,
        help=(
            "render-delta: the BEFORE snapshot to compare against (required). Must share the "
            "after snapshot's geometry — a before/after across different grids is refused."
        ),
    )
    parser.add_argument(
        "--prospect", default=None,
        help="render-heatmap / render-delta: one prospect id, instead of every prospect in scope",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help=(
            "rollup: recompute every coverage statistic from the stored rank_vectors and report "
            "disagreements. Writes nothing."
        ),
    )
    parser.add_argument(
        "--no-rollup", action="store_true",
        help=(
            "collect: do NOT roll up the snapshots this tick finalizes. The rollup is free and "
            "riding the collector is what keeps it off a third cron schedule, so this is for "
            "isolating a collection problem, not for routine use."
        ),
    )
    handlers = {
        "seed": cmd_seed,
        "ingest": cmd_ingest,
        "filter": cmd_filter,
        "run": cmd_run,
        "calibrate": cmd_calibrate,
        "verify-reviews": cmd_verify_reviews,
        "probe-dataforseo": cmd_probe_dataforseo,
        "probe-ai-granularity": cmd_probe_ai_granularity,
        "scan": cmd_scan,
        "scan-organic": cmd_scan_organic,
        "collect": cmd_collect,
        "rollup": cmd_rollup,
        "tick": cmd_tick,
        "render-heatmap": cmd_render_heatmap,
        "render-delta": cmd_render_delta,
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
        # The spend gate, BEFORE the handler and before any credential is touched. Raising
        # SystemExit rather than returning routes it through the marker path below, so a refused
        # run reports `OUTREACH_RESULT status=failed` with the reason — a refusal has to be as
        # visible as a crash, or an unattended job that silently declined to work looks identical
        # to one that had nothing to do.
        denial = spend_denial(
            command,
            dict(os.environ),
            bills=True if getattr(args, "sample_place_id", None) else None,
        )
        if denial:
            raise SystemExit(denial)
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
