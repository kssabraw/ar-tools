-- Migration: 20260711120000_backlink_review_fixes.sql
-- Purpose: Atomic daily-budget reservation for the Backlink Explorer.
--   The Python _reserve_budget did a read-modify-write (SELECT calls → compare
--   → UPSERT), so two concurrent interactive lookups could both read the same
--   `used` and each write used+n, overshooting the cap. This function does the
--   check-and-increment in a single UPDATE whose WHERE enforces the cap, so
--   concurrent reservations serialize on the row lock and can never overshoot.
--   Returns true when the reservation fit under the cap (and was applied),
--   false when it would exceed it (nothing incremented).

create or replace function reserve_backlink_calls(p_day date, p_n integer, p_cap integer)
returns boolean
language plpgsql
as $$
begin
  insert into backlink_usage (day, calls) values (p_day, 0)
    on conflict (day) do nothing;
  update backlink_usage
     set calls = calls + p_n
   where day = p_day and calls + p_n <= p_cap;
  return found;
end;
$$;
