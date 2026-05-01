# PRD: Content Brief Generator Module

**Version:** 1.8
**Status:** Ready for Engineering Spec
**Last Updated:** 2026-05-01
**Part of:** [Parent Content Creation Platform — TBD name]
**Downstream Dependency:** Content Writer Module

> **v1.8 changes (2026-05-01):** Encoded Content Quality PRD v1.0 R1, R2, R3, R5. Filename retains `-v1.7` suffix; canonical version is in this header.

---

## 1. Problem Statement

Producing SEO-optimized content briefs manually is slow, inconsistent, and often shallow. Writers receive briefs that mirror the top SERP results without identifying what's *missing* from the competitive landscape, resulting in content that ranks for nothing because it adds no information gain over existing pages. This module automates the research, classification, gap analysis, and structural planning required to produce a brief that a downstream AI writing module can execute against. Output must be optimized for both Google search ranking and LLM citation surfaces.

---

## 2. Goals

- Accept a single keyword input and return a fully structured content brief as a typed JSON object
- Eliminate manual SERP research, PAA scraping, and competitor heading analysis
- Produce briefs optimized for both Google ranking and LLM citation
- Generate heading structures that are intent-aware, semantically relevant, and authoritative
- Ensure every brief contains measurable information gain over existing top-ranking content via the Authority Gap process
- Capture LLM fan-out queries from ChatGPT, Claude, Gemini, and Perplexity to align content with how AI models actually research topics
- Automatically surface content silo cluster article seeds from discarded heading candidates, enabling systematic topic coverage without additional research cost

### Out of Scope (v1)
- Content writing (handled downstream)
- Title generation (handled by Content Writer Module)
- Keyword research / keyword selection
- Internal linking suggestions
- Publishing or CMS integration
- User-facing UI (this is a pipeline module)
- Multi-locale support — English / United States only
- Rank tracking and citation monitoring
- Multi-tenant brand configuration
- Downstream consumption of silo candidates — whether they automatically trigger new brief generation, enter a queue, or are surfaced to a human for approval is outside this module's scope

---

## 3. Success Metrics

Success in v1 is defined by structural validity and operational discipline, not downstream ranking performance. All metrics are measurable from the module's own output and logs.

| Metric | Target |
|---|---|
| Output validates against JSON schema | 100% |
| Brief contains 3–5 FAQs | 100% |
| Brief contains 3–5 authority gap H3s | 100% |
| Heading count respects intent rules | 100% |
| End-to-end generation completes within 120s | ≥95% |
| Cost per brief stays under $0.50 | ≥95% |

Ranking and LLM citation performance tracking is out of scope for v1 and will be revisited once publish-to-tracking infrastructure exists.

---

## 4. System Architecture Overview

```
[Keyword Input]
      │
      ▼
┌─────────────────────┐
│  Input Validation   │  ◄── Reject empty/whitespace, >150 chars
└─────────────────────┘
      │
      ▼
┌──────────────────────────────────────────────────────────┐
│  Step 1 + 2 (Parallel)                                   │
│  ┌────────────┐  ┌────────────────────────────────────┐  │
│  │ SERP Scrape│  │ PAA + Reddit + Autocomplete        │  │
│  │ DataForSEO │  │ + Keyword Suggestions              │  │
│  │            │  │ + LLM Fan-Out Queries              │  │
│  │            │  │   (ChatGPT, Claude, Gemini,        │  │
│  │            │  │    Perplexity — parallel)          │  │
│  └────────────┘  └────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 3: Intent     │  ◄── Rules-based on SERP features
│  Classification     │  ◄── LLM check on borderline ecom/commercial
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 4: Subtopic   │  ◄── Aggregate + dedup all candidate sources
│  Aggregation        │  ◄── Track LLM fan-out consensus across models
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 5: Semantic   │  ◄── OpenAI text-embedding-3-small
│  Scoring + Polish   │  ◄── Cosine similarity + heading priority formula
│                     │  ◄── LLM polish for awkward headings
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 6: Authority  │  ◄── Universal Authority Agent (3-pillar)
│  Gap Analysis       │  ◄── Reddit threads as context
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 7: FAQ        │  ◄── PAA + Reddit regex pass + LLM concern pass
│  Generation         │  ◄── Weighted scoring formula
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 8: Structure  │  ◄── Intent-aware assembly
│  Assembly           │  ◄── How-to sequential reordering
│                     │  ◄── Global subheading cap enforcement
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 9: Silo       │  ◄── Filter discarded headings by reason
│  Cluster            │  ◄── Semantic clustering of candidates
│  Identification     │  ◄── Surface cluster article seeds
└─────────────────────┘
      │
      ▼
[JSON Output → Content Writer Module]
```

---

## 5. Functional Requirements

### Step 0 — Input Validation

| Rule | Action |
|---|---|
| Input is empty or whitespace-only | Reject with structured error |
| Input length >150 characters | Reject with structured error |
| All other inputs | Pass through as-typed |

**Optional input (v1.8+):** `client_context` — same shape as the Writer Module's Input D (`brand_guide_text`, `icp_text`, `website_analysis`, `website_analysis_unavailable`). When provided, it is consumed only by the Step 8 audience-alignment downgrade (per Content Quality PRD v1.0 R5). When omitted, all R5-related logic is skipped and `metadata.client_context_provided` is `false`. The brief never injects brand voice into prompts itself — that remains the Writer Module's responsibility; the brief uses ICP only as a similarity reference for downgrading off-audience headings.

### Step 1 — SERP Scraping

**Provider:** DataForSEO SERP API (Standard Queue)
**Locale:** English / United States only

**Outputs:**
- Headings (H1–H3) from top 20 organic results
- SERP feature presence flags: shopping box, news box, local pack, featured snippet, PAA, product carousels, comparison tables

**Rules:**
- Exclude headings shorter than 3 words
- Exclude headings from paginated results (page 2+)
- Tag each heading with source URL and SERP position
- Strip boilerplate patterns ("Contact Us", "About the Author", "Related Posts")
- Apply the **SERP heading sanitization rules** from Step 4 (see below) at intake time so subreddit suffixes, ellipsis, site-name prefixes/suffixes, and similar artifacts are stripped before the heading enters any candidate pool. Per Content Quality PRD v1.0 R2.

### Step 2 — PAA, Reddit, Autocomplete, and LLM Fan-Out (Parallel with Step 1)

**Source 2A — PAA:**
- DataForSEO PAA endpoint
- Capture all available PAA questions
- Tag `source: "paa"`

**Source 2B — Reddit:**
- Query: `{keyword} site:reddit.com` via DataForSEO
- Pull top 5 threads by relevance
- Extract: post titles, top-level comments with upvotes ≥10
- Output feeds two pipeline destinations:
  1. FAQ pool (Step 7)
  2. Authority Gap context (Step 6)

**Source 2C — Autocomplete + Keyword Suggestions:**
- DataForSEO Google Autocomplete endpoint
- DataForSEO Keyword Suggestions endpoint
- Capture all returned queries
- Tag `source: "autocomplete"` or `source: "keyword_suggestion"`
- Enter heading candidate pipeline as raw text; will be rewritten during Step 5 polish pass

**Source 2D — LLM Fan-Out Queries + Response Extraction (Multi-LLM):**

**Provider:** DataForSEO LLM Responses API (Live mode), four LLMs in parallel:
- ChatGPT (`gpt-4o`)
- Claude (latest available model supporting web search)
- Gemini (latest available model supporting web search)
- Perplexity (`sonar` — web search enabled by default)

**Prompt (sent to all four):** `"What are the most important subtopics and questions someone should understand about [keyword]?"`

**Configuration (per LLM):**
- `web_search: true` where supported
- `force_web_search: true` (ChatGPT and Claude only — not supported by Gemini or Perplexity)
- `web_search_country_iso_code: "US"` (where supported)
- `max_output_tokens: 500`

**Capture per LLM:**

**Output A — Fan-out queries:**
- Extract `fan_out_queries` array from each response
- Tag with source matching the LLM:
  - ChatGPT → `source: "llm_fanout_chatgpt"`
  - Claude → `source: "llm_fanout_claude"`
  - Gemini → `source: "llm_fanout_gemini"`
  - Perplexity → `source: "llm_fanout_perplexity"`

**Output B — Response content extraction:**
- Pass each LLM's full response text through a lightweight LLM extraction call
- Extraction prompt: "Extract all distinct subtopics, heading-like statements, and key concepts from this text. Return as a JSON array of strings."
- Tag with source matching the LLM:
  - ChatGPT → `source: "llm_response_chatgpt"`
  - Claude → `source: "llm_response_claude"`
  - Gemini → `source: "llm_response_gemini"`
  - Perplexity → `source: "llm_response_perplexity"`

**Cross-LLM dedup:**
The fuzzy dedup in Step 4 collapses near-duplicate fan-out queries across LLMs. When duplicates are merged, retain the entry with the highest count of LLMs that surfaced it, and store the count as `llm_fanout_consensus` (0–4) on the heading object. A query that appears across all 4 LLMs is a strong signal — much stronger than one appearing in only one.

### Step 3 — Intent Classification

**Method:** Rules-based classifier on SERP feature signals, with LLM check for borderline ecom/commercial cases.

**Rule mapping:**

| SERP Signal | Assigned Intent |
|---|---|
| Shopping box + product carousels | ecom (with borderline check) |
| News box dominant | news |
| Local pack present | local-seo |
| "vs" or "versus" in 3+ of top 5 titles, comparison tables | comparison |
| "How to" in 3+ of top 5 titles | how-to |
| Numbered list titles dominating (3+) | listicle |
| Featured snippet, no shopping/news/local signals | informational |

**Borderline ecom check (LLM):**

Trigger an LLM intent check when initial classification is `ecom` AND any of:
- Top 5 titles contain "best", "top", "review", "guide"
- Featured snippet is present
- Top 3 results are not e-commerce domains

LLM returns one of: `ecom`, `comparison`, or `informational-commercial`.

**Conflict priority:** `news > ecom > local-seo > comparison > how-to > listicle > informational`

**Output:** `intent_type`, `intent_confidence`, `intent_review_required` (true if confidence <0.75)

### Step 4 — Subtopic Aggregation

**Step 4.0 — SERP heading sanitization (deterministic, runs before all other Step 4 logic).** Per Content Quality PRD v1.0 R2, the following sanitization rules apply to every heading candidate at intake, regardless of source:

| # | Pattern | Action |
|---|---|---|
| S1 | Trailing `: r/<subreddit>` | Strip suffix |
| S2 | Trailing `…` or three or more consecutive periods | Strip suffix |
| S3 | Trailing `\| <site name>`, `– <site name>`, `— <site name>` where the trailing segment matches a domain root in the SERP item's URL or is < 30 chars and contains at most one CapitalizedWord run | Strip suffix |
| S4 | Leading `<site name>: ` (same matching rule as S3) | Strip prefix |
| S5 | Trailing `\| Read More`, `\| Continue Reading`, `Read More …`, `Continue Reading …` | Strip suffix |
| S6 | Wrapping HTML tags or entities (`<strong>`, `&amp;`, `&#8217;`) | Decode entities; strip tags |
| S7 | Multiple internal whitespace runs | Collapse to single spaces |
| S8 | Trailing punctuation runs other than a single terminal `?` or `.` | Reduce to single terminal mark |
| S9 | Headings shorter than 3 words after sanitization | Discard with `discard_reason: "too_short_after_sanitization"` |
| S10 | Headings whose sanitized form is a single proper-noun brand name with no verb or noun phrase | Discard with `discard_reason: "non_descriptive_after_sanitization"` |

The pre-sanitization raw text is preserved on the candidate as `raw_text` so `discarded_headings[].original_source` can show what was scraped. The polish-pass LLM (Step 5) receives sanitized text only.

**Step 4.1 — Aggregation.**
- Combine all scraped H1–H3 headings from Step 1 plus autocomplete queries, keyword suggestions, fan-out queries from all 4 LLMs, and response extractions from all 4 LLMs from Step 2
- Normalize: lowercase + strip punctuation for comparison; preserve original casing for output
- Deduplicate using fuzzy matching (Levenshtein distance threshold ≤0.15) across all sources
- Tag each unique entry with `serp_frequency` and `avg_serp_position`
- Non-SERP sources (autocomplete, keyword suggestion, LLM fan-out, LLM response) get `serp_frequency: 0` and `avg_serp_position: null`
- Track `llm_fanout_consensus` (integer 0–4) on each heading: count of LLMs whose fan-out queries or response extractions surfaced this topic. Pure SERP/autocomplete/keyword_suggestion entries get `llm_fanout_consensus: 0`

### Step 5 — Semantic Scoring + Heading Polish

**Embedding model:** OpenAI `text-embedding-3-small`

**Process:**
1. Embed the seed keyword
2. Embed each unique heading from Step 4
3. Compute cosine similarity → `semantic_score` (0.0–1.0)
4. Filter: retain headings with `semantic_score ≥ 0.55`. Headings below this threshold are moved to `discarded_headings` with `discard_reason: "below_semantic_threshold"`
5. **Heading polish pass (LLM):** Awkward, keyword-stuffed, or raw query-format candidates (autocomplete, fan-out, etc.) are rewritten for clarity. Rewritten headings get `source: "synthesized"` with `original_source` preserved.

**Combined priority formula for H2 selection:**
```
heading_priority = (0.4 × semantic_score) + (0.25 × normalized_serp_frequency) + (0.15 × position_weight) + (0.2 × normalized_llm_consensus)

Where:
- normalized_serp_frequency = min(serp_frequency / 20, 1.0)
- position_weight = 1.0 - ((avg_serp_position - 1) / 20)
- normalized_llm_consensus = llm_fanout_consensus / 4 (range 0.0–1.0)
```

**Rationale:** A topic that 3 of 4 LLMs surface independently is a strong signal that LLMs view it as core to the topic — exactly what's needed for citation optimization.

**Step 5.5 — Semantic deduplication (added per Content Quality PRD v1.0 R1).** After scoring and polishing, but before priority-based selection in Step 8, run a pairwise cosine-similarity pass across all surviving H2 candidates using the embeddings already computed in Step 5.

- For every pair `(a, b)` where `cosine(a.embedding, b.embedding) ≥ 0.85`, retain the candidate with the higher `heading_priority` and discard the other with:
  - `discard_reason: "semantic_duplicate_of_higher_priority_h2"`
  - `semantic_duplicate_of: <order of the kept H2>` (back-reference field added to discarded headings)
- Definitional-restatement guard: when ≥ 6 candidates have a pairwise cosine to the seed keyword ≥ 0.90 (signal of a definitional keyword like "what is X"), retain at most **one** candidate that matches the regex `^(what (is|are|does)|define|explain|introducing|demystif|explained?|overview of)\b` (case-insensitive). Additional matches are discarded with `discard_reason: "definitional_restatement"`.
- Increment `metadata.semantic_dedup_collapses_count` for every pair collapsed by the 0.85 rule and `metadata.definitional_restatements_discarded_count` for each candidate dropped by the definitional guard.
- This pass runs **before** Step 6 (Authority Gap) so authority-gap H3s never get attached to an H2 that is about to be dropped as a semantic duplicate.

### Step 6 — Authority Gap Analysis

**Agent:** Universal Authority Agent

**Three Pillars:**
1. **Human/Behavioral** — Psychological drivers, common errors, emotional decision points
2. **Risk/Regulatory** — Legal, safety, compliance, financial liabilities
3. **Long-Term Systems** — Evolution over time, sustainability, ecosystem outcomes

**Inputs:**
- Aggregated heading list from Step 4
- Reddit thread summaries from Step 2 (as context, not as headings)

**Output rules:**
- Exactly 3–5 new H3 subheadings
- Inserted immediately after the most relevant H2
- Tagged `source: "authority_gap_sme"`
- **Authority gap H3s count toward the per-H2 limit of 2 H3s.** If an H2 already has 2 H3s, the lowest-priority existing H3 is displaced to make room.
- Must not duplicate existing headings (fuzzy check)
- Score is computed but `exempt: true` flag set — bypasses 0.55 threshold
- Authority gap H3s are never discarded

### Step 7 — FAQ Generation

**Source A — Regex extraction (deterministic):**
- Extract sentences ending in `?` from Reddit post titles and top-comment text
- Filter: 5–25 words
- Add to candidate pool with PAA questions

**Source B — LLM concern extraction:**
- Single LLM call with all Reddit thread content
- Prompt: extract up to 10 implicit questions or concerns
- Returns JSON array of question strings

**Scoring formula:**
```
faq_score = (0.4 × source_signal) + (0.4 × semantic_relevance) + (0.2 × novelty_bonus)

Where:
- source_signal:
    - PAA = 1.0
    - Reddit ≥50 upvotes = 0.9
    - Reddit 10–49 upvotes = 0.6
    - Reddit <10 upvotes = 0.3
    - LLM-extracted concern = 0.5
- semantic_relevance: cosine similarity to seed keyword
- novelty_bonus: 1.0 if topic not in heading_structure, else 0.0
```

**Selection rules:**
- Take top 5 by score with minimum threshold 0.5
- If <3 pass threshold, accept top 3 regardless
- Always output 3–5 FAQs

### Step 8 — Structure Assembly

**Universal structural constants:**

| Element | Rule |
|---|---|
| Title | Generated downstream by Writer Module — not in this output |
| H1 | 1 per brief. Exact-match seed keyword only. Writer Module enriches with entities. |
| Conclusion | 1 structural block. Type-flagged, no heading level. |
| FAQ Section | H2 labeled "Frequently Asked Questions". Does NOT count toward H2 budget or global subheading cap. |
| FAQ Questions | H3 tags. 3–5 per brief. |

**Heading rules:**

| Rule | Value |
|---|---|
| Max content H2s (capped intents) | 6 |
| Max content H2s (listicle, how-to) | Uncapped |
| Max H3s per H2 | 2 |
| H3s required per H2 | No — only included if candidates score above threshold |
| Authority gap H3s count toward per-H2 limit | Yes |
| Global content subheading cap (capped intents) | 15 |
| Global content subheading cap (listicle, how-to) | 20 |
| FAQ H2 + FAQ H3s | Outside both caps |
| Topical-diversity-aware selection (MMR) | **Required** — see below |

Headings that do not make the final selection due to priority ranking are moved to `discarded_headings` with `discard_reason: "below_priority_threshold"`. Headings that would have been included but are cut by the global cap are moved with `discard_reason: "global_cap_exceeded"`.

**MMR-ranked H2 selection (added per Content Quality PRD v1.0 R1).**

Selection is no longer pure priority sort. To prevent topical redundancy in the final outline, H2s are picked greedily by **Maximum Marginal Relevance**:

1. Sort the H2 candidate pool by `heading_priority` desc.
2. Pick the highest-priority candidate as the first selected H2.
3. For each subsequent slot up to the cap, score every remaining candidate as:
   ```
   mmr_score(c) = λ * heading_priority(c) − (1 − λ) * max_cosine(c.embedding, selected_h2_embeddings)
   λ = 0.6
   ```
   Pick the candidate with the highest `mmr_score`.
4. Stop when the H2 cap (6 for capped intents) is reached or no candidate has `mmr_score > 0`.

`λ` is configurable via `format_directives.mmr_lambda` if a downstream module needs to tune the diversity/priority balance per intent.

**Topic-adherence ICP downgrade (added per Content Quality PRD v1.0 R5).**

When the brief's optional `client_context.icp_text` is provided (see Section 4 — Inputs):
- Embed the audience summary (single sentence extracted from the ICP guide; if not extractable, embed the full ICP text truncated to 500 tokens).
- For each H2 candidate, compute `audience_alignment = cosine(c.embedding, audience_embedding)`.
- Candidates whose `audience_alignment ≤ 0.45` **and** whose `heading_priority` rank is in the bottom 25% of the H2 pool are downgraded by 0.10 in `heading_priority` before MMR selection runs. The downgrade is logged on the candidate as `audience_alignment_downgrade_applied: true`.

**Intent-specific structure:**

| Intent | H2 Cap | Notes |
|---|---|---|
| Informational | 6 | — |
| Comparison | 6 | — |
| Local SEO | 6 | — |
| Ecom | 6 | — |
| Informational-Commercial | 6 | From borderline ecom check |
| News | 6 | — |
| Listicle | Uncapped | Each list item is an H2 |
| How-to | Uncapped | Each step is an H2, sequentially ordered |

**How-to sequential reordering:**
- Embed each step heading
- Cluster by semantic proximity
- Apply dependency heuristics: setup → execution → validation
- Output steps in logical order

**Word budget:**
- Maximum **2,500 words** across content sections
- FAQ section excluded from word count
- Enforcement is the Content Writer Module's responsibility

**Section length math (for sanity checking):**

| Scenario | Headings | Words/Section |
|---|---|---|
| Max (15) | 6 H2 + 9 H3 | ~167 words |
| Typical (10) | 5 H2 + 5 H3 | ~250 words |
| Light (7) | 4 H2 + 3 H3 | ~357 words |

### Step 9 — Spin-Off Article Routing (formerly Silo Cluster Identification)

**Purpose:** Convert discarded headings — including those dropped by R1 semantic dedup, R3 topic-adherence checks, and the historical priority/cap discards — into a structured `spin_off_articles[]` map of supporting cluster articles. Off-topic headings are never padded into the parent piece (per Content Quality PRD v1.0 R3); they always route here for use as future article seeds.

This step adds zero additional API cost since all embeddings were computed in Step 5.

**Input:** All headings in `discarded_headings` with `discard_reason` of:
- `below_priority_threshold`
- `global_cap_exceeded`
- `semantic_duplicate_of_higher_priority_h2` (added per R1)
- `definitional_restatement` (added per R1)
- `low_topic_adherence_in_writer` (added per R3 — backfilled when the Writer drops a section for low topic adherence)

Headings with `discard_reason` of `below_semantic_threshold`, `duplicate`, `too_short_after_sanitization`, or `non_descriptive_after_sanitization` are excluded from spin-off candidates.

**Process:**
1. Take all eligible discarded headings — their embeddings already exist from Step 5, no re-embedding needed
2. Group by semantic proximity to each other using cosine similarity clustering (not proximity to the pillar keyword)
3. For each cluster, derive a suggested seed keyword by identifying the centroid heading — the one with the highest average similarity to all other headings in the cluster
4. Compute `cluster_coherence_score` — the average cosine similarity between all headings in the cluster. High score = tightly focused article topic. Low score = loose grouping that may need human review.
5. Assign `recommended_intent` to each cluster using the same rules-based signal mapping from Step 3, applied to the cluster's heading patterns

**Cluster quality rules:**

| Rule | Value |
|---|---|
| Minimum headings per cluster | 2 |
| Minimum cluster coherence score | 0.60 |
| Maximum silo candidates per brief | 10 |
| Review recommended threshold | Coherence between 0.60 and 0.70 |

- Clusters below 0.60 coherence are added to `discarded_headings` with `discard_reason: "low_cluster_coherence"`
- If more than 10 clusters qualify, take the 10 with the highest coherence scores
- If `cluster_coherence_score` is between 0.60 and 0.70, flag `review_recommended: true` — the cluster is valid but loose enough that the suggested keyword may benefit from human refinement before being used as a brief seed

---

## 6. Output Schema

```json
{
  "keyword": "string",
  "intent_type": "informational | listicle | how-to | comparison | ecom | local-seo | news | informational-commercial",
  "intent_confidence": 0.0,
  "intent_review_required": false,
  "heading_structure": [
    {
      "level": "H1 | H2 | H3",
      "text": "string",
      "type": "content | faq-header | faq-question | conclusion",
      "source": "serp | paa | reddit | authority_gap_sme | synthesized | autocomplete | keyword_suggestion | llm_fanout_chatgpt | llm_fanout_claude | llm_fanout_gemini | llm_fanout_perplexity | llm_response_chatgpt | llm_response_claude | llm_response_gemini | llm_response_perplexity",
      "original_source": "string | null",
      "semantic_score": 0.0,
      "exempt": false,
      "serp_frequency": 0,
      "avg_serp_position": 0.0,
      "llm_fanout_consensus": 0,
      "heading_priority": 0.0,
      "order": 0
    }
  ],
  "faqs": [
    {
      "question": "string",
      "source": "paa | reddit | llm_extracted",
      "faq_score": 0.0
    }
  ],
  "structural_constants": {
    "conclusion": {
      "type": "conclusion",
      "level": null,
      "text": "[Conclusion placeholder]"
    }
  },
  "format_directives": {
    "require_bulleted_lists": true,
    "require_tables": true,
    "min_lists_per_article": 2,
    "min_tables_per_article": 1,
    "preferred_paragraph_max_words": 80,
    "answer_first_paragraphs": true
  },
  "discarded_headings": [
    {
      "text": "string",
      "source": "serp | autocomplete | keyword_suggestion | llm_fanout_chatgpt | llm_fanout_claude | llm_fanout_gemini | llm_fanout_perplexity | llm_response_chatgpt | llm_response_claude | llm_response_gemini | llm_response_perplexity",
      "original_source": "string | null",
      "semantic_score": 0.0,
      "serp_frequency": 0,
      "avg_serp_position": 0.0,
      "llm_fanout_consensus": 0,
      "heading_priority": 0.0,
      "discard_reason": "below_semantic_threshold | below_priority_threshold | global_cap_exceeded | duplicate | low_cluster_coherence | semantic_duplicate_of_higher_priority_h2 | definitional_restatement | too_short_after_sanitization | non_descriptive_after_sanitization | low_topic_adherence_in_writer",
      "semantic_duplicate_of": null,
      "raw_text": "string — pre-sanitization text as scraped (R2)"
    }
  ],
  "silo_candidates": [
    {
      "suggested_keyword": "string",
      "cluster_coherence_score": 0.0,
      "review_recommended": false,
      "recommended_intent": "informational | listicle | how-to | comparison | ecom | local-seo | news | informational-commercial",
      "source_headings": [
        {
          "text": "string",
          "semantic_score": 0.0,
          "heading_priority": 0.0,
          "discard_reason": "global_cap_exceeded | below_priority_threshold"
        }
      ]
    }
  ],
  "spin_off_articles": [
    {
      "suggested_keyword": "string",
      "source_heading_text": "string",
      "source_reason": "low_topic_adherence | semantic_duplicate | global_cap_exceeded | below_priority_threshold | definitional_restatement",
      "topic_adherence_score": 0.0,
      "cluster_coherence_score": 0.0,
      "review_recommended": false,
      "recommended_intent": "informational | listicle | how-to | comparison | ecom | local-seo | news | informational-commercial",
      "supporting_headings": ["string"]
    }
  ],
  "metadata": {
    "word_budget": 2500,
    "faq_count": 0,
    "h2_count": 0,
    "h3_count": 0,
    "total_content_subheadings": 0,
    "discarded_headings_count": 0,
    "silo_candidates_count": 0,
    "competitors_analyzed": 20,
    "reddit_threads_analyzed": 0,
    "llm_fanout_queries_captured": {
      "chatgpt": 0,
      "claude": 0,
      "gemini": 0,
      "perplexity": 0
    },
    "llm_response_subtopics_extracted": {
      "chatgpt": 0,
      "claude": 0,
      "gemini": 0,
      "perplexity": 0
    },
    "intent_signals": {
      "shopping_box": false,
      "news_box": false,
      "local_pack": false,
      "featured_snippet": false,
      "comparison_tables": false
    },
    "embedding_model": "text-embedding-3-small",
    "semantic_filter_threshold": 0.55,
    "semantic_dedup_threshold": 0.85,
    "semantic_dedup_collapses_count": 0,
    "definitional_restatements_discarded_count": 0,
    "mmr_lambda": 0.6,
    "client_context_provided": false,
    "audience_alignment_downgrades_applied": 0,
    "low_serp_coverage": false,
    "reddit_unavailable": false,
    "llm_fanout_unavailable": {
      "chatgpt": false,
      "claude": false,
      "gemini": false,
      "perplexity": false
    },
    "schema_version": "1.8"
  }
}
```

---

## 7. Failure Mode Handling

| Scenario | Behavior |
|---|---|
| DataForSEO returns <10 results | Continue with available; flag `low_serp_coverage: true` |
| DataForSEO returns 0 results | Abort with structured error; do not pass to writer |
| Reddit returns 0 threads | Continue without Reddit; flag `reddit_unavailable: true` |
| Any individual LLM fan-out call fails or returns empty | Continue with remaining LLMs; flag the specific LLM in `llm_fanout_unavailable` |
| All 4 LLM fan-out calls fail | Continue without LLM fan-out data entirely; flag all 4 |
| All headings score <0.55 | Lower threshold to 0.40 and retry; if still <3 pass, abort |
| Authority Agent returns malformed JSON | Retry once with stricter prompt; on second failure, return brief without authority gap headings + flag |
| OpenAI embeddings timeout | Retry 3x with exponential backoff; on final failure, abort |
| Authority Agent returns wrong heading count | Truncate to 5 if >5; retry if <3; on retry failure, accept what was returned |
| Intent confidence <0.50 even after LLM check | Default to `informational`; flag `intent_review_required: true` |
| No silo clusters meet minimum coherence threshold | Return empty `silo_candidates` array; do not abort |
| End-to-end exceeds 120s | Abort and notify user |

---

## 8. Performance Targets

**Trigger model:** Synchronous, user-initiated, runs in parallel with the keyword/entity/quadgram research module.

| Stage | Target | Max |
|---|---|---|
| End-to-end brief generation | 60s | 120s |
| SERP + Reddit + Autocomplete + 4-LLM Fan-Out scrape (parallel) | 30s | 60s |
| Embedding + scoring | 5s | 10s |
| Authority agent | 15s | 30s |
| Structure assembly | 5s | 10s |
| Silo cluster identification | 2s | 5s |

The 4 LLM fan-out calls run concurrently with each other and with SERP/Reddit/Autocomplete. The slowest single call determines stage time. Silo cluster identification adds negligible latency since it reuses existing embeddings.

---

## 9. Cost Model

| Component | Cost per Brief |
|---|---|
| DataForSEO SERP (depth 20, standard queue) | ~$0.001 |
| DataForSEO PAA | ~$0.001 |
| DataForSEO Reddit search | ~$0.001 |
| DataForSEO Autocomplete | ~$0.001 |
| DataForSEO Keyword Suggestions | ~$0.001 |
| DataForSEO LLM Responses (4 LLMs parallel) | ~$0.08–$0.20 |
| LLM extraction of response content (4 calls) | ~$0.04 |
| OpenAI embeddings | <$0.001 |
| LLM calls (intent borderline, heading polish, authority agent, FAQ extraction, how-to reordering) | $0.10–$0.30 |
| Silo cluster identification | $0.00 (reuses Step 5 embeddings) |
| **Estimated total per brief** | **$0.19–$0.53** |
| **Budget ceiling** | **$0.75** |

**Monthly operational cost at 10–20 briefs/day:** ~$60–$320/month

---

## 10. Volume and Scale Assumptions

- **Current volume:** 10–20 briefs/day
- **Trigger source (v1):** User-initiated via parent platform UI
- **Trigger source (v2):** Cron job from Supabase database
- **Concurrency:** No requirement for v1 — sequential per-user execution acceptable

---

## 11. Business Rules Summary

| Rule | Value |
|---|---|
| Locale | English / United States |
| Min input length | Non-empty, non-whitespace |
| Max input length | 150 characters |
| SERP results analyzed | 20 |
| Reddit threads analyzed | 5 |
| LLM fan-out providers | ChatGPT, Claude, Gemini, Perplexity |
| Intent types | 8 (informational, listicle, how-to, comparison, ecom, local-seo, news, informational-commercial) |
| Intent confidence threshold for review flag | 0.75 |
| Semantic score filter threshold | 0.55 |
| Authority gap headings bypass filter | Yes (still scored) |
| Authority gap headings per brief | 3–5 |
| Authority gap H3s count toward per-H2 limit | Yes |
| Authority gap H3s ever discarded | Never |
| Max content H2s (capped intents) | 6 |
| Max content H2s (listicle, how-to) | Uncapped |
| Max H3s per H2 | 2 |
| H3s required per H2 | No |
| FAQ counts toward H2 budget | No |
| FAQ counts toward global subheading cap | No |
| Conclusion is an H2 | No |
| Min FAQs | 3 |
| Max FAQs | 5 |
| Global content subheading cap (capped intents) | 15 |
| Global content subheading cap (listicle, how-to) | 20 |
| Max article word count | 2,500 (FAQ excluded) |
| Silo candidate discard reasons included | `below_priority_threshold`, `global_cap_exceeded` |
| Silo candidate discard reasons excluded | `below_semantic_threshold`, `duplicate`, `low_cluster_coherence` |
| Spin-off article discard reasons included (R3) | `below_priority_threshold`, `global_cap_exceeded`, `semantic_duplicate_of_higher_priority_h2`, `definitional_restatement`, `low_topic_adherence_in_writer` |
| Spin-off article discard reasons excluded | `below_semantic_threshold`, `duplicate`, `too_short_after_sanitization`, `non_descriptive_after_sanitization`, `low_cluster_coherence` |
| H2 semantic-dedup cosine threshold (R1) | 0.85 |
| Definitional-restatement guard trigger (R1) | ≥ 6 candidates with cosine ≥ 0.90 to seed keyword |
| Definitional-restatement keep limit (R1) | 1 |
| MMR lambda (R1) | 0.6 default; configurable via `format_directives.mmr_lambda` |
| Audience-alignment downgrade trigger (R5) | `audience_alignment ≤ 0.45` AND `heading_priority` rank in bottom 25% |
| Audience-alignment downgrade amount (R5) | −0.10 to `heading_priority` |
| Min headings per silo cluster | 2 |
| Min cluster coherence score | 0.60 |
| Max silo candidates per brief | 10 |
| Review recommended threshold | Coherence between 0.60 and 0.70 |
| Additional embedding cost for Step 9 | $0.00 — reuses Step 5 embeddings |

---

## 12. What This PRD Does Not Cover

To be addressed in the engineering implementation spec:
- Authentication / API key management for DataForSEO and OpenAI
- Rate limiting and retry logic
- Caching strategy for repeated keywords
- Cost tracking and monitoring per brief
- Logging and observability requirements
- Schema versioning compatibility with Writer Module
- Specific LLM model selection for each agent call (intent fallback, heading polish, authority agent, FAQ extraction, response extraction, how-to reordering)
- Specific model versions for each fan-out LLM (ChatGPT, Claude, Gemini, Perplexity) — should be configurable
- Downstream consumption of silo candidates — whether they automatically trigger new brief generation, enter a queue, or are surfaced to a human for approval

---

## 13. Version History

| Version | Date | Notes |
|---|---|---|
| 1.0 | Initial draft | Original PRD |
| 1.1 | 2026-04-29 | Added success metrics, failure modes, FAQ scoring formula, heading priority formula, borderline ecom LLM check, format directives, performance targets, cost model, input validation, informational-commercial intent type |
| 1.2 | 2026-04-29 | Added autocomplete and keyword suggestions as heading candidate sources |
| 1.3 | 2026-04-29 | Added LLM fan-out queries via DataForSEO LLM Responses API (ChatGPT); added response content extraction as additional heading candidate source |
| 1.4 | 2026-04-29 | Raised word budget to 2,500; added global content subheading cap; authority gap H3s now count toward per-H2 limit; H3s optional per H2 |
| 1.5 | 2026-04-29 | Reduced max H3s per H2 from 3 to 2 |
| 1.6 | 2026-04-29 | Expanded LLM fan-out capture from ChatGPT-only to all 4 major LLMs (ChatGPT, Claude, Gemini, Perplexity); added cross-LLM consensus tracking (`llm_fanout_consensus`); rebalanced heading priority formula to weight LLM consensus at 0.2 |
| 1.7 | 2026-04-29 | Added Step 9 Silo Cluster Identification; added `discarded_headings` and `silo_candidates` to output schema; added cluster quality rules, review flag, and failure mode for empty silo results |
| 1.8 | 2026-05-01 | Encoded Content Quality PRD v1.0 R1, R2, R3, and R5: SERP heading sanitization at intake (Step 4.0), semantic-similarity dedup with 0.85 cosine threshold and definitional-restatement guard (Step 5.5), MMR-ranked H2 selection in Step 8 with `λ=0.6`, optional `client_context` input feeding Step 8 audience-alignment downgrade, renamed Step 9 to Spin-Off Article Routing with new `spin_off_articles[]` output (legacy `silo_candidates[]` retained for one release), expanded `discarded_headings` enum, schema metadata adds `semantic_dedup_threshold`, `semantic_dedup_collapses_count`, `definitional_restatements_discarded_count`, `mmr_lambda`, `client_context_provided`, `audience_alignment_downgrades_applied`. Bumped `schema_version` to `1.8`. |
