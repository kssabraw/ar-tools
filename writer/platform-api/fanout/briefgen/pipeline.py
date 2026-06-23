"""Brief Generator pipeline orchestration (M13 slice 5b).

`generate_brief` runs the answer-engine-first flow end to end:

  sources (Step 1-2) → intent (Step 3 + A1) → title/scope (Step 3.5)
  → main entity (Step 3.6) → MCS H2 skeleton (Steps 7-8, gate-prefiltered)
  → assemble the v2.6 BriefOutput (Step 11).

Deps are injected (`BriefDeps`) so the orchestration is testable; `build_brief_deps`
constructs the real clients, including the DUAL embedding spaces (aio §0 #1): OpenAI
`text-embedding-3-large` for the organic gates + ChatGPT proximity, and Gemini
(RETRIEVAL_* task types) for AIO proximity — the Gemini path is invoked DIRECTLY here,
independent of the app-wide `embedding_provider` (which stays openai). Persona /
authority / H3 / FAQ enrichment (5c) layer onto the BriefOutput after this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .answer_contract import AnswerContract, build_scope_gate, generate_answer_contract
from .assemble import build_brief_output
from .authority import generate_authority_gaps
from .decision_fit import build_decision_fit_directive, detect_partner_factor
from .entity import derive_main_entity
from .faq import generate_faqs
from .gates import prefilter
from .h3 import merge_h3s, select_h3s
from .intent import classify_intent
from .mcs import MCSDeps, MCSResult, ScoredHeading, run_mcs
from .models import BriefOutput
from .persona import generate_persona
from .sources import gather_sources
from .title import generate_title_scope

EmbedFn = Callable[[list[str]], list[list[float]]]


@dataclass
class BriefDeps:
    dfs: object                 # DataForSEOClient (bound to the session location_code)
    scrapeowl: object           # ScrapeOwlClient (discussion-thread content)
    np_extract: object          # spaCy noun-phrase extractor (entity derivation)
    embed_3large: EmbedFn       # OpenAI text-embedding-3-large (gates + ChatGPT proximity)
    embed_aio_query: EmbedFn    # Gemini RETRIEVAL_QUERY (candidate headings)
    embed_aio_doc: EmbedFn      # Gemini RETRIEVAL_DOCUMENT (AIO answer points)
    gen_llm: object             # Haiku — MCS candidate generation
    intent_llm: object          # Haiku — intent + A1 classification
    title_llm: object           # Sonnet — title/scope
    contract_llm: object        # Opus — answer contract (query understanding guardrail)


def build_brief_deps(location_code: int) -> BriefDeps:
    """Construct the real egress clients (lazy imports keep the pure modules importable
    without httpx/openai/spaCy). Builds the two Gemini embedders (asymmetric retrieval
    task types) directly — independent of `embedding_provider`."""
    from openai import OpenAI

    from fanout.config import get_settings
    from fanout.dataforseo import get_dataforseo
    from fanout.llm.anthropic_client import AnthropicLLM
    from fanout.llm.embeddings import GeminiEmbedder, OpenAIEmbedder
    from fanout.sie.scrapeowl_client import ScrapeOwlClient

    from .entity import build_np_extractor

    s = get_settings()
    large = OpenAIEmbedder(OpenAI(api_key=s.openai_api_key), s.brief_embedding_model_large)
    gem_q = GeminiEmbedder(
        api_key=s.gemini_api_key, model=s.gemini_embedding_model,
        output_dim=s.gemini_embedding_dim, task_type=s.brief_aio_query_task_type,
        max_workers=s.gemini_embedding_max_workers,
    )
    gem_d = GeminiEmbedder(
        api_key=s.gemini_api_key, model=s.gemini_embedding_model,
        output_dim=s.gemini_embedding_dim, task_type=s.brief_aio_doc_task_type,
        max_workers=s.gemini_embedding_max_workers,
    )
    return BriefDeps(
        dfs=get_dataforseo(location_code),
        scrapeowl=ScrapeOwlClient(
            s.scrapeowl_api_key, s.scrapeowl_base_url,
            cost_per_scrape=s.scrapeowl_cost_per_scrape,
            cost_per_scrape_premium=s.scrapeowl_cost_per_scrape_premium,
            premium_on_5xx=s.sie_scrapeowl_premium_on_500,
            max_attempts=s.sie_max_transport_attempts,
        ),
        np_extract=build_np_extractor(),
        embed_3large=large.embed,
        embed_aio_query=gem_q.embed,
        embed_aio_doc=gem_d.embed,
        gen_llm=AnthropicLLM(api_key=s.anthropic_api_key, model=s.brief_gen_model),
        intent_llm=AnthropicLLM(api_key=s.anthropic_api_key, model=s.brief_intent_model),
        title_llm=AnthropicLLM(api_key=s.anthropic_api_key, model=s.brief_title_model),
        contract_llm=AnthropicLLM(api_key=s.anthropic_api_key, model=s.brief_answer_contract_model),
    )


def generate_brief(
    keyword: str, *, location_code: int, deps: BriefDeps, intent_override: str | None = None,
    supporting_keywords: list[str] | None = None,
) -> BriefOutput:
    """Run the brief pipeline for one keyword and return the v2.6 BriefOutput. Raises on
    a load-bearing failure (SERP / title) — there is no degraded-brief fallback (owner
    rule); the caller (the metered job) marks the run errored. `intent_override` (a locked
    cluster intent) forces the intent classification. `supporting_keywords` (the cluster's
    secondary keywords) feed the H3 subtopic pool and a post-assembly coverage audit so the
    clustered research is used + surfaced rather than silently dropped."""
    sources = gather_sources(keyword, deps.dfs, scrapeowl=deps.scrapeowl)
    serp_titles = [o.get("title") or "" for o in sources.organic]
    serp_metas = [o.get("description") or "" for o in sources.organic]

    intent = classify_intent(
        keyword, serp_titles=serp_titles, serp_h2s=[], paa=sources.paa, llm=deps.intent_llm,
        intent_override=intent_override,
    )
    title = generate_title_scope(
        keyword, intent_type=intent.intent_type, serp_titles=serp_titles,
        serp_h1s=serp_titles, serp_metas=serp_metas, llm_answers=sources.llm_answers,
        llm=deps.title_llm,
    )
    entity = derive_main_entity(
        aio_answer=sources.aio.get("answer_text", ""), aio_present=bool(sources.aio.get("present")),
        title=title.title, keyword=keyword, np_extract=deps.np_extract,
        embed_fn=deps.embed_3large, comparison_intent=(intent.intent_type == "comparison"),
    )

    # Answer contract (Opus): structured query understanding -> guardrail for MCS. The
    # answer_heading becomes the guaranteed lead H2; must_not_cover gates the candidate pool.
    contract = generate_answer_contract(
        keyword, title=title.title, scope_statement=title.scope_statement or "",
        intent_type=intent.intent_type, aio_answer=sources.aio.get("answer_text", ""),
        chatgpt_answer=sources.llm_answers.get("chat_gpt") or "", llm=deps.contract_llm,
    )
    scope_gate = build_scope_gate(contract, deps.embed_3large)

    topic_vec = deps.embed_3large([keyword])[0]

    def gate_fn(cands: list[str]) -> list[str]:
        # Eligibility pre-filter (X.3): on-topic to the keyword + not a bare restatement
        # of the title (cross-candidate redundancy is handled by MCS coverage), then the
        # answer-contract scope gate drops candidates that fall under must_not_cover.
        results = prefilter(
            cands, topic_vec=topic_vec, references=[title.title], main_entity=entity,
            embed_fn=deps.embed_3large,
        )
        return scope_gate([r.heading for r in results if r.passed])

    tpl = intent.intent_format_template
    max_h2 = tpl.get("max_h2_count", 12)
    mcs = run_mcs(
        entity=entity.canonical, aio=sources.aio,
        chatgpt_answer=sources.llm_answers.get("chat_gpt"), keyword=keyword,
        deps=MCSDeps(
            gen_llm=deps.gen_llm, embed_aio_query=deps.embed_aio_query,
            embed_aio_doc=deps.embed_aio_doc, embed_3large=deps.embed_3large,
        ),
        min_count=tpl.get("min_h2_count", 3), max_count=max_h2,
        gate_fn=gate_fn,
    )
    _prepend_answer_lead(mcs, contract, max_count=max_h2)

    h2_texts = [s.text for s in mcs.selected]
    reddit_summaries = [d.get("content") or d.get("title") or "" for d in sources.reddit]

    # Step 6 persona (informational; degrades to empty) — gap questions feed FAQ + H3s.
    persona = generate_persona(
        keyword, intent_type=intent.intent_type, title=title.title,
        scope_statement=title.scope_statement, serp_h1s=serp_titles, serp_metas=serp_metas,
        candidate_headings=h2_texts, llm=deps.intent_llm,
    )
    # Step 9 authority-gap H3s (enrichment; degrades to []) — differentiation under the H2s.
    authority_h3s = generate_authority_gaps(
        keyword, title=title.title, scope_statement=title.scope_statement,
        intent_type=intent.intent_type, h2_texts=h2_texts, reddit_summaries=reddit_summaries,
        llm=deps.gen_llm,
    )
    # Steps 10/10.5 FAQ generation + intent gate.
    faqs, faq_meta = generate_faqs(
        paa=sources.paa, discussions=sources.reddit, persona_gaps=persona.gap_questions,
        intent_type=intent.intent_type, title=title.title, scope_statement=title.scope_statement,
        primary_goal=persona.primary_goal, heading_texts=[title.title, *h2_texts],
        embed_3large=deps.embed_3large, classify_llm=deps.gen_llm, concern_llm=deps.gen_llm,
    )
    # Step 8.6 regular H3 selection (coverage-graph regions) + merge with authority H3s.
    # The cluster's supporting keywords join the H3 candidate pool — the band/region/MMR
    # filters decide which actually land as subtopics (so good clustered keywords get USED).
    regular_by_h2 = select_h3s(
        h2_texts=h2_texts, candidates=_h3_candidates(sources, persona, supporting_keywords),
        scope_statement=title.scope_statement, embed_3large=deps.embed_3large,
    )
    authority_by_h2: dict[str, list[dict]] = {}
    for a in authority_h3s:
        authority_by_h2.setdefault(a["parent_h2_text"], []).append(a)
    h3s_by_h2 = merge_h3s(regular_by_h2, authority_by_h2)

    # Decision-fit (A3 source -> A4 gate -> A5 emit) — only on a qualifying multi-answer query.
    directive = None
    if intent.decision_fit_qualifies and h2_texts:
        heading_dicts = ([{"text": t, "source": "mcs"} for t in h2_texts]
                         + [{"text": a["text"], "source": "authority_gap_sme"} for a in authority_h3s])
        directive = build_decision_fit_directive(
            intent.decision_fit_detection, anchor_h2_text=h2_texts[0],
            persona_gaps=persona.gap_questions, paa=sources.paa, reddit=sources.reddit,
            partner_factor=detect_partner_factor(intent.intent_type, heading_dicts),
            llm=deps.intent_llm,
        )

    output = build_brief_output(
        keyword=keyword, intent=intent, title=title, entity=entity, mcs=mcs, sources=sources,
        persona=persona, faqs=faqs, h3s_by_h2=h3s_by_h2, decision_fit_directive=directive,
        extra_metadata={**faq_meta, "answer_contract": contract.as_metadata()},
    )

    # Coverage audit (2b): which clustered keywords a heading covers vs. fell through.
    if supporting_keywords:
        from fanout.config import get_settings

        from .coverage import audit

        heading_texts = [h["text"] for h in output.heading_structure if h.get("text")]
        heading_texts += [f.get("question", "") for f in output.faqs if f.get("question")]
        used_texts = [
            h["text"] for h in output.heading_structure if h.get("source") == "cluster_keyword"
        ]
        output.metadata["cluster_keyword_coverage"] = audit(
            supporting_keywords, heading_texts=heading_texts, used_texts=used_texts,
            embed_fn=deps.embed_3large, threshold=get_settings().brief_coverage_threshold,
        )
    return output


def _prepend_answer_lead(mcs: MCSResult, contract: AnswerContract, *, max_count: int) -> None:
    """Make the answer contract's `answer_heading` the guaranteed lead H2 (in place):
    drop any selected heading that merely restates it (case-insensitive containment), insert
    it first, and trim back to `max_count`. No-op without an answer_heading."""
    head = (contract.answer_heading or "").strip()
    if not head:
        return
    low = head.lower()
    kept = [s for s in mcs.selected if low not in s.text.lower() and s.text.lower() not in low]
    lead = ScoredHeading(text=head, point_cosines=[], chatgpt_cosine=0.0, aio_headline=0.0, blended=1.0)
    mcs.selected = [lead, *kept][:max_count]


def _h3_candidates(sources, persona, supporting_keywords: list[str] | None = None) -> list:
    """Build the H3 subtopic candidate pool (info-gain sources: PAA + autocomplete +
    suggestions + persona gaps + the cluster's supporting keywords), deduped."""
    from .h3 import H3Candidate

    seen: set[str] = set()
    out: list = []
    def _add(text: str, src: str) -> None:
        t = (text or "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(H3Candidate(t, src))

    for q in sources.paa:
        _add(q, "paa")
    for s in sources.autocomplete:
        _add(s, "autocomplete")
    for s in sources.suggestions:
        _add(s, "keyword_suggestion")
    for g in persona.gap_questions:
        _add(g.get("question"), "persona_gap")
    for k in supporting_keywords or []:
        _add(k, "cluster_keyword")
    return out
