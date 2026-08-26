"""Feature-extraction tests (scoring-spec §2-§3). The rules that decide unknown-vs-absent live in
`score_features`, so they are pinned here: a franchise flags (never excludes), an unscanned source
never fires a bin, deltas are unknown on the first scan, and reachability is excluded not defaulted.
"""

from __future__ import annotations

import pytest

from api.config import Settings
from api.services import score_features as sf
from api.services import scorecard, scorecard_config as sc

TH = Settings()
PARAMS = sc.load_params(Settings())


def test_geogrid_bins_by_coverage():
    assert sf._geogrid_bin(sf.FeatureInputs(coverage_pct=None), TH) == "geogrid_lt20_steep"  # I-076
    assert sf._geogrid_bin(sf.FeatureInputs(coverage_pct=0.0), TH) == "geogrid_lt20_steep"
    assert sf._geogrid_bin(sf.FeatureInputs(coverage_pct=19.9), TH) == "geogrid_lt20_steep"
    assert sf._geogrid_bin(sf.FeatureInputs(coverage_pct=20.0), TH) == "geogrid_20_50"
    assert sf._geogrid_bin(sf.FeatureInputs(coverage_pct=50.0), TH) == "geogrid_50_80"
    assert sf._geogrid_bin(sf.FeatureInputs(coverage_pct=80.0), TH) == "geogrid_50_80"
    assert sf._geogrid_bin(sf.FeatureInputs(coverage_pct=80.1), TH) == "geogrid_gt80"


def test_first_scan_is_unknown_not_absent():
    bins = sf.reply_bins(sf.FeatureInputs(coverage_pct=10.0), channel="phone", pass_number=1, thresholds=TH)
    assert "delta_first_scan" in bins
    # vendor-failing needs a delta -> omitted entirely (unknown, never absent).
    assert not any(b.startswith("vendor_failing") for b in bins)


def test_franchise_flags_never_excludes():
    inputs = sf.FeatureInputs(coverage_pct=10.0, franchise_status="flagged", rating=4.2)
    reply = sf.reply_bins(inputs, channel="phone", pass_number=1, thresholds=TH)
    close = sf.close_bins(inputs, thresholds=TH)
    assert "franchise" in reply
    assert "close_franchise_corporate" in close
    # It is still SCORED (the -87 / -116 coefficient fires), not removed from the run.
    r = scorecard.score_model(reply, channel="phone", model="reply", params=PARAMS)
    assert PARAMS.points_for("franchise") == -87.0
    assert any(f["bin"] == "franchise" for f in r.score_factors)


def test_unscanned_sources_never_fire_a_bin():
    # tech + organic + ai all unscanned -> none of their flags appear, even if the data fields are True.
    inputs = sf.FeatureInputs(
        coverage_pct=10.0, rating=4.0,
        meta_pixel=True, aw_tag=True, vendor_tag=True,        # tech_scanned defaults False
        organic_absent=True, ads_present=True, lsa_present=True,  # organic_scanned False
        ai_absent=True, ai_cites_competitors=True,            # ai_scanned False
    )
    bins = sf.reply_bins(inputs, channel="phone", pass_number=1, thresholds=TH)
    for absent in ("aw_tag", "vendor_tag", "meta_pixel", "organic_absent", "ads_gap",
                   "lsa_present_absent_pack", "ai_absent_0of3", "ai_cites_competitors"):
        assert absent not in bins, f"{absent} fired without its scan"


def test_scanned_sources_fire_their_flags():
    inputs = sf.FeatureInputs(
        coverage_pct=10.0, rating=4.0, in_pack=False, top10_organic=False,
        tech_scanned=True, meta_pixel=True, aw_tag=True, vendor_tag=True,
        organic_scanned=True, organic_absent=True, ads_present=True, lsa_present=True,
        ai_scanned=True, ai_absent=True, ai_cites_competitors=True,
    )
    bins = sf.reply_bins(inputs, channel="phone", pass_number=1, thresholds=TH)
    for present in ("aw_tag", "vendor_tag", "meta_pixel", "organic_absent", "ads_gap",
                    "lsa_present_absent_pack", "ai_absent_0of3", "ai_cites_competitors"):
        assert present in bins


def test_phone_reachability_excluded_when_type_unknown():
    # LA prospects all carry phone_type='unknown' -> reachability is excluded, not defaulted to 0.
    bins = sf.reply_bins(
        sf.FeatureInputs(coverage_pct=10.0, phone_type="unknown"),
        channel="phone", pass_number=1, thresholds=TH,
    )
    assert not any(b.startswith("reach_") for b in bins)
    # A known direct owner-operated line DOES fire the +50 bin.
    bins2 = sf.reply_bins(
        sf.FeatureInputs(coverage_pct=10.0, phone_type="direct", owner_operated=True),
        channel="phone", pass_number=1, thresholds=TH,
    )
    assert "reach_phone_direct_owner" in bins2


def test_email_reachability_excluded_at_pass_1():
    bins = sf.reply_bins(sf.FeatureInputs(coverage_pct=10.0, rating=4.0), channel="email",
                         pass_number=1, thresholds=TH)
    assert not any(b.startswith("reach_email") for b in bins)


def test_review_quartile_bins():
    top = sf.FeatureInputs(coverage_pct=50.0, review_quartile="top", review_count=200)
    assert "reviews_top_quartile" in sf.reply_bins(top, channel="phone", pass_number=1, thresholds=TH)
    # Bottom quartile requires >=10 reviews.
    low_few = sf.FeatureInputs(coverage_pct=50.0, review_quartile="bottom", review_count=3)
    assert "reviews_bottom_quartile" not in sf.reply_bins(low_few, channel="phone", pass_number=1, thresholds=TH)
    low_many = sf.FeatureInputs(coverage_pct=50.0, review_quartile="bottom", review_count=12)
    assert "reviews_bottom_quartile" in sf.reply_bins(low_many, channel="phone", pass_number=1, thresholds=TH)


def test_vendor_failing_fires_and_suppresses_representation():
    inputs = sf.FeatureInputs(
        coverage_pct=10.0, rating=4.0,
        tech_scanned=True, vendor_tag=True, likely_represented=True,
        delta_present=True, delta_lost_pack_15pp=True,
    )
    bins = sf.reply_bins(inputs, channel="phone", pass_number=1, thresholds=TH)
    assert "vendor_failing_pack" in bins
    # likely_represented is SUPPRESSED when vendor-failing fires (§Vendor-failing interaction).
    assert "likely_represented" not in bins
    assert sf.primary_pitch(inputs, bins) == "displacement"


def test_vendor_failing_omitted_without_delta_but_vendor_tag_still_flags():
    inputs = sf.FeatureInputs(coverage_pct=10.0, rating=4.0, tech_scanned=True, vendor_tag=True)
    bins = sf.reply_bins(inputs, channel="phone", pass_number=1, thresholds=TH)
    assert not any(b.startswith("vendor_failing") for b in bins)
    assert "vendor_tag" in bins   # scores as the ordinary +16 vendor flag


def test_extracted_selection_has_no_group_collision():
    """The extraction must never select two bins from one exclusive group (would double-count)."""
    inputs = sf.FeatureInputs(
        coverage_pct=10.0, rating=4.0, franchise_status="flagged", review_quartile="top",
        review_count=200, velocity="growing",
    )
    reply = sf.reply_bins(inputs, channel="phone", pass_number=1, thresholds=TH)
    close = sf.close_bins(inputs, thresholds=TH)
    scorecard.validate_selection(reply, model="reply", params=PARAMS)
    scorecard.validate_selection(close, model="close", params=PARAMS)


def test_primary_pitch_defaults_to_pain():
    inputs = sf.FeatureInputs(coverage_pct=10.0, rating=4.0)
    bins = sf.reply_bins(inputs, channel="phone", pass_number=1, thresholds=TH)
    assert sf.primary_pitch(inputs, bins) == "pain"


def test_review_distribution_and_quartile():
    dist = sf.review_distribution([1, 5, 10, 20, 50, 100, 200, 500])
    assert dist is not None
    assert dist.quartile(500) == "top"
    assert dist.quartile(1) == "bottom"
    assert dist.quartile(50) in ("mid", "top", "bottom")  # boundary-dependent, but not None
    assert dist.quartile(None) is None
    # Too few to be meaningful.
    assert sf.review_distribution([1, 2, 3]) is None


def test_close_bins_fire_on_current_data_shape():
    """The shape the first live run actually has: coverage + franchise + review quartile, no tech."""
    inputs = sf.FeatureInputs(coverage_pct=10.0, franchise_status="unknown", review_quartile="top",
                              review_count=300)
    close = sf.close_bins(inputs, thresholds=TH)
    assert "close_pain_geogrid_lt20" in close
    assert "close_reviews_top_quartile" in close
    # No decision-authority bin (not franchise, owner_operated unknown) — honest omission.
    assert "close_owner_dm" not in close and "close_franchise_corporate" not in close
