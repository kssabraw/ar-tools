"""Unit tests for the Local Rank Analysis report builder (Maps Module #5)."""

import pytest

from services import maps_report as mr


def test_keyword_tokens_drops_generic_words():
    assert mr.keyword_tokens("roofing contractor near me") == ["roofing"]
    assert mr.keyword_tokens("emergency HVAC repair") == ["emergency", "hvac", "repair"]


def test_name_keyword_hit():
    toks = mr.keyword_tokens("roofing near me")
    assert mr.name_keyword_hit("Metropolitan Roofing Co", toks) == "roofing"
    assert mr.name_keyword_hit("BRP Home Services", toks) is None


def test_client_sab_or_physical():
    assert mr.client_sab_or_physical({"address": "123 Main St"}) == "Physical"
    assert mr.client_sab_or_physical({"address": ""}) == "SAB"
    assert mr.client_sab_or_physical(None) == "SAB"


def test_competitor_diagnostics_filters_and_ranks():
    competitors = [
        {"name": "Ace Roofing", "rating": 4.9, "reviews": 300, "primary_category": "Roofer"},
        {"name": "Budget Roof", "rating": 4.2, "reviews": 999, "primary_category": "Roofer"},  # below min rating
        {"name": "Pro Roofers", "rating": 4.8, "reviews": 120, "primary_category": "Roofer"},
    ]
    out = mr.competitor_diagnostics(competitors, client_reviews=50, keyword="roofing", min_rating=4.7)
    assert [c["name"] for c in out] == ["Ace Roofing", "Pro Roofers"]  # 4.2 excluded, sorted by reviews
    assert out[0]["review_gap_vs_client"] == 250
    assert out[0]["gbp_name_keyword"] == "roofing"
    assert out[0]["sab_physical"] is None


def test_weak_sector_competitors_tally():
    # 3x3 grid; row 0 = north. competitors_above on the NE corner pin only.
    directory = {"p1": {"name": "North Star Roofing"}}
    grid = [
        [None, None, [["p1", 1]]],  # (0,2) = NE
        [None, [], None],           # centre: client 1st
        [None, None, None],
    ]
    ca = {"directory": directory, "grid": grid}
    notes = mr.weak_sector_competitors(ca, weak_octants=["NE", "SW"])
    assert notes["NE"] == [{"place_id": "p1", "name": "North Star Roofing", "pins": 1}]
    assert notes["SW"] == []


def test_build_snapshot_shape():
    client = {"name": "First Class Roofing", "gbp": {"gbp_rating": 4.6, "gbp_review_count": 40,
              "gbp_category": "Roofing contractor", "address": "1 Main St"}}
    analytics = {
        "azimuth_offset_deg": 0.0,
        "overall": {"avg_rank": 5.0, "coverage_pct_top3": 30.0, "coverage_pct_top10": 60.0},
        "performance_horizon": {"ring": 2, "radius_mi": 2.0, "coverage_pct_top3": 10.0},
        "best_directions": [{"sector": "E", "sector_full": "East", "avg_rank": 2.0, "coverage_pct_top3": 80.0}],
        "weakest_directions": [{"sector": "W", "sector_full": "West", "avg_rank": 9.0, "coverage_pct_top3": 5.0}],
        "ring_summaries": [{"ring": 1, "radius_mi": 1.0, "avg_rank": 2.0, "coverage_pct_top3": 80.0,
                            "coverage_pct_top10": 100.0, "cells": 5, "ranked": 5, "not_ranked": 0}],
        "sectors_overall": [{"sector": "W", "sector_full": "West", "avg_rank": 9.0, "coverage_pct_top3": 5.0}],
    }
    result_row = {
        "keyword": "roofing near me",
        "competitors": [{"name": "Ace Roofing", "rating": 4.9, "reviews": 300, "primary_category": "Roofer"}],
        "competitors_above": None,
    }
    snap = mr.build_snapshot(client, result_row, analytics)
    assert snap["client"]["name"] == "First Class Roofing"
    assert snap["client"]["sab_physical"] == "Physical"
    assert snap["competitor_top5"][0]["name"] == "Ace Roofing"
    assert snap["overall"]["coverage_pct_top3"] == 30.0
    assert "W" in mr.json.dumps(snap)  # weakest sector carried through


@pytest.mark.asyncio
async def test_generate_report_for_result_assembles_fields(monkeypatch):
    async def fake_llm(snapshot):
        return {"summary": "# Local Rank Analysis — Test\n\nbody",
                "weak_directions": "West fades past 2 mi.",
                "top_competitors": ["Ace Roofing — 4.9 — 300"]}
    monkeypatch.setattr(mr, "_call_llm", fake_llm)

    client = {"name": "Test Co", "gbp": {"gbp_rating": 4.6, "gbp_review_count": 40, "address": "1 Main St"}}
    scan_row = {"id": "s1", "center_lat": 37.77, "center_lng": -122.41, "completed_at": "2026-06-23T00:00:00Z"}
    grid = [[1 for _ in range(7)] for _ in range(7)]
    grid[0] = [None] * 7  # weaken the north edge
    result_row = {"id": "r1", "keyword": "roofing", "rank_grid": grid,
                  "competitors": [{"name": "Ace", "rating": 4.9, "reviews": 300}], "competitors_above": None}

    fields = await mr.generate_report_for_result(client, scan_row, result_row)
    assert fields["report_status"] == "complete"
    assert fields["report_md"].startswith("# Local Rank Analysis")
    assert fields["report_top_competitors"] == ["Ace Roofing — 4.9 — 300"]
    assert "ring_summaries" in fields["report_analytics"]
    assert fields["report_octant_pins"]["ok"] in (True, False)  # ran without throwing
