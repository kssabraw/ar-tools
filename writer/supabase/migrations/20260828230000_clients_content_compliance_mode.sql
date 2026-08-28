-- Per-client content-compliance guardrail mode.
--
-- Regulated clients (peptide / research-chemical vendors) must never publish
-- content that gives human dosing/administration instructions, claims parity
-- with a branded medication, promises guaranteed results, or advocates buying
-- the product. This column opts a client into the deterministic guardrail
-- (services/content_compliance.py), which blocks such content at every publish
-- choke point — including the fully-automated fan-out scheduler.
--
--   'off'      — no checks (default; every existing client is unchanged).
--   'peptide'  — full guardrail; all four categories block publishing.
--
-- Text (not an enum) so a new mode is a code change, not a migration; unknown
-- values are treated as 'off' by resolve_mode, so a typo can never silently
-- start blocking a client that was never meant to be regulated.
alter table clients
  add column if not exists content_compliance_mode text not null default 'off';

comment on column clients.content_compliance_mode is
  'Content-compliance guardrail mode: off | peptide. See services/content_compliance.py.';
