"""Website Builder — writing the home, about and contact pages.

These are the pages every site has and no keyword targets, so they do not go
through the SERP-analysis + 8-engine scoring machinery the service and location
writers use. There is nothing to out-rank on `/about-us/`; the job is brand
framing built from facts the suite already holds, not competitive optimisation.

So this writer is deliberately small — one Anthropic call per page, no SERP, no
scoring loop — and it lives in platform-api rather than nlp-api: the only thing
nlp would have added is its brand-voice/ICP prose builders, and the suite already
renders that same prose here (`voice_card_service.source_texts`). A cross-service
round-trip to reuse a string is not worth an nlp redeploy.

What each page needs is shaped by what the template renders deterministically,
which differs per page and is easy to get wrong:

* **home** renders its hero and section headings from a `sections` frontmatter
  map and composes the body from components — so it needs `sections` + title +
  description, and NO markdown body.
* **about** renders a markdown body via `<Content />` — so it needs a real
  narrative.
* **contact** renders NAP, hours, form and map from business facts; only the
  title and intro line are generated — so it needs title + description and no
  body.
* **privacy** is fully deterministic in the template (a legal template merged
  with business facts). It is handled by the caller, not here — there is nothing
  for an LLM to write.

**The writer never states a business fact.** Phone, address and hours are
rendered by the template from `site.config`, never by this prompt; the forced
tool schema captures only framing (headlines, a narrative, a CTA label), so a
hallucinated phone number is impossible by construction rather than by
instruction. The facts it IS given (services, city, differentiators) are there
so the copy is specific, and are passed through, not invented.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from config import settings
from services import report_llm

logger = logging.getLogger(__name__)


class CorePageError(Exception):
    """Stable error code, not prose."""


# The kinds this writer produces. `privacy` is intentionally absent — the
# template renders it deterministically, so it never reaches here.
GENERATED_KINDS = frozenset({"home", "about", "contact"})


# --------------------------------------------------------------------------
# Facts assembly — what the prompt is allowed to know
# --------------------------------------------------------------------------


def business_facts(client: dict, website: dict, pages: list[dict]) -> dict:
    """The real facts the copy may be specific about.

    Sourced from the site's own config first (a human entered it and it wins,
    §4.5), then the client's GBP, then the client row. Services and cities come
    from the site's *own planned pages* rather than a guess — a home page that
    lists services the site does not have is worse than one that lists none.
    """
    config = website.get("config") or {}
    business = config.get("business") or {}
    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else {}

    name = (
        business.get("name")
        or website.get("name")
        or gbp.get("business_name")
        or client.get("name")
        or ""
    )
    city = business.get("city") or gbp.get("city") or client.get("business_location") or ""

    services = _titles_of(pages, {"service", "sub_service", "brand_service"})
    cities = _titles_of(pages, {"location", "neighborhood", "local_landing", "hyper_local"})

    return {
        "business_name": name.strip(),
        "site_type": website.get("site_type") or "informational",
        "city": city.strip(),
        "category": gbp.get("gbp_category") or "",
        "services": services,
        "cities": cities,
        "differentiators": _as_str_list(client.get("differentiators")),
        "tagline": (config.get("tagline") or "").strip(),
    }


def _titles_of(pages: list[dict], page_types: set[str]) -> list[str]:
    """Distinct, order-preserving page titles for the given types, capped.

    Capped because these are prompt seasoning, not an exhaustive sitemap — a
    150-city matrix would bury the instruction under a list the model cannot use.
    """
    seen: dict[str, None] = {}
    for page in pages:
        if (page.get("page_type") or "") in page_types:
            title = (page.get("title") or "").strip()
            if title and title not in seen:
                seen[title] = None
    return list(seen)[:12]


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _facts_block(facts: dict) -> str:
    """The facts, rendered for the prompt. Only non-empty lines, so an
    unconfigured site does not hand the model a page full of blanks to fill."""
    lines: list[str] = []
    if facts.get("business_name"):
        lines.append(f"Business name: {facts['business_name']}")
    if facts.get("category"):
        lines.append(f"What they do: {facts['category']}")
    if facts.get("city"):
        lines.append(f"Primary city: {facts['city']}")
    if facts.get("services"):
        lines.append(f"Services offered: {', '.join(facts['services'])}")
    if facts.get("cities"):
        lines.append(f"Areas served: {', '.join(facts['cities'])}")
    if facts.get("differentiators"):
        lines.append("What sets them apart: " + "; ".join(facts["differentiators"]))
    if facts.get("tagline"):
        lines.append(f"Existing tagline: {facts['tagline']}")
    return "\n".join(lines) or "(no business facts on file)"


def _context_block(brand_text: str, icp_text: str) -> str:
    parts: list[str] = []
    if (brand_text or "").strip():
        parts.append(brand_text.strip())
    if (icp_text or "").strip():
        parts.append("IDEAL CUSTOMER (write to this reader):\n" + icp_text.strip())
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# Prompts — behaviour here; the exact voice is owner-tunable copy
# --------------------------------------------------------------------------

# The one rule that outranks everything and is enforced by the schema, not just
# stated: no invented facts. Repeated in each system prompt because it is the
# thing a persuasive-copy instruction most tempts a model to break.
_NO_FACTS = (
    "HARD RULE — never state a specific business fact you were not given: no "
    "phone numbers, street addresses, prices, years-in-business, license "
    "numbers, star ratings or review counts. Those are rendered elsewhere from "
    "verified data. Write only framing and positioning. If a detail would make "
    "the copy stronger but you were not given it, write around it."
)

_HOME_SYSTEM = (
    "You write the home page of a small business's website. You are given the "
    "business's real services, city and brand voice, and you return short, "
    "confident headline-and-intro copy for the page's sections — never the body "
    "text itself, which is built from components.\n\n"
    "Lead with what the business does for the customer, in the customer's words. "
    "Match the brand voice exactly where one is given. Keep every field tight: a "
    "hero headline is a line, not a paragraph.\n\n" + _NO_FACTS
)

_ABOUT_SYSTEM = (
    "You write the About page of a small business's website as flowing Markdown "
    "prose. Tell the story of who the business is, who it serves and why it can "
    "be trusted — grounded in the real services and differentiators given, in "
    "the brand's own voice. Use a few short sections with `##` headings. Warm and "
    "credible, never boilerplate 'we are committed to excellence'.\n\n" + _NO_FACTS
)

_CONTACT_SYSTEM = (
    "You write only the title and one-to-two sentence intro line for a small "
    "business's Contact page. Everything else on the page — phone, address, "
    "hours, form and map — is rendered from verified business data, so you write "
    "just the welcoming lead-in that sits above it, in the brand's voice.\n\n"
    + _NO_FACTS
)


def _home_user(facts: dict, brand_text: str, icp_text: str) -> str:
    ctx = _context_block(brand_text, icp_text)
    return (
        f"BUSINESS FACTS:\n{_facts_block(facts)}\n\n"
        + (ctx + "\n\n" if ctx else "")
        + "Write the home page section copy. Return the SEO title and meta "
        "description, and the section fields — a hero eyebrow, headline and "
        "lede, a call-to-action label, and headings for the services, areas and "
        "latest-content sections. Leave a field empty only if it genuinely does "
        "not apply to this business."
    )


def _about_user(facts: dict, brand_text: str, icp_text: str) -> str:
    ctx = _context_block(brand_text, icp_text)
    return (
        f"BUSINESS FACTS:\n{_facts_block(facts)}\n\n"
        + (ctx + "\n\n" if ctx else "")
        + "Write the About page. Return an SEO title, a meta description, and the "
        "page body as Markdown with a few `##` sections. Around 300–500 words."
    )


def _contact_user(facts: dict, brand_text: str, icp_text: str) -> str:
    ctx = _context_block(brand_text, icp_text)
    return (
        f"BUSINESS FACTS:\n{_facts_block(facts)}\n\n"
        + (ctx + "\n\n" if ctx else "")
        + "Write the Contact page title and a one-to-two sentence intro line that "
        "invites the reader to get in touch. Nothing else — the contact details "
        "render below your line."
    )


# --------------------------------------------------------------------------
# Tool schemas
# --------------------------------------------------------------------------

# The section keys the template's home page reads (index.astro). Kept here as the
# contract: a key the template does not read is dead copy, and a key it reads that
# we never emit falls back to a default, so this list is exactly the overlap.
HOME_SECTION_KEYS = (
    "heroEyebrow",
    "heroTitle",
    "heroLede",
    "ctaLabel",
    "servicesTitle",
    "locationsTitle",
    "latestTitle",
)

_HOME_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "SEO <title>, ≤60 chars."},
        "description": {"type": "string", "description": "Meta description, ≤160 chars."},
        "sections": {
            "type": "object",
            "properties": {k: {"type": "string"} for k in HOME_SECTION_KEYS},
            "additionalProperties": False,
        },
    },
    "required": ["title", "description", "sections"],
    "additionalProperties": False,
}

_ABOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "SEO <title>, ≤60 chars."},
        "description": {"type": "string", "description": "Meta description, ≤160 chars."},
        "body": {"type": "string", "description": "The page body as Markdown."},
    },
    "required": ["title", "description", "body"],
    "additionalProperties": False,
}

_CONTACT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "SEO <title>, ≤60 chars."},
        "description": {"type": "string", "description": "The intro line, one to two sentences."},
    },
    "required": ["title", "description"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------
# Per-kind spec
# --------------------------------------------------------------------------


class _Spec:
    def __init__(self, system: str, build_user: Callable[[dict, str, str], str],
                 schema: dict, to_content: Callable[[dict], dict]):
        self.system = system
        self.build_user = build_user
        self.schema = schema
        self.to_content = to_content


def _home_content(out: dict) -> dict:
    sections = {
        k: v.strip()
        for k, v in (out.get("sections") or {}).items()
        if k in HOME_SECTION_KEYS and isinstance(v, str) and v.strip()
    }
    if not sections:
        # The home page's whole reason to be generated is its section copy; an
        # empty map means the call produced nothing usable, and shipping it would
        # leave the page on template defaults while reporting success.
        raise CorePageError("home_sections_empty")
    return {
        "title": (out.get("title") or "").strip(),
        "description": (out.get("description") or "").strip(),
        "body": "",
        # The template reads `sections` from the entry's frontmatter.
        "frontmatter": {"sections": sections},
    }


def _about_content(out: dict) -> dict:
    body = (out.get("body") or "").strip()
    if not body:
        raise CorePageError("about_body_empty")
    return {
        "title": (out.get("title") or "").strip(),
        "description": (out.get("description") or "").strip(),
        "body": body,
    }


def _contact_content(out: dict) -> dict:
    return {
        "title": (out.get("title") or "").strip() or "Contact",
        "description": (out.get("description") or "").strip(),
        "body": "",
    }


_SPECS: dict[str, _Spec] = {
    "home": _Spec(_HOME_SYSTEM, _home_user, _HOME_SCHEMA, _home_content),
    "about": _Spec(_ABOUT_SYSTEM, _about_user, _ABOUT_SCHEMA, _about_content),
    "contact": _Spec(_CONTACT_SYSTEM, _contact_user, _CONTACT_SCHEMA, _contact_content),
}


# --------------------------------------------------------------------------
# The generate
# --------------------------------------------------------------------------


async def generate_core_page(
    *,
    page_kind: str,
    client: dict,
    website: dict,
    pages: Optional[list[dict]] = None,
) -> dict:
    """Write one core page. Returns the `content` dict a website_pages row stores.

    `content` carries `title`, `description`, `body` (empty for home/contact) and,
    for home, `frontmatter.sections` — the exact shape `source_from_content` /
    `build_files` read at publish, so nothing downstream is core-page-specific.
    """
    spec = _SPECS.get(page_kind)
    if spec is None:
        raise CorePageError(f"core_page_kind_not_generated:{page_kind}")

    from services.voice_card_service import source_texts

    brand_text, icp_text = source_texts(client or {})
    facts = business_facts(client, website, pages or [])

    out = await report_llm.run_forced_tool(
        provider="anthropic",
        model=settings.website_core_pages_model,
        system=spec.system,
        user=spec.build_user(facts, brand_text, icp_text),
        tool_name="write_page",
        tool_description=f"Return the {page_kind} page copy.",
        input_schema=spec.schema,
        max_tokens=settings.website_core_pages_max_tokens,
        log_tag="website_core_page",
    )
    return spec.to_content(out or {})
