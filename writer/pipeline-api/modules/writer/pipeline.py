"""Writer pipeline orchestrator (schema v1.5).

Steps per content-writer-module-prd-v1.3.md and v1.5 change spec:
0. Input validation + cross-validation
1. Title generation
2. H1 enrichment
3. Word budget allocation
3.5a + 3.5b. Brand voice distillation || term reconciliation (parallel)
4. Section writing (sequential per H2 group)
5. FAQ writing
6. Conclusion writing
7. Citation usage reconciliation
+ Post-hoc heading banned-term scan (critical, no retry)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from models.writer import (
    ArticleSection,
    BrandConflictEntry,
    BrandVoiceCard,
    ClientContextInput,
    ClientContextSummary,
    FormatCompliance,
    SchemaVersion,
    WriterMetadata,
    WriterRequest,
    WriterResponse,
)

from .banned_terms import BannedTermLeakage, build_banned_regex, find_banned
from .budget import allocate_budget, CONCLUSION_BUDGET_TARGET
from .citations import reconcile_citation_usage
from .conclusion import write_conclusion
from .distillation import distill_brand_voice, is_card_empty
from .faqs import write_faqs
from .intro import write_intro
from .reconciliation import FilteredSIETerms, reconcile_terms, ReconciledTerm
from .citation_coverage_validator import (
    CoverageValidationResult,
    validate_citation_coverage,
)
from .h2_body_length import H2BodyLengthResult, validate_h2_body_lengths
from .heading_seo_optimizer import optimize_headings
from .sections import SectionWriteResult, write_h2_group
from .term_usage import compute_term_usage_by_zone
from .title import generate_h1_enrichment, generate_title

logger = logging.getLogger(__name__)


class WriterError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _validate_inputs(req: WriterRequest) -> tuple[str, str, list[dict], list[str], list[dict]]:
    """Cross-validate brief and SIE; return (keyword, intent_type, heading_structure,
    faq_questions, citations)."""
    brief = req.brief_output
    sie = req.sie_output

    if not isinstance(brief, dict):
        raise WriterError("invalid_brief", "brief_output must be a dict")
    if not isinstance(sie, dict):
        raise WriterError("invalid_sie", "sie_output must be a dict")

    brief_kw = (brief.get("keyword") or "").strip()
    sie_kw = (sie.get("keyword") or "").strip()
    if not brief_kw or brief_kw.lower() != sie_kw.lower():
        raise WriterError("keyword_mismatch", f"brief.keyword='{brief_kw}' vs sie.keyword='{sie_kw}'")

    intent_type = brief.get("intent_type") or "informational"

    # Prefer Research's enriched heading_structure (carries citation_ids
    # per heading per Research §8). Fall back to the original brief's
    # heading_structure when Research output is unavailable. Without this,
    # the Writer's section prompt has no citations to ground prose,
    # which causes the Section LLM to fall into placeholder mode on
    # speculative topics (e.g. authority-gap H3s).
    heading_structure: list[dict] = []
    if req.research_output and isinstance(req.research_output, dict):
        enriched = req.research_output.get("enriched_brief")
        if isinstance(enriched, dict):
            enriched_hs = enriched.get("heading_structure")
            if isinstance(enriched_hs, list) and enriched_hs:
                heading_structure = enriched_hs
    if not heading_structure:
        heading_structure = brief.get("heading_structure") or []
    if not heading_structure:
        raise WriterError("empty_heading_structure", "brief.heading_structure is empty")

    faqs = brief.get("faqs") or []
    faq_questions = [f.get("question", "") for f in faqs if isinstance(f, dict) and f.get("question")]
    if not (3 <= len(faq_questions) <= 5):
        raise WriterError("faq_count_invalid", f"FAQ count {len(faq_questions)} not in [3,5]")

    citations = []
    if req.research_output and isinstance(req.research_output, dict):
        # Either an enriched_brief structure or top-level citations
        citations = (
            req.research_output.get("citations")
            or (req.research_output.get("enriched_brief") or {}).get("citations")
            or []
        )

    return (brief_kw, intent_type, heading_structure, faq_questions, citations)


def _split_h2_groups(heading_structure: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Group H2s with their child H3s in order. FAQ + conclusion excluded."""
    sorted_items = sorted(
        [h for h in heading_structure if isinstance(h, dict)],
        key=lambda h: h.get("order", 0),
    )
    groups: list[tuple[dict, list[dict]]] = []
    current_h2: Optional[dict] = None
    current_h3s: list[dict] = []
    for item in sorted_items:
        item_type = item.get("type")
        level = item.get("level")
        if item_type in ("faq-header", "faq-question", "conclusion") or level == "H1":
            if current_h2:
                groups.append((current_h2, current_h3s))
                current_h2, current_h3s = None, []
            continue
        if level == "H2" and item_type == "content":
            if current_h2:
                groups.append((current_h2, current_h3s))
            current_h2 = item
            current_h3s = []
        elif level == "H3" and item_type == "content" and current_h2:
            current_h3s.append(item)
    if current_h2:
        groups.append((current_h2, current_h3s))
    return groups


def _scan_headings_for_banned(article: list[ArticleSection], banned_regex):
    """Per spec §4.4.3: heading match aborts immediately, no retry."""
    if banned_regex is None:
        return
    for section in article:
        if section.level not in ("H1", "H2", "H3"):
            continue
        if not section.heading:
            continue
        matches = find_banned(section.heading, banned_regex)
        if matches:
            raise BannedTermLeakage(
                term=matches[0],
                location=f"{section.level} order={section.order}: '{section.heading}'",
                snippet=section.heading,
            )


def _format_compliance(article: list[ArticleSection], directives: dict) -> FormatCompliance:
    lists = 0
    tables = 0
    for s in article:
        if not s.body:
            continue
        body = s.body
        # Bullet/numbered list lines
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith(("- ", "* ", "+ ")) or (stripped[:3].rstrip().rstrip(".").isdigit()):
                lists += 1
                break
        # Markdown table
        if "\n|" in body and "---" in body:
            tables += 1
    lists_required = directives.get("min_lists_per_article", 1)
    tables_required = directives.get("min_tables_per_article", 1)
    return FormatCompliance(
        lists_present=lists,
        tables_present=tables,
        lists_required=lists_required,
        tables_required=tables_required,
        answer_first_applied=bool(directives.get("answer_first_paragraphs", True)),
        directives_satisfied=lists >= lists_required and tables >= tables_required,
    )


def _build_section_summaries(article: list[ArticleSection], max_chars: int = 200) -> list[str]:
    """Return one-sentence summaries per content H2 for the conclusion prompt."""
    out: list[str] = []
    for s in article:
        if s.level != "H2" or s.type != "content":
            continue
        body = s.body or ""
        # First sentence as summary
        first = body.split(".")[0]
        if first:
            out.append(f"{s.heading}: {first[:max_chars]}")
    return out


async def run_writer(req: WriterRequest) -> WriterResponse:
    started = time.perf_counter()
    keyword, intent_type, heading_structure, faq_questions, citations = _validate_inputs(req)

    sie = req.sie_output
    brief = req.brief_output

    no_required_terms = not ((sie.get("terms") or {}).get("required"))
    no_citations = not citations
    word_count_conflict = False
    sie_target = (sie.get("word_count") or {}).get("target") or sie.get("word_count_target") or 0
    word_budget = (brief.get("metadata") or {}).get("word_budget") or 2500
    if sie_target and word_budget:
        if abs(sie_target - word_budget) / word_budget > 0.20:
            word_count_conflict = True

    # ---- Word budget allocation ----
    section_budgets = allocate_budget(heading_structure, word_budget)

    # ---- Brand voice distillation + reconciliation in parallel ----
    schema_effective: SchemaVersion = "1.7"
    brand_voice_card: Optional[BrandVoiceCard] = None
    filtered_terms = FilteredSIETerms()
    brand_conflict_log: list[BrandConflictEntry] = []
    client_summary = ClientContextSummary()

    if req.client_context is None:
        # v1.4 fallback path
        schema_effective = "1.7-no-context"
        # Build a flat filtered terms list (all keep)
        from .reconciliation import _all_keep, _avoid_terms_from_sie, _required_terms_from_sie
        filtered_terms = _all_keep(
            _required_terms_from_sie(sie),
            _avoid_terms_from_sie(sie),
            sie.get("usage_recommendations") or [],
        )
    else:
        ctx = req.client_context
        brand_empty = not (ctx.brand_guide_text or "").strip()
        icp_empty = not (ctx.icp_text or "").strip()
        no_website = ctx.website_analysis_unavailable

        if brand_empty and icp_empty and no_website:
            schema_effective = "1.7-degraded"
            from .reconciliation import _all_keep, _avoid_terms_from_sie, _required_terms_from_sie
            filtered_terms = _all_keep(
                _required_terms_from_sie(sie),
                _avoid_terms_from_sie(sie),
                sie.get("usage_recommendations") or [],
            )
        else:
            distillation_task = asyncio.create_task(distill_brand_voice(ctx))
            reconciliation_task = asyncio.create_task(reconcile_terms(sie, ctx.brand_guide_text or ""))

            try:
                brand_voice_card = await distillation_task
            except Exception as exc:
                raise WriterError("brand_distillation_failed", str(exc))
            if brand_voice_card is None:
                raise WriterError("brand_distillation_failed", "Distillation returned no card after retries")

            try:
                filtered_terms, brand_conflict_log = await reconciliation_task
            except Exception as exc:
                raise WriterError("brand_reconciliation_failed", str(exc))

            if is_card_empty(brand_voice_card):
                logger.warning("Brand voice card is empty; section writing will proceed without brand shaping")

            client_summary = ClientContextSummary(
                brand_guide_provided=not brand_empty,
                icp_provided=not icp_empty,
                website_analysis_used=not no_website,
                schema_version_effective=schema_effective,
            )

    banned_regex = build_banned_regex(brand_voice_card.banned_terms if brand_voice_card else [])

    # ---- Heading SEO Optimizer (PRD v2.6) ----
    # Mutate heading_structure so each H2/H3 carries at least one
    # entity from the SIE recommended set. Closes the prior gap where
    # entities only landed in paragraphs because the brief generator
    # picked H2/H3 text BEFORE SIE per-zone targets were known.
    # Failure-safe: on LLM error / malformed response / forbidden-term
    # in rewrite, the original heading is preserved.
    heading_opt_result = await optimize_headings(
        heading_structure,
        keyword=keyword,
        reconciled_terms=filtered_terms.required,
        forbidden_terms=(
            list(brand_voice_card.banned_terms) if brand_voice_card else []
        ) + list(filtered_terms.avoid),
    )
    heading_structure = heading_opt_result.heading_structure

    # ---- Title + H1 enrichment in parallel ----
    required_terms_list = [
        t.get("term", "")
        for t in ((sie.get("terms") or {}).get("required") or [])
        if isinstance(t, dict) and t.get("term")
    ]
    entity_terms = [
        {"term": t.get("term", ""), "entity_category": t.get("entity_category")}
        for t in ((sie.get("terms") or {}).get("required") or [])
        if isinstance(t, dict) and t.get("is_entity")
    ]
    # The article's on-page H1 and the SEO/meta title are SEPARATE concepts:
    # - title = SEO/meta title (browser tab, SERP, og:title). Brief emits this
    #   in `brief.title`. Surfaced as WriterResponse.title.
    # - h1 = on-page main heading (first H1 in article body). Brief emits this
    #   in `brief.h1`. May equal title or be slightly more descriptive.
    # Legacy fallback chain for the H1: brief.h1 → brief.title → brief
    # heading_structure[H1] → raw keyword.
    h1_item = next(
        (h for h in heading_structure if isinstance(h, dict) and h.get("level") == "H1"),
        None,
    )
    h1_text = (
        (brief.get("h1") or "").strip()
        or (brief.get("title") or "").strip()
        or (h1_item.get("text") if h1_item else "")
        or keyword
    )

    # WriterResponse.title prefers brief.title (the SEO title), falling back
    # to the H1 chain when brief.title is absent (very old briefs).
    if (brief.get("title") or "").strip() or (brief.get("h1") or "").strip() or h1_item:
        title = (brief.get("title") or "").strip() or h1_text
        h1_enrichment = await generate_h1_enrichment(
            keyword=keyword, h1_text=h1_text,
            high_salience_entities=entity_terms,
        )
    else:
        title_task = asyncio.create_task(generate_title(
            keyword=keyword, intent_type=intent_type,
            required_terms=required_terms_list,
            entities=[e["term"] for e in entity_terms],
        ))
        h1_task = asyncio.create_task(generate_h1_enrichment(
            keyword=keyword, h1_text=h1_text,
            high_salience_entities=entity_terms,
        ))
        title = await title_task
        h1_enrichment = await h1_task
        # Promote the LLM-generated title to the H1 too so the article's
        # H1 stays consistent with WriterResponse.title.
        h1_text = title

    # Heading-level banned check on title and H1
    if banned_regex:
        for chk_text, chk_loc in [(title, "title"), (h1_text, "H1")]:
            matches = find_banned(chk_text, banned_regex)
            if matches:
                raise BannedTermLeakage(term=matches[0], location=chk_loc, snippet=chk_text)

    # ---- Build initial article scaffolding ----
    article: list[ArticleSection] = []
    next_order = 1

    article.append(ArticleSection(
        order=next_order, level="H1", type="content",
        heading=h1_text, body="",
    ))
    if h1_enrichment:
        next_order += 1
        article.append(ArticleSection(
            order=next_order, level="none", type="h1-enrichment",
            heading=None, body=h1_enrichment, word_count=len(h1_enrichment.split()),
        ))

    # ---- Intro paragraph (Writer v1.6 §4.3.1 — Agree/Promise/Preview) ----
    h2_groups = _split_h2_groups(heading_structure)
    h2_titles = [(h2_item.get("text") or "").strip() for h2_item, _ in h2_groups]
    h2_titles = [t for t in h2_titles if t]
    scope_statement = (brief.get("scope_statement") or "").strip()
    intro_title = (brief.get("title") or h1_text).strip()
    next_order += 1
    intro_section = await write_intro(
        keyword=keyword,
        title=intro_title,
        scope_statement=scope_statement,
        intent_type=intent_type,
        h2_list=h2_titles,
        brand_voice_card=brand_voice_card,
        banned_regex=banned_regex,
        intro_order=next_order,
    )
    article.append(intro_section)

    # ---- Section writing (sequential per H2 group) ----
    banned_terms_leaked_in_body: list[str] = []
    for h2_item, h3_items in h2_groups:
        result = await write_h2_group(
            keyword=keyword, intent=intent_type,
            h2_item=h2_item, h3_items=h3_items,
            section_budgets=section_budgets,
            filtered_terms=filtered_terms,
            citations=citations,
            brand_voice_card=brand_voice_card,
            banned_regex=banned_regex,
        )
        article.extend(result.sections)
        banned_terms_leaked_in_body.extend(result.banned_terms_leaked)

    # ---- FAQ writing ----
    faq_header_item = next(
        (h for h in heading_structure if isinstance(h, dict) and h.get("type") == "faq-header"),
        None,
    )
    faq_header_text = (faq_header_item or {}).get("text", "Frequently Asked Questions")

    next_order = max((s.order for s in article), default=0) + 1
    faq_header_order = next_order
    question_orders = list(range(faq_header_order + 1, faq_header_order + 1 + len(faq_questions)))
    faq_sections = await write_faqs(
        keyword=keyword,
        faq_questions=faq_questions,
        filtered_terms=filtered_terms,
        brand_voice_card=brand_voice_card,
        banned_regex=banned_regex,
        faq_header_text=faq_header_text,
        faq_header_order=faq_header_order,
        question_orders=question_orders,
    )
    article.extend(faq_sections)

    # ---- Conclusion ----
    next_order = max((s.order for s in article), default=0) + 1
    section_summaries = _build_section_summaries(article)
    conclusion_section = await write_conclusion(
        keyword=keyword, intent_type=intent_type,
        section_summaries=section_summaries,
        brand_voice_card=brand_voice_card,
        banned_regex=banned_regex,
        conclusion_order=next_order,
    )
    article.append(conclusion_section)

    # ---- Heading-level post-hoc banned-term scan ----
    _scan_headings_for_banned(article, banned_regex)

    # ---- Step 6.7 — H2 body length validator (PRD v2.3 / Phase 3) ----
    # Catches H2 sections shipping with empty/lightweight bodies (the
    # audited "two sentences and a stat" failure mode). Retries each
    # under-length H2 group ONCE with a stricter prompt; warns-and-
    # accepts if the retry still falls short. Floor comes from the
    # brief's `format_directives.min_h2_body_words`, which the brief
    # generator stamps from the per-intent template at assembly time.
    directives_dict = (brief.get("format_directives") or {})
    min_h2_body_words = int(directives_dict.get("min_h2_body_words", 0) or 0)
    h2_length_result: Optional[H2BodyLengthResult] = None
    if min_h2_body_words > 0:
        h2_length_result = await validate_h2_body_lengths(
            article,
            min_h2_body_words=min_h2_body_words,
            keyword=keyword,
            intent=intent_type,
            heading_structure=heading_structure,
            section_budgets=section_budgets,
            filtered_terms=filtered_terms,
            citations=citations,
            brand_voice_card=brand_voice_card,
            banned_regex=banned_regex,
        )
        # Re-run the heading-level banned-term scan on any retry-replaced
        # sections — write_h2_group only catches body-level leakage; if a
        # retry produced a different heading text (it shouldn't — retry
        # never regenerates headings — but defensive), the heading scan
        # would catch it.
        article = h2_length_result.validated_article
        _scan_headings_for_banned(article, banned_regex)

    # ---- Step 4F.1 — Citation Coverage Validator (PRD v1.7 / Phase 4) ----
    # Detects citable claims (C1–C9) per H2 group. If coverage is below
    # 50%, retries the section ONCE with a directive listing the uncited
    # claims and asking the LLM to add markers or rewrite to remove the
    # claim. After retry, applies an auto-soften pass to operational
    # claims (C7-C9) that remain unsourced, replacing specific durations
    # / frequencies / operational percentages with hedge phrasing
    # ("4-to-6 week refresh cadence" → "a typical refresh cadence
    # (every few weeks)"). Never aborts.
    coverage_result: Optional[CoverageValidationResult] = None
    coverage_result = await validate_citation_coverage(
        article,
        keyword=keyword,
        intent=intent_type,
        heading_structure=heading_structure,
        section_budgets=section_budgets,
        filtered_terms=filtered_terms,
        citations=citations,
        brand_voice_card=brand_voice_card,
        banned_regex=banned_regex,
    )
    article = coverage_result.validated_article
    _scan_headings_for_banned(article, banned_regex)

    # ---- Citation reconciliation ----
    citation_usage = reconcile_citation_usage(article, citations)

    # ---- Format compliance ----
    directives = (brief.get("format_directives") or {})
    fmt = _format_compliance(article, directives)

    # ---- Metadata ----
    total_words = sum(s.word_count for s in article if s.type not in ("faq-header", "faq-question"))
    faq_words = sum(s.word_count for s in article if s.type == "faq-question")
    metadata = WriterMetadata(
        total_word_count=total_words,
        word_budget=word_budget,
        faq_word_count=faq_words,
        budget_utilization_pct=round((total_words / word_budget) * 100, 1) if word_budget else 0.0,
        word_count_conflict=word_count_conflict,
        no_required_terms=no_required_terms,
        section_count=sum(1 for s in article if s.type == "content"),
        faq_count=len(faq_questions),
        citations_used=citation_usage.citations_used,
        citations_unused=citation_usage.citations_unused,
        no_citations=no_citations,
        retry_count=0,
        banned_terms_leaked_in_body=sorted(set(banned_terms_leaked_in_body)),
        # PRD v2.3 / Phase 3 — Step 6.7 outcomes
        under_length_h2_sections=(
            h2_length_result.under_length_h2_sections
            if h2_length_result is not None else []
        ),
        h2_body_length_retries_attempted=(
            h2_length_result.retries_attempted
            if h2_length_result is not None else 0
        ),
        h2_body_length_retries_succeeded=(
            h2_length_result.retries_succeeded
            if h2_length_result is not None else 0
        ),
        # PRD v1.7 / Phase 4 — Step 4F.1 outcomes
        under_cited_sections=(
            coverage_result.under_cited_sections
            if coverage_result is not None else []
        ),
        operational_claims_softened=(
            coverage_result.operational_claims_softened
            if coverage_result is not None else []
        ),
        citation_coverage_retries_attempted=(
            coverage_result.retries_attempted
            if coverage_result is not None else 0
        ),
        citation_coverage_retries_succeeded=(
            coverage_result.retries_succeeded
            if coverage_result is not None else 0
        ),
        schema_version=schema_effective,
        brief_schema_version=(brief.get("metadata") or {}).get("schema_version", "1.7"),
        generation_time_ms=int((time.perf_counter() - started) * 1000),
    )

    # ---- Per-zone term usage analysis ----
    sie_required_raw = (sie.get("terms") or {}).get("required") or []
    sie_exploratory_raw = (sie.get("terms") or {}).get("exploratory") or []
    article_dicts = [s.model_dump() for s in article]
    term_usage_by_zone = compute_term_usage_by_zone(
        title=title,
        h1=h1_text,
        article=article_dicts,
        sie_terms_required=sie_required_raw,
        sie_terms_exploratory=sie_exploratory_raw,
    )

    return WriterResponse(
        keyword=keyword,
        intent_type=intent_type,
        title=title,
        article=article,
        citation_usage=citation_usage,
        format_compliance=fmt,
        brand_voice_card_used=brand_voice_card,
        brand_conflict_log=brand_conflict_log,
        client_context_summary=client_summary if client_summary.brand_guide_provided or client_summary.icp_provided or client_summary.website_analysis_used else ClientContextSummary(schema_version_effective=schema_effective),
        term_usage_by_zone=term_usage_by_zone,
        metadata=metadata,
    )
