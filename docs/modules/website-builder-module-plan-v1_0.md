# Website Builder — Module Plan v1.0

**Status:** Proposed (not built). Planning document only — nothing in this doc is implemented.
**Owner:** Kyle
**Last updated:** 2026-07-17
**Relationship to other work:** consumes the Local SEO generator (nlp-api), the Blog Writer pipeline, Plan Silo, GBP data, Keyword Research/Fanout, and the shared scheduler/notifications rails. Gives the suite its first true "publish to a live site we control" destination (adjacent to — but not reversing — the locked "publish = Google Doc, CMS-ready later" decision; **owner signed off on the additive website destination 2026-07-17**).

> **One-line summary.** Design a site in **Claude Design**, upload the export to this module, and the suite turns it into a live website: it compiles the design into an **Astro** theme, provisions a **GitHub** repo from a house template, generates the pages/posts with the suite's existing content engines, commits them as content-collection entries, and deploys via **Cloudflare** — for two site shapes: **local business websites** (per-client) and **informational/blog websites** (content properties).

---

## 0. Context for a reader new to this codebase

AR Tools is an internal agency SEO/content suite. The pieces this module builds on are already live unless noted:

| Piece | What it is | Where |
|---|---|---|
| **Local SEO generator** | Competitor SERP analysis + Claude page generation + 8-engine scoring/auto-reoptimization. Emits `<title>` + `<article>` HTML + JSON-LD + content gaps. This is the engine that writes local landing / service / location pages. | `writer/nlp-api/`, `services/local_seo_service.py` |
| **Plan Silo** | Seed service + area → the full set of local pages a business should have (service variations, geocode-verified neighborhoods, multi-city targets), with bulk-create. This is the **site map generator** for a local business site. | `services/local_seo_silo.py` |
| **Blog Writer pipeline** | Five-module pipeline (brief → SIE → research → writer → sources cited) producing publication-ready **Markdown** articles. This is the engine for informational-site posts. | `writer/pipeline-api/`, `services/orchestrator.py` |
| **Fanout content scheduler** | Scheduled mass content generation (blog posts and Local SEO pages) with VA cost gating. The natural "drip new posts onto the site" driver. | `writer/platform-api/fanout/` |
| **GBP data** | Per-client Google Business Profile (NAP, hours, categories, reviews, service areas) already captured. Source of truth for a local site's business facts + LocalBusiness JSON-LD. | `services/gbp_service.py`, `clients.gbp` |
| **HTML→Markdown** | An existing converter used by Content Syndication. Reused to turn nlp-api HTML pages into Astro content-collection Markdown. | `services/syndication_rewrite.py` |
| **async_jobs + shared scheduler** | The suite's only queue (Supabase table + asyncio worker) and in-process scheduler. All new background work rides these — no new infra. | `services/job_worker.py`, `services/gsc_scheduler.py` |
| **Freeze Protocol** | A frozen client's content creation halts everywhere (router gates + job-worker gates). Website publishing must join this. | `services/freeze.py` |
| **Rank tracker + GSC** | Hybrid GSC/DataForSEO rank tracking, GSC ingest via service account. A new site should flow into this the moment it's live. | `services/gsc_*`, `routers/rank.py` |
| **Notifications** | `notifications.emit(...)` → in-app + Slack. The channel for "site deployed" / "deploy failed". | `services/notifications.py` |

**What does not exist yet:** any GitHub or Cloudflare integration, any Astro tooling, any concept of a "website" entity, any design-ingestion path.

---

## 1. Problem

The suite generates excellent content but has nowhere of its own to put it. Local SEO pages and blog articles land as Google Docs (or WordPress via credentials we don't always have). Two recurring agency needs have no automated path:

1. **A local business client needs a website** (or a supporting local site): service pages, location pages, about/contact — the exact inventory Plan Silo already computes and the nlp-api already writes.
2. **The agency wants informational/blog properties** (content sites for topical authority, syndication targets, lead-gen assets) — the exact output the Blog Writer and Fanout already mass-produce.

Today, turning that content into a live site is 100% manual: design, repo, hosting, DNS, page-by-page copy-paste. The module automates the whole line: **design in → live site out → content keeps flowing**.

## 2. What we're building

A per-suite **Websites** module (with per-client attachment) that:

1. **Ingests a Claude Design export** (uploaded HTML/zip, or a pasted share/export URL) and **compiles it into an Astro theme**: design tokens (colors, fonts, spacing), layout components (header/footer/nav), and section components (hero, service card, review strip, article card…) with content slots — then renders a **preview** the user approves before anything is provisioned.
2. **Provisions the site**: creates a GitHub repo from a house **`ar-site-template`** Astro repo, commits the compiled theme + a `site.config.json`, creates the Cloudflare project, and deploys a skeleton immediately (every site gets a `*.workers.dev`/`*.pages.dev` staging URL before the real domain exists). Attaches the custom domain + DNS when the zone is on Cloudflare.
3. **Generates and populates content** using the engines the suite already has:
   - **Local business site**: site plan from Plan Silo + GBP → home, `/services/<slug>`, `/locations/<slug>`, about, contact (+ optional `/blog`). Business facts and LocalBusiness/Service JSON-LD come from the client's business-facts block (manual entry > GBP — §4.5; GBP is a source, not a dependency) — the writer never invents NAP.
   - **Informational site**: content plan from Keyword Research / Fanout → `/ [category] / [post]` articles from the Blog Writer pipeline, plus magazine home, category indexes, RSS, author/about pages.
   - Content is committed to the repo as **content-collection Markdown with frontmatter** (blogs are native Markdown; local pages converted via the existing HTML→Markdown path, JSON-LD carried in frontmatter and injected by the layout).
4. **Deploys on every content change** (build in GitHub Actions → deploy to Cloudflare) and records deploy status per commit.
5. **Keeps operating**: scheduled drip publishing via the Fanout scheduler, auto-verified GSC property (we control DNS → TXT verification) feeding the rank tracker, deploy/failure notifications, and a SerMaStr context provider so "how's the new site doing" is answerable in chat.

**Manual gates, deliberately:** theme preview approval before provisioning, and page review before first publish on local business sites. **Info sites auto-publish** (owner ruling 2026-07-17) — both the initial content plan and the scheduled drip run without a review gate.

## 3. Goals / non-goals

**Goals**
- Design-to-live-site with no manual repo/hosting/DNS clicking (beyond a one-time registrar NS change per domain).
- Reuse every existing content engine unchanged — this module is **assembly + delivery**, not a new writer.
- One site = one GitHub repo (private) = one Cloudflare project. Boring, inspectable, recoverable — the repo *is* the site; if the module dies, the sites keep running.
- Idempotent, resumable provisioning (every step re-runnable; partial failure never leaves a half-site the module can't see).
- Ship dark behind `website_builder_enabled`.

**Non-goals (v1)**
- A visual page editor / drag-drop builder. Design changes happen in Claude Design → re-upload → theme recompile.
- E-commerce, forms backends beyond the Web3Forms contact form (§4.8), auth, or any dynamic server rendering. Sites are static output.
- Domain **purchase** automation. Decided flow (owner 2026-07-17): domains are bought manually at **Namecheap** and their nameservers pointed at Cloudflare — that NS change is the one manual step per site; the module handles everything from the zone onward (DNS records, domain attach, GSC TXT verify).
- Multi-language sites.
- Migrating existing client websites into the module (import is a later phase, if ever).

---

## 4. Architecture — the factory line

```
Claude Design export
      │  (upload zip/HTML or paste URL)
      ▼
[1] THEME COMPILE  (website_theme_compile job, Claude Sonnet)
      tokens.json + Layout.astro + section components + sample page
      → preview HTML in storage bucket → user approves
      ▼
[2] PROVISION  (website_provision job)
      GitHub: repo from ar-site-template → commit theme + site.config.json + secrets
      Cloudflare: create project → first deploy → staging URL
      (later: attach custom domain + DNS record)
      ▼
[3] CONTENT  (existing engines)
      local:  Plan Silo + GBP → nlp-api pages → HTML→MD
      info:   Keyword Research / Fanout plan → Blog Writer → MD
      ▼
[4] PUBLISH  (website_page_publish job, one per page, staggered)
      commit content-collection entry → GitHub Actions: astro build →
      wrangler deploy → Cloudflare serves
      ▼
[5] OPERATE
      drip posts (Fanout scheduler) · GSC auto-verify → rank tracker ·
      deploy notifications · SerMaStr context
```

### 4.1 The `ar-site-template` repo (hand-built once, Phase 0)

A single Astro template repo owned by the agency GitHub org, used as a GitHub **template repository** (`POST /repos/{template}/generate`). It contains everything that is *the same for every site*, so the per-site theme compile only has to produce the *design*:

- Astro 5, content collections (`pages`, `posts`, `services`, `locations`) with zod-validated frontmatter (title, description, slug, JSON-LD payload, draft flag, publish date).
- SEO plumbing baked in: `@astrojs/sitemap`, robots.txt, canonical tags, OG/Twitter meta from frontmatter, RSS for `posts`, 404 page, redirects file.
- A **theme contract**: the template imports `src/theme/` (tokens.css + components) — the compile step only ever writes inside `src/theme/` and `site.config.json`. Template upgrades (dependency bumps, new SEO features) can then be rolled to all site repos mechanically without touching any site's design.
- `site.config.json`: site name, type (`local_business` | `informational`), nav structure, business block (NAP/hours from GBP, injected at provision and refreshed on GBP change), analytics id slot.
- A GitHub Actions workflow: on push to `main` → `astro build` → `wrangler deploy` (Cloudflare). Secrets (`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`) are set per-repo by the provisioner via the GitHub API.
- No Tailwind / no CSS framework: the theme compiler emits plain scoped CSS + custom properties from `tokens.json`. (Claude Design exports often use utility CSS; the compiler normalizes to tokens so the template stays dependency-light and diffs stay readable.)

### 4.2 Hosting path decision (recommendation)

Two viable Cloudflare paths:

| | A: Pages git-integration (CF builds on push) | **B (recommended): GitHub Actions build + `wrangler` deploy to Workers static assets** |
|---|---|---|
| First-time setup | Requires an interactive dashboard OAuth connection of the GitHub account; project-with-git-source creation is not cleanly API-automatable | 100% API-automatable (create project, set repo secrets, push) |
| Build environment | Cloudflare's, less controllable | Ours (Actions), same toolchain as local |
| Product direction | Pages is feature-frozen; Cloudflare's forward path is Workers static assets | Aligned with Cloudflare's current direction |
| Deploy status | CF webhooks/API | Actions run status via GitHub API (already have the MCP-style access pattern; backend uses REST) |

**Decided: B — Workers static assets (owner ruling 2026-07-17).** Fully automatable end-to-end, no per-account dashboard step, and the deploy log lives in the site repo's Actions tab where it's debuggable. Pages remains a fallback if Workers static-asset limits bite (they shouldn't for static marketing/blog sites). Runs on the owner's **existing Cloudflare account** (same ruling).

### 4.3 Design ingestion & theme compile (the risky part, so it's constrained)

**Input:** whatever Claude Design exports — v1 accepts (a) an uploaded `.zip` / `.html` file into the existing `files` upload path, or (b) a pasted URL the backend fetches. Multi-page designs are accepted; the compiler treats the first page as the primary layout and additional pages as section sources.

**Compile (LLM-assisted, but narrow):** one `website_theme_compile` job (Claude Sonnet, `website_theme_model`) that does **extraction + translation, not free design**:

1. Deterministic pre-pass: parse the HTML, inline/download assets (fonts, images → `public/`), strip scripts, extract the raw palette/typography.
2. LLM pass: map the design into the **fixed theme contract** — `tokens.json` (colors, type scale, spacing, radii), `Layout.astro` (header/nav/footer), and a bounded set of section components (`Hero`, `ServiceCard`, `ReviewStrip`, `CtaBand`, `ArticleCard`, `ContactBlock`…), each with named content slots. The LLM never invents page copy and never emits `<script>`.
3. Deterministic post-checks: valid Astro/HTML, no external script/style URLs (self-contained), all tokens referenced exist, sample page renders.
4. Output: theme files stored (storage bucket + `website_themes` row) and a **static preview** (sample page with placeholder content) rendered to the bucket → signed URL shown in the UI. **User approves the preview before provisioning** — this is the fidelity gate; a bad compile costs a re-run, never a bad live site.

Themes are versioned (`website_themes.version`); recompiling a re-uploaded design creates a new version, and applying it to a live site is an explicit action (commit → redeploy). **Themes are reusable across sites and industries** (owner ruling 2026-07-17): the theme library is industry-agnostic, so the efficient steady-state is a handful of approved house themes where a new site is often just a token swap (colors, logo, fonts) on an existing theme — a fresh Claude Design session is for genuinely custom builds, not every site.

### 4.4 Content mapping

| Site type | Site plan source | Page writer | Format committed |
|---|---|---|---|
| Local business | Plan Silo (services, neighborhoods, target cities) + fixed pages (home/about/contact) + GBP facts | nlp-api `/generate-page` (existing, incl. scoring/reopt) | HTML→Markdown (existing converter) + frontmatter carrying meta/JSON-LD |
| Informational | Keyword Research clusters / Fanout content plan | Blog Writer five-module pipeline (native Markdown) | Markdown + frontmatter |

Generated content **also** persists where it already does (`local_seo_pages`, `runs`) — the website row links to those records, so scoring/reoptimization keep working; a reoptimized page can be re-published to the repo (new commit) from the same UI. `website_pages` maps content → repo path + commit sha + route + status (`draft | queued | published | failed`), and per-item publish jobs are **id-based idempotent** (a retry never duplicates a commit for an already-published sha), mirroring the syndication module's contract.

Home, about, and contact pages don't go through this pipeline at all — they're a different kind of page with their own generator (§4.6). For info sites, the home is a deterministic template (latest posts, categories) needing no LLM.

### 4.5 Business facts & the no-GBP path

GBP is **one source of business facts, not a dependency** — and site-before-GBP is likely the *default* order for this module: a brand-new business (e.g. a LeadOff market-entry play) needs the website first, because GBP verification goes smoother when the listing can point at a live site. So the design is:

**Precedence: manual entry > GBP > absent.** The template's `site.config.json` business block (name, address, phone, hours, service areas, categories) is populated at provisioning with per-field-group provenance (`source: "user" | "gbp"`, mirroring how brand voice tracks user-authored vs scanned text). In the creation wizard, a client with a GBP on file pre-fills the block from it; a client without one gets a **business-facts form** as a first-class wizard step (only the facts that exist — everything is optional except the business name). Nothing downstream cares where the facts came from: the writer still never invents NAP, it just reads the config.

**Every fact-consuming surface degrades by section** (the theme contract treats sections as optional slots, so a missing section is a no-op, not a broken layout):

- **NAP + LocalBusiness JSON-LD** — emitted from whatever facts exist. A service-area business, or one with no address yet, suppresses the street address and leans on `areaServed`.
- **Review strip** — not rendered until reviews exist.
- **Hours / categories** — render if present, omit if not.
- **Core-pages generator (§4.6)** — its prompts receive whatever facts + ICP/differentiators are available; with no reviews the home page gets a proof-free hero (services + service area + positioning) rather than fabricated social proof.

**The content engines are GBP-independent anyway.** Plan Silo's inputs are a typed seed service + area; GBP's service area is only one of four multi-city discovery sources (manual `target_cities`, site place-names, and Overpass nearby-cities still work). The nlp-api generator, scoring, and reoptimization don't touch GBP. The auto brand-voice/ICP scans already skip gracefully when a client has neither website nor GBP — and once this module deploys the site, the client *has* a website, so those scans become possible where they previously had nothing to analyze.

**When the GBP arrives later**, the existing paste-a-link/resolve flow captures it on the client, and the module refreshes the business block on the next config re-commit — but under the precedence rule GBP **fills gaps and never silently overwrites user-entered facts** (same philosophy as the auto-scans never overriding user-authored voice/ICP). Reviews start flowing into the review strip, and the loop closes: the live site gives the new GBP something to link to, and the geo-grid then measures whether the market entry worked.

### 4.6 Core-pages generator (home / about / contact)

The three fixed pages every local business site needs are a **different kind of page** from everything the suite generates today: they don't compete in a SERP, so the nlp-api `/generate-page` pipeline is the wrong shape for them — it would burn a DataForSEO SERP pull on pages with no target query and score them against a ranking rubric that doesn't apply. Instead, a lighter **core-pages generator**: one new nlp-api endpoint (`POST /generate-core-page`, `page_kind ∈ {home, about, contact}`) that reuses the existing brand-voice/ICP prompt helpers (`_build_brand_voice_text`/`_build_icp_text`) but skips SERP analysis and the 8-engine scoring/reopt loop entirely.

**Structured section output, not article HTML.** Service/location pages are long-form articles; these three are *assemblies of theme sections*. The generator returns JSON keyed to the theme contract's slots (hero, services grid, differentiators band, review strip, CTA band…), and each page commits as a **data-collection entry** the theme renders (`content_source: "composed"`) — not converted Markdown. That keeps the design mirror faithful and makes regeneration surgical: a facts change re-renders the deterministic parts without touching the LLM copy.

Per page:

- **Home** — inputs: the §4.5 business-facts block, the site plan's *selected* services (teasers link to real `/services/*` routes), reviews if any, ICP + differentiators, brand voice. The LLM writes hero/positioning/teaser copy into the slot structure; LocalBusiness JSON-LD is emitted deterministically from facts. No reviews → proof-free hero (§4.5).
- **About** — the trust/entity page, the most LLM-shaped of the three. The wizard gains an optional **"about facts"** free-text box (origin story, years in business, certifications, team — the user-authored brand guide often already carries this). The LLM writes the narrative in brand voice under the same hard rule as the ecommerce writer: **factual claims (license numbers, years, awards) come only from provided facts; missing facts land in a `content_gaps` report**, never invented. AboutPage/Organization JSON-LD deterministic.
- **Contact** — nearly zero LLM. NAP, hours table, service-area list, and the Web3Forms contact form (§4.8) are deterministic renders of the facts block; the map embed comes from the GBP place_id or the geocoded address. (The Google Maps iframe and the §4.8 third-party snippets are the sanctioned exceptions to the theme's "self-contained, no external scripts" rule.) The only generated text is a short intro blurb, batched into the same call rather than its own request. ContactPage JSON-LD deterministic.

**Mechanics:** one `website_core_pages` job generates all three at site setup (each individually regenerable afterward); it is freeze-gated like all content generation. Validation replaces scoring: required slots filled, length bounds, and a deterministic **facts-consistency check** that the output contains no NAP/claims absent from the facts block.

### 4.7 Imagery

A local business site without photos looks generated. Every hero, service card, and about section needs an image, sourced down this ladder (best trust signal first):

1. **GBP photos** — real storefront/jobsite photos already attached to the listing; the GBP enrichment path pulls them into a per-site media library. Strongest local trust signal, $0.
2. **Client uploads** — a media step in the wizard reusing the existing file-upload path (and `clients.logo_url` for the logo).
3. **AI-generated** (owner ruling 2026-07-17: include an image-generation API) — a provider-pluggable `image_gen` service fills whatever the ladder leaves empty. **Default: Gemini image generation ("Nano Banana")** — `GEMINI_API_KEY` is already on PLATFORM (AI-visibility engine), so no new vendor; **OpenAI** (`gpt-image-1`) as the config-switchable alternative (key also already provisioned); **Ideogram** optional behind a new key if text-in-image graphics are ever needed (`website_image_provider` config, mirroring the `report_llm` provider-selection pattern). Prompts are derived from the page context (service, area, brand palette from the theme tokens). **Owner ruling 2026-07-17: generated imagery may include realistic jobsite/work scenes** — functionally the same role stock photography plays today, so heroes and service cards can show the trade in action even when no real photos exist. Residual recommendation (overridable): keep fabricated **before/after "results" photos and fake team-member portraits** out — those function as proof of specific work rather than generic imagery. Real GBP photos still outrank generated ones on the ladder whenever they exist.

Mechanics: images land in the site repo's `public/` (Astro's asset pipeline handles responsive sizes at build), each with LLM-written alt text; `website_pages` slots record the image source (`gbp|upload|generated`) so a later real photo can replace a generated one surgically. Generation rides the existing job pattern (part of `website_core_pages` / per-page publish jobs, freeze-gated).

### 4.8 Launch kit & lead handling

Everything between "pages generated" and "site you'd hand a client," owned by the module so launches don't revert to manual fiddling. **Owner rulings 2026-07-17:** launch inputs are **a form filled out in the module**; analytics/GSC snippets are added **after the site is live** (a post-launch settings panel, not a wizard blocker); forms are handled by **Web3Forms**; calls most likely by **CallRail**, else a user-provided phone number.

- **Launch form (in-module):** logo/favicon (pre-filled from `clients.logo_url`), the §4.5 business facts, about facts (§4.6), form recipient email, phone setup (below). Deterministic **privacy policy / terms** pages render from templates with the business facts merged in — no LLM.
- **Post-launch settings panel:** GA4 snippet id, GSC (the module's DNS-TXT auto-verify — §8), CallRail snippet, and any other third-party tags — editable any time; each change is a config re-commit + redeploy, never a regeneration.
- **Forms — Web3Forms:** the contact form POSTs to Web3Forms using **one shared access key on the owner's account** (owner ruling 2026-07-17; per-site recipient routing handled via the form's recipient field). Static-site-friendly, no backend of ours. The earlier CF-Worker form idea is dropped. Follow-up (not v1): a webhook copy into the suite so lead volume is visible in-app — the module's own success metric, and the number that proves a LeadOff market entry worked.
- **Calls — CallRail via dynamic number insertion (owner ruling 2026-07-17, owner's account):** the phone block distinguishes **real number** (emitted in LocalBusiness JSON-LD and the GBP-consistent NAP, and rendered on-page as the default) from the **CallRail DNI snippet**, which swaps the displayed number at runtime — the standard local-SEO pattern so citations stay consistent while calls get attributed. The post-launch settings panel stores the per-site DNI snippet. No CallRail on a given site → the real number serves both roles.
- **Nav + internal linking:** header/footer nav generated from the site plan, with silo-aware internal links between service and location pages (the SEO structure Plan Silo already implies, rendered deterministically).
- **Launch checklist view:** a per-site checklist in the UI — domain active, GSC verified, form test submission received, legal pages present, images sourced — so "is it done" is a glance, not an audit.

The Maps iframe, Web3Forms endpoint, and CallRail/GA4 snippets are the **sanctioned exceptions** to the theme's self-contained rule; the theme compiler still strips everything else.

---

## 5. Data model (new tables, one migration)

- **`websites`** — id, `client_id` FK (**decided, owner 2026-07-17:** every site belongs to a client row — standalone info sites get a lightweight client, so freeze/notifications/rank-tracking rails all work unmodified), name, slug, `site_type` (`local_business|informational`), `theme_id`, `github_repo` (full name), `cf_project`, `staging_url`, `custom_domain`, `domain_status` (`none|pending_ns|active`), `status` (`draft|compiling|ready_to_provision|provisioning|live|error`), `config` JSONB, timestamps.
- **`website_themes`** — id, name, `source_kind` (`upload|url`), source ref, `version`, `tokens` JSONB, storage path (compiled files), `preview_path`, `status` (`compiling|ready|failed`), `approved_at`, error.
- **`website_pages`** — id, `website_id`, `route`, `title`, `content_source` (`local_seo_page|run|composed|static`), `source_id`, `repo_path`, `commit_sha`, `status`, `published_at`, error. Unique (`website_id`, `route`).
- **`website_deploys`** — id, `website_id`, `commit_sha`, `trigger` (`provision|publish|theme|manual`), `status` (`queued|building|success|failed`), `actions_run_id`, `url`, error, timestamps.

`async_jobs` types: `website_theme_compile`, `website_provision`, `website_core_pages` (§4.6), `website_page_publish`, `website_deploy_poll` (checks the Actions run + CF deployment for a pending `website_deploys` row; scheduler-driven, cheap). `website_page_publish`, `website_core_pages`, and site-plan generation join `FREEZE_GATED_JOB_TYPES`; provisioning/deploy-status jobs do not (observation vs output, same split as everywhere else).

## 6. API surface (`routers/websites.py`) & frontend

Backend services: `website_theme.py` (ingest + compile), `website_provision.py` (GitHub + Cloudflare orchestration), `website_content.py` (site plan → generation → publish queue), `website_deploy.py` (status), thin `github_api.py` + `cloudflare_api.py` clients (httpx, service-scoped tokens, no SDKs).

Routes (shape, not exhaustive): themes CRUD + compile + approve; websites CRUD; `POST /websites/{id}/provision`; site-plan build + review (`GET/POST /websites/{id}/plan`); publish selected pages; `POST /websites/{id}/domain` (attach + DNS + status); deploys list; per-page retry/republish.

Frontend: suite-level **`pages/Websites.tsx`** (sidebar entry; list + create wizard: client → type → design upload/URL or pick a house theme (§4.3) → theme preview/approve → launch form (business facts, about facts, media, form recipient, phone setup — §4.5/§4.6/§4.8) → provision → plan review → generate → publish) plus a per-site **post-launch settings panel** (analytics/GSC/CallRail snippets, §4.8) and **launch checklist view**, and a client-workspace **"Websites"** card filtered to that client. Deploy status chips poll `website_deploys`; the plan-review screen reuses the Plan Silo selection UX (checkboxes + bulk bar + `useBulkCreate` patterns).

## 7. Credentials & config

New env on `PLATFORM`: `GITHUB_SITES_TOKEN` — site repos live under the **`kssabraw` personal account** (owner ruling 2026-07-17, superseding the dedicated-org recommendation). Caveat that follows: a token able to *create* repos on a personal account is account-wide by nature, so it MUST be a **fine-grained PAT limited to the minimum permissions** (repo administration for create, contents, secrets, actions-read) and never granted more; it can technically see ar-tools, so treat it as a sensitive credential like the service-role key. `GITHUB_SITES_OWNER=kssabraw`, `CLOUDFLARE_API_TOKEN` (Workers + DNS edit on the owner's existing account), `CLOUDFLARE_ACCOUNT_ID`, `WEB3FORMS_ACCESS_KEY` (one shared key, owner's account), optionally `IDEOGRAM_API_KEY` (only if that provider is enabled — the default image provider reuses the existing `GEMINI_API_KEY`/OpenAI keys, §4.7). Config: `website_builder_enabled` (default False), `website_theme_model` (Sonnet), `website_image_provider` (`gemini|openai|ideogram`, default `gemini`), `website_publish_job_spacing_seconds` (reuse the bulk-stagger pattern), `website_template_repo`.

Repos are **private** (content is invisible until deployed; drafts never leak). The Cloudflare token in repo secrets is the standard Actions pattern; scope it to deploy-only.

## 8. Suite integration

- **Freeze Protocol:** frozen client → site content generation + publish blocked (`client_frozen`), deploys of already-committed content still allowed? **No** — publish jobs are gated; an emergency hotfix deploy is a manual GitHub action, outside the module.
- **Rank tracker / GSC:** on domain activation, create the DNS TXT verification via the CF API → verify a GSC domain property for the service account → the site auto-joins GSC ingest, rank tracking, GSC Research eligibility. This closes a loop no other module could: **we create the site, we measure the site.**
- **Notifications:** `website_deployed` (info), `website_deploy_failed` (warning), `website_provisioned` (info) through the shared service.
- **Fanout scheduler:** a third `content_type`-style destination — scheduled runs whose output publishes to a website (a `website_id` on the schedule) instead of / in addition to Docs. Additive divergence, same pattern as the existing `local_seo_page` branch.
- **SerMaStr / strategist:** a `websites` context provider (site list, deploy status, page counts, last publish) so chat can answer "is the new Plano site live yet".
- **Content Syndication:** a module-built site is a legitimate scan target like any other client site — no special casing needed (it has a sitemap because the template ships one).

## 9. Phasing

| Phase | Scope | Notes |
|---|---|---|
| **0 — Foundations** | Owner decisions (§12), creds provisioned, **`ar-site-template` built by hand** (the template is real engineering: theme contract, collections, SEO plumbing, deploy workflow), migration, config flags. One site deployed *manually* from the template end-to-end to prove the GitHub→Actions→Cloudflare line before any module code. | The manual dry run de-risks everything downstream. |
| **1 — Theme pipeline** | Upload/URL ingest → `website_theme_compile` → preview → approve. Theme library CRUD. | Testable in isolation (fixtures of real Claude Design exports). |
| **2 — Provision + deploy** | Repo-from-template, theme commit, secrets, CF project, first deploy, staging URL, `website_deploys` + poll job, custom domain + DNS attach. | Idempotent step machine; every step re-runnable. |
| **3 — Local business sites** | Site plan (Plan Silo + fixed pages + business facts), core-pages generator (§4.6, incl. the three prompt profiles), imagery ladder + `image_gen` service (§4.7), launch form + Web3Forms/phone setup + legal pages + checklist (§4.8), generate → HTML→MD → publish jobs, plan-review UI. | The nlp-api engine is reused unchanged for service/location pages; the core-pages endpoint is the one new generation surface. |
| **4 — Informational sites** | Content plan from Keyword Research/Fanout, Blog Writer runs → posts, categories/RSS/home, drip publishing via the Fanout scheduler. | Blog output is already Markdown — lightest content phase. |
| **5 — Operate & polish** | GSC auto-verify → rank tracker hookup, notifications, SerMaStr provider, theme re-apply/versioning UX, template-upgrade roll-out mechanism. | |

## 10. Risks & mitigations

- **Design→code fidelity** (the #1 risk): mitigated by the narrow theme contract (extract, don't design), deterministic pre/post passes, and the human preview gate. Accept that v1 fidelity is "faithful tokens + layout", not pixel-perfection; the user iterates in Claude Design, not in our UI.
- **Thin/doorway-site SEO risk**: mass-generated local pages are exactly what Google's scaled-content policies target. Mitigations already exist — the nlp-api scoring/reopt loop, Plan Silo's relevance gating — plus the human plan-review gate. Info-site drip cadence is throttled by the Fanout scheduler's existing gating. This is an agency-judgment surface, not a module-automation surface.
- **GitHub/Cloudflare API drift + rate limits**: thin clients, per-item staggered jobs (the suite's existing bulk pattern), and the repo-is-the-site property means the blast radius of API failure is "publish delayed", never "site down".
- **Secrets sprawl**: one deploy token per Cloudflare account (not per site), set as repo secrets by the provisioner; rotation = update secrets via API across repos (a listed follow-up script).
- **Contact forms / anything dynamic**: out of v1 except the Web3Forms contact form + the sanctioned third-party snippets (§4.8); scope creep here is the classic website-builder tarpit — the non-goals list is the defense.
- **AI imagery trust risk**: realistic jobsite scenes are allowed (owner ruling — the stock-photography role, §4.7); the recommended line is at fabricated before/after results and fake team portraits, and the GBP-photos-first ladder keeps real photos winning whenever they exist.

## 11. Cost

Hosting is ~$0 at the ruled scale of **~50 sites in year one** (owner, 2026-07-17): private repos are unlimited on a personal GitHub account, and Workers static-asset requests are free — the $5/mo Workers paid plan is a cheap safety valve if any dynamic pieces grow. Per-page LLM cost is the same as the existing generators (the only new generation surface is the core-pages endpoint (§4.6) — a few Claude calls per site, no SERP spend). Theme compile ≈ one Sonnet call per design version. Image generation (§4.7) is cents per image — well under $1 per site at a typical 10–20 images, and $0 when GBP photos/uploads cover the ladder. Web3Forms/CallRail ride the agency's existing accounts. The only new spend surface is negligible (GitHub/CF API calls are free).

---

## 12. Decision log & remaining inputs

**Resolved (owner rulings 2026-07-17):**

| # | Decision | Ruling |
|---|---|---|
| 1 | GitHub home for site repos | The **`kssabraw`** personal account (supersedes the dedicated-org recommendation; see the §7 token-scoping caveat) |
| 2 | Cloudflare account | The owner's **existing account** |
| 3 | Pages vs Workers | **Workers static assets** via Actions + wrangler (§4.2) |
| 4 | Domains | Bought manually at **Namecheap**, nameservers pointed to Cloudflare (§3) |
| 5 | Info sites are clients | **Yes** — lightweight `clients` row per standalone info site (§5) |
| 6 | Publish gates | Local sites: human plan/page review before first publish. **Info sites: auto-publish**, including the drip (§2) |
| 7 | Locked-decision sign-off | **OK** — website is an additive Blog Writer publish destination (header note) |
| 8 | Volume | **~50 sites in year one** (§11) |
| 9 | Web3Forms | Owner's account, **one shared access key** (§4.8; supersedes the per-site-keys recommendation) |
| 10 | CallRail | Owner's account, **dynamic number insertion** snippet per site (§4.8) |
| 11 | Image generation | Include it — default Gemini/Nano Banana, OpenAI alternative, Ideogram optional (§4.7); **realistic jobsite scenes allowed** (stock-photography role) |
| 12 | Launch inputs | A form filled out in the module; analytics/GSC snippets added post-launch (§4.8) |
| 13 | Themes | **Reusable across industries** (§4.3) |

**Remaining inputs (not blocking Phase 0 — needed at the phase indicated):**

1. **A real Claude Design export sample** (owner: later) — needed **before Phase 1** as the theme-compiler fixture; its format (single HTML / multi-page / zip / share URL) finalizes the ingest UI.
2. **Pilot clients** (owner: later) — one with a GBP and one without (the §4.5 path), needed **before Phase 3** end-to-end validation.
3. **Core-pages prompt copy** — three small prompt profiles (home / about / contact blurb, §4.6); an owner-involved writing task **in Phase 3**, per the "things to ask" convention.

Phase 0 is unblocked: all infrastructure decisions are made.
