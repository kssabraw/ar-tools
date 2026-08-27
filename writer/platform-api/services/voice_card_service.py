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

from fastapi import HTTPException

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


# Mirrors nlp-api's `voice_card.VOICE_PASS_THRESHOLD`. A page below this does
# not sound like the client, whatever it scores on SEO.
VOICE_PASS_THRESHOLD = 80.0


def reoptimize_verdict(
    composite: Optional[float],
    voice_compliance: Optional[dict],
    seo_threshold: float,
    voice_threshold: float = VOICE_PASS_THRESHOLD,
    length_fit: Optional[dict] = None,
) -> tuple[bool, str]:
    """Should this live page be rewritten? Returns `(reoptimize, reason)`.

    The bulk reoptimizer used to decide purely on the SEO score, which meant a
    page at 78 SEO / 40 voice was skipped without the voice score ever being
    looked at — exactly the pages most worth re-running. A page now earns a
    rewrite when the SEO score falls short, a forbidden term is on it, the voice
    score is low, OR it runs significantly over the SERP length target.

    `length_fit` is the deterministic length engine from the score's
    `engine_scores` (or None for clients/tools without it). Length gets its own
    trigger for the same reason voice does: its small composite weight can't drag
    an otherwise-strong page below the SEO bar, so a 2× page at 78 SEO would be
    skipped. Only OVER-length trips this (an over-length deficiency, score < 80);
    under-length is left to the content-depth engines and the SEO bar.

    Pure so the decision is unit-testable without a live score call; the
    `reason` is user-facing copy shown on skipped rows.
    """
    voice_compliance = voice_compliance or {}
    voice_score = voice_compliance.get("score")
    has_critical = bool(voice_compliance.get("critical_count"))

    seo_ok = composite is not None and composite >= seo_threshold
    voice_ok = (
        not has_critical
        and (voice_score is None or voice_score >= voice_threshold)
    )

    lf = length_fit or {}
    lf_target = lf.get("target_words") or 0
    over_length = bool(
        lf.get("measured")
        and lf_target
        and lf.get("page_words", 0) > lf_target
        and lf.get("score", 100) < 80
    )
    length_ok = not over_length

    if seo_ok and voice_ok and length_ok:
        detail = f"Already scores {round(composite)}/100 on SEO"
        if voice_score is not None:
            detail += f" and {round(voice_score)}/100 on brand voice"
        return False, (
            f"{detail} — at or above threshold, so reoptimization was skipped."
        )

    # SEO + voice fine, but the page runs long vs the SERP — trim it.
    if seo_ok and voice_ok and not length_ok:
        return True, (
            f"SEO is fine at {round(composite)}/100, but the page runs "
            f"~{lf.get('page_words')} words vs a ~{lf_target} target "
            f"(competitor SERP average + 20%) — trimming to match the SERP."
        )

    # Unscoreable SEO (None) still reoptimizes, as it always did.
    if seo_ok and not voice_ok:
        if has_critical:
            return True, (
                f"SEO is fine at {round(composite)}/100, but the page uses wording the "
                f"brand guide forbids — rewriting for voice."
            )
        return True, (
            f"SEO is fine at {round(composite)}/100, but brand voice scores "
            f"{round(voice_score)}/100 — rewriting for voice."
        )
    return True, "Below the SEO threshold — rewriting."


def assert_voice_publishable(verdict: Optional[dict], force: bool = False) -> None:
    """Refuse to publish content that breaks the client's brand guide.

    Only a `critical` finding blocks — a forbidden word, caught by word-boundary
    regex, so the term is provably on the page. A low score is a judgement and
    warnings are advisory; neither stops a publish, because blocking on a
    subjective call would make the gate something people route around.

    `force` is the deliberate override. The never-use list comes from an LLM
    distillation of the guide, so a wrong extraction must not deadlock the team
    permanently — but it takes an explicit second action, which is the
    difference between "stopped" and "flagged".

    Raises 409 `voice_violation`; the caller already has the verdict and can
    render exactly which words offended.

    The offending terms ride along in the detail string, so a surface that only
    sees the error (rather than the full verdict) can still name them. The
    format stays backwards-compatible: the code is always the token before the
    first colon, so `detail.startswith("voice_violation")` and
    `"voice_violation" in detail` both keep working; terms follow as
    `"voice_violation: cheapest | budget"` when we have them.

    Terms are joined with " | " rather than ", " so a distilled never-use
    *phrase* that itself contains a comma isn't split into two by the reader.
    """
    if force or not isinstance(verdict, dict):
        return
    if not verdict.get("critical_count"):
        return
    terms = _critical_terms(verdict)
    detail = f"voice_violation: {' | '.join(terms)}" if terms else "voice_violation"
    raise HTTPException(status_code=409, detail=detail)


def _critical_terms(verdict: dict) -> list[str]:
    """The forbidden words that made this verdict critical, de-duplicated in
    order. Best-effort: a malformed violations list yields no terms (the gate
    still blocks — the words are a nicety, the block is the contract)."""
    seen: list[str] = []
    for finding in verdict.get("violations") or []:
        if not isinstance(finding, dict):
            continue
        if finding.get("severity") != "critical":
            continue
        for term in finding.get("terms") or []:
            text = str(term).strip()
            if text and text.lower() not in {s.lower() for s in seen}:
                seen.append(text)
    return seen
