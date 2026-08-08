"""Site tech/tag detection — Slice B1 of the paid-placement money signal (PRD §B3).

Fetch a prospect's own site and detect the ad/marketing tech on it: Meta pixel, Google Ads (`AW-`)
conversion tags, the GTM container, and vendor tags (CallRail / Podium / Birdeye). These are the
scoring-spec.md §Buying-intent and §Decision-structure signals a SERP read cannot see — they live in
the prospect's page, not in the search results.

**Pure detection lives here; the fetch + DB write live in `scan_tech.py`.** This module never touches
the network — it takes already-fetched bytes and returns what matched, exactly the way the heatmap
turns a rank_vector into an SVG. Every match is kept in `evidence` so the finding is replayable from
stored inputs (the `score_factors` discipline).

**Deterministic and fact-grounded.** A signal is present ONLY when its signature is matched; nothing
is inferred. All signals are ONE-DIRECTIONAL (PRD §B3): presence adds, absence never subtracts, and a
FAILED FETCH is `unknown`, never `absent` — that distinction is enforced by the producer (a null
fetch records a status, not an empty TechSignals), not here.

**GTM caveat (ISSUES I-003 / §16a.1).** A GTM container injects tags client-side, so an inline scan
of the page HTML misses GTM-injected pixels — a false negative. `looks_gtm_only` flags a page that
carries a GTM container but no inline pixel, i.e. the case where the container fetch matters. Whether
that follow is REQUIRED is the §16a.1 spike's call; this module supports both (scan the page, then
scan the container bytes with the SAME detector and merge).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --- signatures (measure-don't-infer: these are the documented, stable markers; the producer logs a
# sample so an unexpected page shape is diagnosable) -------------------------------------------

# Meta / Facebook pixel: the loader script and the init call carrying the numeric pixel id.
_META_PIXEL_MARKERS = (
    re.compile(r"connect\.facebook\.net/[^\"'\s]*/fbevents\.js", re.I),
    re.compile(r"\bfbq\s*\(\s*['\"]init['\"]", re.I),
)
_META_PIXEL_ID = re.compile(r"fbq\s*\(\s*['\"]init['\"]\s*,\s*['\"](\d{5,})['\"]", re.I)

# Google Ads conversion: the AW- account id (in a gtag config or a conversion linker) and the
# conversion endpoint. A bare "AW-1234" is enough; the endpoint corroborates.
_AW_ID = re.compile(r"\bAW-(\d{6,})\b")
_AW_MARKERS = (
    re.compile(r"googleadservices\.com/pagead/conversion", re.I),
    re.compile(r"gtag\s*\(\s*['\"]config['\"]\s*,\s*['\"]AW-\d+", re.I),
)

# Google Tag Manager container id.
_GTM_ID = re.compile(r"\bGTM-([A-Z0-9]{4,})\b")

# Vendor tags — the agency/marketing-stack signals that feed `likely_represented` and the vendor-tag
# buying-intent bin. Keyed by the canonical vendor name the scorer expects.
_VENDOR_MARKERS: dict[str, tuple[re.Pattern[str], ...]] = {
    "callrail": (re.compile(r"cdn\.callrail\.com", re.I), re.compile(r"\bcallrail\b", re.I)),
    "podium": (re.compile(r"\bpodium\.com\b", re.I), re.compile(r"connect\.podium\.com", re.I)),
    "birdeye": (re.compile(r"\bbirdeye\.com\b", re.I), re.compile(r"birdeye\.com/widget", re.I)),
}

# Google Guaranteed badge on the site. Weak by design — the authoritative LSA signal comes from the
# organic SERP (Slice A). Matched only as corroboration and never the sole basis for a claim.
_GOOGLE_GUARANTEED = (
    re.compile(r"google\s*guaranteed", re.I),
    re.compile(r"localservices\.google", re.I),
)

# The GTM container URL — the §16a.1 follow. Built here so the producer and its tests share one
# definition of "where the container lives".
GTM_CONTAINER_URL = "https://www.googletagmanager.com/gtm.js?id={container_id}"


@dataclass(frozen=True)
class TechSignals:
    """What one page (optionally + its GTM container) carried. A SUCCESSFUL read — a failed fetch is
    represented by the producer as a status, never as an all-False TechSignals (unknown ≠ absent)."""
    meta_pixel: bool = False
    meta_pixel_ids: tuple[str, ...] = ()
    google_ads_conversion: bool = False
    aw_ids: tuple[str, ...] = ()
    gtm_container_ids: tuple[str, ...] = ()
    vendor_tags: tuple[str, ...] = ()
    google_guaranteed: bool = False
    gtm_followed: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def vendor_count(self) -> int:
        return len(self.vendor_tags)

    @property
    def likely_represented(self) -> bool:
        """2+ agency/vendor signals — the scoring-spec.md §Decision-structure bin. A vendor tag and a
        GTM container both count as marketing-stack signals; two distinct ones read as "handled"."""
        signals = self.vendor_count + (1 if self.gtm_container_ids else 0)
        return signals >= 2


def _sorted_unique(values: Any) -> tuple[str, ...]:
    return tuple(sorted({str(v) for v in values if v}))


def detect_tech_signals(html: str | None) -> TechSignals:
    """Detect the ad/marketing tech in a page's bytes. Pure — never fetches, never raises.

    `html` is the fetched page text (or a page + its concatenated GTM container, when the producer
    follows it). An empty/None body returns an all-False TechSignals, which the producer only stores
    when the fetch SUCCEEDED and the page was genuinely empty — a failed fetch is a status, not this.
    """
    text = html or ""
    evidence: dict[str, Any] = {}

    meta_ids = _sorted_unique(_META_PIXEL_ID.findall(text))
    meta = bool(meta_ids) or any(p.search(text) for p in _META_PIXEL_MARKERS)
    if meta:
        evidence["meta_pixel"] = list(meta_ids) or ["marker"]

    aw_ids = _sorted_unique(f"AW-{m}" for m in _AW_ID.findall(text))
    aw = bool(aw_ids) or any(p.search(text) for p in _AW_MARKERS)
    if aw:
        evidence["google_ads_conversion"] = list(aw_ids) or ["marker"]

    gtm_ids = _sorted_unique(f"GTM-{m}" for m in _GTM_ID.findall(text))
    if gtm_ids:
        evidence["gtm"] = list(gtm_ids)

    vendors: list[str] = []
    for vendor, patterns in _VENDOR_MARKERS.items():
        if any(p.search(text) for p in patterns):
            vendors.append(vendor)
    if vendors:
        evidence["vendor_tags"] = vendors

    guaranteed = any(p.search(text) for p in _GOOGLE_GUARANTEED)
    if guaranteed:
        evidence["google_guaranteed"] = True

    return TechSignals(
        meta_pixel=meta,
        meta_pixel_ids=meta_ids,
        google_ads_conversion=aw,
        aw_ids=aw_ids,
        gtm_container_ids=gtm_ids,
        vendor_tags=tuple(vendors),
        google_guaranteed=guaranteed,
        evidence=evidence,
    )


def looks_gtm_only(sig: TechSignals) -> bool:
    """A page carrying a GTM container but no inline pixel — the case where the §16a.1 container
    fetch matters (a pixel may be injected by the container and invisible to the inline scan)."""
    return bool(sig.gtm_container_ids) and not (sig.meta_pixel or sig.google_ads_conversion)


def merge_signals(page: TechSignals, container: TechSignals) -> TechSignals:
    """Fold a followed GTM container's detections into the page's. Pure — the container is scanned
    with the SAME detector, so a pixel injected via GTM is recovered (I-003 false-negative fix)."""
    evidence = {**page.evidence}
    if container.evidence:
        evidence["gtm_container"] = container.evidence
    return TechSignals(
        meta_pixel=page.meta_pixel or container.meta_pixel,
        meta_pixel_ids=_sorted_unique(page.meta_pixel_ids + container.meta_pixel_ids),
        google_ads_conversion=page.google_ads_conversion or container.google_ads_conversion,
        aw_ids=_sorted_unique(page.aw_ids + container.aw_ids),
        gtm_container_ids=page.gtm_container_ids,  # the container ids come from the page
        vendor_tags=_sorted_unique(page.vendor_tags + container.vendor_tags),
        google_guaranteed=page.google_guaranteed or container.google_guaranteed,
        gtm_followed=True,
        evidence=evidence,
    )


def summarize_tech(sig: TechSignals, *, fetch_status: str, final_url: str | None) -> dict[str, Any]:
    """The JSON-ready row for `prospect_tech_signal` (and the report read). Pure.

    `fetch_status` carries the measured-vs-found distinction into the row: 'ok' means the booleans
    are real findings; anything else means the fetch failed and the booleans are not evidence of
    absence (the reader must treat them as unknown)."""
    return {
        "fetch_status": fetch_status,
        "final_url": final_url,
        "meta_pixel": sig.meta_pixel,
        "meta_pixel_ids": list(sig.meta_pixel_ids),
        "google_ads_conversion": sig.google_ads_conversion,
        "aw_ids": list(sig.aw_ids),
        "gtm_container_ids": list(sig.gtm_container_ids),
        "gtm_followed": sig.gtm_followed,
        "vendor_tags": list(sig.vendor_tags),
        "google_guaranteed": sig.google_guaranteed,
        "evidence": sig.evidence,
    }
