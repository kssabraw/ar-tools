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
import shlex
from typing import Optional
from urllib.parse import unquote, urlparse

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Matches an <img> tag's src URL (single or double quoted), capturing the URL so
# it can be rewritten to the WP-hosted media URL after sideloading.
_IMG_SRC_RE = re.compile(r"""(<img\b[^>]*?\bsrc=["'])([^"']+)(["'])""", re.IGNORECASE)
_DEFAULT_IMAGE_MIME = "image/jpeg"

# A leading <h1> (optionally wrapped in a Gutenberg heading block comment) at the
# very top of the body. When the on-page H1 is sent as the WP post title, the
# theme renders that title as the page's <h1>, so a body-level H1 would be a
# duplicate — we strip the first one.
_LEADING_H1_RE = re.compile(
    r"^\s*(?:<!--\s*wp:heading[^>]*-->\s*)?<h1\b[^>]*>.*?</h1>\s*(?:<!--\s*/wp:heading\s*-->\s*)?",
    re.IGNORECASE | re.DOTALL,
)

# Post-meta keys the major SEO plugins read for a post's meta-title override —
# each drives the <title> tag independently of the WordPress post title. We set
# every known key; only the one the site's installed plugin registered takes
# effect, and the rest are a no-op (the WP REST API silently ignores meta keys
# that aren't registered for the site). SEOPress (`_seopress_titles_title`) and
# Rank Math (`rank_math_title`) register their key for REST out of the box.
# Yoast (`_yoast_wpseo_title`) does NOT — its title meta isn't REST-writable by
# default, so on a stock Yoast site this key is ignored; it takes effect only
# when the site registers the key for REST (a one-time mu-plugin snippet).
_SEO_TITLE_META_KEYS = ("_seopress_titles_title", "rank_math_title", "_yoast_wpseo_title")


def _strip_leading_h1(html: str) -> str:
    """Remove a single leading <h1>…</h1> block from the body (best-effort)."""
    return _LEADING_H1_RE.sub("", html, count=1)


def _default_headers() -> dict:
    """Headers applied to every request in this module's httpx clients.

    The User-Agent is the point: httpx's default identifies us as a script, which
    managed WordPress hosts' bot filters challenge (see `wordpress_user_agent` in
    config for the failure this fixes). Set at the client level so the REST calls,
    the media uploads, and the source-image downloads all carry it."""
    return {"User-Agent": settings.wordpress_user_agent}


def _publisher_header() -> dict:
    """The fixed header identifying this tool, for requests to the client's own
    WordPress host only.

    Deliberately NOT part of `_default_headers`. The publish client also GETs
    source images from arbitrary third-party CDNs, so a client-level header
    would send this shared secret to every host we ever fetch an image from.
    Merged per-request instead, and only onto requests aimed at the client's
    site. Empty (header omitted entirely) until a value is configured."""
    value = (settings.wordpress_publisher_header_value or "").strip()
    if not value:
        return {}
    name = (settings.wordpress_publisher_header_name or "").strip()
    return {name: value} if name else {}


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
        **_publisher_header(),
    }
    try:
        resp = await http.post(f"{rest_base}/media", content=img_bytes, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — best-effort; log and skip this image
        logger.warning("wordpress_media_upload_failed", extra={"upload_filename": filename, "error": str(exc)})
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


def _looks_like_json(response: httpx.Response) -> bool:
    """True when a response body is JSON — by declared content-type, else by a
    leading `{`/`[` (some WP hosts mislabel JSON as text/html)."""
    ctype = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype in ("application/json", "text/json") or ctype.endswith("+json"):
        return True
    if ctype.startswith("text/") or ctype in ("", "application/octet-stream"):
        # Content-type is unhelpful — sniff the first non-space byte.
        head = (response.text or "").lstrip()[:1]
        return head in ("{", "[")
    return False


_LOGGED_HEADER_MAX = 600


def _header_summary(response: httpx.Response) -> str:
    """Render response headers onto a diagnostic log line.

    A managed host's bot filter is diagnosed from the response headers — the
    `set-cookie` a challenge issues, the edge's `server` and cache markers — and
    a host's support team will ask for them, so the failure paths carry them
    rather than status and body alone. Cookie *values* are reduced to the cookie
    name: that a cookie was set is the diagnostic signal, its value is not, and
    this keeps opaque tokens out of the logs. Bounded so a chatty edge can't
    flood the line.
    Never raises. This runs *inside* the failure paths, so an exception here
    would replace a specific, actionable error code with a generic one — the
    diagnostic must not be able to destroy the diagnosis."""
    try:
        headers = response.headers
        # httpx.Headers preserves repeated headers (a challenge sets several
        # cookies) via multi_items(); a plain mapping only has items().
        items = headers.multi_items() if hasattr(headers, "multi_items") else headers.items()
        parts: list[str] = []
        for key, value in items:
            if str(key).lower() == "set-cookie":
                value = f"{str(value).split('=', 1)[0]}=<redacted>"
            parts.append(f"{key}: {value}")
        return "; ".join(parts)[:_LOGGED_HEADER_MAX]
    except Exception:  # noqa: BLE001 — diagnostic only; never mask the real error
        return "<unavailable>"


async def _rest_create(
    http: httpx.AsyncClient,
    primary_url: str,
    fallback_url: str,
    body: dict,
    headers: dict,
    resource: str,
) -> dict:
    """POST a create request to the WP REST API and return the parsed JSON dict.

    Handles the common site-side breakages that used to surface only as an opaque
    `wordpress_call_failed`:
      * "Plain" permalinks (the pretty `/wp-json/` route 404s or serves the theme's
        HTML) — retried once against the `?rest_route=` form.
      * A reverse proxy / security plugin redirecting or returning an HTML page
        instead of JSON — raised as a specific, actionable code.

    Raises WordPressPublishError with a specific code; the caller maps it."""

    async def _post(target: str) -> httpx.Response:
        return await http.post(target, json=body, headers=headers)

    resp = await _post(primary_url)
    # Fall back to the ?rest_route= form when the pretty route can't serve JSON:
    # a redirect, a 404, or a 2xx/3xx that returned HTML (Plain permalinks).
    needs_fallback = (
        resp.is_redirect
        or resp.status_code == 404
        or (resp.status_code < 400 and not _looks_like_json(resp))
    )
    if needs_fallback and fallback_url != primary_url:
        # Log the primary response in full before it is discarded. When the
        # primary is an edge intercept rather than a permalink problem (a
        # challenge page served as 2xx), this is the only record of the first
        # of the two responses — the fallback's failure is logged below, but
        # without this the intercept that triggered it leaves no evidence.
        logger.info(
            "wordpress_rest_fallback resource=%s primary_status=%s headers=%s body=%s",
            resource, resp.status_code, _header_summary(resp), (resp.text or "")[:300],
        )
        resp = await _post(fallback_url)

    if resp.status_code in (401, 403):
        logger.error(
            "wordpress_http_error status=%s resource=%s headers=%s body=%s",
            resp.status_code, resource, _header_summary(resp), (resp.text or "")[:300],
        )
        raise WordPressPublishError("wordpress_auth_failed")
    if resp.status_code == 404:
        logger.error(
            "wordpress_http_error status=404 resource=%s headers=%s body=%s",
            resource, _header_summary(resp), (resp.text or "")[:300],
        )
        raise WordPressPublishError("wordpress_rest_api_unreachable")
    if resp.is_redirect:
        logger.error(
            "wordpress_rest_redirect status=%s resource=%s location=%s headers=%s",
            resp.status_code, resource, resp.headers.get("location", ""),
            _header_summary(resp),
        )
        raise WordPressPublishError("wordpress_rest_redirect")
    if resp.status_code >= 400:
        logger.error(
            "wordpress_http_error status=%s resource=%s headers=%s body=%s",
            resp.status_code, resource, _header_summary(resp), (resp.text or "")[:300],
        )
        raise WordPressPublishError(f"wordpress_http_error_{resp.status_code}")

    if not _looks_like_json(resp):
        logger.error(
            "wordpress_rest_not_json url=%s resource=%s content_type=%s headers=%s body=%s",
            str(resp.url), resource, resp.headers.get("content-type", ""),
            _header_summary(resp), (resp.text or "")[:300],
        )
        raise WordPressPublishError("wordpress_rest_not_json")
    try:
        parsed = resp.json()
    except Exception as exc:  # noqa: BLE001 — declared JSON but unparseable
        logger.error(
            "wordpress_rest_not_json url=%s resource=%s body=%s",
            str(resp.url), resource, (resp.text or "")[:300],
        )
        raise WordPressPublishError("wordpress_rest_not_json") from exc
    return parsed


_WP_CLI_TYPE = {"posts": "post", "pages": "page"}


def _ssh_enabled_for(client: dict) -> bool:
    """True when this client's publishing is routed over SSH + WP-CLI.

    Gated to explicit client ids: an interim workaround for one host's WAF must
    never silently become the default transport for every WordPress client."""
    ids = {i.strip() for i in (settings.wordpress_ssh_client_ids or "").split(",") if i.strip()}
    if not ids or str(client.get("id") or "") not in ids:
        return False
    if not (settings.wordpress_ssh_host and settings.wordpress_ssh_username
            and settings.wordpress_ssh_private_key and settings.wordpress_ssh_wp_path):
        logger.error("wordpress_ssh_enabled_but_unconfigured client_id=%s", client.get("id"))
        return False
    return True


def _ssh_private_key() -> str:
    """The configured private key, tolerating an escaped-newline PEM.

    A PEM is multi-line, and pasting one into a KEY=VALUE environment editor
    commonly flattens it into literal backslash-n sequences. A real PEM never
    contains a backslash, so unescaping is unambiguous and saves a confusing
    "invalid key" failure at publish time."""
    key = settings.wordpress_ssh_private_key or ""
    if "\\n" in key:
        key = key.replace("\\n", "\n")
    return key.strip() + "\n"


async def _publish_via_ssh(
    *,
    client: dict,
    title: str,
    html: str,
    status: str,
    content_type: str,
    slug: Optional[str],
    seo_title: Optional[str],
    featured_image_url: Optional[str],
) -> dict:
    """Create a post/page over SSH with WP-CLI, bypassing the REST API entirely.

    Returns the same dict as the REST path so callers are unaffected. The body is
    piped over stdin rather than embedded in the command, so the HTML never has
    to survive remote shell quoting; every interpolated value is shlex-quoted.

    Images are refused rather than silently dropped: the REST path sideloads them
    into the media library, and a post that publishes with dead external <img>
    srcs looks like a success while being materially wrong. A refusal surfaces
    through the caller's existing publish_error + notification path."""
    if _IMG_SRC_RE.search(html) or (featured_image_url or "").strip():
        # Covers BOTH body images and an explicitly-passed featured image. The
        # latter matters just as much: silently ignoring the argument would
        # publish a post the caller believes has a featured image and does not.
        raise WordPressPublishError("wordpress_ssh_images_unsupported")

    try:
        import asyncssh  # imported lazily: absent in environments that never use SSH
    except ImportError as exc:
        raise WordPressPublishError("wordpress_ssh_unavailable") from exc

    resource = _POST_TYPE_BY_CONTENT.get(content_type, "posts")
    post_type = _WP_CLI_TYPE.get(resource, "post")

    argv = [
        "wp", "post", "create", "-",
        f"--post_title={shlex.quote(title)}",
        f"--post_status={shlex.quote(status)}",
        f"--post_type={shlex.quote(post_type)}",
    ]
    if slug:
        argv.append(f"--post_name={shlex.quote(slug)}")
    argv.append("--porcelain")

    # Capture the new id, set the SEO meta-title if it differs, then echo the id
    # and the permalink so the caller gets the same fields the REST path returns.
    parts = [f"cd {shlex.quote(settings.wordpress_ssh_wp_path)}", f"ID=$({' '.join(argv)})"]
    meta_title = (seo_title or "").strip()
    if meta_title and meta_title.lower() != (title or "").strip().lower():
        for key in _SEO_TITLE_META_KEYS:
            parts.append(
                f"wp post meta update \"$ID\" {shlex.quote(key)} "
                f"{shlex.quote(meta_title)} >/dev/null 2>&1 || true"
            )
    parts.append('echo "$ID"')
    parts.append('wp post get "$ID" --field=link')
    command = " && ".join(parts)

    connect_kwargs: dict = {
        "port": settings.wordpress_ssh_port,
        "username": settings.wordpress_ssh_username,
        "client_keys": [asyncssh.import_private_key(_ssh_private_key())],
    }
    if settings.wordpress_ssh_known_host:
        connect_kwargs["known_hosts"] = ([settings.wordpress_ssh_known_host], [], [])
    else:
        logger.warning("wordpress_ssh_host_key_unverified host=%s", settings.wordpress_ssh_host)
        connect_kwargs["known_hosts"] = None

    try:
        async with asyncssh.connect(settings.wordpress_ssh_host, **connect_kwargs) as conn:
            result = await conn.run(command, input=html, check=False)
    except WordPressPublishError:
        raise
    except Exception as exc:  # noqa: BLE001 — connect/auth/transport
        logger.error("wordpress_ssh_connect_failed error=%s", str(exc), extra={"error": str(exc)})
        raise WordPressPublishError("wordpress_ssh_connect_failed") from exc

    if result.exit_status != 0:
        stderr = (str(result.stderr or ""))[:300]
        logger.error(
            "wordpress_ssh_wpcli_failed exit=%s stderr=%s", result.exit_status, stderr
        )
        raise WordPressPublishError(f"wordpress_ssh_wpcli_error_{result.exit_status}")

    lines = [ln.strip() for ln in str(result.stdout or "").splitlines() if ln.strip()]
    if not lines or not lines[0].isdigit():
        logger.error("wordpress_ssh_unexpected_output out=%s", str(result.stdout or "")[:300])
        raise WordPressPublishError("wordpress_unexpected_response")

    post_id = int(lines[0])
    link = lines[1] if len(lines) > 1 else None
    return {
        "post_id": post_id,
        "link": link,
        "status": status,
        "edit_link": edit_link_for(client["wordpress_site_url"], post_id),
        "featured_media": None,
    }


async def publish_to_wordpress(
    *,
    client: dict,
    title: str,
    html: str,
    status: str = "draft",
    content_type: str = "blog_post",
    sideload_images: bool = True,
    featured_image_url: Optional[str] = None,
    slug: Optional[str] = None,
    seo_title: Optional[str] = None,
    strip_leading_h1: bool = False,
) -> dict:
    """Create a post/page on the client's WordPress site; returns
    {post_id, link, status, edit_link, featured_media}.

    `client` is the clients row (must carry wordpress_site_url/username/
    app_password). `title` is the WordPress post title — the theme renders it as
    the page's visible <h1> — so callers should pass the on-page H1 here. `html`
    is the rendered post body. When `sideload_images` is set, any images the
    content references are uploaded to the WP media library, the <img> srcs
    rewritten to the WP-hosted URLs, and (absent an explicit `featured_image_url`)
    the first becomes the post's featured image. An explicit `featured_image_url`
    is uploaded and set as the featured image regardless of body images. `slug`
    pins the post's URL slug — without it WordPress derives one from the title,
    which breaks callers that pre-computed internal links against a known slug
    (the fanout writer).

    `seo_title` (when distinct from `title`) is written to the SEO plugin's
    meta-title field (SEOPress + Rank Math out of the box; Yoast when the site
    registers its key for REST) so the <title> tag / SERP result differs from the
    on-page H1; it is a no-op on sites without a supported SEO plugin.
    `strip_leading_h1` removes a duplicate H1 from the top of the body (the post
    title already supplies the page's H1).

    Raises WordPressPublishError on missing config, a bad status, or a
    transport/API failure."""
    if status not in ALLOWED_STATUSES:
        raise WordPressPublishError("invalid_status")
    if not client_is_configured(client):
        raise WordPressPublishError("wordpress_not_configured")
    if not (html or "").strip():
        raise WordPressPublishError("content_is_empty")
    if strip_leading_h1:
        html = _strip_leading_h1(html)

    # Routed here rather than at each call site so every caller — the scheduler,
    # the publish router, bulk publish — picks it up with no change.
    if _ssh_enabled_for(client):
        return await _publish_via_ssh(
            client=client, title=title, html=html, status=status,
            content_type=content_type, slug=slug, seo_title=seo_title,
            featured_image_url=featured_image_url,
        )

    rest_base = _rest_base(client["wordpress_site_url"])
    site_host = urlparse(client["wordpress_site_url"].strip()).netloc
    site_root = rest_base.rsplit("/wp-json", 1)[0]
    resource = _POST_TYPE_BY_CONTENT.get(content_type, "posts")
    url = f"{rest_base}/{resource}"
    # ?rest_route= form of the same endpoint — works even when the site's permalinks
    # are "Plain" (the pretty /wp-json/ route 404s / returns HTML in that case).
    fallback_url = f"{site_root}/?rest_route=/wp/v2/{resource}"
    auth = _auth_header(client["wordpress_username"], client["wordpress_app_password"])
    headers = {
        "Authorization": auth,
        "Content-Type": "application/json",
        # Ask for JSON explicitly: a host that intercepts the call is likelier to
        # pass through (or at least answer in kind) than when we accept anything.
        "Accept": "application/json",
        **_publisher_header(),
    }

    try:
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=False, headers=_default_headers()
        ) as http:
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
            if slug:
                body["slug"] = slug
            if featured_id:
                body["featured_media"] = featured_id
            # Route a distinct SEO/meta title to the site's SEO plugin (drives the
            # <title> tag separately from the post title / on-page H1). We set every
            # known plugin's key; the site keeps the one it recognizes.
            meta_title = (seo_title or "").strip()
            if meta_title and meta_title.lower() != (title or "").strip().lower():
                body["meta"] = {key: meta_title for key in _SEO_TITLE_META_KEYS}

            result = await _rest_create(http, url, fallback_url, body, headers, resource)
    except WordPressPublishError:
        raise                       # already a specific, actionable code — don't mask it
    except Exception as exc:
        # Transport-level failure (connect/timeout/TLS) — no HTTP response at all.
        logger.error("wordpress_call_failed error=%s", str(exc), extra={"error": str(exc)})
        raise WordPressPublishError("wordpress_call_failed") from exc

    if not isinstance(result, dict) or not result.get("id"):
        raise WordPressPublishError("wordpress_unexpected_response")

    post_id = result.get("id")
    link = result.get("link")
    edit_link = f"{site_root}/wp-admin/post.php?post={post_id}&action=edit"
    return {
        "post_id": post_id,
        "link": link,
        "status": result.get("status", status),
        "edit_link": edit_link,
        "featured_media": result.get("featured_media") or None,
    }


def edit_link_for(site_url: str, post_id) -> str:
    """The wp-admin edit URL for a post id (so a human can review/publish)."""
    site_root = _rest_base(site_url).rsplit("/wp-json", 1)[0]
    return f"{site_root}/wp-admin/post.php?post={post_id}&action=edit"


async def list_content(client: dict, *, per_page: int = 100, max_pages: int = 1000) -> list[dict]:
    """List the client's WordPress posts + pages for the internal-link inventory.

    Returns ``[{id, type ('posts'|'pages'), url, title, html, status}]`` — published
    items only (we only link real, live pages). Paginates the WP REST API; bounded
    by ``max_pages`` total items. Raises WordPressPublishError on missing config or
    an auth/transport failure (best-effort callers catch it)."""
    if not client_is_configured(client):
        raise WordPressPublishError("wordpress_not_configured")
    rest_base = _rest_base(client["wordpress_site_url"])
    auth = _auth_header(client["wordpress_username"], client["wordpress_app_password"])
    headers = {"Authorization": auth, "Accept": "application/json", **_publisher_header()}
    out: list[dict] = []
    try:
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=False, headers=_default_headers()
        ) as http:
            for resource in ("posts", "pages"):
                page = 1
                while len(out) < max_pages:
                    resp = await http.get(
                        f"{rest_base}/{resource}",
                        params={
                            "per_page": per_page, "page": page, "status": "publish",
                            "_fields": "id,link,title,content,status",
                        },
                        headers=headers,
                    )
                    if resp.status_code == 400:
                        break  # past the last page (WP returns 400 for page > total)
                    resp.raise_for_status()
                    items = resp.json()
                    if not isinstance(items, list) or not items:
                        break
                    for it in items:
                        out.append({
                            "id": it.get("id"),
                            "type": resource,
                            "url": it.get("link"),
                            "title": (it.get("title") or {}).get("rendered") or "",
                            "html": (it.get("content") or {}).get("rendered") or "",
                            "status": it.get("status"),
                        })
                    total_pages = int(resp.headers.get("X-WP-TotalPages") or 0)
                    if page >= total_pages or len(items) < per_page:
                        break
                    page += 1
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (401, 403):
            raise WordPressPublishError("wordpress_auth_failed") from exc
        if code == 404:
            raise WordPressPublishError("wordpress_rest_api_unreachable") from exc
        raise WordPressPublishError(f"wordpress_http_error_{code}") from exc
    except WordPressPublishError:
        raise
    except Exception as exc:
        logger.error("wordpress_list_failed", extra={"error": str(exc)})
        raise WordPressPublishError("wordpress_call_failed") from exc
    return out


async def update_post_content(
    client: dict, post_id, html: str, *, resource: str = "posts"
) -> dict:
    """Write new body ``html`` to an existing WP post/page, **preserving its
    status** (we don't send ``status``, so a published page stays published — this
    is the gated injection that runs only AFTER a human approved the edit).

    Returns ``{post_id, link, edit_link, modified}``. Raises WordPressPublishError
    on missing config or an auth/transport failure."""
    if not client_is_configured(client):
        raise WordPressPublishError("wordpress_not_configured")
    if not (html or "").strip():
        raise WordPressPublishError("content_is_empty")
    if resource not in ("posts", "pages"):
        resource = "posts"
    rest_base = _rest_base(client["wordpress_site_url"])
    auth = _auth_header(client["wordpress_username"], client["wordpress_app_password"])
    headers = {
        "Authorization": auth,
        "Content-Type": "application/json",
        # Ask for JSON explicitly: a host that intercepts the call is likelier to
        # pass through (or at least answer in kind) than when we accept anything.
        "Accept": "application/json",
        **_publisher_header(),
    }
    try:
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=False, headers=_default_headers()
        ) as http:
            resp = await http.post(  # WP accepts POST for updates to /{resource}/{id}
                f"{rest_base}/{resource}/{post_id}",
                json={"content": html},
                headers=headers,
            )
            resp.raise_for_status()
            result = resp.json()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        logger.error("wordpress_update_error",
                     extra={"status": code, "post_id": post_id, "body": exc.response.text[:300]})
        if code in (401, 403):
            raise WordPressPublishError("wordpress_auth_failed") from exc
        if code == 404:
            raise WordPressPublishError("wordpress_post_not_found") from exc
        raise WordPressPublishError(f"wordpress_http_error_{code}") from exc
    except WordPressPublishError:
        raise
    except Exception as exc:
        logger.error("wordpress_update_failed", extra={"post_id": post_id, "error": str(exc)})
        raise WordPressPublishError("wordpress_call_failed") from exc
    if not isinstance(result, dict) or not result.get("id"):
        raise WordPressPublishError("wordpress_unexpected_response")
    return {
        "post_id": result.get("id"),
        "link": result.get("link"),
        "edit_link": edit_link_for(client["wordpress_site_url"], result.get("id")),
        "modified": result.get("modified"),
    }
