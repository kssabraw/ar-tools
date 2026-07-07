"""Citation liveness — the offpage agent's "citation status" check
(Organic Rank Drop SOP §A.8 "citations still live"; _ORCHESTRATOR.md §Agents).

The team pastes each client's citation URLs (from the vendor's deliverables)
into `client_citations`; a weekly sweep fetches every citation and records its
state. Only a **hard** death counts — 404/410/451 or a DNS/connection failure,
and only after two consecutive failing checks (directories flake). Bot-blocks
(403/429/503) record as `blocked` and count as alive: a directory refusing our
fetcher says nothing about what Google sees (fail-open by design).

Newly-dead citations open a `citation_loss` offpage alert (episode semantics —
one open per client; auto-resolves when no dead citations remain), a warning
notification, and an Action Plan action ("fix or reorder the dead listings").
NAP *consistency* stays with the external Citation Audit tool — this is
liveness only; the sweep records a best-effort `nap_found` (business name seen
in the HTML) as advisory context, never as an alert trigger.

Pure helpers (`classify_fetch`, `next_status`) are unit-tested without I/O.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase
from services import notifications

logger = logging.getLogger(__name__)

CHECK_INTERVAL_DAYS = 7
DEAD_AFTER_FAILURES = 2        # consecutive hard failures before a citation is dead
_DEAD_HTTP = {404, 410, 451}
_BLOCKED_HTTP = {401, 403, 405, 406, 429, 503}
_CONCURRENCY = 5
_FETCH_TIMEOUT = 20.0
_UA = "Mozilla/5.0 (compatible; ARTools-CitationCheck/1.0)"


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested)
# ─────────────────────────────────────────────────────────────────────────────
def classify_fetch(http_status: Optional[int], fetch_error: bool) -> str:
    """One fetch's verdict: 'ok' | 'hard_fail' | 'blocked'. Pure.

    Only hard failures can kill a citation; anything ambiguous is 'blocked'
    (alive for alerting). A network error is a hard failure — the host is
    unreachable, which is what a dead citation looks like."""
    if fetch_error:
        return "hard_fail"
    if http_status is None:
        return "blocked"
    if 200 <= http_status < 400:
        return "ok"
    if http_status in _DEAD_HTTP:
        return "hard_fail"
    if http_status in _BLOCKED_HTTP:
        return "blocked"
    # Other 4xx/5xx: ambiguous server trouble — don't kill on it.
    return "blocked"


def next_status(verdict: str, consecutive_failures: int) -> tuple[str, int]:
    """(new_status, new_consecutive_failures) from a fetch verdict. Pure.

    'dead' requires DEAD_AFTER_FAILURES consecutive hard failures; an 'ok'
    resets the counter; 'blocked' neither kills nor heals the counter."""
    if verdict == "ok":
        return "live", 0
    if verdict == "hard_fail":
        failures = consecutive_failures + 1
        return ("dead" if failures >= DEAD_AFTER_FAILURES else "unknown"), failures
    return "blocked", consecutive_failures


# ─────────────────────────────────────────────────────────────────────────────
# The check job
# ─────────────────────────────────────────────────────────────────────────────
async def _fetch_one(client: httpx.AsyncClient, url: str, business_name: Optional[str]) -> dict:
    try:
        resp = await client.get(url, follow_redirects=True, headers={"User-Agent": _UA})
        nap_found = None
        if business_name and resp.status_code < 400:
            try:
                nap_found = business_name.lower() in resp.text.lower()
            except Exception:
                nap_found = None
        return {"http_status": resp.status_code, "fetch_error": False, "nap_found": nap_found}
    except Exception:
        return {"http_status": None, "fetch_error": True, "nap_found": None}


async def run_citation_check_job(job: dict) -> None:
    """Check every citation for one client; open/resolve the citation_loss
    alert from the resulting dead set."""
    supabase = get_supabase()
    job_id = job["id"]
    client_id = (job.get("payload") or {}).get("client_id") or job.get("entity_id")
    try:
        client_row = (
            supabase.table("clients").select("name").eq("id", client_id).single().execute()
        ).data or {}
        citations = (
            supabase.table("client_citations").select("*").eq("client_id", client_id).execute()
        ).data or []

        now = datetime.now(timezone.utc).isoformat()
        newly_dead: list[str] = []
        sem = asyncio.Semaphore(_CONCURRENCY)
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as http:

            async def _check(c: dict) -> None:
                nonlocal newly_dead
                async with sem:
                    result = await _fetch_one(http, c["url"], client_row.get("name"))
                verdict = classify_fetch(result["http_status"], result["fetch_error"])
                status, failures = next_status(verdict, c.get("consecutive_failures") or 0)
                updates = {
                    "status": status,
                    "consecutive_failures": failures,
                    "http_status": result["http_status"],
                    "last_checked_at": now,
                }
                if result["nap_found"] is not None:
                    updates["nap_found"] = result["nap_found"]
                if status == "live":
                    updates["last_ok_at"] = now
                supabase.table("client_citations").update(updates).eq("id", c["id"]).execute()
                if status == "dead" and c.get("status") != "dead":
                    newly_dead.append(c["url"])

            await asyncio.gather(*(_check(c) for c in citations))

        dead_count = (
            supabase.table("client_citations")
            .select("id", count="exact")
            .eq("client_id", client_id)
            .eq("status", "dead")
            .execute()
        ).count or 0

        _sync_citation_alert(supabase, client_id, dead_count, newly_dead)

        supabase.table("async_jobs").update(
            {
                "status": "complete",
                "result": {"checked": len(citations), "dead": dead_count, "newly_dead": len(newly_dead)},
                "completed_at": "now()",
            }
        ).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("citation_check.failed", extra={"job_id": job_id, "client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def _sync_citation_alert(supabase, client_id: str, dead_count: int, newly_dead: list[str]) -> None:
    """Open a citation_loss alert when citations are dead; resolve it when none
    remain. Episode semantics — one open alert per client."""
    open_alert = (
        supabase.table("offpage_alerts")
        .select("id")
        .eq("client_id", client_id)
        .eq("alert_type", "citation_loss")
        .is_("resolved_at", "null")
        .limit(1)
        .execute()
    ).data or []

    if dead_count == 0:
        if open_alert:
            supabase.table("offpage_alerts").update({"resolved_at": "now()"}).eq(
                "id", open_alert[0]["id"]
            ).execute()
        return

    if open_alert:
        return  # already alerted; the weekly sweep keeps the citation rows fresh

    message = f"{dead_count} citation{'s' if dead_count != 1 else ''} no longer resolve."
    supabase.table("offpage_alerts").insert(
        {
            "client_id": client_id,
            "alert_type": "citation_loss",
            "message": message,
            "details": {"dead_count": dead_count, "newly_dead": newly_dead[:20]},
        }
    ).execute()
    try:  # refresh the Action Plan silently so the re-order action shows now
        from services.reopt_planner import enqueue_reopt_plan

        enqueue_reopt_plan(client_id, trigger="offpage")
    except Exception:
        logger.warning("citation_check.plan_refresh_enqueue_failed", extra={"client_id": client_id})
    notifications.emit(
        client_id,
        kind="offpage_citation_loss",
        title="Dead citations found",
        summary=message + " Fix or reorder the dead listings (citations are in the monthly "
        "baseline stack — Minda owns them).",
        severity="warning",
        payload={"link": f"clients/{client_id}/citations"},
    )


def enqueue_due_citation_checks() -> int:
    """Daily due-check: enqueue one citation_check per client whose citations
    haven't been checked in CHECK_INTERVAL_DAYS (or ever)."""
    if not settings.citation_check_enabled:
        return 0
    supabase = get_supabase()
    try:
        rows = (
            supabase.table("client_citations").select("client_id, last_checked_at").execute()
        ).data or []
    except Exception as exc:
        logger.error("citation_check.enqueue_read_failed", extra={"error": str(exc)})
        return 0
    if not rows:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=CHECK_INTERVAL_DAYS)
    due: set[str] = set()
    latest: dict[str, Optional[str]] = {}
    for r in rows:
        cid = r["client_id"]
        ts = r.get("last_checked_at")
        if cid not in latest or (ts or "") > (latest[cid] or ""):
            latest[cid] = ts
    for cid, ts in latest.items():
        if ts is None or datetime.fromisoformat(ts.replace("Z", "+00:00")) <= cutoff:
            due.add(cid)
    if not due:
        return 0

    try:
        pending = (
            supabase.table("async_jobs")
            .select("entity_id")
            .eq("job_type", "citation_check")
            .in_("status", ["pending", "running"])
            .execute()
        ).data or []
        queued = {p.get("entity_id") for p in pending}
    except Exception:
        queued = set()

    count = 0
    for cid in sorted(due - queued):
        try:
            supabase.table("async_jobs").insert(
                {"job_type": "citation_check", "entity_id": cid, "payload": {"client_id": cid}}
            ).execute()
            count += 1
        except Exception as exc:
            logger.error("citation_check.enqueue_failed", extra={"client_id": cid, "error": str(exc)})
    if count:
        logger.info("citation_check.enqueued", extra={"count": count})
    return count
