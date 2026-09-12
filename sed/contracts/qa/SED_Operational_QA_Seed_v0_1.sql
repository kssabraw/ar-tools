-- SED Operational QA / Wave Acceptance Contract v0.1
-- Seed skeleton for ops.qa_contract_version and ops.qa_rule.
-- Freeze only after artifact URI/SHA and pilot review are supplied.

with qac as (
  insert into ops.qa_contract_version (
    contract_code, version_code, status, notes
  ) values (
    'SED_WAVE_QA', '0.1', 'draft',
    'Operational QA / Wave Acceptance Contract v0.1; aligned to collection manifest v0.7 and physical schema v0.1.'
  )
  on conflict (contract_code, version_code) do update
    set notes = excluded.notes
  returning qa_contract_version_id
)
insert into ops.qa_rule (
  qa_contract_version_id, rule_code, scope, severity, description, rule_config
)
select qa_contract_version_id, x.rule_code, x.scope, x.severity, x.description, x.rule_config::jsonb
from qac
cross join (values
  ('QA-MAN-001','wave/job','critical','Job methodology version must equal wave methodology version.','{}'),
  ('QA-MAN-002','job','critical','job_key must be unique and match versioned generator hash.','{}'),
  ('QA-MAN-003','wave','critical','Database job membership must reconcile exactly to frozen manifest matrix.','{}'),
  ('QA-MAN-004','coordinate job','critical','Coordinate eligibility must be resolved before submission.','{"blocked_states":["pending","manual_review","configuration_failure"]}'),
  ('QA-MAN-005','coordinate job','critical','Structural-water exclusions must not be submitted or encoded as measured zero/nonappearance.','{}'),
  ('QA-MAN-006','chatgpt','critical','Each expected ChatGPT condition has exactly three fresh-context scientific jobs.','{"replicates":[1,2,3]}'),
  ('QA-OPS-001','job/observation','critical','At most one scientific observation per deterministic job.','{}'),
  ('QA-OPS-002','observation','critical','Accepted attempt must belong to the same job as observation.','{}'),
  ('QA-OPS-003','attempt','error','Attempt numbering should be contiguous from one unless a documented recovery path applies.','{}'),
  ('QA-OPS-004','observation/payload','critical','Returned observation retains accepted attempt and raw-response provenance.','{}'),
  ('QA-OPS-005','job','error','Retry-exhausted job terminates explicitly.','{}'),
  ('QA-OPS-006','timestamps','error','Event chronology must be temporally plausible.','{}'),
  ('QA-RAW-001','raw_blob','critical','Retained bytes hash must match ops.raw_blob.sha256.','{"hash":"sha256"}'),
  ('QA-RAW-002','raw_blob','critical','Accepted raw payload pointer must resolve in private Storage.','{}'),
  ('QA-RAW-003','raw_blob','critical','Storage path must not mutate to bytes with a different recorded hash.','{}'),
  ('QA-RAW-004','provider_payload','error','Provider payload provenance must be internally consistent.','{}'),
  ('QA-RAW-005','normalized output','error','Same parser version should deterministically reproduce normalized output hash.','{}'),
  ('QA-COST-001','cost','critical','Cost events are nonnegative and append-only.','{}'),
  ('QA-COST-002','cost','error','Nonzero paid cost attribution target is 99.9 percent.','{"target":0.999}'),
  ('QA-COST-003','cost','error','Applicable cost events reference provider price version or documented exception.','{}'),
  ('QA-COST-004','cost','warning','Unexplained unit-cost drift thresholds.','{"warning":0.10,"error":0.25,"critical":0.50}')
) as x(rule_code,scope,severity,description,rule_config)
on conflict (qa_contract_version_id, rule_code) do update
set scope=excluded.scope,
    severity=excluded.severity,
    description=excluded.description,
    rule_config=excluded.rule_config;
