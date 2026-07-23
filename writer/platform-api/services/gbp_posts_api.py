"""Google Business Profile **Posts** API — the v4 ``localPosts`` surface.

Posts live only on the legacy-but-active **Google My Business API (v4)**
(``mybusiness.googleapis.com/v4``) — the v1 split APIs (Account Management /
Business Information / Performance) never got a posts resource. v4 is NOT in
Google's discovery service, so this is plain REST (httpx + a service-account
bearer token) rather than ``googleapiclient.discovery.build``.

Auth reuses the agency service account already used for GSC + GBP metrics
(``gbp_performance_service._credentials()``, ``business.manage`` scope). The
client onboards by adding the SA's ``client_email`` as a **Manager** on their
Business Profile — the same "add this email" step as GSC.

The pure builders/parsers/classifiers (no Google dependency) are unit-tested;
the live calls are synchronous (httpx.Client) and meant to be run via
``asyncio.to_thread`` from the async job runners. On a non-2xx they raise an
``HTTPException`` whose ``detail`` is a classified code the runner records.

See: docs/modules/gbp-posts-module-prd-v1_0.md §2, §7.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import HTTPException

from config import settings

logger = logging.getLogger(__name__)

_V4_BASE = "https://mybusiness.googleapis.com/v4"
_TIMEOUT = 45

# The post topic types we offer in the composer. ALERT is Google-initiated only
# (excluded). 'product' is OUR type, not a Google one: Google's localPosts API
# has no PRODUCT topicType and no public product-post API (products live in the
# GBP Product Editor), so a 'product' post publishes as a product-framed STANDARD
# ("What's New") post — see _TOPIC_TO_API and the module PRD.
TOPIC_TYPES = ("standard", "event", "offer", "product")
# Our topic_type → the v4 API's topicType enum.
_TOPIC_TO_API = {
    "standard": "STANDARD",
    "product": "STANDARD",  # product-framed Update (no PRODUCT topicType exists)
    "event": "EVENT",
    "offer": "OFFER",
}
# Call-to-action action types the v4 API accepts. CALL uses the listing's
# phone number and carries no URL.
CTA_TYPES = ("book", "order", "shop", "learn_more", "sign_up", "call")
_CTA_NO_URL = {"call"}


# ---------------------------------------------------------------------------
# Pure helpers (no Google dependency) — unit-tested.
# ---------------------------------------------------------------------------
def v4_parent(account_id: str, location_id: str) -> str:
    """Combine the stored ``accounts/{a}`` + ``locations/{l}`` into the v4
    parent ``accounts/{a}/locations/{l}``. Accepts bare ids or full forms.

    v4 keys on account+location together, unlike the Performance API which keys
    on ``locations/{id}`` alone — so both stored columns are needed.
    """
    acct = (account_id or "").strip().strip("/")
    loc = (location_id or "").strip().strip("/")
    if not acct or not loc:
        raise ValueError("account_id and location_id are required")
    acct = acct if acct.startswith("accounts/") else f"accounts/{acct.split('/')[-1]}"
    loc = loc if loc.startswith("locations/") else f"locations/{loc.split('/')[-1]}"
    return f"{acct}/{loc}"


def append_utm(url: Optional[str], campaign: str) -> Optional[str]:
    """Append gbp post UTM params to a CTA URL (idempotent, http(s) only).

    Adds ``utm_source=gbp&utm_medium=post&utm_campaign=<slug>`` so post→site
    clicks are attributable. Existing utm_* params are preserved (never
    overwritten). Non-http URLs and falsy input pass through untouched.
    """
    if not url:
        return url
    value = url.strip()
    if not (value.startswith("http://") or value.startswith("https://")):
        return value
    slug = re.sub(r"[^a-z0-9]+", "-", (campaign or "").strip().lower()).strip("-") or "gbp"
    try:
        parts = urlsplit(value)
        existing = dict(parse_qsl(parts.query, keep_blank_values=True))
        defaults = {"utm_source": "gbp", "utm_medium": "post", "utm_campaign": slug}
        for k, v in defaults.items():
            existing.setdefault(k, v)
        return urlunsplit(parts._replace(query=urlencode(existing)))
    except ValueError:
        return value


def build_call_to_action(cta_type: Optional[str], cta_url: Optional[str]) -> Optional[dict]:
    """Build the ``callToAction`` block, or None. Raises ValueError on a bad type
    or a missing URL where one is required (every type except CALL)."""
    if not cta_type:
        return None
    kind = cta_type.strip().lower()
    if kind not in CTA_TYPES:
        raise ValueError(f"invalid cta_type: {cta_type}")
    action = {"actionType": kind.upper()}
    if kind in _CTA_NO_URL:
        return action
    if not (cta_url or "").strip():
        raise ValueError("cta_url is required for this call-to-action")
    action["url"] = cta_url.strip()
    return action


def build_local_post_body(
    *,
    summary: str,
    topic_type: str = "standard",
    cta_type: Optional[str] = None,
    cta_url: Optional[str] = None,
    event: Optional[dict] = None,
    offer: Optional[dict] = None,
    media: Optional[list] = None,
    language_code: str = "en-US",
) -> dict:
    """Assemble a v4 ``LocalPost`` request body from our internal fields.

    Validates: summary length (<= gbp_post_max_chars), topic type, CTA, and the
    EVENT/OFFER requirement of an ``event`` block with a title. ``media`` is a
    list of ``{"sourceUrl": "..."}`` (a public, Google-fetchable image URL) —
    mapped to the API's ``{mediaFormat: PHOTO, sourceUrl}``. Raises ValueError on
    any invalid input so the caller returns a clean 400.
    """
    body_summary = (summary or "").strip()
    if not body_summary:
        raise ValueError("summary is required")
    if len(body_summary) > settings.gbp_post_max_chars:
        raise ValueError(f"summary exceeds {settings.gbp_post_max_chars} characters")
    kind = (topic_type or "standard").strip().lower()
    if kind not in TOPIC_TYPES:
        raise ValueError(f"invalid topic_type: {topic_type}")

    body: dict = {
        "languageCode": language_code or "en-US",
        "summary": body_summary,
        "topicType": _TOPIC_TO_API[kind],
    }
    cta = build_call_to_action(cta_type, cta_url)
    if cta:
        body["callToAction"] = cta

    if kind in ("event", "offer"):
        if not event or not (event.get("title") or "").strip():
            raise ValueError("event.title is required for EVENT and OFFER posts")
        if not event.get("schedule"):
            raise ValueError("event.schedule is required for EVENT and OFFER posts")
        body["event"] = event
    if kind == "offer" and offer:
        body["offer"] = offer

    if media:
        items = []
        for m in media:
            src = (m.get("sourceUrl") if isinstance(m, dict) else None) or ""
            if src.strip():
                items.append({"mediaFormat": "PHOTO", "sourceUrl": src.strip()})
        if items:
            body["media"] = items
    return body


def state_to_status(google_state: Optional[str]) -> str:
    """Map Google's LocalPost ``state`` to our post status enum."""
    s = (google_state or "").strip().upper()
    if s == "LIVE":
        return "live"
    if s == "REJECTED":
        return "rejected"
    # PROCESSING (or unknown) — still settling.
    return "publishing"


def parse_local_post(payload: dict) -> dict:
    """Map a v4 ``LocalPost`` response to the fields we persist."""
    payload = payload or {}
    topic = (payload.get("topicType") or "STANDARD").strip().lower()
    return {
        "google_name": payload.get("name"),
        "google_state": payload.get("state"),
        "status": state_to_status(payload.get("state")),
        "search_url": payload.get("searchUrl"),
        "summary": payload.get("summary"),
        "topic_type": topic if topic in TOPIC_TYPES else "standard",
        "create_time": payload.get("createTime"),
        "update_time": payload.get("updateTime"),
    }


def classify_post_error(status_code: Optional[int], message: str = "") -> str:
    """Map an HTTP status + error message from a v4 call to an actionable code."""
    msg = (message or "").lower()
    if status_code == 403 and ("has not been used" in msg or "is disabled" in msg):
        return "gbp_api_not_enabled"
    if status_code == 429 or "resource_exhausted" in msg or "quota" in msg:
        return "gbp_quota_not_granted"
    if status_code in (401, 403):
        return "service_account_not_a_manager_or_forbidden"
    if status_code == 400:
        return "invalid_post_content"
    if status_code == 404:
        return "post_or_location_not_found"
    return f"http_{status_code}" if status_code else "unknown_error"


# ---------------------------------------------------------------------------
# Live calls (synchronous; run via asyncio.to_thread from async runners).
# ---------------------------------------------------------------------------
def is_configured() -> bool:
    """Whether the GBP API layer + Posts feature are both enabled and the
    service-account key is present. Every live call no-ops-with-error otherwise."""
    from services import gbp_performance_service as gbp  # lazy: no google import at module load

    return bool(
        settings.gbp_api_enabled
        and settings.gbp_posts_enabled
        and gbp.gsc_service.is_configured()
    )


def _access_token() -> str:
    """Mint a bearer token from the shared service-account creds (business.manage)."""
    from google.auth.transport.requests import Request  # lazy Google import

    from services import gbp_performance_service as gbp

    creds = gbp._credentials()
    creds.refresh(Request())
    return creds.token


def _headers() -> dict:
    return {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"}


def _raise_for(resp: httpx.Response) -> None:
    """Raise an HTTPException with a classified detail on a non-2xx response."""
    if resp.status_code < 400:
        return
    try:
        message = (resp.json().get("error") or {}).get("message", "")
    except Exception:  # noqa: BLE001 — body may not be JSON
        message = resp.text[:300]
    code = classify_post_error(resp.status_code, message)
    logger.info("gbp_posts_api.error", extra={"status": resp.status_code, "code": code})
    raise HTTPException(status_code=502, detail=code)


def create_post(parent: str, body: dict) -> dict:
    """POST a new local post. Returns the parsed created post."""
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(f"{_V4_BASE}/{parent}/localPosts", headers=_headers(), json=body)
    _raise_for(resp)
    return parse_local_post(resp.json())


def list_posts(parent: str, page_size: int = 100) -> list[dict]:
    """List a location's local posts (first page — newest first). Parsed."""
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(
            f"{_V4_BASE}/{parent}/localPosts",
            headers=_headers(),
            params={"pageSize": page_size},
        )
    _raise_for(resp)
    return [parse_local_post(p) for p in (resp.json().get("localPosts") or [])]


def get_post(name: str) -> dict:
    """GET one local post by resource name. Parsed."""
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(f"{_V4_BASE}/{name}", headers=_headers())
    _raise_for(resp)
    return parse_local_post(resp.json())


def patch_post(name: str, body: dict, update_mask: str) -> dict:
    """PATCH an existing local post (edit). ``update_mask`` is a comma-separated
    field list (e.g. 'summary,callToAction'). Returns the parsed post."""
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.patch(
            f"{_V4_BASE}/{name}",
            headers=_headers(),
            params={"updateMask": update_mask},
            json=body,
        )
    _raise_for(resp)
    return parse_local_post(resp.json())


def delete_post(name: str) -> None:
    """DELETE a local post by resource name. 404 is treated as already-gone."""
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.delete(f"{_V4_BASE}/{name}", headers=_headers())
    if resp.status_code == 404:
        return
    _raise_for(resp)
