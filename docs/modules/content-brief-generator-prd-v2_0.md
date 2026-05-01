# PRD: Content Brief Generator Module

**Version:** 2.0
**Status:** Ready for Engineering Spec
**Last Updated:** May 1, 2026
**Part of:** [Parent Content Creation Platform — TBD name]
**Downstream Dependency:** Content Writer Module (v1.5+)
**Supersedes:** v1.7

---

## 1. Problem Statement

v1.7 of the Content Brief Generator produced briefs that were structurally valid but topically broken. Outputs frequently contained 5+ H2s that all paraphrased the seed keyword (e.g., for "what is tiktok shop": "What is TikTok Shop", "What exactly is TikTok Shop", "What is a TikTok Shop seller", "What is a TikTok Shop creator", "What is a TikTok Shop account") — distinct headings on paper but functionally restating the same question. Other briefs included topically-related but scope-drifted sections (e.g., a "what is" piece including algorithm-optimization content that belongs in a different article). Both failure modes produced unusable downstream content.

Root causes in v1.7:
- **Lexical-only deduplication** (Levenshtein ≤ 0.15) failed to catch paraphrase H2s that differ at the character level but cluster tightly in semantic space.
- **No anti-restatement constraint.** Headings scoring 0.85+ semantic similarity to the seed passed the relevance filter (≥ 0.55) and were eligible for selection.
- **No intent diversity enforcement.** Six definition-flavored H2s could pass every constraint and end up in the same outline.
- **No scope discipline.** The brief generator had no concept of what the article's title commits to, so topically-related-but-out-of-scope sections were selected freely.
- **No information gain modeling.** Heading priority weighted SERP frequency and position heavily, which structurally encourages outlines that mirror what's already ranking.

v2.0 rewrites the pipeline around four new architectural primitives: explicit title and scope-statement generation, a coverage graph with community detection, hard mathematical constraints on semantic distance from the title, and Maximum Marginal Relevance (MMR) selection that maximizes topical value while enforcing diversity. Data acquisition (Steps 1–2) is preserved from v1.7; scoring, selection, and assembly are rewritten.

---

## 2. Goals

- Accept a single keyword input and return a fully structured content brief as a typed JSON object
- **Generate the article's title and scope statement from SERP signal** rather than letting the writer module infer them
- **Eliminate near-duplicate headings deterministically** via embedding-distance constraints, not LLM judgment
- **Eliminate topical-clone outlines** via graph-based region uniqueness in selection
- **Enforce scope discipline** via LLM verification against the explicit scope statement
- **Model information gain** as an explicit term in the priority formula
- Produce briefs optimized for both Google ranking and LLM citation
- Preserve v1.7's silo cluster identification, surfacing future-article seeds at no extra embedding cost

### Out of Scope (v2.0)
- Content writing (handled downstream by Writer Module)
- Keyword research / keyword selection
- Internal linking suggestions
- Publishing or CMS integration
- User-facing UI (this is a pipeline module)
- Multi-locale support — English / United States only
- Rank tracking and citation monitoring
- Multi-tenant brand configuration
- Per-client ICP context — the brief generator derives a hypothetical searcher from the topic itself; brand and ICP shaping is the Writer Module's responsibility (per v1.5 spec)
- Downstream consumption of silo candidates — whether they automatically trigger new brief generation, enter a queue, or are surfaced to a human for approval is outside this module's scope

---

## 3. Success Metrics

Success in v2.0 is defined by structural validity, semantic-constraint adherence, and operational discipline. Ranking and LLM citation performance tracking is out of scope and will be revisited once publish-to-tracking infrastructure exists.

| Metric | Target |
|---|---|
| Output validates against JSON schema | 100% |
| Brief contains 3–5 FAQs | 100% |
| Brief contains 3–5 authority gap H3s | 100% |
| **No selected H2 has cosine > 0.78 to title embedding** | 100% |
| **No two selected H2s have cosine > 0.75 to each other** | 100% |
| **No two selected H2s come from the same coverage graph region** | 100% |
| **Every selected H2 passes scope verification or is logged with override reason** | 100% |
| Brief produces a non-empty title and scope_statement | 100% |
| End-to-end generation completes within 120s | ≥95% |
| Cost per brief stays under $1.00 | ≥95% |

The first four constraint-adherence metrics are mathematically guaranteed by the selection algorithm — failure to meet them indicates an implementation bug, not a quality issue.

---

## 4. System Architecture Overview

```
[Keyword Input]
      │
      ▼
┌─────────────────────┐
│  Step 0: Input      │  ◄── Reject empty/whitespace, >150 chars
│  Validation         │
└─────────────────────┘
      │
      ▼
┌──────────────────────────────────────────────────────────┐
│  Step 1 + 2 (Parallel) — UNCHANGED FROM v1.7             │
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
│  Step 3.5: Title +  │  ◄── NEW. Single LLM call.
│  Scope Statement    │  ◄── Inputs: seed, intent, top SERP titles,
│  Generation         │      H1s, meta descriptions, LLM fan-out
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 4: Subtopic   │  ◄── Aggregate all candidate sources
│  Aggregation        │  ◄── Lexical dedup (Levenshtein) preserved
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 5: Embedding  │  ◄── REWRITTEN. text-embedding-3-large
│  + Coverage Graph   │  ◄── Build pairwise similarity graph
│  Construction       │  ◄── Louvain community detection → regions
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 6: Hypothetical│ ◄── NEW. Single LLM call.
│  Searcher Persona    │ ◄── Generates persona + gap questions
│  Generation          │
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 7: Heading    │  ◄── REVISED priority formula
│  Priority Scoring   │  ◄── Includes information gain term
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 8: Constrained│  ◄── REWRITTEN. MMR selection with:
│  H2 Selection (MMR) │      • Relevance floor (≥0.55 to title)
│                     │      • Restatement ceiling (≤0.78 to title)
│                     │      • Inter-heading limit (≤0.75 pairwise)
│                     │      • Region uniqueness (max 1 per region)
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 8.5: Scope    │  ◄── NEW. LLM verification against
│  Verification       │      scope_statement. Out-of-scope H2s
│                     │      route to silo candidates.
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 9: Authority  │  ◄── Universal Authority Agent (3-pillar)
│  Gap Analysis       │  ◄── Reddit threads as context
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 10: FAQ       │  ◄── PAA + Reddit regex + LLM concern pass
│  Generation         │  ◄── Persona gap questions feed candidates
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 11: Structure │  ◄── Intent-aware assembly
│  Assembly           │  ◄── How-to sequential reordering
│                     │  ◄── Global subheading cap enforcement
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 12: Silo      │  ◄── REUSES regions from Step 5
│  Cluster            │  ◄── Regions that didn't contribute H2s
│  Identification     │      become silo candidates
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

### Step 1 — SERP Scraping (Unchanged from v1.7)

**Provider:** DataForSEO SERP API (Standard Queue)
**Locale:** English / United States only

**Outputs:**
- Headings (H1–H3) from top 20 organic results
- **Top 20 organic page titles** (used as input to Step 3.5)
- **Top 20 meta descriptions** (used as input to Step 3.5)
- SERP feature presence flags: shopping box, news box, local pack, featured snippet, PAA, product carousels, comparison tables

**Rules:**
- Exclude headings shorter than 3 words
- Exclude headings from paginated results (page 2+)
- Tag each heading with source URL and SERP position
- Strip boilerplate patterns ("Contact Us", "About the Author", "Related Posts")

### Step 2 — PAA, Reddit, Autocomplete, and LLM Fan-Out (Unchanged from v1.7)

All sub-sources (2A PAA, 2B Reddit, 2C Autocomplete + Keyword Suggestions, 2D LLM Fan-Out across 4 LLMs) operate identically to v1.7. See v1.7 Section 5 for full specifications. Cross-LLM consensus tracking via `llm_fanout_consensus` (0–4) is preserved.

### Step 3 — Intent Classification (Unchanged from v1.7)

Rules-based classifier on SERP feature signals, with LLM check for borderline ecom/commercial cases. Intent types: `informational`, `listicle`, `how-to`, `comparison`, `ecom`, `local-seo`, `news`, `informational-commercial`. See v1.7 Section 5 Step 3 for full rule mapping.

**Output:** `intent_type`, `intent_confidence`, `intent_review_required` (true if confidence < 0.75)

### Step 3.5 — Title + Scope Statement Generation (NEW)

**Purpose:** Commit to an explicit article title and scope statement that anchor all downstream selection and verification logic. Without this commitment, scope discipline can only be approximated from indirect signals.

**Method:** Single LLM call (model: same as section writing in Writer Module — likely the highest-quality available model, since title quality cascades through every downstream step).

**Inputs:**
- Seed keyword
- `intent_type` from Step 3
- Top 20 SERP titles from Step 1
- Top 20 SERP H1s from Step 1
- Top 20 meta descriptions from Step 1
- LLM fan-out responses from Step 2D (full text, not just extracted queries)

**Output schema (strict, additionalProperties: false):**

```json
{
  "title": "string (50–80 chars preferred, 100 char max)",
  "scope_statement": "string (≤500 chars)",
  "title_rationale": "string (≤300 chars)"
}
```

**Prompt requirements:**

The title generation LLM must:
- Examine competitor title patterns to identify SERP convention for this query
- Note what no competitor is doing (potential differentiation angle)
- Avoid generic AI-tells in titling: "Ultimate Guide to", "Complete Guide", "Everything You Need to Know", "The Definitive Guide", "Master [topic]"
- Produce a scope statement specific enough to be enforceable, not so specific that it preempts editorial judgment in the Writer Module
- Include a `does not cover` clause in the scope statement that names 1–3 adjacent topics this article will explicitly not address
- Stay within freshness/recency constraints: mention the current year only when the topic genuinely warrants it; do not reflexively stamp "in 2026" on every title

**Example output for seed `"what is tiktok shop"` with intent `informational`:**

```json
{
  "title": "What TikTok Shop Is and How It Works in 2026",
  "scope_statement": "Defines TikTok Shop, explains how the system functions for both sellers and buyers, and orients readers to the major components of the platform. Does not cover advanced seller tactics, algorithm optimization strategies, or operational decisions like inventory management or paid amplification.",
  "title_rationale": "Top 20 SERP titles converge on definitional framing. Featured snippet present indicates Google has settled on a canonical definition format. Adding 'in 2026' signals freshness against 2023-launch vintage of most ranking content."
}
```

**Failure handling:**

| Scenario | Behavior |
|---|---|
| LLM returns malformed JSON | One retry with stricter prompt; on second failure, abort run with `title_generation_failed` |
| Title field empty or >100 chars | One retry; on second failure, abort with `title_generation_failed` |
| Scope statement empty or missing `does not cover` clause | One retry with stricter prompt; on second failure, abort with `title_generation_failed` |

### Step 4 — Subtopic Aggregation (Mostly Unchanged from v1.7)

- Combine all scraped H1–H3 headings from Step 1 plus autocomplete queries, keyword suggestions, fan-out queries from all 4 LLMs, and response extractions from all 4 LLMs from Step 2
- **Add persona gap questions from Step 6** as candidate headings (tagged `source: "persona_gap"`)
- Normalize: lowercase + strip punctuation for comparison; preserve original casing for output
- Deduplicate using fuzzy matching (Levenshtein distance threshold ≤ 0.15) across all sources
- Tag each unique entry with `serp_frequency` and `avg_serp_position`
- Non-SERP sources (autocomplete, keyword suggestion, LLM fan-out, LLM response, persona gap) get `serp_frequency: 0` and `avg_serp_position: null`
- Track `llm_fanout_consensus` (integer 0–4) on each heading: count of LLMs whose fan-out queries or response extractions surfaced this topic

**Note on ordering:** Step 6 (persona generation) runs after Step 4 conceptually but its output feeds back into the candidate pool. Implementation should aggregate non-persona candidates first, then re-aggregate after persona output, then proceed to Step 5.

### Step 5 — Embedding + Coverage Graph Construction (REWRITTEN)

**Embedding model:** OpenAI `text-embedding-3-large` (1536-dimensional, upgraded from v1.7's `text-embedding-3-small` for finer-grained paraphrase discrimination).

**Substeps:**

**5.1 Embedding generation:**
1. Embed the seed keyword
2. Embed the title from Step 3.5
3. Embed the scope statement from Step 3.5
4. Embed each unique heading from Step 4
5. Normalize all embeddings to unit length (so cosine similarity equals dot product)

**5.2 Pre-filtering by relevance to title:**

```
For each heading:
    title_relevance = heading_embedding · title_embedding
    
    If title_relevance < 0.55:
        Move to discarded_headings with discard_reason: "below_relevance_floor"
    Else if title_relevance > 0.78:
        Move to discarded_headings with discard_reason: "above_restatement_ceiling"
    Else:
        Keep as eligible candidate
```

The 0.78 ceiling is the central anti-paraphrase mechanism. Headings restating the title are blocked at this gate, before any selection logic runs.

**5.3 Coverage graph construction:**

Using `networkx`, build an undirected graph where:
- Nodes are eligible candidates from 5.2
- Edges connect candidates with pairwise cosine similarity above the **edge threshold of 0.65**
- Edge weights are the cosine similarity values

**5.4 Community detection:**

Apply Louvain community detection (`networkx.algorithms.community.louvain_communities`) with `resolution=1.0` and a fixed `seed=42` for reproducibility. Output: list of node sets, each representing a topical region.

**5.5 Region scoring:**

For each region, compute:

| Metric | Formula |
|---|---|
| `density` | Number of candidates in the region |
| `source_diversity` | Count of distinct source types (serp, paa, reddit, autocomplete, keyword_suggestion, llm_fanout_*, llm_response_*, persona_gap) represented in the region |
| `centroid_title_distance` | Cosine similarity between region centroid (mean of member embeddings) and title embedding |
| `information_gain_signal` | Fraction of region candidates that come from non-SERP sources (Reddit, PAA, autocomplete, LLM fan-out, LLM response, persona gap). High value = readers ask about this but competitors aren't covering it. |

**Region elimination:**

| Rule | Action |
|---|---|
| Region has fewer than 2 candidates | Mark as singleton; eligible for selection but cannot become a silo candidate |
| Region centroid scores < 0.55 to title (region as a whole is off-topic) | Eliminate region; member candidates move to discarded_headings with `discard_reason: "region_off_topic"` |
| Region centroid scores > 0.78 to title (entire region restates the title) | Eliminate region; member candidates move to discarded_headings with `discard_reason: "region_restates_title"` |

### Step 6 — Hypothetical Searcher Persona Generation (NEW)

**Purpose:** Generate questions a curious searcher of this keyword would ask that the candidate pool doesn't address well. These become candidate H2s tagged `source: "persona_gap"` that re-enter the aggregation pool (Step 4).

**Method:** Single LLM call.

**Inputs:**
- Seed keyword
- `intent_type` from Step 3
- Title and scope statement from Step 3.5
- Top SERP H1s and meta descriptions from Step 1
- Aggregated candidate headings from Step 4 (pre-graph-construction)

**Output schema (strict, additionalProperties: false):**

```json
{
  "persona": {
    "description": "string (≤300 chars)",
    "background_assumptions": ["string (max 5 items)"],
    "primary_goal": "string (≤200 chars)"
  },
  "gap_questions": [
    {
      "question": "string",
      "rationale": "string (≤200 chars) — why this question matters and is not covered by existing candidates"
    }
  ]
}
```

**Constraints:**
- Generate 5–10 gap questions
- Questions must respect the scope statement — no questions outside the article's scope boundary
- Persona description must derive from topic + SERP signal, not from any external ICP context
- Each gap question feeds Step 4 as a candidate heading with `source: "persona_gap"`

**Failure handling:**

| Scenario | Behavior |
|---|---|
| LLM returns malformed JSON | One retry; on second failure, continue with empty gap_questions and log warning |
| Persona description empty | Continue; persona output is informational only, not used as a hard constraint |
| Zero gap questions returned | Continue; selection proceeds without persona-derived candidates |

### Step 7 — Heading Priority Scoring (REVISED)

**Combined priority formula:**

```
heading_priority = (0.30 × title_relevance) 
                 + (0.20 × normalized_serp_frequency) 
                 + (0.10 × position_weight) 
                 + (0.20 × normalized_llm_consensus)
                 + (0.20 × information_gain_score)

Where:
- title_relevance = cosine(heading_embedding, title_embedding)
- normalized_serp_frequency = min(serp_frequency / 20, 1.0)
- position_weight = 1.0 - ((avg_serp_position - 1) / 20) if avg_serp_position is not null, else 0.5
- normalized_llm_consensus = llm_fanout_consensus / 4
- information_gain_score = 1.0 if heading source is non-SERP and llm_fanout_consensus >= 1, 
                            else 0.7 if heading source is non-SERP, 
                            else 0.3 if heading source is SERP only,
                            else 0.0
```

**Rationale:**
- **Title relevance** (0.30) replaces v1.7's seed similarity. The title is the article's actual commitment.
- **SERP frequency** (0.20) is a proven signal that something is topically central but should not dominate.
- **Position weight** (0.10) reduced from v1.7's 0.15 — top-position bias compounds SERP convergence.
- **LLM consensus** (0.20) preserved at v1.7 level. Cross-model agreement is a strong citation-optimization signal.
- **Information gain** (0.20) is new. A heading that appears in Reddit/PAA/LLM fan-out but not in competitor SERP is exactly the differentiation we want to surface.

### Step 8 — Constrained H2 Selection via MMR (REWRITTEN)

**Algorithm:** Greedy Maximum Marginal Relevance (MMR) with hard constraints.

**Configuration:**

| Parameter | Default | Notes |
|---|---|---|
| `mmr_lambda` | 0.7 | Balance between topical value (priority score) and diversity |
| `target_h2_count` | 6 (capped intents), 10 (listicle/how-to baseline, uncapped) | From v1.7 intent rules |
| `inter_heading_threshold` | 0.75 | Maximum allowed pairwise cosine between any two selected H2s |

**Algorithm logic:**

```python
def select_h2s(candidates, title_embedding, target_count, mmr_lambda=0.7,
               inter_heading_threshold=0.75):
    """
    candidates: list of dicts with embedding, priority_score, region_id, heading text
    title_embedding: unit-normalized title embedding
    """
    selected = []
    selected_regions = set()
    selected_embeddings = []
    eligible = list(candidates)  # Already pre-filtered for relevance + restatement gates
    
    while eligible and len(selected) < target_count:
        best_score = -float('inf')
        best_idx = None
        
        for i, candidate in enumerate(eligible):
            # Hard constraint: region uniqueness
            if candidate['region_id'] in selected_regions:
                continue
            
            # Hard constraint: inter-heading anti-redundancy
            if selected_embeddings:
                max_pairwise = max(
                    candidate['embedding'] @ s for s in selected_embeddings
                )
                if max_pairwise > inter_heading_threshold:
                    continue
                redundancy_penalty = max_pairwise
            else:
                redundancy_penalty = 0.0
            
            # MMR objective
            mmr_score = (
                mmr_lambda * candidate['priority_score']
                - (1 - mmr_lambda) * redundancy_penalty
            )
            
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i
        
        if best_idx is None:
            break  # No eligible candidate satisfies all constraints
        
        chosen = eligible.pop(best_idx)
        selected.append(chosen)
        selected_regions.add(chosen['region_id'])
        selected_embeddings.append(chosen['embedding'])
    
    return selected
```

**Shortfall handling:**

If selection terminates with fewer H2s than `target_h2_count`, accept the shortfall. Output the H2s found and set `metadata.h2_shortfall = true` with `metadata.h2_shortfall_reason: "constraints_exhausted_eligible_pool"`. Do NOT relax thresholds or invent synthetic H2s to hit a quota — an honest brief with 4 strong H2s beats a padded brief with 6 weak ones.

**Discarded headings:**

Eligible candidates not selected are moved to `discarded_headings` with `discard_reason: "below_priority_threshold"` (didn't win MMR competition) or `discard_reason: "global_cap_exceeded"` (selected by MMR but cut by global subheading cap downstream — see Step 11).

### Step 8.5 — Scope Verification (NEW)

**Purpose:** Catch the small percentage of cases where a heading passes all numerical constraints but answers a different reader question than the title's promise. This is the "TikTok Shop algorithm signals" failure mode — topically related but out of scope.

**Method:** Single LLM call.

**Inputs:**
- Title from Step 3.5
- Scope statement from Step 3.5 (with explicit `does not cover` clause)
- All H2s selected by Step 8

**Output schema (strict, additionalProperties: false):**

```json
{
  "verified_h2s": [
    {
      "h2_text": "string",
      "scope_classification": "in_scope" | "borderline" | "out_of_scope",
      "reasoning": "string (≤200 chars)"
    }
  ]
}
```

**Routing:**

| Classification | Action |
|---|---|
| `in_scope` | Keep in selected H2s |
| `borderline` | Keep in selected H2s; flag in metadata for human review |
| `out_of_scope` | Remove from selected H2s; route to `silo_candidates` with `routed_from: "scope_verification"` |

After scope verification, if removals dropped the H2 count below target, the selection algorithm (Step 8) does NOT re-run to fill the gap. Accept the shortfall with `h2_shortfall = true`. Re-running selection risks pulling in candidates that would also fail scope verification, and the LLM call is non-deterministic enough that a re-run loop is risky.

**Failure handling:**

| Scenario | Behavior |
|---|---|
| LLM returns malformed JSON | One retry; on second failure, accept all H2s as `in_scope` and log warning. Do not abort the run — selection has already produced a valid outline by mathematical constraints. |
| LLM classifies an H2 not in the input list | Discard the rogue classification; log warning |

### Step 8.6 — H3 Selection (NEW)

**Purpose:** For each selected H2, choose 0–2 H3s from the candidate pool that elaborate the H2's scope without restating it. Authority Gap H3s (Step 9) are inserted afterward and may displace lower-priority H3s if the per-H2 cap is exceeded.

This step formalizes H3 selection as a parent-scoped mirror of Step 8: same MMR + region + anti-restatement principles, but applied at H2-scope rather than title-scope. Without explicit rules at this layer, an implementation might default to picking H3s by global priority regardless of parent H2, which would reproduce the v1.7 paraphrase failure mode at the H3 level.

**Inputs:**
- All eligible H3-level candidates from the coverage graph (Step 5) — the post-region-elimination pool minus the H2s selected by Step 8
- Selected H2s from Step 8 with their embeddings and `region_id`s
- Scope statement from Step 3.5

**Algorithm — for each selected H2:**

1. Compute `parent_relevance` for every H3 candidate as the cosine similarity between the H3 candidate embedding and the H2 embedding.

2. Filter the candidate pool to that H2's scope. Keep only H3 candidates that:
   - Have `parent_relevance >= 0.60` (must be related to the H2)
   - Have `parent_relevance <= 0.85` (must not restate the H2; threshold is slightly looser than the title-level 0.78 because H3s legitimately drill into narrower scopes)
   - Belong to the same coverage graph region as the H2, OR an adjacent region with edge weight `>= 0.65` to the H2's region centroid
   - Were not already selected as H2s elsewhere

3. Apply MMR within the filtered pool, using:
   - Target count: 2 H3s per H2 maximum
   - Inter-H3 anti-redundancy threshold: 0.78 pairwise (looser than the 0.75 used for H2s)
   - Priority score for H3s: same formula as H2s in Step 7, with `title_relevance` replaced by `parent_relevance` for the H2 the H3 is being assigned to

4. Accept shortfalls. If filtering produces fewer than 2 eligible H3s for a given H2, output what is available. Per Section 11, H3s are not required per H2.

**Discarded headings:**

H3 candidates dropped during this step are routed to `discarded_headings` with one of the following reasons:

| Filter | discard_reason |
|---|---|
| Below `parent_relevance >= 0.60` | `h3_below_parent_relevance_floor` |
| Above `parent_relevance <= 0.85` | `h3_above_parent_restatement_ceiling` |
| Lost the per-H2 MMR competition | `below_priority_threshold` |

A candidate that fails the parent-relevance check for one H2 is still considered for every other selected H2. Only candidates that fail against all selected H2s carry an `h3_*` discard reason in the final output.

**Authority Gap H3 Interaction:**

After Step 8.6 produces selected H3s per H2, Step 9 runs and adds 3–5 Authority Gap H3s. Each Authority Gap H3 is assigned to the most relevant H2. If adding an Authority Gap H3 would push that H2 over the 2-H3 cap:

1. Compare priority scores. If the Authority Gap H3 has a higher priority score than the lowest-scoring existing H3, the existing H3 is displaced (moved to `discarded_headings` with `discard_reason: "displaced_by_authority_gap_h3"`).
2. If the Authority Gap H3 has a lower priority score than all existing H3s on that H2, route it to the next-most-relevant H2 (recursive).
3. If no H2 can accommodate the Authority Gap H3 without violating the cap and the Authority Gap H3 has the lowest priority across the board, it is still kept (Authority Gap H3s are never discarded per Step 9 rules); the per-H2 cap may be exceeded by 1 in this edge case. Step 11 (Structure Assembly) must allow a maximum of 3 H3s per H2 specifically when Authority Gap H3s caused the overflow.

**Output:**

Each selected H2 carries an h3s array (possibly empty), and each H3 carries:
- `parent_h2_text` (so the structure is reconstructable from the flat `heading_structure` array)
- `parent_relevance` (the cosine similarity to its parent H2)
- All standard heading fields already specified in the output schema (`region_id`, `source`, scores, etc.)

**Failure handling:**

| Scenario | Behavior |
|---|---|
| H2 has 0 eligible H3s after filtering | Accept zero H3s for that H2; increment `metadata.h2s_with_zero_h3s` |
| Eligible pool is empty across all H2s | Continue without non-authority H3s; Step 9 still runs |
| Embedding required for H2 or H3 candidate is missing (defensive) | Skip that pairing; do not abort |

This step adds no new LLM calls — it is pure embedding math and MMR over the same vectors produced in Step 5.

### Step 9 — Authority Gap Analysis (Unchanged from v1.7)

Universal Authority Agent with three pillars (Human/Behavioral, Risk/Regulatory, Long-Term Systems). Inputs: aggregated heading list from Step 4 plus Reddit thread summaries from Step 2 as context (not as headings). See v1.7 Section 5 Step 6 for full specification.

**Output rules unchanged:**
- Exactly 3–5 new H3 subheadings
- Inserted immediately after the most relevant H2
- Tagged `source: "authority_gap_sme"`
- Authority gap H3s count toward the per-H2 limit of 2 H3s (with the cap-displacement rules specified in Step 8.6)
- Score is computed but `exempt: true` flag set — bypasses 0.55 relevance threshold
- Authority gap H3s are never discarded

### Step 10 — FAQ Generation (Mostly Unchanged from v1.7)

**Source A — Regex extraction (deterministic):**
- Extract sentences ending in `?` from Reddit post titles and top-comment text
- Filter: 5–25 words
- Add to candidate pool with PAA questions

**Source B — LLM concern extraction:**
- Single LLM call with all Reddit thread content
- Returns up to 10 implicit questions or concerns

**Source C — Persona gap questions (NEW):**
- Persona gap questions from Step 6 that did NOT make it into the H2 outline (either because they weren't aggregated as H2 candidates, or because they were aggregated but not selected) feed the FAQ candidate pool
- Tagged `source: "persona_gap"`

**Scoring formula (unchanged from v1.7):**

```
faq_score = (0.4 × source_signal) + (0.4 × semantic_relevance) + (0.2 × novelty_bonus)

Where:
- source_signal:
    - PAA = 1.0
    - Reddit ≥50 upvotes = 0.9
    - Reddit 10–49 upvotes = 0.6
    - Reddit <10 upvotes = 0.3
    - LLM-extracted concern = 0.5
    - Persona gap question = 0.6
- semantic_relevance: cosine similarity to title embedding (changed from seed in v1.7)
- novelty_bonus: 1.0 if topic not in heading_structure, else 0.0
```

**Selection rules (unchanged):** Top 5 by score with minimum threshold 0.5; if <3 pass, accept top 3 regardless; always output 3–5 FAQs.

### Step 11 — Structure Assembly (Unchanged from v1.7)

Universal structural constants, intent-aware H2/H3 caps, how-to sequential reordering, global subheading cap enforcement. See v1.7 Section 5 Step 8 for full specification.

| Rule | Value |
|---|---|
| Max content H2s (capped intents) | 6 |
| Max content H2s (listicle, how-to) | Uncapped |
| Max H3s per H2 | 2 |
| Authority gap H3s count toward per-H2 limit | Yes |
| Global content subheading cap (capped intents) | 15 |
| Global content subheading cap (listicle, how-to) | 20 |
| FAQ H2 + FAQ H3s | Outside both caps |

**Word budget:** Maximum 2,500 words across content sections; FAQ section excluded; enforcement is the Writer Module's responsibility.

### Step 12 — Silo Cluster Identification (REWRITTEN — Now Reuses Step 5 Regions)

**Purpose:** Convert non-selected coverage graph regions and scope-verification rejects into a prioritized roadmap of supporting cluster articles. Reuses regions computed in Step 5 — no additional clustering or embedding cost. Adds explicit filtering, search-demand validation, and a per-candidate viability check so the output is a defensible roadmap rather than a noisy list.

**Input:** All regions from Step 5 that did NOT contribute a selected H2 to the final outline, plus all candidates moved to `discarded_headings` with `discard_reason: "scope_verification_out_of_scope"`. The discard reason filtering in Step 12.1 governs which headings actually proceed.

**Process:** Run Steps 12.1 → 12.4 in order, then format per Step 12.6. Step 12.5 is reserved for v2.1.

#### Step 12.1 — Discard Reason Filtering

A heading's `discard_reason` determines whether it can become silo material. Re-routing the wrong reasons would generate articles that compete with the parent brief or surface noise.

| Discard Reason | Silo Eligible | Reasoning |
|---|---|---|
| `above_restatement_ceiling` | No | Paraphrases the title; routing to silo would generate articles competing with the parent. |
| `region_restates_title` | No | Same reasoning at the region level. |
| `below_relevance_floor` | No | Off-topic noise; not a future article on this subject. |
| `region_off_topic` | No | Same reasoning at the region level. |
| `scope_verification_out_of_scope` | Yes — high priority | Topically relevant, in the eligible band, but answers a different reader question. Highest-confidence silo material. |
| `below_priority_threshold` | Conditional | Eligible only if the heading's region did not contribute a selected H2. If the region did contribute, this heading is redundant with that H2 and excluded. |
| `global_cap_exceeded` | Yes — medium priority | Cut for length, not quality. |
| `low_cluster_coherence` | No | Already evaluated and rejected; do not re-evaluate. |
| `duplicate` | No | Lexical duplicate. |
| `displaced_by_authority_gap_h3` | No | H3-level signal, not H2-worthy. |
| `h3_below_parent_relevance_floor` | No | H3-level signal. |
| `h3_above_parent_restatement_ceiling` | No | H3-level signal. |

Only headings with "Yes" or "Conditional" eligibility proceed to Step 12.2. Headings filtered out at this step are counted in `metadata.silo_candidates_rejected_by_discard_reason`.

#### Step 12.2 — Cluster Formation

For each non-selected, non-eliminated region from Step 5 whose members survived Step 12.1, compute:

- `cluster_coherence_score` = average pairwise cosine similarity between region members
- `suggested_keyword` = the centroid heading (highest average similarity to all other region members)
- `recommended_intent` = applied via the same rules-based signal mapping from Step 3, using the region's heading patterns

For scope-verification rejects, treat each as a singleton silo candidate with `suggested_keyword = original heading text` and `cluster_coherence_score = 1.0`. Singletons from `scope_verification_out_of_scope` are exempt from the minimum-2-heading rule because they have already been evaluated and confirmed as on-topic-but-out-of-scope.

**Cluster quality rules:**

| Rule | Value |
|---|---|
| Minimum headings per cluster | 2 (singletons from scope verification are exempt) |
| Minimum cluster coherence score | 0.60 |
| Maximum silo candidates per brief | 10 |
| Review recommended threshold | Coherence between 0.60 and 0.70 |

- Clusters below 0.60 coherence are added to `discarded_headings` with `discard_reason: "low_cluster_coherence"`
- If more than 10 clusters qualify, take the 10 with the highest coherence scores
- If `cluster_coherence_score` is between 0.60 and 0.70, flag `review_recommended: true`

#### Step 12.3 — Search Demand Validation

A silo candidate that no one searches for is not a content opportunity. Compute a `search_demand_score` from signals already present on member headings:

```
search_demand_score =
    0.30 × normalized_max_serp_frequency
  + 0.25 × normalized_max_llm_consensus
  + 0.20 × paa_presence_indicator
  + 0.15 × autocomplete_presence_indicator
  + 0.10 × reddit_discussion_indicator
```

Where:
- `normalized_max_serp_frequency` = max `serp_frequency` among member headings, divided by 20
- `normalized_max_llm_consensus` = max `llm_fanout_consensus` among member headings, divided by 4
- `paa_presence_indicator` = 1.0 if any member heading has `source: "paa"`, else 0.0
- `autocomplete_presence_indicator` = 1.0 if any member heading has `source` in {`autocomplete`, `keyword_suggestion`}, else 0.0
- `reddit_discussion_indicator` = 1.0 if any member heading has `source: "reddit"`, else 0.0

Silo candidates with `search_demand_score < 0.30` are filtered out — they have weak external evidence of search demand. This is a hard threshold, configurable per Section 12.6 of the PRD's Python Implementation Notes. Candidates filtered out at this step are counted in `metadata.silo_candidates_rejected_by_search_demand`.

#### Step 12.4 — Independent Article Viability Check

For each silo candidate that passes Steps 12.1–12.3, run a single LLM call to verify the candidate would make a defensible standalone article — distinct from the parent brief's intent, not a thin spin-off, and substantive enough to support its own outline.

**Inputs:**
- The silo candidate's `suggested_keyword`
- The current brief's `title` and `scope_statement` (so the LLM can verify distinct intent)
- The member headings of the silo candidate

**Output schema (strict, additionalProperties: false):**

```json
{
  "candidate_keyword": "string",
  "viable_as_standalone_article": true,
  "reasoning": "string (≤150 chars)",
  "estimated_intent": "informational | listicle | how-to | comparison | ecom | local-seo | news | informational-commercial"
}
```

**Failure handling:**

| Scenario | Behavior |
|---|---|
| LLM returns malformed JSON | One retry; on second failure default `viable_as_standalone_article: true` and flag `metadata.silo_viability_fallback_applied: true` |
| LLM call timeout | Same as malformed JSON |

Candidates classified as `viable_as_standalone_article: false` are excluded from the final `silo_candidates` output array but logged in `metadata.silo_candidates_rejected_by_viability_check`.

Viability checks for distinct candidates are independent and SHOULD run in parallel — see Section 8 for performance impact.

#### Step 12.5 — Cross-Brief Deduplication (Deferred to v2.1)

Cross-brief deduplication of silo candidates requires a Supabase table for tracking silo candidates across briefs over time. Out of scope for v2.0; flagged as a v2.1 requirement.

**Future v2.1 logic:** maintain a `silo_candidates` table keyed by `client_id` + `suggested_keyword` embedding. On each new brief, check cosine similarity (≥ 0.85) against existing entries. Increment `cross_brief_occurrence_count` on duplicates. Surface candidates with high occurrence counts as priority article seeds in the platform UI.

**For v2.0:** every silo candidate's `cross_brief_occurrence_count` defaults to 1.

#### Step 12.6 — Output Format

Each silo candidate carries:
- `suggested_keyword`
- `cluster_coherence_score`
- `review_recommended`
- `recommended_intent`
- `routed_from`: `"non_selected_region"` (region didn't win H2 competition) or `"scope_verification"` (heading rejected by scope check)
- `source_headings[]` (member headings with text, source, title_relevance, heading_priority, discard_reason)
- `discard_reason_breakdown`: object mapping `discard_reason` values to counts among member headings
- `search_demand_score` (float, 0.0–1.0)
- `viable_as_standalone_article` (boolean)
- `viability_reasoning` (string, ≤150 chars)
- `estimated_intent` (one of the 8 intent types)
- `cross_brief_occurrence_count` (integer, always 1 for v2.0; populated by v2.1)

The `routed_from: "scope_verification"` flag remains particularly valuable — these are headings that almost made it into a brief but represent genuinely different articles, so they're high-confidence silo seeds. Combined with the `search_demand_score` and the viability check, the silo output becomes a prioritized roadmap rather than a noisy list.

---

## 6. Output Schema

```json
{
  "schema_version": "2.0",
  "keyword": "string",
  "title": "string",
  "scope_statement": "string",
  "title_rationale": "string",
  "intent_type": "informational | listicle | how-to | comparison | ecom | local-seo | news | informational-commercial",
  "intent_confidence": 0.0,
  "intent_review_required": false,
  "persona": {
    "description": "string",
    "background_assumptions": ["string"],
    "primary_goal": "string"
  },
  "heading_structure": [
    {
      "level": "H1 | H2 | H3",
      "text": "string",
      "type": "content | faq-header | faq-question | conclusion",
      "source": "serp | paa | reddit | authority_gap_sme | synthesized | autocomplete | keyword_suggestion | llm_fanout_chatgpt | llm_fanout_claude | llm_fanout_gemini | llm_fanout_perplexity | llm_response_chatgpt | llm_response_claude | llm_response_gemini | llm_response_perplexity | persona_gap",
      "original_source": "string | null",
      "title_relevance": 0.0,
      "exempt": false,
      "serp_frequency": 0,
      "avg_serp_position": 0.0,
      "llm_fanout_consensus": 0,
      "information_gain_score": 0.0,
      "heading_priority": 0.0,
      "region_id": "string | null",
      "scope_classification": "in_scope | borderline | null",
      "parent_h2_text": "string | null",
      "parent_relevance": 0.0,
      "order": 0
    }
  ],
  "faqs": [
    {
      "question": "string",
      "source": "paa | reddit | llm_extracted | persona_gap",
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
      "source": "string",
      "original_source": "string | null",
      "title_relevance": 0.0,
      "serp_frequency": 0,
      "avg_serp_position": 0.0,
      "llm_fanout_consensus": 0,
      "heading_priority": 0.0,
      "region_id": "string | null",
      "discard_reason": "below_relevance_floor | above_restatement_ceiling | region_off_topic | region_restates_title | below_priority_threshold | global_cap_exceeded | duplicate | low_cluster_coherence | scope_verification_out_of_scope | h3_below_parent_relevance_floor | h3_above_parent_restatement_ceiling | displaced_by_authority_gap_h3"
    }
  ],
  "silo_candidates": [
    {
      "suggested_keyword": "string",
      "cluster_coherence_score": 0.0,
      "review_recommended": false,
      "recommended_intent": "informational | listicle | how-to | comparison | ecom | local-seo | news | informational-commercial",
      "routed_from": "non_selected_region | scope_verification",
      "source_headings": [
        {
          "text": "string",
          "source": "string",
          "title_relevance": 0.0,
          "heading_priority": 0.0,
          "discard_reason": "string | null"
        }
      ],
      "discard_reason_breakdown": {
        "below_priority_threshold": 0,
        "global_cap_exceeded": 0,
        "scope_verification_out_of_scope": 0
      },
      "search_demand_score": 0.0,
      "viable_as_standalone_article": true,
      "viability_reasoning": "string",
      "estimated_intent": "informational | listicle | how-to | comparison | ecom | local-seo | news | informational-commercial",
      "cross_brief_occurrence_count": 1
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
    "silo_candidates_rejected_by_discard_reason": 0,
    "silo_candidates_rejected_by_search_demand": 0,
    "silo_candidates_rejected_by_viability_check": 0,
    "silo_viability_fallback_applied": false,
    "competitors_analyzed": 20,
    "reddit_threads_analyzed": 0,
    "h2_shortfall": false,
    "h2_shortfall_reason": "string | null",
    "h3_count_average": 0.0,
    "h2s_with_zero_h3s": 0,
    "regions_detected": 0,
    "regions_eliminated_off_topic": 0,
    "regions_eliminated_restate_title": 0,
    "regions_contributing_h2s": 0,
    "scope_verification_borderline_count": 0,
    "scope_verification_rejected_count": 0,
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
    "embedding_model": "text-embedding-3-large",
    "relevance_floor_threshold": 0.55,
    "restatement_ceiling_threshold": 0.78,
    "inter_heading_threshold": 0.75,
    "edge_threshold": 0.65,
    "mmr_lambda": 0.7,
    "low_serp_coverage": false,
    "reddit_unavailable": false,
    "llm_fanout_unavailable": {
      "chatgpt": false,
      "claude": false,
      "gemini": false,
      "perplexity": false
    }
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
| Title generation LLM fails twice | Abort with `title_generation_failed` |
| Persona generation LLM fails twice | Continue with empty persona output; log warning |
| All headings rejected by relevance/restatement gates (no eligible candidates) | Lower relevance floor to 0.40, retry; if still <3 eligible, abort with `no_eligible_candidates` |
| Selection algorithm produces fewer H2s than target | Accept shortfall; flag `h2_shortfall: true` with reason |
| Scope verification LLM fails twice | Accept all selected H2s as `in_scope`; log warning |
| Authority Agent returns malformed JSON | Retry once with stricter prompt; on second failure, return brief without authority gap headings + flag |
| OpenAI embeddings timeout | Retry 3x with exponential backoff; on final failure, abort |
| Authority Agent returns wrong heading count | Truncate to 5 if >5; retry if <3; on retry failure, accept what was returned |
| Intent confidence <0.50 even after LLM check | Default to `informational`; flag `intent_review_required: true` |
| No silo clusters meet minimum coherence threshold | Return empty `silo_candidates` array; do not abort |
| Silo viability check LLM fails twice (per candidate) | Default `viable_as_standalone_article: true`, set `metadata.silo_viability_fallback_applied: true`, log warning; do not abort |
| End-to-end exceeds 120s | Abort and notify user |

---

## 8. Performance Targets

**Trigger model:** Synchronous, user-initiated, runs in parallel with the keyword/entity/quadgram research module.

| Stage | Target | Max |
|---|---|---|
| End-to-end brief generation | 75s | 120s |
| SERP + Reddit + Autocomplete + 4-LLM Fan-Out scrape (parallel) | 30s | 60s |
| Intent classification + Title generation (sequential) | 8s | 15s |
| Embedding + graph construction + scoring | 5s | 10s |
| Persona generation | 5s | 10s |
| MMR selection + scope verification | 8s | 15s |
| H3 selection (Step 8.6, embedding math + MMR only) | 1–2s | 4s |
| Authority agent | 15s | 30s |
| Structure assembly + silo identification | 4s | 8s |
| Silo viability checks (Step 12.4, up to 10 candidates in parallel) | 5–10s | 15s |

The 4 LLM fan-out calls run concurrently with each other and with SERP/Reddit/Autocomplete. Title generation is sequential after intent classification (it uses intent type as input). Persona generation runs after graph construction completes (it benefits from seeing the candidate pool). Selection, scope verification, H3 selection (Step 8.6), and authority agent run sequentially.

H3 selection (Step 8.6) is pure embedding math and MMR — no new LLM calls — and adds approximately 1–2 seconds to the structure assembly stage. End-to-end target stays at 75s; 120s ceiling preserved.

Silo viability checks (Step 12.4) add 5–10s when run in parallel (recommended) or 80–85s end-to-end if run sequentially (not recommended). Each viability check is a single Claude call (~$0.01–$0.02) over a small payload (suggested_keyword + title + scope + member headings); they are independent across candidates and SHOULD be issued concurrently with `asyncio.gather`. With parallel execution, end-to-end target stays at 75s.

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
| OpenAI embeddings (text-embedding-3-large) | <$0.001 |
| **Title + scope statement generation (NEW)** | $0.03–$0.05 |
| **Persona generation (NEW)** | $0.02–$0.04 |
| **Scope verification (NEW)** | $0.02–$0.04 |
| LLM calls (intent borderline, heading polish, authority agent, FAQ extraction, how-to reordering) | $0.10–$0.30 |
| Coverage graph + Louvain clustering | $0.00 (CPU only, milliseconds) |
| Silo cluster identification | $0.00 (reuses Step 5 regions) |
| **Silo viability checks (Step 12.4, up to 10 candidates × $0.01–$0.02 each)** | $0.05–$0.20 |
| **Estimated total per brief** | **$0.35–$0.89** |
| **Budget ceiling** | **$1.00** |

**Monthly operational cost at 10–20 briefs/day:** ~$105–$534/month

Cost increase from v1.7's $0.19–$0.53 range to v2.0's $0.35–$0.89 range reflects four new LLM call sites (title, persona, scope verification, silo viability checks). Silo viability checks scale linearly with eligible silo candidates (capped at 10) and parallelize cleanly. Still under the $1.00 ceiling.

---

## 10. Volume and Scale Assumptions

- **Current volume:** 10–20 briefs/day
- **Trigger source (v2.0):** User-initiated via parent platform UI
- **Trigger source (v2.1+):** Cron job from Supabase database
- **Concurrency:** No requirement for v2.0 — sequential per-user execution acceptable

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
| Embedding model | OpenAI text-embedding-3-large |
| **Title + scope statement generated per brief** | Yes (Step 3.5) |
| **Title max length** | 100 chars |
| **Scope statement must include `does not cover` clause** | Yes |
| **Relevance floor (heading-to-title cosine minimum)** | 0.55 |
| **Restatement ceiling (heading-to-title cosine maximum)** | 0.78 |
| **Inter-heading anti-redundancy threshold (max pairwise cosine between selected H2s)** | 0.75 |
| **Coverage graph edge threshold** | 0.65 |
| **Region uniqueness in selection** | Max 1 H2 per coverage graph region |
| **MMR lambda** | 0.7 |
| **Scope verification runs after MMR selection** | Yes (Step 8.5) |
| **H3 parent_relevance floor (heading-to-parent-H2 cosine minimum)** | 0.60 |
| **H3 parent_relevance ceiling (heading-to-parent-H2 cosine maximum)** | 0.85 |
| **Inter-H3 anti-redundancy threshold (max pairwise cosine between H3s under one H2)** | 0.78 |
| **H3 selection runs per parent H2 (Step 8.6)** | Yes |
| Authority gap headings bypass relevance filter | Yes (still scored) |
| Authority gap headings per brief | 3–5 |
| Authority gap H3s count toward per-H2 limit | Yes |
| Authority gap H3s ever discarded | Never |
| Max content H2s (capped intents) | 6 |
| Max content H2s (listicle, how-to) | Uncapped |
| Max H3s per H2 (standard) | 2 |
| Max H3s per H2 (Authority Gap overflow only) | 3 (per Step 8.6 cap-displacement edge case) |
| H3s required per H2 | No |
| **H2 shortfall handling** | Accept shortfall; flag in metadata; do not relax thresholds or pad with synthetic content |
| FAQ counts toward H2 budget | No |
| FAQ counts toward global subheading cap | No |
| Conclusion is an H2 | No |
| Min FAQs | 3 |
| Max FAQs | 5 |
| Global content subheading cap (capped intents) | 15 |
| Global content subheading cap (listicle, how-to) | 20 |
| Max article word count | 2,500 (FAQ excluded) |
| **Silo candidates reuse Step 5 regions** | Yes (no additional clustering cost) |
| Silo candidate sources | Non-selected regions + scope-verification rejects |
| **Silo discard reason filtering (Step 12.1)** | Yes — only specified `discard_reason` values eligible |
| Min headings per silo cluster | 2 (singletons from scope verification exempt) |
| Min cluster coherence score | 0.60 |
| **Silo search demand minimum threshold (Step 12.3)** | 0.30 |
| **Silo viability check per candidate (Step 12.4)** | Yes |
| **Cross-brief silo deduplication (Step 12.5)** | Deferred to v2.1 |
| Max silo candidates per brief | 10 |
| Review recommended threshold | Coherence between 0.60 and 0.70 |
| **ICP context input** | Not accepted; brief generator derives hypothetical searcher from topic itself |

---

## 12. Python Implementation Notes

This section provides reference implementations for the core mathematical operations. These are not exhaustive but anchor the engineering spec.

### 12.1 Required Libraries

```python
# Core
openai          # text-embedding-3-large + LLM calls
numpy           # vector math
networkx        # graph construction + Louvain community detection
pydantic        # typed data models throughout pipeline

# Optional / fallback
scikit-learn    # alternative clustering (HDBSCAN, agglomerative) if Louvain proves unstable
```

### 12.2 Embedding Generation

```python
from openai import OpenAI
import numpy as np

client = OpenAI()

def embed(texts: list[str]) -> np.ndarray:
    """Returns (n_texts, 1536) array of unit-normalized embeddings."""
    response = client.embeddings.create(
        model="text-embedding-3-large",
        input=texts
    )
    embeddings = np.array([e.embedding for e in response.data])
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    return embeddings / norms
```

### 12.3 Pre-filtering by Relevance + Restatement Gates

```python
def filter_eligible(
    candidate_embeddings: np.ndarray,
    title_embedding: np.ndarray,
    relevance_floor: float = 0.55,
    restatement_ceiling: float = 0.78,
) -> tuple[np.ndarray, list[int], list[int]]:
    """
    Returns:
        - eligible_mask: boolean array marking eligible candidates
        - rejected_below_floor: indices rejected for being off-topic
        - rejected_above_ceiling: indices rejected for restating title
    """
    title_relevances = candidate_embeddings @ title_embedding
    eligible_mask = (title_relevances >= relevance_floor) & (title_relevances <= restatement_ceiling)
    rejected_below = np.where(title_relevances < relevance_floor)[0].tolist()
    rejected_above = np.where(title_relevances > restatement_ceiling)[0].tolist()
    return eligible_mask, rejected_below, rejected_above
```

### 12.4 Coverage Graph Construction + Louvain Community Detection

```python
import networkx as nx
from networkx.algorithms.community import louvain_communities

def build_coverage_graph(
    embeddings: np.ndarray,
    edge_threshold: float = 0.65,
) -> nx.Graph:
    """Build undirected graph with edges between similar candidates."""
    n = len(embeddings)
    sim = embeddings @ embeddings.T
    
    G = nx.Graph()
    G.add_nodes_from(range(n))
    
    # Vectorized edge construction
    rows, cols = np.where(np.triu(sim > edge_threshold, k=1))
    edges = [(int(r), int(c), {"weight": float(sim[r, c])}) for r, c in zip(rows, cols)]
    G.add_edges_from(edges)
    
    return G

def detect_regions(G: nx.Graph, resolution: float = 1.0, seed: int = 42) -> list[set[int]]:
    """Louvain community detection. Returns list of node-index sets."""
    return louvain_communities(G, resolution=resolution, seed=seed)
```

### 12.5 MMR Selection with Hard Constraints

```python
def select_h2s_mmr(
    candidates: list[dict],         # each has 'embedding', 'priority_score', 'region_id'
    target_count: int,
    inter_heading_threshold: float = 0.75,
    mmr_lambda: float = 0.7,
) -> list[dict]:
    """Greedy MMR selection with region uniqueness and pairwise constraints."""
    selected: list[dict] = []
    selected_regions: set = set()
    selected_embeddings: list[np.ndarray] = []
    eligible = list(candidates)
    
    while eligible and len(selected) < target_count:
        best_score = -float('inf')
        best_idx = None
        
        for i, cand in enumerate(eligible):
            if cand['region_id'] in selected_regions:
                continue
            
            if selected_embeddings:
                max_pairwise = max(
                    float(cand['embedding'] @ s) for s in selected_embeddings
                )
                if max_pairwise > inter_heading_threshold:
                    continue
                redundancy = max_pairwise
            else:
                redundancy = 0.0
            
            mmr = mmr_lambda * cand['priority_score'] - (1 - mmr_lambda) * redundancy
            
            if mmr > best_score:
                best_score = mmr
                best_idx = i
        
        if best_idx is None:
            break
        
        chosen = eligible.pop(best_idx)
        selected.append(chosen)
        selected_regions.add(chosen['region_id'])
        selected_embeddings.append(chosen['embedding'])
    
    return selected
```

### 12.6 Threshold Tuning Note

All thresholds (`0.55`, `0.78`, `0.75`, `0.65`, `0.7`) are starting defaults derived from prior work with `text-embedding-3-large` on similar content. The implementation must:

- Make every threshold a configuration value (not a hardcoded constant)
- Log every rejection at every gate with the heading text and the score that triggered the rejection
- Provide a "tuning mode" output that surfaces all candidate scores so operators can adjust thresholds based on real production behavior

Expect first-week tuning. Pay particular attention to the restatement ceiling (0.78) — this is the most consequential threshold and the most sensitive to seed phrasing patterns.

---

## 13. What This PRD Does Not Cover

To be addressed in the engineering implementation spec:
- Authentication / API key management for DataForSEO and OpenAI
- Rate limiting and retry logic
- Caching strategy for repeated keywords
- Cost tracking and monitoring per brief
- Logging and observability requirements (note: the threshold-tuning logging in §12.6 is required, not optional)
- Schema versioning compatibility with Writer Module v1.5+
- Specific LLM model selection for each agent call (intent fallback, title generation, persona, scope verification, heading polish, authority agent, FAQ extraction, how-to reordering)
- Specific model versions for each fan-out LLM (ChatGPT, Claude, Gemini, Perplexity) — should be configurable
- Downstream consumption of silo candidates — whether they automatically trigger new brief generation, enter a queue, or are surfaced to a human for approval
- Threshold tuning workflow and acceptance criteria for production behavior

---

## 14. Migration from v1.7

### 14.1 Breaking Changes

- Output schema changes substantially. Writer Module consumers must update to handle:
  - New top-level fields: `title`, `scope_statement`, `title_rationale`, `persona`
  - New per-heading fields: `title_relevance` (replaces `semantic_score`), `region_id`, `scope_classification`, `information_gain_score`
  - New metadata fields: graph structure stats, threshold values used, shortfall flags
  - New source values: `persona_gap`
  - New `discard_reason` values: `above_restatement_ceiling`, `region_off_topic`, `region_restates_title`, `scope_verification_out_of_scope`
  - Removed field: `semantic_score` (renamed to `title_relevance`; semantically different — measures distance from title, not seed)
- Embedding model changes from `text-embedding-3-small` to `text-embedding-3-large`. Any cached v1.7 embeddings cannot be reused.
- Heading priority formula changes. Briefs from v1.7 and v2.0 are not directly comparable on priority scores.

### 14.2 Non-Breaking Continuity

These v1.7 elements are preserved unchanged:
- All data acquisition (Steps 1, 2)
- Intent classification (Step 3)
- Subtopic aggregation logic (Step 4)
- Authority Gap Agent (Step 9)
- FAQ scoring formula (Step 10), with `semantic_relevance` now measured against title rather than seed
- Structure assembly rules (Step 11): H2/H3 caps, intent-aware structure, how-to reordering, word budgets
- Silo cluster quality rules (Step 12)
- DataForSEO and OpenAI integration patterns

### 14.3 Suggested Test Fixtures

To validate v2.0 against the failure modes that motivated the rewrite:

1. **Fixture A — TikTok Shop replication.** Run the seed `"what is tiktok shop"` and verify:
   - Title generated is definitional, not seller-tactical
   - At most one H2 has cosine > 0.85 to title (should be zero by construction)
   - All paraphrase H2s ("What exactly is TikTok Shop", "What is a TikTok Shop seller", etc.) appear in `discarded_headings` with `discard_reason: "above_restatement_ceiling"`
   - "TikTok Shop algorithm signals"-type headings appear in `silo_candidates` with `routed_from: "scope_verification"` or as non-selected regions
   - For each selected H2, every assigned H3 has `parent_relevance` in [0.60, 0.85] — no H3 paraphrases its parent
   - Within any single H2, no two H3s have pairwise cosine > 0.78 — H3 siblings do not paraphrase each other
   - Every entry in `silo_candidates` has `search_demand_score > 0.0`
   - "TikTok Shop algorithm signals"-type rejects are classified with `viable_as_standalone_article: true` and `estimated_intent` of `how-to` or `informational`
2. **Fixture B — Sparse SERP.** Run a niche keyword with <10 SERP results. Verify graceful degradation: `low_serp_coverage: true` and reasonable persona-gap-driven outline.
3. **Fixture C — Listicle intent.** Run a "best X" keyword. Verify uncapped H2 selection respects intent-specific rules and that each list-item-H2 is a distinct region.
4. **Fixture D — Constraint exhaustion.** Construct a scenario where eligible candidates cluster heavily in 2–3 regions only. Verify `h2_shortfall: true` and `h2_shortfall_reason: "constraints_exhausted_eligible_pool"`.
5. **Fixture E — Title generation failure path.** Mock title generation LLM to return malformed JSON twice. Verify run aborts with `title_generation_failed`.
6. **Fixture F — Scope verification override.** Run a brief where the LLM marks an H2 `out_of_scope` that a human reviewer would consider in-scope. Verify the H2 routes to silo and the metadata captures the rejection. (This fixture is for catching false-positive scope rejections during tuning.)
7. **Fixture G — Threshold sensitivity.** Run the same keyword 3 times with restatement_ceiling values of 0.74, 0.78, 0.82. Compare outputs. The middle run should be the production default; the others should produce visibly worse (over-constrained or under-constrained) results.
8. **Fixture H — H3 sparsity.** Construct a scenario where a selected H2 has very few eligible H3 candidates after parent-relevance filtering (e.g., a niche H2 whose region is small and well-isolated from other regions). Verify `metadata.h2s_with_zero_h3s > 0`, that the brief is still valid, and that Authority Gap H3s still attach to the most-relevant available H2.
9. **Fixture I — Silo discard reason filtering.** Construct a brief where many headings are discarded with `discard_reason: "above_restatement_ceiling"` (i.e., the LLM fan-out / SERP returned several near-paraphrases of the title). Verify that none of these headings appear in `silo_candidates` and that `metadata.silo_candidates_rejected_by_discard_reason` is incremented to match.
10. **Fixture J — Silo viability rejection.** Mock the Step 12.4 viability LLM to return `viable_as_standalone_article: false` for a known silo candidate. Verify the candidate is excluded from the final `silo_candidates` array and that `metadata.silo_candidates_rejected_by_viability_check` is incremented by 1.

---

## 15. Version History

| Version | Date | Notes |
|---|---|---|
| 1.0 | Initial draft | Original PRD |
| 1.1 | 2026-04-29 | Added success metrics, failure modes, FAQ scoring formula, heading priority formula, borderline ecom LLM check, format directives, performance targets, cost model, input validation, informational-commercial intent type |
| 1.2 | 2026-04-29 | Added autocomplete and keyword suggestions as heading candidate sources |
| 1.3 | 2026-04-29 | Added LLM fan-out queries via DataForSEO LLM Responses API (ChatGPT); added response content extraction as additional heading candidate source |
| 1.4 | 2026-04-29 | Raised word budget to 2,500; added global content subheading cap; authority gap H3s now count toward per-H2 limit; H3s optional per H2 |
| 1.5 | 2026-04-29 | Reduced max H3s per H2 from 3 to 2 |
| 1.6 | 2026-04-29 | Expanded LLM fan-out capture from ChatGPT-only to all 4 major LLMs; added cross-LLM consensus tracking; rebalanced heading priority formula to weight LLM consensus at 0.2 |
| 1.7 | 2026-04-29 | Added Step 9 Silo Cluster Identification; added `discarded_headings` and `silo_candidates` to output schema; added cluster quality rules, review flag, and failure mode for empty silo results |
| **2.0** | **2026-05-01** | **Major architectural rewrite. Added Step 3.5 (title + scope statement generation), Step 6 (hypothetical searcher persona generation), Step 8.5 (scope verification), and Step 8.6 (H3 selection — applies the same MMR + region + anti-restatement principles at H2-scope rather than title-scope, with `parent_relevance` floor 0.60 and ceiling 0.85, inter-H3 threshold 0.78, and Authority Gap cap-displacement rules). Replaced lexical-only deduplication with embedding-based pre-filtering (relevance floor 0.55, restatement ceiling 0.78). Replaced ad-hoc heading selection with MMR optimization respecting region uniqueness and inter-heading anti-redundancy (max 0.75 pairwise cosine). Added coverage graph construction via Louvain community detection. Upgraded embedding model from text-embedding-3-small to text-embedding-3-large. Rebalanced heading priority formula to include explicit information_gain_score term. Silo cluster identification now reuses Step 5 regions instead of clustering discarded headings separately. Output schema fundamentally restructured: `semantic_score` renamed to `title_relevance`; new fields `title`, `scope_statement`, `persona`, `region_id`, `scope_classification`, `information_gain_score`, `parent_h2_text`, `parent_relevance`; new discard reasons (including `h3_below_parent_relevance_floor`, `h3_above_parent_restatement_ceiling`, `displaced_by_authority_gap_h3`); new metadata for graph structure, shortfall flags, and H3 distribution (`h3_count_average`, `h2s_with_zero_h3s`). Cost ceiling raised from $0.75 to $1.00. End-to-end target raised from 60s to 75s. Brief generator does not accept ICP context; hypothetical searcher is derived from topic + SERP signal only. Fixes the v1.7 failure modes documented in Section 1: paraphrase-H2 outlines and topical-clone outlines.** |
| **2.0.2** | **2026-05-01** | **Refined Step 12 (Silo Cluster Identification) into six numbered subsections: 12.1 explicit `discard_reason` filtering (only `scope_verification_out_of_scope`, conditional `below_priority_threshold`, and `global_cap_exceeded` route to silos; restatement ceiling and off-topic rejects are excluded so silos never compete with the parent brief); 12.2 cluster formation (preserves region reuse + coherence + centroid); 12.3 search demand validation with hard threshold 0.30 against a five-signal `search_demand_score` (max SERP frequency, max LLM consensus, PAA / autocomplete / Reddit presence indicators); 12.4 per-candidate viability LLM check with strict JSON output (`viable_as_standalone_article`, `reasoning`, `estimated_intent`) and parallel execution; 12.5 cross-brief deduplication scoped out as a v2.1 requirement; 12.6 expanded silo candidate output with `discard_reason_breakdown`, `search_demand_score`, `viable_as_standalone_article`, `viability_reasoning`, `estimated_intent`, and `cross_brief_occurrence_count`. New metadata counters: `silo_candidates_rejected_by_discard_reason`, `silo_candidates_rejected_by_search_demand`, `silo_candidates_rejected_by_viability_check`, `silo_viability_fallback_applied`. Cost range updated to $0.35–$0.89 reflecting up to 10 parallel viability checks at $0.01–$0.02 each; $1.00 ceiling preserved; end-to-end target stays at 75s under parallel execution. New test fixtures I (discard-reason filtering) and J (viability rejection); Fixture A extended to verify silo `search_demand_score > 0` and `viable_as_standalone_article: true` for in-band scope rejects. No breaking schema changes — new fields are additive.** |
