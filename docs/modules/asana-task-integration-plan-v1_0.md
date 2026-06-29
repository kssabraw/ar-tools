# Asana Task Integration — Plan (v1.0)

**Authored:** 2026-06-29 · **Status:** Planned — not yet built · **New suite integration — "Asana"**

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
| 3 | Monthly template source | A hand-maintained **`Template` section** in each client project; the job **clones it forward**. Team edits the template in Asana — no code change to adjust the monthly set. |
| 4 | Due dates on generated tasks | **None at creation.** Tasks are created with assignee + category + Status=Not Started; the team fills dates in. |
| 5 | What carries forward | Task **name**, **assignee**, **category** custom field. Status reset to **Not Started**. No due date. |
| 6 | Trigger | **Both** — auto on the 1st of the month (shared `gsc_scheduler` → `async_jobs`) **and** a manual "Generate next month" button per client. |
| 7 | Idempotency | If `<Month YYYY>` already exists in the project, the job is a **no-op** — auto + manual can't double up. |
| 8 | Workload feature mode | **View + proactive alerts** — a Team Workload view *and* a daily check that pings Slack/in-app via the **notifications service**. |
| 9 | Workload scope | **A defined team list** (configurable), not every workspace member. |
| 10 | Graceful degradation | Absent token / project mapping / team list → the relevant feature is **skipped with a note**, never an error. Matches GSC / Slack provisioning behavior. |

---

## 3. Feature A — Monthly section automation (write)

**Goal:** each month, every mapped client project gets a new `<Month YYYY>` section populated
from its `Template` section, so the team stops hand-copying tasks.

**Flow (per client project):**
1. Resolve the client's Asana **project GID** (mapping table, §6).
2. Compute the target month label `<Month YYYY>` (e.g. `July 2026`).
3. If a section with that exact name already exists → **no-op** (idempotent).
4. Read the project's **`Template` section** tasks (name, assignee, category custom field).
5. Create the new `<Month YYYY>` section, **inserted above** the backlog ("Untitled
   section") — Asana section create supports `insert_before`/`insert_after`.
6. For each Template task, **create a task** in the new section with: same name, same
   assignee, same category custom-field value, **Status = Not Started**, **no `due_on`**.

**Asana API surface used:**
- `GET /projects/{gid}/sections` — find `Template` + the insert anchor.
- `GET /sections/{gid}/tasks?opt_fields=name,assignee,custom_fields` — read the template.
- `POST /projects/{gid}/sections` — create `<Month YYYY>`.
- `POST /tasks` with `memberships: [{project, section}]`, `assignee`, `custom_fields`
  (Status enum option = "Not Started", category enum option carried from template).

**Triggers:**
- **Auto:** the shared in-process scheduler (`services/gsc_scheduler.py`) gains an
  `enqueue_due_asana_monthly` due-check that, at month start, enqueues one
  `asana_monthly` `async_jobs` job per mapped client.
- **Manual:** `POST /clients/{id}/asana/generate-month` (optionally with a target month) —
  enqueues the same job; surfaced as a **"Generate next month"** button in the client
  workspace. Optionally renders each assignee's current load (Feature B) as pre-commit
  context.

---

## 4. Feature B — Team Workload (read + alerts)

**Goal:** know we're not overloading a team member or stacking too many tasks on one day.

**Read view (suite-level — spans people and all client projects):**
- For each person in the **defined team list**, pull **open tasks across the workspace**
  (`GET /tasks?assignee={user_gid}&workspace={gid}&completed_since=now`, paginated, with
  `opt_fields=name,due_on,projects`).
- Aggregate into: **per-person open-task count** and a **due-date distribution**
  (tasks-due-per-day for the current/next window).
- **Overload flags** (thresholds in `config.py`): too many open tasks per person; too many
  tasks **due the same day** (e.g. "Minda has 6 tasks due Jul 9").
- Lives above any single client — Home or a dedicated "Team Workload" page. Read-only, so
  no `profiles ↔ Asana-user` mapping required for v1 (display Asana assignee names).
- Pulled on demand with **light caching** to respect Asana rate limits (~150 req/min).

**Proactive alerts:**
- A **daily** scheduler due-check (`gsc_scheduler`) runs the same aggregation and, when a
  team member crosses an overload threshold or has too many tasks due the same day, calls
  `services/notifications.emit(...)` → in-app feed + Slack (email when provisioned). Reuses
  the existing `notification_dispatch` pipeline; no new delivery infra.

**Note on creation-time stacking:** because Feature A creates tasks **without due dates**,
there is no due-date clustering to guard against *at creation*. Workload is therefore an
ongoing **monitoring** concern (view + daily alerts), which is what catches same-day
stacking once the team fills dates in.

**Native-Asana caveat:** Asana's **Workload** view (Portfolios, Business tier) covers part
of this out of the box. The in-app version still earns its place — tied to the suite, custom
thresholds, cross-client aggregation, and it can drive the proactive Slack/in-app alerts —
but if the team is on that tier, scope Feature B's view against what the native view already
gives them.

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

A small mapping table (everything else lives in Asana):

```
asana_client_projects
  client_id    uuid  → clients(id)   (unique)
  project_gid  text  (the Asana project for this client)
  created_at   timestamptz
```

- Populated once per client at onboarding (one row).
- The **team list** (Feature B scope) and **custom-field GIDs** (Status / category, plus the
  "Not Started" option GID) are configuration, not per-client data — held in `config.py`
  (§7), since they're workspace-level constants.

---

## 7. Config (`config.py`, on `PLATFORM`)

| Setting | Purpose |
|---|---|
| `asana_token` (`ASANA_TOKEN`) | PAT / service-account token. **Absent → both features skipped.** |
| `asana_workspace_gid` | Workspace to scope task queries. |
| `asana_template_section_name` (default `"Template"`) | Which section the monthly job clones. |
| `asana_status_field_gid` / `asana_status_not_started_option_gid` | Set Status = Not Started on new tasks. |
| `asana_category_field_gid` | Carry the category custom field forward (read from template). |
| `asana_team_member_gids` (list) | The defined team list for workload. |
| `asana_workload_max_open` / `asana_workload_max_due_same_day` | Overload thresholds. |
| `asana_monthly_enabled` / `asana_workload_enabled` | Feature toggles. |

Secrets are set on the `PLATFORM` Railway service by the user — never handled in code/chat.

---

## 8. One-time Asana provisioning (user-side, dashboard + env)

These are external inputs the integration can't invent; code is built to degrade gracefully
until they exist (so it ships safely before they're all in place). To go live:

1. **Token** — create an Asana PAT (or service account) → set `ASANA_TOKEN` on `PLATFORM`.
2. **`Template` section** — create a `Template` section in each client project, populated
   with the recurring tasks + assignees + category. (These don't exist yet.)
3. **Project mapping** — record each AR Tools client's Asana **project GID** (one
   `asana_client_projects` row per client).
4. **Custom-field GIDs** — pull the Status field GID + "Not Started" option GID + the
   category field GID from the Asana API once the token exists; set in config.
5. **Team list** — the Asana user GIDs to track for workload → `asana_team_member_gids`.
6. *(Optional, no code)* install Asana's official **Slack app** for the Slack ⇄ Asana leg.

Provisioning steps will be written into `HANDOFF.md` (top section) alongside the Slack /
notifications setup.

---

## 9. Phasing

- **Phase 0 — scaffolding:** config seams, `asana_client_projects` migration, `asana_service`
  skeleton + pure helpers + tests. Graceful no-op when unprovisioned.
- **Phase 1 — monthly automation:** template clone-forward, `asana_monthly` job, scheduler
  month-start due-check, manual endpoint + "Generate next month" button. Idempotent.
- **Phase 2 — workload view:** per-person aggregation + overload detection + read-only
  suite-level view.
- **Phase 3 — workload alerts:** daily due-check → notifications service (Slack/in-app).
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
