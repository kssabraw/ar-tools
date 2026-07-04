# Site Architecture, URL Structure, and Internal Linking SOP

**Current as of:** 02 July 2026
**Revision:** v2 — all page-type schemas aligned to AR Single Schema Creator v1.1 (Organization + Brand model, real GBP reviews, single deduped `@graph`); FAQ restored on every type; `@id`s unified; internal-linking matrix and glossary added.
**Goal:** Build a website that is easy to crawl for both Googlebot and users.
**Who this is for:** All SEO and Web Design clients.
**When this is done:** During all site builds, and whenever new pages are added.
**Assigned to:** per `_ORCHESTRATOR.md` §6 (roles matrix).
**Scope:** This SOP is a **strategy/structure layer** — it decides which pages belong on a site, at what URLs, with what nav, schema, and internal links. Its output is a **site plan** (page list + specs). Content creation is out of scope and handled by the content production pipeline.

---

## Glossary

- **NAP** — Name, Address, Phone; the business's core contact identity, kept consistent across the site and citations.
- **GBP** — Google Business Profile (formerly Google My Business); the business's Google listing. The "GBP-linked page" is the page whose URL is set as the website link in the GBP.
- **CID** — Google Customer ID; the unique identifier for a GBP listing.
- **USP** — Unique Selling Proposition; what differentiates the business.
- **CTA** — Call To Action.
- **POI** — Point of Interest. _(Deprecated in this SOP — POI pages are not used.)_
- **Silo** — A theme-based cluster of related, interlinked pages that concentrates topical relevance.
- **Link equity / link juice** — The ranking value passed between pages through links.
- **Hub page** — An index/archive page linking to a set of child pages (e.g. `/services/`, `/areas-we-serve/`).
- **Local landing page** — A `(service) in (city)` page targeting geographic search intent.
- **`@graph`** — A JSON-LD container holding multiple linked schema entities under one `@context`, cross-referenced by `@id`.
- **`@id`** — A stable identifier for a schema entity, used to reference it from other entities and reconcile it across pages.

---

## Global Navigation & Footer

These rules apply to **every page type** on the site. They are stated once here; individual page sections below specify only their **body-content** links.

**Global navigation (identical on every page):**
Home · About Us · Services · Areas We Serve · Blog · Contact

**Global footer (identical on every page):**
All navigation links above **plus Privacy Policy**. Privacy Policy appears in the **footer only** — never in the main navigation.

**Dropdown vs. hub-page rule (applies to Services and to Areas We Serve / locations):**

- **7 or fewer items:** list the individual pages as a dropdown under the nav item. No hub page is created.
- **8 or more items:** create the hub page (`/services/` or `/areas-we-serve/`), collapse the nav item to a single link pointing at that hub, and list the individual pages in the hub's body content.

The Services hub (`/services/`) and the Areas We Serve hub (`/areas-we-serve/`) **exist only when their item count is ≥ 8.**

---

## Schema Conventions

Source of truth: **AR Single Schema Creator v1.1** (one consolidated workflow that routes all page types through a `Switch` and builds each block in deterministic code). These conventions apply to every page type.

- **Entity model = Organization + Brand.** The business is a canonical `Organization` (`@id` `{home_page_url}#organization`) plus a companion `Brand` node (`@id` `{home_page_url}#brand`). The **`Brand` node holds `aggregateRating` and the reviews**; the Organization carries identity (`name`, `legalName`, `logo`, `address`, `sameAs`), `knowsAbout`, `hasOfferCatalog`, and a `brand` reference.
- **Reviews are real.** Reviews and ratings come from live GBP data (filtered), not LLM-authored text. _(Resolves the earlier fabricated-reviews flag.)_
- **GBP-linked page = LocalBusiness subtype.** The one page whose URL is the GBP website link uses a `LocalBusiness` (or a detected subtype such as `Plumber`, `Attorney`, `MedicalClinic`) with `geo`, `openingHoursSpecification`, `address`, and its own `aggregateRating`/`review`. Its `@id` is the canonical `{home_page_url}#organization` (unified with the Organization used on every other page), so the whole site reads as one business — typed as `LocalBusiness` here, `Organization` elsewhere.
- **FAQPage on every page.** Every page type includes an `FAQPage` block built from the page content (see Shared Schema Blocks). **Exception: the Privacy Policy** — not a ranking target; it carries no page-type schema requirements. _Note: v1.1 as shipped does not emit FAQ; the workflow needs an FAQ builder re-added per the earlier subworkflows to match this SOP._
- **Single `@graph`, deduped by `@id`.** Each page emits one top-level `@graph` with a single `@context`; the assembler dedupes nodes by `@id`. _(Resolves the earlier flat-array flag — production now matches this SOP.)_
- **Cross-entity links by `@id`:** `provider` → Organization, `parentOrganization` → Brand, `publisher`/`worksFor` → Organization, `isPartOf` → WebSite, `mainEntityOfPage` → WebPage, `author` → Person.
- **Field bindings (v1.1 form fields):** `Owner/Manager`, `Owner/Manager Bio Page`, `Name Of Service/Target Keyword`, `URL Of Page`, `Home Page URL`, `Citations And Social Media`, plus GBP Info, TextRazor entities, and DataForSEO topics.

### Shared Schema Blocks

The blocks below are **identical across every page type**. Each page-type section lists which of these it includes plus its own primary block, rather than repeating these in full.

**Organization + Brand** (included on every non-GBP page):
```json
{
  "@type": "Organization",
  "@id": "{home_page_url}#organization",
  "name": "", "legalName": "", "url": "{home_page_url}",
  "logo": "{logo_url}", "image": "",
  "description": "", "telephone": "",
  "address": { "@type": "PostalAddress", "streetAddress": "", "addressLocality": "", "addressRegion": "", "postalCode": "", "addressCountry": "" },
  "knowsAbout": [ "{category + 25 entities from TextRazor/DataForSEO}" ],
  "sameAs": [ "{citations_and_social_media}" ],
  "hasOfferCatalog": {
    "@type": "OfferCatalog",
    "name": "{services offered}",
    "itemListElement": [ { "@type": "Offer", "itemOffered": { "@type": "Service", "name": "{service_name}" } } ]
  },
  "brand": { "@id": "{home_page_url}#brand" }
}
```
```json
{
  "@type": "Brand",
  "@id": "{home_page_url}#brand",
  "name": "",
  "aggregateRating": { "@type": "AggregateRating", "ratingValue": "{from GBP}", "reviewCount": "{from GBP}" },
  "review": [
    { "@type": "Review", "author": { "@type": "Person", "name": "{gbp reviewer}" }, "reviewBody": "{gbp review text}", "reviewRating": { "@type": "Rating", "ratingValue": "{gbp rating}" } }
  ]
}
```

**WebPage** (base; the `@type` and `@id` fragment change per page role — see note):
```json
{
  "@type": "WebPage",
  "@id": "{url_of_page}#webpage",
  "url": "{url_of_page}", "name": "", "headline": "", "description": "",
  "wordCount": "{word_count}", "datePublished": "{first publish — preserved on regeneration}", "dateModified": "{now}",
  "isPartOf": { "@type": "WebSite", "@id": "{home_page_url}#website", "url": "{home_page_url}" },
  "about": [ { "@type": "Thing", "name": "{topic label}", "sameAs": ["{wikidata + wikipedia}"] } ],
  "mentions": [ { "@type": "Thing", "name": "{entity}", "sameAs": ["{wikidata + freebase + wikipedia}"] } ],
  "significantLink": [""],
  "relatedLink": [""]
}
```
WebPage subtypes by page role: About Us → `@type: "AboutPage"`, `@id: {url}#aboutpage`; Bio → `@type: "ProfilePage"`, `@id: {url}#profilepage`; Contact → `@type: "ContactPage"`, `@id: {url}#contactpage`. All other pages use `WebPage` / `#webpage`.

**Person** (included wherever a page cites an owner/author):
```json
{
  "@type": "Person",
  "@id": "{owner_manager_bio_page}",
  "name": "{owner_manager}", "jobTitle": "", "description": "",
  "worksFor": { "@type": "Organization", "@id": "{home_page_url}#organization" },
  "knowsAbout": [""],
  "memberOf": [],
  "sameAs": [""]
}
```

**FAQPage** (included on every page; built from the page's content):
```json
{
  "@type": "FAQPage",
  "@id": "{url_of_page}#faq",
  "mainEntity": [
    { "@type": "Question", "name": "", "acceptedAnswer": { "@type": "Answer", "text": "" } }
  ]
}
```

_`worksFor.@id` uses `{home_page_url}#organization` so it reconciles with the Organization node. Overrides the v1.1 agent example (bare home URL); the workflow needs the `#organization` fragment to match._

---

## Agent Operating Notes

**Cross-references:** decision ownership, shared definitions (incl. "highly competitive"), global rules, and the workflow chain live in **`_ORCHESTRATOR.md`** — read it before executing this SOP. This SOP's output (the site plan) is consumed by the content pipeline and the Link Building SOP per the workflow chain.

**Required data sources (fetch, don't guess):** services/locations/sub-services lists and leadership names (from the client); GBP website-link URL; page-1 avg RD/DR (Ahrefs/Majestic) and DataForSEO competitiveness for any third-level gate; Google Maps for the neighborhood test.

**Halt-and-ask triggers (this SOP):**
1. The services or locations list is missing, ambiguous, or looks wrong (e.g., a "service" that's really a sub-service) — confirm with a human before planning.
2. The GBP website-link URL is unknown — the GBP-variant designation (Step 9) cannot be made; ask.
3. Competitive-gate data (RD/DR/DataForSEO) can't be fetched for a proposed third-level page — do not create the page on a guess.
4. The business doesn't fit the model: service-area business with no physical address, franchise/multi-brand, e-commerce, or >100 locations — these need human strategy input; the algorithm's defaults are untested there.
5. Any instruction conflicts with `_ORCHESTRATOR.md` shared definitions — report, don't resolve silently.

**Edge cases (handled — do not halt):** single-city business (no location pages; services target the city — Step 4); single service (plan collapses to Home/About/Contact/Privacy/Blog + 1 service page + locations); services or locations exactly at the 7/8 boundary (rule is exact: ≤7 dropdown, ≥8 hub).

---

# Site Architecture Overview

## What is Site Architecture?

Site architecture refers to the hierarchical structure and organization of a website's content. It encompasses the way pages are categorized, linked, and presented to users and search engines. A well-designed site architecture makes it easy for users to navigate the website and find the information they need while allowing search engines to efficiently crawl and index the site's content.

A logical site architecture is essential for both SEO and UX purposes. By organizing your website's content in a clear and intuitive manner, you improve the ability of search engines to crawl and index your pages while providing a seamless user experience.

Implementing best practices for site architecture, such as creating a clear hierarchy, using descriptive URLs, and optimizing internal linking, can significantly enhance your website's SEO performance and user engagement. By prioritizing logical site architecture, you lay the foundation for a successful online presence that attracts, retains, and converts visitors effectively.

## Benefits of Logical Site Architecture for SEO

- **Improved Crawlability:** A logical site architecture enables search engine bots to easily navigate the website and discover all important pages. A clear hierarchy and internal linking structure ensure that search engines can find and index content efficiently.
- **Link Equity Distribution:** A logical site architecture allows for efficient distribution of link equity ("link juice") throughout the website. By strategically linking important pages and ensuring all pages are reachable within a few clicks, you boost the overall SEO value of the site.

## Benefits of Logical Site Architecture for UI

- **Enhanced User Experience:** A well-organized website with a logical structure makes it easier for users to find information. Grouping related content and using clear navigation menus reduces cognitive load and provides a more intuitive browsing experience.
- **Reduced Bounce Rates:** When users can quickly find what they are looking for, they are less likely to leave prematurely. A logical site architecture minimizes confusion and frustration, reducing bounce rates.
- **Improved Conversion Rates:** A user-friendly architecture guides visitors toward conversion goals — a purchase, a form fill, a subscription. Strategically placed CTAs and a logical flow optimize the site for conversions.

## Importance of Logical Site Architecture for Technical SEO

- **Discoverability:** A well-structured architecture makes it easier for Googlebot to discover all important pages. Hierarchical organization and clear internal linking ensure relevant pages get found, accessed, and indexed.
- **Understanding Content Relevance:** A logical structure helps Google understand the relevance and context of pages. Grouping related content and using descriptive categories gives Google clear signals about each page's topic and purpose.
- **Link Equity Distribution:** An optimized architecture ensures link equity is efficiently distributed. Linking strategically from high-authority pages to important content helps Google identify the most valuable pages.
- **Sitemaps and Indexation:** A logical architecture makes it easier to create comprehensive, accurate XML sitemaps, helping ensure all important pages are discovered and indexed.
- **Avoiding Duplicate Content:** A well-organized architecture minimizes duplicate-content risk. Canonical tags and properly structured URLs help Google identify the authoritative version of each page.

---

# How To Structure A Site

## PageRank Principles

The rules an SEO (or agent) must apply when making structural decisions. The worked model that derives them follows as rationale.

1. **Every outgoing link divides a page's passable value.** A page splits its passable PageRank across *all* its outgoing links — nav, footer, and body alike. More links out = less value per link. Do not add links to a high-value page without a reason.
2. **Adding pages to a category dilutes every existing page in it.** New pages added under a hub cut the share every sibling receives (e.g., a hub going from 28 to 38 outgoing links drops each child's share by ~25%). New content is a relevance win but a per-page PageRank cost — plan category sizes deliberately.
3. **Deep pages live on a single link's share.** A page linked only from its hub receives only that hub's per-link fraction — often well under 1% of the site's total equity. If a deep page must rank, it needs additional internal links from high-value pages, or its own external links.
4. **A damping factor means value shrinks at every hop — external links beat internal links.** Not all inbound value is passed on (the original patent used ~15% loss). Internal linking redistributes equity but cannot create it; only external links add new equity to the system.
5. **The homepage is the equity reservoir.** It typically holds the most external links; every page it links to receives a meaningful share. Reserve homepage links for pages that matter, and keep important pages within few clicks of it.

### Rationale — the worked model behind the principles

Imagine you have a website. For simplicity, the website has ten overall categories, and each consists of ten pages. One of those categories is our "top level pages" and includes the Homepage, the About page, and a bunch of other top-level content that is linked to on every page of the whole site.

Each of those pages in the top-level category also links to a category homepage or index page.

The category pages each link to 9 other pages about the specific product or service the category is about. These are your second-tier content pages, and are the more specific pages for the product or service that the category focuses on.

So that's 10 top-level pages, each linking to each other plus to 9 category-level index pages. Only the category homepages link to the other 9 pages within each specific category.

With that simple structure in mind, imagine about 50% of all external links to the site point to the homepage, and another 50% in total point to various specific content pages or category index pages.

Those exact ratios are not too important; the main thing is that we account in some way for 100% of all the links pointing to your site, and thus 100% of all the link "juice" that flows into the site.

You have 100 pages, and 100% of your link "juice" value, pictured in your head, right?

Now remember the structure. Your homepage links to 9 other top-level pages and also to 9 category-level index pages. That's 18 links out from that page. So 100% of passable value is divided among the 18 links, meaning each gets 5.56% of the total passable link value from the homepage.

(There is actually a dampening factor, meaning not all the value of links coming to a page gets passed out again — a percentage is lost. The original patent had this at 15%, but it could be more, less, or even variable. For now we won't worry about the exact damping factor; just remember it exists, and is why direct links are still more valuable than internal links.)

So each top-level page is getting roughly 5% of the total link power the homepage has, based on the link structure. Each of those other top-level pages also links back to the homepage, to each other, and to those 9 category index pages, so each has 18 links total and passes just over 5% (5.6%) through each link. The homepage gets some added power from what it links to linking back, but it is only 5% of 5% (about 0.25% of the total value coming into the site).

The category-level index pages were also linked from every page, so they got the same 5.56% as the others. But each of those pages has 10 links to the 10 top-level pages, 9 links to the other category pages, and 9 links to the deep content pages in the category itself — 28 links the value has to be split between.

That means each category index page passes 1/28th of the 5.56% flowing in, or roughly 0.2%, to each page it links to.

For the deep pages inside a category — not linked directly from the rest of the site — that 0.2% is the **only** real link value they get. That's all the "juice" they have to work with when Google works out authority-style metrics.

If I create 10 new pages in one of those categories, so it now has 20 pages total, the category homepage that links to them now has 38 links instead of 28, and the juice passed to each is now 1/38th of the 5.56% instead of 1/28th. You added new content, hopefully more keywords — great for creating *relevant* pages — but you also dropped the PageRank of **all** the pages in the category. Instead of each getting 0.2%, now each gets 0.15%, or 25% less juice than before.

## Logical Site Layout

Sites should be laid out in a logical order, from least specific to most specific topics.

Each site should include:

- Home page (optimized for the brand)
- "About Us" page
- "Contact Us" page
- Privacy Policy
- A page for each service offered
- A page for each city or location targeted
- Blog archive page
- "Areas We Serve" page (this is an archive/hub page for the local landing pages, like a blog archive — see the dropdown vs. hub rule above)

---

## Site Theming

The site is organized under **one main topic** (see Maps SOP §Site Theming for the full model and audit). Structural rules this SOP enforces:

- **Home page = top of the silo**, targeting brand + main service.
- Silos break down into **services → sub-services** and **locations**, per the URL structures below.
- **Structural prominence follows the theme hierarchy:** the primary theme gets the home page and top silos; secondary services sit deeper, with fewer high-value internal links and less nav prominence.
- **GBP mirror:** every GBP category should have a corresponding silo on the site, and vice versa.

---

# Site Planning Algorithm

Given a business's inputs, this procedure deterministically produces the **site plan** — the full page list, URL map, and nav shape. An agent (or human) should be able to run it start-to-finish with no judgment calls except where a gate explicitly requires data.

## Required inputs

| Input | Example |
|---|---|
| Brand / business name | "Smith Plumbing" |
| Services (list) | plumbing, drain cleaning, water heaters, repiping, leak detection |
| Sub-services (list, per parent service) | 24-hour (under plumbing) |
| Locations targeted (list of cities) | 12 cities |
| Leadership/owners for bios (list) | 1 person |
| GBP website-link URL | which page the GBP points at |
| Competition level per target keyword | from SERP data *(used by Steps 7–8)* |

## Procedure

**Step 1 — Always-create pages (every site):**
`/` (Home) · `/about-us/` · `/contact-us/` · `/privacy-policy/` · `/blog/` (Blog Archive)

**Step 2 — Bios:** one page per leadership person → `/bio/{person-slug}/`

**Step 3 — Services:** one page per service → `/{service}/`
- Count services: **≤7** → nav dropdown of the individual pages, **no** `/services/` hub. **≥8** → create `/services/` hub; nav entry is a single link to it.

**Step 4 — Locations:**
- **Single-city business** → create **no** location pages; top-level service pages target that city. Skip to Step 6.
- Multi-city → one page per city → `/{location}/`
- Count locations: **≤7** → nav dropdown. **≥8** → create `/areas-we-serve/` hub; nav entry is a single link.

**Step 5 — Local landing pages (the L×S cross product):** for each location × each service → `/{location}/{service}/`
- **All** L×S combinations belong on the site plan — no cap. (This SOP decides what pages the site needs; build order and production pacing are the content pipeline's concern, not a structural decision.)

**Step 6 — Sub-services:** one non-geo page per sub-service → `/{service}/{subservice}/`

**Step 7 — Neighborhoods (conditional):** for each large city, run the Google Maps test — click the neighborhood on Google Maps; if it returns a left-panel description with associated entities, it qualifies → `/{location}/{neighborhood}/`

**Step 8 — Third-level hyper-specific pages (conditional, rare):** `/{location}/{service}/{subservice}/` or `/{location}/{neighborhood}/{subservice}/`
- Gate — on an **existing site**, a third-level page belongs on the plan only if **(a)** the target keyword is **highly competitive**, **AND (b)** the existing second-level page has failed to rank despite on-page, technical, and internal linking being solved. At **initial site planning** (no ranking history exists yet), **(a) alone qualifies** — condition (b) applies only when adding pages to a live site. *(Ruling 04 Jul 2026.)*
- **Highly competitive** (shared definition — `_ORCHESTRATOR.md` §2) = ANY of:
  - Page-1 average **true** RD **≥ 250** (tool read × 10 per the ×10 tool-visibility discount; ≈ 25 tool-measured), or page-1 average DR **≥ 50**, for the target keyword
  - DataForSEO **keyword_difficulty ≥ 50** (0–100 scale)
  - The vertical is **legal, finance, government, or health** — automatically highly competitive

**Step 9 — GBP-linked page designation:** whichever page the GBP website link points at gets the **GBP-linked schema variant** (LocalBusiness); all others use the standard variant (see Schema Conventions). Selection rules for *which* page the GBP should point at live in the Maps SOP (§The GBP Landing Page): multi-location → dedicated top-level location page per GBP; single GBP, multi-city → the GBP city's local landing page for its most valuable keyword (rule 1 — as in the golden trace); single-city single-service → home page if it ranks the main keyword; SAB → home page. The GBP-linked page is the **second most important page after the home page** and receives privileged internal linking (below).

**Step 10 — Nav assembly:** Home · About Us · Services (dropdown or hub link per Step 3) · Areas We Serve (dropdown or hub link per Step 4) · Blog · Contact. Footer = nav + Privacy Policy.

**Step 11 — Apply schemas and internal links:** assign each page on the plan its schema per its page-type section, and its body links per the Internal Linking Matrix.

## Worked Example — Golden Trace

**Inputs:** Smith Plumbing · 5 services (plumbing, drain cleaning, water heaters, repiping, leak detection) · 1 sub-service (24-hour, under plumbing) · 12 cities incl. Los Angeles · 1 bio (John Smith) · GBP points at `/los-angeles/plumbing/` · LA qualifies for 2 neighborhoods (Sherman Oaks, Van Nuys).

| Step | Result |
|---|---|
| 1 | `/` · `/about-us/` · `/contact-us/` · `/privacy-policy/` · `/blog/` — **5 pages** |
| 2 | `/bio/john-smith/` — **1 page** |
| 3 | 5 services ≤7 → **no** `/services/` hub; nav dropdown. 5 service pages (`/plumbing/`, `/drain-cleaning/`, …) — **5 pages** |
| 4 | 12 locations ≥8 → `/areas-we-serve/` hub **+** 12 location pages — **13 pages** |
| 5 | 12 × 5 = **60 local landing pages** (`/los-angeles/plumbing/`, …) |
| 6 | `/plumbing/24-hour/` — **1 page** |
| 7 | `/los-angeles/sherman-oaks/` · `/los-angeles/van-nuys/` — **2 pages** |
| 8 | "24 hour plumber los angeles" is highly competitive → plan-time gate ((a) alone — see Step 8) → `/los-angeles/plumbing/24-hour/` — **1 page** |
| 9 | `/los-angeles/plumbing/` = GBP-linked → LocalBusiness schema variant; all others standard |
| 10 | Nav: Home · About Us · Services ▾(5) · Areas We Serve → `/areas-we-serve/` · Blog · Contact. Footer adds Privacy Policy |

**Total: 88 pages.** Any agent running this algorithm on these inputs must produce exactly this site plan — this trace is the conformance test.

---

# Top Level Pages — URL Structure

| Page | URL pattern |
|---|---|
| Home Page | `https://site.com/` |
| About Us | `https://site.com/about-us/` |
| Bio Pages | `https://site.com/bio/{person-slug}/` |
| Contact Us | `https://site.com/contact-us/` |
| Privacy Policy | `https://site.com/privacy-policy/` |
| Services hub (conditional, ≥8 services) | `https://site.com/services/` |
| Top Level Service Pages | `https://site.com/service/`, `/service-2/`, `/service-3/`, … |
| Areas We Serve hub (conditional, ≥8 locations) | `https://site.com/areas-we-serve/` |
| Top Level Location Pages | `https://site.com/location/`, `/location-2/`, `/location-3/`, … |
| Blog Archive | `https://site.com/blog/` |

### Home Page

The home page targets **brand + main service** (e.g., title: "XYZ Plumber | Top Plumbing Services"). It is the **top of the site's silo** — it carries the brand/navigational intent *and* establishes the primary theme. Do not stuff it with every service keyword; one primary theme, plus the brand. *(Doctrine updated 02 Jul 2026 — previously "brand only, never the main keyword." See Maps SOP §Site Theming.)*

**Schema (merged single `@graph`).** Same composition as the standard **Local Landing Page**: `@graph` = **Organization + Brand** + **WebPage** + **Person** + **FAQPage** — all from [Shared Schema Blocks](#shared-schema-blocks). The WebPage uses the home URL (`@id {home_page_url}#webpage`); the services offered are expressed via the Organization's `hasOfferCatalog`.

**Notes:**
- Supersedes the earlier block-list spec (WebPage / Organization / Services list / Person). The "services list" is now the Organization's `hasOfferCatalog`, and reviews/rating live on the **Brand** node.
- `WebSite` is referenced inline via each WebPage's `isPartOf` (`@id {home_page_url}#website`), consistent with every other page. If you want a richly-defined `WebSite` node (e.g. with a `SearchAction` sitelinks searchbox), the home page is the place to add it.

### About Us Page

The About Us page should be about the company itself, not necessarily the services it provides. Include the history of the company, the mission statement, USP, and information about the owners or leadership team.

**Schema (merged single `@graph`).** `@graph` = **Organization + Brand** + **WebPage (AboutPage variant)** + **Person** + **FAQPage** — all from [Shared Schema Blocks](#shared-schema-blocks). The only page-specific detail: the WebPage block uses `@type: "AboutPage"` and `@id: {url_of_page}#aboutpage`. No Service, no BlogPosting.

### Bio Page

Bio pages go in-depth on the leadership team or owners. Each person gets their own page at `/bio/{person-slug}/`. Include professional accreditations, work history, educational background, professional social media, and any professional organizations they belong to. These build the "authority" of the company and leadership team and help potential customers get to know the company. Because bio pages sit at the root rather than nested under About Us, the parent/child relationship is carried by internal links (About Us ↔ Bio).

**Schema (merged single `@graph`).** `@graph` = **Organization + Brand** + **WebPage (ProfilePage variant)** + **Person** + **FAQPage** — all from [Shared Schema Blocks](#shared-schema-blocks). Page-specific detail: the WebPage block uses `@type: "ProfilePage"` and `@id: {url_of_page}#profilepage`, and the **Person** block is the subject of the page (the individual whose bio this is). No Service, no BlogPosting.

### Contact Us Page

The Contact Us page should be short — no need for hundreds or thousands of words. Include the NAP, GBP embed, a form fill, and a click-to-call button or link. Also include the company's social media.

**Schema (merged single `@graph`).** `@graph` = **Organization + Brand** + **WebPage (ContactPage variant)** + **Person** + **FAQPage** — all from [Shared Schema Blocks](#shared-schema-blocks). Page-specific detail: the WebPage block uses `@type: "ContactPage"` and `@id: {url_of_page}#contactpage`. No headline/description agent runs for this type. No Service, no BlogPosting.

### Services Page (hub)

Used **only** when there are 8 or more services (see the dropdown vs. hub rule). The Services hub is about the services offered. Optimize for the service keyword only — not service + geo. Copy should show the expertise and authority of the company, a list of services, and the benefits each service provides.

**Schema (merged single `@graph`).** `@graph` = **Organization + Brand** + **WebPage** + **Person** + **FAQPage** — all from [Shared Schema Blocks](#shared-schema-blocks). Page-specific: the Organization's **`hasOfferCatalog`** lists **every** individual service (one `Offer` -> `itemOffered` `Service` each), with each service's `provider` set to the Organization:

```json
"hasOfferCatalog": {
  "@type": "OfferCatalog",
  "name": "Services",
  "itemListElement": [
    {
      "@type": "Offer",
      "itemOffered": {
        "@type": "Service",
        "name": "{service_name}",
        "url": "{service_page_url}",
        "provider": { "@id": "{home_page_url}#organization" }
      }
    }
  ]
}
```

### Top Level Service Pages

Top level service pages should be about the service only. Unless the company operates in / targets a single city, top level service pages should **never** be geo-targeted. If the company targets only one city, then the top level service pages should target that city.

Optimize for the service keyword only — not service + geo. Copy should show the expertise and authority of the company and the benefits of the service.

**Schema (merged single `@graph`).** `@graph` = **Organization + Brand** + **WebPage** + **Service** (primary) + **Person** + **FAQPage** — companion blocks are the [Shared Schema Blocks](#shared-schema-blocks). Primary block:

```json
{
  "@type": "Service",
  "@id": "{url_of_page}#service",
  "name": "{name_of_service/target_keyword}",
  "url": "{url_of_page}",
  "provider": { "@id": "{home_page_url}#organization" },
  "parentOrganization": { "@id": "{home_page_url}#brand" },
  "description": "{service description, from agent}",
  "serviceOutput": [ "{outcome/benefit of the service}" ],
  "areaServed": "{inherited from Organization.areaServed; fallback: the business's country}"
}
```

**Notes:**
- `provider` -> Organization, `parentOrganization` -> Brand.
- The Organization block carries `hasOfferCatalog` (services offered), merged in by the Service branch.
- `areaServed` inherits from the Organization; falls back to the **business's country** if the org has none (US for current clients — never hardcode United States for international clients).

### Top Level Location Pages

Top level location pages should be about the locations the company is targeting. Each city gets its own page. If a company targets only one city, location pages are not needed.

Optimize for the geo keyword, and include all major services in H2s. Copy should show the expertise and authority of the company.

**Schema (merged single `@graph`).** `@graph` = **Organization + Brand** + **WebPage** + **Person** + **FAQPage** — all from [Shared Schema Blocks](#shared-schema-blocks). There is **no standalone Service node**; the services offered in this city are expressed through the Organization's **`hasOfferCatalog`** (`itemListElement` lists the services offered in this location).

**Notes:**
- Location pages model the city presence via the Organization's `hasOfferCatalog`, not a `Service` node.
- No standalone BlogPosting or Service node.

### Blog Archive Page

This page acts as a repository for blog posts. Users navigating here typically see the latest blog posts. Do not optimize for any keyword except "(brand) blog".

**Schema (merged single `@graph`).** `@graph` = **Organization + Brand** + **WebPage** + **Blog** (primary) + **Person** (author) + **FAQPage** — companion blocks from [Shared Schema Blocks](#shared-schema-blocks). Primary block:

```json
{
  "@type": "Blog",
  "@id": "{url_of_page}#blog",
  "headline": "",
  "alternativeHeadline": "",
  "description": "",
  "disambiguatingDescription": "",
  "about": [ { "@type": "Thing", "name": "" } ],
  "author": { "@id": "{owner_manager_bio_page}" },
  "publisher": { "@id": "{home_page_url}#organization" },
  "isPartOf": { "@id": "{home_page_url}#website" }
}
```

**Notes:** `author` -> Person node, `publisher` -> Organization node, `isPartOf` -> WebSite node, all by `@id`.

### Areas We Serve Page (hub)

Used **only** when there are 8 or more locations (see the dropdown vs. hub rule). This page acts as a repository for top level location pages. Users navigating here typically see a list of the locations served. Do not optimize for any keyword except "(brand) areas".

**Schema (merged single `@graph`).** `@graph` = **Organization + Brand** + **WebPage** + **Person** + **FAQPage** — all from [Shared Schema Blocks](#shared-schema-blocks). Plain `WebPage` (no Service/Blog/Collection primary); the page lists the location pages in its body content (see Internal Linking Matrix). _Per spec this is "WebPage + Organization + Person"; Brand (Organization's companion) and FAQPage are included per the every-page conventions (deliberate)._

---

# Second Level Pages — URL Structure

| Page | URL pattern |
|---|---|
| Local Landing Page | `https://site.com/location/service/`, `/location/service-2/`, … |
| Blog Posts | `https://site.com/blog/blog-name-here/` |
| Sub-Service Page (non-geo) | `https://site.com/service/subservice/` |
| Neighborhoods | `https://site.com/location/neighborhood/` |

### Local Landing Page

This page pushes the most geographically relevant power and is optimized for "(service) in (city)" keywords. It is most likely the page pushing the most power to the GBPs, and is hyper-relevant to "(service) in (city)" and "(service) near me" searches. These do not need to be unique from each other except to be geographically relevant.

> **Two schema variants (see Schema Conventions):** the **GBP-linked variant** (below) — the one local landing page whose URL is the GBP website link — uses a `LocalBusiness` (subtype). **Every other** local landing page uses the **standard variant**, identical except the business entity is **Organization + Brand** instead of the LocalBusiness.

**Standard variant — schema (merged single `@graph`).** `@graph` = **Organization + Brand** + **WebPage** + **Person** + **FAQPage** — all from [Shared Schema Blocks](#shared-schema-blocks). No standalone Service node; the services offered are expressed via the Organization's `hasOfferCatalog`. (Same composition as a Top Level Location Page.)

**Notes:**
- Same as the GBP-linked variant below, except the business is **Organization + Brand** (canonical `@id {home_page_url}#organization` / `{home_page_url}#brand`) rather than a page-scoped `LocalBusiness`.
- `LocalBusiness`-only properties (`geo`, `openingHoursSpecification`) do **not** carry over — they're invalid on `Organization` — and reviews/rating live on the **Brand** node.

**GBP-linked variant (route: GBP Landing Page).** The single local landing page whose URL is the GBP website link uses a **`LocalBusiness` (or detected subtype)** as its business entity instead of Organization + Brand. Its `@graph` = **LocalBusiness(subtype)** + **WebPage** + **Person** + **FAQPage**, with the Organization's `hasOfferCatalog` / `knowsAbout` merged onto the LocalBusiness. The LocalBusiness carries its own rating and reviews, so there is no separate Brand node.

```json
{
  "@type": "{detected subtype — default LocalBusiness; e.g. Plumber, Attorney, MedicalClinic}",
  "@id": "{home_page_url}#organization",
  "name": "",
  "url": "{gbp_page_url}",
  "description": "",
  "telephone": "",
  "image": "",
  "logo": "{logo_url}",
  "address": { "@type": "PostalAddress", "streetAddress": "", "addressLocality": "", "addressRegion": "", "postalCode": "", "addressCountry": "" },
  "geo": { "@type": "GeoCoordinates", "latitude": "{from GBP}", "longitude": "{from GBP}" },
  "aggregateRating": { "@type": "AggregateRating", "ratingValue": "{from GBP}", "reviewCount": "{from GBP}" },
  "openingHoursSpecification": [ "{from GBP work hours}" ],
  "review": [ "{real GBP reviews, filtered}" ],
  "sameAs": [ "{citations_and_social_media}" ]
}
```

**GBP-linked variant notes:**
- `@type` is the detected subtype from the subtype agent (defaults to `LocalBusiness`; a value of `ProfessionalService` is ignored in favor of `LocalBusiness`).
- **Recognized LocalBusiness subtypes** (use the most specific match): AnimalShelter · ArchiveOrganization · AutomotiveBusiness · ChildCare · Dentist · DryCleaningOrLaundry · EmergencyService · EmploymentAgency · EntertainmentBusiness · FinancialService · FoodEstablishment · GovernmentOffice · HealthAndBeautyBusiness · HomeAndConstructionBusiness · InternetCafe · LegalService · Library · LodgingBusiness · MedicalBusiness · RadioStation · RealEstateAgent · RecyclingCenter · SelfStorage · ShoppingCenter · SportsActivityLocation · Store · TelevisionStation · TouristInformationCenter · TravelAgency. *(ProfessionalService exists in the vocabulary but is ignored per the rule above.)*
- Reviews and rating come from live GBP data (filtered), not LLM text.
- **`@id` unified (resolved):** this LocalBusiness uses the canonical `{home_page_url}#organization`, so the GBP page and every other page describe one business — richly typed as `LocalBusiness` here, as `Organization` elsewhere. _Overrides v1.1 (which emits `{gbp_page_url}#localbusiness`); the workflow needs that id changed to match._

### Blog Post

Blog posts are mostly for informational-intent keywords — to drive nationwide traffic and build brand and authority, or to give more geographic relevance to the local landing pages. Informational-intent keywords should never be geographically targeted. Blog posts about a city, POI, or other geo area will naturally be geographically targeted to that area.

**Schema (merged single `@graph`).** `@graph` = **Organization + Brand** + **WebPage** + **BlogPosting** (primary) + **Person** (author) + **FAQPage** — companion blocks are the [Shared Schema Blocks](#shared-schema-blocks). Primary block:

```json
{
  "@type": "BlogPosting",
  "headline": "{from Create Headlines And Description agent}",
  "description": "{agent, or first ~160 chars of body}",
  "articleBody": "{page content, nav/footer/sidebar excluded}",
  "wordCount": "{word_count}",
  "dateCreated": "{first publish — preserved on regeneration}",
  "dateModified": "{now}",
  "datePublished": "{first publish — preserved on regeneration}",
  "keywords": "{TextRazor entity IDs, comma-joined}",
  "author": {
    "@type": "Person",
    "@id": "{owner_manager_bio_page}",
    "name": "{owner_manager}",
    "url": "{owner_manager_bio_page}"
  },
  "publisher": {
    "@type": "Organization",
    "@id": "{home_page_url}#organization",
    "logo": { "@type": "ImageObject", "url": "{logo_url}" }
  },
  "isPartOf": { "@type": "WebSite", "@id": "{home_page_url}#website" },
  "mainEntity": { "@type": "Thing", "name": "{name_of_service/target_keyword}" },
  "mainEntityOfPage": { "@type": "WebPage", "@id": "{url_of_page}#webpage" }
}
```

**Notes:**
- `publisher` references the Organization by `@id` and carries only the logo (no `name`).
- Inline `publisher` / `isPartOf` / `mainEntityOfPage` stubs dedupe against their full `@graph` nodes by `@id` at assembly.
- `author` references the Person node by its `@id` `{owner_manager_bio_page}` (matching the shared Person block), so they reconcile as one entity. _Overrides v1.1 (which emits `{...}#person`); the workflow needs that suffix removed to match._

### Sub-Service Page (non-geo)

A sub-service page is about a more specific service the company offers, **not** tied to a location. It lives under its parent service at `/service/subservice/` and is optimized for the bare sub-service keyword. (For the geo version — how the company provides that sub-service in a specific area — see Hyper-Specific Local Landing Page under Third Level Pages.)

**Schema (merged single `@graph`).** Same as a **Top Level Service Page**: `@graph` = **Organization + Brand** + **WebPage** + **Service** (primary) + **Person** + **FAQPage** (see [Top Level Service Pages](#top-level-service-pages)). The `Service` block's `name` is the sub-service; `provider` -> Organization, `parentOrganization` -> Brand.

### Neighborhoods Page

These pages are for more specific areas within a larger city. Not every city needs neighborhood pages — typically just larger cities with recognized neighborhoods. If in doubt, check Google Maps and click on neighborhoods listed in the city; if it returns information on the left-hand side with a description of the area and associated entities, it is a good candidate for a neighborhood page.

**Schema (merged single `@graph`).** Same as a **Top Level Location Page**: `@graph` = **Organization + Brand** + **WebPage** + **Person** + **FAQPage**, with the Organization's `hasOfferCatalog` expressing the services offered (no standalone Service node). See [Top Level Location Pages](#top-level-location-pages).

---

# Third Level Pages — URL Structure

| Page | URL pattern |
|---|---|
| Hyper-Specific Local Landing Page | `https://site.com/location/service/subservice/` |
| Hyper-Specific Neighborhood Page | `https://site.com/location/neighborhood/subservice/` |

These pages are for the most granular, hyper-targeted keywords. They should generally only be made for highly competitive topics, or for topics/services/areas the client cannot rank for despite all other efforts. We generally will not need to go this deep.

### Hyper-Specific Local Landing Page

This is the geo version of a sub-service: how the company provides a specific sub-service in a specific area, at `/location/service/subservice/`. Optimize for "(sub-service) in (city)" / "(sub-service) near me".

**Example:** A plumber has a local landing page at `site.com/los-angeles/plumber/` optimized for "plumber in los angeles" / "plumber near me". They also want to rank for "24 hour plumber in los angeles" — a different search vector with a more specific need. They create a hyper-specific local landing page at `site.com/los-angeles/plumber/24-hour/` targeting that keyword with its own messaging.

**Schema (merged single `@graph`).** Same as the standard **Local Landing Page**: `@graph` = **Organization + Brand** + **WebPage** + **Person** + **FAQPage** (see [Local Landing Page](#local-landing-page)). **Third-level rule:** a hyper-specific page uses the **Local Landing Page** schema when it is location-primary, or the **Service Page** schema when it is service-primary.

### Hyper-Specific Neighborhood Page

The neighborhood-scoped equivalent, at `/location/neighborhood/subservice/`, for the most granular neighborhood + sub-service targeting.

**Schema (merged single `@graph`).** Location-primary third-level page -> use the **Local Landing Page** schema: `@graph` = **Organization + Brand** + **WebPage** + **Person** + **FAQPage**. If a given third-level page is service-primary instead, use the **Service Page** schema.

---

# Internal Linking Overview

## What Is Internal Linking?

Internal linking is an important part of logical site architecture and SEO. By strategically linking relevant pages within a site, you establish a clear hierarchy, improve navigation, and distribute link equity ("link juice") throughout the website. This helps search engines and users understand the structure and relevance of your content. Effective internal linking enhances the user experience by guiding visitors to related, valuable content and encourages them to spend more time exploring the site.

## Why Is Internal Linking Important for SEO?

A primary benefit of internal linking is its ability to distribute link equity throughout the site. By strategically linking to important pages, you ensure the authority and value of one page is passed to others, boosting their SEO potential. Internal linking also helps create semantically related content silos — clusters of related content that search engines can easily identify and understand. Grouping relevant pages through internal links establishes a clear hierarchy and context, making the site easier for search engines to understand. Finally, internal linking enhances user navigation, letting visitors easily find and access related information.

## What Are Content Silos?

Content silos organize a website's content into distinct, theme-based sections. Each silo represents a main topic or theme, and within that silo you create a hierarchy of related subtopics. This structure helps search engines crawl and index pages more efficiently, as they can identify the relationships between content.

**The importance of semantically related pages:** semantically related pages share a common theme or topic and use similar keywords and phrases. Linking these pages together within a silo creates a strong semantic connection search engines can recognize:

1. **Keyword Relevance:** Grouping semantically related pages reinforces the relevance of your target keywords, helping search engines understand context and meaning and increasing the likelihood of ranking for those keywords.
2. **Internal Linking:** Connecting semantically related pages through internal links helps search engines navigate the site and distributes link equity, boosting the authority of individual pages within the silo.
3. **User Engagement:** When users find relevant, interconnected content within a silo, they are more likely to engage, navigating between related pages, increasing time on site, and reducing bounce rates — positive signals to search engines.

---

# Optimal Internal Linking

**Reminder:** Every page carries the Global Navigation and Global Footer defined at the top of this document. The lists below specify **only the body-content links** unique to each page type. Unless noted otherwise, body-content links should use exact-match anchor text.

## Internal Linking Matrix

Quick-reference adjacency table (body-content links only; every page also carries the global nav + footer). Detailed per-type notes follow below.

> **GBP-linked page rule:** the GBP-linked page receives internal links from the **home page and other high-value pages by rule**, in addition to its normal matrix links — it is the second most important page of the site after the home page (Maps SOP §The GBP Landing Page).

| From (page type) | Links to (body content) |
|---|---|
| Home | Location Pages (each if ≤7; hub if ≥8) · Service Pages (each if ≤7; hub if ≥8) · Contact |
| About Us | Bio Pages · Areas We Serve · Top Level Service Page(s) |
| Contact Us | — (global nav/footer only) |
| Privacy Policy | — (global nav/footer only) |
| Areas We Serve (hub) | Each Location Page |
| Services (hub) | Each Service Page · Contact |
| Top Level Location Page | Neighborhood Pages · Related Local Landing Pages · Contact · Areas We Serve |
| Top Level Service Page | Sub-Services · Contact · Services hub · Related Local Landing Pages |
| Sub-Service Page | Parent Service Page · Contact · Services hub · Related Hyper-Specific Local Landing Pages |
| Neighborhood Page | Parent Location Page · Related Neighborhoods · Related Service |
| Local Landing Page | Parent Location Page · Relevant Service Page · Relevant Sub-Service Page · Contact |
| Hyper-Specific Local Landing Page | Parent Location Page · Relevant Service Page · Relevant Sub-Service Page · Contact |
| Blog Archive | Latest Blog Posts |
| Blog Post | Related Blog Posts (same silo) · Related Service/Sub-Service |

### Home Page
Body content links (same ≤7/≥8 threshold as the nav hub rule):
- Locations: **≤7** → each individual location page · **≥8** → the Areas We Serve hub instead
- Services: **≤7** → each individual service page · **≥8** → the Services hub instead
- Contact Us

### About Us
Body content links:
- Bio Pages
- Areas We Serve Page
- Top Level Service Page(s)

### Contact Us
Body content links:
- (Global nav/footer only — no required body links)

### Privacy Policy
Body content links:
- (Global nav/footer only — no required body links)

### Areas We Serve Page
Body content links (exact-match anchor text):
- Each individual location page

### Each Top Level Location Page
Body content links (exact-match anchor text):
- Neighborhood Pages
- Related Local Landing Pages
- Contact Us
- Areas We Serve Page (if applicable)

### Services Page (hub)
Body content links (exact-match anchor text):
- Each individual service page
- Contact Us

### Each Top Level Service Page
Body content links (exact-match anchor text):
- Sub-services
- Contact Us
- Services Page (if applicable)
- Related Local Landing Pages

### Each Sub-Service Page
Body content links (exact-match anchor text):
- Parent Service Page
- Contact Us
- Services Page (if applicable)
- Related Hyper-Specific Local Landing Pages

### Each Neighborhood Page
Body content links (exact-match anchor text):
- Parent Location Page
- Related Neighborhoods
- Related Service

### Each Local Landing Page
Body content links (exact-match anchor text):
- Parent Location Page
- Relevant Service Page
- Relevant Sub-Service Page
- Contact Us

### Each Hyper-Specific Local Landing Page
Use these pages for sub-services. Body content links:
- Parent Location Page
- Relevant Service Page
- Relevant Sub-Service Page
- Contact Us

### Blog Archive Page
Body content links:
- Latest Blog Posts

### Blog Posts
Body content links:
- Related blog posts in the silo
- Related service or sub-service
