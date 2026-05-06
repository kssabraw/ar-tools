"""Heading SEO Optimizer (Writer Module - PRD v2.6).

Closes a real gap: the brief generator picks H2 / H3 text BEFORE SIE's
per-zone entity targets are known, so entities never get explicitly
placed in headings. The writer's `term_usage.py` audit shows entities
landing in paragraphs but not in titles / headings - exactly the
opposite of where they carry the most SEO weight.

This stage runs AFTER reconciliation (so brand-voice exclusions are
applied) and BEFORE per-section generation. One Claude call rewrites
each H2 / H3 to incorporate at least one entity from the SIE
recommended set, respecting:

  - The seed keyword's tokens (preserve case-insensitively - the brief
    promised this keyword in the URL/SEO meta; we don't reword it).
  - The heading's underlying TOPIC (light-touch only - we add words,
    we don't change what the section covers).
  - Forbidden / avoid terms from brand-voice reconciliation.
  - Per-zone target/max from the SIE usage_recommendations (so we
    don't stuff a single H2 with 5 entities just because they all
    qualified).
  - Min entity count per heading (default 1 - n8n used 2 but that
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


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class HeadingOptimizationResult:
    """Outcome of `optimize_headings`. The `heading_structure` field is
    the new structure to feed downstream stages - even on failure it's
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
headings (already chosen by an upstream brief generator) plus three
category-bucketed term lists (entities, related keywords, keyword
variants) and aggregate target counts for the subheadings zone (H2 +
H3 combined). Your job is to rewrite each heading so that:

1. The heading's TOPIC stays the same. You add words; you do not change
   what the section is about.
2. Across all H2 + H3 headings combined, the rewrites carry at least
   the target distinct count per category (entities target, related
   keywords target, keyword variants target). Distribute naturally -
   not every heading needs items from every category.
3. The seed keyword's tokens are preserved verbatim where they already
   appear. If the keyword's tokens don't appear in any heading, leave
   that to the brief - don't try to inject the keyword everywhere.
4. Forbidden terms NEVER appear in any heading.
5. Heading text remains natural. "TikTok Shop ROI Optimization Tactics
   Strategy Tips" is bad. "Optimize TikTok Shop ROI" is good.

LIGHT TOUCH RULE: If a heading already contains an appropriate term
from any category, keep it as-is. Only rewrite when the aggregate
category count is below target or when an obviously-better term from
the list fits naturally.

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
    related_keywords: list[str],
    keyword_variants: list[str],
    forbidden_terms: list[str],
    subheadings_targets: dict[str, int],
) -> str:
    targets_block = json.dumps({
        "entities": int(subheadings_targets.get("entities", 0) or 0),
        "related_keywords": int(subheadings_targets.get("related_keywords", 0) or 0),
        "keyword_variants": int(subheadings_targets.get("keyword_variants", 0) or 0),
    }, ensure_ascii=False)
    return (
        f"Seed keyword (preserve tokens where they appear): {keyword}\n\n"
        f"Subheadings (H2 + H3 combined) aggregate targets - distinct\n"
        f"counts the rewrites must hit across ALL headings:\n"
        f"{targets_block}\n\n"
        f"Recommended entities (each carries metadata; pick naturally\n"
        f"from this set):\n"
        f"{json.dumps(entities, ensure_ascii=False, indent=2)}\n\n"
        f"Related keywords:\n"
        f"{json.dumps(related_keywords, ensure_ascii=False)}\n\n"
        f"Keyword variants (seed-keyword echoes - usable as headings\n"
        f"where natural, but don't force them into every H3):\n"
        f"{json.dumps(keyword_variants, ensure_ascii=False)}\n\n"
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
    inside "freedom". Convenience wrapper that compiles a fresh regex
    each call - for the inner loop in `optimize_headings`, callers
    should use `_compile_forbidden_pattern` once and re-use it via
    `_match_forbidden_compiled` to avoid recompiling per heading.
    """
    if not text or not forbidden_terms:
        return None
    pattern = _compile_forbidden_pattern(forbidden_terms)
    if pattern is None:
        return None
    return _match_forbidden_compiled(text, pattern, forbidden_terms)


def _compile_forbidden_pattern(forbidden_terms: list[str]) -> Optional[re.Pattern]:
    """Compile a single combined word-boundary regex over all forbidden
    terms. Returns None when the list is effectively empty so callers
    can short-circuit. Compiled once per `optimize_headings` call,
    reused across every rewrite candidate."""
    cleaned = [t for t in (forbidden_terms or []) if t]
    if not cleaned:
        return None
    # De-dupe to avoid wasted alternation branches when the same term
    # surfaces from both brand_voice_card.banned_terms and
    # filtered_terms.avoid (common - they overlap).
    deduped = sorted(set(t.lower() for t in cleaned), key=len, reverse=True)
    alternation = "|".join(re.escape(t) for t in deduped)
    return re.compile(rf"\b({alternation})\b", re.IGNORECASE)


def _match_forbidden_compiled(
    text: str, pattern: re.Pattern, forbidden_terms: list[str],
) -> Optional[str]:
    """Look up the matched forbidden term using a pre-compiled pattern.
    Returns the canonical term from `forbidden_terms` (preserving the
    caller's casing for logs) when matched, else None."""
    if not text:
        return None
    m = pattern.search(text)
    if not m:
        return None
    matched_lower = m.group(1).lower()
    for orig in forbidden_terms or []:
        if orig and orig.lower() == matched_lower:
            return orig
    return matched_lower


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def optimize_headings(
    heading_structure: list[dict],
    *,
    keyword: str,
    reconciled_terms: list,  # list[ReconciledTerm] - typed loosely to avoid circular imports
    forbidden_terms: list[str],
    subheadings_targets: Optional[dict[str, int]] = None,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> HeadingOptimizationResult:
    """Rewrite H2 / H3 headings to incorporate SIE-recommended terms.

    SIE v1.4 - three-bucket category injection. The optimizer offers
    the LLM three category-bucketed term lists (entities, related
    keywords, keyword variants) and an aggregate target across the
    H2 + H3 zone (`subheadings_targets`). Keyword variants ARE included
    at the user's spec - they're explicit injection candidates, not
    keyword echoes to be filtered out.

    Args:
        heading_structure: the brief's heading list. List of dicts with
            `level`, `text`, `order`, etc.
        keyword: the seed keyword (preserved in headings where present).
        reconciled_terms: ReconciledTerm objects from the writer's
            reconciliation stage. Bucketed by is_entity / is_seed_fragment
            into entities / keyword_variants / related_keywords.
        forbidden_terms: brand-voice avoid list. Headings containing
            any of these are rejected and the original is preserved.
        subheadings_targets: SIE v1.4 zone aggregate keyed by category;
            sum of h2 + h3 zone aggregates from
            `sie.zone_category_targets`. Defaults to all-zero when None.
        llm_json_fn: injectable for tests.

    Returns:
        HeadingOptimizationResult with the new `heading_structure`. Even
        on failure the structure is populated (with the original) so the
        caller can use it unconditionally.
    """
    # Defensive None-guards. Type hints say `list` but Python doesn't
    # enforce, and callers may pass None when SIE / reconciliation
    # short-circuited.
    reconciled_terms = reconciled_terms or []
    forbidden_terms = forbidden_terms or []
    subheadings_targets = subheadings_targets or {
        "entities": 0, "related_keywords": 0, "keyword_variants": 0,
    }

    # Always populate with the original so callers can rely on the
    # field being present.
    original_structure = [dict(h) for h in heading_structure]
    result = HeadingOptimizationResult(heading_structure=original_structure)

    # Filter to H2 / H3 (we don't rewrite H1 here - title.py / intro.py
    # handle title and H1 entity injection at generation time).
    candidates: list[tuple[int, dict]] = [
        (i, h) for i, h in enumerate(heading_structure)
        if h.get("level") in ("H2", "H3") and h.get("type") == "content"
    ]
    if not candidates:
        result.skipped_reason = "no_h2_h3_candidates"
        return result

    # Bucket reconciled terms into the v1.4 three categories.
    entity_payload: list[dict] = []
    related_keywords: list[str] = []
    keyword_variants: list[str] = []
    for term in reconciled_terms:
        term_str = getattr(term, "term", None)
        if not term_str:
            continue
        if getattr(term, "is_entity", False):
            entity_payload.append({
                "term": term_str,
                "category": getattr(term, "entity_category", None),
            })
        elif getattr(term, "is_seed_fragment", False):
            keyword_variants.append(term_str)
        else:
            related_keywords.append(term_str)

    # Truncate per-category to keep prompt token budget bounded.
    entity_payload = entity_payload[:MAX_ENTITIES_PER_PROMPT]
    related_keywords = related_keywords[:MAX_ENTITIES_PER_PROMPT]
    keyword_variants = keyword_variants[:15]

    if not (entity_payload or related_keywords or keyword_variants):
        # Nothing to inject across any category - skip silently.
        result.skipped_reason = "no_terms_available"
        return result

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
        related_keywords=related_keywords,
        keyword_variants=keyword_variants,
        forbidden_terms=forbidden_terms,
        subheadings_targets=subheadings_targets,
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

    # Index rewrites by (order, level). Normalize both sides to handle
    # LLM-side type drift: returning `"order": "1"` (string) instead of
    # `1` (int), or `"level": "h2"` (lower) instead of `"H2"` (upper).
    # Without normalization the lookup silently misses and we drop a
    # rewrite that the LLM actually produced.
    def _normalize_key(order: Any, level: Any) -> Optional[tuple[int, str]]:
        if isinstance(level, str):
            level_norm = level.strip().upper()
        else:
            return None
        if level_norm not in ("H1", "H2", "H3"):
            return None
        if isinstance(order, int):
            order_norm = order
        elif isinstance(order, str):
            try:
                order_norm = int(order.strip())
            except (TypeError, ValueError):
                return None
        elif isinstance(order, float) and order.is_integer():
            order_norm = int(order)
        else:
            return None
        return (order_norm, level_norm)

    rewrites_by_key: dict[tuple[int, str], str] = {}
    for entry in rewrites:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        key = _normalize_key(entry.get("order"), entry.get("level"))
        if key is None:
            continue
        rewrites_by_key[key] = text.strip()

    # Compile the forbidden-term regex ONCE per call. Inner loop runs
    # the compiled pattern against each rewrite - saves N×M regex
    # compiles for N candidates × M forbidden terms.
    forbidden_pattern = _compile_forbidden_pattern(forbidden_terms)

    # Apply rewrites with safety guards.
    new_structure = [dict(h) for h in heading_structure]
    for idx, original in candidates:
        key = _normalize_key(original.get("order"), original.get("level"))
        if key is None:
            continue
        new_text = rewrites_by_key.get(key)
        if not new_text:
            continue
        if new_text == original.get("text"):
            continue
        # Forbidden-term guard - if the LLM ignored the constraint and
        # produced a heading with a forbidden term, keep the original.
        if forbidden_pattern is not None:
            forbidden_hit = _match_forbidden_compiled(
                new_text, forbidden_pattern, forbidden_terms,
            )
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
