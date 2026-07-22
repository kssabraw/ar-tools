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
from services.page_structure_render import render_reference_structure

logger = logging.getLogger(__name__)

# ContextVar so every log emitted during a run carries the run_id automatically
run_id_ctx: ContextVar[str] = ContextVar("run_id", default="")

# ---------------------------------------------------------------------------
# Schema version registry (Engineering Spec §6.5)
# ---------------------------------------------------------------------------

EXPECTED_MODULE_VERSIONS: dict[str, str] = {
    "brief": "2.8",
    "sie": "1.4",
    "research": "1.1",
    "writer": "1.9",
    "sources_cited": "1.1",
    # Service-page content type (content_type='service_page')
    "service_brief": "1.2",
    "service_writer": "1.0",
}

WRITER_ACCEPTED_VERSIONS = {
    "1.9", "1.9-no-context", "1.9-degraded",
    # 1.8 kept accepted for in-flight / cached outputs from before the bump.
    "1.8", "1.8-no-context", "1.8-degraded",
}

# Per-module HTTP timeouts in seconds
MODULE_TIMEOUTS: dict[str, int] = {
    # Brief generator runs a heavy LLM fan-out (silo viability,
    # scope verification, framing, intent rewrite, persona, authority
    # ×3 pillars, editorial critique, etc.). Anthropic 429 rate
    # limiting during the silo viability phase routinely pushes total
    # duration to ~150s; 200s gives headroom without making timeouts
    # invisible.
    "brief": 200,
    # SIE on a cold (uncached) keyword: DataForSEO SERP + ScrapeOwl on
    # ~20 pages + Google NLP analyzeEntities per page + TextRazor per
    # page + Anthropic for entity dedup + OpenAI embeddings. Observed
    # ~195s on a fresh run with TextRazor 401s adding latency. Cache
    # hits are near-instant. 240s gives headroom for cold starts.
    "sie": 240,
    "research": 130,
    "writer": 600,  # writer makes many sequential LLM calls; allow up to 10m
    "sources_cited": 20,
    # service_brief runs its own SERP + competitor scrape/teardown + entity
    # extraction + synthesis (similar cost profile to brief); service_writer
    # makes several sequential LLM calls (like writer).
    "service_brief": 240,
    "service_writer": 600,
}

# Pipeline API endpoint paths
MODULE_PATHS: dict[str, str] = {
    "brief": "/brief",
    "sie": "/sie",
    "research": "/research",
    "writer": "/write",
    "sources_cited": "/sources-cited",
    "service_brief": "/service-brief",
    "service_writer": "/service-write",
}

# Pause before retrying a dropped connection so a Railway redeploy rollover has
# time to bring the replacement container up (swaps complete in a few seconds).
RETRY_BACKOFF_SECONDS = 3.0

# Hard wall-clock ceiling above the per-module httpx timeout. httpx's own read
# timeout should fire first, but it is enforced by this (heavily loaded, single)
# event loop's timer, and under load that timer can be starved: a research call
# budgeted at 130s was once observed stranded in `research_running` for ~17 min.
# asyncio.wait_for gives an independent, guaranteed cutoff so a slow or hung
# pipeline-api can never hold a run open indefinitely. The buffer lets the
# transport timeout win in the normal case (cleaner error text) while still
# capping the pathological case.
HARD_DEADLINE_BUFFER_SECONDS = 15.0


def _extract_schema_version(module: str, result: dict) -> str | None:
    if module == "brief":
        return (result.get("metadata") or {}).get("schema_version")
    if module == "research":
        return (result.get("citations_metadata") or {}).get("citations_schema_version")
    if module == "writer":
        return (result.get("metadata") or {}).get("schema_version")
    if module == "sources_cited":
        return (result.get("sources_cited_metadata") or {}).get("schema_version")
    if module in ("service_brief", "service_writer"):
        return (result.get("metadata") or {}).get("schema_version")
    # SIE returns it at the top level
    return result.get("schema_version")

NON_TERMINAL_STATUSES = {
    "queued",
    "brief_running",
    "sie_running",
    "research_running",
    "writer_running",
    "sources_cited_running",
    "service_brief_running",
    "service_writer_running",
    "service_scoring_running",
    "service_reopt_running",
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
    if status in {"brief_running", "sie_running", "service_brief_running"} and not error_stage:
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

    # Native task manager producer (PRD §11, opt-in): a completed run opens a
    # "Review & publish" task. Self-gated + best-effort inside.
    if status == "complete":
        from services import task_producers

        task_producers.on_run_completed(run_id)

        # Auto-illustration (hero + inline body images/charts). Gated inside on
        # the global flag AND the client's illustrate_content toggle; best-effort.
        from services.illustration import enqueue_illustrate_run

        enqueue_illustrate_run(run_id)


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
            response = await asyncio.wait_for(
                client.post(url, json=payload),
                timeout=timeout + HARD_DEADLINE_BUFFER_SECONDS,
            )
            duration_ms = int((time.perf_counter() - start) * 1000)

            if response.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}: {response.text[:500]}",
                    request=response.request,
                    response=response,
                )

            result = response.json()

    except (httpx.TransportError, httpx.HTTPStatusError, asyncio.TimeoutError) as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        # A blown hard deadline (asyncio.TimeoutError) is treated exactly like a
        # transport-level read timeout: retryable once, then surfaced as
        # module_timeout.
        is_timeout = isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError))
        is_5xx = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500
        # A transport error that isn't a timeout means the connection itself
        # failed before a response arrived — most commonly the pipeline-api
        # container was swapped out by a Railway redeploy mid-request
        # (httpx.RemoteProtocolError, "Server disconnected without sending a
        # response."), or a transient connect/read error. The response never
        # landed, so there's nothing half-applied to worry about; retrying once
        # sails through a rollover, which completes in seconds.
        is_conn_drop = isinstance(exc, httpx.TransportError) and not is_timeout

        if (is_timeout or is_5xx or is_conn_drop) and attempt == 1:
            logger.warning(
                "module_retry_attempt",
                extra={"run_id": run_id, "pipeline_module": module, "error": str(exc)},
            )
            await _fail_module_output(output_id, str(exc))
            # Give a redeploy rollover a moment to bring the new container up
            # before retrying a dropped connection (a timeout/5xx already burned
            # its own delay, so only pause for the fast-failing connection drop).
            if is_conn_drop:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
            return await _call_module(module, run_id, payload, attempt=2)

        await _fail_module_output(output_id, str(exc))
        if is_timeout:
            code = "module_timeout"
        elif is_conn_drop:
            code = "module_unavailable"
        else:
            code = "module_error"
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

    # PRD v1.4 §8.5 — when a brief (or service_brief) module_output
    # transitions to complete, enqueue the silo_dedup async job. Best-effort:
    # failures here log but do not affect the run.
    if module in ("brief", "service_brief"):
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
    # Blog posts mirror the client's own blog-post structure when one is configured
    # (the cached, client-agnostic brief can't carry client layout). The intro gets
    # the OPENING pattern; the body sections get the STRUCTURE style (heading depth,
    # length variation, recurring blocks) applied over the SEO-driven outline.
    blog_structure_entry = (snapshot.get("page_structures") or {}).get("blog_post")
    reference_page_structure = render_reference_structure(
        blog_structure_entry, "blog_post", mode="opening"
    )
    reference_page_body_structure = render_reference_structure(
        blog_structure_entry, "blog_post", mode="structure"
    )

    return {
        "run_id": run["id"],
        "attempt": 1,
        "brief_output": brief_output,
        "sie_output": sie_output,
        "research_output": research_output,
        # Per-run editorial guidance typed at run creation ("mention <brand>
        # as one of the top 10 best"). Rides the run row, never the cached
        # client-agnostic brief.
        "user_notes": (run.get("writer_notes") or "").strip() or None,
        "client_context": {
            "brand_guide_text": brand_guide_text,
            "brand_guide_format": brand_guide_format,
            "icp_text": icp_text,
            "icp_format": icp_format,
            "website_analysis": website_analysis,
            "website_analysis_unavailable": website_unavailable,
            "reference_page_structure": reference_page_structure,
            "reference_page_body_structure": reference_page_body_structure,
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


def _page_type_for(run: dict) -> str:
    """Map the run's content_type to the pipeline page_type. A location_page run
    drives the multi-service location-hub mode; everything else is 'service'."""
    return "location" if run.get("content_type") == "location_page" else "service"


def _run_services(run: dict) -> list[str]:
    """The services a location page must cover (persisted on the run)."""
    raw = run.get("services") or []
    return [str(s).strip() for s in raw if isinstance(raw, list) and str(s).strip()]


def _build_service_brief_payload(run: dict, snapshot: dict) -> dict:
    """Service / location Page Brief payload. The brief runs its own research;
    client context comes from the frozen snapshot. The snapshot's resolved
    icp_text already folds in the client's differentiators (see icp_service), so
    the wedge is available via icp_text even though structured differentiators
    aren't snapshotted separately (a v1 limitation).

    For a location page, `service` carries the location label, `page_type` is
    'location', `services` lists the services to cover, and the mirrored layout
    comes from the client's reference *location* page (not the service page)."""
    page_type = _page_type_for(run)
    is_location = page_type == "location"
    structures = snapshot.get("page_structures") or {}
    return {
        "run_id": run["id"],
        "attempt": 1,
        "service": (run.get("location") or run["keyword"]) if is_location else (run.get("service") or run["keyword"]),
        "primary_query": run["keyword"],
        "location": run.get("location"),
        "location_code": run.get("location_code") or 2840,
        "page_type": page_type,
        "services": _run_services(run),
        "client_context": {
            "brand_voice_text": snapshot.get("brand_guide_text") or "",
            "icp_text": snapshot.get("icp_text") or "",
            "website_analysis": snapshot.get("website_analysis"),
            # Mirror the client's own layout for this page type.
            "reference_page_structure": render_reference_structure(
                structures.get("location" if is_location else "service"),
                "location" if is_location else "service",
            ),
        },
    }


def _build_service_writer_payload(
    run: dict, service_brief_output: dict, snapshot: dict,
    source_deficiencies: list[dict] | None = None,
) -> dict:
    """Service/location writer payload. When `source_deficiencies` is provided (a
    reoptimize-of-live run), the first pass runs in reoptimize mode fed those
    deficiencies, so the generated page specifically fixes where the live page falls
    short. There are no `prior_sections` — the live page has no structured ones — so
    generation still follows the brief's architecture, just deficiency-guided."""
    payload = {
        "run_id": run["id"],
        "attempt": 1,
        "service_brief_output": service_brief_output,
        "page_type": _page_type_for(run),
        "location": run.get("location"),
        "services": _run_services(run),
        "client_context": {
            "brand_guide_text": snapshot.get("brand_guide_text") or "",
            "icp_text": snapshot.get("icp_text") or "",
            "website_analysis": snapshot.get("website_analysis"),
            "website_analysis_unavailable": snapshot.get("website_analysis_unavailable", False),
        },
    }
    if source_deficiencies:
        payload["mode"] = "reoptimize"
        payload["prior_sections"] = []
        payload["deficiencies"] = source_deficiencies
    return payload


async def _orchestrate_service_page(
    run_id: str, run: dict, snapshot: dict, completed: dict[str, dict]
) -> None:
    """Service-page pipeline: service_brief -> service_writer. Reuses the
    runs/module_outputs plumbing (silos + publish come for free). Resume-aware
    via `completed`, mirroring the blog path."""
    # Stage A: Service Page Brief
    if await _is_cancelled(run_id):
        raise CancellationError()
    brief_result: Any = completed.get("service_brief")
    if brief_result is None:
        await _set_run_status(run_id, "service_brief_running")
        brief_result = await _call_module(
            "service_brief", run_id, _build_service_brief_payload(run, snapshot)
        )

    # Stage B': for a reoptimize-of-live run, scrape + score the existing live page
    # so the writer's first pass is fed its deficiencies. Best-effort — a
    # scrape/score failure logs and falls back to a normal (non-reopt) generation.
    source_deficiencies: list[dict] | None = None
    source_url = run.get("reoptimize_source_url")
    if source_url and completed.get("service_writer") is None:
        try:
            from services.service_page_score import score_external_page

            await _set_run_status(run_id, "service_scoring_running")
            source_score = await score_external_page(run_id, source_url)
            source_deficiencies = source_score.get("deficiencies") or []
        except Exception as exc:
            logger.warning(
                "service_page_source_score_failed",
                extra={"run_id": run_id, "url": source_url, "error": str(exc)},
            )

    # Stage B: Service Page Writer
    if await _is_cancelled(run_id):
        raise CancellationError()
    if completed.get("service_writer") is None:
        await _set_run_status(run_id, "service_writer_running")
        await _call_module(
            "service_writer", run_id,
            _build_service_writer_payload(run, brief_result, snapshot, source_deficiencies),
        )

    # Stage C: auto score + (≤1) reoptimize. Best-effort — scoring/reopt failure
    # logs but never fails the run (the page already exists). Skipped on resume if
    # a score already exists.
    if await _is_cancelled(run_id):
        raise CancellationError()
    if completed.get("service_score") is None:
        try:
            from services.service_page_score import reoptimize_run, score_run, structural_deficiency

            await _set_run_status(run_id, "service_scoring_running")
            score = await score_run(run_id)
            deficiencies = list(score.get("deficiencies") or [])
            # Structural-fidelity gate: if the writer drifted from the client's
            # reference layout, fold the corrections into the SAME reopt pass as a
            # synthetic deficiency (no extra reopt beyond the content-score budget).
            struct_def = structural_deficiency(run, snapshot)
            if struct_def:
                deficiencies.append(struct_def)
            below_threshold = (score.get("composite_score") or 0) < settings.service_page_score_threshold
            if below_threshold or struct_def:
                await _set_run_status(run_id, "service_reopt_running")
                await reoptimize_run(run_id, deficiencies)
        except Exception as exc:
            logger.warning(
                "service_page_autoscore_failed",
                extra={"run_id": run_id, "error": str(exc)},
            )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


# Global cap on concurrently-EXECUTING runs. Every run-create request spawns an
# independent orchestrate_run background task, and each run fires brief+SIE in
# parallel (each a heavy Claude fan-out inside pipeline-api) — with no cap, N
# simultaneous run-creates multiplied straight into the shared Anthropic
# account's rate limit (the demand-side amplifier behind the 429 saturation).
# Excess runs simply wait here in their queued status; nothing is dropped.
# Lazily constructed so the semaphore binds to the running event loop.
_run_gate: Optional[asyncio.Semaphore] = None


def _get_run_gate() -> asyncio.Semaphore:
    global _run_gate
    if _run_gate is None:
        _run_gate = asyncio.Semaphore(max(1, settings.max_concurrent_runs))
    return _run_gate


async def orchestrate_run(run_id: str) -> None:
    """Full pipeline orchestration as a background task, gated by the global
    run-concurrency cap (`max_concurrent_runs`)."""
    gate = _get_run_gate()
    if gate.locked():
        logger.info("run_waiting_for_slot", extra={"run_id": run_id})
    async with gate:
        await _orchestrate_run_impl(run_id)


async def _orchestrate_run_impl(run_id: str) -> None:
    """The actual pipeline orchestration (see orchestrate_run)."""
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

        # Service-page content type runs a distinct two-stage pipeline
        # (service_brief -> service_writer); the blog 5-module pipeline below
        # is skipped entirely.
        if run.get("content_type") in ("service_page", "location_page"):
            await _orchestrate_service_page(run_id, run, snapshot, completed)
            await _set_run_status(run_id, "complete")
            await _update_total_cost(run_id)
            logger.info("run_complete", extra={"run_id": run_id})
            return

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
        # Append run_id to the error message so it surfaces in the UI.
        # Without it, the user has nothing to grep production logs for
        # when reporting a failure — "Error (brief): module_timeout"
        # is identical for every failed run.
        await _set_run_status(
            run_id,
            "failed",
            error_stage=exc.stage,
            error_message=f"{exc.cause} (run_id: {run_id})",
        )

    except Exception as exc:
        logger.exception("orchestrator.unhandled", extra={"run_id": run_id, "error": str(exc)})
        await _set_run_status(
            run_id, "failed", error_stage="unknown",
            error_message=f"{exc} (run_id: {run_id})",
        )


def should_resume(run: dict, max_resumes: int) -> bool:
    """Whether an orphaned run gets auto-resumed (vs marked failed). Pure.
    A missing resume_count (pre-migration rows) counts as 0."""
    if max_resumes <= 0:
        return False
    return int(run.get("resume_count") or 0) < max_resumes


# Auto-resume tasks are fire-and-forget; keep references so the event loop
# can't garbage-collect them mid-run (the standard create_task pattern).
_RESUME_TASKS: set = set()


def _spawn_resume(run_id: str) -> None:
    task = asyncio.create_task(orchestrate_run(run_id))
    _RESUME_TASKS.add(task)
    task.add_done_callback(_RESUME_TASKS.discard)


async def recover_stuck_runs() -> None:
    """On startup, recover runs stranded in non-terminal states by the previous
    process dying mid-run (deploy/crash — orchestrate_run is an in-process
    background task, so it doesn't survive a restart).

    Each orphaned run is RE-DISPATCHED through orchestrate_run, which loads its
    completed module_outputs and skips them — so a resume re-runs only the
    interrupted stage, not the whole pipeline. `resume_count` bounds the
    auto-resumes (`run_auto_resume_max`, default 2) so a run that keeps dying
    (e.g. one whose generation crashes the service) fails permanently instead
    of crash-looping; past the cap it fails with the old recovery message.
    Resumed runs respect the global run-concurrency gate like any other run."""
    try:
        result = (
            _sb()
            .table("runs")
            .select("id, status, resume_count")
            .in_("status", list(NON_TERMINAL_STATUSES))
            .execute()
        )
        stuck = result.data or []
        resumed = failed = 0
        for run in stuck:
            if should_resume(run, settings.run_auto_resume_max):
                attempt = int(run.get("resume_count") or 0) + 1
                logger.warning(
                    "startup_recovery_run_resumed",
                    extra={"run_id": run["id"], "stuck_status": run["status"],
                           "resume_attempt": attempt},
                )
                _sb().table("runs").update(
                    {"resume_count": attempt, "updated_at": "now()"}
                ).eq("id", run["id"]).execute()
                _spawn_resume(run["id"])
                resumed += 1
            else:
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
                failed += 1
        if stuck:
            logger.info(
                "startup_recovery_complete",
                extra={"resumed": resumed, "failed": failed},
            )
    except Exception as exc:
        logger.error("startup_recovery_failed", extra={"error": str(exc)})
