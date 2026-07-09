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
    while True:
        try:
            await _tick()
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
    """Requeue rows left `running` by a prior process (restart mid-write)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)).isoformat()
    res = (get_service_client().table("scheduled_article_runs")
           .update({"status": "queued", "started_at": None})
           .eq("status", "running").lt("started_at", cutoff).execute())
    if res.data:
        logger.info("scheduler_requeued_stuck",
                    extra={"event": "scheduler_requeued_stuck", "count": len(res.data)})


def _process_run(row: dict) -> None:
    """Generate the article for one claimed run, then record the outcome + advance the schedule."""
    from fanout import jobs
    from fanout.storage import silo as store
    from fanout.writer import schedule_store

    run_id = row["id"]
    cluster_id = row["cluster_id"]
    session_id = row["session_id"]
    schedule_id = row.get("content_schedule_id")
    try:
        cluster = store.get_cluster(cluster_id)
        pkid = (cluster or {}).get("primary_keyword_id")
        keyword = store.get_keyword_texts([pkid]).get(pkid) if pkid else None
        session = store.get_session(session_id)
        if not keyword or not session:
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
        _finish_run(run_id, "complete" if success else "failed",
                    error=None if success else "content generation failed")
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
        _finish_run(run_id, "failed", error=repr(exc)[:500])
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
    session's internal links point at) and sending the distinct SEO title as the
    post title with the H1 already in the body."""
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
    res = asyncio.run(publish_to_wordpress(
        client=client_row,
        title=aj.get("seo_title") or aj.get("title") or keyword or "Article",
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
