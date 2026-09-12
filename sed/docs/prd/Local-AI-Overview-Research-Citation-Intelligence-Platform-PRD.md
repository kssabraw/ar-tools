# CURRENT AUTHORITATIVE PRODUCTION NOTICE — 2026-09-09

# The operative AIO design is the 25-industry × 50-market production panel with 10 approved query/prompt conditions and 9 coordinates per market: center \+ N/S/E/W at 2.5 miles \+ N/S/E/W at 5 miles, subject to structural water exclusions. The full AIO panel is collected monthly; the fixed Research Sentinel is weekly. This notice supersedes older weekly-full-panel, single-primary-coordinate, 13-point AIO, \~65,000/week, and 8–10-natural-query production statements retained below for historical provenance. Maps/Organic geometry must not be silently applied to AIO.

# 

# Local AI Overview Research & Citation Intelligence Platform

Product Requirements Document (PRD)

**Version: 1.1 — Unified Parent Governance / Adversarial Review Update (2026-09-06)**

**Primary purpose:** SEO research

**Collection cadence: Monthly Full Panel \+ weekly fixed Research Sentinel**

**Current production scale target: 25 industries × 50 markets × 10 approved query/prompt conditions × 9 coordinates \= 112,500 maximum pre-water-exclusion AIO observations per monthly full wave. Weekly collection is limited to the fixed Research Sentinel.**

**Core stack:** DataForSEO \+ Railway \+ Supabase/Postgres \+ Gemini Embeddings \+ GitHub

# **Parent governance: This AIO PRD is an authoritative surface-specific module under the SED Local Search Intelligence Platform — Unified Research Architecture & Cost Optimization PRD (Google Doc ID 1Y5CmSWDpSKryfkmcbPh25UG\_yfyyvwZV2hdkh1hh3Sc). The parent controls shared canonical entities, raw-observation mechanics, provider/economic-unit deduplication, signal storage, content-addressed assets/embeddings, LLM gating, queueing, cost accounting, shared missingness states, Analysis Specification Contracts, discovery/validation/replication governance, intervention infrastructure, and shared finding infrastructure. This document controls AIO-specific sampling, query-family methodology, AIO capture, visibility/presentation semantics, controls/transitions/persistence, sensitivity experiments, and Section 68 evidence/strategy semantics. Where duplicated shared implementation text is weaker than or conflicts with the parent, the parent governs implementation without erasing this module's scientific intent.**

# 

# **Adversarial-review methodological addendum: AIO control selection must be estimand-aware. The exposure under study must not be used as a matching criterion; plausible mediators/colliders must not be automatically adjusted for. Strategy-eligible analyses inherit the parent's Analysis Specification Contract, multiple-testing/FDR, holdout-validation, prospective-replication, practical-effect-size, repeated-measures, selective-enrichment/missingness, negative-control, and intervention-bundle rules. AIO findings must state their population of inference and must not generalize matched organic/local competitors to all market-eligible businesses without supporting design.**

# 

# **AIO prevalence terminology: prevalence calculated from the fixed constructed research panel is standardized panel prevalence. It must not be described as real-world search-demand-weighted local-search prevalence unless a defensible demand-weighting methodology is applied. Query selection must preserve reproducible selection evidence, including treatment/family, selection reason, demand evidence where available, and sampling weight where appropriate. The approved 10-condition AIO panel and 9-point geometry remain fixed/versioned within a methodology version once launched; these requirements improve panel construction and interpretation rather than authorize silent mid-version changes.**

# 

# **Calibration requirement: establish bounded, stratified validation subsets where needed for desktop/mobile, provider/rendering, or coordinate sensitivity beyond the approved production geometry. The full AIO universe remains desktop-first and uses the approved fixed 9-point geometry. Any additional coordinate or device sensitivity work must be explicitly versioned and must measure AIO trigger, citation/source, business-selection, local-entity-surface, and placement agreement without redefining the production panel.**

# 

# **Q\&A validation status: Google Business Q\&A is not a required production V1 signal until a bounded validation study demonstrates current research value. Provider endpoint availability alone is insufficient. Measure returned-data rate, age of newest questions, evidence of new longitudinal activity, and correspondence to a currently meaningful Google surface. Then classify Q\&A as active, historical-only, or retired. Until then, existing Q\&A schema/cost/job text is provisional and must not authorize recurring collection or strategy evidence.**

# 

# **Semantic-processing precedence: all embedding, similarity, classification, review, social, GBP-post, page, and mention-context workflows inherit the parent's Python/SQL Before LLM and Enrichment & Semantic Processing Efficiency contracts. Stored embeddings and local vector math are the default for semantic similarity. Structured LLM extraction runs only for unresolved/research-required semantic variables after deterministic/cache/vector gating. Collection of a text record does not automatically authorize an LLM classification call.**

# 

# **Social and other expensive enrichment expansion must begin with a stratified pilot rather than assuming the illustrative 2,000-business backfill is required at launch. Scale only after coverage, incremental contribution beyond existing signals, cost, and research value are measured. The illustrative 2,000-business cost scenarios remain sensitivity estimates, not mandatory V1 population sizes.**

# 

# **1\. Executive Summary**

The Local AIO Research Platform will systematically monitor how Google AI Overviews behave for local-intent searches across industries, geographic markets, and query types.

The system goes beyond conventional AIO rank tracking. It is designed to answer why certain websites, pages, brands, businesses, directories, publishers, forums, and social platforms receive visibility within local AI Overviews while others do not.

For every search, the platform should record whether an AIO appears; the AIO content; every cited source; every business or company mentioned; every structured AIO local-business-card module/card and every direct embedded Google Business Profile / Maps entity surface where present; whether a company receives a clickable link or only a textual mention; where the company or source appears; left/right placement where exposed; approximate above-the-fold visibility where measurable; organic rankings; local/Map Pack results; social-media citations; source type; authority/link metrics; site-size proxies; page characteristics; semantic similarity between the query, AIO, and source pages; and historical citation persistence.

The research design must preserve three distinct outcomes from day one: source visibility, entity visibility, and destination visibility. A business can be mentioned without its own site being cited, or its site can be cited without the company being prominently named. Those are different SEO outcomes and must remain separate in the schema and analysis. Structured AIO local-business cards and direct embedded Google Business Profile / Maps entity surfaces are presentation surfaces rather than additional fundamental visibility forms: either may confer entity visibility and/or destination visibility, while source visibility is true only when separately evidenced by a source/citation. Google SearchViewer is classified as a destination type when it is the observed URL/action target; it is not itself a presentation-surface class or proof of source visibility.

&nbsp;

The current production AIO universe is 25 industries × 50 markets × 10 approved query/prompt conditions × 9 fixed coordinates per market, for 112,500 maximum pre-water-exclusion observations per monthly full wave. The 9-point geometry is center \+ N/S/E/W at 2.5 miles \+ N/S/E/W at 5 miles. Exact query/prompt wording is versioned and fixed within a methodology version; the system must not manufacture additional queries merely to increase volume.

&nbsp;

Monthly full-panel SERP/AIO collection is exhaustive for the active production universe because those observations are time-sensitive and cannot be reconstructed reliably later. The fixed Research Sentinel is collected weekly. Downstream enrichment is not exhaustive on every run: canonical businesses, domains, pages, profiles, and historical snapshots should be cached and reused, with new enrichment triggered by newly discovered entities, detected changes, AIO/citation/business transitions, analysis-specific staleness requirements, or bounded reconciliation samples. The operating model is baseline enrichment \+ cache reuse \+ incremental updates \+ event-triggered refresh rather than repeated full-universe enrichment.

&nbsp;

This architecture enables two complementary research modes. Cross-sectional analysis asks what AIO-visible businesses/pages have in common relative to matched non-visible controls. Longitudinal transition analysis asks what changed before a business/page gained, lost, retained, or changed its type of AIO visibility. Over time, the platform should increasingly emphasize within-entity and winner/loser transition comparisons so it can test whether changes in reviews, Maps/local prominence, organic position, backlinks/mentions, GBP activity, social activity, topical content, citation corroboration, or other already-approved signals tend to precede or accompany changes in AIO visibility.

&nbsp;

The platform's operational end-state is not research alone. Findings that accumulate sufficient evidence should flow through the Strategy Evidence Framework in Section 68, where they are classified by evidence strength, applicability, actionability, proxy risk, client/competitor gap, expected value, and recommendation confidence before influencing client strategy. When the agency implements a material research-informed change, the intervention and its outcomes should be recorded so the platform can learn from the full cycle: observation → analysis → evidence classification → client opportunity → intervention → measured outcome → refined evidence.

# **2\. Research Objective**

Primary research question:

What characteristics predict visibility, mentions, direct links, and citations in Google AI Overviews for local-intent searches?

&nbsp;

Secondary strategic objective:

Which observed relationships are sufficiently robust, applicable, actionable, and low enough in proxy risk to inform client strategy, and how do measured client interventions strengthen, weaken, or refine that evidence over time?

Secondary research questions:  
• What percentage of observed local-intent searches produce an AIO overall, and how does AIO prevalence vary by industry, city/market, market tier, intent, query family, geography type, period, and later device?  
• What determines whether a local-intent query produces an AIO?  
• What makes Google cite one page instead of another?  
• Why are certain local businesses recommended or mentioned?  
• When does Google provide a clickable company link versus an unlinked brand mention?  
• Which companies receive prominent placement versus right-side/source-only visibility?  
• How strongly does AIO visibility correlate with organic position, domain authority, page authority, referring domains, backlinks, site size, and organic visibility?  
• How strongly does AIO visibility correlate with Map Pack position, reviews, categories, location, and third-party business mentions?  
• Does semantic similarity predict citations better than traditional authority metrics?  
• Which social platforms are cited, and for which query/vertical types?  
• What source/site types does Google use in local AIOs—such as business sites, directories/data aggregators, publishers/editorial sites, news, review platforms, social/community platforms, forums, video platforms, Google properties, government, associations, manufacturers, and marketplaces?  
• What page/content formats does Google use—such as service/location pages, listicles/rankings, news articles, editorial guides, blog posts, review/profile pages, social posts/threads, forum threads, directory listings, datasets/databases, videos, and Google Maps/GBP?  
• For each source/site type and content type, what percentage of AIOs contain at least one such source, what share of all citations does it receive, and what share of unique cited domains/pages does it represent?  
• How does source and content composition vary by industry, intent, geography cohort, query family, city/market tier, AIO placement, and time?  
• Does Google rely more on particular source/content types for particular intents—for example listicles for recommendation queries, business sites for direct-service queries, social/community content for recommendations, directories/data aggregators for local entity corroboration, or Google-owned properties for near-me searches?  
• How much of local AIO sourcing comes from Google-owned properties versus the open web?  
• Does Google mention businesses based on third-party corroboration without citing the business website?  
• How do geo-neutral, explicit-city, and near-me formulations differ in AIO triggering, businesses selected, citations, Maps overlap, and signal relationships when the underlying service/intent is held constant?  
• How much absolute and relative AIO lift occurs from geo-neutral → explicit-city, geo-neutral → near-me, and explicit-city → near-me, and how do those lifts change over time?  
• How sensitive are selected near-me AIO results to fixed searcher coordinates within the same market?  
• How stable are AIO triggers, answers, citations, company recommendations, and source domains over time?  
• What changes in observable business/page signals occur before an entity first gains AIO visibility, loses visibility, regains visibility, or changes from mention-only to direct-link/citation visibility?  
• When one business/page replaces another in an AIO for the same query, which fast-moving signals changed for the incoming versus outgoing entity before or around the transition?  
• Do changes in reviews, Maps/local prominence, organic position, backlinks/mentions, GBP activity, social activity, topical content, or corroboration tend to precede AIO gains/losses, occur simultaneously, or follow them?  
• Are some AIO gains/losses short-lived while others persist, and which pre-transition conditions distinguish durable transitions from temporary churn?  
• Within the same business or page, are changes in approved explanatory variables associated with changes in AIO visibility after controlling for stable entity characteristics?

• Which findings remain strategically credible after matched-control, multivariable, longitudinal, within-entity, persistence, and sensitivity analysis, and for which industries, markets, intents, and geography cohorts do they actually apply?

• What percentage of local-intent AIO observations contain structured local-business-card modules, and how does that prevalence vary by industry, intent, query family, geography type, market tier, period, and device?

• Which businesses are selected and ordered in these cards, and how strongly do they overlap with the traditional Local Pack/Maps results, AIO text mentions, direct links, and source citations?

• Which attributes, service/category text, actions, and destinations are exposed in local-business cards, including Google-hosted searchviewer/Business Profile destinations versus business websites where observable?

• Do Maps/local prominence, proximity, GBP category/service relevance, and review evidence predict local-card inclusion or rank differently from organic rank, authority, backlinks, and page relevance?

• How persistent are local-card modules and selected businesses, and how do local-card gains, losses, swaps, rank changes, or destination changes relate to other AIO visibility transitions?

• What percentage of local-intent AIO observations contain a direct embedded Google Business Profile / Maps entity surface, and how does that prevalence vary by industry, intent, query family, geography type, market tier, period, device, and coordinate cohort where tested?

• Which businesses receive direct embedded GBP visibility, and how strongly do those selections overlap with traditional Local Pack/Maps results, local-business cards, AIO text mentions, direct business links, and source citations?

• Which GBP fields, attributes, service/category text, images, actions, and destinations are displayed in embedded GBP surfaces, including business websites, Maps/GBP destinations, Google SearchViewer destinations, call, directions, and booking actions where observable?

• Do Maps/local prominence, proximity, GBP category/service relevance, reviews, and other local-entity signals predict direct embedded GBP inclusion differently from local-card inclusion and conventional web-source citation?

• How persistent are direct embedded GBP surfaces, how coordinate-sensitive are they, and how do embedded-GBP gains, losses, regains, destination/action changes, GBP-only visibility, and card ↔ embedded-GBP surface transitions relate to other AIO changes?

&nbsp;

• When the agency implements a research-informed intervention, do subsequent target outcomes and relevant comparison groups strengthen, weaken, or refine the original finding?

# **3\. Initial Hypotheses**

H1. AIO prevalence differs substantially by query intent.

H2. Informational-commercial local searches trigger AIO more frequently than pure transactional searches.

H3. Organic position positively predicts AIO citation probability.

H4. Domain authority positively predicts citation probability after controlling for organic position.

H5. Page-level referring domains are more predictive than domain-level authority for some query classes.

H6. Semantic similarity between query and page predicts AIO citation probability.

H7. Best-passage semantic similarity predicts citation probability better than whole-page similarity.

H8. Third-party sources frequently support business recommendations even when the business website is not cited.

H9. Social/community sources disproportionately influence recommendation-style queries.

H10. AIO visibility varies significantly between industries.

H11. AIO visibility varies by market size and geography.

H12. Businesses with stronger Maps visibility have a higher probability of being mentioned in local AIOs.

H13. AIO citations exhibit meaningful week-to-week volatility.

H14. Certain domains demonstrate unusually high citation persistence.

H15. Direct clickable company links are governed by a different signal mix than unlinked brand mentions.  
H16. Geo-neutral, explicit-city, and near-me formulations exhibit meaningfully different AIO prevalence, business selection, citation patterns, and signal relationships within matched query families.  
H17. Adding explicit or implicit geography produces measurable AIO prevalence lift for at least some local-intent query families, and the magnitude of that lift changes over time.  
H18. Proximity and Maps/local prominence have stronger relationships with business selection for near-me queries than for otherwise comparable geo-neutral and explicit-city queries.

H19. Some apparent cross-sectional relationships between business/page signals and AIO visibility will materially weaken after matched-control, multivariable, within-entity, or longitudinal analysis, indicating that the original signal was partly a proxy for stable business characteristics or other confounders.

H20. Signals that consistently precede AIO visibility transitions and replicate across within-entity, incoming-versus-outgoing, and matched non-transition comparisons will provide stronger strategic evidence than signals that merely distinguish existing AIO winners from non-winners at a single point in time.

&nbsp;

H21. AIO local-business-card inclusion is a distinct presentation/selection outcome with a different predictor mix from conventional source citation, text mention, and direct website-link visibility.

&nbsp;

H22. Maps/local prominence, proximity, GBP category/service relevance, and review evidence have stronger associations with AIO local-business-card inclusion/rank than with conventional web-source citation.

&nbsp;

H23. AIO local-business-card module prevalence and selected business sets vary materially across matched geo-neutral, explicit-city, and near-me query formulations.

&nbsp;

H24. Direct embedded Google Business Profile / Maps entity surfaces are a distinct AIO presentation/selection outcome with a predictor mix that may differ from conventional web citation, text mention, direct website-link visibility, and local-business-card inclusion.

&nbsp;

H25. Maps/local prominence, proximity, GBP category/service relevance, reviews, and other local-entity signals have stronger associations with direct embedded GBP selection than with conventional web-source citation, while embedded-GBP selection may only partially overlap traditional Local Pack ordering.

# **4\. Experimental Universe**

Current production target: 25 industries × 50 markets × exactly 10 approved AIO query/prompt conditions × 9 fixed coordinates \= 112,500 maximum pre-water-exclusion AIO observations per monthly Full Panel wave. The four core Google query classes plus six locked conversational/long-tail conditions are versioned treatments; the collection system must not generate extra variants or silently omit approved conditions. Query-form and geography-family labels remain analytical attributes where applicable, not a mechanism for changing the panel size.

Historical planning note: an earlier AIO design estimated roughly nine natural variants and \~65,000 weekly/shared-geometry observations. That volume/cadence is superseded and MUST NOT be used for implementation or cost planning. Current AIO Full Panel volume is 112,500 maximum pre-water-exclusion observations per monthly wave; the weekly Research Sentinel is the separate fixed monitoring subset governed by the parent contract.

The exact experiment universe must be version-controlled. Once an experiment version begins, its industries, cities, query templates, device settings, and location methodology should remain fixed unless a new version is created.

# **5\. Industry Sampling**

Industries should represent distinct local-search ecosystems rather than a single vertical family.

Recommended starting verticals:  
Home services: plumbing, HVAC, roofing, electricians, pest control, tree service, landscaping, garage door repair, foundation repair, house cleaning, painting, moving, water damage restoration.  
Legal: personal injury, family law, criminal defense.  
Medical/local services: dentistry, cosmetic dentistry, dermatology, chiropractic, med spas.  
Automotive: auto repair, auto body.  
Other: veterinarians, property management.

The list should be finalized before V1 data collection and remain unchanged within the experiment version.

# **6\. Geographic Sampling**

Do not sample only major metros. Stratify cities by market size and region.

Suggested market tiers:  
Tier 1: major metros.  
Tier 2: large secondary markets.  
Tier 3: mid-sized cities.  
Tier 4: smaller markets.

Geographic coverage should span the West Coast, Southwest, Mountain West, Midwest, South, Southeast, and Northeast.

Store for every market:  
city, state, metro, latitude, longitude, population, population bucket, census/region label, and market tier.

This enables later analysis by city size, region, and market competitiveness.

# **7\. Query Treatments, Intent Taxonomy & Historical Query-Development Provenance**

# **Production AIO collection uses exactly 10 approved, locked query/prompt conditions per industry: four core Google query classes plus six locked conversational/long-tail conditions. Exact literal treatment text is versioned and belongs in the collection manifest; collection code or an LLM must not generate, rewrite, substitute, or omit treatments during a methodology version. The earlier matched-family examples below are retained as historical query-development provenance and as analytical taxonomy only where they map to an approved current treatment.**

# 

# **Current core Google query classes are: \[SERVICE\] near me; best \[SERVICE\] near me; the manually approved natural industry-specific high-need/commercial \[SERVICE\] near-me treatment; and \[SERVICE\] in \[CITY\]. The additional six conversational/long-tail conditions remain locked/versioned. Historical query\_family\_id and geography labels may still group genuinely comparable approved treatments for analysis, but they no longer determine how many production queries are generated.**

# 

# **Example for plumbing in Phoenix:**

# **Base service family:**

# **plumber**

# **plumber phoenix**

# **plumber near me**

# 

# **Recommendation family:**

# **best plumber**

# **best plumber phoenix**

# **best plumber near me**

# 

# **Urgent family:**

# **emergency plumber**

# **emergency plumber phoenix**

# **emergency plumber near me**

# 

# 

# **Cost family where natural:**

# **how much does a plumber cost**

# **how much does a plumber cost in phoenix**

# **A near-me cost variant should be included only when the phrase is natural and supported by search behavior.**

# 

# **Problem/service family where natural:**

# **slab leak repair**

# **slab leak repair phoenix**

# **slab leak repair near me**

# 

# **HISTORICAL QUERY-DEVELOPMENT PROVENANCE: the earlier design selected approximately 8–10 natural variants from geography/intent families. That variable-count selection rule is superseded for production. Current AIO collection uses exactly 10 approved, locked conditions per industry—four core Google query classes plus six locked conversational/long-tail conditions. Historical family labels may be retained for analysis where they map to an approved condition, but they do not authorize generating, dropping, or substituting production queries.**

# 

# **Template families should be stored independently from generated keywords. Candidate family patterns include:**

# **Base service: {service} / {service} {city} / {service} near me**

# **Recommendation: best {service} / best {service} {city} / best {service} near me**

# **Urgent: emergency {service} / emergency {service} {city} / emergency {service} near me — where natural**

# **Cost: how much does {service} cost / how much does {service} cost in {city}; near-me cost variant only where natural**

# **Problem: {specific\_problem\_or\_service} / {specific\_problem\_or\_service} {city} / {specific\_problem\_or\_service} near me — where natural**

# **Historical provenance only: additional family patterns from the earlier variable-count design do not authorize new production AIO queries. A permanent treatment change requires explicit approval and a new methodology/collection-manifest version.**

# 

# **Each query receives both an intent classification and a geography classification. Intent classes can include transactional, commercial investigation, recommendation, cost, problem-solution, urgent, or informational-local. Geography classes are geo\_neutral, explicit\_city, near\_me, and other where needed.**

# 

# **Every generated query must store query\_family\_id. Members of the same family share the same industry, market, underlying service/problem, intent, device, language, and standardized market location context; the intended difference is the geographic wording. Example: “emergency plumber,” “emergency plumber phoenix,” and “emergency plumber near me” share one query\_family\_id.**

# 

# **For matched-family analysis, all variants should use the same fixed, versioned market coordinate/location context whenever the provider supports it. This enables clean comparison of service-only versus service+city versus near-me AIO prevalence and downstream AIO composition. Section 66 defines the lift calculations and longitudinal reporting requirements.**

# 

# **8\. Geography Cohorts, Reference Conditions & Controls**

The study uses matched query-family cohorts to compare query formulations, plus separate winner/non-winner page and business controls for explanatory modeling.

&nbsp;

Geo-neutral, explicit-city, and near-me queries are all first-class primary cohorts. The geo-neutral form is the reference condition for geography-lift analysis, not a throwaway control sample.

&nbsp;

Recommended matched geography comparisons and sensitivity experiments:

Matched geography triplets: for each selected underlying intent, collect a geo-neutral variant, explicit-city variant, and near-me variant wherever natural. Example: “emergency plumber” / “emergency plumber phoenix” / “emergency plumber near me.” The three variants should use the same industry, market, device, language, and standardized location context so wording is the primary difference.

Same-query/multi-location sensitivity: selected near-me queries repeated from several fixed secondary coordinates within the same metro to measure geographic sensitivity. This is a sensitivity experiment, not the main control group.

Explicit-city coordinate sensitivity: for a smaller subset, the same city-modified query may also be repeated from multiple coordinates to test whether inferred physical location affects results even when the city is written in the query.

Device sensitivity: a later representative mobile subset can measure device-specific AIO behavior against the desktop primary cohort.

&nbsp;

The term control group should primarily refer to matched non-AIO pages/businesses from the same organic/local environment, as defined in Section 27 and Section 65\. Query-form variants are comparison cohorts; multi-coordinate and device repeats are sensitivity experiments. All query-family definitions, coordinates, control-selection rules, and sampling rules must be versioned.

&nbsp;

# **9\. Device Strategy**

V1 should prioritize desktop to simplify layout and placement methodology.

A later representative subset should duplicate queries on mobile to measure device differences.

Every observation must store device, language, viewport assumptions used for derived placement metrics, and location parameters.

# **10\. AIO Module Integration with Shared Platform Architecture**

Shared architecture is inherited from the Unified Platform PRD. This module defines only AIO-specific configuration, collection/parsing requirements, derived AIO observations, and module-specific analysis dependencies. AIO work must use the parent scheduler, canonical entity graph, raw-observation layer, shared signal warehouse, content assets/embeddings, cost ledger, finding registry, and intervention infrastructure rather than implementing parallel copies. Railway, Supabase/Postgres, object storage, provider workers, and other deployment choices are governed by the parent except where this module declares an AIO-specific requirement.

# **11\. Raw Data Preservation**

Never discard or overwrite the original SERP/API response.

Store every raw response compressed in object storage using a deterministic, non-overwriting path that preserves run and provider-task identity, such as:  
/raw-serps/YYYY/MM/DD/run-{run\_id}/query-{query\_id}/task-{provider\_task\_id}.json.gz

&nbsp;

Do not use a query-only path that could be overwritten by retries, duplicate runs, or multiple observations on the same date.

Postgres should store the object path, provider task identifiers, status, and parser version.

Raw preservation lets future parsers extract fields that were not anticipated when the study began.

# **12\. Experiment Versioning**

Table: experiment\_versions

Recommended fields:  
id  
name  
description  
start\_date  
end\_date  
industry\_definition  
city\_definition  
query\_template\_definition  
query\_universe\_version  
query\_template\_version  
coordinate\_strategy\_version  
control\_selection\_version  
source\_taxonomy\_version  
content\_taxonomy\_version  
feature\_set\_version  
analysis\_model\_version  
strategy\_framework\_version\_when\_applicable  
device  
language  
serp\_settings  
viewport\_definition  
parser\_version

aio\_local\_entity\_surface\_parser\_version  
created\_at

Example: local-aio-v1.

Any material methodology change should create a new experiment version rather than silently altering V1.

# **13\. SERP Runs**

Table: serp\_runs

Fields:  
id  
experiment\_version\_id  
started\_at  
completed\_at  
expected\_queries  
successful\_queries  
failed\_queries  
estimated\_provider\_cost  
git\_commit  
collector\_version  
parser\_version  
status

Each monthly Full Panel and weekly Sentinel collection is an explicit run/cohort. Month-over-month Full Panel comparisons and week-over-week Sentinel comparisons must preserve cohort identity; the Sentinel must not be treated as a complete weekly Full Panel.

# **14\. Query Registry**

Table: queries

Fields:  
id  
experiment\_version\_id  
keyword  
industry\_id  
city\_id  
query\_template\_id  
query\_family\_id  
intent  
query\_geo\_type  
location\_code  
latitude  
longitude  
location\_coordinate  
coordinate\_label  
coordinate\_strategy\_version  
explicit\_location\_text\_when\_present  
near\_me\_boolean  
device  
language  
active  
created\_at

Queries should be generated once per experiment version and rerun by ID every week. Do not regenerate keyword strings independently each week.

# **15\. SERP Observations**

Table: serp\_observations

One immutable record per query × run.

Fields:  
id  
run\_id  
query\_id  
collected\_at  
aio\_present  
prevalence\_eligible  
prevalence\_exclusion\_reason  
aio\_rank  
aio\_async  
local\_pack\_present  
paa\_present  
featured\_snippet\_present  
organic\_result\_count  
raw\_storage\_path  
provider\_task\_id  
provider\_check\_url  
status  
error\_code

&nbsp;

prevalence\_eligible must explicitly define whether the observation belongs in AIO-prevalence denominators. Failed, malformed, incomplete, or methodology-excluded observations must not silently enter the denominator; preserve an exclusion reason so prevalence can be reproduced.

Observations must be append-only. Never update last week’s row with this week’s result.

# **16\. AI Overview Answers**

Table: aio\_answers

Fields:  
id  
serp\_observation\_id  
text  
markdown  
word\_count  
citation\_count  
link\_count  
business\_mention\_count  
answer\_hash  
created\_at

answer\_hash should be calculated from normalized answer content. This provides inexpensive detection of whether the AIO changed between observations.

# **17\. AIO Elements**

Do not flatten the entire AIO into a single blob if the provider returns element-level structure.

Table: aio\_elements

Fields:  
id  
aio\_answer\_id  
element\_index  
element\_type  
title  
text  
markdown  
position  
rectangle\_x  
rectangle\_y  
rectangle\_width  
rectangle\_height  
created\_at

Element-level structure is required to distinguish where a link or mention appeared and to support placement research. Preserve provider element/sub-element type and parent-child relationships when exposed. Structured local-business-card modules/cards and direct embedded Google Business Profile / Maps entity surfaces are normalized separately under Section 69 while retaining their originating AIO element/provider context.

# **18\. Citation Model**

Table: aio\_citations

Fields:  
id  
aio\_answer\_id  
aio\_element\_id  
page\_id  
domain\_id  
citation\_index  
source  
title  
snippet  
url  
position  
is\_reference  
is\_inline\_link  
created\_at

A reference/citation and an inline clickable link must never be treated as the same event.

# **19\. Domain Registry and Source Taxonomy**

Table: domains

Fields:  
id  
domain  
root\_domain  
subdomain  
source\_type  
source\_type\_version  
social\_platform  
is\_social  
is\_forum  
is\_directory  
is\_publisher  
is\_government  
is\_google\_property  
is\_business  
first\_seen\_at  
last\_seen\_at

Initial source/site taxonomy:  
local\_business  
national\_business  
directory\_data\_aggregator  
social\_community  
forum  
video\_platform  
publisher\_editorial  
news  
review\_platform  
google\_property  
government  
association  
manufacturer  
marketplace  
other

&nbsp;

Source/site type describes the organization or platform/domain, not the format of the individual cited page. Keep it separate from page/content type. For example, a publisher may host a listicle, news article, or guide; a business domain may host a homepage, service page, location page, or blog article. Google-owned properties must remain an explicit google\_property class so the platform can quantify reliance on Google's own ecosystem versus the open web.

Classification should be independently stored so the taxonomy can evolve without rewriting raw observations.

# **20\. Social-Media Tracking**

Track social/community platforms explicitly, including at minimum:  
Reddit  
YouTube  
LinkedIn  
Facebook  
Instagram  
TikTok  
X  
Nextdoor  
Pinterest  
Quora

Where feasible, classify the cited social asset subtype as:  
profile  
company\_page  
post  
thread  
comment  
video  
community  
unknown

&nbsp;

This social-platform asset subtype is a platform-specific classification and must remain distinct from the global page/content taxonomy in Section 21\. A social URL may therefore have both a global content\_type and a more specific social asset subtype.

This allows analysis such as social citation share by platform, query intent, vertical, city, market tier, and week.

# **21\. Page Registry**

Table: pages

Fields:  
id  
domain\_id  
url  
normalized\_url  
canonical\_url  
url\_hash  
title  
h1  
page\_type  
content\_type  
content\_type\_version  
http\_status  
content\_hash  
first\_seen\_at  
last\_seen\_at  
last\_crawled\_at

&nbsp;

Initial page/content taxonomy should support at minimum: homepage, service\_page, location\_page, listicle\_ranking, news\_article, editorial\_guide, blog\_post, review\_profile, directory\_listing, dataset\_database, social\_post\_thread, forum\_thread, video, google\_maps\_gbp, other. Preserve both source\_type from the domain/platform and content\_type from the individual page so analyses can distinguish, for example, publisher-hosted listicles from publisher-hosted news articles.

URL normalization must remove irrelevant tracking parameters while preserving parameters that materially identify unique content.

# **22\. Page Content and Change Detection**

Table: page\_content

Fields:  
id  
page\_id  
observation\_or\_snapshot\_at  
collected\_at  
title  
meta\_description  
h1  
headings\_json  
main\_text  
word\_count  
schema\_types  
author  
published\_at  
updated\_at  
content\_hash  
extraction\_version  
raw\_storage\_path

Raw HTML belongs in object storage.

On recrawl:  
fetch → extract main content → normalize → hash.  
If the hash is unchanged, reuse the existing content version and avoid duplicate semantic work.  
If the hash changes, create a new immutable content snapshot/version, update only the canonical page's current-state metadata/pointer as needed, regenerate embeddings for the new content version, and rerun content/entity extraction. Do not overwrite the historical content snapshot that was valid for earlier AIO observations.

# **23\. Domain and Page Metric Snapshots**

Do not place “current” authority metrics directly on canonical domain/page rows. Use historical snapshots.

Table: domain\_metric\_snapshots  
Fields:  
id  
domain\_id  
snapshot\_date  
dfs\_rank  
referring\_domains  
backlinks  
spam\_score  
organic\_keywords  
organic\_pages  
estimated\_traffic  
site\_size\_proxy

Table: page\_metric\_snapshots  
Fields:  
id  
page\_id  
snapshot\_date  
dfs\_rank  
referring\_domains  
backlinks  
estimated\_traffic  
ranking\_keywords

After the initial snapshot, reuse link/site metrics until a staleness threshold, detected change, transition event, or scheduled low-frequency reconciliation requires a new snapshot. Do not refresh every known domain/page simply because another month has elapsed.

# **24\. Site Size**

Do not rely on Google site: counts as the primary measure of site size.

Use multiple proxies:  
organic\_pages  
ranking\_pages  
ranking\_keywords  
estimated\_traffic  
crawl\_discovered\_pages

Preserve raw numeric variables and optionally derive buckets such as micro, small, medium, large, and very\_large.

# **25\. Embedding Architecture**

Use Supabase pgvector for vector storage and similarity queries.

Tables:  
query\_embeddings  
page\_embeddings  
aio\_embeddings

Every embedding record must include model, model version, content hash, vector, and created\_at. Never store a vector without the model identity that produced it.

V1 should use lightweight URL \+ title \+ H1 embeddings for site-wide topical census work and whole-page embeddings for strategically selected pages. Targeted passage/chunk embeddings may be added for AIO-cited pages, matched control pages, and other high-relevance candidates when useful; full-site chunking is not required for V1.

# **26\. Semantic Similarity Metrics**

Calculate at minimum:  
query → cited page similarity  
AIO → cited page similarity  
query → non-cited control page similarity  
AIO → non-cited control page similarity

Targeted deep-page analysis should add where enabled:  
query → best passage similarity  
AIO → best passage similarity  
mean chunk similarity  
maximum chunk similarity

This allows testing whether Google favors the most semantically aligned passage even when the overall page is less similar.

# **27\. Control Group Design**

Do not enrich only pages that received AIO citations.

For every AIO query, create matched controls for the outcome being analyzed rather than enriching only winners. Page-level citation controls should come from non-cited competing organic pages; a strong initial approach is to consider organic positions 1–10, remove pages already cited by AIO, and select a fixed/versioned number of remaining pages. ially come from businesses in the same Maps/local environment that were not selected or mentioned by the AIO, supplemented where appropriate by same-query organic competitors that represent the same service/geography/category.

Example:  
AIO cites organic \#4.  
Controls include organic \#1, \#2, \#3, \#5, and \#6.

Apply the same enrichment methodology to winner and control pages/businesses wherever possible. Store control type, selection reason, source SERP/local position, matching attributes, and control-selection version as defined in Section 65\.

This is essential. Without matched controls, the project can describe what AIO-visible pages/businesses look like but cannot reliably identify what differentiates them from plausible alternatives Google did not cite, mention, or directly link.

# **28\. Organic Results**

Table: organic\_results

Fields:  
id  
serp\_observation\_id  
page\_id  
domain\_id  
organic\_position  
rank\_absolute  
title  
snippet  
is\_aio\_cited

Derived ranking buckets can include top\_3, top\_10, 11\_20, 20\_plus, and not\_ranking.

# **29\. Local Results and Business Registry**

Table: local\_results

Fields:  
id  
serp\_observation\_id  
business\_id  
position  
rating  
review\_count  
primary\_category  
latitude  
longitude  
website\_domain\_id

Table: businesses

Fields:  
id  
name  
normalized\_name  
address  
city  
state  
phone  
website\_domain\_id  
google\_place\_id  
cid  
first\_seen\_at  
last\_seen\_at

This supports AIO ↔ Maps overlap analysis. Any business resolved from an AIO local-business card or direct embedded GBP surface must map to this same canonical businesses registry so AI-surface selection can be compared directly with traditional \`local\_results\` positions and GBP/place identity.

# **30\. Business Mentions Versus Citations**

Business mentions are separate from citations.

Table: aio\_business\_mentions

Fields:  
id  
aio\_answer\_id  
aio\_element\_id  
business\_id  
mention\_text  
mention\_index  
linked  
linked\_url  
linked\_domain\_id  
source\_support\_type  
created\_at

A business can be named in the answer while Yelp, Reddit, BBB, a newspaper, or another source is cited as supporting evidence. That relationship must be preserved.

# **31\. Company Appearance Classification**

Table: aio\_company\_appearances

Recommended fields:  
id  
aio\_answer\_id  
aio\_element\_id  
business\_id  
appearance\_type

appearance\_surface

local\_business\_card\_id

embedded\_gbp\_surface\_id  
is\_text\_mention  
has\_clickable\_link  
linked\_url  
linked\_domain\_id  
is\_reference  
reference\_page\_id  
position  
rectangle\_x  
rectangle\_y  
rectangle\_width  
rectangle\_height  
above\_fold\_status  
appearance\_index  
created\_at

Initial appearance roles:  
linked\_main\_mention  
unlinked\_main\_mention  
reference\_only  
source\_only

&nbsp;

Do not encode right\_position and left\_position as mutually exclusive appearance types. Placement is a separate dimension derived from raw position/rectangle fields because a linked or unlinked main mention may also have a left/right placement. Preserve appearance role, linkage/reference status, placement, and presentation surface independently. Initial appearance\_surface values should support main\_answer\_text, reference, source\_panel, local\_business\_card, embedded\_gbp, and other. A local-business-card or embedded-GBP surface does not automatically imply a conventional text mention, web-source citation, or direct business-website link.

Do not reduce these to one “cited” boolean.

# **32\. Placement and Above-the-Fold Analysis**

Store raw provider geometry/position fields first. Derive semantic labels later.

Raw fields:  
position  
rectangle\_x  
rectangle\_y  
rectangle\_width  
rectangle\_height

Derived fields:  
visible\_above\_fold  
partially\_above\_fold  
below\_fold

A fixed research viewport must be defined and versioned. Example desktop viewport: 1440 × 900\.

Do not automatically equate position=right with “sidebar.” First validate the provider representation against rendered Google SERPs. The raw database should preserve position=right and any rectangle geometry even if the semantic label changes later.

# **33\. Validation Study**

Before production research begins, manually review approximately 100 SERPs, stratified across geo-neutral, explicit-city, and near-me query cohorts and across representative industries/markets. Include matched query families so the same service/intent is validated across all three geography formulations.

For each:  
1\. Retrieve the provider response.  
2\. Inspect the rendered Google result where possible.  
3\. Compare AIO presence and text.  
4\. Compare links.  
5\. Compare references.  
6\. Compare company mentions.  
7\. Compare left/right placement.  
8\. Compare rectangle placement.  
9\. Compare citation destinations.

10\. Where structured local-business cards appear, compare rendered card/module presence, selected businesses, displayed attributes, actions/destinations, order, geometry, and the exact provider encoding/raw element type.

11\. Where direct embedded Google Business Profile / Maps entity surfaces appear, validate the rendered surface independently from local-business cards: resolve the business, compare displayed fields/attributes/services/images/actions/destinations, geometry/above-fold placement, and the exact provider encoding/raw element type. A Google Maps, Google Business Profile, or Google SearchViewer URL alone does not establish that an embedded GBP surface was rendered; require provider structure and/or rendered validation.

Produce a validation report and freeze definitions for linked mention, unlinked mention, citation/reference, main-answer role, raw right/left placement, any separately validated sidebar-like interpretation, and above-fold status before V1 placement findings are published. Do not treat raw right-position as synonymous with sidebar unless validation supports that semantic interpretation.

# **34\. AIO Visibility Outcomes**

Do not use one binary visibility metric.

For every business/domain/page calculate separate outcomes:  
Presence: present anywhere.  
Mention: company named.  
Linked mention: named and clickable.  
Citation: company website/source used as evidence.  
Third-party corroboration: business mentioned while another site supplied the evidence.  
Main-answer presence: appears in primary AIO content.  
Right-position presence: appears in a right-position element.  
Above-fold presence: appears within the standardized first viewport.

Local-business-card presence: business appears in a validated structured AIO local-business-card surface.

Local-business-card rank/order: business position within the validated card module.

Local-card-only visibility: business appears in a local-business card while separately observed conventional AIO text-mention, direct business-website-link, business-site-citation, and embedded-GBP outcomes are absent.

&nbsp;

Embedded-GBP presence: business appears in a validated direct embedded Google Business Profile / Maps entity surface.

&nbsp;

Embedded-GBP above-fold presence: the validated embedded GBP surface appears within the standardized first viewport where geometry supports the determination.

&nbsp;

Embedded-GBP destination type: classify the primary observed destination/action separately, including website, google\_maps, google\_business\_profile, google\_searchviewer, call, directions, booking, other\_google, other\_web, none, or unknown.

&nbsp;

Embedded-GBP-only visibility: business appears in a direct embedded GBP surface while separately observed conventional AIO text mention, direct business-website link, business-site citation, and local-business-card outcomes are absent. Embedded GBP presence does not automatically count as a citation or source.

Do not create a composite AIO Visibility Score in V1. Preserve and model the raw visibility outcomes separately. If a composite index is ever explored later, its weights must be empirically justified, versioned, reversible to the underlying components, and never treated as a substitute for source, entity, destination, placement, or persistence outcomes.

# **35\. Persistence and Volatility Metrics**

For each page/domain/business calculate citation persistence:  
weeks\_cited / weeks\_observed.

For each query calculate:  
AIO trigger persistence  
new citations  
lost citations  
retained citations  
weekly citation churn

AIO local-business-card module prevalence

businesses appearing in AIO local-business cards

local-business-card ↔ Local Pack overlap

local-card-only visibility rate

AIO embedded-GBP surface prevalence

businesses appearing in direct embedded GBP surfaces

embedded GBP ↔ Local Pack overlap

embedded-GBP-only visibility rate

local-card ↔ embedded-GBP surface distribution  
business recommendation churn

For answer volatility calculate:  
answer\_changed  
semantic\_change\_score  
citation\_change\_rate  
business\_change\_rate

This makes the project longitudinal rather than a collection of screenshots.

&nbsp;

Transition-event interpretation should classify at minimum: first gain, loss, regain, persistence, mention-to-link upgrade, link-to-mention downgrade, citation gain/loss, business/page replacement within the same query, local-card gain/loss, local-card business swap, local-card rank/order change, local-card destination change, embedded-GBP gain/loss/regain, embedded-GBP persistence, embedded-GBP action/destination change, embedded-GBP-only visibility change, and local-card ↔ embedded-GBP surface transition. These events create natural longitudinal comparison windows. For each event, compare the entity's valid pre-transition state with its post-transition state and, where applicable, compare the incoming entity with the outgoing entity using the same temporally aligned signal families. The purpose is not to assume causation, but to identify which observable changes consistently precede, accompany, or follow AIO transitions.

# **36\. Social Citation Analytics**

Dashboard and research outputs should support:  
social citation share  
social citations per AIO  
social citations per query  
social citations by platform  
social citations by industry  
social citations by intent  
social citations by market tier  
social citations by week

Key questions:  
Does Reddit dominate recommendation searches?  
Does YouTube dominate how-to/informational local searches?  
Is LinkedIn disproportionately used for professional services?  
Are Facebook business pages direct sources?  
Does Google use social content to validate local business recommendations?

# **37\. Brand Corroboration Graph**

Build relationships between businesses and third-party sources that mention or support them.

Conceptual graph:  
BUSINESS → mentioned/supported by → SOURCE  
AIO → mentions BUSINESS  
AIO → cites SOURCE

Example:  
Joe’s Plumbing is mentioned in the AIO, while Yelp is cited.  
The system should preserve that Yelp served as third-party corroboration rather than incorrectly labeling Joe’s website as the source.

Over time, this can create a brand corroboration graph showing which directories, social platforms, forums, publishers, and local media sources repeatedly support specific businesses.

# **38\. Enrichment Scheduling**

Event-driven enrichment policy:

SERP/AIO/citations/company mentions/AIO local-business-card modules and cards/direct embedded GBP surfaces/organic/local results: monthly for the Full Panel; weekly only for the fixed Research Sentinel

newly discovered pages/entities: queue immediately after discovery

page/content embeddings and classifications: first processing plus content change only

domain/page authority and approved backlink/link histories: MONTHLY for the regular Full Panel population with global economic-unit deduplication and shared-data reuse; the Research Sentinel retains the approved lightweight weekly link monitoring plus targeted deeper inspection when an event or Analysis Specification Contract requires it

GBP/review/update state: baseline plus the approved incremental/change-aware refresh logic. Direct social collection is selective and evidence/fanout/Analysis-Specification-Contract driven rather than a universal 90-day refresh. Q\&A remains disabled unless separately validated and authorized.

NAP/citation footprint and full site inventory: baseline once; use hashes/diffs and refresh only on change/staleness/transition needs, with low-frequency sampled reconciliation

source/entity classifications: first discovery plus versioned/manual corrections

AIO production spatial collection: all valid coordinates in the fixed 9-point AIO geometry. Additional coordinates/devices/provider-rendering tests beyond production are permitted only on bounded subsets defined by an explicit experiment version.

&nbsp;

An unchanged monthly full-panel and weekly Sentinel AIO/SERP still creates a new immutable observation, but it should normally create no duplicate full enrichment. When a cited/mentioned business or page is swapped, enrich the new entity if needed and selectively refresh only fast-moving signals for the outgoing/incoming entities that are required for transition analysis. The governing model is baseline enrichment \+ cache reuse \+ incremental updates \+ event-triggered refresh \+ bounded low-frequency reconciliation. Section 65 is authoritative for orchestration and temporal rules.

&nbsp;

# **39\. AIO-Specific Reuse Requirements**

Canonical entity, content, embedding, signal, and provider-request reuse is governed by the Unified Platform PRD. AIO-specific requirement: monthly full-panel and weekly Sentinel AIO citations, mentions, destinations, cards, and embedded-GBP observations must reference the shared canonical entities/assets while preserving their immutable AIO observation context. Repeated AIO appearances do not independently authorize duplicate domain metrics, page crawls, embeddings, GBP enrichment, review retrieval, or other shared purchases.

# **40\. AIO Queue Requirements**

The parent Unified Platform PRD is authoritative for the durable collection queue, idempotency, retries, priority mechanics, economic-unit deduplication, and shared worker orchestration. This section retains only AIO-specific queue requirements.

&nbsp;

AIO jobs must preserve AIO query/observation context and must not block the permanent monthly full-panel and weekly Sentinel AIO collection on downstream enrichment. Shared queue fields and mechanics are inherited from the parent.

&nbsp;

Priority ordering must protect scheduled raw AIO collection first—monthly Full Panel and weekly Research Sentinel—then parsing/entity resolution/control selection, then time-sensitive enrichment, followed by slower enrichment and derived-feature/backfill work.

&nbsp;

SERP collection must never block on crawling, embeddings, social collection, backlink enrichment, GBP enrichment, or downstream analysis. See Section 65 for the current field list, job types, worker responsibilities, priority tiers, and failure handling.

&nbsp;

# **41\. AIO Execution Requirements**

Deployment/service topology is governed by the Unified Platform PRD. AIO requires logical separation of permanent SERP/AIO collection from downstream parsing/enrichment so provider or semantic-processing failures cannot prevent preservation of the monthly full-panel and weekly Sentinel AIO observations.

Suggested structure:  
/apps  
  collector  
  worker  
  dashboard

/packages  
  database  
  dataforseo  
  embeddings  
  crawler  
  normalization  
  analysis  
  classifiers  
  strategy-evidence

Railway can initially host a scheduler/collector, background worker, and API/dashboard service, then split workloads as volume grows.

# **42\. GitHub Repository Structure**

Recommended repository:

/local-aio-research  
  /config  
    industries.yaml  
    cities.yaml  
    query-templates.yaml  
    experiment.yaml  
  /apps  
    collector/  
    worker/  
    dashboard/  
  /packages  
    database/  
    dataforseo/  
    embeddings/  
    crawler/  
    analysis/  
    normalization/  
    classifiers/  
    strategy-evidence/  
  /migrations  
  /tests  
  /docs  
    methodology.md  
    schema.md  
    validation.md  
    strategy-evidence.md

Research configuration belongs in Git so methodology changes are auditable.

# **43\. AIO Storage Requirements**

Shared relational, vector, content-asset, and object-storage responsibilities are inherited from the Unified Platform PRD. AIO-specific normalized observations and derived tables must point to shared raw/content/canonical records rather than duplicating large payloads or reusable text.

# **44\. Data Retention and Immutability**

Never overwrite:  
SERP observations  
AIO answers  
citations  
company appearances  
historical metric/content snapshots  
material research-finding evidence versions  
client intervention records and measured intervention outcomes

Canonical records such as domains, pages, and businesses may update current metadata, but historical snapshots remain immutable. Research findings and client recommendations may have a current status/pointer, but material evidence or recommendation changes must create a new version/superseding record rather than rewriting the historical decision state.

# **45\. Error Handling**

Every external interaction should record status, attempt count, last error, and next retry.

Retry transient network failures, rate limits, provider 5xx responses, and timeouts with exponential backoff/jitter.

Do not endlessly retry malformed requests or permanent invalid-parameter errors.

Failed monthly full-panel observations plus weekly Sentinel observations should remain represented as failed records rather than disappearing from the dataset.

# **46\. AIO Cost Attribution Requirements**

Use the parent Unified Platform PRD api\_usage/cost-ledger model as the authoritative cost-accounting schema. At minimum, record provider, endpoint/Actor, run\_id, job\_id, entity type/id, request count, returned records, token usage where applicable, provider-reported cost when available, estimated cost, currency, and collected\_at.

&nbsp;

Track separate spend for SERP/AIO collection, backlinks, Business Data/GBP, On-Page/website retrieval, any approved selective social collector, semantic/embedding providers, external-review providers, storage, and Railway/Supabase infrastructure where measurable.

&nbsp;

Dashboard metrics should include cost this week/month, cost per primary query, cost per AIO observed, cost per newly enriched entity/page, provider-level spend, and budget-versus-plan. Soft/hard budget alerts and per-provider collection caps are defined in Section 65\.

&nbsp;

The collection/enrichment system should make variable research cost observable from production usage rather than relying on static PRD estimates.

&nbsp;

# **47\. Dashboard Requirements**

Top-level KPIs:  
queries collected  
AIO prevalence \= successful observed searches with AIO / successful observed searches eligible for prevalence analysis  
AIO prevalence week-over-week  
total citations  
unique citation domains  
unique cited URLs  
AIO source-presence rate by source/site type  
citation share by source/site type  
unique-domain share by source/site type  
AIO source-presence rate by page/content type  
citation share by page/content type  
Google-property source/citation share versus open-web share  
businesses mentioned  
businesses directly linked  
social citation share  
citation churn

AIO local-business-card module prevalence

businesses appearing in AIO local-business cards

local-business-card ↔ Local Pack overlap

local-card-only visibility rate

AIO embedded-GBP surface prevalence

businesses appearing in direct embedded GBP surfaces

embedded GBP ↔ Local Pack overlap

embedded-GBP-only visibility rate

local-card ↔ embedded-GBP surface distribution

Filters:  
date  
industry  
city  
state  
market tier  
query intent  
query family  
query geography type (geo\_neutral / explicit\_city / near\_me)  
coordinate cohort where applicable  
device  
source/site type  
page/content type  
Google property vs open web  
social platform

Core reports:  
AIO prevalence overall and by industry, city/market, market tier, intent, query family, geography cohort, period, and later device  
source/site-type composition: AIO source-presence rate, citation share, unique-domain share, unique-page share, and citations per AIO by source type  
page/content-type composition using the same presence/share metrics  
Google-property versus open-web sourcing report  
source-type × content-type matrix and cross-tabs by industry, intent, geography cohort, query family, market tier, placement, and time  
source/content-type persistence, gain/loss, and transition report  
geo-neutral vs explicit-city vs near-me matched-family comparison  
absolute percentage-point AIO lift by geography variant  
relative AIO lift by geography variant  
week-over-week prevalence and lift trends  
coordinate-sensitivity subset report  
citation leaders  
citation winners/losers  
citation persistence  
social citation report  
organic overlap  
Maps overlap  
authority/link/anchor analysis  
site topical-footprint analysis  
GBP/review/post analysis  
semantic similarity analysis  
business mention vs direct-link analysis  
placement analysis  
source/entity corroboration analysis

local entity surface analysis: local-business cards vs direct embedded GBP, Local Pack overlap, destination/action mix, card-only/GBP-only visibility, and surface transitions  
strategy-evidence findings by evidence level/classification and applicability scope, once sufficient evidence exists  
client opportunity gaps, recommendation confidence, proxy risk, and Observe/Test/Implement/Scale/Maintain state when the strategy layer is operational  
client intervention tracking and measured outcome/evidence changes when interventions have been recorded

# **48\. Statistical Analysis**

Primary modeling outcomes must match the research question rather than defaulting to citation alone. Initial binary outcomes can include:  
aio\_present \= 1/0 for query-level AIO prevalence  
page\_or\_source\_cited \= 1/0 among eligible candidate/control pages  
aio\_business\_mentioned \= 1/0  
aio\_business\_directly\_linked \= 1/0  
aio\_business\_cited \= 1/0

aio\_business\_local\_card\_present \= 1/0

aio\_business\_embedded\_gbp\_present \= 1/0

&nbsp;

Additional models may address placement, persistence/churn, source selection, content/source-type selection, AIO local-business-card inclusion/rank/order, direct embedded GBP inclusion/persistence/destination/action outcomes, local-card ↔ embedded-GBP surface switching, and transition events. Preserve the distinction among source visibility, entity visibility, and destination visibility throughout modeling.

Potential predictor families include:  
organic rank and organic visibility  
domain/page authority, referring domains, backlinks, anchor profile, and link context  
raw site size and Site Topical Footprint  
page/query/AIO semantic relevance and targeted passage similarity  
source/site type, page/content type, social platform, and third-party corroboration  
Maps/local rank, Maps geographic share of voice, and distance/proximity  
GBP categories/profile attributes, reviews, review velocity/relevance, and GBP posts; Q\&A only if separately validated and authorized  
discovered NAP citations, NAP consistency, off-site mentions, and service × geography corroboration  
social presence, activity, engagement, and topical relevance  
external review ecosystem and business/entity longevity  
schema/entity consistency and website freshness  
source-overlap/co-occurrence/entity-graph features  
industry, market size, query intent, query\_geo\_type, coordinate cohort, device, and time

Start with interpretable models appropriate to the outcome, such as logistic regression for binary outcomes and paired/matched descriptive models for query-family comparisons. Later consider mixed-effects/fixed-effects models, survival/persistence/transition models, and predictive models such as random forest or gradient boosting where they add research value. Statistical significance or predictive accuracy alone must never determine the Strategy Evidence Framework classification; Section 68 requires effect magnitude, uncertainty, replication, controls, applicability, longitudinal evidence, proxy risk, and actionability to remain separate.

The goal is explanation first, not merely predictive accuracy. Geo-neutral, explicit-city, and near-me observations must retain query\_geo\_type and query\_family\_id. Report the three cohorts separately and as matched-family contrasts before interpreting pooled models or interaction terms. For AIO prevalence, report both absolute percentage-point differences and relative lift, with geo-neutral as the default reference condition unless a research question specifies another contrast.

&nbsp;

As longitudinal history accumulates, add transition-centered and within-entity analyses in addition to cross-sectional winner-versus-control models. Useful designs include pre/post windows around first gain, loss, regain, or visibility-type changes; incoming-versus-outgoing entity comparisons for the same query; within-business/page change models that absorb stable entity characteristics; lagged predictor analysis to test whether signal changes tend to occur before AIO transitions; persistence analysis to distinguish durable gains/losses from one-week churn; and transition hazard/survival-style models when sample size supports them. Interpret these as temporal associations unless an intervention or stronger causal design exists.

# **49\. Statistical Caveats**

Observations are not independent. The same domains, businesses, treatments, and coordinates can recur across monthly Full Panel waves and weekly Sentinel waves. Statistical models must preserve that repeated-measures structure and cohort/cadence identity.

Analysis must eventually account for clustering/repeated measures by domain, query, query family, industry, city, and time. Matched geography variants within the same query\_family\_id are deliberately related observations and should not be treated as independent. Otherwise statistical significance can be overstated.

Separate exploratory findings from causal claims. The platform is primarily observational unless specific interventions are later designed. A signal changing before an AIO gain is stronger temporal evidence than a simple cross-sectional correlation, but it still does not prove that the signal caused the gain. Common causes, Google-system changes, market-wide shifts, seasonality, query changes, measurement timing, and other confounders may explain both the signal change and the AIO transition. Report lead/lag timing, sample sizes, uncertainty, persistence, and comparison-group behavior when interpreting transition findings.

# **50\. Example Research Outputs**

The system should eventually support defensible statements such as:  
• Geo-neutral, explicit-city, and near-me variants of the same underlying query family exhibit measurably different AIO prevalence, business selection, or citation behavior.  
• Adding a city modifier or near-me wording produces a measurable absolute and/or relative AIO lift for some query families, and that lift changes over time.  
• Recommendation queries trigger AIO substantially more often than some pure service query classes.  
• A meaningful share of businesses mentioned by AIO are supported by third-party sources rather than their own websites.  
• Organic position correlates with citation probability, but semantic similarity remains predictive after controlling for rank and authority.  
• Reddit or YouTube account for a measurable share of social/community citations in specific intent classes.  
• Linked company mentions have different predictors from unlinked entity mentions.  
• Recommendation-style AIOs rely on a measurably different mix of source/site types and page/content formats than direct-service queries.  
• Google-owned properties account for a measurable share of local AIO sourcing in some geography/query cohorts, while other cohorts rely more heavily on open-web sources.  
• A research finding can be strongly explanatory yet remain non-actionable or high in proxy risk, in which case it should inform benchmarking/model interpretation rather than automatically becoming a client task.

• AIO local-business cards can select a business set and ordering that only partially overlaps the traditional Local Pack, allowing the platform to test whether this surface represents distinct local-entity selection rather than a simple rendering of Maps rank.

• Google-hosted local-card/searchviewer destinations can be measured separately from business-website destinations so Google-owned entity surfaces are not misclassified as ordinary open-web citations.

Additional longitudinal outputs should eventually support defensible statements such as:  
• Businesses that gained AIO visibility showed a measurable increase/decrease in a given signal during the preceding N weeks relative to their own earlier baseline and/or matched controls.  
• When Business B replaced Business A for the same query, the two entities differed in specific time-varying signals before or around the transition.  
• A signal change commonly preceded AIO gains by one or more observation periods, while another signal tended to move only after visibility changed.  
• Some gains were transient one-week events while others persisted for multiple weeks; durable gains were associated with a different pre-transition profile than temporary gains.  
• Mention-only visibility sometimes progressed to direct-link/citation visibility, allowing the platform to study factors associated with visibility upgrades rather than only first appearance.  
• The same business can serve as its own historical comparison, helping separate stable business characteristics from variables that actually changed near the transition.

&nbsp;

Any numerical examples used during product planning are placeholders until the dataset produces actual estimates.

# **51\. MVP Scope and Build Gates**

Section 65 contains the authoritative implementation phase sequence. This section defines the V1 launch gates and study-scope checkpoints so there is only one detailed implementation roadmap.

&nbsp;

Gate 1 — Bounded end-to-end engineering pilot

Build the minimum end-to-end pipeline using the current AIO contract. The post-reconciliation pilot protocol governs final pilot size; the current recommended starting scope is 3 industries × 5 markets. Within selected pilot cells, collect the approved 10-condition × 9-point AIO design subject to structural exclusions, preserve raw responses, parse AIO text/citations/entities/destinations plus any observed local-business-card or embedded-GBP surfaces, and record completeness, cost, provider, parser, and error telemetry. The pilot validates engineering/observability and must not tune methodology toward interesting outcomes.

&nbsp;

Gate 2 — SERP and placement validation

Manually validate approximately 100 SERPs across geo-neutral, explicit-city, and near-me cohorts. Freeze definitions for AIO presence, citations, inline/direct links, company mentions, validated AIO local-business-card modules/cards and direct embedded GBP surfaces, their provider mappings and destination/action normalization, position/geometry, above-fold status, query-family matching, and coordinate handling before publishing V1 findings.

&nbsp;

Gate 3 — Monthly Full Panel production expansion

After pilot acceptance, expand to the 25-industry × 50-market monthly AIO Full Panel using exactly 10 approved conditions × the fixed 9-point AIO geometry, for a maximum 112,500 pre-water-exclusion observations per monthly wave. Keep literal query treatments, coordinates, exclusions, provider settings, and methodology version frozen within the collection version. The fixed Research Sentinel remains the separate weekly monitoring layer.

&nbsp;

Gate 4 — Matched controls and enrichment

Create page/business controls from the same SERP/local environment, then add authority/link metrics, site topical footprint, GBP/reviews/posts and provisionally validated Q\&A where authorized, NAP/entity corroboration, social/external review data, backlinks/anchor context, and other approved V1 enrichments.

&nbsp;

Gate 5 — Semantic and longitudinal analysis

Add embeddings/classification, temporally valid feature generation, winner-vs-control comparisons, cadence-appropriate descriptive/effect-size analysis for monthly Full Panel and weekly Sentinel observations, and later repeated-measures/persistence modeling as history accumulates.

&nbsp;

Gate 6 — Additional bounded geography/device validation

The 9-point AIO geometry is already the permanent production spatial panel. Any coordinates beyond those nine, alternate devices, or provider/rendering sensitivity tests must be bounded, explicitly versioned validation experiments. They do not redefine the production geometry or authorize a return to the retired one-primary-coordinate architecture.

&nbsp;

Gate 7 — Dashboard and cadence-aware reporting

Produce versioned dashboards and reports from the analysis-ready dataset. Weekly reporting must be clearly scoped to the fixed Research Sentinel; Full Panel reporting is monthly. Where approved conditions support valid matched query-form contrasts, report those separately alongside source/site-type and content-type composition, spatial variation, transitions, persistence, and cadence-appropriate changes.

&nbsp;

Gate 8 — Strategy Evidence Layer after sufficient history

Create versioned research\_findings records and apply the Section 68 evidence hierarchy, applicability, actionability, proxy-risk, and confidence framework only after data quality and sample history support it. Early findings should remain Exploratory or Directional unless the evidence justifies a higher classification. Client opportunity outputs must trace to underlying research findings and must not move to Implement or Scale merely because a correlation is statistically significant. Intervention tracking may begin when the agency actually acts on a research-informed recommendation.

&nbsp;

The detailed build order, worker architecture, job dependencies, temporal rules, QA, reporting implementation, and strategy-layer integration are defined in Section 65\.

&nbsp;

# **52\. Success Criteria**

The platform succeeds when it can reliably answer:  
What percentage of observed local-intent searches trigger AIO overall, and how does that percentage vary by industry, city/market, market tier, intent, query family, geography type, period, and later device?  
What types of local searches produce AIO?  
What source/site types and page/content types does Google use in local AIOs, and what are their AIO source-presence rates, citation shares, unique-domain/page shares, and persistence over time?  
How does source/content composition differ by industry, intent, geography cohort, query family, market tier, placement, and time?  
How much local AIO sourcing comes from Google-owned properties versus the open web?  
When AIO composition changes, which source/content types enter, leave, or persist, and do source-mix changes accompany business/page visibility transitions?  
How do geo-neutral, explicit-city, and near-me formulations change AIO prevalence for the same underlying service/intent?  
What is the absolute percentage-point and relative AIO lift from geo-neutral → explicit-city, geo-neutral → near-me, and explicit-city → near-me?  
How do those lifts change week over week and over longer periods?  
How sensitive are selected near-me results to searcher coordinates?  
What sources does Google repeatedly trust?  
Which businesses receive entity visibility?  
Which businesses receive direct clickable destinations?  
Where within the AIO does that visibility occur?  
How much do rankings, links, authority, anchor/link context, raw site size, and topical footprint matter?  
How much do Maps/local prominence, proximity, GBP categories, reviews, and GBP posts matter, and does Q\&A add measurable value if the validation study authorizes it?  
How much does semantic relevance matter across websites, reviews, social content, GBP posts, and off-site mentions?  
How important are Reddit, YouTube, LinkedIn, Facebook, TikTok, Nextdoor, and other social/community sources?  
How important are NAP/entity corroboration, external reviews, schema/entity consistency, business longevity, and source/entity co-occurrence?  
How often do structured AIO local-business-card modules appear, which businesses do they select and rank, what destinations/actions do they expose, and how do they overlap with traditional Local Pack/Maps results and other AIO visibility forms?

How often do direct embedded GBP surfaces appear, which businesses receive that visibility, what fields/actions/destinations are exposed, how often SearchViewer or other Google-hosted destinations are used, how much embedded-GBP selection overlaps Local Pack and local-business-card selection, and how often embedded GBP is the business's only observed AIO visibility form?

How persistent or volatile are these patterns over time?  
What changed before a business/page gained, lost, regained, upgraded, or downgraded AIO visibility?  
When one business/page replaces another for the same query, how did their temporally aligned signals differ before and around the transition?  
Which signal changes tend to lead AIO transitions, which coincide with them, and which tend to follow them?  
Which conditions are associated with durable gains/losses versus temporary AIO churn?  
Can within-entity longitudinal comparisons explain visibility changes better than cross-sectional winner-only comparisons?  
Which findings are sufficiently robust, replicated, applicable, actionable, and low enough in proxy risk to influence client strategy?  
For a specific client, where does its current state materially differ from applicable matched competitors and AIO-visible benchmarks?  
Should an identified client opportunity currently be Observed, Tested, Implemented, Scaled, or Maintained based on the evidence and client gap?  
When a research-informed intervention is implemented, do subsequent target outcomes and comparison groups strengthen, weaken, or refine the underlying finding?

# **53\. Explicit Non-Goals for V1**

Do not initially build:  
a polished public SaaS  
multi-user accounts and billing  
hundreds of industries  
every US city  
mobile and desktop for every query  
daily collection  
opaque AI-generated “SEO scores”  
complex machine-learning prediction before enough historical data exists  
automatic SEO recommendations presented as causal truth or generated without the Strategy Evidence Framework in Section 68

Priority: collect clean, comparable, longitudinal research data first.

# **54\. Core Data Model**

Conceptual hierarchy:

EXPERIMENT  
→ QUERY  
→ SERP OBSERVATION  
→ AI OVERVIEW  
→ AIO ELEMENT  
→ CITATION / COMPANY APPEARANCE / LOCAL BUSINESS CARD MODULE / EMBEDDED GBP SURFACE  
→ PAGE  
→ DOMAIN

Parallel relationships:  
SERP → organic results / local results / AIO elements  
QUERY → query family / geography type / fixed coordinate  
AIO → citations / business mentions / direct destinations / local-business-card modules / embedded GBP surfaces

LOCAL BUSINESS CARD MODULE → cards → BUSINESS

EMBEDDED GBP SURFACE → BUSINESS  
BUSINESS → GBP entity / Maps results / reviews / GBP posts / provisionally validated Q\&A  
BUSINESS → social profiles/content / external review profiles / NAP citations / off-site mentions  
BUSINESS → distance/proximity and geographic Maps-prominence features  
PAGE → content / page metrics / embeddings/chunks  
DOMAIN → authority/backlinks/anchors / Site Topical Footprint / schema/entity evidence  
BUSINESS ↔ SOURCE / BUSINESS ↔ BUSINESS → corroboration and co-occurrence graphs  
BUSINESS × QUERY × OBSERVATION DATE → temporally valid analysis features  
ANALYSIS DATASETS → versioned RESEARCH FINDINGS → CLIENT STRATEGY RECOMMENDATIONS → CLIENT INTERVENTIONS → measured outcome/evidence feedback

# **55\. Most Important Architectural Principle**

The platform must preserve three different forms of visibility:

1\. Source visibility  
Google uses a website/page as evidence for the AIO.

2\. Entity visibility  
Google mentions or recommends a company/business by name.

3\. Destination visibility  
Google gives the company/business a direct clickable link.

Examples:  
Source visibility: NO  
Entity visibility: YES  
Destination visibility: NO  
This occurs when a business is recommended but a third party such as Yelp supplies the citation.

Source visibility: YES  
Entity visibility: YES  
Destination visibility: YES  
This occurs when Google directly cites/links the business website while also naming the business.

These should never be collapsed into one boolean field.

&nbsp;

AIO local-business cards and direct embedded Google Business Profile / Maps entity surfaces are presentation surfaces layered on top of this model, not additional fundamental visibility forms. Either can confer entity visibility and may confer destination visibility through a website, Google Maps/Business Profile, Google SearchViewer, call/directions/booking action, or another target. SearchViewer belongs to destination classification, not source classification or presentation-surface classification. Source visibility should be marked only when a source/citation relationship is separately observed.

# **56\. End-State Research Asset**

After 6–12 months, the platform should hold hundreds of thousands of controlled local-search observations connecting query intent and geography type, fixed search coordinates, AIO presence, citations, company mentions, direct links, organic/Maps visibility, proximity, GBP/review/post signals, page/domain authority, backlinks/anchor context, Site Topical Footprint, social activity/content, NAP and off-site entity corroboration, external review evidence, schema/entity consistency, source/entity graphs, semantic similarity, and historical persistence.

The end goal is not simply to answer “How do I rank in AIO?” It is to build an empirical model of how Google constructs local recommendations in generative search: what it retrieves, which brands it trusts, which sources it uses to corroborate those brands, when it provides direct links, how placement changes, and which traditional/local/semantic signals correlate with those decisions over time. Once findings accumulate sufficient evidence, Section 68 governs how those findings are translated into client strategy so research conclusions, actionability, applicability, uncertainty, proxy risk, and intervention outcomes remain explicit rather than being collapsed into generic SEO advice.

# **57\. Business NAP Citation & Entity Corroboration Discovery**

The platform should add a lightweight citation-discovery layer for AIO-visible businesses and matched non-visible competitor businesses. For this research, a discovered NAP citation is defined operationally as a third-party indexed page containing a sufficiently strong match to the business’s name, address, phone number, website, or a combination of those identifiers. This is a comparative research metric, not a claim to have discovered every citation on the web.

&nbsp;

Discovery methodology

When a new business is resolved, generate a standardized set of ordinary Google searches using combinations such as:

• exact business name \+ phone number

• exact phone number

• exact business name \+ street address

• exact address \+ phone number

• business name \+ city \+ state

• business name \+ website/domain for broader entity corroboration

Avoid expensive search operators such as site:, intext:, or intitle: unless a later experiment specifically requires them. The same query methodology, result depth, location assumptions, and confidence rules must be applied to every business so citation-footprint comparisons remain consistent.

&nbsp;

Citation confidence

Do not treat every search result containing the business name as a traditional citation. Score the evidence found on each page using:

name\_found

phone\_found

address\_found

website\_found

city\_state\_found

name\_match

phone\_match

address\_match

website\_match

&nbsp;

Recommended confidence classes:

High confidence: name \+ phone; name \+ exact address; or phone \+ exact address.

Medium confidence: name \+ city \+ website; name \+ partial address; or another combination strongly suggesting the same entity.

Low confidence: business name alone or otherwise ambiguous entity evidence.

V1 strict citation metrics should count only high-confidence discovered NAP citations. Medium- and low-confidence results should remain stored for broader entity-corroboration analysis and later validation.

&nbsp;

Table: business\_citations

Recommended fields:

id

business\_id

source\_domain\_id

source\_page\_id

source\_url

citation\_type

business\_name\_found

address\_found

phone\_found

website\_found

city\_state\_found

name\_match

address\_match

phone\_match

website\_match

confidence\_class

nap\_consistency\_score

is\_structured\_directory

is\_social\_profile

is\_review\_platform

is\_local\_directory

is\_industry\_directory

is\_news\_or\_editorial

first\_seen\_at

last\_checked\_at

&nbsp;

Business-level derived metrics

Calculate at minimum:

discovered\_nap\_citation\_count

unique\_nap\_citation\_domains

high\_confidence\_citation\_count

entity\_mention\_count

unique\_entity\_mention\_domains

citation\_source\_diversity

citation\_authority\_distribution

name\_consistency\_rate

address\_consistency\_rate

phone\_consistency\_rate

overall\_nap\_consistency

&nbsp;

Citation source diversity should preserve source classes rather than treating all citations equally. Use the global source/site taxonomy from Section 19 as the primary cross-platform classification so citation, AIO-source, and corroboration analyses remain compatible. NAP-specific subtypes such as major/local/industry directory, chamber/association, or structured business listing may be preserved as secondary attributes rather than creating an incompatible parallel source taxonomy.

&nbsp;

Query-visible corroboration

The system should separately measure whether third-party pages corroborating a business are themselves visible in the organic results for the exact research query. For every business/query observation, derive fields such as:

serp\_corroborating\_domains

serp\_corroborating\_urls

highest\_corroborating\_organic\_position

citation\_domain\_in\_serp

citation\_url\_in\_serp

citation\_organic\_position

citation\_is\_aio\_source

This enables testing whether first-page corroboration density predicts AIO business visibility more strongly than the business’s total discovered citation footprint.

&nbsp;

Research questions

The citation layer should support questions such as:

• Do businesses with more discovered NAP citation domains receive AIO mentions more frequently?

• Does citation-source diversity predict AIO visibility?

• Does NAP consistency correlate with business mentions or direct links?

• Are high-authority citations more predictive than raw citation quantity?

• Do citations from source classes Google frequently uses in AIO have greater predictive value?

• Does first-page corroboration density predict AIO recommendations?

• Are entity mentions without complete NAP data independently associated with AIO visibility?

&nbsp;

Refresh strategy

NAP discovery should not run weekly for every known business. Run the discovery workflow when a business is first seen, cache and deduplicate the results, and run it for newly discovered businesses thereafter. Refresh established citation footprints only when change/transition evidence, analysis-specific staleness requirements, or bounded low-frequency reconciliation justify it. Quarterly reconciliation may be used for selected samples or layers when useful, but it is not an automatic full-universe refresh. Citation pages and domains should use the same canonical page/domain registries as the rest of the platform.

&nbsp;

Cost strategy

Use the DataForSEO Standard Queue and ordinary quoted/NAP searches where practical. As a planning example, if 2,000 unique businesses require four discovery searches each, 8,000 top-10 SERPs would add roughly $4.80 at a $0.0006-per-SERP baseline. Collecting three 10-result pages for each search would be roughly $14.40. At 10,000 known businesses, a four-search top-10 full reconciliation pass would be approximately $24 at that baseline; this is a cost-sensitivity example, not a required quarterly cadence. These are planning estimates only; actual provider cost must be recorded through api\_usage and validated against current provider pricing and returned task costs.

&nbsp;

Integration with the research model

Add citation variables to business-level modeling alongside Maps rank, review count/rating, business-site authority and referring domains, organic rank, site size, semantic relevance, social mentions, and third-party corroboration. Preserve citation quantity, citation quality/diversity, NAP consistency, and query-visible corroboration as separate predictors rather than collapsing them into one citation score.

&nbsp;

The platform should refer to these metrics as “discovered NAP citations” rather than “total citations,” because search-based discovery cannot guarantee exhaustive coverage of every citation on the web. The research value comes from applying the same repeatable discovery methodology to every business.

&nbsp;

# **58\. HISTORICAL / VALIDATION-ONLY — Business Social Presence, Activity & Engagement Layer**

Status: SUPERSEDED AS A UNIVERSAL PRODUCTION COLLECTION LAYER. The concepts, candidate fields, temporal controls, and research questions in this section are retained for provenance and for explicitly approved bounded validation/Analysis Specification Contracts. Current production social/community evidence comes from the shared Brand \+ Service \+ Location Top-50 Google evidence layer. Direct social-profile/activity collection is selective and may occur only when justified by observed evidence, observed fanout/source behavior, or an approved analysis/validation contract. Apify is not a governing production provider assumption.

&nbsp;

Research objective

This layer should allow the study to test whether social presence, activity, audience size, engagement, recency, consistency, or platform mix correlate with AIO business mentions, direct clickable links, citation visibility, placement, or persistence after controlling for traditional SEO, local SEO, citation, authority, and semantic variables.

&nbsp;

Social profile discovery and identity resolution

VALIDATION/ANALYSIS ONLY: when a bounded approved direct-social study requires official-profile data, discover and verify the required profiles only for the pre-specified eligible sample/platforms. Profile discovery and profile verification remain separate steps. Do not universally enumerate social profiles for every resolved production business.

&nbsp;

Potential verification evidence includes:

• social profile linked from the business website

• business website/domain linked from the social profile

• matching business name

• matching phone number

• matching address or city/state

• matching website/domain

• matching branding or organization details

• profile links found in Google/business listing data

&nbsp;

Assign a profile\_match\_confidence value and preserve the underlying matching evidence. Primary statistical analysis should use only high-confidence business-to-profile matches unless a research question explicitly examines uncertain matches.

&nbsp;

Table: business\_social\_profiles

Recommended fields:

id

business\_id

platform

profile\_url

handle

profile\_name

profile\_match\_confidence

match\_evidence\_json

is\_verified\_by\_platform

followers

following

subscriber\_count

page\_likes

profile\_created\_at

profile\_discovered\_at

first\_seen\_at

last\_checked\_at

provider

provider\_actor

provider\_actor\_version

&nbsp;

Social content snapshots

VALIDATION/ANALYSIS ONLY: if an approved contract requires direct social content, collect only the bounded recent sample specified by that contract rather than a business's entire history. The former 10–30-post suggestion is historical planning guidance, not a universal V1 target.

&nbsp;

Table: social\_post\_snapshots

Recommended fields:

id

business\_id

business\_social\_profile\_id

platform

post\_id

post\_url

published\_at

post\_type

caption\_or\_text

likes

comments

shares

replies

views

reposts

saves\_when\_available

other\_engagement\_json

collected\_at

provider

provider\_actor

provider\_actor\_version

&nbsp;

Preserve raw provider fields when practical because engagement metrics differ by platform and can change over time. Do not force every platform into an identical metric schema if the underlying platform does not expose equivalent signals.

&nbsp;

Derived social activity metrics

Calculate business/platform metrics such as:

posts\_last\_7d

posts\_last\_30d

posts\_last\_90d

days\_since\_last\_post

median\_days\_between\_posts

active\_weeks\_last\_90d

posting\_consistency\_rate

median\_posts\_per\_week

&nbsp;

Derived audience and engagement metrics

Calculate where supported:

followers\_at\_snapshot

subscribers\_at\_snapshot

median\_likes\_recent\_posts

median\_comments\_recent\_posts

median\_shares\_recent\_posts

median\_views\_recent\_video\_posts

median\_total\_interactions\_recent\_posts

mean\_total\_interactions\_recent\_posts

engagement\_rate\_by\_followers

video\_engagement\_rate

view\_to\_follower\_ratio

comment\_to\_like\_ratio

&nbsp;

Prefer medians for many descriptive comparisons because social engagement distributions can be highly skewed by occasional viral posts. Preserve raw values so alternate definitions can be calculated later.

&nbsp;

Cross-platform business metrics

At the business level derive:

confirmed\_social\_platform\_count

active\_social\_platform\_count

platforms\_present

platforms\_active\_last\_30d

largest\_audience\_platform

total\_known\_followers\_or\_subscribers\_by\_platform

social\_activity\_breadth

social\_engagement\_breadth

&nbsp;

Do not blindly sum followers across platforms into a single audience metric because audiences can overlap and platform metrics are not directly equivalent. Platform-specific values should remain available for analysis.

&nbsp;

Temporal alignment

Social metrics must be time-aware. A social snapshot collected after an AIO observation should not be used as though it represented the business's social state before that observation. For each SERP/AIO observation, join to the nearest valid social snapshot at or before the observation date, subject to a defined maximum staleness window.

&nbsp;

Useful temporally aligned predictors include:

posts\_30d\_before\_aio

posts\_90d\_before\_aio

days\_since\_last\_post\_at\_aio

followers\_at\_or\_before\_aio

median\_engagement\_recent\_posts\_at\_aio

median\_video\_views\_recent\_posts\_at\_aio

active\_platform\_count\_at\_aio

&nbsp;

This supports analysis of whether recent activity preceding an AIO observation correlates with visibility rather than using future data to explain past outcomes.

&nbsp;

Business social presence versus social AIO corroboration

Maintain a strict distinction between two concepts:

1\. Business social presence: the business itself maintains an official profile and publishes content.

2\. Social AIO corroboration: Google cites or relies on social/community content when constructing an AIO or discussing the business.

&nbsp;

A business may be highly active on Instagram but never have Instagram cited by AIO. Conversely, a business may have little direct social activity while third-party Reddit discussions, YouTube videos, Facebook community posts, or other social sources corroborate the business. These must remain separate variables.

&nbsp;

Third-party social discussion

Where feasible, later phases should separately measure third-party social discussion of the business rather than only first-party business profiles. Potential variables include:

third\_party\_social\_mention\_count

unique\_social\_authors\_or\_channels

unique\_social\_platforms\_mentioning\_business

recent\_social\_mentions\_30d

recent\_social\_mentions\_90d

social\_mentions\_cited\_by\_aio

social\_mentions\_visible\_in\_organic\_serp

&nbsp;

This can test whether public discussion and community corroboration are more predictive of AIO recommendations than the business's own posting activity.

&nbsp;

Historical Apify implementation example — NOT a production provider requirement

HISTORICAL PROVIDER EXAMPLE: earlier planning considered Apify for bounded direct-social collection. Current production does not authorize universal Apify collection. If an approved bounded social study uses Apify or another provider, identity still comes from the canonical business graph; preserve raw provider output where practical, normalize supported fields, and record provider/version/cost provenance.

&nbsp;

Add job types such as:

discover\_social\_profiles

verify\_social\_profile

refresh\_social\_profile

collect\_recent\_social\_posts

calculate\_social\_metrics

&nbsp;

Selective direct-social collection failures must not block scheduled AIO collection. Social enrichment, when explicitly justified by evidence/fanout/analysis requirements, runs asynchronously through the existing jobs architecture and does not create a universal recurring social crawl.

&nbsp;

Refresh cadence

HISTORICAL / VALIDATION-ONLY cadence examples — NOT production scheduling:

profile discovery: first business discovery, then retry unresolved profiles periodically

profile verification: first discovery and when identity evidence changes

profile audience metrics: refresh for new/transitioning entities, when the last snapshot exceeds the analysis staleness threshold, or in a bounded reconciliation sample

recent post/activity collection: incremental for new posts on new/transitioning/active entities; otherwise reuse cached content until staleness or reconciliation rules require a check

high-value experimental subset: optionally weekly

historical post backfill: one-time only when explicitly required

&nbsp;

Any bounded direct-social study must pre-specify cadence from its estimand, required temporal resolution, and cost. No universal direct-social cadence is authorized, and outcome-driven post hoc frequency changes are not permitted.

&nbsp;

Cost controls

For any approved bounded direct-social study, track realized cost by provider/economic unit/platform/business/profile/record as applicable; deduplicate and reuse unchanged content. Historical Apify-specific cost assumptions are not part of the current production budget.

&nbsp;

Research questions

The social layer should support questions such as:

• Are AIO-mentioned businesses more likely to maintain active social profiles than non-mentioned competitors?

• Does the number of confirmed social platforms correlate with AIO visibility?

• Does posting frequency correlate with AIO mentions, direct links, or persistence?

• Does recency of social activity matter?

• Does audience size remain predictive after controlling for business size, authority, reviews, and organic visibility?

• Does engagement matter more than follower count?

• Are video views or video activity associated with AIO visibility in particular industries or query intents?

• Which platforms, if any, show the strongest relationship with AIO business visibility?

• Is first-party social activity less or more predictive than third-party social discussion/corroboration?

• Do social signals interact with NAP citation breadth, review prominence, Maps visibility, or organic rank?

&nbsp;

Control-group requirement

If an approved analysis tests direct-social variables as explanatory factors, the Analysis Specification Contract must define an unbiased eligible comparison/control sample and apply the same authorized direct-social methodology to cases and controls. Do not collect direct-social data only for AIO winners, and do not turn this conditional requirement into universal production enrichment.

&nbsp;

Integration with statistical modeling

Add social predictors alongside organic rank, Maps rank, reviews, domain/page authority, referring domains, site size, discovered NAP citations, citation diversity, NAP consistency, semantic similarity, and third-party corroboration. Preserve platform-specific variables and raw activity/engagement measures instead of collapsing them immediately into a proprietary social score.

&nbsp;

Potential dependent outcomes include:

aio\_business\_mentioned

aio\_business\_directly\_linked

aio\_business\_above\_fold

aio\_business\_right\_position

aio\_business\_cited

aio\_business\_persistence

&nbsp;

Methodological caution

This remains observational research. A correlation between social activity and AIO visibility would not establish that posting more frequently causes AIO visibility. Social activity may proxy for business size, brand prominence, marketing maturity, customer activity, or other confounders. The platform should collect enough covariates to test whether social variables remain associated with AIO outcomes after controlling for these factors.

&nbsp;

# **59\. HISTORICAL / VALIDATION-ONLY — Direct Social Content & Semantic Analysis**

Status: CANDIDATE ANALYSIS LAYER ONLY. Direct social-content text is not universally collected in current production. When an approved bounded analysis, observed fanout/source pathway, or validation experiment requires direct social content, preserve the underlying text and analyze it under the rules below. The shared Top-50 Google evidence layer remains the routine production social/community evidence source.

&nbsp;

Collection scope

For the pre-specified sample of an approved direct-social analysis, and only where publicly available and supported by the authorized collector, candidate fields include:

• YouTube video title, description, hashtags/tags, and transcript/captions when available

• Instagram caption/description, hashtags, mentions, and media type

• TikTok caption/description, hashtags, mentions, and video metadata

• Pinterest pin title, description, board/context, and destination URL

• Facebook post text and link metadata

• LinkedIn post text and link metadata

• X post text and referenced URLs

• comparable textual fields from additional supported platforms

&nbsp;

Also preserve publish date/time, content URL, outbound URLs, mentioned entities/handles, language, and platform-specific content subtype. Store this subtype as platform\_content\_type; it must not be confused with the global page/content taxonomy in Section 21\. Raw source text should be retained rather than storing only an embedding, summary, or model-generated label.

&nbsp;

Table: social\_content

Recommended fields:

id

business\_id

business\_social\_profile\_id

platform

content\_id

content\_url

published\_at

platform\_content\_type

title

description

caption

transcript

hashtags\_json

mentions\_json

outbound\_urls\_json

language

text\_normalized

text\_hash

raw\_storage\_path

first\_collected\_at

last\_collected\_at

provider

provider\_actor

provider\_actor\_version

&nbsp;

Gemini semantic analysis layer

When direct social content is validly collected under an approved contract, semantic processing uses the shared platform pipeline. The authorized collector supplies raw public content; the shared content-asset layer preserves it; embeddings are reused by content hash/model version; local vector calculations provide similarity/relevance; and an approved LLM may be used only for unresolved structured semantic fields under the parent gating policy. The LLM is never the source of the underlying social data.

&nbsp;

Embeddings

Generate embeddings for normalized social content and preserve embedding model, version, content hash, vector, and creation date. Do not regenerate an embedding when the source text hash is unchanged.

&nbsp;

Table: social\_content\_embeddings

Recommended fields:

id

social\_content\_id

embedding\_model

embedding\_version

content\_hash

vector

created\_at

&nbsp;

Calculate similarity features such as:

query\_social\_similarity

aio\_social\_similarity

website\_social\_similarity

query\_social\_max\_similarity

query\_social\_mean\_top5\_similarity

aio\_social\_max\_similarity

&nbsp;

Structured Gemini extraction/classification

Use a strict structured-output schema to classify/extract fields such as:

primary\_topic

secondary\_topics

service\_or\_product\_discussed

problem\_or\_need\_addressed

location\_mentions

local\_relevance

informational\_vs\_promotional\_intent

question\_answered

entities\_mentioned

brands\_or\_products\_mentioned

firsthand\_business\_experience\_signal

content\_summary

&nbsp;

Store model/version and prompt/schema version so classifications can be reproduced or rerun later. Raw social content remains authoritative; Gemini classifications are derived features that may be replaced as methodology improves.

&nbsp;

Business × query semantic features

Aggregate post-level data into query-specific business features. Useful variables include:

relevant\_social\_posts\_30d

relevant\_social\_posts\_90d

relevant\_social\_posts\_365d

local\_relevant\_social\_posts

exact\_service\_posts

problem\_relevant\_social\_posts

query\_social\_max\_similarity

query\_social\_mean\_top5\_similarity

aio\_social\_max\_similarity

days\_since\_relevant\_social\_post

relevant\_youtube\_videos

relevant\_tiktok\_posts

relevant\_instagram\_posts

relevant\_pinterest\_pins

relevant\_facebook\_posts

relevant\_linkedin\_posts

&nbsp;

This allows the study to distinguish a business that merely posts frequently from one that consistently publishes content closely related to the specific services/problems for which Google surfaces it.

&nbsp;

Three social dimensions

Preserve three separate dimensions rather than collapsing them into one score:

1\. Presence/activity — which platforms the business uses, how recently it posted, and how consistently it publishes.

2\. Engagement/prominence — audience size, views, likes, comments, shares, replies, and other supported interaction metrics.

3\. Content/topic relevance — what the business publishes and how semantically aligned that content is with target queries, AIO answers, locations, and service/problem topics.

&nbsp;

Research questions

This layer should support questions such as:

• Are AIO-visible businesses publishing more query-relevant social content than comparable non-visible businesses?

• Does topical social footprint predict AIO mentions after controlling for posting frequency and audience size?

• Is query-to-social semantic similarity associated with direct links or above-fold visibility?

• Does recent publication of relevant social content matter more than total historical volume?

• Are locally explicit social posts more strongly associated with local AIO visibility?

• Does YouTube topical coverage behave differently from Instagram, TikTok, Pinterest, Facebook, or LinkedIn coverage?

• Does social content semantic relevance remain predictive after controlling for website semantic relevance, organic rank, Maps rank, reviews, backlinks, and discovered NAP citations?

&nbsp;

Cost and collection strategy

The Gemini component should be inexpensive relative to social-data collection. As a planning scenario, 2,000 businesses × 3 confirmed profiles per business × 20 recent pieces of content per profile yields approximately 120,000 social content records. If average analyzable text is approximately 100 tokens per record, that represents roughly 12 million input tokens before longer transcripts or descriptions. At previously reviewed Gemini embedding rates, embedding short-form text at this scale would generally be only a few dollars; structured classification should also remain relatively inexpensive when outputs are kept compact. YouTube transcripts can materially increase token volume and should be measured separately.

&nbsp;

HISTORICAL COST PROVENANCE ONLY: the former $150–$500 Apify/social backfill scenario was developed for the superseded universal-social concept. It is non-operative for current production. Any bounded direct-social study must estimate and record its own current provider cost.

&nbsp;

HISTORICAL COST PROVENANCE ONLY: the former $25–$100/month social-collection, $1–$5/month semantic-processing, and $150–$500 backfill ranges are not current production budgets. Any authorized bounded study records actual provider usage/cost; current platform planning is governed by the Unified parent and measured telemetry.

&nbsp;

V1 should generally collect engagement counts but not scrape and semantically analyze every individual user comment. Full comment collection can dramatically increase record volume and is not required to answer the initial research questions. A later controlled experiment can analyze comment text if evidence suggests third-party conversation quality or sentiment is important.

&nbsp;

Incremental and event-driven processing

Use content\_id/content\_url plus text\_hash to prevent unnecessary repeated analysis. When a known post is encountered again with unchanged text, reuse its embedding/classification while updating mutable engagement snapshots separately. When text changes, create a new content version or regenerate derived semantic features according to the versioning policy.

&nbsp;

Temporal alignment

As with social engagement metrics, semantic features used to explain an AIO observation must come only from content published on or before that SERP observation. Derived variables such as relevant\_social\_posts\_90d must be calculated relative to the observation date, not the current date.

&nbsp;

Control-group requirement

If an approved Analysis Specification Contract tests direct-social content as an explanatory variable, apply the same authorized collection/processing methodology to its pre-specified case and comparison/control population. Without a defensible comparison design, results remain descriptive. This conditional rule does not authorize universal social-content collection.

&nbsp;

# **60\. Google Business Profile, Reviews & Local Entity Analysis**

Because this study focuses on local-intent AIO visibility, Google Business Profile and Maps-derived entity signals are a major research layer. AIO-visible businesses and controlled non-visible competitors must resolve through the shared canonical local-entity model and reuse shared GBP, review, update/post, and Maps-related signals. Q\&A remains disabled for production unless the bounded validation study authorizes it.

&nbsp;

Business-to-GBP resolution

For each canonical business, attempt to resolve and store the corresponding Google entity identifiers and profile evidence, including:

google\_place\_id

cid

google\_maps\_url

business\_name

address

phone

website

latitude

longitude

primary\_category

&nbsp;

Resolution confidence should be stored so ambiguous businesses can be excluded from primary analysis. Matching evidence may include name, address, phone, website/domain, coordinates, and other canonical business fields.

&nbsp;

GBP profile snapshots

Create a time-aware profile snapshot rather than overwriting the latest profile state.

&nbsp;

Table: gbp\_profile\_snapshots

Recommended fields:

id

business\_id

snapshot\_date

google\_place\_id

cid

business\_name

primary\_category

additional\_categories\_json

description

address

phone

website

latitude

longitude

claimed\_status

rating

review\_count

hours\_json

special\_hours\_json

attributes\_json

place\_topics\_json

photo\_count\_when\_available

profile\_fields\_json

provider

collected\_at

&nbsp;

Derived GBP/profile variables may include:

primary\_category\_match

additional\_category\_count

query\_category\_relevance

profile\_description\_present

profile\_description\_query\_similarity

attribute\_count

hours\_present

website\_present

phone\_present

claimed\_profile

profile\_completeness\_features

&nbsp;

Do not create an arbitrary GBP optimization score in V1. Preserve individual observable variables first so their relationships with AIO outcomes can be measured independently.

&nbsp;

Google reviews

Collect a bounded review sample for AIO-visible businesses and controlled competitors. A practical initial target is approximately the 100 most recent reviews per business, with incremental collection of new reviews thereafter.

&nbsp;

Table: google\_reviews

Recommended fields:

id

business\_id

google\_place\_id

review\_id

review\_url\_when\_available

rating

review\_text

review\_timestamp

reviewer\_name\_or\_id\_when\_available

owner\_response\_text

owner\_response\_timestamp

collected\_at

text\_hash

provider

&nbsp;

Derived review metrics should include:

review\_count\_at\_snapshot

average\_rating\_at\_snapshot

reviews\_last\_30d

reviews\_last\_90d

reviews\_last\_365d

review\_velocity\_30d

review\_velocity\_90d

review\_velocity\_365d

days\_since\_last\_review

owner\_response\_rate

median\_owner\_response\_time\_when\_available

rating\_distribution

&nbsp;

Review semantic analysis

Preserve raw review text and use the same Gemini semantic infrastructure developed for website and social content. Generate embeddings and/or structured extraction only when review text exists.

&nbsp;

Potential extracted fields include:

service\_mentioned

problem\_or\_need\_mentioned

location\_mentioned

review\_topic

sentiment

query\_relevance

firsthand\_experience\_signal

entities\_mentioned

&nbsp;

Useful business × query features include:

review\_query\_max\_similarity

review\_query\_mean\_top10\_similarity

relevant\_reviews\_90d

relevant\_reviews\_365d

service\_specific\_review\_count

problem\_specific\_review\_count

location\_specific\_review\_count

review\_topic\_coverage

recent\_relevant\_review\_velocity

&nbsp;

This distinction is important: review quantity and review relevance should be modeled separately. A business with many generic reviews may differ from a business whose customers repeatedly describe the exact services, problems, and locations represented by the query.

&nbsp;

Place topics

Where DataForSEO exposes Google place\_topics or comparable review-derived topics, preserve them directly as Google-derived local entity signals. Treat these separately from Gemini-derived review topics. This allows comparison between Google's visible topic representation and the project's independent semantic classification.

&nbsp;

GBP updates/posts

Collect public Google Business Profile updates where available. Section 63 is authoritative for the final gbp\_updates storage schema, deduplication rules, embeddings/classification, semantic features, and incremental collection policy. The fields immediately below are a conceptual subset and must not override Section 63\.

&nbsp;

Table: gbp\_updates

Recommended fields:

id

business\_id

update\_id\_or\_url

published\_at

text

url

image\_urls\_json

update\_type

text\_hash

collected\_at

provider

&nbsp;

Derived metrics may include:

updates\_last\_30d

updates\_last\_90d

updates\_last\_365d

days\_since\_last\_update

update\_frequency

update\_query\_similarity

relevant\_updates\_90d

&nbsp;

Preserve update text so it can be embedded and analyzed using the same semantic methodology as social content.

&nbsp;

Google Questions & Answers

Where available, collect public Google Q\&A associated with the business.

&nbsp;

Table: google\_business\_qa

Recommended fields:

id

business\_id

question\_id

question\_text

question\_timestamp

answer\_text

answer\_timestamp

answer\_source\_when\_available

collected\_at

text\_hash

provider

&nbsp;

Potential derived features include:

question\_count

answered\_question\_count

answer\_rate

recent\_questions\_365d

query\_question\_similarity

relevant\_question\_count

service\_specific\_questions

problem\_specific\_questions

&nbsp;

No strategic value is assumed for Q\&A before validation. Any historical question corpus must be labeled according to the validated surface/status and must not be treated as evidence of current GBP functionality.

&nbsp;

Photos and media

Where reliably available, preserve profile-level media counts and useful metadata such as photo count, recent media activity, and media types. V1 does not require computer-vision analysis of every GBP photo. Photo-level image analysis should remain a later controlled experiment unless early evidence suggests profile media is strongly associated with AIO visibility.

&nbsp;

Maps and local visibility integration

Join GBP/entity data with the existing local\_results observations. For every business × query observation, preserve variables such as:

maps\_present

maps\_position

local\_pack\_position

primary\_category\_match

rating\_at\_observation

review\_count\_at\_observation

review\_velocity\_before\_observation

relevant\_review\_count\_before\_observation

place\_topic\_query\_overlap

&nbsp;

This allows the study to test whether AIO business selection is explained by traditional local prominence, GBP relevance, review evidence, or signals beyond the local pack.

&nbsp;

Temporal alignment

All GBP/review/update/Q\&A predictors must be aligned to the SERP/AIO observation date. Do not use reviews, updates, rating changes, or profile changes that occurred after an AIO observation to explain that earlier result. Join each observation to the nearest valid snapshot at or before the SERP date and calculate rolling review/update variables relative to that date.

&nbsp;

Control-group requirement

Do not collect GBP data only for businesses mentioned or cited by AIO. Apply the same resolution, profile, review, update, Q\&A, semantic-analysis, and refresh methodology to a controlled set of competing businesses from the same query/local environment. This is required to determine whether GBP variables actually distinguish AIO winners from businesses Google did not surface.

&nbsp;

Research questions

This layer should support questions such as:

• Are AIO-mentioned businesses more likely to have a particular primary or secondary category configuration?

• Does category/query relevance predict AIO visibility after controlling for organic rank?

• Do rating and review count predict mentions, direct links, or persistence?

• Does review velocity matter independently of total review count?

• Are query-relevant reviews more predictive than raw review quantity?

• Does owner-response behavior correlate with AIO visibility?

• Do Google place topics overlap more strongly with target queries for AIO-visible businesses?

• Does GBP update activity or update topical relevance correlate with AIO visibility?

• If Q\&A validation authorizes an active or historical research layer, does its topical coverage add measurable explanatory value under the validated status?

• How much AIO business selection can be explained by Maps/local-pack prominence versus website, citation, social, and semantic signals?

&nbsp;

Statistical integration

Add GBP/local predictors alongside organic rank, domain/page authority, referring domains, site size, discovered NAP citations, NAP consistency, social presence, social engagement, social content relevance, website semantic relevance, and third-party corroboration.

&nbsp;

Potential dependent outcomes remain:

aio\_business\_mentioned

aio\_business\_directly\_linked

aio\_business\_above\_fold

aio\_business\_right\_position

aio\_business\_cited

aio\_business\_persistence

&nbsp;

Cost model

GBP/review analysis should be relatively inexpensive compared with social scraping. Using the DataForSEO Standard Queue pricing reviewed during PRD development as planning assumptions:

• GBP profile information: approximately $0.0015 per profile

• GBP updates: approximately $0.0015 base plus $0.00075 per 10 updates

• Google reviews: approximately $0.00075 per 10 reviews

• Google Q\&A \[DISABLED for current production unless separately validated and explicitly authorized by a methodology amendment\]: approximately $0.00075 per 10 questions

&nbsp;

Illustrative initial backfill for 2,000 businesses:

• 2,000 GBP profiles: approximately $3.00

• approximately 10 GBP updates per business: approximately $4.50

• approximately 100 reviews per business / 200,000 reviews total: approximately $15.00

• Q\&A: generally a small incremental amount depending on available question volume

&nbsp;

Plan approximately $20–$40 under the prior 2,000-business GBP/review/post backfill sensitivity scenario; Q\&A is excluded from required backfill unless validation separately authorizes it. This is a sensitivity estimate, not a mandatory launch population. After initial collection, avoid repeatedly downloading the same historical reviews and updates. Incrementally collect new records and refresh mutable profile snapshots.

&nbsp;

A reasonable ongoing planning range is approximately $5–$20/month after initial backfill under prior assumptions, depending on business growth, refresh cadence, review volume, post activity, and authorized semantic processing; Q\&A contributes no recurring production cost unless validation authorizes it. These values are planning estimates only. Provider pricing can change, and actual DataForSEO/Gemini usage and returned costs must be captured in api\_usage and reconciled periodically.

&nbsp;

Refresh strategy

CURRENT PROGRESSIVE REFRESH GUIDANCE:

GBP/entity resolution: first business sighting

GBP profile snapshot: first resolution, then on transition/staleness/reconciliation triggers rather than automatic monthly refresh for every business

review initial backfill: first resolution, approximately 100 recent reviews

new review collection: incremental for new/transitioning/active entities; otherwise only when stale or selected for reconciliation

GBP updates: incremental/event-triggered where practical; do not refetch unchanged history

Google Q\&A: no recurring production cadence until the bounded Q\&A validation study authorizes active-signal status; historical-only or retired status is permitted.

place topics: with profile refresh

high-value experimental subset: optionally weekly

&nbsp;

Methodological caution

This is observational research. GBP completeness, review activity, review relevance, owner responses, and AIO visibility may all be influenced by underlying business prominence, marketing maturity, age, customer volume, or market size. Preserve the raw component variables and appropriate controls rather than interpreting correlation as causation.

&nbsp;

Consolidated budget reference

The GBP/review layer's incremental planning range is approximately $5–$20/month after initial backfill. The current consolidated all-in V1 budget is maintained in Section 67; this section should not be used as a standalone cumulative platform total.

&nbsp;

# **61\. Site-Wide Topical Footprint & Content Relevance**

Raw site size is not sufficient to characterize the content footprint of a business website. A 500-page website with only a small fraction of pages related to the target industry/service may represent a weaker topical corpus than a 50-page website where nearly every page is tightly related to the business's core services and locations. The platform should therefore measure site-wide topical composition separately from total page count.

&nbsp;

V1 lightweight methodology

Use a lightweight whole-site census based primarily on URL, title tag, and H1 rather than downloading and semantically analyzing the full body content of every page. This provides a scalable approximation of what topics the website intentionally covers while keeping crawl, storage, and Gemini costs low.

&nbsp;

For each discovered business domain:

1\. Discover indexable/meaningful URLs using sitemaps and crawler discovery.

2\. Collect canonical URL, URL path/slug, title tag, and H1 where available.

3\. Normalize and deduplicate URLs.

4\. Create a lightweight semantic representation from URL \+ title \+ H1.

5\. Reuse/create shared content-addressed embeddings for these representations; classify only unresolved research-required semantics under the parent LLM-gating policy.

6\. Aggregate page-level results into domain-, service-, location-, and query-level topical-footprint variables.

&nbsp;

This metric should be called Site Topical Footprint or a similarly precise term. It must not be labeled content quality because optimized titles/H1s do not prove that the underlying body content is high quality.

&nbsp;

Table: site\_page\_inventory

Recommended fields:

id

domain\_id

page\_id

url

canonical\_url

url\_path

title

h1

indexable\_when\_known

source\_sitemap

content\_type

first\_seen\_at

last\_seen\_at

last\_checked\_at

title\_h1\_hash

provider

&nbsp;

Where site\_page\_inventory stores content\_type, use the global Section 21 page/content taxonomy (or an explicitly mapped/versioned compatible subset) rather than creating a separate incompatible site-inventory taxonomy.

&nbsp;

Table: site\_page\_topic\_embeddings

Recommended fields:

id

site\_page\_inventory\_id

embedding\_model

embedding\_version

title\_h1\_hash

vector

created\_at

&nbsp;

Site-size and topical-footprint variables

Preserve raw size and relevant size separately. Potential domain-level variables include:

total\_discovered\_pages

total\_indexable\_pages\_when\_known

industry\_relevant\_pages

industry\_relevant\_percentage

service\_relevant\_pages

service\_relevant\_percentage

location\_relevant\_pages

location\_relevant\_percentage

service\_location\_relevant\_pages

off\_topic\_pages

off\_topic\_percentage

supporting\_topic\_pages

&nbsp;

Query-specific semantic variables

For each business/domain × research query, calculate the similarity distribution between the query and the site's lightweight page representations. Potential variables include:

site\_query\_max\_similarity

site\_query\_mean\_similarity

site\_query\_median\_similarity

site\_query\_top5\_mean\_similarity

site\_query\_top10\_mean\_similarity

query\_relevant\_page\_count

query\_relevant\_page\_percentage

&nbsp;

The system may also store counts above exploratory similarity thresholds, but threshold values such as 0.70, 0.75, or 0.80 should not be assumed meaningful before empirical calibration. Preserve raw similarities so thresholds can be selected from observed distributions.

&nbsp;

Industry, service, and location decomposition

Because the project studies local SEO, topical relevance should be decomposed rather than represented as one generic similarity score. Classify or measure coverage for:

• core industry

• specific service

• problem/need

• geography/location

• service \+ geography combinations

• supporting informational topics

• company/admin content

• unrelated/off-topic content

&nbsp;

Useful variables include:

industry\_relevant\_pages

service\_relevant\_pages

problem\_relevant\_pages

location\_relevant\_pages

service\_location\_relevant\_pages

supporting\_topic\_pages

industry\_relevance\_ratio

service\_relevance\_ratio

local\_relevance\_ratio

service\_location\_depth

off\_topic\_ratio

&nbsp;

Topical clustering

Where useful, cluster page embeddings to build an empirical topic map for each site. This can reveal whether a domain has deep coherent clusters around core services or whether a large page count is distributed across unrelated subjects. Store cluster assignments and cluster labels separately from the raw embeddings so clustering methodology can be rerun later.

&nbsp;

Potential outputs could characterize a site as having, for example, substantial clusters around water heaters, drain cleaning, emergency plumbing, leak detection, sewer repair, and local service pages versus a broader multi-industry site dominated by HVAC, electrical, solar, generic home improvement, or unrelated informational content.

&nbsp;

Two-stage semantic analysis

Use two distinct levels of content analysis:

Stage 1 — whole-site topical census: URL \+ title \+ H1 for as much of the meaningful site as practical. Use this to estimate topical breadth, depth, concentration, dilution, and query coverage.

Stage 2 — deep page analysis: retrieve full content and chunk/embed only strategically important pages, including AIO-cited pages, organic control pages, highly query-relevant candidate pages, and potentially a controlled random sample.

&nbsp;

This prevents the project from paying to fully process every word of very large websites while still allowing deep analysis of the pages most relevant to AIO selection.

&nbsp;

Research questions

This layer should support questions such as:

• Does relevant topical depth predict AIO visibility better than raw site size?

• Does raw site size remain predictive after controlling for relevant-page count?

• Do sites with a higher percentage of industry-relevant pages receive more AIO visibility?

• Is service-specific topical depth associated with visibility for service-specific queries?

• Does service \+ location content depth correlate with local AIO business selection?

• Is off-topic dilution negatively associated with AIO visibility after controlling for domain authority and site size?

• Do coherent topical clusters outperform large but diffuse content footprints?

• Does the relationship differ by industry, query intent, city size, or source type?

&nbsp;

Statistical integration

Model raw site size and topical footprint as separate predictors. For example:

aio\_visibility \~ total\_site\_pages \+ relevant\_page\_count \+ relevant\_page\_percentage \+ service\_relevant\_pages \+ location\_relevant\_pages \+ service\_location\_depth \+ off\_topic\_ratio \+ organic\_rank \+ Maps\_rank \+ reviews \+ domain/page authority \+ referring\_domains \+ NAP citations \+ social variables \+ semantic page relevance

&nbsp;

A particularly important test is whether the apparent effect of total site size weakens or disappears after relevant topical depth is introduced. This would indicate that a perceived large-site advantage may actually be a topical-depth advantage.

&nbsp;

Control-group requirement

Apply the same site inventory, title/H1 collection, embedding/classification, and topical-footprint methodology to AIO-visible businesses and controlled non-visible competitors. Do not analyze only cited domains.

&nbsp;

Refresh strategy

CURRENT CHANGE-DETECTION / INCREMENTAL WEBSITE GUIDANCE:

initial site inventory: first domain discovery

full lightweight topical census: first domain discovery

new URL detection: sitemap/diff checks for new/transitioning/stale domains; otherwise bounded low-frequency reconciliation

full inventory reconciliation: low-frequency and preferably sampled; run sooner only when change/transition evidence justifies it

embedding/classification: only for new or changed URL/title/H1 representations

deep full-content analysis: only for selected pages according to the existing page-analysis pipeline

&nbsp;

Use sitemap diffs, URL registries, and title\_h1\_hash values to avoid reprocessing unchanged pages.

&nbsp;

Cost model

CURRENT PROVIDER CORRECTION: website retrieval/scraping is planned through ScrapeOwl, using the least-expensive viable request mode first and escalating to JavaScript/premium-proxy modes only when necessary, wrapped in shared URL/domain/content-hash caching and change detection. The older DataForSEO On-Page per-page pricing examples below are historical planning provenance only and MUST NOT be used as the current website-scraping budget.

&nbsp;

HISTORICAL DATAFORSEO ON-PAGE COST EXAMPLES — NON-OPERATIVE:

• average 50 pages/site \= 100,000 pages ≈ $15

• average 100 pages/site \= 200,000 pages ≈ $30

• average 250 pages/site \= 500,000 pages ≈ $75

• average 500 pages/site \= 1,000,000 pages ≈ $150

These figures are preserved only to document earlier planning assumptions. Current realized ScrapeOwl request-mode usage, cache hits/misses, change-detection outcomes, and provider costs must be measured prospectively.

&nbsp;

Gemini analysis should remain relatively inexpensive because V1 embeds/classifies short URL \+ title \+ H1 representations rather than complete page bodies. Even hundreds of thousands of pages should generally add only a modest semantic-processing cost relative to crawling and social-data collection.

&nbsp;

Provision approximately $20–$150 for the initial site-topical-footprint backfill at the expected initial scale, with higher costs possible if the dataset contains unusually large domains. Ongoing incremental collection is expected to average approximately $5–$25/month depending on domain growth and refresh cadence.

&nbsp;

Avoid browser rendering by default. The browser-rendering pricing reviewed during PRD development is dramatically higher than the basic crawl and is unnecessary for most title/H1/URL collection. Use JavaScript/browser-rendered crawling only as a targeted fallback for sites where the basic crawler demonstrably fails to expose required metadata.

&nbsp;

Consolidated budget reference

The site-topical-footprint layer adds approximately $5–$25/month ongoing and approximately $20–$150 for the expected initial backfill. The current consolidated all-in V1 budget is maintained in Section 67\. Actual provider usage and returned costs must be recorded in api\_usage and reconciled against current pricing.

&nbsp;

Methodological caution

Title tags, URL slugs, and H1s provide a scalable approximation of topical coverage, not proof of body-content quality, originality, usefulness, or depth. The system should explicitly distinguish Site Topical Footprint from Page Content Quality/Relevance. Full-content analysis of cited/control pages remains necessary for research questions about actual page quality and passage-level semantic relevance.

&nbsp;

# **62\. Backlink Anchor Text & Link Context Analysis**

The platform should analyze not only backlink quantity, referring domains, and authority, but also how external websites link to each business/domain. Anchor-text composition may distinguish AIO-visible businesses from matched competitors and may reveal whether branded, keyword-bearing, naked-URL, generic, or contextually relevant links are associated with AIO visibility.

&nbsp;

Data source

Use DataForSEO Backlinks API as the primary source. The Anchors endpoint provides anchor text with backlink counts and related metrics, while detailed backlink records can provide the actual anchor plus referring URL/domain and contextual/link attributes. DataForSEO currently prices Backlinks API requests on a pay-as-you-go basis at approximately $0.024 per request plus $0.000036 per returned row, with up to 1,000 rows per request. A 1,000-row request is therefore approximately $0.06 under current pricing. Provider pricing must be treated as mutable and actual returned task costs must be recorded in api\_usage.

&nbsp;

Anchor classification

Preserve raw anchor text and classify it using deterministic rules first, with Gemini or another classifier only for ambiguous cases. Required analytical categories include:

• brand

• exact match

• partial match

• naked URL

• generic

• other/uncategorized

&nbsp;

Do not force every anchor into a single mutually exclusive category. Preserve boolean dimensions so an anchor such as “ABC Plumbing Phoenix” can be both branded and keyword-bearing.

&nbsp;

Recommended classification fields:

is\_brand

is\_exact\_match

is\_partial\_match

is\_naked\_url

is\_generic

is\_other

contains\_location

contains\_service\_term

contains\_business\_name

contains\_domain

&nbsp;

Table: backlink\_anchors

Recommended fields:

id

domain\_id

anchor\_text

anchor\_normalized

backlinks

referring\_domains\_when\_available

anchor\_rank

first\_seen

lost\_date

is\_brand

is\_exact\_match

is\_partial\_match

is\_naked\_url

is\_generic

is\_other

contains\_location

contains\_service\_term

classification\_version

snapshot\_date

provider

&nbsp;

Business/domain-level anchor metrics

Calculate both backlink-weighted and referring-domain-weighted distributions. Potential metrics include:

total\_anchor\_backlinks

unique\_anchor\_texts

brand\_anchor\_backlinks

brand\_anchor\_percentage

exact\_match\_anchor\_backlinks

exact\_match\_anchor\_percentage

partial\_match\_anchor\_backlinks

partial\_match\_anchor\_percentage

naked\_url\_anchor\_backlinks

naked\_url\_anchor\_percentage

generic\_anchor\_backlinks

generic\_anchor\_percentage

&nbsp;

Also calculate referring-domain versions wherever the underlying data supports reliable attribution:

brand\_anchor\_referring\_domains

exact\_match\_referring\_domains

partial\_match\_referring\_domains

naked\_url\_referring\_domains

generic\_anchor\_referring\_domains

&nbsp;

Referring-domain-weighted measures are important because thousands of repeated sitewide links from one domain should not be treated as equivalent to independent links from thousands of domains.

&nbsp;

Query-specific anchor relevance

Anchor classification should also be calculated relative to the specific research query/service/location rather than only a site's general target terms. For a query such as “emergency plumber phoenix,” derive variables such as:

query\_exact\_match\_anchor\_count

query\_partial\_match\_anchor\_count

query\_service\_anchor\_count

query\_location\_anchor\_count

query\_service\_location\_anchor\_count

query\_keyword\_anchor\_referring\_domains

&nbsp;

This allows the study to test whether anchor relevance to the exact AIO query is more predictive than overall keyword-rich anchor usage.

&nbsp;

Detailed backlink context

For a controlled subset or strategically important backlinks, use detailed DataForSEO backlink records to preserve contextual fields such as:

referring\_domain

referring\_url

target\_url

anchor

text\_pre

text\_post

dofollow/nofollow or link attributes

semantic/location fields when available

first\_seen

last\_seen/lost status

&nbsp;

Table: backlink\_context\_samples

Recommended fields:

id

domain\_id

page\_id\_when\_target\_resolved

referring\_domain\_id

referring\_url

target\_url

anchor\_text

text\_pre

text\_post

link\_attributes\_json

semantic\_location

is\_contextual\_content\_link

context\_text\_hash

snapshot\_date

provider

&nbsp;

Topical backlink context

For sampled links, combine anchor \+ surrounding text and optionally embed/classify the context. This creates a separate signal for whether a backlink is topically relevant even when the anchor itself is branded or generic. For example, a branded anchor embedded in an article about Phoenix water-heater repair should be distinguishable from the same branded anchor in a generic directory, footer, or unrelated page.

&nbsp;

Potential variables include:

context\_query\_similarity

context\_industry\_similarity

context\_service\_similarity

context\_location\_relevance

contextual\_link\_percentage

topically\_relevant\_referring\_domains

relevant\_context\_link\_count

&nbsp;

Anchor profile diversity and concentration

Preserve measures of anchor diversity/concentration rather than only category percentages. Potential features include:

unique\_anchor\_ratio

brand\_to\_keyword\_anchor\_ratio

anchor\_category\_entropy

top\_anchor\_share

top5\_anchor\_share

keyword\_anchor\_concentration

&nbsp;

These may help distinguish naturally diverse link profiles from profiles dominated by a small number of repeated keyword anchors.

&nbsp;

Research questions

This layer should support questions such as:

• Do AIO-visible businesses have different branded-anchor distributions than matched competitors?

• Are exact-match or partial-match anchors associated with AIO visibility after controlling for authority and referring-domain count?

• Is referring-domain anchor diversity more predictive than raw backlink-weighted anchor distribution?

• Are branded/naked anchors more strongly associated with persistent AIO business visibility?

• Does query-specific keyword anchor coverage correlate with AIO mentions or direct links?

• Are topically relevant contextual backlinks more predictive than anchor text alone?

• Does the relationship between anchor profile and AIO visibility differ by industry, city, query intent, or Maps prominence?

&nbsp;

Control-group requirement

Apply the same anchor retrieval, classification, and aggregation methodology to AIO-visible businesses and controlled non-visible competitors. Do not retrieve detailed anchor data only for cited businesses.

&nbsp;

Refresh strategy

CURRENT GOVERNING BACKLINK / ANCHOR CADENCE:

The regular/monthly Full Panel population retains MONTHLY approved backlink/link variables and histories, globally deduplicated by domain/URL/provider economic unit and reused when sufficiently fresh. This includes approved anchor-distribution variables where they are part of the methodology. The weekly Research Sentinel retains lightweight weekly link monitoring needed for Sentinel research, with targeted deeper inspection only when an event or Analysis Specification Contract requires it.

initial anchor snapshot: first domain enrichment

monthly anchor/link refresh: regular Full Panel, subject to shared-cache/provider-data reuse and economic-unit deduplication

detailed backlink-context sampling: initial enrichment plus targeted refreshes when analytically required

new/lost link analysis: approved Sentinel monitoring or targeted transition/Analysis Specification Contract work

Do not replace the monthly regular-population backlink cadence with quarterly-only collection.

&nbsp;

Use snapshot dates so anchor profiles can eventually be aligned with AIO observations without overwriting historical states.

&nbsp;

Cost strategy and estimated running cost

Current DataForSEO Backlinks API pricing reviewed during PRD development is approximately $0.024 per request plus $0.000036 per returned row. One request returning 1,000 rows is approximately $0.06.

&nbsp;

Illustrative initial anchor costs for 2,000 domains:

• 100 anchor rows/domain: roughly one request/domain, approximately $55.20 total ($48 request charges \+ $7.20 rows)

• 500 anchor rows/domain: roughly one request/domain, approximately $84 total ($48 request charges \+ $36 rows)

• 1,000 anchor rows/domain: approximately $120 total

&nbsp;

The 1,000-row maximum means domains requiring more than 1,000 rows require additional requests. However, V1 should generally avoid exhaustive extraction for very large domains. Use bounded anchor samples/distributions and targeted detailed backlink pulls.

&nbsp;

For ongoing operation, do not automatically refresh anchor distributions quarterly for the full domain set. Use transition/staleness triggers and bounded reconciliation samples as defined by the event-driven enrichment policy. A complete 2,000-domain pass remains useful as a cost-sensitivity reference—at up to 500 anchor rows/domain it would be roughly $84 under the planning assumption, and at 1,000 rows/domain roughly $120—but those full-pass amounts should not be treated as recurring quarterly spend unless an experiment explicitly schedules such a reconciliation.

&nbsp;

Detailed link-context analysis should be sampled rather than performed for every backlink. For example, an additional 100 detailed backlink rows per domain would cost roughly another $55 for a 2,000-domain full pass under current pricing. This can be limited to new domains, matched research subsets, or high-value links.

&nbsp;

Treat approximately $25–$50/month as a conservative layer-level sensitivity allowance rather than a required recurring anchor/link-context spend. Under the event-driven policy, actual steady-state cost should depend on the number of new, transitioning, stale-needed, and reconciliation-sampled domains. Initial backfill remains approximately $55–$120 depending on requested anchor depth. Actual usage belongs in api\_usage and the consolidated all-in planning envelope remains authoritative in Section 67\.

&nbsp;

Consolidated budget reference

The anchor/link-context layer has an initial expected 2,000-domain backfill of approximately $55–$120. Ongoing cost is event-driven and should not be inferred by automatically amortizing full-universe quarterly refreshes; approximately $25–$50/month is retained only as a conservative sensitivity allowance. The current consolidated all-in V1 budget is maintained in Section 67\.

&nbsp;

These are planning estimates only. DataForSEO changed pricing for selected APIs in July 2026, and provider pricing may change again. The implementation must record actual task/request cost in api\_usage and use observed production costs for future forecasting.

&nbsp;

Methodological caution

Anchor-text patterns are observational signals and may proxy for brand strength, link-building strategy, business age, directory presence, PR activity, sitewide links, or industry-specific linking behavior. Preserve raw anchor distributions and appropriate controls rather than interpreting any correlation as evidence that a particular anchor mix causes AIO visibility.

&nbsp;

# **63\. GBP Post Semantic Relevance & Embedding Analysis**

&nbsp;

Expand the existing GBP Updates work in Section 60 into a first-class semantic research layer. DataForSEO's My Business Updates endpoint can retrieve public Google Business Profile posts/updates for a resolved business using CID, Place ID, or business identity plus location/language. Returned update data can include plain text, post URL, image URL, author, publication date/timestamp, and links with URL and anchor text. DataForSEO recommends requesting depth in multiples of 10 because updates are processed and billed in blocks of 10\.

&nbsp;

Collection strategy

For every AIO-visible business and matched non-visible control business with a resolvable GBP:

1\. Resolve and preserve CID/Place ID through the existing GBP entity-resolution pipeline.

2\. Request the most recent GBP updates through DataForSEO My Business Updates.

3\. Initial V1 target: collect the most recent 20–50 available posts per business, with depth selected in multiples of 10\.

4\. Preserve the raw DataForSEO response in object storage.

5\. Normalize each post into the existing gbp\_updates table or a compatible normalized post table.

6\. Deduplicate posts using update ID/URL when available plus text\_hash.

7\. Reuse/create the shared content-addressed embedding for new or changed post text.

8\. Run structured LLM classification only for unresolved research-required fields that pass the parent deterministic/cache/vector gating policy.

9\. Calculate query-, AIO-, service-, problem-, and location-level semantic relevance.

10\. On later refreshes, process only newly discovered or changed posts wherever possible.

&nbsp;

GBP update storage

The existing gbp\_updates table should preserve at minimum:

id

business\_id

google\_place\_id

cid

update\_id\_or\_url

published\_at

text

post\_url

image\_urls\_json

links\_json

author\_when\_available

update\_type\_when\_available

text\_hash

first\_collected\_at

last\_collected\_at

provider

raw\_storage\_path

&nbsp;

Table: gbp\_update\_embeddings

Recommended fields:

id

gbp\_update\_id

embedding\_model

embedding\_version

text\_hash

vector

created\_at

&nbsp;

Gemini structured classification

For each GBP post, classify or extract where supported by the text:

primary\_topic

secondary\_topics

service\_or\_product

problem\_or\_need

location\_mentions

local\_relevance

informational\_vs\_promotional\_intent

question\_answered\_when\_applicable

entities\_mentioned

brands\_or\_products\_mentioned

content\_summary

&nbsp;

Store Gemini model, model version, prompt version, and output-schema version. The raw GBP post remains authoritative; model-generated labels are derived research features.

&nbsp;

Semantic similarity features

For each GBP post, calculate relevant embedding similarities such as:

query\_gbp\_post\_similarity

aio\_gbp\_post\_similarity

website\_gbp\_post\_similarity\_when\_useful

service\_gbp\_post\_similarity

location\_gbp\_post\_similarity

&nbsp;

For each business × query × AIO observation, derive temporally valid aggregate features such as:

gbp\_post\_max\_similarity

gbp\_post\_mean\_top5\_similarity

gbp\_post\_mean\_top10\_similarity

aio\_gbp\_post\_max\_similarity

relevant\_gbp\_posts\_30d

relevant\_gbp\_posts\_90d

relevant\_gbp\_posts\_365d

service\_relevant\_gbp\_posts\_90d

problem\_relevant\_gbp\_posts\_90d

location\_relevant\_gbp\_posts\_90d

service\_location\_relevant\_gbp\_posts\_90d

days\_since\_relevant\_gbp\_post

gbp\_posts\_last\_30d

gbp\_posts\_last\_90d

gbp\_posts\_last\_365d

days\_since\_last\_gbp\_post

gbp\_post\_frequency

gbp\_post\_consistency

&nbsp;

Similarity thresholds should not be treated as fixed truths in V1. Preserve raw similarity values and calibrate any relevant/not-relevant threshold empirically from observed distributions and manual validation samples.

&nbsp;

Core methodological distinction

Do not collapse GBP posting into one activity metric. Preserve at least three separate dimensions:

1\. GBP post activity — whether and how frequently the business posts.

2\. GBP post recency — how recently the business posted before the AIO observation.

3\. GBP post topical relevance — how closely recent posts align with the specific service, problem, location, research query, and/or AIO answer.

&nbsp;

This allows the research to test whether semantically relevant posting is associated with AIO visibility independently of posting frequency alone.

&nbsp;

Temporal alignment

For every AIO observation, use only GBP posts published at or before that observation. Features such as posts\_last\_90d, days\_since\_relevant\_gbp\_post, and query relevance must be calculated relative to the AIO observation timestamp. Never allow future posts to leak into historical observations.

&nbsp;

Control-group requirement

Collect and analyze GBP posts for AIO-visible businesses and matched non-visible competitor businesses using the same collection depth, refresh rules, embedding model, and classification methodology. Do not enrich only AIO winners.

&nbsp;

Research questions

This layer should support questions including:

• Are businesses with recent GBP posts more likely to appear in local AIO results?

• Is posting frequency associated with AIO visibility after controlling for Maps rank, reviews, website authority, citations, backlinks, social activity, and organic rank?

• Does semantic relevance of GBP posts predict AIO visibility better than raw posting frequency?

• Are service-specific posts associated with service-specific AIO selection?

• Are problem/need-specific posts associated with problem-oriented local queries?

• Does location-specific GBP content matter independently of service relevance?

• Does recent relevant posting matter more than historical posting volume?

• Does GBP post relevance remain predictive after controlling for website topical footprint and review-topic relevance?

• Is GBP post semantic similarity associated with direct business mentions, clickable links, citation inclusion, placement, or persistence across monthly full-panel observations plus weekly Sentinel observations?

&nbsp;

DataForSEO running cost

Current DataForSEO Standard Queue pricing for My Business Updates is $0.0015 to set a task plus $0.00075 per 10 updates. DataForSEO processes depth in blocks of 10, so request depths should generally be 10, 20, 30, 40, or 50 rather than arbitrary values.

&nbsp;

Illustrative initial backfill for 2,000 businesses:

10 posts/business: approximately $4.50

20 posts/business: approximately $6.00

30 posts/business: approximately $7.50

50 posts/business: approximately $10.50

&nbsp;

These estimates assume one task per business and Standard Queue pricing. Businesses with fewer available posts may return less data, while billing behavior should be verified from actual task cost fields during implementation.

&nbsp;

Ongoing DataForSEO cost should be very small. A hypothetical full 2,000-business depth-10 refresh would cost approximately $4.50 under the planning assumption, but V1 should not automatically run that refresh every month. Use incremental/event-triggered collection for new, changed, transitioning, or analysis-stale businesses plus bounded reconciliation samples. Provision approximately $2–$10/month for ongoing GBP-post retrieval at the initial scale as a planning allowance, with actual cost driven by triggered business count and captured in api\_usage.

&nbsp;

Gemini embedding cost

GBP posts are short text records, so embedding costs are expected to be negligible relative to most other collection layers. Current paid text pricing reviewed during PRD development is approximately $0.15 per 1M tokens for gemini-embedding-001 standard or $0.075 per 1M tokens in batch; Gemini Embedding 2 is approximately $0.20 per 1M text tokens standard or $0.10 per 1M in batch.

&nbsp;

Illustrative example: 2,000 businesses × 50 posts \= 100,000 posts. Even at an average of 100 text tokens per post, this represents approximately 10M embedding input tokens, or roughly $0.75–$2.00 depending on embedding model and batch/standard processing. Actual posts may be shorter or longer.

&nbsp;

Structured classification cost

Gemini structured classification adds some input/output-token cost beyond embeddings, but the records are short and classification should run only for new or changed posts. Provision approximately $1–$5 for an initial 100,000-post classification pass using a low-cost Gemini model and concise structured output, subject to the model selected at implementation time. Ongoing classification should generally be well below a few dollars per month at the initial scale.

&nbsp;

Layer-level budget

Recommended planning allowance:

initial GBP-post retrieval \+ embedding/classification backfill: approximately $5–$20 at the initial 2,000-business scale, depending primarily on requested history depth and classification configuration.

ongoing GBP-post retrieval \+ Gemini semantic processing: approximately $2–$12/month.

&nbsp;

Consolidated budget reference

The GBP-post semantic layer adds approximately $2–$12/month ongoing and approximately $5–$20 for initial retrieval/semantic backfill. The current consolidated all-in V1 budget is maintained in Section 67\.

&nbsp;

As with all provider estimates, record actual DataForSEO task costs and Gemini token usage in api\_usage and reconcile planning estimates against current provider pricing.

&nbsp;

# **64\. Additional Entity, Off-Site & Local Prominence Measurements**

&nbsp;

The following measurements should be added as complementary explanatory variables. These should remain separate raw/derived features rather than being collapsed into an arbitrary authority score.

&nbsp;

64.1 Mention Context & Off-Site Topical Relevance

Do not merely count off-site business mentions. Capture enough context to determine what the business is being mentioned for. Where available, store the source page title and surrounding paragraph/text window around the business mention, then use Gemini embeddings/classification to compare that context with the target industry, service, location, research query, and AIO answer.

&nbsp;

Potential variables:

offsite\_mention\_count

topically\_relevant\_mention\_count

locally\_relevant\_mention\_count

service\_relevant\_mention\_count

service\_location\_relevant\_mention\_count

mention\_query\_max\_similarity

mention\_query\_mean\_similarity

mention\_aio\_similarity

unique\_relevant\_mention\_domains

relevant\_mention\_percentage

&nbsp;

This distinguishes a business mentioned repeatedly in highly relevant local/service contexts from a business with the same number of mentions in unrelated contexts. Treat this as an off-site topical relevance/corroboration layer, not merely a citation count.

&nbsp;

64.2 Review Ecosystem Beyond Google

Extend review corroboration beyond Google where reliable public data can be collected. Candidate sources include Yelp, Facebook, BBB, Angi, Trustpilot, and industry-specific review platforms. V1 does not require scraping every review. Prioritize profile presence, total review count, rating, review recency, review velocity when derivable, and a controlled sample of review text for semantic analysis.

&nbsp;

Potential variables:

external\_review\_platform\_count

external\_review\_count\_by\_platform

external\_rating\_by\_platform

external\_reviews\_last\_90d/365d when available

days\_since\_latest\_external\_review

external\_review\_query\_similarity

external\_review\_service\_relevance

external\_review\_location\_relevance

cross\_platform\_review\_consistency

&nbsp;

Preserve platform-specific metrics separately because rating systems and review populations are not directly comparable across platforms.

&nbsp;

64.3 Business Age / Entity Longevity

Approximate how long the business/entity has existed using multiple observable proxies rather than assuming one source represents true business age. Candidate evidence includes domain registration/first-seen age where reliably obtainable, earliest discovered citation or web mention, oldest Google review, earliest social activity, oldest known GBP evidence, and business founding date when explicitly published by a reliable source.

&nbsp;

Potential variables:

domain\_age\_days

entity\_first\_seen\_days

days\_since\_earliest\_citation

days\_since\_earliest\_web\_mention

days\_since\_oldest\_google\_review

days\_since\_earliest\_social\_activity

published\_business\_age\_when\_known

longevity\_evidence\_count

&nbsp;

Keep each proxy separate so the analysis can test whether established entities have an AIO advantage independent of links, reviews, authority, and other prominence signals.

&nbsp;

64.4 Local Geographic Prominence / Maps Share of Voice

For a controlled subset of businesses/markets, measure geographic Maps visibility rather than relying only on Maps rank at one search coordinate. Run a standardized local grid around the market/business and calculate geographic visibility across grid points.

&nbsp;

Potential variables:

maps\_grid\_points\_checked

maps\_top3\_grid\_percentage

maps\_top10\_grid\_percentage

maps\_average\_rank

maps\_median\_rank

maps\_share\_of\_voice

maps\_visibility\_radius

maps\_geographic\_coverage

&nbsp;

Use a standardized grid design, radius, keyword, device/location methodology, and experiment version so observations are comparable. This can test whether AIO visibility correlates with broad metro-level Maps prominence rather than a single-coordinate local rank. Because grid collection can materially increase SERP/API volume, run this on a stratified subset initially rather than every business/query.

&nbsp;

64.5 Distance / Proximity

Store geographic distance from the standardized search coordinates or query-location centroid to each resolved business location. Calculate distance deterministically from stored latitude/longitude rather than paying for a separate API call.

&nbsp;

Potential variables:

distance\_to\_search\_point\_km

distance\_to\_city\_centroid\_km

distance\_to\_grid\_center\_km

business\_inside\_target\_city

business\_inside\_target\_radius

&nbsp;

This enables testing whether AIO business recommendations exhibit the same proximity bias seen in local search/Maps and whether proximity effects vary by query intent. For service-area businesses or businesses without a meaningful public storefront coordinate, preserve business type and location-confidence flags so distance is not overinterpreted.

&nbsp;

64.6 Schema / Entity Markup

On important business websites, record structured entity markup including LocalBusiness and Organization schema, sameAs, name, address, phone, URL, service-related schema, areaServed, review/aggregateRating markup when present, and other relevant entity properties.

&nbsp;

Potential variables:

has\_localbusiness\_schema

has\_organization\_schema

has\_sameas

sameas\_count

sameas\_matches\_discovered\_social\_profiles

schema\_name\_matches\_business

schema\_address\_matches\_gbp

schema\_phone\_matches\_gbp

has\_area\_served

area\_served\_matches\_target\_location

has\_service\_schema

schema\_service\_query\_relevance

entity\_schema\_consistency

&nbsp;

A particularly useful test is whether sameAs and other structured entity relationships correspond cleanly to the social profiles and business entities independently discovered by the platform.

&nbsp;

64.7 Website Content Freshness

Extend the Site Topical Footprint layer with freshness measurements for relevant pages. Where publication/modified dates can be reliably detected, measure the recency of the relevant topical corpus rather than only total site publishing activity.

&nbsp;

Potential variables:

relevant\_pages\_last\_30d

relevant\_pages\_last\_90d

relevant\_pages\_last\_365d

percentage\_relevant\_pages\_updated\_90d

percentage\_relevant\_pages\_updated\_365d

median\_relevant\_content\_age

days\_since\_latest\_relevant\_page

recent\_service\_relevant\_pages

recent\_location\_relevant\_pages

recent\_service\_location\_pages

&nbsp;

This should parallel social and GBP recency measurements and allow testing whether recent relevant website activity predicts AIO visibility independently of total topical depth.

&nbsp;

64.8 Citation-Source Overlap Across AIO Winners

Do not only count citations for each business independently. Measure which source domains and source types repeatedly appear in association with AIO-visible businesses within the same vertical, geography, and query class.

&nbsp;

Potential variables:

winner\_source\_domain\_frequency

winner\_source\_domain\_share

winner\_source\_type\_frequency

business\_source\_overlap\_count

vertical\_source\_overlap\_count

market\_source\_overlap\_count

source\_winner\_lift

source\_nonwinner\_frequency

&nbsp;

For each domain, compare its prevalence among AIO-visible businesses with matched controls. This may reveal domains, directories, publishers, platforms, or source classes disproportionately associated with AIO visibility in particular verticals. Avoid causal interpretation without appropriate controls.

&nbsp;

64.9 Competitor Co-Occurrence & Entity Graph

Track which businesses/entities repeatedly appear together across AIO answers, organic listicles, directories, social/community discussions, YouTube content, review ecosystems, and other collected sources. Construct a business co-occurrence/entity graph by market and service.

&nbsp;

Potential edge attributes:

cooccurrence\_count

aio\_cooccurrence\_count

organic\_listicle\_cooccurrence\_count

directory\_cooccurrence\_count

social\_cooccurrence\_count

video\_cooccurrence\_count

review\_platform\_cooccurrence\_count

first\_seen\_at

last\_seen\_at

&nbsp;

Potential business-level graph features:

entity\_degree

weighted\_entity\_degree

market\_cooccurrence\_frequency

winner\_cooccurrence\_rate

community\_membership

centrality metrics where statistically appropriate

&nbsp;

This can test whether Google appears to operate from a recurring competitive/entity set for a local market and whether AIO-visible businesses occupy different positions in that graph.

&nbsp;

64.10 Relationship to Service × Geography Corroboration

The measurements above should feed the broader Business → Service → Location corroboration analysis without being reduced to one opaque score. Preserve source-level evidence so the system can count how many independent source types and domains corroborate a business as providing a particular service in a particular geography.

&nbsp;

64.11 Cost & Refresh Planning

Mention-context semantic analysis: expected Gemini cost is small when embedding short titles/context windows and deduplicating by text hash. Provision approximately $1–$5/month at the initial scale, excluding any provider-specific discovery/scraping costs already counted elsewhere.

&nbsp;

External review ecosystem: provider availability and pricing vary substantially by platform. Provision approximately $10–$50/month for a limited V1 profile/summary/sample-text layer, with actual costs recorded by platform/provider. Do not assume full-review-history collection in this estimate.

&nbsp;

Entity longevity: mostly derived from data already collected. Incremental compute/storage cost should be negligible. Any paid domain-history/WHOIS source should be evaluated separately before implementation.

&nbsp;

Local geographic prominence grids: this is the potentially expensive addition. Keep V1 to a stratified subset. Provision approximately $10–$50/month initially for additional local/Maps SERP collection, then recalculate from actual grid size, keyword count, business count, and DFS task costs. Do not silently expand grids to the full business universe.

&nbsp;

Distance/proximity: negligible incremental running cost because it is calculated from coordinates already stored.

&nbsp;

Schema/entity markup: negligible to low incremental cost when extracted during existing website crawls; provision approximately $0–$5/month for incremental processing/storage rather than separate crawling.

&nbsp;

Website freshness: approximately $0–$10/month incremental when derived from the existing lightweight crawl and changed-page pipeline. Do not pay to fully recrawl unchanged sites solely for freshness.

&nbsp;

Citation-source overlap and competitor/entity graph: primarily database/analysis workloads over data already collected. Provision approximately $0–$10/month incremental infrastructure/compute at initial scale.

&nbsp;

Section 64 component ranges are cost-sensitivity allowances, not simultaneous recurring spend assumptions. Do not add every component upper bound to forecast steady-state operation. Event-driven collection, shared canonical entities/data, bounded subsets, and selective reconciliation mean many components will not incur their upper-bound cost in the same month. Section 67 remains the authoritative consolidated operating envelope. If a Section 64 experiment is deliberately expanded beyond that envelope, record it as an explicit scope/budget change.

&nbsp;

Do not treat Section 64's individual layer allowances as an automatic additive $20–$130 recurring charge. They are scenario/sensitivity ranges for optional or event-driven work. The current authoritative V1 operating envelope across the geo-neutral, explicit-city, and near-me query-family design is maintained in Section 67, and provider-level api\_usage/cost tables remain the production source of truth.

&nbsp;

64.12 Methodological Controls

Apply these features to AIO-visible businesses and controlled non-visible competitors. Preserve observation dates and use only evidence that existed at or before the AIO observation for temporal models. Keep raw component variables available even when creating derived aggregates. Separate correlation from causation, and version classification, embedding, grid, and entity-resolution methodologies so historical analyses remain reproducible.

&nbsp;

# **65\. AIO Module Implementation Plan & Parent Dependencies**

&nbsp;

Purpose

This section defines the AIO module's implementation sequence and dependencies. Shared platform architecture—canonical entities, raw-observation storage, queue schema/mechanics, provider economic-unit deduplication, content assets/hashes, embeddings, signal warehouse, cost ledger, missingness states, finding registry, intervention infrastructure, and LLM gating—is inherited from the Unified Platform PRD and must not be implemented as a parallel AIO stack. The AIO-specific implementation priority remains preservation of monthly full-panel and weekly Sentinel AIO observations above enrichment work because historical SERP/AIO observations are time-sensitive and cannot be reconstructed reliably later.

&nbsp;

Core architectural principle

AIO observation collection is Tier 1 and must never wait for enrichment. If semantic processing, selective social collection, crawling, backlink enrichment, GBP enrichment, external-review collection, or any other downstream provider fails, the system must still preserve the scheduled run's raw provider responses and normalized AIO observations.

&nbsp;

System architecture

Recommended high-level flow:

GitHub → Railway scheduler/orchestrator → Postgres job queue/workers → DataForSEO / ScrapeOwl / approved selective enrichment and semantic providers → Supabase Postgres \+ pgvector \+ Storage → feature pipeline → statistical analysis → versioned research\_findings / Strategy Evidence Framework → cadence-aware dashboards/reports \+ qualified client-opportunity outputs → intervention/outcome feedback when applicable.

&nbsp;

GitHub is the source of truth for application code, migrations, schemas, configuration, taxonomies, prompts, analysis code, and experiment definitions. Railway hosts scheduled jobs and workers. Supabase provides the canonical relational database, pgvector, and raw/object storage where appropriate.

&nbsp;

Logical worker architecture

Implement independent workers so provider failures and slow enrichments do not block core collection. Recommended workers:

• scheduler/orchestrator

• serp-collector-worker

• serp-parser-worker

• business-entity-resolver-worker

• control-selection-worker

• crawler/site-inventory-worker

• dfs-domain-page-metrics-worker

• dfs-backlinks-anchor-worker

• dfs-gbp-worker

• dfs-reviews-updates-worker (Q\&A subtask disabled unless validation authorizes it)

• nap-citation-discovery-worker

• social-profile-discovery-worker

• selective-social-content-worker \[evidence/fanout/analysis-directed only\]

• external-review-worker

• gemini-embedding-worker

• gemini-classification-worker

• feature-calculation-worker

• temporal-join-worker

• analysis-worker

• report-worker

&nbsp;

Workers may initially run within fewer Railway services for simplicity, but jobs and responsibilities should remain logically separated so they can be scaled independently later.

&nbsp;

Job queue architecture

Use Postgres as the initial durable job queue unless scale demonstrates a need for a dedicated queue system.

&nbsp;

jobs recommended fields:

id

job\_type

entity\_type

entity\_id

query\_id\_when\_applicable

serp\_observation\_id\_when\_applicable

provider

priority

status

attempts

max\_attempts

scheduled\_at

started\_at

completed\_at

last\_error

payload\_json

idempotency\_key

created\_at

updated\_at

&nbsp;

Job types include:

collect\_serp

parse\_serp

resolve\_business

select\_controls

crawl\_page

inventory\_domain

embed\_page

embed\_site\_title\_h1

classify\_page

classify\_domain

refresh\_domain\_metrics

refresh\_page\_metrics

refresh\_backlinks

refresh\_anchors

discover\_nap\_citations

resolve\_gbp

refresh\_gbp\_profile

collect\_google\_reviews

collect\_gbp\_updates

collect\_google\_qa \[DISABLED until Q\&A validation authorizes recurring collection\]

discover\_social\_profiles

verify\_social\_profile

refresh\_social\_profile

collect\_social\_content \[SELECTIVE ONLY; no universal recurring profile-history crawl\]

collect\_external\_reviews

embed\_social\_content

classify\_social\_content

embed\_gbp\_post

classify\_gbp\_post

calculate\_features

build\_analysis\_dataset

build\_research\_findings

evaluate\_client\_strategy\_when\_applicable

evaluate\_intervention\_outcomes\_when\_applicable

generate\_cadence\_report

&nbsp;

Job requirements

Jobs must be idempotent wherever practical. Use deterministic idempotency keys such as job\_type \+ entity\_id \+ observation/snapshot period \+ provider/version. Implement bounded retries with exponential backoff, provider-specific rate limits, dead-letter/failed status, error logging, and manual replay capability. Downstream provider outages must not cascade into failed scheduled AIO collection for either the monthly Full Panel or weekly Research Sentinel.

&nbsp;

Priority classes

Tier 1: monthly Full Panel \+ weekly Research Sentinel AIO collection and immutable raw-response preservation.

Tier 2: parsing, business/entity resolution, AIO citations, organic/Maps extraction, control selection.

Tier 3: time-sensitive enrichment required for temporal analysis, including GBP/reviews/posts/social snapshots.

Tier 4: slower enrichment such as backlinks, site inventories, NAP discovery, external reviews, embeddings, classifications.

Tier 5: derived-feature recomputation, historical backfills, clustering, exploratory analysis.

&nbsp;

AIO-specific canonical relationships and projections

The database should distinguish:

1\. Canonical entities — businesses, domains, pages, social profiles, queries.

2\. Immutable or append-oriented observations — SERP observations, AIO answers, citations, rankings, review/post snapshots, metric snapshots.

3\. Mutable current-state metadata — normalized business/domain/page/profile records.

4\. Derived features — reproducible calculations generated from raw/canonical observations.

5\. Raw provider artifacts — complete provider responses stored separately for replay and audit.

6\. Versioned evidence and decision records — research\_findings, client\_strategy\_recommendations, and client\_interventions, with superseding/version relationships so historical evidence and decisions remain auditable.

&nbsp;

Never overwrite historical observations merely because a newer observation exists.

&nbsp;

Entity relationships

The canonical relationship should generally follow:

business → website domain → pages

business → GBP Place ID/CID

business → social profiles

business → NAP citations/mentions

business → external-review profiles

query → city/location → industry/service/query template

serp\_run → query → serp\_observation → AIO answer / organic results / local results

AIO answer → citations/pages/domains/business mentions/company appearances

business × query × observation date → analysis features.

analysis datasets → versioned research\_findings → client\_strategy\_recommendations → client\_interventions → measured outcome/evidence feedback.

&nbsp;

Entity resolution

Create one canonical business\_id wherever evidence supports a match. Use Google Place ID and CID as strong identifiers when available, supplemented by normalized domain, phone, business name, address, coordinates, and other evidence.

&nbsp;

Store resolution evidence and confidence rather than silently merging uncertain entities. Recommended fields include resolution\_method, resolution\_confidence, matched\_place\_id, matched\_cid, matched\_domain, matched\_phone, matched\_address, match\_evidence\_json, resolved\_at, resolver\_version.

&nbsp;

Ambiguous matches should remain unresolved or enter a review queue rather than contaminating the research dataset.

&nbsp;

URL/domain normalization

Centralize URL normalization. Store original URL plus canonical/normalized forms. Normalize protocol/www variants, tracking parameters, fragments, trailing slash conventions, host casing, and known redirect/canonical relationships while preserving enough raw information for audit. Use root-domain/subdomain fields separately because citations may occur on meaningful subdomains.

&nbsp;

Raw-data retention

Preserve complete DataForSEO SERP JSON and other provider responses whenever economically practical. Recommended paths include:

/raw-serps/YYYY/MM/DD/run-id/query-id/task-id.json.gz

/raw-pages/domain/hash.html.gz

/raw-provider/provider/YYYY/MM/DD/entity-id/hash.json.gz

&nbsp;

Normalized tables must point back to the raw object path and provider task/request identifiers. Raw responses are the audit/reprocessing layer if parsers or taxonomies change later.

&nbsp;

Temporal architecture

Temporal correctness is mandatory. Every observation/enrichment should have observed\_at, collected\_at, published\_at, snapshot\_date, or equivalent timestamps as appropriate.

&nbsp;

When explaining an AIO observation at time T, derived features must use only information known to exist at or before T. Never use a review, post, backlink snapshot, social metric, GBP update, or other observation collected after T as though it existed before the AIO observation.

&nbsp;

For periodic snapshots, join the nearest valid snapshot at or before the AIO observation and enforce provider/layer-specific maximum staleness windows. Store feature\_source\_timestamp and feature\_staleness\_days where useful.

&nbsp;

Control-selection architecture

Controls are a first-class component of the experiment, not an afterthought. For each AIO-visible business/page, select controlled non-visible competitors from the same query/SERP/market wherever possible.

&nbsp;

Candidate controls should preferentially come from:

• businesses in the same Maps/local result set that were not selected by AIO

• organic competitors ranking for the same query but not cited/mentioned by AIO

• businesses matching the same service/geography/category

&nbsp;

Store why each control was selected, its source SERP position, Maps/organic position, and matching variables. Do not repeatedly choose only the weakest competitors. The control procedure should be versioned and deterministic enough to reproduce.

&nbsp;

Recommended table: experiment\_controls

id

serp\_observation\_id

query\_id

winner\_business\_id\_or\_page\_id

control\_business\_id\_or\_page\_id

control\_type

selection\_reason

organic\_position

maps\_position

matching\_features\_json

control\_selection\_version

created\_at

&nbsp;

Analysis unit and feature store

The principal explanatory analysis-ready unit should be business × query × observation date, with additional page/source-level datasets where required. A separate query-family × observation-period dataset is required for AIO prevalence and geography-lift analysis.

&nbsp;

Recommended table/materialized dataset: business\_query\_features

business\_id

query\_id

serp\_observation\_id

observation\_date

aio\_visible

aio\_mentioned

aio\_direct\_link

aio\_cited

all derived predictor columns

feature\_set\_version

built\_at

&nbsp;

Do not make this table the source of truth. It is a reproducible analytical projection of canonical observations.

&nbsp;

Recommended query-family prevalence dataset: query\_family\_period\_metrics

experiment\_version\_id

period\_start

period\_type

query\_family\_id

industry\_id

city\_id

intent

geo\_neutral\_observations

geo\_neutral\_aio\_count

geo\_neutral\_aio\_prevalence

explicit\_city\_observations

explicit\_city\_aio\_count

explicit\_city\_aio\_prevalence

near\_me\_observations

near\_me\_aio\_count

near\_me\_aio\_prevalence

city\_vs\_neutral\_absolute\_lift\_pp

city\_vs\_neutral\_relative\_lift

near\_me\_vs\_neutral\_absolute\_lift\_pp

near\_me\_vs\_neutral\_relative\_lift

near\_me\_vs\_city\_absolute\_lift\_pp

near\_me\_vs\_city\_relative\_lift

prior\_period\_change\_json

feature\_set\_version

built\_at

&nbsp;

Build this reproducibly from approved query treatments and immutable serp\_observations. The \*\_observations denominator fields in query\_family\_period\_metrics must count only prevalence\_eligible successful observations; failed, malformed, incomplete, or methodology-excluded observations remain tracked separately and never silently enter prevalence denominators. Generate period rows by valid collection cohort: monthly Full Panel rows from Full Panel observations and weekly Sentinel rows from Sentinel observations. Do not treat the Sentinel as a statistically complete weekly copy of the Full Panel. Rolling aggregates must preserve cohort/cadence membership.

&nbsp;

Feature pipeline

Raw provider response → normalized canonical records → timestamped snapshots → semantic classifications/embeddings → query/business/page joins → derived variables → analysis-ready feature table → statistical models/report.

&nbsp;

Every derived feature should have a documented definition. Prefer SQL/dbt-like reproducible transformations or version-controlled Python/SQL over calculations embedded only in dashboard code.

&nbsp;

Embedding architecture

Use pgvector for page/query/AIO/social/GBP-post embeddings where useful. Store embedding\_model, embedding\_version, source text/content hash, vector, and created\_at. Do not recompute embeddings when the underlying content hash and embedding version are unchanged.

&nbsp;

For large-site topical footprint analysis, embed the lightweight URL \+ title \+ H1 representation for the site census. Reserve full-content/chunk embeddings for AIO-cited pages, controls, high-relevance candidates, and controlled samples.

&nbsp;

AIO semantic-classification requirements

Structured semantic extraction/classification inherits the parent deterministic/cache/vector-before-LLM policy and shared telemetry. When an AIO-specific semantic variable genuinely requires an LLM, use explicit schemas and versioned prompts/models and preserve derived-output provenance; raw/content-addressed source text remains authoritative.

&nbsp;

Versioning

Version at minimum:

experiment\_version

query\_universe\_version

query\_template\_version

control\_selection\_version

SERP parser version

business resolver version

URL normalization version

source taxonomy version

content taxonomy version

anchor classification version

Gemini model/prompt/schema versions

embedding model/version

feature\_set\_version

analysis\_model\_version

strategy\_framework\_version

decision\_logic\_version

report\_template\_version

Git commit SHA

&nbsp;

Every scheduled run—monthly Full Panel, weekly Sentinel, or explicitly versioned validation experiment—must record the relevant versions so methodological changes can be separated from real changes in Google behavior.

&nbsp;

AIO provider-cost attribution

Provider/API usage accounting is provided by the parent cost ledger. AIO collection/enrichment jobs must populate module/research-run attribution so AIO consumption and shared/reused cost can be reported without a second accounting table.

&nbsp;

Recommended api\_usage fields:

id

provider

endpoint\_or\_actor

job\_id

entity\_type

entity\_id

request\_count

returned\_record\_count

input\_tokens

output\_tokens

embedding\_tokens

provider\_reported\_cost\_when\_available

estimated\_cost

currency

collected\_at

run\_id

&nbsp;

Implement soft and hard monthly budget alerts. Provider-specific limits should include maximum pages per domain, backlinks/anchors per domain, reviews per business, GBP posts per business, social posts per profile, external-review samples, and retry ceilings.

&nbsp;

Incremental and event-driven processing

Avoid full reprocessing by default. Use hashes, canonical IDs, last-seen state, snapshot staleness, and SERP/AIO diffs to process only new, changed, or analytically necessary data. An unchanged monthly full-panel and weekly Sentinel AIO should normally create a new immutable SERP observation but no duplicate full enrichment. Examples:

• sitemap/URL diffs for site inventory

• title\_h1\_hash for topical footprint

• content\_hash for page embeddings

• text\_hash for reviews/posts/social content

• review/post IDs for incremental collection

• nearest historical metric snapshot rather than repeated immutable backfills  
• AIO answer/citation/business-set diffs to detect transition events  
• winner/loser transition jobs that refresh only fast-moving comparison signals  
• canonical entity cache checks before any paid enrichment request

&nbsp;

Cadence-aware collection orchestration

Recommended sequence for each scheduled collection cohort:

1\. Create serp\_run with an explicit cohort\_type (FULL\_PANEL, SENTINEL, or approved EXPERIMENT) and freeze the applicable methodology/query/geometry/provider configuration versions.

2\. Submit/collect provider observations only for the queries/prompts and coordinates belonging to that scheduled cohort. Full Panel AIO uses the locked 10-condition × 9-point design; Sentinel membership follows the governing parent/manifest contract.

3\. Persist complete raw responses immediately.

4\. Parse AIO, citations, organic results, Maps/local results, SERP features and geometry, plus validated local-business-card modules/cards and direct embedded GBP surfaces with normalized destination/action types and versioned provider mappings.

5\. Resolve newly observed domains/pages/businesses.

6\. Select/update matched controls.

7\. Compare the current observation with the prior observation and classify any transition event (gain, loss, regain, persistence, mention/link/citation upgrade or downgrade, business/page swap, local-card gain/loss/swap/rank/destination change, embedded-GBP gain/loss/regain/persistence/action-or-destination change, or local-card ↔ embedded-GBP surface switch). Queue only required enrichment: baseline enrichment for new entities/pages, incremental work for new/changed records, and bounded transition refreshes for incoming/outgoing entities when fast-moving signals are needed for longitudinal comparison. Reuse valid cached enrichment when the relevant entity/state is unchanged.

8\. Run shared embedding processing for new/changed content and LLM classification only where the parent gating policy authorizes it.

9\. Calculate temporally valid business/query features and query-family AIO prevalence/lift metrics.

10\. Build the analysis-ready business × query × date dataset and query\_family\_period\_metrics dataset.

11\. Run QA checks.

12\. Generate the cadence-appropriate statistical/research report and dashboard updates. Weekly reports are Sentinel-scoped; Full Panel reports are monthly. Where evidence thresholds and history are sufficient, create or supersede versioned research\_findings and update Strategy Evidence Framework outputs; early findings should remain appropriately Exploratory/Directional. Client-specific recommendation/intervention evaluation runs only where the strategy layer is operational and suitable client/intervention data exists.

&nbsp;

Steps 1–4 must complete independently of Steps 5–12. If downstream work is delayed, the scheduled run's immutable observations remain intact and downstream analysis can be regenerated later.

&nbsp;

Event-driven and reconciliation orchestration

Do not run full-universe enrichment refreshes simply because a calendar period has elapsed. After baseline enrichment, default to cache reuse. Queue enrichment when a new canonical entity/page/domain appears; a hash/provider ID indicates new or changed data; an AIO winner/loser or citation transition creates a targeted comparison opportunity; a snapshot exceeds the maximum staleness allowed for an analysis that actually needs it; or a bounded reconciliation sample is due.

&nbsp;

Low-frequency reconciliation may still run monthly or quarterly on selected layers/subsets to detect silent changes and estimate cache freshness. Full site-inventory and NAP reconciliation should generally be quarterly or less frequent and may be sampled. Authority/backlink/anchor, GBP, review, social, and external-review refreshes should preferentially target active transition entities, newly observed entities, stale entities actually needed for analysis, and controlled samples rather than every known entity.

&nbsp;

Store the trigger reason on every enrichment job (baseline\_new\_entity, detected\_change, transition\_refresh, staleness\_required, reconciliation\_sample, manual\_backfill). High-value experimental subsets may run more frequently, but cadence/trigger-policy changes must be versioned.

&nbsp;

Quality assurance

Automated QA should include:

• expected query count versus successful SERPs

• matched query-family completeness by geography cohort

• unexpected imbalance in geo-neutral / explicit-city / near-me observation counts

• AIO parse success and schema drift detection

• local-business-card and embedded-GBP provider-mapping/schema-drift detection

• local-entity surface misclassification checks, including the rule that Maps/GBP/SearchViewer URLs alone do not prove a rendered card or embedded GBP surface

• destination/action normalization integrity for website, Maps, GBP, SearchViewer, call, directions, booking, other Google/web, none, and unknown

• duplicate observation detection

• missing raw response detection

• malformed/canonical URL detection

• Place ID/CID/business resolution conflicts

• impossible ranking/geometry values

• citation/page/domain foreign-key integrity

• control coverage rate

• enrichment staleness

• unexpected provider cost spikes

• embedding/classification failures

• timestamp leakage checks

• missing feature-rate changes week over week

• prevalence-eligibility/exclusion integrity so failed or methodology-excluded SERPs never silently enter AIO-prevalence denominators

• source/content taxonomy version drift and unclassified-rate changes

• every strategy recommendation traces to one or more versioned research findings

• no strategy/intervention analysis uses post-outcome or otherwise future information as pre-intervention evidence

&nbsp;

Manual QA should include a recurring sample of rendered/actual Google SERPs to validate DataForSEO AIO structure, left/right placement, rectangle geometry, above-fold assumptions, business links/mentions, source classifications, local-business-card modules/cards, direct embedded GBP surfaces, and their destination/action mappings. Cards and embedded GBP must be validated independently, and SearchViewer/Maps/GBP URLs should be treated as destination evidence unless the rendered/provider structure separately proves the presentation surface. Validate 50–100 rendered SERPs before treating layout-derived semantic zones such as sidebar or above-fold as authoritative.

&nbsp;

Observability

Track run health and worker/provider health. Recommended metrics include jobs queued/completed/failed, retry rates, provider latency, provider errors, observation success rate, parse success rate, unresolved business rate, control coverage, enrichment freshness, raw-storage writes, cost by run/cohort/provider/economic unit, and report-generation status.

&nbsp;

Reporting architecture

Reports must be generated from versioned analysis tables, not directly from raw provider responses. Preserve each monthly Full Panel report and weekly Sentinel report with explicit cohort scope plus the feature-set/model versions used to create it.

&nbsp;

Core reporting outputs should include, with weekly change metrics limited to the Sentinel unless otherwise supported by a valid cohort:

• AIO prevalence overall and by industry, city/market, market tier, query intent, query family, query geography type, period, and later device

• citation/source-site-type and page/content-type distribution, including AIO source-presence rate, citation share, unique-domain/page share, and Google-property versus open-web share

• business mention/direct-link/citation placement patterns

• local-business-card and direct embedded GBP prevalence, Local Pack overlap, card ↔ embedded-GBP overlap/switching, card-only/GBP-only visibility, and destination/action mix including business website versus Google-hosted SearchViewer/Maps/GBP destinations

• week-over-week AIO answer/citation/business churn

• persistent winners and new gainers/losers  
• transition-event summaries: first gains, losses, regains, swaps, and visibility upgrades/downgrades  
• pre-transition versus post-transition signal deltas for incoming/outgoing entities  
• lead/lag summaries showing whether approved signal changes tend to precede, coincide with, or follow AIO transitions  
• durable-transition versus temporary-churn comparisons

• organic/Maps overlap

• descriptive winner versus control comparisons

• correlations/effect sizes for major signal families

• service × geography corroboration patterns

• topical-footprint relationships

• backlink/anchor relationships

• GBP/review/post/social relationships

• source-overlap and entity co-occurrence patterns

• geo-neutral versus explicit-city versus near-me prevalence and matched-family AIO lift  
• week-over-week change in geography-cohort prevalence and lift  
• coordinate sensitivity where sampled  
• notable industry/geographic differences

• data-quality/sample-size warnings

&nbsp;

Statistical architecture

Do not treat simple pairwise correlations as causal evidence. Report sample sizes, uncertainty/confidence intervals where appropriate, effect sizes, and multiple-comparison considerations. Because the same businesses, query treatments, markets, coordinates, and domains recur across monthly Full Panel waves and weekly Sentinel waves, observations are not independent. Analysis should account for repeated measures using clustered standard errors, mixed-effects models, fixed effects, or other appropriate longitudinal methods as the dataset matures.

&nbsp;

Primary modeling can include binary outcomes such as AIO visibility, mention, direct link, and citation; placement/rank outcomes; persistence/churn outcomes; and source-selection outcomes.

&nbsp;

Maintain raw variables rather than collapsing them prematurely into arbitrary composite scores. No composite AIO Visibility Score belongs in V1. Any future exploratory composite must be empirically justified, versioned, reversible to its component outcomes, and must not replace the raw source/entity/destination/placement/persistence measures.

&nbsp;

Report evolution across monthly Full Panel and weekly Sentinel history

Early collection periods should emphasize descriptive statistics, data quality, and effect sizes because longitudinal history will be limited. As history accumulates, shift part of reporting toward transition analysis: first gains/losses/regains, incoming-versus-outgoing swaps, visibility upgrades/downgrades, persistence versus short-lived churn, within-business/page changes, lagged predictors, survival/churn analysis, and tests of whether signal changes precede, coincide with, or follow AIO visibility changes. Weekly transition language must be identified as Sentinel-scoped when it uses Sentinel observations.

&nbsp;

For transition reports, preserve a configurable pre/post event window, the event query/query family, incoming and outgoing entity IDs where applicable, the exact visibility outcome that changed, and temporally valid deltas for approved signal families. Show both absolute levels and changes from each entity's own prior baseline. Where possible, include matched controls or non-transitioning peers from the same query/market so market-wide or Google-wide movement is not mistaken for an entity-specific effect.

&nbsp;

Security and secrets

Store provider API keys, Gemini credentials, Supabase service credentials, and other secrets in Railway/Supabase secret management, never in Git. Use least-privilege credentials where possible. Avoid storing unnecessary personal information from reviewers/social users; retain only fields needed for aggregate research.

&nbsp;

Backfill strategy

Do not delay scheduled AIO collection for historical enrichment. Begin collecting the monthly Full Panel and weekly Sentinel as soon as Phase 1/pilot acceptance makes the corresponding cohort operational. Backfill approved businesses, pages, GBP/reviews, backlinks, selective social/evidence, NAP, site topical footprint, and other approved enrichments asynchronously.

&nbsp;

If historical provider data cannot establish that a signal existed before an older AIO observation, mark the historical feature missing/unknown rather than imputing future state into the past.

&nbsp;

Implementation phases

Phase 1 — Foundation and irreplaceable collection

• repository/environment setup

• Supabase schema/migrations

• experiment/query universe

• Railway scheduler

• DataForSEO SERP collector

• raw response storage

• run/cost/error logging

At completion of Phase 1, monthly full-panel and weekly Sentinel AIO collection begins and should remain continuously operational.

&nbsp;

Phase 2 — Core SERP normalization

• AIO parser

• citation/reference parser

• organic results

• Maps/local results

• geometry/placement

• domains/pages/businesses

• entity resolution

• local-entity surface parser/provider mapping for local-business cards and direct embedded GBP

• versioned destination/action normalization, including SearchViewer as a destination type rather than a surface

&nbsp;

Phase 3 — Experimental controls

• winner identification

• candidate-control generation

• deterministic/versioned control selection

• control QA

&nbsp;

Phase 4 — DataForSEO/local/web enrichment

• domain/page metrics

• backlinks and anchor text

• NAP citation discovery

• site inventory/topical footprint

• GBP profiles

• Google reviews

• GBP updates/posts

• Google Q\&A \[DISABLED for current production unless separately validated and explicitly authorized by a methodology amendment\]

• business age/entity evidence where obtainable

&nbsp;

Phase 5 — Top-50 evidence and selective external corroboration

• shared Brand \+ Service \+ Location Top-50 Google evidence collection/classification for eligible canonical businesses

• selective social profile/artifact resolution only when required by observed evidence, observed fanout/source behavior, or an approved Analysis Specification Contract

• external review ecosystem where approved

• unlinked mentions/off-site context where observed or analytically required

• referring-source relevance

• no universal Apify/direct-social collection path

&nbsp;

Phase 6 — Gemini semantic layer

• query/AIO/page embeddings

• site title/H1 embeddings

• direct-social-content embeddings/classification only for validly collected bounded evidence/analysis samples

• GBP-post embeddings/classification

• review semantic analysis

• mention/referring-source context analysis

• citation claim/support analysis

&nbsp;

Phase 7 — Derived features and temporal joins

• business × query × date feature store

• service × geography corroboration variables

• nearest-prior snapshot joins

• staleness enforcement

• source-overlap/entity-graph features

• QA/leakage tests

&nbsp;

Phase 8 — Statistical analysis

• descriptive baselines

• winner/control comparisons

• correlations and effect sizes

• multivariable models

• repeated-measures/longitudinal methodology

• persistence/churn analysis as history grows

&nbsp;

Phase 9 — Dashboard, automated reporting, and strategy-evidence outputs

• monthly Full Panel report \+ weekly Sentinel report

• filters by industry/city/state/market tier/query intent/query family/query geography type/source-site type/page-content type/device

• AIO prevalence, geography-cohort lift, and volatility  
• source/site-type and page/content-type composition, presence/share metrics, Google-property versus open-web sourcing, and source-mix changes over time

• citation/source/domain leaderboards

• gainers/losers

• model/effect summaries

• Strategy Evidence Framework classifications and evidence records for findings that meet reporting thresholds

• client-opportunity outputs only after research findings pass the evidence, applicability, actionability, and proxy-risk rules in Section 68

• data-quality and cost dashboards

&nbsp;

Phase 10 — Client strategy and intervention feedback after sufficient evidence/history

• map applicable versioned research findings to client/competitor feature benchmarks

• create versioned client strategy recommendations with confidence, actionability, proxy risk, and Observe/Test/Implement/Scale/Maintain state

• record material research-informed client interventions when they occur

• evaluate predeclared outcomes against appropriate temporal baselines and comparison groups where feasible

• feed intervention-supported, weakened, or contradictory evidence back into superseding research-finding versions without rewriting prior evidence states

&nbsp;

The core research platform can be implementation-ready and collecting useful history before Phase 10 is operational. Strategy outputs mature only as the Section 68 evidence requirements are met.

&nbsp;

Definition of implementation-ready V1

The system is implementation-ready when a developer/coding agent can trace every core research variable from provider/raw source through canonical storage, enrichment, feature calculation, temporal join, and cadence-appropriate reports; rerun parsers/features without recollecting immutable raw data; identify the experiment/model/code versions used for any observation/report; and continue monthly Full Panel and weekly Sentinel AIO collection even when non-core providers are unavailable.

&nbsp;

Build principle

Do not expand V1 with additional research variables merely because they are technically available. The current priority is to build, preserve the irreplaceable monthly Full Panel and weekly Sentinel history, validate data quality/cost/completeness, and allow explicit research need plus accumulated evidence to determine whether any future methodology amendment is justified.

&nbsp;

# **66\. Geography Cohorts, Matched Query Families & AIO Lift**

&nbsp;

Decision

Geo-neutral, explicit-city, and near-me queries are all first-class primary query cohorts. None of these three should be treated as a reduced or secondary control sample. The geo-neutral form is the default reference condition for measuring the effect of adding geographic wording, while the actual experimental control group remains the matched non-AIO pages/businesses described in Sections 27 and 65\.

&nbsp;

Core matched-family design

Where phrasing is natural, organize queries into matched geography triplets that hold the service and intent constant while changing only the geographic expression.

&nbsp;

Core example:

plumber

plumber phoenix

plumber near me

&nbsp;

Urgent-intent example:

emergency plumber

emergency plumber phoenix

emergency plumber near me

&nbsp;

Recommendation example:

best plumber

best plumber phoenix

best plumber near me

&nbsp;

Other intent families such as cost or specific-problem/service queries may also use matched triplets where the wording reflects plausible search behavior. Do not mechanically create awkward variants simply to complete a triplet.

&nbsp;

The base service family should be strongly preferred across industries because it directly measures the difference between a service-only query, an explicit-city query, and a near-me query. Additional matched families should be selected by vertical based on realistic user behavior.

&nbsp;

Standardized location context

All three members of a matched query family should be executed using the same fixed, versioned market location context whenever the provider permits it. For a Phoenix family, “plumber,” “plumber phoenix,” and “plumber near me” should all use the standardized Phoenix research coordinate/location configuration. This prevents location-setting differences from being confused with query-wording differences.

&nbsp;

Every production AIO observation must use a fixed, versioned coordinate\_id from the approved 9-point AIO registry when coordinate targeting is applicable. Where two approved query treatments are compared as a matched family, compare them at the same valid coordinate(s) so treatment and location are not inadvertently confounded.

&nbsp;

For longitudinal comparability, do not allow the approved 9-point AIO coordinate registry to drift between collection waves. A material coordinate-definition change requires an explicit new geometry/methodology version; structural water exclusions remain recorded structural missingness.

&nbsp;

Recommended query fields

query\_geo\_type: geo\_neutral | explicit\_city | near\_me | other

query\_family\_id

location\_coordinate

coordinate\_label

coordinate\_strategy\_version

explicit\_location\_text\_when\_present

near\_me\_boolean

device

language

&nbsp;

query\_family\_id should identify all geography variants representing the same underlying service/intent. Example: the three plumbing queries above share one query\_family\_id.

&nbsp;

Primary AIO prevalence comparisons

For every matched family, calculate AIO prevalence separately for geo-neutral, explicit-city, and near-me. Then calculate at minimum:

&nbsp;

city\_vs\_neutral\_absolute\_lift\_pp \= P(AIO | explicit\_city) \- P(AIO | geo\_neutral)

near\_me\_vs\_neutral\_absolute\_lift\_pp \= P(AIO | near\_me) \- P(AIO | geo\_neutral)

near\_me\_vs\_city\_absolute\_lift\_pp \= P(AIO | near\_me) \- P(AIO | explicit\_city)

&nbsp;

Also calculate relative lift:

&nbsp;

city\_vs\_neutral\_relative\_lift \= (P(AIO | explicit\_city) \- P(AIO | geo\_neutral)) / P(AIO | geo\_neutral)

near\_me\_vs\_neutral\_relative\_lift \= (P(AIO | near\_me) \- P(AIO | geo\_neutral)) / P(AIO | geo\_neutral)

near\_me\_vs\_city\_relative\_lift \= (P(AIO | near\_me) \- P(AIO | explicit\_city)) / P(AIO | explicit\_city)

&nbsp;

Always report both percentage-point difference and relative lift. Relative lift can look disproportionately large when the reference prevalence is low.

&nbsp;

Longitudinal lift analysis

The platform should not only report the current prevalence difference between query types. It should also track how those differences change over time. For each week, month, and rolling period, calculate:

&nbsp;

AIO prevalence by geography cohort

week-over-week prevalence change by cohort

city-vs-neutral absolute and relative lift

near-me-vs-neutral absolute and relative lift

near-me-vs-city absolute and relative lift

week-over-week change in each lift

rolling 4-week and 12-week lift where enough history exists

industry-specific lift

intent-family-specific lift

market-tier and geography-specific lift

&nbsp;

This allows the research to detect whether Google is expanding AIO coverage faster for near-me, explicit-city, or geo-neutral service searches rather than only measuring a static difference.

&nbsp;

Matched-family outcome comparisons

Beyond whether an AIO appears, compare the three geography variants on:

&nbsp;

AIO answer composition

number and identity of businesses mentioned

direct business links

source/site types and page/content types

Maps/local-pack overlap

organic overlap

distance/proximity sensitivity

GBP/review importance

service × geography corroboration

brand/entity prominence

authority/backlink relationships

source diversity

placement/above-fold behavior where measurable

business and citation persistence/churn

&nbsp;

Statistical requirement

Matched triplets create repeated observations of the same underlying intent. Preserve query\_family\_id and model the within-family structure explicitly. Initial reporting should be descriptive and paired/matched where possible. Later models should account for query family, industry, city/market, time, and repeated measures rather than treating every query as independent.

&nbsp;

The default reference condition for geography-formulation contrasts is geo\_neutral, but explicit\_city should also be used as a direct reference when measuring near-me versus city-modified behavior.

&nbsp;

Sensitivity experiments

Multi-coordinate testing remains useful, but it is not the main query control group. A smaller stratified subset should run identical near-me queries from multiple fixed secondary coordinates within the same metro to measure geographic sensitivity. Explicit-city variants may also be repeated from secondary coordinates for a smaller subset to test whether physical location affects results even when the city is present in the query.

&nbsp;

CURRENT GEOMETRY CORRECTION: the production AIO universe is intentionally multiplied across the approved fixed 9-point geometry. Preserve all valid production coordinates for every applicable approved condition. Coordinates beyond the nine-point panel require a bounded, versioned validation experiment; the former one-primary-coordinate/secondary-coordinate design is superseded.

&nbsp;

DataForSEO implementation

Use Google Organic SERP Advanced with the same AIO-loading and geometry settings across all geography variants. Preserve location configuration, check\_url, provider task identifiers, raw responses, and query\_family\_id so matched comparisons remain reproducible.

&nbsp;

Cost assumptions

HISTORICAL COST NOTE: the following older per-task and weekly-volume examples were developed under a superseded AIO sampling design and provider-price assumption. They are retained only as historical sensitivity context and MUST NOT be used as the current AIO budget. Current cost planning uses the 112,500-observation monthly AIO Full Panel, the governing Sentinel contract, current provider telemetry, and the Unified parent cost model.

&nbsp;

SUPERSEDED EXAMPLE: the former \~10,000-query/week core-AIO cost scenario is non-operative.

&nbsp;

SUPERSEDED EXAMPLE: the former \~12,500-query/week core-AIO cost scenario is non-operative.

&nbsp;

SUPERSEDED EXAMPLE: the former \~15,000-query/week expansion scenario is non-operative and does not authorize changing the locked 10-condition panel.

&nbsp;

SUPERSEDED SAMPLING NOTE: the former approximately-nine-natural-variant / \~65,000-weekly AIO universe is historical only. Current production is exactly 10 approved AIO conditions × 9 fixed coordinates across 25 × 50 markets, collected as a monthly Full Panel.

&nbsp;

Additional coordinate testing beyond the approved 9-point production geometry is permitted only as a bounded, explicitly versioned validation experiment. Historical 500-keyword/three-secondary-coordinate cost examples are non-operative.

&nbsp;

Downstream enrichment cost

Matched geography variants should not trigger duplicate enrichment for businesses, domains, pages, GBP entities, backlinks, site-footprint data, social profiles, NAP citations, or reviews already known to the system. Reuse canonical entities and snapshots. Additional cost should mainly come from newly discovered entities/pages and additional business × query semantic calculations.

&nbsp;

Planning envelope

For steady-state planning, the current architecture still requires event-driven enrichment and cache reuse rather than calendar-based re-enrichment. However, the former \~65,000/week and \~$78–$97.50/month core-AIO planning envelope is superseded. Current Full Panel volume is 112,500 maximum pre-water-exclusion observations monthly, and realized provider usage/cost telemetry is the source of truth.

&nbsp;

The former AIO-only $200–$250/month / $225 working target is superseded. AIO is budgeted as part of the Unified platform using shared enrichment and measured economic-unit reuse; current platform planning envelopes are governed by the parent/handoff and must be replaced by observed telemetry as the system operates.

&nbsp;

The former optional 500-keyword × three-secondary-coordinate \~$12/month scenario is historical only. Any new validation subset requires an explicit versioned experiment and its own measured cost telemetry.

&nbsp;

These are planning estimates, not guaranteed bills. As cache reuse rises, enrichment cost should generally decline. Actual DataForSEO task costs and downstream provider usage must be recorded in api\_usage and used to recalibrate future budgets.

&nbsp;

Methodological requirement

Geo-neutral, explicit-city, and near-me observations must never be pooled without retaining query\_geo\_type and query\_family\_id. Report the three cohorts separately, report matched-family contrasts, and then test interaction effects. A signal that predicts AIO visibility for “plumber” may behave differently for “plumber phoenix” or “plumber near me,” particularly proximity, Maps prominence, reviews, and service-area evidence.

&nbsp;

67\. Reconciled AIO Production Scope, Controls & Cost Governance

&nbsp;

Authoritative scope summary

This section is the current consolidated AIO implementation reference. Older AIO passages that describe approximately 8–10 natural variants, \~9 average variants, a weekly full universe, one primary coordinate, a shared 13-point AIO grid, \~65,000 AIO observations per week/snapshot, or the former $200–$250/$225 AIO operating envelope are historical planning provenance and MUST NOT drive current implementation.

&nbsp;

Current Full Panel

• 25 industries × 50 markets.

• Exactly 10 approved AIO query/prompt conditions per industry: four locked core Google query classes plus six locked conversational/long-tail conditions. Literal wording is version-controlled and must not be rewritten or expanded during a wave.

• 9 fixed AIO coordinates per market: center; N/S/E/W at 2.5 miles; N/S/E/W at 5 miles.

• Structural water exclusions are preserved as structural missingness and do not create replacement coordinates.

• Monthly Full Panel maximum before structural exclusions: 25 × 50 × 10 × 9 \= 112,500 AIO observations.

• The fixed Research Sentinel remains weekly under the governing parent contract; it is not a weekly replay of the full 25 × 50 AIO panel.

&nbsp;

Query-treatment and geography analysis

The four core query classes remain first-class treatments inside the 10-condition AIO panel. The six additional conversational/long-tail conditions are also first-class versioned treatments. Historical geo-neutral/explicit-city/near-me matched-family work remains scientifically useful only where the approved 10-condition panel contains genuinely comparable treatments; it is an analysis relationship, not authority to generate extra queries or to redefine the production panel.

All production AIO treatments are observed across the approved 9-point AIO geometry unless the versioned collection manifest explicitly identifies a separately approved bounded experiment. Preserve query-treatment ID, coordinate ID, market, industry, collection wave/time, raw provider configuration, and methodology version so spatial and treatment interactions remain reproducible.

&nbsp;

Controls and sensitivity work

Matched non-visible businesses/pages, within-entity transitions, incoming-versus-outgoing comparisons, negative controls, and bounded device/provider/surface validation remain separate analytical designs under Analysis Specification Contracts. They do not alter the permanent Full Panel. Additional coordinates or devices require an explicitly versioned bounded experiment; the old one-primary-coordinate/secondary-coordinate architecture is not current production.

&nbsp;

Enrichment

Preserve every raw AIO observation first. Then canonicalize and apply shared-cache reuse, content hashes, TTL/freshness, change detection, provider-economic-unit deduplication, and progressive enrichment. Every valid resolved AIO-observed business receives the universal AIO explanatory-variable baseline even if seen on only one query or coordinate. Deeper enrichment remains analysis/event directed.

AIO retains approved backlink/link candidate explanatory variables and monthly histories, deduplicated against sufficiently fresh shared data. Their collection or predictive value does not establish an AIO ranking/selection factor.

Website retrieval uses ScrapeOwl through the shared caching/change-detection layer.

&nbsp;

Shared Top-50 evidence layer

For each applicable eligible canonical business, use the canonical \[BRAND\] \+ \[SERVICE\] \+ \[LOCATION\] Google Organic query and retain the complete first five pages / Top 50 ranked results. Classify first-party website, official social, third-party social, Reddit/community/forum, directory/review, news/editorial/local publication, trade/professional, and other evidence classes as applicable. Direct social collection is selective/evidence-driven; the superseded universal platform-restricted site: searches and universal 90-day activity refreshes are not production requirements. “Not observed in Top 50” is not evidence of nonexistence.

&nbsp;

Cost governance

Current AIO costs are part of the Unified platform cost model and provider telemetry. Do not use the historical \~65,000/week, $87.70/month core-AIO, $200–$250/month, $225/month, or optional one-coordinate sensitivity cost figures as current budgets. Record actual provider requests, economic units, cache hits/misses, escalation modes, and realized costs. Platform-level current working cost envelopes are governed by the Unified PRD/handoff and are planning assumptions, never research findings.

&nbsp;

Methodological consistency

• hypotheses are not findings;

• correlation/predictive importance does not establish causation or an AIO ranking/recommendation factor;

• missing does not equal zero;

• retrieved, cited, linked, supportive, mentioned/recommended, and ranked are distinct states;

• raw observations are immutable;

• derived features/results are reproducible and versioned;

• LLMs must not invent quantitative findings, query treatments, thresholds, or composite scores;

• Section 65 remains the detailed implementation architecture, while this Section 67 controls current AIO scope/cadence/geometry/cost interpretation where older body text conflicts.

&nbsp;

68\. Strategy Evidence Framework & Client Decision Layer

&nbsp;

Purpose

&nbsp;

The Strategy Evidence Framework is the formal layer between research findings and client recommendations. Its purpose is to convert evidence produced by the Local AIO Research Platform into prioritized, defensible SEO actions without treating correlation as causation or assuming that every statistically significant signal should become a client deliverable.

&nbsp;

The framework must answer four separate questions for every potential strategy:

&nbsp;

1\. Is the finding real? Is the observed relationship statistically and methodologically credible?

2\. Is the finding relevant? Does it apply to the client’s industry, market, query intent, geography formulation, competitive environment, and current maturity?

3\. Is the finding actionable? Can the agency or client meaningfully influence the signal or the plausible mechanism behind it?

4\. Is the action worth doing? Does expected strategic value justify effort, cost, risk, opportunity cost, and time to effect?

&nbsp;

A finding must not become a client recommendation merely because it correlates with AIO visibility.

&nbsp;

Evidence classification

&nbsp;

Every research finding should receive one of four evidence classifications:

&nbsp;

Exploratory — an interesting pattern with insufficient evidence for strategy. Use it to generate hypotheses, validation work, or additional analysis.

&nbsp;

Directional — a repeated association with reasonable evidence, but meaningful uncertainty remains. It may inform strategy alongside conventional SEO judgment, particularly when the action is low-risk and broadly beneficial.

&nbsp;

Strong — a robust, replicated relationship that survives relevant controls and sensitivity checks. It should materially influence campaign prioritization for applicable clients.

&nbsp;

Strategy-ready — the evidence is sufficiently strong and well-scoped to be eligible for strategy translation through the remaining Section 68 safeguards. This classification does not itself mean the signal is actionable or that a client should implement it; actionability, proxy risk, applicability, client gap, recommendation confidence, expected value, and risk remain separate decision dimensions.

&nbsp;

These labels are summaries only. Evidence classification and actionability are intentionally separate: the four evidence classes are Exploratory, Directional, Strong, and Strategy-ready, while actionability has its own classification later in this section. The underlying evidence dimensions and raw results must remain available so the classification never becomes an opaque proprietary score.

&nbsp;

Evidence dimensions

&nbsp;

Evaluate each finding across at least the following dimensions:

&nbsp;

sample size — queries, businesses/pages, markets, industries, observation periods, and transition events supporting the finding;

effect magnitude — whether the observed difference is large enough to matter strategically;

statistical uncertainty — confidence intervals, standard errors, posterior intervals, or other uncertainty measures appropriate to the method;

consistency over time — whether the relationship persists across weeks, months, and rolling periods;

cross-market replication — whether it appears in multiple markets rather than one unusual city;

cross-industry replication — whether it is universal, vertical-specific, or isolated to a small subset;

query-intent consistency — whether the relationship differs across service, recommendation, urgent, cost, problem, or informational-local queries;

geography consistency — whether it differs across geo-neutral, explicit-city, near-me, and coordinate-sensitivity conditions;

winner/control robustness — whether it remains when AIO-visible entities are compared with matched non-visible competitors;

multivariable robustness — whether it remains after controlling for important competing explanations and known confounders already represented in the research model;

longitudinal evidence — whether changes in the signal tend to precede, coincide with, or follow visibility transitions;

within-entity evidence — whether the same business/page shows signal movement near changes in its own AIO visibility;

transition replication — whether the pattern repeats across multiple gain, loss, regain, upgrade, downgrade, or swap events;

persistence relationship — whether the signal is associated with durable visibility rather than one-week churn;

sensitivity robustness — whether the conclusion survives reasonable changes to model specification, control selection, coordinates, taxonomy definitions, sampling, and staleness rules.

&nbsp;

No single dimension should determine the evidence classification.

&nbsp;

Evidence hierarchy

&nbsp;

The platform should identify the strongest evidence type available for every material finding. Use the following hierarchy as a conceptual guide rather than a rigid numeric scoring system:

&nbsp;

Level 1 — descriptive association. Example: AIO-visible plumbers have more Google reviews than non-visible plumbers.

&nbsp;

Level 2 — matched comparison. Example: AIO-visible plumbers have more reviews than comparable Maps/organic competitors for the same queries and markets.

&nbsp;

Level 3 — multivariable association. Example: review count remains associated with AIO visibility after controlling for Maps position, organic visibility, authority, market, and other relevant covariates.

&nbsp;

Level 4 — temporal association. Example: review velocity tends to increase before AIO gains rather than merely being higher among existing winners.

&nbsp;

Level 5 — within-entity transition evidence. Example: businesses that gain AIO visibility tend to experience increased service-relevant review activity beforehand relative to their own historical baseline.

&nbsp;

Level 6 — replicated transition evidence. Example: the same pre-transition pattern repeats across multiple markets, weeks, query families, and matched non-transitioning controls.

&nbsp;

Level 7 — intervention evidence. Example: a deliberately changed signal is followed by a measurable difference relative to a suitable comparison or experimental design.

&nbsp;

Most V1 findings will remain observational. Intervention evidence is therefore the strongest available category when the agency later creates suitable real-world tests, but its absence must not be disguised by stronger causal wording.

&nbsp;

Cross-sectional versus longitudinal strategic evidence

&nbsp;

The framework must distinguish “winners have X” from “X tends to change before visibility changes.” Cross-sectional differences may reflect persistent business size, age, brand strength, marketing maturity, customer volume, or other stable characteristics. Longitudinal and within-entity evidence is generally more strategically informative because it focuses on variables that actually changed near an AIO transition, although it still does not establish causation without a stronger design.

&nbsp;

Recommendation outputs should therefore state the strongest evidence available: descriptive, matched-control, multivariable, temporal, within-entity, replicated-transition, or intervention-supported.

&nbsp;

Actionability classification

&nbsp;

Evidence strength and actionability are separate dimensions. A signal can have very strong explanatory evidence yet be impossible to manipulate.

&nbsp;

Classify actionability as:

&nbsp;

Non-actionable — cannot reasonably be changed by the agency/client, such as historical business age.

&nbsp;

Indirectly actionable — cannot be changed directly but can be influenced through related mechanisms, such as broad brand prominence or third-party discussion.

&nbsp;

Actionable — the agency/client can materially affect the observable signal, such as service-page depth, structured entity consistency, citation acquisition, or review-process improvements.

&nbsp;

Highly actionable — the signal can be deliberately changed, measured, and iterated with a reasonably clear operational intervention, such as targeted content expansion, GBP publishing, schema corrections, or specific corroboration work.

&nbsp;

Strong but non-actionable findings remain useful for explanation, benchmarking, model adjustment, and client selection, but should not be presented as tasks merely to make the research feel actionable.

&nbsp;

Strategic applicability

&nbsp;

Every finding must have an explicit applicability scope rather than being generalized automatically to all clients. Store and report applicability by at least:

&nbsp;

industry/vertical;

market and market tier;

query intent;

query family;

query geography type;

device when later available;

client/business maturity where observable;

research period and experiment version.

&nbsp;

A relationship may be strong for home-service recommendation queries in explicit-city and near-me cohorts while weak or unknown for legal informational searches. The strategy layer must preserve those differences.

&nbsp;

Proxy-risk classification

&nbsp;

The framework must distinguish potentially manipulable mechanisms from proxy variables. For example, if large social audiences correlate with AIO visibility, the correct strategy is not automatically “buy or acquire more followers.” Audience size may proxy for brand awareness, business size, customer volume, age, or marketing maturity.

&nbsp;

Assign each strategy candidate a proxy-risk classification:

&nbsp;

Low — the observed signal plausibly represents the mechanism itself or a close operational approximation.

&nbsp;

Moderate — the signal may partly reflect a broader underlying factor and requires corroborating evidence or cautious interpretation.

&nbsp;

High — the signal is likely to be an outcome/proxy of broader business strength or another latent factor; direct manipulation of the metric should not be recommended without stronger evidence.

&nbsp;

Client opportunity analysis

&nbsp;

Once a finding reaches sufficient evidence strength, compare the research evidence with the client’s current state and relevant competitors. Conceptually:

&nbsp;

Opportunity \= supported strategic factor × client deficiency × competitive gap × applicability × actionability.

&nbsp;

This is a conceptual decision framework, not a mandate to multiply arbitrary normalized scores. Preserve the component values separately.

&nbsp;

For each applicable factor, compare at minimum:

&nbsp;

client current value;

matched local competitor distribution;

AIO-visible competitor distribution;

industry/market/query-family benchmark where sample size supports it;

client-to-winner gap;

client-to-competitor gap;

current trend when longitudinal client data exists.

&nbsp;

The same research finding should produce different recommendations for different clients. A client already exceeding the AIO-visible benchmark should not receive a high-priority task merely because the factor is globally important.

&nbsp;

Recommendation confidence

&nbsp;

Each client recommendation should carry a confidence label distinct from the research evidence classification:

&nbsp;

Experimental — evidence is early, inconsistent, or based on limited samples. Use for inexpensive tests or strategically interesting hypotheses.

&nbsp;

Moderate confidence — repeated directional evidence exists, the intervention is plausible, and it generally aligns with established SEO/local-search practice.

&nbsp;

High confidence — strong replicated evidence, appropriate controls, meaningful effect size, direct client applicability, and manageable proxy risk.

&nbsp;

Very high confidence — strong cross-sectional, multivariable, longitudinal, transition, and where available intervention evidence with repeated replication across relevant markets/query classes.

&nbsp;

Strategic priority

&nbsp;

Evidence confidence should not equal execution priority. Priority should consider at minimum:

&nbsp;

evidence confidence;

expected impact;

client gap;

competitor gap;

actionability;

effort;

direct cost;

time to expected signal movement;

strategic durability;

broader SEO/local/conversion benefit;

implementation risk;

proxy risk;

client-specific constraints.

&nbsp;

This prevents a small statistically significant effect from outranking a larger, more practical, and more durable opportunity.

&nbsp;

Recommended strategy states

&nbsp;

Place client opportunities into one of five operational states:

&nbsp;

Observe — interesting but not ready for action.

&nbsp;

Test — worth a controlled, bounded, or low-cost experiment.

&nbsp;

Implement — evidence and client opportunity justify action.

&nbsp;

Scale — prior implementation results and broader evidence justify greater investment.

&nbsp;

Maintain — the client is already strong on the factor and should preserve the advantage rather than divert resources toward unnecessary expansion.

&nbsp;

Research finding record

&nbsp;

Create a versioned findings layer so recommendations point back to reproducible evidence rather than directly to ad hoc dashboard observations.

&nbsp;

Recommended table/materialized entity: research\_findings

&nbsp;

Recommended fields:

&nbsp;

id

finding\_key

finding\_version

supersedes\_finding\_id

status

finding\_title

signal\_family

outcome\_type

industry\_scope\_json

market\_scope\_json

intent\_scope\_json

query\_geo\_scope\_json

experiment\_version\_id

analysis\_model\_version

feature\_set\_version

period\_start

period\_end

sample\_size\_observations

sample\_size\_entities

sample\_size\_markets

sample\_size\_queries

transition\_event\_count

effect\_size\_json

uncertainty\_json

matched\_control\_support

multivariable\_support

longitudinal\_support

within\_entity\_support

transition\_replication\_support

intervention\_support\_when\_available

sensitivity\_results\_json

evidence\_level

evidence\_classification

applicability\_notes

proxy\_risk

limitations

created\_at

updated\_at

&nbsp;

A finding should be regenerated/versioned when the underlying analysis period, experiment version, feature set, model, or material methodology changes. Material changes create a new finding\_version that supersedes the prior record; use status values such as active, superseded, or retracted rather than rewriting the historical evidence state.

&nbsp;

Recommendation record

&nbsp;

Every strategy recommendation should retain an explicit link to one or more research findings.

&nbsp;

Recommended table: client\_strategy\_recommendations

&nbsp;

Recommended fields:

&nbsp;

id

client\_id\_or\_business\_id

recommendation\_version

supersedes\_recommendation\_id

status

primary\_finding\_id\_when\_applicable

industry

market

query\_intent

query\_family\_id\_when\_applicable

query\_geo\_type

signal\_family

recommended\_action

evidence\_classification

recommendation\_confidence

actionability\_class

proxy\_risk

client\_current\_value\_json

competitor\_benchmark\_json

aio\_winner\_benchmark\_json

client\_gap\_json

effect\_size\_json

sample\_context\_json

longitudinal\_support

within\_entity\_support

control\_adjusted\_support

model\_adjusted\_support

applicability\_notes

expected\_benefit

estimated\_effort

estimated\_cost

time\_to\_expected\_signal\_change

broader\_seo\_benefit

risk\_level

strategic\_priority

recommended\_state

evidence\_period\_start

evidence\_period\_end

analysis\_version

created\_at

updated\_at

&nbsp;

Because a recommendation may rely on more than one finding, use a junction table such as client\_strategy\_recommendation\_findings with recommendation\_id, finding\_id, and evidence\_role (for example primary, supporting, or contradictory). Do not force a many-to-many evidence relationship into one finding\_id field.

&nbsp;

Material recommendation changes must create a new recommendation\_version/superseding record rather than overwriting the historical decision state. Status may include active, superseded, withdrawn, completed, or other explicitly versioned states.

&nbsp;

Do not require every field to be a scalar. Complex benchmark/effect data may be stored in normalized child tables or structured JSON where appropriate, but the implementation must preserve traceability to the underlying analysis.

&nbsp;

Example decision logic

&nbsp;

Suppose the research finds that service-specific topical depth is materially higher among AIO-visible plumbing businesses than matched competitors; the relationship remains after controlling for total site size, organic rank, Maps visibility, reviews, authority, and referring domains; businesses gaining AIO visibility also tend to add or substantially update service-relevant content in the preceding observation window; and the relationship replicates across many sufficiently sampled markets.

&nbsp;

That finding may qualify as Strong, with High actionability and Low-to-Moderate proxy risk for applicable plumbing/service-intent queries.

&nbsp;

If a client has four water-heater-related pages while relevant AIO-visible competitors have a median of thirteen, and the client’s service topical-footprint measures materially trail the relevant winner distribution, the strategy layer may recommend expanding the water-heater content cluster. The recommendation should state the evidence level, benchmark gap, applicability scope, uncertainty, and why the action is believed to address the observed deficit. It should not reduce the finding to an unsupported instruction such as “you need nine more pages.”

&nbsp;

Intervention feedback loop

&nbsp;

The long-term strategic value of the platform increases when agency actions are recorded and fed back into the research system. Where practical, create an intervention record whenever the agency makes a material, research-informed change for a client.

&nbsp;

Recommended table: client\_interventions

&nbsp;

Fields should include at minimum:

&nbsp;

id

client\_id\_or\_business\_id

recommendation\_id\_when\_applicable

finding\_id\_when\_applicable

intervention\_type

signal\_family

hypothesis

start\_date

completion\_date

affected\_urls\_or\_entities\_json

target\_queries\_or\_families\_json

pre\_intervention\_state\_json

implementation\_notes

measurement\_plan\_json

comparison\_group\_definition\_json

outcome\_window\_definition\_json

cointerventions\_json

created\_at

&nbsp;

Subsequent observations should allow the platform to derive post-intervention outcomes for AIO visibility, source/entity/destination visibility, organic visibility, Maps visibility, citations, relevant underlying signals, and other predeclared outcomes. Preserve intervention timing so changes before and after the intervention can be evaluated without contaminating historical features.

&nbsp;

The desired learning loop is:

&nbsp;

observational research → strategy hypothesis → client intervention → measured outcome → stronger/weaker evidence → refined strategy.

&nbsp;

Intervention results should not automatically be interpreted causally. Client interventions are often non-randomized and may coincide with other SEO work, seasonality, Google updates, competitive changes, or market shifts. Where feasible, use matched untreated queries/businesses, staggered rollout, predeclared target queries, difference-in-differences-style comparisons, or other stronger quasi-experimental designs before making causal claims.

&nbsp;

Recommendation guardrails

&nbsp;

The system must never automatically translate “X correlates with AIO visibility” into “increase X.”

&nbsp;

Before a recommendation is promoted to Implement or Scale, require sufficient evidence, direct applicability, reasonable actionability, a plausible mechanism, acceptable proxy risk, and an identifiable client/competitor gap.

&nbsp;

Avoid false precision. Do not produce claims such as “backlinks account for 14.7% of AIO rankings” unless the statistical design genuinely supports that interpretation. Prefer effect sizes, uncertainty, conditional associations, benchmark differences, and clearly scoped applicability.

&nbsp;

Do not recommend manipulative behavior solely to move a metric. Examples include manufacturing review language, artificial engagement, deceptive business information, spammy citations, or link schemes. The framework should optimize legitimate evidence of real services, entities, customer experiences, expertise, relevance, and prominence rather than metric gaming.

&nbsp;

Strategy-output architecture

&nbsp;

Strategy recommendations should be generated from versioned research\_findings and client/competitor feature data, not directly from raw provider responses or an unconstrained language-model prompt. An LLM may summarize or explain the recommendation, but the evidence classification, benchmark values, applicability, confidence, actionability, proxy risk, and recommendation state must come from reproducible structured data and version-controlled decision logic.

&nbsp;

The dashboard should eventually support:

&nbsp;

research findings ranked by evidence strength;

findings filtered by industry, intent, geography cohort, signal family, and period;

client opportunity gaps against matched competitors and AIO-visible benchmarks;

recommendations by Observe/Test/Implement/Scale/Maintain state;

recommendation confidence and proxy-risk filters;

intervention tracking and measured outcomes;

findings whose evidence classification changed as new weeks of data accumulated.

&nbsp;

Strategy framework maturity

&nbsp;

Do not treat the strategy layer as fully mature immediately after launch. Early operation should emphasize evidence accumulation and calibration.

&nbsp;

0–4 weeks: observation and validation. Findings are primarily exploratory and should not materially redirect client budgets based on AIO evidence alone.

&nbsp;

Approximately 1–3 months: directional strategy. Repeated, large, methodologically credible effects may influence recommendations, particularly when actions are low-risk and beneficial across conventional SEO/local-search objectives.

&nbsp;

Approximately 3–6 months: evidence-driven strategy. Repeated observations, controls, multivariable models, and early transition history should support stronger prioritization for well-replicated findings.

&nbsp;

Approximately 6–12 months and beyond: proprietary strategic intelligence. Longitudinal transition history, within-entity comparisons, source-composition trends, vertical-specific patterns, and accumulated intervention results can increasingly support agency-specific playbooks.

&nbsp;

These time ranges are guidance, not automatic thresholds. Evidence quality, transition count, sample size, Google-system stability, and vertical coverage matter more than elapsed calendar time.

&nbsp;

Success criterion for the strategy layer

&nbsp;

The Strategy Evidence Framework succeeds when the agency can answer, for a specific client:

&nbsp;

Given what the research platform has learned from the relevant local-AIO observation history, what should this client do next, why should they do it, how confident are we, where does the client differ from applicable AIO-visible competitors, what evidence supports the recommendation, what uncertainty or proxy risk remains, and how will we measure whether the intervention worked?

&nbsp;

Methodological consistency

&nbsp;

Section 68 does not add new primary V1 research variables or change the authoritative query universe, collection cadence, control design, event-driven enrichment policy, or budget. It operates on the evidence already produced by Sections 1–67 plus client-specific state and intervention records when the agency chooses to use the framework operationally.

&nbsp;

If a strategy conclusion conflicts with the underlying research evidence, the research evidence and its documented limitations take precedence. If evidence is insufficient, the correct strategy state is Observe or Test—not to manufacture certainty.

&nbsp;

&nbsp;

# **69\. AIO Local Entity Surfaces: Business Cards, Embedded GBP & Google-Hosted Destinations**

&nbsp;

Purpose

&nbsp;

Local AIOs can expose local businesses through structured presentation surfaces that are not adequately represented by conventional text mentions or web citations. V1 must therefore measure two canonical local-entity presentation classes separately: local\_business\_card and embedded\_gbp. Google SearchViewer is not a third presentation class. When a google.com/searchviewer destination is observed, classify it as a destination/action type attached to the relevant card or embedded GBP surface.

&nbsp;

These surfaces remain subordinate to the three fundamental visibility dimensions in Section 55\. A card or embedded GBP can confer entity visibility and/or destination visibility. Source visibility is true only when separate evidence shows that a source/page was used as evidence. A Google-hosted destination must not be silently counted as an open-web citation or business-site citation.

&nbsp;

Provider and parser handling

&nbsp;

Preserve the complete DataForSEO Advanced SERP response, including raw element/sub-element types, URLs, references, geometry, and provider context. DataForSEO may expose the needed information without a stable normalized serviceviewer, local-card, or embedded-GBP result label. The parser should therefore map validated provider patterns into the stable research schema using a versioned aio\_local\_entity\_surface\_parser\_version.

&nbsp;

Do not use ServiceViewer or SearchViewer as semantic presentation-surface names. Do not infer a local-business card or embedded GBP solely because an element contains a business name, a google.com URL, a Maps/GBP/SearchViewer URL, or right-side placement. Production classification requires a validated provider structure and/or rendered-result confirmation.

&nbsp;

Local business card module

&nbsp;

Table: aio\_local\_business\_card\_modules

&nbsp;

Recommended fields:

id

aio\_answer\_id

serp\_observation\_id

aio\_element\_id

provider\_type

raw\_provider\_type

provider\_context\_json

module\_position

rectangle\_x

rectangle\_y

rectangle\_width

rectangle\_height

above\_fold\_status

card\_count

parser\_method

parser\_version

created\_at

&nbsp;

Table: aio\_local\_business\_cards

&nbsp;

Recommended fields:

id

module\_id

aio\_answer\_id

serp\_observation\_id

aio\_element\_id

business\_id

card\_index

provider\_type

raw\_provider\_type

provider\_context\_json

display\_name

google\_place\_id

cid

rating

review\_count

primary\_category

secondary\_categories\_or\_services\_json

address\_or\_service\_area

hours\_or\_open\_status

phone

website\_url

displayed\_attributes\_json

displayed\_actions\_json

destination\_urls\_json

primary\_destination\_url

primary\_destination\_type

image\_urls\_json

position

rectangle\_x

rectangle\_y

rectangle\_width

rectangle\_height

above\_fold\_status

parser\_method

parser\_version

created\_at

&nbsp;

Direct embedded Google Business Profile / Maps entity surface

&nbsp;

Table: aio\_embedded\_gbp\_surfaces

&nbsp;

Recommended fields:

id

aio\_answer\_id

serp\_observation\_id

aio\_element\_id

business\_id

provider\_type

raw\_provider\_type

provider\_context\_json

display\_name

google\_place\_id

cid

rating

review\_count

primary\_category

secondary\_categories\_or\_services\_json

address\_or\_service\_area

hours\_or\_open\_status

phone

website\_url

displayed\_attributes\_json

displayed\_actions\_json

destination\_urls\_json

primary\_destination\_url

primary\_destination\_type

image\_urls\_json

position

rectangle\_x

rectangle\_y

rectangle\_width

rectangle\_height

above\_fold\_status

parser\_method

parser\_version

created\_at

&nbsp;

A direct embedded GBP is a first-class presentation outcome distinct from a multi-business card module. Resolve its business\_id into the same canonical businesses registry used for Local Pack/Maps, local cards, text mentions, direct links, and citations.

&nbsp;

Destination taxonomy

&nbsp;

primary\_destination\_type and other normalized action destinations should support at minimum:

website

google\_maps

google\_business\_profile

google\_searchviewer

call

directions

booking

other\_google

other\_web

none

unknown

&nbsp;

SearchViewer is a destination classification. A SearchViewer URL can be attached to a local-business card or embedded GBP surface without implying that SearchViewer itself is the source, the business website, or a distinct local-entity presentation class.

&nbsp;

Derived local-card outcomes

&nbsp;

Query-level outcomes should include aio\_local\_card\_module\_present and aio\_local\_card\_count. Business × query × observation outcomes should include aio\_local\_card\_present, aio\_local\_card\_rank, aio\_local\_card\_above\_fold, aio\_local\_card\_destination\_type, aio\_local\_card\_business\_in\_local\_pack, aio\_local\_card\_business\_maps\_position, aio\_local\_card\_business\_text\_mentioned, aio\_local\_card\_business\_direct\_linked, aio\_local\_card\_business\_site\_cited, aio\_local\_card\_business\_supported\_by\_third\_party, and aio\_local\_card\_only\_visibility.

&nbsp;

aio\_local\_card\_only\_visibility means the business appears in a validated local-business card while separately observed conventional AIO text mention, direct business-website link, business-site citation, and embedded-GBP outcomes are absent.

&nbsp;

Derived embedded-GBP outcomes

&nbsp;

Business × query × observation outcomes should include at minimum:

aio\_embedded\_gbp\_present

aio\_embedded\_gbp\_above\_fold

aio\_embedded\_gbp\_destination\_type

aio\_embedded\_gbp\_business\_in\_local\_pack

aio\_embedded\_gbp\_maps\_position

aio\_embedded\_gbp\_cooccurs\_local\_card

aio\_embedded\_gbp\_text\_mentioned

aio\_embedded\_gbp\_business\_direct\_linked

aio\_embedded\_gbp\_business\_site\_cited

aio\_embedded\_gbp\_only\_visibility

&nbsp;

aio\_embedded\_gbp\_only\_visibility means the business appears in a validated direct embedded GBP surface while separately observed conventional AIO text mention, direct business-website link, business-site citation, and local-business-card outcomes are absent. Embedded GBP presence does not automatically count as a source/citation event.

&nbsp;

Cross-surface analysis

&nbsp;

Compare the same canonical business across: traditional Local Pack/Maps position; local-business-card inclusion and order; direct embedded GBP presence; conventional AIO text mention; direct business destination; business-site citation; third-party corroboration; and destination type. Report card ↔ Local Pack overlap, embedded GBP ↔ Local Pack overlap, card ↔ embedded GBP overlap/co-occurrence, card-only visibility, embedded-GBP-only visibility, and destination mix between business websites and Google-hosted destinations.

&nbsp;

Transition events

&nbsp;

Track at minimum: local-card gain/loss, card business swap, card rank/order change, card destination change, embedded-GBP gain/loss/regain, embedded-GBP persistence, embedded-GBP action/destination change, embedded-GBP-only visibility change, local-card → embedded-GBP transition, embedded-GBP → local-card transition, and card/embedded-GBP co-occurrence gain/loss. Do not label these as strategic upgrades or downgrades unless later evidence establishes a meaningful ordering of outcomes.

&nbsp;

Research questions

&nbsp;

The platform should answer how frequently each local-entity surface appears; which businesses are selected; how selection and order overlap with traditional Local Pack/Maps results and each other; what fields, services/categories, images, actions, and destinations are displayed; how often clicks stay within Google via Maps, Business Profile, or SearchViewer versus go to a business website; how Maps/local prominence, proximity, category/service relevance, reviews, GBP activity, organic rank, authority, backlinks, page relevance, and other already-approved factors differ in their relationships with card selection, embedded-GBP selection, and web citation; how persistent and coordinate-sensitive each surface is; and whether gains/losses or surface switches precede, coincide with, or follow other AIO visibility changes.

&nbsp;

Validation protocol

&nbsp;

Before treating either surface as production research data:

1\. Identify a bounded, stratified set of rendered Google results with clear local-business-card and direct embedded-GBP examples.

2\. Save the complete DataForSEO Advanced raw response and provider check URL for the same observations.

3\. Compare rendered surface presence, selected business identity, card order where applicable, visible fields, actions/destinations, URLs, position, and geometry against provider data.

4\. Record the exact provider path/type pattern corresponding to each validated UI surface.

5\. Require repeated successful mappings across representative industries/query types before promoting a mapping from experimental to production parsing.

6\. Store parser/mapping version and retain unknown structures for QA when Google or DataForSEO changes representation.

7\. Treat a Maps, GBP, or SearchViewer URL only as destination evidence unless the provider structure/rendered result separately establishes the presentation surface.

&nbsp;

Collection, enrichment, and cost policy

&nbsp;

Local-entity surface extraction belongs in the shared AIO parser used by each scheduled collection cohort; do not create a separate microservice merely for cards or embedded GBP. If these surfaces can be recovered from the same Advanced raw SERP response already collected for the study, there is no additional full-universe provider-query requirement beyond processing/storage. Newly discovered businesses receive normal baseline canonical enrichment; known businesses reuse cached enrichment unless change, staleness, transition, or reconciliation rules require refresh.

&nbsp;

Do not silently add a second SERP/rendering/API request across the full universe to capture these surfaces. If reliable measurement requires another endpoint, HTML/rendering request, screenshot workflow, or provider option, first test its hit rate, incremental cost, and methodological benefit on a bounded representative validation subset. If adopted as recurring collection, update the authoritative Section 67 budget/scope and experiment/methodology version before pooling observations.

&nbsp;

Methodological interpretation

&nbsp;

Local-business cards and direct embedded GBP surfaces are observable Google outputs, not speculative explanatory variables. Adding them closes a measurement gap without expanding the approved predictor feature set. Their selection outcomes must remain separable from conventional citations, text mentions, direct website links, Local Pack rankings, and one another.

&nbsp;

&nbsp;

70\. CURRENT / RECONCILED AIO COLLECTION CONTRACT — 2026-09-09

Status: authoritative for this AIO child wherever older AIO body text conflicts.

The former shared matched-panel addendum used four shared query classes and a shared 13-point Google geometry. That architecture remains historical provenance only for AIO and MUST NOT be implemented as the current AIO collection contract.

&nbsp;

Current AIO Full Panel:

• 25 industries × 50 markets.

• 10 approved query/prompt conditions per industry: the four locked core Google query classes plus six locked conversational/long-tail conditions. Exact literal text belongs to the versioned methodology/collection manifest and must not be generated or rewritten during collection.

• 9 fixed AIO coordinates per market: center; N/S/E/W at 2.5 miles; N/S/E/W at 5 miles.

• Structural water exclusions remain structural missingness; excluded points are not relocated, imputed, or encoded as zero.

• Full Panel cadence is monthly.

• Maximum pre-water-exclusion monthly Full Panel volume is 25 × 50 × 10 × 9 \= 112,500 AIO observations.

&nbsp;

Research Sentinel:

• The fixed 5-industry × 10-market Sentinel remains weekly under the parent Sentinel contract.

• Use the approved AIO surface-specific geometry and the query membership defined by the governing Sentinel/collection manifest; do not infer a shared four-query/13-point AIO Sentinel from the retired addendum.

• Sentinel collection detects change and does not authorize universal refresh of every explanatory variable.

&nbsp;

Cross-surface comparison:

• Preserve canonical market, industry, query-treatment, coordinate/location-context, collection-time, entity, source, and surface keys so valid matched comparisons can be constructed where treatments genuinely overlap.

• Do not force Maps/Organic geometry or query counts onto AIO merely to create symmetry.

• Cross-surface overlap, coordinate sensitivity, and longitudinal transitions are measured outcomes, not assumptions.

&nbsp;

Enrichment and epistemic safeguards:

• Observe broadly and enrich selectively after canonicalization, shared-cache reuse, TTL/change checks, and economic-unit deduplication.

• Every valid resolved AIO-observed business receives the universal AIO explanatory-variable baseline even when observed only once; recurrence or cross-surface appearance is not an eligibility gate.

• Hypotheses are not findings; correlation or predictive importance does not establish causation or an AIO ranking/selection factor; missing does not equal zero; retrieved, cited, linked, supportive, mentioned/recommended, and ranked states remain distinct.

• Historical 65,000/shared-13-point volume and cost calculations in the retired matched-panel design are non-operative for current AIO implementation. Current cost planning is governed by the Unified parent and measured provider telemetry.

&nbsp;

71\. HISTORICAL / SUPERSEDED SOCIAL METHODOLOGY — 2026-09-09

Status: retained for provenance and bounded validation only; NOT operative production collection.

The former social design used universal platform-restricted Google searches for Facebook, Instagram, and YouTube, Top-20 platform SERPs, and universal 90-day business-profile activity checks. That design is superseded for current production by the shared per-canonical-business \[BRAND\] \+ \[SERVICE\] \+ \[LOCATION\] Google Organic evidence layer through the first five pages / Top 50 results. Do not schedule the former universal site:-restricted searches, universal 90-day activity refreshes, or their historical cadence/cost tables.

Historical constructs worth preserving include first-party versus third-party social evidence, service/location relevance, profile/entity-resolution confidence, strict missingness states, temporal alignment, and the rule that association or predictive importance does not establish a ranking/recommendation factor. These constructs may be derived from Top-50 evidence or selectively collected direct-social evidence when scientifically required.

Validation-only: a stratified, explicitly versioned direct-social sample may be used to estimate precision/recall or otherwise validate Google-indexed social evidence. Such a validation experiment does not authorize universal recurring social scraping.

Current production rule: classify social/community evidence within the complete Top-50 ranked result set and selectively enrich exact/direct social artifacts only when required by observed evidence, observed fanout/source behavior, or an Analysis Specification Contract. “Not observed in Top 50” is not equivalent to no profile, no mention, no activity, or no corroboration.

&nbsp;

72\. LOCKED — AI/AIO Progressive Enrichment & Cost Governance — 2026-09-09

&nbsp;

AI/AIO preserves the approved matched observational panel and applies the parent platform's enrichment-economics architecture after observation. Cost optimization MUST NOT reduce AI/AIO spatial collection.

&nbsp;

72.1 Observation first; enrichment second

Preserve immutable raw AI/AIO observations, answer text, entity/source/destination states, citations, links, mentions, local-business-card/embedded-GBP states, and provenance before enrichment. Then canonicalize and apply the shared gate: sufficiently fresh? materially changed? analytically relevant? paid enrichment required? Deduplicate globally by the correct business/GBP/organization/domain/URL/source/social/content/provider economic unit. Repeated AI appearances, citations, destinations, positions, coordinates, queries, waves, or cross-surface appearances do not justify repurchasing the same sufficiently fresh economic unit.

&nbsp;

72.2 Shared incremental reviews and website assets

AI/AIO reuses the parent's incremental append-only review history and current review-state measurements. It does not repurchase complete review histories merely because a business is selected/cited again. AI/AIO also reuses content-addressed website/page versions, extraction, embeddings, classifications, page-topic/service/location features, and structured-data interpretation when the underlying content has not materially changed. Existing approved site research scope remains intact; this is change-triggered reprocessing, NOT a core-pages-only corpus.

&nbsp;

72.3 Progressive entity/source/destination resolution

Use stable identity evidence first, inexpensive multi-signal resolution second, embeddings where useful third, LLM adjudication only for unresolved ambiguity fourth, and human review where scientifically necessary fifth. Preserve evidence/conflicts/stage/method/confidence/resolver version/override provenance. Deterministic parsing, exact URL/domain/entity relationships, provider metadata, and structured/lexical classification precede embeddings/LLMs where equivalent.

&nbsp;

72.4 TTL and shared signals

Reuse sufficiently fresh shared identity/business/link/review/content/social signals under signal/provider-specific TTL policies. Preserve observed\_at/effective\_at/last\_verified\_at/freshness/TTL-version/stale-or-unknown semantics. Cached reuse is not a fresh observation.

&nbsp;

72.5 Backlinks

For entities/assets belonging to the regular monthly Full Panel population, approved backlink/link variables and histories remain MONTHLY and are shared/deduplicated at the canonical domain/URL/provider economic unit. AI/AIO does not create duplicate monthly backlink purchases for the same economic unit already obtained through Maps/Organic/shared enrichment. The weekly Sentinel uses the approved lightweight weekly link monitoring plus targeted deeper inspection when an event or analysis requires it; it does not run universal full backlink reconstruction weekly. Quarterly replacement of the regular monthly backlink cadence is NOT authorized.

&nbsp;

72.6 Event-driven Sentinel enrichment

Weekly AI/AIO Sentinel observations are collected at the approved scientific resolution, but do not universally refresh all explanatory variables. Compare with prior Sentinel/full-wave state and trigger targeted enrichment only under predefined/versioned research-event rules, such as material AI business-composition change, new/lost AI selection/citation, destination/source transition, or major cross-surface state change. Thresholds come from prospective analysis contracts/baseline variance, not post-outcome LLM invention.

&nbsp;

72.7 Tiered enrichment

Inherit parent Tier 1 universal/cheap, Tier 2 progressive, Tier 3 study-specific/deep enrichment. Deep case/control/transition enrichment must respect analysis-specific risk sets and avoid outcome-conditioned bias.

&nbsp;

72.8 Explicit non-changes

CURRENT CORRECTION: AI/AIO uses its separately approved fixed 9-point geometry for the monthly Full Panel: center \+ N/S/E/W at 2.5 miles \+ N/S/E/W at 5 miles, subject to structural water exclusions. The AIO Full Panel uses the approved 10-condition panel. The fixed weekly Sentinel follows the governing parent/collection-manifest contract. Raw AIO observation retention, current Top-50 evidence methodology, approved backlink methodology, and existing approved brand-demand methodology remain unchanged.

&nbsp;

&nbsp;

73\. LOCKED METHODOLOGY UPDATE — 2026-09-09 — 9-POINT AIO GEOGRAPHY, BACKLINKS & TOP-50 EVIDENCE

&nbsp;

This update supersedes any production statement in this PRD requiring AIO to inherit the 13-point Maps grid.

&nbsp;

AIO production geography is 9 points per market: center; N/S/E/W at 2.5 miles; N/S/E/W at 5 miles. Structural water exclusions remain exclusions and are not relocated or imputed. Spatial sensitivity is itself an AIO research outcome. Maps/Organic geography is governed by their own PRDs and is not reduced by this AIO change.

&nbsp;

The expanded AIO panel uses the approved 10-query design where applicable: 4 core queries plus 6 locked conversational/long-tail queries per industry. At 25 industries × 50 markets × 10 queries × 9 points, the monthly full-panel planning envelope is 112,500 AIO observations before structural exclusions.

&nbsp;

AIO retains backlink/link explanatory variables and approved monthly backlink histories. Newly observed AIO entities/URLs may trigger backlink enrichment when sufficiently fresh shared backlink state is unavailable. Purchases must deduplicate by the correct economic unit (domain/URL/entity/provider object). Link variables are candidate explanatory variables; their collection does not by itself establish an AIO ranking/selection factor.

&nbsp;

Every valid resolved business observed in AIO receives the universal AIO explanatory-variable enrichment even if it appears at only one coordinate or query. Do not gate enrichment on recurrence or cross-platform appearance.

&nbsp;

The shared Brand/Service/Location Search-Evidence Layer is locked at the first 5 Google organic pages / Top 50 results for the canonical brand \+ service \+ location query per eligible canonical business. Preserve the entire ranked Top-50 result set and classify first-party, official social, third-party social, Reddit/community/forum, directory/review, news/editorial, trade/professional, and other evidence classes. Preserve rank, URL, domain, title, snippet, wave, query, market, and canonical mapping. “Not observed in Top 50” is not equivalent to no presence.

&nbsp;

Website retrieval uses ScrapeOwl under the shared content-hash/change-detection architecture. The Top-50 layer supersedes the discussed Top-100/10-page planning option.

&nbsp;

&nbsp;

IMPLEMENTATION-READINESS CHECKPOINT — 2026-09-09 — CURRENT / GOVERNING

This checkpoint supersedes older next-task/implementation-status language in this PRD without changing the locked AIO scientific methodology.

\- Current production contract remains 25 industries × 50 markets × 10 approved query/prompt conditions × the fixed 9-point AIO geometry (center \+ N/S/E/W at 2.5 and 5 miles), subject to structural water exclusions; monthly Full Panel plus weekly fixed Research Sentinel.

\- Shared implementation artifacts now complete: Physical Supabase/Postgres Schema Contract v0.1; Operational QA / Wave Acceptance Contract v0.1 plus machine-readable rules/SQL seed. The collection manifest v0.7 is materially built and awaits deterministic structural-water application/final executable freeze.

\- Active next artifact: bounded Pilot → Production Protocol, recommended starting scale 3 industries × 5 markets.

\- The Maps/Organic 13-vs-9 pilot question does NOT apply to AIO. AIO remains on the separately approved 9-point geometry during the engineering pilot and production unless explicitly amended later.

\- AIO pilot validation must cover provider execution, immutable raw payload retention, AIO trigger/non-trigger semantics, normalized presentation units, business/entity appearances, sources, citations, destinations, evidence relationships, canonical resolution, enrichment/cache reuse, backlink-history joins where governed, structural missingness, cost attribution, parser/version provenance, and QA acceptance.

\- A valid AIO non-trigger or absence is scientific evidence when the request completed and observability is valid; it must not be retried merely to obtain an AIO. Provider/parser failures remain technical states and are governed by the QA contract.

\- The pilot is an engineering and observability validation. It must not be used to tune the permanent 10-condition panel, geography, hypotheses, signals, or source taxonomy toward interesting results.

\- Shared canonical entities, signal histories, costs, raw payloads, QA, and research/finding infrastructure remain parent-owned; this child PRD must not create a parallel AIO truth system during implementation.

&nbsp;

&nbsp;

LOCKED — APPROVED BOUNDED PILOT → PRODUCTION PROTOCOL — 2026-09-09

&nbsp;

Status: APPROVED. This section supersedes prior wording that treated the bounded pilot as a recommendation or pending protocol decision.

&nbsp;

Pilot membership is fixed at IND010 Locksmith, IND019 Urgent Care, and IND022 Chinese Restaurant across MKT008 Vancouver WA, MKT011 Phoenix AZ, MKT021 Chicago IL, MKT040 Birmingham AL, and MKT049 New York City NY: 15 industry×market cells.

&nbsp;

AIO / AI Mode contributes 1,350 pre-water scientific jobs: 15 cells × 10 approved AIO conditions × 9 intended coordinates. The exact C01–C10 literals are inherited from frozen Manifest v1.0. Runtime execution must not paraphrase, expand, collapse, or dynamically rewrite the approved condition text except for the explicitly defined literal city substitution already encoded in the manifest/generator contract.

&nbsp;

AIO geometry remains its independently approved fixed 9-point design: center \+ N/S/E/W at 2.5 miles \+ N/S/E/W at 5 miles. It is not part of the Maps/Organic 13-versus-9 decision and must not change if Maps/Organic later receive a separately approved geometry amendment.

&nbsp;

Structural-water eligibility is resolved before collection under the approved water-mask contract. Intended coordinates remain in provenance when structurally excluded. structural\_water\_exclusion is structural missingness and is never treated as zero/nonappearance; manual\_review is non-executable; configuration\_failure must be corrected before launch. The water gate must be completed across all 1,100 configured coordinate records before Manifest v1.0 is frozen for execution.

&nbsp;

Provider behavior remains the approved DataForSEO AI Mode asynchronous profile: POST /v3/serp/google/ai\_mode/task\_post; GET /v3/serp/google/ai\_mode/task\_get/advanced/{id}; priority 1; English; location\_coordinate {lat},{lon},9z; calculate\_rectangles=false; maximum 100 tasks per POST; and immutable retention of the full advanced raw response together with all observable source, entity/business, presentation, citation/destination, provider task, timing, and provenance objects required by the schema and QA contracts.

&nbsp;

Pilot max\_attempts \= 3 per deterministic job: one initial provider attempt plus at most two QA-authorized technical retries. A valid no-trigger/no-presentation/no-business/no-citation outcome is a scientific observation when supported by the provider response and must not be retried merely to obtain an AIO result. Technical retries remain attempts under the same deterministic scientific job.

&nbsp;

AIO promotion to production is governed by the parent COMPLETE-only GO gate. Required checks include exact manifest/database reconciliation, water eligibility freeze, immutable raw evidence/hash/pointer integrity, parser/schema-drift validation, correct AIO normalization without fabricating absent object types, entity-resolution execution for eligible observed objects, cost attribution, quarantine isolation, reproducible derived-dataset rebuild, and successful mandatory failure drills. PARTIAL means REMEDIATE, not GO.

&nbsp;

&nbsp;

LOCKED — CIVIC-CENTER MARKET ANCHOR AMENDMENT — 2026-09-09

&nbsp;

Status: APPROVED before first live collection. For prospective AIO/AI Mode collection, Census Gazetteer representative/internal points are superseded as the operative market-center origin by the shared platform methodology CIVIC\_CENTER\_ANCHOR\_V1\_2026-09-09.

&nbsp;

Each of the 50 markets uses one frozen official civic-government anchor selected prospectively from: official City Hall; if no conventional City Hall exists, the primary municipal government headquarters/civic center; if a multi-building municipal campus exists, the main municipal seat/public-government headquarters. Exact address, anchor label/type, WGS84 EPSG:4326 latitude/longitude at 7-decimal precision, coordinate/source provenance, source URL(s), verification date, method version, and freeze state are retained. Census place/GEOID fields remain market-identity metadata and historical provenance, not the spatial origin.

&nbsp;

The AIO geography remains its independently approved 9-point cardinal design and is regenerated geodesically from the shared frozen civic-center anchor: center plus N/S/E/W at 2.5 miles and N/S/E/W at 5 miles. No Maps/Organic 1-mile or 3-mile point is introduced into AIO. AIO condition count, source/entity/destination semantics, presentation outcomes, controls, persistence, and cadence remain unchanged.

&nbsp;

After coordinate regeneration, every AIO candidate point is classified under the approved 2025 Census TIGER/Line Areal Hydrography structural-water contract. A non-center water point is structural\_water\_exclusion and remains structural missingness without relocation, substitution, randomization, rotation, imputation, or zero encoding. A civic-center anchor intersecting an approved auto-exclude water polygon is configuration\_failure and blocks launch until corrected.

&nbsp;

This amendment changes only the deterministic spatial origin and derived AIO coordinate values. It does not change the 25-industry × 50-market universe, approved 10-condition panel, Sentinel membership/cadence, pilot membership, result semantics, or pre-water AIO workload. Any older operative text specifying Census Gazetteer representative/internal points as the production center is superseded by this amendment; prior values may be retained only for provenance or an explicitly approved sensitivity study.

&nbsp;

&nbsp;

LOCKED — 2025 TIGER/LINE AREAWATER PACKAGING-EQUIVALENCE AMENDMENT — 2026-09-10

&nbsp;

User-approved implementation amendment. The structural-water source is the U.S. Census Bureau 2025 TIGER/Line AREAWATER polygon dataset. Official county-partitioned archives tl\_2025\_\<5-digit-county-GEOID\>\_areawater.zip are the preferred implementation packaging; the national 2025 AREAWATER GeoPackage is optional and is not a launch prerequisite.

&nbsp;

Retain exact filename, county GEOID, official Census URL, retrieval timestamp, SHA-256, and 2025 vintage for every archive used. Packaging does not change polygon-intersection semantics, the six approved auto-exclude MTFCC values, manual-review rules, center configuration-failure behavior, structural exclusion semantics, no-relocation/no-substitution rule, AIO 9-point geometry, or missingness treatment.

&nbsp;

Manifest Candidate v0.9 records this amendment and is still pre-water. Any foreign-country/boundary treatment discovered during coordinate QA is a distinct methodology question and is not silently authorized by this packaging amendment.

&nbsp;

&nbsp;

LOCKED — U.S. COUNTRY-BOUNDARY ELIGIBILITY GATE — 2026-09-10

&nbsp;

Status: APPROVED METHODOLOGY AMENDMENT BEFORE FIRST LIVE COLLECTION.

&nbsp;

Every AIO spatial coordinate is evaluated against a frozen official U.S. country boundary before the structural-water classifier.

&nbsp;

Rules:

\- Preserve the intended coordinate exactly.

\- Non-center outside-U.S. point → \`outside\_country\_exclusion\`; structural missingness; no ordinary provider job.

\- Center outside-U.S. point → \`configuration\_failure\`; configuration must be corrected before launch.

\- Only inside-U.S. points proceed to the locked 2025 Census TIGER/Line AREAWATER polygon classifier.

\- Crossing a city, county, or state boundary is allowed and is not itself an exclusion.

\- Never relocate, rotate, randomize, substitute, or impute an excluded point; never encode exclusion as rank/visibility zero.

\- Retain boundary source/version, source hash, classifier version, and point-level provenance.

\- Apply uniformly to all configured AIO points before Manifest v1.0 freeze.

&nbsp;

Detroit/Windsor is the motivating discovery only; this is a universal country-boundary rule and supersedes any water-only implementation that would permit out-of-U.S. dry land to become eligible.

&nbsp;