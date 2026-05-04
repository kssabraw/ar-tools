"""Step 6.8 — ICP callout LLM judge.

Post-write verification that the section designated as the ICP anchor
actually surfaced the audience callout. A regex / substring check would
generate false negatives whenever the LLM paraphrased the hook phrase
("margin erosion from refunds" → "shrinking unit economics on returned
orders"); a small judge prompt handles paraphrase tolerantly.

Position in the pipeline:
  Runs LAST, alongside / after `_verify_brand_mention_landed`. The
  result lands in `WriterMetadata.icp_callout_landed` (warn-and-accept
  signal — never aborts the run, never auto-retries the section).

Failure handling:
  - No ICP anchor assigned (plan didn't pick one) → skip, return
    `(None, None, None)`. There's nothing to verify.
  - ICP anchor section not found in `article` (e.g., dropped during
    retries) → return `(False, None, "anchor_not_in_article")`.
  - LLM call raises (network, rate limit, malformed JSON) → log,
    return `(None, None, "judge_error:<reason>")`. Unknown is the
    honest answer; setting False would falsely flag the run.
  - LLM judge returns malformed payload → return
    `(None, None, "judge_payload_invalid")`.

Cost discipline:
  - One LLM call per article, only when an ICP anchor was assigned.
  - Tight max_tokens (256) — the judge returns a small JSON object,
    not prose.
  - Body is truncated to 4,000 chars before sending — section bodies
    rarely exceed this and the judge doesn't need full context to
    assess whether the audience was named.

Mocking:
  `judge_fn` is injected so tests don't need monkeypatching of
  module-level imports. Defaults to `claude_json`.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from models.writer import ArticleSection, BrandVoiceCard

from modules.brief.llm import claude_json

logger = logging.getLogger(__name__)


JudgeFn = Callable[..., Awaitable[Any]]

_BODY_CHAR_CAP = 4000
_EVIDENCE_CHAR_CAP = 240


_JUDGE_SYSTEM = """You are evaluating whether an article section explicitly surfaces a target audience callout.

OUTPUT FORMAT:
Return a single JSON object:
{
  "icp_callout_landed": true | false,
  "evidence": "<short verbatim quote (≤200 chars) from the body that surfaces the audience, or null if not landed>",
  "reasoning": "<one short sentence>"
}

WHAT COUNTS AS LANDED:
- The hook phrase appears verbatim or paraphrased.
- A close synonym refers to the same audience pain or vertical.
- A direct callout names the audience's situation in the section's own framing of the same need.

WHAT DOES NOT COUNT:
- Generic "B2B leaders" / "businesses" / "marketers" framing without the specific audience signal.
- Mentions of the article's topic or the brand without naming the audience.
- Audience signals unrelated to the hook (e.g., a different pain point or vertical).

Be strict on specificity but tolerant of paraphrase."""


def _build_judge_user_prompt(
    *,
    hook_phrase: str,
    audience_pain_points: list[str],
    audience_verticals: list[str],
    body: str,
) -> str:
    parts: list[str] = []
    parts.append(f"HOOK_PHRASE (the audience signal this section was supposed to surface): {hook_phrase}")
    if audience_pain_points:
        parts.append(
            "AUDIENCE_PAIN_POINTS (any close synonym of these counts as landed): "
            + " | ".join(audience_pain_points[:5])
        )
    if audience_verticals:
        parts.append(
            "AUDIENCE_VERTICALS (mentioning one of these by name when discussing the hook also counts): "
            + ", ".join(audience_verticals[:8])
        )
    truncated = body[:_BODY_CHAR_CAP]
    if len(body) > _BODY_CHAR_CAP:
        truncated += "…[truncated]"
    parts.append("\nSECTION_BODY:\n" + truncated)
    parts.append("\nReturn the JSON object now.")
    return "\n".join(parts)


def _find_anchor_body(
    article: list[ArticleSection],
    anchor_heading_text: str,
) -> Optional[str]:
    """Return the body of the H2 whose heading matches `anchor_heading_text`
    (case-insensitive, whitespace-normalized). Returns None if no match.

    Match by heading text rather than `order` because pipeline.py:632
    resequences every section's order to its final 1..N position before
    this validator runs."""
    target = anchor_heading_text.strip().lower()
    for section in article:
        if section.level != "H2" or section.type != "content":
            continue
        if (section.heading or "").strip().lower() == target:
            return section.body or ""
    return None


async def verify_icp_callout_landed(
    article: list[ArticleSection],
    *,
    icp_anchor_text: Optional[str],
    icp_hook_phrase: Optional[str],
    brand_voice_card: Optional[BrandVoiceCard],
    judge_fn: Optional[JudgeFn] = None,
) -> tuple[Optional[bool], Optional[str], Optional[str]]:
    """Returns `(landed, evidence_quote, status_or_reason)`.

    `landed`:
      - `True`  → judge says the audience callout landed.
      - `False` → judge says it didn't, or the anchor section is missing.
      - `None`  → no ICP anchor was assigned, or the judge call failed.
        Unknown is honest — flagging False would mislead.

    `evidence_quote`: a short verbatim quote when `landed=True`, otherwise
      None.

    `status_or_reason`: a short tag for observability. `"landed"`,
      `"not_landed"`, `"no_anchor"`, `"empty_body"`,
      `"anchor_not_in_article"`, `"judge_error:<type>"`, or
      `"judge_payload_invalid"`.
    """
    if not icp_anchor_text or not icp_hook_phrase:
        return None, None, "no_anchor"

    body = _find_anchor_body(article, icp_anchor_text)
    if body is None:
        logger.warning(
            "writer.icp_judge.anchor_not_in_article",
            extra={"anchor_heading": icp_anchor_text[:120]},
        )
        return False, None, "anchor_not_in_article"
    if not body.strip():
        return False, None, "empty_body"

    fn = judge_fn or claude_json

    pain_points = list((brand_voice_card.audience_pain_points if brand_voice_card else []) or [])
    verticals = list((brand_voice_card.audience_verticals if brand_voice_card else []) or [])

    user_prompt = _build_judge_user_prompt(
        hook_phrase=icp_hook_phrase,
        audience_pain_points=pain_points,
        audience_verticals=verticals,
        body=body,
    )

    try:
        result = await fn(_JUDGE_SYSTEM, user_prompt, max_tokens=256, temperature=0.0)
    except Exception as exc:
        logger.warning(
            "writer.icp_judge.call_failed",
            extra={
                "error_type": type(exc).__name__,
                "error": str(exc)[:300],
                "anchor_heading": icp_anchor_text[:120],
            },
        )
        return None, None, f"judge_error:{type(exc).__name__}"

    if not isinstance(result, dict):
        logger.warning(
            "writer.icp_judge.payload_not_dict",
            extra={"got_type": type(result).__name__},
        )
        return None, None, "judge_payload_invalid"

    landed_raw = result.get("icp_callout_landed")
    if not isinstance(landed_raw, bool):
        logger.warning(
            "writer.icp_judge.landed_not_bool",
            extra={"got": repr(landed_raw)[:80]},
        )
        return None, None, "judge_payload_invalid"

    evidence: Optional[str] = None
    raw_evidence = result.get("evidence")
    if landed_raw and isinstance(raw_evidence, str) and raw_evidence.strip():
        evidence = raw_evidence.strip()[:_EVIDENCE_CHAR_CAP]

    logger.info(
        "writer.icp_judge.complete",
        extra={
            "anchor_heading": icp_anchor_text[:120],
            "hook_phrase": icp_hook_phrase[:120],
            "landed": landed_raw,
            "has_evidence": evidence is not None,
            "reasoning": str(result.get("reasoning") or "")[:200],
        },
    )

    return landed_raw, evidence, "landed" if landed_raw else "not_landed"
