"""Brand Guide — D4 palette-method spike, the worker-runnable core (PRD §10).

The impure half of the D4 spike: the live capture (ScrapeOwl rendered HTML +
DataForSEO screenshot), the Pillow pixel-dominance quantization, and the
per-site report assembly over the pure census (`brand_guide_extract`). Split out
of the CLI script so BOTH the `scripts/spike_brand_guide_palette.py` command
(local/PLATFORM shell) AND the `brand_guide_spike` async job (deployed worker)
run the *same* capture path — the worker can't import a `scripts/` module, and
duplicating the capture logic would let the two drift.

Pillow lives here (and in the future Phase-1 capture layer), never in the pure
census. Everything is best-effort: a dead page / missing screenshot / bad creds
degrades that part of the report and is recorded in `errors`, never raised — the
spike's job is to *measure*, so a site that half-captures is still a data point.

**The gate this feeds (PRD §11 #1):** compare each site's merged palette to a
manual eyedropper; if declared-hex-from-scraped-CSS recovers nothing across sites
AND the pixel-sampled palette is unacceptably wrong, reopen the ADR before Phase 1.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# How many swatches to keep in the report's palette previews (the full merged
# census is kept under "colors"; these are just the human-readable heads).
_PREVIEW = 14


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
        logger.warning("brand_guide_spike.no_pillow", extra={"error": str(exc)})
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
        logger.warning("brand_guide_spike.quantize_failed", extra={"error": str(exc)})
        return []


async def capture_site_report(url: str) -> dict:
    """Capture one site through the REAL production paths → a spike report dict.

    Best-effort: ScrapeOwl (rendered HTML, premium retry on empty) + DataForSEO
    `page_screenshot` (Pillow dominance) each degrade independently; the pure
    two-tier census assembles whatever was captured. No printing — the CLI and
    the worker both consume this dict.
    """
    from services import brand_guide_extract as bg
    from services.qa_visual import capture_screenshot
    from services.website_scraper import scrapeowl_fetch

    report: dict = {"url": url, "errors": []}

    # 1. Rendered HTML (ScrapeOwl), premium retry when the plain fetch is empty.
    html = ""
    try:
        html = await scrapeowl_fetch(url, render_js=True)
        if not html.strip():
            html = await scrapeowl_fetch(url, render_js=True, premium=True)
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"scrapeowl: {type(exc).__name__}: {exc}")
    report["html_len"] = len(html)

    decls = bg.css_declarations(html)
    css_palette, _css_src = bg.build_color_census(css_declarations_list=decls)
    report["css_decl_count"] = len(decls)
    report["css_color_count"] = len(css_palette)
    report["css_palette"] = [s.as_dict() for s in css_palette[:_PREVIEW]]

    # 2. Screenshot (DataForSEO) → Pillow pixel-dominance table.
    pixels: Optional[list] = None
    try:
        png = await capture_screenshot(url)
        if png:
            report["screenshot_bytes"] = len(png)
            pixels = pixel_counts_from_png(png)
            report["quantized_colors"] = len(pixels)
        else:
            report["errors"].append("screenshot: capture returned None (creds/limit/error)")
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"screenshot: {type(exc).__name__}: {exc}")
    report["has_screenshot"] = bool(pixels)

    # 3. The real two-tier merged census (what the module will ship).
    census = bg.extract_visual_census(html, pixel_counts=pixels, base_url=url)
    report["palette_source"] = census.palette_source
    report["merged_color_count"] = len(census.colors)
    report["snapped_to_css"] = sum(1 for c in census.colors if c.source == "both")
    report["pixel_only"] = sum(1 for c in census.colors if c.source == "pixel")
    report["colors"] = [c.as_dict() for c in census.colors]
    report["colors_preview"] = [c.as_dict() for c in census.colors[:_PREVIEW]]
    report["fonts"] = [f.as_dict() for f in census.fonts[:8]]
    report["type_scale"] = [t.as_dict() for t in census.type_scale]
    report["logo_candidates"] = [c.as_dict() for c in census.logo_candidates[:5]]
    report["notes"] = census.notes
    return report


async def run_spike(urls: list[str]) -> list[dict]:
    """Capture every URL sequentially (paid calls — no need to fan out) → reports."""
    reports: list[dict] = []
    for url in urls:
        try:
            reports.append(await capture_site_report(url))
        except Exception as exc:  # noqa: BLE001 — a hard failure is still a data point
            logger.warning("brand_guide_spike.site_failed", extra={"url": url, "error": str(exc)})
            reports.append({"url": url, "errors": [f"{type(exc).__name__}: {exc}"]})
    return reports


def summarize(reports: list[dict]) -> dict:
    """The D4 gate at a glance — the per-site read a human weighs vs the eyedropper.

    ``css_recovered_any`` is the headline for the unproven half of D4: True when
    scraped CSS yielded ≥1 declared colour on ≥1 site (the refinement fires);
    all-False means pixel-sampled hex is the real output and the ADR's fallback
    reasoning applies.
    """
    sites = [r for r in reports if "url" in r]
    ran = [r for r in sites if r.get("html_len") or r.get("has_screenshot")]
    css_any = any((r.get("css_color_count") or 0) > 0 for r in sites)
    return {
        "sites": len(sites),
        "captured": len(ran),
        "css_recovered_any": css_any,
        "per_site": [
            {
                "url": r.get("url"),
                "css_colors": r.get("css_color_count", 0),
                "palette_source": r.get("palette_source", "none"),
                "merged_colors": r.get("merged_color_count", 0),
                "snapped_to_css": r.get("snapped_to_css", 0),
                "pixel_only": r.get("pixel_only", 0),
                "errors": r.get("errors", []),
            }
            for r in sites
        ],
    }
