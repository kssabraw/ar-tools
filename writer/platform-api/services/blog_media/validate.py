"""App-side media-plan validation — the independent enforcement the addendum
mandates. The model's own `validation` block is never trusted; every relevant
condition is re-checked here in code and invalid *optional* assets are dropped
(not repaired). Pure and unit-tested.

Phase 1 scope: hero + generated inline images. Chart assets are recognized but
deferred (dropped with a skip reason) until Phase 2 renders SVG charts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.blog_media.article_html import IdIndex

_FILENAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.(webp|svg)$")


def valid_filename(name: str, ext: str) -> bool:
    """Lowercase letters/numbers/hyphens only, ≤80 chars, correct extension."""
    if not name or len(name) > 80:
        return False
    if not _FILENAME_RE.match(name):
        return False
    return name.endswith(f".{ext}")


def placement_resolvable(placement: dict, idx: IdIndex) -> bool:
    """A placement can be resolved if its anchor_id or section_id is a real ID,
    or it supplies a non-empty fallback_excerpt (verified verbatim later)."""
    if not isinstance(placement, dict):
        return False
    if (placement.get("anchor_id") or "").strip() in idx.anchor_ids:
        return True
    if (placement.get("section_id") or "").strip() in idx.anchor_ids:
        return True
    return bool((placement.get("fallback_excerpt") or "").strip())


@dataclass
class ValidationResult:
    hero: dict | None = None          # normalized hero, or None → use fallback image
    hero_ok: bool = False
    inline: list[dict] = field(default_factory=list)   # normalized kept inline assets
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _normalize_hero(h: dict, *, hero_min: float) -> tuple[dict | None, list[str]]:
    errs: list[str] = []
    if not isinstance(h, dict):
        return None, ["hero_missing"]
    if h.get("status") != "create":
        errs.append("hero_status_not_create")
    prompt = (h.get("prompt") or "").strip()
    if not prompt:
        errs.append("hero_prompt_empty")
    filename = (h.get("filename") or "").strip()
    if not valid_filename(filename, "webp"):
        errs.append("hero_filename_invalid")
    conf = _as_float(h.get("confidence"))
    if conf < hero_min:
        errs.append(f"hero_confidence_below_{hero_min}")
    if errs:
        return None, errs
    return {
        "asset_id": "hero",
        "role": "hero",
        "asset_type": "image",
        "prompt": prompt,
        "alt": (h.get("alt_text") or "").strip(),
        "caption": (h.get("caption") or "").strip() or None,
        "filename": filename,
        "width": int(h.get("width") or 0) or None,
        "height": int(h.get("height") or 0) or None,
        "confidence": conf,
        "concept": (h.get("concept") or "").strip(),
    }, []


def _normalize_inline(asset: dict, *, idx: IdIndex, inline_min: float, chart_min: float,
                      allow_charts: bool) -> tuple[dict | None, str | None]:
    """Return (normalized_asset, None) if kept, or (None, skip_reason) if dropped."""
    if not isinstance(asset, dict):
        return None, "not_an_object"
    asset_id = (asset.get("asset_id") or "").strip()
    if not asset_id:
        return None, "missing_asset_id"
    atype = asset.get("asset_type")
    placement = asset.get("placement") or {}

    if atype == "chart":
        if not allow_charts:
            return None, "charts_deferred_to_phase_2"
        chart = asset.get("chart") or {}
        if chart.get("status") != "create":
            return None, "chart_not_create"
        if _as_float(chart.get("confidence")) < chart_min:
            return None, "chart_confidence_below_threshold"
        if not valid_filename((chart.get("filename") or "").strip(), "svg"):
            return None, "chart_filename_invalid"
        if not placement_resolvable(placement, idx):
            return None, "chart_placement_unresolvable"
        # Phase 2 will deep-validate values/sources; kept minimally here.
        return {
            "asset_id": asset_id, "role": "inline", "asset_type": "chart",
            "chart": chart, "placement": placement,
            "alt": (chart.get("alt_text") or "").strip(),
            "caption": (chart.get("caption") or "").strip() or None,
            "filename": (chart.get("filename") or "").strip(),
            "confidence": _as_float(chart.get("confidence")),
        }, None

    # Default: generated image.
    gi = asset.get("generated_image") or {}
    if gi.get("status") != "create":
        return None, "image_not_create"
    prompt = (gi.get("prompt") or "").strip()
    if not prompt:
        return None, "image_prompt_empty"
    if _as_float(gi.get("confidence")) < inline_min:
        return None, "image_confidence_below_threshold"
    if not valid_filename((gi.get("filename") or "").strip(), "webp"):
        return None, "image_filename_invalid"
    if not placement_resolvable(placement, idx):
        return None, "image_placement_unresolvable"
    return {
        "asset_id": asset_id, "role": "inline", "asset_type": "image",
        "prompt": prompt,
        "alt": (gi.get("alt_text") or "").strip(),
        "caption": (gi.get("caption") or "").strip() or None,
        "filename": (gi.get("filename") or "").strip(),
        "width": int(gi.get("width") or 0) or None,
        "height": int(gi.get("height") or 0) or None,
        "confidence": _as_float(gi.get("confidence")),
        "concept": (gi.get("concept") or "").strip(),
        "placement": placement,
    }, None


def validate_and_clean(
    plan: dict,
    *,
    idx: IdIndex,
    max_inline: int,
    allow_charts: bool,
    hero_min: float,
    inline_min: float,
    chart_min: float,
) -> ValidationResult:
    """Independently validate a media plan. Drops invalid/over-budget optional
    assets (recording why in warnings); flags an invalid hero as an error so the
    caller falls back to the client hero image. Enforces: ≤ max_inline inline
    assets, ≤ 1 chart, unique asset_ids + filenames, real placement anchors,
    filename rules, and confidence thresholds."""
    result = ValidationResult()
    plan = plan if isinstance(plan, dict) else {}

    hero, hero_errs = _normalize_hero(plan.get("hero_image") or {}, hero_min=hero_min)
    result.hero = hero
    result.hero_ok = hero is not None
    if hero_errs:
        result.errors.extend(hero_errs)

    raw_inline = plan.get("inline_assets")
    raw_inline = raw_inline if isinstance(raw_inline, list) else []

    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    charts_kept = 0
    for asset in raw_inline:
        if len(result.inline) >= max_inline:
            result.warnings.append("dropped_asset_over_inline_budget")
            continue
        norm, skip = _normalize_inline(
            asset, idx=idx, inline_min=inline_min, chart_min=chart_min, allow_charts=allow_charts
        )
        if norm is None:
            result.warnings.append(f"dropped_{(asset or {}).get('asset_id', '?')}:{skip}")
            continue
        if norm["asset_id"] in seen_ids:
            result.warnings.append(f"dropped_duplicate_asset_id:{norm['asset_id']}")
            continue
        if norm["filename"] in seen_files:
            result.warnings.append(f"dropped_duplicate_filename:{norm['filename']}")
            continue
        if norm["asset_type"] == "chart":
            if charts_kept >= 1:
                result.warnings.append("dropped_second_chart")
                continue
            charts_kept += 1
        seen_ids.add(norm["asset_id"])
        seen_files.add(norm["filename"])
        result.inline.append(norm)

    return result


def _as_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
