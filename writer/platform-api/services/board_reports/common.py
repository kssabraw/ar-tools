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
    "or change a number), write a 2–4 sentence spoken-voice summary of your "
    "department this week. Lead with the verdict, name the one or two things that "
    "matter most, and if there is an ask of the board, close with it plainly. "
    "Slack mrkdwn only: *bold* for emphasis, no headings, no tables, no bullet "
    "lists. Be direct and specific; no filler."
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
# Emit (I/O)
# ---------------------------------------------------------------------------
def emit_report(report: dict, *, kind: str, today: date, link: str) -> dict:
    """Render + emit one board report via the shared notifications pipe. Deduped
    per ISO week; severity follows the RAG. Best-effort."""
    from services import notifications

    agent = report.get("agent", kind)
    body = render_report(report)
    severity = "warning" if report.get("rag") == "red" else "info"
    nid = notifications.emit(
        client_id=None,
        kind=kind,
        title=report.get("title", "Board report"),
        summary=body,
        severity=severity,
        payload={"link": link},
        dedupe_key=week_dedupe_key(agent, today),
    )
    return {"emitted": nid is not None, "deduped": nid is None, "rag": report.get("rag")}
