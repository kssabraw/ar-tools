"""Organic-SERP capture — the second competitive signal, alongside the Maps geogrid.

One Google organic SERP for a snapshot's keyword + location, stored in `serp_result`. This is the
report's "organic ranking for that keyword vs the top competitors" section (outreach ISSUES I-095,
increment 2). It attaches to the maps `scan_snapshot` for that submarket×keyword (I-084 resolved in
DECISIONS 2026-08-08 — the natural join key), so the per-prospect report reads it off the same
snapshot its coverage came from.

Unlike the maps grid (81 queued tasks), organic is ONE call per snapshot, so it uses the live
endpoint — immediate, one billed request. It BILLS: gated behind the spend token like every other
paid command, and it writes a `cost_ledger` row (stage `b2_organic`).

**Endpoint shape is MEASURED on the first real run, not asserted** — the discipline
`dataforseo_client.py` exists to enforce (a previous author asserted an endpoint from another repo
and shipped a silent 404). `ORGANIC_LIVE_PATH` is the standard DataForSEO organic endpoint and is
added to that module's free probe set, but the first `capture_organic` logs one full response so an
unexpected envelope is recoverable from the log rather than needing a second paid run, and
`parse_organic_serp` is tolerant of the envelope and RAISES on a task-level error rather than
returning an empty SERP (an outage must never read as "nobody ranks").
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import Settings
from .scan_runner import BASE_URL, _auth_header, month_of

logger = logging.getLogger(__name__)

# The standard DataForSEO organic SERP endpoint. Measured on first run (see module docstring); the
# maps LIVE twin (/v3/serp/google/maps/live/advanced) is already probe-confirmed 200 on this
# account, so the same-family organic path is very likely live — but "very likely" is exactly what
# the 404 lesson warns against, so it is probed free before the first paid call.
ORGANIC_LIVE_PATH = "/v3/serp/google/organic/live/advanced"

# The engine label on the serp_result row. `serp_result.engine` is free text; this is the value the
# report read filters on, so it is a shared contract — do not change it without the reader.
ENGINE = "google_organic"

_TASK_STATUS_OK = 20000

# SERP item types that count as a ranking organic result. `ai_overview` and the other enrichments
# are detected separately (they are signals, not competitors in the organic list).
_ORGANIC_TYPES = frozenset({"organic"})
_AI_OVERVIEW_TYPES = frozenset({"ai_overview"})


class OrganicScanError(RuntimeError):
    """A failure capturing or parsing an organic SERP, including task-level errors inside a 200."""


@dataclass(frozen=True)
class OrganicResult:
    rank: int
    domain: str
    url: str | None
    title: str | None


@dataclass(frozen=True)
class OrganicSerp:
    results: list[OrganicResult]
    ai_overview_present: bool
    total_count: int


@dataclass
class OrganicCaptureReport:
    snapshot_id: str = ""
    keyword: str = ""
    stored: bool = False
    already_captured: bool = False
    results: int = 0
    ai_overview_present: bool = False
    problems: list[str] = field(default_factory=list)


# --- pure: request + parse --------------------------------------------------------------------


def build_organic_task(
    keyword: str,
    lat: float,
    lng: float,
    *,
    depth: int,
    language_code: str,
    device: str,
) -> dict[str, Any]:
    """The DataForSEO organic live/advanced request body for one keyword at one location. Pure.

    `location_coordinate` anchors the SERP to the submarket centre — the same coordinate the maps
    grid is built around — so the organic read is of the SAME place the coverage is, not a
    country-wide ranking that would misrepresent a local business.
    """
    return {
        "keyword": keyword,
        "location_coordinate": f"{lat},{lng}",
        "language_code": language_code,
        "device": device,
        "depth": depth,
    }


def domain_of(url: str | None) -> str | None:
    """A bare, lower-cased registrable-ish domain from a URL or host, `www.` stripped. Pure.

    Deliberately simple (no public-suffix list): the report compares a prospect's stored website
    host against the SERP's `domain` field, and DataForSEO already returns `domain` as a bare host,
    so this only needs to normalise the two the same way. Never raises — a junk value returns None
    and simply won't match, which is the safe direction (no false "you rank" claim)."""
    if not url:
        return None
    text = url.strip().lower()
    if not text:
        return None
    if "//" not in text:
        text = "//" + text
    host = urlparse(text).netloc or ""
    host = host.split("@")[-1].split(":")[0]  # drop any userinfo / port
    if host.startswith("www."):
        host = host[4:]
    return host or None


def parse_organic_serp(body: dict[str, Any]) -> OrganicSerp:
    """Read one organic live/advanced response into ranked results + the AI-overview flag. Pure.

    RAISES `OrganicScanError` on a task-level error (status_code != 20000), mirroring
    `parse_my_business_info`: a failed lookup must not be collapsed into an empty SERP, or an outage
    would argue that a prospect's competitors don't exist. Tolerant of the item envelope otherwise —
    a shape assumption that silently holds until it doesn't is how a parser returns nothing.
    """
    tasks = body.get("tasks") or []
    if not tasks:
        raise OrganicScanError("response carried no tasks")
    task = tasks[0] or {}
    status = task.get("status_code")
    if status is not None and status != _TASK_STATUS_OK:
        raise OrganicScanError(
            f"task failed: status_code={status} message={task.get('status_message')!r}"
        )
    result = task.get("result") or []
    if not result:
        raise OrganicScanError("task returned no result block")

    first = result[0] or {}
    items = first.get("items")
    if not isinstance(items, list):
        items = []

    results: list[OrganicResult] = []
    ai_overview = False
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type in _AI_OVERVIEW_TYPES:
            ai_overview = True
            continue
        if item_type not in _ORGANIC_TYPES:
            continue
        domain = str(item.get("domain") or "").lower() or None
        rank = item.get("rank_absolute")
        if rank is None:
            rank = item.get("rank_group")
        if not domain or not isinstance(rank, (int, float)):
            continue
        results.append(
            OrganicResult(
                rank=int(rank),
                domain=domain,
                url=item.get("url"),
                title=item.get("title"),
            )
        )

    results.sort(key=lambda r: r.rank)
    total = first.get("se_results_count")
    return OrganicSerp(
        results=results,
        ai_overview_present=ai_overview,
        total_count=int(total) if isinstance(total, (int, float)) else len(results),
    )


def summarize_serp(serp: OrganicSerp, *, depth: int) -> dict[str, Any]:
    """The `payload_summary` the report reads — the parsed results, JSON-ready. Pure.

    Stored alongside the raw `payload` (storage spec §6): the summary is what every read touches, the
    raw is kept for reproducibility until it migrates to R2.
    """
    return {
        "engine": ENGINE,
        "captured_depth": depth,
        "ai_overview_present": serp.ai_overview_present,
        "total_count": serp.total_count,
        "results": [
            {"rank": r.rank, "domain": r.domain, "url": r.url, "title": r.title}
            for r in serp.results
        ],
    }


# --- I/O: the capture -------------------------------------------------------------------------


async def capture_organic(
    db: Any,
    settings: Settings,
    snapshot: dict[str, Any],
    keyword_term: str,
    *,
    market_id: str | None,
    client: httpx.AsyncClient | None = None,
) -> OrganicCaptureReport:
    """Capture one organic SERP for a snapshot and store it. BILLS one request.

    Idempotent per (snapshot, engine): a snapshot already carrying an organic row is left alone
    (`already_captured`) rather than re-billed, so a re-run is free and safe. The row is written
    AFTER the paid call succeeds; a `cost_ledger` row is written best-effort (a ledger failure must
    never cost the capture — the provider dashboard is the reconciliation ground truth, §7.1)."""
    report = OrganicCaptureReport(snapshot_id=snapshot["id"], keyword=keyword_term)

    existing = (
        db.table("serp_result")
        .select("id")
        .eq("snapshot_id", snapshot["id"])
        .eq("engine", ENGINE)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        report.already_captured = True
        return report

    task = build_organic_task(
        keyword_term,
        float(snapshot["center_lat"]),
        float(snapshot["center_lng"]),
        depth=settings.scan_depth,
        language_code=settings.dataforseo_default_language_code,
        device=settings.scan_device,
    )

    owns = client is None
    client = client or httpx.AsyncClient(timeout=settings.dataforseo_request_timeout_seconds)
    try:
        response = await client.post(
            f"{BASE_URL}{ORGANIC_LIVE_PATH}", headers=_auth_header(settings), json=[task]
        )
        response.raise_for_status()
        body = response.json()
    finally:
        if owns:
            await client.aclose()

    # One full sample, once per process, so an unexpected envelope is diagnosable from the log
    # rather than from a second paid run (the dataforseo_client.py discipline).
    logger.info("organic serp sample", extra={"raw": str(body)[:4000]})

    serp = parse_organic_serp(body)
    scan_month = month_of(snapshot["scanned_at"])
    db.table("serp_result").insert(
        {
            "snapshot_id": snapshot["id"],
            "scan_month": scan_month.isoformat(),
            "engine": ENGINE,
            "payload": body,
            "payload_summary": summarize_serp(serp, depth=settings.scan_depth),
        }
    ).execute()
    report.stored = True
    report.results = len(serp.results)
    report.ai_overview_present = serp.ai_overview_present

    try:
        from .cost import build_ledger_row

        db.table("cost_ledger").insert(
            build_ledger_row(
                market_id=market_id,
                cycle_number=None,
                stage="b2_organic",
                provider="dataforseo",
                units=1,
                cost_cents=settings.dataforseo_cost_per_request_cents,
            )
        ).execute()
    except Exception as exc:  # noqa: BLE001 — a ledger failure must never cost the capture
        logger.error("could not write cost_ledger row", extra={"error": str(exc)[:500]})

    logger.info(
        "organic serp captured",
        extra={
            "snapshot_id": snapshot["id"],
            "results": report.results,
            "ai_overview": report.ai_overview_present,
        },
    )
    return report
