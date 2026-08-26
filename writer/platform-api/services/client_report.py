"""Client Reporting module — generated client-facing PDF reports.

Phase 0–1: assemble a per-client report from data AR Tools already has (organic
rankings, Maps geo-grids, GBP profile/reviews), render it to a **PDF**
(WeasyPrint, HTML/CSS → PDF), store it in the private `reports` storage bucket,
and record a `client_reports` row.

Phase 4 (this report is **client-facing & positive**): a **Performance
highlights** section with 30-day / 90-day / since-start comparisons (impressions,
organic clicks, average ranking — clicks auto-populate once GSC/GA4 traffic is
connected), an **AI search visibility** section (auto-populates once AI Visibility
scans run), and a Claude-written **executive summary** in plain, upbeat,
business-owner language (no SEO jargon, wins-focused, no "health score").

Owner-friendly layer (built on Phase 4): an **at-a-glance KPI strip** of hero
numbers at the top, a **Work delivered this period** section (completed pipeline
runs + new Local SEO pages), the organic table trimmed to the **top movers**
(not all 40 keywords), plain-English **captions** under each section, and a
**white-labeled** footer (the agency name, `client_report_agency_name`).

Later phases add GA4 + GBP-performance growth (Phase 2), Asana (Phase 3), and
email + Drive-folder delivery + scheduling (Phase 5).

Split for testability: data gathering + the pure HTML/SVG builders are
import-light and unit-tested; `render_pdf` is a thin WeasyPrint wrapper (lazy
import — the lib + its system libs live only in the deployed image), and the
job/store do I/O.
"""

from __future__ import annotations

import asyncio
import html as _html
import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import maps_reporting

logger = logging.getLogger(__name__)

_REPORTS_BUCKET = "reports"
_SIGNED_URL_TTL = 60 * 60 * 24 * 7  # 7 days
_LLM_TIMEOUT = 60.0                 # bound the campaign-health Claude call
_MAX_KEYWORDS = 40
_DEFAULT_PERIOD_DAYS = 30
_COMPARISON_LOOKBACK_DAYS = 400  # history window for 30/90/since-start comparisons


# ---------------------------------------------------------------------------
# Pure builders (no I/O) — unit-tested.
# ---------------------------------------------------------------------------
def _esc(value) -> str:
    return _html.escape("" if value is None else str(value))


def _rank_color(v) -> str:
    """Heatmap color for a geo-grid cell rank (lower = better; None = absent)."""
    if not isinstance(v, (int, float)):
        return "#e5e7eb"
    if v <= 3:
        return "#16a34a"
    if v <= 10:
        return "#84cc16"
    if v <= 20:
        return "#f59e0b"
    return "#ef4444"


def svg_sparkline(values: list, width: int = 170, height: int = 38) -> str:
    """Tiny rank trendline SVG from a series (gaps/None skipped). Pure.

    Rank is lower-is-better, so the y-axis is left as-is: a *rising* line means
    the position number grew (worse), a *falling* line means it improved — the
    legend in the report explains direction; the sparkline is a shape cue."""
    pts = [(i, float(v)) for i, v in enumerate(values) if isinstance(v, (int, float))]
    if len(pts) < 2:
        return ""
    vmin = min(v for _, v in pts)
    vmax = max(v for _, v in pts)
    span = (vmax - vmin) or 1.0
    n = len(values)
    last_better = pts[-1][1] <= pts[0][1]
    color = "#16a34a" if last_better else "#ef4444"

    def px(i: int) -> float:
        return round(i / max(n - 1, 1) * (width - 4) + 2, 1)

    def py(v: float) -> float:
        return round((v - vmin) / span * (height - 8) + 4, 1)

    coords = " ".join(f"{px(i)},{py(v)}" for i, v in pts)
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="1.5"/></svg>'
    )


def svg_geogrid(grid, cell: int = 13) -> str:
    """Geo-grid rank heatmap SVG from a 2-D array of ranks (None = absent). Pure."""
    if not isinstance(grid, list) or not grid:
        return ""
    cols = max((len(r) for r in grid if isinstance(r, list)), default=0)
    if not cols:
        return ""
    rows = len(grid)
    w, h = cols * cell, rows * cell
    rects = []
    for ri, row in enumerate(grid):
        if not isinstance(row, list):
            continue
        for ci, val in enumerate(row):
            rects.append(
                f'<rect x="{ci * cell}" y="{ri * cell}" width="{cell - 1}" '
                f'height="{cell - 1}" rx="1" fill="{_rank_color(val)}"/>'
            )
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(rects)}</svg>'
    )


def _weak_area_names(report_weak_locations) -> list[str]:
    """City names from a geo-grid result's report_weak_locations (object/list/None)."""
    rwl = report_weak_locations
    areas = rwl.get("weak_areas") if isinstance(rwl, dict) else (rwl if isinstance(rwl, list) else [])
    out: list[str] = []
    for a in (areas or [])[:6]:
        city = a.get("city") if isinstance(a, dict) else None
        if city and city not in out:
            out.append(city)
    return out


_TOP_MOVERS = 5


def _keyword_change(summary: dict):
    """Positions gained recently for one keyword (positive = improved). Pure.

    Uses the GSC 7-day vs 30-day averages when available, else the first→last of
    the rank sparkline (DataForSEO weekly series). None when there's too little
    history to call a direction."""
    a7, a30 = summary.get("avg_7"), summary.get("avg_30")
    if isinstance(a7, (int, float)) and isinstance(a30, (int, float)):
        return round(a30 - a7, 1)  # rank lower-is-better → 30d minus 7d = gain
    spark = [v for v in (summary.get("sparkline") or []) if isinstance(v, (int, float))]
    if len(spark) >= 2:
        return round(spark[0] - spark[-1], 1)  # first − last; positive = improved
    return None


def _section_organic(data: dict) -> str:
    o = data.get("organic")
    if not o or not o.get("keywords"):
        return ""
    kws = o["keywords"]
    # Lead with wins: feature the keywords that improved most, then the strongest
    # current rankings (page 1 first). A keyword is never featured purely because it
    # slipped — the story a client should see is where they're winning and gaining.
    # Figures stay accurate (a featured keyword shows its real movement, gain or
    # small dip); we just don't headline the losers.
    def _rank_of(k):
        r = k.get("current_rank")
        return r if isinstance(r, (int, float)) and r > 0 else 10_000

    gainers = sorted((k for k in kws if (k.get("change") or 0) > 0),
                     key=lambda k: k.get("change") or 0, reverse=True)
    # Only genuine wins are showcased: keywords that improved, or that rank on
    # page 1. A mid-pack or slipping keyword is NOT pulled in just to fill the
    # table (a client with only a few page-1 rankings would otherwise see a
    # decline padded into the list).
    page_one = sorted((k for k in kws if _rank_of(k) <= 10), key=_rank_of)
    featured, seen = [], set()
    for k in gainers + page_one:
        key = k.get("keyword")
        if key in seen:
            continue
        seen.add(key)
        featured.append(k)
        if len(featured) >= _TOP_MOVERS:
            break
    if not featured:
        # Nothing on page 1 or improving yet → show the closest-to-the-top few so
        # the section still reflects real positions (never headlining a decline).
        ranked = sorted((k for k in kws if _rank_of(k) < 10_000), key=_rank_of)
        featured = ranked[:_TOP_MOVERS] or kws[:_TOP_MOVERS]
    rows = []
    for k in featured:
        rank = k.get("current_rank")
        rank_txt = "—" if rank is None else (f"{rank}" if rank else "—")
        rows.append(
            f"<tr><td>{_esc(k.get('keyword'))}</td>"
            f"<td class='num'>{_esc(rank_txt)}</td>"
            f"<td class='num pos'>{_esc(_fmt_positions(k.get('change')))}</td>"
            f"<td>{svg_sparkline(k.get('sparkline') or [])}</td></tr>"
        )
    s = o.get("summary", {})
    extra = max((s.get("tracked", 0) or 0) - len(featured), 0)
    more = f" The remaining {extra} are tracked too — full list available on request." if extra else ""
    improving = s.get("improved", 0) or 0
    improving_txt = f" · {improving} improving" if improving else ""
    summary = (
        f"<p class='note'>Where your website shows up in Google for the searches that "
        f"matter to your business — highlighting your strongest rankings and recent gains.</p>"
        f"<p class='lead'>{s.get('tracked', 0)} tracked keywords · "
        f"{s.get('top10', 0)} ranking on page 1 of Google{improving_txt}.{more}</p>"
    )
    return (
        "<section><h2>Organic rankings</h2>" + summary
        + "<table><thead><tr><th>Keyword</th><th class='num'>Current</th>"
        "<th class='num'>Movement</th><th>Trend</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table></section>"
    )


def _maps_presence_line(g: dict) -> str:
    """A plain-English local-pack presence line with this-period vs previous-period
    movement (positive framing — a gain is called out; a dip is stated neutrally)."""
    now = g.get("presence_now")
    if now is None:
        return ""
    base = f"You’re in the top 3 on Google Maps across {round(now)}% of your service area"
    prev = g.get("presence_prev")
    if prev is not None:
        delta = round(now - prev)
        if delta > 0:
            base += f" — up from {round(prev)}% the previous period"
        elif delta < 0:
            base += f" — {round(prev)}% the previous period"
        else:
            base += " — steady vs the previous period"
    return f"<p class='lead'>{base}.</p>"


def _section_geogrid(data: dict) -> str:
    g = data.get("geogrid")
    if not g or not g.get("keywords"):
        return ""
    cards = []
    for k in g["keywords"]:
        avg = _fmt_pos(k.get("average_rank"))
        img = k.get("map_image")
        # The saved map image (real Google tile + numbered rank pins) when we have
        # it; otherwise the lightweight SVG grid so older scans still render.
        visual = (
            f"<img class='grid-img' src='{img}' alt='Local rank map'/>" if img
            else svg_geogrid(k.get("rank_grid"))
        )
        cards.append(
            "<div class='grid-card'>"
            f"<div class='grid-kw'>{_esc(k.get('keyword'))}</div>"
            f"<div>{visual}</div>"
            f"<div class='grid-meta'>avg rank {_esc(avg)} · "
            f"top-3 in {_esc(k.get('top3_pins', 0))}/{_esc(k.get('total_pins', 0))} pins</div>"
            "</div>"
        )
    presence_html = _maps_presence_line(g)
    weak = g.get("weak_areas") or []
    weak_html = (
        f"<p class='lead'>Areas with room to grow: {_esc(', '.join(weak))} — "
        f"the neighborhoods we’ll focus on next.</p>" if weak else ""
    )
    legend = (
        "<p class='legend'><span class='sw' style='background:#16a34a'></span>1–3 "
        "<span class='sw' style='background:#84cc16'></span>4–10 "
        "<span class='sw' style='background:#f59e0b'></span>11–20 "
        "<span class='sw' style='background:#ef4444'></span>21+ "
        "<span class='sw' style='background:#e5e7eb'></span>not ranked</p>"
    )
    return (
        "<section><h2>Local pack / Maps coverage</h2>"
        "<p class='note'>How visible your business is on Google Maps across your "
        "service area — green means you’re at the top of the map.</p>"
        + presence_html + weak_html + legend
        + "<div class='grid-cards'>" + "".join(cards) + "</div></section>"
    )


def _gbp_review_period_block(rp: Optional[dict]) -> tuple[str, bool]:
    """Reviews + rating this period vs last period (positive framing). Returns
    (html, has_highlights) — has_highlights lets the caller drop the generic
    top-reviews list when we're already showing this-period highlights."""
    if not rp:
        return "", False
    parts: list[str] = []
    rt = rp.get("reviews_this")
    if isinstance(rt, int) and (rt > 0 or (rp.get("reviews_prev") or 0) > 0):
        prev = rp.get("reviews_prev")
        vs = f" (vs {prev} the previous period)" if isinstance(prev, int) else ""
        parts.append(
            f"<p class='lead'>You gained <strong>{rt}</strong> new review"
            f"{'s' if rt != 1 else ''} this period{vs}.</p>"
        )
    now, prev_r = rp.get("rating_now"), rp.get("rating_prev")
    if now is not None and prev_r is not None and round(now - prev_r, 1) > 0:
        parts.append(
            f"<p class='lead'>Your rating climbed to {now:g}★ — up from "
            f"{round(prev_r, 1):g}★ at the start of the period.</p>"
        )
    highlights = rp.get("highlights") or []
    if highlights:
        lis = "".join(f"<li>“{_esc(t)}”</li>" for t in highlights)
        parts.append(f"<p class='note'>Recent reviews this period:</p><ul class='reviews'>{lis}</ul>")
    return "".join(parts), bool(highlights)


def _section_gbp(data: dict) -> str:
    b = data.get("gbp")
    if not b:
        return ""
    review_period_html, has_period_highlights = _gbp_review_period_block(b.get("review_period"))
    # Fall back to the generic top-reviews list only when the period block isn't
    # already showing this-period highlights.
    reviews = "" if has_period_highlights else "".join(
        f"<li>“{_esc(r)}”</li>" for r in (b.get("top_reviews") or [])[:3]
    )
    reviews_html = f"<ul class='reviews'>{reviews}</ul>" if reviews else ""
    rating = b.get("rating")
    rating_html = (
        f"<p class='lead'>{_esc(rating)} ★ · {_esc(b.get('review_count', 0))} reviews</p>"
        if rating is not None else ""
    )
    metrics = b.get("metrics") or {}
    metric_rows = ""
    for it in metrics.get("items") or []:
        pct = it.get("pct")
        if pct is None:
            change = "new"
        else:
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "▬")
            change = f"{arrow} {abs(pct)}%"
        metric_rows += (
            f"<tr><td>{_esc(it.get('label'))}</td>"
            f"<td>{_esc(it.get('current', 0))}</td>"
            f"<td>{_esc(change)}</td></tr>"
        )
    metrics_html = (
        "<p class='note'>How customers engaged with your Google listing in the last "
        f"{_esc(metrics.get('window_days', 30))} days, vs the previous "
        f"{_esc(metrics.get('window_days', 30))}.</p>"
        "<table class='gbp-metrics'><thead><tr><th>Action</th><th>This period</th>"
        f"<th>Change</th></tr></thead><tbody>{metric_rows}</tbody></table>"
        if metric_rows else ""
    )
    return (
        "<section><h2>Google Business Profile</h2>"
        "<p class='note'>Your Google listing — the profile customers see on Google "
        "Search and Maps, with their ratings and reviews.</p>"
        f"<p>{_esc(b.get('business_name'))}{(' · ' + _esc(b.get('address'))) if b.get('address') else ''}</p>"
        + rating_html + review_period_html + reviews_html + metrics_html + "</section>"
    )


# --- Period-over-period comparisons (this period vs the previous same-length
# window) — pure --------------------------------------------------------------
def previous_period(period_start: date, period_end: date) -> tuple[date, date]:
    """The window of the same length immediately before the report period. Pure."""
    length = max(1, (period_end - period_start).days)
    return period_start - timedelta(days=length), period_start


def _sum_between(by_date: dict, start: date, end: date) -> Optional[float]:
    vals = [v for d, v in by_date.items() if start < d <= end]
    return sum(vals) if vals else None


def _avg_between(by_date: dict, start: date, end: date) -> Optional[float]:
    vals = [v for d, v in by_date.items() if start < d <= end]
    return sum(vals) / len(vals) if vals else None


def _pct(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    if curr is None or not prev:
        return None
    return round((curr - prev) / prev * 100, 1)


def _accum_by_date(rows: list[dict], field: str) -> dict:
    """{date: summed field} over rows with a parseable date and a non-null field."""
    out: dict = {}
    for r in rows or []:
        if r.get(field) is None:
            continue
        try:
            d = date.fromisoformat(str(r.get("date"))[:10])
        except (TypeError, ValueError):
            continue
        out[d] = out.get(d, 0) + (r[field] or 0)
    return out


def build_comparisons(
    metric_rows: list[dict], period_start: date, period_end: date,
    traffic_rows: Optional[list[dict]] = None,
) -> Optional[dict]:
    """This-period vs previous-period change for impressions, organic clicks, and
    average ranking — tied to the report's own period length. Pure.

    The previous period is the same-length window immediately before the report
    period. A previous-period figure is shown only when the data actually spans
    that window (data began on or before it); otherwise it's None — never a
    partial, misleading delta. ``traffic_rows`` (one row per date) sources the
    volume metrics (property-level GSC daily totals); ranking always comes from
    ``metric_rows`` (per-keyword positions)."""
    traffic_src = traffic_rows if traffic_rows is not None else metric_rows
    impr = _accum_by_date(traffic_src, "impressions")
    clk = _accum_by_date(traffic_src, "clicks")

    rsum, rn = {}, {}
    for r in metric_rows or []:
        try:
            d = date.fromisoformat(str(r.get("date"))[:10])
        except (TypeError, ValueError):
            continue
        pos = r.get("gsc_position")
        if pos is None:
            pos = r.get("tracked_rank")
        if pos is not None:
            rsum[d] = rsum.get(d, 0) + pos
            rn[d] = rn.get(d, 0) + 1
    rank = {d: rsum[d] / rn[d] for d in rsum}
    prev_start, prev_end = previous_period(period_start, period_end)

    def _prev_covered(by_date: dict) -> bool:
        # Only compare to the previous period when data actually spans it.
        return bool(by_date) and min(by_date) <= prev_start

    def _vol(by_date: dict) -> Optional[dict]:
        cur = _sum_between(by_date, period_start, period_end)
        if cur is None:
            return None
        prev = _sum_between(by_date, prev_start, prev_end) if _prev_covered(by_date) else None
        return {"current": cur, "previous": prev, "change": _pct(cur, prev)}

    def _rnk(by_date: dict) -> Optional[dict]:
        cur = _avg_between(by_date, period_start, period_end)
        if cur is None:
            return None
        prev = _avg_between(by_date, prev_start, prev_end) if _prev_covered(by_date) else None
        change = None if prev is None else round(prev - cur, 1)  # positive = positions gained
        return {"current": cur, "previous": prev, "change_positions": change}

    out: dict = {}
    if (v := _vol(impr)):
        out["impressions"] = v
    if (v := _vol(clk)):
        out["clicks"] = v
    if (v := _rnk(rank)):
        out["rank"] = v
    return out or None


def _fmt_int(v) -> str:
    try:
        return f"{int(round(float(v))):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(p) -> str:
    if p is None:
        return "—"
    arrow = "▲" if p > 0 else ("▼" if p < 0 else "")
    return f"{arrow} {'+' if p > 0 else ''}{round(p)}%"


def _fmt_positions(d) -> str:
    if d is None:
        return "—"
    if d > 0:
        return f"▲ +{round(d, 1):g} positions"
    if d < 0:
        return f"▼ {round(d, 1):g} positions"
    return "no change"


def _perf_row(label, current, previous, change) -> str:
    return (f"<tr><td>{_esc(label)}</td><td class='num'>{_esc(current)}</td>"
            f"<td class='num'>{_esc(previous)}</td>"
            f"<td class='num pos'>{_esc(change)}</td></tr>")


def _section_performance(data: dict) -> str:
    comp = (data.get("organic") or {}).get("comparisons")
    if not comp:
        return ""
    rows = []
    for key, label, fmt_val, change_key, fmt_change in (
        ("impressions", "Impressions", _fmt_int, "change", _fmt_pct),
        ("clicks", "Organic clicks", _fmt_int, "change", _fmt_pct),
        ("rank", "Average ranking", _fmt_pos, "change_positions", _fmt_positions),
    ):
        m = comp.get(key)
        if not m or m.get("current") is None:
            continue
        # A volume metric with a zero current window means the source has no traffic
        # for this period (a GSC gap, or a stale feed) — showing "0 ▼ -100%" reads
        # as a collapse to a client. Omit it rather than fabricate a scary delta.
        if key in ("impressions", "clicks") and not m.get("current"):
            continue
        prev = m.get("previous")
        prev_txt = fmt_val(prev) if prev is not None else "—"
        rows.append(_perf_row(label, fmt_val(m["current"]), prev_txt, fmt_change(m.get(change_key))))
    if not rows:
        return ""
    return (
        "<section><h2>Performance highlights</h2>"
        "<p class='note'>How you’re doing this period compared with the period just "
        "before it (the same number of days).</p>"
        "<table><thead><tr><th>Metric</th><th class='num'>This period</th>"
        "<th class='num'>Previous period</th><th class='num'>Change</th>"
        "</tr></thead><tbody>"
        + "".join(rows) + "</tbody></table></section>"
    )


def _section_ga4(data: dict) -> str:
    """GA4 website-traffic section (visits/conversions + top channels).
    Client-facing tone, degrades cleanly. Client Reporting Phase 2.

    Deliberately no summed "visitors" row — GA4 totalUsers isn't additive across
    days (see _gather_ga4). Visits (sessions) and conversions are additive."""
    g = data.get("ga4")
    if not g:
        return ""
    rows = []
    for key, label in (("sessions", "Website visits"), ("conversions", "Conversions")):
        m = g.get(key)
        if not m or not m.get("current"):
            continue
        prev = m.get("previous")
        prev_txt = _fmt_int(prev) if prev is not None else "—"
        rows.append(_perf_row(label, _fmt_int(m["current"]), prev_txt, _fmt_pct(m.get("change"))))
    if not rows:
        return ""
    table = (
        "<table><thead><tr><th>Metric</th><th class='num'>This period</th>"
        "<th class='num'>Previous period</th><th class='num'>Change</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )
    channels = g.get("channels") or []
    ch_html = ""
    if channels:
        ch_rows = "".join(
            f"<tr><td>{_esc(c.get('name'))}</td><td class='num'>{_fmt_int(c.get('sessions'))}</td>"
            f"<td class='num'>{_esc(c.get('pct', 0))}%</td></tr>"
            for c in channels
        )
        ch_html = (
            "<p class='note'>Where your visits came from this period.</p>"
            "<table><thead><tr><th>Channel</th><th class='num'>Visits</th>"
            "<th class='num'>Share</th></tr></thead><tbody>" + ch_rows + "</tbody></table>"
        )
    return (
        "<section><h2>Website traffic</h2>"
        "<p class='note'>Visits to your website and what they did, from Google "
        "Analytics — this period vs the period just before it.</p>"
        + table + ch_html + "</section>"
    )


def _section_ai_visibility(data: dict) -> str:
    a = data.get("ai_visibility")
    if not a or not a.get("engines"):
        return ""
    items = "".join(
        f"<li><strong>{_esc(_ENGINE_LABELS.get(e, e))}</strong>: appears in {_esc(v)}</li>"
        for e, v in a["engines"].items()
    )
    return (
        "<section><h2>AI search visibility</h2>"
        "<p class='note'>How often your brand is recommended when AI assistants "
        "answer questions like your customers'.</p>"
        + _ai_visibility_headline(a)
        + "<p class='lead'>Across the AI tools we track:</p>"
        f"<ul class='reviews'>{items}</ul>"
        + _ai_keyword_matrix(a.get("keywords") or [])
        + "</section>"
    )


def _ai_visibility_headline(a: dict) -> str:
    """Overall AI visibility this period, with previous-period movement (positive
    framing — a gain is called out, a dip stated neutrally)."""
    now = a.get("visibility_now")
    if now is None:
        return ""
    base = f"You’re being recommended in {round(now)}% of the AI answers we track"
    prev = a.get("visibility_prev")
    if prev is not None:
        delta = round(now - prev)
        if delta > 0:
            base += f" — up from {round(prev)}% the previous period"
        elif delta < 0:
            base += f" — {round(prev)}% the previous period"
        else:
            base += " — steady vs the previous period"
    return f"<p class='lead'>{base}.</p>"


def _ai_keyword_matrix(keywords: list[dict]) -> str:
    """Per-query visibility: for each tracked question, which AI tools recommend the
    brand (green chip) vs don't (grey). Makes the summary counts specific — the
    client sees exactly which questions they win and which they're missing from."""
    if not keywords:
        return ""
    rows = ""
    for k in keywords:
        eng = k.get("engines") or {}
        chips = ""
        for e in _AI_ENGINE_ORDER:
            if e not in eng:
                continue  # engine not run for this query → not shown (not a miss)
            cls = "aiyes" if eng[e] else "aino"
            chips += f"<span class='aichip {cls}'>{_esc(_AI_ENGINE_SHORT[e])}</span>"
        count = f"{k.get('found_count', 0)}/{k.get('total', 0)}"
        rows += (
            f"<tr><td class='aiq'>{_esc(_shorten(k.get('keyword'), 120))}</td>"
            f"<td class='aichips'>{chips}</td>"
            f"<td class='num aicount'>{_esc(count)}</td></tr>"
        )
    invisible = [k for k in keywords if not k.get("found_count")]
    note = ""
    if invisible:
        qs = ", ".join(f"“{_shorten(k.get('keyword'), 70)}”" for k in invisible[:4])
        note = (
            f"<p class='note'>Room to grow — a few questions where we’ll work to get you "
            f"recommended next: {_esc(qs)}{'…' if len(invisible) > 4 else ''}</p>"
        )
    return (
        "<p class='lead' style='margin-top:12px'>Which AI tools recommend you, question by question:</p>"
        "<table class='aimatrix'><thead><tr><th>Question a customer might ask</th>"
        "<th>AI tools recommending you</th><th class='num'>Score</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>{note}"
    )


def _shorten(text, limit: int) -> str:
    s = "" if text is None else str(text)
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


_ENGINE_LABELS = {
    "chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini",
    "perplexity": "Perplexity", "google_ai_overview": "Google AI Overviews",
    "google_ai_mode": "Google AI Mode",
}
# Stable column order + compact labels for the per-keyword chip matrix.
_AI_ENGINE_ORDER = ["chatgpt", "claude", "gemini", "perplexity", "google_ai_overview", "google_ai_mode"]
_AI_ENGINE_SHORT = {
    "chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini",
    "perplexity": "Perplexity", "google_ai_overview": "AI Overviews", "google_ai_mode": "AI Mode",
}


def _section_exec(data: dict) -> str:
    e = data.get("exec")
    if not e:
        return ""

    def _list(title, items):
        clean = [x for x in (items or []) if x is not None and str(x).strip()][:5]
        lis = "".join(f"<li>{_esc(x)}</li>" for x in clean)
        return f"<div class='hcol'><h4>{title}</h4><ul>{lis}</ul></div>" if lis else ""

    cols = _list("Highlights", e.get("highlights")) + _list("What we’re focused on next", e.get("focus_next"))
    return (
        "<section class='exec'><h2>Executive summary</h2>"
        f"<p class='headline'>{_esc(e.get('headline'))}</p>"
        f"<div class='hcols'>{cols}</div></section>"
    )


# Client-facing status label + colour (positive framing — no "overdue"/"behind"
# scare copy in a client deliverable; the internal strategy doc keeps the raw
# status). Goals with no measurement yet are dropped from the client report.
_GOAL_STATUS_CLIENT = {
    "achieved": ("Achieved", "#166534"),
    "on_track": ("On track", "#166534"),
    "behind": ("In progress", "#b45309"),
    "overdue": ("In progress", "#b45309"),
    "manual": ("Tracking", "#475569"),
}


def _fmt_goal_value(goal_type, v) -> str:
    """Human, client-friendly rendering of a goal metric value. Pure."""
    if v is None:
        return "—"
    if goal_type == "keyword_position":
        return f"position {v:g}"
    if goal_type == "keywords_in_top":
        return f"{v:g} keyword{'s' if v != 1 else ''}"
    if goal_type == "organic_clicks":
        return f"{_fmt_int(v)} clicks/mo"
    if goal_type == "organic_impressions":
        return f"{_fmt_int(v)} impressions/mo"
    if goal_type in ("ai_visibility", "maps_pack_presence"):
        return f"{v:g}%"
    return f"{v:g}"


def _goal_label(goal: dict) -> str:
    """A display label for a goal — its user label, else a type-derived one."""
    if goal.get("label"):
        return str(goal["label"])
    kw = goal.get("keyword")
    base = {
        "keyword_position": f"Rank for “{kw}”" if kw else "Keyword ranking",
        "keywords_in_top": "Keywords in the top results",
        "organic_clicks": "Monthly organic clicks",
        "organic_impressions": "Monthly search impressions",
        "ai_visibility": "AI-assistant visibility",
        "maps_pack_presence": "Local-pack presence",
        "custom": "Goal",
    }
    return base.get(goal.get("goal_type"), "Goal")


# Goal types whose measurement is date-aware (respects the as-of date), so a
# "since last period" delta is meaningful. maps_pack_presence / ai_visibility read
# the latest scan regardless of date (they get their own period comparison in the
# Maps / AI sections instead), and custom has no metric.
_PERIOD_GOAL_TYPES = {"keyword_position", "keywords_in_top", "organic_clicks", "organic_impressions"}
_GOAL_MOVE_UNIT = {
    "keyword_position": "positions", "keywords_in_top": "keywords",
    "organic_clicks": "clicks/mo", "organic_impressions": "impressions/mo",
}


def _goal_movement(g: dict) -> str:
    """A small 'since last period' movement line for a goal (positive framing —
    gains are green, dips are muted, never alarming red). '' when not comparable."""
    gt = g.get("goal_type")
    cur, prev = g.get("current_value"), g.get("previous_value")
    if gt not in _PERIOD_GOAL_TYPES or cur is None or prev is None:
        return ""
    lower = gt == "keyword_position"
    gain = round((prev - cur) if lower else (cur - prev), 1)
    if gain == 0:
        return "<div class='gmove'>no change since last period</div>"
    unit = _GOAL_MOVE_UNIT.get(gt, "")
    mag = abs(gain)
    if mag == 1 and unit in ("positions", "keywords"):
        unit = unit[:-1]  # "1 keyword" / "1 position", not "1 keywords"
    mag_txt = _fmt_int(mag) if gt in ("organic_clicks", "organic_impressions") else f"{mag:g}"
    arrow, cls = ("▲", "up") if gain > 0 else ("▼", "down")
    return f"<div class='gmove {cls}'>{arrow} {mag_txt} {unit} since last period</div>"


def _section_goals(data: dict) -> str:
    goals = (data.get("goals") or {}).get("goals") or []
    rows = []
    for g in goals:
        label = _GOAL_STATUS_CLIENT.get(g.get("status"))
        if not label:  # no_data / unknown → nothing to show a client
            continue
        status_text, colour = label
        pct = g.get("progress_pct")
        gt = g.get("goal_type")
        current = _fmt_goal_value(gt, g.get("current_value"))
        target = _fmt_goal_value(gt, g.get("target_value"))
        bar = ""
        if pct is not None:
            w = max(0, min(100, round(pct)))
            # "Expected by now" marker at elapsed%: fill short of the marker reads as
            # behind pace at a glance, so a green "On track" (or amber "In progress")
            # never contradicts an almost-empty bar.
            elapsed = g.get("elapsed_pct")
            marker = ""
            if isinstance(elapsed, (int, float)):
                ew = max(0, min(100, round(elapsed)))
                marker = f"<div class='gmark' style='left:{ew}%'></div>"
            bar = (f"<div class='gbar'><div class='gbar-fill' style='width:{w}%;"
                   f"background:{colour}'></div>{marker}</div>")
        where = current if gt == "custom" else f"{_esc(current)} &middot; target {_esc(target)}"
        rows.append(
            f"<tr><td><strong>{_esc(_goal_label(g))}</strong></td>"
            f"<td><span class='gchip' style='color:{colour}'>{_esc(status_text)}</span></td>"
            f"<td class='gprog'>{bar}</td>"
            f"<td class='num'>{where}{_goal_movement(g)}</td></tr>"
        )
    if not rows:
        return ""
    return (
        "<section><h2>Progress toward your goals</h2>"
        "<p class='note'>The targets we set for this campaign and how each is tracking. "
        "The line on each bar marks where the goal is expected to be by now.</p>"
        "<table><thead><tr><th>Goal</th><th>Status</th><th>Progress</th>"
        "<th class='num'>Where we are</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table></section>"
    )


def _fmt_pos(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{round(float(v), 1):g}"
    except (TypeError, ValueError):
        return "—"


_CONTENT_LABELS = {
    "blog_post": "Blog posts", "service_page": "Service pages",
    "location_page": "Location pages", "local_seo_page": "Local SEO pages",
}


def _section_work_delivered(data: dict) -> str:
    w = data.get("work_delivered")
    if not w or not w.get("counts"):
        return ""
    items = "".join(
        f"<li><strong>{_esc(n)}</strong> {_esc(_CONTENT_LABELS.get(ct, ct))}</li>"
        for ct, n in w["counts"].items()
    )
    return (
        "<section><h2>Work delivered this period</h2>"
        "<p class='note'>The new pages and articles we created this period to grow "
        "your search presence.</p>"
        f"<ul class='delivered'>{items}</ul></section>"
    )


def _kpi(label: str, value: str, sub: str) -> str:
    return (
        "<div class='kpi'>"
        f"<div class='kpi-val'>{_esc(value)}</div>"
        f"<div class='kpi-label'>{_esc(label)}</div>"
        f"<div class='kpi-sub'>{_esc(sub)}</div></div>"
    )


def _kpi_strip(data: dict) -> str:
    """Three–four hero numbers at the very top — the at-a-glance answer to 'is my
    marketing working?'. Each card is included only when its data exists."""
    cards: list[str] = []
    comp = (data.get("organic") or {}).get("comparisons") or {}
    impr = comp.get("impressions") or {}
    impr_change = impr.get("change")
    # Only a genuine gain leads the report — a flat/negative or not-yet-comparable
    # figure isn't a hero number (build_comparisons already leaves change None when
    # there's no comparable previous period).
    if impr_change and impr_change > 0:
        cards.append(_kpi("Search visibility", _fmt_pct(impr_change), "vs the previous period"))
    # GA4 website visits (Phase 2) — a hero number only on a genuine gain.
    sess = (data.get("ga4") or {}).get("sessions") or {}
    sess_change = sess.get("change")
    if sess_change and sess_change > 0:
        cards.append(_kpi("Website visits", _fmt_pct(sess_change), "vs the previous period"))
    rank = comp.get("rank") or {}
    rank_change = (rank or {}).get("change_positions")
    if rank_change and rank_change > 0:
        cards.append(_kpi("Ranking gains", f"▲ {round(rank_change, 1):g}", "positions vs the previous period"))
    summ = (data.get("organic") or {}).get("summary") or {}
    if summ.get("tracked"):
        cards.append(_kpi("On page 1 of Google", str(summ.get("top10", 0)), f"of {summ.get('tracked')} keywords"))
    wd = data.get("work_delivered") or {}
    if wd.get("total"):
        cards.append(_kpi("Content delivered", str(wd["total"]), "new pages & articles"))
    if not cards:
        return ""
    return f"<section class='kpis'>{''.join(cards)}</section>"


def build_report_html(data: dict) -> str:
    """Assemble the full report HTML document (pure). WeasyPrint renders this."""
    client = data.get("client", {})
    period = data.get("period", {})
    kpis = _kpi_strip(data)
    sections = "".join(
        s for s in (_section_exec(data), _section_goals(data), _section_performance(data),
                    _section_ga4(data), _section_work_delivered(data), _section_organic(data),
                    _section_geogrid(data), _section_ai_visibility(data)) if s
        # GBP section removed from the client PDF for now (re-add _section_gbp(data)
        # above to restore). _gather_gbp still runs so review snapshots keep
        # recording and the historical series stays continuous.
    )
    if not (kpis or sections):
        sections = "<section><p class='lead'>No report data is available for this client yet.</p></section>"
    logo = client.get("logo_url")
    logo_html = f'<img class="logo" src="{_esc(logo)}"/>' if logo else ""
    agency = data.get("agency_name") or "Amazing Rankings"
    title = _esc(client.get("name") or "Client") + " — SEO Report"
    return f"""<!doctype html><html><head><meta charset="utf-8"/>
<title>{title}</title>
<style>{_CSS}</style></head><body>
<header class="cover">
  {logo_html}
  <h1>{_esc(client.get('name') or 'Client')}</h1>
  <div class="subtitle">SEO Performance Report</div>
  <div class="period">{_esc(period.get('start'))} – {_esc(period.get('end'))}</div>
</header>
<main>{kpis}{sections}</main>
<footer>Prepared by {_esc(agency)} · {_esc(period.get('end'))}</footer>
</body></html>"""


_CSS = """
@page { size: A4; margin: 18mm 16mm; @bottom-center { content: counter(page); color:#94a3b8; font-size:9px; } }
* { box-sizing: border-box; }
body { font-family: -apple-system, Helvetica, Arial, sans-serif; color:#0f172a; font-size:11px; line-height:1.5; }
.cover { text-align:center; padding:40px 0 24px; border-bottom:3px solid #6366f1; margin-bottom:24px; }
.cover .logo { max-height:64px; margin-bottom:16px; }
.cover h1 { font-size:26px; margin:0; }
.cover .subtitle { color:#6366f1; font-weight:600; letter-spacing:.05em; text-transform:uppercase; font-size:12px; margin-top:6px; }
.cover .period { color:#64748b; margin-top:8px; }
section { margin-bottom:22px; page-break-inside:avoid; }
h2 { font-size:15px; border-bottom:1px solid #e2e8f0; padding-bottom:6px; color:#0f172a; }
.lead { color:#334155; }
.note { color:#64748b; font-size:10px; font-style:italic; margin:2px 0 6px; }
.kpis { display:flex; gap:12px; margin-bottom:24px; page-break-inside:avoid; }
.kpi { flex:1; border:1px solid #e2e8f0; border-radius:10px; padding:14px 12px; text-align:center; background:#f8fafc; }
.kpi-val { font-size:22px; font-weight:700; color:#166534; }
.kpi-label { font-size:10px; font-weight:600; color:#0f172a; margin-top:4px; }
.kpi-sub { font-size:9px; color:#94a3b8; margin-top:2px; }
.delivered { list-style:none; padding:0; display:flex; flex-wrap:wrap; gap:8px 24px; color:#334155; }
.delivered li { font-size:12px; }
.delivered strong { color:#166534; font-size:14px; }
table { width:100%; border-collapse:collapse; margin-top:8px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid #eef2f6; vertical-align:middle; }
th { font-size:9px; text-transform:uppercase; letter-spacing:.04em; color:#94a3b8; }
td.num, th.num { text-align:right; }
.grid-cards { display:flex; flex-wrap:wrap; gap:14px; margin-top:10px; }
.grid-card { border:1px solid #e2e8f0; border-radius:8px; padding:10px; text-align:center; }
.grid-img { width:220px; max-width:100%; height:auto; border-radius:6px; }
.grid-kw { font-weight:600; margin-bottom:6px; }
.grid-meta { color:#64748b; font-size:10px; margin-top:6px; }
.legend { color:#64748b; font-size:9px; }
.legend .sw { display:inline-block; width:9px; height:9px; border-radius:2px; margin:0 3px 0 10px; vertical-align:middle; }
.reviews { color:#334155; } .reviews li { margin-bottom:4px; }
.gchip { font-weight:700; font-size:10px; }
.gprog { width:34%; }
.gbar { position:relative; background:#eef2f6; border-radius:6px; height:8px; width:100%; }
.gbar-fill { height:8px; border-radius:6px; }
.gmark { position:absolute; top:-2px; width:2px; height:12px; background:#334155; border-radius:1px; }
.gmove { font-size:9px; font-weight:400; color:#94a3b8; margin-top:2px; }
.gmove.up { color:#166534; }
.aimatrix td, .aimatrix th { vertical-align:middle; }
.aimatrix .aiq { width:46%; color:#334155; }
.aichips { line-height:1.9; }
.aichip { display:inline-block; font-size:8px; font-weight:600; padding:1px 6px; border-radius:9px; margin:1px 3px 1px 0; }
.aichip.aiyes { background:#dcfce7; color:#166534; }
.aichip.aino { background:#f1f5f9; color:#94a3b8; }
.aicount { font-weight:700; color:#166534; white-space:nowrap; }
footer { margin-top:24px; padding-top:8px; border-top:1px solid #e2e8f0; color:#94a3b8; font-size:9px; text-align:center; }
.exec .headline { font-size:13px; color:#0f172a; font-weight:600; }
td.num.pos { font-weight:600; color:#166534; }
.hcols { display:flex; gap:16px; margin-top:8px; }
.hcol { flex:1; } .hcol h4 { font-size:10px; text-transform:uppercase; letter-spacing:.04em; color:#94a3b8; margin:0 0 4px; }
.hcol ul { margin:0; padding-left:16px; } .hcol li { margin-bottom:3px; color:#334155; }
"""


# ---------------------------------------------------------------------------
# Data gathering (DB reads) — best-effort per section.
# ---------------------------------------------------------------------------
def _keyword_period_change(rows: list[dict], period_start: date, period_end: date):
    """Positions gained this period vs the previous same-length period for one
    keyword (positive = improved, since a lower rank is better). None when either
    period lacks position data. Pure."""
    prev_start, _ = previous_period(period_start, period_end)

    def _avg(start: date, end: date):
        vals = []
        for r in rows or []:
            try:
                d = date.fromisoformat(str(r.get("date"))[:10])
            except (TypeError, ValueError):
                continue
            pos = r.get("gsc_position")
            if pos is None:
                pos = r.get("tracked_rank")
            if pos is not None and start < d <= end:
                vals.append(pos)
        return sum(vals) / len(vals) if vals else None

    cur = _avg(period_start, period_end)
    prev = _avg(prev_start, period_start)
    if cur is None or prev is None:
        return None
    return round(prev - cur, 1)


def _gather_organic(supabase, client_id: str, period_start: date, period_end: date) -> Optional[dict]:
    from services import rank_status

    kws = (
        supabase.table("tracked_keywords")
        .select("id, keyword")
        .eq("client_id", client_id)
        .eq("active", True)
        .order("keyword")
        .limit(_MAX_KEYWORDS)
        .execute()
    ).data or []
    if not kws:
        return None
    kw_ids = [k["id"] for k in kws]
    metrics: dict[str, list[dict]] = {}
    flat_rows: list[dict] = []
    # Full history (capped) so the previous-period comparison has a baseline.
    cutoff = date.fromordinal(period_end.toordinal() - _COMPARISON_LOOKBACK_DAYS).isoformat()
    for r in (
        supabase.table("rank_keyword_metrics")
        .select("keyword_id, date, gsc_position, tracked_rank, impressions, clicks")
        .in_("keyword_id", kw_ids)
        .gte("date", cutoff)
        .execute()
    ).data or []:
        metrics.setdefault(r["keyword_id"], []).append(r)
        flat_rows.append(r)

    keywords, top10, improved, declined = [], 0, 0, 0
    for k in kws:
        s = rank_status.compute_keyword_summary(
            metrics.get(k["id"], []), period_end, settings.rank_gsc_coverage_days
        )
        rank = s.get("today_rank")
        if isinstance(rank, (int, float)) and rank <= 10:
            top10 += 1
        # Movement is this period vs the previous same-length period.
        change = _keyword_period_change(metrics.get(k["id"], []), period_start, period_end)
        if isinstance(change, (int, float)):
            if change > 0:
                improved += 1
            elif change < 0:
                declined += 1
        keywords.append({
            "keyword": k["keyword"],
            "current_rank": rank,
            "avg_30d": s.get("avg_30"),
            "change": change,
            "sparkline": s.get("sparkline") or [],
        })
    return {
        "keywords": keywords,
        "summary": {"tracked": len(keywords), "top10": top10, "improved": improved, "declined": declined},
        # Volume metrics come from the property-level GSC daily totals (same source
        # as the campaign goals) so Performance highlights agrees with the goals and
        # never shows the stale-per-keyword "0 / -100%" artifact; ranking stays from
        # the per-keyword series (flat_rows).
        "comparisons": build_comparisons(
            flat_rows, period_start, period_end,
            traffic_rows=_gather_gsc_traffic(supabase, client_id, period_end),
        ),
    }


def _gather_gsc_traffic(supabase, client_id: str, today: date) -> Optional[list[dict]]:
    """Per-day property-level GSC impressions/clicks over the comparison window, via
    the aggregating RPC (one row per day). None when the client has no verified GSC
    property or the read fails — comparisons then fall back to the per-keyword series."""
    try:
        prop = (
            supabase.table("gsc_properties").select("id")
            .eq("client_id", client_id).eq("access_status", "ok").limit(1).execute()
        ).data
        if not prop:
            return None
        cutoff = date.fromordinal(today.toordinal() - _COMPARISON_LOOKBACK_DAYS).isoformat()
        rows = supabase.rpc(
            "gsc_property_daily_traffic",
            {"p_property_id": prop[0]["id"], "p_from": cutoff},
        ).execute().data or []
        return rows or None
    except Exception as exc:
        logger.warning("report_gsc_traffic_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def _gather_ga4(supabase, client_id: str, period_start: date, period_end: date) -> Optional[dict]:
    """GA4 website traffic (visits/visitors/conversions + top channels) for the
    report period vs the previous same-length period. None when the client has no
    verified GA4 property or no data in the window. Client Reporting Phase 2 —
    reads ga4_daily (populated by the daily ga4_ingest, dormant until enabled)."""
    prop = (
        supabase.table("ga4_properties").select("id")
        .eq("client_id", client_id).eq("access_status", "ok").limit(1).execute()
    ).data
    if not prop:
        return None
    cutoff = date.fromordinal(period_end.toordinal() - _COMPARISON_LOOKBACK_DAYS).isoformat()
    rows = (
        supabase.table("ga4_daily")
        .select("date, sessions, total_users, screen_page_views, conversions, channels")
        .eq("property_id", prop[0]["id"])
        .gte("date", cutoff)
        .execute()
    ).data or []
    if not rows:
        return None

    prev_start, prev_end = previous_period(period_start, period_end)

    def _metric(field: str) -> Optional[dict]:
        by_date = _accum_by_date(rows, field)  # skips null-field rows (e.g. no conversions)
        cur = _sum_between(by_date, period_start, period_end)
        if cur is None:
            return None
        covered = bool(by_date) and min(by_date) <= prev_start
        prev = _sum_between(by_date, prev_start, prev_end) if covered else None
        return {"current": cur, "previous": prev, "change": _pct(cur, prev)}

    # Top channels by sessions over the report period.
    channel_totals: dict[str, int] = {}
    for r in rows:
        try:
            d = date.fromisoformat(str(r.get("date"))[:10])
        except (TypeError, ValueError):
            continue
        if not (period_start < d <= period_end):
            continue
        for name, sess in (r.get("channels") or {}).items():
            channel_totals[name] = channel_totals.get(name, 0) + int(sess or 0)
    total_ch = sum(channel_totals.values())
    channels = [
        {"name": n, "sessions": s, "pct": round(s / total_ch * 100) if total_ch else 0}
        for n, s in sorted(channel_totals.items(), key=lambda kv: kv[1], reverse=True)[:6]
    ]

    sessions = _metric("sessions")
    if not sessions:
        # No visits signal at all — nothing worth a "Website traffic" section.
        return None
    # NOTE: deliberately NOT reporting total_users summed across days. GA4's
    # totalUsers is de-duplicated per day, so summing daily values counts a
    # returning visitor once per day they visit ("visitor-days", not unique
    # visitors) and overstates the number to the client. Sessions and
    # conversions (event counts) ARE additive, so they're safe to sum. True
    # period-unique visitors need a separate window-level report (no date
    # dimension); the per-day total_users column stays in ga4_daily for that
    # future path. See the adversarial review 2026-08-15.
    return {
        "sessions": sessions,
        "conversions": _metric("conversions"),
        "channels": channels,
    }


def _latest_reporting_scan(supabase, client_id: str, on_or_before: date):
    """The newest scheduled (reporting) complete scan created on/before a date."""
    rows = (
        maps_reporting.only_reporting(
            supabase.table("maps_scans").select("id, created_at")
        )
        .eq("client_id", client_id)
        .eq("status", "complete")
        .lt("created_at", (on_or_before + timedelta(days=1)).isoformat())
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    return rows[0] if rows else None


def _scan_presence(supabase, scan_id: str) -> Optional[float]:
    """Overall top-3 local-pack presence % for a scan (share of pins in the top 3)."""
    rows = (
        supabase.table("maps_scan_results").select("top3_pins, total_pins")
        .eq("scan_id", scan_id).execute()
    ).data or []
    total = sum(r.get("total_pins") or 0 for r in rows)
    top3 = sum(r.get("top3_pins") or 0 for r in rows)
    return round(100.0 * top3 / total, 1) if total else None


def _gather_geogrid(supabase, client_id: str, period_start: date, period_end: date) -> Optional[dict]:
    # The client-facing PDF reports the scheduled series only — a one-off run the
    # team did to check something is not this client's local-pack record.
    scan = _latest_reporting_scan(supabase, client_id, period_end)
    if not scan:
        return None
    results = (
        supabase.table("maps_scan_results")
        .select("keyword, average_rank, top3_pins, total_pins, rank_grid, map_image_url, report_weak_locations")
        .eq("scan_id", scan["id"])
        .limit(6)
        .execute()
    ).data or []
    if not results:
        return None
    weak: list[str] = []
    for r in results:
        for city in _weak_area_names(r.get("report_weak_locations")):
            if city not in weak:
                weak.append(city)
    # Local-pack presence this period vs the previous period's scan.
    presence_now = _scan_presence(supabase, scan["id"])
    presence_prev = None
    prev_scan = _latest_reporting_scan(supabase, client_id, period_start)
    if prev_scan and prev_scan["id"] != scan["id"]:
        presence_prev = _scan_presence(supabase, prev_scan["id"])
    return {
        "scan_at": scan.get("created_at"),
        "presence_now": presence_now,
        "presence_prev": presence_prev,
        "keywords": [
            {
                "keyword": r.get("keyword"),
                "average_rank": r.get("average_rank"),
                "top3_pins": r.get("top3_pins"),
                "total_pins": r.get("total_pins"),
                "rank_grid": r.get("rank_grid"),
                # Prefer the saved map PNG (Google tile + numbered pins) inlined as
                # a data URI so the PDF is self-contained; fall back to the SVG grid.
                "map_image": _png_data_uri(r.get("map_image_url")),
            }
            for r in results
        ],
        "weak_areas": weak[:8],
    }


def _png_data_uri(url: Optional[str]) -> Optional[str]:
    """Fetch a stored map PNG and return it as a `data:image/png;base64,...` URI so
    it embeds self-contained in the PDF (no network/expiry at render). Best-effort
    — None on any failure (caller falls back to the SVG grid)."""
    if not url:
        return None
    try:
        import base64  # noqa: PLC0415
        import httpx  # noqa: PLC0415

        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        return "data:image/png;base64," + base64.b64encode(resp.content).decode("ascii")
    except Exception as exc:  # noqa: BLE001 — a missing image just falls back to SVG
        logger.warning("client_report_map_image_fetch_failed", extra={"url": url, "error": str(exc)})
        return None


def _gather_gbp(supabase, client_id: str, client: dict, period_start: date, period_end: date) -> Optional[dict]:
    gbp = client.get("gbp") or {}
    if not (gbp.get("business_name") or gbp.get("place_id") or gbp.get("google_maps_uri")):
        return None
    reviews = gbp.get("reviews") or gbp.get("top_reviews") or []
    texts = []
    for r in reviews[:3]:
        t = r.get("text") if isinstance(r, dict) else (r if isinstance(r, str) else None)
        if t:
            texts.append(t[:240])
    from services.gbp_service import rating_and_review_count

    rating, review_count = rating_and_review_count(gbp)
    return {
        "business_name": gbp.get("business_name"),
        "address": gbp.get("address"),
        "rating": rating,
        "review_count": review_count,
        "top_reviews": texts,
        # New reviews + rating this period vs last period (dated-review count now,
        # exact rating from the snapshot series once it accrues). Best-effort.
        "review_period": _gather_review_period(
            supabase, client_id, gbp, rating, review_count, period_start, period_end
        ),
        # Performance-metric growth (impressions/calls/clicks/directions) — the
        # Phase-2 GBP time-series. Best-effort: absent until GBP metrics ingest
        # is enabled and has data for this client's verified location(s).
        "metrics": _gather_gbp_metric_growth(supabase, client_id, period_end),
    }


def _gather_review_period(supabase, client_id: str, gbp: dict, rating_now, review_count,
                          period_start: date, period_end: date) -> Optional[dict]:
    """Reviews + rating this period vs the previous period. New-review COUNT and
    highlights come from the dated review list (immediate); rating-at-period-start
    prefers the exact snapshot series, falling back to a cumulative-average
    approximation. Always records a fresh snapshot so the exact series builds up.
    Best-effort — returns None when nothing comparable is available."""
    from services import gbp_reviews

    prev_start, _ = previous_period(period_start, period_end)
    reviews = gbp_reviews.fetch_dated_reviews(gbp) if settings.client_report_gbp_reviews_enabled else []
    # Grow the exact review-count/rating series regardless of whether we can render
    # a comparison this time.
    gbp_reviews.record_snapshot(supabase, client_id, review_count, rating_now)

    reviews_this = gbp_reviews.count_in_range(reviews, period_start, period_end) if reviews else None
    reviews_prev = gbp_reviews.count_in_range(reviews, prev_start, period_start) if reviews else None

    rating_prev = None
    snap = gbp_reviews.snapshot_on_or_before(supabase, client_id, period_start)
    if snap and snap.get("rating") is not None:
        rating_prev = float(snap["rating"])          # exact
    elif reviews:
        rating_prev = gbp_reviews.avg_rating_asof(reviews, period_start)  # approximate

    highlights = gbp_reviews.newest_highlights(reviews, period_start, period_end) if reviews else []

    if reviews_this is None and rating_prev is None:
        return None  # nothing comparable yet (fetch unavailable, no snapshot history)
    return {
        "reviews_this": reviews_this,
        "reviews_prev": reviews_prev,
        "rating_now": rating_now,
        "rating_prev": rating_prev,
        "highlights": highlights,
    }


# Human labels for the GBP performance metrics shown in the report. Impression
# sub-types are collapsed into one "Profile views" total for owner-friendliness.
_GBP_IMPRESSION_METRICS = {
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
}
_GBP_METRIC_LABELS = {
    "profile_views": "Profile views",
    "CALL_CLICKS": "Calls",
    "WEBSITE_CLICKS": "Website clicks",
    "BUSINESS_DIRECTION_REQUESTS": "Direction requests",
    "BUSINESS_CONVERSATIONS": "Messages",
}


def _gather_gbp_metric_growth(supabase, client_id: str, period_end: date) -> Optional[dict]:
    """30-day GBP performance growth vs the prior 30 days, per metric, summed
    across the client's verified locations. Returns None when GBP metrics aren't
    enabled or no data exists yet (keeps the report unchanged pre-Phase-2)."""
    if not settings.gbp_metrics_enabled:
        return None
    try:
        from services.gbp_metrics_ingest import compute_metric_growth

        locs = (
            supabase.table("gbp_locations").select("id")
            .eq("client_id", client_id).eq("access_status", "ok").execute()
        ).data or []
        if not locs:
            return None
        loc_ids = [l["id"] for l in locs]
        window = 30
        start = period_end - timedelta(days=window * 2)
        rows = (
            supabase.table("gbp_metric_daily").select("date, metric, value")
            .in_("location_row_id", loc_ids)
            .gte("date", start.isoformat()).lte("date", period_end.isoformat())
            .execute()
        ).data or []
        if not rows:
            return None
        # Collapse the four impression sub-types into one "profile_views" metric
        # before computing growth, so the report shows one headline number.
        folded: list[dict] = []
        for r in rows:
            m = r.get("metric")
            folded.append({**r, "metric": "profile_views" if m in _GBP_IMPRESSION_METRICS else m})
        growth = compute_metric_growth(folded, period_end, window)
        # Render-ready ordered list of labeled metrics that have data.
        items = [
            {"label": _GBP_METRIC_LABELS[key], **growth[key]}
            for key in _GBP_METRIC_LABELS
            if key in growth
        ]
        return {"window_days": window, "items": items} if items else None
    except Exception as exc:
        logger.warning("gbp_metric_growth_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def _gather_work_delivered(supabase, client_id: str, period_start: date, period_end: date) -> Optional[dict]:
    """Content produced for the client during the period: completed pipeline runs
    (blog/service/location) + new Local SEO pages. Head-only count queries; each
    source degrades to 0 independently (never fabricated)."""
    start_iso = period_start.isoformat()
    end_iso = (period_end + timedelta(days=1)).isoformat()
    counts: dict[str, int] = {}
    for ct in ("blog_post", "service_page", "location_page"):
        try:
            # NOT head=True: the pinned postgrest discards the count on HEAD
            # responses (always reads 0); limit(1) keeps the transfer to one row.
            n = (
                supabase.table("runs").select("id", count="exact")
                .eq("client_id", client_id).eq("content_type", ct).eq("status", "complete")
                .gte("created_at", start_iso).lt("created_at", end_iso).limit(1).execute()
            ).count or 0
        except Exception:
            n = 0
        if n:
            counts[ct] = n
    try:
        local = (
            supabase.table("local_seo_pages").select("id", count="exact")
            .eq("client_id", client_id).is_("deleted_at", "null")
            .gte("created_at", start_iso).lt("created_at", end_iso).limit(1).execute()
        ).count or 0
    except Exception:
        local = 0
    if local:
        counts["local_seo_page"] = local
    total = sum(counts.values())
    return {"counts": counts, "total": total} if total else None


def gather_report_data(client_id: str, period_start: date, period_end: date) -> dict:
    """Assemble all available report sections for a client. Raises if the client
    is missing; individual sections degrade to absent on error."""
    supabase = get_supabase()
    crow = (
        supabase.table("clients")
        .select("id, name, website_url, logo_url, gbp")
        .eq("id", client_id)
        .limit(1)
        .execute()
    ).data
    if not crow:
        raise ValueError("client_not_found")
    client = crow[0]
    data: dict = {
        "client": {"name": client.get("name"), "website_url": client.get("website_url"),
                   "logo_url": client.get("logo_url")},
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "agency_name": settings.client_report_agency_name,
        "section_status": {},
    }
    for key, fn in (
        ("goals", lambda: _gather_goals(supabase, client_id, period_start, period_end)),
        ("organic", lambda: _gather_organic(supabase, client_id, period_start, period_end)),
        ("ga4", lambda: _gather_ga4(supabase, client_id, period_start, period_end)),
        ("work_delivered", lambda: _gather_work_delivered(supabase, client_id, period_start, period_end)),
        ("geogrid", lambda: _gather_geogrid(supabase, client_id, period_start, period_end)),
        ("ai_visibility", lambda: _gather_ai_visibility(supabase, client_id, period_start, period_end)),
        ("gbp", lambda: _gather_gbp(supabase, client_id, client, period_start, period_end)),
    ):
        try:
            section = fn()
            if section:
                data[key] = section
                data["section_status"][key] = "ok"
            else:
                data["section_status"][key] = "empty"
        except Exception as exc:
            data["section_status"][key] = "failed"
            logger.warning("report_section_failed", extra={"client_id": client_id, "section": key, "error": str(exc)})
    return data


def _gather_goals(supabase, client_id: str, period_start: date, period_end: date) -> Optional[dict]:
    """Campaign goals assessed as of the report's period end (reuses the canonical
    campaign_goals reader), each annotated with its value at the start of the
    period so the report can show movement since the previous period. None when
    the client has no goals / none are shown."""
    from services import campaign_goals

    goals = campaign_goals.assess_goals(client_id, today=period_end)
    shown = [g for g in goals if g.get("status") in _GOAL_STATUS_CLIENT]
    if not shown:
        return None
    for g in shown:
        try:
            g["previous_value"] = campaign_goals.measure_goal(supabase, client_id, g, period_start)
        except Exception:
            g["previous_value"] = None
    return {"goals": shown}


def _batch_overall_visibility(supabase, client_id: str, batch: str) -> Optional[float]:
    """Overall brand-visibility % for one scan batch (share of engine×keyword
    answers that mention the brand). None when the batch has no non-competitor rows."""
    rows = [
        r for r in (
            supabase.table("brand_mention_history").select("mention_found, is_competitor_scan")
            .eq("client_id", client_id).eq("scan_batch_id", batch).execute()
        ).data or []
        if not r.get("is_competitor_scan")
    ]
    if not rows:
        return None
    found = sum(1 for r in rows if r.get("mention_found"))
    return round(100.0 * found / len(rows), 1)


def _gather_ai_visibility(supabase, client_id: str, period_start: date, period_end: date) -> Optional[dict]:
    """AI-visibility scan for the period: per-engine appearance counts, a per-keyword
    breakdown, and overall visibility this period vs the previous period. None until
    a scan has run (auto-populates once AI Visibility is used for the client)."""
    # Newest NON-competitor batches on/before the period end and the period start
    # (a competitor scan can be the newest rows, so filter it out).
    recent = (
        supabase.table("brand_mention_history").select("scan_batch_id, is_competitor_scan, created_at")
        .eq("client_id", client_id).order("created_at", desc=True).limit(1000).execute()
    ).data or []
    noncomp = [r for r in recent if not r.get("is_competitor_scan")]

    def _batch_before(iso_exclusive: str):
        return next((r["scan_batch_id"] for r in noncomp if str(r.get("created_at")) < iso_exclusive), None)

    batch = _batch_before((period_end + timedelta(days=1)).isoformat())
    if not batch:
        return None
    prev_batch = _batch_before(period_start.isoformat())
    visibility_prev = (
        _batch_overall_visibility(supabase, client_id, prev_batch)
        if prev_batch and prev_batch != batch else None
    )
    rows = [
        r for r in (
            supabase.table("brand_mention_history")
            .select("engine, mention_found, keyword_id, is_competitor_scan")
            .eq("client_id", client_id).eq("scan_batch_id", batch).execute()
        ).data or []
        if not r.get("is_competitor_scan")
    ]
    if not rows:
        return None
    kw_ids = list({r["keyword_id"] for r in rows if r.get("keyword_id")})
    kw_map: dict[str, str] = {}
    if kw_ids:
        for k in (
            supabase.table("brand_tracked_keywords").select("id, keyword")
            .in_("id", kw_ids).execute()
        ).data or []:
            kw_map[k["id"]] = k["keyword"]

    per: dict[str, dict] = {}
    by_kw: dict[str, dict] = {}
    for r in rows:
        e = r.get("engine") or "?"
        pe = per.setdefault(e, {"found": 0, "total": 0})
        pe["total"] += 1
        found = bool(r.get("mention_found"))
        if found:
            pe["found"] += 1
        kid = r.get("keyword_id")
        if kid and kid in kw_map:
            by_kw.setdefault(kid, {"keyword": kw_map[kid], "engines": {}})["engines"][e] = found

    keywords = []
    for b in by_kw.values():
        found_count = sum(1 for v in b["engines"].values() if v)
        keywords.append({**b, "found_count": found_count, "total": len(b["engines"])})
    # Most-visible first; the brand-invisible queries sort to the bottom where the
    # "not yet appearing" note draws the eye.
    keywords.sort(key=lambda k: (-k["found_count"], k["keyword"]))
    total_cells = sum(v["total"] for v in per.values())
    found_cells = sum(v["found"] for v in per.values())
    visibility_now = round(100.0 * found_cells / total_cells, 1) if total_cells else None
    return {
        "engines": {e: f"{v['found']} of {v['total']} answers" for e, v in per.items()},
        "keywords": keywords,
        "visibility_now": visibility_now,
        "visibility_prev": visibility_prev,
    }


# ---------------------------------------------------------------------------
# Executive summary (Phase 4) — one Claude call, positive + owner-friendly.
# ---------------------------------------------------------------------------
_EXEC_SYSTEM = (
    "You are an SEO account manager writing the executive summary of a monthly "
    "report FOR THE BUSINESS OWNER — a smart non-specialist who is not an SEO "
    "professional. Write in plain, warm, jargon-free language: avoid SEO jargon "
    "(SERP, CTR, geo-grid, etc.) or explain it in everyday terms. Be POSITIVE and "
    "upbeat — lead with wins and momentum, and celebrate improvements with their "
    "specific numbers (e.g. 'impressions are up 24% this month'). Base everything "
    "ONLY on the supplied data; never invent numbers. Keep each bullet to one "
    "short, encouraging sentence. 'focus_next' should frame upcoming work as "
    "opportunities, not problems."
)
_EXEC_TOOL = {
    "name": "emit_summary",
    "description": "Emit the positive, owner-friendly executive summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "1–2 sentence upbeat headline of the month's progress."},
            "highlights": {"type": "array", "items": {"type": "string"},
                           "description": "Up to 5 concrete wins, each with its number where available."},
            "focus_next": {"type": "array", "items": {"type": "string"},
                           "description": "Up to 4 opportunities/next steps, framed positively."},
        },
        "required": ["headline", "highlights", "focus_next"],
    },
}


def _gather_exec_inputs(supabase, client_id: str) -> dict:
    """Forward-looking signal for the summary: the current Action Plan (best-effort).
    Kept positive — we surface planned next steps, not raw drop alerts."""
    out: dict = {}
    try:
        plan = (
            supabase.table("reopt_plans").select("summary, items")
            .eq("client_id", client_id).order("created_at", desc=True).limit(1).execute()
        ).data
        if plan:
            out["planned_next_steps"] = [
                {"keyword": a.get("keyword"), "recommendation": a.get("recommendation")}
                for a in (plan[0].get("items") or [])[:6]
            ]
    except Exception as exc:
        logger.warning("report_exec_plan_failed", extra={"client_id": client_id, "error": str(exc)})
    return out


def generate_exec_summary(client_name: Optional[str], period: dict, data: dict, signals: dict) -> Optional[dict]:
    """LLM → {headline, highlights, focus_next} (positive, owner-friendly).

    Best-effort: returns None when no LLM key is set or the call fails, so the
    report still renders without the summary. Runs on Anthropic with automatic
    OpenAI→Gemini fallback on a transient failure."""
    if not (settings.anthropic_api_key or settings.openai_api_key or settings.gemini_api_key):
        return None
    context = {
        "client": client_name,
        "period": period,
        "performance_changes": (data.get("organic") or {}).get("comparisons"),
        "rankings_summary": (data.get("organic") or {}).get("summary"),
        "top_keywords": ((data.get("organic") or {}).get("keywords") or [])[:15],
        "local_maps": {
            "keywords": [
                {"keyword": k.get("keyword"), "average_rank": k.get("average_rank"),
                 "top3_pins": k.get("top3_pins"), "total_pins": k.get("total_pins")}
                for k in ((data.get("geogrid") or {}).get("keywords") or [])
            ],
        },
        # GBP removed from the client PDF report for now — not fed to the exec summary.
        "ai_search_visibility": data.get("ai_visibility"),
        "work_delivered": data.get("work_delivered"),
        **signals,
    }
    try:
        from services import report_llm

        # Runs on Anthropic with automatic OpenAI→Gemini fallback on a transient failure.
        return report_llm.run_forced_tool_sync(
            provider="anthropic",
            model=settings.client_report_health_model,
            max_tokens=settings.client_report_health_max_tokens,
            system=_EXEC_SYSTEM,
            user=json.dumps(context, default=str, ensure_ascii=False),
            tool_name=_EXEC_TOOL["name"],
            tool_description=_EXEC_TOOL["description"],
            input_schema=_EXEC_TOOL["input_schema"],
            log_tag="report_exec_summary",
        ) or None
    except Exception as exc:
        logger.warning("report_exec_summary_failed", extra={"client_name": client_name, "error": str(exc)})
    return None


# ---------------------------------------------------------------------------
# PDF render + store + orchestration (I/O).
# ---------------------------------------------------------------------------
def render_pdf(html: str) -> bytes:
    """HTML → PDF via WeasyPrint. Lazy import: the lib + its system libraries are
    only present in the deployed image (added to the Dockerfile)."""
    from weasyprint import HTML  # noqa: PLC0415

    return HTML(string=html).write_pdf()


def _store_pdf(client_id: str, report_id: str, pdf: bytes) -> tuple[str, Optional[str]]:
    supabase = get_supabase()
    path = f"{client_id}/{report_id}.pdf"
    supabase.storage.from_(_REPORTS_BUCKET).upload(
        path, pdf, {"content-type": "application/pdf", "upsert": "true"}
    )
    return path, _signed_url(path)


def _signed_url(path: str) -> Optional[str]:
    try:
        res = get_supabase().storage.from_(_REPORTS_BUCKET).create_signed_url(path, _SIGNED_URL_TTL)
        return res.get("signedURL") or res.get("signedUrl") if isinstance(res, dict) else None
    except Exception as exc:
        logger.warning("report_sign_url_failed", extra={"path": path, "error": str(exc)})
        return None


# Coverage tokens the API/UI can pass instead of explicit dates. 'all' = since
# the start of the campaign (the client's created_at).
PERIOD_CHOICES = ("30d", "60d", "90d", "120d", "1y", "all")
_PERIOD_DAYS = {"30d": 30, "60d": 60, "90d": 90, "120d": 120, "1y": 365}


def period_start_for(period: Optional[str], campaign_start: Optional[date], today: date) -> Optional[date]:
    """Start date for a coverage token; None means the builder default (30d).
    'all' anchors on the campaign start, falling back to the default window
    when the client's created_at is unknown. Pure."""
    if period == "all":
        return campaign_start or (today - timedelta(days=_DEFAULT_PERIOD_DAYS))
    days = _PERIOD_DAYS.get(period or "")
    return (today - timedelta(days=days)) if days else None


def campaign_start(supabase, client_id: str) -> Optional[date]:
    """The client's created_at date — the suite's 'start of campaign' anchor."""
    rows = (
        supabase.table("clients").select("created_at").eq("id", client_id).limit(1).execute()
    ).data
    raw = rows[0].get("created_at") if rows else None
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _build_ai_visibility_report(client_id: str, period_start: date, period_end: date) -> tuple[str, str]:
    """(html, title) for the ai_visibility report type — the LABS-style
    white-label report folded in as a Client Reporting type (Phase 5, locked
    decision 2026-07-06). brand_report_html builds the body; this pipeline owns
    PDF render, storage and delivery. The standalone POST …/brand/report-html
    stays as the instant in-browser preview/download path."""
    from services import brand_report_html

    # generate_html_report is async for its router; this runs inside the job's
    # worker thread (asyncio.to_thread), where no event loop is running.
    result = asyncio.run(
        brand_report_html.generate_html_report(
            client_id, period_start.isoformat(), period_end.isoformat()
        )
    )
    rows = (
        get_supabase().table("clients").select("name").eq("id", client_id).limit(1).execute()
    ).data
    name = (rows[0].get("name") if rows else None) or "Client"
    return result["html"], f"{name} — AI Visibility Report ({period_end.isoformat()})"


def generate_client_report(
    client_id: str,
    report_type: str = "monthly",
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    report_id: Optional[str] = None,
) -> dict:
    """Gather → HTML → PDF → store → finalize the client_reports row. Sync
    (run via asyncio.to_thread from the async job)."""
    supabase = get_supabase()
    period_end = period_end or date.today()
    period_start = period_start or (period_end - timedelta(days=_DEFAULT_PERIOD_DAYS))

    if report_type == "ai_visibility":
        html, title = _build_ai_visibility_report(client_id, period_start, period_end)
        section_status: dict = {"ai_visibility": "ok"}
    else:
        data = gather_report_data(client_id, period_start, period_end)

        # Phase 4: positive, owner-friendly executive summary (best-effort; first section).
        try:
            signals = _gather_exec_inputs(supabase, client_id)
            summary = generate_exec_summary(data["client"].get("name"), data["period"], data, signals)
            if summary:
                data["exec"] = summary
                data["section_status"]["exec"] = "ok"
            else:
                data["section_status"]["exec"] = "empty"
        except Exception as exc:
            data["section_status"]["exec"] = "failed"
            logger.warning("report_exec_failed", extra={"client_id": client_id, "error": str(exc)})

        title = f"{data['client'].get('name') or 'Client'} — SEO Report ({period_end.isoformat()})"
        html = build_report_html(data)
        section_status = data["section_status"]

    pdf = render_pdf(html)

    if report_id is None:
        report_id = (
            supabase.table("client_reports")
            .insert({"client_id": client_id, "report_type": report_type,
                     "period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
                     "status": "running"})
            .execute()
        ).data[0]["id"]

    path, url = _store_pdf(client_id, report_id, pdf)
    supabase.table("client_reports").update({
        "status": "complete", "storage_path": path, "pdf_url": url,
        "sections": section_status, "title": title, "completed_at": "now()",
    }).eq("id", report_id).execute()
    return {"report_id": report_id, "pdf_url": url, "sections": section_status}


def enqueue_client_report(
    client_id: str, report_type: str = "monthly",
    period_start: Optional[date] = None, period_end: Optional[date] = None,
    deliver: bool = False,
    period: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    """Create a pending client_reports row + its async job. Returns the report id.
    deliver=True runs Phase 5 delivery (email + Drive copy per the client's
    report settings) after the render — scheduled runs always deliver; on-demand
    generation opts in. `period` is a PERIOD_CHOICES coverage token resolved to
    period_start here (explicit dates win over it). ``user_id`` (the initiator)
    drives the Activity indicator + completion notification."""
    supabase = get_supabase()
    if period and period_start is None:
        today = period_end or date.today()
        anchor = campaign_start(supabase, client_id) if period == "all" else None
        period_start = period_start_for(period, anchor, today)
        period_end = period_end or today
    row = (
        supabase.table("client_reports")
        .insert({
            "client_id": client_id, "report_type": report_type,
            "period_start": period_start.isoformat() if period_start else None,
            "period_end": period_end.isoformat() if period_end else None,
            "status": "pending",
        })
        .execute()
    ).data[0]
    supabase.table("async_jobs").insert({
        "job_type": "client_report", "entity_id": client_id,
        "payload": {"client_id": client_id, "report_id": row["id"], "report_type": report_type,
                    "period_start": row.get("period_start"), "period_end": row.get("period_end"),
                    "deliver": deliver, "user_id": user_id},
    }).execute()
    return row["id"]


async def run_client_report_job(job: dict) -> None:
    """async_jobs handler for job_type='client_report'."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    report_id = payload.get("report_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not (client_id and report_id):
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id/report_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    ps = payload.get("period_start")
    pe = payload.get("period_end")
    try:
        result = await asyncio.to_thread(
            generate_client_report,
            client_id,
            payload.get("report_type", "monthly"),
            date.fromisoformat(ps) if ps else None,
            date.fromisoformat(pe) if pe else None,
            report_id,
        )
    except Exception as exc:
        logger.warning("client_report_job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("client_reports").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", report_id).execute()
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    if payload.get("deliver"):
        # Phase 5: email + Drive copy per the client's report settings.
        # Best-effort — deliver_report never raises; outcomes land on the row.
        from services.client_report_schedule import deliver_report

        result["delivery"] = await deliver_report(report_id)
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
