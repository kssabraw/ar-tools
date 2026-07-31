# Phase 1b — lead CRM: state, and what is left

**Applied live to the Outreacher project (`fkwhgvcggvsricuinuqy`) and verified.**
17 checks in `tests/lead_crm_rls.sql`.

## What exists

| Object | Notes |
|---|---|
| `lead` | spec §3 shape: six-value `source`, seven-stage workflow, `lost_reason` + `lost_to`, `next_action`/`next_action_due`, `stage_changed_at` |
| `lead_activity` | append-only commentary; `from_stage`/`to_stage` columns; `touch_id` carried without its FK until Phase 3 |
| `lead_stage` | lookup table carrying the spec's seven stages, with `sort_order`/`is_terminal` for the board |
| `suppression` | Phase 1's table, patched additively. No delete path — §4 |
| `lead_inbox`, `lead_detail`, `v_overdue_actions` | `security_invoker` views |
| `lead-intake` edge function | deployed, fails closed until `LEAD_INTAKE_SECRET` is set |

Migrations: `20260731150000_lead_crm.sql` then `20260731190000_lead_crm_spec_reconcile.sql`.
Read them in that order — the first records the original mistakes in place, the
second corrects them, and the comments explain why each was wrong.

## Access model

**Service role only.** RLS is enabled with zero policies and `anon`/`authenticated`
hold no grants, matching every other table in the estate. Authorization belongs in
platform-api.

This replaced a per-user RLS model built for a direct Retool connection. That
runbook (`docs/modules/lead-crm-retool-setup-v0_1.md`) was **deleted** rather than
left to rot: it instructed a reader to wire per-user JWTs against policies that no
longer exist, which is worse than no runbook. See `DECISIONS.md` for the ruling.

## What is left

1. **The platform-api router.** `outreach` routes over a project-scoped Supabase
   client — the LeadOff/fanout pattern, extended to a second Supabase *project*
   rather than a second schema, which is new ground.
2. **The suite UI.** Pages in the suite SPA. Nothing in `frontend/` exists yet.
3. **`LEAD_INTAKE_SECRET`** (ISSUES.md I-037). The intake function has never been
   invoked — the build sandbox cannot reach the project host. Under the module
   ruling it is also a candidate for retirement in favour of a platform-api route,
   which would put inbound behind the same auth and logging as everything else.

## Identity

`owner_id`, `actor_id` and `created_by` carry the **AR Tools** profile id, from the
AR-Internal-Tools project. There is deliberately no foreign key: the referenced
table is in a different database. platform-api validates them.

Nobody needs an Outreacher login. Any instruction to create Supabase auth users for
this project is out of date (ISSUES.md R-011).
