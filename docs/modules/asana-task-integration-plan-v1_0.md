# Asana Task Integration — Plan (v1.0)

**Authored:** 2026-06-29 · **Status:** **Phases 0–3 built** · Phase 4 (two-way sync) optional/ahead · **New suite integration — "Asana"**

> **Build status (2026-06-29).** **Phase 0 (scaffolding)** + **Phase 1 backend (monthly
> automation)** are implemented on branch `claude/asana-integration-options-cp3zul`
> (PR #170).
>
> *Phase 0:* `config.py` settings block; `asana_client_projects` migration (`20260629120000`);
> `services/asana_service.py` — async Asana REST client + pure helpers, graceful-degrading via
> `is_configured()`.
>
> *Phase 1 backend (design pivot — see decision #3):* the template source moved **from an
> Asana `Template` section to an app-defined per-client task template**. Added:
> `asana_client_task_templates` migration (`20260629130000`, also widens `async_jobs.job_type`
> for `asana_monthly`); `services/asana_monthly.py` (`generate_month_for_client` + enqueue +
> `run_asana_monthly_job` + `enqueue_due_asana_monthly`); `routers/asana.py` (status, mapping
> GET/PUT, template GET/PUT, workspace-users + category-options pickers, synchronous
> `generate-month`); `models/asana.py`; job-worker dispatch + scheduler monthly due-check +
> `main.py` registration; new `month`/picker helpers in `asana_service.py`. Tests:
> `tests/test_asana_service.py` (pure helpers) + `tests/test_asana_monthly.py` (create /
> idempotency / skip branches) — **all green**.
>
> *Phase 1 frontend (built):* `frontend/src/pages/AsanaTasks.tsx` — the per-client task
> template editor (add/reorder/remove rows; name + assignee + category, pickers populated from
> Asana; whole-list save), an Asana project-GID mapping field, and a **"Generate this month"**
> button surfacing the create/exists/skipped result. Routed at `/clients/:id/asana-tasks` with
> an **"Asana Tasks"** card in a new **Project Management** section of the client workspace.
> Typechecks + builds clean.
>
> *Phase 2 — Team Workload view (built):* `services/asana_workload.py`
> (`build_team_workload` — resolves names once, fetches each tracked member's open tasks
> concurrently best-effort, aggregates via `build_workload_report`); `GET /asana/workload`;
> `frontend/src/pages/TeamWorkload.tsx` (suite-level page: per-member open counts, overload
> flags, a per-day due-date chip row with same-day-stack highlighting) routed at `/workload`
> with a **"Workload"** nav item. Tests: `tests/test_asana_workload.py`. Typechecks + builds
> clean.
>
> *Phase 3 — effort-weighted workload + daily alert (built):* overload is computed from
> estimated **hours** vs each person's **weekly capacity**, not task counts. Migration
> `20260629140000` (`est_hours` on templates + `asana_team_members` table — team list +
> capacity, supersedes the env gid list). The monthly job stamps each task's `est_hours` into
> an **Asana number custom field** (`asana_effort_field_gid`); the workload read pulls it back
> off the task. `aggregate_member_workload`/`build_workload_report` rewritten to hours
> (same-day over daily capacity; backlog over N weeks). `asana_workload.run_workload_alert`
> emits one suite notification when anyone is overloaded; `gsc_scheduler` runs it daily.
> Frontend: an **Est. hrs** column in the template editor + a **Team & capacity** editor on
> the Workload page (pick members from Asana, set weekly hours), hours/capacity display.
> Tests green; typechecks + builds clean.
>
> **Still ahead (optional Phase 4):** two-way sync (Asana webhook → close rank alerts / mark
> Action Plan items done). Migrations are committed but **not yet applied to the live Supabase
> project** (pending plan approval). Everything degrades gracefully until the Asana token +
> workspace + effort field + team list + per-client mappings are provisioned.

> Read alongside **`docs/suite-architecture-and-roadmap-v1_0.md`** (decision log + shared
> infrastructure) and the **notifications service** section of `CLAUDE.md`. This document
> records the agreed scope, decisions, and phasing for connecting AR Tools to the team's
> existing Asana workspace. It follows the same template as the other module plans in
> `docs/modules/`.

---

## 1. Why this exists (the decision trail)

The team manages per-client delivery work in **Asana**, where each client has a project
laid out as **month sections** (`May 2026`, `June 2026`, `July 2026`, …). Each month holds
the same recurring set of delivery tasks (e.g. *Respect Mah Authoritay*, *Cloud Stack*,
*Map Embeds*, *40 Citations*, *GBP Blast*, *T1 Booster to citations*, *Blog Post
Scheduling*, *Service Page Silo*), each with an **assignee**, a **due date**, a **Status**
custom field (Not Started / In Progress / Complete), and a **category** custom field
(Link Building / GBP Automation / Content).

We considered three end-states and **chose to keep Asana as the system of record** and
integrate with it, rather than build an in-app task board:

- **Build an in-app board (rejected for now):** highest cost; would duplicate Asana's
  assignment / mobile / notification surfaces. The team is only lightly attached to Asana,
  but not enough to justify rebuilding it.
- **App ⇄ Slack ⇄ Asana triangle (partially adopted):** App → Slack already exists
  (notifications service). Slack ⇄ Asana is free via Asana's official Slack app (a
  dashboard install, no code). The only code is **App → Asana**.
- **Per-client-per-quarter projects (rejected):** clean buckets but a heavy project
  lifecycle (N new projects every quarter, a resolver that must create/find them). The
  team's existing **month-section-within-one-project** layout already solves the
  "organized by time" need without project proliferation — completed tasks fall out of
  Asana's active views, so a long-lived per-client project stays light.

**Net:** integrate with the **existing per-client project + month-section** layout. Two
features, one Asana token:

1. **Monthly section automation** (write) — auto-create next month's section + tasks.
2. **Team Workload** (read + alerts) — visibility into per-person load and same-day
   due-date stacking.

---

## 2. Locked decisions (this conversation)

| # | Decision | Choice |
|---|---|---|
| 1 | Integrate vs build in-app board | **Integrate** — Asana stays the system of record. |
| 2 | Project layout | **Existing** per-client project, **month sections** (`<Month YYYY>`). No per-quarter / per-month *projects*. |
| 3 | Monthly template source | **REVISED 2026-06-29 (supersedes the Asana `Template` section):** an **app-defined per-client task template** — each client has its own editable task list in AR Tools (`asana_client_task_templates`); the monthly job creates those tasks in Asana. Source of truth is the app. Granularity: **per-client list** (not shared packages). |
| 4 | Due dates on generated tasks | **None at creation.** Tasks are created with assignee + category + Status=Not Started; the team fills dates in. |
| 5 | Task fields | Each template row sets task **name** + **assignee** + **category** (assignee/category **picked in the app**, pickers populated from Asana — workspace users + the category field's enum options). Status set to **Not Started**, no due date. |
| 6 | Trigger | **Both** — auto on the 1st of the month (shared `gsc_scheduler` → `async_jobs`) **and** a manual "Generate next month" button per client. |
| 7 | Idempotency | If `<Month YYYY>` already exists in the project, the job is a **no-op** — auto + manual can't double up. |
| 8 | Workload feature mode | **View + proactive alerts** — a Team Workload view *and* a daily check that pings Slack/in-app via the **notifications service**. |
| 9 | Workload scope | **A defined team list** (configurable), not every workspace member. |
| 10 | Graceful degradation | Absent token / project mapping / team list → the relevant feature is **skipped with a note**, never an error. Matches GSC / Slack provisioning behavior. |
| 11 | Asana plan | **Starter** — no native Workload view and no native Rules/automation, so Feature B's view is built in full and the monthly spin-up is an API job (not native Asana automation). The Status + category custom fields already exist. |

---

## 3. Feature A — Monthly section automation (write)

**Goal:** each month, every mapped client project gets a new `<Month YYYY>` section populated
from the **client's app-defined task template**, so the team stops hand-copying tasks — and
the monthly deliverables for every client are defined/visible in one place in AR Tools.

**Flow (per client project):**
1. Resolve the client's Asana **project GID** (mapping table, §6).
2. Compute the target month label `<Month YYYY>` (e.g. `July 2026`).
3. List the project's sections; if one with that exact name exists → **no-op** (idempotent).
4. Read the client's **active template rows** from `asana_client_task_templates` (sort order).
5. Create the new `<Month YYYY>` section, **inserted before** the first non-month section
   (so it lands after the month group and above an "Untitled section" backlog;
   `month_insert_anchor_gid`).
6. For each template row, **create a task** in the new section with: the row's name, its
   assignee, its category enum value, **Status = Not Started**, **no `due_on`**. A failed
   task doesn't abort the rest (collected into `errors`).

**Asana API surface used:**
- `GET /projects/{gid}/sections` — find the insert anchor + idempotency check.
- `POST /projects/{gid}/sections` — create `<Month YYYY>`.
- `POST /tasks` with `memberships: [{project, section}]`, `assignee`, `custom_fields`
  (Status enum option = "Not Started", category enum option from the template row).
- `GET /workspaces/{gid}/users` + `GET /projects/{gid}/custom_field_settings` — populate the
  template editor's assignee + category pickers.

**Triggers:**
- **Auto:** the shared in-process scheduler (`services/gsc_scheduler.py`) runs
  `enqueue_due_asana_monthly` once per month on `asana_month_generate_day`, enqueuing one
  `asana_monthly` `async_jobs` job per mapped client (target month =
  `shift_months(today, asana_month_target_offset)`).
- **Manual:** `POST /clients/{id}/asana/generate-month` (optional `month`) — runs the same
  `generate_month_for_client` **synchronously** (one client, a handful of Asana calls) and
  returns the summary; surfaced as a **"Generate this month"** button in the client
  workspace (frontend = Phase 1 follow-up).

---

## 4. Feature B — Team Workload (read + alerts)

**Goal:** know we're not overloading a team member or stacking too many tasks on one day.

**Effort-weighted (decided 2026-06-29):** overload is computed from estimated **hours** vs
each person's **weekly capacity**, not raw task counts — counting tasks treats a 4-hour job
and a 15-minute job as equal. Effort lives on each task as an **Asana number custom field**
(`asana_effort_field_gid`): the monthly job stamps it from the template row's `est_hours`
(set once, rides every month), and the workload read pulls it back off the live task. Capacity
lives per-person in `asana_team_members.weekly_hours` (default for unset).

**Read view (suite-level — spans people and all client projects):**
- For each person in the **tracked team list** (`asana_team_members`), pull **open tasks across
  the workspace** (`GET /tasks?assignee={gid}&workspace={gid}&completed_since=now`, with
  `opt_fields=name,due_on,completed,custom_fields.gid,custom_fields.number_value`).
- Aggregate into per-person **open hours** (effort field, else `default_task_hours`) and a
  **due-hours-per-day** distribution.
- **Overload flags:** a single day's due hours over **daily capacity** (`weekly_hours /
  workdays`), or open backlog over `backlog_weeks` of capacity (e.g. "9h due Jul 9 over
  6h/day").
- A dedicated **"Workload"** nav page; read-only, displays Asana names + a Team & capacity
  editor. Pulled on demand.

**Proactive alerts:**
- A **daily** scheduler due-check (`gsc_scheduler` → `asana_workload.run_workload_alert`) runs
  the same aggregation and, when anyone is over capacity, calls
  `services/notifications.emit(client_id=None, kind="asana_workload", …)` → in-app feed + Slack
  (email when provisioned). Reuses the existing `notification_dispatch` pipeline; no new infra.

**Note on creation-time stacking:** because Feature A creates tasks **without due dates**,
there is no due-date clustering to guard against *at creation*. Workload is therefore an
ongoing **monitoring** concern (view + daily alerts), which is what catches same-day
stacking once the team fills dates in.

**Native-Asana caveat — resolved (2026-06-29):** Asana's native **Workload** view is an
**Advanced/Enterprise** feature. The team is on the **Starter** plan, which does **not**
include it — so there is no native equivalent to lean on, and Feature B's read-view is built
**in full**. (Starter also lacks custom Rules/automation, confirming the monthly spin-up must
be the API job, not native Asana automation; and the **Status** + **category** custom fields
the integration reads/writes already exist on the team's projects, so no field creation is
needed.)

---

## 5. Architecture & files (fits existing suite patterns)

All on the current stack — **no new dependencies, no topology change.** Asana is reached via
`httpx` (the suite's async HTTP client), token from env.

- `writer/platform-api/services/asana_service.py` — async Asana REST client + pure helpers
  (month-label compute, template→tasks transform, workload aggregation, overload detection).
  Pure helpers unit-tested with mocked HTTP (suite convention).
- `writer/platform-api/services/job_worker.py` — add `asana_monthly` (+ `asana_workload_alert`)
  job handlers.
- `writer/platform-api/services/gsc_scheduler.py` — add `enqueue_due_asana_monthly`
  (month-start) and `enqueue_due_asana_workload` (daily) due-checks.
- `writer/platform-api/routers/asana.py` — `POST /clients/{id}/asana/generate-month`,
  `GET /asana/workload`, client↔project mapping CRUD.
- `writer/platform-api/services/notifications.py` — reused as-is (new producer = workload).
- `writer/platform-api/config.py` — new settings (§7).
- Frontend — a client-workspace **"Generate next month"** affordance + a suite-level
  **Team Workload** view; dependency-free, consistent with existing components.
- Migration in `writer/supabase/migrations/` — the client↔project mapping table (§6).

---

## 6. Data model

Two tables (the rest lives in Asana / config):

```
asana_client_projects                     -- migration 20260629120000
  client_id    uuid  → clients(id)  PK     (one Asana project per client)
  project_gid  text
  created_at / updated_at  timestamptz

asana_client_task_templates               -- migration 20260629130000
  id                  uuid PK
  client_id           uuid → clients(id)
  name                text                 (task name)
  assignee_gid        text                 (Asana user gid, nullable)
  assignee_name       text                 (cached label for the editor)
  category_option_gid text                 (Asana enum-option gid, nullable)
  category_name       text                 (cached label for the editor)
  est_hours           numeric              (effort estimate; migration 20260629140000)
  sort_order          integer
  active              boolean
  created_at / updated_at  timestamptz

asana_team_members                        -- migration 20260629140000
  gid          text PK                      (Asana user gid — the tracked team)
  name         text
  weekly_hours numeric                      (capacity; null → config default)
  active       boolean
  created_at / updated_at  timestamptz
```

- `asana_client_projects`: one row per client (PK enforces uniqueness), set at onboarding.
- `asana_client_task_templates`: the client's monthly task list, edited in the app. The
  monthly job reads the **active** rows in `sort_order` and creates one Asana task each;
  `est_hours` is stamped into the Asana effort number field for the workload view.
- `asana_team_members`: the tracked team list + per-person weekly capacity (Feature B),
  edited in the Workload page. Supersedes the env `asana_team_member_gids` (kept as a
  fallback seed).
- The **custom-field GIDs** (Status / category / effort + the "Not Started" option) are
  workspace-level constants in `config.py` (§7).

---

## 7. Config (`config.py`, on `PLATFORM`)

| Setting | Purpose |
|---|---|
| `asana_token` (`ASANA_TOKEN`) | PAT / service-account token. **Absent → both features skipped.** |
| `asana_workspace_gid` | Workspace to scope task/user queries + the editor pickers. |
| `asana_month_generate_day` (default `1`) / `asana_month_target_offset` (default `0`) | When the scheduled monthly run fires, and which month it targets (0 = current). |
| `asana_status_field_gid` / `asana_status_not_started_option_gid` | Set Status = Not Started on new tasks. |
| `asana_category_field_gid` | The category custom field (its enum options populate the editor; the row's chosen option is stamped on each task). |
| `asana_effort_field_gid` | The **number** custom field the monthly job stamps with each task's `est_hours`; the workload read pulls it back off the task. |
| `asana_default_task_hours` (default `1.0`) | Hours assumed for a task with no estimate. |
| `asana_default_weekly_hours` (default `30`) | Capacity for a tracked member with no `weekly_hours` set. |
| `asana_workload_daily_workdays` (default `5`) / `asana_workload_backlog_weeks` (default `2`) | Daily capacity = weekly/workdays; backlog flag = open hours over N weeks of capacity. |
| `asana_team_member_gids` (list) | **Fallback** team-list seed only; the source of truth is `asana_team_members`. |
| `asana_monthly_enabled` / `asana_workload_enabled` | Feature toggles. |

Secrets are set on the `PLATFORM` Railway service by the user — never handled in code/chat.

---

## 8. One-time Asana provisioning (user-side, dashboard + env)

These are external inputs the integration can't invent; code is built to degrade gracefully
until they exist (so it ships safely before they're all in place). To go live:

1. **Token** — create an Asana PAT (or service account) → set `ASANA_TOKEN` on `PLATFORM`.
2. **Project mapping** — record each AR Tools client's Asana **project GID** (one
   `asana_client_projects` row per client; set in the workspace once the editor ships).
3. **Custom-field GIDs** — pull the Status field GID + "Not Started" option GID + the
   category field GID from the Asana API once the token exists; set in config.
4. **Per-client task templates** — fill in each client's monthly task list in the app
   editor (Phase 1 frontend). No Asana `Template` section is needed — the app is the source
   of truth.
5. **Team list** — the Asana user GIDs to track for workload → `asana_team_member_gids`.
6. *(Optional, no code)* install Asana's official **Slack app** for the Slack ⇄ Asana leg.

Provisioning steps will be written into `HANDOFF.md` (top section) alongside the Slack /
notifications setup.

---

## 9. Phasing

- **Phase 0 — scaffolding (built):** config seams, `asana_client_projects` migration,
  `asana_service` + pure helpers + tests. Graceful no-op when unprovisioned.
- **Phase 1 — monthly automation:**
  - *Backend (built):* app-defined per-client template (`asana_client_task_templates`),
    `generate_month_for_client`, `asana_monthly` job, scheduler monthly due-check, the
    template/mapping/picker routes + synchronous `generate-month`. Idempotent.
  - *Frontend (built):* `pages/AsanaTasks.tsx` — the per-client **task template editor**
    (assignee/category pickers from Asana) + project mapping + a **"Generate this month"**
    button; "Asana Tasks" workspace card under a new Project Management section.
- **Phase 2 — workload view (built):** `services/asana_workload.py` + `GET /asana/workload`
  + `pages/TeamWorkload.tsx` (suite-level "Workload" nav) — per-person aggregation, overload
  detection, per-day due chips with same-day-stack highlighting.
- **Phase 3 — effort-weighted workload + alerts (built):** `est_hours` per template task
  stamped into an Asana number field; `asana_team_members` (team + weekly capacity); hours-vs-
  capacity overload; `run_workload_alert` daily due-check → notifications service; frontend
  Est.-hrs column + Team & capacity editor.
- **Phase 4 (optional follow-up):** two-way sync (Asana webhook → close rank alerts / mark
  Action Plan items done); per-client Slack/Asana routing; `profiles ↔ Asana-user` mapping
  if the workload view needs to tie to suite identity.

---

## 10. Open questions / deferred

- **Two-way sync** (Asana "Done" → close app-side alerts) is **out of v1** — would need an
  Asana webhook endpoint mirroring `routers/slack_events.py`. Revisit if the team wants app
  state to react to Asana.
- **Per-client Asana projects** assumed; if a client ever needs splitting, the resolver is a
  single function and can change without touching the rest.
- **Effort/capacity weighting** (Asana "story points") is not modeled — workload is raw task
  counts in v1.
