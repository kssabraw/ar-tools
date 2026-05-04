"""Module 11 — Entity extraction (Google NLP + LLM dedup) and merge into terms.

SIE v1.1 — hybrid scoring replaces the prior salience-only gate:

  Pass 1: Google NLP analyzeEntities with low salience floor (0.10) +
          all entity types allowed. See `google_nlp.py`.
  Pass 1b: Aggregate per page → per normalized name with mentions and
           pages_found tracking.
  Pass 1c: Composite score per aggregated entity:
              entity_score =
                w_recurrence * (pages_found / total_pages)
              + w_salience   * avg_salience
              + w_mention    * (total_mentions / max_total_mentions)
              - w_noise      * noise_penalty
           Promote when score >= threshold OR pages_found >= override.
           Stamp `promotion_reason` for downstream observability.
  Pass 2: Claude dedup + categorization on PROMOTED entities only.
          The LLM may NOT invent entities.

The hybrid model lets cross-SERP recurrence rescue low-salience entities
(e.g. "GMV Max" surfaces with salience 0.18 across 4 pages — strong
topical signal that the prior 0.40 hard gate threw away).
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Literal, Optional

from config import settings
from modules.brief.llm import claude_json

from .google_nlp import NEREntity, PageNERResult, analyze_many
from .ngrams import TermAggregate, lemmatize, tokenize
from .zones import PageZones

logger = logging.getLogger(__name__)


PromotionReason = Literal[
    # Highest priority — entity name (or one of its variants) appears
    # as a contiguous token-sequence inside the user's keyword. Forces
    # promotion regardless of score; the reasoning is that anything
    # the user explicitly typed is by definition relevant.
    "keyword_match",
    "dual_signal_strong",
    "high_recurrence_low_salience",
    "high_salience_low_recurrence",
    "entity_only_promoted",
]


@dataclass
class AggregatedEntity:
    name: str
    avg_salience: float
    pages_found: int
    source_urls: list[str]
    ner_variants: list[str]
    total_mentions: int = 0
    entity_score: float = 0.0
    promotion_reason: Optional[PromotionReason] = None
    category: str = "concepts"
    example_context: str = ""


def _normalize_entity_name(name: str) -> str:
    return " ".join(lemmatize(t) for t in name.lower().split())


def aggregate_ner_results(per_page: list[PageNERResult]) -> list[AggregatedEntity]:
    """Combine per-page entities into aggregated records keyed by normalized name."""
    by_norm: dict[str, dict] = defaultdict(lambda: {
        "names": [],
        "salience_total": 0.0,
        "salience_count": 0,
        "mentions_total": 0,
        "urls": set(),
    })
    for page in per_page:
        if page.failed:
            continue
        for ent in page.entities:
            norm = _normalize_entity_name(ent.name)
            if not norm:
                continue
            slot = by_norm[norm]
            slot["names"].append(ent.name)
            slot["salience_total"] += ent.salience
            slot["salience_count"] += 1
            slot["mentions_total"] += ent.mentions
            slot["urls"].add(page.url)

    aggregated: list[AggregatedEntity] = []
    for norm, slot in by_norm.items():
        if not slot["salience_count"]:
            continue
        # Pick the most common original casing as canonical
        most_common = Counter(slot["names"]).most_common(1)[0][0]
        aggregated.append(AggregatedEntity(
            name=most_common,
            avg_salience=slot["salience_total"] / slot["salience_count"],
            pages_found=len(slot["urls"]),
            source_urls=sorted(slot["urls"]),
            ner_variants=sorted(set(slot["names"])),
            total_mentions=slot["mentions_total"],
        ))
    return aggregated


# ----------------------------------------------------------------------
# SIE v1.1 — composite scoring + promotion (replaces the prior
# salience-only gate at extract time)
# ----------------------------------------------------------------------


_NUMERIC_RE = re.compile(r"^[\d\s,.\-/]+$")
_DATE_LIKE_RE = re.compile(
    r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*\d",
    re.IGNORECASE,
)
_CURRENCY_RE = re.compile(r"^\s*[$€£¥₹]\s*\d")
# Minimal generic-stopword set — names that are ONLY a single stopword
# get a partial noise penalty even when they pass the length check.
_GENERIC_TOKENS: frozenset[str] = frozenset({
    "data", "info", "thing", "item", "stuff", "way", "type",
    "kind", "form", "case", "part", "side", "page", "site",
})


def _noise_penalty(ent: AggregatedEntity) -> float:
    """Heuristic noise score in [0, 1].

    Higher = more likely to be junk. Catches short/numeric/date/price
    tokens that Google NLP returns when the type whitelist is removed,
    plus single-page low-salience candidates that probably aren't worth
    the prompt budget downstream.
    """
    name = (ent.name or "").strip()
    lowered = name.lower()
    if len(name) < 3:
        return 1.0
    if _NUMERIC_RE.match(name):
        return 1.0
    if _DATE_LIKE_RE.match(name):
        return 0.9
    if _CURRENCY_RE.match(name):
        return 0.9
    if lowered in _GENERIC_TOKENS:
        return 0.5
    if ent.pages_found <= 1 and ent.avg_salience < 0.15:
        return 0.3
    return 0.0


def _tokens_for_keyword_match(text: str) -> list[str]:
    """Normalize + tokenize a string for token-level keyword matching.

    Returns an empty list when the text normalizes to nothing (empty
    input, whitespace, or all stopwords stripped). Centralizes the
    normalization so keyword and entity names are compared on identical
    footing.
    """
    if not text:
        return []
    norm = _normalize_entity_name(text)
    if not norm:
        return []
    return norm.split()


def _matches_keyword_tokens(
    entity_tokens: list[str], keyword_tokens: list[str],
) -> bool:
    """Token-level contiguous-subsequence match.

    "shop" matches "tiktok shop" but "ip" does NOT match "trip".
    Multi-word entities must appear in order — "tiktok shop" matches
    "how to start a tiktok shop" but "shop tiktok" does not.

    Caller passes pre-tokenized lists so the keyword's tokens can be
    computed once per `score_and_promote_entities` call rather than
    re-normalized for every entity.
    """
    if not entity_tokens or not keyword_tokens:
        return False
    n = len(entity_tokens)
    if n > len(keyword_tokens):
        return False
    for i in range(len(keyword_tokens) - n + 1):
        if keyword_tokens[i : i + n] == entity_tokens:
            return True
    return False


def _matches_keyword(entity_name: str, keyword: str) -> bool:
    """Convenience wrapper for tests and callers without pre-tokenized
    keyword. Internal hot path uses `_matches_keyword_tokens` directly.

    Empty inputs return False — keyword is optional and we don't want
    to silently auto-promote everything when it's missing.
    """
    if not entity_name or not keyword:
        return False
    return _matches_keyword_tokens(
        _tokens_for_keyword_match(entity_name),
        _tokens_for_keyword_match(keyword),
    )


def _classify_promotion(
    ent: AggregatedEntity,
    *,
    score_threshold: float,
    recurrence_override: int,
    keyword_tokens: Optional[list[str]] = None,
) -> Optional[PromotionReason]:
    """Decide whether to promote and tag the reason.

    Returns None when the entity should NOT be promoted. The five
    reasons are checked in priority order:

      1. keyword_match — entity tokens appear in the user's keyword.
         Always promotes (the user said this matters).
      2. dual_signal_strong — high recurrence AND mid+ salience.
      3. high_recurrence_low_salience — recurrence override path.
      4. high_salience_low_recurrence — single-source strong entity.
      5. entity_only_promoted — composite-score path.

    `keyword_tokens` is the pre-normalized + tokenized keyword (passed
    once from `score_and_promote_entities`). Pass None or an empty
    list to skip the keyword_match path.
    """
    if keyword_tokens:
        # Check the canonical name AND every variant; dedupe so we
        # don't tokenize+match `ent.name` twice when it's also in
        # `ner_variants` (which it typically is).
        seen: set[str] = set()
        for candidate in [ent.name, *ent.ner_variants]:
            if candidate in seen:
                continue
            seen.add(candidate)
            ent_tokens = _tokens_for_keyword_match(candidate)
            if _matches_keyword_tokens(ent_tokens, keyword_tokens):
                return "keyword_match"

    high_recurrence = ent.pages_found >= recurrence_override
    high_salience = ent.avg_salience >= 0.33
    score_passes = ent.entity_score >= score_threshold

    if not (score_passes or high_recurrence):
        return None

    if high_recurrence and ent.avg_salience >= 0.30:
        return "dual_signal_strong"
    if high_recurrence and ent.avg_salience < 0.30:
        return "high_recurrence_low_salience"
    if not high_recurrence and high_salience:
        return "high_salience_low_recurrence"
    return "entity_only_promoted"


def score_and_promote_entities(
    aggregated: list[AggregatedEntity],
    *,
    total_pages: int,
    keyword: str = "",
) -> list[AggregatedEntity]:
    """Compute composite `entity_score` per aggregate and return only
    promoted entities (with `promotion_reason` stamped in place).

    `keyword` (optional) enables the highest-priority "keyword_match"
    promotion path: entities whose tokens appear in the keyword text
    are auto-promoted regardless of composite score. Pass the user's
    seed keyword from the SIE request.

    No-op when `aggregated` is empty or `total_pages == 0` (returns
    empty list — there's nothing to score against).
    """
    if not aggregated or total_pages <= 0:
        return []

    weights = {
        "recurrence": settings.entity_score_weights_recurrence,
        "salience": settings.entity_score_weights_salience,
        "mention": settings.entity_score_weights_mention,
        "noise": settings.entity_score_weights_noise_penalty,
    }
    score_threshold = settings.entity_score_promotion_threshold
    recurrence_override = settings.entity_recurrence_override_pages

    # Normalize the keyword ONCE (not per-entity). The previous
    # implementation called `_normalize_entity_name(keyword)` inside
    # `_matches_keyword` for every entity × variant pair — wasted NLTK
    # lemmatizer calls when the keyword is the same the whole loop.
    keyword_tokens = _tokens_for_keyword_match(keyword)

    max_mentions = max((e.total_mentions for e in aggregated), default=1) or 1

    promoted: list[AggregatedEntity] = []
    reason_counts: dict[str, int] = defaultdict(int)
    salience_bands = {"lt_20": 0, "20_to_40": 0, "40_to_60": 0, "ge_60": 0}
    for ent in aggregated:
        recurrence_score = min(ent.pages_found / total_pages, 1.0)
        salience_score = max(0.0, min(ent.avg_salience, 1.0))
        mention_score = min(ent.total_mentions / max_mentions, 1.0)
        noise = _noise_penalty(ent)

        ent.entity_score = round(
            weights["recurrence"] * recurrence_score
            + weights["salience"] * salience_score
            + weights["mention"] * mention_score
            - weights["noise"] * noise,
            4,
        )

        # Track salience-band distribution for visibility
        if salience_score < 0.20:
            salience_bands["lt_20"] += 1
        elif salience_score < 0.40:
            salience_bands["20_to_40"] += 1
        elif salience_score < 0.60:
            salience_bands["40_to_60"] += 1
        else:
            salience_bands["ge_60"] += 1

        reason = _classify_promotion(
            ent,
            score_threshold=score_threshold,
            recurrence_override=recurrence_override,
            keyword_tokens=keyword_tokens,
        )
        if reason is not None:
            ent.promotion_reason = reason
            promoted.append(ent)
            reason_counts[reason] += 1

    logger.info(
        "sie.entities.scored",
        extra={
            "extracted_count": len(aggregated),
            "promoted_count": len(promoted),
            "by_reason": dict(reason_counts),
            "salience_band_distribution": salience_bands,
            "total_pages": total_pages,
            "score_threshold": score_threshold,
            "recurrence_override": recurrence_override,
        },
    )
    return promoted


# ----------------------------------------------------------------------


async def llm_dedupe_and_categorize(
    aggregated: list[AggregatedEntity],
    *,
    llm_json_fn=None,
) -> list[AggregatedEntity]:
    """Pass 2 — Claude dedup + categorization. May NOT invent entities.

    `llm_json_fn` is injectable for tests; defaults to `claude_json`.
    """
    if not aggregated:
        return []

    call = llm_json_fn or claude_json

    # Prepare a compact representation
    items = [
        {
            "name": ent.name,
            "salience": round(ent.avg_salience, 3),
            "pages": ent.pages_found,
            "variants": ent.ner_variants,
        }
        for ent in aggregated
    ]
    system = (
        "You receive a list of entities extracted from competitor pages by Google NLP. "
        "Your job is to: (1) merge variants of the same entity by their `name` field, "
        "(2) assign each merged entity a category from this list: services, products, "
        "tools, equipment, brands, locations, people, organizations, regulations, "
        "concepts, problems, symptoms, materials, methods, comparisons, pricing_factors, "
        "(3) write a short example_context sentence describing how the entity is used "
        "across pages, and (4) drop ONLY entities that are clearly navigational "
        "(login, signup, footer links, sidebar nav) or pure UI chrome (cookie "
        "banners, breadcrumbs, social-share buttons). Keep anything topical — "
        "even if it seems tangential, it may be relevant to the writer's framing.\n\n"
        "STRICT RULE: You may only output entities whose `name` matches an entry in "
        "the provided list. Do not invent or rename entities.\n\n"
        'Respond with: {"entities": [{"name": "...", "category": "...", '
        '"example_context": "..."}]}'
    )
    try:
        result = await call(system, str(items), max_tokens=2500, temperature=0.2)
    except Exception as exc:
        logger.warning("Entity LLM dedup failed: %s — using raw NER aggregates", exc)
        return aggregated

    if not isinstance(result, dict) or "entities" not in result:
        return aggregated

    by_name = {e.name: e for e in aggregated}
    refined: list[AggregatedEntity] = []
    for entry in result["entities"]:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name or name not in by_name:
            continue
        original = by_name[name]
        original.category = entry.get("category", "concepts")
        original.example_context = entry.get("example_context", "")
        refined.append(original)
    return refined or aggregated


def merge_entities_into_terms(
    aggregates: dict[str, TermAggregate],
    entities: list[AggregatedEntity],
) -> tuple[dict[str, TermAggregate], dict[str, dict]]:
    """Merge aggregated entities into the term list per SIE PRD §11.

    Returns (updated aggregates dict, entity_meta dict keyed by term).
    entity_meta carries category, salience, ner_variants, source flag for the
    scoring stage to consume.
    """
    entity_meta: dict[str, dict] = {}

    for ent in entities:
        norm_name = _normalize_entity_name(ent.name)
        if not norm_name:
            continue

        # Try direct match against an existing term
        match_term: Optional[str] = None
        if norm_name in aggregates:
            match_term = norm_name
        else:
            for variant in ent.ner_variants:
                v_norm = _normalize_entity_name(variant)
                if v_norm in aggregates:
                    match_term = v_norm
                    break

        if match_term:
            entity_meta[match_term] = {
                "is_entity": True,
                "entity_category": ent.category,
                "avg_salience": ent.avg_salience,
                "ner_variants": ent.ner_variants,
                "source": "ngram_and_entity",
                "example_context": ent.example_context,
                # SIE v1.1 — surface the composite score + reason flag
                # so dashboards / debugging can see WHY each entity was
                # promoted (recurrence vs salience vs dual-signal).
                "entity_score": round(ent.entity_score, 4),
                "promotion_reason": ent.promotion_reason,
                "pages_found": ent.pages_found,
                "total_mentions": ent.total_mentions,
            }
        else:
            # Add as entity-only term
            new_term = TermAggregate(
                term=norm_name,
                n_gram_length=len(norm_name.split()),
                total_count=ent.pages_found,
                pages_found=ent.pages_found,
                source_urls=set(ent.source_urls),
            )
            new_term.passes_coverage_threshold = True  # entities always pass
            new_term.coverage_exception = "entity_only"
            aggregates[norm_name] = new_term
            entity_meta[norm_name] = {
                "is_entity": True,
                "entity_category": ent.category,
                "avg_salience": ent.avg_salience,
                "ner_variants": ent.ner_variants,
                "source": "entity_only",
                "example_context": ent.example_context,
                "entity_score": round(ent.entity_score, 4),
                "promotion_reason": ent.promotion_reason,
                "pages_found": ent.pages_found,
                "total_mentions": ent.total_mentions,
            }

    return (aggregates, entity_meta)


def merge_textrazor_entities_into_terms(
    aggregates: dict[str, TermAggregate],
    entity_meta: dict[str, dict],
    textrazor_entities: list,  # list[AggregatedTextRazorEntity] — typed loosely to avoid circular imports
) -> tuple[dict[str, TermAggregate], dict[str, dict]]:
    """Merge TextRazor entities into the SIE aggregates dict (SIE v1.2).

    Mirrors `merge_entities_into_terms` (Google NLP path) but takes
    TextRazor's per-entity stats instead of Google NLP's. When the
    same term is already present (from n-gram extraction OR Google
    NLP merge), the existing `entity_meta` row gets `is_textrazor=True`
    and the TextRazor source URLs are unioned into the existing term's
    `source_urls`. Net effect: one term, one row, multi-source
    provenance.

    Source flag rules (kept compatible with `score_terms`):
      - Term already in aggregates (n-gram match): source stays
        "ngram_and_entity" if Google NLP also flagged it, else
        upgrades to "ngram_and_entity" since TextRazor entities count
        as entities for scoring.
      - Term new to aggregates: added with source = "entity_only"
        (matches Google NLP's entity-only path).

    Returns (updated aggregates, updated entity_meta).
    """
    for ent in textrazor_entities:
        norm_name = _normalize_entity_name(ent.name)
        if not norm_name:
            continue

        # Direct + variant match against existing aggregates
        match_term: Optional[str] = None
        if norm_name in aggregates:
            match_term = norm_name
        else:
            for variant in ent.variants:
                v_norm = _normalize_entity_name(variant)
                if v_norm and v_norm in aggregates:
                    match_term = v_norm
                    break

        if match_term:
            existing_meta = entity_meta.get(match_term, {})
            existing_meta.setdefault("is_entity", True)
            existing_meta.setdefault("entity_category", "concepts")
            existing_meta.setdefault("ner_variants", [])
            # Source-flag rules — TextRazor agreement is a
            # cross-vendor confirmation, not a new signal type. It
            # MUST NOT promote an entity_only term to
            # ngram_and_entity (no n-gram exists to back the claim,
            # and scoring.py applies a 1.20× boost to
            # ngram_and_entity vs 1.10× to entity_only — falsely
            # upgrading inflates the score by ~9%).
            #   - existing "entity_only" (Google NLP only) → stays
            #     "entity_only"; TextRazor adds a confidence flag
            #     via is_textrazor below but NOT a source upgrade.
            #   - existing "ngram_and_entity" → stays.
            #   - no prior entity_meta entry (n-gram-only term) →
            #     becomes "ngram_and_entity" since TextRazor now
            #     supplies the entity signal the n-gram alone
            #     lacked.
            existing_source = existing_meta.get("source")
            if existing_source != "entity_only":
                existing_meta["source"] = "ngram_and_entity"
            existing_meta["is_textrazor"] = True
            existing_meta["textrazor_relevance"] = round(ent.avg_relevance, 4)
            existing_meta["textrazor_confidence"] = round(ent.max_confidence, 4)
            existing_meta["textrazor_types"] = ent.types
            existing_meta["textrazor_wiki_link"] = ent.wiki_link
            entity_meta[match_term] = existing_meta
            # Union the source URLs so coverage gates downstream see
            # the combined corpus reach.
            aggregates[match_term].source_urls.update(ent.source_urls)
            aggregates[match_term].pages_found = len(
                aggregates[match_term].source_urls
            )
        else:
            # Brand-new term — add it with entity-only source flag.
            # Variants stay matched_text + canonical so downstream
            # `usage.py:build_usage` substring-matches against either.
            new_term = TermAggregate(
                term=norm_name,
                n_gram_length=len(norm_name.split()),
                total_count=ent.pages_found,
                pages_found=ent.pages_found,
                source_urls=set(ent.source_urls),
            )
            new_term.passes_coverage_threshold = True
            new_term.coverage_exception = "entity_only"
            aggregates[norm_name] = new_term
            entity_meta[norm_name] = {
                "is_entity": True,
                "entity_category": "concepts",  # TextRazor doesn't map cleanly to our SIE categories
                "ner_variants": ent.variants,
                "source": "entity_only",
                "is_textrazor": True,
                "textrazor_relevance": round(ent.avg_relevance, 4),
                "textrazor_confidence": round(ent.max_confidence, 4),
                "textrazor_types": ent.types,
                "textrazor_wiki_link": ent.wiki_link,
                "pages_found": ent.pages_found,
            }

    return (aggregates, entity_meta)


async def extract_entities(
    pages: list[PageZones],
    *,
    keyword: str = "",
) -> tuple[list[AggregatedEntity], list[str]]:
    """High-level entity extraction. Returns (promoted_entities, failed_urls).

    SIE v1.1 pipeline:
      1. Per-page Google NLP extraction (low salience floor, all types)
      2. Aggregate per normalized name with mentions + page tracking
      3. Composite scoring + promotion (only promoted entities continue)
      4. LLM dedup/categorization on the promoted set (cheaper than v1.0
         since the noise has already been filtered)

    `keyword` enables auto-promotion for entities whose tokens appear
    in the user's seed keyword. Optional for backward compat with
    legacy callers, but should always be passed in production.
    """
    page_inputs = [(p.url, p.body_text or "") for p in pages]
    per_page = await analyze_many(page_inputs)
    failed_urls = [r.url for r in per_page if r.failed]
    successful_pages = sum(1 for r in per_page if not r.failed)

    aggregated = aggregate_ner_results(per_page)
    promoted = score_and_promote_entities(
        aggregated,
        total_pages=max(successful_pages, 1),
        keyword=keyword,
    )
    refined = await llm_dedupe_and_categorize(promoted)
    return (refined, failed_urls)
