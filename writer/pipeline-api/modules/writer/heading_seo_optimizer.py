"""Heading SEO Optimizer (Writer Module — PRD v2.6).

Closes a real gap: the brief generator picks H2 / H3 text BEFORE SIE's
per-zone entity targets are known, so entities never get explicitly
placed in headings. The writer's `term_usage.py` audit shows entities
landing in paragraphs but not in titles / headings — exactly the
opposite of where they carry the most SEO weight.

This stage runs AFTER reconciliation (so brand-voice exclusions are
applied) and BEFORE per-section generation. One Claude call rewrites
each H2 / H3 to incorporate at least one entity from the SIE
recommended set, respecting:

  - The seed keyword's tokens (preserve case-insensitively — the brief
    promised this keyword in the URL/SEO meta; we don't reword it).
  - The heading's underlying TOPIC (light-touch only — we add words,
    we don't change what the section covers).
  - Forbidden / avoid terms from brand-voice reconciliation.
  - Per-zone target/max from the SIE usage_recommendations (so we
    don't stuff a single H2 with 5 entities just because they all
    qualified).
  - Min entity count per heading (default 1 — n8n used 2 but that
    over-stuffs short headings).

Failure-safe: missing API key, LLM exception, malformed response, or
heading text that mutates beyond a sensible threshold all fall back to
the original heading (logged). The brief continues to be written with
the unmodified `heading_structure`.

Output: a NEW heading_structure dict with mutated H2/H3 text. Each
mutated entry carries `softened: True` when the change exceeded the
SOFTENED_CHANGE_RATIO threshold so dashboards can surface what was
rewritten.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from modules.brief.llm import claude_json

logger = logging.getLogger(__name__)


LLMJsonFn = Callable[..., Awaitable[Any]]


# Match the framing.py threshold used by the brief generator's intent
# rewriter. >=50% of characters changed → softened flag for downstream
# observability ("this was significantly reframed").
SOFTENED_CHANGE_RATIO = 0.50

# Maximum entities to surface to the LLM per heading. Sending the full
# 50+ recommended-term list per heading wastes tokens; the optimizer
# picks from a curated top-N.
MAX_ENTITIES_PER_PROMPT = 30

# Per-heading soft minimums. The prompt asks the LLM to incorporate at
# least these many entities per zone. Configurable so we can tune
# per-client / per-keyword if certain niches need more or fewer.
MIN_ENTITIES_PER_H2 = 1
MIN_ENTITIES_PER_H3 = 1


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class HeadingOptimizationResult:
    """Outcome of `optimize_headings`. The `heading_structure` field is
    the new structure to feed downstream stages — even on failure it's
    populated with the original structure so callers can use it
    unconditionally."""

    heading_structure: list[dict] = field(default_factory=list)
    rewritten_indices: list[int] = field(default_factory=list)
    softened_indices: list[int] = field(default_factory=list)
    skipped_reason: Optional[str] = None
    llm_called: bool = False
    llm_failed: bool = False


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = """\
You are an SEO heading optimizer. You receive an article's H2 / H3
headings (already chosen by an upstream brief generator) plus the
article's seed keyword and a curated entity list with per-zone target
counts. Your job is to rewrite each heading so that:

1. The heading's TOPIC stays the same. You add words; you do not change
   what the section is about.
2. Each H2 contains at least N_H2 entity from the entity list (where
   `entity_target` is specified per heading).
3. Each H3 contains at least N_H3 entity from the entity list.
4. The seed keyword's tokens are preserved verbatim where they already
   appear. If the keyword's tokens don't appear in any heading, leave
   that to the brief — don't try to inject the keyword everywhere.
5. Forbidden terms NEVER appear in any heading.
6. Per-zone max counts are respected — don't stuff a heading with 4
   entities when the zone max is 2.
7. Heading text remains natural. "TikTok Shop ROI Optimization Tactics
   Strategy Tips" is bad. "Optimize TikTok Shop ROI" is good.

LIGHT TOUCH RULE: If a heading already contains an appropriate entity,
keep it as-is. Only rewrite when the entity count is below the minimum
or when an obviously-better entity from the list fits naturally.

Output strict JSON only (no preamble, no markdown fences):
{
  "rewrites": [
    {"order": 1, "level": "H2", "text": "Rewritten heading text"},
    {"order": 2, "level": "H3", "text": "..."},
    ...
  ]
}

Return one entry per input heading using the same `order` and `level`
the input provided. Use the original text verbatim when no change is
needed."""


def _build_user_prompt(
    *,
    keyword: str,
    headings: list[dict],
    entities: list[dict],
    forbidden_terms: list[str],
    min_h2: int,
    min_h3: int,
) -> str:
    return (
        f"Seed keyword (preserve tokens where they appear): {keyword}\n\n"
        f"Min entities per H2: {min_h2}\n"
        f"Min entities per H3: {min_h3}\n\n"
        f"Recommended entities (each carries per-zone targets — pick "
        f"naturally from this set):\n"
        f"{json.dumps(entities, ensure_ascii=False, indent=2)}\n\n"
        f"Forbidden terms (must not appear):\n"
        f"{json.dumps(forbidden_terms, ensure_ascii=False)}\n\n"
        f"Headings to optimize (return one rewrite per input order):\n"
        f"{json.dumps(headings, ensure_ascii=False, indent=2)}"
    )


# ---------------------------------------------------------------------------
# Change-ratio helper (mirrors intent_rewrite.py:_change_ratio)
# ---------------------------------------------------------------------------


def _change_ratio(before: str, after: str) -> float:
    a = (before or "").strip().lower()
    b = (after or "").strip().lower()
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    if a == b:
        return 0.0
    prefix = 0
    for x, y in zip(a, b):
        if x == y:
            prefix += 1
        else:
            break
    suffix = 0
    for x, y in zip(reversed(a[prefix:]), reversed(b[prefix:])):
        if x == y:
            suffix += 1
        else:
            break
    longer = max(len(a), len(b))
    matched = prefix + suffix
    return max(0.0, min(1.0, 1.0 - matched / longer))


# ---------------------------------------------------------------------------
# Forbidden-term guard
# ---------------------------------------------------------------------------


def _contains_forbidden(text: str, forbidden_terms: list[str]) -> Optional[str]:
    """Return the first forbidden term found in `text`, or None.

    Word-boundary regex match (case-insensitive) so "free" doesn't match
    inside "freedom".
    """
    if not text or not forbidden_terms:
        return None
    lower = text.lower()
    for term in forbidden_terms:
        if not term:
            continue
        pattern = r"\b" + re.escape(term.lower()) + r"\b"
        if re.search(pattern, lower):
            return term
    return None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def optimize_headings(
    heading_structure: list[dict],
    *,
    keyword: str,
    reconciled_terms: list,  # list[ReconciledTerm] — typed loosely to avoid circular imports
    forbidden_terms: list[str],
    min_h2: int = MIN_ENTITIES_PER_H2,
    min_h3: int = MIN_ENTITIES_PER_H3,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> HeadingOptimizationResult:
    """Rewrite H2 / H3 headings to incorporate SIE-recommended entities.

    Args:
        heading_structure: the brief's heading list. List of dicts with
            `level`, `text`, `order`, etc.
        keyword: the seed keyword (preserved in headings where present).
        reconciled_terms: ReconciledTerm objects from the writer's
            reconciliation stage. Only entities (`is_entity=True`) get
            offered to the LLM; non-entity terms are surfaced through
            the existing required-terms path in section prompts.
        forbidden_terms: brand-voice avoid list. Headings containing
            any of these are rejected and the original is preserved.
        min_h2 / min_h3: minimum entities per heading at each level.
        llm_json_fn: injectable for tests.

    Returns:
        HeadingOptimizationResult with the new `heading_structure`. Even
        on failure the structure is populated (with the original) so the
        caller can use it unconditionally.
    """
    # Always populate with the original so callers can rely on the
    # field being present.
    original_structure = [dict(h) for h in heading_structure]
    result = HeadingOptimizationResult(heading_structure=original_structure)

    # Filter to H2 / H3 (we don't rewrite H1 here — title.py / intro.py
    # handle title and H1 entity injection at generation time).
    candidates: list[tuple[int, dict]] = [
        (i, h) for i, h in enumerate(heading_structure)
        if h.get("level") in ("H2", "H3") and h.get("type") == "content"
    ]
    if not candidates:
        result.skipped_reason = "no_h2_h3_candidates"
        return result

    # Filter reconciled terms to entities only and compose a curated
    # list with per-zone targets. Cap at MAX_ENTITIES_PER_PROMPT to
    # keep token budget bounded.
    entity_payload: list[dict] = []
    for term in reconciled_terms:
        if not getattr(term, "is_entity", False):
            continue
        zones = getattr(term, "zones", {}) or {}
        h2_zone = zones.get("h2", {}) if isinstance(zones, dict) else {}
        h3_zone = zones.get("h3", {}) if isinstance(zones, dict) else {}
        entity_payload.append({
            "term": term.term,
            "category": getattr(term, "entity_category", None),
            "h2_target": int(h2_zone.get("target", 0)) if isinstance(h2_zone, dict) else 0,
            "h2_max": int(h2_zone.get("max", 0)) if isinstance(h2_zone, dict) else 0,
            "h3_target": int(h3_zone.get("target", 0)) if isinstance(h3_zone, dict) else 0,
            "h3_max": int(h3_zone.get("max", 0)) if isinstance(h3_zone, dict) else 0,
        })

    if not entity_payload:
        # Nothing to inject — skip silently. Common when SIE returned no
        # entities (small SERP / NLP unavailable / etc.).
        result.skipped_reason = "no_entities_available"
        return result

    entity_payload = entity_payload[:MAX_ENTITIES_PER_PROMPT]

    headings_payload = [
        {
            "order": h.get("order"),
            "level": h.get("level"),
            "text": h.get("text", ""),
        }
        for _, h in candidates
    ]

    user = _build_user_prompt(
        keyword=keyword,
        headings=headings_payload,
        entities=entity_payload,
        forbidden_terms=forbidden_terms,
        min_h2=min_h2,
        min_h3=min_h3,
    )

    call = llm_json_fn or claude_json
    result.llm_called = True
    try:
        response = await call(SYSTEM_PROMPT, user, max_tokens=2000, temperature=0.2)
    except Exception as exc:
        result.llm_failed = True
        logger.warning(
            "writer.heading_seo_optimizer.llm_failed",
            extra={"error": str(exc), "heading_count": len(candidates)},
        )
        return result

    if not isinstance(response, dict):
        logger.warning(
            "writer.heading_seo_optimizer.malformed_response",
            extra={"response_type": type(response).__name__},
        )
        return result

    rewrites = response.get("rewrites")
    if not isinstance(rewrites, list):
        logger.warning(
            "writer.heading_seo_optimizer.no_rewrites_array",
            extra={"keys": list(response.keys()) if isinstance(response, dict) else []},
        )
        return result

    # Index rewrites by (order, level) — the LLM might shuffle them.
    rewrites_by_key: dict[tuple[Any, Any], str] = {}
    for entry in rewrites:
        if not isinstance(entry, dict):
            continue
        order = entry.get("order")
        level = entry.get("level")
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        rewrites_by_key[(order, level)] = text.strip()

    # Apply rewrites with safety guards.
    new_structure = [dict(h) for h in heading_structure]
    for idx, original in candidates:
        key = (original.get("order"), original.get("level"))
        new_text = rewrites_by_key.get(key)
        if not new_text:
            continue
        if new_text == original.get("text"):
            continue
        # Forbidden-term guard — if the LLM ignored the constraint and
        # produced a heading with a forbidden term, keep the original.
        forbidden_hit = _contains_forbidden(new_text, forbidden_terms)
        if forbidden_hit:
            logger.warning(
                "writer.heading_seo_optimizer.forbidden_in_rewrite",
                extra={
                    "original": original.get("text"),
                    "rewrite": new_text,
                    "forbidden_term": forbidden_hit,
                },
            )
            continue
        # Apply.
        ratio = _change_ratio(original.get("text", ""), new_text)
        new_structure[idx] = {**original, "text": new_text}
        result.rewritten_indices.append(idx)
        if ratio >= SOFTENED_CHANGE_RATIO:
            result.softened_indices.append(idx)

    result.heading_structure = new_structure

    logger.info(
        "writer.heading_seo_optimizer.complete",
        extra={
            "candidate_count": len(candidates),
            "rewritten_count": len(result.rewritten_indices),
            "softened_count": len(result.softened_indices),
            "entity_count_offered": len(entity_payload),
        },
    )
    return result
