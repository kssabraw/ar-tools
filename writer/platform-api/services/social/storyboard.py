"""Social Media module — the Video Storyboard engine (P5 slice a, PRD §5 Deferred → started).

Given a Source (topic / URL / blog run / saved Local SEO page) + a platform (an
Instagram or Facebook **Reel**, or a **YouTube Short**) + an optional angle/tone,
generate a structured, brand-voiced, competitor-informed **shot-by-shot storyboard**
the client (or the agency videographer) uses to shoot the video.

This slice produces the **brief only — no rendered or assembled video, and no new
vendor** (owner decision Q1 = a, 2026-09-19; scope doc ``p5-video-scope-v1_0.md``,
plan ``p5-video-plan-v1_0.md``). It reuses the Creator's Source loader + voice context
+ P1 competitor grounding + the forced-tool LLM path verbatim, and persists the result
to ``social_storyboards`` (a distinct deliverable, not a publishable ``social_drafts``
row). The only paid external call in the whole slice is the OPTIONAL thumbnail, which
reuses the already-built, freeze-gated, fail-closed-budget-metered image path.

Pure helpers (``platform_video_guidance``, ``build_storyboard_prompt``,
``sanitize_storyboard``) are unit-tested; the impure ``generate_storyboard`` / CRUD
isolate the DB + LLM.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from config import settings

logger = logging.getLogger(__name__)

# The video platforms this slice storyboards (Reels + Shorts, owner Q3).
STORYBOARD_PLATFORMS = {"instagram", "facebook", "youtube"}


# ── pure helpers (no network / DB — unit-tested) ─────────────────────────────

def platform_video_guidance(platform: str, fmt: str) -> str:
    """Per-platform native short-form-video guidance folded into the prompt. Pure.
    All three are vertical 9:16, hook-first, sound-on; the differences are framing +
    length conventions."""
    p = (platform or "").lower()
    if p == "youtube":
        return (
            "Platform: YouTube Short — vertical 9:16, up to ~60 seconds. Open with an "
            "immediate hook in the first 2–3 seconds (no slow intro), keep a brisk pace, "
            "and end with a clear next step. On-screen text reinforces the spoken point."
        )
    if p == "instagram":
        return (
            "Platform: Instagram Reel — vertical 9:16, ~15–45 seconds, sound-on. Lead "
            "with a scroll-stopping visual + hook line, keep shots short, use on-screen "
            "captions throughout (many watch muted), and land a clear call to action."
        )
    if p == "facebook":
        return (
            "Platform: Facebook Reel — vertical 9:16, ~15–45 seconds. Warm and direct, a "
            "strong opening hook, on-screen captions throughout, and a friendly call to "
            "action a local business owner would use."
        )
    return (
        "Platform: short-form vertical video (9:16). Hook in the first 3 seconds, short "
        "shots, on-screen captions throughout, a clear call to action at the end."
    )


_SYSTEM_PROMPT = (
    "You are a senior short-form video director for a marketing agency. You turn a "
    "business's existing content into a shoot-ready STORYBOARD for a vertical Reel or "
    "Short — a shot-by-shot plan the business can film themselves. Rules you MUST follow:\n"
    "- Match the business's brand voice when given; it wins on tone, word choice, "
    "grammatical person, and call-to-action wording.\n"
    "- NEVER invent facts, offers, prices, discounts, dates, statistics, guarantees, or "
    "claims not present in the material you're given. If you have little to work with, "
    "keep shots general rather than fabricating specifics.\n"
    "- Design for the platform's format: vertical 9:16, hook in the first ~3 seconds, "
    "short shots, on-screen captions, a clear call to action.\n"
    "- Each shot needs a concrete VISUAL the client can actually film (a talking-head "
    "line, a b-roll clip of the work, a product close-up, a text card) — not an abstract "
    "idea. Give on-screen text and, where it helps, a short voiceover/script line.\n"
    "- No medical, legal, or other regulated claims."
)

_STORYBOARD_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "A short working title for the video (2–6 words)."},
        "hook": {"type": "string", "description": "The first ~3 seconds — the scroll-stopping opening line/visual."},
        "duration_seconds": {"type": "integer", "description": "Target total length in seconds (15–60)."},
        "shots": {
            "type": "array",
            "description": "Ordered shots, in filming order.",
            "items": {
                "type": "object",
                "properties": {
                    "visual": {"type": "string", "description": "What the shot shows — a concrete, filmable visual."},
                    "on_screen_text": {"type": "string", "description": "Text overlay for this shot (captions)."},
                    "voiceover": {"type": "string", "description": "Spoken line/script for this shot, if any."},
                    "duration_seconds": {"type": "integer", "description": "Rough length of this shot in seconds."},
                    "b_roll": {"type": "boolean", "description": "True if this is b-roll rather than talking-head."},
                },
                "required": ["visual"],
            },
        },
        "music": {"type": "string", "description": "Audio / music mood direction (a style, not a specific copyrighted track)."},
        "caption": {"type": "string", "description": "The post caption to use when publishing the finished video."},
        "hashtags": {"type": "array", "items": {"type": "string"}, "description": "Relevant hashtags (no leading #)."},
        "cta": {"type": "string", "description": "The call to action."},
    },
    "required": ["hook", "shots"],
}


def build_storyboard_prompt(
    *,
    platform: str,
    fmt: str,
    source_title: Optional[str],
    source_text: str,
    angle: Optional[str],
    tone: Optional[str],
    client_context: str,
    voice_block: str,
    competitor_signals_block: str = "",
) -> str:
    """Assemble the user prompt for a storyboard. Pure. The competitor-signals block
    (P1) is optional grounding (empty ⇒ byte-identical). The voice block is appended
    LAST so it wins on expression (the suite's late-high-priority-block pattern)."""
    ask: list[str] = [
        platform_video_guidance(platform, fmt),
        "Plan a shoot-ready storyboard for this video.",
    ]
    if angle:
        ask.append(f"Angle / hook to take: {angle}")
    if tone:
        ask.append(f"Tone: {tone}")
    src = (source_text or "").strip()
    if src:
        ask.append(
            "Base the storyboard ONLY on this source content — do not invent facts, prices, "
            "dates, or claims not present here.\n"
            f"Source title: {source_title or 'n/a'}.\n"
            f"--- SOURCE ---\n{src}\n--- END SOURCE ---"
        )
    elif source_title:
        ask.append(f"Topic: {source_title}")

    user = client_context + "\n\n" + "\n".join(ask)
    if competitor_signals_block:
        user += "\n\n" + competitor_signals_block
    if voice_block:
        user += "\n\n" + voice_block
    return user


def _coerce_int(v, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def sanitize_storyboard(raw, max_shots: int) -> dict:
    """Clean the model's storyboard: coerce types, drop empty shots, cap at
    ``max_shots``, and guarantee a non-empty hook + at least one shot. Pure
    (unit-tested). Raises HTTPException(502) only when there is nothing usable at all."""
    data = raw if isinstance(raw, dict) else {}
    hook = (data.get("hook") or "").strip()

    shots: list[dict] = []
    for s in (data.get("shots") or []):
        if not isinstance(s, dict):
            continue
        visual = (s.get("visual") or "").strip()
        if not visual:
            continue
        shot: dict = {"n": len(shots) + 1, "visual": visual[:600]}
        ost = (s.get("on_screen_text") or "").strip()
        if ost:
            shot["on_screen_text"] = ost[:300]
        vo = (s.get("voiceover") or "").strip()
        if vo:
            shot["voiceover"] = vo[:600]
        dur = _coerce_int(s.get("duration_seconds"))
        if dur and dur > 0:
            shot["duration_seconds"] = min(dur, 600)
        if isinstance(s.get("b_roll"), bool):
            shot["b_roll"] = s["b_roll"]
        shots.append(shot)
        if len(shots) >= max(1, int(max_shots)):
            break

    if not shots and not hook:
        raise HTTPException(status_code=502, detail="social_storyboard_empty")
    if not hook and shots:
        hook = shots[0]["visual"][:200]

    hashtags = [
        h.lstrip("#").strip()
        for h in (data.get("hashtags") or [])
        if isinstance(h, str) and h.strip()
    ][:15]

    return {
        "hook": hook,
        "duration_seconds": _coerce_int(data.get("duration_seconds")),
        "shots": shots,
        "music": (data.get("music") or "").strip() or None,
        "caption": (data.get("caption") or "").strip() or None,
        "hashtags": hashtags,
        "cta": (data.get("cta") or "").strip() or None,
    }


# ── impure layer ─────────────────────────────────────────────────────────────

def _assert_enabled() -> None:
    if not settings.social_enabled:
        raise HTTPException(status_code=503, detail="social_not_enabled")


def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


async def generate_storyboard(client_id: str, req, user_id: Optional[str] = None) -> dict:
    """Generate a shot-by-shot video storyboard from a Source and persist it. Loads the
    source + the client's voice context ONCE, folds in the latest competitor signals
    (P1, best-effort), runs one bounded forced-tool Sonnet call, sanitizes, records a
    best-effort voice advisory (NOT auto-corrected — a storyboard is a brief a human
    finishes), and stores a ``social_storyboards`` row. No video is generated."""
    _assert_enabled()
    from services.social import creator

    platform = (req.platform or "").lower()
    if platform not in STORYBOARD_PLATFORMS:
        raise HTTPException(status_code=422, detail="social_storyboard_bad_platform")
    fmt = (req.format or "reel").lower()

    source_title, source_text, source_ref = await creator.load_source(
        client_id, req.source_type, source_id=req.source_id, url=req.url, text=req.text
    )
    card, voice_block, client_context = await creator.resolve_voice_context(
        creator._client_row(client_id), user_id
    )

    # P1 grounding — react to what's working in the niche (empty ⇒ prompt unchanged).
    from services.social import competitor_research

    signals_block = competitor_research.render_competitor_signals_block(
        competitor_research.latest_signals_for_client(client_id)
    )

    from services import report_llm

    try:
        out = await report_llm.run_forced_tool(
            provider="anthropic", model=settings.social_storyboard_model,
            system=_SYSTEM_PROMPT,
            user=build_storyboard_prompt(
                platform=platform, fmt=fmt, source_title=source_title, source_text=source_text,
                angle=req.angle, tone=req.tone, client_context=client_context,
                voice_block=voice_block, competitor_signals_block=signals_block,
            ),
            tool_name="emit_storyboard",
            tool_description="Return the shot-by-shot video storyboard.",
            input_schema=_STORYBOARD_SCHEMA,
            max_tokens=int(settings.social_storyboard_max_tokens),
            log_tag="social_storyboard",
        )
    except Exception as exc:  # noqa: BLE001 — clean provider error
        logger.warning("social.storyboard_failed", extra={"error": str(getattr(exc, "detail", exc))[:200]})
        raise HTTPException(status_code=502, detail="social_storyboard_failed") from exc

    board = sanitize_storyboard(out, int(settings.social_storyboard_max_shots))
    title = (out.get("title") or "").strip() or source_title or None

    # Best-effort voice advisory over the human-facing text (caption + on-screen text).
    # Advisory only — a storyboard is edited by a human before it's shot, so we surface
    # forbidden-term hits rather than running the copy corrective-rewrite loop.
    from services import gbp_posts_service

    advisory_text = " ".join(
        [board.get("caption") or "", board.get("hook") or ""]
        + [s.get("on_screen_text") or "" for s in board.get("shots", [])]
    )
    voice_warnings = [f"forbidden_term:{h}" for h in gbp_posts_service.voice_forbidden_hits(advisory_text, card)]

    row = {
        "client_id": client_id,
        "platform": platform,
        "format": fmt,
        "source_type": (req.source_type or "topic"),
        "source_ref": source_ref,
        "source_title": source_title,
        "source_version": creator.source_version_of(source_text),
        "angle": req.angle,
        "tone": req.tone,
        "title": title,
        "storyboard": board,
        "voice_warnings": voice_warnings or None,
        "status": "generated",
        "created_by": user_id,
    }
    inserted = (_sb().table("social_storyboards").insert(row).execute()).data or []
    if not inserted:
        raise HTTPException(status_code=500, detail="social_storyboard_persist_failed")
    return inserted[0]


def list_storyboards(client_id: str, limit: int = 100) -> list[dict]:
    return (
        _sb().table("social_storyboards").select("*").eq("client_id", client_id)
        .neq("status", "archived").order("created_at", desc=True).limit(limit).execute()
    ).data or []


def get_storyboard(storyboard_id: str) -> dict:
    rows = (
        _sb().table("social_storyboards").select("*").eq("id", storyboard_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="social_storyboard_not_found")
    return rows[0]


def update_storyboard(
    storyboard_id: str,
    *,
    title: Optional[str] = None,
    storyboard: Optional[dict] = None,
    thumbnail_url: Optional[str] = None,
) -> dict:
    """Human edit of a storyboard (title / the shot-list body / thumbnail). Only
    provided fields change."""
    get_storyboard(storyboard_id)  # 404 if missing
    fields: dict = {"updated_at": "now()"}
    if title is not None:
        fields["title"] = title.strip() or None
    if storyboard is not None:
        fields["storyboard"] = storyboard
    if thumbnail_url is not None:
        fields["thumbnail_url"] = thumbnail_url.strip() or None
    (_sb().table("social_storyboards").update(fields).eq("id", storyboard_id).execute())
    return get_storyboard(storyboard_id)


def delete_storyboard(storyboard_id: str) -> dict:
    get_storyboard(storyboard_id)  # 404 if missing
    (
        _sb().table("social_storyboards").update({"status": "archived", "updated_at": "now()"})
        .eq("id", storyboard_id).execute()
    )
    return {"ok": True}


async def generate_thumbnail(client_id: str, storyboard_id: str, user_id: Optional[str] = None) -> dict:
    """Generate + attach a 9:16 thumbnail for a storyboard. Reuses the built social
    image path (freeze-gated + fail-closed budget-metered). The description is derived
    from the storyboard's own hook/title — no new prompt surface."""
    _assert_enabled()
    board_row = get_storyboard(storyboard_id)
    if str(board_row.get("client_id")) != str(client_id):
        raise HTTPException(status_code=404, detail="social_storyboard_not_found")

    body = board_row.get("storyboard") or {}
    description = (board_row.get("title") or body.get("hook") or board_row.get("source_title") or "").strip()
    if not description:
        raise HTTPException(status_code=422, detail="social_storyboard_no_thumbnail_seed")

    from services.social import image as social_image
    from models.social import SocialGenerateImageRequest

    # A Reel/Short thumbnail is vertical 9:16 on every platform — fmt="reel" forces it
    # (resolve_aspect_ratio maps reel/story → 9:16 regardless of platform).
    img_req = SocialGenerateImageRequest(
        platform=board_row.get("platform") or "instagram",
        format="reel",
        description=description,
    )
    result = await social_image.generate_image(client_id, img_req, user_id=user_id)
    return update_storyboard(storyboard_id, thumbnail_url=result.get("url"))
