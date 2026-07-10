"""Keyword Research report — pure builders (stats + HTML).

Turns a Topic Fan-out session's already-fetched Postgres rows (topics/silos,
surviving keywords with §7.8 volume/CPC/KD metrics, clusters, and the article
architecture) into a client-facing PDF deliverable: an executive summary +
at-a-glance KPIs + topic-silo breakdown + top opportunities + the content
plan, followed by a detailed per-silo keyword appendix.

Everything here is pure (no I/O) so it is fully unit-testable with no Supabase
/ DataForSEO / LLM access — the orchestration (fetch → LLM summary → render_pdf
→ Drive + storage) lives in fanout/report_runner.py. The volume/CPC/KD columns
are null when the run didn't opt into metrics enrichment; the builders degrade
to blank cells and skip nulls from the sums/averages, and note it in the KPIs.
"""

from __future__ import annotations

import html as html_mod
from typing import Optional

# KD is a 0–100 difficulty index (DataForSEO Labs). Bands for the spread chart.
_KD_EASY_MAX = 30
_KD_MEDIUM_MAX = 60

# Cap the appendix so a pathological session can't render a thousand-page PDF.
_APPENDIX_ROW_CAP = 600
_TOP_OPPORTUNITIES = 20

# Suite palette (mirrors brand_report_html / client_report).
_BRAND = "#4f46e5"
_H2_UNDERLINE = "#c7d2fe"
_MUTED = "#6b7280"
_FAINT = "#94a3b8"
_BOX = "#f8fafc"
_TABLE_HEAD = "#f1f5f9"
_CELL_BORDER = "#e2e8f0"


def _num(v) -> Optional[float]:
    """Coerce a metric to float, or None when absent/malformed."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _mean(vals: list[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def _target_keywords(keywords: list[dict]) -> list[dict]:
    """The keywords a report is about: the active (survived-the-gate) pool.
    Falls back to every surviving keyword if none are marked active, so a report
    is never empty just because statuses weren't set."""
    active = [k for k in keywords if (k.get("status") or "") == "active"]
    return active if active else list(keywords)


# ── stats (pure) ──────────────────────────────────────────────────────────────
def build_report_stats(
    *,
    session: dict,
    topics: list[dict],
    keywords: list[dict],
    clusters: list[dict],
    architecture_json: Optional[dict],
) -> dict:
    """Aggregate a session's rows into the report figures. Pure."""
    seed = (session.get("seed_keyword") or "").strip()
    topic_name = {t["id"]: (t.get("name") or "Untitled silo") for t in topics}
    target = _target_keywords(keywords)

    # Per-silo rollup.
    silos: dict = {}
    for k in target:
        tid = k.get("topic_id")
        s = silos.setdefault(tid, {
            "topic_id": tid, "name": topic_name.get(tid, "Unassigned"),
            "count": 0, "volume": 0, "kds": [], "cpcs": [], "top": None, "keywords": [],
        })
        s["count"] += 1
        s["keywords"].append(k)
        v = _num(k.get("volume"))
        if v is not None:
            s["volume"] += v
        kd = _num(k.get("keyword_difficulty"))
        if kd is not None:
            s["kds"].append(kd)
        cpc = _num(k.get("cpc_usd"))
        if cpc is not None:
            s["cpcs"].append(cpc)
        if s["top"] is None or (v or -1) > (_num(s["top"].get("volume")) or -1):
            s["top"] = k

    silo_rows = []
    for s in silos.values():
        silo_rows.append({
            "name": s["name"],
            "count": s["count"],
            "volume": int(s["volume"]),
            "avg_kd": _mean(s["kds"]),
            "avg_cpc": _mean(s["cpcs"]),
            "top_keyword": (s["top"] or {}).get("keyword") or "",
            "keywords": sorted(
                s["keywords"],
                key=lambda k: (_num(k.get("volume")) is not None, _num(k.get("volume")) or 0),
                reverse=True,
            ),
        })
    silo_rows.sort(key=lambda r: r["volume"], reverse=True)

    # Totals.
    total_keywords = len(target)
    total_volume = int(sum((_num(k.get("volume")) or 0) for k in target))
    kds_all = [kd for k in target if (kd := _num(k.get("keyword_difficulty"))) is not None]
    have_volume = sum(1 for k in target if _num(k.get("volume")) is not None)
    metrics_present = have_volume > 0

    # Top opportunities (by monthly volume).
    ranked = sorted(
        target,
        key=lambda k: (_num(k.get("volume")) is not None, _num(k.get("volume")) or 0),
        reverse=True,
    )
    top_opportunities = [
        {
            "keyword": k.get("keyword") or "",
            "volume": _num(k.get("volume")),
            "kd": _num(k.get("keyword_difficulty")),
            "cpc": _num(k.get("cpc_usd")),
            "silo": topic_name.get(k.get("topic_id"), "Unassigned"),
        }
        for k in ranked[:_TOP_OPPORTUNITIES]
    ]

    # Difficulty spread.
    easy = sum(1 for kd in kds_all if kd < _KD_EASY_MAX)
    medium = sum(1 for kd in kds_all if _KD_EASY_MAX <= kd <= _KD_MEDIUM_MAX)
    hard = sum(1 for kd in kds_all if kd > _KD_MEDIUM_MAX)

    # Content plan (from the article architecture, if planned).
    content_plan = _build_content_plan(architecture_json, clusters)

    return {
        "seed": seed,
        "total_keywords": total_keywords,
        "total_silos": len(silo_rows),
        "total_volume": total_volume,
        "metrics_present": metrics_present,
        "metrics_coverage": (round(100.0 * have_volume / total_keywords) if total_keywords else 0),
        "avg_difficulty": _mean(kds_all),
        "difficulty_spread": {"easy": easy, "medium": medium, "hard": hard},
        "planned_pages": content_plan["planned_pages"],
        "silos": silo_rows,
        "top_opportunities": top_opportunities,
        "content_plan": content_plan,
    }


def _build_content_plan(architecture_json: Optional[dict], clusters: list[dict]) -> dict:
    arch = architecture_json or {}
    pillars_raw = arch.get("pillars") or []
    supporting_raw = arch.get("supporting_articles") or []
    cluster_name = {c["id"]: (c.get("name") or "") for c in clusters}

    by_parent: dict = {}
    for a in supporting_raw:
        name = a.get("name") or cluster_name.get(a.get("article_id")) or "Untitled article"
        by_parent.setdefault(a.get("parent_pillar_topic_id"), []).append(name)

    pillars = []
    for p in pillars_raw:
        pillars.append({
            "title": p.get("title") or p.get("silo_name") or "Untitled pillar",
            "target_keyword": p.get("target_keyword") or "",
            "articles": by_parent.get(p.get("topic_id"), []),
        })
    return {
        "pillars": pillars,
        "planned_pages": len(pillars_raw) + len(supporting_raw),
        "pillar_count": len(pillars_raw),
        "article_count": len(supporting_raw),
    }


def fallback_summary(stats: dict) -> str:
    """A deterministic executive summary, used when the LLM call is unavailable
    or fails — so the report always has a lead paragraph."""
    seed = stats.get("seed") or "this topic"
    parts = [
        f'This keyword research mapped {stats["total_keywords"]:,} target '
        f'keyword{"" if stats["total_keywords"] == 1 else "s"} across '
        f'{stats["total_silos"]} topic silo{"" if stats["total_silos"] == 1 else "s"} '
        f'for "{seed}".'
    ]
    if stats["metrics_present"] and stats["total_volume"]:
        parts.append(
            f'Together they represent roughly {stats["total_volume"]:,} searches per month.'
        )
    cp = stats["content_plan"]
    if stats["planned_pages"]:
        parts.append(
            f'The recommended content plan covers {stats["planned_pages"]} pages '
            f'({cp["pillar_count"]} pillar{"" if cp["pillar_count"] == 1 else "s"} and '
            f'{cp["article_count"]} supporting article'
            f'{"" if cp["article_count"] == 1 else "s"}).'
        )
    return " ".join(parts)


# ── HTML rendering (pure) ─────────────────────────────────────────────────────
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
    *,
    stats: dict,
    exec_summary: str,
    agency_name: str,
    client_name: Optional[str],
    generated_on: str,
) -> str:
    """The full standalone report document (inline CSS, print-friendly). Pure."""
    seed = stats.get("seed") or ""
    parts: list[str] = []

    # Header.
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

    # Executive summary.
    parts.append(_h2("Executive summary"))
    parts.append(f'<p style="font-size:13.5px;line-height:1.6;color:#1f2937;margin:0 0 8px">{_esc(exec_summary)}</p>')

    # At-a-glance KPIs.
    parts.append(_h2("At a glance"))
    kpis = [
        ("Target keywords", _fmt_int(stats["total_keywords"])),
        ("Topic silos", str(stats["total_silos"])),
        ("Monthly searches", _fmt_int(stats["total_volume"]) if stats["metrics_present"] else "—"),
        ("Planned pages", str(stats["planned_pages"])),
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
        parts.append(f'<div style="font-size:11.5px;color:#b45309;margin-bottom:6px">Search volume / CPC / difficulty were not fetched for this run — enable "Fetch volume / CPC / KD" when running keyword research to populate these figures.</div>')

    # Topic silos.
    parts.append(_h2("Topic silos"))
    silo_rows = "".join(
        f'''<tr>
  <td style="{_TD}">{_esc(s["name"])}</td>
  <td style="{_TD};text-align:right">{_fmt_int(s["count"])}</td>
  <td style="{_TD};text-align:right">{_fmt_int(s["volume"]) if stats["metrics_present"] else "—"}</td>
  <td style="{_TD};text-align:right">{_fmt_kd(s["avg_kd"])}</td>
  <td style="{_TD}">{_esc(s["top_keyword"])}</td>
</tr>''' for s in stats["silos"]
    )
    parts.append(f'''<table style="{_TABLE}">
<thead><tr>
  <th style="{_TH}">Silo</th>
  <th style="{_TH};text-align:right">Keywords</th>
  <th style="{_TH};text-align:right">Monthly vol.</th>
  <th style="{_TH};text-align:right">Avg. KD</th>
  <th style="{_TH}">Top keyword</th>
</tr></thead>
<tbody>{silo_rows}</tbody></table>''')

    # Top opportunities.
    if stats["top_opportunities"]:
        parts.append(_h2("Top opportunities"))
        opp_rows = "".join(
            f'''<tr>
  <td style="{_TD}">{_esc(o["keyword"])}</td>
  <td style="{_TD}">{_esc(o["silo"])}</td>
  <td style="{_TD};text-align:right">{_fmt_int(o["volume"])}</td>
  <td style="{_TD};text-align:right">{_fmt_kd(o["kd"])}</td>
  <td style="{_TD};text-align:right">{_fmt_cpc(o["cpc"])}</td>
</tr>''' for o in stats["top_opportunities"]
        )
        parts.append(f'''<table style="{_TABLE}">
<thead><tr>
  <th style="{_TH}">Keyword</th>
  <th style="{_TH}">Silo</th>
  <th style="{_TH};text-align:right">Monthly vol.</th>
  <th style="{_TH};text-align:right">KD</th>
  <th style="{_TH};text-align:right">CPC</th>
</tr></thead>
<tbody>{opp_rows}</tbody></table>''')

    # Content plan.
    plan = stats["content_plan"]
    if plan["pillars"]:
        parts.append(_h2("Recommended content plan"))
        for p in plan["pillars"]:
            arts = "".join(f'<li style="margin:2px 0">{_esc(a)}</li>' for a in p["articles"])
            arts_block = f'<ul style="margin:6px 0 0;padding-left:20px;font-size:12.5px;color:#334155">{arts}</ul>' if arts else '<div style="font-size:12px;color:#94a3b8;margin-top:4px">No supporting articles planned.</div>'
            tk = f' <span style="font-size:11.5px;color:{_MUTED}">· target: {_esc(p["target_keyword"])}</span>' if p["target_keyword"] else ""
            parts.append(f'''<div style="border:1px solid {_CELL_BORDER};border-radius:8px;padding:12px 14px;margin-bottom:10px">
  <div style="font-size:13.5px;font-weight:700;color:#0f172a">{_esc(p["title"])}{tk}</div>
  {arts_block}
</div>''')

    # Appendix: full per-silo keyword list.
    parts.append('<div style="page-break-before:always"></div>')
    parts.append(_h2("Appendix — full keyword list"))
    rendered = 0
    truncated = False
    for s in stats["silos"]:
        if rendered >= _APPENDIX_ROW_CAP:
            truncated = True
            break
        parts.append(f'<h3 style="font-size:13.5px;color:#0f172a;margin:16px 0 6px">{_esc(s["name"])} <span style="font-size:11.5px;color:{_FAINT};font-weight:400">({s["count"]} keywords)</span></h3>')
        kw_rows = []
        for k in s["keywords"]:
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

    # Footer.
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
