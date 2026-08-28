"""Intervention-outcome loop — read surface (services/interventions.py).

GET /clients/{id}/interventions  the client's interventions + per-tactic
                                 effectiveness rollup (report-only in v1).

No mutation endpoint: interventions are registered by the proposal-approve /
task-done hooks and evaluated by the daily sweep — never created by hand.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from config import settings
from middleware.auth import require_auth
from services import interventions

router = APIRouter(tags=["interventions"])


@router.get("/clients/{client_id}/interventions")
async def list_client_interventions(
    client_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """The client's interventions (newest first) + the per-tactic effectiveness
    rollup. `enabled` reflects the feature flag so the UI can show a dormant
    state without guessing."""
    rows = interventions.list_interventions(str(client_id))
    return {
        "enabled": settings.intervention_tracking_enabled,
        "interventions": rows,
        "effectiveness": interventions.summarize_effectiveness(rows),
    }
