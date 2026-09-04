"""GBP Profile Monitor — alert on a suspended listing or on out-of-band profile
changes (Google or an outside source editing the description / services / hours /
name / phone / website / address / categories / open-status).

A daily ``gbp_profile_monitor`` job reads each registered ``ok`` location (v1
``locations.get`` with the wider ``MONITOR_READ_MASK``), snapshots the monitored
fields, and compares against a stored baseline (``gbp_profile_snapshots``):

  * **Suspension / access loss** — Voice of Merchant flips to False, or the read
    fails with an access-lost code (404 / read-only / unverified). Transition-
    based (``ok`` → ``suspended``/``no_access``) so it alerts once, critical.
    A transient/quota/api-disabled read failure is skipped (never flips state).
  * **Out-of-band change** — a monitored field differs from the baseline. The
    baseline is the dedup: after alerting we advance it, so each distinct change
    alerts exactly once. The team's OWN applies advance the baseline
    (``note_own_edit``), so the monitor never flags an edit we made.

Alert-only (like ``freeze_check``): it never auto-freezes or auto-reverts — a
human triages. Reads are observation, so the monitor runs during a freeze.

Pure snapshot/diff/access helpers live in ``gbp_profile_api``; this layer owns
the job, the baseline store, and the alerts. See
docs/modules/gbp-profile-editor-prd-v1_0.md.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import gbp_profile_api as api
from services import gbp_profile_service as svc

logger = logging.getLogger(__name__)

_SNAP_COLUMNS = "location_row_id, client_id, snapshot, access_status, checked_at, last_change, last_change_at"


def is_enabled() -> bool:
    """The monitor rides on the module being enabled AND its own flag."""
    return bool(svc.is_enabled() and settings.gbp_profile_monitor_enabled)


# ───────────────────────────────────────────────────────────────────────────
# Baseline store
# ───────────────────────────────────────────────────────────────────────────
def _get_baseline(location_row_id: str) -> Optional[dict]:
    res = (
        get_supabase().table("gbp_profile_snapshots").select(_SNAP_COLUMNS)
        .eq("location_row_id", location_row_id).limit(1).execute()
    )
    return res.data[0] if res.data else None


def _upsert_baseline(row: dict) -> None:
    row = {**row, "updated_at": "now()"}
    get_supabase().table("gbp_profile_snapshots").upsert(row, on_conflict="location_row_id").execute()


def get_monitor_status(client_id: str, location_row_id: str) -> dict:
    """The monitor state for one location (for the UI). ``monitored`` is False
    until the first check establishes a baseline."""
    svc._assert_enabled()
    svc._location(location_row_id, client_id)  # ownership check (404 if not this client's)
    base = _get_baseline(location_row_id)
    if not base:
        return {"monitored": False, "enabled": is_enabled()}
    return {
        "monitored": True,
        "enabled": is_enabled(),
        "access_status": base.get("access_status"),
        "checked_at": base.get("checked_at"),
        "last_change": base.get("last_change"),
        "last_change_at": base.get("last_change_at"),
    }


# ───────────────────────────────────────────────────────────────────────────
# Our own applies advance the baseline (so the monitor never flags them)
# ───────────────────────────────────────────────────────────────────────────
async def refresh_baseline(location_row_id: str, client_id: str, field: str) -> None:
    """Best-effort: after WE apply an edit to ``field`` and it goes live, advance
    ONLY that field in the monitor baseline to its current live value, so the next
    check doesn't flag our own change.

    Re-reading the live value (rather than storing the proposed value) keeps the
    baseline and future checks in the SAME shape, avoiding a representation-
    mismatch false positive on hours/services. Updating only the applied field
    (not the whole snapshot) means a concurrent OUTSIDE change to a different
    field is still caught by the next daily check — a full-snapshot refresh would
    silently swallow it. No-op if no baseline exists yet (the first monitor run
    captures the post-apply state). Called from the apply/reconciler ``applied``
    branch — never raises."""
    if not is_enabled() or field not in api.MONITOR_FIELDS:
        return
    try:
        base = _get_baseline(location_row_id)
        if not base:
            return
        location = svc._location(location_row_id, client_id)
        loc = await asyncio.to_thread(api.get_location, svc._location_name(location), api.MONITOR_READ_MASK)
        snap = api.monitor_snapshot(loc)
        snapshot = dict(base.get("snapshot") or {})
        snapshot[field] = snap.get(field)
        get_supabase().table("gbp_profile_snapshots").update({
            "snapshot": snapshot,
            "access_status": api.snapshot_access_status(snap),
            "checked_at": "now()", "updated_at": "now()",
        }).eq("location_row_id", location_row_id).execute()
    except Exception as exc:  # noqa: BLE001 — best-effort, never breaks apply
        logger.info("gbp_monitor.refresh_baseline_failed", extra={"error": str(exc)[:200]})


# ───────────────────────────────────────────────────────────────────────────
# Enqueue (daily) + on-demand
# ───────────────────────────────────────────────────────────────────────────
def _pending_location_ids() -> set:
    rows = (
        get_supabase().table("async_jobs").select("payload")
        .eq("job_type", "gbp_profile_monitor").in_("status", ["pending", "running"])
        .execute().data or []
    )
    return {(r.get("payload") or {}).get("location_row_id") for r in rows}


def enqueue_due_gbp_profile_monitor() -> int:
    """Enqueue one ``gbp_profile_monitor`` job per registered ``ok`` location,
    daily. Skips a location that already has a pending/running check. No-op until
    the module + monitor flag are enabled."""
    if not is_enabled():
        return 0
    supabase = get_supabase()
    try:
        locs = (
            supabase.table("gbp_locations").select("id, client_id")
            .eq("access_status", "ok").execute().data or []
        )
        queued = _pending_location_ids()
    except Exception as exc:  # noqa: BLE001
        logger.error("gbp_monitor.enqueue_query_failed", extra={"error": str(exc)})
        return 0

    count = 0
    for loc in locs:
        if loc["id"] in queued:
            continue
        try:
            supabase.table("async_jobs").insert(
                {"job_type": "gbp_profile_monitor", "entity_id": loc["client_id"],
                 "payload": {"client_id": loc["client_id"], "location_row_id": loc["id"]}}
            ).execute()
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("gbp_monitor.enqueue_failed", extra={"location_row_id": loc["id"], "error": str(exc)})
    if count:
        logger.info("gbp_monitor.checks_enqueued", extra={"count": count})
    return count


def enqueue_check(client_id: str, location_row_id: str) -> str:
    """On-demand 'Check now' — enqueue one monitor check for a location."""
    svc._assert_enabled()
    location = svc._location(location_row_id, client_id)
    res = (
        get_supabase().table("async_jobs")
        .insert({"job_type": "gbp_profile_monitor", "entity_id": client_id,
                 "payload": {"client_id": client_id, "location_row_id": location["id"]}})
        .execute()
    )
    return res.data[0]["id"]


# ───────────────────────────────────────────────────────────────────────────
# The check
# ───────────────────────────────────────────────────────────────────────────
def _link(client_id: str) -> str:
    return f"clients/{client_id}/gbp?tab=profile"


def _notify(client_id: str, kind: str, title: str, summary: str, severity: str, location_row_id: str) -> None:
    try:
        from services import notifications  # lazy

        notifications.emit(
            client_id, kind, title, summary=summary, severity=severity,
            payload={"link": _link(client_id), "location_row_id": location_row_id},
        )
    except Exception as exc:  # noqa: BLE001 — alert is best-effort
        logger.info("gbp_monitor.notify_failed", extra={"error": str(exc)[:200]})


async def run_monitor_job(job: dict) -> None:
    """Handler for job_type='gbp_profile_monitor'. Reads one location, diffs
    against its baseline, and alerts on a suspension/access-loss transition or an
    out-of-band field change, then advances the baseline. Never auto-remediates."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    location_row_id = payload.get("location_row_id")
    supabase = get_supabase()

    def _complete(result: dict) -> None:
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()

    try:
        if not is_enabled():
            _complete({"skipped": "not_enabled"})
            return
        location = svc._location(location_row_id, client_id)
        name = svc._location_name(location)
        base = _get_baseline(location_row_id)
        client_name = svc._client(client_id).get("name") or "Client"

        # Read live; a classified access-lost failure is a suspension signal,
        # a transient one is skipped (never flips state).
        try:
            loc = await asyncio.to_thread(api.get_location, name, api.MONITOR_READ_MASK)
        except HTTPException as exc:
            access = api.access_status_for_code(str(exc.detail or ""))
            if access is None:
                _complete({"skipped": "transient_read_error", "detail": str(exc.detail)})
                return
            _handle_access(base, access, client_id, location_row_id, client_name, supabase, snapshot=None)
            _complete({"access_status": access, "read_failed": True})
            return

        snap = api.monitor_snapshot(loc)
        access = api.snapshot_access_status(snap)  # 'ok' | 'suspended'

        if access != "ok":
            _handle_access(base, access, client_id, location_row_id, client_name, supabase, snapshot=snap)
            _complete({"access_status": access})
            return

        # access ok — recovery + content-change detection.
        prev_access = (base or {}).get("access_status") or "ok"
        recovered = base is not None and prev_access != "ok"
        changes = api.diff_snapshot(base["snapshot"], snap) if base else []

        upsert = {
            "location_row_id": location_row_id, "client_id": client_id,
            "snapshot": snap, "access_status": "ok", "checked_at": "now()",
        }
        if base is None:
            _upsert_baseline(upsert)  # first run — establish baseline, no content alert
            _complete({"baseline_established": True})
            return

        if recovered:
            _notify(client_id, "gbp_profile_restored", "GBP access restored",
                    f"{client_name}'s Google Business Profile is verified/accessible again.",
                    "info", location_row_id)
        if changes:
            fields = ", ".join(c["label"] for c in changes)
            _notify(
                client_id, "gbp_profile_changed", "GBP profile changed outside the tool",
                f"{client_name}'s Google Business Profile {fields} changed — a change we didn't make "
                "(Google or an outside source). Review it in the Profile editor.",
                "warning", location_row_id,
            )
            upsert["last_change"] = {"fields": [c["field"] for c in changes]}
            upsert["last_change_at"] = "now()"
        _upsert_baseline(upsert)
        _complete({"access_status": "ok", "changed_fields": [c["field"] for c in changes], "recovered": recovered})
        logger.info("gbp_monitor.checked", extra={
            "location_row_id": location_row_id, "changes": len(changes), "recovered": recovered})
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("gbp_monitor.check_failed", extra={"location_row_id": location_row_id, "error": str(detail)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()


def _handle_access(base: Optional[dict], access: str, client_id: str, location_row_id: str,
                   client_name: str, supabase, snapshot: Optional[dict]) -> None:
    """Record an access state (suspended/no_access) and alert on a transition
    from ok (or on the first observation). Keeps the last-known-good snapshot so a
    later recovery can still diff."""
    prev_access = (base or {}).get("access_status") or "ok"
    upsert: dict = {
        "location_row_id": location_row_id, "client_id": client_id,
        "access_status": access, "checked_at": "now()",
    }
    # Keep an existing snapshot; on first-ever observation store what we have.
    if base is not None:
        upsert["snapshot"] = base.get("snapshot") or (snapshot or {})
    else:
        upsert["snapshot"] = snapshot or {}
    _upsert_baseline(upsert)

    if prev_access == "ok":  # transition ok → not-ok (or first observation is not-ok)
        if access == "suspended":
            summary = (f"{client_name}'s Google Business Profile appears SUSPENDED — Google reports the "
                       "listing is no longer verified (Voice of Merchant lost). Check the GBP dashboard.")
        else:  # no_access
            summary = (f"{client_name}'s Google Business Profile can no longer be read by our connected "
                       "account (removed, unverified, or access revoked). Check the GBP dashboard / connection.")
        _notify(client_id, "gbp_profile_suspended", "GBP listing suspended / access lost", summary,
                "critical", location_row_id)
