"""Unit tests for the LeadOff brand-footprint pure helpers (no network/DB)."""
from services.leadoff_brand import (
    attach_footprint,
    brand_key,
    digits,
    filter_rows_by_locale,
    is_generic_name,
    median,
    mention_cost,
    mention_domains_from_rows,
    parse_mentions_summary,
    parse_referring_domains,
    parse_search_rows,
    parse_site_count,
    top5_from_items,
    unlinked_count,
)


class TestKeysAndCosts:
    def test_brand_key_is_global_norm(self):
        # no |city_id suffix — franchises dedupe across markets
        assert brand_key("Roto-Rooter Plumbing") == brand_key("ROTO-ROOTER Plumbing ")
        assert "|" not in brand_key("Bill Howe Plumbing")

    def test_mention_cost_tiers(self):
        assert mention_cost(generic=False, deep=False, has_phone=True) == 0.03
        # generic light = search + NAP
        assert mention_cost(generic=True, deep=False, has_phone=True) == 0.09
        # generic light without a phone = search only
        assert mention_cost(generic=True, deep=False, has_phone=False) == 0.06
        # deep = search + unlinked list + NAP
        assert mention_cost(generic=False, deep=True, has_phone=True) == 0.14
        assert mention_cost(generic=True, deep=True, has_phone=False) == 0.11


class TestGenericNames:
    def test_category_city_stopword_names_are_generic(self):
        assert is_generic_name("Pest Control KC", "pest control service",
                               "Kansas City")
        assert is_generic_name("Kansas City Locksmith", "locksmith",
                               "Kansas City")
        assert is_generic_name("Best Pest Control Services",
                               "pest control service", "Kansas City")

    def test_distinctive_brands_are_not(self):
        assert not is_generic_name("Saela Pest Control",
                                   "pest control service", "Kansas City")
        assert not is_generic_name("Roto-Rooter", "plumber", "Kansas City")
        assert not is_generic_name("Blue Beetle Pest Control",
                                   "pest control service", "Kansas City")

    def test_locale_filter_keeps_city_or_phone_rows(self):
        rows = [
            {"content_info": {"snippet": "Great pest control in Kansas City"}},
            {"content_info": {"snippet": "pest control tips for your garden"}},
            {"title": "Call (816) 555-1234 today"},
        ]
        kept = filter_rows_by_locale(rows, "Kansas City", "816-555-1234")
        assert len(kept) == 2  # city match + phone match; the tips page drops

    def test_digits(self):
        assert digits("(816) 555-1234") == "8165551234"
        assert digits(None) == ""


class TestUnlinked:
    def test_mention_minus_referring_minus_own(self):
        mentions = {"yelp.com", "kctoday.com", "acmepest.com", "linkedpr.com"}
        referring = {"www.linkedpr.com"}
        # own site + the linking domain drop → yelp + kctoday remain
        assert unlinked_count(mentions, referring, "www.acmepest.com") == 2

    def test_domains_from_rows(self):
        rows = [{"domain": "Yelp.com"}, {"url": "https://www.kctoday.com/x"},
                {"domain": None}]
        assert mention_domains_from_rows(rows) == {"yelp.com", "kctoday.com"}


class TestParsing:
    def test_site_count_from_se_results_count(self):
        assert parse_site_count({"result": [{"se_results_count": 1240}]}) == 1240
        assert parse_site_count({"result": [{}]}) is None
        assert parse_site_count({"result": None}) is None

    def test_mentions_summary(self):
        task = {"result": [{"total_count": 4310,
                            "connotation_types": {"positive": 900,
                                                  "negative": 40,
                                                  "neutral": 3370}}]}
        out = parse_mentions_summary(task)
        assert out == {"citations": 4310, "positive": 900, "negative": 40}
        assert parse_mentions_summary({"result": None}) is None

    def test_search_rows(self):
        total, rows = parse_search_rows(
            {"result": [{"total_count": 77, "items": [{"domain": "a.com"}]}]})
        assert total == 77 and rows == [{"domain": "a.com"}]
        assert parse_search_rows({"result": None}) == (None, [])

    def test_referring_domains(self):
        task = {"result": [{"items": [{"domain": "x.com"}, {"domain": None}]}]}
        assert parse_referring_domains(task) == {"x.com"}


class TestTop5:
    def test_top5_from_maps_items_with_phone(self):
        items = [
            {"rank_group": 1, "title": "Acme Pest", "domain": "acmepest.com",
             "phone": "(816) 555-1234"},
            {"rank_group": 2, "title": "Beta Bugs", "domain": None},
            {"rank_group": 6, "title": "Too Deep", "domain": "toodeep.com"},
            {"rank_group": 3, "title": "", "domain": "noname.com"},
        ]
        out = top5_from_items(items)
        assert [o["business_name"] for o in out] == ["Acme Pest", "Beta Bugs"]
        assert out[0]["phone"] == "(816) 555-1234"
        assert out[1]["domain"] is None and out[1]["phone"] is None


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
