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
    "brief": "1.7",
    "sie": "1.0",
    "research": "1.1",
    "writer": "1.5",
    "sources_cited": "1.1",
}

WRITER_ACCEPTED_VERSIONS = {"1.5", "1.5-no-context", "1.5-degraded"}

# Per-module HTTP timeouts in seconds
MODULE_TIMEOUTS: dict[str, int] = {
    "brief": 130,
    "sie": 130,
    "research": 130,
    "writer": 100,
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


async def _create_module_output(run_id: str, module: str, input_payload: dict) -> str:
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

    # Validate schema version
    actual_version = result.get("schema_version")
    if module == "writer":
        if actual_version not in WRITER_ACCEPTED_VERSIONS:
            err = SchemaVersionMismatch(module, EXPECTED_MODULE_VERSIONS[module], actual_version)
            logger.error(
                "schema_version_mismatch",
                extra={
                    "run_id": run_id,
                    "module": module,
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
                    "module": module,
                    "expected": expected,
                    "actual": actual_version,
                },
            )
            await _fail_module_output(output_id, str(err))
            raise StageError(module, err)

    cost = result.get("cost_usd") or result.get("metadata", {}).get("cost_usd")
    module_version = actual_version or result.get("metadata", {}).get("schema_version")
    await _save_module_output(output_id, result, duration_ms, cost, module_version)

    logger.info(
        "stage_complete",
        extra={
            "run_id": run_id,
            "module": module,
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

        # Stage 1: Brief + SIE in parallel
        if await _is_cancelled(run_id):
            raise CancellationError()

        await _set_run_status(run_id, "brief_running")

        brief_payload = _build_brief_payload(run)
        sie_payload = _build_sie_payload(run)

        brief_result, sie_result = await asyncio.gather(
            _call_module("brief", run_id, brief_payload),
            _call_module("sie", run_id, sie_payload),
            return_exceptions=True,
        )

        if isinstance(brief_result, Exception):
            raise brief_result if isinstance(brief_result, StageError) else StageError("brief", brief_result)
        if isinstance(sie_result, Exception):
            raise sie_result if isinstance(sie_result, StageError) else StageError("sie", sie_result)

        # Check SIE cache hit and persist to run
        sie_cache_hit = sie_result.get("sie_cache_hit", False)
        _sb().table("runs").update({"sie_cache_hit": sie_cache_hit}).eq("id", run_id).execute()

        # Stage 2: Research
        if await _is_cancelled(run_id):
            raise CancellationError()

        await _set_run_status(run_id, "research_running")
        research_payload = _build_research_payload(run, brief_result)
        research_result = await _call_module("research", run_id, research_payload)

        # Stage 3: Writer
        if await _is_cancelled(run_id):
            raise CancellationError()

        await _set_run_status(run_id, "writer_running")
        writer_payload = _build_writer_payload(
            run, brief_result, sie_result, research_result, snapshot
        )
        writer_result = await _call_module("writer", run_id, writer_payload)

        # Stage 4: Sources Cited
        if await _is_cancelled(run_id):
            raise CancellationError()

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
