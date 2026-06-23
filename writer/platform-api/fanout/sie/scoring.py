"""SIE Modules 12–14: word-count (M12), recommendation scoring (M13), usage
recommendations (M14), and final-output assembly.

All the math is pure + sandbox-testable. `build_sie_output` lazy-imports pydantic
models so the math functions import without pydantic.

Output reconciliation (flagged): the SIE PRD's own model is schema_version "1.0"
with {title,h1,paragraphs} zones, but the Writer's **Input C is 1.4 with
{h2,h3,paragraphs}** and the consumer wins (live-contract rule). So usage +
target-keyword floors are computed internally across all zones but EMITTED as the
1.4 {h2,h3,paragraphs} subset.
"""

from __future__ import annotations

import math

from .ngrams import AggregatedTerm, ZonePage

# Module 13 weights (sum = 1.0).
WEIGHTS = {
    "semantic_similarity": 0.25,
    "tfidf": 0.10,
    "pages_found": 0.25,
    "zone_importance": 0.20,
    "rank": 0.10,
    "intent_alignment": 0.10,
}
ZONE_WEIGHTS = {
    "title": 1.0, "h1": 0.9, "h2": 0.8, "meta_description": 0.4,
    "h3": 0.5, "paragraphs": 0.3, "lists": 0.2, "tables": 0.2, "faq_blocks": 0.3,
}
WRITER_ZONES = ("h2", "h3", "paragraphs")     # the 1.4 emitted subset
OVEROPT_CAP_PER_1000 = 10                       # M14 hard cap


# ----- shared math ----------------------------------------------------------


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (p in [0,1])."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(s[int(k)])
    return s[lo] * (hi - k) + s[hi] * (k - lo)


def minmax_normalize(values: list[float]) -> list[float]:
    """Min-max to [0,1]; all-equal -> 0.5 (PRD M13 division-by-zero rule)."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


# ----- Module 12: word count ------------------------------------------------


def recommend_word_count(
    pages: list[ZonePage], *, min_words: int = 800, max_words: int = 5000
) -> tuple[int, int, int, list[int]]:
    """(min=p25, target=p50, max=p75, source_word_counts) over pages in
    [min_words, max_words]. Empty -> zeros (caller warns on too-few)."""
    counts = [p.word_count for p in pages if min_words <= p.word_count <= max_words]
    if not counts:
        return 0, 0, 0, []
    return (
        round(percentile(counts, 0.25)),
        round(percentile(counts, 0.50)),
        round(percentile(counts, 0.75)),
        sorted(counts),
    )


# ----- Module 13: recommendation scoring ------------------------------------


def _zone_importance_raw(term: AggregatedTerm) -> float:
    return max((ZONE_WEIGHTS.get(z, 0.2) for z in term.zones), default=0.0)


def _rank_raw(term: AggregatedTerm, rank_by_url: dict[str, int | None]) -> float:
    ranks = [rank_by_url.get(u) for u in term.pages]
    ranks = [r for r in ranks if r]
    return (1.0 / min(ranks)) if ranks else 0.0


def quadgram_zone_multiplier(term: AggregatedTerm) -> float:
    """1.5x title/H1, 1.4x H2, 1.2x H3 (on 2+ pages); else 1.0 (PRD M13)."""
    if term.n != 4:
        return 1.0
    pages_in = lambda z: len(term.zones[z].pages) if z in term.zones else 0  # noqa: E731
    if pages_in("title") >= 2 or pages_in("h1") >= 2:
        return 1.5
    if pages_in("h2") >= 2:
        return 1.4
    if pages_in("h3") >= 2:
        return 1.2
    return 1.0


def _confidence(term: AggregatedTerm) -> str:
    if term.pages_found <= 1 or term.recommendation_score < 0.3:
        return "low"
    if (term.pages_found >= 3 and term.semantic_similarity >= 0.5
            and _zone_importance_raw(term) >= 0.5 and not term.low_coverage):
        return "high"
    return "medium"


def score_terms(
    terms: list[AggregatedTerm], rank_by_url: dict[str, int | None]
) -> list[AggregatedTerm]:
    """Min-max normalize the 6 inputs across the candidate set, apply weights +
    the quadgram zone multiplier, set recommendation_score/confidence/reason."""
    if not terms:
        return terms
    raw = {
        "semantic_similarity": [t.semantic_similarity for t in terms],
        "tfidf": [t.tfidf for t in terms],
        "pages_found": [float(t.pages_found) for t in terms],
        "zone_importance": [_zone_importance_raw(t) for t in terms],
        "rank": [_rank_raw(t, rank_by_url) for t in terms],
        "intent_alignment": [t.intent_alignment for t in terms],
    }
    norm = {k: minmax_normalize(v) for k, v in raw.items()}
    for i, term in enumerate(terms):
        mult = quadgram_zone_multiplier(term)
        zone_norm = min(1.0, norm["zone_importance"][i] * mult)
        term.zone_boost_applied = mult > 1.0
        score = sum(
            WEIGHTS[k] * (zone_norm if k == "zone_importance" else norm[k][i])
            for k in WEIGHTS
        )
        # Dual-signal boost (M11 merge): a term that is BOTH a surviving n-gram and a
        # high-salience entity gets 1.15x (entity_only terms score normally).
        if term.is_entity and term.source == "ngram_and_entity":
            score *= 1.15
        term.recommendation_score = round(min(1.0, score), 4)
        term.confidence = _confidence(term)
        boost = f" Zone multiplier {mult}x applied." if term.zone_boost_applied else ""
        term.reason = (
            f"Appears across {term.pages_found} ranking page(s); "
            f"strongest zone weight {_zone_importance_raw(term):.1f}.{boost}"
        )
    return terms


# ----- Module 14: usage recommendations -------------------------------------


def _zone_freqs_per_1000(
    term: AggregatedTerm, zone: str, wc_by_url: dict[str, int]
) -> list[float]:
    out = []
    for url, count in term.zone_page_count.get(zone, {}).items():
        wc = wc_by_url.get(url, 0)
        if wc > 0:
            out.append(count / wc * 1000.0)
    return out


def _safe_exclude_outliers(freqs: list[float]) -> list[float]:
    """Drop single-page outliers >= 3x the median of the OTHER pages (PRD M14 safe)."""
    if len(freqs) < 3:
        return freqs
    kept = []
    for i, f in enumerate(freqs):
        others = freqs[:i] + freqs[i + 1:]
        med = percentile(others, 0.5)
        if med > 0 and f >= 3 * med:
            continue
        kept.append(f)
    return kept or freqs


def usage_range(
    term: AggregatedTerm, zone: str, target_word_count: int, wc_by_url: dict[str, int],
    *, mode: str = "safe",
) -> tuple[int, int, int]:
    """Per-zone (min,target,max) occurrence counts at `target_word_count`, from
    per-1000-word percentiles, safe-mode outlier exclusion, 10-per-1000 hard cap."""
    freqs = _zone_freqs_per_1000(term, zone, wc_by_url)
    if not freqs:
        return 0, 0, 0
    if mode == "safe":
        freqs = _safe_exclude_outliers(freqs)
    factor = target_word_count / 1000.0
    cap = math.floor(OVEROPT_CAP_PER_1000 * factor)
    lo = round(percentile(freqs, 0.25) * factor)
    tg = round(percentile(freqs, 0.50) * factor)
    hi = round(percentile(freqs, 0.75) * factor)
    hi = min(hi, cap)
    tg = min(tg, hi)
    lo = min(lo, tg)
    return lo, tg, hi


# ----- assembly (lazy pydantic) ---------------------------------------------


def build_sie_output(
    *,
    keyword: str,
    target_keyword: str,
    required: list[AggregatedTerm],
    entities: list,
    pages: list[ZonePage],
    word_count: tuple[int, int, int],
    mode: str = "safe",
    avoid: list[str] | None = None,
    warnings: list[str] | None = None,
    analyzed_pages: list | None = None,
):
    """Assemble the SIEOutput (Writer Input C, schema 1.4). `required` must already
    be scored + filtered; `entities` are models.Entity; the target keyword is merged
    in at score 1.00 with the higher-of floor (M13)."""
    from .models import (
        Entity, MinimumUsage, RequiredTerm, SIEOutput, TargetKeyword, Terms,
        UsageRecommendation, WordCount, ZoneRange,
    )

    wc_by_url = {p.url: p.word_count for p in pages}
    target_wc = word_count[1] or 0
    by_score = sorted(required, key=lambda t: t.recommendation_score, reverse=True)

    req_models = [
        RequiredTerm(
            term=t.term, recommendation_score=t.recommendation_score,
            is_entity=t.is_entity,
            entity_category=next(
                (e.entity_category for e in entities if e.term.lower() == t.term.lower()),
                None,
            ),
        )
        for t in by_score
    ]

    def _usage(term_obj: AggregatedTerm) -> UsageRecommendation:
        ranges = {
            z: usage_range(term_obj, z, target_wc, wc_by_url, mode=mode)
            for z in WRITER_ZONES
        }
        return UsageRecommendation(
            term=term_obj.term,
            h2=ZoneRange(min=ranges["h2"][0], target=ranges["h2"][1], max=ranges["h2"][2]),
            h3=ZoneRange(min=ranges["h3"][0], target=ranges["h3"][1], max=ranges["h3"][2]),
            paragraphs=ZoneRange(
                min=ranges["paragraphs"][0], target=ranges["paragraphs"][1],
                max=ranges["paragraphs"][2],
            ),
        )

    usage = [_usage(t) for t in by_score]

    # Target keyword: floor {paragraphs:1} merged higher-of with M14 (the 1.4 subset;
    # title/H1 floors are owned by the brief/heading structure, not the Writer body).
    tk = next((t for t in by_score if t.term.lower() == target_keyword.lower()), None)
    tk_ranges = (
        {z: usage_range(tk, z, target_wc, wc_by_url, mode=mode) for z in WRITER_ZONES}
        if tk else {z: (0, 0, 0) for z in WRITER_ZONES}
    )
    min_usage = MinimumUsage(
        h2=max(0, tk_ranges["h2"][0]),
        h3=max(0, tk_ranges["h3"][0]),
        paragraphs=max(1, tk_ranges["paragraphs"][0]),
    )

    return SIEOutput(
        keyword=keyword,
        word_count=WordCount(min=word_count[0], target=word_count[1], max=word_count[2]),
        target_keyword=TargetKeyword(term=target_keyword, minimum_usage=min_usage),
        terms=Terms(required=req_models, avoid=list(avoid or [])),
        usage_recommendations=usage,
        entities=[e if isinstance(e, Entity) else Entity(**e) for e in entities],
        warnings=list(warnings or []),
        pages=list(analyzed_pages or []),
    )
