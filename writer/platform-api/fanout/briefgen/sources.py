"""Brief Generator Steps 1-2 — source gathering (M13 slice 2).

Fetches the candidate-source bundle the later slices (intent, gates, MCS) consume:
the SERP (organic results + headings via the shared SIE scrape), the **AI Overview**
answer (X.1 — an MCS scoring target), PAA, Reddit discussions, autocomplete +
keyword suggestions, and the **LLM fan-out** answers (ChatGPT + Gemini — the other
MCS targets; E4 trims Claude + Perplexity).

The DataForSEO egress is thin (`dataforseo/client.py` returns raw items[]); the
parsers here are PURE and unit-tested with fixtures. The Reddit / LLM-Responses /
AIO shapes are docs-derived — confirm on the first deployed brief run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fanout.concurrency import ContextThreadPoolExecutor

logger = logging.getLogger(__name__)

# E4: the answer-engine fan-out is ChatGPT + Gemini only (Claude + Perplexity dropped).
DEFAULT_LLM_PROVIDERS = ("chat_gpt", "gemini")


# ----- pure parsers ---------------------------------------------------------


def parse_organic(items: list[dict], depth: int = 20) -> list[dict]:
    """Top organic results with metadata (url/title/description/rank)."""
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "organic":
            continue
        url = item.get("url")
        if not url:
            continue
        out.append({
            "url": url,
            "title": item.get("title"),
            "description": item.get("description"),
            "rank": _coerce_int(item.get("rank_absolute")) or len(out) + 1,
        })
        if len(out) >= depth:
            break
    return out


def parse_paa(items: list[dict]) -> list[str]:
    """People-Also-Ask questions from the SERP items."""
    questions: list[str] = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "people_also_ask":
            continue
        for q in item.get("items") or []:
            title = q.get("title") if isinstance(q, dict) else None
            if title:
                questions.append(title)
    return questions


def parse_aio(items: list[dict]) -> dict:
    """X.1 AI-Overview target: {present, answer_text, cited_sources}. Absent AIO is a
    normal, common case (`present: False`) the answer-engine path degrades on."""
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "ai_overview":
            continue
        texts: list[str] = []
        if isinstance(item.get("text"), str):
            texts.append(item["text"])
        for el in item.get("items") or []:
            if isinstance(el, dict) and isinstance(el.get("text"), str):
                texts.append(el["text"])
        sources: list[dict] = []
        for ref in item.get("references") or []:
            if not isinstance(ref, dict):
                continue
            url = ref.get("url")
            if url:
                sources.append({
                    "url": url, "domain": ref.get("domain"), "title": ref.get("title"),
                })
        return {
            "present": True,
            "answer_text": "\n".join(t for t in texts if t).strip(),
            "cited_sources": sources,
        }
    return {"present": False, "answer_text": "", "cited_sources": []}


def parse_discussions_forums(items: list[dict]) -> list[dict]:
    """Step 2B discovery: Reddit/forum threads from the native **Discussions and
    Forums** SERP feature (Google-curated; mostly Reddit + Quora). Returns
    {title, url, domain, posts_count}. Handles both the container item (`type:
    discussions_and_forums` with nested `items`) and flat `..._element` items.
    Shape is docs-derived — confirm live."""
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        t = item.get("type")
        if t == "discussions_and_forums":
            for el in item.get("items") or []:
                _add_forum(out, el)
        elif t == "discussions_and_forums_element":
            _add_forum(out, item)
    return out


def _add_forum(out: list[dict], el) -> None:
    if not isinstance(el, dict):
        return
    url = el.get("url")
    if not url:
        return
    out.append({
        "title": el.get("title"), "url": url, "domain": el.get("domain"),
        "posts_count": _coerce_int(el.get("posts_count")),
    })


def _is_reddit(url: str | None) -> bool:
    from urllib.parse import urlparse

    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return host == "reddit.com" or host.endswith(".reddit.com")


def fetch_discussion_content(
    threads: list[dict], scrapeowl, *, top_n: int = 4, char_limit: int = 4000,
    max_workers: int = 4,
) -> list[dict]:
    """Scrape the top discussion threads (Reddit first) for real comment/pain-point
    text — what `reddit_insights`/persona actually need. Reuses the SIE ScrapeOwl
    client (premium fallback) + extract_zones; a failed/empty scrape yields
    content=None for that thread (degrade, don't fail). The threads are scraped
    CONCURRENTLY (each scrape can take 35s + a premium retry; serial would add
    minutes to every brief). `pool.map` preserves the Reddit-first order."""
    from fanout.sie.extract import extract_zones

    ordered = sorted(threads, key=lambda t: 0 if _is_reddit(t.get("url")) else 1)[:top_n]
    if not ordered:
        return []

    def _one(t: dict) -> dict:
        content = None
        try:
            sc = scrapeowl.scrape(t["url"])
            if sc.scrape_status == "success" and sc.html:
                page = extract_zones(sc.html, t["url"])
                text = " ".join([*page.zones.paragraphs, *page.zones.lists]).strip()
                content = text[:char_limit] or None
        except Exception as exc:  # noqa: BLE001 — one bad thread degrades, not the brief
            logger.warning(
                "brief_discussion_scrape_failed",
                extra={"event": "brief_discussion_scrape_failed",
                       "url": t.get("url"), "reason": repr(exc)},
            )
        return {**t, "content": content}

    with ContextThreadPoolExecutor(max_workers=min(max_workers, len(ordered))) as pool:
        return list(pool.map(_one, ordered))


def parse_llm_answer(items: list[dict]) -> str | None:
    """One LLM's answer text from the AI-Optimization "LLM Responses" items. The exact
    shape is docs-derived, so we pull text from the common keys / nested blocks
    defensively (confirm live)."""
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("text", "message", "content", "answer"):
            if isinstance(item.get(key), str):
                parts.append(item[key])
        for nest_key in ("sections", "items"):
            sub_list = item.get(nest_key)
            if not isinstance(sub_list, list):   # a non-list `sections` must not crash
                continue
            for sub in sub_list:
                if isinstance(sub, dict) and isinstance(sub.get("text"), str):
                    parts.append(sub["text"])
    text = "\n".join(p for p in parts if p).strip()
    return text or None


def _coerce_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ----- orchestration --------------------------------------------------------


@dataclass
class BriefSources:
    keyword: str
    organic: list[dict] = field(default_factory=list)
    aio: dict = field(default_factory=lambda: {"present": False, "answer_text": "", "cited_sources": []})
    paa: list[str] = field(default_factory=list)
    # Discussions/Forums threads (Reddit first) — {title,url,domain,posts_count,content}.
    reddit: list[dict] = field(default_factory=list)
    autocomplete: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    llm_answers: dict[str, str] = field(default_factory=dict)  # {provider: answer_text}


def gather_sources(
    keyword: str, dfs, *, scrapeowl=None, depth: int = 20, llm_prompt: str | None = None,
    llm_providers: tuple[str, ...] = DEFAULT_LLM_PROVIDERS, max_discussion_threads: int = 4,
    max_workers: int = 6,
) -> BriefSources:
    """Run Steps 1-2 and assemble `BriefSources`. Step 1 is one SERP-advanced call
    (organic + AIO + PAA + the Discussions/Forums thread list together — E2/E3); it
    runs first because the discussion threads feed the Reddit scrape. The remaining
    sources (discussion-content scrape, autocomplete, suggestions, LLM fan-out) run
    concurrently. Per-source failures degrade that source (logged), not the brief."""
    prompt = llm_prompt or keyword
    src = BriefSources(keyword=keyword)

    # Step 1 (shared SERP) — blocking, yields the discussion threads the scrape needs.
    items = dfs.serp_advanced_items(keyword, depth=depth)
    src.organic = parse_organic(items, depth)
    src.aio = parse_aio(items)
    src.paa = parse_paa(items)
    threads = parse_discussions_forums(items)

    def _discussions() -> None:
        if scrapeowl is not None and threads:
            src.reddit = fetch_discussion_content(
                threads, scrapeowl, top_n=max_discussion_threads
            )
        else:  # no scraper wired (or no threads) — keep the metadata-level threads
            src.reddit = [{**t, "content": None} for t in threads[:max_discussion_threads]]

    def _autocomplete() -> None:
        src.autocomplete = dfs.autocomplete(keyword)

    def _suggestions() -> None:
        src.suggestions = dfs.keyword_suggestions(keyword)

    def _llm(provider: str):
        def run() -> None:
            src.llm_answers[provider] = parse_llm_answer(
                dfs.llm_response_items(prompt, provider)
            ) or ""
        run.__name__ = f"llm[{provider}]"   # so a failure logs the provider, not "run"
        return run

    tasks = [_discussions, _autocomplete, _suggestions, *(_llm(p) for p in llm_providers)]

    def _safe(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — one bad source degrades, not the brief
            logger.warning(
                "brief_source_failed",
                extra={"event": "brief_source_failed", "source": fn.__name__,
                       "keyword": keyword, "reason": repr(exc)},
            )

    with ContextThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(_safe, tasks))
    return src
