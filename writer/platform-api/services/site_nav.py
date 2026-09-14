"""Service-label extraction from a site's navigation menu.

A local-business site almost always lists its services in the header/nav menu —
and, crucially, those nav links are written **city-agnostically** ("Roof
Restoration", "Gutter Cleaning") rather than as the "<service> <city>" landing
slugs the URL-based `coverage_audit.derive_site_services` reads. So the nav is
the cleaner primary signal for the Coverage Audit's *service* axis: it names the
services a business offers without the place noise the planner then has to strip.

This module is PURE (no I/O): it parses homepage HTML the caller already fetched
and returns candidate service labels. The caller (`coverage_audit_service`) does
the best-effort fetch and feeds the labels into the service-axis planner. Every
step is defensive — malformed HTML, a JS-only nav, or a menu of pure utility
links all degrade to an empty list, never an error.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from services.site_page_index import content_tokens

# Nav labels that are never a service — site chrome, contact/utility items, the
# bare "Services" dropdown parent, e-commerce/account links, and location hubs.
# Matched against a NORMALIZED label (lower-cased, whitespace-collapsed, outer
# punctuation stripped).
_UTILITY_LABELS = frozenset({
    "home", "homepage", "welcome",
    "about", "about us", "about me", "who we are", "our story", "our company",
    "contact", "contact us", "contact me", "get in touch",
    "blog", "blogs", "news", "articles", "insights", "resources",
    "gallery", "photo gallery", "photos", "portfolio", "projects", "our work",
    "reviews", "testimonials", "review",
    "faq", "faqs", "q&a",
    "careers", "career", "jobs", "join us",
    "team", "our team", "meet the team", "staff", "the team",
    "pricing", "prices", "price list",
    "services", "service", "our services", "what we do", "all services",
    "quote", "get a quote", "request a quote", "free quote", "get quote",
    "book", "book now", "book online", "schedule", "booking",
    "login", "log in", "sign in", "signin", "my account", "account",
    "cart", "checkout", "shop", "store", "products", "product",
    "locations", "location", "our locations", "service area", "service areas",
    "areas we serve", "areas served", "coverage area", "coverage areas", "areas",
    "privacy", "privacy policy", "terms", "terms of service",
    "terms and conditions", "sitemap", "more", "menu", "search",
    "gallery & reviews", "specials", "offers", "financing",
})

# Phrases that, wherever they appear in a label, mark it as chrome/CTA rather
# than a service (catches decorated variants the exact set misses).
_UTILITY_SUBSTRINGS = (
    "get a quote", "request a quote", "free quote", "book now", "book online",
    "contact us", "about us", "areas we serve", "service area", "our service",
    "meet the", "call now", "call us", "get started", "learn more", "read more",
    "view all",
)

_MAX_LABEL_WORDS = 6
_LABEL_CAP = 25
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Lower-case, collapse whitespace, strip surrounding punctuation/emoji."""
    t = _WS_RE.sub(" ", (text or "").replace("\xa0", " ")).strip()
    return t.strip("|/-–—•·:>»«←→ \t").strip().lower()


def _base_domain(url: str) -> str:
    """The bare registrable-ish host of a URL, lower-cased, ``www.`` dropped.
    Empty when the URL has no host."""
    host = (urlsplit(url if "//" in (url or "") else f"//{url}").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_internal(href: str, base_domain: str) -> bool:
    """Whether an anchor href is an internal, real-page link.

    Drops empty/fragment/``mailto:``/``tel:``/``javascript:`` hrefs and the bare
    homepage; keeps relative links and (when a ``base_domain`` is known) absolute
    links to the same host or a subdomain of it. With no ``base_domain`` known,
    keeps relative links only (absolute links can't be verified as internal)."""
    h = (href or "").strip()
    if not h or h.startswith(("#", "mailto:", "tel:", "javascript:", "sms:")):
        return False
    parts = urlsplit(h)
    if not parts.netloc:  # relative link
        path = parts.path.strip("/")
        return bool(path)  # drop bare "/" (home)
    host = parts.netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    if not base_domain:
        return False
    return host == base_domain or host.endswith("." + base_domain)


def _nav_anchors(soup: BeautifulSoup) -> list:
    """Anchor tags from the site's navigation regions.

    Prefers real nav containers — ``<nav>``, ``role="navigation"``, and elements
    whose id/class names a menu/nav — and falls back to ``<header>`` only when
    those found no anchors, so a header logo/phone strip doesn't crowd out a real
    menu. Deduped by identity across overlapping containers."""
    containers = list(soup.find_all("nav"))
    containers += soup.find_all(attrs={"role": "navigation"})

    def _named_menu(tag) -> bool:
        ident = " ".join(
            [str(tag.get("id") or "")] + list(tag.get("class") or [])
        ).lower()
        return ("menu" in ident or "nav" in ident) and tag.name in (
            "ul", "div", "header", "section",
        )

    containers += soup.find_all(_named_menu)

    anchors: list = []
    seen: set[int] = set()
    for c in containers:
        for a in c.find_all("a"):
            if id(a) not in seen:
                seen.add(id(a))
                anchors.append(a)
    if not anchors:  # fall back to the header only if nothing else matched
        for header in soup.find_all("header"):
            for a in header.find_all("a"):
                if id(a) not in seen:
                    seen.add(id(a))
                    anchors.append(a)
    return anchors


def extract_nav_links(html: str, base_domain: str = "") -> list[tuple[str, str]]:
    """``(label, href)`` pairs from the site's nav menu — internal links with
    visible text only. Pure; tolerant of malformed HTML (returns [] on any parse
    failure)."""
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001 — never let a parse blow up the audit
        return []
    out: list[tuple[str, str]] = []
    for a in _nav_anchors(soup):
        href = a.get("href") or ""
        if not _is_internal(href, base_domain):
            continue
        label = _WS_RE.sub(" ", a.get_text(" ", strip=True)).strip()
        if label:
            out.append((label, href))
    return out


def _is_service_label(normalized: str, place_tokens: frozenset[str]) -> bool:
    """Whether a normalized nav label looks like a real service (not chrome, not a
    pure place name, not a phone/email/CTA)."""
    if not normalized or len(normalized) < 2:
        return False
    if normalized in _UTILITY_LABELS:
        return False
    if any(sub in normalized for sub in _UTILITY_SUBSTRINGS):
        return False
    if "@" in normalized or re.search(r"\d{3}", normalized):
        return False  # email / phone-shaped (a service label rarely has a 3-digit run)
    if len(normalized.split()) > _MAX_LABEL_WORDS:
        return False
    toks = content_tokens(normalized)
    if not toks:  # nothing distinguishing survived (generics/punctuation only)
        return False
    if place_tokens and toks <= place_tokens:
        return False  # a pure location nav item ("Melbourne", "Inner West")
    return True


def nav_service_labels(
    html: str,
    base_domain: str = "",
    *,
    place_tokens: frozenset[str] = frozenset(),
    cap: int = _LABEL_CAP,
) -> list[str]:
    """Candidate service labels from a site's nav menu, in menu order.

    Filters the nav links to real service items — drops site chrome (home/about/
    contact/blog/…), the bare "Services" parent, e-commerce/account links, and
    pure location hubs (via ``place_tokens``) — then de-dupes case-insensitively
    (first-seen wins), preserving the original casing of the label, and caps the
    list. Pure — the caller fetches the HTML. Best-effort: an empty/JS-only nav
    yields ``[]``."""
    labels: list[str] = []
    seen: set[str] = set()
    place_low = frozenset(t.lower() for t in place_tokens)
    for label, _href in extract_nav_links(html, base_domain):
        norm = _normalize(label)
        if not _is_service_label(norm, place_low):
            continue
        if norm in seen:
            continue
        seen.add(norm)
        labels.append(label.strip())
        if len(labels) >= cap:
            break
    return labels
