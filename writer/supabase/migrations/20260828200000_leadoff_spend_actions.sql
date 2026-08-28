-- leadoff_spend.action allowed set was {tryout, scout, ai_probe}, but record_spend
-- also writes 'city_finder' (city-finder run) and 'map_refresh' (Plot the live GBPs).
-- Those inserts violated leadoff_spend_action_check → 500 internal_error on the
-- endpoint (e.g. "Plot the live GBPs"). Widen the allowed set to every action the
-- code records. Superset of the old set, so no existing row is invalidated.
alter table public.leadoff_spend
  drop constraint if exists leadoff_spend_action_check;
alter table public.leadoff_spend
  add constraint leadoff_spend_action_check
  check (action = any (array['tryout', 'scout', 'ai_probe', 'city_finder', 'map_refresh']));
