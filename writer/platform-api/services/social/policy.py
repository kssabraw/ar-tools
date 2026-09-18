"""Social Media P3 — the Social Policy write path (PRD §10).

v1 exposes the **consumer fields only** (owner Q3): ``monthly_ceiling_usd`` (the
fail-closed budget ceiling), ``image_prompt_template`` (image-gen steering, already
consumed), and ``text_prompt_template`` (copy-gen steering — wired into
``creator.draft_platform_copy`` in this build). The P4 planning fields
(``autonomy_tier`` / ``allowed_topics`` / ``blocked_topics`` / ``tone_prefs`` /
``competitor_focus`` / ``cadence``) are deferred — cadence config lives in
``social_post_schedules`` (``services/social/schedules.py``), not ``social_policy.cadence``.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from config import settings
from services.social import budget

logger = logging.getLogger(__name__)

# The columns the v1 write path may set (owner Q3 — consumer fields only).
_EDITABLE = ("monthly_ceiling_usd", "image_prompt_template", "text_prompt_template")


def _assert_enabled() -> None:
    if not settings.social_enabled:
        raise HTTPException(status_code=503, detail="social_not_enabled")


def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


def get_policy(client_id: str) -> dict:
    """The client's Social Policy (consumer fields) plus the effective monthly ceiling
    (their value when set, else the configured default). Defaults when no row exists."""
    rows = (
        _sb().table("social_policy")
        .select("monthly_ceiling_usd, image_prompt_template, text_prompt_template")
        .eq("client_id", client_id).limit(1).execute()
    ).data or []
    row = rows[0] if rows else {}
    return {
        "monthly_ceiling_usd": row.get("monthly_ceiling_usd"),
        "image_prompt_template": row.get("image_prompt_template"),
        "text_prompt_template": row.get("text_prompt_template"),
        "effective_ceiling_usd": budget.resolve_ceiling(row or None),
        "default_ceiling_usd": round(float(settings.social_monthly_ceiling_default_usd), 2),
    }


def text_prompt_template(client_id: str) -> str | None:
    """The client's copy-gen steering template, if set (consumed by the copy prompt)."""
    try:
        rows = (
            _sb().table("social_policy").select("text_prompt_template")
            .eq("client_id", client_id).limit(1).execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001 — best-effort read; steering is optional
        logger.warning("social.text_template_read_failed", extra={"client_id": client_id, "error": str(exc)})
        return None
    val = (rows[0].get("text_prompt_template") if rows else None) or None
    return val


def upsert_policy(client_id: str, fields: dict) -> dict:
    """Set the client's Social Policy consumer fields. Only the provided (unset-excluded)
    editable keys change; a null value clears that field (monthly_ceiling_usd→default,
    templates→no custom steering). A non-positive ceiling is rejected (422)."""
    _assert_enabled()
    update = {k: v for k, v in (fields or {}).items() if k in _EDITABLE}
    if "monthly_ceiling_usd" in update and update["monthly_ceiling_usd"] is not None:
        try:
            if float(update["monthly_ceiling_usd"]) <= 0:
                raise HTTPException(status_code=422, detail="social_ceiling_must_be_positive")
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="social_ceiling_invalid")
    if not update:
        return get_policy(client_id)
    update["client_id"] = client_id
    update["updated_at"] = "now()"
    _sb().table("social_policy").upsert(update, on_conflict="client_id").execute()
    return get_policy(client_id)
