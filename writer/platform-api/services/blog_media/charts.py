"""Deterministic charts for the media pipeline (Phase 2).

Statistical charts are NEVER sent to an image model. The planner returns a chart
*specification* (type, values, exact source quotes); the app independently
validates every value against the real article text and renders a restrained
editorial SVG in code. Pure throughout (validation + rendering); the pipeline
handles committing the `.svg`.

Validation enforces the spec's source + structural rules:
  - each non-derived value's `source_quote` must appear verbatim in the article,
    and the value's number must appear inside that quote;
  - derived values are allowed only with a formula + explanation (and only when
    derivations are enabled);
  - type-structural minimums (bar ≥2, line ≥3 ordered, donut sums to ~100,
    single_stat exactly 1, scatter ≥2).
"""
from __future__ import annotations

import re
from html import escape

SUPPORTED = {"bar", "horizontal_bar", "line", "donut", "stacked_bar", "scatter", "single_stat"}

_DEFAULTS = {
    "primary": "#1e293b",     # slate-800
    "secondary": "#2563eb",   # blue-600
    "background": "#ffffff",
    "text": "#0f172a",
    "grid": "#e2e8f0",
}


# ── helpers ──────────────────────────────────────────────────────────────────


def _num(v) -> float | None:
    try:
        f = float(v)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def points(chart: dict) -> list[dict]:
    """Flatten all series data points."""
    out: list[dict] = []
    for s in chart.get("series") or []:
        if isinstance(s, dict):
            for d in s.get("data") or []:
                if isinstance(d, dict):
                    out.append(d)
    return out


def _number_in_quote(d: dict, quote: str) -> bool:
    """Whether the value's number appears in its supporting quote (tolerant of
    thousands separators + a formatted display value)."""
    q = quote.replace(",", "")
    candidates: set[str] = set()
    disp = str(d.get("display_value") or "")
    for tok in re.findall(r"\d+(?:\.\d+)?", disp.replace(",", "")):
        candidates.add(tok)
    val = _num(d.get("value"))
    if val is not None:
        candidates.add(f"{val:g}")
        if val == int(val):
            candidates.add(str(int(val)))
    return any(c and c in q for c in candidates)


# ── validation ───────────────────────────────────────────────────────────────


def validate_chart_spec(chart: dict, *, article_text: str, allow_derived: bool) -> tuple[bool, str | None]:
    """Independently validate a chart spec against the article. Returns
    (ok, reason). Pure."""
    if not isinstance(chart, dict):
        return False, "not_an_object"
    ctype = chart.get("type")
    if ctype not in SUPPORTED:
        return False, "unsupported_type"
    pts = points(chart)
    if not pts:
        return False, "no_data"

    if ctype in ("bar", "horizontal_bar") and len(pts) < 2:
        return False, "bar_needs_two_categories"
    if ctype == "line":
        if len(pts) < 3:
            return False, "line_needs_three_points"
        if any(not (d.get("date")) for d in pts):
            return False, "line_needs_dates"
    if ctype == "donut":
        total = sum((_num(d.get("value")) or 0.0) for d in pts)
        if not (99.5 <= total <= 100.5):
            return False, "donut_values_do_not_total_100"
    if ctype == "single_stat" and len(pts) != 1:
        return False, "single_stat_requires_one_value"
    if ctype == "scatter" and len(pts) < 2:
        return False, "scatter_needs_multiple_observations"

    norm_article = _norm(article_text)
    for d in pts:
        if _num(d.get("value")) is None:
            return False, "value_not_finite"
        if d.get("derived"):
            if not allow_derived:
                return False, "derived_values_not_allowed"
            if not (str(d.get("formula") or "").strip() and str(d.get("derivation_explanation") or "").strip()):
                return False, "derived_missing_formula_or_explanation"
            continue
        quote = str(d.get("source_quote") or "").strip()
        if not quote:
            return False, "missing_source_quote"
        if _norm(quote) not in norm_article:
            return False, "source_quote_not_in_article"
        if not _number_in_quote(d, quote):
            return False, "value_not_present_in_quote"
        if not str(d.get("source_name") or "").strip():
            return False, "missing_source_name"
    return True, None


# ── rendering ────────────────────────────────────────────────────────────────


_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _safe_color(value, default: str) -> str:
    """Whitelist a model-supplied color to a hex literal — theme values are
    interpolated into SVG attributes, so anything non-hex (including attribute-
    breaking strings) falls back to the default rather than being injected."""
    v = str(value or "").strip()
    return v if _HEX_COLOR_RE.match(v) else default


def _theme(chart: dict) -> dict:
    t = chart.get("theme") if isinstance(chart.get("theme"), dict) else {}
    return {
        "primary": _safe_color(t.get("primary_color"), _DEFAULTS["primary"]),
        "secondary": _safe_color(t.get("secondary_color"), _DEFAULTS["secondary"]),
        "background": _safe_color(t.get("background_color"), _DEFAULTS["background"]),
        "text": _safe_color(t.get("text_color"), _DEFAULTS["text"]),
        "grid": _safe_color(t.get("grid_color"), _DEFAULTS["grid"]),
    }


def _label(d: dict) -> str:
    return str(d.get("label") or d.get("date") or "")


def _display(d: dict) -> str:
    return str(d.get("display_value") or d.get("value") or "")


_W, _H = 1200, 750
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 90, 40, 96, 130


def render_chart_svg(chart: dict) -> str:
    """Render a validated chart spec to a standalone SVG string (dispatch by
    type). Restrained editorial styling, zero-baseline bars, title/subtitle +
    source attribution. Pure — no external renderer, no model-supplied code."""
    ctype = chart.get("type")
    th = _theme(chart)
    body = {
        "bar": _render_bar,
        "horizontal_bar": _render_hbar,
        "line": _render_line,
        "donut": _render_donut,
        "stacked_bar": _render_bar,   # v1: render component sums as bars
        "scatter": _render_scatter,
        "single_stat": _render_single_stat,
    }.get(ctype, _render_bar)(chart, th)
    return _frame(chart, th, body)


def _frame(chart: dict, th: dict, body: str) -> str:
    title = escape(str(chart.get("title") or ""))
    subtitle = escape(str(chart.get("subtitle") or chart.get("takeaway") or ""))
    src = str(chart.get("source_name") or chart.get("source_text") or "")
    source_line = f"Source: {escape(src)}" if src else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_W} {_H}" '
        f'role="img" font-family="Inter, Arial, sans-serif">'
        f'<rect width="{_W}" height="{_H}" fill="{th["background"]}"/>'
        f'<text x="{_PAD_L}" y="46" font-size="30" font-weight="700" fill="{th["text"]}">{title}</text>'
        f'<text x="{_PAD_L}" y="76" font-size="18" fill="{th["text"]}" opacity="0.7">{subtitle}</text>'
        f'{body}'
        f'<text x="{_PAD_L}" y="{_H - 24}" font-size="14" fill="{th["text"]}" opacity="0.55">{source_line}</text>'
        f'</svg>'
    )


def _render_bar(chart: dict, th: dict) -> str:
    pts = points(chart)
    vals = [(_num(d.get("value")) or 0.0) for d in pts]
    vmax = max(vals + [1.0])
    x0, y0 = _PAD_L, _H - _PAD_B
    plot_w, plot_h = _W - _PAD_L - _PAD_R, y0 - _PAD_T
    n = len(pts)
    slot = plot_w / n
    bw = slot * 0.6
    out = [_baseline(x0, y0, plot_w, th)]
    for i, d in enumerate(pts):
        v = _num(d.get("value")) or 0.0
        h = (v / vmax) * plot_h
        x = x0 + i * slot + (slot - bw) / 2
        y = y0 - h
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{th["secondary"]}" rx="3"/>')
        out.append(f'<text x="{x + bw/2:.1f}" y="{y - 10:.1f}" font-size="16" font-weight="600" text-anchor="middle" fill="{th["text"]}">{escape(_display(d))}</text>')
        out.append(f'<text x="{x + bw/2:.1f}" y="{y0 + 28:.1f}" font-size="15" text-anchor="middle" fill="{th["text"]}" opacity="0.8">{escape(_label(d)[:22])}</text>')
    return "".join(out)


def _render_hbar(chart: dict, th: dict) -> str:
    pts = points(chart)
    vals = [(_num(d.get("value")) or 0.0) for d in pts]
    vmax = max(vals + [1.0])
    x0, y0 = _PAD_L + 80, _PAD_T + 10
    plot_w = _W - x0 - _PAD_R - 60
    plot_h = (_H - _PAD_B) - y0
    n = len(pts)
    slot = plot_h / n
    bh = slot * 0.6
    out = []
    for i, d in enumerate(pts):
        v = _num(d.get("value")) or 0.0
        w = (v / vmax) * plot_w
        y = y0 + i * slot + (slot - bh) / 2
        out.append(f'<text x="{x0 - 12:.1f}" y="{y + bh/2 + 5:.1f}" font-size="15" text-anchor="end" fill="{th["text"]}" opacity="0.8">{escape(_label(d)[:24])}</text>')
        out.append(f'<rect x="{x0:.1f}" y="{y:.1f}" width="{w:.1f}" height="{bh:.1f}" fill="{th["secondary"]}" rx="3"/>')
        out.append(f'<text x="{x0 + w + 8:.1f}" y="{y + bh/2 + 5:.1f}" font-size="16" font-weight="600" fill="{th["text"]}">{escape(_display(d))}</text>')
    return "".join(out)


def _render_line(chart: dict, th: dict) -> str:
    pts = sorted(points(chart), key=lambda d: str(d.get("date") or ""))
    vals = [(_num(d.get("value")) or 0.0) for d in pts]
    vmax, vmin = max(vals + [1.0]), min(vals + [0.0])
    span = (vmax - vmin) or 1.0
    x0, y0 = _PAD_L, _H - _PAD_B
    plot_w, plot_h = _W - _PAD_L - _PAD_R, y0 - _PAD_T
    n = len(pts)
    step = plot_w / max(1, n - 1)
    coords = []
    for i, d in enumerate(pts):
        v = _num(d.get("value")) or 0.0
        x = x0 + i * step
        y = y0 - ((v - vmin) / span) * plot_h
        coords.append((x, y, d))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in coords)
    out = [_baseline(x0, y0, plot_w, th),
           f'<polyline points="{poly}" fill="none" stroke="{th["secondary"]}" stroke-width="3"/>']
    for x, y, d in coords:
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{th["secondary"]}"/>')
        out.append(f'<text x="{x:.1f}" y="{y0 + 28:.1f}" font-size="14" text-anchor="middle" fill="{th["text"]}" opacity="0.8">{escape(_label(d)[:12])}</text>')
    return "".join(out)


def _render_donut(chart: dict, th: dict) -> str:
    import math

    pts = points(chart)
    total = sum((_num(d.get("value")) or 0.0) for d in pts) or 1.0
    cx, cy, r, rin = 360, 420, 190, 110
    palette = [th["secondary"], th["primary"], "#64748b", "#94a3b8", "#0ea5e9", "#334155"]
    out = []
    ang = -math.pi / 2
    for i, d in enumerate(pts):
        frac = (_num(d.get("value")) or 0.0) / total
        a2 = ang + frac * 2 * math.pi
        large = 1 if frac > 0.5 else 0
        x1, y1 = cx + r * math.cos(ang), cy + r * math.sin(ang)
        x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
        xi1, yi1 = cx + rin * math.cos(a2), cy + rin * math.sin(a2)
        xi2, yi2 = cx + rin * math.cos(ang), cy + rin * math.sin(ang)
        color = palette[i % len(palette)]
        out.append(
            f'<path d="M{x1:.1f},{y1:.1f} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f} '
            f'L{xi1:.1f},{yi1:.1f} A{rin},{rin} 0 {large} 0 {xi2:.1f},{yi2:.1f} Z" fill="{color}"/>'
        )
        # legend
        ly = _PAD_T + 40 + i * 34
        out.append(f'<rect x="720" y="{ly - 14}" width="18" height="18" fill="{color}" rx="3"/>')
        out.append(f'<text x="748" y="{ly}" font-size="17" fill="{th["text"]}">{escape(_label(d)[:28])} — {escape(_display(d))}</text>')
        ang = a2
    return "".join(out)


def _render_scatter(chart: dict, th: dict) -> str:
    pts = points(chart)
    xs, ys = [], []
    for d in pts:
        xv = _num(d.get("x")) if d.get("x") is not None else _num(d.get("value"))
        yv = _num(d.get("y")) if d.get("y") is not None else _num(d.get("value"))
        xs.append(xv or 0.0)
        ys.append(yv or 0.0)
    x0, y0 = _PAD_L, _H - _PAD_B
    plot_w, plot_h = _W - _PAD_L - _PAD_R, y0 - _PAD_T
    xmax, xmin = max(xs + [1.0]), min(xs + [0.0])
    ymax, ymin = max(ys + [1.0]), min(ys + [0.0])
    xs_span = (xmax - xmin) or 1.0
    ys_span = (ymax - ymin) or 1.0
    out = [_baseline(x0, y0, plot_w, th)]
    for xv, yv in zip(xs, ys):
        cx = x0 + ((xv - xmin) / xs_span) * plot_w
        cy = y0 - ((yv - ymin) / ys_span) * plot_h
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{th["secondary"]}" opacity="0.8"/>')
    return "".join(out)


def _render_single_stat(chart: dict, th: dict) -> str:
    pts = points(chart)
    d = pts[0] if pts else {}
    stat = escape(_display(d) or "")
    label = escape(_label(d) or str(chart.get("subtitle") or ""))
    return (
        f'<text x="{_W/2:.0f}" y="400" font-size="150" font-weight="800" text-anchor="middle" fill="{th["secondary"]}">{stat}</text>'
        f'<text x="{_W/2:.0f}" y="470" font-size="26" text-anchor="middle" fill="{th["text"]}" opacity="0.8">{label[:60]}</text>'
    )


def _baseline(x0: float, y0: float, w: float, th: dict) -> str:
    return f'<line x1="{x0}" y1="{y0}" x2="{x0 + w}" y2="{y0}" stroke="{th["grid"]}" stroke-width="2"/>'
