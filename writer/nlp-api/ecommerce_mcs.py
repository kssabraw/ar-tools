"""Max-Cosine Synthesis (MCS) for ecommerce pages.

Turns the ecommerce module's "Max-Cosine Score" from a style label into real
embedding cosine, following the on-page methodology in
``docs/sops/ecommerce-product-page-cro-seo-sop-v1_0.md`` and the SRT analysis:

  1. Capture — extract Google's live AI Overview (AIO) answer from the SERP
     items the ecommerce SERP analysis already fetches (no new paid call).
  2. Entity — derive the noun phrase the AIO answer repeatedly names, ported
     from ``pipeline-api/modules/brief/entity.py`` but adapted for commerce:
     the input product/SKU (PDP) or category (PLP) is the AUTHORITATIVE entity.
     On a PRODUCT page the AIO can NEVER override the SKU with a more-generic
     head — it may only supply the surface form + variants. On a COLLECTION
     page the AIO-derived entity is allowed, with the input category as a floor.
  3. Facts — the "points the answer actually makes" (the SRT's 95%-vs-91%
     lever: headings pair the entity with a fact the answer states, not a bare
     topic word).
  4. Synthesis — generate ``entity + fact`` candidate headings, embed them +
     the answer with Gemini (the model AIO runs on), and greedily keep the set
     that lands closest to the answer. **Phase 4 activates only when a Gemini
     embedding function is supplied** (gated on ``GEMINI_API_KEY`` at the call
     site); without it Phases 1-3 still run and headings are guided by the
     entity + facts text alone.

Pure + unit-testable: no network at import, every embedding/LLM dependency is
injected. spaCy is loaded lazily and degrades to a regex noun-phrase fallback
when the model is unavailable, so capture/facts never hard-fail on it.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# --- Tunable thresholds (mirror brief/entity.py where ported) --------------
CONFIDENCE_ACCEPT = 1.5           # winner/runner-up score ratio to accept "aio"
ENTITY_FLOOR_COSINE = 0.45        # min cosine(derived entity, input entity) — PLP
ENTITY_FLOOR_JACCARD = 0.34       # token-overlap floor when no embed_fn (PLP)
MIN_FREQUENCY_FOR_CONFIDENCE = 3  # short-answer guard
SUBJECT_WEIGHT = 1.5              # multiplier when the entity is a clause subject
GENERIC_PENALTY = 0.5            # multiplier for single-token generic heads
SYNTH_NEAR_DUP_COSINE = 0.92      # drop a candidate this close to one already kept

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]

_DETERMINERS = {
    "the", "a", "an", "this", "that", "these", "those",
    "your", "our", "their", "its", "his", "her", "my", "you", "we",
}

_NORM_PUNCT_RE = re.compile(r"[^\w\s]")
_NORM_WS_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _NORM_WS_RE.sub(" ", _NORM_PUNCT_RE.sub(" ", (text or "").lower())).strip()


def _tokens(text: str) -> set[str]:
    return set(_norm(text).split())


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _is_superset_of(candidate: str, base: str) -> bool:
    """True when `candidate` carries all of `base`'s tokens (word-order
    agnostic) — i.e. it is at least as SPECIFIC as base ("Acme Trail Runner
    shoe" ⊇ "Acme Trail Runner"). Guards PDP against generic drift."""
    tb = _tokens(base)
    return bool(tb) and tb <= _tokens(candidate)


# ---------------------------------------------------------------------------
# Phase 1 — AIO capture (ported from platform-api serp_snapshot.extract_aio)
# ---------------------------------------------------------------------------

def extract_aio(items: list[dict]) -> dict:
    """Extract the AI Overview block from a DataForSEO organic/advanced SERP
    item list. Returns ``{present, text, sources, fanout, asynchronous}``.

    Side-channel only — degrades to ``present=False`` when no ``ai_overview``
    item exists. AIO text may arrive as a top-level ``markdown`` string and/or
    ``text`` sub-items; references arrive nested or as a top-level list. When
    ``asynchronous_ai_overview`` is true only the inline text is captured (a
    follow-up /ai_overview/live fetch is intentionally out of v1 scope).
    """
    empty = {"present": False, "text": "", "sources": [], "fanout": [], "asynchronous": False}
    for item in items or []:
        if not isinstance(item, dict) or item.get("type") != "ai_overview":
            continue
        sub_items = item.get("items") or []
        texts: list[str] = []
        refs: list[dict] = [r for r in (item.get("references") or []) if isinstance(r, dict)]
        fanout: list[str] = []
        for el in sub_items:
            if not isinstance(el, dict):
                continue
            if el.get("type") == "ai_overview_reference":
                refs.append(el)
                continue
            text = (el.get("text") or "").strip()
            if text:
                texts.append(text)
            title = (el.get("title") or "").strip()
            if title.endswith("?"):
                fanout.append(title)

        markdown = (item.get("markdown") or "").strip()
        answer_text = markdown or "\n".join(texts)

        sources: list[str] = []
        for ref in refs:
            dom = (ref.get("domain") or "").strip().lower()
            if dom and dom not in sources:
                sources.append(dom)

        return {
            "present": bool(answer_text.strip()),
            "text": answer_text,
            "sources": sources,
            "fanout": fanout,
            "asynchronous": bool(item.get("asynchronous_ai_overview")),
        }
    return dict(empty)


# ---------------------------------------------------------------------------
# spaCy noun-chunking (lazy; regex fallback if the model is unavailable)
# ---------------------------------------------------------------------------

_NLP = None
_NLP_TRIED = False

_NUM_POS = {"NUM"}
_NUM_ENT = {"CARDINAL", "ORDINAL"}
_PRONOUN_POS = {"PRON"}


def _get_nlp():
    """Best-effort lazy spaCy load. Returns None (not raise) when the model is
    missing, so the caller can fall back to the regex chunker."""
    global _NLP, _NLP_TRIED
    if _NLP is not None or _NLP_TRIED:
        return _NLP
    _NLP_TRIED = True
    try:
        import spacy
        _NLP = spacy.load("en_core_web_sm")
    except Exception as exc:  # pragma: no cover - dependency/model guard
        logger.warning("spaCy en_core_web_sm unavailable for MCS entity derivation "
                        "(%s); using regex noun-phrase fallback.", exc)
        _NLP = None
    return _NLP


@dataclass
class _Occurrence:
    surface: str
    normalized: str
    head_lemma: str
    n_tokens: int
    is_subject: bool


def _domain_tokens(sources: Optional[list[str]]) -> set[str]:
    """Core token of each cited domain ('healthline.com' -> 'healthline'),
    used to keep brand/site names out of entity candidates."""
    tokens: set[str] = set()
    for dom in sources or []:
        if not dom:
            continue
        host = re.sub(r"^https?://", "", dom.strip().lower()).split("/")[0]
        parts = [p for p in host.split(".") if p not in {
            "www", "com", "org", "net", "io", "co", "uk", "gov", "edu"}]
        if parts:
            tokens.add(parts[0])
    return tokens


_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-']*")


def _extract_occurrences_regex(text: str, brand_tokens: set[str]) -> list[_Occurrence]:
    """Fallback noun-phrase extractor when spaCy is unavailable: sliding
    1-3 word windows of non-stopword tokens. Cruder than the dependency parse
    (no subject detection), but keeps entity derivation functional."""
    occ: list[_Occurrence] = []
    for raw_sent in re.split(r"[.!?\n]+", text or ""):
        words = _WORD_RE.findall(raw_sent)
        cleaned = [w for w in words if w.lower() not in _DETERMINERS]
        for n in (3, 2, 1):
            for i in range(len(cleaned) - n + 1):
                span = cleaned[i:i + n]
                low = [w.lower() for w in span]
                if any(tok in brand_tokens for tok in low):
                    continue
                surface = " ".join(span)
                normalized = " ".join(low)
                occ.append(_Occurrence(surface, normalized, low[-1], n, False))
    return occ


def _extract_occurrences(text: str, brand_tokens: set[str]) -> list[_Occurrence]:
    nlp = _get_nlp()
    if nlp is None:
        return _extract_occurrences_regex(text, brand_tokens)

    doc = nlp(text)
    occurrences: list[_Occurrence] = []
    for chunk in doc.noun_chunks:
        start, end = chunk.start, chunk.end
        # Absorb an immediately-following / preceding cardinal
        # ("angel number" + "327" -> "angel number 327").
        while end < len(doc) and (doc[end].pos_ in _NUM_POS or doc[end].ent_type_ in _NUM_ENT):
            end += 1
        while start > 0 and (doc[start - 1].pos_ in _NUM_POS or doc[start - 1].ent_type_ in _NUM_ENT):
            start -= 1
        span = doc[start:end]
        toks = list(span)
        while toks and toks[0].lower_ in _DETERMINERS:
            toks = toks[1:]
        if not toks or all(t.pos_ in _PRONOUN_POS for t in toks):
            continue
        surface = "".join(t.text_with_ws for t in toks).strip().strip(" .,:;!?\"'")
        if not surface:
            continue
        low = [t.lower_ for t in toks]
        if any(t.ent_type_ == "ORG" for t in toks) or any(tok in brand_tokens for tok in low):
            continue
        head = chunk.root
        head_lemma = head.lemma_.lower()
        normalized = " ".join(head_lemma if t == head else t.lower_ for t in toks)
        occurrences.append(_Occurrence(
            surface=surface, normalized=normalized, head_lemma=head_lemma,
            n_tokens=len(toks), is_subject=chunk.root.dep_ in {"nsubj", "nsubjpass"},
        ))
    return occurrences


# ---------------------------------------------------------------------------
# Clustering + scoring (ported)
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
        multi = {s: c for s, c in self.surface_counts.items() if len(s.split()) >= 2}
        pool = multi or self.surface_counts
        return max(pool.items(), key=lambda kv: (kv[1], len(kv[0]), kv[0]))[0]

    def score(self) -> float:
        subj = SUBJECT_WEIGHT if self.has_subject else 1.0
        specificity = GENERIC_PENALTY if self.min_tokens == 1 else 1.0
        return self.frequency * subj * specificity


def _cluster_occurrences(occurrences: list[_Occurrence]) -> list[_Cluster]:
    clusters: list[_Cluster] = []
    for occ in occurrences:
        occ_set = frozenset(occ.normalized.split())
        placed = False
        for cl in clusters:
            if cl.head_lemma != occ.head_lemma:
                continue
            cl_set = frozenset(cl.normalized.split())
            if occ_set == cl_set or occ_set <= cl_set or cl_set <= occ_set:
                cl.add(occ)
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
# Phase 2 — entity derivation (PDP-authoritative)
# ---------------------------------------------------------------------------

@dataclass
class MCSEntity:
    canonical: str
    variants: list[str] = field(default_factory=list)
    source: str = "input_fallback"   # input_pdp | aio | input_fallback
    secondary_entity: Optional[str] = None
    multi_entity_flag: bool = False
    emq_identical: bool = False
    confidence: float = 0.0

    def as_dict(self) -> dict:
        return {
            "canonical": self.canonical,
            "variants": list(self.variants),
            "source": self.source,
            "secondary_entity": self.secondary_entity,
            "multi_entity_flag": self.multi_entity_flag,
            "emq_identical": self.emq_identical,
            "confidence": self.confidence,
        }


async def _sim(a: str, b: str, embed_fn: Optional[EmbedFn]) -> float:
    """cosine(a, b) via the injected embedder, else a token-Jaccard proxy."""
    if embed_fn is None:
        return _jaccard(a, b)
    try:
        vecs = await embed_fn([a, b])
        if len(vecs) >= 2:
            return cosine(vecs[0], vecs[1])
    except Exception as exc:  # pragma: no cover - network guard
        logger.warning("MCS entity sim embedding failed (%s); using Jaccard.", exc)
    return _jaccard(a, b)


async def derive_main_entity(
    *,
    page_type: str,
    input_entity: str,
    primary_keyword: str,
    aio_text: Optional[str] = None,
    aio_sources: Optional[list[str]] = None,
    embed_fn: Optional[EmbedFn] = None,
) -> MCSEntity:
    """Derive the page's main entity.

    ``input_entity`` is the store's product/SKU (PDP) or category (PLP) name and
    is the authoritative prior. PRODUCT pages keep it as the canonical entity
    unconditionally (the AIO only contributes superset surface variants);
    COLLECTION pages may adopt an AIO-derived entity when it clears the
    similarity floor against the input category, else fall back to the input.
    Never raises on content.
    """
    input_entity = (input_entity or "").strip() or (primary_keyword or "").strip()
    is_product = (page_type or "product").lower() != "collection"

    def _emq(name: str) -> bool:
        return name.strip().lower() == (primary_keyword or "").strip().lower()

    clusters: list[_Cluster] = []
    if (aio_text or "").strip():
        brand_tokens = _domain_tokens(aio_sources)
        clusters = _cluster_occurrences(_extract_occurrences(aio_text, brand_tokens))
        clusters.sort(key=lambda c: (c.score(), c.frequency, c.canonical_surface()), reverse=True)

    # -- PRODUCT (PDP): input SKU is authoritative; AIO only adds variants -----
    if is_product:
        variants: list[str] = []
        for cl in clusters:
            surf = cl.canonical_surface()
            if _is_superset_of(surf, input_entity) and _norm(surf) != _norm(input_entity):
                variants.append(surf)
        return MCSEntity(
            canonical=input_entity,
            variants=sorted(set(variants))[:5],
            source="input_pdp",
            emq_identical=_emq(input_entity),
            confidence=1.0,
        )

    # -- COLLECTION (PLP): allow an AIO entity above the input-category floor --
    if not clusters:
        return MCSEntity(canonical=input_entity, source="input_fallback",
                         emq_identical=_emq(input_entity))

    winner = clusters[0]
    runner_up = clusters[1] if len(clusters) > 1 else None
    ratio = (winner.score() / runner_up.score()) if (runner_up and runner_up.score()) else float("inf")
    short_answer = winner.frequency < MIN_FREQUENCY_FOR_CONFIDENCE
    winner_surface = winner.canonical_surface()

    floor = ENTITY_FLOOR_COSINE if embed_fn is not None else ENTITY_FLOOR_JACCARD
    sim_to_input = await _sim(winner_surface, input_entity, embed_fn)
    if sim_to_input < floor or short_answer or ratio < CONFIDENCE_ACCEPT:
        # Too far from the category, too thin, or ambiguous → keep the input.
        return MCSEntity(
            canonical=input_entity,
            variants=[winner_surface] if _is_superset_of(winner_surface, input_entity) else [],
            source="input_fallback",
            secondary_entity=winner_surface if winner_surface != input_entity else None,
            multi_entity_flag=ratio < CONFIDENCE_ACCEPT and runner_up is not None,
            emq_identical=_emq(input_entity),
            confidence=round(sim_to_input, 4),
        )

    variants = [s for s in winner.surface_counts if s != winner_surface]
    return MCSEntity(
        canonical=winner_surface,
        variants=sorted(variants)[:5],
        source="aio",
        secondary_entity=(runner_up.canonical_surface() if runner_up else None),
        multi_entity_flag=False,
        emq_identical=_emq(winner_surface),
        confidence=round(ratio, 4) if ratio != float("inf") else float(winner.frequency),
    )


# ---------------------------------------------------------------------------
# Phase 3 — answer facts ("points the answer actually makes")
# ---------------------------------------------------------------------------

_FACT_SYSTEM = (
    "You extract the distinct factual points a source answer makes, for building "
    "SEO headings. Return ONLY a JSON array of short factual phrases (3-9 words "
    "each), each a single point the answer actually states — a claim, spec, use, "
    "or distinction. No preamble, no numbering, no duplicates, no marketing. If "
    "the answer states nothing factual, return []."
)


def build_fact_extraction_messages(aio_text: str, entity: str) -> tuple[str, str]:
    """(system, user) for the fact-extraction LLM call. Kept here (pure) so the
    Anthropic call site stays a thin wrapper and this stays unit-testable."""
    user = (
        f"MAIN ENTITY: {entity}\n\n"
        f"SOURCE ANSWER (Google AI Overview):\n\"\"\"\n{(aio_text or '').strip()}\n\"\"\"\n\n"
        "List the distinct factual points this answer makes about the main "
        "entity (or its topic), as a JSON array of short phrases. Each phrase "
        "should be pairable after the entity to form a heading "
        f"(e.g. \"{entity} <point>\"). Facts only; no fluff."
    )
    return _FACT_SYSTEM, user


def parse_facts(raw: str, *, limit: int = 12) -> list[str]:
    """Parse the fact-extraction response into a clean, deduped phrase list.
    Tolerant of a fenced/looser response: falls back to line parsing."""
    import json

    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

    facts: list[str] = []
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            arr = json.loads(text[start:end + 1])
            if isinstance(arr, list):
                facts = [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            facts = []
    if not facts:  # line fallback
        for line in text.splitlines():
            cleaned = re.sub(r'^[\s\-\*\d\.\)"]+', "", line).strip().strip('",')
            if cleaned:
                facts.append(cleaned)

    seen: set[str] = set()
    out: list[str] = []
    for f in facts:
        key = _norm(f)
        if key and key not in seen:
            seen.add(key)
            out.append(f)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Phase 4 — max-cosine heading synthesis (gated on an embed_fn)
# ---------------------------------------------------------------------------

def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


@dataclass
class ScoredHeading:
    heading: str
    cosine: float


def build_candidate_headings(entity: str, facts: list[str]) -> list[str]:
    """Deterministic candidate pool: ``entity + fact`` for each fact, plus the
    bare entity. (An LLM candidate-expansion pass is a follow-up; this keeps
    synthesis dependency-free beyond the embedder.)"""
    entity = (entity or "").strip()
    out: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        fact = (fact or "").strip().rstrip(".")
        if not fact:
            continue
        # Avoid doubling the entity if the fact already leads with it.
        head = fact if _norm(fact).startswith(_norm(entity)) else f"{entity} {fact}"
        key = _norm(head)
        if key and key not in seen:
            seen.add(key)
            out.append(head)
    return out


async def synthesize_headings(
    *,
    aio_text: str,
    entity: str,
    facts: list[str],
    embed_fn: EmbedFn,
    candidates: Optional[list[str]] = None,
    top_k: int = 8,
) -> list[ScoredHeading]:
    """Greedy max-cosine selection of a heading SET (the SRT's 'synthesis'):
    score every ``entity + fact`` candidate against the AIO answer, then keep
    the closest, skipping near-duplicates so the set spreads across the
    answer's points rather than stacking one facet. Returns [] when there is
    no answer text or no candidate survives.
    """
    pool = candidates if candidates is not None else build_candidate_headings(entity, facts)
    if not (aio_text or "").strip() or not pool:
        return []

    vecs = await embed_fn([aio_text, *pool])
    if len(vecs) < 2:
        return []
    answer_vec, cand_vecs = vecs[0], vecs[1:]

    scored = sorted(
        (ScoredHeading(h, cosine(v, answer_vec)) for h, v in zip(pool, cand_vecs)),
        key=lambda s: s.cosine, reverse=True,
    )

    kept: list[ScoredHeading] = []
    kept_vecs: list[list[float]] = []
    by_heading = {h: v for h, v in zip(pool, cand_vecs)}
    for cand in scored:
        v = by_heading[cand.heading]
        if any(cosine(v, kv) >= SYNTH_NEAR_DUP_COSINE for kv in kept_vecs):
            continue
        kept.append(cand)
        kept_vecs.append(v)
        if len(kept) >= top_k:
            break
    return kept


# ---------------------------------------------------------------------------
# Prompt block — injected into _ECOMMERCE_GEN_SYSTEM_PROMPT's user message
# ---------------------------------------------------------------------------

def build_mcs_prompt_block(
    entity: MCSEntity,
    facts: list[str],
    synthesized: Optional[list[ScoredHeading]] = None,
    noun: str = "product",
) -> str:
    """Render the MCS guidance block for the generation prompt. `noun` labels the
    subject's data/facts ("product" for ecommerce, "business" for local SEO) so
    the same engine serves both writers. Returns '' when there is nothing useful
    to inject (no facts and a plain input-fallback entity), so pages without an
    AIO behave exactly as today."""
    have_signal = bool(facts) or entity.source in ("aio",) or bool(entity.variants)
    if not have_signal:
        return ""

    lines: list[str] = [
        "MAX-COSINE TARGET (from the live Google AI Overview for this query) — "
        "use this to aim the ENTITY and HEADINGS at the answer Google already "
        "rewards. This does NOT license new facts; obey the anti-fabrication rules "
        f"above and use only provided {noun} data for specifics.",
        f"- MAIN ENTITY to repeat across H1/H2/H3 (in this surface form): \"{entity.canonical}\".",
    ]
    if entity.variants:
        lines.append("  Acceptable entity variants: " + "; ".join(f'"{v}"' for v in entity.variants) + ".")
    if entity.emq_identical:
        lines.append("  (The entity equals the target search phrase — still keep the EMQ out of subheadings; use it once in body text.)")

    if synthesized:
        lines.append(
            "- HEADINGS — use these max-cosine heading targets (entity + a point "
            f"the answer makes), adapting wording to the real {noun} facts and "
            "dropping any you cannot support truthfully:"
        )
        for s in synthesized:
            lines.append(f"    • {s.heading}")
    elif facts:
        lines.append(
            "- Build each H2/H3 as the MAIN ENTITY + one of these points the "
            f"answer actually makes (one point per heading; adapt to real {noun} "
            "facts, drop any you cannot support):"
        )
        for fact in facts:
            lines.append(f"    • {fact}")

    return "\n".join(lines) + "\n"
