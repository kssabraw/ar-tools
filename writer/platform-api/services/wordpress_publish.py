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
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

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


async def publish_to_wordpress(
    *,
    client: dict,
    title: str,
    html: str,
    status: str = "draft",
    content_type: str = "blog_post",
) -> dict:
    """Create a post/page on the client's WordPress site; returns
    {post_id, link, status, edit_link}.

    `client` is the clients row (must carry wordpress_site_url/username/
    app_password). `html` is the rendered post body. Raises WordPressPublishError
    on missing config, a bad status, or a transport/API failure."""
    if status not in ALLOWED_STATUSES:
        raise WordPressPublishError("invalid_status")
    if not client_is_configured(client):
        raise WordPressPublishError("wordpress_not_configured")
    if not (html or "").strip():
        raise WordPressPublishError("content_is_empty")

    rest_base = _rest_base(client["wordpress_site_url"])
    resource = _POST_TYPE_BY_CONTENT.get(content_type, "posts")
    url = f"{rest_base}/{resource}"
    headers = {
        "Authorization": _auth_header(
            client["wordpress_username"], client["wordpress_app_password"]
        ),
        "Content-Type": "application/json",
    }
    body = {"title": title, "content": html, "status": status}

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as http:
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
    }
