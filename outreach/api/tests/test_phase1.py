"""Phase 1 unit tests — filter matrix, dedup, cost gate, parser aliases.

No golden fixtures here: tests/fixtures/golden-fixtures.json covers scorecard arithmetic, which
is Phase 4. Nothing in Phase 1 writes a score.

External calls are never made — the Outscraper client is exercised through a stub transport.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.services import cost  # noqa: E402
from api.services.filters import (  # noqa: E402
    NOT_EVALUATED,
    RULE_BUSINESS_STATUS,
    RULE_HAS_PHONE,
    RULE_NOT_FRANCHISE,
    RULE_NOT_SUPPRESSED,
    RULE_REVIEW_COUNT,
    RULE_REVIEW_RECENCY,
    SuppressionIndex,
    evaluate,
    matches_franchise_pattern,
)
from api.services.outscraper_client import TileRequest, extract_places  # noqa: E402
from api.services.parser import (  # noqa: E402
    FIELD_ALIASES,
    normalize_business_status,
    parse_place,
)
from api.services.tiling import (  # noqa: E402
    Submarket,
    build_tiles,
    dedupe_on_place_id,
    nearest_submarket,
)

TODAY = date(2026, 7, 31)

SUBMARKETS = [
    Submarket(id="sm-north", name="Overland Park", center_lat=38.9822, center_lng=-94.6708),
    Submarket(id="sm-east", name="Lee's Summit", center_lat=38.9108, center_lng=-94.3822),
]


def place(**overrides):
    raw = {
        "place_id": "ChIJ_test_1",
        "name": "Acme Plumbing",
        "phone": "+1 816-555-0100",
        "site": "https://acmeplumbing.example",
        "reviews": 42,
        "rating": 4.6,
        "business_status": "OPERATIONAL",
        "latitude": 38.98,
        "longitude": -94.67,
        "type": "Plumber",
        "full_address": "1 Main St, Overland Park, KS",
    }
    raw.update(overrides)
    return parse_place(raw)


def run(p, **kwargs):
    defaults = dict(
        suppression=SuppressionIndex(),
        franchise_patterns=["Roto-Rooter", "Mr. Rooter"],
        min_review_count=10,
        review_recency_months=9,
        today=TODAY,
    )
    defaults.update(kwargs)
    return evaluate(p, **defaults)


# --- parser -----------------------------------------------------------------------------


def test_parser_prefers_site_over_website():
    """The SDK's own example uses `site`, not `website`. Getting this backwards loses every URL."""
    parsed = parse_place({"place_id": "x", "name": "n", "site": "https://a.example"})
    assert parsed.website == "https://a.example"


def test_parser_falls_back_through_aliases():
    parsed = parse_place(
        {"place_id": "x", "name": "n", "website": "https://b.example", "reviews_count": 7}
    )
    assert parsed.website == "https://b.example"
    assert parsed.review_count == 7


def test_parser_takes_first_category_from_a_list():
    parsed = parse_place({"place_id": "x", "name": "n", "type": ["Plumber", "Contractor"]})
    assert parsed.category == "Plumber"


def test_parser_refuses_a_place_with_no_id():
    """Never fabricate a place_id — grid results join on it and an invented one matches nothing."""
    assert parse_place({"name": "No Id Plumbing"}) is None
    assert parse_place({"place_id": "x"}) is None


def test_phone_type_is_always_unknown_in_phase_1():
    assert place().phone_type == "unknown"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("OPERATIONAL", "OPERATIONAL"),
        ("closed_temporarily", "CLOSED_TEMPORARILY"),
        ("CLOSED_PERMANENTLY", "CLOSED_PERMANENTLY"),
        ("permanently_closed", "CLOSED_PERMANENTLY"),
        (True, "CLOSED_PERMANENTLY"),
        (False, "OPERATIONAL"),
        ("something_new", None),
        (None, None),
    ],
)
def test_business_status_normalisation(value, expected):
    assert normalize_business_status(value) == expected


# --- the central requirement: every rule is evaluated -----------------------------------


def test_every_rule_is_recorded_for_every_prospect():
    verdict = run(place())
    recorded = {o.rule for o in verdict.outcomes}
    assert recorded == {
        RULE_BUSINESS_STATUS,
        RULE_HAS_PHONE,
        RULE_NOT_SUPPRESSED,
        RULE_NOT_FRANCHISE,
        RULE_REVIEW_COUNT,
        RULE_REVIEW_RECENCY,
    }


def test_all_failing_rules_are_logged_not_just_the_first():
    """A dead listing typically fails three gates at once. First-match-only logging would report
    only `business_status_open` and make the other two rules look useless during tuning."""
    dead = place(business_status="CLOSED_PERMANENTLY", phone=None, reviews=2)
    verdict = run(dead)

    assert set(verdict.failed_rules) == {
        RULE_BUSINESS_STATUS,
        RULE_HAS_PHONE,
        RULE_REVIEW_COUNT,
    }
    assert verdict.excluded


# --- franchise: flag, never exclude ------------------------------------------------------


def test_franchise_match_flags_and_does_not_exclude():
    verdict = run(place(name="Roto-Rooter Plumbing & Water Cleanup"))

    assert verdict.franchise_flagged
    assert verdict.franchise_status == "flagged"
    assert RULE_NOT_FRANCHISE in verdict.failed_rules
    assert not verdict.excluded, "a franchise match must never exclude"


def test_franchise_flag_does_not_rescue_a_prospect_failing_a_hard_gate():
    verdict = run(place(name="Roto-Rooter Plumbing", phone=None))
    assert verdict.franchise_flagged
    assert verdict.excluded


def test_franchise_status_is_never_confirmed_by_a_pattern_match():
    """Confirmation is a human act. A regex may only ever produce 'flagged'."""
    assert run(place(name="Mr. Rooter of KC")).franchise_status == "flagged"
    assert run(place()).franchise_status == "unknown"


def test_franchise_pattern_match_is_case_insensitive():
    assert matches_franchise_pattern("ROTO-ROOTER KC", ["Roto-Rooter"]) == "Roto-Rooter"
    assert matches_franchise_pattern("Independent Plumbing", ["Roto-Rooter"]) is None


# --- hard gates --------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"])
def test_closed_businesses_are_excluded(status):
    verdict = run(place(business_status=status))
    assert RULE_BUSINESS_STATUS in verdict.failed_rules
    assert verdict.excluded


def test_unknown_business_status_does_not_exclude():
    """Excluding on an unrecognised status drops live businesses with no recovery path."""
    verdict = run(place(business_status="SOME_NEW_STATUS"))
    outcome = next(o for o in verdict.outcomes if o.rule == RULE_BUSINESS_STATUS)
    assert outcome.passed
    assert outcome.observed_value == NOT_EVALUATED
    assert not verdict.excluded


def test_missing_phone_excludes():
    verdict = run(place(phone=None))
    assert RULE_HAS_PHONE in verdict.failed_rules
    assert verdict.excluded


def test_review_count_below_threshold_excludes():
    verdict = run(place(reviews=9))
    assert RULE_REVIEW_COUNT in verdict.failed_rules
    assert verdict.excluded

    assert not run(place(reviews=10)).excluded


def test_absent_review_count_is_not_treated_as_a_low_count():
    parsed = parse_place({"place_id": "x", "name": "n", "phone": "555"})
    outcome = next(o for o in run(parsed).outcomes if o.rule == RULE_REVIEW_COUNT)
    assert outcome.passed
    assert outcome.observed_value == NOT_EVALUATED


# --- suppression -------------------------------------------------------------------------


def test_suppression_check_tolerates_an_empty_table():
    verdict = run(place(), suppression=SuppressionIndex([]))
    outcome = next(o for o in verdict.outcomes if o.rule == RULE_NOT_SUPPRESSED)
    assert outcome.passed
    assert not verdict.excluded


def test_suppression_matches_any_scope_and_excludes():
    verdict = run(place(), suppression=SuppressionIndex(["ChIJ_test_1"]))
    assert RULE_NOT_SUPPRESSED in verdict.failed_rules
    assert verdict.excluded


def test_suppression_matches_phone_and_website_too():
    assert run(place(), suppression=SuppressionIndex(["+1 816-555-0100"])).excluded
    assert run(place(), suppression=SuppressionIndex(["HTTPS://ACMEPLUMBING.EXAMPLE"])).excluded


# --- review recency: deferred ------------------------------------------------------------


def test_review_recency_is_recorded_as_not_evaluated_by_default():
    """Deferred to Phase 5, where multiple pulls allow the better relative-velocity rule.
    The row is still written so the audit trail is honest rather than silently absent."""
    outcome = next(o for o in run(place()).outcomes if o.rule == RULE_REVIEW_RECENCY)
    assert outcome.passed
    assert outcome.observed_value == NOT_EVALUATED
    assert not outcome.evaluated


def test_enabling_review_recency_without_data_fails_open():
    """latest_review_at is None for every prospect in Phase 1. If someone flips the flag without
    the reviews stage in place, this must not exclude the entire market."""
    verdict = run(place(), review_recency_enabled=True)
    outcome = next(o for o in verdict.outcomes if o.rule == RULE_REVIEW_RECENCY)
    assert outcome.passed
    assert not verdict.excluded


def test_review_recency_excludes_when_data_exists():
    parsed = place()
    parsed.latest_review_at = date(2025, 1, 1)  # ~19 months before TODAY
    verdict = run(parsed, review_recency_enabled=True)
    assert RULE_REVIEW_RECENCY in verdict.failed_rules

    parsed.latest_review_at = date(2026, 6, 1)  # 1 month
    assert RULE_REVIEW_RECENCY not in run(parsed, review_recency_enabled=True).failed_rules


# --- disabled rules ----------------------------------------------------------------------


def test_disabled_rules_still_write_an_honest_row():
    verdict = run(place(phone=None, reviews=1), require_phone=False, min_review_count_enabled=False)
    for rule in (RULE_HAS_PHONE, RULE_REVIEW_COUNT):
        outcome = next(o for o in verdict.outcomes if o.rule == rule)
        assert outcome.passed
        assert outcome.observed_value == NOT_EVALUATED
    assert not verdict.excluded


# --- tiling and dedup --------------------------------------------------------------------


def test_tiles_are_the_cross_product_of_categories_and_submarkets():
    tiles = build_tiles(
        categories=["plumber", "drain cleaning"], submarkets=SUBMARKETS, market_name="Kansas City"
    )
    assert len(tiles) == 4
    assert all(t.coordinates for t in tiles)
    assert {t.submarket_id for t in tiles} == {"sm-north", "sm-east"}


def test_dedupe_collapses_overlapping_tiles_on_place_id():
    tile_a = TileRequest(query="plumber, Overland Park", label="A")
    tile_b = TileRequest(query="plumber, Lee's Summit", label="B")

    shared = {"place_id": "shared", "name": "Shared Plumbing"}
    deduped, stats = dedupe_on_place_id(
        [
            (tile_a, [shared, {"place_id": "only-a", "name": "A Only"}]),
            (tile_b, [shared, {"place_id": "only-b", "name": "B Only"}]),
        ],
        parse=parse_place,
    )

    assert set(deduped) == {"shared", "only-a", "only-b"}
    assert stats.total_returned == 4
    assert stats.unique_places == 3
    assert stats.duplicates_dropped == 1
    assert deduped["shared"].seen_in_tiles == ["A", "B"]
    assert stats.overlap_rate == pytest.approx(0.25)


def test_dedupe_counts_unparseable_rows_rather_than_inventing_ids():
    tile = TileRequest(query="plumber", label="A")
    deduped, stats = dedupe_on_place_id([(tile, [{"name": "No Id"}])], parse=parse_place)
    assert deduped == {}
    assert stats.unparseable == 1


def test_submarket_assignment_is_by_nearest_centroid_not_tile_order():
    assert nearest_submarket(38.98, -94.67, SUBMARKETS) == "sm-north"
    assert nearest_submarket(38.91, -94.38, SUBMARKETS) == "sm-east"
    assert nearest_submarket(None, None, SUBMARKETS) is None


# --- cost gate ---------------------------------------------------------------------------


def test_cost_estimate_rounds_up():
    estimate = cost.estimate_ingest_cost(
        tiles=1, places_per_tile=1, cost_per_1000_places_cents=200, limit_cents=5000
    )
    assert estimate.projected_cents == 1  # 0.2c rounded up, never down past the gate


def test_run_aborts_before_exceeding_the_cost_limit():
    estimate = cost.estimate_ingest_cost(
        tiles=100, places_per_tile=400, cost_per_1000_places_cents=200, limit_cents=5000
    )
    assert estimate.projected_cents == 8000
    assert not estimate.within_limit

    with pytest.raises(cost.CostLimitExceeded):
        cost.enforce_limit(estimate)


def test_cost_gate_passes_a_realistic_single_market_run():
    estimate = cost.estimate_ingest_cost(
        tiles=16, places_per_tile=400, cost_per_1000_places_cents=200, limit_cents=5000
    )
    assert estimate.within_limit
    cost.enforce_limit(estimate)


# --- transport shape ---------------------------------------------------------------------


def test_extract_places_handles_the_nested_per_query_shape():
    body = {"data": [[{"place_id": "a"}, {"place_id": "b"}]]}
    assert len(extract_places(body)) == 2


def test_extract_places_tolerates_a_flat_list():
    assert len(extract_places({"data": [{"place_id": "a"}]})) == 1


def test_extract_places_on_a_missing_payload():
    assert extract_places({"status": "Pending"}) == []


# --- host failover -----------------------------------------------------------------------


def test_proxy_error_triggers_failover():
    """httpx.ProxyError is NOT a subclass of ConnectError. An egress proxy refusing CONNECT looks
    nothing like a refused connection, so omitting it means the fallback hosts are never tried.
    Found for real: this environment's network policy 403s the CONNECT and the client gave up on
    the first host instead of trying the other two."""
    import httpx as _httpx

    from api.services.outscraper_client import FAILOVER_ERRORS

    assert not issubclass(_httpx.ProxyError, _httpx.ConnectError)
    assert issubclass(_httpx.ProxyError, FAILOVER_ERRORS)
    assert issubclass(_httpx.ConnectError, FAILOVER_ERRORS)

    # A slow host is working, not failing — do not burn the fallbacks on it.
    assert not issubclass(_httpx.ReadTimeout, FAILOVER_ERRORS)


# --- aliases confirmed against production ------------------------------------------------
#
# platform-api's services/gbp_service.py parses live Outscraper maps responses using this same
# API key. These lock in the field handling it demonstrates, so a future "tidy-up" of the alias
# order cannot silently break parsing that is known to work.


def test_category_prefers_category_then_type_then_subtypes():
    """gbp_service does `category or type`, falling back to a comma-joined `subtypes` string."""
    assert parse_place({"place_id": "x", "name": "n", "category": "Plumber",
                        "type": "Contractor"}).category == "Plumber"
    assert parse_place({"place_id": "x", "name": "n", "type": "Contractor"}).category == "Contractor"
    assert parse_place({"place_id": "x", "name": "n",
                        "subtypes": "Plumber, Drain service"}).category == "Plumber, Drain service"


def test_address_prefers_full_address():
    parsed = parse_place({"place_id": "x", "name": "n", "full_address": "1 Main St",
                          "address": "Main St"})
    assert parsed.address == "1 Main St"


def test_place_id_falls_back_to_google_id():
    """gbp_service resolves `place_id or google_id`. Both are real identifiers, so either is a
    legitimate key — unlike inventing one, which would join to nothing forever."""
    assert parse_place({"google_id": "0x80c2c7:0x5141f", "name": "n"}).place_id == "0x80c2c7:0x5141f"


def test_review_count_never_reads_reviews_data():
    """`reviews` is the count; `reviews_data` is the inline review list. Reading the latter as a
    count would produce a number that means nothing."""
    parsed = parse_place({
        "place_id": "x", "name": "n", "reviews": 42,
        "reviews_data": [{"review_text": "great"}, {"review_text": "good"}],
    })
    assert parsed.review_count == 42
    assert "reviews_data" not in {a for al in FIELD_ALIASES.values() for a in al}


def test_a_production_shaped_place_parses_completely():
    """Field names taken from what gbp_service actually reads off a live response."""
    parsed = parse_place({
        "place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
        "google_id": "0x80c2c7:0x5141f",
        "name": "Acme Plumbing",
        "full_address": "123 S Main St, Los Angeles, CA 90012",
        "phone": "+1 213-555-0100",
        "site": "https://acmeplumbing.example",
        "category": "Plumber",
        "subtypes": "Plumber, Drainage service",
        "rating": 4.7,
        "reviews": 218,
        "latitude": 34.0407,
        "longitude": -118.2468,
        "working_hours": {"Monday": "8AM-5PM"},
        "location_link": "https://maps.google.com/?cid=123",
        "area_service": False,
    })

    assert parsed.place_id == "ChIJN1t_tDeuEmsRUsoyG83frY4"
    assert parsed.website == "https://acmeplumbing.example"
    assert parsed.address.startswith("123 S Main St")
    assert parsed.category == "Plumber"
    assert parsed.review_count == 218
    assert (parsed.lat, parsed.lng) == (34.0407, -118.2468)
    # business_status is absent from real responses as far as anything here has observed —
    # it must not exclude.
    assert parsed.business_status is None
    assert not run(parsed).excluded


def test_endpoint_default_is_the_production_proven_one():
    from api.config import Settings
    from api.services.outscraper_client import ENDPOINT_MAPS_SEARCH, ENDPOINT_SEARCH_V3

    assert Settings().outscraper_search_endpoint == ENDPOINT_SEARCH_V3
    assert ENDPOINT_SEARCH_V3 != ENDPOINT_MAPS_SEARCH


# --- request shape per endpoint ----------------------------------------------------------


def _capture(endpoint: str):
    """Submit one tile against a mock transport and return the captured request."""
    import asyncio

    import httpx as _httpx

    from api.config import Settings
    from api.services.outscraper_client import OutscraperClient

    seen = {}

    def handler(request: _httpx.Request) -> _httpx.Response:
        seen["method"] = request.method
        seen["url"] = request.url
        seen["body"] = request.content.decode() if request.content else ""
        seen["api_key_header"] = request.headers.get("X-API-KEY")
        return _httpx.Response(200, json={"id": "req-1"})

    settings = Settings(
        outscraper_api_key="test-key", outscraper_search_endpoint=endpoint
    )
    mock = _httpx.AsyncClient(transport=_httpx.MockTransport(handler))

    async def go():
        async with OutscraperClient(settings, client=mock) as client:
            return await client.submit_maps_search(
                TileRequest(query="plumber, Downtown Los Angeles", coordinates="34.04,-118.24"),
                limit=20,
            )

    request_id = asyncio.run(go())
    assert request_id == "req-1"
    return seen


def test_search_v3_submits_a_GET_with_string_booleans():
    """Production passes `async` as the string "false"; the async form must mirror that."""
    from api.services.outscraper_client import ENDPOINT_SEARCH_V3

    seen = _capture(ENDPOINT_SEARCH_V3)

    assert seen["method"] == "GET"
    assert seen["url"].path == "/maps/search-v3"
    params = dict(seen["url"].params)
    assert params["query"] == "plumber, Downtown Los Angeles"
    assert params["async"] == "true"
    assert params["organizationsPerQueryLimit"] == "20"
    assert params["coordinates"] == "34.04,-118.24"
    assert seen["api_key_header"] == "test-key"


def test_google_maps_search_submits_a_POST_with_a_json_body():
    import json as _json

    from api.services.outscraper_client import ENDPOINT_MAPS_SEARCH

    seen = _capture(ENDPOINT_MAPS_SEARCH)

    assert seen["method"] == "POST"
    assert seen["url"].path == "/google-maps-search"
    body = _json.loads(seen["body"])
    assert body["query"] == ["plumber, Downtown Los Angeles"]
    assert body["async"] is True
    assert body["organizationsPerQueryLimit"] == 20


def test_enrichment_is_never_populated_on_either_endpoint():
    """Base tier only. An enrichment slipping in here is billed separately and is Phase 5."""
    import json as _json

    from api.services.outscraper_client import ENDPOINT_MAPS_SEARCH, ENDPOINT_SEARCH_V3

    assert dict(_capture(ENDPOINT_SEARCH_V3)["url"].params)["enrichment"] == ""
    assert _json.loads(_capture(ENDPOINT_MAPS_SEARCH)["body"])["enrichment"] == ""


def test_a_2xx_carrying_an_error_body_still_raises():
    """Outscraper reports failures with HTTP 200 and error:true. Status-code-only handling would
    treat this as success and return zero places."""
    import asyncio

    import httpx as _httpx

    from api.config import Settings
    from api.services.outscraper_client import OutscraperClient, OutscraperError

    mock = _httpx.AsyncClient(
        transport=_httpx.MockTransport(
            lambda r: _httpx.Response(200, json={"error": True, "errorMessage": "quota exceeded"})
        )
    )

    async def go():
        async with OutscraperClient(Settings(outscraper_api_key="k"), client=mock) as client:
            await client.submit_maps_search(TileRequest(query="plumber"))

    with pytest.raises(OutscraperError, match="quota exceeded"):
        asyncio.run(go())


# --- geography: the region qualifier -----------------------------------------------------
#
# A live calibration pull for "plumber, Downtown Los Angeles" with no coordinates and no region
# returned businesses in JERSEY CITY, NEW JERSEY. Outscraper resolves an ambiguous place name
# against its own server location, and most submarket names exist in several states. The failure
# mode is the dangerous kind: a market full of the wrong state's businesses is perfectly
# well-formed and completely worthless.


def test_region_qualifier_is_appended_to_tile_queries():
    from api.services.tiling import build_query

    assert build_query("plumber", "Downtown Los Angeles", "CA, USA") == (
        "plumber, Downtown Los Angeles, CA, USA"
    )
    assert build_query("plumber", "Downtown Los Angeles") == "plumber, Downtown Los Angeles"


def test_tiles_pin_geography_twice_with_coordinates_and_region():
    tiles = build_tiles(
        categories=["plumber"],
        submarkets=SUBMARKETS,
        market_name="Kansas City",
        region="MO, USA",
    )
    for tile in tiles:
        assert tile.coordinates, "coordinates bias the search centre"
        assert tile.query.endswith("MO, USA"), "the region disambiguates the place name"


def test_the_degenerate_no_submarket_tile_still_carries_the_region():
    """The fallback path is the one most likely to be hit by accident, so it must not be the one
    that silently searches the wrong state."""
    tiles = build_tiles(
        categories=["plumber"], submarkets=[], market_name="Springfield", region="IL, USA"
    )
    assert tiles[0].query == "plumber, Springfield, IL, USA"


def test_a_market_without_a_region_is_flagged():
    from api.services.seeding import MarketDefinition, SubmarketDefinition, validate_definition

    definition = MarketDefinition(
        name="M",
        center_lat=39.0,
        center_lng=-94.0,
        radius_miles=25,
        categories=["plumber"],
        submarkets=[SubmarketDefinition(name="S", center_lat=39.0, center_lng=-94.0)],
    )
    assert any("region" in p for p in validate_definition(definition))

    definition.region = "MO, USA"
    assert validate_definition(definition) == []


def test_the_los_angeles_market_carries_a_region():
    from api.services.seeding import MarketDefinition

    path = Path(__file__).resolve().parents[2] / "markets" / "los-angeles-plumbing.json"
    assert MarketDefinition.from_file(path).region == "CA, USA"


# --- job result marker -------------------------------------------------------------------


def test_missing_credentials_names_only_the_absent_one():
    """"A and B must be set" when only B is missing sends people to check A first — which is
    set — and makes the error look wrong. Observed for real on the first Railway run."""
    from api.config import Settings, missing_supabase_vars

    only_key_missing = Settings(
        supabase_url="https://x.supabase.co", supabase_service_role_key=""
    )
    assert missing_supabase_vars(only_key_missing) == ["OUTREACH_SUPABASE_SERVICE_ROLE_KEY"]

    assert missing_supabase_vars(
        Settings(supabase_url="", supabase_service_role_key="")
    ) == ["OUTREACH_SUPABASE_URL", "OUTREACH_SUPABASE_SERVICE_ROLE_KEY"]

    assert missing_supabase_vars(
        Settings(supabase_url="https://x.supabase.co", supabase_service_role_key="k")
    ) == []
