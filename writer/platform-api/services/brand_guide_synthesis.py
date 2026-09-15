"""Brand Guide Generator — Phase 2: grounded synthesis (the Proposed layer).

Turns the deterministic census (`brand_guide_extract`), the vibe read
(`brand_guide_vibe`), and the client's already-owned voice/ICP/differentiator
assets into the guide's **Proposed** layer (PRD §3 / §4.5): swatch names + roles +
60/30/10 usage + WCAG pairings, a named type scale, imagery/iconography direction,
a tagline, a positioning statement + mission, worked voice examples, a
we-say/we-don't table, key messages, boilerplate, the **coherence check** (vibe vs
census), and a per-section gap analysis.

Two bounded forced-tool calls (PRD §12 Q4), each best-effort and independent:
  * **naming** — Haiku NAMES + ROLES the measured tokens (swatches, type steps) +
    proposes imagery/iconography direction + tagline options. It is handed the
    exact measured hexes and never invents one (PRD §5.2).
  * **messaging** — Sonnet writes the strategy layer (positioning, worked
    examples, boilerplate, key messages, coherence narrative, gap analysis) over
    the (guardrail-filtered) asset corpus.

Determinism where it counts (PRD §5.2): the WCAG contrast pairings, the coherence
flags, and the 60/30/10 usage mapping are computed in Python
(`brand_guide_coherence`) and handed to the LLM as facts / attached to the output
— the LLM narrates them, it never computes them.

Guardrail (PRD §5.3): a **universal** prompt exclusion (every client — never a
product claim / efficacy / dosage / safety / "FDA" / any ungrounded fact); PLUS,
for a regulated client (`content_compliance_mode != 'off'`), a deterministic
claim-shape input-filter (`brand_guide_guardrail`) excises tripping sentences from
the corpus BEFORE synthesis, and the guide finalizes **`awaiting_signoff`** rather
than `done` (the separate render/approval flow is Phase 3/4).

Best-effort throughout (PRD §5.4): a disabled flag, a missing asset, or a failed
LLM call omits `synthesized` (or the failed half) and the guide still finalizes.
Pure helpers are unit-tested; the LLM calls are mocked in tests.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from config import settings
from db.supabase_client import get_supabase
from services import (
    brand_guide_coherence as coherence,
    brand_guide_guardrail as guardrail,
    brand_voice_service,
    content_compliance,
    icp_service,
    report_llm,
)

logger = logging.getLogger(__name__)

_ROLE_CHOICES = ("primary", "secondary", "accent", "neutral", "other")
# Positional type-scale names, largest → smallest, when the model didn't name one.
_TYPE_NAMES = ("Display", "H1", "H2", "H3", "H4", "Body Large", "Body", "Small", "Caption")

# Caps so a runaway model output can't bloat the stored jsonb.
_MAX_KEY_MESSAGES = 8
_MAX_WE_SAY = 10
_MAX_SECTION_GAPS = 12
_MAX_TAGLINE_OPTIONS = 5
_MAX_IMAGERY_ITEMS = 8
_STR_CAP = 600
_LONG_CAP = 1500


# --------------------------------------------------------------------------
# Universal + per-call prompt scaffolding (PRD §5.3 universal exclusions)
# --------------------------------------------------------------------------
_UNIVERSAL_EXCLUSIONS = """UNIVERSAL RULES — you are writing a BRAND guide, not marketing copy.
You MAY invent brand LANGUAGE: swatch names, taglines, tone/aesthetic words, a positioning angle.
You must NEVER state, imply, or invent:
- a product claim, efficacy, benefit-as-fact, or result;
- a dosage, administration route, or usage instruction;
- a safety, therapeutic, medical, or health-outcome claim;
- a regulatory status or any "FDA" / "clinically proven" reference;
- ANY fact (statistic, credential, guarantee, award, price, years-in-business) not present in the grounding below.
If a fact is not in the grounding, omit it. When in doubt, describe the brand's LANGUAGE and LOOK, never its product's effects."""

_NAMING_SYSTEM = (
    "You are a brand designer NAMING and ORGANIZING a brand's already-measured visual identity. "
    "You are given the EXACT colours and type sizes measured from the live site — name and role them, "
    "never invent or alter a hex or a size. Propose imagery/iconography DIRECTION (subjects, lighting, "
    "treatment) and a few tagline options grounded in the brand's feel.\n\n" + _UNIVERSAL_EXCLUSIONS
)

_MESSAGING_SYSTEM = (
    "You are a brand strategist writing the MESSAGING + VOICE layer of a brand guide, grounded strictly "
    "in the provided assets, captured site copy, measured visuals, and coherence findings. Write a "
    "positioning statement, mission/promise, tagline, worked voice examples (headline / CTA / product "
    "blurb / email opener) that sound like THIS brand, a we-say/we-don't table, key messages, short + "
    "long boilerplate, a coherence narrative (does the executed detail match the intended feel?), and a "
    "per-section gap analysis. Reframe every coherence gap as a forward-looking opportunity, never a "
    "diagnosis of failure.\n\n" + _UNIVERSAL_EXCLUSIONS
)


# --------------------------------------------------------------------------
# Tool schemas
# --------------------------------------------------------------------------
def _naming_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "swatches": {
                "type": "array",
                "description": "Name + role each measured colour. hex MUST be one of the provided measured hexes, verbatim.",
                "items": {
                    "type": "object",
                    "properties": {
                        "hex": {"type": "string", "description": "one of the exact measured hexes, verbatim"},
                        "name": {"type": "string", "description": "an evocative swatch name, e.g. 'Midnight Navy'"},
                        "role": {"type": "string", "enum": list(_ROLE_CHOICES)},
                    },
                    "required": ["hex", "name", "role"],
                },
            },
            "type_scale": {
                "type": "array",
                "description": "Name + usage for each measured type size. px MUST be one of the provided sizes.",
                "items": {
                    "type": "object",
                    "properties": {
                        "px": {"type": "number"},
                        "name": {"type": "string", "description": "e.g. 'H1', 'Body'"},
                        "usage": {"type": "string"},
                    },
                    "required": ["px", "name"],
                },
            },
            "imagery_direction": {
                "type": "object",
                "properties": {
                    "subjects": {"type": "string"},
                    "lighting": {"type": "string"},
                    "treatment": {"type": "string"},
                    "stock_vs_custom": {"type": "string"},
                    "dos": {"type": "array", "items": {"type": "string"}},
                    "donts": {"type": "array", "items": {"type": "string"}},
                },
            },
            "iconography": {"type": "string", "description": "the icon style direction"},
            "tagline_options": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["swatches"],
    }


def _messaging_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "tagline": {"type": "string"},
            "mission": {"type": "string", "description": "the brand's mission / promise"},
            "positioning_statement": {"type": "string"},
            "palette_usage": {"type": "string", "description": "how to apply the palette (the 60/30/10 narrative)"},
            "voice_examples": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "cta": {"type": "string"},
                    "product_blurb": {"type": "string"},
                    "email_opener": {"type": "string"},
                },
            },
            "we_say_we_dont": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"we_say": {"type": "string"}, "we_dont": {"type": "string"}},
                    "required": ["we_say", "we_dont"],
                },
            },
            "key_messages": {"type": "array", "items": {"type": "string"}},
            "boilerplate": {
                "type": "object",
                "properties": {"short": {"type": "string"}, "long": {"type": "string"}},
            },
            "coherence_narrative": {"type": "string"},
            "section_gaps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"section": {"type": "string"}, "gap": {"type": "string"}},
                    "required": ["section", "gap"],
                },
            },
        },
        "required": ["positioning_statement"],
    }


# --------------------------------------------------------------------------
# Pull existing assets (PRD §4.4) — pure over a client dict
# --------------------------------------------------------------------------
def pull_assets(client: dict) -> dict:
    """Read the client's already-owned brand assets for grounding (PRD §4.4).

    Reads via `resolve_brand_guide_text` / `resolve_icp_text` (the converged
    brand_voice / detected_icp, human-seed-aware) — NOT the legacy top-level
    `*_text` columns (empty for current clients). The cached Voice & Audience Card
    (`clients.voice_card.card`) is read as-is; it is never distilled here (that
    would be a paid call on the render hot path). Best-effort — every field
    degrades to empty/None. Pure over the client dict."""
    client = client if isinstance(client, dict) else {}
    voice_card = client.get("voice_card")
    card = voice_card.get("card") if isinstance(voice_card, dict) else None
    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else {}
    diffs = client.get("differentiators")
    return {
        "business_name": (client.get("name") or "").strip(),
        "website": (client.get("website_url") or "").strip(),
        "brand_voice_text": brand_voice_service.resolve_brand_guide_text(client) or "",
        "icp_text": icp_service.resolve_icp_text(client) or "",
        "voice_card": card if isinstance(card, dict) else None,
        "differentiators": diffs if isinstance(diffs, list) else [],
        "logo_url": (client.get("logo_url") or gbp.get("logo") or "").strip() or None,
    }


# --------------------------------------------------------------------------
# Prompt-corpus builders (pure)
# --------------------------------------------------------------------------
def _site_copy(captured: Any) -> str:
    """The captured site copy (per-page title / meta / h1) for grounding. Pure."""
    if not isinstance(captured, dict):
        return ""
    lines: list[str] = []
    for page in captured.get("pages") or []:
        if not isinstance(page, dict):
            continue
        dom = page.get("dom_digest") or {}
        for key in ("title", "meta_description", "h1"):
            val = (dom.get(key) or "").strip() if isinstance(dom, dict) else ""
            if val:
                lines.append(val)
    return "\n".join(lines)


def build_synthesis_corpus(assets: dict, captured: Any) -> str:
    """Assemble the TEXT grounding corpus (site copy + voice + ICP + differentiators).

    This is the corpus the regulated input-filter runs over (`brand_guide_guardrail`)
    — the visual census/vibe summaries are separate prompt sections and carry no
    claims, so they are never filtered. Pure."""
    parts: list[str] = []
    if assets.get("business_name"):
        parts.append(f"Business: {assets['business_name']}")
    if assets.get("website"):
        parts.append(f"Website: {assets['website']}")
    site = _site_copy(captured)
    if site:
        parts.append("SITE COPY:\n" + site)
    if assets.get("brand_voice_text"):
        parts.append("BRAND VOICE ON FILE:\n" + assets["brand_voice_text"])
    if assets.get("icp_text"):
        parts.append("AUDIENCE (ICP) ON FILE:\n" + assets["icp_text"])
    diffs = assets.get("differentiators") or []
    if diffs:
        diff_lines = []
        for d in diffs:
            if isinstance(d, dict):
                claim = (d.get("claim") or "").strip()
                mech = (d.get("mechanism") or "").strip()
                if claim:
                    diff_lines.append(f"- {claim}" + (f" (mechanism: {mech})" if mech else ""))
        if diff_lines:
            parts.append("DIFFERENTIATORS ON FILE:\n" + "\n".join(diff_lines))
    return "\n\n".join(parts)


def _census_summary(census: Any) -> str:
    """A compact measured-visual summary for the prompt (facts the LLM names). Pure."""
    census = census if isinstance(census, dict) else {}
    lines: list[str] = []
    colors = [c for c in (census.get("colors") or []) if isinstance(c, dict)]
    if colors:
        lines.append("MEASURED COLOURS (name + role these EXACT hexes, do not invent):")
        for c in colors:
            share = c.get("share")
            pct = f" ({round(share * 100)}% of the page)" if isinstance(share, (int, float)) else ""
            lines.append(f"  {c.get('hex')}{pct}")
    fonts = [f for f in (census.get("fonts") or []) if isinstance(f, dict)]
    if fonts:
        lines.append("MEASURED TYPEFACES: " + ", ".join(str(f.get("name")) for f in fonts if f.get("name")))
    steps = [t for t in (census.get("type_scale") or []) if isinstance(t, dict)]
    if steps:
        lines.append("MEASURED TYPE SIZES (px, largest→smallest): " + ", ".join(str(t.get("px")) for t in steps))
    return "\n".join(lines)


def _vibe_summary(vibe_read: Any) -> str:
    """A compact vibe-read summary for the prompt. Pure."""
    if not isinstance(vibe_read, dict):
        return ""
    lines: list[str] = []
    descriptors = vibe_read.get("aesthetic_descriptors") or []
    words = [d.get("descriptor") for d in descriptors if isinstance(d, dict) and d.get("descriptor")]
    if words:
        lines.append("AESTHETIC (felt): " + ", ".join(words))
    axes = vibe_read.get("mood_axes") or {}
    if isinstance(axes, dict) and axes:
        lines.append("MOOD AXES (0-100): " + ", ".join(f"{k}={v}" for k, v in axes.items()))
    char = vibe_read.get("character") or {}
    if isinstance(char, dict) and char:
        lines.append("CHARACTER: " + "; ".join(f"{k}: {v}" for k, v in char.items()))
    return "\n".join(lines)


def _coherence_summary(flags: list[dict]) -> str:
    """Render the deterministic coherence flags for the messaging prompt. Pure."""
    if not flags:
        return ""
    lines = ["COHERENCE FINDINGS (narrate these as opportunities; the numbers are measured — do not change them):"]
    for f in flags:
        lines.append(f"  - [{f.get('section')}] {f.get('title')}: {f.get('detail')}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Deterministic 60/30/10 usage from the LLM-assigned roles (pure — PRD §5.2)
# --------------------------------------------------------------------------
_ROLE_RATIO = {"primary": "~60%", "secondary": "~30%", "accent": "~10%"}


def usage_ratios_from_roles(swatches: list[dict]) -> dict:
    """Group the roled swatches into the 60/30/10 convention. Pure/deterministic —
    the ratio convention is applied in code once roles exist, not asked of the LLM."""
    by_role: dict[str, list[str]] = {r: [] for r in _ROLE_CHOICES}
    for sw in swatches:
        role = sw.get("role") if sw.get("role") in _ROLE_CHOICES else "other"
        if sw.get("hex"):
            by_role[role].append(sw["hex"])
    out: dict[str, Any] = {"ratio": "60% primary / 30% secondary / 10% accent", "roles": {}}
    for role in _ROLE_CHOICES:
        hexes = by_role[role]
        if hexes:
            out["roles"][role] = {"hexes": hexes, "share": _ROLE_RATIO.get(role, "as needed")}
    return out


# --------------------------------------------------------------------------
# Sanitizers (pure)
# --------------------------------------------------------------------------
def _s(val: Any, cap: int = _STR_CAP) -> str:
    return str(val).strip()[:cap] if val else ""


def _slist(val: Any, cap_items: int, cap_len: int = _STR_CAP) -> list[str]:
    # Only iterate a real sequence: a model (esp. a report_llm fallback provider)
    # can return a scalar string where the schema declares an array, and iterating
    # a str would split it into characters. A lone string is wrapped as one item.
    if isinstance(val, str):
        val = [val]
    elif not isinstance(val, (list, tuple)):
        val = []
    out: list[str] = []
    for item in val:
        s = _s(item, cap_len)
        if s:
            out.append(s)
        if len(out) >= cap_items:
            break
    return out


def _hex_norm(val: Any) -> str:
    return str(val).strip().lower() if val else ""


def sanitize_naming(raw: Any, census: Any) -> dict:
    """Fold the naming call into census-anchored swatches + a named type scale +
    imagery/iconography + tagline options. Pure.

    Every documented swatch appears (built from the census, in census order) with
    the LLM's name/role attached where its hex matches; an LLM swatch whose hex is
    NOT in the census is dropped (never invent a hex — PRD §5.2). Type steps are
    likewise built from the census, LLM-named where the px matches, else named
    positionally (Display/H1/…)."""
    raw = raw if isinstance(raw, dict) else {}
    census = census if isinstance(census, dict) else {}

    llm_by_hex: dict[str, dict] = {}
    for item in raw.get("swatches") or []:
        if isinstance(item, dict):
            h = _hex_norm(item.get("hex"))
            if h:
                llm_by_hex[h] = item

    swatches: list[dict] = []
    for c in census.get("colors") or []:
        if not isinstance(c, dict):
            continue
        h = _hex_norm(c.get("hex"))
        named = llm_by_hex.get(h) or {}
        role = named.get("role") if named.get("role") in _ROLE_CHOICES else "other"
        swatches.append({
            "hex": c.get("hex"),
            "css_hex": c.get("css_hex"),
            "share": c.get("share"),
            "source": c.get("source"),
            "name": _s(named.get("name"), 60),
            "role": role,
            "is_recommendation": False,  # every documented swatch is real, on-site
        })

    # Type scale: census steps, LLM name/usage where the px matches (within 0.5px).
    llm_steps = [t for t in (raw.get("type_scale") or []) if isinstance(t, dict)]
    census_steps = [t for t in (census.get("type_scale") or []) if isinstance(t, dict)]
    type_scale: list[dict] = []
    for i, step in enumerate(census_steps):
        px = step.get("px")
        match = None
        for t in llm_steps:
            try:
                if abs(float(t.get("px")) - float(px)) <= 0.5:
                    match = t
                    break
            except (TypeError, ValueError):
                continue
        name = _s((match or {}).get("name"), 40) or (_TYPE_NAMES[i] if i < len(_TYPE_NAMES) else f"Step {i + 1}")
        type_scale.append({"px": px, "name": name, "usage": _s((match or {}).get("usage"), 120)})

    imagery = raw.get("imagery_direction") if isinstance(raw.get("imagery_direction"), dict) else {}
    imagery_out = {
        "subjects": _s(imagery.get("subjects")),
        "lighting": _s(imagery.get("lighting")),
        "treatment": _s(imagery.get("treatment")),
        "stock_vs_custom": _s(imagery.get("stock_vs_custom")),
        "dos": _slist(imagery.get("dos"), _MAX_IMAGERY_ITEMS),
        "donts": _slist(imagery.get("donts"), _MAX_IMAGERY_ITEMS),
    }
    if not any(imagery_out.values()):
        imagery_out = {}

    return {
        "swatches": swatches,
        "type_scale": type_scale,
        "imagery_direction": imagery_out,
        "iconography": _s(raw.get("iconography")),
        "tagline_options": _slist(raw.get("tagline_options"), _MAX_TAGLINE_OPTIONS, 120),
    }


def sanitize_messaging(raw: Any) -> dict:
    """Cap + coerce the messaging call into the stored shape. Pure."""
    raw = raw if isinstance(raw, dict) else {}
    ve = raw.get("voice_examples") if isinstance(raw.get("voice_examples"), dict) else {}
    voice_examples = {
        k: _s(ve.get(k)) for k in ("headline", "cta", "product_blurb", "email_opener") if _s(ve.get(k))
    }

    we_say: list[dict] = []
    for item in raw.get("we_say_we_dont") or []:
        if isinstance(item, dict):
            say, dont = _s(item.get("we_say"), 200), _s(item.get("we_dont"), 200)
            if say or dont:
                we_say.append({"we_say": say, "we_dont": dont})
        if len(we_say) >= _MAX_WE_SAY:
            break

    section_gaps: list[dict] = []
    for item in raw.get("section_gaps") or []:
        if isinstance(item, dict):
            section, gap = _s(item.get("section"), 60), _s(item.get("gap"), 400)
            if gap:
                section_gaps.append({"section": section, "gap": gap})
        if len(section_gaps) >= _MAX_SECTION_GAPS:
            break

    bp = raw.get("boilerplate") if isinstance(raw.get("boilerplate"), dict) else {}
    boilerplate = {"short": _s(bp.get("short")), "long": _s(bp.get("long"), _LONG_CAP)}
    if not (boilerplate["short"] or boilerplate["long"]):
        boilerplate = {}

    return {
        "tagline": _s(raw.get("tagline"), 200),
        "mission": _s(raw.get("mission")),
        "positioning_statement": _s(raw.get("positioning_statement")),
        "palette_usage": _s(raw.get("palette_usage")),
        "voice_examples": voice_examples,
        "we_say_we_dont": we_say,
        "key_messages": _slist(raw.get("key_messages"), _MAX_KEY_MESSAGES),
        "boilerplate": boilerplate,
        "coherence_narrative": _s(raw.get("coherence_narrative"), _LONG_CAP),
        "section_gaps": section_gaps,
    }


def assemble_synthesized(
    naming: Optional[dict],
    messaging: Optional[dict],
    *,
    coherence_flags: list[dict],
    pairings: list[dict],
    provenance: dict,
) -> Optional[dict]:
    """Merge the (best-effort) naming + messaging halves with the deterministic
    coherence + contrast layers into the stored `synthesized` shape. Returns None
    only when BOTH LLM halves failed AND there is nothing deterministic worth
    storing. Pure."""
    naming = naming or {}
    messaging = messaging or {}
    swatches = naming.get("swatches") or []

    synthesized: dict[str, Any] = {
        "tagline": messaging.get("tagline") or (naming.get("tagline_options") or [None])[0] or "",
        "tagline_options": naming.get("tagline_options") or [],
        "mission": messaging.get("mission", ""),
        "positioning_statement": messaging.get("positioning_statement", ""),
        "color": {
            "swatches": swatches,
            "usage_ratios": usage_ratios_from_roles(swatches) if swatches else {},
            "usage_narrative": messaging.get("palette_usage", ""),
            "pairings": pairings,
        },
        "type_scale": naming.get("type_scale") or [],
        "imagery_direction": naming.get("imagery_direction") or {},
        "iconography": naming.get("iconography", ""),
        "voice_examples": messaging.get("voice_examples") or {},
        "we_say_we_dont": messaging.get("we_say_we_dont") or [],
        "key_messages": messaging.get("key_messages") or [],
        "boilerplate": messaging.get("boilerplate") or {},
        "coherence": {
            "flags": coherence_flags,
            "narrative": messaging.get("coherence_narrative", ""),
        },
        "section_gaps": messaging.get("section_gaps") or [],
        "provenance": provenance,
    }

    has_llm = bool(naming) or bool(messaging)
    has_det = bool(coherence_flags) or bool(pairings)
    if not has_llm and not has_det:
        return None
    return synthesized


# --------------------------------------------------------------------------
# LLM calls (impure, best-effort → None)
# --------------------------------------------------------------------------
async def _run_naming(user: str) -> Optional[dict]:
    try:
        return await report_llm.run_forced_tool(
            provider="anthropic",
            model=settings.brand_guide_naming_model,
            system=_NAMING_SYSTEM,
            user=user,
            tool_name="emit_brand_naming",
            tool_description="Name + role the measured visual tokens and propose imagery/iconography direction.",
            input_schema=_naming_schema(),
            max_tokens=settings.brand_guide_naming_max_tokens,
            log_tag="brand_guide_naming",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand_guide_synthesis.naming_failed", extra={"error": str(exc)[:200]})
        return None


async def _run_messaging(user: str) -> Optional[dict]:
    try:
        return await report_llm.run_forced_tool(
            provider="anthropic",
            model=settings.brand_guide_synthesis_model,
            system=_MESSAGING_SYSTEM,
            user=user,
            tool_name="emit_brand_messaging",
            tool_description="Write the messaging + voice layer grounded strictly in the provided assets.",
            input_schema=_messaging_schema(),
            max_tokens=settings.brand_guide_synthesis_max_tokens,
            log_tag="brand_guide_messaging",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand_guide_synthesis.messaging_failed", extra={"error": str(exc)[:200]})
        return None


def _naming_user(census: Any, vibe_read: Any) -> str:
    return "\n\n".join(p for p in (
        "Name and role this brand's measured visual identity.",
        _census_summary(census),
        _vibe_summary(vibe_read),
    ) if p)


def _messaging_user(corpus: str, census: Any, vibe_read: Any, coherence_flags: list[dict]) -> str:
    return "\n\n".join(p for p in (
        "Write the messaging + voice layer for this brand's guide.",
        corpus,
        _census_summary(census),
        _vibe_summary(vibe_read),
        _coherence_summary(coherence_flags),
    ) if p)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
async def run_synthesis_for_guide(
    client: dict,
    *,
    census: Any,
    vibe_read: Any = None,
    captured: Any = None,
) -> tuple[Optional[dict], str, str]:
    """Synthesize the Proposed layer for one guide (PRD §4.5). Best-effort.

    Returns ``(synthesized | None, note, status)`` where status ∈
    ``{'done', 'awaiting_signoff'}``: a regulated client (`content_compliance_mode
    != 'off'`) whose synthesis produced content finalizes `awaiting_signoff`
    (the §5.3b sign-off gate; render/approval is Phase 3/4), everyone else `done`.
    A disabled flag / no LLM output → (None, note, 'done')."""
    if not (settings.brand_guide_enabled and settings.brand_guide_synthesis_enabled):
        return None, "synthesis skipped — disabled", "done"

    mode = content_compliance.resolve_mode(client)
    regulated = mode != "off"

    assets = pull_assets(client)
    coherence_flags = coherence.build_coherence_flags(census, vibe_read)
    census_colors = [c for c in ((census or {}).get("colors") or []) if isinstance(c, dict)] if isinstance(census, dict) else []
    pairings = coherence.contrast_pairings(census_colors) if census_colors else []

    # Corpus + the regulated input-filter (excise claim-shape sentences BEFORE synthesis).
    corpus = build_synthesis_corpus(assets, captured)
    filtered_corpus, excised = guardrail.filter_synthesis_corpus(corpus, mode)

    naming_raw = await _run_naming(_naming_user(census, vibe_read))
    messaging_raw = await _run_messaging(_messaging_user(filtered_corpus, census, vibe_read, coherence_flags))

    naming = sanitize_naming(naming_raw, census) if naming_raw is not None else None
    messaging = sanitize_messaging(messaging_raw) if messaging_raw is not None else None

    provenance = {
        "regulated": regulated,
        "compliance_mode": mode,
        "excised_sentences": len(excised),
        "excised": excised[:20],
        "naming_ok": naming_raw is not None,
        "messaging_ok": messaging_raw is not None,
        "models": {
            "naming": settings.brand_guide_naming_model,
            "messaging": settings.brand_guide_synthesis_model,
        },
        "assets_used": {
            "brand_voice": bool(assets.get("brand_voice_text")),
            "icp": bool(assets.get("icp_text")),
            "voice_card": bool(assets.get("voice_card")),
            "differentiators": len(assets.get("differentiators") or []),
            "logo_url": bool(assets.get("logo_url")),
        },
    }

    synthesized = assemble_synthesized(
        naming, messaging,
        coherence_flags=coherence_flags, pairings=pairings, provenance=provenance,
    )

    if synthesized is None:
        return None, "synthesis produced no usable output", "done"

    if naming_raw is not None and messaging_raw is not None:
        note = "synthesis complete"
    elif naming_raw is None and messaging_raw is None:
        # Both LLM halves failed; only the deterministic coherence/contrast layer
        # survived (or synthesized would be None and we'd have returned above).
        note = "synthesis deterministic-only (both LLM calls failed)"
    elif messaging_raw is None:
        note = "synthesis partial (naming only)"
    else:
        note = "synthesis partial (messaging only)"

    # Regulated + we actually synthesized content → hold for human sign-off (§5.3b).
    if regulated:
        note += " — awaiting sign-off (regulated client)"
        return synthesized, note, "awaiting_signoff"
    return synthesized, note, "done"
