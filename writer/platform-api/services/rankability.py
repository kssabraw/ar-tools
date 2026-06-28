"""Rankability — how realistically a client can win a tracked keyword.

Organic Rank Tracker (Module #4). A transparent, client-relative score (0–100) +
band (Easy / Moderate / Hard / Very hard) computed from the keyword's latest
Competitive SERP Snapshot plus the client's own authority and the keyword's
market value. Higher = more winnable for THIS client (the inverse of the familiar
"keyword difficulty"). Every score carries its 2–3 driving factors so the team
can trust it rather than treat it as a black box.

Four sub-scores (each 0–100, higher = better for us), blended:
  - competition weakness — how weak the top-10 backlink authority is
    (weighted RD > UR > DR, the user's backlink-importance order)
  - targeting gap — how many of the top results are NOT written for the keyword
    (loose-match incumbents a purpose-built page can take)
  - client capability — the client's authority vs the incumbents' + rank momentum
  - SERP opportunity — click real-estate left after AIO / shopping / ads crowding

Pure scorer (no I/O) is unit-tested; get_client_rankability does the reads and
pairs each score with the keyword's potential value into a "Quick wins" priority.
Heuristic + tunable — all weights/thresholds are module constants.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from db.supabase_client import get_supabase
from services import keyword_market

# Sub-score blend (sums to 1.0). Competition weakness dominates; capability next.
_W_WEAKNESS = 0.40
_W_CAPABILITY = 0.25
_W_TARGETING = 0.20
_W_OPPORTUNITY = 0.15

# Backlink-metric weights inside an authority figure: RD > UR > DR (user's order).
_A_RD, _A_UR, _A_DR = 0.5, 0.3, 0.2

# Band thresholds on the 0–100 score.
_BANDS = [(70, "Easy"), (50, "Moderate"), (30, "Hard"), (0, "Very hard")]

# Click-real-estate penalties (subtracted from the opportunity sub-score).
_AIO_PENALTY = 25
_SHOPPING_PENALTY = 15

# Potential-value target position (value "if we win it" → top-3 placement).
_VALUE_TARGET_POSITION = 3.0


# ----------------------------------------------------------------------------
# Pure scoring (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _median(nums: list[Optional[float]]) -> Optional[float]:
    vals = sorted(n for n in nums if n is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def _norm_rd(rd: Optional[float]) -> float:
    """Referring-domains count → 0–100 (≈200 RD saturates to 100)."""
    return 0.0 if rd is None else _clamp(rd * 0.5)


def _norm_rank(v: Optional[float]) -> float:
    """DataForSEO 0–1000 rank (UR/DR) → 0–100."""
    return 0.0 if v is None else _clamp(v / 10.0)


def _authority(rd: Optional[float], ur: Optional[float], dr: Optional[float]) -> float:
    """Blended 0–100 backlink authority, weighted RD > UR > DR."""
    return _A_RD * _norm_rd(rd) + _A_UR * _norm_rank(ur) + _A_DR * _norm_rank(dr)


def score_keyword(inp: dict) -> dict:
    """Compute {score, band, factors} from one keyword's snapshot-derived inputs.

    Expected keys: top_ur / top_rd (competitor page-level lists), competitor_dr
    (competitor domain-level list), targeted_count, top_count, client_ur /
    client_rd / client_dr, aio_present, signals (list), client_rank.
    """
    top_count = inp.get("top_count") or 0
    incumbent = _authority(
        _median(inp.get("top_rd") or []),
        _median(inp.get("top_ur") or []),
        _median(inp.get("competitor_dr") or []),
    )
    client = _authority(inp.get("client_rd"), inp.get("client_ur"), inp.get("client_dr"))

    # 1) Competition weakness.
    weakness = 100.0 - incumbent

    # 2) Targeting gap — share of the top results NOT written for the keyword.
    targeted = inp.get("targeted_count") or 0
    targeting = (top_count - targeted) / top_count * 100.0 if top_count else 50.0

    # 3) Client capability — authority vs incumbents (parity = 50) + rank momentum.
    capability = 50.0 + (client - incumbent)
    rank = inp.get("client_rank")
    momentum = _clamp((21 - rank), 0, 20) * 0.5 if rank else 0.0  # already close → bonus
    capability = _clamp(capability + momentum)

    # 4) SERP opportunity — click real-estate left.
    signals = set(inp.get("signals") or [])
    penalty = (_AIO_PENALTY if inp.get("aio_present") else 0) + (
        _SHOPPING_PENALTY if "shopping" in signals else 0
    )
    opportunity = _clamp(100.0 - penalty)

    score = (
        _W_WEAKNESS * weakness
        + _W_CAPABILITY * capability
        + _W_TARGETING * targeting
        + _W_OPPORTUNITY * opportunity
    )
    score = int(round(_clamp(score)))

    band = next(label for threshold, label in _BANDS if score >= threshold)
    return {
        "score": score,
        "band": band,
        "factors": _factors(weakness, targeting, capability, opportunity, inp, top_count, targeted),
    }


def _factors(weakness, targeting, capability, opportunity, inp, top_count, targeted) -> list[dict]:
    """The 2–3 sub-scores furthest from neutral (50), weighted by their blend
    weight, rendered as human-readable drivers with a direction."""
    loose = top_count - targeted
    cands: list[tuple[float, str, str]] = []  # (impact, text, direction)

    impact = (weakness - 50) * _W_WEAKNESS
    cands.append((impact, "Top-10 backlink authority is low" if impact >= 0
                  else "Top-10 are high-authority pages", "up" if impact >= 0 else "down"))

    if top_count:
        impact = (targeting - 50) * _W_TARGETING
        cands.append((impact, f"{loose} of {top_count} incumbents are loose matches" if impact >= 0
                      else "Incumbents are tightly targeted", "up" if impact >= 0 else "down"))

    impact = (capability - 50) * _W_CAPABILITY
    rank = inp.get("client_rank")
    if rank and rank <= 20:
        cands.append((abs(impact) + 1, f"You already rank #{rank}", "up"))
    cands.append((impact, "Your authority is competitive here" if impact >= 0
                  else "Large authority gap to close", "up" if impact >= 0 else "down"))

    impact = (opportunity - 50) * _W_OPPORTUNITY
    if inp.get("aio_present"):
        cands.append((abs(impact) + 1, "AI Overview steals clicks", "down"))
    if "shopping" in set(inp.get("signals") or []):
        cands.append((abs(impact) + 0.5, "Shopping/ads crowd the SERP", "down"))

    cands.sort(key=lambda c: abs(c[0]), reverse=True)
    out, seen = [], set()
    for _, text, direction in cands:
        if text in seen:
            continue
        seen.add(text)
        out.append({"text": text, "direction": direction})
        if len(out) >= 3:
            break
    return out


# ----------------------------------------------------------------------------
# DB assembly.
# ----------------------------------------------------------------------------
def _latest_snapshot_per_keyword(supabase, client_id: str) -> dict[str, dict]:
    rows = (
        supabase.table("serp_snapshots")
        .select("id, keyword_id, captured_at, targeted_count, aio_present, intent_signals, client_rank")
        .eq("client_id", client_id)
        .in_("status", ["complete", "partial"])
        .order("captured_at", desc=True)
        .execute()
    ).data or []
    latest: dict[str, dict] = {}
    for r in rows:  # rows are newest-first → first seen per keyword wins
        latest.setdefault(r["keyword_id"], r)
    return latest


def get_client_rankability(client_id: str, today: Optional[date] = None) -> dict:
    """Per-keyword rankability for a client + a Quick-wins priority (score ×
    potential value). Keywords with no snapshot yet are returned unscored."""
    supabase = get_supabase()
    today = today or date.today()

    kws = (
        supabase.table("tracked_keywords")
        .select("id, keyword")
        .eq("client_id", client_id)
        .eq("active", True)
        .order("keyword")
        .execute()
    ).data or []
    if not kws:
        return {"items": []}

    latest = _latest_snapshot_per_keyword(supabase, client_id)
    snap_ids = [s["id"] for s in latest.values()]
    results_by: dict[str, list[dict]] = {}
    domains_by: dict[str, list[dict]] = {}
    if snap_ids:
        for r in (
            supabase.table("serp_snapshot_results")
            .select("snapshot_id, position, is_client, targeted, url_rating, referring_domains")
            .in_("snapshot_id", snap_ids)
            .execute()
        ).data or []:
            results_by.setdefault(r["snapshot_id"], []).append(r)
        for d in (
            supabase.table("serp_snapshot_domains")
            .select("snapshot_id, is_client, domain_rating")
            .in_("snapshot_id", snap_ids)
            .execute()
        ).data or []:
            domains_by.setdefault(d["snapshot_id"], []).append(d)

    # Market data (volume/CPC) for the potential-value figure — reuse the cache.
    location_code = _client_location_code(supabase, client_id)
    market = keyword_market.fetch_cached_market(
        supabase, [k["keyword"] for k in kws], location_code
    )

    items: list[dict] = []
    for k in kws:
        snap = latest.get(k["id"])
        m = market.get(k["keyword"].lower(), {})
        volume, cpc = m.get("search_volume"), m.get("cpc")
        potential = keyword_market.estimate_monthly_value(volume, _VALUE_TARGET_POSITION, cpc)
        base = {
            "keyword_id": k["id"],
            "keyword": k["keyword"],
            "search_volume": volume,
            "cpc": cpc,
            "est_value": potential,
        }
        if not snap:
            items.append({**base, "has_snapshot": False, "score": None, "band": None,
                          "factors": [], "priority": None, "snapshot_id": None, "client_rank": None})
            continue

        results = results_by.get(snap["id"], [])
        domains = domains_by.get(snap["id"], [])
        top = [r for r in results if r.get("position") is not None and r["position"] <= 10]
        competitors = [r for r in top if not r.get("is_client")]
        client_rows = [r for r in results if r.get("is_client")]
        client_best = max(client_rows, key=lambda r: (r.get("url_rating") or -1), default=None)
        client_dr_row = next((d for d in domains if d.get("is_client")), None)

        scored = score_keyword(
            {
                "top_ur": [r.get("url_rating") for r in competitors],
                "top_rd": [r.get("referring_domains") for r in competitors],
                "competitor_dr": [d.get("domain_rating") for d in domains if not d.get("is_client")],
                "targeted_count": snap.get("targeted_count") or 0,
                "top_count": len(top),
                "client_ur": (client_best or {}).get("url_rating"),
                "client_rd": (client_best or {}).get("referring_domains"),
                "client_dr": (client_dr_row or {}).get("domain_rating"),
                "aio_present": bool(snap.get("aio_present")),
                "signals": snap.get("intent_signals") or [],
                "client_rank": snap.get("client_rank"),
            }
        )
        priority = round(scored["score"] / 100.0 * (potential or 0.0), 2)
        items.append({**base, "has_snapshot": True, "snapshot_id": snap["id"],
                      "client_rank": snap.get("client_rank"), "priority": priority, **scored})

    return {"items": items}


def _client_location_code(supabase, client_id: str) -> int:
    """Mirror routers.rank._client_location_code without importing the router."""
    from services.dataforseo_rank import location_code_for

    res = (
        supabase.table("clients")
        .select("id, website_url, gbp, rank_tracking_location_code")
        .eq("id", client_id)
        .limit(1)
        .execute()
    )
    return location_code_for(res.data[0]) if res.data else location_code_for({})
