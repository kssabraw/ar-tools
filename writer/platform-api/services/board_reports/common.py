"""Board reports — the shared six-part shape, render, memo, and emit.

A ``BoardReport`` is a plain dict (verdict+RAG · scorecard · wins · risks &
actions · asks · outlook · optional rows · optional narrative). The three
assemblers (`pace_board` / `director_board` / `client_board`) each build one and
call `emit_report`. Render + RAG helpers are pure (unit-tested); `attach_narrative`
does the best-effort LLM memo and `emit_report` does the notification I/O.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

RAG_ORDER = {"green": 0, "yellow": 1, "red": 2}
RAG_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
RAG_WORD = {"green": "on track", "yellow": "watch", "red": "action needed"}


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def worst_rag(rags) -> str:
    """The most severe RAG in the iterable (red > yellow > green). Empty → green.
    Pure."""
    out = "green"
    for r in rags:
        if RAG_ORDER.get(r, 0) > RAG_ORDER.get(out, 0):
            out = r
    return out


def pct_delta(current: Optional[float], previous: Optional[float]) -> Optional[str]:
    """A '+3' / '−2 (−12%)' style delta string vs the prior period, or None when
    there's no comparable baseline. Pure."""
    if current is None or previous is None:
        return None
    diff = current - previous
    if diff == 0:
        return "flat"
    sign = "+" if diff > 0 else "−"
    body = f"{sign}{abs(round(diff, 2)):g}"
    if previous:
        body += f" ({sign}{abs(round(diff / previous * 100)):g}%)"
    return body


def _scorecard_line(item: dict) -> str:
    label = item.get("label", "")
    value = item.get("value", "")
    line = f"• {label}: *{value}*"
    if item.get("delta"):
        line += f" ({item['delta']})"
    if item.get("target"):
        line += f" vs target {item['target']}"
    return line


def _risk_line(r: dict) -> str:
    sev = f"[{r['severity']}] " if r.get("severity") else ""
    line = f"• {sev}{r.get('issue', '')} → {r.get('action', '')}"
    tail = ", ".join(x for x in (r.get("owner"), r.get("eta")) if x)
    if tail:
        line += f" ({tail})"
    return line


def render_report(report: dict) -> str:
    """The deterministic board-report body as Slack mrkdwn. Pure — the numbers,
    verdict, and every section come from the assembled ``report`` dict. Leads with
    the department-head memo when one is attached."""
    rag = report.get("rag", "green")
    emoji = RAG_EMOJI.get(rag, "")
    parts: list[str] = [
        f"*{report.get('title', 'Board report')}* — {emoji} {report.get('verdict', '')}".rstrip()
    ]
    if report.get("as_of"):
        parts[0] += f"  ·  _as of {report['as_of']}_"

    if report.get("narrative"):
        parts.append(report["narrative"])

    scorecard = report.get("scorecard") or []
    if scorecard:
        parts.append("*Scorecard*\n" + "\n".join(_scorecard_line(i) for i in scorecard))

    rows = report.get("rows") or {}
    items = rows.get("items") or []
    if items:
        rendered = []
        for it in items:
            re = RAG_EMOJI.get(it.get("rag"), "") if it.get("rag") else ""
            prefix = f"{re} " if re else "• "
            rendered.append(f"{prefix}*{it.get('name', '')}* — {it.get('line', '')}")
        parts.append(f"*{rows.get('title', 'Detail')}*\n" + "\n".join(rendered))

    cases = report.get("cases") or {}
    citems = cases.get("items") or []
    if citems:
        blocks = []
        for c in citems:
            ce = RAG_EMOJI.get(c.get("rag"), "") if c.get("rag") else ""
            head = f"{ce} *{c.get('name', '')}*".strip()
            lines = [f"    _{d.get('label')}:_ {d.get('text')}" for d in (c.get("detail") or []) if d.get("text")]
            blocks.append(head + ("\n" + "\n".join(lines) if lines else ""))
        parts.append(f"*{cases.get('title', 'Detail')}*\n" + "\n\n".join(blocks))

    if report.get("wins"):
        parts.append("*Wins*\n" + "\n".join(f"• {w}" for w in report["wins"]))

    if report.get("risks"):
        parts.append("*Risks & actions*\n" + "\n".join(_risk_line(r) for r in report["risks"]))

    asks = report.get("asks") or []
    parts.append(
        "*Asks of the board*\n" + ("\n".join(f"• {a}" for a in asks) if asks else "• None this week.")
    )

    if report.get("outlook"):
        parts.append(f"*Outlook*\n{report['outlook']}")

    return "\n\n".join(parts)


def monday_of(today: date) -> date:
    return today - timedelta(days=today.weekday())


def week_dedupe_key(agent: str, today: date) -> str:
    """Stable per ISO week so a redeploy re-run is a clean DB-level no-op. Pure."""
    iso_year, iso_week, _ = today.isocalendar()
    return f"board_report:{agent}:{iso_year}-W{iso_week:02d}"


# ---------------------------------------------------------------------------
# Narrative memo (best-effort LLM — never raises, degrades to "")
# ---------------------------------------------------------------------------
_MEMO_SYSTEM = (
    "You are {persona}, a department head giving your weekly report to the C-suite "
    "board of an SEO agency. From the FACTS below (already computed — never invent "
    "or change a number, name, or diagnosis), write a substantive executive "
    "narrative of your department this week: a few short paragraphs (up to ~8 "
    "sentences). Lead with the verdict, then explain the story BEHIND the numbers "
    "and each flagged item — the who (client, teammate, competitor), what, where "
    "(market / keyword / channel), why (the root cause / diagnosis), and how "
    "(what's being done or is needed). Draw the who/what/why/how from the CASES and "
    "risks in the facts — cite the specific names, keywords, and diagnoses given "
    "there; do not restate the scorecard counts mechanically. Close with the ask of "
    "the board if there is one. Slack mrkdwn only: *bold* for emphasis, no headings, "
    "no tables. Be specific and concrete; no filler."
)


def attach_narrative(report: dict, persona: str) -> None:
    """Best-effort: set ``report['narrative']`` to a short department-head memo.
    Gated on ``board_reports_narrative_enabled``; any failure leaves it unset so
    the deterministic report still ships. Never raises."""
    if not settings.board_reports_narrative_enabled:
        return
    facts = {
        "verdict": report.get("verdict"),
        "status": report.get("rag"),
        "scorecard": report.get("scorecard"),
        "cases": (report.get("cases") or {}).get("items"),
        "wins": report.get("wins"),
        "risks": report.get("risks"),
        "asks": report.get("asks"),
        "outlook": report.get("outlook"),
    }
    try:
        from services import report_llm

        text = report_llm.generate_text_sync(
            system=_MEMO_SYSTEM.format(persona=persona),
            user="FACTS:\n" + json.dumps(facts, default=str),
            max_tokens=settings.board_reports_narrative_max_tokens,
            provider=settings.board_reports_narrative_provider,
            model=settings.board_reports_narrative_model,
            log_tag="board_report_memo",
        )
        if text and text.strip():
            report["narrative"] = text.strip()
    except Exception as exc:  # noqa: BLE001 — the memo is polish, the report ships regardless
        logger.warning(
            "board_reports.memo_failed", extra={"persona": persona, "error": str(exc)}
        )


# ---------------------------------------------------------------------------
# HTML render (for the PDF copy) — pure
# ---------------------------------------------------------------------------
_RAG_HTML = {
    "green": ("#1a7f37", "#dafbe1"),
    "yellow": ("#9a6700", "#fff8c5"),
    "red": ("#cf222e", "#ffebe9"),
}


def _esc(s) -> str:
    return (
        str(s if s is not None else "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def render_html(report: dict) -> str:
    """A standalone, self-contained HTML document for the PDF copy of a board
    report. Pure — same content as ``render_report``, laid out for print."""
    rag = report.get("rag", "green")
    fg, bg = _RAG_HTML.get(rag, ("#57606a", "#eaeef2"))
    emoji = RAG_EMOJI.get(rag, "")
    h: list[str] = []

    h.append(f"<h1>{_esc(report.get('title', 'Board report'))}</h1>")
    if report.get("as_of"):
        h.append(f"<p class='asof'>As of {_esc(report['as_of'])}</p>")
    h.append(
        f"<div class='verdict' style='color:{fg};background:{bg}'>"
        f"{emoji} {_esc(report.get('verdict', ''))}</div>"
    )
    if report.get("narrative"):
        h.append(f"<p class='memo'>{_esc(report['narrative'])}</p>")

    scorecard = report.get("scorecard") or []
    if scorecard:
        h.append("<h2>Scorecard</h2><table class='sc'>")
        for it in scorecard:
            extra = []
            if it.get("delta"):
                extra.append(_esc(it["delta"]))
            if it.get("target"):
                extra.append("vs target " + _esc(it["target"]))
            tail = f" <span class='muted'>({'; '.join(extra)})</span>" if extra else ""
            h.append(
                f"<tr><td class='lbl'>{_esc(it.get('label'))}</td>"
                f"<td class='val'>{_esc(it.get('value'))}{tail}</td></tr>"
            )
        h.append("</table>")

    rows = report.get("rows") or {}
    items = rows.get("items") or []
    if items:
        h.append(f"<h2>{_esc(rows.get('title', 'Detail'))}</h2><table class='rows'>")
        for it in items:
            dot_fg, _ = _RAG_HTML.get(it.get("rag"), ("#57606a", ""))
            dot = f"<span class='dot' style='background:{dot_fg}'></span>" if it.get("rag") else ""
            h.append(
                f"<tr><td class='nm'>{dot}{_esc(it.get('name'))}</td>"
                f"<td>{_esc(it.get('line'))}</td></tr>"
            )
        h.append("</table>")

    cases = report.get("cases") or {}
    citems = cases.get("items") or []
    if citems:
        h.append(f"<h2>{_esc(cases.get('title', 'Detail'))}</h2>")
        for c in citems:
            dot_fg, _ = _RAG_HTML.get(c.get("rag"), ("#57606a", ""))
            dot = f"<span class='dot' style='background:{dot_fg}'></span>" if c.get("rag") else ""
            h.append(f"<div class='case'><div class='case-h'>{dot}{_esc(c.get('name'))}</div>")
            for d in (c.get("detail") or []):
                if not d.get("text"):
                    continue
                h.append(
                    f"<div class='case-d'><span class='case-l'>{_esc(d.get('label'))}:</span> "
                    f"{_esc(d.get('text'))}</div>"
                )
            h.append("</div>")

    def _list(title: str, items_):
        if not items_:
            return
        h.append(f"<h2>{title}</h2><ul>")
        for x in items_:
            h.append(f"<li>{_esc(x)}</li>")
        h.append("</ul>")

    _list("Wins", report.get("wins"))

    risks = report.get("risks") or []
    if risks:
        h.append("<h2>Risks &amp; actions</h2><ul>")
        for r in risks:
            sev = f"<b>[{_esc(r['severity'])}]</b> " if r.get("severity") else ""
            tail = ", ".join(_esc(x) for x in (r.get("owner"), r.get("eta")) if x)
            tail = f" <span class='muted'>({tail})</span>" if tail else ""
            h.append(f"<li>{sev}{_esc(r.get('issue'))} → {_esc(r.get('action'))}{tail}</li>")
        h.append("</ul>")

    asks = report.get("asks") or []
    h.append("<h2>Asks of the board</h2>")
    if asks:
        h.append("<ul>" + "".join(f"<li>{_esc(a)}</li>" for a in asks) + "</ul>")
    else:
        h.append("<p class='muted'>None this week.</p>")

    if report.get("outlook"):
        h.append(f"<h2>Outlook</h2><p>{_esc(report['outlook'])}</p>")

    style = (
        "body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
        "color:#1f2328;margin:0;font-size:12px;line-height:1.5}"
        "h1{font-size:19px;margin:0 0 2px}"
        "h2{font-size:13px;margin:18px 0 6px;border-bottom:1px solid #d0d7de;padding-bottom:3px}"
        ".asof{color:#57606a;margin:0 0 12px;font-size:11px}"
        ".verdict{font-size:14px;font-weight:600;padding:10px 12px;border-radius:6px;margin:0 0 12px}"
        ".memo{font-style:italic;color:#24292f;margin:0 0 8px}"
        "table{border-collapse:collapse;width:100%}"
        "table.sc td,table.rows td{padding:4px 8px;border-bottom:1px solid #eaeef2;vertical-align:top}"
        ".sc .lbl{color:#57606a;width:55%}.sc .val{font-weight:600}"
        ".rows .nm{font-weight:600;width:32%;white-space:nowrap}"
        ".dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}"
        ".muted{color:#57606a;font-weight:400}"
        "ul{margin:4px 0;padding-left:18px}li{margin:2px 0}"
        ".case{margin:0 0 12px;padding:8px 10px;border:1px solid #eaeef2;border-radius:6px}"
        ".case-h{font-weight:600;font-size:13px;margin-bottom:4px}"
        ".case-d{margin:2px 0}.case-l{color:#57606a;font-weight:600}"
    )
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{style}</style></head><body>{''.join(h)}</body></html>"


def maybe_publish_pdf(report: dict) -> dict:
    """Best-effort: render the board report to PDF and upload it to the configured
    Google Drive folder. Gated on ``board_reports_drive_folder_id`` +
    ``google_apps_script_url``; any failure is swallowed (Slack/in-app already
    shipped). Designed to run inside the scheduler's worker thread (off the event
    loop), so the async Drive upload is driven with ``asyncio.run``."""
    folder = settings.board_reports_drive_folder_id
    if not folder or not settings.google_apps_script_url:
        return {"published": False, "reason": "not_configured"}
    try:
        import asyncio

        from services import client_report, google_docs

        pdf = client_report.render_pdf(render_html(report))
        title = report.get("title", "Board report")
        result = asyncio.run(google_docs.upload_pdf(folder, title, pdf))
        return {"published": True, "file_url": result.get("file_url")}
    except Exception as exc:  # noqa: BLE001 — the PDF copy is additive; the report already shipped
        logger.warning(
            "board_reports.pdf_failed",
            extra={"agent": report.get("agent"), "error": str(exc)},
        )
        return {"published": False, "reason": "error"}


# ---------------------------------------------------------------------------
# Emit (I/O)
# ---------------------------------------------------------------------------
def emit_report(report: dict, *, kind: str, today: date, link: str) -> dict:
    """Deliver one board report. Owner ruling 2026-09-14: PDF-only by default —
    publish the PDF copy to the configured Drive folder, and post to Slack + the
    in-app feed ONLY when ``board_reports_slack_enabled`` is on. Deduped per ISO
    week; severity follows the RAG. Best-effort throughout."""
    pdf = maybe_publish_pdf(report)

    nid = None
    if settings.board_reports_slack_enabled:
        from services import notifications

        agent = report.get("agent", kind)
        severity = "warning" if report.get("rag") == "red" else "info"
        nid = notifications.emit(
            client_id=None,
            kind=kind,
            title=report.get("title", "Board report"),
            summary=render_report(report),
            severity=severity,
            payload={"link": link},
            dedupe_key=week_dedupe_key(agent, today),
        )
    return {
        "emitted": nid is not None, "deduped": nid is None,
        "rag": report.get("rag"), "pdf": pdf, "slack": settings.board_reports_slack_enabled,
    }
