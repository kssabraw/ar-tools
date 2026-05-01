"""Step 6 — Hypothetical Searcher Persona Generation (Brief Generator v2.0).

Implements PRD §5 Step 6. Single Claude Sonnet 4.6 LLM call that
produces a hypothetical persona for the search query plus 5-10 gap
questions — questions a curious searcher would ask that the existing
candidate pool doesn't address well.

Critical constraint (PRD §2): the persona is derived from topic + SERP
signal ONLY. Brand and ICP context never feed into this — that's the
Writer Module's job. The brief generator stays client-agnostic, which
is why the cache can be shared across clients.

Inputs:
  - Seed keyword
  - intent_type (Step 3)
  - title + scope_statement (Step 3.5)
  - Top SERP H1s + meta descriptions (Step 1)
  - Aggregated candidate headings (Step 4 pre-graph-construction)

Output (strict JSON, additionalProperties: false):
  {
    "persona": {
      "description": "string (≤300 chars)",
      "background_assumptions": ["string (max 5 items)"],
      "primary_goal": "string (≤200 chars)"
    },
    "gap_questions": [
      {"question": "string", "rationale": "string (≤200 chars)"}
    ]
  }

Failure handling (PRD §5 Step 6) — never aborts the run:
  - Malformed JSON → one retry with stricter prompt; second failure
    returns empty result and logs warning
  - Empty persona description → continue (persona is informational)
  - Zero gap questions → continue (selection proceeds without them)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .llm import claude_json

logger = logging.getLogger(__name__)


MAX_DESCRIPTION_LEN = 300
MAX_PRIMARY_GOAL_LEN = 200
MAX_BACKGROUND_ASSUMPTIONS = 5
MAX_RATIONALE_LEN = 200
MIN_GAP_QUESTIONS = 5
MAX_GAP_QUESTIONS = 10


@dataclass
class GapQuestion:
    """A persona-derived gap question that becomes a candidate heading."""
    question: str
    rationale: str = ""


@dataclass
class PersonaResult:
    """Validated Step 6 output. All fields are best-effort: empty values
    are acceptable and the orchestrator continues."""
    description: str = ""
    background_assumptions: list[str] = field(default_factory=list)
    primary_goal: str = ""
    gap_questions: list[GapQuestion] = field(default_factory=list)


LLMJsonFn = Callable[..., Awaitable[Any]]


SYSTEM_PROMPT = """\
You profile the hypothetical searcher behind a keyword and identify
questions they would ask that the existing candidate pool doesn't address.

Your output feeds two downstream uses:
1. The persona description appears in the brief metadata so Writer agents
   can keep the article calibrated to the right reader.
2. Gap questions become candidate H2s that re-enter the heading pool —
   they're the differentiation lever for headings that compete against
   the SERP convention.

Process:
1. Read the seed keyword, intent type, title, and scope statement to
   anchor on what the article is committed to delivering.
2. Look at top SERP H1s and meta descriptions to see what level of
   sophistication the SERP assumes.
3. Scan the aggregated candidate headings to map what's already covered.
4. Infer a single hypothetical searcher: what they know, what they
   assume, what they're trying to accomplish.
5. Write 5-10 gap questions — questions this persona would ask that
   the candidate pool covers poorly or not at all. Each question MUST
   stay within the scope statement; if a question would force the
   article outside scope, leave it out.

Hard requirements:
- The persona is derived from topic + SERP signal ONLY. Do not invent
  brand context, ICP context, or company-specific framings — none of
  that is provided to you and inventing it produces unusable personas.
- 5-10 gap questions (NOT fewer than 5, NOT more than 10).
- Each gap question must be answerable within the article's stated scope.
- Description ≤ 300 chars. Primary goal ≤ 200 chars. Each rationale ≤ 200 chars.
- Maximum 5 background assumptions.

Output strict JSON only — no preamble, no markdown fences, no commentary:
{
  "persona": {
    "description": "Short profile (≤300 chars). Who this person is.",
    "background_assumptions": ["What they likely know already (max 5 items)"],
    "primary_goal": "What they're trying to accomplish by reading this"
  },
  "gap_questions": [
    {
      "question": "Specific question this persona would ask",
      "rationale": "Why this matters and is not adequately covered (≤200 chars)"
    }
  ]
}
"""


STRICTER_RETRY_SUFFIX = """\

CRITICAL: Your previous response was rejected for a validation failure.
Re-read the hard requirements. Output ONLY the JSON object with the
required structure, no surrounding text. The gap_questions array MUST
contain between 5 and 10 entries.
"""


def _format_user_prompt(
    seed_keyword: str,
    intent_type: str,
    title: str,
    scope_statement: str,
    serp_h1s: list[str],
    meta_descriptions: list[str],
    candidate_headings: list[str],
) -> str:
    def _bullets(items: list[str], cap: int = 30) -> str:
        if not items:
            return "(none)"
        out = []
        for i, s in enumerate(items[:cap], 1):
            text = (s or "").strip()
            if text:
                out.append(f"  {i}. {text}")
        return "\n".join(out) if out else "(none)"

    return (
        f"Seed keyword: {seed_keyword}\n"
        f"Intent: {intent_type}\n\n"
        f"Article title (committed): {title}\n"
        f"Scope statement: {scope_statement}\n\n"
        f"Top SERP H1s:\n{_bullets(serp_h1s)}\n\n"
        f"Top meta descriptions:\n{_bullets(meta_descriptions)}\n\n"
        f"Aggregated candidate headings already in the pool:\n"
        f"{_bullets(candidate_headings)}"
    )


def _validate_payload(payload: Any) -> tuple[bool, str, Optional[PersonaResult]]:
    """Validate payload against the strict schema.

    Loosely parses: missing fields default to empty rather than failing.
    The only hard failures that trigger retry are:
      - payload is not a dict
      - gap_questions count is outside [MIN, MAX]
    Empty persona fields are warned but accepted.
    """
    if not isinstance(payload, dict):
        return False, "payload_not_object", None

    persona_raw = payload.get("persona") or {}
    if not isinstance(persona_raw, dict):
        return False, "persona_not_object", None

    description = persona_raw.get("description", "")
    if not isinstance(description, str):
        description = ""
    description = description.strip()[:MAX_DESCRIPTION_LEN]

    bg_raw = persona_raw.get("background_assumptions", []) or []
    if not isinstance(bg_raw, list):
        bg_raw = []
    background_assumptions = [
        str(item).strip() for item in bg_raw[:MAX_BACKGROUND_ASSUMPTIONS]
        if isinstance(item, str) and item.strip()
    ]

    primary_goal = persona_raw.get("primary_goal", "")
    if not isinstance(primary_goal, str):
        primary_goal = ""
    primary_goal = primary_goal.strip()[:MAX_PRIMARY_GOAL_LEN]

    gq_raw = payload.get("gap_questions", [])
    if not isinstance(gq_raw, list):
        return False, "gap_questions_not_list", None

    gap_questions: list[GapQuestion] = []
    for entry in gq_raw:
        if not isinstance(entry, dict):
            continue
        q = entry.get("question")
        r = entry.get("rationale", "") or ""
        if isinstance(q, str) and q.strip():
            gap_questions.append(GapQuestion(
                question=q.strip(),
                rationale=str(r).strip()[:MAX_RATIONALE_LEN],
            ))

    if not (MIN_GAP_QUESTIONS <= len(gap_questions) <= MAX_GAP_QUESTIONS):
        return False, (
            f"gap_questions_count_out_of_range "
            f"({len(gap_questions)} not in [{MIN_GAP_QUESTIONS}, {MAX_GAP_QUESTIONS}])"
        ), None

    return True, "ok", PersonaResult(
        description=description,
        background_assumptions=background_assumptions,
        primary_goal=primary_goal,
        gap_questions=gap_questions,
    )


async def generate_persona(
    *,
    seed_keyword: str,
    intent_type: str,
    title: str,
    scope_statement: str,
    serp_h1s: list[str],
    meta_descriptions: list[str],
    candidate_headings: list[str],
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> PersonaResult:
    """Run Step 6: persona + gap questions, with graceful degradation.

    Never aborts the run. On second-attempt failure (malformed JSON,
    invalid count) returns an empty PersonaResult so selection proceeds
    without persona-derived candidates.

    `llm_json_fn` is injectable for tests; defaults to `claude_json`.
    """
    call = llm_json_fn or claude_json

    user = _format_user_prompt(
        seed_keyword=seed_keyword,
        intent_type=intent_type,
        title=title,
        scope_statement=scope_statement,
        serp_h1s=serp_h1s,
        meta_descriptions=meta_descriptions,
        candidate_headings=candidate_headings,
    )

    last_error: str = "unknown"
    for attempt in (1, 2):
        system = (
            SYSTEM_PROMPT if attempt == 1
            else SYSTEM_PROMPT + STRICTER_RETRY_SUFFIX
        )
        try:
            payload = await call(
                system, user,
                max_tokens=2000,
                temperature=0.4 if attempt == 1 else 0.2,
            )
        except Exception as exc:
            last_error = f"llm_call_exception: {exc}"
            logger.warning(
                "brief.persona.llm_failed",
                extra={"attempt": attempt, "error": str(exc)},
            )
            continue

        ok, reason, parsed = _validate_payload(payload)
        if ok and parsed is not None:
            logger.info(
                "brief.persona.generated",
                extra={
                    "attempt": attempt,
                    "gap_question_count": len(parsed.gap_questions),
                    "has_description": bool(parsed.description),
                    "has_primary_goal": bool(parsed.primary_goal),
                },
            )
            return parsed

        last_error = reason
        logger.warning(
            "brief.persona.invalid",
            extra={"attempt": attempt, "reason": reason},
        )

    logger.warning(
        "brief.persona.degraded",
        extra={
            "reason": last_error,
            "fallback": "empty_persona_result_returned",
        },
    )
    return PersonaResult()
