# AR Tools — Handoff

## ⏩ Update — 2026-08-28 · **LeadOff — agency cost-to-win ROI replaces the $/review "ROI" (MERGED + LIVE)** (latest)

The market brief/board/tryout used to show **"ROI ($/mo per review)"** =
`exp_val / max(rev_win, 10)` — a value-per-effort ratio that **subtracts no
cost**, so a market read as cheap-to-win while being expensive. Owner ruling
(2026-08-28): make it a **real ROI** — expected monthly value vs. what the
**agency** pays to win and hold the ranking. Three PRs, all squash-merged to
`main` and live (the routes compute it on read; **no migration**):
**[#832](https://github.com/kssabraw/ar-tools/pull/832)** (the model + board/brief),
**[#834](https://github.com/kssabraw/ar-tools/pull/834)** (first-month 2× setup),
**[#835](https://github.com/kssabraw/ar-tools/pull/835)** (Tryout).

**The model** — `services/leadoff_roi.py` (pure `compute_roi` +
`estimate_ramp_months` + `estimate_maintenance` + `rd_gap_from_enrichment`;
impure `attach_roi`; unit-tested `tests/test_leadoff_roi.py`):

- **deliverables** = reviews-to-win × per-review + pages × per-page (+ RD gap ×
  per-link, **scouted markets only**). Unit prices come from the **Recipe Engine**
  catalog (`CONTENT_PAGE_COST` imported directly) so nothing is invented.
- **first-month setup surcharge** = (first_month_multiplier − 1) × monthly
  maintenance — the first month costs 2× (site build, initial citations, GBP
  config) the steady-state months.
- **ramp cost** = ramp_months × monthly maintenance — SEO doesn't rank instantly;
  you pay monthly labour through the climb before value arrives. This is what
  makes payback realistic (the first cut, with no ramp, gave a <1-month payback).
- **monthly profit** = expected $/mo − monthly maintenance (steady state).
- **payback (months)** = ramp_months + (deliverables + setup + ramp) ÷ monthly
  profit. `None` ⇒ never recoups (maintenance ≥ the market's value). Value is
  modelled as a step at end-of-ramp (conservative; a pre-client forecast).

**Everything slides per market on field difficulty** (Beatability — from
rev_win/holders/rating — preferred, win-likelihood `rankab` fallback, 0.5 ease
if neither):

- **ramp** between `leadoff_roi_ramp_min_months` (3, soft field) and
  `_max_months` (9, brutal), THEN adjusted by the review-velocity **momentum**
  (the "competition is still doing SEO" / moving-target factor, **scouted only**):
  accel ×`_ramp_accel_mult` (1.35), cooling/dead ×`_ramp_cooling_mult` (1.05 —
  even a cooling field is still building, so it mildly *extends*, not shortens).
- **maintenance** between `leadoff_roi_maint_min_month` (135, soft) and
  `_max_month` (600, brutal) — harder fields cost more to *hold*.

**Measured vs modelled** (carried as `roi_confidence`): the RD/link gap is only
captured on **scouted** markets (the brief, via `rd_gap_from_enrichment` on the
`enrichment.rd_med` ×10-true-RD field) → `measured`; **board-wide + tryout** have
no scouted RD → links omitted + flagged `modelled`. Same honesty split as the
rest of LeadOff.

**Wiring / surfaces:**
- `services/leadoff.py` — `attach_roi` over board rows (after `attach_beatability`,
  modelled) + on the brief (measured); new **`profit`/`payback` board sorts**
  (prefetch on `exp_val`, re-sorted in Python — no scanner column exists).
- `services/leadoff_actions.py::run_tryout_job` — Beatability + `attach_roi` on
  tryout rows before persist (best-effort; JSON `leadoff_tryouts.results`).
- `frontend/src/pages/LeadOff.tsx` — **Profit $/mo + Payback** columns (replacing
  ROI $/rev) on the board AND tryout tables, the two new sort options, a brief
  ROI block with the cost-to-win breakdown (reviews/pages/links/1st-mo setup/ramp)
  + measured/modelled note, CSV columns. The old `roi` field is kept for
  back-compat.

**Worked example (Little Rock water-damage, Beatability 71):** maintenance
~$212/mo, ramp ~4.7mo, first-month setup +$212, cost-to-win ~$1,388, monthly
profit ~$1,237, **payback ~5.8 months** — vs. the old nonsensical $/review 90.6.

**⚠ The unit-cost defaults are placeholders, not the agency's real economics** —
all config, tune without a rebuild: `leadoff_roi_cost_per_review` (10),
`_cost_per_link` (30), `_content_pages` (4), `_maint_min/max_month` (135/600),
`_ramp_min/max_months` (3/9), `_ramp_accel/cooling_mult` (1.35/1.05),
`_first_month_multiplier` (2.0), `_rd_target_mult` (1.0), `_enabled` (True).

**Gap-grows-during-the-ramp (BUILT — owner ruling 2026-08-28, Option B):** while
you close the review/RD gap, the incumbents keep building, so the **effective**
gap (and its cost) is larger than the static snapshot. `compute_roi` now inflates
the deliverable counts over the ramp horizon: **reviews** = `rev_win` +
review_rate × ramp, where the rate is the field's **measured** velocity on
scouted markets (`field_review_growth` = `field_vel30 / vel_matched` ≈ the #3's
monthly review gain) or a flat board default (`leadoff_roi_field_review_growth`,
2/mo); **RD** = the scouted RD gap × (1 + `leadoff_roi_rd_growth_pct_month` (0.055)
× ramp) — RD has no growth-rate data pre-client, so it's a flat %/month
assumption applied to the measured RD gap only (board/tryout have no RD gap → no
RD growth). Gated `leadoff_roi_gap_growth_enabled` (True). The cost breakdown
carries `reviews_growth`/`links_growth` and the brief annotates "+N during ramp".
**Note the deliberate compounding:** the momentum ramp-extension already
lengthens the *time* for an active field, and this adds *quantity* on top — an
accelerating field is penalised on both axes (owner accepted this). Little Rock:
+~9 reviews over the ramp ≈ +$94, a modest effect that grows in fast-moving
fields. **Still deferred:** swap in the real agency unit costs (the one change
that moves every number more than this refinement does).

---

## ⏩ Update — 2026-08-27 · **Website Builder — brand_service + hyper_local engines BUILT + generalized to service variations (MERGED)**

Tier A of the roadmap entry below is **done and on `main`**. Three PRs, all
squash-merged:

- **[#807](https://github.com/kssabraw/ar-tools/pull/807)** — the two Tier-A
  engines. `brand_service` (`/{service}/{brand}/`) + `hyper_local`
  (`/{city}/{service}/{subservice}/`) now generate through the **existing nlp
  writer** (`local_seo_service.generate_page`) — no new generator, just a
  `generation_inputs` branch each + both added to `NLP_PAGE_TYPES`.
  `brand_service` targets `"<Brand> <Service>"` geo-agnostically (city scopes the
  SERP only); `hyper_local` targets its need with the city as location and stays
  **engine-only** (SOP: escalation-only, never bulk-generated — the writer
  exists, the planner proposes none). `frontmatter_extra` fixed for
  `brand_service` (its service is `segs[0]`, the brand is `segs[-1]`).
- **[#810](https://github.com/kssabraw/ar-tools/pull/810)** — **generalized
  `brands` into service variations** so the auto-matrix works for any trade, not
  just equipment brands. A top-level service carries a `variations` list of
  `ServiceVariation{label, kind}` (`kind ∈ {brand, type}`);
  `service_variation_pages` emits **brand** → a brand × service page, **type** →
  a **sub-service** whose title is the label alone ("Oak Tree Removal", no "Oak
  Trees Tree Removal" doubling → `/tree-removal/oak-trees/`). `ServiceEntry.brands`
  is now a computed property; the store parser accepts both the new `variations`
  shape and the legacy `brands` field (→ `kind:"brand"`), so an older stored
  catalog keeps working and migrates forward on save. `variation_scale_gate`
  (>200 cells → acknowledgeable link-equity sign-off). Frontend: the Plan tab's
  brands input became a per-service **"Service variations"** editor (label +
  Type/Brand kind), normalizing legacy `brands` on load.
- **[#815](https://github.com/kssabraw/ar-tools/pull/815)** — the team user guide
  (`docs/website-builder-user-guide.md`) documents Service variations.
- **[#819](https://github.com/kssabraw/ar-tools/pull/819)** — adversarial-review
  fixes: (a) the store parser mirrors the frontend's "variations wins" rule —
  legacy `brands` are read ONLY when the `variations` key is absent (presence of
  the key, even `[]`, means the catalog is migrated), so the two can't double up
  server-side; (b) a synthetic `type`-variation's generation keyword is scoped by
  its parent service (`generation_inputs` → "Emergency AC Repair"), skipping the
  join when the service name is already in the label — so a bare label like
  "Emergency" on two services no longer generates identical keyword+location
  pages; the page TITLE stays bare and real catalog sub-services are unchanged.
  (Also caught a process gotcha worth repeating: `git checkout main` had landed
  on a **stale local `main`** and silently reverted the working tree to
  pre-change files — always `git reset --hard origin/main` before reviewing
  merged work.)

**Verification pattern held:** built BOTH `/ac-repair/carrier/` (brand) and
`/tree-removal/oak-trees/` (type → sub-service, clean "Oak Trees" title) in
`site-template`; 280 website unit tests pass; CI green (pytest + Netlify) on
#807 and #810. No template change for the generalization — `type` variations are
standard `sub_service` pages the template already renders (the synthetic
sub-service's keyword falls back to the page title). **What's left of the
roadmap:** only Tier B (the ⭐ extension types — cost/problem-symptom/FAQ/
projects/comparison), which still need both a template screen AND an engine; see
the entry below.

---

## ⏩ Update — 2026-08-27 · **Website Builder — future page-type engines (ROADMAP; Tier A now built above)**

**Why this entry exists.** The generation layer routes every planned page to
whichever suite writer owns its type (`website_generate.generation_inputs` →
`nlp` / `run` / `core_pages` / `template`). A handful of **reference page types
have no writer engine yet**: the planner is wired to *detect* them and record
`engine: None` (surfaced as `engine_unavailable:<type>` / the
`template_coverage_gate`) rather than fake them. **In practice today the planner
emits none of these**, so every currently-plannable page has a writer or renders
from data — this is a forward roadmap, not a live gap.

**The types, in two tiers (source of truth: `services/website_plan.py`
`NLP_PAGE_TYPES`, `services/website_content.py`
`_COLLECTION_BY_PAGE_TYPE`/`UNRENDERABLE_PAGE_TYPES`, `site-template`
`content.config.ts`):**

- **Tier A — template exists, only a writer engine is missing. ✅ BUILT (#807 +
  #810, see the entry above).**
  - **`brand_service`** (brand × service, e.g. `/ac-repair/carrier/`) — collection `services`.
  - **`hyper_local`** (a hyper-specific service×place page) — collection `local-landing`.
- **Tier B — ⭐ extension types with ratified URLs but NO template AND no engine.**
  `UNRENDERABLE_PAGE_TYPES` is an intentionally-empty frozenset today; the first
  plan that proposes one trips `template_coverage_gate` (blocking-but-
  acknowledgeable). Each needs **both** a new template screen (added in Claude
  Design + compiled, or mapped onto an existing collection) **and** a writer
  engine:
  - **cost / pricing**
  - **problem / symptom**
  - **standalone FAQ**
  - **projects** (portfolio / case-study)
  - **comparison** (X vs Y)

**What "add an engine" concretely means** (per type): (1) add the type to
`NLP_PAGE_TYPES` or give it a branch in `generation_inputs` returning a real
`engine` + keyword/location; (2) for Tier B, add its template screen +
`_COLLECTION_BY_PAGE_TYPE` mapping and remove it from `UNRENDERABLE_PAGE_TYPES`;
(3) point it at a writer — most reuse `local_seo_service.generate_page` with a
tuned prompt, `comparison`/`cost` may be better as a `run`-engine blog variant;
(4) teach the planner to actually EMIT it (an emitter in `website_plan.py`), since
today none are proposed.

**Also thin-but-not-broken (no roadmap action needed):** `blog_archive`,
`sitemap`, `services_index`, `areas_we_serve` are `template`-engine — they render
from the published-pages query with **no body writer**. Reference "Writer #6"
would add narrative depth to the two index hubs; until then they ship as accurate
hubs, not broken pages.

---

## ⏩ Update — 2026-08-27 · **Website Builder content creator — ALL MERGED + LIVE, frontend UI shipped, user guide added**

Everything the two sections below describe is now **merged to `main` and live in
production**. The "nothing is merged yet" / "frontend UI not built" caveats in
the 2026-08-26 (pm) entry are **superseded by this one** — read this first.

**What merged (all squash-merged to `main`):**
- **[#740](https://github.com/kssabraw/ar-tools/pull/740)** — the backend +
  template: content_plan model, post/pillar planner, `run` engine, effective-
  frontmatter publish gate, seed bridges (strategist + Fanout), the drip-release
  schedule (`website_releases`, migration `20260826140000`, applied live), and
  the cross-family fix (a local site's `/blog/` is planned + dripped alongside
  its geo pages).
- **[#796](https://github.com/kssabraw/ar-tools/pull/796)** — the **frontend UI**
  the #740 entry lists as "NOT built": `ContentPlanEditor.tsx` (Plan tab, **every
  site type**) with the two one-click **seed buttons** (strategist / Fanout
  session id) + `ScheduleTab.tsx` (the drip-release schedule) + PlanTab gating
  the service/city "Build plan" cards to **geo sites only** while the blog
  content-plan editor shows for all. So the whole feature is now editable in-app.
- **[#800](https://github.com/kssabraw/ar-tools/pull/800)** — a **team-facing
  user guide**, `docs/website-builder-user-guide.md`: a no-code, dashboard-only
  tutorial of the full lifecycle (create → provision → theme → plan (services/
  cities + the blog content plan) → approve → generate/publish → drip-release →
  deploys → settings), with a quick-reference table and an FAQ whose first entry
  answers the recurring "my local site's plan shows no blog posts" question (the
  blog is driven by the Blog content plan editor, which starts empty).
- **[#801](https://github.com/kssabraw/ar-tools/pull/801)** — CLAUDE.md now
  references the user guide and records the frontend UI as built.

**Production flag flipped ON (owner asked 2026-08-27):** `WEBSITE_BUILDER_ENABLED=true`
on the PLATFORM Railway service. **Railway gotcha that cost time:** `set-variables`
**staged** the value but did **not** roll a fresh container (the running deployment
kept serving the old value — confirmed by the container timestamp in logs
being unchanged after the variable write). A **`redeploy`** was what actually
applied it. `WEBSITE_IMAGES_ENABLED` was **deliberately left off** — it bills a
per-page image render, flip it separately when hero images are wanted. Both
Netlify (frontend) and PLATFORM (backend) are deployed; the **Website Builder
card** now appears on the client workspace (gated on `GET /websites/status`,
which the restarted container returns `{enabled:true}` for; TanStack caches it
~5 min, so a hard refresh surfaces it).

**Where to use it:** client workspace → **Website Builder** card (route
`clients/:id/website`), or the sidebar **Websites** fleet view (`/websites`).
The blog on a local site lives behind the **Blog content plan** editor on the
**Plan** tab (below Service catalog / Cities) — empty by default, which is why a
fresh local site's plan shows only service/city/matrix pages until you add silos
+ posts (or seed them) and Save.

---

## ⏩ Update — 2026-08-26 (pm) · **Website Builder — informational content creator + drip-publish release schedule BUILT (PR #740)**

> **Superseded by the 2026-08-27 entry above** — #740 (and the frontend, user
> guide, and flag-on that followed) are all merged and live now. Kept for the
> build detail; ignore its "nothing is merged yet" / "frontend UI not built"
> caveats.

The gap mapped in the section below is **built**. PR
[#740](https://github.com/kssabraw/ar-tools/pull/740) (draft, green CI,
`mergeable_state: clean`) is on branch
`claude/website-builder-content-creator-70iu8b`. Nothing is merged yet — it is
ready for the owner to review/merge. What follows is the "so the next chat
doesn't re-derive it" summary; CLAUDE.md's Website Builder bullet carries the
durable version.

### The decision that was surfaced first (owner-confirmed)

**Who owns an informational site's cluster inventory?** Confirmed: the **Website
Builder owns it** in `websites.config.content_plan` — editable, durable across a
re-research, reviewed/approved through the same plan flow as the geo matrix —
rather than reading a research run at build time. A **one-shot seed bridge**
copies a research plan in once; after that it is the site's own data. This keeps
informational sites inside the existing plan → approve → generate → publish
machinery instead of coupling site structure to a research run.

### What was built (5 commits on the branch)

1. **The five planning/generation pieces** (`website_plan.py`,
   `website_content.py`, `website_generate.py`, `website_publish.py`): the
   `content_plan` model (`PostEntry`/`PillarEntry`), posts at `/blog/{slug}/`, a
   **pillar/hub** at top-level `/{topic-slug}/` once a silo has ≥5 **evergreen**
   posts (`news` excluded), a **`run` engine** (a blog Writer run whose angle
   rides on `writer_notes`, linked back `content_source="run"`), the effective-
   frontmatter publish gate + first-paragraph meta description. **No migration**
   — reuses the `website_page_generate` job, `content_source='run'`, and the
   free-text `page_type` column.
2. **Template** (`site-template`): a `pillars` collection + top-level route via
   `[...path]`, pillars surfaced on home/nav/sitemap. Verified by **building both
   site types** (the rule that keeps earning its keep).
3. **Strategist seed bridge** — `import_from_strategist` maps the client's latest
   `keyword_topic_strategist` plan into `content_plan`.
4. **Fanout seed bridge** — `import_from_fanout(session_id)` maps a finished
   Topic Fanout session's silos/clusters in. **Owner ruling: OPTION 1, always
   regenerate fresh** — copies only the topics/keywords, never links the
   session's already-generated articles.
5. **Release (drip-publish) schedule** (`website_release.py` + `website_releases`
   table + `website_pages.released_at`, migration `20260826140000` applied live)
   — publish an immediate batch, then N per **day/week/month**. **Owner ruling:
   generate + publish on the drip** (Fanout-style, just-in-time), via a
   `publish_after` flag on the existing generate job — **no new job type**.
6. **Cross-family fix** (owner caught it): blog posts are planned for **every**
   site type, so a **local SEO site's `/blog/` is filled from its content plan**
   alongside its service/location pages, and the release schedule drips **both**
   its geo pages and its blog (acts on `NLP_PAGE_TYPES ∪ RUN_PAGE_TYPES`).

### What is NOT built (deliberate follow-ups)

- **Frontend UI** for the content plan, the two seed buttons, and the release
  schedule — backend + template only, consistent with the module's build so far.
- **Local-site pillar hubs** are reachable (home Guides grid + sitemap + own URL
  + they link down to posts) but a **post→pillar up-link** and **pillar-in-local-
  nav** are not wired.
- Local geo pages already drip; a per-page-type immediate-vs-drip split beyond
  ordering is not built.

### Verification rule that keeps earning its keep

Still true, and used again this pass: **build both site types in `site-template`**,
not just the unit tests. The local-with-a-blog build (geo pages + posts + a
pillar, 14 pages, no namespace conflict) is what confirmed the cross-family fix.

---

## ⏩ Update — 2026-08-26 · **The Apps Script publish webhook: which project, which deployment, and how to redeploy it**

**Why this entry exists.** Closing out the deploy-safety work needed one webhook
change, and finding *which script to edit* took longer than writing the change.
Nothing recorded the project name or the deployment id — only "the 2026-07-07
deployment". Two traps cost the time; both are written down here so they cost it
once.

**The live webhook.** Apps Script project **"AR Tools Google Docs Webhook"**,
script id `1EoBPm2VqU-GlloClByKq6BVqIs9-6AsZVbraw9DahEG_1NBBmHSiduep`
(https://script.google.com/d/1EoBPm2VqU-GlloClByKq6BVqIs9-6AsZVbraw9DahEG_1NBBmHSiduep/edit).
Source of truth in-repo: `writer/apps-script/publish_webhook.gs`. It serves the
doc / `type:"sheet"` / `type:"pdf"` branches, `share`, `format:"html"`, image
embedding, and (2026-08-26) `dedupe_by_name`.

**Trap 1 — the decoy project.** A second project, **"AR Tools Publisher"**
(created 2026-05-01, untouched since), is the *original markdown-only* script:
no `sheet`, no `pdf`, no `share`, no `format`. It is NOT the webhook. Editing it
changes nothing, and because it looks plausible it is the one you find first.
Consider renaming it `AR Tools Publisher (OLD — unused)`.

*How it was ruled out, if you ever need to redo this:* `upload_pdf` hard-fails
with `pdf_not_supported` unless the webhook returns a `file_id`, and the decoy
has no `pdf` branch — yet 20 of 26 `client_reports` rows carry successful Drive
delivery. So the live script could not be that one. The definitive check is
comparing a deployment's exec URL against `GOOGLE_APPS_SCRIPT_URL` on the
PLATFORM Railway service.

**Trap 2 — two active deployments.** The real project has two, differing only
after `/macros/s/`:

| Prefix | Was | Now |
|---|---|---|
| `AKfycbxTjwbZYB…` | Version 8 (Jul 6) — **PRIMARY: the one `GOOGLE_APPS_SCRIPT_URL` points at** | Version 10 |
| `AKfycbyfvDYYs…` | Version 1 (Jun 27) | Version 9 |

**Resolved 2026-08-26:** `GOOGLE_APPS_SCRIPT_URL` holds the
`AKfycbxTjwbZYB…` / Version 10 deployment — verified by revealing the value in
the Railway **dashboard** and full-string-matching it against the deployment id
(not just the prefix). Both deployments' descriptions now say which is which.
Note the value is readable ONLY in the dashboard: every API client (the Railway
MCP, an OAuth app) gets variable names with values redacted, which is what made
this take two attempts to settle.

Even so, **bumping BOTH on a redeploy stays the default** — webhook changes here
are additive and opt-in, so it is free insurance against this drifting again.

**Redeploy procedure.** Edit the code → save → **Deploy → Manage deployments →
pencil icon → Version: "New version" → Deploy**. ⚠️ **Never "New deployment"** —
that mints a *different* exec URL while `GOOGLE_APPS_SCRIPT_URL` keeps pointing
at the old one, so prod silently keeps running the old code with no error
anywhere. Authorization is only re-prompted when a change introduces a NEW
Google service (Sheets, UrlFetchApp did; `dedupe_by_name` did not — it reuses
`DriveApp`). If you drive this UI with a browser agent: the pencil icon
silently swallows clicks while the Manage-deployments dialog is still animating
open, and the dialog settles at two different sizes depending on timing — wait
for each control's position to stop moving before clicking, or the early clicks
land on nothing.

**Deployment labels vanish on every redeploy — this is expected.** The name shown
in the Manage-deployments list is just a mirror of the deployment's Description,
and **cutting a new version resets it to "Untitled"**. That is why the 2026-08-26
redeploy appeared to wipe the "AR Tools Google Docs Webhook" label, and it cost
confusion twice in one session. Two consequences: (1) after any redeploy, expect
to re-enter the descriptions; (2) **always identify a deployment by its version
number or its `AKfyc…` deployment ID, never by the list label** — the label may
be blank, stale, or duplicated across both. Editing a description alone does NOT
cut a version (verified: the list still topped out at Version 10 afterwards).

**Verifying a deploy landed.** Two options, in order of convenience:
1. Read the project source back through Drive (`download_file_content` with
   `exportMimeType: application/vnd.google-apps.script+json`) and confirm the
   code is present — this is how the 2026-08-26 change was verified, and it
   works from an agent session.
2. Exercise it: POST the same `{folder_id, title, …, dedupe_by_name: true}`
   twice against a scratch folder; the second reply should carry the SAME id
   plus `"reused": true`. **Note the sandbox cannot do this** — the agent proxy
   denies `script.google.com` (403 on CONNECT), so run it from a real terminal.

**Current state.** Both deployments serve the 2026-08-26 code; the syndication
duplicate-Doc guard (PR #758) is live. The un-run item is option 2 above — a
live round-trip test, which only matters on a retry path and is not blocking.

## ⏩ Update — 2026-08-26 · **Brand-voice QA: the judge was too generous — hardened the scoring rubric across both writers + turned on nlp/pipeline CI**

**Problem.** The separate brand-voice scorecard (the 8-dimension LLM judge, not
the deterministic checks) was scoring off-brand pages "fine." Pulled the real
distribution from `<page>.voice_violations` to confirm — across **all 17 pages
scored since the voice system shipped 2026-07-31** (the other 200 are pre-guide
and correctly unscored): composites clustered **81–87** (Local SEO avg 84.2,
Ecommerce 81.3), nothing ≥90, almost nothing <80. Textbook LLM-judge
central-tendency.

**The insight that wrote the fix.** Per-dimension, the **only** dimension
producing honest, well-spread scores was `distinctiveness` (avg **71.5**, range
55–82) — and it is the **only** dimension whose prompt line was already framed
adversarially ("could a competitor use this by swapping the name? score LOW").
The other seven ("score how faithfully it follows the guide") inflated: tone
86.8, writing_style 84.3, vocabulary 80.4. So it was a controlled experiment —
adversarial framing works; extend it to the other seven.

**What changed (PR #743, open).** Hardened **both** judge prompts — they are
separate and have **no sync-guard** (unlike `voice_card.py`):
- `nlp-api/main.py::_VOICE_SCORE_PROMPT_SUFFIX` — the page judge, consumed by all
  four page scorers (`_score_system_prompt_for` local/national,
  `_ecommerce_score_system_prompt_for`, `_blog_score_system_prompt_for`).
- `pipeline-api/modules/writer/voice_review.py::_SCORE_SYSTEM` — the blog/service
  **article** judge (its own rubric; would have stayed generous otherwise).

Each got: anchored 0–100 bands with **60–74 "competent but anonymous" as the
DEFAULT** for a page that reads fine but isn't distinctly the client; "never
award 75+ for the mere absence of errors"; **worst-section evidence** (quote
where it drifts, score to that); an 85+ justification guardrail; per-dimension
"what LOW looks like" cues. **Output contracts unchanged** (page: `brand_voice`
key; article: bare 8-dim object) → parsers, `voice_scorecard` math, weights,
`VOICE_PASS_THRESHOLD` (80), deterministic caps all untouched. Verified locally
as far as the sandbox allows (py_compile; `test_voice_card` 54 pass; isolated
article-path integration).

**Validation — the next real step, must run on PLATFORM.**
`platform-api/scripts/revalidate_voice_scores.py` re-scores the baseline pages
through the deployed nlp path and prints before→after distributions +
per-dimension means. Read-only w.r.t. the stored baseline (records a score-run
history row like a UI "Score", never overwrites `voice_score`/`voice_violations`;
`--write` persists once trusted; `--limit` smoke-tests). The **sandbox can't
reach the private nlp service**, so run it in a Railway shell on PLATFORM.
Expected: the 81–87 mass spreads to **~62–80**, on-brand pages still reaching
high 80s. Caveats it prints: re-score uses the client's *current* voice card
(clean rubric comparison only where the guide is unchanged); local pages with an
empty/unrecognized `location` error out (excluded, not scored 0).

**Deferred until that re-score is measured (do NOT guess now):** raise the
`distinctiveness` weight (.10→.15) and revisit `VOICE_PASS_THRESHOLD`. Scores are
stored, so recalibration needs no re-billing beyond the one re-score.

**CI coverage (PR #746, open).** Only platform-api ran in CI, so both prompt
changes above had **no automated gate**. Added `.github/workflows/
nlp-api-tests.yml` + `pipeline-api-tests.yml` (mirror `python-tests.yml`; nlp got
a CI-only `requirements-dev.txt`). nlp-api went green; **pipeline-api immediately
caught two pre-existing failures** (1327 passed, 2 failed) invisible because the
suite never ran — both fixed in the same PR:
1. `test_pipeline_metadata_threshold_echo` — stale assertion (0.55) vs
   `config.brief_relevance_floor` raised to 0.65 in #688.
2. **Real bug** in `brief/assembly.py::_apply_title_case` — it title-cased each
   content H2 but left child H3s' `parent_h2_text` on the old casing, so an H3
   referenced a "nonexistent" parent. Fixed by realigning H3 parent pointers to
   the re-cased H2 in the same pass (idempotent).

**Open items for the next session:** (1) run the re-score on PLATFORM and record
the spread; (2) recalibrate weight+threshold from it; (3) land #746 green (CI
re-running after the two fixes) then #743; (4) longer-term, fold the two judge
prompts into one seam so they can't drift again (the scorecard math is already
shared; the prompts are not); (5) 146 live pre-guide pages still carry no voice
verdict — a backfill via voice-aware reoptimization.

## ⏩ Update — 2026-08-26 · **Client Reporting — report-content upgrades (all merged + live)**

A run of improvements to the client-facing PDF report shipped this session — each
its own PR, squash-merged to `main`, auto-deployed to PLATFORM (each verified
`SUCCESS`), and gated by the platform-api `pytest` GitHub Actions workflow (five
code PRs #741/#742/#744/#745/#748 + a docs PR #747). All
are additive rendering changes in `services/client_report.py` +
`services/brand_report_html.py`; two carry additive migrations (applied live).
Toggles default off, so nothing changes for a client until an account manager
opts in on the ClientReports **Delivery & schedule** card.

- **#741 (`ad26fb1`) — scheduled standalone report types.** The recurring
  schedule (`client_report_schedule.enqueue_due_report_schedules`) now also
  emits, per opt-in, the **AI Visibility** report (`report_type="ai_visibility"`
  — the 2026-07-06 fold-in decision finally executed) and a **new Local Rank
  (Maps) report** (`report_type="maps"`, `_build_maps_report` — a self-contained
  geo-grid PDF reusing the combined report's own `_gather_geogrid` +
  `_section_geogrid`; deterministic, no LLM, on purpose). Opt-in via
  `client_report_settings.ai_visibility_enabled` / `maps_enabled` (migrations
  `20260826140000` + `20260826150000`; the latter also widened the
  `client_reports.report_type` CHECK to include `maps`). Gated on the client
  actually tracking the matching keywords (empty-report guard); the pending-report
  guard is now `report_type`-scoped so the three deliverables don't block each
  other; delivery reads the report row generically so both new PDFs email +
  Drive-copy unchanged. The per-keyword Maps **Local Rank Analysis Docs** stay a
  separate on-scan-completion deliverable — not folded in.
- **#742 (`779f670`) — clearer Rank trend + month-over-month + GBP Insights.**
  The organic "Trend" column is relabeled **"Rank trend (last 90 days)"** with a
  legend (the sparkline already plots better ranks higher — it just had no
  label). Maps + AI-visibility gained month-over-month callouts with
  **per-keyword deltas** (`_gather_geogrid` pulls the previous reporting scan's
  per-keyword rows; `_gather_ai_visibility` the previous batch's found-counts;
  standalone `brand_report_html` gained a prev-period overall + per-keyword
  column). The **GBP Insights** section (`_section_gbp` — rating + new reviews +
  highlights + the `_gather_gbp_metric_growth` performance table) was
  **re-enabled** in the combined report (it was built-but-disabled) and added to
  the standalone Maps report. Note: `gbp_metric_daily` is keyed by
  `location_row_id`, **not** `client_id` — a naive `client_id` count reads 0 even
  for clients that have data (it joins through `gbp_locations`).
- **#744 (`3f70b96`) — 30d / 90d / since-start comparison horizons.** A
  single-window comparison tied to the report period is volatile (a 30-day
  report only ever showed a 30-day delta), which the owner flagged as hiding
  wins. **Performance highlights** now shows **Now / vs prev 30d / vs prev 90d /
  since-we-started** columns — pure `build_multi_comparisons` anchored at
  `period_end`, each horizon **omitted ("—") when the data doesn't span both its
  windows** (no fabricated partial deltas). Maps (`presence_horizons`) and
  AI-visibility (`visibility_horizons`) get the same section-level three-horizon
  callout (vs the scan/batch nearest each horizon + the first scan/batch). The
  single-window `build_comparisons` is kept for the KPI strip.
- **#745 (`d3b3a55`) — executive summary longer time frame.** The `emit_summary`
  tool gained a required **`long_term_progress`** field rendered as a green
  **"The bigger picture"** callout under the headline; the exec context now
  carries the three horizon sets so the model cites the durable 90d/since-start
  trend positively, leading with the longer view when a single month dipped and
  saying "early and building momentum" (never an invented number) when long-term
  data isn't there yet.
- **#748 (`a79c0cc`) — every tracked keyword in Organic rankings.** The combined
  report's `_section_organic` trimmed to the top ~5 movers with a "remaining N —
  full list on request" note; owner wants the full table. It now renders **every**
  tracked keyword, sorted strongest current position first (unranked last), with
  per-row Movement + rank-trend intact — so a slip shows honestly now (the old
  design deliberately hid decliners). Dropped the top-movers selection + the
  now-unused `_TOP_MOVERS` constant; raised `_gather_organic`'s `_MAX_KEYWORDS`
  cap **40 → 250** (runaway ceiling, not a display trim) because several clients
  track 50–96 keywords (UMH 96, Southwestern Hearing 60, EML 58, WheelHouse FL 50)
  — those clients now get a **multi-page** organic table, which is the accepted
  cost of "all keywords" (flag if a cap/hybrid is wanted for the very large ones).
- **#747 (docs)** — recorded #741/#742/#744/#745 in CLAUDE.md + HANDOFF.md.

**Live-data caveat (tell whoever tests this):** the horizons + month-over-month
only render where the history supports them. **Organic rank** runs long, so
Performance shows all three horizons today (verified on First Class Roofing:
Feb→Aug). **Maps + AI-visibility** scan history is younger than 90 days for
every current client, so their 90d/since-start rows correctly read "—" and fill
in over the coming months. A good end-to-end test client is **First Class
Roofing** (real previous Maps scan for MoM + real GBP metric growth; its AI
scans are a single day so AI MoM won't show).

**Infra note — the pytest gate is intermittent.** The platform-api `pytest`
workflow (added 2026-08-15, path filter `writer/platform-api/**`) **triggered for
#744/#745/#748 but did NOT fire for #741/#742** despite matching the same filter
and firing normally on other `claude/*` PRs. All were validated locally (74–80
report tests green) and merged clean. Unresolved; worth a glance if a
platform-api PR merges without its Python tests having gated it.

## ⏩ Update — 2026-08-26 (am) · **Website Builder — where it stood before PR #740, and the informational gap that is now built above**

Nothing was built in this pass. This section records **what is finished**, the
one thing that was silently broken and is now fixed, and a precise map of the
**informational gap** — which is **now built (see the section above)**, kept here
for the reasoning trail.

### Finished since the 2026-08-07 section

- **PR #575 merged** (`6e12bbb`) — theme compiler, core-pages writer, imagery.
- **PR #577 merged** (`473feee`) — the **per-site business-facts Settings tab**
  (`services/website_settings.py` + `components/website/SettingsTab.tsx`). Seven
  editable NAP/business facts, each stamped `provenance:"user"` so a later GBP
  re-scan fills **gaps only** and never overwrites a typed value; clearing a
  field drops the value *and* its stamp so it hands back to GBP. Saving
  re-commits `site.config.json` via `record_deploy(..., trigger="config")`. The
  pure helpers are tested against the **real** `build_site_config` fill step,
  because the editor and the fill step are only correct together.
- **PR #622 merged** (`c0397f7`) — ten defects from an adversarial re-read.
- **PR #624 / #681** — flags-on record, then design-fidelity layout variants.
- **Flags ON in production** (`WEBSITE_BUILDER_ENABLED` +
  `WEBSITE_IMAGES_ENABLED` on PLATFORM). Code defaults stay `False`, so a fresh
  environment still ships dark. Verified **behaviourally** (Railway redacts
  variable values for OAuth callers): the logs show `enqueue_due_deploy_polls`
  running its query, which returns early when the flag is off.
- **Nothing has ever been created by the module.** `websites`, `website_themes`,
  `website_pages`, `website_deploys` are all **0 rows**. (The 16 `website_*`
  jobs in `async_jobs` are the unrelated `website_scrape` client-site scraper.)

### The two bugs worth remembering

**1 · The narrowed select.** `website_generate` fetched the site row with
`.select("id, client_id, name")`. Every downstream writer therefore saw
`config == {}` and `site_type == "informational"` — so a business fact typed into
the Settings tab was silently ignored in favour of GBP, the tagline never reached
the prompt, and **every local site would have been written with informational
framing**. Fixed to `.select("*")`.

The part worth keeping: **my first regression test passed against the broken
code.** The test fake ignored column projection and returned whole rows whatever
was asked for. A fake more generous than the real dependency cannot catch that
class of bug. `tests/test_website_generate.py::_supabase` now honours
`.select(...)`, and the fix was verified fail-on-old / pass-on-new.

**2 · The stale template repo.** `kssabraw/ar-site-template` — the repo every
site is minted from — had not been synced since 2026-08-03. It was missing the
`site.ts` crash fix, the `hubs.ts`/nav fix, both hub routes and
`[...path].astro`. **Every site provisioned from it would have failed its first
build.** Full tree replacement pushed as `24e8416`. There is no automation
keeping `site-template/` and the GitHub template repo in sync; that is a real
gap, and re-checking it is cheap.

The other eight fixes, briefly: fonts failing open when the census measured none
(the one case the model had nothing to copy from was the one case it was free to
invent — now `no_fonts_measured`); raw `website_deploys` inserts bypassing
`record_deploy`, so a deploy chip sat at `queued` until the next scheduler sweep;
`site_type` never reaching the core-pages prompt (it is live now, with an
explicit informational framing that forbids sales copy); `_clean` treating a JSON
*number* as a clear, which deleted a field and dropped its `user` stamp;
`business.hours`/`areaServed` missing from `build_site_config`, which would have
crashed the **first** contact-page build of any local site (fixed at both the
producer and the template layer); six reads per save; a provision/settings config
clobber; brand tone read from the wrong nesting level; and a dead
`website_image_provider` setting, removed.

### Is it usable end to end?

**Local / lead-gen: yes, on paper** — design → theme → provision → plan →
generate → publish → deploy is wired and each stage is tested. **It has never
been run against a real design for a real client**, so the first live run should
be treated as a smoke test, not a delivery.

**Informational: no.** A plan for an informational site contains four content
pages and a blog archive with nothing in it.

### The informational gap, precisely

The **rendering half is already complete** — this is the surprising part, and it
means the build is smaller than it looks:

| Already built | Where |
|---|---|
| `posts` collection, five formats (`informational_cluster`/`listicle`/`comparison`/`local_geo`/`news`) | `site-template/src/content.config.ts:100` |
| `/blog/[...slug]` route + archive | `site-template/src/pages/blog/` |
| `post` → `posts` collection mapping | `website_content.py:41` |
| Post-specific `entry_id` (entry id IS the slug — a full-path id would publish `/blog/blog-my-post/`) | `website_content.py:122` |
| The **strict** post publish gate | `website_content.py:272` |
| Post body assembled from a blog run's `module_outputs` markdown | `website_publish.resolve_source`, `kind == "run"` |
| `post` is hero-eligible and its image prompt is never geo-tagged | `website_images.py` |

The post gate is deliberately stricter than anywhere a human is in the loop,
because auto-publish means nobody reads a post before the public does: a critical
voice violation and a `-degraded` writer run are **non-overridable**; frontmatter
must carry title/description/format; a `news` post must carry `reviewBy`
(non-evergreen + auto-publish + no expiry is how a site ranks on stale
information indefinitely). Keep that; do not soften it to make the first post
ship.

**What is missing is the planning and generation half — five things:**

1. **`website_plan.build_plan` never plans a post.** Every non-geo site falls
   through the `else` branch, so an informational plan is home / about-us /
   contact-us / privacy-policy / sitemap / blog. No pillars, no clusters, no
   posts. (`website_plan.py:608`)
2. **No `post` engine.** `generation_inputs` returns `{"engine": None}` for any
   page type outside `NLP_PAGE_TYPES` ∪ `CORE_PAGE_TYPES` ∪
   `TEMPLATE_ONLY_PAGE_TYPES`, so a planned post would report
   `engine_unavailable:post`. (`website_plan.py:635`, `:717`)
3. **No post frontmatter.** `frontmatter_extra` has no `post` branch, so
   `format`/`silo`/`cluster` would be absent and the publish gate would —
   correctly — refuse the page. (`website_plan.py:645`)
4. **No generation branch.** `website_generate` has no path that starts a Blog
   Writer run and links it back as `content_source="run"` +
   `source_id=<run_id>`. The publish side of that contract already exists.
5. **Pillar / Hub does not exist at all.** Reference §5.3: `/{topic-slug}/`,
   2,000–4,000 words, Writer #6, planner trigger *a cluster of ≥ 5 posts*. No
   page type, no collection, no route — yet it is the parent every cluster post
   links up to, so a cluster of posts with no pillar is not the page type the
   reference describes.

**The cluster map already exists and is unwired.**
`keyword_topic_strategist` emits exactly the shape the planner needs:

```
{assessment, pillars: [{pillar, rationale,
  clusters: [{title, buyer_problem, search_intent, funnel_stage,
              target_keywords, questions, priority, rationale}]}]}
```

and `keyword_research_handoff` already turns selected keywords into a Fanout
session whose scheduler writes blog posts (`content_type` blog_post |
local_seo_page). `website_plan`'s own docstring records the standing assumption
that *"the fan-out owns an informational site's post plan"*.

**That assumption is the first decision of the next build**, and it should be
made explicitly rather than inherited: either the site plan *reads* an existing
strategist/Fanout plan (cheap, reuses a tested path, but couples site structure
to a research run), or the Website Builder owns its own cluster inventory
(more work, but the plan is then a property of the site and survives a
re-research). Both are defensible; picking silently is not.

Two reference rules the planner must encode either way: **blog posts are planned
per cluster, never ad hoc** — every post carries a silo and a target format
*before* generation — and the `news` format is **non-evergreen and excluded from
pillar-cluster math**.

### Verification rule that keeps earning its keep

Build **both** site types in `site-template/` — not just the unit tests. That is
what caught the variable-font duplication (same bytes downloaded 3× under 3
names, masked by the bundler's content hashing), the `sections` key missing from
the frontmatter order (home copy silently dropped while reporting success), and
the contact-page crash. Unit tests found none of the three.


## ⏩ Update — 2026-08-26 · **LeadOff GBP Placement Advisor — built + LIVE + prod-verified**

The demand-aware **"where should the GBP live"** module — the demand-side upgrade
of the competition-only Proximity signal (an empty octant can be empty of
*people*, not just of competitors). Shipped across **8 PRs, all merged to `main`
+ deployed** (#725 Phases 1+2, #728 + #730 prod-verification fixes, #731
calibration freeze, #732 Phase-0b probe, #733 + #735 docs), building on the
live-GBP market map (#719/#721). Authoritative doc:
**`docs/modules/leadoff-gbp-placement-plan-v1_0.md`** (owner decisions §1;
build-status + prod findings §9a). Full writeup is in that doc + CLAUDE.md's
LeadOff section — this is the operational handoff summary.

**What it does (deterministic, no LLM):** for any point `c`,
`placement_score(c) = 100 × norm(demand_access) × (1 − norm(pressure))` — `demand_access`
sums Census block-group **households** with a `1/(1+d/5mi)` decay; `pressure`
sums competitor GBPs review-weighted with proximity's verbatim `1/(1+d/2mi)`
decay; `norm()` is min-max over the market's OWN 1-mile lattice (market-relative,
never comparable across markets). It surfaces 3–5 ranked, ≥2-mi-apart,
locality-named zones ("Near Maumelle") on the market map + a "Best areas to plant
a GBP" card list, plus a **Phase 2 "Both"** score-any-location panel (click the
map / paste an address or GBP → scored against the zones, side-by-side compare,
optional octant re-anchor).

**Free, $0/market beyond captured pins.** Core: `services/leadoff_placement.py`
(pure) + `services/census_demand.py` (ACS block groups + TIGERweb centroids →
`census_block_demand` cache, filled by the `leadoff_placement` async job). API
`GET /leadoff/placement` + `POST /leadoff/placement/score-point`. Behind
**`leadoff_placement_enabled` (default True — ON in prod)**.

**Activation / env (already set on PLATFORM):** needs **`CENSUS_API_KEY`** (ACS)
+ **`GOOGLE_MAPS_API_KEY`** (zone naming + the static map) + the existing
DataForSEO creds (only for the map-refresh pin pull, not the advisor itself). No
dashboard setup needed. Opening a scouted market with ≥5 live pins auto-enqueues
the Census demand fill on first view (poll `job_id`); markets with <5 pins show
the honest `thin_field` state and a nudge to Refresh map (~$0.004).

**Prod verification earned its keep** — three real bugs, each caught live and
pinpointed by the self-diagnostic built into the job, none catchable by unit
tests:
1. `enqueue_placement` wrote a non-UUID `entity_id` (the column is UUID) → the
   auto-enqueue would throw. Fixed to `uuid4()` + dedupe by `payload->>city_id`.
2. The TIGERweb centroid query used `STATE=/COUNTY=` field names that returned 0
   features. Fixed to `GEOID LIKE '<fips>%'` + `outFields=*`, with a persisted
   `tigerweb_diag` on the job row.
3. `_resolve_bg_layer` matched **"Tribal Block Groups"** (layer 6, listed first)
   instead of **"Census Block Groups"** (layer 10) → all-null centroids. Fixed to
   select the Census layer specifically (`pick_bg_layer`, unit-tested).
After the third fix, a live KC run wrote **1,494 real ACS block groups** and
produced sensible zones — verified end-to-end.

**Phase 3 (paid per-ZIP demand layer) — PROBED & DROPPED.** The ~$0.05 Phase-0b
feasibility probe (`services/leadoff_zip_demand.py`, `leadoff_zip_demand` job) ran
live: 10 Chicago ZIPs (60601–60610) × "plumber" all queried cleanly but returned
`search_volume: null` (`null_share` 1.0 → `inconclusive`). Google thresholds Ads
search volume at ZIP granularity even for a high-demand trade in a major metro,
so a per-ZIP re-weight adds no signal over the free households surface → **not
built**; `leadoff_zip_demand_enabled` stays False, the probe is the record. Total
paid spend for the whole module: **~$0.05**, on the probe that prevented a wasted
build.

**Calibration freeze (§8, built):** the create-client handoff freezes the market's
zone set into `leadoff_predictions.placement` (jsonb) alongside the existing
`proximity` freeze, so the post-client geo-grid can later grade whether high-score
zones matched better pack outcomes — the loop that eventually earns the dollar
layer (still off). Read-only instrumentation; nothing feeds scoring.

**Grade safety is absolute:** placement reads only `leadoff_gbp_pins` +
`census_block_demand` and writes only its own cache — **never** the board grade,
`competitor_locations`, or `proximity_opportunity`.

**Demo market left in place (owner):** **Kansas City / pest_control_service** is
seeded as a working demo — 5 real competitor pins in `leadoff_gbp_pins` + 1,494
real ACS rows cached. To remove the pin seed later:
```sql
delete from public.leadoff_gbp_pins where city_id=4393217 and category_id='pest_control_service';
```
(The `census_block_demand` rows are legitimate real ACS cache — fine to keep.)

**Migrations (all applied live):** `20260825140000` (map refresh),
`20260825150000` (`census_block_demand`) + `20260825160000` (async_jobs CHECK),
`20260826120000` (`leadoff_predictions.placement`), `20260826130000` (async_jobs
CHECK + `leadoff_zip_demand`).

**Remaining (owner call, not started):** the **dollar layer** — gated on the §8
calibration loop showing signal (needs real post-client geo-grid outcomes to
accrue first).

---

## ⏩ Update — 2026-08-25 · **LeadOff market-map interactions + two-maps sync (PR #721, MERGED + DEPLOYED)**

Owner-driven UX polish on the live-GBP market map, shipped in the **same PR #721**
as the Refresh-map affordance below (squash-merged to `main` as `f2da79d`,
auto-deploys PLATFORM + rebuilds the Netlify frontend). All in
`frontend/src/components/leadoff/MarketMap.tsx` (+ a `place_id` field threaded
through `ProximityRead.pins` / `MarketMapPin` in `pages/LeadOff.tsx`).

**What changed, in order of how it landed:**
- **Per-pin interactivity.** Each competitor pin is a link to its **exact GBP**
  (`place_id` → `maps/place/?q=place_id:…`, else a name/coord search), and
  hovering shows a card with the business **name / ★ rating / reviews / distance**
  plus a "View on Google" link. The hover card flips below the pin for top-row
  pins and spills past the map edge (outer container `overflow: visible`; the
  image keeps its clipped rounded border). `place_id` was already captured for
  live pins by `_map_pins`; it just wasn't typed on the frontend.
- **Two-maps sync (owner: "users are going to get confused").** The map + pins
  show only the **ranked competitors we captured** (bounded: SERP depth ~20,
  coords-required, within the analysis radius, exact keyword). A Google Maps link
  can't be limited to that exact set — it always renders Google's **full live
  directory** — so a whole-map "Open in Maps" jump read as the two maps
  disagreeing. **Resolution (owner chose "exact links only"):** the base map is a
  **static snapshot, not a link**; the only place-level jump to Google is
  **per-pin** (place_id-exact, always in sync with what's plotted).
- **Separate "Browse all …" escape hatch (owner request).** A **clearly-distinct,
  labelled** link *below* the map — `Browse all "<category>" businesses on Google
  Maps` with a sub-note that it opens Google's full live directory (more listings
  than the ranked field above). Framed as its own action, never as "the same
  map". Driven by a new optional `browseQuery` prop (the market's humanized
  category slug).

**Why the counts differ (for future reference):** the tool map is the *ranked
competitive field for one keyword* (a curated, bounded snapshot from a single
DataForSEO Maps SERP), not the exhaustive local directory Google shows live. This
is by design; the per-pin `place_id` links are the only guaranteed-exact bridge
between the two.

Frontend-only; `tsc` + `vite build` clean; platform-api tests green on the merge.

---

## ⏩ Update — 2026-08-25 · **LeadOff market-map "Refresh map" affordance (follow-up #3)**

Follow-up to the live-GBP market map below. Closes the gap where a **fully-cached
scout can't (re)generate its map**: `fetch_market_pins` (the ~$0.004 Maps SERP
that captures GBP pins) only fired inside a full scout, and a fully-cached scout
returns `{job_id: null}` and runs nothing — so every market scouted before the
pins feature shipped (2026-08-21) showed octant bars but **no map**, with no way
to get one short of 90-day cache expiry.

**What it adds:** a lightweight **`leadoff_map_refresh`** async job that re-pulls
ONLY the market's live competitor GBP pins (one Maps SERP, `COST_MAP_REFRESH` =
$0.004), decoupled from the RD/velocity/trend/footprint enrichment. Surfaced as a
**"Refresh map (~$0.004)"** link on a market whose map is already showing, and as
**"Plot the live GBPs (~$0.004)"** on a not-yet-scouted market (the cheap
alternative to a full ~$0.70 scout just to get the map) — including the
`no_geocoded_competitors` empty state.

**Files:** `services/leadoff_actions.py` (`COST_MAP_REFRESH`, `market_display`,
`enqueue_map_refresh`, `run_map_refresh_job`), `services/job_worker.py` (dispatch),
`routers/leadoff.py` (`POST /leadoff/map-refresh`, staff-gated + budget-checked +
spend-recorded as `"map_refresh"`; job added to the `/leadoff/jobs/{id}`
allowlist), `frontend/src/pages/LeadOff.tsx` (`MapRefreshButton`, wired into
`ProximityCard`/`ProximityDetail`).

**Safety:** an empty/failed SERP (`fetch_market_pins` returns `[]` on any error)
**skips persist entirely** — `persist_gbp_pins_batch`'s delete-stale step would
otherwise wipe the market's prior pins on an empty batch, so a bad pull leaves the
existing map intact (unit-tested). Reuses the separate `leadoff_gbp_pins` table,
so a refresh still never shifts the board grade (Census pins unchanged).

**Migration `20260825140000_leadoff_map_refresh_job.sql`** (adds the job type to
the `async_jobs` CHECK) — **applied live** to `AR-Internal-Tools`. Tests:
`tests/test_leadoff_map_refresh.py` (persist-only-non-empty, empty-preserves,
unknown-market-fails); 115 leadoff tests green + frontend build clean.

**Still open (deliberately deferred, owner "v1 is a start"):** click-to-drop a
candidate pin (#1) + re-anchoring the octant math on a chosen point (#2), and the
sparse-category (<5 pin) read polish (#4).

---

## ⏩ Update — 2026-08-25 · **LeadOff live-GBP market map from Scout/Tryout + placement plan (PR #719, MERGED + DEPLOYED)**

The LeadOff market brief now shows a **map of the actual competitor Google
Business Profiles** for a market, plus a plain-English **placement plan**
("where should we plant a GBP"). Shipped in **PR #719**, squash-merged to `main`
as `d075d8d`, auto-deployed to `PLATFORM` (deploy SUCCESS on `d075d8d`), frontend
live via Netlify. **No feature flag — it's on.**

### What it does
- **Scout a market** (or run a **Tryout**) → the live competitor GBPs are plotted
  over a Google static map (teal dots sized by review count, ranked ones
  labelled), with the market centre, suggested placement zones, and an optional
  pasted-GBP reference pin. A deterministic **placement plan** names the weakest
  bearings + the best place to plant a GBP (near the nearest real town) + the
  nearest-competitor distance.
- **Where to see it:** LeadOff (sidebar Radar icon / `/leadoff`) → filter to a
  market → click its row → the **"Proximity (where the field sits)"** card. The
  map renders only **after** a scout/tryout (source `gbp_serp`); before that the
  card shows the octant bars + a "Scout this market" nudge. Also on the **Tryouts**
  tab: a per-result-row **Map** button.

### The cheap-win insight
Scout and Tryout **already fire a live Google Maps SERP** whose items carry each
competitor's GBP **coordinates / place_id / rating / review count** — the parsers
just kept name/domain/phone. So plotting the real GBPs needs **no new paid call**;
scout still fires a single Maps SERP (its phones also feed the existing NAP
footprint step).

### Architecture / decisions worth knowing
- **Grade safety.** Live pins live in a **new, separate** `public.leadoff_gbp_pins`
  table — deliberately NOT in `competitor_locations`, whose Census pins feed
  `proximity_opportunity` (a board grade input). So scouting improves a market's
  **map** without shifting its **grade**. The grade path
  (`leadoff_proximity.market_proximity_score`) still reads Census pins, unchanged.
- **`market_proximity(prefer_live=True)`** prefers live GBP pins → attaches the map
  layer only for the `gbp_serp` source. The **create-client handoff** calls it with
  `prefer_live=False` so the campaign-goal placement text + the calibration-frozen
  proximity stay aligned with the grade's Census read even on a scouted market.
- **Persistence is insert-then-delete-stale** (`services/leadoff_gbp_pins.py`,
  keyed on a per-batch `captured_at` stamp) so a failed insert never wipes a
  market's prior pins; tryout writes all categories in one batched insert + delete.
- **Rural fallback:** if every competitor sits beyond the 10-mi analysis radius
  (octant read empty), the map still shows all captured GBPs, framed by a
  `map_radius_miles`, instead of reading "unavailable".
- Migration **`20260821140000_leadoff_gbp_pins.sql`** (table + index + RLS-on,
  service-role-only like every sibling LeadOff table) — **applied live** to
  `AR-Internal-Tools`.

### Verified in production (2026-08-25)
Ran one real scout on the deployed worker for **Little Rock, AR / chimney_sweep**
(city_id `4119403`) — everything else cached, so ≈ one $0.004 Maps SERP. Result
`gbp_pins: 2`, no error; the two real GBPs (JMI Masonry Chimney Inspection ★3.8;
Clean Sweep Management ★5) persisted with coords/place_ids and the batch stamp,
both inside the 10-mi radius → the read flips to `source=gbp_serp` and serves the
map. (Those 2 rows are real scout output — left in place.)

### Known limits / follow-ups (owner: "not perfect, a start")
- Sparse categories (like the chimney_sweep test, 2 pins) correctly show a "thin
  data" note and **no** placement plan — you need ≥5 in-radius pins for the plan.
- **Re-generating the map on an already-fully-cached scout** isn't offerable yet
  (the first scout always captures pins; a later refresh needs cache expiry). A
  "refresh map" affordance is an easy follow-up.
- Deliberately not built (owner chose reference-pin-only for v1): **click-to-drop**
  a candidate pin anywhere, and **re-anchoring** the proximity math on a chosen
  location.
- The map image needs `VITE_GOOGLE_MAPS_API_KEY` in the Netlify build (same key
  the geo-grid map uses). Absent it, the card shows a "needs a Maps key" note +
  the octant bars (pins/logic still present).

---

## ⏩ Update — 2026-08-19 · **Second-Anthropic-account failover (concurrency headroom)**

Concurrency limits (429s) on the shared Anthropic account can now fail over to a
**second Anthropic account** — same Claude models, so output quality is
unchanged. This is distinct from the existing cross-*provider* fallback
(Anthropic→OpenAI→Gemini in `report_llm.py`), which swaps models; the second
account is tried **first**, before any provider swap. Reactive failover only
(the primary stays primary; the secondary is used only when the primary hits a
transient 429/5xx that outlasts its retry budget). Covers all four Anthropic
call surfaces: the report fan-out + brand/AI scans + agentic loops
(Slack/SerMastr, strategist, PACE, QA) in **platform-api**, blog/service
generation in **pipeline-api**, Local SEO/Ecommerce generation in **nlp-api**,
and the Topic Fanout backend.

**To activate — set ONE env var per service** (empty ⇒ no failover, so the code
ships dark until you set it). The var is a **second Anthropic account's API key**
(a genuinely separate account/org, not a second key on the same account — same
account shares the same concurrency limit):

| Railway service | Var to set |
|---|---|
| `PLATFORM` (platform-api + the vendored fanout) | `ANTHROPIC_API_KEY_SECONDARY` |
| `pipeline` (pipeline-api) | `ANTHROPIC_API_KEY_SECONDARY` |
| `nlp` (nlp-api) | `ANTHROPIC_API_KEY_SECONDARY` |

Each service also honours `ANTHROPIC_KEY_FAILOVER_ENABLED` (default `true`; set
`false` to disable without unsetting the key). Read the live Railway config
before/after setting these (see the CLAUDE.md "read the live config" rule). No
migration, no schema change, no new dependency.

---

## ⏩ Update — 2026-08-07 · **Website Builder — theme compiler + core-pages writer + imagery (PR #575, MERGED)**

Closes the owner's four-step arc — *upload a Claude design → write the pages →
generate images → push to a repo*. Three slices on **`claude/website-builder-slice-3-9an50d`**,
three commits, CI green, **merged to `main` 2026-08-07**. Still dark behind
`website_builder_enabled`; imagery additionally behind `website_images_enabled`
(both default False — unchanged, nothing has run).

**Read the earlier 2026-08-05/06 section below for the module's base state; this
is what those three "still unbuilt" items became.**

### 1 · Theme compiler (`services/website_theme.py` + `_precompile.py` + `_fonts.py`)

Upload a Claude Design export (`.dc.html` or the zip) → a compiled `tokens.css`
the template's `src/theme/` reads. **Split so the LLM only does the part it's
good at:** the precompile pass MEASURES everything countable (colour frequencies,
font families/sizes/weights/radii/spacing, the design's screens/collections/
image-slot seeds) with no network; the LLM pass NAMES — one forced tool call
answering *which measured value is which role*, shown a frequency table, never
the markup. **`validate_roles` refuses any value the census didn't see**, so a
hallucinated brand colour fails the compile instead of shipping as a client's
identity. **Fonts are self-hosted** (downloaded at the design's own measured
weights, committed beside `tokens.css`) so a site makes no third-party request;
best-effort — a font-CDN outage degrades to naming the family.

Themes are **fleet-level** (a design starts several sites): `GET/POST
/website-themes`, `…/{id}`, `…/recompile`, `…/approve`, `POST /websites/{id}/theme`.
Compiled bytes are stored and committed **verbatim** (what's approved is what
ships). Applying to a provisioned site commits `src/theme/*` + records a
`theme` deploy; applying before provisioning rides in with the **configure**
commit so the first build never deploys the house theme to a watched URL. Job
`website_theme_compile` (type already in the live CHECK). **Private
`website-themes` bucket** — migration `20260806120000_website_theme_bucket.sql`
**applied live**. Frontend: a **Theme** tab (upload / swatches / compiled CSS /
approve / use-on-site / recompile). Config `website_theme_model` (Sonnet),
`website_theme_max_mb` (25). *Build verification caught a bug unit tests
couldn't: variable fonts serve one file per subset with a `@font-face` per
weight, so naming files by weight downloaded the same bytes 3× under 3 names —
`resolve_filenames` now names a shared file without a weight (12→4 on the
reference design).*

### 2 · Core-pages writer (`services/website_core_pages.py`)

Home / about / contact — the pages no keyword targets, so **no SERP, no scoring
loop**: one Anthropic call each, in platform-api (nlp would only add its
brand-voice prose builder, which the suite already renders here). Each produces
exactly what its template slot reads: **home** → a `sections` frontmatter map
(hero copy + headings), no body; **about** → a Markdown narrative; **contact**
→ title + intro line only (NAP/hours/form render from verified data). **Privacy
is deterministic** — a legal template merged with business facts, recorded
`template_rendered`, never sent to an LLM. **The forced schema has no
phone/address/price field, so an invented business fact is structurally
impossible;** home draws real services/cities from the site's own planned pages.
Same brand-context gate as the service writer (refuses without a voice on file).
Wired into `website_generate.generate_page` (the `core_pages` engine, previously
`engine_not_built`). Config `website_core_pages_model` (Sonnet) / `_max_tokens`.
*Fix found while verifying: `sections` wasn't in `website_content`'s frontmatter
key order, so a home page's section copy would have been silently dropped —
added, with a round-trip test.*

### 3 · Imagery (`services/website_images.py`)

A hero image per hero-eligible page (home + service/location/matrix/post; about/
contact/privacy excluded) during the same generate job, landing in the page's
`heroImage`/`heroImageAlt` frontmatter — **already committed by `build_files`,
so publish needed no change.** Reuses the suite's one proven renderer
(`illustration.py`'s gpt-image-1); prompt art-directed from the page's own
subject + a photographic brand-style tail forbidding text/logos (no fake signs);
client tone rides along. **Delivered as a public-bucket URL, NOT committed to the
repo** — a 20 KB shared font earned self-hosting, a 1–2 MB hero × dozens of pages
would bloat every repo and re-upload to Cloudflare each deploy. Additive +
best-effort: double-gated on `website_images_enabled` (default off, its own axis
so enabling the builder never starts spending — a 40-page bulk-create is 40
renders) + an image key; every failure path returns None and ships the page
heroless. `website_image_provider` default corrected **gemini→openai** (gemini
names a renderer that doesn't exist yet).

### Inputs (where the four pages' content comes from)

Contact NAP auto-fills from the client's **GBP** into `site.config` (human-entered
values win, §4.5). Brand voice + ICP come from the client's auto-scan of
website/GBP at creation, or a typed guide (user-authored supersedes). **Not yet
built:** a dedicated per-site business-facts editor (the deferred Settings tab) —
today a per-site NAP override goes through the config, not a form.

### To run it end-to-end

Flip `website_builder_enabled=true` (and `website_images_enabled=true` for art)
on PLATFORM — **both set to `true` on 2026-08-08** (deployment `ea2b98b4`,
commit `b4ca6da`, SUCCESS; verified behaviourally in the running app's logs —
the scheduler is executing `enqueue_due_deploy_polls`, which returns early
unless the flag is on). Then the normal lifecycle: create a
`websites` row → upload+approve a theme → provision → build+approve a plan →
generate (now covers home/about/contact + hero images, not just nlp pages) →
publish. Testing: ~160 new unit tests across the three modules; full backend
suite 3288 passed (same 13 pre-existing sandbox failures as main).

---

## ⏩ Update — 2026-08-05 · **Website Builder module — slices 1–2 MERGED, slice 3 in flight**

Design in Claude Design → upload → the suite compiles it to an Astro theme,
provisions a private GitHub repo from a house template, generates pages with the
suite's existing engines, and Cloudflare serves it. **Ships dark behind
`website_builder_enabled` (default False)** — nothing can create a repo until
that flag is on.

### 🟢 Nothing has been created — and "publish" here is jargon

**As of 2026-08-05 no website exists.** `websites`, `website_pages`,
`website_deploys` and `website_themes` are all **empty**, and no
`website_provision` / `website_page_publish` job has ever run. (16 `website_scrape`
rows exist — that is the unrelated, pre-existing client-site scraper.)

**"Publish" in this module means "commit a generated page file into that site's
repo".** It is the name of a code path, not an outward-facing act, and the
function that does it is not written yet. Likewise "generate" means "call
nlp-api for body copy", not "put something on the internet". The docs and commit
messages use these words throughout; none of them describe anything that has
run.

**`kssabraw/ar-site-template` is the mould, not a site.** Private, containing
the template plus two sample blog posts. It exists because the provisioner
creates each site with `POST /repos/{template}/generate`, which needs a template
repo to point at. Nothing is deployed from it and it has no Cloudflare project.

**For a real website to exist, all of these must happen deliberately:**

1. `website_builder_enabled=true` set on PLATFORM (**done 2026-08-08**; was
   False before that, which is why nothing below had run)
2. a `websites` row created for a client
3. `POST /websites/{id}/provision` called by a staff+ user
4. a site plan built, reviewed and approved
5. content generated (this is the step that spends money — one nlp-api call per page)
6. pages published, i.e. committed, which triggers the Actions deploy

Steps 4–6 now have code behind them (2026-08-05), and **still nothing has run**:
every route 503s while the flag is off, and every step above needs a person to
take it. Building the machinery is **setup**; creating a site is a separate,
deliberate act that nobody has taken.

**Docs (read these first, in this order):**
- `docs/modules/website-builder-module-plan-v1_0.md` — engineering spec:
  architecture, data model, phasing, locked infrastructure rulings.
- `docs/modules/website-builder-prd-v1_0.md` — behaviour, permissions,
  lifecycle, quality gates, acceptance criteria. **Vendored from the owner's
  Google Doc; the Doc is the source of truth.** Owner rulings made after capture
  live in an **amendments block at the top**, not edited into the body — read it
  before trusting any section it names.
- `docs/reference/page-type-reference-v3_6.md` — **authoritative** for page
  types, planner triggers, URL patterns, page structure, the Shared Component
  Library, and content specs. Also vendored; subordinate to the AR Site
  Architecture SOP.

### What is built and merged (PR #545, squash `5c3ef95`)

- **`site-template/`** — the house Astro template, also published as the GitHub
  **template repository `kssabraw/ar-site-template`** (private, `is_template:
  true`). Astro 5 content collections with a zod frontmatter contract,
  deterministic JSON-LD, SEO plumbing, token-driven theme layer, push-to-main
  Actions → `wrangler` deploy to Cloudflare Workers static assets.
  **`site-template/` in this repo is the source of truth** — edit here, publish
  from here.
- **Backend**: 4 tables, a resumable provisioning step machine
  (`services/website_provision.py`), REST surface (`routers/websites.py`), job
  wiring. Migrations `20260803190000` + `20260803210000`, both **applied live**.

### Slice 3 — merged (#560) plus the wiring that finishes it

Merged in #560: `services/website_plan.py` (the site-plan inventory) and
`services/website_content.py` (content → repo files + publish gates), both pure.

The impure half is now built: `services/website_plan_store.py` (build / rebuild
/ approve a plan as `website_pages` rows), `services/website_generate.py`
(`website_page_generate` → `local_seo_service.generate_page`, unchanged),
`services/website_publish.py` (`website_page_publish` → one commit per page via
`github_publish.commit_files_to_github`), `services/website_deploy.py`
(`website_deploy_poll` + the scheduler sweep), and eight routes on
`routers/websites.py`. Migration `20260805120000` applied live. **206 tests
across the seven modules** (was 99).

**UI (built 2026-08-06).** Two entry points, per PRD §6.1, and **both are
hidden until `website_builder_enabled=true` on PLATFORM** — **set 2026-08-08**,
so the module is now visible in the dashboard (it was invisible by design until
then):

1. **Sidebar → Websites** (`pages/Websites.tsx`, route `/websites`) — the fleet
   across every client, with status/domain/last-deploy columns, a filter, the
   §7 counts, and Trash. Read-only apart from soft-delete and restore; rows link
   into the client's workspace, which is where work happens.
2. **Client workspace → Website Builder card** (route `clients/:id/website`).

Both gate on the same `GET /websites/status` (the PACE/QA pattern — a card that
503s on click is worse than no card), so the module appears in both places at
once or in neither.

`frontend/src/pages/WebsiteBuilder.tsx` + `components/website/*`. Four tabs:
**Overview** (the provisioning step machine with per-step state and a Resume,
URLs, repo, last deploy), **Plan** (catalog + cities editors, Build, the issue
list split into blocking vs advisory with per-gate sign-off checkboxes,
Approve), **Pages** (per-page status, engine, the gate reason in plain English,
select → Generate/Publish, per-row retry, a leaveable batch bar), **Deploys**
(history with `superseded`/`unknown` explained inline, Re-check, recorded gate
overrides). Actions above the user's role render **disabled with the reason**
rather than hidden, per §6.2.

**Still unbuilt in the module** *(as of this 2026-08-05 section; the theme
compiler, core-pages generator and imagery were built 2026-08-07 — see the top
section)*: custom domains, GSC auto-verify, and the Settings tab. The
suite-level fleet index shipped 2026-08-06 (Sidebar → Websites). Generation
originally covered the nlp-api page types only; a page type with no engine still
records `engine_unavailable:<type>` on its row rather than being silently
skipped.

**⚠ Three things the build found that reading the docs did not:**

- **The template's deploy workflow sets `concurrency: cancel-in-progress: true`,**
  so publishing a 20-page batch cancels 19 runs. The merged
  `deploy_status_from_run` read `cancelled` as **failed**, which would have
  painted a successful batch red 19 times. `cancelled` now maps to a new
  `superseded` status and raises no notification.
- **Post entry ids doubled the `blog` segment.** `/blog/[...slug]` uses the
  entry id AS the slug, so the full-path id from `entry_id` would have published
  `/blog/blog-my-post/`. Found by building the template with real generated
  files, not by reading the zod schema — do this every time.
- **`areas_we_serve` and `services_index` were listed as "template-rendered"
  but the template has no route for either** (they are Writer #6's page types).
  Publishing would have marked them live at a URL that 404s. They are now
  `UNRENDERABLE_PAGE_TYPES`, reported as a non-blocking `missing_template` plan
  issue, and a page with an empty body is held at `body_not_generated` rather
  than committed as an empty file.

**Where the catalog lives:** the plan is built from a catalog + cities posted to
`POST /websites/{id}/plan` and persisted onto `websites.config`. The
client-level Business Facts store (PRD §4.10) is a later slice; this is the
shape it will feed. Nothing is imported from GBP categories.

**Contradiction resolved against the PRD, not the plan:** a deploy whose Actions
run cannot be found past `website_deploy_timeout_minutes` is recorded as
**`unknown`** with a re-check action (PRD §6.3), not as failed — the old config
comment said failed and has been corrected.

### Provisioned (all live on PLATFORM)

`GITHUB_SITES_TOKEN`, `GITHUB_SITES_OWNER=kssabraw`, `CLOUDFLARE_API_TOKEN`,
`CLOUDFLARE_ACCOUNT_ID`.

### Owner rulings

Site repos under **`kssabraw`** (personal account, not an org) · existing
Cloudflare account · **Workers static assets**, not Pages · Namecheap domains
with NS pointed at Cloudflare · every site belongs to a client row · info sites
**auto-publish**, local sites get human review · themes reusable across
industries · AI imagery including realistic jobsite scenes · Web3Forms (one
shared key) · CallRail DNI · ~50 sites year one. Then **2026-08-04**: a lead-gen
property's matrix **may ship before its informational layer** (overrules PRD
§4.12.3b "neither ships alone"), and the **>40 links figure is too high** —
advisory only, pending a ratified number.

**v1 scope:** `local_business` + `lead_gen`, Tiers 1–3, `monetization: leads`.
Deferred: `ads`/`affiliate` and the consent stack, informational properties, and
the six unbuilt writers (§4.7).

- **The global nav was 404s, on every page of every site.** `default_nav()`
  wrote `/services`, `/locations`, `/about` and `/contact` into each site's
  config, and `CTABand`'s default CTA pointed at `/contact` — none of which are
  routes (the real ones are `/about-us/`, `/contact-us/`, and cities sit at
  root). Astro does not fail a build on a bad `href`, so it shipped silently.
  Fixed 2026-08-06: the template **derives** the SOP global nav/footer set from
  published pages (`src/lib/hubs.ts`), config `nav` is an override, and the
  provisioner writes none. **Verification now includes a link check** over the
  built `dist` — it found 13 broken links on the pre-fix build and 0 after.

### ⚠ Gotchas that cost real time

- **The root `.gitignore` has a Python `lib/` rule at line 13** that silently
  swallowed `site-template/src/lib/` — three essential files were missing from a
  commit with no warning, and the template would not have built. Fixed with
  `!site-template/src/lib/` (negate the **directory**; git will not descend into
  an ignored directory to re-include children). **Anything else added under a
  `lib/` path will hit this again.**
- **URL structure was wrong in slice 1** and had to be reworked. Reference §1.1
  R1: local top-level pages sit at **root**, not under `/services/` or
  `/locations/`, and the matrix is **location-first** `/{city}/{service}/`. The
  plan's pre-ruling text illustrated the wrong shape.
- **Page type is DECLARED, never inferred from the URL.** `/{city}/{x}/` may be
  a local landing, a neighborhood or a POI. Every routed entry carries `path`
  **and** `pageType`; one catch-all `[...path].astro` renders them. Do not add
  per-type route files.
- **PyNaCl is required** — GitHub's Actions-secrets API only accepts values
  sealed with the repo's libsodium key. Imported lazily, so a deploy without it
  starts and fails with `pynacl_not_installed` rather than an ImportError.
- **This session's GitHub credential cannot create repos** (App installation
  scoped to `ar-tools`; `POST /user/repos` → 403 "not accessible by
  integration"). The template repo was created by hand. `GITHUB_SITES_TOKEN` is
  a different credential and is what the provisioner uses — **whether it can
  create repos is still unverified**; if it cannot, swap for a classic PAT with
  `repo` + `workflow`.
- **PRs here are squash-merged**, so the branch's commits are never ancestors of
  `main`. After a merge, reset the branch from `origin/main` and
  **force-with-lease** — but verify by **content diff** first, because
  `git log branch ^main` will list every already-merged commit and look alarming.
- **Verify by building BOTH site types.** A stale component reference behind the
  `isLocal` branch passed the informational build and crashed the local one.

### Open items

- ~~The **ratified links-per-index figure**~~ — **ratified at 25** by the owner
  2026-08-05 and upstream in **Page Type Reference v3.6** §1.2 (body links only,
  excluding the global nav/footer set; the two agree). It now **blocks approval
  until acknowledged**, like the >200 matrix gate; both clear via `acknowledge`
  on the approve route, and planning errors never do. Remaining: fold the figure
  into the **SOP's** link-equity section — the reference half is done.
- **Reference is now v3.6** (`docs/reference/page-type-reference-v3_6.md`, the
  v3.4 capture is retired). Besides the 25, **v3.5 promoted Areas We Serve and
  Services Index to CORE-conditional (auto-triggered)** — Areas We Serve on any
  multi-city site (≥2 cities), Services Index above 8 top-level services. The
  planner already fired on exactly those thresholds; what changed is that they
  are *infrastructure, not optional*.
- **Areas We Serve triggers at ≥ 6 cities** (owner ruling 2026-08-06), settling
  reference R6's open threshold and **superseding the ≥ 2 in the vendored v3.6
  capture** — the capture is faithful, so the ruling lives in the PRD amendments
  block until the Doc is revised. A 2–5 city site therefore has location pages
  and a matrix but no location hub, and nothing in its global nav points at the
  location silo (those cities are reached from the homepage grid, the matrix
  pages' structural links, and the HTML sitemap). The number lives in
  `website_plan.AREAS_WE_SERVE_TRIGGER` **and** `site-template/src/lib/hubs.ts`
  — the planner decides whether to plan the hub, the template whether to render
  it, and if they disagree the symptom is a 404 in the global nav.
- **Component renaming is done**, but 13 library components remain unbuilt and
  are listed in `site-template/src/theme/manifest.ts::MISSING_COMPONENTS`; each
  gates a page type that has no writer anyway.
- **The two CORE-conditional hubs now render** (2026-08-06). `/areas-we-serve/`
  and `/services/` have routes in the template, built from the same
  published-pages query as structural linking — so the listing half needs no
  writer at all. Both are conditional on their reference triggers (>= 2 cities;
  > 8 top-level services) via a `getStaticPaths` that returns `[]`, because
  building a hub the reference says not to build would put a thin unlinked page
  in the XML sitemap. **Writer #6 still owns the narrative copy** that brings
  them up to the reference's depth band; until then they ship as accurate hubs
  with a factual lede rather than as pages that cannot ship at all. Thresholds
  live in `site-template/src/lib/hubs.ts` and mirror `website_plan.py` — the
  same rule evaluated in two places, so a change to one needs the other.
- **Client-side 404 search** (Pagefind) not built; the 404 points at the HTML
  sitemap.
- Core-pages prompt copy, pilot clients, and a local-business design export as a
  second compiler fixture are owner tasks.

## ⏩ Update — 2026-07-12 · **LeadOff v2 BUILT: paid tryout/scout, neighborhoods tab, SOP routing + the grants repair**

PRD §5 items 1/3/4 shipped (item 2, the create-client handoff, shipped earlier
the same day in #339). Detail in the CLAUDE.md LeadOff paragraph.

- **Paid actions**: `POST /leadoff/tryout` (~$0.20/city, async job →
  `leadoff_tryouts` + a Tryouts tab) and `POST /leadoff/scout` (~$0.10–1,
  cache-cheapened; free `GET /leadoff/scout/estimate` preflight) — ported from
  `docs/reference/leadoff-scanner/check_city.py` / `enrich_shortlist.py`
  (committed reference copies; the cache contracts MUST NOT drift — the
  PowerShell tools write the same `market_scanner` cache rows).
- **Budget guard**: `leadoff_spend` ledger + `leadoff_daily_budget_usd`
  (config, default **$5/user/day**) — raise it on PLATFORM if the team needs
  more headroom. Migration `20260712120000` applied live.
- **⚠ Grants gotcha (bit us in prod)**: the scanner's loader drop/recreates
  `market_scanner` tables on reload, which STRIPS `service_role` grants — the
  deployed board was permission-broken until 2026-07-12. Fixed live:
  `grant usage on schema market_scanner to service_role;`
  `grant select on all tables in schema market_scanner to service_role;`
  `grant insert on market_scanner.domain_backlinks, market_scanner.business_reviews, market_scanner.demand_trend to service_role;`
  and — so future reloads keep them —
  `grant market_scanner_loader to postgres;`
  `alter default privileges for role market_scanner_loader in schema market_scanner grant select on tables to service_role;`
  (Default privileges cover SELECT only; if the loader ever recreates the three
  cache tables, re-grant INSERT.)
- No new env vars (reuses `DATAFORSEO_LOGIN/PASSWORD`). DataForSEO 40203
  (daily money limit) aborts a job without recording; balance context lives
  in `docs/reference/leadoff-scanner/scanner-CLAUDE.md`.

## ⏩ Update — 2026-07-11 · **LeadOff market-intelligence module (v1 read-only) BUILT**

The suite's pre-client "which market do we enter" tool — the LeadOff scanner's
graded board (34,352 US city×category markets + neighborhood combos), served
from Supabase schema `market_scanner` into a new suite-level page.

**What exists (detail in the CLAUDE.md paragraph + `docs/modules/leadoff-prd-v1_0.md`):**
- Backend: `services/leadoff_db.py` (schema-scoped client, fanout pattern),
  `services/leadoff.py` (pure grade/economics logic), `routers/leadoff.py`
  (`GET /leadoff/board`, `GET /leadoff/market-brief`). Config:
  `leadoff_prefetch_rows`. No migration — the `market_scanner` tables are
  populated by the external scanner; `service_role` grants already applied.
- Frontend: `pages/LeadOff.tsx` at `/leadoff` + sidebar entry (Radar icon).
- Agent layer: `docs/sops/LeadOff_Market_Intelligence_SOP.md` (+ byte-identical
  vendored copy in `agent_docs/sops/`, registered in `docs/sops/README.md`).

**Verification done:** 15 new pytest green (`tests/test_leadoff.py`, pure
logic); `npm run build` clean. Full backend suite NOT run in this (Windows)
workspace — deps aren't installed locally; note `test_sop_library.py`'s
vendored-sync test fails on clean `main` here too (a cp1252 locale artifact
reading `_ORCHESTRATOR.md`, passes on Linux/CI) — pre-existing, not from this
change.

### 🚦 To activate
1. Supabase dashboard → API settings → **Exposed schemas** → add
   `market_scanner`. (Grants to `service_role` are already applied.) Without
   this, `/leadoff/*` returns PostgREST schema errors.
2. Deploy PLATFORM + frontend as usual. No env vars needed for v1 (read-only).
3. Smoke: open `/leadoff` → board renders with `data 2026-07`; click a row →
   brief shows top-5 competitors; Vancouver WA Locksmith should show cached
   scouting enrichment (RD/velocity from the shared caches).

## ⏩ Update — 2026-07-05 · **SerMaStr Phases 0–4 BUILT — dormant behind `strategist_enabled=false`**

The strategist agent from `docs/modules/seo-strategist-agent-plan-v1_0.md` is
**built end-to-end (Phases 0–4; Phase 5 Asana push deliberately out of scope)**
in one overnight autonomous run. Migration `20260704180000_strategy_reviews`
is **applied to the live Supabase project**. Nothing is active in production:
every trigger path (on-demand API, weekly scheduler pass, both escalation
hooks, the Slack action) checks `strategist_enabled`, which ships **FALSE**.

**What exists now (detail in the CLAUDE.md paragraph):**
- **Phase 0** — `services/strategy_digest.py` (signal envelope w/ deterministic
  `status`, keyword passports, staleness flags, isolated providers) +
  `services/sop_library.py` (active-domain SOP selection over `docs/sops/` +
  the DB `sop_store` layer + module cards; corpus **vendored** at
  `writer/platform-api/agent_docs/` because the Docker build context can't see
  repo-root `docs/` — a unit test keeps the copies byte-identical).
- **Phases 1+3** — `services/strategist.py` (bounded tool-use run →
  `strategy_reviews` row; `sanitize_review` enforces §3 in code) +
  `services/strategist_tools.py` (serp_deep_dive / geogrid_history LLM
  subagents; episode_timeline / read_sop / client_capacity deterministic;
  audit_page paid+capped) + `routers/strategist.py` + the Action Plan
  **Strategist Review card** (Approve/Dismiss; senior proposals need admin).
- **Phases 2+4** — weekly active-signal-only pass on the shared scheduler
  (Tuesday, day after the reopt build); SerMaStr Slack action
  ("strategy review for <client>", reply-*yes*); escalation briefs riding
  `episode_escalated` + the new sitewide-decline transition detector.

**Verification done:** 994 pytest green under the pinned `fastapi==0.115.0`
import-check; real `npm run build` clean; an 8-angle code review ran before
push — 6 confirmed findings fixed (senior-approval now enforced at the API,
per-trigger job dedup so escalation briefs can't be swallowed, DB sop_store
folded into the run, dead budget-domain read, orphaned-review cleanup,
completed_at timing). Also fixed 3 pre-existing drifted `test_run_dispatch`
assertions (fanout `generate_service_page_core` returns a run id now).

### 🚦 To activate (the smoke gate — spec §7)
1. Set `STRATEGIST_ENABLED=true` on the **PLATFORM** Railway service (env var
   → redeploy). Nothing else is needed — schema is live, Slack/notifications
   already provisioned.
2. Smoke-test: open a client's **Action Plan** page → "Strategist Review" card
   → **Run review** (or in Slack: "strategy review for <client>" → reply
   *yes*). Expect a review in 1–3 minutes: assessment, findings w/ SOP
   citations, proposals (senior-only badged), questions.
3. Judge 2–3 real clients' reviews (Kyle/Ryan). If they'd have been your
   calls, leave it on — the weekly pass (active-signal clients only) and the
   escalation briefs are then live automatically. If not, set the flag back
   to false; everything goes dormant again.

**Deferred / notes:** Phase 5 (approved proposal → Asana task) rides the
Asana-push build. `docs/sops/` + module-card edits must be re-copied into
`writer/platform-api/agent_docs/` (pytest fails loudly if you forget).
Weekly-scope/model/digest-destination/approval-surface all use the spec §9
defaults (Sonnet everywhere; shared Slack channel; active-signal only;
Action-Plan-first).

---

## ⏩ Update — 2026-07-04 · **SerMaStr — Search Marketing Strategist Agent, spec approved** — **MERGED to `main`** (PRs #218 `c7254fd` + #219 `2166a03`; spec only, nothing built yet)

The reasoning layer atop the deterministic agent loop now has an **approved
plan of record**: **`docs/modules/seo-strategist-agent-plan-v1_0.md`**. The
agent's name is **SerMaStr** — **SE**arch **MA**rketing **STR**ategist (owner
ruling, #219). The existing Slack assistant is this agent's conversational
surface — one identity: the Q&A/actions bot today, plus the strategist mode
the plan adds. Scope is the whole search surface (organic, local pack/maps,
AI-answer visibility, content, links/offpage, budget) — deliberately *not*
"a strategist for LLM visibility."

**Locked decisions (decision records in the spec):**
- **Per-domain standing LLM monitors rejected** — monitoring stays
  deterministic (already built); strategy is the cross-domain part (one
  shared budget, interlocking SOPs). Architecture: **one strategist run per
  client**, event-driven (weekly for active-signal clients + escalation
  events + on-demand), with **bounded drill-down tools** (≤4/run; only
  `serp_deep_dive` + `geogrid_history` are true LLM subagents).
- **Proposes, never executes.** Advice objects with SOP citations, staged for
  Approve/Dismiss; six hard-coded human passthroughs from `_ORCHESTRATOR.md`
  §3 (freeze, GBP suspension, sub-50% margin, separate-entity calls,
  overclock, the 6-week review itself). Unowned decisions → questions.
- **Escalation briefs:** the 6-week rule's critical notification gains a
  prepared case file (what was tried / what moved / recommendation) instead
  of a bare alert.
- **Module legibility (spec §2b):** module cards + a standard signal envelope
  (`direction` + deterministically-computed `status` — the LLM never does
  trend arithmetic) + the **keyword passport** (digest grouped by keyword
  across channels) + explicit staleness + self-documenting tools. First three
  **module cards written** at **`docs/agents/module-cards/`** (rank-tracker,
  geogrid-tracker, labs-ai-visibility — each with a worked misreading, e.g.
  "average_rank without found_pins", "null GSC position ≠ rank loss", "one
  AI answer-flip ≠ trend"). Cards can be wired into SerMaStr's Slack context
  providers immediately, before the strategist ships.
- **Cost:** ≈ $1–2/client/mo typical (Sonnet-class), $0 for quiet clients.
- **Smoke gate:** Phase 1 is on-demand only (`strategist_enabled` default
  false); weekly scheduling only after Kyle/Ryan judge 2–3 real reviews.

**Next build (on "go"):** Phase 0–1 — `build_strategy_digest` (signal
envelope + keyword passport + staleness + SOP/module-card retrieval),
`strategy_reviews` migration, the on-demand run, and the Action Plan
"Strategist Review" card. The **Asana task push** (plan lines → assigned
Asana tasks) remains queued as its own build and later becomes SerMaStr
Phase 5. Open §9 defaults to confirm at build time: Sonnet everywhere;
digests to the shared Slack channel; weekly = active-signal clients only;
approvals Action-Plan-first.

---

## ⏩ Update — 2026-07-04 · **SOP library + 24/7 SEO agent phase 1** — **MERGED to `main`** (PRs #215 `3e3c828` + #216 `73e6e15`, both deployed & live)

The session that turned the agency's SOP corpus into a running machine. Two
merged PRs: **#215** (the SOP library + the whole agent loop) and **#216** (the
Recipe Engine frontend + a production hotfix). Everything below is **live** —
all six migrations were applied to the live Supabase project during the build,
and the PLATFORM deploy of `main` is healthy.

**The agent loop (all built, all running on the shared scheduler):**

```
detect      trackers + daily freeze check + offpage/citation/imbalance sweeps
classify    B1–B5 + §A sitewide scope (drop_classifier.py)
decide      SOP response playbooks rendered in the Action Plan
cost/assign Recipe Engine → monthly task plan (margin-aware, roles-matrix)
verify      response episodes: 2-week rechecks / 6-week escalate → Kyle/Ryan
kill switch Freeze Protocol (freeze pauses all content + link output)
```

**What shipped, by module** (full detail in each CLAUDE.md paragraph):

1. **`docs/sops/`** — the 11-doc SOP library imported with a consistency pass:
   drift fixes across every doc, the On-Page thresholds resolved from the live
   nlp-api scoring code (bands ≥90/≥80/≥70/≥60; deficiency bar = engine < 80;
   operational pass line 90), four owner rulings (plan-time Step 8 gate;
   threshold-gated overclock self-serve; RD 250 = guideline not cap; LABS
   engine list aligned to the built module), and the capacity workbook's dead
   formulas wired. **Read `docs/sops/README.md` first** — `_ORCHESTRATOR.md`
   is the router.
2. **Freeze Protocol** — `client_freezes`, router/worker/fanout gates
   (409 `client_frozen`), daily `freeze_check` (GSC URL-Inspection → auto
   deindexing-freeze; DataForSEO `site:` probe warn-only), `FreezeBanner` on
   the workspace (admin freeze/lift). Manual actions have no Google API — a
   human confirms via the banner.
3. **Recipe Engine** — SOP §1–§5 as code, conformance-tested against the §4
   worked example ($2,000 → $0 remaining, exact). Auto-diagnosis from suite
   data. **Frontend:** workspace "Monthly Task Plan" card → generate (66%/50%
   margin), summary strip, flags, assigned task table, CSV, history.
4. **Drop classifier** — open rank alerts arrive classified (B1 cannibalization
   / B2 SERP-shift / B3 CTR / B4 indexing / B5 position; §A sitewide banner);
   the Action Plan renders each classification's SOP protocol + right-tool CTA.
5. **Response episodes** — every drop response has the SOP clock: baseline at
   open (organic weighted position / maps geo-grid `average_rank`), 14-day
   rechecks, recovered when the tracker resolves the alert, **escalated once
   at 6 weeks** with no improvement (critical notification; improving episodes
   never escalate). Clock notes append to Action Plan rows.
6. **Offpage agent** — RD loss / unnatural spike from `backlink_profiles`
   (both relative + absolute bars), **citation liveness** (paste-in list at
   `clients/:id/citations`; fail-open — only hard 404/410/DNS ×2 consecutive
   = dead; bot-blocks count alive), **per-page RD imbalance** (monthly page
   summaries, inner page > homepage RD × 1.5 → info-severity rebalance).
   Every new alert triggers a silent Action Plan rebuild (`trigger="offpage"`).

### ⚠️ Incident (resolved) — PLATFORM crash-loop after the #215 deploy

The `DELETE /citations/{id}` route used `status_code=204`, which the pinned
`fastapi==0.115.0` rejects **at import time** → the whole API crash-looped
~07:34–07:45 UTC ("client cards aren't loading"). Fixed in #216 (200 + JSON
body), verified by importing all 30 suite modules under the pinned FastAPI.
**Process rule going forward:** backend changes are import-checked under the
pinned requirements before push (the sandbox's newer FastAPI had masked it),
and frontend changes run the real `npm run build` (which also caught a React
19 `JSX` namespace break earlier).

### 🔧 Operator to-dos (the loop idles until these are done)

1. **Set each client's budget** — client form → "Budget & Campaign Type"
   (monthly budget with live 34%-deployable readout; local/enterprise funding
   order; SAB toggle → $130 baseline).
2. **Paste citation lists** — client workspace → Citations card → paste the
   URLs from vendor deliverables (weekly liveness sweep starts from there).
3. **Smoke-test one client** — generate a Monthly Task Plan and gut-check it;
   open + lift a manual freeze and confirm the Slack ping + the 409 gates.

No migrations to apply — unlike prior handoffs, **all schema is already live**
(`client_freezes`, `recipe_engine`, `response_episodes`, `offpage_alerts`,
`citations_page_backlinks`).

### Deferred / next builds (each a clean follow-up PR)

- **Asana task push** — one Asana task per plan line, assigned per the roles
  matrix (the Asana integration already exists). Highest-leverage next step:
  closes the loop from "plan generated" to "task in Minda's queue".
- Algo-update detection (cross-client drop correlation).
- On-page coverage audit (blog/service/location scoring parity with local).
- LABS "mention AND link" win rollup + AIO Fork A/B classification.
- Recipe Engine refinements: gap-sized funding quantities; cross-client
  capacity from the workbook; per-person escalation routing.
- SOP paper debt: anchor-ratio ledger (the freeze health check references it),
  T1 Booster spec, LB recipe decision matrix.

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
- **Logic:** the `services/slack_assistant/` package (helpers/prompts/context/actions/llm; split 2026-07-10) — pure helpers (`verify_slack_signature`,
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
