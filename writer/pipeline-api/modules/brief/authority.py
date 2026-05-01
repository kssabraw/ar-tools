"""Step 6 — Universal Authority Agent (3 pillars).

Generates 3-5 H3 subheadings that fill information gaps across:
1. Human/Behavioral
2. Risk/Regulatory
3. Long-Term Systems

Output gets `exempt: true` (bypasses semantic threshold), counts toward per-H2 limit.
"""

from __future__ import annotations

import logging
from typing import Optional

from .llm import claude_json
from .parsers import levenshtein_ratio, normalize_text
from .scoring import HeadingCandidate

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


async def authority_gap_headings(
    keyword: str,
    existing_headings: list[str],
    reddit_context: list[str],
    max_retries: int = 1,
) -> list[HeadingCandidate]:
    """Run the Universal Authority Agent. Returns 3-5 HeadingCandidates,
    each tagged source='authority_gap_sme', exempt=True.

    On malformed output: retry once with stricter prompt; on second failure
    return empty list (caller will continue without authority gap headings).
    """
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
            result = await claude_json(system, user, max_tokens=600, temperature=0.4)
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

            # Truncate to 5 if over; require >=3
            if len(cleaned) > 5:
                cleaned = cleaned[:5]
            if len(cleaned) < 3:
                if attempt < max_retries:
                    continue
                # Accept what we got per failure mode rules
            return [
                HeadingCandidate(
                    text=text,
                    source="authority_gap_sme",
                    exempt=True,
                )
                for text in cleaned
            ]
        except Exception as exc:
            last_exc = exc
            logger.warning("authority agent attempt %s failed: %s", attempt + 1, exc)

    logger.warning("authority agent gave up: %s", last_exc)
    return []
