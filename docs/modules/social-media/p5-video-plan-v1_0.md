# Social P5 — Video Storyboard (slice a) — Plan v1.0

> The FIRST P5 slice, built to the owner's 2026-09-19 decisions (scope doc:
> `p5-video-scope-v1_0.md`). **Slice (a): a storyboard/brief deliverable — NO rendered
> video, NO new vendor.** Scoped Reels (IG/FB) + YouTube Shorts, Compose-first. Grounded
> against `main` @ `b43dff8`. Build docs: `CLAUDE.md` / `HANDOFF.md` (this folder).

## What this builds

A **Video Storyboard** Creator surface: pick a **Source** (topic / URL / blog run / saved
Local SEO page) + a **platform** (IG Reel / FB Reel / YouTube Short) + optional angle/tone →
generate a structured, brand-voiced, competitor-informed **shot-by-shot storyboard** the
client (or the agency videographer) uses to shoot the video. It is a **planning deliverable**,
not a publishable post — the module still does not generate or assemble video.

A storyboard carries:
- **working_title**, **platform**, **format** (reel | short), **duration_seconds** (target),
- **hook** (the first ~3 seconds — the scroll-stopper),
- **shots[]** — ordered, each `{n, visual, on_screen_text, voiceover, duration_seconds, b_roll}`,
- **music** (audio/mood direction), **caption** (the post caption for when they publish),
  **hashtags[]**, **cta**,
- optional **thumbnail_url** (a Nano Banana image via the existing budget-metered path).

## Why a dedicated table (not `social_drafts`)

`social_drafts` is a *publishable post* (copy + media → the publish lifecycle). A storyboard
publishes nothing — it is a brief with a distinct shape (a shot list). Overloading
`social_drafts` would pollute the Drafts tab, the calendar, the approval queue, and every
`status` state machine with a row that can never publish. So: a new **`social_storyboards`**
table (the shot list as JSONB), a distinct surface, and a distinct status (`generated`).
The thumbnail is the ONLY thing that touches the existing publish machinery (a generated image
URL), and it reuses the built image path wholesale.

## Data model — `social_storyboards` (new table, one migration)

```
social_storyboards(
  id            uuid pk default gen_random_uuid(),
  client_id     uuid not null → clients(id) on delete cascade,
  platform      text not null,                  -- instagram | facebook | youtube
  format        text not null default 'reel',   -- reel | short
  source_type   text,                           -- topic | url | blog_run | local_seo_page
  source_ref    jsonb,                           -- {type, url|run_id|page_id}
  source_title  text,
  source_version text,                           -- creator.source_version_of (edited-source guard, future)
  angle         text,
  tone          text,
  title         text,                            -- working title
  storyboard    jsonb not null,                  -- {hook, duration_seconds, shots[], music, caption, hashtags[], cta}
  thumbnail_url text,
  status        text not null default 'generated',   -- generated | archived (free-ish; CHECK the two)
  voice_warnings jsonb,                           -- forbidden-term advisories (best-effort)
  created_by    uuid, created_at, updated_at
)
enable row level security;  -- service-role only (like every social table)
index (client_id, created_at desc) where status <> 'archived';
```

- **No `async_jobs` type.** Generation is a single bounded forced-tool Sonnet call — synchronous
  like `draft-copy` / `angles` (the composer already does synchronous AI calls). No worker
  dispatch, no scheduler hook, no CHECK widen.
- **No provider fields** (a storyboard never reaches PostForMe). ADR-0006 edge untouched.

## Services — `services/social/storyboard.py` (new)

Mirrors `creator.propose_angles` / `carousel_slide_descriptions` exactly:
- **Pure** (unit-tested): `platform_video_guidance(platform, fmt)` (native short-form guidance —
  IG/FB Reel vs YT Short, vertical 9:16, hook-first, on-screen-text conventions),
  `build_storyboard_prompt(...)` (client context + source + angle/tone + competitor-signals block
  + voice block, voice LAST so it wins — the suite's late-high-priority pattern),
  `sanitize_storyboard(raw, max_shots)` (clamp shots to `social_storyboard_max_shots`, coerce
  types, drop empties, guarantee a non-empty hook + ≥1 shot), `_STORYBOARD_SCHEMA` (the
  forced-tool schema).
- **Impure**: `generate_storyboard(client_id, req, user_id)` — `_assert_enabled` →
  `creator.load_source` (verbatim reuse) → `creator.resolve_voice_context` (verbatim) →
  `competitor_research.render_competitor_signals_block(latest_signals_for_client(...))` (P1
  grounding, empty ⇒ prompt byte-identical) → `report_llm.run_forced_tool(model=social_storyboard_model,
  tool_name="emit_storyboard", …)` → `sanitize_storyboard` → best-effort voice advisory
  (`gbp_posts_service.voice_forbidden_hits` on the caption + on-screen text — advisory only, a
  storyboard is not auto-corrected; a human edits) → persist a `social_storyboards` row → return it.
- **CRUD** (mirror `fanout.list_drafts` / `get_draft` / `update_draft` / `delete_draft`):
  `list_storyboards(client_id)`, `get_storyboard(id)`, `update_storyboard(id, …)` (edit title /
  storyboard fields / caption / hashtags / thumbnail_url), `delete_storyboard(id)` (→ `archived`),
  `attach_thumbnail(id, url)`.
- **Voice enforcement is advisory** (not the corrective-rewrite loop copy uses): a storyboard is
  a brief a human finishes, so a forbidden-term hit is surfaced as `voice_warnings`, not
  auto-rewritten. (Rationale: the deliverable is edited by a human before it's used; a
  regurgitate loop over a multi-field shot list is not worth the tokens for a brief.)

## Models — `models/social.py` (additions)

`SocialStoryboardRequest` (`platform`, `source_type`/`source_id`/`url`/`text`, `angle`, `tone`,
`format='reel'`, `include_thumbnail: bool=False`), `SocialStoryboardShot`,
`SocialStoryboardResponse` (`extra='ignore'`, mirrors `SocialDraftResponse`).

## API — `routers/social.py` (additions, all `require_staff` for writes / `require_auth` reads)

| Route | Purpose |
|---|---|
| `POST /clients/{id}/social/storyboard` | generate a storyboard (freeze-gated via `assert_not_frozen` — it MAY generate a paid thumbnail) |
| `GET /clients/{id}/social/storyboards` | list a client's storyboards |
| `GET /social/storyboards/{id}` | one storyboard |
| `PATCH /social/storyboards/{id}` | edit title / storyboard / caption / hashtags |
| `DELETE /social/storyboards/{id}` | archive |
| `POST /social/storyboards/{id}/thumbnail` | generate + attach a thumbnail (reuses `image.generate_image`; freeze-gated + budget-metered) |

All gated on `social_publish._assert_enabled()` (module master gate), same as every social route.

## Reuse map (do NOT reinvent)

| Need | Reuse |
|---|---|
| Resolve a Source | `creator.load_source` (verbatim) |
| Client context + voice card + voice block | `creator.resolve_voice_context` (verbatim) |
| P1 competitor grounding | `competitor_research.render_competitor_signals_block` + `latest_signals_for_client` |
| Structured LLM output | `report_llm.run_forced_tool` (same as `propose_angles`) |
| Voice advisory | `gbp_posts_service.voice_forbidden_hits` |
| Thumbnail | `services/social/image.generate_image` (freeze-gated, fail-closed budget-metered, R2 store) |
| Persistence/CRUD shape | `fanout.list_drafts`/`get_draft`/`update_draft`/`delete_draft` |
| Freeze | `assert_not_frozen` in the generate + thumbnail routes |
| Frontend | a new **Storyboard** tab in `pages/SocialCompose.tsx` (Source picker → platform/format → generate → editable shot-list view) |

## Cost / budget

- **Storyboard text: not metered** (our own Anthropic key, exactly like `draft-copy` / `angles` —
  a few Sonnet cents). No `budget.reserve` on the text call.
- **Thumbnail: metered + freeze-gated** — reuses `image.generate_image`, which already reserves
  fail-closed against the per-client ceiling before the paid Gemini call. Opt-in
  (`include_thumbnail` / the explicit thumbnail route), so a text-only storyboard spends nothing.

## Autonomy (Q4 = "may propose") — NOT in this slice

The build-now surface is the **human Compose** storyboard path. The autonomy-propose seam (the
P4 loop surfacing a storyboard as a candidate) is a clearly-scoped later sub-slice — it would
add storyboard generation to the manager's `gather_candidates` as a `requires="approval"`
proposal (never auto-generate video, never auto-publish; there is no video to generate in slice
(a) anyway). Deferred deliberately to keep this slice tight and to keep P4 (which ships dark) a
layer, not a rewrite. Recorded here so it isn't lost.

## Frontend — `pages/SocialCompose.tsx` (a new tab)

A **Storyboard** tab: Source picker (reuses the existing Create-with-AI source controls) →
platform (IG Reel / FB Reel / YT Short) + optional angle/tone + an "include thumbnail" toggle →
**Generate storyboard** → an editable shot-list view (hook, per-shot visual/on-screen-text/
voiceover/duration, music, caption, hashtags, CTA) with Save + a thumbnail preview + a
storyboards list (open/edit/archive). `errorGuidance.ts` gets the new codes. eslint stays 0.

## Constraints

- Migration in `writer/supabase/migrations/`, applied live via the Supabase MCP. No
  `async_jobs` CHECK widen (no new job type).
- `platform-api` pytest + `ruff check .` on changed files; frontend `tsc -b` + eslint (keep
  `SocialCompose.tsx` at 0 problems). mypy: no new own-file errors. Never echo live secrets.
- Provider fields ONLY at the `postforme_adapter` edge (this slice adds none).

## Tests — `tests/test_social_storyboard.py`

Pure: `platform_video_guidance` per platform/format, `build_storyboard_prompt` (source + angle +
competitor block + voice block ordering; empty competitor block ⇒ byte-identical),
`sanitize_storyboard` (shot cap, type coercion, empty-drop, hook/≥1-shot guarantee, garbage
input). The impure `generate_storyboard` / CRUD are covered with a mocked LLM + a fake Supabase
(mirroring `test_social_fanout.py`).

## Config — `config.py` (additions)

`social_storyboard_model` (`claude-sonnet-5`, reuses the copy model) / `social_storyboard_max_tokens`
(2000 — a shot list is bigger than a caption) / `social_storyboard_max_shots` (12).

## Deployed-only / not-this-slice

A live thumbnail generation (sandbox egress-blocked from Gemini) — the thumbnail path reuses the
already-live `image.generate_image`, so it's the same deployed-only confidence as image gen. No
new vendor, no new external dependency. All the other module deployed-only items (PostForMe test
post, R2 CORS, live YouTube post, P1 research run, P4 autonomy loop) are unchanged and unrelated.
