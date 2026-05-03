"""Step 4 — Section writing.

Sequential per H2 group. Each H2 group = parent H2 + its child H3s. One
LLM call per group. Body is GitHub-flavored Markdown with {{cit_N}}
inline markers placed immediately after closing punctuation of cited
sentences.

Implements:
- 4A: answer-first paragraphs
- 4B: intent-specific patterns
- 4C: term injection with effective targets from reconciliation
- 4D: format directives (lists, tables)
- 4E: H3 sub-section writing (authority gap deeper coverage)
- 4F: citation marker placement
- 4.4: post-hoc banned-term retry (one retry on body match)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from models.writer import ArticleSection, BrandVoiceCard

from modules.brief.llm import claude_json

from .banned_terms import BannedTermLeakage, find_banned
from .reconciliation import FilteredSIETerms, ReconciledTerm

logger = logging.getLogger(__name__)


SECTION_SYSTEM = """You are an expert blog content writer producing publication-ready Markdown sections.

OUTPUT FORMAT:
Return a single JSON object: {"sections": [{"order": <int>, "heading": "<text>", "body": "<markdown>"}]}.

The "sections" array must contain one entry for the parent H2 followed by one entry per nested H3.
- The H2 entry's body is the prose immediately under the H2 (NOT including H3 subsections).
- Each H3 entry's body is the prose under that H3.

WRITING RULES:
- Markdown only (GitHub Flavored Markdown). No HTML.
- DO NOT include the heading text inside the body. Heading goes in the "heading" field.
- Every H2 section opens with a direct answer sentence (max 25 words). 1-2 supporting detail sentences. Then elaboration.
- Use bulleted/numbered lists and Markdown tables where they help comprehension. Distribute lists/tables across sections (do not stack in one).
- No promotional superlatives ("the best", "industry-leading", "world-class").
- Cite specific facts using {{cit_N}} markers immediately after the closing punctuation of the sentence, like: "Heat pump installations grew 11% year over year.{{cit_001}}"
- Use the citation_id values provided. Never invent citation IDs.
- For sentences without a verifiable claim from the provided citations, do not place a marker.
- Do NOT use any term in the FORBIDDEN_TERMS list anywhere.
- Use REQUIRED_TERMS naturally where they fit; aim for the target counts listed."""


INTENT_GUIDANCE = {
    "how-to": "This is a how-to article. Write each H2 as a numbered step. First sentence = the action instruction. Use H3s for sub-steps.",
    "listicle": "This is a listicle. Each H2 is a list item with a clear label. Use parallel structure across items.",
    "informational": "This is informational. Explanatory prose with answer-first paragraphs. Use evidence and concrete examples.",
    "comparison": "This is a comparison piece. Each section evaluates the same axis across compared options. Maintain parallel structure.",
    "local-seo": "Informational base with service framing. Avoid claims tied to specific cities you cannot verify.",
    "ecom": "Feature-benefit framing focused on practical outcomes. Neutral tone, not promotional.",
    "informational-commercial": "Buyer-education tone. Compare options. Do not endorse a single product.",
    "news": "Recency-forward. Lead with the most important information. Be factual.",
}


@dataclass
class SectionWriteResult:
    sections: list[ArticleSection]
    citations_used_in_group: set[str] = field(default_factory=set)
    banned_terms_leaked: list[str] = field(default_factory=list)


def _intent_guidance(intent: str) -> str:
    return INTENT_GUIDANCE.get(intent, INTENT_GUIDANCE["informational"])


def _terms_for_section(filtered: FilteredSIETerms, max_required: int = 10) -> tuple[list[ReconciledTerm], list[str], list[str]]:
    """Split into (required to use with effective targets, excluded to avoid, raw avoid)."""
    required = filtered.required[:max_required]
    excluded_terms = [e["term"] for e in filtered.excluded if e.get("term")]
    return (required, excluded_terms, filtered.avoid)


def _resolve_citations(
    citation_ids: list[str],
    citations: list[dict],
) -> list[dict]:
    """Look up citations by ID, filter to relevance >= 0.50.

    Per PRD §4F: fallback_stub claims may not be used as factual assertions —
    we still expose them but mark them so the LLM uses them only as source
    acknowledgment.
    """
    by_id = {c.get("citation_id"): c for c in citations if isinstance(c, dict)}
    out = []
    for cid in citation_ids:
        c = by_id.get(cid)
        if not c:
            continue
        # Filter claims by relevance
        keep_claims = []
        for claim in c.get("claims") or []:
            if not isinstance(claim, dict):
                continue
            if (claim.get("relevance_score") or 0) >= 0.50:
                keep_claims.append(claim)
        c_copy = dict(c)
        c_copy["claims"] = keep_claims
        out.append(c_copy)
    return out


def _build_section_user_prompt(
    keyword: str,
    intent: str,
    h2_item: dict,
    h3_items: list[dict],
    section_budgets: dict[int, int],
    required_terms: list[ReconciledTerm],
    excluded_terms: list[str],
    avoid_terms: list[str],
    forbidden_terms: list[str],
    citations: list[dict],
    brand_voice_card: Optional[BrandVoiceCard],
    is_authority_gap_section: bool,
    retry_term: Optional[str] = None,
    citations_were_fallback: bool = False,
    length_retry_directive: Optional[str] = None,
    coverage_retry_directive: Optional[str] = None,
    section_category_aspirational: Optional[dict[str, int]] = None,
) -> str:
    parts: list[str] = []
    parts.append(f"KEYWORD: {keyword}")
    parts.append(f"INTENT: {intent}")
    parts.append(f"INTENT_GUIDANCE: {_intent_guidance(intent)}")
    parts.append(f"\nH2_HEADING (order {h2_item.get('order')}): {h2_item.get('text')}")
    parts.append(f"WORD_BUDGET_FOR_H2: {section_budgets.get(h2_item.get('order'), 200)} words")

    if h3_items:
        parts.append("\nH3_SUBSECTIONS:")
        for h3 in h3_items:
            # Internal SME-flagged H3s carry source='authority_gap_sme'.
            # The directive below tells the writer this section must add
            # substantive insight competitors miss — but we deliberately
            # avoid the literal phrase "authority gap" because the
            # writer LLM has parroted it back into article bodies in the
            # past (e.g. "The authority gap has four failure points...").
            tag = (
                " [must add a specific expert insight competitors don't cover — non-obvious angle, hidden trade-off, or insider perspective]"
                if h3.get("source") == "authority_gap_sme"
                else ""
            )
            parts.append(
                f"  - order {h3.get('order')}: {h3.get('text')}"
                f" — budget: {section_budgets.get(h3.get('order'), 150)} words{tag}"
            )

    if brand_voice_card:
        parts.append("\nBRAND_VOICE:")
        if brand_voice_card.brand_name:
            parts.append(f"  brand_name: {brand_voice_card.brand_name}")
        if brand_voice_card.tone_adjectives:
            parts.append(f"  tone: {', '.join(brand_voice_card.tone_adjectives)}")
        if brand_voice_card.voice_directives:
            parts.append(f"  directives: {' | '.join(brand_voice_card.voice_directives[:5])}")
        if brand_voice_card.audience_summary:
            parts.append(f"\nAUDIENCE: {brand_voice_card.audience_summary}")
        if brand_voice_card.audience_personas:
            parts.append(f"  personas: {', '.join(brand_voice_card.audience_personas[:5])}")
        if brand_voice_card.audience_company_size:
            parts.append(f"  company size: {brand_voice_card.audience_company_size}")
        if brand_voice_card.audience_verticals:
            parts.append(
                f"  verticals: {', '.join(brand_voice_card.audience_verticals[:8])} "
                f"(when an example would help, ground it in one of these verticals "
                f"rather than a generic industry)"
            )
        if brand_voice_card.audience_pain_points:
            parts.append(f"  pain points: {', '.join(brand_voice_card.audience_pain_points[:3])}")
        if brand_voice_card.audience_goals:
            parts.append(
                f"  goals (frame the section to advance one of these where natural): "
                f"{', '.join(brand_voice_card.audience_goals[:3])}"
            )
        if (
            brand_voice_card.brand_name
            or brand_voice_card.client_services
            or brand_voice_card.client_locations
        ):
            parts.append(
                "\nCLIENT_CONTEXT (anchor the section to this brand where it adds credibility):"
            )
            if brand_voice_card.brand_name:
                parts.append(
                    f"  Across the article, mention {brand_voice_card.brand_name} 1–2 times "
                    f"total — anchored to evidence (data, methodology, or a specific service), "
                    f"never as standalone promotion. In any single section you may include AT "
                    f"MOST 1 mention; if the topic is far from the brand's offering, omit the "
                    f"mention in this section and let another carry it."
                )
            if brand_voice_card.client_services:
                parts.append(
                    f"  services (reference one where it naturally extends a section's argument): "
                    f"{', '.join(brand_voice_card.client_services[:8])}"
                )
            if brand_voice_card.client_locations:
                parts.append(f"  locations: {', '.join(brand_voice_card.client_locations[:8])}")

    if required_terms:
        parts.append("\nREQUIRED_TERMS (use naturally, aim for target count):")
        for t in required_terms:
            parts.append(f"  - {t.term} (target: {t.effective_target}, max: {t.effective_max})")

    # SIE v1.4 — section-level pro-rated category target. Informational
    # only (the per-term targets above are the hard guidance). The
    # writer pipeline pre-divides the article-wide body aggregate by
    # this section's word-budget share before passing it in.
    if section_category_aspirational:
        ent = int(section_category_aspirational.get("entities", 0) or 0)
        rel = int(section_category_aspirational.get("related_keywords", 0) or 0)
        var = int(section_category_aspirational.get("keyword_variants", 0) or 0)
        if ent or rel or var:
            parts.append(
                f"\nSECTION_CATEGORY_TARGET (this section's fair-share "
                f"contribution to article-wide body coverage — aspirational, "
                f"distribute naturally): {ent} entities, {rel} related "
                f"keywords, {var} keyword variants."
            )

    forbidden_combined = sorted(set([t.lower() for t in forbidden_terms + excluded_terms + avoid_terms if t]))
    if forbidden_combined:
        parts.append("\nFORBIDDEN_TERMS (must not appear anywhere in output):")
        parts.append("  " + ", ".join(forbidden_combined[:50]))

    if retry_term:
        parts.append(f"\nRETRY: A previous attempt included the forbidden term '{retry_term}'. Rewrite without it.")

    if length_retry_directive:
        # PRD v2.3 / Phase 3 — Step 6.7 H2 body length retry directive.
        # The validator passes this string when the previous attempt
        # produced a section group below `format_directives.min_h2_body_
        # words`. The directive names the floor and instructs additional
        # SUBSTANCE (not padding) to hit it.
        parts.append(f"\nLENGTH_RETRY: {length_retry_directive}")

    if coverage_retry_directive:
        # PRD v1.7 / Phase 4 — Step 4F.1 citation-coverage retry directive.
        # The validator passes this string when the previous attempt
        # produced fewer than 50% citation markers on detected citable
        # claims. The directive lists the offending sentences and asks
        # the LLM to either add a marker from the available pool or
        # rewrite the sentence to remove the claim.
        parts.append(f"\nCOVERAGE_RETRY: {coverage_retry_directive}")

    if citations:
        valid_ids = sorted({c.get("citation_id", "") for c in citations if c.get("citation_id")})
        if citations_were_fallback:
            parts.append(
                "\nCITATIONS (general references for this article — cite where any "
                "actually fits a factual claim in your section; otherwise omit the marker):"
            )
        else:
            parts.append(
                "\nCITATIONS (use {{cit_id}} markers after sentences containing these "
                "specific facts):"
            )
        for c in citations:
            cid = c.get("citation_id", "")
            url = c.get("url", "")
            title = c.get("title", "")
            parts.append(f"  {cid}: {title} — {url}")
            for claim in c.get("claims", [])[:5]:
                method = claim.get("extraction_method", "verbatim_extraction")
                if method == "fallback_stub":
                    parts.append(
                        f"    [stub-only — reference as source, do not assert specific stats]: {claim.get('claim_text', '')}"
                    )
                else:
                    parts.append(f"    fact: {claim.get('claim_text', '')}")
        parts.append(
            f"\nVALID_CITATION_IDS: {', '.join(valid_ids)}. "
            f"You may ONLY use these exact IDs in {{{{cit_id}}}} markers. "
            f"NEVER invent IDs (do not write {{{{cit_001}}}}, {{{{cit_002}}}}, etc. unless they appear above)."
        )
    else:
        parts.append(
            "\nCITATIONS: none available for this section. "
            "DO NOT place any {{cit_id}} markers in the body. "
            "Write the section as factual prose without inline citations."
        )

    parts.append(
        "\nWrite the section now. Output the JSON object with the sections array."
    )
    return "\n".join(parts)


def _extract_marker_ids(body: str) -> list[str]:
    return re.findall(r"\{\{(cit_\d+)\}\}", body)


_MARKER_RE = re.compile(r"\{\{(cit_\d+)\}\}")


def _strip_invalid_markers(
    body: str,
    *,
    valid_ids: set[str],
    h2_order: Optional[int] = None,
) -> str:
    """Remove any {{cit_NNN}} marker whose id is not in `valid_ids`.

    Also collapses any extra whitespace introduced by the removal so the
    surrounding sentence remains clean (e.g., "fact.{{cit_999}} Next" →
    "fact. Next" rather than "fact.  Next").
    """
    invented: list[str] = []

    def _sub(match: re.Match) -> str:
        cid = match.group(1)
        if cid in valid_ids:
            return match.group(0)
        invented.append(cid)
        return ""

    cleaned = _MARKER_RE.sub(_sub, body)
    if invented:
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r" +([.,;:!?])", r"\1", cleaned)
        logger.warning(
            "writer.section.invented_markers_stripped",
            extra={
                "h2_order": h2_order,
                "stripped_ids": invented[:20],
                "stripped_count": len(invented),
                "valid_id_count": len(valid_ids),
            },
        )
    return cleaned


async def write_h2_group(
    keyword: str,
    intent: str,
    h2_item: dict,
    h3_items: list[dict],
    section_budgets: dict[int, int],
    filtered_terms: FilteredSIETerms,
    citations: list[dict],
    brand_voice_card: Optional[BrandVoiceCard],
    banned_regex,
    length_retry_directive: Optional[str] = None,
    coverage_retry_directive: Optional[str] = None,
    section_category_aspirational: Optional[dict[str, int]] = None,
) -> SectionWriteResult:
    """Single LLM call for the H2 + nested H3 children. Retries once on
    body banned-term match. Headings are NOT regenerated by this function —
    headings come from the brief verbatim, so the only retry source is body.

    `length_retry_directive` (PRD v2.3 / Phase 3): set by Step 6.7 when a
    previous attempt produced a section group below
    `format_directives.min_h2_body_words`. The directive names the floor
    and asks for additional substance (not padding) to clear it.

    `coverage_retry_directive` (PRD v1.7 / Phase 4): set by Step 4F.1 when
    a previous attempt produced under-50% citation coverage on detected
    citable claims. The directive lists the offending sentences and asks
    the LLM to either add a marker or rewrite to remove the claim."""
    required_terms, excluded_terms, avoid_terms = _terms_for_section(filtered_terms)
    forbidden_terms = (brand_voice_card.banned_terms if brand_voice_card else []) or []

    # Resolve citations applicable to the H2 group
    h2_citation_ids = h2_item.get("citation_ids") or []
    h3_citation_ids: list[str] = []
    for h3 in h3_items:
        h3_citation_ids.extend(h3.get("citation_ids") or [])
    all_ids = list(dict.fromkeys(h2_citation_ids + h3_citation_ids))
    resolved_citations = _resolve_citations(all_ids, citations)

    # Fallback: if Research didn't attach any citation_ids to this H2 group,
    # pass the full research.citations pool so the writer can still cite
    # general sources where they fit. Without this, an entire H2 group
    # writes citation-free prose and the article ships with an empty
    # Sources Cited section.
    citations_were_fallback = False
    if not resolved_citations and citations:
        resolved_citations = list(citations)[:8]  # cap at 8 to keep prompt size bounded
        citations_were_fallback = True
        logger.info(
            "writer.section.citations_fallback_to_global_pool",
            extra={
                "h2_order": h2_item.get("order"),
                "h2_text": (h2_item.get("text") or "")[:120],
                "fallback_count": len(resolved_citations),
            },
        )

    is_auth_gap = any(h3.get("source") == "authority_gap_sme" for h3 in h3_items)

    logger.info(
        "writer.section.citations_attached",
        extra={
            "h2_order": h2_item.get("order"),
            "h2_text": (h2_item.get("text") or "")[:120],
            "h3_count": len(h3_items),
            "citation_ids_from_brief": len(all_ids),
            "citations_resolved": len(resolved_citations),
            "fallback_used": citations_were_fallback,
        },
    )

    retry_term: Optional[str] = None
    last_response: Optional[dict] = None

    for attempt in range(2):
        user = _build_section_user_prompt(
            keyword=keyword,
            intent=intent,
            h2_item=h2_item,
            h3_items=h3_items,
            section_budgets=section_budgets,
            required_terms=required_terms,
            excluded_terms=excluded_terms,
            avoid_terms=avoid_terms,
            forbidden_terms=forbidden_terms,
            citations=resolved_citations,
            brand_voice_card=brand_voice_card,
            is_authority_gap_section=is_auth_gap,
            retry_term=retry_term,
            citations_were_fallback=citations_were_fallback,
            length_retry_directive=length_retry_directive,
            coverage_retry_directive=coverage_retry_directive,
            section_category_aspirational=section_category_aspirational,
        )
        try:
            # 8000 tokens accommodates an H2 + up to ~6 H3 children, each with
            # answer-first body + lists/tables, without truncation. The previous
            # 3500-token cap silently truncated mid-string when a brief produced
            # 1 H2 with many H3 children, raising JSONDecodeError downstream.
            result = await claude_json(SECTION_SYSTEM, user, max_tokens=8000, temperature=0.4)
        except Exception as exc:
            logger.exception(
                "writer.section.llm_failed",
                extra={
                    "h2_order": h2_item.get("order"),
                    "h2_text": (h2_item.get("text") or "")[:120],
                    "h3_count": len(h3_items),
                    "citations_attached": len(resolved_citations),
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
            return _placeholder_result(
                h2_item, h3_items, section_budgets,
                reason=f"llm_call:{type(exc).__name__}",
            )

        if not isinstance(result, dict):
            logger.warning(
                "writer.section.payload_not_dict",
                extra={"h2_order": h2_item.get("order"), "got_type": type(result).__name__},
            )
            return _placeholder_result(
                h2_item, h3_items, section_budgets, reason="payload_not_dict",
            )

        sections_raw = result.get("sections") or []
        if not isinstance(sections_raw, list) or not sections_raw:
            logger.warning(
                "writer.section.empty_sections",
                extra={
                    "h2_order": h2_item.get("order"),
                    "got_keys": list(result.keys()) if isinstance(result, dict) else [],
                },
            )
            return _placeholder_result(
                h2_item, h3_items, section_budgets, reason="empty_sections",
            )

        # Banned-term check on body content of every produced section
        body_match: Optional[str] = None
        for s in sections_raw:
            if not isinstance(s, dict):
                continue
            body = s.get("body") or ""
            matches = find_banned(body, banned_regex)
            if matches:
                body_match = matches[0]
                break

        if body_match and attempt == 0:
            retry_term = body_match
            last_response = result
            continue

        # Body-content leakage after retry: degrade gracefully instead of
        # aborting the entire run. The brand voice card's banned_terms list
        # is sometimes too aggressive (the distillation LLM categorizes
        # soft preferences like "leverage" as banned, then the section LLM
        # can't avoid them in marketing/ROI prose). Surface the leakage in
        # logs + writer metadata so the reviewer can find and fix the term;
        # headings remain hard-abort (see _scan_headings_for_banned).
        leaked_terms: list[str] = []
        if body_match and attempt == 1:
            all_body_matches: list[str] = []
            for s in sections_raw:
                if not isinstance(s, dict):
                    continue
                body = s.get("body") or ""
                all_body_matches.extend(find_banned(body, banned_regex))
            leaked_terms = sorted(set(all_body_matches))
            logger.warning(
                "writer.section.banned_term_leakage_after_retry",
                extra={
                    "h2_order": h2_item.get("order"),
                    "h2_text": (h2_item.get("text") or "")[:120],
                    "leaked_terms": leaked_terms[:20],
                    "leaked_count": len(all_body_matches),
                },
            )

        # Strip invented citation markers — any {{cit_NNN}} that doesn't
        # match an actual citation_id in `resolved_citations` is removed
        # from every body. The Section LLM occasionally hallucinates IDs
        # (matching the example in the system prompt's format) when no or
        # few citations are attached; sources_cited rejects unknowns with
        # HTTP 422, so we sanitize here as a safety net.
        valid_marker_ids = {
            c.get("citation_id", "") for c in resolved_citations if c.get("citation_id")
        }
        for s in sections_raw:
            if isinstance(s, dict) and isinstance(s.get("body"), str):
                s["body"] = _strip_invalid_markers(
                    s["body"],
                    valid_ids=valid_marker_ids,
                    h2_order=h2_item.get("order"),
                )

        result_obj = _build_result(h2_item, h3_items, sections_raw, section_budgets)
        result_obj.banned_terms_leaked = leaked_terms
        return result_obj

    return _placeholder_result(
        h2_item, h3_items, section_budgets, reason="loop_exhausted",
    )


def _placeholder_result(
    h2_item: dict,
    h3_items: list[dict],
    budgets: dict[int, int],
    reason: str = "unknown",
) -> SectionWriteResult:
    placeholder = (
        f"[SECTION GENERATION FAILED — MANUAL REVIEW REQUIRED — reason: {reason}]"
    )
    sections = [ArticleSection(
        order=h2_item.get("order", 0),
        level="H2",
        type="content",
        heading=h2_item.get("text", ""),
        body=placeholder,
        word_count=0,
        section_budget=budgets.get(h2_item.get("order"), 200),
    )]
    for h3 in h3_items:
        sections.append(ArticleSection(
            order=h3.get("order", 0),
            level="H3",
            type="content",
            heading=h3.get("text", ""),
            body=placeholder,
            word_count=0,
            section_budget=budgets.get(h3.get("order"), 150),
        ))
    return SectionWriteResult(sections=sections)


def _build_result(
    h2_item: dict,
    h3_items: list[dict],
    sections_raw: list[dict],
    budgets: dict[int, int],
) -> SectionWriteResult:
    by_order = {}
    for s in sections_raw:
        if not isinstance(s, dict):
            continue
        order = s.get("order")
        if isinstance(order, int):
            by_order[order] = s

    out_sections: list[ArticleSection] = []
    citations_used: set[str] = set()

    h2_order = h2_item.get("order", 0)
    h2_data = by_order.get(h2_order, {})
    h2_body = h2_data.get("body", "") if isinstance(h2_data, dict) else ""
    citations_used.update(_extract_marker_ids(h2_body))
    out_sections.append(ArticleSection(
        order=h2_order,
        level="H2",
        type="content",
        heading=h2_item.get("text", ""),
        body=h2_body,
        word_count=len(h2_body.split()),
        section_budget=budgets.get(h2_order, 200),
        citations_referenced=_extract_marker_ids(h2_body),
    ))

    for h3 in h3_items:
        h3_order = h3.get("order", 0)
        h3_data = by_order.get(h3_order, {})
        body = h3_data.get("body", "") if isinstance(h3_data, dict) else ""
        citations_used.update(_extract_marker_ids(body))
        out_sections.append(ArticleSection(
            order=h3_order,
            level="H3",
            type="content",
            heading=h3.get("text", ""),
            body=body,
            word_count=len(body.split()),
            section_budget=budgets.get(h3_order, 150),
            citations_referenced=_extract_marker_ids(body),
        ))

    return SectionWriteResult(sections=out_sections, citations_used_in_group=citations_used)
