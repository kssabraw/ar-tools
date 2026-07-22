"""Brand Voice module — orchestration + persistence (client-level, converged).

platform-api owns auth + persistence; the private nlp service runs the actual
crawl/scrape/3-LLM-call analysis (`/analyze-brand-voice`). The structured voice
is the canonical client asset (Option A) consumed by both the Local SEO nlp
service and — rendered into the run snapshot — the Blog Writer.

Provenance (`brand_voice.source`) enforces the supersede rule: a user-authored
voice is never clobbered by an auto-scan unless the caller passes `force=True`.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from fastapi import HTTPException

from db.supabase_client import get_supabase

# Reuse the Local SEO transport + client→business mapping so the two modules
# can't drift on how a client row maps to the nlp payload.
from services.local_seo_service import _business_fields, _get_client, _post_nlp

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# The brand-voice scan LLM occasionally emits `vocabulary` as a stringified JSON
# blob instead of an object — and sometimes an invalid one, with an inline
# annotation injected into a JSON array (e.g. `"innovative" (used once)`). Stored
# verbatim, that string later crashes every consumer that does `vocabulary.get(...)`
# (nlp page generation, run snapshots). Normalize at the persist boundary so the
# canonical client asset is always well-formed, whatever the model returned.
_VOCAB_ANNOTATION_RE = re.compile(r'"\s*\([^)]*\)')


def _coerce_vocabulary(vocab):
    """Coerce a voice's `vocabulary` field to a dict (or None). Parses a JSON
    string; if that fails, strips the inline `( … )` annotations the scan LLM
    sometimes injects after array items and retries; drops to None when still
    unrecoverable, so a bad scan degrades to 'no vocab' rather than a poison value."""
    if isinstance(vocab, dict):
        return vocab
    if isinstance(vocab, str):
        s = vocab.strip()
        if not s:
            return None
        for candidate in (s, _VOCAB_ANNOTATION_RE.sub('"', s)):
            try:
                parsed = json.loads(candidate)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
            break
        return None
    return None  # unknown type → drop rather than persist a poison value


def _normalize_voice(voice):
    """Normalize a single voice object (current/recommended) before persistence.
    Currently guarantees `vocabulary` is an object (or absent); passes everything
    else through untouched. None / non-dict inputs are returned unchanged."""
    if not isinstance(voice, dict):
        return voice
    if "vocabulary" not in voice:
        return voice
    normalized = dict(voice)
    normalized["vocabulary"] = _coerce_vocabulary(voice.get("vocabulary"))
    return normalized


def _empty_blob() -> dict:
    return {
        "source": None,
        "raw_text": None,
        "current_voice": None,
        "recommended_voice": None,
        "recommended_accepted": None,
        "writer_execution_guide": None,
        "generated_at": None,
        "edited_at": None,
    }


def _scan_blocked(existing: dict, force: bool) -> bool:
    """An auto-scan is blocked only when the user has authored *structured*
    voice that the scan would overwrite. A user with only `raw_text` (a freeform
    brand guide) can still be enriched — the scan preserves their raw_text — so
    those clients are not blocked. `force` overrides the guard entirely."""
    if force:
        return False
    return existing.get("source") == "user" and existing.get("current_voice") is not None


def merge_raw_text(existing: dict | None, raw_text: str | None) -> dict | None:
    """Keep brand_voice in sync with the legacy free-text brand guide so newly
    created / edited clients converge (Option A). The guide is user input, so a
    non-empty value is marked source:'user' (supersede). Structured fields on an
    existing blob are preserved. Returns None when nothing meaningful remains,
    collapsing an empty voice back to SQL NULL."""
    text = (raw_text or "").strip()
    blob = {**_empty_blob(), **(existing or {})}
    blob["raw_text"] = text or None
    if text:
        blob["source"] = "user"
        blob["edited_at"] = _now_iso()
    if not any(
        blob.get(k)
        for k in ("raw_text", "current_voice", "recommended_voice", "writer_execution_guide")
    ):
        return None
    return blob


def _persist(client_id: str, blob: dict) -> None:
    supabase = get_supabase()
    result = (
        supabase.table("clients")
        .update({"brand_voice": blob, "updated_at": _now_iso()})
        .eq("id", client_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="client_not_found")


def get_brand_voice(client_id: str) -> dict:
    """Return the stored brand_voice blob (or None) for a client."""
    client = _get_client(client_id)
    return {"brand_voice": client.get("brand_voice")}


def render_brand_voice_text(brand_voice: dict | None) -> str:
    """Render a client's brand_voice into plain text for the Blog Writer run
    snapshot (Option A convergence). Platform-side mirror of nlp-api's
    `_build_brand_voice_text`, with one deliberate difference: a user's freeform
    guide (`raw_text`) is returned **unwrapped** so free-text clients get
    byte-identical text to the legacy brand_guide_text path.

    Precedence: raw_text (user's verbatim guide) → structured voice → "".
    """
    if not brand_voice:
        return ""

    raw = (brand_voice.get("raw_text") or "").strip()
    if raw:
        return raw  # unwrapped — identical to the legacy brand_guide_text value

    # Structured voice: default to current, switch to recommended only when the
    # user explicitly accepted it (mirrors nlp-api selection).
    if brand_voice.get("recommended_accepted") is True:
        voice = brand_voice.get("recommended_voice") or brand_voice.get("current_voice") or {}
    else:
        voice = brand_voice.get("current_voice") or brand_voice.get("recommended_voice") or {}
    guide = brand_voice.get("writer_execution_guide") or {}
    if not voice and not guide:
        return ""

    lines = ["BRAND VOICE (match this exactly):"]
    if voice.get("tone"):
        lines.append(f"  Tone: {voice['tone']}")
    if voice.get("personality"):
        lines.append(f"  Personality: {', '.join(voice['personality'])}")

    ws = voice.get("writing_style") or {}
    style_parts: list[str] = []
    if ws.get("sentence_length"):
        style_parts.append(f"{ws['sentence_length']} sentences")
    if ws.get("person"):
        style_parts.append(str(ws["person"]))
    if ws.get("formality"):
        style_parts.append(f"{ws['formality']} formality")
    if ws.get("jargon_level"):
        style_parts.append(f"jargon: {ws['jargon_level']}")
    if style_parts:
        lines.append(f"  Writing style: {', '.join(style_parts)}")

    vocab = voice.get("vocabulary") or {}
    if vocab.get("use"):
        lines.append(f"  Words/phrases to use: {', '.join(vocab['use'])}")
    if vocab.get("avoid"):
        lines.append(f"  Words/phrases to avoid: {', '.join(vocab['avoid'])}")
    if voice.get("messaging_themes"):
        lines.append(f"  Messaging themes: {'; '.join(voice['messaging_themes'])}")
    if voice.get("sample_phrases"):
        lines.append(f"  Sample phrases (mirror this style): {'; '.join(voice['sample_phrases'])}")
    if voice.get("content_generation_instructions"):
        lines.append(f"  Writer instructions: {voice['content_generation_instructions']}")

    if isinstance(guide, dict) and guide:
        if guide.get("default_writing_formula"):
            lines.append(f"  Default writing formula: {guide['default_writing_formula']}")
        for key, label in (
            ("non_negotiable_rules", "Non-negotiable rules"),
            ("sentence_style_do", "Sentence style — DO"),
            ("sentence_style_dont", "Sentence style — DON'T"),
            ("quick_cheat_sheet", "Quick cheat sheet"),
        ):
            items = guide.get(key) or []
            if items:
                lines.append(f"  {label}:")
                for item in items:
                    lines.append(f"    - {item}")

    return "\n".join(lines)


def resolve_brand_guide_text(client: dict) -> str:
    """Canonical brand-guide text for a run snapshot. Prefers the converged
    brand_voice (Option A); falls back to the legacy free-text column for any
    client whose brand_voice is unset (e.g. created before the migration)."""
    rendered = render_brand_voice_text(client.get("brand_voice"))
    if rendered:
        return rendered
    return client.get("brand_guide_text") or ""


def ensure_scannable(client_id: str, force: bool) -> None:
    """Pre-flight the supersede guard so the router can return a real HTTP 409
    *before* opening the SSE stream (otherwise the guard would surface as a
    200 + in-stream error event)."""
    existing = _get_client(client_id).get("brand_voice") or {}
    if _scan_blocked(existing, force):
        raise HTTPException(status_code=409, detail="brand_voice_user_authored")


async def scan(client_id: str, force: bool, user_id: str) -> dict:
    """Run the app brand-voice analysis and persist it as source:'app'.

    Refuses to overwrite a user-authored voice unless `force` is set.
    Works without GBP: business identity falls back to the client row.
    """
    client = _get_client(client_id)
    existing = client.get("brand_voice") or {}

    if _scan_blocked(existing, force):
        # User-authored structured voice supersedes — don't silently clobber it.
        raise HTTPException(status_code=409, detail="brand_voice_user_authored")

    fields = _business_fields(client)
    payload = {
        "website_url": fields.get("website"),
        "business_name": fields.get("business_name") or "",
        "gbp_category": fields.get("gbp_category") or "",
    }

    result = await _post_nlp("/analyze-brand-voice", payload, user_id=user_id)
    engine = result.get("brand_voice") or {}

    # Preserve any user freeform brand guide (raw_text) — it still supersedes in
    # rendering — while the scan fills in the structured voice around it.
    preserved_raw = existing.get("raw_text")
    blob = _empty_blob()
    blob.update(
        {
            "source": "app",
            "raw_text": preserved_raw,
            "current_voice": _normalize_voice(engine.get("current_voice")),
            "recommended_voice": _normalize_voice(engine.get("recommended_voice")),
            "recommended_accepted": engine.get("recommended_accepted"),
            "writer_execution_guide": engine.get("writer_execution_guide"),
            "generated_at": _now_iso(),
            # edited_at tracks user authorship of raw_text; only meaningful when
            # preserved (avoids a stale user-edit timestamp on a pure app voice).
            "edited_at": existing.get("edited_at") if preserved_raw else None,
        }
    )
    _persist(client_id, blob)
    logger.info(
        "brand_voice.scan_persisted",
        extra={"client_id": client_id, "pages_sampled": result.get("pages_sampled")},
    )
    return {"brand_voice": blob, "pages_sampled": result.get("pages_sampled")}


async def run_brand_voice_scan_job(job: dict) -> None:
    """Async worker entry: auto-generate a client's brand voice (enqueued at
    client creation). Best-effort — a provider error or the user-authored
    supersede guard (409) is not a hard failure. Persists via `scan`; this
    only manages the async_jobs row."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    user_id = payload.get("user_id")
    job_id = job["id"]
    supabase = get_supabase()
    try:
        result = await scan(
            client_id=client_id, force=bool(payload.get("force")), user_id=user_id
        )
        supabase.table("async_jobs").update(
            {
                "status": "complete",
                "result": {"pages_sampled": result.get("pages_sampled")},
                "completed_at": "now()",
            }
        ).eq("id", job_id).execute()
        logger.info("brand_voice.auto_scan_complete", extra={"client_id": client_id})
    except HTTPException as exc:
        # 409 = a user already authored a structured voice → nothing to do (not
        # an error). Anything else is a best-effort miss recorded on the job.
        status = "complete" if exc.status_code == 409 else "failed"
        supabase.table("async_jobs").update(
            {"status": status, "error": str(exc.detail)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info(
            "brand_voice.auto_scan_skipped",
            extra={"client_id": client_id, "status": status, "detail": str(exc.detail)},
        )
    except Exception as exc:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.warning(
            "brand_voice.auto_scan_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )


async def enqueue_scan(client_id: str, force: bool, user_id: str) -> str:
    """Enqueue a `brand_voice_scan` job for a manual Generate/Re-scan. Returns the
    job id. Runs in the worker (`run_brand_voice_scan_job`), which persists the
    voice, so the UI can navigate away and reconnect (poll `get_scan_job`). The
    caller should `ensure_scannable` first to surface the supersede 409 up front."""
    _get_client(client_id)  # validate ownership / existence
    res = (
        get_supabase()
        .table("async_jobs")
        .insert(
            {
                "job_type": "brand_voice_scan",
                "entity_id": client_id,
                "payload": {"client_id": client_id, "user_id": user_id, "force": bool(force)},
            }
        )
        .execute()
    )
    return res.data[0]["id"]


def get_scan_job(job_id: str, client_id: str) -> dict:
    """Poll a brand-voice scan job (scoped to the client). Returns {status, error}.
    On completion the caller refetches the voice via `get_brand_voice`."""
    res = (
        get_supabase()
        .table("async_jobs")
        .select("status, error, entity_id")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    if not res.data or res.data[0].get("entity_id") != client_id:
        raise HTTPException(status_code=404, detail="scan_job_not_found")
    row = res.data[0]
    return {"status": row["status"], "error": row.get("error")}


def update(
    client_id: str,
    *,
    raw_text: str | None,
    current_voice: dict | None,
    recommended_accepted: bool | None,
    user_id: str,
) -> dict:
    """Merge a manual edit into the stored voice and mark it source:'user'.

    This is the supersede path: a user-authored voice blocks future auto-scans.
    """
    client = _get_client(client_id)
    blob = {**_empty_blob(), **(client.get("brand_voice") or {})}

    if raw_text is not None:
        blob["raw_text"] = raw_text
    if current_voice is not None:
        blob["current_voice"] = current_voice
    if recommended_accepted is not None:
        blob["recommended_accepted"] = recommended_accepted

    blob["source"] = "user"
    blob["edited_at"] = _now_iso()

    _persist(client_id, blob)
    logger.info("brand_voice.user_updated", extra={"client_id": client_id})
    return {"brand_voice": blob}
