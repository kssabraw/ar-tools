# Social Media Manager + Content Creator — Module PRD v1.0

**Status:** Design-complete (owner grill, 2026-09-02) — **not yet built.** This PRD
records the decisions reached during the design grill; it is authoritative for the
module's scope and shape. Implementation has not started.

**Vendor-gate update (2026-09-02, later the same day):** the four PostPeer P0 questions
are **closed** (`social-media-vendor-confirm-postpeer-v1_0.md` v1.1): the X link tax is a
confirmed **pass-through** (5 / 50 credits), **Instagram carousels are live** (the v1
single-image restriction was a vendor limit — carousel scope is now an owner call), there
is **no SLA** (accepted; the adapter is the mitigation), and the legal-entity question was
**waived by the owner**. §1/§4/§11/§14 reflect this.

**Review corrections (2026-09-02):** this revision applies fixes from an adversarial
review of v1.0 — the image model is switched to **nano-banana Pro (Gemini 3 Pro
Image)** for per-platform aspect-ratio control (§4/§6/§11/§13), the budget meter's
fail-closed template is corrected to `autonomy_budget.reserve` (§3), and there are
data-model, token-ownership, scope, and failure/edge-path clarifications
(§3/§5/§6/§10/§13/§14).

**Companion docs:**
- `docs/modules/social-media-module-context.md` — the domain glossary (Source,
  Angle, Draft, Post, Calendar, Cadence, Social Account, Competitor Signal, Social
  Manager, Social Creator, Social Policy, Graduated approval, Platform Spec,
  Analyze-in-place, Auto-publish). Read it first for vocabulary.
- `docs/adr/0001-postpeer-posting-provider-behind-adapter.md`
- `docs/adr/0002-analyze-in-place-never-rehost-competitor-media.md`
- `docs/adr/0003-social-autonomy-is-a-domain-executor.md`
- `docs/modules/social-media-cost-model-v1_0.md` — worked cost model (§11).
- `docs/modules/social-media-failure-handling-v1_0.md` — failure/edge-path spec (§14).
- `docs/modules/social-media-vendor-confirm-postpeer-v1_0.md` — PostPeer due diligence (§14).

**Sibling modules this builds on / mirrors:** GBP Posts
(`gbp-posts-module-prd-v1_0.md` — the publish-lifecycle template), the autonomy
executor (`autonomous-seo-agent-plan-v1_0.md` — the guardrails reused for social
autonomy), Competitive Intelligence (`client_competitors` registry, extended
here), the voice-card system, and the shared scheduler/notifications/freeze rails.

---

## 1. What this is

One suite module, **two surfaces over one per-client data model**, that
repurposes a client's existing content into on-brand, platform-native social
content — informed by competitor research, enforced against the client's brand
voice, human-approved — and publishes it to the client's own social accounts.

- **Creator (surface)** — generation: a **Source** → 3–5 **Angles** →
  per-platform **Drafts** (copy + image).
- **Manager (surface)** — planning/operations: the **Calendar**, per-platform
  **Cadence**, approval, publishing, and (later) performance.

**Platforms (v1):** Twitter/X, Facebook (Pages), Instagram (feed, **single-image as the
floor** — PostPeer's carousel support is now confirmed live, so whether a multi-image
carousel Draft type is in v1 is an **open owner scope decision**; Stories/Reels remain a
separate open decision), Pinterest — text + still image, fully produced. **YouTube** is analyze-only in v1: the module
reverse-engineers competitor video and produces a **storyboard/brief + thumbnail +
title/description/hashtags** for the client to shoot; it does **not** generate
video.

**The endgame** (built toward, not shipped in v1) is an **autonomous social
department**: humans approve content and tune the agents; the department otherwise
plans, produces, schedules, and — at the top autonomy tier — publishes on its own.
This is realized as a **domain executor reusing the suite's existing autonomy
guardrails**, not a new persona (ADR-0003).

## 2. Why, and non-goals

**Why:** the suite already generates a client's blog posts, Local SEO/Ecommerce
pages, keyword research, and competitive intel — turning each into platform-native
social content is high-leverage and nearly free of new source material. Social is
also a channel the agency currently manages by hand.

**Non-goals (v1):**
- **Video production** — no generated video; YouTube/Reels are analyze + storyboard
  only (deferred, Phase 5).
- **Auto-publishing by default** — publishing is human-approved unless a client is
  explicitly opted into the top autonomy tier.
- **Re-hosting or reposting competitor media** — analyze-in-place only (ADR-0002).
- **Client-facing self-serve** — internal team use, like the rest of the suite.
- **Post-publish analytics** — deferred to Phase 4 (read engagement back from the
  posting provider then).

## 3. Architecture & suite integration

Rides all standard rails — no new infrastructure:
- **`async_jobs`** for every heavy step (research, generate, publish, orchestrate);
  new job types registered by widening the live CHECK constraint + a `job_worker`
  dispatch branch.
- **Shared scheduler** (`gsc_scheduler`) for due work via `enqueue_due_social_*`;
  the DST-correct `compute_next_run_at` cadence helper is reused for Cadence.
- **`notifications.emit`** for approval-needed / publish-failed / research-ready.
- **Voice-card enforcement** — "on brand" is *scored and enforced*, not just
  prompted, reusing the existing voice-card machinery.
- **Freeze protocol** — content-output + publish job types added to
  `FREEZE_GATED_JOB_TYPES`; routers call `assert_not_frozen`. Research/observation
  keeps running under freeze; output pauses.
- **Per-module paid-call budget meter** — a `social_usage(day, calls)` table +
  `reserve_social_calls` RPC. **Copy `autonomy_budget.reserve` — fail-CLOSED on RPC
  error (a failed reservation must never spend) — NOT `keyword_research.reserve_budget`,
  which is fail-OPEN on RPC error.** Every paid external call (Apify / TwelveLabs /
  nano-banana Pro / posting provider) reserves before it spends.
- **The one genuinely new plumbing:** per-client, per-platform **Social Account**
  connections. The per-account OAuth tokens are **held by the posting provider, not
  stored by us** — `social_accounts` keeps only the provider's `adapter_account_id`
  (deliberate: we don't want a platform-credential store to secure).

## 4. External services

See ADR-0001 and ADR-0002 for the load-bearing decisions. Reliability/legal
posture per service:

| Service | Role | Posture |
|---|---|---|
| **PostPeer** | Publish to the client's accounts; hosts per-account OAuth | Indie/early, **no SLA (confirmed)** — **behind a swappable adapter**; Ayrshare the fallback. Publishes under its own reviewed apps (confirmed). **X link tax is passed through: 5 credits plain / 50 credits with a URL** (vs 1 credit elsewhere); analytics reads 1 credit/call. Media by public URL. |
| **Apify** | Scrape public competitor posts (per-platform actors) | Logged-out public content, **content not identities**; per-result pricing; retention-bound any personal data. |
| **TwelveLabs** | Analyze competitor + client video (Pegasus/Marengo) | Reliable, first-party-grade; **ingest by public URL** (no download); metered by **minutes indexed** with a per-run cap. |
| **cobalt.tools** | Download media | **P5 dependency only** (video production) — no v1 phase consumes it, so it is NOT provisioned in P0. **Self-hosted only**; **owned/licensed assets only** (never competitor media). |
| **nano-banana Pro** (Gemini 3 Pro Image) | Generate/edit images | Chosen over 2.5 Flash for **flexible aspect ratios** (2K/4K, e.g. 9:16 / 2:3) + strong in-image text rendering — both required by the per-platform Platform Spec (§6). The existing `services/nano_banana.py` (2.5 Flash) sends **no** `imageConfig`/`aspectRatio`, so the module needs a **Pro-based renderer that passes per-platform `aspectRatio`** (new code, not the GBP call as-is). ~$0.134/image at 1K/2K (vs ~$0.039 for 2.5 Flash) — the largest per-Draft cost line, metered. SynthID-watermarked; keep to client's own assets. |
| **Claude Sonnet 5** | Copy + angle + image-prompt authoring | The suite's default generation model. |

**Vendor facts to verify before/at Phase 0** (not decisions): current TwelveLabs +
nano-banana **Pro** pricing (per-image cost drives the budget); cobalt self-host on
Railway (P5 only). *PostPeer's app-review model, X link-tax handling, and Instagram
Stories support (Business account only, caption-less) are now confirmed — vendor-confirm
doc §1/§2/§6.*

## 5. Domain / data model (sketch)

Greenfield (no prior social-publishing tables). Anchor everything to `clients`.
Indicative tables (final columns settled at build):

- **`social_accounts`** — `(client_id, platform, adapter, adapter_account_id,
  handle, status, connected_at)`. One per connected platform account.
- **`social_competitor_handles`** — per-platform handles for a competitor, as a
  child table keyed `(competitor_id, platform, handle)` referencing the existing
  `client_competitors` identity — **not** bare rows on `client_competitors` itself
  (its uniqueness indexes are partial, `WHERE domain IS NOT NULL` / `WHERE place_id
  IS NOT NULL`, so a handle-only row with null domain **and** null place_id escapes
  dedup and would allow duplicate competitors).
- **`social_competitor_signals`** — per `(client, competitor, platform)`:
  themes, formats, hook patterns, cadence, top-performers (**links only**),
  rolled-up "what's working". Produced by analyze-in-place research.
- **`social_drafts`** — a per-platform Draft: `(client_id, source_ref, angle,
  platform, copy, image_url, platform_metadata jsonb, voice_verdict,
  spec_verdict, status)`. Editable pre-approval.
- **`social_posts`** — an approved/scheduled/published Post + lifecycle:
  `(draft_id, platform, scheduled_at, published_at, provider_post_id, status,
  status_detail)`. Mirrors the GBP-Posts lifecycle.
- **`social_policy`** — per-client tuning (see §10): cadence/on-off per platform,
  allowed/blocked topics & claims, tone/angle prefs, competitor focus, budget
  ceiling, autonomy tier / approval strictness, and **editable image/text
  generation prompt templates**.
- **`social_platform_specs`** — the per-platform constraint data (§6).
- **`social_usage`** — the daily paid-call budget meter.

## 6. Generation pipeline (Creator)

`Source` → `Angles` → per-platform `Drafts`.

- **Source** — a client blog run, Local SEO/Ecommerce/Website page, keyword-research
  idea, a competitor top-performer ("make our version"), or a manual topic. Read
  finished client content via existing helpers — `illustration._load_article` returns
  the article **sections** (title/keyword come from `runs.keyword`, not this helper);
  `local_seo_pages.content_html` + `page_title`; `syndication_rewrite.extract_source_content`
  returns `(title, markdown)` for an external URL. Reuse `list_reusable_images` for
  assets.
- **Angles** — 3–5 distinct editorial takes proposed by Sonnet, grounded in the
  Source + brand voice/ICP + relevant **Competitor Signals** + keyword ideas;
  multi-select; the user may hand-write one. The chosen Angle is stored on the
  Draft set.
- **Draft fan-out** — one job produces N platform-native Drafts. **Copy is tailored
  per platform** (separate Sonnet pass each — native length/format/hashtags/CTA).
  An optional image via **nano-banana Pro**, generated at the **per-platform aspect
  ratio** from the Platform Spec (`aspectRatio` passed to the API) so the spec
  validator can pass it; subject-consistency for a coherent set.
  Per-platform metadata (Pinterest board+title, YouTube description, …).
- **Platform Spec** — per-platform constraint data (char limits, aspect ratios,
  hashtag norms, CTA style, link policy) consumed by **both** the generation prompt
  **and a deterministic validator**. A Draft violating a hard constraint (over
  length, wrong aspect ratio, a link on a "no-link X" client) is **flagged before it
  can be approved** — the voice-card LLM-writes/regex-enforces split, applied to
  platform rules.
- **Voice** — enforced + scored via the existing voice-card system, not merely
  prompted.

## 7. Competitor research (analyze-in-place — ADR-0002)

- Competitor identity extended with per-platform **handles** (manual entry v1;
  discovery later).
- **Apify** scrapes public post data; **TwelveLabs** analyzes competitor video from
  its public URL (Pegasus for the "why this works" teardown — hook, pacing, on-screen
  text, structure — Marengo for timestamped search). No downloads; cobalt is
  owned/licensed only.
- Output = a per-`(client, competitor, platform)` **Competitor Signal** (links, not
  media) feeding Angle proposals + generator prompts.
- **Cadence:** on-demand + an optional weekly scheduled refresh per client (mirrors
  `competitor_intel`), budget-metered and freeze-skipped.
- **"Make our version"** is **manual only** — a human picks a top-performer, which
  becomes a Source with a suggested Angle. Transform, never replicate.

## 8. Accounts & connection

- Each client connects **their own** accounts through the posting adapter's OAuth
  (PostPeer today) — one-click, no per-platform apps for us. Stored per
  `(client, platform)` as a **Social Account**.
- **A per-platform ELI5 client connect guide is a required deliverable** — step-by-step
  with the prerequisites surfaced at connect time (e.g. Instagram must be a
  Business/Creator account).

## 9. Manager: Calendar, Cadence, approval, publish

- **Calendar** — per-client, cross-platform view of scheduled + published Posts.
- **Cadence** — per-`(client, platform)` target frequency that **suggests** Calendar
  slots; a human confirms/adjusts each (`compute_next_run_at`).
- **Approval** — **per-post by default, with opt-in batch approval** (approve a whole
  generated set / a week in one action, PACE's "yes / approve 1,3" pattern). Optional
  **QA-agent gate** with a social rubric (voice pass, has-CTA, platform constraints,
  no banned claims, image present) — off by default, opt-in.
- **Publish lifecycle** — the GBP-Posts template: draft → approve → **explicit,
  freeze-gated, idempotent publish job** → **async status reconciliation** (the
  provider's async REJECTED/LIVE verdicts reconciled back onto the Post, with
  failure notifications).

## 10. Autonomy (the endgame — ADR-0003)

A **domain executor that reuses the autonomy executor's guardrail *primitives***
(`autonomy_policy.classify`, `autonomy_budget.reserve` (fail-closed), tiers, freeze,
the DORA veto) — but **not its candidate loop**. The SEO executor's
`gather_candidates` is remediation-reactive (it returns nothing unless a goal is
behind/overdue), whereas social is **cadence-driven and generative**, so the
orchestration loop below is genuinely **new code that calls the shared primitives**,
not an extension of the existing executor. Not a new persona.

- **Social Manager (orchestrator)** — a headless autonomous loop: each cycle reads
  the **Social Policy**, Cadence, goals, and Competitor Signals → plans the period →
  dispatches the Social Creator → routes results to approval → schedules → (top-tier)
  publishes.
- **Social Creator (worker)** — the bounded, tool-using production loop the Manager
  dispatches (and the Creator surface invokes on-demand): research → Angle → design →
  self-critique vs voice/Platform-Spec → regenerate. One engine, two callers.
- **Social Policy (Playbook)** — the per-client tuning object: cadence/on-off per
  platform, allowed/blocked topics & claims, tone/angle prefs, competitor focus,
  budget ceiling, **autonomy tier / approval strictness**, and **editable image + text
  generation prompt templates**. A tuned prompt still passes the Platform-Spec + voice
  validators — tuning steers, never bypasses.
- **Graduated approval** — strictness scales with tier: new/low-trust → approve every
  Post; trusted → batch / approve-by-exception; top tier → **Auto-publish** with
  post-hoc review. This is what makes "minimal supervision" real. Auto-publish is
  top-tier + explicit per-client opt-in only; never a default.

## 11. Cost governance

- **Own daily paid-call budget meter** (`social_usage` + `reserve_social_calls`),
  separate from the Recipe-Engine/autonomy budget (this is content production, not
  link deployment) but **exposed to the Recipe Engine as a cost line**.
- TwelveLabs metered by **minutes indexed** with a per-run cap.
- X's link tax is a **confirmed PostPeer pass-through** — **50 credits (~$0.30–0.43) for
  an X post whose body contains `http(s)://`, 5 credits (~$0.03–0.04) otherwise, 1 credit
  on every other platform**. Surfaced as a cost warning at approval/schedule time, plus a
  per-client "avoid links on X" toggle that the Platform-Spec validator enforces
  mechanically (a URL scheme in X copy).
- PostPeer's non-X per-post fee tracked but trivial; analytics reads are 1 credit/call
  (metered in P4).
- **Full worked model: `social-media-cost-model-v1_0.md` (v1.1).** Headline: at
  realistic volume the **nano-banana Pro image (~$0.11/post) and competitor research
  (~$20/client/mo) dominate — not the X link tax.** Base scenario (20 clients × 5
  posts/day) ≈ **$960/mo (~$48/client)**. The **X line is ~$120/mo at a realistic ~10%
  X-link-post share** (confirmed 50-credit pass-through; v1.0's $60 assumed PostPeer
  absorbed the fee). Largest cost lever: a **mixed 2.5-Flash/Pro image path** (Flash
  for square platforms, Pro only for aspect-ratio/text-heavy graphics) roughly halves
  the dominant line.
- The **Social Policy carries a per-client monthly hard ceiling**, enforced by the
  fail-closed meter — the backstop against a runaway autonomous loop.

## 12. Agent integration

- **SerMaStr** — a `social` context provider (scheduled/published Posts + Competitor
  Signals); may **propose** social pushes, never publishes.
- **PACE** — creates/tracks social tasks on the native board (e.g. "approve this
  week's calendar").
- **DORA** — sees social seams (approved-but-unscheduled Drafts, idle connected
  accounts, the autonomy loop's proposals).
- **QA** — the opt-in social rubric (§9).

## 13. Build phases

- **P0 — Foundations:** data model, the swappable posting **adapter**, Social Account
  connection + the **ELI5 per-platform guide**, the budget meter, `async_jobs`/scheduler
  wiring, freeze gating, **+ a thin connect-and-post smoke test** (de-risk PostPeer
  early — answers the vendor-confirm items before the calendar is built on top).
  **The Social Policy object + autonomy-tier field go into the schema here** so the
  orchestrator (P4) is a layer, not a rewrite.
- **P1 — Competitor research** *(moved up to feed Angles):* Apify Signals + TwelveLabs
  analyze-in-place → Competitor Signal.
- **P2 — Creator core:** Source → Angles → per-platform Draft fan-out, voice-enforced,
  Platform-Spec validated (incl. the **nano-banana Pro** renderer emitting per-platform
  aspect ratios). cobalt is **not** provisioned here — it is a P5 dependency.
- **P3 — Manager + full publish:** Calendar, Cadence, per-post/batch approval, the
  GBP-Posts-style publish lifecycle.
- **P4 — Agents, autonomy, analytics:** `social` context providers, PACE tasks, opt-in
  QA rubric, performance read-back, and the Social Manager orchestrator + graduated /
  top-tier opt-in auto-publish.
- **P5 — Deferred:** video *production* (Reels/Shorts/YouTube).

## 14. Open items & risks

- **Vendor-confirm — full readout in `social-media-vendor-confirm-postpeer-v1_0.md`
  (v1.1). The P0 vendor gate is CLOSED.** ✅ Managed OAuth under PostPeer's own reviewed
  apps; platform coverage; IG professional-account requirement; pricing. ✅ (1) **X
  link-post billing** — pass-through, 5/50 credits. ✅ (2) **IG carousel** — live, ≤10
  items, one aspect ratio. ✅ (3) **SLA** — none (accepted; the adapter + polling
  reconciliation are the mitigation). ✅ (4) legal entity — **waived by the owner**. The
  **P0 smoke test remains the go/no-go on real reliability.** Still to confirm: current
  TwelveLabs / nano-banana **Pro** pricing. cobalt self-host is a **P5** concern, not P0.
- **Failure & edge paths — specified in `social-media-failure-handling-v1_0.md`** (the
  PRD above specifies the happy path). It covers the connection-health state machine,
  a **token revoked between approval and scheduled publish** (`blocked_account` hold +
  pause the platform's Cadence, never silent-fail), a **Source edited/unpublished after
  its Draft is approved** (`source_version` stamp → `source_changed` re-review hold),
  **partial fan-out failure** (per-platform independent Drafts + retry), **empty states**
  (competitor with no posts; client with zero connected accounts), and the reused
  GBP-Posts idempotency guards. The new Post statuses it introduces feed the §5 model.
- **Platform onboarding realities:** Instagram Business/Creator requirement; X link
  economics can dominate cost for link-heavy clients — model a realistic client-volume
  scenario before committing budgets.
- **Legal posture:** analyze-in-place keeps us clear of the main copyright/ToS risk;
  keep personal data minimized + retention-bounded; owned/licensed provenance on any
  downloaded asset.
- **Autonomy is the first *domain-scoped* orchestration** in a by-disposition agent
  suite — deliberately built on the existing guardrails to stay on-grain (ADR-0003).
