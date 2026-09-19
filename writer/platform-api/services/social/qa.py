"""Social Media P4 (Phase C) — the opt-in social QA rubric.

**Deterministic** (the verdict is computed in code, never an LLM's). Per-client opt-in via
``social_policy.qa_gate``. Given a draft's copy + media + platform, it runs the §9 checks —
brand voice (no guide-forbidden terms), no banned regulated claims, a CTA, platform
constraints, an image — and folds them into a graduated verdict via the shared
``qa_signals.build_verdict``.

Two gates consume the verdict:
- **Auto-queue** (the autonomy loop, tier 2): ``blocks_auto_queue`` — ANY blocking failure
  keeps the draft ``ready`` instead of ``queued`` (never queue unreviewed content that
  fails). An advisory-only miss (a text-only post where the platform allows one) still
  auto-queues.
- **Manual publish**: ``is_critical_fail`` — a CRITICAL fail (a guide-forbidden voice term
  or a banned regulated claim) blocks the publish (409, with a ``force`` override); other
  failures are advisory on the human path (platform/char/image-required are already
  hard-blocked by ``validate_post``).

Reuses the built primitives: ``qa_signals`` (``check_social_draft`` / ``build_verdict`` /
``has_cta`` / ``mark_critical``), ``gbp_posts_service.voice_forbidden_hits``,
``content_compliance.scan_text``, ``publish.validate_post``. The verdict is persisted on
``social_drafts.qa_verdict`` (``qa_reviews`` is task-scoped and can't hold a draft review).
Best-effort throughout: a failed signal read never fabricates a block or crashes a publish.
"""

from __future__ import annotations

import logging
from typing import Optional

from services import qa_signals

logger = logging.getLogger(__name__)


def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


def qa_gate_enabled(client_id: str) -> bool:
    """Whether the client opted into the social QA gate (social_policy.qa_gate)."""
    try:
        rows = (
            _sb().table("social_policy").select("qa_gate")
            .eq("client_id", client_id).limit(1).execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001 — a read failure defaults to OFF (no gate)
        logger.warning("social.qa_gate_read_failed", extra={"client_id": client_id, "error": str(exc)[:160]})
        return False
    return bool(rows[0].get("qa_gate")) if rows else False


def _client_for_voice(client_id: str) -> dict:
    """The client row with the fields the cached voice card + its freshness check need."""
    try:
        rows = (
            _sb().table("clients").select("*")
            .eq("id", client_id).limit(1).execute()
        ).data or []
        return rows[0] if rows else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("social.qa_client_read_failed", extra={"client_id": client_id, "error": str(exc)[:160]})
        return {}


def _compliance_mode(client: dict) -> str:
    return (client.get("content_compliance_mode") or "off") if isinstance(client, dict) else "off"


def resolve_compliance_mode(client_id: str) -> str:
    """The client's content_compliance_mode via a targeted read (default 'off'). Used to
    resolve the mode ONCE per fan-out for the auto-queue path (the fan-out's client row
    doesn't carry the column, which would otherwise skip the banned-claims check)."""
    try:
        rows = (
            _sb().table("clients").select("content_compliance_mode")
            .eq("id", client_id).limit(1).execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001 — default to 'off' (no claims check) on a read error
        logger.warning("social.qa_mode_read_failed", extra={"client_id": client_id, "error": str(exc)[:140]})
        return "off"
    return (rows[0].get("content_compliance_mode") or "off") if rows else "off"


def review_draft(
    *,
    client_id: str,
    platform: str,
    copy: Optional[str],
    media: Optional[list],
    fmt: str = "feed",
    board_id: Optional[str] = None,
    card: Optional[dict] = None,
    client: Optional[dict] = None,
    compliance_mode: Optional[str] = None,
) -> dict:
    """Compute the deterministic social QA verdict for a draft. Best-effort per signal.

    ``card`` (the voice card) + ``client`` may be passed pre-resolved (the fan-out job has
    them); otherwise they're read here (the sync manual-publish path uses the cached card).
    ``compliance_mode`` may be passed pre-resolved (the auto-queue path resolves it once, since
    the fan-out's client row doesn't carry the column); else it's read from the client.
    Returns a ``build_verdict`` dict + ``rubric`` + the annotated ``checks``."""
    from services import content_compliance, gbp_posts_service
    from services.social import publish

    copy = copy or ""
    fmt = (fmt or "feed").lower()
    media = media or []

    if client is None and (card is None):
        client = _client_for_voice(client_id)

    # Voice — guide-forbidden terms (deterministic). Resolve the card from the cache when
    # not passed (fresh-only; a stale/absent card degrades to no enforcement, never a false
    # block). A story carries no caption, so its copy is empty and this is naturally [].
    if card is None:
        try:
            from services import voice_card_service

            card = voice_card_service.cached_card(client or {})
        except Exception as exc:  # noqa: BLE001
            logger.info("social.qa_card_unavailable", extra={"error": str(exc)[:140]})
            card = None
    try:
        forbidden = gbp_posts_service.voice_forbidden_hits(copy, card) if copy else []
    except Exception:  # noqa: BLE001
        forbidden = []

    # Banned regulated claims — only bites for a regulated client (mode != 'off'); an
    # 'off'/unknown mode returns an empty (passing) scan. Resolve the mode robustly: an
    # explicit arg (auto-queue, resolved once) → the passed client IF it carries the column
    # → a targeted read (the fan-out client row omits it, so never trust its absence).
    if compliance_mode is not None:
        mode = compliance_mode
    elif isinstance(client, dict) and "content_compliance_mode" in client:
        mode = _compliance_mode(client)
    else:
        mode = resolve_compliance_mode(client_id)
    banned: list[str] = []
    try:
        res = content_compliance.scan_text(copy, mode=mode)
        banned = [f.evidence for f in res.findings if f.severity == "critical"]
    except Exception:  # noqa: BLE001
        banned = []

    # A story has no caption by design → its CTA check is N/A (never a fail).
    has_cta_flag = True if fmt == "story" else qa_signals.has_cta(copy)

    # Platform constraints — validate_post's hard list (char / image-required / format /
    # board). A validator error must NOT fabricate a fail (fail-safe → platform_ok).
    try:
        spec = publish._platform_spec(platform)
        hard = publish.validate_post(platform, copy, media, spec, fmt=fmt, board_id=board_id).get("hard") or []
        platform_ok = not hard
    except Exception as exc:  # noqa: BLE001
        logger.info("social.qa_validate_error", extra={"platform": platform, "error": str(exc)[:140]})
        platform_ok = True

    checks = qa_signals.mark_critical(qa_signals.check_social_draft(
        forbidden_terms=forbidden, banned_claims=banned, has_cta_flag=has_cta_flag,
        platform_ok=platform_ok, has_media=bool(media),
    ))
    verdict = qa_signals.build_verdict(checks)
    verdict["rubric"] = qa_signals.RUBRIC_SOCIAL
    verdict["checks"] = checks
    return verdict


def blocks_auto_queue(verdict: Optional[dict]) -> bool:
    """The autonomy auto-queue gate: block on ANY non-pass/advisory verdict (never queue
    unreviewed content that fails a check). None (no verdict) never blocks."""
    if not verdict:
        return False
    return verdict.get("verdict") not in (qa_signals.PASS, qa_signals.ADVISORY)


def is_critical_fail(verdict: Optional[dict]) -> bool:
    """The manual-publish gate: a CRITICAL fail (a guide-forbidden voice term or a banned
    regulated claim). Non-critical failures (CTA / platform / image) are advisory on the
    human path."""
    if not verdict:
        return False
    return verdict.get("verdict") == qa_signals.FAIL and bool(verdict.get("critical"))


def critical_terms(verdict: Optional[dict]) -> list[str]:
    """The critical findings (labels + notes) — for the block message / notification."""
    return list((verdict or {}).get("critical") or [])


def persist_verdict(draft_id: str, verdict: dict) -> None:
    """Store the verdict on the draft (surfaced in the Drafts UI). Best-effort."""
    try:
        _sb().table("social_drafts").update(
            {"qa_verdict": verdict, "updated_at": "now()"}
        ).eq("id", draft_id).execute()
    except Exception as exc:  # noqa: BLE001 — persistence is best-effort
        logger.warning("social.qa_persist_failed", extra={"draft_id": draft_id, "error": str(exc)[:160]})
