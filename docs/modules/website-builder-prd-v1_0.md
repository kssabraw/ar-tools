<!--
Vendored 2026-08-04 from the owner's Google Doc:
"Website Builder — Module PRD v1.0"
https://docs.google.com/document/d/16eICZ7hIaYlWa3yPLSaB6ye-Yv2OeQaiTK7W9g3eCyU/

The Google Doc is the source of truth. This is a captured copy so the PRD is
readable next to the code it governs and so owner rulings have somewhere durable
to live. The body below is UNMODIFIED; rulings made after capture are recorded
in the amendments block, not edited into the text, so the capture stays faithful
and the drift stays visible. Fold them into the Doc when convenient, then
re-vendor.
-->

# Amendments since capture (owner rulings)

These supersede the sections named. The body text below is unchanged.

| Date | Supersedes | Ruling |
|---|---|---|
| 2026-08-04 | §4.12.3b ("the informational layer is in scope from the first property… neither ships alone") | **No — a lead-gen property's conversion matrix may ship before its informational layer.** The content layer remains the intent, not a launch gate. Consequence: `lead_gen` is no longer blocked behind Fanout, the Blog Writer path and writer #6, so it can ship alongside `local_business` — its remaining divergences are identity/schema suppression (§4.12.2), market-first city discovery (§4.12.3) and the portfolio conflict check (§4.12.4). |
| 2026-08-04 | §4.3, §8.D, Q11 (the "> 40 outbound body links" figure) | **40 is too many.** A lower figure is to be ratified. Pending ratification the advisory stands (§4.3 and Q11 are correct; **§8.D is wrong** — it must not block approval). Two things ratify together: the number *and* what it counts. Recommendation on file: count **body links only**, excluding the SOP-mandated global nav/footer set, with the bar at **25** — the PRD's own §4.8b math puts a 12-service city page at 20+ links before any body copy, so a threshold at or below that fires on every legitimate city page and trains people to ignore it. |
| 2026-08-05 | The 2026-08-04 amendment above; §4.3, §8.D, Q11 | **Ratified at 25**, on the recommendation on file: **body links only**, excluding the global nav/footer set. Being ratified, it now **blocks plan approval until acknowledged** — §8.D's behaviour is correct from this date; §4.3's "advisory that does not block" described the pre-ratification state only. Implemented in `website_plan.LINKS_PER_INDEX_MAX`. |
| 2026-08-06 | Reference note R6's open threshold; the ≥ 2 in the v3.6 capture | **Areas We Serve auto-triggers at ≥ 6 location pages** (owner ruling). R6 left the threshold open between ≥ 2 cities (which v3.5 adopted) and the SOP's looser nav-overflow implication; 6 is a third answer and settles it. **The vendored v3.6 capture still says ≥ 2** — it is a faithful capture, so the ruling lives here until the Doc is revised and re-vendored. Consequence: a 2–5 city site gets location pages and a matrix but **no location hub**, so nothing in the global nav points at the location silo. Those cities stay reachable from the homepage grid, every matrix page's structural links, and the HTML sitemap — §4.1 rule 4 lists Areas We Serve as "where applicable", so a site under the threshold is conformant without one. The threshold lives in `website_plan.AREAS_WE_SERVE_TRIGGER` and `site-template/src/lib/hubs.ts`; both must move together. |
| 2026-08-06 | §4.4 ("a hard stop at plan approval"); §5.2 | **Two rulings.** (1) A plan needing a page type the theme cannot render **blocks approval but is acknowledgeable**, on the same terms as the scale gates — §4.4's three recoveries (drop / re-upload / map) all need the theme compiler and a plan editor, so a bare hard stop would be a wall rather than a gate. Drop `acknowledgeable` when the compiler lands and this becomes §4.4 as written. (2) A local page whose **SEO composite is missing** (scoring failed or never ran) is now **held**, staff-overridable, instead of publishing as though it had cleared 75 — "unscored" and "scored 81" were the same verdict at the gate, which was the one place the threshold could be skipped invisibly. |
| 2026-08-06 | §4.7 (Writer #6 "Gap"), §4.1 rule 4 | **Areas We Serve and the Services index now render without a writer.** Their listing is deterministic — the same published-pages query as structural linking — so the template builds both hubs, conditional on the reference's triggers (≥2 cities; >8 top-level services). Writer #6 still owns their narrative copy and their depth band; what changed is that the plan no longer contains pages that cannot ship. Related: the SOP global nav/footer set (rule 4) is now **derived by the template** from published pages rather than written into config at provisioning time — the previous hardcoded default was four routes that do not exist, i.e. a 404 in the global nav of every page. |
| 2026-08-06 | The doc-relationship list above; §4.1, §4.7 | **Page Type Reference upgraded to v3.6** (`docs/reference/page-type-reference-v3_6.md`, replacing the v3.4 capture). Two changes reach this module. **v3.6** ratifies the link-equity threshold at **25** upstream, on the same terms as the 2026-08-05 ruling below — the two agree, and the reference is now binding rather than advisory. **v3.5** promotes **Areas We Serve** and **Services Index** from optional to **CORE-conditional (auto-triggered)**: Areas We Serve on any multi-city site (≥ 2 location pages), Services Index above 8 top-level services. They are infrastructure the planner includes automatically, not add-ons — and *both are Writer #6 page types with no template*, so §4.7's "load-bearing gap" now blocks a CORE-conditional page type rather than an optional one. Reference R6 flags the Areas We Serve promotion for SOP ratification (≥2 cities vs the SOP's looser nav-overflow reading). |
| 2026-08-05 | §4.3, §8.D (both scale gates) | **Scale gates block *until acknowledged*, which is a sign-off and not a wall.** Both documents say "until acknowledged" but neither describes the mechanism, and without one a site with a legitimately large matrix could never be approved at all — the only way out would be to lie to the planner. `POST /websites/{id}/plan/approve` takes an `acknowledge` list naming the gates being signed off, and the approval record stores what was signed and by whom. **Planning errors are never acknowledgeable** (a reserved-slug collision is wrong, not large, and a published slug is immutable). |

**Consequence for the counter:** the ratified figure counts §4.8b's structural rules, which are not "pages nested under this path". A service page links to **the cities that offer it** — on a 15-city site that is the entire number, and a path-prefix count missed it. `website_plan.links_per_index` implements the §4.8b table directly.

**Still open:** folding the ratified 25 into the **SOP's** link-equity section. (The Page Type Reference did it in v3.6 — that half is done.) The Areas We Serve auto-trigger threshold is settled at 6 (see the 2026-08-06 amendment); what remains upstream is folding it into the reference Doc and the SOP.

**Noted discrepancy in §4.8b:** its worked-example paragraph gives a city page "12 services, 8 nearby cities", but its own table assigns nearby-city links to the *local landing* row, not the city page. The implementation follows the table.

---

# Website Builder — Module PRD v1.0

**Status:** Draft for owner review. Backend slice built and shipped dark behind website\_builder\_enabled; no UI, no content path. **Owner:** Kyle **Last updated:** 2026-08-03 **Relationship to other docs:**

  

  - docs/modules/website-builder-module-plan-v1\_0.md — the engineering spec. Owns architecture, data model, phasing, and the owner's locked infrastructure rulings. **This PRD does not restate or contradict it.**
  - docs/content-quality-prd-v1\_0.md — R1–R7 override this document on content acceptance criteria (per CLAUDE.md, "when docs conflict").
  - docs/suite-architecture-and-roadmap-v1\_0.md — the locked suite decision log; the website is an *additive* publish destination, not a replacement for the Doc path.
  - docs/reference/page-type-reference-v3\_6.md — the Page Type Reference & Site Planning Document (**v3.6**, superseding the v3.4 capture this section was written against; see the amendments block). **Authoritative for which page types exist, their planner triggers, URL patterns, page structure, shared components, and content specs.** §4 below binds this module to it; it is itself subordinate to the AR *Site Architecture, URL Structure, and Internal Linking SOP*. Note v3.4's own scope caveat: its §1.2 conventions are ratified into the reference and its downstream tools, **not** into the SOP document — so this module follows the reference, and the SOP text remains a separate outstanding action.
  - docs/sops/Link\_Building\_Recipe\_Engine.md / Freeze Protocol — the freeze semantics §3.4 extends.

  

**One-line summary.** This document decides who may do what to a website, what pages a site may contain, what a website's lifecycle states mean, what quality a page must clear before it goes live, what the user sees when something breaks, and how we will know the module worked.

  

## 0\. Scope of this document

### 0.1 Division of labour

The plan owns *how it's built*. This PRD owns *what it should do*: users, permissions, lifecycle, quality gates, error surfaces, metrics, acceptance criteria. Several of these are currently being decided implicitly in code — creation and provisioning are gated on staff today, which was an undocumented developer judgment call, not a ruling. This document makes them explicit and overridable.

### 0.2 Settled by the plan — not reopened

Astro + GitHub Actions + Cloudflare Workers static assets (plan §4.2) · one private repo per site under kssabraw (§7) · Namecheap domains, nameservers at Cloudflare (§3) · every site belongs to a client row (§5) · informational sites auto-publish, local-business sites get human plan/page review before first publish (§2) · themes reusable across industries (§4.3) · imagery ladder GBP → uploads → generated, realistic jobsite scenes allowed (§4.7) · Web3Forms with one shared key, CallRail DNI with the real number in JSON-LD (§4.8) · \~50 sites in year one (§11).

### 0.3 What exists today

The pipe from API call to live URL works and deploys an empty site: ar-site-template is published and verified building both site types, and the backend slice (4 tables, resumable provisioning step machine, REST surface, job wiring, 32 tests) is merged with its migration live. Unbuilt: all UI, content generation on the publish path, the theme compiler, imagery, custom-domain attachment, deploy polling to completion, GSC auto-verification. This PRD describes the intended end state; §8 is the checklist for getting there.

  

## 1\. Audience

**The module is internal-only. It produces client-facing artifacts, and — since the** **lead\_gen** **ruling (§4.12) — agency-owned ones. Nothing in it is a client surface.** No client login, no client account, no per-client view of the builder — consistent with the suite (CLAUDE.md: "not a customer-facing SaaS").

  

Two consequences that are easy to get wrong:

  

1.  **Two internal artifacts will leave the building.** The theme preview signed URL and the \*.workers.dev staging URL will be pasted into client emails the day they exist — that is what they are for. They must be presentable and self-contained: no internal jargon, no scores, no other client's name, no AR Tools chrome. Treat them as client-visible even though they are not client surfaces.
2.  **Repos are private and stay private** (plan §7), so drafts never leak; content is public only after a deploy.

  

**\[Assumption\]** No client-facing status page, approval link, or comment flow in v1. If a client must approve a design, a human sends them the preview URL.

  

## 2\. Roles and permissions

Suite roles are admin, staff, and regular user. VAs are regular users who do content production. The governing distinction for this module is **who can create external resources or change what the public sees**.

  

|  |  |  |  |
| :-: | :-: | :-: | :-: |
| \*\*Action\*\* | \*\*Regular user (VA)\*\* | \*\*staff\*\* | \*\*admin\*\* |
| View websites, pages, deploys, checklist | ✅ | ✅ | ✅ |
| Upload a design / compile a theme | ✅ | ✅ | ✅ |
| Approve a theme preview | ❌ | ✅ | ✅ |
| Create a website row (draft) | ❌ | ✅ | ✅ |
| Provision (repo + Cloudflare + first deploy) | ❌ | ✅ | ✅ |
| Build / edit the site plan | ❌ | ✅ | ✅ |
| Generate content into a site | ✅ | ✅ | ✅ |
| Publish a page (commit → live) | ❌ | ✅ | ✅ |
| Retry a failed publish or deploy | ✅ | ✅ | ✅ |
| Edit post-launch settings (GA4, CallRail, GSC) | ❌ | ✅ | ✅ |
| Attach or detach a custom domain | ❌ | ❌ | ✅ |
| Unpublish a live site | ❌ | ❌ | ✅ |
| Soft-delete a website | ❌ | ✅ | ✅ |
| Restore a soft-deleted website | ❌ | ✅ | ✅ |
| Purge (hard-delete row and/or external resources) | ❌ | ❌ | ✅ |
| Apply a new theme version to a live site | ❌ | ✅ | ✅ |
| Roll back to the previous theme version | ❌ | ✅ | ✅ |

  

**Reasoning.** VAs generate and retry — that is their work, and both are idempotent. They do not publish, because publish here means *the public internet*, not a Google Doc; the Fanout's VA cost/review gating assumes a reviewable Doc destination and does not transfer. Provisioning stays at staff (the current de facto rule, now ratified): private repos and undeployed Workers cost nothing and are recoverable, so an admin bottleneck buys little. Domain, unpublish, and purge are admin because each has blast radius outside the site — DNS lives in the owner's single Cloudflare account, and the repo-creating token is account-wide by nature (plan §7).

  

**Enforcement.** Per-action dependencies in routers/websites.py, in the suite's require\_auth / require\_admin style. Denials return 403 with a string error code (requires\_staff, requires\_admin) per the error-envelope convention. Permission is checked at the **route**, and again in the job worker for any job that can be enqueued indirectly, so a scheduled drip can never publish something its originator could not.

  

**\[Assumption\]** Roles are global, not per-client; there is no "this VA is assigned to this client" concept in the suite today and this module does not invent one.

  

## 3\. Site lifecycle

### 3.1 States

The plan's websites.status (draft | compiling | ready\_to\_provision | provisioning | live | error) is the *build* state. Product lifecycle adds three states carried additively, matching the suite's existing soft-delete pattern (local\_seo\_pages.deleted\_at → Drafts tab; assistant\_conversations.archived\_at):

  

|  |  |  |  |  |
| :-: | :-: | :-: | :-: | :-: |
| \*\*Product state\*\* | \*\*How it's represented\*\* | \*\*Site reachable?\*\* | \*\*Content generation\*\* | \*\*Scheduled drip\*\* |
| Active | status='live', no flags | Yes | Yes | Yes |
| Frozen (client) | client has an open client\\\_freezes row | \*\*Yes — unchanged\*\* | No (client\\\_frozen) | Suspended |
| Archived (client) | client archived | \*\*Yes — unchanged\*\* | No | Stopped |
| Unpublished | unpublished\\\_at set | No | Yes (to draft) | Paused |
| Soft-deleted | deleted\\\_at set | Yes, unless unpublished first | No | Stopped |
| Purged | row gone | Depends on the purge options chosen | — | — |

### 3.2 Delete means soft-delete. Purge is a separate, admin-only act.

**"Delete a website" removes the row from the module's lists and nothing else.** The repo, the Worker, the domain, and the live site are untouched. This follows from the plan's first principle — the repo *is* the site — so deleting our record must not destroy the artifact we handed a client. Deleted sites appear in a **Trash** view with Restore, mirroring the Local SEO Drafts tab; restore is a flag clear, nothing is re-provisioned.

  

**Purge** is the escape hatch for genuine mistakes (a test site, a duplicate). admin-only, requires typing the site name, and presents three independently-checked, default-off options:

  

  - delete the GitHub repo,
  - delete the Cloudflare Worker / project,
  - remove the site's DNS records and detach the domain.

  

Purging a site whose domain\_status='active' is **refused** until the domain is detached — the failure mode here is blackholing a client's live domain, and it should take two deliberate acts, not one. Every purge writes an admin audit line and a website\_purged critical notification.

  

**\[Assumption\]** Soft-deleted sites are never auto-purged. A site sitting in Trash for 90 days raises a nag on the Websites list; the decision stays human (see Q8).

### 3.3 Unpublish is real and is not a delete

**Unpublish takes the site off the public internet without touching the repo, the content, or the deploy history.** Mechanically it detaches the custom domain and disables the Worker's public route; the staging URL stays live so the team can still see the site. It is one click to reverse (republish), and it is the correct answer to "client churned", "domain dispute", "we're rebuilding this", and "take it down now".

  

Unpublishing does **not** stop content generation — a paused site can still accumulate drafts. It does pause the scheduled drip, because publishing into a dark site is pointless spend.

### 3.4 Client archived vs client frozen

These are different events and must behave differently.

  

**Client archived** → the site's live presence is unchanged. Archiving is bookkeeping about the *relationship*, not an instruction to take a website off the internet; silently doing so would be a serious failure (the client's phone stops ringing and nobody knows why). The site becomes read-only in the module — no generation, no publish, no drip — and stays visible and hand-deployable from its repo. Archiving a client with live sites raises a confirmation naming them, offering "also unpublish these" as an explicit, unchecked option.

  

**Client frozen** (Freeze Protocol — manual action or deindexing) → per plan §8, all content generation and publish jobs are gated with client\_frozen, the drip is suspended, and the **live site stays exactly as it is**. The module offers no in-app deploy during a freeze; an emergency hotfix is a manual GitHub action outside the module. Provisioning of a *new* site for a frozen client is blocked. The site view carries the same red freeze banner as the workspace. This matches the SOP's rule that a freeze pauses output, not observation — deploy-status polling and GSC ingest keep running.

  

**Freeze lift** does not auto-resume queued work. Jobs that failed client\_frozen are not silently retried; the drip resumes on its next tick, and anything that was mid-batch is re-queued by a human from the batch's retry control. Silent resumption of content output after a manual-action freeze is exactly what the Freeze Protocol exists to prevent.

### 3.5 Domain detach and GSC

Detaching a domain removes the DNS records and the domain binding, leaves the GSC property in place (verification TXT is cheap to keep, and re-attaching later is then instant), and leaves the site reachable at its staging URL. The rank tracker keeps the historical data; a detached site's keywords stop updating rather than being deleted.

  

## 4\. Page inventory — what a site plan may contain

### 4.1 The catalog is the authority

**A site plan is an instance of the Page Type Reference catalog, not a free composition.** The build plan (§4.4) settles where page *instances* come from — Plan Silo for services, geocode-verified neighborhoods and target cities; Keyword Research / Fanout for informational clusters. The catalog decides which **page types** those instances become, and whether a page type may exist on this site at all.

  

Binding rules, taken from the reference's planner instructions (§2):

  

1.  The site's **family** is fixed by site\_type: local\_business → Local Service family, informational → Content & Authority family, lead\_gen → Local Service family **with the identity and schema overrides in §4.12**. A site that is both (a local business with a store) inherits from both.
2.  Every **CORE** entry for the family is planned unconditionally. For a local business that is: homepage, About Us, Contact Us, Privacy Policy, top-level service pages, top-level location pages, local landing pages, blog archive. **Single-city exception (reference §1.2):** a single-city business gets no location pages and **no local-landing matrix** — its service pages geo-target the one city instead. The matrix is CORE only for multi-city businesses, so site\_type alone does not determine the CORE set; city count does.
3.  **No non-CORE page type is planned without a matched trigger**, and the matched trigger is recorded on the plan row. A reviewer must be able to see *why* a page was proposed, not just that it was.
4.  Every template carries the SOP **global nav/footer set** — Home, About Us, Contact Us, Privacy Policy, service pages or Services index, Areas We Serve where applicable, Blog Archive. Campaign / paid landing pages are the only exemption.
5.  Plan output is ordered by the reference's **priority tiers** (reference §7), so review starts at Tier 1.
6.  Every emitted slug is checked against the **reserved root slugs** (reference §1.2) — about-us, services, areas-we-serve, blog, contact-us, privacy-policy, faq, specials, warranty, projects, glossary, bio, compare, lp, reviews, sitemap, search, 404, plus cost at the second level under a service. A collision is surfaced as a planning error, never silently resolved. Precedence when slugs collide: utilities \> services \> cities \> pillars.
7.  **POI pages are excluded from this module** (owner ruling 2026-08-03). The planner never proposes /{city-slug}/{poi-slug}/. POI subject matter is not lost — the **Local Geo Post** (reference §5.3) covers city, neighborhood and landmark content in the blog silo, which is where informational geo content belongs and where it is already SOP-governed. The exclusion also removes one of the three claimants on the second-level city namespace, leaving only local landing and neighborhood pages there.
8.  **Blog posts are planned per cluster with a declared format** (reference §5.3 sub-family): Informational Cluster, Listicle/Roundup, Comparison/Vs, Local Geo, or News/Commentary. Format is a plan-time decision, not a writer-time one, because it changes the geo rule (§5.5), the schema, and whether the post counts toward pillar-cluster math — News/Commentary is non-evergreen and excluded from it.

### 4.2 URL structure

The SOP wins, per the reference's reconciliation note R1. The site-plan generator emits these paths:

  

|  |  |
| :-: | :-: |
| \*\*Page type\*\* | \*\*Path\*\* |
| Top-level service | /{service-slug}/ |
| Sub-service | /{service-slug}/{subservice-slug}/ |
| Top-level location | /{city-slug}/ |
| \*\*Local landing (service × city)\*\* | /{city-slug}/{service-slug}/ — \*\*location first\*\* |
| Neighborhood | /{city-slug}/{neighborhood-slug}/ |
| Hyper-specific local landing | /{city-slug}/{service-slug}/{subservice-slug}/ |
| Hyper-specific (neighborhood) | /{city-slug}/{neighborhood-slug}/{subservice-slug}/ |
| Areas We Serve | /areas-we-serve/ |
| Blog post / archive | /blog/{post-slug}/, /blog/, paginated /blog/page/{n}/ |
| Cost ⭐ | /{service-slug}/cost/ |
| Problem / symptom ⭐ | /blog/{symptom-slug}/ |
| Brand × service ⭐ | /{service-slug}/{brand-slug}/ |
| Projects ⭐ | /projects/, /projects/{project-slug}/ |
| Commercial comparison ⭐ | /compare/{a}-vs-{b}/ |
| FAQ / specials / warranty ⭐ | /faq/, /specials/, /warranty/ |
| Bio | /bio/{person-slug}/ |

  

**Trailing slash on every URL**, and **breadcrumbs follow the URL path, not the link hierarchy** (reference §1.2) — so BreadcrumbList and canonical never disagree. Two consequences the template must implement: the Services index is not a breadcrumb ancestor of /{service-slug}/, and a local landing page's breadcrumb parent is the **city page**, not the service page.

  

**Owner ruling 2026-08-03 — settled.** The plan's pre-ruling text illustrated local routes as /services/\<slug\> and /locations/\<slug\> with no slot for the service × city matrix at all. The SOP structure above governs: no /services/ or /locations/ prefixes, and the location-first /{city-slug}/{service-slug}/ matrix is a first-class page type. Plan §2, §4.6 and the §12 decision log (\#14) are updated to match. The matrix lives in a fifth local\_landing content collection in ar-site-template; sub-service, neighborhood and hyper-specific pages reuse their parent's collection rather than earning their own, and every entry declares its full path in frontmatter so nothing infers a page type from segment count (rulings 2026-08-03, plan §12 \#15–16).

### 4.3 Scale gates at plan review

These are blocking warnings in the plan-review screen, not silent truncations:

  

  - **Matrix count \> 200** (services × cities, brands × services) → human sign-off before the plan can be approved.
  - **Index page outbound body links** → the plan review shows links-per-index for every silo it proposes. The **\> 40 figure is UNRATIFIED** (reference §1.2 — a reference heuristic, not an SOP number), so it renders as an **advisory warning that does not block approval** until a figure is ratified. See Q11.
  - **Hyper-specific local landing pages are escalation-only.** Never bulk-generated; the planner must justify each instance against a competitive or non-ranking target.
  - **Neighborhood pages require the Maps entity test** to pass per neighborhood — a knowledge panel with description and associated entities. The Plan Silo geocode check establishes containment, not entity status; both must pass.
  - **Slug collisions** against the reserved list or between two entries claiming one path → blocking planning error with the conflicting pair named.
  - **⭐ extension page types** now carry **ratified URL patterns** (reference §1.2, v3.4). Ratification reserves the path; it is not a commitment to build. Two things remain open upstream: the SOP body text still lacks the type definitions, and no writer exists for most of them (§4.7).

### 4.4 One template per page type, and the design must cover them

A site needs one template per page type it uses, not per page instance. The compiler keys off which sc-if branches a design actually contains (plan §4.3), so **a plan requiring a page type the approved theme has no template for is a hard stop at plan approval**, with three recoveries offered: drop those page types, add the screen in Claude Design and re-upload, or explicitly map the type onto an existing template. Silently rendering a cost page through the blog-post template is the failure this prevents.

### 4.5 The theme's slot vocabulary is the Shared Component Library

Theme section components use the reference's §4 component names — HeroAnswer, ComparisonTable, PriceRangeTable, FAQAccordion, StepList, TrustBadgeRow, LocationCardGrid, and the rest — with each component's specified mobile behaviour. This is what makes the locked "themes reusable across industries" ruling true in practice: a page type composes from named components, so any approved theme can render any page type whose components it has. A theme missing a component a planned page type needs is reported at **theme approval**, not discovered at publish.

### 4.6 Content specs are the editorial brief

Each catalog entry's **Content spec** — angle, voice, must-cover, depth — is passed to the generating engine as the brief baseline. It is angle-level guidance, not a script, and the client's brand guide and voice card still win on voice. Depth targets bound length; must-cover items are coverage requirements; the entry's Pitfalls are negative checks. Several are deterministic enough to gate publishing — see §5.5.

### 4.7 Generation coverage — which page types can actually be written

The catalog defines \~25 page types across the two families this module ships. The suite's engines cover a subset. **The plan tab must not propose a page type without showing its engine status**, or it will promise pages nothing can produce.

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*Page type\*\* | \*\*Engine\*\* | \*\*Status\*\* |
| Top-level service, top-level location | nlp-api | \*\*Built\*\* |
| Local landing (matrix) | nlp-api matrix engine | \*\*Built\*\* |
| Informational cluster post | Blog Writer | \*\*Built\*\* |
| Privacy policy, blog archive | Template, no LLM | \*\*Built\*\* |
| Home, About Us, Contact Us | Core-pages generator | Specified, Phase 3 |
| Sub-service, neighborhood, hyper-specific | nlp-api variants | \*\*Assumed — unconfirmed\*\* |
| Listicle/roundup, Comparison/Vs, Local Geo posts | Blog Writer, format-aware | \*\*Assumed — unconfirmed\*\* |
| News/Commentary post | n8n curator workflow | Exists outside the module |
| \*\*Areas We Serve, Services index, pillar pages, project/blog archives\*\* | \*\*Writer \\\#6 (hub/index)\*\* | \*\*Gap — see Q14\*\* |
| Cost ⭐ | Writer \\\#7 | Gap |
| Problem / symptom ⭐ | Writer \\\#8 | Gap |
| Standalone FAQ ⭐ | Writer \\\#4 | Gap |
| Comparison (commercial) ⭐ | Writer \\\#1 | Gap |
| Brand × service ⭐ | Writer \\\#5 | Gap |
| Glossary, statistics, original research | Writers \\\#3, \\\#13 | Gap |
| Bio, projects/case studies, offers, warranty, testimonials | \*\*None — by design\*\* | Intake, not generation |

  

Three things follow:

  

1.  **Writer \#6 is the load-bearing gap.** One archetype unlocks five page types across both site shapes. Areas We Serve and the Services index trigger whenever the nav overflows, which at multi-service × multi-city scale is most sites; pillar pages trigger at ≥5 posts in a cluster, which Fanout produces by construction. Today an informational site ships posts and an archive with no pillar above them.
2.  **The "assumed" rows need confirming before the plan tab promises them.** The catalog describes these as variants of engines that exist; whether nlp-api and the Blog Writer accept the page-type and format parameters is unverified.
3.  **The last row is not a gap.** Bio, projects, offers, warranty and testimonials all require real credentials, real job data, or legally-reviewed terms, and §5.6 makes fabricating any of it a hard block with no override. These are **intake-form page types**: the module should collect the facts and render them, never write them. The create wizard has no such intake step today.

### 4.8 Slug immutability and redirects

**Published slugs are immutable** (reference §1.2). When a service is renamed or a city dropped, the old path stays as a **301 to its replacement**, or to the nearest surviving parent if there is none. A live slug is never silently changed.

  

This is a new module requirement with no home yet, and it has consequences the build plan does not currently cover:

  

  - website\_pages needs to retain superseded routes rather than overwriting route, so the redirect source survives the rename.
  - The repo needs a generated redirect artifact (an Astro/Cloudflare \_redirects file is the obvious candidate) committed on the same deploy as the rename, so the redirect ships atomically with the change that caused it.
  - Renaming is therefore a **publish-path action**, not a settings edit — it produces a commit.

  

Flagged as Q13; nothing is built for it today.

### 4.8b Internal linking

**Structural links are rendered by the template; editorial links are chosen by the writer from a supplied list. Neither ever invents a URL.**

#### Structural — deterministic, from frontmatter

Most internal linking on these sites is dictated by the SOP rather than by editorial judgment, and every page already carries the data needed to derive it. The template renders these; no model is involved and no generation call is made:

  

|  |  |
| :-: | :-: |
| \*\*Page type\*\* | \*\*Renders links to\*\* |
| Local landing (/{city}/{service}/) | Breadcrumb to its city; its service page; sibling services in the same city; the same service in nearby cities |
| City page | Its services; its neighborhoods; the Areas We Serve page where one exists |
| Service page | Its sub-services; the cities where the service is offered |
| Pillar | Every published post in its cluster |
| Cluster post | Its pillar; sibling posts in the cluster |
| Every page | Global nav and footer set (§4.1 rule 4) |

  

Three properties follow, and they are why this is the cheap option:

  

1.  **Always correct.** A link derived from city\_slug + service\_slug cannot point at a page that was never planned.
2.  **Self-healing.** Publish a new page and every page that should link to it picks it up on the next deploy, with no regeneration.
3.  **The held-page problem disappears.** These queries return **published** entries only, so a page held by a quality gate is simply absent from the lists rather than linked and broken. When it later publishes, its inbound links appear on the next deploy. No build-time link resolver is required.

#### Editorial — model chooses relevance, system supplies the URL

Contextual body links — a blog post linking to a relevant service page, a symptom page linking to the service that fixes it — are genuinely editorial and are the one place a model adds value. The constraint that makes them reliable:

  

**The writer receives a list of eligible published targets for the silo (slug, title, page type) and may only link to entries on that list.** It selects relevance; it never composes a URL. This is the same rule as affiliate links (§4.15.4) and for the same reason: a generated URL is either wrong or hallucinated, and a broken internal link is a broken internal link whether an LLM or a human typed it.

  

A link in generated copy that does not resolve to a published page on the eligible list is **stripped at publish**, leaving the text intact. That is a degradation, not a failure, and it is logged.

#### Link volume is counted from the structural rules

Because structural linking is deterministic, its volume is calculable before anything is generated. A city page with 12 services, 8 nearby cities and the global nav carries 20+ links before a word of body copy. **This is the number the plan tab's links-per-index advisory (§4.3) counts**, and it is available at plan time precisely because the rules produce it.

### 4.8c Sitemaps and the 404 page

Three additions to the CORE set for every site type. All are template-rendered, none involve a model.

  

**XML sitemap** (/sitemap-index.xml) — already in the template's SEO plumbing. Published pages only, regenerated on every build, referenced from robots.txt. **Indexing itself is handled through GSC**, not by the module; no submission API, no crawl requests.

  

**HTML sitemap** (/sitemap/) — a human- and crawler-readable index of every published page, grouped by silo: services with their sub-services, cities with their local landing pages and neighborhoods, blog silos with their clusters. Rendered from the same published-pages query as structural linking (§4.8b), so it self-heals and never lists a held page.

  

Two notes on it: sitemap joins the reserved root slugs in §4.1 rule 6, and the HTML sitemap is a page type **not present in the Page Type Reference catalog** — it is an addition this module makes, and worth feeding back for ratification.

  

**404 page** with a **search bar**, plus links to the homepage, the top-level services or silos, and the HTML sitemap. The search is client-side over a build-time index (Pagefind or equivalent) — these are static sites with no server to query, so search is an index committed with the build, not a runtime service. A 404 that offers a dead end is the one page guaranteed to be seen by someone who already failed to find what they wanted.

  

404 and search join the reserved root slugs.

  

**Out of scope, by ruling:** post-launch performance triage (what happens to a property that produces nothing after nine months) and revenue attribution per page or per slot. Both belong to other modules.

### 4.9 Inputs: what the module must be given, with or without a GBP

**A site must build completely for a business with no GBP, no reviews, no address, and no photos.** The plan settles the mechanism — manual entry \> GBP \> absent, per-field provenance, a later GBP sync fills gaps but never overwrites a human's entry (plan §4.5). Site-before-GBP is the *expected* order for a LeadOff market entry, not an edge case, since GBP verification goes smoother pointing at a live site.

  

The product consequence the plan doesn't state: **GBP is a pre-fill for one slice of the intake, not the intake.** Most of what CORE pages need was never in GBP to begin with.

  

|  |  |
| :-: | :-: |
| \*\*GBP supplies\*\* | \*\*GBP cannot supply\*\* |
| Name, address, phone, hours | \*\*Billable service catalog\*\* (categories ≠ services) |
| Primary/secondary categories | Founding story, mission, USP, years in business |
| Reviews, rating | Licences, insurance, certifications, associations |
| Service areas | Warranty and guarantee terms |
| Photos | Differentiators, leadership names and credentials |

  

So the business-facts step runs on **every** site. With a GBP it opens partly filled; without one it opens empty. Same step, same required fields.

  

**Minimum viable input set** — no fallback exists for these, and the wizard cannot complete without them:

  

|  |  |
| :-: | :-: |
| \*\*Required\*\* | \*\*Why it has no fallback\*\* |
| Business name | Brand-optimized homepage H1, JSON-LD, every template |
| Phone | Primary conversion path; CallRail DNI needs a real number underneath |
| At least one city | Determines single-city vs multi-city, which decides the whole CORE set (§4.1) |
| \*\*Service catalog\*\* | \*\*Plan Silo consumes a service list; it does not invent one.\*\* No services means no service pages, no matrix, no nav — no site. This is the one input with no degradation path. |

  

Everything else degrades to a defined outcome rather than blocking:

  

|  |  |
| :-: | :-: |
| \*\*Absent\*\* | \*\*Result\*\* |
| Address (service-area business) | No address in NAP or JSON-LD; coverage stated as service areas |
| Reviews | Testimonial and rating components render nothing (§5.6 — never fabricated) |
| Photos | Imagery ladder falls through to generated for hero/service/jobsite slots only |
| Hours | Hours block and the hours property omitted |
| Licences, certifications | TrustBadgeRow renders nothing — a hard block, not a quality choice (§5.3) |
| Founding story, USP | About Us cannot be generated to spec; held rather than filled with platitudes |
| Leadership credentials | No Bio pages planned (non-CORE, trigger unmatched) |

  

Two of those rows are worth stating plainly: a site with no trust facts and no founding story **ships without a TrustBadgeRow and with a held About page**. That is correct behaviour under the fabrication rule, but it is a visibly incomplete site, and it is the default outcome for a brand-new business unless someone types the facts in. The launch checklist must surface both.

### 4.10 Business facts intake (owner ruling 2026-08-03 — build it)

The user enters every fact the module needs. GBP pre-fills what it can; nothing is ever required to come from GBP.

  

**Facts live on the client, not the website.** The service catalog, founding story, licences and credentials describe the *business*, not a particular site — a client with two sites types them once, and the existing content engines benefit from the same block. Only delivery settings (domain, form recipient, CallRail, GA4) are site-level.

  

**Two entry points, one dataset.** The wizard enforces the required set and blocks; everything else is editable at any time from a **Business Facts** surface on the client. A client will not have warranty terms to hand on day one, and blocking a site launch on that would be wrong. Filling a field later re-enables the pages it unlocks, and the launch checklist shows what is still missing.

  

|  |  |  |  |
| :-: | :-: | :-: | :-: |
| \*\*Group\*\* | \*\*Fields\*\* | \*\*What it unlocks\*\* | \*\*If absent\*\* |
| \*\*Required — wizard blocks\*\* | Business name · phone · one or more cities · \*\*service catalog\*\* (per service: name, short description, sub-service flag) | The entire plan: nav, service pages, location pages, the matrix, JSON-LD | Wizard cannot complete |
| \*\*CORE-page facts\*\* | Founding story with specifics (dates, turning points) · mission · USP · 2–3 differentiators · years in business | About Us; homepage why-us section | About Us held (§5.3); homepage section omitted |
|   | Licences, insurance, certifications — each with issuing body and number · associations | TrustBadgeRow everywhere it appears | Renders nothing — hard block, no override |
|   | Address (optional for service-area businesses) · hours · service areas · email · social links | NAP block, Contact page, LocalBusiness JSON-LD | Field-by-field omission; no empty shells |
| \*\*Optional page types\*\* | Leadership names, titles, credentials | Bio pages | Not planned (trigger unmatched) |
|   | Warranty and guarantee terms | Warranty page | Not planned |
|   | Offers with value, terms, expiry | Specials page | Not planned; expired offers flagged |
|   | Job data, photos, client permission | Projects / case studies, GalleryBeforeAfter | Not planned; component renders nothing |
|   | Testimonials with attribution and permission | TestimonialCard | Renders nothing — never fabricated |

  

**The service catalog is user-entered** (owner ruling 2026-08-03). GBP categories may *suggest* entries but are never imported as services — a category is a taxonomy label, a service is a billable job, and wiring one into the other would silently produce the wrong page inventory. Per entry:

  

|  |  |
| :-: | :-: |
| \*\*Field\*\* | \*\*Notes\*\* |
| Service name | The billable job, in the client's own words |
| Slug | Derived from the name, editable \*\*before first publish only\*\* — immutable after (§4.8) |
| Short description | 1–2 sentences; feeds the nav, ServiceCardGrid, and the Services index |
| Sub-service of | Optional parent. A sub-service must be a genuinely different keyword vector than its parent, or it cannibalizes it — the form warns, it cannot verify |
| Include in local-landing matrix | Per-service, default on. This is the pruning control the catalog requires for thin cells: a minor service crossed with every city is how a matrix doubles for no return |
| Nav order | Determines nav order and whether a Services index is triggered (\\\>\\\~8) |

  

Two checks run at entry, not at plan time, so the user can fix them while they are still cheap:

  

  - **Reserved-slug and collision check** (§4.1 rule 6) — a service slug clashing with a reserved root slug, a city, or another service is caught as it is typed.
  - **Live matrix projection.** As services and cities are entered, the form shows the resulting page count and links-per-index. The \>200 review threshold and the link-equity warning become visible *before* anything is planned, which is the only point at which trimming the catalog is easy.

  

**Rules the form enforces:**

  

  - **Per-field provenance.** Every field records manual or GBP. A later GBP sync fills empty fields and never overwrites a manual entry (plan §4.5). The form shows which source each value came from.
  - **Credential fields are facts, not prose.** Licence and certification entries are structured (type, issuing body, number, expiry where applicable) because §5.3 checks generated copy against them. A free-text "we're licensed and insured" field would defeat the check.
  - **Every optional field states what it unlocks**, so the user can see that typing warranty terms produces a warranty page rather than filling a box for its own sake.
  - **Nothing in the form is required to publish** beyond the wizard's four. Absence produces omission, never an empty shell or an invented fact.

### 4.11 Editorial context: brand voice, ICP, competitors

Brand voice, ICP, and competitors are **existing client-level suite assets** with existing consumers. The module reads them, and — owner ruling 2026-08-03 — also lets the user enter and edit them from the Business Facts surface, so a site can be set up without leaving the module.

  

**One dataset, two entry points.** The module writes to the **same client fields the dashboard edits**. It never keeps a module-local copy of a voice card or ICP. A second store would drift, and the failure would be silent and slow: the Website Builder writing in one voice while the Blog Writer writes the same client in another.

  

|  |  |  |  |
| :-: | :-: | :-: | :-: |
| \*\*Asset\*\* | \*\*Where it lives\*\* | \*\*Entered\*\* | \*\*What the module uses it for\*\* |
| Brand voice / voice card | Client record | Dashboard \*\*or\*\* Business Facts | Every generated page; assert\\\_voice\\\_publishable at publish (§5.2) |
| ICP | Client record | Dashboard \*\*or\*\* Business Facts | Angle and audience framing on service, location and core pages |
| Differentiators, USP | Client record | Business Facts (§4.10) | Homepage why-us, About Us, service pages |
| Competitors | client\\\_competitors | Dashboard \*\*or\*\* Business Facts; LeadOff seeds them | nlp-api's competitor SERP analysis on local pages |

  

**Generation is gated on brand voice being present; site creation is not.** A site can be created, themed and provisioned with no voice card — none of that writes copy. The moment content generation is requested, a missing voice card blocks with content\_no\_brand\_context rather than proceeding.

  

This is a stronger stance than the suite takes for a single article, and deliberately so. The suite has already shipped one article written with zero brand context; the same failure on a website writes *every page* that way, and on an informational site nobody reads them before the public does. §5.4 already refuses to auto-publish a -degraded run — this is the same rule moved upstream, so the degraded run never happens instead of being caught afterward.

  

**Three ways to satisfy the gate**, in precedence order — the user picks, nothing is silent:

  

1.  **Already on the client.** An established client has a voice card; the module uses it and shows which one.
2.  **Typed in.** The user writes or pastes the voice card and ICP directly in Business Facts.
3.  **Derived draft.** For a brand-new business — a LeadOff market entry has no voice card for the same reason it has no GBP — the module offers to draft one from the §4.10 intake (USP, differentiators, service catalog, cities, vertical). **A derived draft must be reviewed and approved before it unlocks generation.** If the module could auto-fill its own gate, the gate would do nothing.

  

A derived voice card is marked as derived on the client record, so the next person to read it knows it was machine-drafted rather than client-supplied.

### 4.12 Lead-generation properties (lead\_gen)

Owner ruling 2026-08-03: the module also builds **agency-owned lead-generation properties** — an invented brand, targeting a vertical in a geography, whose leads are sold or brokered per-lead. Some are later assigned to a client; some are not. This is a **third site type, not a variant of** **local\_business**, because it shares the geo silo and the service × city matrix but differs on identity, schema, facts, and metrics.

#### 4.12.1 Client rows carry a kind

Every site still belongs to a client row (locked ruling), but a lead-gen property is not a client. The row gains a **kind —** **client** **or** **owned\_property** — so the suite can tell them apart without a second table. Client-scoped surfaces keep working unchanged; reporting, the client picker and LeadOff dup checks filter owned properties out by default. A property later assigned to a client flips kind; the site, repo and history are untouched.

  

**The wizard creates the row; it is not a prerequisite.** For a client site the client already exists and is selected. For a lead\_gen property **there is no business to select** — the brand is invented in the wizard, so the wizard creates the owned\_property row from the chosen market and brand name as its first act. Requiring someone to pre-create a placeholder client would be asking them to model a business that does not exist.

  

**Owned properties have no client workspace.** The Business Facts surface (§4.10, §4.11) hangs off the **property row**, reached from the sidebar Websites index rather than from a client workspace, and shows only the field groups that apply (§4.12.5). Everything else about the surface is identical.

#### 4.12.2 Identity: an honest matching service, never a fake business

There is no business behind the brand, so:

  

|  |  |
| :-: | :-: |
| \*\*Rule\*\* | \*\*Consequence\*\* |
| \*\*No\*\* \*\*LocalBusiness\*\* \*\*or\*\* \*\*Service\*\* \*\*JSON-LD\*\* | WebSite and BreadcrumbList only. Emitting business schema for a business that does not exist is misrepresentation, not a style choice |
| \*\*No NAP block, address, or hours\*\* | Nothing to state; the Contact page is a form and a routing promise |
| \*\*No TrustBadgeRow, testimonials, reviews, team, or before-after\*\* | No licences, no jobs, no people. §5.6 applies unchanged and is not relaxed here |
| \*\*No first-person contractor voice\*\* | Copy is "find a plumber in Anaheim," not "we're your plumber in Anaheim" |
| \*\*About page states what the site actually is\*\* | A matching service, how it makes money, and that quotes come from independent local providers |
| \*\*Form and privacy policy disclose lead sale\*\* | Consent language on the form; the privacy policy states submissions are sold or shared. The privacy template's "legal-reviewed text" no longer covers this |

  

The honest-directory framing is not decoration: a site that presents as a matching service and genuinely helps someone find a provider is doing what it says. One that presents as a contractor who does not exist is a doorway page at any page count.

#### 4.12.3 Market-first create path

A client site starts with a business and asks what areas it serves. A lead-gen property starts with a **market** — the cities are an input, not a fact about anyone.

  

1.  **Vertical + seed city.** From the GBP market opportunity scorer or LeadOff, or typed.
2.  **Scope: single-city or multi-city** — the user's choice.
3.  **Single-city** → no location pages and no matrix; service pages geo-target the one city (§4.1 rule 2, same rule as a single-city business).
4.  **Multi-city** → census places within a **10-mile radius of the seed city centroid** (default, editable per site), ranked by population, **capped at 20** with the remainder addable by hand.
5.  **Drop any candidate without a valid DataForSEO location** — a city that cannot be rank-tracked or researched later is a bad city page regardless of anything else. Free and deterministic.
6.  **User reviews and edits the list**, showing distance from seed, population, and census place type per candidate. This is the only real filter — keyword volume is deliberately not checked (owner ruling), so the review step is what keeps administrative artifacts (CDPs, unincorporated communities) out of the plan.
7.  **Neighborhoods per surviving city**, Maps entity test applied as normal.
8.  **Matrix projection** (§4.10) and the §4.12.4 conflict check, then Plan Silo unchanged.

  

**Cities produce matrix cells; neighborhoods do not.** A neighborhood produces a location-variant page at /{city}/{neighborhood}/ under its city. Neighborhood × service is the hyper-specific third level, which stays escalation-only. Without this line, 15 cities × 4 neighborhoods × 10 services is 600 pages instead of 150.

  

City discovery costs nothing — census data and the DataForSEO locations lookup are both free — so it runs on selection rather than behind a cost gate.

#### 4.12.3b Content: two pipelines, one property

A lead-gen property runs **both** content pipelines (owner ruling 2026-08-03). The matrix converts; the informational layer is what earns the rankings and the trust that make the matrix worth anything.

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*Layer\*\* | \*\*Engines\*\* | \*\*Produces\*\* |
| \*\*Conversion\*\* | Plan Silo → nlp-api | Service pages, city pages, the /{city}/{service}/ matrix |
| \*\*Informational\*\* | Fanout → Blog Writer, scheduled per §4.15.1b | Cost guides, symptom/problem content, comparisons, how-to and buying content in the blog silo |

  

The informational layer is **in scope from the first property**, not a later addition. A matrix with nothing behind it is a set of conversion pages with no reason to rank and no reason to trust; the content layer is what a property has instead of a licence and twenty years in business.

  

**This makes writers \#7 and \#8 matter more here than anywhere else.** Cost pages and problem/symptom pages are the highest-intent informational content in a trade vertical, they are exactly what a matching service should be good at, and neither has a writer (§4.7). On a client site their absence costs some coverage; on a lead-gen property it removes the layer the whole model rests on.

  

**Perspective, not just tone.** Every page nlp-api writes for a local business is framed as *we do this here*. A lead-gen property cannot say "we" — there is no crew, no truck, no licence (§4.12.2). The same page type has to be written as *here is what this job involves in this city, here is what it typically costs, here is how to judge a quote* and then route to providers. That is the perspective the page is written from, not an adjustment at the edges.

  

Two consequences:

  

  - **Content specs differ by perspective.** A client's service page leans on stored facts — years in business, licence, response window. A property has none of those and may not invent them, so its pages must be substantive on the job itself: what it involves, what drives the price, what varies locally, what separates a good quote from a bad one.
  - **How the perspective is implemented is unverified.** Either nlp-api takes a **perspective parameter** (provider | directory) and its prompts branch on it, or it is perspective-agnostic enough to follow a different brief supplied by the module. This lands on the same code as the four assumed engine rows in §4.7 and should be checked in the same pass. Marked as an assumption, not a fact.

#### 4.12.4 Portfolio conflict check

Client sites never overlapped; each client had its own footprint. Owned properties break that twice, so **before a** **lead\_gen** **plan can be approved, every other site in the suite is scanned for overlapping service × city cells**:

  

  - **Property vs property** — two owned sites competing for the same cells split their own results.
  - **Property vs client** — a lead-gen plumber site in Anaheim while a plumber client is served in Anaheim means competing with a client for their keywords, on the agency's own infrastructure. That is a relationship failure, not an SEO one, and it surfaces at renewal rather than at launch.

  

Collisions are surfaced with the conflicting site named and the overlapping cells listed. A property-vs-client collision requires an explicit admin override to proceed; property-vs-property is a warning.

#### 4.12.5 Facts and metrics differ

The §4.10 required set assumes a real business. For lead\_gen it becomes:

  

|  |  |
| :-: | :-: |
| \*\*§4.10 group\*\* | \*\*On an owned property\*\* |
| Brand name | Required — \*\*invented in the wizard\*\*, not looked up |
| Service catalog | Required, unchanged |
| Phone | Required, but it is an \*\*agency-owned CallRail tracking number\*\*; there is no business line underneath it |
| Cities | \*\*Not typed\*\* — produced by §4.12.3 discovery and review |
| Founding story, mission, USP, years in business | \*\*Not applicable.\*\* Hidden from the form, absent from the checklist |
| Licences, insurance, certifications, associations | \*\*Not applicable.\*\* Hidden and absent |
| Address, hours | \*\*Not applicable\*\* (§4.12.2 forbids them) |
| Brand voice, ICP | Required for generation as normal; always derived or typed, never inherited from a business (§4.11) |

  

The distinction between *not applicable* and *missing* is the point. On a client site an empty founding story is an incomplete site the launch checklist nags about. On an owned property there is no business to have a history, so the form should not ask and the checklist should not flag — otherwise every property ships permanently red.

  

Metrics invert. §7's time-to-live and sites-per-month measure delivery throughput, which is the wrong question for an owned asset. For lead\_gen the primary metrics are **leads per site per month, cost per lead, and payback period against build cost**. This makes the Web3Forms webhook (§7 metric 5, plan §4.8 follow-up) a **prerequisite rather than a deferred nice-to-have** — without it there is no lead attribution and no way to value the property.

  

Lead-gen properties carry monetization = leads (§4.15.4); the field is orthogonal to site type, so an owned property could in principle carry leads alongside ads.

  

**Lead handling is out of scope for this module.** Selling per-lead needs lead records, buyer management, pricing, dedup, routing and disposition — a marketplace, not a website builder. This module's responsibility ends at **emitting a lead event with attribution** (source site, service, city, timestamp, contact) from Web3Forms and CallRail. The marketplace is a separate module; see Q17.

### 4.13 Imagery

The ladder is settled by the plan (§4.7): **GBP photos \> uploads \> generated**, generation defaulting to Gemini/Nano Banana with OpenAI as alternative, realistic jobsite scenes allowed, and the design's labelled placeholders doubling as prompt seeds since a Claude Design export ships zero images. What follows is the product behaviour around it.

#### 4.13.1 A per-site image spec, locked at theme approval

Fifty images generated independently from independent placeholder strings produce fifty images that do not belong to the same website. Every site therefore carries an **image spec**, derived at theme approval and reused on every generation call:

  

|  |  |
| :-: | :-: |
| \*\*Field\*\* | \*\*Source\*\* |
| Palette and colour temperature | Theme tokens |
| Medium — photographic, illustrated, mixed | Design export; the compiler infers, the user confirms |
| Lighting and time of day | Default per vertical, editable |
| Framing and camera distance conventions | Default, editable |
| People: present or absent | Site type + user choice (§4.13.4) |

  

The spec is versioned with the theme. Applying a new theme version offers regeneration of imagery against the new spec; it never regenerates silently, since that would rewrite the look of a live site on a styling change.

#### 4.13.2 Generation runs at plan approval, not at publish

Imagery is batched for the whole site when the plan is approved, so slots are filled before the first publish rather than discovered empty at it. Per-slot regeneration and upload-instead remain available at any time from the Pages tab.

  

Batches show cost before dispatch, per the §4.10 pattern. A slot that fails generation retains its placeholder, does not block the page from publishing, and is flagged on the launch checklist (§6.3).

#### 4.13.3 Alt text is generated with the image, and is subject to the facts gate

Every generated or uploaded image carries alt text, produced from the placeholder label plus the page's context. It is an accessibility requirement and an on-page signal — and it is also a **claim surface**: alt text reading "our technician installing a condenser" asserts staff and work history exactly as body copy would. Alt text is checked against stored facts under §5.3, and a facts-consistency failure in alt text is a hard block on the same terms as one in prose.

#### 4.13.4 People in images

Realistic jobsite scenes are permitted (locked ruling), but a scene containing workers implies staff:

  

|  |  |
| :-: | :-: |
| \*\*Site type\*\* | \*\*Rule\*\* |
| local\\\_business | People permitted in jobsite and service scenes. Never in a way that implies a specific named person, and never as a team portrait or headshot — those remain §5.6 fabrication territory |
| lead\\\_gen | \*\*No identifiable people.\*\* There are no staff behind an invented brand, so a crew in a hero image is the same misrepresentation §4.12.2 blocks in copy and schema. Imagery is equipment, work, materials and place |
| informational | Subject-appropriate; no implied authorship or team |

#### 4.13.5 Images are unique per site and committed to the repo

**No shared image library across sites.** Two clients running the same generated jobsite scene is a poor look and a visible footprint across the portfolio; the rule holds for owned properties too. Images are generated per site even where the vertical and prompt would be near-identical.

  

Generated assets are **committed to the site's repo** alongside the content that references them, not served from external storage. This follows the plan's first principle: the repo is the site, and a site whose imagery lives somewhere the agency controls separately does not keep shipping if the suite disappears.

### 4.14 Theme sources — one now, two later

A site's theme carries a **theme\_source**, and v1 supports exactly one value.

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*Source\*\* | \*\*Status\*\* | \*\*Path\*\* |
| design\\\_import | \*\*v1 — the only supported path\*\* | Claude Design export → compiler → Astro theme |
| generated | \*\*Future\*\* | Model generates the Astro component set and tokens.json directly against the template contract |
| house | \*\*Falls out of v1 for free\*\* | A previously approved theme reused on a new site (themes are reusable across industries — locked ruling) |

  

**v1 is Claude Design (owner ruling 2026-08-03).** It keeps a human at a visual canvas, which is what lets someone who is not an engineer iterate on a design before it becomes a site, and it is the path the compiler is already being built for.

  

**Why** **generated** **is worth carrying as future work rather than dropping.** A spike (theme-spike-copperline.html, 2026-08-03) produced a two-page-type HVAC theme — homepage and /anaheim/ac-repair/ — of usable quality in a single pass. The interesting property is not the output but what it skips: generating Astro and tokens directly removes the DSL translation entirely, and the compiler is the hardest unbuilt piece in the plan and the one every downstream phase is blocked behind. If the compiler proves expensive or fragile, generated is the escape hatch, and it is cheaper to build than the compiler is to finish.

  

Three things follow for v1, so the option stays open at no cost:

  

1.  theme\_source exists on the theme record from the first migration, even with one legal value. Retrofitting it later means touching every theme row.
2.  The **theme contract is the boundary**, not the compiler. Whatever produces a theme must satisfy the same contract: Shared Component Library names (§4.5), tokens.json, one template per page type (§4.4), the §4.13.1 image spec. The compiler is one producer of that contract, not the definition of it.
3.  Nothing downstream of theme approval may assume a design import ever existed.

  

**Deliberately not decided:** whether generated ships at all. It is a hedge, not a plan, and it needs no ruling until the compiler is either finished or in trouble.

### 4.15 Informational properties (informational)

Agency-owned content sites monetised by **display advertising and affiliate links** (owner ruling 2026-08-03). Some are built for clients; standalone ones are owned assets.

#### 4.15.1 Row, creation, and topic scope

Standalone informational sites are owned\_property, not clients — the plan's "lightweight client" was the workaround that predates the kind field (§4.12.1). The wizard creates the row; Business Facts hangs off the property row.

  

**Topic scope replaces the service catalog** as the required no-fallback input. Fanout's silo structure is what the page inventory derives from, exactly as the service catalog is for a local site: no silos, no pages, no site. Discovery and review work the same way — the user reviews and edits the proposed silo and cluster set before it is committed.

#### 4.15.1b The schedule: Fanout plans it, the scheduler supplements it

**Fanout produces the plan, not just the topic scope.** Silo → clusters → posts is already the right publication order, so the fan-out output *is* the content schedule rather than an input to one. An informational site's plan tab is therefore a schedule view: cluster order, post order within cluster, pillar placement, and origin.

  

Three rules govern it:

  

1.  **Pillars publish after their cluster, never before.** A pillar triggers at ≥5 posts in a cluster; a hub that links to nothing is a thin page on the day it ships. The schedule interleaves — cluster posts, then that cluster's pillar, then the next cluster. This puts **writer \#6 (§4.7) on the critical path for the first informational site**, not on a catch-up list.
2.  **Approval binds order, not dates.** Dates float against a declared cadence (e.g. three posts a week). A generation failure, a freeze, or a held post then shifts the queue rather than orphaning everything downstream of it. Absolute dates are more useful and more brittle; order survives contact with reality.
3.  **Every page declares its silo and cluster**, whatever produced it (see below).

  

**The content scheduler is the supplemental lane.** Pages the fan-out did not produce — news and timely posts no keyword fan-out would surface, gaps found after launch from GSC queries with impressions and no page, commercial pages the fan-out skips (comparisons, roundups, affiliate-bearing content), seasonal one-offs — are added through the existing scheduler rather than a second mechanism inside this module.

  

|  |  |  |
| :-: | :-: | :-: |
|   | \*\*Fanout\*\* | \*\*Content scheduler\*\* |
| Produces | The structural plan: silos, clusters, pillars | Individual supplemental pages |
| When | At site creation, and on re-runs | Any time, including years post-launch |
| Cost gating | Fanout's own wizard cap | The scheduler's existing estimate and spend gate |

  

Both land in **one queue and one plan-tab view**, distinguished by a provenance field on the page row (fanout or supplemental). Months later, "did the fan-out propose this or did someone add it" is a question worth being able to answer, and recording it now is free.

  

**A supplemental page declares its silo and cluster at creation, or explicitly declares itself standalone.** Without that, internal linking degrades quietly — orphans nothing links to, or clusters whose pillar does not know about a member. Two consequences follow: a supplement that pushes a cluster to five posts **triggers its pillar exactly as a fan-out post would**, and a supplement that pushes a hub past the links-per-index advisory surfaces it, since that drift is what the advisory exists to catch.

  

**Two integration points to verify before building** — both are assumptions here, not established facts:

  

  - **Whether the scheduler carries a publication date or only a production date.** On a Doc destination writing is delivery, so the distinction never arose. On a website they come apart: a cluster can be written in one batch and published over six weeks. If the scheduler is production-only, the module reuses it for generation and layers a publish cadence over it — still one scheduler, one cost model.
  - **Whether "website" can be a destination, and whether the VA flow composes with auto-publish.** The scheduler is VA-oriented; informational sites publish with no human. A queue built around handing work to a person may not have a sensible shape when nobody touches it.

  

Reusing the scheduler beats building a second one regardless: it already has cost estimation, the spend gate, and the VA flow, and a parallel scheduler would mean two cost models that drift. Its estimate is computed on the blog per-article constant, which is the correct constant for informational content.

#### 4.15.2 Required set

|  |  |
| :-: | :-: |
| \*\*§4.10 group\*\* | \*\*On an informational property\*\* |
| Brand name | Required |
| \*\*Topic scope / silo structure\*\* | \*\*Required\*\* — from Fanout, user-reviewed |
| \*\*Named author\*\* (§4.15.3) | \*\*Required before generation\*\* |
| Phone, cities, service catalog | Not applicable |
| Founding story, licences, address, hours | Not applicable |
| Brand voice, ICP | Required for generation as normal |

  

Schema is WebSite, BreadcrumbList and Article/BlogPosting. No LocalBusiness, no NAP, no CallRail.

#### 4.15.3 Authorship

**Articles carry a real named person as author** (owner ruling). Three requirements follow, and they are not optional:

  

1.  The author is a **real person with a real bio page** — genuine credentials, per §5.6. An invented persona is fabrication whether it appears in a byline or a team photo.
2.  The **bio page is required**, not trigger-gated, on an informational property. Article.author pointing at nothing is worse than no byline.
3.  The author's name and credentials are stored facts, so §5.3 applies: generated copy cannot expand a byline into experience the person does not have.

  

**The tension worth naming.** Informational sites auto-publish with no human review (locked ruling), and a real byline is a claim of authorship. Attaching a real person's name to content they have never read is a reputational exposure for that person, and it is the one place where two settled decisions pull against each other. This is not a reason to reopen either, but it wants a deliberate answer rather than an accident — see Q18.

#### 4.15.4 Monetisation is a declared property of the site

Every site carries **monetization**, a multi-select — not a site type, and not inferred from content. Legal values: ads, affiliate, leads. **Authority is the empty set**, not a third option, because ads and affiliate routinely stack and forcing a single choice would produce a wrong answer on day one.

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*Value\*\* | \*\*Typical site type\*\* | \*\*What it turns on\*\* |
| ads | informational | Ad slot components, ads.txt, ad network settings |
| affiliate | informational | Affiliate link table, post-generation link insertion, disclosure template and gate |
| leads | lead\\\_gen, local\\\_business | Web3Forms lead events, CallRail attribution, lead-sale disclosure on owned properties |
| \*(none)\* | any | Nothing. No ad config, no affiliate table, no disclosure surface |

  

**It is orthogonal to** **site\_type**, which is why it is a separate field. A client's local site is leads; an owned property may be leads, or ads + affiliate, or both. Reading monetisation off the site type would be right most of the time and wrong exactly where it matters.

  

**Declaring it up front is what makes the gates deterministic:**

  

  - **Affiliate links cannot be inserted on a site without** **affiliate****.** A stray affiliate URL becomes a build-time bug rather than an undisclosed live page.
  - **Template coverage (§4.4) knows what to check for.** An ads site whose approved theme has no ad slot components fails at **theme approval**, not at publish.
  - **An unmonetised site carries no dead config** — no ads.txt, no ad settings, no affiliate table, no disclosure template.

  

**Monetisation is editable on a live site**, because launching as an authority asset and monetising once traffic clears a network's threshold is the normal sequence, not an exception. To make that switch cheap, **ad slot components are present in every informational theme and render nothing when** **ads** **is off** — reserved space costs nothing empty and saves a theme rebuild later. Adding affiliate to a live site requires no theme change at all, only the link table and disclosure template.

  

Both monetisation modes introduce requirements the module must handle at build time, not bolt on afterward.

  

**Display advertising**

  

  - **Ad slots are named theme components** with reserved dimensions, part of the theme contract like any other (§4.5). They exist in every informational theme regardless of the current monetization value, and render nothing when ads is off.
  - **Space is reserved in the layout** whether or not a slot is filled, so an unfilled or slow-loading ad shifts nothing.
  - **ads.txt** **is committed to the repo root** and treated as config, not content.
  - **Network approval is a post-launch lifecycle step.** AdSense approval and the traffic thresholds on the larger networks arrive months after launch, so ad configuration is editable in Settings on a live site and is not part of the launch checklist. ads.txt is written when ads is enabled, whenever that happens.

  

**Affiliate links**

  

  - **An LLM never generates an affiliate URL.** Links are inserted deterministically after generation, matched from a stored product/link table. A generated affiliate URL is either hallucinated or wrong, which means broken links and unattributed revenue.
  - **Every affiliate link carries** **rel="sponsored nofollow"**, applied by the insertion step rather than left to the writer.
  - **Disclosure is a hard requirement**, not a privacy-policy line: an FTC-compliant disclosure renders above the first affiliate link on every page carrying one, from a template. A page with an affiliate link and no disclosure **cannot publish**, on the same terms as a facts-consistency failure. The same gate makes an affiliate link on a site without affiliate a hard failure rather than a silent publish.
  - Networks with prescribed disclosure wording (Amazon Associates) store that wording per-network rather than paraphrasing it.

  

**Consent management**

  

An ads site needs a consent management platform — ad networks require one, and California residents are in scope of CCPA/CPRA regardless of where the site is hosted. This is a **required theme component and a build-time concern**, not a snippet added later:

  

  - **Consent banner is a named theme component** with reserved space, so it does not shift layout when it appears (the same CLS logic as ad slots).
  - **Ad and analytics tags do not fire before consent** is resolved where consent is required.
  - **A "Do Not Sell or Share My Personal Information" link renders in the footer** on any site carrying ads or affiliate, alongside the privacy policy.
  - **Global Privacy Control (GPC) browser signals are honoured** as an opt-out. This is not optional under CPRA and is frequently missed because it needs no visible UI.
  - **The privacy policy states the categories of data collected, sold and shared** — the generic template does not cover this, so an ads or affiliate site takes an expanded policy template.
  - The consent surface is **configured per site and enabled with** **ads**, so an authority site carries none of it.

  

The module is not the place to settle jurisdiction questions; the requirement here is that the components exist, are wired to the monetisation flag, and are reviewed by someone qualified before the first monetised property goes live.

  

**One structural caution.** A site that is ad-dense and affiliate-heavy relative to its actual usefulness is the shape search engines treat as made-for-advertising. The mitigations are already in the spec — ad slots budgeted in the theme rather than maximised, disclosure enforced, quality gates unchanged — but ad density is a theme-level decision that should be made deliberately once, not tuned upward per site.

#### 4.15.5 Metrics

Neither §7's delivery metrics nor §4.12's cost-per-lead apply. Informational properties are measured on **sessions, RPM/EPMV, affiliate revenue per session, and indexed-page share at 90 days** — all of which take months, so the leading indicator in the meantime is indexation rate and time-to-first-ranking-keyword.

  

## 5\. Content quality gates

### 5.1 The rule

**Every page passes a gate at publish time, not at generation time.** Generation always completes and always persists; a page that fails its gate sits at website\_pages.status='draft' carrying the reason. This keeps failures inspectable and makes retry cheap.

  

R1–R7 of the content-quality PRD apply unchanged to everything this module publishes and override anything below them.

### 5.2 Local-business pages (service / location — nlp-api)

Two bars, both already existing in the suite. The module reuses them and invents nothing:

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*Bar\*\* | \*\*Threshold\*\* | \*\*On failure\*\* |
| SEO composite (8-engine) | ≥ 75 (REOPT\\\_SCORE\\\_THRESHOLD) | Publish blocked; page offered to the reoptimization loop |
| Brand-voice verdict | assert\\\_voice\\\_publishable — blocks on an unresolved \*\*critical\*\* finding only | 409 voice\\\_violation; force\\\_voice override, staff+, one extra click |

  

75 is already the number the suite uses to decide a live page is good enough to leave alone; a second, website-specific threshold would make "good enough" mean two things depending on destination. Voice warnings and a low voice score stay advisory, exactly as in the three existing publish paths — a gate people route around is worse than no gate. Since local-business sites also carry a human plan/page review before first publish (plan §2), these bars are a floor under a human, not a substitute for one.

### 5.3 Core pages (home / about / contact — plan §4.6)

These have no target query and no SERP, so there is no composite score. The gate is the plan's deterministic validation: required slots filled, length bounds, and the facts-consistency check.

  

**The facts-consistency failure is a hard block with no override.** If generated copy asserts NAP, a licence number, years in business, or an award that is absent from the stored facts block, the page cannot be published by anyone at any role. This is the "facts vs prose" principle, and it is a liability question rather than a quality preference — a page must not claim something the business has not told us. Everything else in these pages (missing slot, length) is a staff-overridable warning.

### 5.4 Informational blog posts (auto-publish)

Auto-publish means no human reads these before the public does, so the machine gate must be **stricter** than where a human is in the loop, not looser. A post auto-publishes only if all hold:

  

1.  R1–R7 pass (the pipeline's existing checks).
2.  Voice verdict clean of critical findings.
3.  The Writer's schema\_version is **not** a -degraded variant. A degraded run means the article was written with zero brand context; the suite has already shipped one such article by accident and emits content\_no\_brand\_context for it. That article must never reach a live site unread.
4.  Frontmatter is complete and zod-valid: title, description, slug, publish date, category, **and declared blog format** (reference §5.3).
5.  **News/Commentary posts carry a published date and a sunset or review date.** This format is explicitly non-evergreen, and auto-publish plus no human review plus no expiry is how a site ends up ranking on outdated information indefinitely. A News post without a review date is held.

  

A post failing any of these is held at draft and raises one website\_page\_held notification per batch (not per page). Holding is the safe default because the alternative — publishing it — is unrecoverable in the sense that matters: it is indexed before anyone notices.

  

**\[Assumption\]** Auto-publish applies to the initial content plan and the drip alike, per plan §2. It does **not** extend to core pages or to any local-business page, ever, regardless of site type.

### 5.5 Structural rules from the Page Type Reference

Deterministic, checkable, and publish-blocking on the page type they apply to. None of these needs an LLM to evaluate:

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*Rule\*\* | \*\*Applies to\*\* | \*\*Source\*\* |
| H1 optimized for the brand, not the money keyword | Homepage | SOP via reference R5 |
| Never geo-targeted | Top-level service pages (single-city businesses excepted); informational posts \*\*except the Local Geo Post format\*\*, which is the SOP-sanctioned geo-targeted post | SOP via reference R5, §5.3 |
| Geo keyword only, major services as H2s | Top-level location pages | SOP |
| Under 150 words of copy | Contact Us | SOP — padding is an explicit violation |
| Not keyword-targeted beyond "(brand) areas" / "(brand) blog" | Areas We Serve, Blog Archive | SOP |
| Definition resolves the query in 40–60 words, standalone | Glossary / DefinitionBox | Reference |
| Freshness date present | Cost, pricing, statistics pages | Reference §7 global rule |
| Expiry present, and expired offers flagged | Offers / Specials | Reference |
| Depth within the entry's target band (±20%) | All | Reference Content spec |

  

A violation holds the page at draft with the rule named. Staff may override the depth band; the SOP rules (the first five rows) are not overridable, because they are structural SEO errors the site would carry indefinitely.

### 5.6 Proof and imagery: fabrication is a hard block

The reference's global rule — *never fabricate proof: testimonials, metrics, customers, team members, stock-photo personas* — is binding here and **upgrades plan §4.7's residual recommendation to a rule**. Generated imagery may fill hero, service-card, and jobsite slots (the locked ruling; it plays the stock-photography role). It may **not** populate TestimonialCard, team or author photos, or GalleryBeforeAfter. Those components render nothing when real assets are absent, per the degradation default. There is no override at any role, for the same reason the facts-consistency check has none: these are claims about specific work and specific people, not decoration. §4.13.3 extends the same test to alt text, and §4.13.4 sets which site types may show people at all.

### 5.7 Overrides are recorded

Any forced publish records who forced it and which gate was bypassed on the website\_deploys row that carries the commit. Overrides that are invisible after the fact are indistinguishable from bugs.

  

## 6\. The module surface

### 6.1 Where it lives in AR Tools

The Website Builder is a **client-workspace module**, in the pattern every other module already uses (GBP Posts, Ecommerce Writer, Local SEO):

  

|  |  |
| :-: | :-: |
| \*\*Concern\*\* | \*\*Convention it follows\*\* |
| Entry points | \*\*Two, and they do different jobs.\*\* (1) A \*\*"Websites" sidebar entry\*\* → route /websites, the fleet view across every client. (2) A \*\*"Website Builder" card\*\* in the client workspace → route clients/:id/website, where the work on one site happens. |
| Code | frontend/src/pages/WebsiteBuilder.tsx + components/website/\\\* |
| Gating | website\\\_builder\\\_enabled feature flag, plus the §2 role checks per action |
| Long jobs | useResumableJob + the shared components/publish/\\\* bars — compile, provision, generate and publish batches are all leaveable |
| Alerts | notifications.emit(client\\\_id, …) for deploy failure, held pages, domain activation, purge |
| Freeze | The same red client-freeze banner the rest of the workspace shows |

  

Every site belongs to a client row (locked ruling), including standalone informational sites and owned lead-gen properties, so **there is no second place to look** — a site is always reachable from its client's workspace. Owned properties carry kind = owned\_property (§4.12.1) and are filtered out of client-facing reporting and the client picker by default; the sidebar Websites index shows both, filterable by kind.

  

**Why a sidebar entry and not just the card.** Every other module in the suite is purely client-scoped, and that is right for them — you pick a client, then work. This module is the exception because its unit of management is the *fleet*: \~50 sites across many clients, where the questions are "what's live," "what failed to deploy last night," and "how many shipped this month." None of those are answerable from inside one client's workspace, and §7's metrics 1–4 are read directly off that screen. Trash (§3.2) lives there too, since a soft-deleted site has no workspace to sit in.

  

The split:

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*Surface\*\* | \*\*Scope\*\* | \*\*For\*\* |
| \*\*Sidebar → Websites\*\* | All clients | Fleet status, filtering, Trash, throughput metrics. staff+ |
| \*\*Workspace card → Website Builder\*\* | One client | Create, plan, generate, publish, deploy, settings |
| \*\*Client → Business Facts\*\* | One client | The §4.10 / §4.11 inputs, shared across that client's sites |

  

Nothing is duplicated: the sidebar index links into the workspace card, and the card is the only place work happens.

### 6.2 Screens

|  |  |  |
| :-: | :-: | :-: |
| \*\*Screen\*\* | \*\*What it must let someone do\*\* | \*\*States from §6.3 it surfaces\*\* |
| \*\*Websites index\*\* (suite-level) | See every site, filter by status/client, open one, restore or purge from Trash | — |
| \*\*Create wizard\*\* (modal, 4 steps) | \*\*Client path:\*\* 1 select client + site type → 2 business facts and service catalog. \*\*Owned-property path:\*\* 1 vertical/topic + site type + \*\*monetisation\*\* (§4.15.4) → the wizard \*\*creates the property row\*\* → 2 invent brand, catalog or topic scope, tracking number, then the §4.12.3 or §4.15.1 discovery and review step. Both then: (§4.9 — required set enforced; GBP pre-fills a slice, manual always wins) → 3 design upload → 4 compile + preview + approve. Provisioning starts on approve, not before | Zip ambiguous · zip is a canvas doc · compile failed · preview wrong |
| \*\*Overview tab\*\* | See status, staging and live URLs, domain state, last deploy, launch checklist; run the danger-zone actions the role allows | Provisioning in flight · provisioning failed · freeze · domain pending NS |
| \*\*Plan tab\*\* | Review proposed pages in tier order with the trigger that matched each, links-per-index per silo, matrix size, template coverage; approve or edit the plan | Matrix \\\>200 · index \\\>40 links · missing template |
| \*\*Pages tab\*\* | See every page with status and, where held, the gate that failed; generate, retry, publish, republish; Drafts and Trash filters mirroring Local SEO | Batch partial failure · page failed its gate · image slot failed |
| \*\*Deploys tab\*\* | See deploy history with commit and conclusion, open the Actions log, retry, roll back a theme version | Deploy failed · status unknown · theme regression |
| \*\*Business Facts\*\* (on the client row, or the property row for owned\\\_property) | Enter and edit every fact in §4.10 plus brand voice, ICP and competitors (§4.11); see per-field provenance, what each field unlocks, and what is still missing. On an owned property, not-applicable groups are hidden rather than shown empty (§4.12.5) | — |
| \*\*Settings tab\*\* | Attach or detach a domain, manage GA4 / CallRail / Web3Forms, change monetization and its config (ad networks, affiliate link table), view and switch theme versions | Domain pending NS |

  

Screens are role-aware rather than role-hidden: an action a user cannot perform is shown disabled with the reason, so a VA can see that publish exists and who to ask. Hiding it produces support questions instead of understanding.

### 6.3 States and error surfaces

The rule for every state below: **the surface names what failed, at which step, and offers exactly one recovery action.** "Something went wrong, try again" is not acceptable in a module whose failures are mostly partial and mostly resumable.

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*Situation\*\* | \*\*What the user sees\*\* | \*\*Recovery action\*\* |
| Provisioning in flight | The step machine's steps with per-step state (repo → secrets → config commit → deploy recorded), current step highlighted | None needed; the page is safe to leave — work continues server-side |
| Provisioning failed at step N | Steps 1..N-1 green, step N red with the provider error mapped to a suite error code | \*\*Resume\*\* — re-runs from step N (idempotent, never restarts). Never a "start over" button |
| Theme compile failed a post-check | Which check failed (invalid Astro, external request, missing token, sc-\\\* residue) and the file | \*\*Recompile\*\* (new version) · \*\*Upload a revised design\*\* · \*\*Pick a house theme\*\* |
| Compile succeeded but the preview looks wrong | Preview with \*\*Approve\*\* / \*\*Reject\*\* | Reject → recompile or re-upload. Nothing is provisioned until approve, so a bad compile costs a re-run, never a bad live site |
| Zip contains several designs | Picker listing each design with its thumbnail; canvas/direction docs excluded and labelled as such | Choose one |
| Zip contains only a canvas doc | Explicit error: this is an exploration doc, not a design | Upload the design export |
| Deploy failed (Actions run) | Failed chip on the deploy row, the run's conclusion, deep link to the Actions log. \*\*The site is still serving its last good deploy\*\* — stated in the surface | \*\*Retry deploy\*\* (re-dispatch, no re-generation) |
| Deploy status unknown (poll timeout) | "Status unknown" chip, not "failed", with the age of the last successful poll | \*\*Re-check now\*\* · link to Actions |
| Content batch partially failed (N of M) | Per-page rows with individual status and reason; the batch does not roll back succeeded pages | \*\*Retry failed (N)\*\* as a bulk action; per-page retry on each row |
| A page failed its quality gate | Held at draft with the gate and the number/finding that failed it | \*\*Reoptimize\*\* (SEO) · \*\*View voice findings\*\* · \*\*Publish anyway\*\* where the gate permits an override |
| Freeze opened mid-batch | Freeze banner; remaining jobs show client\\\_frozen; queued jobs cancelled, not retried | None in-module until the freeze lifts |
| Domain waiting on nameservers | "Waiting for nameservers" with the two Cloudflare NS values shown for copy-paste and the last check time | \*\*Check now\*\*; automatic re-check on the scheduler |
| Image generation failed for a slot | Placeholder retained, page publishes, slot flagged on the launch checklist | \*\*Regenerate image\*\* · \*\*Upload one\*\* |
| New theme version changes the image spec | Prompt naming how many slots were generated under the old spec, shown before anything changes | \*\*Regenerate imagery\*\* · \*\*Keep existing\*\* — never silent |
| New theme version made a live site worse | Deploy history shows the theme commit | \*\*Roll back to previous theme version\*\* — revert commit + redeploy; content untouched |

  

Two cross-cutting requirements:

  

  - **Nothing that costs money runs without the user having seen the cost.** Content batches show the item count before dispatch, in the pattern the Fanout already uses.
  - **Every long-running action is leaveable.** The suite's useResumableJob / "leave & finish in the background" affordance applies to compile, provision, generate, and publish batches.

  

## 7\. Success metrics

At \~50 sites in year one, outcome metrics are low-n and slow; leading operational metrics are what will actually tell us whether the module works. Ranked:

  

|  |  |  |  |  |  |
| :-: | :-: | :-: | :-: | :-: | :-: |
| \*\*\\\#\*\* | \*\*Metric\*\* | \*\*Definition\*\* | \*\*Source\*\* | \*\*Target\*\* | \*\*Meaningful from\*\* |
| 1 | \*\*Time to live\*\* | Median hours from first design upload to the site answering on its custom domain, excluding time waiting on the registrar NS change | websites timestamps + website\\\_deploys | ≤ 1 working day | Site 3 |
| 2 | \*\*Sites shipped / month\*\* | Sites reaching live on a custom domain | websites | ≥ 4 (the \\\~50/yr ruling) | Month 2 |
| 3 | \*\*Rework rate\*\* | Theme recompiles per shipped site; pages republished within 7 days of first publish | website\\\_themes.version, website\\\_pages | ≤ 2 recompiles, ≤ 10% pages | Site 5 |
| 4 | \*\*Deploy reliability\*\* | Failed deploys / total deploys; median minutes to green after a failure | website\\\_deploys | \\\< 5% failed | Month 1 |
| 5 | \*\*Lead volume\*\* | Web3Forms submissions per site per month | Requires the webhook copy back into the suite (plan §4.8 follow-up) | Baseline first | Month 3 post-launch |
| 6 | \*\*Organic at 90 days\*\* | Indexed page share and keywords in top 20, per site | GSC via auto-verified property → rank tracker | Baseline first | Day 90 of site 1 |

  

**Why this order.** The module's thesis is throughput — it exists because turning generated content into a live site is currently 100% manual. Metrics 1–4 measure that directly, from data the module already writes. Metric 5 is the only outcome metric we own end-to-end and is the number that proves a LeadOff market entry worked, which is why the webhook is worth building. Metric 6 is real but confounded and slow, and free (GSC auto-verification puts every site into the rank tracker), so it is reported, not targeted.

  

**Explicit anti-metric:** pages published per site. Volume of thin local pages is precisely the failure mode Google's scaled-content policies target (plan §10), and rewarding it would push the team the wrong way.

  

## 8\. Acceptance criteria

Testable, in the repo's checkable style. A reviewer should be able to tick each.

### A. Design ingest and theme compile

  - A .zip containing one design and one canvas doc compiles the design and excludes the canvas doc without asking.
  - A zip with two designs presents a picker; a zip with zero designs errors explicitly.
  - The compiled theme contains no sc-if, sc-for, {{ }}, or onClick residue and makes no external network request except the §4.8 sanctioned snippets.
  - Every token referenced by a template exists in tokens.json; every page branch renders against the derived collection schema.
  - Prototype nav (state.screen, go\*()) becomes real \<a href\> routes, and image placeholder strings are captured per slot into the image-generation prompt.
  - A preview is rendered per page type and the site cannot be provisioned until it is approved by a staff+ user.
  - Recompiling a re-uploaded design creates a new version and does not mutate the approved one.
  - Themes carry a theme\_source; no code downstream of theme approval branches on whether a design import produced the theme.

### B. Provisioning

  - Provisioning is gated on staff, website\_builder\_enabled, and the client not being frozen; killing the worker mid-provision and resuming produces exactly one repo, one Worker, one deploy record.
  - A failure at any step leaves the site in error with the failed step named and a Resume action, never a half-site the module cannot see.
  - The created repo is private, under kssabraw, with the Cloudflare secrets set and no other secret present.
  - A staging URL is reachable before any custom domain exists.

### C. Site plan and content generation

  - A local-business plan renders from Plan Silo + fixed pages and cannot be published without a human approving it.
  - A client with no GBP produces a complete plan; every fact-consuming section that has no facts renders nothing rather than an empty shell.
  - The wizard cannot complete without business name, phone, at least one city, and a service catalog; every other field is optional.
  - Business facts are stored on the client and shared across that client's sites; a second site for the same client requires no re-entry.
  - The service catalog is entered by the user; GBP categories never populate it, only suggest.
  - A service slug is editable before first publish and immutable after; a clash with a reserved slug, a city, or another service is caught at entry.
  - The catalog form shows the projected matrix page count and links-per-index as services and cities are entered.
  - A service excluded from the matrix gets a service page but no local landing pages.
  - A site can be created, themed and provisioned with no voice card; the first generation request blocks with content\_no\_brand\_context.
  - Brand voice, ICP and competitors are editable from Business Facts and write to the same client fields the dashboard edits — no module-local copy.
  - A derived voice card is marked as derived and does not unlock generation until approved.
  - No page is generated from a -degraded run on any site type.
  - Every field shows its provenance, and a GBP sync fills empty fields without overwriting any manual entry.
  - Licences and certifications are structured entries (type, issuing body, number), not free text, so §5.3 can check copy against them.
  - Filling a previously empty optional field re-enables the page types it unlocks, without a rebuild of unrelated pages.
  - A site built from the required set alone deploys successfully, with absent-fact sections omitted and both the held About page and the empty TrustBadgeRow named on the launch checklist.
  - Manual facts always beat GBP; a later GBP sync fills gaps and overwrites no user-entered field.
  - NAP and JSON-LD are built only from stored facts; a generated page asserting an unstored fact fails the facts-consistency check.
  - Generation is freeze-gated (client\_frozen); a VA can generate and cannot publish.

### D. Page inventory and templates

  - Every planned page maps to a Page Type Reference entry; every non-CORE page carries the trigger that matched, visible in plan review.
  - Local landing pages are emitted at /{city-slug}/{service-slug}/, service pages at /{service-slug}/, location pages at /{city-slug}/.
  - Two entries claiming the same path fail the site build rather than one silently winning; a neighborhood page and a local landing page can coexist under the same city.
  - A single-city client's plan contains no location pages and no local-landing matrix; its service pages geo-target the city.
  - A service, city, or pillar slug colliding with a reserved root slug blocks plan approval and names the collision.
  - Every emitted URL carries a trailing slash; archive pagination is /{archive}/page/{n}/.
  - A local landing page's breadcrumb parent is its city page; the Services index is not a breadcrumb ancestor of a service page.
  - Every planned blog post carries a declared format; News/Commentary posts are excluded from pillar-cluster counts.
  - Renaming a service emits a 301 from the old path in the same deploy as the rename.
  - Structural links are rendered from frontmatter and reference published pages only; a page held by a quality gate is absent from its neighbours' link lists rather than linked and broken.
  - A held page that later publishes gains its inbound structural links on the next deploy without any page being regenerated.
  - Generated copy contains no internal URL that was not on the supplied eligible-target list; an unresolvable link is stripped at publish with its text left intact, and the strip is logged.
  - The links-per-index figure shown at plan review is derived from the structural rules and is available before generation runs.
  - Every site renders an XML sitemap of published pages only, referenced from robots.txt, and an HTML sitemap at /sitemap/ grouped by silo.
  - Neither sitemap lists a page held by a quality gate; both pick it up on the next deploy once it publishes.
  - Every site renders a 404 page carrying a working client-side search plus links to the homepage, top-level silos and the HTML sitemap.
  - Every page type shown in plan review displays its engine status; a type with no engine cannot be approved into the plan without an explicit acknowledgement.
  - Intake-only page types (bio, projects, offers, warranty, testimonials) are populated from collected facts and are never generated.
  - Every generated template carries the SOP global nav/footer set; campaign pages are the only exemption.
  - A matrix exceeding 200 pages, or an index page exceeding 40 outbound body links, blocks plan approval until acknowledged.
  - A neighborhood page cannot be planned for a neighborhood that fails the Maps entity test.
  - A plan requiring a page type the approved theme has no template for cannot be approved, and the screen offers drop / re-upload / map-to-existing.
  - Compiled theme components are named from the Shared Component Library and each carries its specified mobile behaviour.
  - Generated content stays within its entry's depth band, covers its must-cover items, and violates none of the §5.5 structural rules.
  - No generated image is placed in a testimonial, team/author, or before-after component at any role.

### E. Publish and deploy

  - A local-business page below composite 75 or with an unresolved critical voice finding cannot publish without an explicit override, and the override is recorded on the deploy row.
  - An informational post from a -degraded Writer run is held, never auto-published.
  - Publishing is idempotent by page id: a retry never creates a second commit for an already-published sha.
  - A batch of 20 pages where 3 fail leaves 17 published and offers Retry failed (3).
  - Deploy status resolves to success or failed for every recorded deploy, or to an explicit unknown with a re-check action.
  - A failed deploy leaves the previously deployed site serving.

### F. Domain and search console

  - Attaching a domain is admin-only, creates the DNS records, and reports pending\_ns until the nameservers resolve, with the NS values displayed.
  - On activation, the GSC TXT record is created, the property verifies for the service account, and the site appears in the rank tracker without further action.
  - Detaching a domain leaves the repo, the content, and the GSC property intact.

### G. Lifecycle and permissions

  - Delete soft-deletes only; the live site stays up and the repo still exists afterwards.
  - A soft-deleted site is restorable with its pages, deploys, and theme intact.
  - Purge is admin-only, requires the site name typed, defaults every destructive option off, and is refused while a custom domain is active.
  - Unpublish takes the site off the public domain, keeps the staging URL and the repo, and is reversible in one action.
  - Archiving a client with live sites warns and names them; the sites stay live.
  - A freeze halts generation and publish, leaves the live site serving, and does not silently resume on lift.
  - Every action in §2 returns 403 with the right error code for a role below its bar, at both the route and the job worker.

### H. Module surface

  - The Website Builder card appears in the client workspace only when website\_builder\_enabled is on, and the route 404s when it is off.
  - A client with no site shows an empty state with Create; a client with a site opens on Overview.
  - The Websites sidebar entry lists sites across all clients with status, domain state and last deploy, and is the source for metrics 1–4.
  - Opening a site from the sidebar index lands on that site's workspace card; no work action exists on the index except restore and purge from Trash.
  - Actions above the user's role render disabled with the reason, not hidden.
  - Compile, provision, generate and publish can each be left mid-run and are still progressing when the user returns.
  - A frozen client's site shows the standard freeze banner and every write action is disabled.

### I. Lead-generation properties

  - A lead\_gen site emits WebSite and BreadcrumbList schema only; no LocalBusiness or Service JSON-LD is produced at any point.
  - No NAP block, address, hours, TrustBadgeRow, testimonial, team or before-after component renders on a lead\_gen site.
  - The About page states the site is a matching service and that quotes come from independent providers; the form carries consent language and the privacy policy discloses lead sale.
  - Multi-city discovery returns census places within the configured radius of the seed centroid, capped at 20 by population, with anything lacking a valid DataForSEO location dropped.
  - The city list is presented for review with distance, population and place type before it is committed; no city enters the plan unreviewed.
  - Neighborhoods generate location-variant pages only and never multiply the service matrix.
  - A single-city lead\_gen site has no location pages and no matrix.
  - Plan approval is blocked until the portfolio conflict check runs; a property-vs-client overlap requires an admin override, property-vs-property warns.
  - A lead\_gen site can be created without any pre-existing client row; the wizard creates the property row from the market and brand name.
  - Business Facts for an owned property is reachable from the Websites index and requires no client workspace.
  - Not-applicable fact groups are hidden from the form and absent from the launch checklist, so a complete property shows a clean checklist.
  - Every form submission and tracked call emits a lead event carrying source site, service, city and timestamp.
  - A lead\_gen property plans both a conversion matrix and an informational silo set; neither ships alone.
  - No generated page on a lead\_gen property is written in first person as a service provider, and none claims a licence, crew, history or physical premises.
  - Informational pages on a property are scheduled through the same Fanout-plus-supplement mechanism as an informational site (§4.15.1b).

### J. Informational properties

  - A standalone informational site is created without a pre-existing client row and carries kind = owned\_property.
  - Generation is blocked until a topic scope is committed and a named author with a bio page exists.
  - The plan tab shows fan-out and supplemental pages in one view, each carrying its provenance.
  - A pillar is never scheduled before the cluster it summarises is complete.
  - Approval binds publication order; a held or failed post shifts the queue without orphaning anything downstream.
  - A supplemental page cannot be created without declaring a silo and cluster, or declaring itself standalone.
  - A supplement that brings a cluster to the pillar threshold triggers the pillar identically to a fan-out post.
  - Every article emits Article/BlogPosting schema with a resolving author; no LocalBusiness schema is produced.
  - No affiliate URL appears in generated copy; links are inserted post-generation from the stored link table and carry rel="sponsored nofollow".
  - A page containing an affiliate link cannot publish without its disclosure rendered above the first such link.
  - Ad slots reserve their space in the layout when unfilled; ads.txt is present at the repo root whenever ads is enabled and absent otherwise.
  - monetization is a multi-select independent of site\_type; an unmonetised site carries no ad config, affiliate table or disclosure template.
  - An ads site whose approved theme lacks ad slot components fails at theme approval, not at publish.
  - Enabling ads on a live site requires no theme change; ad slots are present and dormant in every informational theme.
  - An affiliate link on a site without affiliate blocks publish rather than shipping undisclosed.
  - Ad network configuration is editable on a live site and is absent from the launch checklist.
  - A site with ads renders a consent banner that reserves its space, and no ad or analytics tag fires before consent is resolved.
  - A site with ads or affiliate carries a "Do Not Sell or Share My Personal Information" link and the expanded privacy policy template; an unmonetised site carries neither.
  - GPC signals are honoured as an opt-out without requiring user interaction.

### K. Imagery

  - Every site has an image spec derived at theme approval, and every generation call on that site uses it.
  - Applying a new theme version offers imagery regeneration and never performs it silently.
  - Imagery for the whole site is generated at plan approval; a failed slot keeps its placeholder, does not block publish, and appears on the launch checklist.
  - Every image carries alt text, and alt text asserting an unstored fact is blocked on the same terms as body copy.
  - No lead\_gen site renders an image containing identifiable people.
  - No image file is shared between two sites; generated assets are committed to the site's own repo.
  - An image batch shows its cost before dispatch.

### L. Launch kit

  - The launch checklist reports domain active, GSC verified, form test submission received, legal pages present, and every image slot sourced.
  - The contact form's test submission arrives at the configured recipient.
  - The real phone number is in the JSON-LD and the CallRail number is in visible markup on a site with DNI configured; on a site without it, the real number serves both.
  - Privacy and terms pages render from templates with no LLM involvement.

  

## 9\. Open questions for the owner

Each question below has a recommended default, already applied in the body above. Rule one way or the other; silence means the default stands. (Separately, core-pages prompt copy, pilot client selection, and a second design fixture are owner tasks already tracked in plan §12 — not gaps in this document.)

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*\\\#\*\* | \*\*Question\*\* | \*\*Recommended default\*\* |
| Q1 | Does provisioning stay at staff, or move to admin? | \*\*Stays\*\* \*\*staff\*\*\*\*.\*\* It creates only private, undeployed, recoverable resources. Domain attach, unpublish, and purge are the admin-gated acts. |
| Q2 | Should hard-deleting the GitHub repo and Cloudflare Worker be possible at all? | \*\*Yes, admin-only, opt-in per resource, never default, blocked while a domain is live.\*\* Removing the capability entirely means test sites accumulate forever. |
| Q3 | Is "a -degraded Writer run never auto-publishes" the right floor for informational sites? | \*\*Yes.\*\* It is the one failure mode we have already shipped in production, and no human reads these posts. |
| Q4 | Publish threshold for local-business pages — reuse 75, or set a higher website-specific bar? | \*\*Reuse 75.\*\* One number for "good enough to be live" across the suite. |
| Q5 | Can a VA publish to a live website? | \*\*No.\*\* Generate and retry, yes; publish, no. Revisit once a VA-facing review queue exists. |
| Q6 | Does unpublish also kill the staging URL? | \*\*No.\*\* Keeping it lets the team keep working on a paused site. |
| Q7 | Build the Web3Forms → suite webhook copy (plan §4.8 follow-up) in Phase 3? | \*\*Yes.\*\* Lead volume is the only outcome metric the module fully owns, and without it §7 metric 5 is unmeasurable. |
| Q8 | Retention for soft-deleted sites? | \*\*90 days, nag only, never auto-purge.\*\* Auto-destroying a live client artifact on a timer is not a risk worth the tidiness. |
| Q9 | Should archiving a client default to unpublishing its sites? | \*\*No\*\* — offer it as an unchecked option at archive time. A churned client's site coming down should be a decision, not a side effect. |
| Q10 | Bio canonical path | \*\*Resolved 2026-08-03\*\* — /bio/{person-slug}/, ratified in reference §1.2. |
| Q11 | ⭐ extension URLs are now ratified in the reference, but the SOP body still lacks the type definitions and the \\\> 40 link-equity threshold is explicitly unratified. Does the module plan these types on the reference's authority alone, and does it block on 40 links? | \*\*Plan on the reference's authority; treat 40 as advisory.\*\* The reference is what the tools read, and a reserved path is safe to emit. But a number that blocks work needs ratifying — until it is, the plan review warns rather than blocks. Ratifying a real figure is the outstanding item. |
| Q12 | Which priority tiers should a v1 site plan propose by default? | \*\*Tiers 1–3.\*\* Tier 4 matrix expansion beyond the service × city grid, and Tier 5 investment pages, are proposed only on an explicit ask — they are where thin-content risk and link-equity dilution live. |
| Q16 | Can the user enter brand voice and ICP in the module, and can it derive a starter card? | \*\*Resolved 2026-08-03 — both (§4.11).\*\* Direct entry writes to the client record; a derived draft is offered for brand-new businesses and requires approval. Remaining sub-question: whether editing a voice card mid-site should flag already-published pages written under the old one for review. Recommend \*\*yes, as an advisory list, not an auto-regenerate.\*\* |
| Q15 | Business facts intake and the service catalog | \*\*Resolved 2026-08-03 — both user-entered, built in v1 (§4.10).\*\* The catalog is a new client-level structure; GBP categories suggest but never import. |
| Q18 | Informational sites auto-publish with no human review, and now carry a real person's byline. How is that reconciled? | \*\*Keep auto-publish, but bootstrap and sample.\*\* The first \\\~10 posts on a new property are reviewed before publish so the pipeline is calibrated against that author's voice and subject; after that a rolling sample rather than every post. Any post held by a §5.4 gate never auto-publishes regardless. The alternative — a byline on wholly unread content — puts a real person's name behind output nobody has checked. |
| Q17 | The lead marketplace — buyer management, per-lead pricing, routing, dedup, disposition — is out of scope here. Does it get its own module now, or start as a section of this one? | \*\*Its own module from day one.\*\* It shares nothing with site building and will grow buyers, pricing and dedup logic of its own. This module's contract with it is a lead event with attribution, nothing more. |
| Q13 | Where do redirects live, and does website\\\_pages retain superseded routes? | \*\*A generated\*\* \*\*\\\_redirects\*\* \*\*file committed with the rename\*\*, and yes — retain superseded routes, since the redirect source must outlive the slug. Nothing is built for this; slug immutability is a ratified rule with no implementation. |
| Q14 | Writer \\\#6 (hub/index) covers Areas We Serve, Services index, project/blog archives and pillar pages, and does not exist (§4.7). Build it, or ship without those page types? | \*\*Build it.\*\* It is one archetype unlocking five page types across both site shapes, and pillar pages are load-bearing for informational sites — Fanout produces clusters that trigger a pillar by construction. |

  