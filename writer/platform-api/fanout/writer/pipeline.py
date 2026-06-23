"""Writer pipeline (M14 slice 4) — the sequential step runner (PRD §5, degraded path).

Runs the `1.7-no-context` + `no_citations` flow end to end: H1 + enrichment lede →
budget + topic-adherence filter → intro → sections (sequential, one Sonnet call per H2
group) → FAQ → conclusion → CTA → key takeaways → deterministic validators (soften,
length/paragraph flags, title-case) → assemble + serialize the §6 WriterOutput.

Deps are injected (`WriterDeps`) so the orchestration is unit-testable with a mock LLM;
`build_writer_deps` constructs the real Sonnet/Haiku clients + the 3-small embedder.
Sections are written SEQUENTIALLY (D8 — term-budget state is order-dependent); never
parallelize within one article.
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Callable

from . import budget as budget_mod
from . import validators as v
from .models import (
    SCHEMA_VERSION_NO_CONTEXT,
    ArticleItem,
    Brief,
    BriefHeading,
    IntentType,
    SieInput,
    WriterAbort,
    WriterOutput,
)
from .serialize import to_html, to_markdown
from .templates import cta_template, h2_body_floor

logger = logging.getLogger(__name__)
EmbedFn = Callable[[list[str]], list[list[float]]]
TAKEAWAY_PAIR_COSINE = 0.85          # §5.12 — over this -> drop one of the pair


@dataclass
class WriterDeps:
    section_llm: object       # Sonnet — prose (sections/intro/FAQ/conclusion/takeaways)
    short_llm: object         # Haiku — CTA
    embed_fn: EmbedFn         # text-embedding-3-small (title anchor + H2 + takeaways)


def build_writer_deps() -> WriterDeps:
    """Construct the real clients (lazy imports keep the pure modules import-light)."""
    from fanout.config import get_settings
    from fanout.llm import get_llm
    from fanout.llm.anthropic_client import AnthropicLLM

    s = get_settings()
    return WriterDeps(
        section_llm=AnthropicLLM(api_key=s.anthropic_api_key, model=s.writer_section_model),
        short_llm=AnthropicLLM(api_key=s.anthropic_api_key, model=s.writer_short_model),
        embed_fn=get_llm().embed,
    )


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (da * db)


# ----- prose steps ----------------------------------------------------------


def _enrichment_lede(deps: WriterDeps, brief: Brief, sie: SieInput) -> str:
    """§5.2.2 — 1 sentence ≤25 words, names ≥1 entity/key term, not a title restatement.
    Δ4a: with no qualifying entity category, anchor on the top supporting term."""
    anchors = [e.term for e in sie.entities[:5]] or [t.term for t in sie.terms.required[:5]]
    anchor_hint = ", ".join(anchors) or brief.keyword
    txt = deps.section_llm.complete_text(
        system="You write a single-sentence topical lede for an article. No preamble.",
        user=(
            f"Title: {brief.title}\nScope: {brief.scope_statement or ''}\n"
            f"Anchor terms (use at least one naturally): {anchor_hint}\n\n"
            "Write ONE sentence (<=25 words) that sets topical context for the article. "
            "Do not restate the title verbatim. No heading markers, no list markers."
        ),
        purpose="writer_enrichment_lede", max_tokens=120, temperature=0.5,
    )
    return " ".join(txt.split())[:400]


def _intro(deps: WriterDeps, brief: Brief, kept_h2_texts: list[str]) -> dict:
    """§5.3 — Agree/Promise/Preview, combined into one 60–150 word paragraph."""
    schema = {
        "type": "object",
        "properties": {
            "agree": {"type": "string"}, "promise": {"type": "string"},
            "preview": {"type": "string"},
        },
        "required": ["agree", "promise", "preview"],
    }
    preview_list = "; ".join(kept_h2_texts[:5])
    out = deps.section_llm.call_tool(
        system="You write article introductions in three beats. Return the tool call only.",
        user=(
            f"Title: {brief.title}\nScope: {brief.scope_statement or ''}\n"
            f"First sections (in order): {preview_list}\n\n"
            "Write three beats, each <=50 words:\n"
            "1. agree — name the reader's situation in their own words; do NOT name a brand; "
            "do NOT begin with the keyword.\n"
            "2. promise — what the article delivers, anchored in the title and scope; no CTA.\n"
            "3. preview — name the first 3-5 sections in order, in plain language (do not "
            "verbatim list the headings)."
        ),
        tool_name="intro", tool_description="The three intro beats.", input_schema=schema,
        purpose="writer_intro", max_tokens=512, temperature=0.5,
    )
    return {k: " ".join((out.get(k) or "").split()) for k in ("agree", "promise", "preview")}


def _intro_paragraph(intro: dict) -> str:
    """Join the three beats into one paragraph; collapse any newlines (§5.3 v1.6)."""
    joined = " ".join(p for p in (intro.get("agree"), intro.get("promise"), intro.get("preview")) if p)
    return re.sub(r"\s*\n+\s*", " ", joined).strip()


_INTENT_PATTERN_HINT = {
    IntentType.how_to: "Each H2 is a step; first sentence is an action instruction.",
    IntentType.listicle: "Each H2 is a list item with a bolded label; consistent structure.",
    IntentType.informational: "Explanatory prose; answer-first; evidence where available.",
    IntentType.comparison: "Parallel structure; address the same evaluative axis for each option.",
    IntentType.local_seo: "Informational base, service-context framing; avoid city-specific claims.",
    IntentType.ecom: "Feature-benefit framing; practical outcomes; neutral, not promotional.",
    IntentType.informational_commercial: "Buyer-education tone; compare options; do not endorse.",
    IntentType.news: "Recency-forward; factual; lead with the most important information.",
}


def _write_group(
    deps: WriterDeps, brief: Brief, sie: SieInput, group: budget_mod.Group,
    section_budget: int, *, retry_directive: str = "",
) -> str:
    """§5.8 — one Sonnet call for an H2 group (parent + child H3s). Returns markdown
    body (H3s as `### ` subsections inside). No citation markers (no_citations)."""
    h3_lines = "\n".join(f"- {c.text}" for c in group.children)
    required = ", ".join(t.term for t in sie.terms.required[:20])
    avoid = ", ".join(sie.terms.avoid[:20])
    fd = brief.format_directives
    fmt_bits = []
    if fd.require_bulleted_lists:
        fmt_bits.append("include at least one bulleted or numbered list")
    if fd.require_tables:
        fmt_bits.append("include at least one Markdown table")
    user = (
        f"Article title: {brief.title}\nScope: {brief.scope_statement or ''}\n"
        f"Intent: {brief.intent_type.value} — {_INTENT_PATTERN_HINT.get(brief.intent_type, '')}\n"
        f"Write the section under this H2: \"{group.parent.text}\"\n"
        + (f"After the lead, cover these H3 subsections (use a `### ` heading for each):\n{h3_lines}\n"
           if group.children else "")
        + f"Target length: ~{section_budget} words.\n"
        + (f"Weave in these terms naturally where relevant: {required}\n" if required else "")
        + (f"Do NOT use these terms: {avoid}\n" if avoid else "")
        + (f"Formatting: {', '.join(fmt_bits)}.\n" if fmt_bits else "")
        + "Open with at least one answer-first paragraph (lead with a direct answer "
        + "sentence <=25 words) BEFORE any `### ` subheading — never start the section with "
        + "a subheading, and never make a subheading that merely restates the H2. "
        + f"Every paragraph <= {fd.max_sentences_per_paragraph} sentences. "
        + "Do NOT fabricate statistics, percentages, dates, or study citations. "
        + _decision_fit_directive_text(group.parent.format_directive)
        + "Output GitHub-flavored Markdown for the section body only (no H1/H2 heading line)."
        + (f"\n\n{retry_directive}" if retry_directive else "")
    )
    prose = deps.section_llm.complete_text(
        system="You are an expert writer producing SEO article sections. Markdown only.",
        user=user, purpose="writer_section",
        # ~4 tokens/word headroom (tables/lists add markdown overhead); generous cap so a
        # multi-H3 group is never truncated mid-content.
        max_tokens=min(6000, max(768, section_budget * 4)), temperature=0.6,
    )
    # Defensive: if a draft still ends on a dangling/empty list marker (e.g. a truncated
    # "- "), drop that incomplete trailing bullet so it never renders.
    return re.sub(r"\n\s*[-*+]\s*$", "", prose).rstrip()


def _decision_fit_directive_text(directive: dict | None) -> str:
    """Render a `decision_fit` format_directive (§A5 STAGE B) into section-prompt guidance:
    the answer depends on the reader's situation, so the prose must work the condition→
    recommendation branches in naturally (condition-first), plus the overarching default.
    No forced 'which is right for you' heading — it's woven into the body. Empty for any
    other / absent directive."""
    if not directive or directive.get("type") != "decision_fit":
        return ""
    branches = [
        b for b in (directive.get("branches") or [])
        if isinstance(b, dict) and (b.get("condition") or "").strip() and (b.get("option") or "").strip()
    ]
    if len(branches) < 2:
        return ""
    lines = "\n".join(f"- If {b['condition'].strip()}: {b['option'].strip()}" for b in branches)
    default = (directive.get("default_statement") or "").strip()
    return (
        "IMPORTANT — this section's best answer depends on the reader's situation. Work the "
        "following condition->recommendation branches into the prose naturally, stating the "
        "condition first in each; do NOT add a separate subheading or a 'which is right for "
        f"you' label, and do not present them as a bulleted list verbatim:\n{lines}\n"
        + (f"Across all cases, the overarching guidance is: {default}\n" if default else "")
    )


def _group_to_items(prose: str, group: budget_mod.Group, start_order: int) -> list[ArticleItem]:
    """Split a group's markdown into ordered article items: H2 heading + its lead body,
    then each `### ` H3 as a heading + body item. Keeps MD/HTML serialization clean.

    Invariant (no H2 may go straight into an H3 with no body): if the model led with a
    `### ` subheading, the first H3's prose is promoted to be the H2's lead paragraph and
    that restating first subheading is dropped — every H2 then has answer-first body."""
    items: list[ArticleItem] = [
        ArticleItem(order=start_order, level="H2", type="content", heading=group.parent.text)
    ]
    order = start_order + 1
    # Split on H3 markers, keeping the heading text.
    parts = re.split(r"(?m)^\s*###\s+(.+?)\s*$", prose.strip())
    lead = parts[0].strip()
    start_idx = 1
    if not lead and len(parts) >= 3:
        # Model opened with a subheading -> promote its prose to the H2 lead, drop the heading.
        lead = parts[2].strip()
        start_idx = 3
    if lead:
        items.append(ArticleItem(order=order, level="none", type="content", body=lead))
        order += 1
    for i in range(start_idx, len(parts), 2):
        h3_text = parts[i].strip()
        h3_body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        items.append(ArticleItem(order=order, level="H3", type="content", heading=h3_text))
        order += 1
        if h3_body:
            items.append(ArticleItem(order=order, level="none", type="content", body=h3_body))
            order += 1
    return items


def _write_faqs(deps: WriterDeps, brief: Brief) -> list[dict]:
    """§5.9 — 40–80 word answer-first answers, self-contained. Questions from the brief."""
    questions = [h.text for h in brief.heading_structure if h.type == "faq-question"]
    if not questions:
        return []
    schema = {
        "type": "object",
        "properties": {"faqs": {"type": "array", "items": {
            "type": "object",
            "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
            "required": ["question", "answer"],
        }}},
        "required": ["faqs"],
    }
    out = deps.section_llm.call_tool(
        system="You write standalone, answer-first FAQ answers (40-80 words). Tool call only.",
        user=(
            f"Keyword: {brief.keyword}\nAnswer each question in 40-80 words, answer-first, "
            "self-contained (no 'as mentioned above'). Use the keyword or its core phrase in "
            "at least two answers.\nQuestions:\n" + "\n".join(f"- {q}" for q in questions)
        ),
        tool_name="faqs", tool_description="The FAQ answers.", input_schema=schema,
        purpose="writer_faqs", max_tokens=2048, temperature=0.5,
    )
    by_q = {(f.get("question") or "").strip(): (f.get("answer") or "").strip()
            for f in (out.get("faqs") or [])}
    # Preserve brief question order; fall back to the question text if the model dropped one.
    return [{"question": q, "answer": by_q.get(q, "")} for q in questions]


def _write_conclusion(deps: WriterDeps, brief: Brief) -> str:
    """§5.10 — 100–150 words, seed keyword present, no CTA inside."""
    return deps.section_llm.complete_text(
        system="You write concise article conclusions. Markdown prose only.",
        user=(
            f"Title: {brief.title}\nKeyword: {brief.keyword}\n"
            "Write a 100-150 word conclusion that synthesizes the article. Include the keyword "
            "once, naturally. Do NOT include a call-to-action. No headings or lists."
        ),
        purpose="writer_conclusion", max_tokens=512, temperature=0.5,
    )


def _write_cta(deps: WriterDeps, brief: Brief) -> str:
    """§5.11 — single sentence ≤30 words, names a next action, never a hard sell."""
    schema = {"type": "object", "properties": {"cta": {"type": "string"}}, "required": ["cta"]}
    try:
        out = deps.short_llm.call_tool(
            system="You write a single-sentence CTA. No hard-sales language. Tool call only.",
            user=(
                f"Title: {brief.title}\nIntent: {brief.intent_type.value}\n"
                "Write ONE sentence (<=30 words) naming a specific next action (read, compare, "
                "evaluate, review, explore...). Never 'buy now' / 'limited time' / 'act today'."
            ),
            tool_name="cta", tool_description="The CTA sentence.", input_schema=schema,
            purpose="writer_cta", max_tokens=128, temperature=0.4,
        )
        cta = (out.get("cta") or "").strip()
    except Exception:  # noqa: BLE001 — short call; fall back to the intent template
        cta = ""
    check = v.validate_cta(cta) if cta else {"ok": False}
    if not check.get("ok"):
        cta = cta_template(brief.intent_type)
    return v.truncate_cta(cta)


def _write_takeaways(deps: WriterDeps, brief: Brief, body_text: str) -> tuple[list[str], str | None]:
    """§5.12 — 3–5 standalone sentences ≤25 words; drop near-duplicate pairs (≥0.85)."""
    schema = {"type": "object", "properties": {
        "takeaways": {"type": "array", "items": {"type": "string"}}}, "required": ["takeaways"]}
    out = deps.section_llm.call_tool(
        system="You extract 3-5 standalone key takeaways. Facts/actionable only. Tool call only.",
        user=(
            f"Title: {brief.title}\nFrom the article below, write 3-5 standalone takeaway "
            "sentences (<=25 words each). No opinion, no marketing, no questions.\n\n"
            f"{body_text[:6000]}"
        ),
        tool_name="takeaways", tool_description="The key takeaways.", input_schema=schema,
        purpose="writer_takeaways", max_tokens=768, temperature=0.4,
    )
    items, code = v.normalize_takeaways(out.get("takeaways") or [])
    if code:
        raise WriterAbort(code, "Key takeaways count invalid (<3)")
    # Drop near-duplicate pairs (§5.12) using embeddings.
    if len(items) > 1:
        vecs = deps.embed_fn(items)
        drop: set[int] = set()
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if i not in drop and j not in drop and _cosine(vecs[i], vecs[j]) >= TAKEAWAY_PAIR_COSINE:
                    drop.add(j)
        items = [t for k, t in enumerate(items) if k not in drop]
    return items, None


# ----- orchestration --------------------------------------------------------


def _content_h2_texts(brief: Brief) -> list[str]:
    return [h.text for h in brief.heading_structure if h.level == "H2" and h.type == "content"]


def generate_article(
    brief: Brief, sie: SieInput, *, warnings: dict, deps: WriterDeps,
    word_budget: int | None = None, coverage_enabled: bool = True,
    timeout_s: float = 90.0, adherence_threshold: float = budget_mod.ADHERENCE_THRESHOLD,
) -> WriterOutput:
    """Run the degraded `1.7-no-context` writer flow and return the §6 WriterOutput.
    `warnings` is the adapter's cross-validation result (no_citations / word_count_conflict).
    Raises WriterAbort on a load-bearing failure (D7) or `generation_timeout` (§7)."""
    started = time.perf_counter()
    budget = word_budget or brief.metadata.get("word_budget") or 2500

    def _check_timeout() -> None:
        if time.perf_counter() - started > timeout_s:
            raise WriterAbort("generation_timeout", f"exceeded {timeout_s}s")

    # Step 1/2 — title anchor + H1 (verbatim).
    title = brief.title
    title_vec = deps.embed_fn([title])[0]

    # Step 3 — topic-adherence filter over content H2s (cosine to title).
    h2_texts = _content_h2_texts(brief)
    scores: dict[int, float] = {}
    if h2_texts:
        h2_vecs = deps.embed_fn(h2_texts)
        vec_by_text = dict(zip(h2_texts, h2_vecs))
        for h in brief.heading_structure:
            if h.level == "H2" and h.type == "content":
                scores[h.order] = _cosine(vec_by_text[h.text], title_vec)
    kept_orders, dropped = budget_mod.drop_low_adherence(
        brief.heading_structure, scores, threshold=adherence_threshold)
    kept_order_set = set(kept_orders)
    kept_groups = [
        g for g in budget_mod.group_headings(brief.heading_structure)
        if g.parent.order in kept_order_set
    ]
    low_h2_flag = len(kept_groups) < 3

    # Step 3 budget allocation (over the kept content structure + conclusion row).
    kept_headings: list[BriefHeading] = []
    for g in kept_groups:
        kept_headings.append(g.parent)
        kept_headings.extend(g.children)
    conclusion_row = next((h for h in brief.heading_structure if h.type == "conclusion"), None)
    if conclusion_row:
        kept_headings.append(conclusion_row)
    alloc = budget_mod.allocate_budget(kept_headings, word_budget=budget)

    # Step 2.5 — intro (after adherence so the preview names kept H2s).
    lede = _enrichment_lede(deps, brief, sie)
    intro = _intro(deps, brief, [g.parent.text for g in kept_groups])
    intro_para = _intro_paragraph(intro)
    _check_timeout()

    # Step 4 — sections (sequential; D8). One Sonnet call per kept H2 group.
    section_items: list[ArticleItem] = []
    under_cited: list[dict] = []
    softened_log: list[dict] = []
    under_length: list[dict] = []
    entity_names = [e.term for e in sie.entities if e.term]
    decision_fit_rendered = False
    order_cursor = 100  # provisional; re-sequenced at assembly
    for g in kept_groups:
        _check_timeout()
        # The whole group (parent H2 + all H3s) is written in one call, so size its budget
        # (and thus max_tokens) from the SUM of the parent + child allocations — not the
        # parent alone, which truncated multi-H3 sections mid-content.
        sec_budget = alloc.get(g.parent.order, budget_mod.SECTION_FLOOR) + sum(
            alloc.get(c.order, 0) for c in g.children)
        if _decision_fit_directive_text(g.parent.format_directive):
            decision_fit_rendered = True
        prose = _write_group(deps, brief, sie, g, sec_budget)

        # §5.8.8 deterministic operational-claim soften (anti-fabrication guard).
        if coverage_enabled:
            prose, n_soft = v.soften_operational_claims(prose)
            citable, cited, ratio = v.coverage_ratio(prose, entities=entity_names)
            if n_soft:
                softened_log.append({"h2_order": g.parent.order, "softened": n_soft})
            if citable and ratio < 0.5:
                under_cited.append({"section_order": g.parent.order, "citable_claims": citable,
                                    "cited_claims": cited, "ratio": round(ratio, 4),
                                    "threshold": 0.5, "operational_claims_softened": n_soft})

        # §5.14 per-H2 body-length floor — one-shot retry for more substance.
        floor = h2_body_floor(brief.intent_type, brief.format_directives.min_h2_body_words)
        if v.word_count(prose) < floor:
            retry = _write_group(
                deps, brief, sie, g, sec_budget,
                retry_directive=(f"The previous draft was too short (floor {floor} words). "
                                 "Add substantive detail (not padding) and expand."),
            )
            if coverage_enabled:
                retry, _ = v.soften_operational_claims(retry)
            prose = retry if v.word_count(retry) > v.word_count(prose) else prose
            if v.word_count(prose) < floor:
                under_length.append({"section_order": g.parent.order,
                                     "word_count": v.word_count(prose), "floor": floor})

        items = _group_to_items(prose, g, order_cursor)
        section_items.extend(items)
        order_cursor += len(items) + 1

    # Step 5 — FAQ.
    faqs = _write_faqs(deps, brief)
    _check_timeout()
    # Step 6 — conclusion + Step 6.4 CTA.
    conclusion = _write_conclusion(deps, brief)
    cta = _write_cta(deps, brief)
    _check_timeout()

    # Step 6.5 — key takeaways (from the assembled body text, generated last).
    body_text = "\n\n".join(it.body for it in section_items if it.body)
    takeaways, _ = _write_takeaways(deps, brief, body_text or title)

    # ----- assembly (display order: H1, takeaways, intro, sections, FAQ, conclusion, CTA) ----
    article: list[ArticleItem] = []

    def _add(level: str, typ: str, heading: str | None = None, body: str = "") -> None:
        article.append(ArticleItem(order=len(article) + 1, level=level, type=typ,
                                   heading=heading, body=body, word_count=v.word_count(body)))

    _add("H1", "title", heading=v.titlecase_heading(title))
    if lede:
        _add("none", "h1-enrichment", body=lede)
    if takeaways:
        _add("none", "key-takeaways", heading="Key Takeaways",
             body="\n".join(f"- {t}" for t in takeaways))
    if intro_para:
        _add("none", "intro", body=intro_para)
    for it in section_items:
        heading = v.titlecase_heading(it.heading) if it.heading else None
        _add(it.level, it.type, heading=heading, body=it.body)
    if faqs:
        _add("H2", "faq-header", heading="Frequently Asked Questions")
        for f in faqs:
            _add("H3", "faq-question", heading=f["question"])
            _add("none", "content", body=f["answer"])
    if conclusion_row:
        _add("H2", "conclusion", heading=v.titlecase_heading(conclusion_row.text))
    if conclusion:
        _add("none", "content", body=conclusion)
    _add("none", "cta", body=cta)

    # §5.13 paragraph-length flags (post-write, deterministic).
    max_sent = brief.format_directives.max_sentences_per_paragraph
    para_violations: list[dict] = []
    for it in article:
        for viol in v.paragraph_violations(it.body, max_sent):
            para_violations.append({"section_order": it.order, **viol})

    # ----- serialize + metadata ----
    article_markdown = to_markdown(article)
    article_html = to_html(article)
    faq_words = sum(it.word_count for it in article if it.type in ("faq-question",) or
                    (it.type == "content" and any(fa["answer"] == it.body for fa in faqs)))
    total_words = sum(it.word_count for it in article)
    gen_ms = round((time.perf_counter() - started) * 1000, 2)

    metadata = {
        "total_word_count": total_words, "word_budget": budget,
        "faq_word_count": faq_words,
        "budget_utilization_pct": round(100 * total_words / budget, 1) if budget else 0.0,
        "word_count_conflict": warnings.get("word_count_conflict", False),
        "no_required_terms": not sie.terms.required,
        "section_count": len(kept_groups), "faq_count": len(faqs),
        "citations_used": 0, "citations_unused": 0, "no_citations": True, "retry_count": 0,
        "dropped_for_low_topic_adherence": dropped,
        "low_h2_count_after_adherence_drop": low_h2_flag,
        "paragraph_length_violations": para_violations,
        "under_cited_sections": under_cited,
        "operational_claims_softened": softened_log,
        "under_length_h2_sections": under_length,
        "icp_callout_judge_status": "not_assigned",
        "decision_fit_rendered": decision_fit_rendered,
        "schema_version": "1.7", "brief_schema_version": "2.6",
        "generation_time_ms": gen_ms,
    }
    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "writer_generate", "keyword": brief.keyword,
               "sections": len(kept_groups), "faqs": len(faqs), "words": total_words,
               "gen_ms": gen_ms},
    )
    return WriterOutput(
        keyword=brief.keyword, intent_type=brief.intent_type, title=title,
        article=article, article_markdown=article_markdown, article_html=article_html,
        key_takeaways=takeaways, intro=intro, cta=cta,
        citation_usage={"total_citations_available": 0, "citations_used": 0,
                        "citations_unused": 0, "usage": []},
        format_compliance={
            "lists_present": article_markdown.count("\n- ") + len(re.findall(r"(?m)^\d+\. ", article_markdown)),
            "tables_present": article_markdown.count("\n|"),
            "lists_required": brief.format_directives.min_lists_per_article if brief.format_directives.require_bulleted_lists else 0,
            "tables_required": brief.format_directives.min_tables_per_article if brief.format_directives.require_tables else 0,
            "answer_first_applied": brief.format_directives.answer_first_paragraphs,
            "directives_satisfied": True,
        },
        brand_voice_card_used=None, brand_conflict_log=[],
        client_context_summary={
            "brand_guide_provided": False, "icp_provided": False,
            "website_analysis_used": False,
            "schema_version_effective": SCHEMA_VERSION_NO_CONTEXT,
        },
        metadata=metadata,
    )
