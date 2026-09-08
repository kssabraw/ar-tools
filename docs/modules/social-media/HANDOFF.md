# Social Media Module — Handoff

> Module-scoped handoff for the **Social Media Manager + Content Creator** module.
> Not the root `/HANDOFF.md` (the suite-wide one). Read `CLAUDE.md` (this folder) for the
> build primer; this file is **current state + what to do next**.

## Current state (2026-09-08) — P0 + backend publish path + frontend compose are BUILT, MERGED & (nearly) LIVE

The module went from design-complete to a **working, end-to-end Social Media manager** on `main`.
Build order diverged from the design phasing on purpose: **publish-path-first** (a thin, reliable
manual compose → publish/schedule spine, Facebook-first but platform-general), then media/video/
scheduling, then the R2 media store, then the frontend. **Competitor research (P1) and the AI Creator
generation engine (P2) are NOT built yet** — this is a manual composer today, not the repurpose engine.

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

**Provisioned + live on PLATFORM:** `SOCIAL_ENABLED=true`; R2 (`R2_ACCOUNT_ID` / `_ACCESS_KEY_ID` /
`_SECRET_ACCESS_KEY` / `R2_BUCKET=smm-media` / `R2_PUBLIC_BASE_URL=https://smm-media.arrvmedia.com`,
custom domain **Active** in Cloudflare); `GEMINI_API_KEY` is set (was dormant).

**⚠️ THE ONE REMAINING BLOCKER — `POSTPEER_API_KEY` is NOT set on PLATFORM (verified 2026-09-08).**
Every live route (`GET .../social/accounts`, publish) calls PostPeer through the adapter, which reads
`settings.postpeer_api_key`. Until the agency's existing key is copied onto PLATFORM as
`POSTPEER_API_KEY`, the compose screen loads but shows no accounts and nothing can publish. This is the
last step to a functioning module. (Env var only — never commit the key.)

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

- **`POSTPEER_API_KEY`** — ❌ **NOT set** — the last blocker (see the state section). Copy the agency's
  existing key onto PLATFORM. Env var only; never commit it. `SOCIAL_POSTING_PROVIDER`/`POSTPEER_BASE_URL`
  have working defaults.
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
  (0.0085), `social_max_upload_mb` (200.0), `r2_*`. Still to add when P1/P2 land: `apify_api_token`,
  `twelvelabs_api_key`, `nano_banana_pro_model`.

## Open decisions for the owner (not yet made)

- **Mixed image path** — build the 2.5-Flash-for-square / Pro-for-aspect-ratio renderer in v1 (halves
  the dominant image cost) or ship Pro-only first?
- **v1 Instagram scope** — feed-only, or include single-media Reels/Stories? (Stories: Business account
  only, no caption, no link stickers — a weak fit for repurposed content.)
- **IG carousel Draft type in v1?** — PostPeer supports it (≤10 items). Each slide is another
  nano-banana Pro image (~$0.13), so a 5-slide carousel is ~5× the dominant cost line per post.
- **Default per-client monthly cost ceiling** in the Social Policy (the cost model says Base ≈ $45/client/mo).
- **Autonomy rollout** — which clients (if any) reach the top tier for auto-publish, and when.

## Next actions, in order

1. **Set `POSTPEER_API_KEY` on PLATFORM** — the one step between here and a working module. Then either
   run `r2_check.py` or just do a **test post** through the compose screen (proves the whole chain +
   R2 in one go — use an agency-owned/low-stakes account, since the connected accounts are real clients').
2. ~~Answer the four PostPeer questions~~ / ~~P0 foundations~~ / ~~publish path~~ / ~~R2~~ /
   ~~frontend compose~~ — **all done** (see the state section).
3. **Owner scope decisions still open** (unchanged from below) — mixed image path, IG Reels/Stories,
   IG carousel Draft type, default per-client monthly ceiling, autonomy rollout.
4. **Remaining build, roughly in order:**
   - **AI copy drafting** — buildable now (Anthropic key exists); the smallest next win (draft the post
     copy from a source/angle). AI **images** additionally need the nano-banana Pro renderer
     (`GEMINI_API_KEY` is set; still need the Gemini 3 Pro Image model id + a renderer that passes
     `aspectRatio` — `nano_banana.py` is 1:1-only).
   - **YouTube poster** — waiting on PostPeer's `/docs/platforms/youtube` (title/description/tags/
     thumbnail/Shorts fields) before mapping.
   - **Big-video direct-to-R2 (presign)** — the `POST .../social/media/presign` endpoint exists; the UI
     uses server upload today. Wiring the browser PUT needs an **R2 CORS policy** allowing PUT from the
     Netlify origin to the R2 S3 endpoint.
   - **P1 competitor research** (Apify + TwelveLabs), **P2 AI Creator** (Source → Angle → per-platform
     Draft fan-out + nano-banana Pro), **P4 autonomy/agents**, **P5 video** — the repurpose-engine
     vision from the PRD, none built yet.

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
- **`POSTPEER_API_KEY` was never on PLATFORM** — the 2026-09-05 smoke test ran from the owner's own
  machine, so a green smoke test did **not** mean the deployed service could reach PostPeer. Verify with
  `list-variables`, don't assume. It's still unset as of 2026-09-08 (the module's last blocker).
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
