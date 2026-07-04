# How To Rank In Google Maps SOP

**Current as of:** 02 July 2026
**Goal:** Rank client GBPs in the Map Pack / Maps results for their target services and areas.
**Who this is for:** All local SEO clients with a GBP.
**When:** GBP optimization at onboarding; review/engagement/diagnostic work monthly.
**Assigned to:** per `_ORCHESTRATOR.md` §6 (roles matrix).
**Scope:** Maps/GBP ranking strategy — the factors, the optimization procedure, and the diagnostic tree. Grid *measurement* tooling lives with the rank trackers; link actions route to the Link Building SOP; site structure routes to the Architecture SOP.

> **Cross-references:** shared definitions, decision ownership, and global rules live in **`_ORCHESTRATOR.md`**. The GBP-linked page is defined in the Architecture SOP; stuck-grid link actions are owned by the Link Building SOP (§Link Building Targets for Maps).

---

# Part 1 — How Maps Ranking Works (Theory)

## Organic SEO vs. Local SEO

| | Organic SEO | Local SEO (GBP/Maps) |
|---|---|---|
| **Where it shows** | Main results, PAA, People Also Search For | Map Pack + Maps results |
| **Main signals** | Website-level: backlinks, on-page, content depth, authority, technical, entity/knowledge graph | Local business signals: GBP optimization, reviews, proximity, NAP consistency, listing engagement — **plus** all the organic signals |
| **User behavior** | Browsing, comparing, reading | Ready to act: call, directions, reviews. High-intent, fast |
| **Technical** | Speed, schema, mobile, crawlability | Those help (esp. local landing pages + schema), plus the GBP itself, reviews, local signals |
| **Searcher location** | Less influential unless the query is geo-specific | Central — proximity is a core factor |

**They feed each other:** strong organic (landing pages, links, authority) boosts GBP visibility; strong local (branded searches, reviews, engagement) boosts organic.

**What local has that organic doesn't:** the GBP itself as a ranking surface · proximity · physical vs. SAB status · GBP + third-party reviews · CTR to the GBP · driving directions · citations · LocalBusiness + industry schema · GBP embeds · RDF-triple mentions · less reliance on backlink DR/UR for authority · heavier weighting of brand/entity.

## The Five Core Factors

### 1. Proximity

Google assumes searchers want nearby businesses and won't travel far unless there's no option.

**Rules:**
- Expect ranking difficulty to increase in bands moving away from the business location; treat **~5 miles** as the practical radius for "near me" queries.
- **SABs** (service-area businesses, hidden address) carry weaker geographic signals than physical locations — *unless* the SERP for that query/area is majority-SAB, in which case the dampening disappears. **Hybrid** GBPs are not dampened.
- Ranking beyond ~5 miles is possible but exponentially harder — exceptions: low population density, low competition, or being a physical location among mostly SABs.

> **Working model (label, not fact):** difficulty steps appear at ~0.5 / 1.5 / 3 / 5 miles. Treat these bands as the agency's operating theory, validated against geo-grids — not published Google behavior.

### 2. Relevance

Does the GBP (and its linked website) match the query — service, product, and geography? GBPs and sites sit in topical "buckets"; ranking far from the core topic is much harder, same as organic.

**Relevance signals, strongest → weakest:**
1. Keyword in GBP name
2. Primary category
3. Secondary categories
4. Landing page the GBP links to
5. On-page optimization of the associated site (incl. schema)
6. GBP reviews — keywords in review text
7. CTR
8. Citations
9. Off-page signals: third-party reviews · social mentions · RDF-triple mentions ("XYZ Tree Service provides tree trimming") · backlink anchors + context
10. Services listed in the GBP
11. GBP posts with keyword
12. GBP image metadata
13. Website image data

### The GBP Landing Page

**The page the GBP links to is the second most important page of the site, after the home page.** Google looks directly at the GBP's landing page when deciding whether the GBP is relevant for a search.

*Example:* a user searches "plumber in Yorba Linda." A GBP whose landing page is the home page of an Anaheim company — title "plumber in anaheim," content and schema all Anaheim — **will always lose** to a GBP whose landing page targets "plumber in Yorba Linda" in the title tag, H1, content, and schema.

**Selection rules:**
1. The GBP points at the page targeting its **most valuable or most relevant keyword**.
2. **Multi-location companies: a dedicated inner page per GBP — the top-level location page** for that GBP's city. Pointing multiple GBPs at the home page is very inefficient and causes real ranking drops.
3. **Single GBP, multi-city companies:** rule 1 governs — point the GBP at the page targeting its most valuable keyword, typically the GBP city's local landing page for the main service (e.g. `/los-angeles/plumbing/`). *(Rule added 04 Jul 2026 — matches the Architecture SOP golden trace.)*
4. **Single-city, single-main-service companies:** the home page is acceptable *if* it is the page ranking for the main service keyword.
5. **SABs:** the GBP points at the **home page**.
6. Two GBPs may share a landing page **only if they are located in the same city**; otherwise one dedicated page per GBP.
7. The GBP-linked page receives **privileged internal linking** — links from the home page and other high-value pages by rule (Architecture SOP), and priority link building (Link Building SOP §Link Building Targets for Maps Rankings).

### 3. Entity (Knowledge Graph)

"Entity" here = the business itself in Google's knowledge graph (each GBP has an mreid, e.g. `/g/11tf9x7f80`). If Google can't fully resolve *who* the business is — location, services, sentiment, ownership, expertise — and connect it to its wider graph, it ranks the GBP less.

**Content volume & the entity vector:**
- **More on-topic content = a clearer entity.** Google consistently favors sites with more content: more pages give it a clearer picture of the services offered, the areas served, and the company's expertise and differentiators. **As long as pages stay close to the site's core topic / core service offerings, create as many pages as possible** — a top-level location page per targeted city, a top-level service page per service, the **complete service × city matrix** (local landing pages), and informational blog posts tightly targeting the site's main entity. *(This is exactly the site plan the Architecture SOP's Site Planning Algorithm emits — the entity model is the "why" behind its unbounded L×S rule.)*
- **The vector boundary:** too many blog posts drifting too far from the main entity's vector pull the site off-vector, confusing Google — causing **both organic and Maps ranking drops**. On-vector volume helps; off-vector volume actively hurts.
- **One site + one GBP = one topical bucket.** A business cannot rank for disparate service categories from a single site and GBP. Example: a house cleaning company will rank fine for "house cleaner near me," "house cleaner costa mesa," "apartment cleaner near me," "move in/move out cleaner near me" — but will **not** be able to rank that same site/GBP for "solar panel cleaning near me" or "bathroom remodeling near me."
- **The vector test (computable):** there is no fixed distance metric — vectors differ per entity. The operational test is empirical: **check the SERP/Map Pack for the target keyword. If other GBPs in your primary category are ranking for it, you can too; if none are, you can't.** *(Working model — the whole vector/bucket framework is the agency's operating theory of Google's behavior, validated in practice.)*
- **Reconciliation with PageRank Principle #2 (Architecture SOP):** on-vector page volume does dilute per-page equity — but **entity gain outweighs per-page dilution when pages are on-vector, and link building replenishes equity.** Both rules stand; this is the precedence.
- **Strategic implication (agent-relevant):** if a client wants to rank for a category outside their entity vector, the answer is **a separate legal entity/DBA + separate GBP + separate site** — not more pages on the existing site. This is a halt-and-recommend, not a page-creation task. The two entities *may* overlap in the knowledge graph (same parent company, same owner) — vector separation is about the site/GBP topical bucket, not hiding common ownership.
- **Expansion path for adjacent services** (e.g., a cleaning company adding pressure washing): build the on-ramp **before** expecting rankings — the service silo on the site, GBP secondary category, RDF triples, and citations mentioning the new service. **Do not expect the GBP to rank for it initially.** And watch the grid: **if rankings for existing services start to fall, the too-far service must be moved off — to a new site, or a subdomain of the original.**

**Entity is built by:** GBP title keyword · primary/secondary categories · website topic · on-page + schema · parent-company entity · owner/key-person entities · social content (company + third-party): Facebook, YouTube, Instagram (incl. hashtags), Pinterest, Reddit mentions · podcasts (company's own + owner appearances) · linked *and unlinked* brand mentions · RDF triples on third-party sites.

### 4. Popularity

Brand mentions plus how people interact with the GBP.

- **CTR** — clicks vs. competition help; below-competition CTR hurts. *(Working model: a GBP whose steady clicks stop gets thrown into an A/B re-rank test until clicks normalize — possibly at a much lower spot.)*
- **Engagement** — what users do after the click: call · website click · appointment · order · photo/video views · product/service exploration · post views. Low engagement for a query lowers that query *and its relatives*.
- **Also:** referral traffic from third-party sites/social · third-party mentions of the business and its people · driving-direction requests (physical/hybrid).

### 5. Prominence

Popularity × entity: is the business an *authority* for the topics it wants? Shown by: CTR vs. competition · count **and strength** of referring domains to the site — specifically the **homepage** and the **GBP-linked page** · brand mentions on highly trusted sites (incl. unlinked) · owner/key-person mentions on trusted sites · demonstrated expertise (blog + service-page on-page) · **recent reviews on trusted third-party platforms:** Yellowpages, Trustpilot, Brownbook, Foursquare, Facebook, DexKnows, TripAdvisor, ZocDoc, Avvo, Yelp.

> Note: source doc said "Avro" — corrected to **Avvo** (legal-vertical review site). Flag if you meant something else.

---

# Part 2 — GBP Optimization Procedure

Onboarding checklist, ordered by the relevance/entity signal strength above:

1. **GBP name — legal business name only. Never add keywords.** Keyword stuffing the name is a fast route to suspension. *(Rationale, stated honestly: a GBP with the keyword in its name is far easier to rank — Google consistently prioritizes keyword-named GBPs. We still don't do it; the suspension risk isn't worth it. The legitimate version is a business whose registered name genuinely contains the keyword.)*
2. **Primary category** — the single category matching the highest-value service. Check the top 3 competitors' primary categories on the target SERP; match unless there's a reason not to.
3. **Secondary categories** — every category matching a real service offered; nothing aspirational.
4. **Website link → the GBP-linked page** per the selection rules in Part 1 §The GBP Landing Page: multi-location → the city's top-level location page (dedicated per GBP); single-city single-service → home page if it ranks for the main keyword; SAB → home page. This page gets the LocalBusiness schema variant (Architecture SOP).
5. **Services — list all of them, including every location + service combination**, and **mirror them on the associated site**. *(The site plan's L×S local landing pages — Architecture SOP Step 5 — are the mirror: every GBP service should have its corresponding page, and vice versa.)*
6. **NAP** — exact match with site + citations (Citation Audit tool owns citation consistency).
7. **Attributes, hours, service areas** — complete everything applicable. SABs: list service-area cities up to **Google's max of 20**, drawn from the site plan's targeted cities.
8. **Photos** — goal: **2 per week**, ongoing.
9. **GBP posts** — **5 per week.** *(Mental model: the GBP is a home page and posts are its inner pages. For every keyword you want the GBP to rank for, post regularly on that topic, linking back to that keyword's page on the site — the post-to-page link mirrors internal linking.)*
10. **GBP embed** — embed the GBP on the site (entity signal; embeds are dofollow per the Link Building SOP).

> **Deprecated:** GBP Q&A — the feature no longer exists on Google Business Profiles. *(Also removed from the Part 1 engagement signals if referenced.)*

# Part 3 — Review Strategy

**Velocity rules:**
1. **25 reviews is the entry threshold.** *(Working model: Google appears to require ~25 GBP reviews before a profile is considered for the Map Pack for almost all keywords/niches.)* Getting a new client to 25 is the first review priority.
2. **Floor = the lowest-review GBP currently in the target Map Pack** (never below 25). Match it, then keep going — after the threshold, more is better.
3. **Cadence beats volume.** Reviews must drip steadily — a blast followed by a dry month is worse than fewer reviews arriving consistently. Target a faster steady cadence than the competitors', not a bigger burst.

**Review content (signal #6 — engineer it):** customers should be prompted to mention in their review:
- the **service** performed
- the **location/city**
- the **price** paid *(strong signal)*
- the **language spoken** during service *(strong signal)*

`[open: standard mechanism for the ask — owner sends? template/QR/review link? Define when settled.]`

**Third-party platforms:** no universal set beyond **Yext, Trustpilot, and the major aggregators for the client's industry** (e.g., ZocDoc medical, Avvo legal, TripAdvisor hospitality — per the Part 1 prominence list). Keep reviews *recent* on whichever apply.

**Responses:**
- Every review gets a response from the **owner or the owner's representative within 24 hours**.
- **Negative reviews:** acknowledge the reviewer's emotional state first, then attempt to fix the problem.

# Part 4 — Diagnostic Decision Tree

Input: geo-grid readout + GBP Insights. Identify the weak factor, act on it.

| Symptom (grid/insights) | Likely weak factor | Action |
|---|---|---|
| Ranks near office, dies past ~1.5–3 mi | Proximity-bound (normal) | Confirm competitors' radius on grid; if they carry further → Prominence gap, see below |
| Ranks for primary category queries, not a specific service | Relevance | Check: service in GBP services? On landing page + site? Reviews mention it? Fix in signal-strength order |
| Ranks in wrong city / not in target city | Geo-relevance | Landing-page geo optimization + citations. **Never touch the GBP address** — fix with geo signals only |
| Strong grid, weak conversions | Engagement | Photos, posts, review responses; CTR optimization (title/photos) |
| Stuck at grid spots 3–6, all above solved | Prominence | **Route to Link Building SOP §Link Building Targets for Maps** (RD first, then strength; anchors per that SOP) |
| Steady clicks stopped, rank sliding | CTR A/B re-rank (working model) | **CTR software (e.g., Agency Assassin)** to restore a steady click stream + increased short-form social activity (YouTube Shorts, IG Reels, FB video, TikTok) to drive real engagement |
| Entity signals thin (no KG panel, weak mreid graph) | Entity | **Run Part 5 — Entity/KG Building Procedure** (ring + vehicles route to the Link Building SOP from within it) |
| **GBP suspended** | — | **Escalation only: alert Senior SEO / Admin / Owner immediately. AI agents and Jr SEOs must not attempt reinstatement.** |
| **Duplicate GBP / merged listing** | — | **Escalation only: alert Senior SEO / Admin / Owner immediately. AI agents and Jr SEOs must not attempt to resolve.** |
| Broad soft decline in organic **and** maps; site carries heavy off-topic content | Entity-vector confusion | Off-vector content remediation: **delete** off-vector pages with no traffic to conversion pages and no conversions; **noindex + nofollow internal links** to off-vector pages that *do* have such traffic/conversions. If a whole service is too far off-vector, move it to a new site or a subdomain |

**Escalation:** one cycle (~6 weeks — the time links take to reach full effect, per the Link Building SOP) of correct-factor work with no grid movement → strategy review with Kyle/Ryan.

> **Agent halt rule:** the suspended-GBP and duplicate-listing rows are hard halt-and-ask triggers (per `_ORCHESTRATOR.md` §3) — an agent detecting either alerts and stops; it takes no GBP actions.

---

# Part 5 — Entity / Knowledge Graph Building Procedure

The actionable layer for Part 1's Entity factor. One standard process for every client (no tiers). Several steps are owned by other SOPs and are routed, not duplicated.

**Step 0 — Entity baseline audit.**
- Look up the GBP's **mreid** (`google.com/search?kgmid=/g/...`) and run a brand-name SERP: does a knowledge panel exist, and what does it contain?
- Check what Google associates with the brand (brand + service searches).
- **Site-level vector/intent audit:** flag too many unrelated services or blog posts (vector test, Part 1), and check whether the site targets **informational queries where it should target commercial queries** — a very common finding.

**Step 1 — Schema foundation** *(Architecture SOP owns templates)*: canonical Organization + Brand `@graph` site-wide; `sameAs` wired to every property from Step 2; consistent `@id`s. The `sameAs` array is the hub of the graph.

**Step 2 — Profile ring (standard set, every client):** Facebook, Instagram, YouTube, TikTok, Pinterest, LinkedIn, X, **Trustpilot, Google Site, and cloud pages** — identical NAP and brand language throughout → **branded IFTTT ring** (Link Building SOP owns the ring and links to it).

**Step 3 — Content build-out per the site plan:** location pages, service pages, the full service × city matrix, and on-vector blog posts (see *Content volume & the entity vector*, Part 1). The site plan comes from the Architecture SOP; content production is the pipeline's job. **Blog topics must stay tight to the main entity — off-vector posts are a ranking risk, not a win.**

**Step 4 — Citations as entity anchors** — industry + geo directories (Citation Audit tool owns consistency); Yext per Part 3.

**Step 5 — RDF-triple placement.** Standard set per client:
- One per service: **"[Brand] provides [service]"**
- One per city: **"[Brand] is a [category] in [city]"**
Placed via citations, PRs, guest posts, G stacks *(Link Building SOP owns the vehicles; this SOP owns the sentence patterns)*.

**Step 6 — Owner/key-person entities (standard for everyone):** bio page (Architecture SOP) + owner social profiles. Podcast booking / owner PR is **aspirational, not standard** — pursue opportunistically, don't plan around it.

**Step 7 — Content signals, optimal cadences:**
- **YouTube:** 1× 10+ minute video **+ 5 Shorts per week**
- **Instagram:** cross-post the YouTube Shorts
- **TikTok:** 3× per week
- **Reddit:** claimed brand account + brand subreddit + **daily posting**
- **GBP:** posts 5×/week, photos 2×/week (Part 2)

**Step 8 — Re-verify quarterly:** re-check the mreid / knowledge panel each quarter; confirm new profiles and mentions are being connected to the entity.

---

# Part 6 — Site Theming

**The model:** a site is organized under **one main topic**. The **home page is the top of the silo**, targeting **brand + main service** (e.g., title: "XYZ Plumber | Top Plumbing Services"). Below it, silos break down into **services and sub-services**, and **locations**. Theming is the site-level expression of the entity vector (Part 1): the structure itself demonstrates what the entity is.

**Rules:**
1. **Home page = brand + main service.** The top of the silo carries both the brand and the primary theme.
2. **The GBP and the website mirror each other.** Every GBP category (primary and secondary) should have a corresponding silo on the site — and the site's silo structure should be reflected in the GBP's categories and services.
3. **Structural prominence follows the theme hierarchy:** the primary theme gets the home page and the top silos; secondary services get **less structural prominence** (deeper placement, fewer high-value internal links, less nav real estate).
4. Theme membership is judged by the **vector test** (Part 1): if category-peer GBPs rank for it, it's on-theme.

**Theming audit (run at onboarding and when diagnosing vector confusion):**
- [ ] Home page title/H1 = brand + main service?
- [ ] Every GBP category (primary + secondary) has a matching silo on the site?
- [ ] Every site silo is reflected in GBP categories/services? *(mirror runs both ways)*
- [ ] Primary theme holds the home page + top silos; secondary services structurally subordinate?
- [ ] Silos clean — services/sub-services and locations broken down per the Architecture SOP, no orphaned or cross-bred silos?
- [ ] Off-theme content: run the vector test; remediate per Part 4's vector-confusion row (delete / noindex+nofollow / move to new site or subdomain).

**Fixes route to:** silo/structure changes → Architecture SOP (site plan + internal linking); GBP category changes → Part 2; content remediation → Part 4 vector-confusion row.

---

# Part 7 — Standard Maps Tactics Stack

The proactive, maps-side stack per client (distinct from Part 4's diagnostics, which react to symptoms). Tool specs also live in the Link Building SOP master table.

| Tactic | Who gets it | Cadence / trigger | Cost |
|---|---|---|---|
| **Agency Assassin (CTR)** | Every client with a retainer **≥ $1,200/mo** | Ongoing; configuration per the Agency Assassin SOP *(pending)* | $85/client/mo |
| **GBP Blast** (SEO NEO) | Every **physical or hybrid** GBP — **never SABs** (no visible address = no destination for directions) | **1×/week, rotating keywords** | $5/mo *(baseline-funded — Recipe Engine §2)* |
| **Hyper Local GBP Blast** (SEO NEO) | Diagnostic-triggered: weak grid areas/neighborhoods (Part 4) | Run **until the weak grid nodes improve** | priced monthly |
| **GBP Sniper** (SEO NEO) | Every client | **Once per target keyword at campaign start**, and again **on a ranking drop** | $10/run *(Link Building master table / Recipe Engine)* |
| **Maps Embeds** | Every client | **Once a month** | $5/run *(baseline-funded — Recipe Engine §2)* |

**Mechanics & rationale:**
- **GBP Blast** — creates driving-direction requests from randomized lat/longs within a **2-mile radius** of the GBP, to the GBP. *(Rationale: driving directions are a Popularity signal — Part 1. The 2-mile radius stays inside the proximity bands where the requests are plausible.)*
- **Hyper Local GBP Blast** — same mechanic, but the lat/longs are **hand-picked at the weak areas/neighborhoods** instead of randomized, concentrating the signal exactly where the grid is weak.
- **GBP Sniper** — **high power, low RD, low contextual relevance** links pointed directly at the GBP — the maps equivalent of a power blast at a site's homepage.
- **Maps Embeds** — **low power, high contextual relevance, high RD** links to the GBP: pages carrying an embed of the GBP's map. The complement of Sniper — Sniper solves juice, Embeds solve RD + relevance.
