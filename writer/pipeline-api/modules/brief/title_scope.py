"""Step 3.5 - Title + Scope Statement Generation (Brief Generator v2.0).

Implements PRD §5 Step 3.5. Single Claude Sonnet 4.6 LLM call that
produces the article's committed title and scope_statement, which
anchor every downstream selection and verification step in v2.0.

Without this commitment, scope discipline can only be approximated from
indirect signals - that's the v1.7 failure mode this module fixes.

Inputs (PRD §5 Step 3.5):
  - Seed keyword
  - intent_type (from Step 3)
  - Top 20 SERP titles, H1s, meta descriptions (from Step 1)
  - LLM fan-out response bodies (from Step 2D, full text not just queries)

Output (strict JSON, additionalProperties: false):
  {
    "title": str (50-80 chars preferred, 100 max),
    "scope_statement": str (≤500 chars, MUST include "does not cover"),
    "title_rationale": str (≤300 chars)
  }

Failure handling (PRD §5 Step 3.5):
  - Malformed JSON / missing field / overlong / no does-not-cover →
    one retry with stricter prompt
  - On second failure → raise BriefError("title_generation_failed").
    PRD treats this as a hard abort because every downstream step
    depends on the title.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from .errors import BriefError
from .llm import claude_json

logger = logging.getLogger(__name__)


MAX_TITLE_LEN = 100
MAX_H1_LEN = 130
MAX_SCOPE_LEN = 500
MAX_RATIONALE_LEN = 300

REQUIRED_SCOPE_PHRASE = "does not cover"

# Generic AI-tell phrases the prompt explicitly forbids in titles.
BANNED_TITLE_PHRASES: tuple[str, ...] = (
    "ultimate guide",
    "complete guide",
    "everything you need to know",
    "definitive guide",
    "master ",
)


@dataclass
class TitleScopeOutput:
    """Validated Step 3.5 output."""

    title: str
    h1: str
    scope_statement: str
    title_rationale: str


# Type alias so tests can inject a synthetic claude_json.
LLMJsonFn = Callable[..., Awaitable[Any]]


SYSTEM_PROMPT = """\
You generate the article title and scope statement for an SEO/AEO blog brief.

Your output anchors every downstream selection and verification step in
the brief generator. Get the framing right and the rest of the brief
inherits the right boundaries; get it wrong and downstream sections will
either restate the title or drift outside its scope.

Process:
1. Examine the competitor titles, H1s, and meta descriptions to identify
   the SERP convention for this query (definitional? listicle? how-to?
   comparison?). The intent classification you receive is a strong hint.
2. Note what no competitor is doing - angles, framings, or differentiators
   that none of the top 20 are using. These are candidates for the article's
   unique angle.
3. Read the LLM fan-out response bodies to see what searchers ask AI
   assistants about this topic. These often surface gaps in SERP coverage.
4. Write a title that matches SERP convention but adds at most one
   differentiator (year, audience qualifier, framing twist).
5. Write a scope statement that is specific enough to be enforceable
   but not so specific that it preempts editorial judgment in the
   Writer Module. The scope MUST include a "does not cover:" clause
   listing 1-3 adjacent topics this article will explicitly NOT address.

Hard requirements for the title (SEO / meta title - appears in browser
tab, SERP snippet, and og:title):
- 50-80 characters preferred; 100 character maximum
- AVOID generic AI-tells: "Ultimate Guide to", "Complete Guide",
  "Everything You Need to Know", "Definitive Guide", "Master [topic]"
- Mention the current year ONLY when the topic genuinely warrants it
  (rapidly changing space, version-specific content). Do not reflexively
  stamp a year on every title.

Hard requirements for the h1 (on-page main heading - appears at the
top of the article body):
- 130 character maximum (longer leeway than the title)
- Often similar to the title, but MAY be slightly more descriptive,
  more conversational, or expand on the title's framing. The H1's job
  is to confirm to the on-page reader that they landed on the right
  article - it does NOT have to be SERP-optimized.
- It is acceptable for h1 == title when the title already reads as a
  natural on-page heading. Do not force a difference.
- Same banned-phrase rules as the title.

Hard requirements for the scope statement:
- 500 character maximum
- MUST contain the literal phrase "does not cover" introducing the
  exclusion clause
- Name 1-3 specific adjacent topics that are out of scope

Output strict JSON only - no preamble, no markdown fences, no commentary:
{
  "title": "SEO/meta title (50-80 chars preferred, ≤100 max)",
  "h1": "On-page H1 heading (≤130 chars; may equal the title or expand it slightly)",
  "scope_statement": "Defines/explains... [in-scope]. Does not cover [adjacent topics].",
  "title_rationale": "Brief explanation (≤300 chars) of why this title and angle"
}
"""


STRICTER_RETRY_PROMPT_SUFFIX = """\

CRITICAL: Your previous response was rejected for a validation failure.
Re-read the hard requirements. Output ONLY the JSON object with the three
required fields, no surrounding text. The scope_statement MUST contain
the literal phrase "does not cover". The title MUST be ≤100 characters
and MUST NOT contain banned phrases.
"""


def _format_user_prompt(
    seed_keyword: str,
    intent_type: str,
    serp_titles: list[str],
    serp_h1s: list[str],
    meta_descriptions: list[str],
    fanout_response_bodies: list[str],
) -> str:
    """Build the user-message body that carries the raw inputs."""
    def _bullets(items: list[str], cap: int = 20) -> str:
        if not items:
            return "(none)"
        out = []
        for i, s in enumerate(items[:cap], 1):
            text = (s or "").strip()
            if text:
                out.append(f"  {i}. {text}")
        return "\n".join(out) if out else "(none)"

    # Cap fan-out bodies so we don't blow the prompt budget. Each body
    # may be long; trim individual entries to keep the total bounded.
    trimmed_bodies = [
        (body or "")[:1500] for body in fanout_response_bodies[:4]
    ]

    return (
        f"Seed keyword: {seed_keyword}\n"
        f"Classified intent: {intent_type}\n\n"
        f"Top SERP titles (up to 20):\n{_bullets(serp_titles)}\n\n"
        f"Top SERP H1s (up to 20):\n{_bullets(serp_h1s)}\n\n"
        f"Top meta descriptions (up to 20):\n{_bullets(meta_descriptions)}\n\n"
        f"LLM fan-out response bodies (full text from up to 4 LLMs):\n"
        + "\n\n---\n\n".join(
            f"[{i+1}] {body}" for i, body in enumerate(trimmed_bodies) if body
        )
    )


def _validate_payload(payload: Any) -> tuple[bool, str, Optional[TitleScopeOutput]]:
    """Validate an LLM JSON payload against the strict schema.

    Returns (ok, error_reason, parsed). When ok is False, the orchestrator
    knows to retry (or abort on the second attempt). When ok is True,
    `parsed` carries the validated TitleScopeOutput.
    """
    if not isinstance(payload, dict):
        return False, "payload_not_object", None

    title = payload.get("title")
    scope = payload.get("scope_statement")
    rationale = payload.get("title_rationale", "")
    h1_raw = payload.get("h1")

    if not isinstance(title, str) or not title.strip():
        return False, "title_missing_or_empty", None
    title = title.strip()
    if len(title) > MAX_TITLE_LEN:
        return False, f"title_too_long ({len(title)} > {MAX_TITLE_LEN})", None

    title_lower = title.lower()
    for banned in BANNED_TITLE_PHRASES:
        if banned in title_lower:
            return False, f"title_contains_banned_phrase: {banned!r}", None

    # H1 falls back to title when missing (older payloads / LLM omits the
    # field). When present, it gets the same banned-phrase check as the
    # title but a longer length cap (on-page headings can be more
    # descriptive than SERP titles).
    if isinstance(h1_raw, str) and h1_raw.strip():
        h1 = h1_raw.strip()
        if len(h1) > MAX_H1_LEN:
            return False, f"h1_too_long ({len(h1)} > {MAX_H1_LEN})", None
        h1_lower = h1.lower()
        for banned in BANNED_TITLE_PHRASES:
            if banned in h1_lower:
                return False, f"h1_contains_banned_phrase: {banned!r}", None
    else:
        h1 = title

    if not isinstance(scope, str) or not scope.strip():
        return False, "scope_statement_missing_or_empty", None
    scope = scope.strip()
    if len(scope) > MAX_SCOPE_LEN:
        return False, f"scope_too_long ({len(scope)} > {MAX_SCOPE_LEN})", None
    if REQUIRED_SCOPE_PHRASE not in scope.lower():
        return False, "scope_missing_does_not_cover_clause", None

    if not isinstance(rationale, str):
        return False, "rationale_wrong_type", None
    rationale = rationale.strip()
    if len(rationale) > MAX_RATIONALE_LEN:
        # Rationale is informational only; truncate rather than reject.
        rationale = rationale[:MAX_RATIONALE_LEN]

    return True, "ok", TitleScopeOutput(
        title=title,
        h1=h1,
        scope_statement=scope,
        title_rationale=rationale,
    )


async def generate_title_and_scope(
    *,
    seed_keyword: str,
    intent_type: str,
    serp_titles: list[str],
    serp_h1s: list[str],
    meta_descriptions: list[str],
    fanout_response_bodies: list[str],
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> TitleScopeOutput:
    """Run Step 3.5: single Claude call with one strict-retry on failure.

    Aborts the run with BriefError("title_generation_failed") on second
    failure - every downstream step depends on the title.

    `llm_json_fn` is injectable for tests; defaults to `claude_json` so
    production code calls Sonnet 4.6 directly.
    """
    call = llm_json_fn or claude_json

    user = _format_user_prompt(
        seed_keyword=seed_keyword,
        intent_type=intent_type,
        serp_titles=serp_titles,
        serp_h1s=serp_h1s,
        meta_descriptions=meta_descriptions,
        fanout_response_bodies=fanout_response_bodies,
    )

    last_error: str = "unknown"
    for attempt in (1, 2):
        system = (
            SYSTEM_PROMPT if attempt == 1
            else SYSTEM_PROMPT + STRICTER_RETRY_PROMPT_SUFFIX
        )
        try:
            payload = await call(
                system, user,
                max_tokens=900,
                # First attempt: 0.7 for meaningful variation across
                # regenerations of the same keyword (the brief generator
                # is the source of truth for title/h1, and the writer
                # consumes them verbatim - so title diversity has to come
                # from THIS call). Retry drops to 0.1 to maximize the
                # chance the structured output validates after a
                # malformed first response.
                temperature=0.7 if attempt == 1 else 0.1,
            )
        except Exception as exc:
            last_error = f"llm_call_exception: {exc}"
            logger.warning(
                "brief.title_scope.llm_failed",
                extra={"attempt": attempt, "error": str(exc)},
            )
            continue

        ok, reason, parsed = _validate_payload(payload)
        if ok and parsed is not None:
            logger.info(
                "brief.title_scope.generated",
                extra={
                    "attempt": attempt,
                    "title_len": len(parsed.title),
                    "scope_len": len(parsed.scope_statement),
                },
            )
            return parsed

        last_error = reason
        logger.warning(
            "brief.title_scope.invalid",
            extra={"attempt": attempt, "reason": reason},
        )

    raise BriefError(
        "title_generation_failed",
        f"Title + scope statement generation failed after retry: {last_error}",
    )
