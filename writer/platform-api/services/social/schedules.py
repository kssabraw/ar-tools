"""Social Media P3 — the cadence / recurrence engine (PRD §9).

One ``social_post_schedules`` row per (client, platform): a DST-correct recurring
cadence (weekly / biweekly / monthly). Clones the GBP-Posts pattern — the pure
``compute_next_run_at`` is reused verbatim and the sweep self-clocks ``next_run_at``.

What a due tick does (owner Q1 — auto-fill / drip, three-gated):
- **Drip** (all of ``social_auto_publish_enabled`` + the schedule's ``auto_fill`` + an
  explicitly ``queued`` draft + a target ``account_id``) → publish the oldest queued
  draft to the slot's account NOW (reuses ``publish_existing_draft``). Unattended publish.
- **Empty-queue nudge** (auto_fill on but nothing queued) → ``social_slot_empty``.
- **Suggest nudge** (auto_fill off / globally gated) → ``social_slot_due`` — a human
  assigns/approves a post; the Calendar shows the slot as a client-side ghost.

Frozen clients are skipped (output pauses under freeze). ``next_run_at`` advances
regardless so a skipped/failed slot never re-fires.

Pure helpers (``resolve_next_run``, ``decide_slot``) are unit-tested; the DB reads +
publish are the impure layer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from config import settings
from services import gbp_timezone
from services.gbp_posts_service import compute_next_run_at

logger = logging.getLogger(__name__)

_VALID_CADENCES = {"disabled", "weekly", "biweekly", "monthly"}


def _assert_enabled() -> None:
    if not settings.social_enabled:
        raise HTTPException(status_code=503, detail="social_not_enabled")


def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except ValueError:
        return None


# ── pure decision helpers (unit-tested) ──────────────────────────────────────

def decide_slot(
    auto_fill: bool,
    global_enabled: bool,
    has_account: bool,
    has_queued_draft: bool,
) -> str:
    """What a due slot should do. Pure:
    ``drip`` — publish a queued draft (all three gates hold);
    ``empty`` — auto-fill wanted but the queue is empty / no account → nudge to queue one;
    ``suggest`` — auto-fill off or globally gated → remind a human.
    """
    if auto_fill and global_enabled and has_account:
        return "drip" if has_queued_draft else "empty"
    return "suggest"


def resolve_next_run(
    now: datetime, cadence: str, day_of_week: Optional[int],
    day_of_month: Optional[int], hour_local: int, tz: Optional[str],
    prev: Optional[datetime] = None,
) -> Optional[datetime]:
    """Next fire time (reuses the GBP DST-correct helper). Pure passthrough kept here
    so the module has one cadence entrypoint."""
    return compute_next_run_at(now, cadence, day_of_week, day_of_month, hour_local, prev=prev, tz=tz)


# ── read / write ─────────────────────────────────────────────────────────────

_SELECT = ("id, platform, account_id, cadence, day_of_week, day_of_month, hour_local, "
           "is_active, auto_fill, next_run_at, last_run_at")


def get_schedules(client_id: str) -> dict:
    """The client's per-platform schedules + the client tz + whether the global
    auto-publish gate is on (so the UI can explain why auto_fill is/isn't live)."""
    rows = (
        _sb().table("social_post_schedules").select(_SELECT)
        .eq("client_id", client_id).order("platform").execute()
    ).data or []
    return {
        "timezone": gbp_timezone.resolve_client_timezone(client_id),
        "auto_publish_enabled": bool(settings.social_auto_publish_enabled),
        "schedules": rows,
    }


def upsert_schedule(client_id: str, req: dict, user_id: Optional[str]) -> dict:
    """Create/replace one platform's schedule. Recomputes next_run_at (DST-correct)."""
    _assert_enabled()
    platform = (req.get("platform") or "").lower().strip()
    if not platform:
        raise HTTPException(status_code=422, detail="social_schedule_platform_required")
    cadence = req.get("cadence") or "disabled"
    if cadence not in _VALID_CADENCES:
        raise HTTPException(status_code=400, detail="invalid_cadence")
    hour_local = int(req.get("hour_local", 9))
    day_of_week = req.get("day_of_week")
    day_of_month = req.get("day_of_month")
    if cadence in ("weekly", "biweekly") and day_of_week is None:
        day_of_week = 0
    if cadence == "monthly" and day_of_month is None:
        day_of_month = 1
    # Range-guard the fields compute_next_run_at feeds to datetime.replace(): an
    # out-of-range hour (≥24) or day-of-month (≥29, which .replace(day=) rejects in
    # short months) would raise ValueError → a 500 here, and a day_of_month=31 stored
    # in a 31-day month would later poison the sweep in a 30-day month. Reject at the
    # edge (the frontend already caps these; this defends the API).
    if not (0 <= hour_local <= 23):
        raise HTTPException(status_code=422, detail="social_schedule_invalid_hour")
    if day_of_week is not None and not (0 <= int(day_of_week) <= 6):
        raise HTTPException(status_code=422, detail="social_schedule_invalid_day")
    if day_of_month is not None and not (1 <= int(day_of_month) <= 28):
        raise HTTPException(status_code=422, detail="social_schedule_invalid_day")
    is_active = bool(req.get("is_active", True))
    auto_fill = bool(req.get("auto_fill", False))
    account_id = req.get("account_id") or None
    now = datetime.now(timezone.utc)
    tz = gbp_timezone.resolve_client_timezone(client_id)
    next_run = resolve_next_run(now, cadence, day_of_week, day_of_month, hour_local, tz)
    next_run_iso = next_run.isoformat() if (next_run and is_active and cadence != "disabled") else None
    row = {
        "client_id": client_id, "platform": platform, "account_id": account_id,
        "cadence": cadence, "day_of_week": day_of_week, "day_of_month": day_of_month,
        "hour_local": hour_local, "is_active": is_active, "auto_fill": auto_fill,
        "next_run_at": next_run_iso, "created_by": user_id, "updated_at": "now()",
    }
    _sb().table("social_post_schedules").upsert(row, on_conflict="client_id,platform").execute()
    return get_schedules(client_id)


def delete_schedule(client_id: str, platform: str) -> dict:
    """Remove a platform's schedule entirely (stops the cadence for that platform)."""
    _assert_enabled()
    _sb().table("social_post_schedules").delete() \
        .eq("client_id", client_id).eq("platform", (platform or "").lower()).execute()
    return get_schedules(client_id)


# ── the per-tick sweep ───────────────────────────────────────────────────────

def enqueue_due_social_schedules() -> int:
    """Per-tick sweep: for each active, due (next_run_at ≤ now) schedule, fire the slot
    (drip / empty-nudge / suggest-nudge per ``decide_slot``) and advance next_run_at.
    Skips frozen clients. No-op until the module is enabled. Returns the fired count."""
    if not settings.social_enabled:
        return 0
    from services import notifications
    from services.freeze import is_frozen
    from services.social import fanout

    now = datetime.now(timezone.utc)
    due = (
        _sb().table("social_post_schedules")
        .select("client_id, platform, account_id, cadence, day_of_week, day_of_month, "
                "hour_local, auto_fill, next_run_at")
        .eq("is_active", True).neq("cadence", "disabled")
        .lte("next_run_at", now.isoformat()).execute().data or []
    )
    fired = 0
    for sched in due:
        cid, platform = sched["client_id"], sched["platform"]
        # Advance the clock FIRST (self-clocked) so a failure below can't re-fire this slot.
        prev = _parse_dt(sched.get("next_run_at"))
        tz = gbp_timezone.resolve_client_timezone(cid)
        try:
            next_run = resolve_next_run(
                now, sched["cadence"], sched.get("day_of_week"),
                sched.get("day_of_month"), sched["hour_local"], tz, prev=prev,
            )
        except Exception as exc:  # noqa: BLE001 — a bad-config row must never sink the tick
            # An un-computable next-run (e.g. a legacy/hand-edited day_of_month=31 row) would
            # otherwise raise here and abort every remaining due schedule this tick. Deactivate
            # the poison row so it drops out of the due query, and move on.
            logger.warning("social.schedule_next_run_failed",
                           extra={"client_id": cid, "platform": platform, "error": str(exc)[:200]})
            try:
                _sb().table("social_post_schedules").update(
                    {"is_active": False, "next_run_at": None, "updated_at": "now()"}
                ).eq("client_id", cid).eq("platform", platform).execute()
            except Exception:  # noqa: BLE001 — best-effort deactivation
                logger.warning("social.schedule_deactivate_failed",
                               extra={"client_id": cid, "platform": platform})
            continue
        _sb().table("social_post_schedules").update({
            "last_run_at": now.isoformat(),
            "next_run_at": next_run.isoformat() if next_run else None,
        }).eq("client_id", cid).eq("platform", platform).execute()

        if is_frozen(cid):
            continue
        try:
            _fire_slot(cid, sched, now, notifications, fanout)
            fired += 1
        except Exception as exc:  # noqa: BLE001 — one schedule never sinks the sweep
            logger.warning("social.schedule_fire_failed",
                           extra={"client_id": cid, "platform": platform,
                                  "error": str(getattr(exc, "detail", exc))[:200]})
    if fired:
        logger.info("social.schedules_fired", extra={"count": fired})
    return fired


def _fire_slot(client_id: str, sched: dict, now: datetime, notifications, fanout) -> None:
    """Execute one due slot (see ``decide_slot``)."""
    platform = sched["platform"]
    account_id = sched.get("account_id")
    day = now.date().isoformat()
    queued = (
        fanout.next_queued_draft(client_id, platform)
        if (sched.get("auto_fill") and settings.social_auto_publish_enabled and account_id)
        else None
    )
    action = decide_slot(
        bool(sched.get("auto_fill")), bool(settings.social_auto_publish_enabled),
        bool(account_id), bool(queued),
    )
    if action == "drip":
        fanout.publish_existing_draft(str(queued["id"]), str(account_id))  # publish now
        notifications.emit(
            client_id, "social_slot_published", f"Auto-posted to {platform.title()}",
            summary=f"Dripped a queued draft to your {platform} cadence slot.",
            severity="info", payload={"platform": platform, "draft_id": queued["id"]},
        )
    elif action == "empty":
        notifications.emit(
            client_id, "social_slot_empty",
            f"{platform.title()} slot fired with no queued draft",
            summary=(f"Your {platform} cadence slot came due but no approved draft was "
                     "queued. Approve one into the queue to keep the rhythm."),
            severity="warning", payload={"platform": platform},
            dedupe_key=f"social_slot_empty:{client_id}:{platform}:{day}",
        )
    else:  # suggest
        notifications.emit(
            client_id, "social_slot_due", f"Time to post to {platform.title()}",
            summary=f"Your {platform} cadence slot is due — assign or approve a post.",
            severity="info", payload={"platform": platform},
            dedupe_key=f"social_slot_due:{client_id}:{platform}:{day}",
        )
