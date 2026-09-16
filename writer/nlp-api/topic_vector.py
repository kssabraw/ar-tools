"""Topic-Vector Centering + Information Gain — P0 (report-only).

Implements the P0 subset of
``docs/modules/topic-vector-information-gain-plan-v1_0.md``:

  1. **Topic centering** — cosine(page, centroid) where the centroid is anchored
     on the EXPLICIT query only: query terms + AIO text + top-10 competitor
     headings (§4). Reported as a drift signal; NOT fed into the reopt loop.
  2. **Per-subtopic coverage** — cluster the competitor headings (top-10 +
     qualifying 11-20) into subtopics, embed each, take the page's
     best-matching-section cosine per cluster; report covered/missing (§5).
  3. **Inverse gain gap** — the on-vector subtopics the competitor corpus states
     that the page lacks (§6, "inverse — reported, not scored"). Grounded purely
     in what competitors demonstrably said — no site index, no fabrication risk.

Design constraints honoured here (plan §9/§3/§4/§6/§10):

- This runs as a SEPARATE async measure BESIDE ``_compute_serp_signal_coverage``
  — never folded into it. It emits its own report; the deterministic engine is
  left byte-for-byte untouched.
- Gated on ``GEMINI_API_KEY`` at the call site: without an embedder the measure
  is SKIPPED (``available: False``), never defaulted to a number.
- The implied query is NOT in the centroid (that lives one layer down as
  coverage-checklist items — a P1 concern; P0's centroid is query + AIO +
  top-10 headings only).
- AIO is often absent: the centroid then falls back to query + top-10 headings,
  and centering is only comparable within the same AIO-availability. The output
  carries ``aio_present`` + a comparability note so a caller never ranks an
  AIO-present score against an AIO-absent one.
- MCS-first: centering + coverage are the spine; nothing soft/emotional in P0.

Pure + unit-testable: no network at import, the embedding dependency is
injected (the same Gemini ``EmbedFn`` that MCS uses), and ``cosine`` is reused
from ``ecommerce_mcs``. BeautifulSoup is imported lazily inside the one
HTML-parsing helper so the pure math imports offline.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from ecommerce_mcs import EmbedFn, cosine  # reuse — do NOT re-implement

logger = logging.getLogger(__name__)

# --- Tunable thresholds (calibrate from real runs, like every floor here) ----
# A subtopic is "on-vector" when its label embeds within this cosine of the
# centroid — off-vector subtopics (vendor-trust boilerplate) never count as an
# information-gain gap (§10 "centering gates gain").
CENTERING_FLOOR = float(os.environ.get("TOPIC_VECTOR_CENTERING_FLOOR", "0.45"))
# The page "covers" a subtopic when its best-matching section embeds at least
# this close to the subtopic label. Below it → a coverage gap.
COVERAGE_FLOOR = float(os.environ.get("TOPIC_VECTOR_COVERAGE_FLOOR", "0.55"))
# The ≥2-page-spread guard for the 11-20 tier so page-2 junk can't leak in (§3).
TIER2_MIN_PAGE_SPREAD = int(os.environ.get("TOPIC_VECTOR_TIER2_MIN_SPREAD", "2"))
# Greedy single-link clustering merges two headings whose content-token sets are
# at least this Jaccard-similar.
CLUSTER_JACCARD = float(os.environ.get("TOPIC_VECTOR_CLUSTER_JACCARD", "0.5"))
# Bounds on the embedding batch (report-only cost the deterministic engine never
# carried — keep it small).
MAX_SUBTOPICS = int(os.environ.get("TOPIC_VECTOR_MAX_SUBTOPICS", "15"))
MAX_SECTIONS = int(os.environ.get("TOPIC_VECTOR_MAX_SECTIONS", "40"))
_SECTION_CHARS = 1500
_PAGE_CHARS = 6000
TOP10_RANK = 10  # rank ≤ this = consensus tier; (10, 20] = differentiation tier

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-']*")

# Content-free words dropped before clustering / token comparison. Deliberately
# small: articles, prepositions, aux verbs, and a few heading-generic words.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "for", "to", "in", "on", "at",
    "by", "with", "from", "as", "is", "are", "be", "was", "were", "been", "it",
    "its", "this", "that", "these", "those", "your", "our", "their", "my", "you",
    "we", "how", "what", "why", "when", "where", "which", "who", "do", "does",
    "can", "will", "vs", "versus", "about", "into", "per", "not", "no", "yes",
    "best", "top", "guide", "overview", "more", "all", "any", "get", "use",
}

# Bare site-chrome headings that are sections, not subtopics. Umbrella "FAQ"
# headings are dropped (their child H3 questions ARE real subtopics and survive).
_CHROME_HEADINGS = {
    "faq", "faqs", "frequently asked questions", "reviews", "customer reviews",
    "related products", "you may also like", "related", "newsletter",
    "sign up", "subscribe", "cart", "my account", "categories", "share",
    "recently viewed", "contact us", "about us", "menu", "search",
    "add a review", "leave a review", "comments",
}

_NORM_PUNCT_RE = re.compile(r"[^\w\s]")
_NORM_WS_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _NORM_WS_RE.sub(" ", _NORM_PUNCT_RE.sub(" ", (text or "").lower())).strip()


def _content_tokens(text: str) -> set:
    return {t for t in _WORD_RE.findall((text or "").lower())
            if t not in _STOPWORDS and len(t) >= 3}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_topical_heading(text: str) -> bool:
    """A heading is a candidate subtopic when it isn't bare site-chrome and it
    carries at least one content token (so "Details", "127" or a lone stopword
    string never becomes a subtopic)."""
    key = _norm(text)
    if not key or key in _CHROME_HEADINGS or len(key) < 3:
        return False
    return bool(_content_tokens(text))


# ---------------------------------------------------------------------------
# SERP-rank tiering of the ALREADY-scraped competitor headings (§3)
# ---------------------------------------------------------------------------

def build_heading_tiers(
    h2_per_page: list,
    h3_per_page: list,
    page_ranks: list,
    top_n: int = TOP10_RANK,
) -> dict:
    """Partition the already-scraped competitor headings by SERP rank into the
    consensus (top-10) and differentiation-within-reach (11-20) tiers (§3). This
    is a re-partition of pages we ALREADY fetched — no extra network.

    ``h2_per_page``/``h3_per_page`` are per-page heading lists (index-aligned);
    ``page_ranks`` is the 1-based SERP rank of each scraped page (same order).
    A page's headings = its H2s + H3s. Within a tier, a heading's ``page_spread``
    is the number of that tier's pages carrying it (deduped per page). The 11-20
    tier applies the ≥2-page-spread guard so page-2 junk can't leak in.

    Returns ``{top10_headings, tier2_headings, top10_pages, tier2_pages}`` where
    each ``*_headings`` is a list of ``{text, page_spread}`` (topical only).
    """
    top10_spread: dict = {}
    tier2_spread: dict = {}
    top10_canon: dict = {}
    tier2_canon: dict = {}
    top10_pages = 0
    tier2_pages = 0

    n = min(len(page_ranks), len(h2_per_page), len(h3_per_page))
    for i in range(n):
        rank = page_ranks[i]
        if rank <= top_n:
            spread, canon = top10_spread, top10_canon
            top10_pages += 1
        elif rank <= 2 * top_n:
            spread, canon = tier2_spread, tier2_canon
            tier2_pages += 1
        else:
            continue
        seen_this_page: set = set()
        for h in list(h2_per_page[i] or []) + list(h3_per_page[i] or []):
            if not _is_topical_heading(h):
                continue
            key = _norm(h)
            if key in seen_this_page:
                continue
            seen_this_page.add(key)
            spread[key] = spread.get(key, 0) + 1
            canon.setdefault(key, h.strip())

    top10 = [{"text": top10_canon[k], "page_spread": v}
             for k, v in sorted(top10_spread.items(), key=lambda kv: -kv[1])]
    tier2 = [{"text": tier2_canon[k], "page_spread": v}
             for k, v in sorted(tier2_spread.items(), key=lambda kv: -kv[1])
             if v >= TIER2_MIN_PAGE_SPREAD]
    return {
        "top10_headings": top10,
        "tier2_headings": tier2,
        "top10_pages": top10_pages,
        "tier2_pages": tier2_pages,
    }


# ---------------------------------------------------------------------------
# Subtopic clustering (deterministic, pure)
# ---------------------------------------------------------------------------

@dataclass
class Subtopic:
    label: str                 # representative heading (most specific member)
    tier: str                  # "top10" (consensus) | "tier2" (differentiation)
    members: list = field(default_factory=list)
    page_spread: int = 0       # summed spread across member headings
    tokens: set = field(default_factory=set)


def _heading_entries(top10: list, tier2: list) -> list:
    """Normalise the tier heading lists (each a list of ``{text, page_spread}``
    or bare strings) into ``(text, tier, page_spread)`` tuples, topical only."""
    out = []
    for items, tier in ((top10 or [], "top10"), (tier2 or [], "tier2")):
        for it in items:
            if it is None:
                continue  # a None entry must not become a "None" garbage subtopic
            if isinstance(it, dict):
                text, spread = it.get("text", ""), int(it.get("page_spread", 1) or 1)
            else:
                text, spread = str(it), 1
            if _is_topical_heading(text):
                out.append((text.strip(), tier, spread))
    return out


def cluster_headings(top10: list, tier2: list, *, jaccard: float = CLUSTER_JACCARD,
                     limit: int = MAX_SUBTOPICS) -> list:
    """Greedy single-link clustering of competitor headings into subtopics by
    content-token Jaccard. Deterministic (no embeddings — clusters are then
    embedded downstream for the coverage cosine). A cluster is ``top10`` if any
    member came from the consensus tier, else ``tier2``. The label is the most
    token-rich member (most specific). Sorted by prevalence (summed page-spread),
    capped at ``limit``.
    """
    entries = _heading_entries(top10, tier2)
    clusters: list = []
    for text, tier, spread in entries:
        toks = _content_tokens(text)
        if not toks:
            continue
        best = None
        best_sim = 0.0
        for cl in clusters:
            sim = _jaccard(toks, cl.tokens)
            if sim > best_sim:
                best_sim, best = sim, cl
        if best is not None and best_sim >= jaccard:
            best.members.append(text)
            best.page_spread += spread
            best.tokens |= toks
            if tier == "top10":
                best.tier = "top10"
            # Promote the label to the most token-rich (most specific) member.
            if len(_content_tokens(text)) > len(_content_tokens(best.label)):
                best.label = text
        else:
            clusters.append(Subtopic(label=text, tier=tier, members=[text],
                                     page_spread=spread, tokens=set(toks)))

    clusters.sort(key=lambda c: (-c.page_spread, -len(c.members), c.label))
    return clusters[:limit]


# ---------------------------------------------------------------------------
# Centroid + page text assembly (pure)
# ---------------------------------------------------------------------------

def build_centroid_component_texts(query: str, aio_text: str,
                                   top10_heading_texts: list) -> list:
    """The centroid's component strings (§4): the explicit query, the AIO answer
    (when present), and the top-10 competitor headings joined. Each is embedded
    separately and mean-pooled into the centroid vector — the implied query is
    deliberately absent. Empty components are dropped.
    """
    comps: list = []
    if (query or "").strip():
        comps.append(query.strip())
    if (aio_text or "").strip():
        comps.append(aio_text.strip()[:_PAGE_CHARS])
    joined = " . ".join(h for h in (top10_heading_texts or []) if (h or "").strip())
    if joined.strip():
        comps.append(joined[:_PAGE_CHARS])
    return comps


def mean_vector(vectors: list) -> list:
    """Mean-pool L2-normalised vectors into a centroid. Skips empty/zero vectors
    and any vector whose dimensionality doesn't match the first usable one (a
    uniform embedder never trips this, but it removes a latent IndexError);
    returns [] when nothing usable is supplied."""
    usable: list = []
    for v in vectors or []:
        if not v:
            continue
        norm = sum(x * x for x in v) ** 0.5
        if norm == 0.0:
            continue
        unit = [x / norm for x in v]
        if usable and len(unit) != len(usable[0]):
            continue
        usable.append(unit)
    if not usable:
        return []
    dim = len(usable[0])
    return [sum(v[i] for v in usable) / len(usable) for i in range(dim)]


# ---------------------------------------------------------------------------
# HTML → page sections (lazy bs4)
# ---------------------------------------------------------------------------

def extract_sections(html: str, *, limit: int = MAX_SECTIONS) -> list:
    """Split a page into heading-anchored sections for per-subtopic coverage:
    the lead text before the first heading, then one section per H1-H4 (its
    heading + the text up to the next heading). Each section is capped; the whole
    list is capped at ``limit``. Returns [] on empty content."""
    from bs4 import BeautifulSoup  # lazy — keep the pure math importable offline

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    sections: list = []
    cur_head: Optional[str] = None
    cur_parts: list = []

    def _flush():
        text = ((cur_head or "") + ". " + " ".join(cur_parts)).strip(" .")
        if text:
            sections.append(text[:_SECTION_CHARS])

    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th",
                             "blockquote"]):
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if el.name in ("h1", "h2", "h3", "h4"):
            if cur_head is not None or cur_parts:
                _flush()
            cur_head, cur_parts = txt, []
        else:
            cur_parts.append(txt)
    if cur_head is not None or cur_parts:
        _flush()

    if not sections:  # no structured blocks — fall back to the whole text
        whole = soup.get_text(" ", strip=True)
        if whole:
            sections.append(whole[:_SECTION_CHARS])
    return sections[:limit]


def build_page_text(page_title: str, sections: list) -> str:
    """The page's centering string. Leads with the title (the heaviest single
    signal for a "buy" query — §4a) then the section text, bounded."""
    body = " ".join(sections or [])
    title = (page_title or "").strip()
    return (f"{title}. {body}" if title else body)[:_PAGE_CHARS]


# ---------------------------------------------------------------------------
# Coverage + on-vector verdicts from embeddings (pure)
# ---------------------------------------------------------------------------

def coverage_verdicts(
    subtopics: list,
    subtopic_vecs: list,
    section_vecs: list,
    centroid_vec: list,
    *,
    coverage_floor: float = COVERAGE_FLOOR,
    centering_floor: float = CENTERING_FLOOR,
) -> list:
    """Per-subtopic coverage + on-vector verdicts. For each subtopic: its best
    section cosine (covered when ≥ coverage_floor) and whether it is on-vector
    (its label cosine to the centroid ≥ centering_floor). Pure — every vector is
    supplied by the caller."""
    out = []
    for st, sv in zip(subtopics, subtopic_vecs):
        best = max((cosine(sv, secv) for secv in section_vecs), default=0.0)
        on_vec = cosine(sv, centroid_vec) >= centering_floor if centroid_vec else False
        out.append({
            "label": st.label,
            "tier": st.tier,
            "page_spread": st.page_spread,
            "best_cosine": round(best, 4),
            "covered": best >= coverage_floor,
            "on_vector": on_vec,
        })
    return out


# ---------------------------------------------------------------------------
# Orchestrator — the one place embeddings are fetched (async, best-effort)
# ---------------------------------------------------------------------------

async def measure(
    *,
    embed_fn: Optional[EmbedFn],
    query: str,
    page_title: str,
    page_html: str,
    aio_present: bool,
    aio_text: str,
    top10_headings: list,
    tier2_headings: list,
    centering_floor: float = CENTERING_FLOOR,
    coverage_floor: float = COVERAGE_FLOOR,
) -> dict:
    """Run the P0 topic-vector measure. Report-only — the caller attaches the
    result beside the composite; it is never folded into the score.

    Degrades explicitly (never a misleading number):
      - no ``embed_fn`` (GEMINI_API_KEY absent) → ``{available: False, reason:
        "gemini_key_absent"}``
      - no competitor headings → ``{available: False, reason:
        "no_competitor_headings"}``
      - an embedding failure / short batch → ``{available: False, reason:
        "embed_failed" | "embed_incomplete"}``
    """
    if embed_fn is None:
        return {"available": False, "reason": "gemini_key_absent"}

    top10_texts = [
        (h.get("text") if isinstance(h, dict) else str(h))
        for h in (top10_headings or [])
        if _is_topical_heading(h.get("text") if isinstance(h, dict) else str(h))
    ]
    subtopics = cluster_headings(top10_headings or [], tier2_headings or [])
    centroid_texts = build_centroid_component_texts(
        query, aio_text if aio_present else "", top10_texts)

    if not subtopics and not centroid_texts:
        return {"available": False, "reason": "no_competitor_headings"}

    sections = extract_sections(page_html)
    page_text = build_page_text(page_title, sections)
    if not page_text.strip():
        return {"available": False, "reason": "empty_page"}
    if not centroid_texts:
        return {"available": False, "reason": "empty_centroid"}

    labels = [st.label for st in subtopics]
    # One batched embedding call: page, centroid components, subtopic labels,
    # page sections — sliced back out in that order.
    batch = [page_text] + centroid_texts + labels + sections
    try:
        vecs = await embed_fn(batch)
    except Exception as exc:  # pragma: no cover - network guard
        logger.warning("topic-vector embedding failed (%s); skipping measure.", exc)
        return {"available": False, "reason": "embed_failed"}
    if not vecs or len(vecs) != len(batch):
        return {"available": False, "reason": "embed_incomplete"}

    idx = 0
    page_vec = vecs[idx]; idx += 1
    centroid_vecs = vecs[idx:idx + len(centroid_texts)]; idx += len(centroid_texts)
    subtopic_vecs = vecs[idx:idx + len(labels)]; idx += len(labels)
    section_vecs = vecs[idx:idx + len(sections)]

    centroid_vec = mean_vector(centroid_vecs)
    if not centroid_vec:
        return {"available": False, "reason": "empty_centroid"}

    centering_cos = cosine(page_vec, centroid_vec)
    verdicts = coverage_verdicts(
        subtopics, subtopic_vecs, section_vecs, centroid_vec,
        coverage_floor=coverage_floor, centering_floor=centering_floor,
    )

    covered = [v for v in verdicts if v["covered"]]
    missing = [v for v in verdicts if not v["covered"]]
    # Inverse gain gap (§6): on-vector subtopics the corpus states that the page
    # lacks. Grounded in what competitors demonstrably said — no fabrication risk.
    # Consensus (top-10) gaps are table-stakes; tier-2 gaps are differentiation.
    inverse = sorted(
        (v for v in missing if v["on_vector"]),
        key=lambda v: (0 if v["tier"] == "top10" else 1, v["best_cosine"]),
    )

    return {
        "available": True,
        "aio_present": bool(aio_present),
        # Centering is only comparable across pages with the SAME AIO
        # availability — never rank an AIO-present score against an AIO-absent
        # one on one scale (§4).
        "comparability_note": (
            "Centering is comparable only within the same AIO availability "
            f"(this run: aio_present={bool(aio_present)})."
        ),
        "centering": {
            "cosine": round(centering_cos, 4),
            "score": round(max(0.0, centering_cos) * 100, 1),  # 0-100, report-only
            "on_vector": centering_cos >= centering_floor,
            "centroid_components": {
                "query": bool((query or "").strip()),
                "aio": bool(aio_present and (aio_text or "").strip()),
                "top10_headings": len(top10_texts),
            },
        },
        "coverage": {
            "subtopics": verdicts,
            "covered_count": len(covered),
            "missing_count": len(missing),
            "total": len(verdicts),
        },
        "inverse_gain_gap": inverse,
        "thresholds": {
            "centering_floor": centering_floor,
            "coverage_floor": coverage_floor,
        },
        "note": (
            "P0 report-only — NOT folded into the composite and NOT fed to the "
            "reopt loop. Centering is a coarse drift gauge; the actionable detail "
            "is per-subtopic coverage + the inverse gain gap."
        ),
    }
