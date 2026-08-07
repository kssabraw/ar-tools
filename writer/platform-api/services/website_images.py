"""Website Builder — a hero image for the pages that show one.

The template renders `heroImage` as a plain `<img src=…>` and makes the whole
slot disappear when it is absent, so imagery here is purely additive: a page
without one is a page that looks unfinished, never one that fails to build.

Delivery is an absolute URL to the public bucket, the same shape the suite's
blog illustrator already ships (`illustration.py`). It is deliberately NOT
committed into the site repo the way the theme's fonts are: a hero render is
1–2 MB and there is one per page, so committing them would bloat every repo by
tens of megabytes and re-upload them to Cloudflare on every deploy — whereas a
20 KB font, shared across the whole site, earned self-hosting. The trade is that
a generated site references our bucket for its imagery; acceptable for v1, and
revisitable if a site needs to be fully self-contained.

Everything is best-effort and double-gated (`website_images_enabled` + an image
API key). A generation failure, a missing key, or the flag being off all leave
the page exactly as it was — with no hero, which the template already handles.
The renderer itself is reused from `illustration.py` so the suite has one image
model to maintain, not two.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

# The public bucket the blog illustrator already writes to; reused rather than
# minting a new one, since these images are served straight to the browser.
_BUCKET = "wordpress_images"

# Page types that render a hero image. About and contact deliberately do not —
# about leads with a PageHeader and prose, contact with the NAP block, and a
# stock hero on either reads as filler. Kept as data so "which pages get art" is
# one obvious list rather than a condition scattered across the writer.
HERO_PAGE_TYPES = frozenset(
    {"home", "service", "sub_service", "brand_service", "location",
     "neighborhood", "local_landing", "hyper_local", "post"}
)


def wants_hero(page_type: str) -> bool:
    return page_type in HERO_PAGE_TYPES


def _enabled() -> bool:
    """On only when switched on AND a renderer key exists.

    The key check is what lets the website-builder flag be turned on without
    silently starting to spend on images — a bulk-create of 40 pages is 40
    renders, so this stays opt-in on its own axis.
    """
    return bool(settings.website_images_enabled and settings.openai_api_key)


def brand_style_suffix(client: dict) -> str:
    """A fixed style tail so every page's hero reads as one set.

    Photographic rather than illustrated: a local business's service pages want
    to look like real work, not vector art (which is the blog illustrator's
    house style). The client's brand tone nudges it when present.
    """
    base = (
        "professional editorial photograph, natural light, realistic, high detail, "
        "no text, no words, no logos, no watermarks"
    )
    voice = client.get("brand_voice")
    if isinstance(voice, dict):
        tone = voice.get("tone") or voice.get("summary")
        if isinstance(tone, str) and tone.strip():
            return f"{base}, {tone.strip()[:80]}"
    return base


def build_prompt(page: dict, *, business: str, city: str, style: str) -> str:
    """A literal, brand-safe scene for one page.

    Deterministic — no art-direction LLM call — because a hero here is
    decoration, not the deliverable, and the page's own subject (its title, and
    for a local page its city) is a good enough brief. The rules mirror the blog
    illustrator's: depict a scene, never text or a logo, so the render cannot
    invent a fake sign or a garbled brand mark.
    """
    subject = (page.get("title") or page.get("route") or "the business").strip()
    page_type = page.get("page_type") or ""

    if page_type == "home":
        scene = f"the work and setting of {business or subject}"
    elif page_type == "post":
        scene = f"an editorial scene illustrating: {subject}"
    else:
        scene = f"a real-world scene of {subject}"
    where = f" in {city}" if city and page_type != "post" else ""

    return f"{scene}{where}. {style}"


def alt_text(page: dict, *, city: str) -> str:
    subject = (page.get("title") or "").strip() or "the business"
    where = f" in {city}" if city and (page.get("page_type") or "") != "post" else ""
    return f"{subject}{where}"[:160]


def storage_key(website_id: str, page_id: str) -> str:
    # One image per page; a regenerate overwrites (upsert) rather than piling up.
    return f"website/{website_id}/{page_id}.png"


# --------------------------------------------------------------------------
# Impure
# --------------------------------------------------------------------------


async def _render(prompt: str) -> Optional[bytes]:
    """The image bytes for a prompt, via the suite's one image renderer."""
    from services.illustration import _generate_image  # the proven gpt-image-1 path

    return await _generate_image(prompt)


def _upload(supabase, key: str, png: bytes) -> Optional[str]:
    try:
        supabase.storage.from_(_BUCKET).upload(
            key, png, {"content-type": "image/png", "upsert": "true"}
        )
        url = supabase.storage.from_(_BUCKET).get_public_url(key)
        return url if isinstance(url, str) and url else None
    except Exception as exc:  # noqa: BLE001 — best-effort decoration
        logger.warning("website_images.upload_failed", extra={"key": key, "error": str(exc)[:200]})
        return None


async def generate_hero(
    *, page: dict, client: dict, website: dict, business: str, city: str
) -> Optional[dict]:
    """Render + host one hero image → `{heroImage, heroImageAlt}` or None.

    Returns None (never raises) whenever imagery is off, unsupported for this
    page type, or anything in the render/upload path fails — the caller treats
    None as "ship the page without a hero", which is a valid, finished state.
    """
    if not _enabled() or not wants_hero(page.get("page_type") or ""):
        return None
    try:
        prompt = build_prompt(page, business=business, city=city, style=brand_style_suffix(client))
        png = await _render(prompt)
        if not png:
            return None
        url = _upload(get_supabase_storage(website), storage_key(website["id"], page["id"]), png)
        if not url:
            return None
        return {"heroImage": url, "heroImageAlt": alt_text(page, city=city)}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "website_images.hero_failed",
            extra={"page_id": page.get("id"), "error": str(exc)[:200]},
        )
        return None


def get_supabase_storage(_website: dict):
    # Indirection kept tiny so the impure path has one seam to patch in tests.
    from db.supabase_client import get_supabase

    return get_supabase()
