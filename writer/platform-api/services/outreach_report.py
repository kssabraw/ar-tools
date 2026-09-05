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

# The competitive signals, in report order. Maps first because it is the one with data today.
SIGNAL_MAPS = "maps"
SIGNAL_ORGANIC = "organic"
SIGNAL_LLM = "llm"
# Paid placement — the fourth signal (outreach HANDOFF §12 item 3a). Is the business (or its
# competitors) buying Google Ads / Local Services Ads for this keyword. The single highest-value
# lead signal in scoring-spec.md (LSA active +57, Google Ads + no organic/pack +46) — a business
# paying to solve the visibility problem while still losing organically has proven budget AND intent.
SIGNAL_PAID = "paid"


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


def _tech_ok(tech: Optional[dict[str, Any]]) -> bool:
    """A tech row is usable only when the fetch SUCCEEDED — a failed fetch is unknown, never absent
    (PRD §B3), so its all-False booleans must not read as "no ad tech"."""
    return bool(tech) and tech.get("fetch_status") == "ok"


def derive_paid_signal(
    paid: Optional[dict[str, Any]],
    *,
    prospect_website: Optional[str],
    prospect_name: Optional[str],
    max_named: int,
    tech: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """The paid-placement facts for ONE prospect, from the snapshot's stored `payload_summary.paid`.
    Pure and deterministic — never asserts an ad, advertiser or spend that is not in the captured
    response (the module's governing invariant).

    `paid` is the block `organic_scan.summarize_paid` wrote (advertisers by domain, LSA advertisers
    by name). This does the SAME kind of read-time match the organic section does for `prospect_rank`
    and the LLM section does for a mention: is the prospect's OWN domain among the ad advertisers, and
    is its name among the LSA advertisers. Competitors are the advertisers that are NOT the prospect.

    `competitors_advertising_gap` is the pitch (scoring-spec.md §Buying intent): a rival is paying for
    the top of this search and the prospect is not. Absence never manufactures a claim — no ads in the
    capture means `ads_present: False`, which is a finding, not a gap.
    """
    block = paid or {}
    advertisers = block.get("advertisers") or []
    lsa_advertisers = block.get("lsa_advertisers") or []
    ads_present = bool(block.get("ads_present")) or bool(advertisers)
    lsa_present = bool(block.get("lsa_present")) or bool(lsa_advertisers)

    prospect_domain = domain_of(prospect_website)
    prospect_norm = _normalize_name(prospect_name)

    def _is_prospect_ad(ad: dict[str, Any]) -> bool:
        return bool(prospect_domain) and domain_of(ad.get("domain")) == prospect_domain

    def _is_prospect_lsa(ad: dict[str, Any]) -> bool:
        """Is this LSA advertiser the prospect? ONE-DIRECTIONAL — the prospect's name inside the
        advertiser's, never the reverse. Exactly the rule `detect_ai_mention` uses, and for the same
        reason: the two directions fail in OPPOSITE directions and only one is safe.

        The reverse (`name in prospect_norm`) let a SHORTER advertiser name match a longer prospect
        name — "AAA Plumbing" (a real, distinct competitor) inside prospect "AAA Plumbing Services",
        which is routine in the trades. That produced two fabrications at once: it asserted the
        prospect was running an LSA they do not run, and it DELETED a real competitor from the list
        (this function also gates the competitor loop below). Both breach "never assert an ad, an
        advertiser, or spend that is not in the captured response".

        This direction's failure mode is a miss (the LSA lists a longer legal name than the GBP
        name), which UNDERSTATES the prospect's spend and at worst lists them beside their own
        competitors — visible and harmless, never a claim made to their face.
        """
        name = _normalize_name(ad.get("name"))
        return len(prospect_norm) >= 4 and bool(name) and prospect_norm in name

    prospect_running_ads = any(_is_prospect_ad(a) for a in advertisers)
    prospect_running_lsa = any(_is_prospect_lsa(a) for a in lsa_advertisers)

    # Competitor advertisers, prospect excluded, deduped by domain (an advertiser can appear twice).
    seen: set[str] = set()
    competitor_ads: list[dict[str, Any]] = []
    for a in advertisers:
        dom = domain_of(a.get("domain"))
        if not dom or _is_prospect_ad(a) or dom in seen:
            continue
        seen.add(dom)
        competitor_ads.append({"domain": dom, "rank": a.get("rank"), "title": a.get("title")})
    competitor_ads.sort(key=lambda a: (a["rank"] if isinstance(a.get("rank"), int) else 10**6, a["domain"]))

    seen_names: set[str] = set()
    competitor_lsa: list[dict[str, Any]] = []
    for a in lsa_advertisers:
        norm = _normalize_name(a.get("name"))
        if not norm or _is_prospect_lsa(a) or norm in seen_names:
            continue
        seen_names.add(norm)
        competitor_lsa.append({"name": a.get("name"), "rank": a.get("rank")})
    competitor_lsa.sort(key=lambda a: (a["rank"] if isinstance(a.get("rank"), int) else 10**6, str(a["name"])))

    competitors_advertising = bool(competitor_ads) or bool(competitor_lsa)

    # --- site tech signals (Slice B1), folded in additively -----------------------------------
    # The SERP-derived facts above keep their Slice-A meaning (the competitor gap stays keyed on the
    # SERP paid block alone, unchanged). The tech row adds "does the prospect run ad tech on their
    # OWN site" — an AW- conversion tag / Meta pixel / vendor stack — a separate, complementary
    # signal. `prospect_is_paying` is the BROAD read used for the "paying and losing" pitch:
    # in the paid SERP block, OR running LSA, OR carrying an AW conversion tag. A failed/absent tech
    # fetch contributes nothing (unknown ≡ absent — never subtracts).
    t = tech if _tech_ok(tech) else None
    tech_ads = bool(t and t.get("google_ads_conversion"))
    tech_pixel = bool(t and t.get("meta_pixel"))
    vendor_tags = list(t.get("vendor_tags") or []) if t else []
    # 2+ VENDOR tags only. GTM was counted here and must not be: it is a free Google tool on a large
    # share of all sites, so "GTM + one vendor tag" flagged DIY operators as agency-managed — and
    # `likely_represented` is the one derived flag that scores NEGATIVE (−21 Model A / −26 Model B),
    # so a loose match here penalises a good prospect. GTM stays recorded on the row as context.
    likely_represented = len(vendor_tags) >= 2

    # TWO reads, deliberately kept apart, because they support different claims:
    #   * `prospect_paying_this_keyword` — MEASURED on this keyword's SERP (their ad or their LSA is
    #     in the captured block). Only this one licenses a keyword-specific spend claim.
    #   * `prospect_is_paying` — the BROAD read, which also counts an `AW-` conversion tag found on
    #     their site. A tag proves Google Ads conversion tracking is installed; it does NOT prove
    #     they bid on this keyword, and tags routinely outlive the campaigns that placed them.
    # `paying_evidence` names which one fired, so every downstream sentence can be built from what
    # was actually observed instead of collapsing the two.
    prospect_paying_this_keyword = prospect_running_ads or prospect_running_lsa
    prospect_is_paying = prospect_paying_this_keyword or tech_ads
    paying_evidence = (
        "serp_ad" if prospect_running_ads
        else "lsa" if prospect_running_lsa
        else "conversion_tag" if tech_ads
        else None
    )

    return {
        "ads_present": ads_present,
        "lsa_present": lsa_present,
        "prospect_running_ads": prospect_running_ads,
        "prospect_running_lsa": prospect_running_lsa,
        "prospect_running_any": prospect_running_ads or prospect_running_lsa,
        "competitor_advertisers": competitor_ads[:max_named],
        "competitor_lsa": competitor_lsa[:max_named],
        "advertiser_count": len(competitor_ads),
        "lsa_count": len(competitor_lsa),
        # THE pitch, and it is SERP-SCOPED on both sides: rivals hold paid placement on THIS
        # keyword's SERP and the prospect does not. It deliberately ignores `tech_ads` — a
        # conversion tag says nothing about this keyword — so a prospect can legitimately be both
        # `prospect_is_paying` (tag on site) and inside this gap (absent from this SERP's paid
        # block). Those are not contradictory; they are two different measurements.
        "competitors_advertising_gap": competitors_advertising and not prospect_paying_this_keyword,
        # Site tech (Slice B1). `tech_measured` distinguishes "site read, nothing found" from "site
        # not read / not scanned" so the report never shows absence as a finding on a failed fetch.
        "tech_measured": t is not None,
        "prospect_meta_pixel": tech_pixel,
        "prospect_ad_conversion_tag": tech_ads,
        "prospect_vendor_tags": vendor_tags,
        "prospect_likely_represented": likely_represented,
        "prospect_is_paying": prospect_is_paying,
        "prospect_paying_this_keyword": prospect_paying_this_keyword,
        "paying_evidence": paying_evidence,
    }


def build_paid_section(
    summary: Optional[dict[str, Any]],
    *,
    prospect_website: Optional[str],
    prospect_name: Optional[str],
    max_competitors: int,
    tech: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """The "paid placement" report section. Pure.

    `summary` is the stored `serp_result.payload_summary` (from `organic_scan.summarize_serp`) —
    Slice A's SERP paid block. `tech` is the latest `prospect_tech_signal` row — Slice B1's site ad
    tech (or None when `scan-tech` hasn't run for the prospect). Paid placement rides the organic
    capture, so the SECTION's presence is gated on the SERP capture:
      * `summary is None` → the organic/paid scan hasn't run → `not_scanned`.
      * `summary` present but with no `paid` block → captured before paid parsing existed → also
        `not_scanned` (honest: we didn't measure ads, which must not read as "no ads").
      * otherwise → `measured`, with the derived per-prospect facts (SERP + site tech).
    """
    if not summary:
        return not_scanned_section(
            SIGNAL_PAID, "The paid-placement scan hasn't run for this prospect yet."
        )
    if "paid" not in summary:
        return not_scanned_section(
            SIGNAL_PAID, "This scan predates paid-placement detection — re-run the search scan."
        )
    signal = derive_paid_signal(
        summary.get("paid"),
        prospect_website=prospect_website,
        prospect_name=prospect_name,
        max_named=max_competitors,
        tech=tech,
    )
    return {"status": STATUS_MEASURED, "signal": SIGNAL_PAID, **signal}


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


def _client_paid_html(section: dict[str, Any], keyword: str) -> str:
    if section.get("status") != STATUS_MEASURED:
        return "<p class='muted'>This section will be added when the search scan is available.</p>"
    ads = section.get("competitor_advertisers") or []
    lsa = section.get("competitor_lsa") or []
    if not section.get("ads_present") and not section.get("lsa_present"):
        return (
            f"<p>No businesses are currently paying for Google Ads on “{_esc(keyword)}” in your area "
            "— the top of this search is still won on merit, not budget.</p>"
        )
    # Keyword-level spend is claimed ONLY when it was measured on this keyword's SERP. A conversion
    # tag found on their site proves tracking is installed, not that they bid on this term — and a
    # claim the reader can falsify ("we paused those ads months ago") costs the lead.
    if section.get("prospect_paying_this_keyword"):
        lead = (
            f"<p>You’re paying to advertise for “{_esc(keyword)}”. Here’s who else is bidding for the "
            "same customers:</p>"
        )
    elif section.get("paying_evidence") == "conversion_tag":
        lead = (
            "<p>Your site is running Google Ads conversion tracking, so you’re investing in paid "
            f"traffic — but you’re not showing in the paid results for “{_esc(keyword)}”, and these "
            "businesses are:</p>"
        )
    elif section.get("competitors_advertising_gap"):
        lead = (
            f"<p>Competitors are paying Google to appear at the top for “{_esc(keyword)}”, and you’re "
            "not — they’re buying the customers you’re invisible to.</p>"
        )
    else:
        lead = f"<p>Paid advertising is active on “{_esc(keyword)}” in your area.</p>"
    rows = "".join(
        f"<tr><td>{_esc(a.get('domain'))}</td><td>Google Ads</td></tr>" for a in ads
    ) + "".join(
        f"<tr><td>{_esc(a.get('name'))}</td><td>Local Services Ad</td></tr>" for a in lsa
    )
    table = (
        "<table><thead><tr><th>Advertiser</th><th>Type</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        if rows
        else ""
    )
    return lead + table


def _client_valuation_html(valuation: Optional[dict[str, Any]]) -> str:
    """The client-facing missed-opportunity box (Phase B). Leads with — and shows ONLY — the
    ad-cost-equivalent anchor: the defensible number (measured CPC × the local demand they're missing
    from the pack), carrying no soft close-rate / job-value assumption. The missed-revenue band stays
    INTERNAL (the Phase-A brief). Renders nothing unless the valuation is available AND the anchor is
    present (no CPC → no client-facing figure — a band alone is too soft to put in front of a
    prospect). Vocabulary: 'estimated missed opportunity', never 'loss'; the estimate shows its work.
    """
    if not valuation or not valuation.get("available"):
        return ""
    ad_cost = valuation.get("ad_cost_equivalent_monthly")
    if not isinstance(ad_cost, (int, float)) or ad_cost <= 0:
        return ""
    how = valuation.get("how_estimated") or ""
    return (
        "<h2>Estimated missed opportunity</h2>"
        f"<p>To buy the local search traffic you're currently missing from the Google map pack, "
        f"you'd need to spend roughly <strong>${int(ad_cost):,}/month</strong> on Google Ads. "
        f"That's the demand going to competitors instead of you, right now.</p>"
        f"<p class='small muted'>Estimate, not a guarantee. {_esc(how)}</p>"
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
        "<h2>Paid advertising</h2>"
        f"{_client_paid_html(signals.get('paid', {}), keyword)}"
        f"{_client_valuation_html(report.get('valuation'))}"
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
    paid_section: dict[str, Any],
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
        # The prospect's market, so the report UI's "Run AI scan" seed modal knows which market to
        # list/seed ai_regions against (the AI signal is scanned per human-seeded region, not submarket).
        "market_id": prospect.get("market_id"),
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
            SIGNAL_PAID: paid_section,
        },
        "heatmap_available": heatmap_available,
        "justification": justification,
        # The missed-opportunity dollar valuation (docs/missed-opportunity-valuation-prd-v0_1.md),
        # surfaced top-level for the internal brief. Carried on the justification (computed once at
        # read time, deterministic, never LLM-phrased), so it is None when the feature is off or an
        # input is missing. Phase A is internal-only — this is NOT rendered into the client PDF.
        "valuation": justification.get("valuation"),
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
