"""Feature EXTRACTION (scoring-spec.md §2-§3): DB-shaped prospect signals -> scorecard bins.

Pure. Takes a `FeatureInputs` (assembled by the score job from stored rows — coverage, tech,
franchise, review distribution, deltas) and returns the bin selection per model/channel, plus the
primary pitch. The ENGINE (`scorecard.py`) then sums points; extraction decides WHICH bins fire.

The invariants live here, because this is where "unknown vs absent" is decided:

  * Unknown == absent for ad/tech/AI/organic signals — a source that was not scanned contributes
    NOTHING and never subtracts (CLAUDE.md). Every such flag is gated on `*_scanned`.
  * A franchise flag flags for review — it fires the -87 / -116 bin, it never excludes.
  * Deltas are unknown on the first two scans (need three: the mean of the prior two, §Deltas /
    START-HERE Phase 4). Extraction emits `delta_first_scan` (an explicit 0-point unknown), and
    vendor-failing (which needs a delta) is simply omitted — unknown, never absent.
  * Pass 1 EXCLUDES reachability rather than defaulting it (START-HERE Phase 4). Phone reachability
    is emitted only when `phone_type` is a known kind; email reachability only at pass 2 with
    enrichment. An unmeasured channel is left out of the factors entirely, not scored at a
    reference bin — a 0 that reads as "measured, average" is a claim, and it is false here.

Every coefficient is an elicited prior; treat rank order as a strong prior, not a prediction, until
~100 prospects have been contacted (CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FeatureInputs:
    """One prospect's stored signals, already read from the DB and normalized. Pure input.

    A field left at its default means "not measured" — which for a one-directional signal means the
    bin is omitted (absent), never a negative. Only the geogrid coverage and franchise flag are ever
    present for a prospect in a scanned submarket today; everything else fills as producers run.
    """

    # --- Maps geogrid (always present for a scored prospect — it is why the submarket was scanned)
    # coverage_pct is None when the prospect has NO coverage row inside a MEASURED submarket, which
    # per ISSUES I-076 is total invisibility (0%), not unknown — the job only scores prospects in a
    # submarket carrying a completion marker.
    coverage_pct: float | None = None
    best_rank: int | None = None
    centroid_dist_at_loss: float | None = None

    # --- Base-pull identity
    franchise_status: str | None = None          # 'flagged' | 'confirmed_franchise' | 'unknown'
    phone_type: str | None = None                # 'unknown' today for every LA prospect
    rating: float | None = None
    review_count: int | None = None
    review_quartile: str | None = None           # 'top' | 'bottom' | 'mid' (job computes from market)
    owner_operated: bool | None = None
    multi_location: bool | None = None
    years_in_business: int | None = None

    # --- Site tech (scan-tech; free). scanned=False => every flag below is unknown==absent.
    tech_scanned: bool = False
    meta_pixel: bool = False
    aw_tag: bool = False
    vendor_tag: bool = False                      # any CallRail/Podium/Birdeye tag
    google_guaranteed: bool = False              # LSA / Google Guaranteed badge on the site
    likely_represented: bool = False             # 2+ agency/marketing-stack signals

    # --- Organic SERP (scan-organic; paid). scanned=False => unknown==absent.
    organic_scanned: bool = False
    organic_absent: bool = False                 # no top-20 organic presence
    ads_present: bool = False                    # Google Ads advertiser is this prospect
    lsa_present: bool = False                    # LSA/Google-Guaranteed placement for this prospect
    top10_organic: bool = False                  # has a top-10 organic result
    in_pack: bool | None = None                  # is the prospect in the local pack (from geogrid)

    # --- AI answers (scan-ai; paid). scanned=False => unknown==absent.
    ai_scanned: bool = False
    ai_absent: bool = False                      # not mentioned in 0/3 samples
    ai_cites_competitors: bool = False           # AI names >=3 competitors, not them

    # --- Deltas (need >=2 prior snapshots). present=False => first scan, unknown, never absent.
    delta_present: bool = False
    delta_lost_pack_15pp: bool = False
    delta_competitor_overtook: bool = False
    delta_ads_newly_on: bool = False
    delta_dropped_ai: bool = False
    delta_organic_lost5: bool = False
    delta_velocity_stalled: bool = False
    velocity: str | None = None                  # 'declining' | 'growing' | 'flat' (needs history)


def _is_franchise(inputs: FeatureInputs) -> bool:
    return (inputs.franchise_status or "").lower() in ("flagged", "confirmed_franchise")


def _geogrid_bin(inputs: FeatureInputs, thresholds) -> str:
    """scoring-spec §Geogrid-pain. coverage None inside a measured submarket == 0% (I-076).

    A coverage below the low threshold maps to the `_steep` pain bin unconditionally: there is no
    non-steep <low bin in the spec, and gating the pipeline's PRIMARY discriminator on an unreliable
    decay computation would zero out the strongest signal in the market (logged as a spec ambiguity;
    the decay refinement lands with a reliable per-pin measurement).
    """
    cov = inputs.coverage_pct if inputs.coverage_pct is not None else 0.0
    if cov < thresholds.score_geogrid_low_pct:
        return "geogrid_lt20_steep"
    if cov < thresholds.score_geogrid_mid_pct:
        return "geogrid_20_50"
    if cov <= thresholds.score_geogrid_high_pct:
        return "geogrid_50_80"
    return "geogrid_gt80"


def _change_signal_bin(inputs: FeatureInputs) -> str:
    """One change-signal bin (the strongest that fired), or the explicit first-scan unknown."""
    if not inputs.delta_present:
        return "delta_first_scan"
    # Ordered by weight — the strongest fired delta is the opener (scoring-spec §Change signals).
    for flag, bin_name in (
        (inputs.delta_lost_pack_15pp, "delta_lost_pack_15pp"),
        (inputs.delta_competitor_overtook, "delta_competitor_overtook"),
        (inputs.delta_ads_newly_on, "delta_ads_newly_on"),
        (inputs.delta_dropped_ai, "delta_dropped_ai"),
        (inputs.delta_organic_lost5, "delta_organic_lost5"),
        (inputs.delta_velocity_stalled, "delta_velocity_stalled"),
    ):
        if flag:
            return bin_name
    return "delta_none"


def _vendor_failing_bin(inputs: FeatureInputs) -> str | None:
    """scoring-spec §Vendor-failing: a vendor tag AND a measured decline. Needs a delta, so it is
    UNKNOWN (omitted) until deltas exist — never `absent`. Returns None when it cannot be evaluated."""
    if not inputs.delta_present or not inputs.vendor_tag:
        return None
    if inputs.delta_lost_pack_15pp:
        return "vendor_failing_pack"
    if inputs.delta_organic_lost5:
        return "vendor_failing_organic"
    return None  # vendor tag, no measured decline -> scores as the ordinary vendor_tag flag (+16)


def _decision_structure_bin(inputs: FeatureInputs, *, vendor_failing: bool) -> str:
    """scoring-spec §Decision-structure. Vendor-failing SUPPRESSES likely_represented (the interaction
    in §Vendor-failing): when the incumbent is visibly failing, representation is the premise of the
    pitch, not an obstacle. Franchise wins over everything (it is the -87 flag-for-review bin)."""
    if _is_franchise(inputs):
        return "franchise"
    if inputs.likely_represented and not vendor_failing:
        return "likely_represented"
    if inputs.owner_operated:
        return "owner_operated"
    return "independent"


def reply_bins(inputs: FeatureInputs, *, channel: str, pass_number: int, thresholds) -> list[str]:
    """The Model A (reply) bin selection for one channel + pass. See module docstring for the rules."""
    bins: list[str] = []

    # Reachability — channel-specific, and EXCLUDED (not defaulted) when unmeasured (START-HERE P4).
    if channel == "phone":
        pt = (inputs.phone_type or "").lower()
        if pt in ("direct", "direct_owner", "mobile") and inputs.owner_operated:
            bins.append("reach_phone_direct_owner")
        elif pt in ("main", "corporate", "toll_free") or (inputs.multi_location and pt):
            bins.append("reach_phone_gatekept")
        elif pt in ("listed", "landline", "local"):
            bins.append("reach_phone_listed")
        # pt in {'', 'unknown'} -> unmeasured -> excluded, not a reference 0.
    elif channel == "email" and pass_number >= 2:
        # Email reachability requires enrichment (pass 2). Pass 1 excludes it entirely.
        # (Enrichment-driven; the enrichment table is Phase 5, so this is dormant wiring.)
        pass

    # Change signals — explicit first-scan unknown or the strongest fired delta.
    bins.append(_change_signal_bin(inputs))

    # Vendor-failing (compound, highest-intent) — only when evaluable.
    vendor_failing = _vendor_failing_bin(inputs)
    if vendor_failing is not None:
        bins.append(vendor_failing)

    # Case-study proof match — AR holds none in target verticals; case_none is the active reference.
    bins.append("case_none")

    # Geogrid pain — always (the reason the submarket was scanned).
    bins.append(_geogrid_bin(inputs, thresholds))

    # GBP gate — Stage 1 captures rating only, not photos/categories, so strong/weak stay dormant and
    # GBP scores at the `adequate` reference (0). Emitted when rating is present so the factors read
    # as "GBP considered"; omitted with no rating at all.
    if inputs.rating is not None:
        bins.append("gbp_adequate")

    # Organic / AI pain — independent additive flags, gated on their scan (unknown == absent).
    if inputs.organic_scanned and inputs.organic_absent:
        bins.append("organic_absent")
    if inputs.ai_scanned and inputs.ai_absent:
        bins.append("ai_absent_0of3")
    if inputs.ai_scanned and inputs.ai_cites_competitors:
        bins.append("ai_cites_competitors")

    # Buying intent — independent additive flags. SERP-derived ones gate on the organic scan; tag
    # ones gate on the tech scan. Absence never subtracts.
    absent_from_pack = inputs.in_pack is False
    if inputs.organic_scanned and inputs.lsa_present and absent_from_pack:
        bins.append("lsa_present_absent_pack")
    if inputs.organic_scanned and inputs.ads_present and not inputs.top10_organic and absent_from_pack:
        bins.append("ads_gap")
    if inputs.tech_scanned and inputs.aw_tag:
        bins.append("aw_tag")
    if inputs.tech_scanned and inputs.vendor_tag:
        bins.append("vendor_tag")
    if inputs.tech_scanned and inputs.meta_pixel:
        bins.append("meta_pixel")

    # Decision structure — franchise flags (never excludes); vendor-failing suppresses represented.
    bins.append(_decision_structure_bin(inputs, vendor_failing=vendor_failing is not None))

    # Trajectory — velocity needs history (omitted until it exists); review quartile is computable now.
    if inputs.velocity in ("declining", "growing", "flat"):
        bins.append({"declining": "velocity_declining", "growing": "velocity_growing",
                     "flat": "velocity_flat"}[inputs.velocity])
    if inputs.review_quartile == "top":
        bins.append("reviews_top_quartile")
    elif inputs.review_quartile == "bottom" and (inputs.review_count or 0) >= thresholds.score_review_bottom_min:
        bins.append("reviews_bottom_quartile")

    return bins


def close_bins(inputs: FeatureInputs, *, thresholds) -> list[str]:
    """The Model B (close | reply) bin selection (scoring-spec §3). Channel-independent."""
    bins: list[str] = []

    # Decision authority.
    if _is_franchise(inputs):
        bins.append("close_franchise_corporate")
    elif inputs.owner_operated:
        bins.append("close_owner_dm")

    # Proven spend — ad-spend MAGNITUDE bands are the deferred Slice B2 (unknown -> omitted). LSA is
    # a proven-spend flag from the organic scan.
    if inputs.organic_scanned and (inputs.lsa_present or inputs.google_guaranteed):
        bins.append("close_lsa_active")

    # Displaceable budget — vendor tags now; vendor-failing needs a delta (omitted until it exists).
    if inputs.delta_present and inputs.vendor_tag and inputs.delta_lost_pack_15pp:
        bins.append("close_vendor_failing")
    elif inputs.tech_scanned and inputs.vendor_tag:
        bins.append("close_vendor_tags")

    # Representation.
    if inputs.likely_represented:
        bins.append("close_likely_represented")

    # Capacity — review quartile + multi-location.
    if inputs.review_quartile == "top":
        bins.append("close_reviews_top_quartile")
    elif inputs.review_quartile == "bottom" and (inputs.review_count or 0) >= thresholds.score_review_bottom_min:
        bins.append("close_reviews_bottom_quartile")
    if inputs.multi_location:
        bins.append("close_multi_location")

    # Stability.
    if (inputs.years_in_business or 0) > 5:
        bins.append("close_years_gt5")

    # Pain — a replier has conceded the pain, so it barely moves close (scoring-spec §3, +13).
    cov = inputs.coverage_pct if inputs.coverage_pct is not None else 0.0
    if cov < thresholds.score_geogrid_low_pct:
        bins.append("close_pain_geogrid_lt20")

    return bins


def primary_pitch(inputs: FeatureInputs, reply_selection: list[str]) -> str:
    """scoring-spec §2: displacement (vendor-failing) > proof (case study) > pain (default)."""
    if any(b in ("vendor_failing_pack", "vendor_failing_organic") for b in reply_selection):
        return "displacement"
    if any(b in ("case_same_vertical_comparable", "case_same_vertical_any", "case_adjacent_comparable")
           for b in reply_selection):
        return "proof"
    return "pain"


@dataclass(frozen=True)
class ReviewDistribution:
    """Market-wide review-count quartile cut points, computed once per score run."""

    p25: float
    p75: float

    def quartile(self, review_count: int | None) -> str | None:
        if review_count is None:
            return None
        if review_count >= self.p75:
            return "top"
        if review_count <= self.p25:
            return "bottom"
        return "mid"


def review_distribution(review_counts: list[int]) -> ReviewDistribution | None:
    """25th/75th percentile of a market's review counts (nearest-rank). None if too few to be meaningful."""
    counts = sorted(c for c in review_counts if c is not None)
    if len(counts) < 4:
        return None

    def _pct(p: float) -> float:
        if not counts:
            return 0.0
        idx = min(len(counts) - 1, max(0, int(round(p * (len(counts) - 1)))))
        return float(counts[idx])

    return ReviewDistribution(p25=_pct(0.25), p75=_pct(0.75))
