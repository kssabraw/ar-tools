-- Migration: 20260723120000_gbp_scheduling_timezone.sql
-- Purpose: Express GBP post scheduling in the CLIENT'S local time, not UTC.
--   Previously a recurring schedule stored an `hour_utc` and one-off posts were
--   scheduled in the operator's browser timezone — neither adapts to a client in
--   a different timezone than the operator. Now the client's IANA timezone
--   (derived from the GBP location's lat/lng via Google's Time Zone API and
--   cached here) is the frame: the recurring hour is a client-local hour, and
--   naive one-off times are localized to the client before converting to UTC.
--   All stored timestamps stay UTC; only the human-facing frame changes.
--   See services/gbp_timezone.py + services/gbp_posts_service.py.
--
--   Safe rename: the GBP Posts module is gated off (gbp_api_enabled +
--   gbp_posts_enabled default false), so no live schedule is running; the column
--   rename is a pure semantic relabel (UTC hour → client-local hour).

-- The client's IANA timezone (e.g. 'America/Los_Angeles'); NULL until derived,
-- and NULL degrades scheduling to UTC (never breaks it).
alter table clients add column if not exists timezone text;

-- Recurring GBP post schedule: the hour is now interpreted in the client's local
-- timezone (resolved from clients.timezone at compute time), not UTC.
alter table gbp_post_schedules rename column hour_utc to hour_local;
