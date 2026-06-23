"""Brief Generator Steps 4-5 — eligibility gates as a PRE-FILTER (M13 slice 3, X.3).

Answer-engine-first: the gates demote from a selection layer to a pre-filter in front
of MCS (aio §0 #3). Two gates on `text-embedding-3-large` (brief-plan §7 #3):

- **Relevance floor** (≥ 0.55): the FULL heading must be on-topic vs the article topic.
- **Restatement ceiling** (≤ 0.78): the **entity-stripped** heading must not just
  restate the title / an already-selected heading.

The entity strip (collision §4.5-A / the X.3→X.4 ordering) is the load-bearing detail:
the heading-form pass (X.4) puts the main entity in *every* heading, so if the entity
tokens reached the restatement cosine, near-everything would look redundant. We strip
the entity (canonical + variants) from BOTH the candidate and the references before the
restatement math, so it measures the *residual* idea, not the shared entity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .entity import MainEntity, cosine

RELEVANCE_FLOOR = 0.55
RESTATEMENT_CEILING = 0.78


def strip_entity(text: str, main_entity: MainEntity) -> str:
    """Remove the main entity's surface forms (canonical + variants) from a heading,
    longest-first, case-insensitively (collision §4.5-A)."""
    out = text
    forms = sorted(
        (f for f in (main_entity.canonical, *main_entity.variants) if f and f.strip()),
        key=len, reverse=True,
    )
    for f in forms:
        out = re.sub(rf"\b{re.escape(f)}\b", " ", out, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip()


@dataclass
class GateResult:
    heading: str
    relevance: float
    restatement: float
    passed: bool
    reason: str | None = None       # "below_relevance_floor" | "restates_existing"


def prefilter(
    candidates: list[str], *, topic_vec: list[float], references: list[str],
    main_entity: MainEntity, embed_fn,
    floor: float = RELEVANCE_FLOOR, ceiling: float = RESTATEMENT_CEILING,
) -> list[GateResult]:
    """Apply both gates. Relevance uses the FULL heading vs the topic; restatement uses
    the ENTITY-STRIPPED heading vs the entity-stripped references. Returns a GateResult
    per candidate (the MCS slice consumes only `passed` ones; the rest are recorded as
    `discarded_headings` with a reason)."""
    if not candidates:
        return []
    stripped_cands = [strip_entity(c, main_entity) for c in candidates]
    stripped_refs = [s for s in (strip_entity(r, main_entity) for r in references) if s]
    # ONE embed call: the full candidates + the deduped NON-EMPTY stripped text. OpenAI
    # rejects "" inputs (400), so a candidate that is JUST the entity (strips to "") is
    # never embedded — its restatement is 0 (no residual idea), but the relevance gate
    # still judges its full heading. Stripped forms keyed by text so dups share a vector.
    to_embed = sorted({s for s in (*stripped_cands, *stripped_refs) if s})
    batch = [*candidates, *to_embed]
    all_vecs = embed_fn(batch)
    full_vecs = all_vecs[:len(candidates)]
    vec_by_text = dict(zip(to_embed, all_vecs[len(candidates):]))
    sr_vecs = [vec_by_text[s] for s in stripped_refs]   # stripped_refs already non-empty

    results: list[GateResult] = []
    for cand, fv, sc in zip(candidates, full_vecs, stripped_cands):
        relevance = cosine(fv, topic_vec)
        sv = vec_by_text.get(sc)
        restatement = (
            max((cosine(sv, rv) for rv in sr_vecs), default=0.0) if sv is not None else 0.0
        )
        if relevance < floor:
            results.append(GateResult(cand, relevance, restatement, False, "below_relevance_floor"))
        elif restatement > ceiling:
            results.append(GateResult(cand, relevance, restatement, False, "restates_existing"))
        else:
            results.append(GateResult(cand, relevance, restatement, True, None))
    return results
