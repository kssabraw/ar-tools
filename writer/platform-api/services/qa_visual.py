"""QA Agent — visual page-rendering check (qa-agent-plan, the final phase;
QA_Checklists §Website Pages Posted, "design fit — visual rendering").

"Is the page visually broken when rendered?" — overlapping elements, broken
CSS, a collapsed layout. Answered WITHOUT bundling Chromium into the Railway
image (heavy, memory-hungry, deploy-risky): the screenshot comes from
**DataForSEO's on-page page_screenshot endpoint** (creds already live on
PLATFORM, fractions of a cent per capture), and a **Claude vision** call
judges the render.

Verdict discipline (same as the map-embed assertion sentence): this is an
LLM-*judged* check inside the deterministic verdict fold — the model returns
{broken, confidence, issues}; only **high-confidence broken** maps to a
blocking fail, low-confidence broken reads "could not verify" (needs_human),
and any infra failure (no creds, capture error, oversized image) is fail-open
to needs_human, never an auto-bounce. Pure parsing/mapping helpers are
unit-tested; the IO wrappers are best-effort.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from typing import Any, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_SCREENSHOT_PATH = "/v3/on_page/page_screenshot"
_BASE_URL = "https://api.dataforseo.com"
# Anthropic's image limits are ~5 MB / 8000px; stay well inside them.
_MAX_IMAGE_BYTES = 3_500_000
_RESIZE_WIDTH = 1200
_MAX_IMAGE_HEIGHT = 7500


def _auth_header() -> dict[str, str]:
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    return {"Authorization": "Basic " + base64.b64encode(creds.encode()).decode()}


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def screenshot_url_from_response(data: Any) -> Optional[str]:
    """The captured image's URL out of a DataForSEO page_screenshot response.
    Tolerant of the exact item key (image/screenshot/screenshot_url) so a
    provider-side rename degrades to needs_human instead of a crash. Pure."""
    try:
        for task in (data or {}).get("tasks") or []:
            for result in task.get("result") or []:
                for item in result.get("items") or []:
                    for key in ("image", "screenshot", "screenshot_url"):
                        val = item.get(key)
                        if isinstance(val, str) and val.startswith("http"):
                            return val
    except AttributeError:
        return None
    return None


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_visual_verdict(text: Optional[str]) -> Optional[dict]:
    """Parse the judge's JSON reply → {broken: bool, confidence: 'high'|'low',
    issues: [str]}. None when unparsable (→ fail-open). Pure."""
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("broken"), bool):
        return None
    confidence = raw.get("confidence")
    if confidence not in ("high", "low"):
        confidence = "low"
    issues = [str(i)[:200] for i in raw.get("issues") or [] if str(i).strip()][:5]
    return {"broken": raw["broken"], "confidence": confidence, "issues": issues}


def verdict_to_ok(verdict: Optional[dict]) -> tuple[Optional[bool], str]:
    """Map the judge's verdict onto a check result. Only HIGH-confidence
    broken bounces; low-confidence broken reads needs-human; unparsable is
    fail-open. Pure."""
    if verdict is None:
        return None, "visual judge returned no verdict"
    issues = "; ".join(verdict["issues"])
    if not verdict["broken"]:
        return True, "render looks intact"
    if verdict["confidence"] == "high":
        return False, f"visually broken — {issues}" if issues else "visually broken"
    return None, (f"possibly broken (low confidence) — {issues}" if issues
                  else "possibly broken (low confidence)")


# ---------------------------------------------------------------------------
# IO (best-effort throughout)
# ---------------------------------------------------------------------------
async def capture_screenshot(url: str) -> Optional[bytes]:
    """Render + capture via DataForSEO; the PNG bytes, or None on any failure
    (missing creds, API error, unfetchable image)."""
    if not (settings.dataforseo_login and settings.dataforseo_password):
        return None
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{_BASE_URL}{_SCREENSHOT_PATH}",
                headers=_auth_header(),
                json=[{"url": url}],
            )
            resp.raise_for_status()
            image_url = screenshot_url_from_response(resp.json())
            if not image_url:
                logger.warning("qa_visual_no_image_in_response", extra={"url": url})
                return None
            img = await client.get(image_url)
            if img.status_code >= 400:
                return None
            return img.content
    except Exception as exc:
        logger.warning("qa_visual_capture_failed", extra={"url": url, "error": str(exc)})
        return None


def _fit_image(png: bytes) -> Optional[tuple[bytes, str]]:
    """(bytes, media_type) sized inside Anthropic's image limits — downscaled
    to JPEG via Pillow when the capture is too large/tall. None when it can't
    be made to fit."""
    if len(png) <= _MAX_IMAGE_BYTES:
        try:
            from PIL import Image

            with Image.open(io.BytesIO(png)) as im:
                if im.height <= _MAX_IMAGE_HEIGHT:
                    return png, "image/png"
        except Exception:
            return png, "image/png"  # size OK; dimension check unavailable
    try:
        from PIL import Image

        with Image.open(io.BytesIO(png)) as im:
            im = im.convert("RGB")
            scale = min(_RESIZE_WIDTH / im.width, _MAX_IMAGE_HEIGHT / im.height, 1.0)
            if scale < 1.0:
                im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=80)
            out = buf.getvalue()
            return (out, "image/jpeg") if len(out) <= _MAX_IMAGE_BYTES else None
    except Exception as exc:
        logger.warning("qa_visual_resize_failed", extra={"error": str(exc)})
        return None


async def judge_render(image: bytes, media_type: str) -> tuple[Optional[bool], str]:
    """One vision call: is the rendered page visually broken? Returns the
    check's (ok, note) via the pure mapping. Best-effort → (None, note)."""
    try:
        import anthropic

        api = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=90.0)
        msg = await api.messages.create(
            model=settings.qa_visual_model,
            max_tokens=settings.qa_visual_max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.b64encode(image).decode(),
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "You are a visual QA checker looking at a screenshot of a "
                            "rendered web page. Is the page VISUALLY BROKEN — overlapping "
                            "or clipped elements, unstyled raw HTML (CSS failed to load), "
                            "collapsed/empty layout, giant unscaled images, illegible "
                            "overlapping text? Unusual-but-intentional design is NOT "
                            "broken; judge mechanical breakage only. Reply with ONLY a "
                            'JSON object: {"broken": true|false, "confidence": '
                            '"high"|"low", "issues": ["<short issue>", ...]}'
                        ),
                    },
                ],
            }],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return verdict_to_ok(parse_visual_verdict(text))
    except Exception as exc:
        logger.warning("qa_visual_judge_failed", extra={"error": str(exc)})
        return None, f"visual judge unavailable ({type(exc).__name__})"


async def visual_check(url: str) -> dict:
    """The full pipeline → one standard QA check dict (key 'visual_render',
    blocking). Every failure path is fail-open (ok=None) with a plain note."""
    png = await capture_screenshot(url)
    if png is None:
        return {"key": "visual_render", "label": "Page renders without visual breakage",
                "ok": None, "blocking": True,
                "note": "screenshot unavailable (capture failed or DataForSEO creds missing)"}
    fitted = _fit_image(png)
    if fitted is None:
        return {"key": "visual_render", "label": "Page renders without visual breakage",
                "ok": None, "blocking": True,
                "note": "screenshot too large to judge — review manually"}
    image, media_type = fitted
    ok, note = await judge_render(image, media_type)
    return {"key": "visual_render", "label": "Page renders without visual breakage",
            "ok": ok, "blocking": True, "note": note}
