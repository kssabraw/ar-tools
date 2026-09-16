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


def compose_reopt_notes(
    user_notes: Optional[str],
    *,
    mode: str = "generate",
    deficiencies: Optional[list[dict]] = None,
    prior_sections: Optional[list[dict]] = None,
    gain_guidance: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Compose the writer's editorial notes for a (possibly reoptimize) run.

    Returns ``(section_notes, notes_for_qa)``:
      - ``section_notes`` — fed to every section/intro/conclusion prompt.
      - ``notes_for_qa`` — fed to the notes-landed QA judge (the MUST-LAND
        directives only: the user's own writer notes + the reopt deficiency
        directive).

    The report-only Topic-Vector / Information-Gain coaching (``gain_guidance``)
    is ADVISORY — folded into ``section_notes`` so it can steer the rewrite, but
    EXCLUDED from ``notes_for_qa`` so it is never graded as an unmet user
    instruction ("improve where it fits", not a must-land note). It is never a
    ``deficiencies`` entry (report-only, composite weight 0). Empty/absent
    ``gain_guidance`` ⇒ ``section_notes == notes_for_qa`` — byte-identical to the
    prior behaviour. Pure — no LLM, no network.
    """
    base = (user_notes or "").strip() or None
    if mode == "reoptimize":
        directive = reopt_directive(deficiencies or [], prior_sections)
        if directive:
            base = f"{directive}\n\n{base}" if base else directive
    notes_for_qa = base
    gain = (gain_guidance or "").strip() or None
    section_notes = f"{base}\n\n{gain}" if (base and gain) else (base or gain)
    return section_notes, notes_for_qa
