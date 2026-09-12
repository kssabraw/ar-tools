CURRENT AUTHORITATIVE PRODUCTION NOTICE — 2026-09-09

The operative ChatGPT design is 25 industries × 50 markets × 10 approved prompt conditions × exactly 3 independent fresh-context replicates per monthly full wave, with no geo grid. This supersedes older 10-industry × 20-market, four-family-only, one-anchor-query, 800-condition/week, 2,400-observation/week, and approximately 10,400/month production statements retained below for historical provenance. The fixed Research Sentinel is weekly and does not replace the monthly full panel.

&nbsp;

SED ChatGPT Local Search & Recommendation Intelligence — Product Requirements Document

&nbsp;

Status

Active module PRD. This document is authoritative for ChatGPT-specific methodology subject to the governing hierarchy below.

&nbsp;

&nbsp;

Authoritative Governance

The governing hierarchy is:

&nbsp;

1\. SED Local Search Intelligence Platform — Unified Research Architecture & Cost Optimization PRD

   \- Parent specification.

   \- Controls shared canonical entities, immutable raw observations, provider/economic-unit deduplication, shared signal storage, content-addressed assets and embeddings, Python/SQL-before-LLM gating, queueing/orchestration, cost accounting, shared missingness states, Analysis Specification Contracts, validation/replication governance, intervention infrastructure, and shared finding infrastructure.

&nbsp;

2\. Google Maps Local Search Intelligence & Strategy Engine PRD

   \- Authoritative surface-specific Maps module.

   \- Controls Maps-specific sampling under the current 25-industry × 50-market production universe, four canonical core queries, approved 13-point cardinal geometry, Maps/Organic outcomes, distance methodology, Maps cohorts/enrichment eligibility, Maps-specific signal cadence overrides, DAVS/Effective Ranking Radius research, and Maps Client Mode.

&nbsp;

3\. Local AI Overview Research & Citation Intelligence Platform PRD

   \- Authoritative surface-specific AIO module.

   \- Controls AIO-specific sampling, query-family methodology, AIO capture, source/entity/destination visibility, local-business-card and embedded-GBP presentation semantics, controls/transitions/persistence, sensitivity experiments, and AIO strategy-evidence semantics.

&nbsp;

The ChatGPT module must integrate as another observation surface within the existing platform. It must not create a parallel canonical entity system, enrichment warehouse, cost ledger, finding registry, intervention layer, or independent research truth.

&nbsp;

Locked Cross-Platform Principles Inherited by ChatGPT

\- Preserve immutable raw observations and provider/source provenance.

\- Canonical entity resolution is separate, versioned, and rebuildable.

\- Reuse existing canonical business, GBP, domain, URL, social, and organization entities.

\- Reuse sufficiently fresh enrichment rather than repurchasing the same economic unit.

\- Cost optimization must come from deduplication, caching, batching, progressive enrichment, change detection, and shared infrastructure rather than weakening a permanent longitudinal panel.

\- Python/SQL/provider parsing/vector math precede LLM inference whenever deterministic computation is sufficient.

\- LLMs may summarize, classify, explain, and synthesize, but may not manufacture measurements, effect sizes, p-values, coefficients, confidence intervals, or research findings.

\- Hypotheses are not findings.

\- Correlation does not establish causation.

\- Predictive importance does not establish a ranking/recommendation factor.

\- Missing is not zero.

\- Discovery, validation, and replication are separate stages.

\- Strategy-eligible analyses require explicit population, estimand, exposure, confounders, timing/lag, missingness, repeated-measures structure, multiple-testing treatment, validation/holdout design, effect magnitude, uncertainty, and methodology/code provenance.

\- New cross-surface findings do not inherit the strongest evidence label from any child module automatically.

\- No universal Maps \+ Organic \+ AIO \+ ChatGPT visibility score is authorized.

\- Client Mode must use the shared signal warehouse and finding registry and must be able to return TEST, MONITOR, LEAVE ALONE, insufficient\_evidence, or ineligible rather than manufacture certainty.

\- Superseded decisions from the parent, Maps, or AIO specifications must not be resurrected.

&nbsp;

Current ChatGPT Module Working Objective

Build a longitudinal research module that studies which local businesses, brands, websites, and third-party sources ChatGPT surfaces, recommends, cites, links to, or excludes in local-commercial and local-recommendation conversations.

&nbsp;

Working primary research question:

&nbsp;

What characteristics predict ChatGPT local business visibility, recommendation, destination linking, and evidence/source exposure under controlled local-intent prompts?

&nbsp;

Causal language is not authorized unless later evidence supports it under the platform's causal-inference governance.

&nbsp;

LOCKED Decision 1 — ChatGPT Local Visibility & Recommendation Taxonomy

Status: LOCKED — 2026-09-06

&nbsp;

The ChatGPT module MUST treat visibility, recommendation, link exposure, destinations, and supporting evidence as analytically distinct outcomes. They MUST NOT be collapsed into a single V1 recommendation or visibility score.

&nbsp;

1\. Response-level outcome

Every observation records the response behavior before business-level classification. Initial controlled values:

&nbsp;

\- \`answered\_local\`

\- \`clarification\_requested\`

\- \`generic\_guidance\_only\`

\- \`no\_local\_recommendations\`

\- \`refusal\`

\- \`error\`

\- \`other\`

&nbsp;

Clarification requests are valid research outcomes and MUST NOT be silently discarded as failed observations.

&nbsp;

2\. Entity visibility

\`entity\_visible \= true\` means a business/brand is named or otherwise surfaced as an identifiable entity.

&nbsp;

Entity visibility does not imply recommendation.

&nbsp;

A factual mention, citation context, geographic reference, comparison reference, or other non-choice mention remains visible while \`recommended \= false\`.

&nbsp;

3\. Recommendation inclusion

A ChatGPT recommendation occurs when a business is intentionally presented as a viable choice for satisfying the user's expressed local-commercial need.

&nbsp;

A business included in a model-generated shortlist of viable choices counts as \`recommended \= true\` even if no single business receives an explicit endorsement.

&nbsp;

Mere factual mention, citation, comparison context, or geographic reference does not constitute a recommendation.

&nbsp;

4\. Recommendation strength

Recommendation inclusion and recommendation strength are separate variables.

&nbsp;

Initial ordinal classification:

&nbsp;

\- \`0 \= not\_recommended\`

\- \`1 \= weak\`

\- \`2 \= standard\`

\- \`3 \= strong\`

\- \`4 \= top\_choice\`

&nbsp;

The ordinal categories MUST NOT be treated as interval-scale quantities without later empirical justification. For example, \`top\_choice\` is not assumed to be twice as strong as \`standard\`.

&nbsp;

5\. Response order versus explicit rank

Rendered/list order and explicit model ranking are separate.

&nbsp;

Capture at least:

&nbsp;

\- \`mention\_position\`

\- \`recommendation\_position\`

\- \`explicit\_ranking\`

\- \`explicit\_rank\`, where applicable

&nbsp;

A first-listed business is not automatically the strongest recommendation. A business may appear second yet receive stronger explicit endorsement language.

&nbsp;

6\. Recommendation polarity

Visibility can be positive, neutral, cautionary, or negative.

&nbsp;

Initial classification:

&nbsp;

\- \`positive\`

\- \`neutral\`

\- \`cautionary\`

\- \`negative\`

&nbsp;

Negative/cautionary visibility MUST remain in the dataset rather than being dropped.

&nbsp;

An explicitly discouraged business may be \`entity\_visible \= true\`, \`recommended \= false\`, \`recommendation\_polarity \= negative\`.

&nbsp;

7\. Shortlist membership and top-choice elevation

Capture shortlist inclusion separately from top-choice elevation:

&nbsp;

\- \`shortlist\_member\`

\- \`top\_choice\`

&nbsp;

This permits separate study of:

1\. what gets a business into ChatGPT's consideration set; and

2\. what causes or predicts elevation within that set.

&nbsp;

Causal language remains prohibited unless the platform's evidence requirements are satisfied.

&nbsp;

8\. Stated recommendation rationales

Preserve the raw text ChatGPT gives as the reason for recommending, preferring, cautioning about, or distinguishing a business.

&nbsp;

Structured rationale classifications may include multi-label categories such as:

&nbsp;

\- review/reputation

\- service match

\- availability

\- location

\- price/value

\- experience/longevity

\- specialization

\- credentials

\- brand reputation

\- third-party recognition

\- other

&nbsp;

These are stated recommendation rationales, not proven recommendation factors.

&nbsp;

A model-stated rationale does not establish that the attribute caused the recommendation. Causal or mechanistic interpretation requires independent empirical evidence.

&nbsp;

9\. Linked versus unlinked business mentions — first-class outcome

Linked versus unlinked mention is a first-class ChatGPT outcome and MUST NOT be buried inside a generic destination field.

&nbsp;

For every resolved or unresolved business mention, capture at least:

&nbsp;

\- \`entity\_visible\`

\- \`mention\_position\`

\- \`mention\_linked\`

\- \`linked\_destination\_position\`

\- \`linked\_destination\_url\`

\- \`linked\_destination\_domain\`

\- \`linked\_destination\_type\`

\- \`direct\_business\_link\`

\- \`third\_party\_business\_link\`

\- \`supporting\_citation\_present\`

&nbsp;

At minimum, distinguish:

&nbsp;

1\. Unlinked business mention — business is named but the mention itself has no clickable destination.

2\. Linked own-site mention — business/entity mention links directly to the business's own website.

3\. Linked Google/Maps/GBP mention — business/entity mention links to an observed Google/Maps/GBP destination.

4\. Linked third-party mention — business/entity mention links to a third-party profile, directory, review platform, publisher, social profile, booking surface, or other external destination.

5\. Citation-supported but unlinked mention — business is named without the business mention itself being clickable, while a citation/source supports the surrounding business statement or recommendation.

&nbsp;

A business mention being clickable and a claim about the business being citation-supported are different phenomena and MUST be stored separately.

&nbsp;

10\. Destination taxonomy

Initial destination types include:

&nbsp;

\- \`business\_homepage\`

\- \`business\_service\_page\`

\- \`business\_location\_page\`

\- \`business\_other\_page\`

\- \`google\_maps\`

\- \`google\_business\_profile\`

\- \`directory\_profile\`

\- \`review\_platform\`

\- \`publisher\_editorial\`

\- \`social\_profile\`

\- \`booking\_contact\`

\- \`other\`

&nbsp;

The observed raw URL MUST be preserved. Destination classification is derived and reprocessable.

&nbsp;

11\. Evidence/source visibility

The recommended business/entity and the source used to support the answer MUST NOT be conflated.

&nbsp;

Capture source relationships such as:

&nbsp;

\- \`supports\_business\`

\- \`supports\_claim\`

\- \`supports\_comparison\`

\- \`supports\_list\`

\- \`general\_background\`

\- \`unclear\`

&nbsp;

Where technically observable, preserve the relationship:

&nbsp;

\`business → recommendation/mention → stated rationale or claim → supporting source\`

&nbsp;

This relationship is preferable to merely recording that a domain appeared somewhere in the response.

&nbsp;

12\. Five V1 outcome families

The V1 outcome framework therefore contains five explicitly distinct families:

&nbsp;

1\. Entity Visibility — was the business/entity surfaced?

2\. Recommendation Visibility — was it presented as a viable choice, and with what strength/polarity/order?

3\. Mention-Link Visibility — was the surfaced business/entity itself clickable?

4\. Destination Visibility — where did the click lead?

5\. Evidence/Source Visibility — what supporting sources/citations were exposed and what did they support?

&nbsp;

These MUST remain separable in storage and analysis.

&nbsp;

13\. Unresolved, ambiguous, and likely nonexistent businesses

Recommended or mentioned entities MUST NOT be discarded merely because canonical resolution fails.

&nbsp;

Initial resolution states:

&nbsp;

\- \`resolved\`

\- \`probable\_match\`

\- \`ambiguous\`

\- \`unresolved\`

\- \`likely\_nonexistent\`

\- \`insufficient\_information\`

&nbsp;

Preserve raw entity text and provenance. Hallucinated/likely nonexistent local businesses may later form a longitudinal model-quality outcome.

&nbsp;

14\. Longitudinal transition outcomes

The taxonomy should support derived transitions including:

&nbsp;

\- \`recommendation\_gain\`

\- \`recommendation\_loss\`

\- \`recommendation\_regain\`

\- \`recommendation\_persist\`

\- \`recommendation\_strength\_upgrade\`

\- \`recommendation\_strength\_downgrade\`

\- \`position\_gain\`

\- \`position\_loss\`

\- \`top\_choice\_gain\`

\- \`top\_choice\_loss\`

\- \`link\_gain\`

\- \`link\_loss\`

\- \`direct\_link\_gain\`

\- \`direct\_link\_loss\`

\- \`unlinked\_to\_linked\_upgrade\`

\- \`linked\_to\_unlinked\_downgrade\`

\- \`link\_destination\_swap\`

\- \`destination\_gain\`

\- \`destination\_loss\`

\- \`citation\_gain\`

\- \`citation\_loss\`

\- \`source\_swap\`

\- \`business\_swap\`

&nbsp;

These are derived from preserved observations and MUST NOT overwrite raw state.

&nbsp;

15\. Raw observation versus derived interpretation

The immutable observation layer MUST preserve, where technically available:

&nbsp;

\- raw response

\- raw links

\- raw citations/source references

\- raw ordering

\- raw entity strings

\- raw rendered/structured metadata

\- prompt and prompt version

\- conversation/session state

\- product/model/mode/tool configuration

\- timestamp and observation provenance

&nbsp;

Derived classifications such as recommendation status, strength, polarity, shortlist membership, rationale categories, destination type, and source relationship MUST be versioned and reprocessable.

&nbsp;

Derived semantic classification provenance should include, as applicable:

&nbsp;

\- parser/classifier version

\- extraction prompt version

\- extraction model/version

\- confidence

\- validation status

&nbsp;

Historical raw observations MUST remain available so taxonomy or classifier changes can be applied retrospectively without corrupting longitudinal comparability.

&nbsp;

16\. Core research distinction created by this decision

The module must be capable of separately studying:

&nbsp;

\- what predicts being mentioned by ChatGPT;

\- what predicts being recommended;

\- what predicts receiving a clickable business/entity link;

\- what predicts the type of destination ChatGPT exposes; and

\- what predicts which supporting sources/evidence ChatGPT exposes.

&nbsp;

These may represent different thresholds and different optimization problems. Client Mode MUST NOT assume that improving one necessarily improves the others.

&nbsp;

Decision Log Update

2026-09-06 — Decision 1 LOCKED- Locked the five-family visibility/recommendation framework.

\- Locked recommendation inclusion versus strength as separate variables.

\- Locked response order versus explicit rank as separate variables.

\- Locked polarity, shortlist membership, top-choice elevation, and stated rationale semantics.

\- Locked linked versus unlinked business mentions as a first-class outcome.

\- Locked business-link versus supporting-citation distinction.

\- Locked destination-type and source-support relationships as separate structures.

\- Locked preservation of unresolved/likely nonexistent entities.

\- Locked raw-observation versus derived-classification separation and reprocessability.

\- No composite ChatGPT recommendation/visibility score is authorized in V1.

&nbsp;

LOCKED Decision 2 — Prompt / Query-Family Methodology

Status: CURRENT / RECONCILED — 2026-09-09

&nbsp;

Current production prompt panel

The permanent ChatGPT Full Panel uses exactly 10 approved prompt conditions per industry-market cell: the four approved core conditions plus six locked conversational/long-tail conditions. Exact literal prompt text, condition IDs, slot values, and version membership belong to the versioned prompt/collection manifest and MUST NOT be generated, paraphrased, expanded, dropped, or silently substituted by an LLM or collector during a methodology version.

&nbsp;

Controlled treatment principle

Prompt wording is a controlled experimental treatment. Fresh-session / zero-history execution is the permanent baseline. Multi-turn conversational research, source-conditioned prompting, location-conditioned execution, or other materially different prompting belongs to an explicitly versioned bounded experiment unless already included in the approved permanent 10-condition manifest.

&nbsp;

Prompt-family taxonomy

DISCOVERY, RECOMMEND, BEST, and PROBLEM remain useful ChatGPT-specific prompt-family/treatment classifications where an approved prompt maps to them. They are no longer the complete production prompt count and MUST NOT be multiplied as though the permanent panel contains only four conditions. Preserve prompt\_family and prompt\_condition\_id separately so family-level analyses do not erase condition-level treatment differences.

&nbsp;

Geography wording

Explicit-market, near-me-style, geo-neutral, or other geography wording—where present in an approved prompt condition—must remain distinguishable treatment metadata and must not be silently pooled. Decision 4 governs what may be inferred about physical searcher location; prompt wording alone does not prove physical in-market execution.

&nbsp;

Historical provenance

The earlier “four permanent V1 prompt families” design is superseded only as a statement of complete production panel size. Its family taxonomy remains scientifically useful as described above.

&nbsp;

LOCKED Decision 3 — Permanent Universe and Replication

Status: CURRENT / RECONCILED — 2026-09-09

&nbsp;

Current permanent Full Panel

\- 25 industries × 50 markets \= 1,250 industry-market cells.

\- Exactly 10 approved ChatGPT prompt conditions per industry-market cell under the active methodology version.

\- Exactly 3 independent fresh-context replicates per prompt condition.

\- 12,500 prompt conditions × 3 replicates \= 37,500 raw ChatGPT observations per monthly Full Panel wave.

\- The fixed Research Sentinel is collected weekly as a separate monitoring cohort; it is not a weekly replay of the Full Panel.

\- ChatGPT has no Maps/AIO geographic grid. Geography/session treatment remains ChatGPT-specific and is governed by Decision 4 plus the versioned prompt/collection manifest.

&nbsp;

Replicate integrity

Each replicate is part of the immutable observation key and MUST preserve its own raw response, exact prompt, session/context provenance, collection timestamp, provider/product configuration where observable, and attempt/retry relationship. Replicates MUST NOT be collapsed at ingestion and MUST begin in independent fresh contexts under the permanent-panel session controls.

&nbsp;

Probabilistic recommendation principle

The system measures recommendation probability/frequency and stability rather than pretending a stochastic generative system has one deterministic local rank. Replicate-derived measures may include entity visibility frequency, recommendation frequency, top-choice frequency, direct-link frequency, linked-mention frequency, citation/source frequency, destination frequency, recommendation-set overlap, and position distributions. These are reproducible derived measures from preserved raw observations.

&nbsp;

Separate stability dimensions

Inclusion stability, position stability, link stability, destination stability, and citation/source stability remain distinct. They MUST NOT be collapsed into one arbitrary V1 stability score. Deterministic set/statistical methods should precede LLM interpretation where scientifically appropriate.

&nbsp;

Scheduling governance

The locked scientific requirement is exactly three independent fresh-context replicates for every permanent ChatGPT prompt condition in each applicable scheduled cohort. The operational scheduler may execute them at controlled times within the collection window, but exact timestamps/order/configuration must be preserved and timing MUST NOT introduce shared conversational history or intentional personalization. Timing policy belongs in the machine-readable collection manifest/operational contract and does not reopen replicate count, Full Panel cadence, or panel size.

&nbsp;

Historical provenance — SUPERSEDED FOR CURRENT IMPLEMENTATION

The prior 10-industry × 20-market, four-family-only, 800-condition/week, 2,400-observation/week (\~10,400/month), one-anchor-query baseline and its within-week scheduling language are retained only as historical design provenance. They MUST NOT be used by collection code, schema defaults, schedulers, cost models, or QA acceptance calculations. The current 25 × 50 × 10 × 3 monthly Full Panel supersedes those production counts.

&nbsp;

Cross-surface sampling

Reuse the shared 25-industry × 50-market universe and canonical graph to maximize valid joins and shared enrichment reuse. This shared universe does not make ChatGPT inherit Maps/Organic/AIO coordinate geometry or create duplicate enrichment purchases.

&nbsp;

LOCKED Decision 4 — V1 Geography and Location Methodology

Status: LOCKED — 2026-09-07

&nbsp;

V1 measures explicit geographic intent, not simulated physical user location.

&nbsp;

The permanent longitudinal panel uses market-explicit geography context under the versioned 10-condition prompt manifest. The named research market and exact geography wording are controlled prompt-treatment metadata. The collection environment does not simulate a physical user coordinate and ChatGPT does not inherit a Google geo grid.

&nbsp;

No V1 location spoofing requirement

V1 MUST NOT require city-specific proxies, VPN-based city simulation, browser/device geolocation spoofing, GPS simulation, 73-point ChatGPT geographic grids, or per-market physical execution environments.

&nbsp;

Standardized execution environment

Permanent V1 observations should be collected from a standardized research execution environment. Execution-environment metadata should be preserved where technically observable, but execution location is not actively varied as a permanent V1 treatment.

&nbsp;

The platform MUST NOT claim that an explicit-city observation represents the experience of a user physically located in that city.

&nbsp;

Phase 2 — location-conditioned research

Location-conditioned ChatGPT research is explicitly deferred to Phase 2 / Experimental.

&nbsp;

Candidate Phase 2 work includes:

\- \`near me\` prompts;

\- in-market versus out-of-market execution;

\- IP/proxy location sensitivity;

\- device/browser geolocation sensitivity;

\- neighborhood/coordinate sensitivity;

\- limited reuse of Maps geographic points;

\- eventual comparison of Maps distance-response behavior with ChatGPT recommendation-distance behavior.

&nbsp;

These methodologies MUST NOT enter permanent collection until execution location can be controlled and validated reliably enough for the intended estimand.

&nbsp;

Near-me governance

Near-me/location governance: permanent prompt membership is controlled only by the approved versioned 10-condition manifest; this older decision no longer independently excludes a wording pattern. Regardless of wording, a permanent ChatGPT observation collected without validated physical-location control MUST NOT be represented as the experience of a user physically located at the named market or a specific coordinate. A separate experiment that explicitly claims location-conditioned or near-me physical execution requires validated location provenance.

&nbsp;

Out-of-city recommendations and service-area businesses

Businesses recommended outside the explicitly named city remain valid observations and MUST NOT be automatically excluded.

&nbsp;

Where available through the shared entity graph, preserve physical business location, named prompt market, city/market relationship, distance variables, and service-area evidence.

&nbsp;

For service-area industries, physical address and service-market relevance are distinct concepts. No arbitrary geographic eligibility threshold may be imposed merely because a business lies outside the named municipal boundary.

&nbsp;

Empirical geographic boundaries

How geographically expansive ChatGPT's interpretation of a market is remains a research question. Geographic inclusion/exclusion rules MUST NOT encode conventional Local SEO assumptions as findings before the data supports them.

&nbsp;

Decision Log Update

2026-09-07 — Decision 4 LOCKED- Locked V1 to explicit geographic intent rather than simulated physical location.

\- Locked market-explicit geography context as the permanent geography framework, with exact prompt wording governed by the approved versioned 10-condition manifest.

\- Removed location spoofing/control as a V1 infrastructure requirement.

\- Deferred physical-location-conditioned near-me execution, proxy/IP, browser/device geolocation, neighborhood/coordinate, and geographic-grid experiments to bounded experimental work unless explicitly approved later.

\- Locked standardized execution environment for V1 without claiming physical in-market equivalence.

\- Locked preservation of out-of-city recommendations rather than arbitrary exclusion.

\- Locked physical location versus service-area relevance as separate concepts.

\- Locked geographic eligibility/boundary effects as empirical research questions.

&nbsp;

LOCKED Decision 5 — ChatGPT Product Surface, Session Controls, Search & Fanout Capture

Status: LOCKED — 2026-09-07

&nbsp;

Research target

The permanent V1 target is the consumer ChatGPT local-recommendation experience with normal web-search capability available, without explicitly instructing the model to search.

&nbsp;

The research object is the evolving consumer ChatGPT recommendation product, not a permanently frozen historical model/API configuration.

&nbsp;

Search behavior

Permanent prompts MUST NOT instruct ChatGPT to use Search, Google, Maps, Yelp, Reddit, reviews, directories, or another source unless source-conditioning is an explicit experimental treatment.

&nbsp;

Whether Search is invoked is itself an observed outcome where technically observable.

&nbsp;

Preserve:

\- \`search\_available\`

\- \`search\_invoked\`

\- \`search\_invocation\_status\`

\- any observable search/tool metadata

&nbsp;

Unknown/unobservable values remain unknown rather than inferred.

&nbsp;

Fresh-context replicates

Each of the three locked replicates MUST begin in a separate fresh conversation/context.

&nbsp;

Replicates MUST NOT be generated by repeatedly submitting the permanent prompt inside the same conversation.

&nbsp;

Prior conversational context must not intentionally contaminate the permanent panel.

&nbsp;

Personalization controls

The permanent research environment should minimize/disable intentional personalization wherever technically possible, including:

\- Memory effects;

\- custom instructions;

\- prior conversation context;

\- research-account persona/preferences;

\- connected-source/app influence unless explicitly part of the treatment.

&nbsp;

The exact observed/configured state must be recorded where technically possible.

&nbsp;

Product/configuration provenance

Preserve, where observable:

\- product surface;

\- model family/identifier/mode;

\- Search availability and invocation;

\- tool configuration;

\- account/workspace type;

\- Memory/personalization configuration;

\- location configuration;

\- collection method;

\- collector version;

\- observation timestamp;

\- other product-state metadata required to interpret longitudinal changes.

&nbsp;

Unknown product/model internals MUST NOT be fabricated.

&nbsp;

Product-change registry

Maintain a versioned \`chatgpt\_product\_event\` registry for known or observed structural changes that may affect longitudinal interpretation, including changes to:

\- models;

\- Search/retrieval;

\- citations;

\- links/destinations;

\- local/Maps presentation;

\- recommendation UI;

\- source/provider behavior;

\- tool behavior;

\- other relevant product mechanics.

&nbsp;

Major product changes are potential structural breaks and MUST NOT be silently normalized away.

&nbsp;

Fanout/search-query extraction — FIRST-CLASS V1 REQUIREMENT

Whenever technically observable, the system MUST extract and preserve all observed fanout/search queries generated from the original user prompt, in execution order.

&nbsp;

The raw original prompt and each observed fanout query remain separate artifacts.

&nbsp;

At minimum, where observable, preserve:

\- \`observation\_id\`

\- \`original\_prompt\`

\- \`fanout\_query\_id\`

\- \`fanout\_sequence\`

\- \`fanout\_query\_text\`

\- \`query\_stage\` (\`initial\`, \`follow\_up\`, \`unknown\`)

\- \`search\_provider\`

\- \`query\_timestamp\`

\- \`query\_location\_context\`

\- raw provider/tool provenance

&nbsp;

Only observed fanout queries may enter the primary observed-query dataset. Reconstructed, guessed, or LLM-inferred queries MUST NOT be represented as observed behavior.

&nbsp;

If inferred query classifications or reconstructions are created for exploratory purposes, they must be explicitly labeled derived/inferred and kept separate from observed fanout data.

&nbsp;

Fanout-derived variables

Derived variables may include:

\- \`fanout\_query\_count\`

\- fanout depth/stage;

\- query-family classifications;

\- brand/entity query indicators;

\- service-intent indicators;

\- geography indicators;

\- review/reputation indicators;

\- superlative/best indicators;

\- directory/source indicators;

\- comparison indicators;

\- problem/service-specific indicators;

\- credentials indicators;

\- price/value indicators;

\- other versioned classifications.

&nbsp;

Raw query text MUST always be retained so classifications can be reprocessed.

&nbsp;

No composite \`fanout strength score\` is permitted in V1.

&nbsp;

Retrieval-chain relationships

Where technically observable, preserve explicit relationships across the retrieval chain:

&nbsp;

\`original prompt → fanout query → retrieved source/result → citation/evidence → surfaced business → recommendation → destination/link\`

&nbsp;

Do not fabricate missing edges.

&nbsp;

This enables separate study of:

\- what prompts trigger Search;

\- what retrieval paths ChatGPT generates;

\- which sources appear for which fanout queries;

\- which evidence supports surfaced/recommended businesses;

\- which retrieval patterns precede recommendations;

\- whether brand/entity queries emerge over time;

\- whether retrieval behavior changes before recommendation outcomes change.

&nbsp;

Search invocation as an outcome

Search invocation and fanout behavior are legitimate dependent variables in their own right and should not be treated merely as implementation metadata.

&nbsp;

The system may estimate outcomes such as Search-invocation frequency and fanout-query frequency by industry, market, prompt family, and observation period, subject to the parent statistical-governance requirements.

&nbsp;

Decision Log Update

2026-09-07 — Decision 5 LOCKED- Locked the consumer ChatGPT recommendation product with normal Search capability available as the V1 research target.

\- Locked natural prompts without explicit instructions to search.

\- Locked three separate fresh contexts for the three permanent replicates.

\- Locked minimization/control of Memory, personalization, custom instructions, prior context, and connected-source influence.

\- Locked product/model/search/tool provenance capture where observable.

\- Locked product-change registry and structural-break treatment.

\- Locked Search invocation as a first-class observed outcome.

\- Locked fanout/search-query extraction as a first-class V1 research requirement whenever technically observable.

\- Locked raw ordered fanout preservation and prohibition on representing inferred/reconstructed queries as observed.

\- Locked retrieval-chain relationships where observable.

\- Prohibited a composite fanout score in V1.

&nbsp;

LOCKED Decision 6 — Raw Observation, Retrieval, Source & Evidence Capture

Status: LOCKED — 2026-09-07

&nbsp;

Foundational ruleCapture first. Normalize second. Classify third.

&nbsp;

Every permanent ChatGPT observation MUST retain an immutable raw representation sufficient for future reprocessing. Normalized or derived records MUST NOT become the only surviving representation.

&nbsp;

Three-layer architecture1. Immutable raw layer — exact collector/provider artifacts and response payloads.

2\. Normalized extraction layer — response text, URLs, citations, business strings, positions, fanout queries, retrieved results, and other observable structures.

3\. Derived research layer — recommendation strength, rationale classifications, source/destination types, entity resolution, relationship classifications, and other versioned analytical variables.

&nbsp;

Observation and response preservationEach observation receives a permanent \`chatgpt\_observation\_id\` linked to prompt condition, industry, market, intent family, replicate number, timestamps, collection method, collector version, product configuration, and session configuration.

&nbsp;

Retain the complete raw provider/collector response when available and the exact returned/rendered response text, including ordering, headings, lists, qualifying language, recommendation wording, and link anchors.

&nbsp;

Rendered HTML/equivalent structured UI artifacts may be retained where useful. Screenshots are conditional in V1 and should be retained when meaningful UI information cannot otherwise be reconstructed.

&nbsp;

First-class links, citations, fanout queries, and retrieved resultsObserved links and citations MUST be individual records with their observable position, context, URL/source metadata, business relationships, and destination/source classifications.

&nbsp;

Decision 5 fanout queries MUST be first-class records linked to their observation. Where technically observable, retrieved results MUST be linked to the fanout query that produced them and preserve result position, URL, domain, title, snippet, and raw provenance.

&nbsp;

Retrieval-chain graphWhere technically observable, preserve:

&nbsp;

\`original prompt → fanout query → retrieved source/result → citation/evidence → surfaced business → recommendation → destination/link\`

&nbsp;

Missing edges remain missing/unknown and MUST NOT be fabricated.

&nbsp;

Distinct evidence statesRetrieved, cited, linked, supports-claim, associated-with-business, and recommended are separate concepts and MUST NOT be collapsed. Retrieval does not prove citation; citation does not prove causal influence on a recommendation.

&nbsp;

Source snapshot economicsUse the parent architecture's canonical URL/content-hash/content-addressed asset system rather than repeatedly storing unchanged source pages. Preserve temporal provenance sufficient to identify relevant source versions.

&nbsp;

Parser/classifier provenanceDerived classifications retain version/provenance including, where applicable, parser version, classification method, model, prompt version, timestamp, confidence, and validation status. New versions MUST NOT silently overwrite prior provenance; historical raw observations remain reprocessable.

&nbsp;

Failures, clarifications, retries, and replicate integrityErrors, timeouts, refusals, clarification requests, no-recommendation responses, Search failures, and malformed outputs are valid outcomes and MUST NOT be silently discarded.

&nbsp;

Retries may occur operationally, but preserve attempt number, retry reason, parent/original attempt relationship, and each attempt's outcome.

&nbsp;

A failed, clarification, or no-recommendation replicate MUST NOT be replaced merely to obtain a successful recommendation response. Variation across the three permanent replicates remains part of the dataset.

&nbsp;

Decision Log Update

2026-09-07 — Decision 6 LOCKED- Locked immutable raw observation preservation.

\- Locked separate raw, normalized, and derived layers.

\- Locked complete raw collector/provider response and exact response presentation preservation where available.

\- Locked links, citations, fanout queries, and retrieved results as first-class records where observable.

\- Locked retrieval-chain graph preservation without fabricated edges.

\- Locked retrieved/cited/linked/supportive/recommended as separate concepts.

\- Locked content-addressed/deduplicated source snapshots.

\- Locked parser/classifier provenance and reprocessability.

\- Locked preservation of failures, clarifications, retries, and unsuccessful replicates.

&nbsp;

HISTORICAL / RESOLVED QUERY-COUNT CONFLICT — SUPERSEDED 2026-09-09

The former Maps-two-query versus ChatGPT-one-anchor cost/query-count conflict is resolved for current implementation by the governing production panel. ChatGPT now uses exactly 10 approved prompt conditions per industry-market cell, with exactly 3 fresh-context replicates, across the 25-industry × 50-market monthly Full Panel. Maps and Organic use their separately approved four-query panels. Cross-surface research aligns canonical service/query intent where scientifically defensible; surfaces do not need identical literal query counts.

&nbsp;

The former 800-condition/week, 2,400-observation/week and hypothetical 4,800-observation/week calculations are historical provenance only. They MUST NOT control schema cardinality, scheduling, QA, or cost planning.

&nbsp;

Bounded experiments may add experiment-specific prompt/query conditions when prospectively justified, but those observations remain outside the permanent-panel denominator unless the methodology is explicitly versioned to include them.

&nbsp;

LOCKED Decision 7 — Canonical Business / Entity Resolution

Status: LOCKED

&nbsp;

Foundational rule

ChatGPT MUST reuse the parent platform's shared canonical entity graph. It MUST NOT create a separate ChatGPT-specific canonical business truth system.

&nbsp;

An observed ChatGPT entity mention and a canonical entity are different objects. Every business-like entity surfaced by ChatGPT is preserved first as an observation-level entity mention, regardless of whether canonical resolution succeeds.

&nbsp;

Resolution MUST assert only the most specific canonical entity level actually supported by the available evidence. Ambiguity, partial identity, brand-only identity, and unresolved identity MUST remain explicit.

&nbsp;

Resolution chain

The preferred resolution workflow is:

&nbsp;

\`ChatGPT observation → observed entity mention → candidate canonical entities → match evidence/conflicts → versioned resolution assertion → canonical entity if justified\`

&nbsp;

Candidate generation and match adjudication are separate stages.

&nbsp;

Candidate generation asks which canonical entities could plausibly represent the observation.

&nbsp;

Match adjudication asks what identity assertion, if any, the evidence justifies.

&nbsp;

The highest-scoring candidate MUST NOT automatically become truth.

&nbsp;

Canonical entity grain

The shared entity graph must preserve distinctions among, where applicable:

&nbsp;

\- organization / operating entity;

\- brand / trade name / DBA;

\- local business location or local service operation;

\- franchisee / franchise relationship;

\- GBP / Google Place entity;

\- domain;

\- individual URL;

\- directory profile;

\- review-platform profile;

\- social profile/account;

\- booking/contact destination;

\- publisher/source asset;

\- other provider/entity identifiers.

&nbsp;

These objects may be related but MUST NOT be flattened merely for convenience.

&nbsp;

The preferred local-analysis grain is the specific local business location or service operation when evidence supports that resolution level.

&nbsp;

A brand-level observation remains brand-level when branch/location identity is not supported.

&nbsp;

Prompt geography alone MUST NOT be used to manufacture a branch/location match.

&nbsp;

Aliases and trade names

Known legal names, operating names, DBAs, abbreviations, legacy names, and verified aliases may participate in candidate generation and matching.

&nbsp;

Alias relationships are versioned shared-graph assertions with provenance. Name similarity alone is not sufficient to establish canonical identity.

&nbsp;

Deterministic identity evidence

Deterministic resolution requires genuinely identity-bearing evidence or a previously verified graph relationship.

&nbsp;

Examples may include:

&nbsp;

\- exact stable Google Place / GBP location identifiers;

\- exact stable provider business identifiers already mapped to the shared graph;

\- exact external profile identifiers already verified to represent a canonical entity;

\- previously verified asset-to-entity relationships.

&nbsp;

Fields such as business name, domain, phone, address, or prompt market are not universally deterministic on their own.

&nbsp;

They may become effectively deterministic only where the shared graph contains a versioned uniqueness assertion sufficient for the intended resolution level.

&nbsp;

Probabilistic / multi-signal resolution

Where conclusive identifiers are unavailable, the resolver may combine multiple identity signals, including:

&nbsp;

\- normalized-name similarity;

\- alias/trade-name match;

\- phone correspondence;

\- street-address correspondence;

\- geographic proximity;

\- domain correspondence;

\- location-page correspondence;

\- structured-data identity;

\- service/category compatibility;

\- service-area compatibility;

\- brand/franchise relationship;

\- directory/profile linkage;

\- social-profile linkage;

\- source-page identity;

\- linked destination surfaced in the ChatGPT response;

\- existing Maps/AIO/shared-graph evidence.

&nbsp;

Prompt market and geographic context are supporting evidence only. They MUST NOT force a candidate match.

&nbsp;

Match score versus probability

An uncalibrated entity-resolution score MUST NOT be described as a probability.

&nbsp;

Use \`match\_score\` for uncalibrated scoring.

&nbsp;

Use probability semantics such as \`estimated\_match\_probability\` only after calibration against a labeled identity-resolution dataset supports that interpretation.

&nbsp;

Canonical resolution states

The canonical resolution-state vocabulary is:

&nbsp;

\- \`resolved\`

\- \`probable\_match\`

\- \`ambiguous\`

\- \`unresolved\`

\- \`likely\_nonexistent\`

\- \`insufficient\_information\`

&nbsp;

\`resolved\`

Evidence is sufficient to treat the observation as the asserted canonical entity at the specified resolution level.

&nbsp;

Resolution may result from conclusive deterministic evidence or from a validated/calibrated probabilistic methodology meeting the configured threshold, candidate-separation, and contradiction requirements.

&nbsp;

\`probable\_match\`

One candidate is substantially better supported than alternatives, but the evidence does not meet the standard for confirmed resolution.

&nbsp;

A probable match MUST NOT silently become a confirmed analytical join.

&nbsp;

\`ambiguous\`

Two or more plausible canonical identities remain and available evidence cannot reliably distinguish among them.

&nbsp;

Competing candidate identities and their supporting/conflicting evidence must be preserved.

&nbsp;

\`unresolved\`

There is enough identifying information to attempt resolution, but no sufficiently plausible canonical candidate can currently be established.

&nbsp;

\`likely\_nonexistent\`

The entity cannot currently be corroborated after the defined verification procedure and available evidence suggests it may be generated, fabricated, or nonexistent.

&nbsp;

\`likely\_nonexistent\` does not mean proven nonexistent.

&nbsp;

\`insufficient\_information\`

The observation does not contain enough identity-bearing evidence to make a meaningful canonical determination.

&nbsp;

Confidence thresholds

Numeric thresholds for \`resolved\`, \`probable\_match\`, candidate separation, and contradiction handling MUST NOT be invented merely for implementation convenience.

&nbsp;

The policy is versionable in forms such as:

&nbsp;

\- \`resolved \>= T\_resolved\`

\- \`probable\_match \>= T\_probable\`

\- top-candidate separation \`\>= Δ\_required\`

\- contradiction/conflict rules

&nbsp;

The actual values must be calibrated and validated on a manually labeled entity-resolution set before they are treated as scientifically meaningful.

&nbsp;

Threshold values and calibration provenance are versioned.

&nbsp;

Contradictory identity evidence

The resolver must preserve both supporting and conflicting evidence.

&nbsp;

Possible evidence fields or records include:

&nbsp;

\- \`name\_supports\_match\`

\- \`phone\_supports\_match\`

\- \`address\_supports\_match\`

\- \`domain\_supports\_match\`

\- \`provider\_id\_supports\_match\`

\- \`phone\_conflicts\`

\- \`address\_conflicts\`

\- \`domain\_conflicts\`

\- \`brand\_relationship\_conflict\`

\- \`temporal\_conflict\`

\- other versioned conflict classifications.

&nbsp;

The system MUST NOT treat matching evidence as purely additive while ignoring material contradictions.

&nbsp;

Temporal identity

Business identity is longitudinal and may change.

&nbsp;

The shared graph should preserve temporal provenance for attributes and mappings where possible, including:

&nbsp;

\- names and aliases;

\- addresses;

\- phone numbers;

\- domains;

\- GBP/provider IDs;

\- ownership;

\- franchise relationships;

\- profile relationships;

\- closure/reopening/rebrand events.

&nbsp;

Historical observations must preserve both:

&nbsp;

1\. the identity assertion known/applied for the observation under its resolution version; and

2\. the latest reconciled canonical identity available for reanalysis.

&nbsp;

Later knowledge MAY improve retrospective reconciliation, but it MUST NOT erase original resolution provenance or create temporal leakage in analyses.

&nbsp;

Service-area businesses

Missing or hidden public street address is not negative identity evidence for a service-area business.

&nbsp;

SAB resolution may rely on evidence including:

&nbsp;

\- GBP / Place ID;

\- phone;

\- website/domain;

\- business/brand name;

\- GBP-linked destination;

\- service-area statements;

\- directory profiles;

\- social profiles;

\- provider identifiers;

\- location/service pages;

\- corroborating cross-surface evidence.

&nbsp;

Preserve separately:

&nbsp;

\- \`physical\_location\_known\`

\- \`serves\_prompt\_market\`

&nbsp;

One MUST NOT be inferred solely from the other.

&nbsp;

Multi-location brands and franchises

A brand-level mention MUST NOT be converted into every local branch or franchise matching the prompt market.

&nbsp;

If ChatGPT surfaces only a brand name, brand resolution may be \`resolved\` while location/service-operation resolution remains \`insufficient\_information\`, \`ambiguous\`, or \`unresolved\`.

&nbsp;

Location-level resolution requires branch/location-specific evidence such as a specific GBP, local profile, local phone/address, location page, or equivalent identity-bearing evidence.

&nbsp;

Franchise and multi-location structures should preserve relationships such as:

&nbsp;

\`location/service operation → operated\_by organization → franchisee\_of/member\_of brand\`

&nbsp;

rather than flattening the location, operating company, and brand into one entity.

&nbsp;

Domains, URLs, profiles, and sources are not businesses

Websites, individual URLs, directory pages, review-platform profiles, social profiles, booking pages, and publisher pages are canonical assets/entities related to businesses; they are not automatically the business itself.

&nbsp;

Examples:

&nbsp;

\`external\_profile → represents → canonical\_business\`

&nbsp;

\`location\_page → represents → canonical\_location\`

&nbsp;

\`domain → owned\_by/represents → organization\_or\_brand\`

&nbsp;

Source/publisher identity and represented-business identity remain distinct.

&nbsp;

ChatGPT destinations as identity evidence

A destination surfaced by ChatGPT may materially strengthen entity resolution when it is already linked or resolvable to a canonical entity.

&nbsp;

For example, an exact location page, directory profile, or GBP may provide stronger identity evidence than the rendered business name alone.

&nbsp;

This use is limited to identity determination.

&nbsp;

A surfaced destination or supporting citation does NOT establish that the source caused the recommendation.

&nbsp;

Hallucinated / nonexistent entities

Observed entities MUST NOT be discarded merely because they cannot be mapped to a known real business.

&nbsp;

Likely nonexistent or repeatedly unresolved business-like mentions may be clustered in a separate observed-unresolved entity layer with attributes such as:

&nbsp;

\- normalized observed name;

\- raw name variants;

\- observation IDs;

\- prompt markets;

\- occurrence frequency;

\- surfaced links;

\- claimed phone/address data where observable;

\- verification results;

\- current resolution state.

&nbsp;

Such a cluster is NOT automatically promoted into the canonical real-business graph.

&nbsp;

Repeated model output does not establish real-world existence.

&nbsp;

Hybrid/conflicting entities

The resolver must support cases where a response combines attributes from different businesses or mixes real and apparently fabricated identity information.

&nbsp;

Potential conflict classes may include:

&nbsp;

\- \`name\_address\_mismatch\`

\- \`name\_phone\_mismatch\`

\- \`name\_domain\_mismatch\`

\- \`cross\_business\_attribute\_merge\`

\- \`stale\_identity\`

\- \`unknown\_conflict\`

&nbsp;

The system MUST NOT force these observations into a binary real-versus-fake classification when the evidence is mixed.

&nbsp;

Analyst review and override

Analyst review is permitted but must be transparent and append-only.

&nbsp;

Resolution provenance should retain, where applicable:

&nbsp;

\- resolver version;

\- candidate-generation version;

\- evidence used;

\- resolution method;

\- match score/probability semantics;

\- resolution state;

\- resolution level;

\- selected canonical ID;

\- competing candidate IDs;

\- timestamp;

\- validation status;

\- analyst-review status.

&nbsp;

Analyst overrides must preserve:

&nbsp;

\- prior assertion;

\- new assertion;

\- reason code;

\- supporting evidence;

\- reviewer;

\- timestamp;

\- override version.

&nbsp;

Manual review MUST NOT invisibly overwrite historical resolution state.

&nbsp;

Canonical merges/splits capable of altering many longitudinal observations require stronger review than ordinary observation-level matching.

&nbsp;

Versioned resolution assertions

Resolution is a versioned analytical assertion.

&nbsp;

Conceptually:

&nbsp;

\`observed\_entity\_mention → resolution\_assertion\_v1 → canonical\_entity\_X\`

&nbsp;

may later become:

&nbsp;

\`observed\_entity\_mention → resolution\_assertion\_v2 → canonical\_entity\_Y\`

&nbsp;

without deleting v1.

&nbsp;

Changes in aliases, canonical graph structure, algorithms, thresholds, provider identifiers, analyst review, or temporal business history must remain auditable.

&nbsp;

Downstream analytical gating

Resolution state and resolution level determine analytical eligibility.

&nbsp;

Primary confirmed cross-surface analyses use \`resolved\` identities by default.

&nbsp;

\`probable\_match\` MUST NOT enter the primary confirmed cross-surface dataset as established truth.

&nbsp;

It may be used in explicitly labeled:

&nbsp;

\- sensitivity analysis;

\- exploratory analysis;

\- probabilistic-identity methods;

\- manual-review queues.

&nbsp;

\`ambiguous\`, \`unresolved\`, \`likely\_nonexistent\`, and \`insufficient\_information\` MUST NOT be silently assigned to a canonical business for confirmatory analysis.

&nbsp;

A brand-resolved but location-unresolved observation may participate in brand-level analyses but MUST NOT be treated as a confirmed Maps/GBP location join.

&nbsp;

Cross-surface join rule

Research joins across ChatGPT, Maps, Organic, AIO, websites, directories, review platforms, sources, and social entities MUST flow through the shared versioned canonical entity graph.

&nbsp;

Ad-hoc analytical joins such as case-insensitive business-name equality, nearest-name matching, or one-off fuzzy joins MUST NOT be treated as research truth.

&nbsp;

String, domain, phone, address, profile, and geography matching belong in the canonical resolution layer.

&nbsp;

Resolution outcomes as research outcomes

Canonical resolution quality is itself measurable.

&nbsp;

Derived measures may include:

&nbsp;

\- resolved share;

\- probable-match share;

\- ambiguous share;

\- unresolved share;

\- likely-nonexistent share;

\- insufficient-information share;

\- brand-only resolution share;

\- location-resolution share;

\- resolution-state transitions.

&nbsp;

These are model/data-quality outcomes and MUST NOT be interpreted as recommendation factors without separate evidence.

&nbsp;

Decision 7 summary

Decision 7 therefore locks:

&nbsp;

1\. reuse of the shared parent canonical graph;

2\. observed-mention-first architecture;

3\. most-specific-supported resolution grain;

4\. strict brand/location distinction;

5\. candidate generation separate from adjudication;

6\. deterministic versus probabilistic evidence separation;

7\. calibrated probability semantics only;

8\. preservation of supporting and conflicting evidence;

9\. six canonical resolution states;

10\. empirically calibrated thresholds rather than arbitrary numeric cutoffs;

11\. temporal/versioned identity mappings;

12\. explicit SAB, multi-location, franchise, profile, domain, and asset handling;

13\. separate handling of likely hallucinated/nonexistent and hybrid entities;

14\. append-only analyst override provenance;

15\. versioned resolution assertions;

16\. primary confirmed joins restricted to \`resolved\` at the applicable entity level;

17\. probable-match use restricted to explicitly labeled sensitivity/exploratory contexts by default;

18\. canonical-ID-only cross-surface research joins;

19\. resolution uncertainty retained as an analyzable longitudinal outcome.

&nbsp;

&nbsp;

LOCKED Decision 8 — Recommendation Position, Strength & Rationale Structure

Status: LOCKED

&nbsp;

Foundational rule

Preserve what ChatGPT actually rendered first; interpret recommendation hierarchy second. Recommendation strength MUST NOT be inferred merely from screen position, list numbering, citation count, formatting, link presence, or response length.

&nbsp;

Occurrence-level representation

Every identifiable business appearance should first be represented as an occurrence-level record tied to the raw response and exact response location.

&nbsp;

A single business may appear multiple times in one response, including in an opening summary, list, table, recommendation section, comparison, or final recommendation. These occurrences MUST remain reconstructable rather than being collapsed into one business-level label at ingestion.

&nbsp;

Occurrence-level structure should preserve, where observable:

\- response/observation ID;

\- observed entity mention ID;

\- occurrence sequence;

\- raw text/span;

\- component or section membership;

\- list/table position where applicable;

\- links/citations associated with the occurrence;

\- recommendation semantics and classifier provenance.

&nbsp;

Business-level summaries are derived from the preserved occurrence records rather than replacing them.

&nbsp;

Position dimensions

The system MUST keep at least the following concepts separate:

\- \`mention\_position\` — order in which identifiable businesses first appear;

\- \`recommendation\_position\` — order among businesses that actually qualify as recommendations;

\- \`list\_ordinal\` — rendered ordinal within a numbered/ordered structure;

\- \`explicit\_ranking\` — whether ChatGPT semantically asserts a ranking;

\- \`explicit\_rank\` — asserted rank when present.

&nbsp;

Rendered position, recommendation position, list ordinal, and explicit rank MUST NOT be treated as synonyms.

&nbsp;

Numbered lists do not automatically establish semantic ranking

Numbered or ordered formatting may be used only to organize options. A rendered \`list\_ordinal \= 1\` does NOT by itself establish \`explicit\_rank \= 1\` or \`top\_choice \= true\`.

&nbsp;

Explicit ranking requires semantic evidence that ChatGPT is actually ranking or ordering the businesses by preference or merit.

&nbsp;

Recommendation groups and sections

Where the response organizes businesses under labels such as \`Best overall\`, \`Best for emergencies\`, \`Best budget option\`, or another named category, preserve the recommendation-group structure separately from numeric rank.

&nbsp;

Where observable, group-level records may preserve:

\- \`group\_id\`;

\- \`group\_position\`;

\- raw group/section label;

\- normalized group classification;

\- group type;

\- member occurrence IDs.

&nbsp;

A section label may communicate categorical elevation without establishing a global rank among all businesses in the response.

&nbsp;

Recommendation strength

The ordinal recommendation-strength taxonomy remains:

\- \`0 \= not\_recommended\`;

\- \`1 \= weak\`;

\- \`2 \= standard\`;

\- \`3 \= strong\`;

\- \`4 \= top\_choice\`.

&nbsp;

These are ordinal categories and MUST NOT be treated as interval-scale quantities without empirical justification.

&nbsp;

Strength classification semantics

\`not\_recommended\`

The entity is visible but is not intentionally presented as a viable choice for the user's need. Factual context, citation context, comparison-only references, warnings, and negative mentions may fall here.

&nbsp;

\`weak\`

The business is presented as potentially viable but with hedging, secondary positioning, or weak endorsement.

&nbsp;

\`standard\`

The business is straightforwardly included among viable recommended choices without unusual elevation or hedging. This is the normal state for an ordinary shortlist member.

&nbsp;

\`strong\`

ChatGPT explicitly elevates or endorses the business beyond ordinary shortlist membership without identifying it as the singular or co-equal preferred choice.

&nbsp;

\`top\_choice\`

ChatGPT explicitly identifies the business as its preferred, best, first, or singular/co-equal choice for the user's expressed need.

&nbsp;

Being rendered first is insufficient for \`top\_choice\`.

&nbsp;

Strength must derive from recommendation semantics

The classifier MUST NOT increase recommendation strength merely because a business:

\- appears first;

\- receives more words;

\- appears multiple times;

\- has more citations;

\- receives a direct business link;

\- has more reviews or stronger external metrics;

\- appears in Maps, Organic, or AIO;

\- has a seemingly persuasive stated rationale.

&nbsp;

Those may later be explanatory variables or separate outcomes. They do not define recommendation strength.

&nbsp;

Top choice versus explicit rank

\`top\_choice\`, \`explicit\_ranking\`, \`explicit\_rank\`, and \`recommendation\_strength\` remain separate analytical dimensions.

&nbsp;

A business may be explicitly ranked first without receiving separate top-choice language, and a business may receive explicit top-choice language without a numeric ranking.

&nbsp;

The system MUST NOT mechanically overwrite one variable from another.

&nbsp;

Ties and co-top choices

The data model MUST allow multiple co-equal top choices or tied explicit ranks when the response genuinely communicates a tie or co-preference.

&nbsp;

The schema MUST NOT impose a rule that each response has at most one \`top\_choice \= true\` entity.

&nbsp;

Occurrence-aware strength

Recommendation semantics may change within a response. If an entity is weakly recommended earlier and explicitly elevated later, both occurrences remain preserved.

&nbsp;

Derived entity-level fields may include:

\- \`first\_mention\_position\`;

\- \`first\_recommendation\_position\`;

\- \`mention\_count\`;

\- \`recommendation\_occurrence\_count\`;

\- \`max\_recommendation\_strength\`;

\- \`final\_recommendation\_strength\`, where meaningfully defined;

\- \`shortlist\_member\`;

\- \`top\_choice\`;

\- \`explicit\_ranking\`;

\- \`explicit\_rank\`;

\- \`rationale\_count\`.

&nbsp;

These are derivatives and MUST NOT replace occurrence-level raw/normalized data.

&nbsp;

Rationale structure — claim-level, raw-span-backed

Stated recommendation rationales should be represented as individual claim-level records rather than only as one flattened rationale string.

&nbsp;

For each rationale claim, preserve where technically practical:

\- observation/response ID;

\- entity/recommendation occurrence ID;

\- exact raw rationale text;

\- raw response span or offsets;

\- normalized rationale category/categories;

\- extraction/classification provenance;

\- confidence and validation status.

&nbsp;

The raw rationale span is evidence. The normalized label is a derived classification.

&nbsp;

Rationale taxonomy

The initial controlled multi-label rationale taxonomy includes:

\- review/reputation;

\- service match;

\- availability;

\- location;

\- price/value;

\- experience/longevity;

\- specialization;

\- credentials;

\- brand reputation;

\- third-party recognition;

\- other;

\- unclear.

&nbsp;

A single rationale claim may receive multiple labels where justified. The taxonomy is versioned and may later be extended without overwriting raw rationale text.

&nbsp;

Stated rationale versus verified attribute

A model-stated rationale is an observed statement about why ChatGPT says it recommends, prefers, cautions about, or distinguishes a business. It is NOT automatically a verified factual attribute of that business.

&nbsp;

For example, if ChatGPT states that a company has operated for 40 years, the dataset may record an \`experience/longevity\` stated rationale. It MUST NOT silently set a verified business-age field to 40 years merely because the model said so.

&nbsp;

The architecture may later link:

\`stated rationale → claim → supporting citation/source → external verification\`

with verification states such as supported, contradicted, unclear, or not checked.

&nbsp;

Decision 8 does not require every rationale to be externally verified during collection.

&nbsp;

Rationale-to-source relationships

Where technically observable, preserve:

\`recommendation → rationale claim → supporting source/citation\`

&nbsp;

A visible citation supporting a rationale does not establish that the cited source caused the recommendation.

&nbsp;

Stated rationale frequency and verified explanatory factors remain different research objects.

&nbsp;

Rationale language is not a recommendation factor by definition

Frequent occurrence of a rationale category does not establish that the corresponding attribute causally drives ChatGPT recommendation behavior.

&nbsp;

Predictive association with recommendation also does not by itself establish a ranking/recommendation factor. The parent platform's statistical and causal-governance rules continue to apply.

&nbsp;

Deterministic structure before semantic classification

Deterministic/provider parsing should first identify observable response structure wherever possible, including:

\- blocks/sections;

\- headings;

\- lists;

\- tables;

\- entity occurrences;

\- raw order;

\- list ordinals;

\- links;

\- citations;

\- group/section membership.

&nbsp;

Semantic classification is then used for concepts that require interpretation, including:

\- recommendation inclusion;

\- strength;

\- polarity;

\- top-choice status;

\- explicit-ranking semantics;

\- rationale spans/categories.

&nbsp;

Classifier output remains versioned and reprocessable with parser/classifier version, model/version where applicable, extraction prompt version, confidence, and validation status.

&nbsp;

Ambiguous classifications

The classifier MUST NOT manufacture certainty when wording is genuinely ambiguous.

&nbsp;

Low-confidence recommendation or rationale classifications should retain their uncertainty and may enter validation/review samples rather than being silently forced into a high-confidence class.

&nbsp;

Component type

Where technically observable, preserve the response component type for each entity occurrence, including values such as:

\- narrative text;

\- bullet/list item;

\- numbered item;

\- table row;

\- dedicated recommendation section;

\- rendered business/card element;

\- citation context;

\- other structured UI.

&nbsp;

Component type is an observed presentation feature and MUST NOT automatically determine recommendation inclusion or strength.

&nbsp;

Replicate-derived implications

Across the three locked independent replicates, Decision 8 enables separate derived measures such as:

\- recommendation-inclusion frequency;

\- position distribution;

\- strength distribution;

\- top-choice frequency;

\- explicit-rank frequency;

\- rationale-category frequency.

&nbsp;

The ordinal strength codes MUST NOT simply be averaged as though the distance between categories were interval-scaled. V1 should prefer appropriate distributions, event frequencies, medians where justified, threshold-event summaries, or later ordinal statistical models.

&nbsp;

No composite prominence score

No composite \`recommendation prominence score\`, \`recommendation strength score\`, or equivalent V1 metric that collapses position, strength, links, citations, groups, and rationale is authorized.

&nbsp;

Decision 8 summary

Decision 8 therefore locks:

1\. occurrence-level-first representation of every business appearance;

2\. separation of mention position, recommendation position, list ordinal, explicit ranking, and explicit rank;

3\. prohibition on interpreting numbered formatting alone as ranking;

4\. first-class recommendation groups/section labels;

5\. the existing 0–4 ordinal recommendation-strength taxonomy with explicit classification semantics;

6\. semantic rather than positional/external-signal definition of strength;

7\. separate top-choice, explicit-rank, and recommendation-strength variables;

8\. support for tied/co-equal top choices and ranks;

9\. occurrence-aware preservation when recommendation semantics change within a response;

10\. claim-level, raw-span-backed stated rationale records;

11\. multi-label, versioned rationale taxonomy;

12\. strict separation of stated rationale from verified business attributes;

13\. rationale-to-source relationships where observable without causal overclaiming;

14\. deterministic structural parsing before semantic classification;

15\. preservation of low-confidence/ambiguous semantic classifications;

16\. component-type preservation where observable;

17\. replicate-level position/strength/rationale distributions without interval-scale misuse; and

18\. prohibition of a composite recommendation-prominence score in V1.

&nbsp;

Decision Log Update

Decision 8 LOCKED

\- Locked occurrence-level recommendation representation.

\- Locked position/order/rank separation.

\- Locked numbered-list non-ranking rule.

\- Locked recommendation groups as distinct structure.

\- Locked semantic ordinal strength classification and top-choice semantics.

\- Locked claim-level raw-span-backed rationale extraction.

\- Locked stated-rationale versus verified-attribute and causal-factor separation.

\- Locked deterministic-structure-before-semantic-classification ordering.

\- Locked ambiguity/confidence preservation and no composite prominence score.

&nbsp;

LOCKED Decision 9 — Persistence, Churn & Longitudinal Transition Modeling

Status: LOCKED

&nbsp;

Foundational rule

Exact replicate-level state is primary. Named longitudinal transitions are derived only under an explicit, versioned transition definition.

&nbsp;

The ChatGPT module studies a stochastic recommendation system. A business appearing in fewer or more individual replicates from one comparable collection wave to the next MUST NOT automatically be described as having gained or lost a deterministic rank. For the permanent population, the monthly Full Panel wave is the primary full-population longitudinal comparison unit; the weekly Research Sentinel is a separate monitoring cohort. All underlying replicate observations remain preserved.

&nbsp;

Collection wave as the longitudinal comparison unit

Each permanent Full Panel prompt condition produces exactly three independent fresh-context replicates per monthly Full Panel wave. Sentinel prompt conditions likewise preserve exactly three fresh-context replicates in each weekly Sentinel wave. Cohort membership MUST remain explicit.

&nbsp;

For every entity and outcome dimension, derive a wave-level state from the preserved replicates. Example fields may include:

\- \`scheduled\_replicates\`;

\- \`observable\_replicates\` for the specific outcome dimension;

\- outcome-positive replicate count;

\- conditional observed frequency;

\- exact replicate-state distribution;

\- wave timestamp/version/provenance.

&nbsp;

The same framework applies independently to entity visibility, recommendation inclusion, top-choice status, linked mention, direct business link, destination exposure, citation/source exposure, recommendation strength, and position.

&nbsp;

Missing and unobservable states

Missing or unobservable replicate outcomes MUST NOT be converted to zero.

&nbsp;

Per-dimension observability should distinguish at least:

\- \`observed\_true\`;

\- \`observed\_false\`;

\- \`not\_observable\`.

&nbsp;

If one replicate is recommended, one errors before recommendation status can be assessed, and one is observed not recommended, the system must preserve:

\- 3 scheduled replicates;

\- 2 recommendation-observable replicates;

\- 1 recommendation-positive replicate;

\- conditional observed frequency \= 1/2;

\- the error as its own response/product outcome.

&nbsp;

Alternative estimands such as end-to-end consumer success rates may later use the full scheduled denominator, but they MUST be explicitly defined and MUST NOT be silently conflated with recommendation conditional on an assessable response.

&nbsp;

Exact replicate counts before persistence labels

With three permanent replicates, the primary V1 wave state should preserve exact states such as:

\- 0 of 3;

\- 1 of 3;

\- 2 of 3;

\- 3 of 3;

plus reduced observable denominators where missingness requires them.

&nbsp;

A trajectory such as \`1/3 → 2/3 → 3/3\` remains an exact longitudinal trajectory before any semantic persistence label is applied.

&nbsp;

No universal V1 definition of recommendation gain

An increase from \`0/3 → 1/3\` and an increase from \`0/3 → 3/3\` are not equivalent phenomena.

&nbsp;

The primary transition representation therefore preserves the exact prior-state/current-state pair. Thresholded transition labels are derived analytical definitions.

&nbsp;

Candidate threshold families include:

\- any-presence: \`0 → \>=1\` and \`\>=1 → 0\`;

\- majority: \`\<=1 → \>=2\` and \`\>=2 → \<=1\`;

\- unanimous: \`\<=2 → 3\` and \`3 → \<=2\`.

&nbsp;

Decision 9 DOES NOT declare any of these to be the single universal definition of \`recommendation\_gain\` or \`recommendation\_loss\`.

&nbsp;

Any threshold-based transition must be defined and versioned through fields such as:

\- \`transition\_definition\_id\`;

\- \`transition\_definition\_version\`;

\- outcome dimension;

\- denominator/observability rule;

\- threshold rule;

\- window rule where applicable.

&nbsp;

Replicate numbers are not longitudinal identities

Replicate 1 in one collection wave is not presumed to correspond to replicate 1 in the next comparable wave. The three observations are independent fresh contexts, not persistent paired stochastic subjects.

&nbsp;

Primary longitudinal comparisons therefore operate on cohort-compatible wave distributions/states rather than pseudo-pairing same-numbered replicates across waves, unless a prospectively specified bounded experiment deliberately creates a paired execution design.

&nbsp;

Separate persistence dimensions

Persistence and churn are modeled separately for at least:

\- entity visibility;

\- recommendation inclusion;

\- top-choice status;

\- recommendation strength;

\- mention/recommendation position;

\- linked mention;

\- direct business link;

\- destination URL/domain/type;

\- citation/source exposure;

\- rationale/source-support relationships where observable.

&nbsp;

These dimensions MUST NOT be collapsed into a single V1 ChatGPT stability/churn score.

&nbsp;

Set-level recommendation churn

Recommendation-set composition is a first-class longitudinal object in addition to entity-level outcomes.

&nbsp;

Deterministic set-derived measures may include:

\- retained entities;

\- added entities;

\- removed entities;

\- union size;

\- intersection size;

\- retained share;

\- added count;

\- removed count;

\- Jaccard/set overlap where appropriate.

&nbsp;

Added and removed entities MUST be recorded before asserting that one specifically replaced another.

&nbsp;

Business-swap governance

A \`business\_swap\` classification requires an explicit operational definition that supports the pairing of the outgoing and incoming entities.

&nbsp;

Potential future swap definitions may use evidence such as:

\- same explicit-rank slot;

\- same recommendation-group slot;

\- exactly one entity removed and one added while set cardinality remains otherwise stable;

\- explicit comparative replacement language.

&nbsp;

Without such a rule, the system records \`business\_removed\` and \`business\_added\` separately rather than fabricating a direct swap relationship.

&nbsp;

Source and destination churn

Source and destination changes follow the same principle.

&nbsp;

Preserve exact added/removed/retained source relationships at both URL and domain levels before deriving \`source\_swap\`.

&nbsp;

Destination change should distinguish, where observable:

\- exact destination URL retained;

\- same domain with different URL;

\- destination-type change;

\- own-site to third-party;

\- third-party to own-site;

\- Google/Maps/GBP to business site or reverse;

\- destination removed;

\- destination added.

&nbsp;

A singular source/destination swap MUST NOT be inferred merely because the sets differ.

&nbsp;

Ordinal strength transitions

Recommendation-strength transitions may be labeled as upgrades/downgrades because ordinal order is established.

&nbsp;

The exact transition MUST remain preserved, for example:

\- \`standard → strong\`;

\- \`top\_choice → standard\`.

&nbsp;

Numeric code differences are not effect magnitudes. A \`4 → 2\` transition MUST NOT be interpreted as mathematically twice the change of \`3 → 2\`.

&nbsp;

Position transitions

Position gain/loss must identify the exact position variable and comparable population being analyzed.

&nbsp;

Examples include:

\- first-recommendation-position change;

\- mention-position change;

\- explicit-rank change.

&nbsp;

A vague cross-variable \`position\_gain\` should not be used when the underlying metric differs.

&nbsp;

Interpretation must consider relevant set size, observability, occurrence definition, and whether the response contained semantic ranking versus mere rendered order.

&nbsp;

Regain semantics

A \`recommendation\_regain\` requires a confirmed prior recommendation-positive state, an intervening confirmed loss under the same transition definition, and subsequent recommendation-positive state.

&nbsp;

A missing/unobserved intervening wave does not establish a loss. \`present → unobserved → present\` MUST NOT automatically be labeled a regain.

&nbsp;

Gap handling

For cross-wave comparisons preserve at least:

\- number of elapsed/scheduled waves;

\- number of missing/unobserved intermediate waves;

\- whether all intermediate waves are comparable/observable for the intended outcome.

&nbsp;

A business observed in two distant waves MUST NOT be described as continuously persistent across unobserved intervals.

&nbsp;

Streaks and longer-term persistence

Useful deterministic derived measures may include:

\- first observed wave;

\- first recommended wave;

\- last observed wave;

\- last recommended wave;

\- consecutive positive-wave streak;

\- waves since last positive observation;

\- cumulative positive-wave count;

\- cumulative positive replicate count;

\- cumulative observed replicate denominator.

&nbsp;

Every streak or persistence metric must identify its threshold definition, such as any-presence, majority, or unanimous persistence.

&nbsp;

Long-term persistence windows remain parameterized rather than hard-coded in V1. Analysis contracts may later define windows such as:

\- N consecutive waves;

\- N of the last M waves;

\- rolling windows;

\- pre/post event windows.

&nbsp;

Structural-break comparability

Cross-wave transitions require an explicit comparability state.

&nbsp;

Candidate states include:

\- \`comparable\`;

\- \`prompt\_version\_changed\`;

\- \`product\_structural\_break\`;

\- \`collection\_method\_changed\`;

\- \`session\_configuration\_changed\`;

\- \`resolution\_version\_materially\_changed\`;

\- \`insufficient\_observability\`;

\- \`other\_noncomparable\`.

&nbsp;

Transitions across noncomparable regimes may still be stored, but they MUST NOT silently be interpreted as ordinary business-level recommendation churn.

&nbsp;

Prompt-version regimes

Permanent prompt wording is immutable within a prompt version. A prompt-version change creates a new longitudinal regime unless a bridge/calibration design supports direct comparison and quantifies the discontinuity sufficiently for the intended analysis.

&nbsp;

Primary persistence analyses should therefore hold constant, where applicable:

\- industry;

\- market;

\- service/query concept;

\- prompt family;

\- prompt version;

\- experimental population;

\- material collection configuration.

&nbsp;

Product-event regimes

Decision 5's \`chatgpt\_product\_event\` registry must be incorporated into longitudinal interpretation. Major changes to model behavior, Search/retrieval, citations, links/destinations, local/Maps presentation, recommendation UI, tools, or other product mechanics may constitute structural breaks.

&nbsp;

A market-wide disappearance following a product change may represent a product-regime transition rather than deterioration in the businesses themselves.

&nbsp;

Entity-resolution revision versus surface churn

Entity-resolution changes MUST NOT masquerade as ChatGPT recommendation churn.

&nbsp;

If an observed business string was present in both waves but becomes canonically resolved only later, the change may be a \`resolution\_reclassification\`, not a recommendation gain.

&nbsp;

Transition calculations should preserve:

\- resolution version used;

\- canonical identity assertion used at calculation time;

\- latest reconciled identity available for reanalysis;

\- whether a transition changed because of canonical merge/split/reclassification rather than observed surface behavior.

&nbsp;

Source/support graph transitions

Where the retrieval/evidence graph is observable, the platform should be able to distinguish changes such as:

\- business persists while source changes;

\- business and source persist while stated rationale changes;

\- recommendation persists while direct link disappears;

\- recommendation persists while a third-party citation appears;

\- source relationship changes without recommendation-state change.

&nbsp;

These are separate longitudinal outcomes and MUST NOT be treated as evidence that the source change caused recommendation change.

&nbsp;

Deterministic transition tables before LLM interpretation

The system should produce deterministic transition matrices/tables before narrative interpretation.

&nbsp;

For binary replicate-count outcomes, these may include all prior/current state combinations such as \`0/3 → 0/3\`, \`0/3 → 1/3\`, through \`3/3 → 3/3\`, plus denominator-aware states where missingness applies.

&nbsp;

Equivalent exact-transition structures should exist for top choice, links, direct links, citations, destinations, strength distributions, position measures, and source relationships as appropriate.

&nbsp;

LLMs may summarize or explain deterministic outputs, but MUST NOT invent transition labels, rates, significance, or causal explanations.

&nbsp;

Decision 9 summary

Decision 9 therefore locks:

1\. cohort-compatible collection wave as the longitudinal comparison unit, with monthly Full Panel and weekly Sentinel kept distinct and immutable replicates preserved;

2\. explicit per-dimension observability and missing-not-zero treatment;

3\. exact replicate counts/frequencies before persistence labels;

4\. exact state transitions before thresholded gain/loss terminology;

5\. no single universal V1 definition of recommendation gain/loss;

6\. versioned threshold/transition definitions;

7\. prohibition on pseudo-pairing replicate numbers across waves;

8\. separate persistence models for recommendation, top choice, strength, position, links, destinations, citations, sources, and other outcome dimensions;

9\. deterministic recommendation-set additions/removals and overlap before swap claims;

10\. explicit operational definitions for business/source/destination swaps;

11\. ordinal strength-transition treatment without interval-scale misuse;

12\. exact-position-variable requirements for position transitions;

13\. regain requiring a confirmed intervening loss under the same definition;

14\. explicit gap/unobserved-wave handling;

15\. threshold/window-specific streaks and long-term persistence;

16\. structural-break comparability flags;

17\. prompt-version regime separation unless bridge/calibration evidence supports comparison;

18\. use of the product-event registry in longitudinal interpretation;

19\. separation of canonical-resolution revision from surface churn;

20\. separate source/support graph transitions without causal overclaiming;

21\. deterministic transition tables/statistics before LLM interpretation; and

22\. prohibition of a composite ChatGPT churn/stability score in V1.

&nbsp;

Decision Log Update

Decision 9 LOCKED

\- Locked cohort-compatible wave-level longitudinal comparison with immutable replicate preservation; monthly Full Panel and weekly Sentinel remain distinct cohorts.

\- Locked dimension-specific observability and missing-not-zero handling.

\- Locked exact state transitions before thresholded gain/loss labels.

\- Locked no universal V1 gain/loss threshold.

\- Locked non-pairing of replicate numbers across collection waves.

\- Locked separate persistence/churn models by outcome dimension.

\- Locked deterministic set changes before business/source/destination swap assertions.

\- Locked ordinal strength and metric-specific position transitions.

\- Locked regain/gap/streak/window semantics.

\- Locked structural-break, prompt-version, product-event, and entity-resolution comparability governance.

\- Locked deterministic transition tables before LLM interpretation.

\- No composite ChatGPT stability/churn score is authorized in V1.

&nbsp;

LOCKED Decision 10 — Control Selection

Status: LOCKED

&nbsp;

Foundational rule

There is no universal ChatGPT control business or universal control group. Control selection MUST be estimand-aware and must follow the exact outcome, exposure, population, and comparison question defined in the applicable Analysis Specification Contract.

&nbsp;

The valid controls for studying entity visibility are not automatically the valid controls for studying recommendation inclusion, top-choice elevation, link exposure, destination type, citation support, or longitudinal transitions. Controls MUST reflect the stage of the outcome process being studied rather than collapsing all non-winning businesses into one comparison class.

&nbsp;

Outcome-funnel control architecture

The preferred control logic follows the outcome funnel:

&nbsp;

\- Entity visibility: cases are surfaced businesses; preferred controls are eligible but non-surfaced businesses.

\- Recommendation inclusion: cases are recommended businesses; preferred controls are surfaced, viable, non-recommended businesses when the estimand is recommendation conditional on visibility.

\- Top-choice elevation: cases are top-choice businesses; preferred controls are recommended but non-top-choice businesses.

\- Recommendation strength: higher-strength cases are compared with eligible lower-strength recommendations under an explicitly defined ordinal estimand.

\- Linked mention: cases are visible/surfaced businesses whose mention is linked; preferred controls are comparable visible/surfaced businesses whose mention is unlinked.

\- Direct own-site link: cases are own-site-linked businesses; controls are comparable visible/linked businesses receiving another destination type or no direct business destination, depending on the estimand.

\- Destination type: cases receiving destination type X are compared with otherwise eligible visible/recommended businesses receiving other destination states.

\- Citation/evidence support: cases are citation-supported businesses/claims; controls are comparable visible/recommended businesses or claims without observed citation support, but only when citation observability is valid.

&nbsp;

These stages answer different questions and MUST NOT be silently pooled. For example, \`recommended vs invisible\` studies a mixture of visibility and recommendation processes, while \`recommended vs visible-but-not-recommended\` targets recommendation conditional on visibility.

&nbsp;

Two distinct control universes

Decision 10 distinguishes two control universes:

&nbsp;

1\. Response-conditioned controls — businesses actually surfaced in the ChatGPT response but not receiving the target downstream outcome.

2\. Market-eligible external controls — businesses not surfaced in the ChatGPT response but independently established as plausibly eligible for the relevant service/query concept and market condition.

&nbsp;

The two universes MUST remain distinguishable. Response-conditioned controls are especially useful for downstream outcomes such as recommendation, top choice, links, and citation support. External eligible controls are necessary for studying entity visibility itself.

&nbsp;

Non-appearance does not establish control validity

A business is not a scientifically valid control merely because ChatGPT did not mention or recommend it.

&nbsp;

Control eligibility must be established independently of the ChatGPT outcome. Businesses that are closed, irrelevant to the service concept, outside the defined eligible population, or otherwise incapable of satisfying the controlled user intent MUST NOT be treated as equivalent non-winners simply because their observed ChatGPT outcome is zero/non-appearance.

&nbsp;

Geographic eligibility MUST follow Decision 4\. Physical municipal boundaries, hidden addresses, or conventional Local SEO assumptions MUST NOT be used as automatic exclusion criteria for service-area businesses or out-of-city businesses when service-market eligibility remains plausible.

&nbsp;

Versioned control-eligibility assertions

Control eligibility should be represented as a versioned assertion linking a canonical entity to a specific research condition or eligibility population.

&nbsp;

Candidate states may include:

\- \`eligible\`;

\- \`probably\_eligible\`;

\- \`ineligible\`;

\- \`unknown\`.

&nbsp;

Primary confirmatory control selection should use \`eligible\` by default. \`probably\_eligible\` may enter explicitly labeled sensitivity or exploratory analyses. \`unknown\` MUST NOT silently become eligible.

&nbsp;

Eligibility assertions should retain their evidence, methodology/version, timestamp/effective period, service/query concept, market context, and applicable entity grain.

&nbsp;

Eligibility independent of ChatGPT outcome

Eligibility MUST be determined from logically prior/external evidence rather than from ChatGPT success itself. The system MUST NOT define a business as market-eligible merely because it appeared in ChatGPT, nor define eligibility from recommendation frequency or other target outcomes.

&nbsp;

Potential evidence can come from the shared canonical business/GBP/domain/service universe, service/category evidence, website/service evidence, known operating/service-area relationships, and other versioned shared signals, subject to the later schema and analysis contracts.

&nbsp;

Population of inference

Every control-based analysis MUST declare its \`population\_of\_inference\`.

&nbsp;

The shared research universe may provide a defensible pool of market/service-eligible competitors, but it is not automatically a census of every real-world business capable of serving the market. Findings based on matched research-universe controls MUST NOT be generalized to all real-world businesses unless the design supports that inference.

&nbsp;

Estimand-aware matching

Control selection starts with the research question:

&nbsp;

\`research question → outcome → exposure → eligible population → pre-exposure confounders → control-selection method\`

&nbsp;

The exposure under study MUST NOT be used as a matching criterion in a way that removes the contrast being estimated.

&nbsp;

Examples:

\- when studying review count, do not force-match on review count;

\- when studying Maps visibility, do not force-match on Maps visibility;

\- when studying DR, do not force-match on DR;

\- when studying brand demand, do not force-match on branded search demand.

&nbsp;

Potential mediators or colliders MUST NOT be automatically controlled or matched merely because the signal exists in the warehouse.

&nbsp;

Variable-role classification

Each Analysis Specification Contract should be able to classify variables as, where applicable:

\- outcome;

\- exposure\_of\_interest;

\- pre\_exposure\_confounder;

\- matching\_variable;

\- stratification\_variable;

\- mediator\_candidate;

\- collider\_candidate;

\- effect\_modifier;

\- descriptive\_only.

&nbsp;

Collection of a signal does not authorize its automatic use as a matching/control variable.

&nbsp;

Preferred comparison strata

Where scientifically appropriate, the preferred starting comparison stratum for primary cross-sectional work is:

&nbsp;

\- same industry/service concept;

\- same market;

\- same controlled service/query concept;

\- same prompt family;

\- same prompt version;

\- same observation period/wave;

\- same experimental population/configuration where material.

&nbsp;

Further matching or adjustment is estimand-specific rather than universally mandatory.

&nbsp;

Same-wave preference

Cross-sectional controls should normally come from the same collection wave because ChatGPT product state, web evidence, competitor state, and other relevant signals can change over time.

&nbsp;

Historical controls may be used in explicit longitudinal designs, but they MUST NOT be substituted for same-period controls without an analysis-specific justification.

&nbsp;

Downstream-outcome conditioning

Recommendation, top-choice, link, destination, and citation analyses should condition on the appropriate upstream state when that matches the estimand.

&nbsp;

Examples:

\- recommendation mechanism: \`visible \+ recommended\` vs \`visible \+ not\_recommended\`;

\- top-choice mechanism: \`recommended \+ top\_choice\` vs \`recommended \+ not\_top\_choice\`;

\- link mechanism: \`visible \+ linked\` vs \`visible \+ unlinked\`;

\- direct destination mechanism: \`linked → own\_site\` vs \`linked → other\_destination\`;

\- citation-support mechanism: \`recommended \+ citation\_supported\` vs \`recommended \+ no\_observed\_citation\_support\`, conditional on citation observability.

&nbsp;

The system MUST NOT treat an unobservable citation/link state as a confirmed absence.

&nbsp;

Multiple controls, weights, and reuse

Decision 10 does not mandate one case → one control.

&nbsp;

Permitted designs may later include exact matching, stratification, nearest-neighbor methods, coarsened matching, weighting, propensity-style methods, full regression without explicit matching, or hybrid designs, subject to Decision 13\.

&nbsp;

Multiple controls per case and weighted control sets are permitted.

&nbsp;

A control may be reused across multiple cases when the statistical design accounts for dependence/reuse. Matching without replacement is NOT universally required.

&nbsp;

Control-selection records should preserve, where applicable:

\- case ID;

\- control ID;

\- control-selection run ID;

\- selection method;

\- match weight;

\- matching variables;

\- eligibility version;

\- analysis specification ID.

&nbsp;

No acceptable control is preferable to a poor forced match

If no scientifically credible control exists under the specified methodology, the case may remain unmatched with a state such as \`no\_acceptable\_control\`.

&nbsp;

The system MUST NOT force a weak control merely to preserve sample size or produce visually neat pairs.

&nbsp;

Match quality and common support

Where explicit matching or weighting is used, the system must preserve diagnostics sufficient to evaluate match quality, including where applicable:

\- matching-variable balance;

\- candidate control count;

\- selected control count;

\- match/distance metric;

\- overlap/common support;

\- exclusion reasons;

\- unmatched cases;

\- effective sample size for weighted designs.

&nbsp;

A dataset MUST NOT be described as having matched controls without diagnostics supporting the comparison.

&nbsp;

Cases or subgroups lacking sufficient covariate overlap/common support should be explicitly marked outside the supported comparative population rather than forced into an estimate.

&nbsp;

Longitudinal transition controls

Longitudinal transition analysis supports at least three complementary comparison designs:

&nbsp;

1\. Within-entity pre/post — the same business before and after a defined transition.

2\. Matched non-transition controls — eligible comparable businesses that do not experience the target transition during the comparison window.

3\. Incoming-versus-outgoing comparison — where Decision 9's operational business-swap rules support a credible outgoing/incoming pairing.

&nbsp;

These designs answer different questions and MUST remain distinguishable.

&nbsp;

Within-entity analyses should become increasingly important as longitudinal history accumulates because they reduce confounding from stable time-invariant business characteristics, while still not automatically establishing causation.

&nbsp;

Risk-set-aware transition controls

Transition controls MUST come from businesses capable of experiencing the event at baseline.

&nbsp;

Examples:

\- gain analyses should generally draw controls from businesses in the same relevant baseline non-positive state;

\- loss analyses should generally draw controls from businesses in the same relevant baseline positive state.

&nbsp;

Businesses not at risk for the event under the transition definition MUST NOT be treated as equivalent non-events merely because they did not transition.

&nbsp;

No future-information leakage

Historical control eligibility, matching, and covariates MUST use time-appropriate information. Future business state or later-discovered attributes MUST NOT silently leak into an earlier analysis unless the design explicitly reconstructs and validates the historical state.

&nbsp;

Control-selection reproducibility

Every control-selection run used for research should be reproducible and versioned. Preserve, where applicable:

\- \`control\_selection\_run\_id\`;

\- \`analysis\_spec\_id\`;

\- case definition;

\- control definition;

\- eligibility version;

\- population of inference;

\- matching variables and excluded variables;

\- matching/weighting method;

\- parameters;

\- candidate pool;

\- selected controls;

\- weights;

\- balance/common-support diagnostics;

\- random seed where relevant;

\- code/methodology version;

\- timestamp.

&nbsp;

Analyst cherry-picking prohibited

Primary research controls MUST NOT be selected ad hoc because an analyst believes certain competitors "look similar." Manual review/override is permitted only when transparently documented under a versioned method, with reason and provenance, and should be excluded from confirmatory analysis by default unless the methodology explicitly permits it.

&nbsp;

Progressive and cost-aware control enrichment

Control enrichment should follow a progressive sequence where feasible:

&nbsp;

\`eligible pool → inexpensive/basic matching evidence → candidate controls → selected controls → deeper enrichment\`

&nbsp;

The platform should reuse fresh shared signals and avoid deeply enriching every eligible business before control selection when cheaper screening is scientifically sufficient.

&nbsp;

Cost optimization MUST NOT weaken scientific eligibility. A known better control MUST NOT be replaced with a biased alternative merely because the better control requires additional enrichment. Cost savings should come from deduplication, caching, progressive enrichment, batching, and reuse.

&nbsp;

Negative-control support

The architecture should support later negative-control analyses defined under Decision 13 and the parent statistical-governance framework. Exact negative-control exposures/outcomes are not locked by Decision 10\.

&nbsp;

Decision 10 summary

Decision 10 therefore locks:

1\. no universal ChatGPT control group;

2\. estimand-aware control selection;

3\. outcome-funnel-specific controls;

4\. eligible non-visible controls for entity-visibility analysis;

5\. response-conditioned controls for downstream outcomes where appropriate;

6\. separate response-conditioned and external eligible control universes;

7\. non-appearance alone is not control eligibility;

8\. versioned eligibility assertions independent of ChatGPT outcome;

9\. confirmed eligibility for primary confirmatory controls by default;

10\. explicit population-of-inference statements;

11\. prohibition on unsupported generalization from research-universe controls to all real-world businesses;

12\. prohibition on matching away the exposure of interest;

13\. mediator/collider caution and Analysis Specification Contract variable roles;

14\. preferred same-industry/market/service/prompt/time strata where appropriate;

15\. same-wave preference for cross-sectional controls;

16\. appropriate upstream-state conditioning for recommendation, top-choice, link, destination, and citation analyses;

17\. support for multiple controls, weights, control reuse, and method-specific replacement rules;

18\. \`no\_acceptable\_control\` rather than forced poor matching;

19\. required match-quality/common-support diagnostics;

20\. within-entity, matched non-transition, and incoming/outgoing longitudinal designs;

21\. baseline risk-set-aware transition controls;

22\. prohibition on future-information leakage;

23\. reproducible/versioned control-selection artifacts;

24\. prohibition on analyst cherry-picking as primary research truth;

25\. progressive, shared, cost-aware control enrichment without weakening scientific eligibility; and

26\. support for later negative-control analysis.

&nbsp;

Decision Log Update

Decision 10 LOCKED

\- Locked estimand-aware, outcome-specific control architecture.

\- Locked separate response-conditioned and external eligible control universes.

\- Locked outcome-independent, versioned control eligibility and population-of-inference requirements.

\- Locked exposure-not-matched-away and mediator/collider safeguards.

\- Locked same-condition/same-wave preference where appropriate.

\- Locked multiple-control/weight/reuse support with diagnostics and common-support handling.

\- Locked transition-specific within-entity/non-transition/incoming-outgoing control designs and baseline risk sets.

\- Locked reproducibility, no future leakage, no cherry-picking, and progressive cost-aware enrichment.

&nbsp;

LOCKED Decision 11 — Cross-Surface Join Methodology

Status: LOCKED

Foundational rule

Cross-surface joining connects observations through shared canonical entities, controlled research conditions, and explicit time alignment. It MUST NOT collapse ChatGPT, Maps, Organic, AIO, GBP, websites, sources, or other surfaces into one outcome, and co-occurrence MUST NOT be interpreted as evidence that one surface caused another.

&nbsp;

Four distinct join concepts

Decision 11 distinguishes four progressively stronger concepts:

1\. Identity join — two records/assets are linked to the same compatible canonical entity or canonical asset.

2\. Condition-aligned join — identity join plus compatible industry, market, service/query intent, and other required research conditions.

3\. Time-aligned join — condition-aligned join plus a temporally acceptable observation/signal relationship.

4\. Analysis-eligible join — identity \+ condition \+ time \+ resolution quality \+ observability \+ any additional eligibility requirements specified by the applicable Analysis Specification Contract.

&nbsp;

A shared canonical ID alone does NOT establish analytical comparability.

&nbsp;

Join eligibility and comparability state

The system should preserve distinct joinability/eligibility concepts rather than one binary joined flag. Where applicable, records may preserve states such as:

\- \`identity\_joinable\`;

\- \`condition\_joinable\`;

\- \`time\_joinable\`;

\- \`analysis\_eligible\`.

&nbsp;

An analysis-facing status may distinguish, where useful:

\- \`confirmed\`;

\- \`sensitivity\_only\`;

\- \`exploratory\_only\`;

\- \`ineligible\`;

\- \`unknown\`.

&nbsp;

A valid brand-level identity join can coexist with an ineligible location-level Maps comparison.

&nbsp;

Explicit join grain

Every cross-surface join or analysis MUST declare the relevant entity/asset grain. Candidate grains include:

\- organization;

\- brand;

\- local business/service operation;

\- GBP/location;

\- domain;

\- URL;

\- source/publisher;

\- social profile;

\- directory/review profile.

&nbsp;

The analytical question determines the permitted grain. A brand-resolved ChatGPT observation MUST NOT be treated as a confirmed local-location/GBP join merely because a same-brand location exists in the prompt market.

&nbsp;

Confirmed identity requirement

Primary confirmatory cross-surface analyses use \`resolved\` canonical identities at compatible grain by default.

&nbsp;

\`probable\_match\` remains sensitivity/exploratory/probabilistic-identity material unless a later validated methodology explicitly authorizes otherwise. Ambiguous, unresolved, likely-nonexistent, and insufficient-information states MUST NOT be silently promoted into confirmatory cross-surface truth.

&nbsp;

Identity overlap versus asset overlap

The system MUST preserve separate relationships for:

\- same business/entity;

\- same local operation/GBP;

\- same owned domain;

\- same exact URL;

\- same destination;

\- same supporting source URL;

\- same source domain/publisher/platform;

\- other verified asset relationships.

&nbsp;

A business overlap is not the same as a domain overlap, URL overlap, destination overlap, or source overlap.

&nbsp;

Surface-qualified outcome semantics

Cross-surface variables MUST retain surface-qualified semantics. For example:

\- ChatGPT recommendation frequency;

\- ChatGPT direct-link frequency;

\- Maps Top-3/Top-10/spatial visibility metrics;

\- Organic rank/visibility;

\- AIO entity visibility;

\- AIO source visibility;

\- AIO destination visibility.

&nbsp;

Generic unqualified fields such as \`rank\`, \`visibility\`, or \`citation\` MUST NOT be used where they conceal surface-specific meaning.

&nbsp;

No universal cross-surface composite

Cross-surface state is a multidimensional profile/vector, not a universal score.

&nbsp;

No universal Maps \+ Organic \+ AIO \+ ChatGPT visibility, authority, concordance, or recommendation score is authorized in V1.

&nbsp;

Query/service-intent alignment

Cross-surface analytical comparability MUST explicitly classify query/service-intent alignment. At minimum, the methodology should support distinctions such as:

\- \`exact\` — same canonical controlled service/query concept;

\- \`related\` — same industry with a related but non-identical service/query concept;

\- \`industry\_only\` — broad industry/market overlap without defensible query equivalence;

\- \`none\_or\_unknown\`.

&nbsp;

Literal query-text equality is NOT required. Channel-specific prompts/queries may differ in wording while mapping to the same canonical \`research\_query\_concept\` / service-intent identity.

&nbsp;

Preferred primary condition alignment

Where scientifically appropriate, primary confirmatory cross-surface comparison should prefer the same:

\- industry/service concept;

\- research market;

\- canonical service/query intent;

\- compatible observation period;

\- methodology/product regime where material.

&nbsp;

ChatGPT prompt family remains a ChatGPT-specific treatment dimension and MUST remain preserved even when another surface has no equivalent family. Maps or Organic observations MUST NOT be assigned artificial DISCOVERY/RECOMMEND/BEST/PROBLEM labels merely to force symmetry.

&nbsp;

Historical one-versus-two-query issue — RESOLVED / SUPERSEDED

The former Maps-two-query versus ChatGPT-one-anchor-intent conflict is no longer operative. Current implementation uses the locked surface-specific panels: Maps/Organic four core queries and ChatGPT exactly 10 approved prompt conditions. Decision 11 governs how those distinct treatments are aligned analytically without forcing literal symmetry.

&nbsp;

If a Maps query has no permanent exact ChatGPT counterpart, that state is a design/missingness/alignment state. It MUST NOT be silently averaged with the matched Maps query or represented as an observed ChatGPT negative.

&nbsp;

The schema and analysis layer MUST preserve prompt\_condition\_id, canonical service/query-intent alignment, and explicit mismatch states so the current fixed surface-specific panels can be compared reproducibly without inventing missing observations.

&nbsp;

Geographic concepts remain distinct

Cross-surface joins MUST preserve distinctions among:

\- research/prompt market;

\- physical business location;

\- service area / serves-market evidence;

\- Maps search coordinate;

\- provider/search location setting;

\- actual or simulated searcher location where applicable.

&nbsp;

A business physically outside the named municipality may still be a valid service-market entity. Decision 4 continues to govern geographic interpretation.

&nbsp;

Shared research-wave alignment

The platform should support a shared \`research\_wave\_id\` / research-week identity across surfaces for operational time alignment while preserving exact observation timestamps underneath it.

&nbsp;

Belonging to the same research wave does NOT automatically make observations temporally comparable. Exact timing, product events, methodology changes, freshness, and structural breaks must still be evaluated.

&nbsp;

Cross-surface comparability flags

A cross-surface dataset or pair should be able to record comparability states such as:

\- \`comparable\`;

\- \`product\_regime\_mismatch\`;

\- \`prompt\_version\_mismatch\`;

\- \`query\_intent\_mismatch\`;

\- \`temporal\_window\_exceeded\`;

\- \`entity\_grain\_mismatch\`;

\- \`stale\_signal\`;

\- \`missing\_surface\_observation\`;

\- \`resolution\_uncertain\`;

\- \`other\_noncomparable\`.

&nbsp;

Structural-break governance from Decisions 5 and 9 applies to cross-surface analysis.

&nbsp;

Maps cross-surface representation

There is no universal generic \`maps\_rank\` for ChatGPT cross-surface analysis.

&nbsp;

Maps may contribute approved spatial/outcome variables such as, where appropriate:

\- rank at an explicitly identified coordinate;

\- center-point rank;

\- Top-3 grid coverage;

\- Top-10 grid coverage;

\- DAVS;

\- Effective Ranking Radius;

\- distance-band outcomes;

\- other approved Maps-specific measures.

&nbsp;

The Analysis Specification Contract MUST identify the exact Maps metric used and why it matches the estimand.

&nbsp;

A business actually absent from a collected relevant Maps Top-10 observation may legitimately have \`maps\_top10\_visible \= false\` for that observation. If no valid Maps observation exists, the state is missing/unobserved rather than a negative.

&nbsp;

Organic join levels

Organic cross-surface analysis MUST distinguish, where applicable:

1\. exact-URL visibility — the exact ChatGPT-linked/destination URL ranks;

2\. same-domain visibility — another URL on the same domain ranks;

3\. canonical-business-owned visibility — another verified business-owned/represented asset ranks.

&nbsp;

These states MUST NOT be flattened into one generic Organic rank.

&nbsp;

Destination architecture as a first-class cross-surface relationship

The platform should be able to compare a ChatGPT destination against:

\- the exact Organic ranking URL;

\- another ranking URL on the same domain;

\- the GBP linked page;

\- an AIO cited/destination URL;

\- the canonical business homepage/service/location/other page;

\- a third-party profile or publisher destination.

&nbsp;

Homepage, service-page, location-page, other-business-page, Google/GBP/Maps, and third-party destination types remain analytically distinct.

&nbsp;

AIO join semantics

AIO source visibility, entity visibility, and destination visibility remain separate when joined to ChatGPT outcomes.

&nbsp;

AIO local-business-card inclusion and direct embedded-GBP visibility remain surface-qualified presentation outcomes rather than being collapsed into Maps visibility or ChatGPT recommendation.

&nbsp;

Cross-surface AIO relationships may include, separately:

\- same entity;

\- same GBP/local operation;

\- same owned domain;

\- same owned URL;

\- same destination;

\- same supporting source URL;

\- same source domain/publisher.

&nbsp;

Source and publisher joins

Supporting-source analysis should preserve exact URL, canonical URL, domain, publisher/source identity, platform/site type, and business relationship where available.

&nbsp;

The platform should be able to study whether ChatGPT and AIO rely on the same third-party source ecosystems without losing URL-level evidence.

&nbsp;

Source overlap or citation overlap does NOT establish that the source caused a recommendation.

&nbsp;

Social asset relationships

Business-owned social profiles and third-party social mentions MUST remain distinct.

&nbsp;

A social URL MUST NOT become a business-owned asset merely because it mentions the business. Ownership/representation requires a verified graph relationship.

&nbsp;

Temporal alignment windows

Every cross-surface analysis MUST define its acceptable temporal alignment window and applicable signal-freshness rules.

&nbsp;

For each joined signal/observation, the system should preserve or derive:

\- target observation time;

\- source/signal observation or effective time;

\- signal age;

\- freshness/staleness state;

\- temporal relation to the target outcome.

&nbsp;

Stale signals MUST NOT be indefinitely forward-filled as though unchanged.

&nbsp;

Temporal direction

Where the research question concerns temporal relationships, preserve whether a signal or surface state is:

\- pre-outcome;

\- contemporaneous / same observation interval;

\- post-outcome;

\- ordering uncertain.

&nbsp;

A signal observed after a ChatGPT transition MUST NOT be described as preceding that transition.

&nbsp;

Same-wave does not mean simultaneous

When two transitions are first detected in the same scheduled observation interval, the platform may report \`same\_observation\_interval\` but MUST NOT manufacture sub-cadence ordering unless timestamps and collection design genuinely support it. The interval must identify its cohort/cadence (for example monthly Full Panel or weekly Sentinel).

&nbsp;

Cross-surface transitions and lags

The historical model MUST support deterministic construction of cross-surface transition/lag analyses such as:

\- Maps change preceding/following ChatGPT change;

\- Organic change preceding/following ChatGPT change;

\- AIO change preceding/following ChatGPT change;

\- review, brand-demand, link, content, or source changes preceding/following ChatGPT outcomes.

&nbsp;

Lag windows are parameterized by the Analysis Specification Contract rather than hard-coded as a single correct lag.

&nbsp;

Lagged variables should be generated deterministically from raw histories rather than requiring a permanently denormalized column for every possible lag.

&nbsp;

Shared signals and enrichment

Once a ChatGPT entity resolves to a canonical entity/asset, the ChatGPT module MUST reuse sufficiently fresh shared signals already collected for Maps, Organic, AIO, Client Mode, or another platform purpose when provider metric, economic unit, and freshness requirements are equivalent.

&nbsp;

ChatGPT MUST NOT duplicate shared review, GBP, DR/RD/URL authority, backlink, page-content, embedding, site-size, social-identity, brand-demand, citation, or other shared signal histories simply because the entity appeared on another surface.

&nbsp;

Shared signals remain owned by the parent signal warehouse rather than copied into separate per-surface truth columns.

&nbsp;

Generated analysis-specific datasets

Cross-surface research datasets should be generated from normalized surface observations \+ the shared canonical graph \+ shared signal histories \+ the applicable Analysis Specification Contract.

&nbsp;

The platform MUST NOT create one permanently flattened \`everything\_table\` that treats different entity grains, timestamps, queries, coordinates, URLs, replicates, AIO sources, and methodologies as though they were naturally one row.

&nbsp;

Versioned dataset provenance

Every cross-surface analytical dataset used to support a research finding should preserve enough provenance to reproduce its construction, including where applicable:

\- \`cross\_surface\_dataset\_id\`;

\- \`analysis\_spec\_id\`;

\- canonical-graph / entity-resolution version;

\- intent-alignment version;

\- temporal-alignment rule;

\- signal-freshness policy;

\- surface methodology versions;

\- eligible-population definition;

\- code version;

\- generation timestamp;

\- row count and exclusion counts.

&nbsp;

Join coverage and QA

Cross-surface dataset QA MUST report the join funnel rather than only the final row count. Useful measures include:

\- ChatGPT entities observed;

\- resolved share at required grain;

\- joinable share by surface;

\- exact-intent-aligned share;

\- related-intent share;

\- time-aligned share;

\- location-level join share;

\- brand-only join share;

\- exact-URL-match share where relevant;

\- stale-signal exclusions;

\- missing-surface observations;

\- unjoinable/unmatched counts;

\- sensitivity-only/probable-match counts where relevant.

&nbsp;

A finding MUST NOT imply whole-panel coverage when only a subset met the required join criteria.

&nbsp;

Missing versus negative surface state

Missing/unobserved surface data is not negative presence.

&nbsp;

Examples:

\- no Maps observation ≠ Maps non-visible;

\- no Organic observation ≠ not ranking;

\- no AIO observation ≠ AIO absent;

\- no social enrichment ≠ no social profile.

&nbsp;

Confirmed negative values require an observation/methodology capable of establishing that negative state.

&nbsp;

Cross-surface overlap remains descriptive/associational by default

Observed overlap, discordance, predictive importance, or temporal association between surfaces does NOT by itself prove that one surface is a causal input, recommendation factor, ranking factor, or mechanism for another.

&nbsp;

Examples such as high Maps Top-3 overlap among ChatGPT recommendations, strong Organic visibility among linked businesses, or common AIO/ChatGPT source use remain descriptive/associational until stronger research design supports a stronger evidence label.

&nbsp;

Cross-surface finding independence

A validated finding in Maps, Organic, or AIO does NOT automatically become a validated ChatGPT finding merely because the same signal overlaps ChatGPT outcomes.

&nbsp;

Every new cross-surface finding requires its own population, estimand, exposure/outcome definition, controls, timing, statistical method, uncertainty, validation, replication, and evidence classification.

&nbsp;

Heterogeneity

Cross-surface relationships should remain capable of varying by:

\- industry;

\- market;

\- prompt family;

\- service/query intent;

\- business model;

\- SAB versus storefront;

\- franchise/multi-location status;

\- product/model regime;

\- time period;

\- other justified effect modifiers.

&nbsp;

A relationship observed in one cohort MUST NOT be automatically generalized across all local businesses.

&nbsp;

Cross-surface discordance as a first-class outcome

A cross-surface discordance is an analytically interesting mismatch between otherwise compatible surface states, not automatically a data-quality error.

&nbsp;

Examples include:

\- ChatGPT recommended / Maps weak;

\- Maps strong / ChatGPT absent;

\- ChatGPT top choice / Organic weak;

\- Organic strong / ChatGPT unlinked;

\- AIO visible / ChatGPT absent;

\- ChatGPT recommended / no own-site destination.

&nbsp;

Discordant populations may be analyzed directly to discover which signals distinguish surface-specific winners from businesses that win everywhere.

&nbsp;

Outcome-specific concordance/discordance

There is no universal cross-surface concordance definition.

&nbsp;

Each analysis must state the exact outcome thresholds being compared, for example ChatGPT majority recommendation × Maps Top-10, ChatGPT top-choice × Maps Top-3, or ChatGPT direct-link × Organic Top-10.

&nbsp;

Dimension-specific concordance states may be derived, but no composite concordance/authority score is authorized.

&nbsp;

Outcome-conditioning hierarchy carries across surfaces

Decision 10's outcome funnel applies to cross-surface exposures.

&nbsp;

For example, a question about whether Organic strength predicts ChatGPT linking may be estimated among all eligible businesses or conditional on ChatGPT already surfacing the business. Those are different estimands.

&nbsp;

Likewise, whether Maps prominence predicts ChatGPT top-choice status may be studied among all eligible businesses, visible businesses, or recommended businesses. The applicable Analysis Specification Contract MUST define the conditioning population rather than silently mixing stages.

&nbsp;

Cross-surface controls inherit Decision 10

When a surface state is the exposure of interest, the control-selection process MUST NOT match away that exposure.

&nbsp;

Examples:

\- when testing Maps visibility as an exposure, do not force-match on Maps visibility;

\- when testing Organic rank as an exposure, do not force-match on Organic rank;

\- when testing AIO visibility as an exposure, do not force-match on AIO visibility.

&nbsp;

Control eligibility, common support, temporal leakage, matching quality, and reproducibility remain governed by Decision 10\.

&nbsp;

Mediator/collider preservation

Cross-surface joining must preserve enough temporal and graph structure for later statistical contracts to distinguish possible exposures, confounders, mediators, colliders, outcomes, and effect modifiers.

&nbsp;

A correlated surface signal MUST NOT automatically be adjusted for merely because it exists. For example, Maps or Organic visibility could in some hypotheses lie on a pathway between an upstream business signal and ChatGPT outcome.

&nbsp;

No new cross-surface canonical truth system

ChatGPT MUST NOT create parallel truth identifiers such as independent ChatGPT→Maps, ChatGPT→AIO, or ChatGPT→Organic business identities.

&nbsp;

All identity-bearing joins flow through the shared versioned canonical graph. Analysis-specific join records may reference shared IDs and join assertions, but they MUST NOT replace the canonical graph.

&nbsp;

Decision 11 summary

Decision 11 therefore locks:

1\. identity, condition, temporal, and analysis-eligibility joins as distinct concepts;

2\. explicit entity/asset join grain;

3\. compatible resolved identity for primary confirmatory joins;

4\. probable matches restricted to sensitivity/exploratory contexts by default;

5\. exact industry/market/service-intent alignment as the preferred primary comparison foundation where appropriate;

6\. preservation of ChatGPT prompt family as a surface-specific treatment;

7\. canonical service-intent alignment rather than literal query equality;

8\. exact/related/industry-only/no-alignment states;

9\. explicit resolution of the historical one-versus-two-query conflict through the current surface-specific fixed panels, while preserving exact/related/industry-only/no-alignment states;

10\. shared research-wave alignment with exact timestamps/product regimes preserved;

11\. structural-break and methodology mismatch comparability flags;

12\. separation of market, physical location, service area, searcher/provider location, and Maps coordinates;

13\. exact identification of the Maps spatial metric used;

14\. prohibition of a generic universal Maps rank;

15\. exact-URL, same-domain, and business-owned Organic visibility distinctions;

16\. first-class ChatGPT destination ↔ Organic page ↔ GBP-linked page ↔ AIO destination relationships;

17\. separate AIO entity/source/destination/local-card/embedded-GBP joins;

18\. separation of business identity overlap from asset/source overlap;

19\. supporting-source overlap as a separately analyzable relationship;

20\. explicit temporal windows and freshness rules;

21\. preservation of pre/contemporaneous/post temporal position;

22\. same-wave non-equivalence to exact simultaneity/order;

23\. parameterized deterministic lag analysis from histories;

24\. separation of actual negative outcomes from missing/unobserved data;

25\. reuse of shared parent-platform enrichment and signals;

26\. analysis-specific generated cross-surface datasets rather than a permanent everything-table;

27\. reproducible/versioned cross-surface dataset construction;

28\. mandatory join-coverage/exclusion/quality reporting;

29\. descriptive/associational interpretation of overlap unless stronger evidence exists;

30\. prohibition on treating predictive importance as causal surface influence;

31\. first-class cross-surface transitions and temporal-precedence research;

32\. first-class cross-surface discordance;

33\. outcome/threshold-specific concordance and discordance definitions;

34\. inheritance of Decision 10's outcome-conditioning and control rules;

35\. preservation of potential mediator/collider structure rather than blind adjustment;

36\. independent validation/evidence requirements for cross-surface findings;

37\. prohibition of a universal cross-surface visibility/authority/concordance score; and

38\. prohibition on any separate ChatGPT cross-surface canonical truth system.

&nbsp;

Decision Log Update

Decision 11 LOCKED

\- Locked canonical-graph-based joins with explicit entity grain, condition alignment, and temporal alignment.

\- Locked surface-qualified outcome semantics and no universal cross-surface composite.

\- Locked exact/related/industry-only intent alignment and reconciled the historical query-count conflict to the current surface-specific fixed panels.

\- Locked Maps spatial-metric specificity, Organic URL/domain/business distinctions, and AIO entity/source/destination distinctions.

\- Locked first-class destination/source relationships across ChatGPT, Organic, GBP, and AIO.

\- Locked explicit temporal windows, structural-break comparability, lag support, and no invented sub-cadence ordering.

\- Locked shared-signal reuse and analysis-specific generated datasets rather than an everything-table.

\- Locked join-coverage QA, missing-versus-negative treatment, discordance analysis, and independent cross-surface evidence validation.

\- Locked Decision 10 outcome-conditioning/control inheritance and mediator/collider safeguards.

\- No separate cross-surface canonical truth system or composite cross-surface score is authorized.

&nbsp;

LOCKED Decision 12 — ChatGPT-Specific Explanatory Signals

Status: LOCKED

Foundational rule

ChatGPT-specific explanatory signals describe the prompt-to-retrieval-to-evidence-to-response process. They MUST remain separate from shared business attributes, surface outcomes, and causal claims. Every research-used signal must preserve where in the process it was observed and whether it occurred before, during, or after the outcome being studied.

Shared signals are reused, not duplicated

Maps, Organic, GBP, review, link, brand-demand, website, AIO, social, business-identity, and other cross-platform signals already governed by the parent architecture remain shared signals. The ChatGPT module MUST NOT create duplicate truth fields such as \`chatgpt\_review\_count\`, \`chatgpt\_DR\`, or \`chatgpt\_business\_age\` merely because those values are used in a ChatGPT analysis.

If ChatGPT itself states a value or attribute, that model-stated claim is stored separately as an observed response claim and MUST NOT overwrite the verified shared attribute.

Process-oriented signal families

ChatGPT-specific explanatory signals should be organized around the observable process graph:

\`controlled prompt → Search invocation → fanout/query generation → retrieved results/sources → evidence/citations → entity surfacing → recommendation → link/destination\`

Primary ChatGPT-specific signal families include:

1\. product/execution context;

2\. Search invocation;

3\. fanout and query transformation;

4\. retrieval exposure;

5\. entity retrieval exposure;

6\. source/evidence topology;

7\. first-party versus third-party evidence;

8\. destination-selection behavior;

9\. recommendation/rationale process signals;

10\. cross-replicate process stability;

11\. identity/model-quality signals; and

12\. lagged historical ChatGPT state.

Signal process stage

Every analytical variable must retain a conceptually explicit process stage. Controlled values may include:

\- \`pre\_prompt\`;

\- \`prompt\_treatment\`;

\- \`search\_invocation\`;

\- \`fanout\`;

\- \`retrieval\`;

\- \`evidence\`;

\- \`response\`;

\- \`destination\`;

\- \`post\_response\`;

\- \`historical\_lag\`;

\- \`product\_regime\`.

This does not require one literal database column in every table; it requires the methodology and later schema to preserve the distinction.

Temporal relationship to target outcome

For an analysis-specific target outcome, preserve the signal's temporal/process relationship using concepts such as:

\- prior;

\- same\_process\_before\_outcome where actually observable;

\- contemporaneous;

\- downstream;

\- post-outcome;

\- ordering\_unknown.

A response-stage or downstream variable MUST NOT automatically be treated as a pre-outcome predictor merely because it is correlated with the target outcome.

Search invocation

Decision 5's Search variables remain first-class. \`search\_invoked\` may be analyzed as an outcome in one Analysis Specification Contract and as a process variable in another.

Examples include studying which prompt families or industries predict Search invocation, or studying recommendation behavior conditional on Search being invoked.

Search invocation does not by itself establish that Search caused a recommendation.

Observed fanout/query signals

Observed fanout queries are a first-class ChatGPT-specific signal family. Raw query text remains authoritative and immutable under the observation record.

Versioned multi-label fanout classifications may include:

\- generic service;

\- service \+ market;

\- near-me;

\- superlative/best;

\- review/reputation;

\- directory-specific;

\- publisher-specific;

\- Google/Maps-specific;

\- social/community-specific;

\- price/value;

\- credentials/licensing;

\- experience/longevity;

\- emergency/urgency;

\- problem-specific;

\- service subtype;

\- comparison;

\- business/brand-specific;

\- exact business name;

\- exact domain;

\- location/branch-specific;

\- other;

\- unclear.

Only observed fanout queries may be represented as observed product behavior. Reconstructed/inferred fanout remains explicitly derived/inferred.

Brand-query emergence

Generic-to-branded query emergence is a first-class retrieval-process event where observable.

Potential derived fields include:

\- \`brand\_query\_generated\`;

\- resolved brand/business entity ID where supported;

\- brand-query sequence;

\- brand-query count;

\- first brand-query stage.

This supports research into when a generic local-recommendation process transitions into branded verification/retrieval.

Brand-query emergence MUST NOT automatically be interpreted as evidence that external brand demand caused the recommendation; branded retrieval may itself occur downstream of earlier candidate selection.

Query reformulation

The system should preserve and derive observable query-transformation characteristics such as:

\- fanout count;

\- fanout depth/stage;

\- number of distinct query-intent classes;

\- reformulation count;

\- geography retained/removed;

\- service specificity increased/decreased;

\- superlative introduced;

\- review/reputation intent introduced;

\- credential intent introduced;

\- source/platform restriction introduced;

\- brand/entity query introduced.

These remain separate variables. No composite \`fanout\_quality\_score\` is authorized.

Retrieval exposure

For every technically observable retrieved result, preserve at least where available:

\- fanout query ID;

\- result sequence/order;

\- raw URL;

\- canonical URL;

\- domain;

\- publisher/source entity;

\- title;

\- snippet;

\- provider/tool provenance;

\- retrieval timestamp;

\- canonical business relationship where independently established.

Derived retrieval variables may include unique URL/domain/publisher counts, first-party retrieval count, third-party retrieval count, business-specific source count, and source-type distribution.

ChatGPT retrieval position is not Organic rank

A ChatGPT retrieval result position describes the observed position inside that ChatGPT retrieval result set. It MUST NOT be renamed or treated as Google Organic rank unless an independently collected Organic observation establishes that ranking under the Organic methodology.

Decision 11 permits comparison of the two surfaces; it does not make them equivalent.

Retrieval-to-recommendation funnel

Where observable, preserve separate states across the process funnel:

\`retrieved → associated\_with\_business → cited → business surfaced → business recommended → business linked → top choice\`

Retrieved, cited, surfaced, recommended, linked, and top-choice remain different events.

Useful stage-specific analyses may include:

\- retrieved but not surfaced;

\- surfaced but not recommended;

\- recommended but not linked;

\- own-site retrieved but not cited;

\- source cited without business recommendation;

\- recommended entity with no observable supporting source.

Negative states are valid only when the relevant stage was actually observable.

Observed sequence is not automatically causal mechanism

An observed chain such as \`owned site retrieved → cited → recommendation\` may provide process evidence, but it does not prove that retrieval caused the recommendation. Hidden product mechanics may be unobservable.

The platform may describe observable retrieval/recommendation sequence but MUST NOT label it a causal recommendation pathway without stronger evidence.

No observed support is not model memory

If a recommendation has no observable supporting source, permitted states include \`no\_observed\_support\`, \`support\_unobservable\`, or equivalent methodology-defined states.

The module MUST NOT infer or label the recommendation as \`from\_model\_memory\` merely because retrieval evidence is absent.

Source-use composition

ChatGPT-specific source usage should reuse the shared canonical source taxonomy while storing the ChatGPT-specific fact that a source was retrieved, cited, linked, or used as an exposed destination.

Source classes may include:

\- first-party business website;

\- Google/Maps/GBP;

\- review platform;

\- local directory;

\- vertical directory;

\- publisher/editorial;

\- government/licensing;

\- professional association;

\- social platform;

\- community/forum;

\- booking/marketplace;

\- aggregator;

\- other;

\- unclear.

First-party versus third-party evidence

For each relevant entity, preserve or derive separately where observable:

\- \`own\_site\_retrieved\`;

\- \`own\_site\_cited\`;

\- \`own\_site\_linked\`;

\- \`third\_party\_retrieved\`;

\- \`third\_party\_cited\`;

\- \`third\_party\_linked\`.

This supports analysis of first-party evidence, third-party corroboration, mixed evidence, and no-observable-evidence states without collapsing them.

Independent source corroboration

URL count does not equal independent corroboration. Where relevant, preserve separate counts such as:

\- supporting URL count;

\- supporting domain count;

\- supporting publisher/source count;

\- independent-source count.

Any \`independent\_source\_count\` requires an explicit, versioned deduplication methodology capable of accounting for same-publisher pages, syndication/content duplication, and other non-independent sources where detectable.

Source diversity remains dimensional

Source-type count, first-party presence, review-platform presence, editorial presence, directory presence, social/community presence, and government/licensing presence may be measured independently.

No generic \`source\_authority\_score\`, \`evidence\_quality\_score\`, or equivalent composite is authorized unless a later empirically validated methodology explicitly defines it.

Cross-replicate source and retrieval stability

Across the three permanent replicates, derive separate stability profiles for, where applicable:

\- exact source URL recurrence;

\- source-domain recurrence;

\- publisher recurrence;

\- first-party recurrence;

\- third-party recurrence;

\- business-source relationship recurrence;

\- exact fanout-query overlap;

\- normalized fanout-intent overlap;

\- brand-query overlap;

\- source-type overlap;

\- fanout-count distribution.

Recommendation stability, retrieval-query stability, source stability, destination stability, and rationale stability remain separate dimensions.

A condition may have stable recommendations but unstable source paths, or stable sources but unstable recommendations. No universal ChatGPT consistency score is authorized.

Recommendation rationales as response-stage signals

Decision 8's rationale claims remain response-stage observations unless an analysis can independently establish an earlier temporal role.

A model statement such as \`I recommend ABC because it has excellent reviews\` may create a \`review/reputation\` rationale classification, but that classification MUST NOT automatically enter a factor model as though it were an independently measured pre-recommendation review signal.

Stated rationale versus verified attribute

Model-stated claims can be joined to independently measured shared attributes without treating the model statement as truth.

Possible claim-verification states include:

\- supported;

\- contradicted;

\- partially\_supported;

\- unclear;

\- not\_checked.

Permanent collection does not require exhaustive external verification of every stated rationale. Verification may be progressive and analysis-driven.

Rationale accuracy/model quality

Rationale factual accuracy, unsupported rationale frequency, contradiction rate, persistent false claims, and similar measures may be studied as separate model-quality outcomes.

They remain distinct from the research question of which external characteristics predict recommendation.

Rationale-to-source support

Where technically observable, preserve:

\`recommended business → rationale claim → supporting source/citation\`

Support classifications may include clearly supports, partially supports, does not support, unclear, and no observable support, with raw evidence and classifier provenance retained.

Destination selection

Destination selection is a first-class ChatGPT process/outcome family. The system should support research into when a recommendation links to an own homepage, service page, location page, GBP/Maps surface, directory/review profile, publisher, social profile, booking/contact surface, or another destination.

Candidate explanatory relationships may include whether the destination URL/domain was previously retrieved or cited, whether it is first-party or third-party, and whether the same destination recurs across replicates.

The destination type itself is an outcome when destination selection is the target estimand.

Retrieval-to-destination relationship

Where observable, derive states such as:

\- \`destination\_was\_retrieved\`;

\- \`destination\_was\_cited\`;

\- \`destination\_same\_as\_supporting\_source\`;

\- \`destination\_same\_domain\_different\_url\`;

\- \`destination\_not\_observed\_in\_retrieval\`;

with true/false/unknown semantics appropriate to observability.

Semantic relationships and embeddings

The module may derive semantic similarity relationships such as:

\- prompt ↔ source;

\- prompt ↔ business/page;

\- fanout query ↔ business/page;

\- fanout query ↔ retrieved source;

\- rationale claim ↔ supporting source.

Underlying page/content embeddings MUST remain shared content-addressed assets in the parent architecture and MUST NOT be duplicated merely because ChatGPT used the content.

Embedding-derived features must preserve embedding model/version, source content hash/version, query/prompt version, similarity method, and relevant temporal provenance.

Semantic similarity is a measurement, not automatically a recommendation factor.

Distinct semantic-fit relationships

Prompt-to-business fit, fanout-to-business fit, fanout-to-source fit, and source-to-rationale fit remain separate constructs. No universal \`relevance\_score\` may collapse them without an explicitly validated later methodology.

Lagged historical ChatGPT signals

As longitudinal history accumulates, prior ChatGPT state may become a legitimate pre-outcome predictor when generated strictly from information preceding the target observation.

Potential historical features include:

\- prior recommendation frequency;

\- prior top-choice frequency;

\- prior linked-mention frequency;

\- prior Search-invocation frequency;

\- prior branded-fanout occurrence;

\- prior source-domain recurrence;

\- prior destination type;

\- prior recommendation streak;

\- prior retrieval-process stability.

Historical lag features are generated under the Analysis Specification Contract and MUST avoid future-information leakage.

Same-wave/process-role caution

Same-response or same-wave variables may be valid for conditional estimands, but their role must be explicit.

For example, \`recommended\` may legitimately condition a top-choice analysis, while same-response \`own\_site\_cited\` may be a mediator, co-occurring process variable, or downstream consequence depending on observable order and estimand.

These MUST NOT be treated as generic baseline predictors.

Observable order only

Observable execution order may be preserved where the collector/product exposes it. Hidden internal reasoning or retrieval order MUST NOT be invented.

If citations are returned only as a final bundle, the system cannot claim exact internal sequence merely from their presence.

Product and execution variables

Product/model/search/session/account/collector variables are scientifically important for regime control, structural-break analysis, nuisance adjustment, stratification, or effect-modification research.

They are not automatically client optimization signals.

Identity and model-quality signals

Canonical resolution failure, ambiguity, likely-nonexistent entities, hybrid identity errors, source/entity mismatch, destination mismatch, and model-stated factual contradiction are first-class model/data-quality outcomes and MUST NOT be discarded.

Potential model-quality states include:

\- recommended entity lacks corroborated canonical identity;

\- cited source appears to refer to a different business;

\- phone/address/domain conflict;

\- rationale contradicted by supporting source;

\- real brand with mixed branch attributes;

\- linked destination belongs to a different entity.

These outcomes may be analyzed by prompt family, industry, Search state, product regime, and other valid conditions, but are not recommendation factors by definition.

Retrieval graph metrics

The preserved retrieval/evidence graph may support deterministic metrics such as:

\- fanout-node count;

\- source-node count;

\- unique-domain count;

\- entity-node count;

\- source-to-entity edge count;

\- first-party edge count;

\- third-party edge count;

\- repeated-source count;

\- observed path depth;

\- branching factor where technically meaningful.

No composite \`retrieval\_complexity\_score\` is authorized in V1.

Cost-aware derivation and enrichment

Most ChatGPT-specific signals should be derived from already-paid raw observations through deterministic parsing before purchasing additional enrichment.

Incremental enrichment may be necessary for new source URL resolution, stale/new page crawling, external claim verification, previously unseen embeddings, or deeper source/content analysis.

Deep source enrichment should follow the parent progressive architecture:

\`raw retrieval → canonical URL/domain/source resolution → reuse fresh cached snapshot → identify analysis-relevant sources → deep enrichment only where necessary\`

The system SHOULD NOT deeply crawl/analyze every retrieved URL every week merely because it appeared in ChatGPT.

No duplicate enrichment purchases

If a retrieved ChatGPT page/domain already has sufficiently fresh crawl, content hash, embedding, authority, backlink, identity, or other shared enrichment, those records MUST be reused. Appearance in ChatGPT does not authorize a duplicate \`chatgpt\_enrichment\` purchase.

Signal provenance

ChatGPT-specific signals must distinguish at least:

1\. observed — directly exposed by the product/provider/collector;

2\. deterministically derived — mechanically derived from observed data or canonical relationships;

3\. semantically classified — model/rule-derived semantic interpretation with version/confidence provenance;

4\. inferred/hypothesized — analytical reconstruction or hypothesis not represented as observed product behavior.

Inferred/hypothesized values MUST NOT be silently promoted to observed data.

Analysis Specification Contract integration

Every ChatGPT-specific signal used in research must be governed through the applicable Analysis Specification Contract with concepts including, as relevant:

\- signal definition;

\- signal stage;

\- temporal relation to target outcome;

\- observability;

\- provenance/classification method;

\- variable role;

\- effective time;

\- freshness/staleness.

Variable roles may include exposure\_of\_interest, outcome, mediator\_candidate, pre\_exposure\_confounder, effect\_modifier, descriptive\_only, nuisance/regime, or other methodology-defined roles.

No automatic factor promotion

Decision 12 creates candidate explanatory signals, process variables, outcomes, and model-quality measures. It does NOT create a list of ChatGPT ranking/recommendation factors.

The platform MUST follow:

\`research signal → analysis → validation/replication → finding registry → strategy eligibility\`

Strong association, predictive feature importance, SHAP value, or frequent rationale occurrence does not by itself establish a causal recommendation factor.

No ChatGPT Optimization Score

No V1 metric may collapse Search behavior, fanout, source diversity, citations, recommendation frequency, first-party presence, brand-query emergence, Maps/Organic/AIO, reviews, links, or other signals into a universal \`ChatGPT Optimization Score\`, \`ChatGPT Authority Score\`, or equivalent 0–100 score.

Client Mode may later prioritize evidence-backed actions without inventing a universal score.

Decision 12 summary

Decision 12 therefore locks:

1\. ChatGPT-specific signals describe the ChatGPT prompt/retrieval/evidence/response process while shared business signals remain in the parent warehouse;

2\. no duplicate ChatGPT versions of shared Maps, Organic, GBP, review, link, brand-demand, website, AIO, social, or identity signals;

3\. explicit process-stage and temporal-relation semantics for research-used signals;

4\. separation of pre-observation, prompt-treatment, process/retrieval, response/downstream, historical-lag, and product-regime variables;

5\. Search invocation as either outcome or process variable depending on estimand;

6\. observed fanout/query generation as a first-class signal family;

7\. multi-label/versioned fanout semantics with raw queries authoritative;

8\. generic-to-branded query emergence as first-class retrieval behavior;

9\. separate query-reformulation and retrieval-strategy measurements;

10\. first-class retrieval records with URL/domain/source/order/query provenance;

11\. prohibition on treating ChatGPT retrieval order as Organic rank;

12\. separate retrieved/cited/associated/surfaced/recommended/linked/top-choice funnel stages;

13\. prohibition on treating observed funnel sequence as causal mechanism by default;

14\. prohibition on inferring \`model memory\` from lack of observable support;

15\. ChatGPT source-use composition using the shared source taxonomy;

16\. separate first-party and third-party retrieval/citation/link exposure;

17\. separate URL/domain/publisher/independent-source corroboration counts;

18\. explicit methodology required for independent-source deduplication;

19\. dimensional source diversity with no generic evidence/source-authority score;

20\. separate source, query, retrieval, rationale, destination, and recommendation stability across replicates;

21\. no universal ChatGPT consistency score;

22\. response-stage classification of recommendation rationales by default;

23\. joinability of stated rationales to independently verified shared attributes without treating model claims as truth;

24\. rationale factual accuracy and claim support as separate model-quality outcomes;

25\. preserved rationale-to-source support relationships where observable;

26\. destination-selection behavior as a first-class process/outcome family;

27\. measurable retrieval-to-destination relationships;

28\. reusable shared embeddings with ChatGPT-specific semantic relationships rather than duplicate embeddings;

29\. embedding/content/method provenance requirements;

30\. separate prompt↔business, fanout↔business, fanout↔source, and source↔rationale constructs;

31\. lagged historical ChatGPT state as valid pre-outcome input only when time-aligned without leakage;

32\. explicit same-wave/process-role treatment;

33\. observable process order preservation without fabricated hidden reasoning order;

34\. product/session/model variables as regime/nuisance/effect-modifier candidates rather than default client optimization signals;

35\. resolution failure, hallucination, identity mismatch, source mismatch, and related quality problems as first-class outcomes;

36\. deterministic retrieval-graph metrics without a composite retrieval-complexity score;

37\. derivation from existing raw observations before buying additional enrichment;

38\. progressive, cached, deduplicated, freshness-aware source enrichment;

39\. prohibition on duplicate shared enrichment purchases because an asset appears in ChatGPT;

40\. provenance separation of observed, deterministic, semantic-classified, and inferred/hypothesized signals;

41\. Analysis Specification Contract governance for every research-used ChatGPT-specific signal;

42\. prohibition on automatically promoting candidate signals into ChatGPT recommendation/ranking factors; and

43\. prohibition of a universal ChatGPT Optimization Score.

Decision Log Update

Decision 12 LOCKED

\- Locked ChatGPT-specific process signals while preserving the parent shared-signal warehouse as the only shared truth layer.

\- Locked signal-stage, temporal-role, observability, and provenance semantics.

\- Locked Search/fanout/retrieval/source/destination/rationale process signals without causal overclaiming.

\- Locked generic-to-branded fanout emergence and retrieval-to-recommendation funnel analysis.

\- Locked first-party/third-party and independent-source distinctions.

\- Locked replicate-level retrieval/source/process stability as separate from recommendation stability.

\- Locked semantic-relation reuse of shared embeddings and progressive source enrichment.

\- Locked model-quality outcomes including hallucination, resolution, source-support, and identity mismatches.

\- Locked Analysis Specification Contract governance, no automatic factor promotion, and no ChatGPT Optimization Score.

&nbsp;

LOCKED Decision 13 — Statistical Analysis Contracts

Status: LOCKED

Foundational rule

No analysis may produce a research finding, strategy-eligible conclusion, or causal/predictive claim merely because variables can be joined in the warehouse. Every formal analysis MUST execute under a versioned parent-platform Analysis Specification Contract that explicitly defines the research question, estimand, population, outcome, exposure, timing, variable roles, dependence structure, missingness, statistical method, validation plan, and strongest permissible interpretation before the result is promoted beyond exploratory status.

Decision 13 extends the parent Analysis Specification Contract for ChatGPT-specific analysis. It MUST NOT create a parallel statistical-governance system, evidence hierarchy, finding registry, or independent research truth.

Contract as the unit of scientific analysis

A raw SQL query, notebook, dashboard filter, regression run, correlation table, LLM-generated observation, or exploratory visualization is not by itself a formal research analysis.

Every formal analysis receives a versioned \`analysis\_spec\_id\` and follows the conceptual path:

\`research question → Analysis Specification Contract → eligible dataset/view → deterministic analysis → diagnostics → statistical output → validation/replication → finding registry\`

The contract governs which data may enter, which variables may play which analytical roles, which statistical methods are scientifically eligible, and what interpretation the completed analysis is permitted to support.

Required research-question definition

Every Analysis Specification Contract MUST define, as applicable:

\- \`research\_question\` — the exact question being answered;

\- \`analysis\_goal\` — descriptive, associational/explanatory, predictive, quasi-experimental/causal, randomized/intervention, or another explicitly defined class;

\- \`primary\_outcome\` — the exact outcome being studied;

\- \`estimand\` — the quantity the analysis is intended to estimate;

\- \`population\_of\_inference\` — the population to which the result may legitimately apply;

\- \`conditioning\_population\` — the upstream outcome-funnel state, where applicable;

\- \`exposure\_of\_interest\` — the signal, treatment, or state being studied;

\- \`unit\_of\_analysis\` — for example replicate, business, business-wave, condition-wave, URL, domain, source, claim, or transition;

\- \`time\_basis\` — cross-sectional same-wave, lagged, longitudinal, event-based, intervention-based, or another defined temporal design;

\- \`primary\_hypothesis\`, where a confirmatory hypothesis exists; and

\- the planned alternative/specification family or sensitivity family where relevant.

An implicit or ambiguous denominator is a contract failure.

The following are distinct estimands and MUST NOT be casually combined:

\- probability a market/service-eligible business is surfaced;

\- probability a surfaced business is recommended;

\- probability a recommended business becomes a top choice;

\- probability a visible business receives a linked mention; and

\- probability a linked business receives an own-site destination.

Population and eligibility contract

Every analysis MUST explicitly define the analytical population and inclusion/exclusion rules, including as applicable:

\- industry/service concept;

\- research market;

\- canonical service/query intent;

\- prompt family and prompt version;

\- research wave/window;

\- ChatGPT product/methodology regime;

\- canonical entity/asset grain;

\- resolution requirements;

\- required surface observations;

\- query/service-intent alignment requirements;

\- temporal-alignment rule;

\- signal-freshness limits;

\- geographic/service eligibility;

\- control eligibility;

\- structural-break/comparability rules; and

\- other required inclusion/exclusion criteria.

Every generated analysis population should preserve its inclusion funnel, analytical denominator, exclusion counts, and exclusion reasons. A canonical join alone does not establish scientific eligibility.

Variable-role contract

Every variable used in a formal model or control-selection process MUST have an explicit role where applicable. Supported conceptual roles include:

\- \`outcome\`;

\- \`exposure\_of\_interest\`;

\- \`pre\_exposure\_confounder\`;

\- \`matching\_variable\`;

\- \`stratification\_variable\`;

\- \`mediator\_candidate\`;

\- \`collider\_candidate\`;

\- \`effect\_modifier\`;

\- \`descriptive\_only\`;

\- \`nuisance\_variable\`;

\- \`regime\_variable\`;

\- \`post\_outcome\_variable\`; and

\- \`unknown\_role\`.

Availability in the warehouse is never sufficient justification for statistical adjustment. Potential mediators, colliders, post-outcome variables, and variables of unresolved role MUST NOT be automatically added to an adjustment set merely because they exist.

Signal stage and temporal ordering

Every research-used ChatGPT-specific variable inherits Decision 12's process-stage and temporal-role semantics.

The contract MUST preserve both the signal's process stage and its temporal/process relation to the target outcome, including concepts such as \`pre\_prompt\`, \`prompt\_treatment\`, \`search\_invocation\`, \`fanout\`, \`retrieval\`, \`evidence\`, \`response\`, \`destination\`, \`post\_response\`, \`historical\_lag\`, and \`product\_regime\`, together with relations such as prior, same-process-before-outcome where genuinely observable, contemporaneous, downstream, post-outcome, or ordering unknown.

A same-response or downstream variable may be analyzed as a process association, mediator candidate, outcome, conditioning state, or descriptive signal, but MUST NOT be silently relabeled as an antecedent recommendation predictor.

Cross-surface variables must be exact

Cross-surface analyses MUST use explicitly defined surface-qualified metrics rather than generic variables whose meaning changes across analyses.

Generic labels such as \`maps\_rank\`, \`organic\_visibility\`, \`aio\_visibility\`, or \`social\_strength\` are not scientifically sufficient unless the Analysis Specification Contract resolves them to an exact approved measurement, method, condition, effective time, and freshness rule.

For Maps, for example, the contract must identify whether the analysis uses an explicitly identified coordinate rank, center-point rank, Top-3 coverage, Top-10 coverage, DAVS, Effective Ranking Radius, a distance-band outcome, or another approved Maps metric.

Control-selection sub-contract

Decision 10 is inherited in full.

When a design uses controls, the Analysis Specification Contract MUST identify, as applicable:

\`case definition → control universe → risk set → eligibility → matching/weighting/adjustment strategy → variables included → variables intentionally excluded → common-support rule → diagnostics\`

The contract should explicitly preserve \`variables\_intentionally\_not\_matched\_or\_adjusted\` or equivalent rationale so that the exposure of interest or a plausible mediator is not accidentally matched/adjusted away.

\`no\_acceptable\_control\` is a valid analytical state. The system MUST NOT loosen the scientific design merely to manufacture a control or preserve sample size.

Replicate handling

The three permanent ChatGPT replicates are independent fresh contexts under one controlled prompt condition. They are not three independent businesses and are not persistent paired subjects across weeks.

Every contract MUST state its replicate representation, such as:

\- \`raw\_replicate\`;

\- \`wave\_count\`;

\- \`wave\_frequency\`;

\- \`thresholded\_wave\_state\`; or

\- another explicitly defined representation.

Raw replicate-level, wave-count/frequency, and thresholded-state analyses are all potentially legitimate, but they estimate different quantities. Thresholding MUST NOT be selected merely because it makes statistical analysis easier.

Replicate number 1 in one wave MUST NOT be automatically paired with replicate number 1 in another wave.

Dependence and pseudo-replication

Analyses MUST account for relevant dependence structures rather than treating every warehouse row as an independent observation.

Potential dependence includes:

\- replicates within prompt condition/wave;

\- repeated observations of the same business across waves;

\- the same business across prompt families or related conditions;

\- multiple businesses within a market;

\- industry-level clustering;

\- reused controls;

\- repeated domains, URLs, publishers, and sources; and

\- product/methodology regimes affecting blocks of observations.

Eligible statistical approaches may include clustered uncertainty estimates, mixed/hierarchical models, generalized estimating equations, repeated-measures models, fixed effects, entity effects, market/industry effects, or other methods appropriate to the estimand.

Decision 13 does NOT lock one universal dependence model. It locks the requirement that correlated rows MUST NOT be treated as independent merely because they occupy separate database records.

Outcome scale determines eligible statistical families

The statistical method MUST respect the measurement scale and structure of the target outcome.

Potential outcome classes and eligible families include, depending on the estimand and assumptions:

\- binary outcomes such as visible, recommended, top choice, linked, own-site linked, or citation-supported → appropriate binary/binomial methods;

\- replicate-positive counts/frequencies such as 0/3 through 3/3 → binomial or other suitable count/proportion methods where justified;

\- ordinal outcomes such as recommendation strength → ordinal models or ordinal/nonparametric methods;

\- count outcomes such as fanout-query count or source count → appropriate count models;

\- position/rank outcomes → rank/ordinal/conditional methods that respect the exact position definition;

\- continuous outcomes → appropriate continuous-outcome methods when assumptions support them;

\- set outcomes such as recommendation/source overlap → set metrics plus appropriate uncertainty/modeling rather than treating them as generic rank variables;

\- transition/multi-state outcomes → transition, multi-state, or event-history approaches;

\- time-to-event outcomes → survival/event-history approaches; and

\- repeated longitudinal outcomes → panel, hierarchical, GEE, fixed-effects, or other suitable longitudinal methods.

These are eligible method families, not universal defaults.

Recommendation strength remains ordinal. The numeric codes 0–4 MUST NOT be averaged or interpreted as interval-scale effect magnitudes merely for convenience.

Missingness and observability contract

Missing and unobservable states MUST remain distinct from observed negatives. Analytical states may include, as applicable:

\- \`observed\_true\`;

\- \`observed\_false\`;

\- \`not\_observable\`;

\- \`missing\_collection\`;

\- \`structurally\_unavailable\`;

\- \`stale\`; and

\- \`ineligible\`.

Every contract MUST define its denominator rule, missingness treatment, complete-case rule where relevant, imputation policy, stale-signal treatment, and sensitivity analysis where appropriate.

Unobserved ChatGPT outcomes MUST NOT be imputed to false or zero.

Imputation is not a generic repair mechanism for poor observability. Covariate imputation may be scientifically appropriate under an explicitly justified design; outcome imputation for unobservable recommendation behavior should be exceptional and sensitivity-only by default unless stronger methodology justifies it.

Temporal-lag contract

Every time-varying exposure or covariate used as historical evidence MUST have an explicit temporal specification, including where applicable:

\- \`effective\_time\`;

\- \`measurement\_time\`;

\- \`outcome\_time\`;

\- \`lag\_definition\`;

\- \`freshness\_window\`; and

\- \`allowable\_overlap\`.

The platform MUST support parameterized lags such as t-1, t-2, t-4, configurable N-wave lags, rolling prior-N-wave windows, or latest valid pre-outcome observation where scientifically appropriate.

No one lag is declared universally correct.

For confirmatory analyses, the primary lag should be frozen before validation outcomes are examined.

Structural breaks and product regimes

Every Analysis Specification Contract MUST state how prompt-version, product/model, Search/retrieval, collector, session, resolution, schema, or methodology changes affect comparability.

Permitted treatments may include restricting the analysis to one regime, estimating separate regimes, performing an explicit bridge/calibration analysis, or applying an adjustment only where scientifically justified.

Adding a product-regime indicator to a model does not automatically make fundamentally incomparable periods scientifically comparable.

If no defensible bridge exists, the observations remain separate regimes.

Analysis interpretation classes

Every contract MUST declare the strongest intended interpretation before findings are promoted.

Descriptive analyses describe observed distributions, frequencies, overlaps, transitions, or other measured states without causal claims.

Associational/explanatory analyses estimate relationships under a declared population, conditioning state, timing structure, and adjustment strategy. They remain associational unless a stronger design supports stronger interpretation.

Predictive analyses ask whether variables known at a defined prediction time improve prediction of a future or otherwise explicitly defined outcome. Predictive coefficients, feature importance, SHAP values, permutation importance, or similar model diagnostics do NOT establish recommendation/ranking factors or causal mechanisms.

Quasi-experimental or causal analyses require a defensible identification strategy and assumptions appropriate to the design. Regression adjustment by itself does NOT elevate an observational association into a causal finding.

Decision 15 will govern intervention mechanics, but Decision 13 governs the claims all analytical designs are permitted to make.

Predictive-model governance

Every predictive analysis MUST define its prediction target, prediction timestamp, feature-availability cutoff, intended generalization population, validation design, and leakage safeguards.

All features must be observable at or before the prediction time used by the estimand.

Train/validation/test separation MUST respect temporal, entity, market, and other relevant dependence. A random row split may be invalid when repeated observations of the same business, condition, URL, source, or time regime occur across both training and evaluation data.

Validation may therefore hold out businesses, later waves, markets, industries, prompt conditions, or another scientifically appropriate unit depending on the intended generalization claim.

A model that predicts new observations for businesses seen during training answers a different question from a model intended to generalize to unseen businesses. The contract MUST preserve that distinction.

Multiple-testing governance

The platform may test many signals, outcomes, markets, industries, prompt families, lags, transition definitions, thresholds, interactions, and subgroups. Decision 13 MUST prevent selective significance reporting and indiscriminate significance fishing.

Every formal analysis should distinguish, as applicable:

1\. a primary pre-specified hypothesis family;

2\. an exploratory family in which the executed search space/specifications remain logged and clearly exploratory; and

3\. the declared multiplicity treatment.

Eligible multiple-testing approaches may include false-discovery-rate control, family-wise procedures, hierarchical testing, shrinkage, or another method appropriate to the analysis. No one universal correction method is locked.

An LLM MUST NOT search thousands of variable combinations and report only statistically favorable ones.

Analysis Search Ledger

Formal research should preserve an \`analysis\_search\_ledger\` or equivalent record of meaningful specifications actually run, including where applicable:

\- primary specification;

\- alternate model specifications;

\- alternate lags;

\- subgroup analyses;

\- interaction tests;

\- sensitivity variants;

\- failed analyses;

\- null results; and

\- specification amendments.

The ledger does not need to store every analyst keystroke. Its purpose is to prevent a process in which many material specifications are tried and only the favorable one survives in the research record.

Internal specification freeze

Any analysis intended for confirmatory validation SHOULD create an immutable/versioned specification freeze before the validation outcome is examined.

At minimum, freeze as applicable:

\- primary hypothesis;

\- primary outcome;

\- population;

\- exposure;

\- primary lag;

\- core covariate/control strategy;

\- statistical model family;

\- primary effect measure;

\- multiple-testing family; and

\- validation population/design.

An external academic preregistration is not required by Decision 13\. The platform uses an internal immutable/versioned specification freeze to limit researcher degrees of freedom.

If a legitimate change is required after freeze, create an amendment preserving what changed, why, when, whether validation outcomes had already been inspected, and the prior specification version. The old version remains immutable.

Discovery, validation, and replication

Discovery, validation, and replication remain separate evidence stages.

Discovery generates candidate relationships and may use broad exploratory analysis, provided the resulting relationships remain explicitly discovery-stage evidence.

Validation tests a pre-specified/frozen relationship on an appropriate independent temporal, population, entity, market, industry, prompt-condition, or other holdout. A hypothesis MUST NOT be retuned to the validation outcome and still be described as a clean validation.

Replication tests whether a validated relationship appears again under additional scientifically relevant markets, industries, future periods, prompt families, service concepts, product regimes, or later interventions.

The replication requirement must match the population of inference. A narrowly scoped claim does not require irrelevant populations, while a purportedly universal local-commercial rule requires broader replication support.

Effect magnitude and practical relevance

Statistical significance alone MUST NOT create a finding-registry or strategy recommendation.

Inferential results should preserve an effect measure appropriate to the estimand, such as:

\- risk difference;

\- relative risk;

\- odds ratio;

\- predicted probability difference;

\- marginal effect;

\- ordinal effect;

\- rate ratio;

\- slope;

\- transition difference; or

\- another scientifically appropriate magnitude.

Where useful, absolute probability-scale effects should be reported alongside model-native measures because they are often more interpretable for later Client Mode use.

Practical magnitude, uncertainty, applicability, heterogeneity, and validation status matter in addition to statistical significance.

Uncertainty reporting

Inferential findings MUST report appropriate uncertainty rather than point estimates alone where the statistical design supports uncertainty estimation.

All coefficients, sample sizes, p-values, confidence/credible intervals, standard errors, effect sizes, and other quantitative statistical outputs MUST originate from reproducible deterministic computation.

LLMs may explain structured statistical outputs but MUST NOT manufacture or interpolate missing statistical values.

Heterogeneity

Pooled averages MUST NOT silently become universal rules.

The Analysis Specification Contract should identify scientifically plausible effect modifiers where relevant, including industry, market, prompt family, service intent, SAB/storefront, franchise/independent, product regime, and time period.

Eligible approaches may include stratified estimation, interaction terms, hierarchical partial pooling, or other appropriate methods. Decision 13 does not require every subgroup analysis in every research question.

Subgroup findings require their own uncertainty, coverage, and applicability interpretation.

Interaction governance

Confirmatory interaction terms should be pre-specified when scientifically motivated. Candidate examples include reviews × Maps visibility, brand demand × Organic visibility, first-party retrieval × domain strength, and Search invocation × prompt family.

Exploratory interaction search is permitted but remains exploratory evidence. The system MUST NOT indiscriminately generate combinatorial two-way, three-way, and higher-order interactions and promote whichever are significant.

For nonlinear models, interpretation should use appropriate predicted/marginal effects where useful rather than assuming that a raw interaction coefficient alone communicates the substantive effect.

Mediator and collider governance

Decision 10's mediator/collider safeguards remain in force.

Adjustment sets MUST be justified from the estimand, temporal ordering, and plausible causal/process structure rather than automatically generated from every available warehouse signal.

A variable such as Maps visibility, Organic visibility, retrieval, citation, or another surface/process signal may be a confounder in one research question and a mediator, collider candidate, outcome, or effect modifier in another.

The contract MUST preserve that analytical-role reasoning.

Negative controls and falsification

The analysis framework should support scientifically meaningful:

\- negative-control exposures;

\- negative-control outcomes;

\- placebo timing/lag tests;

\- future-exposure leakage tests;

\- pre-trend checks; and

\- other falsification tests.

Negative controls are not required as meaningless checklist items. They should be used when the estimand/design makes them informative.

Sensitivity specifications

The primary specification MUST remain distinguishable from sensitivity variants.

Scientifically useful sensitivity analyses may test:

\- inclusion of \`probable\_match\` identities;

\- alternate eligibility definitions;

\- alternate cross-surface alignment windows;

\- signal-freshness limits;

\- lag choices;

\- transition thresholds;

\- control-selection methods;

\- structural-break exclusions;

\- missing-data handling; and

\- alternate statistical model specifications.

Sensitivity outputs should be reported as a family rather than cherry-picking whichever variant is most favorable. A field such as \`primary\_specification \= true/false\` or equivalent should identify the primary specification and link sensitivity variants to it.

Automated contract preflight

The platform SHOULD support deterministic contract validation before a formal analysis executes.

Examples of preflight BLOCK conditions include:

\- denominator or conditioning population undefined;

\- ordinal recommendation strength treated as continuous without explicit validated justification;

\- exposure of interest also used as a matching criterion in a way that removes the target contrast;

\- response-stage/post-outcome variable incorrectly labeled as an antecedent predictor;

\- replicate numbers pseudo-paired across waves without an explicit paired design;

\- generic cross-surface metric such as \`maps\_rank\` used without exact definition;

\- confirmatory analysis lacking the required frozen validation specification;

\- discovery and validation populations overlapping contrary to the declared design; or

\- a structural break silently crossed without a comparability rule.

Examples of WARN conditions include probable matches entering a primary population, weak common support, or subgroup estimates with insufficient effective information.

Possible preflight states include \`analysis\_contract\_valid\`, \`analysis\_contract\_blocked\`, \`exploratory\_only\`, \`sensitivity\_only\`, and \`confirmatory\_eligible\`.

These are validation states under the parent Analysis Specification Contract, not a separate ChatGPT research-truth system.

Reproducibility package

Every executed formal analysis MUST preserve enough provenance to reconstruct the analysis. Conceptually this includes, where applicable:

\- \`analysis\_spec\_id\` and version;

\- \`specification\_freeze\_id\`;

\- dataset ID/version/hash;

\- canonical-graph/entity-resolution version;

\- signal-definition versions;

\- control-selection run ID;

\- transition-definition ID/version;

\- intent-alignment version;

\- temporal-alignment rule;

\- product/methodology regime;

\- statistical model specification;

\- code/commit version;

\- random seed where relevant;

\- material software/library versions;

\- execution timestamp;

\- Analysis Search Ledger reference; and

\- output artifact IDs.

Exact database implementation is deferred to Decision 18\. Decision 13 locks the reproducibility requirement, not one physical schema.

Finding-registry eligibility

Decision 13 MUST NOT create a child-only evidence hierarchy. The shared parent finding registry remains authoritative.

A completed analysis should state its \`maximum\_permissible\_evidence\_class\` or equivalent design-based ceiling together with actual discovery, validation, and replication status.

A finding submitted to the shared registry should preserve at least:

\- exact population and population of inference;

\- estimand;

\- outcome;

\- exposure;

\- conditioning population;

\- design/model;

\- effect magnitude;

\- uncertainty;

\- discovery provenance;

\- validation status;

\- replication status;

\- heterogeneity/applicability;

\- applicable product/methodology regime; and

\- limitations.

The parent governance determines the final evidence classification. A validated finding from another surface does not automatically confer that evidence status on a new ChatGPT relationship.

Strategy eligibility is stricter than finding eligibility

A scientifically valid or interesting finding is not automatically an actionable client recommendation.

\`finding\_registry\_eligible\` and \`strategy\_eligible\` MUST remain separate concepts.

Decision 14 will govern how Client Mode consumes shared findings, but Decision 13 requires enough evidence metadata to allow Client Mode to distinguish TEST, MONITOR, LEAVE ALONE, \`insufficient\_evidence\`, and \`ineligible\` without manufacturing certainty.

LLM role

LLMs MAY:

\- propose hypotheses;

\- propose candidate Analysis Specification Contracts for analyst review;

\- classify semantic signals with versioned provenance;

\- explain frozen methodologies;

\- interpret and summarize deterministic statistical outputs;

\- identify heterogeneity or unusual patterns for analyst review;

\- draft research narratives; and

\- suggest follow-up validation or intervention tests.

LLMs MUST NOT:

\- modify a frozen primary specification after seeing results without a logged amendment;

\- suppress unfavorable, null, or failed analyses from the required research record;

\- select the most favorable p-value from a specification search and present it as the pre-specified result;

\- invent sample sizes, coefficients, effect sizes, p-values, intervals, model output, or diagnostics;

\- label an association causal beyond the design's permissible interpretation;

\- promote predictive feature importance, SHAP values, or rationale/source frequency into recommendation-factor proof; or

\- override the Analysis Specification Contract.

All quantitative statistics originate from reproducible deterministic computation.

Illustrative application — reviews and recommendation

A question such as \`Are higher pre-outcome review counts associated with recommendation among businesses already surfaced by ChatGPT?\` conditions on surfaced businesses rather than all eligible businesses.

\`recommended\` is a binary outcome. Review count is the exposure of interest and MUST NOT be matched away. Review data must be time-appropriate at or before the ChatGPT outcome. Repeated observations of the same business/condition must be modeled appropriately.

The resulting interpretation is an association with recommendation conditional on surfacing, not proof that reviews are a ChatGPT ranking/recommendation factor.

Illustrative application — first-party retrieval and own-site destination

A question such as \`Among linked recommended businesses, is observable first-party retrieval associated with selection of an own-site destination?\` studies a ChatGPT process relationship.

Where collection provenance genuinely shows retrieval before destination selection, first-party retrieval may be classified as \`same\_process\_before\_outcome\`. That establishes observable process order, not by itself causal mechanism.

A causal claim that increasing retrieval causes own-site linking would require stronger evidence, potentially through Decision 15 intervention methodology.

Decision 13 summary

Decision 13 therefore locks:

1\. a versioned parent-platform Analysis Specification Contract for every formal research analysis;

2\. explicit research question, estimand, denominator, population, conditioning state, outcome, exposure, unit, and evidence goal;

3\. explicit variable roles and ChatGPT process/temporal roles;

4\. exact, surface-qualified, time-aligned cross-surface metric definitions;

5\. full inheritance of Decision 10 control-selection governance;

6\. declared replicate representation at raw-replicate, wave-count/frequency, threshold-state, or another explicit level;

7\. prohibition on treating replicate numbers as longitudinal identities;

8\. explicit handling of repeated measures, clustering, control reuse, and other dependence/pseudo-replication;

9\. statistical methods appropriate to the outcome's measurement scale;

10\. no universal ChatGPT statistical model or ranking/recommendation-factor model;

11\. missing/unobservable states preserved rather than silently converted to zero;

12\. explicit effective times, freshness, lag, overlap, and temporal ordering;

13\. structural breaks/product regimes handled explicitly rather than silently pooled;

14\. separate descriptive, associational, predictive, quasi-experimental, and intervention evidence tracks with different permissible claims;

15\. leakage-aware out-of-sample predictive validation without causal/factor promotion;

16\. explicit multiple-testing families and discovery governance;

17\. an Analysis Search Ledger for meaningful executed specification searches;

18\. internal immutable/versioned specification freeze before confirmatory validation outcomes are examined;

19\. discovery, validation, and replication as distinct stages;

20\. effect magnitude, practical relevance, and uncertainty rather than significance alone;

21\. explicit heterogeneity/applicability rather than universalizing pooled averages;

22\. pre-specified confirmatory interactions and exploratory labeling for interaction searches;

23\. explicit mediator/collider reasoning before adjustment;

24\. support for scientifically meaningful negative controls, falsification, and sensitivity analysis;

25\. deterministic contract preflight capable of blocking scientifically invalid analyses before execution;

26\. reproducible versioned specification, dataset, code, methodology, and output provenance;

27\. finding-registry eligibility separate from strategy eligibility;

28\. no ChatGPT-only evidence hierarchy or finding registry; the parent shared registry remains authoritative;

29\. LLM interpretation of deterministic statistics without manufactured or selectively curated quantitative findings; and

30\. Decision 13 does not alter the governing current 10-condition permanent ChatGPT prompt panel or surface-specific query alignment contract.

Decision Log Update

Decision 13 LOCKED

\- Locked statistical governance around a versioned Analysis Specification Contract rather than one universal model.

\- Locked explicit estimands, denominators, populations, variable roles, timing, missingness, dependence, and outcome-scale requirements.

\- Locked discovery/validation/replication separation, internal specification freeze, multiple-testing governance, and the Analysis Search Ledger.

\- Locked effect-magnitude, uncertainty, heterogeneity, robustness, falsification, and reproducibility requirements.

\- Locked predictive-versus-causal separation and no automatic ranking/recommendation-factor promotion.

\- Locked deterministic contract preflight and strict LLM prohibition on manufactured/selectively curated statistics.

\- Preserved the current fixed 10-condition ChatGPT panel and surface-specific query-alignment semantics without reopening historical query-count alternatives.

# **LOCKED Decision 14 — Client Mode**

Status: LOCKED

&nbsp;

## **Foundational rule**

&nbsp;

ChatGPT Client Mode is an evidence-constrained diagnostic and decision system, not a ranking-factor translator. It may identify measured client conditions, reproducible competitive differences, applicable registered research findings, and scientifically eligible actions, but no competitor difference, model-stated rationale, correlation, predictive feature importance, retrieval pattern, citation pattern, destination pattern, or cross-surface relationship may become an optimization instruction without passing explicit applicability and action-eligibility gates.

&nbsp;

The required conceptual chain is:

&nbsp;

\`measured client condition → diagnostic state → reproducible gap/comparison → registered finding → finding applicability → actionability assessment → permitted action ceiling → Client Mode decision → measurement/intervention plan\`

&nbsp;

The system MUST NOT create shortcuts such as \`competitor has X → client lacks X → do X\` or \`X predicts recommendation → increasing X will increase recommendation\`.

&nbsp;

## **Research Mode and Client Mode remain separate**

&nbsp;

Client Mode MUST NOT alter the permanent Research Mode panel merely to fit an individual client.

&nbsp;

Client measurement supports two distinct lanes:

&nbsp;

1\. Research-aligned diagnostic lane — client observations that are as compatible as possible with permanent Research Mode conditions, including canonical service intent, market, prompt family/version, fresh-context methodology, product/methodology regime, and replicate methodology. This lane has the strongest eligibility for direct Research Finding applicability.

2\. Client-operational diagnostic lane — additional commercially useful client conditions such as other service lines, neighborhoods, markets, problem intents, comparison intents, commercial modifiers, and client-specific reporting conditions. These observations are operationally valuable but MUST be mapped explicitly to Research Findings and MUST NOT inherit exact-finding applicability merely because they concern the same business or broad industry.

&nbsp;

Decision 14 does not change the locked 10-condition permanent ChatGPT Research Mode panel. Client Mode may measure additional client intents when required for a client-specific question, but those observations do not alter the permanent Research Mode denominator.

&nbsp;

## **Outcome-funnel-conditioned diagnosis**

&nbsp;

Client Mode MUST preserve the separate ChatGPT outcome families and condition comparisons on the correct upstream population when that matches the diagnostic question.

&nbsp;

Examples include:

\- surfacing probability among independently eligible businesses;

\- recommendation probability among surfaced businesses when studying recommendation conditional on surfacing;

\- top-choice probability among recommended businesses;

\- linked-mention probability among the appropriate visible/recommended population;

\- own-site destination selection among the appropriate linked/visible population;

\- destination-type selection among businesses for which destination selection is observable;

\- citation/evidence support among claims/businesses for which support is observable; and

\- first-party retrieval or retrieval-to-destination states only where Search/retrieval observability is valid.

&nbsp;

A client that is surfaced but not recommended should primarily be diagnosed against scientifically appropriate surfaced businesses that become recommended, not against every market business. A client that is recommended but not top choice should primarily be compared with recommended businesses that become top choices when that is the target estimand.

&nbsp;

## **No ChatGPT Optimization Score**

&nbsp;

Client Mode MUST preserve a multidimensional outcome and signal profile rather than collapsing visibility, recommendation, top choice, links, destinations, retrieval, sources, Maps, Organic, AIO, GBP, reviews, links, brand demand, social, citations, or other shared signals into a universal ChatGPT Optimization Score, AI Authority Score, or equivalent 0–100 index.

&nbsp;

Operational prioritization may exist later, but it MUST remain explicitly operational rather than being represented as scientific factor importance.

&nbsp;

## **Versioned Client Diagnostic Snapshot**

&nbsp;

Every formal Client Mode run MUST create an immutable/versioned Client Diagnostic Snapshot or equivalent decision-time evidence object.

&nbsp;

The snapshot should bind, as applicable:

\- client/canonical entity and resolution version;

\- diagnostic execution timestamp and evidence cutoff;

\- client measurement period;

\- ChatGPT observations and controlled conditions;

\- prompt/service-intent versions;

\- shared-signal values and effective times;

\- cross-surface observations and alignment rules;

\- comparator population and comparator-selection version;

\- shared Research Finding Registry version/state;

\- product/methodology regime;

\- freshness/staleness policy;

\- missingness/observability state;

\- Client Mode rule/methodology version; and

\- code/build version.

&nbsp;

Later research MUST NOT be retroactively presented as evidence that existed when an earlier client recommendation was produced. Materially new evidence creates a new diagnostic version rather than rewriting the earlier snapshot.

&nbsp;

## **Observation, gap, and Research Finding are distinct objects**

&nbsp;

Client Mode MUST keep separate:

&nbsp;

\- Client Observation — a measured fact about the client under defined conditions.

\- Competitive Gap — a deterministic comparison between the client and a reproducible comparator population.

\- Research Finding — a registered analytical result with defined population, estimand, exposure/outcome, effect or predictive measure, uncertainty where applicable, validation/replication state, limitations, and strategy eligibility.

&nbsp;

A competitive gap does not inherit the meaning of a Research Finding merely because the variables have the same label. A Research Finding does not automatically apply to an individual client merely because a matching gap exists.

&nbsp;

## **ChatGPT-specific Competitive Gap families**

&nbsp;

Client Mode reuses the shared parent Competitive Gap/diagnostic architecture rather than creating a parallel truth system. ChatGPT-specific gap types may include, where measurable:

\- surfacing gap;

\- recommendation-conversion gap;

\- top-choice gap;

\- linked-mention gap;

\- first-party destination gap;

\- destination-page gap;

\- first-party retrieval gap;

\- support/corroboration gap;

\- source-type gap;

\- brand-query-emergence gap; and

\- cross-surface discordance gap.

&nbsp;

Process-stage or downstream gaps such as branded fanout, citation exposure, rationale frequency, or destination behavior MUST NOT automatically become antecedent optimization instructions. Their Decision 12 process-stage and temporal role remains operative.

&nbsp;

## **Comparator governance**

&nbsp;

Client Mode MUST NOT default to \`copy whoever ChatGPT recommends\`.

&nbsp;

Depending on the question, valid comparator populations may include:

\- response-conditioned winners;

\- persistent recommendation winners;

\- persistent top choices;

\- linked versus unlinked recommendations;

\- first-party-linked versus third-party-linked recommendations;

\- matched eligible non-surfaced businesses;

\- cross-surface discordant businesses;

\- newly emerging winners;

\- the client's own historical baseline; and

\- finding-specific matched or weighted controls produced under Decision 10/13.

&nbsp;

Winner cohorts are descriptive comparator populations unless a registered Research Finding gives the observed difference stronger analytical meaning.

&nbsp;

## **Mechanical finding retrieval before generative interpretation**

&nbsp;

The LLM MUST NOT search raw warehouse variables and decide from intuition which signals \`matter\` for a client.

&nbsp;

Client Mode first queries the shared Research Finding Registry using structured eligibility criteria. Applicability matching should consider, as relevant:

\- exact ChatGPT outcome;

\- conditioning population;

\- industry/vertical;

\- service/query intent;

\- prompt family/version;

\- market/population;

\- SAB/storefront/franchise/multi-location or other business type;

\- product/methodology regime;

\- signal definition/version;

\- temporal/process role;

\- data window/freshness;

\- discovery/validation/replication status; and

\- whether the client lies within the finding's observed/common-support population.

&nbsp;

A scientifically strong finding can still be a poor or ineligible recommendation for a particular client.

&nbsp;

## **Multidimensional applicability**

&nbsp;

Client applicability MUST NOT be represented by an unexplained universal percentage or single magic score.

&nbsp;

The system should preserve dimension-specific applicability states such as exact, related, extrapolated, incompatible, unknown, or other controlled values for the relevant dimensions. A deterministic/versioned rule may then derive a controlled overall applicability class such as:

\- \`strongly\_applicable\`;

\- \`partially\_applicable\`;

\- \`extrapolative\`; or

\- \`incompatible\`.

&nbsp;

The LLM may explain an applicability result but MUST NOT upgrade it through intuition.

&nbsp;

## **Research-sample-overlap leakage guard**

&nbsp;

Client Mode MUST identify whether the same canonical client entity materially contributed to the discovery, validation, or replication sample supporting a Research Finding.

&nbsp;

The architecture should support states such as:

\- \`none\`;

\- \`discovery\_sample\_overlap\`;

\- \`validation\_sample\_overlap\`;

\- \`replication\_sample\_overlap\`; and

\- \`unknown\`.

&nbsp;

Where client overlap would make the evidence non-independent for the intended interpretation, appropriate out-of-sample, leave-entity-out, or otherwise independent support is required before the finding is represented as independently validated evidence for that client.

&nbsp;

## **Epistemic ladder for \`why\` explanations**

&nbsp;

Every Client Mode explanation of why a client is or is not surfaced, recommended, top choice, linked, or selected for a destination MUST preserve the strongest evidence level actually supported.

&nbsp;

Conceptual levels are:

&nbsp;

A. Directly observed — exact measured client/product behavior.

B. Deterministic comparative fact — reproducible difference between client and comparator population.

C. Registered associational/predictive evidence — an applicable Research Finding supports a relationship but not necessarily causal change.

D. Intervention/causal evidence — a qualifying intervention or causal design supports a change claim under defined conditions.

&nbsp;

C-level evidence MUST NOT be phrased as though changing X is proven to cause Y. The system should be able to state that a difference is plausible and evidence-supported while explicitly noting that current evidence does not establish causation.

&nbsp;

## **Model-stated rationale lane**

&nbsp;

ChatGPT-stated rationales MUST remain separate from verified attributes and causal explanations.

&nbsp;

Client Mode should preserve distinct objects for:

\- stated rationale;

\- independently verified attribute;

\- source/citation support relationship;

\- registered research association; and

\- intervention/causal evidence.

&nbsp;

A rationale may be factually wrong, may rationalize an already-selected entity, may be a downstream response-stage artifact, or may align with a separately validated factor. Client Mode MUST NOT collapse these possibilities.

&nbsp;

## **Destination diagnosis**

&nbsp;

Destination selection receives its own diagnostic logic. Where observable, Client Mode should reconstruct the exposed process path:

&nbsp;

\`prompt → Search/fanout → retrieved first-party/third-party assets → citations/support → business recommendation → linked destination\`

&nbsp;

Useful observable states may include:

\- \`own\_site\_not\_observed\_in\_retrieval\`;

\- \`own\_site\_retrieved\_not\_cited\`;

\- \`own\_site\_cited\_not\_selected\_as\_destination\`;

\- \`third\_party\_source\_selected\_as\_destination\`;

\- \`own\_site\_destination\_selected\`;

\- \`different\_owned\_url\_selected\`; and

\- \`destination\_observability\_unknown\`.

&nbsp;

These states describe observable process behavior. They do not by themselves establish the causal path that produced the destination.

&nbsp;

## **First-party and third-party evidence environment**

&nbsp;

Client Mode should be able to describe the client's and competitors' evidence environments using first-party retrieval, third-party retrieval, citation/support, independent corroboration, source classes, and destination relationships.

&nbsp;

A competitor having more third-party corroboration or a different source topology is a measured diagnostic difference, not automatically an instruction to obtain more listings, citations, reviews, publisher coverage, or other third-party mentions. Such an action requires applicable Research Finding support and action eligibility.

&nbsp;

## **Cross-surface diagnostic vector**

&nbsp;

Maps, Organic, AIO, GBP, reviews, links, brand demand, content, social, citations, and other shared signals remain separate surface-qualified diagnostic dimensions.

&nbsp;

Client Mode may create Cross-Surface Diagnostic Objects describing states such as ChatGPT weak/Maps strong/Organic strong or ChatGPT recommended/AIO absent/own-site linked, but MUST NOT infer causal influence merely from concordance or discordance.

&nbsp;

No blended cross-surface authority score is authorized.

&nbsp;

## **Modifiability and evidence are separate axes**

&nbsp;

Every action-relevant signal should have an operational modifiability classification independent of evidence strength. Conceptual classes include:

\- directly modifiable;

\- indirectly influenceable;

\- structurally constrained;

\- product/process state;

\- downstream observation;

\- non-actionable; and

\- prohibited/deceptive.

&nbsp;

\`modifiable\` does not mean \`important\`, and \`predictive\` does not mean \`modifiable treatment\`.

&nbsp;

## **Recommendation eligibility gate**

&nbsp;

A Client Mode action candidate requires the following evidence chain, as applicable:

&nbsp;

\`current measured client condition \+ reproducible comparator/gap \+ strategy-eligible registered finding \+ acceptable client applicability \+ compatible temporal/process role \+ legitimate modifiable intervention target \+ no blocking contra-evidence \+ adequate freshness/observability \+ compatible product/methodology regime \+ factual/policy eligibility \+ defined outcome to measure\`

&nbsp;

If the chain fails, Client Mode MUST downgrade, monitor, leave alone, mark insufficient evidence, or mark the candidate ineligible rather than manufacture an optimization instruction.

&nbsp;

## **Client Mode decision states and action ceiling**

&nbsp;

Client Mode supports the following substantive decision states:

\- \`ineligible\` — the action/finding/client condition cannot legitimately be evaluated or implemented under the current evidence or methodology;

\- \`insufficient\_evidence\` — a condition or gap exists but evidence does not justify an operational inference;

\- \`LEAVE ALONE\` — evidence does not justify changing the current state, the gap is immaterial, or intervention risk exceeds support;

\- \`MONITOR\` — the condition is relevant but current evidence maturity, lag, uncertainty, observability, or actionability does not justify intervention;

\- \`TEST\` — evidence is sufficiently promising and applicable to justify an explicit controlled intervention; and

\- \`CHANGE\` — the exact action has sufficiently strong evidence to implement without treating the action as exploratory.

&nbsp;

\`CHANGE\` has a strict ceiling.

&nbsp;

Observational association, even when replicated, MUST NOT by itself produce \`CHANGE\`. Predictive importance MUST NOT produce \`CHANGE\`. Competitor prevalence MUST NOT produce \`CHANGE\`. Model-stated rationale frequency MUST NOT produce \`CHANGE\`. Cross-surface correlation MUST NOT produce \`CHANGE\`.

&nbsp;

A research-driven \`CHANGE\` requires qualifying intervention/quasi-experimental evidence under Decision 15 plus sufficiently strong client applicability. Independently justified factual remediation, such as correcting objectively false first-party information, may also be a \`CHANGE\` without claiming that the remediation is a proven ChatGPT ranking factor.

&nbsp;

Until Decision 15 defines qualifying intervention evidence, \`CHANGE\` remains a reserved highest action state whose research-evidence activation is not fully specified.

&nbsp;

## **Strategy-use ceiling on findings**

&nbsp;

The parent-governed shared finding record should expose a strategy-use ceiling distinct from the finding's scientific evidence class. Controlled values may include:

\- \`not\_client\_eligible\`;

\- \`diagnostic\_only\`;

\- \`monitor\_eligible\`;

\- \`test\_eligible\`; and

\- \`change\_candidate\`.

&nbsp;

This ceiling answers the strongest Client Mode use the finding is permitted to support. It MUST NOT become a new ChatGPT-only evidence hierarchy.

&nbsp;

## **Bidirectional evidence retrieval and contra-evidence**

&nbsp;

Every Client Mode Evidence Packet MUST retrieve not only findings supporting an action but also materially applicable findings that weaken, contradict, limit, supersede, or show heterogeneity in the relationship.

&nbsp;

Evidence packets should retain, where relevant:

\- supporting findings;

\- contradictory findings;

\- null findings;

\- superseded findings;

\- applicable heterogeneity;

\- limitations; and

\- evidence gaps.

&nbsp;

The LLM may summarize the balance of evidence but MUST NOT suppress inconvenient findings.

&nbsp;

## **No numerical competitor targets by default**

&nbsp;

Competitor distributions are context, not causal thresholds.

&nbsp;

A competitor median review count, referring-domain count, source count, content length, brand-demand level, or other measured value MUST NOT automatically become the client's numerical target.

&nbsp;

An exact target requires evidence supporting a dose-response, threshold, intervention target, or other scientifically justified quantity under applicable conditions. Otherwise actions remain directional or test-based.

&nbsp;

## **Predictive probability is not intervention lift**

&nbsp;

A predictive model may estimate an outcome probability under defined conditions. That does not authorize a counterfactual statement that changing one input by a specified amount will produce a specified lift.

&nbsp;

\`predictive probability ≠ intervention lift\`

&nbsp;

\`observational effect estimate ≠ expected action lift\`

&nbsp;

Numerical expected-improvement claims require a design capable of supporting that counterfactual/intervention interpretation.

&nbsp;

## **Operational prioritization**

&nbsp;

Once multiple candidates pass the eligibility gate, Client Mode may prioritize them using transparent operational dimensions such as:

\- evidence class;

\- strategy-use ceiling;

\- applicability;

\- measured gap magnitude;

\- reversibility;

\- risk;

\- cost;

\- effort;

\- measurement latency;

\- dependencies;

\- intervention-isolation potential; and

\- cross-surface side effects.

&nbsp;

Any internal prioritization score MUST be explicitly labeled operational, have a transparent/versioned formula, and MUST NOT be represented as a ranking-factor hierarchy or causal-importance score.

&nbsp;

## **Evidence-chain output contract**

&nbsp;

For each evaluated client issue, the system should expose enough structure to reconstruct the decision, including as applicable:

\- observed client condition;

\- comparator definition;

\- measured gap and distribution;

\- applicable Research Finding ID(s);

\- finding population, estimand, evidence class, effect/predictive measure, uncertainty, validation/replication, and limitations;

\- applicability dimensions and overall applicability class;

\- temporal/process status;

\- strategy-use ceiling;

\- Client Mode decision state;

\- exact intervention candidate, where eligible;

\- explanation of why a stronger action state was not permitted;

\- contra-evidence and unknowns;

\- outcome to measure; and

\- Client Diagnostic Snapshot/version.

&nbsp;

## **Human review in V1**

&nbsp;

Human review is mandatory before implementation in Client Mode V1.

&nbsp;

The system MUST preserve the machine-generated decision and a separate analyst disposition. Controlled analyst states may include:

\- \`approve\`;

\- \`reject\`;

\- \`modify\`;

\- \`defer\`; and

\- \`reorder\`.

&nbsp;

Analyst disposition, reasoning, reviewer, and timestamp should be retained. The machine recommendation remains immutable after review. An analyst override MUST NOT retroactively upgrade the evidence supporting the machine recommendation.

&nbsp;

## **Client interventions do not automatically become Research Findings**

&nbsp;

Client intervention outcomes may become valuable external/intervention evidence, but they MUST enter the research system through explicit intervention logging and Decision 13/15 analysis rather than automatically strengthening the finding that originally motivated the action.

&nbsp;

Required conceptual flow:

&nbsp;

\`client intervention → immutable intervention record → defined outcome window → Decision 13/15 analysis → validation/replication governance → shared finding registry\`

&nbsp;

Null, negative, and harmful outcomes MUST remain in the intervention record. Client Mode MUST NOT create a self-reinforcing evidence loop in which only successful recommended actions become research evidence.

&nbsp;

## **Prohibited methodological failure modes**

&nbsp;

Client Mode MUST explicitly guard against:

1\. winner imitation — competitors have X, therefore the client should obtain X;

2\. outcome-conditioning errors — comparing downstream failures against businesses outside the relevant upstream risk set;

3\. mediator/downstream optimization — treating retrieval, citations, rationales, branded fanout, destinations, or other same-process/downstream variables as antecedent factors without temporal justification;

4\. predictive-to-causal leap — predictive importance becoming a prescriptive factor;

5\. numerical-threshold folklore — competitor medians/percentiles becoming targets without threshold evidence;

6\. cross-surface causal leakage — Maps/AIO/Organic correlation becoming a claim that ChatGPT uses that surface as a factor;

7\. rationale literalism — model-stated reason becoming causal mechanism;

8\. in-sample circularity — applying evidence back to a client that materially generated it without appropriate independent support;

9\. positive-evidence retrieval bias — retrieving only findings favorable to the proposed action;

10\. historical leakage — using research unavailable at the decision-time snapshot to justify an earlier recommendation;

11\. research contamination — automatically feeding successful client actions back as proof while failures disappear;

12\. LLM target invention — creating exact quantities, thresholds, effects, or expected lifts not supported by deterministic evidence;

13\. applicability laundering — presenting a strong finding from a poorly matched population as strong client evidence;

14\. product-regime laundering — applying findings across materially incompatible ChatGPT regimes without valid bridge evidence; and

15\. actionability confusion — treating a predictive signal as a manipulable treatment merely because it is measurable or indirectly influenceable.

&nbsp;

## **Deterministic Client Mode preflight**

&nbsp;

Before an operational action state is issued, deterministic validation SHOULD check, as applicable:

\- valid observability of the client condition;

\- sufficient canonical identity/resolution;

\- defined target outcome and conditioning population;

\- reproducible comparator selection;

\- measured rather than inferred competitive gap;

\- active and strategy-eligible finding status;

\- acceptable applicability for the requested use;

\- compatible temporal/process role;

\- legitimate and genuinely modifiable action target;

\- requested action state does not exceed the finding's strategy-use ceiling;

\- materially relevant contra-evidence has been retrieved;

\- no unsupported numerical target;

\- no quantitative lift claim without intervention-grade evidence;

\- client/research-sample overlap is handled appropriately;

\- adequate freshness and product/methodology comparability; and

\- defined measurable outcome for any intervention candidate.

&nbsp;

Preflight failures may BLOCK the candidate or deterministically downgrade it to \`ineligible\`, \`insufficient\_evidence\`, \`LEAVE ALONE\`, \`MONITOR\`, or \`TEST\` as permitted. The LLM MUST NOT waive a failed gate because an action seems intuitively reasonable.

&nbsp;

## **Boundary with Decision 15**

&nbsp;

Decision 14 ends at:

&nbsp;

\`diagnosis → evidence → applicability → decision state → precise intervention candidate → measurement requirement\`

&nbsp;

Decision 15 governs intervention and experiment mechanics, including treatment assignment, control selection for interventions, pre-periods, expected lags, concurrent interventions, randomization where possible, quasi-experimental designs, stop criteria, bundles, attribution, outcome analysis, negative controls, replication, and how intervention results become research evidence.

&nbsp;

## **Decision 14 lock summary**

&nbsp;

Decision 14 therefore locks:

1\. Client Mode as an evidence-constrained diagnostic/decision system rather than a ranking-factor translator;

2\. strict measured-condition → gap → finding → applicability → actionability → decision ordering;

3\. separate research-aligned and client-operational measurement lanes;

4\. no modification of the locked permanent 10-condition ChatGPT panel;

5\. funnel-conditioned diagnostics and comparators by target outcome;

6\. no ChatGPT Optimization Score or blended cross-surface authority score;

7\. immutable/versioned Client Diagnostic Snapshots with decision-time evidence cutoffs;

8\. strict separation of Client Observation, Competitive Gap, and Research Finding;

9\. ChatGPT-specific gap families for surfacing, recommendation, top choice, linking, destination, retrieval, support/source, branded fanout, and cross-surface discordance;

10\. no default winner imitation or competitor-copying methodology;

11\. mechanical structured finding-registry retrieval before generative interpretation;

12\. multidimensional applicability rather than a magic applicability score;

13\. research-sample-overlap protection against in-sample circularity;

14\. a four-level epistemic ladder for \`why\` explanations;

15\. separation of model-stated rationales, verified attributes, source support, associations, and causal/intervention evidence;

16\. first-class destination-path and first-party/third-party evidence diagnostics without causal overclaiming;

17\. cross-surface diagnostics as vectors rather than scores;

18\. modifiability/actionability as separate from evidence strength;

19\. an explicit recommendation-eligibility chain and deterministic Client Mode preflight;

20\. \`ineligible\`, \`insufficient\_evidence\`, \`LEAVE ALONE\`, \`MONITOR\`, \`TEST\`, and reserved \`CHANGE\` decision states;

21\. a strict \`CHANGE\` ceiling requiring qualifying intervention/quasi-experimental evidence or independently justified factual remediation;

22\. parent-governed strategy-use ceilings distinct from scientific evidence class;

23\. mandatory retrieval of contra-evidence, nulls, limitations, and heterogeneity where applicable;

24\. prohibition on turning competitor distributions into numerical optimization targets without supporting threshold/dose-response evidence;

25\. prohibition on treating predictive probability or observational effects as intervention lift;

26\. operational prioritization separated from scientific factor importance;

27\. reconstructable Evidence Packet outputs;

28\. mandatory human review with immutable machine recommendation and separate analyst disposition;

29\. explicit intervention-to-research ingestion rather than automatic self-reinforcing evidence updates;

30\. explicit prohibition of the major leakage, circularity, applicability, product-regime, and causal-overclaim failure modes; and

31\. a clean boundary in which Decision 15 defines intervention/experiment mechanics and qualifying intervention evidence.

&nbsp;

## **Decision Log Update**

Decision 14 LOCKED

\- Locked a finding-registry-driven, funnel-conditioned Client Mode with explicit applicability and action ceilings.

\- Locked separate research-aligned and client-operational measurement lanes.

\- Locked Client Diagnostic Snapshots, research-sample-overlap safeguards, bidirectional evidence retrieval, and deterministic Client Mode preflight.

\- Locked \`TEST\`, \`MONITOR\`, \`LEAVE ALONE\`, \`insufficient\_evidence\`, \`ineligible\`, and reserved \`CHANGE\` semantics with a strict intervention-evidence ceiling for \`CHANGE\`.

\- Locked no numerical target/lift invention, no winner imitation, no predictive-to-causal promotion, and no universal optimization score.

\- Locked mandatory human review and explicit intervention-to-research feedback governance.

\- Preserved the current fixed 10-condition ChatGPT panel and surface-specific query-alignment semantics without reopening historical query-count alternatives.

&nbsp;

\---

&nbsp;

# **HISTORICAL DUPLICATE DRAFT — Decision 15 Interventions / Experiments**

# **Status: retained for provenance only. The consolidated numbered Decision 15 (Sections 15.1–15.22) below is the sole governing Decision 15\. If wording here differs from the consolidated version, the consolidated version governs. Do not implement this earlier drafting copy as a second intervention contract.**

# 

# 

&nbsp;

Status: LOCKED.

&nbsp;

## **Purpose and governing principle**

&nbsp;

Decision 15 defines how evidence-constrained action candidates become scientifically interpretable interventions or experiments without converting ordinary client work into causal proof. It inherits the parent platform intervention infrastructure, Decision 13 Analysis Specification Contract governance, Decision 14 strategy-use ceilings, the shared signal warehouse, and the shared Research Finding Registry. It creates no ChatGPT-specific parallel intervention truth system.

&nbsp;

The governing distinction is:

&nbsp;

Intervention \= an intentional change.

Experiment \= an intervention conducted under a design capable of estimating its effect.

&nbsp;

An intervention occurring before an outcome change does not, by itself, establish that the intervention caused the change.

&nbsp;

## **Design classes and causal ceiling**

&nbsp;

Every intervention record MUST identify its design class and the maximum causal interpretation the design can support:

&nbsp;

1\. Controlled randomized intervention — may support causal interpretation when randomization, adherence, interference, measurement, and analysis remain valid.

2\. Controlled quasi-experiment — including matched-control difference-in-differences, controlled interrupted time series, defensible natural experiments, and related designs — may support causal interpretation only when the identification assumptions and required diagnostics are credible.

3\. Uncontrolled intervention — including ordinary before/after client changes — may support temporal or descriptive evidence but is not causal evidence by itself.

4\. Ordinary operational change without a research protocol — is retained as change-history/context only unless a later valid design can use it as part of a defensible quasi-experimental analysis.

&nbsp;

A compelling temporal sequence does not upgrade an uncontrolled intervention into causal evidence.

&nbsp;

## **Legitimate intervention requirements**

&nbsp;

Before treatment begins, a confirmatory intervention protocol MUST define, as applicable:

\- treatment and treatment version;

\- treatment unit and eligible intervention population;

\- treatment start/effective date;

\- assignment mechanism;

\- primary outcome or small predeclared primary outcome family;

\- conditioning population and analytical grain;

\- pre-treatment baseline period;

\- expected lag/wash-in period;

\- primary measurement and follow-up/persistence windows;

\- control/comparator design;

\- concurrent-change policy;

\- treatment-adherence/exposure definition;

\- spillover/interference and contamination plan;

\- Analysis Specification Contract;

\- stopping rules;

\- multiple-testing family and correction where relevant; and

\- intended evidence claim and maximum permissible interpretation.

&nbsp;

The treatment MUST be the manipulation actually introduced, not a hoped-for mediator, downstream state, or outcome. For example:

\- a compliant review-solicitation process may be the treatment; achieved review count is not the assigned treatment;

\- deployment of defined structured data may be the treatment; “improved entity understanding” is not;

\- placement or correction of defined legitimate references may be the treatment; “increased authority” is not.

&nbsp;

## **Research-asset and client intervention lanes**

&nbsp;

Decision 15 authorizes two intervention lanes, both using the shared parent intervention infrastructure.

&nbsp;

Research-asset experiments are preferred when stronger control is needed over randomization, treatment isolation, rollback, timing, content, structured data, internal linking, destination-page architecture, or source/citation changes. Their primary limitation is external validity. Research-asset evidence alone may ordinarily make a treatment eligible for further client TEST use, but it does not by itself justify a general client CHANGE recommendation. Real-world/client replication is ordinarily required before general CHANGE eligibility.

&nbsp;

Client experiments provide stronger real-world relevance but often have more concurrent changes, natural review/link acquisition, campaigns, business changes, competitor responses, and implementation noise. They therefore require stronger timeline logging, adherence verification, contamination assessment, and design diagnostics. Messier implementation does not make client evidence unusable; it lowers the strength of claims the design can support when counterfactual identification is compromised.

&nbsp;

## **Eligible intervention families**

&nbsp;

Intervention families may include, where legitimate and operationally permitted:

\- website/content changes;

\- destination-page changes;

\- structured-data changes;

\- entity-consistency corrections;

\- GBP changes where legitimately editable;

\- link interventions;

\- citation/source interventions;

\- compliant review/reputation interventions;

\- social/profile/source changes;

\- first-party source-environment changes; and

\- explicitly defined cross-surface interventions.

&nbsp;

Fake reviews, fabricated citations, deceptive entity information, or other illegitimate/manipulative activity do not qualify as research interventions.

&nbsp;

## **Isolation, bundles, and component claims**

&nbsp;

An experiment SHOULD isolate one treatment when scientifically and operationally feasible. If multiple changes are deliberately applied together, the identified treatment is the bundle.

&nbsp;

A bundled treatment may support a claim about the bundle only. It MUST NOT be used to claim that any individual component caused the outcome unless the design independently identifies that component.

&nbsp;

Factorial or other component-interaction designs may be used when adequately powered and pre-specified, but are Phase 2/Experimental by default because sample-size and multiplicity requirements can grow quickly.

&nbsp;

## **Mandatory concurrent-change ledger**

&nbsp;

Every treated and comparator unit MUST have a time-aligned concurrent-change ledger covering material changes that could affect interpretation, including as applicable:

\- website and content;

\- GBP;

\- links;

\- citations;

\- reviews/reputation;

\- social/profile activity;

\- Organic visibility;

\- Maps visibility;

\- AIO visibility;

\- brand campaigns/demand-generating activity;

\- major business changes; and

\- relevant ChatGPT/product/platform or collection-method changes.

&nbsp;

Concurrent events SHOULD be classified as:

\- planned co-treatment;

\- allowed background change;

\- material contamination;

\- exogenous shock; or

\- unknown.

&nbsp;

A contaminated experiment is retained rather than discarded. Contamination may lower the experiment's evidence ceiling or make the causal estimand non-identifiable, but it does not erase the intervention record.

&nbsp;

## **Eligible experimental and quasi-experimental designs**

&nbsp;

Decision 15 does not mandate one universal design. The Analysis Specification Contract selects a design appropriate to the estimand, treatment unit, interference boundary, available controls, temporal structure, and operational constraints.

&nbsp;

### **Randomized controlled intervention**

Randomization is preferred whenever scientifically and operationally feasible. Randomization may occur at the business, location, page, service-page, market, source-asset, cluster/site, or rollout-wave level. The randomization unit MUST reflect the plausible interference boundary rather than convenience.

&nbsp;

### **Cluster randomization**

Cluster randomization SHOULD be used where treatment can spill across pages, locations, businesses, brands, websites, GBP profiles, or other shared units such that lower-level controls would be contaminated.

&nbsp;

### **Randomized staggered rollout**

Where all eligible units will ultimately receive treatment, randomized rollout timing is an encouraged design. It can create experimental variation while avoiding a permanent untreated group, provided time effects and interference are handled correctly.

&nbsp;

### **Difference-in-differences**

Difference-in-differences may be used when randomization is infeasible and a credible comparison group exists. Confirmatory use requires adequate pre-treatment history, pre-trend diagnostics, explicit intervention timing, assessment of differential shocks, and contamination/interference review. Merely fitting a DiD regression does not create causal evidence.

&nbsp;

### **Interrupted time series**

Interrupted time-series designs may be used where repeated observations before and after treatment can identify a plausible discontinuity or change in trend. Controlled ITS is preferred when a credible control series exists. Analyses SHOULD address pre-treatment trend, post-treatment level/trend, autocorrelation, seasonality where relevant, ChatGPT product/methodology changes, and concurrent interventions.

&nbsp;

### **Matched or synthetic controls**

Matched or synthetic controls may be used when they can plausibly approximate the untreated counterfactual. Decision 10 control-selection governance remains applicable; matching quality and pre-treatment fit MUST be documented.

&nbsp;

### **Natural experiments**

Natural experiments are permitted only when an explicit identification argument supports the claim that the exposure variation is plausibly exogenous for the estimand. The fact that SED did not cause the event does not itself make the event exogenous.

&nbsp;

## **Baselines, lags, wash-in, and follow-up windows**

&nbsp;

Decision 15 does not lock one universal number of pre- or post-treatment weeks.

&nbsp;

Every protocol MUST separately define:

pre-treatment baseline → treatment implementation → expected lag/wash-in → primary outcome window → persistence/follow-up window.

&nbsp;

Window adequacy depends on, as applicable:

\- baseline variance;

\- outcome frequency;

\- intervention mechanism;

\- expected indexing/retrieval lag;

\- number of experimental units;

\- clustering/dependence;

\- product/methodology stability; and

\- desired minimum detectable effect or precision.

&nbsp;

Difference-in-differences designs require sufficient pre-treatment history to evaluate pre-trends. Interrupted time-series designs require sufficient pre/post observations to estimate the intervention against underlying variation. Adequately randomized multi-unit experiments may require less historical baseline for identification, although baseline measures may improve precision and diagnostics.

&nbsp;

Operational default windows may later be established prospectively from measured variance, lags, pilot telemetry, and collection cost, but any defaults must be versioned in the applicable operational/analysis contract and must not override a design-specific Analysis Specification Contract.

&nbsp;

## **ChatGPT stochasticity, repeated replicates, and experimental sampling**

&nbsp;

Experiments inherit the permanent-panel fresh-context replication discipline, but the permanent three-replicate design is not automatically sufficient for every experiment.

&nbsp;

An experiment may require:

\- additional independent ChatGPT replicates;

\- more treated/control units;

\- additional waves; or

\- a combination of these.

&nbsp;

Power/MDE or precision planning MUST use observed outcome variability and relevant clustering/repeated-measures dependence rather than treating every ChatGPT response as an independent observation.

&nbsp;

Additional experiment-specific replicates MUST be pre-specified, fresh-context where required by the governing collection methodology, independently preserved, bounded to the experiment, and excluded from the permanent Research Mode denominator unless they truly belong to the permanent panel.

&nbsp;

Experiment-specific prompt/query conditions are allowed in bounded experimental/calibration panels when scientifically useful. They do NOT change the locked permanent 10-condition ChatGPT panel unless a new methodology version is explicitly approved. An experiment may test a cross-surface service/query concept that is not a permanent ChatGPT condition, but those observations remain experiment-scoped.

&nbsp;

## **Prompt-family effects**

&nbsp;

DISCOVERY, RECOMMEND, BEST, and PROBLEM remain explicit experimental context dimensions. Every protocol MUST declare whether prompt family is:

\- part of the primary estimand;

\- a stratification factor;

\- a pre-specified effect modifier/interaction;

\- a secondary outcome dimension; or

\- exploratory.

&nbsp;

When DISCOVERY, RECOMMEND, BEST, and PROBLEM family labels are used among approved prompt conditions, they MUST NOT be silently pooled into one universal treatment effect. Any pooled estimand requires explicit weighting and interpretation in the Analysis Specification Contract. These family labels do not define the permanent panel size; prompt\_condition\_id remains the primary controlled-treatment identifier.

&nbsp;

## **Outcome pre-specification**

&nbsp;

Each confirmatory experiment SHOULD have one primary outcome or a small predeclared primary outcome family, selected from the locked ChatGPT taxonomy and relevant conditioning population.

&nbsp;

Eligible outcome dimensions include:

Entity Visibility → Recommendation Visibility → Top Choice → Mention/Link → Destination → Evidence/Source.

&nbsp;

For example, an experiment may define:

\- primary: P(recommended | surfaced);

\- secondary: P(top\_choice | recommended) and P(direct\_business\_link | recommended); and

\- exploratory: first-party retrieval, branded fanout, or source-topology changes.

&nbsp;

Outcome shopping across many possible ChatGPT states is prohibited for confirmatory inference.

&nbsp;

## **Cross-surface outcomes and mediator governance**

&nbsp;

Maps, Organic, AIO, and ChatGPT outcomes SHOULD be measured together when scientifically relevant, while remaining distinct outcomes rather than a universal blended score.

&nbsp;

A treatment may plausibly create sequences such as:

Organic visibility change → ChatGPT retrieval change → ChatGPT recommendation/linking change.

&nbsp;

Such sequences are scientifically useful but do not automatically establish mediation or causal mechanism. Maps visibility, Organic visibility, AIO visibility, retrieval, citations, or other intermediate states MUST NOT automatically be adjusted away because they may lie on the causal pathway. Decision 13 governs whether they are confounders, mediators, colliders, outcomes, or descriptive pathway variables for a specific estimand.

&nbsp;

## **Spillover, interference, and contamination**

&nbsp;

Every intervention protocol MUST define the expected interference boundary and identify likely spillover channels, including as applicable:

\- multiple locations sharing one domain;

\- brand-wide reputation effects;

\- shared review profiles;

\- internal-link or template changes affecting untreated pages;

\- citation propagation/syndication;

\- indexing/retrieval propagation;

\- treated pages influencing recommendations for untreated locations;

\- competitor responses; and

\- treatment-driven Maps/Organic/AIO changes that alter ChatGPT exposure.

&nbsp;

If interference is likely at the website or brand level, page- or location-level units under that same boundary may be invalid controls. The treatment/randomization unit MUST move to a level at which the no-interference assumption is more defensible, or the analysis must explicitly model/limit the resulting interference.

&nbsp;

## **Treatment adherence and realized exposure**

&nbsp;

Assigned treatment and realized treatment/exposure are distinct and MUST both be preserved.

&nbsp;

Examples of non-adherence include a planned link never going live, a template removing deployed schema, a review-solicitation workflow not being executed, or a designated source page never becoming available as planned.

&nbsp;

For randomized designs, intent-to-treat is the preferred primary analysis where scientifically appropriate because conditioning the primary analysis on realized exposure can reintroduce selection bias. Per-protocol, treatment-on-treated, or exposure-response analyses may be secondary when justified and correctly specified.

&nbsp;

## **Power, precision, and minimum detectable effects**

&nbsp;

Where feasible, a confirmatory intervention SHOULD estimate before launch:

\- expected baseline outcome rate/level;

\- variance;

\- clustering/dependence;

\- planned sample size/effective sample size;

\- practically meaningful minimum detectable effect; and

\- planned statistical power or equivalent precision criterion.

&nbsp;

Repeated ChatGPT replicates do not automatically create equivalent independent sample size. If the design cannot plausibly detect an effect large enough to matter, it MUST be labeled pilot/feasibility rather than used to manufacture a definitive null or causal conclusion.

&nbsp;

## **Stopping and rollback rules**

&nbsp;

Fixed-horizon analysis is the default. Experiments MUST NOT stop early merely because interim results appear favorable.

&nbsp;

Early stopping may occur when pre-specified for:

\- safety/harm;

\- operational failure;

\- material contamination;

\- treatment non-adherence;

\- futility; or

\- a formally specified sequential-analysis rule.

&nbsp;

Operational safety rollback is always allowed. The intervention record MUST preserve the stop/rollback reason, timing, protocol deviation, and resulting evidence limitations.

&nbsp;

## **Multiple testing and analysis search governance**

&nbsp;

Decision 13 multiple-testing and Analysis Search Ledger governance applies to interventions. Before confirmatory analysis, the protocol SHOULD declare:

\- primary treatment contrast;

\- primary outcome family;

\- confirmatory subgroup/effect-modifier analyses;

\- multiplicity treatment where required; and

\- exploratory analyses.

&nbsp;

Every treatment arm, null result, negative result, and pre-specified analysis remains discoverable. The system MUST NOT search many treatments × prompt families × outcomes × markets/industries and report only favorable results.

&nbsp;

## **Null, negative, harmful, failed, and contaminated experiments**

&nbsp;

The intervention system MUST distinguish and preserve at least:

\- null effect — treatment delivered but no detectable outcome effect under the specified design;

\- negative/harmful effect — treatment associated with a worsening of the specified outcome under the design;

\- failed intervention — treatment was not delivered or adherence/exposure failed materially; and

\- contaminated experiment — treatment occurred but causal interpretation was compromised by spillover, concurrent changes, structural breaks, or other violations.

&nbsp;

All remain permanently discoverable and may contribute to contra-evidence, feasibility evidence, or future design improvement. Negative or failed experiments MUST NOT disappear because they are inconvenient.

&nbsp;

## **Intervention-to-finding pathway**

&nbsp;

Intervention evidence MUST flow through the shared parent infrastructure:

&nbsp;

registered intervention → immutable treatment record → outcome collection → Decision 13 statistical analysis → protocol/adherence/contamination diagnostics → validation/replication → shared Research Finding Registry → strategy-use eligibility.

&nbsp;

The ChatGPT module MUST NOT create a separate intervention-results registry or independently assign final scientific evidence classes.

&nbsp;

A qualifying intervention finding MUST retain enough structured metadata to recover, at minimum:

\- exact treatment/version;

\- treatment population/unit;

\- assignment mechanism;

\- design class;

\- primary estimand/outcome;

\- comparator/control method;

\- baseline/pre-trend window;

\- expected lag and outcome/follow-up windows;

\- adherence/exposure status;

\- contamination/interference status;

\- effect magnitude and uncertainty from deterministic/statistical computation;

\- relevant ChatGPT product/methodology regime;

\- protocol deviations/stopping status;

\- null/negative/contra-evidence;

\- validation/replication status;

\- applicability boundaries; and

\- maximum permissible strategy-use ceiling.

&nbsp;

The shared parent Research Finding Registry remains authoritative for final evidence classification and strategy-use eligibility.

&nbsp;

## **Strategy eligibility: TEST versus CHANGE**

&nbsp;

Decision 15 creates a deliberately conservative promotion rule.

&nbsp;

### **TEST eligibility**

A promising intervention may become TEST-eligible after one credible controlled experiment, one strong quasi-experimental result, consistent research-asset evidence, or another sufficiently mature intervention finding, provided the finding is active, applicable, and not blocked by material contra-evidence or design failure.

&nbsp;

### **CHANGE candidate threshold**

A research finding should ordinarily become change\_candidate only when all of the following are satisfied:

1\. at least one qualifying causal/intervention design;

2\. successful protocol and treatment-adherence diagnostics;

3\. practically meaningful effect magnitude rather than statistical significance alone;

4\. uncertainty compatible with the proposed claim;

5\. no fatal contamination or identification failure;

6\. relevant applicability to the intended client use;

7\. no strong unresolved contradictory evidence; and

8\. independent replication.

&nbsp;

Research-asset evidence ordinarily requires real-world/client replication before general client CHANGE eligibility. Quasi-experimental evidence ordinarily requires replication across independent designs, populations, markets, industries, or periods before change\_candidate status because causal interpretation depends more heavily on identification assumptions.

&nbsp;

Decision 14 remains the final client-specific gate. A change\_candidate finding does not automatically produce CHANGE. Client Mode must still confirm strong applicability, a legitimate modifiable treatment, current compatible evidence, no blocking contra-evidence, and mandatory human review.

&nbsp;

## **Causal-language governance**

&nbsp;

Uncontrolled interventions may use temporal/descriptive language only, for example: “After the treatment, recommendation frequency increased.”

&nbsp;

Quasi-experimental results may use conditional causal language only when the identification assumptions and diagnostics support it, and the claim MUST state or preserve those assumptions/limitations.

&nbsp;

Randomized interventions may support language that assignment to the treatment caused an estimated change in the pre-specified outcome within the tested experimental population when randomization and experiment validity are intact.

&nbsp;

Even randomized evidence remains bounded to the treatment, population, product/methodology regime, prompt/outcome scope, and observation window actually tested. It does not establish a timeless universal ChatGPT ranking or recommendation factor.

&nbsp;

## **Decision 15 lock summary**

&nbsp;

Decision 15 therefore locks:

1\. intervention versus experiment as distinct concepts;

2\. no causal interpretation from ordinary uncontrolled before/after change alone;

3\. randomized, quasi-experimental, uncontrolled, and operational-change design classes with explicit evidence ceilings;

4\. mandatory pre-treatment intervention specification and Analysis Specification Contract linkage;

5\. the manipulation itself, not a mediator/downstream state, as the treatment definition;

6\. separate research-asset and client intervention lanes within shared parent infrastructure;

7\. research-asset evidence ordinarily capped at client TEST until real-world replication;

8\. legitimate website, destination, structured-data, entity-consistency, GBP, link, citation/source, review/reputation, social/profile, first-party-source, and cross-surface intervention families;

9\. bundled treatments supporting bundle-level claims only unless component effects are independently identified;

10\. mandatory concurrent-change ledgers and contamination classification;

11\. randomization preferred when feasible, with cluster and randomized staggered-rollout designs explicitly supported;

12\. controlled quasi-experimental designs permitted only with defensible identification assumptions and diagnostics;

13\. no universal baseline, lag, wash-in, or follow-up duration; design-specific adequacy governs;

14\. experiment-specific ChatGPT replicates and query conditions may exceed the permanent panel when pre-specified and bounded;

15\. no modification of the locked permanent 10-condition ChatGPT panel by intervention/experiment rules;

16\. explicit prompt-family treatment/effect-modifier governance and no silent pooling;

17\. pre-specified primary outcomes from the locked ChatGPT funnel taxonomy;

18\. cross-surface outcomes measured separately and potential mediators not automatically controlled away;

19\. explicit spillover/interference boundaries;

20\. assigned versus realized treatment separation and intent-to-treat as the preferred primary randomized analysis where appropriate;

21\. power/MDE or precision planning where feasible and pilot labeling for materially underpowered designs;

22\. fixed-horizon default and pre-specified stopping/rollback rules;

23\. Decision 13 multiple-testing and Analysis Search Ledger governance for experiments;

24\. permanent retention of null, negative, harmful, failed, and contaminated experiments;

25\. a governed intervention → statistical analysis → validation/replication → shared Finding Registry pathway;

26\. TEST eligibility after one sufficiently credible intervention finding where applicable;

27\. a conservative CHANGE-candidate threshold requiring qualifying causal evidence plus independent replication;

28\. real-world/client replication before general CHANGE from research-asset-only evidence;

29\. parent Research Finding Registry authority over final evidence class and strategy-use ceiling; and

30\. causal-language ceilings bounded by design, population, regime, prompt/outcome scope, and observation window.

&nbsp;

## **Decision Log Update**

Decision 15 LOCKED

\- Locked controlled intervention/experiment governance and explicit design-specific causal ceilings.

\- Locked research-asset versus client experiment lanes, mandatory change/adherence/contamination logging, and interference-aware design selection.

\- Locked randomized and qualifying quasi-experimental pathways without treating ordinary before/after client work as causal proof.

\- Locked experiment-specific sampling/replication flexibility without altering the permanent 10-condition ChatGPT panel.

\- Locked null/negative/failed/contaminated experiment retention and the shared intervention-to-finding pathway.

\- Locked TEST versus CHANGE promotion rules, including independent replication before research-driven CHANGE and real-world replication for research-asset-only evidence.

&nbsp;

LOCKED Decision 15 — Interventions / Experiments

&nbsp;

Status: LOCKED. This decision governs how controlled interventions and experiments may generate intervention evidence for the ChatGPT module while reusing the parent platform’s shared intervention infrastructure, Analysis Specification Contracts, and Research Finding Registry.

&nbsp;

15.1 Foundational distinction

&nbsp;

An intervention is an intentional change. An experiment is an intervention conducted under a design capable of estimating the effect of that change. Temporal ordering alone is insufficient: the fact that an intervention occurred before an outcome changed does not establish that the intervention caused the change.

&nbsp;

The system must distinguish at minimum:

\- controlled randomized interventions;

\- controlled quasi-experiments with a defensible identification strategy;

\- uncontrolled interventions / before-after changes;

\- ordinary operational changes.

&nbsp;

Uncontrolled before/after client changes are never causal evidence by themselves. They may provide temporal/descriptive evidence and motivate stronger tests.

&nbsp;

15.2 Legitimate intervention requirements

&nbsp;

Before treatment begins, a research-grade intervention must pre-specify, where applicable:

\- the exact treatment and treatment version;

\- treatment unit and eligible population;

\- assignment mechanism;

\- treatment start/effective timestamp;

\- primary outcome or small predeclared primary outcome family;

\- conditioning population and estimand;

\- pre-treatment baseline;

\- expected wash-in / lag period;

\- primary measurement and follow-up windows;

\- treatment/control or comparator design;

\- concurrent-change policy;

\- treatment-adherence definition;

\- spillover / contamination plan;

\- Analysis Specification Contract;

\- stopping rules;

\- multiple-testing plan where relevant;

\- intended evidence claim and evidence ceiling.

&nbsp;

The treatment must be the actual manipulated object or process, not the hoped-for mediator or outcome. For example, a compliant review-solicitation process is a treatment; “increase reviews by 25%” is not. Adding a defined structured-data implementation is a treatment; “improve entity understanding” is not. Creating or correcting defined legitimate source references is a treatment; “increase authority” is not.

&nbsp;

15.3 Research-asset and client intervention lanes

&nbsp;

Both lanes use the shared parent intervention infrastructure and Finding Registry. No ChatGPT-only intervention ledger or causal truth system may be created.

&nbsp;

Research-asset experiments are the preferred controlled laboratory where feasible because they can support cleaner assignment, isolation, rollback, timing, page/site manipulation, structured-data tests, destination tests, citation/source tests, and staggered rollouts. Their limitation is external validity. Research-asset evidence alone may ordinarily make a treatment TEST-eligible for clients but does not by itself make a general client CHANGE eligible. Real-world/client replication is required before a research-asset result can support general CHANGE eligibility.

&nbsp;

Client experiments provide stronger real-world relevance but typically weaker experimental control because clients, competitors, platforms, and the market may change concurrently. Client experiments therefore require stronger change logging, adherence tracking, contamination assessment, and design-specific causal safeguards.

&nbsp;

15.4 Eligible intervention families

&nbsp;

Eligible legitimate intervention families include, where lawful, ethical, technically feasible, and scientifically interpretable:

\- website/content changes;

\- destination-page changes;

\- structured-data changes;

\- entity-consistency corrections;

\- legitimate GBP changes where applicable;

\- link changes;

\- citation/source changes;

\- review/reputation interventions based on compliant solicitation/process changes;

\- social/profile/source changes;

\- first-party source-environment changes;

\- cross-surface interventions affecting Maps, Organic, AIO, or ChatGPT-relevant inputs.

&nbsp;

Fake reviews, fabricated citations, deceptive business/entity information, or other illegitimate/manipulative activity cannot qualify as research interventions.

&nbsp;

15.5 Treatment isolation and bundles

&nbsp;

A treatment bundle may estimate the effect of the bundle only. If content, schema, links, GBP settings, reviews, or other components are changed simultaneously, the experiment must not attribute the observed effect to an individual component unless the design independently identifies that component.

&nbsp;

Factorial or component-isolation designs may be used when adequately powered and scientifically justified, but they are not required for V1 and may remain Phase 2 / Experimental.

&nbsp;

15.6 Mandatory concurrent-change ledger

&nbsp;

Every treated and control unit must support a unified intervention timeline capturing material concurrent changes across relevant surfaces, including website, GBP, links, citations, reviews, social, content, Organic, Maps, AIO, brand campaigns, major business changes, and material product/platform events.

&nbsp;

Concurrent events should be classifiable as:

\- planned\_co\_treatment;

\- allowed\_background\_change;

\- material\_contamination;

\- exogenous\_shock;

\- unknown.

&nbsp;

Contaminated experiments must remain discoverable. Contamination lowers the permissible evidence ceiling rather than causing the experiment to disappear.

&nbsp;

15.7 Eligible experimental and quasi-experimental designs

&nbsp;

Decision 15 does not mandate one universal design. The design must match the treatment, interference structure, data-generating process, and causal estimand.

&nbsp;

Preferred/eligible designs include:

\- randomized controlled interventions where feasible;

\- cluster randomization when the likely interference boundary is at the site, business, brand, location, or other cluster level;

\- randomized staggered rollouts when all units will eventually receive treatment;

\- difference-in-differences when randomization is infeasible and credible comparison units, adequate pre-treatment history, pre-trend diagnostics, timing, differential-shock checks, and contamination assessment support the design;

\- interrupted time-series designs, preferably controlled where feasible, with appropriate treatment of pre-trends, autocorrelation, seasonality, product-regime changes, and concurrent interventions;

\- matched or synthetic-control approaches where untreated units can plausibly approximate the counterfactual;

\- natural experiments only when an explicit identification argument supports plausibly exogenous exposure.

&nbsp;

The fact that SED did not cause an external change does not automatically make that change exogenous.

&nbsp;

15.8 Baselines, lags, wash-in, and observation windows

&nbsp;

No universal number of baseline or follow-up weeks is locked. Each protocol must define a design-appropriate sequence:

pre-treatment baseline → treatment implementation → wash-in / expected lag → primary outcome window → persistence / follow-up window.

&nbsp;

Adequacy depends on observed variance, outcome frequency, treatment mechanism, indexing/retrieval lag, number of experimental units, clustering/dependence, product stability, desired minimum detectable effect, and the identification strategy. Difference-in-differences requires enough pre-treatment history to evaluate pre-trends. Interrupted time-series requires enough pre/post observations to estimate intervention effects against underlying variation. Operational defaults may later be versioned from observed variance and cost data without overriding this design-based rule.

&nbsp;

15.9 ChatGPT stochasticity, replicates, and experimental query panels

&nbsp;

The permanent three-replicate methodology remains authoritative for the permanent panel, but three replicates are not automatically sufficient for an intervention study. A pre-specified experiment may require additional fresh-context independent replicates, treatment units, waves, or combinations thereof according to power/precision requirements.

&nbsp;

Additional experimental observations must be bounded to the experiment and must not enter the permanent-panel denominator unless they independently satisfy the permanent-panel definition.

&nbsp;

Experiment-specific prompt/query conditions, including cross-surface service/query concepts not present in the permanent ChatGPT panel where scientifically useful, may be included in bounded experimental/calibration panels without silently changing the locked permanent 10-condition ChatGPT panel.

&nbsp;

15.10 Prompt-family effects

&nbsp;

DISCOVERY, RECOMMEND, BEST, and PROBLEM remain explicit dimensions. Every intervention protocol must declare whether prompt family is part of the primary estimand, a stratification factor, a pre-specified effect modifier, or secondary/exploratory analysis.

&nbsp;

When DISCOVERY, RECOMMEND, BEST, and PROBLEM family labels are used among approved prompt conditions, they must not be silently pooled into one universal treatment effect. A pooled estimand is allowed only when the Analysis Specification Contract explicitly defines its meaning and weighting. The family taxonomy does not replace the locked 10-condition production panel.

&nbsp;

15.11 Outcome pre-specification

&nbsp;

Each confirmatory experiment should use one primary outcome or a small predeclared primary outcome family. Eligible outcomes inherit the locked ChatGPT taxonomy, including Entity Visibility, Recommendation Visibility, Top Choice, Mention/Link, Destination, and Evidence/Source outcomes. Secondary and exploratory outcomes must remain explicitly labeled so outcome shopping cannot masquerade as confirmation.

&nbsp;

15.12 Cross-surface outcomes and mediation

&nbsp;

Maps, Organic, AIO, and ChatGPT outcomes may be measured together where relevant but remain distinct outcomes. Cross-surface sequences may be scientifically informative and must be preserved.

&nbsp;

Maps visibility, Organic visibility, AIO exposure, retrieval, citation, linking, or related signals may be mediators rather than ordinary confounders. They must not be automatically adjusted away. Decision 13 and the Analysis Specification Contract determine their analytical role for the specific estimand.

&nbsp;

15.13 Spillover, interference, and contamination

&nbsp;

Every intervention must declare an expected interference boundary. Potential interference includes shared domains, shared brand reputation, review profiles, internal linking, citation propagation or syndication, indexing, treated pages affecting untreated locations, competitor reactions, and treatment-induced Maps/Organic/AIO changes that affect ChatGPT outcomes.

&nbsp;

When interference is plausible at a broader unit than the proposed treatment unit, randomization/control selection should occur at the broader scientifically defensible unit when feasible. Sister locations or pages may be invalid controls when brand/site-level spillover is likely.

&nbsp;

15.14 Treatment assignment versus realized exposure

&nbsp;

The system must distinguish assigned treatment from realized treatment/exposure. Examples include links that never go live, review outreach that generates no reviews, schema that is removed after deployment, or source pages that are never indexed.

&nbsp;

For randomized designs, intent-to-treat is the default primary analysis where appropriate because conditioning on realized treatment may reintroduce selection bias. Per-protocol or treatment-on-treated analyses may be secondary when explicitly justified.

&nbsp;

15.15 Power, precision, and minimum detectable effects

&nbsp;

Where feasible, confirmatory intervention protocols should estimate or preserve:

\- expected baseline outcome;

\- variance;

\- clustering/dependence;

\- sample size and effective sample size;

\- practically meaningful minimum detectable effect;

\- planned statistical power or equivalent precision criterion.

&nbsp;

Repeated ChatGPT replicates, businesses, markets, prompt families, and waves must not create pseudo-replication or the illusion of a larger effective sample than the design provides.

&nbsp;

An intervention that cannot plausibly detect a practically useful effect should be classified as a pilot/feasibility study rather than used to manufacture a definitive null or causal conclusion.

&nbsp;

15.16 Stopping rules

&nbsp;

Fixed-horizon analysis is the default. Experiments must not stop early merely because a favorable result appears statistically significant.

&nbsp;

Pre-specified early stopping may be allowed for safety/harm, operational failure, material contamination, treatment non-adherence, futility, or a formally specified sequential-analysis rule. Operational safety rollback is always permitted, but the reason and resulting analysis status must be recorded.

&nbsp;

15.17 Multiple testing

&nbsp;

Intervention protocols must predeclare, where relevant:

\- primary treatment contrast;

\- primary outcome family;

\- confirmatory subgroups/interactions;

\- multiplicity treatment;

\- exploratory analyses.

&nbsp;

Decision 13 remains authoritative for statistical multiplicity governance. Every treatment arm, null result, and relevant analysis remains discoverable in the Analysis Search Ledger; the system must not report only favorable contrasts.

&nbsp;

15.18 Null, negative, failed, and contaminated experiments

&nbsp;

The following states remain distinct and permanently discoverable:

\- null\_effect: treatment delivered but no detectable outcome effect under the specified design;

\- negative\_or\_harmful\_effect: treatment appears to worsen the outcome;

\- failed\_intervention: treatment was not successfully delivered or adhered to;

\- contaminated\_experiment: treatment occurred but causal interpretation was materially compromised.

&nbsp;

None may be silently discarded because the result is inconvenient.

&nbsp;

15.19 Shared Finding Registry pathway

&nbsp;

Intervention evidence must flow through the shared parent architecture:

registered intervention → immutable treatment record → outcome collection → Decision 13 analysis → protocol/adherence/contamination diagnostics → validation/replication → shared Research Finding Registry → strategy-use eligibility.

&nbsp;

The ChatGPT module must not create a separate intervention-results registry.

&nbsp;

A qualifying intervention finding must preserve enough structured information to reconstruct and bound the claim, including exact treatment, treatment population, assignment mechanism, design class, estimand, controls/comparators, baseline, lags, outcome windows, adherence, contamination, effect magnitude, uncertainty, product regime, protocol deviations, null/negative evidence, replication, applicability, and maximum permissible strategy use. The parent Finding Registry remains authoritative for final evidence classification.

&nbsp;

15.20 Strategy eligibility from intervention evidence

&nbsp;

TEST eligibility may arise from a credible controlled experiment, a strong quasi-experimental result, consistent research-asset evidence, or another sufficiently mature intervention finding, subject to applicability and evidence constraints.

&nbsp;

CHANGE eligibility is intentionally stricter. A finding should ordinarily become a change\_candidate only when all of the following are satisfied:

1\. at least one qualifying causal/intervention design;

2\. successful protocol and treatment-adherence diagnostics;

3\. practically meaningful effect rather than statistical significance alone;

4\. uncertainty compatible with the intended claim;

5\. no fatal contamination;

6\. relevant population/query/product-regime applicability;

7\. no blocking strong contradictory evidence;

8\. independent replication.

&nbsp;

Research-asset-only evidence cannot by itself support a general client CHANGE; real-world/client replication is required. Quasi-experimental evidence should ordinarily require multiple independent populations and/or designs before change\_candidate status because its causal interpretation rests on identification assumptions rather than randomized assignment.

&nbsp;

Decision 14 remains the final Client Mode gate. Conceptually:

change\_candidate finding \+ strong client applicability \+ legitimate modifiable treatment \+ current evidence \+ no blocking contra-evidence → possible CHANGE.

&nbsp;

Human review remains mandatory before implementation.

&nbsp;

15.21 Causal-language governance

&nbsp;

Uncontrolled interventions may use temporal/descriptive language such as: “After the treatment, recommendation frequency increased.” They must not claim causation.

&nbsp;

Quasi-experimental results may use design-bounded intervention language only when the identification assumptions and diagnostics support it, for example: “Under the specified matched difference-in-differences design and its assumptions, the treatment was associated with an estimated intervention effect.”

&nbsp;

Randomized interventions may support causal language bounded to the tested treatment, experimental population, product regime, and observation window, for example: “Assignment to the treatment caused an estimated change in the specified outcome within this experimental population.”

&nbsp;

Even a randomized result does not establish a timeless or universal “ChatGPT ranking/recommendation factor.”

&nbsp;

15.22 Locked Decision 15 summary

&nbsp;

The following are governing requirements:

\- uncontrolled client before/after changes are never causal by themselves;

\- research assets are a strong experimental lane but ordinarily max out at client TEST without real-world replication;

\- randomization is preferred where scientifically and operationally feasible;

\- quasi-experimental designs are allowed only with explicit identification assumptions and diagnostics/falsification where applicable;

\- treatment bundles estimate the bundle only unless components are independently identified;

\- no universal baseline/follow-up week count is authorized;

\- experimental replicates may exceed the permanent three when pre-specified and justified;

\- bounded experiment-specific query panels may be used without changing the locked permanent 10-condition ChatGPT panel;

\- prompt-family effects must be pre-specified and are not silently pooled;

\- the concurrent-change ledger is mandatory;

\- review interventions manipulate legitimate solicitation/processes rather than defining achieved review counts as treatment;

\- cross-surface outcomes may be measured but are not automatically adjusted away;

\- intent-to-treat is primary for randomized designs where appropriate;

\- fixed-horizon stopping is the default;

\- null, negative, failed, and contaminated experiments are retained;

\- credible intervention evidence may support TEST;

\- CHANGE requires qualifying causal/intervention evidence plus independent replication;

\- research-asset-only evidence cannot support general CHANGE without real-world replication;

\- the shared parent Finding Registry remains authoritative.

&nbsp;

CURRENT CONTINUATION STATE — PRD RECONCILIATION → IMPLEMENTATION READINESS

The former “Remaining Decision Sequence” beginning with collection mechanism/provider/API and cadence/cost is superseded. Those are no longer open default methodology decisions. The core scientific methodology is substantially complete and is in design freeze.

&nbsp;

After this reconciliation is verified, the implementation handoff is:

1\. machine-readable collection manifest;

2\. physical Supabase/Postgres schema contract;

3\. operational QA / wave-acceptance contract;

4\. bounded pilot → production protocol;

5\. implementation/build.

&nbsp;

Any unresolved implementation detail must be resolved within those artifacts without inventing or reopening scientific methodology. New permanent prompts, grids, signals, providers, enrichment categories, or scores require explicit research justification and approval rather than being added as part of implementation convenience.

&nbsp;

LOCKED SHARED-ARCHITECTURE UPDATE — Progressive Enrichment & Control Economics — 2026-09-09

&nbsp;

ChatGPT inherits the parent platform's enrichment-economics architecture. This update does not alter ChatGPT's locked prompt, replication, geography, product-surface, outcome, or control methodology.

&nbsp;

Shared enrichment gate: after preserving the immutable ChatGPT observation and resolving observed mentions/assets as far as justified, apply: canonicalized → already sufficiently fresh? → changed materially? → analytically relevant? → paid enrichment required? Globally deduplicate by the correct business/GBP/organization/domain/URL/source/social/content/provider economic unit. A business or asset does not become a new paid enrichment unit merely because ChatGPT surfaced, recommended, cited, linked, retrieved, or referenced it in another replicate, prompt, wave, destination, source relationship, or surface.

&nbsp;

Progressive control enrichment: preserve the locked control flow \`eligible pool → cheap/basic matching variables → candidate controls → selected controls → deep enrichment\`. Tier 1 universal/cheap signals support discovery and eligibility. Tier 2 moderate-cost enrichment occurs when scientifically relevant, changed, stale, or required for a candidate comparison cohort/analysis contract. Tier 3 deep enrichment is reserved for valid cases, selected controls, transition cohorts, replication/validation samples, intervention studies, and approved analyses. This MUST NOT use outcome-conditioned information illegitimately or bias control selection.

&nbsp;

Entity resolution inherits the staged parent resolver: stable identity evidence → inexpensive multi-signal matching → embeddings where useful → LLM adjudication only for unresolved ambiguity → human review where scientifically necessary. Preserve supporting/conflicting evidence, method, stage, confidence, version, and override provenance. Deterministic parsing/rules/provider metadata/structured or lexical comparison precede embeddings and LLM classification where scientifically equivalent.

&nbsp;

Shared reviews, website/page assets, embeddings, backlinks, social/community signals, and other explanatory data are reused when sufficiently fresh and scientifically equivalent. Review bodies use incremental append-only acquisition where technically possible rather than repeated full-history purchase. Unchanged website content reuses prior extraction/embeddings/classifications while preserving temporal page versions; this does not reduce the approved site-research corpus. Slow-changing attributes use signal/provider-specific TTL/change verification with explicit freshness provenance.

&nbsp;

Backlink inheritance: approved shared backlink/link collection remains MONTHLY for entities/URLs covered by Maps/AIO/Organic or another research design that authorizes link acquisition, globally deduplicated by domain/URL/provider economic unit. Weekly Sentinel research may reuse approved lightweight weekly link monitoring and targeted deeper inspection where already justified. ChatGPT appearance alone MUST NOT trigger a new backlink purchase or duplicate backlink reconstruction; ChatGPT joins sufficiently fresh shared link state when it already exists. Quarterly replacement of the approved monthly regular-population cadence is not authorized.

&nbsp;

Where ChatGPT participates in shared Sentinel/cross-surface event analysis, explanatory enrichment is event-driven rather than universally refreshed merely because a weekly observation occurred. Trigger definitions must be predefined/versioned through the applicable analysis contract/baseline-variance methodology, not retrofitted by an LLM after outcomes are observed.

&nbsp;

This update introduces no new brand-demand dedup methodology, no reduced Organic or AI/AIO coordinate design, no core-pages-only website methodology, no arbitrary composite score, and no parallel ChatGPT enrichment warehouse or canonical truth.

&nbsp;

&nbsp;

HISTORICAL / SUPERSEDED COST-PLANNING ADDENDUM — 2026-09-09

Status: retained for financial provenance only; NOT operative for current collection cardinality or budget calculations.

&nbsp;

The former incremental ChatGPT planning model used 25 industries × 50 markets × four prompt-family conditions × three replicates \= 15,000 result-page observations per monthly planning wave and a then-observed DataForSEO planning price of $0.0012/result page, producing an illustrative \~$18 raw-collection estimate. That observation count is superseded by the governing 25 × 50 × 10 × 3 \= 37,500 monthly Full Panel. Therefore the former $18 raw-collection figure and the dependent $60–$90 / $100–$160 / $170–$270 scenario totals MUST NOT be used as current budgets without recomputation from the active manifest and current provider telemetry.

&nbsp;

The useful cost-governance concepts from this historical addendum remain current: ChatGPT is an incremental observational surface rather than a duplicate enrichment universe; canonicalize and deduplicate before paid enrichment; reuse sufficiently fresh shared business/GBP/domain/URL/review/website/social/source data; preserve every raw ChatGPT occurrence even when enrichment is reused; ChatGPT appearance alone does not trigger backlink purchases; observed fanout queries remain first-class; and measured overlap/cache/provider-cost telemetry must replace planning assumptions as evidence accumulates.

&nbsp;

Current cost truth

\- Current ChatGPT Full Panel observation cardinality: 37,500 raw observations per monthly wave before provider failures/non-observability.

\- Weekly collection is the fixed Research Sentinel only.

\- Provider prices and realized call/economic-unit costs are external, versioned planning inputs and must be measured rather than hard-coded as scientific constants.

\- Current whole-platform cost envelopes and working budgets are governed by the Unified parent/handoff; ChatGPT child-level historical scenario totals are non-operative unless explicitly recalculated and versioned against the current manifest.

\- Planning assumptions are never research findings.

&nbsp;

Required cost telemetry remains: raw ChatGPT observations; business/entity occurrences; unique pre-resolution entities; canonical matches/new entities; cross-surface overlap; cache hits/misses; paid-enrichment triggers; fanout counts/patterns; provider calls; and realized costs.

&nbsp;

LOCKED METHODOLOGY UPDATE — 2026-09-09 — FANOUT-DIRECTED ENRICHMENT & TOP-50 EVIDENCE

&nbsp;

ChatGPT does not inherit the Maps/AIO geo grid. Geography remains market-level under the approved prompt manifest with independent fresh-context stochastic replicates. The operative production panel is 25 industries × 50 markets × exactly 10 approved prompt conditions × exactly 3 replicates \= 37,500 raw ChatGPT observations per monthly Full Panel wave. The fixed Research Sentinel is the separate weekly monitoring cohort.

&nbsp;

Every valid resolved business surfaced by ChatGPT receives a fixed inexpensive universal baseline of explanatory-variable enrichment even if it appears in only one replicate, prompt, or platform. This is required to support selected-vs-comparison analyses and avoid outcome-conditioned enrichment bias.

&nbsp;

Additional ChatGPT-specific enrichment is fanout-directed. Observed provider fan\_out\_queries are stored as first-class raw observations and classified into empirically observed evidence families such as reviews/reputation, first-party website/service, Reddit/community/forum, social, directories/lists, credentials, news/media, brand/entity, and location. Those observed families guide additional enrichment. Fanout behavior does not replace the universal baseline and must not be treated as proof of an internal ranking factor.

&nbsp;

Preserve the observable chain where available: original prompt → observed fanout query → retrieved source/result → citation/evidence → surfaced canonical business/entity → recommendation/mention → destination/link. Retrieved, cited, linked, supportive, recommended, and ranked remain distinct states. Deduplicate source enrichment by canonical URL/domain/content hash while preserving every retrieval occurrence.

&nbsp;

ChatGPT appearance alone does NOT trigger a backlink purchase. Existing sufficiently fresh backlink state already present in the shared warehouse may be joined for analysis, but no new backlink API work is purchased solely because ChatGPT surfaced an entity or URL.

&nbsp;

The shared Brand/Service/Location Search-Evidence Layer is locked at the first 5 Google organic pages / Top 50 results for each eligible canonical business using the canonical brand \+ service \+ location query. Preserve all Top-50 results and classify social/community plus other third-party corroboration classes. “Not observed in Top 50” means only that; it is not absence from the web or from Google’s index.

&nbsp;

Website retrieval uses ScrapeOwl under shared content-hash/change-detection rules. The Top-50 layer supersedes the discussed Top-100/10-page option.

&nbsp;

&nbsp;

IMPLEMENTATION-READINESS CHECKPOINT — 2026-09-09 — CURRENT / GOVERNING

This checkpoint supersedes older next-task/implementation-status language in this PRD without changing the locked ChatGPT scientific methodology.

\- Current production contract remains 25 industries × 50 markets × 10 approved prompt conditions × exactly 3 independent fresh-context replicates per monthly Full Panel wave, with no geo grid; the fixed Research Sentinel remains weekly.

\- Shared implementation artifacts now complete: Physical Supabase/Postgres Schema Contract v0.1; Operational QA / Wave Acceptance Contract v0.1 plus machine-readable rules/SQL seed. The collection manifest v0.7 is materially built; ChatGPT has no water-mask dependency, while the shared geo-surface manifest awaits deterministic structural-water application/final executable freeze.

\- Active next artifact: bounded Pilot → Production Protocol, recommended starting scale 3 industries × 5 markets.

\- ChatGPT pilot validation must verify that R1/R2/R3 are three distinct scientific jobs in independent fresh contexts rather than technical retries; failed/refusal/clarification/no-recommendation observations remain preserved and are not replaced merely to obtain a recommendation.

\- Preserve the full observable chain where available: original prompt → observed fanout query → retrieved source/result → citation/evidence → surfaced canonical business/entity → recommendation/mention → destination/link. Retrieved, cited, linked, supportive, recommended, and ranked remain distinct states.

\- Validate immutable raw response retention, response/parser versioning, fanout/source/citation capture, recommendation and rationale semantics, canonical entity resolution, shared enrichment/cache reuse, source enrichment, cost attribution, product/session provenance, absence/failure separation, and QA acceptance.

\- ChatGPT appearance alone does not create a new backlink-purchase path; sufficiently fresh shared link state may be joined under the parent architecture. The pilot must not add a geo grid or silently change prompt wording, replicate count, product/session controls, or other permanent methodology.

\- The pilot is an engineering/observability validation, not an outcome-driven prompt or methodology tuning exercise. Shared canonical entities, signal histories, costs, QA, raw payloads, and finding infrastructure remain parent-owned.

&nbsp;

&nbsp;

LOCKED — APPROVED BOUNDED PILOT → PRODUCTION PROTOCOL — 2026-09-09

&nbsp;

Status: APPROVED. This section supersedes prior wording that treated the bounded pilot as recommended or pending protocol approval.

&nbsp;

Pilot membership is fixed at IND010 Locksmith, IND019 Urgent Care, and IND022 Chinese Restaurant across MKT008 Vancouver WA, MKT011 Phoenix AZ, MKT021 Chicago IL, MKT040 Birmingham AL, and MKT049 New York City NY: 15 industry×market cells.

&nbsp;

ChatGPT contributes 450 pre-water scientific jobs: 15 cells × 10 approved prompt conditions × exactly 3 independent replicates. ChatGPT remains non-grid. The exact C01–C10 prompt literals are inherited from frozen Manifest v1.0 and may not be paraphrased or dynamically rewritten at runtime beyond the approved literal city substitution.

&nbsp;

Provider behavior remains the approved DataForSEO ChatGPT LLM Scraper asynchronous profile: POST /v3/ai\_optimization/chat\_gpt/llm\_scraper/task\_post; GET /v3/ai\_optimization/chat\_gpt/llm\_scraper/task\_get/advanced/{id}; priority 1; English; provider location\_code 2840 (United States); market encoded in the literal prompt only; maximum 100 tasks per POST; and immutable retention of markdown/response content, sources, search\_results, local\_businesses, model/version, task identifiers, timing, and required provenance.

&nbsp;

For every industry × market × prompt condition, R1, R2, and R3 are three separate deterministic scientific jobs with fresh-context isolation. They should be co-submitted within the same wave batch when practical, but no conversational/session state may intentionally carry across replicates. A technical retry is a new attempt beneath the same replicate job; it is never a substitute for or creation of another replicate.

&nbsp;

Pilot max\_attempts \= 3 per deterministic replicate job: one initial attempt plus at most two QA-authorized technical retries. Valid refusal, clarification\_requested, generic\_guidance\_only, no\_local\_recommendations, no business mentions, negative/cautionary mention, zero fanout, zero citation, or zero recommendation is a scientific outcome when technically valid and must not be retried to obtain a more favorable recommendation result.

&nbsp;

ChatGPT promotion to production is governed by the parent COMPLETE-only GO gate. Required checks include exact manifest/database reconciliation, exactly R1/R2/R3 separate jobs per expected condition, fresh-context independence, immutable raw evidence/hash/pointer integrity, response-outcome taxonomy and surface normalization integrity, observed-versus-inferred fanout provenance separation, entity-resolution execution for eligible identifiable mentions, cost attribution, quarantine isolation, reproducible derived-dataset rebuild, and successful mandatory failure drills. Any explicit cross-replicate context/session contamination is critical quarantine. PARTIAL means REMEDIATE, not GO.

&nbsp;