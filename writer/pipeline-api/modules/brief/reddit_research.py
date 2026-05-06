"""Reddit research via Perplexity sonar-pro.

Replaces the prior shallow Reddit collection (DataForSEO depth=5, titles +
SERP-snippet descriptions only) with a single Perplexity sonar-pro call
that searches Reddit and returns a synthesized insights document.

Why Perplexity:
  - sonar-pro searches the open web (with strong Reddit coverage) and
    synthesizes in one call. We don't need to build thread fetching,
    comment scoring, or LLM synthesis ourselves.
  - The user's existing n8n workflow uses this exact pattern; this is a
    direct port.

Output: `RedditInsights` dataclass with the seven sections from the n8n
prompt (Authentic Experience Signals, Fears & Concerns, Values &
Recommendations, E-E-A-T Opportunities, Information Gain vs. Competing
Content, Emotional/Cultural/Experiential Insights, Citations) plus the
raw Markdown body for downstream consumers (Authority Agent, Writer)
that prefer prose to structured sections.

Failure handling: never aborts the brief.
  - PERPLEXITY_API_KEY missing → returns empty insights with
    `available=False`. Pipeline falls back to raw DataForSEO Reddit
    context for the Authority Agent.
  - Perplexity HTTP error → same fallback.
  - Validation failure (citation count below MIN_CITATIONS) → one retry
    with stricter prompt, then fallback.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from .perplexity_client import (
    PerplexityError,
    PerplexityUnavailable,
    extract_content_and_citations,
    perplexity_chat,
)

logger = logging.getLogger(__name__)


MIN_CITATIONS = 4
MIN_REDDIT_CITATION_RATIO = 0.6  # ≥60% of citations must be reddit.com

PERPLEXITY_FN = Callable[..., Awaitable[dict]]


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------


@dataclass
class RedditInsights:
    """Structured output of `research_reddit`.

    `available=False` is the explicit "no signal" state - caller should
    fall back to whatever Reddit context it had before this module was
    introduced. `markdown_report` carries the raw synthesized body for
    consumers that want the full narrative; the parsed `sections` dict
    gives structured access to each of the seven section headings the
    Perplexity prompt produces.
    """

    available: bool = False
    markdown_report: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    citations: list[str] = field(default_factory=list)
    reddit_citations: list[str] = field(default_factory=list)
    fallback_reason: Optional[str] = None

    @property
    def citation_count(self) -> int:
        return len(self.reddit_citations)

    def to_dict(self) -> dict:
        """Serialization shape carried into the brief response."""
        return {
            "available": self.available,
            "markdown_report": self.markdown_report,
            "sections": self.sections,
            "citations": self.citations,
            "reddit_citations": self.reddit_citations,
            "fallback_reason": self.fallback_reason,
        }


# ---------------------------------------------------------------------------
# Prompts (ported from the n8n Reddit Research subworkflow)
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = """\
You are a senior Reddit research analyst specializing in information gain,
E-E-A-T enhancement, and topical differentiation for SEO content.

Search Reddit thoroughly. Query both post titles and comment threads.
Focus on experience-based subreddits when relevant (r/AskReddit,
r/legaladvice, industry-specific subs, city subs). Capture 15-30
relevant posts/comments across "Top," "New," and "Relevance" sorts.

Your purpose is to extract authentic, first-hand Reddit insights that reveal:
- What real users experience, fear, value, and recommend
- What information competitors overlook (true information gain)
- How Reddit's emotional, cultural, and experiential data can improve
  E-E-A-T on a service or content page

Validation Rules (must hold or you must regenerate):
- All cited sources must be reddit.com URLs
- Provide at least six (6) reddit.com citations
- No non-Reddit URLs in the citation list
- Never fabricate quotes or claims; everything must trace to Reddit

If Reddit lacks meaningful data on the topic after a thorough search,
return a minimal but honest report explaining: the search terms tried,
why Reddit likely lacks data, and what closely related Reddit topics
DO exist. Do not pad with non-Reddit content.

Output a Markdown report with EXACTLY these section headings, in this
order, using H2 (`##`) for each:

## 1. Authentic Experience Signals
Positive and negative first-hand experiences. Use bullets. Cite each
claim with a [N] reference matching the citation list.

## 2. Common Fears & Concerns
What worries readers about this topic - costs, risks, mistakes, bad
outcomes. Use bullets.

## 3. What Redditors Value & Recommend
What "good" looks like in Redditors' own words; heuristics experienced
practitioners share with newcomers. Use bullets.

## 4. Specific E-E-A-T Opportunities
Concrete angles competitor service/content pages overlook that Reddit
discussions reveal. Each item should be actionable for a content
strategist.

## 5. Information Gain vs. Competing Content
Themes Reddit surfaces that typical marketing content misses entirely.
Be specific.

## 6. Emotional, Cultural & Experiential Insights
Tone, vocabulary, cultural context, regional variation, multilingual
notes - anything that signals the human texture of the discussion.

## 7. Citations
Numbered list (1, 2, 3, ...) of the reddit.com URLs you drew from. At
least six entries. No non-Reddit URLs.
"""


STRICTER_RETRY_SUFFIX = """\

CRITICAL: Your previous response either had fewer than six reddit.com
citations or included non-Reddit URLs. Re-run the research with
broader Reddit queries and produce a report that satisfies the
validation rules. All citations MUST be reddit.com URLs and there
MUST be at least six.
"""


def _user_prompt(keyword: str) -> str:
    return (
        f'Research Reddit discussions about: "{keyword}"\n\n'
        f"Produce the seven-section Markdown report described in the "
        f"system prompt. Treat the keyword as the central topic; surface "
        f"insights that would help a content team write a more authoritative "
        f"article on this topic than the typical commercial result."
    )


# ---------------------------------------------------------------------------
# Markdown section parser
# ---------------------------------------------------------------------------


_SECTION_HEADER_RE = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$", re.MULTILINE)


def _parse_sections(markdown: str) -> dict[str, str]:
    """Split the report into a dict keyed by section title.

    Permissive: tolerates extra whitespace, missing sections, and
    trailing prose. Section bodies are stripped but otherwise preserved
    verbatim (Markdown formatting intact).
    """
    if not markdown:
        return {}

    matches = list(_SECTION_HEADER_RE.finditer(markdown))
    if not matches:
        return {}

    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        if title:
            sections[title] = body
    return sections


# ---------------------------------------------------------------------------
# Citation validation
# ---------------------------------------------------------------------------


_REDDIT_HOST_RE = re.compile(r"^https?://([^/]*\.)?reddit\.com/", re.IGNORECASE)


def _filter_reddit_citations(citations: list[str]) -> list[str]:
    return [c for c in citations if _REDDIT_HOST_RE.match(c)]


def _validate_citations(
    citations: list[str],
) -> tuple[list[str], Optional[str]]:
    """Returns (reddit_citations, failure_reason).

    failure_reason is None when validation passes (≥ MIN_CITATIONS reddit
    URLs AND non-Reddit URLs are below MIN_REDDIT_CITATION_RATIO).
    """
    reddit = _filter_reddit_citations(citations)
    if not citations:
        return reddit, "no_citations_returned"
    if len(reddit) < MIN_CITATIONS:
        return reddit, f"too_few_reddit_citations ({len(reddit)} < {MIN_CITATIONS})"
    ratio = len(reddit) / max(len(citations), 1)
    if ratio < MIN_REDDIT_CITATION_RATIO:
        return reddit, (
            f"non_reddit_citations_dominate "
            f"({len(reddit)}/{len(citations)} = {ratio:.2f})"
        )
    return reddit, None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def research_reddit(
    keyword: str,
    *,
    perplexity_fn: Optional[PERPLEXITY_FN] = None,
    max_attempts: int = 2,
) -> RedditInsights:
    """Run the Perplexity-based Reddit research synthesis.

    Args:
        keyword: the brief's seed keyword.
        perplexity_fn: injectable for tests; defaults to perplexity_chat.
        max_attempts: total attempts including the initial call. Second
            attempt uses STRICTER_RETRY_SUFFIX appended to the system prompt.

    Returns:
        RedditInsights - `available=True` only when a synthesis call
        succeeded and validation passed. Other cases return
        `available=False` with `fallback_reason` populated so the caller
        can log + downgrade gracefully.
    """
    call = perplexity_fn or perplexity_chat
    user = _user_prompt(keyword)

    last_reason = "unknown"
    for attempt in range(1, max_attempts + 1):
        system = SYSTEM_PROMPT
        if attempt > 1:
            system = SYSTEM_PROMPT + STRICTER_RETRY_SUFFIX
        try:
            payload = await call(system=system, user=user)
        except PerplexityUnavailable as exc:
            logger.info(
                "brief.reddit_research.unavailable",
                extra={"reason": str(exc)},
            )
            return RedditInsights(
                available=False, fallback_reason="perplexity_unavailable"
            )
        except PerplexityError as exc:
            last_reason = f"perplexity_error: {exc}"
            logger.warning(
                "brief.reddit_research.api_error",
                extra={"attempt": attempt, "error": str(exc)},
            )
            continue
        except Exception as exc:
            last_reason = f"unexpected_error: {exc}"
            logger.warning(
                "brief.reddit_research.unexpected_error",
                extra={"attempt": attempt, "error": str(exc)},
            )
            continue

        content, citations = extract_content_and_citations(payload)
        if not content.strip():
            last_reason = "empty_content"
            logger.warning(
                "brief.reddit_research.empty_content",
                extra={"attempt": attempt},
            )
            continue

        reddit_citations, validation_failure = _validate_citations(citations)
        if validation_failure:
            last_reason = validation_failure
            logger.warning(
                "brief.reddit_research.validation_failed",
                extra={
                    "attempt": attempt,
                    "reason": validation_failure,
                    "total_citations": len(citations),
                    "reddit_citations": len(reddit_citations),
                },
            )
            if attempt < max_attempts:
                continue
            # Final attempt: keep what we have rather than discarding the
            # whole synthesis. The caller logs low_coverage and we still
            # return the markdown body so downstream consumers can decide.

        sections = _parse_sections(content)

        logger.info(
            "brief.reddit_research.synthesized",
            extra={
                "attempt": attempt,
                "section_count": len(sections),
                "total_citations": len(citations),
                "reddit_citations": len(reddit_citations),
                "validation_passed": validation_failure is None,
            },
        )

        return RedditInsights(
            available=True,
            markdown_report=content,
            sections=sections,
            citations=citations,
            reddit_citations=reddit_citations,
            fallback_reason=validation_failure,  # None when fully clean
        )

    logger.warning(
        "brief.reddit_research.gave_up",
        extra={"reason": last_reason, "attempts": max_attempts},
    )
    return RedditInsights(
        available=False, fallback_reason=last_reason
    )
