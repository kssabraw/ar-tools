"""Social Media P1 — the Apify client + per-platform post parsers (ADR-0002).

Analyze-in-place competitor research: Apify actors read a competitor's PUBLIC,
logged-out posts (post text + engagement + captions). We **never** download or
re-host competitor media — the parsers keep post URLs and numbers, not media.
Owner decision c1: TwelveLabs is dropped, so there is **no video-content
analysis** — YouTube signals are titles/descriptions/tags/engagement/
thumbnail-links only, the same text+metadata class as every other platform.

Design mirrors ``postpeer_adapter.py``: the pure helpers (actor-path mapping,
per-platform input builders, per-platform post parsers) are unit-tested with no
network; the one live call (``run_actor``) is a synchronous ``httpx`` request run
via ``asyncio.to_thread`` from the async job.

Actor ids are config-driven (``settings.social_apify_actor_*``) and env-overridable
so an actor can be swapped without a code change; the API path form is
``username~actor-name`` (we map ``/``→``~``). A platform whose actor id is blank is
skipped by the caller. Swapping an actor whose output schema differs may require
adjusting that platform's input builder / parser.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Platforms we ship parsers for (v1). LinkedIn is a deliberate gap (public
# scraping is fragile/ToS-sensitive) — its actor id stays blank until set.
SUPPORTED_PLATFORMS = ("instagram", "facebook", "twitter", "youtube", "pinterest")

_MEDIA_IMAGE = "image"
_MEDIA_VIDEO = "video"
_MEDIA_CAROUSEL = "carousel"
_MEDIA_UNKNOWN = "unknown"


class ApifyError(Exception):
    """A failed Apify actor run (transport, non-2xx, or empty). Best-effort
    callers swallow it into an 'insufficient_data' signal for that handle."""


# ── pure helpers (no network — unit-tested) ──────────────────────────────────

def actor_path(actor_id: str) -> str:
    """Apify API path form of an actor id: ``username/actor`` → ``username~actor``.
    Already-tilde ids and bare ids pass through. Pure."""
    return (actor_id or "").strip().replace("/", "~")


def actor_for_platform(platform: str) -> str:
    """The configured actor id for a platform ('' when unconfigured). Pure over
    settings."""
    return {
        "instagram": settings.social_apify_actor_instagram,
        "facebook": settings.social_apify_actor_facebook,
        "twitter": settings.social_apify_actor_twitter,
        "x": settings.social_apify_actor_twitter,
        "youtube": settings.social_apify_actor_youtube,
        "pinterest": settings.social_apify_actor_pinterest,
    }.get((platform or "").lower(), "")


def normalize_handle(handle: str) -> str:
    """A bare handle: strip a leading '@' and any wrapping whitespace/url. Pure."""
    h = (handle or "").strip()
    if h.startswith("@"):
        h = h[1:]
    # Tolerate someone pasting a full profile URL: keep the last non-empty segment.
    if "://" in h or h.startswith("www."):
        parts = [p for p in h.split("/") if p and "." not in p]
        if parts:
            h = parts[-1]
    return h.lstrip("@").strip()


def _profile_url(platform: str, handle: str) -> str:
    h = normalize_handle(handle)
    return {
        "instagram": f"https://www.instagram.com/{h}/",
        "facebook": f"https://www.facebook.com/{h}",
        "youtube": f"https://www.youtube.com/@{h}/videos",
        "pinterest": f"https://www.pinterest.com/{h}/",
    }.get((platform or "").lower(), f"https://www.{platform}.com/{h}")


def build_actor_input(platform: str, handle: str, max_items: int) -> dict:
    """The run input for a platform's actor. Shapes match the DEFAULT actors in
    config; a swapped actor with a different input schema may need adjusting here.
    Pure."""
    pl = (platform or "").lower()
    h = normalize_handle(handle)
    n = max(1, int(max_items))
    if pl == "instagram":
        return {"directUrls": [_profile_url("instagram", h)],
                "resultsType": "posts", "resultsLimit": n, "addParentData": False}
    if pl == "facebook":
        return {"startUrls": [{"url": _profile_url("facebook", h)}], "resultsLimit": n}
    if pl in ("twitter", "x"):
        return {"twitterHandles": [h], "maxItems": n, "sort": "Latest",
                "includeSearchTerms": False}
    if pl == "youtube":
        return {"startUrls": [{"url": _profile_url("youtube", h)}], "maxResults": n,
                "maxResultsShorts": 0, "sortVideosBy": "NEWEST"}
    if pl == "pinterest":
        return {"startUrls": [{"url": _profile_url("pinterest", h)}], "maxItems": n}
    return {"startUrls": [{"url": _profile_url(pl, h)}], "maxItems": n}


def _first(d: dict, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _to_int(v) -> int:
    """Coerce a count that may be int / float / '1,234' / '1.2K' / None → int. Pure."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace(",", "")
    if not s:
        return 0
    mult = 1
    if s[-1:].lower() in ("k", "m", "b"):
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[s[-1].lower()]
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except (TypeError, ValueError):
        return 0


def parse_timestamp(raw) -> Optional[str]:
    """Best-effort → ISO-8601 UTC string, else None. Accepts ISO strings, unix
    epoch seconds (int/float/numeric string), and Twitter's ctime format. Pure."""
    if raw is None or raw == "":
        return None
    # Numeric epoch seconds.
    if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.strip().isdigit()):
        try:
            return datetime.fromtimestamp(int(float(raw)), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return None
    s = str(raw).strip()
    # ISO-8601 (tolerate a trailing Z).
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    # Twitter ctime, e.g. "Wed Sep 10 07:00:00 +0000 2025".
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            continue
    return None


def _post(url, caption, *, likes=0, comments=0, shares=0, views=0,
          published_at=None, media_type=_MEDIA_UNKNOWN) -> dict:
    """The normalized post shape every parser returns. Links + numbers + caption
    TEXT only — never media bytes/urls of the media itself beyond the post link."""
    return {
        "url": (str(url).strip() if url else None),
        "caption": (str(caption).strip() if caption else ""),
        "likes": _to_int(likes),
        "comments": _to_int(comments),
        "shares": _to_int(shares),
        "views": _to_int(views),
        "published_at": parse_timestamp(published_at),
        "media_type": media_type or _MEDIA_UNKNOWN,
    }


def _ig_media_type(raw: dict) -> str:
    t = str(_first(raw, "type", "__typename", default="")).lower()
    if "sidecar" in t or (raw.get("childPosts") or raw.get("images")):
        return _MEDIA_CAROUSEL
    if "video" in t or raw.get("productType") in ("clips", "igtv") or raw.get("videoUrl"):
        return _MEDIA_VIDEO
    if "image" in t or raw.get("displayUrl"):
        return _MEDIA_IMAGE
    return _MEDIA_UNKNOWN


def parse_instagram(raw: dict) -> dict:
    return _post(
        _first(raw, "url", "postUrl", "inputUrl"),
        _first(raw, "caption", "text", default=""),
        likes=_first(raw, "likesCount", "likes", default=0),
        comments=_first(raw, "commentsCount", "comments", default=0),
        views=_first(raw, "videoViewCount", "videoPlayCount", "viewsCount", default=0),
        published_at=_first(raw, "timestamp", "takenAt", "time"),
        media_type=_ig_media_type(raw),
    )


def _fb_media_type(raw: dict) -> str:
    if raw.get("video") or str(_first(raw, "type", default="")).lower() == "video":
        return _MEDIA_VIDEO
    media = raw.get("media") or raw.get("attachments")
    if isinstance(media, list) and len(media) > 1:
        return _MEDIA_CAROUSEL
    if media or raw.get("photo") or raw.get("image"):
        return _MEDIA_IMAGE
    return _MEDIA_UNKNOWN


def _fb_count(raw: dict, *keys) -> int:
    v = _first(raw, *keys)
    if isinstance(v, dict):  # some FB actors nest {"count": N}
        v = v.get("count") or v.get("total")
    return _to_int(v)


def parse_facebook(raw: dict) -> dict:
    return _post(
        _first(raw, "url", "postUrl", "topLevelUrl", "link"),
        _first(raw, "text", "message", "caption", default=""),
        likes=_fb_count(raw, "likes", "likesCount", "reactionsCount", "reactions"),
        comments=_fb_count(raw, "comments", "commentsCount"),
        shares=_fb_count(raw, "shares", "sharesCount", "shareCount"),
        views=_fb_count(raw, "viewsCount", "videoViewCount"),
        published_at=_first(raw, "time", "date", "timestamp", "publishedTime"),
        media_type=_fb_media_type(raw),
    )


def _x_media_type(raw: dict) -> str:
    ext = (raw.get("extendedEntities") or {}).get("media") or raw.get("media") or []
    if isinstance(ext, list) and ext:
        types = {str((m or {}).get("type", "")).lower() for m in ext if isinstance(m, dict)}
        if types & {"video", "animated_gif"}:
            return _MEDIA_VIDEO
        if len(ext) > 1:
            return _MEDIA_CAROUSEL
        return _MEDIA_IMAGE
    return _MEDIA_UNKNOWN


def parse_twitter(raw: dict) -> dict:
    return _post(
        _first(raw, "url", "twitterUrl", "tweetUrl"),
        _first(raw, "text", "fullText", "full_text", default=""),
        likes=_first(raw, "likeCount", "favoriteCount", "likes", default=0),
        comments=_first(raw, "replyCount", "replies", default=0),
        shares=_first(raw, "retweetCount", "retweets", default=0),
        views=_first(raw, "viewCount", "views", default=0),
        published_at=_first(raw, "createdAt", "created_at", "date"),
        media_type=_x_media_type(raw),
    )


def parse_youtube(raw: dict) -> dict:
    # YouTube's "caption" for our text rollup is the video TITLE (the strongest
    # topical signal); description is appended when short. No video content is read.
    title = str(_first(raw, "title", default="")).strip()
    desc = str(_first(raw, "text", "description", default="")).strip()
    caption = title if not desc else f"{title}\n{desc[:400]}"
    return _post(
        _first(raw, "url", "videoUrl", "watchUrl"),
        caption,
        likes=_first(raw, "likes", "likeCount", default=0),
        comments=_first(raw, "commentsCount", "commentCount", "comments", default=0),
        views=_first(raw, "viewCount", "numberOfViews", "views", default=0),
        published_at=_first(raw, "date", "uploadDate", "publishedAt", "publishDate"),
        media_type=_MEDIA_VIDEO,
    )


def parse_pinterest(raw: dict) -> dict:
    return _post(
        _first(raw, "url", "pinUrl", "link"),
        _first(raw, "title", "description", "grid_title", "gridTitle", default=""),
        likes=_first(raw, "repinCount", "repin_count", "saves", "saveCount", "reactionCount", default=0),
        comments=_first(raw, "commentCount", "comment_count", "comments", default=0),
        published_at=_first(raw, "createdAt", "created_at", "date"),
        media_type=_MEDIA_IMAGE,
    )


_PARSERS = {
    "instagram": parse_instagram,
    "facebook": parse_facebook,
    "twitter": parse_twitter,
    "x": parse_twitter,
    "youtube": parse_youtube,
    "pinterest": parse_pinterest,
}


def parse_posts(platform: str, items: list) -> list[dict]:
    """Normalize a raw Apify dataset into post dicts, dropping rows with no URL
    (error/summary rows some actors append). Pure."""
    fn = _PARSERS.get((platform or "").lower())
    if not fn:
        return []
    out: list[dict] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        try:
            post = fn(raw)
        except Exception as exc:  # noqa: BLE001 — one malformed row never breaks the batch
            logger.debug("apify.parse_row_failed", extra={"platform": platform, "error": str(exc)[:120]})
            continue
        if post.get("url"):
            out.append(post)
    return out


# ── live call (network) ──────────────────────────────────────────────────────

def run_actor(actor_id: str, run_input: dict, *, max_items: int) -> list[dict]:
    """Run one actor synchronously and return its dataset items.

    Uses Apify's ``run-sync-get-dataset-items`` endpoint (runs the actor and
    returns the dataset in one call), bounded by ``max_items`` and the configured
    timeout. Raises ``ApifyError`` on a missing token, transport error, or non-2xx.
    """
    token = (settings.apify_api_token or "").strip()
    if not token:
        raise ApifyError("apify_not_configured")
    if not (actor_id or "").strip():
        raise ApifyError("apify_actor_not_configured")
    base = (settings.apify_base_url or "https://api.apify.com/v2").rstrip("/")
    url = f"{base}/acts/{actor_path(actor_id)}/run-sync-get-dataset-items"
    params = {"token": token, "clean": "true", "limit": max(1, int(max_items))}
    timeout = float(settings.social_apify_timeout_secs or 300)
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, params=params, json=run_input)
    except httpx.HTTPError as exc:
        raise ApifyError(f"apify_transport_error: {str(exc)[:160]}") from exc
    if resp.status_code >= 400:
        detail = resp.text[:200]
        logger.info("apify.error", extra={"status": resp.status_code, "actor": actor_id})
        raise ApifyError(f"apify_http_{resp.status_code}: {detail}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise ApifyError("apify_bad_json") from exc
    return data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else []) or []


def scrape_handle(platform: str, handle: str, *, max_items: Optional[int] = None) -> list[dict]:
    """Run the platform's configured actor for one handle → normalized posts.
    Raises ``ApifyError`` when the actor id is unconfigured or the run fails."""
    actor = actor_for_platform(platform)
    if not actor:
        raise ApifyError(f"apify_actor_unconfigured:{platform}")
    n = int(max_items if max_items is not None else settings.social_apify_max_posts)
    raw = run_actor(actor, build_actor_input(platform, handle, n), max_items=n)
    return parse_posts(platform, raw)
