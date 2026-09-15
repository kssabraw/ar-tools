"""Brand Guide Generator — Phase 1 capture pipeline + the generate job.

The real, worker-run capture layer (no headless browser — ADR 2026-09-15 / PRD
§4.1). Phase 0 shipped the pure extraction core (`brand_guide_extract`) and the
D4 palette spike (gate PASSED live: `css_recovered_any=true`, 4/4 sites captured).
This module wraps that proven capture path in the durable module: capture the
homepage (the visual authority) + up to 2 auto-discovered key pages via the
existing ScrapeOwl (`render_js`) + DataForSEO `page_screenshot` production paths,
run the deterministic census, and store `captured` + `visual_census` on a
versioned `brand_guides` row.

Phase 1 does capture → extract → store census ONLY. There is no synthesis (Phase
2), no aesthetic/vibe read (Phase 1.5), and no PDF render (Phase 3) here — so the
`brand_guide_generate` job finalizes `done` after storing the census, and the
regulated `awaiting_signoff` gate (which gates *synthesis* output for
`content_compliance_mode != 'off'` clients) does not engage yet (nothing
synthesized to sign off).

Everything is gated on `settings.brand_guide_enabled` and best-effort: a dead
page, a ScrapeOwl bot-block (401), a missing screenshot, or a client with no site
each degrades that part of the capture and is recorded in the page's notes —
never raised (PRD §5.4). Pillow lives here (the canonical capture home); the pure
census never imports it.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import brand_guide_extract as bg

logger = logging.getLogger(__name__)

_BUCKET = "brand-guides"
# How many logo candidates to keep after merging across the captured pages.
_MAX_LOGOS = 10

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]*content=["\']([^"\']*)["\']', re.I
)
_META_DESC_REV_RE = re.compile(
    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*name=["\']description["\']', re.I
)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


# --------------------------------------------------------------------------
# Pillow pixel-dominance (the canonical capture home; the spike re-exports this)
# --------------------------------------------------------------------------
def pixel_counts_from_png(png: bytes, *, max_colors: int = 40, max_dim: int = 500):
    """Pillow median-cut quantization → a ``[(rgb, pixel_count)]`` dominance table.

    Downscaled first (dominance *ratios* are scale-invariant, and it keeps the
    quantize cheap on a tall full-page screenshot). Pillow is imported lazily so
    this module loads in environments without it (the pure census never needs it).
    Returns ``[]`` on any Pillow failure so the caller degrades to CSS-only.
    """
    try:
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand_guide.no_pillow", extra={"error": str(exc)})
        return []
    import io

    try:
        im = Image.open(io.BytesIO(png)).convert("RGB")
        im.thumbnail((max_dim, max_dim * 6))  # cap the longest side; keep aspect
        quant = im.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT)
        palette = quant.getpalette() or []
        out: list[tuple[tuple[int, int, int], int]] = []
        for count, idx in quant.getcolors(maxcolors=max_colors * 4) or []:
            base = idx * 3
            out.append(((palette[base], palette[base + 1], palette[base + 2]), count))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand_guide.quantize_failed", extra={"error": str(exc)})
        return []


# --------------------------------------------------------------------------
# Per-page capture (best-effort — records a reason on every degrade path)
# --------------------------------------------------------------------------
def _dom_digest(html: str) -> dict:
    """A light DOM digest for the capture record + Phase-2 synthesis context."""
    def _first(rx, s):
        m = rx.search(s)
        return _TAG_STRIP_RE.sub(" ", m.group(1)).strip()[:400] if m else ""

    desc = _first(_META_DESC_RE, html) or _first(_META_DESC_REV_RE, html)
    return {
        "title": _first(_TITLE_RE, html),
        "meta_description": desc,
        "h1": _first(_H1_RE, html),
    }


async def _capture_page(url: str, role: str) -> dict:
    """Capture one page through the REAL production paths.

    ScrapeOwl (rendered HTML, premium retry on empty) + DataForSEO screenshot
    (Pillow dominance) each degrade independently. Finding 3 of the Phase-0 spike
    — some sites hard-block ScrapeOwl (401) even with premium — is handled here:
    the failure is recorded as a page note and capture continues to the screenshot
    path, which is the essential palette fallback when HTML is unavailable. The raw
    ``_html`` / ``_pixels`` / ``_png`` are internal (popped before storage).
    """
    from services.qa_visual import capture_screenshot
    from services.website_scraper import scrapeowl_fetch

    rec: dict = {"url": url, "role": role, "notes": []}

    # 1. Rendered HTML (ScrapeOwl), premium retry when the plain fetch is empty.
    html = ""
    try:
        html = await scrapeowl_fetch(url, render_js=True)
        if not html.strip():
            html = await scrapeowl_fetch(url, render_js=True, premium=True)
    except Exception as exc:  # noqa: BLE001
        rec["notes"].append(f"scrapeowl_failed: {type(exc).__name__}: {str(exc)[:200]}")
    rec["html_len"] = len(html)
    if not html.strip():
        rec["notes"].append(
            "html_unavailable: rendered HTML empty (bot-block / 401 / error) — "
            "degraded to screenshot-only; palette from pixels, no CSS hex / fonts / type"
        )

    # 2. Screenshot (DataForSEO) → Pillow pixel-dominance table.
    png: Optional[bytes] = None
    try:
        png = await capture_screenshot(url)
    except Exception as exc:  # noqa: BLE001
        rec["notes"].append(f"screenshot_failed: {type(exc).__name__}: {str(exc)[:200]}")
    if png is None:
        rec["notes"].append("screenshot_unavailable: capture returned None (creds/limit/error)")
    rec["has_screenshot"] = bool(png)

    rec["_html"] = html
    rec["_png"] = png
    rec["_pixels"] = pixel_counts_from_png(png) if png else []
    return rec


def _store_screenshot(client_id: str, guide_id: str, role: str, png: Optional[bytes]) -> Optional[str]:
    """Persist a page screenshot to the private `brand-guides` bucket → its path.

    Kept so the Phase-1.5 vibe read reuses the capture instead of re-paying
    DataForSEO. Best-effort — a storage failure just drops the path (the census is
    already computed from the pixels in-memory)."""
    if not png:
        return None
    path = f"{client_id}/{guide_id}/{role}.png"
    try:
        get_supabase().storage.from_(_BUCKET).upload(
            path, png, {"content-type": "image/png", "upsert": "true"}
        )
        return path
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand_guide.screenshot_store_failed", extra={"path": path, "error": str(exc)})
        return None


def _merge_logo_candidates(base: list, extra_pages: list) -> list:
    """Merge homepage logo candidates with the +2 pages' candidates (PRD §4.1).

    The extra pages contribute logo VARIETY only — never the palette/fonts/type
    census. Deduped by URL keeping the best score, re-sorted, capped."""
    by_url: dict[str, bg.LogoCandidate] = {}
    for cand in base:
        by_url[cand.url] = cand
    for rec in extra_pages:
        for cand in bg.logo_candidates_from_html(rec.get("_html", ""), base_url=rec["url"]):
            prev = by_url.get(cand.url)
            if prev is None or cand.score > prev.score:
                by_url[cand.url] = cand
    return sorted(by_url.values(), key=lambda c: c.score, reverse=True)[:_MAX_LOGOS]


# --------------------------------------------------------------------------
# The capture pipeline
# --------------------------------------------------------------------------
def _set(guide_id: str, fields: dict) -> None:
    get_supabase().table("brand_guides").update(fields).eq("id", guide_id).execute()


async def generate_brand_guide(
    guide_id: str,
    client_id: str,
    source_url: Optional[str],
    *,
    pages_override: Optional[list] = None,
    max_pages: Optional[int] = None,
) -> dict:
    """Capture → extract → store the visual census on the brand_guides row.

    Homepage is the SOLE palette/fonts/type source (§4.1); the +2 auto-discovered
    pages (operator-overridable) add logo variety + a capture record only. Returns
    a small result summary for the job row."""
    max_pages = settings.brand_guide_max_pages if max_pages is None else max_pages
    source_url = (source_url or "").strip()
    _set(guide_id, {"status": "capturing"})

    # No site → a guide with the visual layer marked unavailable (§5.4). Phase 1
    # stores an empty census + a note; Phase 2 generates the prescriptive layer.
    if not source_url:
        census = bg.VisualCensus(notes=["No source URL — visual capture skipped; guide will rest on voice/ICP assets."])
        _set(guide_id, {
            "status": "done",
            "captured": {"pages": [], "page_count": 0, "no_source_url": True},
            "visual_census": census.as_dict(),
            "generated_at": "now()",
        })
        return {"guide_id": guide_id, "pages": 0, "palette_source": "none", "no_source_url": True}

    # 1. Homepage — the visual authority.
    home = await _capture_page(source_url, "homepage")
    home_html = home["_html"]

    # 2. Up to N key pages (operator override wins; else auto-discover from nav).
    if pages_override:
        extra_urls = [u.strip() for u in pages_override if isinstance(u, str) and u.strip()][:max_pages]
    else:
        extra_urls = bg.discover_key_pages(home_html, source_url, limit=max_pages)
    extra = []
    for i, u in enumerate(extra_urls, 1):
        extra.append(await _capture_page(u, f"page-{i}"))

    # 3. Census — HOMEPAGE ONLY for palette/fonts/type (§4.1); extras add logos.
    census = bg.extract_visual_census(home_html, pixel_counts=home["_pixels"], base_url=source_url)
    census.logo_candidates = _merge_logo_candidates(census.logo_candidates, extra)
    census.notes.append(
        f"Captured {1 + len(extra)} page(s); palette/fonts/type measured from the homepage only "
        f"(the +{len(extra)} page(s) contribute logo candidates + imagery variety, not the palette)."
    )

    # 4. Store screenshots + assemble the `captured` record.
    captured_pages = []
    for rec in [home, *extra]:
        png = rec.pop("_png", None)
        html = rec.pop("_html", "")
        rec.pop("_pixels", None)
        path = _store_screenshot(client_id, guide_id, rec["role"], png)
        captured_pages.append({
            "url": rec["url"],
            "role": rec["role"],
            "html_len": rec.get("html_len", 0),
            "has_screenshot": rec.get("has_screenshot", False),
            "screenshot_path": path,
            "dom_digest": _dom_digest(html),
            "notes": rec.get("notes", []),
        })

    _set(guide_id, {
        "status": "done",
        "source_url": source_url,
        "captured": {"pages": captured_pages, "page_count": len(captured_pages)},
        "visual_census": census.as_dict(),
        "generated_at": "now()",
    })
    logger.info(
        "brand_guide.capture_complete",
        extra={"guide_id": guide_id, "client_id": client_id, "pages": len(captured_pages),
               "palette_source": census.palette_source, "colors": len(census.colors)},
    )
    return {
        "guide_id": guide_id,
        "pages": len(captured_pages),
        "palette_source": census.palette_source,
        "colors": len(census.colors),
        "fonts": len(census.fonts),
        "logo_candidates": len(census.logo_candidates),
    }


# --------------------------------------------------------------------------
# Enqueue + job handler
# --------------------------------------------------------------------------
def _next_version(supabase, client_id: str) -> int:
    rows = (
        supabase.table("brand_guides").select("version")
        .eq("client_id", client_id).order("version", desc=True).limit(1).execute().data
        or []
    )
    return (rows[0]["version"] + 1) if rows else 1


def _resolve_source_url(supabase, client_id: str) -> str:
    rows = supabase.table("clients").select("website_url").eq("id", client_id).limit(1).execute().data or []
    return (rows[0].get("website_url") or "").strip() if rows else ""


def enqueue_brand_guide_generate(
    client_id: str,
    source_url: Optional[str] = None,
    pages: Optional[list] = None,
    user_id: Optional[str] = None,
) -> str:
    """Create a queued brand_guides row (next version) + its async job. Returns the
    guide id. ``source_url`` defaults to the client's website_url; ``pages`` is an
    operator page-scope override (else nav auto-discovery). ``user_id`` (initiator)
    drives the Activity indicator + completion ping."""
    supabase = get_supabase()
    if source_url is None:
        source_url = _resolve_source_url(supabase, client_id)
    version = _next_version(supabase, client_id)
    row = (
        supabase.table("brand_guides")
        .insert({"client_id": client_id, "version": version, "status": "queued",
                 "source_url": source_url or None})
        .execute()
    ).data[0]
    guide_id = row["id"]
    supabase.table("async_jobs").insert({
        "job_type": "brand_guide_generate", "entity_id": client_id,
        "payload": {"guide_id": guide_id, "client_id": client_id,
                    "source_url": source_url, "pages": pages, "user_id": user_id},
    }).execute()
    return guide_id


async def run_brand_guide_generate_job(job: dict) -> None:
    """async_jobs handler for job_type='brand_guide_generate' (Phase 1).

    Gated on `brand_guide_enabled` — an enqueue while the module is dark settles
    without spending on paid vendor calls. Defensive: a job hand-inserted with only
    `{client_id}` (the worker-verification path, like the spike) creates its own
    queued row so a bare insert on the deployed worker runs end-to-end."""
    job_id = job["id"]
    payload = job.get("payload") or {}
    supabase = get_supabase()

    if not settings.brand_guide_enabled:
        gid = payload.get("guide_id")
        if gid:
            supabase.table("brand_guides").update(
                {"status": "error", "error": "brand_guide_disabled"}
            ).eq("id", gid).execute()
        supabase.table("async_jobs").update(
            {"status": "complete",
             "result": {"skipped": "brand_guide_disabled",
                        "note": "Set BRAND_GUIDE_ENABLED=true on PLATFORM to run capture."},
             "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("brand_guide.disabled", extra={"job_id": job_id})
        return

    client_id = payload.get("client_id")
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    guide_id = payload.get("guide_id")
    source_url = payload.get("source_url")
    if source_url is None:
        source_url = _resolve_source_url(supabase, client_id)
    if not guide_id:  # bare {client_id} job (worker verification) → create the row
        version = _next_version(supabase, client_id)
        guide_id = (
            supabase.table("brand_guides")
            .insert({"client_id": client_id, "version": version, "status": "queued",
                     "source_url": source_url or None})
            .execute()
        ).data[0]["id"]

    logger.info("brand_guide.started", extra={"job_id": job_id, "guide_id": guide_id, "client_id": client_id})
    try:
        result = await generate_brand_guide(
            guide_id, client_id, source_url, pages_override=payload.get("pages")
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand_guide.job_failed", extra={"guide_id": guide_id, "error": str(exc)})
        supabase.table("brand_guides").update(
            {"status": "error", "error": str(exc)[:500]}
        ).eq("id", guide_id).execute()
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
