# Runbook — Rank tracker "data stopped updating" (silent freeze)

**Symptom.** A client's organic rankings stop changing for days, or keywords
that are ranking fine show as **deindexed** / `deindex_risk`. Every scheduled
job reports success — nothing looks broken — but the tracker isn't learning
anything new.

This has happened twice, via two different mechanisms (a materialize read bug in
2026-07, an ingest-window bug in 2026-09). Both shared one signature: **data
silently stopped while jobs reported "ok."** The durable defense is the
freshness watch below; this runbook is for confirming + recovering.

## 1. Confirm it (which clients, how stale)

The **freshness watch** (`services/scan_health.py::run_rank_freshness_sweep`,
daily) posts a `rank_data_stale` alert to Slack + the in-app feed within ~24h of
data stopping, and a portfolio "N clients stalled" alert when several go at once.
To check directly:

```sql
-- Per-property GSC freshness (the usual culprit).
select p.site_url, p.access_status,
       max(d.date) as max_gsc_date, current_date - max(d.date) as days_stale,
       count(distinct d.date) filter (where d.date >= current_date - 30) as dates_30d
from gsc_properties p
left join gsc_query_daily d on d.property_id = p.id
where p.access_status = 'ok'
group by p.site_url, p.access_status
order by max_gsc_date;
```

- **`days_stale` large + `dates_30d` low (3–6)** → the ingest window isn't
  keeping up with GSC's lag (the 2026-09 mechanism). Recover with §2.
- **`access_status = no_access`** → the GSC service account was removed/never
  added for that property (e.g. `myihbs.com`'s 403). This is **not** a code fix:
  re-add the agency service account as a user on the Search Console property and
  re-verify (Rankings → Settings → connect). The `scan_health` failure-streak
  watch already alerts on this.

Per-keyword source freshness for one client:

```sql
select tk.keyword, tk.source, tk.status,
  max(m.date) filter (where m.gsc_position is not null) as last_gsc,
  max(m.date) filter (where m.tracked_rank is not null) as last_dfs
from tracked_keywords tk
left join rank_keyword_metrics m on m.keyword_id = tk.id
where tk.client_id = '<CLIENT_ID>'
group by tk.keyword, tk.source, tk.status;
```

## 2. Recover a stalled GSC property (backfill the gap)

Re-pull the missing finalized days by enqueuing `gsc_ingest` jobs **in ≤3-day
chunks**. Do NOT enqueue one wide (e.g. 20-day) window: a single un-chunked
upsert of ~75k rows hits the Postgres statement timeout (57014). ~3 days ≈ 15k
rows, which commits fine. (The deployed ingest now chunks its upserts, but a
manual DB-enqueued backfill still runs whatever the worker code does, so keep
chunks small.)

```sql
-- Backfill 08-27 → 09-16 for one property, 3-day chunks (adjust dates).
with chunks(s,e) as (values
  ('2026-08-27','2026-08-29'),('2026-08-30','2026-09-01'),
  ('2026-09-02','2026-09-04'),('2026-09-05','2026-09-07'),
  ('2026-09-08','2026-09-10'),('2026-09-11','2026-09-13'),
  ('2026-09-14','2026-09-16'))
insert into async_jobs (job_type, entity_id, payload)
select 'gsc_ingest', '<PROPERTY_ID>'::uuid,
       jsonb_build_object('property_id','<PROPERTY_ID>','start_date',c.s,'end_date',c.e)
from chunks c;
```

Each `gsc_ingest` chains a `gsc_materialize` on success, which recomputes status.
Verify: re-run the §1 query (max date advances) and check the client's keyword
statuses (false `deindex_risk` clears once fresh data lands). GSC's own ~2–3 day
lag means the last 2–3 days will still be empty — that's expected, not a stall.

## 3. Why it can't silently stall for days anymore

- **Ingest window** (`gsc_repull_days`) is 10 days, comfortably wider than GSC's
  lag, and every upsert is chunked — so finalized days can't scroll out of range
  before capture, and a wide catch-up can't time out.
- **`deindex_risk` is cross-source**: a live DataForSEO rank vetoes a "deindexed"
  verdict, so a GSC data gap alone never reads as a deindex.
- **DataForSEO steps in** once GSC is stale > `rank_gsc_stale_refetch_days` (5),
  via the weekly pull and an off-cadence scheduler trigger.
- **The freshness watch** (`rank_freshness_status` + the daily sweep) alerts the
  team within ~24h whenever *any* client's data stops advancing — whatever the
  cause — and the scheduled **combined** client report is **held** (team warned)
  rather than shipped on stale numbers (`client_report_schedule._rank_data_stale`).
  The standalone AI-Visibility / Maps reports draw on their own data sources and
  are not held by a rank-data stall.
- **Pipeline stall vs. total ranking loss.** A "stale" verdict means the tracker
  hasn't collected new data AND DataForSEO hasn't *actively* queried the SERP
  recently (`rank_fetch_config.last_active_fetch_at`, stamped only when it truly
  fetched ≥1 keyword — not a run that skipped everything as GSC-covered). A client
  that IS being checked but ranks for nothing (site dropped out) is `reason:
  current_not_ranking` → NOT flagged as a pipeline stall (its data is current);
  that ranking loss surfaces through the rank-drop / `unranked` / deindex alerts
  instead. This keeps the freshness alert from crying "pipeline down" when the
  real problem is rankings — without ever masking a genuine stall (only a recent
  *active* fetch rescues the verdict).

Config: `rank_freshness_enabled`, `rank_freshness_gsc_stale_days`,
`rank_freshness_df_stale_days`, `rank_freshness_portfolio_min`,
`gsc_repull_days`, `rank_gsc_stale_refetch_days`.
