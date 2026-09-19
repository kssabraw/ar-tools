"""Social Media P4 (Phase B) — the Social Manager orchestrator loop.

A headless per-client loop that **calls** the shared autonomy primitives
(``autonomy_policy.classify``, the fail-closed social ``budget`` meter, freeze) rather
than extending the SEO executor: social is **cadence-driven and generative**, not the
SEO executor's remediation-reactive ``gather_candidates``. Each run, for a client:

  1. gate    — social_enabled AND social_autonomy_enabled AND effective social tier > 0
  2. read    — policy (tier, topics, tone, competitor focus), active-cadence platforms
               with a connected account, per-platform queued-draft depth, this week's
               autonomy-produced count
  3. plan    — ``plan_batches`` (PURE): per platform under the target queue depth, the
               generation batches to run, capped by the weekly rate cap
  4. source  — ``select_source`` (PURE, hybrid): freshest not-recently-used client
               content (complete blog runs + saved Local SEO pages) → the Social Policy
               topic bank
  5. decide  — classify ``generate_social_drafts`` (tier 1) + ``queue_social_draft``
               (tier 2) → auto | propose | escalate (budget advisory, freeze)
  6. act     — for an AUTO run, dispatch one fan-out job per batch (the built Creator),
               tagged ``produced_by='autonomy'`` and ``auto_queue`` = whether the tier-2
               queue action is auto. The fan-out job generates the drafts + (if
               auto_queue) enrolls the ``ready`` ones in the cadence queue. **Nothing
               here publishes** — P3's gates (a schedule's ``auto_fill`` +
               ``social_auto_publish_enabled``) still govern the unattended drip.
  7. record  — write the shared ``autonomy_runs`` ledger (``domain='social'``) + digest

Two global clamps keep it dark: ``social_autonomy_enabled`` (default False) and the
fact that the loop only ever **produces/queues** drafts (never publishes). Spend is
gated by the existing fail-closed social meter (the fan-out image path reserves per
image); the loop's budget read is the advisory pre-filter. The DORA pre-flight veto is
keyword-target-based (SEO); a social generate candidate carries no keyword target, so
the veto is a no-op for v1 and is deliberately not wired (no guard that does nothing) —
it slots in when social candidates gain a target.

Pure helpers (``source_key``, ``filter_candidates``, ``platform_deficits``,
``plan_batches``, ``select_source``, ``compose_angle``) are unit-tested without a DB.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

from config import settings
from services import autonomy_policy
from services.social import budget, policy as social_policy

logger = logging.getLogger(__name__)

AUTO_EXECUTE: frozenset[str] = frozenset({"generate_social_drafts", "queue_social_draft"})
_PROVENANCE = "autonomy"


def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


# ── pure core (unit-tested) ──────────────────────────────────────────────────

def source_key(source_type: str, source_id: Optional[str] = None, text: Optional[str] = None) -> str:
    """A stable de-dup key for a source (matches the cooldown / used-set logic). Pure."""
    st = (source_type or "topic").lower()
    if st == "topic":
        return f"topic:{(text or '').strip().lower()}"
    return f"{st}:{(source_id or '').strip()}"


def filter_candidates(candidates: list[dict], blocked_topics: list[str]) -> list[dict]:
    """Drop content sources whose title contains a blocked-topic phrase (case-insensitive
    substring). Pure — a source with no title is always kept (nothing to match)."""
    if not blocked_topics:
        return list(candidates or [])
    blocked = [b.lower() for b in blocked_topics if b]
    out: list[dict] = []
    for c in candidates or []:
        title = (c.get("title") or "").lower()
        if title and any(b in title for b in blocked):
            continue
        out.append(c)
    return out


def platform_deficits(
    active_platforms: list[str], queued_counts: dict[str, int], target_queue: int
) -> dict[str, int]:
    """How many more queued drafts each active-cadence platform needs to reach the target
    depth. Pure. Order follows ``active_platforms``."""
    out: dict[str, int] = {}
    for p in active_platforms:
        out[p] = max(0, int(target_queue) - int(queued_counts.get(p, 0)))
    return out


def plan_batches(deficits: dict[str, int], weekly_remaining: int) -> list[list[str]]:
    """Turn per-platform deficits into fan-out batches — each batch is a set of platforms
    that get ONE draft this round. Greedy + order-stable; the total drafts planned never
    exceeds ``weekly_remaining`` (the rate-cap headroom). Pure.

    A platform needing N more drafts appears in N batches; batches shrink as platforms
    reach the target. Returns [] when there's nothing to do or no headroom."""
    remaining = {p: int(n) for p, n in deficits.items() if int(n) > 0}
    batches: list[list[str]] = []
    planned = 0
    cap = max(0, int(weekly_remaining))
    while remaining and planned < cap:
        batch: list[str] = []
        for p in list(remaining):
            if planned >= cap:
                break
            batch.append(p)
            planned += 1
            remaining[p] -= 1
            if remaining[p] <= 0:
                del remaining[p]
        if batch:
            batches.append(batch)
    return batches


def compose_angle(angle: dict) -> tuple[str, str]:
    """(angle_text, angle_title) from a proposed angle dict {title, hook, description}.
    The text is what the copy writer is steered by; the title labels the draft. Pure."""
    title = (angle.get("title") or "").strip()
    hook = (angle.get("hook") or "").strip()
    text = f"{title}. {hook}".strip(". ").strip() if (title and hook) else (title or hook)
    return (text or title or hook), (title or hook[:120] or "Social angle")


def activity_item(row: dict) -> dict:
    """Shape one ``autonomy_runs`` (domain='social') ledger row into a compact
    activity item for the UI/API: produced/auto-queued/proposed + the targeted
    platforms + cost. Pure — mirrors what ``_write_ledger`` stores."""
    snap = row.get("goal_snapshot") if isinstance(row.get("goal_snapshot"), dict) else {}
    decisions = row.get("decisions") or []
    produced = len(row.get("actions_taken") or [])
    proposed = 0
    for d in decisions:
        if isinstance(d, dict) and d.get("proposed_batches"):
            proposed += len(d["proposed_batches"])
    deficits = snap.get("deficits") if isinstance(snap, dict) else None
    platforms = sorted(deficits.keys()) if isinstance(deficits, dict) else []
    return {
        "id": row.get("id"),
        "trigger": row.get("trigger"),
        "tier": row.get("tier"),
        "produced": produced,
        "auto_queued": bool(snap.get("auto_queue")),
        "proposed": proposed,
        "platforms": platforms,
        "cost_usd": row.get("cost_usd"),
        "at": row.get("created_at"),
    }


def select_source(
    candidates: list[dict], used_keys: set[str], topics: list[str]
) -> Optional[dict]:
    """Pick ONE source to repurpose (hybrid, PRD Q3): the freshest client-content
    candidate whose key isn't in ``used_keys``, else the first topic-bank entry not in
    ``used_keys``, else None (nothing fresh to post). Pure.

    ``candidates`` = [{type, id, title}] freshest-first. Returns a source spec ready for
    the fan-out: {source_type, source_id?, text?, title, key}."""
    for c in candidates or []:
        k = source_key(c["type"], c.get("id"))
        if k not in used_keys:
            return {"source_type": c["type"], "source_id": c.get("id"),
                    "text": None, "title": c.get("title"), "key": k}
    for t in topics or []:
        tt = (t or "").strip()
        if not tt:
            continue
        k = source_key("topic", text=tt)
        if k not in used_keys:
            return {"source_type": "topic", "source_id": None, "text": tt, "title": tt, "key": k}
    return None


def _per_draft_image_cost() -> float:
    """The USD cost the budget advisory pre-filter charges per generated draft (one image).
    Reads the same knobs the fan-out image path uses."""
    from services.social import image as social_image

    _model, cost = social_image.select_image_model(
        use_flash=bool(settings.social_image_use_flash),
        flash_model=settings.social_image_flash_model,
        flash_cost=float(settings.social_image_flash_cost_usd),
        pro_model=settings.nano_banana_pro_model,
        pro_cost=float(settings.social_image_cost_usd),
    )
    return float(cost)


# ── impure reads ─────────────────────────────────────────────────────────────

def _policy_row(client_id: str) -> dict:
    rows = (
        _sb().table("social_policy")
        .select("autonomy_tier, allowed_topics, blocked_topics, tone_prefs, "
                "competitor_focus, monthly_ceiling_usd")
        .eq("client_id", client_id).limit(1).execute()
    ).data or []
    return rows[0] if rows else {}


def _active_cadence_platforms(client_id: str) -> list[str]:
    """Platforms the client is on a rhythm for AND has a connected account for — the loop
    keeps THESE queues full (cadence-driven). A platform with no connected account can't
    be fanned out to, so it's excluded."""
    from services.social import publish

    rows = (
        _sb().table("social_post_schedules")
        .select("platform, account_id, is_active, cadence")
        .eq("client_id", client_id).eq("is_active", True).neq("cadence", "disabled").execute()
    ).data or []
    scheduled = []
    seen: set[str] = set()
    for r in rows:
        p = (r.get("platform") or "").lower()
        if p and p not in seen:
            seen.add(p)
            scheduled.append(p)
    connected = {(a.get("platform") or "").lower() for a in publish.list_accounts(client_id)}
    return [p for p in scheduled if p in connected]


def _queued_counts(client_id: str) -> dict[str, int]:
    rows = (
        _sb().table("social_drafts").select("platform")
        .eq("client_id", client_id).eq("status", "queued").execute()
    ).data or []
    counts: dict[str, int] = {}
    for r in rows:
        p = (r.get("platform") or "").lower()
        counts[p] = counts.get(p, 0) + 1
    return counts


def _candidate_sources(client_id: str, limit: int = 20) -> list[dict]:
    """Recent repurposable client content, freshest-first: complete blog runs + saved
    (non-deleted) Local SEO pages. Each {type, id, title, created_at}."""
    sb = _sb()
    out: list[dict] = []
    try:
        runs = (
            sb.table("runs").select("id, keyword, created_at")
            .eq("client_id", client_id).eq("status", "complete")
            .order("created_at", desc=True).limit(limit).execute()
        ).data or []
        out.extend({"type": "blog_run", "id": r["id"], "title": r.get("keyword"),
                    "created_at": r.get("created_at")} for r in runs)
    except Exception as exc:  # noqa: BLE001 — one source class failing isn't the run's
        logger.warning("social.autonomy_runs_read_failed", extra={"client_id": client_id, "error": str(exc)[:200]})
    try:
        pages = (
            sb.table("local_seo_pages").select("id, page_title, created_at")
            .eq("client_id", client_id).is_("deleted_at", "null")
            .order("created_at", desc=True).limit(limit).execute()
        ).data or []
        out.extend({"type": "local_seo_page", "id": p["id"], "title": p.get("page_title"),
                    "created_at": p.get("created_at")} for p in pages)
    except Exception as exc:  # noqa: BLE001
        logger.warning("social.autonomy_pages_read_failed", extra={"client_id": client_id, "error": str(exc)[:200]})
    out.sort(key=lambda c: c.get("created_at") or "", reverse=True)
    return out


def _recent_source_keys(client_id: str, cooldown_days: int) -> set[str]:
    """Source keys the autonomy loop has already repurposed within the cooldown window —
    so it rotates rather than re-posting the same content. Reads produced_by='autonomy'
    drafts' source_ref."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(0, cooldown_days))).isoformat()
    rows = (
        _sb().table("social_drafts").select("source_ref, platform_metadata, created_at")
        .eq("client_id", client_id).gte("created_at", cutoff).execute()
    ).data or []
    keys: set[str] = set()
    for r in rows:
        meta = r.get("platform_metadata") or {}
        if (meta.get("produced_by") if isinstance(meta, dict) else None) != _PROVENANCE:
            continue
        ref = r.get("source_ref") or {}
        if not isinstance(ref, dict):
            continue
        st = ref.get("type") or "topic"
        if st == "topic":
            # A topic ref carries its text (build_source_ref) so the topic bank cools down
            # across runs too. An older topicless ref (pre-fix) simply isn't matched.
            txt = ref.get("text")
            if txt:
                keys.add(source_key("topic", text=txt))
            continue
        keys.add(source_key(st, ref.get("run_id") or ref.get("page_id")))
    return keys


def _autonomy_drafts_this_week(client_id: str) -> int:
    """Count of autonomy-produced drafts created in the trailing 7 days — the weekly rate
    signal (a draft is one paid image)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows = (
        _sb().table("social_drafts").select("platform_metadata")
        .eq("client_id", client_id).gte("created_at", cutoff).execute()
    ).data or []
    n = 0
    for r in rows:
        meta = r.get("platform_metadata") or {}
        if isinstance(meta, dict) and meta.get("produced_by") == _PROVENANCE:
            n += 1
    return n


def _in_flight_run(client_id: str) -> bool:
    """True if a social_autonomy_run job for this client is already pending/running — so a
    burst of due empty slots can't stack duplicate runs."""
    rows = (
        _sb().table("async_jobs").select("id")
        .eq("job_type", "social_autonomy_run").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    ).data or []
    return bool(rows)


def list_autonomy_runs(client_id: str, limit: Optional[int] = None) -> list[dict]:
    """Recent Social Manager runs for a client (the activity view), most-recent
    first. Reads the shared ``autonomy_runs`` ledger scoped to ``domain='social'``
    and shapes each row via ``activity_item``. Best-effort — [] on error."""
    lim = max(1, int(limit or settings.social_autonomy_activity_limit))
    try:
        rows = (
            _sb().table("autonomy_runs")
            .select("id, trigger, tier, goal_snapshot, decisions, actions_taken, cost_usd, created_at")
            .eq("client_id", client_id).eq("domain", "social")
            .order("created_at", desc=True).limit(lim).execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001 — the activity read is best-effort
        logger.warning("social.autonomy_activity_read_failed",
                       extra={"client_id": client_id, "error": str(exc)[:200]})
        return []
    return [activity_item(r) for r in rows]


# ── the run ──────────────────────────────────────────────────────────────────

async def _angle_for_source(client_id: str, src: dict, user_id: Optional[str]) -> tuple[str, str]:
    """A grounded editorial angle for the batch's source (the Creator's angle step,
    competitor-signal-grounded via propose_angles). Best-effort: on any failure, fall back
    to the source title so a batch still generates."""
    from services.social import creator

    title = (src.get("title") or "").strip()
    try:
        req = SimpleNamespace(
            source_type=src["source_type"], source_id=src.get("source_id"),
            url=None, text=src.get("text"),
        )
        angles = await creator.propose_angles(client_id, req, user_id)
        if angles:
            return compose_angle(angles[0])
    except Exception as exc:  # noqa: BLE001 — angle proposal is best-effort
        logger.info("social.autonomy_angle_fallback", extra={"error": str(getattr(exc, "detail", exc))[:160]})
    return (title or "Social post", title[:120] or "Social post")


def _dispatch_batch(
    client_id: str, platforms: list[str], src: dict, angle: str, angle_title: str,
    auto_queue: bool, user_id: Optional[str],
) -> Optional[str]:
    """Dispatch ONE fan-out job for a batch (produced_by='autonomy', with the auto_queue
    flag). Returns the angle_set_id, or None on failure (recorded, never raised)."""
    from services.social import fanout

    req = SimpleNamespace(
        angle=angle, angle_title=angle_title, platforms=platforms, format="feed",
        source_type=src["source_type"], source_id=src.get("source_id"), url=None,
        text=src.get("text"), tone=None, include_image=True, include_hashtags=True,
        slides=None, auto_queue=auto_queue, produced_by=_PROVENANCE,
    )
    try:
        out = fanout.enqueue_fanout(client_id, req, user_id)
        return out.get("angle_set_id")
    except Exception as exc:  # noqa: BLE001 — one batch's dispatch failure isn't the run's
        logger.warning("social.autonomy_dispatch_failed",
                       extra={"client_id": client_id, "platforms": platforms,
                              "error": str(getattr(exc, "detail", exc))[:200]})
        return None


async def run_social_autonomy_for_client(
    client_id: str, *, trigger: str = "scheduled", platform: Optional[str] = None,
    today: Optional[date] = None,
) -> dict:
    """Walk the loop for one client. Best-effort throughout — a per-step failure degrades
    to observation, never raises into the caller. ``platform`` scopes an empty-queue
    top-up to a single platform."""
    if not (settings.social_enabled and settings.social_autonomy_enabled):
        return {"status": "disabled"}

    from services.freeze import is_frozen

    prow = _policy_row(client_id)
    tier = autonomy_policy.effective_tier(prow.get("autonomy_tier"), settings.social_autonomy_cap_tier)
    if tier <= 0:
        return {"status": "not_opted_in"}
    if is_frozen(client_id):
        return {"status": "frozen"}   # output pauses under freeze; nothing to generate

    active = _active_cadence_platforms(client_id)
    if platform:
        pl = platform.lower()
        active = [p for p in active if p == pl]
    if not active:
        return {"status": "noop", "reason": "no active-cadence platforms with an account"}

    allowed_topics = social_policy.clean_str_list(prow.get("allowed_topics"))
    blocked_topics = social_policy.clean_str_list(prow.get("blocked_topics"))

    deficits = platform_deficits(active, _queued_counts(client_id), settings.social_autonomy_target_queue)
    produced_this_week = _autonomy_drafts_this_week(client_id)
    weekly_remaining = max(0, int(settings.social_autonomy_max_per_week) - produced_this_week)
    batches = plan_batches(deficits, weekly_remaining)
    if not batches:
        return {"status": "noop", "reason": "queues full or weekly cap reached",
                "deficits": deficits, "weekly_remaining": weekly_remaining}

    # Decide once (the action class is the same for every batch): generation is tier 1,
    # auto-queue is tier 2. The budget check is advisory (the fan-out image path reserves
    # atomically per image); freeze already handled above.
    ceiling = budget.resolve_ceiling(prow or None)
    budget_left = budget.remaining(ceiling, budget.spent_this_month(client_id, today))
    per_cost = _per_draft_image_cost()
    gen = autonomy_policy.classify(
        {"action": "generate_social_drafts", "cost_usd": per_cost, "requires": "none"},
        client_tier=tier, budget_left=budget_left, freeze=False,
        content_this_week=produced_this_week, content_cap=int(settings.social_autonomy_max_per_week),
    )
    queue = autonomy_policy.classify(
        {"action": "queue_social_draft", "requires": "none"},
        client_tier=tier, budget_left=budget_left, freeze=False,
    )
    auto_queue = queue.is_auto

    decisions: list[dict] = [
        {"action": "generate_social_drafts", "outcome": gen.outcome, "reason": gen.reason,
         "cost_usd": round(per_cost, 4)},
        {"action": "queue_social_draft", "outcome": queue.outcome, "reason": queue.reason},
    ]

    if not gen.is_auto:
        # Surface what WOULD have been generated as proposals (out of tier / over budget /
        # rate-capped) — recorded + digested for a human, never run.
        decisions.append({"proposed_batches": batches, "auto_queue": auto_queue})
        _write_ledger(client_id, trigger, tier, deficits, decisions, dispatched=[], auto_queue=auto_queue)
        _emit_digest(client_id, trigger, produced=0, queued=auto_queue, batches=batches, proposed=True)
        return {"status": "proposed", "tier": tier, "batches": len(batches), "reason": gen.reason}

    # AUTO: dispatch one fan-out job per batch, each with a fresh rotated source + angle.
    used_keys = _recent_source_keys(client_id, int(settings.social_autonomy_source_cooldown_days))
    candidates = filter_candidates(_candidate_sources(client_id), blocked_topics)
    dispatched: list[dict] = []
    for batch in batches:
        src = select_source(candidates, used_keys, allowed_topics)
        if not src:
            decisions.append({"skipped_batch": batch, "reason": "no fresh source"})
            break  # nothing fresh left — later batches would repeat; stop
        used_keys.add(src["key"])
        angle, angle_title = await _angle_for_source(client_id, src, None)
        angle_set_id = _dispatch_batch(client_id, batch, src, angle, angle_title, auto_queue, None)
        if angle_set_id:
            dispatched.append({"angle_set_id": angle_set_id, "platforms": batch,
                               "source_key": src["key"], "angle": angle_title})

    _write_ledger(client_id, trigger, tier, deficits, decisions, dispatched, auto_queue)
    _emit_digest(client_id, trigger, produced=len(dispatched), queued=auto_queue,
                 batches=[d["platforms"] for d in dispatched], proposed=False)
    # PACE hand-off (Phase D): when the drafts land awaiting human approval
    # (tier 1 — not auto-queued), file a "review the generated drafts" task so
    # the work is owned on the board, not just a notification. A tier-2
    # auto-queued run drips on its own; the weekly calendar-approval task covers
    # its oversight. Best-effort + double-gated inside the producer.
    if dispatched and not auto_queue:
        _file_pace_review_task(client_id, len(dispatched))
    return {
        "status": "ran", "tier": tier, "auto_queue": auto_queue,
        "dispatched": len(dispatched), "platforms": sorted({p for d in dispatched for p in d["platforms"]}),
    }


def _write_ledger(client_id, trigger, tier, deficits, decisions, dispatched, auto_queue) -> None:
    try:
        _sb().table("autonomy_runs").insert({
            "client_id": client_id, "domain": "social", "trigger": trigger, "tier": tier,
            "goal_snapshot": {"deficits": deficits, "auto_queue": auto_queue} or None,
            "decisions": decisions or None,
            "actions_taken": [d["angle_set_id"] for d in dispatched] or None,
            "cost_usd": 0,   # spend is metered by the fan-out image reserves, not here
        }).execute()
    except Exception as exc:  # noqa: BLE001 — the ledger is best-effort
        logger.warning("social.autonomy_ledger_failed", extra={"client_id": client_id, "error": str(exc)[:200]})


def _file_pace_review_task(client_id: str, count: int) -> None:
    """Best-effort PACE hand-off — a "review the generated social drafts" board
    task (double-gated inside the producer; off by default). Never raises."""
    try:
        from services import task_producers

        task_producers.on_social_drafts_generated(client_id, count)
    except Exception as exc:  # noqa: BLE001 — the PACE hand-off is best-effort
        logger.warning("social.autonomy_pace_task_failed",
                       extra={"client_id": client_id, "error": str(exc)[:200]})


def _emit_digest(client_id, trigger, *, produced, queued, batches, proposed) -> None:
    if not batches:
        return
    try:
        from services import notifications

        n_platforms = len({p for b in batches for p in b})
        if proposed:
            summary = (f"Would generate {len(batches)} social draft batch(es) across "
                       f"{n_platforms} platform(s) — awaiting approval (out of tier / budget).")
        else:
            verb = "generated + auto-queued" if queued else "generated (awaiting your approval)"
            summary = f"{produced} social draft batch(es) {verb} across {n_platforms} platform(s)."
        notifications.emit(
            client_id, "social_autonomy_run", "Social Manager run",
            summary=summary, severity="info",
            payload={"trigger": trigger, "produced": produced, "auto_queue": queued},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("social.autonomy_digest_failed", extra={"error": str(exc)[:200]})


# ── enqueue + job + scheduler ──────────────────────────────────────────────────

def enqueue_social_autonomy_run(
    client_id: str, trigger: str = "scheduled", platform: Optional[str] = None,
    *, dedupe: bool = True,
) -> Optional[str]:
    """Enqueue a social_autonomy_run job. Returns the job id, or None when disabled or a
    run is already in flight for this client (dedupe — so a burst of due empty slots can't
    stack runs)."""
    if not (settings.social_enabled and settings.social_autonomy_enabled):
        return None
    if dedupe and _in_flight_run(client_id):
        return None
    try:
        row = _sb().table("async_jobs").insert({
            "job_type": "social_autonomy_run", "entity_id": client_id,
            "payload": {"client_id": client_id, "trigger": trigger, "platform": platform},
        }).execute().data[0]
        return row["id"]
    except Exception as exc:  # noqa: BLE001 — a failed enqueue never breaks the caller (the sweep)
        logger.warning("social.autonomy_enqueue_failed", extra={"client_id": client_id, "error": str(exc)[:200]})
        return None


_WEEKLY_INTERVAL_DAYS = 6  # a client run this recently is skipped (weekly cadence)


def enqueue_due_social_autonomy_runs(today_weekday: Optional[int] = None) -> int:
    """Weekly baseline pass on ``social_autonomy_weekly_weekday``: one run per opted-in
    (social_policy.autonomy_tier > 0) client not already run within the last week
    (self-clocked off the shared autonomy_runs ledger, domain='social'). No-ops entirely
    while social_autonomy_enabled is False."""
    if not (settings.social_enabled and settings.social_autonomy_enabled):
        return 0
    if today_weekday is None:
        today_weekday = datetime.now(timezone.utc).weekday()
    if today_weekday != settings.social_autonomy_weekly_weekday:
        return 0
    sb = _sb()
    try:
        opted = (
            sb.table("social_policy").select("client_id")
            .gt("autonomy_tier", 0).execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("social.autonomy_due_read_failed", extra={"error": str(exc)[:200]})
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_WEEKLY_INTERVAL_DAYS)).isoformat()
    n = 0
    for row in opted:
        cid = row.get("client_id")
        if not cid:
            continue
        try:
            recent = (
                sb.table("autonomy_runs").select("id")
                .eq("client_id", cid).eq("domain", "social")
                .gte("created_at", cutoff).limit(1).execute()
            ).data
            if recent:
                continue
            if enqueue_social_autonomy_run(cid, "scheduled"):
                n += 1
        except Exception as exc:  # noqa: BLE001 — one client can't break the pass
            logger.warning("social.autonomy_due_enqueue_failed", extra={"client_id": cid, "error": str(exc)[:200]})
    return n


async def run_social_autonomy_job(job: dict) -> None:
    """Handler for job_type='social_autonomy_run'. Settles its own row."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id") or job.get("entity_id")
    sb = _sb()
    try:
        result = await run_social_autonomy_for_client(
            client_id, trigger=payload.get("trigger") or "scheduled",
            platform=payload.get("platform"),
        )
        sb.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("social.autonomy_job_failed", extra={"client_id": client_id, "error": str(exc)[:300]})
        sb.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
