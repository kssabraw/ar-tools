"""GSC connection-health watch: auto-recover ``no_access`` properties + alert.

Organic Rank Tracker (Module #4), M2. A GSC property that returns 403 flips to
``access_status='no_access'`` (``gsc_ingest``), and the daily scheduler only
enqueues ``ok`` properties (``gsc_scheduler.enqueue_due_ingests``) — so once a
property loses access it is **never retried**, and a successful ingest does not
flip it back (unlike GBP metrics, which self-heals on a *manual* re-sync but has
the same automatic-recovery gap). The result: after a transient blip OR a real
permission removal, GSC collection stops for that property indefinitely and only
a human clicking "Verify" in Rankings → Settings brings it back.

Worse, the two existing dead-man's switches both go blind in exactly this case:

  * ``scan_health`` alerts on a *streak of failed jobs* — but once the property
    flips to ``no_access`` the scheduler stops enqueuing it, so no more failed
    ``gsc_ingest`` rows accrue and the streak can't grow.
  * ``rank_freshness`` alerts on stale *client rank data* — but a client with the
    DataForSEO fallback keeps fresh ``tracked_rank`` data, so the client looks
    healthy while its GSC-only signals (clicks / impressions / GSC position)
    silently die.

This closes both gaps with one daily, best-effort sweep keyed on ``access_status``
itself (which neither existing sweep watches):

  1. **Self-heal.** Re-verify each ``no_access`` property with one live GSC test
     query. A property whose access has returned flips back to ``ok`` and an
     immediate back-fill ingest is queued (the daily enqueue already ran this
     tick, so we can't wait for it) — the automatic recovery GBP/GSC both lacked.
  2. **Alert.** A property still denied emits ONE ``gsc_access`` notification
     (deduped per ISO week so an unresolved outage re-nudges weekly, not daily)
     naming the client + the exact remedy, plus a recovery note when it flips
     back.

The live verify is a blocking Google call, so the scheduler runs this sweep off
the event loop (``asyncio.to_thread``) — see the event-loop-safety lesson in
``gsc_ingest`` / PR #1179. Pure helpers (``access_episode_key`` /
``build_access_digest``) are unit-tested; the sweep never raises into the loop.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import gsc_service, notifications

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def access_episode_key(property_id: str, now: datetime) -> str:
    """Dedupe key for one still-denied GSC property. The ISO-week suffix lets an
    unresolved outage re-nudge at most once a week rather than every daily sweep;
    once the property recovers it leaves the sweep (access_status='ok'), so a
    later re-break naturally starts a fresh week's alert. Pure."""
    year, week, _ = now.isocalendar()
    return f"gsc_access:{property_id}:{year}W{week:02d}"


def build_access_digest(
    client_name: str,
    site_url: str,
    sa_email: Optional[str],
    days_frozen: Optional[int],
    critical_days: int,
) -> dict:
    """A ``{title, summary, severity}`` digest for one property that has lost GSC
    access. Escalates to ``critical`` once the blackout has run ``critical_days``.
    Pure — the notification copy."""
    who = sa_email or "the service-account email shown in Rankings → Settings"
    if days_frozen is not None and days_frozen > 0:
        frozen = (
            f" GSC clicks, impressions and organic positions for this client have "
            f"not updated in {days_frozen} day{'s' if days_frozen != 1 else ''}."
        )
    else:
        frozen = (
            " GSC clicks, impressions and organic positions for this client have "
            "stopped updating."
        )
    severity = (
        "critical"
        if (days_frozen is not None and days_frozen >= critical_days)
        else "warning"
    )
    title = f"Google Search Console access lost for {client_name}"
    summary = (
        f"The rank tracker can no longer read {site_url} from Search Console "
        f"(HTTP 403 — the service account is not an authorized user on the "
        f"property).{frozen} "
        f"Fix: add {who} as a user on the property in Google Search Console, then "
        f"open Rankings → Settings and click Verify — it recovers automatically "
        f"within a day once access is restored. "
        f"(DataForSEO rank tracking, if configured, keeps running, so the client's "
        f"overall rank data can look current while its GSC half is dark.)"
    )
    return {"title": title, "summary": summary, "severity": severity}


# ----------------------------------------------------------------------------
# Sweep (I/O) — best-effort, never raises into the scheduler.
# ----------------------------------------------------------------------------
def _client_names(supabase, client_ids: list[str]) -> dict[str, str]:
    if not client_ids:
        return {}
    try:
        rows = (
            supabase.table("clients").select("id, name").in_("id", client_ids).execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("gsc_access.client_names_failed", extra={"error": str(exc)})
        return {}
    return {r["id"]: r.get("name") or "Unknown client" for r in rows}


def _days_since_data(supabase, property_id: str, today: date) -> Optional[int]:
    """Days since the property's freshest ``gsc_query_daily`` row, or None. One
    top-1 read; best-effort."""
    try:
        rows = (
            supabase.table("gsc_query_daily")
            .select("date")
            .eq("property_id", property_id)
            .order("date", desc=True)
            .limit(1)
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "gsc_access.freshness_read_failed",
            extra={"property_id": property_id, "error": str(exc)},
        )
        return None
    if not rows:
        return None
    raw = rows[0].get("date")
    try:
        return max(0, (today - date.fromisoformat(str(raw)[:10])).days) if raw else None
    except ValueError:
        return None


def run_gsc_access_sweep() -> dict:
    """Daily: re-verify every ``no_access`` GSC property (self-heal on recovery)
    and alert on each one still denied. Runs a blocking Google test query per
    stuck property, so the scheduler calls it off the event loop. Best-effort —
    never raises into the loop."""
    if not settings.gsc_access_monitor_enabled:
        return {"skipped": "disabled"}
    if not settings.google_service_account_key:
        # No service account configured → verify can't succeed for anyone; a blanket
        # "GSC access lost" alert would be misleading noise, so stay silent.
        return {"skipped": "no_service_account"}

    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    today = now.date()

    try:
        props = (
            supabase.table("gsc_properties")
            .select("id, client_id, site_url, property_type, access_status")
            .eq("access_status", "no_access")
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        logger.error("gsc_access.property_read_failed", extra={"error": str(exc)})
        return {"error": str(exc)}
    if not props:
        return {"checked": 0, "recovered": 0, "alerted": 0}

    names = _client_names(supabase, sorted({p["client_id"] for p in props if p.get("client_id")}))
    try:
        sa_email = gsc_service.get_service_account_email()
    except Exception:  # noqa: BLE001 — key without client_email; fall back to generic text
        sa_email = None

    recovered = alerted = 0
    for prop in props:
        property_id = prop["id"]
        client_id = prop.get("client_id")
        site_url = prop.get("site_url") or ""
        client_name = names.get(client_id, "Unknown client")

        try:
            result = gsc_service.verify_property_access(site_url, prop.get("property_type"))
        except Exception as exc:  # noqa: BLE001 — one bad property must not abort the sweep
            logger.warning(
                "gsc_access.verify_failed",
                extra={"property_id": property_id, "error": str(exc)},
            )
            continue

        if result.status == "ok":
            # Access is back. Flip to ok (the scheduler resumes daily ingest) AND
            # queue an immediate back-fill — the daily enqueue already ran this tick.
            try:
                supabase.table("gsc_properties").update(
                    {"access_status": "ok", "last_verified_at": now.isoformat(),
                     "updated_at": now.isoformat()}
                ).eq("id", property_id).execute()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "gsc_access.recover_update_failed",
                    extra={"property_id": property_id, "error": str(exc)},
                )
                continue
            try:
                from services.gsc_ingest import enqueue_ingest

                enqueue_ingest(property_id)
            except Exception as exc:  # noqa: BLE001 — recovery still stands; daily tick catches up
                logger.warning(
                    "gsc_access.backfill_enqueue_failed",
                    extra={"property_id": property_id, "error": str(exc)},
                )
            notifications.emit(
                client_id=client_id,
                kind="gsc_access",
                title=f"Google Search Console access restored for {client_name}",
                summary=(
                    f"The service account can read {site_url} again; the rank tracker "
                    f"has resumed pulling GSC data (a back-fill is queued)."
                ),
                severity="info",
                payload={"link": f"clients/{client_id}/rankings" if client_id else "rankings",
                         "property_id": property_id, "state": "recovered"},
                dedupe_key=f"gsc_access_recovered:{property_id}:{today.isoformat()}",
            )
            recovered += 1
            logger.info("gsc_access.recovered", extra={"property_id": property_id})
        elif result.status == "no_access":
            days_frozen = _days_since_data(supabase, property_id, today)
            digest = build_access_digest(
                client_name, site_url, sa_email, days_frozen, settings.gsc_access_critical_days
            )
            notifications.emit(
                client_id=client_id,
                kind="gsc_access",
                title=digest["title"],
                summary=digest["summary"],
                severity=digest["severity"],
                payload={"link": f"clients/{client_id}/rankings" if client_id else "rankings",
                         "property_id": property_id, "site_url": site_url,
                         "days_frozen": days_frozen, "state": "lost"},
                dedupe_key=access_episode_key(property_id, now),
            )
            alerted += 1
        # result.status == "error" (key/network/config) → transient; leave the
        # property as-is and don't alert (would be noise on a config blip).

    if recovered or alerted:
        logger.info(
            "gsc_access.sweep_complete",
            extra={"checked": len(props), "recovered": recovered, "alerted": alerted},
        )
    return {"checked": len(props), "recovered": recovered, "alerted": alerted}
