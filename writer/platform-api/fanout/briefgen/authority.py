"""Brief Generator Step 9 — authority-gap H3s (M13 slice 5c-ii).

A "Universal Authority Agent" (three pillars: Human/Behavioral, Risk/Regulatory,
Long-Term Systems) proposes 3-5 H3 subtopics that competitors miss but that stay within
the article's committed scope (the `does not cover` clause is emphasized). Each H3 is
tagged `source: "authority_gap_sme"`, `exempt: true`, attached to its most-relevant H2.

In the answer-engine-first design these are where genuine differentiation re-enters —
MCS pulls the H2s toward the consensus answer; authority-gap H3s are deliberately NOT
form-enforced toward it (aio §0 #7). Enrichment, not load-bearing: degrades to [].
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MAX_AUTHORITY_H3S = 5
MIN_AUTHORITY_H3S = 3


def generate_authority_gaps(
    keyword: str, *, title: str, scope_statement: str, intent_type: str,
    h2_texts: list[str], reddit_summaries: list[str], llm,
) -> list[dict]:
    """One tool-use call. Returns up to 5 H3 dicts {text, parent_h2_text,
    scope_alignment_note}, each parent restricted to the given H2s. Empty on failure or
    when there are no H2s to attach to."""
    if not h2_texts:
        return []
    schema = {
        "type": "object",
        "properties": {"h3s": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "parent_h2_text": {"type": "string", "enum": list(h2_texts)},
                "scope_alignment_note": {"type": "string"},
            },
            "required": ["text", "parent_h2_text"],
        }}},
        "required": ["h3s"],
    }
    context = (
        "Existing H2s (attach each H3 to its most relevant one):\n"
        + "\n".join(f"- {h}" for h in h2_texts)
        + "\n\nReddit discussion context (for signal, NOT as headings):\n"
        + "\n".join(f"- {s[:200]}" for s in reddit_summaries[:8])
    )
    try:
        out = llm.call_tool(
            system=(
                "You are a subject-matter Authority Agent with three pillars "
                "(Human/Behavioral, Risk/Regulatory, Long-Term Systems). Propose 3-5 H3 "
                "subtopics a true expert would add that competitors miss. CRITICAL: every "
                "H3 MUST stay within the article's scope statement — especially its 'does "
                "not cover' clause. If a pillar would go off-scope, leave it empty and "
                f"return fewer H3s. Scope statement:\n{scope_statement}"
            ),
            user=f"Keyword: {keyword}\nIntent: {intent_type}\nTitle: {title}\n\n{context}",
            tool_name="authority_gaps",
            tool_description="Return 3-5 in-scope authority-gap H3 subtopics.",
            input_schema=schema,
            purpose="brief_authority_gaps",
        )
    except Exception as exc:  # noqa: BLE001 — enrichment; degrade to none
        logger.warning("brief_authority_failed", extra={"event": "brief_authority_failed",
                                                         "keyword": keyword, "reason": repr(exc)})
        return []

    allowed = set(h2_texts)
    result: list[dict] = []
    for h in (out.get("h3s") or []):
        if not isinstance(h, dict):
            continue
        text = (h.get("text") or "").strip()
        parent = (h.get("parent_h2_text") or "").strip()
        if not text or parent not in allowed:
            continue
        result.append({
            "text": text, "parent_h2_text": parent,
            "scope_alignment_note": (h.get("scope_alignment_note") or "").strip(),
        })
        if len(result) >= MAX_AUTHORITY_H3S:
            break
    return result
