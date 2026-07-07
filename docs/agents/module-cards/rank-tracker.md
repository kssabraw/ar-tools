# Module card — Organic Rank Tracker

**What it measures:** where the client's pages rank in Google's *web results*
for tracked keywords, plus the demand behind them (impressions/clicks).
Channel: organic SERP only — the local pack is the geo-grid tracker's job.

**Two instruments, not one:**
- **GSC** (`gsc_position`, daily): Google's own average position for queries
  that got impressions. **Impressions-weighted** — a #4 seen 10,000 times and a
  #4 seen 10 times are not the same fact; always read position with its
  impressions.
- **DataForSEO** (`tracked_rank`, scheduled live checks): one real SERP fetch.
  A point sample, not an average. Do not splice GSC and DataForSEO readings
  into one trend — they disagree legitimately.

**Direction:** lower = better (position 1 is the top).

**How to read the fields:**
- `gsc_position = null` → **no data that day** (no impressions, or GSC not
  connected). Never read null as "dropped out."
- `tracked_rank = null` → not found within the fetched SERP depth — could be
  ranking below it.
- Windows under ~20 impressions are noise — the drop classifier refuses to
  triage them; you should too.
- Alerts (`rank_alerts`): `weekly_drop` / `page_one_exit` / `thirty_day_drop` /
  `deindexed`; `resolved_at = null` means the episode is still open. Deindexed
  alerts are URL-Inspection-confirmed, not inferred.
- Competitor referring-domain reads are **tool-visibility discounted ×10**
  (SOP shared definition); client RD reads are not scaled.

**Known blind spots:** GSC only reports queries that got impressions (invisible
keywords produce no rows, not zeros); brand-new keywords have no baseline for
~2 weeks; position exists per query×page — cannibalization splits one query's
demand across pages.

**Worked misreading:** "gsc_position went from 6.2 to null — we lost the
ranking." Wrong: null = no impressions recorded (often seasonal demand dip or
GSC lag). A real loss shows as a *position increase* or an open
`page_one_exit`/`deindexed` alert, not a null.
