"""Brief Generator — answer-engine-first content-brief module (M13).

The Brief Generator v2.6 pipeline (docs/brief-generator-module-plan.md +
docs/aio-optimization-plan.md — the answer-engine-first source of truth), run per
article keyword, lazily at write time (parallel stage 1 with SIE), producing the
Brief Output that IS the Writer's **Input A**, cached 7 days in `fanout.briefs`.

Build order (each a logical commit / slice, per aio-optimization-plan.md §5):
  models.py     — v2.6 Brief Output schema (this slice; answer-engine fields are
                  added by the MCS / X.8 slices that bump the schema)
  cache.py      — fanout.briefs read/write (this slice)
  sources.py    — Steps 1-2: DataForSEO SERP+headings / PAA / Reddit / autocomplete /
                  LLM-responses fan-out (ChatGPT + Gemini, E4) + AIO-block capture
  entity.py     — Step 3.6: main-entity derivation (X.2)
  intent.py     — Step 3 two-pass intent + template registry + decision-fit A1 detector
  title.py      — Step 3.5: title + scope
  gates.py      — Steps 4-5: aggregation + eligibility gates as a pre-filter (X.3)
  mcs.py        — Max Cosine Synthesis selection (dual-space, beam-climb) — centerpiece
  persona.py    — Step 6
  authority.py  — Step 9 (authority gaps -> H3)
  faq.py        — Steps 10-10.5
  assemble.py   — Step 11 + title-case + X.8 metadata
  pipeline.py   — orchestration + cache check
"""

__all__ = ["BriefOutput", "SCHEMA_VERSION"]


def __getattr__(name: str):
    # Lazy (PEP 562): pure helpers must import without pulling in pydantic via models.
    if name in ("BriefOutput", "SCHEMA_VERSION"):
        from . import models

        return getattr(models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
