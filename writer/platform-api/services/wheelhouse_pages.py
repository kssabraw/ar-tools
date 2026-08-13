"""WheelHouse IT — location/service Page hierarchy publisher.

Publishes a 3-level tree of standard WordPress **Pages** (not a custom post
type): State → City → Service, linked by the page ``parent`` field so the URLs
nest with no post-type prefix (``/florida/miami/managed-it/``). Only the leaf
(Service) page carries on-page copy — 33 ACF fields written under the WP REST
``acf`` object; State/City are lightweight title+slug hub pages whose layout an
Elementor template supplies.

The core routine is **"ensure the path, then upsert the leaf"**: parent ids are
resolved at runtime by ``slug + parent`` lookup (never hardcoded), created as
draft hubs when missing, and the leaf is found by ``slug + parent`` and updated
in place if it exists — so re-running a combo never duplicates.

Reuses the low-level WordPress helpers from ``wordpress_publish`` (Basic auth
with the client's Application Password, permalink fallback, bot-wall/JSON error
mapping). This module adds only Pages-specific pieces: a slug lookup, the
``parent`` field, and the ``acf`` payload. All calls are server-side — the app
password lives only on the ``clients`` row and never reaches the browser.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional
from urllib.parse import urlparse

import httpx

from config import settings
from services.wordpress_publish import (
    WordPressPublishError,
    _auth_header,
    _default_headers,
    _publisher_header,
    _rest_base,
    _rest_create,
    client_is_configured,
    edit_link_for,
)

logger = logging.getLogger(__name__)

# WP page statuses this module exposes. Default draft so nothing goes live
# unreviewed (matches the build spec's "never publish unless explicitly chosen").
ALLOWED_STATUSES = {"draft", "publish"}


def slugify(text: str) -> str:
    """Turn a state/city/service name into a WordPress URL slug.

    Lowercases, strips accents, replaces any run of non-alphanumeric characters
    with a single hyphen, and trims leading/trailing hyphens. Deterministic and
    pure so it is unit-testable and produces the same slug the WP-side lookup
    keys on (slugs are unique per parent)."""
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower().strip()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    return ascii_text.strip("-")


def _rest_context(client: dict) -> tuple[str, str, dict]:
    """Return (rest_base, site_root, headers) for the client's WP Pages API.

    Raises WordPressPublishError on missing/invalid config."""
    if not client_is_configured(client):
        raise WordPressPublishError("wordpress_not_configured")
    rest_base = _rest_base(client["wordpress_site_url"])
    site_root = rest_base.rsplit("/wp-json", 1)[0]
    auth = _auth_header(client["wordpress_username"], client["wordpress_app_password"])
    headers = {
        "Authorization": auth,
        "Content-Type": "application/json",
        "Accept": "application/json",
        **_publisher_header(),
    }
    return rest_base, site_root, headers


def _pages_urls(rest_base: str, site_root: str, page_id: Optional[int] = None) -> tuple[str, str]:
    """(primary, fallback) URLs for the pages endpoint (create) or a single page
    (update). The fallback is the ``?rest_route=`` form that works when the site's
    permalinks are "Plain" and the pretty /wp-json/ route 404s / returns HTML."""
    if page_id is None:
        return f"{rest_base}/pages", f"{site_root}/?rest_route=/wp/v2/pages"
    return (
        f"{rest_base}/pages/{page_id}",
        f"{site_root}/?rest_route=/wp/v2/pages/{page_id}",
    )


async def _get_page_by_slug(
    http: httpx.AsyncClient, rest_base: str, headers: dict, slug: str, parent: int
) -> Optional[dict]:
    """Find a page by ``slug`` under ``parent`` (any status). Returns the first
    match ``{id, slug, status, parent, link}`` or None.

    Slugs are unique *per parent*, so both are required to identify a page. Reads
    only — safe in dry-run."""
    params = {
        "slug": slug,
        "parent": parent,
        "status": "any",
        "_fields": "id,slug,status,parent,link",
    }
    try:
        resp = await http.get(f"{rest_base}/pages", params=params, headers=headers)
    except Exception as exc:  # noqa: BLE001 — transport failure
        logger.error("wheelhouse_lookup_failed slug=%s parent=%s error=%s", slug, parent, str(exc))
        raise WordPressPublishError("wordpress_call_failed") from exc
    if resp.status_code in (401, 403):
        raise WordPressPublishError("wordpress_auth_failed")
    if resp.status_code == 404:
        # Some hosts 404 the pretty route; retry the ?rest_route= form once.
        site_root = rest_base.rsplit("/wp-json", 1)[0]
        try:
            resp = await http.get(
                f"{site_root}/?rest_route=/wp/v2/pages",
                params={k: v for k, v in params.items() if k != "_fields"},
                headers=headers,
            )
        except Exception as exc:  # noqa: BLE001
            raise WordPressPublishError("wordpress_rest_api_unreachable") from exc
    if resp.status_code >= 400:
        raise WordPressPublishError(f"wordpress_http_error_{resp.status_code}")
    try:
        items = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise WordPressPublishError("wordpress_rest_not_json") from exc
    if not isinstance(items, list) or not items:
        return None
    # Guard against a fuzzy match: WP's slug filter is exact, but be strict.
    for it in items:
        if isinstance(it, dict) and it.get("slug") == slug:
            return it
    return items[0] if isinstance(items[0], dict) else None


async def ensure_page(
    http: httpx.AsyncClient,
    rest_base: str,
    site_root: str,
    headers: dict,
    *,
    slug: str,
    title: str,
    parent: int,
    hub_status: str = "draft",
) -> dict:
    """Idempotent ensure(slug, title, parent) → ``{id, created, link}``.

    Returns the existing page's id when one already exists under ``parent`` (never
    touches its status/title — hubs are curated by hand once created), else
    creates a lightweight hub page and returns the new id. Used for the State and
    City levels of the tree."""
    hit = await _get_page_by_slug(http, rest_base, headers, slug, parent)
    if hit and hit.get("id"):
        return {"id": int(hit["id"]), "created": False, "link": hit.get("link")}
    primary, fallback = _pages_urls(rest_base, site_root)
    body = {"title": title, "slug": slug, "parent": parent, "status": hub_status}
    result = await _rest_create(http, primary, fallback, body, headers, "pages")
    if not isinstance(result, dict) or not result.get("id"):
        raise WordPressPublishError("wordpress_unexpected_response")
    return {"id": int(result["id"]), "created": True, "link": result.get("link")}


async def _upsert_leaf(
    http: httpx.AsyncClient,
    rest_base: str,
    site_root: str,
    headers: dict,
    *,
    slug: str,
    title: str,
    parent: int,
    status: str,
    acf: dict,
) -> dict:
    """Find the leaf (service) page by ``slug + parent`` and update it in place,
    else create it. Carries the 33 ACF fields under the REST ``acf`` object.
    Returns the raw WP page dict."""
    hit = await _get_page_by_slug(http, rest_base, headers, slug, parent)
    body: dict = {"title": title, "slug": slug, "parent": parent, "status": status, "acf": acf}
    if hit and hit.get("id"):
        primary, fallback = _pages_urls(rest_base, site_root, int(hit["id"]))
        result = await _rest_create(http, primary, fallback, body, headers, "pages")
        created = False
    else:
        primary, fallback = _pages_urls(rest_base, site_root)
        result = await _rest_create(http, primary, fallback, body, headers, "pages")
        created = True
    if not isinstance(result, dict) or not result.get("id"):
        raise WordPressPublishError("wordpress_unexpected_response")
    result["_created"] = created
    return result


def build_slug_path(state_slug: str, city_slug: str, service_slug: str) -> str:
    """The nested URL path for a leaf, e.g. ``/florida/miami/managed-it/``."""
    return f"/{state_slug}/{city_slug}/{service_slug}/"


async def publish_leaf(
    *,
    client: dict,
    state: str,
    city: str,
    service: str,
    title: str,
    acf: dict,
    status: str = "draft",
    hub_status: str = "draft",
    state_slug: Optional[str] = None,
    city_slug: Optional[str] = None,
    service_slug: Optional[str] = None,
) -> dict:
    """Ensure the State→City parent chain, then upsert the Service leaf with its
    ACF fields. Returns a report dict::

        {wp_state_id, wp_city_id, wp_page_id, created (leaf), state_created,
         city_created, slug_path, link, edit_link, status}

    Raises WordPressPublishError on missing config, a bad status, or a
    transport/API failure. All calls are server-side."""
    if status not in ALLOWED_STATUSES:
        raise WordPressPublishError("invalid_status")
    state_slug = state_slug or slugify(state)
    city_slug = city_slug or slugify(city)
    service_slug = service_slug or slugify(service)
    if not (state_slug and city_slug and service_slug):
        raise WordPressPublishError("invalid_slug")

    rest_base, site_root, headers = _rest_context(client)
    try:
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=False, headers=_default_headers()
        ) as http:
            state_hub = await ensure_page(
                http, rest_base, site_root, headers,
                slug=state_slug, title=state, parent=0, hub_status=hub_status,
            )
            city_hub = await ensure_page(
                http, rest_base, site_root, headers,
                slug=city_slug, title=city, parent=state_hub["id"], hub_status=hub_status,
            )
            leaf = await _upsert_leaf(
                http, rest_base, site_root, headers,
                slug=service_slug, title=title, parent=city_hub["id"],
                status=status, acf=acf,
            )
    except WordPressPublishError:
        raise
    except Exception as exc:  # noqa: BLE001 — transport (connect/timeout/TLS)
        logger.error("wheelhouse_publish_failed error=%s", str(exc))
        raise WordPressPublishError("wordpress_call_failed") from exc

    leaf_id = int(leaf["id"])
    return {
        "wp_state_id": state_hub["id"],
        "wp_city_id": city_hub["id"],
        "wp_page_id": leaf_id,
        "state_created": state_hub["created"],
        "city_created": city_hub["created"],
        "created": bool(leaf.get("_created")),
        "slug_path": build_slug_path(state_slug, city_slug, service_slug),
        "link": leaf.get("link"),
        "edit_link": edit_link_for(client["wordpress_site_url"], leaf_id),
        "status": leaf.get("status", status),
    }


async def dry_run_leaf(
    *,
    client: dict,
    state: str,
    city: str,
    service: str,
    title: str,
    acf: dict,
    status: str = "draft",
    state_slug: Optional[str] = None,
    city_slug: Optional[str] = None,
    service_slug: Optional[str] = None,
) -> dict:
    """Assemble + resolve the parent chain and return the exact payloads that
    *would* be POSTed, with **zero write calls**. Parent ids are resolved by
    read-only slug lookups when WP is configured (so the chain is accurate),
    otherwise reported as "would create". No POST is ever issued."""
    state_slug = state_slug or slugify(state)
    city_slug = city_slug or slugify(city)
    service_slug = service_slug or slugify(service)
    slug_path = build_slug_path(state_slug, city_slug, service_slug)

    leaf_payload = {
        "title": title, "slug": service_slug, "parent": "<cityId>",
        "status": status, "acf": acf,
    }
    chain = {
        "state": {"slug": state_slug, "title": state, "parent": 0, "existing_id": None},
        "city": {"slug": city_slug, "title": city, "parent": "<stateId>", "existing_id": None},
        "service": {"slug": service_slug, "title": title, "parent": "<cityId>", "existing_id": None},
    }

    resolved = False
    if client_is_configured(client):
        try:
            rest_base, _site_root, headers = _rest_context(client)
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=False, headers=_default_headers()
            ) as http:
                state_hit = await _get_page_by_slug(http, rest_base, headers, state_slug, 0)
                state_id = int(state_hit["id"]) if state_hit and state_hit.get("id") else None
                chain["state"]["existing_id"] = state_id
                city_id = None
                if state_id is not None:
                    city_hit = await _get_page_by_slug(http, rest_base, headers, city_slug, state_id)
                    city_id = int(city_hit["id"]) if city_hit and city_hit.get("id") else None
                    chain["city"]["parent"] = state_id
                    chain["city"]["existing_id"] = city_id
                if city_id is not None:
                    leaf_hit = await _get_page_by_slug(http, rest_base, headers, service_slug, city_id)
                    chain["service"]["parent"] = city_id
                    chain["service"]["existing_id"] = (
                        int(leaf_hit["id"]) if leaf_hit and leaf_hit.get("id") else None
                    )
                    leaf_payload["parent"] = city_id
            resolved = True
        except WordPressPublishError as exc:
            logger.info("wheelhouse_dryrun_lookup_skipped reason=%s", str(exc))
        except Exception as exc:  # noqa: BLE001 — best-effort; dry-run must not fail on reads
            logger.info("wheelhouse_dryrun_lookup_error error=%s", str(exc))

    return {
        "slug_path": slug_path,
        "chain": chain,
        "leaf_payload": leaf_payload,
        "parents_resolved": resolved,
        "writes": 0,
    }
