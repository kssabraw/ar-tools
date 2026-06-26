"""WordPress publishing — shared helper around the WP REST API.

Publishes finished content straight to a client's WordPress site using an
Application Password (WordPress core 5.6+, no plugin). Authentication is HTTP
Basic auth (`username:application_password`); one POST to
`<site>/wp-json/wp/v2/{posts|pages}` creates the post and returns its id + link.

Per-client credentials (`wordpress_site_url`, `wordpress_username`,
`wordpress_app_password`) live on the `clients` row. The app password is a
secret — it is read here server-side only and never logged or returned to the
frontend.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import posixpath
import re
from typing import Optional
from urllib.parse import unquote, urlparse

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Matches an <img> tag's src URL (single or double quoted), capturing the URL so
# it can be rewritten to the WP-hosted media URL after sideloading.
_IMG_SRC_RE = re.compile(r"""(<img\b[^>]*?\bsrc=["'])([^"']+)(["'])""", re.IGNORECASE)
_DEFAULT_IMAGE_MIME = "image/jpeg"

# WP statuses we expose. Default to draft so nothing goes live unreviewed.
ALLOWED_STATUSES = {"draft", "publish"}
# content_type → WP REST resource. Blog posts become posts; the conversion-
# focused landing pages (service/location/local SEO) become pages.
_POST_TYPE_BY_CONTENT = {
    "blog_post": "posts",
    "service_page": "pages",
    "location_page": "pages",
    "local_seo_page": "pages",
}


class WordPressPublishError(RuntimeError):
    """Raised when a client's WP config is missing/invalid or the API call fails.

    Callers map the string code to their own error envelope (HTTP route or job).
    """


def client_is_configured(client: dict) -> bool:
    return bool(
        client.get("wordpress_site_url")
        and client.get("wordpress_username")
        and client.get("wordpress_app_password")
    )


def _rest_base(site_url: str) -> str:
    parsed = urlparse(site_url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise WordPressPublishError("invalid_wordpress_site_url")
    if parsed.scheme != "https":
        # WP rejects Application Passwords over plain HTTP by default.
        raise WordPressPublishError("wordpress_site_url_must_be_https")
    return f"{parsed.scheme}://{parsed.netloc}/wp-json/wp/v2"


def _auth_header(username: str, app_password: str) -> str:
    # WP accepts the application password with or without its display spaces.
    token = base64.b64encode(f"{username}:{app_password}".encode()).decode()
    return f"Basic {token}"


def _filename_and_mime(url: str, content_type: Optional[str]) -> tuple[str, str]:
    """Derive a media filename + MIME from the source URL and response type."""
    mime = (content_type or "").split(";")[0].strip().lower()
    if not mime.startswith("image/"):
        mime = ""
    path = urlparse(url).path
    name = posixpath.basename(unquote(path)) or "image"
    # Ensure the filename carries an extension WP will accept.
    if "." not in name:
        ext = mimetypes.guess_extension(mime) if mime else None
        name = f"{name}{ext or '.jpg'}"
    if not mime:
        guessed, _ = mimetypes.guess_type(name)
        mime = guessed if (guessed or "").startswith("image/") else _DEFAULT_IMAGE_MIME
    return name, mime


async def _upload_media(
    http: httpx.AsyncClient, rest_base: str, auth: str, img_bytes: bytes, filename: str, mime: str
) -> Optional[dict]:
    """Upload one image to the WP media library; returns {id, source_url} or None
    on any failure (sideloading is best-effort — a failed image must not abort
    the publish)."""
    headers = {
        "Authorization": auth,
        "Content-Type": mime,
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    try:
        resp = await http.post(f"{rest_base}/media", content=img_bytes, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — best-effort; log and skip this image
        logger.warning("wordpress_media_upload_failed", extra={"filename": filename, "error": str(exc)})
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    return {"id": data.get("id"), "source_url": data.get("source_url")}


async def _sideload_one(
    http: httpx.AsyncClient, rest_base: str, auth: str, url: str
) -> Optional[dict]:
    """Download a single external image URL and upload it to the WP media
    library; returns {id, source_url} or None on any failure (best-effort)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    try:
        resp = await http.get(url, follow_redirects=True)
        resp.raise_for_status()
        img_bytes = resp.content
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("wordpress_image_fetch_failed", extra={"src": url, "error": str(exc)})
        return None
    if len(img_bytes) > settings.wordpress_media_max_bytes:
        logger.warning("wordpress_image_too_large", extra={"src": url, "bytes": len(img_bytes)})
        return None
    filename, mime = _filename_and_mime(url, resp.headers.get("content-type"))
    return await _upload_media(http, rest_base, auth, img_bytes, filename, mime)


async def _sideload_images(
    http: httpx.AsyncClient, rest_base: str, auth: str, html: str, site_host: str
) -> tuple[str, Optional[int]]:
    """Upload each referenced image to the client's WP media library, rewrite the
    <img> src to the WP-hosted URL, and return (rewritten_html, featured_media_id).

    Best-effort and bounded: images already on the client's WP host are skipped,
    each unique source is uploaded once, and at most `wordpress_media_max_images`
    images (each ≤ `wordpress_media_max_bytes`) are processed. Any per-image
    failure leaves that image's original src untouched."""
    max_images = settings.wordpress_media_max_images
    if max_images <= 0:
        return html, None

    seen: dict[str, Optional[str]] = {}  # original src → WP source_url (or None if skipped)
    featured_id: Optional[int] = None
    uploaded = 0

    matches = list(_IMG_SRC_RE.finditer(html))
    for m in matches:
        src = m.group(2)
        if src in seen:
            continue
        parsed = urlparse(src)
        # Only sideload absolute http(s) images not already on the WP host.
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            seen[src] = None
            continue
        if parsed.netloc.lower() == site_host.lower():
            seen[src] = None
            continue
        if uploaded >= max_images:
            seen[src] = None
            continue

        try:
            img_resp = await http.get(src, follow_redirects=True)
            img_resp.raise_for_status()
            img_bytes = img_resp.content
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("wordpress_image_fetch_failed", extra={"src": src, "error": str(exc)})
            seen[src] = None
            continue
        if len(img_bytes) > settings.wordpress_media_max_bytes:
            logger.warning("wordpress_image_too_large", extra={"src": src, "bytes": len(img_bytes)})
            seen[src] = None
            continue

        filename, mime = _filename_and_mime(src, img_resp.headers.get("content-type"))
        media = await _upload_media(http, rest_base, auth, img_bytes, filename, mime)
        if not media or not media.get("source_url"):
            seen[src] = None
            continue

        seen[src] = media["source_url"]
        uploaded += 1
        if featured_id is None:
            featured_id = media["id"]

    if not any(seen.values()):
        return html, featured_id

    def _replace(match: re.Match) -> str:
        new_url = seen.get(match.group(2))
        if not new_url:
            return match.group(0)
        return f"{match.group(1)}{new_url}{match.group(3)}"

    return _IMG_SRC_RE.sub(_replace, html), featured_id


async def publish_to_wordpress(
    *,
    client: dict,
    title: str,
    html: str,
    status: str = "draft",
    content_type: str = "blog_post",
    sideload_images: bool = True,
    featured_image_url: Optional[str] = None,
) -> dict:
    """Create a post/page on the client's WordPress site; returns
    {post_id, link, status, edit_link, featured_media}.

    `client` is the clients row (must carry wordpress_site_url/username/
    app_password). `html` is the rendered post body. When `sideload_images` is
    set, any images the content references are uploaded to the WP media library,
    the <img> srcs rewritten to the WP-hosted URLs, and (absent an explicit
    `featured_image_url`) the first becomes the post's featured image. An explicit
    `featured_image_url` is uploaded and set as the featured image regardless of
    body images. Raises WordPressPublishError on missing config, a bad status, or
    a transport/API failure."""
    if status not in ALLOWED_STATUSES:
        raise WordPressPublishError("invalid_status")
    if not client_is_configured(client):
        raise WordPressPublishError("wordpress_not_configured")
    if not (html or "").strip():
        raise WordPressPublishError("content_is_empty")

    rest_base = _rest_base(client["wordpress_site_url"])
    site_host = urlparse(client["wordpress_site_url"].strip()).netloc
    resource = _POST_TYPE_BY_CONTENT.get(content_type, "posts")
    url = f"{rest_base}/{resource}"
    auth = _auth_header(client["wordpress_username"], client["wordpress_app_password"])
    headers = {"Authorization": auth, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as http:
            featured_id: Optional[int] = None
            if sideload_images:
                # Best-effort: never let a media failure abort the publish.
                try:
                    # An explicit featured image takes precedence over body images.
                    if featured_image_url:
                        media = await _sideload_one(http, rest_base, auth, featured_image_url)
                        if media:
                            featured_id = media.get("id")
                    html, body_featured = await _sideload_images(
                        http, rest_base, auth, html, site_host
                    )
                    if featured_id is None:
                        featured_id = body_featured
                except Exception as exc:  # noqa: BLE001
                    logger.warning("wordpress_sideload_failed", extra={"error": str(exc)})

            body: dict = {"title": title, "content": html, "status": status}
            if featured_id:
                body["featured_media"] = featured_id

            response = await http.post(url, json=body, headers=headers)
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        logger.error(
            "wordpress_http_error",
            extra={"status": code, "body": exc.response.text[:300], "resource": resource},
        )
        if code in (401, 403):
            raise WordPressPublishError("wordpress_auth_failed") from exc
        if code == 404:
            raise WordPressPublishError("wordpress_rest_api_unreachable") from exc
        raise WordPressPublishError(f"wordpress_http_error_{code}") from exc
    except Exception as exc:
        logger.error("wordpress_call_failed", extra={"error": str(exc)})
        raise WordPressPublishError("wordpress_call_failed") from exc

    if not isinstance(result, dict) or not result.get("id"):
        raise WordPressPublishError("wordpress_unexpected_response")

    post_id = result.get("id")
    link = result.get("link")
    site_root = rest_base.rsplit("/wp-json", 1)[0]
    edit_link = f"{site_root}/wp-admin/post.php?post={post_id}&action=edit"
    return {
        "post_id": post_id,
        "link": link,
        "status": result.get("status", status),
        "edit_link": edit_link,
        "featured_media": result.get("featured_media") or None,
    }
