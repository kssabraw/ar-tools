# SOP Library

The agency's agent-operable SOP library. **Start with `_ORCHESTRATOR.md`** — it is the router: decision ownership, shared definitions, global rules, roles matrix, and rate limits. Every other SOP defers to it; when a leaf SOP conflicts with `_ORCHESTRATOR.md` §2, §2 wins and the conflict must be reported.

| File | Owns |
|---|---|
| `_ORCHESTRATOR.md` | Routing, shared definitions, global agent rules, roles (§6), limits (§7) |
| `Site_Architecture_and_Internal_Linking_SOP.md` | Site plans: page list, URLs, nav, schema, internal links (incl. the Site Planning Algorithm + golden trace) |
| `Link_Building_SOP.md` | Link strategy & SEO NEO execution; Freeze Protocol; master link-type table |
| `Link_Building_Recipe_Engine.md` | Budget → costed, assigned monthly task plan |
| `How_To_Rank_In_Google_Maps_SOP.md` | Maps/GBP ranking: factors, GBP optimization, reviews, diagnostics, entity building, theming, tactics stack |
| `Rank_Drop_Mitigation_SOP_Maps.md` | Geo-grid drop response |
| `Rank_Drop_Mitigation_SOP_Organic.md` | Organic drop response (consumes the rank tracking agent's classified signals) |
| `On_Page_Criteria_and_Coverage.md` | The 8-engine on-page verdict schema, thresholds, routing (mirrors `writer/nlp-api` scoring) |
| `AIO_AEO_SOP.md` | AI Overview / LLM-answer visibility, offense + click-absorption defense (LABS = the AI Visibility module) |
| `Seed_Keyword_SOP.md` | Seed keyword selection at onboarding (feeds the Site Planning Algorithm + Topic Fanout) |
| `AR_Team_Capacity_Workbook.xlsx` | Task build times, team capacity math, monthly allocation |

Not yet written: **Agency Assassin SOP** (deferred — tool is not agent-accessible; see `_ORCHESTRATOR.md` §1).

Imported 2026-07-04 with a consistency pass applied (dedup of shared definitions, status-drift fixes, thresholds resolved from the live scoring code, and four rulings: plan-time Step 8 gate, threshold-gated overclock self-serve, RD 250 as guideline not cap, LABS engine list aligned to the built module).
