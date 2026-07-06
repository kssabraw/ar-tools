import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import gbp_service  # noqa: E402


@pytest.mark.asyncio
async def test_resolve_query_passes_through_place_id():
    assert await gbp_service.resolve_query("ChIJrTLr-GyuEmsRBfy61i59si0") == (
        "ChIJrTLr-GyuEmsRBfy61i59si0"
    )


@pytest.mark.asyncio
async def test_resolve_query_passes_through_feature_id():
    fid = "0x89c259a9b3117469:0xd134e199a405a163"
    assert await gbp_service.resolve_query(fid) == fid


@pytest.mark.asyncio
async def test_resolve_query_passes_through_free_text():
    assert await gbp_service.resolve_query("  Joe's Coffee Austin  ") == "Joe's Coffee Austin"


@pytest.mark.asyncio
async def test_resolve_query_extracts_feature_id_from_full_url():
    url = (
        "https://www.google.com/maps/place/Joe's/@30.26,-97.74,17z/"
        "data=!3m1!4b1!4m6!1s0x89c259a9b3117469:0xd134e199a405a163!8m2"
    )
    assert await gbp_service.resolve_query(url) == "0x89c259a9b3117469:0xd134e199a405a163"


@pytest.mark.asyncio
async def test_resolve_query_extracts_cid_from_url():
    url = "https://maps.google.com/?cid=15021632960191197043"
    assert await gbp_service.resolve_query(url) == "15021632960191197043"


@pytest.mark.asyncio
async def test_resolve_query_returns_full_url_when_no_identifier():
    url = "https://www.google.com/maps/place/Some+Place/"
    assert await gbp_service.resolve_query(url) == url


@pytest.mark.asyncio
async def test_resolve_query_expands_short_link():
    expanded = "https://www.google.com/maps/place/X/data=!4m2!1s0xabc:0xdef!8m2"
    with patch.object(
        gbp_service, "_expand_short_link", new=AsyncMock(return_value=expanded)
    ) as mock_expand:
        result = await gbp_service.resolve_query("https://maps.app.goo.gl/abc123")
    mock_expand.assert_awaited_once()
    assert result == "0xabc:0xdef"


@pytest.mark.asyncio
async def test_resolve_query_rejects_empty():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await gbp_service.resolve_query("   ")
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_resolve_business_delegates_to_details():
    with patch.object(
        gbp_service, "get_business_details", new=AsyncMock(return_value={"place_id": "X"})
    ) as mock_details:
        out = await gbp_service.resolve_business("Joe's Coffee Austin")
    mock_details.assert_awaited_once_with("Joe's Coffee Austin")
    assert out == {"place_id": "X"}


# ── normalize_website_url ────────────────────────────────────────────────────

def test_normalize_website_repairs_encoded_query_in_path():
    # A GBP tracking link whose `?…` was percent-encoded into the path (the
    # WheelHouse IT bug): `%3F`=`?`, `%3D`=`=`, `%26`=`&`. The encoded `?`
    # never separates the query, so the URL 404s. Decode it, then strip the
    # tracking params → the clean canonical page.
    bad = (
        "https://www.wheelhouseit.com/it-support-fort-lauderdale/"
        "%3Futm_source%3Dgoogle%26utm_medium%3Dorganic%26utm_campaign%3Dgbp"
    )
    assert (
        gbp_service.normalize_website_url(bad)
        == "https://www.wheelhouseit.com/it-support-fort-lauderdale/"
    )


def test_normalize_website_strips_tracking_params_from_real_query():
    url = "https://ex.com/page/?utm_source=google&gclid=abc&id=7"
    # Non-tracking params are preserved; tracking ones dropped.
    assert gbp_service.normalize_website_url(url) == "https://ex.com/page/?id=7"


def test_normalize_website_leaves_clean_url_untouched():
    for url in (
        "https://ex.com/",
        "https://ex.com/services/plumbing",
        "https://ex.com/search?q=hello",
    ):
        assert gbp_service.normalize_website_url(url) == url


def test_normalize_website_handles_empty_and_none():
    assert gbp_service.normalize_website_url(None) is None
    assert gbp_service.normalize_website_url("") == ""
    assert gbp_service.normalize_website_url("   ") == ""
