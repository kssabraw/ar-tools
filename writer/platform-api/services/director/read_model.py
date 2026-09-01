"""Director of Operations — the read model (build spec §4).

``build_read_model(client_id, today)`` assembles the cross-agent state SerMaStr
answers Director questions from and the daily reconcile pass (§6.1) acts on.
``client_id=None`` is the portfolio read; a real id scopes to one client.

Every provider call is isolated in its own try/except (mirrors
``slack_assistant/context.py::build_context``'s ``_ctx_*`` isolation) so one
module failing degrades the model to a gap, never breaks the read. The
delivery/assignment providers reuse ONE call to the shared PACE board read
(``pm_signals.build_board_digest``) rather than querying fresh — the same
data ``pace_episodes``/``pace_digest`` already compute.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import pm_signals
from services.director import providers, seams

logger = logging.getLogger(__name__)


def _isolate(name: str, fn, *args):
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 — one provider's failure is a gap, not a crash
        logger.warning("director.provider_failed", extra={"provider": name, "error": str(exc)})
        return None


def build_read_model(client_id: Optional[str], today: Optional[date] = None) -> dict:
    """The full cross-agent read: one client (``client_id`` set) or portfolio
    (``None`` — every client the shared board read surfaces). Read-only,
    best-effort, deterministic. Never raises."""
    today = today or date.today()
    supabase = get_supabase()

    board = _isolate("board", pm_signals.build_board_digest, client_id, today) or {
        "as_of": today.isoformat(),
        "clients": [],
        "workload": {},
    }
    client_ids: Optional[list[str]] = (
        [client_id] if client_id else [c["client_id"] for c in board.get("clients", []) if c.get("client_id")]
    )

    model: dict = {
        "as_of": today.isoformat(),
        "client_id": client_id,
        "portfolio": client_id is None,
        "delivery": _isolate("delivery", providers.prov_delivery, board),
        "assignment": _isolate("assignment", providers.prov_assignment, supabase, board, client_ids),
        "strategy": _isolate("strategy", providers.prov_strategy, supabase, client_ids, today),
        "autonomy": _isolate("autonomy", providers.prov_autonomy, supabase, client_ids, today),
        "producers": _isolate("producers", providers.prov_producers, supabase, client_ids, today),
        "interventions": _isolate("interventions", providers.prov_interventions, supabase, client_ids, today),
        # qa_idle is a portfolio predicate (§2.3) — always read globally, even
        # inside a per-client model, so "is anything reaching QA at all" never
        # depends on which client was asked about.
        "qa": _isolate("qa", providers.prov_qa, supabase, today),
        "content": _isolate("content", providers.prov_content, supabase, client_ids, today),
        "duplicates": _isolate("duplicates", providers.prov_duplicates, supabase, client_ids, today),
        # WS2/WS4: PACE's process-efficiency findings addressed to DORA.
        "pace_efficiency": _isolate("pace_efficiency", providers.prov_pace_efficiency,
                                    supabase, client_ids, today),
        # WS3/WS4: agent-to-agent coordination health (bus blockers/stalls/loops).
        "coordination": _isolate("coordination", providers.prov_coordination,
                                  supabase, client_ids, today),
    }

    thresholds = {
        "approved_unplaced_days": settings.director_seam_approved_unplaced_days,
        "proposal_pending_days": settings.director_seam_proposal_pending_days,
        "qa_idle_days": settings.director_seam_qa_idle_days,
        "autonomy_unactioned_days": settings.director_seam_autonomy_unactioned_days,
    }
    model["flow"] = _isolate("flow", seams.compute_flags, model, today, thresholds) or {
        "flags": [],
        "count": 0,
    }
    return model
