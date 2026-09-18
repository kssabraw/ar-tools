"""Unit tests for the LeadOff paid-action port (pure logic only — no Supabase,
no DataForSEO). Conformance target: docs/reference/leadoff-scanner/
check_city.py + enrich_shortlist.py — the methodology + cache contracts."""
from datetime import datetime, timedelta, timezone

from services.leadoff_actions import (
    category_tokens,
    demand_from_items,
    field_stats,
    holder_label,
    pick_monthly,
    same_month_growth,
    scout_estimate,
    spent_today,
    trend_date_from,
    trend_row,
    tryout_market_comps,
    tryout_result_row,
    tryout_rows,
    tryout_scoutable,
    velocity_row,
)

NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)
# 101-point reference: thresholds 0,10,…,1000 (same shape as the live table)
BREAKPOINTS = [i * 10.0 for i in range(101)]


def _serp_item(title, votes, rating=4.8, category="Locksmith"):
    return {"title": title, "category": category,
            "rating": {"votes_count": votes, "value": rating}}


class TestCategoryQuirks:
    def test_handyman_rename_alias(self):
        # lesson #3: Google renamed the label — holders must match the new one
        assert holder_label("Handyman") == "handyman handywoman handyperson"

    def test_plumbing_maps_to_plumber(self):
        assert holder_label("Plumbing") == "plumber"

    def test_normal_category_passthrough(self):
        assert holder_label("Roofing Contractor") == "roofing contractor"

    def test_tokens_drop_stopwords_and_short_words(self):
        # "tree service" → only "tree" is a token... but len>=4 keeps "tree";
        # "service" is a stopword.
        assert category_tokens("Tree Service") == ["tree"]
        # 6-char prefix: "locksmith" → "locksm"
        assert category_tokens("Locksmith") == ["locksm"]


class TestDemand:
    def test_both_forms_max_wins(self):
        # lesson #4: near-me dominates in many markets (KC locksmith)
        items = [
            {"keyword": "locksmith", "search_volume": 880, "cpc": 9.5},
            {"keyword": "locksmith near me", "search_volume": 1900, "cpc": 11.0},
        ]
        d = demand_from_items(items, ["Locksmith"])
        assert d["Locksmith"]["vol"] == 1900
        assert d["Locksmith"]["cpc"] == 9.5  # base form preferred

    def test_missing_category_is_zero(self):
        d = demand_from_items([], ["Plumber"])
        assert d["Plumber"]["vol"] == 0 and d["Plumber"]["cpc"] is None


class TestFieldStats:
    ITEMS = [
        _serp_item("Harry's Key Service", 46),
        _serp_item("Locksmith Plus", 201),
        _serp_item("Minute Key", 10),
        _serp_item("KeyMe Locksmiths", 21, rating=4.1),
        _serp_item("Anytown Garage", 36, category="Garage door supplier"),
        _serp_item("Sixth Business", 500),  # outside top-5
    ]

    def test_stats_shape(self):
        s = field_stats(self.ITEMS, "Locksmith")
        assert s["supply"] == 6
        # top-5 votes 46,201,10,21,36 → sorted desc 201,46,36,21,10 →
        # rev_win = 3rd-highest = 36 (reviews to beat #3)
        assert s["rev_win"] == 36
        assert s["avg5"] == round((46 + 201 + 10 + 21 + 36) / 5, 1)
        # namekw: top-5 titles containing "locksm" → Locksmith Plus, KeyMe Locksmiths
        assert s["namekw"] == 2
        # holders: normalized category == "locksmith" over ALL items (5 of 6 —
        # only the garage-door supplier differs; the count is not top-5-bounded)
        assert s["holders"] == 5

    def test_valid_zero_field(self):
        # 40102 "No Search Results" is a VALID zero (lesson #2)
        s = field_stats([], "Locksmith")
        assert s["supply"] == 0 and s["rev_win"] == 0 and s["avg5"] == 0

    def test_rev_win_small_fields(self):
        one = [_serp_item("Solo", 12)]
        assert field_stats(one, "Locksmith")["rev_win"] == 12
        two = [_serp_item("A", 30), _serp_item("B", 8)]
        assert field_stats(two, "Locksmith")["rev_win"] == 8  # min(2, len-1)

    def test_holder_category_decouples_holders_from_the_searched_keyword(self):
        # a literal keyword ("key cutting") is graded on its own SERP, but the
        # exact-holder count is matched against the catalog category
        s = field_stats(self.ITEMS, "key cutting", holder_category="Locksmith")
        assert s["holders"] == 5                 # holders from the catalog category
        assert s["namekw"] == 0                  # namekw from the literal keyword
        # supply/reviews are keyword-agnostic (the SERP is the SERP)
        assert s["supply"] == 6 and s["rev_win"] == 36


class TestTryoutEconomics:
    def test_grading_and_vetoes(self):
        field = {"Locksmith": {"supply": 20, "avg5": 60.0, "rev_win": 36,
                               "rating": 4.7, "namekw": 2, "holders": 4}}
        demand = {"Locksmith": {"vol": 500, "cpc": 10.0}}
        rows = tryout_rows(demand, field, {"Locksmith": 25.0}, BREAKPOINTS, 0.10)
        r = rows[0]
        # leads=50, value=1250, rankab=.75/(1+60/50)+.25/(1+4/5)=0.48
        assert r["rankab"] == 0.48
        assert r["exp_val"] == round(1250 * 0.48)
        assert r["grade"] in ("D", "C", "B", "B+", "A", "A+")
        assert r["roi"] == round(r["exp_val"] / 36, 1)
        # no multiplier → flat CPL exposed, value unchanged (byte-identical path)
        assert r["cpl_base"] == 25.0 and r["cpl_modifier"] == 1.0 and r["cpl"] == 25.0

    def test_cpc_local_modifier_scales_cpl_and_value(self):
        field = {"Locksmith": {"supply": 20, "avg5": 60.0, "rev_win": 36,
                               "rating": 4.7, "namekw": 2, "holders": 4}}
        demand = {"Locksmith": {"vol": 500, "cpc": 45.0}}
        rows = tryout_rows(demand, field, {"Locksmith": 25.0}, BREAKPOINTS, 0.10,
                           cpl_multipliers={"Locksmith": 1.5})
        r = rows[0]
        assert r["cpl_base"] == 25.0 and r["cpl_modifier"] == 1.5
        assert r["cpl"] == 37.5                 # 25 × 1.5, effective exclusive CPL
        assert r["value_mo"] == round(50 * 37.5)  # leads × effective CPL

    def test_no_lead_value_is_f(self):
        field = {"Oddity": {"supply": 3, "avg5": 5.0, "rev_win": 4,
                            "rating": 5.0, "namekw": 0, "holders": 0}}
        rows = tryout_rows({"Oddity": {"vol": 900, "cpc": None}}, field, {},
                           BREAKPOINTS, 0.10)
        assert rows[0]["grade"] == "F"

    def test_tiny_market_capped_at_c(self):
        field = {"Locksmith": {"supply": 2, "avg5": 2.0, "rev_win": 3,
                               "rating": 5.0, "namekw": 0, "holders": 0}}
        # vol 30 × 0.10 = 3 leads → veto caps the percentile at 74.9 (≤ C)
        rows = tryout_rows({"Locksmith": {"vol": 30, "cpc": 5.0}}, field,
                           {"Locksmith": 500.0}, BREAKPOINTS, 0.10)
        assert rows[0]["grade"] in ("C", "D", "F")

    def test_sorted_by_exp_val(self):
        field = {
            "A": {"supply": 5, "avg5": 10.0, "rev_win": 10, "rating": 4, "namekw": 0, "holders": 1},
            "B": {"supply": 5, "avg5": 10.0, "rev_win": 10, "rating": 4, "namekw": 0, "holders": 1},
        }
        demand = {"A": {"vol": 100, "cpc": 1}, "B": {"vol": 1000, "cpc": 1}}
        rows = tryout_rows(demand, field, {"A": 20.0, "B": 20.0}, BREAKPOINTS, 0.10)
        assert rows[0]["category"] == "B"


def _tryout(**over):
    row = {"id": "t1", "status": "complete", "city_id": 5368304,
           "city_name": "Los Alamitos", "state_code": "CA",
           "results": [
               {"category": "Plumber", "category_id": "plumber", "grade": "B",
                "competitors": [
                    {"business_name": "ACME Plumbing", "domain": "acme.com", "phone": "1"},
                    {"business_name": "Bob Pipes", "domain": "bob.com", "phone": "2"}]},
               {"category": "Locksmith", "category_id": "locksmith", "grade": "C",
                "competitors": [{"business_name": "Lock Co", "domain": "lock.com"}]}]}
    row.update(over)
    return row


class TestTryoutScout:
    def test_result_row_lookup(self):
        assert tryout_result_row(_tryout(), "plumber")["grade"] == "B"
        assert tryout_result_row(_tryout(), "locksmith")["grade"] == "C"
        assert tryout_result_row(_tryout(), "nope") is None

    def test_complete_row_with_comps_is_scoutable(self):
        assert tryout_scoutable(_tryout(), "plumber") is None

    def test_incomplete_tryout_not_scoutable(self):
        assert tryout_scoutable(_tryout(status="running"), "plumber") == "tryout_not_ready"

    def test_unknown_category_not_scoutable(self):
        assert tryout_scoutable(_tryout(), "nope") == "category_not_found"

    def test_row_without_category_id_not_scoutable(self):
        # defensive guard: a matched row that carries no category_id can't be
        # scouted (the scanner's Pass-2 caches key on the catalog category).
        # The router requires a non-empty category_id, so this is belt-and-braces.
        row = _tryout(results=[{"category": "X", "category_id": None,
                                "competitors": [{"business_name": "Y"}]}])
        assert tryout_scoutable(row, "") == "scout_requires_catalog"

    def test_no_competitors_not_scoutable(self):
        row = _tryout(results=[{"category": "Plumber", "category_id": "plumber",
                                "competitors": []}])
        assert tryout_scoutable(row, "plumber") == "no_competitors"

    def test_market_comps_shape(self):
        row = _tryout()
        market, comps = tryout_market_comps(row, tryout_result_row(row, "plumber"))
        # a tryout category IS a scanned catalog category, so its NAME keys the
        # scanner's Pass-2 caches directly (unlike a grade's literal keyword).
        assert market == {"city_id": 5368304, "category_id": "plumber",
                          "category": "Plumber", "city_name": "Los Alamitos",
                          "state_code": "CA"}
        assert [c["rank_position"] for c in comps] == [1, 2]
        assert comps[0]["business_name"] == "ACME Plumbing"
        assert comps[0]["domain"] == "acme.com"

    def test_market_comps_empty_competitors(self):
        row = _tryout(results=[{"category": "Plumber", "category_id": "plumber",
                                "competitors": []}])
        _market, comps = tryout_market_comps(row, tryout_result_row(row, "plumber"))
        assert comps == []


class TestScoutContracts:
    def test_velocity_row_contract(self):
        # EXACT enrich_shortlist semantics: last30/prior30 buckets, newest
        # date string, capped = 30 items that don't even span 60 days.
        ts = [NOW - timedelta(days=d) for d in (1, 5, 29, 31, 45, 59)]
        row = velocity_row(ts, "locksmith plus inc|5814616", item_count=6, now=NOW)
        assert row["biz_key"] == "locksmith plus inc|5814616"
        assert row["last30"] == 3 and row["prior30"] == 3
        assert row["newest"] == (NOW - timedelta(days=1)).date().isoformat()
        assert row["capped"] is False
        assert row["pulled_at"] == NOW.isoformat()

    def test_velocity_capped_when_window_saturated(self):
        ts = [NOW - timedelta(days=d) for d in range(1, 31)]  # 30 in 30 days
        row = velocity_row(ts, "k|1", item_count=30, now=NOW)
        assert row["capped"] is True

    def test_trend_row_contract(self):
        monthly = [{"month": m, "search_volume": v} for m, v in
                   [(6, 900), (5, 800), (4, 700), (3, 300), (2, 300),
                    (1, 300), (12, 300), (11, 300), (10, 300), (9, 300),
                    (8, 300), (7, 300)]]
        row = trend_row(monthly, "5814616|locksmith", NOW)
        assert row["trend_key"] == "5814616|locksmith"
        assert row["growth_yoy"] == round((900 + 800 + 700) / 3 / 300, 2)
        assert row["peak_months"] == "6,5"
        assert row["pulled_at"] == NOW.isoformat()

    def test_trend_refuses_thin_history(self):
        monthly = [{"month": m, "search_volume": 100} for m in range(1, 5)]
        row = trend_row(monthly, "k", NOW)
        assert row["growth_yoy"] is None and row["peak_months"] is None

    def test_pick_monthly_longest_series_wins(self):
        items = [
            {"keyword": "locksmith", "monthly_searches": [{"month": 1, "search_volume": 10}]},
            {"keyword": "locksmith near me", "monthly_searches": [
                {"month": 1, "search_volume": 20}, {"month": 2, "search_volume": 30}]},
        ]
        m = pick_monthly(items)
        assert len(m["locksmith"]) == 2  # near-me stripped, longer series kept


def _seasonal_24(growth=1.0):
    """24 months of a roofing-shaped seasonal curve (summer peak, winter
    trough), newest = FEBRUARY 2026 — the window position that produces the
    lesson-#8 artifact (recent 3 = winter trough, window-oldest 3 = spring
    ramp → legacy growth reads ~0.3 on a flat market, the roofing-0.21 shape).
    `growth` multiplies the most recent 12 months (Mar 2025–Feb 2026)."""
    base = {1: 200, 2: 220, 3: 400, 4: 700, 5: 950, 6: 1000, 7: 980, 8: 900,
            9: 700, 10: 500, 11: 300, 12: 220}
    out = []
    for back in range(24):  # newest-first from 2026-02
        total = 2026 * 12 + 1 - back  # month index of (2026, February)
        y, m = total // 12, total % 12 + 1
        recent_year = y == 2026 or (y == 2025 and m > 2)
        out.append({"year": y, "month": m,
                    "search_volume": round(base[m] * (growth if recent_year else 1.0))})
    return out


class TestSameMonthGrowth:
    def test_pure_seasonality_collapses_to_one(self):
        # The lesson-#8 artifact: identical seasonal years. The legacy 12-mo
        # calc reads a big "trend" (Apr–Jun vs Jul–Sep of the window); the
        # same-month calc reads exactly 1.0.
        ms = _seasonal_24()
        legacy = trend_row(ms, "k", NOW)["growth_yoy"]
        assert legacy is not None and abs(legacy - 1.0) > 0.25  # confounded
        assert same_month_growth(ms) == 1.0                     # cancelled

    def test_real_trend_survives(self):
        # A genuine +30% year multiplies every recent month; same-month reads it.
        ms = _seasonal_24(growth=1.3)
        assert same_month_growth(ms) == 1.3

    def test_refuses_short_history(self):
        # only 14 months — the 3rd prior-year month is missing → refuse, never
        # partially match (that would reintroduce the confound)
        ms = _seasonal_24()[:14]
        assert same_month_growth(ms) is None

    def test_refuses_missing_years(self):
        ms = [{"month": m, "search_volume": 100} for m in range(1, 13)] * 2
        assert same_month_growth(ms) is None

    def test_zero_prior_year_refuses(self):
        ms = _seasonal_24()
        for row in ms[12:]:
            row["search_volume"] = 0
        assert same_month_growth(ms) is None

    def test_trend_row_carries_both_fields(self):
        ms = _seasonal_24()
        row = trend_row(ms, "5814616|roofing contractor", NOW)
        assert row["growth_yoy_ss"] == 1.0
        assert row["growth_yoy"] is not None  # legacy semantics untouched
        assert row["peak_months"]  # still from the recent 12

    def test_trend_row_12mo_data_leaves_ss_null(self):
        # a 12-month pull (old tool, old cadence) → ss stays null, legacy works
        ms = _seasonal_24()[:12]
        row = trend_row(ms, "k", NOW)
        assert row["growth_yoy_ss"] is None and row["growth_yoy"] is not None

    def test_trend_date_from_is_24_months_back(self):
        from datetime import datetime, timezone
        assert trend_date_from(datetime(2026, 7, 12, tzinfo=timezone.utc)) == "2024-07-01"
        assert trend_date_from(datetime(2026, 1, 3, tzinfo=timezone.utc)) == "2024-01-01"


def test_base_url_carries_api_version():
    # The scanner scripts' endpoint paths are relative to a client that
    # prefixes /v3 — the port must too (a bare host 404s on the first call).
    from services.leadoff_actions import _BASE_URL
    assert _BASE_URL.endswith("/v3")


class TestBudget:
    def test_scout_estimate_math(self):
        assert scout_estimate(5, 5, True) == round(5 * 0.005 + 5 * 0.0023 + 0.05, 2)
        assert scout_estimate(0, 0, False) == 0.0

    def test_spent_today_sums_ledger(self):
        rows = [{"est_cost": 0.20}, {"est_cost": "0.05"}, {"est_cost": None}]
        assert spent_today(rows) == 0.25
