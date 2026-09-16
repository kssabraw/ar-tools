"""Brand Guide Generator — Phase 4: the structured-field edit core + adopt/download
helpers (pure, unit-tested).

Phase 4 gives the stored `brand_guides` record a lightweight, NON-canvas edit
surface (PRD §9 / §6 / §13): drop / rename / flag-not-brand a proposed swatch,
replace a tagline / positioning / mission line, and edit a worked voice example.
Applying any edit is what sets `brand_guides.edited = true` — the flag that makes a
regenerate WARN-and-version rather than silently overwrite (the page-spec /
voice-card "edited stays" pattern). The edit operates ONLY on the synthesized
Proposed layer (the operator's judgement over the LLM's proposals); the measured
`visual_census` (Documented truth) is never mutated by an edit.

Everything here is pure over dicts so it unit-tests with no DB / network. The
router owns permissions + I/O; this owns "what an edit means" and the two small
selection helpers the logo-adopt (§12 Q1) + profile download (§4.7) routes need,
plus the pure text builder behind the **suggest-only** voice surface (§4.8) — the
copyable brand-voice block an operator pastes into the EXISTING Brand Voice editor
(this module never writes voice/ICP itself).
"""

from __future__ import annotations

import copy
from typing import Any

# Caps mirror brand_guide_synthesis so an edited value can't exceed a synthesized one.
_STR_CAP = 600
_TAGLINE_CAP = 200
_LONG_CAP = 1500

# The editable Proposed-layer scalar fields (PRD §9).
_FIELD_CAPS = {
    "tagline": _TAGLINE_CAP,
    "positioning_statement": _STR_CAP,
    "mission": _STR_CAP,
}
_VOICE_KEYS = ("headline", "cta", "product_blurb", "email_opener")
_SWATCH_OPS = {"swatch_drop", "swatch_rename", "swatch_flag_not_brand"}
_VALID_OPS = {"set_field", "set_voice_example", *_SWATCH_OPS}


class EditError(Exception):
    """A malformed edit operation — the router maps this to a 422."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _hex_norm(val: Any) -> str:
    return str(val).strip().lower() if val else ""


def _clean(val: Any, cap: int) -> str:
    return str(val).strip()[:cap] if val is not None else ""


def validate_ops(ops: Any) -> list[dict]:
    """Coerce + validate the raw ops list. Raises EditError on anything malformed
    so a bad edit never half-applies. Returns the validated ops."""
    if not isinstance(ops, list) or not ops:
        raise EditError("no_edits")
    out: list[dict] = []
    for op in ops:
        if not isinstance(op, dict):
            raise EditError("invalid_op")
        kind = op.get("op")
        if kind not in _VALID_OPS:
            raise EditError("unknown_op")
        if kind == "set_field":
            if op.get("field") not in _FIELD_CAPS:
                raise EditError("unknown_field")
        elif kind == "set_voice_example":
            if op.get("key") not in _VOICE_KEYS:
                raise EditError("unknown_voice_key")
        else:  # a swatch op
            if not _hex_norm(op.get("hex")):
                raise EditError("missing_hex")
            if kind == "swatch_rename" and not _clean(op.get("name"), 60):
                raise EditError("missing_name")
        out.append(op)
    return out


def apply_edits(synthesized: Any, ops: list[dict]) -> tuple[dict, int]:
    """Apply validated structured-field edits to a copy of `synthesized`.

    Returns ``(new_synthesized, applied_count)``. Pure — never mutates the input.
    An op that targets something not present (a swatch hex the palette doesn't
    carry) is a no-op counted as not-applied, so the router can tell the operator
    when nothing changed. A ``set_*`` to an empty value CLEARS that field (the
    operator deliberately removing a proposed line)."""
    synth = copy.deepcopy(synthesized) if isinstance(synthesized, dict) else {}
    applied = 0
    for op in ops:
        kind = op["op"]
        if kind == "set_field":
            field = op["field"]
            synth[field] = _clean(op.get("value"), _FIELD_CAPS[field])
            applied += 1
        elif kind == "set_voice_example":
            ve = synth.get("voice_examples")
            if not isinstance(ve, dict):
                ve = {}
            value = _clean(op.get("value"), _STR_CAP)
            if value:
                ve[op["key"]] = value
            else:
                ve.pop(op["key"], None)
            synth["voice_examples"] = ve
            applied += 1
        else:  # swatch op
            if _apply_swatch_op(synth, kind, op):
                applied += 1
    return synth, applied


def _apply_swatch_op(synth: dict, kind: str, op: dict) -> bool:
    """Mutate synth['color']['swatches'] for one swatch op. Returns True if it
    matched a swatch. The measured `visual_census` is never touched — only the
    named Proposed palette an operator is curating."""
    color = synth.get("color")
    if not isinstance(color, dict):
        return False
    swatches = color.get("swatches")
    if not isinstance(swatches, list):
        return False
    target = _hex_norm(op.get("hex"))

    if kind == "swatch_drop":
        kept = [s for s in swatches if not (isinstance(s, dict) and _hex_norm(s.get("hex")) == target)]
        if len(kept) == len(swatches):
            return False
        color["swatches"] = kept
        # Keep the usage/ratio map honest after a drop (deterministic, no LLM).
        color["usage_ratios"] = _usage_ratios_from_roles(kept)
        return True

    for s in swatches:
        if isinstance(s, dict) and _hex_norm(s.get("hex")) == target:
            if kind == "swatch_rename":
                s["name"] = _clean(op.get("name"), 60)
            elif kind == "swatch_flag_not_brand":
                s["not_brand"] = True
                # A flagged not-brand swatch drops out of the 60/30/10 usage map
                # too (the render reads it), same as a drop — keep it honest.
                color["usage_ratios"] = _usage_ratios_from_roles(swatches)
            return True
    return False


# Kept local (a copy of brand_guide_synthesis.usage_ratios_from_roles) so this pure
# module has no import of the synthesis pipeline; the shape is identical.
_ROLE_CHOICES = ("primary", "secondary", "accent", "neutral", "other")
_ROLE_RATIO = {"primary": "~60%", "secondary": "~30%", "accent": "~10%"}


def _usage_ratios_from_roles(swatches: list[dict]) -> dict:
    by_role: dict[str, list[str]] = {r: [] for r in _ROLE_CHOICES}
    for sw in swatches:
        if not isinstance(sw, dict) or sw.get("not_brand"):
            continue
        role = sw.get("role") if sw.get("role") in _ROLE_CHOICES else "other"
        if sw.get("hex"):
            by_role[role].append(sw["hex"])
    out: dict[str, Any] = {"ratio": "60% primary / 30% secondary / 10% accent", "roles": {}}
    for role in _ROLE_CHOICES:
        hexes = by_role[role]
        if hexes:
            out["roles"][role] = {"hexes": hexes, "share": _ROLE_RATIO.get(role, "as needed")}
    return out


# ---------------------------------------------------------------------------
# Logo adopt (§12 Q1) — pure candidate selection
# ---------------------------------------------------------------------------
def pick_logo_candidate(visual_census: Any, url: str) -> dict | None:
    """Return the census logo candidate matching `url` (exact), else None. The
    adopt route only ever writes a URL the census actually surfaced — never a
    free-typed one — so a hallucinated/typo'd URL can't be adopted."""
    target = (url or "").strip()
    if not target:
        return None
    census = visual_census if isinstance(visual_census, dict) else {}
    for cand in census.get("logo_candidates") or []:
        if isinstance(cand, dict) and (cand.get("url") or "").strip() == target:
            return cand
    return None


# ---------------------------------------------------------------------------
# Profile download (§4.7) — pure path resolution
# ---------------------------------------------------------------------------
PROFILES = ("internal", "client")


def resolve_render_path(guide: Any, profile: str) -> str | None:
    """The stored PDF storage_path for a render profile, for re-signing on read.

    Prefers the per-profile `renders[profile].storage_path`; falls back to the
    top-level `storage_path` for the CLIENT profile (which mirrors it). Returns
    None when that profile hasn't been rendered."""
    if profile not in PROFILES:
        return None
    guide = guide if isinstance(guide, dict) else {}
    renders = guide.get("renders") if isinstance(guide.get("renders"), dict) else {}
    entry = renders.get(profile) if isinstance(renders.get(profile), dict) else {}
    path = entry.get("storage_path")
    if path:
        return path
    if profile == "client":
        return guide.get("storage_path") or None
    return None


# ---------------------------------------------------------------------------
# Suggest-only voice surface (§4.8) — pure text builder
# ---------------------------------------------------------------------------
def build_voice_suggestion_text(synthesized: Any) -> str:
    """Compose the refined voice/messaging into a single copyable block the
    operator pastes into the EXISTING Brand Voice editor (`raw_text`). This module
    NEVER writes voice/ICP — v1 is suggest-only (§4.8), so the whole surface is
    just this text + a link to the editor. Returns '' when there's nothing to
    suggest. Pure."""
    synth = synthesized if isinstance(synthesized, dict) else {}
    parts: list[str] = []

    positioning = (synth.get("positioning_statement") or "").strip()
    if positioning:
        parts.append(f"Positioning: {positioning}")
    mission = (synth.get("mission") or "").strip()
    if mission:
        parts.append(f"Mission / promise: {mission}")
    tagline = (synth.get("tagline") or "").strip()
    if tagline:
        parts.append(f"Tagline: {tagline}")

    ve = synth.get("voice_examples") if isinstance(synth.get("voice_examples"), dict) else {}
    ve_lines = [
        f"- {label}: {(ve.get(key) or '').strip()}"
        for key, label in (
            ("headline", "Headline"), ("cta", "CTA"),
            ("product_blurb", "Product blurb"), ("email_opener", "Email opener"),
        )
        if (ve.get(key) or "").strip()
    ]
    if ve_lines:
        parts.append("Worked voice examples:\n" + "\n".join(ve_lines))

    wswd = [r for r in (synth.get("we_say_we_dont") or []) if isinstance(r, dict)]
    ws_lines = [
        f"- We say: {(r.get('we_say') or '').strip()} / We don't: {(r.get('we_dont') or '').strip()}"
        for r in wswd if (r.get("we_say") or r.get("we_dont"))
    ]
    if ws_lines:
        parts.append("We say / we don't:\n" + "\n".join(ws_lines))

    km = [str(m).strip() for m in (synth.get("key_messages") or []) if str(m or "").strip()]
    if km:
        parts.append("Key messages:\n" + "\n".join(f"- {m}" for m in km))

    bp = synth.get("boilerplate") if isinstance(synth.get("boilerplate"), dict) else {}
    if (bp.get("short") or "").strip():
        parts.append(f"Boilerplate (short): {bp['short'].strip()}")
    if (bp.get("long") or "").strip():
        parts.append(f"Boilerplate (long): {bp['long'].strip()}")

    return "\n\n".join(parts)
