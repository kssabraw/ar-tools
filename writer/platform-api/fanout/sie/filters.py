"""SIE Modules 9–10: TF-IDF pre-filter (M9, pure) + semantic filtering (M10).

This slice ships M9 (pure, sandbox-testable). M10 (embeddings) is added in the
egress slice — its `attach_semantic_similarity(terms, embed_fn, keyword)` will set
`term.semantic_similarity` (cosine to the keyword, 0.65 gate with dynamic 0.60/0.70
adjustment + heading-term preservation). Until then `semantic_similarity` stays 0.0
and scoring treats it as a normalized input.
"""

from __future__ import annotations

import math
from typing import Callable

from .ngrams import AggregatedTerm, ZonePage

TFIDF_THRESHOLD = 0.005
SEMANTIC_THRESHOLD = 0.65
_HIGH_ZONES = ("title", "h1", "h2")
EmbedFn = Callable[[list[str]], list[list[float]]]


def compute_tfidf(
    terms: dict[str, AggregatedTerm], pages: list[ZonePage]
) -> dict[str, AggregatedTerm]:
    """Corpus TF-IDF per term (PRD M9), set on `term.tfidf`.

        tf(term, page)   = term_count_in_page / page_word_count
        idf(term)        = log(total_pages / pages_containing_term)
        corpus_tfidf     = mean over pages where the term appears of tf*idf
    """
    total_pages = len(pages)
    wc_by_url = {p.url: p.word_count for p in pages}
    for term in terms.values():
        if total_pages == 0 or term.pages_found == 0:
            term.tfidf = 0.0
            continue
        idf = math.log(total_pages / term.pages_found)
        per_page = []
        for url, count in term.per_page_count.items():
            wc = wc_by_url.get(url, 0)
            if wc > 0:
                per_page.append((count / wc) * idf)
        term.tfidf = (sum(per_page) / len(per_page)) if per_page else 0.0
    return terms


def tfidf_gate(
    terms: dict[str, AggregatedTerm], *, threshold: float = TFIDF_THRESHOLD
) -> dict[str, AggregatedTerm]:
    """Set `passes_tfidf`. Below threshold fails, EXCEPT terms that passed a
    coverage exception (M8) or are quadgrams in title/H1/H2 on 2+ pages — those
    are always preserved (PRD M9 'Default Thresholds')."""
    for term in terms.values():
        if term.tfidf >= threshold:
            term.passes_tfidf = True
        elif term.coverage_exception or term.quadgram_zone_flag:
            term.passes_tfidf = True
        else:
            term.passes_tfidf = False
    return terms


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _high_zone_pages(term: AggregatedTerm) -> int:
    return len({u for z in _HIGH_ZONES if z in term.zones for u in term.zones[z].pages})


def apply_dynamic_threshold(
    terms: list[AggregatedTerm], *, base: float = SEMANTIC_THRESHOLD
) -> float:
    """PURE (PRD M10): start at `base`; <25 passing -> 0.60; >300 passing -> 0.70.
    Sets `passes_semantic` on each term; heading terms in title/H1/H2 on 3+ pages are
    preserved even below threshold. Assumes `semantic_similarity` is already set."""
    threshold = base
    for _ in range(2):  # converge (lower then maybe stay)
        passing = sum(1 for t in terms if t.semantic_similarity >= threshold)
        if passing < 25 and threshold > 0.60:
            threshold = 0.60
        elif passing > 300 and threshold < 0.70:
            threshold = 0.70
        else:
            break
    for t in terms:
        if t.semantic_similarity >= threshold:
            t.passes_semantic = True
        elif _high_zone_pages(t) >= 3:
            t.passes_semantic = True       # heading-term preservation
        else:
            t.passes_semantic = False
    return threshold


def attach_semantic_similarity(
    terms: list[AggregatedTerm], keyword: str, embed_fn: EmbedFn,
    *, base: float = SEMANTIC_THRESHOLD,
) -> float:
    """M10 egress: embed keyword + terms (one batched call), set
    `semantic_similarity` (cosine), then apply the dynamic threshold. Returns the
    effective threshold."""
    if not terms:
        return base
    vectors = embed_fn([keyword, *(t.term for t in terms)])
    kw_vec, term_vecs = vectors[0], vectors[1:]
    for term, vec in zip(terms, term_vecs):
        term.semantic_similarity = round(_cosine(kw_vec, vec), 4)
    return apply_dynamic_threshold(terms, base=base)
