# Social P3 — Manager (Calendar / Cadence / Approval queue / Policy write path) — Scope v1.0

> Task 2 of the owner-set post-queue work (Pinterest ✅ → **P3 Manager**). Scoped
> against the live codebase + current main (post-Pinterest merge `e11f0b9`). Build
> docs: `CLAUDE.md` / `HANDOFF.md` (this folder). PRD: `../social-media-module-prd-v1_0.md`
> (P3 = §13; §9 Calendar/Cadence/approval/publish; §10 social_policy; §11 cost governance).
> Failure paths: `../social-media-failure-handling-v1_0.md`. Provider: ADR-0006 (PostForMe).

## The gap (what P3 fills)

The module has a **working publish spine** (compose → validate → freeze-gated
idempotent publish job → status reconcile) and the **full Creator** (AI copy /
image / angle fan-out → Drafts). What's missing is the **Manager** layer the PRD
§9 describes:

| Capability | Today | P3 |
|---|---|---|
| **One-off scheduling** | ✅ EXISTS — `social_posts.scheduled_at` + the per-tick `enqueue_due_social_posts()` sweep publishes when due (freeze-aware). A future post gets **no job at insert**; the sweep enqueues it at due time. | unchanged |
| **Recurrence / cadence** | ⬜ NONE. `social_policy.cadence` (jsonb) is a **dead column** (never read). No `social_post_schedules` table. | a cadence engine (fork Q1) |
| **Calendar** | ⬜ NONE. Scheduled posts appear only commingled + **read-only** in the flat "Recent posts" list. | a per-client cross-platform calendar |
| **Edit / cancel / reschedule** | ⬜ NONE. `social_posts.status` already allows `'cancelled'` (in the live CHECK) but **no code ever sets it**; no reschedule path. | wire cancel/reschedule/edit |
| **Approval queue** | ⬜ per-draft only (`publish_existing_draft`); no batch / multi-select. | batch review → publish (PACE "approve 1,3" pattern) |
| **`social_policy` write path** | ⬜ NONE. 2/9 content columns consumed (`monthly_ceiling_usd`, `image_prompt_template`); **no INSERT/UPDATE anywhere**. | a Policy/Settings write path (fork Q3) |

## Verified current state (main @ `e11f0b9`)

- **One-off sweep:** `services/social/publish.py::enqueue_due_social_posts()` → wired in
  `services/gsc_scheduler.py` as `social_scheduled_posts` (per-tick block, beside
  `gbp_scheduled_posts`). `run_publish_job` is the publisher. Freeze-aware
  (`is_frozen` skip + `social_publish` ∈ `FREEZE_GATED_JOB_TYPES`).
- **GBP cadence precedent to CLONE:** `gbp_posts_service.compute_next_run_at`
  (DST/IANA-correct weekly/biweekly/monthly, pure, unit-tested) + the
  `gbp_post_schedules` table + `enqueue_due_gbp_post_schedules` (self-clocked
  `next_run_at` advance; each tick recomputes from `now` with `prev` for biweekly
  phase). GBP's sweep enqueues a **generate** job (drafts + opt-in auto_publish).
- **Draft/publish reuse:** `fanout.publish_existing_draft(draft_id, account_id,
  scheduled_at)` is the approve→publish path; `update_draft` edits copy/media/board;
  `_assert_account_allowed` is the client-isolation gate (compose-tolerant,
  publish-authoritative).
- **`social_posts` schema:** `draft_id`, `account_id`, `scheduled_at` all **nullable**;
  status CHECK includes `cancelled` (live-verified). `social_drafts.status` is
  **free-text** (no CHECK) — a new draft status costs no migration.
- **`social_policy` schema:** `client_id` PK; columns `cadence` (jsonb),
  `allowed_topics`, `blocked_topics`, `tone_prefs`, `competitor_focus`,
  `monthly_ceiling_usd`, `autonomy_tier`, `image_prompt_template`,
  `text_prompt_template`. Only `monthly_ceiling_usd` (budget) + `image_prompt_template`
  (image gen) are read; the rest are inert.
- **Budget:** `services/social/budget.py` — **fail-CLOSED** `reserve` (copies
  `autonomy_budget.reserve`), `ceiling_for_client` reads `social_policy.monthly_ceiling_usd`.
- **Frontend:** `pages/SocialCompose.tsx` (~1700 lines) — tabs Compose / Create with AI /
  Drafts / Competitors; "Recent posts" list is read-only. `social_posts.status` renders
  via `StatusBadge`. eslint currently 0 problems (keep it there).

## Owner-confirmed decisions (2026-09-18)

_(To be filled from the AskUserQuestion round below — cadence behavior, phasing,
policy scope, default ceiling. See "Open owner decisions".)_

## In scope (all four sub-parts)

**(a) Cadence / recurrence engine** — a new **`social_post_schedules`** table (per
`(client, platform)`) + `enqueue_due_social_schedules()` wired into `gsc_scheduler`
(per-tick, beside `social_scheduled_posts`), cloning the GBP pattern
(`compute_next_run_at` reused verbatim + the self-clocked `next_run_at` advance). What a
due tick **does** is fork **Q1** (suggest slots / auto-fill / auto-generate). A
`GET/PUT/DELETE .../social/schedule` config surface (per platform).

**(b) Calendar + edit / cancel / reschedule** — a per-client cross-platform **Calendar**
view (scheduled + published + any planned slots) and, on a **scheduled** post:
- **cancel** → set `status='cancelled'` (already in the CHECK) + drop any pending
  `social_publish` job. Guarded: only a `scheduled` post with no active publish job
  (else 409 `social_post_publishing`).
- **reschedule** → change `scheduled_at` (must be future; reuses `_ensure_future_iso`).
- **edit** → update the post's draft copy/media (reuses `update_draft`).

**(c) Approval queue** — a batch-review surface over `ready` drafts: multi-select →
publish/schedule N drafts to their chosen accounts in one action (PACE's "approve 1,3").
Reuses `publish_existing_draft` per draft; a new `POST .../social/drafts/publish-batch`.
Per-draft failures are independent (partial success reported; PRD §4 failure spec).

**(d) `social_policy` write path** — `GET/PUT .../social/policy` + a Policy/Settings tab.
Which columns are editable in v1 is fork **Q3**; the default monthly ceiling is fork **Q4**.

## Out of scope (deferred to P4 / later — do not build here)

- **Auto-PUBLISH** of unattended content (PRD: top autonomy tier + explicit per-client
  opt-in only). P3 never publishes without a human, regardless of the Q1 choice.
- **The P4 autonomous orchestrator** (§10) — the headless "plan the period → dispatch
  the Creator" brain. Cadence in P3 is a schedule + a due-sweep, not a planner.
- **QA-agent approval gate** (§9, opt-in) — P4.
- **Analytics / performance read-back** (§9/§11) — P4.
- **Agent seams** (SerMaStr `social` provider, PACE tasks, DORA seams, §12) — P4.
- Changing the one-off `scheduled_at` publish path (works today).

## Data model + flow

### New table — `social_post_schedules` (the GBP clone, per client × platform)

```
social_post_schedules(
  id uuid pk,
  client_id uuid → clients(id) on delete cascade,
  platform text,                      -- one row per (client, platform)
  cadence text,                       -- disabled | weekly | biweekly | monthly
  day_of_week smallint,               -- 0=Mon (weekly/biweekly)
  day_of_month smallint,              -- 1..28 (monthly)
  hour_local smallint default 9,      -- in the client's tz (DST-correct via compute_next_run_at)
  is_active boolean default false,
  auto_fill boolean default false,    -- Q1 opt-in (only if Q1 ≠ suggest-only)
  next_run_at timestamptz,
  last_run_at timestamptz,
  created_by uuid, created_at, updated_at,
  unique (client_id, platform)
)
```
(Cadence config lives HERE, not on `social_policy.cadence` — Design X, GBP-literal.
`social_policy.cadence` is retired/left inert. Alternative "Design Y" — cadence in
`social_policy.cadence`, schedules table thin — is noted under Q1; Design X recommended.)

### Flow — the due tick (behavior = fork Q1)

```
schedule config (GET/PUT .../social/schedule)  ──►  social_post_schedules
                                                          │  (is_active, next_run_at)
                       enqueue_due_social_schedules()  ◄──┘  (per-tick sweep; advances next_run_at)
                                    │
        ┌───────────────────────────┼───────────────────────────┐
   Q1=suggest                  Q1=auto_fill                 Q1=auto_generate  (= P4-lite)
   materialize a "planned"     pull the oldest ready         enqueue a fan-out
   slot on the calendar +      approved draft for the        job → drafts land
   notify; human assigns a     platform into the slot        in the approval
   draft (→ scheduled_at)      (→ scheduled_at); human       queue for human
                               confirms before publish       approval (spends budget)
```

- A "planned slot" (Q1=suggest) is representable as a `social_posts` row with null
  `draft_id`/`account_id` + a new `status='planned'` (needs a one-line CHECK widen), so
  the Calendar is a single-table read. (Build detail; decided at build.)
- **Every path keeps publishing human-gated** — the existing one-off sweep publishes only
  a post a human put into `scheduled`. No auto-publish anywhere in P3.

## API surfaces (new)

| Route | Purpose |
|---|---|
| `GET/PUT/DELETE /clients/{id}/social/schedule` | per-platform cadence config (list/upsert/clear) |
| `GET /clients/{id}/social/calendar?from&to` | scheduled + published + planned, cross-platform |
| `POST /social/posts/{id}/cancel` | cancel a scheduled post (guarded) |
| `POST /social/posts/{id}/reschedule` | change `scheduled_at` (future) |
| `PATCH /social/posts/{id}` | edit the post's draft copy/media (scheduled only) |
| `POST /clients/{id}/social/drafts/publish-batch` | approve/publish/schedule N drafts at once |
| `GET/PUT /clients/{id}/social/policy` | Social Policy read/write (Q3 scope) |

## Reuse map (do NOT reinvent)

| Need | Reuse |
|---|---|
| DST-correct next-fire | `gbp_posts_service.compute_next_run_at` (import + reuse verbatim) |
| Self-clocked sweep shape | `gbp_posts_service.enqueue_due_gbp_post_schedules` (clone) |
| Scheduler wiring | `gsc_scheduler` per-tick block (add `social_schedules` beside `social_scheduled_posts`) |
| Publish a draft | `fanout.publish_existing_draft` (batch calls it per draft) |
| Edit draft content | `fanout.update_draft` |
| Client-tz | `gbp_timezone.resolve_client_timezone` |
| Budget ceiling | `budget.ceiling_for_client` / `resolve_ceiling` |
| Freeze | `assert_not_frozen` (routes) + `is_frozen` (sweep) — a schedule sweep is freeze-skipped |
| Notifications | `notifications.emit(dedupe_key=…)` (e.g. `social_slot_due`) |
| Frontend | new **Calendar** + **Settings** tabs in `SocialCompose.tsx`; Drafts tab gains multi-select |

## Constraints (from the task + ADR-0006)

- Provider fields ONLY at the `postforme_adapter` edge (unchanged — P3 adds no provider
  fields; it schedules/manages existing posts).
- Migrations in `writer/supabase/migrations/`, applied live via the Supabase MCP;
  widen any `async_jobs` CHECK **from the LIVE constraint** (captured this session).
- Reuse `async_jobs` + `job_worker`, `gsc_scheduler`, `notifications.emit`, freeze gating,
  the fail-CLOSED `budget`. Never echo live secrets.
- `platform-api` pytest + `ruff check .` on changed files; frontend `tsc -b` + eslint
  (keep `SocialCompose.tsx` at 0 problems). mypy: don't add new own-file errors.

## Phasing / effort (order = fork Q2)

Four reviewable slices on one branch (`claude/social-p3-manager`), one draft PR:
1. **(b) Calendar + edit/cancel/reschedule** — mostly management over existing rows; no
   new infra; immediate value. _Small–medium._
2. **(c) Approval queue** — batch-publish over the built draft path. _Small._
3. **(d) Policy write path** + **(a) Cadence engine** — cadence config IS policy, so these
   land together: the `social_post_schedules` table + `compute_next_run_at` clone + the
   sweep + the Policy/Schedule UI. _Medium (the one new table + sweep + the Q1 behavior)._

Migrations: `social_post_schedules` (new table + `social_schedule` job type IF Q1 =
auto_generate) + (if Q1 = suggest) a one-line `social_posts.status` CHECK widen for
`planned`. No provider changes.

## Open owner decisions (put to the owner BEFORE code)

- **Q1 — Cadence engine behavior** (the central data-flow fork; determines whether the
  sweep suggests, auto-fills, or auto-generates): **suggest-only** (recommended, cleanest
  P3/P4 line) / **auto-fill from the approved-draft backlog** (opt-in) / **auto-generate on
  cadence** (= P4-lite, spends budget). Also implicitly: cadence config home — Design X
  (`social_post_schedules`, GBP-literal, recommended) vs Design Y (`social_policy.cadence`).
- **Q2 — Phasing order** of (a)(b)(c)(d).
- **Q3 — `social_policy` scope** — which of the currently-dead columns to wire in v1
  (cadence is needed by (a); ceiling + prompt templates have consumers; autonomy_tier /
  topics / tone_prefs / competitor_focus are P4 planning inputs).
- **Q4 — Default per-client monthly ceiling** (b3; `social_monthly_ceiling_default_usd`
  is currently **$75**; cost model Base ≈ $45/client/mo).

## Deployed-only / not-P3 (flag, don't attempt)

A live PostForMe test post; the R2 CORS policy on `smm-media` (queue #4 prereq); first
live YouTube post; the first-live-Pin `board_ids` placement confirm; a live P1 research
run + Pinterest-actor confirm; #5 flash model id confirm. All sandbox-egress-blocked
(PostForMe / R2 / Apify / Gemini) — deployed-only, independent of this build.
