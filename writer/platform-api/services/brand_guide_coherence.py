"""Brand Guide Generator — Phase 2: the coherence check + WCAG contrast (pure).

Two deterministic pieces that feed synthesis (`brand_guide_synthesis`) and that
the LLM never computes (PRD §5.2 — "the LLM only names and proposes; it never
counts, measures, or reports a hex it wasn't handed"):

1. **WCAG contrast pairings** (`contrast_pairings`) — the accessible text-on-swatch
   recommendations the Color section's "accessible pairings" rows are built from.
   Contrast is math, so it is computed here in Python and handed to the LLM as a
   fact, never asked of it.

2. **The coherence check** (`build_coherence_flags`) — the audit payoff (PRD §4.3
   / §4.5). Because the deterministic census (`brand_guide_extract`, the measured
   tokens) and the vision vibe read (`brand_guide_vibe`, the felt aesthetic) are
   produced INDEPENDENTLY, we can cross-check them and flag where the intended
   feel and the executed detail diverge — "the aesthetic reads premium, but the
   palette has 11 near-duplicate grays → consolidate to 3." That is exactly the
   "here's where your brand is leaking" insight that makes the deliverable a sales
   asset, and it is only possible because vibe and tokens were read separately.

Everything here is pure — `dict`/list in (the stored `visual_census` /
`vibe_read` jsonb shapes), plain dicts out — so it unit-tests with no network and
runs over a stored guide row as readily as over a freshly-captured one. The LLM
later NARRATES these flags (grounded, never inventing a number); the deterministic
flags are the testable core.
"""

from __future__ import annotations

from typing import Any, Optional

# --------------------------------------------------------------------------
# Thresholds (the knobs behind each flag; kept module-level + named so a tuning
# change is one line and the tests can reference them).
# --------------------------------------------------------------------------
# HSL saturation (%) at/below which a swatch reads as a neutral/gray, not a hue.
NEUTRAL_SAT_MAX = 12
# Neutral swatches at/above this count = "too many near-duplicate grays".
COHERENCE_NEUTRAL_MIN = 4
# Total documented swatches at/above this = palette sprawl.
COHERENCE_PALETTE_MAX = 8
# Distinct type-scale steps at/above this = an unfocused scale.
COHERENCE_TYPE_STEPS_MAX = 9
# In-use typefaces (declared, count > 0) above this = too many fonts.
COHERENCE_FONT_MAX = 2
# Mood-axis reads that make a sprawl a *contradiction* of the intended feel.
PREMIUM_AXIS_MIN = 60   # budget_premium >= this → the brand means to read premium
MINIMAL_AXIS_MAX = 40   # minimal_maximal <= this → the brand means to read minimal

# WCAG 2.x contrast thresholds.
_AA_BODY = 4.5
_AA_LARGE = 3.0
_AAA_BODY = 7.0


# --------------------------------------------------------------------------
# WCAG contrast (pure math — PRD §5.2)
# --------------------------------------------------------------------------
def _srgb_channel(c: int) -> float:
    x = c / 255.0
    return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance of an sRGB colour (0.0 black … 1.0 white)."""
    r, g, b = rgb
    return 0.2126 * _srgb_channel(r) + 0.7152 * _srgb_channel(g) + 0.0722 * _srgb_channel(b)


def wcag_contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """WCAG contrast ratio between two colours, 1.0 … 21.0 (order-independent)."""
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = (la, lb) if la >= lb else (lb, la)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def contrast_level(ratio: float) -> str:
    """The strongest WCAG level a ratio clears: 'AAA' | 'AA' | 'AA Large' | 'fail'."""
    if ratio >= _AAA_BODY:
        return "AAA"
    if ratio >= _AA_BODY:
        return "AA"
    if ratio >= _AA_LARGE:
        return "AA Large"
    return "fail"


_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)


def _rgb_of(color: dict) -> Optional[tuple[int, int, int]]:
    rgb = color.get("rgb")
    if isinstance(rgb, (list, tuple)) and len(rgb) == 3:
        try:
            return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        except (TypeError, ValueError):
            return None
    return None


def contrast_pairings(colors: list[dict], *, limit: int = 6) -> list[dict]:
    """For the top `limit` documented swatches, the accessible text colour to put
    ON that swatch (PRD §6 Color: "accessible pairings (WCAG contrast)").

    Pure: reads the `visual_census` colour dicts (`hex`/`rgb`). For each swatch it
    picks white or black text — whichever contrasts more — and reports the ratio +
    the WCAG level it clears, so the guide can render "white text on #1a2b6d —
    12.6:1 (AAA)" as a fact. A swatch where NEITHER text colour clears AA body is
    flagged `passes_body=False` (a caution, still shown). Deterministic; the LLM
    never computes any of this.
    """
    out: list[dict] = []
    for color in colors[:limit]:
        rgb = _rgb_of(color)
        if rgb is None:
            continue
        on_white = wcag_contrast(rgb, _WHITE)
        on_black = wcag_contrast(rgb, _BLACK)
        if on_white >= on_black:
            text_hex, ratio = "#ffffff", on_white
        else:
            text_hex, ratio = "#000000", on_black
        level = contrast_level(ratio)
        out.append({
            "background": color.get("hex"),
            "text": text_hex,
            "ratio": ratio,
            "level": level,
            "passes_body": ratio >= _AA_BODY,
        })
    return out


# --------------------------------------------------------------------------
# Coherence check (deterministic cross-check of census vs vibe — PRD §4.3)
# --------------------------------------------------------------------------
def _neutral_count(colors: list[dict]) -> int:
    """How many documented swatches read as neutrals/grays (low saturation)."""
    n = 0
    for color in colors:
        hsl = color.get("hsl")
        if isinstance(hsl, (list, tuple)) and len(hsl) == 3:
            try:
                sat = int(hsl[1])
            except (TypeError, ValueError):
                continue
            if sat <= NEUTRAL_SAT_MAX:
                n += 1
    return n


def _in_use_font_count(fonts: list[dict]) -> int:
    """Typefaces actually declared in the captured CSS (count > 0). A Google-only
    font (declared via an external class we can't see, count == 0) is real but not
    evidence of *over*-use, so it doesn't count toward font sprawl."""
    return sum(1 for f in fonts if isinstance(f, dict) and (f.get("count") or 0) > 0)


def _axis(vibe_read: Any, key: str) -> Optional[int]:
    if not isinstance(vibe_read, dict):
        return None
    axes = vibe_read.get("mood_axes")
    if not isinstance(axes, dict):
        return None
    val = axes.get(key)
    return val if isinstance(val, int) else None


def _premium_or_minimal(vibe_read: Any) -> Optional[str]:
    """The intended-feel read that a sprawl would contradict: 'premium', 'minimal',
    or None when the vibe read is absent / says neither."""
    premium = _axis(vibe_read, "budget_premium")
    minimal = _axis(vibe_read, "minimal_maximal")
    if premium is not None and premium >= PREMIUM_AXIS_MIN:
        return "premium"
    if minimal is not None and minimal <= MINIMAL_AXIS_MAX:
        return "minimal"
    return None


def _flag(code: str, section: str, severity: str, title: str, detail: str, evidence: dict) -> dict:
    return {
        "code": code,
        "section": section,
        "severity": severity,     # 'gap' (leak to fix) | 'info' (worth noting)
        "title": title,
        "detail": detail,
        "evidence": evidence,
    }


def build_coherence_flags(census: Any, vibe_read: Any = None) -> list[dict]:
    """Cross-check the measured census against the felt vibe read → coherence flags.

    Pure. `census` is the `visual_census` dict (colors/fonts/type_scale…);
    `vibe_read` is the `vibe_read` dict (mood_axes/…) or None. Each flag names a
    concrete divergence between intended feel and executed detail, grounded in the
    real numbers, for synthesis to narrate (never invent). The sprawl flags fire
    on the measurement alone; the `vibe_execution_gap` is the audit headline — it
    fires only when a sprawl CONTRADICTS an explicit premium/minimal vibe read.

    Ordered gap-first, then by section, so the render leads with the leaks.
    """
    census = census if isinstance(census, dict) else {}
    colors = [c for c in (census.get("colors") or []) if isinstance(c, dict)]
    fonts = [f for f in (census.get("fonts") or []) if isinstance(f, dict)]
    type_scale = [t for t in (census.get("type_scale") or []) if isinstance(t, dict)]

    neutral_n = _neutral_count(colors)
    palette_n = len(colors)
    type_steps = len(type_scale)
    font_n = _in_use_font_count(fonts)
    feel = _premium_or_minimal(vibe_read)

    flags: list[dict] = []

    neutral_sprawl = neutral_n >= COHERENCE_NEUTRAL_MIN
    palette_sprawl = palette_n >= COHERENCE_PALETTE_MAX

    if neutral_sprawl:
        flags.append(_flag(
            "neutral_sprawl", "color", "gap",
            f"{neutral_n} near-duplicate neutrals in the palette",
            f"The captured palette carries {neutral_n} low-saturation grays/neutrals. "
            "A tight system needs about three (a near-black, a mid gray, a near-white) — "
            "consolidate the rest so the neutrals read as a deliberate scale, not drift.",
            {"neutral_count": neutral_n, "threshold": COHERENCE_NEUTRAL_MIN},
        ))
    if palette_sprawl:
        flags.append(_flag(
            "palette_sprawl", "color", "gap",
            f"{palette_n} distinct colours documented",
            f"{palette_n} colours dominate the page. A recognisable brand palette is "
            "usually one primary, one or two supporting hues, and a small neutral set — "
            "propose a consolidated system and mark anything beyond it as a substitution.",
            {"palette_count": palette_n, "threshold": COHERENCE_PALETTE_MAX},
        ))
    if type_steps >= COHERENCE_TYPE_STEPS_MAX:
        flags.append(_flag(
            "type_scale_sprawl", "typography", "gap",
            f"{type_steps} distinct type sizes in use",
            f"{type_steps} declared font sizes were measured. Tighten to a clear "
            "scale (H1→caption, ~6–7 steps) so hierarchy is legible and repeatable.",
            {"type_steps": type_steps, "threshold": COHERENCE_TYPE_STEPS_MAX},
        ))
    if font_n > COHERENCE_FONT_MAX:
        flags.append(_flag(
            "font_sprawl", "typography", "gap",
            f"{font_n} typefaces in use",
            f"{font_n} typefaces were declared in the captured CSS. A focused system "
            "pairs two (one display, one text) — recommend a primary/secondary pair "
            "and retire the rest.",
            {"font_count": font_n, "threshold": COHERENCE_FONT_MAX},
        ))

    # The audit headline: intended feel vs executed detail. Only fires when the
    # vibe read explicitly means premium/minimal AND the census shows a sprawl —
    # the divergence that makes the deliverable a sales asset.
    if feel is not None and (neutral_sprawl or palette_sprawl or type_steps >= COHERENCE_TYPE_STEPS_MAX):
        reasons: list[str] = []
        if neutral_sprawl:
            reasons.append(f"{neutral_n} near-duplicate neutrals")
        if palette_sprawl:
            reasons.append(f"{palette_n} distinct colours")
        if type_steps >= COHERENCE_TYPE_STEPS_MAX:
            reasons.append(f"{type_steps} type sizes")
        flags.append(_flag(
            "vibe_execution_gap", "aesthetic", "gap",
            f"The brand reads {feel}, but the execution is inconsistent",
            f"The homepage reads {feel}, yet the measured details tell a looser story "
            f"({', '.join(reasons)}). Closing that gap — a disciplined palette and type "
            f"scale — is what would make the {feel} intent land.",
            {"feel": feel, "reasons": reasons,
             "budget_premium": _axis(vibe_read, "budget_premium"),
             "minimal_maximal": _axis(vibe_read, "minimal_maximal")},
        ))

    order = {"gap": 0, "info": 1}
    flags.sort(key=lambda f: (order.get(f["severity"], 9), f["section"]))
    return flags
