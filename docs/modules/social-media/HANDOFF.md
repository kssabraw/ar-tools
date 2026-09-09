# Social Media Module — Handoff

> Module-scoped handoff for the **Social Media Manager + Content Creator** module.
> Not the root `/HANDOFF.md` (the suite-wide one). Read `CLAUDE.md` (this folder) for the
> build primer; this file is **current state + what to do next**.

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
- **`APIFY_API_TOKEN`** — ❌ not set — needed for **P1 competitor research** (unbuilt).
- **`TWELVELABS_API_KEY`** — ❌ not set — needed for **P1 competitor video analysis** (unbuilt).
- **cobalt** — self-hosted; **P5 only**, not needed for v1.
- Config settings that landed with #1027: `social_posting_provider`, `postpeer_api_key`,
  `postpeer_base_url`, `social_enabled`, `social_monthly_ceiling_default_usd` (75.0), `social_credit_usd`
  (0.0085), `social_max_upload_mb` (200.0), `r2_*`. Added with the P2 Creator (#1036): `social_copy_*`,
  `nano_banana_pro_model` (`gemini-3-pro-image-preview`), `social_image_size` (`2K`),
  `social_image_cost_usd` (0.134), `social_angles_count` (4) / `social_angles_max_tokens` — all have
  working defaults (no new env needed; copy/angles reuse `ANTHROPIC_API_KEY`, images reuse the already-set
  `GEMINI_API_KEY`). Still to add when P1 lands: `apify_api_token`, `twelvelabs_api_key`.

## Open decisions for the owner (not yet made)

- ~~**Mixed image path**~~ — **DECIDED (owner): Pro-only for now.** The 2.5-Flash-for-square /
  Pro-for-aspect-ratio cost-saver (halves the dominant image cost) is a future option, not built.
- **v1 Instagram scope** — feed-only, or include single-media Reels/Stories? (Stories: Business account
  only, no caption, no link stickers — a weak fit for repurposed content.)
- **IG carousel Draft type in v1?** — PostPeer supports it (≤10 items). Each slide is another
  nano-banana Pro image (~$0.13), so a 5-slide carousel is ~5× the dominant cost line per post.
- **Default per-client monthly cost ceiling** in the Social Policy (the cost model says Base ≈ $45/client/mo).
- **Autonomy rollout** — which clients (if any) reach the top tier for auto-publish, and when.

## Next actions, in order

1. **Live test post** (STILL PENDING — highest priority; a confidence step, not a build step). Through the
   compose screen on a **low-stakes/agency-owned account**, prove the whole chain: PostPeer account listing
   → compose → R2 media upload → publish. Doubles as the live R2 write/read proof (so `r2_check.py` in
   isolation is optional). Now that the P2 Creator is merged + deployed, this can also exercise **Draft with
   AI**, **Generate an image with AI**, and **fan-out → Drafts → publish**. The 4 connected accounts are REAL
   client LinkedIn/Facebook accounts — use a throwaway/agency account, not a client's audience.
2. **Everything through P2 is done + merged + live** — P0 foundations, publish path, R2, frontend compose,
   `POSTPEER_API_KEY`/`SOCIAL_ENABLED`, and the **full P2 Creator (PR #1036)** with its hardening pass.
3. **Owner scope decisions still open** (see "Open decisions" below) — IG Reels/Stories scope, IG carousel
   Draft type, default per-client monthly ceiling, autonomy rollout. (The **mixed image path** is DECIDED:
   Pro-only for now.)
4. **Remaining build, roughly in order** (the repurpose-engine vision beyond P2):
   - **P1 Competitor research** (Apify Signals + TwelveLabs analyze-in-place) — the next major build.
     Analyze-in-place per ADR-0002 (public content, never re-hosted media). Extend `client_competitors`
     via the child `social_competitor_handles` table (already migrated); output → `social_competitor_signals`.
     **It also grounds Angle proposals in competitor signals** (the `propose_angles` prompt already leaves
     room for this — the glossary says angles are grounded in "relevant Competitor Signals"). **Needs
     `APIFY_API_TOKEN` + `TWELVELABS_API_KEY` provisioned on PLATFORM (both currently unset).**
   - **YouTube poster** — waiting on PostPeer's `/docs/platforms/youtube` (title/description/tags/
     thumbnail/Shorts fields) before mapping. Uploads existing videos, not generation.
   - **Big-video direct-to-R2 (presign)** — the `POST .../social/media/presign` endpoint exists; the UI
     uses server upload today. Wiring the browser PUT needs an **R2 CORS policy** allowing PUT from the
     Netlify origin to the R2 S3 endpoint.
   - **P4 autonomy/agents** (a domain executor reusing `autonomy_policy`/`autonomy_budget`/tiers/freeze/
     DORA veto — the orchestration loop itself is new code), **P5 video production** (Reels/Shorts, cobalt
     self-host) — later phases from the PRD.
   - **Mixed image path** (2.5-Flash-for-square / Pro-for-aspect-ratio, halves the dominant image cost) — a
     deferred cost optimization, owner-decided as "later."

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
