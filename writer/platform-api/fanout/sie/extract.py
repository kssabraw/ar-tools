"""SIE Modules 5–6: Zone extraction + 5-layer noise filtering (PRD #3).

Module 5 (zone extraction) needs BeautifulSoup; it's lazy-imported inside
`extract_zones` so the **pure** noise layers (3 cross-page fingerprint, 4 heuristic
filters, 5 frequency anomaly) import and unit-test in the sandbox without bs4/lxml.

Layer order (PRD §Module 6): 1 structural strip + 2 text-density run *during*
extraction; 3 + 4 run over the extracted blocks before n-grams; 5 runs *after*
n-grams at the term level. Layer-4-excluded contact/address text is preserved on
`ZonePage.entity_text` for Module 11 (entities) even though it's dropped from
n-grams.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import mean, pstdev

# ----- Module 5 data structures ---------------------------------------------


@dataclass
class Zones:
    title: str = ""
    meta_description: str = ""
    h1: list[str] = field(default_factory=list)
    h2: list[str] = field(default_factory=list)
    h3: list[str] = field(default_factory=list)
    h4: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    lists: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    faq_blocks: list[str] = field(default_factory=list)


@dataclass
class ZonePage:
    url: str
    domain: str
    zones: Zones
    word_count: int
    rank: int | None = None
    # Layer-4-excluded blocks (contact info / addresses) kept for entity extraction.
    entity_text: list[str] = field(default_factory=list)


# ----- Layer 1/2 constants ---------------------------------------------------

_STRIP_TAGS = ("script", "style", "nav", "footer", "header", "aside", "noscript")
_BOILERPLATE_HINTS = (
    "sidebar", "widget", "menu", "nav", "footer", "breadcrumb", "cookie", "banner",
    "social-share", "related-posts", "author-bio", "comments", "newsletter",
    "signup", "cta",
)
_ARIA_STRIP_ROLES = ("navigation", "banner", "contentinfo", "complementary")
_MIN_PARAGRAPH_WORDS = 5          # Module 5 / Layer 4: drop paragraphs under 5 words
_LINK_RATIO_NAV = 0.3             # Layer 2: link_ratio > 0.3 => navigation


def _words(text: str) -> list[str]:
    return text.split()


def domain_of(url: str) -> str:
    from urllib.parse import urlparse

    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


# ----- Module 5: Zone extraction (Layers 1–2 applied during parse) ----------


def extract_zones(html: str, url: str, rank: int | None = None) -> ZonePage:
    """Parse a scraped page into zones, stripping chrome (Layer 1) and
    navigation-y blocks (Layer 2 link-density). bs4 is lazy-imported."""
    from bs4 import BeautifulSoup  # lazy: keeps the pure layers import-clean

    soup = BeautifulSoup(html or "", "lxml")

    # Layer 1: structural strip — by tag, by class/id hint, by ARIA role.
    for tag in soup(list(_STRIP_TAGS)):
        tag.decompose()
    # Collect first, then decompose: decomposing a parent mid-iteration clears its
    # descendants' attrs (to None), so a later `el.get(...)` on an already-decomposed
    # child raises "'NoneType' object has no attribute 'get'". Two passes avoid that.
    to_strip = []
    for el in soup.find_all(True):
        classes = el.get("class") or []
        if isinstance(classes, str):
            classes = [classes]
        ident = " ".join(
            filter(None, [" ".join(classes), el.get("id") or ""])
        ).lower()
        role = (el.get("role") or "").lower()
        if role in _ARIA_STRIP_ROLES or any(h in ident for h in _BOILERPLATE_HINTS):
            to_strip.append(el)
    for el in to_strip:
        if not getattr(el, "decomposed", False):
            el.decompose()

    z = Zones()
    if soup.title and soup.title.string:
        z.title = _norm_ws(soup.title.string)
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        z.meta_description = _norm_ws(meta["content"])
    for level in ("h1", "h2", "h3", "h4"):
        getattr(z, level).extend(
            t for t in (_norm_ws(h.get_text(" ")) for h in soup.find_all(level)) if t
        )

    for p in soup.find_all("p"):
        text = _norm_ws(p.get_text(" "))
        if len(_words(text)) < _MIN_PARAGRAPH_WORDS:
            continue
        if _link_ratio(p) > _LINK_RATIO_NAV:  # Layer 2
            continue
        z.paragraphs.append(text)
    for li in soup.find_all("li"):
        text = _norm_ws(li.get_text(" "))
        if text and _link_ratio(li) <= _LINK_RATIO_NAV:
            z.lists.append(text)
    for table in soup.find_all("table"):
        text = _norm_ws(table.get_text(" "))
        if text:
            z.tables.append(text)
    # FAQ blocks: <details>/<summary> or schema.org FAQ-ish containers.
    for d in soup.find_all("details"):
        text = _norm_ws(d.get_text(" "))
        if text:
            z.faq_blocks.append(text)

    body_text = " ".join(
        [*z.h1, *z.h2, *z.h3, *z.h4, *z.paragraphs, *z.lists, *z.tables]
    )
    return ZonePage(
        url=url, domain=domain_of(url), zones=z, word_count=len(_words(body_text)),
        rank=rank,
    )


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _link_ratio(el) -> float:
    """Layer 2: link word count / total word count for a block element."""
    total = len(_words(el.get_text(" ")))
    if total == 0:
        return 0.0
    link_words = sum(len(_words(a.get_text(" "))) for a in el.find_all("a"))
    return link_words / total


# ----- Layer 3: Cross-page fingerprinting (PURE) ----------------------------

_PUNCT_RE = re.compile(r"[^\w\s]")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def normalize_block(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace (Layer 3 key)."""
    return _norm_ws(_PUNCT_RE.sub(" ", (text or "").lower()))


def cross_page_fingerprint(pages: list[ZonePage], min_domains: int = 3) -> set[str]:
    """Normalized blocks (paragraph- AND sentence-level) appearing on `min_domains`+
    distinct domains = cross-page boilerplate to exclude from n-grams."""
    domains_by_block: dict[str, set[str]] = {}

    def _record(text: str, domain: str) -> None:
        norm = normalize_block(text)
        if norm:
            domains_by_block.setdefault(norm, set()).add(domain)

    for page in pages:
        blocks = [*page.zones.paragraphs, *page.zones.lists]
        for block in blocks:
            _record(block, page.domain)                      # paragraph-level
            sentences = _SENT_SPLIT_RE.split(block)
            if len(sentences) > 1:
                for sent in sentences:                       # sentence-level
                    _record(sent, page.domain)
    return {b for b, doms in domains_by_block.items() if len(doms) >= min_domains}


# ----- Layer 4: Heuristic text filters (PURE) -------------------------------

_PHONE_RE = re.compile(r"[\(\+]?\d[\d\-\.\s\(\)]{6,}\d")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+\w+(\s+\w+)*\s+(st|street|ave|avenue|blvd|rd|road|dr|drive|"
    r"ln|lane|way|ct|court|suite|ste)\b", re.IGNORECASE,
)
_CTA_RE = re.compile(
    r"\b(call\s+(now|us|today)|get\s+a\s+free|schedule\s+your|request\s+a\s+quote|"
    r"contact\s+us\s+today|book\s+now|sign\s+up)\b", re.IGNORECASE,
)
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]+\b")


def is_contact_or_address(text: str) -> bool:
    """Phone/email/address block — exclude from n-grams, KEEP for entities."""
    stripped = _norm_ws(text)
    if not stripped:
        return False
    if _PHONE_RE.fullmatch(stripped) or _EMAIL_RE.fullmatch(stripped):
        return True
    return bool(_ADDRESS_RE.search(stripped)) and len(_words(stripped)) <= 12


def is_cta(text: str) -> bool:
    return bool(_CTA_RE.search(text or ""))


def is_service_area_list(text: str) -> bool:
    """>50% of words are proper nouns / city names => likely a service-area list."""
    words = _words(text or "")
    if len(words) < 3:
        return False
    proper = sum(1 for w in words if _PROPER_NOUN_RE.fullmatch(w))
    return proper / len(words) > 0.5


def heuristic_keep(text: str) -> tuple[bool, str | None]:
    """Layer 4. Returns (keep_for_ngram, exclusion_reason). Contact/address text is
    NOT kept for n-grams but the caller should preserve it for entity extraction."""
    stripped = _norm_ws(text)
    if len(_words(stripped)) < _MIN_PARAGRAPH_WORDS:
        return False, "under_5_words"
    if is_contact_or_address(stripped):
        return False, "contact_or_address"
    if is_cta(stripped):
        return False, "cta_pattern"
    if is_service_area_list(stripped):
        return False, "service_area_list"
    return True, None


# ----- Layer 5: Post-n-gram frequency anomaly (PURE) ------------------------


def frequency_anomaly_terms(
    per_page_freq: dict[str, list[int]], *, min_pages: int = 4, cv_threshold: float = 0.1
) -> set[str]:
    """Flag terms whose per-page frequency coefficient of variation (stdev/mean) is
    below `cv_threshold` on `min_pages`+ pages — template boilerplate, not organic
    usage (PRD Layer 5). `per_page_freq[term]` = counts across the pages it appears
    on."""
    flagged: set[str] = set()
    for term, counts in per_page_freq.items():
        present = [c for c in counts if c > 0]
        if len(present) < min_pages:
            continue
        m = mean(present)
        if m == 0:
            continue
        cv = pstdev(present) / m
        if cv < cv_threshold:
            flagged.add(term)
    return flagged
