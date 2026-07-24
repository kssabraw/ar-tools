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
from services import dataforseo_labs

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
    stopwords, length ≥ 2. Preserves order. Pure."""
    words = re.findall(r"[a-z0-9]+", normalize_keyword(keyword))
    return [w for w in words if len(w) >= 2 and w not in _STOPWORDS]


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
            get_supabase().table("clients").select("name, rank_tracking_location_code")
            .eq("id", client_id).limit(1).execute()
        ).data
    except Exception as exc:
        logger.warning("keyword_research.client_lookup_failed", extra={"client_id": client_id, "error": str(exc)})
        return {}
    return (rows or [{}])[0] or {}


def _client_location_code(client_id: str) -> Optional[int]:
    return _client_context(client_id).get("rank_tracking_location_code")


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

    use_suggestions = settings.keyword_research_use_suggestions
    use_related = settings.keyword_research_broaden_with_related
    # keyword_ideas stays available but off by default (category drift). Fall back
    # to it only if it's the sole enabled source, so a run always has one.
    use_ideas = settings.keyword_research_broaden_with_ideas or not (use_suggestions or use_related)
    n_calls = (
        (len(seed_list) if use_suggestions else 0)
        + (len(seed_list) if use_related else 0)
        + (1 if use_ideas else 0)
    )
    reserve_budget(max(1, n_calls))

    cost = 0.0

    async def _gather_per_seed(fetch, label):
        """Run a per-seed fetch across all seeds concurrently; collect rows + cost."""
        nonlocal cost
        out: list[dict] = []
        results = await asyncio.gather(
            *[fetch(s) for s in seed_list], return_exceptions=True
        )
        for res in results:
            if isinstance(res, Exception):
                logger.warning(f"keyword_research.{label}_failed",
                               extra={"client_id": client_id, "error": str(res)})
                continue
            rows_i, cost_i = res
            out.extend(rows_i)
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

    # related_keywords returns enriched graph nodes PLUS bare "searches related to"
    # neighbour strings (Google's adjacency layer). Collect both across seeds.
    related_neighbors: list[str] = []
    if use_related:
        results = await asyncio.gather(*[
            dataforseo_labs.fetch_related_keywords(
                s, location_code, language_code,
                depth=settings.keyword_research_related_depth,
                limit=settings.keyword_research_related_limit,
            ) for s in seed_list
        ], return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                logger.warning("keyword_research.related_failed",
                               extra={"client_id": client_id, "error": str(res)})
                continue
            node_rows, neighbors, cost_i = res
            trusted_rows += node_rows
            related_neighbors += neighbors
            cost += cost_i or 0.0

    # Enrich the adjacency neighbours (bare strings) that aren't already present,
    # then merge them as trusted rows — this is where cross-topic terms like
    # "adaptive reuse" enter. One keyword_overview call per ≤700, capped.
    if related_neighbors:
        have = {normalize_keyword(r.get("keyword")) for r in trusted_rows}
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
                trusted_rows.append({
                    "keyword": k, "volume": m.get("volume"), "cpc_usd": m.get("cpc_usd"),
                    "competition_index": m.get("competition_index"),
                    "keyword_difficulty": m.get("keyword_difficulty"),
                    "search_intent": m.get("search_intent"),
                })

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
    warnings = seed_warnings(
        seed_list, client_name, filter_report,
        ratio_threshold=settings.keyword_research_brand_seed_ratio,
        total_results=len(rows),
    )
    if warnings:
        logger.info("keyword_research.seed_warnings",
                    extra={"client_id": client_id, "seeds": seed_list,
                           "filter": filter_report, "warnings": warnings})
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
