-- =============================================================================
-- prospect_call_hook — the cached, loss-framed LLM phrasing of the per-prospect
-- "Why call?" hook.
--
-- The hook is assembled deterministically (services/outreach_justification.py) and
-- then rewritten into compelling, loss-framed, per-prospect prose by a grounded
-- LLM pass (services/outreach_call_hook.py). That pass is non-deterministic and
-- costs a paid call, so its output is CACHED here per (prospect, snapshot):
-- determinism/replayability lives at the cache (a re-read returns the stored hook
-- byte-for-byte; reporting-layer-spec §2/§6) rather than at the model, and the LLM
-- is called once per prospect×snapshot, not per report open.
--
-- `facts_fingerprint` is a SHA-256 over the DETERMINISTIC facts that fed phrasing
-- (the hook element + each talking point's element + facts, never its prose). A
-- re-read whose fingerprint matches returns the cache; a new scan changes a number
-- → new fingerprint → regenerate. So a stale hook can never outlive the facts it
-- was built from.
--
-- House posture (HANDOFF §2): RLS on, ZERO policies, service-role only. The revoke
-- is the statement that does something (Supabase grants ALL to anon/authenticated
-- by default). Do NOT add an RLS policy to silence the advisor.
-- =============================================================================

create table if not exists prospect_call_hook (
  id uuid primary key default gen_random_uuid(),

  prospect_id uuid not null references prospect(id)      on delete cascade,
  snapshot_id uuid not null references scan_snapshot(id) on delete cascade,

  -- SHA-256 of the deterministic facts that fed phrasing. A mismatch on read means
  -- the scan changed, so the cached hook is ignored and regenerated.
  facts_fingerprint text not null,

  -- The generated loss-framed opener, and the rephrased talking points (keyed by
  -- element; the element+facts stay the deterministic ones, so this is prose only).
  hook           text  not null,
  talking_points jsonb not null default '[]'::jsonb,

  -- provider:model that produced it, for provenance / debugging a bad hook.
  model text,

  generated_at timestamptz not null default now(),

  -- One cached hook per prospect × snapshot — the upsert target.
  unique (prospect_id, snapshot_id)
);

alter table prospect_call_hook enable row level security;
revoke all on prospect_call_hook from anon, authenticated;

comment on table prospect_call_hook is
  'Cached loss-framed LLM phrasing of the per-prospect call hook (2026-08-10). Keyed by (prospect, '
  'snapshot); facts_fingerprint invalidates it when the scan changes, so a re-read is an identical '
  'replay (reporting-spec §2/§6) and the LLM runs once per prospect×snapshot. Service-role only.';
