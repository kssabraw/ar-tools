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
    "headings other articles cover, your job is to identify 3-5 unique "
    "subheadings that would add genuine information gain across THREE pillars:\n\n"
    "1. HUMAN/BEHAVIORAL — psychological drivers, common errors people make, "
    "emotional decision points. Specifically surface:\n"
    "   - FEARS / CONCERNS readers carry into the topic (what they're worried "
    "will go wrong)\n"
    "   - VALUES readers prize when evaluating options (what \"good\" looks "
    "like to them, in their words)\n"
    "   - RECOMMENDATIONS / HEURISTICS experienced practitioners share with "
    "newcomers (what insiders tell each other)\n"
    "2. RISK/REGULATORY — legal, safety, compliance, financial liabilities\n"
    "3. LONG-TERM SYSTEMS — how this evolves over time, sustainability, "
    "ecosystem outcomes\n\n"
    "INFORMATION GAIN DISCIPLINE: The headings you propose must add coverage "
    "the existing list does NOT already provide. Before emitting each "
    "heading, check: does any heading in the existing-coverage list already "
    "answer this reader question, even partially? If yes, skip it — your job "
    "is to fill the gaps the existing coverage leaves, not to restate it. "
    "Genuine information gain typically lives in the seams between the "
    "existing topics: the unspoken assumptions, the failure modes nobody "
    "documents, the trade-offs experienced practitioners make but beginner-"
    "oriented content omits.\n\n"
    "Rules:\n"
    "- Output exactly 3-5 headings (not more, not less)\n"
    "- Each heading must be distinct from any heading in the existing list\n"
    "- Use sentence case, no trailing punctuation\n"
    "- Each heading should be specific and actionable, not generic\n"
    "- Distribute coverage across all three pillars when possible\n\n"
    "LEVEL ASSIGNMENT (mandatory): For each heading, decide whether it is "
    "an H2 or an H3. Most authority-gap headings are H3s — narrow expert "
    "perspectives that fit naturally under an existing H2. Mark a heading "
    "as H2 ONLY when it is substantial enough to be its own top-level "
    "section: a distinct angle competitors miss entirely (not just a "
    "sub-topic of an existing H2), broad enough to support its own "
    "subsections of content, and not a natural fit under any H2 in the "
    "existing list. At most ONE H2-level gap per article — if multiple "
    "headings could plausibly be H2s, pick the strongest and demote the "
    "rest to H3.\n\n"
    "SCOPE DISCIPLINE (PRD v2.0.3): Authority gap content must respect the "
    "article's scope boundary. The three pillars (Human/Behavioral, Risk/"
    "Regulatory, Long-Term Systems) should explore expertise WITHIN the "
    "scope, not adjacent to it. If a pillar would naturally produce content "
    "outside the scope, prefer leaving that pillar empty over producing "
    "off-scope content. It is acceptable to return three headings instead "
    "of five when staying in-scope requires it.\n\n"
    "For EACH heading, write a `scope_alignment_note` (≤200 chars) that "
    "explains how the heading stays within the scope_statement — especially "
    "the `does not cover` clause. The note is for downstream scope "
    "verification; be specific about WHY the heading is in-scope.\n\n"
    "Respond with a single JSON object:\n"
    "{\n"
    '  "headings": [\n'
    '    {"text": "<heading text>", "level": "H2" | "H3", '
    '"scope_alignment_note": "<≤200 chars>"},\n'
    "    ...\n"
    "  ]\n"
    "}"
)


# At most one H2-level authority gap per article, regardless of what the
# LLM emits — see prompt above. The pipeline relies on this cap when
# enforcing the intent template's `max_h2_count`.
MAX_AUTHORITY_GAP_H2_PER_ARTICLE = 1


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
            # `level` defaults to "H3" when absent — preserves prior behavior
            # for callers / fixtures that predate the H2/H3 split.
            cleaned: list[tuple[str, str, str]] = []  # (text, note, level)
            seen_norms = {normalize_text(h) for h in existing_headings}
            for entry in raw:
                if isinstance(entry, dict):
                    text = entry.get("text") or ""
                    note = entry.get("scope_alignment_note") or ""
                    level = entry.get("level") or "H3"
                elif isinstance(entry, str):
                    text = entry
                    note = ""
                    level = "H3"
                else:
                    continue
                text = (text or "").strip()
                note = (note or "").strip()[:MAX_SCOPE_ALIGNMENT_NOTE_LEN]
                level = level.strip().upper() if isinstance(level, str) else "H3"
                if level not in ("H2", "H3"):
                    level = "H3"
                if not text:
                    continue
                norm = normalize_text(text)
                if not norm or any(levenshtein_ratio(norm, e) <= 0.15 for e in seen_norms):
                    continue
                cleaned.append((text, note, level))
                seen_norms.add(norm)

            if len(cleaned) > 5:
                cleaned = cleaned[:5]
            if len(cleaned) < 3:
                if attempt < max_retries:
                    continue
                # Accept what we got per PRD §5 Step 9 — never abort.

            # Enforce the H2 cap: keep at most MAX_AUTHORITY_GAP_H2_PER_ARTICLE
            # H2-level gaps; demote any extras to H3. Order is preserved so
            # the LLM's first H2 nomination wins when it emits multiple.
            h2_count = 0
            capped: list[tuple[str, str, str]] = []
            demoted = 0
            for text, note, level in cleaned:
                if level == "H2":
                    if h2_count >= MAX_AUTHORITY_GAP_H2_PER_ARTICLE:
                        level = "H3"
                        demoted += 1
                    else:
                        h2_count += 1
                capped.append((text, note, level))
            if demoted:
                logger.info(
                    "brief.authority.h2_overflow_demoted",
                    extra={"demoted_count": demoted, "h2_kept": h2_count},
                )

            logger.info(
                "brief.authority.generated",
                extra={
                    "count": len(capped),
                    "h2_count": h2_count,
                    "h3_count": len(capped) - h2_count,
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
                    authority_gap_level=level,  # type: ignore[arg-type]
                )
                for text, note, level in capped
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
