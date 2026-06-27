"""AI Visibility (Brand Strength) — scan engine.

Ports brand-strength-ai's `run-scan` edge function to the suite's Python/async
stack. A *scan* asks an AI answer engine a keyword's question and detects whether
the client's brand appears in the answer, recording mention/type/sentiment/
confidence + supporting citations + the raw response. The same raw response is
re-classified for each tracked competitor (no extra search calls).

Six engines: `chatgpt` (OpenAI Responses API + web search), `claude` (Anthropic
+ web search), `gemini` (Google + search grounding), `perplexity` (`sonar`), and
`google_ai_overview` / `google_ai_mode` (Google's AI answers via DataForSEO).

Differences from the source (per the integration plan):
  * No credits/billing, no snippet encryption, no inline alert trigger.
  * The mention classifier uses the suite-default Claude model instead of
    gpt-4o-mini (build decision: "suite defaults").

Runs as an `async_jobs` job (job_type='brand_scan'); the per-keyword×engine
loop is fully async (SDK + httpx calls), so no worker-thread offload is needed.
See docs/modules/brand-strength-module-integration-plan-v1_0.md (Phase 1).
"""

from __future__ import annotations

import base64
import logging
import re
import uuid
from typing import Optional

import httpx
from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger("brand_scan")

ENGINES = {
    "chatgpt", "claude", "gemini", "perplexity",
    "google_ai_overview", "google_ai_mode",
}

# Provider HTTP statuses that are terminal for a scan (no point retrying):
# auth, payment/quota, forbidden, and rate-limit.
_TERMINAL_STATUSES = {401, 402, 403, 429}

_SCAN_PROMPT = (
    'You are answering as a local search assistant.\n\n'
    'User query: "{keyword}"\n\n'
    'List the top local businesses or service providers that are mentioned in '
    'response to this query.\n\n'
    'After listing the businesses, indicate whether "{brand}" appears in the results.'
)


class ProviderError(Exception):
    """A scan engine's provider returned a non-success HTTP status."""

    def __init__(self, status: int, message: str = ""):
        self.status = status
        self.message = message
        super().__init__(f"provider_error status={status}")


class ScanFailed(Exception):
    """A keyword×engine scan failed terminally; carries a user-facing reason."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


# ── citation extraction (per provider) ────────────────────────────────────────

def _extract_openai(output: list) -> tuple[str, list[str]]:
    text, citations = "", []
    for item in output or []:
        if item.get("type") == "message" and item.get("role") == "assistant":
            for content in item.get("content") or []:
                if content.get("type") == "output_text" or content.get("text"):
                    text = text or content.get("text") or ""
                for ann in content.get("annotations") or []:
                    url = ann.get("url")
                    if ann.get("type") == "url_citation" and url and url not in citations:
                        citations.append(url)
    return text, citations


def _extract_gemini(data: dict) -> tuple[str, list[str]]:
    candidates = data.get("candidates") or []
    if not candidates:
        return "", []
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if p.get("text"))
    citations: list[str] = []
    grounding = candidates[0].get("groundingMetadata") or {}
    for chunk in grounding.get("groundingChunks") or []:
        url = (chunk.get("web") or {}).get("uri")
        if url and url not in citations:
            citations.append(url)
    return text, citations


def _extract_claude(content: list) -> tuple[str, list[str]]:
    text, citations = "", []
    for block in content or []:
        btype = block.get("type")
        if btype == "text":
            text += block.get("text") or ""
            for cit in block.get("citations") or []:
                url = cit.get("url")
                if url and url not in citations:
                    citations.append(url)
        elif btype == "web_search_tool_result":
            for result in block.get("content") or []:
                url = result.get("url")
                if result.get("type") == "web_search_result" and url and url not in citations:
                    citations.append(url)
    return text, citations


def _extract_dataforseo_ai(items: list, keyword: str, brand: str, label: str) -> tuple[str, list[str]]:
    """Pull AI Overview / AI Mode text + references out of a DataForSEO SERP."""
    text, citations = "", []
    for item in items or []:
        if item.get("type") in ("ai_overview", "ai_mode"):
            for sub in item.get("items") or []:
                if sub.get("text"):
                    text += sub["text"] + "\n"
                for ref in sub.get("references") or []:
                    url = ref.get("url")
                    if url and url not in citations:
                        citations.append(url)
            if item.get("text"):
                text += item["text"] + "\n"
            for ref in item.get("references") or []:
                url = ref.get("url")
                if url and url not in citations:
                    citations.append(url)
    text = text.strip()
    if not text:
        # No AI answer shown — a valid "not visible" result, not an error.
        return (
            f'No Google {label} was displayed for the query "{keyword}". '
            f'Google did not generate one for this search, which means "{brand}" '
            f"does not appear in {label} for this query.",
            [],
        )
    return text, citations


# ── engine executors ─────────────────────────────────────────────────────────

async def _execute_chatgpt(keyword: str, brand: str) -> tuple[str, list[str]]:
    if not settings.openai_api_key:
        raise ScanFailed("OpenAI API not configured")
    import openai

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        resp = await client.responses.create(
            model=settings.brand_engine_chatgpt_model,
            tools=[{"type": settings.brand_chatgpt_web_search_tool}],
            input=_SCAN_PROMPT.format(keyword=keyword, brand=brand),
        )
    except openai.APIStatusError as exc:  # pragma: no cover - thin provider wrapper
        raise ProviderError(exc.status_code, str(exc))
    return _extract_openai(resp.model_dump().get("output") or [])


async def _execute_claude(keyword: str, brand: str) -> tuple[str, list[str]]:
    if not settings.anthropic_api_key:
        raise ScanFailed("Anthropic API not configured")
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        resp = await client.messages.create(
            model=settings.brand_engine_claude_model,
            max_tokens=1024,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=[{"role": "user", "content": _SCAN_PROMPT.format(keyword=keyword, brand=brand)}],
        )
    except anthropic.APIStatusError as exc:  # pragma: no cover
        raise ProviderError(exc.status_code, str(exc))
    return _extract_claude(resp.model_dump().get("content") or [])


async def _execute_gemini(keyword: str, brand: str) -> tuple[str, list[str]]:
    if not settings.gemini_api_key:
        raise ScanFailed("Gemini API not configured")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.brand_engine_gemini_model}:generateContent?key={settings.gemini_api_key}"
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": _SCAN_PROMPT.format(keyword=keyword, brand=brand)}]}],
        "tools": [{"google_search": {}}],
    }
    async with httpx.AsyncClient(timeout=60) as http:
        resp = await http.post(url, json=body)
    if resp.status_code != 200:
        raise ProviderError(resp.status_code, resp.text)
    return _extract_gemini(resp.json())


async def _execute_perplexity(keyword: str, brand: str) -> tuple[str, list[str]]:
    if not settings.perplexity_api_key:
        raise ScanFailed("Perplexity API not configured")
    body = {
        "model": settings.brand_engine_perplexity_model,
        "messages": [
            {"role": "system", "content": "You are a local search assistant. Be precise and concise."},
            {"role": "user", "content": _SCAN_PROMPT.format(keyword=keyword, brand=brand)},
        ],
    }
    async with httpx.AsyncClient(timeout=60) as http:
        resp = await http.post(
            "https://api.perplexity.ai/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {settings.perplexity_api_key}"},
        )
    if resp.status_code != 200:
        raise ProviderError(resp.status_code, resp.text)
    data = resp.json()
    text = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
    citations = data.get("citations") or []
    return text, citations


async def _execute_dataforseo(keyword: str, brand: str, ai_mode: bool) -> tuple[str, list[str]]:
    if not settings.dataforseo_login or not settings.dataforseo_password:
        raise ScanFailed("DataForSEO API not configured")
    endpoint = (
        "https://api.dataforseo.com/v3/serp/google/ai_mode/live/advanced"
        if ai_mode
        else "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
    )
    task = {
        "keyword": keyword,
        "location_code": settings.dataforseo_default_location_code,
        "language_code": settings.dataforseo_default_language_code,
        "device": "desktop",
        "os": "windows",
    }
    if not ai_mode:
        task["load_async_ai_overview"] = True
        task["expand_ai_overview"] = True
    auth = base64.b64encode(
        f"{settings.dataforseo_login}:{settings.dataforseo_password}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=120) as http:
        resp = await http.post(endpoint, json=[task], headers={"Authorization": f"Basic {auth}"})
    if resp.status_code != 200:
        raise ProviderError(resp.status_code, resp.text)
    data = resp.json()
    if data.get("status_code") != 20000:
        raise ProviderError(500, data.get("status_message") or "DataForSEO API error")
    tasks = data.get("tasks") or []
    if not tasks or not (tasks[0].get("result") or []):
        raise ProviderError(500, "No SERP results returned")
    items = (tasks[0]["result"][0] or {}).get("items") or []
    return _extract_dataforseo_ai(items, keyword, brand, "AI Mode" if ai_mode else "AI Overview")


async def _dispatch(engine: str, keyword: str, brand: str) -> tuple[str, list[str]]:
    if engine == "chatgpt":
        return await _execute_chatgpt(keyword, brand)
    if engine == "claude":
        return await _execute_claude(keyword, brand)
    if engine == "gemini":
        return await _execute_gemini(keyword, brand)
    if engine == "perplexity":
        return await _execute_perplexity(keyword, brand)
    if engine == "google_ai_overview":
        return await _execute_dataforseo(keyword, brand, ai_mode=False)
    if engine == "google_ai_mode":
        return await _execute_dataforseo(keyword, brand, ai_mode=True)
    raise ScanFailed(f"Unknown engine: {engine}")


# ── mention classification ───────────────────────────────────────────────────

_CLASSIFIER_SYSTEM = (
    "You are analyzing AI search results to determine if a specific business "
    "appears in the actual results.\n\n"
    "CRITICAL RULES:\n"
    '1. A query restatement like "I\'ll search for [brand]..." is NOT a mention\n'
    "2. Only count it as a mention if the business is listed as an actual search "
    "result or business listing\n"
    '3. Phrases like "does not appear", "not found", "no mention of", or "not in '
    'the results" mean NO mention\n'
    "4. The brand must appear in the RESULTS section, not the AI's preamble or "
    "methodology explanation\n"
    "5. If the AI explicitly states the brand was NOT found, mention_found is false\n\n"
    "Be precise. False positives are worse than false negatives."
)

_CLASSIFIER_TOOL = {
    "name": "report_brand_visibility",
    "description": "Report whether the brand was found in search results as an actual business listing",
    "input_schema": {
        "type": "object",
        "properties": {
            "mention_found": {"type": "boolean", "description": "True ONLY if brand appears as an actual business result."},
            "mention_type": {"type": "string", "enum": ["direct", "implied", "none"]},
            "sentiment": {"type": "number", "description": "-1 (negative) to 1 (positive); 0 if neutral/absent."},
            "confidence": {"type": "number", "description": "0 to 1"},
            "evidence_snippet": {"type": "string", "description": "Text proving the brand was/wasn't found (max 300 chars)."},
            "reasoning": {"type": "string", "description": "Brief explanation of the classification."},
        },
        "required": ["mention_found", "mention_type", "sentiment", "confidence", "evidence_snippet", "reasoning"],
    },
}


def _clamp(value, lo, hi, default):
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


async def analyze_mention(response_text: str, brand: str, citations: list[str], raw_response: str) -> dict:
    """Classify whether `brand` appears in `response_text`. Uses the suite-default
    Claude model with forced tool-use; falls back to regex on any failure."""
    if not settings.anthropic_api_key:
        return _fallback_analysis(response_text, brand, citations, raw_response)
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        resp = await client.messages.create(
            model=settings.brand_classifier_model,
            max_tokens=1024,
            system=_CLASSIFIER_SYSTEM,
            tools=[_CLASSIFIER_TOOL],
            tool_choice={"type": "tool", "name": "report_brand_visibility"},
            messages=[{
                "role": "user",
                "content": (
                    f'Brand to find: "{brand}"\n\nSearch response to analyze:\n"""\n'
                    f'{response_text[:4000]}\n"""\n\nDetermine if this brand appears as an '
                    "actual business result (not just mentioned in the query or methodology)."
                ),
            }],
        )
        tool_input = next(
            (b.get("input") for b in resp.model_dump().get("content") or [] if b.get("type") == "tool_use"),
            None,
        )
        if not tool_input:
            return _fallback_analysis(response_text, brand, citations, raw_response)
        found = tool_input.get("mention_found") is True
        return {
            "mention_found": found,
            "mention_type": (tool_input.get("mention_type") or "direct") if found else "none",
            "sentiment": _clamp(tool_input.get("sentiment"), -1, 1, 0.0),
            "confidence_score": _clamp(tool_input.get("confidence"), 0, 1, 0.5),
            "snippet": (tool_input.get("evidence_snippet") or None),
            "citations": citations,
            "reasoning": tool_input.get("reasoning") or None,
            "raw_response": raw_response,
        }
    except Exception as exc:
        logger.warning("brand_scan.classifier_failed", extra={"error": str(exc)})
        return _fallback_analysis(response_text, brand, citations, raw_response)


def _fallback_analysis(response_text: str, brand: str, citations: list[str], raw_response: str) -> dict:
    """Regex fallback when the classifier is unavailable. Ported from the source."""
    lower_brand = brand.lower()
    esc = re.escape(lower_brand)
    not_found = [
        rf"{esc}[^.]*does not appear",
        rf"{esc}[^.]*is not mentioned",
        rf"{esc}[^.]*was not found",
        rf"no mention of[^.]*{esc}",
        rf"no information[^.]*{esc}",
        r"not[^.]{0,20}in the (search )?results",
    ]
    for pat in not_found:
        if re.search(pat, response_text, re.IGNORECASE):
            return {
                "mention_found": False, "mention_type": "none", "sentiment": 0.0,
                "confidence_score": 0.85,
                "snippet": "Brand explicitly stated as not found in results",
                "citations": citations,
                "reasoning": "[Fallback] Explicit negative statement detected",
                "raw_response": raw_response,
            }

    clean = response_text
    for pat in [
        r"I('ll| will) search for[^.]*\.",
        r"Let me (search|look|find|check)[^.]*\.",
        r"Searching for[^.]*\.",
        r"I('ll| will) (check|look|see) if[^.]*appears[^.]*\.",
    ]:
        clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    clean_lower = clean.lower()

    direct = lower_brand in clean_lower
    brand_words = [w for w in lower_brand.split() if len(w) > 3]
    implied = (not direct) and any(w in clean_lower for w in brand_words)
    mention_type = "direct" if direct else ("implied" if implied else "none")
    found = mention_type != "none"

    sentiment = 0.0
    if found:
        pos = sum(w in clean_lower for w in ["best", "top", "excellent", "great", "recommended", "trusted", "reliable"])
        neg = sum(w in clean_lower for w in ["avoid", "bad", "poor", "complaint", "issue", "problem"])
        if pos > neg:
            sentiment = min(1.0, 0.3 + pos * 0.1)
        elif neg > pos:
            sentiment = max(-1.0, -0.3 - neg * 0.1)

    snippet = None
    if found:
        term = lower_brand if mention_type == "direct" else next((w for w in brand_words if w in clean_lower), "")
        idx = clean_lower.find(term)
        if idx != -1:
            start, end = max(0, idx - 100), min(len(clean), idx + 200)
            snippet = clean[start:end].strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(clean):
                snippet = snippet + "..."
            snippet = f"[Fallback analysis] {snippet}"

    return {
        "mention_found": found, "mention_type": mention_type,
        "sentiment": round(sentiment, 2),
        "confidence_score": 0.6 if found else 0.7,
        "snippet": snippet, "citations": citations,
        "reasoning": "[Fallback] classifier unavailable, used pattern matching",
        "raw_response": raw_response,
    }


# ── one keyword × engine ─────────────────────────────────────────────────────

async def scan_keyword_engine(
    keyword: str, brand: str, engine: str, competitor_names: list[str]
) -> dict:
    """Run a single keyword×engine scan: dispatch → classify → competitor pass.

    Retries transient provider errors up to `brand_scan_max_retries`; auth/quota/
    rate-limit errors are terminal. Raises `ScanFailed` on terminal failure."""
    result = None
    retry_count = 0
    max_retries = settings.brand_scan_max_retries
    while retry_count <= max_retries and result is None:
        try:
            response_text, citations = await _dispatch(engine, keyword, brand)
        except ProviderError as exc:
            if exc.status in _TERMINAL_STATUSES:
                raise ScanFailed(
                    "Rate limit exceeded" if exc.status == 429 else "AI service authentication/quota issue"
                )
            retry_count += 1
            continue
        if not response_text:
            retry_count += 1
            continue
        result = await analyze_mention(response_text, brand, citations, response_text)

    if result is None:
        raise ScanFailed("Failed to get a valid AI response after retries")

    competitor_results = []
    for name in competitor_names[: settings.brand_scan_max_competitors]:
        try:
            comp = await analyze_mention(result["raw_response"], name, result["citations"], result["raw_response"])
            competitor_results.append({
                "name": name, "found": comp["mention_found"], "mention_type": comp["mention_type"],
                "sentiment": comp["sentiment"], "confidence": comp["confidence_score"],
                "snippet": (comp["snippet"][:300] if comp["snippet"] else None),
            })
        except Exception:
            competitor_results.append({
                "name": name, "found": False, "mention_type": "none",
                "sentiment": 0, "confidence": 0, "snippet": None,
            })

    result["competitor_results"] = competitor_results
    result["retry_count"] = retry_count
    return result


# ── enqueue + job handler ────────────────────────────────────────────────────

def enqueue_brand_scan(
    client_id: str,
    keyword_ids: list[str],
    engines: list[str],
    include_competitors: bool,
    user_id: Optional[str],
) -> dict:
    """Insert a `brand_scan` async job covering keyword_ids × engines. Returns
    {job_id, scan_batch_id}. Used by the router (Phase 2) and the scheduler."""
    bad = [e for e in engines if e not in ENGINES]
    if bad:
        raise HTTPException(status_code=400, detail="invalid_engine")
    if not keyword_ids or not engines:
        raise HTTPException(status_code=400, detail="empty_scan")

    scan_batch_id = str(uuid.uuid4())
    supabase = get_supabase()
    res = (
        supabase.table("async_jobs")
        .insert({
            "job_type": "brand_scan",
            "entity_id": client_id,
            "payload": {
                "client_id": client_id,
                "keyword_ids": keyword_ids,
                "engines": engines,
                "include_competitors": include_competitors,
                "scan_batch_id": scan_batch_id,
                "user_id": user_id,
            },
        })
        .execute()
    )
    return {"job_id": res.data[0]["id"], "scan_batch_id": scan_batch_id}


async def run_brand_scan_job(job: dict) -> None:
    """async_jobs handler for job_type='brand_scan'.

    Pre-creates a brand_mention_history row per keyword×engine (status 'queued')
    so the UI can show progress, then processes each, updating the row to
    'completed'/'failed'. Finalizes the job row 'complete' with a count summary."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    keyword_ids = payload.get("keyword_ids") or []
    engines = payload.get("engines") or []
    include_competitors = bool(payload.get("include_competitors"))
    scan_batch_id = payload.get("scan_batch_id") or str(uuid.uuid4())
    user_id = payload.get("user_id")
    job_id = job["id"]
    supabase = get_supabase()

    logger.info(
        "brand_scan.start",
        extra={"job_id": job_id, "client_id": client_id,
               "keywords": len(keyword_ids), "engines": len(engines)},
    )

    try:
        client_row = (
            supabase.table("clients").select("name").eq("id", client_id).limit(1).execute()
        ).data
        if not client_row:
            raise ScanFailed("client_not_found")
        brand = client_row[0].get("name") or ""

        kw_rows = (
            supabase.table("brand_tracked_keywords")
            .select("id, keyword")
            .eq("client_id", client_id)
            .in_("id", keyword_ids)
            .execute()
        ).data or []
        keyword_by_id = {r["id"]: r["keyword"] for r in kw_rows}

        competitor_names: list[str] = []
        if include_competitors:
            comp_rows = (
                supabase.table("brand_tracked_competitors")
                .select("competitor_name")
                .eq("client_id", client_id)
                .execute()
            ).data or []
            competitor_names = [r["competitor_name"] for r in comp_rows if r.get("competitor_name")]

        # Pre-create queued rows (one per keyword×engine present).
        rows_to_process = []
        for keyword_id in keyword_ids:
            keyword = keyword_by_id.get(keyword_id)
            if not keyword:
                continue
            for engine in engines:
                inserted = (
                    supabase.table("brand_mention_history")
                    .insert({
                        "client_id": client_id,
                        "keyword_id": keyword_id,
                        "scan_batch_id": scan_batch_id,
                        "engine": engine,
                        "scanned_brand_name": brand,
                        "is_competitor_scan": False,
                        "status": "queued",
                        "created_by": user_id,
                    })
                    .execute()
                ).data[0]
                rows_to_process.append((inserted["id"], keyword, engine))

        completed = failed = 0
        for row_id, keyword, engine in rows_to_process:
            supabase.table("brand_mention_history").update(
                {"status": "processing"}
            ).eq("id", row_id).execute()
            try:
                result = await scan_keyword_engine(keyword, brand, engine, competitor_names)
                supabase.table("brand_mention_history").update({
                    "status": "completed",
                    "mention_found": result["mention_found"],
                    "mention_type": result["mention_type"],
                    "sentiment": result["sentiment"],
                    "confidence_score": result["confidence_score"],
                    "snippet": result["snippet"],
                    "citations": result["citations"],
                    "reasoning": result["reasoning"],
                    "raw_response": result["raw_response"],
                    "competitor_results": result["competitor_results"],
                    "retry_count": result["retry_count"],
                    "updated_at": "now()",
                }).eq("id", row_id).execute()
                completed += 1
            except ScanFailed as exc:
                supabase.table("brand_mention_history").update(
                    {"status": "failed", "failure_reason": exc.reason, "updated_at": "now()"}
                ).eq("id", row_id).execute()
                failed += 1
            except Exception as exc:
                logger.warning("brand_scan.row_error", extra={"row_id": row_id, "error": str(exc)})
                supabase.table("brand_mention_history").update(
                    {"status": "failed", "failure_reason": "internal_error", "updated_at": "now()"}
                ).eq("id", row_id).execute()
                failed += 1

        supabase.table("async_jobs").update({
            "status": "complete",
            "result": {
                "scan_batch_id": scan_batch_id,
                "total": len(rows_to_process),
                "completed": completed,
                "failed": failed,
            },
            "completed_at": "now()",
        }).eq("id", job_id).execute()
        logger.info(
            "brand_scan.complete",
            extra={"job_id": job_id, "completed": completed, "failed": failed},
        )
    except Exception as exc:
        logger.warning("brand_scan.failed", extra={"job_id": job_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
