"""The enrichment-order drain: a UI selection becomes billed contact enrichment.

Sibling to `scan_queue` / `onboard_queue`, and the same signed-order discipline — conditional claim,
terminal failure, a `cost_ledger` write, the order row as the durable record. The differences all
follow from enrichment being LIGHTWEIGHT and BATCHABLE, unlike a geogrid scan:

  * **Many orders per tick.** A scan's ≤1-per-tick cadence exists so each scan's collection starts
    before the next scan spends; that reasoning does not apply to a cheap request that covers a whole
    selection at once. `drain` processes up to `enrich_orders_per_tick` orders per heartbeat.
  * **One order carries the whole selection.** No submit/collect split: the order's prospects are
    enriched and stored in one pass, chunked so a crash loses at most one chunk's worth (the chunk
    granularity is also where idempotency bites — see below).
  * **Idempotent, so a re-order is a cheap resume, not a re-bill.** A prospect already carrying a
    `prospect_enrichment` row with status `enriched` or `no_contacts` is SKIPPED — it was billed
    once and the answer is durable. Only `failed` (the call errored) is retried. This is what makes a
    stuck-`running` order recoverable: re-place it and only the un-enriched prospects cost money.

Failure is asymmetric, like the scan drains: a budget refusal fails the order with nothing spent; a
mid-run error is recorded but every prospect written before it stays written (and marked, so a
re-order skips it).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from . import cost, enrich_client, enrichment
from .scan_queue import budget_denial

logger = logging.getLogger(__name__)

_TABLE = "enrichment_request"
STAGE_ENRICH = "a5_enrich"


@dataclass
class EnrichOrderReport:
    """What draining one order did — the log-line copy; the durable copy is the order row."""

    order_id: str = ""
    outcome: str = "idle"       # idle | done | failed
    requested: int = 0
    skipped: int = 0
    enriched: int = 0
    contacts: int = 0
    failed: int = 0
    billable: int = 0
    error: str = ""
    problems: list[str] = field(default_factory=list)


@dataclass
class EnrichDrainReport:
    """What one tick's whole enrichment drain did."""

    orders_processed: int = 0
    orders: list[EnrichOrderReport] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def error_place_ids(errors: list[str]) -> set[str]:
    """The place_ids that failed, parsed from `enrich_places` error strings (`"<place_id>: msg"`).
    Pure, so the failed/no-contacts distinction is testable without a provider."""
    out: set[str] = set()
    for err in errors:
        head = err.split(":", 1)[0].strip()
        if head:
            out.add(head)
    return out


def claim_next_order(db: Any) -> dict[str, Any] | None:
    """The oldest pending order, claimed. Read-then-conditionally-claim: the update re-checks
    `status='pending'`, so a row claimed between read and write comes back empty and this tick takes
    nothing (losing a race costs a tick; winning it twice costs paid enrichment)."""
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
    """{prospect_id: {id, place_id, market_id, name}} for the selection, chunked under the 1000-row
    PostgREST cap."""
    out: dict[str, dict[str, Any]] = {}
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            db.table("prospect")
            .select("id, place_id, market_id, name")
            .in_("id", chunk)
            .execute()
            .data
            or []
        ):
            out[row["id"]] = row
    return out


def _already_enriched(db: Any, prospect_ids: list[str]) -> set[str]:
    """Prospects whose enrichment answer is already durable (status enriched|no_contacts) — skipped,
    never re-billed. `failed` is deliberately absent: a failed call is retryable."""
    done: set[str] = set()
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            db.table("prospect_enrichment")
            .select("prospect_id, status")
            .in_("prospect_id", chunk)
            .in_("status", ["enriched", "no_contacts"])
            .execute()
            .data
            or []
        ):
            done.add(row["prospect_id"])
    return done


def _store_prospect(
    db: Any,
    *,
    prospect_id: str,
    place_id: str,
    records: list[dict[str, Any]],
    enrichments: list[str],
    order_id: str,
) -> int:
    """Replace this prospect's contacts with the freshly parsed set and upsert its enrichment status.
    Returns the number of contacts written. Replace-on-place, so a re-run never duplicates contacts.
    """
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.extend(enrichment.contact_rows(record, prospect_id=prospect_id, place_id=place_id))

    # Delete-then-insert: the child rows are fully derived from the latest pull, so replacing them is
    # both correct and idempotent. Contacts first, then the status marker, so a crash between the two
    # leaves the marker absent (status unknown → retried) rather than present-with-stale-children.
    db.table("prospect_contact").delete().eq("prospect_id", prospect_id).execute()
    if rows:
        db.table("prospect_contact").insert(rows).execute()

    db.table("prospect_enrichment").upsert(
        {
            "prospect_id": prospect_id,
            "place_id": place_id,
            "status": "enriched" if rows else "no_contacts",
            "contact_count": len(rows),
            "enrichment_request_id": order_id,
            "enrichments": enrichments,
            "error": None,
            "raw": records[0] if records else None,
            "enriched_at": _now(),
        },
        on_conflict="prospect_id",
    ).execute()
    return len(rows)


def _mark_failed(db: Any, *, prospect_id: str, place_id: str, enrichments: list[str],
                 order_id: str, error: str) -> None:
    """Record a per-prospect enrichment failure (retryable) without disturbing any prior contacts."""
    db.table("prospect_enrichment").upsert(
        {
            "prospect_id": prospect_id,
            "place_id": place_id,
            "status": "failed",
            "contact_count": 0,
            "enrichment_request_id": order_id,
            "enrichments": enrichments,
            "error": error[:500],
            "enriched_at": _now(),
        },
        on_conflict="prospect_id",
    ).execute()


async def process_order(db: Any, settings: Settings, order: dict[str, Any]) -> EnrichOrderReport:
    """Enrich one claimed order end to end. Never raises past recording the failure on the order."""
    report = EnrichOrderReport(order_id=str(order["id"]))
    prospect_ids = list(order.get("prospect_ids") or [])
    report.requested = len(prospect_ids)
    enrichments = list(order.get("enrichments") or settings.enrich_enrichments)

    if not prospect_ids:
        report.outcome = "failed"
        report.error = "order has no prospects"
        _finish(db, report.order_id, {"status": "failed", "error": report.error,
                                      "requested_count": 0})
        return report

    # Defensive per-order ceiling (the placement layer caps it too). A selection past the cap is
    # refused rather than silently truncated — a truncated order that reports `done` is the
    # "reports clean because it did almost nothing" failure this module keeps meeting.
    if len(prospect_ids) > settings.enrich_max_places_per_order:
        report.outcome = "failed"
        report.error = (
            f"selection of {len(prospect_ids)} exceeds enrich_max_places_per_order "
            f"{settings.enrich_max_places_per_order}"
        )
        _finish(db, report.order_id, {"status": "failed", "error": report.error,
                                      "requested_count": report.requested})
        return report

    prospects = _load_prospects(db, prospect_ids)
    skip = _already_enriched(db, prospect_ids)
    report.skipped = sum(1 for pid in prospect_ids if pid in skip)

    to_enrich = [
        prospects[pid]
        for pid in prospect_ids
        if pid not in skip and pid in prospects and prospects[pid].get("place_id")
    ]
    report.billable = len(to_enrich)

    if not to_enrich:
        # Everything was already enriched (or vanished) — a legitimate no-op, not a failure.
        report.outcome = "done"
        _finish(
            db,
            report.order_id,
            {
                "status": "done",
                "requested_count": report.requested,
                "skipped_count": report.skipped,
                "enriched_count": 0,
                "contact_count": 0,
                "failed_count": 0,
                "error": None,
            },
        )
        return report

    # Budget backstop before the money (the placement guard already ran; this catches a runaway order
    # the same way the scan drain does). Rate is the drain-side configured cost per place.
    estimate = report.billable * settings.enrich_cost_per_place_cents
    denial = budget_denial(estimate, settings.max_market_run_cost_cents)
    if denial:
        report.outcome = "failed"
        report.error = denial
        _finish(db, report.order_id, {"status": "failed", "error": denial,
                                      "requested_count": report.requested,
                                      "skipped_count": report.skipped})
        return report

    by_place = {p["place_id"]: p for p in to_enrich}

    # Chunk at the drain so a crash marks the chunks that finished (idempotent skip on re-order) and
    # only re-bills the unfinished ones. The chunk size doubles as enrich_places' concurrency bound.
    chunk_size = max(1, settings.enrich_chunk_size)
    place_list = list(by_place.keys())
    for start in range(0, len(place_list), chunk_size):
        chunk = place_list[start : start + chunk_size]
        try:
            records, errors = await enrich_client.enrich_places(
                settings, chunk, enrichments=enrichments
            )
        except Exception as exc:  # noqa: BLE001 — the order must resolve; mark the chunk retryable
            logger.error("enrich chunk failed", extra={"order_id": report.order_id})
            for place_id in chunk:
                _mark_failed(db, prospect_id=by_place[place_id]["id"], place_id=place_id,
                             enrichments=enrichments, order_id=report.order_id, error=repr(exc))
                report.failed += 1
            report.problems.append(f"chunk @ {start}: {repr(exc)[:200]}")
            continue

        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            pid = record.get(enrich_client.PLACE_TAG)
            if pid:
                grouped.setdefault(pid, []).append(record)
        failed_places = enrich_place_intersection(errors, chunk)

        for place_id in chunk:
            prospect = by_place[place_id]
            recs = grouped.get(place_id, [])
            if not recs and place_id in failed_places:
                _mark_failed(db, prospect_id=prospect["id"], place_id=place_id,
                             enrichments=enrichments, order_id=report.order_id,
                             error=_first_error(errors, place_id))
                report.failed += 1
                continue
            written = _store_prospect(
                db, prospect_id=prospect["id"], place_id=place_id, records=recs,
                enrichments=enrichments, order_id=report.order_id,
            )
            report.enriched += 1
            report.contacts += written
        report.problems.extend(errors)

    # cost_ledger: units = places we sent to the provider (billable), reconciled manually against the
    # Outscraper dashboard like every rate here (I-022). market_id from any billed prospect.
    market_id = next((p.get("market_id") for p in to_enrich if p.get("market_id")), None)
    try:
        db.table("cost_ledger").insert(
            cost.build_ledger_row(
                market_id=market_id,
                cycle_number=None,
                stage=STAGE_ENRICH,
                provider=cost.PROVIDER_OUTSCRAPER,
                units=report.billable,
                cost_cents=report.billable * settings.enrich_cost_per_place_cents,
            )
        ).execute()
    except Exception as exc:  # noqa: BLE001 — a ledger hiccup must not lose the enrichment
        logger.warning("enrich cost_ledger write failed", extra={"error": str(exc)[:200]})

    report.outcome = "done"
    _finish(
        db,
        report.order_id,
        {
            "status": "done",
            "requested_count": report.requested,
            "skipped_count": report.skipped,
            "enriched_count": report.enriched,
            "contact_count": report.contacts,
            "failed_count": report.failed,
            "error": None,
        },
    )
    logger.info(
        "enrich order executed",
        extra={
            "order_id": report.order_id,
            "billable": report.billable,
            "enriched": report.enriched,
            "contacts": report.contacts,
            "failed": report.failed,
        },
    )
    return report


def enrich_place_intersection(errors: list[str], chunk: list[str]) -> set[str]:
    """The chunk's place_ids that appear in the error list. Pure helper for testability."""
    return error_place_ids(errors) & set(chunk)


def _first_error(errors: list[str], place_id: str) -> str:
    for err in errors:
        if err.split(":", 1)[0].strip() == place_id:
            return err
    return "enrichment failed"


async def drain(db: Any, settings: Settings, *, max_orders: int | None = None) -> EnrichDrainReport:
    """Claim and process up to `max_orders` pending orders (default `enrich_orders_per_tick`)."""
    report = EnrichDrainReport()
    limit = max_orders if max_orders is not None else settings.enrich_orders_per_tick
    while report.orders_processed < max(0, limit):
        order = claim_next_order(db)
        if order is None:
            break
        report.orders.append(await process_order(db, settings, order))
        report.orders_processed += 1
    return report
