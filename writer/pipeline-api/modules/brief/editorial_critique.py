"""Adversarial Editorial Critique (PRD v2.6).

Industry-blind-spot mitigation: after the brief is fully assembled,
run ONE Claude call that critiques the outline as if it were an
industry insider noticing what the outline gets wrong, what
conventional wisdom it follows uncritically, and what angles a real
expert would miss the first time.

The critique does NOT change the H2/H3 structure - it's a separate
output strategists see in the dashboard alongside the brief. Surfaces
contrarian angles for human consideration without forcing the outline
into a contrarian shape (which would be self-defeating if the
underlying topic genuinely is well-served by conventional structure).

Failure-safe: LLM exceptions / malformed responses log and return
`available=False`. The brief proceeds without a critique field; the
frontend can show "no critique generated for this run" or hide the
section.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .llm import claude_json

logger = logging.getLogger(__name__)


LLMJsonFn = Callable[..., Awaitable[Any]]


@dataclass
class EditorialCritique:
    """Structured output of `generate_editorial_critique`.

    `available=False` signals "no critique" - caller should hide the
    section in the dashboard rather than show a blank one.
    """

    available: bool = False
    stale_framings: list[str] = field(default_factory=list)
    missing_angles: list[str] = field(default_factory=list)
    contrarian_takes: list[str] = field(default_factory=list)
    overall_assessment: str = ""
    confidence: float = 0.0
    fallback_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "stale_framings": self.stale_framings,
            "missing_angles": self.missing_angles,
            "contrarian_takes": self.contrarian_takes,
            "overall_assessment": self.overall_assessment,
            "confidence": round(self.confidence, 4),
            "fallback_reason": self.fallback_reason,
        }


SYSTEM_PROMPT = """\
You are a senior editor and industry insider reviewing an SEO brief
outline. Your job is NOT to be polite or agreeable. Your job is to
surface the things the outline gets wrong or misses that a real
expert in the topic would notice on second reading.

You will receive:
- The article's keyword and intent
- The committed title and scope_statement
- The full ordered list of selected H2 headings
- (Optional) excerpts from competitor SERP titles

Produce three short lists and a single overall-assessment paragraph:

1. STALE FRAMINGS - conventional wisdom or framing the outline follows
   uncritically that is misleading, outdated, or oversimplified. Be
   specific. "Most articles say X, but the actual situation is Y."

2. MISSING ANGLES - what an industry insider would notice this outline
   doesn't address. Don't list "more keywords" - list specific
   substantive angles a competitor outline ALSO misses but a
   knowledgeable reader would expect.

3. CONTRARIAN TAKES - defensible opposing viewpoints worth the writer
   considering even if they don't end up in the final article. Each
   take should be specific enough that a reader could evaluate it.

End with a one-paragraph OVERALL ASSESSMENT (≤200 words) addressing:
- Does the outline read like generic SERP-following content, or does
  it have a defensible POV?
- What's the single biggest risk if the writer follows this outline
  literally?

Be substantive, not generic. "It could be more engaging" is useless.
"The H2 about X assumes Y when the actual reader segment cares about
Z" is useful.

If the outline is genuinely strong and you have nothing meaningful to
say in a category, return an empty list for that category - don't pad
with weak observations.

Output strict JSON only - no preamble, no markdown fences:
{
  "stale_framings": ["string", "string", ...],
  "missing_angles": ["string", "string", ...],
  "contrarian_takes": ["string", "string", ...],
  "overall_assessment": "single paragraph string",
  "confidence": float between 0 and 1
}

`confidence` is your honest read on how confident you are in this
critique - lower it (0.3-0.5) for niche topics where you'd defer to
domain experts; raise it (0.7-0.9) for topics where standard editorial
judgment applies. Don't fake confidence to seem authoritative."""


def _build_user_prompt(
    *,
    keyword: str,
    intent: str,
    title: str,
    scope_statement: str,
    selected_h2_texts: list[str],
    competitor_titles: list[str],
) -> str:
    return (
        f"Keyword: {keyword}\n"
        f"Intent: {intent}\n"
        f"Title: {title}\n\n"
        f"Scope statement:\n{scope_statement}\n\n"
        f"Selected H2 outline:\n"
        + "\n".join(f"  {i+1}. {t}" for i, t in enumerate(selected_h2_texts))
        + "\n\nTop competitor titles (for reference only - your job is to "
        f"critique the OUTLINE, not summarize the SERP):\n"
        + "\n".join(f"  - {t}" for t in competitor_titles[:10])
    )


def _validate_payload(payload: Any) -> Optional[EditorialCritique]:
    """Parse a Claude response into EditorialCritique. Returns None on
    malformed payload so caller can record a fallback_reason."""
    if not isinstance(payload, dict):
        return None

    def _list_of_strings(key: str) -> list[str]:
        raw = payload.get(key) or []
        if not isinstance(raw, list):
            return []
        return [s.strip() for s in raw if isinstance(s, str) and s.strip()]

    stale = _list_of_strings("stale_framings")
    missing = _list_of_strings("missing_angles")
    contrarian = _list_of_strings("contrarian_takes")

    overall = payload.get("overall_assessment") or ""
    if not isinstance(overall, str):
        overall = ""
    overall = overall.strip()

    confidence = payload.get("confidence")
    if isinstance(confidence, (int, float)):
        confidence = max(0.0, min(1.0, float(confidence)))
    else:
        confidence = 0.5  # neutral default when LLM omits

    if not (stale or missing or contrarian or overall):
        # Completely empty critique - treat as no useful signal
        return None

    return EditorialCritique(
        available=True,
        stale_framings=stale,
        missing_angles=missing,
        contrarian_takes=contrarian,
        overall_assessment=overall,
        confidence=confidence,
    )


async def generate_editorial_critique(
    *,
    keyword: str,
    intent: str,
    title: str,
    scope_statement: str,
    selected_h2_texts: list[str],
    competitor_titles: Optional[list[str]] = None,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> EditorialCritique:
    """Run the adversarial critique pass.

    Returns `EditorialCritique(available=False, ...)` on:
      - LLM call exception
      - Malformed JSON response
      - Empty critique (LLM had nothing useful to add)

    Never aborts the run - the critique is a side output, not a gate.
    """
    if not selected_h2_texts:
        return EditorialCritique(
            available=False, fallback_reason="empty_outline",
        )

    call = llm_json_fn or claude_json
    user = _build_user_prompt(
        keyword=keyword,
        intent=intent,
        title=title,
        scope_statement=scope_statement,
        selected_h2_texts=selected_h2_texts,
        competitor_titles=competitor_titles or [],
    )

    try:
        payload = await call(SYSTEM_PROMPT, user, max_tokens=1500, temperature=0.4)
    except Exception as exc:
        logger.warning(
            "brief.editorial_critique.llm_failed",
            extra={"intent": intent, "error": str(exc)},
        )
        return EditorialCritique(
            available=False, fallback_reason=f"llm_failed: {exc}",
        )

    critique = _validate_payload(payload)
    if critique is None:
        logger.warning(
            "brief.editorial_critique.malformed_or_empty",
            extra={"intent": intent},
        )
        return EditorialCritique(
            available=False, fallback_reason="malformed_or_empty",
        )

    logger.info(
        "brief.editorial_critique.complete",
        extra={
            "intent": intent,
            "stale_framings_count": len(critique.stale_framings),
            "missing_angles_count": len(critique.missing_angles),
            "contrarian_takes_count": len(critique.contrarian_takes),
            "confidence": critique.confidence,
        },
    )
    return critique
