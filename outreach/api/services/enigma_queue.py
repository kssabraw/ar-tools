"""The Enigma card-revenue drain: a signed order becomes a PAID per-prospect card-transaction lookup.

Sibling to `name_search_queue` — this BILLS (one Enigma `search` call per prospect), so it keeps the
full paid-order discipline: a signed `enigma_request` (the spend confirmation), a budget backstop
before the money, a `cost_ledger` write, idempotent skip so a re-order is a cheap resume, a per-tick
prospect budget + a stuck-order reaper (I-118/I-119), and per-prospect isolation so one lookup's
failure never discards the answers the others were charged for.

What DIFFERS from `name_search`:
  * **The provider call returns one result per prospect, not a (records, errors) split.**
    `enigma_graphql.lookup_many` runs the synchronous `search` per business (bounded concurrency,
    every lookup wrapped so it never raises) and returns a `GraphqlLookup` per prospect carrying the
    matched entity (or a recorded call error). So there is no error-string parsing here — each result
    is self-describing.
  * **It stores CARD data, not contacts.** The matched entity's 1m/3m/12m `card_revenue_amount`
    windows land in `prospect_enigma` (migration 20260828120000). The untouched entity is kept in
    `raw`, so any owner/firmographic fields on the same already-billed call are recoverable later
    without a re-bill (the prospect_enrichment.raw discipline) — the deferred contacts rung's raw
    material, captured for free.

Durable per-prospect answers — never re-billed — are `matched` / `no_card` / `no_match` (all real,
billed answers). `failed` (the call errored) is retryable, exactly like the contact rungs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings
from . import cost, enigma_graphql
from .scan_queue import budget_denial

logger = logging.getLogger(__name__)

_TABLE = "enigma_request"
_MARKER = "prospect_enigma"
PROVIDER_ENIGMA = "enigma"
STAGE_ENIGMA = "a7_enigma"

# Durable per-prospect answers — never re-looked-up (never re-billed). `failed` is retryable.
_DURABLE = ("matched", "no_card", "no_match")


@dataclass
class EnigmaOrderReport:
    """What draining one order did — the log-line copy; the durable copy is the order row."""

    order_id: str = ""
    outcome: str = "idle"       # idle | done | partial | failed
    requested: int = 0
    skipped: int = 0
    matched: int = 0            # entity matched (status matched or no_card)
    card: int = 0              # of matched, carrying >=1 card window
    no_match: int = 0
    failed: int = 0
    billable: int = 0
    error: str = ""
    problems: list[str] = field(default_factory=list)


@dataclass
class EnigmaDrainReport:
    """What one tick's whole Enigma drain did."""

    orders_processed: int = 0
    orders: list[EnigmaOrderReport] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def claim_next_order(db: Any) -> dict[str, Any] | None:
    """The oldest pending order, claimed. Read-then-conditionally-claim: the update re-checks
    `status='pending'`, so a row claimed between read and write comes back empty and this tick takes
    nothing (losing a race costs a tick; winning it twice costs a paid lookup)."""
    rows = (
        db.table(_TABLE).select("*").eq("status", "pending")
        .order("created_at", desc=False).limit(1).execute().data or []
    )
    if not rows:
        return None
    order = rows[0]
    claimed = (
        db.table(_TABLE).update({"status": "running", "started_at": _now()})
        .eq("id", order["id"]).eq("status", "pending").execute().data or []
    )
    return dict(order, status="running") if claimed else None


def _finish(db: Any, order_id: str, fields: dict[str, Any]) -> None:
    db.table(_TABLE).update(dict(fields, finished_at=_now())).eq("id", order_id).execute()


def _load_prospects(db: Any, prospect_ids: list[str]) -> dict[str, dict[str, Any]]:
    """{prospect_id: {id, place_id, market_id, name, address, website}} — the identifiers the Enigma
    match sends + the market for the ledger. Chunked under the 1000-row PostgREST cap."""
    out: dict[str, dict[str, Any]] = {}
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            db.table("prospect")
            .select("id, place_id, market_id, name, address, website")
            .in_("id", chunk).execute().data or []
        ):
            out[row["id"]] = row
    return out


def _already_fetched(db: Any, prospect_ids: list[str]) -> set[str]:
    """Prospects whose Enigma answer is already durable (matched|no_card|no_match) — skipped, never
    re-billed. `failed` is deliberately absent: a failed call is retryable."""
    done: set[str] = set()
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            db.table(_MARKER).select("prospect_id, status")
            .in_("prospect_id", chunk).in_("status", list(_DURABLE)).execute().data or []
        ):
            done.add(row["prospect_id"])
    return done


def _order_marker_tally(db: Any, order_id: str, prospect_ids: list[str]) -> dict[str, int]:
    """This order's CUMULATIVE progress across ticks, read from the markers IT wrote (so a multi-tick
    resume reports the whole order, not just the last batch). Only markers carrying THIS
    `enigma_request_id` are counted — a durable marker left by a PRIOR order is a skip, not this
    order's work. Chunked under the 1000-row cap; pure over the DB read."""
    matched = card = no_match = failed = 0
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            db.table(_MARKER)
            .select("prospect_id, status, enigma_request_id")
            .in_("prospect_id", chunk).execute().data or []
        ):
            if str(row.get("enigma_request_id")) != str(order_id):
                continue
            status = row.get("status")
            if status == "matched":
                matched += 1
                card += 1
            elif status == "no_card":
                matched += 1
            elif status == "no_match":
                no_match += 1
            elif status == "failed":
                failed += 1
    # `attempted` = every prospect this order produced a durable-or-failed answer for.
    return {"matched": matched, "card": card, "no_match": no_match, "failed": failed,
            "attempted": matched + no_match + failed}


def _write_order_progress(
    db: Any, order_id: str, *, status: str, requested: int, missing: int, tally: dict[str, int],
) -> None:
    """Persist an order's CUMULATIVE counters (from the marker tally) + its status. `done` stamps
    finished_at; `pending` (a partial left to resume) does not. `skipped` = requested prospects this
    order neither attempted nor found unmatchable — i.e. durable from a PRIOR order."""
    fields: dict[str, Any] = {
        "status": status,
        "requested_count": requested,
        "skipped_count": max(0, requested - tally["attempted"] - missing),
        "matched_count": tally["matched"],
        "card_count": tally["card"],
        "no_match_count": tally["no_match"],
        "failed_count": tally["failed"],
        "error": None,
    }
    if status == "done":
        fields["finished_at"] = _now()
    db.table(_TABLE).update(fields).eq("id", order_id).execute()


def recover_stuck_orders(db: Any, settings: Settings) -> int:
    """Reset `running` orders older than `enigma_stuck_order_minutes` back to `pending` so a later
    tick resumes them (I-118 recovery half). A normal tick holds an order `running` only for the tens
    of seconds it looks up one budget's worth, so a much-older `running` is a container that died
    mid-tick. The idempotent skip means the resume re-bills only the un-done prospects. Returns the
    number recovered."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=settings.enigma_stuck_order_minutes)
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
            logger.warning("recovered stuck enigma order", extra={"order_id": row["id"]})
    return recovered


def _store_result(
    db: Any,
    *,
    prospect_id: str,
    place_id: str | None,
    status: str,
    entity: dict[str, Any] | None,
    entity_type: str,
    order_id: str,
) -> dict[str, Any]:
    """Upsert one prospect's Enigma marker (card windows + match audit + raw). Idempotent on
    prospect_id, so a re-order (or a resumed tick) replaces the row rather than duplicating it.
    Returns the card windows written (for the report). Never raises past the caller's handling."""
    card = enigma_graphql.extract_card_windows(entity) if entity is not None else None
    row = {
        "prospect_id": prospect_id,
        "place_id": place_id,
        "status": status,
        "matched": entity is not None,
        "matched_name": enigma_graphql.extract_matched_name(entity) if entity is not None else None,
        "card_revenue_1m": (card or {}).get("1m"),
        "card_revenue_3m": (card or {}).get("3m"),
        "card_revenue_12m": (card or {}).get("12m"),
        "card_as_of": enigma_graphql.extract_card_as_of(entity) if entity is not None else None,
        "entity_type": entity_type,
        "enigma_request_id": order_id,
        "error": None,
        # Keep the untouched matched entity for a later re-parse (owner/firmographic fields on the
        # same billed call) — null on no_match.
        "raw": entity if entity is not None else None,
        "fetched_at": _now(),
    }
    db.table(_MARKER).upsert(row, on_conflict="prospect_id").execute()
    return card or {}


def _mark_failed(db: Any, *, prospect_id: str, place_id: str | None, entity_type: str,
                 order_id: str, error: str) -> None:
    """Record a per-prospect lookup failure (retryable) without a card answer."""
    db.table(_MARKER).upsert(
        {
            "prospect_id": prospect_id,
            "place_id": place_id,
            "status": "failed",
            "matched": False,
            "entity_type": entity_type,
            "enigma_request_id": order_id,
            "error": error[:500],
            "fetched_at": _now(),
        },
        on_conflict="prospect_id",
    ).execute()


async def process_order(
    db: Any, settings: Settings, order: dict[str, Any], *, max_places: int
) -> tuple[EnigmaOrderReport, int, bool]:
    """Look up card revenue for up to `max_places` of one claimed order's due prospects. Never raises
    past recording the failure on the order.

    Returns `(report, billed_this_call, finished)`. When the order's due set exceeds `max_places`,
    only that many are looked up this call and the order is left PENDING (finished False) — the
    marker-based idempotent skip means the next tick's resume re-bills only the rest. The order's
    persisted counters are the CUMULATIVE marker tally, so a resumed order still reports its whole
    self (I-118)."""
    report = EnigmaOrderReport(order_id=str(order["id"]))
    prospect_ids = list(order.get("prospect_ids") or [])
    report.requested = len(prospect_ids)
    entity_type = str(order.get("entity_type") or settings.enigma_entity_type)

    if not prospect_ids:
        report.outcome = "failed"
        report.error = "order has no prospects"
        _finish(db, report.order_id, {"status": "failed", "error": report.error, "requested_count": 0})
        return report, 0, True

    if len(prospect_ids) > settings.enigma_max_places_per_order:
        report.outcome = "failed"
        report.error = (
            f"selection of {len(prospect_ids)} exceeds enigma_max_places_per_order "
            f"{settings.enigma_max_places_per_order}"
        )
        _finish(db, report.order_id, {"status": "failed", "error": report.error,
                                      "requested_count": report.requested})
        return report, 0, True

    prospects = _load_prospects(db, prospect_ids)
    skip = _already_fetched(db, prospect_ids)
    report.skipped = sum(1 for pid in prospect_ids if pid in skip)
    # A prospect needs a NAME (the Enigma match anchor). Neither skipped nor matchable → not an error,
    # not skipped, just not billable; counted so the order's skipped math reconciles. (place_id is NOT
    # required — Enigma matches on name+address, unlike the contact rungs.)
    missing = sum(
        1 for pid in prospect_ids
        if pid not in skip and (pid not in prospects or not (prospects[pid].get("name") or "").strip())
    )

    to_fetch = [
        prospects[pid] for pid in prospect_ids
        if pid not in skip and pid in prospects and (prospects[pid].get("name") or "").strip()
    ]

    if not to_fetch:
        # Everything was already fetched (or unmatchable) — a legitimate no-op, not a failure.
        report.outcome = "done"
        tally = _order_marker_tally(db, report.order_id, prospect_ids)
        _write_order_progress(db, report.order_id, status="done", requested=report.requested,
                              missing=missing, tally=tally)
        return report, 0, True

    # Budget: look up at most `max_places` this call; leave the rest to resume next tick (I-118).
    cap = max(1, max_places)
    batch = to_fetch[:cap]
    finished = len(to_fetch) <= cap
    # Dedupe by prospect id BEFORE anything bills: an order's uuid[] carries no uniqueness, so a
    # duplicated prospect would otherwise fire the paid `search` twice for one business (the sibling
    # drains dedupe the same way via their by_place/by_id keys). Billing, the budget estimate, the
    # returned spend and the provider call all count DISTINCT prospects.
    by_id = {p["id"]: p for p in batch}
    report.billable = len(by_id)

    # Budget backstop before the money (a placement guard may run too; this catches a runaway) — over
    # THIS call's distinct batch, since that is all that bills now.
    estimate = report.billable * settings.enigma_cost_per_lookup_cents
    denial = budget_denial(estimate, settings.max_market_run_cost_cents)
    if denial:
        report.outcome = "failed"
        report.error = denial
        _finish(db, report.order_id, {"status": "failed", "error": denial,
                                      "requested_count": report.requested,
                                      "skipped_count": report.skipped})
        return report, 0, True

    # One bounded-concurrency pass over the DISTINCT batch. lookup_many wraps every prospect so it never
    # raises; the outer try/except is the belt-and-braces that marks the whole batch retryable if it
    # somehow does (a resume then re-bills only these, none of the durable ones).
    biz_batch = [
        {"id": p["id"], "name": p.get("name"), "street": p.get("address"),
         "website": p.get("website"), "place_id": p.get("place_id"),
         "market_id": p.get("market_id")}
        for p in by_id.values()
    ]
    try:
        results = await enigma_graphql.lookup_many(
            settings, biz_batch, entity_type=entity_type,
            concurrency=max(1, settings.enigma_chunk_size),
        )
    except Exception as exc:  # noqa: BLE001 — the order must resolve; mark the batch retryable
        logger.error("enigma lookup batch failed", extra={"order_id": report.order_id})
        for pid, p in by_id.items():
            _mark_failed(db, prospect_id=pid, place_id=p.get("place_id"), entity_type=entity_type,
                         order_id=report.order_id, error=repr(exc))
            report.failed += 1
        report.problems.append(f"batch: {repr(exc)[:200]}")
        results = []

    for lk in results:
        pid = getattr(lk, "prospect_id", "")
        p = by_id.get(pid)
        if p is None:
            continue
        call = getattr(lk, "call", None)
        if call is None or not getattr(call, "ok", False):
            err = (getattr(call, "error", "") or getattr(call, "body_text", "") or "lookup failed")
            _mark_failed(db, prospect_id=pid, place_id=p.get("place_id"), entity_type=entity_type,
                         order_id=report.order_id, error=str(err))
            report.failed += 1
            continue
        entity = getattr(lk, "brand", None)
        if entity is None:
            _store_result(db, prospect_id=pid, place_id=p.get("place_id"), status="no_match",
                          entity=None, entity_type=entity_type, order_id=report.order_id)
            report.no_match += 1
            continue
        card = enigma_graphql.extract_card_windows(entity)
        status = "matched" if card else "no_card"
        _store_result(db, prospect_id=pid, place_id=p.get("place_id"), status=status,
                      entity=entity, entity_type=entity_type, order_id=report.order_id)
        report.matched += 1
        if card:
            report.card += 1

    # cost_ledger: units = prospects we sent to the provider THIS call (only the batch bills now; a
    # multi-tick order writes one ledger row per tick). market_id from any billed prospect; rate
    # reconciled manually against the Enigma bill (I-022).
    market_id = next((p.get("market_id") for p in by_id.values() if p.get("market_id")), None)
    try:
        db.table("cost_ledger").insert(
            cost.build_ledger_row(
                market_id=market_id, cycle_number=None, stage=STAGE_ENIGMA,
                provider=PROVIDER_ENIGMA, units=report.billable,
                cost_cents=report.billable * settings.enigma_cost_per_lookup_cents,
            )
        ).execute()
    except Exception as exc:  # noqa: BLE001 — a ledger hiccup must not lose the lookup
        logger.warning("enigma cost_ledger write failed", extra={"error": str(exc)[:200]})

    tally = _order_marker_tally(db, report.order_id, prospect_ids)
    _write_order_progress(
        db, report.order_id, status="done" if finished else "pending",
        requested=report.requested, missing=missing, tally=tally,
    )
    report.outcome = "done" if finished else "partial"
    logger.info("enigma order %s", "executed" if finished else "partial (resuming next tick)",
                extra={"order_id": report.order_id, "billed_this_call": report.billable,
                       "matched_total": tally["matched"], "card_total": tally["card"],
                       "failed_total": tally["failed"], "finished": finished})
    return report, report.billable, finished


async def drain(
    db: Any, settings: Settings, *, max_orders: int | None = None, max_places: int | None = None,
) -> EnigmaDrainReport:
    """Claim and process pending orders, up to `max_orders` (default `enigma_orders_per_tick`) and a
    per-tick PROSPECT budget `max_places` (default `enigma_per_tick`; <=0 = no cap). The budget bounds
    the tick's wall-time so a large order can't overrun Railway's cron window: an order larger than the
    remaining budget is looked up to it and left PENDING to resume next tick (a partial ⟹ the budget is
    spent, so the loop stops). Stranded `running` orders are recovered first (I-118). PAID — but
    order-gated (the signed order is the confirmation), so no env token."""
    report = EnigmaDrainReport()
    try:
        recover_stuck_orders(db, settings)
    except Exception as exc:  # noqa: BLE001 — recovery is best-effort; never block the drain
        logger.warning("enigma stuck-order recovery failed", extra={"error": str(exc)[:200]})

    order_limit = max_orders if max_orders is not None else settings.enigma_orders_per_tick
    per_tick = max_places if max_places is not None else settings.enigma_per_tick
    budget = per_tick if per_tick > 0 else 10**9  # <=0 → effectively no cap
    while report.orders_processed < max(0, order_limit) and budget > 0:
        order = claim_next_order(db)
        if order is None:
            break
        rep, billed, finished = await process_order(db, settings, order, max_places=budget)
        report.orders.append(rep)
        report.orders_processed += 1
        budget -= billed
        if not finished:
            break  # a partial means the budget is exhausted; the order resumes next tick
    return report
