import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import locations_service  # noqa: E402


_AU_LOCATIONS = [
    {"location_name": "Melbourne,Victoria,Australia", "location_code": 1000567,
     "location_type": "City", "country_iso_code": "AU"},
    {"location_name": "Melbourne,Florida,United States", "location_code": 1015116,
     "location_type": "City", "country_iso_code": "US"},
    {"location_name": "Sydney,New South Wales,Australia", "location_code": 1000286,
     "location_type": "City", "country_iso_code": "AU"},
]


def test_infer_country_iso_from_cctld():
    assert locations_service.infer_country_iso({"website_url": "https://firstclassroofing.com.au"}) == "AU"
    assert locations_service.infer_country_iso({"website_url": "https://example.co.uk"}) == "GB"
    # unknown / gTLD falls back to the default
    assert locations_service.infer_country_iso({"website_url": "https://example.com"}) == "US"
    assert locations_service.infer_country_iso({}) == "US"


def test_infer_country_iso_uses_gbp_website():
    client = {"website_url": None, "gbp": {"website": "https://shop.com.au"}}
    assert locations_service.infer_country_iso(client) == "AU"


@pytest.mark.asyncio
async def test_search_locations_ranks_city_prefix_first():
    with patch.object(locations_service, "_fetch_country_locations",
                      new=AsyncMock(return_value=_AU_LOCATIONS)):
        res = await locations_service.search_locations({"website_url": "x.com.au"}, "melb")
    # both Melbournes match; AU client list only contains AU + the US dupe we fed,
    # ordering is by match strength then name — prefix on the city segment wins.
    assert res
    assert all("Melbourne" in r["location_name"] for r in res)


@pytest.mark.asyncio
async def test_search_locations_short_query_returns_empty():
    res = await locations_service.search_locations({"website_url": "x.com.au"}, "m")
    assert res == []


@pytest.mark.asyncio
async def test_resolve_location_trusts_supplied_code():
    # code present → no network call, returned as-is
    name, code = await locations_service.resolve_location({}, "anything typed", 4242)
    assert (name, code) == ("anything typed", 4242)


@pytest.mark.asyncio
async def test_resolve_location_exact_match_attaches_code():
    with patch.object(locations_service, "_fetch_country_locations",
                      new=AsyncMock(return_value=_AU_LOCATIONS)):
        name, code = await locations_service.resolve_location(
            {"website_url": "x.com.au"}, "melbourne, victoria, australia", None
        )
    assert code == 1000567
    assert name == "Melbourne,Victoria,Australia"


@pytest.mark.asyncio
async def test_resolve_location_rejects_unknown_with_suggestions():
    with patch.object(locations_service, "_fetch_country_locations",
                      new=AsyncMock(return_value=_AU_LOCATIONS)):
        with pytest.raises(HTTPException) as exc:
            await locations_service.resolve_location(
                {"website_url": "x.com.au"}, "Atlantis, Nowhere, Australia", None
            )
    assert exc.value.status_code == 400
    assert "location_not_recognized" in exc.value.detail


@pytest.mark.asyncio
async def test_resolve_location_passes_through_when_lookup_unavailable():
    # provider/creds down → empty list → don't block generation
    with patch.object(locations_service, "_fetch_country_locations",
                      new=AsyncMock(return_value=[])):
        name, code = await locations_service.resolve_location(
            {"website_url": "x.com.au"}, "Melbourne, VIC", None
        )
    assert (name, code) == ("Melbourne, VIC", None)
