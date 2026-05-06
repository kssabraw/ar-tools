"""Step 10 - FAQ Generation (Brief Generator v2.0 → v2.2).

Implements PRD §5 Step 10. Mostly unchanged from v1.7 except:

  - semantic_relevance is cosine to TITLE embedding, not seed (PRD §5 Step 10)
  - persona gap questions that did NOT make it into the H2 outline feed
    the FAQ candidate pool (Source C)
  - persona_gap source carries source_signal = 0.6 in the scoring formula
  - PRD v2.2 / Phase 2: semantic_relevance is now a 50/50 weighted blend
    of cosine-to-title and cosine-to-intent-profile so an FAQ that
    matches the title's surface vocabulary but a different stakeholder's
    intent (audited "creator monetization on a seller-ROI article" case)
    gets penalized. The intent_profile vector is supplied by the caller
    (built by `faq_intent_gate.build_intent_profile_text` and embedded
    once); when omitted, the score falls back to the v2.1 title-only
    behavior so legacy callers continue to work.

Sources:
  A. Regex extraction over PAA + Reddit titles + Reddit comment text
     (sentences ending in `?`, 5–25 words long).
  B. LLM concern extraction across all Reddit content (one Claude call).
  C. Persona gap questions from Step 6 (PRD v2.0 NEW source).

Scoring (PRD §5 Step 10, blended in v2.2):

    semantic_relevance = (0.5 · cos(title) + 0.5 · cos(intent_profile))
                          if intent_profile_embedding is provided,
                          else cos(title) only (v2.1 behavior).

    faq_score = 0.4·source_signal + 0.4·semantic_relevance + 0.2·novelty_bonus

    source_signal:
        paa                              = 1.0
        reddit (≥50 upvotes)             = 0.9
        reddit (10–49 upvotes)           = 0.6
        reddit (<10 upvotes)             = 0.3
        llm_extracted                    = 0.5
        persona_gap                      = 0.6
    novelty_bonus: 1.0 if question's normalized text not in heading_texts_norm

Selection (unchanged from v1.7):
  - Top 5 by score with min threshold 0.5
  - If <3 pass threshold, accept top 3 regardless
  - Always returns 3–5 FAQs (or fewer if pool is exhausted)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from models.brief import FAQItem, FAQSource

from .llm import claude_json, embed_batch_large
from .parsers import normalize_text

logger = logging.getLogger(__name__)


QUESTION_RE = re.compile(r"([A-Z][^.!?]*\?)")

DEFAULT_MIN_FAQ_SCORE = 0.5
MAX_FAQS = 5
MIN_FAQS_FALLBACK = 3


@dataclass
class FAQCandidate:
    question: str
    source: FAQSource
    upvotes: int = 0
    semantic_score: float = 0.0
    novelty_bonus: float = 0.0
    faq_score: float = 0.0
    # PRD v2.2 / Phase 2 - Step 10.5 FAQ Intent Gate.
    # `intent_role` is stamped by Step 10.5 when the LLM classifier runs
    # over the cosine-floor survivors. Stays None when Step 10.5 hasn't
    # run yet (between score_faqs and the gate) or when the gate's LLM
    # call failed and we accepted everyone via the fallback.
    intent_role: Optional[str] = None
    # Cached cosines so Step 10.5's gate doesn't have to re-embed.
    title_cosine: float = 0.0
    intent_profile_cosine: float = 0.0


# Type alias so tests can inject a synthetic embedder.
EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]


def extract_question_sentences(text: str) -> list[str]:
    """Pull sentences ending in '?' that are 5-25 words."""
    out: list[str] = []
    for match in QUESTION_RE.finditer(text):
        q = match.group(1).strip()
        wc = len(q.split())
        if 5 <= wc <= 25:
            out.append(q)
    return out


def regex_faq_pool(
    paa_questions: list[str],
    reddit_titles: list[str],
    reddit_comments: list[str],
    persona_gap_questions: Optional[list[str]] = None,
) -> list[FAQCandidate]:
    """Source A + Source C (deterministic) FAQ candidates.

    Persona gap questions only enter as FAQ candidates here (Source C);
    the LLM concern extractor (Source B) does not see them - they're
    already explicit questions.

    Same-text dedup uses normalized text (lowercased + punctuation
    stripped) so e.g. "How does TikTok Shop work?" and "How does TikTok
    Shop work" collapse into one candidate.
    """
    pool: list[FAQCandidate] = []
    seen: set[str] = set()

    for q in paa_questions:
        norm = normalize_text(q)
        if norm and norm not in seen:
            seen.add(norm)
            pool.append(FAQCandidate(question=q.strip(), source="paa"))

    for title in reddit_titles:
        for q in extract_question_sentences(title):
            norm = normalize_text(q)
            if norm not in seen:
                seen.add(norm)
                pool.append(FAQCandidate(question=q, source="reddit", upvotes=10))

    for comment in reddit_comments:
        for q in extract_question_sentences(comment):
            norm = normalize_text(q)
            if norm not in seen:
                seen.add(norm)
                pool.append(FAQCandidate(question=q, source="reddit", upvotes=10))

    if persona_gap_questions:
        for q in persona_gap_questions:
            text = (q or "").strip()
            if not text:
                continue
            # Ensure the entry actually reads as a question; persona Step 6
            # already enforces "?", but defensive trailing-punctuation here
            # keeps the FAQ list consistent if a stray entry slips through.
            if not text.endswith("?"):
                text = text.rstrip(".!") + "?"
            norm = normalize_text(text)
            if norm and norm not in seen:
                seen.add(norm)
                pool.append(FAQCandidate(question=text, source="persona_gap"))

    return pool


async def llm_concern_extraction(
    reddit_text: str,
    *,
    llm_json_fn: Optional[Callable[..., Awaitable]] = None,
) -> list[FAQCandidate]:
    """Source B - single Claude call across all Reddit content.

    Returns up to 10 implicit questions/concerns. Failures degrade to an
    empty list (the run never aborts because of FAQ extraction).
    """
    if not reddit_text.strip():
        return []
    call = llm_json_fn or claude_json
    system = (
        "Extract up to 10 distinct implicit questions or concerns expressed "
        "in the given Reddit content. Each question must be a real human "
        "concern someone would want answered. Use natural phrasing ending "
        "in '?'. "
        'Respond with: {"questions": ["...", "..."]}'
    )
    try:
        result = await call(system, reddit_text[:8000], max_tokens=600, temperature=0.3)
        questions = result.get("questions") if isinstance(result, dict) else None
        if not isinstance(questions, list):
            return []
        return [
            FAQCandidate(question=q.strip(), source="llm_extracted")
            for q in questions
            if isinstance(q, str) and 5 <= len(q.split()) <= 30
        ]
    except Exception as exc:
        logger.warning("brief.faq.llm_failed", extra={"error": str(exc)})
        return []


def _source_signal(c: FAQCandidate) -> float:
    """Tier weights from PRD §5 Step 10 (v2.0 adds persona_gap = 0.6)."""
    if c.source == "paa":
        return 1.0
    if c.source == "reddit":
        if c.upvotes >= 50:
            return 0.9
        if c.upvotes >= 10:
            return 0.6
        return 0.3
    if c.source == "llm_extracted":
        return 0.5
    if c.source == "persona_gap":
        return 0.6
    return 0.3


async def score_faqs(
    candidates: list[FAQCandidate],
    title_embedding: list[float],
    heading_texts_norm: set[str],
    *,
    embed_fn: Optional[EmbedFn] = None,
    intent_profile_embedding: Optional[list[float]] = None,
    candidate_embeddings: Optional[list[list[float]]] = None,
) -> list[FAQCandidate]:
    """Compute faq_score per PRD §5 Step 10 (v2.0: cosine to title, not seed;
    v2.2: blended cosine-to-title + cosine-to-intent_profile).

    Embeddings come from text-embedding-3-large via embed_batch_large
    (unit-normalized → cosine == dot product). Title embedding is the
    same vector produced in Step 5.1 - passing it in keeps FAQ scoring
    consistent with H2 selection.

    PRD v2.2 / Phase 2 - when `intent_profile_embedding` is supplied,
    `semantic_score` becomes the 50/50 weighted average of cosine-to-
    title and cosine-to-intent-profile. When omitted (legacy callers
    or when the intent profile failed to embed upstream), `semantic_
    score` falls back to cosine-to-title only.

    `candidate_embeddings` is an optional pre-computed embeddings
    array (one entry per candidate). Phase 2's pipeline computes these
    once before invoking score_faqs so they can be reused by the
    intent gate without a second API call.

    Mutates each candidate in place: writes `title_cosine`,
    `intent_profile_cosine`, `semantic_score`, `novelty_bonus`,
    `faq_score`. Returns the same list for chaining.
    """
    if not candidates:
        return []
    embed = embed_fn or embed_batch_large

    if candidate_embeddings is not None and len(candidate_embeddings) == len(candidates):
        embeddings = candidate_embeddings
    else:
        embeddings = await embed([c.question for c in candidates])
    for c, vec in zip(candidates, embeddings):
        # title_embedding is unit-normalized; embed_batch_large normalizes
        # by default → cosine reduces to dot product.
        title_cos = (
            sum(a * b for a, b in zip(title_embedding, vec))
            if title_embedding and vec
            else 0.0
        )
        c.title_cosine = title_cos
        if intent_profile_embedding and vec:
            intent_cos = sum(
                a * b for a, b in zip(intent_profile_embedding, vec)
            )
            c.intent_profile_cosine = intent_cos
            c.semantic_score = 0.5 * title_cos + 0.5 * intent_cos
        else:
            c.intent_profile_cosine = 0.0
            c.semantic_score = title_cos
        c.novelty_bonus = 0.0 if normalize_text(c.question) in heading_texts_norm else 1.0
        c.faq_score = (
            0.4 * _source_signal(c)
            + 0.4 * c.semantic_score
            + 0.2 * c.novelty_bonus
        )
    return candidates


def select_faqs(
    scored: list[FAQCandidate],
    min_score: float = DEFAULT_MIN_FAQ_SCORE,
) -> list[FAQItem]:
    """PRD §5 Step 10 selection - top 5 by score, threshold 0.5.

    Behavior:
      - Sort by faq_score desc
      - Keep entries scoring ≥ min_score; cap at 5
      - If fewer than 3 pass the threshold, fall back to the top 3
        regardless of score (so the brief always carries a non-empty
        FAQ block when ANY candidates exist)
      - Empty input → empty output

    Returns API-ready FAQItem objects with rounded faq_score. PRD v2.2 /
    Phase 2: when the candidate carries an `intent_role` (set by Step
    10.5's gate), it's surfaced verbatim on the FAQItem so consumers
    can highlight `adjacent_intent` fallbacks.
    """
    if not scored:
        return []
    ranked = sorted(scored, key=lambda c: c.faq_score, reverse=True)
    above = [c for c in ranked if c.faq_score >= min_score]
    chosen = above[:MAX_FAQS] if len(above) >= MIN_FAQS_FALLBACK else ranked[:MIN_FAQS_FALLBACK]
    return [
        FAQItem(
            question=c.question,
            source=c.source,
            faq_score=round(c.faq_score, 4),
            intent_role=c.intent_role,  # type: ignore[arg-type]
        )
        for c in chosen
    ]
