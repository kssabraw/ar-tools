"""The name-search-order drain: a UI request becomes a PAID web search for owner/manager names.

Sibling to `enrich_queue` — this BILLS (one OpenAI web-search call per prospect), so it keeps the
full paid-order discipline: a signed `name_search_request` (the spend confirmation), a budget
backstop before the money, a `cost_ledger` write, idempotent skip so a re-order is a cheap resume,
and per-prospect isolation so one failure never discards the records the others were charged for.

Distinct from `name_scrape_queue` (FREE) in exactly the cost-bearing parts; identical in the parts
about correctness (conditional claim, measured markers, replace-on-place scoped to THIS producer's
`source='web_search'` contacts so enrichment/site-scrape contacts are never touched).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings
from . import cost, name_confidence, name_search
from .scan_queue import budget_denial

logger = logging.getLogger(__name__)

_TABLE = "name_search_request"
_MARKER = "prospect_name_search"
_CONTACT = "prospect_contact"
CONTACT_SOURCE = "web_search"
PROVIDER_OPENAI = "openai"
STAGE_SEARCH = "a6_name_search"

# Durable per-prospect answers — never re-searched (never re-billed). `failed` is retryable.
_DURABLE = ("found", "no_names")


@dataclass
class NameSearchOrderReport:
    order_id: str = ""
    outcome: str = "idle"       # idle | done | failed
    requested: int = 0
    skipped: int = 0
    searched: int = 0
    found: int = 0
    names: int = 0
    failed: int = 0
    billable: int = 0
    error: str = ""
    problems: list[str] = field(default_factory=list)


@dataclass
class NameSearchDrainReport:
    orders_processed: int = 0
    orders: list[NameSearchOrderReport] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def error_prospect_ids(errors: list[str]) -> set[str]:
    """The prospect_ids that failed, parsed from `search_names` error strings (`"<id>: msg"`). Pure."""
    out: set[str] = set()
    for err in errors:
        head = err.split(":", 1)[0].strip()
        if head:
            out.add(head)
    return out


def claim_next_order(db: Any) -> dict[str, Any] | None:
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
    """{prospect_id: {id, place_id, market_id, name, address, category, website}} — the fields the
    search prompt is grounded on + the contact join key. Chunked under the 1000-row cap."""
    out: dict[str, dict[str, Any]] = {}
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            db.table("prospect")
            .select("id, place_id, market_id, name, address, category, website")
            .in_("id", chunk).execute().data or []
        ):
            out[row["id"]] = row
    return out


def _already_searched(db: Any, prospect_ids: list[str]) -> set[str]:
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
    `name_search_request_id` are counted — a durable marker left by a PRIOR order is a skip, not this
    order's work. Chunked under the 1000-row cap; pure over the DB read."""
    found = no_names = failed = names = 0
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            db.table(_MARKER)
            .select("prospect_id, status, name_count, name_search_request_id")
            .in_("prospect_id", chunk)
            .execute()
            .data
            or []
        ):
            if str(row.get("name_search_request_id")) != str(order_id):
                continue
            status = row.get("status")
            if status == "found":
                found += 1
                names += int(row.get("name_count") or 0)
            elif status == "no_names":
                no_names += 1
            elif status == "failed":
                failed += 1
    # `searched` = prospects the search actually returned a result for (found + no_names), matching the
    # per-run report; `attempted` includes failures.
    return {"found": found, "no_names": no_names, "failed": failed, "names": names,
            "searched": found + no_names, "attempted": found + no_names + failed}


def _write_order_progress(
    db: Any, order_id: str, *, status: str, requested: int, missing: int, tally: dict[str, int],
) -> None:
    """Persist an order's CUMULATIVE counters (from the marker tally) + its status. `done` stamps
    finished_at; `pending` (a partial left to resume) does not. `skipped` = requested prospects this
    order neither attempted nor found unsearchable — i.e. durable from a PRIOR order."""
    fields: dict[str, Any] = {
        "status": status,
        "requested_count": requested,
        "skipped_count": max(0, requested - tally["attempted"] - missing),
        "searched_count": tally["searched"],
        "found_count": tally["found"],
        "name_count": tally["names"],
        "failed_count": tally["failed"],
        "error": None,
    }
    if status == "done":
        fields["finished_at"] = _now()
    db.table(_TABLE).update(fields).eq("id", order_id).execute()


def recover_stuck_orders(db: Any, settings: Settings) -> int:
    """Reset `running` orders older than `name_search_stuck_order_minutes` back to `pending` so a later
    tick resumes them (I-118 sibling — this producer had no reaper). A normal tick holds an order
    `running` only for the tens of seconds it searches one budget's worth, so a much-older `running`
    is a container that died mid-tick. The idempotent skip means the resume re-bills only the un-done
    places. Returns the number recovered."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=settings.name_search_stuck_order_minutes)
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
            logger.warning("recovered stuck name-search order", extra={"order_id": row["id"]})
    return recovered


def _contact_rows(
    result: name_search.NameSearchResult, place_id: str, business_website: str | None = None
) -> list[dict[str, Any]]:
    """`prospect_contact` insert rows for a search result. `source='web_search'`; the citation +
    model ride in `raw` so a caller can verify the low-trust name against its source. Confidence is
    BLENDED (deterministic corroboration across the search's citations + the model's self-rating)."""
    rows: list[dict[str, Any]] = []
    for idx, name in enumerate(result.names):
        conf = name_confidence.score_web_search(
            model_confidence=name.model_confidence,
            citations=result.citations,
            business_website=business_website,
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
                    "source_kind": "web_search",
                    "citation": name.citation,
                    "evidence": name.evidence,
                    "model": result.model,
                    "model_confidence": name.model_confidence,
                    "model_reason": name.model_reason,
                    "confidence": conf.factors,
                },
                **name.as_contact(),
            }
        )
    return rows


def _store_result(
    db: Any, result: name_search.NameSearchResult, place_id: str, order_id: str,
    business_website: str | None = None,
) -> int:
    """Persist one search result. Replaces THIS prospect's web_search contacts (never the Outscraper
    or site-scrape ones) and upserts the marker. Contacts first, then the marker."""
    rows = _contact_rows(result, place_id, business_website)
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
            "citations": list(result.citations) or None,
            "model": result.model,
            "name_search_request_id": order_id,
            "error": None,
            "raw": result.raw,
            "searched_at": _now(),
        },
        on_conflict="prospect_id",
    ).execute()
    return len(rows)


def _mark_failed(db: Any, *, prospect_id: str, order_id: str, error: str) -> None:
    db.table(_MARKER).upsert(
        {
            "prospect_id": prospect_id,
            "status": "failed",
            "name_count": 0,
            "name_search_request_id": order_id,
            "error": error[:500],
            "searched_at": _now(),
        },
        on_conflict="prospect_id",
    ).execute()


async def process_order(
    db: Any, settings: Settings, order: dict[str, Any], *, max_places: int
) -> tuple[NameSearchOrderReport, int, bool]:
    """Search up to `max_places` of one claimed order's due prospects. Never raises past recording the
    failure on the order.

    Returns `(report, billed_this_call, finished)`. When the order's due set exceeds `max_places`,
    only that many are searched this call and the order is left PENDING (finished False) — the
    marker-based idempotent skip means the next tick's resume re-bills only the rest. The order's
    persisted counters are the CUMULATIVE marker tally, so a resumed order still reports its whole
    self (I-118 sibling)."""
    report = NameSearchOrderReport(order_id=str(order["id"]))
    prospect_ids = list(order.get("prospect_ids") or [])
    report.requested = len(prospect_ids)

    if not prospect_ids:
        report.outcome = "failed"
        report.error = "order has no prospects"
        _finish(db, report.order_id, {"status": "failed", "error": report.error, "requested_count": 0})
        return report, 0, True

    if len(prospect_ids) > settings.name_search_max_places_per_order:
        report.outcome = "failed"
        report.error = (
            f"selection of {len(prospect_ids)} exceeds name_search_max_places_per_order "
            f"{settings.name_search_max_places_per_order}"
        )
        _finish(db, report.order_id, {"status": "failed", "error": report.error,
                                      "requested_count": report.requested})
        return report, 0, True

    prospects = _load_prospects(db, prospect_ids)
    skip = _already_searched(db, prospect_ids)
    report.skipped = sum(1 for pid in prospect_ids if pid in skip)
    # Prospects that are neither skipped nor searchable (vanished, or no place_id) — not an error, not
    # skipped, just not billable. Counted so the order's skipped math reconciles.
    missing = sum(
        1 for pid in prospect_ids
        if pid not in skip and (pid not in prospects or not prospects[pid].get("place_id"))
    )

    # A prospect needs a place_id (the contact row's NOT-NULL join key); a website is preferred for
    # grounding but not required (the search can anchor on name + address).
    to_search = [
        prospects[pid] for pid in prospect_ids
        if pid not in skip and pid in prospects and prospects[pid].get("place_id")
    ]

    if not to_search:
        report.outcome = "done"
        tally = _order_marker_tally(db, report.order_id, prospect_ids)
        _write_order_progress(db, report.order_id, status="done", requested=report.requested,
                              missing=missing, tally=tally)
        return report, 0, True

    # Budget: search at most `max_places` this call; leave the rest to resume next tick (I-118 sibling).
    cap = max(1, max_places)
    batch = to_search[:cap]
    finished = len(to_search) <= cap
    report.billable = len(batch)

    # Budget backstop before the money (the placement guard already ran; this catches a runaway) —
    # over THIS call's batch, since that is all that bills now.
    estimate = report.billable * settings.name_search_cost_cents
    denial = budget_denial(estimate, settings.max_market_run_cost_cents)
    if denial:
        report.outcome = "failed"
        report.error = denial
        _finish(db, report.order_id, {"status": "failed", "error": denial,
                                      "requested_count": report.requested,
                                      "skipped_count": report.skipped})
        return report, 0, True

    by_id = {p["id"]: p for p in batch}
    ids = list(by_id.keys())
    chunk_size = max(1, settings.name_search_chunk_size)
    for start in range(0, len(ids), chunk_size):
        chunk = [by_id[i] for i in ids[start : start + chunk_size]]
        chunk_ids = [p["id"] for p in chunk]
        try:
            results, errors = await name_search.search_names(settings, chunk)
        except Exception as exc:  # noqa: BLE001 — the order must resolve; mark the chunk retryable
            logger.error("name search chunk failed", extra={"order_id": report.order_id})
            for pid in chunk_ids:
                _mark_failed(db, prospect_id=pid, order_id=report.order_id, error=repr(exc))
                report.failed += 1
            report.problems.append(f"chunk @ {start}: {repr(exc)[:200]}")
            continue

        by_result = {r.prospect_id: r for r in results}
        failed_ids = error_prospect_ids(errors) & set(chunk_ids)
        for pid in chunk_ids:
            result = by_result.get(pid)
            if result is None:
                _mark_failed(db, prospect_id=pid, order_id=report.order_id,
                             error=_first_error(errors, pid) if pid in failed_ids else "no result")
                report.failed += 1
                continue
            written = _store_result(db, result, by_id[pid]["place_id"], report.order_id,
                                    by_id[pid].get("website"))
            report.searched += 1
            report.names += written
            if result.status == "found":
                report.found += 1
        report.problems.extend(errors)

    # cost_ledger: units = prospects we sent to the provider THIS call (only the batch bills now; a
    # multi-tick order writes one ledger row per tick). market_id from any billed prospect; rate
    # reconciled manually against the OpenAI dashboard (I-022).
    market_id = next((p.get("market_id") for p in batch if p.get("market_id")), None)
    try:
        db.table("cost_ledger").insert(
            cost.build_ledger_row(
                market_id=market_id, cycle_number=None, stage=STAGE_SEARCH,
                provider=PROVIDER_OPENAI, units=report.billable,
                cost_cents=report.billable * settings.name_search_cost_cents,
            )
        ).execute()
    except Exception as exc:  # noqa: BLE001 — a ledger hiccup must not lose the search
        logger.warning("name search cost_ledger write failed", extra={"error": str(exc)[:200]})

    tally = _order_marker_tally(db, report.order_id, prospect_ids)
    _write_order_progress(
        db, report.order_id, status="done" if finished else "pending",
        requested=report.requested, missing=missing, tally=tally,
    )
    report.outcome = "done" if finished else "partial"
    logger.info("name search order %s", "executed" if finished else "partial (resuming next tick)",
                extra={"order_id": report.order_id, "billed_this_call": report.billable,
                       "searched_total": tally["searched"], "found_total": tally["found"],
                       "failed_total": tally["failed"], "finished": finished})
    return report, len(batch), finished


def _first_error(errors: list[str], prospect_id: str) -> str:
    for err in errors:
        if err.split(":", 1)[0].strip() == prospect_id:
            return err
    return "name search failed"


async def drain(
    db: Any, settings: Settings, *, max_orders: int | None = None, max_places: int | None = None,
) -> NameSearchDrainReport:
    """Claim and process pending orders, up to `max_orders` (default `name_search_orders_per_tick`)
    and a per-tick PLACE budget `max_places` (default `name_search_per_tick`; <=0 = no cap). The place
    budget bounds the tick's wall-time so a large order can't overrun Railway's cron window: an order
    larger than the remaining budget is searched up to it and left PENDING to resume next tick (a
    partial ⟹ the budget is spent, so the loop stops). Stranded `running` orders are recovered first
    (I-118 sibling). PAID — but order-gated (the signed order is the confirmation), so no env token."""
    report = NameSearchDrainReport()
    try:
        recover_stuck_orders(db, settings)
    except Exception as exc:  # noqa: BLE001 — recovery is best-effort; never block the drain
        logger.warning("name-search stuck-order recovery failed", extra={"error": str(exc)[:200]})

    order_limit = max_orders if max_orders is not None else settings.name_search_orders_per_tick
    per_tick = max_places if max_places is not None else settings.name_search_per_tick
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
