"""Step 3.5b - Brand-SIE Term Reconciliation.

Single Claude call. Classifies each SIE-Required term against the brand
guide as keep / exclude_due_to_brand_conflict / reduce_due_to_brand_preference.
Classifies each SIE-Avoid term as keep_avoiding / use_due_to_brand_preference.

Brand always wins (Decision D3 in v1.5 spec). LLM must cite specific
brand-guide text in `brand_guide_reasoning` for every non-`keep` decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from models.writer import BrandConflictEntry

from modules.brief.llm import claude_json

logger = logging.getLogger(__name__)


RECONCILIATION_SYSTEM = """You are a categorization-only LLM. Reconcile each term against the provided brand guide and assign a classification. You MUST cite specific brand-guide text in `brand_guide_reasoning` for any non-`keep` / non-`keep_avoiding` decision.

For each REQUIRED term, classify as:
- "keep" - no conflict; brand guide is silent or supportive
- "exclude_due_to_brand_conflict" - brand guide explicitly bans this term
- "reduce_due_to_brand_preference" - brand guide ambiguously discourages without prohibition

For each AVOID term, classify as:
- "keep_avoiding" - no brand-guide preference for this term
- "use_due_to_brand_preference" - brand guide explicitly prefers this term

CRITICAL RULES:
- Cite specific brand-guide text in brand_guide_reasoning for every non-keep / non-keep_avoiding decision.
- Do not infer that a term is banned because it "feels off-brand" - base every decision on text in the brand guide.
- If the brand guide does not address a term either way, classify as "keep" or "keep_avoiding".
- Do not add any term that is not in the input lists.

Output a single JSON object:
{
  "required_classifications": [
    {"term": "...", "classification": "keep | exclude_due_to_brand_conflict | reduce_due_to_brand_preference", "brand_guide_reasoning": "..."}
  ],
  "avoid_classifications": [
    {"term": "...", "classification": "keep_avoiding | use_due_to_brand_preference", "brand_guide_reasoning": "..."}
  ]
}"""


@dataclass
class ReconciledTerm:
    term: str
    zone_usage_target: int = 0
    zone_usage_min: int = 0
    zone_usage_max: int = 0
    effective_target: int = 0
    effective_max: int = 0
    reconciliation_action: str = "keep"
    # PRD v2.6 - Heading SEO Optimizer needs per-zone targets (title /
    # h1 / h2 / h3 / paragraphs). The legacy `zone_usage_*` / `effective_*`
    # fields above carry the paragraphs zone for back-compat with the
    # existing writer-section prompt; `zones` carries every zone the
    # SIE pipeline computes so the optimizer can enforce per-zone min/
    # target/max.
    zones: dict = field(default_factory=dict)
    is_entity: bool = False
    entity_category: Optional[str] = None
    # SIE v1.3 - n-gram terms whose tokens are a contiguous subsequence of
    # the seed keyword. Heading SEO Optimizer must NOT inject these into
    # H2/H3 (they're keyword echoes, not topical adjacents). Entities and
    # the seed itself are never flagged. Defaults False for legacy SIE
    # responses (pre-1.3) that omit the field.
    is_seed_fragment: bool = False


@dataclass
class FilteredSIETerms:
    required: list[ReconciledTerm] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)


def _required_terms_from_sie(sie: dict) -> list[dict]:
    """Pluck (term, zone usage) from the SIE output."""
    required = []
    terms_obj = sie.get("terms") or {}
    for entry in terms_obj.get("required") or []:
        if not isinstance(entry, dict):
            continue
        required.append({"term": entry.get("term", ""), "data": entry})
    return required


def _avoid_terms_from_sie(sie: dict) -> list[str]:
    out: list[str] = []
    terms_obj = sie.get("terms") or {}
    for entry in terms_obj.get("avoid") or []:
        if isinstance(entry, dict):
            out.append(entry.get("term", ""))
        elif isinstance(entry, str):
            out.append(entry)
    return [t for t in out if t]


_USAGE_ZONES = ("title", "h1", "h2", "h3", "paragraphs")


def _zones_for_term(usage_recs: list[dict], term: str) -> dict:
    """Pull every zone's {min, target, max} for a term from usage_recommendations.

    Returns a dict keyed by zone name with each value `{min, target, max}`.
    Zones missing from the SIE usage_rec default to all-zero. PRD v2.6 -
    consumed by the Heading SEO Optimizer to enforce per-zone entity
    targets when rewriting H2/H3.
    """
    zones: dict[str, dict[str, int]] = {
        z: {"min": 0, "target": 0, "max": 0} for z in _USAGE_ZONES
    }
    for rec in usage_recs:
        if not isinstance(rec, dict) or rec.get("term") != term:
            continue
        usage = rec.get("usage", {}) or {}
        if not isinstance(usage, dict):
            return zones
        for z in _USAGE_ZONES:
            zone_rec = usage.get(z, {}) or {}
            if not isinstance(zone_rec, dict):
                continue
            zones[z] = {
                "min": int(zone_rec.get("min", 0)),
                "target": int(zone_rec.get("target", 0)),
                "max": int(zone_rec.get("max", 0)),
            }
        return zones
    return zones


def _zone_usage_for_term(usage_recs: list[dict], term: str) -> tuple[int, int, int]:
    """Backward-compat wrapper - returns the paragraphs-zone (min, target, max).

    Existing callers in `sections.py` rely on this exact triple shape. New
    callers should use `_zones_for_term` to access per-zone targets across
    all five zones (title / h1 / h2 / h3 / paragraphs).
    """
    paras = _zones_for_term(usage_recs, term)["paragraphs"]
    return (paras["min"], paras["target"], paras["max"])


async def reconcile_terms(
    sie_output: dict,
    brand_guide_text: str,
) -> tuple[FilteredSIETerms, list[BrandConflictEntry]]:
    """Returns (filtered_terms, brand_conflict_log).

    Empty brand_guide_text → all terms keep / keep_avoiding, empty conflict log.
    LLM failure → fall back to all-keep with empty conflict log + warning.
    """
    required_terms = _required_terms_from_sie(sie_output)
    avoid_terms = _avoid_terms_from_sie(sie_output)
    usage_recs = sie_output.get("usage_recommendations") or []

    if not brand_guide_text or not brand_guide_text.strip():
        return _all_keep(required_terms, avoid_terms, usage_recs), []

    if not required_terms and not avoid_terms:
        return FilteredSIETerms(), []

    user = (
        "=== BRAND GUIDE ===\n"
        f"{brand_guide_text[:80_000]}\n\n"
        "=== SIE REQUIRED TERMS (classify each) ===\n"
        + "\n".join(f"- {r['term']}" for r in required_terms[:60])
        + "\n\n=== SIE AVOID TERMS (classify each) ===\n"
        + "\n".join(f"- {t}" for t in avoid_terms[:30])
        + "\n\nReturn the JSON object with required_classifications and avoid_classifications now."
    )

    last_exc: Optional[Exception] = None
    for attempt in range(2):
        system = RECONCILIATION_SYSTEM
        if attempt > 0:
            system += "\n\nIMPORTANT: Your previous response did not parse. Return ONLY the JSON object."
        try:
            result = await claude_json(system, user, max_tokens=3000, temperature=0.1)
            if not isinstance(result, dict):
                raise ValueError("expected JSON object")
            return _build_filtered(
                required_terms=required_terms,
                avoid_terms=avoid_terms,
                usage_recs=usage_recs,
                req_class=result.get("required_classifications") or [],
                avoid_class=result.get("avoid_classifications") or [],
            )
        except Exception as exc:
            last_exc = exc
            logger.warning("Reconciliation attempt %d failed: %s", attempt + 1, exc)

    logger.warning("Reconciliation gave up - falling back to all-keep: %s", last_exc)
    return _all_keep(required_terms, avoid_terms, usage_recs), []


def _entity_metadata_for_term(rec: dict) -> tuple[bool, Optional[str], bool]:
    """Pluck (is_entity, entity_category, is_seed_fragment) from a SIE term
    entry. Defaults to (False, None, False) when the SIE row doesn't carry
    the metadata - keeps backward compat with pre-v1.3 SIE responses."""
    data = rec.get("data") or {}
    if not isinstance(data, dict):
        return (False, None, False)
    is_entity = bool(data.get("is_entity", False))
    entity_category = data.get("entity_category")
    if not isinstance(entity_category, str):
        entity_category = None
    is_seed_fragment = bool(data.get("is_seed_fragment", False))
    return (is_entity, entity_category, is_seed_fragment)


def _all_keep(
    required: list[dict],
    avoid: list[str],
    usage_recs: list[dict],
) -> FilteredSIETerms:
    """Build a filtered structure where every term is kept as-is."""
    out = FilteredSIETerms()
    for r in required:
        term = r["term"]
        if not term:
            continue
        mn, tg, mx = _zone_usage_for_term(usage_recs, term)
        zones = _zones_for_term(usage_recs, term)
        is_entity, entity_category, is_seed_fragment = _entity_metadata_for_term(r)
        out.required.append(ReconciledTerm(
            term=term,
            zone_usage_target=tg, zone_usage_min=mn, zone_usage_max=mx,
            effective_target=tg, effective_max=mx,
            reconciliation_action="keep",
            zones=zones,
            is_entity=is_entity,
            entity_category=entity_category,
            is_seed_fragment=is_seed_fragment,
        ))
    out.avoid = [t for t in avoid if t]
    return out


def _build_filtered(
    required_terms: list[dict],
    avoid_terms: list[str],
    usage_recs: list[dict],
    req_class: list[dict],
    avoid_class: list[dict],
) -> tuple[FilteredSIETerms, list[BrandConflictEntry]]:
    out = FilteredSIETerms()
    log: list[BrandConflictEntry] = []

    # Build lookup
    sie_term_set = {r["term"] for r in required_terms}
    avoid_term_set = set(avoid_terms)
    req_class_by_term = {
        e.get("term", ""): e
        for e in req_class
        if isinstance(e, dict) and e.get("term") in sie_term_set
    }
    avoid_class_by_term = {
        e.get("term", ""): e
        for e in avoid_class
        if isinstance(e, dict) and e.get("term") in avoid_term_set
    }

    for r in required_terms:
        term = r["term"]
        if not term:
            continue
        mn, tg, mx = _zone_usage_for_term(usage_recs, term)
        zones = _zones_for_term(usage_recs, term)
        is_entity, entity_category, is_seed_fragment = _entity_metadata_for_term(r)
        cls = req_class_by_term.get(term, {})
        action = cls.get("classification", "keep")
        reasoning = (cls.get("brand_guide_reasoning") or "")[:300]

        if action == "exclude_due_to_brand_conflict":
            out.excluded.append({"term": term, "reason": "exclude_due_to_brand_conflict"})
            log.append(BrandConflictEntry(
                term=term,
                sie_classification="required",
                resolution="exclude_due_to_brand_conflict",
                brand_guide_reasoning=reasoning,
            ))
        elif action == "reduce_due_to_brand_preference":
            out.required.append(ReconciledTerm(
                term=term,
                zone_usage_target=tg, zone_usage_min=mn, zone_usage_max=mx,
                effective_target=mn,
                effective_max=tg,
                reconciliation_action="reduce_due_to_brand_preference",
                zones=zones,
                is_entity=is_entity,
                entity_category=entity_category,
                is_seed_fragment=is_seed_fragment,
            ))
            log.append(BrandConflictEntry(
                term=term,
                sie_classification="required",
                resolution="reduce_due_to_brand_preference",
                brand_guide_reasoning=reasoning,
            ))
        else:
            out.required.append(ReconciledTerm(
                term=term,
                zone_usage_target=tg, zone_usage_min=mn, zone_usage_max=mx,
                effective_target=tg, effective_max=mx,
                reconciliation_action="keep",
                zones=zones,
                is_entity=is_entity,
                entity_category=entity_category,
                is_seed_fragment=is_seed_fragment,
            ))

    final_avoid: list[str] = []
    for term in avoid_terms:
        cls = avoid_class_by_term.get(term, {})
        action = cls.get("classification", "keep_avoiding")
        reasoning = (cls.get("brand_guide_reasoning") or "")[:300]
        if action == "use_due_to_brand_preference":
            log.append(BrandConflictEntry(
                term=term,
                sie_classification="avoid",
                resolution="brand_preference_overridden_by_sie",
                brand_guide_reasoning=reasoning,
            ))
            # Term is NOT added to required - but it's also removed from avoid
        else:
            final_avoid.append(term)

    out.avoid = final_avoid
    return (out, log)
