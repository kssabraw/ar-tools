"""§16a.1 pixel-field spike — the PURE heuristic that reads a spike result (ISSUES I-003).

The live enriched pull is measured on the owner's run (fetch_enriched_sample logs the raw record);
what is tested here is how a returned record is scanned for pixel indicators, WITHOUT asserting the
enrichment's field name — because that name is exactly what the spike is measuring.
"""
from api.services import pixel_probe as pp


def test_scan_place_finds_pixel_by_value_regardless_of_key_name():
    # The field name is unknown; a value fingerprint is the strong signal.
    place = {"name": "Drips", "site_meta": {"scripts": ["https://connect.facebook.net/fbevents.js"]}}
    got = pp.scan_place_for_pixel(place)
    assert got["found"] is True
    assert got["value_hits"][0]["key"] == "site_meta.scripts[0]"


def test_scan_place_key_hint_without_value_means_field_exists_but_empty():
    # A field NAMED like a pixel but null -> the envelope carries it, this record didn't populate it.
    place = {"name": "Drips", "facebook_pixel_id": None, "meta_tags": ""}
    got = pp.scan_place_for_pixel(place)
    assert got["found"] is False
    assert "facebook_pixel_id" in got["key_hints"]


def test_scan_place_detects_gtm_and_aw_values():
    assert pp.scan_place_for_pixel({"x": "GTM-ABCD12"})["found"] is True
    assert pp.scan_place_for_pixel({"x": "AW-1234567"})["found"] is True
    assert pp.scan_place_for_pixel({"x": "nothing here"})["found"] is False


def test_summarize_pixel_probe_aggregates_rates():
    records = [
        {"fb_pixel": "connect.facebook.net/fbevents.js"},   # found + key hint
        {"fb_pixel": None},                                  # key hint only (carries, empty)
        {"name": "no tech at all"},                          # neither
        {"tracking": "fbq('init')"},                         # found (value) + key hint
    ]
    out = pp.summarize_pixel_probe(records)
    assert out["sample"] == 4
    assert out["found"] == 2 and out["found_rate"] == 0.5
    assert out["carries_field"] == 3 and out["carries_field_rate"] == 0.75
    assert "fb_pixel" in out["field_names_seen"]


def test_summarize_empty_sample_is_zero_not_error():
    out = pp.summarize_pixel_probe([])
    assert out == {"sample": 0, "found": 0, "found_rate": 0.0, "carries_field": 0,
                   "carries_field_rate": 0.0, "field_names_seen": [], "per_record": []}
