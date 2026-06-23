"""SIE pipeline orchestration — runs Modules 1-14 in order to produce a SIEOutput.

Deps are injected (`SIEDeps`) so the orchestration is mockable; `build_deps()`
constructs the real clients (DataForSEO bound to the session's location_code per
E1, Haiku classifier, Sonnet entity LLM, OpenAI embeddings, ScrapeOwl, TextRazor,
spaCy lemmatizer). Egress fans out per page via `ContextThreadPoolExecutor` (meter +
session_id propagate). Per-page scrape/NER failures degrade that page; a too-thin
SERP (<min_eligible) continues with a degraded-confidence warning (PRD guardrail).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from fanout.concurrency import ContextThreadPoolExecutor

from . import entities as ent
from . import filters, scoring, serp
from .extract import ZonePage, extract_zones, cross_page_fingerprint, frequency_anomaly_terms
from .ngrams import AggregatedTerm, LemmaFn, aggregate_pages, coverage_gate, subsume

logger = logging.getLogger(__name__)


@dataclass
class SIEDeps:
    dfs: object                      # DataForSEOClient (serp_top_results)
    classifier_llm: object           # AnthropicLLM (Haiku) — M3
    entity_llm: object               # AnthropicLLM (Sonnet) — M11 pass-2
    embed_fn: Callable[[list[str]], list[list[float]]]   # M10
    scrapeowl: object                # ScrapeOwlClient — M4
    textrazor: object                # TextRazorClient — M11 pass-1
    lemma_fn: LemmaFn                 # spaCy — M7
    settings: object                 # app config (thresholds)


def build_deps(location_code: int):
    """Construct the real clients (egress). DataForSEO is bound to the session's
    location_code (E1). Lazy imports keep the pure modules importable without deps."""
    from fanout.config import get_settings
    from fanout.dataforseo import get_dataforseo
    from fanout.llm import get_llm
    from fanout.llm.anthropic_client import AnthropicLLM

    from .ngrams import get_spacy_lemmatizer
    from .scrapeowl_client import ScrapeOwlClient
    from .textrazor_client import TextRazorClient

    s = get_settings()
    return SIEDeps(
        dfs=get_dataforseo(location_code),
        classifier_llm=AnthropicLLM(api_key=s.anthropic_api_key, model=s.sie_classifier_model),
        entity_llm=AnthropicLLM(api_key=s.anthropic_api_key, model=s.sie_entity_model),
        embed_fn=get_llm().embed,
        scrapeowl=ScrapeOwlClient(
            s.scrapeowl_api_key, s.scrapeowl_base_url,
            cost_per_scrape=s.scrapeowl_cost_per_scrape,
            cost_per_scrape_premium=s.scrapeowl_cost_per_scrape_premium,
            premium_on_5xx=s.sie_scrapeowl_premium_on_500,
            max_attempts=s.sie_max_transport_attempts,
        ),
        textrazor=TextRazorClient(
            s.textrazor_api_key, s.textrazor_base_url,
            cost_per_request=s.textrazor_cost_per_request,
            relevance_min=s.sie_textrazor_relevance_min,
            max_attempts=s.sie_max_transport_attempts,
        ),
        lemma_fn=get_spacy_lemmatizer(),
        settings=s,
    )


def _body_text(page: ZonePage) -> str:
    z = page.zones
    return " ".join([*z.h1, *z.h2, *z.h3, *z.paragraphs, *z.lists, *page.entity_text])


def analyze(
    keyword: str, *, location_code: int, language_code: str = "en",
    outlier_mode: str = "safe", deps: SIEDeps,
):
    """Run the full SIE pipeline. Returns a models.SIEOutput. Raises on a fatal
    egress/LLM failure (the caller marks the run errored)."""
    from .models import AnalyzedPage

    s = deps.settings
    warnings: list[str] = []

    # M2 SERP + M3 classify ---------------------------------------------------
    results = deps.dfs.serp_top_results(keyword, depth=s.sie_serp_depth)
    classified = serp.classify_results(results, keyword, deps.classifier_llm)
    eligible = [c for c in classified if c.content_eligible]
    excluded = [c for c in classified if not c.content_eligible]

    # M4 scrape (parallel) ----------------------------------------------------
    rank_by_url = {c.url: c.rank for c in classified}
    with ContextThreadPoolExecutor(max_workers=s.sie_scrape_max_workers) as pool:
        scrapes = list(pool.map(lambda c: deps.scrapeowl.scrape(c.url), eligible))

    pages: list[ZonePage] = []
    failed: list[tuple[str, str]] = []
    for c, sc in zip(eligible, scrapes):
        if sc.scrape_status != "success" or not sc.html:
            failed.append((c.url, sc.failure_reason or "scrape failed"))
            continue
        try:
            pages.append(extract_zones(sc.html, c.url, rank=c.rank))
        except Exception as exc:  # noqa: BLE001 — one bad page must not kill the run
            logger.warning(
                "sie_extract_failed",
                extra={"event": "sie_extract_failed", "url": c.url, "reason": repr(exc)},
            )
            failed.append((c.url, f"extract failed: {type(exc).__name__}"))

    # M3 near-dup (post-scrape) -----------------------------------------------
    dups = serp.near_duplicates([(p.url, p.rank, _body_text(p)) for p in pages])
    pages = [p for p in pages if p.url not in dups]

    if len(pages) < s.sie_min_eligible_pages:
        warnings.append(
            f"Only {len(pages)} content-eligible pages analyzed (<{s.sie_min_eligible_pages}); "
            "recommendations are degraded-confidence."
        )

    # M11 pass-1: per-page NER (parallel) — feeds the M8 entity exception + merge.
    # TextRazor rejects (401) under a high concurrent fan-out, so cap it lower.
    with ContextThreadPoolExecutor(max_workers=s.sie_textrazor_max_workers) as pool:
        per_page_ner = list(pool.map(
            lambda p: (p.url, deps.textrazor.extract_entities(_body_text(p))), pages
        ))
    raw_entities = ent.aggregate_ner(per_page_ner)
    entity_names = {r.name for r in raw_entities}

    # M5-6 noise + M7-8 n-grams/aggregate/subsume/coverage --------------------
    boilerplate = cross_page_fingerprint(pages)
    terms: dict[str, AggregatedTerm] = aggregate_pages(pages, deps.lemma_fn, boilerplate)
    terms = subsume(terms, target_keyword=keyword)
    coverage_gate(terms, pages, threshold=s.sie_coverage_threshold, entity_terms=entity_names)

    # Layer 5 frequency anomaly -> avoid candidates.
    anomalies = frequency_anomaly_terms({t.term: list(t.per_page_count.values()) for t in terms.values()})

    # M9 TF-IDF + M10 semantic (on coverage survivors) ------------------------
    filters.compute_tfidf(terms, pages)
    filters.tfidf_gate(terms, threshold=s.sie_tfidf_threshold)
    semantic_pool = [
        t for t in terms.values()
        if t.passes_coverage and t.passes_tfidf and t.term not in anomalies
    ]
    filters.attach_semantic_similarity(
        semantic_pool, keyword, deps.embed_fn, base=s.sie_semantic_threshold
    )

    # M11 pass-2 + merge into the term list -----------------------------------
    categorized = ent.categorize_entities(raw_entities, keyword, deps.entity_llm)
    ent.merge_entities_into_terms(terms, categorized, deps.lemma_fn)

    # Selection: survivors of coverage + tfidf + semantic, minus boilerplate.
    required = [
        t for t in terms.values()
        if t.passes_coverage and t.passes_tfidf and t.passes_semantic
        and not t.low_coverage and t.term not in anomalies and t.term.strip()
    ]
    required = _ensure_target_keyword(required, terms, keyword, deps.lemma_fn)

    # M12-14 ------------------------------------------------------------------
    wc_min, wc_target, wc_max, _src = scoring.recommend_word_count(pages)
    scoring.score_terms(required, rank_by_url)
    _force_target_score(required, keyword, deps.lemma_fn)

    avoid = sorted(anomalies)[:25]
    analyzed_pages = (
        [AnalyzedPage(url=p.url, rank=p.rank, included=True) for p in pages]
        + [AnalyzedPage(url=u, included=False, reason=f"near-duplicate of {c}")
           for u, (c, _s) in dups.items()]
        + [AnalyzedPage(url=c.url, rank=c.rank, included=False, reason=c.page_category)
           for c in excluded]
        + [AnalyzedPage(url=u, included=False, reason=r) for u, r in failed]
    )
    return scoring.build_sie_output(
        keyword=keyword, target_keyword=keyword, required=required,
        entities=categorized, pages=pages, word_count=(wc_min, wc_target, wc_max),
        mode=outlier_mode, avoid=avoid, warnings=warnings, analyzed_pages=analyzed_pages,
    )


def _target_key(keyword: str, lemma_fn: LemmaFn) -> str:
    return " ".join(lem for lem, _ in lemma_fn(keyword))


def _ensure_target_keyword(
    required: list[AggregatedTerm], terms: dict, keyword: str, lemma_fn: LemmaFn
) -> list[AggregatedTerm]:
    """The target keyword is always a Required term (PRD M13), exempt from gating."""
    key = _target_key(keyword, lemma_fn)
    if any(t.term == key for t in required):
        return required
    tk = terms.get(key) or AggregatedTerm(term=key, n=max(1, len(key.split())))
    tk.passes_coverage = tk.passes_tfidf = tk.passes_semantic = True
    return [tk, *required]


def _force_target_score(required: list[AggregatedTerm], keyword: str, lemma_fn: LemmaFn) -> None:
    key = _target_key(keyword, lemma_fn)
    for t in required:
        if t.term == key:
            t.recommendation_score = 1.0
            t.confidence = "high"
            t.reason = "Target keyword — always required."
            # Display the original keyword, not its lemma (e.g. "is retatrutide a
            # glp-3 drug" lemmatizes to "be retatrutide a drug"). Matching/coverage
            # is already done, so renaming the label here is safe — and it lets
            # build_sie_output match the target term for its minimum-usage floor.
            t.term = keyword
