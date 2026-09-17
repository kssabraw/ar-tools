-- Migration: 20260917120000_lead_callback_time.sql
-- Target:    Outreacher project (fkwhgvcggvsricuinuqy) — NOT AR-Internal-Tools.
-- Purpose:   Cold-caller CRM Tier 1.4 — a precise callback time + the prospect's timezone.
--            `next_action_due` is date-only, so "call back Tuesday 2pm THEIR time" is not
--            representable and a caller dialing across timezones (LA/KC/…) has no business-hours
--            signal. This adds the two columns that fix both.
--
-- WHY ADDITIVE, NOT A TYPE CHANGE (crm-layer-spec.md §5 Q2 — owner decision 2026-09-17):
-- migrating `next_action_due` (date) to timestamptz would change the meaning of "overdue" (a day
-- vs an instant) and every reader that compares it against `current_date` — the reporting-layer
-- v_overdue_actions view and services/outreach.py's `list_leads(overdue=…)` filter both do. So
-- `next_action_due` stays the day-level driver of the queue/overdue logic UNCHANGED, and a precise
-- callback is layered on top:
--
--   next_action_at   the resolved ABSOLUTE INSTANT of the callback (timestamptz). The application
--                    computes it from a wall-clock time entered in the prospect's zone, DST-correct
--                    via zoneinfo, and syncs next_action_due to that instant's LOCAL date — so
--                    booking a precise time never breaks the day-level overdue read.
--   next_action_tz   the prospect's IANA zone (e.g. 'America/Los_Angeles'). Used to (a) redisplay
--                    next_action_at as their local time and (b) drive the local-time / in-business-
--                    hours indicator on the card and queue. Plain text, no CHECK — the application
--                    validates it against zoneinfo (a bad value names itself as invalid_timezone
--                    rather than silently reading as an unknown zone). When null, the zone is
--                    guessed from the prospect's longitude, then the configured default.
--
-- Both nullable and defaulted to nothing: an existing lead is untouched, a day-only follow-up sets
-- neither, and the whole change is reversible by dropping the two columns.

alter table lead add column if not exists next_action_at timestamptz;
alter table lead add column if not exists next_action_tz text;

comment on column lead.next_action_at is
  'Cold-caller CRM (T1.4): the resolved absolute instant of a scheduled callback. Computed by '
  'platform-api from a wall-clock time in next_action_tz; next_action_due is kept in sync with its '
  'local date so day-level overdue/queue logic is unchanged. Null = no precise time booked.';
comment on column lead.next_action_tz is
  'Cold-caller CRM (T1.4): the prospect''s IANA timezone, used to interpret next_action_at and to '
  'compute the local-time / business-hours indicator. Plain text (no CHECK) — validated in the '
  'application against zoneinfo. Null = derive from prospect longitude, else the configured default.';

-- next_action_due already carries the index that drives the queue/overdue reads
-- (lead_next_action_due_idx). next_action_at is display/precision, not an ordering key, so it needs
-- no index of its own.
