"""Unit tests for services.brand_insights pure helpers (no network)."""

from __future__ import annotations

import asyncio

from services import brand_insights as bi


def test_parse_keyword_list_plain_json():
    out = bi._parse_keyword_list('["a", "b", "c"]')
    assert out == ["a", "b", "c"]


def test_parse_keyword_list_tolerates_fences_and_prose():
    text = 'Here are the keywords:\n```json\n["plumber near me", "Acme reviews"]\n```'
    assert bi._parse_keyword_list(text) == ["plumber near me", "Acme reviews"]


def test_parse_keyword_list_caps_at_five_and_drops_blanks():
    out = bi._parse_keyword_list('["a","b","c","d","e","f"]')
    assert out == ["a", "b", "c", "d", "e"]
    assert bi._parse_keyword_list('["x", "", "  "]') == ["x"]


def test_parse_keyword_list_bad_input_returns_empty():
    assert bi._parse_keyword_list("not json at all") == []
    assert bi._parse_keyword_list("") == []


def test_prompts_include_context():
    d = bi._diagnosis_prompt("Acme", "burst pipe sydney", "Joe Pipes, Bob Drains")
    assert "Acme" in d and "burst pipe sydney" in d and "Joe Pipes" in d
    s = bi._suggest_prompt("Acme", ["Plumber"], "123 St, Sydney")
    assert "Acme" in s and "Plumber" in s and "123 St, Sydney" in s


# ── "near me" is never suggested ──────────────────────────────────────────────
def test_drop_near_me_filters_variants():
    items = [
        "plumber near me",       # canonical
        "plumber near-me",       # hyphen
        "plumber nearme",        # no space
        "PLUMBER NEAR ME now",   # casing + trailing words
        "emergency plumber Sydney",  # keep
        "nearest plumber",       # keep — "nearest" is not "near me"
        "plumbers near Mexico",  # keep — different word after "near"
    ]
    assert bi._drop_near_me(items) == [
        "emergency plumber Sydney", "nearest plumber", "plumbers near Mexico",
    ]


def test_suggest_prompt_forbids_near_me():
    s = bi._suggest_prompt("Acme", ["Plumber"], "123 St, Sydney")
    assert 'Never use the phrase "near me"' in s
    assert "plumber near me" not in s.lower()  # the old example is gone


def test_conversational_prompt_forbids_near_me():
    p = bi._conversational_prompt("Acme", "Acme (Plumber) — Sydney", "", ["plumber near me"])
    assert 'Never use the phrase "near me"' in p


# ── conversational-query suggestions ──────────────────────────────────────────
def test_parse_string_list_respects_cap():
    assert bi._parse_string_list('["a","b","c"]', cap=2) == ["a", "b"]
    assert bi._parse_string_list('["x", "", "  ", "y"]', cap=10) == ["x", "y"]
    assert bi._parse_string_list("not json", cap=5) == []


def test_conversational_prompt_includes_seeds_and_icp():
    p = bi._conversational_prompt(
        "Acme Plumbing", "Acme Plumbing (Plumber) — Sydney",
        "Homeowners with an urgent leak who value fast, insured tradies.",
        ["emergency plumber sydney", "blocked drain inner west"],
    )
    assert "emergency plumber sydney" in p and "blocked drain inner west" in p
    assert "Homeowners with an urgent leak" in p
    assert "Acme Plumbing (Plumber) — Sydney" in p
    assert "3-5 conversational queries per seed keyword" in p


def test_conversational_prompt_notes_missing_icp():
    p = bi._conversational_prompt("Acme", "Acme (Roofer)", "", ["roof repair sydney"])
    assert "No explicit ICP is on file" in p


def test_conversational_prompt_constrains_length_and_single_thought():
    p = bi._conversational_prompt("Acme", "Acme (Plumber) — Sydney", "", ["plumber sydney"])
    assert "8-14 words" in p
    assert "One thought per query" in p


def test_suggest_conversational_queries_empty_when_no_seeds():
    assert asyncio.run(bi.suggest_conversational_queries("Acme", "ctx", "icp", [])) == []


# ── real client signals → prompt block ────────────────────────────────────────
def test_format_signals_block_empty_when_no_signals():
    assert bi.format_signals_block({}) == ""


def test_format_signals_block_renders_gbp_strength():
    block = bi.format_signals_block({"gbp": {
        "rating": 4.6, "review_count": 38, "primary_category": "Roofer",
        "categories": ["Roofer", "Roofing contractor"], "has_website": True, "has_description": False,
    }})
    assert "Google Business Profile" in block
    assert "4.6★ from 38 reviews" in block
    assert 'primary category "Roofer"' in block
    assert "Roofing contractor" in block  # secondary category, not duplicated as primary
    assert "no description on the profile" in block


def test_format_signals_block_renders_competitor_authority_and_rank():
    block = bi.format_signals_block({"serp": {
        "captured_at": "2026-06-22T00:00:00Z", "client_rank": 14, "client_domain_rating": 90,
        "competitors": [
            {"domain": "big.com", "dr": 410, "referring_domains": 5000},
            {"domain": "mid.com", "dr": 300, "referring_domains": None},
        ],
    }})
    assert "ranks #14 organically" in block
    assert "domain rating is 90" in block
    assert "big.com DR 410/5000 ref. domains" in block
    assert "mid.com DR 300" in block


def test_format_signals_block_notes_client_not_ranking():
    block = bi.format_signals_block({"serp": {
        "client_rank": None, "client_domain_rating": None, "competitors": [],
    }})
    assert "does NOT rank in the captured top results" in block


# ── gather_client_signals (assembly over a fake Supabase) ─────────────────────
class _FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def ilike(self, *a, **k): return self
    def neq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self):
        return type("R", (), {"data": self._data})()


class _FakeSupabase:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))


def test_gather_client_signals_assembles_gbp_and_serp(monkeypatch):
    tables = {
        "clients": [{"gbp": {
            "gbp_rating": 4.6, "gbp_review_count": 38, "gbp_category": "Roofer",
            "gbp_categories": ["Roofer", "Roofing contractor"],
            "website": "x.com", "description": "We roof.",
        }}],
        "serp_snapshots": [{"id": "s1", "captured_at": "2026-06-22T00:00:00Z",
                            "client_rank": 14, "status": "complete"}],
        "serp_snapshot_domains": [
            {"domain": "client.com", "is_client": True, "domain_rating": 90, "referring_domains": 100},
            {"domain": "mid.com", "is_client": False, "domain_rating": 300, "referring_domains": 200},
            {"domain": "big.com", "is_client": False, "domain_rating": 410, "referring_domains": 5000},
            {"domain": "nodr.com", "is_client": False, "domain_rating": None, "referring_domains": 5},
        ],
    }
    monkeypatch.setattr("db.supabase_client.get_supabase", lambda: _FakeSupabase(tables))
    sig = bi.gather_client_signals("c1", "roof repair")
    assert sig["gbp"]["rating"] == 4.6 and sig["gbp"]["review_count"] == 38
    assert sig["serp"]["client_rank"] == 14 and sig["serp"]["client_domain_rating"] == 90
    # Competitors sorted by DR desc; the DR-less domain is dropped.
    assert [c["domain"] for c in sig["serp"]["competitors"]] == ["big.com", "mid.com"]


def test_gather_client_signals_best_effort_when_empty(monkeypatch):
    monkeypatch.setattr("db.supabase_client.get_supabase", lambda: _FakeSupabase({}))
    assert bi.gather_client_signals("c1", "kw") == {}


def test_gather_client_signals_includes_gsc_when_property_verified(monkeypatch):
    tables = {
        "gsc_properties": [{"id": "p1"}],
        "gsc_query_daily": [
            {"clicks": 3, "impressions": 100, "position": 8.0},
            {"clicks": 1, "impressions": 100, "position": 12.0},
            {"clicks": 0, "impressions": 0, "position": None},  # no-impression day
        ],
    }
    monkeypatch.setattr("db.supabase_client.get_supabase", lambda: _FakeSupabase(tables))
    sig = bi.gather_client_signals("c1", "roof repair")
    assert sig["gsc"]["clicks"] == 4 and sig["gsc"]["impressions"] == 200
    assert sig["gsc"]["avg_position"] == 10.0  # impression-weighted (8*100 + 12*100)/200
    assert sig["gsc"]["window_days"] == 28


def test_format_signals_block_renders_gsc_performance():
    block = bi.format_signals_block({"gsc": {
        "window_days": 28, "clicks": 4, "impressions": 1200, "avg_position": 9.4,
    }})
    assert "Google Search performance (last 28 days, this exact query)" in block
    assert "1,200 impressions" in block and "4 clicks" in block
    assert "average position 9.4" in block


# ── live DataForSEO fallback (when GSC is unavailable) ────────────────────────
def test_format_signals_block_renders_search_fallback():
    block = bi.format_signals_block({"search_fallback": {
        "source": "dataforseo", "rank": 8, "search_volume": 1600, "competition": "LOW",
    }})
    assert "Classic Google Search (live DataForSEO check — no GSC connected)" in block
    assert "ranks #8 organically" in block
    assert "~1,600 searches/mo, low competition" in block


def test_format_signals_block_search_fallback_not_ranking():
    block = bi.format_signals_block({"search_fallback": {"source": "dataforseo", "rank": None, "search_volume": 50}})
    assert "does NOT rank in the top organic results" in block


def test_fetch_search_fallback_none_when_dataforseo_unconfigured(monkeypatch):
    monkeypatch.setattr(bi.settings, "dataforseo_login", "")
    monkeypatch.setattr(bi.settings, "dataforseo_password", "")
    assert asyncio.run(bi.fetch_search_fallback("c1", "kw")) is None


def test_fetch_search_fallback_live_lookup_and_caches(monkeypatch):
    monkeypatch.setattr(bi.settings, "dataforseo_login", "x")
    monkeypatch.setattr(bi.settings, "dataforseo_password", "y")
    monkeypatch.setattr(
        "db.supabase_client.get_supabase",
        lambda: _FakeSupabase({"clients": [{"website_url": "https://acme.com", "gbp": {}, "rank_tracking_location_code": 2840}]}),
    )
    calls = {"rank": 0, "market": 0}

    async def fake_rank(keyword, domain, location_code):
        calls["rank"] += 1
        assert domain == "acme.com" and location_code == 2840
        return 8

    async def fake_market(keywords, location_code):
        calls["market"] += 1
        return {keywords[0].lower(): {"search_volume": 1600, "competition": "LOW"}}

    monkeypatch.setattr("services.dataforseo_rank.fetch_serp_rank", fake_rank)
    monkeypatch.setattr("services.keyword_market.fetch_cached_market", lambda *a, **k: {})
    monkeypatch.setattr("services.keyword_market.fetch_market", fake_market)

    kw = "fallback-unique-kw-xyz"
    out = asyncio.run(bi.fetch_search_fallback("client-cache-test", kw))
    assert out == {"source": "dataforseo", "rank": 8, "search_volume": 1600, "competition": "LOW"}
    # Second call for the same (client, keyword, location) is served from the memo.
    out2 = asyncio.run(bi.fetch_search_fallback("client-cache-test", kw))
    assert out2 == out
    assert calls["rank"] == 1 and calls["market"] == 1


def test_build_signals_block_prefers_gsc_over_fallback(monkeypatch):
    monkeypatch.setattr(bi, "gather_client_signals", lambda cid, kw: {"gsc": {"window_days": 28, "clicks": 1, "impressions": 9}})
    called = {"fb": False}

    async def fb(cid, kw):
        called["fb"] = True
        return {"rank": 1}

    monkeypatch.setattr(bi, "fetch_search_fallback", fb)
    block = asyncio.run(bi.build_signals_block("c1", "kw"))
    assert "Google Search performance" in block
    assert called["fb"] is False  # GSC present → no paid fallback


def test_build_signals_block_uses_fallback_when_no_gsc_or_snapshot(monkeypatch):
    monkeypatch.setattr(bi, "gather_client_signals", lambda cid, kw: {})

    async def fb(cid, kw):
        return {"source": "dataforseo", "rank": 5, "search_volume": 200}

    monkeypatch.setattr(bi, "fetch_search_fallback", fb)
    block = asyncio.run(bi.build_signals_block("c1", "kw"))
    assert "live DataForSEO check" in block and "ranks #5 organically" in block


def test_diagnosis_prompt_injects_signals_and_demands_grounding():
    block = "- Google Business Profile: 4.6★ from 38 reviews."
    d = bi._diagnosis_prompt("Acme", "roof repair", "Comp A, Comp B", block)
    assert block in d
    assert "REAL DATA" in d
    assert "real metrics provided" in d  # the grounded closing instruction
    # Without a block, the prompt keeps its original generic wording.
    plain = bi._diagnosis_prompt("Acme", "roof repair", "Comp A, Comp B")
    assert "REAL DATA" not in plain
