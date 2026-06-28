"""Unit tests for the Competitive SERP Snapshot pure parse helpers.

No network: only the I/O-free extractors/classifiers are exercised.
"""

from __future__ import annotations

from services import serp_snapshot


# ---------------------------------------------------------------------------
# extract_organic_results
# ---------------------------------------------------------------------------
def test_extract_organic_results_top_n_and_fields():
    items = [
        {"type": "ai_overview"},
        {"type": "organic", "rank_absolute": 1, "url": "https://a.com/p", "domain": "a.com",
         "title": "A Title", "description": "A desc"},
        {"type": "people_also_ask"},
        {"type": "organic", "rank_absolute": 2, "url": "https://b.com/p", "domain": "B.com",
         "title": "B Title", "description": "B desc"},
        {"type": "organic", "rank_absolute": 3, "url": "https://c.com", "domain": "c.com"},
    ]
    out = serp_snapshot.extract_organic_results(items, top_n=2)
    assert len(out) == 2
    assert out[0] == {
        "position": 1, "url": "https://a.com/p", "domain": "a.com",
        "title": "A Title", "description": "A desc",
    }
    assert out[1]["domain"] == "b.com"  # lowercased


# ---------------------------------------------------------------------------
# find_client_organic
# ---------------------------------------------------------------------------
def test_find_client_organic_matches_subdomain_and_www():
    items = [
        {"type": "organic", "rank_absolute": 1, "url": "https://comp.com", "domain": "comp.com"},
        {"type": "organic", "rank_absolute": 7, "url": "https://www.acme.com/x", "domain": "www.acme.com",
         "title": "Acme", "description": "d"},
    ]
    match = serp_snapshot.find_client_organic(items, "acme.com")
    assert match["position"] == 7
    assert match["url"] == "https://www.acme.com/x"


def test_find_client_organic_none_when_absent():
    items = [{"type": "organic", "rank_absolute": 1, "url": "https://comp.com", "domain": "comp.com"}]
    assert serp_snapshot.find_client_organic(items, "acme.com") is None
    assert serp_snapshot.find_client_organic(items, "") is None


# ---------------------------------------------------------------------------
# extract_aio
# ---------------------------------------------------------------------------
def test_extract_aio_present_with_sources_and_text():
    items = [
        {
            "type": "ai_overview",
            "references": [
                {"url": "https://a.com", "domain": "a.com", "title": "A"},
            ],
            "items": [
                {"text": "First para", "references": [
                    {"url": "https://b.com", "domain": "b.com", "title": "B"},
                    {"url": "https://a.com", "domain": "a.com", "title": "A"},  # dup url
                ]},
                {"text": "Second para"},
            ],
        }
    ]
    aio = serp_snapshot.extract_aio(items)
    assert aio["present"] is True
    assert aio["text"] == "First para\n\nSecond para"
    assert [s["url"] for s in aio["sources"]] == ["https://a.com", "https://b.com"]  # deduped


def test_extract_aio_absent():
    aio = serp_snapshot.extract_aio([{"type": "organic"}])
    assert aio == {"present": False, "text": None, "sources": []}


# ---------------------------------------------------------------------------
# extract_serp_features
# ---------------------------------------------------------------------------
def test_extract_serp_features_inventory_and_detail():
    items = [
        {"type": "organic", "rank_absolute": 1},
        {"type": "local_pack", "title": "Joe's Plumbing", "domain": "joes.com",
         "rating": {"value": 4.7}},
        {"type": "people_also_ask", "items": [
            {"title": "How much does X cost?"}, {"title": "Is X safe?"}]},
        {"type": "discussions_and_forums", "items": [
            {"title": "Reddit thread", "url": "https://reddit.com/x", "domain": "reddit.com"}]},
        {"type": "featured_snippet", "title": "Snippet", "url": "https://s.com", "domain": "s.com"},
        {"type": "local_pack", "title": "Second", "domain": "two.com", "rating": 4.1},
    ]
    f = serp_snapshot.extract_serp_features(items)
    assert "organic" not in f["feature_types"]
    assert f["feature_types"] == [
        "local_pack", "people_also_ask", "discussions_and_forums", "featured_snippet",
    ]
    assert len(f["local_pack"]) == 2
    assert f["local_pack"][0] == {"title": "Joe's Plumbing", "domain": "joes.com", "rating": 4.7}
    assert f["local_pack"][1]["rating"] == 4.1  # non-dict rating passthrough
    assert f["people_also_ask"] == ["How much does X cost?", "Is X safe?"]
    assert f["discussions_and_forums"][0]["domain"] == "reddit.com"
    assert f["featured_snippet"] == {"title": "Snippet", "url": "https://s.com", "domain": "s.com"}


# ---------------------------------------------------------------------------
# classify_intent
# ---------------------------------------------------------------------------
def test_classify_intent_primary_and_secondary():
    result_items = [
        {
            "keyword_intent": {"label": "commercial", "probability": 0.8},
            "secondary_keyword_intents": [
                {"label": "informational", "probability": 0.15},
                {"label": "transactional", "probability": 0.05},
            ],
        }
    ]
    label, probs = serp_snapshot.classify_intent(result_items)
    assert label == "commercial"
    assert probs == {"commercial": 0.8, "informational": 0.15, "transactional": 0.05}


def test_classify_intent_empty():
    assert serp_snapshot.classify_intent([]) == (None, {})


# ---------------------------------------------------------------------------
# parse_backlinks_summary
# ---------------------------------------------------------------------------
def test_parse_backlinks_summary_maps_rank_to_url_rating():
    body = {
        "tasks": [
            {"status_code": 20000, "result": [
                {"referring_domains": 87, "rank": 412, "backlinks": 1043}]}
        ]
    }
    out = serp_snapshot.parse_backlinks_summary(body)
    assert out == {"referring_domains": 87, "url_rating": 412, "backlinks": 1043}


def test_parse_backlinks_summary_raises_on_error():
    body = {"tasks": [{"status_code": 40400, "status_message": "nope", "result": None}]}
    try:
        serp_snapshot.parse_backlinks_summary(body)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "dataforseo_backlinks_error" in str(exc)


# ---------------------------------------------------------------------------
# collect_snapshot_domains
# ---------------------------------------------------------------------------
def test_collect_snapshot_domains_dedupes_and_flags_client():
    rows = [
        {"domain": "comp.com", "is_client": False},
        {"domain": "Comp.com", "is_client": False},   # case-insensitive dup
        {"domain": "acme.com", "is_client": True},
        {"domain": "other.com", "is_client": False},
    ]
    out = serp_snapshot.collect_snapshot_domains(rows, "acme.com")
    assert [d["domain"] for d in out] == ["comp.com", "acme.com", "other.com"]
    assert [d["is_client"] for d in out] == [False, True, False]


def test_collect_snapshot_domains_appends_client_when_absent():
    # Client doesn't rank in the captured pages — its domain is still appended
    # last so it always gets a DR row.
    rows = [{"domain": "comp.com"}, {"domain": "other.com"}]
    out = serp_snapshot.collect_snapshot_domains(rows, "acme.com")
    assert [d["domain"] for d in out] == ["comp.com", "other.com", "acme.com"]
    assert out[-1] == {"domain": "acme.com", "is_client": True}


def test_collect_snapshot_domains_skips_empty_and_no_client_domain():
    rows = [{"domain": None}, {"domain": ""}, {"domain": "comp.com"}]
    out = serp_snapshot.collect_snapshot_domains(rows, "")
    assert [d["domain"] for d in out] == ["comp.com"]
    assert out[0]["is_client"] is False
