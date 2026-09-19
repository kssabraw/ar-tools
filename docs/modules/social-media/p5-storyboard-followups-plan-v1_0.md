# Social P5 — Video Storyboard follow-ups (slice a.1) — Plan v1.0

> **STATUS: BUILT** (2026-09-19, branch `claude/ar-tools-social-p5-video-8tndc2`) — all three
> follow-ups implemented; migration applied live; 268 social tests pass, ruff/tsc/eslint clean.
> See `HANDOFF.md` 2026-09-19 a.1 entry for the as-built readout.
>
> The **deferred follow-ups** to the merged Video Storyboard slice (a) (PR #1245,
> squash `b1eabef`), all three chosen by the owner via AskUserQuestion (2026-09-19):
> **(1) the Q4 autonomy-PROPOSE seam**, **(2) a Google-Doc export** of a storyboard,
> **(3) deeper shot-level UI editing**. No new vendor, no rendered/assembled video —
> these extend the merged brief-only slice. Grounded against `main` @ `1d2329e`
> (post-#1245/#1246). Build docs: `CLAUDE.md` / `HANDOFF.md` (this folder). Scope:
> `p5-video-scope-v1_0.md` (§"load-bearing fork" — phase (b)/(c) remain separate owner
> decisions; this plan touches NEITHER).

## Why these three, why now

Slice (a) shipped a shoot-ready storyboard *brief* (a `social_storyboards` row: hook +
shot list + music + caption + hashtags + CTA + optional thumbnail). Its own "Deferred"
list named exactly these three; the owner opted into all three as the next PR (path 1 —
buildable now, no new owner decision, low risk). Phase (b) (assembled video via ffmpeg)
and phase (c) (true AI video generation, new vendor) stay their own discuss-first rounds.

## (1) Autonomy-PROPOSE seam (owner Q4 = "may propose") — backend

The P4 Social Manager loop (`services/social/manager.py`) is cadence-driven: it keeps a
client's **draft queues** full and (at tier 2) auto-queues them. A **storyboard** is a
different deliverable (a video brief a human shoots) — the owner's Q4 decision is the loop
**may PROPOSE** a storyboard, **never** auto-generate video and **never** auto-publish.

**How it integrates (thin, additive):**
- A `requires="approval"` candidate deterministically classifies **`propose`**
  (`autonomy_policy.classify` rule 3) — never `auto`, whatever the tier/budget. So a
  storyboard candidate can NEVER auto-run. `propose_social_storyboard` is deliberately
  **NOT** added to `manager.AUTO_EXECUTE` (belt + suspenders).
- **DORA needs no changes.** `director/providers.prov_autonomy` already reads every
  `autonomy_runs` (domain='social') row and counts any `decisions[].outcome == "propose"`
  as a domain-tagged `proposed_unactioned` item → it surfaces in the
  `autonomy_proposed_unactioned` seam + the ops digest automatically. The seam just has to
  write a `{"action":"propose_social_storyboard","outcome":"propose", ...}` decision.
- **Trigger:** for each **active-cadence** platform (a schedule + a connected account) that
  is a `storyboard.STORYBOARD_PLATFORMS` member (instagram/facebook/youtube) AND has **no
  non-archived `social_storyboards` row created within a cooldown window**, propose ONE
  storyboard. Capped at `social_autonomy_storyboard_max_per_run` (default **1**) so a run
  proposes at most one video brief at a time (cycles platforms as cooldowns lapse). Once a
  human actually makes a storyboard for that platform, the cooldown suppresses re-proposing.
- **Spends nothing, generates nothing.** No LLM call, no thumbnail, no video. It records a
  proposal decision + folds a line into the run's digest. A human sees it (DORA seam / digest
  / the Social Manager activity view) and goes to the Storyboard tab to make it.

**Code:**
- Pure `manager.gather_storyboard_proposals(active_platforms, recent_platforms, max_proposals)`
  → `[{platform, format, reason}]` (video platforms not in the recent set, capped;
  `format`="short" for youtube else "reel"). Unit-tested.
- Impure `manager._platforms_with_recent_storyboard(client_id, cooldown_days)` → the set of
  platforms with a recent non-archived storyboard (best-effort → `set()` on error).
- In `run_social_autonomy_for_client`: after the active-platform gate, build the storyboard
  proposal decisions once (gated on `social_autonomy_storyboard_proposals`, default True),
  then thread them into **every** downstream exit's ledger + digest (the "queues full" noop
  exit now writes a ledger when there ARE storyboard proposals; the "proposed" and "ran"
  exits append them). `_emit_digest` gains a `storyboards=` count (emits when there are
  batches OR storyboards); `activity_item` counts `propose_social_storyboard` decisions +
  their platforms.
- Config: `social_autonomy_storyboard_proposals` (bool, True) /
  `social_autonomy_storyboard_cooldown_days` (14) / `social_autonomy_storyboard_max_per_run` (1).

**Guardrails held:** propose-only; ships dark behind the existing `social_autonomy_enabled`;
never in `AUTO_EXECUTE`; no video generated; no publish. `AUTO_EXECUTE`, the tiers, the
budget meter, freeze — all untouched.

## (2) Google-Doc export — backend + a button

A storyboard is a client/videographer deliverable; a Google Doc in the client's Drive folder
is how the suite hands off deliverables (reports, keyword-research PDFs). Reuse
`services/google_docs.py` wholesale.

- **Migration** `20260919160000_social_storyboard_doc_url.sql` (applied live): add
  `social_storyboards.doc_url text` (nullable) so the exported Doc is re-openable + a
  re-export is idempotent. **No `async_jobs` type** (export is a single async httpx call in a
  route — non-blocking; no CHECK widen).
- Pure `storyboard.render_storyboard_markdown(row) -> (title, markdown)` — a clean brief:
  title, platform/format/target-duration, hook, a numbered shot list (visual, on-screen text,
  voiceover, duration, b-roll), music, caption, hashtags, CTA, source, and any brand-voice
  advisory. Unit-tested.
- Impure `storyboard.export_storyboard_doc(client_id, storyboard_id, user_id)` — assert
  enabled, fetch the storyboard (client-scoped 404 guard), fetch the client's Drive folder
  fields, `resolve_drive_folder(client, "social_storyboard")` (422 `missing_google_drive_folder_id`
  when unset), `create_google_doc(..., content_format="markdown", dedupe_by_name=True)`, persist
  `doc_url` on the row, return `{doc_id, doc_url, reused}`.
- Route `POST /clients/{id}/social/storyboards/{storyboard_id}/export-doc` (`require_staff`).
  **Not freeze-gated** — an internal planning brief export spends nothing and publishes
  nothing to a platform (mirrors client-report Doc creation; freeze pauses content *output*).
- `SocialStoryboardResponse` gains `doc_url`; a new `SocialStoryboardExportResponse`
  (`doc_id`, `doc_url`, `reused`).
- Errors: `missing_google_drive_folder_id` (already in `errorGuidance`), plus a
  `social_storyboard_export_failed` entry.

## (3) Deeper shot-level UI editing — frontend only

The backend already supports it: `PATCH /social/storyboards/{id}` takes a full
`SocialStoryboardBody` (`update_storyboard(storyboard=…)` stores it verbatim). Today the card
only edits title/caption/hashtags/CTA and renders the shot list read-only. Make the shot list
editable in `StoryboardCard` (`SocialCompose.tsx`):
- Per-shot inputs (visual / on-screen text / voiceover / duration / b-roll), move up/down
  (reorder), delete, and "Add shot"; plus hook + music + target duration.
- On Save: drop empty-`visual` shots, renumber `n`, PATCH the full body. `eslint` stays 0.
- Add the **Export to Google Doc** button + a persistent **Open Doc** link when `doc_url` is set.

## Reuse map

| Need | Reuse |
|---|---|
| Propose classification | `autonomy_policy.classify` (`requires="approval"` → propose) |
| Proposal → DORA | `director/providers.prov_autonomy` (unchanged — counts domain='social' `propose` decisions) |
| Ledger / digest / activity | `manager._write_ledger` / `_emit_digest` / `activity_item` (extended) |
| Doc export | `google_docs.create_google_doc` + `resolve_drive_folder` |
| Storyboard CRUD | `storyboard.get_storyboard` / `update_storyboard` (already accept a full body) |
| Frontend edit | the existing `StoryboardCard` PATCH path |

## Tests

- `tests/test_social_storyboard.py` (extend): `render_storyboard_markdown` (fields present,
  empty-field omission, hashtag rendering); `export_storyboard_doc` (folder-missing 422, the
  `create_google_doc` call args, `doc_url` persisted, client-scoped 404) with a mocked
  `google_docs` + fake Supabase.
- `tests/test_social_manager.py` (extend): `gather_storyboard_proposals` (video-only,
  recent-set exclusion, cap, youtube→short); a run test asserting a storyboard proposal
  decision is recorded (and never `auto`).

## Constraints

- Migration in `writer/supabase/migrations/`, applied live via the Supabase MCP. No
  `async_jobs` CHECK widen (no new job type).
- `platform-api` pytest + `ruff check .` on changed files; frontend `tsc -b` + eslint (keep
  `SocialCompose.tsx` at 0 problems). mypy: no new own-file errors. Never echo live secrets.
- Provider fields ONLY at the `postforme_adapter` edge (this slice adds none).

## Deployed-only / not-this-slice

A live Doc export (sandbox egress-blocked from the Apps Script webhook) and a live thumbnail
render — same deployed-only confidence as the merged slice. Phase (b)/(c) video production +
cobalt remain separate owner decisions (scope doc). No new external dependency here.
