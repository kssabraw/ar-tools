"""Website Builder — writing the body copy for a planned page.

This module does not write anything itself. It maps a planned page onto the
engine that already writes that page type and calls it unchanged: local service,
location and matrix pages go to the nlp-api local generator through
`local_seo_service.generate_page`, exactly as the Local SEO tool does. The
module is assembly and delivery, not a new writer.

Two consequences follow from that, and both are deliberate:

* **The generated page also persists where it already does.** A `local_seo_pages`
  row is the source of truth for the text; the `website_pages` row points at it.
  So scoring and reoptimization keep working, and republishing a reoptimized page
  is one action rather than a second copy that drifts from the first.
* **A page type with no engine is recorded as such, not silently skipped.** The
  catalog has ~25 page types and the suite writes a subset (PRD §4.7); a plan
  that promises pages nothing can produce is worse than one that says so.

This is where the module starts spending money — one nlp-api call plus its SERP
analysis per page — so the route takes an explicit list of page ids rather than
generating a whole plan on one click.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


class GenerateError(Exception):
    """Stable error code, not prose."""


def has_brand_context(client: dict) -> bool:
    """Whether this client has a brand voice on file.

    Generation is gated on it; site creation, theming and provisioning are not —
    none of those write copy (PRD §4.11). This is a stronger stance than the
    suite takes for a single article and deliberately so: the suite has already
    shipped one article written with zero brand context, and the same failure on
    a website writes *every page* that way.
    """
    from services.voice_card_service import source_texts

    brand_text, _ = source_texts(client or {})
    return bool((brand_text or "").strip())


def generation_plan(page: dict) -> dict:
    """What this page needs to be generated, or why it cannot be.

    Returns `{engine, keyword, location}`; `engine` of None means no writer in
    the suite covers this page type.
    """
    plan = page.get("plan") or {}
    return {
        "engine": plan.get("engine"),
        "keyword": plan.get("keyword"),
        "location": plan.get("location"),
    }


def _spaced_at(index: int) -> str:
    spacing = max(0, int(settings.website_publish_job_spacing_seconds))
    return (datetime.now(timezone.utc) + timedelta(seconds=index * spacing)).isoformat()


def enqueue_generation(
    *, website_id: str, client_id: str, page_ids: list[str], user_id: str
) -> list[str]:
    """One `website_page_generate` job per page, staggered.

    Per-item rather than one batch job for the reasons the Local SEO bulk path
    documents: each unit stays under the stale-job reaper's timeout (a batch job
    would be reaped mid-run and regenerate what it had already paid for), and
    the staggered `scheduled_at` lets interactive work overtake the batch.
    """
    rows = []
    for page_id in page_ids:
        rows.append(
            {
                "job_type": "website_page_generate",
                "entity_id": website_id,
                "scheduled_at": _spaced_at(len(rows)),
                "payload": {
                    "website_id": website_id,
                    "client_id": client_id,
                    "page_id": page_id,
                    "user_id": user_id,
                },
            }
        )
    if not rows:
        return []
    res = get_supabase().table("async_jobs").insert(rows).execute()
    return [r["id"] for r in (res.data or [])]


async def generate_page(*, page_id: str, user_id: str) -> dict:
    """Write one planned page's body with the engine that owns its type."""
    supabase = get_supabase()
    pages = (
        supabase.table("website_pages").select("*").eq("id", page_id).limit(1).execute()
    ).data
    if not pages:
        raise GenerateError("website_page_not_found")
    page = pages[0]

    sites = (
        supabase.table("websites")
        .select("id, client_id, name")
        .eq("id", page["website_id"])
        .limit(1)
        .execute()
    ).data
    if not sites:
        raise GenerateError("website_not_found")
    website = sites[0]

    inputs = generation_plan(page)
    engine = inputs.get("engine")

    if engine in ("template", None):
        reason = (
            "template_rendered"
            if engine == "template"
            else f"engine_unavailable:{page.get('page_type')}"
        )
        supabase.table("website_pages").update(
            {"error": reason, "updated_at": "now()"}
        ).eq("id", page_id).execute()
        return {"page_id": page_id, "generated": False, "reason": reason}

    if engine != "nlp":
        # core_pages is specified but unbuilt (plan §4.6, Phase 3). Saying so is
        # the point: the alternative is a page that sits at draft forever with
        # nobody able to tell why.
        reason = f"engine_not_built:{engine}"
        supabase.table("website_pages").update(
            {"error": reason, "updated_at": "now()"}
        ).eq("id", page_id).execute()
        return {"page_id": page_id, "generated": False, "reason": reason}

    keyword = (inputs.get("keyword") or "").strip()
    if not keyword:
        raise GenerateError("plan_row_has_no_keyword")

    from services import local_seo_service

    client = (
        supabase.table("clients").select("*").eq("id", website["client_id"]).limit(1).execute()
    ).data
    if not client:
        raise GenerateError("client_not_found")
    if not has_brand_context(client[0]):
        raise GenerateError("content_no_brand_context")

    generated = await local_seo_service.generate_page(
        client_id=website["client_id"],
        keyword=keyword,
        location=inputs.get("location") or "",
        location_code=None,
        user_id=user_id,
    )

    supabase.table("website_pages").update(
        {
            "content_source": "local_seo_page",
            "source_id": generated["id"],
            "title": generated.get("page_title") or page.get("title") or "",
            "status": "draft",
            "error": None,
            # A new body invalidates whatever was last committed, so the next
            # publish must not short-circuit on an unchanged hash.
            "content_hash": None,
            "updated_at": "now()",
        }
    ).eq("id", page_id).execute()

    logger.info(
        "website_generate.page_written",
        extra={"page_id": page_id, "source_id": generated["id"], "keyword": keyword},
    )
    return {"page_id": page_id, "generated": True, "source_id": generated["id"]}


async def run_generate_job(job: dict) -> None:
    """async_jobs handler for `website_page_generate`."""
    payload = job.get("payload") or {}
    supabase = get_supabase()
    try:
        result = await generate_page(
            page_id=payload["page_id"], user_id=payload.get("user_id") or ""
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:  # noqa: BLE001 — record it for the poller
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning(
            "website_generate.job_failed",
            extra={"job_id": job["id"], "error": str(detail)},
        )
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
        page_id = payload.get("page_id")
        if page_id:
            supabase.table("website_pages").update(
                {"error": str(detail)[:500], "updated_at": "now()"}
            ).eq("id", page_id).execute()
