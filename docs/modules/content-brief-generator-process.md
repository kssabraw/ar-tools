# Content Brief Generator — Process Reference

**Status:** Living reference (describes the code as built)
**Module:** `writer/pipeline-api/modules/brief/`
**Schema version:** `2.6` (`SCHEMA_VERSION` in `pipeline.py`; the orchestrator's `EXPECTED_MODULE_VERSIONS["brief"]` must match)
**Authoritative spec:** `docs/modules/content-brief-generator-prd-v2_0.md` (filename keeps the `-v2_0` suffix; its header is the canonical version — currently v2.3)

> This document explains *how the Brief Generator actually runs* — the order of
> steps, what each does, and where it lives in the code. It is a process map,
> not a spec. When the PRD and this doc disagree about intended behavior, the
> PRD wins; when this doc and the code disagree about actual behavior, the code
> wins (and this doc should be corrected). `pipeline.py`'s `SCHEMA_VERSION` and
> the orchestrator remain the source of truth for versions. (Note: several
> docstrings still say "v2.0" while the live `SCHEMA_VERSION` is `2.6` — the
> constant is authoritative.)

---

## 1. Where the Brief Generator sits in the pipeline

The Brief Generator is the **first** of the five Blog Writer pipeline modules.
It runs inside the private **pipeline-api** and is dispatched by the
**platform-api** orchestrator. Everything downstream consumes its output.

```
BRIEF  →  sie  →  research  →  writer  →  sources_cited
```

- **Input:** a keyword (plus location and a few flags). The brief is
  **client-agnostic** — `client_id` is audit-only and never feeds LLM inputs
  or scopes the cache, so two clients running the same keyword share a cached
  brief.
- **Output:** a fully structured plan — title, H1, scope statement, intent
  classification, searcher persona, the H2/H3 heading architecture, FAQs,
  format directives, discarded headings, silo candidates, and rich metadata.
- **Downstream consumers:** SIE (terms/entities) and Research (citations) build
  on the heading structure; the Writer turns the whole plan into prose. The
  Writer specifically prefers Research's *enriched* heading structure but falls
  back to the brief's.

**Entry point:** `routers/router.py` → `run_brief()` in `pipeline.py`.

The Brief Generator is the most external-data-heavy module in the pipeline: it
calls DataForSEO (SERP, Reddit, autocomplete, keyword suggestions, LLM fan-out)
plus Perplexity (Reddit + customer-review synthesis), OpenAI embeddings
(`text-embedding-3-large`), and Claude (intent, title/scope, persona, scoring,
authority gaps, verification, critique).

---

## 2. Inputs and outputs

### Request (`BriefRequest`, `models/brief.py`)

| Field | Default | Purpose |
|---|---|---|
| `run_id` | — | Idempotency / correlation key from platform-api |
| `attempt` | 1 | Retry attempt counter |
| `keyword` | — | Seed keyword (1–150 chars; empty or over-length aborts) |
| `location_code` | 2840 (US) | DataForSEO location; part of the cache key |
| `client_id` | none | Audit only — never feeds LLM inputs, never scopes the cache |
| `force_refresh` | false | Skip the cache lookup and overwrite the cached row |
| `intent_override` | none | Force the intent classification |

### Response (`BriefResponse`)

All models lock to `extra='forbid'` (strict validation per PRD §12). Top-level
fields include: `keyword`, `title`, `h1`, `scope_statement`, `title_rationale`,
`intent_type`, `intent_confidence`, `intent_review_required`, `persona`,
`heading_structure`, `faqs`, `format_directives`, `discarded_headings`,
`silo_candidates`, `intent_format_template`, the v2.6 blind-spot side-channels
(`reddit_insights`, `customer_review_insights`, `llm_disagreement`,
`editorial_critique`), and `metadata`.

---

## 3. The process, step by step

Orchestration lives in `run_brief()` (`pipeline.py`). The overall shape:

```
[Cache lookup] → Steps 1–2 (parallel) → Step 3 → Step 3.5 →
Step 4 (pass 1) → Step 5 (gates + graph + regions) → Step 6 (persona) →
Step 4 (pass 2 w/ persona gap) → Step 5 augmentation → Step 7 / 7.5 / 7.6 →
Step 8 (MMR) → Step 8.5 → Step 11 framing → Step 8.6 (H3) → Step 9 (authority) →
Step 11.5 → Step 8.5b / 8.7 → Step 10 (FAQ + 10.5 gate) → Step 11 (assembly) →
Step 12 (silos) → assemble response → cache write
```

A recurring design rule: candidates flow through **gates** (relevance,
restatement, region, scope, parent-fit) that either keep them, route them to
silos, or record them as discarded — almost nothing is silently dropped.

### Cache lookup
Unless `force_refresh` is set, look up a cached brief by `(keyword,
location_code)`. A cache hit rehydrates straight into a `BriefResponse`; a
hydrate failure (e.g. older schema, since `extra='forbid'`) is treated as a
miss and the full pipeline runs.

### Steps 1 & 2 — Data acquisition (parallel)
All external fetches fire concurrently:
- **SERP organic** (depth 20) — the only **hard dependency**: 0 organic
  results aborts with `serp_no_results`.
- **Reddit SERP, autocomplete, keyword suggestions** — best-effort
  (`_swallow`); empty on failure.
- **LLM fan-out** across ChatGPT / Claude / Gemini / Perplexity — each captures
  fan-out queries plus a response body; failures flag that LLM unavailable.
- **Perplexity Reddit research** (v2.4) and **customer-review research** (v2.6)
  — synthesized insight documents feeding the Authority Agent; both degrade to
  `available=False` and never abort.

Parsing then produces SERP headings/signals/PAA questions/titles/meta
descriptions, SERP heading stats, competitor domains, and (from the fan-out
bodies) per-LLM subtopic extractions.

### Step 3 — Intent classification (`classify_intent`)
Classifies the keyword into one of eight intents (informational, listicle,
how-to, comparison, ecom, local-seo, news, informational-commercial) using
signals, titles, and the top-3 domains. Honors `intent_override`. Emits a
confidence and a `review_required` flag.

### Step 3.5 — Title + scope statement (`generate_title_and_scope`)
Generates the SEO title, the on-page H1, the scope statement (the topical
boundary every later gate measures against), and a title rationale — grounded
in SERP titles/H1s/meta descriptions and the fan-out bodies.

### Step 4 (pass 1) — Candidate aggregation (`aggregate_candidates`)
Merges heading candidates from every source (SERP stats, PAA, autocomplete,
keyword suggestions, LLM fan-out queries, LLM-response subtopics) with
Levenshtein dedup. Zero candidates aborts with `no_candidates`.

### Step 5 — Embedding + relevance gates (`embed_with_gates`)
Embeds the title and all candidates (`text-embedding-3-large`) and applies two
gates: a **relevance floor** (cosine to title too low → off-topic) and a
**restatement ceiling** (cosine too high → just restates the title). No
survivors aborts with `all_below_threshold`.

### Step 6 — Searcher persona (`generate_persona`)
Builds a hypothetical-searcher persona (description, background assumptions,
primary goal) and a set of **gap questions** the SERP under-serves. Never
aborts — returns empty on failure.

### Step 4 (pass 2) — Re-aggregate with persona gap
Re-runs aggregation including the persona gap questions so they can fuzzy-merge
with existing candidates (dedup is idempotent). Pass-1 gate decisions
(embeddings, relevance, discard reasons) are carried forward by normalized
text; only genuinely new candidates are embedded and gated. The surviving set
becomes the `eligible_pool`.

### Step 5.3–5.5 — Coverage graph + regions
Builds a semantic **coverage graph** over the eligible pool (edges above a
similarity threshold), detects **regions** via Louvain community detection, and
scores each region for relevance/restatement. Off-topic or title-restating
regions are eliminated; if every region is eliminated, abort with
`all_regions_eliminated`. Survivors are `region_kept`.

### Step 7 / 7.5 / 7.6 — Prioritize, template, reserve anchors
- **Step 7 (`compute_priority`):** vector-based heading priority on the kept
  pool.
- **Step 7.6 (`score_top_candidates_llm`):** bell-curve LLM quality scoring on
  the top-K candidates, blended into priority at ~30% (vectors stay 70%). Never
  aborts; set the weight to 0 to disable.
- **Intent template (`get_template`):** deterministic per-intent heading
  skeleton (`h2_pattern`, framing rule, ordering, min/max H2 count, anchor
  slots). Drives `target_h2`, anchor reservation, and framing validation.
- **Step 7.5 (`reserve_anchor_slots`):** embeds the template's anchor strings
  and reserves the best-fit candidate per slot before MMR. No-op for templates
  with empty anchor lists (listicle / news / local-seo).

### Step 8 — MMR H2 selection (`select_h2s_mmr`)
Maximal-marginal-relevance selection over the non-reserved pool (balancing
relevance against inter-heading redundancy), seeded with the reserved anchors,
up to the template-clamped `target_h2`. Zero selected aborts with
`no_h2s_selected`.

### Step 8.5 — Scope verification (`verify_scope`)
LLM-checks each selected H2 against title + scope statement; rejects route to
silos. If *every* H2 is rejected (extreme edge case), fall back to the original
selection rather than abort.

### Step 11 — Framing validator (`validate_and_rewrite_framing`)
Normalizes H2 framing to the template's rule (e.g. verb-leading for how-to).
Warn-and-accept: rewrites that still fail are accepted with a violation flag.
Rewritten H2s are re-embedded (one API call) so downstream cosine bands stay
aligned with the displayed text.

### how-to reorder (`reorder_how_to`)
For how-to intent only, reorder H2s into narrative setup → execution →
validation order. **Runs before Step 8.6** so H3 attachments (keyed by H2
index) land under the right parents.

### Step 8.6 — H3 selection (`select_h3s_for_h2s`)
Per-H2 MMR over the MMR-loser pool, constrained to a parent-relevance cosine
band ([0.65, 0.85] in v2.2) and the **same region** as the parent. Attached H3s
shed the `below_priority_threshold` stamp.

### Step 9 — Authority-gap headings (`authority_gap_headings`)
The Universal Authority Agent proposes "unique angle competitors miss"
headings, grounded in the Reddit + customer-review insight documents (or raw
Reddit snippets as fallback), scoped to the title/scope/intent. Each emitted
heading carries a `level`:
- **Step 9b:** H2-level gaps go through scope verification + framing, then
  **displace** the lowest-priority non-authority H2 if accepting them would
  exceed the template's `max_h2_count` (authority gaps are always retained).
- H3-level gaps continue to Step 8.5b.

### Step 11.5 — Intent rewriter (`rewrite_h2s_for_intent`)
Archetype-driven **structural** rewriting for how-to / listicle / informational
(e.g. Q&A-style H2s → procedural steps or value-leading list items). Distinct
from Step 11 (shape only). Never aborts — framing validation already ran as the
safety net.

### Step 8.5b / 8.7 — H3 scope + parent-fit verification
- **Step 8.5b (`verify_h3_scope`):** drops authority H3s that drift outside
  scope; rejects route to silos. Fail-open.
- **Step 8.7 (`verify_h3_parent_fit`):** a batched LLM call classifying each
  attached H3 `good` / `marginal` / `wrong_parent` / `promote_to_h2`.
  `wrong_parent` re-attaches to a better-fit H2 when capacity exists, else
  routes to silos; `promote_to_h2` routes to silos. Authority H3s are exempt
  from discard.

### Step 10 / 10.5 — FAQ generation + intent gate
- **Pool:** PAA questions, Reddit titles/comments, *unused* persona-gap
  questions, plus an LLM concern-extraction pass over Reddit.
- **Step 10.5 (`apply_faq_intent_gate`):** two-stage filter — a cosine floor
  against an intent-profile vector (intent + title + scope + persona goal) and
  an LLM intent-role classifier dropping `different_audience` FAQs. Relaxes
  (tops up with `adjacent_intent`) when fewer than 3 primary FAQs survive.
- **Score + select (`score_faqs` / `select_faqs`):** blended cosine
  (title + intent-profile), reusing the gate's embeddings to avoid a second
  API call.

### Step 11 — Structure assembly (`assemble_structure`)
Assembles the final `heading_structure` (H1 → H2s with attached H3s → FAQ →
conclusion) from the selected H2s, attachments, FAQs, and title. Returns the
outline plus any `cap_cuts` (global-cap overflow).

### Step 12 — Silos (`identify_silos` → `verify_silo_viability`)
Identifies adjacent-topic **silo candidates** from leftover material: region
non-contributors, scope rejects (H2 and H3), relevance-gate rejects, and
parent-fit rejects. Applies a search-demand floor with a strong-priority
bypass, then an LLM viability check. Low-coherence candidates are recorded as
discarded.

---

## 4. Outputs assembled at the end

- **`discarded_headings`:** a deduped audit trail of every dropped candidate
  with its `discard_reason` — relevance/restatement gate, region elimination,
  MMR losers not promoted to H3, scope rejects, H3 parent-relevance rejects,
  authority displacements, low-coherence silos, and global-cap cuts.
- **`format_directives`:** carries `min_h2_body_words`, derived from the intent
  template's `h2_pattern` (e.g. 120 for how-to, 180 for informational), which
  the **Writer's Step 6.7** validator later enforces.
- **v2.6 blind-spot side-channels** — all observability-only, none gate the
  brief, all degrade to `available=False`:
  - `reddit_insights`, `customer_review_insights` — Perplexity syntheses.
  - `llm_disagreement` (`analyze_fanout_disagreement`) — consensus strength and
    contested topics across the fan-out LLMs.
  - `editorial_critique` (`generate_editorial_critique`) — a critique of the
    selected outline vs. competitor titles.
- **Cache write:** best-effort write of the full payload keyed by
  `(keyword, location_code)` with the schema version and duration.

---

## 5. Failure modes & error codes

The router maps `BriefError` to HTTP 422 and anything else to 500
`internal_error`. The **hard aborts** (everything else degrades gracefully):

| Condition | Code | HTTP |
|---|---|---|
| Empty or over-length keyword | `validation_error` | 422 |
| SERP returns 0 organic results | `serp_no_results` | 422 |
| Aggregation produces 0 candidates | `no_candidates` | 422 |
| Relevance gates eliminate everything | `all_below_threshold` | 422 |
| Every coverage region eliminated | `all_regions_eliminated` | 422 |
| MMR selects 0 H2s | `no_h2s_selected` | 422 |
| Unexpected exception | `internal_error` | 500 |

**Graceful degradation** (never aborts): Reddit / autocomplete / suggestions
fetch failures, any LLM fan-out source, persona generation, LLM heading
scoring, scope verification (falls back to accept-all), authority gap, FAQ
extraction, the parent-fit / FAQ intent gates, and all v2.6 side-channels.

---

## 6. Key metadata for reviewers

`BriefMetadata` is the tuning + audit surface. Useful groupings:

- **Outline shape:** `h2_count`, `h3_count`, `h3_count_average`,
  `h2s_with_zero_h3s`, `faq_count`, `h2_shortfall` (+ reason).
- **Gate/region accounting:** `regions_detected`,
  `regions_eliminated_off_topic`, `regions_eliminated_restate_title`,
  `regions_contributing_h2s`, `scope_verification_*_count`,
  `discarded_headings_count`.
- **Silos:** `silo_candidates_count` and the `silo_candidates_rejected_by_*`
  counters plus `silo_viability_fallback_applied`.
- **v2.1/2.2 stages:** `anchor_slots_total` / `_reserved_count`,
  `framing_rewrites_applied` / `_accepted_with_violation`,
  `h3_parent_fit_*_count`, `faq_intent_gate_*`.
- **Data availability:** `low_serp_coverage`, `reddit_unavailable`,
  `llm_fanout_unavailable`, `llm_fanout_queries_captured`,
  `llm_response_subtopics_extracted`, `competitor_domains`.
- **Tuning thresholds (echoed):** `relevance_floor_threshold`,
  `restatement_ceiling_threshold`, `inter_heading_threshold`,
  `edge_threshold`, `mmr_lambda`, `parent_relevance_floor_threshold`, etc.

---

## 7. Quick reference — files

| File | Responsibility |
|---|---|
| `pipeline.py` | `run_brief()` orchestration — owns the whole process above |
| `router.py` | `POST /brief` endpoint + error mapping |
| `cache.py` | Cache lookup / write keyed by `(keyword, location_code)` |
| `dataforseo.py` | SERP / Reddit / autocomplete / suggestions / LLM fan-out client |
| `parsers.py` | SERP + Reddit parsing, SERP stat aggregation |
| `perplexity_client.py` / `reddit_research.py` / `customer_review_research.py` | Perplexity-synthesized insight documents |
| `intent.py` / `intent_template.py` / `intent_rewrite.py` | Intent classify, per-intent template, archetype rewrite |
| `title_scope.py` | Title + H1 + scope statement generation |
| `aggregation.py` | Step 4 candidate aggregation + dedup |
| `graph.py` | Embedding gates, coverage graph, region detection/scoring |
| `persona.py` | Step 6 searcher persona + gap questions |
| `priority.py` / `llm_scoring.py` | Vector priority + LLM quality scoring |
| `skeleton_slots.py` | Step 7.5 anchor-slot reservation |
| `mmr.py` | Step 8 MMR H2 selection |
| `scope_verification.py` | Step 8.5 / 8.5b H2 + H3 scope checks |
| `framing.py` | Step 11 framing validator |
| `h3_selection.py` / `h3_parent_fit.py` | Step 8.6 H3 selection + 8.7 parent-fit |
| `authority.py` | Step 9 authority-gap agent |
| `faqs.py` / `faq_intent_gate.py` | Step 10 FAQ pool/score/select + 10.5 gate |
| `assembly.py` | Step 11 structure assembly, how-to reorder, authority attach |
| `silos.py` | Step 12 silo identification + viability |
| `llm_disagreement.py` / `editorial_critique.py` | v2.6 blind-spot side-channels |
| `llm.py` | Claude JSON + OpenAI embedding helpers |
| `models/brief.py` | Request/response/metadata Pydantic schemas (`extra='forbid'`) |
