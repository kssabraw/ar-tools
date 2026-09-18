"""Tests for Step 0.6 client-aware banned-term outline compliance
(modules/writer/outline_compliance.py).

Guards the real block: a compliance-bound client (e.g. a peptide brand that bans
GLP-1 drug names) could never generate an article on "best weight loss tips"
because the shared brief seeded an FAQ H3 "How can I mimic Ozempic naturally?"
and the Writer hard-aborts on a banned term in a heading. This pass rewords such
headings/questions in place BEFORE generation.
"""

from __future__ import annotations

import asyncio

from modules.writer.banned_terms import build_banned_regex, find_banned
from modules.writer.outline_compliance import (
    deterministic_strip,
    find_banned_items,
    resolve_rewrites,
    sanitize_outline_terms,
)

BANNED = ["Ozempic", "semaglutide", "Wegovy"]
RX = build_banned_regex(BANNED)


def _hs():
    return [
        {"level": "H1", "text": "Best Weight Loss Tips", "type": "content", "order": 0},
        {"level": "H2", "text": "Diet basics", "type": "content", "order": 1},
        {"level": "H2", "text": "How Ozempic compares", "type": "content", "order": 2},
        {"level": "faq-header", "text": "Frequently Asked Questions", "type": "faq-header", "order": 18},
    ]


# ── find_banned_items ────────────────────────────────────────────────────────
def test_find_banned_items_flags_heading_and_faq_only():
    faqs = ["How much water should I drink?", "How can I mimic Ozempic naturally?"]
    items = find_banned_items(_hs(), faqs, RX)
    # The banned H2 (index 2) + the banned FAQ (index 1); clean rows ignored,
    # and H1 / faq-header are never rewritten here.
    kinds = {(i.kind, i.ref_index) for i in items}
    assert kinds == {("heading", 2), ("faq", 1)}
    assert all(i.terms for i in items)


def test_find_banned_items_none_when_no_regex_or_clean():
    assert find_banned_items(_hs(), ["clean q one", "clean q two"], None) == []
    assert find_banned_items(
        [{"level": "H2", "text": "Diet basics", "type": "content"}], ["clean"], RX
    ) == []


# ── deterministic_strip ──────────────────────────────────────────────────────
def test_deterministic_strip_removes_term_and_tidies_punctuation():
    out = deterministic_strip("How can I mimic Ozempic naturally?", RX)
    assert not find_banned(out, RX)
    assert "  " not in out
    assert out.endswith("?")


# ── resolve_rewrites ─────────────────────────────────────────────────────────
def test_resolve_rewrites_accepts_clean_llm_rewrite():
    items = find_banned_items(_hs(), ["How can I mimic Ozempic naturally?"], RX)
    faq_item = next(i for i in items if i.kind == "faq")
    payload = {"rewrites": [{"id": faq_item.item_id,
                             "text": "How can I curb my appetite naturally?"}]}
    resolved = resolve_rewrites(items, payload, RX)
    text, method = resolved[faq_item.item_id]
    assert method == "llm" and "curb my appetite" in text


def test_resolve_rewrites_falls_back_when_llm_still_banned():
    items = find_banned_items([{"level": "H2", "text": "How Ozempic compares", "type": "content"}], [], RX)
    hid = items[0].item_id
    # LLM "rewrite" that swapped one banned drug for another → rejected → strip.
    payload = {"rewrites": [{"id": hid, "text": "How Wegovy compares"}]}
    resolved = resolve_rewrites(items, payload, RX)
    text, method = resolved[hid]
    assert method == "strip" and not find_banned(text, RX)


def test_resolve_rewrites_tolerates_malformed_payload():
    items = find_banned_items([{"level": "H2", "text": "How Ozempic compares", "type": "content"}], [], RX)
    for bad in (None, {}, {"rewrites": "nope"}, {"rewrites": [{"id": "x"}]}):
        resolved = resolve_rewrites(items, bad, RX)
        text, method = resolved[items[0].item_id]
        assert method == "strip" and not find_banned(text, RX)


# ── sanitize_outline_terms (async orchestration) ─────────────────────────────
def _run(coro):
    return asyncio.run(coro)


def test_sanitize_rewords_in_place_and_preserves_structure():
    faqs = ["How can I mimic Ozempic naturally?", "Q2", "Q3"]

    async def fake_llm(system, user, **kw):
        # Return a compliant rewrite for every requested id.
        import re
        ids = [int(m) for m in re.findall(r"id=(\d+)", user)]
        return {"rewrites": [{"id": i, "text": f"compliant heading {i}"} for i in ids]}

    res = _run(sanitize_outline_terms(_hs(), faqs, banned_terms=BANNED, llm_json_fn=fake_llm))
    # FAQ count and heading count preserved (reword in place, no drops).
    assert len(res.faq_questions) == 3
    assert len(res.heading_structure) == len(_hs())
    # Every reworded element is now banned-free.
    assert not find_banned(res.faq_questions[0], RX)
    assert not find_banned(res.heading_structure[2]["text"], RX)
    # Clean rows untouched; orders preserved.
    assert res.heading_structure[1]["text"] == "Diet basics"
    assert [r["order"] for r in res.heading_structure] == [0, 1, 2, 18]
    assert {e["method"] for e in res.reworded} == {"llm"}
    assert len(res.reworded) == 2


def test_sanitize_noop_when_nothing_banned():
    hs = [{"level": "H2", "text": "Diet basics", "type": "content", "order": 1}]
    res = _run(sanitize_outline_terms(hs, ["clean", "also clean"], banned_terms=BANNED))
    assert res.reworded == []
    assert res.heading_structure[0]["text"] == "Diet basics"


def test_sanitize_falls_back_to_strip_when_llm_raises():
    faqs = ["How can I mimic Ozempic naturally?"]

    async def boom(system, user, **kw):
        raise RuntimeError("llm down")

    res = _run(sanitize_outline_terms(_hs(), faqs, banned_terms=BANNED, llm_json_fn=boom))
    assert not find_banned(res.faq_questions[0], RX)          # still compliant
    assert res.reworded and res.reworded[-1]["method"] == "strip"


def test_sanitize_empty_banned_terms_is_noop():
    res = _run(sanitize_outline_terms(_hs(), ["How can I mimic Ozempic naturally?"],
                                      banned_terms=[]))
    assert res.reworded == []
