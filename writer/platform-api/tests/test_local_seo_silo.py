"""Unit tests for services.local_seo_silo — the found/on_site/missing marking.

Pure logic only: the LLM/geocoding pipeline (`_run_pipeline`, neighborhood +
target-city discovery) bills external APIs and is not exercised here. These cover
`_to_items` + `_match_page_on_site` — in particular that a page already published on
the client's live site is flagged `on_site` (not a false `missing`), which is the
regression this module hardens.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services import local_seo_silo as silo


def _fake_supabase_with_pages(rows: list[dict]) -> MagicMock:
    """Mock the `local_seo_pages` read in `_to_items`:
    table().select().eq().is_().execute().data == rows."""
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value.is_.return_value
    chain.execute.return_value.data = rows
    return sb


def _status_by_kw(items: list[dict]) -> dict[str, dict]:
    return {i["keyword"]: i for i in items}


# ── the reported bug: a live "<service> <city>" page is not "missing" ──────────

def test_service_city_page_on_live_site_is_on_site():
    per_silo = [
        {
            "silo": "Roof Restoration",
            "pages": [
                {"keyword": "roof restoration melbourne", "supporting_keywords": []},
                {"keyword": "roof restoration geelong", "supporting_keywords": []},
            ],
        }
    ]
    site_urls = ["https://fcr.com/roof-restoration-melbourne/"]
    with patch.object(silo, "get_supabase", return_value=_fake_supabase_with_pages([])):
        items = silo._to_items(per_silo, "client-1", site_urls)

    by_kw = _status_by_kw(items)
    # Melbourne page already published on the site → on_site (was a false "missing").
    assert by_kw["roof restoration melbourne"]["status"] == "on_site"
    assert by_kw["roof restoration melbourne"]["url"] == "https://fcr.com/roof-restoration-melbourne/"
    # Geelong page genuinely absent → still offered for creation.
    assert by_kw["roof restoration geelong"]["status"] == "missing"


def test_found_in_tool_wins_over_on_site():
    per_silo = [
        {"silo": "Roof Restoration", "pages": [{"keyword": "roof restoration melbourne"}]}
    ]
    rows = [{"keyword": "roof restoration melbourne", "published_doc_url": "https://docs/abc"}]
    site_urls = ["https://fcr.com/roof-restoration-melbourne/"]
    with patch.object(silo, "get_supabase", return_value=_fake_supabase_with_pages(rows)):
        items = silo._to_items(per_silo, "client-1", site_urls)
    assert items[0]["status"] == "found"
    assert items[0]["url"] == "https://docs/abc"


def test_more_specific_live_page_does_not_suppress_base_page():
    # An emergency variation on the site must not mark the base page as existing.
    per_silo = [
        {"silo": "Roof Restoration", "pages": [{"keyword": "roof restoration melbourne"}]}
    ]
    site_urls = ["https://fcr.com/emergency-roof-restoration-melbourne/"]
    with patch.object(silo, "get_supabase", return_value=_fake_supabase_with_pages([])):
        items = silo._to_items(per_silo, "client-1", site_urls)
    assert items[0]["status"] == "missing"


def test_supporting_keyword_matches_live_page():
    per_silo = [
        {
            "silo": "Roof Restoration",
            "pages": [
                {
                    "keyword": "roof restoration melbourne",
                    "supporting_keywords": ["melbourne roof restorations"],
                }
            ],
        }
    ]
    # Site slug matches the supporting variant, not the head keyword's exact slug.
    site_urls = ["https://fcr.com/melbourne-roof-restorations/"]
    with patch.object(silo, "get_supabase", return_value=_fake_supabase_with_pages([])):
        items = silo._to_items(per_silo, "client-1", site_urls)
    assert items[0]["status"] == "on_site"


def test_no_site_urls_leaves_pages_missing():
    per_silo = [
        {"silo": "Roof Restoration", "pages": [{"keyword": "roof restoration melbourne"}]}
    ]
    with patch.object(silo, "get_supabase", return_value=_fake_supabase_with_pages([])):
        items = silo._to_items(per_silo, "client-1", [])
    assert items[0]["status"] == "missing"


# ── generic location page still covers a bare-place area target ────────────────

def test_generic_location_page_matches_area_target_via_location_name():
    per_silo = [
        {
            "silo": "Neighborhoods",
            "pages": [
                {
                    "keyword": "roof restoration inner east",
                    "supporting_keywords": [],
                    "location_name": "Inner East",
                }
            ],
        }
    ]
    # No service+area page, but a generic /inner-east/ location page exists.
    site_urls = ["https://fcr.com/service-areas/inner-east/"]
    with patch.object(silo, "get_supabase", return_value=_fake_supabase_with_pages([])):
        items = silo._to_items(per_silo, "client-1", site_urls)
    assert items[0]["status"] == "on_site"
    assert items[0]["url"] == "https://fcr.com/service-areas/inner-east/"


# ── _match_page_on_site precedence: keyword before bare place ──────────────────

def test_match_page_on_site_prefers_keyword_over_place():
    token_index = silo.site_page_index.build_page_token_index(
        ["https://fcr.com/roof-restoration-melbourne/"]
    )
    place_index = silo.site_page_index.build_location_slug_index(
        ["https://fcr.com/melbourne/"]
    )
    page = {
        "keyword": "roof restoration melbourne",
        "supporting_keywords": [],
        "location_name": "Melbourne",
    }
    # The specific service+city page wins over the generic /melbourne/ page.
    assert (
        silo._match_page_on_site(page, token_index, place_index)
        == "https://fcr.com/roof-restoration-melbourne/"
    )


def test_match_page_on_site_none_when_nothing_matches():
    page = {"keyword": "roof restoration bendigo", "supporting_keywords": []}
    assert silo._match_page_on_site(page, {}, {}) is None
