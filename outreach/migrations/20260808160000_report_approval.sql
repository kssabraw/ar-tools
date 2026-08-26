-- report_approval — the explicit human approval behind a client-facing asset (report increment 4).
--
-- The module's hardest invariant: "No prospect-facing asset is generated without explicit human
-- approval" (CLAUDE.md; reporting-layer-spec §4a). The client-facing PDF is that asset, so its
-- generation is admin-gated at the API and RECORDED here — who approved, when, and the content_hash
-- of the exact bytes approved (reporting §2 — a report shared in March regenerates identically in
-- June, and the approval names which render was sanctioned).
--
-- `approved_by` carries the AR Tools profile id from AR-Internal-Tools and has NO foreign key —
-- Postgres cannot enforce it across databases, and under the suite-module ruling (HANDOFF §2) the
-- identity columns in this project deliberately carry no cross-database FKs.
--
-- Service-role only (RLS on, zero policies) like every other object here. Do NOT add an RLS policy
-- to silence the advisor — that is the intended posture.

create table if not exists report_approval (
  id uuid primary key default gen_random_uuid(),
  prospect_id uuid not null references prospect(id) on delete cascade,
  snapshot_id uuid references scan_snapshot(id),
  content_hash text not null,
  approved_by uuid not null,          -- AR Tools profile id; cross-database, no FK (HANDOFF §2)
  created_at timestamptz not null default now()
);

create index if not exists report_approval_prospect_idx
  on report_approval (prospect_id, created_at desc);

alter table report_approval enable row level security;

revoke all on report_approval from anon, authenticated;

comment on table report_approval is
  'The explicit human approval behind a client-facing report PDF (report increment 4; '
  'reporting-layer-spec §4a). content_hash names the exact bytes approved; approved_by is an AR '
  'Tools profile id with no cross-database FK (HANDOFF §2). Service-role only.';
