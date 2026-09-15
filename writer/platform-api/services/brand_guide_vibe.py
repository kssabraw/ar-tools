"""Brand Guide Generator — Phase 1.5: the aesthetic / "vibe" read (PRD §4.3).

The deterministic census (`brand_guide_extract`, Phase 0/1) captures the
*ingredients* of a brand's visual identity — exact colors, fonts, sizes, radii —
but not the **aesthetic**: the gestalt a human feels in two seconds
(minimal↔maximal, warm↔cool, budget↔premium, …). That feeling lives in the
*relationships* between tokens (whitespace, contrast, saturation, shape language,
imagery treatment, polish), not the tokens themselves — two brands can share the
same hex + typeface and feel opposite. So a separate **vision pass reads the
captured homepage screenshot** and produces the *felt* layer.

Mechanics (PRD §4.3 / §12 Q4): **one bounded Claude-vision call — Sonnet** (one
tier above the QA visual-check's Haiku, because this read is interpretive and
feeds the whole Aesthetic section + the Phase-2 coherence check), forced-tool
output into a fixed schema, temperature 0 for repeatability, over the
**homepage** screenshot ONLY — read back from the private `brand-guides` bucket
that Phase-1 capture already persisted (so we never re-pay DataForSEO), and the
+2 discovered pages are deliberately NOT sent.

This is **not new infrastructure** — it reuses the exact screenshot+vision
pattern the QA agent already runs (`services/qa_visual.py` visual-render check),
one model tier up. It borrows `qa_visual._fit_image` to size the capture inside
Anthropic's image limits.

Best-effort throughout (PRD §5.4): a disabled flag, a homepage capture that
degraded to CSS-only (no screenshot on file), a storage-download miss, an LLM
failure, or an empty read each **omits `vibe_read`** and the guide still
finalizes `done`. It is presented as an *observed reading the operator can edit*,
never as measurement — the methodology limits ride along in the stored record.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_BUCKET = "brand-guides"

# The fixed mood-axis vocabulary (PRD §4.3). 0 = the LEFT pole, 100 = the RIGHT
# pole. Kept as an ordered mapping so the schema, the prompt, and the sanitizer
# agree on exactly which axes exist — an axis the model invents is dropped.
MOOD_AXES: dict[str, tuple[str, str]] = {
    "minimal_maximal": ("minimal", "maximal"),
    "warm_cool": ("warm", "cool"),
    "playful_serious": ("playful", "serious"),
    "understated_bold": ("understated", "bold"),
    "budget_premium": ("budget", "premium"),
    "organic_geometric": ("organic", "geometric"),
    "classic_futuristic": ("classic", "futuristic"),
}

# The fixed character reads (PRD §4.3). Short free-text descriptions.
CHARACTER_KEYS: tuple[str, ...] = (
    "color_mood",       # muted vs vibrant, mono vs multi
    "type_personality",  # geometric vs humanist, technical vs editorial
    "shape_language",    # sharp vs rounded
    "spatial_density",   # airy vs packed
    "imagery_style",     # photographic vs illustrated vs none; lighting; subjects
)

# Carried in the stored record so the honesty about the read's limits (PRD §4.3)
# rides with it into every later phase / render — it is an interpretation, static
# shots miss motion/interaction, and an LLM read can be wrong.
METHODOLOGY_NOTE = (
    "This is an interpretive reading of the homepage's visual feel, not a "
    "measurement — static screenshots miss motion and interaction, and a "
    "vision model's read can be wrong. Treat it as an observed starting point "
    "you can edit, not a fact."
)

_MAX_DESCRIPTORS = 8
_DESCRIPTOR_LEN = 60
_EVIDENCE_LEN = 240
_CHARACTER_LEN = 240

_TOOL_NAME = "emit_vibe_read"


def _tool_schema() -> dict:
    axis_lines = ", ".join(f"{k} (0={lo}, 100={hi})" for k, (lo, hi) in MOOD_AXES.items())
    return {
        "name": _TOOL_NAME,
        "description": (
            "Record the FELT aesthetic of the brand's homepage from the screenshot. "
            "Describe visual feel ONLY — never assert a product fact, claim, or the "
            "company's business. Every descriptor MUST be tied to a concrete visual "
            "evidence phrase from what is actually on the page."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "aesthetic_descriptors": {
                    "type": "array",
                    "description": (
                        "3-6 adjectives for the overall feel (e.g. clinical, minimalist, "
                        "premium, playful), each grounded in a short evidence phrase."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "descriptor": {"type": "string", "description": "one adjective"},
                            "evidence": {
                                "type": "string",
                                "description": "what on the page shows it, e.g. 'near-black canvas, single electric-violet accent, generous whitespace, hard corners'",
                            },
                        },
                        "required": ["descriptor", "evidence"],
                    },
                },
                "mood_axes": {
                    "type": "object",
                    "description": f"Place the brand on each 0-100 scale: {axis_lines}.",
                    "properties": {
                        k: {"type": "integer", "minimum": 0, "maximum": 100} for k in MOOD_AXES
                    },
                },
                "character": {
                    "type": "object",
                    "description": "Short reads of each visual dimension.",
                    "properties": {k: {"type": "string"} for k in CHARACTER_KEYS},
                },
            },
            "required": ["aesthetic_descriptors", "mood_axes", "character"],
        },
    }


_PROMPT = (
    "You are a brand designer reading the AESTHETIC of a website from a screenshot "
    "of its homepage. Judge the FELT visual identity — the gestalt a person senses "
    "in two seconds: minimalism, warmth, polish, energy, premium-ness, shape "
    "language, density, imagery treatment. This is an interpretation, not a "
    "measurement. Describe only what is VISUALLY on the page — never guess at the "
    "product, its claims, or the business. Ground every descriptor in a concrete "
    "visual detail you can point to. Call the emit_vibe_read tool with your read."
)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def clamp_axis(value: Any) -> Optional[int]:
    """Coerce a mood-axis value to an int clamped to [0, 100]; None when it isn't
    a number (so a garbage axis is dropped, not defaulted). Pure."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, n))


def sanitize_vibe_read(raw: Any) -> Optional[dict]:
    """Fixed-schema sanitize of the vision model's tool output → the stored
    `vibe_read` shape, or None when nothing usable survives. Pure.

    - descriptors: drop any WITHOUT a non-empty evidence phrase (PRD §4.3 — a
      descriptor untied to the render is exactly the ungrounded "Bio-Futuristic
      Sharpness" we're avoiding); trim, dedupe by lowercased descriptor, cap.
    - mood_axes: keep only the known axes, each clamped to 0-100 (drop garbage).
    - character: keep only the known keys with non-empty strings, trimmed/capped.
    """
    if not isinstance(raw, dict):
        return None

    descriptors: list[dict] = []
    seen: set[str] = set()
    for item in raw.get("aesthetic_descriptors") or []:
        if not isinstance(item, dict):
            continue
        desc = str(item.get("descriptor") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        if not desc or not evidence:  # unevidenced descriptor → dropped
            continue
        key = desc.lower()
        if key in seen:
            continue
        seen.add(key)
        descriptors.append({"descriptor": desc[:_DESCRIPTOR_LEN], "evidence": evidence[:_EVIDENCE_LEN]})
        if len(descriptors) >= _MAX_DESCRIPTORS:
            break

    axes_in = raw.get("mood_axes") if isinstance(raw.get("mood_axes"), dict) else {}
    mood_axes: dict[str, int] = {}
    for key in MOOD_AXES:
        if key in axes_in:
            clamped = clamp_axis(axes_in[key])
            if clamped is not None:
                mood_axes[key] = clamped

    char_in = raw.get("character") if isinstance(raw.get("character"), dict) else {}
    character: dict[str, str] = {}
    for key in CHARACTER_KEYS:
        val = str(char_in.get(key) or "").strip()
        if val:
            character[key] = val[:_CHARACTER_LEN]

    if not descriptors and not mood_axes and not character:
        return None
    return {"aesthetic_descriptors": descriptors, "mood_axes": mood_axes, "character": character}


def homepage_screenshot_path(captured: Any) -> Optional[str]:
    """The stored homepage screenshot path from a `captured` record, or None.

    The homepage is the SOLE input to the vibe read (PRD §4.3 / §12 Q4). Falls
    back to the first page carrying a screenshot only if no page is explicitly
    the homepage (defensive; the Phase-1 capture always labels one 'homepage').
    Pure."""
    if not isinstance(captured, dict):
        return None
    pages = captured.get("pages") or []
    if not isinstance(pages, list):
        return None
    for page in pages:
        if isinstance(page, dict) and page.get("role") == "homepage" and page.get("screenshot_path"):
            return page["screenshot_path"]
    return None


# ---------------------------------------------------------------------------
# IO (best-effort throughout)
# ---------------------------------------------------------------------------
def _download_screenshot(path: str) -> Optional[bytes]:
    """Read a stored page screenshot back from the private `brand-guides` bucket.
    None on any failure (missing object / storage error) → the vibe read skips."""
    try:
        return get_supabase().storage.from_(_BUCKET).download(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand_guide_vibe.download_failed", extra={"path": path, "error": str(exc)})
        return None


async def _judge_vibe(image: bytes, media_type: str) -> Optional[dict]:
    """One Sonnet vision call → the raw tool arguments (unsanitized), or None on
    any failure. Reuses the QA visual-check's failover Anthropic client, one model
    tier up, with a forced tool for the fixed schema and temperature 0."""
    try:
        from services import anthropic_failover

        api = anthropic_failover.FailoverAsyncAnthropic(timeout=90.0, log_tag="brand_guide_vibe")
        msg = await api.messages.create(
            model=settings.brand_guide_vibe_model,
            max_tokens=settings.brand_guide_vibe_max_tokens,
            temperature=0,
            tools=[_tool_schema()],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.b64encode(image).decode(),
                        },
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }],
        )
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
                return dict(block.input or {})
        logger.warning("brand_guide_vibe.no_tool_use")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand_guide_vibe.judge_failed", extra={"error": str(exc)})
        return None


async def run_vibe_read_from_png(png: bytes) -> tuple[Optional[dict], str]:
    """Fit → Sonnet vision → sanitize a homepage screenshot into `vibe_read`.
    Returns (vibe_read | None, note). Best-effort — every failure is (None, note)."""
    from services.qa_visual import _fit_image

    fitted = _fit_image(png)
    if fitted is None:
        return None, "vibe read skipped — screenshot too large to send to the vision model"
    image, media_type = fitted
    raw = await _judge_vibe(image, media_type)
    if raw is None:
        return None, "vibe read unavailable — the vision model returned no read"
    vibe = sanitize_vibe_read(raw)
    if vibe is None:
        return None, "vibe read empty after sanitize — no evidenced descriptors / axes"
    vibe["model"] = settings.brand_guide_vibe_model
    vibe["methodology_note"] = METHODOLOGY_NOTE
    return vibe, "vibe read captured"


async def run_vibe_read_for_capture(captured: Any) -> tuple[Optional[dict], str]:
    """Orchestrate the vibe read over a stored `captured` record (PRD §4.3).

    Gated on the module flag + the vibe skip guard. Reads the HOMEPAGE screenshot
    back from the `brand-guides` bucket (no re-capture, no DataForSEO re-pay). A
    capture that degraded to CSS-only (no screenshot path) skips the read with a
    note rather than fabricating a vibe. Returns (vibe_read | None, note)."""
    if not (settings.brand_guide_enabled and settings.brand_guide_vibe_enabled):
        return None, "vibe read skipped — disabled"
    path = homepage_screenshot_path(captured)
    if not path:
        return None, "vibe read skipped — no homepage screenshot on file (capture was CSS-only)"
    png = _download_screenshot(path)
    if not png:
        return None, "vibe read skipped — homepage screenshot could not be read from storage"
    return await run_vibe_read_from_png(png)
