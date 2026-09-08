"""Social Media module — the AI image renderer (PRD §7).

Generate one on-brand, per-platform social image with **Nano Banana Pro**
(Gemini 3 Pro Image) and store it in the media store (R2) for the composer to
attach to a post. Pro-only for v1: the Pro model passes an ``aspectRatio`` so
the image matches the platform's native shape (Reels/Stories 9:16, Pinterest
2:3, Instagram feed 4:5, X/YouTube 16:9, else 1:1) — the 2.5-Flash renderer
(``nano_banana.generate_image``) can only produce 1:1.

Paid external call: the estimated cost is **reserved against the fail-closed
social budget before spending** (like every other paid social call). Stateless —
returns a media URL for the composer; nothing is persisted until publish.

Pure helpers (``resolve_aspect_ratio``, ``build_image_prompt``, ``ext_for_mime``)
are unit-tested; ``generate_image`` isolates the DB + budget + Gemini + R2.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from config import settings

logger = logging.getLogger(__name__)

# Aspect ratios Nano Banana Pro (gemini-3-pro-image-preview) accepts. NOTE the
# seeded social_platform_specs use "1.91:1", which Gemini does NOT support, so
# the platform→ratio choice is a deliberate mapping, not a raw spec read.
GEMINI_ASPECT_RATIOS = frozenset(
    {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
)

# mime → storage extension (media_store.IMAGE_TYPES keys), default png.
_MIME_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


# ── pure helpers (no network / DB — unit-tested) ─────────────────────────────

def resolve_aspect_ratio(platform: str, fmt: str) -> str:
    """The Gemini-supported aspect ratio for a platform + format. Vertical
    formats (reel/story) are 9:16 everywhere; otherwise per-platform native.
    Pure — always returns a value in GEMINI_ASPECT_RATIOS."""
    p = (platform or "").lower()
    f = (fmt or "feed").lower()
    if f in ("reel", "story"):
        return "9:16"
    if p == "pinterest":
        return "2:3"
    if p == "instagram":
        return "4:5"
    if p in ("twitter", "x", "youtube"):
        return "16:9"
    return "1:1"


def ext_for_mime(mime: str) -> str:
    """Storage extension for a returned image mime type (default png). Pure."""
    return _MIME_EXT.get((mime or "").lower().split(";")[0].strip(), "png")


def build_image_prompt(
    description: str, client: Optional[dict], policy_template: Optional[str]
) -> str:
    """Assemble the image-generation prompt. When the client's Social Policy sets
    an ``image_prompt_template`` it drives the look (``{description}`` is
    substituted, else the description is appended); otherwise a light default
    style guidance is added. The business name grounds brand consistency. Pure."""
    desc = (description or "").strip()
    tmpl = (policy_template or "").strip()
    name = (client or {}).get("name") if client else None

    if tmpl:
        if "{description}" in tmpl:
            body = tmpl.replace("{description}", desc)
        else:
            body = f"{tmpl}\n\n{desc}" if desc else tmpl
    else:
        body = desc

    parts: list[str] = []
    if name:
        parts.append(f"On-brand social media image for {name}.")
    if body:
        parts.append(body)
    if not tmpl:
        parts.append(
            "Professional, high-quality and visually appealing. Do not include "
            "text, logos, or watermarks unless explicitly described above."
        )
    return "\n".join(p for p in parts if p).strip()


# ── impure layer ─────────────────────────────────────────────────────────────

def _assert_enabled() -> None:
    if not settings.social_enabled:
        raise HTTPException(status_code=503, detail="social_not_enabled")


def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


def _client_row(client_id: str) -> dict:
    rows = (
        _sb().table("clients").select("id, name").eq("id", client_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="client_not_found")
    return rows[0]


def _policy_template(client_id: str) -> Optional[str]:
    try:
        rows = (
            _sb().table("social_policy").select("image_prompt_template")
            .eq("client_id", client_id).limit(1).execute()
        ).data or []
        return (rows[0].get("image_prompt_template") if rows else None) or None
    except Exception as exc:  # noqa: BLE001 — best-effort; a missing policy is fine
        logger.info("social.policy_template_read_failed", extra={"error": str(exc)[:200]})
        return None


async def generate_image(client_id: str, req, user_id: Optional[str] = None) -> dict:
    """Generate one platform-native social image and store it. Reserves the
    estimated cost against the client's monthly social budget FIRST (fail-closed),
    then calls Nano Banana Pro and uploads the result to the media store. Returns
    {"url", "type", "aspect_ratio", "cost_usd"}. Stateless."""
    _assert_enabled()
    from services import nano_banana
    from services.social import budget
    from services.social.media_store import get_media_store, media_key

    platform = (req.platform or "").lower()
    fmt = (req.format or "feed")
    description = (req.description or "").strip()
    if not description:
        raise HTTPException(status_code=422, detail="social_image_description_required")

    if req.aspect_ratio:
        ar = req.aspect_ratio.strip()
        if ar not in GEMINI_ASPECT_RATIOS:
            raise HTTPException(status_code=422, detail=f"social_bad_aspect_ratio:{ar}")
    else:
        ar = resolve_aspect_ratio(platform, fmt)

    if not nano_banana.is_configured():
        raise HTTPException(status_code=503, detail="social_image_not_configured")

    client = _client_row(client_id)
    prompt = build_image_prompt(description, client, _policy_template(client_id))

    # Reserve the estimated cost before spending it (fail-closed backstop).
    est = float(settings.social_image_cost_usd)
    cap = budget.ceiling_for_client(client_id)
    if not budget.reserve(client_id, est, cap=cap):
        raise HTTPException(status_code=402, detail="social_image_budget_exceeded")

    out = await nano_banana.generate_image_pro(
        prompt, aspect_ratio=ar, image_size=settings.social_image_size
    )
    if not out:
        # The reservation stands (the estimate was spent attempting generation);
        # the composer surfaces a retry. Over-charge on a rare failure is ~$0.13.
        raise HTTPException(status_code=502, detail="social_image_generation_failed")

    data, mime = out
    ext = ext_for_mime(mime)
    content_type = mime if (mime or "").startswith("image/") else "image/png"
    url = get_media_store().put_bytes(media_key(ext, "generated"), data, content_type)
    logger.info("social.image_generated", extra={"client_id": client_id, "aspect_ratio": ar})
    return {"url": url, "type": "image", "aspect_ratio": ar, "cost_usd": round(est, 4)}
