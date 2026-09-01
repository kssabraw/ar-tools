-- PACE PM designation (owner ruling 2026-09-01).
--
-- A "PACE PM" is a named person authorized for the two board-level PACE
-- operations that are the human PM's job: approving the daily Chase Plan and
-- manually generating a client's monthly board. Admins are implicitly PMs; a
-- non-admin (e.g. a staff PM like Minda) becomes one via this flag.
--
-- This is deliberately a per-person flag, NOT a role: the PM set is a named few
-- (not "any staff" — a staff VA must not silently gain these powers), and it
-- survives a handoff by moving the flag rather than changing anyone's role.
alter table profiles
    add column if not exists is_pace_pm boolean not null default false;

comment on column profiles.is_pace_pm is
    'PACE PM: may approve the daily Chase Plan and manually generate monthly boards. Admins are implicitly PMs regardless of this flag.';
