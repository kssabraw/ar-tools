"""AI Visibility — LABS-style white-label HTML report (client-facing).

The self-contained HTML visibility report ported from labs.bfeai's
reports/generate route (same section order + print-to-PDF CSS), restyled to the
suite palette (indigo, suite health bands). Aggregates brand_mention_history
over a date range (LABS semantics — every completed scan cell in the window),
unlike the Google-Doc report (services/brand_report.py) which snapshots one
batch. Both paths coexist: this returns HTML for the in-app preview /
download / print; the Doc report keeps publishing to Drive.

Sections (LABS order): white-label header · brand H1 · business profile +
tracked keywords · health-score gradient card · performance by engine ·
keyword performance · competitor benchmarking · lead valuation · footer.
Lead valuation reads the shared keyword_market cache only (never a live
DataForSEO call — report generation stays fast; the Lead Valuation card is
what populates the cache).
"""

from __future__ import annotations

import html as html_mod
import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services.brand_scan import ENGINE_ORDER
from services.brand_report import ENGINE_LABELS
from services.brand_service import _safe

logger = logging.getLogger("brand_report_html")

# Hard ceiling on mention rows aggregated into one report. Fetched in pages;
# a range that exceeds it renders with an explicit truncation note instead of
# silently reporting wrong totals.
_MAX_REPORT_ROWS = 20000
_PAGE_SIZE = 1000

# ── suite palette (LABS layout, AR Tools colors) ─────────────────────────────
_BRAND = "#4f46e5"          # indigo-600 (in place of LABS' purple #533577)
_BRAND_GRADIENT_TO = "#818cf8"
_H2_UNDERLINE = "#c7d2fe"
_TEXT = "#1f2937"
_MUTED = "#6b7280"
_FAINT = "#94a3b8"
_BOX = "#f8fafc"
_TABLE_HEAD = "#f1f5f9"
_CELL_BORDER = "#e2e8f0"
_YOU_HIGHLIGHT = "#f0fdf4"
_RED = "#b91c1c"
_RED_BG = "#fef2f2"
_RED_BORDER = "#fecaca"


def _esc(v) -> str:
    return html_mod.escape(str(v)) if v is not None else ""


def score_color(score: float) -> str:
    if score >= 70:
        return "#15803d"
    if score >= 40:
        return "#b45309"
    return _RED


def score_label(score: float) -> str:
    if score >= 70:
        return "Healthy Visibility"
    if score >= 40:
        return "Partial Visibility"
    return "Critically Invisible"


def health_score(visibility_pct: float | None, avg_confidence: float | None) -> int | None:
    """LABS formula: visibility share (0-100) x 0.7 + avg confidence (0-1) x 30."""
    if visibility_pct is None:
        return None
    return max(0, min(100, round(visibility_pct * 0.7 + (avg_confidence or 0.0) * 30)))


# ── pure aggregation ─────────────────────────────────────────────────────────
def aggregate_range(rows: list[dict], keyword_labels: dict[str, str]) -> dict:
    """Roll completed mention rows in a date range into the report figures.
    Pure. Every scan cell counts (no per-cell dedup — LABS semantics)."""
    engines = {e: {"scans": 0, "mentions": 0} for e in ENGINE_ORDER}
    keywords: dict[str, dict] = {}
    competitors: dict[str, dict] = {}
    total = found = 0
    confs: list[float] = []

    for r in rows:
        if r.get("status") != "completed":
            continue
        eng = r.get("engine")
        hit = bool(r.get("mention_found"))
        total += 1
        found += 1 if hit else 0
        if r.get("confidence_score") is not None:
            confs.append(float(r["confidence_score"]))
        if eng in engines:
            engines[eng]["scans"] += 1
            engines[eng]["mentions"] += 1 if hit else 0
        label = keyword_labels.get(r.get("keyword_id"), "(removed keyword)")
        kw = keywords.setdefault(label, {"scans": 0, "mentions": 0})
        kw["scans"] += 1
        kw["mentions"] += 1 if hit else 0
        for comp in r.get("competitor_results") or []:
            name = comp.get("name")
            if not name:
                continue
            agg = competitors.setdefault(name, {"scans": 0, "mentions": 0})
            agg["scans"] += 1
            agg["mentions"] += 1 if comp.get("found") else 0

    def pct(m, s):
        return round(100.0 * m / s, 1) if s else 0.0

    visibility = pct(found, total) if total else None
    avg_conf = sum(confs) / len(confs) if confs else None
    return {
        "totals": {
            "scans": total,
            "mentions": found,
            "visibility_pct": visibility,
            "avg_confidence": avg_conf,
            "health_score": health_score(visibility, avg_conf),
        },
        "engines": [
            {"engine": e, "label": ENGINE_LABELS.get(e, e), "scans": v["scans"],
             "mentions": v["mentions"], "pct": pct(v["mentions"], v["scans"])}
            for e, v in engines.items() if v["scans"] > 0
        ],
        "keywords": [
            {"keyword": k, "scans": v["scans"], "mentions": v["mentions"], "pct": pct(v["mentions"], v["scans"])}
            for k, v in sorted(keywords.items())
        ],
        "competitors": [
            {"name": n, "scans": v["scans"], "mentions": v["mentions"], "pct": pct(v["mentions"], v["scans"])}
            for n, v in sorted(competitors.items(), key=lambda kv: -pct(kv[1]["mentions"], kv[1]["scans"]))
        ],
    }


def build_lead_valuation(keyword_stats: list[dict], market_by_kw: dict[str, dict]) -> dict | None:
    """Per keyword: volume x CPC x visibility gap (share of scanned cells where
    the brand wasn't found). None when no keyword has market data."""
    rows = []
    for k in keyword_stats:
        m = market_by_kw.get(k["keyword"].lower()) or {}
        vol, cpc = m.get("search_volume"), m.get("cpc")
        if vol is None or cpc is None or not k["scans"]:
            continue
        gap = 1 - k["mentions"] / k["scans"]
        rows.append({"keyword": k["keyword"], "volume": vol, "cpc": float(cpc), "gap": gap,
                     "cost": float(vol) * float(cpc) * gap})
    if not rows:
        return None
    total = sum(r["cost"] for r in rows)
    return {
        "total": round(total),
        "avg_cpc": round(sum(r["cpc"] for r in rows) / len(rows), 2),
        "monthly_searches": sum(r["volume"] for r in rows),
        "gap_pct": round(100 * sum(r["gap"] for r in rows) / len(rows)),
        "rows": sorted(rows, key=lambda r: -r["cost"]),
    }


# ── HTML rendering (pure) ────────────────────────────────────────────────────
_TABLE = f'width:100%;border-collapse:collapse;margin-bottom:24px;font-size:13px'
_TH = f'border:1px solid {_CELL_BORDER};padding:10px 12px;text-align:left'
_TD = f'border:1px solid {_CELL_BORDER};padding:10px 12px'


def _h2(title: str) -> str:
    return (f'<h2 style="color:{_BRAND};font-size:18px;border-bottom:2px solid {_H2_UNDERLINE};'
            f'padding-bottom:8px;margin:28px 0 14px">{_esc(title)}</h2>')


def _pct_span(p: float) -> str:
    return f'<span style="color:{score_color(p)};font-weight:600">{p:g}%</span>'


def render_html(*, client: dict, agency_name: str, date_range_label: str,
                tracked_keywords: list[dict], data: dict, valuation: dict | None,
                generated_on: str) -> str:
    """The full standalone report document. Pure string building, all inline
    CSS (it must survive being saved/emailed/printed on its own)."""
    totals = data["totals"]
    gbp = client.get("gbp") or {}

    # 1 — white-label header
    parts = [f'''<div style="display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px solid {_BRAND};padding-bottom:14px;margin-bottom:24px">
  <div style="font-size:18px;font-weight:bold;color:{_BRAND}">{_esc(agency_name)}</div>
  <div style="text-align:right">
    <div style="font-size:12px;color:{_MUTED}">AI Visibility Report</div>
    <div style="font-size:14px;font-weight:600">{_esc(date_range_label)}</div>
  </div>
</div>''']

    # 2 — brand H1
    parts.append(f'<h1 style="color:{_BRAND};font-size:28px;margin:0 0 26px">{_esc(client.get("name") or "")}</h1>')

    # 3 — business profile & tracked keywords
    parts.append(_h2("Business Profile & Tracked Keywords"))  # _h2 escapes
    profile_bits = []
    if gbp.get("address"):
        profile_bits.append(f'<div><strong>Address:</strong> {_esc(gbp["address"])}</div>')
    if client.get("website_url"):
        url = _esc(client["website_url"])
        profile_bits.append(f'<div><strong>Website:</strong> <a href="{url}" style="color:{_BRAND}">{url}</a></div>')
    if gbp.get("gbp_rating") is not None:
        reviews = f' ({int(gbp["gbp_review_count"])} reviews)' if gbp.get("gbp_review_count") is not None else ""
        profile_bits.append(f'<div><strong>Google Rating:</strong> {_esc(gbp["gbp_rating"])} ★{_esc(reviews)}</div>')
    if profile_bits:
        parts.append(f'<div style="background:{_BOX};border-radius:8px;padding:16px;line-height:2;font-size:13px;margin-bottom:16px">{"".join(profile_bits)}</div>')

    if tracked_keywords:
        by_cat: dict[str, list[dict]] = {}
        for k in tracked_keywords:
            by_cat.setdefault(k.get("category") or "General", []).append(k)
        kw_rows = []
        for cat in sorted(by_cat):
            kw_rows.append(f'<tr><td colspan="2" style="{_TD};background:{_TABLE_HEAD};font-weight:600;color:{_BRAND}">{_esc(cat)}</td></tr>')
            for k in by_cat[cat]:
                status = "Active" if k.get("is_active") else "Paused"
                kw_rows.append(f'<tr><td style="{_TD};padding-left:24px">{_esc(k["keyword"])}</td>'
                               f'<td style="{_TD};color:{_MUTED};text-align:center">{status}</td></tr>')
        parts.append(f'''<table style="{_TABLE}">
<thead><tr><th style="{_TH};background:{_BRAND};color:#fff">Keyword</th><th style="{_TH};background:{_BRAND};color:#fff;width:100px;text-align:center">Status</th></tr></thead>
<tbody>{"".join(kw_rows)}</tbody></table>''')

    # 4 — health score gradient card
    hs = totals["health_score"]
    hs_num = _esc(hs) if hs is not None else "—"
    hs_label = score_label(hs) if hs is not None else "No completed scans in this range"
    vis = f'{totals["visibility_pct"]:g}%' if totals["visibility_pct"] is not None else "—"
    parts.append(f'''<div style="background:linear-gradient(135deg,{_BRAND} 0%,{_BRAND_GRADIENT_TO} 100%);border-radius:12px;padding:30px;color:#fff;display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
  <div>
    <div style="font-size:16px;opacity:0.9">Global Health Score</div>
    <div style="font-size:64px;font-weight:bold;line-height:1.1">{hs_num}</div>
    <div style="font-size:14px">{_esc(hs_label)}</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:13px;opacity:0.9">Visibility Share</div>
    <div style="font-size:32px;font-weight:bold">{vis}</div>
    <div style="font-size:13px;opacity:0.9;margin-top:10px">Total Scans</div>
    <div style="font-size:32px;font-weight:bold">{totals["scans"]}</div>
  </div>
</div>''')

    if data.get("truncated"):
        parts.append(f'<div style="font-size:12px;color:{_MUTED};margin-bottom:18px">'
                     f'Note: this date range exceeded {_MAX_REPORT_ROWS:,} scan results — '
                     f'figures cover the most recent {_MAX_REPORT_ROWS:,} only. Pick a shorter range for exact totals.</div>')

    # 5 — performance by AI engine
    if data["engines"]:
        parts.append(_h2("Performance by AI Engine"))
        eng_rows = "".join(
            f'<tr><td style="{_TD}">{_esc(e["label"])}</td><td style="{_TD};text-align:center">{e["scans"]}</td>'
            f'<td style="{_TD};text-align:center">{e["mentions"]}</td><td style="{_TD};text-align:center">{_pct_span(e["pct"])}</td></tr>'
            for e in data["engines"]
        )
        parts.append(f'''<table style="{_TABLE}">
<thead><tr><th style="{_TH};background:{_TABLE_HEAD}">Engine</th><th style="{_TH};background:{_TABLE_HEAD};text-align:center">Scans</th><th style="{_TH};background:{_TABLE_HEAD};text-align:center">Mentions</th><th style="{_TH};background:{_TABLE_HEAD};text-align:center">Visibility</th></tr></thead>
<tbody>{eng_rows}</tbody></table>''')

    # 6 — keyword performance
    if data["keywords"]:
        parts.append('<div class="page-break"></div>')
        parts.append(_h2("Keyword Performance"))
        kw_rows = "".join(
            f'<tr><td style="{_TD}">{_esc(k["keyword"])}</td><td style="{_TD};text-align:center">{k["scans"]}</td>'
            f'<td style="{_TD};text-align:center">{k["mentions"]}</td><td style="{_TD};text-align:center">{_pct_span(k["pct"])}</td></tr>'
            for k in data["keywords"]
        )
        parts.append(f'''<table style="{_TABLE}">
<thead><tr><th style="{_TH};background:{_TABLE_HEAD}">Keyword</th><th style="{_TH};background:{_TABLE_HEAD};text-align:center">Scans</th><th style="{_TH};background:{_TABLE_HEAD};text-align:center">Mentions</th><th style="{_TH};background:{_TABLE_HEAD};text-align:center">Visibility</th></tr></thead>
<tbody>{kw_rows}</tbody></table>''')

    # 7 — competitor benchmarking (You first, highlighted)
    if data["competitors"]:
        parts.append(_h2("Competitor Benchmarking"))
        you_pct = totals["visibility_pct"] if totals["visibility_pct"] is not None else 0.0
        comp_rows = [
            f'<tr style="background:{_YOU_HIGHLIGHT};font-weight:bold"><td style="{_TD}">{_esc(client.get("name") or "You")} (You)</td>'
            f'<td style="{_TD};text-align:center">{_pct_span(you_pct)}</td><td style="{_TD};text-align:center">{totals["mentions"]}</td></tr>'
        ]
        comp_rows += [
            f'<tr><td style="{_TD}">{_esc(c["name"])}</td><td style="{_TD};text-align:center">{_pct_span(c["pct"])}</td>'
            f'<td style="{_TD};text-align:center">{c["mentions"]}</td></tr>'
            for c in data["competitors"]
        ]
        parts.append(f'''<table style="{_TABLE}">
<thead><tr><th style="{_TH};background:{_TABLE_HEAD}">Competitor</th><th style="{_TH};background:{_TABLE_HEAD};text-align:center">Visibility Share</th><th style="{_TH};background:{_TABLE_HEAD};text-align:center">Mentions</th></tr></thead>
<tbody>{"".join(comp_rows)}</tbody></table>''')

    # 8 — lead valuation
    if valuation and valuation["total"] > 0:
        parts.append(f'''<div style="background:{_RED_BG};border:1px solid {_RED_BORDER};border-radius:8px;padding:20px;margin-bottom:24px">
  <h2 style="color:{_RED};font-size:18px;margin:0 0 8px">Estimated Monthly Visibility Opportunity Cost</h2>
  <div style="font-size:42px;font-weight:bold;color:{_RED}">${valuation["total"]:,}<span style="font-size:16px;font-weight:normal">/mo</span></div>
  <div style="font-size:12px;color:{_MUTED};margin-bottom:14px">What replacing this lost AI visibility with paid clicks would cost.</div>
  <div style="display:flex;justify-content:space-around;text-align:center">
    <div><div style="font-size:11px;color:{_MUTED}">Avg. CPC</div><div style="font-size:20px;font-weight:600">${valuation["avg_cpc"]:.2f}</div></div>
    <div><div style="font-size:11px;color:{_MUTED}">Monthly Searches</div><div style="font-size:20px;font-weight:600">{valuation["monthly_searches"]:,}</div></div>
    <div><div style="font-size:11px;color:{_MUTED}">Visibility Gap</div><div style="font-size:20px;font-weight:600;color:{_RED}">{valuation["gap_pct"]}%</div></div>
  </div>
  <div style="font-size:11px;color:{_FAINT};margin-top:14px">This estimate reflects the cost to replace lost AI visibility through paid demand. It is not a guarantee of revenue.</div>
</div>''')

    # 9 — footer
    parts.append(f'''<div style="border-top:1px solid #e5e7eb;margin-top:34px;padding-top:14px;text-align:center;color:{_FAINT};font-size:12px">
  <div>Report generated on {_esc(generated_on)}</div>
  <div>AI Visibility Report — Answer Engine Optimization Diagnostics</div>
</div>''')

    body = "\n".join(parts)
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AI Visibility Report — {_esc(client.get("name") or "")}</title>
<style>
  body {{ max-width: 800px; margin: 0 auto; padding: 40px; color: {_TEXT}; line-height: 1.6;
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }}
  @media print {{
    body {{ padding: 20px; }}
    .page-break {{ page-break-before: always; }}
  }}
</style>
</head>
<body>
{body}
</body>
</html>'''


# ── orchestration ────────────────────────────────────────────────────────────
def _fetch_mention_rows(supabase, client_id: str, start: date, end: date) -> tuple[list[dict], bool]:
    """All completed brand mention rows in the range, paged (PostgREST caps a
    single response), up to _MAX_REPORT_ROWS. Returns (rows, truncated)."""
    rows: list[dict] = []
    while True:
        batch = (
            supabase.table("brand_mention_history")
            .select("keyword_id, engine, status, mention_found, confidence_score, competitor_results, created_at")
            .eq("client_id", client_id)
            .eq("is_competitor_scan", False)
            .eq("status", "completed")
            .gte("created_at", start.isoformat())
            .lt("created_at", (end + timedelta(days=1)).isoformat())
            .order("created_at", desc=True)
            .range(len(rows), len(rows) + _PAGE_SIZE - 1)
            .execute()
        ).data or []
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            return rows, False
        if len(rows) >= _MAX_REPORT_ROWS:
            logger.warning("brand_report_html_truncated", extra={"client_id": client_id, "rows": len(rows)})
            return rows, True


async def generate_html_report(client_id: str, start_date: str | None, end_date: str | None) -> dict:
    """Assemble the report for a date range (defaults: last 30 days). DB reads
    + the keyword_market cache only — no LLM, no paid calls; synchronous-fast."""
    from services.dataforseo_rank import location_code_for
    from services.keyword_market import fetch_cached_market

    supabase = get_supabase()
    client_res = _safe(lambda: (
        supabase.table("clients")
        .select("id, name, website_url, gbp, rank_tracking_location_code")
        .eq("id", client_id).limit(1).execute()
    ))
    if not client_res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    client = client_res.data[0]

    try:
        end = date.fromisoformat(end_date) if end_date else date.today()
        start = date.fromisoformat(start_date) if start_date else end - timedelta(days=30)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_date")
    if start > end:
        raise HTTPException(status_code=422, detail="invalid_date_range")

    keywords = _safe(lambda: (
        supabase.table("brand_tracked_keywords")
        .select("id, keyword, category, is_active")
        .eq("client_id", client_id).order("created_at").execute()
    ).data) or []
    keyword_labels = {k["id"]: k["keyword"] for k in keywords}

    rows, truncated = _safe(lambda: _fetch_mention_rows(supabase, client_id, start, end))

    data = aggregate_range(rows, keyword_labels)
    data["truncated"] = truncated

    # Lead valuation from the shared market cache (best-effort, never live).
    valuation = None
    try:
        kw_list = [k["keyword"] for k in keywords if k.get("is_active")]
        if kw_list and data["keywords"]:
            market = fetch_cached_market(supabase, kw_list, location_code_for(client))
            valuation = build_lead_valuation(data["keywords"], market)
    except Exception as exc:  # pragma: no cover - cache read is best-effort
        logger.warning("brand_report_html_market_failed", extra={"client_id": client_id, "error": str(exc)})

    range_label = f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"

    html = render_html(
        client=client,
        agency_name=settings.client_report_agency_name,
        date_range_label=range_label,
        tracked_keywords=keywords,
        data=data,
        valuation=valuation,
        generated_on=datetime.now(timezone.utc).strftime("%b %d, %Y"),
    )
    return {"html": html}
