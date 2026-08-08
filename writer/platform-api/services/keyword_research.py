"""Keyword Research — the seed-keyword explorer.

Enter seed keyword(s) for a client → two DataForSEO Labs sources expand them
into the related keyword universe, each already enriched with search volume /
CPC / competition / keyword difficulty / search intent (no follow-up
keyword_overview batch):

  * ``keyword_suggestions`` (PRIMARY, one call per seed) — phrase-containment:
    every returned keyword contains the seed phrase, so the set stays tightly
    on-topic. The trustworthy core.
  * ``related_keywords`` (BROADENER, one call per seed, ON by default) — Google's
    "searches related to" graph. Surfaces adjacent terms that DON'T contain the
    seed phrase ("historic preservation" → "adaptive reuse") while staying on
    Google's related graph, so it broadens without keyword_ideas' category drift.
    Also trusted (no relevance gate).
  * ``keyword_ideas`` (BROADENER, OPT-IN — off by default) — category-based
    expansion that reliably drifts on branded/entity seeds (a category like
    "historic" pulls in "mesopotamia important facts"). Off by default; when
    enabled it's passed through the relevance gate (brand-homonym + drift-anchor
    coherence) before merging.

The merged, deduped set is auto-clustered into topic groups and persisted as a
research run so the view is a cheap re-read and the CSV export is deterministic.

This is a research tool, NOT a content generator — it replaces the old
"Keyword Research" workspace card that pointed at the Topic Fanout (a
mass-content pipeline). The Fanout stays behind the "Create Mass Posts" card.

Design mirrors services/domain_intel.py: the clustering / scoring math here is
PURE (no I/O) and independently unit-tested; the heavy read is a paid Labs call
guarded by a daily budget meter (keyword_research_usage) + persisted to a run so
re-opening a run never re-bills.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import dataforseo_labs, keyword_research_serp

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Raised when a paid Labs call would exceed the module's daily budget."""


_RUNS_KEEP = 25  # research runs retained per client (child rows cascade-delete)

# Common English function words + generic connectors dropped before clustering,
# so topic groups form around meaningful head terms, not "for"/"the"/"near".
_STOPWORDS = frozenset({
    "a", "an", "and", "or", "the", "of", "for", "to", "in", "on", "at", "by",
    "with", "from", "near", "vs", "is", "are", "my", "your", "you", "me", "i",
    "it", "its", "this", "that", "best", "top", "get", "do", "does",
})
# Leading tokens that mark a question keyword (used for the is_question tag and
# to keep question phrasing out of the cluster head where a noun is better).
_QUESTION_LEADS = frozenset({
    "how", "what", "why", "when", "where", "which", "who", "whom", "whose",
    "can", "could", "should", "will", "would", "is", "are", "do", "does",
})
# Pure interrogatives — dropped from tokenization entirely so a QUESTION-form seed
# ("what is a third party claims administrator?") never contributes "what"/"how"
# as a topical token. Without this, a multi-seed run of questions makes "what" a
# seed token, and the keyword_ideas coherence gate (≥2 seed-token overlap) is
# then satisfied by "what" + any one other generic token, flooding the run with
# "what is <anything>" drift ("what is supply chain management", "what is a hen
# party"). Only the unambiguous interrogatives are here — "will"/"can"/"do" can be
# real topic words ("last will and testament", "trash can"), so they stay tokens.
_INTERROGATIVES = frozenset({
    "how", "what", "why", "when", "where", "which", "who", "whom", "whose",
})
_INTENT_WEIGHT = {
    "transactional": 1.0,
    "commercial": 0.9,
    "informational": 0.6,
    "navigational": 0.5,
}


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ---------------------------------------------------------------------------
def normalize_keyword(keyword: Optional[str]) -> str:
    """Lower-cased, whitespace-collapsed keyword. Pure."""
    return re.sub(r"\s+", " ", (keyword or "").strip().lower())


def tokenize(keyword: str) -> list[str]:
    """Significant tokens of a keyword: lower-cased alphanumeric words, minus
    stopwords and pure interrogatives, length ≥ 2. Preserves order. Pure.

    Interrogatives are dropped here (not just flagged by is_question) so a
    question keyword/seed anchors on its real topic in EVERY consumer — clustering
    (no "what" mega-cluster), the relevance/drift gates (no "what"/"how" inflating
    seed-token overlap), and the brand guard alike."""
    words = re.findall(r"[a-z0-9]+", normalize_keyword(keyword))
    return [w for w in words
            if len(w) >= 2 and w not in _STOPWORDS and w not in _INTERROGATIVES]


def _stem(token: str) -> str:
    """Naive plural fold so 'architects'/'razors' match 'architect'/'razor' in the
    relevance gate. Only trims a trailing 's' on tokens long enough that it's a
    plural, not the whole word ('is', 'gas' are left alone). Pure."""
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def token_set(keyword: Optional[str]) -> set[str]:
    """Stemmed significant-token set of a keyword, for relevance comparison. Pure."""
    return {_stem(t) for t in tokenize(keyword or "")}


def brand_tokens(client_name: Optional[str]) -> set[str]:
    """Stemmed significant tokens of a client's business name — the tokens a seed
    shares when it's really the brand, not a topic. Pure."""
    return token_set(client_name)


def is_question(keyword: str) -> bool:
    """Whether a keyword reads as a question (leads with an interrogative or
    ends with '?'). Pure — used to tag question keywords for the view/export."""
    kw = normalize_keyword(keyword)
    if not kw:
        return False
    if kw.endswith("?"):
        return True
    first = re.findall(r"[a-z0-9]+", kw)
    return bool(first) and first[0] in _QUESTION_LEADS


def opportunity_score(
    volume: Optional[int],
    cpc: Optional[float],
    keyword_difficulty: Optional[float],
    search_intent: Optional[str],
) -> float:
    """A ranked-opportunity score for a research keyword. Higher = pursue first.

    value (volume × CPC) × ease (low KD) × intent weight (commercial/transactional
    worth more than informational). Deterministic and monotonic in each input so
    the view/export can sort on it. Pure."""
    value = (volume or 0) * (cpc or 0.0)
    kd = keyword_difficulty if keyword_difficulty is not None else 50.0
    ease = max(0.0, min(100.0, 100.0 - kd)) / 100.0
    weight = _INTENT_WEIGHT.get((search_intent or "").lower(), 0.7)
    return round(value * ease * weight, 2)


def build_research_rows(idea_rows: list[dict]) -> list[dict]:
    """Dedupe + enrich raw Labs idea rows into stored research rows.

    Keeps the highest-volume instance per normalized keyword, and attaches the
    is_question tag + opportunity_score. Sorted by opportunity_score desc. Pure."""
    best: dict[str, dict] = {}
    for r in idea_rows:
        kw = (r.get("keyword") or "").strip()
        if not kw:
            continue
        key = normalize_keyword(kw)
        cur = best.get(key)
        if cur is not None and (r.get("volume") or 0) <= (cur.get("volume") or 0):
            continue
        best[key] = {
            "keyword": kw,
            "volume": r.get("volume"),
            "cpc_usd": r.get("cpc_usd"),
            "competition_index": r.get("competition_index"),
            "keyword_difficulty": r.get("keyword_difficulty"),
            "search_intent": r.get("search_intent"),
            "is_question": is_question(kw),
            "opportunity_score": opportunity_score(
                r.get("volume"), r.get("cpc_usd"),
                r.get("keyword_difficulty"), r.get("search_intent"),
            ),
        }
    rows = list(best.values())
    rows.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return rows


def cluster_keywords(rows: list[dict]) -> list[dict]:
    """Group research rows into topic clusters by their dominant shared token.

    Deterministic, no-LLM lexical clustering: the "head" of a keyword is its
    most globally-frequent significant token (ties → the earliest token in the
    keyword, i.e. its head noun), which is the topic hub the keyword belongs
    under. Preferring the earliest token on a tie keeps a shared city/qualifier
    from hijacking the cluster of "<service> <city>" queries — the service wins.
    Keywords sharing a head land in one cluster labelled by that token. Keywords
    with no significant token (e.g. a bare brand acronym) fall into "other".

    Returns clusters sorted by total search volume desc; within a cluster,
    keywords by opportunity_score desc. Each cluster:
    {label, keyword_count, total_volume, keywords: [keyword, ...]}. Pure."""
    # Global document frequency of each significant token.
    freq: dict[str, int] = {}
    token_cache: dict[int, list[str]] = {}
    for i, r in enumerate(rows):
        toks = tokenize(r.get("keyword") or "")
        token_cache[i] = toks
        for t in set(toks):
            freq[t] = freq.get(t, 0) + 1

    def head_of(toks: list[str]) -> str:
        if not toks:
            return "other"
        # Most globally-frequent token; on a tie the earliest (head) token wins,
        # so a shared city can't outrank the service. Fully deterministic.
        best, best_freq = toks[0], freq.get(toks[0], 0)
        for t in toks[1:]:
            f = freq.get(t, 0)
            if f > best_freq:
                best, best_freq = t, f
        return best

    grouped: dict[str, list[dict]] = {}
    for i, r in enumerate(rows):
        label = head_of(token_cache[i])
        grouped.setdefault(label, []).append(r)

    clusters: list[dict] = []
    for label, members in grouped.items():
        members_sorted = sorted(
            members, key=lambda x: x.get("opportunity_score") or 0, reverse=True
        )
        clusters.append({
            "label": label,
            "keyword_count": len(members_sorted),
            "total_volume": sum((m.get("volume") or 0) for m in members_sorted),
            "keywords": [m["keyword"] for m in members_sorted],
        })
    clusters.sort(key=lambda c: (c["total_volume"], c["keyword_count"]), reverse=True)
    return clusters


# ---------------------------------------------------------------------------
# Relevance gate + brand guard (pure) — keep topic drift out of the results.
#
# DataForSEO Labs ``keyword_ideas`` expands a seed by *category*, not by phrase
# containment, so it drifts two ways:
#
#   * Brand homonym — a branded seed shares a token with a well-known entity
#     ("henson architect" → "henson" the shaving brand / Jim Henson), dragging in
#     that entity's whole category.
#   * Generic-token hijack — a multi-word ENTITY seed contains a common word that
#     is itself a huge category ("local law 97 architect" → the token "law" pulls
#     in "family law attorney", "law firm", "law school", …). Single-token
#     overlap can't catch this: "family law attorney" legitimately shares "law".
#
# filter_relevant_ideas addresses both, scaling strictness to how specific the
# seed is:
#   * Specific seed (≥3 seed tokens, e.g. "local law 97 architect",
#     "historical preservation architect"): a kept idea must share ≥2 of the FULL
#     seed tokens, so one generic word ("law", "historical") can't admit its whole
#     category. Keys on the full seed — not the brand-subtracted set — so a brand
#     token that is also a topic word ("architect") can't shrink the seed out of
#     the gate.
#   * Short seed (1–2 seed tokens): only the brand-homonym gate engages, so clean
#     service seeds keep their cross-topic broadening ("plumber" → "blocked drain").
# seed_warnings additionally advises when a seed is essentially the business name.
# ---------------------------------------------------------------------------
_COHERENCE_MIN_SEED_TOKENS = 3   # seed token count at/above which the coherence gate always runs
_COHERENCE_MIN_OVERLAP = 2       # seed tokens a kept idea must share under that gate
# For 2-token seeds the coherence gate runs only when one seed token is a "drift
# anchor" — present in at least this fraction of the returned ideas. That's the
# signature of a generic word DataForSEO expanded a whole category on ("historic"
# → "synonym for historic", "hisd jobs"), as opposed to a clean service seed
# where broadening dilutes any single token below the bar ("plumber" → "blocked
# drain"). When an anchor dominates, a kept idea must carry a 2nd seed token too.
_COHERENCE_ANCHOR_FRACTION = 0.6
_SPARSE_RESULT_MIN = 8   # below this many results, a long seed gets a "shorten it" advisory


def filter_relevant_ideas(
    idea_rows: list[dict],
    seeds: list[str],
    client_name: Optional[str] = None,
    *,
    enabled: bool = True,
) -> tuple[list[dict], dict]:
    """Drop off-topic / brand-homonym / generic-token-drift ideas from a raw Labs
    idea set.

    Returns (kept_rows, report). ``report`` = {gate, input, kept,
    dropped_off_topic, dropped_brand_only}. ``gate`` is 'off' (disabled),
    'coherence' (specific seed, ≥2 full-seed-token overlap), 'topical'
    (brand-homonym rule), or 'none' (nothing to gate). Pure."""
    total = len(idea_rows)
    report = {"gate": "off", "input": total, "kept": total,
              "dropped_off_topic": 0, "dropped_brand_only": 0}
    if not enabled:
        return idea_rows, report

    seed_toks: set[str] = set()
    for s in seeds or []:
        seed_toks |= token_set(s)
    if not seed_toks:
        return idea_rows, report

    brand = brand_tokens(client_name)
    brand_in_seed = seed_toks & brand

    # Cache each idea's token set once (reused by anchor detection + the gates).
    idea_tokens = [token_set(r.get("keyword")) for r in idea_rows]

    # Coherence gate → require ≥2 overlap with the FULL seed tokens so a lone
    # generic word ("law", "historic") can't drag in its whole category. Keyed on
    # the full seed (NOT brand-subtracted): a brand token is often also a real
    # topic word ("architect" for client "Henson Architect"), and subtracting it
    # would silently shrink the seed out of the gate. It runs when EITHER:
    #   * the seed has ≥3 tokens (specific by construction), OR
    #   * a seed token is a drift anchor — present in ≥60% of the returned ideas
    #     (catches 2-word entity seeds like "historic preservation" whose single
    #     dominant token would otherwise pass unfiltered).
    # Only a NON-brand seed token can be a drift anchor — a dominant brand token
    # ("henson" for client "Henson …") is the brand-homonym case handled below,
    # not generic-category drift.
    anchor = False
    if len(seed_toks) >= 2 and idea_tokens:
        n = len(idea_tokens)
        anchor = any(
            sum(1 for rt in idea_tokens if t in rt) >= _COHERENCE_ANCHOR_FRACTION * n
            for t in (seed_toks - brand)
        )
    if len(seed_toks) >= _COHERENCE_MIN_SEED_TOKENS or (anchor and len(seed_toks) >= 2):
        kept: list[dict] = []
        off_topic = 0
        for r, rt in zip(idea_rows, idea_tokens):
            if len(rt & seed_toks) >= _COHERENCE_MIN_OVERLAP:
                kept.append(r)
            else:
                off_topic += 1
        report.update({"gate": "coherence", "kept": len(kept),
                       "dropped_off_topic": off_topic})
        return kept, report

    # Short seed → brand-homonym gate only (preserve broadening for clean seeds).
    topical_bh = seed_toks - brand
    if not (brand_in_seed and topical_bh):
        report["gate"] = "none"
        return idea_rows, report

    kept = []
    off_topic = brand_only = 0
    for r, rt in zip(idea_rows, idea_tokens):
        if rt & topical_bh:
            kept.append(r)
        elif rt & brand_in_seed:
            brand_only += 1   # matches the brand but not the topic → hijack noise
        else:
            off_topic += 1    # matches nothing in the seed → drift
    report.update({"gate": "topical", "kept": len(kept),
                   "dropped_off_topic": off_topic, "dropped_brand_only": brand_only})
    return kept, report


_BRAND_FLOOD_MIN_FRACTION = 0.4   # a flood token must dominate >= this share of the seedless subset
_BRAND_FLOOD_MIN_COUNT = 8        # ...and appear in >= this many seedless keywords (protects tiny subsets)


def detect_brand_flood_tokens(
    related_keywords: list[str],
    seeds: list[str],
    *,
    enabled: bool = True,
    min_fraction: float = _BRAND_FLOOD_MIN_FRACTION,
    min_count: int = _BRAND_FLOOD_MIN_COUNT,
) -> tuple[set[str], dict]:
    """Detect competitor-brand / homonym namespace floods in the related_keywords
    adjacency layer — the one broadener KR trusts ungated (suggestions are
    phrase-containment; keyword_ideas has its own gate). A flood is a single
    NON-seed token that dominates the SEEDLESS neighbours (those sharing no seed
    token): e.g. related_keywords for "third party claims adjuster" surfaced the
    claims-software vendor "Mitchell" and then flooded with "mitchell connect" /
    "mitchell prodemand" plus homonym "mitchell usa serum".

    Restricting to the seedless subset means legit seed-anchored adjacency
    ("historic preservation office") is never a candidate, and requiring ONE token
    to dominate means diverse legit adjacency ("adaptive reuse", "national trust")
    survives — no single token dominates a healthy related set. Deliberately
    conservative: a small seedless subset (< min_count) can't flood, and the
    fraction bar is high enough that a namespace repeating its brand token clears
    it while topical adjacency does not.

    Returns (flood_tokens, report). ``report`` = {gate, seedless, flood_tokens,
    dropped}. `gate` is 'off' (disabled / no seeds), 'none' (no flood), or 'flood'.
    Pure."""
    report = {"gate": "off", "seedless": 0, "flood_tokens": [], "dropped": 0}
    if not enabled:
        return set(), report
    seed_toks: set[str] = set()
    for s in seeds or []:
        seed_toks |= token_set(s)
    if not seed_toks:
        return set(), report

    # Seedless subset: unique candidate keywords sharing no seed token.
    seedless: dict[str, set[str]] = {}
    for kw in related_keywords:
        nk = normalize_keyword(kw)
        if not nk or nk in seedless:
            continue
        kt = token_set(nk)
        if kt and not (kt & seed_toks):
            seedless[nk] = kt
    n = len(seedless)
    report["seedless"] = n
    if n < min_count:
        return set(), report  # too few seedless neighbours for a flood to be meaningful

    counts: dict[str, int] = {}
    for kt in seedless.values():
        for t in kt:
            counts[t] = counts.get(t, 0) + 1
    flood = {t for t, c in counts.items() if c >= min_count and c / n >= min_fraction}
    dropped = sum(1 for kt in seedless.values() if kt & flood)
    report.update({"gate": "flood" if flood else "none",
                   "flood_tokens": sorted(flood), "dropped": dropped})
    return flood, report


def is_brand_flooded(keyword: Optional[str], seed_toks: set[str], flood_tokens: set[str]) -> bool:
    """A related keyword is dropped when it carries a flood token AND shares no
    seed token (so a legit seed-anchored keyword that happens to contain a flood
    token is kept). Pure."""
    if not flood_tokens:
        return False
    kt = token_set(keyword)
    return bool(kt & flood_tokens) and not (kt & seed_toks)


# ---------------------------------------------------------------------------
# Generic filler-token drift gate (pure) — the companion to the brand-flood
# gate for the trusted related layer.
#
# A multi-word ENTITY seed often carries a semantically-BLEACHED filler word
# that is a huge standalone category — "third PARTY claims administrator",
# "FIRST party data". The related-searches graph wanders from the compound sense
# ("third party", legal) into the filler's own sense ("party" → "party rentals",
# "birthday party"). Those drift keywords share the filler SEED token, so:
#   * the brand-flood gate misses them (it inspects only the seedless subset and
#     flags NON-seed tokens), and
#   * the ≥2-overlap coherence gate — which KR deliberately withholds from the
#     trusted related layer to preserve legit adjacency — never runs on them.
# The result is a run full of "party ..." keywords for a claims-administration
# seed (reported 2026-08-07).
#
# The fix stays token-based (no embeddings) and mirrors the brand-flood gate's
# conservatism. A curated list names the words that are bleached-in-compound and
# carry no topical meaning ALONE; the gate then engages ONLY when the seed's
# topic is clearly carried by ≥2 DISTINCTIVE (non-filler) tokens — so a seed that
# is genuinely ABOUT the filler word ("party rental company", "party planning")
# is never gated — and drops a related keyword whose ONLY tie to the seed is one
# flagged filler token, keeping the on-topic compound ("third party
# administrator", overlap ≥2) and true adjacency (overlap 0).
# ---------------------------------------------------------------------------
# Stemmed forms (token_set stems trailing plurals): relational / ordinal /
# structural filler + generic business-suffix words. A seed token here counts as
# "distinctive" only when it is NOT in this set.
_GENERIC_SEED_MODIFIERS = frozenset({
    "third", "first", "second", "fourth", "fifth",
    "party", "general", "public", "private", "local", "national", "regional",
    "personal", "professional", "direct", "indirect", "mutual", "joint",
    "single", "multiple", "full", "main", "basic", "standard", "premium",
    "various", "several", "certain", "same", "different",
    "company", "companie", "service", "group", "business",
    "inc", "llc", "corp", "ltd", "co",
})
_GENERIC_DRIFT_MIN_COUNT = 5        # solo-overlap keywords a filler token needs to be a drift anchor
_GENERIC_DRIFT_MIN_DISTINCTIVE = 2  # distinctive seed tokens required for the gate to engage at all


def detect_generic_drift_tokens(
    related_keywords: list[str],
    seeds: list[str],
    *,
    enabled: bool = True,
    min_count: int = _GENERIC_DRIFT_MIN_COUNT,
) -> tuple[set[str], dict]:
    """Detect false-friend drift on a bleached FILLER seed token in the related
    adjacency layer (KR's ungated broadener).

    Engages only when the seed pairs a filler word (``_GENERIC_SEED_MODIFIERS``)
    with ≥ ``_GENERIC_DRIFT_MIN_DISTINCTIVE`` distinctive tokens — i.e. the topic
    is clearly elsewhere, so the filler is genuinely peripheral. Among the related
    keywords whose ONLY seed overlap is a single filler token, a filler with
    ≥ ``min_count`` such solo keywords is flagged as a drift anchor.

    Returns (drift_tokens, report). ``report`` = {gate, distinctive, drift_tokens,
    dropped}. ``gate`` is 'off' (disabled / not engaged), 'none' (engaged, no
    anchor), or 'drift'. Pure."""
    report = {"gate": "off", "distinctive": 0, "drift_tokens": [], "dropped": 0}
    if not enabled:
        return set(), report
    seed_toks: set[str] = set()
    for s in seeds or []:
        seed_toks |= token_set(s)
    filler = seed_toks & _GENERIC_SEED_MODIFIERS
    distinctive = seed_toks - _GENERIC_SEED_MODIFIERS
    report["distinctive"] = len(distinctive)
    if not filler or len(distinctive) < _GENERIC_DRIFT_MIN_DISTINCTIVE:
        # Topic not carried by ≥2 distinctive tokens (or no filler at all) → a
        # solo filler match could be the real subject; leave the layer untouched.
        return set(), report

    # Count, per filler token, the UNIQUE related keywords whose seed overlap is
    # exactly that one filler token — the false-friend zone. Keywords sharing ≥2
    # seed tokens (the on-topic compound) or 0 (true adjacency) are never counted.
    solo_counts: dict[str, int] = {}
    seen: set[str] = set()
    for kw in related_keywords:
        nk = normalize_keyword(kw)
        if not nk or nk in seen:
            continue
        seen.add(nk)
        overlap = token_set(nk) & seed_toks
        if len(overlap) == 1:
            (t,) = tuple(overlap)
            if t in filler:
                solo_counts[t] = solo_counts.get(t, 0) + 1
    drift = {t for t, c in solo_counts.items() if c >= min_count}
    dropped = sum(c for t, c in solo_counts.items() if t in drift)
    report.update({"gate": "drift" if drift else "none",
                   "drift_tokens": sorted(drift), "dropped": dropped})
    return drift, report


def is_generic_drift(keyword: Optional[str], seed_toks: set[str], drift_tokens: set[str]) -> bool:
    """A related keyword is dropped when its ONLY seed overlap is a single flagged
    filler/drift token — so a keyword also sharing a distinctive seed token (the
    compound), or sharing no seed token (true adjacency), is kept. Pure."""
    if not drift_tokens:
        return False
    overlap = token_set(keyword) & seed_toks
    return len(overlap) == 1 and next(iter(overlap)) in drift_tokens


def looks_like_brand_seed(
    seed: str, client_name: Optional[str], ratio_threshold: float = 0.6
) -> bool:
    """Whether a seed is essentially the client's business name (so keyword
    research on it will drift). True when a majority of the seed's tokens are
    brand tokens. Pure."""
    brand = brand_tokens(client_name)
    st = token_set(seed)
    if not brand or not st:
        return False
    return (len(st & brand) / len(st)) >= ratio_threshold


def seed_warnings(
    seeds: list[str],
    client_name: Optional[str],
    filter_report: Optional[dict] = None,
    ratio_threshold: float = 0.6,
    total_results: Optional[int] = None,
) -> list[str]:
    """Human-readable advisories for a run: branded seeds and heavy filtering.
    ``total_results`` is the final merged keyword count (suggestions + filtered
    ideas) — the empty-result advisory only fires when the whole run came back
    empty, not merely when the ideas broadener was fully filtered. Deterministic;
    safe to recompute on read from seeds + client name (filter_report omitted).
    Pure."""
    warnings: list[str] = []
    branded = [s for s in (seeds or []) if looks_like_brand_seed(s, client_name, ratio_threshold)]
    if branded:
        quoted = ", ".join(f"“{s}”" for s in branded)
        warnings.append(
            f"{quoted} looks like your business name. Keyword research works best "
            "on the service or topic you want to rank for (e.g. “architect "
            "<city>”, “residential architect”) rather than a brand name."
        )
    if filter_report and filter_report.get("gate") in ("topical", "coherence"):
        dropped = (filter_report.get("dropped_brand_only", 0)
                   + filter_report.get("dropped_off_topic", 0))
        if dropped:
            warnings.append(
                f"Filtered {dropped} off-topic keyword(s) that didn't match the "
                "seed topic closely enough."
            )
    if total_results == 0:
        warnings.append(
            "No on-topic keywords were found — try a more specific service or "
            "topic as the seed."
        )
    elif (total_results is not None and total_results < _SPARSE_RESULT_MIN
          and any(len(token_set(s)) >= 3 for s in (seeds or []))):
        warnings.append(
            f"This seed is very specific and returned only {total_results} "
            "keyword(s). For a fuller set, try a shorter core topic (e.g. the main "
            "subject on its own, like “historic preservation” or “preservation "
            "architect”) rather than a long descriptive phrase."
        )
    return warnings


# ---------------------------------------------------------------------------
# Budget guard (I/O) — mirrors domain_intel's daily meter.
# ---------------------------------------------------------------------------
def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def budget_remaining() -> int:
    """Paid Labs calls left in today's budget (a large number when disabled)."""
    cap = settings.keyword_research_daily_call_budget
    if cap <= 0:
        return 10 ** 9
    try:
        rows = (
            get_supabase().table("keyword_research_usage").select("calls")
            .eq("day", _today()).limit(1).execute()
        ).data
    except Exception:
        return cap
    used = rows[0]["calls"] if rows else 0
    return max(0, cap - used)


def reserve_budget(n: int) -> None:
    """Reserve ``n`` paid Labs calls against today's budget, or raise
    BudgetExceeded. Atomic via the reserve_keyword_research_calls RPC. An RPC
    failure is fail-open (accounting never blocks work)."""
    cap = settings.keyword_research_daily_call_budget
    if cap <= 0:
        return
    try:
        res = get_supabase().rpc(
            "reserve_keyword_research_calls", {"p_day": _today(), "p_n": n, "p_cap": cap}
        ).execute()
        fit = res.data
    except Exception as exc:
        logger.warning("keyword_research_budget_accounting_failed", extra={"error": str(exc)})
        return
    if fit is False:
        raise BudgetExceeded(f"keyword_research_budget_exceeded: cap {cap} reached today")


# ---------------------------------------------------------------------------
# Orchestration (I/O).
# ---------------------------------------------------------------------------
def parse_seeds(raw) -> list[str]:
    """Normalize a seed payload (a string or list) into a deduped seed list.
    Splits a string on newlines/commas. Pure."""
    if isinstance(raw, str):
        parts = re.split(r"[\n,]+", raw)
    elif isinstance(raw, (list, tuple)):
        parts = []
        for item in raw:
            parts.extend(re.split(r"[\n,]+", str(item)))
    else:
        return []
    seen: list[str] = []
    lowered: set[str] = set()
    for p in parts:
        s = p.strip()
        if s and s.lower() not in lowered:
            lowered.add(s.lower())
            seen.append(s)
    return seen[: settings.keyword_research_max_seeds]


def _client_context(client_id: str) -> dict:
    """The client's rank-tracking location + business name (for the relevance
    gate/brand guard). Best-effort — an empty dict on failure."""
    try:
        rows = (
            get_supabase().table("clients")
            .select("name, website_url, business_location, gbp, detected_icp, "
                    "differentiators, icp_text, rank_tracking_location_code")
            .eq("id", client_id).limit(1).execute()
        ).data
    except Exception as exc:
        logger.warning("keyword_research.client_lookup_failed", extra={"client_id": client_id, "error": str(exc)})
        return {}
    return (rows or [{}])[0] or {}


def _client_location_code(client_id: str) -> Optional[int]:
    return _client_context(client_id).get("rank_tracking_location_code")


# Estimated DataForSEO cost per live SERP (organic/live/advanced) call — used
# only to keep the run's best-effort cost_usd honest (fetch_serp returns items,
# not the billed cost).
_SERP_CALL_COST = 0.002


async def _fetch_serp_intel(
    seed_list: list[str],
    location_code: Optional[int],
    language_code: Optional[str],
    client_domain: Optional[str],
) -> tuple[list[tuple[str, str]], dict, float]:
    """SERP-enrichment pass: for the first N seeds, one live Google SERP call each
    → PAA questions + competitive landscape (top organic domains + AIO sources).

    Reuses serp_snapshot's fetch + parsers so there's one SERP parser in the
    suite. Returns (paa_pairs, serp_intel_blob, cost) where paa_pairs is a list of
    (question, seed) across the analyzed seeds — the caller dedupes for folding
    and uses the seed for per-keyword attribution. Best-effort — a failed seed is
    skipped; an all-empty pass returns ([], {}, cost)."""
    from services import serp_snapshot

    seeds = seed_list[: settings.keyword_research_serp_max_seeds]
    loc = int(location_code) if location_code else settings.dataforseo_default_location_code
    lang = language_code or settings.dataforseo_default_language_code
    depth = settings.keyword_research_serp_depth

    async def _one(seed: str):
        items = await serp_snapshot.fetch_serp(seed, loc, lang, depth)
        organic = serp_snapshot.extract_organic_results(
            items, settings.keyword_research_serp_top_competitors)
        features = serp_snapshot.extract_serp_features(items)
        aio = serp_snapshot.extract_aio(items)
        return seed, organic, features.get("people_also_ask") or [], aio

    results = await asyncio.gather(*[_one(s) for s in seeds], return_exceptions=True)

    per_seed_organic: list[dict] = []
    per_seed_aio: list[dict] = []
    paa_lists: list[list[str]] = []
    analyzed: list[str] = []
    cost = 0.0
    for res in results:
        if isinstance(res, Exception):
            logger.warning("keyword_research.serp_failed", extra={"error": str(res)})
            continue
        seed, organic, paa, aio = res
        cost += _SERP_CALL_COST
        analyzed.append(seed)
        per_seed_organic.append({"seed": seed, "organic": organic})
        per_seed_aio.append({"seed": seed, "present": aio.get("present"),
                             "sources": aio.get("sources") or []})
        paa_lists.append(paa)

    if not analyzed:
        return [], {}, cost
    intel = keyword_research_serp.build_serp_intel(
        analyzed, per_seed_organic, per_seed_aio, paa_lists, client_domain,
        top_competitors=settings.keyword_research_serp_top_competitors,
    )
    paa_pairs = [(q, seed) for seed, lst in zip(analyzed, paa_lists) for q in (lst or [])]
    return paa_pairs, intel, cost


async def run_keyword_research(
    client_id: str,
    seeds: list[str],
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
) -> dict:
    """Fetch + persist a keyword research run for a seed set.

    Reserves budget, calls Labs keyword_ideas, dedupes/enriches/clusters (pure),
    and persists a run row with its child keyword rows. Returns a summary."""
    seed_list = seeds[: settings.keyword_research_max_seeds]
    if not seed_list:
        raise ValueError("no_seeds")
    supabase = get_supabase()
    ctx = _client_context(client_id)
    client_name = ctx.get("name")
    if location_code is None:
        location_code = ctx.get("rank_tracking_location_code")

    # Client-grounded topical research (best-effort): read the client's site topics
    # + fan out the seed intent. Produces the relevance anchors AND a few extra
    # on-topic expansion seeds that broaden the run in relevant directions (fed to
    # the phrase-containment suggestions only, so they can't drift).
    from services import keyword_research_topics
    topic_research = await keyword_research_topics.research_topics(ctx, seed_list, location_code)
    expansion_seeds = topic_research.get("expansion_seeds") or []

    use_suggestions = settings.keyword_research_use_suggestions
    use_related = settings.keyword_research_broaden_with_related
    # keyword_ideas stays available but off by default (category drift). Fall back
    # to it only if it's the sole enabled source, so a run always has one.
    use_ideas = settings.keyword_research_broaden_with_ideas or not (use_suggestions or use_related)
    use_serp = settings.keyword_research_serp_enrichment
    n_serp = min(len(seed_list), settings.keyword_research_serp_max_seeds) if use_serp else 0
    n_calls = (
        (len(seed_list) if use_suggestions else 0)
        + (len(expansion_seeds) if use_suggestions else 0)
        + (len(seed_list) if use_related else 0)
        + (1 if use_ideas else 0)
        + n_serp
    )
    reserve_budget(max(1, n_calls))

    cost = 0.0

    # Per-keyword seed attribution: which of the run's seeds produced each keyword,
    # so a user can later remove ONE seed and take its keywords with it (see
    # remove_seed). A keyword can come from several seeds (the pipeline dedupes
    # across sources), so we accumulate a SET per normalized keyword. Only the
    # per-seed sources (suggestions / related nodes + neighbours / PAA) attribute;
    # the batched keyword_ideas call has no per-seed origin from DataForSEO, so
    # ideas-only keywords stay unattributed (source_seeds NULL = run-level, never
    # removed by a single-seed removal — the safe default).
    seed_attr: dict[str, set[str]] = {}

    def _attr(kw: Optional[str], seed: str) -> None:
        nk = normalize_keyword(kw)
        if nk:
            seed_attr.setdefault(nk, set()).add(seed)

    # SERP-enrichment pass (People Also Ask + competitive intelligence): one live
    # SERP call per analyzed seed → PAA questions folded into the keyword universe
    # (below, attributed to the seed whose SERP produced them) and the
    # competitor/AIO landscape persisted as serp_intel. Best-effort — a failure
    # leaves the run otherwise unaffected.
    serp_paa: list[str] = []
    serp_intel: dict = {}
    if use_serp:
        try:
            client_domain = None
            website = ctx.get("website_url")
            if website:
                from services.dataforseo_rank import extract_domain
                client_domain = extract_domain(website) or None
            serp_paa_pairs, serp_intel, serp_cost = await _fetch_serp_intel(
                seed_list, location_code, language_code, client_domain)
            cost += serp_cost or 0.0
            # Attribute each PAA question to its seed; build the flat unique list
            # (order-preserving) that folds into the neighbour-enrichment path.
            _seen_paa: set[str] = set()
            for q, s in serp_paa_pairs:
                _attr(q, s)
                nk = normalize_keyword(q)
                if nk and nk not in _seen_paa:
                    _seen_paa.add(nk)
                    serp_paa.append(q)
        except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
            logger.warning("keyword_research.serp_enrichment_failed",
                           extra={"client_id": client_id, "error": str(exc)})

    async def _gather_per_seed(fetch, label):
        """Run a per-seed fetch across all seeds concurrently; collect rows + cost,
        attributing each row to the seed that produced it (gather preserves order)."""
        nonlocal cost
        out: list[dict] = []
        results = await asyncio.gather(
            *[fetch(s) for s in seed_list], return_exceptions=True
        )
        for s, res in zip(seed_list, results):
            if isinstance(res, Exception):
                logger.warning(f"keyword_research.{label}_failed",
                               extra={"client_id": client_id, "error": str(res)})
                continue
            rows_i, cost_i = res
            for r in rows_i:
                out.append(r)
                _attr(r.get("keyword"), s)
            cost += cost_i or 0.0
        return out

    # PRIMARY — phrase-containment suggestions (contain the seed phrase → trusted
    # on-topic, no gate). BROADENER — related_keywords (Google's related-searches
    # graph → adjacent terms without keyword_ideas' category drift, so also
    # trusted, no gate). Both are per-seed, fanned out.
    trusted_rows: list[dict] = []
    if use_suggestions:
        trusted_rows += await _gather_per_seed(
            lambda s: dataforseo_labs.fetch_keyword_suggestions(
                s, location_code, language_code,
                limit=settings.keyword_research_suggestion_limit,
            ), "suggestions")

        # Topic-derived expansion seeds → phrase-containment suggestions too. These
        # broaden the run along the client's real intents (never drifting, since
        # suggestions contain the seed phrase). Left UNATTRIBUTED (run-level, not a
        # user seed) so per-seed removal never touches them.
        for exp_seed in expansion_seeds:
            try:
                rows_i, cost_i = await dataforseo_labs.fetch_keyword_suggestions(
                    exp_seed, location_code, language_code,
                    limit=settings.keyword_research_suggestion_limit,
                )
                trusted_rows += rows_i
                cost += cost_i or 0.0
            except Exception as exc:  # noqa: BLE001 — best-effort broadening
                logger.warning("keyword_research.expansion_suggestions_failed",
                               extra={"client_id": client_id, "seed": exp_seed, "error": str(exc)})

    # related_keywords returns enriched graph nodes PLUS bare "searches related to"
    # neighbour strings (Google's adjacency layer). Collect both across seeds —
    # kept in `related_rows` (separate from suggestions) so the brand-flood gate can
    # filter this ungated layer before it merges.
    related_rows: list[dict] = []
    related_neighbors: list[str] = []
    if use_related:
        results = await asyncio.gather(*[
            dataforseo_labs.fetch_related_keywords(
                s, location_code, language_code,
                depth=settings.keyword_research_related_depth,
                limit=settings.keyword_research_related_limit,
            ) for s in seed_list
        ], return_exceptions=True)
        for s, res in zip(seed_list, results):
            if isinstance(res, Exception):
                logger.warning("keyword_research.related_failed",
                               extra={"client_id": client_id, "error": str(res)})
                continue
            node_rows, neighbors, cost_i = res
            related_rows += node_rows
            related_neighbors += neighbors
            for r in node_rows:
                _attr(r.get("keyword"), s)
            for nb in neighbors:
                _attr(nb, s)
            cost += cost_i or 0.0

    # People Also Ask questions (from the SERP pass) enter the keyword universe
    # via the same neighbour-enrichment path (bare strings → keyword_overview
    # metrics → rows), so they cluster, export and tag as questions. Prepended so
    # the neighbour cap never truncates them.
    if serp_paa:
        related_neighbors = serp_paa + related_neighbors

    # Enrich the adjacency neighbours (bare strings) that aren't already present,
    # then add them to related_rows — this is where cross-topic terms like
    # "adaptive reuse" enter. One keyword_overview call per ≤700, capped.
    if related_neighbors:
        have = {normalize_keyword(r.get("keyword")) for r in trusted_rows}
        have |= {normalize_keyword(r.get("keyword")) for r in related_rows}
        fresh, seen_fresh = [], set()
        for k in related_neighbors:
            nk = normalize_keyword(k)
            if nk and nk not in have and nk not in seen_fresh:
                seen_fresh.add(nk)
                fresh.append(k)
        fresh = fresh[: settings.keyword_research_related_neighbor_cap]
        if fresh:
            import math
            reserve_budget(max(1, math.ceil(len(fresh) / 700)))
            overview, cost_ov = await dataforseo_labs.fetch_keyword_overview(
                fresh, location_code, language_code)
            cost += cost_ov or 0.0
            ov_lower = {kw.lower(): m for kw, m in overview.items()}
            for k in fresh:
                m = ov_lower.get(k.lower()) or {}
                related_rows.append({
                    "keyword": k, "volume": m.get("volume"), "cpc_usd": m.get("cpc_usd"),
                    "competition_index": m.get("competition_index"),
                    "keyword_difficulty": m.get("keyword_difficulty"),
                    "search_intent": m.get("search_intent"),
                })

    # Two conservative gates clean the trusted related adjacency layer before it
    # merges. Both key off the seed token set, so compute it once.
    seed_toks: set[str] = set()
    for s in seed_list:
        seed_toks |= token_set(s)

    # (1) Brand-flood gate: drop a competitor-brand / homonym namespace that
    # flooded the layer (e.g. a "mitchell ..." cluster), keeping legit
    # seed-anchored and diverse adjacency.
    flood_tokens, flood_report = detect_brand_flood_tokens(
        [r.get("keyword") for r in related_rows], seed_list,
        enabled=settings.keyword_research_brand_flood_filter,
        min_fraction=settings.keyword_research_brand_flood_fraction,
        min_count=settings.keyword_research_brand_flood_min,
    )
    if flood_tokens:
        related_rows = [
            r for r in related_rows
            if not is_brand_flooded(r.get("keyword"), seed_toks, flood_tokens)
        ]

    # (2) Generic filler-token drift gate: drop keywords whose only tie to a
    # multi-word entity seed is a bleached filler word ("party" from "third party
    # claims administrator"), keeping the on-topic compound and true adjacency.
    drift_tokens, drift_report = detect_generic_drift_tokens(
        [r.get("keyword") for r in related_rows], seed_list,
        enabled=settings.keyword_research_generic_drift_filter,
        min_count=settings.keyword_research_generic_drift_min,
    )
    if drift_tokens:
        related_rows = [
            r for r in related_rows
            if not is_generic_drift(r.get("keyword"), seed_toks, drift_tokens)
        ]
    trusted_rows += related_rows

    # OPT-IN BROADENER — category-based ideas, passed through the relevance gate to
    # drop brand-homonym / generic-token drift before merging.
    idea_rows: list[dict] = []
    filter_report = {"gate": "off", "input": 0, "kept": 0,
                     "dropped_off_topic": 0, "dropped_brand_only": 0}
    if use_ideas:
        idea_rows, cost_ideas = await dataforseo_labs.fetch_keyword_ideas(
            seed_list, location_code, language_code,
            limit=settings.keyword_research_idea_limit,
        )
        cost += cost_ideas or 0.0
        idea_rows, filter_report = filter_relevant_ideas(
            idea_rows, seed_list, client_name,
            enabled=settings.keyword_research_relevance_filter,
        )

    # Merge + dedupe (build_research_rows keeps the highest-volume instance per
    # normalized keyword, so a keyword in several sources collapses to one row).
    rows = build_research_rows(trusted_rows + idea_rows)

    # Gemini semantic relevance gate: score each merged keyword by cosine to the
    # anchor set (seeds + fanned-out intents + the client's site topics) and drop
    # the semantically off-topic ones, keeping phrase-containment keywords. Runs
    # on the DEDUPED rows (one embedding per unique keyword), best-effort — skipped
    # (rows untouched) when disabled or no Gemini key. Attaches relevance_score to
    # every surviving row.
    relevance_report = {"gate": "off"}
    if settings.keyword_research_semantic_relevance:
        from services import keyword_research_relevance
        anchors = topic_research.get("anchors") or list(seed_list)
        rows, relevance_report = await keyword_research_relevance.score_relevance(
            rows, anchors, seed_list, settings.keyword_research_relevance_floor,
        )
    topic_research["relevance"] = relevance_report

    # Audience-fit filter: drop keywords targeting the WRONG audience for the
    # client's buyer (job-seeker/career universally + ICP-specific off-audience
    # vocabulary). Relevance ≠ buyer fit — "insurance adjuster salary" is on-topic
    # but useless to a B2B TPA. Runs on the relevance survivors, before clustering.
    audience_report = {"gate": "off"}
    from services import keyword_research_audience
    rows, audience_report = keyword_research_audience.filter_by_audience(rows, ctx, seed_list)
    topic_research["audience"] = audience_report

    warnings = seed_warnings(
        seed_list, client_name, filter_report,
        ratio_threshold=settings.keyword_research_brand_seed_ratio,
        total_results=len(rows),
    )
    if flood_report.get("dropped"):
        warnings.append(
            f"Filtered {flood_report['dropped']} related keyword(s) that looked "
            f"like an unrelated brand/namespace ({', '.join(flood_report['flood_tokens'])})."
        )
    if drift_report.get("dropped"):
        drift_words = ", ".join(f"“{t}”" for t in drift_report["drift_tokens"])
        warnings.append(
            f"Filtered {drift_report['dropped']} related keyword(s) that only matched "
            f"a generic word in your seed ({drift_words}) rather than the actual topic."
        )
    if relevance_report.get("dropped"):
        warnings.append(
            f"Filtered {relevance_report['dropped']} keyword(s) that weren't topically "
            "relevant to the seeds or the client's business."
        )
    _aud_dropped = (audience_report.get("dropped_job_seeker", 0)
                    + audience_report.get("dropped_off_audience", 0))
    if _aud_dropped:
        warnings.append(
            f"Filtered {_aud_dropped} keyword(s) that target the wrong audience "
            "(job-seekers / careers / off-audience), not the client's buyer."
        )
    if warnings:
        logger.info("keyword_research.seed_warnings",
                    extra={"client_id": client_id, "seeds": seed_list,
                           "filter": filter_report, "brand_flood": flood_report,
                           "generic_drift": drift_report, "relevance": relevance_report,
                           "warnings": warnings})
    clusters = cluster_keywords(rows)
    label_for = {kw: c["label"] for c in clusters for kw in c["keywords"]}

    run = (
        supabase.table("keyword_research_runs").insert({
            "client_id": client_id,
            "seeds": seed_list,
            "location_code": location_code,
            "language_code": language_code or "en",
            "keyword_count": len(rows),
            "cluster_count": len(clusters),
            "status": "complete",
            "cost_usd": round(cost or 0.0, 4),
            "serp_intel": serp_intel or None,
            "topic_research": topic_research or None,
        }).execute()
    ).data[0]

    child = [{
        "run_id": run["id"],
        "keyword": r["keyword"],
        "cluster_label": label_for.get(r["keyword"]),
        "volume": r.get("volume"),
        "cpc_usd": r.get("cpc_usd"),
        "competition_index": r.get("competition_index"),
        "keyword_difficulty": r.get("keyword_difficulty"),
        "search_intent": r.get("search_intent"),
        "is_question": r.get("is_question"),
        "opportunity_score": r.get("opportunity_score"),
        "relevance_score": r.get("relevance_score"),
        "audience_fit": r.get("audience_fit"),
        "source_seeds": sorted(seed_attr.get(normalize_keyword(r["keyword"]), set())) or None,
    } for r in rows]
    for group in dataforseo_labs.chunk(child, 500):
        if group:
            supabase.table("keyword_research_keywords").insert(group).execute()

    _prune_runs(client_id)
    return {
        "run_id": run["id"], "keyword_count": len(rows),
        "cluster_count": len(clusters), "cost_usd": round(cost or 0.0, 4),
        "warnings": warnings,
    }


_MIN_SEEDS_TO_REMOVE = 2  # a run must keep at least this many seeds (owner rule)


def remove_seed(client_id: str, run_id: str, seed: str) -> dict:
    """Remove ONE seed from a multi-seed run and take its keywords with it, with
    no re-run / re-bill.

    A keyword is deleted only when the removed seed was its SOLE source (its
    source_seeds becomes empty); a keyword also produced by another seed keeps
    that attribution and stays. Keywords with no attribution (NULL source_seeds —
    the batched keyword_ideas source, or pre-migration rows) are never touched.
    The run's seeds array and rollup counts are recomputed.

    Guards: the run must exist for this client and must have MORE than
    _MIN_SEEDS_TO_REMOVE seeds (so a removal always leaves at least two). Returns
    {seeds, removed_keywords, keyword_count, cluster_count}."""
    supabase = get_supabase()
    runs = (
        supabase.table("keyword_research_runs").select("id, seeds")
        .eq("id", run_id).eq("client_id", client_id).limit(1).execute()
    ).data
    if not runs:
        raise ValueError("run_not_found")
    seeds = list(runs[0].get("seeds") or [])
    if len(seeds) <= _MIN_SEEDS_TO_REMOVE:
        raise ValueError("min_two_seeds")

    target = (seed or "").strip().lower()
    match = next((s for s in seeds if (s or "").strip().lower() == target), None)
    if match is None:
        raise ValueError("seed_not_found")

    kws = (
        supabase.table("keyword_research_keywords")
        .select("id, source_seeds, cluster_label")
        .eq("run_id", run_id).execute()
    ).data or []

    to_delete: list[str] = []
    to_trim: list[tuple[str, list[str]]] = []
    for k in kws:
        srcs = k.get("source_seeds")
        if not srcs:
            continue  # unattributed (ideas / legacy) → never removed by a seed removal
        if not any((x or "").strip().lower() == target for x in srcs):
            continue  # not from this seed
        remaining = [x for x in srcs if (x or "").strip().lower() != target]
        if remaining:
            to_trim.append((k["id"], remaining))
        else:
            to_delete.append(k["id"])

    for group in dataforseo_labs.chunk(to_delete, 200):
        if group:
            supabase.table("keyword_research_keywords").delete().in_("id", group).execute()
    for kid, remaining in to_trim:
        supabase.table("keyword_research_keywords").update(
            {"source_seeds": remaining}).eq("id", kid).execute()

    new_seeds = [s for s in seeds if (s or "").strip().lower() != target]
    remaining_rows = (
        supabase.table("keyword_research_keywords").select("cluster_label")
        .eq("run_id", run_id).execute()
    ).data or []
    keyword_count = len(remaining_rows)
    cluster_count = len({(r.get("cluster_label") or "other") for r in remaining_rows})
    supabase.table("keyword_research_runs").update({
        "seeds": new_seeds,
        "keyword_count": keyword_count,
        "cluster_count": cluster_count,
    }).eq("id", run_id).execute()

    return {
        "seeds": new_seeds,
        "removed_keywords": len(to_delete),
        "keyword_count": keyword_count,
        "cluster_count": cluster_count,
    }


def clear_runs(client_id: str) -> int:
    """Delete ALL keyword research runs for a client (child keyword + report rows
    cascade), so the team can start over. Returns the number of runs deleted."""
    supabase = get_supabase()
    ids = [
        r["id"] for r in (
            supabase.table("keyword_research_runs").select("id")
            .eq("client_id", client_id).execute()
        ).data or []
    ]
    if ids:
        supabase.table("keyword_research_runs").delete().eq("client_id", client_id).execute()
    return len(ids)


def _prune_runs(client_id: str) -> None:
    """Keep the newest _RUNS_KEEP runs per client (child rows cascade). Best-effort."""
    try:
        supabase = get_supabase()
        old = (
            supabase.table("keyword_research_runs").select("id")
            .eq("client_id", client_id).order("created_at", desc=True).execute()
        ).data or []
        stale = [r["id"] for r in old[_RUNS_KEEP:]]
        if stale:
            supabase.table("keyword_research_runs").delete().in_("id", stale).execute()
    except Exception as exc:
        logger.warning("keyword_research.prune_failed", extra={"client_id": client_id, "error": str(exc)})


def enqueue_keyword_research(
    client_id: str,
    seeds: list[str],
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
) -> str:
    """Enqueue a keyword_research async job. Returns the job id."""
    row = (
        get_supabase().table("async_jobs").insert({
            "job_type": "keyword_research",
            "entity_id": client_id,
            "payload": {
                "client_id": client_id, "seeds": seeds,
                "location_code": location_code, "language_code": language_code,
            },
        }).execute()
    ).data[0]
    return row["id"]


async def run_keyword_research_job(job: dict) -> None:
    """async_jobs handler for keyword_research."""
    payload = job.get("payload") or {}
    supabase = get_supabase()
    try:
        result = await run_keyword_research(
            payload.get("client_id") or job.get("entity_id"),
            payload.get("seeds") or [],
            location_code=payload.get("location_code"),
            language_code=payload.get("language_code"),
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except BudgetExceeded:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "budget_exceeded", "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:
        logger.warning("keyword_research.job_failed", extra={"error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()


# ---------------------------------------------------------------------------
# Reads (for the router).
# ---------------------------------------------------------------------------
def list_runs(client_id: str, limit: int = 25) -> list[dict]:
    """Research-run summary rows for a client (no child keywords), newest first."""
    return (
        get_supabase().table("keyword_research_runs")
        .select("id, seeds, location_code, language_code, keyword_count, "
                "cluster_count, cost_usd, status, created_at")
        .eq("client_id", client_id).order("created_at", desc=True).limit(limit).execute()
    ).data or []


def get_run(client_id: str, run_id: str) -> Optional[dict]:
    """A run + its keywords + rebuilt clusters, or None. Scoped to the client."""
    supabase = get_supabase()
    runs = (
        supabase.table("keyword_research_runs").select("*")
        .eq("id", run_id).eq("client_id", client_id).limit(1).execute()
    ).data
    if not runs:
        return None
    kws = (
        supabase.table("keyword_research_keywords").select("*")
        .eq("run_id", run_id)
        .order("opportunity_score", desc=True)
        .limit(settings.keyword_research_idea_limit).execute()
    ).data or []
    clusters = _clusters_from_rows(kws)
    # Recompute the branded-seed advisory on read (deterministic from the stored
    # seeds + the client's name), so re-opening a run still shows the guidance.
    warnings = seed_warnings(
        runs[0].get("seeds") or [], _client_context(client_id).get("name"),
        ratio_threshold=settings.keyword_research_brand_seed_ratio,
    )
    return {"run": runs[0], "keywords": kws, "clusters": clusters, "warnings": warnings}


def _clusters_from_rows(kws: list[dict]) -> list[dict]:
    """Rebuild the cluster summary from stored keyword rows (they carry
    cluster_label), sorted by total volume desc. Pure over the DB read."""
    grouped: dict[str, list[dict]] = {}
    for k in kws:
        grouped.setdefault(k.get("cluster_label") or "other", []).append(k)
    clusters = [{
        "label": label,
        "keyword_count": len(members),
        "total_volume": sum((m.get("volume") or 0) for m in members),
    } for label, members in grouped.items()]
    clusters.sort(key=lambda c: (c["total_volume"], c["keyword_count"]), reverse=True)
    return clusters
