# Local SEO writer — adherence learnings (length, structure, intent, sentiment)

**Date:** 2026-09-02 · **Status:** applied suite-wide (every rule below is general code, gated by nothing client-specific) · **Evidence client:** WheelHouse IT Fort Lauderdale (five live runs in one day) · **Authority for the mechanism:** `docs/modules/local-seo-page-spec-plan-v1_0.md`.

This is the team-facing summary of what one day of live runs taught us about making the Local SEO writer *obey* a length, a structure, a per-section intent and a positive sentiment — and which of those lessons are now rules in code for **every** client. Nothing in this list is special-cased to Wheelhouse; the client was the test bench.

## 1. What actually controls adherence (the rules now in force)

| # | Lesson | Rule now in code (all clients) |
|---|---|---|
| 1 | A number the writer is *asked* for is not a number the page *lands* on. Prompt-only length requests produced 1 in-band page out of 15. | One kept, versioned **page spec** per client × keyword × location (`local_seo_page_specs`): page band + per-section min/max + structure caps. Measured per `<section id>` after writing; only over-band sections are trimmed (section-scoped, ≤2 passes, never gated on the time budget). Saved honestly (`length_status`) + notified when still over the ceiling. |
| 2 | A "suspect" SERP target can feed itself back as "the market". | The market fallback only counts targets inside the plausible window and the band clamps into it (`fallback_target_clamped`). Live: a 2,782-word suspect target came back as a 2,782-word fallback → band 2,318–3,060; now 2,083–2,750. |
| 3 | Three structure sources competing (template, client reference, competitor headings) = no structure. | ONE structure per spec. **The client's reference layout overrides the template** whenever a usable reference is on file (`structure_mode: client`): client sections, client order, no template insertions; omissions recorded (`client_structure_omits`). Template mode only when no usable reference. |
| 4 | Structure has to be *checked*, per section, and *fixed* in place — not regenerated whole. | `structure_verdict` (required sections, order, caps, block composition, item bands, sub-section bands) + a section-scoped loop: reorder / drop extras (deterministic), WRITE missing required sections in, rewrite ONLY sections with a named issue. Keep-best by blocking-issue count. Persisted as `structure_status` + `structure_issues`, notified on drift. |
| 5 | Intent + sentiment need a judge, but a judge needs the band. | One cheap Haiku audit per pass judges every section's assigned intent by **what the copy does** (never heading wording) and **within its own word band** (two short quotes complete a 50-word testimonials block); **only `positive` sentiment passes** (neutral fails). The verdict that ships is re-audited if a later voice/SEO pass changed the text. |
| 6 | The writer cannot reproduce what it is only told the *count* of. | The client's own list items (industries served, service lines — the reference page's folded sub-headings) ride on the spec as `list_items`; the spec block and the fix pass tell the writer to reproduce every one. (Industries list: 5–8 of 13 before this; verified on run 5.) |
| 7 | A section made mandatory by the client's page but impossible from the data must not be faked. | Testimonials with no reviews on file → optional + "OMIT" (never invent quotes); its minimum is released to the page, not to another section. Pulling reviews (`review_intel`, which now backfills `clients.gbp.reviews`) rebuilds the spec with it required. |
| 8 | Reference layouts carry markup noise. | A nav heading with one empty child is dropped; a lone H3 in a short block gives no sub-section band (≥2 prose H3s do); a ceiling clamp never collapses a band to a point; extra sections are advisory under the cap (template mode) and drift in client mode. |
| 9 | Semantic mislabels in the reference analysis leak into the page. | A "coverage" section maps to the template's geographic slot only when it names places; "industry coverage" is its own section (owner ruling). |
| 10 | Anything the verdict enforces must be part of "did the spec change". | Structural asks (sub-section/item bands, blocks, list items) are in the material-difference signature; an unedited spec rebuilds when they change, an edited spec always sticks. |
| 11 | Proportional scaling has no floor: a long reference on a short SERP scales widgets into nonsense (Winter Park: testimonials 6–7 words, a 13-item services block in 22–28). | **Feasibility floors** (2026-09-03): a client section's minimum is never below 80% of its own reference words nor below its structural floor (items × 4, H3s × 25, quotes × 20, prose ≥ 30, FAQ words-per-item); when the required floors exceed the SERP band the **page band lifts to them** (`client_length_over_serp`) — the client's length wins over the SERP average whenever the reference is the longer. The lifted target also drives the writer's budget line and the `length_fit` engine (`_with_spec_length`) — the first lifted run scored length_fit 0 against the SERP it deliberately exceeded. |
| 12 | The loop only trimmed; a floor nothing enforces is a wish (5 of 5 Fort Lauderdale runs landed under the minimum). | A section-scoped **deepen pass** (`_spec_deepen_inline`, ≤`PAGE_SPEC_DEEPEN_PASSES`=2, keep-best on the total shortfall, not time-budget gated) writes substance — competitor entities/topics from the SERP analysis, delivery specifics, local anchors, the client's list items — into REQUIRED under-band sections, never invents facts, never pads; one closing trim if it overshoots. |

## 2. The measured trajectory (one keyword, same SERP, same reference)

| Run | Spec | Words | Band | Structure issues | Composite / voice |
|---|---|---|---|---|---|
| 1 | v1 (suspect fallback) | 2,048 | 2,318–3,060 | 5 | 78.6 / 80.6 |
| 2 | v2 (clamped; reviews on file) | 2,074 | 2,083–2,750 | 3 | 78.2 / 76.8 |
| 3 | v2 (audit-in-band live) | 2,173 | 2,083–2,750 | 3 | 82.5 / 83.1 |
| 4 | v3 (no lone-H3 band) | 2,044 | 2,083–2,750 | 1 (industries 5/13) | 81.9 / 81.7 |
| 5 | v4 (list items; own industries section) | 1,963 | 2,083–2,750 | 2 (industries 10/11; testimonials thin) | 76.9 / 80.8 |

Cross-client batch (2026-09-02, same code): First Class Roofing "roof restoration" (template mode, no usable reference) 1,344 words in band 1,309–1,728, structure ok, 85.0 / 79.4; Wheelhouse Orlando "IT Support Company Winter Park" (client mode) 1,055 words in band 882–1,164 but 7 structure issues, every one downstream of the infeasible bands rule 11 now fixes.

Every run kept the client's 11 sections in the client's order and quoted a real review once reviews were on file. Cost ≈ $0.63 per run, ≈ 11 minutes.

## 3. What is NOT yet general (open, with the evidence)

- **Under-band pages — now built (rule 12).** Five of five Fort Lauderdale runs landed under the minimum (run 5: 1,963 vs 2,083) and the cross-client batch showed the same habit on First Class Roofing (in band but at the bottom) — a writer habit, not a client artefact. The deepen pass is the mirror of the trim; measure its effect on the next runs (expect in-band pages and a small cost increase per page).
- **Long reference on a short SERP — now built (rule 11).** Winter Park (Orlando reference 2,287 words, suburb SERP 882–1,164) produced 7 drift issues, all downstream of infeasible bands. Under the floors its band lifts to roughly 1,830–2,420 words; the page runs ~2× the competitor average by design.
- **Reference quality is the ceiling.** First Class Roofing's reference is a staging host → unusable → template mode. A client only gets the client-structure benefits with a usable reference (live host, ≥300 words, ≥4 sections). Operational: add one per client; the spec panel says when it is missing.
- **The reference analysis stores counts, not content.** List items are recovered from folded *headings*; a real `<ul>` on the reference page still yields only an item count. Capturing list item text at scrape time (`page_structure_eval`) would extend lesson 6 to every list.
- **Acceptance at scale.** Plan §7 (≥9 of 10 fresh pages in band, 0 clean saves over the ceiling) is measured on one client so far. The per-client length report (`GET …/local-seo/length-report`) gives the number; a cross-client rollup does not exist yet.

## 4. Where to look

- Spec + verdicts: `writer/platform-api/services/page_spec.py` (vendored into `writer/nlp-api/page_spec.py`, sync-guarded), store `page_spec_store.py`, wiring `local_seo_service.py`.
- Enforcement loops: `writer/nlp-api/main.py` — `_enforce_spec_structure` (audit → deterministic fixes → add → fix), `_enforce_spec_length` (section-scoped trim, then deepen, then a closing trim), `_final_structure_verdict`.
- Reviews: `services/review_analytics.py` (`review_intel` job; backfills `clients.gbp.reviews`), `services/dataforseo_reviews.py` (live rating shape).
- UI: `frontend/src/components/localseo/PageSpecPanel.tsx` (spec viewer/editor, length + structure chips, issue list).
