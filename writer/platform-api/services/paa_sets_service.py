"""PAA → SEO Neo v1 — the impure service layer (I/O) for the content half.

Orchestrates the PAA content flow over reused suite seams (PRD §7 — nothing here
is a new pipeline or a new data source):

  * **pull** — one live Google SERP call for the service-in-geo (reuses
    ``serp_snapshot.fetch_serp`` + parsers, exactly like Keyword Research's SERP
    enrichment), yielding the People-Also-Ask questions, enriched with reused
    DataForSEO volume/CPC (``keyword_market.fetch_market``). One SERP + one market
    call per pull — no multiplication (PRD §8.5).
  * **save** — persist a ``paa_sets`` row + the chosen ``paa_items``, resolving the
    "link high" service-page URL explicit → ``site_page_index`` auto-match → prompt.
  * **preflight** — the cannibalization guard (reused ``site_page_index`` matching
    + ``local_seo_matrix`` scale gates), surfaced as acknowledgeable issues.
  * **create posts** — one Blog Writer ``run`` per chosen PAA (seeded from the
    exact PAA string, ``writer_notes`` carrying the three rules) + a best-effort
    GBP-post draft (seeded from the same string) + a best-effort syndication-queue
    refresh. All reused writers; no new job type.
  * **verify** — reconstruct each completed post's article and run the deterministic
    exact-match + service-page-link checks (``paa_seo.verify_item_checks``),
    persisting the result on the item.

The pure helpers live in ``services/paa_seo.py``; this module is the I/O around
them. Guardrail (PRD §9): nothing here touches the SEO Neo authority layer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import keyword_market, paa_seo, serp_snapshot, site_page_index
from services.run_dispatch import create_run_and_snapshot

logger = logging.getLogger(__name__)

# Columns the flow needs off the client row.
_CLIENT_COLS = (
    "id, name, website_url, business_location, gbp, rank_tracking_location_code"
)


def _sb():
    return get_supabase()


def _client(client_id: str) -> dict:
    rows = (
        _sb().table("clients").select(_CLIENT_COLS).eq("id", client_id).limit(1).execute()
    ).data or []
    if not rows:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="client_not_found")
    return rows[0]


def _location_label(client: dict, override: Optional[str]) -> str:
    """The geo label for the geo-modified PAA query + display. Explicit override
    wins, else the client's business_location city."""
    if (override or "").strip():
        return override.strip()
    return (client.get("business_location") or "").strip()


def _location_code(client: dict) -> int:
    return int(
        client.get("rank_tracking_location_code")
        or settings.dataforseo_default_location_code
    )


# ── free service-page auto-match (site_page_index, sitemap-only) ──────────────


async def _auto_match_service_page(client: dict, service_keyword: str) -> Optional[str]:
    """Best-effort: the client's live page that already targets this service, for
    the "link high" default. Sitemap-only (free — no paid ``site:`` fallback), so
    the pull stays a single billed call. Never raises."""
    website = client.get("website_url") or (client.get("gbp") or {}).get("website") or ""
    if not website:
        return None
    try:
        urls, _source = await site_page_index.discover_site_urls(
            website, _location_code(client), use_paid_fallback=False
        )
        if not urls:
            return None
        index = site_page_index.build_page_token_index(urls)
        # Exact content-word match first, then the national (city-less) service page.
        return site_page_index.match_site_page_for_keyword(
            service_keyword, index
        ) or site_page_index.match_site_service_page(
            service_keyword, _location_label(client, None), index
        )
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning(
            "paa.auto_match_failed",
            extra={"client_id": client.get("id"), "error": str(exc)},
        )
        return None


# ── pull ──────────────────────────────────────────────────────────────────────


async def pull_paa(
    client_id: str,
    service_keyword: str,
    geo_mode: str = "geo",
    location_override: Optional[str] = None,
) -> dict:
    """Pull People-Also-Ask questions for a service-in-geo + enrich with market
    data + suggest the "link high" service page. Reuses the metered SERP call
    exactly once. Returns candidates + resolution context (does NOT persist)."""
    client = _client(client_id)
    service_keyword = (service_keyword or "").strip()
    if not service_keyword:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="service_keyword_required")

    location = _location_label(client, location_override)
    location_code = _location_code(client)
    lang = settings.dataforseo_default_language_code
    depth = settings.keyword_research_serp_depth
    query = paa_seo.geo_query(service_keyword, location, geo_mode)

    # One live SERP call → PAA questions (reuses serp_snapshot, the suite's one
    # SERP parser). Best-effort: a failed pull yields no candidates, not a 500.
    paa_questions: list[str] = []
    cost = 0.0
    try:
        items = await serp_snapshot.fetch_serp(query, location_code, lang, depth)
        cost += 0.002
        paa_questions = serp_snapshot.extract_serp_features(items).get(
            "people_also_ask"
        ) or []
    except Exception as exc:
        logger.warning("paa.serp_failed", extra={"query": query, "error": str(exc)})

    paa_questions = _dedupe_paa(paa_questions)

    # One batch market call for volume/CPC (reused enrichment). Best-effort.
    market: dict = {}
    if paa_questions:
        try:
            market = await keyword_market.fetch_market(paa_questions, location_code)
        except Exception as exc:
            logger.warning("paa.market_failed", extra={"error": str(exc)})

    candidates = paa_seo.build_paa_candidates(paa_questions, market)
    auto_service_page = await _auto_match_service_page(client, service_keyword)

    return {
        "service_keyword": service_keyword,
        "location": location,
        "location_code": location_code,
        "geo_mode": geo_mode if geo_mode in ("geo", "naked") else "geo",
        "geo_query": query,
        "candidates": candidates,
        "auto_service_page_url": auto_service_page,
        "service_page_source": "auto" if auto_service_page else "none",
        "cost_usd": round(cost, 4),
    }


def _dedupe_paa(paa: list[str]) -> list[str]:
    """Dedupe pulled PAA questions via the suite's single PAA deduper (reuse —
    ``keyword_research_serp.dedupe_paa``), so there's one PAA-dedupe rule."""
    from services.keyword_research_serp import dedupe_paa

    return dedupe_paa([paa])


# ── save ────────────────────────────────────────────────────────────────────


def create_set(
    client_id: str,
    *,
    service_keyword: str,
    items: list[dict],
    geo_mode: str = "geo",
    location: Optional[str] = None,
    location_code: Optional[int] = None,
    service_page_url: Optional[str] = None,
    auto_service_page_url: Optional[str] = None,
    created_by: Optional[str] = None,
) -> dict:
    """Persist a PAA set + its chosen items. Resolves the service-page URL
    explicit → auto-match → none (needs_prompt) via ``paa_seo``."""
    from fastapi import HTTPException

    service_keyword = (service_keyword or "").strip()
    if not service_keyword:
        raise HTTPException(status_code=400, detail="service_keyword_required")
    chosen = [i for i in (items or []) if (i.get("question") or "").strip()]
    if not chosen:
        raise HTTPException(status_code=400, detail="no_questions_selected")

    resolved = paa_seo.resolve_service_page_url(service_page_url, auto_service_page_url)
    gm = geo_mode if geo_mode in ("geo", "naked") else "geo"

    set_row = (
        _sb().table("paa_sets").insert(
            {
                "client_id": client_id,
                "service_keyword": service_keyword,
                "location": (location or "").strip() or None,
                "location_code": location_code,
                "geo_mode": gm,
                "service_page_url": resolved["url"],
                "status": "draft",
                "created_by": created_by,
            }
        ).execute()
    ).data[0]

    rows = []
    for pos, it in enumerate(chosen):
        q = " ".join((it.get("question") or "").split()).strip()
        rows.append(
            {
                "set_id": set_row["id"],
                "client_id": client_id,
                "question": q,
                "slug": it.get("slug") or paa_seo.slugify_question(q),
                "volume": it.get("volume"),
                "cpc_usd": it.get("cpc_usd") if it.get("cpc_usd") is not None else it.get("cpc"),
                "competition": it.get("competition"),
                "chosen": True,
                "position": pos,
            }
        )
    item_rows = _sb().table("paa_items").insert(rows).execute().data or []
    set_row["items"] = sorted(item_rows, key=lambda r: r.get("position") or 0)
    set_row["service_page_source"] = resolved["source"]
    return set_row


def list_sets(client_id: str) -> list[dict]:
    """PAA sets for a client (newest first) with a chosen-count + post-count."""
    sets = (
        _sb().table("paa_sets").select("*").eq("client_id", client_id)
        .order("created_at", desc=True).execute()
    ).data or []
    if not sets:
        return []
    set_ids = [s["id"] for s in sets]
    items = (
        _sb().table("paa_items").select("set_id, run_id, chosen")
        .in_("set_id", set_ids).execute()
    ).data or []
    by_set: dict[str, dict] = {sid: {"chosen": 0, "posts": 0} for sid in set_ids}
    for it in items:
        agg = by_set.get(it["set_id"])
        if not agg:
            continue
        if it.get("chosen"):
            agg["chosen"] += 1
        if it.get("run_id"):
            agg["posts"] += 1
    for s in sets:
        agg = by_set.get(s["id"], {"chosen": 0, "posts": 0})
        s["chosen_count"] = agg["chosen"]
        s["post_count"] = agg["posts"]
    return sets


def get_set(set_id: str) -> dict:
    from fastapi import HTTPException

    rows = _sb().table("paa_sets").select("*").eq("id", set_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="paa_set_not_found")
    set_row = rows[0]
    set_row["items"] = (
        _sb().table("paa_items").select("*").eq("set_id", set_id)
        .order("position").execute()
    ).data or []
    return set_row


def delete_set(set_id: str) -> None:
    _sb().table("paa_sets").delete().eq("id", set_id).execute()


# ── cannibalization preflight ─────────────────────────────────────────────────


async def preflight(set_id: str, acknowledge: bool = False) -> dict:
    """The cannibalization guard for a set's chosen items (PRD §4.3). Reuses
    ``site_page_index`` existing-page matching + ``local_seo_matrix`` scale gates.
    Returns ``{gates, chosen_count, existing_site_matches, slug_collisions}``."""
    set_row = get_set(set_id)
    client = _client(set_row["client_id"])
    chosen = [i for i in set_row["items"] if i.get("chosen")]
    chosen_slugs = [i["slug"] for i in chosen]

    # 1) Cross-set slug collisions (this client's OTHER sets/cities).
    other_items = (
        _sb().table("paa_items")
        .select("id, set_id, slug, question")
        .eq("client_id", set_row["client_id"])
        .neq("set_id", set_id)
        .execute()
    ).data or []
    slug_collisions = paa_seo.find_slug_collisions(chosen_slugs, other_items)

    # 2) Existing live pages that already answer a chosen PAA (free sitemap scan).
    existing_site_matches: list[dict] = []
    website = client.get("website_url") or (client.get("gbp") or {}).get("website") or ""
    if website and chosen:
        try:
            urls, _src = await site_page_index.discover_site_urls(
                website, _location_code(client), use_paid_fallback=False
            )
            index = site_page_index.build_page_token_index(urls)
            for it in chosen:
                match = site_page_index.match_site_page_for_keyword(it["question"], index)
                if match:
                    existing_site_matches.append(
                        {"question": it["question"], "url": match}
                    )
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning("paa.preflight_site_scan_failed", extra={"error": str(exc)})

    # 3) Total PAA-page footprint for this client (the scale sign-off basis).
    total_paa_pages = (
        _sb().table("paa_items").select("id", count="exact")
        .eq("client_id", set_row["client_id"]).eq("chosen", True)
        .execute()
    ).count or 0

    gates = paa_seo.cannibalization_gates(
        create_count=len(chosen),
        total_client_paa_pages=int(total_paa_pages),
        slug_collisions=slug_collisions,
        existing_site_matches=existing_site_matches,
        signoff_acknowledged=acknowledge,
    )
    return {
        "gates": gates,
        "chosen_count": len(chosen),
        "slug_collisions": slug_collisions,
        "existing_site_matches": existing_site_matches,
    }


# ── create posts (blog runs + GBP + syndication) ──────────────────────────────


def _create_gbp_post(client_id: str, question: str, service_page_url: Optional[str], user_id: str) -> Optional[str]:
    """Best-effort GBP-post draft seeded from the exact PAA string. Skipped
    (returns None) when GBP Posts is disabled or the client has no OK location."""
    if not (settings.gbp_api_enabled and settings.gbp_posts_enabled):
        return None
    try:
        from services import gbp_posts_service

        locations = gbp_posts_service.list_ok_locations(client_id)
        if not locations:
            return None
        summary = question.strip()
        if len(summary) > 1400:
            summary = summary[:1400]
        body = {
            "location_row_id": locations[0]["id"],
            "topic_type": "standard",
            "summary": summary,
        }
        if service_page_url:
            body["cta_type"] = "LEARN_MORE"
            body["cta_url"] = service_page_url
        post = gbp_posts_service.create_post(client_id, body, user_id, source="paa")
        return post.get("id")
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("paa.gbp_post_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def _refresh_syndication(client_id: str) -> Optional[str]:
    """Best-effort: refresh the client's syndication queue so the PAA posts are
    discovered + syndicated once they're published to the live site (the module
    is scan-of-live-URLs by design — the exact-PAA title rides through publish).
    Only when the client already uses syndication. Never raises."""
    try:
        cfg = (
            _sb().table("syndication_config").select("enabled")
            .eq("client_id", client_id).limit(1).execute()
        ).data or []
        if not cfg or not cfg[0].get("enabled"):
            return None
        from services import syndication_service

        return syndication_service.enqueue_scan(client_id)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("paa.syndication_refresh_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


async def create_posts(set_id: str, user_id: str, acknowledge: bool = False) -> dict:
    """Create the PAA posts (PRD §10.5): one Blog Writer run per chosen PAA
    (seeded from the exact PAA string, ``writer_notes`` carrying the three rules),
    a best-effort GBP-post draft, and a best-effort syndication-queue refresh.

    Runs the cannibalization guard first (blocking unless ``acknowledge``).
    Returns ``{run_ids, created, gbp_created, syndication_job, blocked?}``. The
    caller (router) dispatches ``orchestrate_run`` for each returned run id."""
    from fastapi import HTTPException

    pre = await preflight(set_id, acknowledge=acknowledge)
    blocking = [g for g in pre["gates"] if g.get("blocking")]
    if blocking:
        return {"blocked": True, "gates": pre["gates"], "run_ids": []}

    set_row = get_set(set_id)
    client = _client(set_row["client_id"])
    client_id = set_row["client_id"]
    service_page_url = set_row.get("service_page_url")
    # Only items that don't already have a post — so a re-invoke (e.g. a Phase-3
    # drill round adds items to an existing set, then calls this again) creates
    # posts for the NEW items only and never duplicates a GBP draft for one that
    # was already created. First run: no item has a run_id, so all are created.
    chosen = [i for i in set_row["items"] if i.get("chosen") and not i.get("run_id")]

    run_ids: list[str] = []
    gbp_created = 0
    for it in chosen:
        question = it["question"]
        writer_notes = paa_seo.compose_writer_notes(
            question,
            service_page_url,
            service_keyword=set_row.get("service_keyword"),
            location=set_row.get("location"),
        )
        # One run per PAA — the PAA string IS the seed keyword (rule 1 structural,
        # rule 2/3 on writer_notes). Idempotent per item (a re-invoke adopts the
        # in-flight/complete run instead of duplicating).
        run_id = create_run_and_snapshot(
            client=client,
            keyword=question,
            content_type="blog_post",
            writer_notes=writer_notes,
            created_by=user_id,
            source_ref=f"paa_item:{it['id']}",
        )
        gbp_post_id = _create_gbp_post(client_id, question, service_page_url, user_id)
        if gbp_post_id:
            gbp_created += 1
        _sb().table("paa_items").update(
            {"run_id": run_id, "gbp_post_id": gbp_post_id}
        ).eq("id", it["id"]).execute()
        run_ids.append(run_id)

    syndication_job = _refresh_syndication(client_id)
    _sb().table("paa_sets").update({"status": "active", "updated_at": "now()"}).eq(
        "id", set_id
    ).execute()

    logger.info(
        "paa.posts_created",
        extra={"set_id": set_id, "runs": len(run_ids), "gbp": gbp_created},
    )
    return {
        "blocked": False,
        "run_ids": run_ids,
        "created": len(run_ids),
        "gbp_created": gbp_created,
        "syndication_job": syndication_job,
    }


# ── verify (deterministic post-generation checks) ─────────────────────────────


def _article_for_run(run_id: str) -> Optional[dict]:
    """Reconstruct a completed blog run's article HTML + headings for the
    deterministic checks. Reuses blog_page_score's sources_cited reader +
    HTML rebuilder. Returns None until the run's sources_cited is complete."""
    from services import blog_page_score as bps

    sc = bps._latest_output(run_id, "sources_cited")
    if not sc:
        return None
    article = (sc.get("output_payload") or {}).get("enriched_article") or []
    title, h1 = bps._blog_title_h1(run_id)
    html = bps.build_scoring_html(article, title, h1)
    headings = [s.get("heading") for s in article if isinstance(s, dict) and s.get("heading")]
    return {"html": html, "title": title, "h1": h1, "headings": headings}


def verify_posts(set_id: str) -> dict:
    """Run the deterministic writer-constraint checks (exact-match + service-page
    link) on each chosen item whose blog run has finished, persisting the verdict
    on ``paa_items.checks``. Items whose run isn't complete yet are left pending.
    Returns ``{verified, pending, items}``."""
    set_row = get_set(set_id)
    service_page_url = set_row.get("service_page_url")
    verified = 0
    pending = 0
    out_items: list[dict] = []
    for it in set_row["items"]:
        if not it.get("chosen"):
            continue
        run_id = it.get("run_id")
        if not run_id:
            pending += 1
            out_items.append(it)
            continue
        art = _article_for_run(run_id)
        if not art:
            pending += 1
            out_items.append(it)
            continue
        checks = paa_seo.verify_item_checks(
            it["question"],
            art["html"],
            service_page_url,
            title=art["title"],
            h1=art["h1"],
            headings=art["headings"],
        )
        _sb().table("paa_items").update({"checks": checks}).eq("id", it["id"]).execute()
        it["checks"] = checks
        verified += 1
        out_items.append(it)
    return {"verified": verified, "pending": pending, "items": out_items}
