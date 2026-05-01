"""Module 11 — Entity extraction (Google NLP + LLM dedup) and merge into terms.

Pass 1: Google Cloud Natural Language API analyzeEntities, salience >= 0.40.
Pass 2: Claude dedup + categorization. The LLM may NOT invent entities.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from modules.brief.llm import claude_json

from .google_nlp import NEREntity, PageNERResult, analyze_many
from .ngrams import TermAggregate, lemmatize, tokenize
from .zones import PageZones

logger = logging.getLogger(__name__)


@dataclass
class AggregatedEntity:
    name: str
    avg_salience: float
    pages_found: int
    source_urls: list[str]
    ner_variants: list[str]
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
            slot["urls"].add(page.url)

    aggregated: list[AggregatedEntity] = []
    for norm, slot in by_norm.items():
        if not slot["salience_count"]:
            continue
        # Pick the most common original casing as canonical
        from collections import Counter
        most_common = Counter(slot["names"]).most_common(1)[0][0]
        aggregated.append(AggregatedEntity(
            name=most_common,
            avg_salience=slot["salience_total"] / slot["salience_count"],
            pages_found=len(slot["urls"]),
            source_urls=sorted(slot["urls"]),
            ner_variants=sorted(set(slot["names"])),
        ))
    return aggregated


async def llm_dedupe_and_categorize(
    aggregated: list[AggregatedEntity],
) -> list[AggregatedEntity]:
    """Pass 2 — Claude dedup + categorization. May NOT invent entities."""
    if not aggregated:
        return []

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
        "across pages, and (4) drop entities that are off-topic, navigational, or have "
        "no SEO value.\n\n"
        "STRICT RULE: You may only output entities whose `name` matches an entry in "
        "the provided list. Do not invent or rename entities.\n\n"
        'Respond with: {"entities": [{"name": "...", "category": "...", '
        '"example_context": "..."}]}'
    )
    try:
        result = await claude_json(system, str(items), max_tokens=2500, temperature=0.2)
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
            }

    return (aggregates, entity_meta)


async def extract_entities(
    pages: list[PageZones],
) -> tuple[list[AggregatedEntity], list[str]]:
    """High-level entity extraction. Returns (entities, failed_urls)."""
    page_inputs = [(p.url, p.body_text or "") for p in pages]
    per_page = await analyze_many(page_inputs)
    failed_urls = [r.url for r in per_page if r.failed]
    aggregated = aggregate_ner_results(per_page)
    refined = await llm_dedupe_and_categorize(aggregated)
    return (refined, failed_urls)
