# Storage & Retention Spec v0.5

**Module:** `outreach-pipeline` (AR Tools)
**Sibling of:** `PRD-prospect-pipeline.md`, `scoring-spec.md`
**Platform:** Supabase (Postgres 15+, Storage, pg_cron)

---

## 1. The problem in one number

`grid_result` is ~99% of all rows the system will ever write.

```
81 grid points × ~20 results per point   =  1,620 rows per snapshot
10 submarkets × 3 keywords               =     30 snapshots per cycle
                                         = 48,600 rows per cycle
× 24 cycles/year (semi-monthly)          =  1.17M rows/year per market-vertical
× 50 market-verticals (5 verticals × 10 cities)
                                         =    58M rows/year
```

> **Corrected 2026-08-01: 81 points, not 89.** The grid holds 81 points, not the 89 this
> arithmetic assumed — see ISSUES I-025. Every figure below is ~9% lower than previously stated.
> **The conclusion is unchanged in every respect**: the Pro allowance is still exhausted inside
> year one, and partitioning is still a Phase 2 prerequisite rather than a later optimisation.
> A 9% correction does not move a ceiling that arrives 12 months out to one that arrives 13.

At ~120 bytes/row including index overhead, that is **~7.0 GB/year from one table**. Add SERP
payloads and LLM responses and year one lands near **9 GB**.

Supabase Pro includes 8 GB of database storage at $25/month, with roughly $0.125 per GB-month
beyond that. Naive append-forever therefore **exhausts the Pro allowance inside the first year**
and grows unbounded after.

> **Revised at the 50-market-vertical portfolio size.** An earlier draft of this document assumed
> 12 market-verticals and concluded the ceiling arrived in year three. At the recorded portfolio
> — 5 verticals × 10 cities — it arrives in **year one**. The retention policy is therefore not a
> year-three optimisation; **partitioning and rollup MUST be in place before the second scan cycle
> writes data.** Retrofitting them onto a multi-gigabyte unpartitioned table is materially harder
> than building them first.

With the policy in this document, steady-state Postgres settles near **2 GB**, growing ~550
MB/year — comfortably inside Pro for roughly a decade.

---

## 2. Governing principle: replaceability, not size

Retention priority is inverted from data volume.

| Data | Size | Replaceable? |
|---|---|---|
| `grid_result`, `serp_result` | Huge | **Yes** — rescan for cents |
| `outcome`, `touch` | Tiny | **No** — cannot be recreated at any price |
| `prospect_score.score_factors` | Small | No — needed to join scores to outcomes |
| `audit_evidence`, `asset_engagement` | Small | No — the causal record |

The expensive data is cheap to lose. The cheap data is impossible to lose. Every rule below
follows from that.

---

## 3. Retention tiers

### 3.1 Permanent — never deleted

- `outcome`, `touch` — the entire learning substrate
- `prospect_score` including `score_factors` — required to join scores to outcomes at refit
- `audit_asset`, `audit_evidence`, `asset_engagement` — evidence attribution record
- `scan_snapshot` **metadata** (not results) — provenance and geometry reproducibility
- `prospect_coverage` (§4) — rolled-up trend history
- `case_study`, `slot`, `conflict_check`, `cost_ledger`
- `market`, `submarket`, `keyword`, `prospect` (current state, upserted not appended)

Combined growth: **under 50 MB/year.** These tables scale with *contacts*, not markets — contact
volume is capacity-bound at 100 prospect starts/month regardless of portfolio size, so this term
does not grow when markets are added.

### 3.2 Hot — full detail, 90 days

- `grid_result`, `serp_result` for all submarkets

90 days = 6 cycles. Deltas need 3 snapshots (~45 days); the extra margin allows recomputation if
delta logic changes without a rescan.

### 3.3 Referenced — retained while cited

Any snapshot cited by a dispatched `audit_asset` MUST be retained at full detail **indefinitely**,
regardless of age. If a prospect disputes a claim, the backing data must exist. Volume is
negligible — roughly 20 snapshots per cycle out of 30.

### 3.4 Client — retained at full detail

> **Cap the promise contractually.** The client-history feature creates a permanent, unbounded
> retention obligation: once you have promised pre-engagement history, that data can never be
> downsampled, and the obligation grows with client count indefinitely. Contracts SHOULD say
> "history since tracking began" with a defined floor (e.g. 24 months), not "forever." Fine at
> current scale; expensive to unwind later.


Any submarket with a `slot` in state `filled` MUST retain full detail indefinitely. This is the
product: a client's pre-engagement ranking history is the differentiator established in PRD §8,
and downsampling it would destroy the thing that makes it valuable.

### 3.5 Cold — rolled up and dropped

Everything else: aggregate to `prospect_coverage`, drop the raw partition.

---

## 4. The rollup

One row per prospect per snapshot replaces ~1,780 raw rows per snapshot — a **~46× reduction**
that preserves everything trend charts, client reports, and delta recomputation need.

```sql
create table prospect_coverage (
  prospect_id     uuid not null references prospect(id) on delete cascade,
  snapshot_id     uuid not null references scan_snapshot(id) on delete cascade,
  coverage_pct    numeric(5,2) not null,   -- % of live grid points where present
  points_present  smallint not null,
  live_points     smallint not null,       -- denominator after land masking
  avg_rank        numeric(4,2),
  best_rank       smallint,
  worst_rank      smallint,
  centroid_dist_at_loss numeric(5,2),      -- miles from pin where they drop out
  rank_vector     bytea not null,          -- 1 byte per grid point, ordered by point_seq
  primary key (prospect_id, snapshot_id)
);
```

- The rollup MUST be computed and verified **before** the raw partition is dropped, never after.
- `centroid_dist_at_loss` is what drives the geogrid pain coefficient and the "invisible past N
  miles" line, so it MUST survive rollup even though it is derived.
- `live_points` MUST be stored, not recomputed. Land masking (PRD §9a.1) changes the denominator
  over time; without the contemporaneous value, historical coverage figures become
  uninterpretable.
- At 400 prospects × 3 keywords × 24 cycles × 50 market-verticals: **~1.44M rows/year ≈ 245 MB**
  including the rank vector.

### `rank_vector` — why the rollup keeps per-point detail

Aggregate statistics cannot reproduce a heatmap. Without per-point ranks, a submarket that is
neither a client nor cited by a dispatched audit loses the ability to render **any** historical
heatmap once its raw partition is dropped — you would retain the numbers and lose the picture,
including the second-touch material ("here is how your coverage looked in March") that makes
follow-up land.

- One unsigned byte per grid point, ordered by `point_seq`, aligned to the snapshot's geometry.
- Encoding: `0` = absent, `1–20` = rank, `255` = dead point (land-masked or not scanned).
- ~81 bytes per prospect-snapshot; roughly **28 MB/year** across the portfolio, versus the ~1.8 GB
  of raw rows it replaces. About a 20× saving while preserving full renderability.
- `point_seq` ordering MUST match the snapshot's pinned geometry generator, or historical vectors
  will render against the wrong coordinates.
- The vector is sufficient for heatmap rendering and for recomputing every coverage statistic,
  so it also serves as a verification path if a rollup is ever suspected of being wrong.

---

## 5. Partitioning — required, not optional

At 15M rows/year, `DELETE` is the wrong tool: it leaves dead tuples, forces vacuum, and bloats
indexes. Partition by month and `DROP PARTITION` instead — near-instant, no bloat.

```sql
create table grid_result (
  id           bigserial,
  snapshot_id  uuid not null references scan_snapshot(id) on delete cascade,
  scan_month   date not null,          -- partition key, denormalized from snapshot
  point_seq    smallint not null,
  place_id     text not null,
  rank         smallint not null,
  primary key (id, scan_month)
) partition by range (scan_month);

-- one partition per month, created ahead by pg_cron
create table grid_result_2026_08 partition of grid_result
  for values from ('2026-08-01') to ('2026-09-01');

create index on grid_result (snapshot_id, place_id);
```

**Drop lat/lng from `grid_result`.** Point coordinates are fully derivable from
`scan_snapshot.{center, grid_radius_miles, grid_spacing_miles}` plus `point_seq`. Storing them
per row duplicates 16 bytes across ~20 results per point — roughly **240 MB/year wasted** at 12
market-verticals. Store the generator parameters (already in `scan_snapshot`) and a pinned
generator function version so historical geometry stays reproducible.

`serp_result` SHOULD be partitioned identically.

---

## 6. Blobs belong in Storage, not Postgres

Pro includes <cite index="16-1">8 GB of database but 100 GB of file storage</cite> — a 12.5×
larger allowance for the same $25. Raw API payloads are write-once, read-rarely, and large:
exactly the wrong shape for Postgres and the right shape for object storage.

Move to Supabase Storage, keeping only a path plus parsed summary in Postgres:

| Column | Current | Volume/year (12 pairs) |
|---|---|---|
| `serp_result.payload` | jsonb | ~250 MB |
| `ai_check.raw` | jsonb | ~120 MB |
| `prospect.raw` | jsonb | ~100 MB steady |

```sql
alter table serp_result add column payload_path text;   -- storage object key
alter table serp_result add column payload_summary jsonb; -- parsed fields only
```

- Parsed fields the pipeline actually queries (ranking domains, paid slots, AIO presence) MUST
  stay in Postgres as `payload_summary`. Only the untouched remainder moves.
- Object keys SHOULD follow `{market}/{submarket}/{snapshot_id}.json.gz` and MUST be gzipped —
  SERP JSON compresses roughly 5–8×.
- Storage objects follow the same retention tiers as their parent rows.

---

## 7. Automation (pg_cron)

Supabase ships `pg_cron`; no external scheduler needed for retention.

| Job | Cadence | Action |
|---|---|---|
| `create_partitions` | Monthly | Create next two months' partitions ahead of need |
| `rollup_coverage` | Daily | Compute `prospect_coverage` for snapshots lacking it |
| `drop_cold_partitions` | Monthly | Drop partitions >90d, **excluding** referenced and client submarkets |
| `export_irreplaceable` | Weekly | Logical dump of §3.1 tables to Storage |
| `vacuum_analyze` | Weekly | On non-partitioned hot tables |

**`drop_cold_partitions` MUST verify before dropping:**
1. Rollup exists and row-count reconciles for every snapshot in the partition
2. No snapshot in the partition is referenced by a dispatched `audit_asset`
3. No snapshot belongs to a submarket with a `filled` slot

A partition failing any check is retained and logged, never partially dropped. Because
referenced and client snapshots are interleaved with cold ones inside the same monthly
partition, the job MUST relocate survivors to a `grid_result_retained` table before dropping —
or partition by `(scan_month, retention_class)` if the operational simplicity is worth the
composite key.

---

## 8. Backup posture

Pro includes daily backups with 7-day retention; PITR is a paid add-on.

**Do not buy PITR for this workload.** Seven days covers operational accident recovery, and the
large tables are reconstructible by rescan for a few dollars. What is not recoverable is §3.1 —
outcome history, score factors, evidence attribution — which is why `export_irreplaceable` dumps
those to Storage weekly. That job is worth more than PITR here and costs nothing.

Retain 12 weekly exports. Total footprint under 1 GB.

---

## 9. Egress and query hygiene

Pro includes <cite index="22-1">250 GB egress, then roughly $0.09 per GB.</cite> Unlikely to
bind, but two rules keep it that way:

- Never `SELECT *` on tables carrying jsonb. Payload columns MUST be requested explicitly.
- Coverage computations MUST aggregate in Postgres (SQL, or an RPC), not by pulling raw
  `grid_result` rows into FastAPI. Pulling 53,400 rows per cycle to compute percentages in
  Python is both slow and billed.

---

## 10. Row-level security

The client-history feature (PRD §8) exposes scan data to end clients. If that surfaces through
Supabase client libraries rather than the FastAPI backend:

- RLS MUST be enabled on `prospect_coverage`, `scan_snapshot`, and `prospect`.
- Policies MUST scope to submarkets where the requesting client holds the `filled` slot.
- Prospect-stage data (scores, `score_factors`, conflict flags, `outcome`) MUST NOT be reachable
  by client roles under any policy. A client seeing their own prospecting score, or a
  competitor's, is a serious disclosure.

If all client access routes through FastAPI with the service role, RLS is defence in depth
rather than the primary control — enable it anyway.

---

## 11. Projected footprint

| Component | Year 1 | Steady state |
|---|---|---|
| `grid_result` (90d hot, partitioned) | 1.9 GB | 1.9 GB |
| `prospect_coverage` (incl. rank vectors) | 245 MB | +245 MB/yr |
| Permanent tables (§3.1) | ~50 MB | +50 MB/yr |
| Referenced + client retained | ~250 MB | **+250 MB/yr, rising with client count** |
| **Postgres total** | **~2.0 GB** | **~2.0 GB + ~550 MB/yr** |
| Object storage, R2 (gzipped blobs) | ~1.6 GB | +1.6 GB/yr |

Comfortably inside Pro's 8 GB for roughly **a decade**, against **year one** without the policy.
Effective cost: **$25/month flat**, no overage.

> **Note which terms scale with what.** The hot window scales with *market count*; permanent
> retention scales with *contacts and clients*, which are capacity-bound. Adding markets grows the
> 1.9 GB figure; adding clients grows the annual term. Doubling the portfolio would roughly double
> steady state and should be accompanied by revisiting the hot window.

---

## 11a. Recorded decisions

**Hot window — 90 days (6 cycles).** Deltas need 3 snapshots (~45 days); the extra margin allows
delta logic to change without a rescan. Raw is ~1.9 GB at this window — the largest single term in the
footprint, so this is worth revisiting if the portfolio grows well past 50 market-verticals.

**Retention class — relocate survivors on drop.** The composite partition key
`(scan_month, retention_class)` is cleaner at drop time but adds a column to every query touching
`grid_result` for the life of the system. Relocation concentrates the complexity in one monthly
job instead of spreading it across every read path.

```sql
create table grid_result_retained (
  like grid_result including defaults including indexes
);
```

- `drop_cold_partitions` MUST copy surviving rows — cited snapshots (§3.3) and client submarkets
  (§3.4) — into `grid_result_retained` and verify the copy **before** dropping the partition.
- Verification MUST compare row counts per snapshot, not partition totals. A partial copy that
  happens to match on aggregate is the failure this guards against.
- Reads spanning both tables SHOULD go through a `UNION ALL` view so callers do not need to know
  which table holds a given snapshot.
- The job MUST be idempotent. An interrupted run that already copied some snapshots must be
  safely re-runnable.

**Blob offload — staged.** Payloads land in Postgres at scan time and migrate to R2 on schedule.
Direct-to-R2 is simpler but couples scan success to object-store availability; staged keeps the
scan write path local and makes retry-on-failure trivial, which matters under unattended
overnight execution.

- `payload_path IS NULL` means *not yet migrated*, not *absent*. Readers MUST fall back to the
  in-Postgres column and MUST NOT treat null as missing data.
- The migration job MUST verify the object is readable from R2 before nulling the Postgres
  column.
- Migration lag MUST be monitored. A stalled migrator silently reverts the storage model to
  all-in-Postgres, which is the growth curve this design exists to avoid.

---

## 12. Acceptance criteria

- [ ] `grid_result` and `serp_result` partitioned by month; retention via `DROP PARTITION`
- [ ] No lat/lng stored on `grid_result`; coordinates derived from snapshot parameters
- [ ] Grid generator function version pinned per snapshot for historical reproducibility
- [ ] Rollup computed and reconciled before any raw partition is dropped
- [ ] Survivors copied to `grid_result_retained` and verified per-snapshot before drop
- [ ] Drop job idempotent and safely re-runnable after interruption
- [ ] Reads span retained and live partitions transparently
- [ ] `payload_path IS NULL` treated as not-yet-migrated, never as absent
- [ ] R2 object verified readable before the Postgres payload column is nulled
- [ ] Blob migration lag monitored and alerted
- [ ] Referenced snapshots (cited by dispatched assets) never dropped
- [ ] `filled`-slot submarkets never downsampled
- [ ] `centroid_dist_at_loss` survives rollup
- [ ] `rank_vector` written on every rollup row; heatmaps renderable from rollup alone
- [ ] `rank_vector` ordering matches the snapshot's pinned geometry generator
- [ ] `live_points` stored contemporaneously, never recomputed from current masking
- [ ] Coverage statistics recomputable from `rank_vector` and reconcile with stored values
- [ ] Blob payloads in Storage, gzipped, with parsed summaries retained in Postgres
- [ ] `export_irreplaceable` runs weekly; 12 exports retained
- [ ] No `SELECT *` against jsonb-bearing tables
- [ ] Coverage aggregation executes in Postgres, not application code
- [ ] RLS enabled on client-reachable tables; prospect-stage data unreachable by client roles

---

## 13. Open decisions

4. ~~**Storage vs Cloudflare R2**~~ — **DECIDED: R2.** See PRD §15a.
   client-facing historical reports get heavy, worth revisiting.
