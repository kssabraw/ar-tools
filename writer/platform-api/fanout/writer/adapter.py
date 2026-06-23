"""Writer adapter (M14 slice 2) — build Input A + Input C from the cached upstreams.

Per the re-sequence (writer-module-plan.md top note) the adapter is a **pure
field-mapper**, not an LLM step: the M13 Brief (`fanout.briefs.output_json`) IS Input A
and the M12 SIE (`fanout.keyword_analyses.output_json`) IS Input C (native shape). The
only structural work is:

  1. append the FAQ + conclusion `heading_structure` rows the Writer expects but the brief
     keeps separate (`brief.faqs[]`), then renumber `order`;
  2. fill `metadata.word_budget / h2_count / h3_count`;
  3. on a SIE miss, synthesise a degraded Input C from the cluster's supporting keywords
     (Δ4 fallback — fallback-only since M12 is live);
  4. Step 0 / §2.5 cross-validation (keyword equality, non-empty headings, FAQ count,
     word-budget divergence).

Pure over dicts — the pipeline/activation slice fetches the rows and the cluster
keywords and calls these.
"""

from __future__ import annotations

from .models import (
    Brief,
    BriefFaq,
    BriefHeading,
    IntentType,
    SieInput,
    WriterAbort,
)

DEFAULT_WORD_BUDGET = 2500
FAQ_MIN, FAQ_MAX = 3, 5
WORD_COUNT_DIVERGENCE = 0.20            # >20% brief vs SIE -> word_count_conflict (brief wins)
FAQ_HEADER_TEXT = "Frequently Asked Questions"
CONCLUSION_TEXT = "Conclusion"


def _intent(value) -> IntentType:
    try:
        return IntentType(value)
    except (ValueError, TypeError):
        return IntentType.informational


def adapt_brief(brief_json: dict) -> Brief:
    """Map a persisted M13 BriefOutput dict to the Writer's Input A, appending the
    structural FAQ + conclusion `heading_structure` rows and filling metadata counts.

    The brief's `heading_structure` carries H1 + content H2/H3 rows; the FAQ block lives
    in `brief.faqs[]`. The Writer expects a single ordered `heading_structure` ending in
    faq-header + faq-question* + conclusion, so we append them here."""
    title = (brief_json.get("title") or brief_json.get("h1") or "").strip()

    headings: list[BriefHeading] = [
        BriefHeading.model_validate(h) for h in (brief_json.get("heading_structure") or [])
    ]
    faqs = [BriefFaq.model_validate(f) for f in (brief_json.get("faqs") or [])]

    # Append FAQ header + one faq-question per FAQ, then a conclusion row.
    appended: list[BriefHeading] = []
    if faqs:
        appended.append(BriefHeading(level="H2", type="faq-header", text=FAQ_HEADER_TEXT))
        appended.extend(
            BriefHeading(level="H3", type="faq-question", text=f.question) for f in faqs
        )
    appended.append(BriefHeading(level="H2", type="conclusion", text=CONCLUSION_TEXT))
    headings.extend(appended)

    # Renumber order sequentially (1-based) across the full structure.
    for i, h in enumerate(headings, start=1):
        h.order = i

    h2_count = sum(1 for h in headings if h.level == "H2" and h.type == "content")
    h3_count = sum(1 for h in headings if h.level == "H3" and h.type == "content")
    metadata = dict(brief_json.get("metadata") or {})
    metadata.setdefault("word_budget", DEFAULT_WORD_BUDGET)
    metadata["h2_count"] = h2_count
    metadata["h3_count"] = h3_count

    return Brief(
        keyword=brief_json.get("keyword") or "",
        title=title,
        intent_type=_intent(brief_json.get("intent_type")),
        scope_statement=brief_json.get("scope_statement"),
        heading_structure=headings,
        faqs=faqs,
        format_directives=brief_json.get("format_directives") or {},
        metadata=metadata,
    )


def degraded_sie(keyword: str, *, word_budget: int, supporting_keywords: list[str]) -> SieInput:
    """Δ4 SIE fallback (SIE-failure / empty path only — M12 live makes this rare). Flat
    term defaults: each supporting keyword required at paragraphs target 1 / max 3, no
    h2/h3 zone targets, no entities. word_count brackets the brief budget so no
    word_count_conflict fires."""
    required = [
        {"term": k, "recommendation_score": 0.5, "is_entity": False}
        for k in dict.fromkeys(kw.strip() for kw in supporting_keywords if kw and kw.strip())
    ]
    usage = [
        {"term": r["term"],
         "h2": {"min": 0, "target": 0, "max": 0},
         "h3": {"min": 0, "target": 0, "max": 0},
         "paragraphs": {"min": 0, "target": 1, "max": 3}}
        for r in required
    ]
    return SieInput.model_validate({
        "keyword": keyword,
        "word_count": {"target": word_budget,
                       "min": int(word_budget * 0.8), "max": int(word_budget * 1.2)},
        "target_keyword": {"term": keyword,
                           "minimum_usage": {"h2": 1, "h3": 0, "paragraphs": 6}},
        "terms": {"required": required, "avoid": []},
        "usage_recommendations": usage,
        "entities": [],
        "warnings": ["sie_degraded_fallback: no SIE analysis; flat term defaults applied"],
    })


def adapt_sie(
    sie_json: dict | None, *, keyword: str, word_budget: int,
    supporting_keywords: list[str] | None = None,
) -> SieInput:
    """Parse the persisted SIE output (native Input C) or, on a miss, the Δ4 fallback."""
    if sie_json:
        return SieInput.model_validate(sie_json)
    return degraded_sie(
        keyword, word_budget=word_budget, supporting_keywords=supporting_keywords or [],
    )


def cross_validate(brief: Brief, sie: SieInput) -> dict:
    """Step 0 / §2.5 — runs before any LLM call. Aborts (WriterAbort) on the fatal
    checks; returns a `warnings` dict (`no_citations` always true — we have no Research
    module; `word_count_conflict` per the ±20% rule). Mutates nothing."""
    if not brief.title:
        raise WriterAbort("brief_missing_title", "Brief produced no title")
    content_headings = [h for h in brief.heading_structure if h.type == "content"]
    if not content_headings:
        raise WriterAbort("empty_heading_structure", "Brief heading_structure has no content H2/H3")
    if (brief.keyword or "").strip().lower() != (sie.keyword or "").strip().lower():
        raise WriterAbort(
            "keyword_mismatch",
            f"brief '{brief.keyword}' != sie '{sie.keyword}'",
        )
    if not (FAQ_MIN <= len(brief.faqs) <= FAQ_MAX):
        raise WriterAbort(
            "faq_count_invalid", f"FAQ count {len(brief.faqs)} outside {FAQ_MIN}-{FAQ_MAX}"
        )

    budget = brief.metadata.get("word_budget", DEFAULT_WORD_BUDGET)
    target = sie.word_count.target if sie.word_count else budget
    word_count_conflict = bool(budget) and abs(target - budget) / budget > WORD_COUNT_DIVERGENCE
    return {"no_citations": True, "word_count_conflict": word_count_conflict}


def build_writer_inputs(
    brief_json: dict, sie_json: dict | None, *, supporting_keywords: list[str] | None = None,
) -> tuple[Brief, SieInput, dict]:
    """Adapt both upstreams + cross-validate. Returns `(brief, sie, warnings)`; raises
    WriterAbort on a fatal Step-0 check. FAQs over the 3–5 band are clamped to 5 before
    validation (the band's hard floor still aborts a <3 brief, per §2.5)."""
    brief = adapt_brief(brief_json)
    if len(brief.faqs) > FAQ_MAX:
        # Clamp the upper bound (keep the highest-scored FAQs) + drop their appended
        # faq-question rows so heading_structure stays consistent.
        kept = sorted(brief.faqs, key=lambda f: (f.faq_score or 0.0), reverse=True)[:FAQ_MAX]
        kept_questions = {f.question for f in kept}
        brief.faqs = [f for f in brief.faqs if f.question in kept_questions]
        brief.heading_structure = [
            h for h in brief.heading_structure
            if h.type != "faq-question" or h.text in kept_questions
        ]
        for i, h in enumerate(brief.heading_structure, start=1):
            h.order = i

    budget = brief.metadata.get("word_budget", DEFAULT_WORD_BUDGET)
    sie = adapt_sie(
        sie_json, keyword=brief.keyword, word_budget=budget,
        supporting_keywords=supporting_keywords,
    )
    warnings = cross_validate(brief, sie)
    return brief, sie, warnings
