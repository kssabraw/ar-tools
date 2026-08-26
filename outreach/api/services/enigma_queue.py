"""The Enigma-order drain: a UI selection becomes billed owner/contact enrichment.

Sibling to `enrich_queue`, and the same signed-order discipline — conditional claim, terminal
failure, a `cost_ledger` write, the order row as the durable record — because Enigma bills per
resolved business just as Outscraper enrichment bills per record. The idempotency and
per-business-isolation reasoning is identical; only the provider and the stored shape differ.

  * **Idempotent, so a re-order is a cheap resume, not a re-bill.** A prospect already carrying a
    `prospect_enigma` row with status `resolved` / `no_match` / `no_contacts` is SKIPPED — it was
    billed once and the answer is durable (including a genuine "Enigma has nothing here"). Only
    `failed` (the call errored, or the query was wrong while the shape is being confirmed) is
    retried.
  * **Gated inert.** The caller (`cmd_tick`) only drains Enigma orders when `enigma_api_key` is set,
    so an unprovisioned environment never claims one. `process_order` also refuses if the key went
    missing between placement and drain, failing the order rather than calling an unauthenticated
    endpoint.

Failure is asymmetric, like the other drains: a budget refusal fails the order with nothing spent;
a mid-run per-prospect error is recorded (retryable) while every prospect resolved before it stays
written.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from . import cost, enigma_client, enigma_enrich
from .scan_queue import budget_denial

logger = logging.getLogger(__name__)

_TABLE = "enigma_request"
STAGE_ENIGMA = "a6_enigma"

# Terminal per-prospect states — a re-order does NOT re-bill these. `failed` is absent: a failed
# call (or a wrong-query error) is retryable.
_DONE_STATUSES = ("resolved", "no_match", "no_contacts")


@dataclass
class EnigmaOrderReport:
    order_id: str = ""
    outcome: str = "idle"       # idle | done | failed
    requested: int = 0
    skipped: int = 0
    resolved: int = 0
    owners: int = 0
    contacts: int = 0
    failed: int = 0
    billable: int = 0
    error: str = ""
    problems: list[str] = field(default_factory=list)


@dataclass
class EnigmaDrainReport:
    orders_processed: int = 0
    orders: list[EnigmaOrderReport] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def error_prospect_ids(errors: list[str]) -> set[str]:
    """The prospect_ids that failed, parsed from `match_prospects` error strings (`"<pid>: msg"`).
    Pure, so the failed/resolved split is testable without a provider."""
    out: set[str] = set()
    for err in errors:
        head = err.split(":", 1)[0].strip()
        if head:
            out.add(head)
    return out


def claim_next_order(db: Any) -> dict[str, Any] | None:
    """The oldest pending order, claimed. Read-then-conditionally-claim (update re-checks
    status='pending'), so a row claimed between read and write comes back empty and this tick takes
    nothing — losing a race costs a tick, winning it twice would cost paid enrichment."""
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
    """{prospect_id: {id, place_id, market_id, name, address, phone, website}} for the selection,
    chunked under the 1000-row PostgREST cap. Enigma matches on name + address + phone + website, so
    all four are read; market_id attributes the cost_ledger row."""
    out: dict[str, dict[str, Any]] = {}
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            db.table("prospect")
            .select("id, place_id, market_id, name, address, phone, website")
            .in_("id", chunk)
            .execute()
            .data
            or []
        ):
            out[row["id"]] = row
    return out


def _already_resolved(db: Any, prospect_ids: list[str]) -> set[str]:
    """Prospects whose Enigma answer is already durable (status in _DONE_STATUSES) — skipped, never
    re-billed. `failed` is deliberately absent: a failed call is retryable."""
    done: set[str] = set()
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            db.table("prospect_enigma")
            .select("prospect_id, status")
            .in_("prospect_id", chunk)
            .in_("status", list(_DONE_STATUSES))
            .execute()
            .data
            or []
        ):
            done.add(row["prospect_id"])
    return done


# Every column of prospect_enigma, so an upsert fully REPLACES the prior row rather than leaving
# stale owner fields when a re-resolve drops from resolved → no_match.
_ROW_COLUMNS = (
    "status", "enigma_entity_id", "match_score", "legal_name",
    "owner_name", "owner_title", "owner_role_score", "owner_email", "owner_phone", "owner_evidence",
    "card_revenue_cents", "revenue_growth_pct", "location_count", "officers", "raw",
)


def _store_row(db: Any, row: dict[str, Any], *, order_id: str) -> None:
    """Upsert one prospect_enigma row (replace-on-prospect, so a re-run never duplicates)."""
    payload: dict[str, Any] = {
        "prospect_id": row["prospect_id"],
        "place_id": row["place_id"],
        "enigma_request_id": order_id,
        "error": None,
        "resolved_at": _now(),
    }
    for col in _ROW_COLUMNS:
        payload[col] = row.get(col) if col != "officers" else row.get("officers", [])
    db.table("prospect_enigma").upsert(payload, on_conflict="prospect_id").execute()


def _mark_failed(db: Any, *, prospect_id: str, place_id: str, order_id: str, error: str) -> None:
    """Record a per-prospect Enigma failure (retryable) without disturbing any prior resolution."""
    db.table("prospect_enigma").upsert(
        {
            "prospect_id": prospect_id,
            "place_id": place_id,
            "status": "failed",
            "enigma_request_id": order_id,
            "error": error[:500],
            "resolved_at": _now(),
        },
        on_conflict="prospect_id",
    ).execute()


async def process_order(db: Any, settings: Settings, order: dict[str, Any]) -> EnigmaOrderReport:
    """Resolve one claimed order end to end. Never raises past recording the failure on the order."""
    report = EnigmaOrderReport(order_id=str(order["id"]))
    prospect_ids = list(order.get("prospect_ids") or [])
    report.requested = len(prospect_ids)

    if not settings.enigma_api_key:
        report.outcome = "failed"
        report.error = "enigma_api_key not set — order cannot be authorized"
        _finish(db, report.order_id, {"status": "failed", "error": report.error,
                                      "requested_count": report.requested})
        return report

    if not prospect_ids:
        report.outcome = "failed"
        report.error = "order has no prospects"
        _finish(db, report.order_id, {"status": "failed", "error": report.error,
                                      "requested_count": 0})
        return report

    if len(prospect_ids) > settings.enigma_max_prospects_per_order:
        report.outcome = "failed"
        report.error = (
            f"selection of {len(prospect_ids)} exceeds enigma_max_prospects_per_order "
            f"{settings.enigma_max_prospects_per_order}"
        )
        _finish(db, report.order_id, {"status": "failed", "error": report.error,
                                      "requested_count": report.requested})
        return report

    prospects = _load_prospects(db, prospect_ids)
    skip = _already_resolved(db, prospect_ids)
    report.skipped = sum(1 for pid in prospect_ids if pid in skip)

    to_match = [
        prospects[pid]
        for pid in prospect_ids
        if pid not in skip and pid in prospects and prospects[pid].get("place_id")
    ]
    report.billable = len(to_match)

    if not to_match:
        report.outcome = "done"
        _finish(db, report.order_id, {
            "status": "done", "requested_count": report.requested,
            "skipped_count": report.skipped, "resolved_count": 0, "owner_count": 0,
            "contact_count": 0, "failed_count": 0, "error": None,
        })
        return report

    estimate = report.billable * settings.enigma_cost_per_prospect_cents
    denial = budget_denial(estimate, settings.max_market_run_cost_cents)
    if denial:
        report.outcome = "failed"
        report.error = denial
        _finish(db, report.order_id, {"status": "failed", "error": denial,
                                      "requested_count": report.requested,
                                      "skipped_count": report.skipped})
        return report

    by_id = {p["id"]: p for p in to_match}
    results, errors = await enigma_client.match_prospects(settings, to_match)

    for pid, raw in results:
        prospect = by_id.get(pid)
        if not prospect:
            continue
        row = enigma_enrich.build_enigma_row(
            prospect, raw, min_match_score=settings.enigma_min_match_score,
            place_id=prospect["place_id"],
        )
        _store_row(db, row, order_id=report.order_id)
        if row["status"] in ("resolved", "no_contacts"):
            report.resolved += 1
        if row.get("owner_name"):
            report.owners += 1
        if row.get("owner_email") or row.get("owner_phone"):
            report.contacts += 1

    for pid in error_prospect_ids(errors):
        prospect = by_id.get(pid)
        if not prospect:
            continue
        _mark_failed(db, prospect_id=pid, place_id=prospect["place_id"],
                     order_id=report.order_id, error=_first_error(errors, pid))
        report.failed += 1
    report.problems.extend(errors)

    market_id = next((p.get("market_id") for p in to_match if p.get("market_id")), None)
    try:
        db.table("cost_ledger").insert(
            cost.build_ledger_row(
                market_id=market_id, cycle_number=None, stage=STAGE_ENIGMA,
                provider=cost.PROVIDER_ENIGMA, units=report.billable,
                cost_cents=report.billable * settings.enigma_cost_per_prospect_cents,
            )
        ).execute()
    except Exception as exc:  # noqa: BLE001 — a ledger hiccup must not lose the resolution
        logger.warning("enigma cost_ledger write failed", extra={"error": str(exc)[:200]})

    report.outcome = "done"
    _finish(db, report.order_id, {
        "status": "done", "requested_count": report.requested, "skipped_count": report.skipped,
        "resolved_count": report.resolved, "owner_count": report.owners,
        "contact_count": report.contacts, "failed_count": report.failed, "error": None,
    })
    logger.info("enigma order executed", extra={
        "order_id": report.order_id, "billable": report.billable, "resolved": report.resolved,
        "owners": report.owners, "contacts": report.contacts, "failed": report.failed,
    })
    return report


def _first_error(errors: list[str], prospect_id: str) -> str:
    for err in errors:
        if err.split(":", 1)[0].strip() == prospect_id:
            return err
    return "enigma match failed"


async def drain(db: Any, settings: Settings, *, max_orders: int | None = None) -> EnigmaDrainReport:
    """Claim and process up to `max_orders` pending orders (default `enigma_orders_per_tick`). A
    no-op when the key is unset — the caller gates on it, and this is a second backstop."""
    report = EnigmaDrainReport()
    if not settings.enigma_api_key:
        return report
    limit = max_orders if max_orders is not None else settings.enigma_orders_per_tick
    while report.orders_processed < max(0, limit):
        order = claim_next_order(db)
        if order is None:
            break
        report.orders.append(await process_order(db, settings, order))
        report.orders_processed += 1
    return report
