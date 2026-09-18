# Social P3 — Manager — Build Plan v1.0 (agreed scope)

> The **agreed** build plan for P3 (Manager). Supersedes the "Open owner decisions" in
> `p3-manager-scope-v1_0.md` (that doc's analysis still stands; this records the answers).
> Branch: `claude/social-p3-manager`. Draft PR. Owner decisions locked 2026-09-18 via
> AskUserQuestion.

## Owner decisions (locked 2026-09-18)

| # | Decision | Answer |
|---|---|---|
| **Q1** | Cadence tick behavior | **Auto-fill (drip approved queue)** — the sweep drips an *explicitly-queued, human-approved* draft on the rhythm; publishes unattended at slot time. **Opt-in per schedule** (`auto_fill`) **+ globally gated** (`social_auto_publish_enabled`, ships dark). When off / no queued draft → a **suggest-nudge** fallback (notify, no publish). |
| **Q2** | Phasing | **(b) Calendar + edit/cancel/reschedule → (c) Approval queue → (d) Policy write path + (a) Cadence engine** (management-first; the new table+sweep last). |
| **Q3** | `social_policy` scope | **Consumer fields only:** `monthly_ceiling_usd`, `image_prompt_template`, `text_prompt_template` (the last gets a small wire into the copy prompt), and cadence (via the schedules engine). **Defer** `autonomy_tier` / `allowed_topics` / `blocked_topics` / `tone_prefs` / `competitor_focus` to P4. |
| **Q4** | Default monthly ceiling | **$100** (`social_monthly_ceiling_default_usd` 75 → 100). |

## The auto-publish stance (Q1 — deliberate, informed)

The owner chose to build the drip, which **crosses the PRD's auto-publish line on purpose**.
Kept PRD-consistent and safe by three gates, all of which must hold for a draft to drip:

1. **`social_auto_publish_enabled`** (config, **default False** — module ships dark; owner
   flips `SOCIAL_AUTO_PUBLISH_ENABLED=true` on PLATFORM when ready). The global kill-switch.
2. **`social_post_schedules.auto_fill=true`** — the explicit **per-client, per-platform
   opt-in** the PRD requires.
3. **The draft is explicitly `queued`** — only a draft a human *deliberately enrolled* in the
   cadence queue drips. A merely-`ready` (generated) draft is NEVER auto-published. This is
   the safety line that keeps auto-fill from surprise-publishing anything the Creator made.

**P4 refinement (noted, not built):** auto_fill will additionally consult
`social_policy.autonomy_tier ≥ threshold` once P4 wires tiers. Until then the three gates
above are strictly more conservative than a tier check alone.

When auto_fill is **off** (or the global flag is off, or the queue is empty), the sweep does
**not** publish — it emits a nudge notification (`social_slot_due` / `social_slot_empty`,
deduped) and the Calendar shows the upcoming slot as a client-side **ghost** (computed from
cadence config). No unattended publish ever happens without all three gates.

## Data model

### New table — `social_post_schedules` (GBP-literal clone, per client × platform)

```sql
create table social_post_schedules (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients(id) on delete cascade,
  platform text not null,                 -- one row per (client, platform)
  account_id text,                        -- the connected account to drip to (auto_fill needs it)
  cadence text not null default 'disabled',   -- disabled | weekly | biweekly | monthly
  day_of_week smallint,                   -- 0=Mon (weekly/biweekly)
  day_of_month smallint,                  -- 1..28 (monthly)
  hour_local smallint not null default 9, -- client tz (DST-correct via compute_next_run_at)
  is_active boolean not null default false,
  auto_fill boolean not null default false,   -- Q1 opt-in (drip vs suggest-nudge)
  next_run_at timestamptz,
  last_run_at timestamptz,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, platform)
);
-- RLS on, service-role only (module tables are service-role only).
```
Cadence config lives HERE (Design X, GBP-literal). `social_policy.cadence` (the dead jsonb)
stays inert. **No `async_jobs` job type** — the drip reuses `publish_existing_draft` →
`social_publish`. **No `social_posts` status change** — no `planned` status; the calendar's
empty slots are client-side ghosts, not rows.

### `social_drafts.status` — add `queued` (free-text column, NO migration)

`queued` = "human-approved and enrolled in the cadence drip queue." Set from the approval
queue ("Add to queue"); cleared back to `ready` ("Remove from queue"). Auto-fill picks the
**oldest `queued`** draft for `(client, platform)`, publishes it via `publish_existing_draft`
(→ `published`).

## Change set (four slices, one branch, one draft PR)

### Slice (b) — Calendar + edit / cancel / reschedule  [no new table]
- `services/social/publish.py`:
  - `cancel_post(post_id)` → guard status `scheduled` (else 409 `social_post_not_cancellable`);
    if an active `social_publish` job exists → 409 `social_post_publishing`; set
    `status='cancelled'`. (Due sweep already queries `status='scheduled'`, so a cancelled
    post is skipped.)
  - `reschedule_post(post_id, scheduled_at)` → guard `scheduled`; `_ensure_future_iso`; update.
  - `edit_scheduled_post(post_id, copy?, image_urls?)` → guard `scheduled`; route to
    `fanout.update_draft(post.draft_id, …)` (a manual-compose post has a throwaway draft;
    editing it is fine and re-validated at publish).
  - `list_calendar(client_id, frm, to)` → `social_posts` filtered to the window
    (`scheduled_at` or `published_at` in range), for the Calendar view.
- `routers/social.py`: `POST /social/posts/{id}/cancel`, `POST /social/posts/{id}/reschedule`,
  `PATCH /social/posts/{id}`, `GET /clients/{id}/social/calendar?from&to`.
- `models/social.py`: `SocialRescheduleRequest`, `SocialEditPostRequest`.
- Frontend: a **Calendar** tab (month/week grid; scheduled + published + client-side ghost
  slots from schedules) with per-post cancel / reschedule / edit; the "Recent posts" list
  gains cancel/reschedule/edit affordances too.
- `errorGuidance.ts`: `social_post_not_cancellable`, `social_post_publishing`.

### Slice (c) — Approval queue (batch) + the cadence queue
- `services/social/fanout.py`:
  - `publish_drafts_batch(client_id, items)` → per `{draft_id, account_id, scheduled_at?}`
    call `publish_existing_draft`, collect independent per-item results (partial success).
  - `enqueue_draft(draft_id)` / `dequeue_draft(draft_id)` → `ready ↔ queued` (guarded to a
    reviewable, non-published state).
- `routers/social.py`: `POST /clients/{id}/social/drafts/publish-batch`,
  `POST /social/drafts/{id}/queue`, `POST /social/drafts/{id}/unqueue`.
- `models/social.py`: `SocialBatchPublishRequest`/`Item`/`Result`.
- Frontend: Drafts tab → multi-select checkboxes + a batch bar (publish now / schedule all /
  **add to cadence queue**); a `queued` badge + "Remove from queue".

### Slice (d)+(a) — Policy write path + Cadence engine
- **Migration** `2026091812XXXX_social_post_schedules.sql` — the table above (applied live).
- `services/social/policy.py` (new): `get_policy(client_id)` (defaults when absent),
  `upsert_policy(client_id, {monthly_ceiling_usd, image_prompt_template, text_prompt_template})`.
- `services/social/schedules.py` (new): `get_schedules`, `upsert_schedule`,
  `delete_schedule`, and **`enqueue_due_social_schedules()`** — the per-tick sweep:
  for each active, due (`next_run_at ≤ now`, `cadence ≠ disabled`) schedule, skip frozen
  clients; if `social_auto_publish_enabled AND auto_fill AND account_id` and an oldest
  `queued` draft exists → `publish_existing_draft` (drip) ; else emit `social_slot_due` /
  `social_slot_empty` (deduped). Advance `next_run_at` via `compute_next_run_at` (reused).
- `services/gsc_scheduler.py`: add `_safe("social_schedules", enqueue_due_social_schedules)`
  in the per-tick block, beside `social_scheduled_posts`.
- `services/social/creator.py`: wire `text_prompt_template` into `draft_platform_copy` as an
  optional steering block (empty → prompt byte-identical to today).
- `routers/social.py`: `GET/PUT /clients/{id}/social/policy`,
  `GET/PUT/DELETE /clients/{id}/social/schedule`.
- `models/social.py`: `SocialPolicy{Response,UpdateRequest}`, `SocialSchedule{Response,UpsertRequest}`.
- `config.py`: `social_monthly_ceiling_default_usd = 100.0`;
  `social_auto_publish_enabled: bool = False` (`SOCIAL_AUTO_PUBLISH_ENABLED`).
- Frontend: a **Settings** tab — Policy (monthly ceiling, image + text prompt templates) +
  per-platform Schedule (cadence, day, hour, account, active, auto-fill toggle with a clear
  "publishes approved queued drafts unattended" warning + the global-flag state).
- `errorGuidance.ts`: `social_schedule_invalid_cadence`, `social_auto_publish_disabled` (if surfaced).

## Reuse map

`compute_next_run_at` (verbatim) · `enqueue_due_gbp_post_schedules` (clone shape) ·
`gbp_timezone.resolve_client_timezone` · `fanout.publish_existing_draft` / `update_draft` ·
`publish._ensure_future_iso` / `_has_active_publish_job` / `_platform_spec` ·
`budget.reserve`/`ceiling_for_client` · `is_frozen` (sweep) / `assert_not_frozen` (routes) ·
`notifications.emit(dedupe_key=…)` · `gsc_scheduler` per-tick block.

## Tests (pure-first, mocked externals)

- `cancel_post`/`reschedule_post` guards (status gate, active-job 409, past-time 422).
- `publish_drafts_batch` partial success; `enqueue_draft`/`dequeue_draft` state gates.
- `enqueue_due_social_schedules` decision matrix: gates off → nudge; all gates on + queued
  draft → drip; auto_fill on but empty queue → `social_slot_empty`; frozen → skip;
  `next_run_at` advance (weekly/biweekly/monthly via the reused `compute_next_run_at`).
- `policy` get/upsert (consumer fields only); `text_prompt_template` wired (empty = no-op).
- ruff + mypy (no new own-file errors) on changed files; frontend `tsc -b` + eslint (0).

## Live / deployed-only (flag, don't attempt)

Auto-fill's unattended publish is verifiable only on the deployed path (sandbox
egress-blocked from PostForMe). Ship dark (`SOCIAL_AUTO_PUBLISH_ENABLED` unset). All the
existing deployed-only items (R2 CORS, live test post, YouTube post, Pin placement, P1 run)
are unchanged and independent of this build.
