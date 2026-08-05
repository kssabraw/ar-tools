<!--
Vendored 2026-08-03 from the owner's Google Doc:
"AR Content Platform — Page Type Reference & Site Planning Document v3" (v3.4)
https://docs.google.com/document/d/1K6H0RQ90JS4h-1JnmOcUi7R9Bhbn02N6kq6AtVYMV2c/

WHY IT IS HERE. The Website Builder PRD (docs/modules/website-builder-prd-v1_0.md)
binds its entire page inventory to this document as the authority for which page
types exist, their planner triggers, URL patterns, page structure, shared
components, and content specs. Without it in the repo, roughly a third of that
PRD is unbuildable and untestable.

AUTHORITY. This reference is subordinate to the AR *Site Architecture, URL
Structure, and Internal Linking SOP* (see its §1.1). Note its own scope caveat:
the §1.2 conventions are ratified into this reference and the tools that read it,
NOT into the SOP body text — that remains an outstanding action.

SYNC. The Google Doc is the source of truth. This is a captured copy; if the doc
revises past v3.4, re-vendor it rather than editing here.
-->

# AR Content Platform — Page Type Reference & Site Planning Document v3

**Version:** 3.4 **Changed in 3.4:** Ratified the URL/namespace worklist into a new **§1.2 URL & Namespace Conventions** — reserved root slugs + precedence, shared-namespace rule (page type is declared by the planner, never inferred from the URL), breadcrumb-follows-path rule, single-city no-matrix rule, the eight extension URL patterns (ratifying a URL is NOT a commitment to build), the bio canonical path, and mechanical conventions (trailing slash, pagination, slug immutability/redirects). Fixed two namespace bugs: local Comparison → /compare/… (was root-level), bio → /bio/{person-slug}/ (variant retired). The 40-link threshold in planner rule 7 is now labeled UNRATIFIED pending a Kyle/Ryan decision. Reference doc only — the Site Architecture SOP itself is unchanged (see close of §1.2). **Changed in 3.3:** Blog posts expanded from a single entry into a five-format sub-family in §5.3 (Informational Cluster, Listicle/Roundup, Comparison/Vs, Local Geo, News/Commentary), each with its own content spec and structure. Added §5.1/§5.2 pointers so blog formats are discoverable from every family. Problem/symptom posts remain their own §5.1 entry (writer \#8), not duplicated here. **Changed in 3.2:** Every catalog entry now includes a **Content spec** field — the editorial angle, voice, must-cover topics, and target depth for the page's copy. Planning apps use it to brief writers; design apps use the depth targets to size content areas; writer systems treat it as the editorial brief baseline (angle-level guidance, not scripts — client brand guides still govern final voice). **Changed in 3.1:** Local Service family reconciled with the AR Site Architecture, URL Structure, and Internal Linking SOP (12 May 2026) — see §1.1. URL patterns corrected, SOP terminology adopted, missing SOP page types added, new page types flagged as SOP extensions pending ratification. **Purpose:** Machine-consumable reference covering every page type in the AR system. This document is designed to be uploaded to downstream apps:

  

  - **A site-planning app** uses §2 + §3 + the "Planner triggers" field in each catalog entry to decide which page types a given site needs.
  - **A design app (e.g., Claude Design)** uses the "Page structure" and "UI components" fields in each catalog entry, plus the Shared Component Library (§4), to produce a design for every page type a site will use.
  - **Writer/build systems** use the "Writer archetype," "Required inputs," and "Schema" fields.

  

Each catalog entry is self-contained and follows an identical field template so it can be parsed programmatically.

  

## 1\. Document Conventions

  - **Funnel:** Top (research/problem-aware) · Mid (evaluating options) · Bottom (ready to act).
  - **AIO:** likelihood the page earns AI Overview / LLM citations when well-executed (Low / Med / High).
  - **Writer \#:** maps to the Writer Archetype Map (§6).
  - **URL patterns** use {placeholders}. All URLs lowercase, hyphenated, no trailing parameters.
  - **Page structure** lists sections in top-to-bottom order — this is the wireframe spec for design apps.
  - **Content spec** defines the copy itself: *Angle* (the editorial stance/POV that makes the page work), *Voice* (register), *Must cover* (non-negotiable topics), *Depth* (word-count target). Angle-level guidance by design — writers adapt to client brand guides; they do not script from it verbatim.
  - **UI components** reference the Shared Component Library (§4) by name where possible so designs stay consistent across page types.

## 1.1 SOP Reconciliation Notes (v3.1)

This document is subordinate to the AR *Site Architecture, URL Structure, and Internal Linking SOP* for the Local Service family. Changes made to comply:

  

  - **R1 — URL order corrected.** Local landing pages are /{city-slug}/{service-slug}/ — **location first** — per SOP. v3.0 had the order reversed. All local top-level pages (services, locations) sit at root level, not under /services/ or /locations/ prefixes.
  - **R2 — Terminology collisions fixed.** "Local Landing Page" now means what the SOP means: the service × city page. The former campaign page is renamed **Campaign / Paid Landing Page**. "Location Hub" is renamed **Areas We Serve** per SOP.
  - **R3 — Missing SOP page types added.** Homepage, About Us, Bio, Contact Us, Privacy Policy, Services index (conditional), Sub-Service, Neighborhood (with the SOP's Google Maps entity test), POI, Hyper-Specific Local Landing (third level, escalation-only), and Blog Archive now have full catalog entries. The v3.0 "Service-Area Overview" entry was removed as redundant with Areas We Serve + per-city location pages under the SOP hierarchy.
  - **R4 — SOP extensions: URL patterns RATIFIED (v3.4).** The eight extension page types (cost, problem/symptom, brand × service, standalone FAQ, projects, comparison, offers, warranty) now have ratified URL patterns in §1.2. Ratifying a URL reserves the path; it is **not** a commitment to build the page type. The bio canonical-path ambiguity is resolved (/bio/{person-slug}/). Two items remain open and are NOT resolved by this document: (a) the actual **type definitions still need to be written into the SOP body text** — this reference doc reserving a path is not the same as the SOP defining the page type; (b) the link-equity threshold decision (§1.2, planner rule 7).
  - **R5 — SOP content rules imported and binding:** homepage optimized for brand, not the money keyword; top-level service pages never geo-targeted (single-city businesses excepted); location pages geo-only with major services as H2s; informational content never geo-targeted; local landing pages need only be geographically relevant, not otherwise unique (this supersedes v3.0's stricter uniqueness language for this page type); exact-match anchors for SOP-specified body links; the SOP global nav/footer set appears on every page; schema authority is the AR Single Schema Creator doc.

## 1.2 URL & Namespace Conventions (ratified v3.4)

Ratified from the SOP-change worklist. **Ratifying a URL pattern is not a commitment to build the page type** — it reserves the path so live sites stay consistent if the type is ever built. Cheap to ratify, expensive to change once sites exist.

  

**Reserved root slugs.** Fixed paths the system claims. A service, city, or pillar slug colliding with one of these is a **planning error to surface, never to silently resolve**: about-us, services, areas-we-serve, blog, contact-us, privacy-policy, faq, specials, warranty, projects, glossary, bio, compare, lp, reviews. cost is reserved at the **second level** under a service (/{service}/cost/), not at root.

  

**Root precedence** when slugs collide: **utilities \> services \> cities \> pillars.**

  

**Shared namespaces — page type is declared by the planner, never inferred from the URL.** Several page types occupy one URL slot; shape alone cannot disambiguate them, so the planner must declare which type owns a given path. **Two entries claiming one path is a planning error.**

  

  - Second level: /{city}/{service}/ (local landing), /{city}/{neighborhood}/, and /{city}/{poi}/ share one slot; /{service}/{subservice}/ and /{service}/{brand}/ share another.
  - Third level: /{city}/{service}/{subservice}/ and /{city}/{neighborhood}/{subservice}/ are indistinguishable by shape.

  

**Breadcrumbs follow the URL path, not the link hierarchy** — so BreadcrumbList and canonical never disagree. Consequences: the Services index links to /{service}/ but is **not** its path ancestor (no breadcrumb link); a local landing page has two parents, and the **city page (by path) is the breadcrumb parent** while the service page (by body link) is not.

  

**Single-city businesses — no local-landing matrix.** Top-level service pages geo-target the single city; /{city}/{service}/ pages are not built. The matrix is CORE **only** for multi-city businesses; this is the explicit exception.

  

**Bio canonical path:** /bio/{person-slug}/. The /about-us/bio/ variant is retired.

  

**Ratified extension URL patterns** (path reserved; building the page type is a separate decision):

  

|  |  |
| :-: | :-: |
| \*\*Page type\*\* | \*\*URL\*\* |
| Cost / pricing | /{service-slug}/cost/ |
| Problem / symptom | /blog/{symptom-slug}/ (informational — never geo-targeted) |
| Brand × service | /{service-slug}/{brand-slug}/ (shares the sub-service namespace) |
| Standalone FAQ | /faq/ |
| Projects / case studies | /projects/ + /projects/{project-slug}/ |
| Comparison (commercial) | /compare/{option-a}-vs-{option-b}/ (informational comparisons use the Comparison/Vs blog post, §5.3) |
| Offers / specials | /specials/ |
| Warranty / guarantee | /warranty/ |

  

**Link-equity threshold — UNRATIFIED.** The "\> 40 outbound body links per index page" figure in planner rule 7 is a Page Type Reference heuristic, **not** an SOP-backed number. It needs either a real figure ratified into the SOP's PageRank/link-equity section, or an explicit statement that no numeric threshold exists. Downstream tools should treat rule 7 as **advisory** until this is decided. **\[Decision needed — Kyle/Ryan.\]**

  

**Mechanical conventions:**

  

  - **Trailing slash** on every URL (matches all SOP examples).
  - **Archive pagination:** /{archive}/page/{n}/ for blog, projects, and glossary indexes.
  - **Slug immutability & redirects:** published slugs are immutable. When a service is renamed or a city dropped, keep the old slug as a **301** to its replacement (or to the nearest parent if there is none). Never silently change a live slug.

  

**Scope note:** the above is ratified into *this reference document* and its downstream planner/design/writer tools. It has **not** been written into the Site Architecture SOP Google Doc itself — that requires checking each item against the live SOP text and proposing changes for approval, which is a separate action.

## 2\. Instructions for Planning Apps

Given a site (its vertical, business model, competitors, service/product catalog, and locations), select page types as follows:

  

1.  Identify the site's **family**: Local Service, Ecommerce, Informational/Authority, B2B Service, or SaaS. Hybrid sites (e.g., local business with ecommerce) inherit from multiple families.
2.  Include that family's **core set** (marked CORE in catalog entries) unconditionally.
3.  Evaluate each remaining entry's **Planner triggers** field against the site's facts. Include the page type only if a trigger matches. Never include a page type without a matched trigger.
4.  For **matrix page types** (marked MATRIX), compute expected page count from the site's data (services × locations, brands × services, integrations, etc.) and flag counts \> 200 for human review before planning.
5.  Output for each selected page type: the page type name, the specific page instances (e.g., which services, which locations, which competitors), estimated page count, and priority tier using §7.
6.  Respect the **swap test** rule: segmentation and vertical pages (writer \#10) may only be planned if vertical-specific research inputs will be available; otherwise defer them.
7.  **Budget link equity when sizing matrices.** Per the Site Architecture SOP's PageRank model: every page added under an index/category page divides that page's passable equity across more links, reducing the equity every sibling receives. When planning matrix page types, report the resulting links-per-index count and flag silos where an index page would carry \> 40 outbound body links — those need restructuring (sub-silos, additional hub layers) or additional inbound equity before the pages are worth building. **The 40-link figure is an UNRATIFIED reference-doc heuristic, not an SOP number (see §1.2) — treat as advisory pending a Kyle/Ryan decision.**

## 3\. Instructions for Design Apps

1.  Design **one template per page type** the site will use — not per page instance. A site using 12 page types needs 12 templates.
2.  Follow each entry's **Page structure** as the section order. Sections are top-to-bottom; do not reorder or omit MUST sections.
3.  Build the **Shared Component Library (§4) first**, then compose page templates from it. Components must be visually consistent everywhere they appear.
4.  Every template MUST include: the site's global header/nav, breadcrumb bar, footer, and at least one CTA placement per the entry. For the Local Service family, the header/footer MUST carry the SOP global link set (Home, About Us, Contact Us, Privacy Policy, top-level service pages or Services index, Areas We Serve where applicable, Blog Archive); Campaign / Paid Landing Pages are the only exemption.
5.  Design mobile-first; every table component needs a defined mobile behavior (stack, scroll, or collapse — specified per component in §4).
6.  Use placeholder content that matches the entry's content shape (e.g., a real-looking price range table on cost pages), never lorem ipsum for structural elements like table headers, FAQ questions, or button labels.

  

## 4\. Shared Component Library (design once, reuse everywhere)

|  |  |  |
| :-: | :-: | :-: |
| \*\*Component\*\* | \*\*Description\*\* | \*\*Mobile behavior\*\* |
| HeroStandard | H1 + subhead + primary CTA + supporting visual | Stack, visual below text |
| HeroAnswer | H1 + 2-sentence plain-language answer paragraph (AIO extraction target) + CTA | Stack |
| CTABand | Full-width call-to-action strip: headline + button (+ optional phone number for local) | Stack |
| FAQAccordion | Expandable Q\\\&A list, FAQPage schema bound | Native accordion |
| ComparisonTable | 2+ columns of entities vs. criteria rows; supports checkmarks, text, ratings; sticky header row | Horizontal scroll with sticky first column |
| PriceRangeTable | Item/tier vs. low–high price + factors column | Stack to cards |
| PricingTierCards | 2–4 plan cards: name, price, feature list, CTA | Carousel or stack |
| StatCallout | Large number + label + source line; used singly or in rows of 3 | Stack |
| StepList | Numbered steps with optional images (how-to, process) | Stack |
| ProsConsPair | Side-by-side pros/cons lists | Stack |
| ProofBlock | Metric headline + client name/logo + 1-paragraph summary + link | Stack |
| TestimonialCard | Quote + attribution (real persons only; no stock photos ever) | Carousel |
| LogoRow | Client/brand/integration logo strip | Wrap to 2 rows |
| ServiceCardGrid | Card grid: icon/image + title + blurb + link | 1-column stack |
| LocationCardGrid | Card grid of locations: name + address/area + link | 1-column stack |
| MapEmbed | Service-area or location map | Full-width |
| TrustBadgeRow | Licenses, certifications, associations, review scores | Wrap |
| TOCSidebar | Sticky in-page table of contents for long pages | Collapse to top dropdown |
| AuthorByline | Author name, credential, photo, reviewed-by line, dates | Inline |
| GalleryBeforeAfter | Paired or slider before/after images | Slider |
| SpecTable | Attribute/value rows (products, sizes, integrations) | Stack to definition list |
| CalculatorShell | Input panel + live results panel + gated detail CTA | Stack, results below inputs |
| LeadForm | Short form (name, contact, message/service) + submit | Full-width |
| RelatedPagesBlock | 3–6 contextual internal links as cards or list | Stack |
| BreadcrumbBar | Breadcrumb trail, BreadcrumbList schema bound | Truncate middle |
| AlertNote | Callout box: compliance notes, disclaimers, freshness dates | Full-width |
| DefinitionBox | Term + concise definition, visually distinct (glossary/AIO extract) | Full-width |

  

## 5\. Page Type Catalog

Every entry uses this template: **Family · Funnel · AIO · Writer \# · Flags** (CORE = always included for its family; MATRIX = programmatic, count computed from data) **What it is** · **Planner triggers** (include only if one matches) · **Query patterns** · **URL pattern** · **Page structure** (design wireframe, top to bottom) · **UI components** (§4 names) · **Schema** · **Internal links** · **Required inputs** · **Pitfalls**

  

### 5.1 Local Service Family

*Blog posts for local sites — including the SOP-sanctioned geo-targeted* ***Local Geo Post*** *— live in the* ***Blog Post sub-family in §5.3****. The Blog Archive page is in this family below.*

  

**SOP alignment note (governs this whole family):** URL patterns, page hierarchy, and internal linking below follow the AR *Site Architecture, URL Structure, and Internal Linking SOP* (12 May 2026). Where this document previously conflicted, the SOP wins. Key rules inherited from the SOP:

  

  - **Global nav/footer set (every page, all levels):** Home, About Us, Contact Us, Privacy Policy, Top-Level Service Pages (dropdown case-by-case; use Services index page if too many), Areas We Serve (if applicable; locations dropdown case-by-case), Blog Archive. Entry "Internal links" fields below list **body-content links only** — the global set is assumed on every template.
  - **Geo-targeting rules:** top-level service pages are NEVER geo-targeted (exception: single-city businesses target that city). Location pages target the geo keyword only, with all major services as H2s. The homepage is optimized for the **brand**, not the main keyword. Informational blog posts are never geo-targeted (except posts about a city/POI, which are naturally geo-targeted).
  - **Exact-match anchors** are used for the body-content links the SOP specifies (marked "EM" below).
  - **Link equity:** every page added to a category dilutes PageRank to its siblings through the shared index page — see §2 rule 7.
  - **Schema:** the authoritative source for all schema in this family is the AR Single Schema Creator doc referenced by the SOP; schema types listed here are summaries, not the spec.

#### Homepage — CORE

  - **Local Service · Bottom · AIO: Low · Writer: live**
  - **What it is:** Brand-optimized front door. Per SOP: optimized for the brand, NOT the main service keyword.
  - **Content spec:** *Angle:* the brand's front door — who we are, what we do, where we do it, why trust us; conversion-warm but not keyword-chasing (SOP: brand, not money keyword). *Voice:* confident, welcoming, first-person plural. *Must cover:* brand promise, service breadth, geographic footprint, top 2–3 differentiators, real trust signals. *Depth:* 500–800 words.
  - **Planner triggers:** Always.
  - **URL pattern:** /
  - **Page structure:** 1. HeroStandard (brand promise + CTA/phone) → 2. Services overview (ServiceCardGrid, links to each service page) → 3. Why-us + TrustBadgeRow → 4. Locations overview (links to each location page where feasible) → 5. ProofBlock/TestimonialCard row → 6. FAQAccordion (brand-level) → 7. CTABand + LeadForm
  - **UI components:** HeroStandard, ServiceCardGrid, TrustBadgeRow, ProofBlock, TestimonialCard, FAQAccordion, LeadForm
  - **Schema:** per Schema Creator (Organization/LocalBusiness home schema)
  - **Internal links (body):** each individual service page, each individual location page (if count permits), Contact Us
  - **Required inputs:** brand positioning, service + location lists, proof
  - **Pitfalls:** Optimizing the H1 for the money keyword instead of the brand (explicit SOP violation).

#### About Us Page — CORE

  - **Local Service · Bottom · AIO: Low · Writer: \#12**
  - **What it is:** The company itself — history, mission, USP, leadership overview. Not about the services.
  - **Content spec:** *Angle:* the founding-story arc — why the company exists, told with specifics (dates, names, turning points) that generic competitors can't copy. *Voice:* human, first-person, warm. *Must cover:* history, mission, USP, leadership intro, values in action (not listed platitudes). *Avoid:* service-selling copy. *Depth:* 400–800 words.
  - **Planner triggers:** Always (SOP required page).
  - **URL pattern:** /about-us/
  - **Page structure:** 1. HeroStandard (founding story hook) → 2. Company history + mission + USP → 3. Leadership overview (real photos, links to bio pages) → 4. TrustBadgeRow (licenses, insurance, associations) → 5. Community involvement → 6. CTABand
  - **UI components:** HeroStandard, TrustBadgeRow, CTABand
  - **Schema:** per Schema Creator (AboutPage/Organization)
  - **Internal links (body):** Bio pages, Areas We Serve, a top-level service page
  - **Required inputs:** real history, mission, leadership info
  - **Pitfalls:** Stock photos of fake team members; drifting into service-page content.

#### Bio Page

  - **Local Service · Bottom · AIO: Low · Writer: \#12**
  - **What it is:** Per-person authority page for owners/leadership: accreditations, work history, education, professional socials, organizations. E-E-A-T builder.
  - **Content spec:** *Angle:* third-person credential narrative establishing this person as a verifiable expert entity. *Voice:* professional profile, factual. *Must cover:* accreditations with issuing bodies, work history, education, professional organizations, professional social links — every claim verifiable. *Depth:* 300–600 words.
  - **Planner triggers:** Leadership/owner with meaningful credentials; YMYL-adjacent categories especially.
  - **URL pattern:** /bio/{person-slug}/ (canonical; /about-us/bio/ variant retired — see §1.2)
  - **Page structure:** 1. HeroStandard (name, title, photo) → 2. Professional background narrative → 3. Credentials list (accreditations, education, organizations — TrustBadgeRow/SpecTable) → 4. Professional social links → 5. CTABand
  - **UI components:** HeroStandard, TrustBadgeRow, SpecTable, CTABand
  - **Schema:** per Schema Creator (Person)
  - **Internal links (body):** About Us parent
  - **Required inputs:** real credentials, verified
  - **Pitfalls:** Inflated or unverifiable credentials.

#### Contact Us Page — CORE

  - **Local Service · Bottom · AIO: Low · Writer: \#12 (thin)**
  - **What it is:** Per SOP: short page — NAP, GBP embed, form, click-to-call, social links. No long copy.
  - **Content spec:** *Angle:* pure function — get in touch in the fewest possible steps. *Must cover:* NAP, hours, GBP embed, form, click-to-call, socials. *Depth:* under 150 words of copy; the SOP explicitly forbids padding.
  - **Planner triggers:** Always (SOP required page).
  - **URL pattern:** /contact-us/
  - **Page structure:** 1. Compact hero (H1 + phone CTA) → 2. NAP block + GBP MapEmbed → 3. LeadForm → 4. Click-to-call + hours → 5. Social links row
  - **UI components:** MapEmbed, LeadForm, CTABand
  - **Schema:** per Schema Creator (ContactPage/LocalBusiness)
  - **Internal links (body):** minimal by design
  - **Required inputs:** NAP, GBP embed, form destination, socials
  - **Pitfalls:** Padding with hundreds of words — SOP explicitly says keep it short.

#### Privacy Policy Page — CORE

  - **Local Service · n/a · AIO: n/a · Writer: template**
  - **What it is:** Required legal page; carries global nav for link-structure completeness.
  - **Content spec:** *Angle:* legal text, plain-language where possible. *Depth:* as legal requires; no marketing content.
  - **Planner triggers:** Always (SOP required page).
  - **URL pattern:** /privacy-policy/
  - **Page structure:** 1. H1 + effective date → 2. Policy body (TOCSidebar if long)
  - **UI components:** TOCSidebar
  - **Schema:** WebPage
  - **Required inputs:** legal-reviewed policy text
  - **Pitfalls:** Missing from footer (breaks the SOP global link set).

#### Services Index Page (conditional)

  - **Local Service · Mid · AIO: Low · Writer: \#6**
  - **What it is:** Per SOP: only exists when there are too many services to list in the nav/dropdown. Optimized for the service keywords collectively, never geo-targeted. Lists and links every service.
  - **Content spec:** *Angle:* the capability overview — breadth and mastery, framed as "everything we do and why we're good at it." *Voice:* authoritative. *Must cover:* every service with a 1–2 sentence expertise-signaling summary and EM link, plus a company-level authority section. *Depth:* 400–700 words plus the list.
  - **Planner triggers:** Service count exceeds nav capacity (typically \> \~8).
  - **URL pattern:** /services/
  - **Page structure:** 1. HeroAnswer (what the company does, expertise/authority framing) → 2. ServiceCardGrid (every service, EM-anchored links) → 3. Benefits/authority section → 4. CTABand + LeadForm
  - **UI components:** HeroAnswer, ServiceCardGrid, LeadForm, CTABand
  - **Schema:** per Schema Creator (Services page schema)
  - **Internal links (body, EM):** each individual service page; Contact Us
  - **Required inputs:** service list with descriptions
  - **Pitfalls:** Building it when the nav can hold the services (unnecessary hierarchy layer).

#### Top-Level Service Page — CORE

  - **Local Service · Bottom · AIO: Med · Writer: live**
  - **What it is:** One page per service, optimized ONLY for the service keyword. Per SOP: never geo-targeted unless the business targets a single city (then target that city). Copy demonstrates expertise, authority, and service benefits.
  - **Content spec:** *Angle:* the expert explaining the work — demonstrate process fluency (methods, materials, standards, code compliance) that proves the company has done this a thousand times. Geo-free by SOP rule. *Voice:* knowledgeable tradesperson, plain-spoken, benefit-anchored. *Must cover:* what the service is and who needs it, how the work is done, what affects outcomes, why this company, what happens if you hire cheap or DIY (honest, not fear-mongering). *Depth:* 800–1,500 words.
  - **Planner triggers:** Always (CORE) — one per distinct billable service.
  - **Query patterns:** "\[service\]," "\[service\] company" (no geo)
  - **URL pattern:** /{service-slug}/ (root level per SOP)
  - **Page structure:** 1. HeroStandard (service H1, no geo + CTA/phone) → 2. Answer paragraph (what the service is, who it's for) → 3. Expertise/authority section → 4. Process/what's-included (StepList) → 5. Benefits + TrustBadgeRow → 6. Cost factors teaser → link to cost page → 7. FAQAccordion (service-specific) → 8. ProofBlock or GalleryBeforeAfter → 9. CTABand + LeadForm
  - **UI components:** HeroStandard, StepList, TrustBadgeRow, FAQAccordion, ProofBlock, LeadForm
  - **Schema:** per Schema Creator (Service page schema); FAQPage
  - **Internal links (body, EM):** subservice pages, Contact Us, Services index (if applicable), related local landing pages
  - **Required inputs:** service description, process, differentiators, FAQs, proof
  - **Pitfalls:** Geo-targeting the page (SOP violation — geo relevance belongs to local landing pages); brochure copy with no expertise signal.

#### Sub-Service Page

  - **Local Service · Bottom · AIO: Med · Writer: live (service-page variant)**
  - **What it is:** Per SOP: a more specific service on a different keyword vector than its parent (e.g., "24 hour plumber" vs "plumber") needing distinct messaging for a distinct need.
  - **Content spec:** *Angle:* meet the specific need-state the modifier implies — urgency copy for emergency/24-hour (response time, availability, what to do right now), precision copy for technical variants (specs, standards, edge cases). The messaging must be genuinely different from the parent, or the page shouldn't exist. *Depth:* 600–1,200 words.
  - **Planner triggers:** A service modifier with its own search vector and intent (emergency/24-hour, commercial vs residential, installation vs repair).
  - **URL pattern:** /{service-slug}/{subservice-slug}/
  - **Page structure:** As Top-Level Service Page with need-specific messaging (urgency framing for emergency services, spec depth for technical variants); section 6 links to parent's cost page.
  - **UI components:** As Top-Level Service Page
  - **Schema:** per Schema Creator (service schema); FAQPage
  - **Internal links (body, EM):** parent service page, Contact Us, Services index (if applicable), related hyper-specific local landing pages
  - **Required inputs:** modifier-specific messaging, parent mapping
  - **Pitfalls:** Creating subservices for modifiers that are the same vector as the parent (cannibalization).

#### Top-Level Location Page — CORE

  - **Local Service · Bottom · AIO: Med · Writer: live**
  - **What it is:** One page per targeted city, optimized ONLY for the geo keyword, with all major services as H2s. Per SOP: not needed for single-city businesses.
  - **Content spec:** *Angle:* proof of genuine local presence — years serving the city, named neighborhoods and landmarks, local jobs completed, local review quotes; the copy a competitor from out of town couldn't write. *Must cover:* geo-focused intro, every major service as an H2 with a 2–3 sentence summary + EM link to its local landing page, coverage specifics. *Avoid:* service+geo keyword targeting (belongs to local landing pages). *Depth:* 600–1,200 words.
  - **Planner triggers:** Business targets ≥ 2 cities; one page per city.
  - **Query patterns:** "\[brand\] \[city\]," "\[category\] \[city\]" (assist)
  - **URL pattern:** /{city-slug}/ (root level per SOP)
  - **Page structure:** 1. HeroStandard (city-focused H1 + CTA) → 2. Local intro (expertise/authority + genuine local presence) → 3. Major services as H2 sections (each: summary + EM link to the local landing page for that service × this city) → 4. NAP/coverage + MapEmbed → 5. Local proof (TestimonialCard, jobs) → 6. Neighborhood links (where neighborhood pages exist) → 7. FAQAccordion (location-specific) → 8. CTABand + LeadForm
  - **UI components:** HeroStandard, MapEmbed, TestimonialCard, FAQAccordion, LeadForm
  - **Schema:** per Schema Creator (location page schema)
  - **Internal links (body, EM):** neighborhood pages, POI pages, related local landing pages, Contact Us, Areas We Serve (if applicable)
  - **Required inputs:** city list, per-city local facts, service list
  - **Pitfalls:** Optimizing for service+geo here (that's the local landing page's job); city-swapped identical copy.

#### Areas We Serve Page (Location Hub)

  - **Local Service · Mid · AIO: Low · Writer: \#6**
  - **What it is:** Per SOP: repository/archive page for top-level location pages — analogous to the blog archive. Optimized only for "(brand) areas."
  - **Content spec:** *Angle:* brand coverage narrative — "where you'll find us and how far we'll come." *Must cover:* full location list with EM links, travel/coverage rules. *Depth:* 300–600 words; archive page, not a ranking play.
  - **Planner triggers:** Location page count exceeds nav capacity (SOP: optional, case-by-case).
  - **URL pattern:** /areas-we-serve/
  - **Page structure:** 1. HeroAnswer (coverage statement, brand-framed) → 2. MapEmbed (all locations) → 3. LocationCardGrid grouped by region (EM-anchored links) → 4. Coverage notes → 5. CTABand
  - **UI components:** HeroAnswer, MapEmbed, LocationCardGrid, CTABand
  - **Schema:** per Schema Creator (Areas We Serve schema)
  - **Internal links (body, EM):** each individual location page
  - **Required inputs:** location list with regions
  - **Pitfalls:** Keyword-targeting it beyond "(brand) areas" (SOP: archive page, not a ranking page).

#### Local Landing Page (Service × Location) — CORE · MATRIX

  - **Local Service · Bottom · AIO: Med · Writer: live (matrix engine)**
  - **What it is:** SOP's term for the service × city page — the page optimized for "(service) in (city)" / "(service) near me," pushing the most geographic power (including to GBPs). Per SOP: these need only be geographically relevant, not otherwise unique from each other — template similarity across cells is acceptable by design.
  - **Content spec:** *Angle:* conversion page for "\[service\] in \[city\]" — the service pitch wrapped in genuine geographic relevance (city/neighborhood mentions, local conditions affecting the work, response times from real locations). Per SOP, body copy may be templated across cells; the geo-relevance blocks are what must be real per cell. *Voice:* direct, urgent-adjacent, phone-forward. *Depth:* 500–1,000 words.
  - **Planner triggers:** Multi-city service business. Count = services × cities; flag \> 200 for link-equity review (§2 rule 7).
  - **Query patterns:** "\[service\] in \[city\]," "\[service\] near me"
  - **URL pattern:** /{city-slug}/{service-slug}/ — **location first, then service, per SOP**
  - **Page structure:** 1. HeroStandard (service-in-city H1 + CTA/phone) → 2. Geo-relevant intro (city/neighborhood specifics) → 3. Service content (templated across cells, geo-localized) → 4. Local coverage detail + MapEmbed → 5. Local proof where available → 6. FAQAccordion (response time, permits, coverage) → 7. CTABand + LeadForm
  - **UI components:** HeroStandard, MapEmbed, FAQAccordion, LeadForm, CTABand
  - **Schema:** per Schema Creator (local landing page schema)
  - **Internal links (body, EM):** location page parent, relevant service page, relevant subservice page, Contact Us
  - **Required inputs:** service × city matrix, per-cell geo data
  - **Pitfalls:** Skipping the geo-relevant blocks (pure city-name swap); misordering the URL as service-first (SOP violation).

#### Hyper-Specific Local Landing Page — MATRIX (third level)

  - **Local Service · Bottom · AIO: Low · Writer: live (matrix variant)**
  - **What it is:** Per SOP: third-level page for the most granular keywords (subservice × city, or subservice × neighborhood). Only for highly competitive topics or stubborn non-ranking targets — generally not needed.
  - **Content spec:** *Angle:* as Local Landing Page, narrowed to the hyper-specific need (subservice × geo); messaging matches the exact search's urgency or specificity. *Depth:* 400–800 words.
  - **Planner triggers:** ONLY when a target is highly competitive or has resisted ranking despite other efforts. Planner must justify each instance; never bulk-generate.
  - **URL pattern:** /{city-slug}/{service-slug}/{subservice-slug}/ or /{city-slug}/{neighborhood-slug}/{subservice-slug}/
  - **Page structure:** As Local Landing Page, messaging matched to the hyper-specific need.
  - **Internal links (body):** location page parent, relevant service page, relevant subservice page, Contact Us
  - **Pitfalls:** Bulk-generating these by default — SOP reserves them as an escalation tool.

#### Neighborhood Page

  - **Local Service · Bottom · AIO: Low · Writer: live (location-page variant)**
  - **What it is:** Sub-area page within a larger city. Per SOP's entity test: only for neighborhoods Google Maps recognizes as entities (has a knowledge panel with description and associated entities).
  - **Content spec:** *Angle:* entity-rich local writing — the neighborhood's character, landmarks, housing stock or building types (which genuinely affect service work), tied naturally back to the services offered there. *Must cover:* recognized entities the Maps panel associates with the neighborhood. *Depth:* 500–900 words.
  - **Planner triggers:** Large city with Google-recognized neighborhoods AND competitive need at neighborhood granularity. Apply the Maps entity test per neighborhood.
  - **URL pattern:** /{city-slug}/{neighborhood-slug}/
  - **Page structure:** As Top-Level Location Page scoped to the neighborhood: neighborhood-specific intro, local entities/landmarks, services as H2s linking to relevant pages.
  - **Schema:** per Schema Creator (location schema)
  - **Internal links (body, EM):** location page parent, related neighborhoods, related POI pages, related service
  - **Required inputs:** verified neighborhood entity status, neighborhood facts
  - **Pitfalls:** Building pages for unrecognized neighborhoods that fail the Maps entity test.

#### POI Page

  - **Local Service · Top · AIO: Low · Writer: live (geo-content variant)**
  - **What it is:** Point-of-interest page (landmark, attraction, notable place) that builds geographic relevance for the location silo and pushes power to local landing pages.
  - **Content spec:** *Angle:* genuinely informative visitor-style content about the landmark (history, what it is, visiting basics) with an organic tie to the service area — geographic relevance building, not ad copy. *Depth:* 500–900 words.
  - **Planner triggers:** Location silo needs additional geo-relevance; POIs with genuine entity recognition near served areas.
  - **URL pattern:** /{city-slug}/{poi-slug}/ (within the location silo)
  - **Page structure:** 1. HeroStandard (POI name) → 2. POI content (what it is, history, visiting info) → 3. Proximity/context tie to service area → 4. RelatedPagesBlock
  - **UI components:** HeroStandard, MapEmbed, RelatedPagesBlock
  - **Schema:** per Schema Creator; Place where applicable
  - **Internal links (body, EM):** location page parent, related neighborhoods, each local landing page (per SOP)
  - **Required inputs:** POI facts, entity verification
  - **Pitfalls:** POI content with zero tie to the location silo's purpose.

#### Blog Archive Page — CORE

  - **Local Service · n/a · AIO: Low · Writer: \#6**
  - **What it is:** Per SOP: repository only — latest posts, optimized for nothing except "(brand) blog."
  - **Content spec:** *Angle:* none — repository per SOP; latest posts, brand-blog framing only.
  - **Planner triggers:** Always where a blog exists (SOP required page).
  - **URL pattern:** /blog/
  - **Page structure:** 1. Compact hero ("(Brand) Blog") → 2. Latest posts grid → 3. Category filter (silo-based) → 4. Pagination
  - **UI components:** ServiceCardGrid (as post cards)
  - **Schema:** per Schema Creator (Blog archive schema)
  - **Internal links (body):** latest blog posts
  - **Pitfalls:** Keyword-optimizing the archive (SOP: brand-blog only).

#### Cost / Pricing Page (Local) — ⭐ SOP extension

  - **Local Service · Bottom · AIO: High · Writer: \#7**
  - **What it is:** "How much does \[service\] cost" page with real ranges and cost factors. Highest-intent local type not yet in the SOP.
  - **Content spec:** *Angle:* the transparent contractor — "here's what this really costs and why," giving real numbers before asking for anything. Radical price honesty is the differentiator and the AIO hook. *Voice:* straight-shooting, educational. *Must cover:* typical range up front, per-job-type ranges, every major cost factor explained honestly (including when the cheap option is fine), what's in/out of scope, financing, how quotes work. *Depth:* 1,000–1,800 words.
  - **Planner triggers:** Service with cost search volume; client sign-off on publishing ranges.
  - **Query patterns:** "\[service\] cost," "how much to \[job\]" — geo-agnostic by default per SOP service-page logic; geo cost pages only as hyper-specific escalations
  - **URL pattern:** /{service-slug}/cost/ (ratified §1.2; cost reserved at the second level under a service).
  - **Page structure:** 1. HeroAnswer (typical range in first two sentences) → 2. PriceRangeTable (job types × low–avg–high) → 3. Cost factors explained → 4. What's included/excluded → 5. Financing options → 6. How to get an exact quote (StepList) → 7. FAQAccordion → 8. AlertNote (prices as of {date}) → 9. CTABand + LeadForm
  - **UI components:** HeroAnswer, PriceRangeTable, StepList, FAQAccordion, AlertNote, LeadForm
  - **Schema:** FAQPage + per Schema Creator once ratified
  - **Internal links (body, EM):** parent service page, Contact Us, offers/financing page
  - **Required inputs:** verified ranges, factors, freshness date
  - **Pitfalls:** Invented ranges; missing freshness date.

#### Problem / Symptom Page — ⭐ SOP extension

  - **Local Service · Top · AIO: High · Writer: \#8**
  - **What it is:** Symptom-in, diagnosis-out page ("AC blowing warm air"). Informational intent — per SOP blog rules, NEVER geo-targeted.
  - **Content spec:** *Angle:* calm diagnostic triage — a knowledgeable friend talking the reader down and walking through causes from most to least likely. *Voice:* reassuring, safety-first, honest about DIY vs. call-a-pro per cause. *Must cover:* likely causes ranked with severity, safety warnings where real, what a pro will actually do, cost expectations teaser, clear when-to-call-now criteria. *Avoid:* manufactured urgency. *Depth:* 800–1,500 words.
  - **Planner triggers:** Category with recognizable symptom queries (HVAC, plumbing, appliance, auto, IT).
  - **URL pattern:** /blog/{symptom-slug}/ (ratified §1.2 — blog silo, informational, never geo-targeted; the /problems/ alternative was rejected to keep the SOP's never-geo rule attached).
  - **Page structure:** 1. HeroAnswer (most likely cause in 2 sentences) → 2. Cause list ranked by likelihood (severity + DIY-vs-pro per cause) → 3. AlertNote (safety warnings) → 4. What a pro will do (StepList) → 5. Cost teaser → link to cost page → 6. When to call now vs. wait → 7. FAQAccordion → 8. CTABand + phone
  - **UI components:** HeroAnswer, AlertNote, StepList, FAQAccordion, CTABand
  - **Schema:** FAQPage; Article if blog-silo
  - **Internal links (body):** related service or subservice (per SOP blog rules), cost page, related posts in silo
  - **Required inputs:** SME-verified symptom/cause/severity data
  - **Pitfalls:** Geo-targeting informational content (SOP violation); overpromising DIY fixes.

#### Brand × Service Page — ⭐ SOP extension · MATRIX

  - **Local Service · Bottom · AIO: Med · Writer: \#5**
  - **What it is:** "\[Equipment brand\] \[service\]" pages (Carrier AC repair). A brand modifier is a distinct keyword vector with distinct messaging — exactly the SOP's subservice definition.
  - **Content spec:** *Angle:* brand fluency as proof of competence — model families serviced, known quirks and failure patterns of this brand, parts availability, warranty implications. The reader should think "they clearly work on my \[brand\] all the time." *Must cover:* brand-specific issues and models; "we service" framing, never implied authorization. *Depth:* 500–900 words per cell.
  - **Planner triggers:** Business services branded equipment. Count = brands × applicable services; flag \> 200 for link-equity review.
  - **URL pattern:** /{service-slug}/{brand-slug}/ (ratified §1.2 — **shares the sub-service namespace**, so the planner must declare this as a brand×service page, not infer it from the path). Hyper-specific geo variants follow /{city-slug}/{service-slug}/{brand-slug}/ only as escalations.
  - **Page structure:** 1. HeroStandard (brand + service H1; certification badge only if true) → 2. Brand-specific expertise (models, common brand issues) → 3. Common \[brand\] problems (links to problem pages) → 4. Parts/warranty notes (AlertNote) → 5. Process StepList → 6. FAQAccordion → 7. CTABand + LeadForm
  - **UI components:** HeroStandard, AlertNote, StepList, FAQAccordion, LeadForm
  - **Schema:** per subservice schema; FAQPage
  - **Internal links (body, EM):** parent service page, Contact Us, related problem pages
  - **Required inputs:** brand list, per-brand issues/models, certification facts
  - **Pitfalls:** "Authorized" claims that aren't true; thin cells with no brand-specific content.

#### FAQ Page (Standalone) — ⭐ SOP extension

  - **Cross-family · Top–Mid · AIO: High · Writer: \#4**
  - **What it is:** Schema-heavy standalone Q\&A; canonical source for FAQ blocks reused elsewhere.
  - **Content spec:** *Angle:* direct answers — every answer resolves the question in its first sentence, marketing (if any) only after. *Voice:* helpful desk expert. *Depth:* 40–80 words per answer, standalone-extractable.
  - **Planner triggers:** ≥ 10 substantive questions exist.
  - **URL pattern:** /faq/ (ratified §1.2 — reserved root slug).
  - **Page structure:** 1. HeroAnswer → 2. TOCSidebar (categories) → 3. FAQAccordion grouped by category → 4. CTABand + LeadForm
  - **UI components:** HeroAnswer, TOCSidebar, FAQAccordion, LeadForm
  - **Schema:** FAQPage (full)
  - **Internal links (body):** every page a question relates to
  - **Required inputs:** question inventory, 40–80 word standalone answers
  - **Pitfalls:** Duplicating full FAQ blocks across many pages instead of subsetting from the canonical page.

#### Case Study / Project Page — ⭐ SOP extension

  - **Local Service · Bottom · AIO: Low · Writer: \#9**
  - **What it is:** One completed job: situation → work → result, with photos.
  - **Content spec:** *Angle:* narrative storytelling with numbers — a real job told as situation → complication → work → result, letting photos and specifics carry the persuasion. *Must cover:* verifiable job facts, what made it hard, exactly what was done, measurable outcome. *Depth:* 400–800 words.
  - **Planner triggers:** Real job data + photos + permission; plan 3–10 initially.
  - **URL pattern:** /projects/ + /projects/{project-slug}/ (ratified §1.2 — reserved root slug; archive paginates /projects/page/{n}/).
  - **Page structure:** 1. HeroStandard (job headline + geo) → 2. StatCallout row (job facts) → 3. Challenge → 4. GalleryBeforeAfter → 5. Work performed (StepList) → 6. Outcome + TestimonialCard → 7. CTABand
  - **UI components:** HeroStandard, StatCallout, GalleryBeforeAfter, StepList, TestimonialCard, CTABand
  - **Schema:** Article
  - **Internal links (body):** matching service page, matching location/local landing page
  - **Required inputs:** real job data, photos, client permission
  - **Pitfalls:** Fabricated or unverifiable results.

#### Comparison Page (Local Service) — ⭐ SOP extension

  - **Local Service · Bottom · AIO: Med · Writer: \#1**
  - **What it is:** "X vs Y" at the service/category level ("tankless vs tank," "repair vs replace").
  - **Content spec:** *Angle:* the neutral advisor who's installed both — verdict up front, honest trade-offs, "choose A if / choose B if" mapped to reader situations. Trust is the ranking asset; steering kills it. *Must cover:* criteria table, real pros/cons each side, cost comparison, situational recommendation. *Depth:* 1,000–1,800 words.
  - **Planner triggers:** Category has a recognized either/or decision buyers research.
  - **URL pattern:** /compare/{option-a}-vs-{option-b}/ (ratified §1.2 — commercial comparison; **not** root-level, which would collide with services/cities/pillars). Informational comparisons use the Comparison/Vs blog post (§5.3) instead.
  - **Page structure:** 1. HeroAnswer (verdict in 2 sentences) → 2. ComparisonTable → 3. Per-option ProsConsPair → 4. "Choose A if / Choose B if" → 5. Cost comparison (PriceRangeTable) → 6. FAQAccordion → 7. CTABand
  - **UI components:** HeroAnswer, ComparisonTable, ProsConsPair, PriceRangeTable, FAQAccordion, CTABand
  - **Schema:** FAQPage; Article if blog-silo
  - **Internal links (body):** both option service pages, cost pages
  - **Required inputs:** honest criteria for both options
  - **Pitfalls:** Steering so hard toward the profitable option the page loses trust.

#### Offers / Specials Page — ⭐ SOP extension

  - **Local Service · Bottom · AIO: Low · Writer: \#12 (thin)**
  - **What it is:** Current coupons, seasonal promos, financing.
  - **Content spec:** *Angle:* clarity over hype — the offer, its real value, its terms and expiry, plainly stated. *Depth:* minimal copy per offer.
  - **Planner triggers:** Business runs promotions or financing.
  - **URL pattern:** /specials/ (ratified §1.2 — reserved root slug).
  - **Page structure:** 1. HeroStandard → 2. Offer cards (title, value, terms, expiry, CTA) → 3. Financing block → 4. Fine print (AlertNote) → 5. CTABand
  - **UI components:** HeroStandard, ServiceCardGrid (offer cards), AlertNote, CTABand
  - **Schema:** Offer per card
  - **Internal links (body):** relevant service pages
  - **Required inputs:** current offers with terms and expiry
  - **Pitfalls:** Expired offers left live.

#### Warranty / Guarantee Page — ⭐ SOP extension

  - **Local Service · Bottom · AIO: Low · Writer: \#12**
  - **What it is:** Risk reversal: workmanship guarantees, warranty terms, coverage.
  - **Content spec:** *Angle:* the promise in plain language — what's covered, for how long, how to claim, with the confidence of a company that expects to honor it. *Avoid:* hedge-everything legalese up front (put conditions after the promise). *Depth:* 400–800 words.
  - **Planner triggers:** Business offers guarantees (nearly all should).
  - **URL pattern:** /warranty/ (ratified §1.2 — reserved root slug).
  - **Page structure:** 1. HeroStandard (guarantee headline) → 2. Coverage SpecTable → 3. Claim process (StepList) → 4. Manufacturer vs. workmanship explainer → 5. FAQAccordion → 6. CTABand
  - **UI components:** HeroStandard, SpecTable, StepList, FAQAccordion, CTABand
  - **Schema:** FAQPage
  - **Internal links (body):** About Us, service pages
  - **Required inputs:** actual warranty terms (legal sign-off)
  - **Pitfalls:** Vague guarantee language that overpromises.

#### Campaign / Paid Landing Page (renamed — was "Local Landing Page" in v3.0)

  - **Local Service · Bottom · AIO: n/a · Writer: live**
  - **What it is:** Paid/seasonal campaign page with a single conversion goal and minimal nav. **Renamed to avoid colliding with the SOP's "Local Landing Page" (which means the service × city page).**
  - **Content spec:** *Angle:* one idea, message-matched to the ad that brought the visitor — same offer, same language, single conversion action. *Depth:* 200–400 words.
  - **Planner triggers:** Site runs paid campaigns or promos needing dedicated destinations.
  - **URL pattern:** /lp/{campaign-slug}/ — typically noindexed; exempt from the SOP global nav rule by design.
  - **Page structure:** 1. HeroStandard (offer-led) → 2. Benefit trio (StatCallout) → 3. ProofBlock + TrustBadgeRow → 4. Offer detail + urgency (AlertNote) → 5. LeadForm → 6. Compressed FAQAccordion → 7. CTABand. Logo + phone only, no global nav.
  - **UI components:** HeroStandard, StatCallout, ProofBlock, TrustBadgeRow, LeadForm, CTABand
  - **Schema:** none; noindex typical
  - **Required inputs:** offer, audience, proof, form destination
  - **Pitfalls:** Nav leakage; offer/ad mismatch.

### 5.2 Ecommerce Family

*Blog posts for ecommerce sites (buying-adjacent informational content, how-to feeders): see the* ***Blog Post sub-family in §5.3****.*

#### Product Page — CORE

  - **Ecommerce · Bottom · AIO: Med · Writer: live**
  - **What it is:** One page per SKU/product: specs, benefits, purchase.
  - **Content spec:** *Angle:* benefit-led opening, spec-complete body — sell the outcome, then satisfy the researcher. Original copy always (never manufacturer boilerplate). *Must cover:* who it's for, key benefits, full specs, objection handling (shipping, returns, authenticity, compatibility), usage summary. *Depth:* 300–800 words plus structured data.
  - **Planner triggers:** Always (CORE) for ecommerce.
  - **URL pattern:** /products/{product-slug}/
  - **Page structure:** 1. Gallery + buy box (price, variants, add-to-cart, stock, TrustBadgeRow) → 2. Benefit-led description → 3. SpecTable → 4. How-to-use summary → link to usage guide → 5. Reviews section → 6. FAQAccordion → 7. RelatedPagesBlock (cross-sells, category)
  - **UI components:** SpecTable, TrustBadgeRow, FAQAccordion, RelatedPagesBlock
  - **Schema:** Product + Offer + AggregateRating, FAQPage, BreadcrumbList
  - **Internal links:** ↔ category page, usage guides, comparison pages
  - **Required inputs:** product data feed, images, reviews
  - **Pitfalls:** Manufacturer-copy duplication; missing Product schema fields.

#### Category / Collection Page — CORE

  - **Ecommerce · Mid · AIO: Med · Writer: live/\#6**
  - **What it is:** Product listing page with buying-criteria content — structurally different from product pages.
  - **Content spec:** *Angle:* the buying-criteria educator — below the grid, teach how to choose within this category (the specs that matter, the trade-offs, who needs what). *Voice:* knowledgeable shop staff. *Depth:* 300–600 words of criteria content.
  - **Planner triggers:** Always (CORE); one per category with ≥ 3 products.
  - **URL pattern:** /collections/{category-slug}/
  - **Page structure:** 1. HeroAnswer (category definition + who it's for) → 2. Filter/sort bar + product grid → 3. Buying criteria guide (below grid: how to choose, key specs explained) → 4. ComparisonTable (top products in category) → 5. FAQAccordion → 6. RelatedPagesBlock (subcategories, guides)
  - **UI components:** HeroAnswer, ComparisonTable, FAQAccordion, RelatedPagesBlock
  - **Schema:** CollectionPage + ItemList, FAQPage, BreadcrumbList
  - **Internal links:** → products, buying guide, category-vs-category pages
  - **Required inputs:** category taxonomy, buying criteria content
  - **Pitfalls:** Zero-content grid pages; criteria content hidden behind tabs where crawlers deprioritize it.

#### Buying Guide / "Best X" Roundup

  - **Ecommerce · Top · AIO: High · Writer: \#2**
  - **What it is:** Ranked list of best products in a category with selection methodology.
  - **Content spec:** *Angle:* methodology-transparent reviewer — name the top pick immediately, show how picks were chosen, give every pick at least one honest con. Credible cons are what make the pros believable (and citable). *Must cover:* quick-picks table, per-pick verdicts with best-for framing, selection methodology, buying criteria. *Depth:* 1,500–2,500 words.
  - **Planner triggers:** Category has "best \[x\]" search volume; store carries ≥ 4 qualifying products (or covers market honestly).
  - **URL pattern:** /guides/best-{category-slug}/
  - **Page structure:** 1. HeroAnswer (top pick named immediately) → 2. Quick-picks summary table (ComparisonTable: pick, best-for, price) → 3. Per-product review blocks (image, verdict, ProsConsPair, buy link) → 4. Methodology / how we chose → 5. Buying criteria explainer → 6. FAQAccordion → 7. AlertNote (last-updated date)
  - **UI components:** HeroAnswer, ComparisonTable, ProsConsPair, FAQAccordion, AlertNote
  - **Schema:** ItemList, FAQPage, Article, BreadcrumbList
  - **Internal links:** → product pages, category page, comparison pages
  - **Required inputs:** honest ranking criteria, product data, methodology
  - **Pitfalls:** Self-serving rankings with no methodology — AIO systems discount these.

#### Product Comparison Page

  - **Ecommerce · Bottom · AIO: Med · Writer: \#1**
  - **What it is:** "\[Product A\] vs \[Product B\]" head-to-head.
  - **Content spec:** *Angle:* spec-honest head-to-head — verdict first, then evidence; end with segment-mapped recommendations ("A for X users, B for Y"). *Depth:* 800–1,500 words.
  - **Planner triggers:** Pairs buyers actually compare (search data or sales-team input).
  - **URL pattern:** /compare/{product-a}-vs-{product-b}/
  - **Page structure:** As Comparison Page (5.1) with product imagery in the table header and buy CTAs per column.
  - **UI components:** HeroAnswer, ComparisonTable, ProsConsPair, FAQAccordion, CTABand
  - **Schema:** Product (both), FAQPage, BreadcrumbList
  - **Internal links:** → both product pages, category
  - **Required inputs:** spec data both products
  - **Pitfalls:** Stale specs after product updates — bind to the product data feed.

#### Alternatives Page (Ecommerce)

  - **Ecommerce · Bottom · AIO: Med · Writer: \#2**
  - **What it is:** "\[Popular product\] alternatives" capturing buyers seeking substitutes.
  - **Content spec:** *Angle:* reason-based routing — organize alternatives by WHY someone leaves the anchor product (price, stock, features, values) and route each reason to its best substitute. Never disparage the anchor. *Depth:* 1,000–1,800 words.
  - **Planner triggers:** A popular/branded product has alternative-seeking volume and the store carries substitutes.
  - **URL pattern:** /alternatives/{product-slug}-alternatives/
  - **Page structure:** As Buying Guide with an anchor-product framing section first (why people look for alternatives — price, stock, features), then ranked alternatives.
  - **UI components:** As Buying Guide
  - **Schema:** ItemList, FAQPage, BreadcrumbList
  - **Required inputs:** anchor product facts, substitute list with honest positioning
  - **Pitfalls:** Disparaging the anchor product; factual tone mandatory.

#### Brand Page — MATRIX

  - **Ecommerce · Mid · AIO: Low · Writer: \#5**
  - **What it is:** One page per carried brand: brand story + that brand's products.
  - **Content spec:** *Angle:* the curator's endorsement — why we chose to carry this brand, what it's known for, where it fits in the lineup. *Must cover:* authenticity/warranty facts, brand positioning. *Depth:* 300–600 words plus grid.
  - **Planner triggers:** Store carries ≥ 3 brands with brand-search volume. Count = brands.
  - **URL pattern:** /brands/{brand-slug}/
  - **Page structure:** 1. HeroStandard (brand logo + positioning) → 2. Why we carry this brand → 3. Product grid filtered to brand → 4. Brand FAQAccordion (warranty, authenticity, shipping) → 5. RelatedPagesBlock (brand comparisons, guides)
  - **UI components:** HeroStandard, FAQAccordion, RelatedPagesBlock
  - **Schema:** Brand + ItemList, BreadcrumbList
  - **Required inputs:** brand list, brand descriptions, authenticity/warranty facts
  - **Pitfalls:** Pure grid with no brand content — thin duplicate of a filtered category.

#### How-To / Usage Guide

  - **Ecommerce · Top · AIO: High · Writer: \#11**
  - **What it is:** "How to use/set up/apply X" content feeding product pages from the top of funnel.
  - **Content spec:** *Angle:* practitioner instruction — prerequisites first, numbered steps with the details beginners miss, common mistakes called out. For regulated products (supplements, peptides): compliance-safe framing, no medical claims, research-use language where applicable. *Depth:* 800–1,500 words.
  - **Planner triggers:** Products require technique, preparation, or protocol knowledge (supplements, tools, equipment, skincare).
  - **URL pattern:** /guides/how-to-{topic-slug}/
  - **Page structure:** 1. HeroAnswer (summary of the method) → 2. What you'll need (linked product list) → 3. StepList with images per step → 4. AlertNote (safety/storage/compliance) → 5. Common mistakes → 6. FAQAccordion → 7. RelatedPagesBlock (products, related guides)
  - **UI components:** HeroAnswer, StepList, AlertNote, FAQAccordion, RelatedPagesBlock
  - **Schema:** HowTo, FAQPage, BreadcrumbList
  - **Internal links:** → product pages, category; ← product pages' usage sections
  - **Required inputs:** verified usage protocol from SME; compliance review for regulated products
  - **Pitfalls:** Regulated-category claims (supplements/peptides: research-use framing, no medical claims).

#### Size / Spec Guide

  - **Ecommerce · Mid · AIO: High · Writer: \#11**
  - **What it is:** Sizing charts, fitment tables, spec explainers that remove purchase objections.
  - **Content spec:** *Angle:* precision plus edge cases — the chart is table stakes; the value is measuring guidance and between-sizes/borderline-fit advice. *Depth:* 400–800 words plus real HTML tables.
  - **Planner triggers:** Products have size/fit/compatibility uncertainty (apparel, parts, equipment).
  - **URL pattern:** /guides/{category-slug}-size-guide/
  - **Page structure:** 1. HeroAnswer → 2. SpecTable (size/fit matrix) → 3. How to measure (StepList + diagram) → 4. Between-sizes / edge-case guidance → 5. FAQAccordion → 6. CTABand (shop the category)
  - **UI components:** HeroAnswer, SpecTable, StepList, FAQAccordion, CTABand
  - **Schema:** FAQPage, BreadcrumbList
  - **Internal links:** ↔ category and product pages
  - **Required inputs:** accurate size/spec data
  - **Pitfalls:** Chart-image-only pages (inaccessible + unextractable) — real HTML tables required.

#### Category vs Category Page

  - **Ecommerce · Top–Mid · AIO: High · Writer: \#1**
  - **What it is:** Concept-level comparison ("tankless vs tank," "whey vs casein") — not SKU vs SKU.
  - **Content spec:** *Angle:* concept educator — explain the underlying difference (technology, mechanism, trade-off), then map to use cases; stay conceptual, never collapse into SKU comparison. *Depth:* 1,000–1,800 words.
  - **Planner triggers:** Category pair with real "vs" search volume and a genuine buyer decision.
  - **URL pattern:** /guides/{category-a}-vs-{category-b}/
  - **Page structure:** As Comparison Page (5.1) ending with category CTAs into both collections.
  - **UI components:** HeroAnswer, ComparisonTable, ProsConsPair, FAQAccordion, CTABand
  - **Schema:** FAQPage, Article, BreadcrumbList
  - **Required inputs:** honest concept-level criteria
  - **Pitfalls:** Collapsing into a product comparison — keep it conceptual.

### 5.3 Content & Authority Family

#### Blog Post — CORE (sub-family)

Blog posts are cross-family: every site family uses them. The formats below share the blog silo, /blog/{post-slug}/ URLs, Article + FAQPage schema, the SOP rule that **informational content is never geo-targeted** (the local geo post is the sole, SOP-sanctioned exception), and the internal-linking pattern of feeding a pillar and/or money page while linking silo siblings. Where a format repeats those defaults, its entry lists only what differs. **Planner note:** blog posts are planned per cluster, never ad hoc; assign every post to a silo and a target format before generation.

##### Informational Cluster Post — CORE

  - **All families · Top · AIO: Med–High · Writer: live**
  - **What it is:** The default evergreen post — answers one informational query inside a topic cluster, feeds its pillar.
  - **Content spec:** *Angle:* brief-driven, answer-first — resolve the query in the opening, then earn the rest with depth the SERP consensus lacks (original examples, data, contrarian-but-defensible takes). *Voice:* per brand guide. *Depth:* 1,000–2,000 words, brief-determined.
  - **Planner triggers:** CORE wherever content marketing is in scope; one per cluster-keyword in the content plan.
  - **Page structure:** 1. HeroAnswer (title + answer-shaped intro) → 2. AuthorByline → 3. TOCSidebar (\> 1,200 words) → 4. Body, H2 question headings, StatCallout/DefinitionBox where relevant → 5. Key takeaways box → 6. FAQAccordion → 7. AuthorByline (expanded) → 8. RelatedPagesBlock (cluster siblings + pillar)
  - **UI components:** HeroAnswer, AuthorByline, TOCSidebar, StatCallout, DefinitionBox, FAQAccordion, RelatedPagesBlock
  - **Schema:** Article, FAQPage, BreadcrumbList
  - **Internal links:** → pillar, cluster siblings, relevant money page; ← pillar
  - **Required inputs:** brief (from Brief Generator), author entity
  - **Pitfalls:** Orphaned posts outside any cluster; missing author E-E-A-T; thin rehash of SERP consensus.

##### Listicle / Roundup Post

  - **All families · Top · AIO: High · Writer: \#2 (roundup)**
  - **What it is:** "N ways / N best / N types" enumerated post — scannable, extractable, link-friendly.
  - **Content spec:** *Angle:* the useful list — each item genuinely distinct and self-contained, ordered deliberately (not filler to hit a number); the intro states the takeaway before the list. *Voice:* per brand guide, brisk. *Depth:* 1,200–2,200 words; item count set by genuine substance, not a round number.
  - **Planner triggers:** Cluster keyword with "best/types/ways/examples/ideas" intent.
  - **Page structure:** 1. HeroAnswer (what the list delivers + top item named) → 2. TOCSidebar (jump-to items) → 3. Item blocks (consistent shape: heading, image where relevant, 80–200 words each) → 4. How-to-choose / criteria note → 5. FAQAccordion → 6. RelatedPagesBlock
  - **UI components:** HeroAnswer, TOCSidebar, ProsConsPair (where items compete), FAQAccordion, RelatedPagesBlock
  - **Schema:** Article, ItemList, FAQPage, BreadcrumbList
  - **Required inputs:** item set with real per-item substance, ranking/order rationale
  - **Pitfalls:** Padding to a number; identical-shape items with nothing distinct to say.

##### Comparison / "Vs" Post (informational)

  - **All families · Top–Mid · AIO: High · Writer: \#1**
  - **What it is:** Informational "A vs B" framing in the blog silo — concept/option comparison, distinct from the commercial Comparison Page (§5.1/§5.5) and the ecommerce Category-vs-Category page. Per SOP, informational so blog-silo and never geo-targeted.
  - **Content spec:** *Angle:* the neutral explainer — verdict-first, honest trade-offs, "choose A if / choose B if" mapped to reader situations; educates rather than sells. *Voice:* per brand guide, even-handed. *Depth:* 1,000–1,800 words.
  - **Planner triggers:** Cluster has a genuine either/or question with informational (not transactional) intent.
  - **Page structure:** 1. HeroAnswer (verdict in 2 sentences) → 2. ComparisonTable → 3. Per-option deep dive (ProsConsPair) → 4. "Choose A if / Choose B if" → 5. FAQAccordion → 6. RelatedPagesBlock (→ related money page if one exists)
  - **UI components:** HeroAnswer, ComparisonTable, ProsConsPair, FAQAccordion, RelatedPagesBlock
  - **Schema:** Article, FAQPage, BreadcrumbList
  - **Internal links:** → the commercial comparison/category page if one exists (hand off transactional intent), pillar
  - **Required inputs:** honest criteria both options
  - **Pitfalls:** Drifting into a sales page (that's the commercial comparison type's job); false balance where one option is clearly better.

##### Local Geo Post (City / POI)

  - **Local Service · Top · AIO: Low–Med · Writer: live (geo-content variant)**
  - **What it is:** The SOP-sanctioned geo-targeted post — content about a city, neighborhood, or point of interest that builds geographic relevance for the location silo. **The one blog format that IS geo-targeted, per SOP.**
  - **Content spec:** *Angle:* genuinely useful local content (local guide, area explainer, event/landmark context) with an organic tie to the service area — relevance-building, not thin service copy in disguise. *Voice:* local, informed. *Depth:* 600–1,200 words.
  - **Planner triggers:** Location silo needs geo-relevance reinforcement; a city/POI with real informational substance.
  - **Page structure:** 1. HeroAnswer (local topic) → 2. Local body content (entities, landmarks, specifics) → 3. Organic tie to relevant service/location page → 4. RelatedPagesBlock (location parent, related local landing pages) → 5. Soft CTABand
  - **UI components:** HeroAnswer, MapEmbed (where relevant), RelatedPagesBlock, CTABand
  - **Schema:** Article, BreadcrumbList; Place where applicable
  - **Internal links:** → location page parent, related local landing pages; ← location silo
  - **Required inputs:** verified local facts/entities
  - **Pitfalls:** Disguised service copy with a city name (fails as informational AND as local proof).

##### News / Commentary Post — non-evergreen

  - **All families · Top · AIO: Low–Med · Writer: live / \#13 where data-backed**
  - **What it is:** Timely reaction to industry news, updates, or trends. **Time-decaying, not evergreen** — does not cluster like the other formats and needs a freshness policy. Maps to the Nova Life "Peptide News Curator" workflow.
  - **Content spec:** *Angle:* informed take — lead with what happened and why it matters to the reader, then the brand's perspective; value is timeliness + interpretation, not comprehensiveness. *Voice:* per brand guide, current. *Depth:* 500–1,200 words.
  - **Planner triggers:** Ongoing news/commentary program exists (e.g., a curator workflow); NOT part of evergreen cluster planning. Planner MUST tag these as non-evergreen and exclude them from pillar-cluster math.
  - **Page structure:** 1. HeroAnswer (what happened + why it matters) → 2. AuthorByline → 3. Context/background → 4. Analysis / brand take → 5. What it means for the reader → 6. AlertNote (published date — freshness critical) → 7. RelatedPagesBlock (evergreen posts on the topic)
  - **UI components:** HeroAnswer, AuthorByline, AlertNote, RelatedPagesBlock
  - **Schema:** NewsArticle or Article, BreadcrumbList
  - **Internal links:** → relevant evergreen cluster posts/pillar (route decaying traffic to durable pages); ← rarely linked from evergreen (avoid tying durable pages to decaying ones)
  - **Required inputs:** the news item, sources, brand POV; freshness/review or sunset policy
  - **Pitfalls:** Slotting into evergreen clusters; no published date; stale posts left ranking on outdated info.

#### Pillar / Hub Page

  - **Content · Top–Mid · AIO: Med · Writer: \#6**
  - **What it is:** Cluster parent covering a broad topic comprehensively, linking down to every child post.
  - **Content spec:** *Angle:* the comprehensive survey — cover the whole topic at useful depth where each chapter delivers standalone value AND routes to its child post for more. *Depth:* 2,000–4,000 words.
  - **Planner triggers:** A topic cluster of ≥ 5 planned/existing posts.
  - **URL pattern:** /{topic-slug}/ (top-level)
  - **Page structure:** 1. HeroAnswer (topic definition) → 2. TOCSidebar → 3. Chapter sections (each: substantive summary + link to child post) → 4. DefinitionBox glossary strip (key terms → glossary pages) → 5. FAQAccordion → 6. RelatedPagesBlock (sibling pillars)
  - **UI components:** HeroAnswer, TOCSidebar, DefinitionBox, FAQAccordion, RelatedPagesBlock
  - **Schema:** Article, FAQPage, BreadcrumbList
  - **Internal links:** → every cluster child, glossary; ← every child, nav
  - **Required inputs:** cluster map with child summaries
  - **Pitfalls:** Thin link-list pillars — each chapter needs standalone value.

#### Glossary / Definition Page — MATRIX

  - **Content + SaaS · Top · AIO: High · Writer: \#3**
  - **What it is:** One page per term: definition-first, extraction-optimized. Same writer serves informational sites and SaaS category glossaries.
  - **Content spec:** *Angle:* reference-neutral — the 40–60 word definition must fully resolve the query alone (the AIO extract); everything after adds context, examples, and related-term contrast. *Voice:* encyclopedia, zero marketing until the closing CTA. *Depth:* 300–600 words.
  - **Planner triggers:** Category is jargon-heavy; term list ≥ 10. Count = terms.
  - **Query patterns:** "what is \[term\]," "\[term\] meaning," "\[term\] vs \[related term\]"
  - **URL pattern:** /glossary/{term-slug}/ + /glossary/ index (writer \#6)
  - **Page structure:** 1. DefinitionBox (term + 40–60 word definition — the extract) → 2. Expanded explanation → 3. Example in context → 4. Related terms (RelatedPagesBlock) → 5. Compact FAQAccordion (2–3) → 6. Soft CTABand (relevant product/pillar)
  - **UI components:** DefinitionBox, RelatedPagesBlock, FAQAccordion, CTABand
  - **Schema:** DefinedTerm, FAQPage, BreadcrumbList
  - **Internal links:** ↔ related terms, pillar, product pages using the term
  - **Required inputs:** term list with definitions, relations, examples
  - **Pitfalls:** Definitions that require reading the whole page — the box must stand alone.

#### Statistics / Data Roundup Page

  - **Content · Top · AIO: High · Writer: \#13**
  - **What it is:** Aggregated statistics on a topic, formatted for citation and link-earning.
  - **Content spec:** *Angle:* citable-number formatting — each stat is a self-contained, sourced, dated unit a journalist can lift; narrative is connective tissue only. *Must cover:* source + year on every number, methodology of aggregation, last-updated date. *Depth:* 1,000–2,000 words.
  - **Planner triggers:** Topic where journalists/bloggers cite stats; link-building is a goal.
  - **URL pattern:** /statistics/{topic-slug}-statistics/
  - **Page structure:** 1. HeroAnswer (headline stat) → 2. Key stats summary (StatCallout grid, each individually citable with source) → 3. Themed stat sections → 4. Methodology/sources list → 5. AlertNote (last updated) → 6. Embed/cite-this block → 7. FAQAccordion
  - **UI components:** HeroAnswer, StatCallout, AlertNote, FAQAccordion
  - **Schema:** Article, Dataset (where applicable), FAQPage
  - **Required inputs:** sourced stat inventory with dates and citations
  - **Pitfalls:** Unsourced or stale stats — every number needs source + year; annual refresh policy.

#### Original Research / Survey Page

  - **Content · Top · AIO: High · Writer: \#13**
  - **What it is:** Primary data published as the citable source (survey results, internal dataset analysis).
  - **Content spec:** *Angle:* journalism of your own data — lead with the most surprising finding, support with charts, expose full methodology (sample, dates, method) so citation is safe. *Depth:* 1,500–3,000 words.
  - **Planner triggers:** A defensible data source exists (survey capability, proprietary dataset, DataForSEO pulls at scale).
  - **URL pattern:** /research/{study-slug}/
  - **Page structure:** 1. HeroStandard (headline finding) → 2. Key findings (StatCallout grid) → 3. Charts per finding with commentary → 4. Full methodology (sample, dates, method) → 5. Data table / downloadable dataset → 6. Press/cite kit → 7. AuthorByline → 8. CTABand
  - **UI components:** HeroStandard, StatCallout, SpecTable, AuthorByline, CTABand
  - **Schema:** Article + Dataset, BreadcrumbList
  - **Required inputs:** the study itself — data, methodology, charts
  - **Pitfalls:** Weak methodology disclosure kills citations; plan promotion before production.

### 5.4 Cross-Vertical — Competitor-Branded Family

#### \[Competitor\] Review Page

  - **Cross-vertical · Bottom · AIO: Med · Writer: \#1**
  - **What it is:** Honest third-person review of a competitor, capturing their branded research traffic.
  - **Content spec:** *Angle:* the fair analyst — genuine strengths covered first and specifically (this is what earns trust and rankings), limitations factual and dated, verdict framed as fit ("right for X, not for Y"). *Must cover:* what it is, pricing summary, strengths, limitations, fit guidance, dated facts. *Depth:* 1,200–2,000 words.
  - **Planner triggers:** Named competitors with review-search volume; brand willing to publish fair coverage.
  - **URL pattern:** /reviews/{competitor-slug}-review/
  - **Page structure:** 1. HeroAnswer (balanced verdict) → 2. What \[competitor\] is (facts: features, pricing summary, fit) → 3. Strengths (genuine) → 4. Limitations (factual) → 5. Who it's right for / not for → 6. "How we compare" section (brief, linked to comparison page) → 7. FAQAccordion → 8. AlertNote (review date) → 9. Soft CTABand
  - **UI components:** HeroAnswer, ProsConsPair, ComparisonTable, FAQAccordion, AlertNote, CTABand
  - **Schema:** Article, FAQPage, BreadcrumbList (Review schema only with genuine rating methodology)
  - **Internal links:** ↔ comparison page, alternatives page for same competitor
  - **Required inputs:** verified competitor facts with capture dates
  - **Pitfalls:** Hit-piece tone destroys rankings and trust; factual-fair is mandatory; stale facts.

#### \[Competitor\] Pricing Page

  - **Cross-vertical · Bottom · AIO: High · Writer: \#7**
  - **What it is:** Breakdown of a competitor's pricing tiers — extremely high intent.
  - **Content spec:** *Angle:* the factual reporter — their tiers, verified and dated, explained more clearly than they explain it themselves; your own comparison is a secondary section, not the frame. *Depth:* 800–1,500 words.
  - **Planner triggers:** Competitor pricing is public/verifiable and searched.
  - **URL pattern:** /pricing/{competitor-slug}-pricing/
  - **Page structure:** 1. HeroAnswer (their price range in 2 sentences) → 2. PricingTierCards or SpecTable (their tiers, verified) → 3. What each tier includes/excludes → 4. Hidden costs / limits → 5. How our pricing compares (honest table) → 6. FAQAccordion → 7. AlertNote (verified as of {date}) → 8. CTABand
  - **UI components:** HeroAnswer, PricingTierCards, SpecTable, ComparisonTable, FAQAccordion, AlertNote, CTABand
  - **Schema:** FAQPage, BreadcrumbList
  - **Required inputs:** verified competitor pricing with capture date; refresh policy (quarterly minimum)
  - **Pitfalls:** Stale third-party pricing is a credibility bomb — freshness process is non-negotiable.

### 5.5 B2B Services + SaaS Family

#### Alternatives Page (SaaS/B2B)

  - **SaaS/B2B · Bottom · AIO: Med · Writer: \#2**
  - **What it is:** "\[Competitor\] alternatives" — typically the highest-converting SaaS page type.
  - **Content spec:** *Angle:* the honest broker — you're the featured alternative, but real alternatives get real coverage including when THEY are the better fit; organized around why people switch from the anchor. Readers smell a rigged list instantly. *Depth:* 1,500–2,500 words.
  - **Planner triggers:** Named competitors with alternative-seeking volume.
  - **URL pattern:** /alternatives/{competitor-slug}-alternatives/
  - **Page structure:** 1. HeroAnswer (best alternative named = you, with honest framing) → 2. Why people switch from \[competitor\] (factual pain points) → 3. Quick ComparisonTable (you + 4–6 real alternatives) → 4. Per-alternative blocks (including honest coverage of others) → 5. Deep dive on your fit → 6. Migration path teaser → link → 7. FAQAccordion → 8. CTABand
  - **UI components:** HeroAnswer, ComparisonTable, ProsConsPair, FAQAccordion, CTABand
  - **Schema:** ItemList, FAQPage, BreadcrumbList
  - **Internal links:** ↔ comparison page, migration guide, competitor review
  - **Required inputs:** verified competitor facts, honest positioning per alternative
  - **Pitfalls:** Listing only yourself; readers and engines both discount it.

#### Comparison Page (SaaS/B2B)

  - **SaaS/B2B · Bottom · AIO: Med · Writer: \#1**
  - **What it is:** "\[You\] vs \[Competitor\]" head-to-head.
  - **Content spec:** *Angle:* the fair fight — concede the points the competitor genuinely wins (this is the page's trust engine), win on evidence elsewhere, close with when-each-wins guidance. *Must cover:* dated feature/pricing facts both sides. *Depth:* 1,200–2,200 words.
  - **Planner triggers:** Competitors buyers actively shortlist against.
  - **URL pattern:** /compare/{you}-vs-{competitor-slug}/
  - **Page structure:** 1. HeroAnswer (fair summary of when each wins) → 2. ComparisonTable (features, pricing, support, fit) → 3. Where we win (evidence) → 4. Where they win (honest — this earns the page trust) → 5. Pricing comparison → 6. Switching path → 7. FAQAccordion → 8. CTABand
  - **UI components:** HeroAnswer, ComparisonTable, PricingTierCards, FAQAccordion, CTABand
  - **Schema:** FAQPage, BreadcrumbList
  - **Required inputs:** verified feature/pricing data both sides, dated
  - **Pitfalls:** One-sided tables read as ads; concede real points.

#### Migration / Switching Guide

  - **SaaS/B2B · Bottom · AIO: Low · Writer: \#11**
  - **What it is:** Step-by-step guide to switching from a competitor — removes the switching-cost objection.
  - **Content spec:** *Angle:* reassurance through specificity — exactly what transfers, exactly what doesn't, real timeline, honest effort estimate. Vague "easy migration" claims increase anxiety; specifics reduce it. *Depth:* 800–1,500 words.
  - **Planner triggers:** Competitor with meaningful installed base; switching is genuinely nontrivial.
  - **URL pattern:** /migrate/{competitor-slug}/
  - **Page structure:** 1. HeroStandard (time/effort promise) → 2. What transfers (SpecTable: data types × supported) → 3. StepList (the migration) → 4. Timeline expectations → 5. Support/concierge offer → 6. ProofBlock (a completed migration) → 7. FAQAccordion → 8. CTABand
  - **UI components:** HeroStandard, SpecTable, StepList, ProofBlock, FAQAccordion, CTABand
  - **Schema:** HowTo, FAQPage, BreadcrumbList
  - **Internal links:** ← alternatives + comparison pages
  - **Required inputs:** real migration process, transfer capabilities
  - **Pitfalls:** Promising smoother migration than reality delivers.

#### Use Case Page

  - **SaaS/B2B · Mid · AIO: Med · Writer: \#10**
  - **What it is:** Job-to-be-done page — persona-agnostic, problem-shaped ("track X," "automate Y").
  - **Content spec:** *Angle:* problem-native — open in the user's own words for the job, explain the mechanism of why the problem exists BEFORE introducing the product (the mechanism section is the AIO asset), then walk the product through the job. *Depth:* 800–1,400 words.
  - **Planner triggers:** Product serves ≥ 2 distinct jobs; each job has problem-shaped search demand.
  - **URL pattern:** /use-cases/{job-slug}/
  - **Page structure:** 1. HeroStandard (job stated in user language) → 2. The problem today (status quo pain) → 3. The mechanism (why the problem happens — AIO section) → 4. Product walkthrough for this job (capability blocks with screenshots) → 5. ProofBlock → 6. FAQAccordion → 7. RelatedPagesBlock (other use cases, personas) → 8. CTABand
  - **UI components:** HeroStandard, StepList, ProofBlock, FAQAccordion, RelatedPagesBlock, CTABand
  - **Schema:** FAQPage, BreadcrumbList
  - **Internal links:** ↔ feature pages, persona/vertical pages
  - **Required inputs:** job definition, capability mapping, screenshots, proof
  - **Pitfalls:** Blurring into persona pages — jobs here, identities there.

#### Industry / Vertical Page

  - **SaaS/B2B · Mid · AIO: Med · Writer: \#10**
  - **What it is:** Segmentation by buyer identity ("\[Product\] for Attorneys") with vertical-specific mechanism content.
  - **Content spec:** *Angle:* vertical fluency — the reader's vocabulary, their buying triggers, the citation sources and constraints unique to their industry, their compliance realities (regulated verticals). Must fail the swap test: replacing the vertical name should break the page. *Depth:* 1,500–2,600 words.
  - **Planner triggers:** Vertical with identity-attached search demand AND vertical research inputs available (swap-test rule).
  - **URL pattern:** /for/{vertical-slug}/ or /{topic}-for-{vertical-slug}/
  - **Page structure:** 1. HeroStandard (vertical H1 + vertical fear/hook) → 2. The shift/problem in vertical language → 3. Vertical-specific mechanism section (E-E-A-T core — must fail the swap test) → 4. Product walkthrough with vertical examples → 5. Compliance note (regulated verticals only: legal/medical/financial) → 6. Vertical ProofBlock → 7. FAQAccordion (vertical-specific) → 8. CTABand
  - **UI components:** HeroStandard, AlertNote, ProofBlock, FAQAccordion, CTABand
  - **Schema:** FAQPage, BreadcrumbList; Service + audience for service businesses
  - **Internal links:** ↔ use case pages, sibling verticals via "Who we help" block, /industries/ hub once ≥ 3 exist
  - **Required inputs:** vertical research (query patterns, citation sources, constraints), vertical proof
  - **Pitfalls:** Noun-swap doorway pages — if replacing the vertical name doesn't break the page, don't ship it.

#### Role / Persona Page

  - **SaaS/B2B · Mid · AIO: Low · Writer: \#10**
  - **What it is:** Segmentation by job title ("for agencies," "for marketing managers").
  - **Content spec:** *Angle:* role-mirror — what this role owns, reports, and fears; outcomes framed in the metrics this role is judged on. *Depth:* 800–1,400 words.
  - **Planner triggers:** Distinct buyer roles with different value props; role-attached search or sales-enablement need.
  - **URL pattern:** /for/{role-slug}/
  - **Page structure:** As Industry page minus compliance; mechanism section replaced by role-specific workflow/outcomes (what this role reports, owns, fears).
  - **UI components:** As Industry page
  - **Schema:** FAQPage, BreadcrumbList
  - **Required inputs:** role pain points, role-relevant capability mapping
  - **Pitfalls:** Same swap-test rule as verticals.

#### Company-Size Page

  - **SaaS/B2B · Mid · AIO: Low · Writer: \#10**
  - **What it is:** "For startups / SMB / enterprise" messaging pages.
  - **Content spec:** *Angle:* fit honesty — what's genuinely different for this segment (pricing, onboarding, features), including who the product is NOT for at this size. *Depth:* 500–900 words.
  - **Planner triggers:** Product genuinely differs by segment (pricing, features, onboarding); "\[product category\] for small business"-type volume exists.
  - **URL pattern:** /for/{size-slug}/
  - **Page structure:** Compressed Industry-page skeleton (6 sections): hero → size-specific pains → fit/features for this size → pricing fit → proof → CTA.
  - **UI components:** HeroStandard, PricingTierCards, ProofBlock, CTABand
  - **Schema:** BreadcrumbList
  - **Required inputs:** segment-specific fit facts
  - **Pitfalls:** Thinnest of the segmentation set — only build with real differentiation.

#### Integration / Partner Page — MATRIX

  - **SaaS · Mid–Bottom · AIO: Low · Writer: \#5**
  - **What it is:** One page per integration — long-tail individually, high-value in aggregate. Ideal structured-data pipeline fit.
  - **Content spec:** *Angle:* concrete mechanics — the exact data flows, triggers, and actions of THIS pairing plus 2–3 real workflow examples; the per-integration specifics are what separate the page from boilerplate. *Depth:* 400–800 words per cell.
  - **Planner triggers:** Product has ≥ 5 integrations. Count = integrations; flag \> 200.
  - **URL pattern:** /integrations/{partner-slug}/ + /integrations/ index (writer \#6)
  - **Page structure:** 1. HeroStandard (both logos + one-line value of the pairing) → 2. What the integration does (data flows, SpecTable: triggers/actions) → 3. Setup (StepList) → 4. Use-case examples (2–3) → 5. FAQAccordion → 6. RelatedPagesBlock (similar integrations) → 7. CTABand
  - **UI components:** HeroStandard, SpecTable, StepList, FAQAccordion, RelatedPagesBlock, CTABand
  - **Schema:** SoftwareApplication reference, FAQPage, BreadcrumbList
  - **Required inputs:** integration dataset (partner, capabilities, setup steps, category)
  - **Pitfalls:** Identical boilerplate per partner — capability/setup data must be per-integration real.

#### Individual Feature Page

  - **SaaS · Bottom · AIO: Med · Writer: \#10/\#11 hybrid**
  - **What it is:** One capability, explained as "what," for "\[capability\] tool/software" queries too narrow for product pages.
  - **Content spec:** *Angle:* the factual "what" — capability, limits, plan availability, shown more than told (annotated screenshots carry the page); adjacent "why" lives on use-case pages. *Depth:* 500–1,000 words.
  - **Planner triggers:** Capability with its own search demand or demo-request pattern.
  - **URL pattern:** /features/{feature-slug}/
  - **Page structure:** 1. HeroStandard (capability + outcome) → 2. How it works (annotated screenshots / StepList) → 3. What you can do with it (mini use-case list, linked) → 4. SpecTable (limits, availability by plan) → 5. FAQAccordion → 6. RelatedPagesBlock (adjacent features) → 7. CTABand
  - **UI components:** HeroStandard, StepList, SpecTable, FAQAccordion, RelatedPagesBlock, CTABand
  - **Schema:** FAQPage, BreadcrumbList
  - **Internal links:** ↔ use cases, pricing, integrations
  - **Required inputs:** feature facts, screenshots, plan matrix
  - **Pitfalls:** Marketing-fluff "why" content — this page is the factual "what."

#### Customer Story / Case Study (SaaS/B2B)

  - **SaaS/B2B · Bottom · AIO: Low · Writer: \#9**
  - **What it is:** Named-customer story with hard numbers (ROI %, hours saved).
  - **Content spec:** *Angle:* journalistic before/after — the customer's situation and numbers tell the story; the customer's voice (real quotes) delivers the verdict; the product appears as the mechanism, not the hero. *Must cover:* verified metrics, named customer with permission. *Depth:* 800–1,500 words.
  - **Planner triggers:** Real customer with measurable results and permission; plan 3+ before a hub page.
  - **URL pattern:** /customers/{customer-slug}/
  - **Page structure:** 1. HeroStandard (headline metric + logo) → 2. StatCallout row (3 key metrics) → 3. Customer context → 4. Challenge → 5. Solution (capabilities used, linked) → 6. Results with evidence → 7. TestimonialCard (real quote) → 8. RelatedPagesBlock (similar stories) → 9. CTABand
  - **UI components:** HeroStandard, StatCallout, TestimonialCard, RelatedPagesBlock, CTABand
  - **Schema:** Article, BreadcrumbList
  - **Required inputs:** verified metrics, approved quotes, logo permission
  - **Pitfalls:** Fabricated customers/metrics — never; unverifiable claims read as fake to humans and engines.

#### Security / Compliance / Trust Page

  - **SaaS/B2B · Bottom · AIO: Med · Writer: \#12**
  - **What it is:** Security posture, certifications, data handling — decisive for mid-market/enterprise.
  - **Content spec:** *Angle:* questionnaire-grade precision — write for the security reviewer who will paste claims into a vendor assessment; every statement exact, no puffery, nothing aspirational stated as current. *Depth:* 600–1,200 words.
  - **Planner triggers:** B2B sales motion where security review occurs; any compliance certification held.
  - **URL pattern:** /security/ or /trust/
  - **Page structure:** 1. HeroStandard (posture statement) → 2. TrustBadgeRow (SOC 2, GDPR, HIPAA — only what's actually held) → 3. Data handling (encryption, residency, retention — SpecTable) → 4. Access controls & practices → 5. Uptime/status link → 6. Subprocessors list → 7. FAQAccordion (security-questionnaire staples) → 8. Contact security team CTA
  - **UI components:** HeroStandard, TrustBadgeRow, SpecTable, FAQAccordion, CTABand
  - **Schema:** WebPage, FAQPage, BreadcrumbList
  - **Required inputs:** actual certifications and practices — legal review required
  - **Pitfalls:** Claiming certifications in progress as held; doubles as sales collateral, so accuracy is contractual.

#### Testimonial / Review Roundup Page

  - **SaaS/B2B · Bottom · AIO: Low · Writer: \#12**
  - **What it is:** Social-proof hub aggregating quotes, ratings, and links to case studies.
  - **Content spec:** *Angle:* curation over copy — real quotes organized by segment, third-party ratings linked at the source; minimal editorial. *Depth:* framing copy only.
  - **Planner triggers:** ≥ 8 real testimonials or third-party reviews exist.
  - **URL pattern:** /reviews/ or /customers/
  - **Page structure:** 1. HeroStandard (aggregate proof headline) → 2. Third-party rating badges (G2/Capterra/Google — real only) → 3. TestimonialCard grid, filterable by segment → 4. Featured ProofBlocks linking to case studies → 5. CTABand
  - **UI components:** HeroStandard, TrustBadgeRow, TestimonialCard, ProofBlock, CTABand
  - **Schema:** BreadcrumbList (AggregateRating only from legitimate third-party sources)
  - **Required inputs:** real testimonials with permission; ratings links
  - **Pitfalls:** Stock-photo personas and invented quotes — a trust page with fake trust signals is worse than no page.

#### Pricing Page (Own)

  - **SaaS · Bottom · AIO: High · Writer: \#7**
  - **What it is:** The product's own pricing — high search volume, high scrutiny.
  - **Content spec:** *Angle:* clarity plus justification — what each tier costs, exactly what you get, why it's priced that way; surface the limits buyers would otherwise discover angrily later. *Depth:* 400–800 words plus tables.
  - **Planner triggers:** CORE for SaaS with public pricing.
  - **URL pattern:** /pricing/
  - **Page structure:** 1. HeroStandard (pricing philosophy one-liner) → 2. PricingTierCards (with billing toggle if applicable) → 3. Full feature ComparisonTable across tiers → 4. Usage/credit explainer if metered → 5. FAQAccordion (billing, trials, cancellation) → 6. Enterprise/custom CTA → 7. TrustBadgeRow + guarantee
  - **UI components:** HeroStandard, PricingTierCards, ComparisonTable, FAQAccordion, TrustBadgeRow
  - **Schema:** Product + Offer per tier, FAQPage, BreadcrumbList
  - **Required inputs:** current pricing, tier matrix, billing rules
  - **Pitfalls:** Tier table drift vs. actual billing; hidden-limit surprises surfacing in reviews.

#### ROI / Savings Calculator

  - **SaaS/B2B · Mid–Bottom · AIO: Low · Writer: \#14**
  - **What it is:** Interactive calculator quantifying the product's value; backlink magnet.
  - **Content spec:** *Angle:* transparent math — the copy's job is defending the assumptions; publish the formula and let conservative inputs make the case. *Depth:* methodology copy 300–600 words.
  - **Planner triggers:** Value is quantifiable with defensible formula inputs.
  - **URL pattern:** /roi-calculator/ or /tools/{calc-slug}/
  - **Page structure:** 1. HeroStandard → 2. CalculatorShell (inputs left, live results right; email-gate the detailed report only) → 3. Methodology/assumptions (transparent formula) → 4. ProofBlock (real customer matching the math) → 5. FAQAccordion → 6. CTABand
  - **UI components:** HeroStandard, CalculatorShell, ProofBlock, FAQAccordion, CTABand
  - **Schema:** WebApplication, BreadcrumbList
  - **Required inputs:** formula with defensible assumptions
  - **Pitfalls:** Fantasy assumptions inflating ROI — publish the methodology.

#### Free Tool / Lead-Magnet Page

  - **SaaS/B2B · Top–Mid · AIO: Low · Writer: \#14**
  - **What it is:** Functional free tool (checker, generator, template) driving signups and links.
  - **Content spec:** *Angle:* value before ask — the tool delivers something genuinely useful ungated; copy explains what it does and how results were computed; the upgrade pitch follows delivered value. *Depth:* 300–600 words around the tool.
  - **Planner triggers:** A product capability can be scoped down into a genuinely useful free version.
  - **URL pattern:** /tools/{tool-slug}/
  - **Page structure:** 1. HeroStandard (tool promise) → 2. The tool itself (CalculatorShell or custom, above fold, usable without signup) → 3. Results display with gated depth → 4. How it works → 5. FAQAccordion → 6. Upgrade path CTABand
  - **UI components:** HeroStandard, CalculatorShell, FAQAccordion, CTABand
  - **Schema:** WebApplication, FAQPage, BreadcrumbList
  - **Required inputs:** working tool spec, gating rules
  - **Pitfalls:** Gating before any value — free layer must genuinely deliver.

#### Template / Resource Library — MATRIX

  - **SaaS/B2B · Top–Mid · AIO: Low · Writer: \#5**
  - **What it is:** One page per template/resource from a dataset; library index above.
  - **Content spec:** *Angle:* per-item usefulness — each template's page says who it's for, when to use it, and how, in the item's own terms. *Depth:* 200–400 words per item.
  - **Planner triggers:** ≥ 10 templates/resources producible from one data structure. Count = items.
  - **URL pattern:** /templates/{template-slug}/ + /templates/ index (writer \#6)
  - **Page structure:** Item page: 1. HeroStandard (template name + preview image) → 2. What it's for / who it's for → 3. Preview (embedded or gallery) → 4. How to use (StepList) → 5. Download/use CTA (gate optional) → 6. RelatedPagesBlock (similar templates)
  - **UI components:** HeroStandard, StepList, RelatedPagesBlock, CTABand
  - **Schema:** CreativeWork, BreadcrumbList
  - **Required inputs:** template dataset (name, category, preview, file/link, use notes)
  - **Pitfalls:** Thin identical wrappers — per-item use-case notes required.

  

## 6\. Writer Archetype Map

Page types collapse into shared writer modules by **data shape**, not vertical. Build \~14 writers, not \~40 page types.

  

|  |  |  |  |  |
| :-: | :-: | :-: | :-: | :-: |
| \*\*\\\#\*\* | \*\*Writer Archetype\*\* | \*\*Data Shape\*\* | \*\*Covers\*\* | \*\*Pipeline Fit\*\* |
| 1 | \*\*Entity × entity comparison\*\* | Two entities + criteria table | SaaS comparison, ecommerce product comparison, local service comparison, category vs category, \\\[competitor\\\] review | Research-assisted |
| 2 | \*\*Alternatives / roundup\*\* | One anchor entity + N alternatives, ranked | SaaS alternatives, ecommerce alternatives, "best X" buying guides | Research-assisted |
| 3 | \*\*Glossary / definition\*\* | Single term + related terms | Informational + SaaS glossaries | Structured-in / page-out |
| 4 | \*\*FAQ\*\* | Question set + schema | Standalone FAQ (all families), FAQ blocks in other writers | Structured-in / page-out |
| 5 | \*\*Programmatic matrix\*\* | Entity A × entity B from dataset | Local landing pages (service × location, live), brand × service, integration pages, template libraries, brand pages | \*\*Structured-in / page-out — location-generator model\*\* |
| 6 | \*\*Hub / index\*\* | Child-page list + taxonomy | Areas We Serve, blog/project archives, Services index, pillar pages, library indexes | Structured-in / page-out |
| 7 | \*\*Cost / pricing\*\* | Price ranges + factors + tiers | Local cost pages, SaaS pricing pages, \\\[competitor\\\] pricing pages | Research-assisted; freshness policy required |
| 8 | \*\*Problem / symptom\*\* | Symptom → causes → fixes → CTA | Local problem pages | Research-assisted |
| 9 | \*\*Case study / proof\*\* | Client + situation + metrics | Local project pages, SaaS customer stories | Client-data-in |
| 10 | \*\*Segmentation page\*\* | Segment profile + pain points + fit | Use case, industry/vertical, role/persona, company-size | Structured-in with ICP/vertical research |
| 11 | \*\*How-to / guide\*\* | Steps + prerequisites + pitfalls | Usage guides, migration guides, size/spec guides | Research-assisted |
| 12 | \*\*Trust / credential\*\* | Certs, policies, guarantees | Security, warranty, about, offers, testimonial hubs | Client-data-in |
| 13 | \*\*Data / research\*\* | Dataset + methodology + findings | Stats roundups, original research | Data-pipeline-in |
| 14 | \*\*Interactive tool\*\* | Formula + inputs + UI | ROI calculators, free tools | Separate pattern (AR Tools interactive) |

  

**Pipeline fit legend:** *Structured-in / page-out* = deterministic from a dataset, cheapest at scale. *Research-assisted* = needs SIE/research modules per page. *Client-data-in* = requires client-supplied inputs. *Data-pipeline-in* = requires a data acquisition step first.

  

## 7\. Priority Tiers (planner output uses these)

  - **Tier 1 — Core:** every CORE entry for the site's family/families.
  - **Tier 2 — Revenue-nearest:** cost/pricing pages, comparison + alternatives, use case pages, competitor-branded pages (where triggers matched).
  - **Tier 3 — Authority & trust:** about, case studies, security/warranty, FAQ, glossary, problem pages.
  - **Tier 4 — Scale:** matrix types (brand × service, integrations, templates, glossary expansion) and hubs once children exist.
  - **Tier 5 — Investment:** original research, calculators, free tools.

  

**Global rules for all consuming apps:** never fabricate proof (testimonials, metrics, customers, team members, stock-photo personas); every pricing/stat page carries a freshness date; segmentation pages must fail the swap test before shipping; matrix page types require pruning rules for thin cells.

  