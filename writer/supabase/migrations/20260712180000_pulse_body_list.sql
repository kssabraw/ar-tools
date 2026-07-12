-- Weekly Pulse list view (owner request 2026-07-12): store BOTH renders per
-- pulse — `body` stays the client-ready narrative email, `body_list` is the
-- deterministic at-a-glance bullet version — so the workspace panel can toggle
-- Email ↔ List and the copy button follows the active view. Older rows have a
-- null body_list until their next (re)generation; the panel falls back to body.

alter table client_pulses
  add column if not exists body_list text;
