"""PostForMe implementation of the social posting adapter (ADR-0001, live provider).

PostForMe (api.postforme.dev) replaces PostPeer. The decisive difference is isolation:
a PostForMe API key is scoped to a single **Project**, and we run one Project per
client, so the key IS the client-isolation boundary — a client's key can only ever see
or post to that client's accounts (verified empirically). The adapter is therefore
constructed with a **per-client** key (loaded by the factory from
``social_client_credentials``), not a global one.

Confirmed API facts (docs/modules/social-media-vendor-confirm-postforme-v1_0.md, from the
verified OpenAPI spec at api.postforme.dev/docs/openapi.json):

  - Base ``https://api.postforme.dev/v1``; ``Authorization: Bearer <key>`` on every
    endpoint. No project id is passed anywhere — the Bearer key alone selects the project.
  - Platform enum: bluesky/facebook/instagram/linkedin/pinterest/threads/tiktok/x/youtube
    (account creation also allows tiktok_business). It is ``x``, NOT ``twitter`` — the
    module's internal slug is ``twitter``, mapped at this boundary.
  - ``GET /social-accounts`` (offset/limit) → ``{data:[SocialAccountDto], meta:{total}}``.
    SocialAccountDto: ``id`` (spc_…), ``platform``, ``username``, ``external_id``,
    ``status`` ∈ {connected, disconnected} (there is no separate reconnect flag —
    disconnected ⇒ reconnect required). No health endpoint, so ``GET /social-accounts?limit=1``
    is the auth check.
  - ``POST /social-accounts/auth-url {platform, external_id?, permissions:["posts"],
    redirect_url_override?}`` → ``{url, platform}`` (the hosted OAuth link).
  - ``POST /social-posts {caption, social_accounts:[id], media:[{url}], scheduled_at?,
    platform_configurations?, external_id?, isDraft?}`` → ``SocialPostDto {id, status}``
    where status ∈ {draft, scheduled, processing, processed}. ``scheduled_at`` null/omitted
    ⇒ publish now (there is no separate publish-now flag; we always drive scheduling from
    OUR sweep, so we always omit it). Media is URL-only — the API infers image vs video.
  - Posts are ASYNC: the create response carries no per-platform URL. The live URL + real
    per-platform success come from ``GET /social-post-results?post_id=<id>`` afterward (or
    the ``social.post.result.created`` webhook). ``post()`` bounded-polls that endpoint
    (Decision 2=A) — the exact SocialPostResultDto field names aren't in the spec fragment
    we captured, so the result parse is deliberately defensive.
  - Pricing is flat (~$10 / 1,000 posts, team-pooled quota) — no PostPeer-style X credit
    quirk. Budget is estimated per post via ``social_postforme_cost_per_post_usd``.

Pure helpers (platform mapping, payload build, response/error parse, result matching) are
unit-tested with no network. Live calls are synchronous (``httpx.Client``) to run via
``asyncio.to_thread`` from the async job runners, mirroring the PostPeer adapter.
"""

from __future__ import annotations

import logging
import time
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

_TIMEOUT = 60
_PAGE_LIMIT = 100  # max per list page (offset/limit)

# PostForMe uses "x"; the module's internal slug is "twitter". Map only at this boundary.
_TO_PFM = {"twitter": "x"}
_FROM_PFM = {"x": "twitter"}

# A created post in any of these states was accepted for delivery (vs an outright failure).
_ACCEPTED_STATUSES = {"scheduled", "processing", "processed", "published"}


# ── pure helpers (no network — unit-tested) ──────────────────────────────────

def to_pfm_platform(platform: str) -> str:
    """Module slug → PostForMe slug (twitter → x)."""
    p = (platform or "").lower()
    return _TO_PFM.get(p, p)


def from_pfm_platform(platform: str) -> str:
    """PostForMe slug → module slug (x → twitter)."""
    p = (platform or "").lower()
    return _FROM_PFM.get(p, p)


def normalize_media(media: Optional[list[dict]]) -> list[dict]:
    """Coerce the module's typed media (``{"type","url"}`` or bare URL string) into
    PostForMe's URL-only ``media`` items (``{"url": ...}``). PostForMe infers the media
    type from the URL, so the ``type`` is dropped. Empties dropped."""
    out: list[dict] = []
    for m in media or []:
        if isinstance(m, str):
            if m:
                out.append({"url": m})
        elif isinstance(m, dict) and m.get("url"):
            out.append({"url": m["url"]})
    return out


def build_auth_url_payload(
    platform: str,
    external_id: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    permissions: Optional[list[str]] = None,
) -> dict:
    """Body for ``POST /social-accounts/auth-url``. ``external_id`` is our own reference
    tag on the account (we pass the client id). ``redirect_url_override`` is only honoured
    on white-label projects with own credentials — on a Quickstart project the redirect is
    the project's dashboard-configured one, so a passed value may be ignored (harmless)."""
    payload: dict = {
        "platform": to_pfm_platform(platform),
        "permissions": permissions or ["posts"],
    }
    if external_id:
        payload["external_id"] = external_id
    if redirect_uri:
        payload["redirect_url_override"] = redirect_uri
    return payload


def parse_account(raw: dict) -> Integration:
    """Map one PostForMe SocialAccountDto onto the module's Integration. ``status`` is
    binary connected/disconnected — disconnected ⇒ reconnect_required (no separate flag)."""
    status = (raw.get("status") or "").lower()
    return Integration(
        account_id=str(raw.get("id") or ""),
        platform=from_pfm_platform(str(raw.get("platform") or "")),
        profile_id=(str(raw["external_id"]) if raw.get("external_id") is not None else None),
        platform_user_id=(str(raw["user_id"]) if raw.get("user_id") is not None else None),
        handle=raw.get("username") or None,
        reconnect_required=(status == "disconnected"),
        raw=raw,
    )


def parse_accounts_page(body: dict) -> tuple[list[Integration], Optional[int]]:
    """Return (integrations, total) from a ``GET /social-accounts`` page
    (``{data:[...], meta:{total}}``). ``total`` is None when absent."""
    items = body.get("data") or []
    meta = body.get("meta") or {}
    total = meta.get("total")
    return [parse_account(i) for i in items if isinstance(i, dict)], (
        int(total) if total is not None else None
    )


def build_post_payload(
    account_id: str,
    platform: str,
    caption: str,
    media: Optional[list[dict]] = None,
    platform_specific: Optional[dict] = None,
    external_id: Optional[str] = None,
) -> dict:
    """Body for ``POST /social-posts`` targeting exactly ONE account. ``scheduled_at`` is
    always omitted (publish now — we schedule from our own sweep). ``platform_specific``,
    when given, is passed as this platform's ``platform_configurations`` block (opaque
    passthrough, e.g. a YouTube ``title``)."""
    payload: dict = {"caption": caption or "", "social_accounts": [account_id]}
    items = normalize_media(media)
    if items:
        payload["media"] = items
    if platform_specific:
        payload["platform_configurations"] = {to_pfm_platform(platform): platform_specific}
    if external_id:
        payload["external_id"] = external_id
    return payload


def parse_post_create(body: dict) -> tuple[Optional[str], str]:
    """Return (post_id, status) from a ``POST /social-posts`` SocialPostDto response."""
    post_id = body.get("id")
    return (str(post_id) if post_id is not None else None), str(body.get("status") or "")


def _result_row_for_account(results: list[dict], account_id: str) -> Optional[dict]:
    """Find the SocialPostResult row for one account (defensive — the exact field name
    isn't pinned in the captured spec, so accept the common shapes; fall back to the sole
    row when a single-account post returns exactly one result)."""
    aid = str(account_id)
    for r in results:
        if not isinstance(r, dict):
            continue
        if str(r.get("social_account_id") or r.get("account_id") or "") == aid:
            return r
    real = [r for r in results if isinstance(r, dict)]
    return real[0] if len(real) == 1 else None


def parse_result_row(row: dict, platform: str, post_id: Optional[str]) -> PostResult:
    """Map one SocialPostResult row onto a PostResult (defensive field access)."""
    pdata = row.get("platform_data") or {}
    ok = bool(row.get("success"))
    url = pdata.get("url") or row.get("platform_url") or row.get("url") or None
    pid = pdata.get("id") or row.get("platform_post_id") or post_id
    err = row.get("error") or row.get("details") or row.get("message")
    return PostResult(
        ok=ok,
        platform=platform,
        status="published" if ok else "failed",
        provider_post_id=(str(pid) if pid else None),
        post_url=url or None,
        detail=("" if ok else str(err or "publish_failed")),
        raw=row,
    )


def accepted_result(platform: str, post_id: Optional[str], create_status: str, body: dict) -> PostResult:
    """The PostResult when a post was ACCEPTED but no per-platform result is available yet
    (still processing past the poll window). ``ok`` reflects acceptance, not final platform
    success — the documented Decision-2=A tradeoff; the URL fills in later via the webhook /
    a re-read."""
    return PostResult(
        ok=(create_status.lower() in _ACCEPTED_STATUSES) or not create_status,
        platform=platform,
        status=create_status or "processing",
        provider_post_id=(str(post_id) if post_id else None),
        post_url=None,
        detail="",
        raw=body,
    )


def classify_error(status_code: int, body: object) -> str:
    """Map a non-2xx into a stable code (PostForMe documents no structured error body, so
    this reads whatever message it can and keys mostly off the status)."""
    msg = ""
    if isinstance(body, dict):
        msg = str(body.get("error") or body.get("message") or body.get("detail") or "")
    elif isinstance(body, str):
        msg = body
    low = msg.lower()
    if status_code == 401:
        return "postforme_auth_failed"
    if status_code == 402 or "quota" in low or "limit reached" in low or "insufficient" in low:
        return "postforme_out_of_quota"
    if status_code == 429:
        return "postforme_rate_limited"
    if status_code == 403:
        return "postforme_forbidden"
    if status_code == 404:
        return "postforme_not_found"
    if status_code == 422 or "validation" in low:
        return "postforme_invalid_request"
    if status_code >= 500:
        return "postforme_server_error"
    return f"postforme_error_{status_code}"


# ── the adapter (live calls) ─────────────────────────────────────────────────

class PostForMeAdapter(SocialPostingAdapter):
    name = "postforme"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self._api_key = api_key or ""
        self._base = (base_url or settings.postforme_base_url or "https://api.postforme.dev/v1").rstrip("/")

    # -- infra --
    def _headers(self) -> dict:
        if not self._api_key:
            # No per-client project key set (or the module isn't configured for this client).
            raise HTTPException(status_code=503, detail="social_not_configured")
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _raise_for(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            body: object = resp.json()
        except Exception:  # noqa: BLE001 — body may not be JSON
            body = resp.text[:300]
        code = classify_error(resp.status_code, body)
        logger.info("postforme.error", extra={"status": resp.status_code, "code": code})
        raise HTTPException(status_code=502, detail=code)

    # -- contract --
    def check_auth(self) -> bool:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(
                f"{self._base}/social-accounts", headers=self._headers(), params={"limit": 1}
            )
        self._raise_for(resp)
        return True

    def create_profile(self, name: str, description: Optional[str] = None) -> str:
        # PostForMe has no project/key-management API — a client's Project + key are created
        # manually in the dashboard and pasted in (services/social/credentials.py). There is
        # nothing to create here; this contract method must never be reached on the PostForMe
        # path (the client-create provisioning enqueue no-ops without a PostPeer key).
        raise HTTPException(status_code=501, detail="postforme_manual_provision")

    def connect_url(
        self,
        platform: str,
        profile_id: str,
        redirect_uri: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> str:
        # profile_id carries our client id, tagged onto the account as external_id (a
        # reconciliation reference — isolation itself is the per-client project key).
        payload = build_auth_url_payload(platform, external_id=profile_id, redirect_uri=redirect_uri)
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(
                f"{self._base}/social-accounts/auth-url", headers=self._headers(), json=payload
            )
        self._raise_for(resp)
        url = (resp.json() or {}).get("url")
        if not url:
            raise HTTPException(status_code=502, detail="postforme_no_connect_url")
        return str(url)

    def list_integrations(
        self, profile_id: Optional[str] = None, platform: Optional[str] = None
    ) -> list[Integration]:
        # profile_id is IGNORED — the per-client project key already scopes the list to this
        # client's accounts (the isolation boundary). Optional platform filter is client-side.
        want = (platform or "").lower()
        out: list[Integration] = []
        offset = 0
        with httpx.Client(timeout=_TIMEOUT) as client:
            while True:
                resp = client.get(
                    f"{self._base}/social-accounts",
                    headers=self._headers(),
                    params={"limit": _PAGE_LIMIT, "offset": offset},
                )
                self._raise_for(resp)
                page, total = parse_accounts_page(resp.json() or {})
                out.extend(page)
                offset += len(page)
                if not page or len(page) < _PAGE_LIMIT:
                    break
                if total is not None and offset >= total:
                    break
        if want:
            out = [i for i in out if (i.platform or "").lower() == want]
        return out

    def _fetch_results(self, client: httpx.Client, post_id: str) -> list[dict]:
        resp = client.get(
            f"{self._base}/social-post-results", headers=self._headers(), params={"post_id": post_id}
        )
        self._raise_for(resp)
        body = resp.json() or {}
        return [r for r in (body.get("data") or []) if isinstance(r, dict)]

    def post(
        self,
        account_id: str,
        platform: str,
        content: str,
        media: Optional[list[dict]] = None,
        platform_specific: Optional[dict] = None,
        publish_now: bool = True,
    ) -> PostResult:
        payload = build_post_payload(account_id, platform, content, media, platform_specific)
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{self._base}/social-posts", headers=self._headers(), json=payload)
            self._raise_for(resp)
            body = resp.json() or {}
            post_id, create_status = parse_post_create(body)

            # A created post is async: bounded-poll /social-post-results for this account's
            # per-platform outcome (Decision 2=A). If none arrives in the window, return
            # "accepted" (ok reflects acceptance; the URL fills in later).
            if not post_id:
                return accepted_result(platform, post_id, create_status, body)
            attempts = max(1, int(settings.social_postforme_result_poll_attempts))
            interval = max(0.0, float(settings.social_postforme_result_poll_interval_secs))
            for i in range(attempts):
                try:
                    results = self._fetch_results(client, post_id)
                except HTTPException:
                    results = []
                row = _result_row_for_account(results, account_id)
                if row is not None and row.get("success") is not None:
                    return parse_result_row(row, platform, post_id)
                if i < attempts - 1 and interval:
                    time.sleep(interval)
            return accepted_result(platform, post_id, create_status, body)
