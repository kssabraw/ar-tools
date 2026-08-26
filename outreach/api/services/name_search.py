"""Web-search owner/manager name — the PAID third-rung fallback (fetch + parse).

When Outscraper enrichment returned no NAME and the free `name_scrape` of the site found none
either, the team can pay for a web search that looks the owner/manager up. One OpenAI web-search call
per prospect (the Responses API + `web_search` tool, called over httpx to match this module's OpenAI
transport — no `openai` SDK dependency), grounded on the business's own identity (name + address +
category + website) so the model resolves THIS business, not a similarly-named one elsewhere.

**This is the lowest-trust name source, so the anti-fabrication guard is the strictest.** A name is
kept ONLY when:
  * the search returns a real SOURCE URL that names the person (the require-citation rule — an
    uncited name is dropped, per the owner ruling), and
  * the name passes the SAME business-name / stopword plausibility guard as the site-scrape
    (`name_extract.is_plausible_name`), so the business itself can't be returned as a person.
Kept names are stored + surfaced as "web-sourced, unverified" with their citation. The parser is
PURE and never trusts the model's prose — it reads a strict JSON answer defensively and cross-checks
the citation.

The network + billing live here; the parse is pure. The drain (`name_search_queue.py`) owns the
signed-order / budget / cost-ledger machinery (this BILLS, unlike `name_scrape`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import Settings
from . import name_extract

logger = logging.getLogger(__name__)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class NameSearchError(Exception):
    """A billed web search that failed at the transport/provider layer (retryable)."""


@dataclass(frozen=True)
class SearchedName:
    """One owner/manager the web search returned WITH a citation. `citation` is the source URL that
    names the person — a SearchedName never exists without one (the require-citation guard)."""

    full_name: str
    title: str | None
    citation: str
    evidence: str
    first_name: str | None = None
    last_name: str | None = None

    def as_contact(self) -> dict[str, Any]:
        return {
            "full_name": self.full_name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "title": self.title,
        }


@dataclass(frozen=True)
class NameSearchResult:
    """What searching one prospect produced. `found` carries ≥1 cited name; `no_names` = the search
    ran and returned no citable owner (a real, billed outcome). A transport failure is an error, not
    a NameSearchResult, so it stays retryable."""

    prospect_id: str
    status: str            # found | no_names
    names: tuple[SearchedName, ...]
    model: str
    citations: tuple[str, ...]
    raw: dict[str, Any]

    @property
    def name_count(self) -> int:
        return len(self.names)


def build_prompt(prospect: dict[str, Any]) -> str:
    """The grounded search prompt. Pure. Anchors on the business's OWN identity so the model resolves
    this exact business, and forces a strict JSON answer with a required source URL."""
    name = (prospect.get("name") or "").strip()
    address = (prospect.get("address") or "").strip()
    category = (prospect.get("category") or "").strip()
    website = (prospect.get("website") or "").strip()
    facts = [f"Business name: {name or '(unknown)'}"]
    if address:
        facts.append(f"Address: {address}")
    if category:
        facts.append(f"Category: {category}")
    if website:
        facts.append(f"Website: {website}")
    return (
        "You are researching the OWNER, founder, or top MANAGER of one specific local business. "
        "Use web search. Identify the person who owns or runs THIS EXACT business — match the "
        "address and website; do NOT confuse it with a similarly-named business elsewhere, and do "
        "NOT guess.\n\n"
        + "\n".join(facts)
        + "\n\nRespond with ONLY a JSON object, no prose:\n"
        '{"found": true|false, "name": "Full Name" or null, '
        '"title": "Owner"|"Founder"|"President"|"General Manager"|... or null, '
        '"source_url": "https://the-page-that-names-them" or null}\n'
        "Set found=true ONLY if a real, citable web source names the person for THIS business, and "
        "put that page's URL in source_url. If you cannot find a cited name, set found=false and "
        "name=null. Never invent a name or a source."
    )


# --- pure parsing ----------------------------------------------------------------------------

_JSON_OBJ = re.compile(r"\{.*\}", re.S)
_URL_RE = re.compile(r"^https?://[^\s]+$", re.I)


def _first_json_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in the model's text (it may be fenced or prose-wrapped). Pure, tolerant
    — returns None rather than raising on anything that isn't a JSON object."""
    if not text:
        return None
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict):
            return obj
    except (ValueError, TypeError):
        pass
    m = _JSON_OBJ.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _clean_url(value: Any, fallback: tuple[str, ...]) -> str | None:
    """A usable citation URL: the model's source_url if it's a real http(s) URL, else the first
    web-search citation annotation. None when neither exists (→ the name is dropped)."""
    if isinstance(value, str) and _URL_RE.match(value.strip()):
        return value.strip()
    for url in fallback:
        if isinstance(url, str) and _URL_RE.match(url.strip()):
            return url.strip()
    return None


def parse_search_answer(
    text: str, citations: list[str], *, business_name: str | None, max_names: int = 2
) -> list[SearchedName]:
    """Turn one search response into kept, CITED names. Pure.

    The require-citation guard: a name is kept only with a real source URL (the model's `source_url`
    or, failing that, a `url_citation` the search returned) AND only if it passes the same
    business-name/stopword plausibility guard as the site-scrape. Returns [] for `found:false`, a
    missing/implausible name, or — critically — a name with no citation."""
    obj = _first_json_object(text)
    if not obj or not obj.get("found"):
        return []
    name = obj.get("name")
    if not isinstance(name, str) or not name.strip():
        return []
    name = re.sub(r"\s+", " ", name).strip()

    business_tokens = name_extract._business_tokens(business_name)
    if not name_extract.is_plausible_name(name, business_tokens=business_tokens):
        return []

    citation = _clean_url(obj.get("source_url"), tuple(citations))
    if not citation:
        # No citable source → drop (the whole point of this guard). A web-search name we can't point
        # a caller at is exactly the hallucinated-owner case the module refuses to store.
        return []

    title = obj.get("title")
    title = re.sub(r"\s+", " ", title).strip() if isinstance(title, str) and title.strip() else None
    parts = name.split(" ")
    first = parts[0] if parts else None
    last = parts[-1] if len(parts) > 1 else None
    return [
        SearchedName(
            full_name=name, title=title, citation=citation,
            evidence=f"web search — cited at {citation}", first_name=first, last_name=last,
        )
    ][:max_names]


def extract_output(output: list[Any]) -> tuple[str, list[str]]:
    """The assistant text + url_citation URLs from an OpenAI Responses `output` array. Pure — mirrors
    the suite brand-scan's `_extract_openai` so the citation shape has one definition."""
    text, citations = "", []
    for item in output or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text" or content.get("text"):
                text += content.get("text") or ""
            for ann in content.get("annotations") or []:
                url = (ann or {}).get("url") if isinstance(ann, dict) else None
                if ann.get("type") == "url_citation" and url and url not in citations:
                    citations.append(url)
    return text, citations


# --- impure producer -------------------------------------------------------------------------


async def _openai_web_search(
    settings: Settings, prompt: str, *, client: httpx.AsyncClient | None = None
) -> tuple[str, list[str]]:
    """One OpenAI Responses web-search call → (assistant_text, citation_urls). BILLS. Raises
    NameSearchError on any transport/provider failure (so the drain marks the prospect retryable)."""
    payload = {
        "model": settings.name_search_model,
        "tools": [{"type": settings.name_search_web_search_tool}],
        "input": prompt,
    }
    owns = client is None
    http = client or httpx.AsyncClient(timeout=settings.name_search_request_timeout_seconds)
    try:
        resp = await http.post(
            OPENAI_RESPONSES_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
        resp.raise_for_status()
        body = resp.json()
    except httpx.HTTPStatusError as exc:
        raise NameSearchError(f"HTTP {exc.response.status_code} from {exc.request.url}") from exc
    except httpx.HTTPError as exc:
        raise NameSearchError(f"transport error: {exc}") from exc
    finally:
        if owns:
            await http.aclose()
    return extract_output(body.get("output") or [])


async def search_owner_name(
    prospect: dict[str, Any], settings: Settings, *, client: httpx.AsyncClient | None = None
) -> NameSearchResult:
    """Search one prospect's owner/manager name. BILLS one web search. Returns a NameSearchResult
    (found | no_names); raises NameSearchError on a transport/provider failure (retryable)."""
    text, citations = await _openai_web_search(settings, build_prompt(prospect), client=client)
    names = parse_search_answer(
        text, citations, business_name=prospect.get("name"),
        max_names=settings.name_search_max_names,
    )
    return NameSearchResult(
        prospect_id=prospect["id"],
        status="found" if names else "no_names",
        names=tuple(names),
        model=settings.name_search_model,
        citations=tuple(dict.fromkeys([n.citation for n in names] + list(citations))),
        raw={"text": text[:4000], "citations": citations[:20]},
    )


async def search_names(
    settings: Settings,
    prospects: list[dict[str, Any]],
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[NameSearchResult], list[str]]:
    """Search a set of prospects. Returns `(results, errors)`. BILLS one search per prospect.

    Bounded concurrency (`name_search_chunk_size`) on ONE shared client. A per-prospect failure is
    REPORTED (never swallowed) and never aborts the rest — every prospect is billed independently
    (the `enrich_places` per-record-isolation discipline: a failure on one must not discard the
    records the others were charged for)."""
    if not prospects:
        return [], []
    owns = client is None
    http = client or httpx.AsyncClient(timeout=settings.name_search_request_timeout_seconds)
    results: list[NameSearchResult] = []
    errors: list[str] = []
    sem = asyncio.Semaphore(max(1, settings.name_search_chunk_size))

    async def _guarded(prospect: dict[str, Any]) -> None:
        async with sem:
            try:
                got = await search_owner_name(prospect, settings, client=http)
            except Exception as exc:  # noqa: BLE001 — a billed prospect already spent; keep the rest
                errors.append(f"{prospect.get('id')}: {str(exc)[:200]}")
                logger.warning("name search failed",
                               extra={"prospect_id": prospect.get("id"), "error": str(exc)[:300]})
                return
            results.append(got)

    try:
        await asyncio.gather(*(_guarded(p) for p in prospects))
    finally:
        if owns:
            await http.aclose()
    return results, errors
