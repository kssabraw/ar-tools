# AR Tools — Handoff

## ⏩ Update — 2026-06-30 · **`main` merged into the SerMaStr branch + first reconciliation** (latest, on branch `claude/unified-keyword-portal-m82e68` / PR #166)

`origin/main` was **merged into `claude/unified-keyword-portal-m82e68`** (the branch was 29 ahead / 24 behind with overlapping work — main had shipped real Asana (#170), Maps alerting (#182, `maps_alerts`), brand alerting (#186), and the intel subsystem (`*_intel`), while this branch had only *designed* those). Merge resolved 4 conflicts (CLAUDE.md, HANDOFF.md, `ClientWorkspace.tsx`, `job_worker.py`); the `audit_runs` migration's stale `async_jobs` CHECK block was already removed and a union migration (`…220000_async_jobs_audit_jobtypes`) is the last word. Frontend `tsc -b` clean, all branch tests green. Branch is now 0 behind main.

**Reconciliation done (build on main's real services, not the branch's parallel designs):**
1. **Executor → Asana** (Phase-4 PR-B): approving a plan now hands every `assigned` action to **main's** `asana_service`. New `services/engagement_asana.py` (`push_assigned_actions` + the `engagement_asana_push` async job): for each approved `assigned` action with no task yet, it resolves the client's mapped project (`asana_client_projects`), routes to the team member whose **role** matches `assignee_role` (new `asana_team_members.role` column), creates an Asana task (in the current-month section if it exists), and stamps `strategy_actions.asana_task_id`. Best-effort — Asana unconfigured / no project mapping leaves actions `assigned` for a human, recording an `asana_skipped`/`asana_task_created` `execution_events` row. `engagement_executor.approve_plan` enqueues it off the request path. Migration `20260629230000_engagement_asana_push` (role column + `engagement_asana_push` job type) **applied live**. 10 unit tests. *(Outbound only; Asana→action two-way status sync is a follow-up.)*
2. **Strategy Engine ⟵ reopt_planner (single source of truth):** extracted a non-persisting `reopt_planner.gather_actions(client_id)` from `build_plan` (reads `rank_alerts` + `maps_alerts` + every intel signal: GBP/review/relevance/content/backlink/SoLV). `strategy_engine` now **delegates organic + Maps** to it via `_reopt_actions` + a `reopt_to_action` mapper (preserving main's cross-tier `sort` as `priority`), replacing the branch's thin re-derivation from raw `maps_scan_results`. The LLM leg still derives from `brand_mention_history` (brand alerts are notification-only — no queryable table to fold). Audit readers unchanged.

**Reconciliation — second pass (all four merge-overlap items now resolved):**
3. **Brand alerting → LLM reader:** `brand_alerts.py` is **notification-only** (no queryable table — it diffs the latest two scans on the fly), so there were no "rows" to consume. Instead `strategy_engine._llm_actions` now **reuses brand_alerts' diff logic** (`index_batch` + `detect_changes` + `_previous_batch_id`) via a pure `build_llm_actions`, so the plan surfaces the SAME regressions the brand-alert notifications fire on: `llm_misinfo` (critical — AI stated wrong business info), `llm_regression` (warning — lost visibility on ≥1 engine since last scan), and the standing `llm_content_gap` (invisible across every engine). Was previously a hand-rolled absolute-invisibility derivation.
4. **backlink_gap vs backlink_intel — complementary, both kept:** these are NOT duplicates. `backlink_intel` (main) computes the *authority-magnitude* gap (DR / referring-domain **counts** vs competitor medians) and its docstring explicitly defers *"the specific domains competitors have that the client lacks… a follow-up."* The branch's `backlink_gap.py` audit **is** that follow-up (the per-domain **prospect list** via the heavier `referring_domains/live` endpoint). They were colliding on `kind="backlink_gap"`; the audit action's kind is now **`backlink_prospects`** so both coexist as complementary plan signals (authority magnitude + the concrete domains to pursue). `backlink_gap` stays the engagement-audit entry point.

**Phase 4 · PR-C — internal-linking analyzer + WordPress injector (built):** `services/internal_linking.py` finds topical internal-link opportunities across a client's pages (a page whose body text mentions another page's title/keyword phrase, where no link exists yet — guardrails: never self-link, skip already-linked targets, ≤`internal_link_max_per_page` new links/page, ≤`internal_link_max_inbound_per_target` inbound/target, anchors ≥`internal_link_min_anchor_words` words, bs4 so boilerplate/existing `<a>` are skipped). **Inventory + content** come from the **WordPress REST API** when app-password creds are set (`wordpress_publish.list_content`, also the write path), else a **sitemap + ScrapeOwl crawl** (`site_page_index.discover_site_urls` + `website_scraper.scrapeowl_fetch`, recommend-only). Each opportunity is stored as an `internal_link_edits` row with its **own approve/deny lifecycle** (migration `20260630120000`) — because injecting a link mutates a live site, the analyzer **notifies** the team (`notifications.emit`, kind `internal_links`) and a **human approves/denies each edit**; only then does the injector write it. **Injector** (`apply_approved_edits`, WordPress only): re-fetches each post fresh, injects approved links via `inject_link_html` (bs4), writes back with `wordpress_publish.update_post_content` (**preserves published status** — gated), marks the edit `applied`, records an `internal_links_applied` `execution_events` row + the wp-admin edit link. Async jobs `internal_link_analyze` / `internal_link_apply` (constraint widened, **applied live**). API `routers/internal_linking.py` (analyze / list / approve / deny / apply); frontend `pages/InternalLinks.tsx` + workspace **Internal Links** card (route `clients/:id/internal-links`) — suggestions grouped by source page, per-edit Approve/Deny, "Apply N approved" (WP), status polling. Config: `internal_link_max_per_page`/`_max_inbound_per_target`/`_min_anchor_words`/`_wp_max_pages`/`_crawl_max_pages`. 13 pure-helper unit tests. **Note:** per the user's steer this is NOT auto-executed — it's a notify→human-approve→inject flow (more conservative than the design's autonomous default, because it edits a live site). Keyword-enrichment of anchor candidates (beyond page titles) is a deliberate follow-up.

**Still open:** Phase 4 PR-D (consolidated engagement report).

---

## ⏩ Update — 2026-06-29 · **Managed engagement + "SerMaStr" Strategy Engine — build started** (on branch `claude/unified-keyword-portal-m82e68` / PR #166 — NOT yet on `main`)

The connective layer from `docs/managed-engagement-and-strategy-engine-design-v1_0.md`
(the full design) is now being **built**, on branch `claude/unified-keyword-portal-m82e68`
(**PR #166**). The Phase-1 build plan is `docs/managed-engagement-phase-1-build-plan-v1_0.md`.
**Recommend-only so far — no autonomous execution, no Asana, no monitor yet.**

**Shipped (code on the branch):**
- **Unified Keyword Portal** (Phase 1 · PR1) — `POST /clients/{id}/keyword-portal/add` fans
  one keyword list out to organic / Maps / brand, deduped, with first-scan kickoff (Maps
  "added but blocked" when the grid isn't configured; brand scans only the new keyword ids).
  `services/keyword_portal.py` + `routers/keyword_portal.py` + `brand_service.add_keywords`;
  frontend `pages/KeywordPortal.tsx` + workspace **Add Keywords** card. 10 unit tests.
- **Engagement spine + Strategy Engine v1** (Phase 2 · PR-A/B/C) — the `engagements`
  lifecycle state machine (`services/engagement_service.py`, pure `can_transition`),
  `services/strategy_engine.py` (generalizes `reopt_planner` cross-module: organic reuses
  it; Maps reads latest-scan weak areas; LLM reads latest-scan invisible keywords → ONE
  unified recommend-only plan), `routers/engagements.py` + `routers/strategy.py`
  (`POST /engagements/{id}/plan/refresh`, `GET …/plan`); frontend `pages/StrategyPlan.tsx`
  + workspace **Strategy** card. 13 unit tests.
- **Onboarding wizard + approval gate** (Phase 1 · PR3) — `pages/OnboardingWizard.tsx`
  (begin engagement → approve brand voice + ICP → add targets), `onboarding_readiness` +
  the `onboarding→intake` transition **gated** on voice + ICP approved; workspace
  **Onboarding** card.
- **Phase 3 — audit modules** (engagement-scoped `audit_runs`, **wired into the loop**):
  **site/technical** (`services/site_audit.py` — pure parse/score of DataForSEO OnPage
  `checks` → typed severity-scored issues; best-effort instant-pages crawl seeded from
  sitemap discovery, capped at `site_audit_max_pages`), **backlink-gap**
  (`services/backlink_gap.py` — DataForSEO Backlinks: client profile + referring domains
  linking to ≥N competitors but not the client, capped at top-N), and **local-citation**
  (`services/citation_audit.py` — a curated target-directory checklist checked via the
  existing DataForSEO SERP; gap = "where you need to be"). `routers/audits.py`
  (`POST …/audits/{site|backlinks|citations}`, `GET …/audits`); async jobs `site_audit` /
  `backlink_audit` / `citation_audit`. Config: `site_audit_max_pages`,
  `backlink_max_competitors`, `citation_directories`. Pure parsers unit-tested.
- **Audits → strategy + UI** — entering the `auditing` stage **auto-enqueues all three
  audits** (`engagement_service.transition`, best-effort); the Strategy Engine's audit
  reader turns the latest `audit_runs` into plan actions — `technical_fix` (**cross**) /
  `backlink` (**organic**) / `citation` (**maps**) — alongside the organic/Maps/LLM signals
  in the one unified plan (new `cross` module; `build_plan` threads `engagement_id`). The
  Strategy page (`pages/StrategyPlan.tsx`) has an **Audits** panel (latest run per kind +
  summary) and a **Run audits** button that polls while runs are in flight.

**Live DB:** migrations **applied to the live project** (`wvcthtmmcmhkybcesirb`) via the
Supabase MCP: `engagements_and_strategy` (`engagements`, `strategy_plans`,
`strategy_actions`) and `audit_runs` (+ widened `async_jobs.job_type` for the audit jobs),
all RLS-enabled. Other migrations on the branch are additive code only.

**To go live:** the **`PLATFORM` Railway service must deploy this branch** for the new
endpoints (`/keyword-portal`, `/engagements`, `/strategy`, `/engagements/{id}/audits/*`) to
exist. Frontend is built on Netlify (PR #166 deploy preview is green). No new env vars /
provisioning for any of the above. **The full loop is wired:** onboard → intake (keyword
portal) → auditing (audits fire) → strategize (audits + tracker signals → one plan) → review.

**Deferred (not built):** the **GA4 connector** (Phase 1 · PR5 — GA4 not hooked up yet),
**GBP Performance** connector (open OAuth decision, design §12 Q14), **Asana** sync and the
**monitor/alerting/executor** (Phase 5). The Maps/LLM strategy readers use data that
already exists; their richer signals (winnability, alerting, goal-gaps) land with the
monitor in Phase 5.

**Next:** **Phase 5 — the Continuous Strategist** (monitor + signal bus → goal-gap /
regression / alerting signals; the per-tracker alerting/winnability/goal-rollup designs;
the algo-update timeline) and **Phase 4** (the autonomous executor + WordPress
internal-linking) and **Asana** sync. Smaller follow-ups: PageSpeed (CWV) on top-traffic
pages for the site audit; the DataForSEO Business Listings API for richer citation NAP
discovery; a deep-link target for audit actions. See design §6.5–6.11.

**Security note (pre-existing):** the Supabase advisor flags `public.maps_geocode_cache`
with **RLS disabled** (a shared cross-client cache; predates this work). Enable with
`ALTER TABLE public.maps_geocode_cache ENABLE ROW LEVEL SECURITY;` **plus policies** if you
want it locked down — not auto-applied.

---

## ⏩ Update — 2026-06-29 · **Maps geo-grid strategy & Action Plan** — **MERGED to `main`** (PR #182, squash `35394ae`)

Brought the **Maps geo-grid tracker** to parity with the organic rank tracker's
reoptimization guidance, then layered on strategic competitive intelligence —
all feeding the **unified, deep-linked Action Plan** (`reopt_planner` →
`pages/ActionPlan.tsx`). Authoritative doc:
**`docs/modules/maps-geogrid-strategy-prd-v1_0.md`**.

**What shipped:**
- **Phase 1 — Maps Action Plan (hybrid).** Pure `build_maps_actions` (separate
  from organic `build_actions`) feeds the **shared** `reopt_plans` store + view +
  cadence (weekly digest + **silent on-drop rebuild** via `maps_analyzer`
  `trigger="maps_drop"`). Reuses `maps_alerts` + geocoded weak areas. Actions are
  tagged `source: organic|maps`; Maps declines are **not** deduped against organic
  drops (distinct channels).
- **Phase 2 — Tier A** (reuse existing data, no new fetch): **Share of Local
  Voice** (`services/maps_solv.py`, derived on read) + **brand-search analysis**
  (`services/brand_search.py`, branded vs non-branded GSC demand).
- **Phase 3 — Tier B** (competitor intelligence; each = a deterministic service +
  async job + migration + Maps-tab panel + an Action Plan action):
  **B1** competitor GBP intelligence (`competitor_gbp.py`), **B2** GBP profile
  audit (`gbp_audit.py`), **B3** review analytics (`review_analytics.py`), **B4**
  backlink authority (`backlink_intel.py`), **B5** on-site content comparison
  (`content_intel.py`), **B6** Local Relevance Scorecard (`local_relevance.py` —
  does each signal align with the tracked service/location?) incl. **business
  type** (SAB / physical / hybrid, `gbp_service.classify_business_type` via
  Outscraper's `area_service` hidden-address flag).

**New Action Plan action kinds:** `maps_decline`, `maps_competitor`,
`maps_weak_area`, `maps_solv_drop`, `gbp_gap`, `review_gap`, `backlink_gap`,
`content_gap`, `local_relevance`, `brand_search_decline` (all rendered generically
in `ActionPlan.tsx`).

**Verified:** ~105 pure-unit tests across the new services (mocked external
APIs); frontend `tsc -b` clean; every commit's Netlify preview built green.

**Deterministic trims (noted in the PRD, each a clean follow-up):** review
sentiment/themes (B3 — `reviews.sentiment` column reserved), per-referring-domain
backlink gap list (B4), semantic/entity content comparison (B5 — currently depth +
heading coverage). Competitor GBP/reviews/backlinks/content/relevance refreshes
are **on-demand** today (monthly auto-refresh via the scheduler is a follow-up).

### ⚠️ Maps-strategy provisioning still required (one-time)

The code is on `main` and deploy-ready, but inert until the migrations are applied.

1. **Apply these migrations** to the live Supabase project (all additive — new
   tables + a `job_type` CHECK widen), in order:
   `20260629160000_competitor_gbp_profiles`, `20260629180000_reviews`,
   `20260629190000_backlink_profiles`, `20260629200000_website_analyses`,
   `20260629210000_local_relevance_scores`, `20260629220000_business_type`.
   - **Note on the `async_jobs.job_type` CHECK:** each of the above rewrites it to
     a **superset**. The merge reconciled a drift where `main`'s Asana migration
     (`20260629130000`) had dropped `client_report` + `maps_analyze` from the list;
     these migrations **restore** those and add `asana_monthly` + the six new Maps
     job types (`competitor_gbp`, `review_intel`, `backlink_intel`, `content_intel`,
     `local_relevance`). The final constraint (after `…210000`) is the complete
     union — apply in timestamp order and the end state is correct.
2. **No new env vars.** Every layer reuses already-provisioned creds on
   **PLATFORM**: `DATAFORSEO_LOGIN/PASSWORD` (SoLV competitor data, backlinks,
   reviews, SERP for content), `OUTSCRAPER_API_KEY` (competitor GBP + business
   type), `SCRAPEOWL_API_KEY` (GBP-link + competitor page scrapes),
   `GOOGLE_SERVICE_ACCOUNT_KEY` (brand-search reads `gsc_query_daily`).
3. **Deferred — GBP engagement (#8):** profile views / calls / direction requests
   over time. Needs Google **OAuth 2.0** (`business.manage`) per listing owner +
   GCP provisioning — **incompatible** with the suite's service-account model.
   Parked as its own project (would add `GOOGLE_CLIENT_ID/SECRET` + a per-client
   refresh-token flow + a `gbp_engagement_metrics` table).

---

## ⏩ Update — 2026-06-29 · **Asana task integration**

Connects AR Tools to the team's Asana workspace. **Two features, one token**
(**PR #170 merged to `main`**, squash `5587b0c`; Phases 0–3 built; a by-name
field-resolution follow-up + optional Phase 4 ahead — see Provisioning progress
below):

- **A. Monthly section automation** — each client has an **app-defined task
  template** (its own editable monthly task list, edited in AR Tools). A job
  creates those tasks in the client's Asana project under a new **`<Month YYYY>`**
  section: assignee + category carried, **Status = Not Started**, **no due dates**,
  inserted above the backlog, **idempotent** (re-run = no-op). Runs **auto on the
  1st** (shared `gsc_scheduler` → `asana_monthly` job) **and** via a **"Generate
  this month"** button. UI: client workspace → **Project Management → Asana Tasks**
  (`/clients/:id/asana-tasks`) — the template editor (name + assignee + category
  pickers populated from Asana) + project-GID field + generate button.
- **B. Team Workload** — a suite-level **"Workload"** nav page (`/workload`,
  `GET /asana/workload`) showing each tracked member's open **hours** across all
  clients vs their **weekly capacity** (effort-weighted), with per-day due-hours
  chips + over-capacity flags + a **Team & capacity** editor (pick members from
  Asana, set weekly hours). A **daily** scheduler check
  (`asana_workload.run_workload_alert`) emits one suite notification (in-app +
  Slack) when anyone is over capacity. Effort per task = an **Asana number field**
  the monthly job stamps from each template row's **Est. hrs**.

**Code:** `services/asana_service.py` (REST client + pure helpers),
`services/asana_monthly.py` (Feature A), `services/asana_workload.py` (Feature B),
`routers/asana.py`, `models/asana.py`; frontend `pages/AsanaTasks.tsx` +
`pages/TeamWorkload.tsx`. Migrations `20260629120000_asana_client_projects.sql`
(client→project map) + `20260629130000_asana_task_templates.sql` (per-client
template + widens `async_jobs.job_type` for `asana_monthly`) +
`20260629140000_asana_effort_capacity.sql` (`est_hours` on templates +
`asana_team_members` team/capacity table). Everything **degrades gracefully** —
absent the token / mapping / team list, the relevant feature is skipped with a
note, never an error (the GSC/Slack pattern).

**Verified:** the Asana test suite is green (`test_asana_service`,
`test_asana_monthly`, `test_asana_workload`); frontend typechecks + builds clean.
Nothing runs live until the provisioning below is done.

### ⚠️ Asana provisioning still required (one-time)

The code is deployed-ready but inert until these are set. All secrets/vars go on
the **PLATFORM** Railway service.

1. **Apply the migrations** to the live Supabase project (all additive — new
   tables + columns + a `job_type` constraint widen): `20260629120000_asana_client_projects`,
   `20260629130000_asana_task_templates`, `20260629140000_asana_effort_capacity`.
2. **Token + workspace** — create an Asana **Personal Access Token**
   (developers.asana.com → *My access tokens*) → set **`ASANA_TOKEN`**. Set
   **`asana_workspace_gid`** = your workspace GID (`GET https://app.asana.com/api/1.0/workspaces`
   with `Authorization: Bearer <token>`).
3. **Custom-field GIDs** — for any client project, call
   `GET /projects/<project_gid>/custom_field_settings?opt_fields=custom_field.name,custom_field.gid,custom_field.resource_subtype,custom_field.enum_options.name,custom_field.enum_options.gid`
   and read off: the **Status** field GID + its **"Not Started"** option GID, the
   **category** field GID, and (for workload) a **number** field for effort. Set
   **`asana_status_field_gid`**, **`asana_status_not_started_option_gid`**,
   **`asana_category_field_gid`**, **`asana_effort_field_gid`**. (Absent these,
   tasks are still created — just without that field stamped. For effort: create a
   number custom field like "Est. hours" on the projects first if you don't have
   one.)
4. **Per-client project mapping** — in the app: open a client → **Asana Tasks** →
   paste the project GID (from the Asana project URL `app.asana.com/0/<project_gid>/…`)
   → **Save**. One per client.
5. **Per-client task templates** — fill each client's monthly task list in the
   **Asana Tasks** editor (no Asana "Template" section needed — the app is the
   source of truth).
6. **Team list + capacity (Feature B)** — add members in the **Workload** page
   ("Team & capacity": pick from Asana users, set each one's weekly hours). The
   env **`asana_team_member_gids`** is a fallback seed only (default capacity).
7. **Effort estimates** — set **Est. hrs** per task in each client's **Asana Tasks**
   editor. The monthly job stamps them into the effort field; the workload view is
   blind to effort until they're filled (unestimated tasks count as
   `asana_default_task_hours`, default 1h).
8. *(Optional, no code)* install Asana's official **Slack app** for the Slack ⇄
   Asana leg (task notifications in Slack + create-task-from-Slack).

**Cadence / tunables (config.py, optional):** `asana_month_generate_day` (default
`1`), `asana_month_target_offset` (default `0` = current month), feature toggles
`asana_monthly_enabled` / `asana_workload_enabled`; workload capacity
`asana_default_weekly_hours` (30), `asana_workload_daily_workdays` (5),
`asana_workload_backlog_weeks` (2), `asana_default_task_hours` (1).

**Next (optional Phase 4):** two-way sync (Asana webhook → close rank alerts /
mark Action Plan items done), per-client Asana-project mapping CRUD UI.

### 📍 Provisioning progress (2026-06-29) — where we are

**✅ Merged + deploying.** **PR #170 is merged to `main`** (squash `5587b0c`;
resolved conflicts with main's Client Reports / `maps_analyze` work, keeping both
sides). PLATFORM (deploys from `main`) + Netlify rebuilt from the merge commit, so
the `/asana/*` endpoints and the Asana Tasks / Workload pages are now in the
production build.

**🔑 Key decisions (2026-06-29) that shape per-client setup:**
- **One ongoing project per client** (decided with the user). Their Asana was
  organized as **per-quarter** projects (e.g. "WheelHouse IT Q2 2026"); going
  forward they move to a single long-lived project per client (months as
  sections). So the integration's **fixed** client→project mapping is correct —
  **no quarter-rollover logic needed**. (Team-side workflow change; no code impact.)
- **Custom fields are project-local.** The pilot's "Status" + "Service Type" fields
  are NOT workspace-library fields — each project has its own copies, so their GIDs
  very likely **differ per client project**. The global `asana_status_field_gid` /
  `asana_category_field_gid` therefore only match the pilot. **Planned next
  (follow-up PR): resolve these fields BY NAME per project** ("Status" + its "Not
  Started" option, "Service Type", + the hours number field) at task-creation time,
  so onboarding a client is just *map project + build template* with no GID lookups.
  Until that ships, only the pilot project's tasks get Status/Service Type stamped.

**✅ Migrations applied to live Supabase** (`wvcthtmmcmhkybcesirb`, via MCP):
`asana_client_projects`, `asana_client_task_templates` (+ `est_hours`),
`asana_team_members`, and `async_jobs.job_type` widened for `asana_monthly`.
NB: the live `job_type` CHECK had two values **not** in any repo migration
(`client_report`, `maps_analyze` — pre-existing drift); I preserved them when
widening (dropping them would fail constraint validation on existing rows).

**✅ Railway PLATFORM env set** (token by the user; the rest via the Railway MCP):
- `ASANA_TOKEN` ✅ (secret, set by user)
- `asana_workspace_gid` = `1143356380295200`
- `asana_status_field_gid` = `1214452613145654` ("Status")
- `asana_status_not_started_option_gid` = `1214452613145655` ("Not Started")
- `asana_category_field_gid` = `1214452613145672` ("Service Type": Content /
  Link Building / GBP Authority / Strategy)
- `asana_effort_field_gid` = **not set** — the pilot project has no number custom
  field. To enable effort-weighting: add an "Est. hours" **number** field to the
  client projects, re-run the per-project `custom_field_settings` call, and set
  this GID. Until then Workload treats every task as `asana_default_task_hours`
  (1h).

**Pilot project:** Asana project GID **`1214452202356916`** (Status field
`1214452613145654`, "Not Started" option `1214452613145655`, Service Type
`1214452613145672`). A second client checked ("WheelHouse IT") has the **same field
names** but project-local GIDs — hence the by-name-resolution plan above.

**Per-client onboarding flow (the end state):** (1) one ongoing Asana project per
client; (2) map it in the **Asana Tasks** page (paste project GID → Save); (3) build
its monthly **template** (tasks + assignee + Service Type [+ est. hrs]). Then the
monthly job adds a `<Month YYYY>` section automatically each month.

**Task-template instantiation (built, separate PR):** the team's recurring tasks
are **Asana task templates with subtasks**. The monthly job now **instantiates**
the matching Asana task template (by name) so subtasks come along, then sets
assignee/category/status + moves it into the month section; rows with no matching
template fall back to a plain task. The Asana Tasks editor marks matching rows
with **⊟**. No migration. Endpoint `…/asana/project-task-templates`.

**Task Library (built, separate PR):** a global `asana_task_library` (migration
`20260629170000`, **applied to live**) — the single source of truth for standard
task **durations** (+ default category), keyed by **task name**. Client template
rows inherit `default_hours` / category by name when blank (override per client by
filling the row). Managed at **`/asana/task-library`**; the template editor's
task-name input has a datalist of library names + an inherited "(lib)" hours hint.
Hours feed auto-distribution immediately; they reach Asana once the effort number
field exists. (The workload read also now sums the effort field **by name**, so
real hours work across project-local fields once that field is added + named.)

**Auto-distribution (built, separate PR):** a template row's assignee can be set to
**Auto-distribute** instead of a person; the monthly job spreads those tasks across
the client's **eligible team subset** ("Auto-assign team" picker on the Asana Tasks
page → `auto_assignee_gids`) by **remaining capacity** (weekly hours − current open
hours across all clients, weighted by est. hrs). Pinned rows stay pinned. Migration
`20260629160000` (`auto_assign` + `auto_assignee_gids`) — **applied to live
Supabase**. Needs tracked team members with capacities set (Workload page).

**⬜ Remaining:**
1. **Ship the by-name field resolution** (follow-up PR) so per-client setup needs no
   GID lookups — the next build step.
2. Smoke-test the token: open a client → **Asana Tasks**; the **Assignee** dropdown
   should populate from Asana (proves the live connection).
3. **Map clients → projects** (in-app, one ongoing project each). Pilot:
   `1214452202356916`.
4. **Build per-client task templates** and run **Generate this month** to verify.
5. **Team & capacity** (Workload page) — add tracked members + weekly hours.
6. *(optional)* add an "Est. hours" **number** field to projects + per-task est. hrs
   for hours-based workload (none on the pilot/WheelHouse projects today).

---

## ⏩ Update — 2026-06-28 · **Slack conversational assistant (SerMastr)**

Two-way Slack, **channel mode**: SerMastr lives in a **dedicated channel** and
answers **every plain human message there — no @mention needed** — a
natural-language question about a client's search performance, grounded in the
cross-module context (below), via Claude, posted back **in-thread** with thread
memory. Also works in **DMs**. It answers questions AND can **take actions**
(below). Anyone in the workspace can ask/act (product decision). Its own posts
(rank-drop alerts) + other bots + edits/joins are ignored, so it never loops.

- **Actions (NL → trigger work):** via Claude tool-use in `interpret()`. Tools =
  `_ACTIONS` (append to add one): `rebuild_action_plan` (free → runs immediately),
  `run_maps_scan` / `run_gsc_research` / `run_ai_visibility_scan` (**paid → staged
  behind an explicit confirm**). Each runner enqueues an EXISTING job
  (`reopt_planner.build_plan`, `local_dominator.enqueue_maps_scan`,
  `gsc_research.enqueue_gsc_research`, `brand_service.start_scan`). Confirm flow: a
  paid request stores a pending entry keyed by `(channel, thread_ts)` in the
  in-memory `_pending` (single-replica PLATFORM; a redeploy just drops pending →
  user re-asks) and replies "…reply *yes* to proceed"; the next `is_affirmative`
  message in that thread runs it (the pending carries its own `client_id`, so the
  "yes" needn't re-name the client). Read-only Q&A stays open; a paid action never
  runs without a confirm.

- **Inbound:** `routers/slack_events.py` → `POST /slack/events` (public; the only
  guard is Slack request-signature verification, fail-closed). Answers the
  url_verification handshake, acks within Slack's 3s window, runs the answer in a
  BackgroundTask (Claude > 3s). Handles `message` events with `subtype ∈ {None,
  thread_broadcast}` and **no `bot_id`** (skips the bot's own/alerts + other bots +
  retries). `message` events also cover @mentions (the mention is stripped), so we
  do **not** also handle `app_mention` — that would double-reply.
- **Logic:** `services/slack_assistant.py` — pure helpers (`verify_slack_signature`,
  `strip_mention`, `resolve_client`, `format_context`, `format_history`, unit-tested)
  + `build_context` + `fetch_thread_history` (conversations.replies → prior turns)
  + `interpret` (Claude tool-use, `slack_assistant_model`=`claude-sonnet-4-6`, folds
  thread history into the prompt; returns `("action", tool)` or `("text", answer)`)
  + `is_affirmative` + `post_message`/`handle_message`. Every message gets a reply:
  an answer, an action/confirm, or a "which client?" prompt when none resolves.
- **Cross-module context (extensible registry):** `build_context` runs every
  provider in `_CONTEXT_PROVIDERS`, each isolated (one module failing/empty never
  breaks the answer) and keyed under its module name, so the LLM can tell "no data
  for this module" from real data. Current providers: `organic_rank` (keywords
  w/ `rank_status.compute_keyword_summary`, open `rank_alerts`, latest `reopt_plans`,
  `gsc_research_runs`), `maps_geogrid` (latest `maps_scans`/`maps_scan_results` —
  avg rank, pin coverage, weak areas), `ai_visibility` (`brand_tracked_keywords` +
  latest `brand_mention_history` per-engine visibility + invisible count), `content`
  (completed `runs` by content_type + `local_seo_pages` saved/published),
  `keyword_research` (fanout `sessions` via the fanout-schema service client),
  `setup` (GBP/brand-voice/ICP/target-cities presence on `clients`).
  **To add a future module:** write `_ctx_<module>(supabase, client_id, today)`
  returning a compact dict (or None) and append it to `_CONTEXT_PROVIDERS` — it
  flows into every answer automatically. (Reserved-LogRecord gotcha: don't use
  `extra={"module": …}` — it collides; we use `ctx_module`.)
- **Config on PLATFORM:** `SLACK_SIGNING_SECRET` (**required** — without it the
  endpoint fail-closes and answers nothing), `slack_assistant_enabled` (default
  on), `slack_assistant_model`, `slack_assistant_max_tokens`,
  `slack_assistant_max_keywords`. Reuses `SLACK_BOT_TOKEN` + `ANTHROPIC_API_KEY`.

### ⚠️ Slack dashboard provisioning (one-time)
**Signing secret + Request URL are already done** (live). For **channel mode**
(answer untagged messages) the remaining steps are:
1. **OAuth & Permissions → Bot Token Scopes** → add **`channels:history`** +
   **`groups:history`** (+ **`im:history`** for DMs) (keep `chat:write`;
   `app_mentions:read` is no longer needed but harmless) → **Reinstall to Workspace**.
2. **Event Subscriptions → Subscribe to bot events** → add **`message.channels`**
   (public) + **`message.groups`** (private) + **`message.im`** (DMs) → Save. (You
   can remove `app_mention` — `message.*` covers mentions too.) Request URL stays
   `https://platform-production-a5c5.up.railway.app/slack/events`.
3. Keep SerMastr in its dedicated channel.

(History scopes power the in-thread memory via `conversations.replies`. DM events
were a no-op until `im:history` + `message.im` are added; actions need no extra
Slack config — they reuse `chat:write`.)

Verified so far: import + **605 tests** (12 new), ruff clean (my files), frontend
unaffected. End-to-end Slack round-trip is **untested until the event
subscription + signing secret are provisioned** (above) — there's no way to
exercise the inbound path without a real signed Slack event.

**Next:** future levels if wanted — NL→action commands (trigger scans / rebuild
plans) with per-user authorization; DM support (`im:history` + `message.im`).

---

## ⏩ Update — 2026-06-28 · **Reoptimization planner / Action Plan** + notifications provisioning status

**Reoptimization planner — built & merged** (`#159`, squash `51f5237` → `main`).
PR 2 of 2 on the notifications pipe. Per-client, recommend-only **Action Plan**:
`build_actions` maps the rank tracker's existing signals (open rank-drop alerts,
rankability Quick wins, GSC-Research cannibalization/hidden-wins) to a strictly
tiered action list, each deep-linking into the tool that does the work; nothing
auto-executes. `services/reopt_planner.py` (+ `routers/reopt.py`, `models/reopt.py`,
`pages/ActionPlan.tsx`, workspace card, route `clients/:id/action-plan`,
migration `…060818_reopt_plans` + `reopt_plan` job type). **Cadence:** on-demand
Rebuild; **weekly digest** (`enqueue_due_reopt_plans` on `reopt_plan_weekday`) is
the only auto-notification trigger; **on-drop refresh** (`trigger="drop"`, silent)
from `rank_materialize`. Verified: **593 tests**, ruff clean, frontend build clean.

### ⚠️ Notifications channel provisioning — current status (PLATFORM Railway vars)

The notifications **pipe is built**; in-app card alerts work **today** with no
config. The outbound channels stay dormant until their creds are set on the
**PLATFORM** service. Status:

- **📧 Email (SMTP) — DEFERRED by user (2026-06-28), set up later.** Vars to set
  when ready: `SMTP_HOST` (`smtp.gmail.com`), `SMTP_PORT` (`587`), `SMTP_USER`
  (sending address), `SMTP_PASSWORD` (**Google App Password**, needs 2FA on the
  account), `SMTP_FROM` (optional), `NOTIFY_EMAIL_TO` (comma-separated
  recipients). Email fires only when host+user+password+recipients are all set.
- **💬 Slack — CONFIGURED & live-verified (2026-06-28).** App **SerMastr**
  (`ar_tools`/display "SerMastr", bot `B0BDP9BDXPU`, team "Amazing Rankings")
  with `chat:write`, installed + invited to channel `C0BDM8E9FJA`. `SLACK_BOT_TOKEN`
  + `SLACK_DEFAULT_CHANNEL` set on PLATFORM. Verified end-to-end through the live
  worker (`notification_dispatch` → `channels_sent.slack="ok"`), not just a raw
  API call. (Setup gotcha for next time: the scope must be **`chat:write`** under
  *Bot* Token Scopes — `calls:write` looks similar and yields `missing_scope`;
  private channels need the bot invited and addressed by **ID**, not `#name`.)
- **🔗 `APP_BASE_URL`** (e.g. `https://ar-internal.netlify.app`) — makes the
  email/Slack "Open in AR Tools" deep links clickable; copies still send without it.
- Master switch `NOTIFICATIONS_ENABLED` defaults `true`. Each channel is
  best-effort and records `channels_sent` (ok/failed/skipped) per notification.

---

## ⏩ Update — 2026-06-28 · **Notifications service (in-app + email + Slack)**

The suite's long-deferred **notifications service** — the shared delivery pipe for
in-app alerts, email, and Slack. Built as **PR 1 of 2** toward the reoptimization
planner (the planner is PR 2; this proves the pipe on the existing rank-drop
alerts first). On branch `claude/notifications-service` — **draft PR**.

**Decisions (user):** email = **SMTP (Gmail/Workspace)**; Slack = **app bot token**;
planner cadence = **weekly digest + on-drop** (planner build is PR 2).

- `services/notifications.py::emit(client_id, kind, title, summary, severity, payload)`
  — writes a `notifications` row (in-app feed) + enqueues a `notification_dispatch`
  async job that sends email (`smtplib`, via `asyncio.to_thread`) + Slack
  (`chat.postMessage`) **best-effort, each gated on its creds**. `emit` never
  raises into the producer. Pure format/gating helpers unit-tested.
- **First producer:** rank-drop alerts. `reconcile_alerts` now returns
  `opened_alerts`; `rank_materialize` calls `emit` with a batched digest
  (`summarize_drop_alerts`) when new alerts open (severity critical if a deindex
  is among them).
- **In-app surfaces:** a red unread badge per client tile on **Home**
  (`/notifications/unread-counts`) + an **Alerts panel** in the client workspace
  (`components/ClientNotifications.tsx`) with mark-read / dismiss / mark-all-read,
  deep-linking via `payload.link`.
- **API:** `routers/notifications.py` — unread-counts, per-client feed,
  read/dismiss/read-all.
- **Config on PLATFORM (to provision):** `SMTP_HOST/PORT/USER/PASSWORD/FROM`,
  `NOTIFY_EMAIL_TO`, `SLACK_BOT_TOKEN`, `SLACK_DEFAULT_CHANNEL`, `APP_BASE_URL`.
  Until set, in-app works and email/Slack are skipped (channels_sent records it).

**Migrations (applied; filenames = recorded versions):** `…054924_notifications`
(table + `notification_dispatch` job type) and `…055434_async_jobs_jobtype_complete`
— a **drift fix**: the `async_jobs.job_type` CHECK was missing `local_seo_generate`,
`local_seo_reoptimize_url/page`, `brand_scan`, `brand_report` (dispatched by the
worker but not allowed — latent, none enqueued yet); recreated as the full set.

**Verified:** import main + **576 tests** on pinned fastapi==0.115.0/pydantic==2.9.2
(8 new); ruff clean (my files); frontend build clean. Email/Slack only run on
Railway once creds are set — first real drop is the live proof.

**Next:** PR 2 — the reoptimization planner as the second producer (weekly digest
+ on-drop), emitting through this pipe.

---

## ⏩ Update — 2026-06-28 · **GSC Research auto-cadence (first run + monthly)**

GSC Research (cannibalization / quick wins / hidden wins — the n8n port) was
**on-demand only**; now it also runs **automatically on first GSC-eligibility and
monthly**. Same branch/PR as the capture-cadence change (`claude/rankability-
capture-cadence`, PR #157).

- `gsc_scheduler.enqueue_due_gsc_research` (daily due-check, in the daily block):
  for each client with a **verified GSC property**, enqueue a run if it has **never
  had a completed run** (first-entry) or its last is **≥ `gsc_research_interval_days`
  (30)** old. Reuses `enqueue_gsc_research(trigger="scheduled")` (dedupes in-flight).
- Gated on GSC being **provisioned** (`gsc_research_auto_enabled` + a service-
  account key); GSC Research can't produce anything without GSC, so until
  `GOOGLE_SERVICE_ACCOUNT_KEY` is set + a property verified, **no auto-runs fire**
  (on-demand also returns empty in that state — unchanged).
- Pure `is_gsc_research_due` unit-tested. **No migration** (reuses `gsc_research_runs`).

⚠️ Note: this is **dormant until the standing GSC provisioning gap is closed**
(service account + Search Console API). It activates automatically once that's done.

**Verified:** import main + **568 tests** on pinned fastapi==0.115.0/pydantic==2.9.2
(2 new); ruff clean.

---

## ⏩ Update — 2026-06-28 · **Rankability capture cadence (cost control)**

Replaced the blanket **weekly** SERP-snapshot auto-capture with an event-driven
model (the snapshot is the cost; rankability reads it for free). On a **new
branch off main** (`claude/rankability-capture-cadence`) after #156 merged — new
draft PR.

- **Weekly auto-capture OFF** by default (`serp_snapshot_auto_weekly=False`; the
  weekly enqueue in `gsc_scheduler` is gated behind it). Flip to restore dense
  SERP-trend history.
- **First-entry opt-in:** after keywords are added (typed/CSV/suggestion), a
  banner offers "Run rankability" → captures snapshots for just those keywords
  (`RankKeywords.tsx`).
- **Drop-triggered (≤1/mo):** when any `rank_alerts` rule newly opens (all four,
  incl. deindexed), `rank_materialize` calls
  `serp_snapshot.enqueue_drop_triggered_snapshots`, which captures only keywords
  with **no snapshot in the last 30 days** (`serp_snapshot_drop_min_days`) — so a
  flapping ranking can't re-capture. `reconcile_alerts` now returns
  `opened_keyword_ids`.
- **Manual:** the per-keyword camera + Rankability tab stay ungated.

**Trade-off (accepted):** SERP Trends/timelines now only have points at those
events (sparser). **Config-only, no migration.**

**Verified:** import main + **566 tests** on pinned fastapi==0.115.0/pydantic==2.9.2
(2 new gate cases); ruff clean; frontend build clean.

---

## ⏩ Update — 2026-06-28 · **Topical focus (specialist vs generalist)**

Added a **topical-specialization** signal to the SERP snapshot + rankability: a
niche site dedicated to the keyword's topic can out-rank generalist incumbents
*even with weaker backlinks*, so a generalist-dominated SERP is an opening for a
specialist client. Part of PR #156 (draft).

- **Classifier:** one best-effort **Claude Haiku** call per snapshot
  (`classify_topical_focus`, `serp_topic_model`) labels each ranking site +
  the client **specialist / generalist / unknown** from domain + title + snippet,
  and names the keyword's core topic. First LLM call in the snapshot pipeline
  (otherwise pure DataForSEO) — needs `ANTHROPIC_API_KEY` on PLATFORM (already
  present for maps/brand). Pure parser `parse_topical_classification` unit-tested.
- **Persisted:** `serp_snapshots.keyword_topic / generalist_count /
  client_topical_focus` + `serp_snapshot_results.topical_focus` (migration
  20260628040255).
- **Rankability:** new **topical-opening** sub-score (weight **0.25**, second only
  to competition weakness) — generalist SERP + specialist client boosts the score
  and **offsets weak backlinks**; weights renormalize when a snapshot has no
  topical data. Surfaces as a driving factor ("Incumbents are generalists; you're
  a topic specialist").
- **Viewer:** "generalist" row tags + a "Topic X · N of M incumbents are
  generalists · you're a specialist (an edge here)" summary.

**Verified:** import main + **562 tests** on pinned fastapi==0.115.0/pydantic==2.9.2
(6 new parser/scorer cases); ruff clean; frontend build clean. The Haiku call only
runs on Railway (sandbox has no key/egress) — first live snapshot is the proof.

---

## ⏩ Update — 2026-06-28 · **Rankability score + Quick wins**

A client-relative **rankability** score per tracked keyword — how realistically
*this* client can win it — on a new **"Rankability"** tab in the Rankings page.
Computed on read from each keyword's latest SERP snapshot (no migration). Part of
PR #156 (draft, awaiting merge).

- **Score 0–100 + band** (Easy / Moderate / Hard / Very hard; higher = winnable,
  inverse of difficulty), each with its 2–3 **driving factors**. Four blended
  sub-scores: competition weakness (0.40, backlink authority weighted **RD > UR >
  DR**, medians), client capability (0.25, authority gap + rank momentum),
  targeting gap (0.20, loose-match incumbents), SERP opportunity (0.15, AIO/
  shopping crowding).
- **Quick wins** sort = rankability × **potential value** (volume × CTR-at-top-3 ×
  CPC). Keywords without a snapshot are listed unscored with a capture prompt.
- `services/rankability.py` (pure `score_keyword` + `get_client_rankability`),
  `GET /clients/{id}/rank/rankability`, `components/rankings/Rankability.tsx`.
  Weights/thresholds are tunable module constants; pure scorer unit-tested.
- Heuristic, not ground truth (title/URL + DataForSEO authority, not page bodies).

**Verified:** import main + **558 tests** on pinned fastapi==0.115.0/pydantic==2.9.2
(8 new scorer cases); ruff clean; frontend build clean.

---

## ⏩ Update — 2026-06-28 · **SERP Landscape Trends**

Built on top of the SERP Snapshot work: an over-time + cross-keyword view of how
Google's SERP composition changes, from the dated snapshot archive. New **"SERP
Trends"** tab in the Rankings page. (All on PR #156, still draft, awaiting merge.)

**Three views** (`services/serp_trends.py` + `components/rankings/SerpTrends.tsx`):
- **Per-signal prevalence over time** — % of the client's keywords whose SERP
  shows each tracked signal (AIO, local pack, the SERP-feature + title-format
  signals), as an **as-of weekly series** (each keyword contributes its latest
  snapshot on-or-before each week-end, so weekly auto-capture + ad-hoc captures
  read cleanly). Per-signal sparkline + now/Δ table.
- **"What changed" digest** — keywords whose newest snapshot gained/lost a signal
  vs the prior capture.
- **Per-keyword timeline** — each dated snapshot with its signal chips, the
  client's rank/UR/DR, and the delta vs the previous capture.

**API:** `GET /clients/{id}/serp-trends?weeks=12`, `GET /tracked-keywords/{id}/serp-timeline`
(`routers/rank.py`). No new tables/migration — pure reads over `serp_snapshots` /
`serp_snapshot_results` / `serp_snapshot_domains`. Pure helpers (deltas, as-of
weekly prevalence, change digest, week-end generation) are unit-tested.

**Intended direction (user):** track SERP + competition change over time to drive
an **automated optimization/reoptimization planner** — these trend reads are that
planner's data foundation (not yet built).

**Verified:** import main + **546 tests** on pinned fastapi==0.115.0/pydantic==2.9.2
(8 new serp_trends cases); ruff clean; frontend build clean. Live providers not
exercised from the sandbox.

---

## ⏩ Update — 2026-06-28 · **Competitive SERP Snapshot — per-domain DR + viewer UI**

Closed out the rank tracker's **Competitive SERP Snapshot** (PRD §14). The capture
engine + retrieval API + weekly auto-capture already existed (PR #53, 2026-06-22) —
backend-only, covering AIO, SERP features, intent, top-10 organic, and **per-URL**
referring domains + UR. This pass added the two missing §14 pieces: **per-domain
Domain Rating (DR)** and an **on-demand viewer UI**. (Decisions confirmed before
building: extend the existing feature rather than rebuild; capture DR on **every**
snapshot including the weekly pass.)

**What's new:**
- **Per-domain DR (backend).** `services/serp_snapshot.py`: `fetch_domain_summary(domain)`
  (Backlinks summary, `target=<domain>`, `include_subdomains=True` → `rank` = DR) +
  a pure `collect_snapshot_domains(result_rows, client_domain)` helper (deduped,
  case-insensitive domain set; client domain always appended even when it doesn't
  rank). `_capture_and_store` now fetches DR per unique domain (competitors + client),
  isolated per-domain (a failure degrades the snapshot to `partial`), and stores rows
  in the new **`serp_snapshot_domains`** table.
- **API.** `SerpSnapshotDomainRow` model + `domains: [...]` on `SerpSnapshotDetail`;
  `GET /serp-snapshots/{id}` now returns the per-domain DR rows.
- **Viewer UI.** `components/rankings/SerpSnapshots.tsx` — a per-keyword camera button
  in `RankKeywords.tsx` opens a modal: dated-snapshot sidebar + "New snapshot" (enqueues
  the capture job, polls the list until it lands), and a detail view (AIO + cited sources,
  intent badge, top-10 table with RD/UR + the page's domain DR, a per-domain DR table,
  client rows highlighted).

**Cost:** ~24 DataForSEO lookups/snapshot (1 SERP + 1 intent + ~11 per-URL backlinks +
~11 per-domain backlinks). Confirmed acceptable. The weekly auto pass now also incurs the
per-domain calls across all keywords/clients (per the "DR everywhere" decision).

**Migration (applied to `wvcthtmmcmhkybcesirb`; filename = recorded version):**
`20260628015542_serp_snapshot_domains` — `serp_snapshot_domains` (snapshot_id FK,
domain, is_client, domain_rating, referring_domains, backlinks, backlinks_status).
RLS on, no policies.

**Verification:** full `import main` (under the pinned `fastapi==0.115.0` /
`pydantic==2.9.2`, with a local `community` stub since python-louvain won't build in the
sandbox — fanout-only, unrelated) + **528 passed** (incl. 3 new `collect_snapshot_domains`
unit tests); frontend `npm run build` clean. Live DataForSEO not exercised from the sandbox
(only runs on Railway) — first real on-demand capture with a competitor domain is the live
proof of the DR path.

---

## ⏩ Update — 2026-06-23 · **Module #5 — Maps geo-grid ranker (Local Dominator)**

**Module #5 is built, merged, deployed, and proven live** — a real scan ran end to
end against Local Dominator (PRs **#59, #61, #63, #64, #66, #68, #69**, all merged;
PLATFORM startups verified). Per-client geo-grid of the business's Google Maps rank,
with a heatmap + history.

**Field-learnings (the expensive ones — don't rediscover):**
- Local Dominator ranks in `content` are **0-indexed** (`0` = 1st place — the spec's
  "0 means ranks first"). Display is **+1** (`to_display_grid`); not-ranked pins come
  back **`-1`** (or null), **not** the `null` the OpenAPI example implied.
- The grid is **always a circle** (`shape='circle'` forced; square dropped — user
  decision). A circle returns ~`π/4 × grid_size²` pins (e.g. 95 for an 11×11), not
  the full square — handy as a circle-vs-square sanity check.
- LD's own heatmap image (`view_only_link`) is **not embeddable** — it's an
  `app.localdominator.co` URL needing an LD login, so it 403s/breaks in our app.
- `grid_size` is capped at **21** by the API (our 3/5/7-mile @ 1-mile presets =
  7/11/15 fit).

**Heatmap rendering (#68/#69):** primary view is a **Google Static Map** with small
color-coded pins at each in-circle pin's real lat/lng (built client-side from the
grid + scan center; row 0 = north — verify orientation vs LD's interactive link).
Gated on **`VITE_GOOGLE_MAPS_API_KEY`** (a **Netlify** build var — set via the
Netlify MCP; referrer-restricted Maps Static API key). Falls back to a
dependency-free **circular pin heatmap** when the key is absent or the image fails.

**Scan UX (#63/#66):** async create job + a per-tick scheduler poll **and** a
client-driven `POST …/maps/poll` (every ~10–15s while watching) so results land in
seconds, not the 5-min tick; idempotent result storage (`unique(scan_id,keyword)`);
a prominent **spinner + progress bar + elapsed timer** (the in-flight detection was
fixed to fire immediately on click, before the scan row exists).

---

## ⏩ Update — 2026-06-23 · Module #5 build detail

**Vendor change (logged):** Maps/local-pack geo-grid uses **Local Dominator**, not
DataForSEO — this **supersedes** the suite roadmap's locked "DataForSEO geo-grid /
no new SERP vendor" decision for #5 (user direction). Roadmap decision log + data
sources updated. `LOCAL_DOMINATOR_API_KEY` is set on the **PLATFORM** Railway service.

**The model.** Per client: a **3/5/7-mile radius, 1-mile pin spacing** grid around
the business → `grid_size` 7/11/15 (49/121/225 pins; the API caps `grid_size` at
**21**, which the 1-mile spacing respects). Tracked keywords are scanned across the
whole grid. **Async, decoupled from the worker:** a `maps_scan` job `POST`s
`/v1/scans` (returns `scan_uuid`, status `polling`); the **shared scheduler polls**
`GET /v1/scans/{uuid}` each tick (202=running, 200=done) and parses each keyword's
`content` (per-pin rank grid, `null`=not in top 20) + `average_rank` into results.
Weekly on `maps_scan_weekday` + an on-demand **"Run scan now"**.

**Code.** `services/local_dominator.py` (auth + `create_scan`/`get_scan_rows`; pure
`summarize_grid`/`build_scan_request`; create job + `poll_pending_maps_scans` +
`enqueue_due_maps_scans`) and `services/maps_grid.py` (pure radius→grid geometry).
Wired into `job_worker` (`maps_scan`) and `gsc_scheduler` (weekly enqueue + per-tick
poll). `routers/maps.py` + `models/maps.py`: config GET/PUT, keywords GET/POST/DELETE,
run-now, scans list/detail/latest. Frontend: a **separate workspace module**
(`pages/MapsGeogrid.tsx`, route `/clients/:id/maps`, workspace card activated) —
Heatmap (dependency-free colored rank grid + rollups), Setup (grid config + keywords),
History. Business id/center prefill from the client's `gbp_place_id` + `gbp` lat/lng.

**Migration (applied; filename = recorded version):** `…005340_maps_geogrid` —
`maps_scan_configs` / `maps_keywords` / `maps_scans` / `maps_scan_results` (+
`async_jobs` `maps_scan`). RLS on, no client-facing policies.

**Verification.** `import main` + full suite **243 passed** on pinned
`fastapi==0.115.0` / `pydantic==2.9.2`; frontend `npm run build` clean. Pure helpers
unit-tested (grid geometry, `summarize_grid`, `build_scan_request`). **Not yet live**
against Local Dominator.

**Open follow-ups.** Live smoke-test (config a client with Place ID + lat/lng, add a
keyword, Run now, confirm the heatmap). Defaults chosen: `resource_category`
`googleMaps` (Local Finder selectable), `serp_device` `desktop` (so `both`'s
desktop+mobile rows aren't disambiguated — first row per keyword wins). The
**rank-of-record `RANK_UNIVERSE=20`** sentinel + the `average_rank` semantics
("0 means first" per the spec) should be sanity-checked on the first real scan.

---

## ⏩ Update — 2026-06-23 · **Rank-drop alerting (in-app)**

The Organic Rank Tracker's **alerting** — M4's last open piece — is built. **In-app
only** (the channel decision the user made); email stays deferred to the
notifications service proper. **Merged to `main` and deployed** (PR **#55**, squash)
— PLATFORM redeploy **runtime startup verified clean** via Railway logs
(`job_worker.started` + `gsc_scheduler.started` + `Application startup complete`,
no Traceback), and the Netlify deploy preview was green pre-merge; migration
**applied** to `wvcthtmmcmhkybcesirb`. **This closes M4 — the Organic Rank Tracker
is now feature-complete per its PRD.** Alerts populate on the next daily
materialize run (GSC's 2–3 day lag applies).

**The four rules** (evaluated daily in the existing materialize job, per keyword,
on the keyword's **primary source** — GSC avg position where covered, else
DataForSEO weekly rank; never reconciling the two):
- **weekly_drop** — was ranking in spots **1–15** and dropped **≥6 spots in a week**.
- **page_one_exit** — was on **page 1** (≤10) a week ago, now **off it** (>10).
- **thirty_day_drop** — was in **~top 20** and dropped **≥6 spots over 30 days**
  (a top-20 floor, confirmed with the user, to cut deep-keyword noise).
- **deindexed** — reuses the existing **`deindex_risk`** signal (sustained NULL
  GSC days after an established baseline; GSC-only).

GSC paths compare **7-day rolling averages** (GSC position is a noisy decimal
aggregate); DataForSEO paths compare weekly **point** ranks. **Episode model:** at
most one *open* alert per (keyword, type) — opened when the condition first holds,
**auto-resolved** when it clears (so a flapping keyword doesn't spam). `status`
(unread/read/dismissed) is the user's read-state, separate from `resolved_at`.

**Surface:** a per-client **Rankings → Alerts tab** (the only surface the user
wanted — no global notification center), with an **unread count badge** on the tab
(sourced from `OverviewResponse.unread_alert_count`, already fetched). Mark-read /
mark-all-read / dismiss; recovered alerts show a "Recovered" tag.

**Code:** `services/rank_alerts.py` (pure `detect_alerts` + `reconcile_alerts`),
hooked into `services/rank_materialize.py` (collects signals per keyword in the
existing loop, reconciles once after — **no new job/scheduler**). API in
`routers/rank.py`: `GET /clients/{id}/rank/alerts`, `POST /rank-alerts/{id}/read`,
`POST /rank-alerts/{id}/dismiss`, `POST /clients/{id}/rank/alerts/read-all`; plus
`unread_alert_count` on the overview. Frontend `components/rankings/RankAlerts.tsx`
+ the Alerts tab in `pages/Rankings.tsx`.

**Migration (applied; filename = recorded version):** `…000343_rank_alerts` —
`rank_alerts` + the partial-unique open-episode index. RLS on, no policies.

**Verification:** `import main` + full suite **229 passed** on the **pinned**
`fastapi==0.115.0` / `pydantic==2.9.2`; frontend `npm run build` clean. Detection
is pure-unit-tested (9 cases: each rule, the top-20 floor, GSC + DataForSEO,
no-fire). Alerts populate on the next daily materialize run.

**Tunables (start conservative; PRD §12):** thresholds live as constants in
`rank_alerts.py` (`WEEKLY_DROP_SPOTS=6`, `WEEKLY_DROP_BASELINE_MAX=15`,
`THIRTY_DAY_BASELINE_MAX=20`, the GSC smoothing window, etc.) — promote to config
if they need per-client tuning.

---

## ⏩ Update — 2026-06-22 · **Competitive SERP Snapshot**

A diagnostic **SERP snapshot** store for the rank tracker — captured **weekly**
alongside the DataForSEO rank refresh so a pre-drop baseline always exists when
investigating a ranking drop later. **Backend-only** (no viewer UI by design —
retrieved on request via the API). **Merged to `main` and deployed** (PR **#53**,
squash) — PLATFORM redeploy **runtime startup verified clean** via Railway logs
(`job_worker.started` + `gsc_scheduler.started` + `Application startup complete`,
no Traceback); migration **applied** to `wvcthtmmcmhkybcesirb`. Runs on the
DataForSEO paths whose creds are already on PLATFORM, so it's **operational today**.

**What it captures**, per tracked keyword per capture: the **AI Overview**
(presence, text, cited sources); the **SERP feature inventory** ("enhancements":
local pack/GBP, PAA, discussions/forums, featured snippet, … — item types present
+ captured detail); the **query intent** (DataForSEO Labs search-intent); and the
**top organic results** (url / domain / rendered **title + description** /
position), each enriched with **referring domains + URL Rating** (DataForSEO
Backlinks page rank 0–1000, the UR-equivalent) — **including the client's own
ranking/canonical page** (an extra row if it ranks below the captured depth).

**Decisions (confirmed with user before building):** UR = DataForSEO page rank
(no new vendor); Backlinks API in scope, ~11 lookups/keyword, cost OK; stored
dated snapshots per keyword; **auto weekly capture**; **store-only + retrieval API**
(users don't need routine access).

**Data sources (all DataForSEO, reusing the `dataforseo_rank.py` Basic-auth
pattern):** SERP advanced (`serp/google/organic/live/advanced`) → AIO + organic +
features; Labs `search_intent/live` → intent; `backlinks/summary/live` per target
URL → referring domains + page rank. Per-URL / per-keyword failures are isolated
(snapshot degrades to `partial`; a SERP failure stores a `failed` marker row).

**Code:** `services/serp_snapshot.py` (pure parse helpers + async orchestrator +
`enqueue_serp_snapshot` / `run_serp_snapshot_job`); wired into
`gsc_scheduler.enqueue_due_serp_snapshots` (weekly branch) + `job_worker`
(`serp_snapshot` job type). Retrieval routes in `routers/rank.py`:
`GET /tracked-keywords/{id}/serp-snapshots`, `GET /serp-snapshots/{id}`, and an
on-demand `POST /tracked-keywords/{id}/serp-snapshot` (enqueues a single-keyword
capture). Models in `models/rank.py`. Config: `serp_snapshot_depth` (20),
`serp_snapshot_top_n` (10 — how many top results get the pricier Backlinks call).

**Migration (applied; filename = recorded version):** `…232017_serp_snapshots`
— `serp_snapshots` + `serp_snapshot_results`, widened `async_jobs.job_type`. RLS
on, no client-facing policies.

**Verification:** `import main` + full suite **220 passed** on the **pinned**
`fastapi==0.115.0` / `pydantic==2.9.2` (the #43 process). Live providers not
exercised from the sandbox (DataForSEO calls only run on Railway) — first real
weekly capture is the live proof.

**Note on cost:** the weekly pass snapshots **every** active keyword for every
client (≈1 SERP + 1 intent + up to 11 backlinks calls each). Cost was approved;
if it needs throttling later, gate `enqueue_due_serp_snapshots` (e.g. priority
keywords only) — the same tiering open question as the DataForSEO "Today" rank.

---

## ⏩ Update — 2026-06-22 · **Rank-tracker reports**

Client **reporting** is built on top of the rank tracker — on-demand, scheduled, and optionally delivered as a Google Doc. All merged to `main` and deployed (PRs **#47**, **#48**, **#50**), each verified live (PLATFORM clean startup, `gsc_scheduler.started`). Sits on the rank-tracker section below.

**What shipped:**
- **On-demand printable report (#47).** A **Reports** tab → "Generate now" / open any saved report → a clean, branded print view (`pages/RankReport.tsx`) with a **Print / Save as PDF** button (scoped `@media print` CSS isolates it from app chrome — no PDF dependency). Sections: branded header (logo + client + date + mode/location), KPI summary incl. **total estimated monthly value**, status rollup, GSC trend charts (avg position + clicks/impressions), Improving / Needs-attention highlights, top opportunities by est. value, full keyword table. Adapts for DataForSEO-only clients (drops GSC-only sections).
- **Scheduled reports + in-app archive (#48).** Per-client `rank_report_config`: **as_needed / weekly+weekday / monthly+day / every 7·14·30 days**. The shared scheduler (`gsc_scheduler.enqueue_due_reports`) checks daily via `rank_report.is_report_due` (month-end clamp; never twice a day) and enqueues a `rank_report` job that **snapshots** the report data into `rank_reports` (so a dated report keeps its as-of numbers). `RankReport` renders either live or a stored snapshot (`/clients/:id/rankings/report/:reportId`).
- **Google Doc delivery (#50).** Optional per-client toggle (`rank_report_config.deliver_google_doc`) auto-publishes scheduled + generated reports as a **Google Doc in the client's Drive folder**, reusing the Apps Script publish webhook (the locked delivery rail). `rank_report.render_report_markdown` (pure) → `publish_report_doc` POSTs `{folder_id, title, content}` to `GOOGLE_APPS_SCRIPT_URL`, stores `doc_url` on the report. Any saved report can be published on demand (`POST /rank-reports/{id}/publish`); UI shows **"To Doc" / "View Doc"**. Requires the client to have a Drive folder set (Client → Edit).

**Code:** `services/rank_report.py`; report routes in `routers/rank.py` (`report-schedule` GET/PUT, `reports` GET/POST, `rank-reports/{id}` GET/DELETE, `rank-reports/{id}/publish` POST); frontend `pages/RankReport.tsx` + `components/rankings/RankReports.tsx`.

**Migrations (applied to `wvcthtmmcmhkybcesirb`; filenames = recorded versions):** `…214725_rank_reports` (`rank_report_config` + `rank_reports` + job_type `rank_report`), `…215804_rank_report_delivery` (`deliver_google_doc` + `doc_id/doc_url/delivered_at`). RLS on, no client-facing policies.

**Delivery options status:** in-app archive + Google Doc = built. **Email = deliberately deferred** — needs the suite **notifications service** (unbuilt) + an email-provider/from-address decision. That same decision unblocks rank-drop **alerting**; building the notifications service once lights up both.

**Process note (carried from the #43 incident):** every backend change since is import-/test-verified against the **pinned** `fastapi==0.115.0` / `pydantic==2.9.2` before merge (latest suite run **206 passed**), and each merge's PLATFORM deploy is confirmed via Railway logs for a clean runtime startup — not just a green build.

---

## ⏩ Update — 2026-06-22 · **Organic Rank Tracker shipped** (supersedes the scheduler + `sie_cache` RLS items in §8)

The **Organic Rank Tracker (Module #4)** is **built and live in production** — M1–M4 complete **except alerting**. Hybrid **GSC + DataForSEO** with an automatic per-keyword fallback. All merged to `main` and deployed (PRs **#36**, **#43** hotfix, **#44**). Authoritative doc: **`docs/modules/organic-rank-tracker-prd-v1_0.md`**.


**The model.** Keywords are **client-anchored** (a GSC property is optional). Source is auto-selected **per keyword**: **GSC** where the site ranks *and* GSC is connected; **DataForSEO (weekly)** otherwise — no accessible property, or the site doesn't rank for the term so GSC has nothing. DataForSEO writes `tracked_rank` only; **never reconciled** with GSC's averaged `gsc_position`. The weekly DataForSEO job skips GSC-covered keywords, so spend scales with the gaps.

**What shipped (PR #36):**
- **M1 connection** — service-account GSC (`gsc_properties`, verify-access). **M2 sync** — daily ingest → `gsc_query_daily` + `sync_runs`; the **in-process asyncio scheduler** (`services/gsc_scheduler.py`) is the **decided shared-scheduler mechanism** — enqueues jobs into `async_jobs`, reuse it for future trackers. **M3** — materialized null date-axis `rank_keyword_metrics` + computed status taxonomy (`rank_status.py` / `rank_materialize.py`); tabbed Overview/Keywords/Settings UI; **dependency-free SVG charts** (inverted-Y with visible gaps — no charting lib, React-19-safe). **M4** — `keyword_market` (CPC/volume/competition + est-monthly-value ROI), weekly query×page `gsc_query_page_daily` → canonical-URL resolution + Pages view, striking-distance discovery, deindex **URL Inspection** confirmation (`tracked_keywords.index_status`).
- New services: `gsc_service, gsc_ingest, gsc_scheduler, rank_status, rank_materialize, dataforseo_rank, keyword_market`; routers `gsc`, `rank`. Frontend `pages/Rankings.tsx` + `components/rankings/`.

**Follow-ups shipped same session:** historical GSC backfill (Settings, ~16mo), per-keyword **page breakdown** + "+N pages" chip, **canonical-URL pinning** UI, **CSV export**, **all actions opened to any authenticated team member** (no admin gates), keyword add via type/paste/**CSV import**, and a **per-client tracking location** (city/region/country via the existing `LocationAutocomplete` — `clients.rank_tracking_location[_code]`, PR #44) that drives the DataForSEO ranks + market data. GSC metrics stay national-aggregate (Google limitation); geo-grid local-pack is Module #5.

**⚠️ Production incident (PR #43) — lesson logged.** Merging #36 crash-looped **all of platform-api** on startup: two `DELETE` endpoints used `status_code=204` with a `-> None` return, which **FastAPI 0.115.0 (the pinned prod version)** rejects at import (`AssertionError: Status code 204 must not have a response body`). The sandbox's *newer* FastAPI didn't surface it. Fixed to match the codebase's working pattern (`routers/users.py`: `response_class=Response`, return `Response(status_code=204)`). **Lesson: verify imports/tests against the *pinned* `requirements.txt` versions, not whatever the sandbox happens to have** — done for all later work (198 tests pass on `fastapi==0.115.0` / `pydantic==2.9.2`). Prod recovery confirmed via Railway logs (clean startup, `gsc_scheduler.started`).

**Migrations (all applied to `wvcthtmmcmhkybcesirb`; filenames reconciled to the apply-time recorded versions per `MIGRATIONS.md`):** `…181919_gsc_properties`, `…181933_gsc_ingest_storage`, `…183357_rank_tracker_keywords`, `…185307_keywords_client_anchor`, `…185948_keyword_market`, `…191240_gsc_query_page_daily`, `…191831_keyword_index_status`, `…203200_sie_cache_enable_rls`, `…211331_clients_rank_tracking_location`. All RLS-on, **no client-facing policies** (service-role only — the `async_jobs` pattern).

**Housekeeping done:** `CLAUDE.md` updated (rank-tracker current state, services/routers, the resolved scheduler decision, `GOOGLE_SERVICE_ACCOUNT_KEY` note); **`public.sie_cache` RLS enabled** — closes the long-standing §8 advisory item (was disabled on the live DB despite the original migration; service-role-only, no policies); migration ledger + reconciliation log updated in `writer/supabase/MIGRATIONS.md`.

**⚠️ Provisioning still required for the GSC path:** set **`GOOGLE_SERVICE_ACCOUNT_KEY`** (full service-account key JSON) on the **PLATFORM** Railway service, and create the GCP service account + enable the **Search Console API** (a dashboard step — confirm with the user). Until then the tracker runs **DataForSEO-only** (works **today** — DataForSEO creds were already set on PLATFORM); GSC verify/ingest/URL-Inspection show a "not configured" state.

**Still pending by design:**
- **Alerting** (deindex/drop → email/Slack/in-app) — gated on the **notifications-channel decision** (in-app feed vs email/Slack + provider/webhook details). The detection (`deindex_risk`/`dropping` status) already runs; only the outbound hook is unbuilt.
- **Module #5 — Maps / local-pack ranker** (geo-grid). This is the *only* thing the per-client tracking location does **not** cover — the organic tracker is national/city point-in-time SERP, not a grid of points around a business.

**Verified & deployed:** backend **198 tests** on the pinned stack; frontend `npm run build` clean. Production confirmed live from the latest commit — PLATFORM (Railway) clean startup, `ar-internal.netlify.app` deploy `ready` on `d353afa`. (Tell users to **hard-refresh** to clear the cached bundle.)

---

## ⏩ Update — 2026-06-22 (supersedes the TextRazor open items in §3/§6/§7 below)

TextRazor is **live, calibrated, and secured**, and the **Local SEO module is feature-complete** (location autocomplete, SERP caching, page templates, Google-Doc publishing). All of today's work is merged to `main` and deployed (PRs #23–#33).

**TextRazor — done.**
- **Activated:** `TEXTRAZOR_API_KEY` had been *staged* (not committed) — committed via Railway `accept-deploy` + redeploy. nlp startup now logs `TEXTRAZOR_API_KEY is set`.
- **Concurrency bug fixed (#25):** live runs returned 0 entities — TextRazor's per-plan concurrent-request cap rejected all-but-~2 of the per-page fan-out with `401`. `fetch_textrazor_entities` now runs behind an `asyncio.Semaphore` (`TEXTRAZOR_MAX_CONCURRENCY`, default 2) + retries 401/403/429 with backoff. A real `roof restoration` / Melbourne analyze then returned all 13 pages `200` → **5 entities**.
- **Calibration:** distribution `[0.93, 0.53, 0.44, 0.35, 0.12]`. `TEXTRAZOR_MIN_RELEVANCE` **kept at the default 0.1** — the page-spread filter is the dominant signal and 5 is a healthy, focused set; no env change needed. (One-keyword sample; revisit if more keywords show noise.)
- **Key NOT rotated** — user deferred (§6.2 still open if desired).

**Security / cost (§6) — closed.**
- nlp **public domain removed** → private-only (`nlp.railway.internal`; PLATFORM already used that). No more internet-exposed auth-less nlp.
- `GOOGLE_NLP_API_KEY` **removed** from nlp (unused post-swap). Redeploy verified healthy.

**Local SEO location robustness (#23, #24) — new.** Mistyped areas silently degraded generation (DataForSEO `200` + 0 results → no competitors, no TextRazor). Fixed with: an **area typeahead** (`GET /clients/{id}/local-seo/locations`, DataForSEO `locations/{country}` scoped to the client's country, in-memory cached — `services/locations_service.py`); a **server-side validation backstop** (`resolve_location`: trust a picked `location_code`, else match the typed name → attach code, else `400` + suggestions); and `location_code` threaded through the **generate** path (`GeneratePageRequest` + its inline analysis — previously dropped). Frontend `LocationAutocomplete` combobox + DataForSEO task-error diagnostics. Tests: platform-api **91 passing**.

**UI (#26).** The localseo `Spinner` never animated because `index.css` (which declares the `spin` keyframe) **isn't imported anywhere** in the app; the Spinner now injects its own keyframe. Analyze/check buttons show "Analyzing competitors…".

**SERP analysis caching (#29) + review hardening (#30).** SERP analysis (DataForSEO+ScrapeOwl+TextRazor, ~20 pages, 2–4 min) was re-run on every analyze/score/generate. It depends only on (keyword, location), so it's now cached and **shared across clients**. `keyword_analyses` table (migration `20260622120000`, RLS-on/service-role-only); `services/analysis_cache.py` with a **14-day TTL** (`analysis_cache_ttl_days`, 0 disables); `_get_or_compute_analysis` used by analyze/generate/score (generate & score pass the cached analysis to nlp so it skips its inline re-scrape); a **`force_refresh`** flag + "Refresh competitor data" checkbox. Review hardening (#30): generate/score **degrade gracefully** when analysis can't be computed (don't hard-fail — `required=False`), `analyze` still propagates; **single-flight** lock collapses concurrent identical misses; cache hits flagged `from_cache` with cost zeroed; idempotent migration; `score` forwards `user_id`.

**Local SEO Phase 3 — page template (#31).** Mirror an existing page's section structure: per-page field + optional **per-client default** (`clients.local_seo_page_template_url`, migration `20260622140000`). nlp `GeneratePageRequest.page_template_url`/`_html`; `_extract_template_outline` scrapes the reference (SSRF-guarded) → H1/H2/H3 outline → injected as a STRUCTURE-OVERRIDE block that supersedes the default 13 sections while keeping AEO rules + JSON-LD; degrades to default if unfetchable. `PUT /clients/{id}/local-seo/page-template-default`.

**Local SEO publishing (#33).** Generated pages now **publish to a Google Doc in the client's Drive folder**, reusing the blog writer's Apps Script webhook (the locked publish destination). `services/html_to_markdown.py` (stdlib HTML→Markdown, no new dep) → `publish_page` POSTs to `GOOGLE_APPS_SCRIPT_URL` with the client's `google_drive_folder_id` → persists `published_doc_id/url/at` (migration `20260622150000`, additive — the in-app page is the source of truth and is unchanged). `POST /local-seo/pages/{id}/publish`; "Publish to Google Doc" / "View Google Doc" in the page view. Prereq: client must have a Drive folder set (Client → Edit), accessible to the Apps Script's Google account.

**Local SEO module is now feature-complete.** Verified our nlp `/generate-page` writer matches the ShowUP Local `CONTENT_WRITER` spec (13 sections, 14 AEO rules, Sonnet 4.6 @ 16k, 8-engine 85/15 scoring, RDFa/JSON-LD) — only deltas are the intentional suite adaptations (TextRazor, no billing, auth at platform layer, caching, location_code). Reoptimizer + GBP-social-posts paths traced end-to-end and confirmed wired (GBP posts are **generate-only** — not auto-posted to Google Business Profile).

**Tests:** platform-api **118 passing** (analysis_cache, locations, page-template, html_to_markdown, publish, degrade/single-flight units).

**New debt / still open.**
- `index.css` unimported → base resets (`box-sizing`, `margin:0`) don't apply suite-wide — left as-is (importing would shift layouts); decide separately.
- TextRazor key rotation still deferred.
- **Local SEO live-verification debt:** only `analyze` + `generate` are live-proven. Not yet live-tested: score, reoptimize, find-page, related-pages, GBP social posts, page-template, **publish**.
- Reoptimize doesn't reuse the SERP cache; some entry paths reoptimize without SERP context (degrades, not breaks). `score` force-refresh not exposed in UI. No DOMPurify on rendered HTML (first-party).
- Not built (out of v1 / separate): **GBP post auto-publishing**, live-CMS/WordPress publishing.
- Everything in §8 below still stands.

---

**Date:** 2026-06-21
**State:** everything below is **merged to `main` and deployed** (PRs #20, #21, #22). No feature branch is left in flight; the only open work is the TextRazor *activation/calibration* and the standing items in §6–§8.
**Scope of this handoff:** this session shipped four things — (1) **Brand Voice** + (2) **ICP/Differentiators** as converged client-level assets, (3) repaired a set of **nlp constants dropped in the Phase-0 rehome** that were silently 502'ing score/generate/reoptimize/press-release, and (4) swapped the entity provider **Google Cloud NLP → TextRazor**.

> Read `CLAUDE.md` first for conventions + current-state summary, `docs/suite-architecture-and-roadmap-v1_0.md` for suite scope/decisions, and `docs/modules/local-seo-module-integration-plan-v1_0.md` for the Local SEO plan. This file ties them to the latest state.

---

## 1. What this session shipped (all merged to `main`)

| PR | Title | What |
|---|---|---|
| **#20** | `Fix nlp-api: restore constants dropped in the Phase-0 rehome` | Restored `SCORE_MODEL`, `_SCORE_SYSTEM_PROMPT`, `_MODEL_PRICING`, `GENERATION_MODEL`, `_GEN_SYSTEM_PROMPT`, `_REOPT_SYSTEM_PROMPT`, `_PRESS_RELEASE_SYSTEM_PROMPT` (verbatim from `local-seo-writer/services/nlp/main.py`); added the missing `import anthropic` in `/find-page-for-keyword`; built `seo_checklist` in the reoptimize loop. **F821 in nlp-api → 0.** |
| **#21** | `Brand Voice + ICP/Differentiators — converged client-level assets` | Two new client-knowledge modules, end-to-end (store + generation + convergence bridge + UI). |
| **#22** | `Swap entity provider: Google Cloud NLP → TextRazor` | Full replacement of the entity pipeline. |

**The nlp repairs (#20) are the most important takeaway.** The Phase-0 rehome (`00ae38e`) carried the *functions* but dropped a block of module-level constants, so `/score-page`, `/generate-page`, `/reoptimize-page`, `/augment-page`, and `/press-release` raised `NameError → HTTP 502` on every call. This was latent because nlp-api has no test harness. Proven via AST (no assignment), `ruff F821`, and `git log -S` (never in the file's history). **If anyone reports "Local SEO scoring/generation was broken before 2026-06-21," this is why.**

---

## 2. Brand Voice + ICP — the convergence model (Option A)

These two re-add capabilities the Local SEO v1 plan had **cut** (`brand-voice`/`ICP` scraping) — done deliberately, per the user, and **converged** so one client-level asset feeds **both** the Blog Writer and Local SEO.

**Decision (Option A):** the structured JSON is the single source of truth; the legacy free-text columns become a *rendered view*.
- `clients.brand_voice` JSONB — `{ source, raw_text, current_voice, recommended_voice, recommended_accepted, writer_execution_guide, generated_at, edited_at }`.
- `clients.detected_icp` JSONB — `{ source, raw_text, segments, reasoning, generated_at, edited_at }`; `clients.differentiators` JSONB (array). One `detected_icp.source` governs supersede for both.
- **Provenance/supersede:** `source: "user" | "app"`. A user-authored *structured* voice/ICP blocks an auto-scan unless `force=true`; a `raw_text`-only entry can still be enriched (the scan preserves it). The UI badge treats any `raw_text` as user-authored.
- **Migrations (live + verified):** `20260621120000_clients_brand_voice.sql`, `20260621130000_clients_icp_differentiators.sql` — both applied to `wvcthtmmcmhkybcesirb` and seeded from existing `brand_guide_text` / `icp_text`.

**Wiring:**
- nlp-api: `POST /analyze-brand-voice` + `POST /analyze-business` (these *engines* already existed but were orphaned — no endpoint/persistence/UI). ICP scan includes opt-in **title/H1 enrichment** (`_enrich_pages_with_titles`, time-bounded). `_build_brand_voice_text` / `_build_icp_text` now also render `raw_text`.
- platform-api: `services/brand_voice_service.py` + `routers/brand_voice.py`; `services/icp_service.py` + `routers/icp.py`. Routes: `GET` / `POST …/scan` (heartbeat-SSE) / `PUT`, all behind `require_auth`, per-user rate-limited via a forwarded `X-User-ID` (added to `_post_nlp`).
- **Convergence bridge:** `resolve_brand_guide_text` / `resolve_icp_text` render the structured asset into the Blog Writer's run-snapshot `brand_guide_text` / `icp_text` (differentiators folded into the ICP text), at all three snapshot sites (`runs.py` dispatch + rerun, `silo_promotion.py`). **No Writer-internals change.** The clients router keeps the structured asset in sync when the legacy free-text fields change.
- **Local SEO generate/social payloads** now pass `brand_voice` / `detected_icp` / `differentiators` to the generator (they were previously omitted — this completes the Local-SEO side of convergence).
- Frontend: `pages/BrandVoice.tsx`, `pages/Icp.tsx`, `components/{brandvoice,icp}/api.ts`, ClientWorkspace "Client setup" cards, routes `/clients/:id/brand-voice` and `/clients/:id/icp`.

---

## 3. TextRazor swap (entity analysis) — **NOT FULLY LIVE YET**

Replaced Google Cloud NLP with TextRazor in the SERP pipeline (cost + Wikipedia/Wikidata linking). **Structure preserved** — per-page de-dup → page-spread + relevance filter — only the source/field mapping changed, and the downstream `google_entities` field name is **kept** so zone targets / rubric / deterministic engine / ICP are untouched.

- Mapping: `relevanceScore` → the `mean_salience` slot; `entityId` = grouping key; `matchedText` (most common) = `name`; `wikidataId` → `mid` (+ new `wiki_link`); mentions grouped by `entityId`.
- Thresholds: `ENTITY_MIN_PAGE_SPREAD` unchanged (the dominant, provider-agnostic filter). The old `0.40` salience cutoff **does not transfer** → replaced by `ENTITY_MIN_RELEVANCE` (env `TEXTRAZOR_MIN_RELEVANCE`, default lenient **`0.1`**) + optional `ENTITY_MIN_CONFIDENCE`. `get_textrazor_entities` **logs the relevance distribution** of page-spread-qualifying entities for calibration.

### ⚠️ Two things are NOT done — pick these up next
1. **The key is staged, not applied.** `TEXTRAZOR_API_KEY` was set on the `nlp` service via the Railway agent but only *staged* — the post-merge deploy log still shows `WARNING - TEXTRAZOR_API_KEY not set`. **Until it's committed (via `accept-deploy`, or re-set + redeploy), TextRazor is inert: `get_textrazor_entities` returns `[]`, so the entity signal is missing entirely** (graceful — scoring/generation still run, entity coverage defaults to its neutral value, no crash). **This was awaiting user go-ahead to redeploy when the session ended.**
2. **Threshold not calibrated.** `0.1` is a placeholder. Once the key is live, run one real Local SEO `/analyze` (or score), read the `nlp` log line `TextRazor calibration: N page-spread-qualifying entities; mean relevance (desc): [...]`, and set a tuned `TEXTRAZOR_MIN_RELEVANCE`.

---

## 4. Verification status (read this before trusting anything live)

- **All checks were static/offline:** `py_compile`, `ruff` (F821=0 in nlp-api), `mypy`/`eslint` on new code, the platform-api pytest suite (**83 passing**), `tsc -b` + `vite build`, and AST byte-identity checks on the restored nlp constants. New aggregation logic (TextRazor) was exercised against a **mocked** response.
- **Nothing was live-tested.** The build sandbox has **no `ANTHROPIC_API_KEY` and an egress allowlist** (e.g. `api.textrazor.com` is blocked, returns `403 Host not in allowlist`). Real provider calls only happen on Railway. So: the nlp repairs, the brand-voice/ICP scans, and the TextRazor swap have **not** been exercised against live providers from here.
- **Sandbox dep gaps** (not bugs): `openai`, `supabase`, `python-multipart` aren't installed in the build env, so some imports/tests fail here but pass with `pip install -r requirements.txt`. `pip install --ignore-installed PyJWT supabase` was needed for the platform tests.

---

## 5. Infra / deploy state

- **Railway (`ar-tools`): 4 services** — `nlp`, `PLATFORM`, `pipeline`, `info-site-kw-research-cluster` (the separate keyword-research app), env `production` (`7bd2e88e-…`), project `2c718e53-…`.
- **All three suite services redeployed** off the merges and reported **SUCCESS** (latest `nlp` deploy = `6025459`, the #22 merge). The TextRazor *code* is live; the *key* is not (see §3).
- **`nlp` keys present:** `ANTHROPIC_API_KEY`, `SCRAPEOWL_API_KEY`, `DATAFORSEO_LOGIN/PASSWORD`, `GOOGLE_NLP_API_KEY` (now unused — removable after TextRazor is confirmed), `TEXTRAZOR_API_KEY` (**staged, not applied**). `SCORE_MODEL`/`GENERATION_MODEL` are **not** env vars (code constants → sonnet default); their absence is expected.
- Railway gotchas still apply (from the prior handoff): private-only `nlp` ⇒ **keep `healthcheckPath` empty**; Dockerfile binds `::`; don't double-trigger deploys; SSE routes need buffering off.

---

## 6. ⚠️ Open security / cost items (flagged, not yet actioned)

1. **`nlp` has a PUBLIC domain** — `nlp-production-0e3c.up.railway.app:8080` — but the service is **auth-less by design** ("private network only" per CLAUDE.md). If that domain is internet-reachable, anyone who finds it can hit `/generate-page`, `/score-page`, `/analyze`, etc. and **burn Anthropic + DataForSEO + ScrapeOwl + TextRazor credits**. The #20 repairs made those endpoints *more* functional, so this matters more now. **Verify reachability and remove the public domain (or add auth) — highest-priority loose end.**
2. **Rotate the TextRazor key** — it was pasted into the chat transcript this session. The working value is in Railway; rotate once cutover is confirmed.
3. After TextRazor is confirmed working, **remove `GOOGLE_NLP_API_KEY`** from `nlp` (no longer read).

---

## 7. Immediate next steps

1. **Finish TextRazor (§3):** apply the staged `TEXTRAZOR_API_KEY` (redeploy `nlp`), run one real `/analyze`, read the calibration log line, set a tuned `TEXTRAZOR_MIN_RELEVANCE`, confirm entity counts are sane. Then rotate the key + drop `GOOGLE_NLP_API_KEY`.
2. **Close the `nlp` public-domain exposure (§6.1).**
3. **Live smoke-test the repaired nlp endpoints** — `/score-page` + `/generate-page` against the deployed PLATFORM→nlp path with an authenticated request. These were 502'ing before #20; a real call is the only true proof they're fixed (couldn't be done from the sandbox).
4. **Click-test Brand Voice + ICP** end-to-end (scan → review → accept → generate) — built/typed-clean but not exercised live.

---

## 8. Open decisions / standing debt (carried forward)

- **SERP analysis cache (`keyword_analyses`) still does not exist.** Every `/analyze` and `run_analysis:true` generate re-runs the full DataForSEO→ScrapeOwl→(now TextRazor) pipeline (2–4 min, recurring cost). SYSTEM_OVERVIEW/Foundation calls for caching `AnalysisResponse` by `(keyword, location)`; this is the highest-value infra still unbuilt and would speed up Score My Page + generation.
- **Vertical wording** — the brand-voice/ICP/score prompts say "local service business" verbatim. Fine for local clients, slightly off for non-local Blog-Writer clients; left verbatim per the "keep prompts exact" rule. Parameterizable later.
- **Manual editing is freeform `raw_text`** for both brand voice + ICP; per-field structured editing is a future enhancement.
- **`seo_checklist` in `/reoptimize-page`** was a latent bug present in the reference copy too; fixed by mirroring generate-page's `_build_seo_checklist(...)` call — worth a sanity check on a live reoptimize run.
- **Scheduler mechanism**, **Maps geo-grid density**, **notification channels**, **Keyword-research repo migration**, **CI on push** — all still open from prior handoffs.
- **Local SEO Phase 3 — page-template field** — still not started (the original request from the prior session).
- Pre-existing: `public.sie_cache` has RLS disabled (advisory); migration-timestamp convention mismatch; `README.md` references a non-existent `/kw-research` path.
