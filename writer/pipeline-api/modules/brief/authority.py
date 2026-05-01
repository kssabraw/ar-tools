"""Step 9 — Universal Authority Agent (Brief Generator v2.0).

Implements PRD §5 Step 9 — unchanged from v1.7 except the output type
is now the v2 Candidate (from graph.py) instead of HeadingCandidate.

Generates 3-5 H3 subheadings filling gaps across three pillars:
  1. Human/Behavioral
  2. Risk/Regulatory
  3. Long-Term Systems

Output:
  - source = "authority_gap_sme"
  - exempt = True (bypasses relevance gate)
  - Counts toward the per-H2 H3 limit but never gets discarded for low
    relevance / priority — exempt from those checks per PRD §5 Step 9
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from .graph import Candidate
from .llm import claude_json
from .parsers import levenshtein_ratio, normalize_text

logger = logging.getLogger(__name__)


AUTHORITY_SYSTEM_PROMPT = (
    "You are the Universal Authority Agent. Given a topic and the existing "
    "headings other articles cover, your job is to identify 3-5 unique H3 "
    "subheadings that would add genuine information gain across THREE pillars:\n\n"
    "1. HUMAN/BEHAVIORAL — psychological drivers, common errors people make, "
    "emotional decision points\n"
    "2. RISK/REGULATORY — legal, safety, compliance, financial liabilities\n"
    "3. LONG-TERM SYSTEMS — how this evolves over time, sustainability, "
    "ecosystem outcomes\n\n"
    "Rules:\n"
    "- Output exactly 3-5 H3 headings (not more, not less)\n"
    "- Each heading must be distinct from any heading in the existing list\n"
    "- Use sentence case, no trailing punctuation\n"
    "- Each heading should be specific and actionable, not generic\n"
    "- Distribute coverage across all three pillars when possible\n\n"
    'Respond with a single JSON object: {"headings": ["...", "..."]}'
)


LLMJsonFn = Callable[..., Awaitable]


async def authority_gap_headings(
    *,
    keyword: str,
    existing_headings: list[str],
    reddit_context: list[str],
    max_retries: int = 1,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> list[Candidate]:
    """Run the Universal Authority Agent. Returns 3-5 v2 Candidates.

    Each candidate is tagged source='authority_gap_sme', exempt=True.

    Failure handling (PRD §5 Step 9 — never aborts):
      - Malformed output / fewer than 3 results → retry once
      - Second failure → return empty list, caller continues
    """
    call = llm_json_fn or claude_json

    user = (
        f"Topic / keyword: {keyword}\n\n"
        "Existing heading coverage in top SERP and synthesized candidates:\n"
        + "\n".join(f"- {h}" for h in existing_headings[:40])
    )
    if reddit_context:
        user += (
            "\n\nReddit thread context (signals of real user concerns and confusions):\n"
            + "\n".join(f"- {snippet[:200]}" for snippet in reddit_context[:5])
        )

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            system = AUTHORITY_SYSTEM_PROMPT
            if attempt > 0:
                system += (
                    "\n\nIMPORTANT: Your previous response did not parse as valid JSON. "
                    "Return ONLY the JSON object, no preamble, no explanation."
                )
            result = await call(system, user, max_tokens=600, temperature=0.4)
            headings = result.get("headings") if isinstance(result, dict) else None
            if not headings or not isinstance(headings, list):
                raise ValueError("missing headings array")

            cleaned: list[str] = []
            seen_norms = {normalize_text(h) for h in existing_headings}
            for h in headings:
                if not isinstance(h, str):
                    continue
                norm = normalize_text(h)
                if not norm or any(levenshtein_ratio(norm, e) <= 0.15 for e in seen_norms):
                    continue
                cleaned.append(h.strip())
                seen_norms.add(norm)

            if len(cleaned) > 5:
                cleaned = cleaned[:5]
            if len(cleaned) < 3:
                if attempt < max_retries:
                    continue
                # Accept what we got per PRD §5 Step 9 — never abort.

            logger.info(
                "brief.authority.generated",
                extra={"count": len(cleaned), "attempt": attempt + 1},
            )
            return [
                Candidate(
                    text=text,
                    source="authority_gap_sme",
                    exempt=True,
                )
                for text in cleaned
            ]
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "brief.authority.attempt_failed",
                extra={"attempt": attempt + 1, "error": str(exc)},
            )

    logger.warning(
        "brief.authority.gave_up",
        extra={"error": str(last_exc) if last_exc else "unknown"},
    )
    return []
