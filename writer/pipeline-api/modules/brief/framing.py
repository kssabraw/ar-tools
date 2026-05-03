"""Step 11 — H2 Framing Validator (Brief Generator PRD v2.1).

Per the proposal accepted alongside Phase 1: every selected H2 must
satisfy the framing rule of its `intent_format_template`. Failures
trigger a single LLM rewrite pass; if the rewrite still fails, we
warn-and-accept (don't block — empty briefs are worse than imperfectly
framed ones).

The validator runs AFTER Step 8 (MMR selection) and Step 8.5 (scope
verification) but BEFORE the how-to reorder LLM call (Step 8.6 prep)
so that:
  1. Reorder operates on already-correctly-framed action H2s.
  2. The rewrite preserves the intent of each H2 (we never re-MMR or
     re-scope after rewriting).

Failure-mode policy (matches Step 8.5 / 8.5b conventions):
  - Regex pre-check classifies each H2 as `pass` or `violation`.
  - Violations are batched into a single LLM call that returns rewritten
    text per H2.
  - If the rewrite text STILL fails the regex, we accept the original
    text but stamp `framing_violation_accepted = True` on the candidate
    so dashboards can surface chronic offenders.
  - LLM call failure: log + accept all originals; never abort.

Regex rules per framing_rule:

| framing_rule                | Pass condition                                       |
|-----------------------------|------------------------------------------------------|
| verb_leading_action         | First token is a verb (action verb whitelist or     |
|                             | "ing"/"e"-stem heuristic) — captures "Plan…",       |
|                             | "Set Up…", "Optimize…". Also accepts an explicit    |
|                             | "Step <N>:" prefix.                                  |
| ordinal_then_noun_phrase    | Leading numeral followed by space (e.g. "1. ") OR  |
|                             | leading "#<N>" / "Top N".                            |
| axis_noun_phrase            | Short noun-phrase (≤6 words), no leading verb,      |
|                             | doesn't start with "How"/"What"/"Why".               |
| question_or_topic_phrase    | Starts with What/How/Why/Where/Who/When OR a noun- |
|                             | phrase (no constraint other than non-empty).         |
| buyer_education_phrase      | Either question form OR an axis-style noun-phrase   |
|                             | mentioning evaluation/comparison/selection.          |
| no_constraint               | Always passes (used for news / local-seo / fallback).|
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from models.brief import H2FramingRule, IntentFormatTemplate

from .graph import Candidate
from .llm import claude_json

logger = logging.getLogger(__name__)


LLMJsonFn = Callable[..., Awaitable[Any]]


# ---------------------------------------------------------------------------
# Regex tables
# ---------------------------------------------------------------------------

# Common action-verb starters. Not exhaustive — `_passes_verb_leading`
# additionally accepts any first word that is NOT in the non-verb-leader
# reject list (`_NON_VERB_LEADERS`), since English imperatives are too
# varied to whitelist comprehensively. The whitelist is kept primarily
# so a future tightening of the predicate can flip back to whitelist-
# only mode without rebuilding the registry.
_ACTION_VERBS: frozenset[str] = frozenset({
    "add", "audit", "build", "buy", "check", "choose", "clean", "configure",
    "connect", "consider", "create", "decide", "deploy", "design", "draft",
    "enable", "evaluate", "execute", "explore", "find", "fix", "generate",
    "handle", "identify", "implement", "improve", "increase", "install",
    "integrate", "iterate", "launch", "learn", "list", "load", "log",
    "make", "manage", "map", "maximize", "measure", "minimize", "monitor",
    "open", "optimize", "organize", "outline", "pick", "plan", "post",
    "prepare", "publish", "refine", "register", "research", "review", "run",
    "schedule", "select", "set", "setup", "ship", "sign", "start", "store",
    "submit", "test", "track", "tune", "update", "upload", "validate",
    "verify", "write",
})


# Words that signal an H2 is NOT a verb-leading action — questions,
# auxiliaries, articles, determiners, generic superlatives. If the first
# word is in this set, `_passes_verb_leading` returns False and the
# framing validator routes the H2 to LLM rewrite. Conversely, if the
# first word is NOT in this set, the validator accepts it as plausibly
# verb-leading. This permissive default exists because English
# imperatives are too varied to whitelist exhaustively (configure, ship,
# pick, handle, scale, …) and the previous verb-stem regex had both
# false-pass cases (e.g. "Where", "Should") and false-reject cases
# (e.g. "Configuring", "Consider", "Handle").
_NON_VERB_LEADERS: frozenset[str] = frozenset({
    # Question/interrogative words
    "what", "how", "why", "where", "who", "when", "which", "whose",
    # Auxiliary / modal verbs that lead questions
    "are", "is", "am", "was", "were", "be", "been",
    "do", "does", "did",
    "can", "could", "may", "might", "shall", "should", "will", "would",
    "has", "have", "had",
    # Articles
    "a", "an", "the",
    # Determiners / possessives
    "this", "that", "these", "those",
    "your", "my", "our", "his", "her", "their", "its",
    # Generic superlatives / commercial AI-tells (PRD §11 banned phrases)
    "best", "top", "ultimate", "complete", "definitive", "everything",
    # "Number N:" listicle marker — treat the bare word "number" as a
    # non-verb leader; the "Number 2: Validate" pattern is unwrapped
    # by the numeric-ordinal recursion in `_passes_verb_leading` so the
    # actual first word ("validate") is what's tested.
    "number",
})


_STEP_PREFIX_RE = re.compile(r"^\s*step\s+\d+\s*[:.\-]\s+", re.IGNORECASE)
_ORDINAL_RE = re.compile(
    r"^\s*(?:#?\d+[\.\)]?\s+|top\s+\d+\s+|number\s+\d+[:\.]?\s+)",
    re.IGNORECASE,
)
# Numeric ordinal only — used by `_passes_verb_leading` to peel off
# "1. " / "2) " / "#3 " / "Number 4:" prefixes and recurse on the rest.
# Distinct from `_ORDINAL_RE` because "Top N" should NOT auto-pass
# verb-leading (the word "Top" is itself a non-verb leader).
_NUMERIC_ORDINAL_PREFIX_RE = re.compile(
    r"^\s*(?:number\s+)?#?\d+[\.\):]?\s+",
    re.IGNORECASE,
)
# Match a leading question/auxiliary word — used by axis_noun_phrase to
# reject question-style headings without going through verb_leading.
_QUESTION_LEAD_RE = re.compile(
    r"^\s*(?:what|how|why|where|who|when|which|whose|"
    r"are|is|am|was|were|be|been|"
    r"do|does|did|"
    r"can|could|may|might|shall|should|will|would|"
    r"has|have|had)\b",
    re.IGNORECASE,
)


def _first_word(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    # Strip leading punctuation that's not a word/digit so "1. Plan" → "Plan"
    # after we've already extracted the ordinal. For the verb test we just
    # want the actual leading lexical token.
    m = re.match(r"^[^A-Za-z0-9]*([A-Za-z]+)", stripped)
    return m.group(1).lower() if m else ""


# ---------------------------------------------------------------------------
# Per-rule pass predicates
# ---------------------------------------------------------------------------


def _passes_verb_leading(text: str) -> bool:
    """Verb-leading predicate (PRD v2.1 Step 11.0).

    Pass conditions:
      - Explicit "Step <N>:" prefix
      - Leading ordinal "1. " / "2. " etc. (a how-to step is still
        action-leading even when the verb is preceded by a numeral)
      - First lexical token is in the action-verb whitelist
      - First lexical token is NOT in the non-verb-leader reject list
        (questions, auxiliaries, articles, determiners, superlatives)

    The fall-through-to-accept policy is deliberately permissive: English
    imperatives are too varied to whitelist exhaustively, and "false
    positives" (a non-verb noun phrase passing the predicate) are
    preferable to "false rejects" (a valid imperative routed through an
    unnecessary LLM rewrite). The framing validator's purpose is to
    catch the *clear* failure case — Q&A-style H2s on a how-to article —
    not to nitpick word forms.
    """
    if _STEP_PREFIX_RE.match(text):
        return True
    # Numeric ordinal prefix: peel off "1. " / "#3 " / "Number 4:" and
    # recurse on the remainder. This makes "1. Choose a niche" pass
    # because "choose" is in the action-verb whitelist, while "Top 5
    # tactics" still fails (no numeric ordinal at the very start; the
    # bare word "top" is in `_NON_VERB_LEADERS`).
    m = _NUMERIC_ORDINAL_PREFIX_RE.match(text)
    if m and m.end() < len(text):
        return _passes_verb_leading(text[m.end():])
    first = _first_word(text)
    if not first:
        return False
    if first in _NON_VERB_LEADERS:
        return False
    if first in _ACTION_VERBS:
        return True
    # Default-accept: first word isn't in either set, presume verb.
    return True


def _passes_ordinal(text: str) -> bool:
    return bool(_ORDINAL_RE.match(text))


def _passes_axis_noun_phrase(text: str) -> bool:
    """Short noun-phrase headings (comparison axes, ecom feature-benefit).

    Pass conditions:
      - Non-empty after stripping whitespace
      - Does NOT lead with a question/auxiliary word
      - Does NOT lead with a listicle ordinal (those belong under
        `ordinal_then_noun_phrase`, not axis)
      - ≤ 8 words (axes are short by convention; "Pricing and Plans"
        passes, "How to evaluate which TikTok Shop fits your business
        model" does not)

    Action-leading is NOT explicitly rejected here — short imperative
    forms like "Compare" or "Pick" are sometimes valid axis labels. The
    upstream Step 5 relevance gates already filter for on-topic content;
    this predicate enforces *shape* only.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if _QUESTION_LEAD_RE.match(stripped):
        return False
    if _ORDINAL_RE.match(stripped):
        return False
    return len(stripped.split()) <= 8


def _passes_question_or_topic(text: str) -> bool:
    return bool(text.strip())


def _passes_buyer_education(text: str) -> bool:
    if _passes_question_or_topic(text):
        return True
    return _passes_axis_noun_phrase(text)


_PASS_PREDICATES: dict[H2FramingRule, Callable[[str], bool]] = {
    "verb_leading_action": _passes_verb_leading,
    "ordinal_then_noun_phrase": _passes_ordinal,
    "axis_noun_phrase": _passes_axis_noun_phrase,
    "question_or_topic_phrase": _passes_question_or_topic,
    "buyer_education_phrase": _passes_buyer_education,
    "no_constraint": lambda _t: True,
}


def passes_framing(text: str, rule: H2FramingRule) -> bool:
    """Public predicate — also exposed for tests."""
    pred = _PASS_PREDICATES.get(rule, _PASS_PREDICATES["no_constraint"])
    return pred(text)


# ---------------------------------------------------------------------------
# LLM rewrite
# ---------------------------------------------------------------------------


_RULE_PROMPT_HINTS: dict[H2FramingRule, str] = {
    "verb_leading_action": (
        "Each H2 must start with an action verb (e.g. 'Plan', 'Set Up', "
        "'Optimize', 'Validate'). Keep the heading specific to its current "
        "topic — do not change what the section is about."
    ),
    "ordinal_then_noun_phrase": (
        "Each H2 must start with a numeral and period (e.g. '1. ', '2. '). "
        "Keep the noun-phrase that follows; only add the ordinal."
    ),
    "axis_noun_phrase": (
        "Each H2 must be a short noun-phrase naming a comparison axis "
        "(e.g. 'Pricing', 'Feature Set', 'Support'). Strip any leading "
        "verb, question word, or article."
    ),
    "question_or_topic_phrase": (
        "Each H2 must be a topic phrase or question (e.g. 'What is X', "
        "'How X works'). Do not turn it into a sales line."
    ),
    "buyer_education_phrase": (
        "Each H2 must be a buyer-education phrase — either a question "
        "('What to look for in X') or a comparison axis ('Pricing models')."
    ),
    "no_constraint": "No specific constraint.",
}


_REWRITE_SYSTEM = """You normalize blog H2 headings to a target framing rule.

You receive a list of H2 headings and the target framing rule. For each
heading, return the same heading rewritten to satisfy the framing rule.
Preserve the heading's topic exactly — do NOT change what the section
covers. Keep the rewrite concise (≤ 80 characters preferred).

Output strict JSON:
  {"rewrites": [{"index": 0, "text": "Rewritten heading"}, ...]}

Return one entry per input heading, in the same order, with the same
indices. Never invent new topics; never drop headings."""


@dataclass
class FramingResult:
    """Outcome of `validate_and_rewrite_framing`.

    `rewritten_indices` records H2 positions whose text was rewritten by
    the LLM (regardless of whether the rewrite passed the regex on
    second look). `accepted_with_violation_indices` records H2s that
    failed the regex on BOTH attempts and were accepted as-is — these
    are the warn-and-accept fallback cases.
    """

    rewritten_indices: list[int] = field(default_factory=list)
    accepted_with_violation_indices: list[int] = field(default_factory=list)
    llm_called: bool = False
    llm_failed: bool = False


async def validate_and_rewrite_framing(
    h2s: list[Candidate],
    template: IntentFormatTemplate,
    *,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> FramingResult:
    """Validate every H2 against `template.h2_framing_rule` and rewrite
    failures via a single batched LLM call.

    Mutates the offending Candidates' `.text` field in place when the
    rewrite produces text that passes the regex; otherwise leaves the
    text unchanged and stamps the candidate index in
    `accepted_with_violation_indices`.

    Pure NOOP when:
      - `template.h2_framing_rule == "no_constraint"`.
      - All H2s already pass the regex.
    """
    rule = template.h2_framing_rule
    result = FramingResult()
    if rule == "no_constraint" or not h2s:
        return result

    failing: list[tuple[int, Candidate]] = [
        (i, c) for i, c in enumerate(h2s) if not passes_framing(c.text, rule)
    ]
    if not failing:
        return result

    call = llm_json_fn or claude_json

    items_payload = [
        {"index": i, "text": c.text} for i, c in failing
    ]
    # Serialize as JSON (not Python repr) so headings containing
    # apostrophes / backslashes / unicode never produce ambiguous
    # quoting in the prompt.
    user = (
        f"Framing rule: {rule}\n"
        f"Hint: {_RULE_PROMPT_HINTS.get(rule, '')}\n"
        f"Headings to rewrite (JSON):\n{json.dumps(items_payload, ensure_ascii=False)}"
    )

    result.llm_called = True
    rewrites_by_index: dict[int, str] = {}
    try:
        response = await call(_REWRITE_SYSTEM, user, max_tokens=600, temperature=0)
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
                        and isinstance(text, str)
                        and text.strip()
                    ):
                        rewrites_by_index[idx] = text.strip()
    except Exception as exc:
        logger.warning(
            "brief.framing.llm_failed",
            extra={"intent": template.intent, "rule": rule, "error": str(exc)},
        )
        result.llm_failed = True

    for idx, cand in failing:
        new_text = rewrites_by_index.get(idx)
        if new_text and passes_framing(new_text, rule):
            logger.info(
                "brief.framing.rewritten",
                extra={
                    "intent": template.intent,
                    "rule": rule,
                    "before": cand.text,
                    "after": new_text,
                },
            )
            cand.text = new_text
            result.rewritten_indices.append(idx)
        else:
            logger.warning(
                "brief.framing.violation_accepted",
                extra={
                    "intent": template.intent,
                    "rule": rule,
                    "heading": cand.text,
                    "rewrite_attempted": new_text or "",
                },
            )
            result.accepted_with_violation_indices.append(idx)

    logger.info(
        "brief.framing.complete",
        extra={
            "intent": template.intent,
            "rule": rule,
            "h2_count": len(h2s),
            "failing_count": len(failing),
            "rewritten_count": len(result.rewritten_indices),
            "accepted_with_violation_count": len(
                result.accepted_with_violation_indices
            ),
            "llm_failed": result.llm_failed,
        },
    )
    return result
