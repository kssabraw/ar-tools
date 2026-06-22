"""Step 3.6 - Main-entity derivation (PRD §X.2 / §13.X.8).

Derives the single main entity - the noun phrase the AI Overview (AIO)
answer repeatedly names, in its preferred surface form - for use by the
heading-form pass (§X.4), the residual restatement gate (§X.3), and
MCS-style rephrase suggestions.

Deterministic by design: local spaCy parse + 2-3 embedding calls (against
the OpenAI key already held). No Claude/LLM in the default path, so the
output is reproducible for the same input. Never hard-fails - the title
fallback always populates `main_entity`.

This module is intentionally decoupled from the AIO-capture work (§X.1):
it takes the answer text and cited domains as plain arguments rather than
an `aio_target` model, so it can be built and tested before X.1 lands.
"""

from __future__ import annotations

import logging
import re
from typing import Awaitable, Callable, Optional

from models.brief import MainEntity

from .llm import cosine, embed_batch_large

logger = logging.getLogger(__name__)


# --- Tunable thresholds (echoed into BriefMetadata when wired) -------------
CONFIDENCE_ACCEPT = 1.5          # winner/runner-up score ratio to accept "aio"
KEYWORD_SANITY_FLOOR = 0.45      # min cosine(entity, keyword); else fall back
TITLE_TIEBREAK_MARGIN = 0.10     # "within 10%" tie on the title cosine tie-break
MIN_FREQUENCY_FOR_CONFIDENCE = 3  # short-answer guard: <3 mentions => low conf
SUBJECT_WEIGHT = 1.5             # multiplier when the entity is a clause subject
GENERIC_PENALTY = 0.5            # multiplier for single-token generic heads

_DETERMINERS = {
    "the", "a", "an", "this", "that", "these", "those",
    "your", "our", "their", "its", "his", "her", "my", "you", "we",
}

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]

# Small stopword set used only to decide whether an entity-stripped residual
# is "meaningful" (§X.3). Deliberately tiny - not general NLP stopwords.
_RESIDUAL_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "with",
    "is", "are", "what", "how", "why", "your", "you",
}

_NORM_PUNCT_RE = re.compile(r"[^\w\s]")
_NORM_WS_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _NORM_WS_RE.sub(" ", _NORM_PUNCT_RE.sub(" ", (text or "").lower())).strip()


def entity_present(text: str, canonical: str, variants: list[str]) -> bool:
    """True when `text` carries the entity. Deterministic: normalized
    substring OR entity-token-set subset of the text tokens (handles
    word-order variants like '327 angel number' vs 'angel number 327')."""
    norm_text = _norm(text)
    text_tokens = set(norm_text.split())
    for form in (canonical, *variants):
        nf = _norm(form)
        if not nf:
            continue
        if nf in norm_text:
            return True
        ftoks = set(nf.split())
        if ftoks and ftoks <= text_tokens:
            return True
    return False


def strip_entity(text: str, canonical: str, variants: list[str]) -> str:
    """Return the entity-stripped residual of `text`: its tokens minus the
    entity's tokens. Empty string when nothing meaningful remains (all
    residual tokens are stopwords) - the caller treats that as a bare
    entity restatement."""
    entity_tokens: set[str] = set()
    for form in (canonical, *variants):
        entity_tokens |= set(_norm(form).split())
    residual = [t for t in _norm(text).split() if t not in entity_tokens]
    if not residual or all(t in _RESIDUAL_STOPWORDS for t in residual):
        return ""
    return " ".join(residual)


# ---------------------------------------------------------------------------
# spaCy loading (lazy singleton)
# ---------------------------------------------------------------------------

_NLP = None


def _get_nlp():
    """Lazily load en_core_web_sm. Raises a clear error if the model is
    missing rather than failing deep inside a parse."""
    global _NLP
    if _NLP is None:
        try:
            import spacy
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "spaCy is required for main-entity derivation. "
                "Add `spacy` + the en_core_web_sm model to requirements."
            ) from exc
        try:
            _NLP = spacy.load("en_core_web_sm")
        except OSError as exc:  # pragma: no cover - model-missing guard
            raise RuntimeError(
                "spaCy model 'en_core_web_sm' is not installed. "
                "Install via the model wheel pinned in requirements.txt "
                "or `python -m spacy download en_core_web_sm`."
            ) from exc
    return _NLP


# ---------------------------------------------------------------------------
# Candidate extraction
# ---------------------------------------------------------------------------

class _Occurrence:
    """One noun-chunk mention in the answer."""

    __slots__ = ("surface", "normalized", "head_lemma", "n_tokens", "is_subject")

    def __init__(self, surface: str, normalized: str, head_lemma: str,
                 n_tokens: int, is_subject: bool):
        self.surface = surface
        self.normalized = normalized
        self.head_lemma = head_lemma
        self.n_tokens = n_tokens
        self.is_subject = is_subject


_NUM_POS = {"NUM"}
_NUM_ENT = {"CARDINAL", "ORDINAL"}
_PRONOUN_POS = {"PRON"}


def _domain_tokens(cited_domains: Optional[list[str]]) -> set[str]:
    """Core token of each cited domain, e.g. 'healthline.com' -> 'healthline'.
    Used to exclude brand/site names from entity candidates."""
    tokens: set[str] = set()
    for dom in cited_domains or []:
        if not dom:
            continue
        host = re.sub(r"^https?://", "", dom.strip().lower()).split("/")[0]
        parts = [p for p in host.split(".") if p not in {"www", "com", "org",
                 "net", "io", "co", "uk", "gov", "edu"}]
        if parts:
            tokens.add(parts[0])
    return tokens


def _extract_occurrences(doc, brand_tokens: set[str]) -> list[_Occurrence]:
    """Noun-chunk the doc into entity-candidate occurrences.

    Handles three things the raw `noun_chunks` iterator gets wrong for our
    purposes:
      - trailing/leading cardinal numbers split off the chunk
        ("The angel number" + "327" -> "angel number 327")
      - leading determiners/possessives ("your crystals" -> "crystals")
      - pronoun and brand/ORG chunks are not candidates
    """
    occurrences: list[_Occurrence] = []
    for chunk in doc.noun_chunks:
        start, end = chunk.start, chunk.end

        # Absorb an immediately-following number ("angel number" + "327").
        while end < len(doc) and (
            doc[end].pos_ in _NUM_POS or doc[end].ent_type_ in _NUM_ENT
        ):
            end += 1
        # Absorb an immediately-preceding number ("327" + "angel number").
        while start > 0 and (
            doc[start - 1].pos_ in _NUM_POS or doc[start - 1].ent_type_ in _NUM_ENT
        ):
            start -= 1

        span = doc[start:end]
        tokens = list(span)

        # Strip leading determiners / possessives.
        while tokens and tokens[0].lower_ in _DETERMINERS:
            tokens = tokens[1:]
        if not tokens:
            continue

        # Drop pure-pronoun chunks ("it", "them", "they").
        if all(t.pos_ in _PRONOUN_POS for t in tokens):
            continue

        surface = "".join(
            t.text_with_ws for t in tokens
        ).strip()
        surface = surface.strip(" .,:;!?\"'")
        if not surface:
            continue

        lower_tokens = [t.lower_ for t in tokens]
        # Brand/site exclusion: any ORG token, or a token matching a cited
        # domain's core name ("Healthline" repeated doesn't make it ours).
        if any(t.ent_type_ == "ORG" for t in tokens):
            continue
        if brand_tokens and any(tok in brand_tokens for tok in lower_tokens):
            continue

        head = chunk.root
        head_lemma = head.lemma_.lower()
        # Normalized form for counting: lowercase tokens, head lemmatized.
        norm_tokens = [
            head_lemma if t == head else t.lower_ for t in tokens
        ]
        normalized = " ".join(norm_tokens)
        is_subject = chunk.root.dep_ in {"nsubj", "nsubjpass"}

        occurrences.append(_Occurrence(
            surface=surface,
            normalized=normalized,
            head_lemma=head_lemma,
            n_tokens=len(tokens),
            is_subject=is_subject,
        ))
    return occurrences


# ---------------------------------------------------------------------------
# Clustering + scoring
# ---------------------------------------------------------------------------

class _Cluster:
    def __init__(self, normalized: str, head_lemma: str):
        self.normalized = normalized
        self.head_lemma = head_lemma
        self.occurrences: list[_Occurrence] = []
        self.surface_counts: dict[str, int] = {}

    def add(self, occ: _Occurrence) -> None:
        self.occurrences.append(occ)
        self.surface_counts[occ.surface] = self.surface_counts.get(occ.surface, 0) + 1

    @property
    def frequency(self) -> int:
        return len(self.occurrences)

    @property
    def has_subject(self) -> bool:
        return any(o.is_subject for o in self.occurrences)

    @property
    def min_tokens(self) -> int:
        return min(o.n_tokens for o in self.occurrences)

    def canonical_surface(self) -> str:
        # Most frequent raw surface form, but never a bare generic head when
        # a modified (multi-token) surface exists in the cluster. Subset
        # merging ("benefits" -> "magnesium glycinate benefits") otherwise
        # lets the frequent bare head win and re-introduces the exact failure
        # mode the specificity penalty exists to kill. Ties broken by length
        # then alpha for determinism.
        multi = {s: c for s, c in self.surface_counts.items() if len(s.split()) >= 2}
        pool = multi or self.surface_counts
        return max(pool.items(), key=lambda kv: (kv[1], len(kv[0]), kv[0]))[0]

    def score(self) -> float:
        freq = self.frequency
        subj = SUBJECT_WEIGHT if self.has_subject else 1.0
        # Generic single-token head with no modifier ("number", "benefits").
        specificity = GENERIC_PENALTY if self.min_tokens == 1 else 1.0
        return freq * subj * specificity


def _token_set(normalized: str) -> frozenset[str]:
    return frozenset(normalized.split())


def _cluster_occurrences(occurrences: list[_Occurrence]) -> list[_Cluster]:
    """Merge normalized forms that are token-set equal, or where one is a
    strict superstring of the other with the same head lemma."""
    clusters: list[_Cluster] = []
    for occ in occurrences:
        occ_set = _token_set(occ.normalized)
        placed = False
        for cl in clusters:
            if cl.head_lemma != occ.head_lemma:
                continue
            cl_set = _token_set(cl.normalized)
            if occ_set == cl_set or occ_set <= cl_set or cl_set <= occ_set:
                cl.add(occ)
                # Keep the longer normalized form as the cluster label.
                if len(occ_set) > len(cl_set):
                    cl.normalized = occ.normalized
                placed = True
                break
        if not placed:
            new = _Cluster(occ.normalized, occ.head_lemma)
            new.add(occ)
            clusters.append(new)
    return clusters


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _sentence_count(doc) -> int:
    return sum(1 for _ in doc.sents)


async def _cosine_to(text: str, target: str, embed_fn: EmbedFn) -> float:
    vecs = await embed_fn([text, target])
    if len(vecs) < 2:
        return 0.0
    return cosine(vecs[0], vecs[1])


async def _title_fallback(
    *, title: str, primary_keyword: str, embed_fn: EmbedFn,
    confidence: float, multi_entity_flag: bool, secondary_entity: Optional[str],
) -> MainEntity:
    """Highest-keyword-cosine noun chunk of the title. Always succeeds:
    Step 3.5 titles contain the keyword, so at least one chunk exists; if
    parsing yields nothing we fall back to the keyword itself."""
    nlp = _get_nlp()
    doc = nlp(title)
    occs = _extract_occurrences(doc, brand_tokens=set())
    candidates = list({o.surface for o in occs}) or [primary_keyword]

    best, best_cos = candidates[0], -1.0
    if len(candidates) == 1:
        best = candidates[0]
    else:
        vecs = await embed_fn(candidates + [primary_keyword])
        kw_vec = vecs[-1]
        for cand, vec in zip(candidates, vecs[:-1]):
            c = cosine(vec, kw_vec)
            if c > best_cos:
                best, best_cos = cand, c

    emq_identical = best.strip().lower() == primary_keyword.strip().lower()
    return MainEntity(
        canonical=best,
        variants=[c for c in candidates if c != best],
        secondary_entity=secondary_entity,
        source="title_fallback",
        confidence=confidence,
        multi_entity_flag=multi_entity_flag,
        emq_identical=emq_identical,
    )


async def derive_main_entity(
    *,
    primary_keyword: str,
    title: str,
    aio_answer_text: Optional[str] = None,
    aio_cited_domains: Optional[list[str]] = None,
    aio_present: bool = False,
    embed_fn: Optional[EmbedFn] = None,
) -> MainEntity:
    """Derive `main_entity`. Never raises on content; degrades to the title
    fallback on AIO absence, low confidence, or sanity-check failure.

    `embed_fn` is injectable for deterministic testing; defaults to
    text-embedding-3-large.
    """
    embed = embed_fn or embed_batch_large

    if not (aio_present and (aio_answer_text or "").strip()):
        return await _title_fallback(
            title=title, primary_keyword=primary_keyword, embed_fn=embed,
            confidence=0.0, multi_entity_flag=False, secondary_entity=None,
        )

    nlp = _get_nlp()
    doc = nlp(aio_answer_text)
    brand_tokens = _domain_tokens(aio_cited_domains)
    occurrences = _extract_occurrences(doc, brand_tokens)
    clusters = _cluster_occurrences(occurrences)

    if not clusters:
        return await _title_fallback(
            title=title, primary_keyword=primary_keyword, embed_fn=embed,
            confidence=0.0, multi_entity_flag=False, secondary_entity=None,
        )

    clusters.sort(key=lambda c: (c.score(), c.frequency, c.canonical_surface()),
                  reverse=True)
    winner = clusters[0]
    runner_up = clusters[1] if len(clusters) > 1 else None

    ratio = (winner.score() / runner_up.score()) if (runner_up and runner_up.score()) else float("inf")
    short_answer = _sentence_count(doc) < 3 or winner.frequency < MIN_FREQUENCY_FOR_CONFIDENCE
    high_confidence = ratio >= CONFIDENCE_ACCEPT and not short_answer

    winner_surface = winner.canonical_surface()

    if not high_confidence:
        # Low-confidence path: multi-entity. Tie-break by title cosine when a
        # genuine runner-up exists; otherwise fall back to the title.
        if runner_up is None:
            return await _title_fallback(
                title=title, primary_keyword=primary_keyword, embed_fn=embed,
                confidence=ratio if ratio != float("inf") else 0.0,
                multi_entity_flag=True, secondary_entity=winner_surface,
            )
        runner_surface = runner_up.canonical_surface()
        w_cos = await _cosine_to(winner_surface, title, embed)
        r_cos = await _cosine_to(runner_surface, title, embed)
        # Within margin => can't separate them; fall back to the title.
        if abs(w_cos - r_cos) <= TITLE_TIEBREAK_MARGIN:
            return await _title_fallback(
                title=title, primary_keyword=primary_keyword, embed_fn=embed,
                confidence=ratio, multi_entity_flag=True,
                secondary_entity=runner_surface,
            )
        if r_cos > w_cos:
            winner, runner_up = runner_up, winner
            winner_surface, runner_surface = runner_surface, winner_surface
        # Sanity-check the chosen winner below; carry multi-entity context.
        sanity = await _cosine_to(winner_surface, primary_keyword, embed)
        if sanity < KEYWORD_SANITY_FLOOR:
            return await _title_fallback(
                title=title, primary_keyword=primary_keyword, embed_fn=embed,
                confidence=ratio, multi_entity_flag=True,
                secondary_entity=runner_surface,
            )
        return _build_aio_entity(
            winner=winner, primary_keyword=primary_keyword, confidence=ratio,
            multi_entity_flag=True, secondary_entity=runner_surface,
        )

    # High-confidence path - still run the keyword sanity check.
    sanity = await _cosine_to(winner_surface, primary_keyword, embed)
    if sanity < KEYWORD_SANITY_FLOOR:
        return await _title_fallback(
            title=title, primary_keyword=primary_keyword, embed_fn=embed,
            confidence=ratio if ratio != float("inf") else 0.0,
            multi_entity_flag=False, secondary_entity=None,
        )

    return _build_aio_entity(
        winner=winner, primary_keyword=primary_keyword,
        confidence=ratio if ratio != float("inf") else float(winner.frequency),
        multi_entity_flag=False, secondary_entity=None,
    )


def _build_aio_entity(
    *, winner: _Cluster, primary_keyword: str, confidence: float,
    multi_entity_flag: bool, secondary_entity: Optional[str],
) -> MainEntity:
    canonical = winner.canonical_surface()
    variants = [s for s in winner.surface_counts if s != canonical]
    return MainEntity(
        canonical=canonical,
        variants=sorted(variants),
        secondary_entity=secondary_entity,
        source="aio",
        confidence=round(confidence, 4) if confidence != float("inf") else confidence,
        multi_entity_flag=multi_entity_flag,
        emq_identical=canonical.strip().lower() == primary_keyword.strip().lower(),
    )
