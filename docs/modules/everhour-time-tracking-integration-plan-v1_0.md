# Everhour Time-Tracking Integration — Plan (v1.0)

**Authored:** 2026-08-28 · **Status:** **Design locked, BLOCKED on live API verification — no code written** · New suite integration — "Everhour"

> Read alongside **`docs/modules/everhour-time-tracking-integration-handoff.md`** (the prior
> session's handoff — decisions #1–#6, the payoff case, and the blocker are carried forward
> here verbatim) and **`docs/suite-architecture-and-roadmap-v1_0.md`** (decision log + shared
> infrastructure). This document follows the same template as the other module plans in
> `docs/modules/` — see `asana-task-integration-plan-v1_0.md`, which this integration sits
> right next to (same client, same roster, same scheduler) and deliberately mirrors in shape.

> **⚠️ Blocker, unresolved as of this writing.** The Everhour API docs
> (`developers.everhour.com`, `everhour.docs.apiary.io`) are egress-blocked in this sandbox —
> re-verified this session (`curl` to both, plus `api.everhour.com` itself, all three return
> `connect_rejected` / gateway 403 at the proxy, i.e. an organization policy denial, not a
> transient failure). **No httpx wrapper code should be written against guessed endpoint
> shapes.** Every endpoint referenced below is marked either from the handoff's "known facts
> (unverified)" or as an explicit **TBD** placeholder. See §11.

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

Whether the mirror runs **inline** (synchronous httpx call inside `create_task`, like the
notification emit) or **async** (a lightweight `async_jobs` job, closer to how the Asana
monthly job batches Asana calls) is a Phase 2 implementation call — inline is simpler and the
call volume is low (one task at a time, not a batch), but every `create_task` call-site
would then carry Everhour latency; async decouples that at the cost of a short window where
a task exists natively but has no Everhour counterpart yet (acceptable — time can't be logged
against it in that window anyway). **Lean inline, degrade to async only if Everhour create
latency proves to matter in practice** — flag for a decision at Phase 2, not now.

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

- `writer/platform-api/services/everhour_service.py` — thin async REST client (`X-Api-Key`
  header, `https://api.everhour.com` base) + pure helpers (payload shaping, id/seconds
  parsing). `is_configured()` gates every entry point. Pure helpers unit-tested with mocked
  HTTP (suite convention) — **the I/O methods themselves cannot be tested against a real
  response shape until §11 is resolved.**
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

1. **API key** — an Everhour account-level API key (Settings → Api in the Everhour web app,
   per ecosystem research — **unverified**, confirm once the docs/key route is open) →
   `EVERHOUR_API_KEY` on `PLATFORM`.
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

- **Phase 0 — BLOCKED.** Config gating (`everhour_enabled`, `everhour_api_key`) +
  `services/everhour_service.py` wrapper + `is_configured()`, **validated against a real
  key/response** before merge. Cannot start until §11 is resolved — this plan doc does not by
  itself unblock Phase 0.
- **Phase 1 — mapping/identity.** Migrations (`asana_team_members.everhour_user_id`,
  `clients.everhour_project_id`); Team-page Everhour user-link dropdown; client↔project
  mapping UI. No live Everhour calls required beyond a "does this key work" ping, so this
  phase *could* start once a key exists even before every endpoint shape is confirmed — but
  the ping itself needs §11's "which endpoint proves a key is valid" answered.
- **Phase 2 — task mirror.** Suite → Everhour task creation at every task-creation hook
  point (§3) + the one-time `everhour_task_id` backfill for existing tasks.
- **Phase 3 — time pull + rollups.** `time_entries` table + scheduled pull + `actual_hours`
  / per-client / per-member rollups (§4, §6).
- **Phase 4 — consumers.** Recipe Engine actual-margin read, PACE/workload wiring
  (`pm_signals.py`), and the frontend surfaces (task drawer, client Time card). This phase's
  exact formula changes (e.g. does Recipe Engine's margin math *switch* to actuals once
  available, or show both estimate- and actual-based margin side by side?) are a **separate
  decision to make at Phase 4**, not locked by this document — flagging so it isn't assumed
  later.

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
  confirm with the owner at Phase 3.
- **Billable vs non-billable** — `time_entries.billable` is captured in the schema (§6) from
  day one since it's presumably free on the same API response, but nothing *consumes* it in
  v1 (Recipe Engine margin math doesn't yet distinguish billable/non-billable hours). Defer
  the consuming logic to Phase 4.
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

## 11. Verification needed before Phase 0 (the blocker, itemized)

Everything below is **either unverified ecosystem-research folklore or an explicit gap** —
none of it should be hard-coded into `everhour_service.py` until confirmed against the real
API (docs or a live key). Restated from the handoff with the specific answer each phase needs:

1. **Auth** — base URL `https://api.everhour.com`, header `X-Api-Key: <key>` (per ecosystem
   research). Confirm the exact header name/casing and whether there's a lighter "whoami"
   endpoint to validate a key cheaply (`is_configured()` should ideally do more than check
   the string is non-empty).
2. **List team users** — endpoint + response shape (need at minimum: an id to store as
   `everhour_user_id`, a display name for the Team-page picker).
3. **Create a project / list projects** — can the suite create an Everhour project via the
   API for onboarding, or must a human create it in the Everhour UI and the suite only
   *reads* the id to store on `clients.everhour_project_id`? The handoff's "known facts" say
   "API-created internal projects support creating tasks directly" — confirm this is actually
   how client projects get created, or whether Phase 8's "provisioning" step 2 is manual.
4. **Create a task in a project** — request shape (name, project id, optional assignee?),
   response shape (the id to store as `tasks.everhour_task_id`).
5. **List team time / time records over a date range** — the report endpoint's request
   params (date range, project/task/user filters) and response shape: does each record carry
   a stable **time-record id** (the idempotency key `time_entries.everhour_record_id` needs),
   the task id, the user id, the project id, seconds/duration, a billable flag, and the entry
   date? Also: does a deleted/edited entry show up distinguishably in this report, or does an
   edit just change the same record id's value (needed for §10's deleted-entry question)?

**Next step:** the user provides one of — the domain(s) allow-listed for this sandbox, the
relevant endpoint docs pasted inline, or an Everhour API key to introspect `api.everhour.com`
live (confirmed this session that the proxy currently rejects `CONNECT` to it outright, so a
key alone doesn't unblock without an allow-list change too — flag that combination to the
user rather than assuming a key alone is sufficient).
