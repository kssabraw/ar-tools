"""Unit tests for the deterministic Trust & Proof block on local landing pages
(`main._build_trust_block` + `main._inject_trust_block` + `main._norm_badges`).

Covers the four elements that are injected rather than LLM-authored — the trust
badge strip, the GBP aggregate-rating badge, financing logos, and the media
gallery — plus independent graceful degradation (a missing field omits only its
element), the empty-when-nothing case, HTML escaping, and the idempotent,
article-aware injection. Also asserts the shared _GEN_SYSTEM_PROMPT carries the
new trust conditionals so a prompt refactor can't silently drop them. Pure +
offline — no network, no Anthropic. Run with `pytest writer/nlp-api/tests/`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


CERTS = [{"name": "BBB Accredited", "logo_url": "https://cdn.example/bbb.png"}]
AFFIL = [{"name": "Master Plumbers Association", "logo_url": ""}]
FIN = [{"name": "Wisetack", "logo_url": "https://cdn.example/wisetack.png"}]
ASSETS = [
    {"kind": "team_photo", "url": "https://cdn.example/team.jpg", "caption": "Our crew"},
    {"kind": "video_embed", "url": "https://youtube.com/embed/abc", "caption": ""},
]


# ── _norm_badges ─────────────────────────────────────────────────────────────

def test_norm_badges_coerces_strings_and_dicts_and_drops_empty():
    out = main._norm_badges(["BBB", {"name": "Angi", "logo": "x.png"}, {}, {"logo_url": "y.png"}])
    names = [b["name"] for b in out]
    assert "BBB" in names            # bare string → {name}
    assert "Angi" in names           # dict, `logo` alias picked up
    assert {"name": "", "logo_url": "y.png"} in out  # logo-only kept
    assert all(b.get("name") or b.get("logo_url") for b in out)  # fully-empty dropped
    assert main._norm_badges(None) == []
    assert main._norm_badges("BBB") == []  # non-list ignored


# ── _build_trust_block ───────────────────────────────────────────────────────

def test_full_block_has_all_four_elements():
    block = main._build_trust_block(
        certifications=CERTS, affiliations=AFFIL, financing_partners=FIN,
        gbp_rating=4.9, gbp_review_count=132, assets=ASSETS,
    )
    assert f'id="{main._TRUST_BLOCK_ID}"' in block
    # Badge strip (certs + affiliations)
    assert "cdn.example/bbb.png" in block
    assert "BBB Accredited" in block
    assert "Master Plumbers Association" in block  # affiliation with no logo → name span
    # Aggregate rating badge
    assert "4.9" in block
    assert "132 Google reviews" in block
    assert "trust-rating" in block
    # Financing logos
    assert "cdn.example/wisetack.png" in block
    assert "Financing available" in block
    # Media gallery
    assert "cdn.example/team.jpg" in block
    assert "Our crew" in block
    assert '<iframe src="https://youtube.com/embed/abc"' in block  # video_embed


def test_each_element_renders_independently():
    only_rating = main._build_trust_block(gbp_rating=5.0, gbp_review_count=1)
    assert "5" in only_rating
    assert "1 Google review" in only_rating  # singular
    assert "<img" not in only_rating         # no badges/financing/gallery

    only_badges = main._build_trust_block(certifications=CERTS)
    assert "cdn.example/bbb.png" in only_badges
    assert "trust-rating" not in only_badges
    assert "Financing" not in only_badges


def test_zero_or_missing_rating_omits_rating_badge():
    assert "trust-rating" not in main._build_trust_block(gbp_rating=0, gbp_review_count=5)
    assert "trust-rating" not in main._build_trust_block(gbp_rating=None)
    assert "trust-rating" not in main._build_trust_block(gbp_rating="not-a-number")


def test_rating_without_review_count_omits_count():
    block = main._build_trust_block(gbp_rating=4.7)
    assert "4.7" in block
    assert "Google review" not in block


def test_video_embed_requires_http_scheme():
    # An iframe src is a script sink; a non-http(s) scheme (or malformed value)
    # must be dropped, not escaped-and-embedded.
    bad = main._build_trust_block(assets=[
        {"kind": "video_embed", "url": "javascript:alert(1)", "caption": "x"},
        {"kind": "video_embed", "url": "/relative/path"},
    ])
    assert bad == ""  # both dropped → nothing renderable
    ok = main._build_trust_block(assets=[
        {"kind": "video_embed", "url": "https://youtube.com/embed/ok"},
    ])
    assert '<iframe src="https://youtube.com/embed/ok"' in ok
    assert "javascript:" not in ok


def test_asset_without_url_is_skipped():
    block = main._build_trust_block(assets=[{"kind": "team_photo", "url": ""}, {"kind": "other"}])
    assert block == ""  # nothing renderable → empty


def test_no_data_returns_empty():
    assert main._build_trust_block() == ""
    assert main._build_trust_block(certifications=[], affiliations=[], assets=[]) == ""


def test_badge_name_is_html_escaped():
    block = main._build_trust_block(certifications=[{"name": "A & B <Cert>", "logo_url": ""}])
    assert "A &amp; B &lt;Cert&gt;" in block
    assert "<Cert>" not in block


def test_license_number_not_rendered_in_block():
    # license_number is a §10 narrative fact, accepted for signature parity only.
    block = main._build_trust_block(certifications=CERTS, license_number="CCC1234567")
    assert "CCC1234567" not in block


# ── _inject_trust_block ──────────────────────────────────────────────────────

def test_inject_inserts_before_closing_article():
    html = "<article><section id='intro'><h1>Hi</h1></section></article>"
    out = main._inject_trust_block(html, certifications=CERTS)
    assert out.count(f'id="{main._TRUST_BLOCK_ID}"') == 1
    assert out.index(main._TRUST_BLOCK_ID) < out.rindex("</article>")


def test_inject_is_idempotent():
    html = "<article><section id='intro'></section></article>"
    once = main._inject_trust_block(html, certifications=CERTS)
    twice = main._inject_trust_block(once, certifications=CERTS)
    assert once == twice
    assert twice.count(f'id="{main._TRUST_BLOCK_ID}"') == 1


def test_inject_no_data_leaves_page_unchanged():
    html = "<article><section id='intro'></section></article>"
    assert main._inject_trust_block(html) == html


def test_inject_empty_html_returns_empty():
    assert main._inject_trust_block("", certifications=CERTS) == ""


# ── _GEN_SYSTEM_PROMPT carries the new conditionals ─────────────────────────

def test_gen_prompt_has_trust_conditionals():
    p = main._GEN_SYSTEM_PROMPT
    assert "years in business" in p.lower()          # §1
    assert "per-line-item pricing" in p.lower()       # §5
    assert "symptom-diagnosis" in p.lower()           # §6 comparison table
    assert "LICENSE NUMBER" in p                       # §10
    assert "TRUST-SIGNAL CONSISTENCY" in p             # cross-cutting rule
    assert "Trust & Proof" in p                        # §10 don't-hand-write note


def test_gen_prompt_content_gaps_has_new_categories():
    p = main._GEN_SYSTEM_PROMPT
    for cat in ("Years in Business", "License Number", "Guarantee/Warranty Terms"):
        assert cat in p
    assert "Trust badges" in p
    assert "Photo/video assets" in p
