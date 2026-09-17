"""Social Media module — posting-provider adapter package (ADR-0001).

Import the provider-agnostic pieces from here:

    from services.social import get_adapter, SocialPostingAdapter, Integration, PostResult

``get_adapter`` is the swap point: PostForMe (live) uses a per-client project key
(provider-enforced isolation), PostPeer (retired fallback) uses one global key.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from config import settings

from services.social.adapter import (  # noqa: F401
    PLATFORMS,
    Integration,
    PostResult,
    SocialPostingAdapter,
)
from services.social.postforme_adapter import PostForMeAdapter  # noqa: F401
from services.social.postpeer_adapter import PostPeerAdapter  # noqa: F401


def get_adapter(
    client_id: Optional[str] = None, provider: Optional[str] = None
) -> SocialPostingAdapter:
    """Factory for the configured posting adapter (ADR-0001 swap point).

    PostForMe keys are per-client, so ``client_id`` loads that client's project key into
    the adapter — the key is the isolation boundary. PostPeer uses one global key and
    ignores ``client_id``. The provider defaults to ``settings.social_posting_provider``
    ("postpeer" in code, "postforme" on PLATFORM)."""
    name = (provider or settings.social_posting_provider or "postpeer").lower()
    if name == "postforme":
        api_key = None
        if client_id:
            from services.social import credentials

            api_key = credentials.get_client_key(client_id)
        return PostForMeAdapter(api_key=api_key)
    if name == "postpeer":
        return PostPeerAdapter()
    raise HTTPException(status_code=503, detail=f"social_provider_unknown:{name}")
