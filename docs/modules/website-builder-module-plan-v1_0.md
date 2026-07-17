# Website Builder — Module Plan v1.0

**Status:** Proposed (not built). Planning document only — nothing in this doc is implemented.
**Owner:** Kyle
**Last updated:** 2026-07-17
**Relationship to other work:** consumes the Local SEO generator (nlp-api), the Blog Writer pipeline, Plan Silo, GBP data, Keyword Research/Fanout, and the shared scheduler/notifications rails. Gives the suite its first true "publish to a live site we control" destination (adjacent to — but not reversing — the locked "publish = Google Doc, CMS-ready later" decision; see §12 Q8).

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
   - **Local business site**: site plan from Plan Silo + GBP → home, `/services/<slug>`, `/locations/<slug>`, about, contact (+ optional `/blog`). Business facts and LocalBusiness/Service JSON-LD come from GBP — the writer never invents NAP.
   - **Informational site**: content plan from Keyword Research / Fanout → `/ [category] / [post]` articles from the Blog Writer pipeline, plus magazine home, category indexes, RSS, author/about pages.
   - Content is committed to the repo as **content-collection Markdown with frontmatter** (blogs are native Markdown; local pages converted via the existing HTML→Markdown path, JSON-LD carried in frontmatter and injected by the layout).
4. **Deploys on every content change** (build in GitHub Actions → deploy to Cloudflare) and records deploy status per commit.
5. **Keeps operating**: scheduled drip publishing via the Fanout scheduler, auto-verified GSC property (we control DNS → TXT verification) feeding the rank tracker, deploy/failure notifications, and a SerMaStr context provider so "how's the new site doing" is answerable in chat.

**Manual gates, deliberately:** theme preview approval before provisioning, and page review before first publish (configurable to auto-publish for info sites once trusted).

## 3. Goals / non-goals

**Goals**
- Design-to-live-site with no manual repo/hosting/DNS clicking (beyond a one-time registrar NS change per domain).
- Reuse every existing content engine unchanged — this module is **assembly + delivery**, not a new writer.
- One site = one GitHub repo (private) = one Cloudflare project. Boring, inspectable, recoverable — the repo *is* the site; if the module dies, the sites keep running.
- Idempotent, resumable provisioning (every step re-runnable; partial failure never leaves a half-site the module can't see).
- Ship dark behind `website_builder_enabled`.

**Non-goals (v1)**
- A visual page editor / drag-drop builder. Design changes happen in Claude Design → re-upload → theme recompile.
- E-commerce, forms backends beyond a simple contact form (Cloudflare Worker → email/notification), auth, or any dynamic server rendering. Sites are static output.
- Domain **purchase** automation (registrar APIs are patchy; v1 assumes the domain exists in the Cloudflare account or gets a manual NS step).
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

**Recommendation: B.** Fully automatable end-to-end, no per-account dashboard step, and the deploy log lives in the site repo's Actions tab where it's debuggable. Pages remains a fallback if Workers static-asset limits bite (they shouldn't for static marketing/blog sites).

### 4.3 Design ingestion & theme compile (the risky part, so it's constrained)

**Input:** whatever Claude Design exports — v1 accepts (a) an uploaded `.zip` / `.html` file into the existing `files` upload path, or (b) a pasted URL the backend fetches. Multi-page designs are accepted; the compiler treats the first page as the primary layout and additional pages as section sources.

**Compile (LLM-assisted, but narrow):** one `website_theme_compile` job (Claude Sonnet, `website_theme_model`) that does **extraction + translation, not free design**:

1. Deterministic pre-pass: parse the HTML, inline/download assets (fonts, images → `public/`), strip scripts, extract the raw palette/typography.
2. LLM pass: map the design into the **fixed theme contract** — `tokens.json` (colors, type scale, spacing, radii), `Layout.astro` (header/nav/footer), and a bounded set of section components (`Hero`, `ServiceCard`, `ReviewStrip`, `CtaBand`, `ArticleCard`, `ContactBlock`…), each with named content slots. The LLM never invents page copy and never emits `<script>`.
3. Deterministic post-checks: valid Astro/HTML, no external script/style URLs (self-contained), all tokens referenced exist, sample page renders.
4. Output: theme files stored (storage bucket + `website_themes` row) and a **static preview** (sample page with placeholder content) rendered to the bucket → signed URL shown in the UI. **User approves the preview before provisioning** — this is the fidelity gate; a bad compile costs a re-run, never a bad live site.

Themes are versioned (`website_themes.version`); recompiling a re-uploaded design creates a new version, and applying it to a live site is an explicit action (commit → redeploy). Info sites can **share a theme** across sites (theme library); a local business site's theme is typically its own.

### 4.4 Content mapping

| Site type | Site plan source | Page writer | Format committed |
|---|---|---|---|
| Local business | Plan Silo (services, neighborhoods, target cities) + fixed pages (home/about/contact) + GBP facts | nlp-api `/generate-page` (existing, incl. scoring/reopt) | HTML→Markdown (existing converter) + frontmatter carrying meta/JSON-LD |
| Informational | Keyword Research clusters / Fanout content plan | Blog Writer five-module pipeline (native Markdown) | Markdown + frontmatter |

Generated content **also** persists where it already does (`local_seo_pages`, `runs`) — the website row links to those records, so scoring/reoptimization keep working; a reoptimized page can be re-published to the repo (new commit) from the same UI. `website_pages` maps content → repo path + commit sha + route + status (`draft | queued | published | failed`), and per-item publish jobs are **id-based idempotent** (a retry never duplicates a commit for an already-published sha), mirroring the syndication module's contract.

Home pages get a dedicated composer: for local sites, assembled from GBP + services + reviews into the theme's section components (one nlp-api call with a home-page prompt profile — a v1 prompt-design task, see §16 Q9); for info sites, the home is a deterministic template (latest posts, categories) needing no LLM.

---

## 5. Data model (new tables, one migration)

- **`websites`** — id, `client_id` FK (see §12 Q5 — recommendation: every site belongs to a client row, creating a lightweight client for standalone info sites so freeze/notifications/rank-tracking rails all work), name, slug, `site_type` (`local_business|informational`), `theme_id`, `github_repo` (full name), `cf_project`, `staging_url`, `custom_domain`, `domain_status` (`none|pending_ns|active`), `status` (`draft|compiling|ready_to_provision|provisioning|live|error`), `config` JSONB, timestamps.
- **`website_themes`** — id, name, `source_kind` (`upload|url`), source ref, `version`, `tokens` JSONB, storage path (compiled files), `preview_path`, `status` (`compiling|ready|failed`), `approved_at`, error.
- **`website_pages`** — id, `website_id`, `route`, `title`, `content_source` (`local_seo_page|run|composed|static`), `source_id`, `repo_path`, `commit_sha`, `status`, `published_at`, error. Unique (`website_id`, `route`).
- **`website_deploys`** — id, `website_id`, `commit_sha`, `trigger` (`provision|publish|theme|manual`), `status` (`queued|building|success|failed`), `actions_run_id`, `url`, error, timestamps.

`async_jobs` types: `website_theme_compile`, `website_provision`, `website_page_publish`, `website_deploy_poll` (checks the Actions run + CF deployment for a pending `website_deploys` row; scheduler-driven, cheap). `website_page_publish` and site-plan generation join `FREEZE_GATED_JOB_TYPES`; provisioning/deploy-status jobs do not (observation vs output, same split as everywhere else).

## 6. API surface (`routers/websites.py`) & frontend

Backend services: `website_theme.py` (ingest + compile), `website_provision.py` (GitHub + Cloudflare orchestration), `website_content.py` (site plan → generation → publish queue), `website_deploy.py` (status), thin `github_api.py` + `cloudflare_api.py` clients (httpx, service-scoped tokens, no SDKs).

Routes (shape, not exhaustive): themes CRUD + compile + approve; websites CRUD; `POST /websites/{id}/provision`; site-plan build + review (`GET/POST /websites/{id}/plan`); publish selected pages; `POST /websites/{id}/domain` (attach + DNS + status); deploys list; per-page retry/republish.

Frontend: suite-level **`pages/Websites.tsx`** (sidebar entry; list + create wizard: client → type → design upload/URL → theme preview/approve → provision → plan review → generate → publish) and a client-workspace **"Websites"** card filtered to that client. Deploy status chips poll `website_deploys`; the plan-review screen reuses the Plan Silo selection UX (checkboxes + bulk bar + `useBulkCreate` patterns).

## 7. Credentials & config

New env on `PLATFORM`: `GITHUB_SITES_TOKEN` (fine-grained PAT or GitHub App for a **dedicated sites org** — repo create/contents/secrets/actions-read only, NOT the ar-tools repo), `GITHUB_SITES_ORG`, `CLOUDFLARE_API_TOKEN` (Workers/Pages + DNS edit, scoped to the sites account), `CLOUDFLARE_ACCOUNT_ID`. Config: `website_builder_enabled` (default False), `website_theme_model` (Sonnet), `website_publish_job_spacing_seconds` (reuse the bulk-stagger pattern), `website_template_repo`.

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
| **3 — Local business sites** | Site plan (Plan Silo + fixed pages + GBP), home-page composer prompt, generate → HTML→MD → publish jobs, plan-review UI. | The nlp-api engine is reused unchanged; new work is assembly. |
| **4 — Informational sites** | Content plan from Keyword Research/Fanout, Blog Writer runs → posts, categories/RSS/home, drip publishing via the Fanout scheduler. | Blog output is already Markdown — lightest content phase. |
| **5 — Operate & polish** | GSC auto-verify → rank tracker hookup, notifications, SerMaStr provider, theme re-apply/versioning UX, template-upgrade roll-out mechanism. | |

## 10. Risks & mitigations

- **Design→code fidelity** (the #1 risk): mitigated by the narrow theme contract (extract, don't design), deterministic pre/post passes, and the human preview gate. Accept that v1 fidelity is "faithful tokens + layout", not pixel-perfection; the user iterates in Claude Design, not in our UI.
- **Thin/doorway-site SEO risk**: mass-generated local pages are exactly what Google's scaled-content policies target. Mitigations already exist — the nlp-api scoring/reopt loop, Plan Silo's relevance gating — plus the human plan-review gate. Info-site drip cadence is throttled by the Fanout scheduler's existing gating. This is an agency-judgment surface, not a module-automation surface.
- **GitHub/Cloudflare API drift + rate limits**: thin clients, per-item staggered jobs (the suite's existing bulk pattern), and the repo-is-the-site property means the blast radius of API failure is "publish delayed", never "site down".
- **Secrets sprawl**: one deploy token per Cloudflare account (not per site), set as repo secrets by the provisioner; rotation = update secrets via API across repos (a listed follow-up script).
- **Contact forms / anything dynamic**: out of v1 except a single optional CF Worker form handler in the template; scope creep here is the classic website-builder tarpit — the non-goals list is the defense.

## 11. Cost

Hosting is ~$0 (private GitHub repos on the org plan, Cloudflare free tier covers static sites/Workers at this scale). Per-page LLM cost is the same as the existing generators (this module adds no new writer). Theme compile ≈ one Sonnet call per design version. The only new spend surface is negligible (GitHub/CF API calls are free).

---

## 12. Open questions for the owner (blocking Phase 0)

1. **GitHub home for site repos** — a dedicated org (recommended: keeps the sites token away from ar-tools) vs the existing account? Org name?
2. **Cloudflare account** — existing agency account or a dedicated one? Confirm API token can be scoped to Workers + DNS on it.
3. **Pages vs Workers static assets** — recommendation is Workers static assets via Actions + wrangler (§4.2); confirm.
4. **Claude Design export format you actually get** — single-page HTML, multi-page, zip, shareable URL? (Determines the ingest UI; the plan accepts upload + URL, but a real export sample is needed as the Phase 1 fixture.)
5. **Are info sites clients?** Recommendation: yes — create a lightweight `clients` row per standalone info site so freeze/notifications/rank/GSC rails work unmodified. Alternative (a client-less `websites` row) forks every rail. Confirm.
6. **Domains** — who buys them, and are they (or will they be) on Cloudflare DNS? v1 assumes zone-on-Cloudflare with a manual registrar NS step; domain purchase automation is out.
7. **Publish gates** — local sites: human reviews the plan + pages before first publish (assumed yes). Info sites: auto-publish drip once trusted, or always reviewed?
8. **Locked-decision sign-off** — the roadmap locks the Blog Writer's publish destination as Google Doc ("CMS-ready later"). This module is the "later": adding *website* as an additional destination is additive, not a reversal — but it touches a locked line, so explicit sign-off.
9. **Home-page composer copy** — the local-site home page needs a prompt profile (hero copy, service teasers, review highlights from GBP). Per the "things to ask" convention: exact prompt copy is an owner-involved design task in Phase 3.
10. **Volume expectation** — roughly how many sites in year one, and posting cadence per info site? (Sanity-checks the free-tier assumption and the job-stagger tuning; nothing in the design breaks at 10× but the answer shapes defaults.)
