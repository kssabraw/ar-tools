"""Freeze Protocol — the suite's kill switch (Link Building SOP §Risk Monitoring
& Freeze Protocol; docs/sops/Link_Building_SOP.md).

On a confirmed **manual action** or **site deindexing**, a client is frozen:
an alert lands on the client card (notifications feed), all content creation
and link-building work pauses (router + job-worker gates call ``is_frozen`` /
``assert_not_frozen``), and the Admins are notified (Slack/email through the
notifications service). This is a freeze, not a recovery procedure — recovery
is owned by Kyle/Ryan/Admins, who lift the freeze explicitly.

How a freeze opens:
  * **Manual** — an admin confirms a manual action or deindexing in the GSC UI
    and freezes via ``POST /clients/{id}/freeze``. (Google exposes no manual-
    actions API, so that half of the SOP's daily check is human-confirmed.)
  * **Automatic detection is warn-only** — the daily ``freeze_check`` job never
    auto-freezes; it only raises a "possible deindexing — verify" warning that a
    human confirms in GSC before freezing. On the GSC path it inspects the
    homepage through the **URL Inspection API** and warns only when the
    ``coverageState`` says the page is *genuinely* not indexed — a benign
    ``NEUTRAL`` (redirect / duplicate / alternate canonical, e.g. an http-vs-https
    or www mismatch) is the page living on Google under a different URL, not a
    deindex, and must not alarm. Clients without a verified GSC property get a
    best-effort DataForSEO ``site:`` probe (from the client's own locale); a zero
    result only warns when the homepage is also unreachable — a `site:` miss on a
    live site is a probe artifact. All warnings are deduped so a daily check can't
    re-fire the same unconfirmed alarm.

Pure helpers (`should_warn_deindex`, `job_client_id`) are unit-tested without a DB.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import notifications

logger = logging.getLogger(__name__)

# Job types that create content or build links — the work the SOP pauses under
# an active freeze. Analysis/monitoring jobs (scans, ingests, reports, plans)
# keep running: the SOP pauses *output*, not observation.
FREEZE_GATED_JOB_TYPES = {
    "local_seo_generate",
    "local_seo_reoptimize_url",
    "local_seo_reoptimize_page",
    "syndication_item",
    "content_batch_item",
}

_REASON_TITLES = {
    "manual_action": "FREEZE: manual action",
    "deindexing": "FREEZE: site deindexed",
    "manual": "FREEZE: manual freeze",
}


# ----------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ----------------------------------------------------------------------------
def job_client_id(job: dict) -> Optional[str]:
    """Best-effort client id for an async job: payload.client_id, else entity_id."""
    payload = job.get("payload") or {}
    return payload.get("client_id") or job.get("entity_id")


# GSC URL-Inspection coverageState substrings that mean the homepage is
# GENUINELY out of Google's index. These are the only NEUTRAL states worth
# warning on. Matched case-insensitively as substrings (Google's exact strings
# vary: "Crawled - currently not indexed", "Discovered - currently not indexed",
# "URL is unknown to Google", "Not found (404)", "Soft 404", server errors).
_DEINDEXED_COVERAGE_MARKERS = (
    "currently not indexed",
    "unknown to google",
    "not found",
    "soft 404",
    "server error",
)
# Benign coverageState substrings — the page is on Google under a *different*
# canonical (redirect/duplicate/alternate) or is intentionally excluded. A
# homepage in one of these states is NOT deindexed, so it must never alarm.
# These are exactly the states that produced the false positives: a homepage
# inspected on the "wrong" scheme/host (http vs https, www vs non-www) comes back
# as NEUTRAL "Page with redirect" / "Duplicate, Google chose different canonical".
# NB: no "indexed" marker here — it would substring-match "not indexed". Genuinely
# indexed pages are PASS verdicts, already handled above.
_BENIGN_COVERAGE_MARKERS = (
    "redirect",           # "Page with redirect" (http→https, www→non-www)
    "canonical",          # "Duplicate, Google chose different canonical…" / "Alternate page…"
    "duplicate",
    "alternate",
    "noindex",            # intentional exclusion, not a penalty deindex
    "blocked by robots",  # intentional
)


def should_warn_deindex(verdict: Optional[str], coverage_state: Optional[str]) -> bool:
    """Whether a homepage URL-Inspection read is a *real* deindexing signal.

    ``coverageState`` is the authority, not the coarse verdict. GSC's
    ``verdict=NEUTRAL`` means "Excluded" in Search Console — for a homepage that is
    overwhelmingly a benign canonical/redirect/alternate state (the page is on
    Google under a different URL), NOT a deindex. Only a hard ``FAIL`` verdict, or
    a coverageState that says the page is genuinely not in the index, counts. A
    missing/unknown verdict (API hiccup) or a benign coverage string never alarms.
    Pure. (Detection is warn-only — automatic deindex never freezes a client; an
    admin confirms in GSC and freezes from the workspace.)
    """
    if verdict == "PASS":
        return False
    cov = (coverage_state or "").lower()
    if any(m in cov for m in _BENIGN_COVERAGE_MARKERS):
        return False
    if verdict == "FAIL":
        return True
    if verdict == "NEUTRAL":
        return any(m in cov for m in _DEINDEXED_COVERAGE_MARKERS)
    return False  # VERDICT_UNSPECIFIED / None — inconclusive, never alarm


# ----------------------------------------------------------------------------
# Freeze state (DB)
# ----------------------------------------------------------------------------
def active_freeze(client_id: str) -> Optional[dict]:
    """The client's active freeze row, or None."""
    try:
        rows = (
            get_supabase()
            .table("client_freezes")
            .select("*")
            .eq("client_id", client_id)
            .eq("status", "active")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.error("freeze.active_lookup_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def is_frozen(client_id: Optional[str]) -> bool:
    if not client_id:
        return False
    return active_freeze(client_id) is not None


def assert_not_frozen(client_id: str) -> None:
    """Router gate: raise 409 client_frozen when the client is under an active
    freeze — content creation and link building both stop (SOP)."""
    if is_frozen(client_id):
        raise HTTPException(status_code=409, detail="client_frozen")


def freeze_client(
    client_id: str,
    reason: str,
    *,
    source: str = "manual",
    note: Optional[str] = None,
    details: Optional[dict] = None,
) -> dict:
    """Open a freeze (idempotent: an existing active freeze is returned, not
    duplicated) and notify the Admins. Never partially fails silently — the
    freeze row is the source of truth; the notification is best-effort."""
    existing = active_freeze(client_id)
    if existing:
        return existing

    supabase = get_supabase()
    row = (
        supabase.table("client_freezes")
        .insert(
            {
                "client_id": client_id,
                "reason": reason,
                "source": source,
                "note": note,
                "details": details,
            }
        )
        .execute()
    ).data[0]

    client_name = _client_name(client_id)
    notifications.emit(
        client_id,
        kind="freeze_opened",
        title=_REASON_TITLES.get(reason, "FREEZE"),
        summary=(
            f"{client_name or 'Client'} is frozen ({reason.replace('_', ' ')}). "
            "All link building and content creation are paused until an admin lifts the freeze."
            + (f" Note: {note}" if note else "")
        ),
        severity="critical",
        payload={"link": f"clients/{client_id}", "freeze_id": row["id"], "reason": reason},
    )
    logger.warning(
        "freeze.opened",
        extra={"client_id": client_id, "reason": reason, "source": source, "freeze_id": row["id"]},
    )
    return row


def lift_freeze(client_id: str, lifted_by: Optional[str] = None) -> int:
    """Lift all active freezes for the client; returns how many were lifted."""
    supabase = get_supabase()
    result = (
        supabase.table("client_freezes")
        .update(
            {
                "status": "lifted",
                "lifted_at": datetime.now(timezone.utc).isoformat(),
                "lifted_by": lifted_by,
            }
        )
        .eq("client_id", client_id)
        .eq("status", "active")
        .execute()
    )
    lifted = len(result.data or [])
    if lifted:
        notifications.emit(
            client_id,
            kind="freeze_lifted",
            title="Freeze lifted",
            summary=f"{_client_name(client_id) or 'Client'} is unfrozen — link building and content creation may resume.",
            severity="info",
            payload={"link": f"clients/{client_id}"},
        )
        logger.info("freeze.lifted", extra={"client_id": client_id, "lifted_by": lifted_by, "count": lifted})
    return lifted


def _client_name(client_id: str) -> Optional[str]:
    try:
        rows = (
            get_supabase().table("clients").select("name").eq("id", client_id).limit(1).execute()
        ).data or []
        return rows[0]["name"] if rows else None
    except Exception:
        return None


def _client_row(client_id: str) -> Optional[dict]:
    """Full client row (best-effort) — used to probe from the client's own
    locale rather than a hardcoded US SERP."""
    try:
        rows = (
            get_supabase().table("clients").select("*").eq("id", client_id).limit(1).execute()
        ).data or []
        return rows[0] if rows else None
    except Exception:
        return None


def _recent_deindex_suspect(client_id: str, within_days: int = 6) -> bool:
    """Whether we've already warned about possible deindexing for this client
    recently. A daily check must not re-emit the same unconfirmed warning every
    run — one open warning is enough until an admin acts on it."""
    from datetime import timedelta

    try:
        since = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat()
        rows = (
            get_supabase()
            .table("notifications")
            .select("id")
            .eq("client_id", client_id)
            .eq("kind", "freeze_suspect")
            .gte("created_at", since)
            .limit(1)
            .execute()
        ).data or []
        return bool(rows)
    except Exception:
        # On a lookup failure, suppress rather than risk a duplicate false alarm.
        return True


async def _homepage_is_live(website_url: str) -> bool:
    """Best-effort: does the homepage respond (status < 400, following
    redirects)? A live homepage means a `site:` miss is a probe artifact, not a
    deindex — so we suppress the warning. On any network error we can't confirm
    the site is up, so we return False (let the probe result stand)."""
    import httpx

    url = website_url if website_url.startswith("http") else f"https://{website_url}"
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ARToolsBot/1.0)"})
        return resp.status_code < 400
    except Exception:
        return False


# ----------------------------------------------------------------------------
# Daily freeze check (scheduler → async job)
# ----------------------------------------------------------------------------
def enqueue_due_freeze_checks() -> int:
    """Enqueue one `freeze_check` job per active client with a website. Called
    once per day by the shared scheduler. Skips clients that already have a
    pending/running check queued."""
    if not settings.freeze_check_enabled:
        return 0
    supabase = get_supabase()
    try:
        clients = (
            supabase.table("clients")
            .select("id, website_url")
            .eq("archived", False)
            .not_.is_("website_url", "null")
            .execute()
        ).data or []
        pending = (
            supabase.table("async_jobs")
            .select("entity_id")
            .eq("job_type", "freeze_check")
            .in_("status", ["pending", "running"])
            .execute()
        ).data or []
        queued = {p.get("entity_id") for p in pending}
    except Exception as exc:
        logger.error("freeze.enqueue_query_failed", extra={"error": str(exc)})
        return 0

    count = 0
    for c in clients:
        if not (c.get("website_url") or "").strip() or c["id"] in queued:
            continue
        try:
            supabase.table("async_jobs").insert(
                {
                    "job_type": "freeze_check",
                    "entity_id": c["id"],
                    "payload": {"client_id": c["id"], "website_url": c["website_url"]},
                }
            ).execute()
            count += 1
        except Exception as exc:
            logger.error("freeze.enqueue_failed", extra={"client_id": c["id"], "error": str(exc)})
    if count:
        logger.info("freeze.checks_enqueued", extra={"count": count})
    return count


def _verified_gsc_property(client_id: str) -> Optional[dict]:
    try:
        rows = (
            get_supabase()
            .table("gsc_properties")
            .select("site_url, property_type, access_status")
            .eq("client_id", client_id)
            .eq("access_status", "ok")
            .limit(1)
            .execute()
        ).data or []
        return rows[0] if rows else None
    except Exception:
        return None


async def run_freeze_check_job(job: dict) -> None:
    """Daily homepage-indexation check for one client (the automatable half of
    the SOP's daily manual-action/deindexing check).

    GSC path (authoritative): URL-Inspect the homepage against the verified
    property; a not-indexed verdict → automatic deindexing freeze. Fallback
    path (no GSC): DataForSEO `site:` probe; zero results → warning
    notification only ("possible deindexing — verify"), never an auto-freeze.
    """
    import asyncio

    from services import gsc_service, site_page_index
    from services.dataforseo_rank import extract_domain

    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    client_id = payload.get("client_id") or job.get("entity_id")
    website_url = (payload.get("website_url") or "").strip()

    def _complete(result: dict) -> None:
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job_id).execute()

    try:
        if not client_id or not website_url:
            _complete({"skipped": "no_client_or_website"})
            return
        if is_frozen(client_id):
            _complete({"skipped": "already_frozen"})
            return

        prop = _verified_gsc_property(client_id) if gsc_service.is_configured() else None
        if prop:
            # GSC path (authoritative but warn-only): inspect the homepage and,
            # if coverageState says it's genuinely not indexed, WARN — never
            # auto-freeze. A benign NEUTRAL (redirect/canonical/alternate — e.g. a
            # http-vs-https or www mismatch) is not a deindex and must not alarm.
            homepage = website_url if website_url.endswith("/") else website_url + "/"
            inspection = await asyncio.to_thread(gsc_service.inspect_url, prop["site_url"], homepage)
            verdict = inspection.get("verdict")
            coverage = inspection.get("coverage_state")
            if should_warn_deindex(verdict, coverage) and not _recent_deindex_suspect(client_id):
                notifications.emit(
                    client_id,
                    kind="freeze_suspect",
                    title="Possible deindexing — verify",
                    summary=(
                        f"GSC URL Inspection reports the homepage as not indexed "
                        f"(coverage: {coverage or 'unknown'}). Verify in Search Console; "
                        "if confirmed, freeze the client from its workspace."
                    ),
                    severity="warning",
                    payload={"link": f"clients/{client_id}"},
                )
                _complete({"frozen": False, "method": "gsc_url_inspection", "verdict": verdict, "coverage_state": coverage, "warned": True})
            else:
                _complete({"frozen": False, "method": "gsc_url_inspection", "verdict": verdict, "coverage_state": coverage})
            return

        # No verified GSC property — best-effort site: probe, warn-only. A
        # `site:` miss is a weak, false-positive-prone signal on its own, so:
        #   (a) probe from the CLIENT'S locale, not a hardcoded US SERP; and
        #   (b) only warn if the homepage is actually unreachable — a live
        #       homepage means the empty `site:` result is a probe artifact.
        #   (c) don't re-warn while an unconfirmed warning is already open.
        if settings.dataforseo_login and settings.dataforseo_password:
            from services.dataforseo_rank import location_code_for

            client_row = _client_row(client_id)
            location_code = (
                location_code_for(client_row) if client_row else settings.dataforseo_default_location_code
            )
            domain = extract_domain(website_url)
            urls = await site_page_index._fetch_google_indexed_urls(domain, location_code)
            if urls:
                _complete({"frozen": False, "method": "dataforseo_site_probe", "indexed_urls": len(urls)})
                return

            homepage_live = await _homepage_is_live(website_url)
            if homepage_live or _recent_deindex_suspect(client_id):
                _complete(
                    {
                        "frozen": False,
                        "method": "dataforseo_site_probe",
                        "indexed_urls": 0,
                        "homepage_live": homepage_live,
                        "warned": False,
                    }
                )
                return

            notifications.emit(
                client_id,
                kind="freeze_suspect",
                title="Possible deindexing — verify",
                summary=(
                    f"A `site:{domain}` probe returned zero indexed pages and the homepage did not "
                    "respond. Check GSC for a manual action or deindexing; if confirmed, freeze the "
                    "client from its workspace."
                ),
                severity="warning",
                payload={"link": f"clients/{client_id}"},
            )
            _complete(
                {
                    "frozen": False,
                    "method": "dataforseo_site_probe",
                    "indexed_urls": 0,
                    "homepage_live": False,
                    "warned": True,
                }
            )
            return

        _complete({"skipped": "no_gsc_or_dataforseo"})
    except Exception as exc:
        logger.warning("freeze.check_failed", extra={"job_id": job_id, "client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
