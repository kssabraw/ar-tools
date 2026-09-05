"""Social Media module — posting-provider adapter package (ADR-0001).

Import the provider-agnostic pieces from here:

    from services.social import get_adapter, SocialPostingAdapter, Integration, PostResult
"""

from services.social.adapter import (  # noqa: F401
    PLATFORMS,
    Integration,
    PostResult,
    SocialPostingAdapter,
)
from services.social.postpeer_adapter import PostPeerAdapter, get_adapter  # noqa: F401
