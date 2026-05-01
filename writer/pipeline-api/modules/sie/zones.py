"""Modules 5 + 6 — Zone extraction + Noise filtering layers 1, 2, 4.

Layer 3 (cross-page fingerprinting) and Layer 5 (frequency anomaly) live in
ngrams.py because they need cross-page state.

We rely on BeautifulSoup with the lxml parser for tolerance against
real-world HTML.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup, Tag

# ---- Layer 1 selectors ----
REMOVE_TAGS = {"nav", "footer", "header", "aside", "noscript", "script", "style", "form", "iframe"}
REMOVE_PATTERNS = re.compile(
    r"sidebar|widget|menu|nav|footer|breadcrumb|cookie|banner|"
    r"social-share|related-posts|author-bio|comments?|newsletter|signup|"
    r"sub-?footer|cta-?(?:button|block|wrap)?",
    re.IGNORECASE,
)
REMOVE_ROLES = {"navigation", "banner", "contentinfo", "complementary"}

# ---- Layer 4 patterns ----
PHONE_RE = re.compile(r"^\+?\(?\d[\d\s\-\(\)\.]{7,}\d$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ADDRESS_RE = re.compile(r"\b\d{1,5}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct)\b", re.IGNORECASE)
CTA_RE = re.compile(
    r"\b(call now|get a free|schedule your|request a quote|book (?:now|today)|"
    r"contact us today|click here|learn more)\b",
    re.IGNORECASE,
)


@dataclass
class PageZones:
    url: str
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
    word_count: int = 0
    body_text: str = ""

    def all_zone_text(self) -> dict[str, list[str]]:
        return {
            "title": [self.title] if self.title else [],
            "meta_description": [self.meta_description] if self.meta_description else [],
            "h1": list(self.h1),
            "h2": list(self.h2),
            "h3": list(self.h3),
            "h4": list(self.h4),
            "paragraphs": list(self.paragraphs),
            "lists": list(self.lists),
            "tables": list(self.tables),
            "faq_blocks": list(self.faq_blocks),
        }


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _layer1_strip_chrome(soup: BeautifulSoup) -> None:
    """Remove nav / footer / aside / class- and role-matched chrome."""
    for tag_name in REMOVE_TAGS:
        for el in soup.find_all(tag_name):
            el.decompose()

    # Remove by class / id pattern
    for el in list(soup.find_all(True)):
        if not isinstance(el, Tag):
            continue
        attrs = el.attrs or {}
        for attr in ("class", "id"):
            value = attrs.get(attr)
            if not value:
                continue
            joined = " ".join(value) if isinstance(value, list) else str(value)
            if REMOVE_PATTERNS.search(joined):
                el.decompose()
                break

    # Remove by ARIA role
    for el in list(soup.find_all(attrs={"role": True})):
        if not isinstance(el, Tag):
            continue
        if el.attrs.get("role") in REMOVE_ROLES:
            el.decompose()


def _layer2_text_density(soup: BeautifulSoup) -> None:
    """Drop blocks with link_ratio > 0.3 or short blocks surrounded by chrome."""
    for el in list(soup.find_all(["div", "section", "article"])):
        if not isinstance(el, Tag):
            continue
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        link_text = " ".join(a.get_text(" ", strip=True) for a in el.find_all("a"))
        text_words = len(text.split())
        link_words = len(link_text.split())
        if text_words and (link_words / text_words) > 0.3:
            el.decompose()


def _layer4_text_filters(text: str) -> bool:
    """Return True if the text block should be DROPPED from n-gram analysis."""
    text = text.strip()
    if len(text.split()) < 5:
        return True
    if PHONE_RE.match(text) or EMAIL_RE.match(text):
        return True
    if ADDRESS_RE.search(text) and len(text.split()) <= 12:
        return True
    if CTA_RE.search(text) and len(text.split()) <= 10:
        return True
    # Service-area lists: >50% of words are capitalized
    words = text.split()
    if words:
        proper_count = sum(1 for w in words if w[:1].isupper() and len(w) > 2)
        if proper_count / len(words) > 0.5 and len(words) <= 30:
            return True
    return False


def extract_zones(url: str, html: str) -> Optional[PageZones]:
    """Extract zones from raw HTML. Returns None if the page is empty/unparseable."""
    if not html or not html.strip():
        return None
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    title_el = soup.title
    title = _clean_text(title_el.text) if title_el else ""

    meta_desc = ""
    desc_tag = soup.find("meta", attrs={"name": "description"})
    if desc_tag and isinstance(desc_tag, Tag):
        meta_desc = _clean_text(desc_tag.attrs.get("content", ""))

    # FAQ schema (preserve before chrome stripping might catch it)
    faq_blocks: list[str] = []
    for el in soup.find_all(attrs={"itemtype": re.compile(r"FAQPage", re.IGNORECASE)}):
        text = _clean_text(el.get_text(" ", strip=True))
        if text:
            faq_blocks.append(text)

    # Apply Layer 1 + 2 to a copy
    _layer1_strip_chrome(soup)
    _layer2_text_density(soup)

    h1 = [_clean_text(t.get_text(" ", strip=True)) for t in soup.find_all("h1")]
    h2 = [_clean_text(t.get_text(" ", strip=True)) for t in soup.find_all("h2")]
    h3 = [_clean_text(t.get_text(" ", strip=True)) for t in soup.find_all("h3")]
    h4 = [_clean_text(t.get_text(" ", strip=True)) for t in soup.find_all("h4")]
    h1 = [h for h in h1 if h]
    h2 = [h for h in h2 if h]
    h3 = [h for h in h3 if h]
    h4 = [h for h in h4 if h]

    paragraphs: list[str] = []
    for p in soup.find_all("p"):
        text = _clean_text(p.get_text(" ", strip=True))
        if not text:
            continue
        if _layer4_text_filters(text):
            continue
        paragraphs.append(text)

    lists: list[str] = []
    for li in soup.find_all("li"):
        text = _clean_text(li.get_text(" ", strip=True))
        if not text:
            continue
        if _layer4_text_filters(text):
            continue
        lists.append(text)

    tables: list[str] = []
    for table in soup.find_all("table"):
        text = _clean_text(table.get_text(" ", strip=True))
        if text and not _layer4_text_filters(text):
            tables.append(text)

    body_text = _clean_text(soup.get_text(" ", strip=True))
    word_count = len(body_text.split())

    return PageZones(
        url=url,
        title=title,
        meta_description=meta_desc,
        h1=h1,
        h2=h2,
        h3=h3,
        h4=h4,
        paragraphs=paragraphs,
        lists=lists,
        tables=tables,
        faq_blocks=faq_blocks,
        word_count=word_count,
        body_text=body_text,
    )


# ---- Layer 3: cross-page fingerprinting ----

def cross_page_fingerprint_filter(pages: list[PageZones], min_domains: int = 3) -> list[PageZones]:
    """Filter out paragraphs/list items that appear (normalized) on >=N unique domains.

    Operates in place; returns the same list for convenience.
    """
    from urllib.parse import urlparse

    def _norm(s: str) -> str:
        return re.sub(r"[^\w\s]", "", s.lower()).strip()

    block_domains: dict[str, set[str]] = {}
    for page in pages:
        domain = urlparse(page.url).netloc.lower()
        for block in page.paragraphs + page.lists:
            key = _norm(block)
            if not key or len(key) < 30:
                continue
            block_domains.setdefault(key, set()).add(domain)

    boilerplate = {k for k, domains in block_domains.items() if len(domains) >= min_domains}

    for page in pages:
        page.paragraphs = [p for p in page.paragraphs if _norm(p) not in boilerplate]
        page.lists = [l for l in page.lists if _norm(l) not in boilerplate]

    return pages
