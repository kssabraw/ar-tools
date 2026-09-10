"""Website Builder — assembling a project / case-study page.

A case study is the one page type that is **entirely real-job facts** (reference
§ Case Study / Project Page, Writer #9): situation → work → result, with photos,
stats and a client testimonial. Its defining pitfall is "fabricated or
unverifiable results", so the human supplies every fact through the Add-project
form and this module NEVER invents one:

* the structured facts (stat callouts, photos, testimonial, geo, the linked
  service/location) are passed straight through to `sections` frontmatter, which
  the template renders deterministically;
* the three prose fields (challenge / work / outcome) are OPTIONALLY narrated by
  one LLM call whose only job is to turn the operator's supplied notes into
  flowing prose — invent-nothing, best-effort. A disabled/failed narration
  degrades to the operator's raw text, which is always usable on its own.

So this writer is deliberately small (one Anthropic call, no SERP, no scoring)
and lives in platform-api beside the core-pages writer, for the same reason: the
only thing nlp would add is brand-voice prose the suite already renders here.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from config import settings
from services import report_llm

logger = logging.getLogger(__name__)


# The prose sections a case study tells its story through (reference page
# structure: Challenge → Work performed → Outcome). Order is fixed.
_PROSE_FIELDS = ("challenge", "work", "outcome")
_PROSE_HEADINGS = {
    "challenge": "The challenge",
    "work": "What we did",
    "outcome": "The result",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _stat_list(project: dict) -> list[dict]:
    """Up to four {label, value} stat callouts, both sides non-empty."""
    out: list[dict] = []
    for raw in project.get("stats") or []:
        label, value = _clean(raw.get("label")), _clean(raw.get("value"))
        if label and value:
            out.append({"label": label, "value": value})
    return out[:4]


def _photo_list(project: dict) -> list[dict]:
    """Pasted image URLs with optional alt/caption. A photo with no URL is dropped."""
    out: list[dict] = []
    for raw in project.get("photos") or []:
        url = _clean(raw.get("url"))
        if url:
            out.append({"url": url, "alt": _clean(raw.get("alt")), "caption": _clean(raw.get("caption"))})
    return out


def _links(project: dict) -> list[dict]:
    """The matching service / location pages this case study links to (reference:
    body internal links). Stored as ready-to-render `{href, title}` items; the
    operator supplies the slug, so a slug that is not (yet) published just links
    to a page that will exist once generated — the same self-healing the rest of
    the structural linking relies on."""
    items: list[dict] = []
    svc = _clean(project.get("service_slug"))
    loc = _clean(project.get("location_slug"))
    if svc:
        items.append({"href": f"/{svc.strip('/')}/", "title": _clean(project.get("service_name")) or "The service"})
    if loc:
        items.append({"href": f"/{loc.strip('/')}/", "title": _clean(project.get("location_name")) or "The area"})
    return items


def _meta_description(project: dict, narrated: Optional[dict]) -> str:
    """A meta description from the outcome (the result is the hook), trimmed."""
    text = _clean((narrated or {}).get("outcome")) or _clean(project.get("outcome")) or _clean(project.get("challenge"))
    text = " ".join(text.split())
    if len(text) <= 160:
        return text
    return text[:160].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def _body(project: dict, narrated: Optional[dict]) -> str:
    """The case-study narrative as Markdown: Challenge / What we did / Result.

    Uses the narrated prose where the LLM produced it, else the operator's raw
    supplied text verbatim. A section the operator left blank is omitted.
    """
    narrated = narrated or {}
    parts: list[str] = []
    for field in _PROSE_FIELDS:
        text = _clean(narrated.get(field)) or _clean(project.get(field))
        if text:
            parts.append(f"## {_PROSE_HEADINGS[field]}\n\n{text}")
    return "\n\n".join(parts)


def build_project_content(project: dict, narrated: Optional[dict] = None) -> dict:
    """The `content` dict a website_pages row stores for a project (mirrors the
    core-pages shape: title / description / body / frontmatter.sections).

    Pure — the structured facts pass through untouched and the prose is whatever
    was supplied or narrated. The template reads `sections.{stats,photos,
    testimonial,geo,links}` and renders the body via `<Content />`.
    """
    project = project or {}
    headline = _clean(project.get("headline")) or _clean(project.get("title")) or "Project"

    sections: dict[str, Any] = {}
    stats = _stat_list(project)
    if stats:
        sections["stats"] = stats
    photos = _photo_list(project)
    if photos:
        sections["photos"] = photos
    geo = _clean(project.get("location"))
    if geo:
        sections["geo"] = geo
    quote = _clean(project.get("testimonial_quote"))
    if quote:
        sections["testimonial"] = {"quote": quote, "author": _clean(project.get("testimonial_author"))}
    links = _links(project)
    if links:
        sections["links"] = links

    frontmatter: dict[str, Any] = {"sections": sections}
    # The hero image is a real supplied photo, never a generated illustration:
    # an explicit hero_url wins, else the first pasted photo.
    hero = _clean(project.get("hero_url")) or (photos[0]["url"] if photos else "")
    if hero:
        frontmatter["heroImage"] = hero
        frontmatter["heroImageAlt"] = (photos[0]["alt"] if photos else "") or headline

    return {
        "title": headline,
        "description": _meta_description(project, narrated),
        "body": _body(project, narrated),
        "frontmatter": frontmatter,
    }


# --------------------------------------------------------------------------
# Narration — one invent-nothing LLM call, best-effort
# --------------------------------------------------------------------------

_NARRATE_SYSTEM = (
    "You polish a real completed job into a case-study narrative. You are given "
    "the operator's own notes for three sections — the challenge, the work "
    "performed, and the outcome — and you return the same three, rewritten as "
    "clear, confident prose a prospective customer would read.\n\n"
    "HARD RULE — invent NOTHING. A case study's only value is that it is true. "
    "Use only facts present in the notes: never add a number, a date, a place, a "
    "material, a name, or a result that is not already there. If a section's "
    "notes are thin, keep your rewrite thin — do not pad it with invented "
    "detail. Do not add a testimonial or a statistic. Keep any specific figure "
    "exactly as given. Match the client's brand voice where one is provided."
)

_NARRATE_SCHEMA = {
    "type": "object",
    "properties": {
        "challenge": {"type": "string", "description": "The situation and what made it hard, as prose."},
        "work": {"type": "string", "description": "Exactly what was done, as prose (a short ordered list is fine)."},
        "outcome": {"type": "string", "description": "The measurable result, as prose."},
    },
    "required": ["challenge", "work", "outcome"],
    "additionalProperties": False,
}


def _narrate_user(project: dict, brand_text: str) -> str:
    lines = [f"JOB: {_clean(project.get('headline')) or 'a completed job'}"]
    if _clean(project.get("location")):
        lines.append(f"LOCATION: {_clean(project.get('location'))}")
    stats = _stat_list(project)
    if stats:
        lines.append("JOB FACTS: " + "; ".join(f"{s['label']}: {s['value']}" for s in stats))
    for field in _PROSE_FIELDS:
        lines.append(f"\n{_PROSE_HEADINGS[field].upper()} — operator notes:\n{_clean(project.get(field)) or '(none given)'}")
    prompt = "\n".join(lines)
    if (brand_text or "").strip():
        prompt += "\n\nBRAND VOICE (match it):\n" + brand_text.strip()
    prompt += (
        "\n\nRewrite the three sections as prose, using only the facts above. "
        "If a section's notes say '(none given)', return an empty string for it."
    )
    return prompt


async def narrate_project(project: dict, client: Optional[dict]) -> Optional[dict]:
    """Turn the operator's challenge/work/outcome notes into prose. Best-effort:
    returns the narrated `{challenge, work, outcome}` or None on any failure, so
    the caller falls back to the raw supplied text.

    Skips the call entirely when there is no prose to narrate (a stats-and-photos
    project) so a bare project costs nothing.
    """
    project = project or {}
    if not any(_clean(project.get(f)) for f in _PROSE_FIELDS):
        return None
    try:
        from services.voice_card_service import source_texts

        brand_text, _icp = source_texts(client or {})
        out = await report_llm.run_forced_tool(
            provider="anthropic",
            model=settings.website_core_pages_model,
            system=_NARRATE_SYSTEM,
            user=_narrate_user(project, brand_text),
            tool_name="write_case_study",
            tool_description="Return the three narrated case-study sections.",
            input_schema=_NARRATE_SCHEMA,
            max_tokens=settings.website_core_pages_max_tokens,
            log_tag="website_project",
        )
    except Exception as exc:  # noqa: BLE001 — narration is an enhancement, never a gate
        logger.warning("website_projects.narrate_failed", extra={"error": str(exc)})
        return None
    if not isinstance(out, dict):
        return None
    return {f: _clean(out.get(f)) for f in _PROSE_FIELDS}
