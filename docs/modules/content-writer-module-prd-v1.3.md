# PRD: Content Writer Module
**Version:** 1.4
**Status:** Draft
**Last Updated:** April 30, 2026
**Part of:** ShowUP Local — Content Generation Platform
**Upstream Dependencies:** SIE Term & Entity Module · Research & Citations Module (v1.1) · Content Brief Generator Module (v1.7)
**Downstream Dependency:** Sources Cited Module (v1.1)

---

## 1. Problem Statement

The Content Brief Generator (v1.7), SIE Term & Entity Module, and Research & Citations Module together produce a fully researched, structured plan for a blog post — heading architecture, FAQ questions, required terms, entity recommendations, format directives, and a set of verified, source-anchored claims mapped to every content section. That plan has no value until it becomes actual prose.

Executing a content brief manually is time-consuming, inconsistent, and failure-prone. Human writers drift from the approved heading structure, ignore term usage targets, violate word budgets, bury answers under preamble, and introduce unverifiable claims — fabricated statistics, unsupported pricing assertions, and jurisdiction-specific regulatory statements that the system cannot confirm.

This module converts the upstream brief, term intelligence, and verified citation pool into a complete, publication-ready blog post that is optimized for both Google search ranking and LLM citation (AEO). By grounding factual assertions in the verified claims delivered by the Research & Citations Module, the Writer avoids fabricating statistics — the citations do the sourcing work so the Writer does not have to invent it.

---

## 2. Goals

- Accept structured input from the Content Brief Generator, Research & Citations Module, and SIE Term & Entity Module as independent payloads and produce a complete blog post
- Generate a title, enrich the H1, and write every content section defined in the heading structure
- Honor the word budget, format directives, heading hierarchy, and term usage targets delivered by upstream modules — the writer does not reinterpret the brief
- Produce content structured for LLM citation: answer-first paragraphs, direct question answers, clean section boundaries, and schema-compatible FAQ output
- Ground factual assertions in the verified claims provided by the Research & Citations Module; treat fallback stub claims as source references only, not as basis for specific factual assertions
- Track which citations were used or unused in prose and output a per-citation usage record for analytics and downstream link-rot monitoring
- Output a structured JSON article object that preserves section boundaries, citation usage, term tracking, and compliance metadata for downstream quality review

### Out of Scope (v1)
- Keyword research or brief generation (handled upstream)
- Internal linking suggestions
- Image selection or alt-text generation
- Meta description generation
- Schema markup injection (JSON-LD)
- CMS publishing or API push
- Multi-locale support — English / United States only
- Rank tracking or citation link-rot monitoring (deferred to a future monitoring module, per Research & Citations Module PRD)
- Human review workflows or editorial approval routing
- Rewriting or re-generating content from a prior run — each run is independent

---

## 3. Success Metrics

Success in v1 is defined by structural compliance, term coverage, and guardrail enforcement — not by downstream ranking performance, which is not measurable from this module's output alone.

| Metric | Target |
|---|---|
| Output validates against JSON schema | 100% |
| Word count within word budget (±5%) | ≥95% |
| All heading_structure entries present in output | 100% |
| Required terms meeting zone usage minimums | ≥90% |
| Format directives satisfied (lists, tables, answer-first) | 100% |
| FAQ section contains correct question count (3–5) | 100% |
| Conclusion section present | 100% |
| End-to-end generation completes within 90s | ≥95% |
| Cost per article under $0.75 | ≥95% |

---

## 4. Inputs

The Content Writer Module receives three upstream JSON payloads on each run. All three are required. If any is missing or fails schema validation, the module aborts with a structured error.

### Input A — Content Brief Generator Output (v1.7 schema)

The raw output JSON from the Content Brief Generator. This is the authoritative source for heading structure, word budget, format directives, and FAQ content. Key fields consumed:

| Field | Usage |
|---|---|
| `keyword` | Seed keyword — used for title generation and to anchor the H1 |
| `intent_type` | Governs tone, section ordering, and structural patterns (how-to steps vs. listicle items vs. informational prose) |
| `heading_structure` | Ordered list of H1/H2/H3 nodes the writer must produce, in sequence |
| `heading_structure[].text` | Exact heading text to use — the writer does not rewrite headings |
| `heading_structure[].type` | `content`, `faq-header`, `faq-question`, `conclusion` — drives section treatment |
| `heading_structure[].order` | Determines output sequence |
| `faqs` | Ordered list of FAQ questions with `question` text and `faq_score` |
| `structural_constants.conclusion` | Flags conclusion as a structural block; writer generates the conclusion prose |
| `format_directives` | `require_bulleted_lists`, `require_tables`, `min_lists_per_article`, `min_tables_per_article`, `answer_first_paragraphs` |
| `metadata.word_budget` | 2,500 words maximum across all content sections; FAQ excluded |
| `metadata.h2_count` | Used for budget-per-section math |
| `metadata.h3_count` | Used for budget-per-section math |

### Input B — Research & Citations Module Output

The full output JSON from the Research & Citations Module. This payload contains the verified citation pool mapped to the brief's heading structure. Key fields consumed:

| Field | Usage |
|---|---|
| `keyword` | Cross-validated against Brief `keyword` — mismatch aborts the run |
| `citations[]` | Full list of verified citations — one or more per content H2 and selected authority gap H3s |
| `citations[].citation_id` | Unique ID used to look up citations for a heading via `heading_structure[].citation_ids`, and used as the value embedded in `{{citation_id}}` markers placed in prose. Must conform to regex `^cit_[0-9]+$`. |
| `citations[].claims[]` | Verified, source-anchored claims; each includes `claim_text`, `relevance_score`, `extraction_method`, and `verification_method` |
| `citations[].extraction_method` | `verbatim_extraction` or `fallback_stub` — governs how the Writer may use the claim (see Step 4F) |
| `heading_structure[].citation_ids` | Array of `citation_id` values mapped to each heading — used to resolve which citations apply to which section |

The following `citations[]` fields are **not consumed** by the Writer Module v1.4: `url`, `title`, `author`, `publication`, `published_date`. These fields pass through downstream and are consumed by the Sources Cited Module for citation entry rendering. The Writer Module only references citations by their `citation_id` via inline `{{citation_id}}` markers placed in prose at the point of citation use (see Step 4F).

### Input C — SIE Term & Entity Module Output

The full output JSON from the SERP Intelligence Engine. Key fields consumed:

| Field | Usage |
|---|---|
| `keyword` | Cross-validated against Brief `keyword` — mismatch aborts the run |
| `terms.required[]` | Full list of Required terms the writer must incorporate |
| `usage_recommendations[]` | Per-zone usage ranges (min/target/max) per term; writer targets the `target` value for each zone |
| `target_keyword.minimum_usage` | Minimum occurrence floors per zone for the seed keyword itself |
| `terms.avoid[]` | Terms the writer must not use |
| `word_count.target` | SIE's word count recommendation — used to cross-validate the brief's `word_budget` |
| `entities[]` (via merged `terms`) | Entities with `entity_category`, `example_context`, and `ner_variants` used to enrich H1 and high-value sections |

### Input Cross-Validation

Before any content generation begins, the module validates all three inputs against each other:

| Check | Failure Behavior |
|---|---|
| `brief.keyword == research.keyword` (case-insensitive) | Abort with structured error if mismatch |
| `brief.keyword == sie.keyword` (case-insensitive) | Abort with structured error if mismatch |
| `sie.word_count.target` within ±20% of `brief.metadata.word_budget` | Flag `word_count_conflict: true` in metadata; proceed using `brief.metadata.word_budget` as authoritative |
| `brief.heading_structure` is non-empty and ordered | Abort if empty; warn if `order` values have gaps |
| `brief.faqs` count is 3–5 | Abort if outside range |
| `research.citations` absent or empty | Continue without citation grounding; log `no_citations: true` warning — degraded mode, not abort |

---

## 5. System Architecture Overview

```
[Brief JSON + Research JSON + SIE JSON]
         │
         ▼
┌─────────────────────┐
│  Input Validation   │  ◄── Schema check, cross-validation, keyword match
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 1: Title      │  ◄── LLM generation — keyword + intent + top entities
│  Generation         │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 2: H1         │  ◄── Exact keyword + entity enrichment injection
│  Enrichment         │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 3: Word       │  ◄── Distribute budget across sections
│  Budget Allocation  │
└─────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  Step 4: Section Writing (sequential, per heading node) │
│  ┌─────────────────────────────────────────────────┐   │
│  │ For each H2 + its H3 children (in order):       │   │
│  │  - Write answer-first intro paragraph           │   │
│  │  - Write body content within section budget     │   │
│  │  - Inject required terms per zone targets       │   │
│  │  - Apply format directives (lists, tables)      │   │
│  │  - Apply intent-specific patterns               │   │
│  │  - Resolve citation_ids → inject verified claims  │   │
│  │  - Place inline hyperlinks; mark citations used   │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 5: FAQ        │  ◄── Direct answers per faq node, schema-ready
│  Section Writing    │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 6: Conclusion │  ◄── Synthesizing summary, soft CTA
│  Writing            │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 7: Citation   │  ◄── Reconcile all citation_ids against sections written
│  Usage Reconcil-    │  ◄── Mark each citation used/unused; record section refs
│  iation             │
└─────────────────────┘
         │
         ▼
[Structured JSON Article Output]
```

---

## 6. Functional Requirements

### Step 0 — Input Validation

All validation runs before any LLM call is made.

| Rule | Action |
|---|---|
| Either input payload is missing | Abort with structured error |
| `brief.keyword != sie.keyword` (case-insensitive) | Abort with structured error |
| `brief.heading_structure` is empty | Abort with structured error |
| `brief.faqs` count outside 3–5 | Abort with structured error |
| `brief.metadata.word_budget` not present | Default to 2,500; log warning |
| `sie.terms.required` is empty | Continue; log `no_required_terms: true` warning |
| `research.citations` absent or empty | Continue; log `no_citations: true` — section writing proceeds without citation grounding |
| `sie.word_count.target` diverges from `brief.word_budget` by >20% | Flag `word_count_conflict: true`; use brief as authoritative |

---

### Step 1 — Title Generation

The title is not included in the Content Brief Generator output (explicitly deferred). This is the only content element the Writer Module generates without a heading-level instruction.

**Inputs:**
- `brief.keyword`
- `brief.intent_type`
- All Required terms and entities from `sie.terms.required`, prioritized by `recommendation_score`

**Rules:**
- Title must contain the seed keyword
- Title must incorporate as many high-scoring Required terms and entities from the SIE output as naturally fit — keyword and entity coverage takes priority over brevity
- Title must match intent tone:
  - `how-to` → starts with "How to" or "How [Audience] Can"
  - `listicle` → leads with a number (e.g., "7 Reasons…")
  - `comparison` → includes "vs." or "or"
  - `informational`, `local-seo`, `ecom`, `informational-commercial`, `news` → declarative, value-led statement
- LLM generates 3 title candidates; selection is deterministic (pick candidate with highest combined keyword + entity coverage)
- Title is stored in `output.title`; it is not injected into `heading_structure`

---

### Step 2 — H1 Enrichment

The H1 in the brief's `heading_structure` is the exact-match seed keyword (e.g., "Water Heater Repair"). The Writer Module enriches the H1 for on-page use without altering the heading text itself.

**H1 enrichment definition:** A sub-head or lede sentence immediately following the H1 that incorporates 1–2 high-salience entities from `sie.terms.required` to provide topical context before the first body section begins.

**Rules:**
- The H1 text itself is written verbatim from `heading_structure`
- The enrichment lede is 1 sentence, maximum 25 words
- Must include at least 1 entity with `entity_category` in: `services`, `equipment`, `problems`, `methods`
- Must not be a complete restatement of the title

---

### Step 3 — Word Budget Allocation

Before writing begins, the module distributes the 2,500-word content budget across sections. The FAQ section is excluded from the budget.

**Allocation formula:**

```
base_section_budget = word_budget / total_content_sections

Where:
total_content_sections = h2_count + h3_count
  (from brief.metadata; conclusion counts as one section)
```

**Adjustment rules:**
- Authority gap H3s (tagged `source: "authority_gap_sme"`) receive a 1.2x budget multiplier — these sections contain the highest-value original information and should not be constrained to base budget
- How-to and listicle intents allocate equal budget per step/item (no adjustment)
- Conclusion receives a fixed budget of 100–150 words regardless of section count
- If total allocated words exceed `word_budget`, scale all non-conclusion sections proportionally downward

**Output:** A `section_budget` map keyed by heading `order` index.

---

### Step 4 — Section Writing

Sections are written sequentially, following `heading_structure[].order`. Each H2 and its child H3s are written as a group (one LLM call per H2 group).

#### 4A — Answer-First Paragraphs

When `format_directives.answer_first_paragraphs` is `true` (default per brief spec), every H2 section must open with a direct answer sentence before elaborating. This is the primary AEO optimization mechanism.

**Rule:** The first sentence of every H2 section must directly address what the heading implies. If the heading is "How Long Does Water Heater Repair Take?", the first sentence must answer that question in plain terms — not begin with background context.

**AEO answer pattern:**
- 1 direct answer sentence (≤25 words)
- 1–2 supporting detail sentences
- Then elaboration / evidence / examples

This structure makes the section extractable by LLMs as a citable answer block.

#### 4B — Intent-Specific Writing Patterns

The `intent_type` from the brief governs prose style and section structure:

| Intent | Pattern |
|---|---|
| `how-to` | Each H2 is a numbered step. First sentence = action instruction. Sub-steps under H3. |
| `listicle` | Each H2 is a list item with a bolded label. Consistent structure across items. |
| `informational` | Explanatory prose. Answer-first. Evidence or comparison where available. |
| `comparison` | Parallel structure. Each section addresses the same evaluative axis for each option. |
| `local-seo` | Informational base; service-context framing. Avoid city-specific claims (see guardrails). |
| `ecom` | Feature-benefit framing. Practical outcomes. Neutral, not promotional. |
| `informational-commercial` | Buyer-education tone. Compare options; do not endorse. |
| `news` | Recency-forward. Factual. Lead with the most important information. |

#### 4C — Term Injection

As each section is written, the module tracks term usage against the `usage_recommendations` from the SIE module. Terms are injected naturally — not bolded, not artificially repeated.

**Per-zone targets:**
- `h2` zone: aim for the SIE `target` count for that term in that zone
- `h3` zone: aim for the SIE `target` count
- `paragraphs` zone: aim for SIE `target`; hard cap at SIE `max`

**Avoid terms:** Any term in `sie.terms.avoid` must not appear anywhere in the article. The writing prompt includes the avoid list explicitly.

**Target keyword minimum usage:** Apply `sie.target_keyword.minimum_usage` floors per zone. If the SIE-computed usage range has a higher minimum than the floor, use the higher value.

#### 4D — Format Directives

| Directive | Enforcement |
|---|---|
| `require_bulleted_lists: true` | At least `min_lists_per_article` (default: 1) bulleted or numbered list must appear in content sections |
| `require_tables: true` | At least `min_tables_per_article` (default: 1) markdown table must appear in a content section |
| `answer_first_paragraphs: true` | See 4A above |

Lists and tables must be distributed across sections — not stacked in a single section to satisfy the minimum mechanically.

#### 4E — H3 Sub-Section Writing

H3 sections inherit the topic context of their parent H2. H3 prose is more specific and narrower in scope than the parent. If the H3 is tagged `source: "authority_gap_sme"`, the section must:
- Present information not typically found on competing SERP pages
- Avoid restating what was already said in the parent H2
- Be written in an expert, substantive register

Authority gap H3s may not use hedge language as a substitute for substance (e.g., "it depends" with no follow-up).

#### 4F — Citation Usage

For each H2 group being written, the module resolves the citation pool for that group and injects verified claims into the LLM writing prompt.

**Citation resolution:**
1. Look up `heading_structure[order].citation_ids` for the H2 heading and for any authority gap H3s in the group
2. Resolve each `citation_id` against `research.citations[]` to retrieve the full citation record
3. Filter to claims with `relevance_score ≥ 0.50`
4. Pass the resolved claims to the section writing LLM prompt as grounding material

**Fallback stub rule (critical):** If a citation's `extraction_method` is `fallback_stub`, the Writer **must not** use its `claim_text` as a specific factual assertion in prose. The citation URL and title may be referenced as a source acknowledgment (e.g., "according to [publication]…"), but no specific statistic or data point from the stub claim may appear in the article.

**Claim integration targets:**
- H2 sections with ≥1 associated citation and at least 1 non-stub verified claim: integrate at least 1 claim into prose as a grounded factual assertion with an inline hyperlink
- H2 sections with only fallback stub claims: reference the source as supporting context; do not assert specific figures
- H2 sections with `citation_ids: []` (no citations): write using general knowledge consistent with the heading intent; do not fabricate statistics

**Inline hyperlink format:**
- Links are placed in Markdown format: `[anchor text](URL)` using `citations[].url`
- Anchor text is drawn from a short paraphrase of the claim or the publication name — not the raw URL
- One inline link per citation per section; do not repeat the same URL multiple times in the same section

**Citation marking:**
After the section is written, record which `citation_id` values were woven into prose for that section. Each citation appearing in prose is marked `used: true`; all others remain `used: false` until Step 7.


---

### Step 5 — FAQ Section Writing

FAQs are written after all content sections. Each FAQ entry in `brief.faqs` becomes a question-answer pair.

**Structure:**
- FAQ section opens with an H2: the exact text from `heading_structure` where `type == "faq-header"` (always "Frequently Asked Questions" per brief spec)
- Each question is an H3
- Each answer is a direct prose paragraph: 40–80 words, answer-first, no preamble

**AEO optimization for FAQs:**
- Answers must be self-contained — a reader (or LLM) should be able to understand the answer without reading the rest of the article
- The seed keyword or its primary sub-phrase must appear in at least 2 FAQ answers
- Answers must not refer back to sections ("as mentioned above")
- Answers are the most citation-friendly content in the article — they must read as standalone facts

**FAQ term usage:** FAQ answers are excluded from the word budget but are not excluded from term coverage tracking. Terms appearing naturally in FAQ answers count toward zone totals.

---

### Step 6 — Conclusion Writing

The conclusion is the final content section. It is a structural block (`type: "conclusion"`) with no heading level per the brief spec.

**Rules:**
- 100–150 words
- Synthesizes the article's core takeaways in 2–3 sentences
- Ends with a soft, generic call-to-action appropriate to the intent type:
  - `how-to`: "Following these steps will…"
  - `informational`: "For more on [topic]…"
  - `local-seo`, `ecom`, `informational-commercial`: "When choosing a [service/product], consider…"
- Must not introduce new information not covered in the article
- The seed keyword must appear at least once in the conclusion

---


### Step 7 — Citation Usage Reconciliation

After all content sections, FAQs, and the conclusion are written, the module performs a final pass to reconcile citation usage across the full article.

**Process:**
1. Collect the set of `citation_id` values from all sections where a citation was marked used during Step 4F
2. Compare against the complete `research.citations[]` array
3. For each citation, determine:
   - `used`: whether the citation appeared in at least one section's prose
   - `sections_used_in`: ordered list of `heading_structure[].order` values for sections that used it
   - `inline_link_placed`: whether an inline hyperlink was placed for this citation in prose
4. Build the `citation_usage` block for the output schema

**Unused citation handling:**
Unused citations are not an error condition — not every citation may be naturally integrable into prose given word budgets and section focus. They are recorded as `used: false` for downstream analytics. No retry is triggered for unused citations.

**Metadata output:**
Record `citations_used` and `citations_unused` counts in the output `metadata` block.

---

## 7. Output Schema
```
{
  "keyword": "string",
  "intent_type": "informational | listicle | how-to | comparison | ecom | local-seo | news | informational-commercial",
  "title": "string",
  "article": [
    {
      "order": 0,
      "level": "H1 | H2 | H3 | none",
      "type": "content | faq-header | faq-question | conclusion | h1-enrichment",
      "heading": "string | null",
      "body": "string — Markdown (GitHub Flavored Markdown / CommonMark). May contain {{citation_id}} inline markers placed immediately after the closing punctuation of sentences containing cited claims. Markers conform to regex \\{\\{cit_[0-9]+\\}\\}. Markers are resolved into superscript references by the downstream Sources Cited Module.",
      "word_count": 0,
      "section_budget": 0,
      "citations_referenced": ["cit_001"]
    }
  ],
  "citation_usage": {
    "total_citations_available": 0,
    "citations_used": 0,
    "citations_unused": 0,
    "usage": [
      {
        "citation_id": "cit_001",
        "used": true,
        "sections_used_in": [2, 4],
        "marker_placed": true
      }
    ]
  },
  "format_compliance": {
    "lists_present": 0,
    "tables_present": 0,
    "lists_required": 0,
    "tables_required": 0,
    "answer_first_applied": true,
    "directives_satisfied": true
  },
  "metadata": {
    "total_word_count": 0,
    "word_budget": 2500,
    "faq_word_count": 0,
    "budget_utilization_pct": 0.0,
    "word_count_conflict": false,
    "no_required_terms": false,
    "section_count": 0,
    "faq_count": 0,
    "citations_used": 0,
    "citations_unused": 0,
    "no_citations": false,
    "retry_count": 0,
    "schema_version": "1.4",
    "brief_schema_version": "1.7",
    "generation_time_ms": 0
  }
}
```

---

## 8. Failure Mode Handling

| Scenario | Behavior |
|---|---|
| Either input JSON fails schema validation | Abort with structured error; do not generate partial output |
| `brief.keyword != sie.keyword` | Abort with structured error |
| LLM call for a section times out | Retry once; on second failure, insert placeholder: `"[SECTION GENERATION FAILED — MANUAL REVIEW REQUIRED]"` and flag in metadata |
| Title generation produces 0 valid candidates | Fall back to: `"{keyword} — A Complete Guide"` |
| Word budget exceeded after all sections | Trim the lowest-priority H3 sections (by `heading_priority` from brief) until budget is met; log trimmed sections |
| End-to-end exceeds 90s | Abort; return structured timeout error |
| `sie.terms.required` is empty | Continue without term injection; log `no_required_terms: true` |
| `research.citations` missing or empty | Continue in degraded mode; sections written without citation grounding; log `no_citations: true` |
| All claims for an H2 have `extraction_method: "fallback_stub"` | Write section without specific factual assertions from citations; reference source as context only; flag `all_stubs: true` on affected section |

---

## 9. AEO Optimization Requirements

Answer Engine Optimization governs how content is structured for LLM citation surfaces (ChatGPT, Claude, Gemini, Perplexity). These requirements are distinct from traditional on-page SEO and must be satisfied independently.

| Requirement | Implementation |
|---|---|
| Answer-first paragraphs | Every H2 section opens with a ≤25-word direct answer sentence before elaboration |
| Self-contained FAQ answers | FAQ answers must be standalone; no cross-references to article sections |
| Clean section boundaries | Each section's content must not bleed topically into adjacent sections |
| Factual density | Sections must contain verifiable facts, not filler padding |
| Hedge-free substance | Claims must be specific and supportable; vague hedges do not satisfy word budgets |
| Question-answer alignment | H2 headings framed as questions must be directly answered in the first sentence of that section |
| Entity presence | High-salience entities from the SIE module must appear in semantically appropriate sections — not forced into every paragraph |
| No promotional language | Avoid superlatives ("the best", "industry-leading") that reduce citation trustworthiness |

---

## 10. Performance Targets

| Stage | Target | Max |
|---|---|---|
| End-to-end article generation | 60s | 90s |
| Input validation + budget allocation | 2s | 5s |
| Title generation (3 candidates) | 5s | 10s |
| Section writing (all H2 groups, sequential) | 40s | 60s |
| FAQ + conclusion writing | 10s | 15s |
| Citation resolution + claim injection (per section, in-memory) | <1s | 2s |
| Step 7: Citation usage reconciliation | <1s | 2s |

Section writing is the dominant cost. Each H2 group (parent + H3 children) is a single LLM call. A brief with 6 H2s generates 6 sequential LLM calls for body content. Parallel section generation is not implemented in v1 due to term injection dependencies (earlier sections affect remaining term budget for later sections). Term usage audit and hallucination scanning are handled by a separate downstream module.

---

## 11. Cost Model

| Component | Cost per Article |
|---|---|
| Title generation LLM call | ~$0.01 |
| H1 enrichment LLM call | ~$0.005 |
| Section writing LLM calls (6 H2 groups avg) | ~$0.20–$0.35 |
| FAQ writing LLM call | ~$0.05 |
| Conclusion writing LLM call | ~$0.02 |
| **Estimated total per article** | **$0.28–$0.43** |
| **Budget ceiling** | **$0.75** |

Combined with upstream costs — Brief Generator ($0.19–$0.53), Research & Citations Module ($0.16–$0.28), and SIE cost (not specified in this PRD) — total per-article pipeline cost is estimated at **$0.63–$1.24** before margin. Term audit and hallucination scanning costs are accounted for in the downstream quality module.

---

## 12. Business Rules Summary

| Rule | Value |
|---|---|
| Locale | English / United States |
| Word budget | 2,500 words (content sections only; FAQ excluded) |
| Word budget tolerance | ±5% |
| Title must contain seed keyword | Yes |
| H1 text | Verbatim from `heading_structure`; no rewrite |
| H1 enrichment lede max words | 25 |
| Conclusion word range | 100–150 words |
| FAQ answer word range | 40–80 words |
| FAQ answers may cross-reference article sections | No |
| Answer-first paragraphs | Required for all H2 sections |
| Avoid terms enforcement | Hard block; flagged for downstream quality module |
| Sections trimmed when over budget | Lowest `heading_priority` H3s trimmed first |
| FAQ excluded from word budget | Yes |
| FAQ excluded from term zone tracking | No |
| Citation grounding required for H2s with verified claims | Yes — at least 1 non-stub claim per cited H2 section |
| Fallback stub claims used as factual assertions | Never |
| Body field output format | Markdown (GitHub Flavored Markdown / CommonMark) with `{{citation_id}}` inline markers at point of citation use |
| Citation marker format | `{{cit_id}}` — placed immediately after closing punctuation of sentence containing the cited claim; conforms to regex `\{\{cit_[0-9]+\}\}` |
| Multiple citations in one sentence | Markers stacked in claim-appearance order: `{{cit_001}}{{cit_004}}` (no spaces between markers) |
| Inline hyperlinks placed for used citations | No — markers only; citation formatting and linking handled by downstream Sources Cited Module |
| Markers permitted in heading fields | No — markers must only appear in `body` fields |
| Citation usage tracked per citation_id | Yes — `used`, `sections_used_in`, `marker_placed` in output |
| Unused citations trigger retry | No — recorded as unused; not an error condition |

---

## 13. What This PRD Does Not Cover

To be addressed in the engineering implementation spec:

- LLM model selection per call type (title, section writing, retry)
- Prompt templates and system prompts for each LLM call
- Lemmatizer selection for term audit (must match SIE module's implementation)
- Caching strategy for repeated brief + SIE input pairs
- Authentication and API key management
- Rate limiting and retry logic for LLM API calls
- Logging and observability (section-level timing, token counts, cost tracking)
- Output storage schema in Supabase
- Schema versioning compatibility with future brief schema versions
- Term usage audit, hallucination scanning, and human review workflows (handled by downstream quality module)
- Citation style formatting (APA, MLA, Chicago) — not required; inline Markdown hyperlinks only
- Citation link-rot detection post-publish (deferred to future monitoring module, per Research & Citations Module PRD)
- Downstream CMS or publishing integration

---

## 14. Version History

| Version | Date | Notes |
|---|---|---|
| 1.0 | 2026-04-29 | Initial draft |
| 1.1 | 2026-04-29 | Removed SAB-specific language; hallucination guardrails and problem statement generalized for any blog content vertical |
| 1.2 | 2026-04-29 | Removed title length and no-question rules; title now optimizes for SIE term/entity coverage. Min lists reduced to 1. Max paragraph words removed. Steps 7 (Term Usage Audit) and 8 (Hallucination Scan) moved to downstream quality module |
| 1.3 | 2026-04-29 | Integrated Research & Citations Module as upstream dependency. Inputs restructured to three independent payloads: Input A (Brief), Input B (Research), Input C (SIE). Added Step 4F (citation usage in section writing), Step 7 (citation usage reconciliation), `citation_usage` output block, `citations_referenced` per article section, fallback stub rules, inline hyperlink requirements, citation-related failure modes and business rules. Combined pipeline cost updated |
| 1.4 | 2026-04-30 | Added downstream Sources Cited Module as a new dependency; restructured citation output to support it. Replaced inline Markdown hyperlink placement with `{{citation_id}}` inline marker placement at the point of citation use (markers conform to regex `\{\{cit_[0-9]+\}\}` and are placed immediately after closing punctuation of the cited sentence). Removed all inline hyperlink logic from Step 4F; citation formatting and external linking are now sole responsibility of the downstream Sources Cited Module. Renamed `inline_link_placed` to `marker_placed` in `citation_usage` output. Declared `article[].body` field format as Markdown (GFM/CommonMark) with embedded marker tokens. Removed `citations[].url`, `title`, `author`, `publication`, and `published_date` from Writer's consumed fields list (they pass through downstream to the Sources Cited Module). Added explicit guardrail: markers are forbidden in heading fields. Added stacked-marker rule for multiple citations in a single sentence. Bumped output `schema_version` to `1.4`. |

---