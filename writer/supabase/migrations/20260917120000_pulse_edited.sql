-- Weekly Pulse editable-save protection (owner request 2026-09-17): a manual
-- Save marks the pulse `edited`, so neither the weekly auto-generation nor the
-- Regenerate button silently overwrites a staff-tweaked copy. A forced
-- regenerate (explicit "replace my edits") clears the flag back to false.
-- A fresh week always starts a new row with edited=false.

alter table client_pulses
  add column if not exists edited boolean not null default false;
