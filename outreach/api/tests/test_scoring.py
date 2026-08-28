"""Score-job pure-core tests (scoring.py). The I/O wrapper (`run_score`) is exercised live against
Outreacher during the session; here we pin the pure builders that decide the rows it writes."""

from __future__ import annotations

import pytest

from api.config import Settings
from api.services import score_features as sf
from api.services import scorecard_config as sc
from api.services import scoring

PARAMS = sc.load_params(Settings())
TH = Settings()


def test_assign_deciles_buckets_high_to_10_low_to_1():
    scores = [float(i) for i in range(100)]
    deciles = scoring.assign_deciles(scores)
    assert deciles[0] == 1        # lowest
    assert deciles[-1] == 10      # highest
    assert min(deciles) == 1 and max(deciles) == 10
    # Monotonic: a higher score never gets a lower decile.
    assert all(deciles[i] <= deciles[i + 1] for i in range(len(deciles) - 1))


def test_assign_deciles_degenerate_inputs():
    assert scoring.assign_deciles([]) == []
    assert scoring.assign_deciles([42.0]) == [10]


def test_build_inputs_maps_tech_and_review_quartile():
    view = {"coverage_pct": 12.0, "best_rank": 5, "centroid_dist_at_loss": 1.2}
    prospect = {"franchise_status": "unknown", "phone_type": "unknown", "rating": 4.3,
                "review_count": 300}
    tech = {"fetch_status": "ok", "meta_pixel": True, "google_ads_conversion": True,
            "vendor_tags": ["callrail"], "gtm_container_ids": ["GTM-XYZ"], "google_guaranteed": False}
    dist = sf.review_distribution([1, 5, 10, 50, 100, 300, 500, 900])
    inputs = scoring.build_inputs(view, prospect, tech, dist)
    assert inputs.coverage_pct == 12.0
    assert inputs.tech_scanned is True
    assert inputs.meta_pixel and inputs.aw_tag and inputs.vendor_tag
    # callrail + a GTM container = 2 marketing-stack signals -> likely_represented.
    assert inputs.likely_represented is True
    assert inputs.review_quartile == "top"


def test_build_inputs_missing_tech_is_unknown_not_absent():
    view = {"coverage_pct": 12.0}
    prospect = {"franchise_status": "unknown", "phone_type": "unknown", "rating": 4.0, "review_count": 5}
    inputs = scoring.build_inputs(view, prospect, None, None)
    assert inputs.tech_scanned is False
    assert inputs.meta_pixel is False and inputs.aw_tag is False


def test_build_inputs_failed_tech_fetch_is_not_scanned():
    # A stored tech row with a non-ok fetch_status is a status, not evidence — never scanned.
    tech = {"fetch_status": "unknown", "meta_pixel": False}
    inputs = scoring.build_inputs({"coverage_pct": 5.0}, {"rating": 4.0}, tech, None)
    assert inputs.tech_scanned is False


def test_build_inputs_no_organic_summary_is_unknown_not_absent():
    # Default (no organic scan for the submarket) leaves every organic field dormant — the pre-organic
    # behaviour, so a caller that doesn't pass a summary is unchanged.
    inputs = scoring.build_inputs({"coverage_pct": 5.0}, {"rating": 4.0, "website": "https://acme.com"}, None, None)
    assert inputs.organic_scanned is False
    assert inputs.organic_absent is False and inputs.top10_organic is False


def test_build_inputs_derives_organic_absent_from_the_submarket_serp():
    # A captured SERP that doesn't rank the prospect's domain -> scanned + absent (the pain signal).
    serp = {"results": [{"rank": 1, "domain": "rival.com"}, {"rank": 2, "domain": "other.com"}]}
    inputs = scoring.build_inputs(
        {"coverage_pct": 12.0}, {"rating": 4.0, "website": "https://acme.com"}, None, None,
        organic_summary=serp,
    )
    assert inputs.organic_scanned is True and inputs.organic_absent is True and inputs.top10_organic is False


def test_build_inputs_derives_top10_when_the_prospect_ranks():
    serp = {"results": [{"rank": 4, "domain": "acme.com"}]}
    inputs = scoring.build_inputs(
        {"coverage_pct": 12.0}, {"rating": 4.0, "website": "https://www.acme.com/x"}, None, None,
        organic_summary=serp,
    )
    assert inputs.organic_scanned is True and inputs.organic_absent is False and inputs.top10_organic is True


def test_score_one_produces_three_models_and_pitch():
    inputs = sf.FeatureInputs(coverage_pct=8.0, franchise_status="unknown", rating=4.1,
                              review_quartile="top", review_count=250)
    s = scoring.score_one(inputs, channel="phone", pass_number=1, params=PARAMS, thresholds=TH,
                          evidence_age_days=3, prospect_id="p1")
    assert s.reply.model == "reply" and s.close.model == "close"
    assert 0.0 <= s.value.predicted_prob <= 1.0
    # value = p_reply x p_close.
    assert s.value.predicted_prob == pytest.approx(s.reply.predicted_prob * s.close.predicted_prob, abs=1e-9)
    assert s.primary_pitch == "pain"


def test_to_records_shape_and_per_model_deciles():
    inputs_a = sf.FeatureInputs(coverage_pct=2.0, rating=4.0)      # severe pain -> high reply
    inputs_b = sf.FeatureInputs(coverage_pct=90.0, rating=4.0, franchise_status="flagged")  # low
    a = scoring.score_one(inputs_a, channel="phone", pass_number=1, params=PARAMS, thresholds=TH,
                          evidence_age_days=1, prospect_id="a")
    b = scoring.score_one(inputs_b, channel="phone", pass_number=1, params=PARAMS, thresholds=TH,
                          evidence_age_days=1, prospect_id="b")
    records = scoring.to_records([a, b], score_run_id="run1")
    assert len(records) == 6   # 2 prospects x 3 models
    models = sorted({r["model"] for r in records})
    assert models == ["close", "reply", "value"]
    for r in records:
        assert set(r) == {"score_run_id", "prospect_id", "pass", "channel", "primary_pitch",
                          "evidence_age_days", "model", "raw_points", "score", "predicted_prob",
                          "decile", "score_factors"}
        assert r["channel"] == "phone" and r["pass"] == 1
        assert 1 <= r["decile"] <= 10
    # value rows carry no points (composition).
    assert all(r["raw_points"] == 0.0 for r in records if r["model"] == "value")
    # The severe-pain prospect out-ranks the franchise incumbent on reply.
    reply_a = next(r for r in records if r["prospect_id"] == "a" and r["model"] == "reply")
    reply_b = next(r for r in records if r["prospect_id"] == "b" and r["model"] == "reply")
    assert reply_a["score"] > reply_b["score"]
    assert reply_a["decile"] >= reply_b["decile"]


def test_score_factors_on_records_are_replayable():
    from api.services import scorecard
    inputs = sf.FeatureInputs(coverage_pct=8.0, rating=4.0, franchise_status="unknown")
    s = scoring.score_one(inputs, channel="phone", pass_number=1, params=PARAMS, thresholds=TH,
                          evidence_age_days=0, prospect_id="p")
    records = scoring.to_records([s], score_run_id="r")
    for r in records:
        if r["model"] == "value":
            continue
        replayed = scorecard.replay_score(
            r["score_factors"], lambda_shrink=PARAMS.lambda_shrink, target=PARAMS.target
        )
        assert replayed == pytest.approx(r["score"], abs=1e-9)
