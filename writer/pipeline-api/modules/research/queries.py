"""Step 1 - Research query generation via Claude.

Per Research PRD §5.1: generate 2-3 specific research queries per citation
target. 25-second per-call timeout with one retry; on second timeout, fall
back to a generic statistics-oriented query.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from modules.brief.llm import claude_json

logger = logging.getLogger(__name__)

QUERY_TIMEOUT_SECONDS = 25.0


H2_PROMPT = """You are a research assistant helping find authoritative citations for a blog post section.

Keyword: {keyword}
Section heading: {h2_text}
Supporting subheadings: {h3_texts_or_none}
Content intent: {intent_type}

Generate 2-3 search queries specifically designed to find:
- Statistics, data points, or quantified research findings relevant to this section
- Official government guidance, regulatory information, or peer-reviewed studies
- Credible expert analysis, industry data, or named institutional reports

Return a JSON array of query strings only, like ["query 1", "query 2"]. Queries must be specific and factual in nature, designed to surface authoritative sources rather than opinion pieces or competitor blog posts. Do not include the domain name of any specific site in the queries."""


AUTHORITY_GAP_PROMPT = """You are a research assistant helping find authoritative citations for a specific informational gap in a blog post.

Keyword: {keyword}
Parent section: {h2_text}
Specific subheading addressing an information gap: {h3_text}
Content intent: {intent_type}

This subheading was identified as missing from competing content - it represents a specific informational gap that needs strong, verified sources.

Generate 2-3 search queries specifically designed to find:
- Statistics or data points directly relevant to this specific subtopic
- Authoritative sources (government, academic, regulatory) addressing this exact angle
- Expert analysis or research findings on this niche aspect

Return a JSON array of query strings only, like ["query 1", "query 2"]."""


SUPPLEMENTAL_PROMPT = """You are a research assistant helping find authoritative citations to support a blog post on a specific topic.

Keyword: {keyword}
Content intent: {intent_type}

Generate 2-3 broad search queries designed to surface authoritative supplemental sources for this topic - statistics, government guidance, peer-reviewed research, or recognized industry data. Queries should not target any specific section of the article; they should support the topic at the article level.

Return a JSON array of query strings only."""


def _fallback_queries(keyword: str, heading_text: str) -> list[str]:
    return [
        f'"{keyword}" "{heading_text}" statistics OR study OR report',
        f'"{keyword}" "{heading_text}" research data',
    ]


async def _safe_call(prompt: str, fallback: list[str]) -> list[str]:
    """Run claude_json with a 25s timeout + 1 retry. Return fallback on failure."""
    for attempt in range(2):
        try:
            result = await asyncio.wait_for(
                claude_json(
                    system="You generate JSON arrays of search query strings.",
                    user=prompt,
                    max_tokens=400,
                    temperature=0.3,
                ),
                timeout=QUERY_TIMEOUT_SECONDS,
            )
            if isinstance(result, list):
                queries = [q.strip() for q in result if isinstance(q, str) and q.strip()]
                if queries:
                    return queries[:3]
            if isinstance(result, dict):
                for key in ("queries", "search_queries", "items"):
                    arr = result.get(key)
                    if isinstance(arr, list):
                        queries = [q.strip() for q in arr if isinstance(q, str) and q.strip()]
                        if queries:
                            return queries[:3]
        except asyncio.TimeoutError:
            logger.warning("Query generation timeout (attempt %d)", attempt + 1)
        except Exception as exc:
            logger.warning("Query generation failed (attempt %d): %s", attempt + 1, exc)
    return fallback


async def generate_h2_queries(
    keyword: str,
    h2_text: str,
    h3_texts: list[str],
    intent_type: str,
) -> list[str]:
    h3_repr = ", ".join(h3_texts) if h3_texts else "none"
    prompt = H2_PROMPT.format(
        keyword=keyword,
        h2_text=h2_text,
        h3_texts_or_none=h3_repr,
        intent_type=intent_type,
    )
    return await _safe_call(prompt, _fallback_queries(keyword, h2_text))


async def generate_authority_gap_queries(
    keyword: str,
    h2_text: str,
    h3_text: str,
    intent_type: str,
) -> list[str]:
    prompt = AUTHORITY_GAP_PROMPT.format(
        keyword=keyword,
        h2_text=h2_text,
        h3_text=h3_text,
        intent_type=intent_type,
    )
    return await _safe_call(prompt, _fallback_queries(keyword, h3_text))


async def generate_supplemental_queries(keyword: str, intent_type: str) -> list[str]:
    prompt = SUPPLEMENTAL_PROMPT.format(keyword=keyword, intent_type=intent_type)
    return await _safe_call(prompt, [
        f'"{keyword}" statistics report',
        f'"{keyword}" research data study',
    ])
