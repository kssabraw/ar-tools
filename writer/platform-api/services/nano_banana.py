"""Nano Banana — Gemini 2.5 Flash Image text-to-image generation.

A thin, reusable client over Google's ``generativelanguage`` ``generateContent``
for the image model nicknamed **"Nano Banana"** (``gemini-2.5-flash-image``).
Reuses the shared ``GEMINI_API_KEY`` already used for embeddings + brand scans —
no new vendor, no new key. First consumer is GBP post imagery; kept generic so
other surfaces (blog, ecommerce, website builder) can reuse it.

Pure ``extract_image_bytes`` (pull the inline image out of a response) is
unit-tested; the live call is best-effort and returns None on any failure.

Refs: ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-image
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def is_configured() -> bool:
    """Whether image generation can run (the shared Gemini key is set)."""
    return bool(settings.gemini_api_key)


def extract_image(response: dict) -> Optional[tuple[bytes, str]]:
    """Pull the first inline image out of a ``generateContent`` response as
    (bytes, mime_type), or None. Handles both camelCase (``inlineData``/
    ``mimeType``) and snake_case shapes. Pure (unit-tested)."""
    for cand in (response or {}).get("candidates") or []:
        for part in ((cand.get("content") or {}).get("parts") or []):
            inline = part.get("inlineData") or part.get("inline_data")
            if not inline:
                continue
            mime = inline.get("mimeType") or inline.get("mime_type") or ""
            data = inline.get("data")
            if mime.startswith("image/") and data:
                try:
                    return base64.b64decode(data), mime
                except (binascii.Error, ValueError):
                    return None
    return None


def extract_image_bytes(response: dict) -> Optional[bytes]:
    """The image bytes from a ``generateContent`` response, or None. Pure."""
    out = extract_image(response)
    return out[0] if out else None


async def generate_image(prompt: str, *, timeout: float = 60.0) -> Optional[bytes]:
    """Generate one image for a text prompt via Nano Banana. Returns the raw
    image bytes (PNG/JPEG), or None on any failure — best-effort, never raises."""
    if not is_configured() or not (prompt or "").strip():
        return None
    url = f"{_BASE}/{settings.nano_banana_model}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt[:4000]}]}],
        # The image model needs IMAGE in the requested modalities; TEXT is kept
        # so a refusal comes back as text rather than an empty error.
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            # Key via header, NOT ?key= in the URL (httpx logs request URLs → key leak).
            resp = await http.post(
                url, headers={"x-goog-api-key": settings.gemini_api_key}, json=body
            )
        if resp.status_code != 200:
            logger.warning(
                "nano_banana.http_error",
                extra={"status": resp.status_code, "body": resp.text[:300]},
            )
            return None
        return extract_image_bytes(resp.json())
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("nano_banana.failed", extra={"error": str(exc)[:200]})
        return None


async def generate_image_pro(
    prompt: str,
    *,
    aspect_ratio: Optional[str] = None,
    image_size: Optional[str] = None,
    timeout: float = 120.0,
) -> Optional[tuple[bytes, str]]:
    """Generate one image via **Nano Banana Pro** (Gemini 3 Pro Image), passing a
    per-platform ``aspectRatio`` (and optional ``imageSize``) through
    ``generationConfig.imageConfig`` — the 2.5-Flash ``generate_image`` above can
    only do 1:1. Returns (image bytes, mime_type), or None on any failure
    (best-effort, never raises). A longer default timeout: Pro at 2K/4K is slower."""
    if not is_configured() or not (prompt or "").strip():
        return None
    url = f"{_BASE}/{settings.nano_banana_pro_model}:generateContent"
    gen_config: dict = {"responseModalities": ["TEXT", "IMAGE"]}
    image_config: dict = {}
    if aspect_ratio:
        image_config["aspectRatio"] = aspect_ratio
    if image_size:
        image_config["imageSize"] = image_size
    if image_config:
        gen_config["imageConfig"] = image_config
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt[:4000]}]}],
        "generationConfig": gen_config,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.post(
                url, headers={"x-goog-api-key": settings.gemini_api_key}, json=body
            )
        if resp.status_code != 200:
            logger.warning(
                "nano_banana_pro.http_error",
                extra={"status": resp.status_code, "body": resp.text[:300]},
            )
            return None
        return extract_image(resp.json())
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("nano_banana_pro.failed", extra={"error": str(exc)[:200]})
        return None
