"""Unit tests for the pure competitor page-generation targeting analysis."""

from services import competitor_page_intel as cpi


# ---------------------------------------------------------------------------
# extract_page_target
# ---------------------------------------------------------------------------
def test_extract_target_suburb_page_with_state_and_postcode():
    assert cpi.extract_page_target("/services/east-melbourne-vic-3002/") == "East Melbourne"
    assert cpi.extract_page_target("https://x.com.au/services/port-melbourne-vic-3207/") == "Port Melbourne"


def test_extract_target_us_state_suffix():
    assert cpi.extract_page_target("https://x.com/locations/austin-tx/") == "Austin"


def test_extract_target_topic_page():
    assert cpi.extract_page_target("/blog/how-to-clean-gutters") == "How To Clean Gutters"


def test_extract_target_skips_generic_terminal_segment():
    # trailing generic "services" segment is skipped for the meaningful one
    assert cpi.extract_page_target("/kew-vic-3121/services") == "Kew"


def test_extract_target_pure_postcode_or_state_is_empty():
    assert cpi.extract_page_target("/services/3002/") == ""
    assert cpi.extract_page_target("/vic/") == ""
    assert cpi.extract_page_target("") == ""
    assert cpi.extract_page_target(None) == ""


def test_extract_target_bare_slug_without_scheme():
    assert cpi.extract_page_target("services/richmond-vic-3121") == "Richmond"


# ---------------------------------------------------------------------------
# page_targets_place — token-level, not substring
# ---------------------------------------------------------------------------
def test_single_token_place_matches_segment_not_substring():
    assert cpi.page_targets_place("/services/kew-vic-3101/", "Kew") is True
    # 'kew' must be a whole token, never a substring of 'kewell'
    assert cpi.page_targets_place("/services/kewell-vic-3000/", "Kew") is False


def test_multi_token_place_requires_all_tokens():
    assert cpi.page_targets_place("/services/port-melbourne-vic-3207/", "Port Melbourne") is True
    # a page only about 'melbourne' does not satisfy the 2-token 'port melbourne'
    assert cpi.page_targets_place("/services/melbourne-cbd-3000/", "Port Melbourne") is False


def test_place_with_admin_suffix_drops_state():
    assert cpi.page_targets_place("/services/toorak-vic-3142/", "Toorak, VIC") is True


def test_empty_place_never_matches():
    assert cpi.page_targets_place("/services/kew/", "") is False
    assert cpi.page_targets_place("/services/kew/", ", VIC") is False


# ---------------------------------------------------------------------------
# match_pages_to_places
# ---------------------------------------------------------------------------
def _pages():
    return [
        {"competitor": "Melbourne Roof Restorers", "url": "/services/toorak-vic-3142/", "first_seen": "2026-08-20"},
        {"competitor": "Melbourne Roof Restorers", "url": "/services/richmond-vic-3121/", "first_seen": "2026-08-21"},
        {"competitor": "Metropolitan Roof Repairs", "url": "/blog/roof-tips", "first_seen": "2026-08-22"},
    ]


def test_match_returns_only_contested_places_in_order():
    places = ["Preston, VIC", "Toorak, VIC", "Kew, VIC"]
    matches = cpi.match_pages_to_places(_pages(), places)
    assert [m["place"] for m in matches] == ["Toorak, VIC"]
    assert matches[0]["competitor"] == "Melbourne Roof Restorers"
    assert matches[0]["url"] == "/services/toorak-vic-3142/"


def test_match_empty_inputs():
    assert cpi.match_pages_to_places([], ["Kew"]) == []
    assert cpi.match_pages_to_places(_pages(), []) == []


# ---------------------------------------------------------------------------
# summarize_targeting
# ---------------------------------------------------------------------------
def _profiles():
    return [
        {
            "name": "Melbourne Roof Restorers",
            "recent_pages": [
                {"url": "/services/toorak-vic-3142/", "first_seen": "2026-08-20"},
                {"url": "/services/richmond-vic-3121/", "first_seen": "2026-08-21"},
                {"url": "/services/toorak-vic-3142/", "first_seen": "2026-08-25"},  # dup label
            ],
        },
        {"name": "Metropolitan Roof Repairs", "recent_pages": []},
    ]


def test_summarize_competitor_targets_deduped():
    out = cpi.summarize_targeting(_profiles(), ["Preston, VIC", "Toorak, VIC"])
    targets = {c["name"]: c for c in out["competitor_targets"]}
    assert targets["Melbourne Roof Restorers"]["targets"] == ["Toorak", "Richmond"]
    assert targets["Melbourne Roof Restorers"]["count"] == 2
    # a competitor with no recent pages contributes nothing
    assert "Metropolitan Roof Repairs" not in targets


def test_summarize_contested_and_open_split():
    out = cpi.summarize_targeting(_profiles(), ["Preston, VIC", "Toorak, VIC"])
    assert out["contested_places"] == ["Toorak, VIC"]
    assert out["open_places"] == ["Preston, VIC"]
    assert len(out["contested"]) == 2  # two Toorak pages (dup url) both surface as evidence


def test_summarize_no_priority_places_still_lists_targets():
    out = cpi.summarize_targeting(_profiles(), [])
    assert out["competitor_targets"]  # answerable without priority places
    assert out["contested"] == []
    assert out["contested_places"] == []
    assert out["open_places"] == []


# ---------------------------------------------------------------------------
# contested_by_place
# ---------------------------------------------------------------------------
def test_contested_by_place_groups_case_insensitively():
    matches = [
        {"place": "Toorak, VIC", "competitor": "A", "url": "/a", "first_seen": "1"},
        {"place": "toorak, vic", "competitor": "B", "url": "/b", "first_seen": "2"},
        {"place": "Kew, VIC", "competitor": "A", "url": "/c", "first_seen": "3"},
    ]
    grouped = cpi.contested_by_place(matches)
    assert set(grouped.keys()) == {"toorak, vic", "kew, vic"}
    assert [c["competitor"] for c in grouped["toorak, vic"]] == ["A", "B"]
