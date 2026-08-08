"""Pure tech-signal detection — paid-placement Slice B1 (PRD §B3).

Deterministic signature detection over page bytes. These pin the fingerprints (a Meta pixel, an AW-
conversion tag, a GTM container, vendor tags) and the two rules that matter downstream: absence is a
real all-False finding (only stored when the fetch SUCCEEDED), and a GTM-only page is the case the
container follow exists for.
"""
import pytest

from api.services import tech_signals as ts
from api.services.scan_tech import normalize_site_url


def test_detect_meta_pixel_by_loader_and_id():
    html = """<script>!function(f){...}(); fbq('init', '1234567890'); fbq('track','PageView');
              <img src="https://connect.facebook.net/en_US/fbevents.js"></script>"""
    sig = ts.detect_tech_signals(html)
    assert sig.meta_pixel is True
    assert sig.meta_pixel_ids == ("1234567890",)
    assert sig.evidence["meta_pixel"] == ["1234567890"]


def test_detect_google_ads_conversion_captures_aw_id():
    html = "<script>gtag('config','AW-987654321');</script>" \
           "<img src='https://www.googleadservices.com/pagead/conversion/1/'>"
    sig = ts.detect_tech_signals(html)
    assert sig.google_ads_conversion is True
    assert sig.aw_ids == ("AW-987654321",)


def test_detect_gtm_and_vendor_tags():
    html = "<script src='https://www.googletagmanager.com/gtm.js?id=GTM-ABCD12'></script>" \
           "<script src='//cdn.callrail.com/x.js'></script>" \
           "<div>powered by podium.com</div>"
    sig = ts.detect_tech_signals(html)
    assert sig.gtm_container_ids == ("GTM-ABCD12",)
    assert set(sig.vendor_tags) == {"callrail", "podium"}
    # Two marketing-stack signals -> reads as "handled" (the -21 decision-structure bin).
    assert sig.likely_represented is True


def test_empty_page_is_all_false_not_an_error():
    sig = ts.detect_tech_signals("")
    assert sig.meta_pixel is False and sig.google_ads_conversion is False
    assert sig.vendor_tags == () and sig.evidence == {}
    # None body is tolerated too (never raises).
    assert ts.detect_tech_signals(None).meta_pixel is False


def test_looks_gtm_only_flags_the_container_follow_case():
    gtm_only = ts.detect_tech_signals("<script src='...gtm.js?id=GTM-ZZZZ99'></script>")
    assert ts.looks_gtm_only(gtm_only) is True
    with_pixel = ts.detect_tech_signals("GTM-ZZZZ99 and fbq('init','111111')")
    assert ts.looks_gtm_only(with_pixel) is False   # a pixel is already inline, no follow needed


def test_merge_signals_recovers_a_gtm_injected_pixel():
    page = ts.detect_tech_signals("<script src='gtm.js?id=GTM-AAAA11'></script>")   # container only
    container = ts.detect_tech_signals("fbq('init','555555'); connect.facebook.net/fbevents.js")
    merged = ts.merge_signals(page, container)
    assert merged.meta_pixel is True and "555555" in merged.meta_pixel_ids
    assert merged.gtm_followed is True
    assert merged.gtm_container_ids == ("GTM-AAAA11",)          # container ids stay from the page
    assert merged.evidence["gtm_container"]["meta_pixel"] == ["555555"]


def test_summarize_tech_carries_fetch_status():
    sig = ts.detect_tech_signals("fbq('init','222222')")
    row = ts.summarize_tech(sig, fetch_status="ok", final_url="https://x.com")
    assert row["fetch_status"] == "ok" and row["meta_pixel"] is True and row["final_url"] == "https://x.com"


@pytest.mark.parametrize("raw,expected", [
    ("drips.com", "https://drips.com"),
    ("http://ace.com", "http://ace.com"),
    ("https://bolt.com/x", "https://bolt.com/x"),
    ("  ", None),
    (None, None),
    ("mailto:x@y.com", None),
])
def test_normalize_site_url(raw, expected):
    assert normalize_site_url(raw) == expected
