"""Brief Generator Step 3.5 — title + scope statement (M13 slice 5a).

One high-quality LLM call commits the article to an explicit title (50-80 chars
preferred, 100 max) and a scope statement (≤500 chars) that MUST name a `does not
cover` clause (1-3 adjacent topics). Validation + one stricter retry, then abort the
run with `title_generation_failed` (bundle §Step 3.5 failure table; no degraded brief).

Pure: `validate_title_scope`. Egress: `generate_title_scope` (LLM + retry).
"""

from __future__ import annotations

from dataclasses import dataclass

# Generic AI-tells the title must avoid (bundle §Step 3.5 prompt requirements).
AI_TELLS = (
    "ultimate guide to", "complete guide", "everything you need to know",
    "the definitive guide", "master ",
)
MAX_TITLE_CHARS = 100


class TitleGenerationError(Exception):
    """Raised after retries when a valid title/scope can't be produced (aborts the run)."""


@dataclass
class TitleScope:
    title: str
    scope_statement: str
    title_rationale: str = ""


def validate_title_scope(d: dict) -> str | None:
    """Return a failure reason, or None if the title+scope are valid (bundle §Step 3.5
    failure table): non-empty title ≤100 chars; non-empty scope with a `does not cover`
    clause."""
    title = (d.get("title") or "").strip()
    scope = (d.get("scope_statement") or "").strip()
    if not title or len(title) > MAX_TITLE_CHARS:
        return "title_empty_or_too_long"
    if not scope or "does not cover" not in scope.lower():
        return "scope_missing_does_not_cover"
    return None


def generate_title_scope(
    keyword: str, *, intent_type: str, serp_titles: list[str], serp_h1s: list[str],
    serp_metas: list[str], llm_answers: dict[str, str], llm, max_attempts: int = 2,
) -> TitleScope:
    """One tool-use call (+ one stricter retry on a malformed/invalid result), then
    abort with TitleGenerationError. The title quality cascades downstream, so this uses
    the house high-quality model (caller supplies `llm`)."""
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "scope_statement": {"type": "string"},
            "title_rationale": {"type": "string"},
        },
        "required": ["title", "scope_statement"],
    }
    context = (
        "Competitor SERP titles:\n" + "\n".join(f"- {t}" for t in serp_titles[:20])
        + "\n\nCompetitor H1s:\n" + "\n".join(f"- {h}" for h in serp_h1s[:20])
        + "\n\nMeta descriptions:\n" + "\n".join(f"- {m}" for m in serp_metas[:20])
        + "\n\nAI answers:\n" + "\n".join(f"[{k}] {v[:600]}" for k, v in (llm_answers or {}).items())
    )
    base_rules = (
        "Write an article title (50-80 chars preferred, 100 max) and a scope statement "
        "(<=500 chars). The scope statement MUST include a 'does not cover' clause naming "
        "1-3 adjacent topics this article will not address. Avoid generic AI-tells "
        f"({', '.join(AI_TELLS)}). Mention the current year only if the topic warrants it."
    )
    last_err: str | None = None
    for attempt in range(max(1, max_attempts)):
        system = base_rules + (
            "\n\nSTRICT RETRY: the previous attempt was invalid — ensure the title is "
            "non-empty and <=100 chars and the scope statement contains 'does not cover'."
            if attempt > 0 else ""
        )
        try:
            out = llm.call_tool(
                system=system,
                user=f"Seed keyword: {keyword}\nIntent: {intent_type}\n\n{context}",
                tool_name="write_title_scope",
                tool_description="Return the article title, scope statement, and rationale.",
                input_schema=schema,
                purpose="brief_title_scope",
            )
        except Exception as exc:  # noqa: BLE001 — a transport/shape failure is a retryable attempt
            last_err = f"llm_error: {exc}"
            continue
        err = validate_title_scope(out)
        if err is None:
            return TitleScope(
                title=out["title"].strip(),
                scope_statement=out["scope_statement"].strip(),
                title_rationale=(out.get("title_rationale") or "").strip(),
            )
        last_err = err
    raise TitleGenerationError(f"title_generation_failed: {last_err}")
