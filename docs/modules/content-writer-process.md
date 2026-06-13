# Content Writer — Process Reference

**Status:** Living reference (describes the code as built)
**Module:** `writer/pipeline-api/modules/writer/`
**Schema version:** `1.7` (accepted variants: `1.7-no-context`, `1.7-degraded`)
**Authoritative specs:** `docs/modules/content-writer-module-prd-v1.3.md` (header says v1.7), `docs/writer-module-v1_5-change-spec_2.md`, `docs/content-quality-prd-v1_0.md` (R1–R7)

> This document explains *how the Content Writer actually runs* — the order of
> steps, what each step does, and where it lives in the code. It is a process
> map, not a spec. When the PRDs and this doc disagree about intended behavior,
> the PRDs win; when this doc and the code disagree about actual behavior, the
> code wins (and this doc should be corrected). The orchestrator and each
> module's `SCHEMA_VERSION` constant remain the source of truth for versions.

---

## 1. Where the Writer sits in the pipeline

The Writer is the fourth of the five Blog Writer pipeline modules. It runs
inside the private **pipeline-api** and is dispatched by the **platform-api**
orchestrator (`writer/platform-api/services/orchestrator.py`).

```
brief  →  sie  →  research  →  WRITER  →  sources_cited
```

- **Upstream inputs** (all independent payloads): the Brief Generator output,
  the SIE Term & Entity output, and the Research & Citations output.
- **Client context** is injected by the orchestrator from the run's snapshot
  (brand guide text, ICP text, website analysis) — see
  `_build_writer_payload` in `orchestrator.py`.
- **Downstream consumer:** the Sources Cited module, which receives the
  Writer's article plus the research output.

The orchestrator calls the Writer at `POST /write` with a 600-second timeout
(the Writer makes many sequential LLM calls). It validates the returned
`metadata.schema_version` against `WRITER_ACCEPTED_VERSIONS`
(`{"1.7", "1.7-no-context", "1.7-degraded"}`).

**Entry point:** `routers/router.py` → `run_writer()` in `pipeline.py`.

---

## 2. Inputs and outputs

### Request (`WriterRequest`, `models/writer.py`)

| Field | Required | Purpose |
|---|---|---|
| `run_id` | yes | Correlation id for logging |
| `attempt` | no (default 1) | Retry attempt counter |
| `brief_output` | yes | Heading structure, FAQs, title/H1, format directives, word budget |
| `sie_output` | yes | Required/avoid terms, per-zone category targets, word-count target |
| `research_output` | no | Enriched heading structure (with citation ids), citation pool, supporting stats |
| `client_context` | no | Brand guide text, ICP text, website analysis (drives brand shaping) |

### Response (`WriterResponse`)

A structured article object — **not** raw markdown. The article is a list of
`ArticleSection` items (each with `order`, `level`, `type`, `heading`, `body`,
`word_count`, `citations_referenced`), plus `title`, `citation_usage`,
`format_compliance`, the `brand_voice_card_used`, the `brand_conflict_log`,
`client_context_summary`, `term_usage_by_zone`, and a rich `metadata` block.
Markdown rendering happens later (in platform-api's publish router).

---

## 3. The process, step by step

The orchestration lives in `run_writer()` (`pipeline.py`). Steps below follow
execution order. A recurring design rule appears throughout: **generation
order ≠ render order** — sections are written in the order that gives each the
most context, then re-ordered and re-sequenced for the final article.

### Step 0 — Input validation & cross-validation (`_validate_inputs`)
- Confirms `brief_output` / `sie_output` are dicts.
- Cross-checks that `brief.keyword` matches `sie.keyword` (case-insensitive) —
  a mismatch aborts with `keyword_mismatch`.
- Resolves the **heading structure**, preferring Research's `enriched_brief.
  heading_structure` (it carries per-heading citation ids) and falling back to
  the brief's own. An empty structure aborts (`empty_heading_structure`).
- Validates FAQ count is between 3 and 5 (`faq_count_invalid`).
- Extracts the citation pool from the research output.

### Step 0.5 — Heading-structure sanitizer (`sanitize_heading_structure`)
Cleans two real-world drift modes from upstream briefs before any content is
generated:
- **Duplicate body H2s** with identical normalized heading text.
- **FAQ-as-content H2s** (a body H2 titled "Frequently Asked Questions" / "Q&A"
  that used to render before the conclusion, producing the "conclusion in the
  middle of the FAQs" bug).

H3 children of dropped H2s are dropped with them. Drops are **warn-and-accept**
and surfaced in metadata (`duplicate_h2_headings_dropped`,
`faq_like_h2_content_dropped`, `h3_children_dropped_under_h2`). Original
`order` values are preserved so downstream lookups by `order` keep working.

### Step 0.6 — Conflict detection (advisory flags)
Sets `no_required_terms`, `no_citations`, and `word_count_conflict` (true when
the SIE word-count target and the brief's word budget differ by more than 20%).
These are surfaced in metadata, not blocking.

### Step 3 — Word-budget allocation (`allocate_budget`)
Distributes the article's word budget (`brief.metadata.word_budget`, default
2500) across sections, returning a per-section budget keyed by heading `order`.

### Steps 3.5a / 3.5b — Brand voice distillation ‖ term reconciliation (parallel)
This is where `client_context` shapes the article. Three paths:

1. **No `client_context`** → schema becomes `1.7-no-context`; all SIE terms are
   kept as-is (no brand filtering).
2. **`client_context` present but fully empty** (no brand guide, no ICP, no
   website) → schema becomes `1.7-degraded`; same all-keep behavior.
3. **`client_context` has signal** → run two tasks concurrently:
   - **Distillation** (`distill_brand_voice`) produces a `BrandVoiceCard`
     (tone, voice directives, audience personas/pain points/verticals,
     preferred/banned/discouraged terms, services, locations, contact info).
     Failure aborts with `brand_distillation_failed`.
   - **Reconciliation** (`reconcile_terms`) filters SIE terms against the brand
     guide, producing `FilteredSIETerms` plus a `brand_conflict_log` recording
     every term excluded or down-weighted due to a brand conflict. Failure
     aborts with `brand_reconciliation_failed`.

The card's `banned_terms` compile into a regex (`build_banned_regex`) used for
guardrail scanning throughout the rest of the run.

### SIE v1.4 zone targets
Per-zone × per-category targets (`entities` / `related_keywords` /
`keyword_variants`) are pulled from `sie.zone_category_targets` for the title,
H1, H2, H3, and paragraphs zones. H2 + H3 are combined into a "subheadings"
target for the heading optimizer. Reconciled terms are bucketed into entities,
related keywords, and variants for the downstream generators.

### Heading SEO optimizer (`optimize_headings`)
Rewrites the heading structure to weave reconciled terms toward the subheading
targets, while respecting forbidden terms (brand banned terms + SIE avoid
terms). Returns the optimized heading structure used for the rest of the run.

### Steps 1 & 2 — Title + H1 enrichment
The article's on-page **H1** and the SEO/meta **title** are distinct concepts:
- `title` = SEO/meta title (browser tab, SERP, og:title), preferring
  `brief.title`.
- `h1` = on-page main heading, preferring `brief.h1`.

When the brief supplies a title/H1, the Writer keeps it and only generates an
**H1 enrichment** line (`generate_h1_enrichment`). When the brief supplies
neither (very old briefs), it generates both the title and H1 in parallel and
promotes the generated title to the H1. Title and H1 are then scanned for
banned terms — a match here is a **hard abort** (`BannedTermLeakage`).

### Step 3.6 — Deterministic brand & ICP placement plan (`build_brand_placement_plan`)
Before any section LLM runs, the pipeline pre-assigns **exactly one** H2 to
anchor the brand mention and **exactly one** H2 to anchor the ICP callout,
using token-overlap scoring against client services / audience pain points /
verticals (no LLM call). Without this, every section sees the same soft
"mention 1–2 times somewhere" guidance and they all punt, shipping zero brand
mentions. The chosen anchors are recorded in metadata for editor override.

### Step 4 — Section writing (sequential per H2 group, `write_h2_group`)
H2s are grouped with their child H3s (`_split_h2_groups`; FAQ and conclusion
excluded) and written **one group at a time**. Each section prompt receives:
- **Global positioning:** the article title, all sibling H2 titles, and this
  section's index, so it knows where it sits in the outline.
- **Running cohesion context:** one-sentence summaries of every previously
  written section, so it can differentiate instead of repeating setups.
- An aspirational per-category term target, pro-rated by the section's share of
  the total body word budget.
- The citation pool, filtered terms, brand voice card, banned-term regex, and
  the placement directive for this H2 (if it is a brand/ICP anchor).

Body-level banned-term leakage is **warn-and-accept** (collected into
`banned_terms_leaked_in_body`); the section writer retries once internally but
the run does not abort on body leakage (distillation occasionally over-flags
common words like "leverage").

### Step 6 — Conclusion (`write_conclusion`)
Written **before** the FAQ (render order is body → conclusion → FAQ). It
receives one-sentence summaries of the body sections so it can synthesize what
was actually written.

### Step 5 — FAQ writing (`write_faqs`)
Written **after** the conclusion (standard article convention). Produces a
`faq-header` section plus one `faq-question` section per question.

### Step 4.3.1 — Intro, generated LAST (`write_intro`)
The intro is generated *after* body + conclusion + FAQ are finalized so its
Agree/Promise/Preview opening can preview **exactly** the H2s that exist —
eliminating the "intro promises 4, body delivers 8" drift. It is then
**inserted** right after the H1 (and optional H1-enrichment), not appended.

### Step R4 — Key Takeaways (`write_key_takeaways`)
Generated after everything else (so it can summarize the assembled article),
then inserted between the H1 enrichment and the intro. Final render order
becomes: **H1 → enrichment → Key Takeaways → intro → body… → conclusion → FAQ.**

### Order resequencing
Every section's `order` is re-stamped `1..N` by final list position. The
markdown renderer sorts by `order`, so this makes render order equal iteration
order and fixes the historical order-collision bug that put the intro
mid-body.

---

## 4. Post-generation validation & guardrails

These run after the article is assembled. With one exception, all are
**warn-and-accept** — they surface issues in metadata/logs for editor review
but never abort an otherwise-valid run.

| Step | Function | Behavior |
|---|---|---|
| Heading banned-term scan | `_scan_headings_for_banned` | **Hard abort** (`BannedTermLeakage`) — banned term in any heading, no retry |
| Article-structure validator | `_validate_article_structure` | Logs warnings: orphan ordinals ("Step 3" with no Step 1/2), intro position, missing conclusion, FAQ-before-conclusion |
| Step 6.7 — H2 body length | `validate_h2_body_lengths` | Retries under-length H2s once against `format_directives.min_h2_body_words`; warn-and-accept; re-scans headings |
| Step 4F.1 — Citation coverage | `validate_citation_coverage` | Detects citable claims (C1–C9); retries sections below 50% coverage once; auto-softens unsourced operational claims (C7–C9); never aborts |
| Step 7 — Citation reconciliation | `reconcile_citation_usage` | Builds the per-citation used/unused usage record |
| Format compliance | `_format_compliance` | Counts lists/tables vs. brief directives |
| Step 6.8 — ICP callout judge | `verify_icp_callout_landed` | One LLM call verifying the ICP anchor surfaced the callout (tolerates paraphrase); never aborts |
| Brand mention verification | `_verify_brand_mention_landed` | Checks the brand-anchor section body actually contains the brand name |

**Citation-coverage detail (Step 4F.1):** patterns C1–C6 (statistics, years,
source-attributed facts) are detected but **never auto-softened** — softening
would mangle them. The new operational patterns C7 (duration-as-recommendation,
e.g. "4-to-6 week refresh cadence"), C8 (frequency-as-recommendation), and C9
(operational-percentage) *are* softened to hedge phrasing when no citation can
be added on retry.

### Final cleanup
- **Em-dash sanitizer** (`_strip_em_dashes`): normalizes U+2014 to `-` across
  the title and every heading/body (LLMs emit em dashes despite instructions);
  word counts are recomputed.
- **Per-zone term usage** (`compute_term_usage_by_zone`): post-hoc breakdown of
  related-keyword / entity / variant usage across title, H1, subheadings, and
  body zones.

---

## 5. Failure modes & error codes

The router (`router.py`) maps exceptions to HTTP responses:

| Condition | Code | HTTP | Aborts run? |
|---|---|---|---|
| Banned term in title/H1/heading | `banned_term_leakage` | 422 | Yes |
| `brief_output` / `sie_output` not a dict | `invalid_brief` / `invalid_sie` | 422 | Yes |
| brief/SIE keyword mismatch | `keyword_mismatch` | 422 | Yes |
| Empty heading structure | `empty_heading_structure` | 422 | Yes |
| FAQ count outside 3–5 | `faq_count_invalid` | 422 | Yes |
| Distillation failed after retries | `brand_distillation_failed` | 422 | Yes |
| Reconciliation failed | `brand_reconciliation_failed` | 422 | Yes |
| Unexpected exception | `internal_error` | 500 | Yes |

Body-level banned-term leakage, under-length H2s, under-cited sections, and a
missing brand/ICP mention are **not** failures — they are recorded in metadata
for editor QA.

---

## 6. Key metadata for reviewers

`WriterMetadata` carries the editor-facing audit trail. Most useful fields:

- **Budget:** `total_word_count`, `word_budget`, `budget_utilization_pct`,
  `word_count_conflict`.
- **Coverage/quality flags:** `banned_terms_leaked_in_body`,
  `under_length_h2_sections`, `under_cited_sections`,
  `operational_claims_softened`, `no_required_terms`, `no_citations`.
- **Placement audit:** `brand_anchor_h2_text` / `_order`, `icp_anchor_h2_text`
  / `_order`, `icp_hook_phrase`, `brand_mention_landed`, `icp_callout_landed`
  (+ `icp_callout_evidence`, `icp_callout_judge_status`).
- **Sanitizer drops:** `duplicate_h2_headings_dropped`,
  `faq_like_h2_content_dropped`, `h3_children_dropped_under_h2`.
- **Versioning:** `schema_version`, `brief_schema_version`,
  `generation_time_ms`.

---

## 7. Quick reference — files

| File | Responsibility |
|---|---|
| `pipeline.py` | `run_writer()` orchestration — owns the whole process above |
| `router.py` | `POST /write` endpoint + error mapping |
| `title.py` | Title + H1 enrichment generation |
| `budget.py` | Word-budget allocation across sections |
| `distillation.py` | Brand voice card distillation (Step 3.5a) |
| `reconciliation.py` | SIE-term ↔ brand reconciliation (Step 3.5b) |
| `heading_seo_optimizer.py` | Heading rewrite toward SIE zone targets |
| `heading_sanitizer.py` | Step 0.5 structural cleanup |
| `brand_placement.py` | Step 3.6 deterministic brand/ICP anchor plan |
| `sections.py` | Per-H2-group section writing |
| `conclusion.py` / `faqs.py` / `intro.py` / `key_takeaways.py` | The named sections |
| `h2_body_length.py` | Step 6.7 length validator + one-retry |
| `citation_coverage_validator.py` | Step 4F.1 C1–C9 detection, retry, soften |
| `citations.py` | Step 7 citation-usage reconciliation |
| `icp_verification.py` | Step 6.8 ICP callout judge |
| `banned_terms.py` | Banned-term regex + leakage exception |
| `term_usage.py` | Per-zone term-usage analytics |
| `models/writer.py` | Request/response/metadata Pydantic schemas |
