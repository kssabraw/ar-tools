"""Pipeline orchestrator — drives a run through all 5 module stages."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any, Optional

import httpx

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# ContextVar so every log emitted during a run carries the run_id automatically
run_id_ctx: ContextVar[str] = ContextVar("run_id", default="")

# ---------------------------------------------------------------------------
# Schema version registry (Engineering Spec §6.5)
# ---------------------------------------------------------------------------

EXPECTED_MODULE_VERSIONS: dict[str, str] = {
    "brief": "2.6",
    "sie": "1.4",
    "research": "1.1",
    "writer": "1.7",
    "sources_cited": "1.1",
}

WRITER_ACCEPTED_VERSIONS = {"1.7", "1.7-no-context", "1.7-degraded"}

# Per-module HTTP timeouts in seconds
MODULE_TIMEOUTS: dict[str, int] = {
    "brief": 130,
    "sie": 130,
    "research": 130,
    "writer": 600,  # writer makes many sequential LLM calls; allow up to 10m
    "sources_cited": 20,
}

# Pipeline API endpoint paths
MODULE_PATHS: dict[str, str] = {
    "brief": "/brief",
    "sie": "/sie",
    "research": "/research",
    "writer": "/write",
    "sources_cited": "/sources-cited",
}


def _extract_schema_version(module: str, result: dict) -> str | None:
    if module == "brief":
        return (result.get("metadata") or {}).get("schema_version")
    if module == "research":
        return (result.get("citations_metadata") or {}).get("citations_schema_version")
    if module == "writer":
        return (result.get("metadata") or {}).get("schema_version")
    if module == "sources_cited":
        return (result.get("sources_cited_metadata") or {}).get("schema_version")
    # SIE returns it at the top level
    return result.get("schema_version")

NON_TERMINAL_STATUSES = {
    "queued",
    "brief_running",
    "sie_running",
    "research_running",
    "writer_running",
    "sources_cited_running",
}


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class StageError(Exception):
    def __init__(self, stage: str, cause: Exception):
        super().__init__(str(cause))
        self.stage = stage
        self.cause = cause


class SchemaVersionMismatch(Exception):
    def __init__(self, module: str, expected: str, actual: Optional[str]):
        msg = f"schema version mismatch: expected {expected}, got {actual}"
        super().__init__(msg)
        self.module = module
        self.expected = expected
        self.actual = actual


class CancellationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------


def _sb():
    return get_supabase()


async def _set_run_status(
    run_id: str,
    status: str,
    error_stage: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    updates: dict[str, Any] = {"status": status, "updated_at": "now()"}
    if status in {"brief_running", "sie_running"} and not error_stage:
        updates["started_at"] = "now()"
    if status in ("complete", "failed", "cancelled"):
        updates["completed_at"] = "now()"
    if error_stage is not None:
        updates["error_stage"] = error_stage
    if error_message is not None:
        updates["error_message"] = error_message[:2000]
    _sb().table("runs").update(updates).eq("id", run_id).execute()

    # PRD v1.4 §7.7.3 — when a run transitions to complete/failed, sync
    # the silo candidate that promoted it (if any). On complete: status
    # → 'published'. On failed: stay 'published' if the candidate was
    # previously published (re-promotion failure preserves history),
    # otherwise → 'approved' with last_promotion_failed_at set.
    if status in ("complete", "failed"):
        await _sync_silo_promotion_status(run_id, run_status=status)


async def _sync_silo_promotion_status(run_id: str, run_status: str) -> None:
    """Update the silo candidate (if any) that promoted this run."""
    try:
        match = (
            _sb()
            .table("silo_candidates")
            .select("id, status, source_run_ids")
            .eq("promoted_to_run_id", run_id)
            .limit(1)
            .execute()
        )
        rows = match.data or []
        if not rows:
            return
        silo = rows[0]

        if run_status == "complete":
            _sb().table("silo_candidates").update(
                {
                    "status": "published",
                    "last_promotion_failed_at": None,
                }
            ).eq("id", silo["id"]).execute()
            return

        # run_status == "failed"
        # Detect "previously published": any prior run for this silo
        # (in source_run_ids) that reached state=complete.
        prior_run_ids = [
            r for r in (silo.get("source_run_ids") or []) if r != run_id
        ]
        was_previously_published = False
        if prior_run_ids:
            prior_runs = (
                _sb()
                .table("runs")
                .select("id, status")
                .in_("id", prior_run_ids)
                .eq("status", "complete")
                .execute()
            )
            was_previously_published = bool(prior_runs.data)

        next_status = "published" if was_previously_published else "approved"
        _sb().table("silo_candidates").update(
            {
                "status": next_status,
                "last_promotion_failed_at": "now()",
            }
        ).eq("id", silo["id"]).execute()
    except Exception as exc:
        logger.warning(
            "silo_status_sync_failed",
            extra={"run_id": run_id, "error": str(exc)},
        )


async def _is_cancelled(run_id: str) -> bool:
    result = _sb().table("runs").select("status").eq("id", run_id).single().execute()
    return (result.data or {}).get("status") == "cancelled"


async def _get_run(run_id: str) -> dict:
    result = _sb().table("runs").select("*").eq("id", run_id).single().execute()
    return result.data or {}


async def _get_snapshot(run_id: str) -> dict:
    result = (
        _sb()
        .table("client_context_snapshots")
        .select("*")
        .eq("run_id", run_id)
        .single()
        .execute()
    )
    return result.data or {}


async def _load_completed_outputs(run_id: str) -> dict[str, dict]:
    """Return {module: output_payload} for all module_outputs rows already
    marked complete. Used by the orchestrator to skip stages on resume."""
    result = (
        _sb()
        .table("module_outputs")
        .select("module, status, output_payload")
        .eq("run_id", run_id)
        .eq("status", "complete")
        .execute()
    )
    out: dict[str, dict] = {}
    for row in result.data or []:
        payload = row.get("output_payload")
        if payload:
            out[row["module"]] = payload
    return out


async def _create_module_output(run_id: str, module: str, input_payload: dict) -> str:
    try:
        result = (
            _sb()
            .table("module_outputs")
            .insert(
                {
                    "run_id": run_id,
                    "module": module,
                    "status": "running",
                    "input_payload": input_payload,
                }
            )
            .execute()
        )
        return (result.data or [{}])[0].get("id", "")
    except Exception as exc:
        # Stale row from a prior crashed run — reset it and reuse its ID
        if "23505" not in str(exc):
            raise
        existing = (
            _sb()
            .table("module_outputs")
            .select("id")
            .eq("run_id", run_id)
            .eq("module", module)
            .order("attempt_number", desc=True)
            .limit(1)
            .execute()
        )
        row_id = (existing.data or [{}])[0].get("id", "")
        _sb().table("module_outputs").update(
            {
                "status": "running",
                "input_payload": input_payload,
                "output_payload": None,
                "completed_at": None,
            }
        ).eq("id", row_id).execute()
        logger.warning(
            "module_output_row_reset",
            extra={"run_id": run_id, "pipeline_module": module, "row_id": row_id},
        )
        return row_id


async def _save_module_output(
    output_id: str,
    result: dict,
    duration_ms: int,
    cost_usd: Optional[float],
    module_version: Optional[str],
) -> None:
    _sb().table("module_outputs").update(
        {
            "status": "complete",
            "output_payload": result,
            "duration_ms": duration_ms,
            "cost_usd": cost_usd,
            "module_version": module_version,
            "completed_at": "now()",
        }
    ).eq("id", output_id).execute()


async def _fail_module_output(output_id: str, error: str) -> None:
    _sb().table("module_outputs").update(
        {"status": "failed", "completed_at": "now()"}
    ).eq("id", output_id).execute()


async def _update_total_cost(run_id: str) -> None:
    result = (
        _sb()
        .table("module_outputs")
        .select("cost_usd")
        .eq("run_id", run_id)
        .execute()
    )
    rows = result.data or []
    total = sum(float(r.get("cost_usd") or 0) for r in rows)
    _sb().table("runs").update({"total_cost_usd": total}).eq("id", run_id).execute()


# ---------------------------------------------------------------------------
# HTTP module calls
# ---------------------------------------------------------------------------


async def _call_module(
    module: str, run_id: str, payload: dict, attempt: int = 1
) -> dict:
    """POST to a pipeline-api module, persist output, validate schema version."""
    output_id = await _create_module_output(run_id, module, payload)
    path = MODULE_PATHS[module]
    url = f"{settings.pipeline_api_url}{path}"
    timeout = MODULE_TIMEOUTS[module]

    logger.info(
        "stage_started",
        extra={"run_id": run_id, "pipeline_module": module, "attempt": attempt},
    )
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            duration_ms = int((time.perf_counter() - start) * 1000)

            if response.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}: {response.text[:500]}",
                    request=response.request,
                    response=response,
                )

            result = response.json()

    except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        is_timeout = isinstance(exc, httpx.TimeoutException)
        is_5xx = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500

        if (is_timeout or is_5xx) and attempt == 1:
            logger.warning(
                "module_retry_attempt",
                extra={"run_id": run_id, "pipeline_module": module, "error": str(exc)},
            )
            await _fail_module_output(output_id, str(exc))
            return await _call_module(module, run_id, payload, attempt=2)

        await _fail_module_output(output_id, str(exc))
        code = "module_timeout" if is_timeout else "module_error"
        raise StageError(module, Exception(f"{code}: {exc}")) from exc

    except Exception as exc:
        await _fail_module_output(output_id, str(exc))
        raise StageError(module, exc) from exc

    # Validate schema version. Each module returns it in a different shape:
    #   brief         -> metadata.schema_version
    #   sie           -> schema_version (top level)
    #   research      -> citations_metadata.citations_schema_version
    #   writer        -> metadata.schema_version
    #   sources_cited -> sources_cited_metadata.schema_version
    actual_version = _extract_schema_version(module, result)
    if module == "writer":
        if actual_version not in WRITER_ACCEPTED_VERSIONS:
            err = SchemaVersionMismatch(module, EXPECTED_MODULE_VERSIONS[module], actual_version)
            logger.error(
                "schema_version_mismatch",
                extra={
                    "run_id": run_id,
                    "pipeline_module": module,
                    "expected": EXPECTED_MODULE_VERSIONS[module],
                    "actual": actual_version,
                },
            )
            await _fail_module_output(output_id, str(err))
            raise StageError(module, err)
        if actual_version != "1.5":
            logger.warning(
                "writer_fallback_version",
                extra={"run_id": run_id, "actual_version": actual_version},
            )
    else:
        expected = EXPECTED_MODULE_VERSIONS[module]
        if actual_version != expected:
            err = SchemaVersionMismatch(module, expected, actual_version)
            logger.error(
                "schema_version_mismatch",
                extra={
                    "run_id": run_id,
                    "pipeline_module": module,
                    "expected": expected,
                    "actual": actual_version,
                },
            )
            await _fail_module_output(output_id, str(err))
            raise StageError(module, err)

    cost = result.get("cost_usd") or result.get("metadata", {}).get("cost_usd")
    await _save_module_output(output_id, result, duration_ms, cost, actual_version)

    # PRD v1.4 §8.5 — when a brief module_output transitions to complete,
    # enqueue the silo_dedup async job. Best-effort: failures here log
    # but do not affect the run.
    if module == "brief":
        try:
            run_row = (
                _sb()
                .table("runs")
                .select("client_id")
                .eq("id", run_id)
                .single()
                .execute()
            ).data or {}
            client_id = run_row.get("client_id")
            if client_id:
                from services.silo_dedup import enqueue_silo_dedup
                enqueue_silo_dedup(
                    module_output_id=output_id,
                    run_id=run_id,
                    client_id=client_id,
                )
        except Exception as exc:
            logger.warning(
                "silo_dedup_enqueue_skipped",
                extra={"run_id": run_id, "error": str(exc)},
            )

    logger.info(
        "stage_complete",
        extra={
            "run_id": run_id,
            "pipeline_module": module,
            "duration_ms": duration_ms,
            "cost_usd": cost,
        },
    )
    return result


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _build_brief_payload(run: dict) -> dict:
    return {
        "run_id": run["id"],
        "attempt": 1,
        "keyword": run["keyword"],
        "location_code": 2840,  # US default
        "intent_override": run.get("intent_override"),
        # PRD v2.6 — when the user picks "regenerate" on the cache-
        # decision modal, the run row carries brief_force_refresh=True
        # and the brief generator skips its cache lookup.
        "force_refresh": run.get("brief_force_refresh", False),
    }


def _build_sie_payload(run: dict) -> dict:
    return {
        "run_id": run["id"],
        "attempt": 1,
        "keyword": run["keyword"],
        "location_code": 2840,
        "outlier_mode": run.get("sie_outlier_mode", "safe"),
        "force_refresh": run.get("sie_force_refresh", False),
    }


def _build_research_payload(run: dict, brief_output: dict) -> dict:
    return {
        "run_id": run["id"],
        "attempt": 1,
        "keyword": run["keyword"],
        "brief_output": brief_output,
    }


def _build_writer_payload(
    run: dict,
    brief_output: dict,
    sie_output: dict,
    research_output: dict,
    snapshot: dict,
) -> dict:
    brand_guide_text = snapshot.get("brand_guide_text") or ""
    brand_guide_format = snapshot.get("brand_guide_format") or "text"
    icp_text = snapshot.get("icp_text") or ""
    icp_format = snapshot.get("icp_format") or "text"
    website_analysis = snapshot.get("website_analysis")
    website_unavailable = snapshot.get("website_analysis_unavailable", False)

    return {
        "run_id": run["id"],
        "attempt": 1,
        "brief_output": brief_output,
        "sie_output": sie_output,
        "research_output": research_output,
        "client_context": {
            "brand_guide_text": brand_guide_text,
            "brand_guide_format": brand_guide_format,
            "icp_text": icp_text,
            "icp_format": icp_format,
            "website_analysis": website_analysis,
            "website_analysis_unavailable": website_unavailable,
        },
    }


def _build_sources_cited_payload(
    run: dict, writer_output: dict, research_output: dict
) -> dict:
    return {
        "run_id": run["id"],
        "attempt": 1,
        "writer_output": writer_output,
        "research_output": research_output,
    }


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


async def orchestrate_run(run_id: str) -> None:
    """Full pipeline orchestration as a background task."""
    run_id_ctx.set(run_id)
    logger.info("run_dispatched", extra={"run_id": run_id})

    try:
        run = await _get_run(run_id)
        snapshot = await _get_snapshot(run_id)
        completed = await _load_completed_outputs(run_id)
        if completed:
            logger.info(
                "resuming_run",
                extra={"run_id": run_id, "completed_stages": list(completed.keys())},
            )

        # Stage 1: Brief + SIE in parallel (skip whichever are already complete)
        if await _is_cancelled(run_id):
            raise CancellationError()

        brief_result: Any = completed.get("brief")
        sie_result: Any = completed.get("sie")

        pending: list[tuple[str, Any]] = []
        if brief_result is None:
            pending.append(("brief", _call_module("brief", run_id, _build_brief_payload(run))))
        if sie_result is None:
            pending.append(("sie", _call_module("sie", run_id, _build_sie_payload(run))))

        if pending:
            await _set_run_status(run_id, "brief_running")
            results = await asyncio.gather(*[c for _, c in pending], return_exceptions=True)
            for (name, _), res in zip(pending, results):
                if isinstance(res, Exception):
                    raise res if isinstance(res, StageError) else StageError(name, res)
                if name == "brief":
                    brief_result = res
                else:
                    sie_result = res

        # Persist SIE cache hit (only meaningful when SIE actually ran)
        sie_cache_hit = sie_result.get("sie_cache_hit", False)
        _sb().table("runs").update({"sie_cache_hit": sie_cache_hit}).eq("id", run_id).execute()

        # Stage 2: Research
        if await _is_cancelled(run_id):
            raise CancellationError()

        research_result = completed.get("research")
        if research_result is None:
            await _set_run_status(run_id, "research_running")
            research_payload = _build_research_payload(run, brief_result)
            research_result = await _call_module("research", run_id, research_payload)

        # Stage 3: Writer
        if await _is_cancelled(run_id):
            raise CancellationError()

        writer_result = completed.get("writer")
        if writer_result is None:
            await _set_run_status(run_id, "writer_running")
            writer_payload = _build_writer_payload(
                run, brief_result, sie_result, research_result, snapshot
            )
            writer_result = await _call_module("writer", run_id, writer_payload)

        # Stage 4: Sources Cited
        if await _is_cancelled(run_id):
            raise CancellationError()

        if completed.get("sources_cited") is None:
            await _set_run_status(run_id, "sources_cited_running")
            sources_payload = _build_sources_cited_payload(run, writer_result, research_result)
            await _call_module("sources_cited", run_id, sources_payload)

        # Complete
        await _set_run_status(run_id, "complete")
        await _update_total_cost(run_id)
        logger.info("run_complete", extra={"run_id": run_id})

    except CancellationError:
        logger.info("run_cancelled", extra={"run_id": run_id})

    except StageError as exc:
        logger.error(
            "stage_failed",
            extra={"run_id": run_id, "stage": exc.stage, "error": str(exc.cause)},
        )
        await _set_run_status(
            run_id,
            "failed",
            error_stage=exc.stage,
            error_message=str(exc.cause),
        )

    except Exception as exc:
        logger.exception("orchestrator.unhandled", extra={"run_id": run_id, "error": str(exc)})
        await _set_run_status(
            run_id, "failed", error_stage="unknown", error_message=str(exc)
        )


async def recover_stuck_runs() -> None:
    """On startup, mark any runs stuck in non-terminal states as failed."""
    try:
        result = (
            _sb()
            .table("runs")
            .select("id, status")
            .in_("status", list(NON_TERMINAL_STATUSES))
            .execute()
        )
        stuck = result.data or []
        for run in stuck:
            logger.warning(
                "startup_recovery_run_failed",
                extra={"run_id": run["id"], "stuck_status": run["status"]},
            )
            await _set_run_status(
                run["id"],
                "failed",
                error_stage="recovery",
                error_message="Service restarted mid-run. Please re-run.",
            )
        if stuck:
            logger.info("startup_recovery_complete", extra={"recovered": len(stuck)})
    except Exception as exc:
        logger.error("startup_recovery_failed", extra={"error": str(exc)})
