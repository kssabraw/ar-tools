# Topic-Vector Centering + Information Gain — Module Plan v1.0

**Status:** Design locked, not built. This doc is the design authority; nothing here has shipped.
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

All from the SERP we already fetch (DataForSEO usually returns 20+ URLs). Pulling 11–20 roughly doubles the scrape for the analysis; mitigate with a **headings-only, no-JS light fetch** for that tier.

| Tier | What it is | Role |
|---|---|---|
| **Top 10** | consensus / table stakes | defines the centering centroid + must-cover baseline |
| **11–20** | on-vector angles the winners skip | *differentiation-within-reach* candidates |
| **Neither tier, but site-grounded** | first-party facts nobody ranking states | *true information gain* |

11–20 guards (so page-2 junk doesn't leak in): a subtopic must appear on **≥2** of the 11–20 pages **and** clear the centering floor before it becomes a target.

## 4. Measure 1 — Topic centering

**The centroid is anchored on the EXPLICIT query only:** `explicit query terms + AIO text + top-10 competitor headings`. For a transactional "buy / where to buy" query these signals are already commercial, so the centroid's center of mass lands on **the offer** (product identity, price, sizes, stock, purchase mechanics, COA-as-purchase-gate) by construction — no hand-weighting needed.

**The implied query is deliberately NOT in the centroid.** It lives one layer down (§5), as coverage checklist items only. This is the load-bearing decision: it makes the implied/emotional layer structurally incapable of pulling the vector off "where to buy." A mechanism essay with no commercial core scores *low* on centering, correctly.

**Score:** `cosine(page_embedding, centroid)`. Reported as a drift alarm ("this page slid toward vendor-trust and off the commercial vector"). Because whole-doc cosine saturates and is forgiving (the lesson already burned into the Fan-out source guard and Keyword Research relevance gate — cosine alone drifts), this single number is a coarse gauge; the actionable detail comes from §5.

**Related finding (adjacent, separately fixable):** `_compute_serp_signal_coverage` has no `never_use_terms` awareness, so it scores the page against `retatrutide` (34 kw + 66 bold shortfall) and its recommendations literally say "add retatrutide" — which voice enforcement then strips, every pass. Excluding `never_use_terms` from the coverage targets is a small, separate change worth doing regardless of this module.

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

**Properties to remember:** gain is corpus-relative (a snapshot — re-running over time shows an eroding edge as competitors catch up) and only credits *rare* claims (claim-level page-spread).

## 7. The site claim index — the one genuinely new artifact

The grounding corpus. Per-client, cached, refreshed periodically.

- **Discovery:** reuse `site_page_index.discover_site_urls` (sitemap → DataForSEO `site:` fallback).
- **Granularity (locked): STRUCTURED FACTS**, not claim-sentences. A per-fact extractor pulls typed facts from the site (price, purity, COA presence/access, molecular identifiers, shipping/returns terms, policies, product identity). Stronger grounding than fuzzy sentence-cosine; a page claim is credited only when it matches a structured fact the site actually asserts.
- **Matching:** a page claim → the index by fact-type + value agreement (embedding cosine assists fuzzy matches; typed comparison for numerics/prices).
- **Name-agnostic:** the site says "GLP-3RT" and carries its specs, so grounding credits the coded-name facts fine.

This is the piece to design most carefully (extractor coverage, refresh cadence, staleness). Everything else is reuse.

## 8. Reuse map

| Need | Reuse |
|---|---|
| Embeddings + cosine | `ecommerce_mcs.py` `cosine`, injected `EmbedFn` (Gemini `gemini-embedding-2`, unit-normed) |
| AIO + competitor headings | already in `serp_analysis` (`aio_text`, `competitor_headings`) |
| Implied-query brief | Haiku intent fan-out, same shape as `keyword_research_topics` |
| Claim/fact extraction | `ecommerce_facts.py`, MCS `parse_facts` |
| Site discovery | `site_page_index.discover_site_urls` |
| Genuinely new | the per-client **structured-fact site claim index** |

## 9. Where it slots

Ecommerce scorer first (`/score-ecommerce-page`, `/reoptimize-ecommerce-page`), then the Local SEO / service / blog scorers (shared `_compute_serp_signal_coverage` seam). Centering + per-subtopic coverage can fold into the deterministic `serp_signal_coverage` engine or sit beside it; Information Gain is a separate reported score. The reopt loop consumes the per-subtopic gaps + gain guidance as rewrite targets.

## 10. Guardrails

- **Fabrication:** gain credited only for site-grounded claims; ungrounded novelty scores zero and is flagged. Composite weight kept low/zero so no gain quota.
- **Name-agnostic:** embeddings + site-grounding both work under `never_use_terms`; the module is the intended answer to the forbidden-name problem.
- **Centering gates gain:** novelty is only "gain" inside the topic vector — off-vector novelty (vendor-trust boilerplate) is not rewarded.
- **Emotional arc stays in the LLM rubric,** never the cosine.

## 11. Decisions

**Locked:**
- Centroid = explicit query + AIO + top-10 headings; implied query demoted to coverage checklist only.
- Fork 2 (per-subtopic semantic coverage) is in.
- 11–20 headings pulled as a distinct "differentiation-within-reach" tier, gated by ≥2 page-spread + centering floor.
- Information Gain = separate prominent score, coached into reopt, low/zero composite weight.
- Site claim index granularity = **structured facts.**
- Ground truth = the client's whole site.

**Open:**
- Structured-fact extractor scope (which fact types v1) + refresh cadence for the site index.
- Exact centering-floor + rare-in-top-10 thresholds (calibrate from real runs, like every other floor in this codebase).
- Whether centering/coverage fold into `serp_signal_coverage` or stand as a new engine.

## 12. Phasing

- **P0 — report-only.** Centering score + per-subtopic coverage + the inverse gain gap (competitor claims the page lacks). No score fed to reopt yet. Cheapest, safest, immediately useful; validates the centroid + clustering before anything optimizes against them.
- **P1 — site claim index (structured facts)** + the scored Information Gain dimension, coached into reopt.
- **P2 — 11–20 differentiation tier** + the emotional-arc rubric dimension.
- Adversarial-review the P0 design before building (the drift/saturation traps are exactly what that review catches).

## 13. Related findings surfaced during design (not this module, don't lose them)

1. **`never_use_terms` not excluded from SERP-signal coverage** — the coverage engine penalizes the page for the forbidden target keyword and instructs the writer to add it, fighting voice enforcement every pass. Small standalone fix.
2. **Empty entity extraction on an entity-rich SERP** — `entity_detail: []` on a 15-page "buy retatrutide" SERP; either the Google-NLP `GOOGLE_NLP_MIN_SALIENCE=0.40` floor (salience is a relative distribution; 0.40 keeps almost nothing) or an extraction failure. Needs a live `/analyze` to see the raw entity count + which provider fired. Compounds the "no entity gap" false comfort.
