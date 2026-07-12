# In-App Task Manager — Product Requirements Document (v1.0)

**Status:** Proposed (greenfield module) · **Supersedes:** the Asana integration approach
(see `docs/modules/asana-task-integration-plan-v1_0.md`) · **Authored:** 2026-06-29

> ## 0. How to read this document
>
> **This PRD is self-contained.** It is written so an engineer or AI agent with **no prior
> context** can build the module from this document plus the codebase. It describes a new
> module that **replaces an external dependency (Asana)** with a **native, in-app
> task-management system** inside an existing internal product called **AR Tools**.
>
> Read §1–§5 for context and scope, §6–§14 for the build (data model, API, UI,
> automation, integration), §15 for the Asana migration, and §16 for the phased roadmap with
> acceptance criteria. §19 is an appendix of concrete real-world data (the exact statuses,
> categories, and recurring tasks the team uses today) — treat it as ground-truth
> requirements.

---

## 1. What AR Tools is (context)

**AR Tools** is an **internal agency suite** for an SEO/content marketing agency that serves
many small-business (SMB) clients. It is **not** a customer-facing SaaS — there is no billing,
signup, or marketing site; it is used by the agency's own team (staff + virtual assistants).

A team member picks a **client**, then works across SEO modules from one dashboard: generate
content (blog posts, local/service pages), research keywords, track organic + local-pack
rankings, track AI-assistant visibility, get alerted on ranking drops with recommended fixes,
and generate client reports. All modules share **one client roster, one database, and one
scheduler**.

**Tech stack (do not deviate without strong reason — these are locked suite decisions):**

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, **FastAPI** (service `platform-api`, deployed on Railway as `PLATFORM`) |
| HTTP client | `httpx` (async) |
| Database | **Supabase** (Postgres). Backend uses the **service-role key**; schema changes via SQL migrations in `writer/supabase/migrations/`. RLS is enabled on suite tables with **no client-facing policies** (service-role only). |
| Auth | Supabase JWT. FastAPI deps `require_auth` / `require_admin` (`middleware/auth.py`). Users live in `profiles` (roles `admin` / `team_member`). |
| Background jobs | A Supabase `async_jobs` table + an in-process asyncio worker (`services/job_worker.py`). **No Redis/Celery.** |
| Scheduler | A single in-process asyncio loop (`services/gsc_scheduler.py`) that enqueues due jobs. Reuse it; do not add new schedulers. |
| Notifications | A shared service `services/notifications.py::emit(client_id, kind, title, summary, severity, payload)` → writes an in-app feed row **and** enqueues a `notification_dispatch` job that delivers **email (SMTP) + Slack** best-effort. Reuse this for all task notifications. |
| Frontend | **React + Vite + TypeScript**, in `frontend/`, deployed to **Netlify**. State via **TanStack Query**. API via `frontend/src/lib/api.ts` (`api.get/post/put/patch/delete`). Auth token from Supabase session. |
| File storage | Supabase Storage buckets. |
| Realtime | None today (UI polls). Supabase Realtime is available if needed (see §6.10). |

**Backend code layout:** `writer/platform-api/` → `main.py` (registers routers), `config.py`
(env via pydantic-settings), `routers/` (one file per resource), `services/` (business logic),
`models/` (Pydantic schemas), `middleware/auth.py`, `db/supabase_client.py` (`get_supabase()`).

---

## 2. Background & motivation (why this module exists)

The agency runs all client **delivery work** (the monthly SEO tasks executed for each client)
in **Asana**. AR Tools currently **integrates** with Asana (an integration was built first —
see §3). The team has now decided to **replace Asana with a native task manager inside AR
Tools**, driven by three goals:

1. **Consolidation / one tool** — eliminate context-switching between AR Tools (content, ranks,
   reports) and Asana (task execution). The team and VAs should work in one place.
2. **Cost** — drop the Asana subscription.
3. **Deep auto-integration** — tasks that **auto-create and auto-close** from the rest of the
   suite (a ranking drop opens a "diagnose & fix" task; a content run completing closes its
   task; the Action Plan's recommendations become assignable tasks). Asana cannot do this
   natively; a native system can, because tasks live in the same database as everything else.

This reverses an earlier "integrate, don't build" decision. The trade-off is understood: this
is the **largest module in the suite** — a real task-management product with a daily-driver UI,
collaboration, notifications, mobile, and a data migration. It must be built **in phases**,
**run in parallel with Asana** during transition, and only cut over once at parity for the
team's actual workflow.

---

## 3. What already exists to reuse (the Asana integration)

An Asana integration already shipped (`docs/modules/asana-task-integration-plan-v1_0.md`,
backend in `writer/platform-api/services/asana_*.py` + `routers/asana.py`, frontend
`pages/AsanaTasks.tsx`, `pages/TeamWorkload.tsx`, `pages/TaskLibrary.tsx`). **Most of its
"brains" transfer directly** to the native system — it is the orchestration layer, and only
its *write target* changes (from the Asana REST API to our own tables). Reuse:

- **Per-client monthly task templates** (`asana_client_task_templates`): each client's
  recurring monthly task set (name + assignee + category + est_hours + auto-assign flag).
- **Task Library** (`asana_task_library`): a **global** catalog of standard tasks → default
  hours + default category, keyed by task name. Already seeded with the real task set.
- **Capacity-aware auto-distribution** (`asana_service.distribute_tasks`): spreads
  "auto-assign" tasks across an eligible team subset by **remaining capacity** (weekly hours −
  current open hours, weighted by est. hours; greedy, heaviest-first).
- **Team & capacity** (`asana_team_members`): tracked team members + weekly-hour capacity.
- **Workload engine** (`asana_service.aggregate_member_workload` / `build_workload_report`):
  per-person open-hours vs capacity, same-day due clustering, overload flags + a daily alert.
- **Monthly generation** (`asana_monthly.generate_month_for_client`): create a month section +
  populate it from the template, idempotently, on the 1st (scheduler) or on demand.

These become the native system's automation, **repointed** to the new `tasks` tables instead
of calling Asana. The Asana REST client also becomes the **migration importer** (§15).

---

## 4. Goals, non-goals, success metrics

**Goals (v1):**
- A native task system the agency team uses **daily** to execute client delivery work, at
  parity with how they use Asana **today** (not at parity with all of Asana).
- Recurring **monthly** task generation per client, with subtask checklists, assignees, due
  dates, statuses, and categories — preserving the current workflow.
- **Capacity-aware** auto-distribution + a workload view (reuse).
- **Collaboration**: comments, @mentions, attachments, activity history.
- **Notifications** (in-app + Slack + email) for assignment, due-soon, @mention, overload.
- **Deep suite integration**: auto-create/auto-close tasks from suite signals.
- **Mobile-usable** (responsive/PWA) for VAs.
- A clean **migration** off Asana with a parallel-run safety period.

**Non-goals (v1):**
- Full Asana feature parity (timeline/Gantt dependencies, portfolios, goals, forms, rules
  builder, proofing/annotations, advanced reporting dashboards).
- A public/client-facing portal (clients do not log in). *(Read-only client task views are a
  later possibility, explicitly out of v1.)*
- Native mobile apps (iOS/Android). v1 mobile = responsive web / installable PWA.
- Time tracking (actual hours logged). v1 uses **estimated** hours only.

**Success metrics:**
- The team runs a full month of client delivery **entirely in AR Tools**, with Asana read-only.
- 100% of recurring monthly tasks auto-generated with correct subtasks/assignees/categories.
- ≥1 suite signal (ranking drop or content run) auto-creates/closes a task in production.
- Asana subscription cancelled after a successful parallel-run cycle.

---

## 5. Glossary

- **Client** — an SMB the agency serves; the existing `clients` table. A client is the primary
  grouping ("board") for tasks. Some tasks are **internal** (no client).
- **Task** — a unit of work. May have **subtasks** (modeled as tasks with a parent).
- **Subtask** — a checklist item under a parent task (a task with `parent_task_id` set).
- **Section** — a grouping of tasks within a client, typically a **month** (e.g. "July 2026"),
  plus a "Backlog" and arbitrary custom sections.
- **Status** — a configurable workflow state (e.g. Not Started → In Progress → … → Complete).
- **Category** — a configurable label on a task (the team calls this "Service Type":
  Content / Link Building / GBP Authority / Strategy). Generalizes to **custom fields** later.
- **Library task** — a standard task definition in the global **Task Library** (name + default
  hours + default category + default subtask checklist).
- **Template** — a client's per-month recurring task set (which library tasks, who, etc.).
- **Capacity** — a team member's weekly available hours.
- **Auto-distribute** — a template row with no fixed assignee; the monthly job assigns it to
  the eligible team member with the most remaining capacity.

---

## 6. Functional requirements

### 6.1 Tasks (core)
A task has: name, optional rich-text description, client (nullable for internal), section,
optional parent task (for subtasks), assignee (a `profiles` user), status, category, due date,
optional start date, estimated hours, completed flag/timestamp, sort order, source (manual or a
suite producer), and audit fields. Users can: create, edit any field, delete (soft-delete →
"Trash", restorable), duplicate (with or without subtasks), move between sections/clients,
reorder, and mark complete.

### 6.2 Subtasks
A task can have an ordered **checklist of subtasks**. Subtasks are tasks with `parent_task_id`
set; they have at minimum a name, assignee (optional, defaults to parent's), completed flag,
and sort order. Completing all subtasks does **not** auto-complete the parent (surface progress
"3/5" instead). Subtasks render inline in the task detail and as a count + progress on the card.

### 6.3 Statuses (configurable)
A configurable, ordered set of statuses with a label, color, and a coarse **category**
(`not_started` | `in_progress` | `blocked` | `done`). Seed with the team's real set (§19.2).
The board's columns can be **grouped by status**. Exactly one status per task. Moving a card
between status columns updates the status.

### 6.4 Categories / "Service Type" (configurable; generalizes to custom fields)
v1: a single configurable enum field called **Service Type** (seed values in §19.3), set per
task, used for filtering/coloring and reporting. v2 (out of scope here): a general custom-field
system (enum / number / text / date / person) — design the table so this is a clean extension
(see §7).

### 6.5 Sections & month grouping
Tasks within a client are grouped into **sections**. The dominant grouping is **monthly** —
the recurring workflow produces a "`<Month YYYY>`" section per month per client. Also support a
**Backlog** section and arbitrary custom sections. Board/list views can group by **section** or
by **status**. A new month section is created by the monthly automation (§6.8) or manually.

### 6.6 Views
- **Board (Kanban)** — columns by **status** (default) or by **section**; drag to move/reorder.
- **List** — grouped rows (by section or status), inline-editable, sortable, filterable.
- **Calendar** — tasks placed on their due dates (month view).
- **My Tasks** — a suite-level, cross-client view of everything assigned to the current user,
  grouped by due (Today / This week / Later / No date / Overdue).
- **Per-client task page** — the client's board/list (reached from the client workspace).

### 6.7 Filtering, search, saved views
Filter by assignee, status, category, section, due-date range, client, source, and free-text
search on name/description. Users can **save a view** (named filter + grouping + sort), private
or shared. Provide built-in views: "My Tasks", "Overdue", "Due this week", "Unassigned".

### 6.8 Recurring monthly automation (reuse + repoint)
Each client has a **template** — its recurring monthly task set. Each template row references a
**library task** (by name) and carries an optional fixed assignee (or "auto-distribute"),
category, and est_hours (blank → inherit from the library). Once per month (configurable day,
default the 1st) — via the shared scheduler — and on demand via a "Generate this month" button,
the system, **per client**, idempotently:
1. Creates the "`<Month YYYY>`" section if absent (no-op if present).
2. For each active template row, creates a task **from the library task** — copying its
   **default subtask checklist** — inheriting blank hours/category from the library.
3. Runs **auto-distribution**: fills assignees for "auto-assign" rows by remaining capacity.
4. Sets status = the configured "initial" status (e.g. "Not Started"); leaves due dates blank
   (the team fills them) unless the template/library specifies a due-day offset (optional v1.1).

This is the native replacement for the Asana monthly job; the logic exists
(`asana_monthly.py`) and is repointed from Asana API calls to `tasks` inserts. **The library
task now owns the subtask checklist** (previously Asana task templates owned subtasks).

### 6.9 Task Library (reuse + extend)
A **global** catalog of standard tasks (name unique, default hours, default category, active) —
already exists (`asana_task_library`) and is seeded. **Extend it** so each library task can
define its **default subtask checklist** (an ordered list of subtask names). Building a client
template = picking library tasks. Editing a library task's hours/category/subtasks updates what
future generations inherit (per-client overrides always win).

### 6.10 Collaboration
- **Comments**: rich text (markdown), threaded under a task, edit/delete own, @mention users.
- **@mentions**: notify the mentioned user (notifications service); link to the task.
- **Attachments**: upload files to a task or comment (Supabase Storage bucket
  `task-attachments`, signed URLs); size/type bounded via config.
- **Activity feed**: an immutable, per-task audit (created, status changed, assigned,
  due changed, commented, completed, etc.) shown in the task detail.
- **Watchers/followers**: users following a task get its notifications; assignee + commenters +
  @mentioned are auto-added.
- **Live-ness**: v1 may poll (TanStack Query refetch). If concurrent editing causes friction,
  adopt **Supabase Realtime** on the `tasks`/`task_comments` tables (no new infra).

### 6.11 Notifications (reuse notifications service)
Emit via `notifications.emit(...)` (in-app feed + Slack + email, best-effort per channel):
- **Assigned to you** (incl. auto-distribution results), **@mentioned**, **comment on a task
  you follow**, **due soon / overdue** (daily sweep), **status changed to one you watch**
  (optional), and **workload overload** (reuse the existing daily workload alert).
Respect per-user delivery preferences (a `task_notification_prefs` table; v1 can default-on).

### 6.12 Workload (reuse)
The existing suite-level **Workload** page (`pages/TeamWorkload.tsx`): per-person open **hours**
vs **weekly capacity**, same-day due clustering, overload flags, and a **Team & capacity**
editor. Repoint its data source from Asana to the `tasks` tables (sum est_hours of each user's
open tasks). The **daily overload alert** continues via the scheduler + notifications.

### 6.13 Capacity & auto-distribution (reuse)
Team members have a weekly-hour **capacity** (`asana_team_members` → generalize to suite users;
see §7). Auto-distribution (`distribute_tasks`) assigns auto rows to the eligible member with
the most remaining capacity (capacity − current open hours, weighted by est. hours). Eligible
set is configured **per client** (which members may receive that client's auto tasks).

### 6.14 Deep suite auto-integration (the differentiator) — see §11
Tasks auto-created/closed from suite signals via an internal `task_service.create_task(...)` +
a `source` / `source_ref` mapping for idempotency and auto-close.

### 6.15 Permissions
- `admin`: full control, incl. status/category/library config, team capacity, all clients.
- `team_member`: create/edit/complete tasks, comment, manage own assignments; cannot edit
  global config (statuses/library) unless granted.
- All authenticated suite users can see all clients' tasks (internal tool; no per-client
  walls in v1). Mutations are audited (activity feed + `created_by`/actor).

---

## 7. Data model

All tables in the **public** schema, prefixed `task_` (except where reusing existing
`asana_*`/suite tables), **RLS enabled, service-role only** (the suite convention). Use
`uuid` PKs (`gen_random_uuid()`), `timestamptz` audit columns. FKs to `clients(id)` and
`profiles(id)` (or `auth.users`) as appropriate. Migrations live in
`writer/supabase/migrations/`.

```
task_sections
  id            uuid pk
  client_id     uuid null → clients(id) on delete cascade   -- null = internal/agency board
  name          text not null                               -- "July 2026" | "Backlog" | custom
  kind          text not null default 'custom'              -- 'month' | 'backlog' | 'custom'
  period_month  date null                                   -- first-of-month for kind='month'
  sort_order    int  not null default 0
  created_at / updated_at  timestamptz

tasks
  id              uuid pk
  client_id       uuid null → clients(id) on delete cascade
  section_id      uuid null → task_sections(id) on delete set null
  parent_task_id  uuid null → tasks(id) on delete cascade   -- set => this row is a SUBTASK
  name            text not null
  description     text null                                  -- markdown
  assignee_id     uuid null → profiles(id)
  status_key      text null → task_statuses(key)             -- workflow state
  category        text null                                  -- "Service Type" value (v1 simple enum)
  due_date        date null
  start_date      date null
  est_hours       numeric null
  completed       boolean not null default false
  completed_at    timestamptz null
  sort_order      int not null default 0                     -- within section (or parent for subtasks)
  source          text not null default 'manual'             -- manual | monthly | rank_drop | content_run | action_plan | maps_alert | ...
  source_ref      text null                                  -- producer's idempotency/auto-close key
  library_task_name text null                                -- which library task it derives from (by name)
  created_by      uuid null → profiles(id)
  deleted_at      timestamptz null                           -- soft delete (Trash)
  created_at / updated_at  timestamptz
  -- indexes: (client_id, section_id, sort_order); (assignee_id) where completed=false and deleted_at is null;
  --          (parent_task_id); (source, source_ref); (due_date) where completed=false.

task_statuses                                                -- configurable workflow states (global v1)
  key         text pk                                        -- 'not_started','in_progress','complete',...
  label       text not null
  color       text null
  category    text not null default 'in_progress'            -- not_started | in_progress | blocked | done
  is_initial  boolean not null default false                 -- the status new tasks get
  is_done     boolean not null default false                 -- counts as complete
  sort_order  int not null default 0
  active      boolean not null default true

task_categories                                              -- "Service Type" options (config, global v1)
  key text pk        -- or just use free-text values; a table keeps them consistent
  label text not null
  color text null
  sort_order int not null default 0
  active boolean not null default true

task_comments
  id          uuid pk
  task_id     uuid not null → tasks(id) on delete cascade
  author_id   uuid not null → profiles(id)
  body        text not null                                  -- markdown; @mentions parsed to user ids
  mentions    jsonb null                                     -- [profile_id,...] for fast notify
  created_at  timestamptz; edited_at timestamptz null; deleted_at timestamptz null

task_attachments
  id          uuid pk
  task_id     uuid not null → tasks(id) on delete cascade
  comment_id  uuid null → task_comments(id) on delete cascade
  file_name   text not null
  storage_path text not null                                 -- bucket 'task-attachments'
  mime_type   text null
  size_bytes  bigint null
  uploaded_by uuid → profiles(id)
  created_at  timestamptz

task_activity                                                -- immutable per-task audit / feed
  id        uuid pk
  task_id   uuid not null → tasks(id) on delete cascade
  actor_id  uuid null → profiles(id)
  kind      text not null                                    -- created|status_changed|assigned|due_changed|commented|completed|reopened|...
  detail    jsonb null                                       -- {from,to} etc.
  created_at timestamptz

task_watchers
  task_id uuid → tasks(id) on delete cascade
  user_id uuid → profiles(id)
  primary key (task_id, user_id)

task_saved_views
  id        uuid pk
  owner_id  uuid null → profiles(id)                         -- null = shared/global
  name      text not null
  config    jsonb not null                                   -- {scope, filters, group_by, sort}
  created_at / updated_at

task_notification_prefs                                      -- per-user channel prefs (v1 optional)
  user_id uuid pk → profiles(id)
  prefs   jsonb not null default '{}'                        -- {assigned:true, mention:true, due:true, ...}

-- REUSED from the Asana module (generalize naming over time; keep as-is to start):
asana_task_library            -- global library: name (unique), default_hours, default_category_name, active
  + NEW: task_library_subtasks(id, library_name text → asana_task_library.name, name text, sort_order int)
asana_client_task_templates   -- per-client recurring set (name, assignee, category, est_hours, auto_assign, sort_order, active)
asana_client_projects         -- repurpose: per-client task settings incl. auto_assignee_gids (eligible team subset)
asana_team_members            -- tracked team + weekly_hours capacity (generalize gid → profiles.id over time)
```

**Notes:**
- **Subtasks are tasks** (`parent_task_id`). This keeps one model, one API, and lets subtasks
  carry assignees/status if ever needed. Top-level tasks have `parent_task_id IS NULL`.
- **`source` + `source_ref`** are the backbone of suite auto-integration (§11): a producer sets
  them so the same signal never creates duplicate tasks and can **auto-close** its task later.
- **Custom fields (v2):** generalize `category` by adding `task_custom_fields` +
  `task_custom_field_values` (field def + per-task value). v1 ships the single `category` field
  to match today's "Service Type".
- **Capacity/team:** v1 keeps `asana_team_members` (its `gid` already maps to people). Plan a
  migration to key capacity on `profiles.id` so team = suite users.

---

## 8. API surface (FastAPI, `routers/tasks.py` + siblings)

All under suite auth (`require_auth`; config/admin endpoints `require_admin`). JSON; errors as
`HTTPException` with a string code (suite convention). Representative endpoints:

**Tasks**
- `GET /tasks` — list with filters: `client_id, assignee_id, status, category, section_id,
  due_before/after, source, q (search), include_subtasks, completed`. Paginated.
- `POST /tasks` — create (any field; `parent_task_id` for a subtask).
- `GET /tasks/{id}` — detail (incl. subtasks, comments, attachments, activity, watchers).
- `PATCH /tasks/{id}` — partial update (name, description, assignee, status, category, due,
  est_hours, section, sort, parent). Each meaningful change writes `task_activity` + notifies.
- `POST /tasks/{id}/complete` / `POST /tasks/{id}/reopen`.
- `POST /tasks/{id}/duplicate` — `{with_subtasks: bool}`.
- `DELETE /tasks/{id}` — soft delete; `POST /tasks/{id}/restore`; `DELETE /tasks/{id}/permanent`.
- `POST /tasks/reorder` — bulk sort within a section/status.
- `GET /tasks/mine` — current user's open tasks across clients, grouped by due bucket.

**Subtasks** — handled via `tasks` with `parent_task_id`; convenience:
`GET /tasks/{id}/subtasks`, `POST /tasks/{id}/subtasks`.

**Comments / attachments / activity**
- `GET/POST /tasks/{id}/comments`, `PATCH/DELETE /tasks/comments/{cid}`.
- `POST /tasks/{id}/attachments` (multipart), `GET /tasks/{id}/attachments`,
  `DELETE /tasks/attachments/{aid}`.
- `GET /tasks/{id}/activity`.
- `POST /tasks/{id}/watch` / `DELETE /tasks/{id}/watch`.

**Sections** — `GET/POST/PATCH/DELETE /clients/{client_id}/task-sections` (+ reorder).

**Config (admin)** — `GET/PUT /tasks/statuses`, `GET/PUT /tasks/categories`.

**Library & templates (reuse existing routes, extend)** — `GET/PUT /asana/task-library`
(+ subtasks); `GET/PUT /clients/{id}/asana/task-templates`; per-client eligible team
(`auto_assignee_gids`). Rename to `/task-library` etc. over time.

**Generation** — `POST /clients/{id}/tasks/generate-month` (manual, idempotent); scheduler
runs the monthly pass.

**Workload (reuse)** — `GET /asana/workload` → repoint to `tasks`. `GET/PUT /asana/team-members`.

**Saved views** — `GET/POST/PATCH/DELETE /tasks/views`.

**Migration (admin, §15)** — `POST /tasks/import/asana` (enqueues an import job), status poll.

---

## 9. Architecture & reuse

- **Service layer:** `services/task_service.py` (CRUD, activity, notifications, the internal
  `create_task`/`close_task_by_source` used by producers), `services/task_monthly.py`
  (repointed `asana_monthly`), `services/task_workload.py` (repointed `asana_workload`).
- **Jobs:** add `async_jobs` types `task_month_generate`, `task_due_sweep`,
  `task_import_asana`. Handlers in `job_worker.py`. (Widen the `async_jobs.job_type` CHECK
  constraint via migration — note the live constraint may carry values not present in repo
  migrations; preserve the **current live set** when widening.)
- **Scheduler:** add to `gsc_scheduler` loop: monthly generation (month-start), a **daily due
  sweep** (due-soon/overdue notifications), and the existing daily **workload overload** check.
- **Notifications:** reuse `notifications.emit`. Add task `kind`s (`task_assigned`,
  `task_mention`, `task_comment`, `task_due`, `task_overload`).
- **Frontend:** new pages/components under `frontend/src/` — `pages/Tasks.tsx` (per-client
  board/list/calendar), `pages/MyTasks.tsx`, `components/tasks/*` (Board, ListView,
  TaskDetail, SubtaskList, Comments, Activity, Filters). Reuse `pages/TeamWorkload.tsx`,
  `pages/TaskLibrary.tsx`, the per-client template editor (today `pages/AsanaTasks.tsx`).
  Add nav + a client-workspace "Tasks" card. Keep components dependency-free / consistent with
  existing inline-style patterns.

---

## 10. Automation details (monthly generation + library + auto-distribution)

Reuse the Asana module's pure helpers verbatim where possible:
- `apply_library_defaults(rows, library, …)` — inherit blank hours/category by name.
- `distribute_tasks(task_hours, members)` — capacity-aware greedy assignment.
- `aggregate_member_workload` / `build_workload_report` — workload math.
- `month_label`, `shift_months`, idempotency by section name.

Changes for native:
- **Subtasks:** the library task carries a **default subtask checklist** (`task_library_subtasks`);
  generation creates the parent task then inserts its subtasks. (Replaces "instantiate an Asana
  task template".)
- **Write target:** insert into `tasks`/`task_sections` instead of POSTing to Asana.
- **Status:** set to the `is_initial` status. **Category:** copy through (no per-project field
  resolution needed — categories are native config now).
- **Workload "current load":** sum `est_hours` of each member's open (`completed=false`,
  `deleted_at is null`) tasks across all clients — a DB query, not an Asana fetch.

---

## 11. Deep suite auto-integration (producers)

This is the payoff that justifies building native. Producers call
`task_service.create_task(..., source=<kind>, source_ref=<stable key>)` (idempotent on
`(source, source_ref)`) and `task_service.close_task_by_source(source, source_ref)` to
auto-complete when the underlying condition resolves. Initial producers (all already emit
signals in the suite today):

| Source | Trigger (existing suite mechanism) | Task created | Auto-close when |
|---|---|---|---|
| `rank_drop` | A new `rank_alerts` row opens (organic rank tracker, `rank_materialize`) | "Diagnose & reoptimize: `<keyword>`" on that client | the alert resolves / keyword recovers |
| `maps_alert` | A `maps_alerts` row opens (local-pack geo-grid) | "Local-pack drop: `<keyword>` — review" | alert resolves |
| `action_plan` | Reoptimization planner items (`reopt_plans`) | one task per recommended action, deep-linked to the tool that does it | item no longer in the latest plan |
| `content_run` | A content run completes (`runs`) | optional "Review & publish `<title>`" | published |

Implementation: a small adapter per producer (subscribe at the point each signal is written —
e.g. in `rank_materialize` where it already calls `notifications.emit`). Keep producers
**optional/config-gated** so the task system works without them and they can be enabled
incrementally. Each created task carries a **deep link** back to the relevant suite tool.

---

## 12. Notifications (reuse)

Use `notifications.emit(client_id, kind, title, summary, severity, payload={link, task_id,…})`.
The `payload.link` deep-links to the task (`/clients/:id/tasks?task=<id>` or
`/tasks/<id>`). The daily **due sweep** job emits `task_due` for tasks due today/overdue to
their assignee+watchers. The workload overload alert is reused. Channels (in-app always; Slack
+ email when configured) are already wired in the dispatch job.

---

## 13. Mobile / responsive / PWA

VAs work from phones, so the daily-driver views (My Tasks, a client's list view, task detail
with subtasks + comments) must be **fully responsive**. Ship an installable **PWA** (web
manifest + service worker for app-icon/launch; offline is **not** required in v1). Board
(Kanban) may degrade to a single-column list on small screens. This is the **hardest parity
item** vs. Asana's native apps — budget accordingly and prioritize My Tasks + task detail.

---

## 14. Permissions (detail)
- Endpoints use `require_auth`; config/library/status/capacity mutations use `require_admin`.
- Any authenticated user reads/writes tasks across clients (internal tool). All mutations are
  attributed (`created_by`, `task_activity.actor_id`).
- Soft-delete (Trash) instead of hard-delete for tasks; permanent delete is admin-only.

---

## 15. Migration from Asana

Goal: move existing live work into the native system, run **both in parallel** for one cycle,
validate, then cut over and decommission the Asana integration.

**Importer** (`task_import_asana` job, reuses the existing Asana REST client
`services/asana_service.py`):
1. **Mapping:** Asana project → `clients` (via the existing `asana_client_projects` map).
   Asana assignees → `profiles` (match by email; unmatched → unassigned + a report).
2. **Sections:** Asana sections → `task_sections` (month/backlog/custom by name).
3. **Tasks + subtasks:** import each task (`name, assignee, due_on, custom fields, completed`)
   → `tasks`; pull subtasks (`GET /tasks/{gid}/subtasks`) → child `tasks`. Map the Asana
   "Status" custom field → `task_statuses` (by name), "Service Type" → `category`,
   "Hours/Est." number field → `est_hours`.
4. **Task templates:** Asana **task templates** (`GET /task_templates?project=`) → seed the
   **Task Library** + each library task's **default subtask checklist** (instantiate or read a
   template's subtasks to capture the checklist). The Task Library is already seeded with the
   names; this adds their subtasks + locks canonical names.
5. **Comments (optional):** Asana stories → `task_comments` (best-effort; can be skipped v1).

**Parallel run & cutover:**
- Import a snapshot; run the native system **alongside** Asana for one monthly cycle. Validate
  generation, assignments, workload, and notifications against reality.
- During parallel run, the team executes in **AR Tools**; Asana is read-only reference.
- Cut over: stop the Asana monthly job, disable the Asana write paths, cancel the subscription.
  Keep the importer + a final export for archival.

**Standardize names during migration:** projects use slightly different task-template names
(e.g. "40 Citations" vs "(Number) Citations", "Service Silo" vs "Service Page Silo"). Pick
**canonical** names for the Task Library; map variants during import so every client's template
lines up.

---

## 16. Phased roadmap (with acceptance criteria)

Build in vertical slices; each phase is shippable and leaves the team better off. Run Asana in
parallel until Phase 5.

**Phase 0 — Foundations & repoint (no user-visible board yet).**
- Migrations for all §7 tables; `task_service` CRUD; statuses/categories seeded (§19);
  extend the Task Library with subtask checklists; repoint monthly generation + workload to
  `tasks`. Add `async_jobs` types + scheduler hooks. Unit tests for pure helpers
  (generation, distribution, workload, due-sweep selection).
- *Acceptance:* a `generate-month` call creates a month section + tasks (with subtasks,
  assignees via auto-distribution, status/category) in `tasks`; the Workload page reads from
  `tasks`; all green tests; graceful when empty.

**Phase 1 — Daily-driver UI.**
- Per-client **Board + List** views; **Task detail** (description, subtask checklist,
  fields, complete); status drag; sections/month grouping; **My Tasks**; basic filters/search;
  client-workspace "Tasks" card + nav.
- *Acceptance:* the team can run a client's month end-to-end in the UI (create/edit/assign/
  status/complete tasks + subtasks) without touching Asana.

**Phase 2 — Collaboration.**
- Comments + @mentions, attachments, activity feed, watchers, soft-delete/Trash, duplicate.
- *Acceptance:* a task supports a full back-and-forth (comment, mention, attach, see history)
  comparable to how the team uses Asana comments today.

**Phase 3 — Notifications, calendar, saved views.**
- Notifications (assigned/mention/comment/due/overload) via the suite service; **daily due
  sweep**; **Calendar** view; **saved views** + built-ins (Overdue, Due this week, Unassigned).
- *Acceptance:* assignees get notified on assignment/mention/due; overdue work surfaces daily;
  users can save and switch views.

**Phase 4 — Mobile (PWA) + deep suite integration.**
- Responsive/PWA for My Tasks + list + task detail; first **producers** (`rank_drop`,
  `action_plan`) auto-creating/closing tasks with deep links.
- *Acceptance:* a VA can work a full day from a phone; a real ranking drop opens a task and its
  recovery closes it.

**Phase 5 — Asana migration & cutover.**
- Importer (tasks/subtasks/templates/assignees), one parallel-run cycle, validation, cutover,
  decommission the Asana integration, cancel the subscription.
- *Acceptance:* a full month runs natively with Asana read-only; subscription cancelled.

---

## 17. Open questions / decisions to confirm before/while building

1. **Status set** — confirm the canonical, ordered list + colors + which is "initial"/"done"
   (start from §19.2; the team has richer states like "Sent to Client", "Client Approved",
   "Waiting on URL to Go Live").
2. **Custom fields generality** — ship only "Service Type" in v1, or build the general
   custom-field model now? (Recommendation: ship the simple field; design the table for the
   extension.)
3. **Realtime** — polling vs. Supabase Realtime for live board updates (start polling; adopt
   Realtime if multi-user editing causes staleness complaints).
4. **Recurring beyond monthly** — any weekly/quarterly recurrences, or is monthly the only
   cadence? (Today: monthly.)
5. **Due-date automation** — should the library/template set default due-day offsets per task,
   or always manual? (Today: manual.)
6. **Client visibility** — any future read-only client view? (Out of v1; keep the data model
   from precluding it.)
7. **Time tracking** — estimated-only confirmed for v1? (Yes.)
8. **Team identity** — migrate capacity from `asana_team_members.gid` to `profiles.id` (so a
   "team member" is a suite user) — when?

---

## 18. Out of scope (v1)
Timeline/Gantt + dependencies, portfolios/goals, forms/intake, rules builder, proofing/
annotations, advanced reporting dashboards, native mobile apps, offline mode, time tracking,
guest/client login, general custom fields (beyond the single Service Type), multi-workspace.

---

## 19. Appendix — ground-truth data (real workflow to support)

### 19.1 The agency's task workflow (as run in Asana today)
- Multiple SMB clients; **each client has its own board/project**.
- Work is organized into **month sections** ("May 2026", "June 2026", …) — a recurring set of
  **monthly delivery tasks** per client.
- Each task has: assignee, due date (filled manually), a **Status**, a **Service Type**
  category, an **estimated time**, and a **subtask checklist** (e.g. "Map Embeds" had 5
  subtasks, "Service Silo" had 14).
- The same standard tasks recur every month (defined as reusable **task templates with
  subtasks**). Team members include VAs (e.g. "Minda", "Ivy"). Each has a weekly capacity.
- They were on Asana's **Starter** plan (no native Workload view, no Rules) — the suite added
  capacity-aware workload + auto-distribution on top.

### 19.2 Statuses observed (seed `task_statuses`; confirm/trim)
From one project's "Status" field: **Not Started** (initial), **In Progress**, **Sent For
Approval**, **For Revision**, **Complete** (done), **Blocked**. Other projects carry richer
states: **On Hold**, **In Review**, **Needs Revisions**, **Approved to Send to Client**, **With
Client**, **Sent to Client**, **Client Approved**, **Waiting on URL to Go Live**, **Approved**,
**Ongoing**, **Done**. → Define one canonical ordered set; map variants on import.

### 19.3 Categories observed ("Service Type"; seed `task_categories`)
**Content**, **Link Building**, **GBP Authority**, **Strategy**. (Some projects label a similar
field differently, e.g. "Service Type" vs a "Category"/"Channel" — standardize to one.)

### 19.4 Standard task catalog (already seeded into the Task Library; durations TBD by team)
Map Embeds, (Number) Citations, SEO NEO Task, GBP Blast, HyperLocal GBP Blast, Website Pages
Posted, GBP Posts, Press Release, Service Silo, Blog Post Title, Blog Post Scheduling, Niche
Edits, Guest Posts — plus variants seen on other projects: 40 Citations, Service Page Silo,
Respect Mah Authoritay, Cloud Stack, T1 Booster to citations. **Each carries a default subtask
checklist** in Asana (to be imported into the library, §15.4). **Canonicalize names** during
migration so every client's template aligns.

### 19.5 What already exists in the codebase (starting point — see §3)
The Asana integration's services (`asana_service`, `asana_monthly`, `asana_workload`), routes
(`routers/asana.py`), models (`models/asana.py`), and frontend (`AsanaTasks`, `TeamWorkload`,
`TaskLibrary`) — the orchestration to repoint, and the REST client to reuse as the migration
importer.

---

## 20. Stage automation + the Inbox Agent (added 2026-07-12)

### 20.1 Built: the status column drives itself
The owner's ruling: the status drag should be automated away wherever a real
signal exists. Shipped, in order:

- **Auto-tick sync** — a forward status change ticks the process-marker
  subtasks the new stage implies (`task_service.marker_tick_stage` /
  `auto_tick_subtasks`; late-never-early; the "Added to deliverables sheet"
  reminder stays manual for the PM until the PACE sheet automation).
- **Rule A — start-on-touch**: the first human touch on a Not Started task (a
  subtask tick, comment, or attachment) moves it to In Progress
  (`start_task_on_touch`, wired in `complete_task`/`task_collab`).
- **Rule B — work-done**: when the last REAL work item on the checklist ticks
  (process markers and deliverables reminders don't count —
  `is_work_item`), the task auto-advances to **In QA**
  (`parent_advance_target` / `advance_parent_after_tick`).
- Publish/deliverable events already complete content tasks (the
  `content_run` producer, enabled 2026-07-12).

Guards everywhere: never backward, never from the exception statuses
(Blocked / In Review), never on completed tasks, activity-logged, best-effort.
Manual drags still work and still cascade auto-ticks.

**Remaining human stages:** In QA → Sent to Client (the **QA agent** — next
build: check registry over the nlp 8-engine scorer / structure eval /
citation checks + an LLM review; comment-only first, then advance-on-pass)
and Sent to Client → Client Approved (below).

### 20.2 FUTURE BUILD — Inbox Agent (client-approval automation; deferred)
**Status: deferred by owner ruling 2026-07-12 — do NOT build until the owner
grants mailbox access** (Google Workspace domain-wide delegation, Gmail
read-only scope on the inbox where client replies land — an admin-console
step only the owner can do).

The last manual stage transition (Sent to Client → Client Approved) encodes an
external event: the client's reply. An inbox-watching agent closes it:

- **Token loop (primary matching):** when a card enters Sent to Client, the
  approval-request email carries a task reference; the reply's token gives a
  deterministic task match. Sender-domain → client matching is the fallback.
- **Intent classification** (one small LLM call — Haiku): approved /
  revisions requested / question.
- **Confidence ladder:** explicit approval → auto-advance to Client Approved
  (reply text attached as a task comment); **revisions requested → park in
  In Review with the feedback routed onto the task** and the assignee
  notified; ambiguous → nothing moves, staged into PACE's daily chase plan
  for a human reply-*yes* confirm. A false "client approved" is the costly
  mistake — only unambiguous language auto-advances.
- **Further consumers (same watcher, owner-requested):** route revision
  feedback onto the task automatically; hand client *questions* to SerMaStr
  to draft replies; sentiment dips → PACE escalation.
- **Runs on the existing rails:** shared-scheduler poll (no new infra),
  producer writes through `task_service`, PACE/SerMaStr integration via the
  existing context-provider + action registries.

Until then, Sent to Client → Client Approved stays the one human drag (an
optional "silence = approval after N business days" policy was offered and
not adopted).
