"""SIE — Term & Entity intelligence module (M12).

The full 14-module SurferSEO/Clearscope-style pipeline (docs/sie-module-plan.md),
run per article keyword, lazily at write time, producing the PRD Final Output
Model (`models.SIEOutput`, the Writer's Input C) and caching it 7 days in
`fanout.keyword_analyses`.

Build order (each a logical commit):
  models.py            — Final Output Model (this slice)
  extract.py           — M5-6: zone extraction + 5-layer noise filtering (pure)
  ngrams.py            — M7-8: n-grams, aggregation, subsumption, coverage gate (pure)
  scoring.py           — M9,12-14: TF-IDF, word-count, scoring, usage recs (pure)
  serp.py              — M2-3: SERP collection + URL classification
  scrapeowl_client.py  — M4: page scraping (ScrapeOwl)
  textrazor_client.py  — M11 pass-1: grounded NER (TextRazor)
  entities.py          — M11 pass-2: dedupe/categorize/filter (LLM)
  filters.py           — M10: semantic filtering (embeddings)
  pipeline.py          — orchestration + cache check
  cache.py             — keyword_analyses read/write
"""

__all__ = ["SIEOutput"]


def __getattr__(name: str):
    # Lazy (PEP 562): importing app.sie.extract/ngrams (pure, stdlib-only) must not
    # pull in pydantic via models. `app.sie.SIEOutput` still resolves on demand.
    if name == "SIEOutput":
        from .models import SIEOutput

        return SIEOutput
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
