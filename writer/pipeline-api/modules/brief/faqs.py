"""Step 7 — FAQ generation.

Source A: regex extraction from PAA + Reddit titles/comments.
Source B: LLM concern extraction from Reddit thread content.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from models.brief import FAQItem, FAQSource

from .llm import claude_json, cosine, embed_batch
from .parsers import normalize_text

logger = logging.getLogger(__name__)

QUESTION_RE = re.compile(r"([A-Z][^.!?]*\?)")


@dataclass
class FAQCandidate:
    question: str
    source: FAQSource
    upvotes: int = 0
    semantic_score: float = 0.0
    novelty_bonus: float = 0.0
    faq_score: float = 0.0


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
) -> list[FAQCandidate]:
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

    return pool


async def llm_concern_extraction(reddit_text: str) -> list[FAQCandidate]:
    """Step 7B — single LLM call across all Reddit content."""
    if not reddit_text.strip():
        return []
    system = (
        "Extract up to 10 distinct implicit questions or concerns expressed in the "
        "given Reddit content. Each question must be a real human concern someone "
        "would want answered. Use natural phrasing ending in '?'. "
        'Respond with: {"questions": ["...", "..."]}'
    )
    try:
        result = await claude_json(system, reddit_text[:8000], max_tokens=600, temperature=0.3)
        questions = result.get("questions") if isinstance(result, dict) else None
        if not isinstance(questions, list):
            return []
        return [
            FAQCandidate(question=q.strip(), source="llm_extracted")
            for q in questions
            if isinstance(q, str) and 5 <= len(q.split()) <= 30
        ]
    except Exception as exc:
        logger.warning("FAQ LLM concern extraction failed: %s", exc)
        return []


def _source_signal(c: FAQCandidate) -> float:
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
    return 0.3


async def score_faqs(
    candidates: list[FAQCandidate],
    keyword_embedding: list[float],
    heading_texts_norm: set[str],
) -> list[FAQCandidate]:
    """Compute faq_score using formula from spec §7.

    faq_score = 0.4*source_signal + 0.4*semantic_relevance + 0.2*novelty_bonus
    """
    if not candidates:
        return []

    embeddings = await embed_batch([c.question for c in candidates])
    for c, vec in zip(candidates, embeddings):
        c.semantic_score = cosine(keyword_embedding, vec)
        c.novelty_bonus = 0.0 if normalize_text(c.question) in heading_texts_norm else 1.0
        c.faq_score = (
            0.4 * _source_signal(c)
            + 0.4 * c.semantic_score
            + 0.2 * c.novelty_bonus
        )
    return candidates


def select_faqs(scored: list[FAQCandidate], min_score: float = 0.5) -> list[FAQItem]:
    """Pick top 5 with score >= 0.5; if <3 pass threshold, accept top 3 regardless.
    Always return 3-5 FAQs (or fewer if pool is exhausted)."""
    if not scored:
        return []
    ranked = sorted(scored, key=lambda c: c.faq_score, reverse=True)
    above = [c for c in ranked if c.faq_score >= min_score]
    if len(above) >= 3:
        chosen = above[:5]
    else:
        chosen = ranked[:3]
    return [
        FAQItem(question=c.question, source=c.source, faq_score=round(c.faq_score, 4))
        for c in chosen
    ]
