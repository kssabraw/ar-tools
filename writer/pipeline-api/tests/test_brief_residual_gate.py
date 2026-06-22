"""Tests for the §X.3 residual restatement gate in embed_with_gates.

Embeddings are injected so cosine values are exact and deterministic.
Key guarantee under test: when main_entity is absent, Step 5 output is
byte-identical to the pre-X.3 behavior.
"""

from __future__ import annotations

import pytest

from modules.brief.graph import Candidate, embed_with_gates


def _cand(text: str) -> Candidate:
    return Candidate(text=text, source="serp")


# Deterministic embeddings keyed by substring, so we control relevance
# (cosine to the title vector) precisely.
#   title vector  = e0
#   "career"      -> e0 scaled 0.70 (mid-band: passes floor, under ceiling)
#   "everything"  -> e0 scaled 0.99 (above ceiling -> restatement)
#   "offtopic"    -> e0 scaled 0.10 (below floor)
#   default       -> e0 scaled 0.72
def _unit(scale: float) -> list[float]:
    # vector along axis 0 with given cosine-to-title (title is pure axis 0)
    import math
    x = scale
    y = math.sqrt(max(0.0, 1.0 - x * x))
    return [x, y, 0.0]


async def _embed(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        tl = t.lower()
        if t == "TITLE":
            out.append([1.0, 0.0, 0.0])
        elif "everything" in tl:
            out.append(_unit(0.99))
        elif "offtopic" in tl:
            out.append(_unit(0.10))
        elif "career" in tl:
            out.append(_unit(0.70))
        else:
            out.append(_unit(0.72))
    return out


FLOOR = 0.55
CEILING = 0.85
ENTITY = {"canonical": "angel number 327", "variants": []}


@pytest.mark.asyncio
async def test_bare_entity_candidate_discarded():
    # Candidate is ONLY the entity (+ stopword) -> empty residual -> discard.
    cands = [_cand("Angel Number 327"), _cand("the angel number 327")]
    result = await embed_with_gates(
        seed="seed", title="TITLE", scope_statement="scope",
        candidates=cands, relevance_floor=FLOOR, restatement_ceiling=CEILING,
        main_entity=ENTITY, embed_fn=_embed,
    )
    assert result.bare_entity_discarded == 2
    assert all(c.discard_reason == "bare_entity_restatement" for c in result.discarded)
    assert result.eligible == []


@pytest.mark.asyncio
async def test_entity_plus_point_gated_on_residual():
    # Full text would embed at 0.72 (default), but the residual "career
    # changes" embeds at 0.70 - both under ceiling, so it's eligible.
    cands = [_cand("Angel Number 327 and Career Changes")]
    result = await embed_with_gates(
        seed="seed", title="TITLE", scope_statement="scope",
        candidates=cands, relevance_floor=FLOOR, restatement_ceiling=CEILING,
        main_entity=ENTITY, embed_fn=_embed,
    )
    assert len(result.eligible) == 1
    assert result.bare_entity_discarded == 0


@pytest.mark.asyncio
async def test_entity_bearing_residual_above_ceiling_discarded():
    # Residual "everything" embeds at 0.99 > ceiling -> restatement discard
    # even though it carries the entity.
    cands = [_cand("Angel Number 327 everything")]
    result = await embed_with_gates(
        seed="seed", title="TITLE", scope_statement="scope",
        candidates=cands, relevance_floor=FLOOR, restatement_ceiling=CEILING,
        main_entity=ENTITY, embed_fn=_embed,
    )
    assert result.eligible == []
    assert result.discarded[0].discard_reason == "above_restatement_ceiling"


@pytest.mark.asyncio
async def test_entity_absent_candidate_gates_on_full_relevance():
    # No entity in the text -> behaves exactly as before (full relevance).
    cands = [_cand("Career planning offtopic")]  # 0.10 -> below floor
    result = await embed_with_gates(
        seed="seed", title="TITLE", scope_statement="scope",
        candidates=cands, relevance_floor=FLOOR, restatement_ceiling=CEILING,
        main_entity=ENTITY, embed_fn=_embed,
    )
    assert result.discarded[0].discard_reason == "below_relevance_floor"


@pytest.mark.asyncio
async def test_byte_identical_when_no_main_entity():
    cands_text = ["Angel Number 327", "Angel Number 327 and Career Changes",
                  "Career planning offtopic", "everything about it"]
    kw = dict(seed="seed", title="TITLE", scope_statement="scope",
              relevance_floor=FLOOR, restatement_ceiling=CEILING, embed_fn=_embed)

    no_entity = await embed_with_gates(candidates=[_cand(t) for t in cands_text], **kw)
    # With main_entity=None, the bare "Angel Number 327" is NOT discarded as
    # a restatement (it embeds at 0.72, under ceiling) -> eligible.
    reasons = {c.text: c.discard_reason for c in
               no_entity.eligible + no_entity.discarded}
    assert reasons["Angel Number 327"] is None
    assert no_entity.bare_entity_discarded == 0
    # offtopic still below floor; everything still above ceiling
    assert reasons["Career planning offtopic"] == "below_relevance_floor"
    assert reasons["everything about it"] == "above_restatement_ceiling"
