"""SIE Module 11: entity aggregation, LLM pass-2 categorization, and the
entity-term merge.

`aggregate_ner` and `merge_entities_into_terms` are PURE (tested). `categorize_entities`
is the only egress (one Sonnet tool-use call) and enforces the PRD's grounding rule:
the LLM may only dedupe/categorize/filter entities the NER pass surfaced — it may not
invent. Output entities not traceable to an input name/variant are dropped.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .ngrams import AggregatedTerm, LemmaFn
from .textrazor_client import NerEntity

# A competitor page whose distinct-entity count exceeds this multiple of the
# median is treated as a spam outlier and dropped before taking the max.
_ENTITY_OUTLIER_MULT = 3.0


@dataclass
class RawEntity:
    name: str
    types: list[str] = field(default_factory=list)
    avg_salience: float = 0.0
    pages_found: int = 0
    source_urls: list[str] = field(default_factory=list)
    mentions: int = 0
    ner_variants: list[str] = field(default_factory=list)


def aggregate_ner(per_page: list[tuple[str, list[NerEntity]]]) -> list[RawEntity]:
    """PURE. Combine per-page TextRazor entities into a corpus list (dedupe by
    lowercased name, sum mentions, average salience, track source URLs)."""
    acc: dict[str, RawEntity] = {}
    for url, ents in per_page:
        for e in ents:
            key = e.name.lower()
            raw = acc.get(key)
            if raw is None:
                raw = RawEntity(name=e.name, types=list(e.types), ner_variants=[e.name])
                acc[key] = raw
            raw.mentions += e.mentions
            raw.avg_salience += e.salience
            if url not in raw.source_urls:
                raw.source_urls.append(url)
    out = []
    for raw in acc.values():
        n = len(raw.source_urls) or 1
        raw.avg_salience = round(raw.avg_salience / n, 4)
        raw.pages_found = len(raw.source_urls)
        out.append(raw)
    return out


def categorize_entities(raw: list[RawEntity], keyword: str, llm) -> list:
    """LLM pass-2 (Sonnet tool-use): dedupe/categorize/enrich/filter. Returns
    models.Entity list (lazy import). GROUNDING: output entities whose term isn't an
    input name/variant are dropped (the LLM may not invent)."""
    if not raw:
        return []
    from .models import Entity

    allowed = {r.name.lower() for r in raw} | {
        v.lower() for r in raw for v in r.ner_variants
    }
    salience_by_name = {r.name.lower(): r.avg_salience for r in raw}
    schema = {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "term": {"type": "string"},
                        "entity_category": {"type": "string"},
                        "example_context": {"type": "string"},
                        "ner_variants": {"type": "array", "items": {"type": "string"}},
                        "recommendation_score": {"type": "number"},
                    },
                    "required": ["term", "entity_category", "recommendation_score"],
                },
            }
        },
        "required": ["entities"],
    }
    listing = "\n".join(
        f"- {r.name} (types: {', '.join(r.types) or 'n/a'}; salience {r.avg_salience}; "
        f"{r.pages_found} pages; variants: {', '.join(r.ner_variants)})"
        for r in raw
    )
    out = llm.call_tool(
        system=(
            "You deduplicate, categorize, enrich, and filter a list of entities that "
            "an NER model extracted from competitor pages. Do NOT add any entity that "
            "is not in the provided list — only process, label, and merge what is given. "
            "Drop off-topic, purely navigational, or SEO-valueless brand entities."
        ),
        user=f"Target keyword: {keyword}\n\nNER entities:\n{listing}",
        tool_name="categorize_entities",
        tool_description="Return the cleaned, categorized entity list.",
        input_schema=schema,
        purpose="sie_entity_pass2",
    )
    result = []
    for e in out.get("entities", []):
        term = (e.get("term") or "").strip()
        variants = [v for v in e.get("ner_variants", []) if v]
        names = {term.lower(), *(v.lower() for v in variants)}
        if not term or not (names & allowed):       # grounding guard
            continue
        result.append(Entity(
            term=term, entity_category=e.get("entity_category"),
            example_context=e.get("example_context"),
            ner_variants=variants or [term],
            recommendation_score=max(0.0, min(1.0, float(e.get("recommendation_score") or 0.0))),
        ))
    # carry NER salience for the merge (Writer Input C drops it, but scoring may use it)
    for ent in result:
        ent_salience = salience_by_name.get(ent.term.lower())
        if ent_salience is not None:
            setattr(ent, "_avg_salience", ent_salience)
    return result


def _lemmatize_phrase(text: str, lemma_fn: LemmaFn) -> str:
    return " ".join(lem for lem, _ in lemma_fn(text))


def merge_entities_into_terms(
    terms: dict[str, AggregatedTerm], entities: list, lemma_fn: LemmaFn
) -> dict[str, AggregatedTerm]:
    """PURE (PRD M11 merge). Entity matches a term (lemmatized name or variant ==
    term) -> enrich it + mark dual-signal (source 'ngram_and_entity', 1.15x in
    scoring). No match -> add an 'entity_only' term that still goes through scoring."""
    for ent in entities:
        names = [ent.term, *getattr(ent, "ner_variants", [])]
        matched = None
        for nm in names:
            key = _lemmatize_phrase(nm, lemma_fn)
            if key in terms:
                matched = terms[key]
                break
        if matched is not None:
            matched.is_entity = True
            matched.entity_category = ent.entity_category
            matched.ner_variants = list(getattr(ent, "ner_variants", []) or [ent.term])
            matched.avg_salience = getattr(ent, "_avg_salience", 0.0)
            matched.source = "ngram_and_entity"
        else:
            key = _lemmatize_phrase(ent.term, lemma_fn)
            if not key.strip() or key in terms:   # skip entities that lemmatize to ""
                continue
            terms[key] = AggregatedTerm(
                term=key, n=max(1, len(key.split())), is_entity=True,
                source="entity_only", entity_category=ent.entity_category,
                ner_variants=list(getattr(ent, "ner_variants", []) or [ent.term]),
                avg_salience=getattr(ent, "_avg_salience", 0.0),
                passes_coverage=True, passes_tfidf=True, passes_semantic=True,
            )
    return terms


# --- Entity-density benchmark (most aggressive competitor) -------------------
# Sizes how many entities the writer surfaces + must cover. Self-contained in the
# fanout copy (the pipeline-api trimmed-max logic lives in a different codebase).


def aggressive_entity_target(
    raw_entities: list[RawEntity], kept_names: set[str] | None = None
) -> int:
    """PURE. Distinct-entity count of the MOST AGGRESSIVE competitor page.

    Uses each RawEntity's ``source_urls`` to derive one distinct-entity count per
    competitor page, then returns the highest after dropping spam outliers (a page
    whose count exceeds 3× the median). With fewer than three competitors there is
    no stable median, so the plain max is returned. When ``kept_names`` is given
    (lowercased entity names + variants that survived pass-2 categorization), only
    those entities are counted, so junk NER the LLM dropped can't inflate the bar.
    """
    per_url: dict[str, int] = {}
    for r in raw_entities:
        if kept_names is not None:
            names = {r.name.lower(), *(v.lower() for v in r.ner_variants)}
            if not (names & kept_names):
                continue
        for url in r.source_urls:
            if url:
                per_url[url] = per_url.get(url, 0) + 1
    counts = [c for c in per_url.values() if c > 0]
    if not counts:
        return 0
    if len(counts) >= 3:
        median = statistics.median(counts)
        if median > 0:
            trimmed = [c for c in counts if c <= median * _ENTITY_OUTLIER_MULT]
            if trimmed:
                counts = trimmed
    return max(counts)


def select_key_entities(entities, benchmark: int, *, default: int, cap: int) -> list[str]:
    """PURE. The top entity terms to require in the writer prompt, sized to the
    aggressive-competitor ``benchmark``.

    Entities (any objects with ``.term`` + ``.recommendation_score``) are ordered
    by score descending; the count is the benchmark, or ``default`` when the
    benchmark is 0/unavailable (e.g. an old cached SIE that predates the field),
    clamped to what exists and to ``cap`` so the prompt stays bounded.
    """
    ordered = sorted(
        (e for e in entities if (getattr(e, "term", "") or "").strip()),
        key=lambda e: getattr(e, "recommendation_score", 0.0),
        reverse=True,
    )
    n = benchmark if benchmark and benchmark > 0 else default
    n = max(0, min(n, len(ordered), cap))
    return [e.term.strip() for e in ordered[:n]]
