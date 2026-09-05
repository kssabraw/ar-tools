# Video Studio — module design & context

> **Status: PLANNING ONLY. Nothing is built.** This file is the design/context reference
> for the proposed **Video Studio** module (working name). It captures a planning session,
> not shipped state. Read `HANDOFF.md` in this folder for the locked/open decisions, the
> grounded economics, and the next steps. When this module is actually built, fold a
> summary into the root `CLAUDE.md` (which documents *built* state) and promote this into a
> proper `docs/modules/video-studio-module-prd-v1_0.md` in the house PRD format.

## What it is (one line)

A per-client tool that turns a page or keyword into a **faceless voiceover-over-b-roll social
video** (30s or 1m, rendered 9:16 **and** 16:9), through a per-client brand template and two
low-touch review gates, delivered to the client's Google Drive folder.

Not a customer-facing product — internal agency use, same as the rest of the suite. It sits
**downstream** of content the suite already produces (blog runs, local SEO pages, website
pages, keyword research), so ~70% of the scaffolding already exists.

## The core design principle

**The LLM writes the *content* of each shot; the brand template supplies the *style*
deterministically; a human never hand-writes prompts (but can edit at Gate 1).** This is the
same "LLM fills slots, deterministic compiler emits the artifact" pattern as the Website
Builder theme compiler and the voice card. It is what makes 12 independent shots look like
one branded video, and it is what keeps the module cheap to run.

## Why faceless VO-over-b-roll (the format decision)

- It is the dominant faceless format on TikTok / Shorts / Reels.
- It drops the hardest, most expensive, most liability-prone lane (avatars) with little loss
  for informational / local-SEO content.
- It makes the pipeline **uniform**: every segment is "a visual under a VO line with a
  caption," which lets the whole timeline hang off the VO (see next).

**VO is the spine.** Generate the ElevenLabs VO *first*, take its word-level timing, and hang
everything off it — captions sync to the words automatically, and each visual just fills the
duration of its VO beat. You never time a voice to a video; the voice *is* the clock. This
kills a whole class of sync bugs and is far easier to make look tight.

## Scope (v1)

- **Faceless only** — no on-screen presenter.
- **Two fixed lengths: 30s and 1m.** Fixed length = two concrete recipes, not an open-ended
  duration problem; predictable cost per SKU; trivial QA. **This consciously drops the
  long-form YouTube/Facebook content from the original vision** — the faceless format is
  weakest at long-form anyway. Long-form is a much-later phase or a deliberate "AI shouldn't
  make this" call.
- **Stock b-roll by default**; generated clips are an opt-in per-segment upgrade (Phase 2).
- **Delivered as MP4s to Drive.** Auto-publishing to social is Phase 3 (human-in-the-loop).
- **Avatars are parked** (Phase 4). If they return, the engine is **HeyGen, never Higgsfield**
  (see HANDOFF economics).

## The pipeline (mirrors Website Builder: template → plan → generate → deliver)

```
Brand Video Template (per client, set once — the "theme" analog)
        │
page/keyword ──► script (timed beats)  ── LLM, brand-voice-grounded
        │
        ▼
   ElevenLabs VO  ← generated first; returns word timing = the timeline backbone
        ├── captions snap to VO word timing (auto)
        └── each beat gets a visual:  stock (default) | generated (Phase 2)
        │
   content JSON (the shot-list) + storyboard stills
        │   [GATE 1: human approves the storyboard — before any render/generation spend]
        ▼
   merge(visuals, brand template) → json2video assembly (VO spine, word-synced captions)
        │   render 9:16  +  render 16:9   (same content JSON, two aspect variants)
        │   [GATE 2: human approves the finished MP4s]
        ▼
   deliver to client Drive folder      (publish to social = Phase 3, HITL)
```

## Data model (proposed — migrations go in `writer/supabase/migrations/`)

- **`clients.video_template`** (jsonb, keyed like `voice_card`) — the per-client brand
  template: caption style (font/position/color/word-animation), color tokens, logo, intro
  sting, outro CTA card, music bed/vibe, ElevenLabs `voice_id` + settings, color grade / LUT,
  a **stock style profile** (aesthetic bias appended to every stock query), recipe defaults,
  per-lane vendor prefs, and (Phase 2) a **hero anchor image** id. Version it with a
  fingerprint so an edit re-applies going forward without touching past videos.
- **`videos`** — one row per video: `client_id, source_type (page|blog_run|keyword|kw_research),
  source_ref, length (30|60), recipe, content_json (the shot-list), status, gate1_at, gate2_at,
  render_9x16_url, render_16x9_url, cost_usd, error`.
- **`video_assets`** — private `video-assets` storage bucket (mirrors `reports` /
  `task-attachments`): VO audio, storyboard stills, generated clips, final renders.
- **`video_usage`** + **`reserve_video_calls` RPC** — daily paid-call meter (mirrors
  `domain_intel_usage` / `leadoff_spend`), so per-client spend is quotable and capped.

Keep the shot-list as **jsonb on `videos`** (like `websites.config`), not a segments table —
it is the natural Gate-1 review artifact. A `video_segments` table only if per-segment regen
at scale later demands it.

### Shot-list schema (what the `video_generate` LLM emits, per beat)

```json
{
  "beat": 3,
  "vo_line": "And that's why storm damage often hides under the surface.",
  "caption": "Damage hides under the surface",
  "duration_hint": 4,
  "visual": {
    "lane": "stock",
    "stock_query": "close up water damage roof shingles",
    "image_prompt": "weathered asphalt shingles, subtle water staining, overcast",
    "motion_prompt": "slow push-in, gentle parallax",
    "reference": "hero"
  }
}
```

The LLM writes **both** `stock_query` and `image_prompt` every beat (LLM tokens are ~free), so
a reviewer can flip a single beat stock→generated at Gate 1 without re-running the script. The
**style layer** (visual style, color grade, aspect, "no baked-in text / no watermarks / no
faces" negatives, and the consistency anchor) is appended **deterministically from the
template at render time** — the LLM never re-specifies it per beat.

## The three kinds of "prompt" (do not conflate)

| Lane | The "prompt" is really… | Goes to |
|---|---|---|
| **Stock** (v1 default) | a **search query** to *find* footage | stock library search API |
| **Generated image** (Phase 2) | a **descriptive prompt** to *create* a still | Nano Banana |
| **Generated motion** (Phase 2) | a short **motion prompt** for how the still animates | Kling image-to-video |

**v1 only writes stock search queries** — the generative image/motion prompts don't exist
until the generated lane turns on. So v1 is "generate good keyword search queries," not
"generative prompting."

## Consistency (within and across videos)

**Cross-video consistency is carried almost entirely by the deterministic template (the
wrapper), not the b-roll.** Viewers read "same brand" from the intro/caption-style/voice/
pacing/outro far more than from matching footage. So ~80% of consistency is a solved,
free, deterministic template problem.

- **Deterministic (template, applied at assembly, free):** intro sting, outro CTA, caption
  style, logo lower-third, color tokens, ElevenLabs voice, music, recipe/pacing, script tone
  (voice card + ICP), and the **color grade / LUT** — the single biggest unifier of disparate
  stock footage.
- **The residual hard part — b-roll *content* look:** unify with (1) a color-grade/LUT pass in
  assembly, (2) a per-client **stock style profile** biasing the queries, (3) the **hero
  anchor** (generated lane only — one canonical style image per client, seeded into every
  generated still for cross-video look).
- **Line to hold:** *lock the wrapper, vary the content.* Locked per client = wrapper, voice,
  captions, pacing, grade, style profile. Varied per video = topic, hook, VO copy, b-roll.
  Consistency must not become sameness.
- **Canonical exemplar pattern:** the first approved video *is* the reference; later videos can
  be deterministically checked for drift against it (same caption style / grade / voice /
  recipe shape) — a measurable "on-brand" signal, like the structure/voice engines.

**Within a generated video**, Nano Banana consistency comes from *referencing prior images*:
`reference: "hero"` (client style anchor) or `"prev"` (chain off the previous still). A
generated image call is always `image_prompt + reference_image`, bound deterministically in
the render job — "give the prompt" is really "give the prompt *plus the anchor*."

## Vendor abstraction (per-lane — the `entity_provider` pattern)

Each lane resolves its vendor independently, honoring the template's choice, falling back if
unkeyed.

| Lane | v1 | Later |
|---|---|---|
| Voice | ElevenLabs | — |
| B-roll | **stock** (default) \| generated (Kling) — *per-segment* | — |
| Avatar | none | HeyGen (Phase 4) — **never Higgsfield** |
| Assembly | json2video | Creatomate |

Generated clips gated behind `video_generated_clips_enabled` (stock-only until flipped).

## async_jobs (two jobs = two gates)

- **`video_generate`** → source → shot-list (LLM) → ElevenLabs VO → Nano Banana storyboard
  stills → `awaiting_shotlist_review`.
- **`video_render`** → (Gate 1 approved) → optional image-to-video per generated segment →
  json2video assembly (VO spine, word-synced captions) → 9:16 + 16:9 → `awaiting_render_review`.

Both **freeze-gated** (content creation → `FREEZE_GATED_JOB_TYPES` + `assert_not_frozen`), both
**metered**, both survive navigation. Add both to the `async_jobs` job_type CHECK.

**Status machine:** `draft → generating → awaiting_shotlist_review → rendering →
awaiting_render_review → ready → delivered` (+ `failed`, `cancelled`).

## The two gates as UI (this is the unit economics — see HANDOFF: labor-bound product)

Because human minutes are 10–30× the API cost, the gates must be **a glance, not a workbench**:

- **Gate 1 — storyboard filmstrip:** the whole video as a row of stills, each with its VO line
  + caption inline. Default action = **one-click Approve all**. Per-beat you *can* edit a
  query/caption or regen a frame, but the happy path is a glance. This is also the QA surface
  (deterministic content_json checks: has hook, has CTA, caption length, beat cadence).
- **Gate 2 — render review:** play 9:16 + 16:9 side by side; Approve or Send-back-with-note.
- **A global "Videos awaiting review" queue** (like the activity feed / task board) so one
  reviewer batches across all clients — this is the touch-time multiplier.

## Frontend

- `pages/VideoStudio.tsx` (route `clients/:id/videos`) + a workspace **"Video Studio"** card.
- `components/video/` → `TemplateTab`, `NewVideo` (source picker + 30s/1m + engine),
  `ShotlistReview` (Gate 1 filmstrip), `RenderReview` (Gate 2), `Library`.
- Optional suite-level `pages/VideoQueue.tsx` for the cross-client review queue.

## What it reuses (already built)

Brand voice card + ICP (script tone) · content sources (`local_seo_pages`, `website_pages`,
blog `runs`, `keyword_research_runs`, free-text keyword) · Drive delivery
(`resolve_drive_folder(client,"video")`) · notifications (Gate-ready pings + `task_complete`) ·
freeze rails · cost-meter + reserve-RPC pattern · `async_jobs` · logo/colors
(`client-logos` bucket, brand tokens) · QA-agent (later, for on-brand drift checks).

## The one genuinely new muscle

The **shot-list generator** — turning a page into *timed beats with VO lines + caption text +
a stock query (and, Phase 2, image/motion prompts) per beat* is a different output schema than
the prose writers, but it is the same brand-voice-grounded LLM call used everywhere else.

## Config (flags default off; set on the PLATFORM Railway service)

`video_studio_enabled` · `video_generated_clips_enabled` · `video_daily_budget_usd` ·
`video_script_model` · `video_storyboard_model` (Nano Banana / Gemini image) · keys:
`ELEVENLABS_API_KEY`, `JSON2VIDEO_API_KEY`, stock-library key, `KLING_API_KEY`.

## Phasing

- **Phase 0** — brand video template + data model + vendor wrappers (stock, ElevenLabs, json2video).
- **Phase 1** — the profit engine: script → VO → storyboard → Gate 1 → stock assembly →
  Gate 2 → Drive. Stock-only (~$0.30 API/video). **Ship this first.**
- **Phase 2** — Kling generated-clip *accent* lane (storyboard → i2v), behind the flag +
  hero-anchor consistency.
- **Phase 3** — social publishing (HITL, per-platform OAuth — its own sub-project).
- **Phase 4** — avatars (HeyGen) + long-form.
- **Phase 5** — scheduled/batch generation + QA-agent on-brand drift checks.
