"""SERP heading sanitization (Content Quality PRD v1.0 R2).

Deterministic preprocessor that strips artifacts off heading candidates
before they enter the aggregation/dedup/scoring pipeline. Returns the
cleaned string, or None when the heading should be discarded (too short
after sanitization, or non-descriptive).

Per Brief Generator PRD v1.8 §5 Step 4.0.
"""

from __future__ import annotations

import html
import re
from typing import Optional
from urllib.parse import urlparse

# Order matters: HTML decode + tag strip before whitespace collapse before
# suffix/prefix strips before length checks.

_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")

# S1 - trailing subreddit suffix `: r/XYZ`
_SUBREDDIT_SUFFIX_RE = re.compile(r"\s*:\s*r/[A-Za-z0-9_]+\s*$")

# S2 - trailing ellipsis: unicode `…`, runs of 3+ periods, with optional surrounding whitespace
_ELLIPSIS_SUFFIX_RE = re.compile(r"\s*(?:…|\.{3,})\s*$")

# S5 - trailing read-more boilerplate (run before the generic site-name strip
# so "Read More" doesn't get caught by the site-name heuristic)
_READ_MORE_SUFFIX_RE = re.compile(
    r"\s*(?:\||\s+[-–-]\s+)\s*(?:read\s*more|continue\s*reading)\s*\.{0,3}\s*$",
    re.IGNORECASE,
)
_READ_MORE_TRAILING_RE = re.compile(
    r"\s*(?:read\s*more|continue\s*reading)\s*(?:…|\.{3,})\s*$",
    re.IGNORECASE,
)

# Pipe separator: `Title | Tagline-or-Site-Name`. SEO titles use this almost
# exclusively to separate article title from publisher tagline, so a trailing
# segment after `|` is treated as strippable unless it's question-shaped.
_PIPE_SUFFIX_RE = re.compile(r"\s*\|\s*([^|]+?)\s*$")

# Dash separator: `Title - Tagline`. Only en/em dashes or a hyphen surrounded
# by spaces count - bare hyphens inside compounds like `E-Commerce` are NOT
# separators. Trailing segment is treated as a possible site/tagline.
_DASH_SUFFIX_RE = re.compile(r"\s+[–-]\s+([^–-]+?)\s*$|\s+-\s+([^-]+?)\s*$")

# Leading numbering / bullet markers
_LEADING_NUMBERING_RE = re.compile(r"^\s*(?:\d{1,2}[\.\)]|[•\-\*•])\s+")

# Markdown emphasis residue
_MARKDOWN_RESIDUE_RE = re.compile(r"[`*_]+")

# Whitespace collapse
_WHITESPACE_RE = re.compile(r"\s+")

# S8 - trailing punctuation runs other than a single ? or .
_TRAILING_PUNCT_RUN_RE = re.compile(r"([?.!]){2,}\s*$")

# S10 - non-descriptive single brand name: 1-3 capitalized words, no verbs/articles,
# no question words. Heuristic: only proper-noun looking tokens, no lowercase verbs.
_NON_DESCRIPTIVE_RE = re.compile(
    r"^([A-Z][A-Za-z0-9&]*(?:[\s\.\-][A-Z][A-Za-z0-9&]*){0,2})$"
)


_QUESTION_WORDS = {"what", "why", "how", "when", "where", "who", "which", "is", "are", "do", "does", "can", "will", "should"}


def _looks_strippable_after_separator(segment: str, source_url: Optional[str]) -> bool:
    """Decide whether the trailing segment after `|` or surrounded `-` should be stripped.

    SEO titles overwhelmingly use these separators to append a publisher
    name or marketing tagline to the article title. We strip aggressively
    EXCEPT when the trailing segment looks like a continuation of the title
    (a question, or starts with a question word).

    Always strip when:
    - Domain match: trailing segment contains the source URL's domain root
    - The segment is not question-shaped (no `?`, doesn't start with what/why/how/etc.)

    Don't strip when:
    - Trailing segment is question-shaped (probably part of the article title,
      e.g. `"X | Y: How does it work?"`)
    """
    seg = segment.strip()
    if not seg:
        return False

    # Domain match wins - always strip when the trailing segment contains
    # the publisher's domain root.
    if source_url:
        try:
            host = urlparse(source_url).hostname or ""
        except Exception:
            host = ""
        host_root = re.sub(r"^www\.", "", host).split(".")[0].lower()
        if host_root and host_root in seg.lower():
            return True

    # Question-shaped → keep (likely part of title).
    if "?" in seg:
        return False
    first_word = re.match(r"\s*([A-Za-z']+)", seg)
    if first_word and first_word.group(1).lower() in _QUESTION_WORDS:
        return False

    return True


def sanitize_heading(text: str, source_url: Optional[str] = None) -> Optional[str]:
    """Apply Content Quality PRD R2 sanitization rules.

    Returns the cleaned heading string, or None if the heading should be
    discarded entirely (S9 too-short, S10 non-descriptive).
    """
    if text is None:
        return None

    out = text

    # S6 - decode HTML entities then strip tags
    out = html.unescape(out)
    out = _HTML_TAG_RE.sub("", out)

    # Markdown residue (asterisks, backticks, underscores used as emphasis)
    out = _MARKDOWN_RESIDUE_RE.sub("", out)

    # Leading numbering / bullets
    out = _LEADING_NUMBERING_RE.sub("", out)

    # S5 - trailing read-more boilerplate
    out = _READ_MORE_SUFFIX_RE.sub("", out)
    out = _READ_MORE_TRAILING_RE.sub("", out)

    # S2 - trailing ellipsis (run before suffix detection so the suffix isn't
    # protected by a trailing "…")
    out = _ELLIPSIS_SUFFIX_RE.sub("", out)

    # S1 - subreddit suffix
    out = _SUBREDDIT_SUFFIX_RE.sub("", out)

    # S3a - trailing pipe-separated tagline / site name. Aggressive: strip
    # unless the trailing segment is question-shaped.
    pipe_match = _PIPE_SUFFIX_RE.search(out)
    if pipe_match:
        trailing = pipe_match.group(1)
        if _looks_strippable_after_separator(trailing, source_url):
            out = out[: pipe_match.start()].rstrip()

    # S3b - trailing dash-separated tagline / site name. Stricter than the
    # pipe rule because dashes legitimately appear inside titles ("Pros - Cons"):
    # only strip when the leading part has ≥ 3 words (so we never collapse a
    # 2-word title to 1 word) AND the trailing segment isn't question-shaped.
    dash_match = _DASH_SUFFIX_RE.search(out)
    if dash_match:
        leading_words = len(out[: dash_match.start()].split())
        trailing = dash_match.group(1) or dash_match.group(2) or ""
        if leading_words >= 3 and _looks_strippable_after_separator(trailing, source_url):
            out = out[: dash_match.start()].rstrip()

    # S4 - leading site-name prefix `SiteName: rest`. Conservative: only strip
    # when the prefix matches the source URL's domain root, since heuristic
    # length-based prefix matching has higher false-positive risk than suffixes.
    prefix_match = re.match(r"^\s*([^:]+?)\s*:\s+", out)
    if prefix_match and source_url:
        prefix = prefix_match.group(1).strip()
        try:
            host = urlparse(source_url).hostname or ""
        except Exception:
            host = ""
        host_root = re.sub(r"^www\.", "", host).split(".")[0].lower()
        if host_root and host_root in prefix.lower():
            out = out[prefix_match.end():].lstrip()

    # S2 again - strip any ellipsis revealed by suffix removal
    out = _ELLIPSIS_SUFFIX_RE.sub("", out)

    # S8 - trailing punctuation runs reduce to single terminal mark
    out = _TRAILING_PUNCT_RUN_RE.sub(r"\1", out)

    # S7 - collapse internal whitespace (do this last so all the strips happen
    # against the original spacing, then we tidy up)
    out = _WHITESPACE_RE.sub(" ", out).strip()

    # Strip stray leading/trailing punctuation that may have been left dangling
    out = out.strip(" \t :;,--–")

    if not out:
        return None

    # S9 - too short after sanitization (< 3 words)
    word_count = len(out.split())
    if word_count < 3:
        return None

    # S10 - non-descriptive (just a brand/proper-noun phrase, no verb/question)
    if word_count <= 3 and _NON_DESCRIPTIVE_RE.match(out):
        return None

    return out
