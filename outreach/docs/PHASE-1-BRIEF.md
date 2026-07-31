# Phase 1 Brief — Ingest and Filter

**Self-contained.** Everything needed for Phase 1 is in this document. You do not need to read
`docs/PRD-prospect-pipeline.md` for this phase; it is 87 KB and ~95% of it describes later phases.

**Goal:** pull every business listing for one category in one city, drop the ones not worth
pursuing, and be able to explain every exclusion.

**Explicitly not in this phase:** scoring, scanning, geogrids, deltas, enrichment, audits,
outreach. Do not build them. Do not create `prospect_score`, `scan_snapshot`, or `grid_result`.

---

## 1. Tables to create

Only these six. Others exist in the specs but belong to later phases.

```sql
create table market (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  center_lat double precision not null,
  center_lng double precision not null,
  radius_miles numeric not null,
  scan_interval_days integer not null default 15,
  created_at timestamptz not null default now()
);

create table submarket (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  name text not null,
  center_lat double precision not null,
  center_lng double precision not null,
  grid_radius_miles numeric not null default 5,
  grid_spacing_miles numeric not null default 1,
  last_scanned_at timestamptz
);

create table keyword (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  term text not null,
  is_primary boolean not null default false,
  unique (market_id, term)
);

create table prospect (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  submarket_id uuid references submarket(id),
  place_id text not null unique,
  name text not null,
  category text,
  address text,
  phone text,
  phone_type text check (phone_type in ('mobile','landline','unknown')),
  website text,
  rating numeric,
  review_count integer,
  latest_review_at date,
  lat double precision,
  lng double precision,
  business_status text,
  franchise_status text not null default 'unknown'
    check (franchise_status in ('unknown','flagged','confirmed_franchise','confirmed_independent')),
  raw jsonb not null,
  ingested_at timestamptz not null default now()
);

create table filter_result (
  prospect_id uuid not null references prospect(id) on delete cascade,
  rule text not null,
  passed boolean not null,
  observed_value text,
  evaluated_at timestamptz not null default now(),
  primary key (prospect_id, rule)
);

create table cost_ledger (
  id bigserial primary key,
  market_id uuid references market(id) on delete cascade,
  cycle_number integer,
  stage text not null,
  provider text not null,
  units integer not null,
  cost_cents integer not null,
  recorded_at timestamptz not null default now()
);
```

---

## 2. Stage A1 — Ingest (Outscraper)

- MUST accept a job spec of `{market, categories[], geography}` and fan out one query per
  category × geographic tile.
- MUST tile large metros. Google caps results per query area; a single "plumbers in Los Angeles"
  query will not return the full market. Tile by submarket centroid with overlapping radii and
  deduplicate on `place_id`.
- MUST use the async request pattern (POST returns a request ID; poll or receive webhook).
  Synchronous calls will time out at market scale.
- MUST persist the full raw response to `prospect.raw` **before** parsing. Re-parsing from stored
  raw is free; re-pulling is not.
- MUST capture `phone_type` where available.
- MUST record actual cost per request in `cost_ledger`.
- MUST request **base tier only**. Enrichment services are billed separately and belong to
  Phase 5. Do not enable them.

> **Verify endpoint paths and parameter names against Outscraper's live API reference.** They
> have changed across versions; do not trust field names copied from a spec.

---

## 3. Stage A2 — Filter

Applied in order. All thresholds config-driven.

| Rule | Default | Type |
|---|---|---|
| `business_status` closed (permanent or temporary) | exclude | hard |
| No phone number | exclude | hard |
| Present in `suppression` (any scope) | exclude | hard *(table does not exist yet — see below)* |
| Franchise / chain name pattern match | **flag for review** | soft |
| Review count < 10 | exclude | soft, configurable |
| No review within 9 months | exclude | soft, configurable |

### Requirements

- MUST log every exclusion to `filter_result` with the triggering rule **and every other rule the
  prospect would also have failed.** Dead listings typically fail three gates at once;
  first-match-only logging produces misleading tuning data.
- **Franchise matches flag, never exclude.** Set `franchise_status = 'flagged'`. A false positive
  is a permanently lost prospect, and plenty of independents carry chain-like names. Flagged
  prospects proceed through the pipeline but must not be contacted until reviewed.
- Review recency uses an **absolute 9-month window**. A relative mode (velocity drop against the
  business's own baseline) is more correct but needs history that does not exist yet.
- `suppression` belongs to Phase 5 and will be empty in Phase 1. Write the check now as a
  left-join that tolerates a missing or empty table, so it is not retrofitted later.

---

## 4. Cost guardrails

- MUST estimate cost before executing the paid stage and abort if the projection exceeds
  `max_market_run_cost_cents` (default 5000 = $50 per market-vertical).
- `cost_ledger` MUST record real reported cost, not estimates.
- Expected Phase 1 cost for one market-vertical: **$2–4** (Outscraper base pull, ~1,000–1,500
  listings before dedup).

---

## 5. Acceptance criteria

- [ ] Raw response persisted before parsing
- [ ] Deduplication on `place_id` across overlapping tiles
- [ ] Every filter exclusion logs all failing rules, not just the first
- [ ] Franchise pattern matches flag, never exclude
- [ ] Suppression check present and tolerant of an empty table
- [ ] No scoring — `prospect_score` is not written in this phase
- [ ] Run aborts before exceeding `max_market_run_cost_cents`
- [ ] `cost_ledger` totals reconcile against the Outscraper dashboard within 5%

---

## 6. Definition of done

One real market-vertical ingested and filtered. You can answer, from SQL alone:

1. How many listings were pulled, and what it cost.
2. How many survived, and how many failed each rule.
3. For any excluded business, which rules it failed.
4. Which businesses are flagged as possible franchises and await review.

That is the whole phase. Stop there and report before starting Phase 2.

---

## 7. If something is ambiguous

Log it in `ISSUES.md` and choose the interpretation that is cheapest to reverse. Do not edit the
specs to resolve ambiguity, and do not pull work forward from later phases to make something fit.
