"""Unit tests for the LeadOff city-finder pure helpers (no network/DB)."""
from services.leadoff_finder import (
    add_opportunity,
    estimate_finder_cost,
    resolve_category,
    _tokens,
)

CATS = ["Tree service", "Arborist and tree surgeon", "Plumber", "Locksmith",
        "Roofing contractor", "Computer repair service", "Electrician"]


class TestResolveCategory:
    def test_exact_normalized_match(self):
        assert resolve_category("tree service", CATS) == "Tree service"
        assert resolve_category("Tree Service", CATS) == "Tree service"

    def test_token_overlap_match(self):
        assert resolve_category("computer support and services", CATS) == \
            "Computer repair service"   # shares 'comput' stem
        # light stemming collapses verb/noun trade forms
        assert resolve_category("roofer", CATS) == "Roofing contractor"
        assert resolve_category("roofing", CATS) == "Roofing contractor"
        assert resolve_category("plumbing", CATS) == "Plumber"

    def test_no_match_returns_none(self):
        assert resolve_category("underwater basket weaving", CATS) is None
        assert resolve_category("", CATS) is None
        assert resolve_category("services", CATS) is None  # only a stopword

    def test_prefers_tightest_match(self):
        # "tree" appears in both Tree service and Arborist and tree surgeon;
        # "tree service" should resolve to the tighter "Tree service"
        assert resolve_category("tree service", CATS) == "Tree service"


class TestCostAndTokens:
    def test_estimate(self):
        assert estimate_finder_cost(120) == 7.2
        assert estimate_finder_cost(0) == 0.0

    def test_opportunity_surfaces_the_gem_not_the_metro(self):
        # a huge contested metro (top demand, strong field → low winnability)
        # vs a mid-size market with real demand and a weak field. The gem — not
        # the metro — must top the ranking (the Moneyball point), and the
        # unwinnable metro must rank below it despite its size.
        rows = [
            {"city_name": "Metro", "vol": 5000, "rankab": 0.10, "exp_val": 9000},
            {"city_name": "Gem", "vol": 900, "rankab": 0.80, "exp_val": 1200},
            {"city_name": "Tiny", "vol": 30, "rankab": 0.95, "exp_val": 60},
        ]
        out = add_opportunity(rows)
        rank = {r["city_name"]: i for i, r in enumerate(out)}
        assert out[0]["city_name"] == "Gem"          # the pick
        assert rank["Gem"] < rank["Metro"]           # gem beats the big metro
        assert all("opportunity" in r for r in out)
        assert out[0]["opportunity"] > out[rank["Metro"]]["opportunity"]

    def test_tokens_drop_stopwords_and_stem(self):
        assert _tokens("Computer support and services") == {"comput", "support"}
        assert _tokens("the a for") == set()
        assert _tokens("Plumbing") == _tokens("Plumber")  # stem collapses
