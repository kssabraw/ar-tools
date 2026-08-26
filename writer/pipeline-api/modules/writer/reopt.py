"""Reoptimization directive for the blog Writer.

Mirrors modules/service_writer/generation.py:reopt_directive. In reoptimize
mode the blog pipeline regenerates the article from the same brief, but this
directive — built from the blog scorer's per-engine deficiencies — is appended
to the per-run `user_notes` so every section/intro/conclusion prompt is steered
to fix the low-scoring dimensions while preserving what already works.

Kept as a tiny pure helper so it is unit-testable without the full pipeline.
"""

from typing import Optional


def reopt_directive(
    deficiencies: list[dict], prior_sections: Optional[list[dict]] = None
) -> str:
    """Build a reoptimization directive from the scorer's deficiencies. Returns an
    empty string when there's nothing to fix (so a reoptimize run with no
    deficiencies behaves exactly like a fresh generation)."""
    if not deficiencies:
        return ""
    lines: list[str] = []
    for d in deficiencies:
        if not isinstance(d, dict):
            continue
        eng = d.get("engine") or d.get("engine_key") or "quality"
        issues = "; ".join(str(i) for i in (d.get("issues") or []) if i)
        recs = "; ".join(str(r) for r in (d.get("recommendations") or []) if r)
        piece = f"- {eng}"
        if issues:
            piece += f" — issues: {issues}"
        if recs:
            piece += f" — fixes: {recs}"
        lines.append(piece)
    if not lines:
        return ""
    prior_note = ""
    if prior_sections:
        headings = [
            str(s.get("heading", "")).strip()
            for s in prior_sections
            if isinstance(s, dict)
        ]
        headings = [h for h in headings if h]
        if headings:
            prior_note = (
                "\nThe prior draft had these sections (preserve what already works, "
                f"improve the rest): {headings}."
            )
    return (
        "REOPTIMIZATION PASS — the prior draft of this article scored low on these "
        "quality dimensions; rewrite to fix them while keeping the article's "
        "strengths:\n"
        + "\n".join(lines)
        + prior_note
    )
