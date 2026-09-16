# Topic-Vector Centering + Information Gain — Module Plan v1.0

**Status:** Design locked. **P0 built (report-only, 2026-09-16)** + **P1 built (2026-09-16)** — the per-client site claim index + the scored Information Gain dimension, coached into the ecommerce reopt loop at **composite weight 0**. Gated on `GEMINI_API_KEY` (embeddings) + `topic_vector_gain_enabled` (the index build); the deterministic `_compute_serp_signal_coverage` engine is byte-identical (untouched). **P0 live-validated on the deployed nlp service (2026-09-16):** the Nova "buy retatrutide" drift page centred **0.747** vs a strong on-vector competitor PDP **0.845** (§14 acceptance #1 met, centering separates the pair), and the floors were **calibrated from the run** — gemini-embedding-2 cosines run high/compressed (per-subtopic best-section 0.67–0.81 with no clean covered/missing gap), so `CENTERING_FLOOR` 0.45→0.60 and `COVERAGE_FLOOR` 0.55→0.70 (the old 0.55 marked everything "covered" → an empty inverse gap). **P2 (emotional-arc rubric) BUILT (report-only, 2026-09-16)** — the subordinate-tail LLM rubric (§10a) seeded from the voice card's audience fields, riding on the report-only `topic_vector.emotional_arc` sub-object at composite weight 0 on the three scorers; one cheap Haiku forced-tool call, best-effort, suppressed (never 0) when there are no audience fields, and scrubbed of `never_use_terms`; live LLM validation post-deploy (see §12). This doc remains the design authority.
**Review:** Adversarially reviewed 2026-09-15; corrections folded in — the 11–20 tier is already-scraped (not an extra fetch), the site claim index is a cross-service platform→nlp integration, the measure runs *beside* the deterministic engine (not folded in) and is gated on `GEMINI_API_KEY`, plus empty-state / absent-AIO handling and acceptance criteria (§14).
**Scope + governance (2026-09-16):** generalized to all content types (§10a — intent-lane-by-page-type, one-arc-per-awareness-stage, the voice-card-seeded emotional arc kept as the subordinate tail) and given an explicit brand-guide precedence rule (§10b).
**Origin:** A reoptimize discussion on the Nova Life Peptides "buy retatrutide" page (page `22c93b10-…`, 2026-09-15, composite 58.8/fail) surfaced two blind spots in ecommerce page scoring: (1) we don't measure whether a page is *semantically about the right thing*, and (2) we don't measure whether it *adds anything the ranking set doesn't*. This module adds both, on top of the existing MCS embedding machinery.

---

## 1. Why

Today's scorers measure **per-term coverage** (keywords / entities / bold terms via `_compute_serp_signal_coverage`) and **qualitative depth** (LLM engines). Two gaps, both proven on the Nova run:

- **No topic-vector measurement.** The page scored `entity_coverage: 75` while the entity target set came back *empty* (`entity_detail: []`) — a hardcoded default (`main.py:4963-4965`), not a measurement. The page had drifted onto a "trustworthy verified vendor" topic vector (its voice card's must-use terms are all COA/HPLC/batch-integrity) and off the *compound* vector (receptor 3/13, metabolic 0/9, triple-agonist 0/4). Nothing flagged it.
- **No information-gain measurement.** Nothing rewards saying something the ranking set doesn't, or flags a page that merely restates the consensus.

Both matter more here than usual because the client's brand guide **forbids the product's own name** ("retatrutide" is in `never_use_terms`; the product is coded "GLP-3RT"). Per-term keyword matching is structurally unwinnable. Embedding-based topic centering and site-grounded information gain are **name-agnostic** — they reward covering the compound's neighborhood and adding real first-party facts, name or no name.

## 2. Core model

Four signals, three from a shared embedding pass, one from an LLM rubric:

1. **Topic centering** — is the page on the explicit-query vector? (cosine vs a centroid)
2. **Per-subtopic coverage** — which competitor subtopics does the page semantically cover / miss?
3. **Information gain** — does the page add on-vector, site-grounded claims the ranking set lacks? (its own 0–100 score)
4. **Emotional-arc resolution** — does the page move the buyer from anxious→confident? (LLM rubric dimension — embeddings capture topic, not affect, so this is deliberately *not* in the cosine)

## 3. The competitor corpus — three tiers

All three tiers come from the SERP **we already scrape today** — there is **no extra fetch**. `SERP_RESULT_COUNT = 20` (`main.py:1208`) and `_run_serp_analysis` scrapes every returned URL, so positions 11–20 are already fetched and already folded into today's competitor targets. The current pipeline just doesn't *retain SERP rank position*: `competitor_headings` and entity targets are aggregated across all ~20 pages with no tier (`main.py:2824-2846`). So the real (cheap) work is **retaining each scraped page's rank and partitioning the already-scraped set** — not a second scrape. (Corollary: today's targets already span ~20 pages, so anchoring the centroid on the **top-10 only (§4) is a deliberate *narrowing* of current behavior** for a cleaner consensus signal, not an addition.)

| Tier | What it is | Role |
|---|---|---|
| **Top 10** | consensus / table stakes | defines the centering centroid + must-cover baseline |
| **11–20** | on-vector angles the winners skip | *differentiation-within-reach* candidates |
| **Neither tier, but site-grounded** | first-party facts nobody ranking states | *true information gain* |

11–20 guards (so page-2 junk doesn't leak in): a subtopic must appear on **≥2** of the 11–20 pages **and** clear the centering floor before it becomes a target.

## 4. Measure 1 — Topic centering

**The centroid is anchored on the EXPLICIT query only:** `explicit query terms + AIO text + top-10 competitor headings`. For a transactional "buy / where to buy" query these signals are already commercial, so the centroid's center of mass lands on **the offer** (product identity, price, sizes, stock, purchase mechanics, COA-as-purchase-gate) by construction — no hand-weighting needed. (For non-ecommerce page types the same construction holds, with the page type declaring the intent lane — see §10a.)

**The implied query is deliberately NOT in the centroid.** It lives one layer down (§5), as coverage checklist items only. This is the load-bearing decision: it makes the implied/emotional layer structurally incapable of pulling the vector off "where to buy." A mechanism essay with no commercial core scores *low* on centering, correctly.

**AIO is often absent — the centroid must degrade explicitly.** Many commercial SERPs return no AI Overview (`aio_present` is a real boolean; `_run_serp_analysis` sets AIO empty when URLs are supplied manually — `main.py:2668`). When AIO is missing the centroid falls back to *explicit query + top-10 headings*. A centering score is therefore only comparable across pages with the **same AIO availability** — never rank an AIO-present score against an AIO-absent one on one scale.

**Score:** `cosine(page_embedding, centroid)`. Reported as a drift alarm ("this page slid toward vendor-trust and off the commercial vector"). Because whole-doc cosine saturates and is forgiving (the lesson already burned into the Fan-out source guard and Keyword Research relevance gate — cosine alone drifts), this single number is a coarse gauge; the actionable detail comes from §5.

**Related finding (adjacent, separately fixable):** `_compute_serp_signal_coverage` has no `never_use_terms` awareness, so it scores the page against `retatrutide` (34 kw + 66 bold shortfall) and its recommendations literally say "add retatrutide" — which voice enforcement then strips, every pass. Excluding `never_use_terms` from the coverage targets is a small, separate change worth doing regardless of this module.

## 4a. Title centering — the heaviest single signal

The `<title>` carries disproportionate weight for both Google and the embedder, and for a "buy" query it is the most important element on the page. The plan treats it explicitly:

- **Weight the title zone in the centering score.** A generic or off-vector title under-centers the whole page regardless of body coverage. (Live example: Nova's `Buy GLP-3RT Research Peptide | Nova Life Peptides` — leads with "Buy" correctly, but carries the coded name instead of the entity every competitor titles with, and none of Nova's own verification edge.)
- **Capture competitor titles as a first-class signal.** Today we surface competitor *headings* (H2/H3) but not competitor *titles* — so the writer gets per-keyword title-zone counts, never "here's how the top-10 title their pages." No extra network is needed (titles ride in the same DataForSEO SERP response), but note they're currently *parsed then discarded*: `fetch_serp_urls` uses titles only for bold-term extraction and returns `(urls, bold_terms, aio)` (`main.py:1294-1298`), so capturing them is a small return-shape change threaded through `serp_analysis`, not a free read. Surface them as a pattern target alongside headings, and fold their tokens into the centroid.
- **The `never_use_terms` cap bites hardest here.** The title is the one place the entity matters most and the one place it's forbidden. There's no full fix; the coded-name title will under-perform for the branded query. The available lever is to win the title on the **commercial + differentiation axis** (buy · sizes · purity · COA/verified) rather than the entity name — the information-gain edge (§6) applied to the title.

## 5. Measure 2 — Per-subtopic coverage

Cluster the competitor headings (top-10 + qualifying 11–20) into subtopics; embed each subtopic; for each, take the page's **best-matching section's cosine**. A subtopic the page is semantically far from is the gap — regardless of exact wording. This is the semantic version of the (never-built) subtopic-coverage engine and the correct home for the **implied-query brief**: one cheap Haiku call (same shape as `keyword_research_topics`'s intent fan-out) emits `{implied_query, job_to_be_done, desired_outcome, must-answer sub-questions}`, and those sub-questions become *additional* coverage checklist items — additive only, never centroid inputs.

Output: per-subtopic covered/missing, biggest gaps first. This is the day-one actionable surface.

## 6. Measure 3 — Information gain (the scored one)

**Unit = a claim, not a section.** Reuse claim/fact extraction (`ecommerce_facts.py`, MCS `parse_facts`).

**A claim counts as gain only if ALL three hold:**
1. **On-vector** — clears the centering floor (gain that serves the *buy*, not an off-vector mechanism tangent).
2. **Rare in the top-10** — stated by ≤1 of the consensus set (a fact everyone has isn't gain; claim-level page-spread).
3. **Site-grounded** — corroborated in the client's **site claim index** (§7). A claim grounded nowhere on the client's own site was introduced from thin air → **scores zero and is flagged**, never credited.

Guard #3 is the anti-fabrication mechanism. Without it, scoring information gain creates a direct incentive to invent specs/claims — unacceptable in a YMYL-adjacent peptide context where `ecommerce_facts` already hard-excludes clinical/dosing/FDA claims. **Gain must be sourced, not generated.**

**Score (own 0–100 dimension, beside the composite — like the voice scorecard):**
- **Realized gain** — count of on-vector, top-10-rare, site-grounded page claims, normalized to a small target (≈3 differentiating grounded facts = full marks).
- **Captured differentiation** — of the §3 tier-2 (11–20) differentiation-within-reach subtopics, how many the page covers.
- **Inverse (reported, not scored)** — the on-vector claims the *corpus* states that the page lacks. Trustworthy with no fabrication risk (grounded in what competitors demonstrably said); this is the finest-grained coverage gap and the most actionable output.

**Weighting decision (locked):** Information Gain is a **separate, prominent score, coached into the reopt loop as guidance ("add these specific site-grounded facts; cover these under-served subtopics"), with LOW-or-ZERO composite weight.** Reason: if gain were heavily weighted *and* the reopt loop optimizes the composite, we'd rebuild the fabrication incentive as a gain *quota* the model strains to fill. A solid table-stakes PDP with a real offer must be allowed to score fine without heroic novelty; gain is the edge, surfaced and coached — not a gate that forces invention.

**Empty-state + cross-vocabulary handling (post-review):**
- **Thin/absent site index → suppress, don't zero.** When the site claim index is empty or thin (new client, or a JS-only / sitemap-less site — `site_page_index` degrades to an empty index best-effort), *every* page claim is ungroundable, so gain would read a misleading `0` and the coaching would have nothing to draw from. In that state, **suppress the gain score ("not measured")** rather than report 0, and don't coach ungroundable additions.
- **Coded-name ≠ competitor-name in the rarity test.** The "rare in top-10" check compares the page's claims (using "GLP-3RT") to competitor claims (using "retatrutide"). Rarity **must** be judged on the claim *predicate* via embedding, not surface tokens — otherwise a coded-name claim looks absent from competitors and is falsely credited as novel. Validate on the Nova pair ("GLP-3RT is a triple-agonist" vs "retatrutide is a triple-agonist" must read as the *same* claim); name-agnostic matching is the module's whole premise, so this is a build-time must-verify, not an assumption.

**Properties to remember:** gain is corpus-relative (a snapshot — re-running over time shows an eroding edge as competitors catch up) and only credits *rare* claims (claim-level page-spread).

## 7. The site claim index — the module's primary integration

The grounding corpus. Per-client, cached, refreshed periodically.

- **Cross-service (load-bearing):** `site_page_index` lives in **platform-api** (`writer/platform-api/services/site_page_index.py`); the scorer that needs the index lives in **nlp-api**, which has *no* access to it (nlp is private/auth-less and receives its inputs — e.g. `serp_analysis` — from platform-api in the request body). So the index is **built and cached in platform-api and passed to nlp in the score/reopt request payload**, the same way `serp_analysis` already is. This cross-service data flow — not the `discover_site_urls` call — is the bulk of the real work.
- **Discovery:** reuse `site_page_index.discover_site_urls` (sitemap → DataForSEO `site:` fallback).
- **Granularity (locked): STRUCTURED FACTS**, not claim-sentences. A per-fact extractor pulls typed facts from the site (price, purity, COA presence/access, molecular identifiers, shipping/returns terms, policies, product identity). Stronger grounding than fuzzy sentence-cosine; a page claim is credited only when it matches a structured fact the site actually asserts.
- **Matching:** a page claim → the index by fact-type + value agreement (embedding cosine assists fuzzy matches; typed comparison for numerics/prices).
- **Name-agnostic:** the site says "GLP-3RT" and carries its specs, so grounding credits the coded-name facts fine.

This is the module's **primary integration**, not a reuse line — design it most carefully (extractor coverage, the platform→nlp payload contract, refresh cadence, staleness). The embedding/cosine/discovery *primitives* are reuse; wiring them into the scoring path across the service boundary is new.

## 8. Reuse map

| Need | Reuse |
|---|---|
| Embeddings + cosine (primitives) | `ecommerce_mcs.py` `cosine`, injected `EmbedFn` (Gemini `gemini-embedding-2`) — **wired into generate/reopt only today, NOT the scoring path; gated on `GEMINI_API_KEY`** (see §9) |
| AIO + competitor headings | already in `serp_analysis` (`aio_text`, `competitor_headings`) — competitor *titles* are NOT (see §4a) |
| Implied-query brief | Haiku intent fan-out, same shape as `keyword_research_topics` |
| Claim/fact extraction | `ecommerce_facts.py`, MCS `parse_facts` |
| Site discovery | `site_page_index.discover_site_urls` — **platform-api only; scorer is nlp-api** (cross-service, see §7) |
| Genuinely new | the per-client **structured-fact site claim index** + its platform→nlp payload contract |

## 9. Where it slots

Ecommerce scorer first (`/score-ecommerce-page`, `/reoptimize-ecommerce-page`), then the Local SEO / service / blog scorers.

**All three measures run as a SEPARATE async pass beside the composite — NOT folded into `_compute_serp_signal_coverage`.** That engine is a synchronous, network-free `def` whose docstring is an explicit contract — *"Runs in Python — not scored by Claude — so results are precise, reproducible, and cost no extra tokens"* (`main.py:4826-4830`, called synchronously at `5350 / 8023 / 11405 / 11687 / 11924`). Centering / coverage / gain are embedding-based: network-bound, non-reproducible run-to-run, and cost+latency-bearing. Folding them in would break all three of that engine's guarantees, so they sit **beside** it as an async measure that emits its own scores, leaving the deterministic engine byte-for-byte untouched.

**Dependency:** the whole measure is gated on **`GEMINI_API_KEY`** on the nlp service (the embedder is dormant without it — `main.py:190`; set in prod today). No key → the measure is skipped, not defaulted to a number. Budget the embedding calls per score (page + centroid components + per-subtopic + claims) — new per-score cost the deterministic engine never carried.

The reopt loop consumes the per-subtopic gaps + gain guidance as rewrite targets.

## 10. Guardrails

- **Fabrication:** gain credited only for site-grounded claims; ungrounded novelty scores zero and is flagged. Composite weight kept low/zero so no gain quota.
- **Name-agnostic:** embeddings + site-grounding both work under `never_use_terms`; the module is the intended answer to the forbidden-name problem (predicate-based claim matching, §6, is the build-time must-verify).
- **Centering gates gain:** novelty is only "gain" inside the topic vector — off-vector novelty (vendor-trust boilerplate) is not rewarded.
- **Emotional arc stays in the LLM rubric,** never the cosine.
- **Deterministic engine untouched:** the new measure sits beside `_compute_serp_signal_coverage`, never inside it (§9).

## 10a. Scope across content types

The module was designed general and only *illustrated* with the Nova ecommerce PDP. It applies to **all clients** and **all content types** (ecommerce, Local SEO, service, blog) because it keys only on the SERP, the client's site, and the voice card's `never_use_terms` — nothing client- or vertical-specific. Caveats: gated on `GEMINI_API_KEY` (§9); information gain needs a usable client site (else suppressed, §6); Local SEO lands in an already-crowded scorer (the page-spec / structure-and-intent layer), so integration there is additive-but-careful (topic vector and structure are different axes — no conflict).

**Intent is a per-page-type input, not a SERP guess.** For a money page (local landing, service, PDP) the intent *lane* is **declared** transactional by the page type — not deferred to a possibly-mixed SERP. The SERP informs the topic **neighborhood** (which subtopics exist); the page type fixes the **lane** (this is a sales page, not a guide). So informational competitors that rank for a `<service> <city>` query inform coverage but never pull the centroid into an informational lane. For a genuinely intent-ambiguous query the centroid can still self-discover intent from the SERP, but a declared page type always wins.

**One page = one awareness stage = one arc.** A page serves a single audience awareness stage:
- **Provider-aware** ("roof restoration melbourne", ready to hire) → the money page.
- **Problem-/solution-aware** ("do I need roof restoration", "restoration vs replacement", "cost") → its own TOFU/MOFU blog/guide, which runs its *own* before/after arc and **hands off** to the money page via internal link + CTA.

The keyword signals the stage (and its SERP differs accordingly), so a keyword routes to the right page type. Enforced by centering: a full education section on a money page reads as drift off the transactional centroid — the model turns "landing page or blog post?" into a *measurable* question, not a judgment call. **Exception:** a *light* touch of the earlier question belongs on the money page as **trust** ("not sure if you need repair or replacement? we assess honestly"), because it defuses the provider-aware buyer's upsell fear — a sentence or short block won't move the centroid; a 400-word treatment will and belongs on the blog. This is the pillar-cluster architecture the suite already has (topic-strategist pillars→clusters, the Website Builder content plan); the module's contribution is keeping TOFU education off the BOFU money page.

**Emotional before/after arc — derived from the voice card, kept as the tail.** With intent and audience fixed, the before→after states fall out of the client's **already-auto-generated** voice card: **before** = `audience_pain_points` + `audience_objections` + `audience_triggers`; **after** = `audience_motivations` satisfied + objections answered. The emotional-arc rubric checks the page performs that transition for *this* client's audience. It stays the **subordinate tail** of the model — an LLM rubric dimension, never in the cosine, never a heavy composite weight — because affect isn't embeddable and over-indexing it recreates Nova's failure in reverse (a warm page that's off-vector and doesn't rank). **MCS-first, always:** centering + coverage + gain are the scored spine; the implied-query brief adds only coverage-checklist items; the emotional arc is one soft rubric dimension.

## 10b. Brand-guide precedence

Topic vector and the brand guide are **mostly orthogonal** — *what the page is about* vs *how it's expressed / what it may say* — so a subtopic gap and a voice rule are usually both satisfiable. The narrow real conflicts resolve by a fixed precedence:

- **Hard brand constraints are inviolable.** `never_use_terms`, RUO/compliance, no-medical-claims — the module never pushes against them, by construction: centering is name-agnostic (credits the neighborhood without the forbidden term), information gain is site-grounded (can't credit a fabricated or forbidden claim), and coaching never names a forbidden word (§13 finding 1). There is **no "topic vector overrides the guide" path.**
- **The forbidden-term-is-the-anchor residual is surfaced, not resolved.** When the topic anchor is a forbidden term (Nova's "retatrutide"), the module gets as close as the neighborhood allows and makes the *residual* ranking gap (the name is the strongest title/exact-match signal) **visible and measured** — a strategy decision, never auto-fixed.
- **Guide-caused drift is surfaced as a separate score, human-resolved.** When following the guide's voice/positioning pulls the page off-topic (Nova's must-use verification terms → the vendor-trust vector), the module neither overrides the guide nor silently follows it off-vector — it reports voice and centering as **separate scores** (both visible, the way the voice scorecard already sits beside the SEO composite), so the tension is legible and a human/strategist rebalances. `force_voice` remains the explicit human override on publish.

The module largely **consumes** the brand guide as input (`never_use_terms` → excluded targets; voice-card audience fields → the emotional arc), so guide and module are collaborators: the guide says what not to say and who the reader is; the module says when following the guide has pulled the page off what actually ranks.

## 11. Decisions

**Locked:**
- Centroid = explicit query + AIO + top-10 headings; implied query demoted to coverage checklist only.
- Fork 2 (per-subtopic semantic coverage) is in.
- 11–20 headings partitioned as a distinct "differentiation-within-reach" tier from the **already-scraped** set (no extra fetch), gated by ≥2 page-spread + centering floor.
- Information Gain = separate prominent score, coached into reopt, low/zero composite weight.
- Site claim index granularity = **structured facts.**
- Ground truth = the client's whole site.
- Centering / coverage / gain run as a **separate async measure** beside the composite, gated on `GEMINI_API_KEY` (§9) — never folded into the deterministic engine.
- Applies to **all clients + all content types**; intent *lane* is declared by page type (money pages = transactional), the SERP informs the neighborhood not the lane (§10a).
- **One page = one awareness stage = one before/after arc**; earlier-funnel stages get their own TOFU/MOFU asset that hands off via internal link (light trust-framing exception aside) (§10a).
- Emotional before/after arc is **derived from the voice card's audience fields** and stays the subordinate tail — MCS-first (§10a).
- **Brand-guide precedence (§10b):** hard constraints (`never_use_terms`/compliance) inviolable — no "topic overrides guide" path; soft voice-vs-topic tensions surfaced as separate scores + human-resolved; the module never coaches a forbidden/non-compliant addition.

**Open:**
- Structured-fact extractor scope (which fact types v1) + refresh cadence for the site index + the platform→nlp payload contract shape.
- Exact centering-floor + rare-in-top-10 thresholds (calibrate from real runs, like every other floor in this codebase).

## 12. Phasing

- **P0 — report-only. ✅ BUILT (2026-09-16).** Centering score + per-subtopic coverage + the inverse gain gap (competitor claims the page lacks). No score fed to reopt yet. Cheapest, safest, immediately useful; validates the centroid + clustering before anything optimizes against them. (The 11–20 tier here is a re-partition of the already-scraped set — see §3 — not new I/O.) *As built:* pure logic in `writer/nlp-api/topic_vector.py` (tiering / clustering / centroid / coverage math), the async orchestrator `topic_vector.measure` gated on `GEMINI_API_KEY` (reusing `ecommerce_mcs.cosine` + the `_gemini_embed` EmbedFn), rank retention threaded through `scrape_urls`→`_run_serp_analysis` (new `competitor_heading_tiers` on `AnalysisResponse`), and a report-only `topic_vector` field on the ecommerce score + reoptimize responses. `_compute_serp_signal_coverage` untouched. Unit tests in `writer/nlp-api/tests/test_topic_vector.py` (incl. the §14 offline mini-set). Live validation on the deployed nlp service is pending (the sandbox can't reach the private nlp / DataForSEO / Gemini).
- **P1 — site claim index (structured facts) + the platform→nlp payload wiring + the scored Information Gain dimension, coached into reopt. ✅ BUILT (2026-09-16).** *As built:* the per-client **`site_claim_index`** table + `writer/platform-api/services/site_claim_index.py` (deterministic — no LLM — typed-fact + claim-phrase extraction from the client's own site, discovered via `site_page_index.discover_site_urls`, scraped via `scrapeowl_fetch`, cached with a re-crawl TTL, mirroring `ecommerce_facts_cache`); the index is passed to nlp on the `/score-ecommerce-page` + `/reoptimize-ecommerce-page` request body (`site_claim_index` field) exactly like `serp_analysis`/`researched_facts` (nlp has no DB). nlp `topic_vector.py` gained pure `extract_page_claims` / `information_gain_verdicts` / `score_information_gain` / `render_gain_guidance`: a page claim counts as **gain** only if (a) on-vector (clears `CENTERING_FLOOR` vs the centroid), (b) **rare in the top-10** — judged on the claim's cosine to the competitor SUBTOPIC vectors (a name-agnostic predicate approximation reusing already-computed embeddings, not surface tokens), and (c) **site-grounded** (embeds within `GAIN_GROUNDING_FLOOR` of a site-claim phrase OR a distinctive numeric/price value it states appears in a site fact). Ungrounded-but-novel claims score **zero and are flagged** (`ungrounded_claims` — the anti-fabrication guard). A thin/absent site index → the gain dimension is **suppressed** ("not measured"), never scored 0. The gain block carries `composite_weight: 0` and is never folded into `scores`; it is coached into the reopt loop as a "TOPIC & INFORMATION-GAIN GUIDANCE" prompt block (under-served on-vector subtopics + the verifiable facts the client's own site asserts that the page omits — never an invented addition). Config: `topic_vector_gain_enabled` + `site_claim_index_*` (platform), `TOPIC_VECTOR_GAIN_*` floors (nlp). Unit-tested: `tests/test_site_claim_index.py` (platform, 8) + the P1 block in `tests/test_topic_vector.py` (nlp, incl. the §14 acceptance #2 fabrication-never-rewarded regression, offline via explicit vectors). **Live validation of the gain path is post-deploy** (the site index needs a live crawl + the deployed nlp; the sandbox is egress-blocked from ScrapeOwl/nlp/Gemini).
  - **Reopt-coaching hardening (2026-09-16, decisions.md).** The reopt-coaching live check (reconstructing `render_gain_guidance` offline on Nova's real live `site_claim_index` + the deployed score run) found the coaching **pushed page-inappropriate facts**: a garbage `price: 0.00 USD` (empty-cart chrome) + cross-product `size` facts (a semaglutide blog's dosages coached onto a retatrutide PDP). Root cause: the index is **client-level**, but coaching PUSHES a fact onto ONE page — for a multi-product client the per-product / per-compound / transactional facts belong to another page. **Fix:** (1) `site_claim_index.extract_facts` drops `$0`/`$0.00` prices at the source; (2) `render_gain_guidance` pushes only SITE-INVARIANT fact types — `_COACHABLE_FACT_TYPES = {coa, purity, storage_temp}` (quality/handling facts a vendor asserts site-wide), never `price`/`size`/`cas`/`molecular_weight`/`molecular_formula`. The scored-gain GROUNDING path (corroborating the page's OWN claim) is unchanged — safe for every type. The subtopic-gap coaching (keyword-anchored) is the primary signal and is unchanged.
  - **Gain coaching wired into the LOCAL SEO reopt loop (2026-09-16, owner-greenlit).** Previously only `/reoptimize-ecommerce-page` coached gain (the Local SEO/service/blog measure was report-only on the SCORERS). nlp `/reoptimize-page` (the Local SEO location/service reopt endpoint) now coaches it too: `ReoptimizePageRequest` gained `site_claim_index`; the handler runs `_measure_topic_vector(existing_html, keyword, serp_analysis_dict, site_claim_index, include_gain=False)` → `render_gain_guidance` → injects the guidance block into the first rewrite prompt (beside `writer_notes`), best-effort. `local_seo_service.reoptimize_page` threads `site_claim_index.resolve_index_for_request(client)` into the payload (covers the in-tool reopt AND `reoptimize_url`/bulk, which route through it). Report-only (composite weight 0). Blog reopt coaching (pipeline-api) is a separate card, not wired.
  - **Gain coaching wired into the BLOG reopt loop (2026-09-16, report-only).** The final "beyond v1" follow-up. The blog rewrite runs in **pipeline-api** (there is NO nlp blog-rewrite endpoint), so the Local SEO pattern — inject the guidance inside an nlp rewrite prompt — can't apply; the coaching travels a different path. **nlp renders it once at SCORE time:** `/score-blog-page` attaches `topic_vector.render_gain_guidance(measure, site_claim_index, page_text)` onto the report-only `topic_vector.gain_guidance` field (single-sourced — platform-api can't import the pure nlp renderer; "" when nothing actionable). **A blog reopt reuses that string with NO second nlp call:** in-place reopt (`blog_page_score.reoptimize_run` → `_reopt_gain_guidance` reads the run's latest `blog_score`) and reopt-of-existing (orchestrator blog **Stage B′** reads `src_score.topic_vector.gain_guidance` off the `blog_source_score`; the Fanout blog reopt inherits it via Stage B′). Both thread it through `orchestrator._build_writer_payload(source_gain_guidance=…)` → a new **input-only** `WriterRequest.reopt_gain_guidance` (no output-schema bump). In the pipeline writer the pure `compose_reopt_notes` folds it into the section/intro/conclusion steering **alongside** `user_notes` + the reopt deficiency directive but **EXCLUDES it from the notes-landed QA** (advisory "improve where it fits", never graded as an unmet directive) and **never** as a `deficiencies` entry (§10 report-only, composite weight 0). The `_COACHABLE_FACT_TYPES` allowlist + `never_use_terms` scrub are inherited from `render_gain_guidance` verbatim (the §12 hardening protects this path too). Best-effort: no GEMINI key / thin-or-absent index / empty measure → "" → writer payload + prompt byte-identical to today; deterministic engines + blog composite/deficiencies untouched. Unit-tested offline (nlp attach contract; `compose_reopt_notes`; platform `_reopt_gain_guidance` + payload threading + `_build_writer_payload` param). **Live LLM/rewrite validation is post-deploy** (sandbox egress-blocked from nlp/Gemini/DataForSEO).
- **P2 — the emotional-arc rubric dimension. ✅ BUILT (2026-09-16, report-only).** *As built:* pure logic in `writer/nlp-api/topic_vector.py` (`build_arc_states` / `has_arc_inputs` / `suppressed_arc` / `build_arc_prompt` / the `ARC_TOOL` forced-tool schema + `ARC_SYSTEM` / `sanitize_arc`), and the one cheap Haiku forced-tool call in `main.py::_measure_emotional_arc`, attached to the report-only `topic_vector` field as an **`emotional_arc`** sub-object at **composite weight 0** — never folded into `scores`. The before/after states come from the client's ALREADY auto-generated voice card (§10a): `before` = `audience_pain_points` + `audience_objections` + `audience_triggers`; `after` = `audience_motivations` (+ objections answered). The voice card is **already resolved inside every scorer** via `main.py::_resolve_voice_card(client, body)` (from the `brand_voice`/`detected_icp`/`voice_card` the request body already carries — platform-api sends the cached `voice_card` on every score), so **no new payload field was needed**. Wired onto the **money-page scorers** (`/score-page` [local landing + service], `/score-ecommerce-page` [product + collection]) — the reopt endpoints are excluded. **Blog + Fanout mass-post content is deliberately EXCLUDED** (owner ruling 2026-09-16): those pages are informational (TOFU/MOFU), and the arc's `before → after` is a **buyer/BOFU** transition seeded from the voice card's purchase-decision audience fields, so scoring an explainer by it would penalise good informational copy for conversion work it isn't meant to do — consistent with §10a "one page = one awareness stage." `/score-blog-page` still runs centering / coverage / gain, just not the arc. (§10a's note that a TOFU/MOFU asset could run *its own* problem-aware arc is a possible future item, not applied here.) Affect is not embeddable, so the arc is deliberately **NOT in the cosine** and runs independently of `GEMINI_API_KEY` (it rides on Claude, always configured). Best-effort + gated: no voice card / no audience fields → **suppressed** (`{available: False, reason: "no_audience_fields"}`), never scored 0; an LLM/parse failure → `arc_failed`; the flag off → `arc_disabled`. `sanitize_arc` DROPS unevidenced verdicts (a "yes" with no page quote is flipped to negative, mirroring the vibe_read sanitize) and SCRUBS every arc string of `never_use_terms` (§10b non-negotiable — a forbidden word never surfaces in any verdict/evidence/rationale). NOT wired into any reopt-coaching loop (report-only, like P0's centering). Config: `TOPIC_VECTOR_ARC_ENABLED` (default True), `TOPIC_VECTOR_ARC_MODEL` (Haiku, mirrors `VOICE_LOCALIZE_MODEL`/`PAGE_SPEC_AUDIT_MODEL`), `TOPIC_VECTOR_ARC_MAX_TOKENS`. Unit-tested offline (`tests/test_topic_vector.py` — state assembly, prompt carries audience + page text, unevidenced verdicts dropped, no-audience-fields suppressed-not-0, score clamped + garbage-safe, forbidden-term never surfaced). **Live validation of the Haiku rubric path is post-deploy** (the sandbox is egress-blocked from the private nlp service; the pure logic runs offline). The 11–20 differentiation tier already landed in P0/P1 as a partition, not a separate fetch phase.
- Adversarial-review done (2026-09-15); re-review before build if the design moves materially.

## 13. Related findings surfaced during design (not this module, don't lose them)

1. **`never_use_terms` not excluded from SERP-signal coverage** — the coverage engine penalizes the page for the forbidden target keyword and instructs the writer to add it, fighting voice enforcement every pass. Small standalone fix.
2. **Empty entity extraction on an entity-rich SERP** — `entity_detail: []` on a 15-page "buy retatrutide" SERP; either the Google-NLP `GOOGLE_NLP_MIN_SALIENCE=0.40` floor (salience is a relative distribution; 0.40 keeps almost nothing) or an extraction failure. Needs a live `/analyze` to see the raw entity count + which provider fired. Compounds the "no entity gap" false comfort.
3. **`<title>` not passed to the LLM scorer** — the `organic_ranking` engine reported it couldn't see the title ("Title tag content not provided in the page extract, so cannot confirm keyword presence"), so the qualitative engines under-scrutinize the single heaviest element while the deterministic `serp_signal_coverage` engine measures it. Extraction-parity fix.

## 14. Acceptance criteria

Concrete and checkable — no "improves quality":

- **Centering tracks real drift.** On a labeled mini-set, the Nova "buy retatrutide" page (vendor-trust drift) scores **below** a strong on-vector competitor PDP for the same keyword. The module isn't "working" until it separates these correctly.
- **Gain never rewards fabrication.** A claim absent from the client's site index is never credited; an injected ungrounded claim scores zero and is flagged (regression test).
- **Coverage names the real gaps.** For the Nova run, the inverse-gain output surfaces the mechanism cluster (receptor / metabolic / triple-agonist) the page under-covers.
- **No regression to the deterministic engine.** `_compute_serp_signal_coverage` outputs are byte-identical before/after (the new measure is beside it, not in it).
- **Graceful degradation.** No `GEMINI_API_KEY`, an empty site index, or an absent AIO each degrade to a skipped-or-suppressed measure — never a misleading number or a failed score.
- **Name-agnostic matching verified.** The coded-name/competitor-name claim pair (§6) reads as the same claim in the rarity test.
