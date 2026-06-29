"""AI Visibility — visibility report → Google Doc.

Assembles the latest scan into a shareable report (per-engine visibility, the
keyword×engine matrix, where the brand is invisible, competitor comparison) +
a short Claude narrative, and publishes it as a Google Doc in the client's Drive
folder (shared services/google_docs, like the Maps Local Rank Analysis report).

Runs as an `async_jobs` job ('brand_report'). The data-assembly + markdown
helpers are pure (unit-tested); only the narrative + publish touch the network.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import settings
from db.supabase_client import get_supabase
from services import brand_analysis
from services.brand_scan import ENGINE_ORDER
from services.google_docs import GoogleDocError, create_google_doc

logger = logging.getLogger("brand_report")

ENGINE_LABELS = {
    "chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini",
    "perplexity": "Perplexity", "google_ai_overview": "Google AI Overview",
    "google_ai_mode": "Google AI Mode",
}
_AIO_ENGINES = ("google_ai_overview", "google_ai_mode")
_AIO_KIND_LABELS = {
    "in_content_link": "linked inline in the answer",
    "both": "linked inline + cited as a source",
    "citation_only": "cited in the sources strip only",
    "none": "not in the AI Overview",
}
SOURCE_TYPE_LABELS = {
    "directory": "Directories", "review": "Review sites", "social": "Social",
    "forum": "Forums/Q&A", "search": "Search/Maps", "editorial": "Editorial/brand sites",
}


# ── pure data assembly ───────────────────────────────────────────────────────
def build_snapshot(rows: list[dict], keyword_labels: dict[str, str]) -> dict:
    """Roll a batch's brand-mention rows into report figures. Pure.

    Beyond the per-engine/keyword/competitor rollups, mines each cell's
    `response_analysis` + `invisibility_diagnosis` (added by the scan engine) for
    the client-facing enrichment: why each invisible cell is invisible, possible
    misinformation, Google AI Overview link status, standout (leading) mentions,
    untracked competitors the AIs surfaced, what wins, and the source-type mix.
    Every enrichment degrades to empty when the rows predate that analysis."""
    engines: dict[str, dict] = {e: {"total": 0, "found": 0} for e in ENGINE_ORDER}
    competitors: dict[str, dict] = {}
    by_keyword: dict[str, dict] = {}
    by_cell: dict[tuple, dict] = {}
    overall_total = overall_found = 0

    for r in rows:
        if r.get("status") != "completed":
            continue
        engine = r.get("engine")
        kid = r.get("keyword_id")
        label = keyword_labels.get(kid, "(removed keyword)")
        found = bool(r.get("mention_found"))
        if engine in engines:
            engines[engine]["total"] += 1
            engines[engine]["found"] += 1 if found else 0
        overall_total += 1
        overall_found += 1 if found else 0
        kw = by_keyword.setdefault(label, {})
        kw[engine] = "found" if found else "not"
        by_cell[(label, engine)] = r
        for comp in r.get("competitor_results") or []:
            name = comp.get("name")
            if not name:
                continue
            agg = competitors.setdefault(name, {"total": 0, "found": 0})
            agg["total"] += 1
            agg["found"] += 1 if comp.get("found") else 0

    def _pct(found, total):
        return round(100.0 * found / total, 1) if total else 0.0

    # Invisible cells, each carrying its (grounded) diagnosis when present.
    invisible = []
    for kw, cells in by_keyword.items():
        for eng in ENGINE_ORDER:
            if cells.get(eng) == "not":
                row = by_cell.get((kw, eng), {})
                invisible.append({
                    "keyword": kw, "engine": eng,
                    "diagnosis": row.get("invisibility_diagnosis"),
                })

    # Possible misinformation, Google AI Overview link status, and standout
    # (leading) mentions — all from per-cell response_analysis.
    accuracy: list[dict] = []
    aio: list[dict] = []
    leading: list[dict] = []
    for (kw, eng), row in by_cell.items():
        ra = row.get("response_analysis") or {}
        for f in ra.get("accuracy_flags") or []:
            accuracy.append({"keyword": kw, "engine": eng, **f})
        if eng in _AIO_ENGINES:
            kind = (ra.get("aio") or {}).get("mention_kind")
            if kind and kind != "none":
                aio.append({"keyword": kw, "engine": eng, "kind": kind})
        if row.get("mention_found") and (ra.get("prominence") == "leading"):
            leading.append({"keyword": kw, "engine": eng})

    # Untracked competitors the AIs surfaced + the source-type mix (aggregated
    # across the batch), and the cross-engine consensus on who wins (+ why).
    discovered: dict[str, dict] = {}
    source_types: dict[str, int] = {}
    tracked_lower = {n.lower() for n in competitors}
    for r in rows:
        if r.get("status") != "completed":
            continue
        ra = r.get("response_analysis") or {}
        for d in ra.get("discovered_competitors") or []:
            name = (d.get("name") or "").strip()
            if not name:
                continue
            entry = discovered.setdefault(name.lower(), {"name": name, "engines": set(), "attributes": []})
            if r.get("engine"):
                entry["engines"].add(r["engine"])
            for a in d.get("attributes") or []:
                if a and a not in entry["attributes"]:
                    entry["attributes"].append(a)
        for t, n in (ra.get("sources") or {}).get("by_type", {}).items():
            source_types[t] = source_types.get(t, 0) + n

    discovered_list = sorted(
        ({"name": v["name"], "count": len(v["engines"]), "attributes": v["attributes"][:4]}
         for v in discovered.values() if v["name"].lower() not in tracked_lower),
        key=lambda d: (-d["count"], d["name"].lower()),
    )
    consensus = brand_analysis.consensus_rollup(
        [r for r in rows if not r.get("is_competitor_scan")], brand=""
    ).get("businesses", [])

    return {
        "overall": {"total": overall_total, "found": overall_found, "pct": _pct(overall_found, overall_total)},
        "engines": {e: {**v, "pct": _pct(v["found"], v["total"])} for e, v in engines.items()},
        "by_keyword": by_keyword,
        "invisible": invisible,
        "competitors": {n: {**v, "pct": _pct(v["found"], v["total"])} for n, v in competitors.items()},
        "accuracy": accuracy,
        "aio": aio,
        "leading": leading,
        "discovered": discovered_list,
        "consensus": consensus,
        "source_types": source_types,
    }


def _cell(s) -> str:
    """Make a value safe inside a Markdown table cell (escape pipes, flatten newlines)."""
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


# Bound the doc length: show full diagnoses for the worst few keywords, and cap
# the discovered/consensus lists. Everything else degrades gracefully.
_MAX_DIAGNOSES = 6
_MAX_LIST = 8


def render_markdown(client_name: str, date_str: str, snapshot: dict, narrative: str = "") -> str:
    """Render the snapshot as the Google Doc's Markdown body. Pure."""
    o = snapshot["overall"]
    lines = [
        f"# AI Visibility Report — {client_name}",
        f"_{date_str}_",
        "",
        f"**Overall visibility: {o['pct']}%** — the brand appeared in {o['found']} of "
        f"{o['total']} AI answers checked.",
        "",
    ]
    if narrative:
        lines += ["## Summary", narrative, ""]

    # Possible misinformation first — it's the most urgent thing to act on.
    accuracy = snapshot.get("accuracy") or []
    if accuracy:
        lines += ["## ⚠ Possible misinformation", "",
                  "AI assistants stated the following about your business that don't match your records:", ""]
        for f in accuracy:
            lines.append(
                f"- **{_cell(f.get('field', 'detail'))}** — {ENGINE_LABELS.get(f['engine'], f['engine'])} said "
                f"\"{_cell(f.get('stated'))}\" (on file: \"{_cell(f.get('actual'))}\") for “{_cell(f['keyword'])}”"
            )
        lines.append("")

    lines += ["## Visibility by engine", "", "| Engine | Visible | Checked | Rate |", "|---|---|---|---|"]
    for e in ENGINE_ORDER:
        s = snapshot["engines"][e]
        lines.append(f"| {ENGINE_LABELS[e]} | {s['found']} | {s['total']} | {s['pct']}% |")
    lines.append("")

    # Keyword × engine matrix
    header = "| Keyword | " + " | ".join(ENGINE_LABELS[e] for e in ENGINE_ORDER) + " |"
    sep = "|---|" + "|".join(["---"] * len(ENGINE_ORDER)) + "|"
    lines += ["## Keyword detail", "", header, sep]
    for kw, cells in snapshot["by_keyword"].items():
        marks = []
        for e in ENGINE_ORDER:
            v = cells.get(e)
            marks.append("✅" if v == "found" else "❌" if v == "not" else "—")
        lines.append(f"| {_cell(kw)} | " + " | ".join(marks) + " |")
    lines.append("")

    # Standout (leading) mentions — where the brand is the top recommendation.
    leading = snapshot.get("leading") or []
    if leading:
        by_kw: dict[str, list] = {}
        for item in leading:
            by_kw.setdefault(item["keyword"], []).append(ENGINE_LABELS.get(item["engine"], item["engine"]))
        lines += ["## Standout mentions", "",
                  "The brand is a *leading* recommendation here:", ""]
        for kw, engs in by_kw.items():
            lines.append(f"- **{_cell(kw)}** — {', '.join(engs)}")
        lines.append("")

    # Google AI Overview link status — inline link vs citation-only.
    aio = snapshot.get("aio") or []
    if aio:
        lines += ["## Google AI Overview presence", "",
                  "How the brand appears in Google's AI answers (an inline link is stronger than a citation):", ""]
        for item in aio:
            lines.append(
                f"- **{_cell(item['keyword'])}** ({ENGINE_LABELS.get(item['engine'], item['engine'])}) — "
                f"{_AIO_KIND_LABELS.get(item['kind'], item['kind'])}"
            )
        lines.append("")

    # Where you're invisible — grouped by keyword, with the grounded diagnosis
    # for the worst few (capped so the doc stays readable).
    if snapshot["invisible"]:
        grouped: dict[str, dict] = {}
        for item in snapshot["invisible"]:
            g = grouped.setdefault(item["keyword"], {"engines": [], "diagnosis": None})
            g["engines"].append(ENGINE_LABELS.get(item["engine"], item["engine"]))
            if not g["diagnosis"] and item.get("diagnosis"):
                g["diagnosis"] = item["diagnosis"]
        ordered = sorted(grouped.items(), key=lambda kv: -len(kv[1]["engines"]))
        lines += ["## Where you're invisible & why", ""]
        shown = 0
        for kw, g in ordered:
            lines.append(f"### {_cell(kw)}")
            lines.append(f"Not shown by: {', '.join(g['engines'])}")
            if g["diagnosis"] and shown < _MAX_DIAGNOSES:
                lines += ["", g["diagnosis"]]
                shown += 1
            lines.append("")

    # Untracked competitors the AIs surfaced.
    discovered = snapshot.get("discovered") or []
    if discovered:
        lines += ["## Competitors the AIs surfaced (not yet tracked)", ""]
        for d in discovered[:_MAX_LIST]:
            attrs = f" — {_cell(', '.join(d['attributes']))}" if d.get("attributes") else ""
            engs = f"{d['count']} engine{'s' if d['count'] != 1 else ''}"
            lines.append(f"- **{_cell(d['name'])}** ({engs}){attrs}")
        lines.append("")

    # Who's winning across engines & why (the themes the answers reward).
    consensus = [c for c in (snapshot.get("consensus") or []) if c.get("attributes")]
    if consensus:
        lines += ["## What the winning answers reward", ""]
        for c in consensus[:_MAX_LIST]:
            lines.append(f"- **{_cell(c['name'])}** — {_cell(', '.join(c['attributes']))}")
        lines.append("")

    # What kinds of sources the AIs trust for these queries.
    source_types = snapshot.get("source_types") or {}
    if source_types:
        parts = [
            f"{SOURCE_TYPE_LABELS.get(t, t)}: {n}"
            for t, n in sorted(source_types.items(), key=lambda kv: -kv[1])
        ]
        lines += ["## Where the AIs get their information", "",
                  "Source types cited across these answers — good places to be present:",
                  "", _cell(" · ".join(parts)), ""]

    if snapshot["competitors"]:
        lines += ["## Competitor comparison", "", "| Competitor | Visibility |", "|---|---|"]
        lines.append(f"| **{_cell(client_name)} (you)** | {o['pct']}% |")
        for name, s in sorted(snapshot["competitors"].items(), key=lambda kv: -kv[1]["pct"]):
            lines.append(f"| {_cell(name)} | {s['pct']}% |")
        lines.append("")

    return "\n".join(lines)


# ── narrative (best-effort) ──────────────────────────────────────────────────
async def _narrative(client_name: str, snapshot: dict) -> str:
    if not settings.anthropic_api_key:
        return ""
    import anthropic

    engine_lines = "\n".join(
        f"- {ENGINE_LABELS[e]}: {snapshot['engines'][e]['pct']}%" for e in ENGINE_ORDER
    )
    comp_lines = "\n".join(f"- {n}: {s['pct']}%" for n, s in snapshot["competitors"].items()) or "none tracked"

    # Fold the enrichment into the prompt so the summary cites specifics rather
    # than just percentages. All best-effort — empty sections are simply omitted.
    extra = []
    accuracy = snapshot.get("accuracy") or []
    if accuracy:
        extra.append(
            "Possible misinformation to flag (AI stated wrong facts about the business): "
            + "; ".join(f"{a.get('field')}=\"{a.get('stated')}\" (actual \"{a.get('actual')}\")" for a in accuracy[:5])
        )
    discovered = snapshot.get("discovered") or []
    if discovered:
        extra.append("Untracked competitors the AIs surfaced: " + ", ".join(d["name"] for d in discovered[:6]))
    consensus = [c for c in (snapshot.get("consensus") or []) if c.get("attributes")]
    if consensus:
        themes = ", ".join(t for c in consensus[:4] for t in c.get("attributes", [])[:2])
        if themes:
            extra.append(f"Themes the winning answers reward: {themes}")
    aio = snapshot.get("aio") or []
    if aio:
        kinds = {a["kind"] for a in aio}
        extra.append("Google AI Overview presence kinds seen: " + ", ".join(sorted(kinds)))
    source_types = snapshot.get("source_types") or {}
    if source_types:
        top = ", ".join(SOURCE_TYPE_LABELS.get(t, t) for t, _ in sorted(source_types.items(), key=lambda kv: -kv[1])[:3])
        extra.append(f"Source types the AIs cite most: {top}")
    extra_block = ("\n\nAdditional findings to weave in where relevant:\n- " + "\n- ".join(extra)) if extra else ""

    prompt = (
        f"Write a concise executive summary (max 160 words) for an AI-search visibility "
        f"report for the business \"{client_name}\". Overall the brand appeared in "
        f"{snapshot['overall']['pct']}% of AI answers checked.\n\n"
        f"Per-engine visibility:\n{engine_lines}\n\nCompetitor visibility:\n{comp_lines}"
        f"{extra_block}\n\n"
        f"Cover: how visible the brand is in AI assistants, the weakest engines, how it "
        f"compares to competitors, any misinformation to correct, and 2-3 prioritized "
        f"recommendations grounded in the findings above. Plain prose, no headings."
    )
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model=settings.brand_report_model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.get("text", "") for b in resp.model_dump().get("content") or []).strip()
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("brand_report.narrative_failed", extra={"error": str(exc)})
        return ""


# ── enqueue + job ────────────────────────────────────────────────────────────
def enqueue_brand_report(client_id: str) -> str:
    supabase = get_supabase()
    res = (
        supabase.table("async_jobs")
        .insert({"job_type": "brand_report", "entity_id": client_id, "payload": {"client_id": client_id}})
        .execute()
    )
    return res.data[0]["id"]


def _latest_batch_id(supabase, client_id: str) -> str | None:
    rows = (
        supabase.table("brand_mention_history")
        .select("scan_batch_id, created_at")
        .eq("client_id", client_id)
        .eq("is_competitor_scan", False)
        .order("created_at", desc=True)
        .limit(1)
        .execute().data
    )
    return rows[0]["scan_batch_id"] if rows else None


async def run_brand_report_job(job: dict) -> None:
    """async_jobs handler for job_type='brand_report'. Builds + publishes the doc."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    try:
        client_rows = (
            supabase.table("clients").select("name, google_drive_folder_id")
            .eq("id", client_id).limit(1).execute().data
        )
        if not client_rows:
            raise GoogleDocError("client_not_found")
        client = client_rows[0]

        batch_id = _latest_batch_id(supabase, client_id)
        if not batch_id:
            raise GoogleDocError("no_scans_to_report")
        from services.brand_service import list_history
        rows = list_history(client_id, limit=2000, scan_batch_id=batch_id)
        kw_rows = (
            supabase.table("brand_tracked_keywords").select("id, keyword")
            .eq("client_id", client_id).execute().data or []
        )
        labels = {k["id"]: k["keyword"] for k in kw_rows}

        snapshot = build_snapshot(rows, labels)
        narrative = await _narrative(client.get("name") or "", snapshot)
        date_str = datetime.now(timezone.utc).strftime("%-d %b %Y")
        markdown = render_markdown(client.get("name") or "Client", date_str, snapshot, narrative)

        doc = await create_google_doc(
            client.get("google_drive_folder_id"),
            f"AI Visibility Report — {client.get('name')} — {date_str}".strip(" —"),
            markdown,
        )
        supabase.table("async_jobs").update({
            "status": "complete",
            "result": {"doc_url": doc.get("doc_url"), "doc_id": doc.get("doc_id")},
            "completed_at": "now()",
        }).eq("id", job_id).execute()
        logger.info("brand_report.complete", extra={"job_id": job_id, "client_id": client_id})
    except Exception as exc:
        logger.warning("brand_report.failed", extra={"job_id": job_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
