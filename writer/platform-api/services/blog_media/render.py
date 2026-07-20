"""Image rendering for the media pipeline — gpt-image-2 → WebP bytes.

gpt-image-2 is a reasoning image model: it reads the (article-grounded) prompt
the planner authored and renders one image. Per the addendum, rendering has a
bounded retry ladder (same prompt once, then a simplified prompt once) and never
raises into the orchestrator — a failed asset is handled by the caller's policy
(hero → client fallback image; inline → dropped).
"""
from __future__ import annotations

import base64
import logging

from config import settings

logger = logging.getLogger(__name__)

_CONTENT_BUCKET = "wordpress_images"


async def _generate(prompt: str, size: str, quality: str) -> bytes:
    """One gpt-image-2 call → decoded image bytes. Requests WebP output."""
    import openai

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    kwargs = {
        "model": settings.blog_media_image_model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
    }
    # WebP output is supported by gpt-image models; tolerate an SDK that predates
    # the param by retrying without it.
    try:
        resp = await client.images.generate(**kwargs, output_format="webp")
    except TypeError:
        resp = await client.images.generate(**kwargs)
    b64 = resp.data[0].b64_json
    if not b64:
        raise RuntimeError("image_generation_empty_response")
    return base64.b64decode(b64)


def _simplify(prompt: str) -> str:
    """A shorter fallback prompt that preserves the main subject + no-text rule.
    Keeps the first ~2 sentences and the trailing prohibition line."""
    parts = [p.strip() for p in prompt.split(".") if p.strip()]
    head = ". ".join(parts[:2])
    return (
        f"{head}. Clean, modern, professional editorial illustration, one clear "
        "focal point. No readable words, letters, numbers, logos, trademarks, "
        "captions, signatures, or watermarks."
    )


async def render_image(prompt: str, *, width: int, height: int, quality: str | None = None) -> bytes | None:
    """Render one image with a bounded retry ladder. Returns WebP bytes, or None
    if every attempt fails (best-effort — never raises).

    Ladder: authored@requested-size → authored@requested-size (transient retry)
    → authored@auto (catches an API-rejected size, which would otherwise fail
    every identical attempt) → simplified@auto."""
    if not settings.openai_api_key or not (prompt or "").strip():
        return None
    size = f"{width}x{height}"
    q = quality or settings.blog_media_image_quality
    attempts = [(prompt, size), (prompt, size), (prompt, "auto"), (_simplify(prompt), "auto")]
    for i, (p, s) in enumerate(attempts):
        try:
            return _ensure_webp(await _generate(p, s, q))
        except Exception as exc:  # noqa: BLE001 — best-effort per addendum
            logger.warning(
                "blog_media.render_failed",
                extra={"attempt": i + 1, "size": s, "simplified": i == 3, "error": str(exc)},
            )
    return None


def _ensure_webp(data: bytes) -> bytes:
    """Normalize rendered bytes to WebP. If the API returned another format (the
    output_format fallback path can yield PNG), convert via Pillow when available
    (it ships with the WeasyPrint stack); otherwise return the bytes unchanged —
    browsers content-sniff images, so a mislabeled extension still renders."""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return data
    try:
        from io import BytesIO

        from PIL import Image  # lazy — present via the WeasyPrint dependency

        img = Image.open(BytesIO(data))
        out = BytesIO()
        img.save(out, format="WEBP", quality=88)
        return out.getvalue()
    except Exception:  # noqa: BLE001 — conversion is best-effort
        return data


def upload_preview(data: bytes, filename: str) -> str | None:
    """Upload rendered bytes to the public content bucket for a stable preview
    URL (also the run's featured_image_url on non-GitHub surfaces). Best-effort."""
    import uuid as _uuid

    from db.supabase_client import get_supabase

    supabase = get_supabase()
    safe = filename if filename.endswith(".webp") else f"{filename}.webp"
    key = f"blog/{_uuid.uuid4().hex}-{safe}"
    try:
        supabase.storage.from_(_CONTENT_BUCKET).upload(
            key, data, {"content-type": "image/webp", "upsert": "true"}
        )
        return supabase.storage.from_(_CONTENT_BUCKET).get_public_url(key).rstrip("?")
    except Exception as exc:  # noqa: BLE001 — preview is non-fatal
        logger.warning("blog_media.preview_upload_failed", extra={"error": str(exc)})
        return None


def upload_svg_preview(svg: str, filename: str) -> str | None:
    """Upload a rendered chart SVG to the content bucket for a preview URL. The
    committed repo `.svg` is the real artifact; this is just for the review UI.
    Best-effort."""
    import uuid as _uuid

    from db.supabase_client import get_supabase

    supabase = get_supabase()
    safe = filename if filename.endswith(".svg") else f"{filename}.svg"
    key = f"blog/{_uuid.uuid4().hex}-{safe}"
    try:
        supabase.storage.from_(_CONTENT_BUCKET).upload(
            key, svg.encode("utf-8"), {"content-type": "image/svg+xml", "upsert": "true"}
        )
        return supabase.storage.from_(_CONTENT_BUCKET).get_public_url(key).rstrip("?")
    except Exception as exc:  # noqa: BLE001 — preview is non-fatal
        logger.warning("blog_media.svg_preview_upload_failed", extra={"error": str(exc)})
        return None
