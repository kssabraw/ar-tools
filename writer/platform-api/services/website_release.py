"""Website Builder — the release (drip-publish) schedule.

Gives a website the cadence the other content-creator modules have: publish an
immediate batch, then release N more pages per day / week / month until the
content plan is exhausted. Owner ruling: each release GENERATES then PUBLISHES
the next planned posts just-in-time — so a schedule needs nothing generated up
front, and no page is committed before it is written.

Mechanically it reuses the existing pipeline rather than adding a new one: a
release enqueues the same `website_page_generate` job with a `publish_after`
flag, and generation auto-enqueues the publish on success. So there is no new
job type, no new generator, and each page still passes the same freeze and
quality gates it would if a human clicked Generate then Publish.

Two rules keep it correct:

* **A page is released exactly once.** Generation is slow, so a manual and a
  scheduled release could otherwise both pick a page in the window between "its
  generate job was enqueued" and "that job finished". `released_at` is the claim
  — a page with it set is out of the pool until it is cleared.
* **Posts publish before their pillar.** A pillar links down to its published
  cluster posts, so releasing posts first means the hub ships with its list
  already populated. Ordering only affects completeness, never correctness (the
  template's structural links self-heal on the next deploy), but the better
  order is free.

The pure helpers (batch selection, cadence math, advance decision) are
unit-tested; the impure half does the I/O.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# The drip acts on the informational content plan's pages. Local geo pages keep
# the manual generate/publish flow for now; extending the drip to them is a
# deliberate follow-up, not a silent widening.
RELEASE_PAGE_TYPES = frozenset({"post", "pillar"})

VALID_MODES = frozenset({"daily", "weekly", "monthly"})


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def is_releasable(page: dict) -> bool:
    """A planned content page that has not yet been released or published."""
    return (
        (page.get("page_type") or "") in RELEASE_PAGE_TYPES
        and (page.get("status") or "") != "published"
        and not page.get("released_at")
    )


def _order_key(page: dict) -> tuple:
    # Posts (0) before pillars (1), then the plan's own tier + route order, so a
    # release is deterministic and a pillar trails the posts it links to.
    is_pillar = 1 if (page.get("page_type") == "pillar") else 0
    return (is_pillar, page.get("tier") or 0, page.get("route") or "")


def select_batch(pages: Iterable[dict], count: int) -> list[dict]:
    """The next `count` releasable pages, in release order. Pure."""
    if count <= 0:
        return []
    releasable = sorted((p for p in pages if is_releasable(p)), key=_order_key)
    return releasable[:count]


def releasable_count(pages: Iterable[dict]) -> int:
    return sum(1 for p in pages if is_releasable(p))


def normalize_anchors(mode: str, weekday: Optional[int], day_of_month: Optional[int],
                      now: datetime) -> tuple[Optional[int], Optional[int]]:
    """Fill missing cadence anchors from the setup time. Pure.

    A weekly schedule with no weekday releases on the day it was set up; a
    monthly one with no day-of-month uses today's date (capped at 28, the last
    day every month has). Anchors are cleared for the mode that doesn't use them,
    so a stored row never carries a stale weekday from a mode switch.
    """
    if mode == "weekly":
        wd = weekday if weekday is not None else now.weekday()
        return int(wd) % 7, None
    if mode == "monthly":
        dom = day_of_month if day_of_month is not None else now.day
        return None, max(1, min(28, int(dom)))
    return None, None


def next_run_after(mode: str, weekday: Optional[int], day_of_month: Optional[int],
                   now: datetime) -> datetime:
    """The next cadence slot strictly after `now`, preserving its time of day. Pure.

    The shared scheduler ticks daily, so the slot fires at the first tick at or
    after it — sub-daily precision is neither offered nor implied.
    """
    if mode == "weekly":
        target = (weekday if weekday is not None else now.weekday()) % 7
        days = (target - now.weekday()) % 7 or 7
        return now + timedelta(days=days)
    if mode == "monthly":
        dom = max(1, min(28, day_of_month if day_of_month is not None else now.day))
        candidate = now.replace(day=dom)
        if candidate > now:
            return candidate
        year = now.year + (1 if now.month == 12 else 0)
        month = 1 if now.month == 12 else now.month + 1
        return now.replace(year=year, month=month, day=dom)
    # daily
    return now + timedelta(days=1)


def advance(schedule: dict, remaining: int, now: datetime) -> dict:
    """The patch to apply after a release ran: complete, or clock the next one. Pure.

    `remaining` is how many releasable pages are LEFT after this release. Zero
    means the plan is fully released, so the schedule completes and stops firing.
    """
    patch: dict = {"last_run_at": now.isoformat()}
    if remaining <= 0:
        patch["status"] = "complete"
        patch["next_run_at"] = None
    else:
        patch["next_run_at"] = next_run_after(
            schedule.get("mode") or "daily",
            schedule.get("weekday"),
            schedule.get("day_of_month"),
            now,
        ).isoformat()
    return patch


# --------------------------------------------------------------------------
# Impure
# --------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_schedule(website_id: str) -> Optional[dict]:
    rows = (
        get_supabase()
        .table("website_releases")
        .select("*")
        .eq("website_id", website_id)
        .limit(1)
        .execute()
    ).data
    return rows[0] if rows else None


def _site_pages(website_id: str) -> list[dict]:
    return (
        get_supabase()
        .table("website_pages")
        .select("id, page_type, status, released_at, tier, route")
        .eq("website_id", website_id)
        .is_("superseded_at", "null")
        .execute()
    ).data or []


def run_release(website_id: str, count: int, user_id: str) -> dict:
    """Generate+publish the next `count` releasable pages. Returns the outcome.

    Marks each claimed page's `released_at` BEFORE enqueuing so a concurrent
    release cannot pick it again, then enqueues one `website_page_generate` job
    per page with `publish_after` set. Returns `{released, remaining}` where
    remaining is the releasable count left afterwards.
    """
    from services import website_generate

    supabase = get_supabase()
    pages = _site_pages(website_id)
    batch = select_batch(pages, count)
    if not batch:
        return {"released": [], "remaining": releasable_count(pages)}

    page_ids = [p["id"] for p in batch]
    now_iso = _now().isoformat()
    supabase.table("website_pages").update({"released_at": now_iso}).in_(
        "id", page_ids
    ).execute()

    site = (
        supabase.table("websites").select("id, client_id").eq("id", website_id).limit(1).execute()
    ).data[0]
    website_generate.enqueue_generation(
        website_id=website_id,
        client_id=site["client_id"],
        page_ids=page_ids,
        user_id=user_id,
        publish_after=True,
    )

    remaining = releasable_count(pages) - len(batch)
    logger.info(
        "website_release.released",
        extra={"website_id": website_id, "count": len(batch), "remaining": remaining},
    )
    return {"released": page_ids, "remaining": max(0, remaining)}


def set_schedule(website: dict, *, body: dict, user_id: str) -> dict:
    """Create or replace a site's release schedule; run the immediate batch.

    The immediate batch fires now (generate+publish `immediate_count` pages);
    the cadence clock is then set for the rest. If nothing is left to release
    after the immediate batch, the schedule is recorded complete rather than
    ticking forever against an empty pool.
    """
    supabase = get_supabase()
    website_id = website["id"]
    now = _now()

    mode = (body.get("mode") or "daily").strip().lower()
    if mode not in VALID_MODES:
        raise ValueError("invalid_release_mode")
    weekday, day_of_month = normalize_anchors(
        mode, body.get("weekday"), body.get("day_of_month"), now
    )
    immediate = max(0, int(body.get("immediate_count") or 0))
    per_release = max(1, int(body.get("per_release_count") or 1))
    enabled = bool(body.get("enabled", True))

    row = {
        "website_id": website_id,
        "enabled": enabled,
        "mode": mode,
        "weekday": weekday,
        "day_of_month": day_of_month,
        "immediate_count": immediate,
        "per_release_count": per_release,
        "status": "active",
        "created_by": user_id or None,
        "next_run_at": next_run_after(mode, weekday, day_of_month, now).isoformat(),
        "updated_at": "now()",
    }
    supabase.table("website_releases").upsert(row, on_conflict="website_id").execute()

    released: list[str] = []
    if enabled and immediate > 0:
        result = run_release(website_id, immediate, user_id)
        released = result["released"]
        # Nothing left after the immediate batch → the schedule is already done.
        if result["remaining"] <= 0:
            supabase.table("website_releases").update(
                {"status": "complete", "next_run_at": None, "last_run_at": now.isoformat(),
                 "updated_at": "now()"}
            ).eq("website_id", website_id).execute()

    schedule = get_schedule(website_id)
    return {"schedule": schedule, "released_now": released}


def enqueue_due_website_releases() -> int:
    """Release the per-release batch for every schedule that has come due.

    Inert unless the module is switched on. Self-gated on `next_run_at` like the
    report/rank schedules; a release that empties the pool marks the schedule
    complete via `advance`.
    """
    if not settings.website_builder_enabled:
        return 0

    supabase = get_supabase()
    now = _now()
    due = (
        supabase.table("website_releases")
        .select("*")
        .eq("enabled", True)
        .eq("status", "active")
        .lte("next_run_at", now.isoformat())
        .execute()
    ).data or []

    fired = 0
    for schedule in due:
        website_id = schedule["website_id"]
        try:
            result = run_release(website_id, int(schedule.get("per_release_count") or 1), "")
            patch = advance(schedule, result["remaining"], now)
            patch["updated_at"] = "now()"
            supabase.table("website_releases").update(patch).eq(
                "website_id", website_id
            ).execute()
            fired += 1
        except Exception as exc:  # noqa: BLE001 — one bad site must not stop the sweep
            logger.warning(
                "website_release.tick_failed",
                extra={"website_id": website_id, "error": str(exc)[:200]},
            )
    return fired
