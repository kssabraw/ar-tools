"""Unit tests for the LeadOff brand-footprint pure helpers (no network/DB)."""
from services.leadoff_brand import (
    attach_footprint,
    brand_key,
    footprint_estimate,
    median,
    parse_mentions_summary,
    parse_site_count,
    top5_from_items,
)


class TestKeysAndCosts:
    def test_brand_key_is_global_norm(self):
        # no |city_id suffix — franchises dedupe across markets
        assert brand_key("Roto-Rooter Plumbing") == brand_key("ROTO-ROOTER Plumbing ")
        assert "|" not in brand_key("Bill Howe Plumbing")

    def test_estimate(self):
        # 5 site queries + 5 mention summaries ≈ $0.16
        assert footprint_estimate(5, 5) == 0.16
        assert footprint_estimate(0, 0) == 0.0


class TestParsing:
    def test_site_count_from_se_results_count(self):
        task = {"result": [{"se_results_count": 1240}]}
        assert parse_site_count(task) == 1240
        assert parse_site_count({"result": [{}]}) is None
        assert parse_site_count({"result": None}) is None

    def test_mentions_summary(self):
        task = {"result": [{"total_count": 4310,
                            "connotation_types": {"positive": 900,
                                                  "negative": 40,
                                                  "neutral": 3370}}]}
        out = parse_mentions_summary(task)
        assert out == {"citations": 4310, "positive": 900, "negative": 40}

    def test_mentions_summary_defensive(self):
        assert parse_mentions_summary({"result": None}) is None
        out = parse_mentions_summary({"result": [{"total_count": 7}]})
        assert out["citations"] == 7 and out["positive"] is None


class TestTop5:
    def test_top5_from_maps_items(self):
        items = [
            {"rank_group": 1, "title": "Acme Pest", "domain": "acmepest.com"},
            {"rank_group": 2, "title": "Beta Bugs", "domain": None},
            {"rank_group": 6, "title": "Too Deep", "domain": "toodeep.com"},
            {"rank_group": 3, "title": "", "domain": "noname.com"},
        ]
        out = top5_from_items(items)
        assert [o["business_name"] for o in out] == ["Acme Pest", "Beta Bugs"]
        assert out[0]["domain"] == "acmepest.com"
        assert out[1]["domain"] is None


class TestAttach:
    def test_medians_attached_per_category(self):
        rows = [{"category": "pest control service", "grade": "B"}]
        top5 = {"pest control service": [
            {"business_name": "Acme Pest", "domain": "acmepest.com"},
            {"business_name": "Beta Bugs", "domain": "betabugs.com"},
            {"business_name": "Gamma Exterminators", "domain": None},
        ]}
        sites = {"acmepest.com": 120, "betabugs.com": 4000}
        mentions = {brand_key("Acme Pest"): 50,
                    brand_key("Beta Bugs"): 900,
                    brand_key("Gamma Exterminators"): 10}
        out = attach_footprint(rows, top5, sites, mentions)
        assert out[0]["field_pages_med"] == 2060   # median of [120, 4000]
        assert out[0]["field_mentions_med"] == 50  # median of [10, 50, 900]
        assert out[0]["grade"] == "B"              # original keys intact

    def test_no_data_passes_through(self):
        rows = [{"category": "locksmith", "grade": "A"}]
        out = attach_footprint(rows, {}, {}, {})
        assert out[0]["field_pages_med"] is None
        assert out[0]["field_mentions_med"] is None

    def test_median(self):
        assert median([3, 1, 2]) == 2
        assert median([1, 2, 3, 4]) == 2.5
        assert median([]) is None
