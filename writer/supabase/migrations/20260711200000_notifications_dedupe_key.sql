-- Migration: 20260711200000_notifications_dedupe_key.sql
-- Purpose: PACE Phase 0B (docs/modules/project-manager-agent-plan-v1_0.md §6) —
--          atomic idempotency for the daily PACE digest. The scheduler's
--          in-memory "once today" guard resets on deploy, and a query-guard has
--          a rolling-deploy TOCTOU race; a unique key makes duplicate emits a
--          no-op at the database.
--
--          Nullable + unique: existing notifications keep a null key (Postgres
--          unique ignores nulls, so unrelated rows are unaffected); the PACE
--          digest inserts with dedupe_key = "pace_digest:<YYYY-MM-DD>:portfolio",
--          so a second insert the same day hits the constraint and no-ops.

alter table notifications add column if not exists dedupe_key text;

create unique index if not exists uq_notifications_dedupe_key
  on notifications (dedupe_key) where dedupe_key is not null;
