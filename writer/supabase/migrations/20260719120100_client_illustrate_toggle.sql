-- Per-client opt-in for auto-illustration of completed runs (hero + inline
-- body images/charts). Default off so bulk/mass runs never incur image spend
-- unless a client is explicitly enabled. On-demand illustration ignores this.
alter table clients add column if not exists illustrate_content boolean not null default false;
