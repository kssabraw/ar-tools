"""Unit tests for backlink profiling pure helpers (no network)."""

from __future__ import annotations

from services import backlink_intel


def test_domain_of_strips_scheme_path_and_www():
    assert backlink_intel.domain_of("https://www.ace-plumbing.com/services") == "ace-plumbing.com"
    assert backlink_intel.domain_of("ace.com") == "ace.com"
    assert backlink_intel.domain_of("http://sub.ace.com") == "sub.ace.com"
    assert backlink_intel.domain_of("") is None
    assert backlink_intel.domain_of(None) is None


def test_compare_dr_and_referring_domains_behind_median():
    client = {"domain_rating": 30, "referring_domains": 50}
    competitors = [
        {"domain_rating": 50, "referring_domains": 100},
        {"domain_rating": 60, "referring_domains": 200},
        {"domain_rating": 55, "referring_domains": 150},
    ]
    cmp = backlink_intel.compare(client, competitors)
    assert cmp["competitor_median_dr"] == 55
    assert cmp["competitor_median_referring_domains"] == 150
    assert cmp["dr_behind"] == 25
    assert cmp["referring_domains_behind"] == 100


def test_compare_not_behind_when_client_leads():
    client = {"domain_rating": 80, "referring_domains": 500}
    competitors = [{"domain_rating": 40, "referring_domains": 100}]
    cmp = backlink_intel.compare(client, competitors)
    assert cmp["dr_behind"] is None
    assert cmp["referring_domains_behind"] is None


def test_detect_backlink_gap_thresholds():
    cmp = {"dr_behind": 25, "referring_domains_behind": 100,
           "competitor_median_dr": 55, "competitor_median_referring_domains": 150}
    assert backlink_intel.detect_backlink_gap(cmp, min_dr_behind=10, min_rd_behind=25) is not None
    # Both below threshold → no signal.
    small = {"dr_behind": 3, "referring_domains_behind": 5}
    assert backlink_intel.detect_backlink_gap(small, 10, 25) is None
    # Referring-domains gap alone (DR fine) still fires.
    rd_only = {"dr_behind": None, "referring_domains_behind": 60}
    assert backlink_intel.detect_backlink_gap(rd_only, 10, 25) is not None
