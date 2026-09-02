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
| Publish | **PostPeer** behind an adapter | Managed OAuth under its own reviewed apps (confirmed). X link-tax handling ★ open. |
| Competitor scrape | **Apify** (per-platform actors) | Public/logged-out content only. |
| Competitor video analysis | **TwelveLabs** (Pegasus/Marengo) | Ingest by public URL; cap minutes/run. |
| Media download | **cobalt.tools** (self-hosted) | **P5 only** — owned/licensed assets. Not provisioned in v1. |

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
- **Don't build an IG carousel Draft type in v1** — PostPeer's IG adapter is single-media (carousel is
  roadmap). v1 IG = single-image.
- **Don't use nano-banana 2.5 Flash where a non-1:1 aspect ratio is required** (Pinterest/9:16) — it
  can't produce it. Use the Pro renderer.
- **Don't copy the keyword_research budget pattern** (fail-open) for spend — use `autonomy_budget.reserve`.

## When stuck / ask the owner

The mixed 2.5-Flash/Pro image cost lever (build in v1 or later); whether v1 IG includes single-media
Reels/Stories or feed-only; the default per-client monthly cost ceiling; anything the PostPeer P0
questions turn up. See `HANDOFF.md` (this folder) for the live open-items list.
