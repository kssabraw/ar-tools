"""Per-topic editorial orchestrator (PRD §7.10.1–.3).

Runs Claude Opus 4.7 once per topic. The orchestrator receives the topic's
statistical groupings, each grouping's MMR representative + that representative's
SERP, and applies merge / split / promote-demote / route / drop to turn the
groupings into a coherent plan of articles (plus topic-level coverage gaps).

Validation runs after the call (PRD §16.2): malformed JSON or a missing tool
block triggers one reprompt, then a degraded fallback to statistical passthrough
(one article per grouping) for that topic only. Business-rule failures drop the
offending item and continue.

An article only becomes a cluster if it has a non-empty primary AND at least one
supporting keyword (PRD §15.2 acceptance #3). A primary with no supporting
keywords is left active+unassigned (the "Unassigned" bucket) rather than spawning
a degenerate one-keyword cluster — no keyword data is lost.
"""

import logging
from concurrent.futures import as_completed
from dataclasses import replace

from fanout.concurrency import ContextThreadPoolExecutor as ThreadPoolExecutor
from fanout.dataforseo import DataForSEOClient
from fanout.llm import AnthropicError, AnthropicLLM

from .dedup import cross_topic_dedup
from .models import (
    DEFAULT_INTENT,
    INTENTS,
    ArticleRecord,
    CoverageGapRecord,
    DroppedKeyword,
    GroupingInput,
    PlanResult,
    TopicInput,
    TopicPlan,
)
from .orphan_promotion import promote_orphans
from .peer_grouping import group_by_peer_entity
from .serp import fetch_candidate_serps
from .split import split_oversized_articles

logger = logging.getLogger(__name__)

_TOOL_NAME = "emit_article_plan"
_TOOL_DESCRIPTION = (
    "Emit the article plan for this topic: the articles to create, the keywords "
    "to drop, and any coverage gaps. Use ONLY keywords drawn from the provided "
    "groupings; never invent keywords."
)

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "primary_keyword": {"type": "string"},
                    "supporting_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "intent": {"type": "string", "enum": list(INTENTS)},
                    "source_statistical_grouping_id": {"type": "string"},
                    "orchestrator_notes": {"type": "string"},
                },
                "required": [
                    "primary_keyword",
                    "supporting_keywords",
                    "intent",
                    "orchestrator_notes",
                ],
            },
        },
        "dropped_keywords": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["keyword", "reason"],
            },
        },
        "coverage_gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "suggested_title": {"type": "string"},
                    "target_keyword": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["suggested_title", "target_keyword", "rationale"],
            },
        },
    },
    "required": ["articles", "dropped_keywords", "coverage_gaps"],
}

_SYSTEM = """You are the editorial orchestrator for a niche authority site. Your job is to turn statistical keyword groupings into a coherent plan of ARTICLES — deciding which keywords share one URL, which deserve their own, and which to drop.

For each grouping, choose one outcome:
- MERGE keywords into one article when they share search intent AND the candidate primaries' top-3 SERP URLs overlap (≥3 of 10) AND the grouping is topically cohesive. Primary = the highest-volume or most-central keyword; the rest become supporting keywords.
- SPLIT a grouping into multiple articles when its keywords cluster statistically but have distinct intents OR their SERPs barely overlap (<2 of 10). You decide the split lines.
- PROMOTE + DEMOTE when one broad keyword has the SERP presence and several narrow children share its SERP space but lack standalone traction: one article, broad keyword as primary, narrow children become supporting keywords.
- ROUTE a keyword into a different grouping within this topic when it editorially belongs there; just place it in the right article.
- DROP a keyword that doesn't justify article-level treatment (no SERP traction, off-niche, redundant). Report it in dropped_keywords with a short reason. Dropped keywords are stored, not deleted.

Infer each article's intent from its SERP composition: product/category pages → transactional or commercial; comparison/"best"/"vs" articles → comparison; how-to/explainer/definition content → informational; brand/login/official-site results → navigational.

Also flag COVERAGE GAPS: article concepts a topical-authority site about this subject should cover but that no grouping surfaced. Give each a suggested title, a target keyword, and a one-sentence rationale.

Rules:
- Use ONLY keywords that appear in the provided groupings. Never invent keywords.
- Every article needs a non-empty primary AND at least one supporting keyword. A keyword with no natural companions should be dropped or left out, not made into a one-keyword article.
- Do NOT produce an H2 outline — the writer module generates each article's headings at write time.
- Emit your answer through the emit_article_plan tool only."""


def _norm(kw: str) -> str:
    return " ".join((kw or "").strip().lower().split())


def _grouping_block(g: GroupingInput, serp_by_keyword: dict[str, list[str]]) -> str:
    urls = serp_by_keyword.get(g.representative) or serp_by_keyword.get(_norm(g.representative))
    serp_lines = "\n".join(f"      - {u}" for u in (urls or [])[:10]) or "      (SERP unavailable)"
    kw_lines = "\n".join(f"    - {k}" for k in g.keywords)
    return (
        f"  Grouping {g.id} (size {g.size}, cohesion {g.cohesion:.3f})\n"
        f"  Candidate primary (MMR representative): {g.representative}\n"
        f"  Top SERP URLs for the candidate primary:\n{serp_lines}\n"
        f"  Keywords:\n{kw_lines}"
    )


def _build_user_prompt(topic: TopicInput, serp_by_keyword: dict[str, list[str]]) -> str:
    groupings = "\n\n".join(_grouping_block(g, serp_by_keyword) for g in topic.groupings)
    return (
        f"TOPIC: {topic.name}\n"
        f"Relationship to the seed: {topic.relationship_type}\n"
        f"Rationale: {topic.rationale or '(none)'}\n\n"
        f"STATISTICAL GROUPINGS ({len(topic.groupings)}):\n\n{groupings}\n\n"
        "Produce the article plan for this topic via the emit_article_plan tool."
    )


def _passthrough_plan(topic: TopicInput, serp_by_keyword: dict[str, list[str]],
                      *, reason: str) -> TopicPlan:
    """Degraded fallback (PRD §16.2): one article per grouping, representative as
    primary, the rest as supporting. Only groupings with ≥2 keywords become
    articles; a solo-keyword grouping is left unassigned."""
    plan = TopicPlan(topic_id=topic.id, degraded=True)
    for g in topic.groupings:
        supporting = [k for k in g.keywords if _norm(k) != _norm(g.representative)]
        if not supporting:
            continue
        plan.articles.append(
            ArticleRecord(
                topic_id=topic.id,
                primary_keyword=g.representative,
                supporting_keywords=supporting,
                intent=DEFAULT_INTENT,
                suggested_h2s=[],
                source_statistical_grouping_id=g.id,
                orchestrator_notes=f"Degraded passthrough ({reason}).",
                serp_top_urls=serp_by_keyword.get(g.representative, []),
            )
        )
    plan.log = {
        "degraded": True,
        "reason": reason,
        "article_count": len(plan.articles),
        "grouping_count": len(topic.groupings),
    }
    logger.warning(
        "degraded",
        extra={"event": "degraded", "step": "orchestrator", "topic_id": topic.id,
               "reason": reason, "articles": len(plan.articles)},
    )
    return plan


def _validate_and_build(
    topic: TopicInput,
    raw: dict,
    serp_by_keyword: dict[str, list[str]],
) -> TopicPlan:
    """Turn validated tool output into a TopicPlan. Business-rule failures drop
    the offending item (PRD §16.2). Keyword references are resolved against the
    topic's actual pool by normalized text; unknown keywords are discarded."""
    plan = TopicPlan(topic_id=topic.id)
    pool = {_norm(k): k for g in topic.groupings for k in g.keywords}
    pool[_norm("")] = ""  # guard
    rep_serps = serp_by_keyword

    dropped_logged: list[dict] = []
    for art in raw.get("articles") or []:
        if not isinstance(art, dict):
            continue
        primary_raw = str(art.get("primary_keyword") or "").strip()
        primary = pool.get(_norm(primary_raw))
        if not primary:
            dropped_logged.append({"primary": primary_raw, "why": "primary not in pool/empty"})
            continue
        # Resolve supporting keywords to the pool; drop unknowns and the primary.
        supporting: list[str] = []
        seen = {_norm(primary)}
        for sk in art.get("supporting_keywords") or []:
            resolved = pool.get(_norm(str(sk)))
            if resolved and _norm(resolved) not in seen:
                supporting.append(resolved)
                seen.add(_norm(resolved))
        if not supporting:
            # No companions -> not a cluster; leave primary active+unassigned.
            dropped_logged.append({"primary": primary, "why": "no supporting keywords"})
            continue
        intent = str(art.get("intent") or "").strip().lower()
        if intent not in INTENTS:
            intent = DEFAULT_INTENT
        # H2 outline is owned by the writer module, not the orchestrator. The field
        # is kept on the record (always empty here) so the writer can fill it later.
        grouping_id = art.get("source_statistical_grouping_id")
        plan.articles.append(
            ArticleRecord(
                topic_id=topic.id,
                primary_keyword=primary,
                supporting_keywords=supporting,
                intent=intent,
                suggested_h2s=[],
                source_statistical_grouping_id=str(grouping_id) if grouping_id else None,
                orchestrator_notes=str(art.get("orchestrator_notes") or "").strip(),
                serp_top_urls=rep_serps.get(primary, []),
            )
        )

    for d in raw.get("dropped_keywords") or []:
        if not isinstance(d, dict):
            continue
        kw = pool.get(_norm(str(d.get("keyword"))))
        if kw:
            plan.dropped.append(DroppedKeyword(keyword=kw, reason=str(d.get("reason") or "").strip()))

    for gap in raw.get("coverage_gaps") or []:
        if not isinstance(gap, dict):
            continue
        title = str(gap.get("suggested_title") or "").strip()
        if not title:
            continue
        plan.gaps.append(
            CoverageGapRecord(
                suggested_title=title,
                target_keyword=(str(gap.get("target_keyword")).strip()
                                if gap.get("target_keyword") else None),
                rationale=str(gap.get("rationale") or "").strip(),
            )
        )

    plan.log = {
        "degraded": False,
        "article_count": len(plan.articles),
        "gap_count": len(plan.gaps),
        "dropped_count": len(plan.dropped),
        "skipped_items": dropped_logged,
    }
    return plan


def plan_topic(
    topic: TopicInput,
    serp_by_keyword: dict[str, list[str]],
    orchestrator: AnthropicLLM,
) -> TopicPlan:
    """Plan one topic. One reprompt on a transport/shape failure, then degrade to
    passthrough for this topic only (PRD §16.2)."""
    if not topic.groupings:
        return TopicPlan(topic_id=topic.id, log={"degraded": False, "article_count": 0,
                                                 "note": "no groupings"})
    user = _build_user_prompt(topic, serp_by_keyword)
    last_error: str | None = None
    for attempt in range(2):
        prompt = user if last_error is None else (
            f"{user}\n\nYour previous response could not be used: {last_error}\n"
            "Return a corrected plan via the emit_article_plan tool."
        )
        try:
            raw = orchestrator.call_tool(
                system=_SYSTEM,
                user=prompt,
                tool_name=_TOOL_NAME,
                tool_description=_TOOL_DESCRIPTION,
                input_schema=_INPUT_SCHEMA,
                purpose="article_orchestrator",
            )
        except AnthropicError as exc:
            last_error = str(exc)
            continue
        plan = _validate_and_build(topic, raw, serp_by_keyword)
        return plan
    return _passthrough_plan(topic, serp_by_keyword, reason=last_error or "orchestrator failed")


def _chunk(items: list, size: int) -> list[list]:
    size = max(1, size)
    return [items[i : i + size] for i in range(0, len(items), size)]


def _merge_chunk_plans(topic_id: str, chunk_plans: list[TopicPlan]) -> TopicPlan:
    """Combine a topic's per-chunk plans into one. The topic counts as degraded
    only if *every* chunk degraded (a single bad chunk doesn't sink the silo).
    Coverage gaps are deduped by title since each chunk flags independently."""
    merged = TopicPlan(topic_id=topic_id)
    seen_gap: set[str] = set()
    degraded_chunks = 0
    for cp in chunk_plans:
        merged.articles.extend(cp.articles)
        merged.dropped.extend(cp.dropped)
        for g in cp.gaps:
            key = _norm(g.suggested_title)
            if key and key not in seen_gap:
                seen_gap.add(key)
                merged.gaps.append(g)
        if cp.degraded:
            degraded_chunks += 1
    merged.degraded = bool(chunk_plans) and degraded_chunks == len(chunk_plans)
    merged.log = {
        "degraded": merged.degraded,
        "chunks": len(chunk_plans),
        "degraded_chunks": degraded_chunks,
        "article_count": len(merged.articles),
        "gap_count": len(merged.gaps),
        "dropped_count": len(merged.dropped),
    }
    return merged


def direct_plan_topic(topic: TopicInput) -> TopicPlan:
    """Direct mode (no LLM): every grouping becomes an article — representative as
    primary, the rest as supporting keywords. Singletons are included as
    one-keyword articles (deliberate; the user opted to keep the long tail). Not
    degraded — this is an intentional path, not a fallback. Intent defaults to
    informational; H2 outlines are not produced here — the writer module owns them."""
    plan = TopicPlan(topic_id=topic.id, degraded=False)
    for g in topic.groupings:
        supporting = [k for k in g.keywords if _norm(k) != _norm(g.representative)]
        plan.articles.append(
            ArticleRecord(
                topic_id=topic.id,
                primary_keyword=g.representative,
                supporting_keywords=supporting,
                intent=DEFAULT_INTENT,
                suggested_h2s=[],
                source_statistical_grouping_id=g.id,
                orchestrator_notes="Direct mode (statistical grouping, no orchestrator).",
                serp_top_urls=[],
            )
        )
    plan.log = {"degraded": False, "direct": True, "article_count": len(plan.articles)}
    return plan


def run_article_planning(
    *,
    topics: list[TopicInput],
    dfs: DataForSEOClient,
    orchestrator: AnthropicLLM,
    embed_fn,
    candidate_serp_top_n: int = 10,
    candidate_serp_max_workers: int = 8,
    candidate_serp_time_budget_s: float = 120.0,
    groupings_per_call: int = 12,
    max_workers: int = 5,
    dedup_primary_cosine_threshold: float = 0.85,
    dedup_serp_overlap_min: float = 2 / 3,
    direct: bool = False,
    split_oversized: bool = True,
    split_min_keywords: int = 40,
    split_resolution: float = 1.5,
    split_edge_threshold: float = 0.55,
    split_min_subarticle_size: int = 5,
    peer_grouping: bool = True,
    peer_min_keywords: int = 1,
    seed_terms: list[str] | None = None,
    peer_terms: list[str] | None = None,
    promote_orphan_keywords: bool = True,
    orphan_promotion_min_score: float = 0.0,
) -> PlanResult:
    """Full §7.10 pass: SERP for each candidate primary -> per-silo orchestrator
    (chunked + parallel) -> cross-topic dedup. Returns the assembled plan;
    persistence is the caller's job.

    With `direct=True`, skips the SERP fetch and the LLM orchestrator entirely:
    every grouping (incl. singletons) becomes an article, then cross-topic dedup
    collapses cross-silo duplicates. Fast/cheap/deterministic, maximal article
    count, no intent/H2 inference.

    Each silo is planned in chunks of `groupings_per_call` groupings so no single
    Opus call overruns its token/timeout budget at scale (200+ groupings); chunks
    run in parallel. A chunk failure degrades only that chunk to passthrough; a
    topic is degraded only if all its chunks did. The caller treats an all-topics-
    degraded run as an error state (PRD §16.2 failure table)."""
    if direct:
        result = PlanResult()
        for topic in topics:
            result.per_topic.append(direct_plan_topic(topic))
        if peer_grouping:
            group_by_peer_entity(result, seed_terms=seed_terms or [],
                                 peer_terms=peer_terms or [],
                                 min_keywords=peer_min_keywords)
        if split_oversized:
            split_oversized_articles(
                result, embed_fn=embed_fn, min_keywords=split_min_keywords,
                resolution=split_resolution, edge_threshold=split_edge_threshold,
                min_subarticle_size=split_min_subarticle_size,
            )
        cross_topic_dedup(
            result,
            topic_embeddings={t.id: t.embedding for t in topics},
            embed_fn=embed_fn,
            primary_cosine_threshold=dedup_primary_cosine_threshold,
            serp_overlap_min=dedup_serp_overlap_min,
        )
        if promote_orphan_keywords:
            promote_orphans(result, topics, min_score=orphan_promotion_min_score)
        logger.info(
            "step_complete",
            extra={"event": "step_complete", "step": "article_planning_direct",
                   "topic_count": len(topics), **result.counts()},
        )
        return result

    representatives = [g.representative for t in topics for g in t.groupings]
    serp = fetch_candidate_serps(
        keywords=representatives,
        dfs=dfs,
        top_n=candidate_serp_top_n,
        max_workers=candidate_serp_max_workers,
        time_budget_s=candidate_serp_time_budget_s,
    )
    result = PlanResult(
        degraded_notes=list(serp.degraded_notes), timed_out=serp.timed_out
    )

    # One task per (topic, grouping-chunk). A topic with no groupings yields no
    # tasks and a non-degraded empty plan below.
    tasks: list[tuple[str, TopicInput]] = []
    for topic in topics:
        for chunk in _chunk(topic.groupings, groupings_per_call):
            tasks.append((topic.id, replace(topic, groupings=chunk)))

    chunk_results: dict[str, list[TopicPlan]] = {t.id: [] for t in topics}
    if tasks:
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
            futures = {
                ex.submit(plan_topic, sub, serp.per_keyword, orchestrator): tid
                for tid, sub in tasks
            }
            for fut in as_completed(futures):
                tid = futures[fut]
                chunk_results[tid].append(fut.result())

    for topic in topics:
        chunks = chunk_results[topic.id]
        if not chunks:
            result.per_topic.append(
                TopicPlan(topic_id=topic.id,
                          log={"degraded": False, "article_count": 0, "note": "no groupings"})
            )
        else:
            result.per_topic.append(_merge_chunk_plans(topic.id, chunks))

    if peer_grouping:
        group_by_peer_entity(result, seed_terms=seed_terms or [],
                             peer_terms=peer_terms or [],
                             min_keywords=peer_min_keywords)
    if split_oversized:
        split_oversized_articles(
            result, embed_fn=embed_fn, min_keywords=split_min_keywords,
            resolution=split_resolution, edge_threshold=split_edge_threshold,
            min_subarticle_size=split_min_subarticle_size,
        )
    cross_topic_dedup(
        result,
        topic_embeddings={t.id: t.embedding for t in topics},
        embed_fn=embed_fn,
        primary_cosine_threshold=dedup_primary_cosine_threshold,
        serp_overlap_min=dedup_serp_overlap_min,
    )
    if promote_orphan_keywords:
        promote_orphans(result, topics, min_score=orphan_promotion_min_score)

    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "article_planning",
               "topic_count": len(topics), "chunk_count": len(tasks), **result.counts(),
               "degraded": any(p.degraded for p in result.per_topic),
               "timed_out": result.timed_out},
    )
    return result


def all_degraded(result: PlanResult) -> bool:
    """True if every planned topic fell back to passthrough — the §16.2
    'orchestrator fails on every silo' condition. Per-silo passthrough is a
    safety net for partial failure; when *every* silo degrades the orchestrator
    is broken (the output would just be M4's clustering relabeled), so the caller
    surfaces an error rather than shipping it. A topic with no groupings yields a
    non-degraded empty plan and doesn't count."""
    plans = [p for p in result.per_topic if p.log.get("note") != "no groupings"]
    return bool(plans) and all(p.degraded for p in plans)
