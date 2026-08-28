"""Standalone 'score an existing page' background jobs for the Blog + Service
writers.

Local SEO + Ecommerce already have run-free score jobs (their own action
families, polled via `.../jobs/status`). Blog + Service scoring was previously
per-run only (Stage B' of a reoptimize-existing run, which spawns a full run and
rewrites). This exposes a *run-free, check-only* score for those two so the
"Score" tab can grade a live URL / pasted content — entity usage + gaps, per the
8-engine rubric — WITHOUT spawning a run or rewriting anything.

Mirrors `backlink_explorer`: the ScoreResult is stored on the `async_jobs` row
and the frontend reads it from the poll. Scoring is observation, not output, so
it is deliberately NOT freeze-gated.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

JOB_TYPE = "score_external"
TOOLS = {"blog", "service"}


def enqueue(client_id: str, tool: str, params: dict, user_id: Optional[str] = None) -> str:
    """Enqueue a run-free score job for `tool` ('blog' | 'service'). Returns the
    job id; poll `get_status` and read the ScoreResult off the row."""
    if tool not in TOOLS:
        raise HTTPException(status_code=400, detail="unknown_score_tool")
    row = (
        get_supabase().table("async_jobs").insert({
            "job_type": JOB_TYPE,
            "entity_id": client_id,
            "payload": {**params, "tool": tool, "client_id": client_id, "user_id": user_id},
        }).execute()
    ).data[0]
    return row["id"]


def get_status(client_id: str, job_id: str) -> Optional[dict]:
    """Return {id, status, result, error} for a score job scoped to this client,
    or None if it isn't found (so ids can't be probed cross-client)."""
    rows = (
        get_supabase().table("async_jobs")
        .select("id, status, result, error")
        .eq("id", job_id).eq("entity_id", client_id).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


async def run_job(job: dict) -> None:
    """async_jobs handler for `score_external` — score the external page and store
    the ScoreResult on the job row. Best-effort: any failure records a reason the
    UI surfaces, never raises out of the worker."""
    payload = job.get("payload") or {}
    job_id = job["id"]
    sb = get_supabase()

    def _fail(reason: str) -> None:
        sb.table("async_jobs").update(
            {"status": "failed", "error": (reason or "score_failed")[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

    tool = payload.get("tool")
    client_id = payload.get("client_id")
    keyword = payload.get("keyword") or ""
    if not client_id:
        _fail("missing_client")
        return
    try:
        if tool == "blog":
            from services import blog_page_score

            result = await blog_page_score.score_external_client(
                client_id, keyword,
                source_url=payload.get("page_url"),
                source_html=payload.get("page_content"),
                entity_provider=payload.get("entity_provider"),
                user_id=payload.get("user_id"),
            )
        elif tool == "service":
            from services import service_page_score

            result = await service_page_score.score_external_client(
                client_id, keyword, payload.get("page_type") or "service_page",
                source_url=payload.get("page_url"),
                source_html=payload.get("page_content"),
                location=payload.get("location"),
                location_code=payload.get("location_code"),
                entity_provider=payload.get("entity_provider"),
                user_id=payload.get("user_id"),
            )
        else:
            _fail("unknown_score_tool")
            return
    except HTTPException as exc:
        _fail(str(getattr(exc, "detail", None) or "score_failed"))
        return
    except Exception as exc:  # noqa: BLE001 — provider / scrape error
        logger.warning("score_external.job_failed", extra={"tool": tool, "error": str(exc)})
        _fail("score_failed")
        return
    sb.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
