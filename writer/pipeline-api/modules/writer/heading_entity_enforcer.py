"""Step 6.6 - Heading main-entity enforcement (AIO Heading Optimization §X.4).

Runs AFTER the Heading SEO Optimizer (which is where heading text is
actually finalized - see writer pipeline). Ensures every content H2 carries
the brief's `main_entity` (canonical or a variant). This is the
high-confidence half of the AIO study (entity presence); the low-confidence
"exactly one point per heading" rule is intentionally NOT enforced - it
fights the SEO optimizer's multi-term injection (per owner decision).

Scope: H2 only this version (H3 deferred, §X.7 #3). Behavior is
warn-and-accept: a heading the rewrite can't fix is left as-is and counted
as a violation - the run never aborts. No-op when `main_entity` is absent
(briefs < schema 2.7), so output is unchanged for older briefs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

RewriteFn = Callable[[str, str, list[str]], Awaitable[str]]

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    text = _PUNCT_RE.sub(" ", (text or "").lower())
    return _WS_RE.sub(" ", text).strip()


def _tokens(text: str) -> set[str]:
    return set(_normalize(text).split())


def is_entity_present(heading: str, canonical: str, variants: list[str]) -> bool:
    """True when the heading carries the entity. Deterministic match:
    normalized substring OR entity-token-set ⊆ heading-token-set (handles
    word-order variants like '327 angel number' vs 'angel number 327')."""
    norm_heading = _normalize(heading)
    heading_tokens = set(norm_heading.split())
    forms = [canonical, *variants]
    for form in forms:
        nf = _normalize(form)
        if not nf:
            continue
        if nf in norm_heading:
            return True
        form_tokens = set(nf.split())
        if form_tokens and form_tokens <= heading_tokens:
            return True
    return False


@dataclass
class HeadingEntityResult:
    heading_structure: list[dict]
    main_entity_used: Optional[str] = None
    enforced_count: int = 0       # content H2s that carry the entity (incl. fixed)
    rewrites_applied: int = 0     # content H2s the rewrite changed
    violation_count: int = 0      # content H2s still missing the entity after retry
    flagged: list[dict] = field(default_factory=list)


async def enforce_heading_entities(
    heading_structure: list[dict],
    main_entity: Optional[dict],
    *,
    forbidden_terms: Optional[list[str]] = None,
    rewrite_fn: Optional[RewriteFn] = None,
) -> HeadingEntityResult:
    """Ensure every content H2 carries `main_entity`. `main_entity` is the
    brief's MainEntity dumped to a dict (canonical/variants/...). Returns a
    new heading_structure (originals untouched on no-op)."""
    result = HeadingEntityResult(heading_structure=heading_structure)

    if not main_entity:
        return result
    canonical = (main_entity.get("canonical") or "").strip()
    if not canonical:
        return result
    variants = [v for v in (main_entity.get("variants") or []) if v]
    result.main_entity_used = canonical
    forbidden = forbidden_terms or []
    rewrite = rewrite_fn or _claude_rewrite

    new_structure = [dict(h) if isinstance(h, dict) else h for h in heading_structure]

    for idx, h in enumerate(new_structure):
        if not isinstance(h, dict):
            continue
        if h.get("level") != "H2" or h.get("type") != "content":
            continue
        original_text = (h.get("text") or "").strip()
        if not original_text:
            continue

        if is_entity_present(original_text, canonical, variants):
            result.enforced_count += 1
            continue

        # Missing - one rewrite attempt, then warn-and-accept.
        try:
            rewritten = (await rewrite(original_text, canonical, forbidden) or "").strip()
        except Exception as exc:  # rewrite is best-effort; never abort
            logger.warning(
                "writer.heading_entity.rewrite_failed",
                extra={"error": str(exc), "order": h.get("order")},
            )
            rewritten = ""

        if rewritten and is_entity_present(rewritten, canonical, variants):
            new_structure[idx] = {**h, "text": rewritten}
            result.rewrites_applied += 1
            result.enforced_count += 1
        else:
            result.violation_count += 1
            result.flagged.append({
                "order": h.get("order"),
                "text": original_text,
            })
            logger.warning(
                "writer.heading_entity.violation",
                extra={"order": h.get("order"), "entity": canonical},
            )

    result.heading_structure = new_structure
    return result


async def _claude_rewrite(heading: str, entity: str, forbidden_terms: list[str]) -> str:
    """Rewrite `heading` so it naturally names `entity`, preserving meaning.
    Imported lazily to keep this module unit-testable without the LLM client."""
    from modules.brief.llm import claude_json

    forbidden_clause = (
        f" Do not use any of these terms: {', '.join(forbidden_terms[:20])}."
        if forbidden_terms else ""
    )
    system = (
        "You rewrite a single blog-post H2 heading so it explicitly names the "
        "given main entity, while preserving the heading's original meaning and "
        "specific point. Keep it concise and in title case. Do not add a second "
        "topic. Do not use em dashes." + forbidden_clause +
        ' Return only JSON: {"text": "<rewritten heading>"}'
    )
    user = f'MAIN_ENTITY: {entity}\nHEADING: {heading}\n\nRewrite the heading now.'
    result = await claude_json(system, user, max_tokens=120, temperature=0.2)
    if isinstance(result, dict):
        return (result.get("text") or "").strip()
    return ""
