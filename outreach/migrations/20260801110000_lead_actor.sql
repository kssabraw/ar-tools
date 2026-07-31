-- Give the lead audit trail a real actor under the module ruling.
--
-- THE DEFECT. `lead_log_changes` writes the stage-change and reassignment activity rows with
-- `actor_id := auth.uid()`. That was correct when the CRM was reached directly with a per-user
-- Supabase JWT. It is not correct now: under the module ruling (HANDOFF §2) platform-api holds
-- the SERVICE ROLE and is the only client, and `auth.uid()` is NULL for the service role. Every
-- stage change and every reassignment would therefore be logged anonymously — the audit trail
-- exists, is append-only and correct in every other respect, and cannot say who did anything.
--
-- Not caught by PR #534's verification because `lead` held zero rows and no client existed yet;
-- it only becomes observable the moment the router starts writing. See ISSUES I-040.
--
-- THE FIX. `lead` gains `updated_by`, the mutation-side twin of the `created_by` it already has,
-- and the trigger prefers it over `auth.uid()`.
--
-- Why not move the activity write into platform-api instead, now that it is the only writer? The
-- trigger is the safety net that makes the audit trail structural rather than conventional — a
-- stage corrected by hand in SQL, or by some later job, still gets logged. Losing that to gain an
-- actor id would be a bad trade when a column buys both. The trigger stays authoritative; the
-- application's only new duty is to say who is acting.
--
-- `coalesce(auth.uid(), new.updated_by)` rather than the reverse: a genuine end-user JWT, if one
-- ever reaches this database again, is stronger evidence of the actor than a column the caller
-- populated itself.

alter table lead add column if not exists updated_by uuid;

comment on column lead.updated_by is
  'Suite profile id of whoever last mutated this row, supplied by platform-api. Not an FK — the '
  'Outreacher auth.users pool stays permanently empty and this carries the SUITE''s identity '
  '(same reasoning as created_by/owner_id in migration 20260731190000).';

create or replace function public.lead_log_changes()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  actor uuid := coalesce(auth.uid(), new.updated_by);
begin
  if new.stage is distinct from old.stage then
    insert into lead_activity (lead_id, actor_id, kind, body, from_stage, to_stage)
    values (new.id, actor, 'stage_change',
            format('Stage %s → %s', old.stage, new.stage), old.stage, new.stage);
  end if;

  if new.owner_id is distinct from old.owner_id then
    insert into lead_activity (lead_id, actor_id, kind, body, metadata)
    values (new.id, actor, 'system',
            case when new.owner_id is null then 'Unassigned' else 'Assigned' end,
            jsonb_build_object('event', 'assignment', 'from', old.owner_id, 'to', new.owner_id));
  end if;

  return null;
end;
$function$;

-- Same posture as every other trigger function here: not callable as an RPC. Invoking one
-- directly errors rather than doing anything, but a SECURITY DEFINER function sitting on
-- /rest/v1/rpc/ is what the advisor flags and there is no reason to leave it reachable.
revoke all on function public.lead_log_changes() from anon, authenticated, public;
