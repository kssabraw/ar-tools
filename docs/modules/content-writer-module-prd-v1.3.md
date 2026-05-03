# PRD: Content Writer Module
**Version:** 1.7
**Status:** Draft
**Last Updated:** 2026-05-03
**Part of:** ShowUP Local — Content Generation Platform
**Upstream Dependencies:** SIE Term & Entity Module · Research & Citations Module (v1.1) · Content Brief Generator Module (v2.3)
**Downstream Dependency:** Sources Cited Module (v1.1)

> **v1.7 changes (2026-05-03):** Phase 4 of the article-quality defect fixes — addresses Defect 5 (unsourced operational claims) from the 2026-05-03 audit ("4-to-6 week refresh cadence" and "60-day affiliate audit window" stated as fact without adjacent citations).
>
> 1. **Step 4F.1 — Citable-Claim Detection** is implemented. Base patterns C1–C6 from the writer PRD (R7) plus three new operational-claim patterns:
>    - **C7 — Duration-as-recommendation**: `<numeric duration> <noun like 'cadence' / 'window' / 'cycle' / 'review' / 'audit' / 'refresh'>`. Catches the audited "4-to-6 week refresh cadence" / "60-day affiliate audit window" cases.
>    - **C8 — Frequency-as-recommendation**: `every <N> <unit>` and `(weekly|monthly|quarterly|biweekly|annually) <action noun>`.
>    - **C9 — Operational-percentage**: `<N>% rule/threshold/target/cap/floor/ceiling` and `aim for <N>%`.
> 2. **Per-H2 citation-coverage validator** runs after Step 6.7 (H2 body length) and before Step 7 (citation reconciliation). Per H2 section group, computes coverage = cited_claims / citable_claims. If below 50%, retries the section ONCE with a `COVERAGE_RETRY:` directive listing the uncited claims and asking the LLM to either add a `{{cit_N}}` marker from the available pool or rewrite the sentence to remove the specific claim.
> 3. **Auto-soften fallback for operational claims**. After the retry, any C7/C8/C9 claim that remains unsourced is deterministically softened via a small lookup table (e.g. "4-to-6 week refresh cadence" → "a typical refresh cadence (every few weeks)"). C1–C6 claims (statistics / years / source-attributed facts) are NEVER softened — softening would mangle the claim more than help it. Sections that still fail the threshold after retry + soften are accepted and recorded in `metadata.under_cited_sections`. Run never aborts.
> 4. **Schema bump** `1.6` → `1.7` (with accepted variants `1.7-no-context`, `1.7-degraded`). New metadata fields: `under_cited_sections`, `operational_claims_softened`, `citation_coverage_retries_attempted`, `citation_coverage_retries_succeeded`. Orchestrator's `EXPECTED_MODULE_VERSIONS["writer"]` and `WRITER_ACCEPTED_VERSIONS` bumped in lockstep.

> **v1.6 changes (2026-05-01):** Encoded Content Quality PRD v1.0 R3, R4, R5, R6, R7. v1.5 changes (`client_context` Input D, brand voice distillation, brand–SIE reconciliation, banned-term scan) remain in `/docs/writer-module-v1_5-change-spec_2.md` and are still authoritative for those features. Filename retains `-v1.3` suffix; canonical version is in this header.

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

**Topic-adherence anchor (added per Content Quality PRD v1.0 R3).**
After the title is selected, embed it with `text-embedding-3-small`. The title embedding is the "topic anchor" for the article. Every H2 from the brief is checked against this anchor immediately after Step 3 (Word Budget Allocation) and **before** Step 4 (Section Writing) begins:

- For each H2 in `brief.heading_structure`, compute `topic_adherence_score = cosine(h2.embedding, title_embedding)`. The H2 embeddings exist in the brief output from the brief's Step 5; if not present, embed the H2 text on the fly.
- H2s with `topic_adherence_score < 0.62` are dropped from the section-writing queue. Each dropped H2 is logged in writer metadata under `dropped_for_low_topic_adherence: [{order, heading, score}]` and added to a writer-side payload that the platform forwards back to the brief's `discarded_headings` with `discard_reason: "low_topic_adherence_in_writer"` so spin-off routing (Brief PRD v1.8 Step 9) can pick them up.
- Authority gap H3s (`source: "authority_gap_sme"`) are exempt from this check, but a parent H2 dropped for low adherence carries its authority gap H3s with it.
- If the dropped set leaves the article with fewer than 3 content H2s, the writer logs `low_h2_count_after_adherence_drop: true` and proceeds; this is not an abort condition.

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

### Step 2.5 — Intro Construction (Agree / Promise / Preview) — added per Content Quality PRD v1.0 R4

The intro is generated **after** the title and H1 enrichment but **before** Step 4 section writing, so the intro's preview block can be built from the post-adherence-filter H2 list.

**Inputs:**
- `output.title` (from Step 1)
- `brief.heading_structure` (post-adherence-filter list of H2s — see Step 1 topic-adherence anchor)
- `client_context.icp_text` (when available)

**Output:** A structured object with three discrete prose blocks:

```json
{
  "intro": {
    "agree": "string (≤ 50 words)",
    "promise": "string (≤ 50 words)",
    "preview": "string (≤ 50 words)"
  }
}
```

**Block semantics:**

| Block | Purpose | Constraints |
|---|---|---|
| **Agree** | A sentence acknowledging the reader's situation, question, or pain point. Anchored in `client_context.icp_text` when available; otherwise inferred from the title's question/topic. | One paragraph. ≤ 50 words. Must not name the brand. Must not begin with the seed keyword. |
| **Promise** | A sentence stating what the article will deliver to the reader. | One paragraph. ≤ 50 words. May reference the seed keyword once. Must not contain a CTA. |
| **Preview** | A sentence that enumerates 2–4 of the topics covered, drawn from the post-adherence-filter H2 list (not the original brief outline). | One paragraph. ≤ 50 words. Names topics in plain language; does not list bullets or H2 headings verbatim. |

**Banned-term enforcement:** All three blocks pass through the same regex banned-term scan as section bodies (Writer v1.5 §4.4).

**Failure handling:**
- LLM returns malformed JSON → retry once with a stricter prompt; on second failure, abort with structured error `intro_generation_failed`.
- Any single block exceeds 50 words → retry once with the over-length block named explicitly; on second failure, truncate the offending block at the last sentence boundary ≤ 50 words.

The intro is added to `article[]` as a single section after the H1 enrichment with `type: "intro"`, `level: "none"`, `heading: null`, and `body` formatted as the three blocks separated by blank lines (Markdown paragraph breaks).

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

#### 4E.1 — Paragraph Length Constraint (added per Content Quality PRD v1.0 R6)

Every section-writing prompt includes the directive:

> **Critical:** Every paragraph must contain at most 4 sentences. Three sentences or fewer is preferred. If a paragraph runs longer, split on a logical break.

This is the upstream half of R6; the downstream validation pass runs in Step 6.6.

`brief.format_directives.max_sentences_per_paragraph` (default `4`) carries the threshold so the value is brief-controlled. If the brief omits the field, the writer defaults to 4 and logs `max_sentences_per_paragraph_default_applied: true`.

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

#### 4F.1 — External-Citation Coverage on Citable Claims (added per Content Quality PRD v1.0 R7)

After each section is written, the writer runs a deterministic **citable-claim detection** pass on the section body:

A sentence is a citable claim if it matches any of:

| # | Pattern |
|---|---|
| C1 | A numeral followed by `%`, `percent`, `pct`, or `percentage points` |
| C2 | A numeral with currency symbol or USD/EUR/GBP suffix (e.g., `$100M`, `1.2 billion USD`) |
| C3 | A four-digit year between 1990 and 2099 used as a date (`in 2023`, `since 2024`) |
| C4 | `according to <ProperNoun>`, `<ProperNoun> reports`, `<ProperNoun> found`, `<ProperNoun> survey` |
| C5 | `studies show`, `research shows`, `data shows`, `analysts predict` |
| C6 | A sentence containing the name of an entity from `sie.terms.required[*]` where `is_entity == true` **and** a quantitative or temporal qualifier from C1–C3 |
| **C7** *(NEW v1.7)* | **Duration-as-recommendation**: a numeric duration (`day`/`week`/`month`/`year`/`hour`/`minute`) followed by a recommendation noun (`cadence`, `window`, `cycle`, `interval`, `period`, `review`, `audit`, `refresh`, `sprint`, `cooldown`, `lookback`, `horizon`, `grace period`, `onboarding`). Catches the audited "4-to-6 week refresh cadence" and "60-day affiliate audit window" cases. |
| **C8** *(NEW v1.7)* | **Frequency-as-recommendation**: `every <N> <unit>` (hours/days/weeks/months/quarters/years) OR `(hourly\|daily\|weekly\|biweekly\|monthly\|quarterly\|annually) <action>` (audit, review, refresh, check, update, inspection, sync, reconciliation, cleanup, standup). |
| **C9** *(NEW v1.7)* | **Operational-percentage**: `<N>% rule/threshold/target/cap/floor/ceiling/minimum/maximum/baseline/benchmark/cutoff` OR `aim for <N>%` OR `keep [it/under/below/above] <N>%`. |

**Coverage threshold:** At least **50%** of detected citable claims in a section must be followed by a `{{cit_id}}` marker. The threshold is per-section.

**First-party preference:** When the Research module produced multiple citation candidates for a claim, the writer prefers citations whose `domain` matches the entity named in the claim sentence. Existing v1.4+ citations carry `url`; the writer extracts the domain from `url` for matching.

**Below-threshold remediation:** A section that fails the 50% threshold triggers a one-shot retry with a stricter `COVERAGE_RETRY:` directive that names the uncited claim sentences and asks the LLM to either add a citation marker from the available pool or rewrite the sentence to remove the specific statistic / year / brand attribution.

**Auto-soften fallback for operational claims** *(NEW in v1.7 / Phase 4):* if the retry still falls below the threshold, a deterministic soften pass rewrites C7/C8/C9 phrases to hedge phrasing — but NOT C1-C6 (statistics / years / source-attributed facts where softening would mangle the claim).

| Pattern | Example before → after |
|---|---|
| C7 (duration) | `4-to-6 week refresh cadence` → `a typical refresh cadence (every few weeks)` |
| C7 (duration, day-scale) | `60-day affiliate audit window` → `a typical audit window (a brief window)` (or "couple of months" depending on duration scale) |
| C8 (frequency) | `weekly audit` → `a regular audit` |
| C8 (frequency, every-N) | `every 7 days` → `every few days` |
| C9 (operational %) | `5% rule` → `a small percentage rule` |
| C9 (aim for) | `aim for 30%` → `aim for a moderate share` |

The soften table is intentionally small in v1; entries are added as production data shows which patterns recur. After retry + soften, sections that still fall below the threshold are **accepted** and recorded in `metadata.under_cited_sections` for review. The run never aborts on coverage.

**Output additions to writer metadata** *(v1.7)*:

```json
{
  "under_cited_sections": [
    {
      "section_order": 4,
      "citable_claims": 5,
      "cited_claims": 1,
      "ratio": 0.2,
      "threshold": 0.5,
      "operational_claims_softened": 2
    }
  ],
  "operational_claims_softened": [
    {
      "section_order": 4,
      "h2_order": 4,
      "rule": "duration-as-recommendation",
      "original": "4-to-6 week refresh cadence",
      "softened": "a typical refresh cadence (every few weeks)"
    }
  ],
  "citation_coverage_retries_attempted": 1,
  "citation_coverage_retries_succeeded": 0
}
```

**Logging events** *(v1.7)*:

- `writer.coverage.complete` (INFO) — totals (groups inspected / retries / sections softened / under-cited remaining).
- `writer.coverage.retry` (INFO) — per-H2 trigger with citable / cited / ratio.
- `writer.coverage.retry_succeeded` (INFO) — retry cleared the floor.
- `writer.coverage.under_cited_after_retry` (WARN) — retry + soften didn't clear; section flagged.
- `writer.coverage.retry_failed` (WARN) — LLM call exception path.
- `writer.coverage.retry_section_count_mismatch` (WARN) — retry returned wrong number of sections (refused splice; Phase 3 fix #1 carry-over).

**FAQ rule:** FAQ answers are exempt from the 50% threshold. However, the same claim-detection pass runs on FAQ answers; any FAQ answer with a numeric statistic without a citation is **rewritten** to remove the statistic in favor of a qualitative phrasing (one-shot retry with explicit instruction). *(FAQ-specific path is specced but not yet wired in v1.7 — current implementation runs the validator over content H2 groups only; FAQ extension is a v1.x candidate.)*


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
- Conclusion prose must NOT contain the CTA — see Step 6.4 for required CTA placement
- Must not introduce new information not covered in the article
- The seed keyword must appear at least once in the conclusion

---

### Step 6.4 — Call-to-Action (CTA) — added per Content Quality PRD v1.0 R4

**Required.** Every article must end with a CTA. The CTA is a separate structural element rendered after the conclusion paragraph(s).

**Inputs:**
- `client_context.icp_text` (when available — used to source audience-specific next-step language)
- `brief.intent_type`
- `output.title` (so the CTA refers naturally to the article's promise)

**Rules:**
- Single sentence, ≤ 30 words.
- Must name a specific next action (read, download, contact, evaluate, compare, sign up, request, schedule, audit, review).
- Never a hard sales pitch ("Buy now", "Limited time only").
- When `client_context.icp_text` is provided, draw the next-step verb from the ICP's stated audience goals (e.g., "growth-focused marketing leaders evaluating new acquisition channels" → "evaluate how this fits your acquisition mix"). When unavailable, use a generic intent-appropriate template:
  - `how-to`: "Try these steps in your next [task] and measure the result."
  - `informational`: "Explore [related sub-topic] next."
  - `comparison`: "Run this comparison against your current [solution category] to see where the trade-offs land for your team."
  - `local-seo` / `ecom` / `informational-commercial`: "When you're ready to evaluate options, look for [criterion drawn from article]."
  - `news`: "Watch for follow-on coverage as the situation develops."

**Output placement:** Added to `article[]` as `{order, level: "none", type: "cta", heading: null, body: "<CTA sentence>"}` immediately after the conclusion section.

**Failure handling:**
- LLM produces > 30 words → retry once with the word limit named explicitly.
- Retry still over → truncate at the last word boundary ≤ 30 words and log `cta_truncated: true`.
- Retry produces a hard sales phrase (regex match against `\b(buy|purchase|order)\s+now\b|\blimited\s+time\b|\bact\s+today\b`) → retry with explicit "no hard sales language" guidance.

---

### Step 6.5 — Key Takeaways — added per Content Quality PRD v1.0 R4

**Required.** Generated **after** all content sections, FAQs, and the conclusion are written so it summarizes actual content rather than the outline.

**Inputs:**
- The full assembled article body (all H2 sections + FAQ answers + conclusion).
- `output.title` (anchor for relevance).

**Rules:**
- Single LLM call.
- Output: 3–5 standalone sentences, each ≤ 25 words.
- Each sentence must be self-contained (LLM citation surfaces extract individual sentences without surrounding context).
- Sentences are facts or actionable claims pulled from the article body — no opinion, no marketing language, no rhetorical questions.
- Sentences must not repeat each other (cosine similarity ≥ 0.85 between any pair triggers a regeneration of the offending pair).
- Brand mentions in Key Takeaways count toward the R5 brand-mention budget.

**Output placement:** Added to `article[]` immediately after the H1 enrichment (before the intro from Step 2.5) so the renderer surfaces it at the top of the page:

```
{order, level: "none", type: "key-takeaways", heading: "Key Takeaways", body: "- bullet\n- bullet\n- bullet"}
```

The renderer (frontend `sectionsToMarkdown`) recognizes `type: "key-takeaways"` and emits the heading as `## Key Takeaways`.

**Re-ordering after generation:** Because Key Takeaways is generated last but rendered second (after H1, before intro), the writer's article assembly performs a final re-ordering pass to insert the takeaways block in its display position before serializing the output.

**Failure handling:**
- LLM returns < 3 or > 5 sentences → retry once with the count constraint named explicitly; on second failure, accept what was returned within the 3–5 bounds (truncate to 5 if over, accept down to 3 if under, abort if < 3 with `key_takeaways_count_invalid`).
- Any single sentence > 25 words → retry once with the word limit named.
- Pair with cosine ≥ 0.85 → regenerate the offending pair only; on second similar failure, drop one and continue with 3–4 takeaways.

---

### Step 6.6 — Post-Generation Validation Pass — added per Content Quality PRD v1.0 R6

After all sections, FAQs, conclusion, CTA, and Key Takeaways are written but **before** the citation reconciliation in Step 7 and the existing v1.5 banned-term scan, run a **paragraph length validation** pass over every body field in `article[]`:

1. Split each `body` on blank lines (Markdown paragraph boundaries).
2. For each paragraph, count sentence-terminal punctuation (`.`, `?`, `!`) outside Markdown link/code spans. Use an abbreviation dictionary to skip false positives: `e.g.`, `i.e.`, `etc.`, `Mr.`, `Dr.`, `vs.`, `Inc.`, `U.S.`, `U.K.`.
3. If any paragraph has > `max_sentences_per_paragraph` (default 4), mark the section for retry.

**Per-section retry rules:**
- One retry per section, with a prompt addendum that names the over-length paragraph and the limit.
- If the retry is also over budget, accept the section but flag in writer metadata: `paragraph_length_violations: [{section_order, paragraph_index, sentence_count}]`.

The validation pass also scans the Key Takeaways bullets — any single bullet > 25 words triggers a one-time retry of Key Takeaways generation with a strict word limit reminder.

---

### Step 6.7 — Per-H2 Body Length Validator — added per Phase 3 (Brief PRD v2.3)

**Purpose:** Catch H2 sections shipping with empty/lightweight bodies (the audited "an H2 followed by two sentences and a stat before jumping to the next H2" case). The brief generator stamps a per-intent floor on `format_directives.min_h2_body_words`; this validator enforces it.

**Position in the pipeline:** runs **after** Step 6.6 paragraph length validation and the heading-level banned-term scan, **before** Step 7 citation reconciliation.

**Algorithm:** For each H2 SECTION GROUP (parent H2 + child H3 bodies):

1. Compute `group_word_count` = sum of word counts across the group, after stripping `{{cit_N}}` markers.
2. If `group_word_count >= format_directives.min_h2_body_words`: pass.
3. Otherwise: re-run `write_h2_group` ONCE with a length-retry directive that names the floor and the current word count, and asks for additional substance (not padding).
4. After the retry:
   - If now ≥ floor: succeeded, replace the original sections.
   - If still under: accept whichever attempt has more words and append `{section_order, word_count, floor}` to `metadata.under_length_h2_sections`.

**Failure-mode policy** (matches Step 6.6 R6 convention):
- Never aborts the run. Empty H2 sections are recoverable in post-edit; aborting the whole article on a length miss is worse.
- Retry uses a single LLM call per offending H2.
- If the retry call itself raises, the H2 is flagged as under-length and the original output is preserved.

**Floor table** (from `intent_format_template.h2_pattern`):

| Pattern | Floor | Intent |
|---|---|---|
| `sequential_steps` | 120 | how-to |
| `ranked_items` | 80 | listicle |
| `parallel_axes` | 150 | comparison |
| `topic_questions` | 180 | informational |
| `buyer_education_axes` | 180 | informational-commercial |
| `feature_benefit` | 150 | ecom |
| `place_bound_topics` | 150 | local-seo |
| `news_lede` | 100 | news |

**Output additions to writer metadata:**

```json
{
  "under_length_h2_sections": [
    {"section_order": 4, "word_count": 47, "floor": 120}
  ],
  "h2_body_length_retries_attempted": 2,
  "h2_body_length_retries_succeeded": 1
}
```

**Logging:**
- `writer.h2_length.complete` (INFO) — totals (groups inspected / retries attempted / retries succeeded / under-length after retry).
- `writer.h2_length.retry` (INFO) — per-H2 trigger with current word count + floor.
- `writer.h2_length.retry_succeeded` (INFO) — per-H2 success with before/after.
- `writer.h2_length.retry_still_under` (WARN) — per-H2 retry didn't clear the floor.
- `writer.h2_length.retry_failed` (WARN) — LLM call exception path.

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
      "type": "content | faq-header | faq-question | conclusion | h1-enrichment | key-takeaways | intro | cta",
      "heading": "string | null",
      "body": "string — Markdown (GitHub Flavored Markdown / CommonMark). May contain {{citation_id}} inline markers placed immediately after the closing punctuation of sentences containing cited claims. Markers conform to regex \\{\\{cit_[0-9]+\\}\\}. Markers are resolved into superscript references by the downstream Sources Cited Module.",
      "word_count": 0,
      "section_budget": 0,
      "citations_referenced": ["cit_001"]
    }
  ],
  "key_takeaways": ["string (≤ 25 words each, 3–5 items)"],
  "intro": {
    "agree": "string (≤ 50 words)",
    "promise": "string (≤ 50 words)",
    "preview": "string (≤ 50 words)"
  },
  "cta": "string (≤ 30 words)",
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
    "dropped_for_low_topic_adherence": [
      {"order": 0, "heading": "string", "score": 0.0}
    ],
    "low_h2_count_after_adherence_drop": false,
    "paragraph_length_violations": [
      {"section_order": 0, "paragraph_index": 0, "sentence_count": 0}
    ],
    "under_cited_sections": [
      {"section_order": 0, "citable_claims": 0, "cited_claims": 0}
    ],
    "topic_brand_alignment": "brand_aligned | brand_agnostic",
    "brand_mention_count": 0,
    "brand_mention_flags": [
      "zero_brand_mentions_on_brand_aligned_topic | brand_mentions_exceed_target | brand_mentions_exceed_hard_cap"
    ],
    "max_sentences_per_paragraph_default_applied": false,
    "cta_truncated": false,
    "schema_version": "1.6",
    "brief_schema_version": "1.8",
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
| Final article missing any of `key-takeaways`, `intro`, `cta` sections (R4) | Abort with structured error `missing_required_structure` and `missing_elements: [...]`. No partial output returned. |
| `intro` block exceeds 50 words after retry | Truncate at the last sentence boundary ≤ 50 words and accept |
| `cta` exceeds 30 words after retry | Truncate at the last word boundary ≤ 30 words; flag `cta_truncated: true` |
| `key_takeaways` count outside 3–5 after retry | Abort with `key_takeaways_count_invalid` if count < 3; truncate to 5 if count > 5 |
| Section fails R7 50% citation coverage after one retry | Accept section and flag in `under_cited_sections` |
| Section fails R6 paragraph-length cap after one retry | Accept section and flag in `paragraph_length_violations` |
| Brand mentions ≥ 6 (R5 hard cap) after one retry on the highest-mention section | Accept output; flag `brand_mentions_exceed_hard_cap`. Do not block publishing. |
| < 3 H2s remain after Step 1 topic-adherence drop (R3) | Continue and log `low_h2_count_after_adherence_drop: true`. Not an abort. |

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
| Required structural elements (R4) | `key-takeaways` (3–5 items, ≤ 25 words each), `intro` (Agree/Promise/Preview, each ≤ 50 words), `cta` (≤ 30 words). All three required; missing any → abort with `missing_required_structure` |
| H2 topic-adherence threshold (R3) | `cosine(h2.embedding, title.embedding) ≥ 0.62` required; below threshold → drop and route to spin-offs |
| Paragraph length cap (R6) | 4 sentences per paragraph (default `format_directives.max_sentences_per_paragraph`); over-budget paragraphs trigger one retry, then accept and flag |
| External citation coverage on citable claims (R7) | ≥ 50% of detected citable claims per section must carry a `{{cit_id}}` marker; below threshold → one retry, then accept and flag |
| Brand mention budget (R5) | 2–3 mentions target; 0 + brand-aligned topic → flag (no reject); 4–5 → log warning; ≥ 6 → one retry then accept |
| Brand-aligned vs. brand-agnostic determination (R5) | `cosine(title.embedding, brand_voice_card.client_services_joined.embedding) ≥ 0.55` → `brand_aligned`; otherwise `brand_agnostic` |

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
| 1.5 | 2026-04-30 | See `/docs/writer-module-v1_5-change-spec_2.md`. Added `client_context` Input D, brand voice distillation (Step 3.5a), brand–SIE term reconciliation (Step 3.5b), brand voice injection into Steps 4–6, post-hoc regex-based banned-term scan (§4.4), `brand_voice_card_used`, `brand_conflict_log[]`, and `client_context_summary` outputs. |
| 1.6 | 2026-05-01 | Encoded Content Quality PRD v1.0 R3, R4, R5, R6, R7. Added: topic-adherence anchor after Step 1 (drops H2s with `cosine ≤ 0.62` to title and routes them to brief spin-offs); intro construction in Step 2.5 with discrete Agree/Promise/Preview blocks; paragraph-length directive in Step 4E.1; citable-claim detection and 50% coverage threshold with one-shot remediation in Step 4F.1; explicit CTA in Step 6.4 (now a separate structural element, removed from conclusion prose); Key Takeaways generation in Step 6.5 (3–5 items, ≤ 25 words each); paragraph-length validation pass in Step 6.6 (default 4 sentences); brand-mention budget enforcement (2–3 target, 0 on brand-aligned topic flagged, ≥ 6 retry-then-accept); new `article[]` types `key-takeaways`, `intro`, `cta`; new metadata fields `dropped_for_low_topic_adherence`, `paragraph_length_violations`, `under_cited_sections`, `topic_brand_alignment`, `brand_mention_count`, `brand_mention_flags`, `cta_truncated`. Bumped `schema_version` to `1.6`; consumed `brief_schema_version` to `1.8`. |
| **1.7** | **2026-05-03** | **Phase 4 of the article-quality defect fixes (proposal accepted 2026-05-03). Addresses Defect 5 — unsourced operational claims. Step 4F.1 citable-claim detection is implemented with base patterns C1-C6 plus three NEW operational-claim patterns: **C7** (duration-as-recommendation: `<numeric duration> + <cadence/window/cycle/review/audit/refresh/sprint/cooldown/lookback/horizon/grace period/onboarding>`), **C8** (frequency-as-recommendation: `every <N> <unit>` and `(weekly\|monthly\|quarterly\|biweekly\|annually) + <action>`), **C9** (operational-percentage: `<N>% rule/threshold/target/cap/floor/ceiling` and `aim for <N>%` and `keep [...]<N>%`). Per-H2 citation-coverage validator runs after Step 6.7 and before Step 7. Coverage = cited_claims / citable_claims. Below 50% triggers ONE retry with a `COVERAGE_RETRY:` directive. After retry, any unresolved C7/C8/C9 claim is deterministically softened via a small lookup table ("4-to-6 week refresh cadence" → "a typical refresh cadence (every few weeks)", "60-day affiliate audit window" → "a typical audit window", "weekly audit" → "a regular audit", "5% rule" → "a small percentage rule", "aim for 30%" → "aim for a moderate share"). C1-C6 claims are NEVER softened. Sections still under threshold are accepted and surfaced in `metadata.under_cited_sections`. Run never aborts. New metadata fields: `under_cited_sections`, `operational_claims_softened`, `citation_coverage_retries_attempted`, `citation_coverage_retries_succeeded`. Schema bump `1.6` → `1.7` (with accepted variants `1.7-no-context`, `1.7-degraded`). Orchestrator `EXPECTED_MODULE_VERSIONS["writer"]` and `WRITER_ACCEPTED_VERSIONS` bumped in lockstep. Cost impact: 0–N additional LLM calls for coverage retries (~$0.01-0.03 each, only fires when coverage < 50%). Steady-state expected ≤ 1/run.** |

---