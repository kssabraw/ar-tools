# Social P5 — Video production ("Video Studio") — Scope v1.0

> Deferred phase, owner item **c3** ("discuss"). Scoped against the live codebase +
> current `main` (post-P4-merge `b43dff8`, #1244). Build docs: `CLAUDE.md` / `HANDOFF.md`
> (this folder). PRD: `../social-media-module-prd-v1_0.md` — §1 (YouTube storyboard-only
> approach), §2 non-goals ("no generated video; YouTube/Reels are analyze + storyboard
> only — deferred, Phase 5"), §3/§4 vendor table (cobalt = **P5-only** dependency,
> owned-assets-only), §13 phasing ("**P5 — Deferred:** video *production*
> (Reels/Shorts/YouTube)"). Legal stance: ADR-0002 (analyze-in-place, cobalt =
> owned/licensed only). Provider: ADR-0006 (PostForMe). Cost: `../social-media-cost-model-v1_0.md`.
>
> **This is a DISCUSS-FIRST scope doc, not a build.** P5 opens on scope + vendor
> decisions the PRD deliberately left un-made — there is **no AI-video-generation vendor
> chosen** (TwelveLabs was analysis-only and DROPPED, owner c1; cobalt is download-only;
> Nano Banana is images). The forks in "Open owner decisions" go to the owner via
> AskUserQuestion **before any code**. Then: plan doc → phase-by-phase build.

## Owner-confirmed decisions (2026-09-19, via AskUserQuestion)

- **Q1 (definition) = (a) Storyboard / brief only.** The first P5 slice produces a
  **storyboard/brief deliverable** — NO rendered video, NO new vendor. The phased path:
  (a) now; (b)/(c) are later, separate decisions.
- **Q2 (vendor) = Defer until (c) is scoped.** No AI-video vendor chosen; consistent with
  (a) first. The vendor map below is retained for the eventual (c) discussion.
- **Q3 (scope) = Reels + Shorts, Compose-first.** Instagram + Facebook **Reels** and
  **YouTube Shorts** storyboards, produced through a Compose-style surface (a human picks the
  Source + platform, generates, edits) — **not** the Creator fan-out. The still-image path is
  untouched.
- **Q4 (autonomy) = Autonomy may PROPOSE.** The P4 loop may surface a storyboard as a
  proposal/candidate (never auto-generate video, never auto-publish). For slice (a) there is
  no video to generate, so this is a low-cost seam (a later sub-slice); the build-now surface
  is the human Compose storyboard path.

**⇒ First slice (this PR):** a **Video Storyboard** deliverable — a Creator extension that
turns a Source (topic / URL / blog run / Local SEO page) + platform (IG Reel / FB Reel /
YouTube Short) + optional angle/tone into a structured, brand-voiced, competitor-informed
**shot-by-shot storyboard** (hook + shot list + on-screen text + script + caption + hashtags +
optional thumbnail) for the client to shoot. Persisted, editable, human-owned. No rendered
video, no new vendor. Plan: `p5-video-plan-v1_0.md`.

## The gap (what P5 would fill)

Today the module is **still-media-complete but video-generation-empty**. It can *publish*
video and *storyboard* video; it cannot *produce* video.

| Capability | Today (verified `main` @ `b43dff8`) | P5 (fork-dependent) |
|---|---|---|
| **Publish an existing video** | ✅ EXISTS. Reel (IG/FB, one video), Facebook video, YouTube (one video + required title) — a **human-uploaded** file → R2 (server path ≤200 MB; big-video direct-to-R2 presign up to ~2 GB, queue #4) → PostForMe. | unchanged |
| **YouTube / Reels *content*** | ✅ analyze + storyboard ONLY. The Creator produces a storyboard/brief + thumbnail (Nano Banana image) + title/description/hashtags for the client to **shoot themselves**. No video is generated. Fan-out **omits** Reel + YouTube (video-only, Compose-only). | a video-producing path (fork Q1) |
| **Generate a video** | ⬜ NONE. No AI-video vendor, no ffmpeg (not in any Dockerfile or `requirements.txt`), no cobalt (self-host not provisioned). Zero references in `writer/` non-docs. | fork Q1 = (b) or (c) |
| **Owned-asset media download** | ⬜ NONE. cobalt is named in the PRD/ADR-0002 as a **P5-only** dependency (self-hosted, owned/licensed assets only) but is **not provisioned** anywhere. | only if fork Q1 = (b) |

## Verified current state (`main` @ `b43dff8`)

- **Video is upload-only.** `services/social/publish.py::validate_post` has hard rules for
  `reel` (exactly one video, no images), `story` (media required, caption dropped), and
  YouTube (exactly one video, no images, 2–100-char title); `upload_media` /
  `_validate_upload` validate + store an uploaded file (server path capped at
  `social_max_upload_mb`, 200 MB); the presign path (`POST …/social/media/presign`) handles
  >200 MB video straight to R2. **Nothing generates the bytes** — every video arrives from a
  human upload.
- **No video toolchain in the repo.** `grep -riE 'ffmpeg|cobalt'` over `writer/**/*.py`
  returns nothing. No moviepy/ffmpeg-python dep. The `video` references in
  `services/social/*` are all about *handling* an uploaded/scraped video URL, not creating one.
- **Still-image generation is built + dominant.** `services/social/image.py::select_image_model`
  → `nano_banana.generate_image_pro(model=…)` on **Nano Banana 2** (`gemini-3.1-flash-image`,
  2K, ~$0.101/img) via the already-set `GEMINI_API_KEY`, fail-closed budget-reserved,
  freeze-gated. This is the reusable "generate a still + overlay in-image text" primitive a
  fork-(b) assembled video would lean on.
- **The Creator storyboard path exists** (`services/social/creator.py`) — copy + angle + a
  Nano Banana thumbnail; a fork-(a) storyboard/brief deliverable is mostly this, extended.
- **Fan-out excludes video** deliberately (Reel + YouTube are Compose-only, no AI video in v1).
- **Budget is fail-CLOSED** (`services/social/budget.py::reserve`, copies
  `autonomy_budget.reserve`); `budget.release` refunds a failed paid step. Any new paid
  video call reserves before it spends, with a strictly-positive floor (the budget-bypass
  guard from queue #5 — a `$0` cost can't slip a paid call past the meter).
- **cobalt legal constraint is locked (ADR-0002):** self-hosted only, **owned/licensed
  assets only, NEVER competitor media.** A fork-(b) build that downloads a clip must carry a
  license/permission provenance gate before the asset can enter a publish flow.

## The load-bearing fork — what "video production" MEANS (fork Q1)

The PRD phrase "video production (Reels/Shorts/YouTube)" spans three very different builds,
in ascending order of cost, risk, and new dependency. This is the decision everything else
hangs on.

### (a) Storyboard / brief deliverable only — **no rendered video**
Extend the Creator to produce a **shot-by-shot storyboard + script + shot list + thumbnail +
title/description/hashtags** for the client (or agency videographer) to shoot. **No video file
is generated.** This is the PRD's *current* YouTube posture, generalized to Reels/Shorts and
made a first-class Draft type.
- **New vendor:** none. **New infra:** none. Reuses the Creator + competitor Signals (P1) +
  Nano Banana (thumbnail).
- **Cost:** a few Sonnet calls per storyboard (~$0.03), same order as a copy Draft. Trivial.
- **Risk:** lowest. No copyright surface, no render pipeline, no unattended spend risk.
- **Delivers:** a repeatable, brand-voiced, competitor-informed production brief — closes the
  "we storyboard by hand" gap without touching video generation.

### (b) Deterministic ASSEMBLED short-form video — **no AI video model**
Stitch a video from parts the module already can produce or legally hold: generated **stills**
(Nano Banana), **captions/text overlays**, Ken-Burns/pan-zoom motion, transitions, and
**owned/licensed clips** (downloaded via **cobalt**, ADR-0002-gated), assembled with **ffmpeg**.
Think "animated carousel / slideshow Reel," not a generative film.
- **New vendor:** none for generation (cobalt is download-only, self-hosted). **New infra:**
  **ffmpeg** in the platform-api (or a dedicated worker) Docker image, and a **cobalt
  self-host on Railway** IF owned-clip download is in scope. A render is CPU/time-heavy →
  likely its own `async_jobs` type + possibly a bulk lane (like the Local SEO page lane).
- **Cost:** stills (~$0.10/img × N frames) + compute (ffmpeg CPU, effectively free on
  Railway) + optional cobalt. Bounded and predictable; no per-second generative fee.
- **Risk:** medium. The render pipeline is real engineering (ffmpeg in the image, long jobs,
  the event-loop-safety rule — any blocking ffmpeg call MUST go through `asyncio.to_thread`);
  the cobalt path needs the ADR-0002 license-provenance gate. No new AI-vendor risk.
- **Delivers:** actual publishable short-form video (Reels/Shorts) from owned material — the
  most common agency use (product/service slideshow + captions) — without an AI-video vendor.

### (c) True text/image-to-video GENERATION — **needs a NEW vendor**
Generate net-new video from a prompt (or an image → video) via an AI video model
(Veo/Runway/Kling/Sora-class API). The "make a Reel from this blog post" magic path.
- **New vendor:** REQUIRED (fork Q2 — none is chosen). **New infra:** a video-gen client
  service + the render/poll job (these models are async, minutes-long).
- **Cost:** the **dominant, order-of-magnitude-larger** line — generative video is priced
  **per second of output** (roughly cents-to-low-dollars per second depending on model/
  resolution; a single 8-second clip can cost more than a whole month of a client's still
  images). Live pricing is **not verifiable from the sandbox** (egress-blocked) and is an
  owner/deployed confirm.
- **Risk:** highest. Cost blast radius (the fail-closed meter + per-client ceiling become
  load-bearing, not advisory), provider maturity/ToS/watermarking, quality variance, and the
  **autonomy question becomes sharp** (should an unattended loop ever spend $$ on a
  generated video? — default proposed **no**, fork Q4).
- **Delivers:** the highest-ceiling capability and the biggest differentiator — and the
  biggest new-vendor + cost commitment.

> **Recommendation for discussion:** phase it — **(a) first** (cheap, no vendor, immediately
> useful, and it's the brief that a later (b)/(c) render consumes), then decide (b) vs (c) as
> a *second* slice once (a) proves the shape. (a) and (b) are additive and can both precede any
> (c) vendor commitment. This is a recommendation, not a decision — the owner picks.

## Vendor landscape — ONLY relevant if fork Q1 = (c) (fork Q2)

No AI-video vendor is chosen. Candidates below are a **map for the discussion, not a
shortlist** — availability, exact pricing, API shape, and ToS are **owner/deployed-confirm**
(sandbox is egress-blocked from every video vendor; my knowledge cutoff is Jan 2026, so treat
all pricing as "verify live").

| Candidate | Why it might fit | Watch-outs |
|---|---|---|
| **Google Veo (via Gemini API)** | **Single-vendor synergy** — the suite already holds `GEMINI_API_KEY` and generates stills on Nano Banana (Gemini); a Veo path could reuse the key + `services/nano_banana.py` HTTP shape, no net-new vendor account. | Confirm current model id, per-second price, max duration/resolution, and image-to-video support live. |
| **Runway (Gen-family)** | Mature API, strong image-to-video, established creative-tool market position. | Net-new vendor + key; per-second pricing; confirm API + ToS for agency/commercial reposting. |
| **Kling** | Competitive quality/price; popular for short-form. | Net-new vendor + key; confirm API access tier, region availability, ToS. |
| **OpenAI Sora (API)** | If/when a stable API tier exists; the suite already uses OpenAI (`OPENAI_API_KEY` on some services) for content prose. | Confirm API availability + pricing + commercial-use ToS live. |

**Default lean (for discussion):** if (c) is chosen, **Veo-via-Gemini** is the lowest
integration-cost starting point (existing key, existing Gemini HTTP client pattern) — but the
choice is the owner's and rides a live pricing/quality check.

## Scope questions beyond the fork (fork Q3)

- **Formats:** Reels (IG/FB) vs YouTube Shorts vs both; TikTok (not a v1 platform — its own
  connect + `draft:true` inbox-review behavior; likely out of P5 v1).
- **Entry point:** manual **Compose** with generated/assembled video (human picks/edits) vs
  **Creator fan-out** producing video Drafts. Recommendation: **Compose-first** (mirrors how
  Reels shipped — no AI video in fan-out until the path is proven).
- **The still-image floor stays.** P5 is additive; a client that never wants video is
  unaffected, and every current still/carousel/upload path is untouched.

## Cost / budget (fork Q4)

- **Metering:** every paid video step reserves against the **fail-closed** `social_usage`
  meter + the per-client **monthly ceiling** (`social_policy.monthly_ceiling_usd`, default
  $100) BEFORE it spends — same discipline as image gen, with the strictly-positive-cost
  floor (queue #5 budget-bypass guard). For (c) especially, a **per-video hard cost cap** +
  a max-duration clamp are the runaway backstops.
- **Cost model impact:** (a) is negligible; (b) adds bounded still + compute cost; (c) adds a
  **new dominant line** (per-second generation) that would need its own row in
  `social-media-cost-model-v1_0.md` and likely a lower default ceiling or a separate
  video-specific sub-ceiling. This gets modeled in the plan doc once the fork is chosen.
- **Autonomy (P4):** the P4 loop ships **dark** and never publishes; the proposal is that P4
  **never triggers video generation** in v1 (video stays **human-initiated only**), so a
  runaway autonomous loop can't spend on video. Fork Q4 confirms this. (P5 video would not be
  added to the autonomy `gather_candidates` / `AUTO_EXECUTE` set.)

## Reuse map (do NOT reinvent) — fork-dependent

| Need | Reuse |
|---|---|
| Storyboard/brief generation (a) | `services/social/creator.py` (copy/angle) + `nano_banana.generate_image_pro` (thumbnail) + P1 competitor Signals grounding |
| Still frames for an assembled video (b) | `services/social/image.py::select_image_model` → Nano Banana 2 (already built, budget-reserved) |
| Owned-clip download (b) | cobalt (self-hosted, ADR-0002 owned/licensed-only + a provenance gate — NEW) |
| Long render job (b/c) | `async_jobs` (widen the LIVE CHECK) + `job_worker` dispatch + likely a bulk lane; **blocking ffmpeg/HTTP MUST go through `asyncio.to_thread`** (the event-loop-safety rule) |
| Media store | `services/social/media_store.py` (R2 behind `MediaStore`, ADR-0004) — a rendered video lands here like an uploaded one |
| Publish the result | `publish.py` / `fanout.publish_existing_draft` — a generated video is just a video URL into the existing Reel/YouTube path (validators unchanged) |
| Budget | `services/social/budget.py::reserve` (fail-CLOSED) + `ceiling_for_client` |
| Freeze | new generate/render job types → `FREEZE_GATED_JOB_TYPES`; routes `assert_not_frozen` |
| Scheduler / notifications | `gsc_scheduler` (if a due-sweep is needed) + `notifications.emit(dedupe_key=…)` |

## Constraints (from the task + module ADRs)

- Provider fields ONLY at the `postforme_adapter` edge (P5 adds none — a generated video is a
  URL into the existing publish path).
- Migrations in `writer/supabase/migrations/`, applied live via the Supabase MCP; widen any
  `async_jobs` CHECK **from the LIVE constraint**.
- Reuse `async_jobs` + `job_worker`, `gsc_scheduler`, `notifications.emit`, freeze gating, the
  fail-CLOSED `budget`. **Never echo live secrets.**
- **cobalt = owned/licensed assets ONLY, never competitor media** (ADR-0002), self-hosted.
- Any blocking call (ffmpeg, a sync video-vendor SDK, a no-timeout socket) MUST run off the
  event loop (`asyncio.to_thread` in a job, `run_in_threadpool` in a route) **with an explicit
  timeout** — the suite's single shared loop means one unbounded blocking call is an outage.
- `platform-api` pytest + `ruff check .` on changed files; frontend `tsc -b` + eslint (keep
  `SocialCompose.tsx` at 0 problems) if touched. mypy: no new own-file errors.

## Phasing sketch (settled after the fork is chosen)

Illustrative — the real phasing lands in the plan doc once Q1–Q4 are answered:
- If **(a):** one slice — a Storyboard Draft type (Creator extension + a Compose/Drafts
  surface). No migration beyond a possible draft-type marker (free-text `social_drafts` status).
- If **(b):** (a) first, then the ffmpeg render pipeline (Docker image change + a render
  `async_jobs` type + the assembly service) and, if owned-clip download is in scope, the
  cobalt self-host + provenance gate as its own slice.
- If **(c):** (a) first, then the chosen-vendor client + the async generate/poll job +
  per-video cost cap + the cost-model row + the ceiling review — the vendor commitment is its
  own reviewed slice with a live pricing/quality confirm before enablement.

## Open owner decisions (put to the owner BEFORE any code)

- **Q1 — What "video production" MEANS** (the load-bearing fork): (a) storyboard/brief only /
  (b) deterministic assembled short-form (stills + captions + owned clips via ffmpeg, no AI
  video model) / (c) true AI text/image-to-video generation (needs a new vendor). Recommendation:
  phase — (a) first, then decide (b) vs (c).
- **Q2 — Vendor** (only if Q1 = c): which text/image-to-video model — Veo-via-Gemini
  (lowest integration cost, existing key) / Runway / Kling / Sora / other. None chosen;
  pricing + availability are a live confirm.
- **Q3 — Scope:** Reels vs YouTube Shorts vs both; which platforms (IG/FB Reels, YouTube
  Shorts, TikTok); manual-Compose-with-generated-video vs Creator fan-out. The still-image
  floor stays regardless.
- **Q4 — Cost / autonomy:** how video meters against the fail-closed budget + per-client
  ceiling (per-video hard cap + max-duration clamp for (c)?), and whether the P4 autonomy loop
  may EVER trigger video generation. Recommendation: **video is human-initiated only**;
  autonomy never spends on it in v1.

## Deployed-only / not-P5-build (flag, don't attempt in-sandbox)

All sandbox-egress-blocked (PostForMe / R2 / Apify / Gemini / any video vendor / a cobalt
self-host on Railway) — deployed-only, independent of this scope work: a live PostForMe test
post; the R2 CORS policy on `smm-media` (queue #4 prereq); first live YouTube post; the
first-live-Pin `board_ids` placement confirm; a live P1 research run + Pinterest-actor confirm;
the #5 flash model-id confirm; the P4 live autonomy-loop + QA verification
(`SOCIAL_AUTONOMY_ENABLED=true` + a client's `autonomy_tier > 0`; PACE producers also need
`NATIVE_TASKS_ENABLED` + the two `TASK_PRODUCER_SOCIAL_*` flags); and **Analytics read-back**
(deferred P4 slice, needs a metric-source decision — separate from P5). Any live video-vendor
pricing/quality/ToS check is likewise deployed/owner-confirm.
