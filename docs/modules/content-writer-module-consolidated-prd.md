# PRD: Content Writer Module (Consolidated, Self-Contained)

**Canonical Version:** 1.7 (with v1.5 brand-context and v1.6 structural additions merged inline)
**Status:** Implementation-ready
**Locale:** English / United States only
**Pipeline Role:** Final generation module in the Blog Writer pipeline. Consumes Brief, Research & Citations, SIE, and Client Context. Produces a publication-ready Markdown article plus a structured JSON article object for the downstream Sources Cited module.

> This document is a self-contained build spec. A reader with no prior context should be able to implement the module from this PRD alone. It consolidates: v1.3 baseline + v1.4 citation marker contract + v1.5 brand-voice/client-context handling + v1.6 H1 sourcing, intro structure, title-case pass, multi-format serialization + v1.7 citable-claim coverage with operational-claim softening. Where a feature was introduced in a specific version, the version is noted; the rule itself is current.

---

## 1. Problem & Scope

### 1.1 Problem

The upstream pipeline (Brief Generator + SIE + Research & Citations) produces a fully researched, structured plan for a blog post — heading architecture, FAQ questions, required terms, entity recommendations, format directives, and a set of verified, source-anchored claims mapped to every content section. That plan has no value until it becomes actual prose. Manual execution drifts from the approved heading structure, ignores term targets, violates word budgets, buries answers under preamble, and introduces fabricated statistics.

The Content Writer converts the upstream brief, term intelligence, verified citation pool, and per-client brand voice into a complete, publication-ready blog post that is optimized for both Google search ranking and LLM citation (Answer Engine Optimization / AEO). Citations do the sourcing work so the writer does not invent statistics.

### 1.2 Goals

- Accept four structured inputs (Brief, Research, SIE, Client Context) and produce a complete article.
- Generate a title; emit H1 verbatim from the brief; write every content section from the brief's heading structure.
- Honor word budget, format directives, heading hierarchy, and term usage targets from upstream — the writer does not reinterpret the brief.
- Produce content structured for LLM citation: answer-first paragraphs, direct question answers, clean section boundaries, schema-compatible FAQ.
- Ground factual assertions in verified claims from Research; treat fallback-stub claims as source references only.
- Track per-citation usage and emit a structured article (`article[]`), plus Markdown and HTML serializations for downstream publishing.
- Enforce per-client brand voice (tone, voice directives, banned terms, preferred terms) over SIE recommendations; brand always wins.
- Enforce content-quality guardrails: topic adherence, paragraph length cap, citable-claim coverage, structural elements (Key Takeaways / Agree-Promise-Preview intro / CTA), brand-mention budget.

### 1.3 Out of Scope (v1)

- Keyword research / brief generation (upstream)
- Internal linking suggestions
- Image selection / alt-text generation
- Meta description generation
- Schema markup injection (JSON-LD)
- CMS publishing or API push (Sources Cited + platform Publish module handle delivery)
- Multi-locale support
- Rank tracking, citation link-rot monitoring
- Human review workflows / editorial routing
- Rewriting prior runs — each run is independent

---

## 2. Inputs

Four upstream JSON payloads on each run. All required except `client_context`, which is optional with documented fallbacks.

### 2.1 Input A — Brief Generator output

Authoritative source for heading structure, word budget, format directives, FAQs, and (since Brief v2.0) the article title.

| Field | Usage |
|---|---|
| `keyword` | Seed keyword. Cross-validated against Research and SIE; mismatch aborts run. |
| `title` | **H1 text — used verbatim. No LLM regeneration.** (Added Brief v2.0 / Writer v1.6.) |
| `intent_type` | One of: `informational`, `listicle`, `how-to`, `comparison`, `ecom`, `local-seo`, `news`, `informational-commercial`. Governs tone, section patterns, CTA template. |
| `scope_statement` | Constrains the article's promise (used in intro construction). |
| `heading_structure[]` | Ordered list of `{order, level: "H1"\|"H2"\|"H3", text, type, source?, citation_ids[]?, embedding?}`. Writer emits these in order. |
| `heading_structure[].type` | `content`, `faq-header`, `faq-question`, `conclusion`. |
| `heading_structure[].source` | Optional. `authority_gap_sme` H3s get a budget multiplier and stricter quality bar. |
| `heading_structure[].citation_ids` | Citation ids mapped to each heading. |
| `faqs[]` | Ordered FAQ `{question, faq_score}`. Count must be 3–5. |
| `format_directives` | `require_bulleted_lists`, `require_tables`, `min_lists_per_article` (default 1), `min_tables_per_article` (default 1), `answer_first_paragraphs` (default true), `max_sentences_per_paragraph` (default 4), `min_h2_body_words` (intent-specific floor — see §5.10). |
| `metadata.word_budget` | 2,500 words across content sections; FAQ excluded. |
| `metadata.h2_count`, `metadata.h3_count` | Budget-per-section math. |

### 2.2 Input B — Research & Citations output

Verified citation pool mapped to brief headings.

| Field | Usage |
|---|---|
| `keyword` | Cross-validated against brief. Mismatch aborts. |
| `citations[]` | Verified citations. |
| `citations[].citation_id` | Must match regex `^cit_[0-9]+$`. Used in `{{cit_N}}` markers placed in prose. |
| `citations[].claims[]` | `{claim_text, relevance_score, extraction_method, verification_method}`. |
| `citations[].extraction_method` | `verbatim_extraction` or `fallback_stub`. **Stubs may not be used for specific factual assertions** — only as source-attribution context. |
| `citations[].url`, `.title`, `.author`, `.publication`, `.published_date` | **Not consumed by Writer**; passed through to downstream Sources Cited module. |

`research.citations` absent or empty → continue in degraded mode (`no_citations: true`); sections written without citation grounding. Not an abort.

### 2.3 Input C — SIE Term & Entity output

| Field | Usage |
|---|---|
| `keyword` | Cross-validated against brief. Mismatch aborts. |
| `terms.required[]` | Terms the writer must incorporate. |
| `usage_recommendations[]` | Per-zone usage ranges (min/target/max) per term. Writer targets `target`, hard-caps at `max`. |
| `target_keyword.minimum_usage` | Per-zone occurrence floors for the seed keyword. |
| `terms.avoid[]` | Terms the writer must not use (hard block; subject to brand-override — see §4.2). |
| `word_count.target` | Cross-validated against `brief.metadata.word_budget`; >20% divergence flags `word_count_conflict`. Brief wins. |
| `entities[]` (merged into `terms`) | `entity_category`, `example_context`, `ner_variants` — used to enrich the H1 lede and high-value sections. |

### 2.4 Input D — Client Context (optional; per-client brand voice)

Added in v1.5. Omitted → fall back to v1.4 behavior; `schema_version_effective: "1.6-no-context"`.

```json
{
  "client_context": {
    "brand_guide_text": "string (max 150,000 chars; JSON, Markdown, or extracted text from PDF/DOCX)",
    "icp_text":         "string (max 150,000 chars; same format rules)",
    "website_analysis": {
      "services":   ["string"],
      "locations":  ["string"],
      "tone":       ["string (3–5 adjectives — NOT used; see below)"],
      "positioning":"string (≤50 words — NOT used; see below)"
    },
    "website_analysis_unavailable": false
  }
}
```

**Website analysis provides factual reference data ONLY** (services, locations, contact info). Tone and positioning signals come exclusively from `brand_guide_text` and `icp_text`. The `website_analysis.tone` and `.positioning` fields are accepted on the wire for forward compatibility but ignored by distillation.

### 2.5 Cross-validation (runs before any LLM call)

| Check | On failure |
|---|---|
| `brief.keyword == research.keyword` (case-insensitive) | Abort `keyword_mismatch` |
| `brief.keyword == sie.keyword` (case-insensitive) | Abort `keyword_mismatch` |
| `sie.word_count.target` within ±20% of `brief.metadata.word_budget` | Flag `word_count_conflict: true`; proceed using brief as authoritative |
| `brief.heading_structure` non-empty and ordered | Abort if empty; warn on `order` gaps |
| `brief.faqs` count 3–5 | Abort outside range |
| `research.citations` missing/empty | Continue; log `no_citations: true` |
| `brief.title` present and non-empty | Abort `brief_missing_title` if missing (legacy fallback path exists — see §5.2.4) |
| `client_context` present but malformed | Abort `client_context_validation_error` |

---

## 3. System Architecture

```
[Brief + Research + SIE + Client Context]
        │
        ▼
  Step 0: Input Validation + Cross-Validation
        │
        ▼
  Step 1: Title Generation  ───►  embed(title) = topic anchor
        │
        ▼
  Step 2: H1 (verbatim from brief.title) + Enrichment Lede
        │
        ▼
  Step 2.5: Intro Construction (Agree / Promise / Preview)
        │
        ▼
  Step 3: Word Budget Allocation
        │
  Step 3.5a: Brand Voice Distillation   ┐
  Step 3.5b: Brand–SIE Reconciliation   ┘  (run in parallel)
        │
        ▼
  Step 3.6: Brand & ICP Placement Plan (deterministic anchors)
        │
        ▼
  Step 3.7: Topic-Adherence Filter (drop H2s with cosine < 0.62 to title)
        │
        ▼
  Step 4: Section Writing (sequential per H2 group)
          ├── 4A Answer-first paragraphs
          ├── 4B Intent-specific patterns
          ├── 4C Term injection (filtered SIE + target keyword floors)
          ├── 4D Format directives (lists, tables)
          ├── 4E H3 sub-section writing (incl. authority-gap H3s)
          ├── 4E.1 Paragraph-length directive
          ├── 4F Citation marker placement
          └── 4F.1 Citable-claim coverage validator (per-section, post-write)
        │
        ▼
  Step 5: FAQ Section Writing
        │
        ▼
  Step 6: Conclusion Writing
  Step 6.4: CTA (separate structural element after conclusion)
  Step 6.5: Key Takeaways (generated last, rendered second)
  Step 6.6: Paragraph-length post-validation
  Step 6.7: Per-H2 body length validation
  Step 6.8: ICP Callout LLM judge
        │
        ▼
  Step 7: Citation Usage Reconciliation
        │
        ▼
  Step 8: Banned-Term Regex Scan
  Step 9: Defense-in-Depth Title-Case Pass on headings
  Step 10: Markdown + HTML Serialization
        │
        ▼
  [JSON output: article[] + article_markdown + article_html + metadata]
```

---

## 4. Locked Design Decisions

These are settled — do not relitigate without explicit user approval.

| # | Decision | Rationale |
|---|---|---|
| D1 | Brand voice card is regenerated per run from current `client_context_snapshots`. Not cached on the client record. Persisted in run output as `brand_voice_card_used`. | No cache invalidation when brand guides change; past runs reflect the snapshot at run time. |
| D2 | Banned-term detection in generated output is regex-based: case-insensitive, word-boundary, alternation over `brand_voice_card.banned_terms`. | Deterministic, cheap, debuggable. LLM-based paraphrase detection is a future-version candidate. |
| D3 | **Brand always wins** in all term conflicts. Brand-banned > SIE-Required (term excluded). Brand-preferred > SIE-Avoid (term used). No exceptions. | Brand compliance is non-negotiable; SIE is SERP-derived intelligence, not a client mandate. |
| D4 | Brand guide / ICP accepted as JSON, Markdown, or extracted text. Distillation LLM handles all formats natively. | Preserve structure when present; do not flatten unnecessarily. |
| D5 | Website analysis is factual reference only (services, locations, contact info). Tone and positioning come exclusively from `brand_guide_text` + `icp_text`. | Clean separation between factual ground truth and declared brand voice. |
| D6 | H1 text is `brief.title` verbatim. No LLM call regenerates the H1. | Brief generator v2.0.3 already title-cases and validates; Writer trusts upstream. |
| D7 | The article ships with three required structural elements: Key Takeaways, Agree/Promise/Preview intro, CTA. Missing any → abort with `missing_required_structure`. | These are the AEO/quality contract; partial output is worse than no output. |
| D8 | Section writing is sequential, not parallel. Earlier sections affect remaining term budget for later sections. | Term injection has order-dependent state. |
| D9 | Citation markers are tokens (`{{cit_N}}`) placed in `body` only. Markers in headings → abort. Sources Cited module owns rendering. | Single source of truth for citation formatting. |

---

## 5. Functional Requirements

### 5.0 Step 0 — Input Validation

Runs before any LLM call. Covers the §2.5 cross-validation table plus:

| Rule | Action |
|---|---|
| Any required input payload missing | Abort `missing_input` |
| `sie.terms.required` empty | Continue; log `no_required_terms: true` |
| `brief.metadata.word_budget` missing | Default 2,500; log warning |

### 5.1 Step 1 — Title Generation

**Inputs:** `brief.keyword`, `brief.intent_type`, SIE Required terms + entities (sorted by `recommendation_score`).

**Rules:**
- Title must contain the seed keyword.
- Title must incorporate as many high-scoring SIE Required terms / entities as fit naturally. Keyword and entity coverage takes priority over brevity.
- Tone by intent:
  - `how-to` → "How to …" or "How [Audience] Can …"
  - `listicle` → leads with a number ("7 Reasons …")
  - `comparison` → includes "vs." or "or"
  - `informational` / `local-seo` / `ecom` / `informational-commercial` / `news` → declarative, value-led
- LLM generates 3 candidates; deterministic selection picks highest combined keyword + entity coverage.
- Stored in `output.title`. Not injected into `heading_structure`.

**Topic anchor (v1.6 / Content Quality R3):** After selection, embed the title with `text-embedding-3-small`. This embedding is the topic anchor used by §5.4 (topic-adherence filter).

**Failure:** 0 valid candidates → fallback: `"{keyword} — A Complete Guide"`.

### 5.2 Step 2 — H1 + Enrichment Lede

#### 5.2.1 H1 sourcing (v1.6)

```
article_h1.text = brief.title   # verbatim, exact string equality, no LLM call
```

No LLM path produces the H1 in v1.6+. Any prior keyword-only generator is removed.

#### 5.2.2 Enrichment lede

A sub-head / lede sentence immediately following H1, providing topical context before the first body section.

- 1 sentence, ≤25 words.
- Must include ≥1 entity with `entity_category ∈ {services, equipment, problems, methods}`.
- Must not be a full restatement of the title.

#### 5.2.3 H1 failure modes

| Scenario | Behavior |
|---|---|
| `brief.title` missing/empty | Abort `brief_missing_title` |
| `brief.title` >120 chars | Accept; log warning (length is brief's concern) |
| `brief.title` contains banned term | Abort `banned_term_leakage` (no rewrite — upstream regression must surface) |

#### 5.2.4 Legacy fallback

For replay tests on pre-v2.0 briefs without `title`: log `brief_legacy_no_title`, regenerate H1 from `keyword + intent` (v1.5 LLM path), report `schema_version_effective: "1.6-legacy-h1"`. Not used in production.

### 5.3 Step 2.5 — Intro Construction (Agree / Promise / Preview)

Generated **after** title/H1 but **before** Step 4, so the preview can reference the post-adherence-filter H2 list (§5.4).

**Output:** structured object with three discrete prose blocks, **assembled into a single paragraph** for emission.

```json
{
  "intro": {
    "agree":   "string (≤ 50 words)",
    "promise": "string (≤ 50 words)",
    "preview": "string (≤ 50 words)"
  }
}
```

| Beat | Purpose | Constraints |
|---|---|---|
| Agree | Names the reader's situation in their own language. Anchored in `client_context.icp_text` when available; otherwise inferred from title topic. | ≤50 words. Must not name the brand. Must not begin with the seed keyword. |
| Promise | States what the article will deliver. Anchored in `brief.title` and `brief.scope_statement`. | ≤50 words. May reference the seed keyword once. No CTA. |
| Preview | Names 2–4 (or first 3–5) topics covered, in `heading_structure` order, from the post-adherence-filter H2 list. | ≤50 words. Plain language; no bullets; does not verbatim list H2 headings. |

**Combined-paragraph rule (v1.6):** Total intro is **one paragraph, 60–150 words**. No `\n\n` breaks. No heading markers, no list markers.

**Banned-term enforcement:** Same regex scan as section bodies (§5.16).

**Prompt directive (verbatim text to include):**

> Write the article's introduction as a single paragraph (60–150 words) in three beats:
> 1. **Agree** — name the reader's situation in their own words (1–2 sentences).
> 2. **Promise** — state what this article will deliver, anchored in the title and the article's stated scope (1 sentence).
> 3. **Preview** — name the first 3–5 H2 sections the reader will encounter, in order (1–2 sentences).
> Do not break the paragraph. Do not include headings, bullets, or numbered lists. Do not introduce out-of-scope topics.

**Validation (post-LLM):**

| Check | On failure |
|---|---|
| `60 ≤ len(text.split()) ≤ 150` | Retry once specifying actual count + direction. Then accept + log warning. |
| `"\n\n" not in text.strip()` | Retry once. Then deterministically collapse `\n+` → single space. |
| No heading markers (`(?m)^\s*#{1,6}\s`) | Retry once. Then strip matched lines. |
| Per-beat ≤50 words | Retry once naming the over-length block; then truncate at last sentence boundary ≤50 words. |
| Malformed JSON twice in a row | Abort `intro_generation_failed`. |
| Banned-term match | Per §5.16: body-level rule (retry once; abort on second failure). |

**Placement in `article[]`:** Single item with `type: "intro"`, `level: "none"`, `heading: null`, `body` = the joined paragraph. Inserted after H1 enrichment.

### 5.4 Step 3 — Word Budget Allocation + Topic-Adherence Filter

#### 5.4.1 Budget formula

```
body_budget       = word_budget − conclusion_budget        ≈ 2,375 of 2,500
per_group_budget  = body_budget / h2_group_count

for each H2 group (parent H2 + child H3s):
  weight(parent_H2)            = 1.0
  weight(H3)                   = 1.0  if regular
                               = 1.2  if source == "authority_gap_sme"
  section_budget(s) = per_group_budget × weight(s) / Σ weights_in_group
```

- Each H2 *group* (parent + children) gets an equal body-budget share so groups without H3s aren't starved.
- Authority-gap H3s reallocate **within** their group (taking from parent), not across groups.
- `how-to` / `listicle` allocate equal budget per step/item (no adjustment).
- Conclusion: fixed 100–150 words.
- Floor: every section ≥50 words.

Output: `section_budget` map keyed by heading `order`.

#### 5.4.2 Topic-adherence filter (Content Quality R3)

Runs immediately after budget allocation, before Step 4 begins.

- For each H2 in `brief.heading_structure`: `topic_adherence_score = cosine(h2.embedding, title_embedding)`. Use brief's H2 embeddings if present; otherwise embed on the fly with `text-embedding-3-small`.
- Drop H2s with `topic_adherence_score < 0.62` from the section-writing queue.
- Each dropped H2 logged in `metadata.dropped_for_low_topic_adherence: [{order, heading, score}]`. Writer also emits a payload that the platform forwards to the brief's `discarded_headings` with `discard_reason: "low_topic_adherence_in_writer"` so spin-off routing can pick them up.
- Authority-gap H3s (`source: "authority_gap_sme"`) are exempt from this check, but a parent H2 dropped for low adherence carries its authority-gap H3s with it.
- If `<3` content H2s remain after the drop, log `low_h2_count_after_adherence_drop: true` and proceed. Not an abort.

### 5.5 Step 3.5a — Brand Voice Distillation

Runs in parallel with Step 3.5b after inputs validate. Both must complete before Step 4.

Single LLM call (same model as section writing). Input: `brand_guide_text` + `icp_text` + `website_analysis` (if available).

**Output (Brand Voice Card):**

```json
{
  "brand_voice_card": {
    "tone_adjectives":      ["string"],
    "voice_directives":     ["string (max 200 chars each, max 8 items)"],
    "audience_summary":     "string (≤300 chars)",
    "audience_pain_points": ["string (max 5 items)"],
    "audience_goals":       ["string (max 5 items)"],
    "audience_verticals":   ["string (max 5 items)"],
    "preferred_terms":      ["string (max 20 items)"],
    "banned_terms":         ["string (max 30 items)"],
    "discouraged_terms":    ["string (max 20 items)"],
    "brand_name":           "string or null",
    "client_services":      ["string (max 15 items, from website_analysis.services)"],
    "client_locations":     ["string (max 15 items, from website_analysis.locations)"],
    "client_contact_info":  {"phone": "...", "email": "...", "address": "...", "hours": "..."}
  }
}
```

**Distillation rules:**

- Tone adjectives come from `brand_guide_text` only. Never supplement from `website_analysis`.
- A term is `banned` only when explicitly prohibited. `discouraged` when expressed against without explicit prohibition. `preferred` when explicitly named as preferred phrasing.
- ICP summarized from `icp_text` into `audience_summary` + distinct `audience_pain_points` + `audience_goals` + `audience_verticals`.
- `client_services`, `client_locations`, `client_contact_info` carried verbatim from `website_analysis` when available.
- **Categorization only** — never invent banned/discouraged/preferred terms; the LLM may only extract and paraphrase content present in the input.
- Both JSON and Markdown brand guides are handled natively. PDF/DOCX uploads arrive as extracted text and are treated as Markdown for extraction purposes.

**Failure handling:**

| Scenario | Behavior |
|---|---|
| Malformed JSON | One retry stricter prompt; second failure → abort `brand_distillation_failed` |
| All-empty card | Continue; log warning; sections proceed without brand shaping |
| `brand_guide_text` empty | Skip brand portion; populate only ICP/website-derived fields |
| `icp_text` empty | Skip ICP portion; populate only brand/website-derived fields |
| Both empty AND `website_analysis_unavailable: true` | Fall back to v1.4 behavior; `schema_version_effective: "1.6-degraded"` |

### 5.6 Step 3.5b — Brand–SIE Term Reconciliation

Runs in parallel with 3.5a. Consumes `brand_guide_text` directly (not the distilled card — needs full nuance to detect conflicts) plus SIE Required and Avoid lists.

Single LLM call. Output: per-term classification.

**For each SIE-Required term:**

| Classification | Trigger | Section behavior |
|---|---|---|
| `keep` | No brand conflict | Use at SIE `target` zone usage |
| `exclude_due_to_brand_conflict` | Brand explicitly bans the term | Term must not appear anywhere |
| `reduce_due_to_brand_preference` | Brand discourages without explicit ban | Use at SIE `min` instead of `target`; max becomes `target` |

**For each SIE-Avoid term:**

| Classification | Trigger | Section behavior |
|---|---|---|
| `keep_avoiding` | No brand preference | Continue avoiding |
| `use_due_to_brand_preference` | Brand explicitly prefers the term | Use despite SIE; log in `brand_conflict_log` as `brand_preference_overrides_sie_avoid` |

**Brand always wins (D3).**

**Internal output** (passed to Step 4):

```json
{
  "filtered_sie_terms": {
    "required": [
      {
        "term": "string",
        "zone_usage_target": int,
        "zone_usage_min":    int,
        "zone_usage_max":    int,
        "effective_target":  int,
        "effective_max":     int,
        "reconciliation_action": "keep | reduce_due_to_brand_preference"
      }
    ],
    "excluded": [
      {"term": "string", "original_classification": "required", "reason": "exclude_due_to_brand_conflict"}
    ],
    "avoid": ["string"]
  }
}
```

**Hallucination guard:** reconciliation LLM must include `brand_guide_reasoning` (≤300 chars) for every non-`keep` classification citing the specific brand-guide text. Classifications not grounded in source text → discarded with a warning.

**Failure:** malformed JSON twice → abort `brand_reconciliation_failed`. Empty output → treat all as `keep`. `brand_guide_text` empty → skip reconciliation; emit empty `brand_conflict_log`.

### 5.7 Step 3.6 — Brand & ICP Placement Plan (deterministic)

Pre-allocates which body H2 sections must carry (a) the brand mention and (b) the ICP callout. Prevents "every section assumes the other will carry it" failure.

No LLM call. Token-set scoring.

- `brand_anchor_order` — the H2 whose heading text shares the most tokens with any `client_services` entry. Tie-break: lowest `order`. Falls back to the first content H2 when no overlap exists.
- `icp_anchor_order` — the H2 whose heading text shares the most tokens with any `audience_pain_points` or `audience_verticals` entry. If tied with `brand_anchor_order`, picks the next-best for variety. Falls back to the first content H2 ≠ brand anchor.
- `icp_hook_phrase` — the specific pain-point / vertical that scored highest, so the section prompt can ground its callout concretely.

Tokenization: lowercased, alphanumeric, stopword-filtered. Token-set intersection (size), not Jaccard.

**Section prompt directives:**

| Directive | Applied to | Effect |
|---|---|---|
| `must_mention_brand: true` | brand anchor H2 | Section MUST mention the brand exactly once, anchored to evidence |
| `must_not_mention_brand: true` | every non-anchor body H2 | Section MUST NOT mention the brand |
| `icp_callout_hook: <phrase>` | ICP anchor H2 | Section MUST surface the named pain point / vertical as an explicit callout |

**Bypass:** when `brand_voice_card` is `None`, `brand_name` empty, or no audience signals exist, the relevant directives are not stamped; sections fall back to the soft v1.4 default.

**Metadata surface:** `brand_anchor_h2_order`, `icp_anchor_h2_order`, `icp_hook_phrase`.

### 5.8 Step 4 — Section Writing

Sequential, one LLM call per H2 group (parent H2 + its H3s). Order follows `heading_structure[].order`.

#### 5.8.1 — 4A Answer-First Paragraphs (default; AEO primary mechanism)

When `format_directives.answer_first_paragraphs == true` (default):

Every H2 section opens with a direct answer sentence before elaborating. If the heading is "How Long Does Water Heater Repair Take?", the first sentence must answer that question in plain terms.

Pattern:
- 1 direct answer sentence (≤25 words)
- 1–2 supporting detail sentences
- Then elaboration / evidence / examples

#### 5.8.2 — 4B Intent-Specific Patterns

| Intent | Pattern |
|---|---|
| `how-to` | Each H2 is a numbered step. First sentence = action instruction. Sub-steps under H3. |
| `listicle` | Each H2 is a list item with bolded label. Consistent structure across items. |
| `informational` | Explanatory prose. Answer-first. Evidence / comparison where available. |
| `comparison` | Parallel structure. Each section addresses the same evaluative axis for each option. |
| `local-seo` | Informational base; service-context framing. Avoid city-specific claims unless cited. |
| `ecom` | Feature-benefit framing. Practical outcomes. Neutral, not promotional. |
| `informational-commercial` | Buyer-education tone. Compare options; do not endorse. |
| `news` | Recency-forward. Factual. Lead with most important information. |

#### 5.8.3 — 4C Term Injection

Track usage against SIE `usage_recommendations` (per-zone min/target/max). Terms injected naturally — not bolded, not artificially repeated.

- `h2` zone: aim for SIE `target` count for that term in that zone.
- `h3` zone: aim for SIE `target`.
- `paragraphs` zone: aim for SIE `target`; hard cap at SIE `max`.

`filtered_sie_terms.excluded` (from Step 3.5b): treated as banned for this article — listed explicitly in the prompt as "do not use, brand conflict".

`filtered_sie_terms.avoid`: must not appear anywhere.

Apply `sie.target_keyword.minimum_usage` floors per zone. If SIE-computed range has a higher minimum than the floor, use the higher.

#### 5.8.4 — 4D Format Directives

| Directive | Enforcement |
|---|---|
| `require_bulleted_lists: true` | At least `min_lists_per_article` (default 1) bulleted or numbered list across content sections |
| `require_tables: true` | At least `min_tables_per_article` (default 1) markdown table across content sections |
| `answer_first_paragraphs: true` | See 4A |

Lists and tables must be **distributed** — not stacked into a single section.

#### 5.8.5 — 4E H3 Sub-Section Writing

H3s inherit parent H2 topic context. Prose is more specific, narrower in scope.

For `source: "authority_gap_sme"`:
- Present information not typically on competing SERP pages.
- Avoid restating parent H2.
- Expert, substantive register.
- May NOT use hedge language ("it depends") as a substitute for substance.

#### 5.8.6 — 4E.1 Paragraph-Length Directive (Content Quality R6)

Every section prompt includes:

> **Critical:** Every paragraph must contain at most 4 sentences. Three sentences or fewer is preferred. If a paragraph runs longer, split on a logical break.

The 4-sentence threshold is brief-controlled via `brief.format_directives.max_sentences_per_paragraph` (default 4). When missing, log `max_sentences_per_paragraph_default_applied: true`.

Validation happens post-write in §5.13.

#### 5.8.7 — 4F Citation Marker Placement

Per H2 group:

1. Look up `heading_structure[order].citation_ids` for the H2 and any authority-gap H3s in the group.
2. Resolve each `citation_id` against `research.citations[]`.
3. Filter claims to `relevance_score ≥ 0.50`.
4. Pass resolved claims to the section prompt as grounding material.

**Fallback-stub rule (critical):** If a citation's `extraction_method == "fallback_stub"`, the writer must NOT use its `claim_text` as a specific factual assertion. The citation may be referenced as "according to [publication]…" context, but no specific statistic / data point from the stub may appear in prose.

**Claim integration targets:**

- H2 with ≥1 non-stub verified claim: integrate ≥1 claim into prose as a grounded factual assertion, followed by `{{cit_N}}` marker.
- H2 with only stub claims: reference source as context; no specific figures.
- H2 with `citation_ids: []`: write from general knowledge; do not fabricate statistics.

**Marker syntax (D9):**

- Format: `{{cit_N}}` matching regex `\{\{cit_[0-9]+\}\}`.
- Placed immediately after the closing punctuation of the sentence containing the cited claim. Example: `Demand climbed 18% in Q3.{{cit_007}}`
- Multiple citations in one sentence: stacked in claim-appearance order, no spaces: `{{cit_001}}{{cit_004}}`
- Markers FORBIDDEN in heading fields. Match in any heading → abort `marker_in_heading`.
- The Writer does NOT emit inline Markdown links. The downstream Sources Cited module resolves markers into superscript references + bibliography.

Record per-section: which `citation_id` values appeared in prose (`marker_placed: true`). All others remain `marker_placed: false` until Step 7.

#### 5.8.8 — 4F.1 Citable-Claim Coverage (Content Quality R7, v1.7)

After each H2 group is written, run a deterministic **citable-claim detection** pass on the section body.

A sentence is a citable claim if it matches any of:

| # | Pattern |
|---|---|
| C1 | Numeral followed by `%`, `percent`, `pct`, or `percentage points` |
| C2 | Numeral with currency symbol or USD/EUR/GBP suffix (e.g., `$100M`, `1.2 billion USD`) |
| C3 | Four-digit year 1990–2099 used as a date (`in 2023`, `since 2024`) |
| C4 | `according to <ProperNoun>`, `<ProperNoun> reports`, `<ProperNoun> found`, `<ProperNoun> survey` |
| C5 | `studies show`, `research shows`, `data shows`, `analysts predict` |
| C6 | Sentence containing the name of an entity from `sie.terms.required[*]` where `is_entity == true` AND a quantitative or temporal qualifier from C1–C3 |
| **C7** | **Duration-as-recommendation:** numeric duration (`day`/`week`/`month`/`year`/`hour`/`minute`) followed by a recommendation noun (`cadence`, `window`, `cycle`, `interval`, `period`, `review`, `audit`, `refresh`, `sprint`, `cooldown`, `lookback`, `horizon`, `grace period`, `onboarding`). Example: `"4-to-6 week refresh cadence"`. |
| **C8** | **Frequency-as-recommendation:** `every <N> <unit>` (hours/days/weeks/months/quarters/years) OR `(hourly\|daily\|weekly\|biweekly\|monthly\|quarterly\|annually) <action>` (audit, review, refresh, check, update, inspection, sync, reconciliation, cleanup, standup). |
| **C9** | **Operational-percentage:** `<N>% rule/threshold/target/cap/floor/ceiling/minimum/maximum/baseline/benchmark/cutoff` OR `aim for <N>%` OR `keep [it/under/below/above] <N>%`. |

**Coverage threshold:** ≥50% of detected citable claims per section must be followed by a `{{cit_N}}` marker.

**First-party preference:** when Research produced multiple candidates for a claim, prefer citations whose `domain` (extracted from `url`) matches the entity named in the claim.

**Below-threshold remediation:** one-shot retry with a `COVERAGE_RETRY:` directive naming the uncited claim sentences and asking the LLM to either add a marker from the available pool or rewrite the sentence to remove the specific statistic / year / brand attribution.

**Auto-soften fallback for operational claims (v1.7):** if the retry still fails, a deterministic soften pass rewrites C7/C8/C9 phrases to hedge phrasing — but **NOT C1–C6**, where softening would mangle the claim more than help it.

| Pattern | Example before → after |
|---|---|
| C7 (duration) | `4-to-6 week refresh cadence` → `a typical refresh cadence (every few weeks)` |
| C7 (duration, day-scale) | `60-day affiliate audit window` → `a typical audit window (a brief window)` |
| C8 (frequency, named) | `weekly audit` → `a regular audit` |
| C8 (frequency, every-N) | `every 7 days` → `every few days` |
| C9 (operational %) | `5% rule` → `a small percentage rule` |
| C9 (aim for) | `aim for 30%` → `aim for a moderate share` |

Sections still below threshold after retry + soften are **accepted** and recorded in `metadata.under_cited_sections`. Run never aborts on coverage.

**FAQ rule:** FAQ answers are exempt from the 50% threshold. However, the same claim-detection runs on FAQ answers — any FAQ answer with a numeric statistic without a citation is rewritten (one-shot retry) to remove the statistic in favor of qualitative phrasing.

**Logging events:**

| Event | Level | Trigger |
|---|---|---|
| `writer.coverage.complete` | INFO | Totals (groups inspected / retries / soften count / under-cited remaining) |
| `writer.coverage.retry` | INFO | Per-H2 trigger (citable / cited / ratio) |
| `writer.coverage.retry_succeeded` | INFO | Retry cleared the floor |
| `writer.coverage.under_cited_after_retry` | WARN | Retry + soften didn't clear |
| `writer.coverage.retry_failed` | WARN | LLM call exception |
| `writer.coverage.retry_section_count_mismatch` | WARN | Retry returned wrong number of sections; refused splice |

### 5.9 Step 5 — FAQ Section Writing

After all content sections.

**Structure:**
- FAQ section opens with an H2: exact text from `heading_structure` where `type == "faq-header"` (always "Frequently Asked Questions" per brief spec).
- Each question is an H3.
- Each answer is a direct prose paragraph: 40–80 words, answer-first, no preamble.

**AEO rules:**
- Answers must be self-contained — readable without surrounding article context.
- Seed keyword or its primary sub-phrase must appear in ≥2 FAQ answers.
- Answers must NOT refer back to article sections ("as mentioned above").
- Answers are the most citation-friendly content — must read as standalone facts.

**FAQ + brand:**
- Receives Audience block (`audience_summary` + `audience_pain_points` + `audience_goals`).
- Receives Brand Voice block (`tone_adjectives` + first 3 `voice_directives`).
- Receives `filtered_sie_terms.required`.
- FAQ questions must reflect ICP phrasing patterns, not generic SEO templates.
- Answers respect tone and banned-terms identically to section writing.

**FAQ term tracking:** FAQ excluded from word budget. NOT excluded from term zone tracking — natural occurrences count toward zone totals.

### 5.10 Step 6 — Conclusion

Final content section. `type: "conclusion"`, no heading level per brief spec.

**Rules:**
- 100–150 words.
- Synthesizes core takeaways in 2–3 sentences.
- Conclusion prose must NOT contain the CTA — see §5.11 for separate CTA element.
- Must not introduce new information.
- Seed keyword must appear at least once.
- Receives full Brand Voice block + `audience_summary` + Client Context block (when website analysis available).
- May include a natural closing sentence referencing client services / location where contextually relevant. Never a hard sales CTA.

### 5.11 Step 6.4 — CTA (separate structural element)

Required. Rendered after the conclusion paragraph(s).

**Inputs:** `client_context.icp_text` (when available), `brief.intent_type`, `output.title`.

**Rules:**
- Single sentence, ≤30 words.
- Must name a specific next action (read, download, contact, evaluate, compare, sign up, request, schedule, audit, review).
- Never a hard sales pitch.
- Regex block: `\b(buy|purchase|order)\s+now\b|\blimited\s+time\b|\bact\s+today\b`.

**ICP-driven verb:** when `icp_text` provided, draw next-step verb from stated audience goals. Otherwise use intent-appropriate template:

| Intent | Template |
|---|---|
| `how-to` | "Try these steps in your next [task] and measure the result." |
| `informational` | "Explore [related sub-topic] next." |
| `comparison` | "Run this comparison against your current [solution category] to see where the trade-offs land for your team." |
| `local-seo` / `ecom` / `informational-commercial` | "When you're ready to evaluate options, look for [criterion drawn from article]." |
| `news` | "Watch for follow-on coverage as the situation develops." |

**Output placement:** Added to `article[]` as `{order, level: "none", type: "cta", heading: null, body: "<CTA sentence>"}` immediately after the conclusion.

**Failure:**

| Scenario | Behavior |
|---|---|
| >30 words | Retry once naming the limit. |
| Still >30 | Truncate at last word boundary ≤30; flag `cta_truncated: true`. |
| Hard sales phrase regex match | Retry once with explicit "no hard sales language" guidance. |

### 5.12 Step 6.5 — Key Takeaways

Generated **after** all sections, FAQs, and conclusion are written so it summarizes actual content rather than the outline.

**Inputs:** the full assembled article body + `output.title`.

**Rules:**
- Single LLM call.
- 3–5 standalone sentences, each ≤25 words.
- Each sentence is self-contained (LLM citation surfaces extract individual sentences).
- Facts or actionable claims only — no opinion, no marketing language, no rhetorical questions.
- Sentences must not repeat: cosine similarity ≥0.85 between any pair triggers regeneration of the offending pair.
- Brand mentions in Key Takeaways count toward the brand-mention budget.

**Output placement:** Added to `article[]` immediately after the H1 enrichment (before the intro) so the renderer surfaces it at the top of the page:

```
{order, level: "none", type: "key-takeaways", heading: "Key Takeaways", body: "- bullet\n- bullet\n- bullet"}
```

The frontend renderer recognizes `type: "key-takeaways"` and emits `## Key Takeaways`.

**Re-ordering pass:** Because Key Takeaways is generated last but rendered second, the assembly performs a final re-ordering pass to insert the takeaways block in its display position before serialization.

**Failure:**

| Scenario | Behavior |
|---|---|
| Count <3 or >5 after retry | Truncate to 5 if over; accept down to 3 if under; abort `key_takeaways_count_invalid` if <3 |
| Any sentence >25 words after retry | Retry once with limit named |
| Pair cosine ≥0.85 after retry | Drop one; continue with 3–4 takeaways |

### 5.13 Step 6.6 — Paragraph-Length Validation (Content Quality R6)

Runs after all sections + FAQs + conclusion + CTA + Key Takeaways, BEFORE Step 7 citation reconciliation and the banned-term scan.

Per `body` field in `article[]`:

1. Split each body on blank lines (Markdown paragraph boundaries).
2. For each paragraph, count sentence-terminal punctuation (`.`, `?`, `!`) outside Markdown link/code spans. Abbreviation dictionary to skip false positives: `e.g.`, `i.e.`, `etc.`, `Mr.`, `Dr.`, `vs.`, `Inc.`, `U.S.`, `U.K.`.
3. If any paragraph > `max_sentences_per_paragraph` (default 4), mark for retry.

**Per-section retry:**
- One retry per section, addendum naming the over-length paragraph and limit.
- Still over → accept; flag `paragraph_length_violations: [{section_order, paragraph_index, sentence_count}]`.

Also scans Key Takeaways bullets — any bullet >25 words → one retry of Key Takeaways generation with strict word limit.

### 5.14 Step 6.7 — Per-H2 Body Length Validator

Catches H2s shipping with empty/lightweight bodies.

Runs **after** §5.13 and the heading-level banned-term scan, **before** §5.15 citation reconciliation.

**Algorithm:** for each H2 section group (parent H2 + child H3 bodies):

1. `group_word_count = sum(word_count(body) for body in group)` after stripping `{{cit_N}}` markers.
2. If `group_word_count >= format_directives.min_h2_body_words`: pass.
3. Otherwise: re-run `write_h2_group` ONCE with a length-retry directive naming the floor and current count, asking for additional substance (not padding).
4. After retry:
   - ≥floor: success, replace original.
   - Still under: accept whichever attempt has more words; append `{section_order, word_count, floor}` to `metadata.under_length_h2_sections`.

Never aborts. Retry uses a single LLM call per offending H2. Retry exception → flag and preserve original.

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

**Logging:** `writer.h2_length.complete` (INFO), `writer.h2_length.retry` (INFO), `writer.h2_length.retry_succeeded` (INFO), `writer.h2_length.retry_still_under` (WARN), `writer.h2_length.retry_failed` (WARN).

### 5.15 Step 6.8 — ICP Callout LLM Judge

Runs after the article is fully assembled and citation reconciliation runs. Verifies the ICP-anchor section (Step 3.6) actually surfaced the callout. A regex / substring check would generate false negatives when the LLM paraphrases the hook ("margin erosion from refunds" → "shrinking unit economics on returned orders"); the judge tolerates paraphrase.

**Position:** after format-compliance computation, before metadata construction. Matches the anchor section by heading text in the post-resequence `article` (pre-resequence `order` no longer meaningful here).

**Inputs:** anchor section's body (truncated to 4,000 chars), ICP hook phrase, brand voice card's `audience_pain_points` + `audience_verticals` for close-synonym recognition.

**Output (JSON):** `icp_callout_landed` (bool), `evidence` (≤200-char verbatim quote when landed), `reasoning` (one-sentence justification).

**Failure-mode policy:**
- Never aborts.
- LLM failure / malformed → `icp_callout_landed = None`. Returning False would falsely flag the run.
- No ICP anchor assigned → skip, `None`.
- Anchor heading not found in `article` → `False` with `anchor_not_in_article`.
- Empty anchor body → `False` with `empty_body`, no LLM call.

**Cost discipline:** at most one LLM call per article, only when an ICP anchor was assigned, 256-token output cap, 4,000-char input cap.

**Metadata surface:** `icp_callout_landed`, `icp_callout_evidence`, `icp_callout_judge_status`.

### 5.16 Step 7 — Citation Usage Reconciliation

After all content is written.

1. Collect the set of `citation_id` values that received markers across all sections.
2. Compare against the complete `research.citations[]`.
3. For each citation, determine:
   - `used`: appeared in ≥1 section's prose.
   - `sections_used_in`: ordered list of `heading_structure[].order` values.
   - `marker_placed`: whether a marker was placed.
4. Build the `citation_usage` block.

**Unused citations are not an error.** Recorded as `used: false`. No retry. (Not every citation may naturally integrate given word budgets and section focus.)

**Metadata output:** `citations_used` and `citations_unused` counts.

### 5.17 Step 8 — Banned-Term Regex Scan (v1.5)

Runs after Step 7, before serialization. Regex-based per Decision D2.

#### 5.17.1 Construction

```python
import re

banned_terms = brand_voice_card["banned_terms"]
if banned_terms:
    pattern = r"\b(?:" + "|".join(re.escape(t) for t in banned_terms) + r")\b"
    banned_regex = re.compile(pattern, re.IGNORECASE)
else:
    banned_regex = None
```

#### 5.17.2 Scan targets

Each field independently: H1, every H2, every H3, every section `body`, intro, conclusion, CTA, Key Takeaways body, each FAQ question, each FAQ answer. Citation marker tokens `{{cit_N}}` cannot contain banned-term text by construction; ignored.

#### 5.17.3 Match behavior

| Match Location | Severity | Behavior |
|---|---|---|
| Any heading (H1/H2/H3) | **Critical** | Abort `banned_term_leakage` immediately. No retry. Surface term + heading text. |
| Body section, intro, conclusion, CTA, FAQ answer, Key Takeaways body | **Recoverable** | Retry that unit once with stricter prompt naming the banned term. If still matches → abort `banned_term_leakage`. |
| FAQ question | **Recoverable** | Same retry-once policy. |

#### 5.17.4 Documented limitations

- Hyphen-variant: `"high-quality"` does not match `"high quality"` (no hyphen). Documented.
- Multi-word phrases match as literal phrases with outer word boundaries; `"cutting-edge"` and `"cuttingedge"` do not match `"cutting edge"`.
- Substring guard: word-boundary regex prevents `"art"` matching inside `"smart"`.
- Possessives / plurals: `"premium"` matches `"premium's"` and `"premiums"` because `\b` treats punctuation as separators. Accepted for v1.
- Case variations handled by `re.IGNORECASE`.

#### 5.17.5 Reporting

Successful retry → original leakage logged in structured logs; not surfaced to user. Abort → `banned_term_leakage` with offending term + field + snippet.

### 5.18 Step 9 — Title-Case Normalization (defense-in-depth, v1.6)

Runs immediately before serialization, after the banned-term pass.

```python
from titlecase import titlecase

_TITLE_CASE_LEVELS = {"H1", "H2", "H3"}
_TITLE_CASE_TYPES  = {"content", "faq-header", "conclusion", "title"}

def apply_title_case(article_items):
    for item in article_items:
        if item.level in _TITLE_CASE_LEVELS and item.type in _TITLE_CASE_TYPES:
            item.text = titlecase(item.text)
    return article_items
```

Pin **`titlecase==2.4.1`** to match the brief generator.

**Idempotency:** `titlecase(titlecase(x)) == titlecase(x)`. Safe to apply unconditionally.

**Exclusions:** FAQ questions (`type == "faq-question"` — sentence case is correct), intro/conclusion body, CTA body, Key Takeaways bullets, section bodies, citation markers.

**Validation (non-production assert; production log-as-warning):**

```python
assert titlecase(item.text) == item.text
# Failure → log "title_case_round_trip_failed", emit heading anyway.
```

### 5.19 Step 10 — Markdown + HTML Serialization (v1.6)

Two flat string serializations emitted alongside `article[]`. Deterministic, no LLM calls.

#### 5.19.1 New top-level output fields

| Field | Type | Purpose |
|---|---|---|
| `article_markdown` | string | GitHub-flavored Markdown with `[^N]` footnote citations. Suitable for Markdown editors, the platform's article preview, GitHub renders, the platform Publish module's Google Doc Apps Script webhook. |
| `article_html` | string | Semantic HTML5 fragment (no `<html>`, `<head>`, `<body>`, no inline styles) with `<sup><a href="#cite-N">` citations and ordered Sources list. Suitable for direct paste into WordPress code/HTML block, Google Docs visual paste, or CMS embed. |

Always present when `article[]` non-empty. Populated on legacy / no-context / degraded paths.

#### 5.19.2 Markdown rules

| `article[]` Item | Markdown |
|---|---|
| `level == "H1"` | `# {text}\n\n` |
| `level == "H2"`, `type == "content"` | `## {text}\n\n` |
| `level == "H3"`, `type == "content"` | `### {text}\n\n` |
| `level == "H2"`, `type == "faq-header"` | `## {text}\n\n` |
| `level == "H2"`, `type == "conclusion"` | `## {text}\n\n` |
| Intro / section body / CTA / Key Takeaways body | `{text}\n\n` |
| FAQ question | `### {text}\n\n` |
| FAQ answer | `{text}\n\n` |
| Citation marker `{{cit_N}}` inline | `[^N]` (GitHub footnote reference) |
| Sources Cited section | `## Sources\n\n[^1]: {title} — {url}\n[^2]: ...` |

Strip trailing whitespace. End with a single `\n`.

#### 5.19.3 HTML rules

| `article[]` Item | HTML |
|---|---|
| `level == "H1"` | `<h1>{text}</h1>` |
| `level == "H2"` (any `type`) | `<h2>{text}</h2>` |
| `level == "H3"` (any `type`) | `<h3>{text}</h3>` |
| Intro / section body / CTA | `<p>{text}</p>` |
| FAQ question | `<h3>{text}</h3>` |
| FAQ answer | `<p>{text}</p>` |
| Citation marker `{{cit_N}}` inline | `<sup><a href="#cite-N">N</a></sup>` |
| Sources Cited section | `<h2>Sources</h2><ol><li id="cite-1"><a href="{url}">{title}</a></li>...</ol>` |

Constraints:
- HTML-escape all text content (`&`, `<`, `>`, `"`, `'`) before insertion. Markers escaped *after* substitution.
- Fragment only — no doctype / wrapping tags / meta.
- No inline `style` attributes; no class names.
- Items joined with `\n` (one element per line) for readability.
- Anchor targets live on `<li>` inside Sources `<ol>` — in-document anchors may not survive paste into Docs / WP visual editor; superscript numerals remain readable.

#### 5.19.4 Determinism & idempotency

- Pure functions of `(article[], citations[])`.
- Do NOT mutate inputs.
- Re-parsing Markdown / HTML output and tag-stripping must recover the same plain-text body content.

#### 5.19.5 Serializer failure handling

| Scenario | Behavior |
|---|---|
| `article[]` empty | `article_markdown = ""`, `article_html = ""`. No abort. |
| Marker references unknown citation id | Emit verbatim (`{{cit_N}}` in MD, `<span>{{cit_N}}</span>` in HTML). Log `serializer_unknown_citation`. No abort. |
| Body contains literal `<` / `>` / `**` | Markdown: pass through (already-Markdown content rendered as-is). HTML: escape entire paragraph (body LLM is not authorized to emit HTML). |
| Sources Cited didn't run / missing | Omit Sources section in both formats. Markers still render to `[^N]` / `<sup>` form. |

---

## 6. Output Schema

```json
{
  "keyword":     "string",
  "intent_type": "informational | listicle | how-to | comparison | ecom | local-seo | news | informational-commercial",
  "title":       "string",
  "article": [
    {
      "order":               0,
      "level":               "H1 | H2 | H3 | none",
      "type":                "content | faq-header | faq-question | conclusion | h1-enrichment | key-takeaways | intro | cta | title",
      "heading":             "string | null",
      "body":                "string (GFM/CommonMark Markdown with {{cit_N}} markers immediately after closing punctuation of cited sentences; markers conform to regex \\{\\{cit_[0-9]+\\}\\})",
      "word_count":          0,
      "section_budget":      0,
      "citations_referenced":["cit_001"]
    }
  ],
  "article_markdown": "string (GFM serialization with [^N] footnotes)",
  "article_html":     "string (semantic HTML5 fragment with <sup><a href=\"#cite-N\">)",
  "key_takeaways":    ["string (≤ 25 words each, 3–5 items)"],
  "intro": {
    "agree":   "string (≤ 50 words)",
    "promise": "string (≤ 50 words)",
    "preview": "string (≤ 50 words)"
  },
  "cta": "string (≤ 30 words)",

  "citation_usage": {
    "total_citations_available": 0,
    "citations_used":            0,
    "citations_unused":          0,
    "usage": [
      {"citation_id": "cit_001", "used": true, "sections_used_in": [2, 4], "marker_placed": true}
    ]
  },

  "format_compliance": {
    "lists_present":         0,
    "tables_present":        0,
    "lists_required":        0,
    "tables_required":       0,
    "answer_first_applied":  true,
    "directives_satisfied":  true
  },

  "brand_voice_card_used": {
    "tone_adjectives":      ["..."],
    "voice_directives":     ["..."],
    "audience_summary":     "...",
    "audience_pain_points": ["..."],
    "audience_goals":       ["..."],
    "audience_verticals":   ["..."],
    "preferred_terms":      ["..."],
    "banned_terms":         ["..."],
    "discouraged_terms":    ["..."],
    "brand_name":           "string or null",
    "client_services":      ["..."],
    "client_locations":     ["..."],
    "client_contact_info":  {"phone": "...", "email": "...", "address": "...", "hours": "..."}
  },

  "brand_conflict_log": [
    {
      "term":                  "string",
      "sie_classification":    "required | avoid",
      "resolution":            "exclude_due_to_brand_conflict | reduce_due_to_brand_preference | brand_preference_overrides_sie_avoid",
      "brand_guide_reasoning": "string (≤300 chars)",
      "applicable_section_ids":["string"]
    }
  ],

  "client_context_summary": {
    "brand_guide_provided":     true,
    "icp_provided":             true,
    "website_analysis_used":    true,
    "schema_version_effective": "1.7 | 1.7-no-context | 1.7-degraded | 1.7-legacy-h1"
  },

  "metadata": {
    "total_word_count":        0,
    "word_budget":             2500,
    "faq_word_count":          0,
    "budget_utilization_pct":  0.0,
    "word_count_conflict":     false,
    "no_required_terms":       false,
    "section_count":           0,
    "faq_count":               0,
    "citations_used":          0,
    "citations_unused":        0,
    "no_citations":            false,
    "retry_count":             0,

    "dropped_for_low_topic_adherence": [{"order": 0, "heading": "string", "score": 0.0}],
    "low_h2_count_after_adherence_drop": false,

    "paragraph_length_violations": [{"section_order": 0, "paragraph_index": 0, "sentence_count": 0}],

    "under_cited_sections": [
      {"section_order": 0, "citable_claims": 0, "cited_claims": 0, "ratio": 0.0, "threshold": 0.5, "operational_claims_softened": 0}
    ],
    "operational_claims_softened": [
      {"section_order": 0, "h2_order": 0, "rule": "duration-as-recommendation", "original": "...", "softened": "..."}
    ],
    "citation_coverage_retries_attempted":  0,
    "citation_coverage_retries_succeeded":  0,

    "under_length_h2_sections":          [{"section_order": 0, "word_count": 0, "floor": 0}],
    "h2_body_length_retries_attempted":  0,
    "h2_body_length_retries_succeeded":  0,

    "topic_brand_alignment":      "brand_aligned | brand_agnostic",
    "brand_mention_count":        0,
    "brand_mention_flags":        ["zero_brand_mentions_on_brand_aligned_topic | brand_mentions_exceed_target | brand_mentions_exceed_hard_cap"],
    "brand_anchor_h2_order":      0,
    "icp_anchor_h2_order":        0,
    "icp_hook_phrase":            "string",
    "icp_callout_landed":         true,
    "icp_callout_evidence":       "string (≤200 chars)",
    "icp_callout_judge_status":   "ok | anchor_not_in_article | empty_body | llm_failure | not_assigned",

    "max_sentences_per_paragraph_default_applied": false,
    "cta_truncated":              false,

    "schema_version":             "1.7",
    "brief_schema_version":       "2.0+",
    "generation_time_ms":         0
  }
}
```

`schema_version` valid values: `"1.7"`, `"1.7-no-context"`, `"1.7-degraded"`, `"1.7-legacy-h1"`. The orchestrator's `EXPECTED_MODULE_VERSIONS["writer"]` and `WRITER_ACCEPTED_VERSIONS` must include all four.

---

## 7. Failure Mode Reference

| Scenario | Behavior |
|---|---|
| Any input JSON fails schema validation | Abort `schema_validation_failed`; no partial output |
| `brief.keyword != research.keyword` or `!= sie.keyword` | Abort `keyword_mismatch` |
| `brief.title` missing / empty | Abort `brief_missing_title` (production); legacy fallback only for replay |
| `client_context` malformed | Abort `client_context_validation_error` |
| Distillation LLM fails twice | Abort `brand_distillation_failed` |
| Reconciliation LLM fails twice | Abort `brand_reconciliation_failed` |
| Intro generation malformed twice | Abort `intro_generation_failed` |
| Section LLM call times out | Retry once; on second failure insert `"[SECTION GENERATION FAILED — MANUAL REVIEW REQUIRED]"`; flag in metadata |
| Title generation produces 0 valid candidates | Fallback `"{keyword} — A Complete Guide"` |
| Word budget exceeded after all sections | Trim lowest-priority H3s by `heading_priority` from brief until budget met; log trimmed sections |
| End-to-end exceeds 90s | Abort `generation_timeout` |
| `sie.terms.required` empty | Continue; log `no_required_terms: true` |
| `research.citations` missing/empty | Degraded mode; sections written without citation grounding; `no_citations: true` |
| All claims for an H2 are `fallback_stub` | Write without specific factual assertions; reference source as context only; flag `all_stubs: true` on the section |
| Final article missing `key-takeaways` / `intro` / `cta` | Abort `missing_required_structure` with `missing_elements: [...]`. No partial output |
| Intro block >50 words after retry | Truncate at last sentence boundary ≤50 words; accept |
| CTA >30 words after retry | Truncate at last word boundary ≤30; flag `cta_truncated: true` |
| CTA matches hard-sales regex after retry | Truncate / sanitize; flag `cta_sanitized: true` |
| Key Takeaways count <3 after retry | Abort `key_takeaways_count_invalid` |
| Key Takeaways count >5 after retry | Truncate to 5 |
| Section fails R7 50% coverage after retry + soften | Accept; flag in `under_cited_sections` |
| Section fails R6 paragraph cap after retry | Accept; flag in `paragraph_length_violations` |
| H2 group below `min_h2_body_words` after retry | Accept best attempt; flag in `under_length_h2_sections` |
| Banned term in heading | Abort `banned_term_leakage` immediately; no retry |
| Banned term in body/FAQ/intro/conclusion/CTA after retry | Abort `banned_term_leakage`; surface term + field + snippet |
| Marker found in heading | Abort `marker_in_heading` |
| Brand mentions ≥6 (hard cap) after retry on highest-mention section | Accept; flag `brand_mentions_exceed_hard_cap`. Do not block. |
| <3 H2s remain after topic-adherence drop | Continue; log `low_h2_count_after_adherence_drop: true`. Not an abort. |
| ICP callout judge LLM fails | `icp_callout_landed = None`; not a flag |
| Serializer encounters unknown citation id | Emit marker verbatim; log `serializer_unknown_citation`. Not an abort. |

---

## 8. AEO Optimization Requirements

| Requirement | Implementation |
|---|---|
| Answer-first paragraphs | Every H2 opens with ≤25-word direct answer before elaboration |
| Self-contained FAQ answers | No cross-references to article sections |
| Clean section boundaries | Content does not bleed topically into adjacent sections |
| Factual density | Sections contain verifiable facts, not filler |
| Hedge-free substance | Claims must be specific and supportable; vague hedges do not satisfy word budgets |
| Question-answer alignment | H2s framed as questions answered directly in first sentence |
| Entity presence | High-salience entities appear in semantically appropriate sections; not forced everywhere |
| No promotional language | Avoid "the best", "industry-leading"; reduces citation trustworthiness |
| Self-contained Key Takeaways | Each Takeaway sentence extractable by an LLM citation surface |

---

## 9. Success Metrics

Structural and guardrail metrics, not downstream ranking.

| Metric | Target |
|---|---|
| Output validates against JSON schema | 100% |
| Word count within budget (±5%) | ≥95% |
| All `heading_structure` entries present in output (after adherence filter) | 100% |
| Required terms meeting zone minimums | ≥90% |
| Format directives satisfied (lists, tables, answer-first) | 100% |
| FAQ contains correct question count (3–5) | 100% |
| Conclusion present | 100% |
| Key Takeaways present (3–5 items) | 100% |
| Intro present (Agree/Promise/Preview, 60–150 words) | 100% |
| CTA present (≤30 words) | 100% |
| Per-section citation coverage ≥50% on citable claims | ≥85% (after retry + soften) |
| Per-H2 body length above intent floor | ≥90% |
| End-to-end within 90s | ≥95% |
| Cost per article < $0.75 | ≥95% |

---

## 10. Performance Targets

| Stage | Target | Max |
|---|---|---|
| End-to-end | 60s | 90s |
| Input validation + budget allocation | 2s | 5s |
| Title generation (3 candidates) | 5s | 10s |
| Brand distillation + reconciliation (parallel) | 5s | 15s |
| Section writing (all H2 groups, sequential) | 30s | 60s |
| FAQ + conclusion + CTA + Key Takeaways | 10s | 20s |
| Citation resolution + claim injection (per section, in-memory) | <1s | 2s |
| Step 6.4–6.8 validators | 5s | 10s |
| Step 7 citation reconciliation | <1s | 2s |
| Step 8 banned-term scan | <1s | 1s |
| Step 9 title-case pass | <1s | 1s |
| Step 10 serialization | <1s | 1s |

Section writing dominates. One LLM call per H2 group. Sequential due to term-budget state.

---

## 11. Cost Model

| Component | Cost per Article |
|---|---|
| Title generation | ~$0.01 |
| Brand distillation | $0.02–$0.04 |
| Brand reconciliation | $0.01–$0.02 |
| H1 (no LLM in v1.6+) | $0 |
| Intro construction | ~$0.01 |
| Section writing (6 H2 groups avg) | $0.20–$0.35 |
| Coverage retries (when fired) | $0.01–$0.03 each, ≤1/run steady state |
| FAQ writing | ~$0.05 |
| Conclusion + CTA | ~$0.02 |
| Key Takeaways | ~$0.02 |
| ICP callout judge | ~$0.005 |
| **Estimated total** | **$0.32–$0.52** |
| **Budget ceiling** | **$0.75** |

---

## 12. Business Rules Summary

| Rule | Value |
|---|---|
| Locale | English / United States |
| Word budget | 2,500 words (content sections only; FAQ excluded) |
| Word budget tolerance | ±5% |
| Title must contain seed keyword | Yes |
| H1 text | Verbatim from `brief.title` — no LLM regeneration |
| H1 enrichment lede max words | 25 |
| Intro construction | Single paragraph, 60–150 words, Agree/Promise/Preview in order |
| Conclusion word range | 100–150 words |
| FAQ answer word range | 40–80 words |
| FAQ may cross-reference article | No |
| Answer-first paragraphs | Required for all H2 sections |
| Avoid terms enforcement | Hard block; subject to brand-override (brand wins) |
| Sections trimmed when over budget | Lowest `heading_priority` H3s first |
| FAQ excluded from word budget | Yes |
| FAQ included in term zone tracking | Yes |
| Citation grounding required for H2s with verified claims | Yes — ≥1 non-stub claim per cited H2 |
| Fallback-stub claims used as factual assertions | Never |
| Body output format | GFM Markdown with `{{cit_N}}` markers |
| Marker format | `{{cit_N}}` — placed immediately after closing punctuation; regex `\{\{cit_[0-9]+\}\}` |
| Multiple citations in one sentence | Stacked, no spaces: `{{cit_001}}{{cit_004}}` |
| Markers in headings | Forbidden — abort if found |
| Citation usage tracked per id | Yes (`used`, `sections_used_in`, `marker_placed`) |
| Unused citations trigger retry | No — recorded as unused |
| Required structural elements | `key-takeaways` (3–5 items, ≤25 words each), `intro` (60–150 words single paragraph), `cta` (≤30 words). Missing any → abort `missing_required_structure` |
| H2 topic-adherence threshold | `cosine(h2.embedding, title.embedding) ≥ 0.62`; below → drop to spin-offs |
| Paragraph length cap | Default 4 sentences (`format_directives.max_sentences_per_paragraph`); over → one retry then accept + flag |
| External citation coverage on citable claims | ≥50% per section; below → one retry then auto-soften (C7/C8/C9 only) then accept + flag |
| Brand mention budget | 2–3 target; 0 + brand-aligned topic → flag (no reject); 4–5 → warn; ≥6 → retry then accept |
| Brand-aligned vs brand-agnostic | `cosine(title.embedding, brand_voice_card.client_services_joined.embedding) ≥ 0.55` → `brand_aligned` |
| Brand always wins term conflicts | Brand-banned > SIE-Required (exclude); Brand-preferred > SIE-Avoid (use) |
| Banned term enforcement | Regex, case-insensitive, word-boundary, alternation over `brand_voice_card.banned_terms` |
| Heading banned-term match | Abort immediately, no retry |
| Body/FAQ banned-term match | Retry once; second match → abort |
| Title case | `titlecase==2.4.1` pass on H1/H2/H3 (content/faq-header/conclusion/title); idempotent |
| Multi-format output | `article_markdown` + `article_html` always present when `article[]` non-empty |
| Brand voice card lifecycle | Regenerated per run; not cached; persisted in `brand_voice_card_used` |

---

## 13. What This PRD Does Not Cover

These belong to the engineering implementation layer, not the PRD:

- LLM model selection per call type (Anthropic Claude is the provider per platform decision — Sonnet vs Opus per call is implementation)
- Exact prompt templates / system prompts
- Lemmatizer selection for term audit (must match SIE module's implementation)
- Caching strategy for repeated (brief, SIE) input pairs
- Authentication and API key management
- Rate limiting and retry logic for LLM API calls
- Logging and observability beyond the named events
- Output storage schema in the platform database
- Schema versioning compatibility with future brief schema versions
- Term usage audit, hallucination scanning, and human review workflows (downstream quality module)
- Citation style formatting (APA, MLA, Chicago) — not required; Markdown footnotes + HTML `<sup>` only
- Citation link-rot detection post-publish (future monitoring module)
- CMS / publishing integration

---

## 14. Test Fixture Suggestions

Recommended fixtures to validate the module in isolation before platform integration:

| ID | Description | Asserts |
|---|---|---|
| F-A | Brief + Research + SIE, no `client_context` | Schema valid; `schema_version_effective == "1.7-no-context"`; v1.4 fallback path |
| F-B | All `client_context` fields empty + `website_analysis_unavailable: true` | `schema_version_effective == "1.7-degraded"` |
| F-C | Brand guide only; explicit banned terms; empty ICP; no website analysis | `brand_conflict_log` populates; banned terms absent in output |
| F-D | Full client context, two different brand guides on same brief/SIE | Section tone shifts visibly |
| F-E | Banned term that is also SIE-Required | Reconciliation excludes; `brand_conflict_log` records decision with cited reasoning |
| F-F | SIE-Avoid term that brand guide prefers | Brand wins; term present; conflict logged as `brand_preference_overrides_sie_avoid` |
| F-G | Brand guide bans a common term ("affordable") section writing might use naturally | Post-hoc regex catches; retry; either clean output or `banned_term_leakage` with term + field + snippet |
| F-H | Brand guide bans a term likely in a heading | Immediate abort on heading match; no retry |
| F-I | Brand guide bans `"art"`; section uses `"smart"` | Word boundary prevents false positive; `"smart"` passes |
| F-J | All H2s pass topic adherence | `dropped_for_low_topic_adherence == []` |
| F-K | Two H2s drift off-topic | Dropped; spin-off payload emitted; `low_h2_count_after_adherence_drop: false` if ≥3 remain |
| F-L | H2 group missing intent floor word count | Length retry triggered; success or `under_length_h2_sections` entry |
| F-M | Section with `"4-to-6 week refresh cadence"` and no matching citation | Coverage retry; if unresolved, soften to `"a typical refresh cadence (every few weeks)"`; entry in `operational_claims_softened` |
| F-N | Section with `"5% rule"` no citation | Soften to `"a small percentage rule"` |
| F-O | Section with `"18% in Q3"` no citation | NOT softened (C1 statistic); accept; flag in `under_cited_sections` |
| F-P | Brief missing `title` | Abort `brief_missing_title` (production path); legacy fallback path emits `"1.7-legacy-h1"` |
| F-Q | Intro LLM returns 4-paragraph response | Single-paragraph validation retry; deterministic collapse on second failure |
| F-R | CTA includes "Buy now" | Hard-sales regex retry; sanitize + flag if still present |
| F-S | Key Takeaways returns 6 sentences | Truncate to 5; no abort |
| F-T | Key Takeaways returns 2 sentences | Abort `key_takeaways_count_invalid` |
| F-U | `article[]` non-empty + valid citation markers | `article_markdown` round-trips to plain text body; `article_html` parses; markers map 1:1 across `article[]` / MD / HTML |
| F-V | Marker `{{cit_999}}` references unknown citation | Serializer emits verbatim + `serializer_unknown_citation` log; no abort |

---

## 15. Implementation Notes (non-normative)

These are guidance for the build team but not part of the contract:

- Use `text-embedding-3-small` for both the title topic anchor (§5.4.2) and the Key Takeaways pair-similarity check (§5.12). Match the model the SIE module uses for embedding consistency.
- The brand voice card is the only LLM-distilled artifact persisted to the run record. Persist the full card (not just a hash) so editors can audit the basis for tone decisions on a per-run basis.
- Step 3.5a and 3.5b are independent and parallelizable. Do not block 3.5b on 3.5a's output — both consume the raw `brand_guide_text`.
- Section writing is sequential due to term-budget state (later sections see remaining term budget after earlier sections). Do NOT parallelize H2 group calls.
- The topic-adherence filter (§5.4.2) and the Key Takeaways generation (§5.12) both rely on embeddings. Batch embedding calls where possible to reduce per-article API overhead.
- The defense-in-depth title-case pass (§5.18) is the last operation that mutates `article[]` content. The serializers (§5.19) must run AFTER this pass and must NOT mutate `article[]`.
- The output `article_markdown` is what the platform's Publish module ships to the Google Docs Apps Script webhook. Validate the Markdown renders cleanly in Google Docs preview before declaring the run complete.
- The `article_html` field is consumed by direct paste into WordPress / Google Docs visual editor. Validate against the WordPress code block + visual editor flow specifically — both must produce readable rich text.
