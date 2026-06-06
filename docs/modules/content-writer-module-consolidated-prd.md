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

- Keyword research / brief generation (upstream — see §1.4)
- Internal linking suggestions
- Image selection / alt-text generation
- Meta description generation
- Schema markup injection (JSON-LD)
- CMS publishing or API push (Sources Cited + platform Publish module handle delivery — see §1.4)
- Multi-locale support
- Rank tracking, citation link-rot monitoring
- Human review workflows / editorial routing
- Rewriting prior runs — each run is independent

### 1.4 Pipeline Position & Sibling Modules

The Writer is one of five generation modules in the Blog Writer pipeline. All five are **sibling Python modules in the same private pipeline-api service**, invoked sequentially by the platform-api orchestrator (which validates each module's returned `schema_version` against an `EXPECTED_MODULE_VERSIONS` map and persists outputs to the platform database). The Writer does not call upstream or downstream modules directly — the orchestrator does.

```
Brief Generator                  ← upstream (Input A)
        │  emits: title, scope_statement, heading_structure[] with
        │         per-heading citation_ids, FAQs, format_directives,
        │         intent_format_template, word_budget
        ▼
SIE Term & Entity Module         ← upstream (Input C)
        │  emits: required/avoid terms, per-zone usage recommendations,
        │         target keyword floors, entities with categories
        ▼
Research & Citations Module      ← upstream (Input B)
        │  emits: verified citation pool with claims, relevance scores,
        │         extraction_method flags, mapped to brief headings
        ▼
[Client Context from platform-api]   ← upstream (Input D)
        │  emits: brand_guide_text, icp_text, website_analysis
        ▼
┌───────────────────────────────┐
│        Content Writer         │  ← THIS MODULE
│   (modules/writer/)           │     emits: article[] with {{cit_N}}
└───────────────┬───────────────┘            markers + article_markdown
                │                            + article_html + metadata
                ▼
Sources Cited Module             ← downstream
        │  consumes Writer output + Research output
        │  resolves {{cit_N}} markers → numbered <sup><a> superscripts,
        │  builds MLA-style "## Sources Cited" section, applies
        │  rel="nofollow" to external URLs
        ▼
Content Editor / Platform Publish module (Google Doc via Apps Script webhook)
```

#### 1.4.1 Upstream: Brief Generator

The article outline does NOT come from this module. It comes from the **Content Brief Generator** (sibling module at `modules/brief/`, PRD `docs/modules/content-brief-generator-prd-v2_0.md`, canonical version 2.3). The Writer does not reinterpret the brief — it executes it. Every field the Writer consumes as Input A (§2.1) is produced by the brief generator's pipeline:

| Brief generator step | Produces field used by Writer |
|---|---|
| Step 3 — Title + scope statement generation | `brief.title` (H1 verbatim — §5.2), `brief.scope_statement` (intro Promise anchor — §5.3) |
| Step 3 — `intent_format_template` | `format_directives.min_h2_body_words` floors (§5.10 H2 body length validator), `h2_pattern` family |
| Steps 4–6 — Coverage graph + MMR scoring | `heading_structure[]` with H2 embeddings used by §5.4.2 topic-adherence filter |
| Step 7.5 — Anchor-slot reservation | Template-required H2 slots (e.g., comparison's parallel evaluative axes) |
| Step 8.5 — Scope verification | Out-of-scope H2s already discarded before Writer sees the brief |
| Steps 8.6 + 8.7 — H3 selection + parent-fit verification | H3 attachment with the 0.65 cosine floor |
| Step 9 — Authority gap H3s | `heading_structure[].source: "authority_gap_sme"` (triggers §5.4.1 1.2× budget multiplier and §5.8.5 substantive register bar) |
| Step 10 + 10.5 — FAQ generation + intent gate | `faqs[]` (3–5 questions consumed by §5.9) |
| Step 11 — Heading framing + title-case normalization | Pre-normalized H2/H3 text. The Writer's defense-in-depth title-case pass (§5.18) uses the same pinned `titlecase==2.4.1` library, so the round-trip is a no-op for already-cased input. |
| Step 12 — Silo identification | H2s the Writer drops via §5.4.2 topic-adherence filter are forwarded back to this routing for future-brief seeding |

The Writer enforces a strict `brief_schema_version` floor of `2.0+` because the H1-from-brief contract (§5.2.1) requires `brief.title`, which was introduced in Brief PRD v2.0 Step 3.

#### 1.4.2 Downstream: Sources Cited Module

The Writer does NOT produce final reader-facing citations. It produces **citation marker tokens** (`{{cit_N}}`) in `article[].body`. The **Sources Cited module** (sibling at `modules/sources_cited/`, PRD `docs/modules/sources-cited-module-prd-v1_1.md`, canonical version 1.1) consumes Writer output and renders the final form.

What Sources Cited does that the Writer deliberately does not:

| Sources Cited step | Action |
|---|---|
| 1 — Marker discovery | Scans every `article[].body` for `{{cit_N}}` tokens (regex `\{\{cit_[0-9]+\}\}`) in document order |
| 2 — Number assignment | Assigns sequential numbers `[1]`, `[2]`, `[3]`… by **order of first appearance**. The Writer's citation *ids* (`cit_001`, `cit_007`) are NOT the user-facing numbers; the numbers are assigned here. |
| 3 — Superscript substitution | Replaces `{{cit_N}}` with `<sup><a href="#cite-1">1</a></sup>` jumplinks. Stacked markers in one sentence sort ascending. |
| 4 — `used: true` filtering | Only citations the Writer marked as placed in prose (via `citation_usage.usage[]`) appear in the bibliography |
| 5 — MLA-derived rendering | Builds the `## Sources Cited` section appended to the article. v1 format: `Title. Publication. URL.` (author/date deferred to v2 because the Research module's author/published_date fields are not yet reliable enough) |
| 6 — `rel="nofollow"` | Applied to every external URL in the bibliography |

The handoff contract:

- **Writer produces** `{{cit_N}}` plain-text tokens inside Markdown `body` fields, placed immediately after the closing punctuation of the cited sentence. Marker ids match regex `^cit_[0-9]+$`. Markers are forbidden in headings — match in any heading → abort `marker_in_heading` (§5.8.7 / D9).
- **Writer does NOT produce** inline Markdown hyperlinks (`[anchor text](url)`) in prose; numbered citation references; a `## Sources Cited` bibliography; `rel="nofollow"` decoration. All of these are downstream.
- **Writer DOES produce** the flat `article_markdown` (`[^N]` GitHub-footnote form) and `article_html` (`<sup><a href="#cite-N">` form) serializations as an *additional* convenience for consumers that bypass Sources Cited entirely (e.g., the platform Publish module's Google Docs / WordPress paste flow). When the Sources Cited module runs, its numbered MLA-rendered output is the canonical form that goes to the Content Editor and Publish modules next.
- **Schema floor:** Sources Cited rejects Writer output below `schema_version` 1.4 because the `{{cit_N}}` marker contract did not exist before that version.

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

---

## 16. Companion Documents (bundle alongside this PRD)

If the implementing team is building the full Blog Writer pipeline (not just the Writer), hand over these sibling PRDs alongside this document. They are required to implement Inputs A/B/C/D and to integrate the downstream renderer.

| Module | File | Canonical version | Why bundle |
|---|---|---|---|
| Content Brief Generator | `docs/modules/content-brief-generator-prd-v2_0.md` | 2.3 | Produces Input A. The Writer's H1 verbatim contract, `intent_format_template`-driven body-length floors, H2 embeddings, authority-gap H3 tagging, FAQ generation, and title-case normalization all originate here. |
| SIE Term & Entity Module | `docs/modules/SIE_PRD_Term_Entity_Module.md` | latest | Produces Input C. Required/avoid term lists, per-zone usage recommendations, target-keyword floors, entity categorization with `is_entity` flag and `recommendation_score`. |
| Research & Citations | `docs/modules/research-citations-module-prd-v1_1_1.md` | 1.1.1 | Produces Input B. Verified citation pool, `extraction_method` semantics (`verbatim_extraction` vs `fallback_stub`), `citation_id` regex contract, `relevance_score`. |
| Sources Cited | `docs/modules/sources-cited-module-prd-v1_1.md` | 1.1 | Consumes Writer output. Defines the `{{cit_N}}` marker discovery, first-appearance numbering, `<sup><a>` substitution, MLA-derived bibliography, `rel="nofollow"` rules. |
| Content Quality PRD | `docs/content-quality-prd-v1_0.md` | 1.0 | Cross-cutting requirements R1–R7 (topic adherence, paragraph length, citable-claim coverage, brand mention budget, required structural elements). The Writer encodes these. |
| Suite Architecture & Roadmap | `docs/suite-architecture-and-roadmap-v1_0.md` | 1.0 | The locked decision log (LLM provider, embeddings provider, SERP source, GSC auth, publish destination). Resolves ambiguity when this PRD references a "platform-level choice." |
| Engineering Implementation Spec | `docs/engineering-implementation-spec-v1_1.md` | 1.1 | Service topology (Railway private network), Supabase schema, `async_jobs` queueing pattern, logging conventions, error envelope, authentication boundary. The infrastructure substrate this module runs on. |

The Writer PRD intentionally does not duplicate content from those documents. Where this PRD says "see Brief PRD" or "consumed by Sources Cited," the implementing team needs the actual sibling document open.

---

## 17. LLM Call Inventory (Anthropic Claude)

Provider: **Anthropic Claude** (locked per suite roadmap). All structured-output calls use **tool use** for guaranteed-valid JSON; prose calls use plain text output. Model IDs assume the Claude 4.X family; substitute newer IDs if available, keeping the size tier (Opus / Sonnet / Haiku).

| # | Call | Model | Output mode | Max tokens (output) | Temperature | Retries on malformed |
|---|---|---|---|---|---|---|
| 1 | Title generation (3 candidates) | `claude-haiku-4-5` | tool use (JSON) | 512 | 0.7 | 1 (then fallback `"{keyword} — A Complete Guide"`) |
| 2 | Brand voice distillation | `claude-sonnet-4-6` | tool use (JSON) | 2,048 | 0.2 | 1 (then abort `brand_distillation_failed`) |
| 3 | Brand–SIE term reconciliation | `claude-sonnet-4-6` | tool use (JSON) | 2,048 | 0.2 | 1 (then abort `brand_reconciliation_failed`) |
| 4 | Intro construction (Agree/Promise/Preview) | `claude-sonnet-4-6` | tool use (JSON, 3 string blocks) | 512 | 0.5 | 1 (then deterministic truncate/collapse, never abort) |
| 5 | Section writing (per H2 group) | `claude-sonnet-4-6` | plain text (Markdown) | 1,500 (group-budget-scaled) | 0.6 | 1 on retry directives (coverage, length, banned-term, paragraph) |
| 6 | FAQ writing | `claude-sonnet-4-6` | tool use (JSON: `[{question, answer}]`) | 2,048 | 0.5 | 1 |
| 7 | Conclusion writing | `claude-sonnet-4-6` | plain text (Markdown) | 512 | 0.5 | 1 |
| 8 | CTA writing | `claude-haiku-4-5` | tool use (JSON: `{cta}`) | 128 | 0.4 | 1 (then truncate, flag `cta_truncated`) |
| 9 | Key Takeaways | `claude-sonnet-4-6` | tool use (JSON: `{takeaways: [...]}`) | 768 | 0.4 | 1 (then accept 3–5 bounds or abort if <3) |
| 10 | ICP callout judge | `claude-haiku-4-5` | tool use (JSON: `{landed, evidence, reasoning}`) | 256 | 0.0 | 0 (failure → `icp_callout_landed = None`) |

**Why these tiers:**
- **Haiku** for short / deterministic / classification calls (title candidates, CTA, judge). Cheap, fast, accurate enough for these shapes.
- **Sonnet** for everything that writes substantive prose (sections, intro, FAQ, conclusion, takeaways) and for structured categorization with reasoning (distillation, reconciliation). The Writer's quality bar requires Sonnet-class output for prose.
- **Opus** is **not** used in v1 because Sonnet quality is sufficient and the article-level budget ceiling ($0.75) doesn't accommodate Opus on the 6-section-writing critical path.

**Tool use contract for JSON calls:** Define a single tool per call with a strict schema. Request `tool_choice: {type: "tool", name: "..."}` so Claude is forced to invoke it. This eliminates the malformed-JSON failure mode in steady state — retries are reserved for content-validity failures (over word count, banned term match, etc.), not parse failures.

**Streaming:** Not required. Section writing benefits from streaming if the platform surfaces progressive UI, but the Writer's metadata-construction passes need the full body before they run, so streaming is consumer-facing only.

**Rate limiting + retries on transient errors:** Outside this PRD's scope — handled by the platform-api HTTP client layer (`httpx` with retry policy on 429 / 5xx).

---

## 18. Prompt Scaffolds

These are skeletons, not production prompts. They lock in the structural contract — what each call receives and what it must return — leaving phrasing details to implementation. Production prompts will be longer (system prompt boilerplate, output-shape examples, tone guidance) but must preserve these contracts.

### 18.1 Title generation (Call #1)

**System:** You are a content strategist producing SEO-optimized blog post titles.

**User:**
```
Generate 3 candidate titles for a blog post.

Seed keyword: {brief.keyword}
Intent type: {brief.intent_type}
Required SIE terms (top 10 by recommendation_score): {sie.terms.required[:10]}
High-salience entities: {sie.entities[:5]}

Rules:
- Every title MUST contain the seed keyword verbatim.
- Title tone by intent: how-to → "How to …" / "How [Audience] Can …"; listicle → leads with a number; comparison → includes "vs." or "or"; everything else → declarative, value-led.
- Incorporate as many high-scoring Required terms / entities as fit naturally. Keyword + entity coverage takes priority over brevity.
- Avoid clickbait, superlatives ("best", "ultimate"), and questions.

Return via the `submit_titles` tool with three candidates.
```

**Tool schema:**
```json
{
  "name": "submit_titles",
  "input_schema": {
    "type": "object",
    "required": ["candidates"],
    "properties": {
      "candidates": {
        "type": "array",
        "minItems": 3,
        "maxItems": 3,
        "items": {"type": "string", "maxLength": 120}
      }
    }
  }
}
```

Selection: deterministic post-LLM. Score each candidate by `(keyword_present ? 1 : 0) + count(required_terms ∩ title) + count(entities ∩ title)`. Highest score wins; tie-break shortest.

### 18.2 Brand voice distillation (Call #2)

**System:** You categorize and summarize brand guidance. You do not invent brand preferences not present in the source text.

**User:**
```
Extract a structured brand voice card from the following inputs.

Brand guide text:
"""
{brand_guide_text}
"""

ICP text:
"""
{icp_text}
"""

Website analysis (factual reference only):
- Services: {website_analysis.services}
- Locations: {website_analysis.locations}
- Contact: {website_analysis.contact_info}

Rules:
- Tone adjectives come ONLY from the brand guide text. Do not supplement from website data.
- A term is `banned` only when the brand guide explicitly prohibits it. `discouraged` if expressed against without explicit prohibition. `preferred` if explicitly named as preferred phrasing.
- All term lists must be terms or phrases that appear in or are explicitly named by the source text. Return [] if the brand guide doesn't address term-level guidance.
- Audience pain points, goals, and verticals come from the ICP text.
- Website services/locations/contact carry verbatim into the card.

Return via `submit_brand_voice_card`.
```

Tool schema mirrors §5.5 output exactly. Field limits (e.g., `max_items: 30` on banned_terms) are enforced in the schema.

### 18.3 Brand–SIE reconciliation (Call #3)

**System:** You classify SIE term recommendations against a brand guide. Every non-`keep` classification must cite specific brand-guide text.

**User:**
```
Brand guide:
"""
{brand_guide_text}
"""

SIE Required terms (must classify each):
{sie.terms.required}

SIE Avoid terms (must classify each):
{sie.terms.avoid}

For each Required term, classify as:
- `keep` (no brand conflict)
- `exclude_due_to_brand_conflict` (brand explicitly bans)
- `reduce_due_to_brand_preference` (brand discourages without explicit ban)

For each Avoid term, classify as:
- `keep_avoiding` (no brand preference)
- `use_due_to_brand_preference` (brand explicitly prefers)

Brand always wins. Every non-`keep` and non-`keep_avoiding` classification MUST include `brand_guide_reasoning` quoting the specific brand-guide text (≤300 chars).

Return via `submit_reconciliation`.
```

### 18.4 Intro construction (Call #4)

**System:** You write blog post introductions in a strict three-beat structure.

**User:**
```
Write the article's introduction as a single paragraph (60–150 words) in three beats:

1. Agree (≤50 words) — name the reader's situation in their own language. Anchor in the ICP when provided. Do not name the brand. Do not begin with the seed keyword.
2. Promise (≤50 words) — state what this article will deliver, anchored in the title and scope. May reference the seed keyword once. No CTA.
3. Preview (≤50 words) — name 2–4 of the H2 sections in order. Plain language. No bullets. No verbatim heading list.

Inputs:
- Title: {output.title}
- Scope: {brief.scope_statement}
- Intent: {brief.intent_type}
- ICP summary: {brand_voice_card.audience_summary}
- H2 list (post-adherence filter, in order): {[h.text for h in kept_h2s]}
- Brand voice block: {brand_voice_card.tone_adjectives + voice_directives}
- Banned terms (must not appear): {brand_voice_card.banned_terms + filtered_sie_excluded}

Return the three blocks via `submit_intro`.
```

**Tool schema:**
```json
{
  "name": "submit_intro",
  "input_schema": {
    "type": "object",
    "required": ["agree", "promise", "preview"],
    "properties": {
      "agree":   {"type": "string", "maxLength": 350},
      "promise": {"type": "string", "maxLength": 350},
      "preview": {"type": "string", "maxLength": 350}
    }
  }
}
```

Post-LLM, the three blocks are joined into a single paragraph with a single space between them and validated per §5.3.

### 18.5 Section writing (Call #5, runs N times)

**System:** You are a senior content writer producing SEO-optimized prose for a specific brand voice and audience.

**User (per H2 group):**
```
Write the following H2 group in Markdown. Output ONLY the section content — no preamble, no postamble, no commentary.

H2 heading: {h2.text}
H3 children (write each in order if present): {[h3.text for h3 in h2.children]}
Word budget for this group: {section_budget}
Intent type: {brief.intent_type}
Intent pattern: {intent_format_template.h2_pattern}

--- Brand & Audience ---
Tone: {brand_voice_card.tone_adjectives}
Voice directives:
{brand_voice_card.voice_directives}
Audience: {brand_voice_card.audience_summary}
Pain points to acknowledge where natural: {brand_voice_card.audience_pain_points}

--- Client context (use only where natural) ---
Services: {brand_voice_card.client_services}
Locations: {brand_voice_card.client_locations}
{must_mention_brand directive if anchor}
{must_not_mention_brand directive if non-anchor}
{icp_callout_hook directive if ICP anchor}

--- Citations available for this section ---
{for cit in resolved_citations:}
  - {{cit.citation_id}} — extraction_method: {cit.extraction_method}
    Verified claims:
      {for claim in cit.claims if claim.relevance_score >= 0.5:}
        - "{claim.claim_text}"
{end}

Citation rules:
- For each specific factual assertion sourced from a citation, place its marker immediately after the closing punctuation: `Demand climbed 18% in Q3.{{cit_007}}`
- Multiple citations in one sentence: stack with no spaces: `{{cit_001}}{{cit_004}}`
- Markers ONLY in body, NEVER in headings.
- `fallback_stub` citations: do not assert specific figures from the stub claim. You may reference the publication as supporting context ("according to [publication]…"), but no statistics, prices, or specific facts from the stub.

--- Format rules ---
- First sentence of the H2 body MUST directly answer the heading in ≤25 words.
- Maximum 4 sentences per paragraph; 3 preferred.
- {if format_directives.require_bulleted_lists: "Include at least one bulleted or numbered list across the H2 group."}
- {if format_directives.require_tables: "Include at least one Markdown table across the H2 group."}

--- Term targets ---
Required terms (with per-zone usage targets):
{for term in filtered_sie_terms.required scoped to this section:}
  - "{term.term}" — h2: {term.effective_target}, h3: {term.effective_target}, paragraph: {term.effective_target} (max {term.effective_max})
{end}

Excluded terms (do not use — brand or SIE conflict):
{filtered_sie_terms.excluded + brand_voice_card.banned_terms + filtered_sie_terms.avoid}

Output format:
```
## {h2.text}
{H2 body, with H3 subsections as needed:}
### {h3.text}
{H3 body}
```
```

For retry directives:
- **Coverage retry** (§5.8.8): prepend `COVERAGE_RETRY: The following sentences contain claims requiring citation but were emitted without markers: [list sentences]. Either append a {{cit_N}} marker from the available pool above, OR rewrite the sentence to remove the specific statistic / year / brand attribution.`
- **Length retry** (§5.10): prepend `LENGTH_RETRY: This H2 group came in at {current_word_count} words but the minimum substance floor for this intent is {floor} words. Add additional substance — facts, examples, evidence — NOT padding or filler. Re-emit the entire H2 group.`
- **Paragraph retry** (§5.9): prepend `PARAGRAPH_RETRY: Paragraph {n} contains {sentence_count} sentences; the cap is {max_sentences}. Split it on a logical break. Re-emit the entire section.`
- **Banned-term retry** (§5.17): prepend `BANNED_TERM_RETRY: The output contained "{term}" which is banned by client brand guidance. Rewrite the section without using "{term}" or any variant. Substitutions are at your discretion; preserve meaning.`

### 18.6 FAQ writing (Call #6)

**System:** You write self-contained FAQ answers optimized for LLM citation extraction.

**User:**
```
Write answers to the following FAQ questions. Each answer must be 40–80 words, answer-first, self-contained (a reader must understand the answer without reading the rest of the article).

Questions (in order):
{for faq in brief.faqs:}
  {faq.order}. {faq.question}
{end}

Rules:
- Answer-first: first sentence directly addresses the question.
- Self-contained: NO "as mentioned above" or other cross-references.
- The seed keyword "{brief.keyword}" (or its primary sub-phrase) must appear in at least 2 answers across the set.
- Respect brand voice ({brand_voice_card.tone_adjectives}) and banned terms ({brand_voice_card.banned_terms + filtered_sie_excluded}).
- ICP framing: questions and answers should reflect how {brand_voice_card.audience_summary} would actually ask, not generic SEO phrasing.

Return via `submit_faqs`.
```

### 18.7 Conclusion (Call #7)

```
Write the article's conclusion in 100–150 words.

Rules:
- 2–3 sentences synthesizing the article's core takeaways.
- The seed keyword "{brief.keyword}" must appear at least once.
- Do NOT include a CTA — the CTA is rendered as a separate element after this paragraph.
- Do NOT introduce new information not covered in the article body.
- {if brand_voice_card.client_services exists: "May include a natural closing sentence referencing the client's services where contextually relevant. Never a hard sales pitch."}
- Brand voice: {tone_adjectives + voice_directives}.
- Banned terms: {banned_terms + filtered_sie_excluded}.

Output plain prose (no Markdown headers).
```

### 18.8 CTA (Call #8)

```
Write a single-sentence call-to-action, ≤30 words.

Rules:
- Must name a specific next action (read, download, contact, evaluate, compare, sign up, request, schedule, audit, review).
- {if icp_text provided: "Draw the next-step verb from the audience's stated goals: " + audience_goals}
- {else: use the intent-appropriate template:}
  - how-to: "Try these steps in your next [task] and measure the result."
  - informational: "Explore [related sub-topic] next."
  - comparison: "Run this comparison against your current [solution category] to see where the trade-offs land for your team."
  - local-seo / ecom / informational-commercial: "When you're ready to evaluate options, look for [criterion drawn from article]."
  - news: "Watch for follow-on coverage as the situation develops."
- Hard-sales phrases BANNED: "buy now", "purchase now", "limited time", "act today".

Article title (for context): {output.title}

Return via `submit_cta`.
```

### 18.9 Key Takeaways (Call #9)

```
Produce 3–5 key takeaways summarizing the assembled article below.

Rules:
- Each takeaway is a single standalone sentence, ≤25 words.
- Each takeaway must be self-contained — readable without the surrounding article.
- Facts or actionable claims only. No opinion, no marketing language, no rhetorical questions.
- Takeaways must not repeat each other.
- Brand mentions count against the brand-mention budget.

Article title: {output.title}

Assembled article body:
"""
{full_article_body_excluding_intro_and_h1}
"""

Return via `submit_takeaways`.
```

Post-LLM: cosine pairwise check (≥0.85 → regenerate offending pair); per-takeaway word count check (>25 → retry once with limit named).

### 18.10 ICP callout judge (Call #10)

```
Did the following article section land an audience-specific callout for the named ICP hook?

Hook to look for: "{icp_hook_phrase}"
Audience pain points (for synonym recognition): {audience_pain_points}
Audience verticals: {audience_verticals}

Section body (truncated to 4,000 chars):
"""
{anchor_section.body[:4000]}
"""

Rules:
- Paraphrases of the hook count as landed ("margin erosion from refunds" ≈ "shrinking unit economics on returned orders").
- A generic acknowledgment of "the audience" does not count — the callout must name the specific pain point or vertical.
- When landed, return a verbatim quote (≤200 chars) as evidence.

Return via `submit_judgment`.
```

Tool schema:
```json
{
  "name": "submit_judgment",
  "input_schema": {
    "type": "object",
    "required": ["landed", "reasoning"],
    "properties": {
      "landed":    {"type": "boolean"},
      "evidence":  {"type": "string", "maxLength": 200},
      "reasoning": {"type": "string", "maxLength": 280}
    }
  }
}
```

---

## 19. Closures (the loose ends the contract depends on)

### 19.1 Embeddings

| Use site | Model | Dimensionality | Threshold |
|---|---|---|---|
| Title topic anchor (§5.4.2 H2 adherence filter) | `text-embedding-3-small` | 1,536 | cosine ≥ 0.62 to keep |
| Brand-aligned vs brand-agnostic determination | `text-embedding-3-small` | 1,536 | cosine ≥ 0.55 to title = `brand_aligned` |
| Key Takeaways pair similarity (§5.12) | `text-embedding-3-small` | 1,536 | cosine ≥ 0.85 → regenerate pair |

Calibrated against `text-embedding-3-small`'s vector space. A different embedding model requires recalibration of these thresholds (the values are not portable across providers).

### 19.2 Tech stack assumptions baked into this spec

| Layer | Choice | Why it matters |
|---|---|---|
| Language | Python 3.11+ | Regex semantics (`re.IGNORECASE`, `\b` Unicode handling), `titlecase` library availability |
| Web framework | FastAPI | Pydantic models for input/output validation; `BackgroundTasks` for async work without Celery |
| HTTP client | `httpx` (async) | Anthropic SDK is async-friendly; concurrent embedding batches |
| Title-case library | `titlecase==2.4.1` | Pinned to match Brief Generator's exact behavior. Different versions produce different casing on edge cases ("vs." vs "Vs.", "iPhone" preservation). |
| Anthropic SDK | `anthropic>=0.40` | Tool use, claude-4.x model support |
| OpenAI SDK | `openai>=1.0` | For embeddings only |

If the other app uses Node/TypeScript: the title-case library equivalent is [`titlecase-js`](https://www.npmjs.com/package/titlecase) (validate behavior parity on the heading test corpus before declaring equivalent). Regex `\b` semantics are equivalent. The embedding and Anthropic SDKs have first-party JS clients.

### 19.3 Complete enum lists

**`intent_type`** (8 values, from Brief PRD):
`informational`, `listicle`, `how-to`, `comparison`, `ecom`, `local-seo`, `news`, `informational-commercial`

**`heading_structure[].level`** (4 values):
`H1`, `H2`, `H3`, `none`

**`heading_structure[].type`** (4 values):
`content`, `faq-header`, `faq-question`, `conclusion`

**`heading_structure[].source`** (3 values):
`serp_derived`, `authority_gap_sme`, `editorial_added`

**`article[].type`** (9 values):
`title`, `content`, `faq-header`, `faq-question`, `conclusion`, `h1-enrichment`, `key-takeaways`, `intro`, `cta`

**`entity_category`** (open-ended; common values): `services`, `equipment`, `problems`, `methods`, `brands`, `tools`, `audiences`, `locations`, `concepts`, `regulations`

**`citations[].extraction_method`** (2 values): `verbatim_extraction`, `fallback_stub`

**`citations[].verification_method`** (3 values): `claim_in_extracted_text`, `entity_overlap`, `stub_acknowledgment`

**Reconciliation actions** (Required terms): `keep`, `exclude_due_to_brand_conflict`, `reduce_due_to_brand_preference`
**Reconciliation actions** (Avoid terms): `keep_avoiding`, `use_due_to_brand_preference`

**`brand_conflict_log[].resolution`** (3 values): `exclude_due_to_brand_conflict`, `reduce_due_to_brand_preference`, `brand_preference_overrides_sie_avoid`

**`brand_mention_flags`** (3 values): `zero_brand_mentions_on_brand_aligned_topic`, `brand_mentions_exceed_target`, `brand_mentions_exceed_hard_cap`

**`topic_brand_alignment`** (2 values): `brand_aligned`, `brand_agnostic`

**`icp_callout_judge_status`** (5 values): `ok`, `anchor_not_in_article`, `empty_body`, `llm_failure`, `not_assigned`

**`schema_version`** valid values: `1.7`, `1.7-no-context`, `1.7-degraded`, `1.7-legacy-h1`

### 19.4 SIE field `is_entity`

`sie.terms.required[*].is_entity` is a boolean indicating whether the term is a Named Entity Recognition (NER)-recognized entity (organization, product, person, location) as opposed to a generic noun phrase. Pattern C6 (§5.8.8) requires this field: a sentence is citable under C6 if it contains an entity name where `is_entity == true` AND a quantitative or temporal qualifier from C1–C3. The SIE module produces this flag during entity merge.

### 19.5 First-party domain extraction (§5.8.8)

When multiple citation candidates exist for a single claim, prefer the citation whose URL domain matches the entity named in the claim sentence:

```python
from urllib.parse import urlparse

def extract_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    # Strip "www." prefix
    return netloc[4:] if netloc.startswith("www.") else netloc

# Match: entity "Shopify" → prefer citation where extract_domain(cit.url) contains "shopify"
def is_first_party(citation_url: str, entity_name: str) -> bool:
    domain = extract_domain(citation_url)
    entity_normalized = entity_name.lower().replace(" ", "")
    return entity_normalized in domain.replace(".", "").replace("-", "")
```

### 19.6 Error envelope (wire format)

All structured errors returned by the Writer conform to:

```json
{
  "error": {
    "code": "string (snake_case, from the failure-mode table §7)",
    "message": "human-readable summary",
    "details": {
      "stage": "step name (e.g., 'step_3_5a_distillation', 'step_4_section_writing')",
      "h2_order": 4,
      "field": "article[4].body",
      "snippet": "≤200-char excerpt of offending content",
      "expected": "string or object describing what was expected",
      "actual": "string or object describing what was received"
    },
    "schema_version": "1.7",
    "trace_id": "uuid"
  }
}
```

HTTP status: `400` for input-validation errors (`keyword_mismatch`, `brief_missing_title`, `client_context_validation_error`, schema validation failures, `missing_required_structure`, `key_takeaways_count_invalid`). `422` for content-policy aborts (`banned_term_leakage`, `marker_in_heading`). `500` for upstream LLM exhaustion (`brand_distillation_failed`, `brand_reconciliation_failed`, `intro_generation_failed`). `504` for `generation_timeout`.

### 19.7 Logging payload

All log lines are structured JSON. Required fields on every log line:

```json
{
  "ts": "2026-06-06T18:23:14.482Z",
  "level": "INFO | WARN | ERROR",
  "event": "writer.coverage.retry",
  "run_id": "uuid",
  "request_id": "uuid",
  "module": "writer",
  "schema_version": "1.7"
}
```

Event-specific payloads add fields. For the events named in this PRD:

| Event | Additional fields |
|---|---|
| `writer.coverage.complete` | `groups_inspected`, `retries_attempted`, `retries_succeeded`, `sections_softened`, `under_cited_remaining` |
| `writer.coverage.retry` | `section_order`, `h2_order`, `citable_claims`, `cited_claims`, `ratio` |
| `writer.coverage.retry_succeeded` | `section_order`, `before_ratio`, `after_ratio` |
| `writer.coverage.under_cited_after_retry` | `section_order`, `final_ratio`, `softened_count` |
| `writer.h2_length.retry` | `section_order`, `word_count`, `floor` |
| `writer.h2_length.retry_succeeded` | `section_order`, `before_words`, `after_words`, `floor` |
| `writer.h2_length.retry_still_under` | `section_order`, `final_words`, `floor` |
| `banned_term_leakage` (when retry succeeds, logged but not surfaced) | `term`, `field`, `snippet`, `recovered_via_retry: true` |
| `title_case_round_trip_failed` (rare safety-net failure) | `level`, `text`, `expected` |
| `serializer_unknown_citation` | `citation_id`, `position` |

Never log: JWTs, full brand guide text, API keys, user passwords. Log brand-guide *snippets* (≤200 chars) only when explicitly required for an error envelope.

### 19.8 Determinism and seeding

The Writer is **not** required to be bit-exact reproducible across runs (LLM stochasticity). It IS required to be deterministic in:

- Title selection (post-LLM scoring + tie-break).
- Word budget allocation.
- Topic-adherence filter (embedding cosine + 0.62 threshold).
- Brand & ICP placement plan (token-set scoring + lowest-order tie-break).
- Citable-claim detection regex passes (C1–C9).
- Auto-soften lookups.
- Title-case pass (idempotent).
- Markdown / HTML serialization.

Two runs with identical inputs and identical Anthropic + OpenAI seeds (when set) MUST produce identical metadata fields, identical placement decisions, and identical serializer output. Prose body content may differ.

---

## 20. Golden Example (end-to-end walkthrough)

A minimal but shape-complete example. Article topic: **"How to Pick Project Management Software for Small Teams"** (intent: `informational-commercial`). Hypothetical client: **Tessera Studios**, a 12-person operations consulting firm.

Truncated to fit: 3 content H2s + conclusion, 3 FAQs, 5 citations. Body prose elided with `[...]` for length. The shape of every required field is shown.

### 20.1 Input A — Brief

```json
{
  "schema_version": "2.3",
  "keyword": "project management software for small teams",
  "title": "How to Pick Project Management Software for Small Teams",
  "scope_statement": "A buyer's-education guide for ops leaders at 10–50-person teams choosing their first project management tool. Covers selection criteria, common pitfalls, and migration steps. Excludes feature-by-feature competitive matrices and enterprise / 500+ seat tooling.",
  "intent_type": "informational-commercial",
  "intent_format_template": {
    "h2_pattern": "buyer_education_axes",
    "h2_framing_rule": "evaluation_criterion_or_decision_factor",
    "ordering": "natural_decision_sequence",
    "min_h2_count": 4,
    "max_h2_count": 7,
    "anchor_slots": ["selection_criteria", "common_pitfalls", "migration_steps"]
  },
  "heading_structure": [
    {"order": 0, "level": "H1", "type": "content", "text": "How to Pick Project Management Software for Small Teams", "citation_ids": []},
    {"order": 1, "level": "H2", "type": "content", "text": "What to Evaluate Before You Compare Tools", "source": "serp_derived", "citation_ids": ["cit_001", "cit_002"], "embedding": [0.0123, -0.0456, "..."]},
    {"order": 2, "level": "H3", "type": "content", "text": "How to Tell If You Actually Need One Yet", "source": "authority_gap_sme", "citation_ids": ["cit_003"]},
    {"order": 3, "level": "H2", "type": "content", "text": "Common Mistakes Small Teams Make When Choosing PM Software", "source": "serp_derived", "citation_ids": ["cit_002", "cit_004"], "embedding": [0.0234, -0.0345, "..."]},
    {"order": 4, "level": "H2", "type": "content", "text": "How to Migrate Your Team to a New PM Tool", "source": "serp_derived", "citation_ids": ["cit_005"], "embedding": [0.0345, -0.0234, "..."]},
    {"order": 5, "level": "H2", "type": "faq-header", "text": "Frequently Asked Questions", "citation_ids": []},
    {"order": 6, "level": "H3", "type": "faq-question", "text": "How much should a small team spend on project management software?", "citation_ids": []},
    {"order": 7, "level": "H3", "type": "faq-question", "text": "Is free project management software good enough for a startup?", "citation_ids": []},
    {"order": 8, "level": "H3", "type": "faq-question", "text": "How long does it take to roll out PM software to a 20-person team?", "citation_ids": []},
    {"order": 9, "level": "H2", "type": "conclusion", "text": "", "citation_ids": []}
  ],
  "faqs": [
    {"order": 0, "question": "How much should a small team spend on project management software?", "faq_score": 0.84, "intent_role": "matches_primary_intent"},
    {"order": 1, "question": "Is free project management software good enough for a startup?", "faq_score": 0.79, "intent_role": "matches_primary_intent"},
    {"order": 2, "question": "How long does it take to roll out PM software to a 20-person team?", "faq_score": 0.71, "intent_role": "adjacent_intent"}
  ],
  "format_directives": {
    "require_bulleted_lists": true,
    "require_tables": true,
    "min_lists_per_article": 1,
    "min_tables_per_article": 1,
    "answer_first_paragraphs": true,
    "max_sentences_per_paragraph": 4,
    "min_h2_body_words": 180
  },
  "metadata": {
    "word_budget": 2500,
    "h2_count": 4,
    "h3_count": 1,
    "schema_version": "2.3"
  }
}
```

### 20.2 Input B — Research & Citations

```json
{
  "schema_version": "1.1",
  "keyword": "project management software for small teams",
  "citations": [
    {
      "citation_id": "cit_001",
      "url": "https://www.gartner.com/en/articles/picking-pm-software-2024",
      "title": "Picking PM Software in 2024: A Buyer's Guide",
      "publication": "Gartner",
      "author": "Gartner Research",
      "published_date": "2024-03-12",
      "extraction_method": "verbatim_extraction",
      "verification_method": "claim_in_extracted_text",
      "claims": [
        {"claim_text": "62% of teams under 50 employees report dissatisfaction with their first PM tool within 18 months.", "relevance_score": 0.91, "extraction_method": "verbatim_extraction", "verification_method": "claim_in_extracted_text"},
        {"claim_text": "The top three evaluation criteria cited by small teams are price, learning curve, and integration with existing tools.", "relevance_score": 0.87, "extraction_method": "verbatim_extraction", "verification_method": "claim_in_extracted_text"}
      ]
    },
    {
      "citation_id": "cit_002",
      "url": "https://hbr.org/2023/09/the-real-cost-of-tool-sprawl",
      "title": "The Real Cost of Tool Sprawl",
      "publication": "Harvard Business Review",
      "author": "Jane Doe",
      "published_date": "2023-09-04",
      "extraction_method": "verbatim_extraction",
      "verification_method": "claim_in_extracted_text",
      "claims": [
        {"claim_text": "Small companies adopting more than 4 SaaS productivity tools see a 23% drop in task-completion velocity within 6 months.", "relevance_score": 0.78, "extraction_method": "verbatim_extraction", "verification_method": "claim_in_extracted_text"}
      ]
    },
    {
      "citation_id": "cit_003",
      "url": "https://www.atlassian.com/blog/teamwork/when-to-adopt-pm-tools",
      "title": "When Does a Small Team Actually Need PM Software?",
      "publication": "Atlassian",
      "author": "Atlassian Work Futures Team",
      "published_date": "2024-01-22",
      "extraction_method": "verbatim_extraction",
      "verification_method": "claim_in_extracted_text",
      "claims": [
        {"claim_text": "Teams smaller than 5 people typically outgrow shared spreadsheets when they hit 3 concurrent multi-week projects.", "relevance_score": 0.82, "extraction_method": "verbatim_extraction", "verification_method": "entity_overlap"}
      ]
    },
    {
      "citation_id": "cit_004",
      "url": "https://www.forrester.com/report/the-pm-software-adoption-trap",
      "title": "The PM Software Adoption Trap",
      "publication": "Forrester",
      "author": "Forrester Analytics",
      "published_date": "2023-11-30",
      "extraction_method": "fallback_stub",
      "verification_method": "stub_acknowledgment",
      "claims": [
        {"claim_text": "[stub: original page returned 403; URL preserved as source acknowledgment only]", "relevance_score": 0.55, "extraction_method": "fallback_stub", "verification_method": "stub_acknowledgment"}
      ]
    },
    {
      "citation_id": "cit_005",
      "url": "https://www.shopify.com/research/team-tool-migration-playbook",
      "title": "Team Tool Migration Playbook",
      "publication": "Shopify Research",
      "author": "Shopify Operations Team",
      "published_date": "2024-02-14",
      "extraction_method": "verbatim_extraction",
      "verification_method": "claim_in_extracted_text",
      "claims": [
        {"claim_text": "A staged migration over 4–6 weeks reduces tool-abandonment risk by 41% compared to a single-day cutover.", "relevance_score": 0.89, "extraction_method": "verbatim_extraction", "verification_method": "claim_in_extracted_text"}
      ]
    }
  ]
}
```

### 20.3 Input C — SIE

```json
{
  "schema_version": "1.4",
  "keyword": "project management software for small teams",
  "word_count": {"target": 2400, "min": 2000, "max": 2800},
  "target_keyword": {
    "term": "project management software",
    "minimum_usage": {"h2": 0, "h3": 0, "paragraphs": 6}
  },
  "terms": {
    "required": [
      {"term": "project management software", "recommendation_score": 0.98, "is_entity": false, "entity_category": null},
      {"term": "small teams", "recommendation_score": 0.92, "is_entity": false, "entity_category": null},
      {"term": "task management", "recommendation_score": 0.78, "is_entity": false, "entity_category": "methods"},
      {"term": "integrations", "recommendation_score": 0.74, "is_entity": false, "entity_category": "methods"},
      {"term": "Asana", "recommendation_score": 0.71, "is_entity": true, "entity_category": "brands"},
      {"term": "Trello", "recommendation_score": 0.68, "is_entity": true, "entity_category": "brands"},
      {"term": "ClickUp", "recommendation_score": 0.66, "is_entity": true, "entity_category": "brands"},
      {"term": "user adoption", "recommendation_score": 0.63, "is_entity": false, "entity_category": "problems"}
    ],
    "avoid": ["best-in-class", "synergy"]
  },
  "usage_recommendations": [
    {"term": "project management software", "h2": {"min": 0, "target": 1, "max": 2}, "h3": {"min": 0, "target": 0, "max": 1}, "paragraphs": {"min": 6, "target": 8, "max": 12}},
    {"term": "small teams", "h2": {"min": 0, "target": 1, "max": 2}, "h3": {"min": 0, "target": 0, "max": 1}, "paragraphs": {"min": 3, "target": 5, "max": 8}},
    {"term": "task management", "h2": {"min": 0, "target": 0, "max": 1}, "h3": {"min": 0, "target": 0, "max": 1}, "paragraphs": {"min": 1, "target": 2, "max": 4}},
    {"term": "integrations", "h2": {"min": 0, "target": 0, "max": 1}, "h3": {"min": 0, "target": 0, "max": 1}, "paragraphs": {"min": 1, "target": 2, "max": 4}},
    {"term": "Asana", "h2": {"min": 0, "target": 0, "max": 1}, "h3": {"min": 0, "target": 0, "max": 0}, "paragraphs": {"min": 0, "target": 1, "max": 2}},
    {"term": "Trello", "h2": {"min": 0, "target": 0, "max": 1}, "h3": {"min": 0, "target": 0, "max": 0}, "paragraphs": {"min": 0, "target": 1, "max": 2}},
    {"term": "ClickUp", "h2": {"min": 0, "target": 0, "max": 1}, "h3": {"min": 0, "target": 0, "max": 0}, "paragraphs": {"min": 0, "target": 1, "max": 2}},
    {"term": "user adoption", "h2": {"min": 0, "target": 0, "max": 1}, "h3": {"min": 0, "target": 0, "max": 0}, "paragraphs": {"min": 0, "target": 1, "max": 3}}
  ],
  "entities": [
    {"term": "Asana", "entity_category": "brands", "example_context": "task and project management tool from Asana, Inc.", "ner_variants": ["Asana"], "recommendation_score": 0.71},
    {"term": "Trello", "entity_category": "brands", "example_context": "Kanban-style PM tool acquired by Atlassian", "ner_variants": ["Trello"], "recommendation_score": 0.68},
    {"term": "ClickUp", "entity_category": "brands", "example_context": "all-in-one PM platform", "ner_variants": ["ClickUp"], "recommendation_score": 0.66}
  ]
}
```

### 20.4 Input D — Client Context (Tessera Studios)

```json
{
  "client_context": {
    "brand_guide_text": "Tessera Studios is an operations consulting firm. Voice: plainspoken, confident, anti-jargon. We refuse marketing-speak. BANNED TERMS: synergy, leverage (as a verb), best-in-class, robust, seamless, world-class. PREFERRED PHRASING: 'clear', 'concrete', 'outcomes', 'in practice'. We address readers as peers, not as students. We never use 'imagine if', 'picture this', or 'in today's fast-paced world'. We open every piece by naming the problem, not by setting a scene.",
    "icp_text": "Our readers are operations leaders at 10-50 person teams — founders, ops managers, head-of-ops, COO at companies past PMF but before Series B. They're under-resourced, allergic to fluff, and have to defend every tool purchase to a skeptical founder or board. They've already tried at least one PM tool and abandoned it. Pain points: tool fatigue, team adoption failures, hidden migration costs, and the gap between vendor demos and daily reality. Goals: pick something that survives 18 months, doesn't require a dedicated admin, and integrates with their existing Slack + GSuite stack.",
    "website_analysis": {
      "services": ["operations consulting", "tool stack audits", "team workflow design"],
      "locations": ["Brooklyn, NY"],
      "tone": [],
      "positioning": ""
    },
    "website_analysis_unavailable": false
  }
}
```

### 20.5 Output (Writer JSON)

```json
{
  "keyword": "project management software for small teams",
  "intent_type": "informational-commercial",
  "title": "How to Pick Project Management Software for Small Teams",

  "article": [
    {
      "order": 0,
      "level": "H1",
      "type": "title",
      "heading": "How to Pick Project Management Software for Small Teams",
      "body": null,
      "word_count": 0,
      "section_budget": 0,
      "citations_referenced": []
    },
    {
      "order": 1,
      "level": "none",
      "type": "h1-enrichment",
      "heading": null,
      "body": "A practical guide to evaluation criteria, common pitfalls, and migration for teams of 10–50 already past the spreadsheet stage.",
      "word_count": 22,
      "section_budget": 25,
      "citations_referenced": []
    },
    {
      "order": 2,
      "level": "none",
      "type": "key-takeaways",
      "heading": "Key Takeaways",
      "body": "- Most small teams pick PM software on features and regret it within 18 months.{{cit_001}}\n- Price, learning curve, and integration depth are the three criteria that actually predict retention.{{cit_001}}\n- Adopting more than four overlapping SaaS tools cuts task velocity by nearly a quarter.{{cit_002}}\n- A staged 4–6 week migration cuts abandonment risk by 41% versus a single-day cutover.{{cit_005}}\n- The right test for needing a tool is three concurrent multi-week projects, not headcount.{{cit_003}}",
      "word_count": 78,
      "section_budget": 100,
      "citations_referenced": ["cit_001", "cit_002", "cit_003", "cit_005"]
    },
    {
      "order": 3,
      "level": "none",
      "type": "intro",
      "heading": null,
      "body": "If your team has already tried a project management tool and quietly abandoned it, you're not alone — 62% of small teams report dissatisfaction with their first PM tool within 18 months. This guide gives you the three evaluation criteria that actually predict whether a tool will stick, the mistakes that sink most small-team rollouts, and a staged migration plan that survives contact with daily work. You'll see how to evaluate before you compare tools, the common mistakes small teams make when choosing PM software, and how to migrate your team to a new tool without losing the first month.",
      "word_count": 108,
      "section_budget": 150,
      "citations_referenced": []
    },
    {
      "order": 4,
      "level": "H2",
      "type": "content",
      "heading": "What to Evaluate Before You Compare Tools",
      "body": "Price, learning curve, and integration depth predict whether a project management software pick survives 18 months — features barely matter. According to Gartner, those are the top three evaluation criteria cited by small teams.{{cit_001}} Most buyers invert this and start with feature checklists; that's how they end up with a tool no one logs into by month six. [... ~150 more words covering the three criteria with concrete examples ...]\n\n### How to Tell If You Actually Need One Yet\n\nThe honest test is concurrent project load, not headcount. Atlassian's research found that teams under five people typically outgrow shared spreadsheets when they hit three concurrent multi-week projects.{{cit_003}} If you're running one or two projects at a time, a shared doc and a recurring Friday review will outperform any tool you adopt. [... ~80 more words ...]",
      "word_count": 312,
      "section_budget": 360,
      "citations_referenced": ["cit_001", "cit_003"]
    },
    {
      "order": 5,
      "level": "H2",
      "type": "content",
      "heading": "Common Mistakes Small Teams Make When Choosing PM Software",
      "body": "The most expensive mistake is stacking tools instead of replacing them. Harvard Business Review found that small companies adopting more than four SaaS productivity tools see a 23% drop in task-completion velocity within six months.{{cit_002}} Forrester has covered the same adoption trap in its research on PM tooling.{{cit_004}} [... ~250 words covering: picking on demo polish, ignoring integration depth, skipping the trial team, not naming an admin. Includes a Markdown table of the four mistakes with symptoms and corrections. Mentions Asana, Trello, and ClickUp as examples of feature-rich tools that get over-adopted ...]\n\nFor Tessera Studios clients we've audited, the pattern is consistent: the team picks a tool, two people set it up, three weeks later only one person is logging in, and the tool quietly joins the graveyard of abandoned subscriptions. The fix is naming the admin BEFORE the trial, not after — a concrete person whose job includes onboarding and quarterly cleanup.",
      "word_count": 308,
      "section_budget": 360,
      "citations_referenced": ["cit_002", "cit_004"]
    },
    {
      "order": 6,
      "level": "H2",
      "type": "content",
      "heading": "How to Migrate Your Team to a New PM Tool",
      "body": "Stage the migration over four to six weeks, not in a single weekend. Shopify's operations research found a staged migration cuts tool-abandonment risk by 41% compared to a single-day cutover.{{cit_005}} The cutover-on-Friday plan fails because it asks people to learn new workflows under deadline pressure; the staged plan asks them to learn it during low-stakes work. [... ~220 words covering: pilot team selection, dual-running existing projects, integration setup with Slack and GSuite, training cadence, and the post-cutover cleanup. Includes a bulleted list of week-by-week milestones ...]",
      "word_count": 296,
      "section_budget": 360,
      "citations_referenced": ["cit_005"]
    },
    {
      "order": 7,
      "level": "H2",
      "type": "faq-header",
      "heading": "Frequently Asked Questions",
      "body": null,
      "word_count": 0,
      "section_budget": 0,
      "citations_referenced": []
    },
    {
      "order": 8,
      "level": "H3",
      "type": "faq-question",
      "heading": "How much should a small team spend on project management software?",
      "body": "Small teams should expect to spend $10–$20 per user per month for project management software that handles their workflow without forcing upgrades. Cheaper tools cover task management but often miss the integrations small teams need with Slack, calendar, and document storage. Spending more than $25 per user usually buys enterprise features your team won't use for at least a year.",
      "word_count": 61,
      "section_budget": 0,
      "citations_referenced": []
    },
    {
      "order": 9,
      "level": "H3",
      "type": "faq-question",
      "heading": "Is free project management software good enough for a startup?",
      "body": "Free project management software works for teams under five people running one or two concurrent projects, but breaks down when integrations, permissions, or reporting matter. Most free tiers cap users or projects exactly where small teams start to feel friction. If you're past three concurrent multi-week projects, the time you lose to workarounds usually costs more than the paid tier.",
      "word_count": 62,
      "section_budget": 0,
      "citations_referenced": []
    },
    {
      "order": 10,
      "level": "H3",
      "type": "faq-question",
      "heading": "How long does it take to roll out PM software to a 20-person team?",
      "body": "A 20-person team can roll out project management software in four to six weeks if you stage it properly. Plan one week of admin setup and integrations, two weeks of pilot use with a single team, then a phased rollout to the remaining people over two to three weeks. Single-weekend cutovers technically work but produce a 41% higher abandonment rate.",
      "word_count": 60,
      "section_budget": 0,
      "citations_referenced": []
    },
    {
      "order": 11,
      "level": "H2",
      "type": "conclusion",
      "heading": "",
      "body": "Picking project management software for small teams is a question of fit, not features. Evaluate on price, learning curve, and integration depth before you compare tools; avoid the four mistakes that sink most rollouts; and stage your migration so people learn the new workflow during low-stakes work. Tessera Studios runs tool stack audits with operations teams in exactly this situation — the audit is usually faster than a vendor demo cycle and produces a tool list your team will actually use.",
      "word_count": 84,
      "section_budget": 125,
      "citations_referenced": []
    },
    {
      "order": 12,
      "level": "none",
      "type": "cta",
      "heading": null,
      "body": "Audit your current tool stack against the three criteria before you start any new PM software trial.",
      "word_count": 17,
      "section_budget": 30,
      "citations_referenced": []
    }
  ],

  "article_markdown": "# How to Pick Project Management Software for Small Teams\n\nA practical guide to evaluation criteria, common pitfalls, and migration for teams of 10–50 already past the spreadsheet stage.\n\n## Key Takeaways\n\n- Most small teams pick PM software on features and regret it within 18 months.[^1]\n- Price, learning curve, and integration depth are the three criteria that actually predict retention.[^1]\n- Adopting more than four overlapping SaaS tools cuts task velocity by nearly a quarter.[^2]\n- A staged 4–6 week migration cuts abandonment risk by 41% versus a single-day cutover.[^3]\n- The right test for needing a tool is three concurrent multi-week projects, not headcount.[^4]\n\nIf your team has already tried a project management tool and quietly abandoned it, you're not alone — 62% of small teams report dissatisfaction with their first PM tool within 18 months. [... full intro paragraph ...]\n\n## What to Evaluate Before You Compare Tools\n\nPrice, learning curve, and integration depth predict whether a project management software pick survives 18 months — features barely matter. According to Gartner, those are the top three evaluation criteria cited by small teams.[^1] [... section body ...]\n\n### How to Tell If You Actually Need One Yet\n\nThe honest test is concurrent project load, not headcount. [... H3 body ...]\n\n## Common Mistakes Small Teams Make When Choosing PM Software\n\n[... section ...]\n\n## How to Migrate Your Team to a New PM Tool\n\n[... section ...]\n\n## Frequently Asked Questions\n\n### How much should a small team spend on project management software?\n\nSmall teams should expect to spend $10–$20 per user per month [... answer ...]\n\n### Is free project management software good enough for a startup?\n\n[... answer ...]\n\n### How long does it take to roll out PM software to a 20-person team?\n\n[... answer ...]\n\n## Conclusion\n\nPicking project management software for small teams is a question of fit, not features. [... conclusion ...]\n\nAudit your current tool stack against the three criteria before you start any new PM software trial.\n\n## Sources\n\n[^1]: Picking PM Software in 2024: A Buyer's Guide — https://www.gartner.com/en/articles/picking-pm-software-2024\n[^2]: The Real Cost of Tool Sprawl — https://hbr.org/2023/09/the-real-cost-of-tool-sprawl\n[^3]: Team Tool Migration Playbook — https://www.shopify.com/research/team-tool-migration-playbook\n[^4]: When Does a Small Team Actually Need PM Software? — https://www.atlassian.com/blog/teamwork/when-to-adopt-pm-tools\n",

  "article_html": "<h1>How to Pick Project Management Software for Small Teams</h1>\n<p>A practical guide to evaluation criteria, common pitfalls, and migration for teams of 10–50 already past the spreadsheet stage.</p>\n<h2>Key Takeaways</h2>\n<p>[... bulleted body with &lt;sup&gt;&lt;a href=&quot;#cite-1&quot;&gt;1&lt;/a&gt;&lt;/sup&gt; superscripts ...]</p>\n[... more elements ...]\n<h2>Sources</h2>\n<ol>\n<li id=\"cite-1\"><a href=\"https://www.gartner.com/en/articles/picking-pm-software-2024\">Picking PM Software in 2024: A Buyer's Guide</a></li>\n<li id=\"cite-2\"><a href=\"https://hbr.org/2023/09/the-real-cost-of-tool-sprawl\">The Real Cost of Tool Sprawl</a></li>\n<li id=\"cite-3\"><a href=\"https://www.shopify.com/research/team-tool-migration-playbook\">Team Tool Migration Playbook</a></li>\n<li id=\"cite-4\"><a href=\"https://www.atlassian.com/blog/teamwork/when-to-adopt-pm-tools\">When Does a Small Team Actually Need PM Software?</a></li>\n</ol>\n",

  "key_takeaways": [
    "Most small teams pick PM software on features and regret it within 18 months.",
    "Price, learning curve, and integration depth are the three criteria that actually predict retention.",
    "Adopting more than four overlapping SaaS tools cuts task velocity by nearly a quarter.",
    "A staged 4–6 week migration cuts abandonment risk by 41% versus a single-day cutover.",
    "The right test for needing a tool is three concurrent multi-week projects, not headcount."
  ],

  "intro": {
    "agree": "If your team has already tried a project management tool and quietly abandoned it, you're not alone — 62% of small teams report dissatisfaction with their first PM tool within 18 months.",
    "promise": "This guide gives you the three evaluation criteria that actually predict whether a tool will stick, the mistakes that sink most small-team rollouts, and a staged migration plan that survives contact with daily work.",
    "preview": "You'll see how to evaluate before you compare tools, the common mistakes small teams make when choosing PM software, and how to migrate your team to a new tool without losing the first month."
  },

  "cta": "Audit your current tool stack against the three criteria before you start any new PM software trial.",

  "citation_usage": {
    "total_citations_available": 5,
    "citations_used": 5,
    "citations_unused": 0,
    "usage": [
      {"citation_id": "cit_001", "used": true, "sections_used_in": [2, 4], "marker_placed": true},
      {"citation_id": "cit_002", "used": true, "sections_used_in": [2, 5], "marker_placed": true},
      {"citation_id": "cit_003", "used": true, "sections_used_in": [2, 4], "marker_placed": true},
      {"citation_id": "cit_004", "used": true, "sections_used_in": [5], "marker_placed": true},
      {"citation_id": "cit_005", "used": true, "sections_used_in": [2, 6], "marker_placed": true}
    ]
  },

  "format_compliance": {
    "lists_present": 2,
    "tables_present": 1,
    "lists_required": 1,
    "tables_required": 1,
    "answer_first_applied": true,
    "directives_satisfied": true
  },

  "brand_voice_card_used": {
    "tone_adjectives": ["plainspoken", "confident", "anti-jargon", "peer-to-peer"],
    "voice_directives": [
      "Open by naming the problem; do not set a scene.",
      "Address readers as peers, never as students.",
      "Refuse marketing-speak.",
      "Use concrete examples over abstractions.",
      "Prefer 'in practice' framing to 'imagine if'."
    ],
    "audience_summary": "Operations leaders at 10–50-person teams (founders, ops managers, COOs) past PMF but pre-Series B, under-resourced, allergic to fluff, defending tool purchases to skeptical founders.",
    "audience_pain_points": [
      "tool fatigue from already-abandoned tools",
      "team adoption failures",
      "hidden migration costs",
      "gap between vendor demos and daily reality"
    ],
    "audience_goals": [
      "pick something that survives 18 months",
      "avoid needing a dedicated admin",
      "integrate with existing Slack + GSuite stack"
    ],
    "audience_verticals": ["B2B SaaS", "operations consulting", "early-stage startups"],
    "preferred_terms": ["clear", "concrete", "outcomes", "in practice"],
    "banned_terms": ["synergy", "leverage", "best-in-class", "robust", "seamless", "world-class", "imagine if", "picture this", "in today's fast-paced world"],
    "discouraged_terms": [],
    "brand_name": "Tessera Studios",
    "client_services": ["operations consulting", "tool stack audits", "team workflow design"],
    "client_locations": ["Brooklyn, NY"],
    "client_contact_info": {"phone": null, "email": null, "address": null, "hours": null}
  },

  "brand_conflict_log": [],

  "client_context_summary": {
    "brand_guide_provided": true,
    "icp_provided": true,
    "website_analysis_used": true,
    "schema_version_effective": "1.7"
  },

  "metadata": {
    "total_word_count": 2218,
    "word_budget": 2500,
    "faq_word_count": 183,
    "budget_utilization_pct": 88.7,
    "word_count_conflict": false,
    "no_required_terms": false,
    "section_count": 4,
    "faq_count": 3,
    "citations_used": 5,
    "citations_unused": 0,
    "no_citations": false,
    "retry_count": 1,

    "dropped_for_low_topic_adherence": [],
    "low_h2_count_after_adherence_drop": false,

    "paragraph_length_violations": [],

    "under_cited_sections": [],
    "operational_claims_softened": [],
    "citation_coverage_retries_attempted": 0,
    "citation_coverage_retries_succeeded": 0,

    "under_length_h2_sections": [],
    "h2_body_length_retries_attempted": 1,
    "h2_body_length_retries_succeeded": 1,

    "topic_brand_alignment": "brand_aligned",
    "brand_mention_count": 2,
    "brand_mention_flags": [],
    "brand_anchor_h2_order": 5,
    "icp_anchor_h2_order": 4,
    "icp_hook_phrase": "tool fatigue from already-abandoned tools",
    "icp_callout_landed": true,
    "icp_callout_evidence": "If your team has already tried a project management tool and quietly abandoned it, you're not alone",
    "icp_callout_judge_status": "ok",

    "max_sentences_per_paragraph_default_applied": false,
    "cta_truncated": false,

    "schema_version": "1.7",
    "brief_schema_version": "2.3",
    "generation_time_ms": 71240
  }
}
```

### 20.6 What this example exercises

| Behavior | Where it shows up |
|---|---|
| H1 verbatim from brief | `article[0].heading == brief.title` |
| Enrichment lede ≤25 words | `article[1].word_count == 22` |
| Key Takeaways with markers | `article[2].body` has `{{cit_001}}` etc. |
| Intro 60–150 words, single paragraph | `article[3].body` joined; `word_count: 108` |
| Authority-gap H3 | `article[4].body` contains the `### How to Tell If You Actually Need One Yet` subsection |
| Fallback stub used as context only | `cit_004` referenced as "Forrester has covered the same adoption trap" — no specific stat from the stub |
| Brand anchor H2 mentions Tessera Studios | `metadata.brand_anchor_h2_order: 5` matches the H2 containing the Tessera mention |
| ICP anchor H2 surfaces pain point | `metadata.icp_anchor_h2_order: 4`, judge landed: true with paraphrase evidence |
| Brand mention count within budget | `brand_mention_count: 2` (target 2–3) |
| Brand-aligned topic | `topic_brand_alignment: "brand_aligned"` because client services overlap with article topic |
| Markdown footnotes | `article_markdown` uses `[^1]` and `## Sources` |
| HTML superscripts + Sources `<ol>` | `article_html` uses `<sup><a href="#cite-1">` and `<li id="cite-1">` |
| H2 body length retry succeeded | `h2_body_length_retries_attempted: 1`, `_succeeded: 1` |
| Zero brand conflicts | `brand_conflict_log: []` (no SIE-vs-brand term overlap on this input) |
| No coverage retries needed | `citation_coverage_retries_attempted: 0` (claims were well-cited on first pass) |
| `schema_version_effective: "1.7"` | Full v1.7 path, client context present and well-formed |

A test fixture can replay these payloads end-to-end and assert each row of this table.

