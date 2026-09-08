"""Social Media module — the Creator's copy engine (PRD §7, first slice).

Given a Source (a topic, a URL, a blog run, or a saved Local SEO page) and a
target platform, generate platform-native post copy — grounded in the source,
tailored to the platform, and enforced against the client's distilled Voice &
Audience Card (the same card the page/GBP writers use). One bounded Sonnet call
per request, with a corrective rewrite when a forbidden term slips through
(mirrors ``gbp_posts_service.draft_summary``).

Deliberately **stateless** for v1: this returns copy for the composer to drop
into the copy box; the real draft/post row is created at publish time by
``publish.create_post``. Multi-platform Angle fan-out + Draft persistence are the
larger P2 Creator, built on this.

Pure helpers (``platform_guidance``, ``build_copy_prompt``, ``clamp_copy``,
``sections_to_text``, ``source_version_of``) are unit-tested; the impure
``load_source`` / ``generate_copy`` isolate the DB + LLM + network.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from fastapi import HTTPException

from config import settings

logger = logging.getLogger(__name__)

# Source types the composer can draft from.
SOURCE_TYPES = {"topic", "url", "blog_run", "local_seo_page"}


# ── pure helpers (no network / DB — unit-tested) ─────────────────────────────

def source_version_of(text: str) -> str:
    """A short stable fingerprint of the source content, stamped on the response
    so a later edit of the source can be caught before publish (failure spec §3).
    Pure."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def clamp_copy(copy: str, char_limit: Optional[int]) -> str:
    """Trim generated copy to the platform character limit on a word boundary
    where possible. Pure."""
    copy = (copy or "").strip()
    if not char_limit or len(copy) <= int(char_limit):
        return copy
    limit = int(char_limit)
    cut = copy[:limit]
    # Prefer not to slice a word in half when there's a nearby space.
    sp = cut.rfind(" ")
    if sp >= limit - 30 and sp > 0:
        cut = cut[:sp]
    return cut.rstrip()


def sections_to_text(sections: list[dict], max_chars: int) -> str:
    """Flatten a blog article's sections (heading + HTML body) into plain text,
    capped at ``max_chars``. Pure (reuses illustration's section flattener)."""
    from services.illustration import section_text  # pure helper

    parts = [t for s in (sections or []) if (t := section_text(s).strip())]
    return "\n\n".join(parts)[: max(0, int(max_chars))]


def platform_guidance(platform: str, spec: Optional[dict], include_hashtags: bool) -> str:
    """Per-platform native-writing guidance folded into the prompt. Pure — the
    seeded Platform Spec supplies the hard limits; this supplies the style."""
    p = (platform or "").lower()
    char_limit = (spec or {}).get("char_limit")
    limit_txt = f" Keep it under {char_limit} characters." if char_limit else ""
    tags = "" if include_hashtags else " Do NOT add hashtags."
    if p in ("twitter", "x"):
        base = (
            "Platform: X (Twitter). One sharp idea, punchy and conversational."
            f"{limit_txt} At most 1–2 hashtags." + tags +
            " AVOID putting a link in the post — a URL there costs ~10× the credits; "
            "only include one if it's essential."
        )
    elif p == "facebook":
        base = (
            "Platform: Facebook. Warm and conversational — 1–3 short paragraphs a real "
            "owner would post. A light call to action at the end is good. Emoji sparingly."
            f"{limit_txt} Hashtags are optional and should be sparse." + tags
        )
    elif p == "instagram":
        base = (
            "Platform: Instagram caption. Open with a scroll-stopping hook line, then a "
            "few short lines with line breaks between thoughts."
            f"{limit_txt} Links are not clickable in captions — say 'link in bio' instead "
            "of pasting a URL. End with 3–8 relevant hashtags on their own line."
            + ("" if include_hashtags else " (Skip the hashtags for now.)")
        )
    elif p == "pinterest":
        base = (
            "Platform: Pinterest pin description. Keyword-rich and descriptive so it's "
            "discoverable in search — say clearly what the pin is about and who it helps."
            f"{limit_txt} A few relevant keywords/hashtags at the end are fine." + tags
        )
    elif p == "linkedin":
        base = (
            "Platform: LinkedIn. Professional and value-first, no fluff. A strong first "
            "line, then a few short paragraphs."
            f"{limit_txt} At most 2–3 hashtags." + tags
        )
    elif p == "threads":
        base = "Platform: Threads. Casual and conversational, one idea." + limit_txt + tags
    elif p == "youtube":
        base = (
            "Platform: YouTube. Write a compelling title-and-description style caption."
            + limit_txt + tags
        )
    else:
        base = "Write a native social post for this platform." + limit_txt + tags
    return base


_SYSTEM_PROMPT = (
    "You are a senior social media copywriter for a marketing agency. You write "
    "on-brand, platform-native posts that sound like the business, not like an ad "
    "template. Rules you MUST follow:\n"
    "- Match the business's brand voice when given; it wins on tone, word choice, "
    "grammatical person, and call-to-action wording.\n"
    "- NEVER invent facts, offers, prices, discounts, dates, statistics, guarantees, "
    "or claims that are not in the material you're given. If you have little to work "
    "with, keep it general rather than fabricating specifics.\n"
    "- Write for the target platform's format and length.\n"
    "- No medical, legal, or other regulated claims.\n"
    "Return ONLY the post text — no preamble, no quotes, no markdown, no labels."
)


def build_copy_prompt(
    *,
    platform: str,
    spec: Optional[dict],
    source_title: Optional[str],
    source_text: str,
    angle: Optional[str],
    tone: Optional[str],
    fmt: str,
    include_hashtags: bool,
    client_context: str,
    voice_block: str,
) -> tuple[str, str]:
    """Assemble the (system, user) prompt for one platform's copy. Pure. The
    voice block, when present, is appended LAST so it wins on expression (the
    late-high-priority-block pattern used across the suite's writers)."""
    ask: list[str] = [platform_guidance(platform, spec, include_hashtags)]
    if fmt and fmt not in ("feed", "pin"):
        ask.append(f"This is for a {fmt}.")
    if angle:
        ask.append(f"Angle / hook to take: {angle}")
    if tone:
        ask.append(f"Tone: {tone}")
    src = (source_text or "").strip()
    if src:
        ask.append(
            "Base the post ONLY on this source content — do not invent facts, prices, "
            "dates, or claims not present here.\n"
            f"Source title: {source_title or 'n/a'}.\n"
            f"--- SOURCE ---\n{src}\n--- END SOURCE ---"
        )
    elif source_title:
        ask.append(f"Topic: {source_title}")

    user = client_context + "\n\n" + "\n".join(ask)
    if voice_block:
        user += "\n\n" + voice_block
    return _SYSTEM_PROMPT, user


# ── impure layer ─────────────────────────────────────────────────────────────

def _assert_enabled() -> None:
    if not settings.social_enabled:
        raise HTTPException(status_code=503, detail="social_not_enabled")


def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


def _client_row(client_id: str) -> dict:
    rows = (
        _sb().table("clients")
        .select("id, name, website_url, business_location, brand_voice, detected_icp, differentiators")
        .eq("id", client_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="client_not_found")
    return rows[0]


async def load_source(
    client_id: str,
    source_type: str,
    *,
    source_id: Optional[str] = None,
    url: Optional[str] = None,
    text: Optional[str] = None,
) -> tuple[Optional[str], str, dict]:
    """Resolve a requested Source to (title, plain_text, source_ref). Content reads
    are scoped to the client (a client can only repurpose its own content). Raises
    HTTPException on a bad/unreachable source. Shared by the single-copy draft and
    the fan-out (which loads the source ONCE for all platforms)."""
    st = (source_type or "topic").lower()
    if st not in SOURCE_TYPES:
        raise HTTPException(status_code=422, detail="social_bad_source_type")
    cap = int(settings.social_copy_source_max_chars)

    if st == "topic":
        txt = (text or "").strip()
        if not txt:
            raise HTTPException(status_code=422, detail="social_source_empty")
        return None, txt[:cap], {"type": "topic"}

    if st == "url":
        u = (url or "").strip()
        if not u:
            raise HTTPException(status_code=422, detail="social_source_url_required")
        from services.syndication_rewrite import RewriteError, extract_source_content

        try:
            title, markdown = await extract_source_content(u)
        except RewriteError as exc:
            raise HTTPException(status_code=422, detail=f"social_source_fetch_failed:{exc}")
        except Exception as exc:  # noqa: BLE001 — network/parse failures are user-facing
            raise HTTPException(status_code=502, detail="social_source_fetch_error") from exc
        return title, (markdown or "")[:cap], {"type": "url", "url": u}

    if st == "blog_run":
        run_id = (source_id or "").strip()
        if not run_id:
            raise HTTPException(status_code=422, detail="social_source_id_required")
        sb = _sb()
        run_rows = (
            sb.table("runs").select("id, keyword")
            .eq("id", run_id).eq("client_id", client_id).limit(1).execute()
        ).data or []
        if not run_rows:
            raise HTTPException(status_code=404, detail="social_source_not_found")
        from services.illustration import _load_article

        body = sections_to_text(_load_article(sb, run_id), cap)
        return run_rows[0].get("keyword"), body, {"type": "blog_run", "run_id": run_id}

    # local_seo_page
    page_id = (source_id or "").strip()
    if not page_id:
        raise HTTPException(status_code=422, detail="social_source_id_required")
    from services.illustration import strip_html

    rows = (
        _sb().table("local_seo_pages").select("id, page_title, content_html")
        .eq("id", page_id).eq("client_id", client_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="social_source_not_found")
    body = strip_html(rows[0].get("content_html") or "")[:cap]
    return rows[0].get("page_title"), body, {"type": "local_seo_page", "page_id": page_id}


def _platform_spec(platform: str) -> Optional[dict]:
    from services.social import publish

    return publish._platform_spec(platform)


async def resolve_voice_context(
    client: dict, user_id: Optional[str] = None
) -> tuple[dict, str, str]:
    """(voice_card, rendered voice block, client context) for a client — resolved
    ONCE and reused across every platform in a fan-out. Voice is best-effort (an
    empty card means no enforcement)."""
    from services import gbp_posts_service, voice_card_service

    card: dict = {}
    try:
        card = await voice_card_service.get_voice_card(client, user_id=user_id) or {}
    except Exception as exc:  # noqa: BLE001 — voice is best-effort
        logger.info("social.voice_card_unavailable", extra={"error": str(exc)[:200]})
    return card, gbp_posts_service.render_voice_card_block(card), gbp_posts_service.build_client_context(client)


async def _copy_llm(system: str, user: str) -> str:
    """One bounded social-copy completion (Anthropic, provider-failover)."""
    from services import report_llm

    return await report_llm.generate_text(
        system=system, user=user, max_tokens=int(settings.social_copy_max_tokens),
        provider="anthropic", model=settings.social_copy_model, log_tag="social_copy",
    )


async def draft_platform_copy(
    *,
    platform: str,
    spec: Optional[dict],
    fmt: str,
    source_title: Optional[str],
    source_text: str,
    angle: Optional[str],
    tone: Optional[str],
    include_hashtags: bool,
    card: dict,
    voice_block: str,
    client_context: str,
) -> tuple[str, list[str], list[str]]:
    """Generate + voice-enforce copy for ONE platform from an already-loaded source
    and voice context. Returns (copy, voice_warnings, spec_warnings). The reusable
    core of both the single-copy draft and the fan-out. Raises HTTPException(502)
    when the model call fails outright."""
    from services import gbp_posts_service

    system, user = build_copy_prompt(
        platform=platform, spec=spec, source_title=source_title, source_text=source_text,
        angle=angle, tone=tone, fmt=fmt, include_hashtags=include_hashtags,
        client_context=client_context, voice_block=voice_block,
    )
    try:
        text = await _copy_llm(system, user)
    except Exception as exc:  # noqa: BLE001 — surface as a clean provider error
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("social.copy_generation_failed", extra={"error": str(detail)[:200]})
        raise HTTPException(status_code=502, detail="social_copy_generation_failed") from exc

    char_limit = (spec or {}).get("char_limit")
    text = clamp_copy(text, char_limit)

    # Enforcement: a forbidden term is provable — corrective rewrites to remove it,
    # keeping whichever pass has the fewest hits (a rewrite can never make it worse).
    hits = gbp_posts_service.voice_forbidden_hits(text, card)
    passes = 0
    while hits and passes < int(settings.social_copy_max_correction_passes):
        passes += 1
        fix_user = (
            "Rewrite this social post to REMOVE these forbidden words/phrases entirely "
            f"(and any close variant): {', '.join(hits)}. Keep the same meaning, the same "
            "brand voice, and the platform's length. Return ONLY the post.\n\n" + text
        )
        if voice_block:
            fix_user = voice_block + "\n\n" + fix_user
        try:
            rewritten = clamp_copy(await _copy_llm(system, fix_user), char_limit)
        except Exception as exc:  # noqa: BLE001 — enforcement is best-effort
            logger.info("social.voice_correction_failed", extra={"error": str(exc)[:200]})
            break
        new_hits = gbp_posts_service.voice_forbidden_hits(rewritten, card)
        if rewritten and len(new_hits) < len(hits):
            text, hits = rewritten, new_hits
        else:
            break

    voice_warnings = [f"forbidden_term:{h}" for h in hits]
    spec_warnings: list[str] = []
    if platform in ("twitter", "x"):
        from services.social.postpeer_adapter import x_credit_cost

        if x_credit_cost(platform, text) >= 50:
            spec_warnings.append("x_link_post_50_credits")
    return text, voice_warnings, spec_warnings


_ANGLES_SYSTEM = (
    "You are a senior social media strategist. Given a piece of source material for "
    "a business, propose DISTINCT editorial angles to turn it into social posts — "
    "different takes on the SAME source, not restatements. Draw from patterns like "
    "myth-bust, customer-pain story, quick-tips list, behind-the-scenes/authority, "
    "seasonal/timely hook, before/after proof, or a common-question answer — but only "
    "those that genuinely fit the material. Ground every angle in the business's brand "
    "voice and its real customer. Never invent facts, offers, or claims not supported "
    "by the source."
)

_ANGLE_SCHEMA = {
    "type": "object",
    "properties": {
        "angles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short name for the angle (2–5 words)."},
                    "hook": {"type": "string", "description": "The opening line or core idea, one sentence."},
                    "description": {"type": "string", "description": "One sentence on what this angle covers."},
                },
                "required": ["title", "hook"],
            },
        }
    },
    "required": ["angles"],
}


def build_angles_prompt(
    client_context: str, source_title: Optional[str], source_text: str, voice_block: str, count: int
) -> str:
    """Assemble the angle-proposal prompt. Pure."""
    parts = [client_context, f"\nPropose {count} distinct social-post angles for this source."]
    src = (source_text or "").strip()
    if src:
        parts.append(
            f"Source title: {source_title or 'n/a'}.\n--- SOURCE ---\n{src}\n--- END SOURCE ---"
        )
    elif source_title:
        parts.append(f"Topic: {source_title}")
    user = "\n".join(parts)
    if voice_block:
        user += "\n\n" + voice_block
    return user


def sanitize_angles(raw, count: int) -> list[dict]:
    """Clean the model's angle list: drop empties, keep {title, hook, description},
    cap at `count`. Pure (unit-tested)."""
    out: list[dict] = []
    for a in (raw or []):
        if not isinstance(a, dict):
            continue
        title = (a.get("title") or "").strip()
        hook = (a.get("hook") or "").strip()
        desc = (a.get("description") or "").strip()
        if not (title or hook):
            continue
        out.append({"title": title or hook[:60], "hook": hook, "description": desc})
        if len(out) >= max(1, count):
            break
    return out


async def propose_angles(client_id: str, req, user_id: Optional[str] = None) -> list[dict]:
    """Propose distinct editorial angles for a Source (PRD §7). Stateless — angles
    are stored on the Draft set a fan-out produces, not here."""
    _assert_enabled()
    source_title, source_text, source_ref = await load_source(
        client_id, req.source_type, source_id=req.source_id, url=req.url, text=req.text
    )
    card, voice_block, client_context = await resolve_voice_context(_client_row(client_id), user_id)
    count = int(settings.social_angles_count)
    from services import report_llm

    try:
        out = await report_llm.run_forced_tool(
            provider="anthropic", model=settings.social_copy_model,
            system=_ANGLES_SYSTEM,
            user=build_angles_prompt(client_context, source_title, source_text, voice_block, count),
            tool_name="emit_angles", tool_description="Return the proposed social-post angles.",
            input_schema=_ANGLE_SCHEMA, max_tokens=int(settings.social_angles_max_tokens),
            log_tag="social_angles",
        )
    except Exception as exc:  # noqa: BLE001 — clean provider error
        logger.warning("social.angles_failed", extra={"error": str(getattr(exc, 'detail', exc))[:200]})
        raise HTTPException(status_code=502, detail="social_angles_failed") from exc
    return sanitize_angles(out.get("angles"), count)


async def generate_copy(client_id: str, req, user_id: Optional[str] = None) -> dict:
    """Draft platform-native copy for the composer. Loads the source, resolves the
    client's voice card, generates one bounded Sonnet completion, runs a corrective
    rewrite if a forbidden term appears, clamps to the platform limit, and returns
    the copy plus voice/spec advisories. Stateless — nothing is persisted."""
    _assert_enabled()
    platform = (req.platform or "").lower()
    if not platform:
        raise HTTPException(status_code=422, detail="social_platform_required")

    spec = _platform_spec(platform)
    source_title, source_text, source_ref = await load_source(
        client_id, req.source_type, source_id=req.source_id, url=req.url, text=req.text
    )
    notes: list[str] = []
    if source_ref.get("type") != "topic" and not source_text.strip():
        notes.append("no_source_content")

    card, voice_block, client_context = await resolve_voice_context(_client_row(client_id), user_id)
    text, voice_warnings, spec_warnings = await draft_platform_copy(
        platform=platform, spec=spec, fmt=(req.format or "feed"),
        source_title=source_title, source_text=source_text, angle=req.angle, tone=req.tone,
        include_hashtags=bool(getattr(req, "include_hashtags", True)),
        card=card, voice_block=voice_block, client_context=client_context,
    )
    if voice_warnings:
        notes.append("voice_uncorrected")

    char_limit = (spec or {}).get("char_limit")
    char_count = len(text)
    return {
        "copy": text,
        "platform": platform,
        "char_count": char_count,
        "char_limit": char_limit,
        "over_limit": bool(char_limit and char_count > int(char_limit)),
        "source_title": source_title,
        "source_version": source_version_of(source_text),
        "angle": req.angle,
        "voice_warnings": voice_warnings,
        "spec_warnings": spec_warnings,
        "notes": notes,
    }
