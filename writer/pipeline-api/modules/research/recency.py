"""Publication date detection from HTML meta tags, JSON-LD, and PDF metadata.

Per Research PRD §3 (Recency classification), sources without a verifiable
date are excluded from the candidate pool. Five-year hard cutoff with a
narrow exception for Tier 1 foundational sources.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Literal, Optional

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

RecencyLabel = Literal["fresh", "dated", "stale"]

META_DATE_FIELDS = (
    "article:published_time",
    "article:modified_time",
    "datepublished",
    "datemodified",
    "publication_date",
    "publish_date",
    "pubdate",
    "date",
    "dc.date",
    "dc.date.issued",
    "lastmod",
    "og:updated_time",
    "sailthru.date",
    "parsely-pub-date",
)

DATE_REGEX_BODY = re.compile(
    r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b"
    r"|\b(?:January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\s+\d{1,2},\s*20\d{2}\b",
    re.IGNORECASE,
)


def _parse_date(value: str) -> Optional[datetime]:
    if not value or not value.strip():
        return None
    try:
        dt = dateparser.parse(value, fuzzy=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def detect_html_date(html: str) -> Optional[datetime]:
    """Try meta tags → JSON-LD → body regex. Returns aware datetime or None."""
    if not html:
        return None
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    # Meta tags (name + property)
    for meta in soup.find_all("meta"):
        attrs = meta.attrs or {}
        identifier = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if identifier in META_DATE_FIELDS:
            dt = _parse_date(attrs.get("content", ""))
            if dt:
                return dt

    # <time datetime="..."> tag
    time_tag = soup.find("time")
    if time_tag and isinstance(time_tag.attrs, dict):
        dt = _parse_date(time_tag.attrs.get("datetime", ""))
        if dt:
            return dt

    # JSON-LD <script type="application/ld+json">
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or "")
        except Exception:
            continue
        for candidate in _iter_jsonld(payload):
            for key in ("datePublished", "dateModified", "uploadDate", "dateCreated"):
                if key in candidate:
                    dt = _parse_date(candidate[key])
                    if dt:
                        return dt

    # Body regex as last resort
    body_text = soup.get_text(" ", strip=True)
    match = DATE_REGEX_BODY.search(body_text)
    if match:
        dt = _parse_date(match.group(0))
        if dt:
            return dt
    return None


def _iter_jsonld(payload):
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_jsonld(item)
    elif isinstance(payload, dict):
        yield payload
        # @graph nesting
        graph = payload.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_jsonld(item)


def detect_pdf_date(pdf_metadata: dict) -> Optional[datetime]:
    """Extract publication date from pypdf metadata dict."""
    if not pdf_metadata:
        return None
    for key in ("/CreationDate", "/ModDate", "creationDate", "creation_date"):
        value = pdf_metadata.get(key) if hasattr(pdf_metadata, "get") else None
        if not value:
            continue
        # PDF dates often look like D:20240131120000Z
        if isinstance(value, str) and value.startswith("D:"):
            value = value[2:16]
            try:
                year = int(value[0:4])
                month = int(value[4:6])
                day = int(value[6:8])
                return datetime(year, month, day, tzinfo=timezone.utc)
            except Exception:
                pass
        dt = _parse_date(str(value))
        if dt:
            return dt
    return None


def recency_label_and_score(
    published: Optional[datetime],
    tier: int,
    is_foundational: bool = False,
) -> tuple[Optional[RecencyLabel], float, bool]:
    """Returns (label, score, recency_exception_flag).

    None label means hard-excluded by recency. is_foundational allows Tier 1
    sources older than 5 years to pass with a flat score of 0.50.
    """
    if published is None:
        return (None, 0.0, False)

    now = datetime.now(timezone.utc)
    age_years = (now - published).days / 365.25

    if age_years < 1:
        return ("fresh", 1.00, False)
    if age_years <= 3:
        return ("dated", 0.65, False)
    if age_years <= 5:
        return ("stale", 0.30, False)
    if tier == 1 and is_foundational:
        return ("stale", 0.50, True)
    return (None, 0.0, False)
