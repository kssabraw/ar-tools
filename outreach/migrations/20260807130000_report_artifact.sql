-- report_artifact — provenance for every rendered reporting asset. Reporting-layer-spec §2.
--
-- "Every report artifact MUST record what produced it, so a report shared in March regenerates
-- identically in June." This is the table the heatmap renderer (Phase 3 slice 1) writes to, and
-- the one the audit bundle, delta heatmap and client report will write to later — all five `kind`
-- values are created now so a later slice adds a renderer, not a column.
--
-- ---------------------------------------------------------------------------------------------
-- TWO DIVERGENCES FROM THE SPEC'S DDL, both deliberate:
--
-- 1. `score_run_id` carries NO foreign key. The spec writes `references score_run(id)`, but
--    `score_run` is the Phase 4 model's table and does not exist yet (START-HERE §3a; ISSUES
--    I-082). A heatmap needs no score run, so the column is nullable and unconstrained for now;
--    the FK lands with `score_run` in Phase 4. Logged as ISSUES I-090 so the FK is not forgotten.
--    Creating the column now (rather than later) keeps the artifact shape stable across slices.
--
-- 2. `subject_id` carries no foreign key either — and that one matches the spec. It is
--    polymorphic over `subject_type in ('prospect','submarket','market')`, so no single FK can
--    constrain it. The check on `subject_type` is the guard the schema can actually enforce.
--
-- ---------------------------------------------------------------------------------------------
-- ACCESS: service-role only, per the suite-module ruling (HANDOFF §2). RLS enabled, ZERO
-- policies, no grants to anon/authenticated — the same posture as every other table here. The
-- API layer (platform-api) is the only reader, and it holds the service-role key. Do NOT add an
-- RLS policy to silence the advisor's rls_enabled_no_policy notice; that is the intended state.

create table report_artifact (
  id                  uuid primary key default gen_random_uuid(),
  kind                text not null check (kind in
                        ('heatmap','heatmap_pair','heatmap_delta','audit_bundle','client_report')),
  subject_type        text not null check (subject_type in ('prospect','submarket','market')),
  subject_id          uuid not null,
  snapshot_id         uuid references scan_snapshot(id),
  compare_snapshot_id uuid references scan_snapshot(id),
  score_run_id        uuid,                        -- FK deferred to Phase 4 (ISSUES I-090)
  generator_version   text not null,
  geometry_version    text not null,
  storage_path        text not null,
  content_hash        text not null,
  generated_at        timestamptz not null default now(),
  expires_at          timestamptz
);

-- The subject-history read from spec §2: "the artifacts for this prospect, newest first".
create index report_artifact_subject_idx
  on report_artifact (subject_type, subject_id, generated_at desc);

-- Reporting §6: "Rendered artifacts are immutable for a given (inputs, generator_version). Cache
-- in R2 keyed by content_hash; never regenerate on identical inputs." A unique constraint on the
-- hash makes that structural: re-rendering identical inputs collides here and is upserted as a
-- no-op rather than piling up duplicate rows. Two different subjects render different bytes (the
-- pin and labels differ), so this never rejects a legitimately distinct artifact.
create unique index report_artifact_content_hash_key on report_artifact (content_hash);

alter table report_artifact enable row level security;

comment on table report_artifact is
  'Reporting-layer-spec §2 provenance for every rendered asset. Snapshot- and version-stamped so '
  'a render is reproducible and citable. Service-role only, RLS-on/zero-policy per HANDOFF §2. '
  'score_run_id FK deferred to Phase 4 (ISSUES I-090).';
