"""AI Visibility (Brand Strength) — per-answer response analysis.

Beyond the binary found/not-found bit, each engine's answer carries a lot more
signal. These pure helpers mine it from data we already have (the classifier's
structured extraction + the cited URLs + the DataForSEO AI Overview structure):

  * source classification — what kinds of domains the AI treats as ground truth
    for this query (directory / review / social / forum / search / editorial),
    whether the client's own site was cited, and which sources cite competitors
    but not the client (a listings/PR target list);
  * AI Overview mention kind — for Google AIO/AI Mode, whether the client appears
    as an in-content link (inline in the generated answer) vs only in the sources
    strip (citation), which carry very different weight;
  * discovered competitors — businesses the answer named that aren't tracked yet;
  * brand-fact accuracy — facts the AI stated about the brand that disagree with
    the client's GBP (wrong phone, "permanently closed", …);
  * cross-engine consensus — which businesses recur across engines.

All functions are pure (no DB, no network) so they're unit-testable; the scan
engine calls build_response_analysis() per brand cell and the service computes
consensus_rollup() per batch on read.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlparse

# ── source-domain taxonomy ────────────────────────────────────────────────────
# Curated root domains by kind. Anything unmatched is treated as "editorial"
# (a brand/news/blog page), which is itself a useful signal.
_DIRECTORY_DOMAINS = {
    "yelp.com", "yellowpages.com", "angi.com", "angieslist.com", "thumbtack.com",
    "houzz.com", "bbb.org", "mapquest.com", "foursquare.com", "manta.com",
    "hotfrog.com", "bark.com", "checkatrade.com", "trustedpros.com", "porch.com",
    "homeadvisor.com", "expertise.com", "threebestrated.com", "yellowbook.com",
    "superpages.com", "local.com", "chamberofcommerce.com", "cylex.com",
    "brownbook.net", "truelocal.com.au", "yellowpages.com.au", "hipages.com.au",
    "oneflare.com.au", "localsearch.com.au", "wordofmouth.com.au",
}
_REVIEW_DOMAINS = {
    "trustpilot.com", "tripadvisor.com", "consumeraffairs.com", "sitejabber.com",
    "productreview.com.au", "reviews.io", "birdeye.com",
}
_SOCIAL_DOMAINS = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "tiktok.com", "youtube.com", "pinterest.com", "nextdoor.com",
}
_FORUM_DOMAINS = {"reddit.com", "quora.com", "stackexchange.com"}
_SEARCH_DOMAINS = {"google.com", "bing.com", "maps.google.com", "g.page"}


def extract_host(url_or_domain: Optional[str]) -> str:
    """Bare lowercased host from a URL or domain string (drops scheme + www)."""
    if not url_or_domain:
        return ""
    s = url_or_domain.strip().lower()
    if "//" in s or s.startswith("http"):
        s = urlparse(s if "//" in s else "http://" + s).netloc
    elif "/" in s:
        s = s.split("/", 1)[0]
    if s.startswith("www."):
        s = s[4:]
    return s


def _root(host: str) -> str:
    """Collapse a host to its registrable-ish root (last two labels), so
    sub.yelp.com and yelp.com classify the same. Good enough for our taxonomy."""
    host = extract_host(host)
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    # Handle common two-label public suffixes (co.uk, com.au, …).
    if parts[-2] in {"com", "co", "org", "net", "gov", "edu"} and parts[-1] in {"au", "uk", "nz", "za"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def domains_match(a: Optional[str], b: Optional[str]) -> bool:
    """True if two URLs/domains share a registrable root (subdomain-tolerant)."""
    ra, rb = _root(a or ""), _root(b or "")
    return bool(ra) and ra == rb


def classify_source_type(domain: str) -> str:
    """One of: directory, review, social, forum, search, editorial."""
    root = _root(domain)
    if root in _DIRECTORY_DOMAINS:
        return "directory"
    if root in _REVIEW_DOMAINS:
        return "review"
    if root in _SOCIAL_DOMAINS:
        return "social"
    if root in _FORUM_DOMAINS:
        return "forum"
    if root in _SEARCH_DOMAINS:
        return "search"
    return "editorial"


def analyze_sources(
    citations: Iterable[str],
    client_domain: Optional[str],
    competitor_domains: Optional[Iterable[str]] = None,
) -> dict:
    """Classify the cited sources for one answer.

    Returns {client_cited, domains: [{domain, type, is_client, is_competitor}],
    by_type: {type: count}, competitor_only_sources: [domain, ...]}. The last is
    the actionable list — sources the AI trusts that mention a competitor's
    domain but not the client's (places to get listed / earn a mention)."""
    comp_domains = [d for d in (competitor_domains or []) if d]
    seen: dict[str, dict] = {}
    for raw in citations or []:
        host = extract_host(raw)
        if not host:
            continue
        root = _root(host)
        if root in seen:
            continue
        is_client = domains_match(host, client_domain) if client_domain else False
        is_competitor = any(domains_match(host, c) for c in comp_domains)
        seen[root] = {
            "domain": root,
            "type": classify_source_type(host),
            "is_client": is_client,
            "is_competitor": is_competitor,
        }
    domains = list(seen.values())
    by_type: dict[str, int] = {}
    for d in domains:
        by_type[d["type"]] = by_type.get(d["type"], 0) + 1
    client_cited = any(d["is_client"] for d in domains)
    competitor_only = (
        [d["domain"] for d in domains if d["is_competitor"]] if (comp_domains and not client_cited) else []
    )
    return {
        "client_cited": client_cited,
        "domains": domains,
        "by_type": by_type,
        "competitor_only_sources": competitor_only,
    }


def aio_mention_kind(
    client_domain: Optional[str],
    inline_domains: Optional[Iterable[str]],
    reference_domains: Optional[Iterable[str]],
) -> str:
    """For a Google AI Overview / AI Mode answer, classify how the client appears:
      'in_content_link' — linked inline within the generated answer text
      'citation_only'   — only in the sources/citations strip
      'both'            — inline AND in the sources strip
      'none'            — not present at all
    An inline content link is the stronger signal (the AI is citing the client
    *as* the answer, not just listing them among references)."""
    if not client_domain:
        return "none"
    in_inline = any(domains_match(client_domain, d) for d in (inline_domains or []))
    in_ref = any(domains_match(client_domain, d) for d in (reference_domains or []))
    if in_inline and in_ref:
        return "both"
    if in_inline:
        return "in_content_link"
    if in_ref:
        return "citation_only"
    return "none"


# ── businesses named in the answer ────────────────────────────────────────────

def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _name_matches(a: str, b: str) -> bool:
    """Loose business-name match: equal, or one contained in the other once
    normalized (handles "Acme Plumbing" vs "Acme Plumbing Co")."""
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def derive_discovered_competitors(
    businesses: Iterable[dict],
    brand: str,
    tracked_names: Iterable[str],
) -> list[dict]:
    """From the answer's full business list, keep the ones that are neither the
    client's brand nor an already-tracked competitor. Returns the (deduped)
    business dicts ({name, attributes}) so the caller can both suggest them as
    new tracked competitors AND show why the AI surfaced them."""
    tracked = [t for t in tracked_names or [] if t]
    out: list[dict] = []
    seen: set[str] = set()
    for b in businesses or []:
        name = (b.get("name") or "").strip() if isinstance(b, dict) else str(b).strip()
        if not name:
            continue
        key = _norm_name(name)
        if not key or key in seen:
            continue
        if _name_matches(name, brand):
            continue
        if any(_name_matches(name, t) for t in tracked):
            continue
        seen.add(key)
        attrs = b.get("attributes") if isinstance(b, dict) else None
        out.append({"name": name, "attributes": [a for a in (attrs or []) if a][:6]})
    return out


def competitor_attributes(businesses: Iterable[dict], brand: str) -> list[dict]:
    """The reasons/attributes the answer attached to each non-client business —
    the positioning themes that win for this query."""
    out: list[dict] = []
    seen: set[str] = set()
    for b in businesses or []:
        if not isinstance(b, dict):
            continue
        name = (b.get("name") or "").strip()
        attrs = [a for a in (b.get("attributes") or []) if a]
        if not name or not attrs or _name_matches(name, brand):
            continue
        key = _norm_name(name)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "attributes": attrs[:6]})
    return out


# ── brand-fact accuracy (vs GBP) ──────────────────────────────────────────────

def _digits(s: Optional[str]) -> str:
    return re.sub(r"\D", "", s or "")


def diff_brand_facts(stated: Optional[dict], gbp: Optional[dict]) -> list[dict]:
    """Flag facts the AI asserted about the brand that disagree with the client's
    GBP. Conservative — only emits a flag when both sides have a comparable value
    and they clearly differ, to avoid false alarms. Each flag is
    {field, stated, actual}."""
    if not stated or not gbp:
        return []
    flags: list[dict] = []

    stated_phone = _digits(stated.get("phone"))
    gbp_phone = _digits(gbp.get("phone"))
    if stated_phone and gbp_phone and len(stated_phone) >= 7 and len(gbp_phone) >= 7:
        # Compare the last 7 digits to sidestep country/area-code formatting.
        if stated_phone[-7:] != gbp_phone[-7:]:
            flags.append({"field": "phone", "stated": stated.get("phone"), "actual": gbp.get("phone")})

    if stated.get("permanently_closed") is True:
        # GBP existing with a rating/reviews implies an operating listing.
        if gbp.get("gbp_rating") is not None or gbp.get("gbp_review_count"):
            flags.append({
                "field": "status",
                "stated": "permanently closed",
                "actual": "active Google Business Profile on file",
            })

    return flags


# ── per-cell assembly ─────────────────────────────────────────────────────────

def build_response_analysis(
    *,
    rich: Optional[dict],
    citations: Iterable[str],
    client_domain: Optional[str],
    competitor_domains: Optional[Iterable[str]],
    tracked_competitor_names: Optional[Iterable[str]],
    brand: str,
    gbp: Optional[dict] = None,
    aio_inline_domains: Optional[Iterable[str]] = None,
    aio_reference_domains: Optional[Iterable[str]] = None,
    is_aio: bool = False,
) -> dict:
    """Assemble the response_analysis blob for one brand cell from the rich
    classifier output + parsed citations + (for AIO) the inline/reference split.
    `rich` is the extended classifier dict (may be None when the regex fallback
    ran — the blob just carries fewer fields then)."""
    rich = rich or {}
    businesses = rich.get("businesses") or []

    analysis: dict = {
        "position": {
            "rank": rich.get("mention_rank") or None,
            "total_businesses": rich.get("total_businesses") or (len(businesses) or None),
        },
        "prominence": rich.get("prominence") or None,
        "sources": analyze_sources(citations, client_domain, competitor_domains),
        "discovered_competitors": derive_discovered_competitors(
            businesses, brand, tracked_competitor_names or []
        ),
        "competitor_attributes": competitor_attributes(businesses, brand),
        "accuracy_flags": diff_brand_facts(rich.get("stated_brand_facts"), gbp),
        "intent": {
            "inferred": rich.get("inferred_intent") or None,
            "locations": [l for l in (rich.get("mentioned_locations") or []) if l][:12],
        },
    }
    if is_aio:
        analysis["aio"] = {
            "mention_kind": aio_mention_kind(client_domain, aio_inline_domains, aio_reference_domains),
        }
    return analysis


# ── cross-engine consensus (per batch, on read) ───────────────────────────────

def consensus_rollup(rows: Iterable[dict], brand: str) -> dict:
    """Across one scan batch's brand rows, roll up which businesses the engines
    agree on. Each row carries response_analysis.competitor_attributes /
    discovered_competitors (the businesses it named) + its engine. Returns
    {businesses: [{name, engines, count, attributes}], engines_total}."""
    by_name: dict[str, dict] = {}
    engines: set[str] = set()
    for r in rows or []:
        if r.get("status") != "completed":
            continue
        engine = r.get("engine")
        if engine:
            engines.add(engine)
        ra = r.get("response_analysis") or {}
        named = list(ra.get("competitor_attributes") or []) + list(ra.get("discovered_competitors") or [])
        local_seen: set[str] = set()
        for b in named:
            name = (b.get("name") or "").strip() if isinstance(b, dict) else str(b).strip()
            key = _norm_name(name)
            if not key or key in local_seen:
                continue
            local_seen.add(key)
            entry = by_name.setdefault(key, {"name": name, "engines": set(), "attributes": []})
            if engine:
                entry["engines"].add(engine)
            for a in (b.get("attributes") or []) if isinstance(b, dict) else []:
                if a and a not in entry["attributes"]:
                    entry["attributes"].append(a)
    businesses = [
        {
            "name": v["name"],
            "engines": sorted(v["engines"]),
            "count": len(v["engines"]),
            "attributes": v["attributes"][:6],
        }
        for v in by_name.values()
    ]
    businesses.sort(key=lambda b: (-b["count"], b["name"].lower()))
    return {"businesses": businesses, "engines_total": len(engines)}
