"""Local Relevance Scorecard (Maps strategy PRD, Tier B / B6).

For a tracked keyword (the service) + the client's location, score — for the
client AND each top local-pack competitor — how well each ranking signal lines
up with what's actually being tracked:

  * reviews mention the service / the location
  * the GBP links to a page that's about the service / location
  * the GBP category is the service (or closely related)
  * site Domain Rating (DR) + the GBP-linked page's URL Rating (UR)

All matching is DETERMINISTIC (token + small synonym map) — no LLM. Pure helpers
are unit-tested; the orchestration reuses ScrapeOwl (page fetch) + the SERP
snapshot's DataForSEO Backlinks summary (DR + page UR).
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from config import settings
from db.supabase_client import get_supabase
from services import competitor_gbp, gbp_service, serp_snapshot
from services.website_scraper import scrapeowl_fetch

logger = logging.getLogger(__name__)

# Tokens too generic to carry service/location meaning.
_STOPWORDS = {
    "the", "and", "of", "for", "in", "near", "me", "best", "top", "a", "to", "your",
    "local", "service", "services", "company", "co", "inc", "llc", "ltd", "pty",
}

# Synonym groups — members are treated as equivalent for matching (service ↔
# category, etc.). Deterministic and easily extended.
_SYNONYM_GROUPS = [
    {"plumber", "plumbers", "plumbing"},
    {"roofer", "roofers", "roofing", "roof"},
    {"electrician", "electricians", "electrical"},
    {"hvac", "heating", "cooling", "air", "conditioning"},
    {"dentist", "dentists", "dental"},
    {"lawyer", "lawyers", "attorney", "attorneys", "legal", "law"},
    {"landscaper", "landscapers", "landscaping", "lawn"},
    {"cleaner", "cleaners", "cleaning"},
    {"painter", "painters", "painting"},
    {"locksmith", "locksmiths"},
    {"mechanic", "mechanics", "automotive", "auto"},
    {"pest", "exterminator", "exterminators"},
    {"builder", "builders", "construction", "remodeling", "remodel", "renovation"},
    {"mover", "movers", "moving", "removalist", "removalists"},
    {"chiropractor", "chiropractors", "chiropractic"},
]


def _canon_map() -> dict[str, str]:
    m: dict[str, str] = {}
    for group in _SYNONYM_GROUPS:
        rep = sorted(group)[0]
        for t in group:
            m[t] = rep
    return m


_CANON = _canon_map()


def tokenize(text: "str | None") -> list[str]:
    if not text:
        return []
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 2]


def _canonicalize(tokens) -> set[str]:
    """Map tokens to their synonym-group representative (or themselves)."""
    return {_CANON.get(t, t) for t in tokens}


def location_terms(location: "str | None") -> set[str]:
    """Meaningful location tokens (drop stopwords, pure numbers, 2-letter codes
    are kept as they may be a suburb abbrev — but bare numbers/postcodes drop)."""
    return {t for t in tokenize(location) if t not in _STOPWORDS and not t.isdigit()}


def service_terms(keyword: "str | None", loc_terms: "set[str] | None" = None) -> set[str]:
    """Service tokens from the tracked keyword: drop stopwords + any location
    tokens, then canonicalize via the synonym map. Pure."""
    loc = loc_terms or set()
    toks = {t for t in tokenize(keyword) if t not in _STOPWORDS and not t.isdigit() and t not in loc}
    return _canonicalize(toks)


def mentions(text: "str | None", terms: set[str]) -> bool:
    """True if any term (synonym-canonicalized, whole-word) appears in text. Pure."""
    if not text or not terms:
        return False
    toks = _canonicalize(tokenize(text))
    return bool(toks & terms)


def count_mentioning(texts: list[str], terms: set[str]) -> int:
    return sum(1 for t in texts if mentions(t, terms))


def reviews_mention_stats(review_texts: list[str], svc: set[str], loc: set[str]) -> dict:
    """How many of the reviews mention the service / the location. Pure."""
    total = len(review_texts)
    svc_n = count_mentioning(review_texts, svc)
    loc_n = count_mentioning(review_texts, loc)
    return {
        "reviews_total": total,
        "reviews_service_mentions": svc_n,
        "reviews_location_mentions": loc_n,
    }


def category_match(category: "str | None", svc: set[str]) -> str:
    """'exact' (the category IS the service), 'related' (overlaps/synonym), or
    'none'. Pure."""
    if not category or not svc:
        return "none"
    cat = _canonicalize(t for t in tokenize(category) if t not in _STOPWORDS)
    if not cat:
        return "none"
    overlap = cat & svc
    if not overlap:
        return "none"
    # Exact when every service token is represented in the category.
    return "exact" if svc <= cat else "related"


def page_relevance(text: "str | None", svc: set[str], loc: set[str]) -> dict:
    """Whether the page text is about the service / the location. Pure."""
    return {"service": mentions(text, svc), "location": mentions(text, loc)}


# --- impure helpers ---------------------------------------------------------
def extract_page_text(html: "str | None") -> str:
    """Title + headings + visible body text from a page's HTML (for term matching)."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    parts = []
    if soup.title and soup.title.string:
        parts.append(soup.title.string)
    parts.append(soup.get_text(" ", strip=True))
    return " ".join(parts)


def _domain(url: "str | None") -> str:
    if not url:
        return ""
    u = url.lower()
    if "//" in u:
        u = u.split("//", 1)[1]
    u = u.split("/", 1)[0].split("@")[-1].split(":")[0]
    return u[4:] if u.startswith("www.") else u


def derive_location(client: dict) -> str:
    """Best-effort client location string: the configured rank-tracking location,
    else the middle of the GBP address (drop street + country)."""
    loc = (client.get("rank_tracking_location") or "").strip()
    if loc:
        return loc
    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else {}
    address = (gbp or {}).get("address") or ""
    segs = [s.strip() for s in address.split(",") if s.strip()]
    if len(segs) >= 3:
        return " ".join(segs[1:-1])  # drop street (first) + country (last)
    return address


async def _score_entity(
    client_id: str, keyword: str, location: str, svc: set[str], loc: set[str],
    place_id: "str | None", name: "str | None", category: "str | None",
    website: "str | None", review_texts: list[str], is_client: bool,
    business_type: "str | None" = None,
) -> dict:
    domain = _domain(website)
    row = {
        "client_id": client_id,
        "keyword": keyword,
        "location": location,
        "place_id": place_id,
        "is_client": is_client,
        "name": name,
        "domain": domain or None,
        "gbp_url": website or None,
        "category": category,
        "category_match": category_match(category, svc),
        "business_type": business_type,
        "page_service_relevant": None,
        "page_location_relevant": None,
        "domain_rating": None,
        "page_ur": None,
        **reviews_mention_stats(review_texts, svc, loc),
    }
    # GBP-linked page relevance (best-effort scrape).
    if website:
        try:
            rel = page_relevance(extract_page_text(await scrapeowl_fetch(website)), svc, loc)
            row["page_service_relevant"] = rel["service"]
            row["page_location_relevant"] = rel["location"]
        except Exception as exc:
            logger.warning("local_relevance_scrape_failed", extra={"url": website, "error": str(exc)})
        # Page-level URL Rating.
        try:
            row["page_ur"] = (await serp_snapshot.fetch_backlinks_summary(website)).get("url_rating")
        except Exception as exc:
            logger.warning("local_relevance_ur_failed", extra={"url": website, "error": str(exc)})
    # Domain Rating.
    if domain:
        try:
            row["domain_rating"] = (await serp_snapshot.fetch_domain_summary(domain)).get("domain_rating")
        except Exception as exc:
            logger.warning("local_relevance_dr_failed", extra={"domain": domain, "error": str(exc)})
    return row


def _review_texts_by_place(client_id: str) -> dict[str, list[str]]:
    rows = (
        get_supabase().table("reviews").select("place_id, text")
        .eq("client_id", client_id).limit(5000).execute()
    ).data or []
    out: dict[str, list[str]] = {}
    for r in rows:
        if r.get("text"):
            out.setdefault(r.get("place_id"), []).append(r["text"])
    return out


async def analyze(client_id: str, keyword: str) -> dict:
    """Build + store the scorecard for `keyword` across the client + top competitors."""
    supabase = get_supabase()
    client_rows = supabase.table("clients").select(
        "name, website, website_url, gbp, gbp_place_id, rank_tracking_location"
    ).eq("id", client_id).limit(1).execute().data
    client = client_rows[0] if client_rows else {}
    location = derive_location(client)
    loc = location_terms(location)
    svc = service_terms(keyword, loc)
    reviews_by_place = _review_texts_by_place(client_id)

    rows: list[dict] = []
    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else {}
    client_place = client.get("gbp_place_id")
    rows.append(await _score_entity(
        client_id, keyword, location, svc, loc,
        client_place, client.get("name"), (gbp or {}).get("gbp_category"),
        (gbp or {}).get("website") or client.get("website") or client.get("website_url"),
        reviews_by_place.get(client_place, []), True,
        business_type=gbp_service.classify_business_type(gbp),
    ))

    for p in competitor_gbp.latest_profiles(client_id)[: settings.competitor_gbp_max]:
        rows.append(await _score_entity(
            client_id, keyword, location, svc, loc,
            p.get("place_id"), p.get("name"), p.get("primary_category"), p.get("website"),
            reviews_by_place.get(p.get("place_id"), []), False,
            business_type=p.get("business_type"),
        ))

    try:
        supabase.table("local_relevance_scores").insert(rows).execute()
    except Exception as exc:
        logger.error("local_relevance_store_failed", extra={"client_id": client_id, "error": str(exc)})
        raise
    return {"keyword": keyword, "location": location, "entities": len(rows)}


def latest_scorecard(client_id: str) -> dict:
    """Most recent capture for the most recent keyword: client row + competitors."""
    rows = (
        get_supabase().table("local_relevance_scores")
        .select("keyword, location, place_id, is_client, name, domain, gbp_url, category, "
                "category_match, business_type, reviews_total, reviews_service_mentions, "
                "reviews_location_mentions, page_service_relevant, page_location_relevant, "
                "domain_rating, page_ur, captured_at")
        .eq("client_id", client_id).order("captured_at", desc=True).limit(200).execute()
    ).data or []
    if not rows:
        return {"keyword": None, "location": None, "client": None, "competitors": []}
    latest_kw = rows[0]["keyword"]
    latest_at = rows[0]["captured_at"]
    batch = [r for r in rows if r["keyword"] == latest_kw and r["captured_at"] == latest_at]
    client = next((r for r in batch if r["is_client"]), None)
    competitors = [r for r in batch if not r["is_client"]]
    return {"keyword": latest_kw, "location": batch[0].get("location"), "client": client, "competitors": competitors}


def detect_relevance_gaps(scorecard: dict) -> "dict | None":
    """The client's own relevance weaknesses, weighted by whether competitors do
    better. Pure-ish (reads the assembled scorecard dict). Returns an Action-Plan
    signal or None."""
    client = scorecard.get("client")
    if not client:
        return None
    competitors = scorecard.get("competitors") or []
    gaps: list[str] = []

    if client.get("category_match") == "none":
        comp_ok = sum(1 for c in competitors if c.get("category_match") in ("exact", "related"))
        if comp_ok:
            gaps.append(f"your GBP category isn't the service ({comp_ok} competitors' are)")
    if client.get("page_service_relevant") is False:
        gaps.append("your GBP links to a page that isn't about the service")
    if (client.get("reviews_total") or 0) >= 3 and (client.get("reviews_service_mentions") or 0) == 0:
        gaps.append("none of your reviews mention the service")
    # DR / UR behind the competitor median.
    comp_dr = [c.get("domain_rating") for c in competitors if c.get("domain_rating") is not None]
    if client.get("domain_rating") is not None and comp_dr:
        median = sorted(comp_dr)[len(comp_dr) // 2]
        if median - client["domain_rating"] >= 10:
            gaps.append(f"site authority (DR {round(client['domain_rating'])}) trails competitors (~{round(median)})")
    comp_ur = [c.get("page_ur") for c in competitors if c.get("page_ur") is not None]
    if client.get("page_ur") is not None and comp_ur:
        median = sorted(comp_ur)[len(comp_ur) // 2]
        if median - client["page_ur"] >= 10:
            gaps.append(f"your linked page's authority (UR {round(client['page_ur'])}) trails competitors (~{round(median)})")

    if not gaps:
        return None
    return {"keyword": scorecard.get("keyword"), "gaps": gaps}


# --- job + enqueue ----------------------------------------------------------
def _resolve_keyword(supabase, client_id: str, keyword: "str | None") -> "str | None":
    if keyword:
        return keyword
    kw = supabase.table("maps_keywords").select("keyword").eq("client_id", client_id).eq("active", True).limit(1).execute().data
    return kw[0]["keyword"] if kw else None


def enqueue_local_relevance(client_id: str, keyword: "str | None" = None) -> bool:
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "local_relevance").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return False
    supabase.table("async_jobs").insert(
        {"job_type": "local_relevance", "entity_id": client_id, "payload": {"client_id": client_id, "keyword": keyword}}
    ).execute()
    return True


async def run_local_relevance_job(job: dict) -> None:
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        keyword = _resolve_keyword(supabase, client_id, payload.get("keyword"))
        result = {"skipped": "no_keyword"} if not keyword else await analyze(client_id, keyword)
    except Exception as exc:
        logger.warning("local_relevance_job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
