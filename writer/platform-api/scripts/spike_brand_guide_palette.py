"""D4 palette-method spike for the Brand Guide Generator (PRD §10 / §11 #1).

**The decisive gate before any Phase 1 work.** The PRD reverses the original
headless-browser plan: the palette is now recovered with **no browser** —
screenshot pixel-dominance (Pillow over the DataForSEO `page_screenshot`) as the
*primary* signal, refined by *declared hex from scraped CSS* (ScrapeOwl,
`render_js=True`) where a dominant colour matches a CSS declaration.

The "declared hex from scraped CSS" half is an **unproven hypothesis**:
`scrapeowl_fetch` returns rendered DOM markup, not inlined external stylesheets,
so colours defined in linked CSS / `var(--x)` custom properties / utility classes
(Tailwind) may never appear as inline `color:`/`background-color:` declarations.
This script runs the **real** ScrapeOwl + DataForSEO + Pillow + census path
against live client sites and measures, per site:

  * how many colours the scraped CSS actually yielded (the D4 hypothesis's
    survival — zero on a Tailwind/external-CSS site means the CSS half adds
    nothing and pixel-sampled hex is the real output),
  * the pixel-dominant palette (what actually dominates the render),
  * how many dominant swatches SNAPPED to an exact declared CSS hex (`both`) vs
    kept a pixel-sampled hex (`pixel`),
  * fonts / type scale / logo candidates recovered.

Compare the printed palette against a **manual eyedropper** on each site
(acceptance #1, within the stated tolerance: exact for CSS-matched colours; a
small ΔE for pixel-sampled ones). **Gate:** if declared-hex-from-CSS doesn't
recover real brand colours AND the pixel-sampled palette is unacceptably wrong,
STOP and reopen the ADR (decisions.md, "Brand Guide Generator — no headless
browser") before building Phase 1.

---
**RUN IT ON THE WORKER (PLATFORM), NOT THE SANDBOX.** The Claude Code sandbox's
egress policy blocks `api.scrapeowl.com` and `api.dataforseo.com` (org-policy 403
on CONNECT — verified 2026-09-15), exactly like DataForSEO/nlp. Production Railway
egress is open and both vendors are already used there. This reuses the live
production code paths (`services.website_scraper.scrapeowl_fetch`,
`services.qa_visual.capture_screenshot`) + the Phase-0 pure census
(`services.brand_guide_extract`), so run it from the platform-api service where
`SCRAPEOWL_API_KEY` / `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` already live:

    cd writer/platform-api
    # >=3 live client sites (positional URLs win); or pull from the clients table:
    python scripts/spike_brand_guide_palette.py https://site-a.com https://site-b.com https://site-c.com
    python scripts/spike_brand_guide_palette.py --from-clients 5     # newest 5 clients w/ a website_url
    python scripts/spike_brand_guide_palette.py --json report.json   # machine-readable dump too

Exit code 0 = ran to completion on >=1 site (a human still makes the gate call
against the eyedropper); non-zero = every site failed to capture.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from typing import Optional


def _pixel_counts_from_png(png: bytes, *, max_colors: int = 40, max_dim: int = 500):
    """Pillow median-cut quantization → a ``[(rgb, pixel_count)]`` dominance table.

    Downscaled first (dominance *ratios* are scale-invariant and this keeps the
    quantize cheap on a tall full-page screenshot). Pillow lives only here / in
    the Phase-1 capture layer — the pure census (`brand_guide_extract`) never
    imports it.
    """
    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("RGB")
    # Cap the longest side; a tall screenshot keeps its aspect ratio.
    im.thumbnail((max_dim, max_dim * 6))
    quant = im.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette() or []
    out: list[tuple[tuple[int, int, int], int]] = []
    for count, idx in quant.getcolors(maxcolors=max_colors * 4) or []:
        base = idx * 3
        rgb = (palette[base], palette[base + 1], palette[base + 2])
        out.append((rgb, count))
    return out


def _client_urls(limit: int) -> list[str]:
    from db.supabase_client import get_supabase

    sb = get_supabase()
    rows = (
        sb.table("clients")
        .select("name, website_url")
        .neq("website_url", "")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    urls = []
    for r in rows:
        url = (r.get("website_url") or "").strip()
        if url:
            urls.append(url)
    return urls


def _fmt_swatch(sw) -> str:
    tag = {"both": "CSS✔", "pixel": "pixel", "css": "css"}.get(sw.source, sw.source)
    css = f" declared={sw.css_hex}" if sw.css_hex and sw.source == "both" else ""
    return f"    {sw.hex}  share={sw.share*100:5.1f}%  [{tag}]  members={sw.member_count}{css}"


def run_site(url: str) -> dict:
    import asyncio

    from services import brand_guide_extract as bg
    from services.qa_visual import capture_screenshot
    from services.website_scraper import scrapeowl_fetch

    print("\n" + "=" * 78)
    print(f"SITE: {url}")
    print("=" * 78)
    report: dict = {"url": url}

    # --- 1. Rendered HTML via ScrapeOwl (retry with premium proxies if empty) ---
    html = ""
    try:
        html = asyncio.run(scrapeowl_fetch(url, render_js=True))
        if not html.strip():
            print("  scrapeowl returned empty HTML — retrying with premium proxies")
            html = asyncio.run(scrapeowl_fetch(url, render_js=True, premium=True))
    except Exception as exc:  # noqa: BLE001 — best-effort spike
        print(f"  ScrapeOwl FAILED: {type(exc).__name__}: {exc}")
    report["html_len"] = len(html)

    decls = bg.css_declarations(html)
    css_palette, css_src = bg.build_color_census(css_declarations_list=decls)
    report["css_decl_count"] = len(decls)
    report["css_color_count"] = len(css_palette)
    print(f"\n  HTML: {len(html):,} chars   CSS declarations: {len(decls):,}")
    print(f"  --- CSS-DECLARED palette ({len(css_palette)} swatches, source={css_src}) "
          f"[the D4 hypothesis: 0 here => scraped CSS adds no colour] ---")
    for sw in css_palette[:12]:
        print(_fmt_swatch(sw))
    if not css_palette:
        print("    (none — external stylesheet / var() / utility classes not surfaced)")

    # --- 2. Screenshot via DataForSEO → Pillow pixel dominance ---
    pixels = None
    try:
        png = asyncio.run(capture_screenshot(url))
        if png:
            pixels = _pixel_counts_from_png(png)
            print(f"\n  Screenshot: {len(png):,} bytes  → {len(pixels)} quantized colours")
        else:
            print("\n  Screenshot: capture returned None (DataForSEO creds/limit/error)")
    except Exception as exc:  # noqa: BLE001
        print(f"\n  Screenshot FAILED: {type(exc).__name__}: {exc}")
    report["has_screenshot"] = bool(pixels)

    # --- 3. The real two-tier merged census (what the module will ship) ---
    census = bg.extract_visual_census(html, pixel_counts=pixels, base_url=url)
    report["palette_source"] = census.palette_source
    report["merged_color_count"] = len(census.colors)
    snapped = sum(1 for c in census.colors if c.source == "both")
    pixel_only = sum(1 for c in census.colors if c.source == "pixel")
    report["snapped_to_css"] = snapped
    report["pixel_only"] = pixel_only

    print(f"\n  === MERGED CENSUS (palette_source={census.palette_source}) — "
          f"COMPARE THESE vs a manual eyedropper ===")
    for sw in census.colors[:14]:
        print(_fmt_swatch(sw))
    if census.palette_source == "pixel":
        print(f"\n  D4 SIGNAL: {snapped}/{len(census.colors)} dominant swatches snapped to an "
              f"exact CSS-declared hex; {pixel_only} kept a pixel-sampled hex.")
        if snapped == 0:
            print("  ⚠️  declared-hex-from-CSS recovered NOTHING here — pixel-sampled hex is the "
                  "real output on this site (Tailwind/external-CSS signature).")

    font_labels = [f.name + ("*" if f.google else "") for f in census.fonts[:6]]
    print(f"\n  Fonts (*=Google Font): {font_labels}")
    print(f"  Type scale (px): {[t.px for t in census.type_scale[:10]]}")
    print(f"  Logo candidates: {[(c.source, c.url) for c in census.logo_candidates[:4]]}")
    if census.notes:
        print(f"  Notes: {census.notes}")

    report["fonts"] = [f.as_dict() for f in census.fonts[:8]]
    report["type_scale"] = [t.as_dict() for t in census.type_scale]
    report["logo_candidates"] = [c.as_dict() for c in census.logo_candidates[:5]]
    report["colors"] = [c.as_dict() for c in census.colors]
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="D4 palette-method spike (run on PLATFORM).")
    ap.add_argument("urls", nargs="*", help="Client site URLs (>=3 recommended).")
    ap.add_argument("--from-clients", type=int, metavar="N", default=0,
                    help="If no URLs given, pull the newest N clients' website_url from Supabase.")
    ap.add_argument("--json", metavar="PATH", help="Also write a machine-readable JSON report.")
    args = ap.parse_args()

    urls = list(args.urls)
    if not urls and args.from_clients:
        try:
            urls = _client_urls(args.from_clients)
            print(f"Pulled {len(urls)} client URL(s) from Supabase: {urls}")
        except Exception as exc:  # noqa: BLE001
            print(f"Could not pull client URLs: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    if not urls:
        ap.error("give >=1 URL, or --from-clients N")

    reports = []
    ran = 0
    for url in urls:
        try:
            rep = run_site(url)
            reports.append(rep)
            if rep.get("html_len") or rep.get("has_screenshot"):
                ran += 1
        except Exception as exc:  # noqa: BLE001
            print(f"\nSITE {url} errored hard: {type(exc).__name__}: {exc}", file=sys.stderr)
            reports.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    # --- Cross-site summary: the D4 gate at a glance ---
    print("\n" + "#" * 78)
    print("# D4 GATE SUMMARY  (acceptance #1 — eyedropper comparison is the human call)")
    print("#" * 78)
    print(f"{'site':<40} {'cssColors':>9} {'srcPal':>7} {'swatches':>8} {'snapped':>7} {'pixel':>6}")
    for r in reports:
        if "error" in r:
            print(f"{r['url'][:39]:<40} {'ERR':>9}")
            continue
        print(f"{r['url'][:39]:<40} {r.get('css_color_count', 0):>9} "
              f"{r.get('palette_source', '-'):>7} {r.get('merged_color_count', 0):>8} "
              f"{r.get('snapped_to_css', 0):>7} {r.get('pixel_only', 0):>6}")
    print(
        "\nRead: cssColors>0 across sites => the declared-hex refinement is real; "
        "\n      cssColors≈0 but sensible pixel swatches => pixel-sampled hex is the output "
        "(D4 still holds, CSS half just doesn't fire);"
        "\n      garbage pixel swatches AND no CSS colours => reopen the ADR."
    )

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(reports, fh, indent=2)
        print(f"\nJSON report → {args.json}")

    return 0 if ran else 1


if __name__ == "__main__":
    raise SystemExit(main())
