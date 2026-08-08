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

import html
import re
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


def _normalize_name(text: Optional[str]) -> str:
    """Lower-case, alnum-and-spaces-only — the loose comparison `ai_granularity.normalize` uses on
    the producer side, so both sides judge "same business" the same way."""
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def detect_ai_mention(
    *,
    prospect_name: Optional[str],
    prospect_domain: Optional[str],
    named_businesses: list[str],
    reference_domains: list[str],
    raw_excerpt: Optional[str],
) -> bool:
    """Is THIS prospect named in one engine's answer? Pure, deterministic, conservative.

    A match is: the prospect's (normalised) name appearing inside a named business or the raw
    excerpt, OR the prospect's domain appearing in the AIO reference domains. The name must be ≥4
    normalised chars to match on substring, so a two-letter shop name can't trivially hit — a false
    NEGATIVE (the AI named them under a variant we didn't match) is the safe direction here: it
    understates the prospect's visibility, never manufactures invisibility as a pitch.
    """
    if prospect_domain and prospect_domain in {d for d in reference_domains if d}:
        return True
    needle = _normalize_name(prospect_name)
    if len(needle) < 4:
        return False
    haystacks = [_normalize_name(b) for b in named_businesses]
    haystacks.append(_normalize_name(raw_excerpt))
    return any(needle in h for h in haystacks if h)


def build_llm_section(
    *,
    engine_rows: list[dict[str, Any]],
    prospect_name: Optional[str],
    prospect_domain: Optional[str],
    region: Optional[str],
    name_level: Optional[str],
    sample_size: int = 5,
) -> dict[str, Any]:
    """The "AI / LLM visibility" section — per engine, is the prospect named. Pure.

    `engine_rows` are stored `ai_scan_result` rows (latest per engine) for the prospect's region ×
    keyword, or empty when no AI scan has run → a `not_scanned` block. Each engine reports `present`
    (the engine gave a usable answer), `visible` (the prospect was named in it), and a small sample
    of who WAS named — the "here's who the AI recommends instead of you" evidence. A
    `neighbourhood`-level region carries the I-004 caveat that the model may have answered for the
    metro.
    """
    if not engine_rows:
        return not_scanned_section(SIGNAL_LLM, "The AI-visibility scan hasn't run for this region yet.")

    prospect_domain = prospect_domain or None
    engines: list[dict[str, Any]] = []
    for row in engine_rows:
        named = row.get("named_businesses") or []
        present = bool(row.get("present"))
        visible = present and detect_ai_mention(
            prospect_name=prospect_name,
            prospect_domain=prospect_domain,
            named_businesses=named,
            reference_domains=row.get("reference_domains") or [],
            raw_excerpt=row.get("raw_excerpt"),
        )
        engines.append({
            "engine": row.get("engine"),
            "present": present,
            "visible": visible,
            "named_count": len(named),
            "sample_businesses": [b for b in named[:sample_size]],
        })

    section: dict[str, Any] = {
        "status": STATUS_MEASURED,
        "signal": SIGNAL_LLM,
        "region": region,
        "name_level": name_level,
        "engines": engines,
    }
    if name_level == "neighbourhood":
        section["caveat"] = (
            "This is a neighbourhood-level check; an AI assistant may answer for the wider metro, "
            "so read a miss here as directional."
        )
    return section


LLM_ENGINE_LABELS = {"chatgpt": "ChatGPT", "google_aio": "Google AI Overview"}


def _esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""))


def _client_maps_html(section: dict[str, Any], keyword: str, submarket: str) -> str:
    if section.get("status") != STATUS_MEASURED or not section.get("prospect"):
        return "<p class='muted'>This section will be added when the map scan is available.</p>"
    p = section["prospect"]
    rows = [
        f"<tr class='you'><td>You</td><td>{_esc(p.get('pack_points'))}</td>"
        f"<td>{_esc(p.get('pack_best_rank') or '—')}</td></tr>"
    ]
    for c in section.get("competitors", []):
        rows.append(
            f"<tr><td>{_esc(c.get('name'))}</td><td>{_esc(c.get('pack_points'))}</td>"
            f"<td>{_esc(c.get('best_rank') or '—')}</td></tr>"
        )
    return (
        f"<p>For “{_esc(keyword)}” across {_esc(submarket)}, you appear in the Google map results at "
        f"{_esc(p.get('points_present'))} of {_esc(p.get('live_points'))} points "
        f"({_esc(p.get('coverage_pct'))}%). Here is how the businesses winning that search compare:</p>"
        "<table><thead><tr><th>Business</th><th>Map-pack points</th><th>Best rank</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _client_organic_html(section: dict[str, Any], keyword: str, submarket: str) -> str:
    if section.get("status") != STATUS_MEASURED:
        return "<p class='muted'>This section will be added when the search scan is available.</p>"
    rank = section.get("prospect_rank")
    depth = section.get("captured_depth")
    lead = (
        f"<p>You rank #{_esc(rank)} in Google’s standard search results for “{_esc(keyword)}”.</p>"
        if rank is not None
        else f"<p>You don’t appear in the top {_esc(depth)} Google search results for "
        f"“{_esc(keyword)}” in {_esc(submarket)}.</p>"
    )
    rows = "".join(
        f"<tr><td>{_esc(c.get('domain'))}</td><td>{_esc(c.get('rank') or '—')}</td></tr>"
        for c in section.get("competitors", [])
    )
    table = (
        "<table><thead><tr><th>Ranking ahead of you</th><th>Rank</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        if rows
        else ""
    )
    return lead + table


def _client_llm_html(section: dict[str, Any]) -> str:
    if section.get("status") != STATUS_MEASURED or not section.get("engines"):
        return "<p class='muted'>This section will be added when the AI-visibility scan is available.</p>"
    rows = []
    for e in section["engines"]:
        label = LLM_ENGINE_LABELS.get(e.get("engine"), _esc(e.get("engine")))
        if not e.get("present"):
            verdict = "<span class='muted'>No AI answer returned for this search.</span>"
        elif e.get("visible"):
            verdict = "<span class='good'>✓ You’re named in the AI answer.</span>"
        else:
            names = ", ".join(_esc(b) for b in (e.get("sample_businesses") or [])[:4])
            extra = f" It names: {names}." if names else ""
            verdict = f"<span class='bad'>✗ You’re not named.</span>{extra}"
        rows.append(f"<tr><td>{_esc(label)}</td><td>{verdict}</td></tr>")
    caveat = f"<p class='muted small'>{_esc(section['caveat'])}</p>" if section.get("caveat") else ""
    return (
        "<table><thead><tr><th>AI assistant</th><th>Are you named?</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>{caveat}"
    )


def render_client_report_html(report: dict[str, Any], *, agency_name: str) -> str:
    """The client-facing report as a standalone HTML document, for WeasyPrint → PDF.

    Pure and deterministic — the SAME assembled facts the on-screen client-facing face renders, in a
    print layout. Client tone, honest `not_scanned` blocks (never an empty table), and every value
    escaped. It is generated ONLY after explicit approval (the router gate), so — unlike the
    on-screen preview — it carries no DRAFT watermark; the footer names the agency that prepared it.
    """
    identity = report.get("identity", {})
    keyword = report.get("keyword", "")
    submarket = report.get("submarket", "")
    signals = report.get("signals", {})
    name = identity.get("name") or "Your business"

    css = (
        "body{font-family:Helvetica,Arial,sans-serif;color:#1f2937;margin:40px;font-size:12px}"
        "h1{font-size:20px;margin:0 0 2px}h2{font-size:13px;margin:22px 0 6px;color:#0f172a;"
        "text-transform:uppercase;letter-spacing:.4px}.sub{color:#64748b;margin:0 0 4px}"
        "table{width:100%;border-collapse:collapse;margin-top:4px}"
        "th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #eef2f7}"
        "th{color:#64748b;font-size:10px;text-transform:uppercase}"
        "tr.you{background:#eff6ff;font-weight:bold}.muted{color:#94a3b8}.small{font-size:10px}"
        ".good{color:#166534;font-weight:bold}.bad{color:#b91c1c;font-weight:bold}"
        ".footer{margin-top:28px;color:#94a3b8;font-size:10px;border-top:1px solid #eef2f7;padding-top:8px}"
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head><body>"
        f"<h1>Your Google visibility for “{_esc(keyword)}” in {_esc(submarket)}</h1>"
        f"<p class='sub'>Prepared for {_esc(name)}</p>"
        "<h2>Google Maps — where customers do (and don’t) find you</h2>"
        f"{_client_maps_html(signals.get('maps', {}), keyword, submarket)}"
        "<h2>Google search results</h2>"
        f"{_client_organic_html(signals.get('organic', {}), keyword, submarket)}"
        "<h2>AI assistants (ChatGPT, Google AI Overview)</h2>"
        f"{_client_llm_html(signals.get('llm', {}))}"
        f"<div class='footer'>Based on a live scan of {_esc(submarket)}. Figures are a point-in-time "
        f"snapshot. Prepared by {_esc(agency_name)}.</div>"
        "</body></html>"
    )


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
    approval: Optional[dict[str, Any]] = None,
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
        # The client-facing face is a draft until an approval is on record. `approval` is the latest
        # report_approval row (or None), so the UI flips from "draft" to "approved" after the first
        # explicit human approval and can show who/when.
        "client_facing": (
            {
                "status": "approved",
                "approved": True,
                "approved_by": approval.get("approved_by"),
                "approved_at": approval.get("created_at"),
                "note": "Approved — this report may be shared with the prospect.",
            }
            if approval
            else {
                "status": "draft",
                "approved": False,
                "note": "Draft — a prospect-facing asset requires explicit approval before it is sent.",
            }
        ),
    }
