"""LeadOff — the monetization print (valuation plan v1, step 3).

Turns the market's ``leads/mo × exclusive CPL`` (which LeadOff already computes)
into the three grounded ways an operator would make money there, rendered on the
**grade card + market brief** (NOT new board columns — plan §7):

  * **PPL — exclusive**   leads/mo × exclusive CPL          (= ``value_mo``)
  * **Rank-and-rent**     PPL-exclusive × rent_discount     (one recurring buyer, ~zero ongoing sales effort)
  * **PPL — shared**      leads/mo × shared price × N buyers (shared price ≈ exclusive CPL × ratio)

**Honesty rule (plan §7):** same lead flow, two billing models — NOT independent
streams. You cannot bank both PPL and rent from one market; and since LeadOff's
model is exclusive, PPL-exclusive and rank-and-rent nearly converge — the daylight
is against SHARED PPL. The speculative Enigma "affordability ceiling" is v2, so it
is deliberately absent here.

All constants are config + calibratable. Pure; unit-tested in
``tests/test_leadoff_monetization.py``.
"""
from __future__ import annotations

from typing import Any, Optional


def monetization(*, value_mo: Optional[float], leads_mo: Optional[float],
                 cpl: Optional[float], rent_discount: float,
                 shared_price_ratio: float, n_buyers: int) -> dict[str, Any]:
    """The three monetization models for one market (pure). Any model whose
    inputs are missing is None (never a fabricated 0)."""
    ppl_exclusive = round(value_mo) if value_mo is not None else None
    rank_and_rent = (round(value_mo * rent_discount)
                     if value_mo is not None else None)
    shared_price = round(cpl * shared_price_ratio) if cpl is not None else None
    ppl_shared = (round((leads_mo or 0) * shared_price * n_buyers)
                  if (leads_mo is not None and shared_price is not None) else None)
    return {
        "ppl_exclusive_mo": ppl_exclusive,
        "rank_and_rent_mo": rank_and_rent,
        "ppl_shared_mo": ppl_shared,
        "shared_price": shared_price,
        "rent_discount": round(rent_discount, 3),
        "shared_price_ratio": round(shared_price_ratio, 3),
        "n_buyers": int(n_buyers),
    }


def params() -> dict[str, Any]:
    """Config-driven monetization constants (calibratable)."""
    from config import settings
    return {"rent_discount": float(settings.leadoff_monetization_rent_discount),
            "shared_price_ratio": float(settings.leadoff_monetization_shared_price_ratio),
            "n_buyers": int(settings.leadoff_monetization_shared_n_buyers)}


def attach(row: dict[str, Any], *, value_mo_key: str = "value_mo",
           leads_key: str = "est_leads_mo", cpl_key: str = "cpl") -> dict[str, Any]:
    """Add a ``monetization`` block to a grade/brief row in place, reading the
    row's own value/leads/CPL (best-effort — never raises; the market surface
    must not break over a monetization print). Returns the row."""
    try:
        row["monetization"] = monetization(
            value_mo=row.get(value_mo_key), leads_mo=row.get(leads_key),
            cpl=row.get(cpl_key), **params())
    except Exception:
        import logging
        logging.getLogger(__name__).warning("leadoff_monetization.attach_failed",
                                            exc_info=True)
    return row
