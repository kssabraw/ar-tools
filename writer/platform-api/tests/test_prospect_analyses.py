import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import prospect_analyses as pa  # noqa: E402


# ── Pure helpers ─────────────────────────────────────────────────────────────

def test_primary_category_prefers_gbp_category_then_list():
    assert pa.primary_category({"gbp_category": "Roofing contractor"}) == "Roofing contractor"
    assert pa.primary_category({"gbp_categories": ["Plumber", "x"]}) == "Plumber"
    assert pa.primary_category({"gbp_category": "  "}) is None
    assert pa.primary_category(None) is None


def test_city_of_takes_locality_before_comma():
    assert pa.city_of({"business_location": "Tampa, FL"}) == "Tampa"
    assert pa.city_of({"business_location": "Orlando"}) == "Orlando"
    assert pa.city_of({}) is None


def test_ai_keyword_geo_qualifies_then_falls_back_to_name():
    g = {"gbp_category": "Roofing contractor"}
    assert pa.ai_keyword(g, "Acme", "Tampa") == "Roofing contractor Tampa"
    assert pa.ai_keyword(g, "Acme", None) == "Roofing contractor"
    assert pa.ai_keyword({}, "Acme Co", "Tampa") == "Acme Co"
    assert pa.ai_keyword(None, "", None) is None


def test_gbp_center_parses_floats_and_degrades():
    assert pa.gbp_center({"latitude": 1.5, "longitude": -2.0}) == (1.5, -2.0)
    assert pa.gbp_center({"latitude": "bad"}) == (None, None)
    assert pa.gbp_center(None) == (None, None)


# ── Gating (which analyses fire) ─────────────────────────────────────────────

def _client():
    return {"id": "c1", "name": "Acme", "website_url": "https://acme.test",
            "gbp_place_id": "p1", "gbp": {"gbp_category": "Roofing contractor",
                                          "latitude": 1.0, "longitude": 2.0}}


def _patched_runners():
    return (
        patch.object(pa, "_run_organic", return_value="enqueued"),
        patch.object(pa, "_run_ai", return_value="enqueued"),
        patch.object(pa, "_run_maps", return_value="enqueued"),
    )


def test_create_fires_all_three():
    o, a, m = _patched_runners()
    with o as mo, a as ma, m as mm:
        summary = pa.run_prospect_analyses(_client(), "u1", is_create=True)
    assert set(summary) == {"organic", "ai", "maps"}
    mo.assert_called_once()
    ma.assert_called_once()
    mm.assert_called_once()


def test_edit_website_change_fires_only_organic():
    o, a, m = _patched_runners()
    with o as mo, a as ma, m as mm:
        summary = pa.run_prospect_analyses(
            _client(), "u1", is_create=False, website_changed=True, gbp_changed=False
        )
    assert set(summary) == {"organic"}
    mo.assert_called_once()
    ma.assert_not_called()
    mm.assert_not_called()


def test_edit_gbp_change_fires_ai_and_maps_not_organic():
    o, a, m = _patched_runners()
    with o as mo, a as ma, m as mm:
        summary = pa.run_prospect_analyses(
            _client(), "u1", is_create=False, website_changed=False, gbp_changed=True
        )
    assert set(summary) == {"ai", "maps"}
    mo.assert_not_called()
    ma.assert_called_once()
    mm.assert_called_once()


def test_edit_no_relevant_change_fires_nothing():
    o, a, m = _patched_runners()
    with o as mo, a as ma, m as mm:
        summary = pa.run_prospect_analyses(
            _client(), "u1", is_create=False, website_changed=False, gbp_changed=False
        )
    assert summary == {}
    mo.assert_not_called()
    ma.assert_not_called()
    mm.assert_not_called()


# ── Runner skip branches ─────────────────────────────────────────────────────

def test_run_organic_skips_without_website():
    assert pa._run_organic({"id": "c1", "website_url": ""}, "u1") == "skipped_no_website"


def test_run_organic_enqueues_overview():
    from services import domain_intel

    # normalize_domain is pure; only the enqueue touches the DB, so stub it.
    with patch.object(domain_intel, "enqueue_domain_overview") as enq:
        out = pa._run_organic({"id": "c1", "website_url": "https://acme.test"}, "u1")
    assert out == "enqueued"
    enq.assert_called_once()
    args, kwargs = enq.call_args
    assert args[0] == "c1"
    assert args[1] == "acme.test"
    assert kwargs.get("role") == "prospect"
    assert kwargs.get("user_id") == "u1"


def test_run_maps_skips_without_gbp_location():
    out = pa._run_maps({"id": "c1", "name": "Acme", "gbp_place_id": None,
                        "gbp": {"gbp_category": "Roofing contractor"}})
    assert out == "skipped_no_gbp_location"
