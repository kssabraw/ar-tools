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

# Paid-placement item types — the fourth competitive signal (outreach HANDOFF §12 item 3a). The
# already-captured organic response ALREADY carries these items; the parser used to discard
# everything that was not organic/ai_overview, so Google-Ads presence is derivable from data on disk
# with NO new paid call.
#
# `paid` is DataForSEO's standard label for a Google Ads text ad in the organic SERP. `local_services`
# is the Local Services Ads ("Google Guaranteed") block. **Both item types are MEASURED, not asserted**
# — `capture_organic` logs the distinct item-type set on first run so the exact envelope for THIS
# account is confirmable from the log rather than a second paid run, and `parse_organic_serp` records
# every non-organic type it saw. If the first live run shows LSA does NOT ride the organic response,
# a dedicated Local-Services endpoint call becomes a gated follow-up (outreach ISSUES I-096); until
# then the cheapest-to-reverse reading is "parse it from the response we already pay for".
_PAID_TYPES = frozenset({"paid"})
_LSA_TYPES = frozenset({"local_services", "google_local_services", "local_service_ads"})


class OrganicScanError(RuntimeError):
    """A failure capturing or parsing an organic SERP, including task-level errors inside a 200."""


@dataclass(frozen=True)
class OrganicResult:
    rank: int
    domain: str
    url: str | None
    title: str | None


@dataclass(frozen=True)
class PaidResult:
    """One Google Ads (paid text) result. `domain` is the advertiser; `rank` its position among the
    paid block (may be absent). The advertiser identity is what the report matches a prospect against
    to decide "is THIS business buying ads" — deterministically, never guessed."""
    rank: int | None
    domain: str | None
    title: str | None


@dataclass(frozen=True)
class LsaResult:
    """One Local Services Ads ("Google Guaranteed") advertiser. LSA entries are keyed by business
    NAME, not domain (the block rarely carries a URL), so the report matches a prospect's name — the
    same loose normalization the AI-mention detector uses."""
    name: str | None
    rank: int | None


@dataclass(frozen=True)
class OrganicSerp:
    results: list[OrganicResult]
    ai_overview_present: bool
    total_count: int
    # Paid-placement signal, parsed from the SAME response (see _PAID_TYPES / _LSA_TYPES). Defaulted
    # so any existing construction still works; parse_organic_serp always fills them.
    paid_results: tuple[PaidResult, ...] = ()
    lsa_results: tuple[LsaResult, ...] = ()
    # Every distinct top-level item `type` the response carried — the measure-don't-infer record, so
    # the first live run's log proves which types this account actually returns for paid/LSA.
    seen_item_types: tuple[str, ...] = ()


@dataclass
class OrganicCaptureReport:
    snapshot_id: str = ""
    keyword: str = ""
    stored: bool = False
    already_captured: bool = False
    results: int = 0
    ai_overview_present: bool = False
    ads_present: bool = False
    lsa_present: bool = False
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
    paid: list[PaidResult] = []
    lsa: list[LsaResult] = []
    seen_types: list[str] = []
    ai_overview = False
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type and item_type not in seen_types:
            seen_types.append(item_type)
        if item_type in _AI_OVERVIEW_TYPES:
            ai_overview = True
            continue
        if item_type in _PAID_TYPES:
            paid.append(_paid_result(item))
            continue
        if item_type in _LSA_TYPES:
            lsa.extend(_lsa_results(item))
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
        paid_results=tuple(paid),
        lsa_results=tuple(lsa),
        seen_item_types=tuple(seen_types),
    )


def _rank_of(item: dict[str, Any]) -> int | None:
    rank = item.get("rank_absolute")
    if rank is None:
        rank = item.get("rank_group")
    return int(rank) if isinstance(rank, (int, float)) and not isinstance(rank, bool) else None


def _paid_result(item: dict[str, Any]) -> PaidResult:
    """One `paid` item → advertiser domain + rank. The domain falls back to one derived from the
    ad's URL when DataForSEO omits `domain` (tolerant, the parser-returns-nothing trap). Pure."""
    domain = str(item.get("domain") or "").lower() or domain_of(item.get("url"))
    return PaidResult(rank=_rank_of(item), domain=domain, title=item.get("title"))


def _lsa_results(item: dict[str, Any]) -> list[LsaResult]:
    """One `local_services` element → its advertiser names. Tolerant of both shapes seen in the wild:
    a flat element carrying its own `title`, and a container whose `items` are the individual
    advertisers. Each name is a business the LSA block is promoting for this search. Pure."""
    rank = _rank_of(item)
    nested = item.get("items")
    if isinstance(nested, list) and nested:
        out: list[LsaResult] = []
        for sub in nested:
            if not isinstance(sub, dict):
                continue
            name = sub.get("title") or sub.get("name")
            out.append(LsaResult(name=str(name) if name else None, rank=_rank_of(sub) or rank))
        if out:
            return out
    name = item.get("title") or item.get("name")
    return [LsaResult(name=str(name) if name else None, rank=rank)]


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
        "paid": summarize_paid(serp),
    }


def summarize_paid(serp: OrganicSerp) -> dict[str, Any]:
    """The paid-placement block of `payload_summary` — the fourth competitive signal. Pure.

    Presence flags plus the advertiser lists, so the per-prospect report (and, later, the Phase-4
    scorer) can read "is this business / are its competitors buying ads for this keyword" straight
    off the snapshot's stored summary, with no re-parse and no new paid call. Nothing here decides
    whether a GIVEN prospect is advertising — that match (their domain vs an advertiser's, their
    name vs an LSA advertiser's) is derived at read time, exactly as the organic prospect_rank is,
    so this stays a per-snapshot fact and never asserts anything about one business.
    """
    advertisers = [
        {"domain": p.domain, "rank": p.rank, "title": p.title}
        for p in serp.paid_results
        if p.domain
    ]
    lsa_advertisers = [
        {"name": a.name, "rank": a.rank} for a in serp.lsa_results if a.name
    ]
    return {
        "ads_present": bool(advertisers),
        "lsa_present": bool(lsa_advertisers),
        "advertisers": advertisers,
        "lsa_advertisers": lsa_advertisers,
        # The measure-don't-infer record: which item types this account actually returned, so the
        # exact paid/LSA envelope is confirmable from a stored summary as well as from the log.
        "seen_item_types": list(serp.seen_item_types),
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
    # The paid/LSA envelope is unproven against this account (organic has never run). Log the distinct
    # item types + what paid parsing found, once, so the exact shape is recoverable from the log
    # rather than a second paid run (the dataforseo_client.py discipline; outreach ISSUES I-096).
    logger.info(
        "organic serp paid signal",
        extra={
            "seen_item_types": list(serp.seen_item_types),
            "paid_count": len(serp.paid_results),
            "lsa_count": len(serp.lsa_results),
        },
    )
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
    report.ads_present = bool(serp.paid_results)
    report.lsa_present = bool(serp.lsa_results)

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
