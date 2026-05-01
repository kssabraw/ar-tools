-- Add brand_guide_format and icp_format to client_context_snapshots.
-- These are needed by the orchestrator to drive Writer module behavior
-- (Writer treats markdown/json structured input differently from plain text).
alter table client_context_snapshots
  add column if not exists brand_guide_format text not null default 'text',
  add column if not exists icp_format         text not null default 'text';
