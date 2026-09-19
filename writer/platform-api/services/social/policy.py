"""Social Media — the Social Policy write path (PRD §10).

P3 exposed the **consumer fields**: ``monthly_ceiling_usd`` (the fail-closed budget
ceiling), ``image_prompt_template`` (image-gen steering), and ``text_prompt_template``
(copy-gen steering — wired into ``creator.draft_platform_copy``). **P4 (Phase A)** opens
the **planning fields** the Social Manager loop tunes on: ``autonomy_tier`` (the
generate→ready→auto-queue ladder), ``allowed_topics`` / ``blocked_topics`` (the topic bank
+ its exclusions), ``tone_prefs`` (angle/tone steering), and ``competitor_focus`` (which
competitors to emphasise). Cadence config lives in ``social_post_schedules``
(``services/social/schedules.py``), NOT ``social_policy.cadence``. ``qa_gate`` lands in
Phase C with the QA rubric that consumes it.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import HTTPException

from config import settings
from services.social import budget

logger = logging.getLogger(__name__)

# The columns the write path may set. Consumer fields (P3) + planning fields (P4 Phase A).
_EDITABLE = (
    "monthly_ceiling_usd", "image_prompt_template", "text_prompt_template",
    "autonomy_tier", "allowed_topics", "blocked_topics", "tone_prefs", "competitor_focus",
    "qa_gate",
)

# The jsonb "list of tags" planning fields (topic bank + competitor focus).
_LIST_FIELDS = ("allowed_topics", "blocked_topics", "competitor_focus")
_MAX_LIST_ITEMS = 100     # a sane ceiling on any one topic/competitor list
_MAX_ITEM_CHARS = 200     # per entry


def clean_str_list(val: Any) -> list[str]:
    """Normalise a topic-bank / competitor-focus value to a clean list of tags: strip each,
    drop empties, dedupe (case-insensitive, first-wins), clamp lengths. Pure. Accepts a list
    or a newline/comma string (a UI textarea), so a stored jsonb string doesn't crash a read."""
    if val is None:
        return []
    if isinstance(val, str):
        raw = [p for chunk in val.split("\n") for p in chunk.split(",")]
    elif isinstance(val, (list, tuple)):
        raw = list(val)
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        s = str(item).strip()[:_MAX_ITEM_CHARS].strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= _MAX_LIST_ITEMS:
            break
    return out


def _assert_enabled() -> None:
    if not settings.social_enabled:
        raise HTTPException(status_code=503, detail="social_not_enabled")


def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


def get_policy(client_id: str) -> dict:
    """The client's Social Policy (consumer + P4 planning fields) plus the effective monthly
    ceiling (their value when set, else the configured default) and read-only autonomy
    context (the tier ceiling + whether the loop is on globally). Defaults when no row exists."""
    cap = int(settings.social_autonomy_cap_tier)
    rows = (
        _sb().table("social_policy")
        .select("monthly_ceiling_usd, image_prompt_template, text_prompt_template, "
                "autonomy_tier, allowed_topics, blocked_topics, tone_prefs, "
                "competitor_focus, qa_gate")
        .eq("client_id", client_id).limit(1).execute()
    ).data or []
    row = rows[0] if rows else {}
    tier = int(row.get("autonomy_tier") or 0)
    return {
        "monthly_ceiling_usd": row.get("monthly_ceiling_usd"),
        "image_prompt_template": row.get("image_prompt_template"),
        "text_prompt_template": row.get("text_prompt_template"),
        "effective_ceiling_usd": budget.resolve_ceiling(row or None),
        "default_ceiling_usd": round(float(settings.social_monthly_ceiling_default_usd), 2),
        "autonomy_tier": max(0, min(tier, cap)),   # clamp a legacy over-cap value on read
        "allowed_topics": clean_str_list(row.get("allowed_topics")),
        "blocked_topics": clean_str_list(row.get("blocked_topics")),
        "tone_prefs": row.get("tone_prefs"),
        "competitor_focus": clean_str_list(row.get("competitor_focus")),
        "qa_gate": bool(row.get("qa_gate")),
        "autonomy_cap_tier": cap,
        "autonomy_enabled": bool(settings.social_autonomy_enabled),
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


def _validate_tier(val: Optional[Any]) -> int:
    """Coerce + range-check autonomy_tier against the configured ceiling (0..cap). Pure."""
    cap = int(settings.social_autonomy_cap_tier)
    try:
        tier = int(val)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="social_autonomy_tier_invalid")
    if not (0 <= tier <= cap):
        raise HTTPException(status_code=422, detail="social_autonomy_tier_out_of_range")
    return tier


def upsert_policy(client_id: str, fields: dict) -> dict:
    """Set the client's Social Policy fields. Only the provided (unset-excluded) editable keys
    change; a null value clears that field (monthly_ceiling_usd→default, templates/tone→none,
    topic lists→empty, autonomy_tier→0/off). A non-positive ceiling or an out-of-range tier is
    rejected (422); topic/competitor lists are normalised (stripped, deduped, clamped)."""
    _assert_enabled()
    update = {k: v for k, v in (fields or {}).items() if k in _EDITABLE}
    if "monthly_ceiling_usd" in update and update["monthly_ceiling_usd"] is not None:
        try:
            if float(update["monthly_ceiling_usd"]) <= 0:
                raise HTTPException(status_code=422, detail="social_ceiling_must_be_positive")
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="social_ceiling_invalid")
    if "autonomy_tier" in update:
        # A null clears the tier back to 0 (off); a value is range-checked.
        update["autonomy_tier"] = 0 if update["autonomy_tier"] is None else _validate_tier(update["autonomy_tier"])
    for k in _LIST_FIELDS:
        if k in update:
            update[k] = clean_str_list(update[k])   # null/[] → [] (clears the list)
    if "tone_prefs" in update and update["tone_prefs"] is not None:
        update["tone_prefs"] = str(update["tone_prefs"]).strip()[:2000] or None
    if "qa_gate" in update:
        update["qa_gate"] = bool(update["qa_gate"])   # null → False (gate off)
    if not update:
        return get_policy(client_id)
    update["client_id"] = client_id
    update["updated_at"] = "now()"
    _sb().table("social_policy").upsert(update, on_conflict="client_id").execute()
    return get_policy(client_id)
