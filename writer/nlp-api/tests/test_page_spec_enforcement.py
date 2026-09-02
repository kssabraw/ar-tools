"""Phase 2 of the page spec (docs/modules/local-seo-page-spec-plan-v1_0.md):
the vendored `page_spec.py` stays byte-identical to platform-api's (one
definition of the bands + measurement for the suite), and the pure halves of
the section-scoped trim + the length axis on the keep-best key. Offline."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
import page_spec as pspec  # noqa: E402

_HERE = Path(__file__).resolve()
_PLATFORM_COPY = _HERE.parents[2] / "platform-api" / "services" / "page_spec.py"
_VENDORED_COPY = _HERE.parents[1] / "page_spec.py"


def test_vendored_page_spec_matches_platform_api():
    """The spec's bands + measurement are defined ONCE for the suite: the nlp
    copy is vendored byte-identical (mirrors the voice_card.py precedent)."""
    if not _PLATFORM_COPY.exists():  # nlp-api checked out alone
        return
    assert _VENDORED_COPY.read_bytes() == _PLATFORM_COPY.read_bytes(), (
        "writer/nlp-api/page_spec.py has drifted from "
        "writer/platform-api/services/page_spec.py — re-copy it"
    )


_SERP = {"serp_word_target": 1058, "serp_avg_word_count": 882, "serp_urls": ["a"] * 15}


def _spec():
    return pspec.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                            reference_entry=None, reference_page_type=None, fallback_target=1200)


def _page(words_by_key):
    return "<article>" + "".join(
        f'<section id="{k}"><h2>{k}</h2><p>' + " ".join(["w"] * n) + "</p></section>"
        for k, n in words_by_key.items()
    ) + "</article>"


def test_spec_trim_targets_only_over_sections_worst_first():
    spec = _spec()
    bands = {s["key"]: s for s in spec["sections"]}
    html = _page({
        "intro": bands["intro"]["max_words"] + 40,
        "services": bands["services"]["max_words"] + 200,
        "usp": bands["usp"]["min_words"],
    })
    measure = pspec.measure_page(html, spec)
    targets = main._spec_trim_targets(measure, spec)
    assert [t["key"] for t in targets] == ["services", "intro"]
    assert targets[0]["cut"] == 200 and targets[1]["cut"] == 40
    assert targets[0]["max_words"] == bands["services"]["max_words"]


def test_spec_trim_targets_empty_when_nothing_over():
    spec = _spec()
    html = _page({s["key"]: s["min_words"] for s in spec["sections"]})
    assert main._spec_trim_targets(pspec.measure_page(html, spec), spec) == []


def test_spec_trim_prompt_names_budget_and_only_targeted_sections():
    import section_edit
    spec = _spec()
    bands = {s["key"]: s for s in spec["sections"]}
    html = _page({"intro": bands["intro"]["max_words"] + 40, "usp": 50})
    sections = section_edit.split_sections(html)
    targets = main._spec_trim_targets(pspec.measure_page(html, spec), spec)
    prompt = main._spec_trim_prompt(targets, sections, "Acme Roofing", "roof restoration", "Melbourne", "VOICE")
    assert "[intro]" in prompt and "[usp]" not in prompt
    assert f"max {bands['intro']['max_words']} words" in prompt
    assert "CUT at least ~40 words" in prompt
    assert "VOICE" in prompt and "Acme Roofing" in prompt


def test_spec_verdict_measures_before_injected_blocks_and_none_without_spec():
    spec = _spec()
    html = _page({s["key"]: s["min_words"] for s in spec["sections"]})
    v = main._spec_verdict(html, spec)
    assert v["status"] == "in_band" and "measure" in v
    assert main._spec_verdict(html, None) is None
    # the deterministic contact block is not authored content: it never counts
    with_block = html.replace("</article>", '<section id="contact-find-us"><p>' + " ".join(["x"] * 400) + "</p></section></article>")
    assert main._spec_verdict(with_block, spec)["total_words"] == v["total_words"]


def test_combined_rank_key_prefers_in_band_over_a_higher_score():
    # A pass that lifts SEO but pushes the page over its band ranks BELOW the
    # in-band state — the length axis sits right after voice criticals.
    voice = {"score": 85, "needs_rewrite": False, "critical_count": 0}
    in_band = main._combined_rank_key(80.0, voice, 90.0, length_ok=True)
    over = main._combined_rank_key(95.0, voice, 90.0, length_ok=False)
    assert in_band > over
    # no spec → length is not a bar → key identical to the pre-Phase-2 shape
    assert main._combined_rank_key(80.0, voice, 90.0) == main._combined_rank_key(80.0, voice, 90.0, length_ok=True)


def test_request_models_accept_page_spec():
    spec = _spec()
    g = main.GeneratePageRequest(keyword="k", location="L", business_name="B", gbp_category="Roofer",
                                 address="1 St", page_spec=spec)
    assert g.page_spec["total"]["target"] == 1058
    r = main.ReoptimizePageRequest(keyword="k", location="L", existing_page_html="<p>x</p>", deficiencies=[],
                                   business_name="B", gbp_category="Roofer")
    assert r.page_spec is None


# ── Phase 4: structure enforcement ───────────────────────────────────────────

import asyncio  # noqa: E402
import json  # noqa: E402
import section_edit  # noqa: E402


def _conforming_body(sec, words=None):
    """Inner HTML that satisfies one spec section's block composition + band."""
    n = words if words is not None else sec["min_words"]
    parts = [f"<h2>{sec['key']}</h2>"]
    if sec["key"] == "faq":
        count = (sec.get("items") or {}).get("min", 4)
        per = max(1, n // count)
        parts += [f"<h3>Question {i}?</h3><p>" + " ".join(["a"] * per) + "</p>" for i in range(count)]
        return "".join(parts)
    if sec.get("subsections"):
        count = sec["subsections"]["min"]
        per = max(1, n // count)
        parts += [f"<h3>Sub {i}</h3><p>" + " ".join(["s"] * per) + "</p>" for i in range(count)]
        return "".join(parts)
    for b in sec.get("blocks") or []:
        if b.get("type") == "list":
            count = (sec.get("items") or {}).get("min") or b.get("items") or 4
            parts.append("<ul>" + "".join(f"<li>item {i}</li>" for i in range(count)) + "</ul>")
            n -= 2 * count
        elif b.get("type") == "table":
            parts.append("<table><tr><td>x</td></tr></table>")
    parts.append("<p>" + " ".join(["w"] * max(1, n)) + "</p>")
    return "".join(parts)


def _full_page(spec, extra=None, omit=(), bodies=None):
    bodies = bodies or {}
    html = "<article>" + "".join(
        f'<section id="{s["key"]}">' + bodies.get(s["key"], _conforming_body(s)) + "</section>"
        for s in spec["sections"] if s["key"] not in omit
    )
    if extra:
        html += extra
    return html + "</article>"


def test_section_edit_insert_remove_reorder_are_deterministic():
    order = ["intro", "usp", "cta-primary", "features", "services", "local", "faq"]
    html = '<article><section id="faq"><h2>f</h2></section><section id="intro"><h1>i</h1></section><section id="zzz"><h2>z</h2></section></article>'
    out, changed = section_edit.reorder_sections(html, order)
    assert changed and [s["key"] for s in section_edit.split_sections(out)] == ["intro", "faq", "zzz"]
    assert section_edit.reorder_sections(out, order) == (out, False)
    out, inserted, skipped = section_edit.insert_sections(
        out, {"usp": "<h2>U</h2><p>u</p>", "local": "<h2>L</h2>", "intro": "<p>dup</p>", "features": ""}, order)
    assert inserted == ["usp", "local"] and set(skipped) == {"intro", "features"}
    assert [s["key"] for s in section_edit.split_sections(out)] == ["intro", "usp", "local", "faq", "zzz"]
    out, removed = section_edit.remove_sections(out, ["zzz", "nope"])
    assert removed == ["zzz"] and "zzz" not in out
    # a page with no sections at all: the new section lands in the article
    out, inserted, _ = section_edit.insert_sections("<article><p>x</p></article>", {"intro": "<h1>I</h1>"}, order)
    assert inserted == ["intro"] and '<section id="intro"><h1>I</h1></section>' in out


def test_parse_section_audit_normalises_and_drops_unknown_keys():
    raw = {"sections": [
        {"key": "intro", "intent_ok": True, "sentiment": "Positive", "note": ""},
        {"key": "cta-primary", "intent_ok": "false", "sentiment": "neutral", "note": "never asks for the call"},
        {"key": "nope", "intent_ok": False, "sentiment": "negative"},
        {"key": "faq", "intent_ok": "maybe", "sentiment": "upbeat"},
        "junk",
    ]}
    out = main._parse_section_audit(raw, ["intro", "cta-primary", "faq"])
    assert out["intro"] == {"intent_ok": True, "sentiment": "positive", "note": ""}
    assert out["cta-primary"]["intent_ok"] is False and out["cta-primary"]["sentiment"] == "neutral"
    assert "nope" not in out and "faq" not in out  # unjudgeable → not a verdict
    # bare list accepted too; garbage → {}
    assert main._parse_section_audit([{"key": "intro", "sentiment": "negative"}], ["intro"])["intro"]["sentiment"] == "negative"
    assert main._parse_section_audit("nonsense", ["intro"]) == {}


def test_structure_verdict_flags_sentiment_and_intent_strictly():
    spec = _spec()
    html = _full_page(spec)
    measure = pspec.measure_page(html, spec)
    audit = {"intro": {"intent_ok": True, "sentiment": "positive", "note": ""},
             "usp": {"intent_ok": True, "sentiment": "neutral", "note": "flat, uncommitted"},
             "cta-primary": {"intent_ok": False, "sentiment": "positive", "note": "never asks"}}
    v = pspec.structure_verdict(measure, spec, audit)
    codes = {(i["key"], i["code"]) for i in v["issues"]}
    assert ("usp", "sentiment") in codes and ("cta-primary", "intent_drift") in codes
    assert v["status"] == "drift" and v["section_keys_to_fix"] == ["cta-primary", "usp"]
    # neutral is NOT good enough — only positive passes
    assert not any(i["key"] == "intro" for i in v["issues"])


def test_structure_verdict_extras_advisory_under_cap_blocking_over():
    spec = _spec()
    extra = '<section id="areas"><h2>a</h2><p>' + " ".join(["w"] * 30) + "</p></section>"
    v = pspec.structure_verdict(pspec.measure_page(_full_page(spec, extra), spec), spec)
    unexpected = [i for i in v["issues"] if i["code"] == "unexpected_section"]
    assert unexpected and unexpected[0]["advisory"] is True
    assert v["status"] == "ok"  # harmless extra under the cap never blocks
    spec2 = dict(spec, structure=dict(spec["structure"], max_sections=len(spec["sections"])))
    many = "".join(f'<section id="x{i}"><h2>x</h2><p>w w w</p></section>' for i in range(3))
    v2 = pspec.structure_verdict(pspec.measure_page(_full_page(spec2, many), spec2), spec2)
    assert "cap_max_sections" in v2["issue_codes"] and v2["status"] == "drift"
    assert all(i["advisory"] is False for i in v2["issues"] if i["code"] == "unexpected_section")


def test_spec_fix_targets_carry_band_and_corrections_only_for_fixable_keys():
    spec = _spec()
    html = _full_page(spec, bodies={"faq": "<h2>FAQ</h2><p>" + " ".join(["w"] * 160) + "</p>"})
    measure = pspec.measure_page(html, spec)
    audit = {"usp": {"intent_ok": True, "sentiment": "negative", "note": "dwells on leaks"}}
    v = pspec.structure_verdict(measure, spec, audit)
    v["measure"] = measure
    # the FAQ has 0 entries here → items_low; faq + usp are the fix targets
    targets = {t["key"]: t for t in main._spec_fix_targets(v, spec)}
    assert "usp" in targets and "faq" in targets
    assert targets["usp"]["min_words"] > 0 and any("negative" in c for c in targets["usp"]["corrections"])
    prompt = main._spec_fix_prompt(list(targets.values()), section_edit.split_sections(html), "Acme", "k", "City", "555", "VOICE")
    assert "[usp]" in prompt and "CORRECTIONS:" in prompt and "PHONE: 555" in prompt and "VOICE" in prompt
    add_prompt = main._spec_add_prompt([s for s in spec["sections"] if s["key"] == "cta-primary"],
                                       section_edit.split_sections(html), "Acme", "k", "City", "555", "1 St", "")
    assert "[cta-primary]" in add_prompt and "ADDRESS: 1 St" in add_prompt and "MISSING SECTIONS TO WRITE" in add_prompt


class _Msg:
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()


class _ScriptedClient:
    """Answers each create() by the system prompt it was called with."""
    def __init__(self, handlers):
        self.handlers, self.calls = handlers, []
        self.messages = self

    async def create(self, **kw):
        system = kw["system"][0]["text"]
        self.calls.append(system[:40])
        for needle, fn in self.handlers.items():
            if needle in system:
                return _Msg(fn(kw["messages"][0]["content"]))
        raise AssertionError("unexpected call")


class _Q:
    async def put(self, _):
        pass


def test_enforce_spec_structure_writes_missing_fixes_sentiment_and_reorders():
    spec = _spec()
    bands = {s["key"]: s for s in spec["sections"]}
    # page: cta-primary MISSING, faq before intro (order), usp negative in the audit
    keys = [s["key"] for s in spec["sections"] if s["key"] != "cta-primary"]
    keys.remove("faq"); keys.insert(0, "faq")
    html = "<article>" + "".join(
        f'<section id="{k}">' + _conforming_body(bands[k]) + "</section>" for k in keys
    ) + "</article>"
    state = {"audits": 0}

    def audit(_prompt):
        state["audits"] += 1
        # first read: usp negative; after the fix pass: everything positive
        sent = "negative" if state["audits"] == 1 else "positive"
        return json.dumps({"sections": [{"key": k, "intent_ok": True, "sentiment": (sent if k == "usp" else "positive"),
                                         "note": ""} for k in bands]})

    def add(_prompt):
        n = bands["cta-primary"]["min_words"]
        return json.dumps({"cta-primary": "<h2>Book now</h2><p>" + " ".join(["c"] * n) + "</p>"})

    def fix(prompt):
        out = {}
        if "[usp]" in prompt:
            out["usp"] = "<h2>usp</h2><p>" + " ".join(["u"] * bands["usp"]["min_words"]) + "</p>"
        return json.dumps(out)

    client = _ScriptedClient({"auditing the body sections": audit, "MISSING": add, "REWRITING specific sections": fix})
    new_html, tok, verdict, changed = asyncio.run(main._enforce_spec_structure(
        html, spec, _Q(), keyword="k", city="City", business_name="Acme", phone="555", address="1 St",
        voice_block="", serp_analysis_dict=None, client=client, label="t"))
    assert changed and verdict["status"] == "ok", verdict["issues"]
    order = [s["key"] for s in section_edit.split_sections(new_html)]
    assert order == [s["key"] for s in spec["sections"] if s["key"] in set(order)]
    assert "cta-primary" in order and "Book now" in new_html
    assert verdict["audit"]["usp"]["sentiment"] == "positive"
    assert tok["input_tokens"] > 0


def test_enforce_spec_structure_keeps_previous_when_a_pass_does_not_improve():
    spec = _spec()
    html = _full_page(spec, bodies={"faq": "<h2>FAQ</h2><p>" + " ".join(["w"] * 160) + "</p>"})  # 0 entries → items_low

    def audit(_):
        return json.dumps({"sections": []})

    def fix(_):  # returns a faq that is STILL empty of entries → no improvement
        return json.dumps({"faq": "<h2>FAQ</h2><p>still prose</p>"})

    client = _ScriptedClient({"auditing the body sections": audit, "REWRITING specific sections": fix})
    new_html, _tok, verdict, changed = asyncio.run(main._enforce_spec_structure(
        html, spec, _Q(), keyword="k", city="C", business_name="A", phone=None, address=None,
        voice_block="", serp_analysis_dict=None, client=client, label="t"))
    assert not changed and new_html == html and verdict["status"] == "drift"
    assert "items_low" in verdict["issue_codes"]
    # no spec → untouched, no calls
    out = asyncio.run(main._enforce_spec_structure(html, None, _Q(), keyword="k", city="C", business_name="A",
                                                   phone=None, address=None, voice_block="", serp_analysis_dict=None,
                                                   client=_ScriptedClient({}), label="t"))
    assert out[2] is None and out[3] is False


def test_final_structure_verdict_reaudits_only_when_the_page_changed():
    spec = _spec()
    html = _full_page(spec)
    prior = {"status": "ok", "issues": [], "audit": {}}
    client = _ScriptedClient({"auditing the body sections": lambda _: json.dumps({"sections": [
        {"key": "intro", "intent_ok": True, "sentiment": "negative", "note": "gloomy"}]})})
    same, tok = asyncio.run(main._final_structure_verdict(html, spec, html, prior, keyword="k", city="C",
                                                          business_name="A", client=client))
    assert same is prior and tok["input_tokens"] == 0 and client.calls == []
    fresh, tok = asyncio.run(main._final_structure_verdict(html + " ", spec, html, prior, keyword="k", city="C",
                                                           business_name="A", client=client))
    assert len(client.calls) == 1 and tok["input_tokens"] == 10
    assert any(i["code"] == "sentiment" and i["key"] == "intro" for i in fresh["issues"])
