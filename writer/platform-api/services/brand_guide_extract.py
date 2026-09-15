"""Brand Guide Generator — the deterministic visual-extraction core (Phase 0).

Turns a client site's scraped CSS + a screenshot's pixel-dominance table into a
**visual census**: the real palette (named-able swatches with Hex/RGB/HSL/CMYK
and a dominance share), the real typefaces + type scale, and ranked logo
candidates. The LLM never touches any of this — it later *names* and *proposes*
over the numbers this module measured, but it never counts, measures, or reports
a hex it wasn't handed (the suite's "the LLM never counts" page-spec discipline,
applied to pixels instead of words).

Two design rules make this module testable and cheap:

* **Pure + stdlib-only.** Everything here is `str`/list in, dataclass out — no
  network, no Pillow, no numpy. The *screenshot → pixel-count* step (Pillow
  quantization) and the *fetch* step (ScrapeOwl / DataForSEO) live in the
  capture layer and the D4 spike; this module consumes their already-extracted
  outputs (a list of ``(rgb, count)`` samples, a blob of scraped CSS). That is
  what lets the unit tests run with no external dependency and what lets the
  same census feed both the pixel path and an all-inline-CSS fixture.

* **Two-tier hex, pixel-primary (PRD §4.2 / D4 / ADR 2026-09-15).** Screenshot
  pixel dominance is the *primary* signal for **which colours dominate** (and by
  how much), because that is what a viewer actually sees. Scraped-CSS declared
  hex is a *refinement* for the reported **number**: when a dominant pixel colour
  matches a CSS declaration within tolerance, the swatch reports the exact
  declared hex (no JPEG/anti-alias drift on the number); otherwise it reports the
  pixel-sampled hex. When no pixels are supplied (a pure-CSS fixture, or a
  capture with no screenshot) the census falls back to clustering the CSS-declared
  colours by their own declaration frequency, so the module still produces a
  palette. Whether declared-hex-from-scraped-CSS actually recovers brand colours
  on templated/Tailwind/external-CSS stacks is the subject of the §10 Phase-0
  spike; this module is agnostic to which source wins — it records the source on
  every swatch.

The colour/font normalisation is a **salvage** of ``website_theme_precompile``'s
count-only census (~25 lines: the colour value regex, the length guard, the
``_norm_color`` collapse) into a new **weight-aware** census — the precompile
version is hard-wired to inline ``style="…"`` from a Claude-Design upload and has
no per-item weight seam, so it could not be reused as-is (ADR 2026-09-15).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

# --------------------------------------------------------------------------
# Salvaged normalisation (from website_theme_precompile) — value-matched so a
# shorthand like `border-bottom:1px solid #e3e9e6` still yields its colour.
# --------------------------------------------------------------------------
_COLOR_RE = re.compile(
    r"(#[0-9a-fA-F]{3,8}\b"
    r"|rgba?\([^)]*\)"
    r"|hsla?\([^)]*\))"
)
# oklch()/lab()/color() are deliberately NOT matched: converting them to RGB for
# clustering is lossy and rare on SMB sites; a colour we cannot place on the RGB
# cube cannot be near-dup clustered, so it is left out of the census rather than
# guessed at. (A future spike finding could add a converter.)
_LENGTH_RE = re.compile(r"^(-?\d+(?:\.\d+)?)(px|rem|em|%|vh|vw)$")
_STYLE_ATTR_RE = re.compile(r'\sstyle="([^"]*)"', re.I)
_STYLE_BLOCK_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
_FONT_HREF_RE = re.compile(r"fonts\.googleapis\.com/css2\?([^\"']+)")
_FAMILY_RE = re.compile(r"family=([^&:]+)")
# A `font-family` value that is not a real typeface name — a CSS custom-property
# reference (`var(--…)`, incl. Elementor's `var( --e-global-typography-… )` with
# spaces) or a Wix `wfont_<hash>` / bare hex-hash font ID. Any 16+ char hex run
# is an opaque asset hash, never a family name (real Wix aliases like
# `futura-lt-w01-light` have no such run and survive). Observed leaking on live
# sites in the Phase-0 D4 spike — dropped in the capture layer now.
_FONT_JUNK_RE = re.compile(r"^var\(|^wfont[_-]|[0-9a-f]{16,}", re.I)

# A near-transparent colour is page background bleed / an overlay, never a brand
# swatch — dropped before the census.
_MIN_ALPHA = 0.30
# rem/em → px at the CSS default root size, so a type scale declared in rem is
# comparable to one declared in px.
_REM_PX = 16.0


def _norm_color(value: str) -> str:
    """Lowercase, whitespace-collapsed, so one literal counts once."""
    return re.sub(r"\s+", " ", value.strip().lower())


# --------------------------------------------------------------------------
# Colour parsing + conversion (pure)
# --------------------------------------------------------------------------
RGB = tuple[int, int, int]


def parse_color(value: str) -> Optional[tuple[RGB, float]]:
    """A CSS colour literal → ``((r, g, b), alpha)``, or None when unparseable.

    Handles ``#rgb`` / ``#rgba`` / ``#rrggbb`` / ``#rrggbbaa``, ``rgb()`` /
    ``rgba()`` (0–255 or ``%``), and ``hsl()`` / ``hsla()``. Alpha defaults to
    ``1.0``. oklch/lab/named colours return None (see ``_COLOR_RE``).
    """
    if not value:
        return None
    v = _norm_color(value)
    if v.startswith("#"):
        return _parse_hex(v)
    if v.startswith("rgb"):
        return _parse_rgb_func(v)
    if v.startswith("hsl"):
        return _parse_hsl_func(v)
    return None


def _parse_hex(v: str) -> Optional[tuple[RGB, float]]:
    h = v.lstrip("#")
    if len(h) in (3, 4):  # shorthand — each nibble doubled
        h = "".join(c * 2 for c in h)
    if len(h) not in (6, 8):
        return None
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None
    alpha = int(h[6:8], 16) / 255.0 if len(h) == 8 else 1.0
    return (r, g, b), alpha


def _parse_channel(token: str) -> Optional[int]:
    token = token.strip()
    try:
        if token.endswith("%"):
            return _clamp8(round(float(token[:-1]) / 100.0 * 255))
        return _clamp8(round(float(token)))
    except ValueError:
        return None


def _parse_rgb_func(v: str) -> Optional[tuple[RGB, float]]:
    inner = v[v.find("(") + 1 : v.rfind(")")]
    # Tolerate both comma and modern space/slash syntax: rgb(12 34 56 / 50%).
    parts = re.split(r"[,\s/]+", inner.strip())
    parts = [p for p in parts if p]
    if len(parts) < 3:
        return None
    chans = [_parse_channel(p) for p in parts[:3]]
    if any(c is None for c in chans):
        return None
    alpha = _parse_alpha(parts[3]) if len(parts) >= 4 else 1.0
    return (chans[0], chans[1], chans[2]), alpha


def _parse_hsl_func(v: str) -> Optional[tuple[RGB, float]]:
    inner = v[v.find("(") + 1 : v.rfind(")")]
    parts = re.split(r"[,\s/]+", inner.strip())
    parts = [p for p in parts if p]
    if len(parts) < 3:
        return None
    try:
        h = float(parts[0].replace("deg", "")) % 360
        s = float(parts[1].rstrip("%")) / 100.0
        light = float(parts[2].rstrip("%")) / 100.0
    except ValueError:
        return None
    alpha = _parse_alpha(parts[3]) if len(parts) >= 4 else 1.0
    return _hsl_to_rgb(h, s, light), alpha


def _parse_alpha(token: str) -> float:
    token = token.strip()
    try:
        if token.endswith("%"):
            return max(0.0, min(1.0, float(token[:-1]) / 100.0))
        return max(0.0, min(1.0, float(token)))
    except ValueError:
        return 1.0


def _clamp8(n: int) -> int:
    return max(0, min(255, n))


def _hsl_to_rgb(h: float, s: float, light: float) -> RGB:
    c = (1 - abs(2 * light - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = light - c / 2
    if h < 60:
        rp, gp, bp = c, x, 0.0
    elif h < 120:
        rp, gp, bp = x, c, 0.0
    elif h < 180:
        rp, gp, bp = 0.0, c, x
    elif h < 240:
        rp, gp, bp = 0.0, x, c
    elif h < 300:
        rp, gp, bp = x, 0.0, c
    else:
        rp, gp, bp = c, 0.0, x
    return (_clamp8(round((rp + m) * 255)), _clamp8(round((gp + m) * 255)), _clamp8(round((bp + m) * 255)))


def rgb_to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(_clamp8(c) for c in rgb))


def rgb_to_hsl(rgb: RGB) -> tuple[int, int, int]:
    r, g, b = (c / 255.0 for c in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    light = (mx + mn) / 2
    if mx == mn:
        h = s = 0.0
    else:
        d = mx - mn
        s = d / (2 - mx - mn) if light > 0.5 else d / (mx + mn)
        if mx == r:
            h = (g - b) / d + (6 if g < b else 0)
        elif mx == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        h /= 6
    return (round(h * 360), round(s * 100), round(light * 100))


def rgb_to_cmyk(rgb: RGB) -> tuple[int, int, int, int]:
    r, g, b = (c / 255.0 for c in rgb)
    k = 1 - max(r, g, b)
    if k >= 1.0:  # pure black — avoid divide-by-zero
        return (0, 0, 0, 100)
    c = (1 - r - k) / (1 - k)
    m = (1 - g - k) / (1 - k)
    y = (1 - b - k) / (1 - k)
    return (round(c * 100), round(m * 100), round(y * 100), round(k * 100))


def color_distance(a: RGB, b: RGB) -> float:
    """Plain Euclidean distance on the RGB cube (0 … ~441.7)."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


# Two colours within this RGB distance are "the same" for clustering — the knob
# behind "11 near-duplicate grays → consolidate to 3". ~24 keeps genuinely
# distinct brand hues apart while folding anti-alias / shade jitter.
DEFAULT_CLUSTER_TOLERANCE = 24.0
# Below this share of total weight a colour is incidental (a stray icon, a
# gradient edge) — kept out of the documented palette.
DEFAULT_MIN_SHARE = 0.005
# CSS-declared hex snaps onto a pixel swatch when it is at least this close —
# tighter than the cluster tolerance so a *different* declared colour can't
# hijack the reported number.
CSS_SNAP_TOLERANCE = 16.0


# --------------------------------------------------------------------------
# Data types (serialisable — these are the `visual_census` jsonb shape)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Swatch:
    """One clustered brand colour."""

    hex: str
    rgb: RGB
    hsl: tuple[int, int, int]
    cmyk: tuple[int, int, int, int]
    share: float                       # fraction of total sampled weight (0–1)
    source: str                        # 'pixel' | 'css' | 'both'
    member_count: int = 1              # how many near-dups folded into this one
    css_hex: Optional[str] = None      # exact declared hex when snapped, else None

    def as_dict(self) -> dict:
        return {
            "hex": self.hex,
            "rgb": list(self.rgb),
            "hsl": list(self.hsl),
            "cmyk": list(self.cmyk),
            "share": round(self.share, 4),
            "source": self.source,
            "member_count": self.member_count,
            "css_hex": self.css_hex,
        }


@dataclass(frozen=True)
class TypeStep:
    px: float
    count: int

    def as_dict(self) -> dict:
        return {"px": self.px, "count": self.count}


@dataclass(frozen=True)
class FontFamily:
    name: str
    count: int
    google: bool = False               # cross-referenced against a Google Fonts href

    def as_dict(self) -> dict:
        return {"name": self.name, "count": self.count, "google": self.google}


@dataclass(frozen=True)
class LogoCandidate:
    url: str
    source: str                        # 'og_image' | 'img_logo' | 'header_link' | 'favicon'
    score: int
    note: str = ""

    def as_dict(self) -> dict:
        return {"url": self.url, "source": self.source, "score": self.score, "note": self.note}


@dataclass
class VisualCensus:
    """Everything the deterministic pass measures from one site's capture."""

    colors: list[Swatch] = field(default_factory=list)
    fonts: list[FontFamily] = field(default_factory=list)
    type_scale: list[TypeStep] = field(default_factory=list)
    font_weights: list[tuple[str, int]] = field(default_factory=list)
    radii: list[tuple[str, int]] = field(default_factory=list)
    spacing: list[tuple[str, int]] = field(default_factory=list)
    logo_candidates: list[LogoCandidate] = field(default_factory=list)
    # Honest provenance so the guide's methodology note and the spike can report
    # what the palette actually came from.
    palette_source: str = "none"       # 'pixel' | 'css' | 'none'
    notes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.colors or self.fonts or self.type_scale)

    def as_dict(self) -> dict:
        return {
            "colors": [c.as_dict() for c in self.colors],
            "fonts": [f.as_dict() for f in self.fonts],
            "type_scale": [t.as_dict() for t in self.type_scale],
            "font_weights": [list(w) for w in self.font_weights],
            "radii": [list(r) for r in self.radii],
            "spacing": [list(s) for s in self.spacing],
            "logo_candidates": [c.as_dict() for c in self.logo_candidates],
            "palette_source": self.palette_source,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------
# CSS declaration harvesting (pure — inline styles + <style> blocks)
# --------------------------------------------------------------------------
def css_declarations(html: str) -> list[tuple[str, str]]:
    """Every ``prop: value`` from inline ``style="…"`` attributes and ``<style>``
    blocks in scraped HTML.

    ⚠️ ScrapeOwl returns rendered DOM markup, **not** inlined external
    stylesheets — colours defined in linked CSS, ``var(--x)`` custom properties,
    or utility classes (Tailwind) will not surface here. That gap is exactly why
    the census treats screenshot pixels as the primary signal and CSS hex as a
    refinement (PRD §4.2). Rules/selectors are ignored; only declarations matter.
    """
    out: list[tuple[str, str]] = []
    for attr in _STYLE_ATTR_RE.finditer(html or ""):
        out.extend(_split_decls(attr.group(1)))
    for block in _STYLE_BLOCK_RE.finditer(html or ""):
        for rule in re.finditer(r"\{([^{}]*)\}", block.group(1)):
            out.extend(_split_decls(rule.group(1)))
    return out


def _split_decls(chunk: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for piece in (chunk or "").split(";"):
        if ":" not in piece:
            continue
        prop, _, value = piece.partition(":")
        prop, value = prop.strip().lower(), value.strip()
        if prop and value:
            out.append((prop, value))
    return out


def _css_colors(declarations: Iterable[tuple[str, str]]) -> Counter:
    """Declaration-frequency table of parseable CSS colours, keyed by RGB.

    A `var(--x)` value contributes nothing (it doesn't match `_COLOR_RE`) — the
    known limitation the pixel signal covers for.
    """
    counts: Counter = Counter()
    for _prop, value in declarations:
        for literal in _COLOR_RE.findall(value):
            parsed = parse_color(literal)
            if parsed is None:
                continue
            rgb, alpha = parsed
            if alpha < _MIN_ALPHA:
                continue
            counts[rgb] += 1
    return counts


# --------------------------------------------------------------------------
# Colour census — clustering + the two-tier hex merge
# --------------------------------------------------------------------------
def cluster_colors(
    weighted: Iterable[tuple[RGB, float]], tolerance: float = DEFAULT_CLUSTER_TOLERANCE
) -> list[Swatch]:
    """Greedy near-duplicate clustering, heaviest-first.

    Colours arrive as ``(rgb, weight)`` where weight is a pixel count or a CSS
    declaration count. The heaviest unclustered colour becomes a cluster's
    representative (a *real observed* colour, never an averaged one — so the
    reported hex is something that actually appears), absorbing every colour
    within ``tolerance``; the cluster's weight is the sum. Representatives are
    returned as ``Swatch`` with a ``share`` of total weight, sorted by share
    descending. ``source``/``css_hex`` are filled by the caller.
    """
    items = sorted(
        ((rgb, float(w)) for rgb, w in weighted if w > 0),
        key=lambda t: t[1],
        reverse=True,
    )
    total = sum(w for _rgb, w in items)
    if total <= 0:
        return []
    used = [False] * len(items)
    swatches: list[Swatch] = []
    for i, (rep_rgb, rep_w) in enumerate(items):
        if used[i]:
            continue
        used[i] = True
        weight = rep_w
        members = 1
        for j in range(i + 1, len(items)):
            if used[j]:
                continue
            if color_distance(rep_rgb, items[j][0]) <= tolerance:
                used[j] = True
                weight += items[j][1]
                members += 1
        swatches.append(
            Swatch(
                hex=rgb_to_hex(rep_rgb),
                rgb=rep_rgb,
                hsl=rgb_to_hsl(rep_rgb),
                cmyk=rgb_to_cmyk(rep_rgb),
                share=weight / total,
                source="pixel",
                member_count=members,
            )
        )
    swatches.sort(key=lambda s: s.share, reverse=True)
    return swatches


def build_color_census(
    *,
    pixel_counts: Optional[Iterable[tuple[RGB, int]]] = None,
    css_declarations_list: Optional[Iterable[tuple[str, str]]] = None,
    tolerance: float = DEFAULT_CLUSTER_TOLERANCE,
    min_share: float = DEFAULT_MIN_SHARE,
    snap_tolerance: float = CSS_SNAP_TOLERANCE,
) -> tuple[list[Swatch], str]:
    """The palette + which source produced it (``'pixel'`` | ``'css'`` | ``'none'``).

    **Pixel-primary two-tier (PRD §4.2):**
    1. Cluster the screenshot pixel counts → the dominance-ranked palette.
    2. Parse the scraped CSS's declared colours.
    3. For each pixel swatch, snap its reported hex to the nearest declared colour
       within ``snap_tolerance`` (``source='both'``, ``css_hex`` recorded); a
       swatch with no CSS match keeps its pixel-sampled hex (``source='pixel'``).
    4. Drop swatches below ``min_share``.

    **CSS-only fallback:** with no pixel counts, cluster the CSS-declared colours
    by declaration frequency instead (``source='css'``) so a capture without a
    usable screenshot — or an all-inline-CSS fixture — still yields a palette.
    """
    css_counter = _css_colors(css_declarations_list or [])
    pixels = [(rgb, int(c)) for rgb, c in (pixel_counts or []) if c > 0]

    if pixels:
        swatches = cluster_colors(pixels, tolerance=tolerance)
        declared = list(css_counter.keys())
        merged: list[Swatch] = []
        for sw in swatches:
            if sw.share < min_share:
                continue
            match = _nearest(sw.rgb, declared, snap_tolerance)
            if match is not None:
                exact = rgb_to_hex(match)
                merged.append(
                    Swatch(
                        hex=exact,
                        rgb=match,
                        hsl=rgb_to_hsl(match),
                        cmyk=rgb_to_cmyk(match),
                        share=sw.share,
                        source="both",
                        member_count=sw.member_count,
                        css_hex=exact,
                    )
                )
            else:
                merged.append(sw)
        return merged, "pixel"

    if css_counter:
        swatches = cluster_colors(
            ((rgb, count) for rgb, count in css_counter.items()), tolerance=tolerance
        )
        out = [
            Swatch(
                hex=sw.hex,
                rgb=sw.rgb,
                hsl=sw.hsl,
                cmyk=sw.cmyk,
                share=sw.share,
                source="css",
                member_count=sw.member_count,
                css_hex=sw.hex,
            )
            for sw in swatches
            if sw.share >= min_share
        ]
        return out, "css"

    return [], "none"


def _nearest(target: RGB, candidates: list[RGB], tolerance: float) -> Optional[RGB]:
    best: Optional[RGB] = None
    best_d = tolerance
    for c in candidates:
        d = color_distance(target, c)
        if d <= best_d:
            best_d = d
            best = c
    return best


# --------------------------------------------------------------------------
# Type scale, fonts, weights/radii/spacing (pure, from CSS declarations)
# --------------------------------------------------------------------------
def _to_px(value: str) -> Optional[float]:
    m = _LENGTH_RE.match(value.strip().lower())
    if not m:
        return None
    num, unit = float(m.group(1)), m.group(2)
    if unit == "px":
        return num
    if unit in ("rem", "em"):
        return round(num * _REM_PX, 2)
    return None  # %, vh, vw are not type-scale steps


def derive_type_scale(
    declarations: Iterable[tuple[str, str]], round_to: float = 0.5
) -> list[TypeStep]:
    """Distinct declared ``font-size`` steps (px, rem/em normalised to px),
    frequency-weighted, largest → smallest.

    Declared, not cascade-computed — sufficient for the garnish layer, and honest
    about it. Sizes are snapped to the nearest ``round_to`` px so 15.98px and
    16px count as one step.
    """
    counts: Counter = Counter()
    for prop, value in declarations:
        if prop != "font-size":
            continue
        px = _to_px(value)
        if px is None or px <= 0:
            continue
        snapped = round(px / round_to) * round_to
        counts[snapped] += 1
    steps = [TypeStep(px=px, count=c) for px, c in counts.items()]
    steps.sort(key=lambda s: s.px, reverse=True)
    return steps


def _first_family(stack: str) -> Optional[str]:
    """The first (preferred) family in a ``font-family`` stack, unquoted.

    Drops values that are not a real typeface name: CSS generic fallbacks,
    ``var(--…)`` custom-property references (Elementor writes every family as a
    ``var(--e-global-typography-…-font-family)``), and Wix ``wfont_<hash>`` /
    bare-hash font IDs. Both leak categories were observed on real client sites in
    the Phase-0 D4 spike (FreightOptics → ``var(--ui)``/``var(--host)``;
    Sealbeach CoLabs → ``wfont_3f9260_763c…``), where they otherwise ranked
    *above* the real families. Genuine Wix family aliases (``futura-lt-w01-light``,
    ``proxima-n-w01-reg``) are kept — only the opaque hash IDs are dropped.
    """
    first = stack.split(",")[0].strip().strip("'\"").strip()
    if not first:
        return None
    low = first.lower()
    # Generic fallbacks are not a brand typeface.
    if low in {"inherit", "initial", "unset", "sans-serif", "serif", "monospace", "cursive", "fantasy", "system-ui"}:
        return None
    if _FONT_JUNK_RE.search(low):
        return None
    return first


def google_font_families(html: str) -> list[str]:
    """Canonical family names from ``fonts.googleapis.com`` hrefs in the HTML."""
    out: list[str] = []
    for href in _FONT_HREF_RE.finditer(html or ""):
        for fam in _FAMILY_RE.finditer(href.group(1)):
            name = fam.group(1).replace("+", " ").strip()
            if name and name not in out:
                out.append(name)
    return out


def rank_font_families(
    declarations: Iterable[tuple[str, str]], google_families: Optional[Iterable[str]] = None
) -> list[FontFamily]:
    """Preferred families across all ``font-family`` declarations, frequency-ranked.

    A family that also appears in a Google Fonts href is flagged ``google=True``
    (canonical name + it's self-hostable), which is the reliable signal for the
    typography section's fallback stacks.
    """
    counts: Counter = Counter()
    for prop, value in declarations:
        if prop != "font-family":
            continue
        fam = _first_family(value)
        if fam:
            counts[fam] += 1
    google_set = {g.strip().lower() for g in (google_families or [])}
    ranked = [
        FontFamily(name=name, count=c, google=name.lower() in google_set)
        for name, c in counts.most_common()
    ]
    # A Google family with zero inline declarations (declared only via a class in
    # an external sheet we can't see) is still a real brand font — surface it.
    seen = {f.name.lower() for f in ranked}
    for g in (google_families or []):
        if g.strip().lower() not in seen:
            ranked.append(FontFamily(name=g.strip(), count=0, google=True))
            seen.add(g.strip().lower())
    return ranked


def _freq_table(declarations: Iterable[tuple[str, str]], props: set[str], *, lengths: bool = False) -> list[tuple[str, int]]:
    counts: Counter = Counter()
    for prop, value in declarations:
        if prop not in props and not any(prop.startswith(p) for p in props):
            continue
        if lengths:
            for token in value.split():
                if _LENGTH_RE.match(token.strip().lower()) and token not in {"0", "0px"}:
                    counts[token] += 1
        else:
            counts[value] += 1
    return counts.most_common()


def font_weights(declarations: Iterable[tuple[str, str]]) -> list[tuple[str, int]]:
    return _freq_table(declarations, {"font-weight"})


def radii(declarations: Iterable[tuple[str, str]]) -> list[tuple[str, int]]:
    return _freq_table(declarations, {"border-radius"})


def spacing(declarations: Iterable[tuple[str, str]]) -> list[tuple[str, int]]:
    return _freq_table(declarations, {"gap", "row-gap", "column-gap", "padding", "margin"}, lengths=True)


# --------------------------------------------------------------------------
# Logo candidates (pure — regex over scraped HTML, ranked)
# --------------------------------------------------------------------------
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', re.I
)
_OG_IMAGE_REV_RE = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', re.I
)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
_ATTR_RE = re.compile(r'(\w[\w-]*)\s*=\s*["\']([^"\']*)["\']', re.I)
_ICON_LINK_RE = re.compile(
    r'<link\b[^>]*rel=["\']([^"\']*icon[^"\']*)["\'][^>]*>', re.I
)
_LOGO_HINT_RE = re.compile(r"logo|brand|wordmark", re.I)
# Third-party asset hosts a "logo"-hinted image can live on that are NEVER the
# client's brand mark: cookie-consent / privacy banners, analytics/tag managers,
# review widgets, avatars. Observed on a live spike site (UMH → a
# cdn-cookieyes.com "poweredbtcky.svg" out-ranked the real UMH header logo). A
# candidate on one of these hosts is heavily down-ranked (not dropped — a host
# match is a strong hint, not proof), so it can never be the top suggestion but
# is still visible. Wix/WordPress asset CDNs (wixstatic, wp-content, parastorage)
# are deliberately NOT here — that is where a client's OWN logo lives.
_THIRD_PARTY_ASSET_HOST_RE = re.compile(
    r"(cookieyes|cookiebot|cookie-?script|onetrust|osano|termly|iubenda|usercentrics|"
    r"trustpilot|trustindex|elfsight|powr\.io|googletagmanager|google-analytics|"
    r"googleadservices|doubleclick|gravatar\.com)",
    re.I,
)
# URL/path hints that a "logo"-hinted image is someone else's mark or a chrome
# badge, not the brand: a customer/partner/client logo wall, a social-share card,
# an "as seen in" / award / payment / powered-by badge. Down-ranked below the
# real brand logo (FreightOptics → `freightoptics-customer-logo-*` + a
# `social_sharing_badge` og:image both out-ranked the real site logo in the spike).
_NON_BRAND_LOGO_HINT_RE = re.compile(
    r"customer[-_]?logo|partner[-_]?logo|client[-_]?logo|/clients?[-_/]|"
    r"social[-_]?shar|badge|award|payment|powered[-_]?b|as[-_]?seen|trust[-_]?bad|guarantee",
    re.I,
)
# Sinks a third-party-host candidate below every plausible real one; a non-brand
# hint just demotes within the real set (e.g. a customer logo below the site logo).
_THIRD_PARTY_LOGO_PENALTY = 1000
_NON_BRAND_LOGO_PENALTY = 60


def _resolve_url(candidate: str, base_url: str) -> str:
    if not candidate:
        return candidate
    c = candidate.strip()
    if c.startswith(("http://", "https://", "data:")):
        return c
    if c.startswith("//"):
        return "https:" + c
    if not base_url:
        return c
    base = base_url.rstrip("/")
    if c.startswith("/"):
        # strip base path down to origin
        m = re.match(r"(https?://[^/]+)", base)
        origin = m.group(1) if m else base
        return origin + c
    return base + "/" + c


def logo_candidates_from_html(html: str, base_url: str = "") -> list[LogoCandidate]:
    """Ranked logo candidates from scraped HTML (regex, no bs4).

    Ranking (highest first) mirrors PRD §4.2: an ``og:image`` and a ``logo``-hinted
    ``<img>`` in the first slice of the DOM (the header) are the strongest signals,
    then any ``logo``-hinted image, then a favicon. URLs are resolved against
    ``base_url`` where possible. Deduped by resolved URL, best score kept.
    """
    text = html or ""
    header_zone = len(text) // 4 or len(text)  # first quarter ≈ header/nav
    scored: dict[str, LogoCandidate] = {}

    def add(url: str, source: str, score: int, note: str = "") -> None:
        resolved = _resolve_url(url, base_url)
        if not resolved:
            return
        # Down-rank chrome that isn't the client's brand mark (finding 2 of the
        # Phase-0 spike). A third-party host (consent banner / analytics) sinks
        # below every real candidate; a non-brand hint (customer/partner logo,
        # social-share badge) demotes it within the real set.
        if _THIRD_PARTY_ASSET_HOST_RE.search(resolved):
            score -= _THIRD_PARTY_LOGO_PENALTY
            note = (note + " · third-party host, down-ranked").strip(" ·")
        elif _NON_BRAND_LOGO_HINT_RE.search(resolved):
            score -= _NON_BRAND_LOGO_PENALTY
            note = (note + " · non-brand hint, down-ranked").strip(" ·")
        prev = scored.get(resolved)
        if prev is None or score > prev.score:
            scored[resolved] = LogoCandidate(url=resolved, source=source, score=score, note=note)

    for m in _OG_IMAGE_RE.finditer(text):
        add(m.group(1), "og_image", 100, "og:image")
    for m in _OG_IMAGE_REV_RE.finditer(text):
        add(m.group(1), "og_image", 100, "og:image")

    for m in _IMG_RE.finditer(text):
        attrs = {k.lower(): v for k, v in _ATTR_RE.findall(m.group(0))}
        src = attrs.get("src") or attrs.get("data-src") or ""
        if not src:
            continue
        haystack = " ".join(
            attrs.get(k, "") for k in ("src", "alt", "class", "id", "title")
        )
        in_header = m.start() < header_zone
        if _LOGO_HINT_RE.search(haystack):
            add(src, "img_logo", 90 if in_header else 70, "logo-hinted <img>")
        elif in_header:
            add(src, "header_link", 40, "first header image")

    for m in _ICON_LINK_RE.finditer(text):
        href = dict((k.lower(), v) for k, v in _ATTR_RE.findall(m.group(0))).get("href", "")
        if href:
            add(href, "favicon", 20, m.group(1).strip())

    return sorted(scored.values(), key=lambda c: c.score, reverse=True)


# --------------------------------------------------------------------------
# Key-page discovery (pure — nav links off the homepage, PRD §4.1)
# --------------------------------------------------------------------------
_ANCHOR_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
_HREF_ATTR_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.I)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_ASSET_EXT_RE = re.compile(r"\.(?:pdf|jpe?g|png|webp|gif|svg|zip|docx?|xlsx?|mp4|mp3)(?:$|\?)", re.I)
# The two key-page kinds captured beyond the homepage: a commercial page
# (product/service — brand voice + imagery in action) and an identity page
# (about/contact — the brand's own framing). Ordered by URL/anchor signal.
_SERVICE_PAGE_RE = re.compile(
    r"service|product|solution|what-?we-?do|shop|store|menu|treatment|pricing|feature|offer",
    re.I,
)
_ABOUT_PAGE_RE = re.compile(
    r"about|our-?story|our-?team|company|who-?we-?are|contact|meet-?", re.I
)


def _same_host(url: str, base_url: str) -> bool:
    def host(u: str) -> str:
        m = re.match(r"https?://([^/]+)", u.lower())
        return (m.group(1) if m else "").lstrip("www.")

    b = host(base_url)
    return not b or host(url) == b


def discover_key_pages(html: str, base_url: str, *, limit: int = 2) -> list[str]:
    """Up to ``limit`` auto-discovered key pages off the homepage's nav (PRD §4.1).

    Deterministic: scan the homepage's ``<a href>`` links (nav links appear early
    in the DOM), resolve same-host absolute URLs, and pick **one commercial page**
    (product/service) + **one identity page** (about/contact) — the +2 pages the
    capture layer grabs for logo candidates / imagery variety / a consistency
    check (never the palette census, §4.1). Earliest-in-document wins within a
    kind (nav order). The homepage, fragments, ``mailto:``/``tel:``, asset files,
    and off-host links are excluded. Returns [] when nothing qualifies — the guide
    still generates from the homepage alone (§5.4).
    """
    text = html or ""
    origin = ""
    m = re.match(r"(https?://[^/]+)", (base_url or "").lower())
    if m:
        origin = m.group(1)

    best: dict[str, tuple[int, str]] = {}  # kind -> (doc_position, url)
    for order, am in enumerate(_ANCHOR_RE.finditer(text)):
        hm = _HREF_ATTR_RE.search(am.group(1))
        if not hm:
            continue
        href = hm.group(1).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        resolved = _resolve_url(href, base_url)
        low = resolved.lower()
        if not low.startswith(("http://", "https://")):
            continue
        if _ASSET_EXT_RE.search(low) or not _same_host(low, base_url):
            continue
        # Exclude the homepage itself (origin, origin/, or a bare path of "/").
        path = low[len(origin):] if origin and low.startswith(origin) else low
        if path in ("", "/") or low.rstrip("/") == origin.rstrip("/"):
            continue
        anchor_text = _TAG_STRIP_RE.sub(" ", am.group(2))
        haystack = f"{path} {anchor_text}"
        kind = None
        if _SERVICE_PAGE_RE.search(haystack):
            kind = "service"
        elif _ABOUT_PAGE_RE.search(haystack):
            kind = "about"
        if kind is None:
            continue
        clean = resolved.split("#")[0]
        if kind not in best:  # first (earliest) match per kind wins
            best[kind] = (order, clean)

    ordered = [best[k][1] for k in ("service", "about") if k in best]
    # Dedup while preserving order (a link can match both kinds' pick to the same URL).
    seen: set[str] = set()
    out: list[str] = []
    for u in ordered:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:limit]


# --------------------------------------------------------------------------
# Top-level orchestration (pure) — the one call the capture layer makes
# --------------------------------------------------------------------------
def extract_visual_census(
    html: str,
    *,
    pixel_counts: Optional[Iterable[tuple[RGB, int]]] = None,
    base_url: str = "",
    tolerance: float = DEFAULT_CLUSTER_TOLERANCE,
    min_share: float = DEFAULT_MIN_SHARE,
) -> VisualCensus:
    """Scraped HTML (+ optional screenshot pixel counts) → the full visual census.

    Pure: no network, no Pillow. The capture layer supplies ``html`` (ScrapeOwl,
    ``render_js=True``) and ``pixel_counts`` (Pillow quantization over the
    DataForSEO screenshot); this assembles the deterministic census over them.
    Best-effort throughout — a missing input degrades that part of the census and
    adds a note, never raises.
    """
    decls = css_declarations(html)
    notes: list[str] = []

    colors, palette_source = build_color_census(
        pixel_counts=pixel_counts,
        css_declarations_list=decls,
        tolerance=tolerance,
        min_share=min_share,
    )
    if palette_source == "none":
        notes.append("No palette recovered — no screenshot pixels and no parseable CSS colours.")
    elif palette_source == "css":
        notes.append("Palette from CSS declarations only (no screenshot supplied); dominance is declaration frequency, not pixel area.")

    gfonts = google_font_families(html)
    fonts = rank_font_families(decls, gfonts)
    if not fonts:
        notes.append("No typefaces recovered from inline/embedded CSS (fonts may be set via external stylesheet or classes).")

    census = VisualCensus(
        colors=colors,
        fonts=fonts,
        type_scale=derive_type_scale(decls),
        font_weights=font_weights(decls),
        radii=radii(decls),
        spacing=spacing(decls),
        logo_candidates=logo_candidates_from_html(html, base_url),
        palette_source=palette_source,
        notes=notes,
    )
    return census
