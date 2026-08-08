"""Per-prospect report assembly — the internal brief and the client-facing draft.

Two report faces over the SAME facts, so they can never disagree:

  * the **internal brief** — a stripped-down competitive read for staff (maps rankings vs
    competitors, organic rankings vs competitors, LLM visibility), plus the call hook.
  * the **client-facing draft** — the same signals in plain, positive-but-honest language, marked
    as a DRAFT that needs explicit human approval before it becomes a prospect-facing asset
    (outreach/CLAUDE.md invariant; reporting-layer-spec §4a).

PURE and deterministic, the same discipline as `outreach_justification` and the heatmap renderer:
no LLM, no clock, no randomness, and never a fabricated fact, competitor, or number. A section for
a signal that has NOT been scanned renders as an explicit `status: "not_scanned"` block, never an
empty table dressed up as data — showing "no organic competitors" for a scan that never ran would
manufacture exactly the false picture the module guards against.

**Signal availability today (2026-08-08):** only the Maps geo-grid layer has a producer. The
organic-SERP and LLM-visibility layers are staged, paid, and (LLM) blocked on `ai_region` naming —
so their sections carry `status: "not_scanned"` until those layers land (outreach ISSUES I-095).
The section shapes are fixed now so a later slice fills a block, not restructures the report.
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

# Section status vocabulary. `measured` = a scan ran and produced data; `not_scanned` = the signal's
# scan layer hasn't run for this prospect (staged/paid/blocked); `not_measured` = the area itself has
# no rolled-up scan at all. A reader (and the UI) branches on these, never on an empty list.
STATUS_MEASURED = "measured"
STATUS_NOT_SCANNED = "not_scanned"
STATUS_NOT_MEASURED = "not_measured"

# The three competitive signals, in report order. Maps first because it is the one with data today.
SIGNAL_MAPS = "maps"
SIGNAL_ORGANIC = "organic"
SIGNAL_LLM = "llm"


def build_maps_comparison(
    *,
    prospect_place_id: Optional[str],
    pack_rows: list[dict[str, Any]],
    name_by_place_id: dict[str, str],
    coverage: Optional[dict[str, Any]],
    live_points: Optional[int],
    max_competitors: int,
) -> dict[str, Any]:
    """The "maps rankings for this keyword vs the top competitors" table. Pure.

    `pack_rows` are `grid_result` rows already filtered to the map pack (`rank <= pack_size`) for one
    snapshot — `{point_seq, place_id, rank}`. Each place (the prospect included) is scored by how
    many grid points it holds a pack spot at and its best rank across the grid — the honest
    apples-to-apples "who owns the map pack for this search" read. Competitors are named only when
    the `place_id` resolves (never invent one); the rest still feed `total_competitors`.
    """
    per_place_points: dict[str, set[int]] = {}
    per_place_best: dict[str, int] = {}
    for row in pack_rows:
        place_id = row.get("place_id")
        if not place_id:
            continue
        seq = int(row["point_seq"])
        rank = int(row["rank"])
        per_place_points.setdefault(place_id, set()).add(seq)
        per_place_best[place_id] = min(per_place_best.get(place_id, rank), rank)

    total = live_points if live_points else None

    def _row(place_id: str, name: Optional[str]) -> dict[str, Any]:
        pts = len(per_place_points.get(place_id, set()))
        return {
            "place_id": place_id,
            "name": name,
            "pack_points": pts,
            "pack_share_pct": round(100.0 * pts / total, 1) if total else None,
            "best_rank": per_place_best.get(place_id),
        }

    competitors = [
        _row(pid, name_by_place_id.get(pid))
        for pid in per_place_points
        if pid != prospect_place_id and name_by_place_id.get(pid)
    ]
    # Most map-pack presence first; place_id as a deterministic tie-break (replayability).
    competitors.sort(key=lambda c: (-c["pack_points"], c["place_id"]))

    prospect_row: dict[str, Any] = {
        "coverage_pct": round(float(coverage["coverage_pct"]), 1) if coverage else 0.0,
        "points_present": int(coverage["points_present"]) if coverage else 0,
        "live_points": total,
        "best_rank": coverage.get("best_rank") if coverage else None,
        "avg_rank": coverage.get("avg_rank") if coverage else None,
    }
    if prospect_place_id and prospect_place_id in per_place_points:
        prospect_row["pack_points"] = len(per_place_points[prospect_place_id])
        prospect_row["pack_best_rank"] = per_place_best.get(prospect_place_id)
    else:
        prospect_row["pack_points"] = 0
        prospect_row["pack_best_rank"] = None

    # distinct competitor place_ids holding any pack spot (named or not) — the honest denominator.
    total_competitors = sum(1 for pid in per_place_points if pid != prospect_place_id)

    return {
        "status": STATUS_MEASURED,
        "signal": SIGNAL_MAPS,
        "prospect": prospect_row,
        "competitors": competitors[:max_competitors],
        "total_competitors": total_competitors,
    }


def not_scanned_section(signal: str, reason: str) -> dict[str, Any]:
    """A signal whose scan layer has not run for this prospect. Explicit, never an empty table."""
    return {"status": STATUS_NOT_SCANNED, "signal": signal, "reason": reason}


def domain_of(url: Optional[str]) -> Optional[str]:
    """A bare, lower-cased host from a URL or host string, `www.` stripped. Pure.

    Mirrors `organic_scan.domain_of` in the outreach api (the two codebases can't share code), so
    the prospect's stored website and the SERP's `domain` field normalise identically — otherwise a
    prospect who DOES rank would silently read as "not found", the false direction. Never raises."""
    if not url:
        return None
    text = url.strip().lower()
    if not text:
        return None
    if "//" not in text:
        text = "//" + text
    host = urlparse(text).netloc or ""
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def build_organic_section(
    summary: Optional[dict[str, Any]],
    *,
    prospect_website: Optional[str],
    max_competitors: int,
) -> dict[str, Any]:
    """The "organic ranking for this keyword vs the top competitors" section. Pure.

    `summary` is a stored `serp_result.payload_summary` (from `organic_scan.summarize_serp`), or
    None when no organic scan has run for the snapshot — which returns a `not_scanned` block, never
    an empty table. The prospect's own organic rank is read by matching their website's domain
    against the SERP's `domain` field (both normalised the same way); competitors are the top
    ranked domains excluding the prospect's own. Nothing is invented — a prospect not in the
    captured depth reports `prospect_rank: None` (not ranking in the top N), not a guessed position.
    """
    if not summary:
        return not_scanned_section(
            SIGNAL_ORGANIC, "The organic-search scan hasn't run for this prospect yet."
        )

    results = summary.get("results") or []
    prospect_domain = domain_of(prospect_website)

    prospect_rank: Optional[int] = None
    if prospect_domain:
        for r in results:
            if domain_of(r.get("domain")) == prospect_domain and isinstance(r.get("rank"), int):
                prospect_rank = r["rank"] if prospect_rank is None else min(prospect_rank, r["rank"])

    competitors: list[dict[str, Any]] = []
    for r in sorted(results, key=lambda r: r.get("rank", 10**6)):
        if not r.get("domain"):
            continue
        if prospect_domain and domain_of(r.get("domain")) == prospect_domain:
            continue
        competitors.append({"domain": r.get("domain"), "rank": r.get("rank"), "title": r.get("title")})
        if len(competitors) >= max_competitors:
            break

    return {
        "status": STATUS_MEASURED,
        "signal": SIGNAL_ORGANIC,
        "prospect_domain": prospect_domain,
        "prospect_rank": prospect_rank,
        "ai_overview_present": bool(summary.get("ai_overview_present")),
        "captured_depth": summary.get("captured_depth"),
        "competitors": competitors,
    }


def build_report(
    *,
    prospect: dict[str, Any],
    keyword: str,
    submarket: str,
    justification: dict[str, Any],
    maps_section: dict[str, Any],
    organic_section: dict[str, Any],
    llm_section: dict[str, Any],
    heatmap_available: bool,
) -> dict[str, Any]:
    """Assemble the full report document — identity + the three competitive signals + the call hook.

    Pure. `justification` is the whole call-hook object (reused verbatim, so the report and the
    "Why call?" panel are one source of truth). The two faces (internal / client-facing) are the
    SAME document; the UI chooses copy per face. The client-facing face is always a DRAFT — the
    approval gate that turns it into a sendable asset is a later slice (outreach ISSUES I-095), and
    a report that could be handed to a prospect without a human saying yes would breach the module's
    no-unapproved-asset invariant.
    """
    measured = bool(justification.get("measured"))
    return {
        "prospect_id": prospect.get("id"),
        "measured": measured,
        "identity": {
            "name": prospect.get("name"),
            "category": prospect.get("category"),
            "phone": prospect.get("phone"),
            "website": prospect.get("website"),
            "address": prospect.get("address"),
            "rating": prospect.get("rating"),
            "review_count": prospect.get("review_count"),
        },
        "keyword": keyword,
        "submarket": submarket,
        "signals": {
            SIGNAL_MAPS: maps_section,
            SIGNAL_ORGANIC: organic_section,
            SIGNAL_LLM: llm_section,
        },
        "heatmap_available": heatmap_available,
        "justification": justification,
        # The client-facing face is a draft until approval exists — surfaced so the UI can gate it.
        "client_facing": {
            "status": "draft",
            "approved": False,
            "note": "Draft — a prospect-facing asset requires explicit approval before it is sent.",
        },
    }
