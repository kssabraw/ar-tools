"""M15 slice 4 — content-schedule worker (handoff.md §9.6).

An in-process asyncio loop in the FastAPI backend (no new Railway service, no Postgres cron).
Every `scheduler_tick_seconds` it claims up to `cap - in_flight` due runs via the atomic
`claim_scheduled_runs` RPC (FOR UPDATE SKIP LOCKED), then generates each in a worker thread
(`generate_article_core`, the same path the Generate button uses) and records the result on
the run row. A startup sweep requeues rows stuck `running` (a restart mid-write).

Durable by construction: state lives in `scheduled_article_runs`, so a process restart just
resumes on the next tick. The heartbeat living in the web process is the accepted M5-style
trade-off; the sweep closes the stuck-row gap on this path.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fanout.config import get_settings
from fanout.cost_attribution import metered_run
from fanout.storage.supabase_client import get_service_client
from fanout.writer import retry as retry_policy

logger = logging.getLogger(__name__)

_loop_task: asyncio.Task | None = None
_inflight: set[asyncio.Task] = set()
_executor: ThreadPoolExecutor | None = None


async def start() -> None:
    """Start the loop (called from the FastAPI lifespan). No-op if disabled or already running."""
    global _loop_task, _executor
    s = get_settings()
    if not s.scheduler_enabled or (_loop_task and not _loop_task.done()):
        return
    _executor = ThreadPoolExecutor(max_workers=s.scheduler_concurrency_cap,
                                   thread_name_prefix="sched-writer")
    try:
        _recover_stuck(s.scheduler_stuck_minutes)
    except Exception as exc:  # noqa: BLE001 — never block startup on the sweep
        logger.warning("scheduler_recover_failed", extra={"event": "scheduler_recover_failed",
                                                          "reason": repr(exc)})
    _loop_task = asyncio.create_task(_run_loop())
    logger.info("scheduler_started", extra={"event": "scheduler_started",
                                            "cap": s.scheduler_concurrency_cap,
                                            "tick_s": s.scheduler_tick_seconds})


async def stop() -> None:
    """Stop the loop + let in-flight writes finish, but bounded by `scheduler_shutdown_grace_s`
    so a minutes-long write can't hang shutdown past the platform's grace period — an abandoned
    `running` row is recovered by the next startup sweep."""
    global _loop_task
    if _loop_task:
        _loop_task.cancel()
        _loop_task = None
    if _inflight:
        grace = float(get_settings().scheduler_shutdown_grace_s)
        try:
            await asyncio.wait_for(asyncio.gather(*_inflight, return_exceptions=True), timeout=grace)
        except asyncio.TimeoutError:
            logger.warning("scheduler_shutdown_timeout",
                           extra={"event": "scheduler_shutdown_timeout", "in_flight": len(_inflight)})
    if _executor:
        _executor.shutdown(wait=False)


async def _run_loop() -> None:
    s = get_settings()
    ticks = 0
    while True:
        ticks += 1
        try:
            await _tick()
            # Periodically re-run the stuck-row sweep (not just at startup) so a run
            # orphaned mid-write by a deploy/restart is recovered on a bounded clock
            # instead of only on the next process restart. Runs on the default
            # executor (a quick DB sweep), never the cap-sized worker pool.
            if ticks % max(1, s.scheduler_sweep_every_ticks) == 0:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _recover_stuck, s.scheduler_stuck_minutes)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a bad tick must not kill the loop
            logger.warning("scheduler_tick_failed",
                           extra={"event": "scheduler_tick_failed", "reason": repr(exc)})
        await asyncio.sleep(s.scheduler_tick_seconds)


async def _tick() -> None:
    s = get_settings()
    cap = s.scheduler_concurrency_cap - len(_inflight)
    if cap <= 0:
        return
    loop = asyncio.get_running_loop()
    # Claim on the default executor (a quick DB call), not `_executor` — so it never waits on a
    # cap-sized worker thread that an in-flight article write is holding.
    rows = await loop.run_in_executor(None, _claim_due, cap)
    for row in rows:
        task = asyncio.create_task(_dispatch(row))
        _inflight.add(task)
        task.add_done_callback(_inflight.discard)


async def _dispatch(row: dict) -> None:
    """Run one claimed row in a worker thread (the write is blocking, minutes long)."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _process_run, row)


# ----- sync helpers (run in the worker thread) ------------------------------


def _claim_due(cap: int) -> list[dict]:
    res = get_service_client().rpc("claim_scheduled_runs", {"cap": cap}).execute()
    return res.data or []


def _recover_stuck(stuck_minutes: int) -> None:
    """Requeue rows left `running` by a prior process (restart mid-write).

    Attempts-aware: each recovered row goes through `_retry_or_fail` so a row that
    repeatedly strands the worker (a poison run that crashes the process) is
    eventually dead-lettered instead of requeued forever. Recovery retries are
    `immediate` (due now) — a restart isn't a content failure, so there's no
    reason to back it off."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)).isoformat()
    rows = (get_service_client().table("scheduled_article_runs").select("*")
            .eq("status", "running").lt("started_at", cutoff).execute().data or [])
    for row in rows:
        # One bad row (a DB write blip) must not skip recovery of the rest.
        try:
            _retry_or_fail(row, "worker restarted mid-generation", immediate=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("scheduler_recover_row_failed",
                           extra={"event": "scheduler_recover_row_failed",
                                  "run_id": row.get("id"), "reason": repr(exc)})
    if rows:
        logger.info("scheduler_requeued_stuck",
                    extra={"event": "scheduler_requeued_stuck", "count": len(rows)})


def _process_run(row: dict) -> None:
    """Generate the article for one claimed run, then record the outcome + advance the schedule."""
    from fanout import jobs
    from fanout.storage import silo as store
    from fanout.writer import schedule_store

    run_id = row["id"]
    cluster_id = row["cluster_id"]
    session_id = row["session_id"]
    schedule_id = row.get("content_schedule_id")
    client_id: str | None = None
    try:
        cluster = store.get_cluster(cluster_id)
        pkid = (cluster or {}).get("primary_keyword_id")
        keyword = store.get_keyword_texts([pkid]).get(pkid) if pkid else None
        session = store.get_session(session_id)
        client_id = (session or {}).get("client_id")
        if not keyword or not session:
            # A structural/data problem (no primary keyword, or the session is
            # gone) won't self-heal — terminal, not retryable.
            _finish_run(run_id, "failed", error="cluster has no primary keyword or session missing")
            return
        # Freeze Protocol (suite): scheduled content creation stops for a frozen
        # client. Fanout may import suite services (never the reverse).
        if session.get("client_id"):
            from services.freeze import is_frozen

            if is_frozen(session["client_id"]):
                _finish_run(run_id, "failed", error="client_frozen")
                return
        # The schedule decides which generator runs (blog post, Local SEO page,
        # or service page).
        schedule = schedule_store.get_schedule(schedule_id) if schedule_id else None
        content_type = (schedule or {}).get("content_type", "blog_post")
        location_code = store.session_location_code(session)
        with metered_run(session_id, "article_generation"):
            if content_type == "local_seo_page":
                ok = jobs.generate_local_seo_page_core(
                    session=session, keyword=keyword,
                    location=(schedule or {}).get("location") or "",
                    location_code=(schedule or {}).get("location_code"),
                    user_id=row.get("user_id"))
            elif content_type == "service_page":
                ok = jobs.generate_service_page_core(
                    session=session, keyword=keyword,
                    user_id=row.get("user_id"))
            else:
                ok = jobs.generate_article_core(
                    session_id, cluster_id, keyword, location_code,
                    scheduled_article_run_id=run_id)
        # local_seo_page / service_page return the artifact id (truthy) on success;
        # blog returns True. `bool(ok)` is the success signal for both.
        success = bool(ok)
        if not success:
            # A generation miss is treated as transient: requeue with backoff up to
            # scheduler_max_attempts, then dead-letter. Safe against double-work —
            # a miss happens before the article is persisted, so a retry re-runs
            # cleanly (and publish only ever runs on success below).
            _retry_or_fail(row, "content generation failed", client_id=client_id)
            return
        _finish_run(run_id, "complete", error=None)
        # Opt-in auto-publish: push the finished piece to the client's Drive folder.
        if success and (schedule or {}).get("auto_publish"):
            _auto_publish_to_client_drive(
                content_type, session=session, cluster_id=cluster_id,
                keyword=keyword, artifact=ok, user_id=row.get("user_id"))
        # Opt-in direct-to-WordPress: blog posts land at the slug their internal
        # links were computed against; local SEO / service pages reuse their own
        # publish paths (as WP pages).
        if success and (schedule or {}).get("wp_publish"):
            _auto_publish_to_wordpress(
                content_type, session=session, cluster_id=cluster_id, keyword=keyword,
                artifact=ok, user_id=row.get("user_id"),
                wp_status=(schedule or {}).get("wp_status") or "draft")
    except Exception as exc:  # noqa: BLE001 — one bad run must not stop the worker
        logger.error("scheduled_run_failed",
                     extra={"event": "scheduled_run_failed", "run_id": run_id,
                            "cluster_id": cluster_id, "reason": repr(exc)})
        # An unexpected error (DB read, external-API blip) is transient by default:
        # requeue with backoff up to the attempt cap, then dead-letter.
        _retry_or_fail(row, repr(exc)[:500], client_id=client_id)
    finally:
        if schedule_id:
            _maybe_complete_schedule(schedule_id)


def _auto_publish_to_client_drive(
    content_type: str, *, session: dict, cluster_id: str, keyword: str,
    artifact, user_id: str | None,
) -> None:
    """Publish a just-generated piece to the linked client's Google Drive folder
    (a Google Doc via the suite's Apps Script webhook). Best-effort — any failure
    is logged and swallowed so it never affects the generation run's status.
    Requires a client-linked session; no-ops otherwise."""
    import asyncio

    client_id = session.get("client_id")
    if not client_id:
        logger.info("auto_publish_skipped",
                    extra={"event": "auto_publish_skipped", "content_type": content_type,
                           "reason": "session not client-linked"})
        return
    try:
        if content_type == "local_seo_page":
            # First-class suite artifact — reuse its own publish path (which also
            # persists published_doc_url on the page row).
            from services import local_seo_service

            if isinstance(artifact, str):
                asyncio.run(local_seo_service.publish_page(
                    artifact, user_id or "", destination="google_docs"))
        elif content_type == "service_page":
            from db.supabase_client import get_supabase
            from routers.publish import _resolve_content
            from fanout.writer.publish.client_drive import publish_html_to_client_drive

            if isinstance(artifact, str):
                _, html = _resolve_content(get_supabase(), artifact, "service_page")
                asyncio.run(publish_html_to_client_drive(
                    client_id, keyword, html, content_type="service_page"))
        else:  # blog_post
            from fanout.writer import store as article_store
            from fanout.writer.publish.client_drive import publish_html_to_client_drive

            art = article_store.get_latest_article(cluster_id)
            aj = (art or {}).get("article_json") or {}
            html = aj.get("article_html") or ""
            if html:
                asyncio.run(publish_html_to_client_drive(
                    client_id, aj.get("title") or keyword or "Article", html,
                    content_type="blog_post"))
        logger.info("auto_published",
                    extra={"event": "auto_published", "content_type": content_type,
                           "client_id": client_id})
    except Exception as exc:  # noqa: BLE001 — auto-publish is best-effort
        logger.warning("auto_publish_failed",
                       extra={"event": "auto_publish_failed", "content_type": content_type,
                              "client_id": client_id, "reason": repr(exc)})


def _auto_publish_to_wordpress(
    content_type: str, *, session: dict, cluster_id: str, keyword: str,
    artifact, user_id: str | None, wp_status: str,
) -> None:
    """Publish a just-generated piece to the linked client's WordPress site.
    Blog posts pin the cluster's slug so the live URL matches the internal links
    the writer injected; local SEO / service pages reuse their own publish paths
    (as WP pages). Best-effort — a publish failure is logged and swallowed, never
    failing the generation run. Requires a client-linked session; no-ops otherwise."""
    import asyncio

    status = wp_status if wp_status in ("draft", "publish") else "draft"
    client_id = session.get("client_id")
    if not client_id:
        logger.info("wp_auto_publish_skipped",
                    extra={"event": "wp_auto_publish_skipped",
                           "reason": "session not client-linked"})
        return
    try:
        if content_type == "local_seo_page":
            # First-class suite artifact — reuse its own WP publish path (which
            # persists published_url on the page row).
            from services import local_seo_service

            if isinstance(artifact, str):
                asyncio.run(local_seo_service.publish_page(
                    artifact, user_id or "", destination="wordpress", status=status))
        elif content_type == "service_page":
            from db.supabase_client import get_supabase
            from routers.publish import _resolve_content
            from services.wordpress_publish import publish_to_wordpress

            if isinstance(artifact, str):
                _, html = _resolve_content(get_supabase(), artifact, "service_page")
                if not (html or "").strip():
                    return
                client_row = (get_supabase().table("clients")
                              .select("name, wordpress_site_url, wordpress_username, "
                                      "wordpress_app_password")
                              .eq("id", client_id).single().execute().data)
                asyncio.run(publish_to_wordpress(
                    client=client_row, title=keyword or "Service", html=html,
                    status=status, content_type="service_page"))
        else:  # blog_post
            _wp_publish_blog(session, cluster_id, keyword, status)
        logger.info("wp_auto_published",
                    extra={"event": "wp_auto_published", "content_type": content_type,
                           "cluster_id": cluster_id, "client_id": client_id})
    except Exception as exc:  # noqa: BLE001 — WP auto-publish is best-effort
        # Reason in the message so it survives the plain stdout formatter.
        logger.warning("wp_auto_publish_failed content_type=%s cluster=%s client=%s reason=%s",
                       content_type, cluster_id, client_id, repr(exc),
                       extra={"event": "wp_auto_publish_failed", "content_type": content_type,
                              "cluster_id": cluster_id, "client_id": client_id,
                              "reason": repr(exc)})


def _wp_publish_blog(session: dict, cluster_id: str, keyword: str, status: str) -> None:
    """Publish a blog article to WordPress, pinning the cluster slug (the URL the
    session's internal links point at). The on-page H1 is sent as the post title
    (the theme's visible <h1>) and the distinct SEO title is routed to SEOPress's
    meta-title field."""
    import asyncio

    from fanout.storage import silo as store
    from fanout.writer import store as article_store
    from db.supabase_client import get_supabase
    from services.wordpress_publish import publish_to_wordpress

    art = article_store.get_latest_article(cluster_id)
    aj = (art or {}).get("article_json") or {}
    html = aj.get("article_html") or ""
    if not html:
        logger.warning("wp_auto_publish_skipped",
                       extra={"event": "wp_auto_publish_skipped",
                              "cluster_id": cluster_id, "reason": "article has no HTML"})
        return
    # Same slug source as link injection (ensure_session_slugs is idempotent, so
    # this is the slug the session's other articles already link to).
    slug = store.ensure_session_slugs(session["id"]).get(cluster_id)
    client_row = (get_supabase().table("clients")
                  .select("name, wordpress_site_url, wordpress_username, "
                          "wordpress_app_password")
                  .eq("id", session["client_id"]).single().execute().data)
    # The on-page H1 becomes the WordPress post title (the theme renders it as the
    # visible <h1>); the distinct SEO title is routed to SEOPress's meta-title
    # field, and the body's own leading H1 is stripped to avoid a duplicate.
    res = asyncio.run(publish_to_wordpress(
        client=client_row,
        title=aj.get("title") or keyword or "Article",
        seo_title=aj.get("seo_title") or None,
        strip_leading_h1=True,
        html=html, status=status, content_type="blog_post", slug=slug))
    link = res.get("link") or ""
    if slug and slug not in link:
        # WP deduped the slug (e.g. -2 suffix) or its permalink base differs from
        # the client card's reference URL — internal links to this post will 404
        # until it's fixed on the WP side.
        logger.warning("wp_auto_publish_slug_mismatch",
                       extra={"event": "wp_auto_publish_slug_mismatch",
                              "cluster_id": cluster_id, "slug": slug, "link": link})


def _finish_run(run_id: str, status: str, *, error: str | None) -> None:
    get_service_client().table("scheduled_article_runs").update({
        "status": status, "completed_at": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }).eq("id", run_id).execute()


def _retry_or_fail(
    row: dict, reason: str, *, client_id: str | None = None, immediate: bool = False,
) -> None:
    """Record a transient failure: requeue the run with backoff up to
    `scheduler_max_attempts`, else dead-letter it (status=failed + a
    notification). `immediate=True` requeues due-now with no backoff (used by the
    restart-recovery sweep, where the failure was a process restart, not content).

    Idempotency: this only ever fires for a *generation* failure, which happens
    before the article is persisted and before any publish — so a re-run can't
    double-generate or double-post.

    Every write is conditional on the row still being `running` (its state when
    the RPC claimed it). If a user cancelled the run mid-generation (running ->
    cancelled), the update no-ops and the run stays cancelled — never resurrected
    into a `queued` zombie that would silently regenerate + spend."""
    s = get_settings()
    run_id = row["id"]
    attempts = retry_policy.next_attempt_number(row.get("attempts"))
    reason = (reason or "")[:500]
    if retry_policy.should_retry(attempts, s.scheduler_max_attempts):
        if immediate:
            next_at = datetime.now(timezone.utc)
        else:
            delay = retry_policy.retry_delay_seconds(
                attempts, s.scheduler_retry_base_seconds, s.scheduler_retry_cap_seconds)
            next_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        res = (get_service_client().table("scheduled_article_runs").update({
            "status": "queued", "attempts": attempts, "started_at": None,
            "completed_at": None, "scheduled_at": next_at.isoformat(), "error": reason,
        }).eq("id", run_id).eq("status", "running").execute())
        if res.data:
            logger.info("scheduled_run_retry",
                        extra={"event": "scheduled_run_retry", "run_id": run_id,
                               "attempt": attempts, "max_attempts": s.scheduler_max_attempts,
                               "next_at": next_at.isoformat(), "reason": reason})
        else:
            logger.info("scheduled_run_retry_skipped",
                        extra={"event": "scheduled_run_retry_skipped", "run_id": run_id,
                               "reason": "run no longer running (cancelled?)"})
        return
    # Out of attempts — dead-letter and surface it so a human looks. Only notify
    # if the row was still running (i.e. we actually dead-lettered it).
    res = (get_service_client().table("scheduled_article_runs").update({
        "status": "failed", "attempts": attempts,
        "completed_at": datetime.now(timezone.utc).isoformat(), "error": reason,
    }).eq("id", run_id).eq("status", "running").execute())
    if not res.data:
        logger.info("scheduled_run_dead_letter_skipped",
                    extra={"event": "scheduled_run_dead_letter_skipped", "run_id": run_id,
                           "reason": "run no longer running (cancelled?)"})
        return
    logger.error("scheduled_run_dead_letter",
                 extra={"event": "scheduled_run_dead_letter", "run_id": run_id,
                        "attempts": attempts, "reason": reason})
    _notify_dead_letter(row, client_id, attempts, reason)


def _notify_dead_letter(row: dict, client_id: str | None, attempts: int, reason: str) -> None:
    """Best-effort in-app/email/Slack alert when a scheduled article gives up.
    Never raises into the worker (a notification failure must not affect the
    run's outcome). Resolves the client from the session when not supplied so the
    alert lands on the right client card."""
    try:
        from services import notifications

        if not client_id and row.get("session_id"):
            from fanout.storage import silo as store
            client_id = (store.get_session(row["session_id"]) or {}).get("client_id")
        notifications.emit(
            client_id,
            kind="content_generation_failed",
            title="Scheduled article failed to generate",
            summary=f"A scheduled article gave up after {attempts} attempt(s): {reason}",
            severity="warning",
            payload={"run_id": row.get("id"), "cluster_id": row.get("cluster_id"),
                     "schedule_id": row.get("content_schedule_id"),
                     "session_id": row.get("session_id")},
        )
    except Exception as exc:  # noqa: BLE001 — notification is best-effort
        logger.warning("dead_letter_notify_failed",
                       extra={"event": "dead_letter_notify_failed",
                              "run_id": row.get("id"), "reason": repr(exc)})


def _maybe_complete_schedule(schedule_id: str) -> None:
    """Flip an active schedule -> complete once none of its runs are queued/running. Leaves a
    paused/cancelled schedule untouched."""
    client = get_service_client()
    sched = (client.table("content_schedules").select("status")
             .eq("id", schedule_id).limit(1).execute().data or [])
    if not sched or sched[0]["status"] != "active":
        return
    pending = (client.table("scheduled_article_runs").select("id", count="exact")
               .eq("content_schedule_id", schedule_id)
               .in_("status", ["queued", "running"]).execute())
    if (pending.count or 0) == 0:
        client.table("content_schedules").update({"status": "complete"}).eq(
            "id", schedule_id).execute()
