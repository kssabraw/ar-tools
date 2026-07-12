"""Unit tests for the QA visual design-fit check's pure layer:
qa_signals.asset_urls_of (the free asset-integrity extraction) and
qa_visual's screenshot-response parsing + verdict mapping. IO (DataForSEO
capture, vision call, HEAD sweeps) is best-effort and not exercised here.
"""

from services import qa_signals as sig
from services import qa_visual


# ---------------------------------------------------------------------------
# Asset extraction (qa_signals.asset_urls_of)
# ---------------------------------------------------------------------------
_HTML = """
<html><head>
<link rel="stylesheet" href="/assets/site.css">
<link rel="stylesheet" href="https://cdn.example.com/theme.css">
<link rel="icon" href="/favicon.ico">
</head><body>
<img src="/img/hero.jpg"><img src="hero2.jpg"><img src="/img/hero.jpg">
<img src="data:image/png;base64,AAAA"><img src="">
</body></html>
"""


def test_asset_urls_absolutized_deduped_and_filtered():
    out = sig.asset_urls_of(_HTML, "https://acme.com/services/roofing")
    assert out["stylesheets"] == [
        "https://acme.com/assets/site.css",
        "https://cdn.example.com/theme.css",
    ]
    # Relative resolves against the page URL; dupes + data: + empty skipped;
    # the icon link is not a stylesheet.
    assert out["images"] == [
        "https://acme.com/img/hero.jpg",
        "https://acme.com/services/hero2.jpg",
    ]


def test_asset_urls_cap_prefers_stylesheets():
    many_imgs = "".join(f'<img src="/i{n}.jpg">' for n in range(20))
    html = '<link rel="stylesheet" href="/a.css">' + many_imgs
    out = sig.asset_urls_of(html, "https://x.com", cap=3)
    assert out["stylesheets"] == ["https://x.com/a.css"]
    assert len(out["images"]) == 2  # cap 3 total, stylesheet first


def test_asset_urls_empty_and_no_base():
    assert sig.asset_urls_of("", "https://x.com") == {"stylesheets": [], "images": []}
    # No base URL → relative srcs can't absolutize and are dropped, absolute kept.
    out = sig.asset_urls_of('<img src="/a.jpg"><img src="https://y.com/b.jpg">', "")
    assert out["images"] == ["https://y.com/b.jpg"]


# ---------------------------------------------------------------------------
# Screenshot response parsing
# ---------------------------------------------------------------------------
def test_screenshot_url_from_response_standard_shape():
    data = {"tasks": [{"result": [{"items": [{"image": "https://cdn.dataforseo.com/x.png"}]}]}]}
    assert qa_visual.screenshot_url_from_response(data) == "https://cdn.dataforseo.com/x.png"


def test_screenshot_url_from_response_alternate_key_and_garbage():
    data = {"tasks": [{"result": [{"items": [{"screenshot_url": "https://cdn/x.png"}]}]}]}
    assert qa_visual.screenshot_url_from_response(data) == "https://cdn/x.png"
    assert qa_visual.screenshot_url_from_response({}) is None
    assert qa_visual.screenshot_url_from_response(None) is None
    assert qa_visual.screenshot_url_from_response({"tasks": [{"result": None}]}) is None
    # A non-URL value in the expected key is rejected.
    bad = {"tasks": [{"result": [{"items": [{"image": "not-a-url"}]}]}]}
    assert qa_visual.screenshot_url_from_response(bad) is None


# ---------------------------------------------------------------------------
# Vision verdict parsing + mapping
# ---------------------------------------------------------------------------
def test_parse_visual_verdict_happy_and_hardening():
    v = qa_visual.parse_visual_verdict(
        'Here you go: {"broken": true, "confidence": "high", "issues": ["overlapping nav"]}'
    )
    assert v == {"broken": True, "confidence": "high", "issues": ["overlapping nav"]}
    # Unknown confidence coerces to low; issues clipped to strings.
    v2 = qa_visual.parse_visual_verdict('{"broken": false, "confidence": "medium"}')
    assert v2 == {"broken": False, "confidence": "low", "issues": []}
    assert qa_visual.parse_visual_verdict("no json here") is None
    assert qa_visual.parse_visual_verdict('{"broken": "yes"}') is None  # non-bool
    assert qa_visual.parse_visual_verdict(None) is None


def test_verdict_to_ok_mapping():
    ok, _ = qa_visual.verdict_to_ok({"broken": False, "confidence": "low", "issues": []})
    assert ok is True
    ok, note = qa_visual.verdict_to_ok(
        {"broken": True, "confidence": "high", "issues": ["raw unstyled HTML"]}
    )
    assert ok is False and "raw unstyled HTML" in note
    # Low-confidence broken is fail-open (needs_human), never a bounce.
    ok, note = qa_visual.verdict_to_ok({"broken": True, "confidence": "low", "issues": []})
    assert ok is None and "low confidence" in note
    assert qa_visual.verdict_to_ok(None) == (None, "visual judge returned no verdict")


def test_high_confidence_broken_bounces_in_the_fold():
    """End-to-end through the deterministic verdict fold: a high-confidence
    visual break is a blocking FAIL; a capture failure is NEEDS_HUMAN."""
    broken_check = {"key": "visual_render", "label": "Page renders", "ok": False,
                    "blocking": True, "note": "visually broken"}
    fine = sig._check("meta_title", "Meta title present", True)
    assert sig.build_verdict([fine, broken_check])["verdict"] == sig.FAIL
    unavailable = {"key": "visual_render", "label": "Page renders", "ok": None,
                   "blocking": True, "note": "screenshot unavailable"}
    assert sig.build_verdict([fine, unavailable])["verdict"] == sig.NEEDS_HUMAN
