"""WheelHouse IT location/service page — content generation.

Fills the 33 ACF fields for one ``{state, city, service}`` leaf page. Supplied
values are kept verbatim; only the missing LLM-authored fields are generated (one
forced-tool Claude call via the shared `report_llm` transport, with provider
fallback). The 8 canonical service-link fields default and are never generated.

Pure prompt assembly + title composition are unit-testable; the single LLM call
is the only impure part and is best-effort at the field level (a field the model
omits simply validates as empty — generation never hard-fails a page).
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings
from services import report_llm
from services.wheelhouse_fields import (
    BRAND_FACTS,
    FIELD_BY_NAME,
    GENERATED_FIELD_NAMES,
    GLOBAL_VOICE,
    LOCATION_HEADLINE_NAMES,
    generation_schema,
    merge_supplied,
    validate_fields,
)

logger = logging.getLogger(__name__)

# US state name → USPS abbreviation, for composing the leaf title ("… , FL").
_STATE_ABBREV = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}


def state_abbrev(state: str) -> Optional[str]:
    """USPS abbreviation for a US state name, or the input upper-cased if it is
    already a 2-letter code, else None."""
    s = (state or "").strip()
    if len(s) == 2 and s.isalpha():
        return s.upper()
    return _STATE_ABBREV.get(s.lower())


# The city page's fixed offering — WheelHouse IS an IT support company, so there
# is one service and the city page IS the local SEO page.
CITY_SERVICE_LABEL = "IT support company"


def compose_title(state: str, city: str, service: str) -> str:
    """The service-page WP post title, e.g. ``Managed IT in Miami, FL`` (the theme
    renders it as the page's H1 slot; the ACF hero_headline is the on-page H1)."""
    city = (city or "").strip()
    service = (service or "").strip()
    abbrev = state_abbrev(state)
    where = f"{city}, {abbrev}" if (city and abbrev) else city
    return f"{service} in {where}".strip() if where else service


def compose_city_title(city: str) -> str:
    """The city-page WP post title, e.g. ``Miami IT Support Company``."""
    city = (city or "").strip()
    return f"{city} IT Support Company" if city else "IT Support Company"


def title_for(page_type: str, state: str, city: str, service: str) -> str:
    return compose_city_title(city) if page_type == "city" else compose_title(state, city, service)


def _field_guide_lines(exclude: set) -> str:
    lines = []
    for i, name in enumerate(GENERATED_FIELD_NAMES, 1):
        if name in exclude:
            continue
        spec = FIELD_BY_NAME[name]
        loc = " (weave in the city)" if name in LOCATION_HEADLINE_NAMES else ""
        g = f" — {spec['guidance']}" if spec.get("guidance") else ""
        fmt = "HTML <p>…</p>" if spec["type"] == "wysiwyg" else spec["type"]
        lines.append(
            f"- {name}: {fmt}, {spec['min_words']}–{spec['max_words']} words, "
            f"focus {spec['focus']}{loc}{g}"
        )
    return "\n".join(lines)


_SYSTEM = (
    "You are an expert local-SEO and conversion copywriter for WheelHouse IT, a "
    "managed IT services provider (MSP). You write the on-page copy for a specific "
    "city + service landing page, field by field.\n\n"
    f"VOICE: {GLOBAL_VOICE}\n\n"
    f"BRAND FACTS (keep consistent, never contradict): {BRAND_FACTS}.\n\n"
    "RULES:\n"
    "- Write each field within its word range and to its stated focus.\n"
    "- Weave the CITY into the location headlines and reflect the SERVICE, so each "
    "city×service page reads distinctly (never the same body under a different H1).\n"
    "- wysiwyg fields must be valid HTML with <p>…</p> paragraphs; text/textarea "
    "fields are plain (no HTML).\n"
    "- Do not invent statistics, certifications, or claims beyond the brand facts.\n"
    "- Return every requested field via the emit_page_fields tool."
)


def build_user_prompt(state: str, city: str, service: str, exclude: set) -> str:
    return (
        f"Generate the landing-page copy for this page:\n"
        f"- State: {state}\n- City: {city}\n- Service: {service}\n\n"
        f"Fields to write:\n{_field_guide_lines(exclude)}"
    )


async def generate_fields(
    *, state: str, city: str, service: str, supplied: Optional[dict] = None,
    page_type: str = "service",
) -> dict:
    """Generate the leaf page's ACF fields. Returns
    ``{acf, field_sources, warnings, title, generation_failed}``.

    For ``page_type='city'`` the offering is fixed to "IT support company" (the
    city page IS the local SEO page) and the title is "[City] IT Support Company".
    Supplied fields are kept verbatim and excluded from the LLM call; the rest are
    generated in one forced-tool call. Best-effort: any missing field validates as
    empty rather than raising."""
    if page_type == "city":
        service = CITY_SERVICE_LABEL  # fixed offering woven into the city page
    supplied = {k: v for k, v in (supplied or {}).items()
                if isinstance(v, str) and v.strip()}
    exclude = set(supplied.keys())
    to_generate = [n for n in GENERATED_FIELD_NAMES if n not in exclude]

    generated: dict = {}
    if to_generate:
        try:
            generated = await report_llm.run_forced_tool(
                provider=settings.wheelhouse_provider,
                model=settings.wheelhouse_model,
                system=_SYSTEM,
                user=build_user_prompt(state, city, service, exclude),
                tool_name="emit_page_fields",
                tool_description="Emit the WheelHouse location/service page ACF field values.",
                input_schema=generation_schema(exclude=exclude),
                max_tokens=settings.wheelhouse_max_tokens,
                log_tag="wheelhouse_generate",
            )
        except Exception as exc:  # noqa: BLE001 — classify: retry transient, degrade terminal
            # A transient exhaustion (429/5xx/connection after all providers +
            # retries) propagates so a mass job can be re-queued when the outage
            # clears. A terminal error (bad key/request) degrades to an empty draft
            # with a surfaced flag rather than failing forever.
            if report_llm.is_transient_llm_error(exc):
                raise
            logger.error("wheelhouse_generate_llm_failed city=%s service=%s error=%s",
                         city, service, str(exc))
            generated = {}
    if not isinstance(generated, dict):
        generated = {}

    produced = [n for n in to_generate if isinstance(generated.get(n), str) and generated[n].strip()]
    acf, field_sources = merge_supplied(generated, supplied)
    return {
        "acf": acf,
        "field_sources": field_sources,
        "warnings": validate_fields(acf),
        "title": title_for(page_type, state, city, service),
        # True when we attempted generation but nothing usable came back — the UI
        # shows an error instead of a silently-blank form.
        "generation_failed": bool(to_generate) and not produced,
    }


async def draft_field(
    *, state: str, city: str, service: str, field_name: str,
    page_type: str = "service",
) -> str:
    """Draft a single ACF field (the one-off form's per-field 'Draft with AI').
    Returns the field's value (HTML for wysiwyg). Empty string on failure."""
    spec = FIELD_BY_NAME.get(field_name)
    if not spec or spec.get("is_link"):
        return ""
    if page_type == "city":
        service = CITY_SERVICE_LABEL
    try:
        out = await report_llm.run_forced_tool(
            provider=settings.wheelhouse_provider,
            model=settings.wheelhouse_model,
            system=_SYSTEM,
            user=(
                f"State: {state}\nCity: {city}\nService: {service}\n\n"
                f"Write ONLY this field:\n{_field_guide_lines(set(GENERATED_FIELD_NAMES) - {field_name})}"
            ),
            tool_name="emit_page_fields",
            tool_description="Emit the single requested ACF field value.",
            input_schema=generation_schema(exclude=set(GENERATED_FIELD_NAMES) - {field_name}),
            max_tokens=settings.wheelhouse_max_tokens,
            log_tag="wheelhouse_draft_field",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("wheelhouse_draft_field_failed field=%s error=%s", field_name, str(exc))
        return ""
    value = out.get(field_name) if isinstance(out, dict) else None
    if not isinstance(value, str):
        return ""
    from services.wheelhouse_fields import coerce_wysiwyg
    return coerce_wysiwyg(value) if spec["type"] == "wysiwyg" else value.strip()
