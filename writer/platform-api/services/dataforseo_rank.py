"""DataForSEO live organic rank — the fallback rank source.

Organic Rank Tracker (Module #4). Used when GSC can't cover a keyword: either
the site has no accessible GSC property, or the site doesn't rank for the
keyword (so GSC returns nothing). Fetches a point-in-time Google organic SERP
and finds the client's domain position, writing it to
rank_keyword_metrics.tracked_rank. Refreshed weekly to bound cost.

DataForSEO writes only tracked_rank; the GSC materialize writes only
gsc_position — the two columns are never reconciled (PRD §2/§5).
"""

from __future__ import annotations

import asyncio
import base64
import calendar
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from config import settings
from db.supabase_client import get_supabase
from services.locations_service import infer_country_iso

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dataforseo.com"
_SERP_PATH = "/v3/serp/google/organic/live/advanced"
_TIMEOUT = 60.0

# A small ISO→DataForSEO country location_code map for the countries the suite's
# location helper already recognizes; falls back to the configured default.
_COUNTRY_LOCATION_CODES = {
    "US": 2840, "GB": 2826, "CA": 2124, "AU": 2036, "NZ": 2554, "IE": 2372,
    "ZA": 2710, "IN": 2356, "SG": 2702, "PH": 2608, "MY": 2458, "DE": 2276,
    "FR": 2250, "ES": 2724, "IT": 2380, "NL": 2528, "SE": 2752, "BR": 2076,
    "MX": 2484, "AE": 2784,
}


def _auth_header() -> dict[str, str]:
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    encoded = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


# ----------------------------------------------------------------------------
# Transient-error classification + per-keyword retry.
#
# The live SERP endpoint returns a task-level error INSIDE an HTTP 200 body
# (observed live 2026-09-13: ~42% of a client's keywords failed this way in one
# run, spread evenly across it — i.e. intermittent throttle/limit, not a hard
# quota wall). Without a retry each such keyword is dropped for the whole run,
# which — for a weekly-cadence keyword that's null 6/7 days by design — reads
# downstream as a full null week and can trip a false deindex signal. So retry
# transient failures per keyword; fail fast (and abort the run) only on the
# auth/payment codes that will hit every keyword.
# Only an account-wide auth/billing failure is worth aborting a whole run for
# (it will hit every keyword). DataForSEO's task status_codes are NOT grouped by
# category into clean numeric ranges — e.g. 40101 is "Internal SE Server Error",
# a TRANSIENT search-engine failure DataForSEO itself already retried, not an
# auth error — so classify "terminal" from the message the API returns, never a
# guessed code range. Everything that isn't clearly auth/billing (internal SE
# errors, throttles, generic task errors) is transient and gets retried.
_TERMINAL_MESSAGE_TERMS = (
    # authentication / authorization
    "unauthor", "not authorized", "authentication", "authorization",
    "access denied", "forbidden", "invalid login", "invalid password",
    "invalid credential", "invalid api key",
    # payment / balance
    "payment required", "insufficient funds", "insufficient balance",
    "not enough money", "not enough credits", "out of money", "no funds",
)
# HTTP statuses worth retrying (rate limit + transient server errors).
_RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})


class DataForSeoTaskError(RuntimeError):
    """A DataForSEO task-level error (HTTP 200 body, task status_code >= 40000).

    Subclasses RuntimeError so existing broad `except`s keep working; carries the
    task `status_code`/`status_message` so the caller can classify + surface it.
    """

    def __init__(self, status_code: int, status_message: str = ""):
        self.status_code = int(status_code or 0)
        self.status_message = status_message or ""
        super().__init__(f"dataforseo_serp_error {self.status_code}: {self.status_message}")


class DataForSeoTerminalError(DataForSeoTaskError):
    """An auth/payment task error — it will hit every keyword, so abort the run."""


def is_terminal_task_message(message: str) -> bool:
    """True when a task-level error message signals an account-wide auth/billing
    problem that will hit every keyword (so the run should abort). Classified by
    message, not code, because DataForSEO codes aren't categorized by numeric
    range — a transient "Internal SE Server Error" (40101) must NOT read as
    terminal."""
    m = (message or "").lower()
    return any(term in m for term in _TERMINAL_MESSAGE_TERMS)


def is_retryable_exc(exc: Exception) -> bool:
    """Whether a fetch failure is transient (retry) vs terminal/permanent (skip).

    Non-terminal task errors (throttle/limit/generic/5xxxx server) and httpx
    transport / 429 / 5xx are transient; a terminal task error, a non-retryable
    HTTP status, or any other exception is not.
    """
    if isinstance(exc, DataForSeoTerminalError):
        return False
    if isinstance(exc, DataForSeoTaskError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_HTTP_STATUS
    if isinstance(exc, httpx.TransportError):  # timeouts, connect/read/protocol errors
        return True
    return False


def retry_delay_seconds(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff for a 1-based attempt: ``base * 2**(attempt-1)``,
    clamped to ``[base, cap]``. Pure."""
    base_f = max(0.1, float(base))
    cap_f = max(base_f, float(cap))
    n = max(1, int(attempt))
    shift = min(n - 1, 20)  # bound the exponent; the min() clamps anyway
    return min(cap_f, base_f * (2 ** shift))


def build_failure_summary(failed: list[dict], *, sample: int = 10) -> dict:
    """Compact per-run fetch-failure summary for the job result / observability.

    `failed` is a list of ``{keyword, status_code, error}``. Returns the failure
    count, the dominant status codes (count-desc), and a bounded keyword sample —
    so a run that dropped a large fraction of keywords is visible in the job
    record, not only in the logs. Pure.
    """
    codes = Counter(int(f.get("status_code") or 0) for f in failed)
    return {
        "count": len(failed),
        "status_codes": {str(code): n for code, n in codes.most_common()},
        "sample": [
            {"keyword": f.get("keyword"), "status_code": int(f.get("status_code") or 0)}
            for f in failed[: max(0, sample)]
        ],
    }


async def fetch_serp_rank_with_retry(
    keyword: str,
    domain: str,
    location_code: int,
    *,
    max_retries: Optional[int] = None,
    fetch=None,
    sleep=None,
) -> Optional[int]:
    """`fetch_serp_rank` with bounded exponential backoff on transient errors.

    Retries transient DataForSEO task errors (throttle/limit/server) and httpx
    transport / 429 / 5xx failures up to `max_retries` times (default from
    config). A terminal (auth/payment) task error or any other non-transient
    failure re-raises immediately. `fetch`/`sleep` are injectable for tests.
    """
    fetch = fetch or fetch_serp_rank
    sleep = sleep or asyncio.sleep
    retries = settings.dataforseo_rank_max_retries if max_retries is None else max_retries
    base = settings.dataforseo_rank_retry_base_seconds
    cap = settings.dataforseo_rank_retry_cap_seconds
    attempt = 0
    while True:
        try:
            return await fetch(keyword, domain, location_code)
        except Exception as exc:  # noqa: BLE001 — classify, re-raise if terminal
            attempt += 1
            if attempt > retries or not is_retryable_exc(exc):
                raise
            delay = retry_delay_seconds(attempt, base, cap)
            logger.warning(
                "dataforseo_rank_retry keyword=%s attempt=%s delay_s=%s error=%s",
                keyword, attempt, round(delay, 1), str(exc)[:200],
            )
            await sleep(delay)


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def extract_domain(website_url: str) -> str:
    """Registrable host for SERP matching: strip scheme, path, and leading www."""
    if not website_url:
        return ""
    raw = website_url if "//" in website_url else f"//{website_url}"
    host = (urlparse(raw).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def location_code_for(client: dict) -> int:
    """DataForSEO location for a client's rank/market checks.

    Prefers an explicit per-client tracking location (city/region/country picked
    in the UI); otherwise falls back to the country auto-detected from the
    website TLD.
    """
    code = client.get("rank_tracking_location_code")
    if code:
        return int(code)
    iso = infer_country_iso(client)
    return _COUNTRY_LOCATION_CODES.get(iso, settings.dataforseo_default_location_code)


def find_rank_in_items(items: list[dict], domain: str) -> Optional[int]:
    """First organic result whose domain matches `domain`, by rank_absolute.

    Returns None when the domain isn't in the fetched results (= not ranking in
    the top N) — a real, stored fact, not an error.
    """
    if not domain:
        return None
    for item in items:
        if item.get("type") != "organic":
            continue
        item_domain = (item.get("domain") or "").lower()
        if item_domain == domain or item_domain.endswith("." + domain):
            rank = item.get("rank_absolute") or item.get("rank_group")
            return int(rank) if rank is not None else None
    return None


def find_all_ranks_in_items(items: list[dict], domain: str) -> list[dict]:
    """Every organic result whose domain matches `domain`, as ``{url, position}``.

    Unlike :func:`find_rank_in_items` (first hit only), this returns *all* of the
    client's ranking URLs in the SERP — so the existing-page precheck can surface
    multiple pages competing for the same keyword (cannibalization) and let the
    user pick which to reoptimize. Ordered by position (best first).
    """
    if not domain:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if item.get("type") != "organic":
            continue
        item_domain = (item.get("domain") or "").lower()
        if item_domain == domain or item_domain.endswith("." + domain):
            url = item.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            rank = item.get("rank_absolute") or item.get("rank_group")
            out.append({"url": url, "position": int(rank) if rank is not None else None})
    out.sort(key=lambda r: (r["position"] is None, r["position"] or 0))
    return out


def is_gsc_covered(rows: list[dict], today: date, days: int) -> bool:
    """True if the keyword has a non-null GSC position within the last `days`."""
    cutoff = today.toordinal() - days + 1
    for row in rows:
        if row.get("gsc_position") is None:
            continue
        d = row["date"]
        d_ord = (d if isinstance(d, date) else date.fromisoformat(d)).toordinal()
        if d_ord >= cutoff:
            return True
    return False


def is_stale_refetch_due(last_fetched_at: Optional[str], today: date, stale_days: int) -> bool:
    """Whether an off-cadence DataForSEO pull should fire for a GSC-stalled client.

    Bounds the stall-triggered refresh to at most once per `stale_days`: fires
    when there's no prior pull, or the last one is at least `stale_days` old. Pure.
    """
    if not last_fetched_at:
        return True
    last = date.fromisoformat(last_fetched_at[:10])
    return (today.toordinal() - last.toordinal()) >= max(1, stale_days)


def is_gsc_stalled(max_gsc_date: Optional[str], today: date, stale_days: int) -> bool:
    """True when a property's freshest GSC date is older than `stale_days`
    (or it has no GSC data at all). Pure."""
    if not max_gsc_date:
        return True
    latest = date.fromisoformat(max_gsc_date[:10])
    return (today.toordinal() - latest.toordinal()) > max(1, stale_days)


def is_fetch_due(config: dict, today: date, default_weekday: int) -> bool:
    """Whether a client's scheduled DataForSEO rank pull should fire today.

    `config` is a rank_fetch_config row (or {} for a client with no explicit
    schedule, which defaults to the legacy weekly-on-`default_weekday` cadence).
    Mirrors rank_report.is_report_due; 'off' never auto-fires, and a fetch never
    fires twice on the same day. `default_weekday` is config.dataforseo_rank_weekday.
    """
    mode = config.get("mode", "weekly")
    if mode == "off":
        return False

    last_raw = config.get("last_fetched_at")
    last_date = date.fromisoformat(last_raw[:10]) if last_raw else None
    if last_date == today:
        return False

    if mode == "weekly":
        dow = config.get("day_of_week")
        if dow is None:
            dow = default_weekday
        return today.weekday() == dow
    if mode == "monthly":
        dom = config.get("day_of_month") or 1
        last_day = calendar.monthrange(today.year, today.month)[1]
        return today.day == min(dom, last_day)  # clamp e.g. 31 → month end
    if mode == "interval":
        n = config.get("interval_days") or 7
        return last_date is None or (today.toordinal() - last_date.toordinal()) >= n
    return False


# ----------------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------------
async def fetch_serp_rank(keyword: str, domain: str, location_code: int) -> Optional[int]:
    """Live organic SERP rank of `domain` for `keyword`, or None if not found."""
    payload = [
        {
            "keyword": keyword,
            "language_code": settings.dataforseo_default_language_code,
            "location_code": location_code,
            "depth": settings.dataforseo_serp_depth,
            "calculate_rectangles": False,
        }
    ]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{_BASE_URL}{_SERP_PATH}", headers=_auth_header(), json=payload)
        resp.raise_for_status()
        body = resp.json()

    tasks = body.get("tasks") or []
    if not tasks:
        raise DataForSeoTaskError(0, "no tasks in response")
    task = tasks[0]
    code = int(task.get("status_code") or 0)
    if code >= 40000:
        msg = task.get("status_message") or ""
        if is_terminal_task_message(msg):
            raise DataForSeoTerminalError(code, msg)
        raise DataForSeoTaskError(code, msg)
    items = (task.get("result") or [{}])[0].get("items") or []
    return find_rank_in_items(items, domain)


def find_local_pack_in_items(items: list[dict]) -> list[dict]:
    """The local pack (map pack) entries in a SERP `items` array, in order. Pure.

    Returns ``[{position, title, domain, rating, reviews}, ...]`` — empty when
    the SERP has no local pack, which is itself the answer to "is this keyword
    even a local-pack query?". The organic and local-pack blocks come back in
    the SAME response, so reading this costs no extra call.
    """
    out: list[dict] = []
    for item in items or []:
        if (item.get("type") or "") != "local_pack":
            continue
        rating = item.get("rating") or {}
        out.append({
            "position": item.get("rank_group") or len(out) + 1,
            "title": item.get("title"),
            "domain": item.get("domain"),
            "rating": rating.get("value"),
            "reviews": rating.get("votes_count"),
        })
    return out


async def fetch_serp_overview(
    keyword: str, domain: str, location_code: int
) -> dict:
    """One live SERP call, read two ways: where `domain` ranks organically AND
    who holds the local pack.

    Returns ``{"organic": [{url, position}, ...], "local_pack": [...],
    "has_local_pack": bool}``. A strategy question ("how do we rank in X") needs
    both channels, and DataForSEO returns both blocks in a single response — so
    this is one paid call, not two. Raises on a task error so callers degrade.
    """
    payload = [
        {
            "keyword": keyword,
            "language_code": settings.dataforseo_default_language_code,
            "location_code": location_code,
            "depth": settings.dataforseo_serp_depth,
            "calculate_rectangles": False,
        }
    ]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{_BASE_URL}{_SERP_PATH}", headers=_auth_header(), json=payload)
        resp.raise_for_status()
        body = resp.json()

    tasks = body.get("tasks") or []
    if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
        raise RuntimeError(f"dataforseo_serp_error: {tasks[0].get('status_message') if tasks else 'no tasks'}")
    items = (tasks[0].get("result") or [{}])[0].get("items") or []
    pack = find_local_pack_in_items(items)
    return {
        "organic": find_all_ranks_in_items(items, domain),
        "local_pack": pack,
        "has_local_pack": bool(pack),
    }


async def fetch_serp_rank_urls(keyword: str, domain: str, location_code: int) -> list[dict]:
    """Live organic SERP: ALL of `domain`'s ranking URLs for `keyword`.

    Returns ``[{url, position}, ...]`` (possibly empty), best position first.
    Used by the existing-page precheck to detect one *or several* of the client's
    pages already ranking for the keyword. Raises on a DataForSEO task error so
    the caller can degrade.
    """
    payload = [
        {
            "keyword": keyword,
            "language_code": settings.dataforseo_default_language_code,
            "location_code": location_code,
            "depth": settings.dataforseo_serp_depth,
            "calculate_rectangles": False,
        }
    ]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{_BASE_URL}{_SERP_PATH}", headers=_auth_header(), json=payload)
        resp.raise_for_status()
        body = resp.json()

    tasks = body.get("tasks") or []
    if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
        raise RuntimeError(f"dataforseo_serp_error: {tasks[0].get('status_message') if tasks else 'no tasks'}")
    items = (tasks[0].get("result") or [{}])[0].get("items") or []
    return find_all_ranks_in_items(items, domain)


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
async def refresh_client_ranks(client_id: str, today: Optional[date] = None) -> dict:
    """Fetch DataForSEO ranks for every keyword GSC can't cover, for one client.

    Skips keywords already covered by a verified GSC property; for the rest,
    writes today's tracked_rank into rank_keyword_metrics. Returns a small
    summary. Designed not to raise for a single keyword's failure.
    """
    supabase = get_supabase()
    today = today or date.today()

    client_res = supabase.table("clients").select(
        "id, name, website_url, gbp, rank_tracking_location_code"
    ).eq("id", client_id).limit(1).execute()
    if not client_res.data:
        return {"status": "failed", "error": "client_not_found", "fetched": 0}
    client = client_res.data[0]
    domain = extract_domain(client.get("website_url") or "")
    if not domain:
        return {"status": "failed", "error": "client_has_no_website", "fetched": 0}
    location_code = location_code_for(client)

    gsc_available = bool(
        supabase.table("gsc_properties")
        .select("id")
        .eq("client_id", client_id)
        .eq("access_status", "ok")
        .limit(1)
        .execute()
        .data
    )

    keywords = (
        supabase.table("tracked_keywords")
        .select("id, keyword")
        .eq("client_id", client_id)
        .eq("active", True)
        .execute()
    ).data or []
    if not keywords:
        return {"status": "ok", "fetched": 0, "skipped": 0}

    # Pull recent metrics once to decide GSC coverage per keyword.
    cutoff = (today - timedelta(days=settings.rank_gsc_coverage_days)).isoformat()
    metrics = (
        supabase.table("rank_keyword_metrics")
        .select("keyword_id, date, gsc_position")
        .in_("keyword_id", [k["id"] for k in keywords])
        .gte("date", cutoff)
        .execute()
    ).data or []
    by_keyword: dict[str, list[dict]] = {}
    for row in metrics:
        by_keyword.setdefault(row["keyword_id"], []).append(row)

    fetched = skipped = failed = 0
    failed_details: list[dict] = []
    terminal_error: Optional[dict] = None
    # Treat GSC as "covering" a keyword only while its data is fresh
    # (rank_gsc_stale_refetch_days), NOT the full display-coverage window: once
    # GSC stalls past that, step in with a live DataForSEO rank rather than
    # leaving the keyword unmeasured until GSC's silence trips a false deindex.
    stale_days = settings.rank_gsc_stale_refetch_days
    for kw in keywords:
        covered = gsc_available and is_gsc_covered(
            by_keyword.get(kw["id"], []), today, stale_days
        )
        if covered:
            skipped += 1
            continue
        try:
            rank = await fetch_serp_rank_with_retry(kw["keyword"], domain, location_code)
        except DataForSeoTerminalError as exc:
            # Auth/payment: every remaining keyword would fail the same way — stop
            # now, and leave the fetch clock untouched so the next tick retries.
            terminal_error = {"status_code": exc.status_code, "error": exc.status_message[:200]}
            logger.error(
                "dataforseo_rank_terminal client_id=%s keyword=%s status_code=%s error=%s aborting_run",
                client_id, kw["keyword"], exc.status_code, exc.status_message[:200],
            )
            break
        except Exception as exc:  # noqa: BLE001 — transient exhausted / non-retryable: skip this keyword
            failed += 1
            code = int(getattr(exc, "status_code", 0) or 0)
            failed_details.append({"keyword": kw["keyword"], "status_code": code, "error": str(exc)[:200]})
            # Inline (not extra=): basicConfig formats only %(message)s, so anything
            # passed via extra never reaches the logs — name the keyword + code here.
            logger.warning(
                "dataforseo_rank_failed keyword=%s status_code=%s error=%s",
                kw["keyword"], code, str(exc)[:200],
            )
            continue
        supabase.table("rank_keyword_metrics").upsert(
            {"keyword_id": kw["id"], "date": today.isoformat(), "tracked_rank": rank},
            on_conflict="keyword_id,date",
        ).execute()
        fetched += 1

    # Advance the per-client fetch clock so interval schedules measure "days
    # since the last real pull" and a weekly/monthly fetch can't double-fire the
    # same day — whether triggered by the scheduler or a manual refresh. Skip the
    # stamp when EVERY attempt errored (transient DataForSEO outage — nothing
    # fetched) or the run aborted on a terminal error: leaving last_fetched_at
    # unchanged lets the next interval tick retry instead of waiting a full cycle
    # on a bad day. (fetched>0, or a pull with nothing to do because all keywords
    # are GSC-covered, both stamp.)
    if terminal_error is None and not (fetched == 0 and failed > 0):
        now_iso = datetime.now(timezone.utc).isoformat()
        cfg_row = {"client_id": client_id, "last_fetched_at": now_iso, "updated_at": now_iso}
        # last_active_fetch_at advances ONLY when we actually queried the SERP for
        # >=1 keyword (fetched > 0) — a run that skipped every keyword because GSC
        # covers them leaves it untouched. The freshness watch relies on this to
        # tell a genuine pipeline stall (never actively checked) from a site that
        # was checked and simply isn't ranking (fetched, found nothing).
        if fetched > 0:
            cfg_row["last_active_fetch_at"] = now_iso
        supabase.table("rank_fetch_config").upsert(cfg_row, on_conflict="client_id").execute()

    result: dict = {
        "status": "failed" if terminal_error else "ok",
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed,
    }
    if failed_details:
        result["failures"] = build_failure_summary(failed_details)
    if terminal_error:
        result["error"] = f"dataforseo_terminal_{terminal_error['status_code']}"
        result["terminal"] = terminal_error

    logger.info(
        "dataforseo_rank_complete client_id=%s fetched=%s skipped=%s failed=%s terminal=%s",
        client_id, fetched, skipped, failed, bool(terminal_error),
    )
    return result


def enqueue_dataforseo_rank(client_id: str) -> str:
    """Enqueue a DataForSEO rank job (deduped against pending/running ones).

    Returns the job id — the existing one when a pull is already queued/running
    (so a manual refresh rides the in-flight job rather than double-fetching),
    otherwise the newly-inserted one.
    """
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "dataforseo_rank")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]
    inserted = supabase.table("async_jobs").insert(
        {"job_type": "dataforseo_rank", "entity_id": client_id, "payload": {"client_id": client_id}}
    ).execute()
    return inserted.data[0]["id"]


async def run_dataforseo_rank_job(job: dict) -> None:
    """async_jobs handler for job_type='dataforseo_rank'."""
    from services.rank_materialize import enqueue_materialize

    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    result = await refresh_client_ranks(client_id)
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.get("status") == "ok" else "failed",
            "result": result,
            "error": result.get("error"),
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()

    # Recompute status/source now that fresh DataForSEO ranks have landed.
    if result.get("status") == "ok" and result.get("fetched"):
        enqueue_materialize(client_id)
