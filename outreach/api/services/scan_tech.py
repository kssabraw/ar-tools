"""Site tech-signal capture — Slice B1 of the paid-placement money signal (PRD §B3).

Fetch each surviving prospect's own site and store the ad/marketing tech detected on it
(`tech_signals.detect_tech_signals`). This is FREE — an own HTTP GET, "not a paid service" (§B3) —
so `scan-tech` is NOT in `PAID_COMMANDS`, the same posture as `collect`/`rollup`.

**The measured-vs-found rule is the whole point.** A fetch that fails records a `fetch_status`
(`unreachable`/`timeout`/`blocked`) with the signal booleans NULL — never `absent`. Unknown ≡ absent
for the scorer, but the two must be stored distinctly so the report can say "couldn't read the site"
rather than "no ad tech" (PRD §B3; the same discipline as the coverage denominator). The pure detector
returns an all-False `TechSignals` only for a page that genuinely loaded and carried nothing.

**GTM follow (ISSUES I-003 / §16a.1).** When a page carries a GTM container but no inline pixel, a
pixel may be injected by the container and invisible to the inline scan. `tech_follow_gtm` (config,
default False) enables fetching the container JS and re-scanning it with the same detector. Whether
that follow is REQUIRED is the §16a.1 spike's call; the seam is built either way.

The fetch is mockable (`fetch_page`), so the orchestration is unit-testable without egress; the pure
detection is tested outright in `tech_signals`.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx

from ..config import Settings
from . import tech_signals as ts
from .paging import fetch_all

logger = logging.getLogger(__name__)

# What the site returns when it is up but blocking bots vs genuinely unreachable — recorded
# distinctly because "blocked" is still evidence the business HAS a site (unknown, not absent),
# while "unreachable" may mean no site at all. Neither is `absent`.
STATUS_OK = "ok"
STATUS_UNREACHABLE = "unreachable"
STATUS_TIMEOUT = "timeout"
STATUS_BLOCKED = "blocked"

# How many per-site failures are kept as examples. The report's COUNTS are always exact.
_MAX_PROBLEMS = 50

# A browser-ish UA — some sites 403 an obvious bot, which would misrecord a live site as unreachable.
_UA = "Mozilla/5.0 (compatible; AR-Outreach-TechScan/1.0)"

FetchFn = Callable[[str], Awaitable["FetchResult"]]


@dataclass(frozen=True)
class FetchResult:
    status: str
    final_url: str | None = None
    body: str = ""


@dataclass
class TechScanReport:
    market_id: str = ""
    considered: int = 0
    fetched_ok: int = 0
    failed: int = 0
    with_pixel: int = 0
    with_ads: int = 0
    with_vendor: int = 0
    stored: int = 0
    problems: list[str] = field(default_factory=list)


def normalize_site_url(website: str | None) -> str | None:
    """A fetchable URL from a stored website value, or None. Pure. Adds https:// when the stored
    value is a bare host, and refuses obviously non-web values (never raises)."""
    if not website:
        return None
    text = website.strip()
    if not text:
        return None
    low = text.lower()
    if low.startswith(("http://", "https://")):
        return text
    # Any other explicit scheme (mailto:, tel:, ftp:, javascript:) is not a fetchable web page. A
    # ":" in the first path segment before any "/" is a scheme marker (a port is vanishingly rare on
    # a stored business website, and rejecting it is the safe direction — no false "you rank").
    if "://" in text or ":" in text.split("/")[0]:
        return None
    return "https://" + text


async def fetch_page(
    url: str, *, timeout: float, max_bytes: int = 2_000_000, client: httpx.AsyncClient | None = None
) -> FetchResult:
    """Fetch one page. Maps transport outcomes to a status; never raises. BILLS NOTHING.

    A 2xx/3xx with a body is `ok`; a 401/403/429 is `blocked` (the site exists, it just won't serve
    us — still evidence of a site, so unknown not absent); a timeout is `timeout`; anything else
    (DNS, connection refused, 5xx) is `unreachable`."""
    owns = client is None
    client = client or httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": _UA}
    )
    try:
        resp = await client.get(url)
        final = str(resp.url)
        if resp.status_code in (401, 403, 429):
            return FetchResult(STATUS_BLOCKED, final, "")
        if resp.status_code >= 400:
            return FetchResult(STATUS_UNREACHABLE, final, "")
        # Truncated, not streamed: ad tags sit in the head and the scripts around it, so the cap
        # costs nothing real and bounds both memory and the regex work per page.
        return FetchResult(STATUS_OK, final, (resp.text or "")[:max_bytes])
    except httpx.TimeoutException:
        return FetchResult(STATUS_TIMEOUT, url, "")
    except httpx.HTTPError:
        return FetchResult(STATUS_UNREACHABLE, url, "")
    finally:
        if owns:
            await client.aclose()


async def scan_prospect_tech(
    prospect: dict[str, Any],
    settings: Settings,
    *,
    fetch: FetchFn,
) -> dict[str, Any] | None:
    """Scan one prospect's site → a `prospect_tech_signal` row (or None when it has no website).

    Follows the GTM container when the page is GTM-only and `tech_follow_gtm` is on (I-003 fix). The
    row always carries a `fetch_status`, so a failed fetch stores unknown, never absent."""
    url = normalize_site_url(prospect.get("website"))
    if not url:
        return None

    page = await fetch(url)
    if page.status != STATUS_OK:
        # Unknown, not absent — the booleans are null-equivalent (all False + the status says why).
        row = ts.summarize_tech(ts.TechSignals(), fetch_status=page.status, final_url=page.final_url)
        row["prospect_id"] = prospect["id"]
        return row

    sig = ts.detect_tech_signals(page.body)
    if settings.tech_follow_gtm and ts.looks_gtm_only(sig):
        for container_id in sig.gtm_container_ids:
            got = await fetch(ts.GTM_CONTAINER_URL.format(container_id=container_id))
            if got.status == STATUS_OK and got.body:
                sig = ts.merge_signals(sig, ts.detect_tech_signals(got.body))
                break  # one container is enough to recover an injected pixel

    row = ts.summarize_tech(sig, fetch_status=STATUS_OK, final_url=page.final_url)
    row["prospect_id"] = prospect["id"]
    return row


async def run_tech_scan(
    db: Any,
    settings: Settings,
    *,
    market_id: str,
    limit: int | None = None,
    fetch: FetchFn | None = None,
) -> TechScanReport:
    """Fetch every prospect-with-a-website in a market and store the tech signals. FREE.

    Scans prospects carrying a website (PRD §B3 detects on the survivors; narrowing to filter
    survivors specifically is a cheap follow-up — a wasted free fetch on an excluded prospect is not
    wrong, only slightly wasteful). Bounded concurrency (`tech_scan_concurrency`); one site's failure
    never ends the batch. Idempotent per prospect — a re-run inserts a fresh dated row (read-latest),
    so the history is kept."""
    report = TechScanReport(market_id=market_id)

    def _q():
        b = (
            db.table("prospect")
            .select("id, name, website")
            .eq("market_id", market_id)
            .not_.is_("website", "null")
        )
        return b

    prospects = [p for p in fetch_all(_q) if normalize_site_url(p.get("website"))]
    if limit:
        prospects = prospects[:limit]
    report.considered = len(prospects)

    await _scan_prospects(db, settings, prospects, fetch=fetch, report=report)
    return report


async def _scan_prospects(
    db: Any,
    settings: Settings,
    prospects: list[dict[str, Any]],
    *,
    fetch: FetchFn | None,
    report: TechScanReport,
) -> TechScanReport:
    """Fetch + store tech signals for an already-selected prospect list, tallying into `report`.

    The shared core of the market-scoped `run_tech_scan` and the tick-driven `run_tech_backlog`:
    bounded concurrency, one site's failure never ends the batch, chunked store. Does NOT set
    `report.considered` — the caller owns selection and its count."""
    if not prospects:
        return report

    timeout = settings.tech_fetch_timeout_seconds
    owns = fetch is None
    client = None if not owns else httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": _UA}
    )
    if fetch is None:
        async def fetch(url: str) -> FetchResult:  # noqa: E306
            return await fetch_page(
                url, timeout=timeout, max_bytes=settings.tech_max_page_bytes, client=client
            )

    sem = asyncio.Semaphore(max(1, settings.tech_scan_concurrency))

    async def _one(prospect: dict[str, Any]) -> dict[str, Any] | None:
        async with sem:
            try:
                return await scan_prospect_tech(prospect, settings, fetch=fetch)
            except Exception as exc:  # noqa: BLE001 — one site must not end the batch
                # Bounded: a market where every site errors would otherwise build a list as long as
                # the market. The counts below stay exact; only the examples are capped.
                if len(report.problems) < _MAX_PROBLEMS:
                    report.problems.append(f"{prospect.get('id')}: {str(exc)[:200]}")
                report.failed += 1
                return None

    try:
        rows = [r for r in await asyncio.gather(*(_one(p) for p in prospects)) if r]
    finally:
        if owns and client is not None:
            await client.aclose()

    for row in rows:
        if row["fetch_status"] == STATUS_OK:
            report.fetched_ok += 1
            report.with_pixel += 1 if row["meta_pixel"] else 0
            report.with_ads += 1 if row["google_ads_conversion"] else 0
            report.with_vendor += 1 if row["vendor_tags"] else 0
        else:
            report.failed += 1

    # Store in chunks — a large market is thousands of rows.
    for start in range(0, len(rows), 200):
        chunk = rows[start : start + 200]
        if not chunk:
            continue
        try:
            db.table("prospect_tech_signal").insert(chunk).execute()
            report.stored += len(chunk)
        except Exception as exc:  # noqa: BLE001 — a store failure is reported, not raised
            report.problems.append(f"store: {str(exc)[:200]}")

    logger.info(
        "tech scan complete",
        extra={"market_id": report.market_id, "ok": report.fetched_ok, "failed": report.failed,
               "pixel": report.with_pixel, "ads": report.with_ads, "vendor": report.with_vendor},
    )
    return report


def pick_backlog(
    candidates: list[dict[str, Any]], signaled: set[str], limit: int | None
) -> list[dict[str, Any]]:
    """Prospects that need a tech fetch — a fetchable website AND no current signal — capped at
    `limit`. Pure, so the "who is due" decision is testable without a DB. Ordering follows
    `candidates` (the caller orders by ingested_at, so the oldest un-scanned prospects go first and
    a backlog drains deterministically rather than re-picking the same head every tick)."""
    out: list[dict[str, Any]] = []
    for p in candidates:
        if p.get("id") in signaled:
            continue
        if not normalize_site_url(p.get("website")):
            continue
        out.append(p)
        if limit and len(out) >= limit:
            break
    return out


def _signaled_prospect_ids(db: Any, *, cutoff_iso: str | None) -> set[str]:
    """prospect_ids that already carry a CURRENT tech signal. `cutoff_iso` None counts ANY signal
    ever (fetch-once); a timestamp counts only signals at/after it, so an older signal reads as
    stale and its prospect is re-fetched."""
    def _q():
        b = db.table("prospect_tech_signal").select("prospect_id")
        if cutoff_iso is not None:
            b = b.gte("fetched_at", cutoff_iso)
        return b

    return {r["prospect_id"] for r in fetch_all(_q) if r.get("prospect_id")}


async def run_tech_backlog(
    db: Any,
    settings: Settings,
    *,
    limit: int | None = None,
    refresh_days: int | None = None,
    fetch: FetchFn | None = None,
) -> TechScanReport:
    """Fetch tech signals for prospects lacking a CURRENT one, across every market. FREE + idempotent.

    This is the `tick` drain (owner ruling 2026-08-14: scan-tech runs automatically each cycle). It
    covers every new run's survivors the cycle after they land AND backfills any market scanned
    before auto-tech existed — including the any-city onboard markets, which have no definition file
    for the market-scoped `run_tech_scan` to target. Bounded by `limit` (`tech_scan_per_tick`) so a
    heartbeat cannot run unboundedly; `refresh_days` (`tech_refresh_days`, 0 = fetch once) decides
    when an existing signal is stale enough to re-fetch. A tick that finds nothing due costs two
    reads and stores nothing."""
    limit = settings.tech_scan_per_tick if limit is None else limit
    refresh_days = settings.tech_refresh_days if refresh_days is None else refresh_days
    report = TechScanReport()
    if limit <= 0:
        return report

    cutoff_iso: str | None = None
    if refresh_days > 0:
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=refresh_days)).isoformat()
    signaled = _signaled_prospect_ids(db, cutoff_iso=cutoff_iso)

    def _q():
        return (
            db.table("prospect")
            .select("id, name, website")
            .not_.is_("website", "null")
            .order("ingested_at", desc=False)
        )

    prospects = pick_backlog(fetch_all(_q), signaled, limit)
    report.considered = len(prospects)
    await _scan_prospects(db, settings, prospects, fetch=fetch, report=report)
    return report
