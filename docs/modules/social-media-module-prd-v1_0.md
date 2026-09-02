# Social Media Manager + Content Creator — Module PRD v1.0

**Status:** Design-complete (owner grill, 2026-09-02) — **not yet built.** This PRD
records the decisions reached during the design grill; it is authoritative for the
module's scope and shape. Implementation has not started.

**Companion docs:**
- `docs/modules/social-media-module-context.md` — the domain glossary (Source,
  Angle, Draft, Post, Calendar, Cadence, Social Account, Competitor Signal, Social
  Manager, Social Creator, Social Policy, Graduated approval, Platform Spec,
  Analyze-in-place, Auto-publish). Read it first for vocabulary.
- `docs/adr/0001-postpeer-posting-provider-behind-adapter.md`
- `docs/adr/0002-analyze-in-place-never-rehost-competitor-media.md`
- `docs/adr/0003-social-autonomy-is-a-domain-executor.md`

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

**Platforms (v1):** Twitter/X, Facebook, Instagram (feed + carousel), Pinterest —
text + still image, fully produced. **YouTube** is analyze-only in v1: the module
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
  `reserve_social_calls` RPC (the keyword_research/domain_intel pattern),
  fail-closed for spend.
- **The one genuinely new plumbing:** per-client, per-platform **Social Account**
  connections and their tokens (held by the posting provider).

## 4. External services

See ADR-0001 and ADR-0002 for the load-bearing decisions. Reliability/legal
posture per service:

| Service | Role | Posture |
|---|---|---|
| **PostPeer** | Publish to the client's accounts; hosts per-account OAuth | Indie/early — **behind a swappable adapter**; Ayrshare the fallback. Confirm: publishes under own reviewed apps? who pays the X link tax? |
| **Apify** | Scrape public competitor posts (per-platform actors) | Logged-out public content, **content not identities**; per-result pricing; retention-bound any personal data. |
| **TwelveLabs** | Analyze competitor + client video (Pegasus/Marengo) | Reliable, first-party-grade; **ingest by public URL** (no download); metered by **minutes indexed** with a per-run cap. |
| **cobalt.tools** | Download media | **Self-hosted only**; **owned/licensed assets only** (never competitor media). |
| **nano-banana** (Gemini 2.5 Flash Image) | Generate/edit images | Already integrated (`services/nano_banana.py`); subject-consistency for coherent sets; SynthID-watermarked; keep to client's own assets. |
| **Claude Sonnet 5** | Copy + angle + image-prompt authoring | The suite's default generation model. |

**Vendor facts to verify before/at Phase 0** (not decisions): PostPeer's app-review
model + X link-tax handling; PostPeer Instagram **Stories** support (unclear);
current TwelveLabs + nano-banana pricing; cobalt self-host on Railway.

## 5. Domain / data model (sketch)

Greenfield (no prior social-publishing tables). Anchor everything to `clients`.
Indicative tables (final columns settled at build):

- **`social_accounts`** — `(client_id, platform, adapter, adapter_account_id,
  handle, status, connected_at)`. One per connected platform account.
- **`social_competitors`** — extends competitor identity with per-platform
  **handles** (reuse/point at `client_competitors`; add handle rows).
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
  finished client content via existing helpers (`illustration._load_article`,
  `local_seo_pages.content_html`, `syndication_rewrite.extract_source_content`,
  etc.); reuse the reusable-image picker for assets.
- **Angles** — 3–5 distinct editorial takes proposed by Sonnet, grounded in the
  Source + brand voice/ICP + relevant **Competitor Signals** + keyword ideas;
  multi-select; the user may hand-write one. The chosen Angle is stored on the
  Draft set.
- **Draft fan-out** — one job produces N platform-native Drafts. **Copy is tailored
  per platform** (separate Sonnet pass each — native length/format/hashtags/CTA).
  An optional image via nano-banana (subject-consistency for a coherent set).
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

A **domain executor reusing the autonomy executor's guardrails** (tiers,
`autonomy_policy.classify`, fail-closed budget governor, freeze, DORA veto) — not a
new persona.

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
- X's **$0.20/link-post tax** surfaced as a cost warning at schedule time, plus an
  optional per-client "avoid links on X" toggle.
- PostPeer's per-post fee tracked but trivial.

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
  Platform-Spec validated.
- **P3 — Manager + full publish:** Calendar, Cadence, per-post/batch approval, the
  GBP-Posts-style publish lifecycle.
- **P4 — Agents, autonomy, analytics:** `social` context providers, PACE tasks, opt-in
  QA rubric, performance read-back, and the Social Manager orchestrator + graduated /
  top-tier opt-in auto-publish.
- **P5 — Deferred:** video *production* (Reels/Shorts/YouTube).

## 14. Open items & risks

- **Vendor-confirm (Phase 0):** PostPeer app-review model + X link-tax handling;
  PostPeer Instagram Stories support; current TwelveLabs/nano-banana pricing; cobalt
  self-host.
- **Platform onboarding realities:** Instagram Business/Creator requirement; X link
  economics can dominate cost for link-heavy clients — model a realistic client-volume
  scenario before committing budgets.
- **Legal posture:** analyze-in-place keeps us clear of the main copyright/ToS risk;
  keep personal data minimized + retention-bounded; owned/licensed provenance on any
  downloaded asset.
- **Autonomy is the first *domain-scoped* orchestration** in a by-disposition agent
  suite — deliberately built on the existing guardrails to stay on-grain (ADR-0003).
