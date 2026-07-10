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
  * **Automatic** — the daily ``freeze_check`` job inspects the client's
    homepage through the GSC **URL Inspection API** (authoritative). A homepage
    whose verdict says not-indexed → **deindexing freeze**. Clients without a
    verified GSC property get a best-effort DataForSEO ``site:`` probe instead;
    zero indexed results raises a *warning notification only* — never an
    auto-freeze on circumstantial evidence (the SOP freezes on *confirmed*
    occurrences).

Pure helpers (`should_auto_freeze`, `job_client_id`) are unit-tested without a DB.
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


def should_auto_freeze(index_status: str, coverage_state: Optional[str]) -> bool:
    """Whether a homepage URL-Inspection read justifies an automatic deindexing
    freeze. Only a hard not-indexed verdict qualifies; 'unknown' (API hiccup,
    missing verdict) must never freeze a client. Pure."""
    if index_status != "not_indexed":
        return False
    # "Excluded by 'noindex'" / "Page with redirect" etc. still mean the homepage
    # is out of the index — all FAIL/NEUTRAL verdicts count. coverage_state is
    # recorded as evidence, not used to overrule the verdict.
    return True


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
            homepage = website_url if website_url.endswith("/") else website_url + "/"
            inspection = await asyncio.to_thread(gsc_service.inspect_url, prop["site_url"], homepage)
            index_status = gsc_service.classify_index_status(inspection.get("verdict"))
            coverage = inspection.get("coverage_state")
            if should_auto_freeze(index_status, coverage):
                freeze_client(
                    client_id,
                    "deindexing",
                    source="freeze_check",
                    details={
                        "method": "gsc_url_inspection",
                        "homepage": homepage,
                        "verdict": inspection.get("verdict"),
                        "coverage_state": coverage,
                    },
                )
                _complete({"frozen": True, "method": "gsc_url_inspection", "index_status": index_status})
            else:
                _complete({"frozen": False, "method": "gsc_url_inspection", "index_status": index_status})
            return

        # No verified GSC property — best-effort site: probe, warn-only.
        if settings.dataforseo_login and settings.dataforseo_password:
            domain = extract_domain(website_url)
            urls = await site_page_index._fetch_google_indexed_urls(
                domain, settings.dataforseo_default_location_code
            )
            if not urls:
                notifications.emit(
                    client_id,
                    kind="freeze_suspect",
                    title="Possible deindexing — verify",
                    summary=(
                        f"A `site:{domain}` probe returned zero indexed pages. Check GSC for a "
                        "manual action or deindexing; if confirmed, freeze the client from its workspace."
                    ),
                    severity="warning",
                    payload={"link": f"clients/{client_id}"},
                )
                _complete({"frozen": False, "method": "dataforseo_site_probe", "indexed_urls": 0, "warned": True})
            else:
                _complete({"frozen": False, "method": "dataforseo_site_probe", "indexed_urls": len(urls)})
            return

        _complete({"skipped": "no_gsc_or_dataforseo"})
    except Exception as exc:
        logger.warning("freeze.check_failed", extra={"job_id": job_id, "client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
