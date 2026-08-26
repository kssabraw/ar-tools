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

    Returns `{engine, keyword, location, content_type, notes}`; `engine` of None
    means no writer in the suite covers this page type. `content_type`/`notes`
    are carried only by the `run` engine (blog posts and pillar pages) and ignored
    otherwise.
    """
    plan = page.get("plan") or {}
    return {
        "engine": plan.get("engine"),
        "keyword": plan.get("keyword"),
        "location": plan.get("location"),
        "content_type": plan.get("content_type"),
        "notes": plan.get("notes"),
    }


def _spaced_at(index: int) -> str:
    spacing = max(0, int(settings.website_publish_job_spacing_seconds))
    return (datetime.now(timezone.utc) + timedelta(seconds=index * spacing)).isoformat()


def enqueue_generation(
    *, website_id: str, client_id: str, page_ids: list[str], user_id: str,
    publish_after: bool = False,
) -> list[str]:
    """One `website_page_generate` job per page, staggered.

    Per-item rather than one batch job for the reasons the Local SEO bulk path
    documents: each unit stays under the stale-job reaper's timeout (a batch job
    would be reaped mid-run and regenerate what it had already paid for), and
    the staggered `scheduled_at` lets interactive work overtake the batch.

    `publish_after` is set by the release (drip) schedule: on a successful
    generation the job auto-enqueues the page's publish, so a scheduled release
    generates then publishes in one flow without a second job type.
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
                    "publish_after": bool(publish_after),
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
        # Whole row, not a column list: the writers downstream read `config`
        # (the human-entered business facts that outrank GBP) and `site_type`.
        # A narrowed select silently handed them an empty config, so a fact a
        # person set in the Settings tab was ignored in favour of GBP — the one
        # thing that editor exists to prevent.
        .select("*")
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

    if engine == "core_pages":
        return await _generate_core_page(page=page, website=website, supabase=supabase)

    if engine == "run":
        return await _generate_run_page(
            page=page, website=website, supabase=supabase, inputs=inputs, user_id=user_id
        )

    if engine != "nlp":
        # A page type whose engine name we recognise but haven't built. None is
        # left today, but saying so is the point: a page sitting at draft forever
        # with nobody able to tell why is the failure this guards against.
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

    update = {
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
    # A hero image rides in the page's own frontmatter (build_files merges it), so
    # a local_seo_page's image lives here rather than on its local_seo_pages row.
    hero = await _hero_for(page, client[0], website)
    if hero:
        update["content"] = {**(page.get("content") or {}),
                             "frontmatter": {**((page.get("content") or {}).get("frontmatter") or {}), **hero}}

    supabase.table("website_pages").update(update).eq("id", page_id).execute()

    logger.info(
        "website_generate.page_written",
        extra={"page_id": page_id, "source_id": generated["id"], "keyword": keyword},
    )
    return {"page_id": page_id, "generated": True, "source_id": generated["id"]}


def _hero_business_city(client: dict, website: dict) -> tuple[str, str]:
    config = website.get("config") or {}
    business_cfg = config.get("business") or {}
    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else {}
    business = (
        business_cfg.get("name") or website.get("name")
        or gbp.get("business_name") or client.get("name") or ""
    )
    city = business_cfg.get("city") or gbp.get("city") or client.get("business_location") or ""
    return business.strip(), city.strip()


async def _hero_for(page: dict, client: dict, website: dict) -> Optional[dict]:
    """A hero image's frontmatter for this page, or None. Never raises.

    Best-effort by construction — imagery being off, unsupported for the page
    type, or a render failure all return None, and the page ships without a hero
    (a state the template renders cleanly).
    """
    from services import website_images

    business, city = _hero_business_city(client, website)
    return await website_images.generate_hero(
        page=page, client=client, website=website, business=business, city=city
    )


async def _generate_core_page(*, page: dict, website: dict, supabase) -> dict:
    """Home / about / contact via the light core-pages writer; privacy is deterministic.

    Privacy is planned with the `core_pages` engine but the template renders it
    from a legal template merged with business facts — there is nothing for an
    LLM to write, so it is recorded as template-rendered (published straight from
    the template) rather than sent to a writer that would only invent a policy.
    """
    from services import website_core_pages

    page_type = page.get("page_type") or ""
    page_id = page["id"]

    if page_type not in website_core_pages.GENERATED_KINDS:
        # privacy (or any future deterministic core page): the template owns it.
        supabase.table("website_pages").update(
            {"error": "template_rendered", "updated_at": "now()"}
        ).eq("id", page_id).execute()
        return {"page_id": page_id, "generated": False, "reason": "template_rendered"}

    client = (
        supabase.table("clients").select("*").eq("id", website["client_id"]).limit(1).execute()
    ).data
    if not client:
        raise GenerateError("client_not_found")
    # The same bar the service writer holds: the suite has shipped one article
    # with zero brand context, and a home page written that way is every visitor's
    # first impression of the client in a generic voice.
    if not has_brand_context(client[0]):
        raise GenerateError("content_no_brand_context")

    # The site's own planned pages seed the copy with the real services and cities
    # — a home page must not list services the site does not have.
    site_pages = (
        supabase.table("website_pages")
        .select("page_type, title")
        .eq("website_id", website["id"])
        .execute()
    ).data or []

    content = await website_core_pages.generate_core_page(
        page_kind=page_type,
        client=client[0],
        website=website,
        pages=site_pages,
    )

    # Home is hero-eligible; about/contact are not, so this is None for them.
    hero = await _hero_for(page, client[0], website)
    if hero:
        content["frontmatter"] = {**(content.get("frontmatter") or {}), **hero}

    supabase.table("website_pages").update(
        {
            # Stored on the row (not a separate record): a core page has no
            # keyword and no upstream local_seo_pages row, so the page IS its
            # own source. `source_from_content` reads exactly this shape.
            "content_source": "composed",
            "source_id": None,
            "content": content,
            "title": content.get("title") or page.get("title") or "",
            "status": "draft",
            "error": None,
            # A fresh body invalidates any prior commit, so the next publish must
            # not short-circuit on an unchanged hash.
            "content_hash": None,
            "updated_at": "now()",
        }
    ).eq("id", page_id).execute()

    logger.info(
        "website_generate.core_page_written",
        extra={"page_id": page_id, "page_kind": page_type},
    )
    return {"page_id": page_id, "generated": True, "page_kind": page_type}


def _blog_run_title(supabase, run_id: str) -> str:
    """The SEO title the Brief Generator produced for a run, if any."""
    rows = (
        supabase.table("module_outputs")
        .select("output_payload, attempt_number")
        .eq("run_id", run_id)
        .eq("module", "brief")
        .eq("status", "complete")
        .order("attempt_number", desc=True)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        return ""
    return ((rows[0].get("output_payload") or {}).get("title") or "").strip()


async def _generate_run_page(
    *, page: dict, website: dict, supabase, inputs: dict, user_id: str
) -> dict:
    """A blog post or pillar page: a suite blog Writer run, linked back.

    Reuses the whole suite blog pipeline (brief -> sie -> research -> writer ->
    sources_cited) rather than a new writer — the publish side already assembles
    the body from the run's `module_outputs` markdown (`content_source="run"`).
    The post's editorial angle rides on the run's `writer_notes`, since the blog
    brief is keyword-driven and globally cached and cannot carry it.
    """
    page_id = page["id"]
    keyword = (inputs.get("keyword") or "").strip()
    if not keyword:
        raise GenerateError("plan_row_has_no_keyword")

    client = (
        supabase.table("clients").select("*").eq("id", website["client_id"]).limit(1).execute()
    ).data
    if not client:
        raise GenerateError("client_not_found")
    # The same bar every generator holds: the suite has shipped one article with
    # zero brand context, and an auto-published post written that way is public
    # before anyone reads it.
    if not has_brand_context(client[0]):
        raise GenerateError("content_no_brand_context")

    from services.orchestrator import orchestrate_run
    from services.run_dispatch import create_run_and_snapshot

    # Idempotent per page: a reaper requeue adopts the in-flight/complete run
    # (create_run_and_snapshot's source_ref) instead of paying for a second one,
    # and orchestrate_run resumes from completed stages.
    run_id = create_run_and_snapshot(
        client=client[0],
        keyword=keyword,
        content_type=(inputs.get("content_type") or "blog_post"),
        writer_notes=(inputs.get("notes") or None),
        created_by=user_id or None,
        source_ref=f"website_page:{page_id}",
    )
    await orchestrate_run(run_id)

    update = {
        "content_source": "run",
        "source_id": run_id,
        "title": _blog_run_title(supabase, run_id) or page.get("title") or keyword,
        "status": "draft",
        "error": None,
        # A fresh run invalidates any prior commit, so the next publish must not
        # short-circuit on an unchanged hash.
        "content_hash": None,
        "updated_at": "now()",
    }
    # Posts and pillars are hero-eligible; the image rides in the page's own
    # frontmatter (build_files merges it). generate_hero returns None for a page
    # type it does not support, so this is safe for both.
    hero = await _hero_for(page, client[0], website)
    if hero:
        update["content"] = {
            **(page.get("content") or {}),
            "frontmatter": {**((page.get("content") or {}).get("frontmatter") or {}), **hero},
        }

    supabase.table("website_pages").update(update).eq("id", page_id).execute()

    logger.info(
        "website_generate.run_page_written",
        extra={"page_id": page_id, "run_id": run_id, "page_type": page.get("page_type")},
    )
    return {"page_id": page_id, "generated": True, "run_id": run_id}


async def run_generate_job(job: dict) -> None:
    """async_jobs handler for `website_page_generate`."""
    payload = job.get("payload") or {}
    supabase = get_supabase()
    try:
        result = await generate_page(
            page_id=payload["page_id"], user_id=payload.get("user_id") or ""
        )
        # Drip-release flow: a successful generation hands straight to publish, so
        # a scheduled release generates then publishes without a second job type.
        # Only on real output — a template/engine-unavailable page has nothing to
        # commit, and a held/failed generation must not auto-ship.
        if payload.get("publish_after") and result.get("generated"):
            from services import website_publish

            website_publish.enqueue_publish(
                website_id=payload["website_id"],
                client_id=payload.get("client_id") or "",
                page_ids=[payload["page_id"]],
                user_id=payload.get("user_id") or "",
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
