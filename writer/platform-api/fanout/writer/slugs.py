"""Deterministic URL slugs (M15 slice 1, handoff §9.5).

A cluster's slug is derived from its title/primary keyword, stable across runs, and
deduped within its silo (topic) so `{base}/{silo-slug}/{article-slug}` is always unique.
Assigned once at pre-schedule time; an article generated on day 1 can therefore link to
one scheduled for day 40 (the target URL is knowable before the target exists).

Pure — no DB. The storage layer persists the result onto `clusters.slug`.
"""

from __future__ import annotations

import re

_NONWORD = re.compile(r"[^\w\s-]")
_SPACES = re.compile(r"[\s_]+")
_DASHES = re.compile(r"-{2,}")


def slugify(text: str, *, max_len: int = 80) -> str:
    """Lowercase, strip punctuation, collapse whitespace to single hyphens. Never empty."""
    s = _NONWORD.sub("", (text or "").lower())
    s = _SPACES.sub("-", s.strip())
    s = _DASHES.sub("-", s).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "page"


def assign_slugs(items: list[tuple[str, str]], *, existing: dict[str, str] | None = None) -> dict[str, str]:
    """`items` = ordered `[(cluster_id, title_or_keyword)]` for ONE silo (topic); returns
    `{cluster_id: unique_slug}`. Deterministic (order-stable) and deduped (`-2`, `-3`, …).
    `existing` (already-assigned `{cluster_id: slug}` in this silo) is honored unchanged and
    reserved so a re-run is idempotent and never reassigns a stable URL."""
    existing = existing or {}
    used = set(existing.values())
    out: dict[str, str] = {}
    for cid, text in items:
        if cid in existing and existing[cid]:
            out[cid] = existing[cid]
            continue
        base = slugify(text)
        slug = base
        n = 1
        while slug in used:
            n += 1
            slug = f"{base}-{n}"
        used.add(slug)
        out[cid] = slug
    return out
