"""Step 11.5 - Intent Rewriter (PRD v2.4).

Ports the n8n "Rewrite For Intent" stage. Applies archetype-specific
**structural** rewriting to the finalized H2 set - distinct from
`framing.py`, which only enforces shape (verb-leading, ordinal-leading,
etc.) and silently accepts unfixable headings.

Per archetype:
  - HOW-TO: H2s become sequential procedural steps; the first H2 is the
    primary solution / first action; verb-leading mandatory.
  - LISTICLE: H2s become value-describing list items (each names what
    the reader gets, not just what the item is).
  - INFORMATIONAL: the first H2 is reframed using "Cost of Inaction"
    logic (high-stakes risk or reward of ignoring the topic).

Universal logic across the three archetypes:
  - Primary keyword should anchor the first H2 (or appear in it
    semantically); if no H2 references the keyword at all, the first H2
    is rewritten to do so.
  - H2s containing "FAQ" or "Frequently Asked Questions" are rewritten
    to drop that wording - FAQs are a separate section in the brief, not
    an H2.

Out-of-scope intents (`comparison`, `news`, `local-seo`, `ecom`,
`informational-commercial`, etc.) pass through unchanged - the existing
framing validator handles their shape rules.

Failure handling: never aborts. On LLM call failure or malformed
response, the existing H2 text is preserved and the failure is logged
as `brief.intent_rewrite.llm_failed`. The framing validator runs after
this step and continues to provide a shape safety net.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from models.brief import IntentType

from .graph import Candidate
from .llm import claude_json

logger = logging.getLogger(__name__)


# Intents this module actively rewrites. Other intents pass through and
# rely on the existing framing validator for shape enforcement.
ARCHETYPE_INTENTS: frozenset[IntentType] = frozenset({
    "how-to",
    "listicle",
    "informational",
})


# An H2 is flagged as "softened" when more than this fraction of its
# characters changed in the rewrite. The threshold matches the n8n
# workflow's 50% rule of thumb so downstream consumers (UI badges,
# debugging) get the same signal across pipelines.
SOFTENED_CHANGE_RATIO = 0.50


# H2s containing this regex are forced through rewriting since "FAQ"
# belongs in a dedicated section, not as a content H2.
_FAQ_H2_RE = re.compile(
    r"\b(faq|frequently\s+asked(\s+questions?)?)\b",
    re.IGNORECASE,
)


LLMJsonFn = Callable[..., Awaitable[Any]]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class IntentRewriteResult:
    """Outcome of `rewrite_h2s_for_intent`.

    `rewritten_indices` records every H2 whose text changed (any change).
    `softened_indices` is the subset whose change exceeded
    `SOFTENED_CHANGE_RATIO` - those headings are flagged for downstream
    awareness (UI badges, "this was significantly reframed").
    `passthrough` is True when the intent isn't in `ARCHETYPE_INTENTS`
    or no H2s were provided - the function returned without calling the
    LLM.
    """

    rewritten_indices: list[int] = field(default_factory=list)
    softened_indices: list[int] = field(default_factory=list)
    llm_called: bool = False
    llm_failed: bool = False
    passthrough: bool = False
    archetype: Optional[str] = None


# ---------------------------------------------------------------------------
# Per-archetype prompt fragments
# ---------------------------------------------------------------------------


_ARCHETYPE_INSTRUCTIONS: dict[IntentType, str] = {
    "how-to": (
        "ARCHETYPE: HOW-TO\n"
        "  - The H2 set must read as a sequential procedural guide.\n"
        "  - Each H2 must be ACTIONABLE and OUTCOME-FOCUSED - start with "
        "    an action verb (Plan, Set Up, Configure, Launch, Optimize, "
        "    Measure, Validate, Fix, etc.) or with 'Step N:' format.\n"
        "  - The FIRST H2 must be the primary action the reader takes - "
        "    typically the solution / first step. Move the most "
        "    foundational action to position 1 if it isn't already there.\n"
        "  - Reject any H2 that reads as a question ('What is...?', 'How "
        "    should I...?'). Rewrite these as imperatives covering the "
        "    same underlying topic.\n"
    ),
    "listicle": (
        "ARCHETYPE: LISTICLE\n"
        "  - The H2 set must read as a numbered list of items.\n"
        "  - Each H2 must describe the VALUE the reader gets from the "
        "    item, not just name it. 'Strong onboarding flow' beats "
        "    'Onboarding'.\n"
        "  - Prefix each H2 with its ordinal ('1. ', '2. ', etc.) "
        "    matching its position in the sequence.\n"
        "  - Reject question-form H2s. Rewrite as value-leading noun "
        "    phrases.\n"
    ),
    "informational": (
        "ARCHETYPE: INFORMATIONAL\n"
        "  - The H2 set must read as a logical argument chain.\n"
        "  - The FIRST H2 must use COST OF INACTION framing - surface "
        "    the high-stakes risk, missed opportunity, or hidden "
        "    consequence of ignoring or misunderstanding the topic. "
        "    Examples: 'Why Misreading X Quietly Costs You Y', "
        "    'What Happens When You Skip X', 'The Hidden Risk in X'.\n"
        "  - Subsequent H2s should each answer a distinct reader question "
        "    that builds on the first. Avoid pure 'What is...?' framing "
        "    where possible - prefer 'How X works under the hood', 'Why "
        "    X matters for Y', 'When to choose X vs alternatives'.\n"
    ),
}


_SYSTEM_PROMPT_BASE = """\
You are a Search Intent Architect. You rewrite the H2 outline of a blog
brief so it matches the structural conventions of its target archetype.

You will receive:
- The article's primary keyword and title (the topic commitment)
- The article's archetype (HOW-TO, LISTICLE, or INFORMATIONAL)
- Archetype-specific structural rules to apply
- The current ordered list of H2 headings, each with an integer index

Your job:
1. For each H2, decide whether it already satisfies the archetype rules.
2. Rewrite the H2 text when it does not. Preserve the underlying topic
   exactly - DO NOT change what the section covers; change only how it
   is framed.
3. If an H2 cannot be saved without changing its topic, keep its
   original text (the framing validator will catch it downstream).

UNIVERSAL LOGIC (applies regardless of archetype):
- The primary keyword should appear in or anchor at least one H2 -
  ideally the first. If no H2 carries the keyword, rewrite the
  most-relevant H2 to include it without losing its topic.
- H2s containing 'FAQ' or 'Frequently Asked Questions' must be
  rewritten - FAQs are a separate section, not an H2 here.

OUTPUT (strict JSON only, no preamble, no markdown fences):
{
  "rewrites": [
    {"index": 0, "text": "Rewritten H2 text"},
    {"index": 1, "text": "..."},
    ...
  ]
}

Return one entry per input H2, in the same order, with the same indices.
Use the original text verbatim when no change is needed."""


def _build_system_prompt(intent: IntentType) -> str:
    archetype_block = _ARCHETYPE_INSTRUCTIONS.get(intent, "")
    return f"{_SYSTEM_PROMPT_BASE}\n\n{archetype_block}"


def _build_user_prompt(
    *,
    keyword: str,
    title: str,
    intent: IntentType,
    h2s: list[Candidate],
) -> str:
    items = [{"index": i, "text": c.text} for i, c in enumerate(h2s)]
    return (
        f"Primary keyword: {keyword}\n"
        f"Article title: {title}\n"
        f"Archetype: {intent.upper()}\n\n"
        f"Current H2s (JSON):\n{json.dumps(items, ensure_ascii=False)}"
    )


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------


def _change_ratio(before: str, after: str) -> float:
    """Cheap character-level change ratio.

    Used to decide whether an H2 was "softened" (significantly rewritten)
    vs. minimally adjusted. Levenshtein would be more precise but is
    overkill for a single-heading comparison; the ratio of the longer
    string's length to the matching prefix/suffix length is sufficient
    for the SOFTENED_CHANGE_RATIO threshold check.
    """
    a = (before or "").strip().lower()
    b = (after or "").strip().lower()
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    if a == b:
        return 0.0
    # Common prefix
    prefix = 0
    for x, y in zip(a, b):
        if x == y:
            prefix += 1
        else:
            break
    # Common suffix
    suffix = 0
    for x, y in zip(reversed(a[prefix:]), reversed(b[prefix:])):
        if x == y:
            suffix += 1
        else:
            break
    longer = max(len(a), len(b))
    matched = prefix + suffix
    return max(0.0, min(1.0, 1.0 - matched / longer))


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def rewrite_h2s_for_intent(
    h2s: list[Candidate],
    *,
    keyword: str,
    title: str,
    intent: IntentType,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> IntentRewriteResult:
    """Apply archetype-specific structural rewriting to the H2 set.

    Mutates each Candidate's `.text` in place when the rewrite preserves
    the underlying topic and matches the archetype rules. Returns an
    `IntentRewriteResult` summarizing what changed.

    No-ops for:
      - intents outside `ARCHETYPE_INTENTS`
      - empty H2 lists

    Never aborts the run. On LLM call failure or malformed response,
    leaves all H2 text unchanged and stamps `llm_failed=True` so
    downstream stages and operators can see the gap.
    """
    if intent not in ARCHETYPE_INTENTS or not h2s:
        return IntentRewriteResult(passthrough=True, archetype=str(intent))

    call = llm_json_fn or claude_json
    system = _build_system_prompt(intent)
    user = _build_user_prompt(
        keyword=keyword, title=title, intent=intent, h2s=h2s,
    )

    result = IntentRewriteResult(archetype=str(intent), llm_called=True)
    rewrites_by_index: dict[int, str] = {}

    try:
        response = await call(system, user, max_tokens=900, temperature=0.2)
    except Exception as exc:
        logger.warning(
            "brief.intent_rewrite.llm_failed",
            extra={"intent": intent, "error": str(exc)},
        )
        result.llm_failed = True
        return result

    if isinstance(response, dict):
        rewrites = response.get("rewrites")
        if isinstance(rewrites, list):
            for entry in rewrites:
                if not isinstance(entry, dict):
                    continue
                idx = entry.get("index")
                text = entry.get("text")
                if (
                    isinstance(idx, int)
                    and 0 <= idx < len(h2s)
                    and isinstance(text, str)
                    and text.strip()
                ):
                    rewrites_by_index[idx] = text.strip()

    if not rewrites_by_index:
        logger.warning(
            "brief.intent_rewrite.no_valid_rewrites",
            extra={"intent": intent, "h2_count": len(h2s)},
        )
        return result

    for idx, cand in enumerate(h2s):
        new_text = rewrites_by_index.get(idx)
        if not new_text or new_text == cand.text:
            continue
        ratio = _change_ratio(cand.text, new_text)
        # Hard rejection: if the rewrite STILL contains 'FAQ', the LLM
        # ignored the universal-logic instruction. Keep the original;
        # the framing validator's pass downstream is the safety net.
        if _FAQ_H2_RE.search(new_text):
            logger.warning(
                "brief.intent_rewrite.faq_in_rewrite",
                extra={
                    "intent": intent,
                    "before": cand.text,
                    "after": new_text,
                },
            )
            continue
        cand.text = new_text
        result.rewritten_indices.append(idx)
        if ratio >= SOFTENED_CHANGE_RATIO:
            result.softened_indices.append(idx)

    logger.info(
        "brief.intent_rewrite.complete",
        extra={
            "intent": intent,
            "h2_count": len(h2s),
            "rewritten_count": len(result.rewritten_indices),
            "softened_count": len(result.softened_indices),
        },
    )
    return result
