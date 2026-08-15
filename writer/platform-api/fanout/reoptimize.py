"""Fan-out blog reoptimization — score + rewrite-to-threshold a Fan-out article.

A client-linked Fan-out blog article is mirrored into the suite as a first-class
blog ``run`` (``fanout.article_outputs.suite_run_id``; see ``suite_mirror``).

Two operations, both driven by the suite's blog score/reopt machinery:

* **Score** reuses ``blog_page_score.score_run`` directly on the mirrored run —
  the mirror carries the article sections + title, which is all the blog/AEO
  scorer needs.
* **Reoptimize** can't use the in-place ``reoptimize_run`` spine (the mirror is a
  thin display shell — no full brief/sie to regenerate from), so it spawns a
  fresh suite **reoptimize-of-existing** blog run from the article's own HTML (a
  full brief→sie→research→writer pass, deficiency-guided by scoring that source),
  then REFLECTS the improved article back onto a fresh ``fanout.article_outputs``
  row — repointed at the new, fully-formed run — so the Fan-out Articles library
  shows it.

Because this needs a suite client (brand voice + the nlp scorer live in the
suite), only **client-linked** Fan-out sessions can be reoptimized — an unlinked
article has no ``suite_run_id`` and no brand/ICP context, and is refused with a
clear ``not_client_linked`` code (the UI prompts to link the session to a client).

Two async ``async_jobs`` types drive this (the suite ``job_worker`` dispatches
them): ``fanout_blog_score`` (observation) and ``fanout_blog_reoptimize`` (output
— freeze-gated). ``entity_id`` is the suite run; the payload carries the
``cluster_id``/``session_id``/``client_id`` the reflection + freeze gate need.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


def _suite_sb():
    """Suite (public-schema) service-role client — async_jobs + suite run reads."""
    from db.supabase_client import get_supabase
    return get_supabase()


def _fanout_sb():
    """Fan-out-schema service-role client — sessions + article_outputs."""
    from fanout.storage.supabase_client import get_service_client
    return get_service_client()


# ── Resolution ───────────────────────────────────────────────────────────────
def resolve_article(cluster_id: str) -> dict:
    """The latest Fan-out article for a cluster + its mirrored suite run and
    client. Raises 404 if there's no article, 409 ``not_client_linked`` if the
    article was written from a session with no suite client (nothing to reopt
    against). Returns {article, suite_run_id, client_id, session_id, cluster_id}."""
    from fanout.writer import store as article_store

    row = article_store.get_latest_article(cluster_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="article_not_found")
    suite_run_id = row.get("suite_run_id")
    if not suite_run_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_client_linked")
    run = (
        _suite_sb().table("runs").select("id, client_id").eq("id", suite_run_id).limit(1).execute()
    ).data or []
    client_id = (run[0].get("client_id") if run else None)
    if not client_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_client_linked")
    return {
        "article": row,
        "suite_run_id": suite_run_id,
        "client_id": client_id,
        "session_id": row.get("session_id"),
        "cluster_id": cluster_id,
    }


def list_client_reoptimizable(client_id: str) -> list[dict]:
    """Reoptimizable Fan-out articles for a client: the latest article per cluster
    across the client's sessions that carries a ``suite_run_id`` (mirrored). Each
    row is {cluster_id, name, composite_score, generated_at}. Newest first."""
    fsb = _fanout_sb()
    sessions = (
        fsb.table("sessions").select("id").eq("client_id", client_id).execute()
    ).data or []
    session_ids = [s["id"] for s in sessions]
    if not session_ids:
        return []

    latest: dict[str, dict] = {}
    page = 0
    while True:
        rows = (
            fsb.table("article_outputs")
            .select("cluster_id, generated_at, suite_run_id, composite_score")
            .in_("session_id", session_ids)
            .order("generated_at", desc=True)
            .range(page * 1000, page * 1000 + 999)
            .execute()
        ).data or []
        for r in rows:
            latest.setdefault(r["cluster_id"], r)  # desc → first seen is newest
        if len(rows) < 1000:
            break
        page += 1

    linked = [r for r in latest.values() if r.get("suite_run_id")]
    if not linked:
        return []
    names: dict[str, str] = {}
    try:
        from fanout.storage import silo as store

        for cid in {r["cluster_id"] for r in linked}:
            c = store.get_cluster(cid)
            if c:
                names[cid] = c.get("name") or cid
    except Exception:  # noqa: BLE001 — names are display-only; fall back to the id
        pass
    out = [
        {
            "cluster_id": r["cluster_id"],
            "name": names.get(r["cluster_id"], "—"),
            "composite_score": r.get("composite_score"),
            "generated_at": r.get("generated_at"),
        }
        for r in linked
    ]
    out.sort(key=lambda x: x["generated_at"] or "", reverse=True)
    return out


# ── Enqueue ──────────────────────────────────────────────────────────────────
def _enqueue(job_type: str, resolved: dict, user_id: Optional[str]) -> str:
    payload = {
        "cluster_id": resolved["cluster_id"],
        "session_id": resolved["session_id"],
        "suite_run_id": resolved["suite_run_id"],
        "client_id": resolved["client_id"],  # freeze gate reads payload.client_id
        "user_id": user_id,
    }
    res = (
        _suite_sb().table("async_jobs")
        .insert({"job_type": job_type, "entity_id": resolved["suite_run_id"], "payload": payload})
        .execute()
    )
    return res.data[0]["id"]


def enqueue_score(cluster_id: str, user_id: Optional[str]) -> str:
    return _enqueue("fanout_blog_score", resolve_article(cluster_id), user_id)


def enqueue_reoptimize(cluster_id: str, user_id: Optional[str]) -> str:
    return _enqueue("fanout_blog_reoptimize", resolve_article(cluster_id), user_id)


def enqueue_reoptimize_for_client(cluster_id: str, client_id: str, user_id: Optional[str]) -> str:
    """Reoptimize a cluster's article, asserting it belongs to ``client_id`` (the
    client-scoped shared-panel path — a caller can only reopt this client's
    articles)."""
    resolved = resolve_article(cluster_id)
    if resolved["client_id"] != client_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cluster_not_in_client")
    return _enqueue("fanout_blog_reoptimize", resolved, user_id)


# ── Job handlers (dispatched by the suite job_worker) ────────────────────────
async def _finish_job(job_id: str, work) -> None:
    sb = _suite_sb()
    try:
        summary = await work()
        sb.table("async_jobs").update(
            {"status": "complete", "result": summary, "completed_at": "now()"}
        ).eq("id", job_id).execute()
    except HTTPException as exc:
        _fail(sb, job_id, str(exc.detail))
    except Exception as exc:  # noqa: BLE001 — record the failure for the poller
        _fail(sb, job_id, str(exc))


def _fail(sb, job_id: str, detail: str) -> None:
    logger.warning("fanout.reopt_job_failed", extra={"job_id": job_id, "error": detail})
    sb.table("async_jobs").update(
        {"status": "failed", "error": detail[:500], "completed_at": "now()"}
    ).eq("id", job_id).execute()


async def run_score_job(job: dict) -> None:
    """async_jobs handler for ``fanout_blog_score`` — score the mirrored suite run
    and persist the composite onto the latest Fan-out article row."""
    from services import blog_page_score

    payload = job.get("payload") or {}
    suite_run_id = payload["suite_run_id"]
    cluster_id = payload.get("cluster_id")
    user_id = payload.get("user_id")

    async def work() -> dict:
        result = await blog_page_score.score_run(suite_run_id, user_id=user_id)
        _persist_score(cluster_id, result.get("composite_score"), result.get("composite_status"))
        return {"composite_score": result.get("composite_score")}

    await _finish_job(job["id"], work)


def _reopt_source(article_row: dict) -> tuple[str, str]:
    """(keyword, source_html) to seed the reoptimize-of-existing run from a Fan-out
    article. HTML prefers the stored ``article_html``; falls back to rendering the
    markdown. Keyword is the article title (the on-page H1)."""
    aj = article_row.get("article_json") or {}
    keyword = (aj.get("title") or "").strip() or (article_row.get("keyword") or "").strip()
    html = (aj.get("article_html") or article_row.get("article_html") or "").strip()
    if not html:
        md = (aj.get("article_markdown") or article_row.get("article_markdown") or "").strip()
        if md:
            from services.markdown_html import markdown_to_html

            html = markdown_to_html(md)
    return keyword, html


async def run_reoptimize_job(job: dict) -> None:
    """async_jobs handler for ``fanout_blog_reoptimize``.

    The mirrored suite run is a THIN display shell (title + article sections only —
    no full brief/sie), so it can't drive the in-place ``reoptimize_run`` spine.
    Instead we spawn a fresh **reoptimize-of-existing** suite blog run from the
    article's own HTML (the orchestrator scores that source and feeds its
    deficiencies into a full brief→sie→research→writer pass), run it to
    completion, score it, then reflect the improved article back onto a fresh
    Fan-out article row (repointed at the new, fully-formed run)."""
    from services import blog_page_score
    from services.orchestrator import orchestrate_run
    from services.run_dispatch import create_run_and_snapshot

    from fanout import suite_mirror
    from fanout.writer import store as article_store

    payload = job.get("payload") or {}
    old_suite_run_id = payload["suite_run_id"]
    cluster_id = payload.get("cluster_id")
    session_id = payload.get("session_id")
    client_id = payload.get("client_id")
    user_id = payload.get("user_id")

    async def work() -> dict:
        article_row = article_store.get_latest_article(cluster_id) or {}
        keyword, source_html = _reopt_source(article_row)
        if not source_html:
            raise RuntimeError("article_has_no_content")

        # Before-score: the current article (the thin mirror IS scorable).
        prev_score = None
        try:
            prev = await blog_page_score.score_run(old_suite_run_id, user_id=user_id)
            prev_score = prev.get("composite_score")
        except Exception as exc:  # noqa: BLE001 — the before-score is a nicety, not load-bearing
            logger.info("fanout.prev_score_skipped", extra={"cluster_id": cluster_id, "error": str(exc)})

        client = (
            _suite_sb().table("clients").select("*").eq("id", client_id).single().execute()
        ).data or {}
        # Idempotent per (cluster, source run) so a reaper requeue adopts the
        # in-flight run instead of spawning a duplicate full pipeline.
        new_run_id = create_run_and_snapshot(
            client=client,
            keyword=keyword or "article",
            content_type="blog_post",
            reoptimize_source_html=source_html,
            created_by=user_id,
            source_ref=f"fanout_reopt:{cluster_id}:{old_suite_run_id}",
        )
        await orchestrate_run(new_run_id)

        new_score = None
        try:
            scored = await blog_page_score.score_run(new_run_id, user_id=user_id)
            new_score = scored.get("composite_score")
        except Exception as exc:  # noqa: BLE001 — score the improved run best-effort
            logger.info("fanout.new_score_skipped", extra={"run_id": new_run_id, "error": str(exc)})

        try:
            suite_mirror.reflect_reoptimized_run_to_fanout(
                cluster_id=cluster_id,
                session_id=session_id,
                suite_run_id=new_run_id,
                prior_article_json=article_row.get("article_json") or {},
            )
        except Exception as exc:  # noqa: BLE001 — reflection is best-effort; the suite run is improved regardless
            logger.warning(
                "fanout.reflect_failed",
                extra={"cluster_id": cluster_id, "run_id": new_run_id, "error": str(exc)},
            )
        return {"prev_score": prev_score, "new_score": new_score, "run_id": new_run_id}

    await _finish_job(job["id"], work)


def _persist_score(cluster_id: Optional[str], score, status_str) -> None:
    """Write the score onto the cluster's latest Fan-out article (score-only)."""
    if not cluster_id:
        return
    try:
        from fanout.writer import store as article_store

        row = article_store.get_latest_article(cluster_id)
        if row and row.get("id"):
            article_store.set_scores(row["id"], score, status_str)
    except Exception as exc:  # noqa: BLE001 — score persistence is a nicety, never fatal
        logger.warning("fanout.persist_score_failed", extra={"cluster_id": cluster_id, "error": str(exc)})


# ── Batch status (frontend poll) ─────────────────────────────────────────────
def _read_jobs(job_ids: list[str], scope_key: str, scope_value: str) -> list[dict]:
    """Statuses for the given reopt jobs, scoped so a caller only sees jobs whose
    payload[scope_key] matches (by session or by client). Returns
    {job_id, status, result, error}."""
    if not job_ids:
        return []
    rows = (
        _suite_sb().table("async_jobs")
        .select("id, status, result, error, payload, job_type")
        .in_("id", job_ids[:200])
        .execute()
    ).data or []
    out = []
    for r in rows:
        if (r.get("payload") or {}).get(scope_key) != scope_value:
            continue
        out.append({
            "job_id": r["id"],
            "status": r.get("status") or "queued",
            "result": r.get("result"),
            "error": r.get("error"),
        })
    return out


def read_jobs(session_id: str, job_ids: list[str]) -> list[dict]:
    """Session-scoped reopt job statuses (the Fan-out inline Articles surface)."""
    return _read_jobs(job_ids, "session_id", session_id)


def read_jobs_for_client(client_id: str, job_ids: list[str]) -> list[dict]:
    """Client-scoped reopt job statuses (the shared suite ReoptimizePanel)."""
    return _read_jobs(job_ids, "client_id", client_id)
