"""Brief Generator — clustered-keyword coverage audit (M13 follow-up, 2b).

The cluster groups many keywords onto one article; only the *primary* keyword drives the
answer-engine-first brief. The supporting keywords are still genuine research — without an
audit they're silently "disused". This module:

  1. Feeds the supporting keywords into the H3 subtopic candidate pool (so the ones that
     fit a heading actually get USED as subtopics) — done in the pipeline via `as_h3_candidates`.
  2. After the brief is assembled, audits which supporting keywords a heading covers and
     which fall through, so the panel can surface "researched but not covered" instead of
     dropping them on the floor.

"Covered" = a keyword whose tokens appear in a heading (lexical) OR whose embedding is within
`threshold` cosine of some heading (3-large). Pure except the single embed batch in `audit`.
"""

from __future__ import annotations

import re

from .entity import cosine

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _dedupe(keywords: list[str]) -> list[str]:
    """Collapse case-insensitive duplicates, preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for k in keywords:
        t = (k or "").strip()
        key = t.lower()
        if t and key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _lexically_covered(kw: str, heading_token_sets: list[set[str]]) -> bool:
    """True when every significant token of the keyword appears in some single heading
    (subset match) — e.g. 'retatrutide amino acid sequence' ⊆ a heading mentioning all of
    'retatrutide', 'amino', 'acid', 'sequence'."""
    kt = _tokens(kw)
    return bool(kt) and any(kt <= hs for hs in heading_token_sets)


def as_h3_candidates(supporting_keywords: list[str]) -> list:
    """Wrap supporting keywords as H3Candidate(source='cluster_keyword') for `select_h3s`.
    Deduped; the band/region/MMR filters downstream decide which actually land."""
    from .h3 import H3Candidate

    return [H3Candidate(k, "cluster_keyword") for k in _dedupe(supporting_keywords)]


def audit(
    supporting_keywords: list[str], *, heading_texts: list[str], used_texts: list[str],
    embed_fn, threshold: float,
) -> dict:
    """Audit clustered-keyword coverage against the assembled brief's headings.

    `heading_texts` = every H1/H2/H3 + FAQ question in the brief. `used_texts` = the subset
    of headings that came from a `cluster_keyword` source (already promoted to subtopics).
    Returns a metadata block: counts + the covered / uncovered / used lists (uncovered carries
    the nearest heading + cosine so the owner can judge whether to split or accept)."""
    kws = [k for k in _dedupe(supporting_keywords) if _tokens(k)]
    used_lower = {t.strip().lower() for t in used_texts}
    result = {
        "threshold": round(threshold, 4),
        "total": len(kws),
        "covered": [],
        "uncovered": [],
        "used_as_subtopic": sorted({t for t in used_texts if t}),
    }
    if not kws or not heading_texts:
        result["uncovered"] = [{"keyword": k, "nearest": None, "cosine": 0.0} for k in kws]
        return result

    heading_token_sets = [_tokens(h) for h in heading_texts]
    vecs = embed_fn([*kws, *heading_texts])
    kw_vecs = vecs[: len(kws)]
    head_vecs = vecs[len(kws):]

    for kw, kv in zip(kws, kw_vecs):
        # A keyword already promoted to a subtopic counts as covered outright.
        if kw.strip().lower() in used_lower or _lexically_covered(kw, heading_token_sets):
            result["covered"].append(kw)
            continue
        best_i, best_cos = -1, -1.0
        for i, hv in enumerate(head_vecs):
            c = cosine(kv, hv)
            if c > best_cos:
                best_i, best_cos = i, c
        if best_cos >= threshold:
            result["covered"].append(kw)
        else:
            result["uncovered"].append({
                "keyword": kw,
                "nearest": heading_texts[best_i] if best_i >= 0 else None,
                "cosine": round(best_cos, 4),
            })
    result["covered_count"] = len(result["covered"])
    result["uncovered_count"] = len(result["uncovered"])
    return result


def greedy_group(texts: list[str], vecs: list[list[float]], *, threshold: float) -> list[list[str]]:
    """Group near-duplicate keywords so each *group* becomes one split article (never one
    article per keyword, which would recreate the thin-content/cannibalization problem).
    Greedy: each text joins the first existing group whose representative (first member) is
    within `threshold` cosine, else it opens a new group. Order-stable."""
    groups: list[list[str]] = []
    reps: list[list[float]] = []
    for t, v in zip(texts, vecs):
        placed = False
        for gi, rv in enumerate(reps):
            if cosine(v, rv) >= threshold:
                groups[gi].append(t)
                placed = True
                break
        if not placed:
            groups.append([t])
            reps.append(v)
    return groups

