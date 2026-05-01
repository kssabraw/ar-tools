"""Step 9 — Universal Authority Agent (Brief Generator v2.0.3).

Implements PRD §5 Step 9 with v2.0.3 scope-aware inputs.

Generates 3-5 H3 subheadings filling gaps across three pillars:
  1. Human/Behavioral
  2. Risk/Regulatory
  3. Long-Term Systems

v2.0.3 changes:
  - Inputs now include `title`, `scope_statement`, and `intent_type` so
    the agent can respect the article's commitment surface.
  - System prompt directs the agent to leave a pillar empty rather than
    drift outside the scope_statement's `does not cover` clause.
  - Each emitted H3 carries a new `scope_alignment_note` (≤200 chars)
    explaining how the H3 stays in scope.

Output:
  - source = "authority_gap_sme"
  - exempt = True (bypasses relevance gate)
  - scope_alignment_note populated on each Candidate
  - Counts toward the per-H2 H3 limit but never gets discarded for low
    relevance / priority — exempt from those checks per PRD §5 Step 9
  - May still be removed by the v2.0.3 Step 8.5b H3 scope-verification
    pass downstream when the agent's pillar exploration drifts off-scope
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from .graph import Candidate
from .llm import claude_json
from .parsers import levenshtein_ratio, normalize_text

logger = logging.getLogger(__name__)


# Soft cap on the scope_alignment_note string, mirroring PRD §5 Step 9 (≤200 chars).
MAX_SCOPE_ALIGNMENT_NOTE_LEN = 200


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
    "SCOPE DISCIPLINE (PRD v2.0.3): Authority gap content must respect the "
    "article's scope boundary. The three pillars (Human/Behavioral, Risk/"
    "Regulatory, Long-Term Systems) should explore expertise WITHIN the "
    "scope, not adjacent to it. If a pillar would naturally produce content "
    "outside the scope, prefer leaving that pillar empty over producing "
    "off-scope content. It is acceptable to return three H3s instead of "
    "five when staying in-scope requires it.\n\n"
    "For EACH heading, write a `scope_alignment_note` (≤200 chars) that "
    "explains how the heading stays within the scope_statement — especially "
    "the `does not cover` clause. The note is for downstream scope "
    "verification; be specific about WHY the heading is in-scope.\n\n"
    "Respond with a single JSON object:\n"
    "{\n"
    '  "headings": [\n'
    '    {"text": "<heading text>", "scope_alignment_note": "<≤200 chars>"},\n'
    "    ...\n"
    "  ]\n"
    "}"
)


LLMJsonFn = Callable[..., Awaitable]


def _format_user_prompt(
    *,
    keyword: str,
    title: Optional[str],
    scope_statement: Optional[str],
    intent_type: Optional[str],
    existing_headings: list[str],
    reddit_context: list[str],
) -> str:
    parts: list[str] = [f"Topic / keyword: {keyword}"]

    if intent_type:
        parts.append(f"Intent type: {intent_type}")
    if title:
        parts.append(f"\nArticle title (committed):\n{title}")
    if scope_statement:
        parts.append(
            "\nScope statement (must respect; pay close attention to the "
            "`does not cover` clause):\n"
            f"{scope_statement}"
        )

    parts.append(
        "\nExisting heading coverage in top SERP and synthesized candidates:\n"
        + "\n".join(f"- {h}" for h in existing_headings[:40])
    )

    if reddit_context:
        parts.append(
            "\nReddit thread context (signals of real user concerns and confusions):\n"
            + "\n".join(f"- {snippet[:200]}" for snippet in reddit_context[:5])
        )

    return "\n".join(parts)


async def authority_gap_headings(
    *,
    keyword: str,
    existing_headings: list[str],
    reddit_context: list[str],
    title: Optional[str] = None,
    scope_statement: Optional[str] = None,
    intent_type: Optional[str] = None,
    max_retries: int = 1,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> list[Candidate]:
    """Run the Universal Authority Agent. Returns 3-5 v2 Candidates.

    Each candidate is tagged source='authority_gap_sme', exempt=True,
    and carries a `scope_alignment_note` explaining how it stays within
    the brief's scope_statement.

    Failure handling (PRD §5 Step 9 — never aborts):
      - Malformed output / fewer than 3 results → retry once
      - Second failure → return empty list, caller continues
    """
    call = llm_json_fn or claude_json

    user = _format_user_prompt(
        keyword=keyword,
        title=title,
        scope_statement=scope_statement,
        intent_type=intent_type,
        existing_headings=existing_headings,
        reddit_context=reddit_context,
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
            result = await call(system, user, max_tokens=900, temperature=0.4)
            raw = result.get("headings") if isinstance(result, dict) else None
            if not raw or not isinstance(raw, list):
                raise ValueError("missing headings array")

            # Accept both the new shape (list of dicts) and the legacy shape
            # (list of strings) so injected mocks / older callers still work.
            cleaned: list[tuple[str, str]] = []  # (text, scope_alignment_note)
            seen_norms = {normalize_text(h) for h in existing_headings}
            for entry in raw:
                if isinstance(entry, dict):
                    text = entry.get("text") or ""
                    note = entry.get("scope_alignment_note") or ""
                elif isinstance(entry, str):
                    text = entry
                    note = ""
                else:
                    continue
                text = (text or "").strip()
                note = (note or "").strip()[:MAX_SCOPE_ALIGNMENT_NOTE_LEN]
                if not text:
                    continue
                norm = normalize_text(text)
                if not norm or any(levenshtein_ratio(norm, e) <= 0.15 for e in seen_norms):
                    continue
                cleaned.append((text, note))
                seen_norms.add(norm)

            if len(cleaned) > 5:
                cleaned = cleaned[:5]
            if len(cleaned) < 3:
                if attempt < max_retries:
                    continue
                # Accept what we got per PRD §5 Step 9 — never abort.

            logger.info(
                "brief.authority.generated",
                extra={
                    "count": len(cleaned),
                    "attempt": attempt + 1,
                    "scope_aware": bool(scope_statement),
                },
            )
            return [
                Candidate(
                    text=text,
                    source="authority_gap_sme",
                    exempt=True,
                    scope_alignment_note=note or None,
                )
                for text, note in cleaned
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
