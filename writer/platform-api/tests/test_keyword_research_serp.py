"""Unit tests for the Keyword Research SERP-enrichment pure aggregation logic."""

from services import keyword_research_serp as krs


# --- dedupe_paa ---------------------------------------------------------------
def test_dedupe_paa_orders_and_dedupes_case_insensitively():
    out = krs.dedupe_paa([
        ["How much does a plumber cost?", "  what is a  french drain "],
        ["how much does a plumber cost?", "Do I need a permit"],
    ])
    assert out == ["How much does a plumber cost?", "what is a french drain", "Do I need a permit"]


def test_dedupe_paa_caps():
    out = krs.dedupe_paa([[f"q{i}" for i in range(10)]], cap=3)
    assert out == ["q0", "q1", "q2"]


# --- aggregate_competitors ----------------------------------------------------
def _organic(seed, *rows):
    return {"seed": seed, "organic": [
        {"position": p, "url": u, "domain": d, "title": t, "description": None}
        for (p, u, d, t) in rows
    ]}


def test_aggregate_competitors_ranks_by_presence_then_position():
    per_seed = [
        _organic("emergency plumber",
                 (1, "https://a.com/x", "a.com", "A"),
                 (2, "https://b.com/y", "b.com", "B")),
        _organic("blocked drain",
                 (3, "https://a.com/z", "a.com", "A2"),
                 (1, "https://c.com/w", "www.c.com", "C")),
    ]
    out = krs.aggregate_competitors(per_seed, client_domain="c.com",
                                    aio_domains={"a.com"}, top_n=10)
    # a.com appears twice → first; then b.com and c.com each once, c.com better pos.
    assert out[0]["domain"] == "a.com"
    assert out[0]["appearances"] == 2
    assert out[0]["best_position"] == 1
    assert out[0]["aio_cited"] is True
    assert set(out[0]["seeds"]) == {"emergency plumber", "blocked drain"}
    # www. stripped + client flagged.
    client = next(r for r in out if r["domain"] == "c.com")
    assert client["is_client"] is True
    # Single-appearance tie broken by best position: c.com (1) before b.com (2).
    singles = [r["domain"] for r in out if r["appearances"] == 1]
    assert singles.index("c.com") < singles.index("b.com")


def test_aggregate_competitors_top_n():
    per_seed = [_organic("s", *[(i + 1, f"https://d{i}.com", f"d{i}.com", "T") for i in range(15)])]
    assert len(krs.aggregate_competitors(per_seed, top_n=5)) == 5


# --- aggregate_aio ------------------------------------------------------------
def test_aggregate_aio_counts_presence_and_ranks_sources():
    per_seed = [
        {"seed": "a", "present": True, "sources": [
            {"url": "https://x.com/1", "domain": "x.com", "title": "X"},
            {"url": "https://y.com/1", "domain": "y.com", "title": "Y"}]},
        {"seed": "b", "present": False, "sources": [
            {"url": "https://x.com/2", "domain": "www.x.com", "title": "X2"}]},
    ]
    out = krs.aggregate_aio(per_seed)
    assert out["seeds_with_aio"] == 1
    assert out["seeds_analyzed"] == 2
    assert out["sources"][0]["domain"] == "x.com"   # cited by both → ranked first
    assert out["sources"][0]["count"] == 2


# --- build_serp_intel ---------------------------------------------------------
def test_build_serp_intel_assembles_blob():
    intel = krs.build_serp_intel(
        ["emergency plumber"],
        [_organic("emergency plumber", (1, "https://a.com", "a.com", "A"))],
        [{"seed": "emergency plumber", "present": True,
          "sources": [{"url": "https://a.com", "domain": "a.com", "title": "A"}]}],
        [["how much does a plumber cost?"]],
        client_domain="mysite.com",
    )
    assert intel["enabled"] is True
    assert intel["seeds_analyzed"] == ["emergency plumber"]
    assert intel["competitors"][0]["domain"] == "a.com"
    assert intel["competitors"][0]["aio_cited"] is True   # a.com is an AIO source
    assert intel["aio"]["seeds_with_aio"] == 1
    assert intel["paa"] == ["how much does a plumber cost?"]
