# Local Geo-Grid Ranking Research & Spatial Intelligence Platform

&nbsp;

## Product Requirements Document (PRD)

&nbsp;

Version: 2026-09-09 — Current methodology-aligned draft

&nbsp;

Primary purpose: Local SEO research

&nbsp;

Primary search surface: Google Maps / Local Pack geographic rankings

&nbsp;

Collection cadence: Monthly Full Panel \+ weekly fixed 5-industry × 10-market Research Sentinel

&nbsp;

Primary unit of observation: Business × keyword × search coordinate × run

&nbsp;

Core architectural principle: Measure geographic local-search visibility as a spatial, longitudinal, competitive phenomenon rather than as a single ranking or heatmap score.

&nbsp;

# 1\. Executive Summary

&nbsp;

The Local Geo-Grid Ranking Research & Spatial Intelligence Platform will systematically measure how Google Maps and Local Pack rankings change across geographic space, industries, markets, keywords, businesses, and time.

&nbsp;

The platform goes beyond conventional geo-grid rank tracking.

&nbsp;

Traditional geo-grid tools primarily answer:

&nbsp;

Where does this specific business rank for this keyword?

&nbsp;

The research platform is designed to answer:

&nbsp;

Why does one business rank at a particular coordinate while another does not, how does that relationship change with distance and local competitive conditions, and which observable changes tend to precede expansion or contraction of geographic ranking visibility?

&nbsp;

For every geo-grid search coordinate, the system should preserve the local result set rather than only the monitored business's position. This allows each coordinate to function as a miniature competitive environment containing winners, near-winners, non-winners, incoming businesses, outgoing businesses, and matched controls.

&nbsp;

The platform should measure at minimum:

&nbsp;

exact Maps/local rank by coordinate;

Top 3 and Top 10 presence as primary outcomes; auxiliary Top-20 only in separately versioned validation data;

non-ranking status;

distance between search coordinate and business;

geographic Top 3 and Top 10 coverage;

geographic share of voice;

rank-decay behavior as distance increases;

maximum and effective ranking radius;

spatial visibility area;

directional visibility;

spatial asymmetry;

local competitive density;

ranking persistence and volatility;

cell-level gains and losses;

Top 3 entrance and exit events;

competitor replacement events;

geographic expansion and contraction;

GBP categories and attributes;

review count, rating, velocity, relevance, and recency;

GBP services, posts, photos, and profile activity where available; historical Q\&A only if obtainable and analytically validated;

organic ranking and website relevance;

domain/page authority, referring domains, backlinks, anchors, and link context;

site topical footprint;

NAP citations and off-site corroboration;

social and external review activity;

schema/entity consistency;

business location and business longevity;

local competitive characteristics;

historical intervention data where the agency deliberately changes a signal.

&nbsp;

The platform should support two complementary research modes.

&nbsp;

Cross-sectional analysis asks what differentiates businesses that outperform competitors at the same or comparable coordinates.

&nbsp;

Longitudinal transition analysis asks what changed before a business gained or lost cells, entered or left the Top 3, expanded or contracted its ranking radius, or displaced another business.

&nbsp;

As history accumulates, the platform should increasingly emphasize within-business, within-coordinate, distance-matched, incoming-versus-outgoing, and intervention-based comparisons rather than relying only on cross-sectional correlations.

&nbsp;

The operational end-state is not merely a more sophisticated rank tracker. Research findings that accumulate sufficient evidence should flow through the same Strategy Evidence Framework used by the broader Local Search Research Platform so findings are classified by evidence strength, applicability, actionability, proxy risk, client gap, expected value, and recommendation confidence before influencing client strategy.

&nbsp;

# 2\. Research Objective

&nbsp;

Primary research question:

&nbsp;

What observable characteristics predict a local business's ability to rank across geographic space for a given local-intent query?

&nbsp;

Secondary strategic objective:

&nbsp;

Which observed relationships are sufficiently robust, replicated, actionable, and low enough in proxy risk to inform local SEO strategy, and how do measured client interventions strengthen, weaken, or refine those findings over time?

&nbsp;

Secondary research questions include:

&nbsp;

How strongly does physical proximity predict Maps rank?

How quickly does ranking probability decay as searcher distance increases?

Which businesses outperform what proximity alone would predict?

Which signals are most strongly associated with Top 3 visibility?

Are the predictors of Top 3 visibility different from the predictors of Top 10 visibility?

Which signals are associated with broader geographic ranking coverage?

Which signals appear to allow businesses to rank farther from their physical location?

How do these relationships vary by industry?

How do they vary by market size and competitive density?

How do they vary by query type?

How do they vary by grid radius?

How do they vary by urban, suburban, and lower-density markets?

How strongly does primary-category alignment predict visibility?

Do secondary categories contribute independently after controlling for proximity and other variables?

How strongly do review count and rating correlate with local rank?

Does review velocity predict geographic ranking expansion better than total review count?

Does semantic relevance of reviews to the target service predict rankings?

Does GBP service relevance matter independently of category alignment?

Does GBP posting frequency or topical relevance predict geographic visibility?

Does website topical relevance predict Maps visibility?

Does organic ranking predict Maps visibility after controlling for proximity?

Does organic ranking matter more at greater searcher distances?

Do backlinks, referring domains, anchors, and link context predict Maps geographic coverage?

Does NAP citation prominence or consistency predict visibility?

Do off-site brand mentions predict ranking beyond conventional citation count?

Does social/community activity correlate with local visibility?

Do businesses with broader brand corroboration rank farther from their physical location?

How much do city boundaries, neighborhoods, highways, density, and competitive clusters appear to affect rank?

Why can a business rank strongly in one direction but poorly in another at the same distance?

What changes before a business enters the Top 3 at a coordinate?

What changes before a business loses the Top 3?

What changes before geographic Top 3 coverage materially expands?

What changes before geographic visibility contracts?

When Business B replaces Business A at the same coordinate, which time-varying signals changed?

Are some improvements temporary while others persist?

Which conditions distinguish durable geographic expansion from short-term volatility, using weekly Sentinel resolution for Sentinel members and monthly resolution elsewhere?

Can the same business serve as its own historical control?

Can nearby coordinates provide quasi-controlled spatial comparisons?

Which findings survive distance matching, competitor matching, multivariable analysis, within-business analysis, persistence analysis, and longitudinal transition analysis?

Which findings remain applicable to a specific client, market, query class, and competitive environment?

When an agency intervention is implemented, does subsequent geographic visibility change relative to untreated keywords, grid areas, or competitors?

&nbsp;

# 3\. Initial Hypotheses

&nbsp;

H1. Physical proximity is one of the strongest predictors of Maps rank but does not fully explain geographic visibility.

&nbsp;

H2. The strength of proximity effects varies substantially by industry and market.

&nbsp;

H3. Primary GBP category alignment predicts Maps visibility after controlling for distance.

&nbsp;

H4. Secondary category relevance provides additional predictive value for some query classes.

&nbsp;

H5. Businesses with higher review counts have greater geographic visibility cross-sectionally.

&nbsp;

H6. Review velocity is more predictive of changes in geographic visibility than total review count for some verticals.

&nbsp;

H7. Review topical relevance to the searched service predicts local visibility after controlling for review volume.

&nbsp;

H8. Organic ranking and organic visibility are positively associated with Maps visibility.

&nbsp;

H9. Organic strength has a larger relationship with Maps visibility at greater searcher distances than immediately surrounding the business.

&nbsp;

H10. Website topical relevance predicts geographic ranking coverage after controlling for proximity.

&nbsp;

H11. Service-specific page strength predicts performance for specific service queries better than general domain authority alone.

&nbsp;

H12. Referring domains, backlink quality, anchor context, and local/entity relevance contribute differently from raw backlink counts.

&nbsp;

H13. NAP citation consistency alone explains less variance than broader off-site entity corroboration.

&nbsp;

H14. Businesses with stronger off-site service × geography corroboration demonstrate greater geographic visibility.

&nbsp;

H15. GBP service relevance contributes to rankings beyond category alignment.

&nbsp;

H16. Review, GBP, organic, citation, and brand signals interact with proximity rather than having constant effects at every distance.

&nbsp;

H17. Different signals dominate at different distance bands.

&nbsp;

H18. Businesses that rank unusually well at long distances have a measurably different signal profile from similarly located competitors.

&nbsp;

H19. Geographic ranking visibility is directionally asymmetric for a meaningful share of businesses.

&nbsp;

H20. Competitive density partially explains geographic asymmetry.

&nbsp;

H21. Some apparent cross-sectional ranking factors will weaken materially under within-business, distance-matched, and longitudinal analysis, indicating proxy relationships.

&nbsp;

H22. Signals that repeatedly change before Top 3 entrance, ranking-radius expansion, or geographic coverage gains provide stronger strategic evidence than signals that merely distinguish current winners from current losers.

&nbsp;

H23. Durable geographic gains have a different pre-transition signal profile from temporary ranking volatility.

&nbsp;

H24. Businesses entering the Top 3 at a coordinate can be meaningfully compared with the businesses they displaced.

&nbsp;

H25. Same-business comparisons across coordinates provide cleaner estimates of proximity and local competitive effects because many stable business-level characteristics are naturally held constant.

&nbsp;

# 4\. Fundamental Unit of Observation

&nbsp;

The atomic analytical unit should be:

&nbsp;

business × keyword × search coordinate × grid run

&nbsp;

The system must not reduce an entire grid to one row.

&nbsp;

Example:

&nbsp;

Business: Joe's Plumbing&nbsp;&nbsp;

Keyword: plumber&nbsp;&nbsp;

Search coordinate: 33.472891, \-112.046122&nbsp;&nbsp;

Business coordinate: 33.448992, \-112.074884&nbsp;&nbsp;

Distance: 2.42 miles&nbsp;&nbsp;

Maps rank: 4&nbsp;&nbsp;

Run date: 2026-09-03

&nbsp;

Each search coordinate also produces a coordinate-level SERP/local observation containing the ordered local businesses returned at that location.

&nbsp;

This structure allows the system to analyze both:

&nbsp;

the performance of one business across space; and

the relative performance of competing businesses at the same location.

&nbsp;

# 5\. Experimental Universe

&nbsp;

The research universe should be stratified rather than immediately attempting exhaustive coverage of every industry and city.

&nbsp;

Superseded V1 planning structure (historical reference only):

&nbsp;

10–15 industries;

20–30 markets;

approximately 2–4 primary service keywords per industry;

fixed primary grid methodology;

weekly full-universe collection;

additional deep-grid and multi-radius subsets.

&nbsp;

Historical planning example only; NOT the current production design:

&nbsp;

10 industries&nbsp;&nbsp;

× 20 markets&nbsp;&nbsp;

× 3 keywords&nbsp;&nbsp;

× 81 coordinates using a 9×9 primary research grid&nbsp;&nbsp;

\= approximately 48,600 coordinate-query observations per week.

&nbsp;

Because every coordinate can return multiple local businesses, the number of business-ranking observations will be much larger than the number of coordinate searches.

&nbsp;

HISTORICAL NOTE: this 48,600/week 9×9-grid number belonged to the superseded early planning design and is not a current V1 planning assumption. Current Maps/Organic pilot cardinality is governed by 25 industries × 50 markets × four approved queries × the eligible 13-point first-pilot geometry, with the nested 9-point production candidate tagged inside it.

&nbsp;

The platform should prefer a stable, high-quality research panel over an unnecessarily large but poorly controlled universe.

&nbsp;

# 6\. Industry Sampling

&nbsp;

Industries should represent materially different local-search ecosystems.

&nbsp;

Recommended initial groups:

&nbsp;

Home services:

&nbsp;

plumbing;

HVAC;

roofing;

electricians;

pest control;

tree service;

landscaping;

garage door repair;

moving;

water damage restoration.

&nbsp;

Professional/local services:

&nbsp;

personal injury law;

family law;

dentistry;

cosmetic dentistry;

med spas;

auto repair;

veterinarians;

property management.

&nbsp;

The final V1 industry set should be versioned and frozen before production analysis begins.

&nbsp;

# 7\. Geographic Sampling

&nbsp;

Markets should not consist only of large metropolitan areas.

&nbsp;

Stratify by:

&nbsp;

population;

market tier;

density;

region;

geographic size;

urban form;

competitive intensity.

&nbsp;

Suggested market tiers:

&nbsp;

Tier 1 — major metros&nbsp;&nbsp;

Tier 2 — large secondary markets&nbsp;&nbsp;

Tier 3 — mid-sized cities&nbsp;&nbsp;

Tier 4 — smaller markets

&nbsp;

Store at minimum:

&nbsp;

city;

state;

metro;

latitude;

longitude;

population;

population density;

market tier;

census/region label;

approximate geographic area;

urban/suburban classification where available;

versioned market centroid;

research-grid center methodology.

&nbsp;

# 8\. Keyword Design

&nbsp;

The production panel uses four locked canonical query classes: \[service\] near me; best \[service\] near me; an industry-specific high-need/commercial-intent \[modifier\] \[service\] near me; and \[service\] in \[city\]. Query class is a first-class analytical variable.

&nbsp;

Examples:

&nbsp;

plumber;

emergency plumber;

water heater repair;

personal injury lawyer;

dentist;

tree removal.

&nbsp;

This is important because the coordinate itself supplies the geographic condition.

&nbsp;

Using an explicit-city modifier as the default would combine two geographic variables:

&nbsp;

1\. physical search location;

2\. geographic wording.

&nbsp;

The production design intentionally measures that contrast: Q1–Q3 use near-me wording while Q4 uses explicit-city wording, with query class modeled explicitly rather than treated as an uncontrolled ambiguity.

&nbsp;

Historical/auxiliary query-family experiments may additionally compare:

&nbsp;

{service}

{service} {city}

{service} near me

&nbsp;

from the exact same coordinates.

&nbsp;

This creates a bridge to the matched geography-family methodology used by the AIO research platform.

&nbsp;

# 9\. Query Families

&nbsp;

Queries should belong to versioned query families.

&nbsp;

Potential families:

&nbsp;

Base service:

&nbsp;

plumber

plumber Phoenix

plumber near me

&nbsp;

Urgent:

&nbsp;

emergency plumber

emergency plumber Phoenix

emergency plumber near me

&nbsp;

Specific service:

&nbsp;

water heater repair

water heater repair Phoenix

water heater repair near me

&nbsp;

Production analysis must preserve all four canonical query classes separately and may compare them as matched intent conditions.

&nbsp;

Near-me and explicit-city variants are permanent production query classes, not optional later cohorts.

&nbsp;

# 10\. Grid Definitions

&nbsp;

A grid is a versioned research object.

&nbsp;

Table: grid\_definitions

&nbsp;

Recommended fields:

&nbsp;

id

experiment\_version\_id

market\_id

grid\_name

center\_latitude

center\_longitude

center\_method

grid\_shape

rows

columns

point\_count

radius\_miles

spacing\_miles

coordinate\_generation\_method

grid\_version

active

created\_at

&nbsp;

Examples:

&nbsp;

HISTORICAL/VALIDATION ONLY — 9×9, 5-mile radius;

HISTORICAL/VALIDATION ONLY — 13×13, 5-mile radius;

HISTORICAL/VALIDATION ONLY — 13×13, 3-mile radius;

HISTORICAL/VALIDATION ONLY — 21×21 deep-analysis subset. Current first-pilot geometry is the fixed 13-point cardinal registry with a tagged nested 9-point candidate; dense grids require an explicitly versioned bounded validation experiment.

&nbsp;

A material grid change creates a new grid version.

&nbsp;

Never silently resize or recenter an active research grid.

&nbsp;

# 11\. Grid Point Registry

&nbsp;

Table: grid\_points

&nbsp;

Fields:

&nbsp;

id

grid\_definition\_id

point\_index

row\_index

column\_index

latitude

longitude

distance\_from\_grid\_center

bearing\_from\_grid\_center

sector

coordinate\_hash

active

created\_at

&nbsp;

Grid points are generated once and then reused.

&nbsp;

Monthly full-panel jobs and weekly fixed Research Sentinel jobs must reuse the same eligible permanent coordinate IDs.

&nbsp;

Coordinates must not drift between runs.

&nbsp;

# 12\. Grid Methodology Cohorts

&nbsp;

The platform should support several controlled grid designs.

&nbsp;

Primary standardized grid

&nbsp;

Used for longitudinal comparison across markets.

&nbsp;

Dense urban grid

&nbsp;

Smaller physical radius with tighter spacing.

&nbsp;

Wider suburban grid

&nbsp;

Wider radius designed for larger service areas and lower density.

&nbsp;

Multi-radius grid

&nbsp;

The same business/market evaluated at several radii.

&nbsp;

Potential radii:

&nbsp;

1 mile;

3 miles;

5 miles;

additional wider radii where justified.

&nbsp;

Boundary grid

&nbsp;

A targeted experiment around observed Top 3 or Top 10 ranking boundaries.

&nbsp;

Deep grid

&nbsp;

Higher-resolution grid used only for stratified research subsets rather than the entire universe.

&nbsp;

All grid methodology cohorts must be versioned.

&nbsp;

# 13\. Coordinate Standardization

&nbsp;

Coordinates are experimental conditions.

&nbsp;

They must be treated with the same methodological discipline as keywords.

&nbsp;

Do not allow coordinate drift between monthly full-panel or weekly fixed Research Sentinel runs.

&nbsp;

A material change to:

&nbsp;

grid center;

radius;

spacing;

coordinate-generation algorithm;

provider location methodology;

&nbsp;

requires a new experiment/grid version.

&nbsp;

Historical observations from materially different coordinate designs should not be pooled without explicit normalization and sensitivity analysis.

&nbsp;

# 14\. Grid Runs

&nbsp;

Table: grid\_runs

&nbsp;

Fields:

&nbsp;

id

experiment\_version\_id

started\_at

completed\_at

expected\_coordinate\_queries

successful\_coordinate\_queries

failed\_coordinate\_queries

estimated\_provider\_cost

provider

collector\_version

parser\_version

git\_commit

status

&nbsp;

Every monthly full-panel or weekly fixed Research Sentinel collection is an explicit versioned run cohort.

&nbsp;

# 15\. Coordinate Query Observations

&nbsp;

Table: grid\_observations

&nbsp;

One immutable record per:

&nbsp;

keyword × grid point × run

&nbsp;

Fields:

&nbsp;

id

run\_id

keyword\_id

grid\_point\_id

collected\_at

local\_results\_present

result\_count

raw\_storage\_path

provider\_task\_id

provider\_status

eligibility\_status

exclusion\_reason

status

error\_code

&nbsp;

Observations must be append-only.

&nbsp;

A failed search remains represented as a failed observation.

&nbsp;

# 16\. Local Result Set

&nbsp;

Table: grid\_local\_results

&nbsp;

Store the complete available ordered local result set at every coordinate rather than only the target business.

&nbsp;

Fields:

&nbsp;

id

grid\_observation\_id

business\_id

position

rank\_absolute

name\_as\_returned

rating\_as\_returned

review\_count\_as\_returned

primary\_category\_as\_returned

address\_as\_returned

latitude\_as\_returned

longitude\_as\_returned

website\_url

google\_place\_id

cid

is\_sponsored

result\_metadata\_json

created\_at

&nbsp;

The current production Maps contract retains the Top 10 ordered results. Deeper result sets may be preserved only as explicitly versioned auxiliary/validation data and must not silently change the primary outcome depth.

&nbsp;

# 17\. Canonical Business Registry

&nbsp;

The geo-grid platform should share a canonical business registry with the broader Local Search Research Platform where practical.

&nbsp;

Table: businesses

&nbsp;

Fields:

&nbsp;

id

normalized\_name

legal\_or\_display\_name

address

city

state

postal\_code

latitude

longitude

phone

website\_domain\_id

google\_place\_id

cid

primary\_category

first\_seen\_at

last\_seen\_at

&nbsp;

Business identity should rely preferentially on stable Google identifiers rather than name matching alone.

&nbsp;

# 18\. Business Location History

&nbsp;

Physical location is analytically critical.

&nbsp;

Do not assume the current business coordinate was always valid historically.

&nbsp;

Table: business\_location\_snapshots

&nbsp;

Fields:

&nbsp;

id

business\_id

latitude

longitude

address

effective\_from

effective\_to

source

collected\_at

&nbsp;

If a business moves, the location change itself becomes a transition event and historical distances must continue using the historically valid coordinate.

&nbsp;

# 19\. Distance Architecture

&nbsp;

For every eligible business result and candidate/control business, calculate:

&nbsp;

straight-line searcher-to-business distance;

distance band;

bearing from business to searcher;

directional sector;

distance from searcher to market centroid;

distance from business to market centroid;

distance rank among competing businesses where appropriate.

&nbsp;

Potential distance bands:

&nbsp;

0–1 mile;

1–2 miles;

2–3 miles;

3–5 miles;

5–8 miles;

8+ miles.

&nbsp;

Distance should remain stored as a raw continuous value even when buckets are used in reporting.

&nbsp;

# 20\. Ranking Outcomes

&nbsp;

Do not use one Geo Grid Score as the authoritative outcome.

&nbsp;

Preserve separately:

&nbsp;

Cell-level outcomes

&nbsp;

exact rank;

Top 3 presence;

Top 10 presence;

auxiliary Top 20 presence where a separately versioned deeper dataset exists;

not observed;

rank change;

threshold gain/loss.

&nbsp;

Business-grid outcomes

&nbsp;

Top 3 coverage;

Top 10 coverage;

auxiliary Top 20 coverage where a separately versioned deeper dataset exists;

mean observed rank;

median observed rank;

weighted geographic share of voice;

ranking radius;

visibility area;

distance-decay slope;

excess geographic performance;

directional visibility;

spatial asymmetry;

ranking persistence;

ranking volatility.

&nbsp;

Composite dashboard scores may be calculated later but must never replace the underlying outcomes.

&nbsp;

# 21\. Top 3 Geographic Coverage

&nbsp;

For each:

&nbsp;

business × keyword × grid × run

&nbsp;

calculate:

&nbsp;

top\_3\_coverage \= top\_3\_grid\_points / eligible\_grid\_points

&nbsp;

Example:

&nbsp;

Example: 8 Top 3 eligible points / 12 valid eligible points \= 66.7% Top 3 coverage. The denominator varies when candidate points are structurally excluded for water.

&nbsp;

Also calculate:

&nbsp;

raw Top 3 cell count;

eligible point denominator;

coverage change between comparable observations (weekly for Sentinel members; monthly for non-Sentinel full-panel members);

rolling coverage;

persistent Top 3 coverage.

&nbsp;

# 22\. Top 10 Geographic Coverage

&nbsp;

Calculate:

&nbsp;

top\_10\_coverage \= top\_10\_grid\_points / eligible\_grid\_points

&nbsp;

Top 10 coverage should remain separate from Top 3 coverage.

&nbsp;

A business may have:

&nbsp;

very high Top 10 coverage;

but weak Top 3 conversion.

&nbsp;

That distinction may reveal different signal relationships.

&nbsp;

# 23\. Geographic Share of Voice

&nbsp;

A geographic share-of-voice metric may be calculated using rank weighting.

&nbsp;

Example conceptual weighting:

&nbsp;

Rank 1 \= strongest weight&nbsp;&nbsp;

Rank 2 \= lower weight&nbsp;&nbsp;

Rank 3 \= lower weight&nbsp;&nbsp;

...&nbsp;&nbsp;

non-ranking \= zero

&nbsp;

The exact function must be:

&nbsp;

explicit;

versioned;

reversible;

validated;

not treated as the only outcome.

&nbsp;

Raw cell rank and coverage metrics remain authoritative.

&nbsp;

# 24\. Ranking Radius

&nbsp;

Define multiple ranking-radius outcomes.

&nbsp;

Maximum Top 3 radius

&nbsp;

Farthest observed coordinate where the business ranks Top 3\.

&nbsp;

Effective Top 3 radius

&nbsp;

Distance at which modeled probability of Top 3 visibility falls below a specified threshold.

&nbsp;

Maximum Top 10 radius

&nbsp;

Farthest observed coordinate where business ranks Top 10\.

&nbsp;

Effective Top 10 radius

&nbsp;

Modeled threshold equivalent for Top 10\.

&nbsp;

Effective radius is preferable to relying only on one anomalous distant cell.

&nbsp;

# 25\. Visibility Area

&nbsp;

Estimate geographic area within which the business is likely to achieve:

&nbsp;

Top 3;

Top 10;

auxiliary Top 20 only where a separately versioned deeper dataset exists.

&nbsp;

Do not simply assume the visibility region is circular.

&nbsp;

Where grid resolution supports it, estimate spatial boundaries from observed cells.

&nbsp;

Store:

&nbsp;

estimated Top 3 area;

estimated Top 10 area;

boundary methodology;

interpolation method/version;

uncertainty where applicable.

&nbsp;

# 26\. Distance-Decay Metrics

&nbsp;

For each business/keyword, estimate how ranking changes with distance.

&nbsp;

Possible outcomes:

&nbsp;

rank decay per mile;

Top 3 probability decay;

Top 10 probability decay;

nonlinear distance-response curves.

&nbsp;

Example:

&nbsp;

A business may remain highly visible for the first 2 miles and then deteriorate rapidly.

&nbsp;

Another may decline gradually.

&nbsp;

Those are meaningfully different geographic profiles even if their average ranks are similar.

&nbsp;

# 27\. Geographic Excess Performance

&nbsp;

One of the platform's most important derived research variables should estimate how well a business performs relative to what proximity alone would predict.

&nbsp;

Conceptually:

&nbsp;

geo\_excess\_performance \= expected\_performance\_given\_distance \- observed\_performance

&nbsp;

Exact implementation will depend on the modeled outcome.

&nbsp;

For ranking probability:

&nbsp;

estimate expected probability of Top 3 based on distance and baseline market conditions;

compare the business's actual outcome with that expectation.

&nbsp;

This allows researchers to identify:

&nbsp;

businesses that rank unusually well at long distances;

businesses that rank unusually poorly despite close proximity.

&nbsp;

Those businesses become especially valuable winner/control cases.

&nbsp;

# 28\. Directional Visibility

&nbsp;

For every search coordinate relative to the business, calculate bearing.

&nbsp;

Group coordinates into directional sectors such as:

&nbsp;

N;

NE;

E;

SE;

S;

SW;

W;

NW.

&nbsp;

Calculate per-sector:

&nbsp;

average rank;

median rank;

Top 3 coverage;

Top 10 coverage;

effective radius;

excess performance.

&nbsp;

This enables analysis of asymmetric geographic visibility.

&nbsp;

# 29\. Spatial Asymmetry

&nbsp;

Create explicit measures of whether visibility is substantially stronger in certain directions.

&nbsp;

Potential drivers to investigate:

&nbsp;

competitor clusters;

population density;

municipal boundaries;

neighborhood boundaries;

road/highway barriers;

business districts;

market centers;

proximity to competing businesses;

Google-defined local geography.

&nbsp;

Do not assume asymmetry has a single cause.

&nbsp;

# 30\. Competitive Density

&nbsp;

For every coordinate and/or surrounding radius, derive local competitive characteristics.

&nbsp;

Potential metrics:

&nbsp;

number of same-category businesses nearby;

number of businesses appearing repeatedly in target-query local results;

density of businesses within distance bands;

average review strength of competitors;

average category relevance;

concentration of dominant competitors.

&nbsp;

Competitive environment must be considered alongside business-level signals.

&nbsp;

# 31\. Control Group Design

&nbsp;

Do not enrich only high-ranking businesses.

&nbsp;

Create matched controls for the outcome being analyzed.

&nbsp;

Same-coordinate competitor controls

&nbsp;

Compare businesses returned for the exact same search coordinate.

&nbsp;

Distance-matched controls

&nbsp;

Compare businesses at similar searcher-to-business distance.

&nbsp;

Same-business spatial controls

&nbsp;

Compare the same business across coordinates where it performs differently.

&nbsp;

Adjacent-cell controls

&nbsp;

Compare neighboring coordinates around ranking boundaries.

&nbsp;

Same-market non-transition controls

&nbsp;

For longitudinal events, compare businesses that did not experience the target transition.

&nbsp;

Incoming-versus-outgoing controls

&nbsp;

When one business enters the Top 3 and another exits, treat that pair as a natural competitive comparison.

&nbsp;

Store:

&nbsp;

control\_type;

control\_selection\_reason;

matching\_attributes;

matching\_distance;

source\_coordinate;

source\_keyword;

control\_selection\_version.

&nbsp;

Apply the same enrichment methodology to winners and controls wherever possible.

&nbsp;

# 32\. Why Same-Business Spatial Controls Matter

&nbsp;

The same business observed from different coordinates naturally holds many variables constant:

&nbsp;

GBP age;

categories;

review count;

website;

backlinks;

NAP citations;

brand prominence;

business longevity.

&nbsp;

The primary variables changing are:

&nbsp;

searcher distance;

direction;

local competitive environment;

Google's location interpretation.

&nbsp;

This makes same-business spatial comparisons especially valuable for studying proximity and local geographic effects.

&nbsp;

# 33\. GBP Snapshot Architecture

&nbsp;

Table: gbp\_snapshots

&nbsp;

Potential fields:

&nbsp;

id

business\_id

snapshot\_date

primary\_category

secondary\_categories

services

description

attributes

opening\_hours

special\_hours

website\_url

appointment\_url

service\_area

business\_status

photo\_count

historical Q\&A fields only where obtainable; Q\&A is not a required current production signal

profile completeness fields

collection\_source

parser\_version

&nbsp;

Historical snapshots must remain immutable.

&nbsp;

# 34\. Review Intelligence

&nbsp;

Table: review\_metric\_snapshots

&nbsp;

Potential variables:

&nbsp;

rating;

total\_reviews;

new\_reviews\_7d;

new\_reviews\_30d;

new\_reviews\_90d;

review\_velocity;

rating\_change;

owner\_response\_rate;

owner\_response\_latency where measurable;

recent-review share;

service relevance;

geographic relevance;

topical embeddings;

sentiment distribution where useful.

&nbsp;

Review text should be used only to the extent required for aggregate research.

&nbsp;

# 35\. Review Semantic Relevance

&nbsp;

Where review text is available and collection is permitted, calculate semantic relationships between:

&nbsp;

target keyword and review text;

service/topic and recent reviews;

location/geography and reviews.

&nbsp;

Possible variables:

&nbsp;

keyword-relevant review share;

recent keyword-relevant review share;

maximum review relevance;

mean review relevance;

relevant-review velocity.

&nbsp;

This allows testing whether the content of reviews predicts visibility beyond count and rating alone.

&nbsp;

# 36\. GBP Activity

&nbsp;

Track time-varying GBP activity where feasible:

&nbsp;

post frequency;

post recency;

post topical relevance;

new photos;

historical Q\&A activity where obtainable; not a required current production signal;

service updates;

category changes;

business-description changes;

hours changes.

&nbsp;

Stable attributes should be cached.

&nbsp;

Fast-moving attributes should be refreshed according to staleness and transition requirements.

&nbsp;

# 37\. Website and Organic Intelligence

&nbsp;

For canonical business websites, reuse the broader Local Search Research Platform's page/domain infrastructure where possible.

&nbsp;

Relevant variables include:

&nbsp;

organic position for the target query;

organic visibility;

service-page presence;

location-page presence;

page relevance;

title/H1 relevance;

whole-page embeddings;

best-passage similarity;

page freshness;

content depth;

internal-link prominence;

site topical footprint;

service × geography content coverage.

&nbsp;

# 38\. Site Topical Footprint

&nbsp;

Do not reduce website relevance to one landing page.

&nbsp;

Measure how extensively the site covers:

&nbsp;

target service;

related subservices;

relevant problems;

target geography;

adjacent geographic entities;

topic × geography combinations.

&nbsp;

Potential metrics:

&nbsp;

relevant ranking pages;

relevant indexed/discovered pages;

target-topic page count;

semantic topical coverage;

service-cluster depth;

location-cluster depth;

service × geography footprint.

&nbsp;

# 39\. Backlink and Link Context Intelligence

&nbsp;

Track:

&nbsp;

domain referring domains;

page referring domains;

backlinks;

local backlinks;

relevant backlinks;

anchor text;

anchor semantic relevance;

referring-page semantic relevance;

referring-domain type;

local/regional source status;

new/lost links.

&nbsp;

Historical snapshots should remain temporally valid.

&nbsp;

# 40\. NAP and Entity Corroboration

&nbsp;

Track:

&nbsp;

citation sources;

NAP consistency;

structured business profiles;

local directories;

vertical directories;

chambers/associations;

publishers;

local media;

government sources;

review platforms;

off-site brand mentions;

service mentions;

geographic mentions.

&nbsp;

Develop features describing broader entity corroboration, not merely raw citation count.

&nbsp;

# 41\. Social and External Review Signals

&nbsp;

Candidate explanatory signal families may include the sources below, but acquisition must follow the shared Top-50 Brand \+ Service \+ Location evidence layer and selective, analysis/fanout/evidence-driven direct-social collection rather than universal platform crawling:

&nbsp;

Facebook;

Instagram;

YouTube;

LinkedIn;

Reddit;

TikTok;

Nextdoor;

industry-specific review platforms;

general external review platforms.

&nbsp;

Potential metrics:

&nbsp;

profile presence;

posting activity;

engagement;

topical relevance;

geographic relevance;

business mentions.

&nbsp;

These are explanatory variables, not assumed ranking factors.

&nbsp;

# 42\. Enrichment Scheduling

&nbsp;

Primary geo-grid observations (monthly Full Panel; additionally weekly for fixed Research Sentinel):

&nbsp;

weekly fixed Research Sentinel

&nbsp;

Newly discovered businesses:

&nbsp;

canonicalize first; baseline enrichment only after the shared freshness/change/relevance/paid-enrichment eligibility gate confirms a genuinely new eligible economic unit

&nbsp;

GBP metadata:

&nbsp;

baseline \+ incremental/change-triggered refresh

&nbsp;

Reviews:

&nbsp;

baseline \+ frequent incremental refresh for active research businesses

&nbsp;

Website content:

&nbsp;

baseline \+ content-change refresh

&nbsp;

Backlinks:

&nbsp;

regular/full population \= monthly approved backlink/link variables and histories after global economic-unit deduplication; weekly Sentinel \= approved lightweight weekly link monitoring plus event-/analysis-triggered deeper inspection

&nbsp;

NAP/entity corroboration:

&nbsp;

baseline \+ low-frequency reconciliation/change-triggered refresh

&nbsp;

Social/community evidence:

&nbsp;

shared Brand \+ Service \+ Location Top-50 evidence layer for eligible canonical businesses; direct social/profile/activity retrieval is selective and only triggered by evidence, observed fanout/source behavior, or an approved Analysis Specification Contract. No universal recurring direct-social baseline is authorized.

&nbsp;

Deep enrichment should not rerun for every business every week merely because a new grid observation exists.

&nbsp;

The governing model is:

&nbsp;

baseline enrichment \+ cache reuse \+ incremental updates \+ transition-triggered refresh \+ bounded reconciliation

&nbsp;

# 43\. Deduplication

&nbsp;

Enrichment operates on canonical entities.

&nbsp;

If a business appears in:

&nbsp;

repeated eligible production coordinates;

all four canonical query classes;

repeated monthly/Sentinel runs;

&nbsp;

it should still receive only one equivalent GBP/domain enrichment purchase per canonical economic unit and valid freshness window.

&nbsp;

All coordinate observations reference the same canonical business while retaining their individual historical ranking outcomes.

&nbsp;

# 44\. Raw Data Preservation

&nbsp;

Never discard or overwrite provider responses.

&nbsp;

Store raw coordinate-query responses using deterministic, non-overwriting paths such as:

&nbsp;

/raw-geogrids/YYYY/MM/DD/run-{run\_id}/keyword-{keyword\_id}/point-{grid\_point\_id}/task-{provider\_task\_id}.json.gz

&nbsp;

Preserve:

&nbsp;

provider;

task ID;

request parameters;

location parameters;

response;

parser version;

storage path.

&nbsp;

Raw preservation allows future parsers to recover fields not anticipated during V1.

&nbsp;

# 45\. Experiment Versioning

&nbsp;

Table: experiment\_versions

&nbsp;

Fields should include:

&nbsp;

id;

name;

description;

start\_date;

end\_date;

industry\_definition;

market\_definition;

keyword\_universe\_version;

grid\_strategy\_version;

coordinate\_generation\_version;

device;

language;

provider\_settings;

result\_depth;

control\_selection\_version;

feature\_set\_version;

statistical\_model\_version;

strategy\_framework\_version;

collector\_version;

parser\_version;

created\_at.

&nbsp;

Any material methodology change creates a new experiment version.

&nbsp;

Do not silently change:

&nbsp;

industries;

markets;

keyword set;

grid size;

radius;

center;

coordinate algorithm;

device;

provider methodology;

ranking depth;

control methodology.

&nbsp;

# 46\. Transition Events

&nbsp;

Create explicit longitudinal events.

&nbsp;

Table: grid\_transition\_events

&nbsp;

Initial event taxonomy:

&nbsp;

Cell-level

&nbsp;

first\_rank\_gain;

first\_rank\_loss;

top3\_gain;

top3\_loss;

top10\_gain;

top10\_loss;

significant\_rank\_improvement;

significant\_rank\_decline.

&nbsp;

Business-grid

&nbsp;

top3\_coverage\_expansion;

top3\_coverage\_contraction;

top10\_coverage\_expansion;

top10\_coverage\_contraction;

ranking\_radius\_expansion;

ranking\_radius\_contraction;

visibility\_area\_expansion;

visibility\_area\_contraction;

directional\_expansion;

directional\_contraction;

persistent\_gain;

temporary\_gain;

persistent\_loss;

temporary\_loss.

&nbsp;

Competitive

&nbsp;

top3\_entry;

top3\_exit;

competitor\_replacement;

rank\_order\_swap.

&nbsp;

Every event should record:

&nbsp;

business;

keyword;

grid;

coordinate where applicable;

event date;

previous state;

new state;

incoming business;

outgoing business;

pre-event window;

post-event window;

confidence/eligibility;

event-classification version.

&nbsp;

# 47\. Transition Windows

&nbsp;

For each qualifying event, create configurable windows such as:

&nbsp;

4 weeks pre-event;

event week;

4 weeks post-event.

&nbsp;

As history grows, support longer windows.

&nbsp;

Feature generation must use information that would have been available at the relevant historical point.

&nbsp;

Do not attach current review counts, backlinks, or GBP state to an event that occurred months earlier.

&nbsp;

# 48\. Incoming Versus Outgoing Business Analysis

&nbsp;

When a coordinate changes from:

&nbsp;

Week 1:

&nbsp;

1\. Business A

2\. Business B

3\. Business C

4\. Business D

&nbsp;

To:

&nbsp;

Week 2:

&nbsp;

1\. Business A

2\. Business D

3\. Business B

4\. Business C

&nbsp;

Business D has entered the Top 3\.

&nbsp;

Compare:

&nbsp;

Business D;

displaced business;

retained Top 3 businesses;

nearby non-transition businesses.

&nbsp;

Analyze both:

&nbsp;

absolute feature levels;

feature changes before the transition.

&nbsp;

Repeat across large numbers of events.

&nbsp;

# 49\. Persistence and Volatility

&nbsp;

For every:

&nbsp;

business × keyword × grid point

&nbsp;

calculate:

&nbsp;

observation\_periods;

periods\_top3;

periods\_top10;

Top 3 persistence;

Top 10 persistence;

rank variance;

rank standard deviation;

threshold churn.

&nbsp;

For every:

&nbsp;

business × keyword × grid

&nbsp;

calculate:

&nbsp;

cell retention;

new Top 3 cells;

lost Top 3 cells;

retained Top 3 cells;

new Top 10 cells;

lost Top 10 cells;

geographic churn;

coverage volatility;

radius volatility.

&nbsp;

This distinguishes durable geographic visibility from unstable ranking noise.

&nbsp;

# 50\. Spatial Boundary Analysis

&nbsp;

Identify boundaries where ranking changes materially across neighboring cells.

&nbsp;

Examples:

&nbsp;

rank 2 → rank 9;

Top 3 → outside Top 10;

visible → non-ranking.

&nbsp;

Boundary observations should support targeted deeper grids.

&nbsp;

The system should eventually test whether boundaries correspond with:

&nbsp;

distance thresholds;

competitor locations;

municipal boundaries;

neighborhoods;

market centers;

density shifts;

geographic features.

&nbsp;

Boundary interpretation must remain exploratory until validated.

&nbsp;

# 51\. Statistical Analysis

&nbsp;

Primary outcomes should include:

&nbsp;

Binary:

&nbsp;

top3 \= 1/0;

top10 \= 1/0;

observed\_top20 \= 1/0;

transition\_gain \= 1/0;

transition\_loss \= 1/0.

&nbsp;

Ordinal/count:

&nbsp;

exact Maps rank;

rank bucket.

&nbsp;

Continuous/aggregate:

&nbsp;

Top 3 coverage;

Top 10 coverage;

geographic share of voice;

effective ranking radius;

visibility area;

excess geographic performance;

distance-decay slope;

spatial asymmetry.

&nbsp;

Potential predictor families include:

&nbsp;

distance/proximity;

business location;

category alignment;

GBP services/attributes;

reviews;

review velocity;

review relevance;

GBP activity;

organic rank;

page/domain authority;

backlinks and anchors;

site topical footprint;

page relevance;

NAP/entity corroboration;

social activity;

external reviews;

schema/entity consistency;

business age;

competitive density;

market tier;

industry;

keyword;

direction;

time.

&nbsp;

Start with interpretable models.

&nbsp;

Possible early approaches:

&nbsp;

descriptive distance curves;

matched comparisons;

logistic regression;

ordinal models;

distance-adjusted residual analysis.

&nbsp;

Later:

&nbsp;

mixed-effects models;

business fixed-effects models;

coordinate/grid fixed effects;

longitudinal transition models;

survival/hazard models;

generalized additive models;

spatial models;

tree/boosting models for exploratory prediction.

&nbsp;

Explanation remains the primary objective.

&nbsp;

# 52\. Spatial Autocorrelation Caveat

&nbsp;

Grid cells are not independent observations.

&nbsp;

The full 13-point first-pilot panel does not provide 13 statistically independent measurements; the nested 9-point candidate likewise does not provide 9 independent measurements. The former 73-point design is historical/high-resolution validation provenance and likewise never represented 73 independent measurements.

&nbsp;

Nearby coordinates are spatially correlated.

&nbsp;

The analysis must eventually account for:

&nbsp;

spatial autocorrelation;

repeated observations over time;

business clustering;

keyword clustering;

market clustering;

grid clustering;

industry clustering.

&nbsp;

Naive models that treat every coordinate as independent are likely to overstate statistical confidence.

&nbsp;

Early reports should therefore emphasize:

&nbsp;

effect sizes;

replicated patterns;

descriptive curves;

matched comparisons;

uncertainty;

longitudinal consistency.

&nbsp;

# 53\. Additional Statistical Caveats

&nbsp;

Correlation does not establish causation.

&nbsp;

High review count may be a proxy for:

&nbsp;

business age;

brand prominence;

customer volume;

stronger marketing;

stronger offline reputation.

&nbsp;

Domain authority may proxy broader brand strength.

&nbsp;

Organic ranking may share causes with Maps ranking rather than directly causing it.

&nbsp;

A signal changing before a Maps improvement is stronger evidence than cross-sectional correlation but still does not prove causality.

&nbsp;

Possible confounders include:

&nbsp;

Google algorithm changes;

category changes;

competitor changes;

seasonality;

market-wide review growth;

business relocations;

provider measurement changes;

temporary ranking volatility.

&nbsp;

These limitations must remain explicit in reporting.

&nbsp;

# 54\. Validation Study

&nbsp;

Before production findings are published, manually validate a stratified sample of geo-grid observations.

&nbsp;

Recommended initial validation:

&nbsp;

approximately 100–200 coordinate searches across:

&nbsp;

multiple industries;

multiple markets;

multiple distance bands;

multiple ranking positions;

ranking and non-ranking target businesses.

&nbsp;

Validate:

&nbsp;

1\. search coordinate accuracy;

2\. provider location handling;

3\. returned local result order;

4\. business identity;

5\. rank depth;

6\. GBP identity resolution;

7\. sponsored versus organic local results where relevant;

8\. distance calculation;

9\. category parsing;

10\. missing/non-ranking interpretation.

&nbsp;

Freeze provider-specific definitions after validation.

&nbsp;

# 55\. Quality Assurance

&nbsp;

Automated QA should detect:

&nbsp;

missing coordinates;

duplicate points;

shifted grids;

impossible distances;

unexpected result-depth changes;

duplicate businesses within one result set;

unresolved Place IDs;

abnormal failure rates;

sudden provider-response schema changes;

large market-wide ranking discontinuities;

unexpectedly empty grids.

&nbsp;

Large unexplained market-wide shifts should be flagged for possible:

&nbsp;

Google volatility;

provider issues;

location methodology changes;

parser failures.

&nbsp;

# 56\. Provider Abstraction

&nbsp;

The system should not make the research schema dependent on one geo-grid vendor.

&nbsp;

Create a provider abstraction layer.

&nbsp;

Potential providers may include:

&nbsp;

dedicated geo-grid rank APIs;

Local Dominator where suitable;

DataForSEO local/SERP capabilities where suitable;

another validated provider.

&nbsp;

Normalize provider outputs into the same canonical schema.

&nbsp;

Provider-specific raw fields remain preserved.

&nbsp;

A provider change or material provider-location-method change requires experiment versioning or a validated bridge study.

&nbsp;

# 57\. Queue Architecture

&nbsp;

Use a durable job system.

&nbsp;

Potential job types:

&nbsp;

collect\_grid\_point;

parse\_grid\_response;

resolve\_business;

snapshot\_business\_location;

snapshot\_gbp;

snapshot\_reviews;

snapshot\_domain\_metrics;

snapshot\_page\_metrics;

crawl\_page;

compute\_embeddings;

discover\_citations;

collect\_social;

generate\_grid\_metrics;

detect\_transition;

generate\_controls;

compute\_features;

generate\_research\_dataset;

update\_research\_finding.

&nbsp;

Jobs should support:

&nbsp;

idempotency;

bounded retries;

priority;

execution timestamps;

payloads;

entity context;

error state;

provider;

idempotency key.

&nbsp;

Primary monthly full-panel and weekly fixed Research Sentinel collection must not block on downstream enrichment.

&nbsp;

# 58\. System Architecture

&nbsp;

High-level flow:

&nbsp;

GitHub repository&nbsp;&nbsp;

→ experiment configuration&nbsp;&nbsp;

→ Railway scheduler/orchestrator&nbsp;&nbsp;

→ geo-grid provider/API&nbsp;&nbsp;

→ raw-response storage&nbsp;&nbsp;

→ parser&nbsp;&nbsp;

→ Supabase/Postgres&nbsp;&nbsp;

→ business resolution&nbsp;&nbsp;

→ canonical local-business intelligence layer&nbsp;&nbsp;

→ enrichment queues&nbsp;&nbsp;

→ feature pipeline&nbsp;&nbsp;

→ spatial/longitudinal analysis&nbsp;&nbsp;

→ versioned research findings&nbsp;&nbsp;

→ Strategy Evidence Framework&nbsp;&nbsp;

→ client opportunity layer&nbsp;&nbsp;

→ interventions&nbsp;&nbsp;

→ measured outcomes&nbsp;&nbsp;

→ refined evidence

&nbsp;

Railway is the execution layer.

&nbsp;

Supabase/Postgres is the source of truth.

&nbsp;

Supabase Storage or another object store holds large raw artifacts.

&nbsp;

# 59\. Shared Local Business Intelligence Layer

&nbsp;

The geo-grid platform should not duplicate entity infrastructure already needed by the AIO research platform.

&nbsp;

Where practical, share:

&nbsp;

businesses;

domains;

pages;

GBP snapshots;

review snapshots;

backlink snapshots;

organic observations;

NAP citations;

social profiles;

content embeddings;

topical footprint;

entity corroboration;

business history.

&nbsp;

Then create separate observation families:

&nbsp;

Maps/Geo-Grid Intelligence

&nbsp;

Where does the business rank geographically?

&nbsp;

AIO Intelligence

&nbsp;

Where and how does the business appear within AI-generated local results?

&nbsp;

Organic Intelligence

&nbsp;

How does the business/site perform in conventional web search?

&nbsp;

These outcomes can then be analyzed against the same temporally valid feature layer.

&nbsp;

# 60\. Cross-Surface Research

&nbsp;

Once AIO and geo-grid observations share canonical businesses, support research such as:

&nbsp;

Do businesses with higher Maps geographic coverage appear in AIO more frequently?

Does Maps Top 3 coverage predict AIO local-business-card inclusion?

Does Maps ranking radius predict embedded GBP selection?

Does Maps geographic dominance precede AIO visibility?

Are AIO-selected businesses simply Maps-dominant businesses?

Which businesses receive AIO visibility despite modest Maps coverage?

Which signals differentiate Maps dominance from AIO selection?

Do Maps gains precede AIO gains?

Do the same review/category/local signals affect both surfaces?

&nbsp;

These analyses should remain secondary until each observation system is independently validated.

&nbsp;

# 61\. Cost Tracking

&nbsp;

Track variable research costs by:

&nbsp;

provider;

endpoint;

run;

keyword;

grid;

market;

enrichment type.

&nbsp;

Fields should include:

&nbsp;

provider;

endpoint;

run\_id;

job\_id;

request\_count;

returned\_records;

provider\_cost;

estimated\_cost;

currency;

collected\_at.

&nbsp;

Dashboard metrics:

&nbsp;

monthly Full Panel and weekly fixed Research Sentinel collection cost;

cost per coordinate-query;

cost per market;

cost per keyword;

cost per business observation;

enrichment spend;

storage/infrastructure spend;

budget-versus-plan.

&nbsp;

Scale decisions should use observed production cost rather than static PRD assumptions.

&nbsp;

# 62\. Dashboard Requirements

&nbsp;

Top-level metrics:

&nbsp;

coordinate searches collected;

successful observation rate;

businesses observed;

Top 3 coverage;

Top 10 coverage;

geographic share of voice;

effective Top 3 radius;

effective Top 10 radius;

geographic excess performance;

cell gains;

cell losses;

Top 3 entrants;

Top 3 exits;

geographic churn;

ranking volatility.

&nbsp;

Filters:

&nbsp;

date;

industry;

market;

market tier;

business;

keyword;

keyword family;

grid;

grid radius;

distance band;

directional sector;

category;

provider;

transition type.

&nbsp;

Core reports:

&nbsp;

proximity vs rank;

Top 3 probability by distance;

Top 10 probability by distance;

geographic winner/loser analysis;

excess-performance leaders;

ranking-radius leaders;

radius gains/losses;

coverage gains/losses;

directional asymmetry;

competitor replacement;

review analysis;

GBP category/service analysis;

organic overlap;

backlink analysis;

topical-footprint analysis;

NAP/corroboration analysis;

transition analysis;

strategy-evidence findings.

&nbsp;

# 63\. Example Research Outputs

&nbsp;

The platform should eventually support defensible findings such as:

&nbsp;

Maps ranking probability declines materially with searcher-to-business distance, but the shape of that decline differs by industry.

Certain businesses consistently outperform distance-based expectations across multiple markets and queries.

Primary-category alignment remains strongly associated with Top 3 visibility after proximity adjustment.

Review count has a strong cross-sectional relationship with geographic coverage but substantially weaker within-business longitudinal evidence.

Review velocity is associated with subsequent geographic coverage expansion in selected industries.

Service-relevant review velocity predicts target-keyword gains more strongly than overall review velocity.

Organic ranking is more strongly associated with Maps visibility at longer searcher distances than at very short distances.

Site topical footprint is associated with broader Maps ranking radius in selected verticals.

Off-site service × geography corroboration is disproportionately high among businesses that outperform proximity expectations.

Maps ranking boundaries frequently exhibit spatial asymmetry rather than simple circular distance decay.

Competitive density explains part, but not all, of directional visibility variation.

Businesses entering the Top 3 demonstrate measurable pre-transition differences from displaced businesses.

Some geographic gains are transient, while durable gains exhibit a distinct pre-transition feature profile.

A signal can be strongly correlated with current geographic dominance while showing little evidence of preceding future gains.

&nbsp;

Any numerical examples used during planning remain placeholders until supported by the collected dataset.

&nbsp;

# 64\. MVP Build Gates

&nbsp;

Gate 1 — Provider and location validation

&nbsp;

Run a small set of known businesses/keywords/coordinates.

&nbsp;

Confirm:

&nbsp;

coordinate handling;

result order;

business identity;

ranking depth;

raw-response preservation;

API reliability;

cost.

&nbsp;

Gate 2 — Pilot grid collection

&nbsp;

Approximately:

&nbsp;

3–5 industries;

5–10 markets;

all four canonical query classes;

the full 13-point first-pilot geometry with the nested 9-point candidate explicitly tagged inside it, including structural-water eligibility/exclusion states.

&nbsp;

Collect several weeks before major explanatory conclusions.

&nbsp;

Gate 3 — Canonical business and distance layer

&nbsp;

Resolve:

&nbsp;

Place IDs;

CIDs;

business coordinates;

distance features;

local-result history.

&nbsp;

Gate 4 — Core derived metrics

&nbsp;

Implement:

&nbsp;

Top 3 coverage;

Top 10 coverage;

share of voice;

distance decay;

ranking radius;

excess performance;

directional metrics.

&nbsp;

Gate 5 — Matched controls

&nbsp;

Implement:

&nbsp;

same-coordinate controls;

distance-matched controls;

same-business spatial comparisons;

incoming/outgoing Top 3 comparisons.

&nbsp;

Gate 6 — Core enrichment

&nbsp;

Add:

&nbsp;

GBP;

reviews;

organic rankings;

website relevance;

authority/backlinks;

topical footprint;

NAP/entity corroboration.

&nbsp;

Gate 7 — Longitudinal transition system

&nbsp;

Detect:

&nbsp;

gains;

losses;

coverage expansion;

radius changes;

Top 3 entry/exit;

competitor swaps.

&nbsp;

Gate 8 — Full primary research panel

&nbsp;

Expand only after cost, reliability, and data-quality validation.

&nbsp;

Gate 9 — Dashboard, monthly full-panel report, and weekly fixed Research Sentinel change report

&nbsp;

Produce versioned analytical reports.

&nbsp;

Gate 10 — Strategy Evidence integration

&nbsp;

Only after sufficient history exists should findings begin driving client recommendation states beyond exploratory testing.

&nbsp;

# 65\. Initial Research Cadence

&nbsp;

Production collection is monthly for the full panel and weekly for the permanently fixed Research Sentinel.

&nbsp;

The platform should collect every eligible full-panel coordinate-query combination monthly and every eligible Sentinel coordinate-query combination weekly regardless of whether rankings appear unchanged. Exceptional full snapshots require predefined, logged Sentinel triggers.

&nbsp;

Historical rank observations cannot be reliably reconstructed later.

&nbsp;

Enrichment should not be exhaustive every week.

&nbsp;

This produces:

&nbsp;

exhaustive longitudinal ranking observation \+ selective temporally valid enrichment

&nbsp;

# 66\. Strategy Evidence Framework Integration

&nbsp;

Geo-grid findings should feed the same research-to-strategy framework used by the broader platform.

&nbsp;

A research finding should preserve separately:

&nbsp;

outcome studied;

predictor/signal;

effect direction;

effect magnitude;

uncertainty;

sample size;

markets;

industries;

query types;

distance ranges;

replication status;

matched-control status;

longitudinal status;

within-entity evidence;

intervention evidence;

proxy risk;

actionability;

applicability.

&nbsp;

A finding should not become a client recommendation solely because:

&nbsp;

p \< 0.05;

a machine-learning model uses the variable;

winners have more of the variable;

the relationship appears intuitive.

&nbsp;

# 67\. Client Gap Analysis

&nbsp;

For an applicable research finding, compare the client against:

&nbsp;

AIO/Maps-visible competitors;

geo-grid winners;

distance-matched competitors;

market benchmarks;

historical client baseline.

&nbsp;

Example:

&nbsp;

Research finding:

&nbsp;

Businesses that maintain unusually strong Top 3 performance 4–6 miles from their locations have substantially stronger target-service topical footprints than distance-matched competitors.

&nbsp;

Client:

&nbsp;

Topical footprint materially below applicable winner distribution.

&nbsp;

Recommendation:

&nbsp;

Potentially expand service-topic coverage.

&nbsp;

But recommendation confidence must still consider:

&nbsp;

longitudinal evidence;

proxy risk;

conventional SEO value;

implementation cost;

client applicability.

&nbsp;

# 68\. Intervention Tracking

&nbsp;

When the agency deliberately implements a research-informed change, create an intervention record.

&nbsp;

Potential interventions:

&nbsp;

category change;

service update;

review-generation initiative;

service-specific content expansion;

internal-link change;

local link acquisition;

citation cleanup;

entity-corroboration campaign;

GBP posting experiment.

&nbsp;

Record:

&nbsp;

client/business;

target keyword;

target geography;

intervention type;

implementation date;

exact change;

expected mechanism;

primary outcome;

secondary outcomes;

untreated comparison keywords;

comparison businesses;

pre-period;

post-period.

&nbsp;

Never rewrite historical interventions.

&nbsp;

# 69\. Intervention Analysis

&nbsp;

Measure whether an intervention is followed by changes in:

&nbsp;

exact cell rank;

Top 3 coverage;

Top 10 coverage;

ranking radius;

geographic share of voice;

excess geographic performance;

treated versus untreated keywords;

treated versus comparison areas;

treated business versus matched competitors.

&nbsp;

One client intervention is not proof.

&nbsp;

But repeated well-documented interventions can strengthen, weaken, or refine observational evidence.

&nbsp;

# 70\. Success Criteria

&nbsp;

The platform succeeds when it can reliably answer:

&nbsp;

How does Maps ranking probability change with searcher distance?

How does that relationship vary by vertical and market?

Which businesses outperform proximity expectations?

What characteristics distinguish those businesses?

Which signals predict Top 3 visibility?

Which signals predict broad geographic Top 3 coverage?

Which signals predict ranking radius?

Which signals matter more at long distances?

Which signals are likely proxies rather than actionable levers?

What changed before a business gained geographic visibility?

What changed before it lost visibility?

What distinguishes durable gains from temporary churn?

Why did one business replace another in the Top 3?

Why does the same business rank differently at equal distances in different directions?

Which findings survive matched-control and longitudinal analysis?

Which findings apply to a specific client?

What should the client test or implement?

Did that intervention subsequently change the intended geographic outcome?

&nbsp;

# 71\. Explicit Non-Goals for V1

&nbsp;

Do not initially build:

&nbsp;

a public geo-grid SaaS;

a white-label reporting product;

hundreds of industries;

every US city;

daily collection across the entire universe;

every possible grid size;

opaque Local SEO Scores;

automated causal recommendations;

complex machine-learning models before sufficient data exists;

exhaustive social crawling;

exhaustive enrichment every week;

synthetic precision unsupported by provider methodology.

&nbsp;

Priority:

&nbsp;

collect clean, comparable, spatially controlled, longitudinal local-ranking data first.

&nbsp;

# 72\. Core Data Model

&nbsp;

Conceptual hierarchy:

&nbsp;

EXPERIMENT&nbsp;&nbsp;

→ MARKET&nbsp;&nbsp;

→ KEYWORD FAMILY&nbsp;&nbsp;

→ KEYWORD&nbsp;&nbsp;

→ GRID DEFINITION&nbsp;&nbsp;

→ GRID POINT&nbsp;&nbsp;

→ GRID RUN&nbsp;&nbsp;

→ GRID OBSERVATION&nbsp;&nbsp;

→ LOCAL RESULT&nbsp;&nbsp;

→ BUSINESS

&nbsp;

Parallel relationships:

&nbsp;

BUSINESS&nbsp;&nbsp;

→ historical location

&nbsp;

BUSINESS&nbsp;&nbsp;

→ GBP snapshots

&nbsp;

BUSINESS&nbsp;&nbsp;

→ review snapshots

&nbsp;

BUSINESS&nbsp;&nbsp;

→ website/domain/pages

&nbsp;

BUSINESS&nbsp;&nbsp;

→ backlink/authority snapshots

&nbsp;

BUSINESS&nbsp;&nbsp;

→ NAP/entity corroboration

&nbsp;

BUSINESS&nbsp;&nbsp;

→ social/external review evidence

&nbsp;

BUSINESS × KEYWORD × GRID POINT × DATE&nbsp;&nbsp;

→ spatial ranking observation

&nbsp;

BUSINESS × KEYWORD × GRID × DATE&nbsp;&nbsp;

→ derived geographic metrics

&nbsp;

BUSINESS × KEYWORD × EVENT DATE&nbsp;&nbsp;

→ transition event

&nbsp;

ANALYSIS DATASETS&nbsp;&nbsp;

→ RESEARCH FINDINGS&nbsp;&nbsp;

→ CLIENT OPPORTUNITIES&nbsp;&nbsp;

→ RECOMMENDATIONS&nbsp;&nbsp;

→ INTERVENTIONS&nbsp;&nbsp;

→ OUTCOMES&nbsp;&nbsp;

→ REFINED EVIDENCE

&nbsp;

# 73\. Most Important Architectural Principle

&nbsp;

The system must preserve the difference between:

&nbsp;

Rank

&nbsp;

Where the business appears at one coordinate.

&nbsp;

Coverage

&nbsp;

Across how much of the grid the business meets a ranking threshold.

&nbsp;

Geographic reach

&nbsp;

How far from the business strong visibility persists.

&nbsp;

Excess geographic performance

&nbsp;

How much better or worse the business performs than expected given proximity and competitive context.

&nbsp;

Persistence

&nbsp;

Whether that visibility is durable over time.

&nbsp;

Transition

&nbsp;

Whether geographic visibility gained, lost, expanded, contracted, or changed competitively.

&nbsp;

These outcomes must not be collapsed into one arbitrary score.

&nbsp;

# 74\. End-State Research Asset

&nbsp;

After sufficient history, the platform should contain hundreds of thousands or millions of controlled spatial local-search observations linking:

&nbsp;

query;

market;

fixed search coordinate;

business;

business coordinate;

searcher distance;

direction;

Maps ranking;

geographic coverage;

ranking radius;

competitive environment;

GBP categories;

GBP services;

reviews;

review velocity;

review semantic relevance;

organic performance;

website topical relevance;

backlinks;

anchors;

citations;

entity corroboration;

social activity;

business history;

geographic persistence;

ranking transitions;

intentional interventions.

&nbsp;

The end goal is not simply to answer:

&nbsp;

How do I improve a geo grid?

&nbsp;

The goal is to build an empirical model of how Google allocates local-business visibility across geographic space:

&nbsp;

how strongly proximity constrains visibility;

which signals appear to extend visibility beyond proximity;

where geographic ranking boundaries form;

how competitors replace one another;

which changes tend to precede expansion or contraction;

which relationships survive stronger controls;

and which findings can responsibly influence client strategy.

&nbsp;

Combined with the AIO and ChatGPT research modules under the Unified Research Architecture, the broader system becomes a longitudinal Local Search Research & Intelligence Platform capable of studying the same canonical businesses across Maps, AI-generated local search, ChatGPT recommendations/evidence, organic search, entity/source surfaces, and deliberate SEO interventions.

&nbsp;

&nbsp;

75\. GOVERNING CURRENT MAPS/ORGANIC PILOT METHODOLOGY — 2026-09-09

Status: LOCKED for current implementation planning, subject to the explicit unresolved post-pilot Maps/Organic 13-versus-9 production decision below. This section supersedes conflicting older planning examples elsewhere in this document; it does not pre-decide the nested 9-point candidate.

&nbsp;

Production universe: 25 industries × 50 permanent markets × four canonical query classes. Q1 \= \[service\] near me. Q2 \= best \[service\] near me. Q3 \= \[industry-specific high-need/commercial modifier\] \[service\] near me, prospectively selected and locked per industry. Q4 \= \[service\] in \[city\].

&nbsp;

First-pilot Maps/Organic spatial design: collect all 13 deterministic candidate coordinates per market—center plus N/S/E/W at 1, 3, and 5 miles—and tag the approved nested 9-point production candidate plus the four incremental points within that same immutable coordinate registry. Candidate points over ocean, lake, or river are excluded before SERP observation, never relocated, and represented as structural missingness. Coverage and spatial denominators use eligible points, not an assumed 13\. The pilot must preserve explicit flags for full\_13\_member, nested\_9\_member, incremental\_4\_member, structural\_water\_exclusion, and geometry\_version so 9-versus-13 comparisons are reproducible.

&nbsp;

Cadence: full 25 × 50 Maps/Organic panel monthly. Fixed representative Sentinel \= 5 industries × 10 markets weekly using the same four Maps/Organic query classes and the applicable eligible Maps/Organic coordinate membership. The full-panel week doubles as the Sentinel run. Predefined Sentinel thresholds may trigger an exceptional full snapshot. Do not infer from this paragraph that AIO shares the same coordinate geometry; AIO uses its own approved 9-point design.

&nbsp;

Maps result depth: Top 10 is the primary production outcome depth. Top-20 references elsewhere are auxiliary/historical unless separately versioned.

&nbsp;

The former 73-point design is retained only as historical/high-resolution validation provenance; it is not the current production-selection comparison. The current pilot decision is nested 9 versus full 13 for Maps/Organic. Because all 13 are collected initially, measure unique businesses under 9 and 13, businesses found only by the incremental four points, incremental SERP observations, incremental canonical entities after cross-surface deduplication, incremental paid enrichment and downstream website/review/backlink/brand-demand/Top-50/processing/storage cost, plus added spatial information, distance-decay information, directional asymmetry, visibility-radius behavior, expansion/contraction, longitudinal transitions, and explanatory-variable variation. Do not assume 13→9 yields proportional enrichment savings. The post-pilot decision must compare the marginal annual cost of points 10–13 against their marginal unique entities plus spatial, longitudinal, and explanatory information.

&nbsp;

Organic Top-10 observations are matched context for analysis and participate in the same shared canonical entity/signal infrastructure. A valid resolved business must not be excluded from explanatory-variable enrichment merely because it appears only on Organic or another single research surface. Paid enrichment still passes through the parent universal baseline/progressive gate, canonical economic-unit deduplication, freshness/TTL checks, caching, and analysis-specific eligibility. Maps, Organic, AIO, and ChatGPT reuse the global canonical entity registry and enrichment cache under the parent platform PRD.

&nbsp;

Any older text specifying 9×9/81-point production grids, 73-point routine production, 10–15 industries, 20–30 markets, two or three production keywords, weekly full-universe collection, Top-20 primary retention, or required GBP Q\&A is superseded unless explicitly labeled as historical/pilot/auxiliary methodology.

&nbsp;

76\. HISTORICAL / SUPERSEDED SOCIAL EVIDENCE METHODOLOGY — DO NOT IMPLEMENT AS CURRENT PRODUCTION

&nbsp;

RECONCILIATION NOTICE — 2026-09-09: The indexed-social/site-restricted searches and universal 90-day activity-check methodology preserved below is superseded for current production. Current social/community evidence collection uses the shared per-canonical-business Brand \+ Service \+ Location Google Organic search through the first 5 pages / Top 50 results, with complete result classification across first-party website, official social, third-party social, Reddit/community/forum, directory/review, news/editorial, trade/professional, local publication/media, BBB and other third-party classes as applicable. Direct social-profile/activity collection is selective and analysis/fanout/evidence-driven, not universal. Preserve the historical text below only for provenance or a separately approved bounded validation experiment.

Status: SUPERSEDED / HISTORICAL ONLY. Nothing in the remainder of Section 76 authorizes production scheduling of universal platform-restricted site: searches, universal Top-20 social SERPs, universal 90-day official-profile checks, or their historical cost model. The current Top-50 Brand \+ Service \+ Location evidence layer and selective direct-social enrichment control.

&nbsp;

Research purpose: measure whether Maps-visible businesses are socially active, whether Google surfaces indexed social evidence connecting businesses to the measured service × city, and whether that evidence is first-party or third-party corroboration. These are explanatory/predictive candidate variables, not assumed ranking factors.

&nbsp;

HISTORICAL ONLY — formerly proposed indexed-social collection was market-level rather than per-GBP, using platform-restricted Facebook/Instagram/YouTube/Reddit Google queries and Top-20 retention. Do not schedule these searches in current production. Their exact historical syntax/settings may be retained solely for provenance or an explicitly approved validation experiment.

&nbsp;

HISTORICAL COST/VOLUME PROVENANCE ONLY — the superseded design implied 5,000 platform-restricted searches and at most 100,000 returned rows per full pass. These counts are non-operative and must not enter current collection manifests, scheduler volumes, cost forecasts, or database acceptance criteria.

&nbsp;

For every returned result, preserve platform, industry/market/service context, rank, URL, title/snippet, profile/handle when derivable, collection timestamp, raw provenance, result/artifact type, and classification version. Classify service relevance, geography relevance, service × geography relevance, and evidence ownership as first\_party, third\_party, or ambiguous/unknown.

&nbsp;

Third-party evidence is first-class. Resolve businesses mentioned, tagged, featured, recommended, reviewed, or otherwise corroborated by customers, creators/influencers, community accounts, partners, media, organizations, and other independent social sources. Cross-reference all relevant social-discovered entities against the shared canonical registry. Store whether each entity is found in Maps/AIO/Organic where applicable and preserve unmatched relevant social-discovered businesses rather than discarding them.

&nbsp;

Maps-facing derived variables may include indexed\_social\_evidence\_present, indexed\_first\_party\_social\_evidence\_present, indexed\_third\_party\_social\_evidence\_present, indexed\_first\_and\_third\_party\_evidence\_present, unique\_third\_party\_social\_profiles, best\_indexed\_social\_rank, best\_first\_party\_social\_rank, best\_third\_party\_social\_rank, service\_location\_relevant\_indexed\_social\_count, maps\_business\_has\_indexed\_social\_match, social\_serp\_business\_found\_in\_maps, and platform-specific equivalents. No arbitrary Social Authority or Social Corroboration composite score is authorized in V1.

&nbsp;

HISTORICAL ONLY — the superseded design proposed a universal lightweight 90-day activity check for resolved Facebook/Instagram/YouTube profiles. Do not perform that check universally in current production. The fields may remain available for bounded validation, fanout/evidence-directed inspection, or another explicitly approved analysis where direct-social collection is justified.

&nbsp;

The production social layer does NOT universally download every post from the prior 90 days, fixed 10/20/50-post corpora, comment bodies, video transcripts, or all social images. Exact artifacts surfaced by the indexed-social SERPs or cited/linked by AIO may be preserved/analyzed as observed evidence. Deeper direct-social collection is reserved for a versioned validation experiment or separately approved analysis.

&nbsp;

Processing order: deterministic parsing/entity/service/location rules → cached classifications → embeddings/vector relevance where useful → LLM only for unresolved cases. Preserve confidence and provenance. Missing social profile, inaccessible profile, ambiguous profile resolution, unavailable activity check, observed inactivity, and no indexed-social result are distinct states and must not be encoded as equivalent zeros.

&nbsp;

HISTORICAL ONLY — the former quarterly indexed-social and monthly 90-day activity cadence is superseded and must not be scheduled. Any future bounded direct-social validation must define its own versioned cadence and preserve temporal alignment/future-data-leakage safeguards.

&nbsp;

Validation: run a stratified direct-social sample to measure how much relevant service × geography social content the Google site-restricted method misses. Compare quoted/unquoted syntax, platform differences, precision/recall where estimable, entity matching, and first-party/third-party classification. Indexed-social absence means only that qualifying evidence was not surfaced by the frozen Google method/depth; it does not prove the underlying social content does not exist.

&nbsp;

HISTORICAL COST MODEL — these prior social-only allowances are superseded because the underlying universal site-search/activity methodology is no longer production. Current cost planning is owned by the parent PRD and must use the Top-50 business-centric evidence layer plus actual selective direct-social usage and telemetry.

&nbsp;

Epistemic safeguard: social activity, indexed first-party evidence, indexed third-party corroboration, underlying unindexed social behavior, Maps visibility, and AIO citation/selection are distinct constructs. Correlation, temporal precedence, or predictive importance does not establish a Maps ranking factor.

&nbsp;

76.1 HISTORICAL ONLY — Superseded Reddit Indexed-Community Expansion

Reddit is added to the indexed-social/community Google site-restricted search set. For each of the 25 industries × 50 markets, run the frozen service × city treatment across Facebook, Instagram, YouTube, and Reddit. Conceptual Reddit form: site:reddit.com \[service\] \[city\].

&nbsp;

HISTORICAL ONLY — this former 5,000-search / 100,000-row workload is superseded and must not be used for current manifests or cost calculations.

&nbsp;

For Reddit results, preserve and classify subreddit/result context where derivable, business/entity mentions, service relevance, geography relevance, service × geography relevance, rank, URL, title/snippet, observed\_at, evidence ownership/affiliation, and entity-match confidence. Reddit should generally be analyzed as community/third-party corroboration, while allowing first-party classification when a business-controlled or confidently attributable Reddit account/post is identified.

&nbsp;

Do not add Reddit to the universal official-profile 90-day activity check. That lightweight activity layer remains Facebook, Instagram, and YouTube only. Reddit direct-post/comment crawling is outside universal V1 unless separately approved as a versioned experiment.

&nbsp;

The added Reddit search increases indexed-social query count by one-third relative to the prior three-platform design. It does not imply a one-third increase in total social or platform cost; incremental cost must be measured from actual provider usage.

&nbsp;

&nbsp;

&nbsp;

77\. APPROVED INDUSTRY PANEL SUBSTITUTIONS & QUERY TEMPLATES — 2026-09-09

Status: LOCKED for the substitutions and literal query templates explicitly approved below. The remaining proposed industry membership, permanent markets, and Sentinel membership remain subject to separate approval unless already locked elsewhere.

&nbsp;

Approved substitutions within the 25-industry production panel:

\- Orthodontics → Optometry

\- Dermatology → Urgent Care

\- Property Management → Handyman

\- Funeral Home → Chinese Restaurant

\- Auto Body → Locksmith

&nbsp;

Approved replacement-industry production queries:

\- Optometry — Q1 \`optometrist near me\`; Q2 \`best optometrist near me\`; Q3 \`eye exam near me\`; Q4 \`optometrist in \[CITY\]\`.

\- Urgent Care — Q1 \`urgent care near me\`; Q2 \`best urgent care near me\`; Q3 \`walk in clinic near me\`; Q4 \`urgent care in \[CITY\]\`.

\- Handyman — Q1 \`handyman near me\`; Q2 \`best handyman near me\`; Q3 \`same day handyman near me\`; Q4 \`handyman in \[CITY\]\`.

\- Chinese Restaurant — Q1 \`Chinese restaurant near me\`; Q2 \`best Chinese restaurant near me\`; Q3 \`Chinese food near me\`; Q4 \`Chinese restaurant in \[CITY\]\`.

\- Locksmith — Q1 \`locksmith near me\`; Q2 \`best locksmith near me\`; Q3 \`auto locksmith near me\`; Q4 \`locksmith in \[CITY\]\`.

&nbsp;

Locksmith Q3 decision: \`auto locksmith near me\` is canonical. Do not substitute \`emergency locksmith near me\` or \`24 hr locksmith near me\` within this methodology version. This Q3 intentionally tests a commercially meaningful service subtype rather than merely an urgency/availability modifier.

&nbsp;

All five replacement query sets inherit the four-class Maps/Organic contract, the full 13-point first-pilot geometry with the nested 9-point production candidate explicitly tagged, monthly Full Panel cadence, weekly Sentinel cadence when the industry-market cell belongs to the Sentinel, Top-10 Maps retention, canonical entity resolution, and shared enrichment rules. The post-pilot Maps/Organic production geometry remains an explicit 9-versus-13 decision. Literal query text is versioned and must not be retrospectively changed in response to observed outcomes.

&nbsp;

78\. LOCKED — Maps Enrichment Economics, Incremental Histories & Sentinel Gating — 2026-09-09

&nbsp;

This section inherits the parent platform's universal enrichment eligibility gate and governs Maps-specific application. It changes enrichment economics, not the approved Maps observational panel.

&nbsp;

78.1 Shared enrichment gate and economic-unit reuse

After every Maps observation, preserve the immutable observation first, then canonicalize. Before any paid enrichment ask: already sufficiently fresh? materially changed? analytically relevant? paid enrichment required? Globally deduplicate at the correct provider economic unit. Repeated appearance of the same canonical business/GBP/domain/URL across queries, coordinates, result positions, Full Panel/Sentinel waves, or Maps/AIO/Organic/ChatGPT/social observations MUST NOT trigger duplicate paid enrichment. Shared enrichment remains separate from raw Maps rank observations.

&nbsp;

78.2 Reviews

Recurring broad Maps collection should cheaply preserve current review count/rating and derive count/rating change and review velocity where supported. Review bodies are append-only incremental history where technically possible; reuse previously stored bodies. Store provider review IDs and/or robust content hashes with provenance. If a known business moves from N reviews to N+k, seek the k newly observed reviews rather than repurchasing/reprocessing the complete N+k history where technically possible. Expensive sentiment/topic/service/location processing applies to new/materially changed review text unless a specified analysis requires historical reprocessing. Missing/blocked review bodies are not zero reviews.

&nbsp;

78.3 Website/site processing

Preserve the existing approved website/site research methodology and corpus. Do NOT replace it with a core-pages-only collection design. Use content/rendered-text/structured-data/sitemap hashes, HTTP/canonical/last-modified/ETag state where reliable, page-type/internal-link state, and temporal check/change fields to avoid expensive reprocessing of unchanged content. Reuse prior extraction, embeddings, classifications, page-topic, service/location, and structured-data features when the source version is unchanged. Changed content creates a new temporal version and may trigger re-embedding/reclassification; prior versions remain immutable.

&nbsp;

78.4 Progressive entity resolution and classification

Maps resolution inherits the parent staged resolver: stable identity evidence → inexpensive multi-signal matching → embeddings where useful → LLM adjudication for unresolved ambiguity → human review where scientifically necessary. Preserve supporting/conflicting evidence, method/stage/confidence/version/override provenance. Likewise, deterministic parsing/rules/provider metadata/lexical structured comparison precede embeddings and LLM classification when scientifically equivalent.

&nbsp;

78.5 TTLs

Slow identity attributes use signal/provider-specific TTL or change-triggered verification rather than automatic weekly/monthly repurchase. Volatile explanatory variables retain their approved cadence. Every cached/reused value preserves observed/effective/verified times, freshness state, TTL policy/version, and stale/unknown semantics; cache reuse is never represented as a fresh observation.

&nbsp;

78.6 Backlinks — governing cadence

For the regular monthly Full Panel population, approved backlink/link variables and histories remain MONTHLY. This includes approved domain-level DR/RD, URL-level UR/RD, GBP-linked page, homepage, service-page, control-page, and approved backlink-history/detail variables. Deduplicate globally by canonical domain/URL/provider economic unit and reuse one sufficiently fresh provider purchase across all eligible surface/query/coordinate observations. Monthly cadence is not replaced by quarterly collection.

&nbsp;

For the weekly Research Sentinel, retain the already-approved LIGHTWEIGHT WEEKLY backlink/link monitoring. Sentinel does not trigger a universal full backlink reconstruction every week. Deeper backlink inspection is event-/analysis-triggered.

&nbsp;

78.7 Event-driven Sentinel enrichment

Weekly Sentinel collection continues at its approved search-observation resolution. External explanatory enrichment is targeted: Sentinel observation → compare with prior Sentinel/full-wave state → apply predefined/versioned change rule → identify affected entities/assets/signals → targeted enrichment. Potential triggers include major Maps visibility change, Top-3/Top-10 entry/loss, material cross-surface composition/state change, and entity/source/destination transition. Thresholds must be defined prospectively from analysis contracts/baseline variance, never retrofitted by an LLM after outcomes are observed.

&nbsp;

78.8 Tiering and safeguards

Use parent Tier 1 universal/cheap, Tier 2 progressive, Tier 3 study-specific/deep enrichment. Deep case/control/transition enrichment must follow valid analysis-specific selection rules and cannot use outcome-conditioned information illegitimately. No arbitrary composite scores are introduced.

&nbsp;

78.9 Explicit preservation of production design

Nothing in this section changes the locked 25-industry × 50-market Full Panel, four canonical Maps/Organic queries, structural water exclusions, Maps Top-10 depth, monthly Full Panel, fixed 5×10 weekly Sentinel, or existing brand-demand methodology. For the first pilot, Maps/Organic collect the full 13-point geometry and tag the nested 9-point candidate; the post-pilot production geometry is not yet permanently chosen. Current social/community evidence uses the shared Top-50 Brand \+ Service \+ Location layer, not the historical universal site-search/90-day layer. Organic is NOT reduced to center-only/5-point production. Website research is NOT reduced to a small core-page universe.

&nbsp;

&nbsp;

LOCKED CROSS-PLATFORM UPDATE — 2026-09-09 — SEARCH-EVIDENCE & ENRICHMENT ECONOMICS

&nbsp;

Maps/Organic retain the full 13-point geometry for the first pilot while the nested 9-point production candidate is measured within it. The AIO-specific 9-point geometry is separate and does not pre-decide the Maps/Organic post-pilot choice.

&nbsp;

A shared Brand/Service/Location Search-Evidence Layer is now locked at Top 50 / first 5 Google organic result pages per eligible canonical business. The canonical query combines brand name \+ service \+ location. Preserve the entire ranked Top-50 SERP and classify first-party, official social, third-party social, Reddit/community/forum, directory/review, news/editorial, trade/professional, and other evidence classes. Absence means not observed in Top 50, never zero/no presence.

&nbsp;

Maps observations participate in the same canonical business/domain/URL/source graph and may reuse this evidence layer. Cost reduction must occur through global canonicalization, economic-unit deduplication, cache reuse, TTLs, incremental reviews, website change detection, and provider batching—not by excluding valid observed Maps businesses from explanatory-variable enrichment.

&nbsp;

Website retrieval is planned through ScrapeOwl while retaining the existing change-detection/content-hash architecture. The Top-50 decision supersedes the discussed Top-100/10-page planning option.

&nbsp;

&nbsp;

IMPLEMENTATION-READINESS CHECKPOINT — 2026-09-09 — CURRENT / GOVERNING

This checkpoint supersedes older next-task/implementation-status language in this PRD without changing the locked Maps/Organic scientific methodology.

\- Shared implementation artifacts now complete: Physical Supabase/Postgres Schema Contract v0.1; Operational QA / Wave Acceptance Contract v0.1 plus machine-readable rules/SQL seed. The collection manifest v0.7 is materially built and awaits deterministic structural-water application/final executable freeze.

\- Active next artifact: bounded Pilot → Production Protocol, recommended starting scale 3 industries × 5 markets.

\- Maps/Organic pilot execution MUST collect the full approved 13-point geometry (center \+ N/S/E/W at 1, 3, and 5 miles) and tag the nested 9-point production candidate. Structural water exclusions remain exclusions and must be frozen before geo-surface execution.

\- The pilot must measure the four incremental points' marginal unique canonical businesses/entities after deduplication, downstream enrichment/processing/storage cost, spatial information, distance-decay information, directional asymmetry, visibility-radius behavior, expansion/contraction and longitudinal transitions, and explanatory-variable variation. Observation-count reduction alone is not evidence that 9 points is sufficient.

\- Do not permanently select 13 versus 9 before the pilot comparison. That choice is the pre-authorized methodology question the pilot may resolve; all other methodology remains frozen unless an explicit amendment is approved.

\- The shared physical schema, canonical graph, enrichment histories, cost ledger, raw-payload system, QA system, and finding infrastructure remain parent-owned. This child PRD must not create duplicate stores or truth systems during implementation.

\- Pilot success means the Maps/Organic collector can produce immutable/raw and normalized evidence, deterministic job identity, valid result-depth capture, correct structural-missingness semantics, entity-resolution provenance, cost/cache telemetry, and QA acceptance data sufficient for the production go/no-go decision.

&nbsp;

&nbsp;

LOCKED — APPROVED BOUNDED PILOT → PRODUCTION PROTOCOL — 2026-09-09

&nbsp;

Status: APPROVED. This section supersedes prior language describing the 3-industry × 5-market pilot or 13-versus-9 comparison as merely recommended or pending protocol approval.

&nbsp;

Pilot membership is fixed at IND010 Locksmith, IND019 Urgent Care, and IND022 Chinese Restaurant across MKT008 Vancouver WA, MKT011 Phoenix AZ, MKT021 Chicago IL, MKT040 Birmingham AL, and MKT049 New York City NY: 15 industry×market cells.

&nbsp;

Maps and Organic each contribute 780 pre-water scientific jobs: 15 cells × 4 approved Google-core queries × 13 intended points. Exact query wording is inherited from frozen Manifest v1.0. Runtime rendering may replace the literal \[CITY\] token with the registered market city only; it must not paraphrase or rewrite the remaining query text.

&nbsp;

The full Maps/Organic pilot geometry is center \+ N/S/E/W at 1, 3, and 5 miles. Structural-water eligibility is resolved before collection under the approved national areal-hydrography mask. Intended points are retained even when excluded. structural\_water\_exclusion is structural missingness, never rank zero or nonappearance, and excluded points are never relocated, randomized, substituted, or imputed. manual\_review is not executable. A center configuration\_failure blocks the affected market/surface geometry until corrected. The water gate must be completed for all 1,100 configured coordinates before Manifest v1.0 is frozen for execution.

&nbsp;

Provider behavior remains the approved DataForSEO Standard asynchronous profile. Maps uses /v3/serp/google/maps/task\_post and /v3/serp/google/maps/task\_get/advanced/{id}, priority 1, English, desktop/Windows, location\_coordinate {lat},{lon},17z, depth 10, search\_this\_area=true, search\_places=false, and immutable retention of the full advanced response. Organic uses /v3/serp/google/organic/task\_post and /v3/serp/google/organic/task\_get/advanced/{id}, priority 1, English, desktop/Windows, location\_coordinate {lat},{lon},200, depth 10, load\_async\_ai\_overview=false, and immutable retention of the full advanced response. Endpoint types must not be mixed in one provider POST; batching is capped at the approved 100 tasks per POST.

&nbsp;

Pilot max\_attempts \= 3 per deterministic job: initial attempt plus at most two retries for QA-authorized technical failure only. A valid short result set or business nonappearance is a scientific observation and must not be retried to obtain a denser or more favorable result. Technical retries remain attempts under the same deterministic job.

&nbsp;

The 13-versus-9 comparison is within-wave and does not authorize two independent collections. Always collect all eligible points from the 13-point geometry. Derive nested-9 results from center \+ N/S/E/W at 1 mile \+ N/S/E/W at 5 miles. The incremental set is N/S/E/W at 3 miles. For the 15-cell pilot, each surface has 540 pre-water nested-9 jobs and 240 pre-water incremental 3-mile jobs; combined across Maps and Organic, nested-9 \= 1,080 and incremental \= 480 before structural-water exclusions.

&nbsp;

Decision rule: default RETAIN\_13. The pilot may issue PROPOSE\_9\_FOR\_APPROVAL only if measured marginal cost is clearly disproportionate to the incremental entity, spatial, longitudinal, and explanatory value of the four 3-mile points. No production geometry change occurs without explicit user approval. Mixed or insufficient evidence is INCONCLUSIVE — RETAIN\_13. No invented equivalence threshold and no outcome-driven optimization are permitted.

&nbsp;

Promotion to production requires the parent COMPLETE-only GO gate plus all mandatory failure drills, exact manifest/database reconciliation, immutable raw evidence verification, parser/surface integrity, entity-resolution execution, cost attribution, quarantine isolation, reproducible rebuild, and separable 13-versus-9 telemetry. PARTIAL means REMEDIATE, not GO.

&nbsp;

&nbsp;

LOCKED — CIVIC-CENTER MARKET ANCHOR AMENDMENT — 2026-09-09

&nbsp;

Status: APPROVED before first live collection. For prospective Maps/Organic collection, Census Gazetteer representative/internal points are superseded as the operative market-center origin by the shared platform methodology CIVIC\_CENTER\_ANCHOR\_V1\_2026-09-09.

&nbsp;

Each of the 50 markets uses one frozen official civic-government anchor selected prospectively from: official City Hall; if no conventional City Hall exists, the primary municipal government headquarters/civic center; if a multi-building municipal campus exists, the main municipal seat/public-government headquarters. Exact address, anchor label/type, WGS84 EPSG:4326 latitude/longitude at 7-decimal precision, coordinate/source provenance, source URL(s), verification date, method version, and freeze state are retained. Census place/GEOID fields remain market-identity metadata and historical provenance, not the spatial origin.

&nbsp;

The approved Maps/Organic geometry is then regenerated geodesically from that frozen anchor without changing the treatment: center plus N/S/E/W at 1, 3, and 5 miles. The first pilot still collects all eligible 13 points. The nested 9-point candidate remains center \+ four 1-mile \+ four 5-mile points; the four 3-mile points remain the incremental comparison set. Point IDs, bearings, distance values, nested/full membership, Top-10 outcome semantics, DAVS/Effective Ranking Radius research, and the conservative RETAIN\_13 decision protocol are unchanged.

&nbsp;

After coordinate regeneration, every candidate point is classified under the approved 2025 Census TIGER/Line Areal Hydrography structural-water contract. A non-center water point is structural\_water\_exclusion and is retained as structural missingness without relocation, substitution, randomization, rotation, imputation, or zero encoding. A civic-center anchor intersecting an approved auto-exclude water polygon is configuration\_failure and blocks launch until corrected.

&nbsp;

This amendment changes only the deterministic spatial origin and derived coordinate values. It does not change the 25-industry × 50-market universe, four query classes, Sentinel membership/cadence, pilot membership, result depth, or pre-water candidate counts. Any older operative text specifying Census Gazetteer representative/internal points as the production center is superseded by this amendment; prior values may be retained only for provenance or an explicitly approved sensitivity study.

&nbsp;

&nbsp;

LOCKED — 2025 TIGER/LINE AREAWATER PACKAGING-EQUIVALENCE AMENDMENT — 2026-09-10

&nbsp;

User-approved implementation amendment. The structural-water source is the U.S. Census Bureau 2025 TIGER/Line AREAWATER polygon dataset. Official county-partitioned archives tl\_2025\_\<5-digit-county-GEOID\>\_areawater.zip are the preferred implementation packaging; the national 2025 AREAWATER GeoPackage is optional and is not a launch prerequisite.

&nbsp;

Retain exact filename, county GEOID, official Census URL, retrieval timestamp, SHA-256, and 2025 vintage for every archive used. Packaging does not change polygon-intersection semantics, the six approved auto-exclude MTFCC values, manual-review rules, center configuration-failure behavior, structural exclusion semantics, no-relocation/no-substitution rule, coordinate geometry, or missingness treatment.

&nbsp;

Manifest Candidate v0.9 records this amendment and is still pre-water. Any foreign-country/boundary treatment discovered during coordinate QA is a distinct methodology question and is not silently authorized by this packaging amendment.

&nbsp;

&nbsp;

LOCKED — U.S. COUNTRY-BOUNDARY ELIGIBILITY GATE — 2026-09-10

&nbsp;

Status: APPROVED METHODOLOGY AMENDMENT BEFORE FIRST LIVE COLLECTION.

&nbsp;

Every Maps/Organic coordinate is evaluated against a frozen official U.S. country boundary before the structural-water classifier.

&nbsp;

Rules:

\- Preserve the intended coordinate exactly.

\- Non-center outside-U.S. point → \`outside\_country\_exclusion\`; structural missingness; no ordinary provider job.

\- Center outside-U.S. point → \`configuration\_failure\`; configuration must be corrected before launch.

\- Only inside-U.S. points proceed to the locked 2025 Census TIGER/Line AREAWATER polygon classifier.

\- Crossing a city, county, or state boundary is allowed and is not itself an exclusion.

\- Never relocate, rotate, randomize, substitute, or impute an excluded point; never encode exclusion as rank/visibility zero.

\- Retain boundary source/version, source hash, classifier version, and point-level provenance.

\- Apply uniformly to all configured Maps/Organic points before Manifest v1.0 freeze.

&nbsp;

Detroit/Windsor is the motivating discovery only; this is a universal country-boundary rule and supersedes any water-only implementation that would permit out-of-U.S. dry land to become eligible.

&nbsp;