"""Topic-Vector Centering + Information Gain — P0 + P1 + P2 (report-only).

Implements the P0 subset + the P1 scored Information Gain + the P2 emotional-arc
rubric of ``docs/modules/topic-vector-information-gain-plan-v1_0.md``:

  1. **Topic centering** — cosine(page, centroid) where the centroid is anchored
     on the EXPLICIT query only: query terms + AIO text + top-10 competitor
     headings (§4). Reported as a drift signal; NOT fed into the reopt loop.
  2. **Per-subtopic coverage** — cluster the competitor headings (top-10 +
     qualifying 11-20) into subtopics, embed each, take the page's
     best-matching-section cosine per cluster; report covered/missing (§5).
  3. **Inverse gain gap** — the on-vector subtopics the competitor corpus states
     that the page lacks (§6, "inverse — reported, not scored"). Grounded purely
     in what competitors demonstrably said — no site index, no fabrication risk.
  4. **Emotional-arc rubric (P2)** — an LLM rubric dimension (NOT embedding-based,
     never in the cosine): does the page move THIS client's buyer from an anxious
     "before" to a confident "after", per the voice card's audience fields (§10a)?
     Pure assembly + sanitize here; the one Haiku call lives in ``main.py``. The
     SUBORDINATE TAIL — composite weight 0, never folded into ``scores``.

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

# --- Tunable thresholds (CALIBRATED from a live gemini-embedding-2 run) -------
# Calibration basis (Nova "buy retatrutide" run, 2026-09-16): gemini-embedding-2
# whole-doc + section↔subtopic cosines run HIGH and COMPRESSED — the Nova drift
# page centred 0.747, a strong on-vector competitor PDP 0.845 (separation held,
# ~0.10), and per-subtopic best-section cosines clustered 0.67–0.81 with no clean
# covered/missing gap. So the P0 floors (0.45 / 0.55) marked everything "on-vector"
# and "covered". Raised here to sit inside the observed band; still env-overridable.
#
# A subtopic is "on-vector" when its label embeds within this cosine of the
# centroid — off-vector subtopics (vendor-trust boilerplate) never count as an
# information-gain gap (§10 "centering gates gain").
CENTERING_FLOOR = float(os.environ.get("TOPIC_VECTOR_CENTERING_FLOOR", "0.60"))
# The page "covers" a subtopic when its best-matching section embeds at least
# this close to the subtopic label. Below it → a coverage gap. Calibrated to 0.70
# to sit inside gemini-embedding-2's compressed cosine band, so a well-covered
# page shows few/no gaps and a thin one surfaces its weak subtopics (the P0 0.55
# floor marked everything "covered"). The inverse-gain gap is the on-vector
# subtopics below this absolute floor — no relative fallback (it over-fired on
# well-covered pages and was removed).
COVERAGE_FLOOR = float(os.environ.get("TOPIC_VECTOR_COVERAGE_FLOOR", "0.70"))
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

# --- Information Gain (P1) thresholds (calibrate on real runs) ---------------
# A page claim counts as gain only if ALL three hold (§6): on-vector (clears
# CENTERING_FLOOR vs the centroid), RARE in the top-10 (its max cosine to any
# competitor subtopic is BELOW this ceiling — i.e. far from the consensus), and
# SITE-GROUNDED (embeds within GAIN_GROUNDING_FLOOR of a site-claim phrase, OR a
# numeric/price value it states appears in a site fact). Ungrounded novelty
# scores ZERO and is flagged — the anti-fabrication guard.
GAIN_RARITY_CEILING = float(os.environ.get("TOPIC_VECTOR_GAIN_RARITY_CEILING", "0.72"))
GAIN_GROUNDING_FLOOR = float(os.environ.get("TOPIC_VECTOR_GAIN_GROUNDING_FLOOR", "0.78"))
# ≈ this many on-vector + rare + grounded claims = full marks on realized gain.
GAIN_TARGET = int(os.environ.get("TOPIC_VECTOR_GAIN_TARGET", "3"))
# Below this many site-claim phrases (and no typed facts) the index is "thin" →
# gain is SUPPRESSED ("not measured"), never scored 0 (§6).
GAIN_MIN_SITE_CLAIMS = int(os.environ.get("TOPIC_VECTOR_GAIN_MIN_SITE_CLAIMS", "3"))
MAX_PAGE_CLAIMS = int(os.environ.get("TOPIC_VECTOR_MAX_PAGE_CLAIMS", "25"))
MAX_SITE_CLAIMS = int(os.environ.get("TOPIC_VECTOR_MAX_SITE_CLAIMS", "60"))
# Composite weight of the gain score — kept ZERO (§6 "low/zero composite weight",
# so the reopt loop never builds a fabrication incentive as a gain quota). Gain
# is report-only + coached into reopt as guidance; it never enters the composite.
GAIN_COMPOSITE_WEIGHT = 0.0

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
# Page-claim extraction — the unit of Information Gain (§6)
# ---------------------------------------------------------------------------

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
# A claim is substantive when it carries a factual signal — a number, unit, %,
# degree, or a currency amount. Bleached marketing prose carries none.
_FACT_SIGNAL_RE = re.compile(r"\d|%|°|\$")
_NUM_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?")
# Site-chrome/boilerplate sentences that carry a stray number (an age-gate,
# a cart/discount popup, a blog-index "N min read" blurb) pass the fact-signal
# gate but are NOT product claims. Left in, they corrupt Information Gain: a
# live Nova run credited "I acknowledge that I am age 21 or older." as a
# realized gain (it self-grounds against the same chrome in the site index).
# html_to_text strips nav/footer/header/form TAGS; this catches the modal/popup
# chrome that lives in ordinary <div>s. Kept deliberately narrow so a real
# product claim can never match. Must stay in sync with the platform-api
# site-claim extractor (services/site_claim_index.py::_CHROME_CLAIM_RE).
_CHROME_CLAIM_RE = re.compile(
    r"(?:"
    r"add(?:ed)?\s+to\s+cart|your\s+cart\s+is\s+empty|cart\s+total|check\s+out\s+our\s+shop|"
    r"close\s+cart|view\s+cart|"
    r"i\s+acknowledge\s+that\s+i\s+am|are\s+you\s+(?:18|21)|age\s+verification|"
    r"\d+\s*%\s*off|off\s+your\s+first\s+order|discount\s+code|"
    r"\d+\s*min\s+read|read\s+article|"
    r"uncategorized"
    r")",
    re.IGNORECASE,
)


def extract_page_claims(sections: list, *, limit: int = MAX_PAGE_CLAIMS,
                        min_words: int = 6, max_words: int = 45) -> list:
    """Split the page's sections into candidate CLAIM sentences (the gain unit).
    Keeps only fact-bearing sentences (a number/%/°/$), deduped, capped. Mirrors
    the platform-api site-claim extractor so a page claim and a site claim are
    the same kind of object (name-agnostic, no LLM)."""
    out: list = []
    seen: set = set()
    for sec in sections or []:
        for raw in _SENT_SPLIT_RE.split(sec or ""):
            sent = _NORM_WS_RE.sub(" ", (raw or "")).strip()
            words = sent.split()
            if not (min_words <= len(words) <= max_words):
                continue
            if not _FACT_SIGNAL_RE.search(sent):
                continue
            if _CHROME_CLAIM_RE.search(sent):  # drop age-gate/cart/popup chrome
                continue
            key = re.sub(r"[^a-z0-9]+", " ", sent.lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(sent)
            if len(out) >= limit:
                return out
    return out


def _site_claim_texts(site_claim_index: Optional[dict], *, limit: int = MAX_SITE_CLAIMS) -> list:
    """The site-claim phrases to embed for the fuzzy grounding path."""
    if not isinstance(site_claim_index, dict):
        return []
    out: list = []
    for c in (site_claim_index.get("claims") or [])[:limit]:
        if isinstance(c, dict):
            t = (c.get("text") or "").strip()
        else:
            t = str(c).strip()
        if t:
            out.append(t[:_SECTION_CHARS])
    return out


def _site_fact_values(site_claim_index: Optional[dict]) -> set:
    """Normalised numeric/price values the site's typed facts assert — the exact-
    match grounding fast path (a claim stating '$90' or '99%' or a CAS number the
    site also lists is site-grounded even if its prose embeds far from any site
    claim phrase)."""
    vals: set = set()
    if not isinstance(site_claim_index, dict):
        return vals
    for f in site_claim_index.get("facts") or []:
        if not isinstance(f, dict):
            continue
        v = str(f.get("value") or "").strip().lower()
        if v:
            vals.add(v)
            for n in _NUM_TOKEN_RE.findall(v):
                vals.add(n)
    return vals


def _index_is_thin(site_claim_index: Optional[dict], min_claims: int) -> bool:
    """Thin/absent → SUPPRESS the gain score ('not measured'), never 0 (§6).
    Thin = fewer than ``min_claims`` claim phrases AND no typed facts."""
    if not isinstance(site_claim_index, dict):
        return True
    claims = site_claim_index.get("claims") or []
    facts = site_claim_index.get("facts") or []
    return len(claims) < max(1, min_claims) and not facts


def _claim_value_grounded(claim: str, site_values: set) -> bool:
    """True when a distinctive value the claim states (a CAS number, a price, a
    percentage, a molecular weight) is one the site also asserts. Bare small
    integers (sizes like '10') are ignored — too common to be grounding."""
    if not site_values:
        return False
    low = (claim or "").lower()
    for n in _NUM_TOKEN_RE.findall(low):
        # Only distinctive numbers ground: ≥3 digits, or a decimal, or a value
        # the site lists verbatim with its unit context.
        if (len(n) >= 3 or "." in n) and n in site_values:
            return True
    return False


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
# Measure 3 — Information Gain (the scored one, §6). Pure.
# ---------------------------------------------------------------------------

def information_gain_verdicts(
    page_claims: list,
    page_claim_vecs: list,
    subtopic_vecs: list,
    centroid_vec: list,
    site_claim_vecs: list,
    site_values: set,
    *,
    centering_floor: float = CENTERING_FLOOR,
    rarity_ceiling: float = GAIN_RARITY_CEILING,
    grounding_floor: float = GAIN_GROUNDING_FLOOR,
) -> list:
    """Per page-claim gain verdict (§6). A claim is `realized` gain iff it is
    on-vector AND rare in the top-10 AND site-grounded. On-vector + rare but
    NOT grounded is `ungrounded_novelty` — scored zero and FLAGGED (the anti-
    fabrication guard). Pure — every vector is supplied by the caller.

    Rarity is judged on the claim's cosine to the competitor SUBTOPIC vectors
    (name-agnostic predicate matching, reusing embeddings already computed for
    coverage) — a v1 approximation of §6's claim-level page-spread that needs no
    per-competitor claim inventory."""
    out = []
    for text, cv in zip(page_claims, page_claim_vecs):
        on_vec = (cosine(cv, centroid_vec) >= centering_floor) if centroid_vec else False
        max_comp = max((cosine(cv, sv) for sv in subtopic_vecs), default=0.0)
        rare = max_comp < rarity_ceiling
        max_site = max((cosine(cv, gv) for gv in site_claim_vecs), default=0.0)
        grounded = (max_site >= grounding_floor) or _claim_value_grounded(text, site_values)
        realized = bool(on_vec and rare and grounded)
        ungrounded = bool(on_vec and rare and not grounded)
        out.append({
            "claim": text[:240],
            "on_vector": on_vec,
            "rare": rare,
            "grounded": grounded,
            "realized_gain": realized,
            "ungrounded_novelty": ungrounded,
            "competitor_cosine": round(max_comp, 4),
            "site_cosine": round(max_site, 4),
        })
    return out


def score_information_gain(claim_verdicts: list, coverage_verdicts: list,
                           *, target: int = GAIN_TARGET) -> dict:
    """Assemble the 0–100 gain score from the per-claim verdicts + the tier-2
    (differentiation-within-reach) coverage (§6). Report-only.

    - realized_gain — count of on-vector + rare + site-grounded page claims,
      normalised to `target` (≈3 grounded differentiating facts = full marks).
    - captured_differentiation — of the tier-2 subtopics, how many the page
      covers (from the already-computed coverage verdicts).
    Combined 60/40 into `score`. Ungrounded-novelty claims are counted + listed
    as a fabrication-risk flag (scored zero, never credited)."""
    realized = [c for c in claim_verdicts if c.get("realized_gain")]
    ungrounded = [c for c in claim_verdicts if c.get("ungrounded_novelty")]
    tier2 = [v for v in coverage_verdicts if v.get("tier") == "tier2"]
    tier2_covered = [v for v in tier2 if v.get("covered")]

    realized_component = min(1.0, len(realized) / max(1, target))
    captured_ratio = (len(tier2_covered) / len(tier2)) if tier2 else 0.0
    # No tier-2 differentiation opportunities on the SERP → the captured-diff
    # dimension is N/A; lean the score entirely on realized gain rather than
    # penalising a page for a differentiation lane that doesn't exist.
    if tier2:
        score = round((0.60 * realized_component + 0.40 * captured_ratio) * 100, 1)
    else:
        score = round(realized_component * 100, 1)

    return {
        "score": score,
        "realized_gain_count": len(realized),
        "realized_gain_target": target,
        "captured_differentiation": len(tier2_covered),
        "differentiation_available": len(tier2),
        "ungrounded_novelty_count": len(ungrounded),
        "realized_claims": [c["claim"] for c in realized][:8],
        # The fabrication-risk surface: novel on-vector claims NOT found on the
        # client's own site. Never credited; flagged for a human.
        "ungrounded_claims": [c["claim"] for c in ungrounded][:8],
        "composite_weight": GAIN_COMPOSITE_WEIGHT,
    }


# Fact TYPES safe to PUSH onto a specific page as "state this" coaching. The
# site-claim index is CLIENT-level (the whole site — every product + blog), but
# the coaching pushes a fact onto ONE page. For a multi-product client (e.g. a
# peptide vendor selling dozens of compounds) the per-product / per-compound /
# transactional facts belong to some OTHER page: a `size` mined from a
# semaglutide comparison blog, a `cas` from a different compound, or a
# transactional `price`, coached onto a retatrutide PDP is a factual error, not
# fabrication-prevention. So coaching pushes only the QUALITY & HANDLING facts a
# vendor asserts SITE-WIDE (a CoA policy, a purity standard, storage temps) —
# never the IDENTITY / COMMERCE facts that are page-specific. (The scored-gain
# GROUNDING path is unaffected: it corroborates the page's OWN claims against the
# index, which is safe for every fact type — see _claim_value_grounded.)
_COACHABLE_FACT_TYPES = frozenset({"coa", "purity", "storage_temp"})


def render_gain_guidance(measure_result: dict, site_claim_index: Optional[dict] = None,
                         page_text: str = "") -> str:
    """A compact rewrite-prompt block coaching the reopt loop (§6/§9): cover the
    under-served on-vector subtopics, and STATE the specific site-grounded facts
    the page is missing. Returns '' when there's nothing actionable — so the
    reopt prompt is byte-identical when the measure is unavailable/thin.

    Only ever coaches facts the client's OWN site asserts (from the passed index)
    that aren't already on the page — never an invented addition (§10)."""
    if not isinstance(measure_result, dict) or not measure_result.get("available"):
        return ""
    lines: list = []

    gaps = measure_result.get("inverse_gain_gap") or []
    if gaps:
        lines.append("UNDER-SERVED ON-VECTOR SUBTOPICS — cover these more directly "
                     "(competitors rank on them and your page is thin here):")
        for g in gaps[:6]:
            lines.append(f"  - {g.get('label','')}")

    # Missing site-grounded facts: real facts on the client's own site the page
    # doesn't currently state (deterministic string check — anti-fabrication).
    low_page = (page_text or "").lower()
    missing: list = []
    for f in ((site_claim_index or {}).get("facts") or []):
        if not isinstance(f, dict):
            continue
        # Only push SITE-INVARIANT fact types (see _COACHABLE_FACT_TYPES) — never
        # a per-product size / per-compound CAS / transactional price scraped from
        # a different page of a multi-product site.
        if str(f.get("type") or "").strip().lower() not in _COACHABLE_FACT_TYPES:
            continue
        val = str(f.get("value") or "").strip()
        if not val:
            continue
        if val.lower() not in low_page:
            unit = str(f.get("unit") or "").strip()
            missing.append(f"{f.get('type','fact')}: {val}{(' ' + unit) if unit else ''}".strip())
        if len(missing) >= 8:
            break
    if missing:
        lines.append("VERIFIABLE FACTS FROM YOUR OWN SITE the page omits — state these "
                     "(number-entity facts; do NOT invent any not listed here):")
        lines += [f"  - {m}" for m in missing]

    if not lines:
        return ""
    return ("TOPIC & INFORMATION-GAIN GUIDANCE (report-only signal — improve where it "
            "does not conflict with the SEO deficiencies or brand voice above):\n"
            + "\n".join(lines))


# ---------------------------------------------------------------------------
# Measure 4 — Emotional-arc rubric (P2, §10a). The subordinate tail.
# ---------------------------------------------------------------------------
# Report-only LLM rubric dimension: does the page move THIS client's buyer from
# an anxious "before" to a confident "after"? The states come from the client's
# ALREADY auto-generated voice card (§10a) — no new audience source:
#   before = audience_pain_points + audience_objections + audience_triggers
#   after  = audience_motivations satisfied + objections answered
# Affect is NOT embeddable (embeddings capture topic, not feeling), so this is
# deliberately NOT in the cosine — it rides BESIDE centering/coverage/gain on
# the report-only ``topic_vector`` field at composite weight 0, and is never
# added to ``scores``. MCS-first: the arc is the SUBORDINATE TAIL, never a heavy
# signal — over-indexing it recreates Nova's failure in reverse (a warm page
# that's off-vector and doesn't rank).
#
# Split of responsibility (mirrors ``voice_card.py`` / ``ecommerce_facts.py``):
#   - everything here is pure + unit-tested (state assembly, prompt, sanitize)
#   - the one cheap Haiku forced-tool call lives in ``main.py::_measure_emotional_arc``
#
# Governance: gated on availability — no voice card / no audience fields →
# SUPPRESSED ("not measured", ``suppressed_arc``), never scored 0. Every string
# the arc surfaces is scrubbed of ``never_use_terms`` (§10b / non-negotiable): a
# forbidden word never appears in any arc verdict, evidence, or rationale.

ARC_COMPOSITE_WEIGHT = 0.0  # NEVER folded into `scores` — report-only (§10a).
MAX_ARC_TRANSITIONS = int(os.environ.get("TOPIC_VECTOR_ARC_MAX_TRANSITIONS", "8"))
_ARC_PAGE_CHARS = int(os.environ.get("TOPIC_VECTOR_ARC_PAGE_CHARS", "9000"))
# A "yes" verdict needs a page quote at least this long to count as evidenced —
# a bare "" or a stray character is an unfounded verdict and is dropped.
_ARC_MIN_EVIDENCE_CHARS = int(os.environ.get("TOPIC_VECTOR_ARC_MIN_EVIDENCE", "10"))

_ARC_AUDIENCE_FIELDS = ("audience_pain_points", "audience_objections",
                        "audience_triggers", "audience_motivations")


def _arc_list(card: Optional[dict], key: str, cap: int = 6) -> list:
    """One audience field as a deduped, capped, bounded list of strings. A
    non-list field (a stray string on a hand-crafted card) yields [] rather than
    char-iterating — the parsed voice card always gives lists, this is defence."""
    vals = card.get(key) if isinstance(card, dict) else None
    out: list = []
    seen: set = set()
    for v in (vals if isinstance(vals, list) else []):
        s = str(v).strip()
        low = s.lower()
        if s and low not in seen:
            seen.add(low)
            out.append(s[:240])
        if len(out) >= cap:
            break
    return out


def build_arc_states(voice_card: Optional[dict]) -> dict:
    """The before/after emotional states from the voice card's audience fields
    (§10a). ``before`` = pains + objections + triggers; ``after`` = motivations
    (+ the objections answered). Pure; returns the four deduped lists plus the
    audience label — reuses the client's ALREADY auto-generated card, inventing
    no new audience source."""
    card = voice_card if isinstance(voice_card, dict) else {}
    return {
        "audience_label": str(card.get("audience_label") or "").strip()[:200],
        "pains": _arc_list(card, "audience_pain_points"),
        "objections": _arc_list(card, "audience_objections"),
        "triggers": _arc_list(card, "audience_triggers"),
        "motivations": _arc_list(card, "audience_motivations"),
    }


def has_arc_inputs(voice_card: Optional[dict]) -> bool:
    """True when the card carries at least one audience signal to build an arc
    from. When False the arc is SUPPRESSED ("not measured"), never scored 0 —
    no input, no verdict (§10a subordinate-tail)."""
    st = build_arc_states(voice_card)
    return bool(st["pains"] or st["objections"] or st["triggers"] or st["motivations"])


def suppressed_arc(reason: str) -> dict:
    """The 'not measured' arc sub-object (never scored 0, §10a). Used for no
    audience fields, a disabled flag, or an LLM/parse failure."""
    return {"available": False, "reason": reason, "composite_weight": ARC_COMPOSITE_WEIGHT}


ARC_SYSTEM = (
    "You are a conversion copy analyst. You judge ONLY whether a web page moves a "
    "specific buyer from their anxious 'before' state to a confident 'after' state. "
    "You never rewrite, prescribe, or invent — you assess what the page already does. "
    "Judge strictly from the PAGE TEXT provided: cite a VERBATIM quote from the page "
    "for every 'yes' verdict, and mark 'no' with an empty quote when the page does not "
    "address a concern. A page that is fluent but never speaks to THIS buyer's specific "
    "worries scores low, however polished it reads. Call the emit_emotional_arc tool "
    "with your assessment."
)

# Forced-tool schema — the arc's structured output (per-transition evidence
# quotes + a 0-100 arc score). Kept as module data so the pure sanitizer and the
# main.py call site agree on the shape.
ARC_TOOL = {
    "name": "emit_emotional_arc",
    "description": (
        "Report whether the page performs this buyer's before->after emotional "
        "transition, with a verbatim page quote as evidence for every 'yes'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "arc_present": {
                "type": "boolean",
                "description": "Does the page perform any before->after emotional transition for this buyer at all?",
            },
            "before_acknowledged": {
                "type": "boolean",
                "description": "Does the page acknowledge this buyer's anxious 'before' state (their pains/worries/triggers)?",
            },
            "before_evidence": {
                "type": "string",
                "description": "A VERBATIM quote from the page that acknowledges the before-state; empty string if none.",
            },
            "after_resolved": {
                "type": "boolean",
                "description": "Does the page deliver the confident 'after' state (this buyer's motivations satisfied)?",
            },
            "after_evidence": {
                "type": "string",
                "description": "A VERBATIM quote from the page that delivers the after-state; empty string if none.",
            },
            "transitions": {
                "type": "array",
                "description": "One entry per specific concern (a pain or objection) this buyer holds. Set addressed=true ONLY with a verbatim page quote that answers it.",
                "items": {
                    "type": "object",
                    "properties": {
                        "concern": {"type": "string", "description": "The buyer concern, restated from the list provided."},
                        "addressed": {"type": "boolean"},
                        "evidence": {"type": "string", "description": "VERBATIM page quote answering the concern; empty string if not addressed."},
                    },
                    "required": ["concern", "addressed", "evidence"],
                },
            },
            "score": {
                "type": "number",
                "description": "0-100: how completely the page moves THIS buyer from before to after. 0 = ignores them entirely; 100 = acknowledges and resolves every concern.",
            },
            "rationale": {"type": "string", "description": "One or two sentences on the verdict."},
        },
        "required": ["arc_present", "before_acknowledged", "after_resolved", "transitions", "score"],
    },
}


def build_arc_prompt(states: dict, page_text: str) -> str:
    """User prompt for the arc call. Pure so tests can assert that the audience
    signals AND the page text both reach the model."""
    def _blk(title: str, items: list) -> str:
        body = "\n".join(f"    - {i}" for i in items) if items else "    (none stated)"
        return f"  {title}:\n{body}"

    states = states if isinstance(states, dict) else {}
    parts = [
        "THIS PAGE'S BUYER (from the client's brand/ICP guide):",
        f"  Who they are: {states.get('audience_label') or '(unspecified)'}",
        "",
        "THE 'BEFORE' STATE — what makes this buyer anxious / hesitant / searching:",
        _blk("Pain points", states.get("pains") or []),
        _blk("Objections (why they hesitate)", states.get("objections") or []),
        _blk("Triggers (what makes them search now)", states.get("triggers") or []),
        "",
        "THE 'AFTER' STATE — what this buyer wants to feel / achieve:",
        _blk("Motivations", states.get("motivations") or []),
        "",
        "PAGE TEXT (judge strictly from this — quote verbatim):",
        (page_text or "").strip()[:_ARC_PAGE_CHARS] or "(empty page)",
        "",
        "Assess whether the page moves this buyer from the before-state to the "
        "after-state, answering each concern. Call emit_emotional_arc now.",
    ]
    return "\n".join(parts)


def _forbidden_regex(never_use_terms: Optional[list]):
    """A word-boundary matcher over the guide's forbidden terms, reusing the
    canonical builder in ``voice_card`` (a sibling, stdlib-only module — safe to
    import offline). Best-effort: any failure → no matcher (the scrub then no-ops
    rather than raising)."""
    if not never_use_terms:
        return None
    try:
        from voice_card import build_term_regex
        return build_term_regex([str(t) for t in never_use_terms if str(t).strip()])
    except Exception:  # pragma: no cover - defensive import guard
        return None


def _arc_clean_str(text, forbidden_rx, cap: int = 300) -> str:
    """A free-text string safe to surface in the report: whitespace-collapsed,
    capped, and BLANKED when it contains a forbidden (never_use) term — the
    report must never surface, and no coaching layer may echo, a term the guide
    forbids (§10b / non-negotiable)."""
    s = _NORM_WS_RE.sub(" ", str(text or "")).strip()
    # Scrub BEFORE capping: a forbidden term straddling the cap boundary must not
    # leave a surviving fragment — check the full string, then truncate.
    if s and forbidden_rx is not None and forbidden_rx.search(s):
        return ""
    return s[:cap]


def sanitize_arc(raw, states: dict, *, never_use_terms: Optional[list] = None,
                 min_evidence_chars: int = _ARC_MIN_EVIDENCE_CHARS) -> dict:
    """Coerce the model's arc tool output into a well-formed, safe sub-object.

    - clamps ``score`` to [0, 100];
    - DROPS unevidenced verdicts: a before/after/transition marked positive with
      no usable page quote is flipped to negative (mirrors the vibe_read
      sanitize — a "yes" with no evidence is unfounded, §10a);
    - SCRUBS every free-text string of forbidden terms so a ``never_use`` word
      never appears in any arc string (§10b / non-negotiable);
    - recomputes the deterministic ``resolved_count`` / ``transition_count`` and
      a ``grounded`` flag from the SURVIVING evidence, so the report can't claim
      an ungrounded resolution.

    Never raises — a malformed field degrades to its safe default."""
    rx = _forbidden_regex(never_use_terms)
    raw = raw if isinstance(raw, dict) else {}

    def _bool(key: str) -> bool:
        val = raw.get(key)
        return val if isinstance(val, bool) else False

    def _evidenced(flag: bool, evidence) -> tuple:
        ev = _arc_clean_str(evidence, rx)
        ok = bool(flag) and len(ev) >= min_evidence_chars
        return ok, (ev if ok else "")

    before_ok, before_ev = _evidenced(_bool("before_acknowledged"), raw.get("before_evidence"))
    after_ok, after_ev = _evidenced(_bool("after_resolved"), raw.get("after_evidence"))

    transitions: list = []
    for t in (raw.get("transitions") or [])[:MAX_ARC_TRANSITIONS]:
        if not isinstance(t, dict):
            continue
        concern = _arc_clean_str(t.get("concern"), rx, cap=240)
        if not concern:  # concern empty or scrubbed (forbidden term) → drop the verdict
            continue
        addressed = t.get("addressed") if isinstance(t.get("addressed"), bool) else False
        ev_ok, ev = _evidenced(addressed, t.get("evidence"))
        transitions.append({"concern": concern, "addressed": ev_ok, "evidence": ev})

    resolved = [t for t in transitions if t["addressed"]]
    try:
        score = round(max(0.0, min(100.0, float(raw.get("score")))), 1)
    except (TypeError, ValueError):
        score = 0.0
    # Grounded = at least one SURVIVING evidenced verdict. A high score with
    # nothing grounded is surfaced with grounded=False (report-only; never gates).
    grounded = bool(before_ok or after_ok or resolved)

    return {
        "available": True,
        "composite_weight": ARC_COMPOSITE_WEIGHT,
        "score": score,
        "grounded": grounded,
        "arc_present": _bool("arc_present"),
        "before_acknowledged": before_ok,
        "before_evidence": before_ev,
        "after_resolved": after_ok,
        "after_evidence": after_ev,
        "transitions": transitions,
        "resolved_count": len(resolved),
        "transition_count": len(transitions),
        "rationale": _arc_clean_str(raw.get("rationale"), rx, cap=400),
        "states": states if isinstance(states, dict) else {},
        "note": (
            "Report-only emotional-arc rubric (composite weight 0) — the "
            "subordinate tail beside centering/coverage/gain; affect is not "
            "embeddable, so this is never in the cosine (§10a)."
        ),
    }


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
    site_claim_index: Optional[dict] = None,
    include_gain: bool = True,
    centering_floor: float = CENTERING_FLOOR,
    coverage_floor: float = COVERAGE_FLOOR,
) -> dict:
    """Run the topic-vector measure (centering / per-subtopic coverage / inverse
    gain gap + the P1 scored Information Gain). Report-only — the caller attaches
    the result beside the composite; it is NEVER folded into the score.

    ``site_claim_index`` (P1) is the client's grounding corpus built in platform-
    api and passed in the request body (§7). When absent/thin the scored gain
    dimension is SUPPRESSED ('not measured', §6), never scored 0.

    ``include_gain=False`` skips the scored Information Gain and, with it, the
    page-claim + site-claim embeddings — so the batch drops back to the P0 size.
    The reopt COACHING pass uses this: it needs only centering + coverage + the
    inverse-gain gap, so embedding/scoring gain on a page about to be rewritten
    away is wasted work.

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
    # P1: the page's own claim sentences (the gain unit) + the client's site-claim
    # phrases (the grounding corpus). Both ride in the SAME batched embedding call
    # as the P0 vectors — sliced back out in order below. Extracted + embedded
    # only when the scored gain will actually be computed: the caller wants it
    # AND the site index is usable. A thin/absent index suppresses gain downstream
    # regardless (§6), so embedding the page's claim sentences would be wasted
    # work — which every /score-page consumer that passes no index (content-gap,
    # the strategist audit_page, a raw score with no client) would otherwise pay.
    want_gain = include_gain and not _index_is_thin(site_claim_index, GAIN_MIN_SITE_CLAIMS)
    page_claims = extract_page_claims(sections) if want_gain else []
    site_claims = _site_claim_texts(site_claim_index) if want_gain else []
    site_values = _site_fact_values(site_claim_index) if want_gain else set()
    # One batched embedding call: page, centroid components, subtopic labels,
    # page sections, page claims, site claims — sliced back out in that order.
    batch = ([page_text] + centroid_texts + labels + sections
             + page_claims + site_claims)
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
    section_vecs = vecs[idx:idx + len(sections)]; idx += len(sections)
    page_claim_vecs = vecs[idx:idx + len(page_claims)]; idx += len(page_claims)
    site_claim_vecs = vecs[idx:idx + len(site_claims)]

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
    # Inverse gain gap (§6): the on-vector subtopics the corpus states that the
    # page lacks (best-section cosine below the coverage floor). Grounded in what
    # competitors demonstrably said — no fabrication risk. Consensus (top-10) gaps
    # are table-stakes; tier-2 gaps are differentiation. The COVERAGE_FLOOR is
    # calibrated (0.70) to sit inside gemini-embedding-2's compressed cosine band,
    # so a well-covered page correctly shows few/no gaps and a thin one surfaces
    # its weak subtopics (the P0 0.55 floor marked everything "covered").
    inverse = sorted(
        (v for v in missing if v["on_vector"]),
        key=lambda v: (0 if v["tier"] == "top10" else 1, v["best_cosine"]),
    )

    # P1 scored Information Gain — suppressed (not zeroed) when the site index is
    # thin/absent or the page yields no claims (§6). Skipped when the caller opted
    # out (include_gain=False — the reopt coaching pass).
    if not include_gain:
        information_gain = {"available": False, "reason": "not_requested"}
    elif _index_is_thin(site_claim_index, GAIN_MIN_SITE_CLAIMS):
        information_gain = {
            "available": False,
            "reason": "no_site_index" if not site_claim_index else "site_index_thin",
            "note": "Information Gain suppressed — the client's site claim index is "
                    "absent or too thin to ground page claims (never scored 0, §6).",
        }
    elif not page_claims:
        information_gain = {"available": False, "reason": "no_page_claims"}
    else:
        claim_verdicts = information_gain_verdicts(
            page_claims, page_claim_vecs, subtopic_vecs, centroid_vec,
            site_claim_vecs, site_values,
            centering_floor=centering_floor,
        )
        information_gain = {"available": True, **score_information_gain(claim_verdicts, verdicts)}
        information_gain["claim_verdicts"] = claim_verdicts

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
        "information_gain": information_gain,
        "thresholds": {
            "centering_floor": centering_floor,
            "coverage_floor": coverage_floor,
            "gain_rarity_ceiling": GAIN_RARITY_CEILING,
            "gain_grounding_floor": GAIN_GROUNDING_FLOOR,
        },
        "note": (
            "Report-only — NOT folded into the composite. Centering is a coarse "
            "drift gauge; the actionable detail is per-subtopic coverage + the "
            "inverse gain gap + the site-grounded Information Gain score (P1, "
            "composite weight 0)."
        ),
    }
