"""Manual (pasted / uploaded) reference page structures.

The scraper path (`page_structure_scraper`) needs a live URL: it fetches one of
the client's own pages and *measures* its structure. That's unavailable for a
client with no website yet — a LeadOff market pick, a rebuild, or an onboarding
where all we have is a brand guide and a page-structure spec document. Those
clients could configure nothing, so every mirroring path (Local SEO, ecommerce
product, service/location, the blog opening) silently degraded to "no reference".

This module closes that gap by accepting the structure as TEXT — pasted into the
client form or lifted out of an uploaded .docx/.pdf by the existing file parser —
and parsing it into the SAME analysis shape the scraper produces:

    {"outline": [{heading, level, intent, intent_note, word_count?, blocks?}],
     "structure_summary": str, "elements": {...}}

Because the shape is identical, nothing downstream changes: `usable_analysis`,
`page_structure_render`, the structural-fidelity gate, and the eval all consume a
manual entry exactly as they consume a scraped one.

**The provenance difference that matters.** For a scraped page the word counts
and block composition are *measured* off the DOM, so they're exact and the
renderer emits them as hard targets. A spec document has no DOM to measure. So
the rule here is the mirror image of the scraper's "the LLM never counts": the
LLM never *invents* a count either. It extracts a word count or block count ONLY
where the guidelines state one, and omits it otherwise. A guideline that says
"Hero — 80-120 words, headline + subhead + CTA button" yields a real target; one
that says "Hero section" yields a section with intent and no size target. Both
degrade correctly:

  - `page_structure_render` skips the word/block target lines for sections that
    have none (see `_render_full`), so the prompt never states a hollow target.
  - `page_structure_eval._word_fit_score` returns a free 100 when the reference
    carries no counts at all, so the structural gate can't burn regeneration
    passes chasing numbers the client never specified.

An invented number would be worse than no number: it would be enforced by the
gate as though the client had asked for it.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from services.page_structure_eval import _derive_elements
from services.page_structure_scraper import INTENT_TAGS

logger = logging.getLogger(__name__)

# Block-type vocabulary the deterministic extractor emits (page_structure_eval).
# The LLM MUST use these exact names: `score_structural_fidelity` scores block
# coverage as a set intersection of type names, so a synonym ("bullet list" vs
# "list") reads as a missing block and would drive pointless regeneration passes.
BLOCK_TYPES = ("paragraph", "list", "table", "quote", "image", "code", "cta", "faq")

# Heading levels the outline uses (H1 is the page title; specs describe H2/H3).
_LEVELS = ("H1", "H2", "H3")

# Guard against a runaway parse — a spec should describe a page, not a book.
_MAX_SECTIONS = 60

# The guidelines text is a human document; bound what we send to the model.
_MAX_TEXT_CHARS = 40_000


_SYSTEM_PROMPT = (
    "You convert a written PAGE STRUCTURE SPECIFICATION into a structured outline.\n\n"
    "The input is a human-authored document describing how a page of this type "
    "should be laid out — section by section. It is NOT a web page and NOT an "
    "article: do not summarize its prose, do not write any page copy, and do not "
    "invent sections it does not describe.\n\n"
    "Your job is to express what the document ALREADY SAYS as JSON.\n\n"
    "CRITICAL RULE — NEVER INVENT NUMBERS.\n"
    "  - Include `word_count` for a section ONLY if the document states a length "
    "for it (a number, or a range like '80-120 words' → use the midpoint, or "
    "'about 2 paragraphs' → do NOT convert that to words, omit it).\n"
    "  - Include `blocks` for a section ONLY for content blocks the document "
    "actually calls for. Include a block's `count`/`items` ONLY if stated "
    "(e.g. 'a 5-item checklist' → {\"type\": \"list\", \"count\": 1, \"items\": 5}; "
    "'a bulleted list' → {\"type\": \"list\", \"count\": 1}).\n"
    "  - Omitting a field is ALWAYS correct when the document is silent. A "
    "guessed number becomes a hard target the writer is held to, so a guess is "
    "actively harmful. Omit it.\n\n"
    "For every section the document describes, in the order it describes them, return:\n"
    "  - `heading`: a GENERALIZED section label (strip any specific brand, product, "
    "or place name so it reads as a reusable slot name).\n"
    "  - `level`: \"H2\" for a main section, \"H3\" for a sub-section nested under "
    "the previous main one.\n"
    "  - `intent`: the section's purpose, EXACTLY ONE tag from this fixed list:\n"
    "      " + ", ".join(INTENT_TAGS) + "\n"
    "  - `intent_note`: <= 12 words on what the section does.\n"
    "  - `word_count` (optional, integer): see the CRITICAL RULE.\n"
    "  - `blocks` (optional): content blocks the section must contain, each "
    "{\"type\": <one of: " + ", ".join(BLOCK_TYPES) + ">, \"count\": <int, optional>, "
    "\"items\": <int, optional>}. Use ONLY those type names. Map synonyms onto "
    "them: bullets/checklist/steps → \"list\"; comparison chart/spec grid → "
    "\"table\"; testimonial/pull quote → \"quote\"; button/contact prompt → "
    "\"cta\"; question-and-answer block → \"faq\"; body copy → \"paragraph\".\n\n"
    "Return ONLY valid JSON matching this exact schema — no prose, no markdown fences:\n"
    "{\n"
    '  "sections": [\n'
    '    {"heading": "...", "level": "H2", "intent": "<one tag>", "intent_note": "...", '
    '"word_count": <int, omit if unstated>, "blocks": [{"type": "list", "items": 5}]}\n'
    "  ],\n"
    '  "structure_summary": "2-5 sentence plain-English description of how the page is '
    'organized: the opening pattern, the order and purpose of the main sections, recurring '
    'content blocks, and how it closes.",\n'
    '  "intro_pattern": "short description of how the page opens, if the document says '
    "(e.g. 'direct answer then context', 'problem framing', 'hero statement + value prop'); "
    'empty string if it does not"\n'
    "}\n\n"
    "If the document does not actually describe a page structure, return an empty "
    "sections list and say so in structure_summary."
)


def _coerce_blocks(raw: Any) -> list[dict[str, Any]]:
    """Normalize the LLM's `blocks` onto the deterministic extractor's shape.

    Drops unknown types (rather than passing a synonym through, which would read
    as a missing block at scoring time) and drops non-positive counts. Pure."""
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for b in raw:
        if not isinstance(b, dict):
            continue
        btype = str(b.get("type") or "").strip().lower()
        if btype not in BLOCK_TYPES:
            continue
        block: dict[str, Any] = {"type": btype}
        count = b.get("count")
        block["count"] = count if isinstance(count, int) and count > 0 else 1
        items = b.get("items")
        if isinstance(items, int) and items > 0:
            block["items"] = items
        # `words` is deliberately never set: the deterministic pass measures it
        # off real prose, and a spec's per-block word split is virtually never
        # stated. The section-level `word_count` carries the size signal.
        out.append(block)
    return out


def normalize_sections(raw: Any) -> list[dict[str, Any]]:
    """Coerce the LLM's `sections` into outline items matching the scraper's
    schema. Sections without a heading are dropped (the renderer and the eval
    both key on headings). Pure — no I/O."""
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for entry in raw[:_MAX_SECTIONS]:
        if not isinstance(entry, dict):
            continue
        heading = str(entry.get("heading") or "").strip()
        if not heading:
            continue
        level = str(entry.get("level") or "H2").strip().upper()
        item: dict[str, Any] = {
            "heading": heading,
            "level": level if level in _LEVELS else "H2",
        }
        intent = str(entry.get("intent") or "").strip().lower()
        item["intent"] = intent if intent in INTENT_TAGS else "other"
        note = str(entry.get("intent_note") or "").strip()
        if note:
            item["intent_note"] = note
        # Only carry a size target the document actually stated.
        words = entry.get("word_count")
        if isinstance(words, int) and words > 0:
            item["word_count"] = words
        blocks = _coerce_blocks(entry.get("blocks"))
        if blocks:
            item["blocks"] = blocks
        out.append(item)
    return out


def build_analysis(parsed: Any, guidelines_text: str) -> dict[str, Any]:
    """Assemble the stored analysis from the LLM's parse.

    `elements` is derived DETERMINISTICALLY from the normalized outline via the
    same helper the scraper's extractor uses, so the element vocabulary can't
    drift between the two capture paths. The guidelines text is passed as the
    element deriver's full-text input so a spec that calls for a CTA in prose
    (without a tagged block) still sets `has_cta`. Pure — no I/O."""
    if not isinstance(parsed, dict):
        parsed = {}
    outline = normalize_sections(parsed.get("sections"))
    elements = dict(_derive_elements(outline, guidelines_text or ""))
    # `_derive_elements` sums the per-section counts, which is right for a scrape
    # (every section is measured) but WRONG here when the spec sized only some
    # sections: the partial sum would render as "aim for roughly N total words"
    # and squeeze the whole page down to the size of its documented parts. A
    # total is only meaningful when every section carries a count.
    if any("word_count" not in it for it in outline):
        elements["approx_total_words"] = 0
    # A section's declared intent is as strong a signal as a tagged block.
    intents = {str(it.get("intent") or "") for it in outline}
    if "faq" in intents:
        elements["has_faq"] = True
    if "cta" in intents:
        elements["has_cta"] = True
    intro_pattern = str(parsed.get("intro_pattern") or "").strip()
    if intro_pattern:
        elements["intro_pattern"] = intro_pattern
    return {
        "outline": outline,
        "structure_summary": str(parsed.get("structure_summary") or "").strip(),
        "elements": elements,
    }


def _strip_fences(raw: str) -> str:
    """Unwrap a ```json fenced response. Pure."""
    text = (raw or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


async def parse_guidelines(guidelines_text: str, page_type: str) -> dict[str, Any]:
    """Parse a written page-structure specification into the stored analysis shape.

    Returns the same {"outline", "structure_summary", "elements"} dict the
    scraper's `analyze_page_structure` returns. Raises on an unusable parse so
    the job records a real failure — unlike the scraper's LLM pass (a pure
    annotation layer over a deterministic outline that stands on its own), the
    LLM IS the whole extraction here, so degrading to empty would silently store
    a complete-but-useless reference."""
    text = (guidelines_text or "").strip()
    if not text:
        raise ValueError("No page structure guidelines provided")
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS]

    from services import report_llm

    # Same provider path as the scraper's annotation pass: Anthropic with an
    # automatic OpenAI→Gemini fallback on a transient failure.
    raw = await report_llm.generate_text(
        system=_SYSTEM_PROMPT,
        user=f"Reference page type: {page_type}\n\nPage structure specification:\n\n{text}",
        model="claude-sonnet-4-6",
        max_tokens=4096,
        log_tag="page_structure_manual",
    )
    try:
        parsed = json.loads(_strip_fences(raw))
    except json.JSONDecodeError:
        logger.warning(
            "page_structure_manual.json_parse_failed",
            extra={"page_type": page_type, "raw_len": len(raw or "")},
        )
        raise ValueError("Could not parse the page structure guidelines")
    if not isinstance(parsed, dict):
        # Valid JSON is not necessarily an object — a bare `null` parses fine.
        raise ValueError("Could not parse the page structure guidelines")

    analysis = build_analysis(parsed, text)
    if not analysis["outline"]:
        raise ValueError(
            "No page sections found in the guidelines — describe the page "
            "section by section (e.g. 'Hero — 80 words', 'Services offered — 3 items')"
        )
    return analysis
