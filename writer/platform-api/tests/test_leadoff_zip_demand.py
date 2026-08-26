"""Unit tests for the LeadOff ZIP-demand Phase 0b probe pure helpers."""
from services.leadoff_zip_demand import pick_probe_zips, probe_verdict


class TestPickProbeZips:
    LOCS = [
        {"location_code": 1, "location_name": "60601,Illinois,United States", "location_type": "Postal Code"},
        {"location_code": 2, "location_name": "60602,Illinois,United States", "location_type": "Postal Code"},
        {"location_code": 9, "location_name": "Chicago,Illinois,United States", "location_type": "City"},
        {"location_code": 3, "location_name": "90210,California,United States", "location_type": "Postal Code"},
        {"location_code": 4, "location_name": "60614,Illinois,United States", "location_type": "Postal Code"},
    ]

    def test_filters_by_type_and_prefix(self):
        got = pick_probe_zips(self.LOCS, "606", 10)
        assert [g["location_code"] for g in got] == [1, 2, 4]  # cities + 902xx excluded

    def test_caps_at_n(self):
        assert len(pick_probe_zips(self.LOCS, "606", 2)) == 2

    def test_no_match(self):
        assert pick_probe_zips(self.LOCS, "303", 5) == []


class TestProbeVerdict:
    def test_pass_when_null_share_low(self):
        results = [{"volume": 5400, "error": None}, {"volume": 3200, "error": None},
                   {"volume": None, "error": None}, {"volume": 1100, "error": None}]
        v = probe_verdict(results, 0.6)
        assert v["verdict"] == "pass"
        assert v["queried"] == 4 and v["non_null"] == 3 and v["null_share"] == 0.25

    def test_inconclusive_when_mostly_null(self):
        results = [{"volume": None, "error": None}] * 8 + [{"volume": 20, "error": None}] * 2
        v = probe_verdict(results, 0.6)
        assert v["verdict"] == "inconclusive" and v["null_share"] == 0.8

    def test_error_when_nothing_queried(self):
        v = probe_verdict([{"volume": None, "error": "boom"}], 0.6)
        assert v["verdict"] == "error" and v["queried"] == 0

    def test_errored_zips_excluded_from_share(self):
        # a task error is not a "null volume" — only queried ZIPs count.
        results = [{"volume": 900, "error": None}, {"volume": None, "error": "timeout"}]
        v = probe_verdict(results, 0.6)
        assert v["queried"] == 1 and v["non_null"] == 1 and v["null_share"] == 0.0
        assert v["verdict"] == "pass"
