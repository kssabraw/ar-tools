"""Board reports — SerMaStr / DORA / PACE as department heads to the L10 board.

Owner ask (2026-09-14): the three agents should report to the Monday-noon L10 as
department heads to a C-suite board. A status digest lists exceptions; a board
report leads with a verdict, contextualizes every number, covers the whole
portfolio (green included), and ends with what the head needs from the board.

Each report is the same six-part shape (`common.BoardReport`) — verdict+RAG,
scorecard, wins, risks & actions, asks, outlook — assembled deterministically
from data the suite already produces, with an optional best-effort LLM
department-head memo on top. Weekly on the shared scheduler, gated on
`board_reports_enabled`. Doc: docs/modules/board-reports-plan-v1_0.md.

`run_weekly_board_reports(today)` is the scheduler entry point; the three
`*_board.build_report()` functions are the deterministic assemblers.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


def run_weekly_board_reports(today: Optional[date] = None) -> dict:
    """Build + emit all three board reports. Self-gated on
    ``board_reports_enabled``; each report is isolated so one failing never
    stops the others. Best-effort — returns a per-report summary, never raises."""
    today = today or date.today()
    if not settings.board_reports_enabled:
        return {"emitted": False, "reason": "disabled"}

    from services.board_reports import client_board, director_board, pace_board

    results: dict[str, dict] = {}
    for name, fn in (
        ("pace", pace_board.run),
        ("director", director_board.run),
        ("client", client_board.run),
    ):
        try:
            results[name] = fn(today)
        except Exception as exc:  # noqa: BLE001 — one report never breaks the others
            logger.warning("board_reports.run_failed", extra={"report": name, "error": str(exc)})
            results[name] = {"emitted": False, "reason": "error", "error": str(exc)[:200]}
    return {"emitted": True, "reports": results}
