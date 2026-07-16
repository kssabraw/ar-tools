-- Migration: 20260716180000_notifications_recipient.sql
-- Purpose: per-user in-app notifications. Adds an optional recipient so a
--          notification can be targeted at ONE suite user (their nudges, task
--          assignments, @mentions) and surfaced in a personal header bell.
--          NULL recipient = agency/client-wide (unchanged behaviour — those
--          keep flowing to the per-client Alerts feed + Home badges only).
--
-- profiles.id == the auth user id, so the recipient is the logged-in user's id.
-- Additive + nullable: existing rows and producers are unaffected.

alter table notifications
  add column if not exists recipient_profile_id uuid references profiles(id) on delete cascade;

-- The personal-inbox read path: a user's newest notifications.
create index if not exists idx_notifications_recipient_created
  on notifications (recipient_profile_id, created_at desc)
  where recipient_profile_id is not null;

-- The unread-badge count path.
create index if not exists idx_notifications_recipient_unread
  on notifications (recipient_profile_id)
  where recipient_profile_id is not null and status = 'unread';
