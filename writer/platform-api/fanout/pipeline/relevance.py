"""Relevance gate + dedup + junk filter (PRD §7.6).

Every candidate keyword is checked against its parent topic's embedding by
cosine similarity. This is the pipeline's volume control point — and the step
that finally sorts the seed-level keyword pool (suggestions/fan-outs were fanned
to every silo in §7.3) into the silo each keyword actually belongs to.

- Cross-source dedup happens upstream: the per-topic pools are keyed by the
  normalized keyword, so duplicate surfacings already merged while preserving
  source attribution. Here we only score and classify.
- Embedding dedup happens here: because the seed-level pool fans the same
  keyword into many silos, we embed each *unique* keyword once across all silos
  (not once per silo) and reuse the vector.
- Junk filter (cheap, pre-embedding): blocked tokens + length sanity.
- Language filter (optional, pre-embedding): when a `language_filter` callable
  is supplied, every unique keyword is run through a real language ID model
  (see `app/pipeline/language.py`) and tagged `filtered_language` if it's
  confidently not English. Catches non-English Latin-script phrases that
  DataForSEO leaks past its en/US locale lock and that the cosine gate would
  otherwise accept (their English content embeds close to English).
- Relevance: cosine >= threshold (default 0.62) -> active, else
  filtered_relevance. Junk -> filtered_junk. Nothing is deleted; failures are
  tagged and stored for v1 calibration.

Resilience: a per-batch embedding failure (or a short/mismatched batch) degrades
only that batch's keywords — they're kept `active` and unscored — rather than
aborting the whole run. Embeddings for surviving keywords are returned so the
clustering step (§7.9) can reuse them rather than re-embedding.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

# Blocked tokens (PRD §7.6): unambiguously off-niche / adult / spam terms that
# are junk regardless of the seed. Kept deliberately tight — topical filtering is
# the relevance gate's job, so words that are legitimate in some niches (e.g.
# "sex" for sexual-health, "bet"/"slots" in other contexts) are NOT blocked here
# to avoid false positives. Brand-name detection (the third §7.6 sub-rule) needs
# a brand DB and is left out of v1.
_BLOCKED_TOKENS = frozenset({
    "porn", "porno", "pornography", "xxx", "nsfw", "casino", "casinos",
    "gambling", "viagra", "cialis",
})
# Platform / forum / social intent (PRD §7.6 junk): a keyword that names a
# discussion platform or social network signals the searcher wants *that
# platform's* threads/videos, not an authority-site article — so an info site
# never targets it. Whole-word match (so "redditor" or a brand containing these
# substrings is unaffected). Owner-chosen set; extend here if more surface.
_PLATFORM_TOKENS = frozenset({
    "reddit", "quora", "forum", "forums", "youtube", "tiktok", "facebook",
})
_MIN_CHARS = 2
_MAX_WORDS = 12

_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class GatedKeyword:
    keyword: str
    sources: list[str]
    status: str  # 'active' | 'filtered_relevance' | 'filtered_junk' | 'filtered_language'
    relevance_score: float | None = None
    embedding: list[float] | None = None  # kept only for scored 'active' (for §7.9)


@dataclass
class RelevanceResult:
    # topic_id -> list of classified keywords
    per_topic: dict[str, list[GatedKeyword]] = field(default_factory=dict)
    degraded_notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"active": 0, "filtered_relevance": 0,
               "filtered_junk": 0, "filtered_language": 0}
        for kws in self.per_topic.values():
            for k in kws:
                out[k.status] = out.get(k.status, 0) + 1
        return out


_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _has_dated_year(keyword: str, current_year: int) -> bool:
    """True when `keyword` contains a 4-digit year (20XX) strictly before
    `current_year` AND no year >= current_year. Used by the junk filter to
    drop keywords whose intent has aged out ("best vpn 2024", "trends 2023")
    while preserving comparisons that name both a past and the current year
    ("ipad 2024 vs 2026") and forward-looking phrases ("2027 predictions")."""
    years = [int(m) for m in _YEAR_RE.findall(keyword)]
    if not years:
        return False
    return any(y < current_year for y in years) and not any(y >= current_year for y in years)


def _is_junk(keyword: str, current_year: int) -> bool:
    if len(keyword) < _MIN_CHARS:
        return True
    words = _WORD_RE.findall(keyword)
    if not words or len(words) > _MAX_WORDS:
        return True
    if any(w in _BLOCKED_TOKENS or w in _PLATFORM_TOKENS for w in words):
        return True
    return _has_dated_year(keyword, current_year)


def _term_pattern(terms: list[str] | None):
    """Whole-word alternation regex for a list of seed/peer terms, or None."""
    cleaned = [re.escape(t.strip().lower()) for t in (terms or []) if t and t.strip()]
    if not cleaned:
        return None
    return re.compile(r"\b(?:" + "|".join(cleaned) + r")\b")


def _off_niche(keyword: str, seed_pat, peer_pat) -> bool:
    """Generic peer-entity filter (PRD §5.1, §7.6): a keyword is off-niche if it
    names a peer entity (competitor/sibling) but not the seed (or an alias). Seed-
    agnostic — the seed/peer term lists are supplied per-seed (LLM-generated at
    grounding), so this works for any subject. A keyword that names both the seed
    and a peer (e.g. "tirzepatide vs retatrutide") is kept as a legit comparison."""
    if peer_pat is None:
        return False
    if seed_pat is not None and seed_pat.search(keyword):
        return False
    return bool(peer_pat.search(keyword))


def _cosine_to_anchor(vectors: np.ndarray, anchor: np.ndarray) -> np.ndarray:
    """Cosine similarity of each row in `vectors` to `anchor`. Zero vectors yield 0."""
    anchor_norm = np.linalg.norm(anchor)
    if anchor_norm == 0:
        return np.zeros(vectors.shape[0])
    row_norms = np.linalg.norm(vectors, axis=1)
    safe = np.where(row_norms == 0, 1.0, row_norms)
    sims = (vectors @ anchor) / (safe * anchor_norm)
    return np.where(row_norms == 0, 0.0, sims)


def _embed_unique(
    keywords: list[str], embed_fn, batch_size: int
) -> tuple[dict[str, np.ndarray], bool]:
    """Embed each keyword once. Returns (keyword -> vector, degraded?). A failed
    or count-mismatched batch is skipped (those keywords get no vector); it never
    raises, so a transient embedding error can't abort the pipeline."""
    out: dict[str, np.ndarray] = {}
    degraded = False
    for start in range(0, len(keywords), batch_size):
        batch = keywords[start : start + batch_size]
        try:
            vectors = embed_fn(batch)
        except Exception as exc:  # noqa: BLE001 — degrade this batch, keep going
            degraded = True
            logger.warning(
                "degraded",
                extra={"event": "degraded", "step": "relevance_gate",
                       "phase": "embed", "reason": str(exc)},
            )
            continue
        if len(vectors) != len(batch):
            # Never zip-truncate silently: drop the whole batch and degrade.
            degraded = True
            logger.warning(
                "degraded",
                extra={"event": "degraded", "step": "relevance_gate", "phase": "embed",
                       "reason": f"embedding count mismatch ({len(vectors)} != {len(batch)})"},
            )
            continue
        arr = np.asarray(vectors, dtype=np.float32)
        for kw, row in zip(batch, arr):
            out[kw] = row.copy()
    return out, degraded


def run_relevance_gate(
    *,
    per_topic: dict[str, dict[str, list[str]]],
    topic_embeddings: dict[str, list[float] | None],
    embed_fn,
    topic_names: dict[str, str] | None = None,
    threshold: float = 0.62,
    batch_size: int = 1000,
    seed_terms: list[str] | None = None,
    peer_terms: list[str] | None = None,
    assign_best_silo: bool = False,
    llm_router=None,
    llm_router_margin: float = 0.04,
    current_year: int | None = None,
    language_filter: Callable[[str], bool] | None = None,
) -> RelevanceResult:
    """Classify every keyword in `per_topic` as active / filtered_relevance /
    filtered_junk. `embed_fn(list[str]) -> list[list[float]]` embeds keywords.
    A topic with no embedding can't be scored — its keywords are kept active
    (score null) and the run is flagged degraded for that silo.

    `seed_terms` (seed + aliases) and `peer_terms` (competitor/sibling entities)
    drive the generic peer-entity filter: a keyword naming a peer but not the
    seed is tagged filtered_junk (off-niche). Both are seed-agnostic lists."""
    result = RelevanceResult()
    topic_names = topic_names or {}
    seed_pat = _term_pattern(seed_terms)
    peer_pat = _term_pattern(peer_terms)
    # `current_year` drives the past-year junk filter. Default to the calendar
    # year at gate-call time (read here, not at module import, so a long-lived
    # worker spanning a year boundary sees the new year on its next run).
    if current_year is None:
        current_year = datetime.now(timezone.utc).year

    # 1. Junk + language filter per topic; collect the unique non-filtered
    #    keywords to embed. Only embed keywords that belong to at least one topic
    #    that HAS an embedding (a keyword living only in unembeddable silos is
    #    never scored). Language detection is per *unique* keyword — same
    #    string in many silos is detected once.
    junk_by_topic: dict[str, list[GatedKeyword]] = {}
    lang_by_topic: dict[str, list[GatedKeyword]] = {}
    cands_by_topic: dict[str, list[tuple[str, list[str]]]] = {}
    unique: dict[str, None] = {}  # insertion-ordered unique keyword set
    lang_cache: dict[str, bool] = {}

    def _is_non_english(kw: str) -> bool:
        if language_filter is None:
            return False
        cached = lang_cache.get(kw)
        if cached is None:
            try:
                cached = bool(language_filter(kw))
            except Exception:  # noqa: BLE001 — never abort the gate on a detector blow-up
                cached = False
            lang_cache[kw] = cached
        return cached

    for tid, pool in per_topic.items():
        has_anchor = bool(topic_embeddings.get(tid))
        junk: list[GatedKeyword] = []
        lang: list[GatedKeyword] = []
        cands: list[tuple[str, list[str]]] = []
        for kw, sources in pool.items():
            srt = sorted(sources)
            if _is_junk(kw, current_year) or _off_niche(kw, seed_pat, peer_pat):
                junk.append(GatedKeyword(kw, srt, "filtered_junk"))
            elif _is_non_english(kw):
                lang.append(GatedKeyword(kw, srt, "filtered_language"))
            else:
                cands.append((kw, srt))
                if has_anchor:
                    unique.setdefault(kw, None)
        junk_by_topic[tid] = junk
        lang_by_topic[tid] = lang
        cands_by_topic[tid] = cands

    # 2. Embed every unique keyword once (dedup across silos), resilient to
    #    per-batch failures.
    emb_by_kw, embed_degraded = _embed_unique(list(unique), embed_fn, batch_size)
    if embed_degraded:
        result.degraded_notes.append(
            "Some keywords could not be scored for relevance (embedding service "
            "degraded); they were kept active."
        )

    # 2b. Lever 3: assign each keyword to its single best silo (argmax cosine to
    #     the silo's anchor) among the silos it appears in. A keyword fanned to
    #     many silos then lands in exactly one — no cross-silo duplicate articles.
    #     Scored against its assigned silo; elsewhere it's filtered_relevance.
    best_topic_for_kw: dict[str, str] = {}
    if assign_best_silo and emb_by_kw:
        # Pre-normalize anchors once so per-keyword cosine is a single dot product.
        anchor_vecs = {}
        for tid, a in topic_embeddings.items():
            if a:
                v = np.asarray(a, dtype=np.float64)
                n = np.linalg.norm(v) or 1.0
                anchor_vecs[tid] = v / n
        cand_topics: dict[str, list[str]] = {}
        for tid, cands in cands_by_topic.items():
            if tid in anchor_vecs:
                for kw, _ in cands:
                    if kw in emb_by_kw:
                        cand_topics.setdefault(kw, []).append(tid)
        # Retain per-keyword per-silo cosines so we can identify ambiguous routing
        # (top-1 vs top-2 margin) for the optional LLM second-pass.
        kw_scores: dict[str, dict[str, float]] = {}
        for kw, tids in cand_topics.items():
            e = emb_by_kw[kw]
            e_n = np.linalg.norm(e) or 1.0
            scores = {tid: float(np.dot(e, anchor_vecs[tid]) / e_n) for tid in tids}
            kw_scores[kw] = scores
            best_topic_for_kw[kw] = max(scores, key=scores.get)

        # LLM second-pass: re-route keywords where the top-2 cosine margin is
        # below the threshold (genuinely ambiguous — embeddings can't decide).
        # The router enforces "LLM may pick only from this keyword's candidate
        # silos"; anything else is ignored and the cosine pick stands.
        if llm_router and kw_scores:
            ambiguous: list[tuple[str, list[str]]] = []
            for kw, scores in kw_scores.items():
                if len(scores) < 2:
                    continue
                sorted_vals = sorted(scores.values(), reverse=True)
                margin = sorted_vals[0] - sorted_vals[1]
                if margin < llm_router_margin:
                    cands_by_score = [
                        tid for tid, _ in sorted(scores.items(), key=lambda x: -x[1])
                    ]
                    ambiguous.append((kw, cands_by_score))
            if ambiguous:
                try:
                    reroutes = llm_router(ambiguous)
                except Exception as exc:  # noqa: BLE001 — fall back to cosine
                    logger.warning(
                        "llm_router_failed",
                        extra={"event": "llm_router_failed", "reason": repr(exc)},
                    )
                    reroutes = {}
                for kw, new_tid in reroutes.items():
                    if new_tid in kw_scores.get(kw, {}):
                        best_topic_for_kw[kw] = new_tid

    # 3. Score per topic against that topic's own anchor.
    for tid, cands in cands_by_topic.items():
        classified: list[GatedKeyword] = (
            list(junk_by_topic[tid]) + list(lang_by_topic[tid])
        )
        anchor = topic_embeddings.get(tid)

        if not anchor:
            if cands:
                label = topic_names.get(tid) or tid
                result.degraded_notes.append(
                    f"Relevance gate skipped for silo “{label}”: no topic embedding."
                )
            for kw, sources in cands:
                classified.append(GatedKeyword(kw, sources, "active"))
            result.per_topic[tid] = classified
            continue

        anchor_vec = np.asarray(anchor, dtype=np.float64)
        scorable = [(kw, src, emb_by_kw[kw]) for kw, src in cands if kw in emb_by_kw]
        # Candidates whose batch failed to embed: keep active, unscored.
        for kw, src in cands:
            if kw not in emb_by_kw:
                classified.append(GatedKeyword(kw, src, "active"))

        if scorable:
            vectors = np.asarray([e for _, _, e in scorable], dtype=np.float64)
            sims = _cosine_to_anchor(vectors, anchor_vec)
            for (kw, src, emb), sim in zip(scorable, sims):
                score = float(sim)
                # Lever 3: only the keyword's best silo can hold it active.
                if assign_best_silo and best_topic_for_kw.get(kw, tid) != tid:
                    classified.append(
                        GatedKeyword(kw, src, "filtered_relevance", relevance_score=score)
                    )
                elif score >= threshold:
                    classified.append(
                        GatedKeyword(kw, src, "active",
                                     relevance_score=score, embedding=emb.tolist())
                    )
                else:
                    classified.append(
                        GatedKeyword(kw, src, "filtered_relevance", relevance_score=score)
                    )
        result.per_topic[tid] = classified

    counts = result.counts()
    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "relevance_gate",
               "active": counts["active"],
               "filtered_relevance": counts["filtered_relevance"],
               "filtered_junk": counts["filtered_junk"],
               "filtered_language": counts["filtered_language"],
               "unique_embedded": len(emb_by_kw),
               "language_filter": language_filter is not None,
               "threshold": threshold},
    )
    return result
