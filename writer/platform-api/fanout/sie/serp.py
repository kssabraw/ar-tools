"""SIE Modules 2–3: SERP collection (DataForSEO `serp_top_results`) + URL
classification (one batched Haiku tool-use call) + near-duplicate detection (pure).

M2 lives on the DataForSEO client; this module owns M3. `classify_results` is the
only egress here; `near_duplicates` is pure (first-500-char similarity) and tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

PAGE_CATEGORIES = (
    "direct competitor", "informational article", "local service page",
    "product/service landing page", "directory", "forum / UGC", "marketplace",
    "government / educational", "video result", "news result",
    "social media result", "irrelevant result",
)
# Categories whose pages are content-eligible for n-gram/entity/usage extraction.
_ELIGIBLE = {
    "direct competitor", "informational article", "local service page",
    "product/service landing page", "government / educational",
}
_NEAR_DUP_WINDOW = 500
_NEAR_DUP_THRESHOLD = 0.90

# Social/video platforms are never content-eligible — decided deterministically here
# rather than left to the LLM classifier. They aren't on-page SEO competitors and
# routinely block scraping (so they'd burn a ScrapeOwl call and degrade anyway).
_SKIP_DOMAINS = (
    "facebook.com", "instagram.com", "youtube.com", "youtu.be",
    "pinterest.com", "tiktok.com",
)


def _is_skip_domain(url: str) -> bool:
    from urllib.parse import urlparse

    try:
        host = urlparse(url).netloc.lower().split(":")[0]
    except ValueError:
        return False
    if host.startswith("www."):
        host = host[4:]
    return any(host == d or host.endswith("." + d) for d in _SKIP_DOMAINS)


@dataclass
class ClassifiedURL:
    url: str
    rank: int | None
    title: str | None
    page_category: str
    content_eligible: bool
    reason: str


def classify_results(results: list[dict], keyword: str, llm) -> list[ClassifiedURL]:
    """One batched Haiku tool-use call classifying all SERP results into the 12
    categories with `content_eligible` + reason (PRD M3). On LLM failure the caller
    degrades; here we raise via `llm.call_tool`."""
    if not results:
        return []
    schema = {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "page_category": {"type": "string", "enum": list(PAGE_CATEGORIES)},
                        "content_eligible": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["url", "page_category", "content_eligible", "reason"],
                },
            }
        },
        "required": ["classifications"],
    }
    listing = "\n".join(
        f"{r.get('rank')}. {r['url']} — {r.get('title') or ''} — {r.get('description') or ''}"
        for r in results
    )
    out = llm.call_tool(
        system=(
            "You classify Google SERP results for on-page SEO analysis. Mark "
            "content_eligible=true only for substantive content pages (competitor, "
            "informational, local service, product/landing, gov/edu). Mark "
            "directories, forums/UGC, marketplaces, video, news, social, and "
            "irrelevant results content_eligible=false."
        ),
        user=f"Target keyword: {keyword}\n\nResults:\n{listing}",
        tool_name="classify_serp",
        tool_description="Return a classification for every result URL.",
        input_schema=schema,
        purpose="sie_url_classification",
    )
    by_url = {c["url"]: c for c in out.get("classifications", [])}
    classified: list[ClassifiedURL] = []
    for r in results:
        if _is_skip_domain(r["url"]):
            classified.append(ClassifiedURL(
                url=r["url"], rank=r.get("rank"), title=r.get("title"),
                page_category="social media result", content_eligible=False,
                reason="skipped (social/video platform)",
            ))
            continue
        c = by_url.get(r["url"], {})
        category = c.get("page_category", "irrelevant result")
        classified.append(ClassifiedURL(
            url=r["url"], rank=r.get("rank"), title=r.get("title"),
            page_category=category,
            content_eligible=bool(c.get("content_eligible", category in _ELIGIBLE)),
            reason=c.get("reason", "no classification returned"),
        ))
    return classified


def near_duplicates(
    body_by_url: list[tuple[str, int, str]]
) -> dict[str, tuple[str, float]]:
    """PURE (PRD M3). Input: (url, rank, cleaned_body_text) for content-eligible
    pages. Compares the first 500 chars between all pairs; pages >90% similar have
    the LOWER-ranked one flagged as a duplicate of the higher-ranked canonical.
    Returns {duplicate_url: (canonical_url, similarity)}."""
    items = sorted(
        ((u, rank if rank is not None else 10**6, (text or "")[:_NEAR_DUP_WINDOW])
         for u, rank, text in body_by_url),
        key=lambda t: t[1],
    )
    dups: dict[str, tuple[str, float]] = {}
    for i, (canon_url, _crank, canon_text) in enumerate(items):
        if canon_url in dups or not canon_text:
            continue
        for dup_url, _drank, dup_text in items[i + 1:]:
            if dup_url in dups or not dup_text:
                continue
            sim = SequenceMatcher(None, canon_text, dup_text).ratio()
            if sim > _NEAR_DUP_THRESHOLD:
                dups[dup_url] = (canon_url, round(sim, 3))
    return dups
