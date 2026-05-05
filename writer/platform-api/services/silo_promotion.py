"""Silo promotion (Platform PRD v1.4 §7.7.3).

Converts an approved silo candidate into a new pipeline run. Mirrors
`POST /runs` shape (client_context snapshot + dispatcher call) but
sources keyword + intent from the candidate row.
"""

from __future__ import annotations

import logging
from typing import Optional

from db.supabase_client import get_supabase
from services.file_parser import detect_format
from services.orchestrator import NON_TERMINAL_STATUSES, orchestrate_run

logger = logging.getLogger(__name__)


class PromotionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_PROMOTABLE_FROM = {"proposed", "approved", "published"}


def in_flight_run_count() -> int:
    """Count current non-terminal runs (matches §7.3 5-run cap)."""
    supabase = get_supabase()
    in_flight = (
        supabase.table("runs")
        .select("id", count="exact")
        .in_("status", list(NON_TERMINAL_STATUSES))
        .execute()
    )
    return in_flight.count or 0


def _client_with_context(client_id: str) -> dict:
    supabase = get_supabase()
    res = (
        supabase.table("clients")
        .select("*")
        .eq("id", client_id)
        .single()
        .execute()
    )
    return res.data or {}


def _create_snapshot(run_id: str, client: dict) -> None:
    supabase = get_supabase()
    brand_text = client.get("brand_guide_text") or ""
    icp_text = client.get("icp_text") or ""
    website_analysis = client.get("website_analysis")
    website_unavailable = (
        website_analysis is None
        or client.get("website_analysis_status") != "complete"
    )
    supabase.table("client_context_snapshots").insert(
        {
            "run_id": run_id,
            "client_id": client["id"],
            "brand_guide_text": brand_text,
            "brand_guide_format": detect_format(brand_text, "text/plain"),
            "icp_text": icp_text,
            "icp_format": detect_format(icp_text, "text/plain"),
            "website_analysis": website_analysis,
            "website_analysis_unavailable": website_unavailable,
        }
    ).execute()


def promote_candidate(
    candidate_id: str,
    *,
    user_id: str,
    enforce_concurrency_cap: bool = True,
    max_concurrent: int = 5,
) -> dict:
    """Create a new run from a silo candidate. Returns {run_id, candidate_id, status}.

    Behavior (PRD §7.7.3):
      1. Validate candidate state (proposed/approved/published) and client active
      2. Create runs row with keyword, client_id, intent_override = candidate.estimated_intent
      3. Create client_context_snapshot
      4. Update candidate: status=in_progress, promoted_to_run_id=new_run.id,
         last_promotion_failed_at=null
      5. Caller (router) is responsible for dispatching `orchestrate_run`
         in a BackgroundTasks; this function returns synchronously.

    Raises PromotionError on validation failure (caller maps to 422/409/etc.).
    """
    supabase = get_supabase()

    cand_res = (
        supabase.table("silo_candidates")
        .select("*")
        .eq("id", candidate_id)
        .single()
        .execute()
    )
    if not cand_res.data:
        raise PromotionError("candidate_not_found", "Silo candidate does not exist")
    cand = cand_res.data

    if cand["status"] not in _PROMOTABLE_FROM:
        raise PromotionError(
            "invalid_status",
            f"Cannot promote a candidate in status {cand['status']!r}; "
            f"must be one of {sorted(_PROMOTABLE_FROM)}.",
        )

    client = _client_with_context(cand["client_id"])
    if not client:
        raise PromotionError("client_not_found", "Owning client does not exist")
    if client.get("archived"):
        raise PromotionError("client_archived", "Cannot promote silo for archived client")

    if enforce_concurrency_cap and in_flight_run_count() >= max_concurrent:
        raise PromotionError(
            "concurrency_limit",
            f"At most {max_concurrent} runs may be in flight at once",
        )

    intent_override: Optional[str] = cand.get("estimated_intent")

    run_res = (
        supabase.table("runs")
        .insert(
            {
                "client_id": cand["client_id"],
                "keyword": cand["suggested_keyword"],
                "intent_override": intent_override,
                "sie_outlier_mode": "safe",
                "sie_force_refresh": False,
                "status": "queued",
                "created_by": user_id,
            }
        )
        .execute()
    )
    run_id = run_res.data[0]["id"]

    _create_snapshot(run_id, client)

    supabase.table("silo_candidates").update(
        {
            "status": "in_progress",
            "promoted_to_run_id": run_id,
            "last_promotion_failed_at": None,
        }
    ).eq("id", candidate_id).execute()

    logger.info(
        "silo_promoted",
        extra={
            "candidate_id": candidate_id,
            "run_id": run_id,
            "user_id": user_id,
            "keyword": cand["suggested_keyword"],
        },
    )

    return {
        "candidate_id": candidate_id,
        "run_id": run_id,
        "status": "in_progress",
    }
