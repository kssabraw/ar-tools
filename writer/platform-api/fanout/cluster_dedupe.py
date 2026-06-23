"""Display-time within-cluster keyword deduplication.

The Cluster View (PRD §9.2) shows every keyword that belongs to an article
cluster. Because autocomplete + DataForSEO suggestions surface many phrasing
variants of the same intent, a single cluster can carry obvious near-dupes
("what is X" / "what are X", "X example" / "X examples", "msp example" /
"managed service provider example", "definition" / "meaning"). The relevance
gate is right to keep them — they're all on-niche — but rendering them all
clutters the article card.

This module runs two collapse passes per cluster:

1. **Surface-form normalization** (cheap, deterministic): lowercase, strip
   punctuation, lemmatize trailing -s plurals, fold "what is/are/'s/does X" to
   one canonical question form, drop leading articles (a/an/the), normalize
   known aliases (msp <-> managed service provider), and ignore word order via
   a sorted token signature. Keywords sharing a normalized form collapse to
   one canonical (highest volume, then highest relevance, then alphabetic).

2. **Cosine collapse** (semantic, embeddings required): pairwise cosine on the
   per-keyword embeddings persisted by the relevance gate (M5/§7.6). Pairs
   above the configured threshold collapse, same winner rule.

The pass is pure: it takes keyword rows, returns a `{keyword_id: canonical_id}`
mapping (canonical maps to itself; collapsed variants map to their canonical).
No DB writes. The endpoint stitches the mapping onto each row as
`dedupe_canonical_id` (null when canonical) so the Cluster View can filter and
the Table View / CSV exports are unaffected. Cosine is skipped per-cluster
when fewer than 2 keywords carry an embedding — old sessions (pre-migration)
get the surface-form half free, the cosine half degrades silently.

Tunable: `cluster_display_dedupe_cosine_threshold` (default 0.95). 1.0 disables
the cosine half without touching the surface-form pass.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

# Known multi-word aliases collapsed to a canonical token. Owner-extensible;
# conservative by default (we only fold pairs where the gloss is well-known and
# unambiguous in any cybersec / ITops / SaaS context). Applied as a token-bag
# pass after singularization + word-order sort, so non-contiguous variants like
# "managed it service provider" still match the same alias as "managed service
# provider". Longest aliases run first so "managed security service provider"
# claims its tokens before the shorter "managed service provider" alias would.
_ALIASES: dict[tuple[str, ...], str] = {
    # Tokens are stored singularized (the singularizer is idempotent) so that
    # the lookup matches against post-singular keyword tokens directly.
    ("managed", "security", "service", "provider"): "mssp",
    ("managed", "service", "provider"): "msp",
    ("information", "technology"): "it",
    ("search", "engine", "optimization"): "seo",
    ("search", "engine", "optimisation"): "seo",
}

# Articles + leading filler stripped from the token signature (so "what is a X"
# == "what is X"). "what is" / "what are" / "what's" / "what does" collapse to
# a single question marker.
_LEADING_FILLER = {"a", "an", "the"}
_QUESTION_HEADS: dict[tuple[str, ...], tuple[str, ...]] = {
    ("what", "is"): ("q_is",),
    ("what", "are"): ("q_is",),
    ("whats",): ("q_is",),       # "what's" after punctuation strip
    ("what", "does"): ("q_is",),
    ("what", "do"): ("q_is",),
    ("how", "to"): ("q_how",),
    ("how", "do", "i"): ("q_how",),
    ("how", "does"): ("q_how",),
}

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def _strip_plural(token: str) -> str:
    """Conservative plural -> singular: trailing 'ies' -> 'y', 'es' after sibilants,
    bare 's' on words >= 4 chars. Skips ambiguous short tokens ('is', 'as')."""
    if len(token) < 4:
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith(("ses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _apply_aliases_token_bag(tokens: list[str]) -> list[str]:
    """Replace any alias whose tokens are ALL present (as a set) in `tokens`
    with its canonical short form, longest alias first so MSSP claims its
    tokens before MSP would. Token order is irrelevant — by this point in the
    pipeline we've already sorted the body."""
    out = list(tokens)
    # Sort aliases by token count descending so longer ones win when they share
    # subsets ("managed security service provider" before "managed service
    # provider").
    for alias_tokens, short in sorted(_ALIASES.items(), key=lambda kv: -len(kv[0])):
        present = set(out)
        if all(t in present for t in alias_tokens):
            consumed = set(alias_tokens)
            out = [t for t in out if t not in consumed] + [short]
    return out


def _strip_question_head(tokens: list[str]) -> list[str]:
    for head, replacement in _QUESTION_HEADS.items():
        n = len(head)
        if tuple(tokens[:n]) == head:
            return list(replacement) + tokens[n:]
    return tokens


def normalize_keyword(keyword: str) -> str:
    """Surface-form signature. Two keywords with the same signature are
    treated as duplicates regardless of phrasing, plural, article, word order,
    or known alias. Returns "" for empty / pure-punctuation input."""
    if not keyword:
        return ""
    text = keyword.lower().strip()
    text = _NON_ALNUM.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    if not text:
        return ""
    tokens = [t for t in text.split(" ") if t and t not in _LEADING_FILLER]
    if not tokens:
        return ""
    tokens = _strip_question_head(tokens)
    tokens = [_strip_plural(t) for t in tokens]
    # Word-order trivia ("managed it service" vs "it managed service"): sort
    # the content tokens but keep the question head pinned at the front so
    # "what is X" doesn't collide with "X" alone.
    head: list[str] = []
    body = tokens
    if tokens and tokens[0].startswith("q_"):
        head = [tokens[0]]
        body = tokens[1:]
    # Token-bag alias substitution runs over the singularized body so non-
    # contiguous phrasings ("managed it service provider") collapse to the
    # same alias short form ("msp") as the contiguous one would.
    body = _apply_aliases_token_bag(body)
    body_sig = sorted(body)
    return " ".join(head + body_sig)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


@dataclass(frozen=True)
class KeywordRow:
    """Minimum fields the dedup pass reads. Maps cleanly to a `fanout.keywords`
    row enriched with the optional `embedding`."""
    id: str
    cluster_id: str | None
    keyword: str
    volume: int | None
    relevance_score: float | None
    is_primary_for_cluster: bool
    embedding: list[float] | None


def _winner_key(row: KeywordRow) -> tuple:
    """Sort key for picking the canonical out of a duplicate group. Higher wins
    under `max(...)`. Primary-of-cluster always wins so the card's "target
    keyword" pointer doesn't end up hidden. Volume and relevance are the
    demand signals; shorter and lexicographically-earlier keywords break ties
    deterministically (the `-ord` tuple inverts string comparison so "a"
    sorts higher than "b" under max())."""
    return (
        1 if row.is_primary_for_cluster else 0,
        row.volume if row.volume is not None else 0,
        row.relevance_score if row.relevance_score is not None else 0.0,
        -len(row.keyword),
        tuple(-ord(c) for c in row.keyword),
    )


def _pick_canonical(group: Sequence[KeywordRow]) -> KeywordRow:
    return max(group, key=_winner_key)


def dedupe_cluster(
    rows: Sequence[KeywordRow], cosine_threshold: float = 0.95,
) -> dict[str, str]:
    """Within a single cluster's keywords, return `{keyword_id: canonical_id}`.
    A canonical maps to itself; collapsed variants map to their group's
    canonical. Combines surface-form normalization with cosine collapse over
    the embedding (skipped when fewer than 2 rows carry one)."""
    if not rows:
        return {}

    # --- Pass 1: surface-form ---
    groups: dict[str, list[KeywordRow]] = defaultdict(list)
    for r in rows:
        sig = normalize_keyword(r.keyword) or f"\x00{r.id}"  # empty norm -> own bucket
        groups[sig].append(r)

    # `surface_canonical[id]` -> the chosen canonical for that surface-form group.
    surface_canonical: dict[str, KeywordRow] = {}
    canonical_to_group: dict[str, list[KeywordRow]] = {}
    for group in groups.values():
        winner = _pick_canonical(group)
        for r in group:
            surface_canonical[r.id] = winner
        canonical_to_group[winner.id] = group

    # --- Pass 2: cosine collapse over surface winners ---
    # Only the surviving canonicals (one per surface group) enter the cosine
    # pass; the others already have their mapping from pass 1.
    canonicals = list(canonical_to_group.keys())
    embedded = [
        c for c in canonicals
        if surface_canonical[c].embedding is not None
        and len(surface_canonical[c].embedding) > 0  # type: ignore[arg-type]
    ]

    # Union-find over surface-canonicals. Initially every canonical is its own
    # parent; cosine pairs merge them.
    parent: dict[str, str] = {c: c for c in canonicals}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str, *, prefer: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        # Make `prefer`'s root absorb the other so the winner stays the root.
        if find(prefer) == rb:
            parent[ra] = rb
        else:
            parent[rb] = ra

    if cosine_threshold < 1.0 and len(embedded) >= 2:
        vecs = np.asarray(
            [surface_canonical[c].embedding for c in embedded], dtype=np.float32,
        )
        # Pairwise cosine via normalized dot product.
        norms = np.linalg.norm(vecs, axis=1)
        safe = np.where(norms == 0, 1.0, norms)
        normed = vecs / safe[:, None]
        sims = normed @ normed.T
        n = len(embedded)
        # Walk the upper triangle; merge any pair above threshold.
        for i in range(n):
            for j in range(i + 1, n):
                if float(sims[i, j]) < cosine_threshold:
                    continue
                # Compare the CURRENT roots' winner keys, not the original
                # pair's — earlier merges may have moved one into a higher-vol
                # cluster, and we want that root to keep winning.
                ra = find(embedded[i])
                rb = find(embedded[j])
                if ra == rb:
                    continue
                preferred = ra if (
                    _winner_key(surface_canonical[ra])
                    >= _winner_key(surface_canonical[rb])
                ) else rb
                union(ra, rb, prefer=preferred)

    # Resolve each surface-canonical to its (possibly cosine-merged) root, then
    # propagate to the surface group's members.
    result: dict[str, str] = {}
    for surface_id, root in list(parent.items()):
        # find() path-compresses
        root = find(surface_id)
        # The root id is one of the surface canonicals. The actual canonical
        # keyword row may differ from `surface_canonical[surface_id]` if the
        # cosine pass merged them — propagate the root's canonical for every
        # surface-group member.
        canonical_row = surface_canonical[root]
        for member in canonical_to_group[surface_id]:
            result[member.id] = canonical_row.id

    return result


def dedupe_by_cluster(
    rows: Iterable[KeywordRow], cosine_threshold: float = 0.95,
) -> dict[str, str]:
    """Run `dedupe_cluster` independently per cluster_id. Rows with a null
    cluster_id are passed through unchanged (each is its own canonical)."""
    by_cluster: dict[str, list[KeywordRow]] = defaultdict(list)
    unclustered: list[KeywordRow] = []
    for r in rows:
        if r.cluster_id is None:
            unclustered.append(r)
        else:
            by_cluster[r.cluster_id].append(r)

    out: dict[str, str] = {r.id: r.id for r in unclustered}
    for group in by_cluster.values():
        out.update(dedupe_cluster(group, cosine_threshold=cosine_threshold))
    return out
