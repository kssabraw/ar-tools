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

import httpx

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
    promote: bool = False,
) -> dict:
    """Idempotent ensure(slug, title, parent) → ``{id, created, promoted, link}``.

    Returns the existing page's id when one already exists under ``parent``, else
    creates a lightweight hub page. When ``promote`` is set and the target status
    is ``publish``, an existing DRAFT ancestor is promoted to publish — otherwise
    a live leaf under a draft ancestor would 404 (WordPress won't serve a
    published child under a draft parent). Title is never rewritten. Used for the
    State and City levels of the tree."""
    hit = await _get_page_by_slug(http, rest_base, headers, slug, parent)
    if hit and hit.get("id"):
        page_id = int(hit["id"])
        promoted = False
        if promote and hub_status == "publish" and hit.get("status") not in ("publish", None):
            primary, fallback = _pages_urls(rest_base, site_root, page_id)
            await _rest_create(http, primary, fallback, {"status": "publish"}, headers, "pages")
            promoted = True
        return {"id": page_id, "created": False, "promoted": promoted, "link": hit.get("link")}
    primary, fallback = _pages_urls(rest_base, site_root)
    body = {"title": title, "slug": slug, "parent": parent, "status": hub_status}
    result = await _rest_create(http, primary, fallback, body, headers, "pages")
    if not isinstance(result, dict) or not result.get("id"):
        raise WordPressPublishError("wordpress_unexpected_response")
    return {"id": int(result["id"]), "created": True, "promoted": False, "link": result.get("link")}


def acf_write_ok(sent_acf: dict, returned_acf) -> bool:
    """Heuristic: did the ACF write actually land?

    WordPress echoes a populated ``acf`` object in the response only when the field
    group is Show-in-REST AND assigned to this post type. If we sent non-empty ACF
    and the response carries no ``acf``, the key was silently dropped (a
    misconfigured field group — exactly the WP-side prerequisite) and the page was
    created/updated with empty content. Pure — unit-tested."""
    sent_nonempty = any(isinstance(v, str) and v.strip() for v in (sent_acf or {}).values())
    if not sent_nonempty:
        return True
    return bool(returned_acf)


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
    result["_acf_ok"] = acf_write_ok(acf, result.get("acf"))
    return result


def build_slug_path(*slugs: str) -> str:
    """The nested URL path for a page, e.g. ``build_slug_path("florida","miami")``
    → ``/florida/miami/``. Variadic so it serves any hierarchy depth (a 2-level
    city page or a 3-level service page)."""
    return "/" + "/".join(s for s in slugs if s) + "/"


async def publish_hierarchy(
    *, client: dict, levels: list[dict], acf: dict, status: str = "draft",
) -> dict:
    """Ensure the ancestor hubs, then upsert the leaf (last level) with its ACF.

    ``levels`` is an ordered list ``[{"slug","title"}, …]`` top→down; every level
    but the last is a hub (created/reused, and promoted to publish when going live
    so the nested URL resolves), and the last carries the ACF payload. One engine
    drives every page_type — a 2-level city page or a 3-level service page.

    Returns ``{ancestor_ids, wp_page_id, created, slug_path, link, edit_link,
    status, acf_written, hubs_promoted}``. Raises WordPressPublishError on missing
    config, a bad status, or a transport/API failure. Server-side only."""
    if status not in ALLOWED_STATUSES:
        raise WordPressPublishError("invalid_status")
    if not levels or any(not (lvl.get("slug") or "") for lvl in levels):
        raise WordPressPublishError("invalid_slug")

    hub_status = status
    promote = status == "publish"
    rest_base, site_root, headers = _rest_context(client)
    try:
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=False, headers=_default_headers()
        ) as http:
            parent = 0
            ancestors: list[dict] = []
            for lvl in levels[:-1]:
                hub = await ensure_page(
                    http, rest_base, site_root, headers,
                    slug=lvl["slug"], title=(lvl.get("title") or lvl["slug"]), parent=parent,
                    hub_status=hub_status, promote=promote,
                )
                parent = hub["id"]
                ancestors.append(hub)
            leaf_lvl = levels[-1]
            leaf = await _upsert_leaf(
                http, rest_base, site_root, headers,
                slug=leaf_lvl["slug"], title=(leaf_lvl.get("title") or leaf_lvl["slug"]), parent=parent,
                status=status, acf=acf,
            )
    except WordPressPublishError:
        raise
    except Exception as exc:  # noqa: BLE001 — transport (connect/timeout/TLS)
        logger.error("wheelhouse_publish_failed error=%s", str(exc))
        raise WordPressPublishError("wordpress_call_failed") from exc

    leaf_id = int(leaf["id"])
    return {
        "ancestor_ids": [a["id"] for a in ancestors],
        "wp_page_id": leaf_id,
        "created": bool(leaf.get("_created")),
        "slug_path": build_slug_path(*[lvl["slug"] for lvl in levels]),
        "link": leaf.get("link"),
        "edit_link": edit_link_for(client["wordpress_site_url"], leaf_id),
        "status": leaf.get("status", status),
        "acf_written": bool(leaf.get("_acf_ok", True)),
        "hubs_promoted": any(a.get("promoted") for a in ancestors),
    }


async def dry_run_hierarchy(
    *, client: dict, levels: list[dict], acf: dict, status: str = "draft",
) -> dict:
    """Resolve the parent chain read-only and return the exact would-POST leaf
    payload + the per-level chain, with **zero writes**. Depth-agnostic — the
    ``chain`` is a list top→down. Parent ids resolve when WP is configured; a
    missing ancestor stops resolution there (deeper levels read as "would
    create")."""
    slugs = [lvl.get("slug") or "" for lvl in levels]
    slug_path = build_slug_path(*slugs)
    chain = [
        {"slug": lvl.get("slug"), "title": lvl.get("title"),
         "parent": 0 if i == 0 else "<parentId>", "existing_id": None}
        for i, lvl in enumerate(levels)
    ]
    leaf_payload = {
        "title": levels[-1].get("title") if levels else None,
        "slug": slugs[-1] if slugs else None,
        "parent": "<parentId>", "status": status, "acf": acf,
    }
    resolved = False
    if levels and client_is_configured(client):
        try:
            rest_base, _site_root, headers = _rest_context(client)
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=False, headers=_default_headers()
            ) as http:
                parent = 0
                for i, lvl in enumerate(levels):
                    hit = await _get_page_by_slug(http, rest_base, headers, lvl["slug"], parent)
                    hit_id = int(hit["id"]) if hit and hit.get("id") else None
                    chain[i]["parent"] = parent
                    chain[i]["existing_id"] = hit_id
                    if i == len(levels) - 1:
                        leaf_payload["parent"] = parent
                    if hit_id is None:
                        break  # can't resolve deeper without this ancestor
                    parent = hit_id
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
