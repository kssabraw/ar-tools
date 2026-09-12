# SED — Local Search Intelligence Platform

This directory is the **version-controlled home** for the SED (Search Engine
Data / Local Search Intelligence) platform: a longitudinal research system that
collects Maps / Organic / AIO / ChatGPT / Top-50 local-search evidence across an
industry × market × surface panel, normalizes it, resolves canonical entities,
and derives reproducible findings.

It is a **sibling project** to `outreach/` (same conventions), not part of the
AR-Tools suite modules.

> **Provenance note.** These artifacts were authored in a prior planning session
> and originally lived only in Google Drive (folder *SED Local Search
> Intelligence* + the SED PRDs). They were imported here so the plan of record
> and the v0.1 contracts are durable and reviewable in git. Every file was
> byte-verified against Drive on import; the two geo data files were additionally
> SHA-256 cross-checked against the hashes recorded in
> `data/SED_Geo_Eligibility_Report_v1_0.json`.

## Infrastructure (provisioned, empty)

A dedicated Supabase project and Railway project both named
**`local-search-intelligence`** are provisioned but empty (no schema, no Storage
bucket, no service). **Resolve their refs/ids by name** at use time
(`list_projects` / `list-projects`) — they are intentionally not hardcoded here.

Secrets (DataForSEO login/password, Supabase service-role key, Gemini key,
ChatGPT-vendor key) live in Railway/Supabase secret management — never in git.

## What's here

### `docs/prd/` — plan of record (the PRD layer)
- `SED-Local-Search-Intelligence-Platform-Unified-Research-Architecture-Cost-Optimization-PRD.md` — the unifying architecture + cost-optimization PRD
- `Local-Geo-Grid-Ranking-Research-Spatial-Intelligence-Platform-PRD.md`
- `Local-AI-Overview-Research-Citation-Intelligence-Platform-PRD.md`
- `SED-ChatGPT-Local-Search-Recommendation-Intelligence-PRD.md`

### `contracts/` — the v0.1 engineering contracts (DRAFT, awaiting sign-off)
- `schema/SED_Physical_Supabase_Postgres_Schema_v0_1.sql` — the DRAFT physical schema (10 schemas, 105 tables, 40 immutability triggers, pgvector, 20-migration deployment order)
- `schema/SED_Physical_Supabase_Postgres_Schema_Contract_v0_1.md` — the schema contract / domain model that governs the SQL
- `qa/SED_Operational_QA_Wave_Acceptance_Contract_v0_1.md` — the Operational QA / Wave Acceptance contract (prose)
- `qa/SED_Operational_QA_Wave_Acceptance_Rules_v0_1.json` — the machine-readable wave-acceptance rules (58 rules across PRE/COL/NOR/RES/ENR/CST/ANA stages)
- `qa/SED_Operational_QA_Rules_v0_1.json` — the qa_rules seed (24 rules, `SED_WAVE_QA` v0.1)
- `qa/SED_Operational_QA_Seed_v0_1.sql` — SQL seed skeleton for `ops.qa_contract_version` + `ops.qa_rule`
- `SED_Job_Generator_Contract_v0_7.json` — the collection-job generator contract

### `data/` — the small v1.0 data manifests (spike inputs)
- `SED_Collection_Manifest_v1_0.json` — the frozen collection manifest (the job space)
- `SED_Coordinates_GeoEligible_v1_0.csv` — 1,100 geo-classified coordinates (the single-coordinate vertical-slice spike draws from here)
- `SED_Geo_Eligibility_Classification_v1_0.csv` — per-coordinate eligibility classification
- `SED_Geo_Eligibility_Report_v1_0.json` — eligibility summary + the SHA-256 checksums used to verify the two files above
- `SED_Geo_Source_Manifest_v1_0.json` — Census TIGER source manifest (boundary/state/county + 78 areawater sources, with SHA-256s)

## Deliberately NOT imported (stay in Drive / go to Storage)

Large **generated / derived** artifacts are left in the *SED Local Search
Intelligence* Drive folder rather than committed to git — they belong in
Supabase Storage or are regenerable from the contracts + coordinates:

- `SED_Full_Panel_Job_Matrix_v1_0.csv.gz`, `SED_Sentinel_Job_Matrix_v1_0.csv`, `SED_Bounded_Pilot_Job_Matrix_v1_0.csv` — derived job matrices
- `tlgpkg_db_2025_a_us_areawater.gpkg.zip` (~1.2 GB) — the Census areawater geopackage
- older candidate versions (`*_Candidate_v0_8/v0_9`, `*_PreWater_v0_8`) — superseded by the v1.0 files above
- `apply_census_2025_areawater_mask.py` — the water-mask script (kept in Drive with the geopackage it operates on)

## Status / next steps

The v0.1 contracts are **DRAFT, awaiting owner sign-off**. Per the plan of
record, **no collector code and no migrations** are written until the contracts
are signed off. After sign-off the build sequence is:

1. Draft the machine-readable `qa_rules` seed (largely present as `contracts/qa/SED_Operational_QA_Rules_v0_1.json` + `_Seed_v0_1.sql`).
2. First migrations from schema v0.1; enable pgvector; create the content-addressed raw-payload Storage bucket (fail-on-exists).
3. Single-coordinate vertical-slice spike: one DataForSEO Maps `task_post` → raw → parse → normalize → resolve → cost-ledger.
4. Wire a Railway service to the repo (secrets in secret management).
