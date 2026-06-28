"""Client Reporting module — generated client-facing PDF reports.

Phase 0–1: assemble a per-client report from data AR Tools already has (organic
rankings, Maps geo-grids, GBP profile/reviews), render it to a **PDF**
(WeasyPrint, HTML/CSS → PDF), store it in the private `reports` storage bucket,
and record a `client_reports` row. Later phases add GA4 + GBP-performance
(Phase 2), Asana (Phase 3), a campaign-health narrative (Phase 4), and
email + Drive-folder delivery + scheduling (Phase 5).

Split for testability: data gathering + the pure HTML/SVG builders are
import-light and unit-tested; `render_pdf` is a thin WeasyPrint wrapper (lazy
import — the lib + its system libs live only in the deployed image), and the
job/store do I/O.
"""

from __future__ import annotations

import asyncio
import html as _html
import logging
from datetime import date, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_REPORTS_BUCKET = "reports"
_SIGNED_URL_TTL = 60 * 60 * 24 * 7  # 7 days
_MAX_KEYWORDS = 40
_DEFAULT_PERIOD_DAYS = 30


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


def _section_organic(data: dict) -> str:
    o = data.get("organic")
    if not o or not o.get("keywords"):
        return ""
    rows = []
    for k in o["keywords"]:
        rank = k.get("current_rank")
        rank_txt = "—" if rank is None else (f"{rank}" if rank else "—")
        rows.append(
            f"<tr><td>{_esc(k.get('keyword'))}</td>"
            f"<td class='num'>{_esc(rank_txt)}</td>"
            f"<td class='num'>{_esc(_fmt_pos(k.get('avg_30d')))}</td>"
            f"<td>{svg_sparkline(k.get('sparkline') or [])}</td></tr>"
        )
    s = o.get("summary", {})
    summary = (
        f"<p class='lead'>{s.get('tracked', 0)} tracked keywords · "
        f"{s.get('top10', 0)} in the top 10 · {s.get('improved', 0)} improved, "
        f"{s.get('declined', 0)} declined this period.</p>"
    )
    return (
        "<section><h2>Organic rankings</h2>" + summary
        + "<table><thead><tr><th>Keyword</th><th class='num'>Current</th>"
        "<th class='num'>30-day avg</th><th>Trend</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table></section>"
    )


def _section_geogrid(data: dict) -> str:
    g = data.get("geogrid")
    if not g or not g.get("keywords"):
        return ""
    cards = []
    for k in g["keywords"]:
        avg = _fmt_pos(k.get("average_rank"))
        cards.append(
            "<div class='grid-card'>"
            f"<div class='grid-kw'>{_esc(k.get('keyword'))}</div>"
            f"<div>{svg_geogrid(k.get('rank_grid'))}</div>"
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
        "<section><h2>Local pack / Maps coverage</h2>" + weak_html + legend
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
    return (
        "<section><h2>Google Business Profile</h2>"
        f"<p>{_esc(b.get('business_name'))}{(' · ' + _esc(b.get('address'))) if b.get('address') else ''}</p>"
        + rating_html + reviews_html + "</section>"
    )


def _fmt_pos(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{round(float(v), 1):g}"
    except (TypeError, ValueError):
        return "—"


def build_report_html(data: dict) -> str:
    """Assemble the full report HTML document (pure). WeasyPrint renders this."""
    client = data.get("client", {})
    period = data.get("period", {})
    sections = "".join(
        s for s in (_section_organic(data), _section_geogrid(data), _section_gbp(data)) if s
    )
    if not sections:
        sections = "<section><p class='lead'>No report data is available for this client yet.</p></section>"
    logo = client.get("logo_url")
    logo_html = f'<img class="logo" src="{_esc(logo)}"/>' if logo else ""
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
<main>{sections}</main>
<footer>Generated by AR Tools · {_esc(period.get('end'))}</footer>
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
table { width:100%; border-collapse:collapse; margin-top:8px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid #eef2f6; vertical-align:middle; }
th { font-size:9px; text-transform:uppercase; letter-spacing:.04em; color:#94a3b8; }
td.num, th.num { text-align:right; }
.grid-cards { display:flex; flex-wrap:wrap; gap:14px; margin-top:10px; }
.grid-card { border:1px solid #e2e8f0; border-radius:8px; padding:10px; text-align:center; }
.grid-kw { font-weight:600; margin-bottom:6px; }
.grid-meta { color:#64748b; font-size:10px; margin-top:6px; }
.legend { color:#64748b; font-size:9px; }
.legend .sw { display:inline-block; width:9px; height:9px; border-radius:2px; margin:0 3px 0 10px; vertical-align:middle; }
.reviews { color:#334155; } .reviews li { margin-bottom:4px; }
footer { margin-top:24px; padding-top:8px; border-top:1px solid #e2e8f0; color:#94a3b8; font-size:9px; text-align:center; }
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
    cutoff = date.fromordinal(today.toordinal() - 90).isoformat()
    for r in (
        supabase.table("rank_keyword_metrics")
        .select("keyword_id, date, gsc_position, tracked_rank")
        .in_("keyword_id", kw_ids)
        .gte("date", cutoff)
        .execute()
    ).data or []:
        metrics.setdefault(r["keyword_id"], []).append(r)

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
            "sparkline": s.get("sparkline") or [],
        })
    return {
        "keywords": keywords,
        "summary": {"tracked": len(keywords), "top10": top10, "improved": improved, "declined": declined},
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
        .select("keyword, average_rank, top3_pins, total_pins, rank_grid, report_weak_locations")
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
            }
            for r in results
        ],
        "weak_areas": weak[:8],
    }


def _gather_gbp(client: dict) -> Optional[dict]:
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
    }


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
        "section_status": {},
    }
    for key, fn in (
        ("organic", lambda: _gather_organic(supabase, client_id, period_end)),
        ("geogrid", lambda: _gather_geogrid(supabase, client_id)),
        ("gbp", lambda: _gather_gbp(client)),
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

    data = gather_report_data(client_id, period_start, period_end)
    title = f"{data['client'].get('name') or 'Client'} — SEO Report ({period_end.isoformat()})"
    pdf = render_pdf(build_report_html(data))

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
        "sections": data["section_status"], "title": title, "completed_at": "now()",
    }).eq("id", report_id).execute()
    return {"report_id": report_id, "pdf_url": url, "sections": data["section_status"]}


def enqueue_client_report(
    client_id: str, report_type: str = "monthly",
    period_start: Optional[date] = None, period_end: Optional[date] = None,
) -> str:
    """Create a pending client_reports row + its async job. Returns the report id."""
    supabase = get_supabase()
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
                    "period_start": row.get("period_start"), "period_end": row.get("period_end")},
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
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
