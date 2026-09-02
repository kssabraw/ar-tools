"""Local SEO — service × location matrix: the store + orchestration half
(Phase 1 of docs/modules/local-seo-matrix-plan-v1_0.md).

Everything with I/O lives here; every decision is delegated to the pure helpers
in `local_seo_matrix`. Reuses, never re-implements:

  * `local_seo_targets.build_matrix_silos` (#953) — the cross product;
  * `local_seo_silo._build_site_url_list` + `_to_items` (#951) — coverage
    marking (found / on_site / missing);
  * `local_seo_silo._generate_service_pages` / `_neighborhoods_for_city` +
    `target_cities.resolve_target_cities` — the two Suggest buttons;
  * `local_seo_service._bulk_scheduled_at` + the `local_seo_generate` job — the
    immediate run (one staggered job per cell, payload carrying `matrix_cell_id`).

Cell state is reconciled **on read** (plan §5.1): `get_matrix` looks each
in-flight cell's job up and brings the cell up to date, so a missed poll can
never strand a cell and no worker hook is needed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Optional

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import local_seo_matrix as core
from services import local_seo_silo, locations_service, target_cities
from services.local_seo_service import _bulk_scheduled_at

logger = logging.getLogger(__name__)

_MATRIX_COLS = (
    "id, client_id, name, location, location_code, services, locations, url_pattern, "
    "base_url, page_template_url, entity_provider, publish_destination, publish_status, "
    "release_enabled, release_mode, release_weekday, release_day_of_month, "
    "release_per_count, release_status, release_next_run_at, release_last_run_at, "
    "created_by, created_at, updated_at"
)
_CELL_COLS = (
    "id, matrix_id, client_id, service_label, service_slug, location_name, location_slug, "
    "service_order, location_order, keyword, path, status, page_id, job_id, url, "
    "released_at, link_coverage, error, updated_at"
)
_PAGE_COLS = "id, page_title, composite_score, composite_status, published_url, published_doc_url"

SUGGEST_JOB_TYPE = "local_seo_matrix_suggest"


# ── reads ─────────────────────────────────────────────────────────────────────


def _matrix_row(matrix_id: str, client_id: str) -> dict:
    res = (
        get_supabase()
        .table("local_seo_matrices")
        .select(_MATRIX_COLS)
        .eq("id", matrix_id)
        .eq("client_id", client_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="matrix_not_found")
    return res.data[0]


def _cells(matrix_id: str) -> list[dict]:
    res = (
        get_supabase()
        .table("local_seo_matrix_cells")
        .select(_CELL_COLS)
        .eq("matrix_id", matrix_id)
        .order("location_order")
        .order("service_order")
        .execute()
    )
    return res.data or []


def _attach_pages(cells: list[dict]) -> None:
    """Join the few page fields the grid shows (title / score / published URL)."""
    ids = [c["page_id"] for c in cells if c.get("page_id")]
    if not ids:
        return
    try:
        rows = (
            get_supabase().table("local_seo_pages").select(_PAGE_COLS).in_("id", ids).execute().data
            or []
        )
    except Exception as exc:  # noqa: BLE001 — a page join is decoration, never a failure
        logger.warning("local_seo_matrix.page_join_failed", extra={"error": str(exc)})
        return
    by_id = {r["id"]: r for r in rows}
    for c in cells:
        p = by_id.get(c.get("page_id"))
        if not p:
            continue
        c["page_title"] = p.get("page_title")
        c["composite_score"] = p.get("composite_score")
        c["composite_status"] = p.get("composite_status")
        c["published_url"] = p.get("published_url") or p.get("published_doc_url")


def _apply_patches(patches: Iterable[tuple[str, dict]]) -> int:
    n = 0
    sb = get_supabase()
    for cell_id, patch in patches:
        sb.table("local_seo_matrix_cells").update({**patch, "updated_at": "now()"}).eq(
            "id", cell_id
        ).execute()
        n += 1
    return n


def reconcile(matrix_id: str) -> int:
    """Bring every in-flight cell up to date from its job row. Returns the number
    of cells patched. Best-effort — a read failure leaves the cells as they are."""
    cells = _cells(matrix_id)
    job_ids = [str(c["job_id"]) for c in cells if c.get("status") in core._IN_FLIGHT and c.get("job_id")]
    if not job_ids:
        return 0
    try:
        rows = (
            get_supabase()
            .table("async_jobs")
            .select("id, status, result, error")
            .in_("id", job_ids)
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("local_seo_matrix.reconcile_read_failed", extra={"matrix_id": matrix_id, "error": str(exc)})
        return 0
    jobs = {str(r["id"]): r for r in rows}
    return _apply_patches(core.reconcile_cell_updates(cells, jobs))


def list_matrices(client_id: str) -> list[dict]:
    sb = get_supabase()
    rows = (
        sb.table("local_seo_matrices")
        .select(_MATRIX_COLS)
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    if not rows:
        return []
    cells = (
        sb.table("local_seo_matrix_cells")
        .select("matrix_id, status")
        .eq("client_id", client_id)
        .execute()
        .data
        or []
    )
    by_matrix: dict[str, list[dict]] = {}
    for c in cells:
        by_matrix.setdefault(c["matrix_id"], []).append(c)
    for m in rows:
        m["coverage"] = core.coverage_counts(by_matrix.get(m["id"], []))
    return rows


def get_matrix(matrix_id: str, client_id: str, *, do_reconcile: bool = True) -> dict:
    """The matrix + its cells (location-major), reconciled, with page fields joined
    and the coverage rollup."""
    matrix = _matrix_row(matrix_id, client_id)
    if do_reconcile:
        reconcile(matrix_id)
    cells = _cells(matrix_id)
    _attach_pages(cells)
    matrix["cells"] = cells
    matrix["coverage"] = core.coverage_counts(cells)
    matrix.setdefault("degraded_notes", [])
    return matrix


# ── create / update / delete ──────────────────────────────────────────────────


def _seed_city(location: str) -> str:
    return local_seo_silo._parse_area(location)[0] or (location or "").strip()


def _validate_pattern(pattern: Optional[str]) -> str:
    p = (pattern or "").strip() or core.DEFAULT_URL_PATTERN
    errors = core.validate_url_pattern(p)
    if errors:
        raise HTTPException(status_code=400, detail=errors[0])
    return p


def _default_base_url(client: dict) -> Optional[str]:
    site = (client.get("gbp") or {}).get("website") or client.get("website_url") or ""
    return site.strip().rstrip("/") or None


async def create_matrix(client_id: str, body: dict, user_id: str) -> dict:
    """Create the matrix + its cells, then mark coverage. `body` is the
    `MatrixCreateRequest` dump."""
    client = local_seo_silo._get_client(client_id)
    location, location_code = await locations_service.resolve_location(
        client, body["location"], body.get("location_code")
    )
    pattern = _validate_pattern(body.get("url_pattern"))
    services = core.normalize_services(body.get("services") or [])
    locations = core.normalize_locations(body.get("locations") or [])
    if not services or not locations:
        raise HTTPException(status_code=400, detail="matrix_axes_empty")

    sb = get_supabase()
    row = {
        "client_id": client_id,
        "name": (body.get("name") or "").strip() or f"{services[0]['label']} × {len(locations)} locations",
        "location": location,
        "location_code": location_code,
        "services": services,
        "locations": locations,
        "url_pattern": pattern,
        "base_url": (body.get("base_url") or "").strip().rstrip("/") or _default_base_url(client),
        "page_template_url": (body.get("page_template_url") or "").strip() or None,
        "entity_provider": body.get("entity_provider") or None,
        "publish_destination": body.get("publish_destination") or "google_docs",
        "publish_status": body.get("publish_status") or "draft",
        "created_by": user_id,
    }
    matrix = sb.table("local_seo_matrices").insert(row).execute().data[0]

    cells = core.build_cells(
        [s["label"] for s in services],
        [l["name"] for l in locations],
        url_pattern=pattern,
        seed_city=_seed_city(location),
    )
    if cells:
        sb.table("local_seo_matrix_cells").insert(
            [{**c, "matrix_id": matrix["id"], "client_id": client_id} for c in cells]
        ).execute()

    notes = await mark_coverage(matrix["id"], client_id)
    out = get_matrix(matrix["id"], client_id, do_reconcile=False)
    out["degraded_notes"] = notes
    return out


async def update_matrix(matrix_id: str, client_id: str, body: dict) -> dict:
    """Edit settings and/or axes. An axis edit gap-fills (plan §3.1): new cells
    are inserted `missing`, pageless removed cells deleted, removed cells WITH a
    page parked as `skipped`, and a reappearing parked cell un-parked. A URL
    pattern change re-renders every cell's path (their links are planned, not
    live, until published)."""
    matrix = _matrix_row(matrix_id, client_id)
    sb = get_supabase()
    patch: dict = {}
    for key in ("name", "base_url", "page_template_url", "entity_provider", "publish_destination", "publish_status"):
        if body.get(key) is not None:
            val = body[key]
            patch[key] = (val.strip().rstrip("/") if key == "base_url" else val.strip()) if isinstance(val, str) else val
            if key in ("base_url", "page_template_url", "entity_provider") and not patch[key]:
                patch[key] = None

    pattern = matrix["url_pattern"]
    if body.get("url_pattern") is not None:
        pattern = _validate_pattern(body["url_pattern"])
        patch["url_pattern"] = pattern

    services = core.normalize_services(body["services"]) if body.get("services") is not None else matrix["services"]
    locations = core.normalize_locations(body["locations"]) if body.get("locations") is not None else matrix["locations"]
    if not services or not locations:
        raise HTTPException(status_code=400, detail="matrix_axes_empty")
    axes_changed = services != matrix["services"] or locations != matrix["locations"]
    if axes_changed:
        patch["services"] = services
        patch["locations"] = locations

    if patch:
        sb.table("local_seo_matrices").update({**patch, "updated_at": "now()"}).eq("id", matrix_id).execute()

    notes: list[str] = []
    if axes_changed or "url_pattern" in patch:
        existing = _cells(matrix_id)
        desired = core.build_cells(
            [s["label"] for s in services],
            [l["name"] for l in locations],
            url_pattern=pattern,
            seed_city=_seed_city(matrix["location"]),
        )
        diff = core.diff_cells(existing, desired)
        if diff["add"]:
            sb.table("local_seo_matrix_cells").insert(
                [{**c, "matrix_id": matrix_id, "client_id": client_id} for c in diff["add"]]
            ).execute()
        if diff["remove"]:
            sb.table("local_seo_matrix_cells").delete().in_("id", [c["id"] for c in diff["remove"]]).execute()
        for c in diff["skip"]:
            if c.get("status") != "skipped":
                _apply_patches([(c["id"], {"status": "skipped"})])
        # Keep: refresh axis positions + path (pattern/order may have moved); un-park.
        desired_by_key = {core.cell_key(c): c for c in desired}
        for c in diff["keep"]:
            d = desired_by_key[core.cell_key(c)]
            cell_patch: dict = {}
            for k in ("service_order", "location_order", "path", "service_label", "location_name"):
                if c.get(k) != d.get(k):
                    cell_patch[k] = d[k]
            if c.get("status") == "skipped":
                cell_patch["status"] = "done" if c.get("page_id") else "missing"
            if cell_patch:
                _apply_patches([(c["id"], cell_patch)])
        if axes_changed:
            notes = await mark_coverage(matrix_id, client_id)

    out = get_matrix(matrix_id, client_id)
    out["degraded_notes"] = notes
    return out


def delete_matrix(matrix_id: str, client_id: str) -> dict:
    """Delete the matrix (cells cascade). Pages are never touched."""
    _matrix_row(matrix_id, client_id)
    get_supabase().table("local_seo_matrices").delete().eq("id", matrix_id).execute()
    return {"deleted": True}


# ── coverage marking (#951 / #953, reused) ────────────────────────────────────


async def mark_coverage(matrix_id: str, client_id: str) -> list[str]:
    """Re-mark every coverage-state cell found / on_site / missing against the
    client's live site + in-tool pages — the exact marking Plan Silo and the
    one-shot matrix use. Never touches a cell that is in flight, done, published
    or parked. Returns the degraded notes."""
    matrix = _matrix_row(matrix_id, client_id)
    cells = _cells(matrix_id)
    eligible = [c for c in cells if c.get("status") in core._COVERAGE_STATUSES]
    if not eligible:
        return []
    seed_city = _seed_city(matrix["location"])
    silos = core.cells_to_silos(eligible, seed_city)
    site_urls, site_note = await local_seo_silo._build_site_url_list(client_id, matrix.get("location_code"))
    items = await asyncio.to_thread(local_seo_silo._to_items, silos, client_id, site_urls, seed_city)
    _apply_patches(core.apply_coverage(eligible, items))
    return [site_note] if site_note else []


async def recheck(matrix_id: str, client_id: str) -> dict:
    before = {c["id"]: (c.get("status"), c.get("url")) for c in _cells(matrix_id)}
    notes = await mark_coverage(matrix_id, client_id)
    after = _cells(matrix_id)
    changed = sum(1 for c in after if before.get(c["id"]) != (c.get("status"), c.get("url")))
    return {"changed": changed, "coverage": core.coverage_counts(after), "degraded_notes": notes}


# ── estimate + immediate run ──────────────────────────────────────────────────


def _runnable(matrix_id: str, client_id: str, cell_ids: Optional[list[str]], include_covered: bool) -> tuple[dict, list[dict], list[dict]]:
    matrix = _matrix_row(matrix_id, client_id)
    reconcile(matrix_id)
    cells = _cells(matrix_id)
    selected = core.select_runnable(cells, cell_ids, include_covered=include_covered)
    return matrix, cells, selected


def estimate_run(
    matrix_id: str, client_id: str, cell_ids: Optional[list[str]] = None,
    include_covered: bool = False, signoff_acknowledged: bool = False,
) -> dict:
    _, cells, selected = _runnable(matrix_id, client_id, cell_ids, include_covered)
    est = core.estimate(
        len(selected),
        cost_per_page_usd=settings.local_seo_matrix_cost_per_page_usd,
        minutes_per_page=settings.local_seo_matrix_minutes_per_page,
    )
    est["gates"] = core.scale_gates(
        len(cells), len(selected),
        max_per_run=settings.local_seo_matrix_max_cells_per_run,
        signoff_acknowledged=signoff_acknowledged,
    )
    est["cell_ids"] = [c["id"] for c in selected]
    return est


def _location_for_cell(matrix: dict, cell: dict) -> tuple[str, Optional[int]]:
    """A location row with its own DataForSEO code generates at that code; every
    other cell generates at the metro anchor (plan §3.2)."""
    for row in matrix.get("locations") or []:
        if row.get("slug") == cell.get("location_slug") and row.get("location_code"):
            return (row.get("canonical") or row.get("name") or matrix["location"], int(row["location_code"]))
    return matrix["location"], matrix.get("location_code")


def start_generate(
    matrix_id: str, client_id: str, user_id: str, *,
    cell_ids: Optional[list[str]] = None, include_covered: bool = False,
    signoff_acknowledged: bool = False, force_refresh: bool = False,
) -> dict:
    """Enqueue one `local_seo_generate` job per selected cell (staggered like every
    bulk flow) and flip the cells to `queued`. Gates first: a blocking gate is a
    409 (`matrix_signoff_required` — acknowledgeable) or 400 (`matrix_cell_limit`)."""
    matrix, cells, selected = _runnable(matrix_id, client_id, cell_ids, include_covered)
    est = core.estimate(
        len(selected),
        cost_per_page_usd=settings.local_seo_matrix_cost_per_page_usd,
        minutes_per_page=settings.local_seo_matrix_minutes_per_page,
    )
    gates = core.scale_gates(
        len(cells), len(selected),
        max_per_run=settings.local_seo_matrix_max_cells_per_run,
        signoff_acknowledged=signoff_acknowledged,
    )
    est["gates"] = gates
    est["cell_ids"] = [c["id"] for c in selected]
    for g in gates:
        if g["kind"] == "matrix_signoff_required":
            raise HTTPException(status_code=409, detail="matrix_signoff_required")
        raise HTTPException(status_code=400, detail=g["kind"])
    if not selected:
        return {"job_ids": [], "cell_ids": [], "estimate": est}

    job_ids = enqueue_cells(matrix, selected, cells, user_id, force_refresh=force_refresh)
    return {"job_ids": job_ids, "cell_ids": [c["id"] for c in selected], "estimate": est}


def enqueue_cells(
    matrix: dict, selected: list[dict], all_cells: list[dict], user_id: str, *,
    publish_after: bool = False, force_refresh: bool = False,
) -> list[str]:
    """Enqueue one `local_seo_generate` job per cell in `selected` (staggered like
    every bulk flow) and flip the cells to `queued`. Shared by the immediate run
    and the drip release; `publish_after` makes the job publish the page to the
    matrix's destination once generated (plan §5.2). Returns the job ids."""
    matrix_id, client_id = matrix["id"], matrix["client_id"]
    rows = []
    base_url = matrix.get("base_url") or ""
    for i, cell in enumerate(selected):
        location, code = _location_for_cell(matrix, cell)
        # Sibling links are planned against the WHOLE grid (plan §4.1), so a cell
        # generated before its siblings still links to their planned URLs.
        links = core.sibling_links(
            cell, all_cells, base_url,
            location_cap=settings.local_seo_matrix_sibling_location_cap,
            max_links=settings.local_seo_matrix_max_links,
        )
        payload = {
            "client_id": client_id,
            "keyword": cell["keyword"],
            "location": location,
            "location_code": code,
            "user_id": user_id,
            "page_template_url": matrix.get("page_template_url") or None,
            "force_refresh": bool(force_refresh),
            "entity_provider": matrix.get("entity_provider") or None,
            "matrix_id": matrix_id,
            "matrix_cell_id": cell["id"],
            "internal_links": links,
        }
        if publish_after:
            payload["publish_after"] = True
            payload["publish_destination"] = matrix.get("publish_destination") or "google_docs"
            payload["publish_status"] = matrix.get("publish_status") or "draft"
        rows.append(
            {
                "job_type": "local_seo_generate",
                "entity_id": client_id,
                "scheduled_at": _bulk_scheduled_at(i),
                "payload": payload,
            }
        )
    inserted = get_supabase().table("async_jobs").insert(rows).execute().data or []
    job_ids: list[str] = []
    for cell, job in zip(selected, inserted):
        _apply_patches([(cell["id"], {"status": "queued", "job_id": job["id"], "error": None})])
        job_ids.append(job["id"])
    logger.info(
        "local_seo_matrix.generate_enqueued",
        extra={"matrix_id": matrix_id, "client_id": client_id, "cells": len(job_ids), "publish_after": publish_after},
    )
    return job_ids


PUBLISH_JOB_TYPE = "local_seo_matrix_publish"


def _publish_scheduled_at(index: int) -> str:
    from datetime import datetime, timedelta, timezone

    spacing = settings.local_seo_matrix_publish_spacing_seconds
    return (datetime.now(timezone.utc) + timedelta(seconds=index * spacing)).isoformat()


def start_publish(
    matrix_id: str, client_id: str, user_id: str, *,
    destination: Optional[str] = None, status: Optional[str] = None,
    force_voice: bool = False, cell_ids: Optional[list[str]] = None,
) -> dict:
    """"Publish all done cells" (plan §5.3): one `local_seo_matrix_publish` job
    per selected cell, staggered a few seconds apart (publishing is seconds, not
    minutes), each publishing the cell's page to `destination` (default: the
    matrix's) and recording the outcome on the cell. `force_voice` is the same
    explicit brand-guide override the per-page Publish button offers — meant for
    a single `publish_blocked` cell the user has seen the words for, so it is
    only honoured together with explicit `cell_ids`."""
    matrix = _matrix_row(matrix_id, client_id)
    reconcile(matrix_id)
    cells = _cells(matrix_id)
    selected = core.select_publishable(cells, cell_ids)
    if not selected:
        return {"job_ids": [], "cell_ids": []}
    dest = destination or matrix.get("publish_destination") or "google_docs"
    pub_status = status or matrix.get("publish_status") or "draft"
    force = bool(force_voice and cell_ids)
    rows = [
        {
            "job_type": PUBLISH_JOB_TYPE,
            "entity_id": client_id,
            "scheduled_at": _publish_scheduled_at(i),
            "payload": {
                "client_id": client_id,
                "matrix_id": matrix_id,
                "matrix_cell_id": cell["id"],
                "page_id": cell["page_id"],
                "user_id": user_id,
                "destination": dest,
                "status": pub_status,
                "force_voice": force,
            },
        }
        for i, cell in enumerate(selected)
    ]
    inserted = get_supabase().table("async_jobs").insert(rows).execute().data or []
    job_ids: list[str] = []
    for cell, job in zip(selected, inserted):
        _apply_patches([(cell["id"], {"status": "publishing", "job_id": job["id"], "error": None})])
        job_ids.append(job["id"])
    logger.info(
        "local_seo_matrix.publish_enqueued",
        extra={"matrix_id": matrix_id, "client_id": client_id, "cells": len(job_ids), "destination": dest},
    )
    return {"job_ids": job_ids, "cell_ids": [c["id"] for c in selected]}


async def run_publish_job(job: dict) -> None:
    """async_jobs handler for job_type='local_seo_matrix_publish': publish one
    cell's page and record the outcome on the cell AND in the job result (so the
    read-side reconcile can re-apply it if the cell write was lost). The job
    itself completes whatever the publish outcome — a blocked / failed publish is
    a recorded outcome, not a job failure."""
    from services import local_seo_service

    payload = job.get("payload") or {}
    job_id = job["id"]
    sb = get_supabase()
    cell_id = payload.get("matrix_cell_id")
    page_id = payload.get("page_id")
    try:
        result = await local_seo_service.publish_page(
            page_id, payload.get("user_id") or "",
            destination=payload.get("destination") or "google_docs",
            status=payload.get("status") or "draft",
            force_voice=bool(payload.get("force_voice")),
        )
        outcome = core.publish_outcome_from_result(result or {})
    except HTTPException as exc:
        outcome = core.publish_outcome_from_error(str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        outcome = core.publish_outcome_from_error(str(exc))
    status, url, error = outcome
    try:
        if cell_id:
            record_publish_outcome(cell_id, page_id, status, url, error)
    except Exception as exc:  # noqa: BLE001 — the job result still carries it
        logger.warning("local_seo_matrix.publish_record_failed", extra={"job_id": job_id, "error": str(exc)})
    sb.table("async_jobs").update(
        {
            "status": "complete",
            "result": {"status": status, "url": url, "error": error, "page_id": page_id},
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()
    logger.info(
        "local_seo_matrix.publish_job_complete",
        extra={"job_id": job_id, "cell_id": cell_id, "outcome": status},
    )


def record_publish_outcome(cell_id: str, page_id: Optional[str], status: str, url: Optional[str], error: Optional[str]) -> None:
    """Record the drip's auto-publish result on the cell: `published` (+url) /
    `publish_failed` / `publish_blocked`. Carries the page id too, so the write
    is complete whether or not the read-side reconcile has run yet."""
    patch: dict = {"status": status, "url": url, "error": error, "updated_at": "now()"}
    if page_id:
        patch["page_id"] = page_id
    get_supabase().table("local_seo_matrix_cells").update(patch).eq("id", cell_id).execute()


def record_link_coverage(cell_id: str, coverage: dict) -> None:
    """Store a cell page's sibling-link coverage (`{expected, present, missing,
    appended}`) — written by the generate job after the link guarantee ran."""
    get_supabase().table("local_seo_matrix_cells").update(
        {"link_coverage": coverage, "updated_at": "now()"}
    ).eq("id", cell_id).execute()


# ── suggestions (async job) ───────────────────────────────────────────────────


def start_suggest(matrix_id: str, client_id: str, axis: str, user_id: str, seed_service: Optional[str] = None) -> str:
    """Enqueue a `local_seo_matrix_suggest` job for one axis; an in-flight job for
    the same matrix + axis is reused. Returns the job id."""
    _matrix_row(matrix_id, client_id)
    sb = get_supabase()
    existing = (
        sb.table("async_jobs")
        .select("id, payload")
        .eq("job_type", SUGGEST_JOB_TYPE)
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .execute()
        .data
        or []
    )
    for row in existing:
        p = row.get("payload") or {}
        if p.get("matrix_id") == matrix_id and p.get("axis") == axis:
            return row["id"]
    res = (
        sb.table("async_jobs")
        .insert(
            {
                "job_type": SUGGEST_JOB_TYPE,
                "entity_id": client_id,
                "payload": {
                    "client_id": client_id,
                    "matrix_id": matrix_id,
                    "axis": axis,
                    "seed_service": (seed_service or "").strip() or None,
                    "user_id": user_id,
                },
            }
        )
        .execute()
    )
    return res.data[0]["id"]


def get_suggest(job_id: str, client_id: str) -> dict:
    res = (
        get_supabase()
        .table("async_jobs")
        .select("status, result, error, entity_id")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    if not res.data or res.data[0].get("entity_id") != client_id:
        raise HTTPException(status_code=404, detail="suggest_job_not_found")
    row = res.data[0]
    result = row.get("result") or {}
    return {
        "status": row["status"],
        "axis": result.get("axis"),
        "suggestions": result.get("suggestions", []),
        "degraded_notes": result.get("degraded_notes", []),
        "error": row.get("error"),
    }


async def _suggest_services(matrix: dict, client: dict, seed_service: Optional[str]) -> tuple[list[dict], list[str]]:
    seed = (seed_service or "").strip() or ((matrix.get("services") or [{}])[0].get("label") or "")
    if not seed:
        return [], ["No seed service — add one service to the axis first."]
    city = _seed_city(matrix["location"])
    llm = local_seo_silo._service_llm()
    if not llm:
        return [], ["Service suggestions skipped — content model not configured."]
    icp_block = ""
    try:
        from services import icp_service

        icp_block = icp_service.resolve_icp_text(client)
    except Exception as exc:  # noqa: BLE001 — ICP grounding is non-critical
        logger.warning("local_seo_matrix.icp_fetch_failed", extra={"error": str(exc)})
    per_silo = await asyncio.to_thread(local_seo_silo._generate_service_pages, seed, city, llm, icp_block)
    have = {s.get("slug") for s in matrix.get("services") or []}
    labels = [s for s in core.service_labels_from_pages(per_silo, city) if core.slugify(s["label"]) not in have]
    return [{"label": s["label"], "group": s["group"], "source": "silo_planner"} for s in labels], []


async def _suggest_locations(matrix: dict, client: dict, supabase) -> tuple[list[dict], list[str]]:
    location, code = matrix["location"], matrix.get("location_code")
    city, state, country = local_seo_silo._parse_area(location)
    have = {l.get("slug") for l in matrix.get("locations") or []}
    out: list[dict] = []
    notes: list[str] = []
    seen: set[str] = set(have)

    def _add(name: str, source: str, geo: Optional[dict] = None) -> None:
        slug = core.slugify(name)
        if not slug or slug in seen:
            return
        seen.add(slug)
        out.append(
            {
                "label": name,
                "group": source,
                "source": source,
                "lat": (geo or {}).get("lat"),
                "lng": (geo or {}).get("lng"),
            }
        )

    # 1. Target cities — GBP service area, manual list, site place-names, nearby.
    try:
        cities, city_notes = await target_cities.resolve_target_cities(client, location, code, supabase)
        notes.extend(city_notes)
        for c in cities:
            _add(c["name"], f"target_city:{c.get('source') or 'discovered'}", c)
    except Exception as exc:  # noqa: BLE001 — best-effort source
        logger.warning("local_seo_matrix.target_cities_failed", extra={"error": str(exc)})
        notes.append("Target cities skipped — discovery error.")

    # 2. Suburbs of the metro — the common AU/UK matrix (Melbourne → Hawthorn…).
    if city and settings.anthropic_api_key and settings.google_maps_api_key:
        try:
            from services import maps_geocode

            city_query = local_seo_silo._query_area(city, state, country)
            geo = await maps_geocode.forward_geocode_places([city_query], supabase=supabase)
            city_geo = geo.get(city_query) or {}
            if city_geo.get("matched") and (city_geo.get("bounds") or city_geo.get("lat") is not None):
                seed = ((matrix.get("services") or [{}])[0].get("label") or "").strip() or "service"
                pages, sub_notes = await local_seo_silo._neighborhoods_for_city(
                    seed, city, state, country, city_geo, set(), supabase
                )
                notes.extend(sub_notes)
                for p in pages:
                    if p.get("location_name"):
                        _add(p["location_name"], "suburb", p.get("geo"))
            else:
                notes.append("Suburbs skipped — couldn't resolve the metro to verify sub-areas.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("local_seo_matrix.suburbs_failed", extra={"error": str(exc)})
            notes.append("Suburbs skipped — discovery error.")
    elif city:
        notes.append("Suburbs skipped — content model or geocoding not configured.")
    return out, notes


async def run_suggest_job(job: dict) -> None:
    """async_jobs handler for job_type='local_seo_matrix_suggest'."""
    payload = job.get("payload") or {}
    job_id = job["id"]
    client_id = payload.get("client_id")
    matrix_id = payload.get("matrix_id")
    axis = payload.get("axis")
    sb = get_supabase()
    try:
        matrix = _matrix_row(matrix_id, client_id)
        client = local_seo_silo._get_client(client_id)
        if axis == "services":
            suggestions, notes = await _suggest_services(matrix, client, payload.get("seed_service"))
        elif axis == "locations":
            suggestions, notes = await _suggest_locations(matrix, client, sb)
        else:
            raise ValueError("axis_invalid")
        sb.table("async_jobs").update(
            {
                "status": "complete",
                "result": {"axis": axis, "suggestions": suggestions, "degraded_notes": notes},
                "completed_at": "now()",
            }
        ).eq("id", job_id).execute()
        logger.info(
            "local_seo_matrix.suggest_complete",
            extra={"job_id": job_id, "matrix_id": matrix_id, "axis": axis, "count": len(suggestions)},
        )
    except Exception as exc:  # noqa: BLE001 — record the failure for the poller
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("local_seo_matrix.suggest_failed", extra={"job_id": job_id, "error": str(detail)})
        sb.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
