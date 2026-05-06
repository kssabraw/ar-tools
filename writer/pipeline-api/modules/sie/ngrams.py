"""Module 7 + 8 - N-gram analysis, term aggregation, subsumption, coverage gating.

Also implements Layer 5 of noise filtering (frequency anomaly detection)
since that operates on aggregated term frequencies.

Lemmatization uses NLTK WordNet. WordNet is downloaded in the Dockerfile so
no runtime download is needed.
"""

from __future__ import annotations

import logging
import math
import re
import string
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from .zones import PageZones

logger = logging.getLogger(__name__)


STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "of", "in",
    "on", "at", "to", "for", "with", "by", "from", "up", "down", "into",
    "out", "over", "under", "about", "is", "are", "was", "were", "be", "been",
    "being", "am", "have", "has", "had", "having", "do", "does", "did",
    "doing", "will", "would", "should", "could", "may", "might", "must",
    "can", "this", "that", "these", "those", "i", "you", "he", "she",
    "it", "we", "they", "them", "his", "her", "its", "our", "their",
    "what", "which", "who", "whom", "whose", "as", "than", "so", "very",
    "just", "also", "only", "any", "some", "no", "not", "all", "each",
    "every", "few", "more", "most", "such", "own", "same", "other",
    # SIE v1.2 - possessives/reflexives that the v1.0 list missed.
    # Production output was leaking "your" / "your tiktok" / "on tiktok"
    # because none of these were filtered. The reflexives ("yourself"
    # etc.) are extremely unlikely to be a useful related-keyword on
    # their own and serve only as bigram pollution.
    "your", "yours", "yourself", "yourselves",
    "myself", "ourselves", "themselves", "himself", "herself", "itself",
    "us", "me", "him",
})


# SIE v1.2 - multi-token n-grams with this fraction or more of
# stopword tokens are dropped at extraction time. "your tiktok" (50%),
# "how to" (100%), "on tiktok shop" (33% - kept) are the canonical
# cases this floor was tuned against.
STOPWORD_DENSITY_FLOOR = 0.50

ZONE_WEIGHTS = {
    "title": 4.0,
    "h1": 3.5,
    "h2": 3.0,
    "h3": 2.0,
    "h4": 1.5,
    "meta_description": 2.5,
    "lists": 1.5,
    "tables": 1.2,
    "faq_blocks": 2.0,
    "paragraphs": 1.0,
}

WORD_RE = re.compile(r"[a-z][a-z'\-]*[a-z]|[a-z]")


@lru_cache(maxsize=10000)
def lemmatize(word: str) -> str:
    """Lemmatize a single word using WordNet.

    Tries verb, noun, adjective lemmas - keeps the shortest which is
    almost always the most-reduced base form. Lowercased on return.
    """
    word = word.lower()
    if not word:
        return word
    try:
        from nltk.stem import WordNetLemmatizer
        lemmatizer = _get_lemmatizer()
        candidates = [
            lemmatizer.lemmatize(word, pos="v"),
            lemmatizer.lemmatize(word, pos="n"),
            lemmatizer.lemmatize(word, pos="a"),
        ]
        return min(candidates, key=len)
    except Exception:
        # Fallback: trivial stemming
        for suffix in ("ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                return word[: -len(suffix)]
        return word


@lru_cache(maxsize=1)
def _get_lemmatizer():
    from nltk.stem import WordNetLemmatizer
    return WordNetLemmatizer()


def tokenize(text: str) -> list[str]:
    """Lowercase + word-tokenize + lemmatize."""
    if not text:
        return []
    return [lemmatize(m.group(0)) for m in WORD_RE.finditer(text.lower())]


def _stopword_density(tokens: list[str]) -> float:
    if not tokens:
        return 1.0
    return sum(1 for t in tokens if t in STOPWORDS) / len(tokens)


def _generate_ngrams(tokens: list[str], n: int) -> list[str]:
    """Generate n-grams of length `n` from `tokens`.

    Unigrams: skip stopwords entirely.
    Bigrams+ (SIE v1.2): drop n-grams with stopword density at or above
    STOPWORD_DENSITY_FLOOR (0.50). Catches "your tiktok" (50%), "how to"
    (100%) without removing legitimate phrases like "on tiktok shop"
    (33%) or "tiktok shop" (0%).
    """
    if len(tokens) < n:
        return []
    if n == 1:
        return [t for t in tokens if t not in STOPWORDS]
    grams: list[str] = []
    for i in range(len(tokens) - n + 1):
        window = tokens[i:i + n]
        if _stopword_density(window) >= STOPWORD_DENSITY_FLOOR:
            continue
        grams.append(" ".join(window))
    return grams


@dataclass
class TermAggregate:
    """Aggregated counts across all pages for a single normalized term."""

    term: str
    n_gram_length: int
    total_count: int = 0
    pages_found: int = 0
    source_urls: set[str] = field(default_factory=set)
    zone_counts: dict[str, int] = field(default_factory=dict)
    zone_pages: dict[str, set[str]] = field(default_factory=dict)
    per_page_count: dict[str, int] = field(default_factory=dict)
    subsumed_terms: list[str] = field(default_factory=list)
    passes_coverage_threshold: bool = False
    coverage_exception: Optional[str] = None
    low_coverage_candidate: bool = False
    template_boilerplate: bool = False


def analyze_pages(pages: list[PageZones]) -> dict[str, TermAggregate]:
    """Run n-gram extraction + aggregation across all pages.

    Returns dict keyed by normalized term text.
    """
    aggregates: dict[str, TermAggregate] = {}

    for page in pages:
        page_term_count: dict[str, int] = {}
        page_zone_count: dict[tuple[str, str], int] = {}

        zones = page.all_zone_text()
        for zone_name, blocks in zones.items():
            for block in blocks:
                tokens = tokenize(block)
                if not tokens:
                    continue
                for n in (1, 2, 3, 4):
                    grams = _generate_ngrams(tokens, n)
                    for g in grams:
                        page_term_count[g] = page_term_count.get(g, 0) + 1
                        page_zone_count[(g, zone_name)] = page_zone_count.get((g, zone_name), 0) + 1

        for term, count in page_term_count.items():
            n = len(term.split())
            agg = aggregates.get(term)
            if agg is None:
                agg = TermAggregate(term=term, n_gram_length=n)
                aggregates[term] = agg
            agg.total_count += count
            agg.source_urls.add(page.url)
            agg.per_page_count[page.url] = count

        for (term, zone), zcount in page_zone_count.items():
            agg = aggregates[term]
            agg.zone_counts[zone] = agg.zone_counts.get(zone, 0) + zcount
            agg.zone_pages.setdefault(zone, set()).add(page.url)

    for agg in aggregates.values():
        agg.pages_found = len(agg.source_urls)

    return aggregates


# ---- Subsumption ----

def apply_subsumption(aggregates: dict[str, TermAggregate]) -> int:
    """Subsume shorter n-grams into longer n-grams when fully contained.

    Mutates `aggregates` in place. Returns the number of merges performed.
    """
    merges = 0
    # Iterate from longest to shortest; treat subsumption as one pass
    by_len = sorted(aggregates.values(), key=lambda a: -a.n_gram_length)
    longer_set = {a.term for a in by_len if a.n_gram_length >= 2}

    for longer in by_len:
        if longer.n_gram_length < 2:
            continue
        longer_words = longer.term.split()
        # Generate all sub-ngrams of `longer`
        sub_grams = []
        for n in range(1, longer.n_gram_length):
            for i in range(longer.n_gram_length - n + 1):
                sub_grams.append(" ".join(longer_words[i:i + n]))

        for sub in sub_grams:
            if sub == longer.term:
                continue
            shorter = aggregates.get(sub)
            if not shorter:
                continue
            # Only subsume if every page where shorter appears, longer also appears
            if not shorter.source_urls.issubset(longer.source_urls):
                continue
            # Merge counts
            longer.total_count += shorter.total_count
            for page, count in shorter.per_page_count.items():
                longer.per_page_count[page] = longer.per_page_count.get(page, 0) + count
            for zone, count in shorter.zone_counts.items():
                longer.zone_counts[zone] = longer.zone_counts.get(zone, 0) + count
                longer.zone_pages.setdefault(zone, set()).update(shorter.zone_pages.get(zone, set()))
            longer.subsumed_terms.append(sub)
            merges += 1
            del aggregates[sub]
    return merges


# ---- Seed-keyword-fragment filter (SIE v1.2) ----


def mark_seed_keyword_fragments(
    aggregates: dict[str, TermAggregate],
    target_keyword: str,
    *,
    entity_meta: Optional[dict[str, dict]] = None,
) -> set[str]:
    """Identify n-gram terms whose normalized tokens are a contiguous
    subsequence of the seed keyword's normalized tokens. Returns the
    SET of flagged term keys - the caller stamps a flag on each
    TermRecord at scoring/build time.

    SIE v1.3 - flag-not-remove (replaces v1.2's filter_seed_keyword_fragments).
    Background: production related-keyword output was dominated by
    fragments of the seed input ("tiktok", "tiktok shop", "roi" for
    "how to increase roi for a tiktok shop"). v1.2 stripped them
    entirely from the aggregates dict - but that ALSO removed them
    from the writer's `terms.required` list, losing the per-zone
    target counts that previously guided the writer to use them
    appropriately for SEO.

    v1.3: keep them in the writer's required list (so target counts
    still drive usage) but flag them with `is_seed_fragment=True` so
    the frontend / strategist UI can filter them out of a "related
    concepts" view. Single list, multiple lenses.

    Protected (NOT flagged):
      - The seed keyword itself (it's the primary term, not a fragment)
      - Entities (entity_meta[term]["is_entity"] truthy) - "TikTok
        Shop" is an entity even when it overlaps the seed
    """
    if not target_keyword:
        return set()
    keyword_tokens = [lemmatize(t) for t in target_keyword.lower().split() if t]
    if not keyword_tokens:
        return set()
    target_norm = " ".join(sorted(keyword_tokens))
    meta = entity_meta or {}

    flagged: set[str] = set()
    for term, agg in aggregates.items():
        # Don't flag the target keyword itself - it's the primary term.
        if agg.coverage_exception == "target_keyword":
            continue
        if " ".join(sorted(term.split())) == target_norm:
            continue
        # Don't flag entities - they belong in the entity bucket
        # regardless of whether their text overlaps the seed keyword.
        if meta.get(term, {}).get("is_entity"):
            continue
        term_tokens = term.split()
        if not term_tokens or len(term_tokens) >= len(keyword_tokens):
            continue
        n = len(term_tokens)
        for i in range(len(keyword_tokens) - n + 1):
            if keyword_tokens[i:i + n] == term_tokens:
                flagged.add(term)
                break

    if flagged:
        logger.info(
            "sie.ngrams.seed_fragments_flagged",
            extra={"flagged_count": len(flagged), "seed_keyword": target_keyword},
        )
    return flagged


# Back-compat alias - older callers (tests, imports) still using the
# v1.2 name. The behavior is now flag-not-remove; the return type
# changed from int to set[str] but `bool(set)` and `len(set)` give
# equivalent truthiness/count semantics for most usage.
filter_seed_keyword_fragments = mark_seed_keyword_fragments


# ---- Coverage gate ----

def apply_coverage_gate(
    aggregates: dict[str, TermAggregate],
    total_pages: int,
    target_keyword: str,
    min_coverage_pages: int = 3,
    top_pages_by_rank: Optional[dict[str, int]] = None,
) -> tuple[int, list[TermAggregate]]:
    """Mark terms as passing coverage; return (filtered_count, low_coverage_candidates).

    Exception terms always pass:
    - Quadgrams in title/H1/H2 on 2+ pages
    - Terms found exclusively on rank 1-3 pages from 2+ unique domains
      (we approximate "domains" by domain extraction from URLs)
    - Sub-phrases of the target keyword cannot be subsumed (handled in
      apply_subsumption already)
    """
    from urllib.parse import urlparse

    target_lemmas = set(tokenize(target_keyword))
    target_norm = " ".join(sorted(target_lemmas))

    filtered = 0
    low_coverage: list[TermAggregate] = []

    for agg in list(aggregates.values()):
        if agg.term == target_keyword.lower() or " ".join(sorted(agg.term.split())) == target_norm:
            agg.passes_coverage_threshold = True
            agg.coverage_exception = "target_keyword"
            continue

        if agg.pages_found >= min_coverage_pages:
            agg.passes_coverage_threshold = True
            continue

        # Quadgram exception
        if agg.n_gram_length == 4:
            for hi_zone in ("title", "h1", "h2"):
                if len(agg.zone_pages.get(hi_zone, set())) >= 2:
                    agg.passes_coverage_threshold = True
                    agg.coverage_exception = f"quadgram_in_{hi_zone}"
                    break
            if agg.passes_coverage_threshold:
                continue

        # Top-of-SERP exception
        if top_pages_by_rank:
            top3_urls = {url for url, rank in top_pages_by_rank.items() if rank <= 3}
            urls_in_top3 = agg.source_urls & top3_urls
            if len(urls_in_top3) >= 2:
                domains = {urlparse(u).netloc.lower() for u in urls_in_top3}
                if len(domains) >= 2:
                    agg.passes_coverage_threshold = True
                    agg.coverage_exception = "top_serp_unique_domains"
                    continue

        agg.low_coverage_candidate = True
        low_coverage.append(agg)
        filtered += 1

    return (filtered, low_coverage)


# ---- Layer 5: frequency anomaly (template boilerplate) ----

def flag_template_boilerplate(
    aggregates: dict[str, TermAggregate],
    cv_threshold: float = 0.1,
    min_pages: int = 4,
) -> int:
    """Layer 5 - flag terms with near-zero coefficient of variation in
    per-page frequency as template boilerplate."""
    flagged = 0
    for agg in aggregates.values():
        if agg.pages_found < min_pages:
            continue
        counts = list(agg.per_page_count.values())
        if not counts:
            continue
        mean = sum(counts) / len(counts)
        if mean == 0:
            continue
        variance = sum((c - mean) ** 2 for c in counts) / len(counts)
        cv = math.sqrt(variance) / mean
        if cv < cv_threshold:
            agg.template_boilerplate = True
            flagged += 1
    return flagged
