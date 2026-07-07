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
    # Trim the (up to 40) tracked keywords to the handful that moved most — a
    # business owner wants the story, not a spreadsheet. Biggest absolute change
    # first; fall back to the first few if nothing has a measurable delta yet.
    movers = sorted(kws, key=lambda k: abs(k.get("change") or 0), reverse=True)
    top = [k for k in movers if k.get("change")][:_TOP_MOVERS] or kws[:_TOP_MOVERS]
    rows = []
    for k in top:
        rank = k.get("current_rank")
        rank_txt = "—" if rank is None else (f"{rank}" if rank else "—")
        rows.append(
            f"<tr><td>{_esc(k.get('keyword'))}</td>"
            f"<td class='num'>{_esc(rank_txt)}</td>"
            f"<td class='num pos'>{_esc(_fmt_positions(k.get('change')))}</td>"
            f"<td>{svg_sparkline(k.get('sparkline') or [])}</td></tr>"
        )
    s = o.get("summary", {})
    extra = max((s.get("tracked", 0) or 0) - len(top), 0)
    more = f" The remaining {extra} are tracked too — full list available on request." if extra else ""
    summary = (
        f"<p class='note'>Where your website shows up in Google for the searches that "
        f"matter to your business. Showing your biggest movers this period.</p>"
        f"<p class='lead'>{s.get('tracked', 0)} tracked keywords · "
        f"{s.get('top10', 0)} on page 1 · {s.get('improved', 0)} improving, "
        f"{s.get('declined', 0)} to watch.{more}</p>"
    )
    return (
        "<section><h2>Organic rankings</h2>" + summary
        + "<table><thead><tr><th>Keyword</th><th class='num'>Current</th>"
        "<th class='num'>Movement</th><th>Trend</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table></section>"
    )


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
    weak = g.get("weak_areas") or []
    weak_html = (
        f"<p class='lead'>Weakest nearby areas: {_esc(', '.join(weak))}.</p>" if weak else ""
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
        + weak_html + legend
        + "<div class='grid-cards'>" + "".join(cards) + "</div></section>"
    )


def _section_gbp(data: dict) -> str:
    b = data.get("gbp")
    if not b:
        return ""
    reviews = "".join(
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
        + rating_html + reviews_html + metrics_html + "</section>"
    )


# --- Period comparisons (30-day / 90-day / since-start) — pure ---------------
def _window_sum(by_date: dict, end: date, days: int) -> Optional[float]:
    start = end - timedelta(days=days)
    vals = [v for d, v in by_date.items() if start < d <= end]
    return sum(vals) if vals else None


def _window_avg(by_date: dict, end: date, days: int) -> Optional[float]:
    start = end - timedelta(days=days)
    vals = [v for d, v in by_date.items() if start < d <= end]
    return sum(vals) / len(vals) if vals else None


def _pct(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    if curr is None or not prev:
        return None
    return round((curr - prev) / prev * 100, 1)


def _volume_changes(by_date: dict, today: date, earliest: date) -> Optional[dict]:
    cur = _window_sum(by_date, today, 30)
    if cur is None:
        return None
    return {"current": cur, "changes": {
        "30d": _pct(cur, _window_sum(by_date, today - timedelta(days=30), 30)),
        "90d": _pct(cur, _window_sum(by_date, today - timedelta(days=90), 30)),
        "start": _pct(cur, _window_sum(by_date, earliest + timedelta(days=30), 30)),
    }}


def _rank_changes(by_date: dict, today: date, earliest: date) -> Optional[dict]:
    cur = _window_avg(by_date, today, 7)
    if cur is None:
        return None

    def improvement(prev):  # rank: lower is better → positive = positions gained
        return None if prev is None else round(prev - cur, 1)

    return {"current": cur, "changes_positions": {
        "30d": improvement(_window_avg(by_date, today - timedelta(days=30), 7)),
        "90d": improvement(_window_avg(by_date, today - timedelta(days=90), 7)),
        "start": improvement(_window_avg(by_date, earliest + timedelta(days=7), 7)),
    }}


def build_comparisons(metric_rows: list[dict], today: date) -> Optional[dict]:
    """30/90/since-start changes for impressions, organic clicks, and avg ranking.

    Pure. Volume metrics compare the trailing-30-day total to the same window 30/90
    days ago and to the first 30 days of data; ranking compares the trailing-7-day
    average. A metric/window with no data is omitted (None) — never fabricated."""
    impr, clk, rsum, rn = {}, {}, {}, {}
    dates: set = set()
    for r in metric_rows:
        ds = r.get("date")
        try:
            d = date.fromisoformat(str(ds)[:10])
        except (TypeError, ValueError):
            continue
        dates.add(d)
        if r.get("impressions") is not None:
            impr[d] = impr.get(d, 0) + (r["impressions"] or 0)
        if r.get("clicks") is not None:
            clk[d] = clk.get(d, 0) + (r["clicks"] or 0)
        pos = r.get("gsc_position")
        if pos is None:
            pos = r.get("tracked_rank")
        if pos is not None:
            rsum[d] = rsum.get(d, 0) + pos
            rn[d] = rn.get(d, 0) + 1
    if not dates:
        return None
    earliest = min(dates)
    rank = {d: rsum[d] / rn[d] for d in rsum}
    out: dict = {}
    if (v := _volume_changes(impr, today, earliest)):
        out["impressions"] = v
    if (v := _volume_changes(clk, today, earliest)):
        out["clicks"] = v
    if (v := _rank_changes(rank, today, earliest)):
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


def _perf_row(label, current, c30, c90, cstart) -> str:
    return (f"<tr><td>{_esc(label)}</td><td class='num'>{_esc(current)}</td>"
            f"<td class='num pos'>{_esc(c30)}</td><td class='num pos'>{_esc(c90)}</td>"
            f"<td class='num pos'>{_esc(cstart)}</td></tr>")


def _section_performance(data: dict) -> str:
    comp = (data.get("organic") or {}).get("comparisons")
    if not comp:
        return ""
    rows = []
    for key, label, fmt_val, change_key, fmt_change in (
        ("impressions", "Impressions", _fmt_int, "changes", _fmt_pct),
        ("clicks", "Organic clicks", _fmt_int, "changes", _fmt_pct),
        ("rank", "Average ranking", _fmt_pos, "changes_positions", _fmt_positions),
    ):
        m = comp.get(key)
        if not m or m.get("current") is None:
            continue
        ch = m.get(change_key, {})
        rows.append(_perf_row(label, fmt_val(m["current"]),
                              fmt_change(ch.get("30d")), fmt_change(ch.get("90d")), fmt_change(ch.get("start"))))
    if not rows:
        return ""
    return (
        "<section><h2>Performance highlights</h2>"
        "<p class='note'>The big-picture trend: how many people are finding you in "
        "search and how your rankings are moving over time.</p>"
        "<table><thead><tr><th>Metric</th><th class='num'>Last 30 days</th>"
        "<th class='num'>vs 30 days ago</th><th class='num'>vs 90 days ago</th>"
        "<th class='num'>Since we started</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table></section>"
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
        "<p class='lead'>How often the brand shows up when AI assistants answer your keywords:</p>"
        f"<ul class='reviews'>{items}</ul></section>"
    )


_ENGINE_LABELS = {
    "chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini",
    "perplexity": "Perplexity", "google_ai_overview": "Google AI Overviews",
    "google_ai_mode": "Google AI Mode",
}


def _section_exec(data: dict) -> str:
    e = data.get("exec")
    if not e:
        return ""

    def _list(title, items):
        lis = "".join(f"<li>{_esc(x)}</li>" for x in (items or [])[:5])
        return f"<div class='hcol'><h4>{title}</h4><ul>{lis}</ul></div>" if lis else ""

    cols = _list("Highlights", e.get("highlights")) + _list("What we’re focused on next", e.get("focus_next"))
    return (
        "<section class='exec'><h2>Executive summary</h2>"
        f"<p class='headline'>{_esc(e.get('headline'))}</p>"
        f"<div class='hcols'>{cols}</div></section>"
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
    impr_start = (impr.get("changes") or {}).get("start")
    if impr_start is not None:
        cards.append(_kpi("Search visibility", _fmt_pct(impr_start), "since we started"))
    rank = comp.get("rank") or {}
    rank_start = (rank.get("changes_positions") or {}).get("start")
    if rank_start and rank_start > 0:
        cards.append(_kpi("Ranking gains", f"▲ {round(rank_start, 1):g}", "positions, since we started"))
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
        s for s in (_section_exec(data), _section_performance(data),
                    _section_work_delivered(data), _section_organic(data),
                    _section_geogrid(data), _section_ai_visibility(data), _section_gbp(data)) if s
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
def _gather_organic(supabase, client_id: str, today: date) -> Optional[dict]:
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
    # Full history (capped) so the since-start comparison has a baseline.
    cutoff = date.fromordinal(today.toordinal() - _COMPARISON_LOOKBACK_DAYS).isoformat()
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
            metrics.get(k["id"], []), today, settings.rank_gsc_coverage_days
        )
        rank = s.get("today_rank")
        if isinstance(rank, (int, float)) and rank <= 10:
            top10 += 1
        if s.get("direction") == "up":
            improved += 1
        elif s.get("direction") == "down":
            declined += 1
        keywords.append({
            "keyword": k["keyword"],
            "current_rank": rank,
            "avg_30d": s.get("avg_30"),
            "change": _keyword_change(s),
            "sparkline": s.get("sparkline") or [],
        })
    return {
        "keywords": keywords,
        "summary": {"tracked": len(keywords), "top10": top10, "improved": improved, "declined": declined},
        "comparisons": build_comparisons(flat_rows, today),
    }


def _gather_geogrid(supabase, client_id: str) -> Optional[dict]:
    scan = (
        supabase.table("maps_scans")
        .select("id, created_at")
        .eq("client_id", client_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not scan:
        return None
    results = (
        supabase.table("maps_scan_results")
        .select("keyword, average_rank, top3_pins, total_pins, rank_grid, map_image_url, report_weak_locations")
        .eq("scan_id", scan[0]["id"])
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
    return {
        "scan_at": scan[0].get("created_at"),
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


def _gather_gbp(supabase, client_id: str, client: dict, period_end: date) -> Optional[dict]:
    gbp = client.get("gbp") or {}
    if not (gbp.get("business_name") or gbp.get("place_id")):
        return None
    reviews = gbp.get("reviews") or gbp.get("top_reviews") or []
    texts = []
    for r in reviews[:3]:
        t = r.get("text") if isinstance(r, dict) else (r if isinstance(r, str) else None)
        if t:
            texts.append(t[:240])
    return {
        "business_name": gbp.get("business_name"),
        "address": gbp.get("address"),
        "rating": gbp.get("rating"),
        "review_count": gbp.get("review_count") or gbp.get("reviews_count"),
        "top_reviews": texts,
        # Performance-metric growth (impressions/calls/clicks/directions) — the
        # Phase-2 GBP time-series. Best-effort: absent until GBP metrics ingest
        # is enabled and has data for this client's verified location(s).
        "metrics": _gather_gbp_metric_growth(supabase, client_id, period_end),
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
            n = (
                supabase.table("runs").select("id", count="exact", head=True)
                .eq("client_id", client_id).eq("content_type", ct).eq("status", "complete")
                .gte("created_at", start_iso).lt("created_at", end_iso).execute()
            ).count or 0
        except Exception:
            n = 0
        if n:
            counts[ct] = n
    try:
        local = (
            supabase.table("local_seo_pages").select("id", count="exact", head=True)
            .eq("client_id", client_id).is_("deleted_at", "null")
            .gte("created_at", start_iso).lt("created_at", end_iso).execute()
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
        ("organic", lambda: _gather_organic(supabase, client_id, period_end)),
        ("work_delivered", lambda: _gather_work_delivered(supabase, client_id, period_start, period_end)),
        ("geogrid", lambda: _gather_geogrid(supabase, client_id)),
        ("ai_visibility", lambda: _gather_ai_visibility(supabase, client_id)),
        ("gbp", lambda: _gather_gbp(supabase, client_id, client, period_end)),
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


def _gather_ai_visibility(supabase, client_id: str) -> Optional[dict]:
    """Latest AI-visibility scan, per-engine appearance counts. None until a scan
    has run (auto-populates once AI Visibility is used for the client)."""
    newest = (
        supabase.table("brand_mention_history").select("scan_batch_id")
        .eq("client_id", client_id).order("created_at", desc=True).limit(1).execute()
    ).data
    if not newest:
        return None
    rows = (
        supabase.table("brand_mention_history").select("engine, mention_found")
        .eq("client_id", client_id).eq("scan_batch_id", newest[0]["scan_batch_id"]).execute()
    ).data or []
    if not rows:
        return None
    per: dict[str, dict] = {}
    for r in rows:
        e = per.setdefault(r.get("engine") or "?", {"found": 0, "total": 0})
        e["total"] += 1
        if r.get("mention_found"):
            e["found"] += 1
    return {"engines": {e: f"{v['found']} of {v['total']} answers" for e, v in per.items()}}


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
    """Claude → {headline, highlights, focus_next} (positive, owner-friendly).

    Best-effort: returns None when the Anthropic key is unset or the call fails, so
    the report still renders without the summary."""
    if not settings.anthropic_api_key:
        return None
    import anthropic  # noqa: PLC0415

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
        "google_business_profile": data.get("gbp"),
        "ai_search_visibility": data.get("ai_visibility"),
        "work_delivered": data.get("work_delivered"),
        **signals,
    }
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=_LLM_TIMEOUT)
        resp = client.messages.create(
            model=settings.client_report_health_model,
            max_tokens=settings.client_report_health_max_tokens,
            system=_EXEC_SYSTEM,
            tools=[_EXEC_TOOL],
            tool_choice={"type": "tool", "name": "emit_summary"},
            messages=[{"role": "user", "content": json.dumps(context, default=str, ensure_ascii=False)}],
        )
        for b in resp.content:
            if getattr(b, "type", None) == "tool_use" and b.name == "emit_summary":
                return b.input or None
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
) -> str:
    """Create a pending client_reports row + its async job. Returns the report id.
    deliver=True runs Phase 5 delivery (email + Drive copy per the client's
    report settings) after the render — scheduled runs always deliver; on-demand
    generation opts in. `period` is a PERIOD_CHOICES coverage token resolved to
    period_start here (explicit dates win over it)."""
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
                    "deliver": deliver},
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
