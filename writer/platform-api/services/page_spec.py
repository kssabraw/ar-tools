"""Local SEO **page spec** — length + structure as one kept, enforceable document.

Plan: ``docs/modules/local-seo-page-spec-plan-v1_0.md``. This is the pure core
(Phase 0): no LLM, no I/O. It turns the three sources that used to compete inside
the writer's head — the client's reference layout (``clients.page_structures``),
the SERP length target (``keyword_analyses``) and the nlp template's must-haves —
into ONE spec with a page-level word band and a per-section ``min_words`` /
``max_words`` band, validated before any tokens are spent, and it measures a
generated page against that spec section by section afterwards.

Shape (schema_version 1) — see the plan §3 for the full example::

    {
      "schema_version": 1, "client_id", "keyword", "location", "location_code", "page_type",
      "generated_at", "edited_at",
      "total": {"min", "target", "max", "basis": "serp"|"fallback"},
      "structure": {"max_sections", "max_h3_per_h2", "faq": {"min", "max"}},
      "sections": [{"key", "level", "required", "intent", "heading_pattern",
                    "min_words", "max_words", "blocks", "source", ...}],
      "provenance": {"reference", "serp", "template", "fallback_reason", "flags"},
    }

Every step is a small pure function so the allocation can be unit-tested and the
numbers in a stored spec can be traced to the input that produced them.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Optional

from bs4 import BeautifulSoup

SCHEMA_VERSION = 1
TEMPLATE_ID = "local_landing_v13"

# ── page band ───────────────────────────────────────────────────────────────
# The SERP target is avg + 20% (length_fit.OVERAGE_MULTIPLIER); full credit runs
# from the SERP average up to target + 10% — that IS the page band.
OVERAGE_MULTIPLIER = 1.20
BAND_UPPER = 1.10
# Hard save ceiling: a page still over total.max × this after trims is saved as
# `over_length`, never as clean (plan §5.5).
CEILING_MULTIPLIER = 1.15
# SERP sanity (plan §5.2).
SERP_MIN_COMPETITOR_PAGES = 3
SERP_TARGET_MIN = 900
SERP_TARGET_MAX = 2500
# Reference sanity (plan §5.2).
REFERENCE_MIN_WORDS = 300
REFERENCE_MIN_SECTIONS = 4
_STAGING_HOST_RE = re.compile(r"(^|[./-])(staging\d*|stage|dev|test|sandbox|localhost)([./-]|$)", re.I)

# ── the template's sections (the nlp <section id> vocabulary) ───────────────
# `weight` = default share of the page when the reference carries no matching
# section; `floor`/`ceiling` = absolute per-section clamps so fixed-size blocks
# (CTAs, intro) stay sane whatever the proportional allocation says. `services`
# is the absorber: it takes the residual so the sums close (plan §4 step 4).
TEMPLATE_SECTIONS: tuple[dict[str, Any], ...] = (
    {"key": "intro", "level": "H1", "intent": "hero", "required": True, "weight": 0.08,
     "floor": 60, "ceiling": 160,
     "heading_pattern": "Exact-match keyword + 1–2 service/credential entities",
     "blocks": [{"type": "paragraph", "count": 3}]},
    {"key": "usp", "level": "H2", "intent": "value_prop", "required": True, "weight": 0.10,
     "floor": 60, "ceiling": 220,
     "heading_pattern": "Full sentence: service + outcome + 1–2 entities (no city)",
     "blocks": [{"type": "paragraph", "count": 3}]},
    {"key": "offers", "level": "H2", "intent": "pricing", "required": False, "weight": 0.0,
     "floor": 0, "ceiling": 120,
     "heading_pattern": "Special offer (only when offer data exists)",
     "blocks": [{"type": "paragraph", "count": 1}]},
    {"key": "cta-primary", "level": "H2", "intent": "cta", "required": True, "weight": 0.04,
     "floor": 30, "ceiling": 80,
     "heading_pattern": "Service-anchored action heading (value/offer-led)",
     "blocks": [{"type": "cta", "count": 1}]},
    {"key": "features", "level": "H2", "intent": "value_prop", "required": True, "weight": 0.10,
     "floor": 60, "ceiling": 220,
     "heading_pattern": "Benefit-focused heading",
     "blocks": [{"type": "list", "count": 1, "items": 4}], "items": {"min": 4, "max": 6}},
    {"key": "services", "level": "H2", "intent": "service_detail", "required": True, "weight": 0.36,
     "floor": 200, "ceiling": None,
     "heading_pattern": "Multiple H2s built from competitor topics; H3 per sub-service",
     "blocks": [{"type": "paragraph", "count": 6}], "subsections": {"min": 3, "max": 6}},
    {"key": "testimonials", "level": "H2", "intent": "trust", "required": False, "weight": 0.0,
     "floor": 0, "ceiling": 200,
     "heading_pattern": "Social proof (verbatim reviews only)",
     "blocks": [{"type": "quote", "count": 3}]},
    {"key": "cta-secondary", "level": "H2", "intent": "cta", "required": True, "weight": 0.04,
     "floor": 30, "ceiling": 80,
     "heading_pattern": "Service-anchored action heading (proof/risk-reversal)",
     "blocks": [{"type": "cta", "count": 1}]},
    {"key": "getting-started", "level": "H2", "intent": "process", "required": True, "weight": 0.08,
     "floor": 60, "ceiling": 220,
     "heading_pattern": "Process-focused heading + 3–5 numbered steps",
     "blocks": [{"type": "list", "count": 1, "items": 4}]},
    {"key": "local", "level": "H2", "intent": "coverage", "required": True, "weight": 0.10,
     "floor": 100, "ceiling": 320,
     "heading_pattern": "City + service; neighborhoods, landmarks, streets, ZIPs, NAP",
     "blocks": [{"type": "paragraph", "count": 3}]},
    {"key": "faq", "level": "H2", "intent": "faq", "required": True, "weight": 0.10,
     "floor": 160, "ceiling": 560,
     "heading_pattern": "Frequently Asked Questions",
     "blocks": [{"type": "faq", "count": 1, "items": 5}], "items": {"min": 4, "max": 7},
     "words_per_item": {"min": 40, "max": 80}},
)
TEMPLATE_KEYS: tuple[str, ...] = tuple(s["key"] for s in TEMPLATE_SECTIONS)
ABSORBER_KEY = "services"

# Reference intent → template key. Intents that can legitimately appear twice
# (value_prop → usp then features; cta → primary then secondary) are listed in
# order; the Nth occurrence takes the Nth key, later ones become extras.
_INTENT_TO_KEYS: dict[str, tuple[str, ...]] = {
    "hero": ("intro",),
    "value_prop": ("usp", "features"),
    "service_detail": ("services",),
    "process": ("getting-started",),
    "trust": ("testimonials",),
    "objection": ("services",),
    "comparison": ("services",),
    "pricing": ("offers",),
    "coverage": ("local",),
    "faq": ("faq",),
    "cta": ("cta-primary", "cta-secondary"),
}

STRUCTURE_DEFAULTS = {"max_sections": 12, "max_h3_per_h2": 6, "faq": {"min": 4, "max": 7}}

# A reference extra (a section with no template slot) below this many reference
# words isn't worth its own section on the generated page — it's a nav stub or
# a NAP line the template's `local` section already covers.
EXTRA_MIN_REFERENCE_WORDS = 20
# The absorber must keep at least this share of the page maximum so the main
# service body never gets squeezed to a point by many small sections.
ABSORBER_MIN_SHARE_OF_MAX = 0.30
# A section band is never narrower than this ratio (max ≥ min × ratio) unless a
# hard ceiling forbids it — a point target is a guess, a band is a spec.
MIN_BAND_RATIO = 1.25
_TESTIMONIAL_RE = re.compile(r"review|testimonial|what (our )?(clients|customers) say", re.I)

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
# Sections platform/nlp inject deterministically AFTER writing (NAP + map +
# form; never authored, never scored) — excluded from measurement so the same
# page measures the same before and after injection.
INJECTED_SECTION_IDS = frozenset({"contact-find-us", "trust-proof"})
_CHROME_TAGS = ("script", "style", "noscript", "template", "iframe", "svg", "nav", "header", "footer", "aside", "form")


# ── small helpers ───────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40]


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def _words_of(item: dict[str, Any]) -> int:
    """A reference outline row's word count (exact `word_count`, else the legacy
    `approx_words`)."""
    return max(0, _int(item.get("word_count", item.get("approx_words", 0))))


def _now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


# ── 1. the page band ────────────────────────────────────────────────────────

def page_band(
    serp_analysis: Optional[dict[str, Any]],
    fallback_target: Optional[int],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """The page-level word band + its SERP provenance + sanity flags.

    ``basis="serp"`` when the analysis carries a measured target from enough
    competitor pages inside the plausible range; otherwise ``"fallback"`` (the
    market's standing target from platform-api) — there is NEVER no band.
    Returns ``(total, serp_provenance, flags)``."""
    sa = serp_analysis or {}
    target = _int(sa.get("serp_word_target"))
    avg = _int(sa.get("serp_avg_word_count")) or (int(round(target / OVERAGE_MULTIPLIER)) if target else 0)
    pages = len(sa.get("serp_urls") or []) if isinstance(sa.get("serp_urls"), list) else 0
    flags: list[str] = []
    basis = "serp"
    if target <= 0:
        basis = "fallback"
        flags.append("serp_target_missing")
    else:
        if pages and pages < SERP_MIN_COMPETITOR_PAGES:
            flags.append("serp_too_few_pages")
            basis = "fallback"
        if target < SERP_TARGET_MIN or target > SERP_TARGET_MAX:
            flags.append("serp_target_suspect")
            basis = "fallback"
    if basis == "fallback":
        target = max(1, _int(fallback_target) or SERP_TARGET_MIN)
        avg = int(round(target / OVERAGE_MULTIPLIER))
    total = {
        "min": avg,
        "target": target,
        "max": int(round(target * BAND_UPPER)),
        "basis": basis,
    }
    prov = {
        "keyword": sa.get("keyword"),
        "location": sa.get("location"),
        "avg_words": _int(sa.get("serp_avg_word_count")) or None,
        "target": _int(sa.get("serp_word_target")) or None,
        "competitor_pages": pages or None,
        "from_cache": bool(sa.get("from_cache")),
    }
    return total, prov, flags


# ── 2. reference validation ─────────────────────────────────────────────────

def reference_usable(entry: Optional[dict[str, Any]]) -> tuple[bool, Optional[str]]:
    """Whether a stored ``clients.page_structures`` entry may drive layout.
    Returns ``(usable, reason)`` — reason is the rejection code when not."""
    if not isinstance(entry, dict):
        return False, "no_reference"
    if entry.get("status") not in (None, "complete"):
        return False, f"status_{entry.get('status')}"
    analysis = entry.get("analysis")
    outline = (analysis or {}).get("outline") if isinstance(analysis, dict) else None
    if not isinstance(outline, list) or not outline:
        return False, "no_outline"
    url = entry.get("url") or ""
    host = re.sub(r"^https?://", "", url).split("/")[0]
    if host and _STAGING_HOST_RE.search(host):
        return False, "staging_host"
    total = sum(_words_of(it) for it in outline if isinstance(it, dict))
    if total < REFERENCE_MIN_WORDS:
        return False, "too_short"
    rows = [it for it in outline if isinstance(it, dict) and it.get("level") in ("H1", "H2")]
    if len(rows) < REFERENCE_MIN_SECTIONS:
        return False, "too_few_sections"
    return True, None


# ── 3. fold + map the reference outline ─────────────────────────────────────

def fold_outline(outline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group a reference outline into H1/H2 sections with their H3 children.

    Heading-only rows (zero words, no blocks) are folded: a zero-word H3 becomes
    one item of a ``list`` block on its parent (Wheelhouse's 14 industry
    headings → one 14-item list), and a zero-word H2 with no children at all is
    dropped. So the writer is never handed an empty heading to reproduce or pad.
    Each group: ``{level, heading, intent, intent_note, words, subsections,
    blocks, folded_headings}``."""
    groups: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    for row in outline or []:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level") or "H2").upper()
        words = _words_of(row)
        blocks = [copy.deepcopy(b) for b in (row.get("blocks") or []) if isinstance(b, dict)]
        if level in ("H1", "H2") or current is None:
            current = {
                "level": "H1" if level == "H1" else "H2",
                "heading": row.get("heading") or "",
                "intent": row.get("intent") or "other",
                "intent_note": row.get("intent_note") or "",
                "words": words,
                "subsections": 0,
                "blocks": blocks,
                "folded_headings": 0,
            }
            groups.append(current)
            continue
        # H3+ → child of the current group
        if words == 0 and not blocks:
            current["folded_headings"] += 1
            continue
        current["words"] += words
        current["subsections"] += 1
        current["blocks"].extend(blocks)
    out: list[dict[str, Any]] = []
    for g in groups:
        if g["folded_headings"]:
            g["blocks"].append({"type": "list", "count": 1, "items": g["folded_headings"], "words": 0, "folded": True})
        if g["level"] != "H1" and g["words"] == 0 and g["subsections"] == 0 and not g["folded_headings"]:
            continue  # pure heading with nothing under it (the H1 hero always survives)
        out.append(g)
    return out


def map_to_template(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign each folded reference group a template key by intent (first
    value_prop → usp, second → features; first cta → primary, second →
    secondary). A group whose intent has no template slot, or whose slot is
    already taken, becomes an optional extra with a slug key. Groups mapped to
    the same absorber key (`services`: service_detail/objection/comparison) are
    merged — their words add up and their count becomes the subsection count."""
    taken: dict[str, dict[str, Any]] = {}
    seen_intent: dict[str, int] = {}
    ordered: list[dict[str, Any]] = []
    for g in groups:
        intent = g.get("intent") or "other"
        # A prose "trust" section (credentials, why-switch) is value-prop copy,
        # not testimonials — only real review blocks take the testimonials slot.
        if intent == "trust":
            has_quotes = any((b.get("type") == "quote") for b in g.get("blocks") or [])
            if not (has_quotes or _TESTIMONIAL_RE.search(g.get("heading") or "")):
                intent = "value_prop"
        n = seen_intent.get(intent, 0)
        seen_intent[intent] = n + 1
        candidates = _INTENT_TO_KEYS.get(intent, ())
        key: Optional[str] = None
        if candidates:
            if candidates[0] == ABSORBER_KEY:
                key = ABSORBER_KEY
            elif n < len(candidates) and candidates[n] not in taken:
                key = candidates[n]
            elif intent in ("value_prop", "objection", "comparison"):
                key = ABSORBER_KEY  # overflow value-prop copy joins the body
        if key is None and int(g.get("words") or 0) < EXTRA_MIN_REFERENCE_WORDS:
            continue  # a nav stub / NAP line — not worth a section of its own
        if key == ABSORBER_KEY and ABSORBER_KEY in taken:
            tgt = taken[ABSORBER_KEY]
            tgt["words"] += g["words"]
            tgt["subsections"] += max(1, g.get("subsections") or 0)
            tgt["blocks"].extend(g.get("blocks") or [])
            continue
        if key is None:
            key = f"ref-{_slug(g.get('heading') or intent) or intent}"
            i = 2
            base = key
            while key in taken:
                key = f"{base}-{i}"
                i += 1
            sec = {**g, "key": key, "required": False, "source": "reference"}
        else:
            sec = {**g, "key": key, "required": _template(key)["required"], "source": "reference"}
            if key == ABSORBER_KEY:
                sec["subsections"] = max(1, g.get("subsections") or 0)
        taken[key] = sec
        ordered.append(sec)
    return ordered


def _template(key: str) -> dict[str, Any]:
    for s in TEMPLATE_SECTIONS:
        if s["key"] == key:
            return s
    raise KeyError(key)


def ensure_required(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert every required template section the reference lacks, and order
    the result in template order (the writer emits sections in that order);
    reference extras keep their relative order and go before the FAQ."""
    by_key = {s["key"]: s for s in sections}
    for t in TEMPLATE_SECTIONS:
        if t["required"] and t["key"] not in by_key:
            by_key[t["key"]] = {
                "key": t["key"], "level": t["level"], "heading": "", "intent": t["intent"],
                "intent_note": "", "words": 0, "subsections": 0,
                "blocks": copy.deepcopy(t["blocks"]), "required": True, "source": "template",
            }
    template_part = [by_key[k] for k in TEMPLATE_KEYS if k in by_key]
    extras = [s for s in sections if s["key"] not in TEMPLATE_KEYS]
    out: list[dict[str, Any]] = []
    for s in template_part:
        if s["key"] == "faq":
            out.extend(extras)
        out.append(s)
    if "faq" not in by_key:
        out.extend(extras)
    return out


# ── 4. band allocation ──────────────────────────────────────────────────────

def allocate_bands(
    sections: list[dict[str, Any]],
    total: dict[str, Any],
) -> list[dict[str, Any]]:
    """Give every section a ``min_words``/``max_words`` band.

    Share per section = its reference words ÷ reference total for reference-
    backed sections, the template weight for inserted ones (both normalised
    together so the two sources coexist); ``min = share × total.min``,
    ``max = share × total.max``, clamped by the template's per-key floor and
    ceiling. The absorber (`services`) then takes the residual so
    ``Σmin ≈ total.min`` and ``Σmax ≈ total.max``. Pure; never mutates input."""
    secs = [copy.deepcopy(s) for s in sections]
    ref_total = sum(int(s.get("words") or 0) for s in secs if s.get("source") == "reference")
    raw: list[float] = []
    for s in secs:
        t = _template(s["key"]) if s["key"] in TEMPLATE_KEYS else None
        if s.get("source") == "reference" and ref_total > 0 and int(s.get("words") or 0) > 0:
            raw.append(int(s.get("words") or 0) / ref_total)
        else:
            # Inserted from the template, or a reference section that carried no
            # prose (a heading-only CTA): the template weight, so it still gets a
            # real share instead of collapsing onto its floor.
            raw.append(float(t["weight"]) if t else 0.0)
    norm = sum(raw) or 1.0
    shares = [r / norm for r in raw]

    t_min, t_max = int(total["min"]), int(total["max"])
    for s, share in zip(secs, shares):
        t = _template(s["key"]) if s["key"] in TEMPLATE_KEYS else None
        floor = int(t["floor"]) if t else 0
        ceiling = t["ceiling"] if t else None
        lo = int(round(share * t_min))
        hi = int(round(share * t_max))
        hi = max(hi, int(round(lo * MIN_BAND_RATIO)))
        if t and t.get("items") and t.get("words_per_item"):
            wpi = t["words_per_item"]
            lo = max(lo, t["items"]["min"] * wpi["min"])
            hi = min(hi if hi else 10**9, t["items"]["max"] * wpi["max"])
        lo = max(lo, floor)
        hi = max(hi, int(round(lo * MIN_BAND_RATIO)))
        if ceiling is not None:
            hi = min(hi, int(ceiling))
            lo = min(lo, hi)
        if not s.get("required"):
            # An optional section may be omitted, so it never contributes to
            # the page minimum — only its maximum bounds what it may take.
            if s.get("source") == "reference" and int(s.get("words") or 0) == 0:
                items = sum(int(b.get("items") or 0) for b in s.get("blocks") or [])
                hi = max(40, items * 4)
            lo = 0
        s["min_words"], s["max_words"] = int(lo), int(hi)
        s["share"] = round(share, 4)

    absorber = next((s for s in secs if s["key"] == ABSORBER_KEY), None)
    if absorber is None:
        return secs
    a_floor = int(_template(ABSORBER_KEY)["floor"])
    others = [s for s in secs if s is not absorber]

    # Squeeze: the other sections may claim at most (1 − absorber share) of the
    # page, so the main body never collapses to a point. Scale their maxima
    # (and, if still needed, their minima — never below the floor) proportionally.
    room_max = int(round(t_max * (1 - ABSORBER_MIN_SHARE_OF_MAX)))
    others_max = sum(s["max_words"] for s in others)
    if others_max > room_max and others_max > 0:
        f = room_max / others_max
        for s in others:
            s["max_words"] = max(int(round(s["max_words"] * f)), s["min_words"])
    room_min = t_max - a_floor
    others_min = sum(s["min_words"] for s in others)
    if others_min > room_min and others_min > 0:
        f = room_min / others_min
        for s in others:
            t = _template(s["key"]) if s["key"] in TEMPLATE_KEYS else None
            floor = int(t["floor"]) if (t and s.get("required")) else 0
            s["min_words"] = max(floor, int(round(s["min_words"] * f)))
            s["max_words"] = max(s["max_words"], s["min_words"])

    # residual → absorber, so the sums close on the page band
    others_min = sum(s["min_words"] for s in others)
    others_max = sum(s["max_words"] for s in others)
    absorber["min_words"] = max(a_floor, t_min - others_min)
    absorber["max_words"] = max(
        int(round(absorber["min_words"] * MIN_BAND_RATIO)), t_max - others_max
    )
    return secs


# ── 5. validation ───────────────────────────────────────────────────────────

def validate_spec(spec: dict[str, Any]) -> list[str]:
    """Deterministic feasibility check (plan §5.1). Returns error codes; an
    empty list means the spec may be handed to the writer."""
    errors: list[str] = []
    total = spec.get("total") or {}
    t_min, t_max = _int(total.get("min")), _int(total.get("max"))
    if t_min <= 0 or t_max <= 0 or t_min > t_max:
        errors.append("total_band_invalid")
    sections = spec.get("sections") or []
    keys = [s.get("key") for s in sections]
    if len(keys) != len(set(keys)):
        errors.append("duplicate_section_keys")
    for t in TEMPLATE_SECTIONS:
        if t["required"] and t["key"] not in keys:
            errors.append(f"missing_required:{t['key']}")
    sum_min = sum(_int(s.get("min_words")) for s in sections)
    sum_max = sum(_int(s.get("max_words")) for s in sections)
    if sum_min > t_max:
        errors.append("section_minimums_exceed_page_max")
    if sum_max < t_min:
        errors.append("section_maximums_below_page_min")
    for s in sections:
        lo, hi = _int(s.get("min_words")), _int(s.get("max_words"))
        if lo < 0 or hi < lo:
            errors.append(f"section_band_invalid:{s.get('key')}")
        items = s.get("items")
        wpi = s.get("words_per_item")
        if isinstance(items, dict) and isinstance(wpi, dict):
            if _int(items.get("min")) * _int(wpi.get("min")) > hi:
                errors.append(f"item_floor_does_not_fit:{s.get('key')}")
    structure = spec.get("structure") or {}
    if _int(structure.get("max_sections")) < len([s for s in sections if s.get("required")]):
        errors.append("max_sections_below_required")
    return errors


# ── 6. build ────────────────────────────────────────────────────────────────

def build_spec(
    *,
    client_id: str,
    keyword: str,
    location: str,
    location_code: Optional[int],
    serp_analysis: Optional[dict[str, Any]],
    reference_entry: Optional[dict[str, Any]],
    reference_page_type: Optional[str],
    fallback_target: Optional[int],
    page_type: str = "local_landing",
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Assemble a spec from its three inputs (plan §4). Pure."""
    total, serp_prov, flags = page_band(serp_analysis, fallback_target)
    usable, reason = reference_usable(reference_entry)
    if usable:
        groups = fold_outline((reference_entry or {}).get("analysis", {}).get("outline") or [])
        sections = ensure_required(map_to_template(groups))
        ref_total = sum(_words_of(it) for it in (reference_entry or {}).get("analysis", {}).get("outline") or [] if isinstance(it, dict))
    else:
        sections = ensure_required([])
        ref_total = 0
    sections = allocate_bands(sections, total)
    out_sections: list[dict[str, Any]] = []
    for s in sections:
        t = _template(s["key"]) if s["key"] in TEMPLATE_KEYS else None
        raw_blocks = s.get("blocks") or []
        if t is not None and s["key"] != "local":
            # A template section keeps only REAL reference blocks; a folded
            # heading-only list (a CTA's sub-heading) isn't a block to reproduce.
            raw_blocks = [b for b in raw_blocks if not b.get("folded")]
        blocks = _compact_blocks(raw_blocks) or (copy.deepcopy(t["blocks"]) if t else [])
        entry: dict[str, Any] = {
            "key": s["key"],
            "level": t["level"] if t else (s.get("level") or "H2"),
            "required": bool(s.get("required")),
            "intent": t["intent"] if t else (s.get("intent") or "other"),
            "heading_pattern": (t["heading_pattern"] if t else s.get("intent_note") or s.get("heading") or ""),
            "reference_heading": s.get("heading") or None,
            "min_words": s["min_words"],
            "max_words": s["max_words"],
            "blocks": blocks,
            "source": s.get("source") or "template",
        }
        if t and t.get("items"):
            entry["items"] = dict(t["items"])
        if t and t.get("words_per_item"):
            entry["words_per_item"] = dict(t["words_per_item"])
        if s["key"] == ABSORBER_KEY:
            sub = _template(ABSORBER_KEY)["subsections"]
            ref_sub = int(s.get("subsections") or 0)
            entry["subsections"] = {
                "min": sub["min"],
                "max": max(sub["min"], min(sub["max"], ref_sub)) if ref_sub else sub["max"],
            }
        out_sections.append(entry)
    structure = copy.deepcopy(STRUCTURE_DEFAULTS)
    structure["max_sections"] = max(structure["max_sections"], len(out_sections))
    spec = {
        "schema_version": SCHEMA_VERSION,
        "client_id": client_id,
        "keyword": keyword,
        "location": location,
        "location_code": location_code,
        "page_type": page_type,
        "generated_at": _now_iso(now),
        "edited_at": None,
        "total": total,
        "structure": structure,
        "sections": out_sections,
        "provenance": {
            "reference": {
                "page_type": reference_page_type if usable else None,
                "url": (reference_entry or {}).get("url") if isinstance(reference_entry, dict) else None,
                "analyzed_at": (reference_entry or {}).get("analyzed_at") if isinstance(reference_entry, dict) else None,
                "total_words": ref_total or None,
                "usable": usable,
                "reason": reason,
            },
            "serp": serp_prov,
            "template": TEMPLATE_ID,
            "fallback_reason": ("; ".join(flags) if total["basis"] == "fallback" else None),
            "flags": flags,
        },
    }
    spec["validation_errors"] = validate_spec(spec)
    return spec


def _compact_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge same-type blocks into ``{type, count, items?}`` (no word counts —
    the section band carries the words)."""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        t = str(b.get("type") or "paragraph")
        if t not in merged:
            merged[t] = {"type": t, "count": 0}
            order.append(t)
        merged[t]["count"] += max(1, _int(b.get("count"), 1))
        if b.get("items"):
            merged[t]["items"] = merged[t].get("items", 0) + _int(b.get("items"))
    return [merged[t] for t in order]


# ── 7. measure a generated page against the spec ────────────────────────────

def _content_words(node: Any) -> int:
    """Readable body words under a node, headings + chrome excluded (mirrors
    nlp-api ``length_fit.content_word_count`` so both sides count alike)."""
    frag = BeautifulSoup(str(node), "html.parser")
    for tag in frag(list(_CHROME_TAGS) + list(_HEADING_TAGS)):
        tag.decompose()
    return len(frag.get_text(" ", strip=True).split())


def measure_page(html: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Per-section actuals for a generated page: words + H3 count per
    top-level ``<section>`` (keyed by its id, else heading slug), the page
    total, and each section's status vs its band. Sections the spec doesn't
    know are reported under ``unknown_sections`` (they still count toward the
    total). Deterministic; no I/O."""
    soup = BeautifulSoup(html or "", "html.parser")
    bands = {s["key"]: s for s in (spec.get("sections") or [])}
    rows: list[dict[str, Any]] = []
    unknown: list[str] = []
    seen: set[str] = set()
    total = 0
    max_h3 = 0
    for i, sec in enumerate(soup.find_all("section")):
        if sec.find_parent("section") is not None:
            continue
        heading_el = sec.find(_HEADING_TAGS)
        heading = heading_el.get_text(" ", strip=True) if heading_el else ""
        key = (sec.get("id") or "").strip() or _slug(heading) or f"section-{i}"
        if key in INJECTED_SECTION_IDS:
            continue  # deterministic block, not authored content
        if key in seen:
            key = f"{key}-{i}"
        seen.add(key)
        words = _content_words(sec)
        h3s = len(sec.find_all("h3"))
        max_h3 = max(max_h3, h3s)
        total += words
        band = bands.get(key)
        if band is None:
            unknown.append(key)
            status = "unknown"
            lo = hi = None
        else:
            lo, hi = _int(band.get("min_words")), _int(band.get("max_words"))
            status = "over" if words > hi else ("under" if words < lo else "ok")
        rows.append({"key": key, "heading": heading, "words": words, "h3_count": h3s,
                     "min_words": lo, "max_words": hi, "status": status})
    if not rows:  # no <section> wrappers — measure the whole document
        total = _content_words(soup)
    present = {r["key"] for r in rows}
    missing = [k for k, s in bands.items() if s.get("required") and k not in present]
    return {
        "total_words": total,
        "sections": rows,
        "unknown_sections": unknown,
        "missing_required": missing,
        "section_count": len(rows),
        "max_h3_per_h2": max_h3,
    }


def length_verdict(measure: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """The page's length status vs the spec (plan §5.5): ``in_band`` /
    ``over_length`` / ``under_length``, plus which sections to trim (over their
    band) and the structural caps that were breached. Pure."""
    total = spec.get("total") or {}
    t_min, t_max = _int(total.get("min")), _int(total.get("max"))
    ceiling = int(round(t_max * CEILING_MULTIPLIER))
    words = _int(measure.get("total_words"))
    if words > t_max:
        status = "over_length"
    elif t_min and words < t_min:
        status = "under_length"
    else:
        status = "in_band"
    over = [r["key"] for r in measure.get("sections") or [] if r.get("status") == "over"]
    under = [r["key"] for r in measure.get("sections") or [] if r.get("status") == "under"]
    structure = spec.get("structure") or {}
    caps: list[str] = []
    if _int(structure.get("max_sections")) and _int(measure.get("section_count")) > _int(structure.get("max_sections")):
        caps.append("max_sections")
    if _int(structure.get("max_h3_per_h2")) and _int(measure.get("max_h3_per_h2")) > _int(structure.get("max_h3_per_h2")):
        caps.append("max_h3_per_h2")
    return {
        "status": status,
        "total_words": words,
        "target_words": _int(total.get("target")),
        "min_words": t_min,
        "max_words": t_max,
        "ceiling_words": ceiling,
        "over_ceiling": words > ceiling,
        "over_sections": over,
        "under_sections": under,
        "cap_breaches": caps,
        "missing_required": list(measure.get("missing_required") or []),
    }


# ── 8. render for the writer ────────────────────────────────────────────────

def render_spec_block(spec: dict[str, Any]) -> str:
    """The PAGE SPEC block for the writer prompt: page band, structure caps and
    one line per section with its key, level, band and block composition. This
    REPLACES the per-section template counts + the reference-mirror block +
    the budget line on the Local SEO path, so the writer has one set of numbers.
    Pure text; no new rules — just the numbers."""
    total = spec.get("total") or {}
    structure = spec.get("structure") or {}
    lines = [
        "PAGE SPEC — AUTHORITATIVE LENGTH + STRUCTURE (overrides the per-section counts in the template):",
        f"- Whole <article> body: {total.get('min')}–{total.get('max')} words (aim ~{total.get('target')}). "
        f"Basis: {'competitor SERP average + 20%' if total.get('basis') == 'serp' else 'standing market target (no SERP measured)'}. "
        "Treat the maximum as a HARD CEILING; coming in under is fine, going over is not.",
        f"- At most {structure.get('max_sections')} top-level sections; at most {structure.get('max_h3_per_h2')} H3s under any H2; "
        f"FAQ {structure.get('faq', {}).get('min')}–{structure.get('faq', {}).get('max')} entries.",
        "- Emit each section as <section id=\"KEY\"> with EXACTLY these keys, in this order. "
        "Required sections must be present; optional ones may be omitted when there is no real content.",
    ]
    for s in spec.get("sections") or []:
        blocks = ", ".join(
            f"{b.get('count', 1)}× {b.get('type')}" + (f" ({b['items']} items)" if b.get("items") else "")
            for b in s.get("blocks") or []
        )
        extras = []
        if s.get("subsections"):
            extras.append(f"{s['subsections']['min']}–{s['subsections']['max']} H2/H3 sub-sections")
        if s.get("items"):
            extras.append(f"{s['items']['min']}–{s['items']['max']} items")
        req = "required" if s.get("required") else "optional"
        lines.append(
            f"  [{s['key']}] {s.get('level')} · {req} · {s.get('min_words')}–{s.get('max_words')} words · "
            f"{s.get('intent')}: {s.get('heading_pattern') or ''}"
            + (f" · blocks: {blocks}" if blocks else "")
            + (f" · {'; '.join(extras)}" if extras else "")
        )
    return "\n".join(lines)
