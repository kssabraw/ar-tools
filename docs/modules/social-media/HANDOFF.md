# Social Media Module — Handoff

> Module-scoped handoff for the **Social Media Manager + Content Creator** module.
> Not the root `/HANDOFF.md` (the suite-wide one). Read `CLAUDE.md` (this folder) for the
> build primer; this file is **current state + what to do next**.

## Next priority (owner-set 2026-09-18) — the build queue, in order

Everything through P2 + P1 is built/merged/live and the PostForMe swap is activated (below).
The owner set the **next build order** to these five, top-to-bottom:

1. **Instagram scope-out — Reels + Stories** (decision b1: BOTH) — **✅ BUILT + MERGED (PR
   [#1206](https://github.com/kssabraw/ar-tools/pull/1206))**, see the 2026-09-18 update below.
2. **IG carousel Draft type** (decision b2: YES) — **✅ BUILT + MERGED (same PR #1206)**, see below.
3. **YouTube poster** — **✅ BUILT + MERGED (PR [#1211](https://github.com/kssabraw/ar-tools/pull/1211),
   squash `44c5e06`)**. A YouTube post = a video + a required `title` via
   `platform_configurations.youtube` (first-class field, folded in by `publish.build_youtube_config`
   which forces only the `public` privacy default; `validate_post` YouTube rule; fanout excludes YT;
   migration `20260918130000` fixed the seeded spec). Deployed-only: verify the `privacy_status` field
   name + one live end-to-end post. Uploads existing videos, **not** generation.
4. **Big-video direct-to-R2 (presign)** — **✅ BUILT + MERGED (PR
   [#1213](https://github.com/kssabraw/ar-tools/pull/1213), squash `069d618`).** The composer routes a
   video **over the 200 MB server cap** (up to a 2 GB advisory client cap) through the existing
   `POST …/social/media/presign` → a browser `fetch` PUT straight to R2 → `public_url`; images + videos
   ≤ 200 MB keep the server path (no CORS dependency). Presign expiry bumped to 2 h
   (`social_presign_expiry_seconds`) for slow multi-GB uploads. **⚠️ Prerequisite still open (owner
   infra, deployed-only): apply the R2 bucket CORS policy** (below) — until then the big-video PUT fails
   its preflight (surfaced as a clear error); small videos + images are unaffected. Provider-agnostic.
5. **Mixed image path** — **✅ BUILT + MERGED (PR [#1216](https://github.com/kssabraw/ar-tools/pull/1216),
   squash `cf9ffa0`).** All social images now render on **Nano Banana 2** (`gemini-3.1-flash-image`) at 2K
   (~25% under Pro; it honors every aspect ratio, so the original "2.5-Flash-for-square" premise was
   obsolete), behind `social_image_use_flash` (default ON, Pro the flag-off fallback). See the 2026-09-18
   update below. **This was the last unbuilt queue item — the build queue is now fully built.**

> These supersede the older "Remaining build" ordering further down this file. The two live
> confidence checks (a real test post on the PostForMe path; a live P1 competitor-research
> run) and the human/deployed-only PostForMe follow-ups (below) are **not** build work — they
> happen whenever a real key + account are in place, independent of this queue.

## Update (2026-09-18) — **P3 Manager BUILT + MERGED** (PR [#1235](https://github.com/kssabraw/ar-tools/pull/1235), squash `f326f196`) — Calendar / cadence / approval queue / policy write path (post-queue task 2; scope: `p3-manager-scope-v1_0.md`; plan: `p3-manager-plan-v1_0.md`)

The second post-queue item. Scope-doc → **AskUserQuestion** → plan-doc → build, per the
owner's confirm-forks-first preference. **Owner decisions (locked 2026-09-18):**
- **Q1 cadence behavior = Auto-fill (drip approved queue)** — the sweep publishes an
  explicitly-`queued`, human-approved draft on the schedule's rhythm, UNATTENDED. Crosses the
  PRD auto-publish line **on purpose**, kept safe by **three gates** (all must hold):
  `social_auto_publish_enabled` (config, **default False — ships dark**) + the schedule's
  `auto_fill=true` (per-client/platform opt-in) + an explicitly `queued` draft. Off/empty →
  a suggest-nudge (`social_slot_due` / `social_slot_empty`). P4 will add the `autonomy_tier` gate.
- **Q2 phasing = b → c → d+a** (management-first). **Q3 policy scope = consumer fields only**
  (ceiling + image/text prompt templates + cadence; P4 planning fields deferred).
  **Q4 default ceiling = $100** (`social_monthly_ceiling_default_usd` 75 → 100).

**Merged to `main`** (squash `f326f196`), CI green (ruff/mypy/pytest ✅ + Netlify preview ✅). An
adversarial self-review after the build found + fixed **3 real bugs** (all with regression tests):
(1) `schedules.upsert_schedule` didn't range-validate `hour_local`/`day_of_week`/`day_of_month`, so a
direct API call could 500 in `compute_next_run_at` (hour≥24) and a stored `day_of_month=31` could
poison the sweep in a 30-day month → now 422-validated + the sweep self-deactivates an un-computable
row instead of aborting the tick; (2) `publish.list_calendar` crashed comparing a naive `from`/`to`
query bound to tz-aware timestamps → naive bounds now treated as UTC; (3) the Settings schedule editor
could save with no account → defaults once accounts load.

**What shipped:**
- **Migration `20260918140000_social_post_schedules.sql`** (**applied live**) — the per-`(client,
  platform)` cadence table (GBP-literal clone). No `async_jobs` type (the drip reuses
  `social_publish` via `publish_existing_draft`); no `social_posts` status change; `social_drafts`
  gained a free-text `queued` status (no migration).
- **(a) cadence** `services/social/schedules.py` — reuses `compute_next_run_at` verbatim;
  `enqueue_due_social_schedules()` (pure `decide_slot` drip/empty/suggest, freeze-skipped, self-clocked
  `next_run_at`) wired into `gsc_scheduler` per-tick beside `social_scheduled_posts`.
- **(b) calendar/edit** `publish.list_calendar` / `cancel_post` / `reschedule_post` /
  `edit_scheduled_post` (guarded to `scheduled`; 409 mid-publish) + routes; `SocialPostResponse`
  gained `draft_id` (so the calendar can edit the draft copy).
- **(c) approval queue** `fanout.publish_drafts_batch` (partial success) + `enqueue_draft`/
  `dequeue_draft`/`next_queued_draft` + routes.
- **(d) policy** `services/social/policy.py` (`monthly_ceiling_usd` + image/text templates;
  `text_prompt_template` wired into `creator.draft_platform_copy` as a mid-priority steering block —
  None → byte-identical) + routes.
- **Frontend** `SocialCompose.tsx`: **Calendar** + **Settings** tabs; Drafts tab gained
  "Publish all ready" + per-draft Add/Remove-from-queue + a `queued` badge. `errorGuidance` for the
  new codes. `tsc` + `eslint` clean (SocialCompose 0 problems).
- **Tests** `tests/test_social_p3.py` (20) — decision matrix, slot routing, cancel/reschedule/edit
  guards, batch partial-success, policy filter/validate, schedule range-validation, naive-calendar-bounds.
  **103 social tests pass**; ruff clean.

**Deployed-only / open (sandbox egress-blocked from PostForMe):**
- **To activate the drip:** flip **`SOCIAL_AUTO_PUBLISH_ENABLED=true`** on PLATFORM (config default
  False — ships dark). Even then a post drips ONLY when its schedule has `auto_fill=true` AND a human
  has explicitly `queued` an approved draft; empty/off → a suggest-nudge, never an unattended publish.
- **Verify on the deployed path:** a live auto-fill drip (schedule due → queued draft publishes), and
  the Calendar/approval-queue/policy surfaces against real accounts. Cadence + management + policy work
  today with `SOCIAL_ENABLED` alone; only the unattended drip needs the extra flag.

**Next:** P4 autonomy (owner c2, "discuss") / P5 video (c3) remain the module's discuss-first items.

**Next:** P4 autonomy (owner c2, "discuss") / P5 video (c3). The deployed-only confidence checks
below are unchanged.

## Update (2026-09-18) — **Pinterest board made first-class — BUILT + MERGED** (PR [#1228](https://github.com/kssabraw/ar-tools/pull/1228); post-queue task 1; scope: `pinterest-board-first-class-scope-v1_0.md`)

The first of the two owner-set post-queue items (Pinterest → then P3 Manager) — **merged to
`main`**. CI green (platform-api lint&typecheck ✅ + tests ✅ + Netlify preview ✅), and an
adversarial self-review (re-read every touched file, traced flow, grepped call sites, re-ran
ruff/mypy/pytest/tsc/eslint) found **no correctness bugs** — 117 social tests pass; the four
findings were all LOW (intentional advanced-JSON precedence, a defensive unreachable
errorGuidance entry, PostPeer provider-parity out of scope, and a cosmetically-`ready`
Pinterest-carousel case that `too_many_images` blocks before publish) and left as-is. Pinterest
was wired end-to-end EXCEPT the board — pure opaque passthrough (a board only reached the
provider if a human typed raw JSON), so a boardless Pin failed at publish as a generic
`postforme_invalid_request`. Board is now a **first-class, required, validated** field.

**Owner-confirmed data-flow first (2026-09-18, via Claude-in-Chrome against the live
OpenAPI spec):** PostForMe has **no board-list endpoint** (all 13 endpoints checked) — the
only board handle is the input field **`board_ids`** (a Pinterest board-IDs **array**) in
`POST /v1/social-posts`. So a provider board dropdown isn't buildable; **board entry is
field-based** (paste the numeric id). Decisions: **block** a boardless Pin (not warn);
**keep** the research actor default (`epctex/pinterest-scraper`, confirm on first live run).

**What shipped (single PR, no migration):**
- **Adapter edge** (`postforme_adapter.map_pinterest_board`, wired into `build_post_payload`)
  — maps our module-internal single `board_id` → PostForMe's `board_ids: [id]` **array**
  under `platform_configurations.pinterest`. The provider shape lives ONLY here (per the
  ADR-0006 edge rule). Field name is `settings.social_pinterest_board_field` (`board_ids`,
  env-overridable without a redeploy if the live field is `board_id`).
- **Publish** (`publish.py`) — `validate_post(…, board_id=)` adds a hard
  `pinterest_board_required` rule (Pinterest can't create a boardless pin);
  `build_pinterest_config` folds the board into `platform_metadata` (module-internal
  `board_id`); `create_post(…, board_id=)` extracts → validates → stores. Mirrors the
  YouTube-title pattern (queue #3), except the provider `board_ids[]` mapping is at the edge.
- **Fanout** (`fanout.py`) — a fan-out Pinterest draft (has image, no board) lands
  **`needs_board`** (`draft_status(…, board_required_missing=)`; `social_drafts.status` is
  free-text so **no migration**); `update_draft(…, board_id=)` sets the board and flips
  `needs_board → ready`; `publish_existing_draft` reads the board from the draft's
  `platform_metadata` and validates it.
- **Models/router/config** — `SocialPostCreateRequest.board_id`,
  `SocialDraftUpdateRequest.board_id`, wired through the routes; `social_pinterest_board_field`.
- **Frontend** (`SocialCompose.tsx`, eslint stays 0) — a required **"Board ID"** field on
  Compose (Pinterest only, with find-your-board-id help + a `hints` block), sent as
  `board_id`; a Board ID field + `needs_board` badge on the Pinterest Draft (saving the
  board flips it to ready); advanced-JSON placeholder no longer suggests a board key.
  `errorGuidance`: `pinterest_board_required` + the enriched `social_spec_violation`.
- **Tests** — `map_pinterest_board` + `build_post_payload` Pinterest mapping
  (`test_social_postforme.py`), the `validate_post` board rule + `build_pinterest_config` +
  `_pinterest_board_id` (`test_social_publish.py`), `draft_status` `needs_board`
  (`test_social_fanout.py`). 104 social tests pass; ruff clean; frontend tsc/eslint clean.

**Deployed-only confirm (sandbox egress-blocked from PostForMe):** the **first live Pin**
confirms the `board_ids` **placement** — default is nested under
`platform_configurations.pinterest` (like YouTube `title` + IG/FB `placement`); if PostForMe
takes it top-level or as `board_id`, it's a one-line adapter change / the config knob. A
wrong placement fails the post (not silently ignored), so it surfaces on the first live Pin.

**Next:** P3 Manager (Calendar / Cadence / Approval queue + a `social_policy` write path).

## Update (2026-09-18) — **Queue #5 (mixed image path) BUILT + MERGED — the build queue is COMPLETE** (PR [#1216](https://github.com/kssabraw/ar-tools/pull/1216))

**#5 mixed image path — MERGED** (squash `cf9ffa0`). **Scope evolved when grounded against current
models (owner-confirmed before build):** the queued "route squares to 2.5-Flash, keep Pro for
non-square" premise was obsolete — the latest Flash tier, **Nano Banana 2** (`gemini-3.1-flash-image`),
honors EVERY aspect ratio via the identical `generationConfig.imageConfig.aspectRatio` API as Pro, at
~$0.101 at 2K (~25% under Pro's $0.134). So **all** social images now route to Nano Banana 2 at 2K (not
just squares); Pro is a flag-gated fallback. The cost saver hits the whole dominant image line, not
only square posts.

- **`services/social/image.py`** — new pure **`select_image_model`** is the single decision point
  (composer + fan-out + carousel all flow through `generate_image`); returns `(model_id, cost)` and
  **guarantees a strictly-positive reserved cost** so a misconfigured `$0` cost can't slip a paid image
  past the fail-closed budget (`budget.reserve(amount<=0)` is a no-op that *succeeds* — the budget-bypass
  guard; a zeroed model cost falls back to the other model's cost, else a `$0.05` floor).
- **`services/nano_banana.py`** — `generate_image_pro` gained an optional `model` param (Pro + Nano
  Banana 2 share the imageConfig API, so the Flash branch returns `(bytes, mime)` symmetrically). The Pro
  default and the old 2.5-Flash `generate_image` (GBP posts / illustration) are **untouched**.
- **Config:** `social_image_use_flash` (default **True**, flip off → Pro-only, no deploy),
  `social_image_flash_model` (`gemini-3.1-flash-image`, env-overridable), `social_image_flash_cost_usd`
  ($0.101 at 2K). `social_image_cost_usd`/`nano_banana_pro_model`/`social_image_size` unchanged. **No
  migration; no new env** (reuses the already-set `GEMINI_API_KEY`; flash is ON by default).
- **Also folded in (owner-requested follow-ups after the review pass):** the budget-bypass guard above,
  and a **SocialCompose eslint cleanup** (6 pre-existing `react-hooks` v7 problems → 0 — four
  `set-state-in-effect` derived-state syncs → React's adjust-state-during-render pattern, `accounts`
  wrapped in `useMemo`, and the schedule-min `Date.now()` moved out of render into a run-once `useState`
  initializer). Behavior preserved (server-side `_ensure_future_iso` still enforces future publish times).
- Tests: 40 social tests pass; ruff/mypy clean; frontend `tsc`/`eslint` clean.

**Deployed-only follow-up (sandbox egress-blocked from Gemini):** on the first live generation, confirm
the model id `gemini-3.1-flash-image` (GA) vs a `-preview` id — override via `SOCIAL_IMAGE_FLASH_MODEL`
if Google only exposes the preview id; verify a real non-square render (IG 4:5 / Reels 9:16) comes back
at that ratio and the `cost_usd` line drops. Rollback lever if quality disappoints:
`SOCIAL_IMAGE_USE_FLASH=false` (Pro-only, no deploy).

## Update (2026-09-18) — **Queue #3 (YouTube poster) + #4 (big-video presign) BUILT + MERGED**

**#3 YouTube poster — MERGED** (PR [#1211](https://github.com/kssabraw/ar-tools/pull/1211), squash
`44c5e06`). A YouTube post = a video + a **required `title`** via `platform_configurations.youtube`
(first-class request field → `publish.build_youtube_config`, which forces only the `public` privacy
default; `made_for_kids`/tags/category ride the advanced-JSON passthrough). `validate_post` gained a
YouTube rule (exactly one video, no images, non-empty 2–100-char title); fanout **excludes** YouTube
(video-only, Compose-only); migration `20260918130000` fixed the seeded `youtube` spec row (`max_images`
1→0). **Deployed-only follow-up:** verify the `privacy_status` field name takes effect + one live
end-to-end YouTube post (sandbox egress-blocked from PostForMe).

**#4 big-video presign — MERGED** (PR [#1213](https://github.com/kssabraw/ar-tools/pull/1213), squash
`069d618`) — details below. **⚠️ Its one open prerequisite is the R2 CORS policy (next section).**

Next queue item is **#5 (mixed image path)**, still "later" per the owner.

## Update (2026-09-18) — **Queue #4 (big-video direct-to-R2 presign) — MERGED** (PR #1213) — ⚠️ needs the R2 CORS policy applied

The composer now uploads a **video over the 200 MB server multipart cap** (up to a **2 GB** advisory
client cap; R2's real single-PUT limit is ~5 GB) **straight to R2** via the pre-existing
`POST …/social/media/presign` endpoint: `presignAndPutVideo` requests the presigned URL then does a
cross-origin `fetch` **PUT** of the file to the R2 S3 endpoint (no auth header — the URL carries the
signature; the exact `Content-Type` it was signed with is sent back), and passes the returned
`public_url` into the post. **Additive — nothing that works today changes:** images and videos ≤ 200 MB
keep the server multipart path (PIL-verified, no CORS dependency); only the previously-impossible
>200 MB video path is new. Backend: `presign_upload` now signs a **2 h** URL
(`social_presign_expiry_seconds`=7200) so a multi-GB upload on a slow link doesn't outlast it. A failed
direct PUT (e.g. CORS not yet applied) surfaces a clear "tell an admin" error, not a silent hang.

### ⚠️ Prerequisite — apply the R2 bucket CORS policy (owner, deployed-only)

The browser PUT is cross-origin (Netlify origin → `<account>.r2.cloudflarestorage.com`), so it triggers
a CORS preflight the bucket must allow. **Until this is applied, big-video upload fails its preflight.**
The sandbox is egress-blocked from R2/Cloudflare and this is the shared prod `smm-media` bucket, so it's
an owner step (not applied here). Set this CORS policy on the bucket:

```json
{
  "CORSRules": [
    {
      "AllowedOrigins": ["https://<the suite's Netlify prod origin>"],
      "AllowedMethods": ["PUT"],
      "AllowedHeaders": ["content-type"],
      "MaxAgeSeconds": 3600
    }
  ]
}
```

Replace `<…prod origin>` with the live frontend origin (and add any custom domain; **`deploy-preview-*.netlify.app`
preview origins are NOT covered** unless added — the browser PUT won't work from a preview build until then).
Apply either via the **Cloudflare dashboard** (R2 → `smm-media` → Settings → CORS Policy) or the S3 API:

```
aws s3api put-bucket-cors --bucket smm-media \
  --cors-configuration file://r2-cors.json \
  --endpoint-url https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com
```

Then verify from the deployed app: upload a >200 MB video in a client's Social → Compose → it PUTs to R2
and the post publishes with that video. (`AllowedHeaders: ["*"]` also works if you prefer; `content-type`
is the minimal set the presigned PUT needs.)

## Update (2026-09-18) — **Queue #1 (Reels + Stories) + #2 (IG carousel) BUILT + MERGED** (PR [#1206](https://github.com/kssabraw/ar-tools/pull/1206))

Both built + merged to `main` in ONE PR (they share the format/spec/composer/validator/adapter
groundwork). Owner-confirmed data-flow first: format→placement threaded as a new `fmt` param on
`adapter.post()`, **mapped only at the PostForMe adapter edge**; strict format-aware validator; one PR.
**Next queue item is #3 (YouTube poster).** The live confidence checks below (a real Reel + Story on
IG/FB; a carousel fan-out) are deployed-only (sandbox egress-blocked from PostForMe + Gemini).

**#1 Reels + Stories.** The composer already offered Reel/Story and `social_drafts.format` already
allowed them, but the stored `format` **was never threaded to the adapter** — so a Reel/Story published
as an ordinary feed post. Now wired end-to-end:
- **Adapter** (`postforme_adapter.py`): `placement_config(platform, fmt)` maps `reel`/`story` on
  **Instagram + Facebook** → `platform_configurations.{platform}.placement` = `reels`/`stories` (else
  default `timeline`); `build_post_payload`/`post` merge it into any user config block. The ABC
  `SocialPostingAdapter.post()` gains `fmt="feed"`; PostPeer accepts + ignores it (dormant fallback).
- **Publish** (`publish.py`/`fanout.py`): `run_publish_job` reads the draft format → `adapter.post(fmt)`
  and **drops the caption for Stories** at that choke point (Stories carry no caption / link stickers).
  `validate_post` is format-aware: **Reel = one video, no images**; **Story = media required, caption
  ignored** (never `empty_post`/`over_char_limit` for a caption-less Story; works for Facebook too).
  Fan-out skips the discarded copy generation for Story drafts.
- **Composer** (`SocialCompose.tsx`): Story hides the caption + AI-copy panel, sends empty copy, shows a
  Business-account / no-caption-or-link-stickers note, and forces image generation in fan-out. Reel
  disables image controls (single video) with format-aware hints. **Fan-out omits Reel** (no AI video in
  v1 — Reels are for manual Compose with an uploaded video).

**#2 IG/FB carousel Draft type.** `format='carousel'` (already in the CHECK), ≤10 items, one shared
aspect ratio:
- **Validator:** carousel → ≥2 media items (`carousel_needs_multiple`); the per-spec `max_images` still
  caps at ≤10. Placement stays default `timeline` (a carousel is just multiple media items).
- **Fan-out multi-slide gen:** `SocialFanoutRequest.slides` (2–`social_carousel_max_slides`=10, default
  `social_carousel_default_slides`=3). `creator.carousel_slide_descriptions` plans N distinct slide
  visuals from the source/angle (one bounded LLM call, deterministic per-slide fallback on failure);
  `fanout._generate_carousel_images` generates one Pro image per slide at the platform's single carousel
  aspect ratio. **Each slide is a separate paid image reserved individually against the fail-closed
  budget — the cost multiplies per slide** (~$0.13/slide). A carousel draft is `ready` only with ≥2
  slides (new `draft_status(enough_media=…)`), else `needs_image`.
- **Composer:** carousel format on IG/FB + a **Slides** count (2–10) in the Create-with-AI tab, image
  generation forced on, an N× cost note; Compose carousel = the existing multi-image UI + a ≥2-item hint.
- **Config:** `social_carousel_max_slides` (10) / `_default_slides` (3) / `_slides_max_tokens` (900).

**No migration** for either — the `social_drafts.format` CHECK already allows `reel`/`story`/`carousel`,
`image_urls` is already an array, and the IG platform spec is per-platform (format rules live in code).

**Live-verification flags (deployed-only — sandbox egress-blocked from PostForMe + Gemini):**
- Placement keys/values (`platform_configurations.instagram.placement` = `reels`/`stories`; same for
  `facebook`) are confirmed from PostForMe's public docs (postforme.dev/resources/posting-reels-and-stories).
  The exact Stories caption/link-sticker + **Business-account** behavior is provider-enforced — verify on a
  real test Reel + Story on IG/FB.
- A live carousel fan-out (N slides generated + published as a carousel) needs a real Gemini key +
  PostForMe account — verify per-slide budget reservation + the timeline carousel post on the deployed path.

Tests: format-aware `validate_post` (reel/story/carousel) + `placement_config`/payload mapping +
`resolve_slide_count`/`sanitize_slide_descriptions` + `draft_status(enough_media)` — 92 social tests pass;
ruff clean; frontend `tsc -b` passes (eslint introduces zero new problems).

## Update (2026-09-17) — **Posting provider swapped: PostForMe replaces PostPeer — MERGED + ACTIVATED + LIVE** (ADR-0006)

The agency moved off PostPeer to **PostForMe** (api.postforme.dev). Built behind the existing
adapter seam (ADR-0001), so it's a contained change. **Merged** (PR #1198, squash `961d57c`),
**activated** on PLATFORM (`SOCIAL_POSTING_PROVIDER=postforme`), and the activation deploy is
**verified healthy** (deploy `df6323b0` = `961d57c` + the provider var reached SUCCESS + active;
boot logs clean: `job_worker.started` / `gsc_scheduler.started` / `event_loop_watchdog.started` /
Uvicorn up, no `gsc_scheduler.step_failed`). The Social module now posts via PostForMe in prod.
Authoritative facts: `docs/modules/social-media-vendor-confirm-postforme-v1_0.md`;
decision: `docs/adr/0006-social-posting-provider-postforme.md`.

**What shipped:**
- `services/social/postforme_adapter.py` — the 5 adapter methods vs PostForMe's `/v1` API
  (`Authorization: Bearer`, `x` not `twitter`); async posts handled by a bounded poll of
  `/social-post-results` (Decision 2=A). Pure helpers + the poll flow unit-tested
  (`tests/test_social_postforme.py`, mocked httpx).
- `services/social/credentials.py` + `social_client_credentials` table (migration
  `20260917120000`, **applied live**) — per-client PostForMe **project key** (secret,
  service-role only). `services.social.get_adapter(client_id)` is now provider-aware and
  loads that key. Isolation is **provider-enforced** (one Project per client; the key is the
  boundary — verified empirically: key A → 12 accounts, key B → 0).
- Routes: `GET/PUT/DELETE /clients/{id}/social/credentials` (PUT validates the key live before
  storing; never returns it). Frontend: the connect panel's setup step is now a **"Save API
  key"** form; setting it stamps `clients.social_profile_id='postforme'` so the publish gate
  is unchanged. errorGuidance for the new codes.
- Provider-aware cost (flat `social_postforme_cost_per_post_usd`; PostPeer X-credit surcharge
  gated to PostPeer). Config: `postforme_base_url` + the poll knobs. PostPeer kept dormant.

**Provisioning is MANUAL** (no PostForMe project/key API): per client, create the Project +
API key in the PostForMe dashboard, paste it into the client's Social setup. Quota pools at
the **Team** level (per-client isolation ≠ per-client quota). Project type = **Quickstart**.

**Activation (DONE):** `SOCIAL_POSTING_PROVIDER=postforme` is set on PLATFORM (code default
stays `postpeer`, inert without a key, so a fresh env still ships dark). No global key. **Now
per client:** create its PostForMe Project + API key in the dashboard and paste it into the
client's **Social setup → Save API key**; a client with no key returns `social_not_configured`
(safe/inert) until then.

**Still open (human, deployed-only — sandbox is egress-blocked from PostForMe):**
- **Per-client keys:** paste each Social client's PostForMe project key (the one recurring step).
- **Live verification** once a key is in place: one end-to-end test post (create → result poll →
  published URL) and a live account-connect via the auth-url flow.
- **Cleanup:** delete the dashboard **test project** ("Isolation Test Client") + the **3 test
  API keys** from the isolation investigation — they're live keys returning real tokens.

---

## Update (2026-09-16) — **P1 Competitor research BUILT + MERGED + LIVE** (PR #1177)

P1 (analyze-in-place competitor research, **Apify-only**; owner c1 — TwelveLabs dropped) is built,
merged to `main` (squash `3f07eda`), and **enabled in production**. This is the repurpose engine's
signal layer: scrape competitors' public posts → per-`(client, competitor, platform)` **Competitor
Signals** that ground the Creator's angle proposals.

**Provisioned + live on PLATFORM (2026-09-16):** `APIFY_API_TOKEN` **set** +
`SOCIAL_COMPETITOR_RESEARCH_ENABLED=true` **set** (on top of the already-set `SOCIAL_ENABLED=true`), so
`research_gate_open()` is satisfied. The merge deploy (`3f07eda`) booted clean — `job_worker.started` /
`gsc_scheduler.started` / `event_loop_watchdog.started` / Uvicorn up.

**What shipped (PR #1177):**
- Migration `20260916200000_social_competitor_research_job.sql` — widens the `async_jobs` CHECK (rebuilt
  from the **LIVE** constraint) to add `social_competitor_research`. **Applied live.** No new tables —
  reuses the already-migrated `social_competitor_handles` (bare-handle child of `client_competitors`) +
  `social_competitor_signals`.
- `services/social/apify.py` — sync httpx `run-sync-get-dataset-items` wrapper (mirrors `postpeer_adapter`)
  + per-platform input builders + **pure post parsers** for Instagram / Facebook / X / YouTube / Pinterest.
  Config-driven, **env-overridable actor ids** (`social_apify_actor_*`; `/`→`~` API-path mapping); LinkedIn
  deferred (blank slot). YouTube = titles/descriptions/tags/engagement/thumbnail-links only (no
  video-content analysis).
- `services/social/competitor_research.py` — the engine: deterministic `formats`/`cadence`/`top_performers`
  (links + numbers only, no media/identity) + a **caption-only** LLM rollup (`themes`/`hook_patterns`/
  `whats_working`; our own Anthropic key, **NOT** metered — only Apify is). One `social_competitor_research`
  job per client; **fail-CLOSED** `budget.reserve` before each Apify run (copies `autonomy_budget.reserve`);
  **NOT freeze-gated** (research runs under freeze, PRD §3); weekly interval-gated scheduler sweep
  (`enqueue_due_social_competitor_research`, mirrors `competitor_intel`). `job_worker` dispatch + a
  `gsc_scheduler` daily-block hook.
- Angle grounding: `creator.propose_angles` folds the client's latest usable signals in via
  `render_competitor_signals_block` (empty → prompt byte-identical to today).
- Routes on `routers/social.py` (competitors + handles CRUD, research trigger + poll, signals read);
  frontend **Competitors** tab in `SocialCompose.tsx` (add/remove handles per platform, "Research now",
  view signals) + `errorGuidance.ts` codes.
- Tests `tests/test_social_apify.py` + `tests/test_social_competitor_research.py` (85 social tests pass;
  a real bug was caught + fixed — `top_performers` dropped url-less rows *after* slicing top-N).

**Remaining confidence step (deployed-only — the sandbox is egress-blocked from Apify):** run a **live
research** from the dashboard (a client → Social Media → Competitors → add a handle → "Research now"),
verify the signals land + the parsers hold on real data, and **confirm/replace the default Pinterest
actor** (`epctex/pinterest-scraper`, env-overridable — the one default not confidently current). Owner
decision on billing/scope unchanged; nothing else pending.

**Config added (`config.py`):** `apify_api_token` / `apify_base_url` / `social_competitor_research_enabled`
(default False) / `_interval_days` (7) / `social_apify_actor_{instagram,facebook,twitter,youtube,pinterest}`
/ `social_apify_max_posts` (30) / `social_apify_run_cost_usd` (0.05) / `social_apify_timeout_secs` (300) /
`social_competitor_signal_model` (Haiku) / `_max_tokens` / `_caption_cap` / `social_competitor_top_performers`
(5) / `social_competitor_angle_signal_cap` (6).

---

## Update (2026-09-16) — Format-dropdown fix MERGED + the **client-isolation A-unit** (MERGED PR #1165)

Two things shipped this session on top of the 2026-09-08 state below.

**1. Format dropdown fix — MERGED (PR #1160).** The composer's Format dropdown offered
Reel/Story for platforms that don't support them (e.g. LinkedIn). `FORMATS_BY_PLATFORM` in
`SocialCompose.tsx` now scopes the offered formats per platform. Merged to `main`.

**2. Client isolation "make account connection per-client and safe" (the A-unit) — DRAFT PR #1165, CI GREEN, awaiting owner review/merge.**
This closes the real multi-client-safety gap: PostPeer has **one account-wide key with no
per-profile access control** (see the "not a security boundary" note in `CLAUDE.md`), so before
this the account picker listed **every** connected account regardless of client. What landed:
- **A1 isolation** — `list_accounts` fails CLOSED (unmapped client → `[]`, adapter never called);
  `publish._assert_account_allowed` enforces membership at the WRITE (`create_post` + fanout
  `publish_existing_draft`): profile MUST be set (409 `social_profile_not_set`) and the account
  must be in the client's PostPeer profile (403 `social_account_not_in_client_profile`). The
  picker's scoping is UX; this membership check is the actual boundary.
  - **Tolerant at compose, authoritative at publish**: `_assert_account_allowed(require_live=…)`.
    Compose/schedule pass `require_live=False` (a PostPeer blip can't block composing); the
    publish job re-checks `require_live=True` **before budget reserve / the platform call**, so a
    wrong or unconfirmable account never posts.
- **A2 connect flow** — `POST /clients/{id}/social/profile` (idempotent ensure) +
  `GET /clients/{id}/social/connect-url?platform=` (per-client OAuth URL scoped to the client's
  Social group); `SocialCompose` empty-state is a `ConnectAccountsPanel` (Set up Social group →
  per-platform Connect buttons). Replaces the "connect manually in PostPeer" v1 stopgap.
- **A3 LinkedIn** — migration `20260916150000_social_linkedin_spec.sql` seeds the `linkedin`
  `social_platform_specs` row (3,000 chars, 9 images, feed-only) so `validate_post` enforces it.
- **`clients.social_profile_id` is now settable + auto-provisioned at client creation**, but
  provisioning is **enqueued** (new `social_profile_provision` async job, migration
  `20260916190000`) so the client-create response never blocks on a synchronous PostPeer call.
  `ensure_profile_for_client` is concurrency/orphan-hardened (re-reads after create, never clobbers
  an existing mapping, raises `social_profile_failed` on a failed persist).
- Four new error codes registered in `errorGuidance.ts` (`social_profile_not_set`,
  `social_account_not_in_client_profile`, `social_profile_failed`, `social_connect_failed`).
- Migrations `20260916150000` + `20260916190000` **applied live**. All CI green on the head commit
  (`98f7079`): platform-api lint&typecheck ✅, platform-api tests ✅, nlp-api tests ✅, Netlify
  preview ✅. It's a **draft** — owner marks ready + merges.

**Behavior change to socialize:** fail-closed means an existing client whose accounts were
connected before profiles existed shows an **empty picker until its Social group is set** — the
correct trade-off vs the old cross-client leak. The connect panel is the path (Set up → Connect).

**Owner decisions made this session (the b/c items):**
- **b1 — IG scope: BOTH** (feed + Reels + Stories) in v1.
- **b2 — IG carousel: YES** in v1 (≤10 items, one aspect ratio throughout; each slide is another
  nano-banana Pro image ≈ $0.13, so a 5-slide carousel is ~5× the dominant cost line — plan for it).
- **b3 — Default per-client monthly ceiling: STILL OPEN** ("let's discuss more").
- **b4 — Autonomy rollout: case-by-case** (per-client decision, not a blanket tier).
- **b5 — PostPeer billing: no monthly fee → PAYG** (pay-as-you-go non-expiring credit packs).
- **c1 — P1 Competitor research: BUILD IT NEXT, Apify-ONLY. SKIP TwelveLabs** (we're not analyzing
  full videos, so no per-video analysis vendor). Leaves `TWELVELABS_API_KEY` unneeded for v1;
  `APIFY_API_TOKEN` was required + unset at the time. _(Since done: P1 built + live, `APIFY_API_TOKEN` set —
  see the P1 update at the top of this file.)_
- **c2 — P4 autonomy: DISCUSS** (not started).
- **c3 — Video Studio / P5: DISCUSS** (not started).

Everything below (2026-09-08) remains accurate; the format fix and the A-unit are additive.

---

## Current state (2026-09-08) — P0 publish path + the **full P2 Creator** are BUILT, MERGED & LIVE

The module is a **working end-to-end Social Media manager PLUS the repurpose-engine Creator** on `main`.
Build order diverged from the design phasing on purpose: **publish-path-first** (a thin, reliable
manual compose → publish/schedule spine, Facebook-first but platform-general), then media/video/
scheduling, then the R2 media store, then the frontend, then the **P2 Creator** (AI copy, AI images,
Angle fan-out). **The P2 Creator is COMPLETE and merged (PR #1036, squash `aaecd5f`, 2026-09-08).**
Still unbuilt toward the full vision: **P1 competitor research** (Apify + TwelveLabs — would also ground
angle proposals in competitor signals), **P4 autonomy**, **P5 video/YouTube**. The one open confidence
step is a **live test post** (also the live R2 proof).

**Merged to `main`:**
- **P0 foundations + publish path — PR #1027** (squash `b14f1b3`). Migrations applied live:
  `20260905120000` (8 tables: `social_accounts`, `social_competitor_handles`, `social_competitor_signals`,
  `social_drafts`, `social_posts`, `social_policy`, `social_platform_specs` [5 seeded], `social_usage` +
  the fail-closed `reserve_social_spend` RPC + `clients.social_profile_id`), `20260905130000`
  (`social_publish` async-job type), `20260905140000` (`social_drafts.media` jsonb). Code:
  `services/social/adapter.py` (swappable `SocialPostingAdapter` ABC, ADR-0001) + `postpeer_adapter.py`
  (sync httpx impl) + `budget.py` (fail-CLOSED meter — copies `autonomy_budget.reserve`) + `publish.py`
  (compose → approve → freeze-gated idempotent publish job, GBP-Posts template; media upload + presign) +
  `media_store.py` (R2 behind a `MediaStore` interface, ADR-0004, Supabase fallback); `models/social.py`;
  `routers/social.py` (all routes gated on `social_enabled`); `job_worker` dispatch + `freeze` gate +
  `gsc_scheduler` due-sweep wiring; `boto3` added (lazy, R2 only). 28 pure-helper unit tests.
- **Frontend compose screen + image/video upload — PR #1032** (squash `ded5d2d`).
  `frontend/src/pages/SocialCompose.tsx` (route `/clients/:id/social`, "Social Media" workspace card):
  account picker (live from PostPeer), copy with live per-platform char count, image + video upload
  (multipart `POST .../social/media` → R2), feed/reel/story, publish-now or schedule, advanced
  platform-specific JSON, and an auto-polling recent-posts list. Social error codes added to
  `errorGuidance.ts`. `tsc -b` + `vite build` green.
- **P2 Creator (AI copy + AI images + Angle fan-out) — PR #1036** (squash `aaecd5f`, MERGED 2026-09-08;
  migration `20260908130000_social_fanout_job.sql` applied live). The four sub-parts below shipped together
  in that PR, plus a hardening pass (freeze cleanup, budget refunds on failed images, no orphan drafts —
  see "Hardening" below).
- **AI copy drafting (P2 Creator, copy half).** `services/social/creator.py` (pure prompt
  builders + async `generate_copy`) + `POST /clients/{id}/social/draft-copy` + a **"Draft with AI"**
  panel in the composer. Given a target platform (the selected account) and a Source — a **topic**,
  a **URL** (via `syndication_rewrite.extract_source_content`), a **blog run**
  (`illustration._load_article`), or a **saved Local SEO page** (`local_seo_pages.content_html`) — plus
  optional angle/tone, it generates platform-native copy through `report_llm.generate_text`
  (`social_copy_model` = `claude-sonnet-5`), enforces the client's Voice & Audience Card (reuses
  `gbp_posts_service.render_voice_card_block` / `voice_forbidden_hits` + one corrective rewrite),
  clamps to the platform char limit, and returns copy + voice/spec advisories. **Stateless** — the
  panel prefills the copy box; the human edits → approves → publishes (the real draft/post is created
  at publish, unchanged). Not metered against the social budget (our own Anthropic key, like the
  blog/GBP writers). 12 pure-helper unit tests (`tests/test_social_creator.py`).
- **AI image generation (Pro-only).** `services/nano_banana.py::generate_image_pro` (Gemini 3
  Pro Image, `gemini-3-pro-image-preview`, passes `generationConfig.imageConfig.aspectRatio`) +
  `services/social/image.py` + `POST /clients/{id}/social/generate-image` + a **"Generate an image
  with AI"** panel in the composer's Media section. Per-platform aspect ratio via `resolve_aspect_ratio`
  (reel/story→9:16, Pinterest→2:3, IG→4:5, X/YouTube→16:9, else 1:1 — all Gemini-supported; the seeded
  specs' `1.91:1` is NOT, so the mapping is deliberate). Prompt built from the client's Social Policy
  `image_prompt_template` (editable) + brand context. **Freeze-gated** and **fail-closed budget-metered**
  (paid call: `budget.reserve` before the Gemini call, `social_image_cost_usd`≈$0.134 — the dominant
  cost line). Image stored to R2 via `media_store.media_key(ext,"generated")`. **Owner ruling: Pro-only**
  — the mixed 2.5-Flash-for-square path is deferred. Config: `nano_banana_pro_model` /
  `social_image_size` (`2K`) / `social_image_cost_usd`. 10 pure-helper unit tests
  (`tests/test_social_image.py`).
- **Angle fan-out + Draft persistence (the full Creator loop).** `services/social/creator.py::propose_angles`
  (`POST …/social/angles`) proposes 3–5 distinct angles from a Source (grounded in source + voice/ICP).
  `services/social/fanout.py` + `POST …/social/fan-out` fans ONE chosen angle across the selected platforms
  as a background **`social_fanout`** job (migration `20260908130000_social_fanout_job.sql`, applied live;
  freeze-gated + `job_worker` dispatch): it loads the source + voice card ONCE, then generates one **Draft
  per platform** (copy via the shared `creator.draft_platform_copy`, opt-in per-platform image via the Pro
  renderer, each image budget-reserved), persisted under a shared `angle_set_id` in `social_drafts` with
  status `ready`/`needs_image`/`generation_failed`, and emits a `social_fanout_ready` notification. Draft
  review: `GET …/social/drafts` (+`?angle_set_id`), `PATCH /social/drafts/{id}` (edit copy/media, recomputes
  needs_image↔ready), `DELETE` (archive), `POST /social/drafts/{id}/publish` (approve → the existing publish
  lifecycle: validate → create Post → freeze-gated publish job; marks the Draft published). Frontend: the
  social page is now **tabbed Compose / Create with AI / Drafts** (`SocialCompose.tsx`) — source picker →
  Suggest angles (or write your own) → platform multi-select + image toggle → fan out → poll → land on the
  Drafts tab to edit + publish each. `creator.load_source` was refactored to kwargs and the copy LLM +
  voice-enforcement extracted to `draft_platform_copy` so single-copy and fan-out share ONE path. Config:
  `social_angles_count` (4) / `_max_tokens`. 7 pure-helper tests (`tests/test_social_fanout.py`). **P2 Creator
  is COMPLETE.**
- **Hardening (folded into PR #1036 after an adversarial review).** All edge/robustness, no happy-path
  defects: (1) **freeze mid-flight no longer orphans drafts** — `social_fanout` is deliberately NOT in the
  worker `FREEZE_GATED_JOB_TYPES`; freeze is enforced INSIDE `run_fanout_job` (a client frozen between
  enqueue and execution gets its pending `generating` drafts marked `generation_failed`, no paid work; the
  enqueue route still `assert_not_frozen`s). (2) **Failed images refund the budget** — new `budget.release`
  (fail-safe) is called on any generation/store failure, and a media-store write error returns a clean
  `social_image_generation_failed` (502) not a bare 500. (3) `enqueue_fanout` archives its just-created
  drafts if the `async_jobs` insert fails. (4) Per-image redundant client/policy reads removed (loaded once,
  threaded in). (5) Frontend: a failed fan-out job is surfaced in the Create tab; the Drafts poll is bounded
  (10 min) so a stuck/crashed worker can't poll forever. 58 social tests green.

**Provisioned + live on PLATFORM:** `SOCIAL_ENABLED=true`; R2 (`R2_ACCOUNT_ID` / `_ACCESS_KEY_ID` /
`_SECRET_ACCESS_KEY` / `R2_BUCKET=smm-media` / `R2_PUBLIC_BASE_URL=https://smm-media.arrvmedia.com`,
custom domain **Active** in Cloudflare); `GEMINI_API_KEY` is set (was dormant).

**✅ `POSTPEER_API_KEY` is now set on PLATFORM (2026-09-08) — the module is fully wired end to end.**
Every live route (`GET .../social/accounts`, publish) calls PostPeer through the adapter, which reads
`settings.postpeer_api_key`; that key was the last blocker and is now provisioned (env var only, never
committed). Nothing is left to provision. The remaining confidence step is a **live test post** through
the compose screen on a low-stakes account (the connected accounts are real clients') — it exercises the
whole chain (PostPeer account listing → compose → R2 media upload → publish) and doubles as the live R2
write/read proof.

- Original design docs merged earlier (was PR #952). Six design docs + ADR-0001..0003 are on `main`;
  **ADR-0004 (Cloudflare R2 media store)** was added with #1027. Cost model v1.1 + vendor-confirm v1.1.
- **Adversarial review (design phase): all findings resolved or tracked.** 1 Blocking (image aspect
  ratio → nano-banana Pro, still relevant to the unbuilt Creator), 1 Major (budget fail-open →
  fail-closed, **applied** in `budget.py`), 4 Minor, 4 Advisory.

## Live R2 write/read check — PENDING (owner to run)

The sandbox is egress-blocked from R2 / the custom domain (same org policy that blocked
api.postpeer.dev), so the isolated R2 round-trip couldn't be run from here. A standalone
`r2_check.py` (write → fetch over the public domain → delete; creds via env, none hardcoded) was sent
to the owner. Alternatively, the **first real media upload through the compose screen** now exercises R2
for real (`SOCIAL_ENABLED=true` + R2 vars live), so a test post doubles as the R2 proof.

## Live smoke test — PASS (2026-09-05)

The connect-and-post smoke test's read-only half ran against the real API with the
agency's key (from the owner's own machine — the Claude Code sandbox is egress-blocked
from api.postpeer.dev). Result:

- **`GET /health/auth` → 200** — key valid, PostPeer reachable. Core dependency proven.
- **`GET /connect/integrations` → 4 accounts** (3 LinkedIn + 1 Facebook), **all healthy**
  (no `tokenStatus.reconnectRequired`). Integration listing + the health-flag read work.
- **`GET /profiles` → 0** — expected, NOT a bug: those accounts sit in PostPeer's implicit
  "Default" group, which the API doesn't enumerate. Our design creates a named profile per
  client via `POST /profiles`, so there's nothing to list until we do.

**Not yet run:** the `--post` publish half. The 4 connected accounts are REAL client
LinkedIn/Facebook accounts, so a test post would publish to a client's audience — defer the
publish proof to an **agency-owned throwaway account** just before P3 (publish lifecycle).
Auth + connectivity + listing + token health are the parts the gate needed; those are green,
so P0 (data model / budget meter / scheduler / freeze) is clear to proceed.

## The P0 vendor gate — CLOSED (2026-09-02)

(Full readout: `../social-media-vendor-confirm-postpeer-v1_0.md` v1.1 — §6 has the API facts the
adapter needs.) The owner supplied PostPeer's live docs and ruled on the rest:
1. **X link-post billing** — ✅ **pass-through**: 5 credits for a plain X post, **50 credits when the body
   contains `http(s)://`**, 1 credit on every other platform; analytics reads 1 credit/call. Cost model
   v1.1 raised the Base X line $60 → ~$120/mo.
2. **IG carousel** — ✅ **live** (≤10 items, one aspect ratio throughout). The v1 single-image restriction
   was a vendor limit; carousel scope is now an **owner decision** (below).
3. **SLA / status page / webhook guarantee** — ✅ **none** (founder). Accepted: status is reconciled by our
   own polling sync job, and the swappable adapter is the mitigation.
4. **Legal entity + support channel** — ✅ **waived by the owner** (internal pilot; founder reachable on Reddit).

The **P0 connect-and-post smoke test** is still the go/no-go on real reliability. Also confirmed:
managed OAuth under PostPeer's own reviewed apps; Instagram uses Instagram Login (no linked Facebook
Page needed); IG feed/Reels need Business **or** Creator, **Stories need Business**; IG has no text-only
posts; feed image aspect ratio 4:5–1.91:1.

## Provisioning status (PLATFORM Railway service, verified 2026-09-08)

- **`POSTPEER_API_KEY`** — ✅ **set** (2026-09-08). `SOCIAL_POSTING_PROVIDER`/`POSTPEER_BASE_URL` have
  working defaults.
- **`SOCIAL_ENABLED=true`** — ✅ set (routes answer).
- **R2** (`R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET=smm-media` /
  `R2_PUBLIC_BASE_URL=https://smm-media.arrvmedia.com`) — ✅ all set; bucket + custom domain live in
  Cloudflare. Live write/read proof still pending (see above).
- **`GEMINI_API_KEY`** — ✅ set (needed for the unbuilt nano-banana Pro image renderer / AI images).
- **`APIFY_API_TOKEN`** — ✅ **set (2026-09-16)** — powers **P1 competitor research** (BUILT + LIVE, PR #1177).
- **`SOCIAL_COMPETITOR_RESEARCH_ENABLED`** — ✅ **set `true` (2026-09-16)** — the P1 feature gate (with
  `SOCIAL_ENABLED` + the token, `research_gate_open()` is satisfied).
- **`TWELVELABS_API_KEY`** — ⛔ **NOT NEEDED (owner decision c1, 2026-09-16): SKIP TwelveLabs.** P1 is
  Apify-ONLY; we're not analyzing full videos, so there's no per-video-analysis vendor in v1. Don't
  provision it and don't build the TwelveLabs path.
- **cobalt** — self-hosted; **P5 only**, not needed for v1.
- Config settings that landed with #1027: `social_posting_provider`, `postpeer_api_key`,
  `postpeer_base_url`, `social_enabled`, `social_monthly_ceiling_default_usd` (75.0), `social_credit_usd`
  (0.0085), `social_max_upload_mb` (200.0), `r2_*`. Added with the P2 Creator (#1036): `social_copy_*`,
  `nano_banana_pro_model` (`gemini-3-pro-image-preview`), `social_image_size` (`2K`),
  `social_image_cost_usd` (0.134), `social_angles_count` (4) / `social_angles_max_tokens` — all have
  working defaults (no new env needed; copy/angles reuse `ANTHROPIC_API_KEY`, images reuse the already-set
  `GEMINI_API_KEY`). Added + live with P1 (#1177): `apify_api_token`, `social_competitor_research_enabled`,
  `social_competitor_research_interval_days`, `social_apify_actor_*`, `social_apify_max_posts`,
  `social_apify_run_cost_usd`, `social_apify_timeout_secs`, `social_competitor_signal_*`,
  `social_competitor_top_performers`, `social_competitor_angle_signal_cap` (`twelvelabs_api_key` NOT needed — c1).

## Open decisions for the owner

- ~~**Mixed image path**~~ — **✅ BUILT + MERGED (PR #1216, queue #5).** All social images route to
  Nano Banana 2 (`gemini-3.1-flash-image`) at 2K, ~25% under Pro; behind `social_image_use_flash`
  (default ON, Pro the fallback). Supersedes the earlier "Pro-only for now" ruling.
- ~~**v1 Instagram scope**~~ — **DECIDED (b1): BOTH** — feed + Reels + Stories. (Not built yet — the
  composer's format set + the seeded IG spec need extending to Reels/Stories; Stories is
  Business-account-only, no caption/link stickers.)
- ~~**IG carousel Draft type in v1?**~~ — **DECIDED (b2): YES.** Not built yet — needs a carousel Draft
  type (≤10 items, one aspect ratio). Cost: each slide is another nano-banana Pro image (~$0.13).
- ~~**PostPeer billing shape**~~ — **DECIDED (b5): PAYG** (non-expiring credit packs, no monthly plan).
- ~~**Autonomy rollout**~~ — **DECIDED (b4): case-by-case** per client (not a blanket tier). The build
  (P4) is still a separate "discuss first" item (c2).
- **STILL OPEN — Default per-client monthly cost ceiling** (b3) in the Social Policy (cost model says
  Base ≈ $45/client/mo). Owner: "let's discuss more."
- **STILL OPEN — P4 autonomy build** (c2) and **Video Studio / P5** (c3): both "let's discuss" before building.

## Next actions, in order

1. **Live test post** (STILL PENDING — highest priority; a confidence step, not a build step). Through the
   compose screen on a **low-stakes/agency-owned account**, prove the whole chain: PostPeer account listing
   → compose → R2 media upload → publish. Doubles as the live R2 write/read proof (so `r2_check.py` in
   isolation is optional). Now that the P2 Creator is merged + deployed, this can also exercise **Draft with
   AI**, **Generate an image with AI**, and **fan-out → Drafts → publish**. The 4 connected accounts are REAL
   client LinkedIn/Facebook accounts — use a throwaway/agency account, not a client's audience.
1b. **Live P1 research run** (PENDING — the P1 confidence step). On a client with competitors, add per-platform
   handles in the **Competitors** tab → "Research now" → verify signals land + the parsers hold on real Apify
   data, and confirm/replace the default Pinterest actor (`epctex/pinterest-scraper`, env-overridable). The
   sandbox is egress-blocked from Apify, so this is deployed-only.
2. **Everything through P2 + P1 is done + merged + live** — P0 foundations, publish path, R2, frontend compose,
   `POSTPEER_API_KEY`/`SOCIAL_ENABLED`, the **full P2 Creator (PR #1036)** with its hardening pass, and **P1
   Competitor research (PR #1177, `APIFY_API_TOKEN` + `SOCIAL_COMPETITOR_RESEARCH_ENABLED` live)**.
3. **Owner scope decisions still open** (see "Open decisions" below) — IG Reels/Stories scope, IG carousel
   Draft type, default per-client monthly ceiling, autonomy rollout. (The **mixed image path** is DECIDED:
   Pro-only for now.)
4. **Remaining build** — the owner-set order is now the **"Next priority" block at the top of
   this file** (IG Reels/Stories → IG carousel → YouTube poster → big-video presign → mixed
   image path). The list below is the fuller context for each; the top block is authoritative
   on sequence.
   - **P1 Competitor research — ✅ BUILT + MERGED + LIVE (PR #1177, squash `3f07eda`; owner c1, Apify-ONLY,
     TwelveLabs dropped).** Analyze-in-place per ADR-0002 (public content, never re-hosted media). Extends
     `client_competitors` via the child `social_competitor_handles` table; output → `social_competitor_signals`
     (deterministic formats/cadence/top-performers + a caption-only LLM rollup). Grounds Angle proposals via
     `creator.render_competitor_signals_block`. `APIFY_API_TOKEN` + `SOCIAL_COMPETITOR_RESEARCH_ENABLED` are
     **set on PLATFORM**. See the 2026-09-16 P1 update at the top of this file. Remaining: the live research run
     (1b above) + Pinterest-actor confirmation.
   - **IG scope-out (b1) + IG carousel (b2)** — extend the composer format set + the seeded IG spec to
     Reels/Stories, and add a carousel Draft type (≤10 images, one aspect ratio). Small-to-medium build;
     do alongside or after P1.
   - **YouTube poster** — waiting on PostPeer's `/docs/platforms/youtube` (title/description/tags/
     thumbnail/Shorts fields) before mapping. Uploads existing videos, not generation.
   - **Big-video direct-to-R2 (presign)** — the `POST .../social/media/presign` endpoint exists; the UI
     uses server upload today. Wiring the browser PUT needs an **R2 CORS policy** allowing PUT from the
     Netlify origin to the R2 S3 endpoint.
   - **P4 autonomy/agents** (a domain executor reusing `autonomy_policy`/`autonomy_budget`/tiers/freeze/
     DORA veto — the orchestration loop itself is new code), **P5 video production** (Reels/Shorts, cobalt
     self-host) — later phases from the PRD.
   - **Mixed image path** — ✅ BUILT + MERGED (PR #1216, squash `cf9ffa0`). All social images → Nano
     Banana 2 (`gemini-3.1-flash-image`) at 2K (~25% under Pro), behind `social_image_use_flash`
     (default ON). See the 2026-09-18 update at the top of this file.

## Gotchas discovered during design (don't re-learn these)

- **Budget meter:** `keyword_research.reserve_budget` is **fail-OPEN** on RPC error; the fail-closed
  one is `autonomy_budget.reserve`. Copy the latter for spend.
- **`nano_banana.py` (2.5 Flash) sends no `imageConfig`/`aspectRatio`** — 1:1 output only. A Pro-based
  renderer that passes `aspectRatio` is required, or the Platform-Spec validator flags every
  non-square Draft un-approvable.
- **IG carousels ARE live in PostPeer** (v1.0 of the vendor doc said otherwise — it read a stale blog
  post). Don't add a carousel Draft type until the owner scopes it, but don't design it out either.
- **PostPeer's X link rule is mechanical** — any `http://`/`https://` in the body = 50 credits. The
  "avoid links on X" toggle and the approval-time cost warning key on exactly that.
- **Don't use PostPeer's `scheduledFor`** — publish with `publishNow` from our own freeze-gated job at
  slot time so the inline health check + `source_changed` guard actually run.
- **PostPeer OAuth tokens are held by PostPeer, not us** — don't build a token store.
- **`client_competitors` has partial unique indexes** (`WHERE domain/place_id IS NOT NULL`) — social
  handle-only rows escape dedup; use a child `social_competitor_handles` table.
- **postpeer.dev is egress-blocked in the Claude Code sandbox** — direct WebFetch fails; use search or
  ask the owner to fetch. (This is why the four vendor questions couldn't be closed automatically.)
- **Cost:** the X line is ~$120/mo at realistic volume (~10% X-link share at the confirmed 50-credit
  pass-through, ~$0.30–0.43/link post) — not the ~$600 an early draft implied, and double v1.0's $60
  (which assumed PostPeer absorbed the fee). The **nano-banana Pro image (~$0.11/post)** is still the
  dominant cost line.
- **R2 media store (built #1027, ADR-0004):** `media_store.py` switches to R2 only when **all five**
  `r2_*` settings are present (`r2_configured()`); any missing one silently falls back to the Supabase
  `wordpress_images` bucket. `R2_PUBLIC_BASE_URL` **must include the scheme** (`https://…`) — `public_url`
  is `f"{base}/{key}"`, so a scheme-less base yields a URL PostPeer can't fetch. The presigned PUT signs
  against the R2 **S3 endpoint** (`{account}.r2.cloudflarestorage.com`), not the custom domain, so a
  browser direct-upload needs an **R2 CORS policy** on the bucket — that's why the compose UI uses the
  server-upload endpoint for now.
- **The 2026-09-05 smoke test ran from the owner's own machine** — a green smoke test did **not** mean
  the deployed service could reach PostPeer, and indeed `POSTPEER_API_KEY` was missing from PLATFORM
  until 2026-09-08. Lesson: verify env presence with `list-variables`, never assume from a smoke test.
  (It is now set — see the state section.)
- **`SocialCompose` upload path:** images go through the multipart `POST .../social/media` (server-side,
  image-decode-verified via PIL); video too (up to the 200 MB `social_max_upload_mb` cap). Client-side
  spec hints in the page are **advisory** — the seeded `social_platform_specs` (backend) are the source
  of truth and 422 on any real violation; LinkedIn/TikTok/Threads have no seeded backend spec, so their
  UI hints are cosmetic.
- **Sandbox egress blocks R2 + api.postpeer.dev** (CONNECT 403 through the agent proxy) — the live R2
  round-trip and any live PostPeer call must be run from the owner's machine or the deployed service,
  not from a Claude Code session.

## References

Root `/CLAUDE.md` (suite authority) · this folder's `CLAUDE.md` (module primer) · the six design docs
listed above · PR #952.
