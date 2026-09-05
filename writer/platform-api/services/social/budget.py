"""Social Media module — the fail-closed per-client budget meter (PRD §11).

The backstop against a runaway autonomous social loop. Mirrors
``services/autonomy_budget.py`` exactly — a per-client, per-month DOLLAR meter
whose atomic ``reserve_social_spend`` RPC refuses a charge that would breach the
client's monthly ceiling, and (crucially) **fails CLOSED**: any RPC error refuses
the reservation, so the caller must not spend. Every paid external call (Apify /
TwelveLabs / nano-banana Pro / the posting provider) reserves its estimated cost
before spending it.

The ceiling is the client's ``social_policy.monthly_ceiling_usd`` when set, else
``settings.social_monthly_ceiling_default_usd``. Pure helpers (``month_key``,
``remaining``, ``resolve_ceiling``) are unit-tested; the reads + reservation are
the thin impure layer the Creator/Manager/orchestrator call.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


def month_key(today: Optional[date] = None) -> date:
    """First day of the calendar month — the meter's period key. Pure."""
    d = today or date.today()
    return d.replace(day=1)


def remaining(cap: float, spent: float) -> float:
    """Budget left this period, floored at 0. Pure."""
    return round(max(0.0, float(cap) - float(spent)), 2)


def resolve_ceiling(policy_row: Optional[dict], default: Optional[float] = None) -> float:
    """The client's monthly ceiling: their policy value when set (and > 0), else the
    configured default. Never negative. Pure."""
    dflt = default if default is not None else settings.social_monthly_ceiling_default_usd
    if policy_row:
        val = policy_row.get("monthly_ceiling_usd")
        if val is not None:
            try:
                v = float(val)
                if v > 0:
                    return round(v, 2)
            except (TypeError, ValueError):
                pass
    return round(max(0.0, float(dflt)), 2)


# --- Impure layer -----------------------------------------------------------

def ceiling_for_client(client_id: str) -> float:
    """This month's ceiling for a client, from social_policy (else the default)."""
    from db.supabase_client import get_supabase
    try:
        rows = (
            get_supabase()
            .table("social_policy")
            .select("monthly_ceiling_usd")
            .eq("client_id", client_id)
            .limit(1)
            .execute()
        ).data or []
        return resolve_ceiling(rows[0] if rows else None)
    except Exception as exc:  # noqa: BLE001 — best-effort read; fall back to default
        logger.warning("social_ceiling_read_failed", extra={"client_id": client_id, "error": str(exc)})
        return resolve_ceiling(None)


def spent_this_month(client_id: str, today: Optional[date] = None) -> float:
    """What the client has already spent on social this month (0 if none)."""
    from db.supabase_client import get_supabase
    try:
        rows = (
            get_supabase()
            .table("social_usage")
            .select("spent_usd")
            .eq("client_id", client_id)
            .eq("month", month_key(today).isoformat())
            .limit(1)
            .execute()
        ).data or []
        return float(rows[0]["spent_usd"]) if rows else 0.0
    except Exception as exc:  # noqa: BLE001 — best-effort read
        logger.warning("social_spent_read_failed", extra={"client_id": client_id, "error": str(exc)})
        return 0.0


def reserve(client_id: str, amount: float, *, cap: float, today: Optional[date] = None) -> bool:
    """Atomically reserve ``amount`` against the client's monthly ``cap``.

    Returns True only if the charge fit (the RPC updated the row); False (refused)
    leaves spend unchanged, so the caller must NOT proceed with the paid action.
    A zero/negative amount is a no-op that succeeds. Fails CLOSED on any error.
    """
    if amount <= 0:
        return True
    from db.supabase_client import get_supabase
    try:
        res = get_supabase().rpc(
            "reserve_social_spend",
            {
                "p_client": client_id,
                "p_month": month_key(today).isoformat(),
                "p_amount": float(amount),
                "p_cap": float(cap),
            },
        ).execute()
        return bool(res.data)
    except Exception as exc:  # noqa: BLE001 — a failed reservation must never spend
        logger.warning("social_reserve_failed", extra={"client_id": client_id, "error": str(exc)})
        return False
