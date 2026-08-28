# Native Task Manager — profiles↔gid unification: Phase 2 cutover runbook

**Status:** staged, NOT executed. Phase 1 (additive, dual-write) shipped in
PR #845 (migration `20260828200000`). This document is the **deliberate
cutover step** — run it only after Phase 1 has been validated in a parallel-run
cycle. Nothing here is in the auto-applied `writer/supabase/migrations/`
directory on purpose: the migration renames/drops columns the still-running code
depends on, so it must be applied **in lockstep with the Phase 2 code deploy**,
never on its own.

## Why Phase 2 is separate

Phase 1 is backward-compatible: `assignee_id` (canonical) and `assignee_gid`
(legacy) are both written, so old and new code coexist. Phase 2 removes the
legacy half and finalizes the roster identity. Removing a column or renaming a
table while any deployed replica still reads it causes 500s, so Phase 2 changes
must land with the code that stops using the legacy names.

## What Phase 2 delivers

1. **Login-less VAs become addable** — the roster's `id` becomes the primary key
   and `gid` becomes nullable, so a roster row can exist with no Asana gid.
2. **Legacy columns dropped** — `tasks.assignee_gid`,
   `asana_client_task_templates.assignee_gid`, `task_member_skills.member_gid`,
   `asana_client_projects.auto_assignee_gids`.
3. **(Optional, deferred by recommendation)** — physical table rename
   `asana_team_members → team_members`. See "The rename" below.

---

## Recommended split

Do Phase 2 in two deploys, not one, so the risky identity-finalization is
isolated from the mechanical cleanup:

### Phase 2a — identity finalization (enables login-less VAs)

**Code (deploy first, or with the migration — it only stops *writing* the gid,
which is safe against the new schema):**

- `services/task_service.py::_resolve_member` — stop populating `assignee_gid`
  (the dual-write). Return only `{assignee_id, assignee_name}`; drop
  `assignee_gid` from the create/update rows. A login-less member resolves to
  `assignee_gid = NULL` today already, so this is a deletion of the mirror, not
  a behavior change for linked members.
- `routers/asana.py::replace_team_members` — allow a member with **no gid**
  (a login-less VA): when `gid` is blank, insert a row with `gid = NULL`
  (skip the `on_conflict=gid` path for those — match/update them by `id`
  instead, or always insert-new when `id` is absent). Keep the
  non-destructive-on-id upsert for members that do have a gid.
- `models/asana.py::AsanaTeamMemberItem` — make `gid` optional
  (`gid: Optional[str]`) so the Team page can submit a login-less member.
- **Frontend** `pages/TeamWorkload.tsx` — add an "Add a VA (no Asana login)"
  affordance next to the existing "Add member by Asana user GID": it creates a
  roster row with a name + weekly hours and no gid. The rest of the roster
  editor is unchanged (the profile-link dropdown already works for both).

**Migration 2a (apply WITH the 2a code deploy):**

**APPLIED LIVE 2026-08-28 (migration `20260828210000`).** The RESTRICT backstop
below makes it safe to apply ahead of the code deploy: the old prod roster
editor's blanket delete now fails loudly instead of orphaning assignee_ids.

```sql
-- The skills FK references asana_team_members(gid)'s FULL unique constraint (the
-- PK). A partial unique index can't back an FK, so drop the FK first — skills is
-- already keyed on member_id in the app (Phase 1); member_gid is dropped in 2b.
alter table task_member_skills drop constraint if exists task_member_skills_member_gid_fkey;

-- Promote id to the primary key by REUSING the existing unique index on id
-- (the id-referencing FKs on tasks/templates/skills depend on it, so it must not
-- be dropped — USING INDEX converts it into the PK in place).
alter table asana_team_members drop constraint asana_team_members_pkey;      -- was on gid
alter table asana_team_members add primary key using index uq_asana_team_members_id;
alter table asana_team_members alter column gid drop not null;               -- login-less VA => gid NULL
create unique index if not exists uq_asana_team_members_gid
  on asana_team_members (gid) where gid is not null;                          -- keep ON CONFLICT(gid) valid

-- Safety backstop: assignee FK SET NULL → RESTRICT, so the OLD roster editor's
-- blanket delete-then-reinsert fails loudly instead of orphaning assignee_id.
-- The Phase 2a code unassigns a removed member's tasks explicitly before delete.
alter table tasks drop constraint tasks_assignee_id_fkey;
alter table tasks add constraint tasks_assignee_id_fkey
  foreign key (assignee_id) references asana_team_members(id) on delete restrict;
```

Note: `ON CONFLICT(gid)` in the roster upsert still works against the partial
unique index. The `member_gid` FK is gone after this; the `member_gid` column
itself (now unreferenced) is dropped in 2b. **Until the Phase 2a code deploys**,
the old prod Team-page save returns a 500 (RESTRICT) — a rare, safe degradation.

**Verify 2a:** add a login-less VA on the Team page, assign them a task, confirm
`tasks.assignee_id` points at their roster `id` and `assignee_gid` is NULL, and
that they appear in workload/My-Tasks/placement.

### Phase 2b — legacy cleanup (after confidence)

Deploy code that no longer references any of the legacy columns (search for
`assignee_gid`, `member_gid`, `auto_assignee_gids` across
`writer/platform-api` — the only remaining ones after 2a are the reads listed
below), then apply:

```sql
-- tasks: drop the legacy assignee column + its index.
drop index if exists idx_tasks_assignee_open;                 -- was on assignee_gid
alter table tasks drop column assignee_gid;

-- templates: drop the legacy default-assignee column.
alter table asana_client_task_templates drop column assignee_gid;

-- skills: finalize on member_id, drop the legacy gid column + its unique/index.
drop index if exists idx_task_member_skills_gid;
alter table task_member_skills drop constraint task_member_skills_member_gid_category_key_key;
alter table task_member_skills drop column member_gid;
alter table task_member_skills alter column member_id set not null;
alter table task_member_skills add constraint uq_task_member_skills_member_cat unique (member_id, category_key);

-- eligibility: drop the legacy gid array.
alter table asana_client_projects drop column auto_assignee_gids;
```

**Code touched by 2b** (remove the now-dead legacy references):

- `models/tasks.py`, `models/asana.py` — drop the `assignee_gid` /
  `auto_assignee_gids` fields.
- `services/task_service.py` — `_resolve_member` / `create_task` /
  `update_task` no longer mention `assignee_gid`.
- `routers/tasks.py` — `/tasks/mine`: drop the legacy `?gid=` param and the
  `gid`/`my_gid` response keys (once the Phase-1 frontend that read them is no
  longer deployed).
- `routers/asana.py` — project-mapping get/put: drop `auto_assignee_gids`
  read/write + the gid↔id cross-fill (keep `auto_assignee_ids`); template
  insert drops `assignee_gid`.
- `services/pm_assign.py` — `_skills_by_member` / `replace_member_skills`
  already use `member_id`; no SQL change, just confirm no `member_gid` remains.
- **Frontend** — drop the `assignee_gid` / legacy `?gid=` fallbacks
  (`t.assignee_id ?? t.assignee_gid` → `t.assignee_id`; `m.id ?? m.gid` →
  `m.id`), and the `gid`/`my_gid` type fields.

**Verify 2b:** full platform-api pytest suite green; Team/Tasks/My-Tasks/
Workload/Action-Plan pages load; a monthly generation + an auto-placement both
assign correctly.

### The rename (Phase 2c — optional, recommended to DEFER)

Physically renaming `asana_team_members → team_members` is **cosmetic** (the
"Asana" in the name is vestigial once gids are gone) and carries real
coordination cost: ~15 files query the table by name, and a bare rename breaks
every deployed replica until the new code ships. The safe pattern is a 3-step
expand/contract:

1. Migration: `alter table asana_team_members rename to team_members;` then
   `create view asana_team_members as select * from team_members;` (a 1:1 view
   keeps old code working — but the view is not writable through
   `on_conflict`, so the roster-CRUD upsert must move to `team_members` in the
   same deploy).
2. Deploy code referencing `team_members` everywhere.
3. Migration: `drop view asana_team_members;`.

**Recommendation:** skip 2c unless the owner specifically wants the cosmetic
rename. It delivers no capability and is best done as its own isolated PR after
2a/2b have settled, not bundled into the cutover.

---

## Ordering summary

```
Phase 1 (done, PR #845)  → additive, dual-write, validate in parallel run
Phase 2a  → id PK + gid nullable  ⇒ login-less VAs; stop writing assignee_gid
Phase 2b  → drop legacy gid columns; finalize member_id NOT NULL
Phase 2c  → (optional) physical rename asana_team_members → team_members
```

Each phase: apply the migration **with** its code deploy (single replica —
`PLATFORM` is `numReplicas: 1` — so there is no cross-replica skew, but the
deploy still swaps the running code atomically). Re-run the platform-api pytest
suite before each deploy.
