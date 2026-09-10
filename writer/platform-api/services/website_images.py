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
     "neighborhood", "local_landing", "hyper_local", "post", "pillar"}
)

# Informational page types are NEVER geo-targeted (SOP / reference §5.3), so
# their hero prompt and alt text carry no city — a pillar or blog post about a
# topic must not be pinned to one place.
_NEVER_GEO_PAGE_TYPES = frozenset({"post", "pillar"})


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
    tone = brand_tone(client)
    return f"{base}, {tone[:80]}" if tone else base


def brand_tone(client: dict) -> str:
    """The client's tone, from where the brand-voice blob actually keeps it.

    `brand_voice` nests the structured voice under `current_voice` (or
    `recommended_voice`) — the same precedence `brand_voice_service` uses. Reading
    `brand_voice["tone"]` off the top level, as this did, finds nothing for every
    real client, so the tone never reached the prompt and the whole set rendered
    in the generic house style.
    """
    voice = client.get("brand_voice")
    if not isinstance(voice, dict):
        return ""
    for blob in (voice.get("current_voice"), voice.get("recommended_voice"), voice):
        if isinstance(blob, dict):
            tone = blob.get("tone") or blob.get("summary")
            if isinstance(tone, str) and tone.strip():
                return tone.strip()
    return ""


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
    elif page_type in _NEVER_GEO_PAGE_TYPES:
        scene = f"an editorial scene illustrating: {subject}"
    else:
        scene = f"a real-world scene of {subject}"
    where = f" in {city}" if city and page_type not in _NEVER_GEO_PAGE_TYPES else ""

    return f"{scene}{where}. {style}"


def alt_text(page: dict, *, city: str) -> str:
    subject = (page.get("title") or "").strip() or "the business"
    page_type = page.get("page_type") or ""
    where = f" in {city}" if city and page_type not in _NEVER_GEO_PAGE_TYPES else ""
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


# --------------------------------------------------------------------------
# User-uploaded project / case-study photos
# --------------------------------------------------------------------------
#
# A case study's photos are real job photos the operator supplies. v1 pasted a
# URL straight into the page, which committed an EXTERNAL url into the site — it
# can rot, hotlink-block, or point somewhere private. This re-hosts every photo
# (uploaded file OR pasted URL) into the same public bucket the heroes use, so a
# project's imagery is a stable, self-hosted URL the deployed site can always
# fetch. Interactive (raises HTTPException) rather than best-effort like the
# hero: a photo the operator explicitly added should fail loudly if it can't be
# stored, not silently vanish.

PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
PHOTO_MAX_BYTES = 15 * 1024 * 1024
PHOTO_MIN_PX = 200

# PIL's `Image.format` → our stored content type, so a wrong/missing upload
# header (common) is corrected from the real decoded format.
_FORMAT_TO_TYPE = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def photo_rejection_reason(
    content_type: str, width: int, height: int, size_bytes: int
) -> Optional[str]:
    """Why a project photo would be rejected, or None if it's fine. Pure
    (unit-tested). A modest floor: real image, not a 1px tracking gif, not a
    25 MB RAW — this is web imagery on a live page, not an archive."""
    if (content_type or "").lower() not in PHOTO_TYPES:
        return "unsupported_image_type"
    if size_bytes <= 0:
        return "empty_image"
    if size_bytes > PHOTO_MAX_BYTES:
        return "image_too_large"
    if width < PHOTO_MIN_PX or height < PHOTO_MIN_PX:
        return "image_dimensions_too_small"
    return None


def _decode_image(data: bytes) -> tuple[str, int, int]:
    """(content_type, width, height) sniffed from the bytes themselves. Raises
    HTTPException(422) on anything PIL can't open as a supported image."""
    from fastapi import HTTPException

    try:
        import io  # lazy

        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
            width, height = im.size
    except Exception:  # noqa: BLE001 — a non-decodable upload is a bad image
        raise HTTPException(status_code=422, detail="invalid_image")
    ct = _FORMAT_TO_TYPE.get(fmt)
    if not ct:
        raise HTTPException(status_code=422, detail="unsupported_image_type")
    return ct, width, height


def _store_photo(website_id: str, data: bytes, content_type: str) -> str:
    """Validate the sniffed image and upload it under this site's project prefix.
    Returns the durable public URL. Raises HTTPException on any rejection."""
    from fastapi import HTTPException
    from uuid import uuid4

    if not data:
        raise HTTPException(status_code=422, detail="empty_image")
    ct, width, height = _decode_image(data)
    reason = photo_rejection_reason(ct, width, height, len(data))
    if reason:
        raise HTTPException(status_code=413 if reason == "image_too_large" else 422, detail=reason)

    from db.supabase_client import get_supabase

    path = f"website-projects/{website_id}/{uuid4()}.{PHOTO_TYPES[ct]}"
    supabase = get_supabase()
    try:
        supabase.storage.from_(_BUCKET).upload(
            path, data, {"content-type": ct, "upsert": "true"}
        )
        return supabase.storage.from_(_BUCKET).get_public_url(path).rstrip("?")
    except Exception as exc:  # noqa: BLE001
        logger.error("website_images.photo_upload_failed", extra={"error": str(exc)[:200]})
        raise HTTPException(status_code=502, detail="image_upload_failed")


def upload_project_photo(website_id: str, data: bytes, content_type: str) -> str:
    """Store an uploaded project photo in the public bucket, returning its URL.

    The declared `content_type` is only a hint — the real format is sniffed from
    the bytes, so a mislabeled upload is stored under its true type.
    """
    return _store_photo(website_id, data, content_type)


async def import_project_photo_from_url(website_id: str, url: str) -> str:
    """Fetch a project photo from a public URL and re-host it in the public
    bucket — so a pasted URL becomes a stable self-hosted asset like an upload,
    rather than an external link committed into the site. Raises HTTPException."""
    from fastapi import HTTPException

    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="invalid_image_url")

    import httpx  # lazy

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            resp = await http.get(
                u, headers={"User-Agent": "Mozilla/5.0 (compatible; ar-tools/1.0)"}
            )
    except Exception as exc:  # noqa: BLE001
        logger.info("website_images.photo_url_fetch_failed", extra={"url": u[:200], "error": str(exc)[:200]})
        raise HTTPException(status_code=502, detail="image_fetch_failed")
    if resp.status_code != 200 or not resp.content:
        raise HTTPException(status_code=502, detail="image_fetch_failed")
    # _store_photo sniffs the real format, so the fetched Content-Type is unused.
    return _store_photo(website_id, resp.content, resp.headers.get("content-type", ""))
