# Local SEO Page Spec — length & structure as a kept, enforceable file (plan v1.0)

**Status:** approved 2026-09-02 (owner) — build in phases below.
**Owner decisions:** the spec format (§3) is the one shown from Wheelhouse IT Fort Lauderdale's stored reference structure, extended with min/max bands; the guardrails in §5 are the agreed set; no new prompt rules.

## 1. Why

Page length and structure have been a recurring defect on Local SEO pages. The SERP-length control (#781, 2026-08-27) and the three bypass fixes (#966, 2026-09-02) each closed a gap, but on the 15 pages that *did* get a target since Aug 27, only **1 landed within 10% of it**; the rest ran 16–33% over before any outage or time-budget starvation. That is the control loop's normal-case result, not a bug.

Root causes, measured:

1. **Length is requested, not enforced.** The writer gets a `TOTAL WORD BUDGET` line and every corrective step is another whole-page LLM rewrite that asks again. The only deterministic part is the measurement afterwards (`length_fit`).
2. **Three structure sources compete and the writer reconciles them in its head.** The nlp 12-section template carries absolute per-section counts whose *minimums* alone sum to ~1,900 words; the client's reference layout (`clients.page_structures`, rescaled by `page_structure_render.scale_analysis_words`) and "cover every competitor heading + information gain" sit on top; then hard count floors stack (multiple H2s, every sub-service as an H3, ≥4 FAQ, ≥4 benefit pairs, ≥3 differentiators). Those floors do not fit into a 1,300-word target.
3. **The gates are downstream and weak.** `length_fit` is 10% of the composite; the generate trim fires only ≥40% over; the reoptimize loop is composite-gated; a 25%-over page passes everything by design.
4. **The combined spec is thrown away.** The reference layout + SERP target are merged at generate time inside `generate_page` and never persisted — nobody can see what the writer was told, nobody can edit it, and it is rebuilt from scratch every run.

## 2. What exists (reuse, don't rebuild)

| Piece | Where | Reuse |
|---|---|---|
| Reference page structures per client × page type (outline, intents, blocks, exact per-section `word_count`) | `clients.page_structures` via `services/page_structure_scraper.py` | The **layout input**. Wheelhouse FL local landing: 38 outline rows / 972 words; FCR local landing: 22 / 2,358. |
| SERP analysis per keyword × location (`serp_avg_word_count`, `serp_word_target`, `competitor_headings`) | `keyword_analyses` via `services/analysis_cache.py` | The **length input**. |
| Deterministic outline extractor (`extract_outline_from_html`) + fidelity scorer | `services/page_structure_eval.py` | Measures the *generated* page per section. |
| Section-scoped edits (`split_sections` / `apply_section_edits` / `section_digest`) | `writer/nlp-api/section_edit.py` | Targeted trims by stable section key. |
| Deterministic length engine | `writer/nlp-api/length_fit.py` | Whole-page band scoring (kept). |
| Structure gate (keep-best regen vs reference) | `services/structure_gate.py` | Replaced on the Local SEO path by the spec gate (§6, Phase 2); untouched for Ecommerce. |

## 3. The spec (format)

One JSON document per **client × keyword × location**, produced by the analysis step, stored, downloadable, editable. Schema v1:

```json
{
  "schema_version": 1,
  "client_id": "…", "keyword": "roof restoration", "location": "Melbourne,Victoria,Australia", "location_code": 1000567,
  "page_type": "local_landing",
  "generated_at": "2026-09-02T…", "edited_at": null,
  "total": { "min": 1309, "target": 1571, "max": 1728, "basis": "serp" },
  "structure": { "max_sections": 12, "max_h3_per_h2": 6, "faq": { "min": 4, "max": 7 } },
  "sections": [
    { "key": "intro",        "level": "H1", "required": true,  "intent": "hero",
      "heading_pattern": "Exact keyword + 1–2 service entities", "min_words": 90, "max_words": 150,
      "blocks": [{ "type": "paragraph", "count": 3 }], "source": "template" },
    { "key": "usp",          "level": "H2", "required": true,  "intent": "value_prop", "min_words": 120, "max_words": 200, "blocks": [ … ], "source": "reference" },
    { "key": "services",     "level": "H2", "required": true,  "intent": "service_detail", "min_words": 500, "max_words": 760,
      "subsections": { "min": 3, "max": 6 }, "blocks": [ … ], "source": "reference+serp" },
    { "key": "faq",          "level": "H2", "required": true,  "intent": "faq", "min_words": 160, "max_words": 420, "items": { "min": 4, "max": 7 }, "source": "template" },
    { "key": "industries",   "level": "H2", "required": false, "intent": "coverage", "min_words": 0, "max_words": 60, "blocks": [{ "type": "list", "count": 1, "items": 12 }], "source": "reference" }
  ],
  "provenance": {
    "reference": { "page_type": "local_landing", "url": "…", "analyzed_at": "…", "total_words": 972, "usable": true },
    "serp":      { "keyword": "…", "location": "…", "analyzed_at": "…", "avg_words": 1309, "target": 1571, "competitor_pages": 15 },
    "template":  "local_landing_v13",
    "fallback_reason": null
  }
}
```

Rules that make it a spec rather than a measurement:

- **Ranges, not one number.** Page band: `min` = SERP average, `max` = target + 10% (the band `length_fit` already gives full credit for). Section bands allocated from the layout's proportions (§4).
- **Heading-only rows are folded into their parent** as a `list` block with `items` (Wheelhouse's 16 zero-word industry/testimonial headings). The writer never gets an empty-heading row to reproduce or pad.
- **Stable `key` per section** (the nlp `<section id>` vocabulary: `intro`, `usp`, `offers`, `cta-primary`, `features`, `services`, `testimonials`, `cta-secondary`, `getting-started`, `geo`, `faq`; reference-derived extras get a slug key). Keys are what the section-scoped trim addresses.
- **`required` flag.** Template must-haves (intro, both CTAs, geo, FAQ, schema) are required; reference-derived extras are optional.
- **`source` on every section** and full **provenance** so every number is traceable to the reference, the SERP, or the template.
- **Edits stick** (`edited_at` set): a re-analysis produces a new *candidate* spec and a diff; the edited spec stays active until the user accepts.

## 4. Building the spec (pure, deterministic)

`services/page_spec.py` (platform-api), no LLM, no I/O:

1. **Length band** from the SERP analysis (`serp_avg_word_count`, `serp_word_target`); when absent, the market fallback target from #966 (`basis: "fallback"`, `fallback_reason` set) — never no band.
2. **Layout** from the client's usable reference (`local_landing` preferred, else `location`), *validated* (§5.2); else the template's default section list.
3. **Normalise the layout:** fold heading-only rows into their parent; map each section to a template key via its intent (`hero→intro`, `value_prop→usp`, `cta→cta-primary/secondary`, `coverage→geo`, `faq→faq`, `service_detail→services`, `trust→testimonials`, `process→getting-started`, `objection/comparison/other→services subsections`); insert missing required sections.
4. **Allocate bands:** each section's share = its reference words ÷ reference total (template proportions when no reference); `min_words = share × total.min`, `max_words = share × total.max`, with per-key floors/ceilings so fixed-size sections stay sane (CTA 40–80, intro 80–160, FAQ items × 40–80). The main body (`services`) absorbs the residual so the sums close.
5. **Validate** (§5.1) and emit.

Every step is a small pure function with unit tests (`tests/test_page_spec.py`): fold, map, allocate, validate, measure, verdict.

## 5. Guardrails (all deterministic, in code)

### 5.1 Before writing — spec validation
- `Σ min_words ≤ total.max` and `Σ max_words ≥ total.min` (feasible), required sections present, count floors (FAQ ≥4, benefits ≥4) fit inside their section's `max_words` at a minimum words-per-item. An infeasible spec **fails loudly** (`page_spec_infeasible`) — it is never handed to the model to reconcile.

### 5.2 Before writing — input validation
- **Reference sanity:** usable only if `total_words ≥ 300`, `≥ 4` sections, URL not on a staging/dev host and not redirected; otherwise `provenance.reference.usable=false` + reason and the template layout is used. (Wheelhouse's `location` reference is 70 words / 9 sections; FCR's local landing is a staging URL.)
- **SERP sanity:** target requires `≥ 3` valid competitor pages (today ≥2) and must fall in `[900, 2500]`; outside → the fallback target + a `serp_target_suspect` flag on the spec for review.

### 5.3 During writing — structure caps
- `structure.max_sections`, `max_h3_per_h2`, `faq.max` are emitted into the prompt as hard caps AND measured after writing. Structural bloat is the second inflation source and nothing measures it today.

### 5.4 After writing — per-section measurement + targeted trim
- Measure the generated page per section (`extract_outline_from_html` keyed by `<section id>`); any section over its `max_words` gets a **section-scoped trim** (`section_edit.apply_section_edits`), ≤ 2 passes, with the LENGTH TRIM OVERRIDE (#966) scoped to those sections. The measure-and-trim step never yields to the time budget; only optional passes do.
- Any later pass (voice, SEO) is section-scoped, re-measured, and **rejected if it pushes a section or the page outside its band** (keep-best on length as well as score).

### 5.5 At save — hard ceiling + honest status
- A page still over `total.max × 1.15` after trims is saved with `length_status = "over_length"` + a `content_over_length` warning notification, never as a clean page. Within band → `"in_band"`; under `total.min` → `"under_length"` (advisory).
- The page row records `page_spec_id` + `spec_version`, `target_words`, `actual_words`, `length_status` so target vs actual is a column, not buried in `engine_scores`.

### 5.6 Operational
- **Edits stick; re-analysis diffs.** `PUT …/page-spec` marks `edited_at`; a re-analysis stores a candidate and the UI shows the diff.
- **Drift report:** per client, target vs actual over the last N pages + per-section overage frequency (`GET …/local-seo/length-report`), so the next regression shows in a table.
- **No new prompt rules.** The template's absolute per-section counts become proportions consumed *through the spec*; the prompt receives the spec's per-section bands, not a second set of numbers.

## 6. Phasing

| Phase | Scope | Deliverable |
|---|---|---|
| **0** | Pure core: `services/page_spec.py` — schema, fold/map/allocate/validate, `measure_page`, `length_verdict`; unit tests. | Module + tests. No behaviour change. |
| **1** | Persistence + API: `local_seo_page_specs` table (client × keyword × location, versioned, `edited_at`); build-on-analysis (`generate_page` builds/loads the spec and threads it), `GET/PUT/POST-rebuild …/local-seo/page-spec` + JSON download; spec id/version + target/actual/status columns on `local_seo_pages`. | Spec kept on file; visible via API; pages record target vs actual. |
| **2** | Enforcement: nlp `GeneratePageRequest.page_spec` (rendered per-section bands + caps replace `reference_page_structure` + the budget line on the Local SEO path); per-section measure + section-scoped trim after writing and after every later pass; save gate + `over_length` notification. Reoptimize consumes the same spec. | Pages land in band by construction; over-length never ships silently. |
| **3** | Frontend: spec viewer/editor + download on the page/New form; Saved Pages target-vs-actual column + status chip; per-client length report. | Team can see, edit, and monitor. |

Blog/service/ecommerce writers are out of scope for v1 (they keep `page_structure_render`/`structure_gate`); the schema is generic so they can adopt it later.

## 7. Acceptance test

On a run of 10 fresh Local SEO pages across ≥2 clients after Phase 2:
- ≥ 9 of 10 land inside `[total.min, total.max]` on the deterministic body count (today: 1 of 15 within 10% of target);
- 0 pages saved as clean while over `total.max × 1.15`;
- every page row carries a `page_spec_id`, `target_words`, `actual_words`, `length_status`;
- composite and voice scores do not regress vs the #792 baseline (voice 83.5 / composite 84.4 on FCR "roof restoration") by more than 2 points on the same keyword.

Measured with the eval CLI (`scripts/eval_page_structure.py`, extended to read the spec) on live-generated pages — the sandbox can't call the live LLM/SERP stack.

## 8. Decisions log
- 2026-09-02 — spec kept **per keyword × location** (SERP length differs per query); the per-client reference stays the layout input. Owner.
- 2026-09-02 — edits stick until the user accepts a re-analysis diff. Owner.
- 2026-09-02 — no new prompt rules; every guardrail is a deterministic check in code. Owner.
