# Everhour Time-Tracking Integration — Handoff

**Status:** Design agreed, not started. No code written. On branch
`claude/everhour-project-management-6h1iuj`.

**One-line goal:** Staff keep tracking time in **Everhour** (Chrome extension /
manual entry on everhour.com); that time flows **into the suite** and lands as
`actual_hours` per native task, per-client hours, and per-member utilization —
so the Recipe Engine gets *real* margin and PACE gets *real* capacity, instead
of the `est_hours` estimates they run on today.

---

## Decisions locked (owner, this session)

1. **Everhour is a time layer, not a task manager.** The suite's native task
   manager (Supabase `tasks`) stays the source of truth. Everhour becomes a
   satellite that only captures **hours**. Asana is being dropped, so Everhour
   can no longer "sync from Asana" — the native board is the anchor.

2. **Direction: pull-only for time.** The suite **reads** time from Everhour;
   it never writes time back. (One small exception below — task metadata.)

3. **Transport: REST API, not the MCP.** A scheduled backend sync must be a
   direct `httpx` wrapper (`X-Api-Key`, `https://api.everhour.com`), exactly
   like `gsc_ingest` / `dataforseo_*` / `gbp_posts_api`. The Everhour **MCP**
   is a conversational layer only — a *possible later* add-on so PACE/SerMaStr
   can answer "how many hours on Acme?" in chat. It cannot back a cron.

4. **Attribution anchor: Everhour project = suite client.** Once Asana is gone,
   staff log against **Everhour-native projects, one per client**. Project →
   client mapping gives correct per-client hours regardless of which task is
   picked.

5. **Granularity: per-task actuals (not just client rollups).** Owner wants
   `actual_hours` per native task, not only per-client totals.

6. **Consequence of #5 — a thin one-way task mirror (suite → Everhour).**
   Reliable per-task actuals need a stable join key. So the suite **creates /
   mirrors each native task into its client's Everhour project** and stores the
   returned Everhour task id on the native task. Staff track against those
   mirrored tasks; time pulls back and joins cleanly. **Time is still inbound
   only** — the only outbound is task metadata (name, maybe assignee), purely
   to establish the join key. Owner approved this ("Yes — mirror tasks to
   Everhour"). Ad-hoc Everhour tasks with no native match still roll up at
   client/member level (`task_id` nullable).

---

## Why it's worth building (the payoff)

- `tasks` has **`est_hours`** but **no actuals** anywhere. This closes that gap:
  estimate-vs-actual per deliverable.
- **Recipe Engine** (`services/recipe_engine.py`) computes deployable budget as
  `retainer × margin` off *estimated* effort. Real logged hours make margin
  measured, not guessed. **This is the strongest reason to do it.**
- **PACE** capacity (`pm_signals`, `task_workload`, `pm_assign`) only sees
  `est_hours` today. Actual utilization per member is a natural new signal.

---

## Architecture (plug into existing seams)

**Config + gating** — mirror `asana_service.is_configured()`:
- `settings.everhour_api_key`, `settings.everhour_enabled` (default **False**).
- Absent creds → feature skipped-with-note, never an error (GSC/Slack/Asana
  provisioning pattern).

**New code**
- `services/everhour_service.py` — thin async `httpx` client (`X-Api-Key`) +
  pure helpers (unit-tested; I/O mocked). Model on `asana_service.py`.
- `services/everhour_sync.py` — the task mirror (out) + the time pull (in) +
  rollups. Pure roll-up helpers unit-tested.
- `routers/everhour.py` — mapping config, "Sync now", read endpoints.
- `models/everhour.py` — Pydantic schemas.

**Identity & mapping** (reuse the in-flight roster identity — see
`20260828200000_task_assignee_identity_phase1.sql`):
- `asana_team_members.everhour_user_id` — **the** Everhour user → roster-member
  map. Right home: assignees already key on the roster uuid `id`; sits next to
  `profile_id` / `slack_user_id`. Editable on the Team page.
- `clients.everhour_project_id` — project = client anchor (admin-set or suite-
  provisioned).
- `tasks.everhour_task_id` (+ `tasks.everhour_synced_at`) — the task join key,
  set when the suite mirrors a task out. Idempotent via the existing
  `source` / `source_ref` backbone.
- `tasks.actual_hours` (numeric, nullable) — rolled up from `time_entries`.

**`time_entries` table** — one row per Everhour time record:
- idempotent by **Everhour's time-record id** (unique),
- `client_id`, `member_id` (roster), `date`, `seconds`, `everhour_task_id`,
  nullable native `task_id`, `billable`.

**Task mirror (suite → Everhour, metadata only)**
- Create each native task in its client's Everhour project; store the Everhour
  task id on the native task. **Not** a full status sync — Everhour just needs
  to exist as a target. Hook the points that already create tasks (monthly
  generation `task_monthly.py`, producers `task_producers.py`) + a one-time
  backfill of open tasks. **Freeze-gated / freeze rails inherited** (tasks
  belong to client rows).

**Time pull (Everhour → suite)**
- Daily job on the **shared `gsc_scheduler`** (`enqueue_due_everhour_sync`),
  new `async_jobs` type `everhour_sync`, + a manual "Sync now."
- **Rolling re-pull window** (staff edit past entries — same idea as GSC's
  re-pull days): pull the team-time report over the last N days, upsert by
  record id.
- Join `everhour_task_id → tasks.everhour_task_id` (native task) and
  `everhour_project_id → clients` (client). Roll up `actual_hours` per task +
  per-client + per-member.

**Frontend**
- Task drawer: actual-vs-estimate readout.
- Client workspace: a "Time" card (hours + real margin).
- Team page: Everhour user-link dropdown (next to Slack/profile links).

---

## Phasing (each shippable, all behind `everhour_enabled`)

0. Config + `everhour_service.py` wrapper + `is_configured()`; **validate
   against a real key.**
1. Mapping/identity migrations + Team-page Everhour user link + client↔project
   mapping UI.
2. Task mirror (suite → Everhour) + `everhour_task_id` backfill.
3. `time_entries` + scheduled pull + rollups (`actual_hours`, per-client,
   per-member).
4. Recipe Engine actual-margin + PACE/workload wiring + frontend surfaces.

---

## ⚠️ Blocker before writing real API code

**The Everhour API docs are egress-blocked in the sandbox** —
`developers.everhour.com` and the Apiary docs (`everhour.docs.apiary.io`) both
fail the network egress proxy. Do **not** guess endpoint shapes. Before
Phase 0 code, get **one** of:
- the domain(s) allow-listed, **or**
- the endpoint docs pasted in (need: **list team users**, **create project /
  list projects**, **create task in a project**, **list team time / time
  records over a date range**, and the **time-record id** field used for
  idempotency), **or**
- an Everhour **API key** to introspect `api.everhour.com` live (confirm the
  proxy can even reach it first).

Known facts (from ecosystem research, unverified against live docs):
- Base `https://api.everhour.com`, auth header `X-Api-Key: <key>`.
- Resources: projects, tasks, time records, timers, team users, reports (full
  CRUD). API-created **internal** projects support creating tasks directly
  (no Asana needed).
- Time records reference a project + optional task; task ids use Everhour's
  internal format for native tasks.

---

## Reference files (read these first next session)

- `docs/modules/in-app-task-manager-prd-v1_0.md` — native task manager authority.
- `docs/modules/project-manager-agent-plan-v1_0.md` — PACE (capacity consumer).
- `writer/platform-api/services/asana_service.py` — the wrapper pattern to mirror.
- `writer/supabase/migrations/20260711130000_native_task_manager.sql` — `tasks`
  schema (`est_hours`, `source`/`source_ref`; no actuals).
- `writer/supabase/migrations/20260828200000_task_assignee_identity_phase1.sql`
  — roster identity (`asana_team_members.id`/`profile_id`), where
  `everhour_user_id` belongs.
- `writer/platform-api/services/gsc_scheduler.py` — the shared scheduler to hook.
- `writer/platform-api/services/recipe_engine.py` — margin math actuals feed.
- `writer/platform-api/services/task_monthly.py` + `task_producers.py` — task
  creation points to hook the mirror into.

---

## Open questions for the owner

- Deliverable form: write the full module plan doc
  (`docs/modules/everhour-time-tracking-integration-plan-v1_0.md`) before code?
- Should ad-hoc / internal Everhour time (no native task, maybe no client) get
  an "internal / overhead" bucket, or be ignored?
- Billable vs non-billable: track the flag now, or defer?
