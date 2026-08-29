# Everhour Time-Tracking Integration — Plan (v1.0)

**Authored:** 2026-08-28 · **Status:** **Phases 0–4 COMPLETE** (2026-08-29) — the
integration is fully built; still gated OFF (`everhour_enabled` default False) until the
owner sets `EVERHOUR_API_KEY` + flips the flag on `PLATFORM`. Phase 4 (consumers: Recipe
Engine actual-margin side-by-side, PACE per-member utilization, and the frontend surfaces)
is detailed in §9. Phase 0 =
config gating + `services/everhour_service.py` wrapper + pure helpers + unit tests, all
endpoint shapes verified against Everhour's live OpenAPI spec and validated end-to-end
against a real admin-role key (all four checks passed live). The four Phase-0 review bugs
were fixed in [#888](https://github.com/kssabraw/ar-tools/pull/888) (see §12). Phase 1 (merged
in [#890](https://github.com/kssabraw/ar-tools/pull/890)) = the `asana_team_members.everhour_user_id`
+ `clients.everhour_project_id` migration (applied live), the read-only pickers
(`routers/everhour.py`: `/everhour/status`,`/users`,`/projects`), roster + client-mapping
wiring, and the frontend (Team roster Everhour-user column + client-form Everhour-Project
field). Phase 2 = the **metadata-only task mirror** — migration `20260829130000` (applied
live: `tasks.everhour_task_id`/`_synced_at` + the `everhour_mirror` job type + a backfill
index), `services/everhour_sync.py` (the mirror + a one-time backfill), the mirror hooked
once into `task_service.create_task` (the single funnel every task-creation path passes
through), the `everhour_mirror` job worker dispatch, and the admin `POST /everhour/
backfill-mirror` endpoint. Gotcha #5 (the `int(everhour_user_id)` assignee cast) is resolved
in `everhour_sync.mirror_user_id`. Phase 3 = the **time pull + rollups**
(migration `20260829140000`, applied live: `tasks.actual_hours` + the
`time_entries` ledger + the `everhour_sync` job type), the daily whole-team pull
in `services/everhour_sync.py` (upsert-by-record-id → `tasks.actual_hours`
recompute), the `everhour_sync` job worker dispatch + `enqueue_due_everhour_sync`
in the shared scheduler's daily block, and the manual `POST /everhour/sync`
endpoint — built on PR [#896](https://github.com/kssabraw/ar-tools/pull/896).
Still gated OFF (`everhour_enabled` default False). **Phase 4 (consumers: Recipe
Engine actual-margin side-by-side + PACE utilization + frontend surfaces) is now
also complete** — see §9. · New suite integration — "Everhour"

> Read alongside **`docs/modules/everhour-time-tracking-integration-handoff.md`** (the prior
> session's handoff — decisions #1–#6, the payoff case, and the blocker are carried forward
> here verbatim) and **`docs/suite-architecture-and-roadmap-v1_0.md`** (decision log + shared
> infrastructure). This document follows the same template as the other module plans in
> `docs/modules/` — see `asana-task-integration-plan-v1_0.md`, which this integration sits
> right next to (same client, same roster, same scheduler) and deliberately mirrors in shape.

> **Blocker — RESOLVED 2026-08-28.** The sandbox's egress policy was `Trusted` (package
> registries only), which is why `developers.everhour.com` / `everhour.docs.apiary.io` /
> `api.everhour.com` all previously failed with `connect_rejected`. The owner switched the
> environment (`ar-tools`, `env_01CQmcKTLwnkKjFLW4ysuWWM`) to a **Custom** network policy and
> allow-listed all three domains. All endpoint shapes in this document are now taken directly
> from Everhour's **published OpenAPI spec** (`https://developers.everhour.com/openapi.json`,
> fetched 2026-08-28 and archived locally at fetch time) — confirmed, not ecosystem-research
> guesswork. See §11 for the full verified reference.

---

## 1. Why this exists (the decision trail)

Staff track time in **Everhour** (Chrome extension / manual entry on everhour.com) today.
Asana is being dropped as the task manager (see the native task-manager cutover, `CLAUDE.md`
→ "Native In-App Task Manager"), so Everhour can no longer ride "sync from Asana" — the
suite's native `tasks` board is now the only anchor available. Meanwhile:

- `tasks` has `est_hours` (an estimate) but **no actuals anywhere**. There is no way today to
  see estimate-vs-actual per deliverable.
- **Recipe Engine** (`services/recipe_engine.py`) computes each client's deployable monthly
  budget as `retainer × margin`, where margin is a **guessed** constant (0.34 / 0.50
  drop-month). Real logged hours would make margin *measured*.
- **PACE** capacity (`pm_signals.py`, `task_workload.py` / `task_monthly.py`'s workload math,
  `pm_assign.py`'s placement engine) only sees `est_hours`. There is no signal for actual
  per-member utilization.

We considered the same three end-states the Asana integration considered, and reached a
different answer for a different reason:

- **Build in-app time tracking (rejected):** staff already have a working habit in Everhour's
  extension; forcing a switch is a change-management cost for no product benefit — the suite
  doesn't need a stopwatch UI, it needs the *number*.
- **Two-way sync, Everhour as a task manager too (rejected — decision #1 below):** unlike
  Asana (which WAS the task manager being replaced), Everhour was never the task system of
  record. Making it bidirectional would re-introduce exactly the two-source-of-truth problem
  the native task manager was built to kill. Everhour becomes a **satellite that only reports
  hours** — never a target the suite reads task *state* from.
- **Pull-only time, thin one-way task mirror for the join key (adopted):** the suite creates
  a lightweight Everhour task shadow for each native task (name only, to establish a stable
  id) and reads time back against it. This is the same "thin write for a join key" shape as
  the Asana effort-field stamp (`asana_effort_field_gid`) — write the minimum needed to make
  a read line up, nothing more.

**Net:** one new integration, pull-only for time, with a narrow metadata-only mirror as
plumbing for per-task attribution.

---

## 2. Locked decisions (prior session + carried forward)

| # | Decision | Choice |
|---|---|---|
| 1 | Everhour's role | **Time layer only, never a task manager.** The native `tasks` table stays the sole source of truth for task state/assignment/due dates. Everhour is a satellite. |
| 2 | Direction | **Pull-only for time.** The suite reads hours from Everhour; it never writes time back. |
| 3 | Transport | **REST API** (`httpx`, `X-Api-Key` header), not the Everhour MCP. The MCP is a possible *later*, separate, conversational add-on (PACE/SerMaStr answering "how many hours on Acme?" in chat) — it cannot back a scheduled sync. |
| 4 | Attribution anchor | **Everhour project = suite client**, one project per client. Staff log time against Everhour-native projects/tasks; project→client mapping gives correct per-client hours regardless of which task within it is picked. |
| 5 | Granularity | **Per-task actuals**, not just client rollups — `actual_hours` must land on the native `tasks` row, not only a client total. |
| 6 | Consequence of #5 | **Thin one-way task mirror, suite → Everhour, metadata only** (name; assignee if cheaply available). The suite creates/mirrors each native task into its client's Everhour project and stores the returned Everhour task id on the native task, so time pulls back and joins cleanly. This is the *only* outbound write; it is not a status/due-date/description sync. Ad-hoc Everhour time with no native-task match still rolls up at client/member level (`task_id` nullable). |
| 7 | Scheduler | **Reuse the shared `gsc_scheduler`** in-process asyncio loop — no new infrastructure, matching every other scheduled tracker (GSC ingest, GBP metrics, DataForSEO rank, syndication scans, …). |
| 8 | Identity join | **Reuse the in-flight roster identity model**, not a new mapping table — `asana_team_members.id` is already the canonical roster-member uuid (Phase 2a/2b of the gid-unification migrations); `everhour_user_id` is a new column on that table, a peer of `profile_id` (the suite-login bridge). *(Correction to the handoff draft: `slack_user_id` is a peer concept but lives on `profiles`, not `asana_team_members` — see §6.)* |
| 9 | Gating | **`everhour_enabled` (default False)**, mirroring `asana_monthly_enabled`/`gbp_metrics_enabled`. Absent the API key → every feature is skipped-with-a-note, never an error. |

---

## 3. Feature A — Task mirror (suite → Everhour, write, metadata-only)

**Goal:** give every native task a stable Everhour counterpart so time logged against it in
Everhour joins back to the exact `tasks` row — without turning Everhour into a second place
task state lives.

**What gets mirrored:** task **name** (required for a usable Everhour task list) and,
*if the Everhour API supports it cheaply on create* (TBD, §11), the assignee (mapped via
`asana_team_members.everhour_user_id`). **Not mirrored:** status, due date, description,
category, completion, subtask structure. This is deliberately thinner than the Asana
integration's monthly automation (which set Status + category + section) — Everhour never
needs to *display* the suite's workflow, only to *exist* as a billing target.

**Flow (per task):**
1. Resolve the task's client → `clients.everhour_project_id`. No project mapped → skip
   (client not yet onboarded to Everhour; not an error).
2. If `tasks.everhour_task_id` is already set → no-op (idempotent; a task is mirrored once).
3. Create the task in the client's Everhour project (name only, or name+assignee — see §11
   for whether Everhour's task-create endpoint takes a project-scoped assignee at all, since
   Everhour assigns people to *projects*, not necessarily to individual tasks, in the
   ecosystem research so far).
4. Store the returned Everhour task id on `tasks.everhour_task_id` + stamp
   `tasks.everhour_synced_at`.

A failed mirror for one task must never abort a batch (collected into an `errors` list, same
pattern as `asana_monthly.generate_month_for_client`).

**Hook points (where new tasks are created today):**
- `services/task_monthly.py::generate_month_for_client` — every task the monthly generator
  creates (this is the bulk of recurring delivery work).
- `services/task_producers.py` — the auto-create hooks (`on_rank_alerts`, `on_maps_alerts`,
  `sync_action_plan_tasks`, `on_run_completed`, …). Producer-created tasks are exactly the
  kind of work whose actual hours matter for margin.
- **Manual task creation** (`task_service.create_task`, used by the Tasks page "+ add" and
  the API) — every net-new task, not only the automated ones.
- **One-time backfill** — a script/endpoint that walks existing open (non-deleted,
  non-completed) tasks with `everhour_task_id is null` and mirrors them, for the cutover
  moment (mirrors the Asana-import precedent in `services/task_import.py`).

Whether the mirror runs **inline** (synchronous httpx call inside `create_task`) or **async**
(a lightweight `async_jobs` job) was flagged as a Phase 2 call. **RESOLVED at Phase 2: async
(`everhour_mirror` job).** The deciding factor turned out not to be latency but the sync/async
boundary: `task_service.create_task` is a *sync* function called BOTH from threadpool request
handlers AND directly on the event loop (`run_task_month_job` awaits the sync
`generate_month_for_client`, which calls `create_task`), so an inline `asyncio.run` of
Everhour's async client would raise "cannot be called from a running event loop" in the
monthly-generation path. Enqueuing a job is a plain sync DB insert that works from anywhere,
decouples Everhour's latency from every call-site, and inherits the worker's retry/settle
machinery. The short window where a task exists natively but has no Everhour counterpart yet is
acceptable (time can't be logged against it in that window anyway).

**Hook simplification (built):** all three §3 creation points — manual creation, the monthly
generator, and every producer — funnel through `task_service.create_task`, so the mirror is
hooked **there once** (`everhour_sync.enqueue_mirror(created)`, best-effort, lazy import),
rather than separately in `task_monthly.py` / `task_producers.py`. Subtasks bypass it (they
insert via `create_subtasks`) and are deliberately never mirrored — they are checklist markers,
not billing targets. **Not freeze-gated:** the mirror creates nothing in the suite and no
client content (it mirrors an already-existing internal task's metadata outward), and internal
PM task creation keeps running during a freeze, so `everhour_mirror` is intentionally NOT in
`FREEZE_GATED_JOB_TYPES`.

---

## 4. Feature B — Time pull (Everhour → suite, read) + rollups

**Goal:** `actual_hours` on every native task, plus per-client and per-member totals, kept
current on a daily cadence with a re-pull window for corrected entries.

**Flow:**
1. Daily scheduler due-check (`services/gsc_scheduler.py::enqueue_due_everhour_sync`) enqueues
   one `everhour_sync` `async_jobs` job (whole-team pull — Everhour's team time report is
   presumably not per-client, see §11.4) when `everhour_enabled` and the last run isn't today.
2. The job pulls the team's time records over a **rolling re-pull window**
   (`everhour_sync_repull_days`, mirrors `gsc_ingest`'s trailing-days re-pull — staff edit past
   entries in Everhour, so a sync that only looked at "since last run" would miss corrections)
   — from `today - everhour_sync_repull_days` to `today`.
3. **Upsert** each time record into `time_entries` by the **Everhour time-record id** (unique
   constraint) — an update-in-place, not an append, so an edited entry's `seconds` changes in
   place rather than duplicating.
4. Join `everhour_task_id → tasks.everhour_task_id` (nullable — an ad-hoc Everhour task with
   no native match still gets a `time_entries` row, just no `task_id`) and
   `everhour_project_id → clients.everhour_project_id`; resolve `member_id` via
   `asana_team_members.everhour_user_id`.
5. **Rollup** (pure, unit-tested helpers): `sum(seconds) group by task_id` →
   `tasks.actual_hours`; `sum(seconds) group by client_id` (client "Time" card); `sum(seconds)
   group by member_id` (PACE workload signal). Rollups recompute from `time_entries` on every
   sync (idempotent — never accumulate deltas), same shape as
   `rank_materialize`/`gsc_ingest`'s rebuild-not-append pattern.

**Manual "Sync now"** — the same job, triggered synchronously from the client workspace or a
suite-level Everhour settings page, for the same reason `POST /clients/{id}/asana/generate-month`
exists alongside the scheduled run.

---

## 5. Architecture & files (fits existing suite patterns)

No new dependencies, no topology change. Everhour reached via `httpx`, key from env — same
shape as Asana/GSC/DataForSEO/GBP.

- `writer/platform-api/services/everhour_service.py` — **BUILT.** Thin async REST client
  (`X-Api-Key` header, `https://api.everhour.com` base: `get_current_user`/`verify_api_key`,
  `list_team_users`, `list_projects`/`get_project`/`create_project`, `create_task`,
  `list_team_time`) + pure helpers (`seconds_to_hours`, `build_task_payload`, `parse_user`,
  `parse_project`, `parse_time_record`, `is_valid_time_record`, `next_page`).
  `is_configured()` gates every entry point. Pure helpers unit-tested with mocked HTTP (suite
  convention) — 19 tests in `tests/test_everhour_service.py`, all green. `scripts/
  verify_everhour_api_key.py` (mirrors `scripts/verify_gbp_api_access.py`) is the live-key
  smoke test — validated twice: against a deliberately bad key (`GET /users/me` → `403`,
  exactly as documented) and, on 2026-08-29, against a **real admin-role key** — all four
  checks passed live (`/users/me`, `/team/users`, `/projects`, `/team/time`), no shape
  mismatches. Everhour issues **one key per user account** (no separate service-account
  concept). **Owner ruling (2026-08-29): keep using Kyle's personal admin key** — no
  dedicated non-human "Integration" Everhour user for now. (The trade-off is that the
  integration's access is tied to that person's account, so rotating/revoking his key would
  touch it; revisit if that becomes a problem.)
- `writer/platform-api/services/everhour_sync.py` — the task mirror (out) + the time pull (in)
  + rollups. Pure roll-up helpers (`rollup_by_task`/`rollup_by_client`/`rollup_by_member`)
  unit-tested; the two I/O flows are orchestration only, mocked in tests.
- `writer/platform-api/services/job_worker.py` — add `everhour_sync` job dispatch.
- `writer/platform-api/services/gsc_scheduler.py` — add `enqueue_due_everhour_sync` (daily
  due-check, same `should_run`/marker pattern as `enqueue_due_ingests`).
- `writer/platform-api/services/task_monthly.py` / `task_producers.py` / `task_service.py` —
  call the mirror at each task-creation point (§3).
- `writer/platform-api/routers/everhour.py` — status, client↔project mapping CRUD, "Sync now",
  read endpoints (task actuals, client time, member time).
- `writer/platform-api/models/everhour.py` — Pydantic schemas.
- `writer/platform-api/config.py` — new settings (§7).
- `writer/platform-api/services/recipe_engine.py` — `build_diagnosis` gains an actual-vs-
  estimated margin read once `actual_hours` exists (Phase 4 — see §9; the exact formula is a
  separate, later decision, not locked here).
- `writer/platform-api/services/pm_signals.py` / `task_workload.py` — actual-hours-aware
  utilization signal (Phase 4 — additive, doesn't replace the `est_hours`-based math that
  exists today, since not every client will be Everhour-onboarded at once).
- Frontend — task drawer actual-vs-estimate readout, a client-workspace "Time" card, a Team
  page Everhour-user-link dropdown next to the Slack/profile links.
- Migration(s) in `writer/supabase/migrations/` — see §6.

---

## 6. Data model

```
asana_team_members                        -- ALTER (existing table, id-keyed since Phase 2a)
  everhour_user_id  text                   (nullable; Everhour's user id — the join to the
                                             roster member. A peer of profile_id, NOT of
                                             slack_user_id, which lives on `profiles`.)

clients                                    -- ALTER
  everhour_project_id  text                (nullable; one Everhour project per client —
                                             mirrors clients.slack_channel_id's shape: a
                                             single external-id column on the client row,
                                             not a separate mapping table, since it's a strict
                                             1:1 unlike Asana's asana_client_projects table
                                             precedent — either shape works; this one avoids
                                             an extra join for the common read path.)

tasks                                      -- ALTER
  everhour_task_id    text                 (nullable; set once the mirror succeeds)
  everhour_synced_at  timestamptz          (nullable; last successful mirror attempt)
  actual_hours        numeric              (nullable; rolled up from time_entries, never
                                             hand-edited)

time_entries                               -- NEW
  id                   uuid PK default gen_random_uuid()
  everhour_record_id   text NOT NULL        (Everhour's own time-record id — the idempotency
                                              key; UNIQUE)
  client_id            uuid → clients(id) on delete cascade
  member_id            uuid → asana_team_members(id) on delete set null  (nullable — an
                                              Everhour user with no everhour_user_id link)
  task_id              uuid → tasks(id) on delete set null               (nullable — ad-hoc
                                              Everhour time with no native-task match)
  everhour_task_id     text                 (raw Everhour task id, kept even when task_id is
                                              null, so a later mirror/backfill can re-join it)
  entry_date           date NOT NULL
  seconds              integer NOT NULL
  billable             boolean
  synced_at            timestamptz not null default now()
  created_at           timestamptz not null default now()
```

- `time_entries` is append/update-by-`everhour_record_id`, never deleted on a normal sync (an
  entry Everhour itself deletes is a v1 gap — see §10).
- `tasks.actual_hours` is a **derived, recomputed** column (sum of `time_entries.seconds` for
  that `task_id` / 3600), same "materialized rollup, never hand-written" contract as
  `rank_keyword_metrics` or `gbp_metric_daily`'s growth figures — the sync job always
  recomputes it from `time_entries`, so a partial/failed sync can't leave it half-updated in
  a way that compounds.
- Indexes: `idx_time_entries_task` on `(task_id)`, `idx_time_entries_client_date` on
  `(client_id, entry_date)`, `idx_time_entries_member_date` on `(member_id, entry_date)` — the
  three rollup shapes (§4 step 5).
- RLS on, service-role only — the suite convention (no client-facing policy needed; this is
  an internal capacity/margin signal, not something exposed to a client login).

**Exact migration file(s)** are Phase 1 work (§9) — this section fixes the shape, not the SQL
text, since column types for `everhour_record_id`/`everhour_task_id`/`everhour_user_id`
(string vs numeric) depend on §11.

---

## 7. Config (`config.py`, on `PLATFORM`)

| Setting | Purpose |
|---|---|
| `everhour_api_key` (`EVERHOUR_API_KEY`) | `X-Api-Key` value. **Absent → the whole integration is skipped.** |
| `everhour_enabled` (default `False`) | Master feature gate — mirrors `asana_monthly_enabled`. |
| `everhour_sync_repull_days` (default TBD, likely `14` — mirrors `gsc_ingest`'s re-pull window) | How far back the daily pull re-checks for edited/late entries. |
| `everhour_mirror_enabled` (default `True`, sub-gate under `everhour_enabled`) | Lets the task-mirror (write) half be turned off independently of the time-pull (read) half, e.g. to validate reads before allowing any outbound writes during rollout. |

Secrets are set on the `PLATFORM` Railway service by the user — never handled in code/chat.

---

## 8. One-time Everhour provisioning (user-side, dashboard + env)

1. **API key** — an admin-role Everhour account's API key (Settings → Api in the Everhour web
   app) → `EVERHOUR_API_KEY` on `PLATFORM`. **Owner ruling (2026-08-29): Kyle's personal admin
   key** — no dedicated "Integration" user (see §5). Any admin-role key works; the mapping
   pickers stay dormant until `everhour_enabled` is flipped on.
2. **Per-client projects** — create (or identify existing) one Everhour project per suite
   client → set `clients.everhour_project_id` (editor ships with Phase 1/2 frontend).
3. **Team roster link** — for each `asana_team_members` row, set `everhour_user_id` (Team
   page dropdown, next to the existing Slack/profile links) so time attributes to the right
   person.
4. **Backfill** — run the one-time mirror backfill (§3) so existing open tasks get an
   Everhour counterpart before staff are asked to start logging against them.

---

## 9. Phasing

Restated from the handoff, unchanged, each shippable and gated on `everhour_enabled`:

- **Phase 0 — COMPLETE (2026-08-29).** Config gating (`everhour_enabled`, `everhour_api_key`,
  `everhour_mirror_enabled`, `everhour_sync_repull_days`, `everhour_sync_page_limit`) +
  `services/everhour_service.py` wrapper + `is_configured()` — all endpoint shapes verified
  against the live OpenAPI spec (§11), not guessed. Pure helpers unit-tested (19 passing
  tests). **Live-key validation done:** `scripts/verify_everhour_api_key.py` run against a
  real admin-role key — all four checks passed (`/users/me`, `/team/users`, `/projects`,
  `/team/time`). `everhour_enabled` is still `False` by default; nothing runs until it's set
  on `PLATFORM` alongside the real key.
- **Phase 1 — mapping/identity — COMPLETE (2026-08-29, merged #890).** Migration
  `20260829120000` (applied live) adds `asana_team_members.everhour_user_id` (peer of
  `profile_id`; the live schema was re-checked first — the table is `id`-PK / `gid`-nullable
  after the Phase-2a identity migration, so the column is a plain additive peer) and
  `clients.everhour_project_id` (mirrors `clients.slack_channel_id`'s single-external-id
  shape). Read-only pickers `routers/everhour.py` + `models/everhour.py` (`/everhour/status`,
  `/users`, `/projects`; degrade to empty when unconfigured). `everhour_user_id` threaded
  through the roster read/write/`partition_roster_write`; `everhour_project_id` on client
  read/create/update (empty-clears semantics). Frontend: the Team & capacity roster editor's
  "Everhour user" column + the client form's "Everhour Project" field (both only shown once
  Everhour is `configured`). Gated OFF until `everhour_enabled` is flipped.
- **Phase 2 — task mirror — COMPLETE (2026-08-29).** Migration `20260829130000` (applied live):
  `tasks.everhour_task_id` (text) + `tasks.everhour_synced_at` (timestamptz) + a partial index
  `idx_tasks_everhour_unmirrored` for the backfill scan + the `everhour_mirror` async job type
  (CHECK rebuilt from the live constraint). `services/everhour_sync.py`: pure `should_mirror`
  (top-level + client-scoped + unmirrored + live) and `mirror_user_id` (gotcha #5's TEXT→int
  assignee cast), `mirror_gate_open`, `enqueue_mirror` (deduped, best-effort), async `mirror_task`
  (resolve project + assignee → `build_task_payload` → `create_task` → stamp the join key),
  `run_mirror_job`, and `backfill_mirror`. Hooked once into `task_service.create_task` (the single
  funnel for manual / monthly / producer creation); `everhour_mirror` dispatch in `job_worker.py`;
  admin `POST /everhour/backfill-mirror`. `everhour_backfill_spacing_seconds` config for the
  backfill's rate stagger. Pure + flow tests in `tests/test_everhour_sync.py`. Gated OFF
  (`everhour_enabled` default False). `tasks.actual_hours` + `time_entries` stay Phase 3.
- **Phase 3 — time pull + rollups — COMPLETE (2026-08-29, PR
  [#896](https://github.com/kssabraw/ar-tools/pull/896)).** Migration
  `20260829140000` (applied live): `tasks.actual_hours` (a derived, recomputed
  rollup column) + the `time_entries` ledger (keyed by `everhour_record_id`;
  `client_id` NULLABLE per the §10 owner ruling, `task_id` nullable, three
  rollup indexes, RLS service-role only) + the `everhour_sync` async job type
  (CHECK rebuilt from the live constraint). `services/everhour_service.py`:
  `parse_time_record` now also surfaces `everhour_project_id` (the ad-hoc
  client-resolution fallback). `services/everhour_sync.py` (Phase 3 half): pure
  `rollup_by_task`/`_client`/`_member` + `resolve_time_entries` (native task →
  its client authoritatively, else project → client, else None) + `sync_window`;
  `run_everhour_sync` (paged pull → parse/validate → resolve maps →
  upsert-by-record-id → recompute `actual_hours` for touched tasks; a delete
  re-reads as `time: 0` and zeroes the task, no reconciliation pass — §11.9);
  `enqueue_everhour_sync`/`enqueue_due_everhour_sync` (one whole-team job,
  deduped) + `run_everhour_sync_job`. The READ gate is `everhour_enabled` only
  (the mirror sub-gate is write-only). `everhour_sync` dispatch in
  `job_worker.py`; `enqueue_due_everhour_sync` in the scheduler's daily block;
  manual `POST /everhour/sync` (admin) + `EverhourSyncResult`. Pure + flow tests
  in `tests/test_everhour_sync.py` (delete-to-zero + ad-hoc-no-task cases).
  Gated OFF. `tasks.actual_hours` **consumers** (Recipe Engine, PACE) + the read
  endpoints for task/client/member actuals stay Phase 4 (they back the frontend
  surfaces, so they land with them; the per-client/member rollup helpers are
  built + tested ready for them).
- **Phase 4 — consumers — COMPLETE (2026-08-29).** The three owner decisions (§10, confirmed
  before build): margin is shown **side-by-side** (never switched); billing is **captured now,
  not split** (`GET /team/time` now sends `opts_include_billing=1` so `time_entries.billable`
  populates from here on); ad-hoc/internal member time **counts** toward the utilization signal.
  All consumers are additive + gated on `everhour_enabled`, degrading to today's estimate-based
  behaviour when `actual_hours` is null (partial onboarding). Built:
  - **Read surface** (`services/everhour_sync.py` Phase-4 section + `routers/everhour.py`):
    pure `billable_split`/`build_client_time`/`utilization_hours` + windowed reads
    `client_time_summary` (→ `GET /clients/{id}/everhour/time`, the client "Time" card),
    `member_utilization` (team-wide {member_id: hours} over a window), and
    `client_month_actual_hours` (the Recipe Engine's this-month labor input). Per-task actuals
    already ride on `tasks.actual_hours` (returned by the existing `.select("*")` board/detail
    reads — no new endpoint). Per-member utilization is surfaced **through the workload report**,
    not a standalone endpoint (fewer surfaces; the Team page already reads it).
  - **Recipe Engine actual-margin** (`services/recipe_engine.py`): pure `actual_margin` +
    `build_actual_labor` (informational side-by-side read — measured labor margin only when the
    new optional `everhour_loaded_hourly_cost` is set, else hours-only, never an invented dollar).
    `build_diagnosis` folds it into `signals["actual_labor"]` best-effort — **never** touches
    `allocate`'s inputs or the conformance-tested allocation.
  - **PACE / workload** (`services/task_workload.py`): pure `attach_logged_hours` adds
    `logged_hours` + `utilization_pct` (vs pro-rated weekly capacity) to each member of
    `build_team_workload`, gated on `everhour_enabled`; the estimate-based `open_hours`/
    `overloaded` verdict is untouched. `pm_signals.build_board_digest` embeds this report, so
    PACE gets the utilization signal with no change to `pm_signals.py` itself.
  - **Frontend:** TaskDetail actual-vs-estimate readout under Est. hours; a client-workspace
    `EverhourTimeCard` (dark until enabled + logged time exists); a Team-page utilization line
    per member. New types in `lib/types.ts` (`actual_hours` on TaskItem, `EverhourClientTime`,
    `logged_hours`/`utilization_pct` on the workload member).
  - **Config:** `everhour_loaded_hourly_cost` (0.0 = disabled, no invented cost),
    `everhour_client_time_window_days` (30), `everhour_utilization_window_days` (7).
  - **No migration** — reads over the Phase-3 `time_entries` + `tasks.actual_hours` schema.
  - **Deferred to a later phase:** consuming `billable` in margin/reporting (captured, not split
    — owner ruling); a hardened loaded-cost model (the `everhour_loaded_hourly_cost` scalar is a
    placeholder until per-member cost rates exist).

---

## 10. Open questions / deferred

Carried from the handoff, still open:

- **Ad-hoc / internal Everhour time** (no native `task_id` match, possibly no
  `everhour_project_id` match either — internal/overhead time) — does it get surfaced as an
  "internal / overhead" bucket in the client/member rollups, or silently ignored? Affects
  whether `time_entries.client_id` should ever be null (an internal-time row with no project)
  and whether the member-utilization rollup (Phase 4/PACE) should count it toward capacity.
  **Leaning:** count it toward member utilization (a person's hours are a person's hours for
  capacity purposes) but exclude it from client/margin rollups (no client to bill it to) —
  confirm with the owner at Phase 3. **RESOLVED (owner, 2026-08-29): the leaning is
  confirmed** — ad-hoc/internal time counts toward member utilization but is excluded from
  client/margin rollups, so `time_entries.client_id` is NULLABLE (implemented in Phase 3's
  `resolve_time_entries` + `rollup_by_client`/`rollup_by_member`).
- **Billable vs non-billable** — `time_entries.billable` is captured in the schema (§6) from
  day one since it's free on the same API response. **RESOLVED (owner, 2026-08-29): capture
  now, don't split yet.** Phase 4 turned on `opts_include_billing=1` in `list_team_time` so the
  field actually populates (previously always None), and the client Time card shows the
  billable/non-billable/unknown split for legibility — but **nothing weights margin/reporting
  on it in v1** (the split-margin consuming logic stays deferred; capturing now avoids a re-pull
  when it lands).
- **Deleted Everhour entries** — a sync that only reads "records in the last N days" will
  miss an entry a staff member *deleted* outside that logic if the delete isn't itself
  represented as a record in the report (unclear without live docs — could be a hard delete
  with no trace, in which case a stale `time_entries` row lingers until it ages out of every
  future re-pull window's diff, silently over-counting hours). Needs the live API's actual
  behavior (§11.5) before deciding whether a periodic full reconciliation pass is needed on
  top of the rolling window.
- **Task-mirror assignee** — whether Everhour's task-create endpoint accepts a per-task
  assignee at all (some time trackers only assign at the *project* level and leave "who
  logged it" to whoever picks up the timer) — affects whether `everhour_user_id` mapping is
  needed before Phase 2 (task mirror) or only before Phase 3 (time pull, where it's needed
  regardless to resolve `member_id`). See §11.3.

---

## 11. Verified API reference (was the blocker — now resolved)

Pulled directly from `https://developers.everhour.com/openapi.json` (the live, published
OpenAPI 3 spec — 65 paths, fetched and archived 2026-08-28) plus the accompanying docs pages
(`authentication`, `pagination`, `rate-limits`, `errors`). Every shape below is confirmed
against that spec, and the auth/error behavior was additionally smoke-tested live (a bad key
against `GET /users/me` returned exactly the documented `403 {"code":403,"message":"Access
denied"}`). This supersedes the earlier "known facts (unverified)" section entirely.

**11.1 Auth.** Base URL `https://api.everhour.com`. Header `X-Api-Key: <key>` (an
`api_key` query param also works but the docs discourage it — query strings land in logs).
One key per Everhour user account; it inherits that user's role/permissions (`admin` sees
everything; a `member` key may see a narrower project/user set — **use an admin-role
account's key** for the integration so team-wide reads aren't silently scoped down). The
cheap "does this key work" call is **`GET /users/me`** (→ `CurrentUser`, a `User` plus
`timezone`/`apiKey`/`team`/etc.) — this is what `everhour_service.verify_api_key()` calls
and what `scripts/verify_everhour_api_key.py` runs first.

**11.2 List team users — `GET /team/users`.** Params: `query` (name/email filter), `limit`.
Response: array of `User` — `{id: number, name, headline, avatarUrl, role: admin|supervisor|
member|member_limited, status: active|invited|pending|removed, phone, capacity: number|null
(weekly capacity in SECONDS), avatarUrlLarge}`. **No email field** — the id + name are what
the roster-link picker needs; `everhour_user_id` is stored as **text** (`str(id)`) for
consistency with every other external-id column in this codebase (`gid` etc. are all text),
even though the API itself returns a number.

**11.3 Projects.** `GET /projects` (params: `query`, `limit`, `page`) lists everything the
key's account can see; the docs explicitly warn some endpoints (this one included) have **no
pagination support at all** — narrow with `query` rather than assuming paging works. `POST
/projects` (`ProjectRequestCreateRequest`: `name` + `type` (`board`|`list`, **required**),
optional `users: [userId,...]`, `client` (an **Everhour-native "Client" entity id** — a
separate concept from this suite's own `clients` table; do not conflate the two, and there is
no need to set it for our purposes), `privacy`, `changeProtected`, `isTemplate`) **does**
create a project via the API — confirms the handoff's "API-created projects" claim. Project
ids are opaque prefixed strings, not numeric — the OpenAPI examples show both `"as:1234567890"`
(Asana-synced) and `"ev:1234567890"` (native) shapes, so `clients.everhour_project_id` must be
**text**, never an integer column. **Open call still to make at Phase 1 (§10):** whether
client onboarding creates the Everhour project via `POST /projects` or a human creates it by
hand and only pastes the id — either works technically now that the shape is confirmed; this
is a workflow preference, not a capability gap.

**11.4 Create a task — `POST /projects/{project_id}/tasks`.** `TaskRequestCreateRequest`:
`name` (required) + optional `section`, `labels`, `status` (`open`|`closed`), `color`,
`dueOn`/`startOn` (`Y-m-d`), `description`, **`assignees: [{userId: number} | {accountId:
string}]`**, `tags`, `fields`, `cover`, `placeBefore`. Response is a `Task` — `{id:
"ev:9876543210"-shaped string, name, projects: [projectId,...], section, labels, position,
description, dueAt, status, time, estimate, attributes, metrics, unbillable}` — `id` is what
gets stored as `tasks.everhour_task_id`. Confirms Feature A's payload exactly:
`build_task_payload()` (built this session, §3/§5) sends only `name` + optionally
`assignees`/`description` — never `status`/`dueOn`/`section`, which the schema supports but
the metadata-only mirror deliberately never sets.

**11.5 Time records — `GET /team/time`.** Params: `from`/`to` (`Y-m-d`; **omitted = today
only**, not "all time" — the daily sync must always pass explicit dates), `limit` (default
example `10000`, **max `50000`**), `page`, `opts_include_billing` (`1` to include the
`billing` sub-object). Response: array of `TimeRecordExtended` (most rows) or
`TaskTimeBillable` (when billing is requested) — both share `{id: number (THE time-record
id — confirmed as the idempotency key `time_entries.everhour_record_id` needs), time: number
(seconds), user: number (user id), date: "Y-m-d", task: <full nested Task object, not just an
id — so the task's own id/name/projects ride along in the same call, no extra round-trip>,
comment}`; `TimeRecordExtended` additionally carries `isLocked`, `isInvoiced`, `history`,
`createdAt`, `warning`, `lockReasons`, `website`; `TaskTimeBillable` carries `billing:
{billable: boolean, rate, amount}` instead. **`billable` is therefore only known when the
request explicitly asked for it** — `everhour_service.parse_time_record()` (built this
session) returns `billable: None` (unknown) rather than `False` (confirmed non-billable) when
the caller didn't set `opts_include_billing=1`. Sibling scoped endpoints exist too —
`GET /tasks/{task_id}/time`, `GET /projects/{project_id}/time`, `GET /users/{user_id}/time` —
but the daily sync uses the **team-wide** `/team/time` per decision #4/#7 (one full pull,
not N per-project calls).

**11.6 Pagination.** Per-endpoint; `GET /team/time` uses bare `page`/`limit` with **no total-
count field and no response envelope** (responses are raw JSON arrays) — detect the last page
by `len(result) < limit` (`everhour_service.next_page()`, built this session). Some endpoints
(`GET /clients`, `GET /invoices`) return the full collection with no pagination at all —
`GET /projects` is in this "narrow with filters instead" category per §11.3.

**11.7 Rate limits.** **100 requests / 10 seconds per API key.** A `429` carries a
`Retry-After` header (seconds). The docs' own recommended handling is exponential backoff;
the daily sync (at most a handful of `GET /team/time` pages, per decision #7's re-pull
window) is nowhere near this ceiling in steady state — the **one-time task-mirror backfill**
(§3, potentially one `POST` per existing open task) is the flow that could realistically hit
it on a large backlog, so it needs backoff, not the daily pull.

**11.8 Errors.** Uniform `{code: number, message: string}` body on any non-2xx (`422` also
carries a per-field `errors` object). `403` = "missing/invalid key or insufficient
permission" — this is what a misconfigured/revoked key looks like at runtime, not just at
`is_configured()` time, so the sync job's error handling (Phase 3) should distinguish a `403`
(config problem — surface it, don't just log-and-retry) from a `429`/`5xx` (transient —
backoff and retry).

**11.9 Deleted time records (§10's open question, now answerable).** `DELETE /time/{time_id}`
is documented as *"Remove a time record by setting its duration to zero"* — i.e. Everhour
models a delete as **an update to `time: 0` on the same record id**, not a row disappearing
from the API's view. This resolves §10's concern cleanly: a rolling re-pull window (decision
#7) that re-reads a deleted record's id will see it come back with `time: 0`, and the upsert
naturally zeroes out that row's contribution to every rollup — **no separate reconciliation
pass is needed**; the existing upsert-by-id design already handles deletes correctly as long
as the deletion happened within the re-pull window. A delete older than the window is the one
residual gap (unchanged from §10) — acceptable given `everhour_sync_repull_days` is tunable.

**11.10 What's still genuinely open (not a docs gap — a decision):** whether the two-way
identity concern in §11.1 (which team member's key backs the integration) matters in
practice given a single agency Everhour account likely has one natural admin; and the §11.3
provisioning-workflow call. Neither blocks Phase 0/1 code.

---

## 12. Phase 0 code gotchas — adversarial re-review (bugs 1–4 fixed in #888; #5 open for Phase 2)

An adversarial re-review of the Phase 0 code (merged in PR #884) found five real defects, all
inert at the time (`everhour_enabled` is `False`, nothing called the wrapper). The owner's
ruling on this session's branch was "merge as-is, defer the fixes" — but a **parallel session
fixed bugs 1–4 the same day in [PR #888](https://github.com/kssabraw/ar-tools/pull/888)**
(commit `45fcc93`, 24 tests up from 19, each fix verified against its live repro), so they are
**already resolved on `main`**. **#5 remains open** — it is a Phase-2 boundary note, not a
current bug. The table records what was found and the resolution.

| # | Location | Defect | Status |
|---|---|---|---|
| 1 | `verify_api_key()` | Docstring says "Never raises," but only `httpx.HTTPError` was caught; `resp.json()` raises `json.JSONDecodeError` (a `ValueError`, not an `httpx.HTTPError`) on a malformed/non-JSON `200`, escaping uncaught. | ✅ **Fixed in #888** — now `except (httpx.HTTPError, ValueError)`. |
| 2 | `scripts/verify_everhour_api_key.py::main()` | No `try/except` around the `httpx` calls, so a transport-level failure (timeout, DNS, refused) crashed with a raw traceback instead of a clean `[FAIL]` line, and leaked the unclosed client. | ✅ **Fixed in #888** — a `_check()` helper catches `httpx.RequestError` + malformed JSON and prints one `[FAIL]`; `with httpx.Client(...)` always closes. |
| 3 | `get_project()` | Missing the `or {}` fallback its own docstring claims to mirror from `asana_service.get_project`; a JSON-`null` body made it return `None` where callers expect a dict. | ✅ **Fixed in #888** — `return await _get(...) or {}`. |
| 4 | `next_page()` | `returned_count < limit` → `TypeError` on `limit=None`; `limit=0` never terminated (returned `current_page + 1` forever). | ✅ **Fixed in #888** — guards `not limit or limit <= 0` first. |
| 5 (lower) | `build_task_payload()` assignee type vs `parse_user()` | `build_task_payload(assignee_user_id: int)` emits `{"userId": <int>}`, but `parse_user` stores `everhour_user_id` as **`str`** (`str(uid)`, like every external-id column). A Phase 2 caller that reads the stored `everhour_user_id` (str) and passes it straight in sends Everhour a **string** `userId`. | ✅ **Fixed in Phase 2.** `everhour_sync.mirror_user_id(str) -> int|None` casts the stored TEXT id to `int` at the mirror boundary (None on blank/non-numeric); the stored column stays `text`. Unit-tested in `tests/test_everhour_sync.py`. |

None of these change the Phase 0 contract or the locked decisions (§2); they are localized
correctness fixes to fold into the named phase's own PR.
