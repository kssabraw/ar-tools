-- Social P4 (Phase C) — the opt-in social QA rubric. Applied live 2026-09-19.
--
-- 1. social_policy.qa_gate: per-client opt-in. When on, a deterministic social rubric
--    (voice / banned-claims / CTA / platform / image, via qa_signals.build_verdict) runs
--    before a draft is auto-queued (blocks ANY failure — the autonomy guard) or manually
--    published (blocks a CRITICAL fail — a guide-forbidden voice term or a banned regulated
--    claim — with a force override). Default false → today's behavior (no QA call).
-- 2. social_drafts.qa_verdict: the persisted review on the draft. qa_reviews.task_id is
--    NOT NULL (task-scoped) and can't hold a draft-scoped review, so the verdict lives on
--    the draft (surfaced in the Drafts UI). No new async_jobs type — the rubric is
--    deterministic and runs inline in the fan-out job / publish path.
alter table social_policy add column if not exists qa_gate boolean not null default false;
alter table social_drafts add column if not exists qa_verdict jsonb;
