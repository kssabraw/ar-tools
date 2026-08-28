"""The name-scrape-order drain: a UI request becomes a FREE site scrape for owner/manager names.

Sibling to `enrich_queue`, minus the money. Enrichment is a signed spend order; this is FREE (own
HTTP GET, the `scan_tech` posture), so there is NO budget guard and NO `cost_ledger` write — the
order row exists only to carry the selection and give the UI something to poll, exactly like the
free tech backlog would if it were UI-triggered.

What it keeps from the enrich drain, because those properties are about correctness not cost:

  * **Conditional claim** — two ticks cannot both take one order.
  * **Idempotent skip** — a prospect already `found`/`no_names` is not re-scraped; only `unreachable`
    / `failed` (the site was down, or the fetch errored) is retried. A re-order is a cheap resume.
  * **Replace-on-place, but ONLY the site-scraped contacts** — storing deletes this prospect's
    `source='site_scrape'` contacts and re-inserts, so a re-scrape never duplicates. It must NEVER
    touch the `source='outscraper'` contacts enrichment wrote — the two producers are independent.
  * **Measured-vs-found** — an `unreachable` result marks the prospect `unreachable`, never
    "no owner named". The marker table records the distinction the report needs.

Chunked so a crash marks the finished prospects (idempotent skip on re-order) and only re-fetches
the rest — the free analogue of the enrich drain's per-chunk isolation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings
from . import name_confidence, name_scrape

logger = logging.getLogger(__name__)

_TABLE = "name_scrape_request"
_MARKER = "prospect_name_scrape"
_CONTACT = "prospect_contact"
CONTACT_SOURCE = "site_scrape"

# Durable per-prospect answers — never re-scraped by a re-order. `unreachable`/`failed` are absent:
# a site that was down may be up on a re-order, so they are retryable.
_DURABLE = ("found", "no_names")


@dataclass
class NameScrapeOrderReport:
    order_id: str = ""
    outcome: str = "idle"       # idle | done | failed
    requested: int = 0
    skipped: int = 0
    scraped: int = 0            # prospects fetched this run (found + no_names + unreachable)
    found: int = 0             # prospects with ≥1 name
    names: int = 0             # total contact rows written
    unreachable: int = 0
    failed: int = 0
    error: str = ""
    problems: list[str] = field(default_factory=list)


@dataclass
class NameScrapeDrainReport:
    orders_processed: int = 0
    orders: list[NameScrapeOrderReport] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def recover_stuck_orders(db: Any, settings: Settings) -> int:
    """Reset `running` orders older than `name_scrape_stuck_order_minutes` back to `pending` so a
    later tick resumes them (I-119 sibling — this FREE drain has a per-tick budget but had no reaper).
    A normal tick holds an order `running` only for the tens of seconds it scrapes one budget's worth,
    so a much-older `running` is a container that died mid-tick (a hard SIGKILL before the budget's
    work finished). The idempotent marker skip means the resume re-scrapes only the un-done prospects.
    Returns the number recovered."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=settings.name_scrape_stuck_order_minutes)
    ).isoformat()
    stuck = (
        db.table(_TABLE).select("id").eq("status", "running").lt("started_at", cutoff)
        .execute().data or []
    )
    recovered = 0
    for row in stuck:
        # Conditional on still-running so we never stomp an order a live tick just re-claimed.
        updated = (
            db.table(_TABLE).update({"status": "pending", "started_at": None})
            .eq("id", row["id"]).eq("status", "running").execute().data or []
        )
        if updated:
            recovered += 1
            logger.warning("recovered stuck name-scrape order", extra={"order_id": row["id"]})
    return recovered


def claim_next_order(db: Any) -> dict[str, Any] | None:
    """The oldest pending order, claimed via read-then-conditional-update (loses a race → takes
    nothing this tick)."""
    rows = (
        db.table(_TABLE)
        .select("*")
        .eq("status", "pending")
        .order("created_at", desc=False)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None
    order = rows[0]
    claimed = (
        db.table(_TABLE)
        .update({"status": "running", "started_at": _now()})
        .eq("id", order["id"])
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    return dict(order, status="running") if claimed else None


def _finish(db: Any, order_id: str, fields: dict[str, Any]) -> None:
    db.table(_TABLE).update(dict(fields, finished_at=_now())).eq("id", order_id).execute()


def _load_prospects(db: Any, prospect_ids: list[str]) -> dict[str, dict[str, Any]]:
    """{prospect_id: {id, place_id, name, website}} for the selection, chunked under the 1000-row
    PostgREST cap."""
    out: dict[str, dict[str, Any]] = {}
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            db.table("prospect")
            .select("id, place_id, name, website")
            .in_("id", chunk)
            .execute()
            .data
            or []
        ):
            out[row["id"]] = row
    return out


def _already_scraped(db: Any, prospect_ids: list[str]) -> set[str]:
    """Prospects whose name-scrape answer is already durable (found|no_names)."""
    done: set[str] = set()
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            db.table(_MARKER)
            .select("prospect_id, status")
            .in_("prospect_id", chunk)
            .in_("status", list(_DURABLE))
            .execute()
            .data
            or []
        ):
            done.add(row["prospect_id"])
    return done


def _contact_rows(result: name_scrape.NameScrapeResult, place_id: str) -> list[dict[str, Any]]:
    """`prospect_contact` insert rows for a scrape result — the names + join keys + site provenance.
    `source='site_scrape'` so these never collide with (or get replaced alongside) Outscraper
    contacts. The evidence + which page it came from ride in `raw`."""
    rows: list[dict[str, Any]] = []
    for idx, name in enumerate(result.names):
        conf = name_confidence.score_site_scrape(
            source_kind=name.source_kind, title=name.title, page_count=name.page_count
        )
        rows.append(
            {
                "prospect_id": result.prospect_id,
                "place_id": place_id,
                "contact_index": idx,
                "source": CONTACT_SOURCE,
                "confidence": conf.score,
                "confidence_band": conf.band,
                "raw": {
                    "source_kind": name.source_kind,
                    "evidence": name.evidence,
                    "source_urls": list(result.source_urls),
                    "confidence": conf.factors,
                },
                **name.as_contact(),
            }
        )
    return rows


def _store_result(
    db: Any, result: name_scrape.NameScrapeResult, place_id: str, order_id: str
) -> int:
    """Persist one scrape result. Replaces THIS prospect's site_scrape contacts (never the
    Outscraper ones) and upserts the marker. Contacts first, then the marker — a crash between them
    leaves the marker absent (retried), never present-with-stale-children. Returns names written."""
    rows = _contact_rows(result, place_id)

    # Replace-on-place, scoped to site_scrape — the Outscraper contacts are a different producer's.
    db.table(_CONTACT).delete().eq("prospect_id", result.prospect_id).eq(
        "source", CONTACT_SOURCE
    ).execute()
    if rows:
        db.table(_CONTACT).insert(rows).execute()

    db.table(_MARKER).upsert(
        {
            "prospect_id": result.prospect_id,
            "status": result.status,
            "name_count": len(rows),
            "pages_fetched": result.pages_fetched,
            "source_urls": list(result.source_urls),
            "name_scrape_request_id": order_id,
            "fetch_status": result.fetch_status,
            "error": None,
            "raw": [
                {
                    "full_name": n.full_name,
                    "title": n.title,
                    "source_kind": n.source_kind,
                    "evidence": n.evidence,
                }
                for n in result.names
            ]
            or None,
            "scraped_at": _now(),
        },
        on_conflict="prospect_id",
    ).execute()
    return len(rows)


def _mark_failed(db: Any, *, prospect_id: str, order_id: str, error: str) -> None:
    """Record a per-prospect scrape failure (retryable) without touching any contacts."""
    db.table(_MARKER).upsert(
        {
            "prospect_id": prospect_id,
            "status": "failed",
            "name_count": 0,
            "pages_fetched": 0,
            "name_scrape_request_id": order_id,
            "fetch_status": None,
            "error": error[:500],
            "scraped_at": _now(),
        },
        on_conflict="prospect_id",
    ).execute()


def _order_marker_tally(db: Any, order_id: str | None, prospect_ids: list[str]) -> dict[str, int]:
    """This order's CUMULATIVE progress, read from the markers it wrote (so a multi-tick resume
    reports the whole order, not just the last batch). Only markers carrying THIS order_id are
    attributed — a durable marker left by a PRIOR order is a skip, not this order's work. Pure over
    the DB read; chunked under the 1000-row cap."""
    scraped = found = names = failed = 0
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            db.table(_MARKER)
            .select("prospect_id, status, name_count, name_scrape_request_id")
            .in_("prospect_id", chunk)
            .execute()
            .data
            or []
        ):
            if str(row.get("name_scrape_request_id")) != str(order_id):
                continue
            status = row.get("status")
            if status == "failed":
                failed += 1
            elif status in ("found", "no_names", "unreachable"):
                scraped += 1
            if status == "found":
                found += 1
                names += int(row.get("name_count") or 0)
    return {"scraped": scraped, "found": found, "names": names, "failed": failed}


def _write_order_progress(
    db: Any, order_id: str, *, status: str, requested: int, no_website: int,
    tally: dict[str, int],
) -> None:
    """Persist an order's cumulative counters (from the marker tally) + its status. `done` stamps
    finished_at; `pending` (a partial left to resume) does not. `skipped` = the requested prospects
    this order neither attempted nor found unscrapable — i.e. durable from a prior order."""
    attempted = tally["scraped"] + tally["failed"]
    counts = {
        "status": status,
        "requested_count": requested,
        "skipped_count": max(0, requested - attempted - no_website),
        "scraped_count": tally["scraped"],
        "found_count": tally["found"],
        "name_count": tally["names"],
        "failed_count": tally["failed"],
        "error": None,
    }
    if status == "done":
        counts["finished_at"] = _now()
    db.table(_TABLE).update(counts).eq("id", order_id).execute()


async def process_order(
    db: Any, settings: Settings, order: dict[str, Any], *, max_prospects: int
) -> tuple[NameScrapeOrderReport, int, bool]:
    """Scrape up to `max_prospects` of one claimed order's due prospects. Never raises past recording
    the failure on the order.

    Returns `(report, scraped_this_call, finished)`. When the order's due set is larger than
    `max_prospects`, only that many are scraped this call and the order is left PENDING (finished
    False) — the marker-based idempotent skip means the next tick's resume re-scrapes only the rest.
    The order's persisted counters are the CUMULATIVE marker tally, so a resumed order still reports
    its whole self."""
    report = NameScrapeOrderReport(order_id=str(order["id"]))
    prospect_ids = list(order.get("prospect_ids") or [])
    report.requested = len(prospect_ids)

    if not prospect_ids:
        report.outcome = "failed"
        report.error = "order has no prospects"
        _finish(db, report.order_id, {"status": "failed", "error": report.error,
                                      "requested_count": 0})
        return report, 0, True

    if len(prospect_ids) > settings.name_scrape_max_places_per_order:
        report.outcome = "failed"
        report.error = (
            f"selection of {len(prospect_ids)} exceeds name_scrape_max_places_per_order "
            f"{settings.name_scrape_max_places_per_order}"
        )
        _finish(db, report.order_id, {"status": "failed", "error": report.error,
                                      "requested_count": report.requested})
        return report, 0, True

    prospects = _load_prospects(db, prospect_ids)
    skip = _already_scraped(db, prospect_ids)
    report.skipped = sum(1 for pid in prospect_ids if pid in skip)
    # Existing prospects with no website — not scrapable, not an error, not "skipped" (never done).
    no_website = sum(
        1 for pid in prospect_ids
        if pid not in skip and pid in prospects and not (prospects[pid].get("website") or "").strip()
    )

    # Needs a website (nothing to fetch otherwise) AND a place_id (the contact row's NOT-NULL join
    # key). A prospect missing either is not an error — it just isn't scrapable.
    to_scrape = [
        prospects[pid]
        for pid in prospect_ids
        if pid not in skip and pid in prospects
        and prospects[pid].get("website") and prospects[pid].get("place_id")
    ]

    if not to_scrape:
        report.outcome = "done"
        tally = _order_marker_tally(db, report.order_id, prospect_ids)
        _write_order_progress(db, report.order_id, status="done", requested=report.requested,
                              no_website=no_website, tally=tally)
        return report, 0, True

    # Budget: scrape at most `max_prospects` this call; leave the rest to resume next tick.
    cap = max(1, max_prospects)
    batch = to_scrape[:cap]
    finished = len(to_scrape) <= cap

    await _scrape_and_store(db, settings, batch, report.order_id, report)

    tally = _order_marker_tally(db, report.order_id, prospect_ids)
    _write_order_progress(
        db, report.order_id, status="done" if finished else "pending",
        requested=report.requested, no_website=no_website, tally=tally,
    )
    report.outcome = "done" if finished else "partial"
    logger.info(
        "name scrape order %s", "executed" if finished else "partial (resuming next tick)",
        extra={"order_id": report.order_id, "scraped_this_call": len(batch),
               "found_total": tally["found"], "names_total": tally["names"],
               "failed_total": tally["failed"], "finished": finished},
    )
    return report, len(batch), finished


async def _scrape_and_store(
    db: Any,
    settings: Settings,
    prospects: list[dict[str, Any]],
    order_id: str | None,
    report: NameScrapeOrderReport,
) -> None:
    """Chunked scrape → store, tallying into `report`. Shared by the order drain and the CLI market
    backfill. Chunking gives crash isolation (finished prospects are marked, skipped on re-run) and
    bounds the in-flight fetch batch; a chunk that raises marks only its prospects retryable."""
    by_id = {p["id"]: p for p in prospects}
    ids = list(by_id.keys())
    chunk_size = max(1, settings.name_scrape_chunk_size)
    for start in range(0, len(ids), chunk_size):
        chunk_ids = ids[start : start + chunk_size]
        chunk = [by_id[i] for i in chunk_ids]
        try:
            results, errors = await name_scrape.scrape_names(settings, chunk)
        except Exception as exc:  # noqa: BLE001 — the order must resolve; mark the chunk retryable
            logger.error("name scrape chunk failed", extra={"order_id": order_id})
            for pid in chunk_ids:
                _mark_failed(db, prospect_id=pid, order_id=order_id, error=repr(exc))
                report.failed += 1
            report.problems.append(f"chunk @ {start}: {repr(exc)[:200]}")
            continue

        by_result = {r.prospect_id: r for r in results}
        errored = {e.split(":", 1)[0].strip() for e in errors}
        for pid in chunk_ids:
            result = by_result.get(pid)
            if result is None:
                _mark_failed(db, prospect_id=pid, order_id=order_id,
                             error=_first_error(errors, pid) if pid in errored else "no result")
                report.failed += 1
                continue
            written = _store_result(db, result, by_id[pid]["place_id"], order_id)
            report.scraped += 1
            report.names += written
            if result.status == "found":
                report.found += 1
            elif result.status == "unreachable":
                report.unreachable += 1
        report.problems.extend(errors)


async def run_name_scrape_market(
    db: Any, settings: Settings, *, market_id: str, limit: int | None = None
) -> NameScrapeOrderReport:
    """Scrape every website-carrying prospect in a market that lacks a durable name-scrape marker.
    The FREE ops/backfill path (`scan-names` CLI) — no order row, so markers carry a null request id.
    Idempotent: a prospect already found/no_names is skipped, so a re-run only fills the rest."""
    from .paging import fetch_all

    def _q():
        return (
            db.table("prospect")
            .select("id, place_id, name, website")
            .eq("market_id", market_id)
            .not_.is_("website", "null")
        )

    prospects = [p for p in fetch_all(_q) if p.get("website") and p.get("place_id")]
    skip = _already_scraped(db, [p["id"] for p in prospects])
    due = [p for p in prospects if p["id"] not in skip]
    if limit:
        due = due[:limit]

    report = NameScrapeOrderReport(order_id="cli", outcome="done")
    report.requested = len(due)
    report.skipped = len(prospects) - len(due) if not limit else 0
    if due:
        await _scrape_and_store(db, settings, due, None, report)
    return report


def _first_error(errors: list[str], prospect_id: str) -> str:
    for err in errors:
        if err.split(":", 1)[0].strip() == prospect_id:
            return err
    return "name scrape failed"


async def drain(
    db: Any, settings: Settings, *, max_orders: int | None = None,
    max_prospects: int | None = None,
) -> NameScrapeDrainReport:
    """Claim and process pending orders, up to `max_orders` (default `name_scrape_orders_per_tick`)
    and a per-tick prospect budget `max_prospects` (default `name_scrape_per_tick`; <=0 = no cap).
    FREE — no order spends, so this is order-gated only (no env token), like the enrich drain.

    The budget bounds the tick's wall-time: an order larger than the remaining budget is scraped up
    to it and left PENDING to resume next tick (a partial ⟹ the budget is spent, so the loop stops).
    Stranded `running` orders are recovered first (I-119 sibling).
    """
    report = NameScrapeDrainReport()
    try:
        recover_stuck_orders(db, settings)
    except Exception as exc:  # noqa: BLE001 — recovery is best-effort; never block the drain
        logger.warning("name-scrape stuck-order recovery failed", extra={"error": str(exc)[:200]})

    order_limit = max_orders if max_orders is not None else settings.name_scrape_orders_per_tick
    per_tick = max_prospects if max_prospects is not None else settings.name_scrape_per_tick
    budget = per_tick if per_tick > 0 else 10**9  # <=0 → effectively no cap
    while report.orders_processed < max(0, order_limit) and budget > 0:
        order = claim_next_order(db)
        if order is None:
            break
        rep, scraped_n, finished = await process_order(db, settings, order, max_prospects=budget)
        report.orders.append(rep)
        report.orders_processed += 1
        budget -= scraped_n
        if not finished:
            break  # a partial means the budget is exhausted; the order resumes next tick
    return report
