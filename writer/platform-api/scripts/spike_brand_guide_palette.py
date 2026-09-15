"""D4 palette-method spike for the Brand Guide Generator (PRD §10 / §11 #1) — CLI.

**The decisive gate before any Phase 1 work.** The PRD reverses the original
headless-browser plan: the palette is now recovered with **no browser** —
screenshot pixel-dominance (Pillow over the DataForSEO `page_screenshot`) as the
*primary* signal, refined by *declared hex from scraped CSS* (ScrapeOwl,
`render_js=True`) where a dominant colour matches a CSS declaration.

The "declared hex from scraped CSS" half is an **unproven hypothesis**:
`scrapeowl_fetch` returns rendered DOM markup, not inlined external stylesheets,
so colours defined in linked CSS / `var(--x)` / utility classes (Tailwind) may
never appear as inline `color:`/`background-color:` declarations. This command
runs the **real** ScrapeOwl + DataForSEO + Pillow + census path against live
client sites and prints, per site, whether the CSS half fired (`css_colors`),
the pixel-dominant palette, how many swatches SNAPPED to a declared hex (`both`)
vs kept a pixel-sampled hex (`pixel`), fonts / type scale / logo candidates.

Compare the printed palette against a **manual eyedropper** (acceptance #1: exact
for CSS-matched colours; a small ΔE for pixel-sampled ones). **Gate:** if
declared-hex-from-CSS doesn't recover real brand colours AND the pixel-sampled
palette is unacceptably wrong, STOP and reopen the ADR (decisions.md, "Brand
Guide Generator — no headless browser") before Phase 1.

This is a thin printer over `services.brand_guide_spike` — the SAME capture core
the `brand_guide_spike` async job runs on the deployed worker, so the two can't
drift. Prefer the worker job (structured result in the DB) when you can; this CLI
is for a hands-on run.

---
**RUN IT ON THE WORKER (PLATFORM), NOT THE SANDBOX.** The Claude Code sandbox's
egress policy blocks `api.scrapeowl.com` and `api.dataforseo.com` (org-policy 403
on CONNECT), exactly like DataForSEO/nlp. Run from the platform-api service where
`SCRAPEOWL_API_KEY` / `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` already live:

    cd writer/platform-api
    python scripts/spike_brand_guide_palette.py https://site-a.com https://site-b.com https://site-c.com
    python scripts/spike_brand_guide_palette.py --from-clients 5      # newest 5 clients w/ a website_url
    python scripts/spike_brand_guide_palette.py --json report.json    # machine-readable dump too

Exit code 0 = ran to completion on >=1 site; non-zero = every site failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def _fmt_swatch(d: dict) -> str:
    tag = {"both": "CSS✔", "pixel": "pixel", "css": "css"}.get(d.get("source"), d.get("source"))
    css = f" declared={d['css_hex']}" if d.get("css_hex") and d.get("source") == "both" else ""
    return (f"    {d['hex']}  share={d.get('share', 0) * 100:5.1f}%  "
            f"[{tag}]  members={d.get('member_count', 1)}{css}")


def _print_report(r: dict) -> None:
    print("\n" + "=" * 78)
    print(f"SITE: {r.get('url')}")
    print("=" * 78)
    for err in r.get("errors", []):
        print(f"  ! {err}")
    print(f"\n  HTML: {r.get('html_len', 0):,} chars   CSS declarations: {r.get('css_decl_count', 0):,}")
    print(f"  --- CSS-DECLARED palette ({r.get('css_color_count', 0)} swatches) "
          f"[the D4 hypothesis: 0 here => scraped CSS adds no colour] ---")
    for sw in r.get("css_palette", []):
        print(_fmt_swatch(sw))
    if not r.get("css_palette"):
        print("    (none — external stylesheet / var() / utility classes not surfaced)")

    if r.get("has_screenshot"):
        print(f"\n  Screenshot: {r.get('screenshot_bytes', 0):,} bytes "
              f"→ {r.get('quantized_colors', 0)} quantized colours")
    else:
        print("\n  Screenshot: none")

    print(f"\n  === MERGED CENSUS (palette_source={r.get('palette_source')}) — "
          f"COMPARE THESE vs a manual eyedropper ===")
    for sw in r.get("colors_preview", []):
        print(_fmt_swatch(sw))
    if r.get("palette_source") == "pixel":
        snapped, total = r.get("snapped_to_css", 0), r.get("merged_color_count", 0)
        print(f"\n  D4 SIGNAL: {snapped}/{total} dominant swatches snapped to an exact "
              f"CSS-declared hex; {r.get('pixel_only', 0)} kept a pixel-sampled hex.")
        if snapped == 0:
            print("  ⚠️  declared-hex-from-CSS recovered NOTHING here — pixel-sampled hex is the "
                  "real output on this site (Tailwind/external-CSS signature).")

    font_labels = [f"{f['name']}{'*' if f.get('google') else ''}" for f in r.get("fonts", [])[:6]]
    print(f"\n  Fonts (*=Google Font): {font_labels}")
    print(f"  Type scale (px): {[t['px'] for t in r.get('type_scale', [])[:10]]}")
    print(f"  Logo candidates: {[(c['source'], c['url']) for c in r.get('logo_candidates', [])[:4]]}")
    if r.get("notes"):
        print(f"  Notes: {r['notes']}")


def _client_urls(limit: int) -> list[str]:
    from db.supabase_client import get_supabase

    rows = (
        get_supabase().table("clients").select("name, website_url")
        .neq("website_url", "").order("created_at", desc=True).limit(limit).execute().data
        or []
    )
    return [r["website_url"].strip() for r in rows if (r.get("website_url") or "").strip()]


def main() -> int:
    from services import brand_guide_spike as spike

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

    reports = asyncio.run(spike.run_spike(urls))
    for r in reports:
        _print_report(r)

    summary = spike.summarize(reports)
    print("\n" + "#" * 78)
    print("# D4 GATE SUMMARY  (acceptance #1 — eyedropper comparison is the human call)")
    print("#" * 78)
    print(f"{'site':<40} {'cssColors':>9} {'srcPal':>7} {'merged':>7} {'snapped':>7} {'pixel':>6}")
    for s in summary["per_site"]:
        print(f"{(s['url'] or '')[:39]:<40} {s['css_colors']:>9} {s['palette_source']:>7} "
              f"{s['merged_colors']:>7} {s['snapped_to_css']:>7} {s['pixel_only']:>6}")
    print(f"\ncss_recovered_any={summary['css_recovered_any']}  "
          f"captured={summary['captured']}/{summary['sites']}")
    print(
        "Read: cssColors>0 across sites => the declared-hex refinement is real; "
        "\n      cssColors≈0 but sensible pixel swatches => pixel-sampled hex is the output "
        "(D4 still holds, CSS half just doesn't fire);"
        "\n      garbage pixel swatches AND no CSS colours => reopen the ADR."
    )

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"reports": reports, "summary": summary}, fh, indent=2)
        print(f"\nJSON report → {args.json}")

    return 0 if summary["captured"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
