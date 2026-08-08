"""The organic-SERP capture's pure layer.

Like the `tasks_ready` tests in test_maps_scan.py, these assert BEHAVIOUR on an envelope this
codebase has not yet called against this account (the organic live endpoint is measured on the
first real run — organic_scan.py's docstring). They cannot prove the shape is right; what they pin
is the response to a shape we DO recognise (parse it), and the response to a task-level error
(RAISE, never return an empty SERP — an outage must not read as "nobody ranks"). The request
builder and the domain normaliser are fully determined and tested outright.
"""
import pytest

from api.services.organic_scan import (
    OrganicScanError,
    build_organic_task,
    domain_of,
    parse_organic_serp,
    summarize_paid,
    summarize_serp,
)


# --- build_organic_task -----------------------------------------------------------------------


def test_build_organic_task_anchors_to_the_coordinate():
    task = build_organic_task(
        "plumber", 34.18, -118.44, depth=20, language_code="en", device="desktop"
    )
    assert task == {
        "keyword": "plumber",
        "location_coordinate": "34.18,-118.44",
        "language_code": "en",
        "device": "desktop",
        "depth": 20,
    }


# --- domain_of --------------------------------------------------------------------------------


def test_domain_of_normalises_the_same_way_both_sides_will():
    assert domain_of("https://www.AcePlumbing.com/services") == "aceplumbing.com"
    assert domain_of("http://boltrooter.com") == "boltrooter.com"
    assert domain_of("ac-drains.com") == "ac-drains.com"          # bare host, no scheme
    assert domain_of("https://user@host.com:8080/x") == "host.com"
    assert domain_of("") is None
    assert domain_of(None) is None


# --- parse_organic_serp -----------------------------------------------------------------------


def _serp_body(items):
    return {"tasks": [{"status_code": 20000,
                       "result": [{"se_results_count": 12345, "items": items}]}]}


def test_parse_organic_serp_reads_organic_items_and_detects_ai_overview():
    body = _serp_body([
        {"type": "ai_overview"},
        {"type": "organic", "rank_absolute": 2, "domain": "ace.com", "url": "https://ace.com", "title": "Ace"},
        {"type": "organic", "rank_absolute": 1, "domain": "bolt.com", "url": "https://bolt.com", "title": "Bolt"},
        {"type": "people_also_ask"},  # ignored
        {"type": "organic", "domain": "nope.com"},  # no rank -> skipped
    ])
    serp = parse_organic_serp(body)
    assert serp.ai_overview_present is True
    assert serp.total_count == 12345
    # Sorted by rank; the rankless organic item is dropped, not guessed at.
    assert [(r.rank, r.domain) for r in serp.results] == [(1, "bolt.com"), (2, "ace.com")]


def test_parse_organic_serp_falls_back_to_rank_group():
    body = _serp_body([{"type": "organic", "rank_group": 3, "domain": "x.com"}])
    serp = parse_organic_serp(body)
    assert serp.results[0].rank == 3


def test_parse_organic_serp_raises_on_task_error():
    # A task-level error must RAISE, never return an empty SERP — an outage that read as "no
    # competitors" would argue that a prospect's rivals don't exist.
    body = {"tasks": [{"status_code": 40501, "status_message": "invalid field"}]}
    with pytest.raises(OrganicScanError):
        parse_organic_serp(body)


def test_parse_organic_serp_raises_on_empty_envelope():
    with pytest.raises(OrganicScanError):
        parse_organic_serp({"tasks": []})
    with pytest.raises(OrganicScanError):
        parse_organic_serp({"tasks": [{"status_code": 20000, "result": []}]})


def test_parse_organic_serp_tolerates_missing_items():
    serp = parse_organic_serp(_serp_body(None))
    assert serp.results == [] and serp.ai_overview_present is False


# --- summarize_serp ---------------------------------------------------------------------------


def test_summarize_serp_is_json_ready():
    body = _serp_body([
        {"type": "organic", "rank_absolute": 1, "domain": "bolt.com", "url": "u", "title": "Bolt"},
    ])
    summary = summarize_serp(parse_organic_serp(body), depth=20)
    assert summary["engine"] == "google_organic"
    assert summary["captured_depth"] == 20
    assert summary["results"] == [{"rank": 1, "domain": "bolt.com", "url": "u", "title": "Bolt"}]
    # No paid items -> the block still exists, presence flags false (absence is a finding, not a gap).
    assert summary["paid"] == {
        "ads_present": False, "lsa_present": False,
        "advertisers": [], "lsa_advertisers": [], "seen_item_types": ["organic"],
    }


# --- paid placement (the fourth signal) -------------------------------------------------------


def test_parse_organic_serp_extracts_paid_ads_from_the_same_response():
    # The paid items ride the SAME response the organic parse already reads — no new call.
    body = _serp_body([
        {"type": "paid", "rank_absolute": 1, "domain": "AcePlumbing.com", "url": "https://ace.com/x", "title": "Ace — Ad"},
        {"type": "organic", "rank_absolute": 1, "domain": "bolt.com"},
        {"type": "paid", "rank_group": 2, "url": "https://boltrooter.com/lp", "title": "Bolt Ad"},  # domain from url
    ])
    serp = parse_organic_serp(body)
    assert [(p.rank, p.domain, p.title) for p in serp.paid_results] == [
        (1, "aceplumbing.com", "Ace — Ad"),
        (2, "boltrooter.com", "Bolt Ad"),   # domain recovered from the ad URL
    ]
    assert serp.seen_item_types == ("paid", "organic")


def test_parse_organic_serp_extracts_lsa_flat_and_nested():
    flat = _serp_body([
        {"type": "local_services", "rank_absolute": 1, "title": "Reliable Rooter"},
    ])
    assert [(l.name, l.rank) for l in parse_organic_serp(flat).lsa_results] == [("Reliable Rooter", 1)]

    nested = _serp_body([
        {"type": "local_services", "rank_absolute": 1, "items": [
            {"title": "Reliable Rooter", "rank_absolute": 1},
            {"title": "Speedy Plumbing", "rank_absolute": 2},
        ]},
    ])
    serp = parse_organic_serp(nested)
    assert [(l.name, l.rank) for l in serp.lsa_results] == [("Reliable Rooter", 1), ("Speedy Plumbing", 2)]
    assert serp.lsa_results and serp.results == []  # LSA is not an organic competitor


def test_summarize_paid_presence_and_advertisers():
    body = _serp_body([
        {"type": "paid", "rank_absolute": 1, "domain": "ace.com", "title": "Ace"},
        {"type": "local_services", "rank_absolute": 1, "items": [{"title": "Reliable Rooter"}]},
    ])
    paid = summarize_paid(parse_organic_serp(body))
    assert paid["ads_present"] is True
    assert paid["lsa_present"] is True
    assert paid["advertisers"] == [{"domain": "ace.com", "rank": 1, "title": "Ace"}]
    assert paid["lsa_advertisers"] == [{"name": "Reliable Rooter", "rank": 1}]
    assert "local_services" in paid["seen_item_types"]


def test_summarize_paid_absent_is_a_finding_not_a_gap():
    paid = summarize_paid(parse_organic_serp(_serp_body([{"type": "organic", "rank_absolute": 1, "domain": "x.com"}])))
    assert paid == {
        "ads_present": False, "lsa_present": False,
        "advertisers": [], "lsa_advertisers": [], "seen_item_types": ["organic"],
    }
