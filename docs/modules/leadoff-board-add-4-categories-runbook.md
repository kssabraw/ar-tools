# LeadOff — adding 4 categories to the precomputed board (scanner runbook)

**Owner-machine runbook.** Adds four GBP categories to the LeadOff catalog and
(optionally) the precomputed board:

| # | Category (GBP name — use verbatim) | `category_id` | `cluster` | `demand_profile` | CPL low / mid / high |
|---|---|---|---|---|---|
| 1 | **Fire damage restoration service** | `fire_damage_restoration_service` | Restoration | `aging_home_systems` | **75 / 138 / 200** |
| 2 | **Dumpster rental service** | `dumpster_rental_service` | Handyman/Repair | `renovation_equity` | **20 / 45 / 70** |
| 3 | **Carpenter** | `carpenter` | Remodeling/Renovation | `renovation_equity` | **25 / 50 / 75** |
| 4 | **Dryer vent cleaning service** | `dryer_vent_cleaning_service` | HVAC | `maintenance_indoor` | **20 / 40 / 60** |

The `category_name` must match Google's exact GBP category string (the scanner
queries it verbatim as the Maps keyword and matches `exact_open` holders on it).
`category_id` is the snake_case slug of the name (the scanner's convention —
e.g. `air_duct_cleaning_service`, `water_damage_restoration_service`).

`cluster` / `demand_profile` are set to each new category's **closest already-scanned
sibling** so the sabermetric layer behaves sanely from day one:

- Fire damage → mirrors `water_damage_restoration_service` (Restoration /
  `aging_home_systems`, 75/138/200) — same event-driven restoration economics.
- Dryer vent cleaning → mirrors `air_duct_cleaning_service` (HVAC /
  `maintenance_indoor`, 20/40/60) — effectively the same service family.
- Carpenter → the `renovation_equity` trades (`cabinet_maker`, `deck_builder`,
  `stair_contractor` …).
- Dumpster rental → no exact sibling in the taxonomy; `renovation_equity` (demand
  tracks renovations/cleanouts) + `Handyman/Repair` are best-fit. **Owner's call** —
  adjust if you'd rather it sit under a waste/junk grouping.

`demand_profile` only affects the board's **xdemand** regression (it buckets a
category to a per-capita demand expectation, killing outlier cities). It does NOT
affect the on-demand grader (which uses raw observed volume, like the tryout).

---

## Two levels — pick what you need

**Level A — catalog only (≈ $0, do this first).** Add the 4 rows to the catalog
(CSVs + the Supabase mirror). This alone makes the **on-demand grader**
(`/leadoff/grade`, the "type a city + a service → grade" tool) treat these 4 as
**on-catalog**: it resolves the typed service to the real category and uses the
real CPL above instead of the flagged default. Each lookup still grades *live*
(~$0.06, cached) until Level B lands — but with the correct lead value.

**Level B — precompute the board (~$75–90, later).** Run the gated scan for the
4 new categories across the board's cities and publish, so these markets answer
**instantly and free** on the board / grader (and appear in Board filters, the
market brief, and tryouts). Only worth it once you want them browsable, not just
gradeable on demand.

---

## Level A — catalog add

### A1. Edit the input CSVs (authoritative source of truth)

On the scanner machine, in `inputs/`:

**`categories.csv`** — append (columns: `category_id, category_name, gbp_category_id, demand_profile`; `gbp_category_id` is unused today, leave blank):

```csv
fire_damage_restoration_service,Fire damage restoration service,,aging_home_systems
dumpster_rental_service,Dumpster rental service,,renovation_equity
carpenter,Carpenter,,renovation_equity
dryer_vent_cleaning_service,Dryer vent cleaning service,,maintenance_indoor
```

**`lead_values.csv`** — append (columns: `category_name, cluster, cpl_low, cpl_mid, cpl_high`):

```csv
Fire damage restoration service,Restoration,75,138,200
Dumpster rental service,Handyman/Repair,20,45,70
Carpenter,Remodeling/Renovation,25,50,75
Dryer vent cleaning service,HVAC,20,40,60
```

> The board is 100 categories today; these take it to 104. `check_city.py`'s
> hard-coded `"… of 100 categories"` log line is cosmetic — it reads
> `len(cats.category_name)` for the real work, so no code change is required.

### A2. Mirror to Supabase so the app sees them now

The catalog CSVs are mirrored into `market_scanner.categories` / `.lead_values`
(the 2026-07-09 mirror, per `scanner-CLAUDE.md`). Re-run your
`migrate_inputs.py` mirror, **or** apply this idempotent upsert once via the
admin MCP / psql (the loader role can't DDL, but these are plain upserts on
existing tables):

```sql
insert into market_scanner.categories (category_id, category_name, gbp_category_id, demand_profile) values
  ('fire_damage_restoration_service','Fire damage restoration service',null,'aging_home_systems'),
  ('dumpster_rental_service','Dumpster rental service',null,'renovation_equity'),
  ('carpenter','Carpenter',null,'renovation_equity'),
  ('dryer_vent_cleaning_service','Dryer vent cleaning service',null,'maintenance_indoor')
on conflict (category_id) do update
  set category_name = excluded.category_name,
      demand_profile = excluded.demand_profile;

insert into market_scanner.lead_values (category_name, cluster, cpl_low, cpl_mid, cpl_high) values
  ('Fire damage restoration service','Restoration',75,138,200),
  ('Dumpster rental service','Handyman/Repair',20,45,70),
  ('Carpenter','Remodeling/Renovation',25,50,75),
  ('Dryer vent cleaning service','HVAC',20,40,60)
on conflict (category_name) do update
  set cluster = excluded.cluster, cpl_low = excluded.cpl_low,
      cpl_mid = excluded.cpl_mid, cpl_high = excluded.cpl_high;
```

(Adjust the `on conflict` target to the tables' real PK/unique keys if they
differ — `categories.category_id` and `lead_values.category_name` are the
natural keys.)

**That's Level A.** The grader now grades these four with the correct CPL. Done
until you want them on the board.

---

## Level B — precompute the board

### B1. Confirm the catalog rows are present (A1 + A2 above).

### B2. Load credentials + resolve the run scope

```powershell
foreach ($n in "DATAFORSEO_LOGIN","DATAFORSEO_PASSWORD","CENSUS_API_KEY","SUPABASE_DB_URL") {
  Set-Item -Path "Env:$n" -Value ([Environment]::GetEnvironmentVariable($n,"User")) }
```

Scope = the board's current city set (run_id=3 ≈ **1,491 cities**) × the **4 new
categories** = ~5,964 new city×category cells, demand-gated at `vol ≥ 20`.

### B3. Run the demand-gated repull for the 4 new categories

Mirror `run_repull.ps1`, scoped to the 4 new keywords so you don't re-pull the
existing 100:

1. **04_pull_cpc** — Google Ads volume+CPC, both keyword forms
   (`<category>` + `<category> near me`), for the 4 new categories across all
   board cities. Billed **per task** (one task per city, ~8 keywords each), not
   per keyword → ~1,491 tasks.
2. **04b_make_keeplist** — `max(base, near-me) ≥ 20` → `serp_keeplist.txt`
   (only the cells worth pulling supply for).
3. **02_pull_serp** with `SERP_KEEPLIST=serp_keeplist.txt` — Maps SERP per gated
   cell. **Coordinates MUST end `,13z`** (the load-bearing lesson). This
   regenerates `serp_results.csv` rows for the new cells.
4. **field_quality precompute** — regenerate `field_quality.csv` off
   `serp_results.csv` (this is a precomputed step, not a hand-authored input;
   the WPA columns `rev_win`/etc. come from here). Re-mirror it to Supabase.
5. **06_score_and_rank** — joins demand + field + `lead_values` + percentiles →
   scores + grades the new cells (below-gate cells kept with
   `supply_measured=false`, excluded from the board).
6. **07_load_to_supabase** — stamp/append the new rows to the master.

### B4. Publish to the app

```
python scripts/export_leadoff_board.py
```

Rebuilds `market_scanner.leadoff_board` (+ the neighborhood board) from the
master at mid tier, joined to `field_quality`. After this the 4 categories are
live on the board, brief, and grader.

### B5. Cost

- **Demand (stage 04):** ~1,491 city tasks ≈ **~$75** (task-based billing;
  independent of the keyword count per task).
- **SERP (stage 02, gated):** only cells passing `vol ≥ 20` (historically
  ~25–40% of cells) at ~$0.002–0.004 each ≈ **~$5–10**.
- **Total ≈ $80–90**, comfortably inside the DataForSEO **$500/day** limit — one
  run. (This corrects the earlier off-hand "~$6–10" estimate, which under-counted
  the per-city demand-task cost.)

If you only care about a shortlist of metros rather than the whole board, scope
B3 to those cities and the cost scales down linearly with the city count.

---

## ⚠️ The reload caveat (don't lose the catalog or the grants)

`market_scanner`'s loader **drops and recreates its tables on reload**, which
(a) wipes any Supabase-only catalog edits and (b) **strips `service_role`
grants**, breaking the app's reads. Therefore:

1. **The `inputs/*.csv` files are the source of truth**, not the Supabase rows.
   Always edit the CSVs (A1); the Supabase upsert (A2) is just to make the app
   see the change *before* the next full reload re-applies it from CSV.
2. **After any `market_scanner` reload**, re-grant (this is the fix from
   2026-07-12, in `HANDOFF.md`):

   ```sql
   grant usage on schema market_scanner to service_role;
   grant select on all tables in schema market_scanner to service_role;
   -- the three app-written caches also need insert:
   grant insert on market_scanner.domain_backlinks,
                   market_scanner.business_reviews,
                   market_scanner.demand_trend to service_role;
   alter default privileges for role market_scanner_loader in schema market_scanner
     grant select on tables to service_role;
   ```

3. `field_quality.csv` is a **precomputed output** of stages 02→field_quality,
   not a hand-authored input — it regenerates when the new categories' SERP is
   pulled (B3.4). Don't try to author its rows by hand.

---

## Verification

- **Grader (Level A):** on `/leadoff` → **Grade a market**, type a board city +
  "fire damage" (or "dumpster rental" / "carpenter" / "dryer vent cleaning").
  The card should show the resolved catalog category and **no** "lead value
  estimated" caveat (it now has a real CPL). Off-board cities grade live (~$0.06).
- **Board (Level B):** the 4 categories appear in the Board's category dropdown
  and `/leadoff/categories`; a known city×category returns instantly (source
  `board`, free) in the grader.
