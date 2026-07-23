# GBP Posts Module — PRD v1.0

**Status:** Approved for build (owner, 2026-07-20). The first build ships **Phases 0–2** (connection activation + manual compose/publish/history + AI drafting/scheduling); Phase 3 (insights + suite integration) is a follow-up. Authoritative for the GBP Posts module.

**Build status (2026-07-23): backend built + unit-tested; frontend pending.** Landed: migration `20260723090000_gbp_posts.sql` (`gbp_posts` / `gbp_post_schedules` / `gbp_post_insights`, async_jobs CHECK widened — applied live); config gates `gbp_api_enabled` + `gbp_posts_enabled` (both default off, so the whole surface no-ops until access lands); the v4 REST wrapper `services/gbp_posts_api.py`; `services/gbp_posts_service.py` (CRUD + soft-delete/trash, publish/generate/sync async jobs, AI drafting, self-clocked schedule tick); `models/gbp_posts.py`; `routers/gbp_posts.py`; worker + freeze (`gbp_post_publish` gated) + scheduler wiring; `tests/test_gbp_posts.py` (28 pure-helper tests green). **Frontend (built 2026-07-23):** `frontend/src/pages/GbpPosts.tsx` + a "GBP Posts" workspace ActionCard (route `clients/:id/gbp-posts`). Four tabs — **Compose** (location picker, Updates/Offers/Events/Products type switch with per-type fields — offer coupon/terms/redeem/window, event title + start/end date-time; summary + 1,500-char counter; AI-draft box; CTA picker; **image upload + reuse-existing picker** via `ImageField`; and Save draft / Publish now / Schedule-at actions), **Posts** (status chips, "View on Google" `search_url` link, publish/unschedule/remove-from-Google/trash, Sync-from-Google), **Schedule** (recurring cadence form with auto-publish opt-in + warning), and **Trash** (restore / delete-permanently / empty-trash with the skipped-live note). Gracefully renders an enablement notice when the module is gated off (503). Typechecks + production-builds clean.

**Remaining:** the live smoke-test once the verify script is green and the service account is a Manager on a pilot listing; Phase 3 (insights + Client Report / Action Plan / SerMaStr wiring).

**Scheduling (built 2026-07-23):** two independent scheduling paths. (1) **One-off scheduled publish** — compose a specific post and set a future `scheduled_at` (`POST …/gbp/posts/{id}/schedule` / `…/unschedule`); the post stays `status='scheduled'` and a **per-tick** due sweep (`enqueue_due_gbp_scheduled_posts`, evaluated every scheduler cycle so it fires near the chosen time — a future-dated async job can't defer since the worker claims the oldest `scheduled_at` with no `<=now` gate) publishes it when due, honouring the Freeze Protocol (frozen → held, fires once lifted) and an idempotency guard (no double-enqueue). (2) **Recurring drafts** — the `gbp_post_schedules` cadence (weekly/biweekly/monthly), self-clocked on `next_run_at`, moved to the per-cycle scheduler section so it fires near its `hour_utc`; auto-publish is opt-in per schedule. Both no-op until the module is enabled.
**Owner ask (2026-07-20):** "I have access to the Google Business Profile API. I want to add the ability to post GBP posts via this API."
**Access state:** GCP quota confirmed at **300 QPM** in the console (2026-07-20) — the project is approved. The §3 verify script still gates Phase 0 (proves API enablement incl. the v4 API specifically, SA-as-Manager grants, and the posts surface end-to-end).

**Locked decisions (owner, 2026-07-20):**
1. **Build scope:** Phases 1+2 together in the first build; Phase 3 later.
2. **Auto-publish:** opt-in per schedule; default is draft-for-approval (§5 stands as written).
3. **Images:** manual upload per post **plus** a picker over the client's existing suite-generated images (public-bucket featured images) — §8.
4. **Content tie-in:** **manual trigger only** — a "Draft a GBP post about this" action on published content (completed runs / Local SEO pages) that opens the composer with an AI draft seeded from that page. **No automatic** draft-on-publish producer in v1.
**Depends on:** the existing (dormant) GBP API connection layer — `services/gbp_performance_service.py`, `gbp_locations` (migration `20260707080000_gbp_metrics.sql`), the agency service account in `GOOGLE_SERVICE_ACCOUNT_KEY`.
**Sibling docs:** `docs/modules/client-reporting-prd-v1_0.md` (Phase 2 — GBP Performance metrics, same connection), `docs/sops/` GBP Authority SOPs, `docs/modules/maps-geogrid-strategy-prd-v1_0.md`.

---

## 1. What this is

A per-client tool that composes and publishes **Google Business Profile posts** ("Updates" / What's New, Events, Offers) directly to the client's GBP listing through Google's API — manually authored or AI-drafted from the client's stored context (brand voice, ICP, services, reviews, recent content, target keywords), published immediately or on a recurring schedule, with full post history, live-state reconciliation (LIVE / REJECTED), and failure alerting through the suite's shared notifications service.

This is the suite's first **write** integration with Google Business Profile. Everything GBP so far is read-only capture via third parties (Outscraper/DataForSEO profile + reviews on `clients.gbp`); the dormant GBP metrics layer is read-only too. Posts change the risk profile: the app acts *as the agency* on the client's public listing, so publishing is deliberate (see §5 approval model) and hard-gated by the Freeze Protocol.

### Why (product rationale)

- **GBP Authority SOP work is manual today.** Regular posting is a standing GBP Authority task (Recipe Engine category `gbp_authority`; the "GBP Blast" line item in the Baseline Stack) currently executed by hand in the GBP dashboard or via third-party tools.
- **Local-pack signals.** Posting cadence/recency is a GBP activity signal; the Maps geo-grid tracker and Action Plan already *diagnose* weak local-pack coverage — this module is one of the levers that *acts* on it (e.g. a `maps_weak_area` or `maps_decline` action can point at "publish a post targeting X").
- **The content already exists.** The suite generates blog articles and Local SEO pages per client; a post announcing/linking each new piece is nearly free and drives GBP → site engagement (UTM-tagged CTA links make it measurable in GA4 later).

### Non-goals (v1)

- Review replies, Q&A, photo-library management, service/attribute editing (all separate GBP surfaces; some are future modules).
- Multi-network social posting (Facebook/Instagram etc.) — this is GBP only.
- Posting for **chains** (~10+ locations under one brand) — Google's Posts API is not available to chains; out of scope entirely.
- Client-facing self-serve — internal team use only, like the rest of the suite.

---

## 2. The Google API surface (facts the build must respect)

> Verified 2026-07: Posts still live **only on the legacy v4 API** and it remains active with no announced sunset. The v1 split APIs (Account Management / Business Information / Performance) never got a posts resource. Re-check Google's deprecation schedule (`developers.google.com/my-business/content/sunset-dates`) at build time.

- **Endpoint family:** `https://mybusiness.googleapis.com/v4/accounts/{accountId}/locations/{locationId}/localPosts` — methods `create`, `list`, `get`, `patch`, `delete`, plus `localPosts:reportInsights` for per-post metrics. This is the **Google My Business API (v4)** — a *separate enableable API* in the GCP console from the v1 APIs, and **not in Google's discovery service** — call it with plain REST (httpx + a service-account token), not `googleapiclient.discovery.build`.
- **Auth:** OAuth2 with scope `https://www.googleapis.com/auth/business.manage` (there is no narrower posts scope). The agency **service account** works exactly like the metrics layer assumes: the client (or agency owner account) adds the SA's `client_email` as a **Manager** on the Business Profile; the app then authenticates as the SA. Same onboarding step as GSC ("add this email"), same key (`GOOGLE_SERVICE_ACCOUNT_KEY`), wider scope.
- **Access gate:** Business Profile APIs default to **0 QPM quota** on any GCP project until Google approves an access request for that project; approved projects get ~300 QPM. Approval is per-project and covers the API family. A 429/`RESOURCE_EXHAUSTED` on the very first call means *not approved*, not "slow down". Quota state is per-API — verify the **v4 Google My Business API specifically** has quota, not just the v1 APIs (community reports exist of projects approved with one API's quota still 0).
- **Resource path quirk:** v4 keys on `accounts/{a}/locations/{l}` — the stored `gbp_locations.location_id` (`locations/{id}`) must be combined with its `account_id` (`accounts/{id}`, already a column) to form the v4 parent. Both are captured by the existing `resolve_locations()` flow.
- **Post anatomy** (`LocalPost`):
  - `languageCode`, `summary` (body text, **≤ 1,500 chars**), `topicType`: `STANDARD` | `EVENT` | `OFFER` | `ALERT` (ALERT is Google-initiated event types only — not offered in our UI).
  - **Post types offered (built 2026-07-23):** the composer offers four — **Updates** (`standard` → `STANDARD`), **Offers** (`offer` → `OFFER`), **Events** (`event` → `EVENT`), and **Products** (`product`). ⚠️ **Google's Posts API has no PRODUCT topicType and no public product-post API at all** — true Product posts live in the GBP Product Editor, which has no write API (verified 2026-07; Google support + integrator consensus). So a **Product** post here is a product-framed **Update**: `product` → `STANDARD` at publish (`gbp_posts_api._TOPIC_TO_API`), with product-spotlight AI copy (no invented price/specs), an image, and a Shop/Order CTA — the same approach commercial GBP tools use. It is labelled in-UI as publishing as an Update so no one expects a Product Editor entry. (A synced/imported product post reads back as `standard`, since Google stored it as STANDARD — the `product` framing is local only.)
  - `callToAction`: `{actionType: BOOK | ORDER | SHOP | LEARN_MORE | SIGN_UP | CALL, url}` (CALL uses the listing's number, no URL).
  - `media`: photos referenced by **publicly fetchable `sourceUrl`** — min 250×250 px, 10 KB–25 MB. (Our public Supabase buckets satisfy this; see §8.)
  - `event`: `{title, schedule: {startDate/startTime/endDate/endTime}}` — required for EVENT and OFFER types.
  - `offer`: `{couponCode, redeemOnlineUrl, termsConditions}` — OFFER only.
  - Response carries `name` (`accounts/*/locations/*/localPosts/*`), `state` (`PROCESSING` → `LIVE` | `REJECTED`), `searchUrl`, `createTime`/`updateTime`.
  - **Post URL (built 2026-07-23):** Google's `searchUrl` — the public link to the live post — is persisted to `gbp_posts.search_url` and returned on every list/detail read. It's captured from the publish response and, because Google frequently populates `searchUrl` a few minutes *after* the post goes LIVE (status already `live`), the sync job backfills it via the pure `post_needs_update` predicate (updates on a status **or** newly-arrived-URL **or** google_state change; never clobbers a stored URL with an empty one). The post-publish sync (~15 min) or the manual sync endpoint refreshes it.
- **Moderation:** Google can reject posts post-hoc (content policy — phone numbers in text are a classic trigger; also regulated-industry content). `REJECTED` arrives asynchronously via `state` — the module must re-read state after publish, not fire-and-forget.
- **Post lifespan:** STANDARD posts scroll down the profile as new ones publish (older UI behavior of 7-day expiry is gone; posts persist but lose prominence) — the *cadence* is what maintains presence, hence scheduling (§9).
- **Insights:** `localPosts:reportInsights` returns `LOCAL_POST_VIEWS_SEARCH` and `LOCAL_POST_ACTIONS_CALL_TO_ACTION` per post — Phase 3 (verify metric availability at build time; Google has pruned insight metrics before).

---

## 3. Permissions & activation checklist (do this before/with Phase 0)

The app-side check tool is **`writer/platform-api/scripts/verify_gbp_api_access.py`** (ships with this PRD). Run it wherever `GOOGLE_SERVICE_ACCOUNT_KEY` is available (Railway PLATFORM shell, `railway run`, or locally with the key exported). It proves, in order, each layer below and prints an actionable diagnosis per failure. As of 2026-07-20 the production state is: key present on PLATFORM; **item 3 confirmed** — the GCP console shows **300 QPM** (project approved); `GBP_METRICS_ENABLED` **not set** (connection layer dormant) and **no live GBP API call has been made by the app yet** — so items 1–2 and 4–5 remain unverified until the script runs green.

| # | Layer | What "correct" looks like | How to fix |
|---|---|---|---|
| 1 | Service-account key | `GOOGLE_SERVICE_ACCOUNT_KEY` parses; token mints for scope `business.manage` | Re-download key from GCP → IAM → Service Accounts |
| 2 | APIs enabled on the SA's GCP project | **Google My Business API (v4)** ✚ **My Business Account Management API** ✚ **My Business Business Information API** all enabled | GCP Console → APIs & Services → Enable. The v4 API is the one posts actually use — don't stop at the v1 pair |
| 3 | Project approved / quota granted | `accounts.list` returns 200 (not 429/`RESOURCE_EXHAUSTED`); GCP quota page shows ~300 QPM, not 0, **for each of the three APIs** | Submit/chase the Business Profile API access request for *this* project. If approved but one API still shows 0 QPM, reply on the approval ticket naming that API |
| 4 | SA is a Manager on the profile | `accounts.list` → `locations.list` shows the client's listing; v4 `localPosts.list` returns 200 | In the GBP dashboard (business.google.com) for each client: Settings → Managers → add the SA's `client_email` as **Manager** (Owner not needed). Invitation must be *accepted*? — no: SA additions apply directly, but propagation can take minutes |
| 5 | Write access | (Optional flag `--post-test`) create + immediately delete a minimal STANDARD post on a designated test location | Same Manager grant covers writes; failure here with reads green usually means content-policy rejection or the chains restriction |

The script's step 4/5 output also yields the `accounts/{id}` + `locations/{id}` pairs to seed `gbp_locations` with.

**Config note:** `gbp_performance_service.is_configured()` currently gates the *shared* connection layer on `gbp_metrics_enabled`. Phase 0 splits that: a new `gbp_api_enabled` flag gates the connection layer (account/location resolution, verify), with `gbp_metrics_enabled` and `gbp_posts_enabled` gating their respective features on top. Flipping metrics on is NOT required to ship posts.

---

## 4. Product scope & phasing

### Phase 0 — Connection activation (mostly ops, small code)
- Split the config gate as above (`gbp_api_enabled`); run the verify script; enable the three APIs / confirm quota; add the SA as Manager on 1–2 pilot client profiles; register their locations via the existing `POST /gbp/locations` + `resolve-locations` flow (UI already exists on the metrics side of the house — reuse, don't duplicate).
- Exit criteria: `gbp_locations` rows with `access_status='ok'` for pilot clients, proven by the existing verify path **plus** a v4 `localPosts.list` 200 (add this to the verify call so posts-readiness is what's actually proven).

### Phase 1 — Manual compose + publish + history (the core)
- **Compose form** (per client, per registered location): topic type (STANDARD/EVENT/OFFER), body (live 1,500-char counter), CTA type + URL (auto-suggest the client's website; UTM params appended by default — `utm_source=gbp&utm_medium=post&utm_campaign=<slug>`), optional image, EVENT/OFFER extra fields.
- **Publish** runs as an `async_jobs` **`gbp_post_publish`** job (freeze-gated): create via v4, persist `google_name`/`search_url`/`state`, then re-check state (see sync below). Failures → `status='failed'` + error, surfaced in UI + a warning notification (`kind="gbp_post_failed"`).
- **History list**: all posts with status chips (draft / scheduled / publishing / live / rejected / failed / deleted), search URL links, edit (patch) + delete (both via API, reflected locally). **Delete is three-tiered** (built): soft-delete/trash (`DELETE /gbp/posts/{id}`, leaves any live Google post up) + restore; **remove-from-Google** (`POST …/remove-from-google`, calls the v4 delete so the post leaves the live listing, then trashes the row); permanent purge (`DELETE …/{id}/permanent`); and a **bulk empty-trash** (`DELETE /clients/{id}/gbp/posts/trash`) that permanently deletes all trashed posts but **skips any still live on Google** (purging the row would orphan the live post) and reports `skipped_live` — the pure `is_live_on_google` guard is unit-tested.
- **State sync**: a **`gbp_posts_sync`** job (per client, daily on the shared scheduler + triggered ~15 min after each publish) lists live posts from Google, reconciles states (catches async `REJECTED` — emits a warning notification naming the post), and imports externally-created posts as read-only history rows (`source='external'`).
- **Freeze Protocol**: `gbp_post_publish` joins `FREEZE_GATED_JOB_TYPES`; compose/publish routes call `assert_not_frozen`. (Sync keeps running — observation, not output.)

### Phase 2 — AI drafting + scheduling
- **AI draft** (`gbp_post_generate` job): Claude drafts a post from the client's stored context — brand voice, ICP/differentiators, services (`clients` + silo/keyword data), recent review themes (the strategist's `review_snippets` raw material), recent published content (completed runs / local_seo_pages — "announce the new page" is a first-class draft mode), target keyword or theme supplied by the user. Guardrails in the prompt: never invent offers/prices/dates; no phone numbers in body text (rejection trigger); no medical/regulated claims; ≤1,500 chars with the CTA carrying the link. Output = a **draft** for human review, never direct to publish.
- **"Draft a GBP post about this" (manual content trigger — locked decision 4):** an action on published content surfaces (a completed run's article view, a Local SEO page's saved/published view) that opens the composer with an AI draft pre-seeded from that page (title, URL as the CTA link, summary from the content). Manual only — no automatic draft-on-publish producer in v1.
- **Recurring schedules** (`gbp_post_schedules`): per client+location cadence (weekly/biweekly/monthly, weekday + hour) and a theme/rotation note; each tick AI-drafts a post. Two modes per schedule: **draft-for-approval** (default — creates a draft + in-app notification; a human approves → publish) and **auto-publish** (opt-in per schedule, for clients/owners who accept it — locked decision 2). Self-clocked `next_run_at` rows on the shared `gsc_scheduler` loop — the `brand_scan_schedules` pattern verbatim; no new infra.
- Model config: `gbp_post_model` (default `claude-sonnet-4-6` — same family as other client-facing copy; Haiku rejected for brand-voice fidelity, consistent with the Local SEO service-page ruling).

### Phase 3 — Measurement + suite integration
- **Insights**: pull `reportInsights` per live post into `gbp_post_insights` (weekly, cheap); show views/CTA-clicks per post; roll into the Client Report ("Work delivered" already exists — add a "GBP posts published" line + a posts section when the module is active) and the strategy digest (a `gbp_posts` provider: cadence kept/missed, recent posts, rejection rate — TRAP note: post views are impressions on the listing, not site traffic).
- **Action Plan / producers**: `maps_weak_area` / `maps_decline` / GBP-audit actions gain a deep link into the composer pre-seeded with the target keyword/area; optionally a task producer ("Monthly GBP posts" is already a Task Library concept — posting from the composer can auto-tick it later; keep this loose until proven).
- **SerMaStr action**: `create_gbp_post` (parameterized, staged, confirm-gated like other content actions) — drafts from a chat instruction, posts only after reply-*yes*.

---

## 5. Approval model (locked for v1)

Publishing to a client's public listing is an outward-facing act. Defaults:
- Manual composes publish immediately on the user's explicit Publish click (the click *is* the approval).
- AI drafts always land as drafts; a human publishes.
- Scheduled runs default to draft-for-approval; **auto-publish is per-schedule opt-in** and is called out in the schedule UI ("posts will go live with no review").
- A frozen client blocks all publishing (including auto-publish schedules — the tick still drafts, marked "held by freeze", so nothing is silently lost).

---

## 6. Data model (new migration; mirrors suite conventions — RLS enabled, no policies, service-role only)

```sql
gbp_posts (
  id uuid pk,
  client_id uuid fk clients on delete cascade,
  location_row_id uuid fk gbp_locations on delete cascade,
  schedule_id uuid null fk gbp_post_schedules,
  source text not null default 'manual',        -- manual | ai | schedule | external
  topic_type text not null default 'standard',  -- standard | event | offer
  summary text not null default '',
  cta_type text, cta_url text,
  event jsonb, offer jsonb, media jsonb,        -- shapes per §2
  status text not null default 'draft',         -- draft | scheduled | publishing | live | rejected | failed | deleted
  scheduled_at timestamptz, published_at timestamptz,
  google_name text, google_state text, search_url text,
  error text,
  created_by uuid, created_at/updated_at timestamptz
)
-- partial unique on (location_row_id, google_name) where google_name is not null
-- (sync idempotency: an external/reconciled post upserts on its resource name)

gbp_post_schedules (
  id uuid pk, client_id fk, location_row_id fk,
  cadence text not null,                        -- weekly | biweekly | monthly
  weekday int, hour_utc int,
  topic_type text default 'standard',
  theme_notes text,                             -- rotation guidance fed to the draft prompt
  auto_publish boolean not null default false,
  active boolean not null default true,
  next_run_at timestamptz, last_run_at timestamptz,
  created_at/updated_at
)

gbp_post_insights (                              -- Phase 3
  post_id fk gbp_posts, metric text, value bigint, as_of date,
  pk (post_id, metric, as_of)
)
```

`async_jobs.job_type` CHECK widened (additive, preserving the full live set — the live CHECK is wider than any single repo migration, same caveat as `20260707080000`): `gbp_post_publish`, `gbp_post_generate`, `gbp_posts_sync`.

---

## 7. Services & code layout

| Piece | Path | Notes |
|---|---|---|
| API client | `services/gbp_posts_api.py` | Thin v4 REST wrapper (httpx + SA token via the shared `_credentials()`); pure builders `build_local_post_body`, `parse_local_post`, `classify_post_error` — unit-tested without Google |
| Module service | `services/gbp_posts_service.py` | CRUD, publish/sync/generate job runners, schedule tick (`enqueue_due_gbp_post_schedules` on the shared scheduler), freeze + config gates |
| Draft prompt | in `gbp_posts_service` (or `gbp_post_prompts.py` if it grows) | context assembly reuses `brand_voice`/`icp_service.resolve_icp_text`/review snippets |
| Router | `routers/gbp_posts.py` | `GET/POST /clients/{id}/gbp/posts`, `PATCH/DELETE /gbp/posts/{post_id}`, `POST …/publish`, `POST …/generate`, schedules CRUD, sync-now |
| Connection split | `services/gbp_performance_service.py` | `is_configured()` re-gated on `gbp_api_enabled` (metrics keeps its own flag on top) |
| Frontend | `pages/GbpPosts.tsx` + workspace card "GBP Posts" | Compose / History / Schedules tabs; drafts inbox with approve-&-publish |
| Tests | `tests/test_gbp_posts.py` | pure builders, error classification, schedule due-logic, draft-prompt assembly |

Config (`config.py`): `gbp_api_enabled` (False), `gbp_posts_enabled` (False), `gbp_post_model`, `gbp_posts_sync_hour_utc`, `gbp_post_max_chars` (1500), `gbp_post_default_utm` (True).

---

## 8. Media handling (locked decision 3)

**Built 2026-07-23 (backend):** `POST /clients/{id}/gbp/posts/image` (multipart) validates an upload against Google's local-post floor — **JPG/PNG only** (WebP/GIF are dropped: Google rejects them for local posts, unlike the generic `/files/image` endpoint), **≥250×250 px** (decoded with Pillow), **10 KB–25 MB** — via the pure, unit-tested `image_rejection_reason`, then stores it in the public `wordpress_images` bucket under a `gbp-posts/` prefix and returns the public URL to drop into a post's `media`. `GET /clients/{id}/gbp/posts/reusable-images` lists the client's existing public images (blog + Local SEO featured images) for the "reuse suite images" picker. A rejected image fails at upload (413/422) rather than becoming a rejected post.


An optional single image per post, from either source:
- **Upload** through the existing file-upload path into a **public** bucket (reuse `wordpress_images` or add `gbp-post-images`), validated app-side against Google's floor (≥250×250, ≥10 KB; Pillow is already a dependency).
- **Pick from the client's existing suite images** — a picker over the client's already-public generated assets (blog featured images in `wordpress_images`), so the "announce this content" flow can reuse the piece's own image with zero extra work.

The stored public URL goes into `media[].sourceUrl`. Google fetches at publish time — a private/signed URL will fail, hence public buckets only. AI-generated-on-demand imagery is out of scope v1.

---

## 9. Risks / open questions

1. **v4 legacy risk** — posts sit on a deprecated-family API Google has kept alive for years without a successor. Mitigation: the API wrapper is one thin file; a future v1 posts API would be a swap inside `gbp_posts_api.py`. Monitor the deprecation schedule; nothing else in the suite couples to v4.
2. **Approval reality** — ~~unknown~~ **quota confirmed at 300 QPM in the GCP console (2026-07-20)**; the project is approved. The verify script remains the Phase 0 gate for the layers the console can't show (v4 API enablement, SA-as-Manager grants, live posts-surface access).
3. **Service-account manager onboarding** — one more "add this email" step per client (same friction as GSC; the UI already surfaces the SA email via `/gbp/service-account-email`).
4. **Content-policy rejections** — expected occasionally; the sync job + notification make them visible, and the draft prompt avoids the known triggers. Track rejection rate in Phase 3.
5. **Open (ask the owner):** (a) default posting cadence for the Baseline Stack (weekly?); (b) ~~auto-publish in v1?~~ **resolved 2026-07-20: exists, opt-in per schedule, off by default** (locked decision 2). (c) test-post location for verify `--post-test` (use the agency's own listing, not a client's).

## 10. Success metrics

- Pilot clients posting on cadence ≥4 weeks with zero manual dashboard posting.
- <5% rejection rate on AI drafts after the first prompt iteration.
- Post→site clicks visible via UTM once GA4 (Client Reporting Phase 2) lands.
