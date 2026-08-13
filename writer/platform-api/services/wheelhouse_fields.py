"""WheelHouse IT location/service page — the 33 ACF field schema.

Single source of truth for the field group ``group_ftl_it_support`` (assigned to
WordPress Pages, Show-in-REST on). Pure + deterministic so it is unit-testable
and drives three consumers off one definition: the generator (what to write per
field), the validator (warn-don't-fail length guardrails), and the frontend
one-off form (fields in ACF group order, grouped by section).

Data comes verbatim from the ACF export + the companion field-generation spec:
each field's meta key, type (text | textarea | wysiwyg), section, focus, the
warn thresholds (min/max words — measured on HTML-stripped text for wysiwyg),
and short authoring guidance. The 8 ``otherservices_link_*`` fields are a fixed
canonical nav list, not LLM-generated.
"""

from __future__ import annotations

import re
from typing import Optional

# Load-bearing brand facts every page must keep consistent (unless a supplied
# value overrides). Threaded into the generator prompt.
BRAND_FACTS = (
    "calls answered in ~52 seconds; resolved in ~29.6 min average; 95%+ customer "
    "satisfaction; SOC 2 certified; CrowdStrike EDR + Huntress; no long-term "
    "contract; pod-based support; internal US-based NOC"
)

GLOBAL_VOICE = (
    "Direct, second-person ('you / your team'), problem-aware, proof-led. The "
    "reader already has an IT provider and is unhappy with it. Avoid hype "
    "adjectives; lead with specifics."
)

# The canonical service nav list (otherservices_link_01..08), in order. These are
# defaults, not generated — a one-off page may override them.
CANONICAL_SERVICE_LINKS = [
    "IT Consulting", "Managed IT", "Co-Managed IT", "Cybersecurity",
    "Office 365 Migration", "IT Outsourcing", "Microsoft Services", "Cloud Services",
]

# Section labels (the ACF tab structure), used to group the one-off form.
SECTION_HERO = "Hero"
SECTION_VALUEBAND = "Positioning Band"
SECTION_DIFF = "Differentiators"
SECTION_INDUSTRY = "Industries"
SECTION_SECURITY = "Security"
SECTION_SWITCH = "Why Switch"
SECTION_OTHER = "Other Services"


def _link_field(idx: int, default: str) -> dict:
    return {
        "name": f"otherservices_link_{idx:02d}",
        "type": "text",
        "section": SECTION_OTHER,
        "focus": "SEO (internal linking)",
        "min_words": 1,
        "max_words": 3,
        "guidance": "Canonical service name.",
        "is_link": True,
        "default": default,
    }


# The 33 content fields, in ACF group order. `is_link` marks the fixed nav list
# (defaulted, not generated). Everything else is LLM-generated when not supplied.
FIELD_SPEC: list[dict] = [
    {"name": "hero_headline", "type": "text", "section": SECTION_HERO,
     "focus": "SEO→Conversion", "min_words": 6, "max_words": 9,
     "guidance": "Primary service phrase + city; the only H1 on the page.", "location_headline": True},
    {"name": "hero_body", "type": "wysiwyg", "section": SECTION_HERO,
     "focus": "Conversion", "min_words": 45, "max_words": 75,
     "guidance": "Establish the 'you already have an MSP and it's failing you' premise; end on a reframe."},
    {"name": "valueband_eyebrow", "type": "text", "section": SECTION_VALUEBAND,
     "focus": "SEO/Value-add", "min_words": 3, "max_words": 5,
     "guidance": "All-caps local signal (e.g. HEADQUARTERED IN <city> / SERVING <city>)."},
    {"name": "valueband_headline", "type": "text", "section": SECTION_VALUEBAND,
     "focus": "Conversion→Value-add", "min_words": 8, "max_words": 16,
     "guidance": "Three benefit fragments separated by periods."},
    {"name": "valueband_body", "type": "wysiwyg", "section": SECTION_VALUEBAND,
     "focus": "Value-add→SEO", "min_words": 120, "max_words": 200,
     "guidance": "Densest local+industry keyword block: the city, its metro/region, county, "
                 "industries served, co-managed/MSP replacement."},
    {"name": "diff_eyebrow", "type": "text", "section": SECTION_DIFF,
     "focus": "Value-add", "min_words": 2, "max_words": 5, "guidance": "All-caps eyebrow."},
    {"name": "diff_headline", "type": "text", "section": SECTION_DIFF,
     "focus": "SEO→Conversion", "min_words": 8, "max_words": 12, "guidance": ""},
    {"name": "diff_intro", "type": "wysiwyg", "section": SECTION_DIFF,
     "focus": "Value-add", "min_words": 25, "max_words": 45, "guidance": ""},
    {"name": "diff_item_1_title", "type": "text", "section": SECTION_DIFF,
     "focus": "Value-add", "min_words": 3, "max_words": 6, "guidance": "Capability name."},
    {"name": "diff_item_1_body", "type": "wysiwyg", "section": SECTION_DIFF,
     "focus": "Value-add", "min_words": 25, "max_words": 50, "guidance": "How it works + benefit."},
    {"name": "diff_item_2_title", "type": "text", "section": SECTION_DIFF,
     "focus": "Value-add", "min_words": 3, "max_words": 6, "guidance": "Capability name."},
    {"name": "diff_item_2_body", "type": "wysiwyg", "section": SECTION_DIFF,
     "focus": "Value-add", "min_words": 25, "max_words": 50, "guidance": "How it works + benefit."},
    {"name": "diff_item_3_title", "type": "text", "section": SECTION_DIFF,
     "focus": "Value-add", "min_words": 3, "max_words": 6, "guidance": "Capability name."},
    {"name": "diff_item_3_body", "type": "wysiwyg", "section": SECTION_DIFF,
     "focus": "Value-add", "min_words": 25, "max_words": 50, "guidance": "How it works + benefit."},
    {"name": "diff_item_4_title", "type": "text", "section": SECTION_DIFF,
     "focus": "Value-add", "min_words": 3, "max_words": 6, "guidance": "Capability name."},
    {"name": "diff_item_4_body", "type": "wysiwyg", "section": SECTION_DIFF,
     "focus": "Value-add", "min_words": 25, "max_words": 50, "guidance": "How it works + benefit."},
    {"name": "industry_headline", "type": "text", "section": SECTION_INDUSTRY,
     "focus": "SEO", "min_words": 7, "max_words": 12, "guidance": "", "location_headline": True},
    {"name": "security_eyebrow", "type": "text", "section": SECTION_SECURITY,
     "focus": "SEO/Value-add", "min_words": 2, "max_words": 4, "guidance": "All-caps eyebrow."},
    {"name": "security_headline", "type": "text", "section": SECTION_SECURITY,
     "focus": "Conversion→SEO", "min_words": 8, "max_words": 14, "guidance": ""},
    {"name": "security_body", "type": "wysiwyg", "section": SECTION_SECURITY,
     "focus": "Value-add→Conversion", "min_words": 50, "max_words": 90,
     "guidance": "Lead with a concrete interception/threat stat."},
    {"name": "switch_headline", "type": "text", "section": SECTION_SWITCH,
     "focus": "SEO→Conversion", "min_words": 7, "max_words": 12, "guidance": "", "location_headline": True},
    {"name": "switch_intro", "type": "wysiwyg", "section": SECTION_SWITCH,
     "focus": "Conversion", "min_words": 40, "max_words": 65, "guidance": ""},
    {"name": "otherservices_eyebrow", "type": "text", "section": SECTION_OTHER,
     "focus": "Value-add", "min_words": 1, "max_words": 3, "guidance": "All-caps eyebrow."},
    {"name": "otherservices_headline", "type": "text", "section": SECTION_OTHER,
     "focus": "SEO", "min_words": 5, "max_words": 9, "guidance": "", "location_headline": True},
    {"name": "otherservices_intro", "type": "textarea", "section": SECTION_OTHER,
     "focus": "Value-add", "min_words": 12, "max_words": 25, "guidance": ""},
    _link_field(1, CANONICAL_SERVICE_LINKS[0]),
    _link_field(2, CANONICAL_SERVICE_LINKS[1]),
    _link_field(3, CANONICAL_SERVICE_LINKS[2]),
    _link_field(4, CANONICAL_SERVICE_LINKS[3]),
    _link_field(5, CANONICAL_SERVICE_LINKS[4]),
    _link_field(6, CANONICAL_SERVICE_LINKS[5]),
    _link_field(7, CANONICAL_SERVICE_LINKS[6]),
    _link_field(8, CANONICAL_SERVICE_LINKS[7]),
]

FIELD_BY_NAME: dict[str, dict] = {f["name"]: f for f in FIELD_SPEC}
FIELD_NAMES: list[str] = [f["name"] for f in FIELD_SPEC]
# Fields the LLM authors (everything except the fixed canonical nav list).
GENERATED_FIELD_NAMES: list[str] = [f["name"] for f in FIELD_SPEC if not f.get("is_link")]
LINK_FIELD_NAMES: list[str] = [f["name"] for f in FIELD_SPEC if f.get("is_link")]
# Headlines that must weave in the city.
LOCATION_HEADLINE_NAMES: list[str] = [f["name"] for f in FIELD_SPEC if f.get("location_headline")]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(value: str) -> str:
    """Plain text from a (possibly) HTML string — tags removed, whitespace collapsed."""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", value or "")).strip()


def word_count(value: str, *, is_html: bool = False) -> int:
    text = strip_html(value) if is_html else (value or "").strip()
    return len(text.split()) if text else 0


def coerce_wysiwyg(value: str) -> str:
    """Ensure a wysiwyg value is HTML: if it carries no tag, wrap each blank-line-
    separated paragraph in <p>…</p> (the ACF wysiwyg field expects HTML)."""
    text = (value or "").strip()
    if not text:
        return ""
    if "<" in text and ">" in text:
        return text  # already HTML
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paras) if paras else f"<p>{text}</p>"


def default_link_fields() -> dict:
    """The 8 canonical service-link fields as {name: default}."""
    return {f["name"]: f["default"] for f in FIELD_SPEC if f.get("is_link")}


def validate_fields(acf: dict) -> list[dict]:
    """Length/focus validation → a list of non-fatal warnings (warn, don't fail).

    Each warning: {field, type, words, min_words, max_words, issue ('short'|'long'|
    'empty')}. wysiwyg word counts are measured on HTML-stripped text. Fields not
    in the schema are ignored; a missing/empty field for which the schema wants
    content warns as 'empty'."""
    warnings: list[dict] = []
    for spec in FIELD_SPEC:
        name = spec["name"]
        raw = acf.get(name)
        value = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
        is_html = spec["type"] == "wysiwyg"
        words = word_count(value, is_html=is_html)
        if words == 0:
            warnings.append({"field": name, "type": spec["type"], "words": 0,
                             "min_words": spec["min_words"], "max_words": spec["max_words"],
                             "issue": "empty"})
            continue
        if words < spec["min_words"]:
            warnings.append({"field": name, "type": spec["type"], "words": words,
                             "min_words": spec["min_words"], "max_words": spec["max_words"],
                             "issue": "short"})
        elif words > spec["max_words"]:
            warnings.append({"field": name, "type": spec["type"], "words": words,
                             "min_words": spec["min_words"], "max_words": spec["max_words"],
                             "issue": "long"})
    return warnings


def sections() -> list[dict]:
    """The field schema grouped by section, in order — for the one-off form.
    ``[{section, fields: [spec, …]}]``."""
    order: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for spec in FIELD_SPEC:
        sec = spec["section"]
        if sec not in grouped:
            grouped[sec] = []
            order.append(sec)
        grouped[sec].append(spec)
    return [{"section": s, "fields": grouped[s]} for s in order]


def generation_schema(exclude: Optional[set] = None) -> dict:
    """JSON Schema for the forced-tool generation call: one string property per
    LLM-authored field (the 8 canonical link fields are excluded — they default).
    All required so the model returns every field. `exclude` drops fields already
    supplied verbatim so the model doesn't waste tokens regenerating them."""
    exclude = exclude or set()
    props = {}
    for name in GENERATED_FIELD_NAMES:
        if name in exclude:
            continue
        spec = FIELD_BY_NAME[name]
        hint = f"{spec['type']} · {spec['min_words']}–{spec['max_words']} words · {spec['focus']}"
        if spec.get("guidance"):
            hint += f" · {spec['guidance']}"
        if spec["type"] == "wysiwyg":
            hint += " · return HTML with <p>…</p> paragraphs"
        props[name] = {"type": "string", "description": hint}
    return {
        "type": "object",
        "properties": props,
        "required": list(props.keys()),
    }


def merge_supplied(generated: dict, supplied: Optional[dict]) -> tuple[dict, dict]:
    """Assemble the final 33-field ACF object + a per-field source map.

    Precedence: a supplied value wins verbatim; else the generated value; else the
    canonical default (link fields). wysiwyg values are coerced to HTML. Returns
    (acf, field_sources) where source ∈ {'supplied','generated','default'}."""
    supplied = supplied or {}
    acf: dict = {}
    sources: dict = {}
    for spec in FIELD_SPEC:
        name = spec["name"]
        sup = supplied.get(name)
        if isinstance(sup, str) and sup.strip():
            value, src = sup.strip(), "supplied"
        elif isinstance(generated.get(name), str) and generated[name].strip():
            value, src = generated[name].strip(), "generated"
        elif spec.get("is_link"):
            value, src = spec["default"], "default"
        else:
            value, src = "", "generated"  # empty; validator will warn
        if spec["type"] == "wysiwyg" and value:
            value = coerce_wysiwyg(value)
        acf[name] = value
        sources[name] = src
    return acf, sources
