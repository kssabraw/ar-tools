# SED Local Search Intelligence Platform — Unified Research Architecture & Cost Optimization PRD

Organization: SED Society

Document status: Draft v0.1 — platform-level parent PRD

Purpose: Define the shared architecture, operating model, cost controls, and cross-surface research layer that unify the Google Maps, Google Organic, Google AIO/AI Mode, and ChatGPT Local Search research modules without weakening their surface-specific methodologies.

Relationship to module PRDs: This document governs shared infrastructure, canonical entities, observation reuse, enrichment, cost governance, orchestration, shared research outputs, and Client Mode integration. The existing Google Maps Local Search Intelligence & Strategy Engine PRD and Local AI Overview Research & Citation Intelligence Platform PRD remain authoritative for their surface-specific research designs unless this document explicitly establishes a shared-platform rule. Locked methodological decisions in those PRDs are not reopened by this parent PRD.

# 1\. Executive Summary

SED Society will build one Local Search Intelligence Platform rather than operate Google Maps, Organic SERP, and AI Overview research as independent systems. The platform will preserve each module’s research methodology while consolidating the expensive and duplicative parts of the stack: research-universe definitions, canonical business/domain/URL identity, SERP collection where a single provider response can support multiple surfaces, competitor enrichment, page crawling, link metrics, embeddings, storage, orchestration, cost accounting, finding management, and Client Mode.

The central optimization principle is simple: observe the search surface at the cadence required by the research design, but do not repeatedly purchase, crawl, embed, classify, or enrich information that is already fresh and reusable. Cost savings must come primarily from deduplication, caching, progressive enrichment, change detection, provider batching, and shared infrastructure—not from degrading the permanent longitudinal panels.

The target outcome is a unified research asset in which Maps, Organic, and AIO observations share the same entity graph and signal warehouse. This will reduce operating cost and engineering complexity while enabling cross-surface questions that neither module can answer alone.

# 2\. Product Scope

The platform has two product modes. Research Mode runs standardized longitudinal panels across industries and markets to produce defensible findings. Client Mode diagnoses a specific client by comparing its observed state against validated research findings, relevant cohorts, and intervention histories.

The supported observation surfaces are Google Maps / Local Pack, Google Organic SERPs, Google AIO/AI Mode, and ChatGPT Local Search. Additional surfaces may be added later, but they must integrate through the same canonical entity, observation, enrichment, cost, and finding layers rather than create parallel stacks.

# 3\. Non-Goals

This PRD governs the shared collection architecture across Maps, Organic, AIO/AI Mode, and ChatGPT. The 2026-09-09 methodology version uses the 25-industry × 50-market panel with surface-specific collection designs: Maps/Organic first pilot \= full 13-point geometry with a tagged nested 9-point production candidate; AIO \= 9 points; ChatGPT \= no geo grid and exactly 3 fresh-context replicates. Routine full-panel collection is monthly and the Research Sentinel is weekly. Surface-specific analytical semantics remain child-owned, and observational associations must not be converted into causal claims. It also does not authorize an LLM to invent quantitative findings, substitute intuition for measured evidence, or treat predictive importance as proof of a ranking or recommendation factor.

The platform is not a generic rank tracker, a one-off heatmap product, or an automated recommendation engine that acts without an evidence trail.

# 4\. Governing Principles

Shared-platform architecture must follow seven governing principles: collect once where scientifically equivalent, store raw observations immutably, resolve entities canonically, enrich progressively, refresh by state rather than habit, attribute every paid call to cost and purpose, and keep hypotheses, associations, predictions, and causal claims explicitly distinct.

When a cost-saving optimization conflicts with longitudinal comparability, research validity wins unless the methodology is deliberately versioned and the effect of the change can be measured.

# 5\. Parent–Module Governance

The platform PRD is the parent specification for shared infrastructure. Surface-specific PRDs remain child specifications. If a rule concerns Maps coordinate geometry, Maps ranking outcomes, AIO citation taxonomy, AIO presentation zones, or another surface-specific measurement, the child PRD controls. If a rule concerns canonical business IDs, shared domains, enrichment TTLs, queueing, raw payload retention, API cost accounting, or shared Client Mode access, this parent PRD controls.

Superseded decisions documented in either module must not be resurrected during implementation. A shared component must support the newest authoritative methodology rather than force the research design backward to fit an older schema.

# 6\. Unified Research Universe

The platform will maintain canonical dimensions for industries, markets, queries/prompts, devices, languages, locations, coordinates, replicates, and research panels. A query/prompt or market may belong to multiple panels simultaneously. This supports the shared 25-industry × 50-market universe while preserving surface-specific panels: four canonical queries for Maps/Organic, 10 conditions for AIO, and 10 prompts with exactly 3 fresh-context replicates for ChatGPT.

Core tables should include research\_industry, research\_market, research\_query, research\_location, research\_coordinate, research\_panel, and research\_panel\_membership. Membership records must contain effective dates and methodology-version identifiers so that panel changes are historically reconstructable.

The current production research foundation is the shared 25-industry × 50-market panel. Maps and Organic use the four permanent canonical core query classes with the eligible fixed 13-point cardinal design; AIO uses the approved 10-condition panel with the eligible 9-point cardinal design; ChatGPT uses the approved 10-condition panel with exactly 3 fresh-context replicates and no geo grid. The former 10-industry × 20-market × two-query Maps panel is historical/superseded and may be retained only for methodology lineage or validation comparisons.

# 7\. Observation Architecture

Every provider request creates a provider\_task and, when successful, one immutable raw\_observation record containing the full response or a lossless stored representation, provider metadata, request parameters, location, device, language, timestamp, module memberships, cost, and parser version.

Surface parsers derive normalized records from raw observations: maps\_observation, organic\_observation, aio\_observation, serp\_feature\_observation, and entity\_appearance. Derived tables may be rebuilt when parsing logic improves; raw provider observations must never be overwritten by a newer parser.

Where one Organic SERP request can validly produce Organic, Local Pack, SERP-feature, and AIO information for the same query/location/device/time condition, the platform should purchase the observation once and fan it out to multiple parsers. Dedicated Maps geo-coordinate observations remain separate when required by the Maps methodology.

# 8\. Canonical Entity Graph

All modules must resolve observations into shared entities. The minimum graph includes business, gbp\_location, domain, url, social\_entity, and organization relationships. A single business may own multiple GBPs, domains, URLs, or social profiles, and these relationships must be time-aware where ownership or canonical associations change.

Entity resolution must prefer stable provider identifiers such as Google place IDs when available, then corroborate with normalized name, phone, address, domain, coordinates, and other identifiers. Probabilistic matches must store confidence and provenance and must not silently merge ambiguous businesses.

Once an entity is resolved, Maps, Organic, AIO, ChatGPT, link, content, source/evidence, social, and Client Mode records should reference the same canonical IDs. This is the primary mechanism for eliminating duplicate enrichment.

# 9\. Shared Signal Warehouse

Enriched facts will be stored as time-versioned signals rather than module-owned columns. Each signal definition specifies entity type, provider, endpoint or collector, units, freshness policy, expected volatility, estimated cost, and whether historical snapshots are required.

Examples include review count, review velocity, primary and secondary GBP categories, DR, referring domains, URL-level authority, linked-page type, site size, content hash, title, headings, schema, page embeddings, social-profile identity, and other approved signals from the module PRDs.

Modules consume signals through the shared warehouse. They do not independently recollect a signal simply because the same entity appears in a different research surface.

# 10\. Refresh Policies and TTLs

Every paid or compute-heavy signal requires an explicit freshness policy and every enrichment request requires a module-owned reason. The scheduler must check whether a sufficiently fresh canonical snapshot already exists for the provider’s true economic unit before creating a paid job.

&nbsp;

Refresh cadence is evaluated at the entity × signal × research-context level, not globally. Routine full-panel research-surface observations are monthly; the fixed Sentinel subset is weekly. For the regular/full research population, approved backlink/link variables and histories—including approved detailed backlink data—remain monthly, subject to global domain/URL/provider-economic-unit deduplication and reuse. The fixed Sentinel may retain approved lightweight weekly link/RD/DR/URL-authority monitoring for eligible Sentinel entities/cohorts, with targeted deeper inspection when a predefined event or Analysis Specification Contract requires it; Sentinel does not cause universal weekly full-backlink reconstruction. AIO entities that do not meet a child-defined staleness, transition, reconciliation, or experimental trigger must not be swept into weekly explanatory enrichment merely because another module uses a signal weekly for a different cohort.

&nbsp;

When the same canonical entity qualifies under multiple modules, the platform satisfies the union of the active requirements with a single purchase whenever the provider metric, economic unit, time window, and requested data are equivalent. The shortest required freshness window applies only to that qualifying entity/signal combination, not to the entire warehouse. Content-derived work remains change-triggered where authorized; low-frequency reconciliation remains bounded and child-methodology-specific. All policy and trigger changes must be versioned.

# 11\. Change Detection

The platform must avoid expensive downstream processing when a page has not materially changed. Each fetched page should produce a normalized content hash and, where useful, HTTP-level change indicators such as ETag and Last-Modified. If the normalized content hash is unchanged, the system should update last\_seen but skip embedding generation, entity extraction, content classification, schema re-analysis, and other unchanged downstream work.

When content changes, the system creates a new url\_content\_version and schedules only the dependent analyses. Historical versions must remain available for event studies.

# 12\. Progressive Competitor Enrichment

Not every observed competitor deserves the same enrichment spend. The parent platform owns the shared mechanics of enrichment—canonical deduplication, economic-unit deduplication, freshness checks, cache reuse, trigger logging, budget controls, and job orchestration—but it does not replace module-specific eligibility cohorts or tier semantics.

&nbsp;

Each child PRD remains authoritative for which entities qualify for enrichment and why. The Maps PRD’s approved competitor cohorts and enrichment tiers remain intact; the AIO PRD’s matched controls, transition entities, and event-driven enrichment rules remain intact. The unified scheduler translates those module-owned eligibility decisions into shared collection jobs and ensures that one qualifying entity receives only one purchase per canonical provider metric/economic unit/freshness window even when multiple modules request it.

&nbsp;

A business may carry multiple simultaneous enrichment reasons across Maps, Organic, AIO, experimental, and Client Mode contexts. All reasons must be preserved for analysis, but duplicate reasons must not create duplicate provider purchases. Low-value or transient appearances do not independently authorize exhaustive enrichment unless a child methodology explicitly requires it.

# 13\. Event-Triggered Enrichment

The platform must detect scientifically interesting changes and respond with targeted enrichment. Examples include sudden Maps expansion or contraction, an abrupt AIO citation change, a new Top-3 organic entrant, a large review change, a material backlink delta, a linked-page change, or a newly dominant cross-surface entity.

An event creates an enrichment request containing the trigger, priority, eligible signal families, estimated cost, and research-run context. This produces denser data around meaningful transitions without paying for deep analysis on every entity every week.

# 14\. Unified Scheduler and Collection Queue

A central scheduler must replace independent module cron logic for shared work. The scheduler evaluates panel cadence, signal freshness, existing queued tasks, provider rate limits, cost budgets, research priority, and event triggers before creating collection jobs.

The minimum queue record should contain task type, entity or research target, module memberships, priority, due\_at, provider, endpoint, estimated cost, idempotency key, retry state, and reason. Idempotency must prevent two modules from purchasing the same equivalent observation or enrichment simultaneously.

Workers should be separated by functional class—SERP collection, GBP/entity enrichment, links, crawl/content, embeddings, and analytics—while sharing a common job contract and telemetry.

# 15\. Batching and Provider Efficiency

The platform should use provider batch endpoints and Standard/queue pricing wherever latency is not scientifically relevant. Research Mode is asynchronous by default. Live or priority endpoints are reserved for explicit cases such as interactive Client Mode where a person is waiting and fresh data is required.

Batching does not necessarily reduce per-task API billing, but it reduces HTTP overhead, Railway executions, logging volume, retry complexity, and failure surface. Batch size must respect provider limits and permit partial retry without replaying successful tasks.

# 16\. Cost Ledger and Budget Governance

Every paid external request must generate an api\_usage record with provider, endpoint, request type, task count, entity count where relevant, module attribution, research run, estimated cost, actual cost when known, timestamp, and outcome.

The platform must distinguish account deposits or prepaid balances from consumed research expense. Monthly reporting is based on actual consumed cost.

Cost dashboards must support provider, market, industry, query, signal family, entity, module, research run, and Client Mode attribution. The system should expose cost per useful observation and, later, cost per validated or decision-relevant finding.

Budget controls should include a global monthly soft target, a hard alert threshold, per-provider ceilings, and optional per-signal-family budgets. A cost ceiling must never silently cause missing research data; it should pause noncritical enrichment first and surface the conflict.

# 17\. Research Cost Effectiveness

After sufficient history exists, the platform will evaluate whether expensive signal families justify their ongoing collection. Each signal family should be measurable by monthly collection cost, dataset coverage, model usage, number of supported findings, and contribution to predictive or explanatory analyses.

Signals that consistently add little value can have their cadence reduced or be removed through a methodology-versioned decision. The platform should therefore become progressively more efficient based on evidence rather than assumptions.

# 18\. Shared Research Engine

The research engine consumes normalized observations and signals across surfaces. It must support cross-sectional analysis, longitudinal analysis, spatial analysis, distance-adjusted models, event studies, cohort comparisons, survival/persistence analyses where appropriate, and cross-surface models.

The system must preserve the distinction between descriptive findings, associations, predictive features, quasi-experimental evidence, and causal claims. Statistical output must include the relevant population, time window, model version, controls, uncertainty, and replication state.

LLMs may summarize, classify, explain, and draft interpretations from computed outputs, but they may not manufacture measurements, p-values, effect sizes, coefficients, confidence intervals, or other quantitative results.

# 19\. Cross-Surface Research

The unified platform must make cross-surface research a first-class capability. Examples include whether distance-adjusted Maps leaders are disproportionately cited in AIO, whether organic gains precede Maps visibility expansion, whether AIO-cited businesses differ in backlink or content structure from similarly ranked non-cited competitors, and which interventions improve multiple surfaces simultaneously.

Cross-surface analysis must use canonical entities and time-aligned observations. A business being present on two surfaces is not sufficient evidence of a relationship; models must account for confounders defined in the relevant research methodology.

# 20\. Finding Registry

Validated and provisional research results will be stored in a shared finding registry. Each finding requires a unique ID, research question, hypothesis, surface or surfaces, population, outcome, signal definitions, methodology/model version, evidence classification, replication count, known limitations, status, and the exact computed artifacts that support it.

Findings may be provisional, replicated, validated for operational use, contradicted, superseded, or retired. The strategy engine may only use findings whose status permits operational use.

# 21\. Shared Strategy Engine and Client Mode

Client Mode should not maintain a separate research truth. It queries the same finding registry and signal warehouse, then compares a client against appropriate industry, market, distance, competitor, and surface cohorts.

Before purchasing new Client Mode enrichment, the system must check whether sufficiently fresh research data already exists for the same business, GBP, domain, URL, or market. Client Mode may request fresher or deeper data when its service-level requirement justifies the cost.

Recommendations must cite the underlying finding IDs, the client-specific observations that triggered the recommendation, confidence or evidence status, expected measurement window, and any assumptions. Advice should distinguish evidence-backed intervention, plausible hypothesis, and exploratory test.

# 22\. Data Model — Minimum Shared Tables

The initial shared schema should include research\_industry, research\_market, research\_query, research\_location, research\_coordinate, research\_panel, research\_panel\_membership, provider\_task, raw\_observation, maps\_observation, organic\_observation, aio\_observation, serp\_feature\_observation, business, gbp\_location, domain, url, social\_entity, entity\_relationship, signal\_definition, signal\_value, url\_content\_version, enrichment\_request, collection\_job, api\_usage, research\_run, methodology\_version, research\_event, research\_finding, finding\_replication, client\_account, client\_entity\_link, intervention, and intervention\_measurement.

Module-specific tables may extend this model but should not duplicate a shared concept under a different ID namespace.

# 23\. Storage and Retention

Supabase/Postgres remains the operational metadata and normalized research store. Large raw payloads may be compressed and moved to object storage if economically preferable, but they must remain addressable by immutable IDs and checksums.

Raw observations and methodology metadata should be retained long term because historical provider responses cannot be recreated exactly. Derived tables may be recomputed. Content versions should be retained when they support longitudinal or event analysis, while redundant fetch artifacts may follow a shorter retention policy.

# 24\. Reliability, QA, and Reproducibility

Every collection job must be idempotent and traceable from scheduled intent through provider task, raw response, parser version, normalized records, enrichment, analysis, and finding. Retries must not duplicate paid tasks when the original task can still be recovered.

QA should detect missing markets, missing coordinates, unexpected result-count changes, parser drift, provider schema changes, duplicate entities, impossible rank values, broken time alignment, stale signals, cost anomalies, and sudden shifts in observation volume.

A research result must be reproducible from stored data plus the applicable methodology and model versions.

# 25\. Security and Access

Provider credentials and database secrets must remain server-side. Workers receive least-privilege access. Client Mode data must be logically separated from unrelated client data while still allowing reuse of public research observations and public entity enrichment through canonical IDs.

Operational logs must avoid leaking credentials or unnecessary personal information.

# 26\. Observability

Operational telemetry must include queue depth, task latency, provider error rate, retry rate, parser failure rate, entity-resolution ambiguity, cache hit rate, enrichment reuse rate, content-change rate, API spend, cost avoided through reuse, and observation completeness.

The platform should explicitly measure deduplication effectiveness: equivalent requests prevented, signals reused across modules, embeddings skipped because content was unchanged, and deep-enrichment jobs avoided through tiering.

# 27\. Cost Targets

The parent platform must not establish an arbitrary savings target that assumes child-module costs are simply additive. The AIO PRD already uses cache reuse, incremental updates, event-triggered enrichment, and bounded reconciliation, so those efficiencies are part of its current baseline rather than entirely new savings created by this parent architecture.

&nbsp;

The authoritative economic objective is therefore to measure and minimize total platform cost per useful observation and per decision-relevant finding while preserving every locked permanent-panel requirement. The initial baseline must be reconstructed from the current child-PRD collection plans and actual provider usage, then compared against unified-platform actuals after cross-module deduplication is live.

&nbsp;

No percentage saving, fixed monthly target, or aspirational range should be represented as validated until the platform has measured unique entity counts, domain/URL/GBP overlap, equivalent SERP-request overlap, cache reuse, provider usage, signal-refresh volume, and avoided duplicate purchases for multiple stable research runs. Any future budget target must be derived from that measured baseline.

# 28\. Phased Implementation

## 28.1 Phase 1 — Shared Foundation

Implement the canonical research universe, provider\_task/raw\_observation model, canonical business/domain/URL graph, api\_usage ledger, methodology versioning, and unified scheduler/job contract. Existing Maps and AIO collectors may continue temporarily, but all new output should land in the shared identifiers and cost ledger.

## 28.2 Phase 2 — Observation Consolidation

Route Organic, Local Pack, AIO, and Maps outputs into shared raw and normalized layers. Add request deduplication, provider batching, and parser-version tracking. Prove that no surface-specific fields are lost relative to the child PRDs.

## 28.3 Phase 3 — Enrichment Consolidation

Centralize GBP, links, page crawl, content, embeddings, site architecture, and social/citation enrichment. Add canonical economic-unit deduplication, module-aware freshness policies, content hashes, child-owned enrichment eligibility, and event-triggered enrichment.

## 28.4 Phase 4 — Research and Findings

Build shared analytical datasets, cross-surface models, event-study pipelines, and the finding registry. Migrate existing validated module findings without changing their evidence status.

## 28.5 Phase 5 — Client Mode

Connect client diagnosis and intervention playbooks to the shared signal warehouse and finding registry. Add reuse-first enrichment logic and client-specific cost attribution.

# 29\. Acceptance Criteria

The platform is acceptable for V1 when: the Maps, Organic, AIO, and ChatGPT panels can run at their approved surface-specific designs without methodological loss; a single canonical entity can be referenced across all four surfaces, enrichment, sources/evidence, and Client Mode; duplicate equivalent collection jobs are prevented; paid calls are fully cost-attributed; page embeddings are skipped when content is unchanged; module-owned enrichment eligibility and platform freshness/deduplication rules are enforced; raw observations can be reparsed without repurchase; module-level findings can be reproduced; and the system can produce at least one valid cross-surface analysis from time-aligned canonical entities.

A second acceptance threshold is economic: after multiple stable runs, the platform must be able to report actual spend, reuse rate, avoided duplicate spend, and the cost contribution of each signal family without manual reconciliation.

# 30\. Risks and Mitigations

The primary risks are over-aggressive caching, entity-resolution mistakes, hidden methodology drift, provider schema changes, enrichment-trigger bias, and premature cost cuts. Mitigations are conservative TTLs where uncertainty exists, provenance on every entity merge, methodology versioning, raw-payload retention, QA alerts, explicit trigger logging, and a rule that permanent-panel integrity takes precedence over small savings.

Another risk is architectural over-centralization. Shared infrastructure must not erase meaningful differences between Maps, Organic, AIO, and ChatGPT. The parent platform owns common mechanics; child PRDs continue to own the scientific semantics of their surfaces.

# 31\. Open Decisions for Engineering

Engineering still needs to select the exact object-storage strategy for raw payloads, define the first-pass entity-resolution confidence thresholds, choose queue technology and worker concurrency, finalize provider-specific TTL defaults, and validate which DataForSEO Organic/AIO response combinations fully satisfy the AIO module’s required fields. These are implementation decisions unless testing reveals a methodological conflict.

Any implementation discovery that would require changing a locked research design must be escalated as a methodology decision rather than silently absorbed into code.

# 32\. Final Architectural Rule

SED Society is building one longitudinal Local Search Intelligence Platform with multiple observation surfaces—not separate Maps, Organic, AIO, and ChatGPT products that happen to share a database. New modules must integrate through the common research universe, canonical entity graph, raw observation layer, signal warehouse, scheduler, cost ledger, finding registry, and strategy engine.

The success criterion is not merely lower API cost. The platform should become cheaper per useful observation while simultaneously becoming more scientifically powerful because every new surface, entity, and signal increases the value of the shared longitudinal dataset.

# 33\. Cross-PRD Audit Results

The parent/child audit confirms that the current governing parent plus Maps/Organic, AIO, and ChatGPT child PRDs are conceptually compatible, but several shared rules were duplicated across the child PRDs before this parent specification existed. The correct long-term architecture is to move ownership of shared mechanics upward while leaving scientific surface semantics downward. Until the child PRDs are formally refactored, duplicated child text remains valid only to the extent that it agrees with this parent PRD and its own surface-specific methodology.

&nbsp;

The AIO PRD contains a mature cache-reuse model: monthly full-panel plus weekly Sentinel AIO/SERP observation under the current collection design, followed by baseline enrichment, canonical cache reuse, incremental updates, transition-triggered refresh, and bounded reconciliation rather than automatic full-universe enrichment. The Maps PRD independently contains the same economic principle: do not repurchase enrichment already available from a required primary observation or sufficiently fresh enrichment at the provider’s canonical economic unit. These are now platform-level rules.

&nbsp;

# 34\. Authority Allocation Matrix

Parent-owned shared concepts: canonical industry/market/service/query-family taxonomy; canonical business/GBP/domain/URL/social identities; provider-task and immutable raw-observation mechanics; provider/economic-unit registry; deduplication and freshness evaluation; shared signal storage; content/version hashing; collection queue and idempotency; API usage/cost ledger; parser/model/methodology provenance; shared finding registry infrastructure; intervention registry infrastructure; shared observability; and cross-module reuse accounting.

&nbsp;

Maps-owned concepts: Maps Top-10 outcome semantics; distance/proximity methodology; DAVS and Effective Ranking Radius research; Maps-specific competitor cohorts and enrichment eligibility; Maps signal definitions; Maps statistical models; Maps Client Mode diagnostics and intervention playbooks. Panel breadth, four canonical query classes, structural-water semantics, and monthly-full/weekly-Sentinel cadence are shared platform rules. For current implementation, the first Maps/Organic pilot collects the full 13-point geometry while tagging a nested 9-point production candidate; the pilot must decide 13 versus 9 from measured marginal cost and information value. The 73-point design is historical/validation-only, not routine production.

&nbsp;

AIO-owned concepts: AIO trigger and answer capture; source visibility, entity visibility, and destination visibility; citation/source/content taxonomies; local-business-card and embedded-GBP presentation outcomes; SearchViewer destination semantics; AIO-specific controls, transitions, persistence outcomes, semantic-similarity analyses, sensitivity experiments, and AIO Strategy Evidence Framework semantics. Panel breadth, the approved 10-condition AIO panel, the 9-point AIO coordinate registry, water exclusions, and routine cadence are governed by the current shared architecture while AIO-specific semantics remain child-owned.

&nbsp;

# 35\. Shared Economic-Unit Contract

All enrichment providers must declare the economic unit on which billing and deduplication operate. Examples include canonical business/GBP, canonical domain, canonical URL/page, review corpus or incremental review ID, citation URL, brand × query × period, content hash, or another provider-native unit. The scheduler must compute a canonical request signature from provider, endpoint/product, economic unit, requested fields/scope, location/device where relevant, and freshness window before purchasing.

&nbsp;

If Maps and AIO request equivalent data for the same canonical economic unit and time window, one provider purchase satisfies both and both module reasons are attached to the resulting snapshot. If the requested scopes differ, the scheduler should purchase the least expensive superset that satisfies both only when that does not change scientific semantics or materially increase cost.

&nbsp;

# 36\. Observation Reuse Contract

A provider response may feed multiple surface parsers only when the request conditions and returned payload satisfy each child methodology. Reuse must never be inferred merely because two modules use the same keyword text. Query, location, coordinates, device, language, time window, provider settings, depth, result type, and required presentation fields must be equivalent for the intended analysis.

&nbsp;

AIO and Maps observations remain separate channel outcomes even when derived from the same provider payload. No universal Maps+Organic+AIO visibility score is authorized. Shared raw storage and canonical IDs enable joining; they do not collapse outcome semantics.

&nbsp;

# 37\. Evidence-System Compatibility

The parent finding registry stores common evidence metadata and allows child-specific evidence taxonomies. The Maps PRD and AIO PRD currently use related but not identical evidence labels. Implementation must not silently translate one module’s label into another. Store evidence\_taxonomy, evidence\_label, evidence\_dimensions, recommendation\_confidence where applicable, applicability, actionability, proxy risk, supporting artifacts, model/methodology versions, and operational eligibility as separate fields.

&nbsp;

Cross-surface findings require a platform-level evidence assessment derived from their own cross-surface methodology; they may reference child findings but do not inherit the strongest child label automatically. An LLM may explain these classifications but may not assign or upgrade them outside version-controlled research logic.

&nbsp;

# 38\. Refactoring Rules for Child PRDs

The child PRDs should eventually be revised to reference this parent PRD for shared architecture rather than maintain duplicate implementations. During that refactor, do not delete surface-specific requirements merely because they mention shared entities or providers. Replace only duplicated mechanics with references to the parent while retaining the module-specific eligibility condition, measurement semantics, cadence override, analytical use, and acceptance criteria.

&nbsp;

The first child-refactor targets are canonical taxonomy/entity tables, raw-observation immutability, provider/economic-unit deduplication, cache/freshness mechanics, api\_usage accounting, shared storage/orchestration, finding/intervention infrastructure, and common LLM quantitative guardrails. The first items that must remain in the children are Maps geometry/cohorts/outcomes and AIO visibility/presentation/query-family taxonomies.

&nbsp;

&nbsp;

# 39\. Python/SQL Before LLM Computational Policy

The platform must default to deterministic computation before LLM inference. If a field, metric, transformation, comparison, classification, or decision input can be produced reliably and reproducibly with Python, SQL, provider metadata, DOM parsing, regular expressions, vector arithmetic, or version-controlled rules, an LLM must not be the default implementation. LLM usage is reserved for tasks where semantic interpretation, ambiguity resolution, qualitative synthesis, or natural-language explanation provides material value.

&nbsp;

Python/SQL-owned work includes, at minimum: URL normalization and canonicalization; domain extraction; tracking-parameter removal; text normalization and hashing; HTML/DOM parsing; title, heading, schema, word-count and link extraction; NAP normalization; geographic distance and coordinate calculations; rank, coverage, DAVS and Effective Ranking Radius calculations; SERP overlap and Jaccard/rank-correlation calculations; citation persistence; deltas and change detection; cohort construction; feature engineering; aggregations; statistical tests and models; event-study calculations; anomaly detection; API-cost calculations; TTL/freshness evaluation; request-signature deduplication; and report/client evidence-packet assembly.

&nbsp;

Provider-returned structured facts must be parsed directly rather than sent to an LLM for re-extraction. This includes ranks, URLs, domains, place IDs, ratings, review counts, coordinates, categories, citation URLs, SERP element types, and other sufficiently structured provider fields. An LLM may not be inserted merely as a convenience parser where deterministic extraction is available.

&nbsp;

Embeddings are reusable semantic representations, not repeated reasoning calls. Each normalized textual artifact must be embedded at most once per normalized content hash × embedding model × embedding-model version unless an explicitly versioned methodology requires otherwise. Query embeddings, page embeddings, page-chunk embeddings, review embeddings, social-content embeddings, GBP-update embeddings, AIO-answer embeddings, citation-passage embeddings, and transcript embeddings must be reusable across modules, queries, weeks, and analyses when the underlying content and model version are unchanged.

&nbsp;

Semantic similarity must be computed locally from stored vectors wherever mathematically sufficient. Cosine similarity, nearest-neighbor retrieval, best-passage selection, query-to-page similarity, AIO-to-page similarity, query-to-review similarity, social-topic relevance, clustering, and related vector operations should use Python/NumPy, pgvector/Postgres, or equivalent deterministic vector infrastructure rather than repeated LLM calls. A page should be deterministically chunked once per content version, its chunks embedded once, and future best-passage queries resolved through vector search rather than resending the full page to an LLM.

&nbsp;

LLM classification should be gated whenever a cheaper deterministic or embedding-based stage can safely eliminate irrelevant or already-resolved records. The preferred funnel is deterministic rules → cached classification lookup → embedding/vector relevance test → LLM only for unresolved or research-relevant cases. Known-domain source types, platform identities, Google-owned/open-web classification, obvious schema/page types, and other high-confidence rule-based cases should bypass the LLM. Ambiguous cases may be escalated with the rule result, confidence, and provenance preserved.

&nbsp;

Raw data should not be repeatedly placed into LLM context for recurring analysis. Python/SQL must first calculate material changes, feature snapshots, cohort comparisons, anomalies, statistical outputs, and applicable finding IDs. Research summaries should be delta-driven: weekly for Sentinel changes and monthly for full-panel changes. Client Mode should construct a compact deterministic Client Evidence Packet containing client features, matched-comparator features, applicable findings, material gaps, contra-evidence, intervention history, measurement windows, and confidence/evidence metadata. The LLM's role is to explain and synthesize that packet, not rediscover measurements from the raw warehouse.

&nbsp;

Model or prompt upgrades do not automatically authorize full historical reprocessing. Historical embeddings or classifications should be recomputed only when a bounded validation demonstrates material analytical benefit, a specific research analysis requires cross-version comparability, or a methodology-versioned migration is approved. Prospective use of a new model is permitted while older derived artifacts retain their model and prompt/schema provenance.

&nbsp;

The platform must instrument LLM efficiency alongside API efficiency. For every LLM or embedding request, record model, model version, prompt/schema version where applicable, input tokens, output tokens, cached/reused status, content hash or artifact IDs, module/research reason, estimated and actual cost when available, and whether deterministic or cached alternatives were evaluated. Operational dashboards should report tokens and cost avoided through cached embeddings, deterministic parsing, local vector math, classification gating, delta-driven context construction, and skipped historical reprocessing.

&nbsp;

Acceptance rule: no production LLM task should exist without an explicit semantic justification. Engineering review must be able to answer why deterministic Python/SQL/provider parsing/vector math is insufficient for that task. If the answer is only implementation convenience, the task should be moved out of the LLM layer

# 40\. Statistical Design & Causal-Inference Governance

All strategy-eligible analyses must be governed by a versioned Analysis Specification Contract before confirmatory execution. The contract must declare the research question, hypothesis, population of inference, analytical grain, outcome, exposure, estimand, plausible confounders, mediators/downstream variables, colliders or prohibited adjustments, matching variables, prohibited matching variables, time zero, exposure window, lag, outcome window, clustering/repeated-measures structure, missingness and censoring policy, primary model, sensitivity models, multiple-testing family/method, discovery-versus-confirmatory status, validation population, holdout strategy, minimum effect of practical interest, code version, and methodology version. Exploratory analyses may be registered after discovery only as exploratory hypotheses; they cannot be represented retrospectively as preregistered confirmatory tests.

Control selection must be exposure- and estimand-aware. A candidate exposure must not be used as a matching criterion for an analysis estimating its relationship with the outcome. Mediators and colliders must not be automatically adjusted for merely because they are available. When an analysis intentionally conditions on a mediator—for example, asking whether backlink strength contains information beyond Organic rank—the specification must state that the estimand differs from the total exposure relationship. Control-selection logic must preserve the matching variables, prohibited variables, selection reason, selection version, and effective period.

The platform must explicitly distinguish market-eligible businesses, Google-observed competitors, and deep-enriched competitors. Findings must state which population they represent and must not generalize from an observed or selectively enriched population to all eligible businesses without supporting design. Module-level random-reference cohorts drawn from observed competitors remain useful but do not constitute population-random samples. A separate Population Reference Cohort should periodically sample businesses independently of current Maps/AIO visibility where feasible so selection into the observable Google result universe can itself be studied.

Selective enrichment is informative missingness. Every signal used analytically must distinguish observed values from NOT\_ELIGIBLE, NOT\_SELECTED, NOT\_YET\_COLLECTED, PROVIDER\_FAILURE, NO\_DATA\_EXISTS, STALE, BUDGET\_LIMIT, TECHNICAL\_FAILURE, and other versioned missingness states. Missing must never be silently encoded as zero. Analyses using selectively enriched signals must restrict inference to an appropriate eligible population, model or characterize the selection mechanism, use weighting/sensitivity methods where justified, and/or use reference samples that make selection bias measurable.

Discovery, validation, and replication are separate stages. Broad exploratory discovery must use a declared multiple-testing family and an appropriate false-discovery procedure; Benjamini-Hochberg FDR is the default starting method for broad exploratory feature searches unless the analysis specification justifies another method. A discovery result cannot become operational evidence solely because it is statistically significant. Validation must lock the exposure, outcome, adjustment set, model, and effect definition before testing on held-out markets, businesses, verticals, queries, or time. Strong operational evidence should additionally survive prospective replication on future observations not used for discovery or model selection when feasible.

Every model must declare its independence/repeated-measures structure. Statistical output must report raw observation count plus relevant unique businesses, markets, queries/query families, weeks/periods, and other effective analytical units. Large SERP row counts must not be represented as equivalent to the same number of independent experiments. Clustered standard errors, fixed/mixed effects, hierarchical models, block/bootstrap methods, or other suitable repeated-measures methods must be selected according to the analysis specification.

Temporal models must prevent future-data leakage and reverse-time storytelling. Features used to explain or predict an outcome at time T must be demonstrably available at or before the allowed exposure cutoff. Lead/placebo tests should be supported where useful. Cohort labels, enrichment eligibility, entity state, and derived classifications created after T must not leak future knowledge into historical validation datasets.

Cross-surface evidence must distinguish cross-surface association, temporal precedence, and causal evidence. A finding that Organic visibility improves before Maps visibility, or Maps prominence precedes AIO selection, is not evidence that one Google surface caused the other; common causes such as brand demand, website changes, business growth, market movement, or Google-system changes may affect multiple surfaces. Cross-surface causal claims require a design capable of isolating the relevant mechanism and must receive their own platform-level evidence assessment.

Confirmatory analyses must define a Minimum Effect of Practical Interest or explicitly document why one cannot yet be specified. Statistical significance alone is insufficient for strategy. The Strategy Engine must consider effect magnitude, uncertainty, intervention cost, reversibility, expected lag, and commercial relevance. Expensive experiments or enrichment expansions should use power/precision analysis based on observed prevalence, variance, clustering, and a plausible effect size before scale-up when enough pilot data exist.

Negative controls are first-class research tools. Where appropriate, analysis and intervention plans should identify unaffected queries, services, markets, outcomes, entities, or time windows that should not respond to the hypothesized mechanism. Broad movement across target and negative-control outcomes is evidence against a narrow intervention interpretation and must be preserved as contra-evidence.

Client interventions must support intervention\_bundle\_id or an equivalent grouping mechanism. When multiple changes occur within a window too close to separate their effects credibly, evidence must be attributed to the bundle rather than manufacturing component-level causality. Intervention analysis should preserve baseline/pre-trend windows, exact implementation timing where possible, expected lags, primary outcomes, negative controls, comparison strategy, concurrent/co-interventions, and market/Google-wide changes.

# Acceptance rule: no finding may become platform-level operational evidence unless its population, estimand, timing, adjustment logic, missingness treatment, dependence structure, validation state, effect magnitude, uncertainty, and applicable evidence taxonomy are reconstructable from structured/versioned records.

&nbsp;

41\. Research-Universe Calibration & Efficiency Experiments

Permanent longitudinal observations must not be reduced merely to save money. Potential methodology reductions must be earned through bounded validation experiments and explicit methodology versioning.

# AIO query selection must use a reproducible sampling frame rather than relying only on subjective labels such as natural or high-value. Candidate queries should preserve demand evidence where available, intent, query family, commercial/research relevance, selection reason, demand source/estimate, and sampling weight where appropriate. The platform must distinguish standardized panel prevalence—the percentage of the fixed research panel producing AIO—from any estimate of real-world search-demand-weighted prevalence. The latter requires a defensible demand-weighting methodology and must never be inferred automatically from the constructed panel.

A permanent AIO calibration subset should begin early enough to measure sensitivity to device and searcher location before broad strategic conclusions are generalized. Use a bounded, stratified subset to compare desktop versus mobile and the primary market coordinate versus selected fixed secondary coordinates. Measure AIO trigger agreement, source/citation agreement, business-selection agreement, presentation-surface agreement, and relevant placement differences. Expansion to the full universe is not required unless measured disagreement makes the primary design inadequate.

The former 73-point Maps design is retained only as historical/high-resolution validation provenance and is not a routine production requirement. The first Maps/Organic implementation pilot collects the full 13-point cardinal geometry while tagging a nested 9-point candidate. That pilot must compare 9 versus 13 on marginal unique canonical entities, paid downstream enrichment, spatial information, distance decay, directional asymmetry, visibility-radius behavior, expansion/contraction, longitudinal transition information, and explanatory-variable variation. AIO uses its separately approved 9-point geometry. Any steady-state Maps/Organic change from 13 to 9 requires an explicit versioned post-pilot methodology decision.

AIO geometry/rectangle collection should be treated as a measurable subfeature rather than assumed universally necessary forever. After the initial rendered-SERP validation, evaluate whether full-universe rectangle collection materially improves placement, above-fold, card, or embedded-GBP research compared with a stratified presentation-measurement panel. A reduced geometry panel is permitted only if raw AIO/source/entity/destination outcomes remain intact and the methodology change is versioned.

Google Business Q\&A must not be assumed either active or obsolete solely from provider endpoint availability. Before making it a recurring signal, run a bounded validation sample that measures returned-data rate, age of newest questions, longitudinal appearance of new questions, and whether the data correspond to a currently meaningful Google surface. Depending on results, classify Q\&A as an active signal, historical entity corpus, or retired collection layer. Until validated, Q\&A must not be required for V1 production enrichment or strategy evidence.

Social, external-review, deep semantic, and other high-variance enrichment families must earn broad scale. Begin with stratified pilots containing visible/winner entities, matched controls, transition entities, and reference entities. Measure incremental predictive/explanatory contribution beyond already-collected signals, coverage, missingness, cost, and research findings supported before expanding to thousands of businesses or additional platforms.

# The platform must maintain a formal Signal Value Review at least every 3–6 months once enough history exists. For each material signal family evaluate collection cost, compute/storage cost, coverage, missingness, variance, model usage, findings supported, unique contribution beyond correlated signals, and intervention/strategy value. Allowed decisions are KEEP, REDUCE, EXPERIMENTAL\_ONLY, EVENT\_TRIGGER\_ONLY, or RETIRE. Signal retirement or cadence reduction is a methodology-versioned decision and must not rewrite historical data.

&nbsp;

42\. Enrichment & Semantic Processing Efficiency Contract

The platform has three economic layers: Layer 1 MUST COLLECT contains irrecoverable time-sensitive search-surface observations; Layer 2 COLLECT WHEN NEEDED contains enrichment such as links, GBP, reviews, social, content, citations, and site architecture; Layer 3 COMPUTE LOCALLY contains distance, similarity, DAVS/ERR, cohorts, deltas, persistence, feature engineering, statistics, findings, and report packets. Cost optimization must protect Layer 1, aggressively deduplicate and gate Layer 2, and avoid external API/LLM use for Layer 3 unless an explicit exception is justified.

All reusable text must be content-addressed. A normalized content\_asset/content-version record should own the authoritative text/hash and be referenced by repeated observations rather than duplicating full text across collection periods or modules. Embeddings belong to content hash × embedding model × model version, not to a query, week, module, or experiment. Page chunks are deterministic content-version children and are embedded once per model version.

Semantic processing uses embeddings and local vector arithmetic before structured LLM classification. Query/page, query/review, query/social, query/GBP-post, AIO/page, best-passage, clustering, and related similarity work must be calculated from stored vectors locally. Structured LLM extraction is authorized only when the required analytical variable cannot be obtained reliably through deterministic parsing, provider fields, rules, or embedding/vector features and the record passes the Section 39 gating policy.

Weekly backlink monitoring must distinguish lightweight summary snapshots from deep inventories. Weekly eligible snapshots may collect RD, backlinks, dofollow/RD measures, new/lost RD, and provider-native authority metrics required by module methodology. Full backlink graphs, large anchor distributions, source-URL inventories, and contextual-link corpora are baseline/deep/event/experimental work and must not be refreshed weekly without a registered analysis need.

Review semantics should be staged. Preserve required raw review records and quantitative review metrics, embed each unique review text at most once per model version, and compute relevance locally. Structured semantic extraction should focus on focal/transition entities, matched controls, statistically justified samples, or analyses that specifically require categorical fields. Social semantic processing follows the same rule; collecting a post does not automatically authorize an LLM classification call.

Raw provider JSON and HTML should be compressed in object storage and referenced from normalized hot tables by immutable ID/path/checksum. Repeated normalized rows must not contain duplicate large payloads. Storage retention should distinguish irreplaceable raw observations from reproducible transient fetch artifacts while preserving everything needed for reparse/research reproducibility.

Exact request-signature deduplication applies across modules. The signature must include provider/product, search engine, keyword/query ID, location and coordinates where relevant, language, device, depth, AIO/geometry options, requested fields/scope, economic unit, and the applicable observation/freshness window. Reuse is allowed only when the signature and child methodology are scientifically equivalent.

LLM and enrichment workers must be auditable for avoided work. Telemetry should report deterministic resolutions, cache hits, embedding reuse, vector comparisons performed locally, classifications bypassed, duplicate provider requests prevented, deep inventories avoided, content unchanged, and historical reprocessing skipped.

&nbsp;

# 43\. Child-PRD Inheritance & Implementation Precedence

The Maps/Organic, AIO, and ChatGPT PRDs are authoritative module specifications under this parent. Shared implementation mechanics in the children are inherited from and constrained by the newest parent rule. Child text remains authoritative for surface-specific methodology, eligibility, cadence overrides, outcomes, taxonomies, and acceptance criteria, but duplicated shared mechanics must not be implemented as independent module stacks.

For shared canonical entities, raw-observation storage, request/economic-unit deduplication, signal warehouse, content assets/hashes, embeddings, LLM gating, queueing, cost accounting, missingness states, Analysis Specification Contracts, validation/replication stages, intervention infrastructure, and shared finding infrastructure, this parent PRD controls. If older child text would cause duplicate implementation or a weaker shared guardrail, engineering must follow the parent and preserve the child's scientific intent through module-specific configuration/overrides.

Maps-specific invariants remain protected where they do not conflict with the 2026-09-09 governing collection architecture: Top-10 retention, distance methodology, approved Maps cohorts, DAVS/Effective Ranking Radius research, Maps-specific eligible signal cadences, and Maps Client Mode methodology. The former 10 × 20 × 2, 73-point, weekly-full production design is superseded. Current implementation uses 25 × 50 × 4; the first Maps/Organic pilot collects 13 points with a tagged nested 9-point production candidate; routine full-panel cadence is monthly with a weekly fixed Sentinel.

AIO-specific invariants remain protected, including its versioned 25-industry × 50-market research universe, source/entity/destination visibility separation, local-business-card and embedded-GBP presentation semantics, SearchViewer destination semantics, AIO controls/transitions/persistence, and the Strategy Evidence Framework. Routine AIO full-panel collection uses the approved 10-condition panel and 9-point geometry, with monthly full-panel cadence and the fixed weekly Sentinel subset. Sampling/calibration rules refine interpretation; they do not authorize silent mid-version panel changes.

The children should be refactored to replace duplicated platform mechanics with explicit parent references while retaining all module-specific conditions. Until that textual refactor is complete, this section is the implementation precedence rule.

&nbsp;

44\. Cross-Surface Cost Model & Overlap Economics

&nbsp;

The platform must model costs at the shared-platform level rather than by summing isolated module budgets. Cross-surface overlap changes enrichment economics but does not automatically reduce the permanent observation burden. Surface observations required by a child methodology remain independently protected even when the same canonical business appears in Maps, AIO, ChatGPT, Organic, or another surface. A business appearing on three surfaces is three surface outcomes but, where provider scope and freshness are equivalent, only one canonical enrichment target.

&nbsp;

The cost model must therefore separate at least four economic layers: (1) protected surface observation cost; (2) canonical business/GBP enrichment cost; (3) canonical domain and URL enrichment cost; and (4) content/semantic/compute/storage cost. Cross-module overlap is applied only at the economic unit where reuse is scientifically valid. A nominal 30% overlap in businesses must never be represented as a 30% reduction in total platform cost.

&nbsp;

For planning and validation, the platform must measure overlap empirically at multiple levels rather than maintain one generic overlap percentage. Required metrics include business-surface records, unique canonical businesses, unique GBPs, unique canonical domains, unique canonical URLs, unique normalized content hashes, cross-surface business overlap, domain overlap, URL overlap, content-hash reuse, signal cache-hit rate, equivalent provider requests prevented, and actual dollars avoided. Pairwise Maps↔AIO, Maps↔ChatGPT, AIO↔ChatGPT and three-way overlap should be reportable separately because a single 30% headline can conceal materially different reuse opportunities.

&nbsp;

The canonical deduplication ladder is observation → business/GBP → domain → URL → content hash → signal snapshot. Observation records are never collapsed merely because their entities overlap. Entity enrichment belongs to the canonical business/GBP; domain-wide metrics belong to the canonical domain; URL-level authority/content/schema/page metrics belong to the canonical URL; embeddings and other content-derived reusable artifacts belong to normalized content hash × model/version; and time-varying provider metrics belong to the provider's declared economic unit × applicable freshness window.

&nbsp;

The scheduler must evaluate each requested enrichment against this ladder before purchase. If a Maps entity, AIO entity, and ChatGPT entity resolve to the same business and request an equivalent fresh GBP signal, one purchase satisfies all qualifying reasons. If multiple modules reference the same domain, domain-level enrichment is purchased once per valid freshness window. If they reference the same URL, URL-level enrichment is reused. If different URLs normalize to unchanged content already represented by the same authorized content hash, downstream embedding/classification work is reused according to the content-addressing contract. Module attribution and research reasons remain many-to-one even when the economic purchase is one-to-one.

&nbsp;

Current provider pricing must be stored as versioned cost assumptions rather than hard-coded methodology. As of the September 2026 planning update, DataForSEO lists Google Maps Standard Queue at $0.0006 per SERP page and Google AI Mode Standard Queue at $0.0012 per SERP page. Provider pricing can change and must be refreshed in the cost registry without changing historical actual-cost records.

&nbsp;

For the current production panel, the maximum pre-water-exclusion full snapshot is 25 industries × 50 markets × four queries × 13 candidate coordinates \= 65,000 Maps observations. The fixed 5-industry × 10-market Sentinel adds 2,600 Maps observations per incremental weekly Sentinel run; in a normal month the full snapshot doubles as that week's Sentinel, so three additional Sentinel runs add 7,800 Maps observations. Actual volume is lower where water points are structurally excluded.

&nbsp;

AIO observation economics must use the authoritative AIO panel and actual eligible coordinates. Before structural-water exclusions, a monthly full snapshot contains 25 × 50 × 10 × 9 \= 112,500 AIO/AI Mode observations. Historical 65,000-full / 2,600-Sentinel AIO calculations are superseded and must not drive implementation. Sentinel workload must be generated from the approved Sentinel manifest and the surface-specific query/geometry membership rather than copied from the former 13-point/four-query design. Provider rates remain versioned operational assumptions rather than methodology constants.

&nbsp;

ChatGPT full-panel observation volume is now locked for planning at 25 × 50 × 10 prompts × exactly 3 independent fresh-context replicates \= 37,500 observations per monthly full wave. Provider price remains a versioned operational assumption; at a hypothetical effective rate p per result page, raw full-wave collection cost is 37,500 × p before retries or authorized variants. The former weekly C × 52/12 and one-anchor/four-prompt planning formulas are superseded.

&nbsp;

The combined steady-state budget must therefore be produced from measured workload and provider rates, not from an assumed percentage saving. For operational planning only—not as a validated finding—the current architecture supports a provisional non-ChatGPT planning target around $550/month for Maps/AIO observation plus shared enrichment, crawling/content, embeddings, database/compute, and operating headroom under the assumptions used in the September 2026 planning exercise. A practical initial non-ChatGPT platform ceiling around $750/month may be used as a budget guardrail while ChatGPT collection and real enrichment volumes are calibrated. These figures are planning allowances, not locked empirical costs, and Section 27's requirement for measured baselines remains controlling.

&nbsp;

A 30% shared-business scenario should be treated as a sensitivity case. It is expected to reduce the addressable duplicate-enrichment pool, not protected surface observations. Until actual entity/domain/URL/content overlap and provider usage are observed, no precise savings percentage is authorized. Illustrative comparisons such as isolated-module versus shared-platform cost may be used for capacity planning only and must be labeled modeled, not measured. Once stable runs exist, modeled figures must be replaced by actual unique economic-unit counts, actual cache/reuse rates, and actual avoided spend.

&nbsp;

The cost ledger must support both gross-demand cost and net-purchased cost. Gross-demand cost estimates what all module requests would have cost if independently fulfilled; net-purchased cost records what was actually purchased after deduplication and freshness reuse. avoided\_duplicate\_cost \= gross\_equivalent\_purchase\_cost − net\_equivalent\_purchase\_cost for requests demonstrably satisfied through valid reuse. This metric must not count work skipped because a methodology did not require it, nor treat missing data as savings.

&nbsp;

Cross-surface overlap is also a research asset. The platform should maintain explicit overlap cohorts such as Maps+AIO+ChatGPT visible, Maps-only/AI-weak, AI-strong/Maps-weak, AIO-cited/ChatGPT-not-recommended, and other analysis-defined combinations. These are descriptive cohort labels, not causal categories. They enable matched cross-surface research using the same canonical signal universe while remaining subject to the Statistical Design & Causal-Inference Governance contract.

&nbsp;

Acceptance rule: engineering must be able to reconstruct, for any reporting period, protected observation spend by surface; gross enrichment demand; unique canonical economic units purchased; reused snapshots by module; duplicate provider calls prevented; embedding/content work avoided; actual net spend; modeled versus measured cost assumptions; and the resulting avoided duplicate cost without weakening any locked permanent-panel methodology.

&nbsp;

&nbsp;

HISTORICAL COLLECTION METHODOLOGY SNAPSHOT — 2026-09-09 — SUPERSEDED IN PART

&nbsp;

Status: HISTORICAL / SUPERSEDED IN PART. This block preserves an earlier same-day collection snapshot for provenance only. It is non-operative wherever it conflicts with the reconciled current architecture: Maps/Organic pilot \= full 13 with nested 9 candidate; AIO \= 10 conditions × 9 points; ChatGPT \= 10 prompts × 3 fresh-context replicates and no grid; Top-50 evidence replaces universal social site-search/activity requirements.

&nbsp;

1\. Core Research Panel

\- 25 industries × 50 permanent markets.

\- Four canonical query classes per industry-market:

  1\) \[service\] near me

  2\) best \[service\] near me

  3\) \[industry-specific high-need/commercial modifier\] \[service\] near me

  4\) \[service\] in \[city\]

\- The high-need/commercial modifier is industry-specific and must be defined prospectively in the query registry. It must not be changed retrospectively because of observed results.

\- The same canonical query intent should be observed across Maps, AI/AIO, and Organic wherever the provider supports the matched query/location design.

&nbsp;

2\. HISTORICAL — Former Cross-Surface 13-Point Spatial Panel (AIO superseded; Maps/Organic pilot only)

Each market begins with 13 deterministic candidate coordinates:

\- market center;

\- North, South, East, and West at 1 mile;

\- North, South, East, and West at 3 miles;

\- North, South, East, and West at 5 miles.

For Maps/Organic, these 13 coordinates are collected in the first pilot and the nested 9-point candidate is tagged within them; the post-pilot production geometry remains to be chosen explicitly from measured 9-vs-13 value. AIO does not use this geometry; it uses its separately approved 9-point panel. Coordinates are deterministic, not randomized each run.

&nbsp;

Water exclusion rule: if a candidate coordinate falls over an ocean, lake, or river, exclude that point. Do not randomize it, relocate it, rotate the bearing, or substitute another point. Record the exclusion reason and retain it as structural missingness. A water-excluded point is not a failed observation and must never be encoded as rank zero, no visibility, or a negative outcome. Market-level denominators must use valid eligible coordinates rather than assuming 13 observations in every market.

&nbsp;

Store separately: (a) distance from market center to search coordinate and (b) distance from each observed business to the search coordinate. These are different variables and must not be conflated.

&nbsp;

3\. HISTORICAL — Former Matched Three-Surface Observation Design

Primary surfaces are Google Maps, Google AI/AIO/AI Mode as implemented by the selected DataForSEO endpoint, and Google Organic Top 10\. Coordinate targeting is used wherever supported so observations can be paired by industry, market, query class, coordinate, and collection window.

&nbsp;

Organic observations preserve rank, URL, canonical domain, title/available SERP metadata, query, coordinate, timestamp, and SERP features. A business is not excluded from explanatory-variable enrichment merely because it appears only on Organic. Organic must still use the shared universal inexpensive baseline and analysis-specific/selective deeper enrichment subject to canonicalization, cache/TTL checks, provider economic-unit deduplication, and surface-approved signal rules; it must not create an unbounded duplicate purchase path.

&nbsp;

Maps and AI/AIO observations use the shared global canonical entity registry and globally deduplicated enrichment cache. Enrichment is purchased by the appropriate economic unit, never per repeated SERP observation.

&nbsp;

4\. Collection Cadence

Full panel: monthly.

Sentinel panel: weekly, using a fixed representative subset of 5 industries × 10 markets and the same four query classes, eligible permanent coordinates, and three primary surfaces. The monthly full-panel collection counts as that week's Sentinel observation; normally only three additional Sentinel collections are required between monthly full snapshots.

&nbsp;

The Sentinel exists to detect material structural change, not to substitute a second research methodology. Predefined change thresholds may trigger an unscheduled full-panel snapshot. Trigger definitions must be specified before evaluation and logged with the reason for the exceptional collection.

&nbsp;

5\. HISTORICAL — Former Three-Surface Panel Scale Before Water Exclusions

Historical snapshot only: the former matched-three-surface design modeled 65,000 SERPs per surface / 195,000 total. DO NOT IMPLEMENT these totals. Current monthly full-panel raw planning volumes before structural exclusions are Maps 65,000; Organic 65,000; AIO 112,500; ChatGPT 37,500; total 280,000.

Sentinel candidate volume: 5 × 10 × 4 × 13 \= 2,600 SERPs per surface, or 7,800 observations per Sentinel run. Three incremental Sentinel runs add 23,400 candidate observations in a normal month.

Routine candidate total before water exclusions: 218,400 SERP-level observations/month, or 2,620,800/year at twelve equal months. Actual collected volume will be lower where water exclusions remove coordinates.

&nbsp;

6\. Overlap and Cost Modeling

An 85% cross-query business-overlap assumption may be used ONLY for financial planning and capacity modeling. It is not a research finding and must not be inserted into analytical results as observed overlap. The system must measure actual marginal-new-entity rate, pairwise and multi-query overlap/Jaccard, cross-coordinate overlap, Maps↔AI/AIO overlap, and month-over-month entity persistence/churn.

&nbsp;

Month 1 is expected to have higher baseline enrichment demand. Month 2+ should rely on the canonical entity registry, variable-specific TTLs, content/change detection, and incremental refreshes.

&nbsp;

7\. Social and Other Enrichment

Social profile/post acquisition remains entity-level and deduplicated. Broad profile-level collection and periodic verification are preferred. Do not scrape complete social post histories for every observed company every month. Deeper post collection should be sampled, change-triggered, periodically scheduled where justified, or targeted to a specific social artifact cited by an AI surface.

&nbsp;

8\. CURRENT MAPS/ORGANIC PILOT — Validation of Nested 9 vs Full 13

During the first Maps/Organic pilot, collect the full eligible 13-point geometry and tag the nested 9-point candidate plus the four incremental points. Compare unique business/entity discovery, incremental SERP observations, downstream paid enrichment and processing/storage costs, distance-decay information, directional asymmetry, visibility-radius behavior, expansion/contraction, longitudinal transitions, and explanatory-variable variation. Do not assume 13→9 produces proportional enrichment savings. Compare the marginal annual cost of points 10–13 against their marginal unique entities plus spatial, longitudinal, and explanatory information. The former 73-point design is historical/validation-only and is not the current production-selection comparison.

&nbsp;

9\. Epistemic Requirements

Hypotheses are not findings. Correlation does not establish causation. Predictive importance does not establish a ranking/recommendation factor. Missing does not equal zero. Retrieved, cited, linked, mentioned, recommended, ranked, and absent are distinct states where applicable. LLMs must not manufacture quantitative findings. All cross-surface conclusions must preserve the observation and missingness semantics of the source surfaces.

&nbsp;

10\. Supersession

Where older shared-platform text specifies a conflicting weekly full-panel cadence, a 73-point production grid, two or five production queries, smaller market/industry breadth, or Organic-triggered enrichment, this 2026-09-09 governing collection methodology supersedes it. The 73-point design remains a pilot/validation benchmark rather than the routine production grid.

&nbsp;

45\. HISTORICAL / SUPERSEDED — Universal Indexed-Social Evidence & 90-Day Activity Layer

Status: SUPERSEDED FOR CURRENT PRODUCTION. Preserve this section only as methodology provenance and possible validation-experiment context. Do not implement its universal platform-restricted site: searches, universal Top-20 social SERPs, universal 90-day profile checks, or the resulting historical cost model. Current production uses the business-centric Brand \+ Service \+ Location Top-50 evidence layer, with selective direct-social enrichment only when empirically or analytically justified.

&nbsp;

RECONCILIATION NOTICE — 2026-09-09: The universal site-restricted indexed-social design and universal 90-day official-profile activity requirements in the following historical Section 45 subsections are superseded for current production by the shared Brand \+ Service \+ Location Top-50 Search-Evidence Layer and selective direct-social enrichment. Do not schedule universal Facebook/Instagram/YouTube/Reddit site: searches or universal 90-day profile checks from the historical text below. Preserve it only as methodology provenance/validation context.

&nbsp;

45.1 HISTORICAL ONLY — Objective and construct separation

The platform will universally measure two distinct social constructs where applicable: (A) lightweight first-party social activity during the 90 days preceding the observation date; and (B) Google-indexed social evidence for the target service × market across Facebook, Instagram, YouTube, and Reddit. These constructs must remain separate from AIO social citation and from underlying unindexed social content. No generic Social Authority score is authorized.

&nbsp;

45.2 HISTORICAL ONLY — Industry × market indexed-social searches — DO NOT SCHEDULE

For every Full Panel industry × market cell, run platform-restricted Google Organic searches for Facebook, Instagram, YouTube, and Reddit using the frozen target service/query treatment and city/market. Conceptual example: site:instagram.com emergency plumber phoenix. The final syntax, quoting, location/device settings, and service/city normalization are frozen after pilot validation and stored under a social\_query\_version.

Retain Top 20 results per platform query. At 25 industries × 50 markets × 4 indexed platforms this produces 5,000 platform-restricted searches per full social/community pass and at most 100,000 result rows before deduplication/relevance filtering. Reddit is primarily a third-party/community corroboration and recommendation surface; it is not part of the direct official-profile activity layer. Social searches are not multiplied by the number of GBPs or canonical businesses.

&nbsp;

45.3 Evidence classification and third-party discovery

For each returned social result, preserve raw SERP provenance and classify service relevance, market/geographic relevance, service × geography relevance, platform, result/artifact type, represented/mentioned business entities, and evidence ownership.

Evidence ownership classes are first\_party, third\_party, and ambiguous/unknown. Third-party evidence includes customers, community accounts, influencers/creators, media, partners, organizations, or other independent accounts that discuss, recommend, feature, review, tag, or otherwise corroborate a measured business. Do not infer independence merely from a different handle when ownership is uncertain.

Every relevant business discovered through these social SERPs must be retained and entity-resolved even when it was not previously present in Maps/AIO. Cross-reference against the canonical registry and store matched\_to\_maps\_entity, matched\_to\_aio\_entity, matched\_to\_organic\_entity where applicable, match confidence, and evidence. This supports both Maps→social and social→Maps/AIO analysis.

&nbsp;

45.4 HISTORICAL ONLY — Lightweight 90-day first-party activity — DO NOT SCHEDULE UNIVERSALLY

For every canonical business with a confidently resolved official Facebook, Instagram, or YouTube profile, perform the minimum economical collection required to determine whether that profile posted within the previous 90 days. Prefer newest-first metadata retrieval, early stopping, cached profile mappings, and global social-profile deduplication. A profile shared by multiple locations is checked once and linked to each applicable entity.

Required fields include social\_profile\_resolved, platform, social\_active\_90d, latest\_observed\_post\_date where obtainable, days\_since\_last\_post, platform\_active\_90d, and active\_social\_platform\_count\_90d. Exact post counts are optional when cheaply returned; the production layer does not require downloading every 90-day artifact merely to establish activity.

Missingness states must distinguish unresolved/ambiguous/private/inaccessible/unavailable from observed inactivity. Missing is not zero.

&nbsp;

45.5 Prohibited universal expansion in V1

The universal production layer does not authorize full 90-day post-body ingestion, fixed 10/20/50-post corpora, comment-body scraping, video transcription, or universal image understanding. Exact artifacts returned by the indexed-social SERPs or cited/linked by an AI surface may be preserved/analyzed as observed evidence. Deeper direct-social collection remains a versioned validation or explicitly approved research experiment.

&nbsp;

45.6 Processing hierarchy

Apply deterministic URL/entity/service/location parsing first, cached classifications second, embeddings/vector relevance where useful third, and LLM classification only for unresolved cases. Preserve classification confidence and model/rule provenance. Entity matching must not be performed by LLM intuition alone when stable identifiers or deterministic corroboration are available.

&nbsp;

45.7 Derived variables

The warehouse must support, without forcing a composite score: indexed\_social\_evidence\_present; indexed\_first\_party\_social\_evidence\_present; indexed\_third\_party\_social\_evidence\_present; indexed\_first\_and\_third\_party\_evidence\_present; indexed\_social\_result\_count; unique\_third\_party\_social\_profiles; best\_indexed\_social\_rank; best\_first\_party\_social\_rank; best\_third\_party\_social\_rank; platforms\_with\_indexed\_social\_evidence; service\_relevant\_indexed\_social\_count; location\_relevant\_indexed\_social\_count; service\_location\_relevant\_indexed\_social\_count; maps\_business\_has\_indexed\_social\_match; social\_serp\_business\_found\_in\_maps; social\_serp\_business\_found\_in\_aio; social\_active\_90d; active\_social\_platform\_count\_90d; and days\_since\_last\_post where observed.

&nbsp;

45.8 HISTORICAL ONLY — Former cadence and temporal validity

Indexed-social Top-20 full-panel searches run quarterly by default. Lightweight 90-day activity status may refresh monthly. The system must prevent future-data leakage: activity windows are anchored to the applicable observation date, and a social SERP collected later cannot be treated as proof that the same indexed result existed or ranked identically earlier.

&nbsp;

45.9 HISTORICAL ONLY — Superseded cost model

Indexed-social/community query volume is 5,000 searches per full pass, independent of canonical-business count. Provider prices must be versioned in api\_usage and revalidated operationally. For planning only, the current design provisions approximately $200–$800 for the initial indexed-social \+ activity implementation/full pass, using approximately $500 as a working estimate, and targets approximately $600–$1,200/year recurring social research after caching/deduplication, or roughly $50–$100/month averaged. Combined with the current approximately $550/month non-social planning target, the preliminary all-in planning target is approximately $600–$650/month averaged. These are modeled allowances, not measured findings or guaranteed costs.

&nbsp;

45.10 Validation

Run a stratified direct-social validation sample before interpreting a negative indexed-social result as evidence of underlying social absence. Compare frozen site-restricted searches with direct recent-social inspection/collection and measure precision, recall where estimable, platform differences, quoted/unquoted syntax sensitivity, result-type mix, entity-match accuracy, and first-party/third-party classification accuracy. The validation sample must not become a hidden universal crawl.

&nbsp;

45.11 Epistemic rule

Indexed first-party social evidence, indexed third-party corroboration, first-party 90-day activity, underlying social content, AIO social citation, Maps visibility, and Organic visibility are separate observed constructs. Association, temporal precedence, or predictive importance does not establish that social activity or social corroboration is a Maps/AIO ranking or recommendation factor.

&nbsp;

45.12 HISTORICAL ONLY — Superseded Reddit site-search expansion

Reddit is added as the fourth platform in the universal Google-indexed social/community search layer. For every Full Panel industry × market cell, the platform-restricted search set now includes Facebook, Instagram, YouTube, and Reddit. Conceptual Reddit form: site:reddit.com \[service\] \[city\], using the same frozen service/query treatment and market normalization rules as the other indexed-social searches.

&nbsp;

This changes full-pass indexed-social/community search volume from 25 × 50 × 3 \= 3,750 searches to 25 × 50 × 4 \= 5,000 searches. At Top 20, the theoretical maximum returned result volume increases from 75,000 to 100,000 result rows before relevance filtering and deduplication.

&nbsp;

Reddit is treated primarily as indexed third-party/community evidence, but first-party business participation may be classified when a business-controlled or confidently attributable account/post is identified. Preserve subreddit, post/comment/result URL where derivable, represented business entities, service relevance, geography relevance, service × geography relevance, rank, title/snippet, observed\_at, and classification provenance. Do not assume Reddit evidence is independent merely because it appears on Reddit; ownership/affiliation remains a separate classification problem.

&nbsp;

Reddit is NOT added to the universal first-party 90-day official-profile activity check. That check remains limited to confidently resolved official Facebook, Instagram, and YouTube profiles. Reddit's production role in V1 is Google-indexed community/corroboration evidence unless a later versioned direct-Reddit methodology is approved.

&nbsp;

Cost planning must treat the additional Reddit site-restricted searches as a 33.3% increase in indexed-social query count, not as a 33.3% increase in the entire social research budget. Actual incremental cost must be measured from provider usage and recorded in api\_usage before revising the recurring all-in budget target.

&nbsp;

&nbsp;

&nbsp;

46\. Approved Industry Panel Query Registry Update — 2026-09-09

Status: LOCKED for the five industry substitutions and literal query templates explicitly approved in the 2026-09-09 methodology session. This section does not by itself lock the remaining 20 proposed industries or the proposed 50-market/Sentinel membership.

&nbsp;

The 25-industry panel is amended by the following approved substitutions:

\- Orthodontics → Optometry

\- Dermatology → Urgent Care

\- Property Management → Handyman

\- Funeral Home → Chinese Restaurant

\- Auto Body → Locksmith

&nbsp;

Approved literal canonical query templates for these replacement industries:

Optometry: Q1 \`optometrist near me\`; Q2 \`best optometrist near me\`; Q3 \`eye exam near me\`; Q4 \`optometrist in \[CITY\]\`.

Urgent Care: Q1 \`urgent care near me\`; Q2 \`best urgent care near me\`; Q3 \`walk in clinic near me\`; Q4 \`urgent care in \[CITY\]\`.

Handyman: Q1 \`handyman near me\`; Q2 \`best handyman near me\`; Q3 \`same day handyman near me\`; Q4 \`handyman in \[CITY\]\`.

Chinese Restaurant: Q1 \`Chinese restaurant near me\`; Q2 \`best Chinese restaurant near me\`; Q3 \`Chinese food near me\`; Q4 \`Chinese restaurant in \[CITY\]\`.

Locksmith: Q1 \`locksmith near me\`; Q2 \`best locksmith near me\`; Q3 \`auto locksmith near me\`; Q4 \`locksmith in \[CITY\]\`.

&nbsp;

For Locksmith specifically, \`auto locksmith near me\` is the approved Q3. \`emergency locksmith near me\` and \`24 hr locksmith near me\` are not the canonical Q3 for this methodology version. The purpose is to preserve a distinct, natural high-commercial-intent service subtype rather than merely add an urgency/availability modifier.

&nbsp;

These literal templates must be stored prospectively in the canonical query registry and used consistently across matched Maps, AI/AIO, and Organic observations wherever supported. They must not be retrospectively rewritten because observed results differ. Historical query definitions remain attached to their original methodology versions.

&nbsp;

47\. LOCKED — Platform-Wide Enrichment Economics & Progressive Processing — 2026-09-09

&nbsp;

Governing principle: Collect the permanent observational panel at the approved scientific resolution, but minimize the marginal cost of each observation through global canonicalization, economic-unit deduplication, cache reuse, change detection, appropriate TTLs, progressive processing, event-driven Sentinel enrichment, incremental histories, and study-specific deep enrichment. Observe broadly. Enrich selectively. This architecture optimizes enrichment economics; it does not reduce the approved observational panel.

&nbsp;

47.1 Universal enrichment eligibility gate

Every newly observed enrichable business, organization, domain, URL, GBP, social profile/artifact, source, backlink target, content object, or provider-specific object passes through the conceptual gate: observed → canonicalized → already sufficiently fresh? → changed materially? → analytically relevant? → paid enrichment required?

&nbsp;

Raw observations remain immutable and independent from shared enrichment. Before paid enrichment, globally deduplicate by the provider's actual economic unit. The same business/GBP, organization, domain, URL, social profile/artifact, backlink target, content hash, or provider-specific enrichment object MUST NOT be repurchased merely because it appears across multiple queries, coordinates, surfaces, waves, or result positions. Reuse sufficiently fresh scientifically equivalent shared enrichment across Maps, AI/AIO, Organic, ChatGPT, and social/community research.

&nbsp;

47.2 Incremental review collection

Universal recurring review collection emphasizes cheap current state: review count, rating, count/rating change, and derivable review velocity. Do not repeatedly repurchase complete review histories when incremental acquisition is technically possible. Historical review bodies are append-only reusable assets. Preserve stable provider review IDs where available and/or robust deduplication hashes, with fields including review\_id, provider\_review\_id, canonical\_business\_id, published\_at, first\_seen\_at, content\_hash, rating, legally/provider-appropriately available reviewer identifier, and source provenance. When review count advances, acquire/identify new reviews rather than re-fetching and reprocessing the entire known history where technically possible. Sentiment/topic/service/location processing runs on newly observed or materially changed review text unless an approved analysis explicitly requires historical reprocessing.

&nbsp;

47.3 Change-triggered website reprocessing

The approved website/site corpus is NOT reduced. Maintain cheap change-detection state where technically reliable, including content hash, relevant rendered-text hash, structured-data hash, sitemap state/hash, last-modified metadata, ETag, canonical URL, HTTP status, page-type relationship, relevant internal-link state, first\_seen\_at, last\_checked\_at, and last\_changed\_at. If previously analyzed content has not materially changed, reuse extracted content, classifications, embeddings, topic/service/location features, structured-data interpretation, and other expensive derived features. Only changed content triggers new embeddings or expensive semantic reprocessing unless an Analysis Specification Contract requires otherwise. Historical page/content versions remain preserved; change detection never overwrites prior versions.

&nbsp;

47.4 Signal-specific TTL and freshness

Slow-changing identity/business attributes do not inherit the cadence of volatile search outcomes. Founding year, franchise/brand relationship, organization identity, business type, licensing identifiers, physical address, primary domain, stable phone, and similar identity attributes may use long TTLs or change-triggered verification. Review count/rating, GBP categories, GBP website destination, DR/RD/link metrics, key page state, and other time-sensitive explanatory variables may remain monthly or otherwise at their approved cadence. TTL is versioned by signal/provider and never implies a cached unchanged value was freshly re-observed. Preserve observed\_at, effective\_at where known, last\_verified\_at, freshness status, TTL policy/version, and stale/unknown state.

&nbsp;

47.5 Event-driven Research Sentinel enrichment

The weekly Research Sentinel primarily detects search-system change. A Sentinel observation MUST NOT automatically refresh every external explanatory variable for every observed business. Flow: weekly Sentinel observation → compare with prior Sentinel/full-wave state → detect meaningful change under a predefined/versioned rule → select affected businesses/assets/signals → targeted enrichment. Candidate triggers include major Maps visibility change, new/lost Top-3 or Top-10 presence, material AI business-composition change, new/lost AIO selection/citation, important Organic composition change, major cross-surface state change, and entity/source/destination transition. Trigger definitions and thresholds must come from Analysis Specification Contracts/baseline variance and be prospectively versioned; an LLM may not retrofit thresholds after seeing outcomes.

&nbsp;

47.6 Progressive entity resolution

Use progressively more expensive resolution only when necessary. Stage 1: stable/deterministic identity evidence such as provider/place ID, canonical GBP, exact domain, exact verified social URL, phone/address in valid identity context, known organization/location relationship, canonical business graph. Stage 2: inexpensive multi-signal resolution using normalized/fuzzy name, geography, domain relationships, structured data, and service/category compatibility. Stage 3: embeddings/vector similarity where useful. Stage 4: LLM adjudication only for unresolved ambiguous cases. Stage 5: human review where scientifically necessary. Preserve match evidence, conflicting evidence, method, stage, confidence, resolver/model/rule version, and analyst-override provenance. LLM inference is not the universal resolver.

&nbsp;

47.7 Progressive classification/semantic processing

Where scientifically valid use: deterministic parsing → rules/regex/exact entity detection → provider-returned metadata → lexical relevance/structured comparison → embeddings → LLM classification for unresolved cases. Apply this to service/geography relevance, page type, entity extraction, schema presence, profile matching, title/H1/location interpretation, source classification, social-result relevance, and analogous tasks. Preserve classifier/version/provenance.

&nbsp;

47.8 Tiered enrichment architecture

Tier 1 — Universal/cheap: economical discovery and eligibility signals maintained across the broad canonical population.

Tier 2 — Progressive: moderate-cost signals collected when an entity becomes analytically relevant, a relevant change occurs, freshness expires, it enters a candidate comparison cohort, or an Analysis Specification Contract requires the data.

Tier 3 — Study-specific/deep: expensive data collected only for cases, valid controls, transition cohorts, replication/validation samples, intervention studies, and specifically approved analyses.

Tiering MUST NOT create outcome-conditioned bias. Case/control selection may use only variables legitimate under the applicable analysis design. Do not deeply enrich the entire business universe merely because a signal could theoretically be collected.

&nbsp;

47.9 Backlink cadence — explicit governing distinction

Regular/monthly Full Panel population: approved backlink/link variables and histories remain MONTHLY, subject to global economic-unit deduplication and shared provider-data reuse. This includes approved DR/domain authority provider metric, domain referring domains, UR/page authority provider metric for relevant URLs, URL referring domains, GBP-linked-page metrics, homepage metrics, service-page metrics, control-page metrics, and approved backlink history/details. Do not weaken the regular population below monthly.

&nbsp;

Weekly Research Sentinel: retain the approved lightweight WEEKLY backlink/link monitoring needed for Sentinel research. Do not run an unnecessary universal full backlink reconstruction every Sentinel week. Deeper backlink inspection is targeted when an event or Analysis Specification Contract requires it.

&nbsp;

47.10 Explicit non-changes / rejected cost reductions

This optimization does NOT authorize: (a) replacing monthly regular-population backlinks with summary-only plus quarterly deep backlinks where the approved module methodology requires monthly link histories; (b) redefining website research as a core-pages-only corpus; (c) silently choosing the nested 9-point Maps/Organic candidate before the 13-vs-9 pilot decision; (d) changing AIO from its approved 9-point geometry; or (e) introducing a new brand-demand dedup methodology. Existing approved brand-demand/search-volume methodology remains unchanged.

&nbsp;

The following remain unchanged unless explicitly versioned later: 25-industry × 50-market Full Panel; four canonical Maps/Organic queries; 10-condition AIO and ChatGPT panels; Maps Top 10; Organic Top 10; AIO raw observations; ChatGPT three fresh-context replicates; monthly Full Panel; weekly fixed 5-industry × 10-market Research Sentinel; structural water exclusions; immutable raw observation retention; canonical entity architecture; the Top-50 Brand \+ Service \+ Location evidence layer; and approved statistical/epistemic safeguards. Maps/Organic geometry remains 13 for the first pilot with a nested 9-point production candidate pending the measured pilot decision; AIO is 9 points.

&nbsp;

&nbsp;

48\. HISTORICAL — CHATGPT SHARED-UNIVERSE INCREMENTAL COST PLANNING MODEL — SUPERSEDED BY CURRENT 10-PROMPT PANEL

Status: HISTORICAL COST-PROVENANCE ONLY. The 15,000-observation/four-prompt planning scenario below is superseded by the current 25 × 50 × 10 × 3 \= 37,500-observation monthly ChatGPT full panel. Preserve the old scenario only to reconstruct earlier budgeting discussions; do not use it for current workload, provider-cost, schema, or scheduler implementation.

&nbsp;

Planning observation envelope

\- Shared-universe scenario: 25 industries × 50 markets × 4 permanent ChatGPT prompt families × 3 independent fresh-context replicates \= 15,000 ChatGPT result-page observations per collection wave.

\- The approved planning scenario models one such wave monthly.

\- ChatGPT does not inherit the Google 13-coordinate geo-grid merely because the same industries and markets are used. ChatGPT geography remains governed by the ChatGPT-specific methodology.

&nbsp;

Current provider-cost assumption

\- Pricing observation date: 2026-09-09.

\- Current DataForSEO Standard ChatGPT/LLM Scraper planning price: $0.0012 per result page.

\- At 15,000 result pages, raw provider collection is therefore approximately $18 per monthly planning wave at that observed price.

\- Provider prices and payload capabilities are external variables and must be versioned/rechecked rather than treated as permanent constants.

&nbsp;

Fanout-query capture

\- Provider-returned observable fanout/search queries are first-class data and should be captured with the ChatGPT observation whenever available.

\- Preserve the graph: original prompt → observed fanout query → retrieved source/result → citation/evidence → surfaced business/entity → recommendation/mention → destination/link, subject to what the provider actually exposes.

\- Observed fanout queries must remain distinct from reconstructed, guessed, or LLM-inferred fanout queries.

\- If fanout queries are returned in the paid result payload, they do not independently trigger duplicate economic-unit purchases merely because multiple fanouts reference the same business, domain, URL, source, or asset.

&nbsp;

Incremental enrichment behavior

Every newly surfaced business/entity/asset must pass the shared enrichment eligibility gate:

observed → canonicalized → already sufficiently fresh? → changed materially? → analytically relevant? → paid enrichment required?

&nbsp;

Do not repurchase enrichment because the same economic unit appeared in multiple ChatGPT prompt families, replicates, positions, markets where identity legitimately overlaps, or because it was already observed through Maps, AIO, Organic, indexed social/community evidence, or another research wave. Preserve the raw ChatGPT mention/observation separately while reusing sufficiently fresh shared enrichment.

&nbsp;

Backlinks are excluded from this incremental ChatGPT cost model. Backlink collection remains governed by the platform-wide backlink contracts: monthly for the regular/full research population and lightweight weekly monitoring for the Research Sentinel, with targeted deeper inspection where justified. Adding ChatGPT must not create a duplicate backlink purchase path.

&nbsp;

Approved financial-planning scenarios — NOT empirical findings

The following are budget scenarios only. Novel-business counts, overlap rates, and enrichment allowances must not be reported as measured platform findings until prospectively observed:

\- High-overlap planning case: \~500 incrementally novel canonical businesses/month; estimated non-backlink enrichment allowance \~$40–$70 plus \~$18 raw ChatGPT collection; total planning range \~$60–$90/month.

\- Expected planning case: \~1,000 incrementally novel canonical businesses/month; estimated non-backlink enrichment allowance \~$80–$140 plus \~$18 raw ChatGPT collection; total planning range \~$100–$160/month.

\- Low-overlap planning case: \~2,000 incrementally novel canonical businesses/month; estimated non-backlink enrichment allowance \~$150–$250 plus \~$18 raw ChatGPT collection; total planning range \~$170–$270/month.

\- A mature shared entity graph may reduce steady-state incremental ChatGPT enrichment toward a planning envelope of roughly $20–$100/month excluding storage/compute overhead and backlinks, but this is a planning hypothesis, not a promised cost or empirical finding.

&nbsp;

The system must measure actual gross ChatGPT business mentions, unique observed entities, canonical matches, cross-surface matches, newly created canonical entities, enrichment cache hits, enrichment cache misses, paid-enrichment triggers, and provider cost. These measured quantities replace the planning assumptions as evidence accumulates.

&nbsp;

Governing economic principle

Adding ChatGPT is an incremental-surface problem, not a duplicate-enrichment problem. Collect the approved ChatGPT observations and fanout evidence broadly, then canonicalize globally and pay only for scientifically required enrichment that is genuinely new, stale, materially changed, or analysis-required.

&nbsp;

&nbsp;

49\. LOCKED — RECONCILED CURRENT IMPLEMENTATION BASELINE — 2026-09-09

&nbsp;

1\. Google AIO / AI Mode production geography uses a 9-point cardinal design: market center plus N/S/E/W at 2.5 miles and N/S/E/W at 5 miles. Structural water exclusions remain valid; excluded points are not relocated or imputed.

2\. Maps and Organic collect the full approved 13-point geometry in the first pilot while tagging a nested 9-point production candidate. The four incremental points are retained specifically to measure marginal unique entities, downstream cost, spatial information, longitudinal information, and explanatory-variable variation. Until the pilot resolves the decision, 13 is the pilot collection geometry and 9 is a candidate—not a permanent replacement. ChatGPT does not inherit a geo grid; it remains market-level with exactly 3 independent fresh-context replicates.

3\. Current full-panel query/prompt counts are locked for implementation: Maps \= 4 canonical queries; Organic \= 4 canonical queries; AIO/AI Mode \= 10 approved query/prompt conditions; ChatGPT \= 10 approved prompt conditions × exactly 3 independent fresh-context replicates. Maps/Organic are not expanded beyond four unless explicitly versioned later.

4\. AIO retains backlink/link explanatory variables and approved backlink histories. ChatGPT appearance alone never triggers a backlink purchase; existing shared backlink state may still be joined to a ChatGPT entity when already available.

5\. Every valid resolved business observed on any research surface receives the universal explanatory-variable enrichment required for that surface even if it appears on only one platform, query, coordinate, or replicate. Cost optimization must come from canonical/economic-unit deduplication, caching, TTLs, incremental updates, and change detection—not outcome-based exclusion.

6\. ChatGPT-specific enrichment uses a fixed inexpensive universal baseline plus fanout-directed enrichment. Observed fanout queries are classified into evidence families (reviews/reputation, first-party website/service, social/community/Reddit, directories/lists, credentials, news/media, brand/entity, location, and other empirically observed classes) and may trigger additional enrichment appropriate to the observed family. Fanout behavior guides additional enrichment but does not replace the universal baseline.

7\. Preserve the observable ChatGPT chain where available: original prompt → observed fanout query → retrieved source/result → citation/evidence → surfaced canonical business/entity → recommendation/mention → destination/link. Retrieved, cited, linked, supportive, recommended, and ranked remain distinct states.

8\. Website retrieval uses ScrapeOwl as the planned scraping provider. Retrieval should use the least-expensive viable request mode first and escalate only when required. Existing content-hash/change-detection rules remain governing so unchanged pages do not trigger unnecessary semantic reprocessing.

9\. LOCKED Brand/Service/Location Search-Evidence Layer: for each eligible canonical business, issue the canonical brand \+ service \+ location Google query and collect the first 5 result pages / Top 50 organic results. Store the complete Top-50 result set, not only social URLs. Classify results into first-party website, official social, third-party social mention, Reddit/community/forum, directory/review, news/editorial, trade/professional organization, and other evidence classes while preserving raw URL, domain, title, snippet, rank, query, market, wave, and canonical-entity relationship.

10\. Top-50 absence means only “not observed in the Top 50 for the canonical brand \+ service \+ location query”; it must never be interpreted as no mention/presence exists.

11\. The Top-50 layer supersedes the discussed Top-100/10-page planning option. At the current planning price of approximately $0.003 per Top-50 query, 15,000 canonical businesses imply approximately $45 per full evidence wave; 20,000–25,000 imply approximately $60–$75. Provider pricing must be versioned and rechecked at execution.

12\. Current whole-platform planning envelope with Top 50 is approximately $580–$815 for Month 1 and $540–$744 around Month 6, with working targets of about $700 Month 1, about $625 Month 6/steady-state, and about $7,800 for Year 1, under a $10,000 planning ceiling until telemetry replaces assumptions. These are financial planning assumptions, not research findings or guaranteed provider spend; actual telemetry supersedes them.

13\. Current raw monthly full-panel planning volumes before structural exclusions are Maps 65,000; Organic 65,000; AIO 112,500; ChatGPT 37,500; total 280,000.

14\. Research Sentinel \= fixed 5 industries × 10 markets, weekly, using approved surface-specific query/geometry membership and exactly 3 fresh-context ChatGPT replicates. Sentinel is change detection, not a substitute for the monthly full panel. Historical Sentinel counts derived from the former matched 13-point/four-query architecture are non-operative.

15\. Current implementation state: PRD reconciliation is complete; the machine-readable collection manifest v0.7 is materially built pending deterministic structural-water application/final freeze; the Physical Supabase/Postgres Schema Contract v0.1 is complete; and the Operational QA / Wave Acceptance Contract v0.1 is complete. The active implementation-readiness artifact is the bounded Pilot → Production Protocol, followed by water-mask/final manifest freeze, migration/seed, pilot execution, QA/economic evaluation, the pre-authorized Maps/Organic 13-vs-9 decision, and production go/no-go. Do not add new permanent signals, queries, grids, modules, or methodology changes without explicit research justification and approval.

&nbsp;

&nbsp;

50\. LOCKED — IMPLEMENTATION-READINESS CHECKPOINT — 2026-09-09

Status: The shared methodology-design and PRD-reconciliation phase is complete. This checkpoint records implementation artifacts and does not reopen or expand the scientific design.

1\. Collection manifest: v0.7 is materially built with the 25-industry × 50-market registries, exact surface treatment registries, deterministic market centers/coordinates, Sentinel membership, surface/provider settings, job-generator contract, 280,000-row monthly Full Panel pre-water execution matrix, and 11,200-row weekly Sentinel pre-water execution matrix. Final executable v1.0 requires deterministic structural-water classification/freeze before geo-surface jobs are released.

2\. Physical data layer: the Physical Supabase/Postgres Schema Contract v0.1 and companion SQL migration are complete implementation inputs. They preserve immutable raw evidence, normalized surface evidence, separate/versioned canonical resolution, shared temporal enrichment, costs, QA, and reproducible derived research.

3\. Operational QA: the Operational QA / Wave Acceptance Contract v0.1, machine-readable QA rules, and SQL seed are complete implementation inputs. Scientific absence, structural missingness, provider/technical failure, and quarantine are distinct states.

4\. Active next artifact: build the bounded Pilot → Production Protocol. Recommended starting scale remains 3 industries × 5 markets. The pilot validates collection, storage, parsing, identity resolution, enrichment/cache economics, raw-payload integrity, cost attribution, runtime, failure handling, and QA observability before production launch.

5\. Maps/Organic pilot requirement: collect the full approved 13-point geometry and tag the nested 9-point candidate. The pilot must measure the four incremental points' marginal unique canonical entities, enrichment/processing/storage cost, spatial information, distance decay, directional asymmetry, visibility-radius behavior, longitudinal transition information, and explanatory-variable variation. Do not permanently choose 13 versus 9 from assumed observation-count savings.

6\. AIO remains on its separately approved fixed 9-point geometry. ChatGPT remains no geo grid with exactly 3 independent fresh-context replicates. The Maps/Organic geometry experiment does not redefine either surface.

7\. The pilot is an engineering/observability validation and a pre-authorized Maps/Organic geometry comparison. It must not be used for outcome-driven tuning of permanent hypotheses, prompts, queries, industries, markets, signals, or provider behavior. Any methodology change requires an explicit versioned amendment and approval.

8\. After water-mask freeze and Pilot → Production Protocol completion, the implementation sequence is: migrate/seed infrastructure → generate executable pilot jobs → run bounded pilot → evaluate QA/economics/13-vs-9 telemetry → resolve only the pre-authorized geometry choice and genuine engineering defects → production go/no-go → launch/operate the 25 × 50 longitudinal panel.

&nbsp;

&nbsp;

51\. LOCKED — APPROVED BOUNDED PILOT → PRODUCTION PROTOCOL — 2026-09-09

&nbsp;

Status: APPROVED by Kyle Sabraw on 2026-09-09. This section supersedes earlier language that described the bounded pilot as a recommendation, draft, or active next artifact. It does not supersede any other locked methodology except where this section explicitly resolves an implementation choice left open for the pilot.

&nbsp;

Pilot membership is fixed at 3 industries × 5 markets \= 15 industry×market cells:

• IND010 Locksmith

• IND019 Urgent Care

• IND022 Chinese Restaurant

• MKT008 Vancouver, WA

• MKT011 Phoenix, AZ

• MKT021 Chicago, IL

• MKT040 Birmingham, AL

• MKT049 New York City, NY

&nbsp;

The pilot contains 9 Sentinel-overlap cells and 6 Full-Panel-only cells. Its purpose is implementation validation and bounded production-readiness testing, not outcome-driven retuning of the scientific design.

&nbsp;

Pre-water deterministic scientific job counts are locked for planning/reconciliation:

• Maps: 15 × 4 × 13 \= 780

• Organic: 15 × 4 × 13 \= 780

• AIO / AI Mode: 15 × 10 × 9 \= 1,350

• ChatGPT: 15 × 10 × 3 \= 450

• Total: 3,360 pre-water jobs

&nbsp;

Post-water counts must be computed exactly from frozen coordinate eligibility and must never be estimated or backfilled. Before Manifest v1.0 can be declared executable, the approved structural-water mask must be applied to all 1,100 configured coordinate records. structural\_water\_exclusion remains structural missingness with retained intended-coordinate provenance; manual\_review is non-executable pending adjudication; configuration\_failure blocks the affected configuration until corrected.

&nbsp;

Pilot implementation order is locked as: physical Supabase/Postgres schema → private immutable raw Storage → QA contract/rule seed → frozen Manifest v1.0 seed → deterministic pilot job generation → reconciliation → live collection. Pilot membership must be generated by subsetting Manifest v1.0, not by hand-authoring an independent pilot manifest.

&nbsp;

Raw response bytes use content-addressed immutable storage. The approved operational content path convention is sha256/\<first-2-hex\>/\<next-2-hex\>/\<full-sha256\>; bucket naming remains environment configuration rather than research methodology. Raw provider bytes, provider-task provenance, accepted-attempt lineage, normalized extraction, canonical resolution, derived research, and cost events remain separate layers.

&nbsp;

Before live submission, the pilot job matrix must be generated twice from the same frozen inputs and produce identical job keys and membership. The database must reconcile exactly to the frozen generated matrix, reject duplicate scientific jobs/observations, and create no executable coordinate job for structural\_water\_exclusion, manual\_review, or configuration\_failure states.

&nbsp;

Retry policy for the pilot is max\_attempts \= 3 per deterministic scientific job: one initial provider attempt plus at most two technical retries. Retries are allowed only for the technical conditions in the QA contract. A technically valid sparse, unfavorable, refusal, non-trigger, no-mention, short-result, or business-nonappearance outcome is the scientific result and must not be retried to improve appearance or completeness. Technical retries remain attempts under the same job and never create a scientific replicate.

&nbsp;

Mandatory pilot failure drills include: retryable provider failure; retry exhaustion; malformed/truncated payload; provider/schema drift; deliberate duplicate insertion; raw SHA-256 mismatch; missing raw pointer; same storage path resolving to different bytes/hash; quarantine isolation; deterministic replay/reprocessing from retained raw evidence without provider recollection; and a scientific-absence fixture demonstrating no outcome-driven retry.

&nbsp;

Production promotion is COMPLETE-only. A PARTIAL pilot is a REMEDIATE state, not an automatic GO. GO requires exact manifest reconciliation, resolved water eligibility, zero critical duplicate/integrity failures, accepted raw hashes and resolvable pointers, surface/parser integrity, independent ChatGPT R1/R2/R3 jobs, entity-resolution execution for all eligible observed objects, measurable cache/dedup/freshness behavior, required cost attribution, quarantine isolation, reproducible derived-dataset rebuild, all mandatory failure drills passed, and separable Maps/Organic 13-versus-9 telemetry. Fixable engineering defects produce REMEDIATE. Any inability to preserve frozen scientific identity, immutable evidence, provider semantics, replicate independence, interpretable normalization, or water configuration is NO-GO until resolved.

&nbsp;

Maps/Organic geometry decision protocol is locked conservatively. The pilot always collects the full approved 13-point geometry: center plus N/S/E/W at 1, 3, and 5 miles. A nested 9-point comparison is derived from the same observations using center \+ the four 1-mile points \+ the four 5-mile points. The four 3-mile cardinal points are the incremental comparison set. No second collection is authorized merely to create the 9-point comparison. The default decision is RETAIN\_13. If measured marginal cost is clearly disproportionate to incremental entity, spatial, longitudinal, and explanatory value, the pilot may produce a PROPOSE\_9\_FOR\_APPROVAL decision packet; production may switch to 9 only after explicit user approval. Mixed or insufficient evidence is INCONCLUSIVE — RETAIN\_13. No invented numeric equivalence threshold and no outcome-driven geometry optimization are permitted. AIO remains on its separately approved fixed 9-point geometry and is not part of this 13-versus-9 decision.

&nbsp;

After an actual pilot GO, freeze the approved protocol/QA/manifest hashes, record the Maps/Organic geometry decision, generate the 25-industry × 50-market monthly Full Panel and fixed 5-industry × 10-market weekly Research Sentinel schedules from Manifest v1.0, and preserve pilot provenance as a separate wave rather than merging it into production history.

&nbsp;

52\. LOCKED — CIVIC-CENTER MARKET ANCHOR AMENDMENT — 2026-09-09

&nbsp;

Status: APPROVED by Kyle Sabraw on 2026-09-09 before first live scientific collection. This amendment replaces Census Gazetteer representative/internal points as the production spatial origin for the 50-market research universe. Census place/GEOID fields remain retained for market identity and provenance but no longer determine collection-center coordinates.

&nbsp;

For every named market, the production anchor is the official primary municipal civic-government seat under methodology version CIVIC\_CENTER\_ANCHOR\_V1\_2026-09-09. Selection hierarchy: (1) official City Hall designated by the municipal government; (2) where no conventional City Hall exists, the primary municipal government headquarters/civic center; (3) for a multi-building municipal campus, the main municipal seat/public-government headquarters. Washington, DC uses the District government's primary civic-government headquarters under the same principle. Selection is universal and prospective; it must not be customized because of observed search outcomes.

&nbsp;

Each frozen market-anchor record must preserve market\_id, anchor label, anchor type, street address where available, WGS84 EPSG:4326 latitude/longitude at 7-decimal precision, coordinate/source provenance, authoritative or corroborating source URL(s), verification date, center\_method\_version, and freeze status. Approved anchor types are official\_city\_hall, primary\_municipal\_government\_headquarters, and district\_government\_headquarters. The anchor and its source record must be frozen before any scientific observation for that methodology version.

&nbsp;

All Maps/Organic and AIO candidate coordinates are deterministically regenerated from the same frozen civic-center anchor for the market. Maps/Organic retain the approved geometry of center plus N/S/E/W at 1, 3, and 5 miles for the first pilot, with the same nested-9 comparison. AIO retains center plus N/S/E/W at 2.5 and 5 miles. Bearings, distances, WGS84 geodesic construction, point IDs, structural-water semantics, and all other geometry rules remain unchanged. ChatGPT remains market-level with no geo grid; this amendment does not simulate ChatGPT searcher location.

&nbsp;

After regeneration, the approved 2025 Census TIGER/Line Areal Hydrography structural-water contract applies to all 1,100 candidate coordinate records before Manifest v1.0 is executable. Non-center water points remain structural\_water\_exclusion and are never relocated, substituted, randomized, imputed, or encoded as zero. A civic-center anchor intersecting an auto-exclude water polygon is configuration\_failure and must be resolved before launch.

&nbsp;

This amendment does not change the 25 industries, 50 markets, Sentinel membership, query/prompt registries, surface depth, cadence, ChatGPT replicate count, pilot membership, or pre-water candidate workload. Full-panel pre-water planning remains Maps 65,000 \+ Organic 65,000 \+ AIO 112,500 \+ ChatGPT 37,500 \= 280,000; the approved pilot remains 3,360 pre-water jobs. Only the spatial origin and the derived coordinate values are replaced.

&nbsp;

Supersession rule: any current or historical implementation text that names Census Gazetteer representative/internal points as the operative market-center source is superseded for prospective production by CIVIC\_CENTER\_ANCHOR\_V1\_2026-09-09. Historical Gazetteer values may be retained only as methodology provenance or for a separately approved sensitivity analysis.

&nbsp;

&nbsp;

52\. LOCKED — 2025 TIGER/LINE AREAWATER PACKAGING-EQUIVALENCE AMENDMENT — 2026-09-10

&nbsp;

User-approved implementation amendment. The structural-water scientific source is the U.S. Census Bureau 2025 TIGER/Line AREAWATER polygon dataset; it is no longer tied to one national GeoPackage container. Official county-partitioned archives named tl\_2025\_\<5-digit-county-GEOID\>\_areawater.zip are the preferred implementation packaging. The national 2025 AREAWATER GeoPackage remains an optional archival-equivalent package and is not required for launch.

&nbsp;

For every county archive actually used, retain exact filename, county GEOID, official Census download URL, retrieval timestamp, SHA-256, and dataset vintage. Package/container choice does not authorize any change to vintage, AREAWATER polygon feature class, MTFCC logic, point geometry, water/missingness treatment, or no-relocation semantics. The existing six auto-exclude MTFCC values and manual-review/configuration-failure rules remain unchanged.

&nbsp;

This amendment is packaging/provenance only. Manifest Candidate v0.9 records it and remains pre-water/non-executable until all 1,100 configured coordinates have final eligibility states and Manifest v1.0 is frozen. Any separate geographic-boundary treatment requires its own explicit methodology approval.

&nbsp;

&nbsp;

52\. LOCKED — U.S. COUNTRY-BOUNDARY ELIGIBILITY GATE — 2026-09-10

&nbsp;

Status: APPROVED METHODOLOGY AMENDMENT BEFORE FIRST LIVE COLLECTION.

&nbsp;

A universal U.S.-country-boundary eligibility gate is applied to every configured Maps/Organic and AIO coordinate before the structural-water classifier. This is a scientific eligibility rule, not a Detroit exception.

&nbsp;

Governing order:

1\. Preserve the intended frozen coordinate exactly.

2\. Evaluate whether the point lies within the frozen official U.S. country boundary.

3\. If a non-center point lies outside the U.S., classify it as \`outside\_country\_exclusion\`; retain the intended coordinate and provenance; do not submit an ordinary provider job for that point.

4\. If a center point lies outside the U.S., classify it as \`configuration\_failure\`; correct the market configuration before launch rather than silently substituting another point.

5\. Only points inside the U.S. proceed to the locked 2025 Census TIGER/Line AREAWATER polygon classifier.

6\. City, county, or state boundary crossings do not by themselves exclude a point. This gate addresses only leaving the United States.

&nbsp;

Semantics:

\- \`outside\_country\_exclusion\` is structural missingness, never rank/visibility zero.

\- Excluded coordinates are never relocated, rotated, randomized, substituted, or imputed.

\- The boundary source, vintage/version, exact source artifact, hash, classifier version, and point-level result must be retained for reproducibility.

\- The rule applies prospectively and uniformly to all 1,100 configured geo-surface coordinate records before Manifest v1.0 freeze.

\- ChatGPT is unaffected because its permanent collection design has no coordinate grid.

&nbsp;

This amendment supersedes any implementation behavior that would allow an out-of-U.S. dry-land point to pass merely because it does not intersect a U.S. water polygon. Detroit/Windsor is the motivating implementation discovery, not a special-case rule.

&nbsp;