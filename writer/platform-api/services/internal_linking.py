"""Internal-linking analyzer + injector (design §6.5).

**Analyzer** builds a topical map of the client's pages and finds opportunities to
link one page to another: a page whose body text mentions another page's topic
phrase, where no link to that page exists yet. Silo-aware in spirit — anchor
candidates come from each page's title + its tracked/Local-SEO keyword, so links
form between topically related pages, not random word matches.

**Injector** is the gated live-site mutation. Because adding a link edits a live
page, each opportunity is stored as an `internal_link_edits` row with its own
approve/deny lifecycle: the analyzer notifies the team, a human reviews and
approves, and ONLY THEN does the WordPress injector write the link (preserving
the post's published status). Non-WordPress pages produce recommend-only edits
(`injectable=false`) the team applies by hand.

Page inventory + content come from the **WordPress REST API** when app-password
creds are configured (also the write path), else from a **sitemap + ScrapeOwl
crawl** (recommend-only). The pure analysis/injection helpers (no I/O) are
unit-tested; the fetch/write paths are best-effort and mocked in tests.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

from bs4 import BeautifulSoup, NavigableString

from config import settings
from db.supabase_client import get_supabase
from services import notifications, site_page_index, website_scraper, wordpress_publish

logger = logging.getLogger("internal_linking")

# Structural / boilerplate tags whose text is never an anchor source or target.
_SKIP_TAGS = {"a", "nav", "header", "footer", "script", "style", "aside", "form", "button"}


# ── pure helpers (unit-tested) ───────────────────────────────────────────────
def norm_url(url: Optional[str]) -> Optional[str]:
    """Normalize a URL for comparison: lowercase host, drop scheme/query/fragment,
    strip a trailing slash. Pure."""
    if not url:
        return None
    s = url.strip()
    if "//" not in s:
        s = "http://" + s
    p = urlparse(s)
    host = (p.netloc or "").lower()
    path = (p.path or "").rstrip("/")
    if not host:
        return None
    # Lowercase the whole key so link dedup is case-insensitive (both targets and
    # existing hrefs run through here, so the comparison stays consistent).
    return f"{host}{path}".lower() or host


def _phrase_regex(phrase: str) -> re.Pattern:
    """Whole-phrase, case-insensitive matcher (won't match inside a longer word)."""
    return re.compile(r"(?<![\w-])" + re.escape(phrase.strip()) + r"(?![\w-])", re.IGNORECASE)


def _within_skip(node) -> bool:
    for parent in node.parents:
        if getattr(parent, "name", None) in _SKIP_TAGS:
            return True
    return False


def visible_text(html: str) -> str:
    """Concatenated visible text, excluding boilerplate + already-linked text. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    parts = [str(t) for t in soup.find_all(string=True) if not _within_skip(t)]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def extract_existing_links(html: str, *, internal_host: Optional[str] = None) -> set[str]:
    """Normalized hrefs already linked from the page. When ``internal_host`` is
    given, only same-host links are kept (internal targets). Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: set[str] = set()
    for a in soup.find_all("a", href=True):
        n = norm_url(a["href"])
        if not n:
            continue
        if internal_host and not n.startswith(internal_host.lower()):
            continue
        out.add(n)
    return out


def _clean_title(title: str) -> str:
    """Title minus a trailing ' | Brand' / ' - Brand' separator segment."""
    t = re.sub(r"\s*[|–—-]\s*[^|–—-]{1,40}$", "", (title or "").strip())
    return t.strip() or (title or "").strip()


def page_anchor_phrases(
    title: str, keywords: Optional[list[str]] = None, *, min_words: int = 2, max_words: int = 8
) -> list[str]:
    """Candidate anchor phrases a page can be linked TO, best (most specific)
    first: its tracked/Local-SEO keywords, then its cleaned title. Deduped,
    length-bounded so single common words / whole sentences aren't anchors. Pure."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in [*(keywords or []), _clean_title(title)]:
        phrase = re.sub(r"\s+", " ", (raw or "").strip())
        wc = len(phrase.split())
        if not (min_words <= wc <= max_words):
            continue
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(phrase)
    return out


def _context_snippet(text: str, match: re.Match, width: int = 60) -> str:
    start = max(0, match.start() - width)
    end = min(len(text), match.end() + width)
    snippet = text[start:end].strip()
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


def find_opportunities(
    pages: list[dict],
    *,
    max_per_page: int = 3,
    max_inbound_per_target: int = 5,
    min_words: int = 2,
) -> list[dict]:
    """Find internal-link opportunities across a page set. Pure (unit-tested).

    ``pages`` = ``[{url, title, html, post_id?, type?, keywords?}]``. For each
    source page, scan its visible text for another page's anchor phrase where (a)
    the source doesn't already link to that target, (b) caps aren't exceeded, and
    (c) the phrase is specific enough (≥ min_words). Returns edit dicts ranked by
    match_score (longer/keyword-backed anchors score higher); at most one edit per
    (source, target) pair."""
    prepped = []
    for p in pages:
        n = norm_url(p.get("url"))
        if not n:
            continue
        host = (urlparse(p["url"] if "//" in p["url"] else "http://" + p["url"]).netloc or "").lower()
        prepped.append({
            **p,
            "norm": n,
            "host": host,
            "text": visible_text(p.get("html") or ""),
            "existing": extract_existing_links(p.get("html") or "", internal_host=host),
            "phrases": page_anchor_phrases(p.get("title") or "", p.get("keywords"), min_words=min_words),
            "kwset": {k.lower() for k in (p.get("keywords") or [])},
        })

    edits: list[dict] = []
    inbound: dict[str, int] = {}
    for src in prepped:
        if not src["text"]:
            continue
        per_page = 0
        linked_targets = set(src["existing"])
        # Targets ranked by best available anchor match against this source's text.
        for tgt in prepped:
            if per_page >= max_per_page:
                break
            if tgt["norm"] == src["norm"]:
                continue  # never self-link
            if tgt["norm"] in linked_targets:
                continue  # already links here
            if inbound.get(tgt["norm"], 0) >= max_inbound_per_target:
                continue
            for phrase in tgt["phrases"]:
                m = _phrase_regex(phrase).search(src["text"])
                if not m:
                    continue
                score = len(phrase.split()) + (2 if phrase.lower() in tgt["kwset"] else 0)
                edits.append({
                    "source_url": src["url"],
                    "source_post_id": src.get("post_id"),
                    "source_type": src.get("type"),
                    "target_url": tgt["url"],
                    "anchor_text": m.group(0),  # preserve the source's actual casing
                    "context": _context_snippet(src["text"], m),
                    "match_score": score,
                    "injectable": bool(src.get("post_id")),
                })
                linked_targets.add(tgt["norm"])
                inbound[tgt["norm"]] = inbound.get(tgt["norm"], 0) + 1
                per_page += 1
                break  # one edit per (source, target)
    edits.sort(key=lambda e: e["match_score"], reverse=True)
    return edits


def inject_link_html(html: str, anchor_text: str, target_url: str) -> tuple[str, bool]:
    """Wrap the first unlinked, non-boilerplate occurrence of ``anchor_text`` in an
    ``<a href=target_url>``. Returns (new_html, injected?). Pure — uses bs4 so it
    never breaks inside an existing tag/link."""
    soup = BeautifulSoup(html or "", "html.parser")
    rx = _phrase_regex(anchor_text)
    for node in soup.find_all(string=True):
        if _within_skip(node):
            continue
        s = str(node)
        m = rx.search(s)
        if not m:
            continue
        before, matched, after = s[: m.start()], s[m.start(): m.end()], s[m.end():]
        link = soup.new_tag("a", href=target_url)
        link.string = matched
        node.replace_with(link)
        if before:
            link.insert_before(NavigableString(before))
        if after:
            link.insert_after(NavigableString(after))
        return str(soup), True
    return html or "", False


# ── page inventory (WordPress REST or sitemap+ScrapeOwl crawl) ────────────────
async def fetch_pages(client: dict) -> tuple[list[dict], str, Optional[str]]:
    """Return (pages, mode, degraded_note). WordPress (app-password) → REST
    inventory with content, injectable. Else → sitemap + ScrapeOwl crawl,
    recommend-only. Best-effort: a fetch failure degrades to an empty set."""
    client_id = client["id"]
    if wordpress_publish.client_is_configured(client):
        try:
            items = await wordpress_publish.list_content(
                client, max_pages=settings.internal_link_wp_max_pages
            )
            pages = [
                {"url": it["url"], "title": it["title"], "html": it["html"],
                 "post_id": it["id"], "type": it["type"]}
                for it in items if it.get("url") and it.get("id")
            ]
            return pages, "wordpress", None if pages else "no_wordpress_content"
        except Exception as exc:  # noqa: BLE001
            logger.warning("internal_linking.wp_inventory_failed",
                           extra={"client_id": client_id, "error": str(exc)})
            return [], "wordpress", "wordpress_inventory_failed"

    website = client.get("website_url") or client.get("website")
    if not website:
        return [], "crawl", "no_website"
    from services import dataforseo_rank

    location_code = dataforseo_rank.location_code_for(client)
    try:
        urls, note = await site_page_index.discover_site_urls(website, location_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("internal_linking.discover_failed", extra={"client_id": client_id, "error": str(exc)})
        return [], "crawl", "site_discovery_failed"
    urls = urls[: settings.internal_link_crawl_max_pages]
    pages: list[dict] = []
    for u in urls:
        try:
            html = await website_scraper.scrapeowl_fetch(u)
        except Exception as exc:  # noqa: BLE001 — one bad page mustn't abort the crawl
            logger.warning("internal_linking.fetch_failed", extra={"url": u, "error": str(exc)})
            continue
        soup = BeautifulSoup(html or "", "html.parser")
        title = (soup.title.string if soup.title and soup.title.string else "") or ""
        pages.append({"url": u, "title": title.strip(), "html": html, "post_id": None, "type": None})
    return pages, "crawl", (note or None) if not pages else None


# ── analysis run (store edits + notify) ──────────────────────────────────────
async def run_analysis(client_id: str, engagement_id: Optional[str] = None) -> dict:
    """Fetch the client's pages, find link opportunities, store them as proposed
    edits (one batch), and notify the team to review. Supersedes the prior batch's
    still-proposed edits so the review surface shows only the latest run."""
    supabase = get_supabase()
    client = supabase.table("clients").select("*").eq("id", client_id).limit(1).execute().data
    if not client:
        raise ValueError("client_not_found")
    client = client[0]

    pages, mode, note = await fetch_pages(client)
    edits = find_opportunities(
        pages,
        max_per_page=settings.internal_link_max_per_page,
        max_inbound_per_target=settings.internal_link_max_inbound_per_target,
        min_words=settings.internal_link_min_anchor_words,
    )

    batch_id = str(uuid4())
    # Supersede prior still-proposed edits (a fresh run replaces stale suggestions).
    supabase.table("internal_link_edits").update({"status": "superseded"}) \
        .eq("client_id", client_id).eq("status", "proposed").execute()

    if edits:
        rows = [{
            "client_id": client_id, "engagement_id": engagement_id, "batch_id": batch_id,
            "source_url": e["source_url"], "source_post_id": str(e["source_post_id"]) if e.get("source_post_id") else None,
            "source_type": e.get("source_type"), "target_url": e["target_url"],
            "anchor_text": e["anchor_text"], "context": e.get("context"),
            "match_score": e.get("match_score"), "injectable": e.get("injectable", False),
        } for e in edits]
        supabase.table("internal_link_edits").insert(rows).execute()
        notifications.emit(
            client_id=client_id, kind="internal_links",
            title=f"{len(edits)} internal-link suggestion{'s' if len(edits) != 1 else ''} to review",
            summary=("Approve the ones to apply" + (" (WordPress — applied automatically once approved)"
                     if mode == "wordpress" else " (recommend-only — apply by hand)")) + ".",
            severity="info",
            payload={"link": f"clients/{client_id}/internal-links", "batch_id": batch_id, "mode": mode},
        )

    result = {"batch_id": batch_id, "mode": mode, "pages": len(pages),
              "edit_count": len(edits), "injectable": mode == "wordpress"}
    if note:
        result["degraded"] = note
    logger.info("internal_link_analysis_complete",
                extra={"client_id": client_id, "mode": mode, "pages": len(pages), "edits": len(edits)})
    return result


# ── injection (apply approved edits — the gated live mutation) ─────────────────
async def apply_approved_edits(client_id: str, batch_id: Optional[str] = None) -> dict:
    """Inject every APPROVED, injectable edit into its WordPress page (preserving
    published status) and mark it applied. Only runs after a human approved each
    edit. Best-effort per edit: a failure marks that row failed, never aborts the
    rest. Re-fetches each post fresh so we inject into current content."""
    supabase = get_supabase()
    client = supabase.table("clients").select("*").eq("id", client_id).limit(1).execute().data
    if not client:
        raise ValueError("client_not_found")
    client = client[0]
    if not wordpress_publish.client_is_configured(client):
        return {"status": "skipped", "reason": "wordpress_not_configured", "applied": 0}

    q = (
        supabase.table("internal_link_edits").select("*")
        .eq("client_id", client_id).eq("status", "approved").eq("injectable", True)
    )
    if batch_id:
        q = q.eq("batch_id", batch_id)
    pending = q.execute().data or []
    if not pending:
        return {"status": "noop", "applied": 0}

    # Group by source post so each page is fetched + written once (multiple links).
    by_post: dict[tuple, list[dict]] = {}
    for e in pending:
        by_post.setdefault((e["source_post_id"], e.get("source_type") or "posts"), []).append(e)

    # Fetch the live inventory ONCE; inject into the current content of each post.
    inv = await wordpress_publish.list_content(client, max_pages=settings.internal_link_wp_max_pages)
    inv_by_id = {str(i.get("id")): i for i in inv}

    applied = 0
    failed = 0
    for (post_id, resource), group in by_post.items():
        try:
            current = inv_by_id.get(str(post_id))
            html = current["html"] if current else None
            if not html:
                raise wordpress_publish.WordPressPublishError("post_content_unavailable")
            done_ids: list[str] = []
            for e in group:
                new_html, ok = inject_link_html(html, e["anchor_text"], e["target_url"])
                if ok:
                    html = new_html
                    done_ids.append(e["id"])
                else:
                    supabase.table("internal_link_edits").update(
                        {"status": "failed", "result": {"reason": "anchor_not_found"}, "updated_at": "now()"}
                    ).eq("id", e["id"]).execute()
                    failed += 1
            if not done_ids:
                continue
            res = await wordpress_publish.update_post_content(client, post_id, html, resource=resource)
            for eid in done_ids:
                supabase.table("internal_link_edits").update(
                    {"status": "applied", "result": res, "updated_at": "now()"}
                ).eq("id", eid).execute()
            applied += len(done_ids)
            if engagement_id := group[0].get("engagement_id"):
                try:
                    from services import engagement_executor
                    engagement_executor.record_event(
                        engagement_id, "internal_links_applied",
                        detail={"post_id": post_id, "count": len(done_ids), "edit_link": res.get("edit_link")},
                    )
                except Exception:  # noqa: BLE001 — audit trail is best-effort
                    pass
        except Exception as exc:  # noqa: BLE001 — one bad post mustn't abort the batch
            logger.warning("internal_linking.apply_failed",
                           extra={"client_id": client_id, "post_id": post_id, "error": str(exc)})
            for e in group:
                supabase.table("internal_link_edits").update(
                    {"status": "failed", "result": {"reason": str(exc)[:200]}, "updated_at": "now()"}
                ).eq("id", e["id"]).execute()
                failed += 1
    logger.info("internal_link_apply_complete",
                extra={"client_id": client_id, "applied": applied, "failed": failed})
    return {"status": "applied", "applied": applied, "failed": failed}


# ── async_jobs plumbing ──────────────────────────────────────────────────────
def enqueue_analyze(client_id: str, engagement_id: Optional[str] = None) -> None:
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "internal_link_analyze").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "internal_link_analyze", "entity_id": client_id,
         "payload": {"client_id": client_id, "engagement_id": engagement_id}}
    ).execute()


def enqueue_apply(client_id: str, batch_id: Optional[str] = None) -> None:
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "internal_link_apply").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "internal_link_apply", "entity_id": client_id,
         "payload": {"client_id": client_id, "batch_id": batch_id}}
    ).execute()


async def _finish(job_id: str, *, status: str, **fields) -> None:
    get_supabase().table("async_jobs").update(
        {"status": status, "completed_at": "now()", **fields}
    ).eq("id", job_id).execute()


async def run_internal_link_analyze_job(job: dict) -> None:
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    if not client_id:
        await _finish(job["id"], status="failed", error="missing client_id")
        return
    try:
        result = await run_analysis(client_id, payload.get("engagement_id"))
    except Exception as exc:
        logger.warning("internal_link_analyze_job_failed", extra={"client_id": client_id, "error": str(exc)})
        await _finish(job["id"], status="failed", error=str(exc)[:500])
        return
    await _finish(job["id"], status="complete", result=result)


async def run_internal_link_apply_job(job: dict) -> None:
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    if not client_id:
        await _finish(job["id"], status="failed", error="missing client_id")
        return
    try:
        result = await apply_approved_edits(client_id, payload.get("batch_id"))
    except Exception as exc:
        logger.warning("internal_link_apply_job_failed", extra={"client_id": client_id, "error": str(exc)})
        await _finish(job["id"], status="failed", error=str(exc)[:500])
        return
    await _finish(job["id"], status="complete", result=result)
