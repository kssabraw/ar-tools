-- GBP Profile Audit — change-log trail. The profile monitor appends a row here
-- for each detected event (an outside/Google content change, a suspension /
-- access loss, a recovery), so the Audit tab can show a chronological trail of
-- external changes alongside the team's own applied edits (gbp_profile_edits).
-- Distinct from gbp_profile_snapshots.last_change (which keeps only the latest
-- change for the compact monitor strip). See services/gbp_profile_audit.py.

create table if not exists gbp_profile_change_log (
  id              uuid primary key default gen_random_uuid(),
  location_row_id uuid not null references gbp_locations(id) on delete cascade,
  client_id       uuid not null references clients(id) on delete cascade,
  kind            text not null check (kind in ('outside_change','suspended','access_lost','restored')),
  detail          jsonb,
  detected_at     timestamptz not null default now()
);

create index if not exists idx_gbp_profile_change_log_loc
  on gbp_profile_change_log (location_row_id, detected_at desc);
create index if not exists idx_gbp_profile_change_log_client
  on gbp_profile_change_log (client_id, detected_at desc);
