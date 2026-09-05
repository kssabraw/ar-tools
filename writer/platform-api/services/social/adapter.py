"""Social posting **adapter** — the swappable seam (ADR-0001).

The Social Media module never talks to a posting provider (PostPeer today,
Ayrshare the fallback) directly; it goes through this interface, so swapping
providers is one implementation, not a refactor. The provider holds the
per-account OAuth tokens — we store only the provider's opaque ``account_id``
(the module's ``social_accounts.adapter_account_id``) and, per client, the
provider's grouping id (``profile_id`` == a PostPeer "Social group").

Return shapes are provider-agnostic dataclasses so raw provider JSON never
leaks into module code. A concrete adapter maps the provider's response onto
these; a non-recoverable provider error surfaces as an ``HTTPException`` whose
``detail`` is a classified string code (the GBP-Posts convention).

See: docs/modules/social-media/CLAUDE.md, docs/adr/0001-postpeer-...md,
docs/modules/social-media-vendor-confirm-postpeer-v1_0.md §6.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Optional


# Platforms the module targets. PostPeer's connect endpoint uses these exact
# slugs (bluesky is deliberately excluded — it has no OAuth redirect flow).
PLATFORMS = (
    "twitter",
    "facebook",
    "instagram",
    "pinterest",
    "youtube",
    "linkedin",
    "tiktok",
    "threads",
)


@dataclass
class Integration:
    """One connected social account, as the module sees it. ``account_id`` is
    the value passed back when publishing (PostPeer's ``integration.id``)."""

    account_id: str
    platform: str
    profile_id: Optional[str] = None
    platform_user_id: Optional[str] = None
    handle: Optional[str] = None
    # True when the provider says the token is expired / insufficient scope and
    # the client must re-authorize (PostPeer: tokenStatus.reconnectRequired).
    reconnect_required: bool = False
    raw: dict = field(default_factory=dict)


@dataclass
class PostResult:
    """The outcome of publishing ONE Draft to ONE platform. ``provider_post_id``
    + ``post_url`` are set on success; ``detail`` carries the failure reason
    otherwise. ``ok`` reflects the *per-platform* success, not just HTTP 2xx —
    a provider can return 200 with a platform entry that failed."""

    ok: bool
    platform: str
    status: str = ""
    provider_post_id: Optional[str] = None
    post_url: Optional[str] = None
    detail: str = ""
    raw: dict = field(default_factory=dict)


class SocialPostingAdapter(abc.ABC):
    """The provider-agnostic contract. Concrete impls: PostPeerAdapter (v1),
    an Ayrshare adapter as the fallback (ADR-0001)."""

    name: str = "abstract"

    @abc.abstractmethod
    def check_auth(self) -> bool:
        """Verify the account credential (free, no side effects). True on 2xx."""

    @abc.abstractmethod
    def create_profile(self, name: str, description: Optional[str] = None) -> str:
        """Create the provider grouping for a client (a PostPeer 'Social group').
        Returns the provider ``profile_id`` to store on the client."""

    @abc.abstractmethod
    def connect_url(
        self,
        platform: str,
        profile_id: str,
        redirect_uri: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> str:
        """Return the OAuth URL to redirect the account owner to. ``app_id`` is
        the BYOK app (agency-branded consent); omit for the provider's shared app."""

    @abc.abstractmethod
    def list_integrations(
        self, profile_id: Optional[str] = None, platform: Optional[str] = None
    ) -> list[Integration]:
        """List connected accounts (all pages), optionally scoped to one client's
        profile and/or one platform."""

    @abc.abstractmethod
    def post(
        self,
        account_id: str,
        platform: str,
        content: str,
        media: Optional[list[dict]] = None,
        platform_specific: Optional[dict] = None,
        publish_now: bool = True,
    ) -> PostResult:
        """Publish ONE piece of content to ONE connected account. ``media`` is a
        list of typed items ``{"type": "image"|"video", "url": ...}`` (images for a
        single/carousel photo post, one video for a Facebook video / Instagram
        Reel). The module's
        data model is one Post per platform, so this sends exactly one platform
        per provider call to keep per-platform status independent. Publishing is
        always driven from OUR scheduler with ``publish_now`` — we never hand the
        provider a future schedule (the freeze + source-changed guards must run
        immediately before posting)."""
