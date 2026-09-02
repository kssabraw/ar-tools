"""Unit tests for the pure page-spec core (plan: docs/modules/local-seo-page-spec-plan-v1_0.md).

Covers the page band (SERP vs fallback + sanity flags), reference validation,
folding heading-only rows, intent→template-key mapping, band allocation (sums
close on the absorber, clamps hold), feasibility validation, per-section
measurement of a generated page, and the length verdict. No I/O, no LLM."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import page_spec as ps  # noqa: E402


def _ref(outline, url="https://www.example.com/it-support/", status="complete"):
    return {"url": url, "status": status, "analyzed_at": "2026-08-13T00:00:00+00:00",
            "analysis": {"outline": outline, "elements": {}}}


def _row(level, heading, intent, words, blocks=None):
    return {"level": level, "heading": heading, "intent": intent, "intent_note": "", "word_count": words,
            "blocks": blocks if blocks is not None else ([{"type": "paragraph", "count": 1, "words": words}] if words else [])}


# A compact stand-in for the Wheelhouse local landing reference: real prose
# sections, a heading-only industry list, two CTAs, no FAQ.
_WHEELHOUSE_LIKE = [
    _row("H1", "Primary Service Headline", "hero", 0, []),
    _row("H2", "Response Time Performance Metrics", "trust", 57),
    _row("H2", "Key Differentiators and Local Presence", "value_prop", 114),
    _row("H2", "Recurring Problem Pattern Introduction", "objection", 53),
    _row("H3", "Identity and Access Problem", "objection", 35),
    _row("H3", "Application Failure Problem", "objection", 29),
    _row("H2", "Provider Delivery Standards", "service_detail", 159),
    _row("H2", "Industry Coverage Overview Heading", "coverage", 0, []),
    _row("H3", "Architecture Industry", "coverage", 0, []),
    _row("H3", "Aviation Industry", "coverage", 0, []),
    _row("H3", "Construction Industry", "coverage", 0, []),
    _row("H3", "Regulatory Compliance Expertise", "service_detail", 16),
    _row("H2", "Security Stack and Coverage Gaps", "service_detail", 162),
    _row("H2", "Free Assessment Offer Heading", "cta", 0, []),
    _row("H3", "Assessment Value Statement", "cta", 0, []),
    _row("H2", "Reasons Businesses Switch Providers", "trust", 126),
    _row("H2", "Local Office Contact Information", "about", 15, [{"type": "list", "count": 1, "items": 3, "words": 15}]),
    _row("H2", "Contact and Consultation Invitation", "cta", 45),
    _row("H2", "Additional Services Navigation Heading", "other", 0, []),
]
_SERP = {"keyword": "it support fort lauderdale", "location": "Fort Lauderdale", "serp_word_target": 1058,
         "serp_avg_word_count": 882, "serp_urls": ["a"] * 15}


# ── page band ───────────────────────────────────────────────────────────────

def test_page_band_from_serp():
    total, prov, flags = ps.page_band(_SERP, 1200)
    assert total == {"min": 882, "target": 1058, "max": 1164, "basis": "serp"}
    assert prov["competitor_pages"] == 15 and prov["target"] == 1058
    assert flags == []


def test_page_band_falls_back_when_serp_missing_or_suspect():
    total, _, flags = ps.page_band(None, 1200)
    assert total["basis"] == "fallback" and total["target"] == 1200 and "serp_target_missing" in flags
    assert total["min"] == 1000 and total["max"] == 1320
    total, _, flags = ps.page_band({"serp_word_target": 4000, "serp_urls": ["a"] * 10}, 1200)
    assert total["basis"] == "fallback" and "serp_target_suspect" in flags
    total, _, flags = ps.page_band({"serp_word_target": 1300, "serp_urls": ["a", "b"]}, 1200)
    assert total["basis"] == "fallback" and "serp_too_few_pages" in flags


# ── reference validation ────────────────────────────────────────────────────

def test_reference_usable_rejects_staging_thin_and_incomplete():
    assert ps.reference_usable(_ref(_WHEELHOUSE_LIKE)) == (True, None)
    assert ps.reference_usable(_ref(_WHEELHOUSE_LIKE, url="https://www.staging3.firstclassroofing.com.au/"))[1] == "staging_host"
    assert ps.reference_usable(_ref([_row("H2", "a", "hero", 30)] * 9))[1] == "too_short"
    assert ps.reference_usable(_ref([_row("H2", "a", "hero", 400)]))[1] == "too_few_sections"
    assert ps.reference_usable(_ref(_WHEELHOUSE_LIKE, status="pending"))[1] == "status_pending"
    assert ps.reference_usable(None)[1] == "no_reference"


# ── fold + map ──────────────────────────────────────────────────────────────

def test_fold_outline_folds_heading_only_children_into_a_list_block():
    groups = ps.fold_outline(_WHEELHOUSE_LIKE)
    industries = next(g for g in groups if g["heading"].startswith("Industry Coverage"))
    assert industries["words"] == 16          # only the compliance H3 carried prose
    assert industries["subsections"] == 1
    assert industries["folded_headings"] == 3
    assert {"type": "list", "count": 1, "items": 3, "words": 0, "folded": True} in industries["blocks"]
    # a pure heading with nothing under it is dropped
    assert not any(g["heading"].startswith("Additional Services") for g in groups)
    # the H1 hero with zero words survives (it is a group, not a child)
    assert groups[0]["level"] == "H1"


def test_map_to_template_assigns_keys_by_intent_and_merges_absorber():
    secs = ps.map_to_template(ps.fold_outline(_WHEELHOUSE_LIKE))
    keys = [s["key"] for s in secs]
    assert keys[0] == "intro"
    assert "usp" in keys and "cta-primary" in keys and "cta-secondary" in keys
    assert keys.count("services") == 1
    services = next(s for s in secs if s["key"] == "services")
    # objection (53+35+29) + service_detail (159 + 162) merged, plus the third
    # value-prop section ("Reasons Businesses Switch", 126) overflowing into the
    # body once usp and features are taken
    assert services["words"] == 53 + 35 + 29 + 159 + 162 + 126
    assert services["subsections"] >= 3
    # prose "trust" sections are value-prop copy, not testimonials: the first
    # takes usp, the second features; a real testimonials slot needs quotes
    assert "testimonials" not in keys
    usp = next(s for s in secs if s["key"] == "usp")
    assert usp["heading"] == "Response Time Performance Metrics"
    # tiny stubs (the 15-word NAP list, the empty nav heading) are dropped
    assert not any(s["key"].startswith("ref-local-office") for s in secs)
    assert not any(s["key"].startswith("ref-additional") for s in secs)


def test_map_to_template_routes_real_reviews_to_testimonials():
    groups = ps.fold_outline([
        _row("H2", "What Our Clients Say", "trust", 60, [{"type": "quote", "count": 3, "words": 60}]),
        _row("H2", "Why Choose Us", "value_prop", 100),
    ])
    keys = [s["key"] for s in ps.map_to_template(groups)]
    assert keys == ["testimonials", "usp"]


def test_ensure_required_inserts_missing_faq_in_template_order():
    secs = ps.ensure_required(ps.map_to_template(ps.fold_outline(_WHEELHOUSE_LIKE)))
    keys = [s["key"] for s in secs]
    assert "faq" in keys and keys[-1] == "faq"
    assert "getting-started" in keys
    tmpl_positions = [keys.index(k) for k in ps.TEMPLATE_KEYS if k in keys]
    assert tmpl_positions == sorted(tmpl_positions)
    # extras sit before the FAQ
    assert all(keys.index(k) < keys.index("faq") for k in keys if k.startswith("ref-"))


# ── allocation + validation ─────────────────────────────────────────────────

def test_allocate_bands_closes_on_the_absorber_and_respects_clamps():
    # template mode (the override off): the reference is mapped onto the skeleton
    spec = ps.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                         reference_entry=_ref(_WHEELHOUSE_LIKE), reference_page_type="local_landing",
                         fallback_target=1200, client_structure_overrides=False)
    assert spec["structure_mode"] == "template"
    assert spec["validation_errors"] == []
    secs = {s["key"]: s for s in spec["sections"]}
    assert sum(s["min_words"] for s in spec["sections"]) <= spec["total"]["max"]
    assert sum(s["max_words"] for s in spec["sections"]) >= spec["total"]["min"]
    for key in ("cta-primary", "cta-secondary"):
        assert 30 <= secs[key]["min_words"] < secs[key]["max_words"] <= 80
    assert secs["intro"]["max_words"] <= 160
    assert secs["faq"]["min_words"] >= 4 * 40
    assert secs["services"]["min_words"] >= 200
    # the sums close exactly on the page band (the absorber takes the residual)
    assert sum(s["min_words"] for s in spec["sections"]) == spec["total"]["min"]
    assert sum(s["max_words"] for s in spec["sections"]) == spec["total"]["max"]
    # bands are bands, not points
    assert all(s["max_words"] > s["min_words"] for s in spec["sections"] if s["required"])
    assert secs["services"]["subsections"]["min"] == 3
    assert all(s["min_words"] <= s["max_words"] for s in spec["sections"])


def test_build_spec_without_reference_uses_template_weights():
    spec = ps.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                         reference_entry=None, reference_page_type=None, fallback_target=1200)
    assert spec["validation_errors"] == []
    assert spec["provenance"]["reference"] == {"page_type": None, "url": None, "analyzed_at": None,
                                               "total_words": None, "usable": False, "reason": "no_reference"}
    keys = [s["key"] for s in spec["sections"]]
    assert keys == [k for k in ps.TEMPLATE_KEYS if ps._template(k)["required"]]
    assert all(s["source"] == "template" for s in spec["sections"])


def test_validate_spec_flags_infeasible_sums_and_missing_required():
    spec = ps.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                         reference_entry=None, reference_page_type=None, fallback_target=1200)
    bad = {**spec, "sections": [dict(s, min_words=900) for s in spec["sections"]]}
    assert "section_minimums_exceed_page_max" in ps.validate_spec(bad)
    bad = {**spec, "sections": [s for s in spec["sections"] if s["key"] != "faq"]}
    assert "missing_required:faq" in ps.validate_spec(bad)
    bad = {**spec, "total": {"min": 1200, "target": 1000, "max": 900, "basis": "serp"}}
    assert "total_band_invalid" in ps.validate_spec(bad)


# ── measurement + verdict ───────────────────────────────────────────────────

def _page(words_by_key):
    parts = []
    for key, n in words_by_key.items():
        parts.append(f'<section id="{key}"><h2>{key}</h2><p>' + " ".join(["w"] * n) + "</p></section>")
    return "<article>" + "".join(parts) + "</article>"


def test_measure_page_reports_per_section_status_and_unknowns():
    spec = ps.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                         reference_entry=None, reference_page_type=None, fallback_target=1200)
    bands = {s["key"]: s for s in spec["sections"]}
    html = _page({"intro": bands["intro"]["max_words"] + 50, "usp": bands["usp"]["min_words"], "bonus": 30})
    m = ps.measure_page(html, spec)
    by = {r["key"]: r for r in m["sections"]}
    assert by["intro"]["status"] == "over" and by["usp"]["status"] == "ok"
    assert m["unknown_sections"] == ["bonus"]
    assert "faq" in m["missing_required"]
    assert m["total_words"] == bands["intro"]["max_words"] + 50 + bands["usp"]["min_words"] + 30


def test_length_verdict_bands_and_ceiling():
    spec = ps.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                         reference_entry=None, reference_page_type=None, fallback_target=1200)
    t = spec["total"]
    v = ps.length_verdict({"total_words": t["target"], "sections": [], "section_count": 8, "max_h3_per_h2": 2}, spec)
    assert v["status"] == "in_band" and not v["over_ceiling"]
    v = ps.length_verdict({"total_words": t["max"] + 1, "sections": [{"key": "services", "status": "over"}],
                           "section_count": 8, "max_h3_per_h2": 9}, spec)
    assert v["status"] == "over_length" and v["over_sections"] == ["services"] and "max_h3_per_h2" in v["cap_breaches"]
    assert v["ceiling_words"] == int(round(t["max"] * ps.CEILING_MULTIPLIER))
    v = ps.length_verdict({"total_words": 3000, "sections": [], "section_count": 8, "max_h3_per_h2": 1}, spec)
    assert v["over_ceiling"]
    v = ps.length_verdict({"total_words": t["min"] - 1, "sections": [], "section_count": 8, "max_h3_per_h2": 1}, spec)
    assert v["status"] == "under_length"


def test_render_spec_block_carries_keys_bands_and_caps():
    spec = ps.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                         reference_entry=_ref(_WHEELHOUSE_LIKE), reference_page_type="local_landing",
                         fallback_target=1200, client_structure_overrides=False)
    block = ps.render_spec_block(spec)
    assert "882–1164 words" in block
    assert "[intro]" in block and "[faq]" in block and "[services]" in block
    assert "HARD CEILING" in block
    assert "H3s under any H2" in block
    assert "STRUCTURE MODE: CLIENT" not in block
    client = ps.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                           reference_entry=_ref(_WHEELHOUSE_LIKE), reference_page_type="local_landing",
                           fallback_target=1200)
    block = ps.render_spec_block(client)
    assert "STRUCTURE MODE: CLIENT" in block and "REPLACES the template" in block
    assert "[faq]" not in block and "[ref-recurring-problem-pattern-introduction]" in block


# ── client-first structure (the reference overrides the template) ───────────

def test_client_mode_keeps_the_clients_sections_and_order_and_inserts_nothing():
    spec = ps.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                         reference_entry=_ref(_WHEELHOUSE_LIKE), reference_page_type="local_landing",
                         fallback_target=1200)
    assert spec["structure_mode"] == "client" and spec["validation_errors"] == []
    keys = [s["key"] for s in spec["sections"]]
    # client order, not template order: the CTA sits where the client put it,
    # the two service bodies stay separate, objections keep their own section
    assert keys == ["intro", "usp", "features", "ref-recurring-problem-pattern-introduction", "services", "local",
                    "ref-security-stack-and-coverage-gaps", "cta-primary", "ref-reasons-businesses-switch-providers",
                    "cta-secondary"]
    # no template section the client lacks is inserted — it is only recorded
    assert "faq" not in keys and "getting-started" not in keys
    assert "client_structure_omits:getting-started,faq" in spec["provenance"]["flags"]
    secs = {s["key"]: s for s in spec["sections"]}
    assert all(s["source"] == "reference" for s in spec["sections"])
    assert secs["ref-recurring-problem-pattern-introduction"]["intent"] == "objection"
    assert secs["ref-recurring-problem-pattern-introduction"]["subsections"] == {"min": 1, "max": 3}
    assert secs["ref-recurring-problem-pattern-introduction"]["heading_pattern"].startswith("Recurring Problem Pattern")
    # the client's proportions rule the bands (no template floor on a prose section)
    assert secs["local"]["max_words"] < 60 and secs["local"]["items"] == {"min": 2, "max": 5}
    assert secs["services"]["min_words"] < 200
    # a folded single sub-heading is not a list block on the CTA
    assert [b["type"] for b in secs["cta-primary"]["blocks"]] == ["cta"]
    # bands are bands and the sums close on the page band
    assert all(s["max_words"] > s["min_words"] for s in spec["sections"])
    assert sum(s["max_words"] for s in spec["sections"]) == spec["total"]["max"]
    assert sum(s["min_words"] for s in spec["sections"]) <= spec["total"]["max"]


def test_client_mode_h1_always_takes_intro_and_reviews_take_testimonials():
    outline = [
        _row("H1", "Big Promise", "other", 40),
        _row("H2", "What Our Clients Say", "trust", 90, [{"type": "quote", "count": 3, "words": 90}]),
        _row("H2", "How It Works", "process", 120),
        _row("H2", "Areas We Cover", "coverage", 110),
        _row("H2", "Questions", "faq", 220, [{"type": "faq", "count": 1, "items": 5, "words": 220}]),
    ]
    spec = ps.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                         reference_entry=_ref(outline), reference_page_type="local_landing", fallback_target=1200)
    keys = [s["key"] for s in spec["sections"]]
    assert keys == ["intro", "testimonials", "getting-started", "local", "faq"]
    faq = next(s for s in spec["sections"] if s["key"] == "faq")
    assert faq["items"] == {"min": 4, "max": 7} and faq["min_words"] >= 160
    assert spec["validation_errors"] == []
    assert not any(f.startswith("client_structure_omits") and "faq" in f for f in spec["provenance"]["flags"])


def test_client_mode_verdict_treats_a_template_section_the_client_lacks_as_drift():
    spec = ps.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                         reference_entry=_ref(_WHEELHOUSE_LIKE), reference_page_type="local_landing",
                         fallback_target=1200)
    html = _conforming_page(spec, extra='<section id="faq"><h2>FAQ</h2><h3>Q?</h3><p>a a a a</p></section>')
    v = ps.structure_verdict(ps.measure_page(html, spec), spec)
    faq = [i for i in v["issues"] if i["code"] == "unexpected_section"]
    assert faq and faq[0]["advisory"] is False and v["status"] == "drift"
    # the same page without the extra is clean
    assert ps.structure_verdict(ps.measure_page(_conforming_page(spec), spec), spec)["status"] == "ok"


def test_validate_spec_client_mode_requires_only_the_intro():
    spec = ps.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                         reference_entry=_ref(_WHEELHOUSE_LIKE), reference_page_type="local_landing",
                         fallback_target=1200)
    assert ps.validate_spec(spec) == []
    no_intro = dict(spec, sections=[s for s in spec["sections"] if s["key"] != "intro"])
    assert ps.validate_spec(no_intro) == ["missing_required:intro"]


def _conforming_page(spec, omit=(), bodies=None, extra=""):
    bodies = bodies or {}
    parts = []
    for s in spec["sections"]:
        if s["key"] in omit:
            continue
        if s["key"] in bodies:
            body = bodies[s["key"]]
        elif s["key"] == "faq":
            body = "<h2>FAQ</h2>" + "".join(f"<h3>Q{i}?</h3><p>" + " ".join(["a"] * 32) + "</p>" for i in range(5))
        elif s.get("subsections"):
            n_sub = s["subsections"]["min"]
            per = max(1, s["min_words"] // n_sub)
            body = "<h2>s</h2>" + "".join(f"<h3>Sub {i}</h3><p>" + " ".join(["s"] * per) + "</p>" for i in range(n_sub))
            if any(b.get("type") == "list" for b in s.get("blocks") or []):
                body += "<ul>" + "".join(f"<li>item {i}</li>" for i in range((s.get("items") or {}).get("min", 4))) + "</ul>"
        elif any(b.get("type") == "list" for b in s.get("blocks") or []):
            n_items = (s.get("items") or {}).get("min", 4)
            body = "<h2>h</h2><ul>" + "".join(f"<li>item {i}</li>" for i in range(n_items)) + "</ul><p>" + " ".join(["w"] * s["min_words"]) + "</p>"
        else:
            body = "<h2>h</h2><p>" + " ".join(["w"] * s["min_words"]) + "</p>"
        parts.append(f'<section id="{s["key"]}">{body}</section>')
    return "<article>" + "".join(parts) + extra + "</article>"


def test_structure_verdict_ok_on_a_conforming_page_and_names_each_drift():
    spec = ps.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                         reference_entry=None, reference_page_type=None, fallback_target=1200)
    ok = ps.structure_verdict(ps.measure_page(_conforming_page(spec), spec), spec)
    assert ok["status"] == "ok" and ok["issues"] == [] and ok["order_ok"] and ok["audited"] is False
    # missing cta-primary + faq with 2 entries + features without its list + services with 8 H3s
    faq2 = "<h2>FAQ</h2>" + "".join(f"<h3>Q{i}?</h3><p>" + " ".join(["a"] * 80) + "</p>" for i in range(2))
    svc8 = "<h2>s</h2>" + "".join(f"<h3>Sub {i}</h3><p>" + " ".join(["s"] * 30) + "</p>" for i in range(8))
    feat = "<h2>h</h2><p>" + " ".join(["w"] * 90) + "</p>"
    html = _conforming_page(spec, omit=("cta-primary",), bodies={"faq": faq2, "services": svc8, "features": feat})
    v = ps.structure_verdict(ps.measure_page(html, spec), spec)
    codes = {(i["key"], i["code"]) for i in v["issues"]}
    assert ("cta-primary", "missing_required") in codes
    assert ("faq", "items_low") in codes
    assert ("features", "block_missing") in codes and ("features", "items_low") in codes
    assert ("services", "subsections_high") in codes and ("services", "cap_max_h3_per_h2") in codes
    assert v["status"] == "drift" and v["missing_required"] == ["cta-primary"]
    assert v["section_keys_to_fix"] == ["faq", "features", "services"]
    corrections = ps.structure_corrections(v)
    assert corrections.startswith("- ") and "[faq] has 2 entries" in corrections
    # out of spec order → an order issue, and the audit merges per section
    swapped = _conforming_page(spec).replace('<section id="intro">', '<section id="intro-tmp">')
    swapped = swapped.replace('<section id="usp">', '<section id="intro">', 1).replace('<section id="intro-tmp">', '<section id="usp">', 1)
    v2 = ps.structure_verdict(ps.measure_page(swapped, spec), spec,
                              audit={"local": {"intent_ok": True, "sentiment": "negative", "note": "gloomy"},
                                     "faq": {"intent_ok": False, "sentiment": "positive", "note": "no real questions"}})
    codes2 = {(i["key"], i["code"]) for i in v2["issues"]}
    assert (None, "order") in codes2 and ("local", "sentiment") in codes2 and ("faq", "intent_drift") in codes2
    assert v2["audited"] is True and not v2["order_ok"]
