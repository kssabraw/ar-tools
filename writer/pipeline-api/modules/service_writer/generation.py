"""LLM generation for the Service Page Writer.

Conversion-focused, section-level generation driven by the brief's directives.
Prose is produced as structured blocks (paragraph / list / subheading / cta) so
the three renderings stay deterministic. Reuses the brief module's
model-tiered Claude wrapper (Sonnet) + the blog writer's banned-term utilities.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from models.service_writer import Block
from modules.service_brief.llm import claude_json_model, synthesis_model
from modules.writer.banned_terms import build_banned_regex, find_banned

logger = logging.getLogger(__name__)

_ALLOWED_BLOCK_TYPES = {"paragraph", "list", "subheading", "cta"}


def _brand_directive(brand_card: Optional[dict]) -> str:
    if not brand_card:
        return "No brand voice card available — use a confident, professional, conversion-focused tone."
    tone = ", ".join(brand_card.get("tone_adjectives") or []) or "professional, confident"
    directives = "; ".join((brand_card.get("voice_directives") or [])[:6])
    banned = ", ".join((brand_card.get("banned_terms") or [])[:30])
    preferred = ", ".join((brand_card.get("preferred_terms") or [])[:20])
    lines = [f"Tone: {tone}."]
    if directives:
        lines.append(f"Voice directives: {directives}.")
    if preferred:
        lines.append(f"Prefer these terms: {preferred}.")
    if banned:
        lines.append(f"NEVER use these banned terms: {banned}.")
    return " ".join(lines)


def reopt_directive(deficiencies: list[dict], prior_sections: Optional[list[dict]] = None) -> str:
    """Build a reoptimization directive from the scorer's deficiencies (appended to
    the per-call brand_directive so every generation call addresses them). Empty
    string when there's nothing to fix."""
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
        headings = [str(s.get("heading", "")).strip() for s in prior_sections if isinstance(s, dict)]
        headings = [h for h in headings if h]
        if headings:
            prior_note = (
                "\nThe prior draft had these sections (preserve what already works, "
                f"improve the rest): {headings}."
            )
    return (
        "\n\nREOPTIMIZATION PASS — the prior draft scored low on these dimensions; "
        "rewrite to fix them while keeping the page's strengths:\n"
        + "\n".join(lines)
        + prior_note
    )


def _coerce_blocks(raw: Any) -> list[Block]:
    out: list[Block] = []
    for b in (raw or []):
        if not isinstance(b, dict):
            continue
        btype = str(b.get("type", "paragraph")).lower()
        if btype not in _ALLOWED_BLOCK_TYPES:
            btype = "paragraph"
        # Defensive: the LLM occasionally returns a non-numeric level
        # (e.g. "three"); coerce safely so one bad value can't discard the
        # whole section's blocks.
        try:
            level = int(b.get("level", 3) or 3)
        except (TypeError, ValueError):
            level = 3
        out.append(Block(
            type=btype,
            text=str(b.get("text", "")).strip(),
            items=[str(i).strip() for i in (b.get("items") or []) if str(i).strip()],
            level=level,
            href=(str(b["href"]).strip() if b.get("href") else None),
        ))
    # Drop empties (a paragraph with no text / a list with no items).
    return [
        b for b in out
        if (b.type == "list" and b.items) or (b.type != "list" and b.text)
    ]


def _block_text(blocks: list[Block]) -> str:
    parts: list[str] = []
    for b in blocks:
        if b.text:
            parts.append(b.text)
        parts.extend(b.items)
    return "\n".join(parts)


async def generate_title_meta_cta(
    *, service: str, primary_query: str, positioning_angle: str, brand_name: str, brand_directive: str,
) -> dict[str, str]:
    system = (
        "You write SEO metadata + a primary CTA for a commercial service page. "
        "Return ONLY this JSON: {\"title\": \"<=60 chars, includes the query\", "
        "\"meta_description\": \"<=155 chars, benefit + CTA\", "
        "\"cta_text\": \"a short button label, <=5 words\"}. " + brand_directive
    )
    user = (
        f"Service: {service}\nPrimary query: {primary_query}\n"
        f"Positioning angle (the wedge): {positioning_angle}\n"
        f"Brand: {brand_name or '(unknown)'}\nProduce the JSON now."
    )
    try:
        result = await claude_json_model(system, user, model=synthesis_model(), max_tokens=400, temperature=0.4)
        if isinstance(result, dict):
            return {
                "title": str(result.get("title", "")).strip(),
                "meta_description": str(result.get("meta_description", "")).strip(),
                "cta_text": str(result.get("cta_text", "")).strip() or "Get a Free Quote",
            }
    except Exception as exc:
        logger.warning("service_writer.title_meta_failed", extra={"error": str(exc)})
    # Deterministic fallback.
    return {
        "title": (f"{service} | {brand_name}".strip(" |") or primary_query)[:60],
        "meta_description": (positioning_angle or service)[:155],
        "cta_text": "Get a Free Quote",
    }


_SECTION_SYSTEM = (
    "You write ONE section body for a commercial service/landing page as "
    "structured blocks (a plan-faithful execution of the brief). Conversion-"
    "focused, benefit-led, scannable, specific — never generic filler.\n\n"
    "Return ONLY this JSON: {\"blocks\": [ {\"type\": \"paragraph\", \"text\": \"...\"} "
    "| {\"type\": \"list\", \"items\": [\"...\"]} | {\"type\": \"subheading\", "
    "\"text\": \"...\", \"level\": 3} | {\"type\": \"cta\", \"text\": \"...\"} ]}.\n\n"
    "Rules: honor the section purpose; cover the must_cover terms naturally; if a "
    "proof_asset is named, work it in concretely; express the page's positioning "
    "angle; if an objection is mapped, preempt it; aim for roughly the length "
    "target. Do NOT repeat the section heading as a block. No fabricated stats."
)


async def write_section_blocks(
    section: dict[str, Any],
    *,
    positioning_angle: str,
    objection: Optional[str],
    brand_card: Optional[dict],
    brand_directive: str,
) -> list[Block]:
    payload = {
        "heading": section.get("heading", ""),
        "purpose": section.get("purpose", ""),
        "must_cover": section.get("must_cover") or [],
        "proof_asset": section.get("proof_asset"),
        "length_target": section.get("length_target") or 150,
        "citation_fit": section.get("citation_fit", False),
        "divergence_note": section.get("divergence_note"),
        "positioning_angle": positioning_angle,
        "objection_to_preempt": objection,
    }
    user = f"{brand_directive}\n\nSECTION BRIEF:\n{payload}\n\nWrite the blocks JSON now."

    blocks: list[Block] = []
    try:
        result = await claude_json_model(_SECTION_SYSTEM, user, model=synthesis_model(), max_tokens=1800, temperature=0.5)
        blocks = _coerce_blocks(result.get("blocks") if isinstance(result, dict) else None)
    except Exception as exc:
        logger.warning(
            "service_writer.section_failed",
            extra={"heading": section.get("heading"), "error": str(exc)},
        )

    # Banned-term enforcement: one retry if the brand bans leaked terms.
    banned_terms = (brand_card or {}).get("banned_terms") or []
    if blocks and banned_terms:
        regex = build_banned_regex(banned_terms)
        leaked = find_banned(_block_text(blocks), regex)
        if leaked:
            retry_user = (
                f"{user}\n\nThe previous draft used these BANNED terms: {leaked}. "
                "Rewrite the blocks without any of them."
            )
            try:
                result = await claude_json_model(
                    _SECTION_SYSTEM, retry_user, model=synthesis_model(), max_tokens=1800, temperature=0.5
                )
                retried = _coerce_blocks(result.get("blocks") if isinstance(result, dict) else None)
                if retried:
                    blocks = retried
            except Exception as exc:
                logger.warning("service_writer.section_retry_failed", extra={"error": str(exc)})

    return blocks


async def write_faqs(
    questions: list[str],
    *,
    service: str,
    positioning_angle: str,
    brand_directive: str,
) -> list[dict[str, str]]:
    if not questions:
        return []
    system = (
        "You answer FAQs for a commercial service page. Each answer is 1-3 "
        "sentences, direct, helpful, and lightly persuasive. Return ONLY this "
        "JSON: {\"faqs\": [{\"question\": \"...\", \"answer\": \"...\"}]}. " + brand_directive
    )
    user = (
        f"Service: {service}\nPositioning angle: {positioning_angle}\n"
        f"Answer these questions:\n{questions[:8]}\nReturn the JSON now."
    )
    try:
        result = await claude_json_model(system, user, model=synthesis_model(), max_tokens=1500, temperature=0.4)
        faqs = result.get("faqs") if isinstance(result, dict) else None
        out: list[dict[str, str]] = []
        for f in (faqs or []):
            if isinstance(f, dict) and f.get("question") and f.get("answer"):
                out.append({"question": str(f["question"]).strip(), "answer": str(f["answer"]).strip()})
        return out
    except Exception as exc:
        logger.warning("service_writer.faqs_failed", extra={"error": str(exc)})
        return []
