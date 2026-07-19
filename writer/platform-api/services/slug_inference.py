"""Detect an existing site's URL/slug conventions (SOP "Importing an Existing
Site — Precedence & Detection").

Pure functions over a list of URLs (from `site_page_index.discover_site_urls`)
or a repo content tree (file paths from the GitHub Git Trees API). No I/O — the
network fetch lives in the caller.

On an imported site the site is authoritative; this module turns "what does the
site actually do" into a machine-readable descriptor the publish path can follow
(and that a validator can diff against the SOP house defaults). Content-type keys
match the `github_content_paths` map (blog_post / service_page / location_page /
product), so an inferred repo-tree result can populate it directly.
"""
from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

# Known collection roots per content type — the first path segment (URL) or a
# directory name (repo tree) a site uses for that role. Matched as a whole
# segment, so "service-areas" won't match a bare "areas".
ROLE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "blog_post": ("blog", "news", "insights", "articles", "article", "resources", "posts", "journal", "updates"),
    "service_page": ("services", "service", "our-services", "what-we-do", "solutions", "capabilities"),
    "location_page": ("areas-we-serve", "service-areas", "service-area", "locations", "location", "areas", "cities"),
    "product": ("shop", "products", "product", "store", "collections", "catalog"),
}

# File extensions that indicate a page URL/file (for extension + leaf detection).
_PAGE_EXT_RE = re.compile(r"\.(html?|php|aspx?)$", re.IGNORECASE)
_REPO_CONTENT_EXT_RE = re.compile(r"\.(md|mdx|mdoc|json|ya?ml)$", re.IGNORECASE)


def _url_segments(url: str) -> list[str]:
    """Non-empty path segments of a URL (raw — not slugified)."""
    try:
        path = urlparse(url).path or ""
    except ValueError:
        return []
    return [s for s in path.split("/") if s]


def _leaf(segments: list[str]) -> str:
    """The last path segment with any page extension stripped, else ''."""
    if not segments:
        return ""
    return _PAGE_EXT_RE.sub("", segments[-1])


def infer_separator(url_lists: list[list[str]]) -> str | None:
    """Dominant word separator in leaf slugs: '-' or '_' (None if undetectable)."""
    hy = un = 0
    for segs in url_lists:
        leaf = _leaf(segs)
        hy += leaf.count("-")
        un += leaf.count("_")
    if hy == 0 and un == 0:
        return None
    return "-" if hy >= un else "_"


def infer_trailing_slash(urls: list[str]) -> bool | None:
    """Whether the site's page URLs end in a trailing slash (majority vote).
    URLs whose last segment is a file (has an extension) don't count."""
    yes = no = 0
    for u in urls:
        segs = _url_segments(u)
        if not segs:  # root "/" — skip, uninformative
            continue
        if _PAGE_EXT_RE.search(segs[-1]):
            continue  # a .html file never carries a trailing slash
        if (urlparse(u).path or "").endswith("/"):
            yes += 1
        else:
            no += 1
    if yes == 0 and no == 0:
        return None
    return yes >= no


def infer_extension(urls: list[str]) -> str:
    """The dominant page-URL file extension ('' when the site uses extensionless
    URLs, else e.g. '.html')."""
    counts: Counter[str] = Counter()
    for u in urls:
        segs = _url_segments(u)
        if not segs:
            continue
        m = _PAGE_EXT_RE.search(segs[-1])
        counts[m.group(0).lower() if m else ""] += 1
    if not counts:
        return ""
    return counts.most_common(1)[0][0]


def _role_for_segment(segment: str) -> str | None:
    seg = segment.lower()
    for content_type, synonyms in ROLE_SYNONYMS.items():
        if seg in synonyms:
            return content_type
    return None


def infer_url_role_prefixes(urls: list[str]) -> dict[str, str]:
    """Per content type, the first-path-segment prefix the site actually uses
    (e.g. {'blog_post': 'news', 'location_page': 'service-areas'}). The most
    frequent matching prefix wins; roles with no matching URL are omitted."""
    # content_type -> Counter of matching first-segment prefixes
    by_role: dict[str, Counter[str]] = {}
    for u in urls:
        segs = _url_segments(u)
        if not segs:
            continue
        role = _role_for_segment(segs[0])
        if role:
            by_role.setdefault(role, Counter())[segs[0].lower()] += 1
    return {role: counts.most_common(1)[0][0] for role, counts in by_role.items()}


def infer_slug_patterns(urls: list[str]) -> dict:
    """Top-level descriptor of a site's URL conventions, inferred from its URL
    list: separator, trailing_slash, extension, and per-role prefixes. Values are
    None/absent when undetectable — the caller falls back to the SOP defaults."""
    seg_lists = [_url_segments(u) for u in urls]
    return {
        "separator": infer_separator(seg_lists),
        "trailing_slash": infer_trailing_slash(urls),
        "extension": infer_extension(urls),
        "prefixes": infer_url_role_prefixes(urls),
    }


# Segments that mark a real content root, so a synonym dir under them is a page
# collection — not e.g. a `/docs/blog/` folder of documentation.
CONTENT_ROOT_SEGMENTS = frozenset({"content", "pages", "data"})


def infer_content_paths_from_repo_tree(paths: list[str]) -> dict[str, str]:
    """Per content type, the repo content path a site's collections live in —
    inferred from a repo file tree (Git Trees API). Directly populates
    `github_content_paths`.

    For each content file, the shallowest path segment matching a role synonym is
    the collection; the path up to and including it is the content path (so
    `src/content/blog/2024/x.md` → `src/content/blog`). The most frequent content
    path per role wins.

    When the tree has a recognizable content root (`content`/`pages`/`data`), a
    collection only counts if it sits under one — so `docs/blog/notes.md` in a
    doc-heavy repo can't out-vote `src/content/blog`. When no content root exists
    (non-standard layout) the restriction is lifted (best-effort)."""
    has_root = any(seg in CONTENT_ROOT_SEGMENTS for path in paths for seg in path.split("/"))
    by_role: dict[str, Counter[str]] = {}
    for path in paths:
        if not _REPO_CONTENT_EXT_RE.search(path):
            continue
        segs = [s for s in path.split("/") if s]
        for i, seg in enumerate(segs[:-1]):  # exclude the file name itself
            role = _role_for_segment(seg)
            if role:
                # Require a content-root ancestor when the tree has one.
                if has_root and not any(a in CONTENT_ROOT_SEGMENTS for a in segs[:i]):
                    break
                content_path = "/".join(segs[: i + 1])
                by_role.setdefault(role, Counter())[content_path] += 1
                break  # shallowest match is the collection root
    return {role: counts.most_common(1)[0][0] for role, counts in by_role.items()}
