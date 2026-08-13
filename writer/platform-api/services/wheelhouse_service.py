"""WheelHouse IT location/service page poster — orchestration + persistence.

Ties together the generator (`wheelhouse_generate`), the WordPress Pages
hierarchy engine (`wheelhouse_pages`), and the `wheelhouse_pages` table (in-tool
draft/upsert store). Owns: the Wheelhouse-only gate, mass (city×service) job
fan-out, the `wheelhouse_generate` background job, single/one-off generation,
publish (ensure chain + upsert leaf), dry-run, and list/report reads.

Client-scoped and gated on ``clients.wheelhouse_cpt_enabled`` — every write path
asserts it, so the module is inert for every other client even if a route is hit.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import wheelhouse_generate
from services.wheelhouse_fields import FIELD_NAMES, validate_fields
from services.wheelhouse_pages import (
    build_slug_path,
    dry_run_leaf,
    publish_leaf,
    slugify,
)

logger = logging.getLogger(__name__)


# ── client + gate ────────────────────────────────────────────────────────────

def _get_client(client_id: str) -> dict:
    res = get_supabase().table("clients").select("*").eq("id", client_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    return res.data


def assert_enabled(client: dict) -> None:
    """Guard: the module is available only for a Wheelhouse-flagged client. A
    disabled client 404s (not 403) so the feature is invisible, not merely denied."""
    if not client.get("wheelhouse_cpt_enabled"):
        raise HTTPException(status_code=404, detail="wheelhouse_not_enabled")


def get_enabled_client(client_id: str) -> dict:
    client = _get_client(client_id)
    assert_enabled(client)
    return client


# ── persistence ──────────────────────────────────────────────────────────────

def _row_to_page(row: dict) -> dict:
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "state": row["state"],
        "city": row["city"],
        "service": row["service"],
        "slug_path": row.get("slug_path"),
        "title": row.get("title"),
        "acf": row.get("acf") or {},
        "field_sources": row.get("field_sources") or {},
        "validation_warnings": row.get("validation_warnings") or [],
        "status": row.get("status") or "draft",
        "wp_status": row.get("wp_status"),
        "wp_page_id": row.get("wp_page_id"),
        "wp_state_id": row.get("wp_state_id"),
        "wp_city_id": row.get("wp_city_id"),
        "published_url": row.get("published_url"),
        "edit_link": row.get("edit_link"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _find_live_row_id(supabase, client_id: str, state_slug: str, city_slug: str, service_slug: str):
    res = (
        supabase.table("wheelhouse_pages").select("id")
        .eq("client_id", client_id).eq("state_slug", state_slug)
        .eq("city_slug", city_slug).eq("service_slug", service_slug)
        .is_("deleted_at", "null").limit(1).execute()
    )
    return res.data[0]["id"] if res.data else None


def _upsert_draft(
    client_id: str, state: str, city: str, service: str, *,
    acf: dict, field_sources: dict, warnings: list, title: str,
) -> dict:
    """Insert or update (by client+slug combo) the in-tool draft row.

    Regenerating/editing an existing row **resets status to 'draft'** — the stored
    content no longer matches what's live on WP — while PRESERVING the recorded WP
    ids (wp_page_id/published_url) so the UI can flag it as "modified, needs
    republish" rather than pretending it's still published. On insert the DB
    default (draft) applies. The check-then-insert is race-guarded: a concurrent
    insert of the same combo (blocked by the partial unique index) falls back to an
    update instead of surfacing a 500."""
    supabase = get_supabase()
    state_slug, city_slug, service_slug = slugify(state), slugify(city), slugify(service)
    payload = {
        "client_id": client_id,
        "state": state.strip(), "city": city.strip(), "service": service.strip(),
        "state_slug": state_slug, "city_slug": city_slug, "service_slug": service_slug,
        "slug_path": build_slug_path(state_slug, city_slug, service_slug),
        "acf": acf, "field_sources": field_sources, "validation_warnings": warnings,
        "title": title, "updated_at": "now()",
    }
    row_id = _find_live_row_id(supabase, client_id, state_slug, city_slug, service_slug)
    if row_id:
        res = supabase.table("wheelhouse_pages").update(
            {**payload, "status": "draft"}
        ).eq("id", row_id).execute()
        return _row_to_page(res.data[0])
    try:
        res = supabase.table("wheelhouse_pages").insert(payload).execute()
        return _row_to_page(res.data[0])
    except Exception:  # noqa: BLE001 — likely a concurrent insert hit the unique index
        row_id = _find_live_row_id(supabase, client_id, state_slug, city_slug, service_slug)
        if not row_id:
            raise
        res = supabase.table("wheelhouse_pages").update(
            {**payload, "status": "draft"}
        ).eq("id", row_id).execute()
        return _row_to_page(res.data[0])


def get_page(client_id: str, page_id: str) -> dict:
    res = (
        get_supabase().table("wheelhouse_pages").select("*")
        .eq("id", page_id).eq("client_id", client_id).limit(1).execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="wheelhouse_page_not_found")
    return _row_to_page(res.data[0])


def list_pages(client_id: str, *, deleted: bool = False) -> list[dict]:
    q = (
        get_supabase().table("wheelhouse_pages").select("*")
        .eq("client_id", client_id).order("updated_at", desc=True)
    )
    q = q.not_.is_("deleted_at", "null") if deleted else q.is_("deleted_at", "null")
    return [_row_to_page(r) for r in (q.execute().data or [])]


def soft_delete(client_id: str, page_id: str) -> None:
    get_page(client_id, page_id)  # 404 if not this client's
    get_supabase().table("wheelhouse_pages").update(
        {"deleted_at": "now()"}
    ).eq("id", page_id).eq("client_id", client_id).execute()


def restore(client_id: str, page_id: str) -> dict:
    get_supabase().table("wheelhouse_pages").update(
        {"deleted_at": None, "updated_at": "now()"}
    ).eq("id", page_id).eq("client_id", client_id).execute()
    return get_page(client_id, page_id)


def purge(client_id: str, page_id: str) -> None:
    get_supabase().table("wheelhouse_pages").delete().eq(
        "id", page_id
    ).eq("client_id", client_id).execute()


# ── generation ───────────────────────────────────────────────────────────────

async def generate_one(
    client_id: str, state: str, city: str, service: str,
    supplied: Optional[dict] = None,
) -> dict:
    """Generate (or, for a one-off, assemble from supplied+generated) the leaf's
    33 fields and persist as a draft. Returns the stored page."""
    get_enabled_client(client_id)
    result = await wheelhouse_generate.generate_fields(
        state=state, city=city, service=service, supplied=supplied,
    )
    page = _upsert_draft(
        client_id, state, city, service,
        acf=result["acf"], field_sources=result["field_sources"],
        warnings=result["warnings"], title=result["title"],
    )
    page["generation_failed"] = result.get("generation_failed", False)
    return page


async def preview_one(
    client_id: str, state: str, city: str, service: str,
    supplied: Optional[dict] = None,
) -> dict:
    """Generate the fields WITHOUT persisting a row (the one-off form's 'Draft all'
    preview). Returns ``{acf, field_sources, warnings, title, generation_failed}``
    so the form populates without creating a Saved page until the user saves."""
    get_enabled_client(client_id)
    result = await wheelhouse_generate.generate_fields(
        state=state, city=city, service=service, supplied=supplied,
    )
    return {
        "id": None,
        "acf": result["acf"],
        "field_sources": result["field_sources"],
        "validation_warnings": result["warnings"],
        "title": result["title"],
        "generation_failed": result.get("generation_failed", False),
    }


async def draft_single_field(
    client_id: str, state: str, city: str, service: str, field_name: str,
) -> str:
    """The one-off form's per-field 'Draft with AI'. Returns the field value only
    (no persistence — the form holds unsaved edits)."""
    get_enabled_client(client_id)
    if field_name not in FIELD_NAMES:
        raise HTTPException(status_code=422, detail="unknown_field")
    return await wheelhouse_generate.draft_field(
        state=state, city=city, service=service, field_name=field_name,
    )


def save_one_off(
    client_id: str, state: str, city: str, service: str, acf: dict,
) -> dict:
    """Persist a user-authored/edited ACF object as a draft (no generation).

    wysiwyg fields are coerced to HTML (matching the generate path), and a field's
    generated/supplied provenance is PRESERVED for values unchanged from the stored
    row — only a field the user actually changed becomes 'supplied' (so the report
    stays accurate across edits)."""
    get_enabled_client(client_id)
    from services.wheelhouse_fields import FIELD_BY_NAME, coerce_wysiwyg, merge_edit_sources
    from services.wheelhouse_generate import compose_title

    acf = acf or {}
    clean: dict = {}
    for name in FIELD_NAMES:
        raw = acf.get(name)
        val = raw.strip() if isinstance(raw, str) else ""
        if FIELD_BY_NAME[name]["type"] == "wysiwyg" and val:
            val = coerce_wysiwyg(val)
        clean[name] = val

    supabase = get_supabase()
    state_slug, city_slug, service_slug = slugify(state), slugify(city), slugify(service)
    existing = (
        supabase.table("wheelhouse_pages").select("acf, field_sources")
        .eq("client_id", client_id).eq("state_slug", state_slug)
        .eq("city_slug", city_slug).eq("service_slug", service_slug)
        .is_("deleted_at", "null").limit(1).execute()
    )
    prev = existing.data[0] if existing.data else {}
    field_sources = merge_edit_sources(clean, prev.get("acf"), prev.get("field_sources"))
    return _upsert_draft(
        client_id, state, city, service,
        acf=clean, field_sources=field_sources, warnings=validate_fields(clean),
        title=compose_title(state, city, service),
    )


# ── mass (city × service) fan-out ────────────────────────────────────────────

def _bulk_scheduled_at(index: int) -> str:
    """Staggered `scheduled_at` so a mass run interleaves at background priority
    (see `wheelhouse_bulk_job_spacing_seconds` / the Local SEO rationale)."""
    spacing = settings.wheelhouse_bulk_job_spacing_seconds
    return (datetime.now(timezone.utc) + timedelta(seconds=index * spacing)).isoformat()


async def enqueue_mass(
    client_id: str, state: str, city: str, services: list[str], user_id: str,
) -> list[str]:
    """Enqueue one `wheelhouse_generate` job per city×service. Returns job ids."""
    get_enabled_client(client_id)
    if not (state or "").strip() or not (city or "").strip():
        raise HTTPException(status_code=422, detail="state_and_city_required")
    rows = []
    seen = set()
    for svc in services:
        svc = (svc or "").strip()
        key = svc.lower()
        if not svc or key in seen:
            continue
        seen.add(key)
        rows.append({
            "job_type": "wheelhouse_generate",
            "entity_id": client_id,
            "scheduled_at": _bulk_scheduled_at(len(rows)),
            "payload": {
                "client_id": client_id, "state": state.strip(), "city": city.strip(),
                "service": svc, "user_id": user_id,
            },
        })
    if not rows:
        raise HTTPException(status_code=422, detail="no_services")
    res = get_supabase().table("async_jobs").insert(rows).execute()
    return [r["id"] for r in (res.data or [])]


async def run_generate_job(job: dict) -> None:
    payload = job.get("payload") or {}
    job_id = job["id"]
    supabase = get_supabase()
    try:
        page = await generate_one(
            client_id=payload["client_id"], state=payload["state"],
            city=payload["city"], service=payload["service"],
            supplied=payload.get("supplied"),
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"page_id": page["id"]}, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("wheelhouse.generate_job_complete", extra={"job_id": job_id, "page_id": page["id"]})
    except Exception as exc:  # noqa: BLE001
        from services.job_worker import settle_job_failure

        settle_job_failure(job_id, exc, job)


def get_generate_job(job_id: str, client_id: str) -> dict:
    res = (
        get_supabase().table("async_jobs").select("status, result, error, entity_id")
        .eq("id", job_id).limit(1).execute()
    )
    if not res.data or res.data[0].get("entity_id") != client_id:
        raise HTTPException(status_code=404, detail="generate_job_not_found")
    row = res.data[0]
    result = row.get("result") or {}
    return {"status": row["status"], "page_id": result.get("page_id"), "error": row.get("error")}


def jobs_status(client_id: str, job_ids: list[str]) -> list[dict]:
    """Batch poll of mass-run jobs (only this client's rows are returned)."""
    if not job_ids:
        return []
    res = (
        get_supabase().table("async_jobs").select("id, status, result, error, entity_id")
        .in_("id", job_ids).execute()
    )
    out = []
    for row in res.data or []:
        if row.get("entity_id") != client_id:
            continue
        result = row.get("result") or {}
        out.append({"job_id": row["id"], "status": row["status"],
                    "page_id": result.get("page_id"), "error": row.get("error")})
    return out


# ── publish + dry-run ────────────────────────────────────────────────────────

async def publish(client_id: str, page_id: str, status: str = "draft") -> dict:
    """Ensure the State→City parent chain and upsert the leaf with its ACF fields.
    Persists the resolved WP ids + link back onto the row and returns the report."""
    client = get_enabled_client(client_id)
    page = get_page(client_id, page_id)
    result = await publish_leaf(
        client=client, state=page["state"], city=page["city"], service=page["service"],
        title=page["title"] or page["service"], acf=page["acf"], status=status,
    )
    get_supabase().table("wheelhouse_pages").update({
        "wp_state_id": result["wp_state_id"], "wp_city_id": result["wp_city_id"],
        "wp_page_id": result["wp_page_id"], "wp_status": result["status"],
        "published_url": result["link"], "edit_link": result["edit_link"],
        "slug_path": result["slug_path"], "status": "published", "updated_at": "now()",
    }).eq("id", page_id).execute()
    return {**result, "page_id": page_id}


async def dry_run(client_id: str, page_id: str, status: str = "draft") -> dict:
    """Assemble + resolve the parent chain for a stored draft and return the exact
    would-POST payloads. Zero writes."""
    client = get_enabled_client(client_id)
    page = get_page(client_id, page_id)
    return await dry_run_leaf(
        client=client, state=page["state"], city=page["city"], service=page["service"],
        title=page["title"] or page["service"], acf=page["acf"], status=status,
    )


def report_for(page: dict) -> dict:
    """The reporting view for a page: slug path, WP ids, edit link, and the
    generated-vs-supplied field breakdown."""
    sources = page.get("field_sources") or {}
    generated = [f for f, s in sources.items() if s == "generated"]
    supplied = [f for f, s in sources.items() if s in ("supplied", "default")]
    return {
        "page_id": page["id"],
        "slug_path": page.get("slug_path"),
        "status": page.get("status"),
        "wp_page_id": page.get("wp_page_id"),
        "published_url": page.get("published_url"),
        "edit_link": page.get("edit_link"),
        "generated_fields": generated,
        "supplied_fields": supplied,
        "validation_warnings": page.get("validation_warnings") or [],
    }
