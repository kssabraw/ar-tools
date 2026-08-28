"""Autonomous SEO agent — the per-client budget governor (plan §4.1).

The spend ceiling that replaces the human confirm on money. The monthly budget
is sourced from the Recipe Engine's own arithmetic (what a retainer can fund),
and every autonomous charge is reserved atomically against it via the
``reserve_autonomy_spend`` RPC — so a half-updated or exhausted budget refuses
the reservation and the executor falls back to PROPOSING rather than spending
(the ``spend_denial`` pattern: the safe path is what you get by omission).

Pure sizing/arithmetic (``monthly_budget``, ``remaining``, ``month_key``) is
unit-tested; the reservation + reads touch Supabase and are the thin impure
layer the Phase 3 executor calls.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import recipe_engine

logger = logging.getLogger(__name__)


def month_key(today: Optional[date] = None) -> date:
    """First day of the calendar month — the spend meter's period key. Pure."""
    d = today or date.today()
    return d.replace(day=1)


def monthly_budget(
    retainer: Optional[float],
    *,
    margin: float = recipe_engine.DEFAULT_MARGIN,
    is_sab: bool = False,
    source: Optional[str] = None,
) -> float:
    """The month's autonomous budget, from the Recipe Engine envelope. Pure.

    ``source`` = "discretionary" (what a strategy can fund on TOP of the baseline
    stack — the honest ceiling; the default) or "deployable" (retainer × margin,
    gross). Never negative — a retainer that can't cover its baseline yields 0,
    which correctly means "nothing to spend autonomously", not a negative cap.
    """
    src = (source or settings.autonomy_budget_source or "discretionary").strip().lower()
    env = recipe_engine.budget_envelope(retainer, margin=margin, is_sab=is_sab)
    value = env.get("deployable" if src == "deployable" else "discretionary") or 0.0
    return round(max(0.0, float(value)), 2)


def remaining(budget: float, spent: float) -> float:
    """Budget left this period, floored at 0. Pure."""
    return round(max(0.0, float(budget) - float(spent)), 2)


# --- Impure layer (the executor's callers) ----------------------------------

def budget_for_client(client_row: dict) -> float:
    """This month's autonomous budget for a client, from its retainer/margin/SAB."""
    return monthly_budget(
        client_row.get("retainer_monthly"),
        is_sab=bool(client_row.get("is_sab")),
    )


def spent_this_month(client_id: str, today: Optional[date] = None) -> float:
    """What the client has already spent autonomously this month (0 if none)."""
    try:
        rows = (
            get_supabase()
            .table("autonomy_spend")
            .select("spent_usd")
            .eq("client_id", client_id)
            .eq("month", month_key(today).isoformat())
            .limit(1)
            .execute()
        ).data or []
        return float(rows[0]["spent_usd"]) if rows else 0.0
    except Exception as exc:  # noqa: BLE001 — best-effort read
        logger.warning("autonomy_spent_read_failed", extra={"client_id": client_id, "error": str(exc)})
        return 0.0


def reserve(client_id: str, amount: float, *, cap: float, today: Optional[date] = None) -> bool:
    """Atomically reserve ``amount`` against the client's monthly ``cap``.

    Returns True only if the charge fit under the cap (the RPC updated the row);
    False (refused) leaves spend unchanged, so the caller must NOT proceed with
    the paid action. A zero/negative amount is a no-op that succeeds.
    """
    if amount <= 0:
        return True
    try:
        res = get_supabase().rpc(
            "reserve_autonomy_spend",
            {
                "p_client": client_id,
                "p_month": month_key(today).isoformat(),
                "p_amount": float(amount),
                "p_cap": float(cap),
            },
        ).execute()
        return bool(res.data)
    except Exception as exc:  # noqa: BLE001 — a failed reservation must never spend
        logger.warning("autonomy_reserve_failed", extra={"client_id": client_id, "error": str(exc)})
        return False
