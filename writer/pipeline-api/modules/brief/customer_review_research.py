"""Customer review research via Perplexity sonar-pro (PRD v2.6).

Industry-blind-spot mitigation: real customer pain often diverges from
what marketing-oriented competitor content addresses. Reviews on
Trustpilot / G2 / Yelp / Capterra / TrustRadius / App Store / Google
Reviews capture frustrations, switching reasons, and feature requests
that don't make it into "best practices" articles. We mine them to
surface angles the rest of the discovery layer (which all draws from
the same SERP + LLM training corpus) misses.

Mirrors the Reddit research pattern: one Perplexity sonar-pro call
that searches review platforms and synthesizes a structured 7-section
Markdown report. No new infrastructure beyond the existing Perplexity
client.

Failure-safe: missing API key, HTTP errors, validation failures, empty
content all log and return `available=False` so the brief continues
with whatever signal it had before this module ran.
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


MIN_REVIEW_CITATIONS = 3
# Patterns matching common customer-review domains. Citations from
# these sites are treated as primary; anything else (a blog summary,
# competitor article) is secondary.
_REVIEW_HOST_RE = re.compile(
    r"^https?://(?:[^/]*\.)?"
    r"(?:trustpilot|g2|capterra|trustradius|yelp|google\.com/maps|"
    r"appstore\.apple|play\.google|amazon|bbb|reseller(?:ratings)?|sitejabber)"
    r"\.com",
    re.IGNORECASE,
)


PERPLEXITY_FN = Callable[..., Awaitable[dict]]


@dataclass
class CustomerReviewInsights:
    """Structured output of `research_customer_reviews`.

    Same shape as `RedditInsights` so consumers can treat both
    interchangeably. `available=False` signals "no signal" — caller
    should ignore this stage rather than fail.
    """

    available: bool = False
    markdown_report: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    citations: list[str] = field(default_factory=list)
    review_citations: list[str] = field(default_factory=list)
    fallback_reason: Optional[str] = None

    @property
    def citation_count(self) -> int:
        return len(self.review_citations)

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "markdown_report": self.markdown_report,
            "sections": self.sections,
            "citations": self.citations,
            "review_citations": self.review_citations,
            "fallback_reason": self.fallback_reason,
        }


SYSTEM_PROMPT = """\
You are a senior customer-research analyst specializing in extracting
unfiltered customer voice from review platforms — Trustpilot, G2,
Capterra, TrustRadius, Yelp, Google Reviews, App Store, Play Store,
Amazon Reviews, Better Business Bureau, ResellerRatings, SiteJabber,
and similar.

Search ACROSS these platforms for the topic at hand. Capture both
positive and negative reviews. Quote real customer language verbatim
when possible (paraphrased only when needed for length).

Your purpose is to extract authentic customer-voice insights that:
- Reveal frustrations and pain points marketing content downplays
- Surface real reasons customers switch to / from competitors
- Capture feature requests and unmet needs
- Identify the difference between "what marketers say" and "what
  customers experience"
- Highlight regulatory / risk angles that come up in complaints

This data is information-gain GOLD because it's largely absent from
the SEO content layer competitors copy from each other.

Validation Rules:
- Cited sources should predominantly be customer review platforms
  (Trustpilot / G2 / Capterra / TrustRadius / Yelp / etc.)
- Aim for at least three (3) citations from review platforms
- Do not fabricate quotes — every claim must trace to a real review
- If review-platform coverage is genuinely thin for this topic, return
  a minimal honest report explaining what platforms you tried and what
  the closest available reviews discuss

Output a Markdown report with EXACTLY these section headings, in this
order, using H2 (`##`) for each:

## 1. Top Customer Frustrations
The pain points reviewers most consistently raise. Use bullets. Cite
each claim with a [N] reference matching the citation list.

## 2. Reasons Customers Switch (Churn Signals)
What pushed reviewers from one option to another. Direction matters —
note WHO they switched FROM and WHO they switched TO when stated.

## 3. Praised Strengths
What reviewers genuinely value when satisfied. Useful for tone and
positioning. Avoid generic praise; capture specific behaviors.

## 4. Unmet Needs & Feature Requests
What customers explicitly asked for that wasn't being delivered.
Often the strongest "missing topic" signal for content strategy.

## 5. Marketing-vs-Reality Gaps
Where customer experience diverged from marketing claims. The exact
ground a content strategist needs to address head-on.

## 6. Regulatory / Risk / Trust Angles
Compliance, security, billing-dispute, or safety concerns that surface
in negative reviews. Often missing from SEO content but high-stakes.

## 7. Citations
Numbered list (1, 2, 3, ...) of the URLs you drew from. Predominantly
customer-review platforms. Indicate the platform name in brackets.
"""


STRICTER_RETRY_SUFFIX = """\

CRITICAL: Your previous response had insufficient review-platform
citations. Re-run the search with broader queries across Trustpilot /
G2 / Capterra / TrustRadius / Yelp / Google Reviews and produce a
report that satisfies the validation rules. At least three citations
should come from customer review platforms.
"""


def _user_prompt(keyword: str) -> str:
    return (
        f'Research customer reviews about: "{keyword}"\n\n'
        f"Produce the seven-section Markdown report described in the "
        f"system prompt. Treat the keyword as the central topic and "
        f"extract authentic customer voice from review platforms. The "
        f"goal is to surface insights a content strategist would miss "
        f"by reading only competitor blog posts and SEO articles."
    )


_SECTION_HEADER_RE = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$", re.MULTILINE)


def _parse_sections(markdown: str) -> dict[str, str]:
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


def _filter_review_citations(citations: list[str]) -> list[str]:
    return [c for c in citations if _REVIEW_HOST_RE.match(c)]


def _validate_citations(
    citations: list[str],
) -> tuple[list[str], Optional[str]]:
    review = _filter_review_citations(citations)
    if not citations:
        return review, "no_citations_returned"
    if len(review) < MIN_REVIEW_CITATIONS:
        return review, (
            f"too_few_review_citations ({len(review)} < {MIN_REVIEW_CITATIONS})"
        )
    return review, None


async def research_customer_reviews(
    keyword: str,
    *,
    perplexity_fn: Optional[PERPLEXITY_FN] = None,
    max_attempts: int = 2,
) -> CustomerReviewInsights:
    """Run the Perplexity-based customer-review synthesis.

    Args:
        keyword: the brief's seed keyword.
        perplexity_fn: injectable for tests; defaults to perplexity_chat.
        max_attempts: total attempts including the initial call. Second
            attempt uses STRICTER_RETRY_SUFFIX appended to the system prompt.

    Returns:
        CustomerReviewInsights — `available=True` only when synthesis
        succeeded and produced citations. Other cases return
        `available=False` with `fallback_reason` populated.
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
                "brief.customer_review_research.unavailable",
                extra={"reason": str(exc)},
            )
            return CustomerReviewInsights(
                available=False, fallback_reason="perplexity_unavailable",
            )
        except PerplexityError as exc:
            last_reason = f"perplexity_error: {exc}"
            logger.warning(
                "brief.customer_review_research.api_error",
                extra={"attempt": attempt, "error": str(exc)},
            )
            continue
        except Exception as exc:
            last_reason = f"unexpected_error: {exc}"
            logger.warning(
                "brief.customer_review_research.unexpected_error",
                extra={"attempt": attempt, "error": str(exc)},
            )
            continue

        content, citations = extract_content_and_citations(payload)
        if not content.strip():
            last_reason = "empty_content"
            logger.warning(
                "brief.customer_review_research.empty_content",
                extra={"attempt": attempt},
            )
            continue

        review_citations, validation_failure = _validate_citations(citations)
        if validation_failure:
            last_reason = validation_failure
            logger.warning(
                "brief.customer_review_research.validation_failed",
                extra={
                    "attempt": attempt,
                    "reason": validation_failure,
                    "total_citations": len(citations),
                    "review_citations": len(review_citations),
                },
            )
            if attempt < max_attempts:
                continue
            # Final attempt: keep partial synthesis rather than discard.

        sections = _parse_sections(content)

        logger.info(
            "brief.customer_review_research.synthesized",
            extra={
                "attempt": attempt,
                "section_count": len(sections),
                "total_citations": len(citations),
                "review_citations": len(review_citations),
                "validation_passed": validation_failure is None,
            },
        )
        return CustomerReviewInsights(
            available=True,
            markdown_report=content,
            sections=sections,
            citations=citations,
            review_citations=review_citations,
            fallback_reason=validation_failure,
        )

    logger.warning(
        "brief.customer_review_research.gave_up",
        extra={"reason": last_reason, "attempts": max_attempts},
    )
    return CustomerReviewInsights(
        available=False, fallback_reason=last_reason,
    )
