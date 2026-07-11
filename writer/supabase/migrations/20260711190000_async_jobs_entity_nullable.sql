-- Migration: 20260711190000_async_jobs_entity_nullable.sql
-- Purpose: Allow suite-level async jobs to omit entity_id.
--          async_jobs.entity_id was NOT NULL, which only fits jobs scoped to a
--          single entity (a client, a GSC property, a maps scan). Genuinely
--          suite-level jobs have no single entity:
--            * task_due_sweep (the native task manager's daily due digest,
--              across all clients),
--            * task_import_asana (imports every mapped client's board),
--          both enqueue WITHOUT an entity_id and so failed the NOT NULL
--          constraint at runtime. (This also silently blocked suite-wide
--          notification_dispatch jobs — notifications.emit with client_id=None
--          — from ever enqueuing their email/Slack copy.)
--
--          Relaxing NOT NULL is safe: it never rewrites existing rows, and the
--          worker claims/reaps by status + scheduled_at and reads job payload,
--          never requiring entity_id. Client-scoped jobs keep passing it.

alter table async_jobs alter column entity_id drop not null;
