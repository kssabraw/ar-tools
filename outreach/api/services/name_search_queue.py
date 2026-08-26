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
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from . import cost, name_search
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


def _contact_rows(result: name_search.NameSearchResult, place_id: str) -> list[dict[str, Any]]:
    """`prospect_contact` insert rows for a search result. `source='web_search'`; the citation +
    model ride in `raw` so a caller can verify the low-trust name against its source."""
    rows: list[dict[str, Any]] = []
    for idx, name in enumerate(result.names):
        rows.append(
            {
                "prospect_id": result.prospect_id,
                "place_id": place_id,
                "contact_index": idx,
                "source": CONTACT_SOURCE,
                "raw": {
                    "source_kind": "web_search",
                    "citation": name.citation,
                    "evidence": name.evidence,
                    "model": result.model,
                },
                **name.as_contact(),
            }
        )
    return rows


def _store_result(db: Any, result: name_search.NameSearchResult, place_id: str, order_id: str) -> int:
    """Persist one search result. Replaces THIS prospect's web_search contacts (never the Outscraper
    or site-scrape ones) and upserts the marker. Contacts first, then the marker."""
    rows = _contact_rows(result, place_id)
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


async def process_order(db: Any, settings: Settings, order: dict[str, Any]) -> NameSearchOrderReport:
    """Search one claimed order end to end. Never raises past recording the failure on the order."""
    report = NameSearchOrderReport(order_id=str(order["id"]))
    prospect_ids = list(order.get("prospect_ids") or [])
    report.requested = len(prospect_ids)

    if not prospect_ids:
        report.outcome = "failed"
        report.error = "order has no prospects"
        _finish(db, report.order_id, {"status": "failed", "error": report.error, "requested_count": 0})
        return report

    if len(prospect_ids) > settings.name_search_max_places_per_order:
        report.outcome = "failed"
        report.error = (
            f"selection of {len(prospect_ids)} exceeds name_search_max_places_per_order "
            f"{settings.name_search_max_places_per_order}"
        )
        _finish(db, report.order_id, {"status": "failed", "error": report.error,
                                      "requested_count": report.requested})
        return report

    prospects = _load_prospects(db, prospect_ids)
    skip = _already_searched(db, prospect_ids)
    report.skipped = sum(1 for pid in prospect_ids if pid in skip)

    # A prospect needs a place_id (the contact row's NOT-NULL join key); a website is preferred for
    # grounding but not required (the search can anchor on name + address).
    to_search = [
        prospects[pid] for pid in prospect_ids
        if pid not in skip and pid in prospects and prospects[pid].get("place_id")
    ]
    report.billable = len(to_search)

    if not to_search:
        report.outcome = "done"
        _finish(db, report.order_id,
                {"status": "done", "requested_count": report.requested,
                 "skipped_count": report.skipped, "searched_count": 0, "found_count": 0,
                 "name_count": 0, "failed_count": 0, "error": None})
        return report

    # Budget backstop before the money (the placement guard already ran; this catches a runaway).
    estimate = report.billable * settings.name_search_cost_cents
    denial = budget_denial(estimate, settings.max_market_run_cost_cents)
    if denial:
        report.outcome = "failed"
        report.error = denial
        _finish(db, report.order_id, {"status": "failed", "error": denial,
                                      "requested_count": report.requested,
                                      "skipped_count": report.skipped})
        return report

    by_id = {p["id"]: p for p in to_search}
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
            written = _store_result(db, result, by_id[pid]["place_id"], report.order_id)
            report.searched += 1
            report.names += written
            if result.status == "found":
                report.found += 1
        report.problems.extend(errors)

    # cost_ledger: units = prospects we sent to the provider (billable). market_id from any billed
    # prospect; rate reconciled manually against the OpenAI dashboard (I-022).
    market_id = next((p.get("market_id") for p in to_search if p.get("market_id")), None)
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

    report.outcome = "done"
    _finish(db, report.order_id,
            {"status": "done", "requested_count": report.requested,
             "skipped_count": report.skipped, "searched_count": report.searched,
             "found_count": report.found, "name_count": report.names,
             "failed_count": report.failed, "error": None})
    logger.info("name search order executed",
                extra={"order_id": report.order_id, "billable": report.billable,
                       "searched": report.searched, "found": report.found, "failed": report.failed})
    return report


def _first_error(errors: list[str], prospect_id: str) -> str:
    for err in errors:
        if err.split(":", 1)[0].strip() == prospect_id:
            return err
    return "name search failed"


async def drain(db: Any, settings: Settings, *, max_orders: int | None = None) -> NameSearchDrainReport:
    """Claim and process up to `max_orders` pending orders (default `name_search_orders_per_tick`).
    PAID — but order-gated (the signed order is the confirmation), so no env token, like enrich."""
    report = NameSearchDrainReport()
    limit = max_orders if max_orders is not None else settings.name_search_orders_per_tick
    while report.orders_processed < max(0, limit):
        order = claim_next_order(db)
        if order is None:
            break
        report.orders.append(await process_order(db, settings, order))
        report.orders_processed += 1
    return report
