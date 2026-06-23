"""SIE Modules 7–8: N-gram analysis + aggregation + subsumption + coverage gate.

Pure and unit-testable. The lemmatizer is **injected** (`LemmaFn`) so tests run
without spaCy; production passes `get_spacy_lemmatizer()` (the locked
`en_core_web_sm`, §9 #1). N-grams (n≥2) keep stopwords so "how to repair" survives;
unigrams drop them (PRD M7). Layer-3 boilerplate blocks and Layer-4 heuristic
exclusions are applied here before counting; Layer-4 contact/address text is moved
onto `page.entity_text` for Module 11.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from .extract import ZonePage, heuristic_keep, is_contact_or_address, normalize_block

# (lemma_lowercased, is_stopword) for each alpha token, in order.
LemmaFn = Callable[[str], list[tuple[str, bool]]]

_ZONES = ("title", "meta_description", "h1", "h2", "h3", "h4",
          "paragraphs", "lists", "tables", "faq_blocks")
# Zones where the Layer-4 heuristic filter applies (prose blocks, not headings).
_FILTER_ZONES = ("paragraphs", "lists")
HIGH_ZONES = ("title", "h1", "h2")          # quadgram zone-flag zones
MAX_N = 4


def get_spacy_lemmatizer() -> LemmaFn:
    """Production lemmatizer (lazy spaCy load — model download accepted, §9 #1)."""
    import spacy

    nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])

    def lemma_fn(text: str) -> list[tuple[str, bool]]:
        return [(t.lemma_.lower(), t.is_stop) for t in nlp(text) if t.is_alpha]

    return lemma_fn


def make_ngrams(tokens: list[tuple[str, bool]]) -> dict[int, list[str]]:
    """Unigrams (stopwords dropped) + bi/tri/quadgrams (stopwords kept) from one
    block's lemma sequence."""
    lemmas = [lem for lem, _ in tokens]
    out: dict[int, list[str]] = {1: [lem for lem, stop in tokens if not stop]}
    for n in range(2, MAX_N + 1):
        out[n] = [" ".join(lemmas[i:i + n]) for i in range(len(lemmas) - n + 1)]
    return out


# ----- Aggregated term ------------------------------------------------------


@dataclass
class ZoneStat:
    total_count: int = 0
    pages: set[str] = field(default_factory=set)


@dataclass
class AggregatedTerm:
    term: str
    n: int
    total_count: int = 0
    pages: set[str] = field(default_factory=set)              # unique urls
    zones: dict[str, ZoneStat] = field(default_factory=dict)
    per_page_count: dict[str, int] = field(default_factory=dict)  # url -> count (Layer 5, M9 tf)
    # zone -> url -> count (M14 per-zone percentiles).
    zone_page_count: dict[str, dict[str, int]] = field(default_factory=dict)
    quadgram_zone_flag: bool = False
    subsumed_terms: list[str] = field(default_factory=list)
    passes_coverage: bool = False
    coverage_exception: str | None = None
    low_coverage: bool = False
    # Scoring inputs populated by later modules (M9 tfidf, M10 semantic, M11 entity,
    # M3-derived intent) and the M13 outputs.
    tfidf: float = 0.0
    passes_tfidf: bool = True
    semantic_similarity: float = 0.0
    passes_semantic: bool = True
    intent_alignment: float = 0.0
    is_entity: bool = False
    avg_salience: float = 0.0
    entity_category: str | None = None
    ner_variants: list[str] = field(default_factory=list)
    source: str = "ngram"               # "ngram" | "ngram_and_entity" | "entity_only"
    recommendation_score: float = 0.0
    confidence: str = "low"
    reason: str = ""
    zone_boost_applied: bool = False

    @property
    def pages_found(self) -> int:
        return len(self.pages)

    def _zone(self, zone: str) -> ZoneStat:
        return self.zones.setdefault(zone, ZoneStat())


# ----- Module 7+8: count per page, then aggregate ---------------------------


def aggregate_pages(
    pages: list[ZonePage], lemma_fn: LemmaFn, boilerplate: set[str]
) -> dict[str, AggregatedTerm]:
    """Count n-grams per page/zone (applying Layer 3+4), then aggregate across
    pages. Mutates `page.entity_text` with Layer-4 contact/address blocks."""
    terms: dict[str, AggregatedTerm] = {}

    for page in pages:
        # term -> (n, {zone: count}) for THIS page
        page_terms: dict[str, tuple[int, dict[str, int]]] = {}
        for zone in _ZONES:
            value = getattr(page.zones, zone)
            blocks = value if isinstance(value, list) else [value]
            for block in blocks:
                if not block:
                    continue
                if normalize_block(block) in boilerplate:        # Layer 3
                    continue
                if zone in _FILTER_ZONES:                        # Layer 4
                    keep, reason = heuristic_keep(block)
                    if not keep:
                        if reason == "contact_or_address" or is_contact_or_address(block):
                            page.entity_text.append(block)
                        continue
                for n, grams in make_ngrams(lemma_fn(block)).items():
                    for gram in grams:
                        entry = page_terms.setdefault(gram, (n, defaultdict(int)))
                        entry[1][zone] += 1

        for term, (n, zone_counts) in page_terms.items():
            agg = terms.get(term) or AggregatedTerm(term=term, n=n)
            terms[term] = agg
            page_total = sum(zone_counts.values())
            agg.total_count += page_total
            agg.pages.add(page.url)
            agg.per_page_count[page.url] = page_total
            for zone, count in zone_counts.items():
                zs = agg._zone(zone)
                zs.total_count += count
                zs.pages.add(page.url)
                agg.zone_page_count.setdefault(zone, {})[page.url] = count

    for agg in terms.values():
        if agg.n == MAX_N:
            high_pages = {
                u for z in HIGH_ZONES for u in agg.zones.get(z, ZoneStat()).pages
            }
            agg.quadgram_zone_flag = len(high_pages) >= 2
    return terms


# ----- Module 8: subsumption ------------------------------------------------


def _is_contiguous_subphrase(shorter: str, longer: str) -> bool:
    return f" {shorter} " in f" {longer} "


def subsume(
    terms: dict[str, AggregatedTerm], target_keyword: str | None = None
) -> dict[str, AggregatedTerm]:
    """Merge a shorter n-gram into a passing longer n-gram when it's a contiguous
    sub-phrase whose pages ⊆ the longer's and whose zones ⊆ the longer's (PRD M8).
    Never subsume a sub-phrase of the target keyword."""
    target = (target_keyword or "").lower().strip()
    survivors = dict(terms)
    # longest-first so a bigram folds into the quadgram, not just the trigram.
    by_len = sorted(terms.values(), key=lambda t: t.n, reverse=True)
    for longer in by_len:
        if longer.term not in survivors:
            continue
        for shorter in list(survivors.values()):
            if shorter.term == longer.term or shorter.n >= longer.n:
                continue
            if not _is_contiguous_subphrase(shorter.term, longer.term):
                continue
            if target and _is_contiguous_subphrase(shorter.term, target):
                continue  # never subsume a target-keyword sub-phrase
            if not shorter.pages.issubset(longer.pages):
                continue  # independent page coverage -> keep
            if not set(shorter.zones).issubset(set(longer.zones)):
                continue  # don't subsume across different zones
            longer.total_count += shorter.total_count
            for zone, zs in shorter.zones.items():
                lz = longer._zone(zone)
                lz.total_count += zs.total_count
                lz.pages |= zs.pages
            for url, c in shorter.per_page_count.items():
                longer.per_page_count[url] = longer.per_page_count.get(url, 0) + c
            for zone, pc in shorter.zone_page_count.items():
                dst = longer.zone_page_count.setdefault(zone, {})
                for url, c in pc.items():
                    dst[url] = dst.get(url, 0) + c
            longer.subsumed_terms.append(shorter.term)
            del survivors[shorter.term]
    return survivors


# ----- Module 8: coverage gate ----------------------------------------------


def coverage_gate(
    terms: dict[str, AggregatedTerm],
    pages: list[ZonePage],
    *,
    threshold: int = 3,
    entity_terms: set[str] | None = None,
) -> dict[str, AggregatedTerm]:
    """A term needs `threshold`-of-top-10 page coverage, with three always-allow
    exceptions (quadgram-in-high-zone on 2+ pages; rank-1–3-only from 2+ domains;
    high-confidence entity). Sets `passes_coverage`/`coverage_exception`/
    `low_coverage` in place; never silently discards."""
    entity_terms = {e.lower() for e in (entity_terms or set())}
    rank_by_url = {p.url: p.rank for p in pages}
    domain_by_url = {p.url: p.domain for p in pages}

    for agg in terms.values():
        if agg.pages_found >= threshold:
            agg.passes_coverage = True
            continue
        if agg.quadgram_zone_flag:
            agg.passes_coverage = True
            agg.coverage_exception = "quadgram in title/H1/H2 on 2+ pages"
            continue
        ranks = [rank_by_url.get(u) for u in agg.pages]
        if ranks and all(r is not None and r <= 3 for r in ranks):
            domains = {domain_by_url.get(u) for u in agg.pages}
            if len(domains) >= 2:
                agg.passes_coverage = True
                agg.coverage_exception = "rank 1-3 only, 2+ unique domains"
                continue
        if agg.term.lower() in entity_terms:
            agg.passes_coverage = True
            agg.coverage_exception = "high-confidence entity"
            continue
        agg.low_coverage = True
    return terms
