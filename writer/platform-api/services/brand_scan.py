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
  * The chatgpt engine and the mention classifier use the latest OpenAI models
    (gpt-5.4 flagship for the engine, gpt-5.4-mini for the classifier) rather
    than the source's gpt-4.1 / gpt-4o-mini (build decision).

Runs as an `async_jobs` job (job_type='brand_scan'); the per-keyword×engine
loop is fully async (SDK + httpx calls), so no worker-thread offload is needed.
See docs/modules/brand-strength-module-integration-plan-v1_0.md (Phase 1).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import uuid
from typing import Optional

import httpx
from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import brand_analysis

logger = logging.getLogger("brand_scan")

# Inline markdown links inside an AI Overview's generated text — [label](url).
_MD_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")

# Canonical display/default order. ENGINES (the validation set) is derived from it.
ENGINE_ORDER = [
    "chatgpt", "claude", "gemini", "perplexity",
    "google_ai_overview", "google_ai_mode",
]
ENGINES = set(ENGINE_ORDER)

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


def _dedup(seq: list[str]) -> list[str]:
    out: list[str] = []
    for s in seq:
        if s and s not in out:
            out.append(s)
    return out


def _collect_aio_links(node: dict, inline: list[str], refs: list[str]) -> None:
    """Pull link domains out of one AI Overview element. The `references` array
    is the sources/citations strip; inline `links` (and markdown links in the
    generated text) are in-content links — a stronger signal."""
    for ref in node.get("references") or []:
        host = brand_analysis.extract_host(ref.get("domain") or ref.get("url"))
        if host:
            refs.append(host)
    for link in node.get("links") or []:
        host = brand_analysis.extract_host(link.get("domain") or link.get("url"))
        if host:
            inline.append(host)
    body = node.get("text") or node.get("markdown") or ""
    for url in _MD_LINK_RE.findall(body):
        host = brand_analysis.extract_host(url)
        if host:
            inline.append(host)


def _extract_aio_domains(items: list) -> tuple[list[str], list[str]]:
    """Walk a DataForSEO AI Overview / AI Mode SERP and split the cited domains
    into (inline in-content links, reference/citation-strip domains)."""
    inline: list[str] = []
    refs: list[str] = []
    for item in items or []:
        if item.get("type") in ("ai_overview", "ai_mode"):
            _collect_aio_links(item, inline, refs)
            for sub in item.get("items") or []:
                _collect_aio_links(sub, inline, refs)
    return _dedup(inline), _dedup(refs)


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
    text, citations = _extract_dataforseo_ai(items, keyword, brand, "AI Mode" if ai_mode else "AI Overview")
    inline_domains, reference_domains = _extract_aio_domains(items)
    meta = {"aio_inline_domains": inline_domains, "aio_reference_domains": reference_domains}
    return text, citations, meta


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
    "type": "function",
    "function": {
        "name": "report_brand_visibility",
        "description": "Report whether the brand was found in search results as an actual business listing",
        "parameters": {
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
    },
}


# Extended schema used ONLY on the brand pass (not the per-competitor
# re-classification), so it adds no extra API calls — the single classifier
# call we already make just extracts more. Mines position/prominence, the full
# business list + the attributes the answer gives each, inferred intent +
# locations, and any facts the answer asserts about the brand (for an accuracy
# check vs GBP). All additive fields are optional so a thin answer never fails.
_RICH_CLASSIFIER_TOOL = {
    "type": "function",
    "function": {
        "name": "report_brand_visibility",
        "description": "Report whether the brand was found AND extract the answer's structure: who else is listed, the brand's position, and how it's framed.",
        "parameters": {
            "type": "object",
            "properties": {
                **_CLASSIFIER_TOOL["function"]["parameters"]["properties"],
                "mention_rank": {"type": "integer", "description": "1-based position of the TARGET brand among the businesses listed in order; 0 if not listed."},
                "total_businesses": {"type": "integer", "description": "How many distinct businesses/providers the answer lists."},
                "prominence": {"type": "string", "enum": ["leading", "passing", "caveated", "none"], "description": "How the TARGET brand is framed: 'leading' = top/standout recommendation, 'passing' = listed among others, 'caveated' = mentioned with reservations, 'none' = absent."},
                "businesses": {
                    "type": "array",
                    "description": "EVERY business/provider named in the answer, in the order listed, with the key reasons/attributes the answer gives each (e.g. '24/7', 'family-owned', 'highly rated').",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "attributes": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["name"],
                    },
                },
                "inferred_intent": {"type": "string", "description": "How the AI interpreted the query (e.g. assumed emergency/sub-service/price tier), one short phrase."},
                "mentioned_locations": {"type": "array", "items": {"type": "string"}, "description": "Specific places/neighborhoods the answer named."},
                "stated_brand_facts": {
                    "type": "object",
                    "description": "Facts the answer asserts about the TARGET brand specifically, if any (for an accuracy check). Omit fields not stated.",
                    "properties": {
                        "phone": {"type": "string"},
                        "permanently_closed": {"type": "boolean"},
                    },
                },
            },
            "required": _CLASSIFIER_TOOL["function"]["parameters"]["required"],
        },
    },
}


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_businesses(raw) -> list[dict]:
    out: list[dict] = []
    for b in raw or []:
        if not isinstance(b, dict):
            continue
        name = (b.get("name") or "").strip()
        if not name:
            continue
        attrs = [str(a).strip() for a in (b.get("attributes") or []) if str(a).strip()]
        out.append({"name": name, "attributes": attrs[:6]})
    return out


def _extract_rich_fields(tool_input: dict, found: bool) -> dict:
    """Pull the extended-schema fields out of the classifier output (brand pass)."""
    facts = tool_input.get("stated_brand_facts")
    return {
        "mention_rank": (_safe_int(tool_input.get("mention_rank")) or None) if found else None,
        "total_businesses": _safe_int(tool_input.get("total_businesses")),
        "prominence": tool_input.get("prominence") if found else "none",
        "businesses": _clean_businesses(tool_input.get("businesses")),
        "inferred_intent": (tool_input.get("inferred_intent") or "").strip() or None,
        "mentioned_locations": [str(l).strip() for l in (tool_input.get("mentioned_locations") or []) if str(l).strip()],
        "stated_brand_facts": facts if isinstance(facts, dict) and found else None,
    }


def _clamp(value, lo, hi, default):
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


async def analyze_mention(
    response_text: str, brand: str, citations: list[str], raw_response: str,
    extract_rich: bool = False,
) -> dict:
    """Classify whether `brand` appears in `response_text`. Uses the latest OpenAI
    `mini` model with forced function-calling; falls back to regex on any failure.

    When `extract_rich` is True (the brand pass — not the per-competitor
    re-classification), the same single call also extracts the answer's
    structure (position, prominence, the full business list + attributes, intent,
    locations, stated brand facts) into result['rich']. No extra API call."""
    if not settings.openai_api_key:
        return _fallback_analysis(response_text, brand, citations, raw_response)
    import openai

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    tool = _RICH_CLASSIFIER_TOOL if extract_rich else _CLASSIFIER_TOOL
    try:
        resp = await client.chat.completions.create(
            model=settings.brand_classifier_model,
            messages=[
                {"role": "system", "content": _CLASSIFIER_SYSTEM},
                {"role": "user", "content": (
                    f'Brand to find: "{brand}"\n\nSearch response to analyze:\n"""\n'
                    f'{response_text[:4000]}\n"""\n\nDetermine if this brand appears as an '
                    "actual business result (not just mentioned in the query or methodology)."
                )},
            ],
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "report_brand_visibility"}},
        )
        tool_calls = resp.choices[0].message.tool_calls
        if not tool_calls or tool_calls[0].function.name != "report_brand_visibility":
            return _fallback_analysis(response_text, brand, citations, raw_response)
        tool_input = json.loads(tool_calls[0].function.arguments)
        found = tool_input.get("mention_found") is True
        result = {
            "mention_found": found,
            "mention_type": (tool_input.get("mention_type") or "direct") if found else "none",
            "sentiment": _clamp(tool_input.get("sentiment"), -1, 1, 0.0),
            "confidence_score": _clamp(tool_input.get("confidence"), 0, 1, 0.5),
            "snippet": (tool_input.get("evidence_snippet") or None),
            "citations": citations,
            "reasoning": tool_input.get("reasoning") or None,
            "raw_response": raw_response,
        }
        if extract_rich:
            result["rich"] = _extract_rich_fields(tool_input, found)
        return result
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
    keyword: str, brand: str, engine: str, competitor_names: list[str],
    client_ctx: Optional[dict] = None,
) -> dict:
    """Run a single keyword×engine scan: dispatch → classify → competitor pass →
    response analysis.

    Retries transient provider errors up to `brand_scan_max_retries`; auth/quota/
    rate-limit errors are terminal. Raises `ScanFailed` on terminal failure.

    `client_ctx` (domain / gbp / competitor_domains / tracked_names) enriches the
    cell with the structured response analysis (sources, position, competitor
    attributes, discovered competitors, AIO mention kind); when None, the scan
    still works and response_analysis is left null."""
    result = None
    retry_count = 0
    meta: dict = {}
    max_retries = settings.brand_scan_max_retries
    while retry_count <= max_retries and result is None:
        try:
            dispatched = await _dispatch(engine, keyword, brand)
        except ScanFailed:
            # Config errors (no API key / unknown engine) — terminal, don't retry.
            raise
        except ProviderError as exc:
            if exc.status in _TERMINAL_STATUSES:
                raise ScanFailed(
                    "Rate limit exceeded" if exc.status == 429 else "AI service authentication/quota issue"
                )
            retry_count += 1
            continue
        except Exception:
            # Connection resets / timeouts (httpx / openai / anthropic) are
            # transient — retry rather than failing the cell outright.
            retry_count += 1
            continue
        # AIO executors return (text, citations, meta); the rest return a 2-tuple.
        if len(dispatched) == 3:
            response_text, citations, meta = dispatched
        else:
            response_text, citations = dispatched
        if not response_text:
            retry_count += 1
            continue
        result = await analyze_mention(response_text, brand, citations, response_text, extract_rich=True)

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

    # Structured response analysis (best-effort, never fatal to the scan).
    result["response_analysis"] = None
    if client_ctx is not None:
        try:
            result["response_analysis"] = brand_analysis.build_response_analysis(
                rich=result.get("rich"),
                citations=result.get("citations") or [],
                client_domain=client_ctx.get("domain"),
                competitor_domains=client_ctx.get("competitor_domains"),
                tracked_competitor_names=client_ctx.get("tracked_names"),
                brand=brand,
                gbp=client_ctx.get("gbp"),
                aio_inline_domains=meta.get("aio_inline_domains"),
                aio_reference_domains=meta.get("aio_reference_domains"),
                is_aio=engine in ("google_ai_overview", "google_ai_mode"),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("brand_scan.analysis_failed", extra={"error": str(exc)})
    result.pop("rich", None)
    return result


# ── auto-diagnosis (per not-found cell, during the scan) ──────────────────────

async def _autodiagnose(client_id: str, brand: str, keyword: str, raw_response: str) -> Optional[str]:
    """Generate the invisibility diagnosis for a not-found cell, grounded in the
    client's real signals (GBP strength + competitor backlink authority + organic
    rank). Best-effort: returns None (rather than raising) when OpenAI isn't
    configured or the call fails, so a diagnosis hiccup never fails the scan cell.
    Signal gathering is itself best-effort (an empty block just means a less
    grounded diagnosis)."""
    from services import brand_insights

    try:
        block = await brand_insights.build_signals_block(client_id, keyword)
        return await brand_insights.diagnose_invisibility(brand, keyword, raw_response or "", block)
    except brand_insights.InsightUnavailable:
        return None
    except Exception as exc:  # pragma: no cover - defensive; never fail the cell
        logger.warning("brand_scan.autodiagnose_failed", extra={"error": str(exc)})
        return None


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
            supabase.table("clients").select("name, website_url, gbp").eq("id", client_id).limit(1).execute()
        ).data
        if not client_row:
            raise ScanFailed("client_not_found")
        client = client_row[0]
        brand = client.get("name") or ""
        client_gbp = client.get("gbp") or {}
        client_domain = (client.get("website_url") or client_gbp.get("website") or "").strip()

        kw_rows = (
            supabase.table("brand_tracked_keywords")
            .select("id, keyword")
            .eq("client_id", client_id)
            .in_("id", keyword_ids)
            .execute()
        ).data or []
        keyword_by_id = {r["id"]: r["keyword"] for r in kw_rows}

        # Always load tracked competitors (name + website): the names filter the
        # discovered-competitor list and the websites let source analysis flag
        # which sources cite a competitor but not the client. The per-competitor
        # re-classification pass (extra LLM calls) stays gated on the toggle.
        comp_rows = (
            supabase.table("brand_tracked_competitors")
            .select("competitor_name, competitor_website")
            .eq("client_id", client_id)
            .execute()
        ).data or []
        tracked_names = [r["competitor_name"] for r in comp_rows if r.get("competitor_name")]
        competitor_domains = [r["competitor_website"] for r in comp_rows if r.get("competitor_website")]
        competitor_names = tracked_names if include_competitors else []

        client_ctx = {
            "domain": client_domain,
            "gbp": client_gbp,
            "competitor_domains": competitor_domains,
            "tracked_names": tracked_names,
        }

        # Build the work list. On a re-run (e.g. a stale-reap requeue after a
        # worker restart) rows for this batch already exist — reuse the not-yet-
        # completed ones instead of pre-creating duplicates (idempotent resume).
        existing = (
            supabase.table("brand_mention_history")
            .select("id, keyword_id, engine, status")
            .eq("scan_batch_id", scan_batch_id)
            .eq("is_competitor_scan", False)
            .execute()
        ).data or []

        rows_to_process: list[tuple[str, str, str]] = []
        if existing:
            for r in existing:
                if r.get("status") == "completed":
                    continue
                kw = keyword_by_id.get(r.get("keyword_id"))
                if kw:
                    rows_to_process.append((r["id"], kw, r["engine"]))
        else:
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
                    ).data
                    if inserted:
                        rows_to_process.append((inserted[0]["id"], keyword, engine))

        # Process cells with bounded concurrency so a large scan overlaps its
        # network-bound provider calls instead of monopolising the worker.
        counts = {"completed": 0, "failed": 0}
        sem = asyncio.Semaphore(max(1, settings.brand_scan_concurrency))

        async def _process_cell(row_id: str, keyword: str, engine: str) -> None:
            async with sem:
                supabase.table("brand_mention_history").update(
                    {"status": "processing"}
                ).eq("id", row_id).execute()
                try:
                    result = await scan_keyword_engine(keyword, brand, engine, competitor_names, client_ctx)
                    # Auto-diagnose invisibility during the scan so the UI shows
                    # the explanation instantly (no on-click generation). Best-
                    # effort — a missing/failed diagnose leaves the column null
                    # and the on-demand /diagnose endpoint can still backfill it.
                    diagnosis = None
                    if settings.brand_autodiagnose_enabled and not result["mention_found"]:
                        diagnosis = await _autodiagnose(client_id, brand, keyword, result["raw_response"])
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
                        "response_analysis": result.get("response_analysis"),
                        "invisibility_diagnosis": diagnosis,
                        "updated_at": "now()",
                    }).eq("id", row_id).execute()
                    counts["completed"] += 1
                except ScanFailed as exc:
                    supabase.table("brand_mention_history").update(
                        {"status": "failed", "failure_reason": exc.reason, "updated_at": "now()"}
                    ).eq("id", row_id).execute()
                    counts["failed"] += 1
                except Exception as exc:
                    logger.warning("brand_scan.row_error", extra={"row_id": row_id, "error": str(exc)})
                    supabase.table("brand_mention_history").update(
                        {"status": "failed", "failure_reason": "internal_error", "updated_at": "now()"}
                    ).eq("id", row_id).execute()
                    counts["failed"] += 1

        await asyncio.gather(*(_process_cell(rid, kw, eng) for rid, kw, eng in rows_to_process))

        supabase.table("async_jobs").update({
            "status": "complete",
            "result": {
                "scan_batch_id": scan_batch_id,
                "total": len(rows_to_process),
                "completed": counts["completed"],
                "failed": counts["failed"],
            },
            "completed_at": "now()",
        }).eq("id", job_id).execute()
        logger.info(
            "brand_scan.complete",
            extra={"job_id": job_id, "completed": counts["completed"], "failed": counts["failed"]},
        )

        # Compare this scan to the previous one and notify on a regression
        # (visibility drop / an engine gone dark / new misinformation). Best-
        # effort — alerting never affects the scan's own success.
        if counts["completed"]:
            from services import brand_alerts

            brand_alerts.emit_scan_alerts(client_id, scan_batch_id)
    except Exception as exc:
        logger.warning("brand_scan.failed", extra={"job_id": job_id, "error": str(exc)})
        # Don't leave half-created cells stuck as queued/processing — they'd
        # render forever as "in progress" in the matrix.
        try:
            supabase.table("brand_mention_history").update(
                {"status": "failed", "failure_reason": "job_aborted", "updated_at": "now()"}
            ).eq("scan_batch_id", scan_batch_id).in_("status", ["queued", "processing"]).execute()
        except Exception:
            pass
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
