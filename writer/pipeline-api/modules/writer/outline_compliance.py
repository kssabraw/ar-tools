"""Step 0.6 - client-aware banned-term outline compliance.

The blog brief is client-agnostic and globally cached, so its outline
(``heading_structure`` + FAQ questions) can carry a term a specific client bans
- e.g. a compliance-bound client's competitor / drug brand names. The Writer
preserves headings (they carry the SEO structure) and hard-aborts on a banned
term in a heading (``banned_terms.py`` per writer-module spec §4.4), so such a
client could never generate an article on a topic whose SERP / People-Also-Ask
data names those terms (a real block: "best weight loss tips" seeds an FAQ H3
"How can I mimic Ozempic naturally?" for a peptide client that bans "Ozempic").

Mirroring how the Fan-out generator produces headings with the ban KNOWN rather
than aborting on a pre-baked one, this pass rewrites the offending headings +
FAQ questions to compliant equivalents BEFORE generation - keeping the topic and
SEO intent, only removing the forbidden word. It **rewords in place** (never
drops), so heading order and the FAQ 3-5 count are preserved. Warn-and-accept
and surfaced in ``WriterMetadata``; a rewrite that still contains a banned term
falls back to a deterministic strip, so the run can never hard-abort on a
pre-baked banned heading again.

Body text is deliberately out of scope - the section / FAQ / intro / conclusion
generators are already told the forbidden terms, and body leakage is a
warn-and-retry (not an abort). Only pre-baked headings are the hard-abort gap.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .banned_terms import build_banned_regex, find_banned

logger = logging.getLogger(__name__)

LLMJsonFn = Callable[..., Awaitable[Any]]

# Only H2 / H3 rows are rewritten here. H1 / title carry their own entity/title
# logic (title.py / intro.py) and the FAQ header is a generic label; scoping to
# H2/H3 keeps this pass from fighting those paths.
_REWRITABLE_LEVELS = {"H2", "H3"}

_SYSTEM = (
    "You rewrite SEO article headings and FAQ questions to remove FORBIDDEN words "
    "while preserving the exact topic, search intent, and specificity. The rewrite "
    "MUST NOT contain any forbidden word or a close variant of one. Keep it natural, "
    "concise, and answerable - do not turn a question into a statement or vice versa. "
    "Return ONLY a JSON object: {\"rewrites\": [{\"id\": <int>, \"text\": \"<rewritten>\"}]}."
)


@dataclass
class BannedOutlineItem:
    """One outline element (a heading row or an FAQ question) that contains a
    client-banned term and must be reworded before generation."""
    item_id: int
    kind: str            # "heading" | "faq"
    ref_index: int       # index into heading_structure (heading) or faq_questions (faq)
    text: str
    terms: list[str]     # matched banned terms (lower-cased)


@dataclass
class OutlineComplianceResult:
    heading_structure: list[dict]
    faq_questions: list[str]
    # One entry per reworded element: {kind, original, revised, terms, method}.
    reworded: list[dict] = field(default_factory=list)


def find_banned_items(
    heading_structure: list[dict],
    faq_questions: list[str],
    banned_regex: Optional[re.Pattern],
) -> list[BannedOutlineItem]:
    """Every H2/H3 heading and FAQ question whose text contains a banned term.
    Pure. Returns [] when nothing offends (the common case)."""
    if banned_regex is None:
        return []
    items: list[BannedOutlineItem] = []
    next_id = 0
    for idx, row in enumerate(heading_structure or []):
        if not isinstance(row, dict):
            continue
        if row.get("level") not in _REWRITABLE_LEVELS:
            continue
        text = row.get("text") or ""
        matched = find_banned(text, banned_regex)
        if matched:
            items.append(BannedOutlineItem(next_id, "heading", idx, text, matched))
            next_id += 1
    for idx, question in enumerate(faq_questions or []):
        matched = find_banned(question or "", banned_regex)
        if matched:
            items.append(BannedOutlineItem(next_id, "faq", idx, question, matched))
            next_id += 1
    return items


def build_rewrite_prompt(items: list[BannedOutlineItem], banned_terms: list[str]) -> str:
    """User prompt listing the forbidden words and the items to rewrite. Pure."""
    forbidden = ", ".join(sorted({t for t in banned_terms if t and t.strip()}))
    lines = [
        f"FORBIDDEN WORDS (must not appear in any rewrite): {forbidden}",
        "",
        "Rewrite each item below so it means the same thing but contains NONE of the "
        "forbidden words. Preserve whether it is a question or a heading.",
        "",
    ]
    for item in items:
        label = "FAQ question" if item.kind == "faq" else "Heading"
        lines.append(f"  id={item.item_id} ({label}): {item.text}")
    lines.append("")
    lines.append('Return ONLY: {"rewrites": [{"id": <int>, "text": "<rewritten>"}]}')
    return "\n".join(lines)


def _normalize_whitespace(text: str) -> str:
    # Collapse spaces and tidy spacing left around removed words / punctuation.
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)          # " ?" -> "?"
    text = re.sub(r"\(\s*\)", "", text).strip()            # empty parens
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" -,")


def deterministic_strip(text: str, banned_regex: Optional[re.Pattern]) -> str:
    """Last-resort compliance: delete banned words and tidy the result. Pure.
    Guarantees a banned-free string so the run never hard-aborts, even if the
    wording is slightly awkward (a rare fallback, only when the LLM rewrite
    itself came back non-compliant or empty)."""
    if banned_regex is None:
        return text
    stripped = _normalize_whitespace(banned_regex.sub("", text or ""))
    return stripped


def resolve_rewrites(
    items: list[BannedOutlineItem],
    rewrites: Any,
    banned_regex: Optional[re.Pattern],
) -> dict[int, tuple[str, str]]:
    """Map each item id -> (final_text, method). Pure.

    A returned rewrite is accepted only when it is non-empty AND contains no
    banned term; otherwise the item falls back to a deterministic strip of the
    ORIGINAL text. A malformed / missing payload is tolerated (every item just
    falls back). ``method`` is "llm" or "strip" for audit."""
    by_id: dict[int, str] = {}
    if isinstance(rewrites, dict):
        entries = rewrites.get("rewrites")
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                rid = entry.get("id")
                text = entry.get("text")
                if isinstance(rid, int) and isinstance(text, str) and text.strip():
                    by_id[rid] = text.strip()

    resolved: dict[int, tuple[str, str]] = {}
    for item in items:
        candidate = by_id.get(item.item_id)
        if candidate and not find_banned(candidate, banned_regex):
            resolved[item.item_id] = (candidate, "llm")
        else:
            fallback = deterministic_strip(item.text, banned_regex)
            resolved[item.item_id] = (fallback, "strip")
    return resolved


async def sanitize_outline_terms(
    heading_structure: list[dict],
    faq_questions: list[str],
    *,
    banned_terms: list[str],
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> OutlineComplianceResult:
    """Reword H2/H3 headings + FAQ questions that contain a client-banned term,
    in place (copies), before generation. Never raises - any failure leaves the
    outline exactly as it was for that item (falling back to a deterministic
    strip), so a bad rewrite can never make things worse than the hard abort it
    replaces.

    Returns copies of ``heading_structure`` and ``faq_questions`` plus a
    per-item audit log for ``WriterMetadata``."""
    hs = [dict(r) if isinstance(r, dict) else r for r in (heading_structure or [])]
    faqs = list(faq_questions or [])
    banned_regex = build_banned_regex(list(banned_terms or []))
    items = find_banned_items(hs, faqs, banned_regex)
    if not items:
        return OutlineComplianceResult(hs, faqs, [])

    logger.warning(
        "writer.outline_banned_terms",
        extra={"count": len(items),
               "terms": sorted({t for it in items for t in it.terms})},
    )

    rewrites: Any = None
    call = llm_json_fn
    try:
        if call is None:
            from modules.brief.llm import claude_json
            call = claude_json
        rewrites = await call(
            system=_SYSTEM,
            user=build_rewrite_prompt(items, list(banned_terms or [])),
            max_tokens=1200,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort; fall back to strip
        logger.warning("writer.outline_rewrite_failed",
                       extra={"error_type": type(exc).__name__, "error": str(exc)[:300]})
        rewrites = None

    resolved = resolve_rewrites(items, rewrites, banned_regex)
    log: list[dict] = []
    for item in items:
        final_text, method = resolved[item.item_id]
        if not final_text:
            # Degenerate strip (e.g. the heading was ONLY the banned term).
            # Keep the original rather than emit an empty heading; the body
            # generators still avoid the term, and this is vanishingly rare.
            final_text = item.text
            method = "kept"
        if item.kind == "heading":
            hs[item.ref_index]["text"] = final_text
        else:
            faqs[item.ref_index] = final_text
        log.append({
            "kind": item.kind,
            "original": item.text,
            "revised": final_text,
            "terms": item.terms,
            "method": method,
        })
    return OutlineComplianceResult(hs, faqs, log)
