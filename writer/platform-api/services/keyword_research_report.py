"""Keyword Research report — a client-facing PDF deliverable.

Turns a keyword research run (its keywords + topic clusters) into a white-label
PDF: an executive summary + at-a-glance KPIs + topic-cluster breakdown + top
opportunities + the questions customers are asking, followed by a full per-cluster
keyword appendix. Saved to the private `reports` bucket for download and (when
the client has a Drive folder) uploaded there too.

The stats + HTML builders are PURE (no I/O) and unit-tested; the orchestration
(fetch → best-effort LLM summary → render_pdf → store → Drive → row) is the
impure `generate_report`. Synchronous like the Fanout keyword report — one LLM
call + a WeasyPrint render + two uploads finish well within the request budget,
and every delivery step is best-effort (a failed Drive upload still returns the
download). Tone follows the suite's client-report ruling: plain, upbeat, no
health score, no scare copy.
"""

from __future__ import annotations

import asyncio
import html as html_mod
import logging
from datetime import datetime, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import keyword_research

logger = logging.getLogger(__name__)

_REPORTS_BUCKET = "reports"
_SIGNED_URL_TTL = 7 * 24 * 3600  # 7 days

# KD is a 0–100 difficulty index (DataForSEO Labs). Bands for the spread read.
_KD_EASY_MAX = 30
_KD_MEDIUM_MAX = 60
_APPENDIX_ROW_CAP = 600
_TOP_OPPORTUNITIES = 20
_TOP_QUESTIONS = 15

# Suite palette (mirrors fanout/report.py / brand_report_html / client_report).
_BRAND = "#4f46e5"
_H2_UNDERLINE = "#c7d2fe"
_MUTED = "#6b7280"
_FAINT = "#94a3b8"
_BOX = "#f8fafc"
_TABLE_HEAD = "#f1f5f9"
_CELL_BORDER = "#e2e8f0"


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — unit-tested.
# ---------------------------------------------------------------------------
def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _mean(vals: list[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def build_report_stats(*, run: dict, keywords: list[dict]) -> dict:
    """Aggregate a run's keyword rows into the report figures. Pure."""
    seeds = run.get("seeds") or []
    seed_str = ", ".join(str(s) for s in seeds) if seeds else ""

    # Per-cluster rollup (grouped by the stored cluster_label).
    groups: dict = {}
    for k in keywords:
        label = k.get("cluster_label") or "other"
        g = groups.setdefault(label, {"label": label, "count": 0, "volume": 0.0,
                                      "kds": [], "top": None, "keywords": []})
        g["count"] += 1
        g["keywords"].append(k)
        v = _num(k.get("volume"))
        if v is not None:
            g["volume"] += v
        kd = _num(k.get("keyword_difficulty"))
        if kd is not None:
            g["kds"].append(kd)
        if g["top"] is None or (v or -1) > (_num(g["top"].get("volume")) or -1):
            g["top"] = k

    cluster_rows = []
    for g in groups.values():
        cluster_rows.append({
            "label": g["label"],
            "count": g["count"],
            "volume": int(g["volume"]),
            "avg_kd": _mean(g["kds"]),
            "top_keyword": (g["top"] or {}).get("keyword") or "",
            "keywords": sorted(
                g["keywords"],
                key=lambda k: (_num(k.get("volume")) is not None, _num(k.get("volume")) or 0),
                reverse=True,
            ),
        })
    cluster_rows.sort(key=lambda r: r["volume"], reverse=True)

    total_keywords = len(keywords)
    total_volume = int(sum((_num(k.get("volume")) or 0) for k in keywords))
    kds_all = [kd for k in keywords if (kd := _num(k.get("keyword_difficulty"))) is not None]
    have_volume = sum(1 for k in keywords if _num(k.get("volume")) is not None)
    metrics_present = have_volume > 0

    # Top opportunities (by the run's opportunity score — value × ease × intent).
    ranked = sorted(
        keywords,
        key=lambda k: (_num(k.get("opportunity_score")) or 0, _num(k.get("volume")) or 0),
        reverse=True,
    )
    top_opportunities = [{
        "keyword": k.get("keyword") or "",
        "cluster": k.get("cluster_label") or "other",
        "volume": _num(k.get("volume")),
        "kd": _num(k.get("keyword_difficulty")),
        "cpc": _num(k.get("cpc_usd")),
        "intent": k.get("search_intent") or "",
    } for k in ranked[:_TOP_OPPORTUNITIES]]

    # Questions customers are asking (highest-volume question keywords).
    questions = sorted(
        [k for k in keywords if k.get("is_question")],
        key=lambda k: (_num(k.get("volume")) is not None, _num(k.get("volume")) or 0),
        reverse=True,
    )
    question_rows = [{"keyword": k.get("keyword") or "", "volume": _num(k.get("volume"))}
                     for k in questions[:_TOP_QUESTIONS]]

    easy = sum(1 for kd in kds_all if kd < _KD_EASY_MAX)
    medium = sum(1 for kd in kds_all if _KD_EASY_MAX <= kd <= _KD_MEDIUM_MAX)
    hard = sum(1 for kd in kds_all if kd > _KD_MEDIUM_MAX)

    return {
        "seed": seed_str,
        "total_keywords": total_keywords,
        "total_clusters": len(cluster_rows),
        "total_volume": total_volume,
        "metrics_present": metrics_present,
        "metrics_coverage": (round(100.0 * have_volume / total_keywords) if total_keywords else 0),
        "avg_difficulty": _mean(kds_all),
        "question_count": len(questions),
        "difficulty_spread": {"easy": easy, "medium": medium, "hard": hard},
        "clusters": cluster_rows,
        "top_opportunities": top_opportunities,
        "questions": question_rows,
    }


def fallback_summary(stats: dict) -> str:
    """A deterministic executive summary, used when the LLM is unavailable or
    fails — so the report always has a lead paragraph. Pure."""
    seed = stats.get("seed") or "this topic"
    n = stats["total_keywords"]
    c = stats["total_clusters"]
    parts = [
        f'This keyword research uncovered {n:,} keyword{"" if n == 1 else "s"} that '
        f'potential customers are searching for around "{seed}", organised into '
        f'{c} topic group{"" if c == 1 else "s"}.'
    ]
    if stats["metrics_present"] and stats["total_volume"]:
        parts.append(
            f'Together they represent roughly {stats["total_volume"]:,} searches every month.'
        )
    if stats["top_opportunities"]:
        top = stats["top_opportunities"][0]["keyword"]
        parts.append(f'The strongest opportunity to pursue first is "{top}".')
    if stats["question_count"]:
        parts.append(
            f'We also found {stats["question_count"]} question'
            f'{"" if stats["question_count"] == 1 else "s"} your customers are asking — '
            f'ready-made topics for helpful content.'
        )
    return " ".join(parts)


# ── HTML rendering (pure) ───────────────────────────────────────────────────
def _esc(v) -> str:
    return html_mod.escape(str(v)) if v is not None else ""


def _fmt_int(v: Optional[float]) -> str:
    return f"{int(v):,}" if v is not None else "—"


def _fmt_kd(v: Optional[float]) -> str:
    return str(round(v)) if v is not None else "—"


def _fmt_cpc(v: Optional[float]) -> str:
    return f"${v:.2f}" if v is not None else "—"


_TABLE = "width:100%;border-collapse:collapse;margin-bottom:20px;font-size:12.5px"
_TH = f"border:1px solid {_CELL_BORDER};padding:8px 10px;text-align:left;background:{_TABLE_HEAD}"
_TD = f"border:1px solid {_CELL_BORDER};padding:8px 10px"


def _h2(title: str) -> str:
    return (f'<h2 style="color:{_BRAND};font-size:17px;border-bottom:2px solid {_H2_UNDERLINE};'
            f'padding-bottom:6px;margin:26px 0 12px">{_esc(title)}</h2>')


def render_report_html(
    *, stats: dict, exec_summary: str, agency_name: str,
    client_name: Optional[str], generated_on: str,
) -> str:
    """The full standalone report document (inline CSS, print-friendly). Pure."""
    seed = stats.get("seed") or ""
    parts: list[str] = []

    subtitle = _esc(client_name) if client_name else "Keyword Research"
    parts.append(f'''<div style="display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px solid {_BRAND};padding-bottom:14px;margin-bottom:22px">
  <div style="font-size:18px;font-weight:bold;color:{_BRAND}">{_esc(agency_name)}</div>
  <div style="text-align:right">
    <div style="font-size:12px;color:{_MUTED}">Keyword Research Report</div>
    <div style="font-size:14px;font-weight:600">{subtitle}</div>
  </div>
</div>''')

    if seed:
        parts.append(f'<div style="font-size:22px;font-weight:700;color:#0f172a;margin-bottom:2px">{_esc(seed)}</div>')
    parts.append(f'<div style="font-size:12px;color:{_MUTED};margin-bottom:18px">Generated {_esc(generated_on)}</div>')

    parts.append(_h2("Executive summary"))
    parts.append(f'<p style="font-size:13.5px;line-height:1.6;color:#1f2937;margin:0 0 8px">{_esc(exec_summary)}</p>')

    parts.append(_h2("At a glance"))
    kpis = [
        ("Keywords found", _fmt_int(stats["total_keywords"])),
        ("Topic clusters", str(stats["total_clusters"])),
        ("Monthly searches", _fmt_int(stats["total_volume"]) if stats["metrics_present"] else "—"),
        ("Questions", str(stats["question_count"])),
        ("Avg. difficulty", _fmt_kd(stats["avg_difficulty"])),
    ]
    cells = "".join(
        f'''<div style="flex:1;min-width:110px;background:{_BOX};border:1px solid {_CELL_BORDER};border-radius:8px;padding:12px 14px">
  <div style="font-size:10.5px;font-weight:600;color:{_FAINT};text-transform:uppercase;letter-spacing:0.04em">{_esc(label)}</div>
  <div style="font-size:22px;font-weight:700;color:#0f172a;margin-top:2px">{val}</div>
</div>''' for label, val in kpis
    )
    parts.append(f'<div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:6px">{cells}</div>')
    if not stats["metrics_present"]:
        parts.append(f'<div style="font-size:11.5px;color:#b45309;margin-bottom:6px">Search volume, CPC and difficulty were not available for this run.</div>')

    # Topic clusters.
    parts.append(_h2("Topic clusters"))
    cluster_rows = "".join(
        f'''<tr>
  <td style="{_TD}">{_esc(c["label"])}</td>
  <td style="{_TD};text-align:right">{_fmt_int(c["count"])}</td>
  <td style="{_TD};text-align:right">{_fmt_int(c["volume"]) if stats["metrics_present"] else "—"}</td>
  <td style="{_TD};text-align:right">{_fmt_kd(c["avg_kd"])}</td>
  <td style="{_TD}">{_esc(c["top_keyword"])}</td>
</tr>''' for c in stats["clusters"]
    )
    parts.append(f'''<table style="{_TABLE}">
<thead><tr>
  <th style="{_TH}">Cluster</th>
  <th style="{_TH};text-align:right">Keywords</th>
  <th style="{_TH};text-align:right">Monthly vol.</th>
  <th style="{_TH};text-align:right">Avg. KD</th>
  <th style="{_TH}">Top keyword</th>
</tr></thead>
<tbody>{cluster_rows}</tbody></table>''')

    # Top opportunities.
    if stats["top_opportunities"]:
        parts.append(_h2("Top opportunities"))
        parts.append(f'<p style="font-size:12px;color:{_MUTED};margin:-4px 0 12px">Ranked by opportunity — high search demand and commercial value weighed against how hard the keyword is to rank for.</p>')
        opp_rows = "".join(
            f'''<tr>
  <td style="{_TD}">{_esc(o["keyword"])}</td>
  <td style="{_TD}">{_esc(o["cluster"])}</td>
  <td style="{_TD};text-align:right">{_fmt_int(o["volume"])}</td>
  <td style="{_TD};text-align:right">{_fmt_kd(o["kd"])}</td>
  <td style="{_TD};text-align:right">{_fmt_cpc(o["cpc"])}</td>
  <td style="{_TD}">{_esc(o["intent"])}</td>
</tr>''' for o in stats["top_opportunities"]
        )
        parts.append(f'''<table style="{_TABLE}">
<thead><tr>
  <th style="{_TH}">Keyword</th>
  <th style="{_TH}">Cluster</th>
  <th style="{_TH};text-align:right">Monthly vol.</th>
  <th style="{_TH};text-align:right">KD</th>
  <th style="{_TH};text-align:right">CPC</th>
  <th style="{_TH}">Intent</th>
</tr></thead>
<tbody>{opp_rows}</tbody></table>''')

    # Questions customers are asking.
    if stats["questions"]:
        parts.append(_h2("Questions your customers are asking"))
        q_rows = "".join(
            f'''<tr>
  <td style="{_TD}">{_esc(q["keyword"])}</td>
  <td style="{_TD};text-align:right">{_fmt_int(q["volume"])}</td>
</tr>''' for q in stats["questions"]
        )
        parts.append(f'''<table style="{_TABLE}">
<thead><tr>
  <th style="{_TH}">Question</th>
  <th style="{_TH};text-align:right">Monthly vol.</th>
</tr></thead>
<tbody>{q_rows}</tbody></table>''')

    # Appendix: full per-cluster keyword list.
    parts.append('<div style="page-break-before:always"></div>')
    parts.append(_h2("Appendix — full keyword list"))
    rendered = 0
    truncated = False
    for c in stats["clusters"]:
        if rendered >= _APPENDIX_ROW_CAP:
            truncated = True
            break
        parts.append(f'<h3 style="font-size:13.5px;color:#0f172a;margin:16px 0 6px">{_esc(c["label"])} <span style="font-size:11.5px;color:{_FAINT};font-weight:400">({c["count"]} keywords)</span></h3>')
        kw_rows = []
        for k in c["keywords"]:
            if rendered >= _APPENDIX_ROW_CAP:
                truncated = True
                break
            kw_rows.append(f'''<tr>
  <td style="{_TD}">{_esc(k.get("keyword") or "")}</td>
  <td style="{_TD};text-align:right">{_fmt_int(_num(k.get("volume")))}</td>
  <td style="{_TD};text-align:right">{_fmt_kd(_num(k.get("keyword_difficulty")))}</td>
  <td style="{_TD};text-align:right">{_fmt_cpc(_num(k.get("cpc_usd")))}</td>
</tr>''')
            rendered += 1
        parts.append(f'''<table style="{_TABLE}">
<thead><tr>
  <th style="{_TH}">Keyword</th>
  <th style="{_TH};text-align:right">Monthly vol.</th>
  <th style="{_TH};text-align:right">KD</th>
  <th style="{_TH};text-align:right">CPC</th>
</tr></thead>
<tbody>{"".join(kw_rows)}</tbody></table>''')
    if truncated:
        parts.append(f'<div style="font-size:11.5px;color:{_MUTED}">Appendix truncated to the first {_APPENDIX_ROW_CAP} keywords — export the full list as CSV for the complete set.</div>')

    parts.append(f'''<div style="border-top:1px solid #e5e7eb;margin-top:30px;padding-top:12px;text-align:center;color:{_FAINT};font-size:11.5px">
  <div>Prepared by {_esc(agency_name)} · {_esc(generated_on)}</div>
</div>''')

    body = "\n".join(parts)
    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  @page {{ size: A4; margin: 20mm 16mm; }}
  @media print {{ h2, h3 {{ page-break-after: avoid; }} table {{ page-break-inside: auto; }} tr {{ page-break-inside: avoid; }} }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; color:#1f2937; }}
</style></head>
<body>{body}</body></html>'''


# ---------------------------------------------------------------------------
# LLM executive summary (best-effort).
# ---------------------------------------------------------------------------
_SUMMARY_SYSTEM = (
    "You are an SEO strategist writing the opening of a client-facing keyword "
    "research report for a small-business owner. Write ONE tight paragraph (3-5 "
    "sentences), plain and upbeat, no jargon, no bullet points, no headings, no "
    "health score. Summarize what the research found and the opportunity — "
    "grounded ONLY in the figures given. Do not invent numbers."
)
_SUMMARY_TOOL = {
    "name": "emit_summary",
    "description": "Return the executive-summary paragraph.",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string", "description": "The paragraph."}},
        "required": ["summary"],
    },
}


def _exec_summary(stats: dict) -> str:
    """Best-effort LLM executive summary; deterministic fallback on any failure
    or when no LLM key is configured. Runs on Anthropic with OpenAI→Gemini
    fallback via report_llm."""
    if not (settings.anthropic_api_key or settings.openai_api_key or settings.gemini_api_key):
        return fallback_summary(stats)
    facts = (
        f'Seed keyword(s): "{stats["seed"]}"\n'
        f'Keywords found: {stats["total_keywords"]}\n'
        f'Topic clusters: {stats["total_clusters"]} '
        f'({", ".join(c["label"] for c in stats["clusters"][:8])})\n'
        f'Total monthly searches: {stats["total_volume"] if stats["metrics_present"] else "not measured"}\n'
        f'Average difficulty (0-100): {round(stats["avg_difficulty"]) if stats["avg_difficulty"] is not None else "n/a"}\n'
        f'Questions found: {stats["question_count"]}\n'
        f'Top opportunities: ' + ", ".join(o["keyword"] for o in stats["top_opportunities"][:6])
    )
    try:
        from services import report_llm

        result = report_llm.run_forced_tool_sync(
            provider="anthropic",
            model=settings.keyword_research_report_model,
            max_tokens=settings.keyword_research_report_max_tokens,
            system=_SUMMARY_SYSTEM,
            user=f"Write the executive summary from these figures:\n\n{facts}",
            tool_name=_SUMMARY_TOOL["name"],
            tool_description=_SUMMARY_TOOL["description"],
            input_schema=_SUMMARY_TOOL["input_schema"],
            log_tag="keyword_research_report_summary",
        )
        text = (result or {}).get("summary", "").strip()
        return text or fallback_summary(stats)
    except Exception as exc:  # noqa: BLE001 — narrative is best-effort
        logger.warning("keyword_research_report.summary_failed", extra={"error": str(exc)})
        return fallback_summary(stats)


# ---------------------------------------------------------------------------
# Delivery (I/O) — best-effort per channel.
# ---------------------------------------------------------------------------
def _client_row(client_id: str) -> Optional[dict]:
    try:
        res = (
            get_supabase().table("clients")
            .select("id, name, google_drive_folder_id, drive_folders")
            .eq("id", client_id).limit(1).execute()
        )
        return res.data[0] if res.data else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_research_report.client_lookup_failed", extra={"error": str(exc)})
        return None


def _store_pdf(client_id: str, report_id: str, pdf: bytes) -> tuple[Optional[str], Optional[str]]:
    try:
        sb = get_supabase()
        path = f"{client_id}/keyword-research/{report_id}.pdf"
        sb.storage.from_(_REPORTS_BUCKET).upload(
            path, pdf, {"content-type": "application/pdf", "upsert": "true"}
        )
        return path, _signed_url(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_research_report.storage_failed", extra={"error": str(exc)})
        return None, None


def _signed_url(path: str) -> Optional[str]:
    try:
        res = get_supabase().storage.from_(_REPORTS_BUCKET).create_signed_url(path, _SIGNED_URL_TTL)
        return (res.get("signedURL") or res.get("signedUrl")) if isinstance(res, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_research_report.sign_failed", extra={"path": path, "error": str(exc)})
        return None


def _upload_to_drive(client: Optional[dict], title: str, pdf: bytes) -> Optional[str]:
    if not client:
        return None
    try:
        from services.google_docs import resolve_drive_folder, upload_pdf

        folder = resolve_drive_folder(client, "keyword_research") or client.get("google_drive_folder_id")
        if not folder:
            return None
        result = asyncio.run(upload_pdf(folder, title, pdf))
        return result.get("file_url")
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_research_report.drive_failed", extra={"error": str(exc)})
        return None


def generate_report(client_id: str, run_id: str, user_id: Optional[str] = None) -> dict:
    """Build + deliver the client-facing PDF for a run. Raises ValueError
    ('run_not_found' / 'no_keywords') when there's nothing to report on."""
    data = keyword_research.get_run(client_id, run_id)
    if not data or not data.get("run"):
        raise ValueError("run_not_found")
    keywords = data.get("keywords") or []
    if not keywords:
        raise ValueError("no_keywords")

    stats = build_report_stats(run=data["run"], keywords=keywords)
    client = _client_row(client_id)
    agency_name = settings.client_report_agency_name
    client_name = (client or {}).get("name")
    exec_summary = _exec_summary(stats)
    generated_on = datetime.now(timezone.utc).strftime("%b %d, %Y")

    html = render_report_html(
        stats=stats, exec_summary=exec_summary, agency_name=agency_name,
        client_name=client_name, generated_on=generated_on,
    )

    from services.client_report import render_pdf

    pdf = render_pdf(html)
    title = f"Keyword Research — {stats['seed'] or 'Report'}"

    supabase = get_supabase()
    row = (
        supabase.table("keyword_research_reports").insert({
            "client_id": client_id, "run_id": run_id, "created_by": user_id,
            "title": title, "status": "complete",
        }).execute()
    ).data[0]
    report_id = row["id"]

    storage_path, download_url = _store_pdf(client_id, report_id, pdf)
    drive_url = _upload_to_drive(client, title, pdf)

    supabase.table("keyword_research_reports").update(
        {"storage_path": storage_path, "drive_url": drive_url}
    ).eq("id", report_id).execute()

    logger.info("keyword_research_report_created", extra={
        "client_id": client_id, "run_id": run_id,
        "keywords": stats["total_keywords"], "drive": bool(drive_url),
    })
    return {
        "report_id": report_id, "run_id": run_id, "title": title,
        "download_url": download_url, "drive_url": drive_url,
        "created_at": row.get("created_at"),
    }


def list_reports(client_id: str, limit: int = 25) -> list[dict]:
    """Report history for a client (newest first)."""
    return (
        get_supabase().table("keyword_research_reports")
        .select("id, run_id, title, status, drive_url, created_at")
        .eq("client_id", client_id).order("created_at", desc=True).limit(limit).execute()
    ).data or []


def report_download_url(client_id: str, report_id: str) -> Optional[str]:
    """A fresh signed download URL for a stored report (past links expire)."""
    rows = (
        get_supabase().table("keyword_research_reports").select("storage_path")
        .eq("id", report_id).eq("client_id", client_id).limit(1).execute()
    ).data
    if not rows or not rows[0].get("storage_path"):
        return None
    return _signed_url(rows[0]["storage_path"])
