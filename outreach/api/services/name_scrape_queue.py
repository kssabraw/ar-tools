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
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from . import name_scrape

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
        rows.append(
            {
                "prospect_id": result.prospect_id,
                "place_id": place_id,
                "contact_index": idx,
                "source": CONTACT_SOURCE,
                "raw": {
                    "source_kind": name.source_kind,
                    "evidence": name.evidence,
                    "source_urls": list(result.source_urls),
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


async def process_order(
    db: Any, settings: Settings, order: dict[str, Any]
) -> NameScrapeOrderReport:
    """Scrape one claimed order end to end. Never raises past recording the failure on the order."""
    report = NameScrapeOrderReport(order_id=str(order["id"]))
    prospect_ids = list(order.get("prospect_ids") or [])
    report.requested = len(prospect_ids)

    if not prospect_ids:
        report.outcome = "failed"
        report.error = "order has no prospects"
        _finish(db, report.order_id, {"status": "failed", "error": report.error,
                                      "requested_count": 0})
        return report

    if len(prospect_ids) > settings.name_scrape_max_places_per_order:
        report.outcome = "failed"
        report.error = (
            f"selection of {len(prospect_ids)} exceeds name_scrape_max_places_per_order "
            f"{settings.name_scrape_max_places_per_order}"
        )
        _finish(db, report.order_id, {"status": "failed", "error": report.error,
                                      "requested_count": report.requested})
        return report

    prospects = _load_prospects(db, prospect_ids)
    skip = _already_scraped(db, prospect_ids)
    report.skipped = sum(1 for pid in prospect_ids if pid in skip)

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
        _finish(
            db, report.order_id,
            {"status": "done", "requested_count": report.requested,
             "skipped_count": report.skipped, "scraped_count": 0, "found_count": 0,
             "name_count": 0, "failed_count": 0, "error": None},
        )
        return report

    await _scrape_and_store(db, settings, to_scrape, report.order_id, report)

    report.outcome = "done"
    _finish(
        db, report.order_id,
        {"status": "done", "requested_count": report.requested,
         "skipped_count": report.skipped, "scraped_count": report.scraped,
         "found_count": report.found, "name_count": report.names,
         "failed_count": report.failed, "error": None},
    )
    logger.info(
        "name scrape order executed",
        extra={"order_id": report.order_id, "scraped": report.scraped, "found": report.found,
               "names": report.names, "failed": report.failed},
    )
    return report


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
    db: Any, settings: Settings, *, max_orders: int | None = None
) -> NameScrapeDrainReport:
    """Claim and process up to `max_orders` pending orders (default `name_scrape_orders_per_tick`).
    FREE — no order spends, so this is order-gated only (no env token), like the enrich drain."""
    report = NameScrapeDrainReport()
    limit = max_orders if max_orders is not None else settings.name_scrape_orders_per_tick
    while report.orders_processed < max(0, limit):
        order = claim_next_order(db)
        if order is None:
            break
        report.orders.append(await process_order(db, settings, order))
        report.orders_processed += 1
    return report
