"""Brand Voice & Audience Card — resolution and caching (platform side).

The card is the enforceable form of a client's brand guide + ICP: tone,
grammatical person, must-use / never-use terms, CTA language, and the real
audience. nlp-api owns the distillation (one Anthropic call, `/distill-voice-card`)
and every check that uses it; this module owns *when* that call happens.

Why cache at all: distilling is one LLM call over documents that change maybe
once a quarter, and generation happens hundreds of times per client. Paying for
it per page would be pure waste, and bulk-create — one job per keyword — would
pay it fifty times in a row for the same guide.

Cache key is a fingerprint of the *rendered* brand-voice and ICP text, not the
raw JSONB, so an incidental field change (a re-scan timestamp) doesn't force a
re-distillation while a real edit to the guide always does.

Every path here is best-effort: a distillation failure returns an empty card,
which every consumer treats as "no enforcement" and falls back to the prior
behaviour. A client's page must never fail to generate because we couldn't
summarise their brand guide.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from db.supabase_client import get_supabase
from services import brand_voice_service, icp_service

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def card_fingerprint(brand_guide_text: str, icp_text: str) -> str:
    """Stable key for a distilled card against the documents it came from.

    Mirrors `nlp-api/voice_card.py::card_fingerprint` exactly — same hash, same
    separator — so a card distilled by either service is recognised by the
    other. Duplicated rather than shared because the two services have no
    common package; the pair is locked by a unit test.
    """
    digest = hashlib.sha256()
    digest.update((brand_guide_text or "").strip().encode("utf-8"))
    digest.update(b"\x00")
    digest.update((icp_text or "").strip().encode("utf-8"))
    return digest.hexdigest()


def source_texts(client: dict) -> tuple[str, str]:
    """The brand-guide and ICP text this client's card is built from — the same
    renderers the run snapshot and the nlp prompts use, so the card is distilled
    from exactly the text the writer would otherwise have seen."""
    return (
        brand_voice_service.resolve_brand_guide_text(client) or "",
        icp_service.resolve_icp_text(client) or "",
    )


def cached_card(client: dict) -> Optional[dict]:
    """The client's stored card when it still matches their current guide.

    Returns None when there is no card, or when the guide has been edited since
    it was built — the caller then re-distills. A stale card is worse than no
    card: it would enforce rules the client has already changed.
    """
    stored = client.get("voice_card")
    if not isinstance(stored, dict) or not stored.get("card"):
        return None
    brand_text, icp_text = source_texts(client)
    if stored.get("fingerprint") != card_fingerprint(brand_text, icp_text):
        return None
    card = stored.get("card")
    return card if isinstance(card, dict) else None


def _persist(client_id: str, fingerprint: str, card: dict) -> None:
    try:
        get_supabase().table("clients").update({
            "voice_card": {
                "fingerprint": fingerprint,
                "card": card,
                "generated_at": _now_iso(),
            }
        }).eq("id", client_id).execute()
    except Exception as exc:
        # A cache write failure costs one extra distillation next time, nothing
        # more — never let it surface to the caller mid-generation.
        logger.warning(
            "voice_card.persist_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )


async def get_voice_card(client: dict, user_id: Optional[str] = None) -> dict:
    """The client's voice card, distilling and caching it if needed.

    Returns `{}` when the client has no brand guide or ICP on file, or when
    distillation fails — both mean "no enforcement", and consumers already
    treat an empty card that way.
    """
    brand_text, icp_text = source_texts(client)
    if not (brand_text.strip() or icp_text.strip()):
        return {}

    cached = cached_card(client)
    if cached is not None:
        return cached

    # Imported here rather than at module scope: local_seo_service imports this
    # module for its payload builders, and a top-level import would close the
    # cycle.
    from services.local_seo_service import _post_nlp

    try:
        result = await _post_nlp(
            "/distill-voice-card",
            {
                "brand_voice": client.get("brand_voice"),
                "detected_icp": client.get("detected_icp"),
            },
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning(
            "voice_card.distill_failed",
            extra={"client_id": client.get("id"), "error": str(exc)},
        )
        return {}

    card = result.get("voice_card")
    if not isinstance(card, dict) or not any(card.values()):
        # A guide we couldn't extract anything enforceable from. Cache the empty
        # result anyway so we don't re-pay for the same non-answer on every page.
        card = {}
    _persist(
        client.get("id"),
        result.get("fingerprint") or card_fingerprint(brand_text, icp_text),
        card,
    )
    return card
