# On-Page Criteria & Coverage

**Current as of:** 03 July 2026
**Purpose:** The shared definition of what an on-page verdict *is* and *means*, so every consumer (the rank-drop branches, the Recipe Engine, the SEO agent) interprets it identically. **Execution lives in the agents** — the four on-page evaluation agents grade pages; the SEO agent routes; the writers fix.
**Scope:** Verdict schema · thresholds · verdict→action routing · coverage boundaries.

> **Cross-references:** invoked by → Rank Drop branches (Maps §A.11, Organic §B5.2) · roles → `_ORCHESTRATOR.md` §6 · agents → `_ORCHESTRATOR.md` §Agents.

---

## 1. Coverage

| Page type | Evaluated by | Optimized by |
|---|---|---|
| Blog posts · Local landing pages · Service pages · Location pages | The four **on-page evaluation agents** (one per type) | **Writers, automatically** — a failing verdict's recommendations flow straight to the writer for execution; no human task-creation step |
| **Home page** | — | **The AI SEO agent** (future — until it ships, home-page optimization is manual: Minda/Ivy per §6) |
| About, bios, neighborhood, hub/archive, Contact, Privacy | Not evaluated | Not optimized for rankings — these page types are not ranking targets (home page excepted above) |

## 2. Verdict Schema

Each on-page agent returns (extracted from live output, `score-page` endpoint):

```
{
  composite_score: float (0–100),
  composite_status: "excellent" | "good" | "needs_improvement" | "below_standard" | "fail",
                                             // bands: ≥90 · ≥80 · ≥70 · ≥60 · <60 (resolved — see §4)
  engine_scores: {
    organic_ranking:        { score, issues[], recommendations[] },
    gbp_maps:               { score, issues[], recommendations[] },
    entity_establishment:   { score, issues[], recommendations[] },
    icp_alignment:          { score, issues[], recommendations[], icp_detected },
    aeo_llm_retrieval:      { score, issues[], recommendations[] },
    geographic_legitimacy:  { score, issues[], recommendations[] },
    nearme_intent:          { score, issues[], recommendations[] },
    serp_signal_coverage:   { score, issues[], recommendations[],
                              keyword_coverage, entity_coverage, quadgram_coverage }
  },
  deficiencies: [ { engine, engine_key, score, issues[], recommendations[] } ],
                                             // inclusion rule: engine score < 80 (fixed bar — resolved, see §4)
  token_usage: { endpoint, model, input_tokens, output_tokens, cost_usd }
}
```

**The eight engines, and what each grades:**
1. **organic_ranking** — title/H1/opening-paragraph keyword+entity targets, answer-first service declaration, CTA-with-phone placement, topical focus.
2. **gbp_maps** — brand+service+city co-occurrence, GBP-category alignment, NAP in body, named-suburb coverage.
3. **entity_establishment** — per-entity frequency targets (e.g., warranty ×3, inspection ×3), sub-service topical depth, triplet distribution across ≥3 sections.
4. **icp_alignment** — detected ICP, pain-point coverage, decision-assistance copy, CTA tone match.
5. **aeo_llm_retrieval** — FAQ presence (4–7 entries, question-format H3s, answer-first), numbered process lists, operational facts (timeframes/response times), ≥300-word citation-worthy depth. *(This engine enforces the AIO/AEO SOP's extraction-writing rules.)*
6. **geographic_legitimacy** — ≥2 named neighborhoods in sentence context, ≥3 postcodes in body, landmark references, geo signals across ≥3 sections.
7. **nearme_intent** — phone-in-first-paragraph, availability language, stated response time, explicit pricing signal (high importance), proximity FAQs.
8. **serp_signal_coverage** — keyword/entity/quadgram coverage percentages against H2/H3 and paragraph targets.

## 3. Verdict → Action Routing

| Verdict | The AI SEO agent does |
|---|---|
| Composite **≥ 90** (`excellent`) | Continue the calling flow (e.g., rank-drop diagnostic proceeds to backlinks) |
| Composite **< 90** (any lower band) | Send the **`deficiencies` array's `recommendations`** (every engine scoring < 80) to the **writer — automatically executed**, no human task step. The scoring stack itself auto-runs a reoptimize pass when the composite is < 90 (max 2 passes); re-run the evaluation after the rewrite is live and indexed |
| Composite still < 90 after rewrite + re-evaluation | Escalate per the calling SOP's timeline (6-week rule → Kyle/Ryan) |
| Page type outside coverage (§1) | Do not invoke an agent — route per §1 (home → manual/SEO agent; others → not a ranking target) |

**Notes for consumers:**
- The `recommendations` are **write-ready instructions** (they include literal suggested copy) — the writer executes them directly; the SEO agent doesn't need to interpret.
- `deficiencies` is the worklist; `engine_scores` is the full picture. Consumers should act on `deficiencies` and read `engine_scores` only for context.
- `token_usage` is cost telemetry, not decision data.

## 4. Resolved cells *(answered from the live scoring code — `writer/nlp-api/main.py`, 04 Jul 2026)*

- **Composite bands** (`_composite_from_scores` / `_status_for_score`): **≥90 `excellent` · ≥80 `good` · ≥70 `needs_improvement` · ≥60 `below_standard` · <60 `fail`**. The **operational pass line is 90**: the generator auto-runs a reoptimize pass whenever the composite is below 90 (max 2 auto passes), so consumers route on **≥90 = continue / <90 = rewrite**. *(The pasted 47.4 example lands in `fail`.)*
- **Deficiencies inclusion rule** (`_build_deficiencies`): a **fixed bar — any engine scoring < 80** enters `deficiencies`. *(Consistent with the observed 75.9 example.)*
