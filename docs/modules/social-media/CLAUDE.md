# Social Media Module — Build Context (CLAUDE.md)

> Module-scoped build primer for the **Social Media Manager + Content Creator** module.
> This does NOT replace the root `/CLAUDE.md` (the suite authority) — read that first for
> suite architecture, then this for the module. **Read this before building the social module.**
>
> **Provider swap (2026-09-17): PostForMe replaces PostPeer** (ADR-0006; facts in
> `docs/modules/social-media-vendor-confirm-postforme-v1_0.md`). The adapter seam (ADR-0001)
> made this contained: a new `services/social/postforme_adapter.py` + a provider-aware
> `services.social.get_adapter(client_id)` factory + config. **Isolation is now
> provider-enforced** — one PostForMe **Project (→ one API key) per client**, stored per
> client in `social_client_credentials` (secret, RLS/service-role only; never on `clients`,
> never returned to the UI). Setting a client's key (Social setup → "Save API key",
> validated live) stamps a `clients.social_profile_id='postforme'` connected-marker so the
> publish path's existing gate is unchanged. **Provisioning is manual** (PostForMe has no
> project/key API): create the client's Project + key in the PostForMe dashboard, paste it
> in. Posts are **async** (create → bounded-poll `/social-post-results` for the URL, Decision
> 2=A); pricing is **flat** (X credit surcharge gated to PostPeer only); quota **pools at the
> Team level** (per-client isolation ≠ per-client quota; our `social_usage` meter does spend).
> Project type = **Quickstart** (owner). **MERGED + ACTIVATED + LIVE** (PR #1198, squash
> `961d57c`): `SOCIAL_POSTING_PROVIDER=postforme` is **set on PLATFORM** and the activation
> deploy (`df6323b0` = `961d57c` + the var) booted healthy. The code default stays `postpeer`
> (inert without a key), so a fresh env still ships dark; PostPeer stays behind the adapter as
> a dormant fallback. **Still open (human, deployed-only):** paste each client's PostForMe
> project key (Social setup → "Save API key"); run one live end-to-end test post + account
> connect (sandbox egress-blocked from PostForMe, so the post path is verifiable only on the
> deployed service); delete the dashboard test project + its throwaway keys.
>
> **Build status (2026-09-16):** **The module is fully wired and live, and P1 competitor research is now BUILT + LIVE.**
> P0 foundations + the backend publish path + the R2 media store (PR #1027) and the frontend compose screen
> with image/video upload (PR #1032) are BUILT and MERGED to `main`; on PLATFORM `SOCIAL_ENABLED=true`, all
> five `R2_*` vars, `GEMINI_API_KEY`, **`POSTPEER_API_KEY`**, and now **`APIFY_API_TOKEN` +
> `SOCIAL_COMPETITOR_RESEARCH_ENABLED=true` are set** — nothing left to provision. What exists today is a
> **manual composer → publish/schedule** flow (platform-general, Facebook-first) PLUS the full
> **P2 Creator** — AI copy drafting, AI image generation (**Nano Banana 2** default, nano-banana Pro fallback — queue #5, PR #1216),
> and **Angle fan-out** (one source → one angle → per-platform Drafts, reviewed/edited/published from a
> Drafts tab) PLUS **P1 Competitor research** (analyze-in-place, Apify-only — a Competitors tab: add per-platform
> handles → Research now → per-`(client, competitor, platform)` signals that ground angle proposals).
> **Shipped since (2026-09-16):** the composer Format dropdown is now per-platform (PR #1160, merged); the
> **client-isolation A-unit** — the account picker is per-client and safe — merged (PR #1165); and **P1
> Competitor research merged + enabled in production (PR #1177, squash `3f07eda`)** — see `HANDOFF.md`
> 2026-09-16 update for the full P1 readout + the owner b/c decisions.
> **Owner decisions (2026-09-16):** IG scope = **feed + Reels + Stories** (b1); **IG carousel in v1** (b2);
> autonomy rollout **case-by-case** (b4); PostPeer billing **PAYG** (b5); **P1 competitor research
> Apify-ONLY — TwelveLabs is DROPPED** (c1, BUILT). Owner-confirmed P1 platform scope: Instagram, Facebook,
> X, YouTube, Pinterest (LinkedIn deferred). Still to discuss: default per-client monthly ceiling (b3),
> the P4 autonomy build (c2), the P5 Video Studio (c3).
> **Next build queue (owner-set 2026-09-18), in order:** (1) **IG Reels + Stories** — **✅ BUILT + MERGED
> (PR #1206)**; (2) **IG carousel Draft type** — **✅ BUILT + MERGED (same PR #1206)**; (3) **YouTube
> poster** — **✅ BUILT + MERGED (PR #1211, squash `44c5e06`)** — a YT post = video + required `title` via
> `platform_configurations.youtube` (`publish.build_youtube_config` forces only the `public` privacy
> default), `validate_post` YouTube rule, fanout excludes YT; (4) **big-video direct-to-R2 presign** —
> **✅ BUILT + MERGED (PR #1213, squash `069d618`)** — video >200 MB PUTs straight to R2 via the presign
> endpoint (`presignAndPutVideo`), presign expiry bumped to 2 h; **⚠️ still needs the R2 bucket CORS
> policy applied (owner infra, deployed-only) before big-video upload works — see `HANDOFF.md`**;
> (5) **mixed image path** — **✅ BUILT + MERGED (PR #1216, squash `cf9ffa0`)** — all social images now
> render on **Nano Banana 2** (`gemini-3.1-flash-image`) at 2K (~25% under Pro; it honors every aspect
> ratio, so the "2.5-Flash-for-square" premise was obsolete), behind `social_image_use_flash` (default ON,
> Pro the fallback); the choice is the pure `services/social/image.py::select_image_model`. Also folded in:
> a budget-bypass guard (a paid image always reserves a strictly-positive cost) + a SocialCompose eslint
> cleanup (6→0). **The build queue is now fully built (all 5 items).** Then **P4 autonomy** +
> **P5 video/YouTube** remain the longer-horizon phases. The `HANDOFF.md`
> **"Next priority" block** (top of that file) is authoritative on this order. Deployed-only follow-ups
> (independent of the queue): apply the **R2 CORS policy** (#4); the first **live YouTube post** (#3);
> a **live test post** on the PostForMe path; a **live P1 research run** (sandbox is egress-blocked from
> PostForMe, R2, and Apify). See `HANDOFF.md` (this folder) for the live state — start there.

## What this module is

One suite module, **two surfaces over one per-client data model**, that repurposes a
client's existing content (blogs, pages, keyword research) into on-brand, platform-native
social content — competitor-signal-informed, brand-voice-enforced, human-approved — and
publishes to the client's own social accounts. **Creator** = generation
(Source → Angle → Draft). **Manager** = calendar / cadence / approval / publish. The
endgame is an **autonomous social department** built on the suite's existing autonomy
guardrails.

## Authoritative docs — read in this order

1. `../social-media-module-context.md` — **domain glossary** (vocabulary; read first).
2. `../social-media-module-prd-v1_0.md` — **the PRD** (scope, decisions, phasing). Authoritative.
3. `../../adr/0001-postpeer-posting-provider-behind-adapter.md` — PostPeer behind a swappable adapter.
4. `../../adr/0002-analyze-in-place-never-rehost-competitor-media.md` — competitor research legal stance.
5. `../../adr/0003-social-autonomy-is-a-domain-executor.md` — autonomy reuses guardrails, not a new persona.
5a. `../../adr/0004-social-media-storage-cloudflare-r2.md` — R2 media store behind a `MediaStore` interface (built #1027).
6. `../social-media-cost-model-v1_0.md` — worked cost model (budget-meter + Social Policy ceilings).
7. `../social-media-failure-handling-v1_0.md` — failure/edge-path build spec (connection health, holds, statuses).
8. `../social-media-vendor-confirm-postpeer-v1_0.md` — PostPeer due diligence + the open P0 questions.

## Locked decisions (from the design grill)

- **Spine = repurpose engine**; competitor research is a signal feeding it; autopilot is the endgame.
- **One module, two surfaces** (Creator = generation, Manager = calendar/publish), one data model.
- **Rides all standard suite rails** — no new infrastructure.
- **Publishing is human-approved by default.** Graduated approval scales with the autonomy tier.
- **Auto-publish only at the top autonomy tier + explicit per-client opt-in** — never a default.
- **Competitor research is analyze-in-place** — Apify (public content, not identities) + TwelveLabs
  (video from public URL, no download). cobalt is owned/licensed assets only. Transform, never replicate.
- **PostPeer behind a swappable adapter** (Ayrshare the fallback — but enterprise per-profile priced,
  so a swap is a cost/architecture event).
- **Social autonomy = a domain executor reusing `autonomy_policy.classify` / `autonomy_budget.reserve` /
  tiers / freeze / DORA veto** — the orchestration loop itself is NEW code (the SEO executor's
  `gather_candidates` is remediation-reactive; social is cadence-driven/generative).
- **Copy is tailored per platform** (a Sonnet pass each), grounded in a shared **Angle**.
- **Humans tune the agents** via a per-client **Social Policy** (cadence, topics, tone/angle,
  competitor focus, budget ceiling, autonomy tier, and **editable image/text prompt templates**).

## Stack & vendors (★ = confirm before relying on)

| Purpose | Choice | Notes |
|---|---|---|
| Copy / Angle / self-critique | **Claude Sonnet 5** (`claude-sonnet-5`) | $2/1M in, $10/1M out. |
| Image gen | **Nano Banana 2** (Gemini 3.1 Flash Image) default; **nano-banana Pro** fallback | **BUILT (queue #5, PR #1216)** — social images render on `gemini-3.1-flash-image` at 2K (~$0.101/img, ~25% under Pro) via `nano_banana.generate_image_pro(model=…)` (Nano Banana 2 + Pro share the `imageConfig.aspectRatio` API, both honor every ratio); the choice is `services/social/image.py::select_image_model`, behind `social_image_use_flash` (default ON, Pro the flag-off fallback). The old 2.5-Flash `generate_image` stays 1:1-only (GBP/illustration). `GEMINI_API_KEY` set on PLATFORM. |
| Publish | **PostPeer** behind an adapter | Managed OAuth under its own reviewed apps (confirmed). **X link tax passed through: 5 credits plain / 50 with a URL; 1 credit elsewhere** (confirmed). **No SLA** (confirmed, accepted). Media by public URL; one platform per `POST /posts` call; `publishNow` from OUR scheduler, never `scheduledFor`. API facts: vendor-confirm doc §6. |
| Competitor scrape | **Apify** (per-platform actors) | Public/logged-out content only. **P1 = Apify-only — BUILT + LIVE (`APIFY_API_TOKEN` set).** IG/FB/X/YouTube/Pinterest; env-overridable actor ids (`social_apify_actor_*`). |
| ~~Competitor video analysis~~ | ~~TwelveLabs~~ | **DROPPED from v1 (owner c1, 2026-09-16)** — not analyzing full videos. Don't provision/build. |
| Media download | **cobalt.tools** (self-hosted) | **P5 only** — owned/licensed assets. Not provisioned in v1. |

## Confirmed PostPeer facts (live build, 2026-09-05)

Distilled from a separate live PostPeer onboarding build (Kyle's `Sabraw Marketing`
Express app — NOT in this repo) that verified these against `postpeer.dev/docs` **and the
live dashboard**. Treat as project memory; they sharpen / correct the vendor-confirm doc.
Anything marked *(inference)* was reasoned, not quoted.

**Account status — already provisioned, don't re-ask.** Kyle already has a PostPeer account
with a **live API key**; the dashboard showed one "Default" group holding 3 LinkedIn + 1
Facebook integration. So the P0 prerequisite is only **putting the existing key on PLATFORM
as `POSTPEER_API_KEY`**, not a new signup.

**A reference implementation already exists.** The Sabraw Marketing repo has a working
PostPeer wrapper (`postpeer.js`: `checkAuth`/`createProfile`/`getProfile`/`listAllProfiles`/
`listIntegrations`/`getConnectUrl`), a client-onboarding server (`server.js` — an `/admin`
create-client page + a public `/connect/:profileId` link per client), and a **`mock-postpeer.js`
fake API** (profiles, integrations, a stand-in OAuth consent page) that let the whole flow be
clicked through locally with no real key. Mirror the connect-link pattern; consider the same
**mock-PostPeer approach for our adapter tests** (no live key in CI).

**Profile == "Social group" (naming mismatch that cost real time).** The API object `profile`
(`profileId`) is exactly what the **dashboard UI calls a "Social group."** Same object; the
dashboard never uses the word "profile." Our design already maps one profile ↔ one suite
client — keep that, and use "Social group" when writing any team/ELI5 guide.

**A profile is org-only, NOT a security boundary (load-bearing).** There is **one API key for
the whole account**; there is no per-client key and **no per-profile access control** — anyone
with the key can see/touch every client's connected accounts *(confirmed reading; docs
describe profiles only as grouping/filtering)*. Consequence for us: **client isolation is
OURS to enforce** (route every call through the client's stored `profile_id`; never expose one
client's `adapter_account_id`s to another). Treat the key as a full-account credential.

**Connect + integration endpoints (fills gaps in vendor-confirm §6):**
- `GET /connect/{platform}?profileId=&redirectUri=&appId=` → `{ url }` (the OAuth URL to
  redirect the authorizer to). `redirectUri` (send them back to our client page) and `appId`
  (BYOK, below) are real params, not just `profileId`. Platforms: twitter, youtube, tiktok,
  facebook, instagram, pinterest, linkedin, threads (**bluesky is different** — no OAuth).
- `GET /connect/integrations?profileId=&platform=&limit=&offset=` — **paginate** with
  `offset`/`limit` until `total`; each integration's `id` is the `accountId` used when posting
  (this is our stored `adapter_account_id`).
- Standard `POST/GET/PATCH/DELETE /profiles` CRUD (list pages `page`/`limit`, max 100).

**Connection health — the concrete field for our state machine.** The integration object
carries **`tokenStatus.reconnectRequired`** — that is the exact signal the failure-handling
spec's `needs_reauth` state should read (health-check sweep + inline pre-publish check).
Facebook tokens are "non-expiring under normal use"; reconnect is needed only on revoke,
password change, a **Facebook security checkpoint (error code 190/459 — the user must clear it
on facebook.com first; reconnecting alone won't fix it)**, or manual removal.

**Two ways a client gets connected** (there is no third — someone controlling the account must
approve once): (1) **client self-serves** via a connect link we send; (2) **agency authorizes
directly** when it already administers the account (common for Facebook Pages). Meta constraint:
whoever approves can only grant the **Pages they personally administer**.

**BYOK ("bring your own OAuth app") — optional, not a launch blocker.** By default clients see
"PostPeer wants permission…" on the consent screen (shared PostPeer app). `POST /apps/`
(platform, name, clientId, clientSecret) registers your own dev app; pass the returned `app.id`
as `appId` on the connect call so the consent screen shows **the agency's branding** and you get
**your own platform rate-limit quota** instead of PostPeer's pooled one. Callback to register
with each platform: `https://api.postpeer.dev/v1/connect/{platform}/callback`. Tradeoff: each
platform's own app-review takes real time — **don't block launch on it.**

**Pricing (reconcile before trusting the cost model).** The Authentication doc states **1 credit
per publish/schedule call** as the *general* rule (X is the documented 5/50 exception we already
have; failed posts don't deduct), a **free tier of 20 credits/month** (not "20 on signup"), paid
plans **from $19/mo for "thousands" of credits**, plus non-expiring PAYG packs. This differs from
the cost model's "$6–8.50/1k, 20 free on signup" framing — **flag for owner reconciliation**;
don't silently rewrite the budget scenarios off the vague "$19/mo for thousands."

**Cross-post (P5 relevance):** one video can go to TikTok + YouTube Shorts + Instagram Reels in a
single `POST /posts` by listing all three in `platforms[]`.

**Platforms beyond our v1 five (noted for later expansion):** LinkedIn (personal + Company Pages,
3,000 chars, mentions org-only), TikTok (`draft:true` sends to the creator's inbox for approval;
call `GET /tiktok/creator-info?accountId=` before posting — per-creator limits vary), Bluesky
(**no OAuth** — the client makes an app password at bsky.app and submits it once via
`POST /connect/bluesky/auth`; needs a form, not a redirect button).

**Known gap:** none of the above was tested against the **real** PostPeer API end-to-end (the
reference build only exercised its mock). The P0 smoke test — one real profile + one real
low-stakes connect + confirm `tokenStatus` behaves as documented — is still the go/no-go.

## Rails to reuse (do NOT reinvent)

- **Jobs:** widen the `async_jobs` CHECK (copy the **full live list** — it's wider than any repo
  migration) + a `job_worker` dispatch branch. Handlers settle their own row.
- **Scheduler:** export `enqueue_due_social_*()` and wire into `services/gsc_scheduler.py`; reuse
  `gbp_posts_service.compute_next_run_at` (DST/IANA-correct) for Cadence.
- **Notifications:** `notifications.emit(client_id, kind, title, …)` (dedupe_key for idempotency).
- **Freeze:** add publish/generate job types to `FREEZE_GATED_JOB_TYPES`; routers call `assert_not_frozen`.
- **Budget meter:** `social_usage(day, calls)` + `reserve_social_calls` RPC. **Copy
  `autonomy_budget.reserve` (fail-CLOSED on RPC error), NOT `keyword_research.reserve_budget`
  (fail-OPEN).**
- **Publish lifecycle:** clone the **GBP Posts** template (`services/gbp_posts_service.py`):
  draft → approve → explicit freeze-gated idempotent publish job → async status reconciliation.
- **Voice:** enforce + score via the voice-card system (`voice_card.py` / `voice_card_service.py`) —
  text-only; image brand lives in the Social Policy prompt templates.
- **Sources:** `illustration._load_article` (returns article **sections**; title from `runs.keyword`),
  `local_seo_pages.content_html`+`page_title`, `syndication_rewrite.extract_source_content` (URL → title+md);
  reuse `gbp_posts_service.list_reusable_images` for the asset picker.
- **Competitor identity:** extend `client_competitors` with a **child** `social_competitor_handles`
  table (bare handle-only rows escape its partial unique indexes → dup competitors).

## Build phases (status as of 2026-09-08)

Build order diverged from this plan deliberately — a **thin publish-path spine went in first** (manual
compose → publish/schedule) rather than P1→P2→P3 in sequence, so the module is usable before the AI
Creator exists.

- **P0 Foundations** — ✅ **BUILT** (#1027): data model (8 tables + `reserve_social_spend` RPC +
  `clients.social_profile_id`), swappable adapter + PostPeer impl, fail-closed budget meter,
  jobs/scheduler wiring, freeze gating, and the connect-and-post smoke test (PASS 2026-09-05). The
  Social Policy + autonomy-tier fields are in the schema. **Not built:** the Social Account *connect
  flow* + ELI5 per-platform guide (accounts are connected manually in PostPeer for v1 — the compose
  screen reads them live).
- **Publish path (leaner than P3) — ✅ BUILT** (#1027): compose → freeze-gated idempotent publish job
  (GBP-Posts template) → status reconcile; media upload + presign; **R2 media store** (ADR-0004).
- **Frontend compose screen + image/video upload — ✅ BUILT** (#1032): `SocialCompose.tsx`.
- **P1 Competitor research** — ✅ **BUILT + LIVE** (PR #1177, squash `3f07eda`; `APIFY_API_TOKEN` +
  `SOCIAL_COMPETITOR_RESEARCH_ENABLED=true` set on PLATFORM). **Apify-ONLY — TwelveLabs is DROPPED from v1**
  (no full-video analysis, so no per-video vendor). Analyze-in-place (ADR-0002): public/logged-out content
  only, signals keep post links + numbers + caption text, never re-hosted media. One
  **`social_competitor_research`** job per client scrapes each competitor's public per-platform handle
  (`social_competitor_handles`) via Apify → per-`(client, competitor, platform)` **`social_competitor_signals`**
  row: **deterministic** `formats`/`cadence`/`top_performers` (links + numbers only, no media/identity) +
  a **caption-only** LLM rollup (`themes`/`hook_patterns`/`whats_working`; our own Anthropic key, NOT
  metered — only Apify is). `services/social/apify.py` (sync httpx `run-sync-get-dataset-items` wrapper +
  per-platform input builders + pure post parsers for IG/FB/X/YouTube/Pinterest; config-driven,
  env-overridable actor ids, LinkedIn deferred) + `services/social/competitor_research.py` (pure aggregators
  + rollup + handle/signal CRUD + enqueue/job + weekly interval-gated scheduler sweep mirroring
  `competitor_intel`). **Fail-CLOSED** `budget.reserve` before each Apify run (copies `autonomy_budget.reserve`).
  **NOT freeze-gated** — research runs under freeze (PRD §3). Grounds `creator.propose_angles` via
  `render_competitor_signals_block` (empty signals → prompt byte-identical). Routes on `routers/social.py`
  (competitors + handles CRUD, research trigger + poll, signals read); frontend **Competitors** tab in
  `SocialCompose.tsx`. Migration `20260916200000_social_competitor_research_job.sql` (widens the
  `async_jobs` CHECK from the LIVE constraint; applied live). Config `apify_*` / `social_competitor_*` /
  `social_apify_*` in `config.py`. Tests `tests/test_social_apify.py` + `tests/test_social_competitor_research.py`.
  **Remaining confidence step:** a live research run from the dashboard (sandbox is egress-blocked from
  Apify) + confirm/replace the default Pinterest actor (`epctex/pinterest-scraper`, env-overridable).
- **P2 Creator core** — ✅ **BUILT** (copy + image + angle fan-out + draft review/publish):
  - **AI copy drafting**: `services/social/creator.py` + `POST /clients/{id}/social/draft-copy` generate
    platform-native copy from a Source (topic / URL / blog run / saved Local SEO page) + optional
    angle/tone, voice-card-enforced (reuses GBP Posts' `render_voice_card_block` / `voice_forbidden_hits`
    + a corrective rewrite), and the composer's **"Draft with AI"** panel prefills the copy box.
    Config: `social_copy_model` (`claude-sonnet-5`) / `_max_tokens` / `_max_correction_passes` /
    `_source_max_chars`.
  - **AI image generation (Nano Banana 2 default, Pro fallback — queue #5, PR #1216)**: `services/nano_banana.py::generate_image_pro` (passes `generationConfig.imageConfig.aspectRatio`; runs the model `select_image_model` picks — `gemini-3.1-flash-image` by default, `gemini-3-pro-image-preview` as the flag-off fallback) +
    `services/social/image.py` + `POST /clients/{id}/social/generate-image` + the composer's
    **"Generate an image with AI"** panel. Per-platform aspect ratio via `resolve_aspect_ratio`
    (reel/story→9:16, Pinterest→2:3, IG→4:5, X/YouTube→16:9, else 1:1 — all Gemini-supported; the
    seeded specs' `1.91:1` is NOT, hence a deliberate mapping). Prompt = the Social Policy
    `image_prompt_template` (client-editable) + brand context. **Freeze-gated + fail-closed
    budget-metered** (paid call — `budget.reserve` before spending; `select_image_model` guarantees a
    strictly-positive reserved cost so a misconfigured `$0` cost can't slip a paid image past the cap).
    Stored to R2 via `media_store` (`media_key(ext,"generated")`). Config: `social_image_use_flash`
    (default ON) / `social_image_flash_model` (`gemini-3.1-flash-image`) / `social_image_flash_cost_usd`
    ($0.101 at 2K) / `nano_banana_pro_model` / `social_image_size` (`2K`) / `social_image_cost_usd` (Pro
    fallback). The **mixed image path is BUILT** (queue #5, PR #1216 — Nano Banana 2 honors every aspect
    ratio, so all social images route to it; Pro stays the flag-off fallback), superseding the earlier
    Pro-only ruling.
  - **Angle fan-out + Draft persistence (the full Creator loop)** — BUILT. `services/social/creator.py::propose_angles`
    (`POST …/social/angles` — 3–5 distinct editorial angles, grounded in source + voice/ICP) →
    `services/social/fanout.py` + `POST …/social/fan-out` fans ONE chosen angle across the selected
    platforms as a background **`social_fanout`** job (migration `20260908130000`, freeze-gated), loading
    the source + voice card ONCE and generating one **Draft per platform** (copy via the shared
    `creator.draft_platform_copy`, opt-in per-platform image via the Pro renderer), persisted under a
    shared `angle_set_id` in `social_drafts` with status `ready`/`needs_image`/`generation_failed`. Draft
    review is `GET …/social/drafts`, `PATCH /social/drafts/{id}` (edit copy/media), `DELETE` (archive),
    and `POST /social/drafts/{id}/publish` (approve → the existing publish lifecycle, freeze-gated). The
    composer page is now tabbed **Compose / Create with AI / Drafts**. Config: `social_angles_count` (4) /
    `_max_tokens`. **The P2 Creator is functionally complete** (copy + image + angle fan-out + draft
    review/publish); competitor-signal grounding of angles rides P1.
- **P3 Manager + publish** — ✅ **BUILT + MERGED (PR #1235, squash `f326f196`)**: a
  Calendar tab (cross-platform scheduled + published, with edit/cancel/reschedule), the **cadence
  engine** (`social_post_schedules` + `enqueue_due_social_schedules`, GBP-literal clone; **auto-fill
  drips an explicitly-`queued` approved draft**, three-gated + ships dark behind
  `social_auto_publish_enabled`), an **approval queue** (batch publish + a cadence queue), and the
  **`social_policy` write path** (Settings tab: ceiling + image/text prompt templates). See
  `HANDOFF.md` (2026-09-18 P3 entry) + `p3-manager-plan-v1_0.md`. Auto-fill's unattended publish is
  deployed-only (sandbox egress-blocked from PostForMe).
- **P4 Agents, autonomy** — ✅ **BUILT + MERGED (ships dark behind `social_autonomy_enabled`)**. The Social
  Manager orchestrator + opt-in QA rubric (Phases A–C, PR #1240 `661c02c`) + the SerMaStr/PACE/DORA
  agent integration + the autonomy activity UI (Phase D, PR #1243 `102be8c`). The loop generates/queues drafts;
  it NEVER publishes (the four-opt-in gate still governs the unattended drip). See
  `p4-autonomy-plan-v1_0.md` + the HANDOFF 2026-09-19 entry. **Analytics read-back is DEFERRED** (Q5 —
  PostForMe has no analytics endpoint; its own later slice).
- **P5 Deferred** — **YouTube poster ✅ BUILT + MERGED** (PR #1211, re-scoped against PostForMe — a YT
  post = video + required `title`; not generation) and **big-video direct-to-R2 presign ✅ BUILT + MERGED**
  (PR #1213 — ⚠️ still needs the R2 CORS policy applied to work end-to-end) and the **mixed image path
  ✅ BUILT + MERGED** (PR #1216 — all social images → Nano Banana 2). **Video production — slice (a)
  Video Storyboard ✅ BUILT + MERGED** (PR #1245, squash `b1eabef`; owner forks
  2026-09-19: Q1=storyboard-only / Q2=defer-vendor / Q3=Reels+Shorts, Compose-first / Q4=autonomy
  may-propose): a shoot-ready shot-by-shot **brief** (NO rendered video, no new vendor) —
  `services/social/storyboard.py` + `social_storyboards` table + a Storyboard tab. Scope/plan:
  `p5-video-scope-v1_0.md` / `p5-video-plan-v1_0.md`. **Still deferred (separate owner decisions):**
  phase (b) deterministic assembled short-form (stills + captions + owned clips via ffmpeg, no AI
  video model) + phase (c) true AI text/image-to-video generation (needs a NEW vendor — none chosen;
  the scope doc has the vendor map) + cobalt self-host.

## Things NOT to do (module-specific)

- **Don't store platform OAuth tokens** — PostPeer holds them; `social_accounts` keeps only the
  provider's `adapter_account_id`.
- **Don't couple module code to PostPeer** — go through the adapter interface.
- **Don't download or re-host competitor media** — analyze-in-place (ADR-0002).
- **Don't auto-publish by default** — top tier + explicit per-client opt-in only.
- **IG/FB carousel + Reels/Stories are IN v1 scope AND BUILT + MERGED** (owner b1+b2; PR #1206, see
  `HANDOFF.md` 2026-09-18). Reel/Story route via `postforme_adapter.placement_config` →
  `platform_configurations.{ig|fb}.placement`; the validator is format-aware (`validate_post(..., fmt=)`);
  a **Story drops its caption** at the publish choke point (no caption / link stickers; Business-account
  is provider-enforced); **Reel = one video, no images** (manual Compose only — no AI video); carousel =
  ≥2 images, one aspect ratio, generated N slides in fan-out (`social_carousel_*` config, each slide a
  budget-reserved ~$0.10 Nano Banana 2 image — queue #5). Format rules live in **code** (the IG `social_platform_specs` row is
  per-platform), so **no migration** was needed. (IG still has **no text-only posts** — an image-less IG
  Draft is `needs_image`.) Live-verify the placement + Business-account + carousel behavior on the
  deployed post path (sandbox egress-blocked from PostForMe + Gemini).
- **Pinterest board is now FIRST-CLASS (BUILT + MERGED 2026-09-18, PR #1228, post-queue
  task 1)** — don't re-add raw-JSON board handling. A Pin carries a required `board_id` (Compose field + the
  Pinterest Draft's Board ID field; validated by `validate_post`'s `pinterest_board_required`
  rule; a fan-out Pinterest draft lands `needs_board` until set). Stored module-internal as a
  single `platform_metadata.board_id`; the **adapter edge** (`map_pinterest_board`) maps it to
  PostForMe's `board_ids: [id]` ARRAY (there is NO board-list endpoint — owner-confirmed vs
  the live spec — so the id is user-pasted). Field name = `social_pinterest_board_field`
  (`board_ids`); the exact **placement** (nested under `platform_configurations.pinterest`) is
  a first-live-Pin confirm. Scope: `pinterest-board-first-class-scope-v1_0.md`.
- **Don't hand PostPeer the schedule (`scheduledFor`)** — publish with `publishNow` from our own
  freeze-gated job so the inline account-health check + `source_changed` guard run first.
- **Don't use the old 2.5-Flash `nano_banana.generate_image` for a non-1:1 ratio** (it's 1:1-only) —
  social image gen goes through `generate_image_pro(model=…)` with **Nano Banana 2** (default) or Pro,
  which honor every aspect ratio via `imageConfig.aspectRatio` (queue #5 — the choice is
  `select_image_model`, behind `social_image_use_flash`).
- **Don't copy the keyword_research budget pattern** (fail-open) for spend — use `autonomy_budget.reserve`.

## When stuck / ask the owner

Still open (owner "let's discuss" as of 2026-09-16): the **default per-client monthly cost ceiling**
(b3); the mixed 2.5-Flash/Pro image cost lever (deferred). **P4 autonomy (c2) is BUILT + MERGED**
(ships dark). **P5 Video Studio (c3):** slice (a) Video Storyboard is **BUILT** (owner forks locked
2026-09-19 — see the P5 line above + `p5-video-scope-v1_0.md`); phase (b) assembled video and phase
(c) AI-video generation (+ its vendor choice) remain the next P5 owner decisions. Already decided — don't re-ask: IG scope = feed+Reels+Stories (b1), IG carousel in v1
(b2), autonomy case-by-case (b4), PostPeer PAYG (b5), P1 = Apify-only / TwelveLabs dropped (c1, **BUILT +
LIVE**); the mixed image path is now **BUILT** (queue #5, PR #1216 — Nano Banana 2, superseding the
earlier Pro-only ruling). The PostPeer P0 questions are closed. See `HANDOFF.md` (this folder) for the live
open-items list + the 2026-09-16 update.
