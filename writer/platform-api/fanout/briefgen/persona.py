"""Brief Generator Step 6 — hypothetical searcher persona + gap questions (M13 slice 5c).

One LLM call generates a searcher persona (description / background / primary_goal) and
5-10 "gap questions" a curious searcher would ask that the candidate pool doesn't cover.
The gap questions feed the FAQ pool (Step 10 source C) and decision-fit (A3). Unlike the
title, persona is NOT load-bearing: on repeated failure it degrades to an empty persona
(logged), the run continues (bundle §Step 6 failure table).

Pure: nothing (it's one LLM call). Egress: `generate_persona` (injected llm).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Persona:
    description: str = ""
    background_assumptions: list[str] = field(default_factory=list)
    primary_goal: str = ""
    gap_questions: list[dict] = field(default_factory=list)   # [{question, rationale}]


def generate_persona(
    keyword: str, *, intent_type: str, title: str, scope_statement: str,
    serp_h1s: list[str], serp_metas: list[str], candidate_headings: list[str], llm,
    max_attempts: int = 2,
) -> Persona:
    """Step 6 (single tool-use call + one retry, then degrade to empty — informational,
    not a hard constraint). Gap questions must respect the scope statement."""
    schema = {
        "type": "object",
        "properties": {
            "persona": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "background_assumptions": {"type": "array", "items": {"type": "string"}},
                    "primary_goal": {"type": "string"},
                },
                "required": ["description", "primary_goal"],
            },
            "gap_questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"question": {"type": "string"}, "rationale": {"type": "string"}},
                    "required": ["question"],
                },
            },
        },
        "required": ["persona", "gap_questions"],
    }
    context = (
        "Competitor H1s:\n" + "\n".join(f"- {h}" for h in serp_h1s[:20])
        + "\n\nMeta descriptions:\n" + "\n".join(f"- {m}" for m in serp_metas[:20])
        + "\n\nCandidate headings already in the pool:\n"
        + "\n".join(f"- {c}" for c in candidate_headings[:30])
    )
    for _ in range(max(1, max_attempts)):
        try:
            out = llm.call_tool(
                system=(
                    "You model a curious searcher of a keyword and surface 5-10 GAP "
                    "questions they'd ask that the existing candidate headings do NOT "
                    "cover well. Every gap question MUST stay within the article's scope "
                    "statement. Derive the persona from the topic + SERP signal only."
                ),
                user=(f"Keyword: {keyword}\nIntent: {intent_type}\nTitle: {title}\n"
                      f"Scope: {scope_statement}\n\n{context}"),
                tool_name="searcher_persona",
                tool_description="Return the searcher persona and gap questions.",
                input_schema=schema,
                purpose="brief_persona",
            )
        except Exception as exc:  # noqa: BLE001 — persona is optional; retry then degrade
            logger.warning("brief_persona_attempt_failed", extra={"reason": repr(exc)})
            continue
        p = out.get("persona") or {}
        gaps = [
            {"question": (g.get("question") or "").strip(),
             "rationale": (g.get("rationale") or "").strip()}
            for g in (out.get("gap_questions") or [])
            if isinstance(g, dict) and (g.get("question") or "").strip()
        ]
        return Persona(
            description=(p.get("description") or "").strip(),
            background_assumptions=[s for s in (p.get("background_assumptions") or []) if isinstance(s, str)],
            primary_goal=(p.get("primary_goal") or "").strip(),
            gap_questions=gaps,
        )
    logger.warning("brief_persona_failed", extra={"event": "brief_persona_failed", "keyword": keyword})
    return Persona()
