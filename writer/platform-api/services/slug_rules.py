"""Deterministic URL slug + path construction.

Implements the house SOP's "URL & Slug Construction Rules"
(docs/sops/Site_Architecture_and_Internal_Linking_SOP.md — v3). Pure functions,
no I/O, so they're unit-testable directly against the SOP's conformance traces.

Precedence note: on an EXISTING/imported site the site's own URL conventions win
(that detection is a separate concern — this module is the greenfield default and
the string-rule engine the publish path calls once a target pattern is chosen).

The normalization pipeline order is mandatory (SOP): the special-token pre-pass
and year strip run BEFORE the generic non-alphanumeric→hyphen pass, or the token
substitutions never fire (`&` would collapse to `-` first).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

# SOP: max slug length 500 chars, no word-boundary truncation (effectively no
# truncation — a hard cap only).
MAX_SLUG_LEN = 500

# Reserved structural URL segments a computed leaf slug must not equal.
RESERVED_SEGMENTS = frozenset(
    {
        "blog",
        "contact-us",
        "bio",
        "services",
        "locations",
        "areas-we-serve",
        "about-us",
        "shop",
        "privacy-policy",
    }
)

# SOP page types build_page_path understands.
PAGE_TYPES = (
    "blog_post",
    "top_level_service",
    "sub_service",
    "top_level_location",
    "local_landing",
    "neighborhood",
    "product",
)

# A standalone 4-digit year in 1900–2099, not adjacent to other digits.
_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_APOSTROPHE_RE = re.compile(r"['‘’]")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _apply_token_prepass(text: str) -> str:
    """SOP 'Numbers & Special Tokens' table. Runs first so word substitutions
    (`&`/`+` → and) survive the later generic hyphen pass. Words are padded with
    spaces so tokens with no surrounding whitespace (``heating&cooling``) still
    split into separate slug words."""
    s = text
    s = s.replace("&", " and ")  # heating & cooling -> ...and...
    s = s.replace("%", " percent ")  # 50% -> 50 percent
    s = s.replace("@", " at ")
    s = re.sub(r"(?<=\d)\s*\+", " plus ", s)  # 55+ -> 55 plus
    s = s.replace("+", " and ")  # commercial + residential -> ...and...
    s = s.replace("$", "")  # $99 -> 99 (drop the $, keep the number)
    s = s.replace("#", "")  # #1 -> 1
    s = s.replace("°", "")  # 72° -> 72
    return s


def build_slug(source: str) -> str:
    """Build a URL slug from a source string per the SOP normalization pipeline.

    Returns "" for empty/whitespace-only input (callers supply their own fallback
    where a non-empty slug is required). Stopwords are kept (SOP)."""
    if not source:
        return ""
    s = _apply_token_prepass(source)  # 1 token pre-pass
    s = _YEAR_RE.sub(" ", s)  # 2 year strip
    s = s.lower()  # 3 lowercase
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")  # 4 ASCII-fold
    s = _APOSTROPHE_RE.sub("", s)  # 5 apostrophe strip (no hyphen)
    s = _NON_ALNUM_RE.sub("-", s)  # 6 generic replace (collapses runs)
    s = s.strip("-")  # 7 trim
    if len(s) > MAX_SLUG_LEN:  # 8 hard length cap (no word-boundary truncation)
        s = s[:MAX_SLUG_LEN].strip("-")
    return s


def collision_suffix(*identity_parts: str, length: int = 5) -> str:
    """A deterministic base-36 (lowercase) suffix derived from a page's stable
    identity. Same identity → same suffix (idempotent, so a re-publish overwrites
    in place); different identities → different suffixes. NOT random — that would
    make every publish create a new file/URL."""
    raw = "\x1f".join(p or "" for p in identity_parts)
    n = int(hashlib.sha256(raw.encode("utf-8")).hexdigest(), 16)
    out = []
    for _ in range(length):
        n, r = divmod(n, 36)
        out.append(_B36[r])
    return "".join(out)


def apply_collision(
    slug: str,
    *,
    identity: tuple[str, ...],
    reserved: frozenset[str] = RESERVED_SEGMENTS,
    taken: object = (),
) -> str:
    """Return `slug`, or `slug-<deterministic suffix>` when it collides with a
    reserved structural segment or an already-taken slug. Fully automatic — no
    human intervention (SOP). `identity` is the stable tuple the suffix hashes
    (e.g. page_type, normalized source, parent path)."""
    taken_set = set(taken)
    if slug in reserved or slug in taken_set:
        return f"{slug}-{collision_suffix(*identity)}"
    return slug


def location_segment(location: str, region: str | None = None) -> str:
    """Build a location slug, appending the region code (SOP same-name
    disambiguation), e.g. ('Los Angeles','CA') → 'los-angeles-ca'."""
    seg = build_slug(location)
    if region:
        r = build_slug(region)
        if r:
            seg = f"{seg}-{r}" if seg else r
    return seg


def compose_path(segments: list[str], *, trailing_slash: bool = True) -> str:
    """Join already-built slug segments into a URL path — leading slash, trailing
    slash by default, no file extension (segments are bare slugs). Empty segments
    are dropped."""
    clean = [s.strip("/") for s in segments if s and s.strip("/")]
    path = "/" + "/".join(clean)
    if trailing_slash and not path.endswith("/"):
        path += "/"
    return path


def build_page_path(
    page_type: str,
    *,
    service: str | None = None,
    subservice: str | None = None,
    location: str | None = None,
    region: str | None = None,
    neighborhood: str | None = None,
    product: str | None = None,
    keyword: str | None = None,
    trailing_slash: bool = True,
) -> str:
    """Compose the public URL path for a page per the SOP per-type nesting
    (greenfield). Each part is run through build_slug. Raises ValueError on an
    unknown page_type."""
    if page_type == "blog_post":
        segs = ["blog", build_slug(keyword or "")]
    elif page_type == "top_level_service":
        segs = [build_slug(service or "")]
    elif page_type == "sub_service":
        segs = [build_slug(service or ""), build_slug(subservice or "")]
    elif page_type == "top_level_location":
        segs = [location_segment(location or "", region)]
    elif page_type == "local_landing":
        segs = [location_segment(location or "", region), build_slug(service or "")]
    elif page_type == "neighborhood":
        segs = [location_segment(location or "", region), build_slug(neighborhood or "")]
    elif page_type == "product":
        segs = ["shop", build_slug(product or "")]
    else:
        raise ValueError(f"unknown page_type: {page_type!r}")
    return compose_path(segs, trailing_slash=trailing_slash)
