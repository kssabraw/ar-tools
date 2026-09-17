-- Rank-data freshness watch (the dead-man's switch for the Organic Rank Tracker).
--
-- scan_health alerts when scheduled data-collection jobs FAIL. This table backs
-- the complementary watch for the more insidious failure both prior silent
-- freezes shared: jobs succeed but the data stops advancing (GSC returns 0 rows
-- inside its lag window, a materialize bug freezes the axis, …). A daily sweep
-- (services/scan_health.py::run_rank_freshness_sweep) records one row per client
-- with tracked keywords, edge-triggering a Slack + in-app alert on the ok→stale
-- transition and a recovery notice on stale→ok, so reporting can never silently
-- stall for days again unnoticed. Also the source of truth for the portfolio
-- "N clients stale" escalation and the UI "data last updated" freshness read.
create table if not exists rank_freshness_status (
    client_id       uuid primary key references clients(id) on delete cascade,
    status          text not null default 'ok',   -- 'ok' | 'stale'
    last_data_at    date,                          -- freshest date the tracker has ANY rank data for
    days_stale      int,
    threshold_days  int,
    stale_since     timestamptz,                   -- when this client last transitioned ok→stale
    updated_at      timestamptz not null default now()
);

alter table rank_freshness_status enable row level security;
-- No policies: service-role (the backend) bypasses RLS; the anon/authenticated
-- clients never read this table directly (it is surfaced via the API).
