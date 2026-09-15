"""Google Trends — social-fit classifier (the "Trending / social" lane, #1129).

A rising query with **no Ads search volume** (``qualified=false``) is often an
EMERGING term too new to have measured volume yet — not junk. That is exactly the
trend-jacking signal for SOCIAL / short-form content, whereas SEO wants durable,
repeatable demand. The scan already KEEPS these rows; this classifier tags them so
they surface in their own lane instead of sitting dead in the results.

"Good for social" is TWO independent axes (a query needs both):

  * Axis 1 — social-SHAPED (inferable from the query text):
      "cute landscaping vids" (entertainment) vs "what is a landscaper" (SEO).
      A deterministic lexical pass (social markers vs SEO/buyer markers) decides
      most; the ones it can't (``lean='ambiguous'``) are resolved by ONE cheap
      batched Haiku call — mirroring keyword_research_audience's hybrid design
      (cheap deterministic first, LLM only where judgement is needed).
  * Axis 2 — actually SURGING worth timing (velocity):
      ``rising_value`` over a floor; ``is_breakout`` always passes.

``social_score = lean_weight × velocity_factor`` is the lane's sort key —
NOT ``trend_score``, which is ~0 for a no-volume row (it multiplies by volume×CPC),
so it would bury exactly these rows.

Runs on the UNQUALIFIED rows only, best-effort throughout: disabled/no-key/failed
LLM degrades to the deterministic wordlist, never aborts a scan.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Optional

from config import settings
from services import keyword_research

logger = logging.getLogger(__name__)

# Axis 1 — lexical markers over the normalized query.
# Social-leaning: entertainment / format / short-form-video vocabulary. A hit here
# (without an SEO marker) marks the query as social-shaped.
_SOCIAL_MARKERS = (
    "vids", "vid", "video", "videos", "reel", "reels", "short", "shorts",
    "tiktok", "tik tok", "youtube short", "cute", "aesthetic", "satisfying",
    "oddly satisfying", "transformation", "before and after", "before after",
    "makeover", "reveal", "hack", "hacks", "diy", "fail", "fails", "gone wrong",
    "asmr", "timelapse", "time lapse", "pov", "day in the life", "viral",
    "trend", "trending", "challenge", "prank", "meme", "memes", "funny",
    "compilation", "montage",
)
# SEO / buyer / answer intent: a hit here (without a social marker) marks the query
# as SEO-shaped — the existing content lane, not social.
_SEO_MARKERS = (
    "what is", "what are", "how to", "how do", "how does", "why is", "why do",
    "cost", "costs", "price", "pricing", "near me", "vs", "versus", "best",
    "reviews", "review", "services", "service", "company", "companies",
    "hire", "quote", "for sale", "buy", "cheap", "affordable", "supplier",
    "wholesale", "manufacturer",
)

# Marker → suggested content format (first match wins, order = specificity).
_FORMAT_MARKERS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("before and after", "before after", "transformation", "makeover", "reveal"),
     "before/after video"),
    (("asmr", "satisfying", "oddly satisfying", "timelapse", "time lapse"),
     "satisfying / ASMR clip"),
    (("meme", "memes", "funny", "fail", "fails", "gone wrong", "prank"),
     "meme / short"),
    (("vids", "vid", "video", "videos", "reel", "reels", "short", "shorts",
      "tiktok", "tik tok", "pov", "day in the life", "compilation", "montage",
      "challenge", "hack", "hacks", "diy", "viral", "trend", "trending"),
     "short-form video"),
)

_BREAKOUT_VELOCITY = 5000.0  # matches google_trends._BREAKOUT_PCT (kept local — no import cycle)
_LEAN_WEIGHT = {"social": 1.0, "ambiguous": 0.6, "seo": 0.0}

# Health-safety / medical-QUESTION intent (owner ruling 2026-09-15 — flag these,
# don't drop them). Deliberately the *safety/symptom/dosage question* vocabulary,
# NOT "mentions a drug": a query that names a drug but is social ("ozempic weight
# loss coworker discussions") or commercial ("costco ozempic") must NOT flag, while
# a genuine medical question ("ozempic vaginal side effects", "ozempic 4 mg") must.
# Client-agnostic — for a non-health brand these markers simply rarely fire, and
# the flag is advisory (a badge, never a behaviour change). Matched as whole words/
# phrases against the normalized query.
_MEDICAL_MARKERS = (
    "side effect", "side effects", "adverse", "reaction", "reactions",
    "allergic", "allergy", "rash", "nausea", "vomiting", "diarrhea",
    "symptom", "symptoms",
    "dosage", "dose", "dosing", "mg", "mcg", "overdose", "how much to take",
    "injection", "how to inject", "where to inject",
    "interaction", "interactions", "contraindication", "contraindications",
    "withdrawal", "taper", "tapering",
    "is it safe", "safe", "safety", "dangerous", "risks", "side-effect", "black box",
    "pregnant", "pregnancy", "breastfeeding", "breastfeed",
    "blood pressure", "blood sugar", "hypoglycemia", "pancreatitis",
    "kidney", "liver", "thyroid", "gallbladder",
    "vaginal", "vagina", "erectile", "erection",
)


def _phrase_regex(terms) -> re.Pattern:
    """Word-boundary alternation over ``terms`` (phrases allowed), longest first."""
    parts = sorted((re.escape(t) for t in terms), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.I)


_SOCIAL_RE = _phrase_regex(_SOCIAL_MARKERS)
_SEO_RE = _phrase_regex(_SEO_MARKERS)
_MEDICAL_RE = _phrase_regex(_MEDICAL_MARKERS)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ---------------------------------------------------------------------------
def lexical_lean(query: Optional[str]) -> str:
    """Axis-1 lean from the query text alone. Pure.

    'social' when it carries a social marker and no SEO marker; 'seo' when the
    reverse; 'ambiguous' when it has both or neither (the LLM pass resolves those).
    """
    nk = keyword_research.normalize_keyword(query)
    if not nk:
        return "ambiguous"
    social = bool(_SOCIAL_RE.search(nk))
    seo = bool(_SEO_RE.search(nk))
    if social and not seo:
        return "social"
    if seo and not social:
        return "seo"
    return "ambiguous"


def is_sensitive_medical(query: Optional[str]) -> bool:
    """Whether a query reads as a medical / health-safety QUESTION (side effects,
    dosage, symptoms, safety) — a real content opportunity, but one that needs
    careful, authoritative treatment rather than a casual social post. Pure.

    Flags the intent, not the topic: a query that merely names a drug but is social
    or commercial is NOT flagged (no safety/symptom/dosage marker), while a genuine
    medical question is. Advisory only — never changes lane routing."""
    return bool(_MEDICAL_RE.search(keyword_research.normalize_keyword(query)))


def suggested_format(query: Optional[str]) -> Optional[str]:
    """A content-format hint from the query's markers, or None. Pure."""
    nk = keyword_research.normalize_keyword(query)
    if not nk:
        return None
    for markers, fmt in _FORMAT_MARKERS:
        if any(re.search(r"\b" + re.escape(m) + r"\b", nk) for m in markers):
            return fmt
    return None


def velocity_factor(rising_pct: float, is_breakout: bool) -> float:
    """A bounded, monotonic velocity multiplier for the social score. Pure.

    Breakout tops out the scale; otherwise log-shaped so a huge % doesn't swamp
    the lean weight it multiplies (mirrors google_trends.velocity_factor's shape,
    duplicated here to avoid a google_trends ↔ google_trends_social import cycle)."""
    pct = _BREAKOUT_VELOCITY if is_breakout else max(0.0, rising_pct or 0.0)
    return 1.0 + math.log10(1.0 + pct / 100.0)


def social_score(
    rising_value: Optional[float], is_breakout: bool, lean: str
) -> float:
    """velocity × lean weight — the social lane's sort key. Pure.

    0.0 for an SEO-shaped query (it never belongs in the social lane). This is the
    key the lane sorts by; ``trend_score`` is ~0 for these no-volume rows."""
    weight = _LEAN_WEIGHT.get(lean, 0.0)
    if weight <= 0:
        return 0.0
    return round(weight * velocity_factor(rising_value or 0.0, bool(is_breakout)), 3)


def is_social_candidate(row: dict, velocity_floor: float) -> bool:
    """Whether a tagged row belongs in the social lane. Pure.

    Social-shaped (Axis 1) AND surging past the velocity floor (Axis 2) —
    ``is_breakout`` always clears the floor. Unqualified rows only (a query with
    real demand is an SEO/content row, never social)."""
    if row.get("qualified"):
        return False
    if row.get("social_lean") != "social":
        return False
    if row.get("is_breakout"):
        return True
    return (row.get("rising_value") or 0.0) >= velocity_floor


def select_social_rows(rows: list[dict], velocity_floor: float) -> list[dict]:
    """The social lane: social candidates, strongest social_score first. Pure.
    Used by the read/frontend so the lane sorts by social_score, not trend_score."""
    lane = [r for r in rows if is_social_candidate(r, velocity_floor)]
    lane.sort(key=lambda r: (r.get("social_score") or 0.0, r.get("rising_value") or 0.0),
              reverse=True)
    return lane


def apply_lexical(rows: list[dict]) -> list[dict]:
    """Tag every UNQUALIFIED row with its lexical lean + suggested format +
    social_score (Axis 1 only, no LLM). Pure. Mutates + returns ``rows`` so the
    tags ride the persisted dicts. Qualified rows are left untouched."""
    for r in rows:
        if r.get("qualified"):
            continue
        lean = lexical_lean(r.get("query"))
        r["social_lean"] = lean
        r["suggested_format"] = suggested_format(r.get("query"))
        r["social_score"] = social_score(r.get("rising_value"), r.get("is_breakout"), lean)
    return rows


# ---------------------------------------------------------------------------
# Axis-1 LLM resolver for the ambiguous rows (I/O via the shared report_llm).
# ---------------------------------------------------------------------------
_LLM_SYSTEM = (
    "You are a social-media content strategist. For each search query, decide "
    "whether it is SOCIAL-shaped (people looking for entertainment / short-form "
    "video / trends — good to make a social post about) or SEO-shaped "
    "(informational or buyer intent — better as a blog/landing page). Judge by "
    "intent and format, not topic. Be decisive; only use 'ambiguous' when a query "
    "genuinely serves both equally."
)
_LLM_TOOL = {
    "name": "emit_social_fit",
    "description": "Classify each query as social- or SEO-shaped, with a format hint.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "lean": {"type": "string", "enum": ["social", "seo", "ambiguous"]},
                        "format": {
                            "type": "string",
                            "description": "Short content-format hint if social "
                                           "(e.g. 'short-form video', 'meme', "
                                           "'before/after video'); empty otherwise.",
                        },
                    },
                    "required": ["query", "lean"],
                },
            },
        },
        "required": ["items"],
    },
}


def resolve_ambiguous_with_llm(queries: list[str]) -> dict[str, dict]:
    """One batched Haiku call classifying the ambiguous queries. Best-effort:
    returns {normalized_query: {lean, format}}; {} on no key / disabled / failure.

    The caller only overrides rows the wordlist left 'ambiguous', so a miss simply
    leaves the deterministic lean in place."""
    queries = [q for q in queries if q and q.strip()]
    if not queries or not settings.google_trends_social_llm:
        return {}
    have_key = bool(
        settings.anthropic_api_key or settings.openai_api_key or settings.gemini_api_key
    )
    if not have_key:
        return {}
    listing = "\n".join(f"- {q}" for q in queries[:80])
    try:
        from services import report_llm

        result = report_llm.run_forced_tool_sync(
            provider="anthropic",
            model=settings.google_trends_social_model,
            max_tokens=settings.google_trends_social_max_tokens,
            system=_LLM_SYSTEM,
            user=("Classify each of these rising search queries as social- or "
                  f"SEO-shaped:\n{listing}"),
            tool_name=_LLM_TOOL["name"],
            tool_description=_LLM_TOOL["description"],
            input_schema=_LLM_TOOL["input_schema"],
            log_tag="google_trends_social",
        ) or {}
    except Exception as exc:  # noqa: BLE001 — best-effort; keep the lexical lean
        logger.warning("google_trends_social.llm_failed", extra={"error": str(exc)})
        return {}
    out: dict[str, dict] = {}
    for item in (result.get("items") or []):
        if not isinstance(item, dict):
            continue
        q = keyword_research.normalize_keyword(item.get("query"))
        lean = item.get("lean")
        if q and lean in ("social", "seo", "ambiguous"):
            fmt = item.get("format")
            out[q] = {"lean": lean, "format": (fmt.strip() if isinstance(fmt, str) and fmt.strip() else None)}
    return out


def classify_social_fit(rows: list[dict]) -> list[dict]:
    """Full social-fit classifier over a scan's rows (mutates + returns ``rows``).

    Tags each UNQUALIFIED row with social_lean / suggested_format / social_score:
    the deterministic lexical pass first, then ONE batched Haiku call resolves the
    'ambiguous' ones (Axis 1), and social_score is recomputed from the final lean.
    Also flags EVERY row `sensitive_medical` (a health-safety question — kept, not
    dropped, just badged; FLAG ONLY, no lane change). Best-effort + gated:
    classify disabled → social tags untouched; no LLM → lexical only."""
    # Medical-safety flag on every row (qualified + unqualified) so the badge is
    # consistent across both lanes. Deterministic + free; independent of the
    # social classification. Owner ruling 2026-09-15 — flag, don't re-route.
    if settings.google_trends_social_flag_sensitive:
        for r in rows:
            r["sensitive_medical"] = is_sensitive_medical(r.get("query"))
    if not settings.google_trends_social_classify_enabled:
        return rows
    candidates = [r for r in rows if not r.get("qualified")]
    if not candidates:
        return rows
    apply_lexical(candidates)  # Axis 1 (deterministic) + provisional score

    ambiguous = [r for r in candidates if r.get("social_lean") == "ambiguous"]
    if ambiguous:
        resolved = resolve_ambiguous_with_llm([r.get("query") for r in ambiguous])
        if resolved:
            for r in ambiguous:
                got = resolved.get(keyword_research.normalize_keyword(r.get("query")))
                if not got:
                    continue
                r["social_lean"] = got["lean"]
                if got.get("format"):
                    r["suggested_format"] = got["format"]
                r["social_score"] = social_score(
                    r.get("rising_value"), r.get("is_breakout"), r["social_lean"])
    return rows
