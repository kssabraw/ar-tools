"""PostPeer implementation of the social posting adapter (ADR-0001, v1 provider).

Confirmed API facts (docs/modules/social-media-vendor-confirm-postpeer-v1_0.md §6,
docs/modules/social-media/CLAUDE.md — "Confirmed PostPeer facts"):

  - Base ``https://api.postpeer.dev/v1``; auth header ``x-access-key`` (one
    account-wide key — NOT a security boundary; client isolation is ours to
    enforce by always scoping to the client's ``profile_id``).
  - ``GET /health/auth`` verifies the key (free).
  - ``POST /profiles {name, description?}`` → ``{profile:{id}}`` (a PostPeer
    "Social group"); ``GET /profiles`` (page/limit).
  - ``GET /connect/{platform}?profileId=&redirectUri=&appId=`` → ``{url}``.
  - ``GET /connect/integrations?profileId=&platform=&limit=&offset=`` — paginate
    with offset/limit; each ``integration.id`` is the posting ``accountId``;
    ``tokenStatus.reconnectRequired`` is the reconnect signal.
  - ``POST /posts {content, platforms:[{platform, accountId, platformSpecificData?}],
    mediaItems?, publishNow}`` → ``{status, postId, platforms:[{platform, success,
    platformPostUrl}]}``.
  - Credits: 1/call, EXCEPT X — 5 (no link) / 50 (body contains ``http(s)://``).

The pure helpers (URL params, payload build, response/error parsing, X credit
cost) are unit-tested with no network. The live calls are synchronous
(``httpx.Client``) to run via ``asyncio.to_thread`` from the async job runners,
mirroring ``services/gbp_posts_api.py``.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
from fastapi import HTTPException

from config import settings

from services.social.adapter import (
    Integration,
    PostResult,
    SocialPostingAdapter,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 45
_PAGE_LIMIT = 100  # max per PostPeer list page
_URL_RE = re.compile(r"https?://", re.IGNORECASE)


# ── pure helpers (no network — unit-tested) ──────────────────────────────────

def x_credit_cost(platform: str, content: str) -> int:
    """PostPeer credit cost for one post. X is the documented exception: 50 if
    the body contains a URL scheme, 5 otherwise; every other platform is 1."""
    if (platform or "").lower() in ("twitter", "x"):
        return 50 if _URL_RE.search(content or "") else 5
    return 1


def build_connect_params(
    profile_id: str, redirect_uri: Optional[str] = None, app_id: Optional[str] = None
) -> dict:
    """Query params for ``GET /connect/{platform}``. ``profileId`` scopes the new
    account to the client; ``appId`` selects a BYOK app (agency-branded consent)."""
    params: dict = {"profileId": profile_id}
    if redirect_uri:
        params["redirectUri"] = redirect_uri
    if app_id:
        params["appId"] = app_id
    return params


def parse_integration(raw: dict) -> Integration:
    """Map one PostPeer integration object onto the module's Integration."""
    token_status = raw.get("tokenStatus") or {}
    return Integration(
        account_id=str(raw.get("id") or ""),
        platform=str(raw.get("platform") or ""),
        profile_id=(str(raw["profileId"]) if raw.get("profileId") is not None else None),
        platform_user_id=(
            str(raw["platformUserId"]) if raw.get("platformUserId") is not None else None
        ),
        handle=raw.get("handle") or raw.get("username") or None,
        reconnect_required=bool(token_status.get("reconnectRequired")),
        raw=raw,
    )


def parse_integrations_page(body: dict) -> tuple[list[Integration], Optional[int]]:
    """Return (integrations, total). ``total`` is None when the body omits it."""
    items = body.get("integrations") or body.get("data") or []
    total = body.get("total")
    return [parse_integration(i) for i in items], (int(total) if total is not None else None)


def normalize_media(media: Optional[list[dict]]) -> list[dict]:
    """Coerce media into PostPeer ``mediaItems`` shape ``{"type","url"}``. Accepts
    already-typed dicts or bare URL strings (treated as images). Drops empties."""
    out: list[dict] = []
    for m in media or []:
        if isinstance(m, str):
            if m:
                out.append({"type": "image", "url": m})
        elif isinstance(m, dict) and m.get("url"):
            out.append({"type": (m.get("type") or "image"), "url": m["url"]})
    return out


def build_post_payload(
    platform: str,
    account_id: str,
    content: str,
    media: Optional[list[dict]] = None,
    platform_specific: Optional[dict] = None,
    publish_now: bool = True,
) -> dict:
    """Body for ``POST /posts`` targeting exactly ONE platform/account. ``media``
    is a list of typed items ``{"type": "image"|"video", "url": ...}``."""
    entry: dict = {"platform": platform, "accountId": account_id}
    if platform_specific:
        entry["platformSpecificData"] = platform_specific
    payload: dict = {"content": content, "platforms": [entry]}
    items = normalize_media(media)
    if items:
        payload["mediaItems"] = items
    if publish_now:
        payload["publishNow"] = True
    return payload


def parse_post_response(body: dict, platform: str) -> PostResult:
    """Parse ``POST /posts`` into a per-platform PostResult. A 200 can still carry
    a failed platform entry (``platforms[].success == false``)."""
    platforms = body.get("platforms") or []
    entry = next(
        (p for p in platforms if (p.get("platform") or "").lower() == (platform or "").lower()),
        (platforms[0] if platforms else {}),
    )
    ok = bool(entry.get("success", body.get("success", False)))
    return PostResult(
        ok=ok,
        platform=platform,
        status=str(body.get("status") or ("published" if ok else "failed")),
        provider_post_id=(str(body["postId"]) if body.get("postId") is not None else None),
        post_url=entry.get("platformPostUrl") or entry.get("url") or None,
        detail=("" if ok else str(entry.get("error") or entry.get("message") or "publish_failed")),
        raw=body,
    )


def classify_error(status_code: int, body: object) -> str:
    """Map a non-2xx into a stable code (the GBP-Posts convention)."""
    msg = ""
    if isinstance(body, dict):
        msg = str(body.get("error") or body.get("message") or "")
    elif isinstance(body, str):
        msg = body
    low = msg.lower()
    if status_code in (401,):
        return "postpeer_auth_failed"
    if status_code == 402 or "credit" in low or "insufficient" in low:
        return "postpeer_out_of_credits"
    if status_code == 429:
        return "postpeer_rate_limited"
    if status_code == 403:
        return "postpeer_forbidden"
    if status_code == 404:
        return "postpeer_not_found"
    if status_code >= 500:
        return "postpeer_server_error"
    return f"postpeer_error_{status_code}"


# ── the adapter (live calls) ─────────────────────────────────────────────────

class PostPeerAdapter(SocialPostingAdapter):
    name = "postpeer"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self._api_key = api_key if api_key is not None else settings.postpeer_api_key
        self._base = (base_url or settings.postpeer_base_url or "https://api.postpeer.dev/v1").rstrip("/")

    # -- infra --
    def _headers(self) -> dict:
        if not self._api_key:
            raise HTTPException(status_code=503, detail="postpeer_not_configured")
        return {"x-access-key": self._api_key, "Content-Type": "application/json"}

    def _raise_for(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            body: object = resp.json()
        except Exception:  # noqa: BLE001 — body may not be JSON
            body = resp.text[:300]
        code = classify_error(resp.status_code, body)
        logger.info("postpeer.error", extra={"status": resp.status_code, "code": code})
        raise HTTPException(status_code=502, detail=code)

    # -- contract --
    def check_auth(self) -> bool:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(f"{self._base}/health/auth", headers=self._headers())
        self._raise_for(resp)
        return True

    def create_profile(self, name: str, description: Optional[str] = None) -> str:
        payload: dict = {"name": name}
        if description:
            payload["description"] = description
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{self._base}/profiles", headers=self._headers(), json=payload)
        self._raise_for(resp)
        profile = (resp.json() or {}).get("profile") or {}
        pid = profile.get("id")
        if not pid:
            raise HTTPException(status_code=502, detail="postpeer_no_profile_id")
        return str(pid)

    def connect_url(
        self,
        platform: str,
        profile_id: str,
        redirect_uri: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> str:
        params = build_connect_params(profile_id, redirect_uri, app_id)
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(
                f"{self._base}/connect/{platform}", headers=self._headers(), params=params
            )
        self._raise_for(resp)
        url = (resp.json() or {}).get("url")
        if not url:
            raise HTTPException(status_code=502, detail="postpeer_no_connect_url")
        return str(url)

    def list_integrations(
        self, profile_id: Optional[str] = None, platform: Optional[str] = None
    ) -> list[Integration]:
        out: list[Integration] = []
        offset = 0
        with httpx.Client(timeout=_TIMEOUT) as client:
            while True:
                params: dict = {"limit": _PAGE_LIMIT, "offset": offset}
                if profile_id:
                    params["profileId"] = profile_id
                if platform:
                    params["platform"] = platform
                resp = client.get(
                    f"{self._base}/connect/integrations", headers=self._headers(), params=params
                )
                self._raise_for(resp)
                page, total = parse_integrations_page(resp.json() or {})
                out.extend(page)
                offset += len(page)
                # Stop when a short page arrives or we've reached the reported total.
                if not page or len(page) < _PAGE_LIMIT:
                    break
                if total is not None and offset >= total:
                    break
        return out

    def post(
        self,
        account_id: str,
        platform: str,
        content: str,
        media: Optional[list[dict]] = None,
        platform_specific: Optional[dict] = None,
        publish_now: bool = True,
    ) -> PostResult:
        payload = build_post_payload(
            platform, account_id, content, media, platform_specific, publish_now
        )
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{self._base}/posts", headers=self._headers(), json=payload)
        self._raise_for(resp)
        return parse_post_response(resp.json() or {}, platform)


def get_adapter(provider: Optional[str] = None) -> SocialPostingAdapter:
    """Factory for the configured posting adapter (ADR-0001 swap point)."""
    name = (provider or settings.social_posting_provider or "postpeer").lower()
    if name == "postpeer":
        return PostPeerAdapter()
    raise HTTPException(status_code=503, detail=f"social_provider_unknown:{name}")
