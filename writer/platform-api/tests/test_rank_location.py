"""Unit tests for GBP→tracking-location derivation (Organic Rank Tracker)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from services import rank_location


def _run(coro):
    return asyncio.run(coro)


# ---- address fallback parsing (pure) ---------------------------------------
def test_address_candidates_au_one_segment():
    # AU: suburb + state + postcode share one comma segment.
    assert rank_location.address_location_candidates(
        "117 Newry St, Carlton North VIC 3054, Australia"
    ) == ["Carlton North", "VIC"]


def test_address_candidates_us_separate_segments():
    # US: city and state are separate comma segments.
    assert rank_location.address_location_candidates(
        "123 Main St, Phoenix, AZ 85001, USA"
    ) == ["Phoenix", "AZ"]


def test_address_candidates_empty_or_too_short():
    assert rank_location.address_location_candidates(None) == []
    assert rank_location.address_location_candidates("") == []
    assert rank_location.address_location_candidates("Australia") == []


# ---- derive_location_from_gbp ----------------------------------------------
def _match(name, code, ltype="City"):
    return {"location_name": name, "location_code": code, "location_type": ltype}


def test_derive_prefers_city_from_reverse_geocode():
    client = {"gbp": {"latitude": -37.78, "longitude": 144.97}, "website_url": "https://x.com.au/"}
    search = AsyncMock(return_value=[_match("Melbourne,Victoria,Australia", 1000567)])
    with patch.object(rank_location, "get_supabase", return_value=MagicMock()), \
         patch.object(rank_location.maps_geocode, "reverse_geocode_points",
                      new=AsyncMock(return_value=[{"city": "Melbourne", "admin_area": "Victoria"}])), \
         patch.object(rank_location.locations_service, "search_locations", new=search):
        name, code = _run(rank_location.derive_location_from_gbp(client))
    assert (name, code) == ("Melbourne,Victoria,Australia", 1000567)
    assert search.await_args_list[0].args[1] == "Melbourne"  # city tried first


def test_derive_falls_back_to_region_when_city_unmatched():
    client = {"gbp": {"latitude": 1.0, "longitude": 2.0}, "website_url": "https://x.com.au/"}

    async def fake_search(_client, candidate, country=None, limit=10):
        return [_match("Victoria,Australia", 2076, "Region")] if candidate == "Victoria" else []

    with patch.object(rank_location, "get_supabase", return_value=MagicMock()), \
         patch.object(rank_location.maps_geocode, "reverse_geocode_points",
                      new=AsyncMock(return_value=[{"city": "Carlton North", "admin_area": "Victoria"}])), \
         patch.object(rank_location.locations_service, "search_locations", new=AsyncMock(side_effect=fake_search)):
        name, code = _run(rank_location.derive_location_from_gbp(client))
    assert (name, code) == ("Victoria,Australia", 2076)


def test_derive_uses_address_when_no_coords():
    client = {"gbp": {"address": "117 Newry St, Carlton North VIC 3054, Australia"},
              "website_url": "https://x.com.au/"}

    async def fake_search(_client, candidate, country=None, limit=10):
        return [_match("Carlton North,Victoria,Australia", 999)] if candidate == "Carlton North" else []

    # No coords → reverse-geocode is never called.
    with patch.object(rank_location.locations_service, "search_locations", new=AsyncMock(side_effect=fake_search)):
        name, code = _run(rank_location.derive_location_from_gbp(client))
    assert (name, code) == ("Carlton North,Victoria,Australia", 999)


def test_derive_returns_none_when_unresolved():
    client = {"gbp": {"address": "1 Nowhere Rd, Faketown ZZ 0000, Australia"},
              "website_url": "https://x.com.au/"}
    with patch.object(rank_location.locations_service, "search_locations", new=AsyncMock(return_value=[])):
        name, code = _run(rank_location.derive_location_from_gbp(client))
    assert (name, code) == (None, None)


def test_derive_no_gbp_returns_none():
    with patch.object(rank_location.locations_service, "search_locations", new=AsyncMock(return_value=[])):
        name, code = _run(rank_location.derive_location_from_gbp({"website_url": "https://x.com/"}))
    assert (name, code) == (None, None)
