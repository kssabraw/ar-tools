"""Brand Guide Generator — Phase 5: Applications / in-context mockups (PRD §3 §9 / §10).

Renders the guide's brand system *in use* — a website hero, a social post, a
business card, a letterhead, and a product label — as **self-contained HTML/CSS
blocks inside the same brand-guide PDF** (`brand_guide_render.build_guide_html`
drops the section in after Imagery). This is the deliberate, code-grounded reading
of the PRD's "reuse the Website-Builder theme render": the Website-Builder render
path (`website_theme` → `tokens.css` → a per-site GitHub repo → Cloudflare deploy →
a live Astro site) is a heavyweight, async, deploy-based pipeline that makes an LLM
call (role-naming) and produces a *live URL* — it cannot be embedded in a PDF
fragment and it would violate the render's core invariant. What we reuse is the
**token → page CONCEPT**: the guide already owns roled swatches + fonts + a type
scale + a tagline + worked voice examples + a logo, so the mockups are pure
assembly over that stored record, styled from the brand's own tokens.

Design rules, all inherited from the render module:
  * **Deterministic — the LLM is NEVER called here** (PRD §5.2). Every mockup is
    pure HTML/CSS assembly over `synthesized` + `visual_census` + the render
    context. No new copy is invented: headlines/taglines/CTAs come from the
    synthesized `voice_examples`/`tagline`/`boilerplate`; a CTA with no synthesized
    label falls back to the generic UI word "Learn more" (a button label, never a
    product/brand claim — §5.3). Contact lines use only the client's real
    name/website/phone/address (never a placeholder that reads as fact).
  * **Best-effort / degrade-never-fail** (PRD §5.4). With no usable palette the
    whole section is omitted (returns "") — like the render module's hero section
    when there's no screenshot. With a palette but a missing logo, a text wordmark
    stands in; a missing tagline/blurb simply drops that line.
  * **Profile-independent** (PRD §4.7). The only internal↔client delta is the
    coherence/audit treatment (§5 Aesthetic section); the mockups are identical in
    both profiles, so this takes no `profile` argument.

Fully inline-styled + self-contained so the section is unit-testable in isolation
(assert the resolved palette hexes + brand copy appear) without the render
module's `_CSS`. WCAG luminance/contrast reuse `brand_guide_coherence` (the suite's
contrast authority) so "readable text on this brand colour" is computed the same
way the Color section's accessible pairings are.
"""

from __future__ import annotations

import html as _html
import re
from typing import Optional

from services.brand_guide_coherence import relative_luminance, wcag_contrast

# ---------------------------------------------------------------------------
# Fallback tokens (only ever reached when the palette lacks a usable role)
# ---------------------------------------------------------------------------
_FALLBACK_PRIMARY = "#334155"
_INK = "#0f172a"
_PAPER = "#ffffff"
_MUTED = "#64748b"

_ROLE_PRIMARY = ("primary",)
_ROLE_ACCENT = ("accent",)
_ROLE_SECONDARY = ("secondary", "neutral")

# A colour usable as a filled BAND behind copy: neither near-white (invisible on
# paper) nor pure black. Mid-luminance window, matched to the census min-share cut.
_BAND_LUM_MIN = 0.03
_BAND_LUM_MAX = 0.86

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
def _esc(value: object) -> str:
    return _html.escape("" if value is None else str(value))


def _hex_rgb(value: object) -> Optional[tuple[int, int, int]]:
    """`#rgb` / `#rrggbb` → an (r,g,b) tuple, or None. Pure — no dependency on the
    extract module's fuller parser (mockups only ever receive hex swatches)."""
    if not isinstance(value, str):
        return None
    m = _HEX_RE.match(value.strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def _lum(rgb: tuple[int, int, int]) -> float:
    return relative_luminance(rgb)


def _readable_on(bg_hex: str) -> str:
    """White or near-black ink, whichever contrasts more with the background —
    the same white/black pick the Color section's WCAG pairings use."""
    rgb = _hex_rgb(bg_hex)
    if rgb is None:
        return _INK
    return "#ffffff" if wcag_contrast(rgb, (255, 255, 255)) >= wcag_contrast(rgb, (17, 17, 17)) else _INK


def _font_css(name: object, generic: str = "sans-serif") -> str:
    """A CSS font-family value naming the brand family with a generic fallback.

    WeasyPrint won't have the family installed, so it falls back to the generic —
    the mockups demonstrate LAYOUT + colour + hierarchy, and the type is labelled
    in the Typography section. Naming the family is honest and free."""
    name = str(name).strip() if name else ""
    if not name:
        return generic
    return f"'{_html.escape(name, quote=True)}', {generic}"


def _display_url(url: object) -> str:
    """A clean host+path for display (scheme + trailing slash stripped)."""
    s = str(url or "").strip()
    s = re.sub(r"^https?://", "", s, flags=re.I).rstrip("/")
    return s


# ---------------------------------------------------------------------------
# Palette resolution (pure over the stored record)
# ---------------------------------------------------------------------------
def _brand_entries(guide: dict) -> list[tuple[str, str]]:
    """Ordered `(hex, role)` brand colours from the record.

    Prefers the synthesized (named + roled) swatches, skipping any the operator
    flagged `not_brand`; falls back to the measured `visual_census` colours
    (dominance order, role unknown) so a guide whose synthesis failed but whose
    capture succeeded still gets mockups. Pure."""
    synth = guide.get("synthesized") if isinstance(guide.get("synthesized"), dict) else {}
    color = synth.get("color") if isinstance(synth.get("color"), dict) else {}
    swatches = [
        s for s in (color.get("swatches") or [])
        if isinstance(s, dict) and s.get("hex") and not s.get("not_brand")
    ]
    if swatches:
        return [(str(s["hex"]), str(s.get("role") or "").lower()) for s in swatches]
    census = guide.get("visual_census") if isinstance(guide.get("visual_census"), dict) else {}
    return [
        (str(c["hex"]), "")
        for c in (census.get("colors") or [])
        if isinstance(c, dict) and c.get("hex")
    ]


def resolve_palette(guide: dict) -> dict:
    """The mockup token map, or `{}` when there is no usable palette (→ the caller
    omits the whole Applications section). Pure over the stored record.

    Keys: `primary` (a mid-luminance brand colour for bands/buttons), `accent`,
    `secondary`, `ink` (dark body text), `paper` (light surface), `on_primary`
    (readable ink on `primary`), plus `heading_font` / `body_font` (named, may be
    empty). Role assignment prefers the LLM-assigned swatch roles and degrades to a
    luminance heuristic over the measured colours."""
    guide = guide if isinstance(guide, dict) else {}
    parsed: list[tuple[str, str, tuple[int, int, int]]] = []
    for hexval, role in _brand_entries(guide):
        rgb = _hex_rgb(hexval)
        if rgb is not None:
            parsed.append((hexval.strip().lower(), role, rgb))
    if not parsed:
        return {}

    def by_role(roles: tuple[str, ...]) -> Optional[tuple[str, tuple[int, int, int]]]:
        for hexval, role, rgb in parsed:
            if role in roles:
                return hexval, rgb
        return None

    usable = [(h, rgb) for h, _role, rgb in parsed if _BAND_LUM_MIN <= _lum(rgb) <= _BAND_LUM_MAX]

    # Primary: an explicit primary/accent role, else the first band-usable colour.
    primary = by_role(_ROLE_PRIMARY) or by_role(_ROLE_ACCENT)
    if primary is None:
        primary = usable[0] if usable else (parsed[0][0], parsed[0][2])
    primary_hex = primary[0]

    # Accent: an accent role, else a different usable colour, else primary.
    accent = by_role(_ROLE_ACCENT)
    if accent is None or accent[0] == primary_hex:
        accent = next(((h, rgb) for h, rgb in usable if h != primary_hex), primary)
    accent_hex = accent[0]

    # Secondary: a secondary/neutral role, else another usable colour, else primary.
    secondary = by_role(_ROLE_SECONDARY)
    if secondary is None or secondary[0] in {primary_hex, accent_hex}:
        secondary = next(
            ((h, rgb) for h, rgb in usable if h not in {primary_hex, accent_hex}), (primary_hex, primary[1])
        )
    secondary_hex = secondary[0]

    # Ink: the darkest measured colour if it's genuinely dark, else a safe slate.
    darkest_hex, darkest_rgb = min(((h, rgb) for h, _r, rgb in parsed), key=lambda t: _lum(t[1]))
    ink = darkest_hex if _lum(darkest_rgb) <= 0.4 else _INK

    # Paper: the lightest measured colour if it's near-white, else white.
    lightest_hex, lightest_rgb = max(((h, rgb) for h, _r, rgb in parsed), key=lambda t: _lum(t[1]))
    paper = lightest_hex if _lum(lightest_rgb) >= 0.9 else _PAPER

    census = guide.get("visual_census") if isinstance(guide.get("visual_census"), dict) else {}
    fonts = [f.get("name") for f in (census.get("fonts") or []) if isinstance(f, dict) and f.get("name")]
    heading_font = fonts[0] if fonts else ""
    body_font = (fonts[1] if len(fonts) > 1 else fonts[0]) if fonts else ""

    return {
        "primary": primary_hex,
        "accent": accent_hex,
        "secondary": secondary_hex,
        "ink": ink,
        "paper": paper,
        "on_primary": _readable_on(primary_hex),
        "heading_font": heading_font,
        "body_font": body_font,
    }


# ---------------------------------------------------------------------------
# Content resolution (pure — grounded copy only)
# ---------------------------------------------------------------------------
def _synth(guide: dict) -> dict:
    return guide.get("synthesized") if isinstance(guide.get("synthesized"), dict) else {}


def _voice(guide: dict, key: str) -> str:
    ve = _synth(guide).get("voice_examples")
    return str(ve.get(key)).strip() if isinstance(ve, dict) and ve.get(key) else ""


def _wordmark(logo_src: Optional[str], name: str, *, color: str, font: str, size: int) -> str:
    """A logo image when we have one, else the business name as a text wordmark in
    the brand's heading font/colour. Never a synthesized mark (§13 — no logo synthesis)."""
    if logo_src:
        return f'<img src="{_esc(logo_src)}" style="max-height:{size}px;max-width:70%;display:block"/>'
    label = _esc(name or "Your Brand")
    return (
        f'<div style="font-family:{font};font-weight:800;letter-spacing:-.01em;'
        f'font-size:{size}px;color:{_esc(color)}">{label}</div>'
    )


def _fig(caption: str, inner: str) -> str:
    """One mockup framed with its caption; kept off page breaks."""
    return (
        '<figure style="margin:0;page-break-inside:avoid">'
        f"{inner}"
        f'<figcaption style="font-size:9px;color:{_MUTED};text-transform:uppercase;'
        f'letter-spacing:.05em;margin-top:6px;text-align:center">{_esc(caption)}</figcaption>'
        "</figure>"
    )


# ---------------------------------------------------------------------------
# The five mockups (pure — fully inline-styled)
# ---------------------------------------------------------------------------
def _mock_hero(guide: dict, name: str, pal: dict, logo_src: Optional[str]) -> str:
    heading_font = _font_css(pal["heading_font"])
    body_font = _font_css(pal["body_font"])
    headline = _voice(guide, "headline") or _synth(guide).get("tagline") or name or "Your brand headline"
    subhead = _voice(guide, "product_blurb")
    cta = _voice(guide, "cta") or "Learn more"
    website = _display_url(guide.get("_website"))
    btn_bg = pal["accent"] if pal["accent"] != pal["primary"] else pal["paper"]
    btn_fg = _readable_on(btn_bg)

    chrome = (
        f'<div style="background:#e9edf2;padding:6px 10px;display:flex;align-items:center;gap:6px">'
        '<span style="width:7px;height:7px;border-radius:50%;background:#cbd5e1"></span>'
        '<span style="width:7px;height:7px;border-radius:50%;background:#cbd5e1"></span>'
        '<span style="width:7px;height:7px;border-radius:50%;background:#cbd5e1"></span>'
        f'<span style="flex:1;background:#fff;border-radius:4px;font-size:8px;color:#94a3b8;'
        f'padding:2px 8px;margin-left:6px">{_esc(website or "yourbrand.com")}</span></div>'
    )
    logo = _wordmark(logo_src, name, color=pal["on_primary"], font=heading_font, size=26)
    hero = (
        f'<div style="background:{_esc(pal["primary"])};color:{_esc(pal["on_primary"])};'
        f'padding:34px 28px;text-align:center">'
        f'<div style="display:flex;justify-content:center;margin-bottom:14px">{logo}</div>'
        f'<div style="font-family:{heading_font};font-size:23px;font-weight:800;line-height:1.15;'
        f'max-width:80%;margin:0 auto 8px">{_esc(headline)}</div>'
        + (f'<div style="font-family:{body_font};font-size:11px;opacity:.85;max-width:70%;'
           f'margin:0 auto 16px">{_esc(subhead)}</div>' if subhead else '<div style="height:10px"></div>')
        + f'<span style="display:inline-block;background:{_esc(btn_bg)};color:{_esc(btn_fg)};'
        f'font-family:{body_font};font-size:11px;font-weight:700;padding:9px 22px;border-radius:6px">'
        f'{_esc(cta)}</span></div>'
    )
    frame = (
        '<div style="border:1px solid #dde3ea;border-radius:8px;overflow:hidden;'
        'box-shadow:0 2px 8px rgba(15,23,42,.08)">' + chrome + hero + "</div>"
    )
    return _fig("Website hero", frame)


def _mock_social(guide: dict, name: str, pal: dict, logo_src: Optional[str]) -> str:
    heading_font = _font_css(pal["heading_font"])
    body_font = _font_css(pal["body_font"])
    line = _synth(guide).get("tagline") or _voice(guide, "headline") or name or "Your brand"
    logo = _wordmark(logo_src, name, color=pal["on_primary"], font=heading_font, size=18)
    inner = (
        f'<div style="width:230px;height:230px;background:{_esc(pal["primary"])};'
        f'color:{_esc(pal["on_primary"])};border-radius:8px;padding:22px;display:flex;'
        'flex-direction:column;box-shadow:0 2px 8px rgba(15,23,42,.08)">'
        f'<div>{logo}</div>'
        f'<div style="flex:1"></div>'
        f'<div style="width:34px;height:4px;background:{_esc(pal["accent"])};border-radius:2px;margin-bottom:10px"></div>'
        f'<div style="font-family:{heading_font};font-size:17px;font-weight:800;line-height:1.2">{_esc(line)}</div>'
        + (f'<div style="font-family:{body_font};font-size:9px;opacity:.8;margin-top:8px">'
           f'{_esc(_display_url(guide.get("_website")))}</div>' if guide.get("_website") else "")
        + "</div>"
    )
    return _fig("Social post", inner)


def _mock_business_card(guide: dict, name: str, pal: dict, logo_src: Optional[str]) -> str:
    heading_font = _font_css(pal["heading_font"])
    body_font = _font_css(pal["body_font"])
    tagline = _synth(guide).get("tagline") or ""
    contact = [
        _display_url(guide.get("_website")),
        str(guide.get("_phone") or "").strip(),
        str(guide.get("_address") or "").strip(),
    ]
    contact_html = "".join(
        f'<div style="font-family:{body_font};font-size:8px;color:{_esc(pal["ink"])};opacity:.7;'
        f'margin-top:2px">{_esc(c)}</div>'
        for c in contact if c
    )
    logo = _wordmark(logo_src, name, color=pal["primary"], font=heading_font, size=17)
    inner = (
        f'<div style="width:280px;height:160px;background:{_esc(pal["paper"])};border:1px solid #e2e8f0;'
        'border-radius:8px;overflow:hidden;display:flex;box-shadow:0 2px 8px rgba(15,23,42,.08)">'
        f'<div style="width:12px;background:{_esc(pal["primary"])}"></div>'
        '<div style="flex:1;padding:18px 20px;display:flex;flex-direction:column">'
        f'<div>{logo}</div>'
        + (f'<div style="font-family:{body_font};font-size:9px;color:{_esc(pal["ink"])};opacity:.65;'
           f'margin-top:4px">{_esc(tagline)}</div>' if tagline else "")
        + '<div style="flex:1"></div>'
        + (contact_html or f'<div style="font-family:{body_font};font-size:8px;color:{_MUTED}">'
           f'{_esc(name)}</div>')
        + "</div></div>"
    )
    return _fig("Business card", inner)


def _mock_letterhead(guide: dict, name: str, pal: dict, logo_src: Optional[str]) -> str:
    heading_font = _font_css(pal["heading_font"])
    body_font = _font_css(pal["body_font"])
    website = _display_url(guide.get("_website"))
    boiler = ""
    bp = _synth(guide).get("boilerplate")
    if isinstance(bp, dict) and bp.get("short"):
        boiler = str(bp["short"]).strip()
    logo = _wordmark(logo_src, name, color=pal["primary"], font=heading_font, size=16)

    if boiler:
        body = (
            f'<div style="font-family:{body_font};font-size:8px;color:{_esc(pal["ink"])};'
            f'opacity:.75;line-height:1.6">{_esc(boiler[:320])}</div>'
        )
    else:
        # No brand copy on file → clearly-inert placeholder rules (never invented copy).
        body = "".join(
            f'<div style="height:5px;background:#eef2f6;border-radius:2px;margin-bottom:7px;'
            f'width:{w}"></div>'
            for w in ("100%", "96%", "92%", "60%")
        )
    inner = (
        f'<div style="width:280px;height:360px;background:{_esc(pal["paper"])};border:1px solid #e2e8f0;'
        'border-radius:6px;padding:22px;display:flex;flex-direction:column;'
        'box-shadow:0 2px 8px rgba(15,23,42,.08)">'
        '<div style="display:flex;justify-content:space-between;align-items:flex-start">'
        f'<div>{logo}</div>'
        + (f'<div style="font-family:{body_font};font-size:7.5px;color:{_MUTED};text-align:right">'
           f'{_esc(website)}</div>' if website else "")
        + f'</div><div style="height:2px;background:{_esc(pal["primary"])};margin:12px 0 16px"></div>'
        + body
        + '<div style="flex:1"></div>'
        + f'<div style="border-top:1px solid #eef2f6;padding-top:8px;font-family:{body_font};'
        f'font-size:7px;color:{_MUTED};text-align:center">{_esc(name)}'
        + (f' · {_esc(website)}' if website else "") + "</div></div>"
    )
    return _fig("Letterhead", inner)


def _mock_label(guide: dict, name: str, pal: dict, logo_src: Optional[str]) -> str:
    heading_font = _font_css(pal["heading_font"])
    body_font = _font_css(pal["body_font"])
    descriptor = _synth(guide).get("tagline") or _voice(guide, "headline") or ""
    logo = _wordmark(logo_src, name, color=pal["on_primary"], font=heading_font, size=16)
    inner = (
        f'<div style="width:280px;height:170px;background:{_esc(pal["paper"])};border:1px solid #e2e8f0;'
        'border-radius:10px;overflow:hidden;display:flex;flex-direction:column;'
        'box-shadow:0 2px 8px rgba(15,23,42,.08)">'
        f'<div style="background:{_esc(pal["primary"])};color:{_esc(pal["on_primary"])};'
        'padding:16px 18px;text-align:center">'
        f'<div style="display:flex;justify-content:center">{logo}</div></div>'
        '<div style="flex:1;padding:14px 18px;text-align:center;display:flex;flex-direction:column;'
        'justify-content:center">'
        f'<div style="font-family:{heading_font};font-size:13px;font-weight:700;color:{_esc(pal["ink"])}">'
        f'{_esc(name or "Product")}</div>'
        + (f'<div style="font-family:{body_font};font-size:8px;color:{_esc(pal["ink"])};opacity:.65;'
           f'margin-top:5px">{_esc(descriptor)}</div>' if descriptor else "")
        + f'<div style="width:40px;height:3px;background:{_esc(pal["accent"])};border-radius:2px;'
        'margin:10px auto 0"></div>'
        + "</div></div>"
    )
    return _fig("Product label", inner)


# ---------------------------------------------------------------------------
# Section assembly
# ---------------------------------------------------------------------------
def build_applications_section(guide: dict, ctx: dict, *, logo_src: Optional[str] = None) -> str:
    """The Applications section HTML (PRD §3 §9), or `""` when there's no usable
    palette (degrade-never-fail — the section is simply omitted, like the render
    module's hero when there's no screenshot).

    Pure over the stored `guide` record + the render `ctx`; the LLM is never called
    (§5.2). `logo_src` is the pre-inlined logo data URI the render orchestrator
    already resolves for the rest of the PDF (a text wordmark stands in when None).
    Identical in both render profiles (§4.7)."""
    guide = guide if isinstance(guide, dict) else {}
    ctx = ctx if isinstance(ctx, dict) else {}
    pal = resolve_palette(guide)
    if not pal:
        return ""

    name = (ctx.get("name") or "").strip()
    # Thread the render context's identity/contact onto the guide dict under
    # private keys so the pure mockup builders read one object. (Not persisted —
    # this dict is the in-memory row the render passes in.)
    ctx_guide = dict(guide)
    ctx_guide["_website"] = ctx.get("website") or ""
    ctx_guide["_phone"] = ctx.get("phone") or ""
    ctx_guide["_address"] = ctx.get("address") or ""

    hero = _mock_hero(ctx_guide, name, pal, logo_src)
    grid_items = [
        _mock_social(ctx_guide, name, pal, logo_src),
        _mock_business_card(ctx_guide, name, pal, logo_src),
        _mock_letterhead(ctx_guide, name, pal, logo_src),
        _mock_label(ctx_guide, name, pal, logo_src),
    ]
    grid = (
        '<div style="display:flex;flex-wrap:wrap;gap:22px;justify-content:center;margin-top:20px">'
        + "".join(f'<div style="flex:0 0 auto">{item}</div>' for item in grid_items)
        + "</div>"
    )
    intro = (
        f'<p style="color:{_MUTED};margin:2px 0 4px">The brand system in use — assembled from your '
        "palette, type and voice. Mockups are illustrative layouts, not final artwork.</p>"
    )
    return (
        '<section class="apps" style="margin-bottom:22px">'
        "<h2>Applications</h2>"
        + intro
        + f'<div style="margin-top:12px">{hero}</div>'
        + grid
        + "</section>"
    )
