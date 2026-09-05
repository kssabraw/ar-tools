# Social Media Module — Build Context (CLAUDE.md)

> Module-scoped build primer for the **Social Media Manager + Content Creator** module.
> This does NOT replace the root `/CLAUDE.md` (the suite authority) — read that first for
> suite architecture, then this for the module. **Read this before building the social
> module.** The module is **design-complete but not built** (PR #952).

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
| Image gen | **nano-banana Pro** (Gemini 3 Pro Image) | For per-platform **aspect ratios** — the existing `services/nano_banana.py` (2.5 Flash) sends no `imageConfig` and does 1:1 only. Needs a **new Pro renderer passing `aspectRatio`**. ~$0.134/img ★. Requires `GEMINI_API_KEY` (dormant today). |
| Publish | **PostPeer** behind an adapter | Managed OAuth under its own reviewed apps (confirmed). **X link tax passed through: 5 credits plain / 50 with a URL; 1 credit elsewhere** (confirmed). **No SLA** (confirmed, accepted). Media by public URL; one platform per `POST /posts` call; `publishNow` from OUR scheduler, never `scheduledFor`. API facts: vendor-confirm doc §6. |
| Competitor scrape | **Apify** (per-platform actors) | Public/logged-out content only. |
| Competitor video analysis | **TwelveLabs** (Pegasus/Marengo) | Ingest by public URL; cap minutes/run. |
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

## Build phases

- **P0 Foundations** — data model, swappable adapter, Social Account connect + **ELI5 per-platform guide**,
  budget meter, jobs/scheduler wiring, freeze gating, **+ a thin connect-and-post PostPeer smoke test**.
  The **Social Policy + autonomy-tier fields go in the schema here.**
- **P1 Competitor research** — Apify Signals + TwelveLabs analyze-in-place → Competitor Signal.
- **P2 Creator core** — Source → Angles → per-platform Draft fan-out (incl. the nano-banana Pro renderer),
  voice-enforced, Platform-Spec validated.
- **P3 Manager + publish** — Calendar, Cadence, approval, the GBP-Posts publish lifecycle.
- **P4 Agents, autonomy, analytics** — social context providers, PACE tasks, opt-in QA rubric,
  performance read-back, the Social Manager orchestrator + top-tier opt-in auto-publish.
- **P5 Deferred** — video production (Reels/Shorts/YouTube); cobalt self-host lands here.

## Things NOT to do (module-specific)

- **Don't store platform OAuth tokens** — PostPeer holds them; `social_accounts` keeps only the
  provider's `adapter_account_id`.
- **Don't couple module code to PostPeer** — go through the adapter interface.
- **Don't download or re-host competitor media** — analyze-in-place (ADR-0002).
- **Don't auto-publish by default** — top tier + explicit per-client opt-in only.
- **Don't add an IG carousel Draft type until the owner scopes it** — PostPeer carousels ARE live
  (≤10 items, one aspect ratio throughout), so this is now a product/cost call, not a vendor limit.
  The v1 floor is single-image IG. (IG has **no text-only posts** — an image-less IG Draft is
  `needs_image`, like Pinterest.)
- **Don't hand PostPeer the schedule (`scheduledFor`)** — publish with `publishNow` from our own
  freeze-gated job so the inline account-health check + `source_changed` guard run first.
- **Don't use nano-banana 2.5 Flash where a non-1:1 aspect ratio is required** (Pinterest/9:16) — it
  can't produce it. Use the Pro renderer.
- **Don't copy the keyword_research budget pattern** (fail-open) for spend — use `autonomy_budget.reserve`.

## When stuck / ask the owner

The mixed 2.5-Flash/Pro image cost lever (build in v1 or later); whether v1 IG includes single-media
Reels/Stories or feed-only; whether an **IG carousel Draft type** is in v1; the default per-client
monthly cost ceiling. The PostPeer P0 questions are closed. See `HANDOFF.md` (this folder) for the
live open-items list.
