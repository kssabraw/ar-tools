# Local SEO — Service × Location Matrix — Plan v1.0

**Status:** Proposed (not built). Planning document only — nothing in this doc is implemented.
**Owner:** Kyle
**Last updated:** 2026-09-01
**Relationship to other work:** extends the Local SEO content module (#2). Reuses the Plan Silo planner's service-variation + city/suburb discovery, the shared bulk-create job path, the nlp-api `/generate-page` writer, the per-page publish paths (Docs / WordPress / GitHub), and the Website Builder's release-schedule helpers. Adds one nlp-api request field (sibling internal links).

> **One-line summary.** A client offers N services across M locations ("roof restoration / tile roof restoration / colorbond roof restoration" × "Melbourne / Caulfield / Hawthorn / Moorabbin"). The Matrix tab lets the team type or suggest both lists, see the N×M grid with each cell's coverage status, and fill the missing cells — all at once or dripped on a cadence — with pages that already interlink as a silo, then publish every finished cell to one destination in one action.

---

## 0. Owner decisions (2026-09-01)

Four questions were put to the owner before this plan was written. The answers are locked:

| # | Question | Decision |
|---|---|---|
| 1 | How are the two axes populated? | **Manual lists + suggest buttons.** The team types/pastes services and locations; "Suggest services" pre-fills from the silo planner's Sonnet service-variation pass, "Suggest locations" pre-fills from GBP service area + `clients.target_cities` + nearby-city discovery + the metro's geocode-verified suburbs. Always editable before running. |
| 2 | Durable or one-shot? | **Durable matrix.** New `local_seo_matrices` + `local_seo_matrix_cells` tables. The grid persists, every cell shows its coverage status and links to its page, and adding a service or location later gap-fills only the new cells. |
| 3 | What pages, and do they interlink? | **Cells + sibling internal links.** One page per service×location. Each page's prompt carries a "link to" block naming its siblings (same service in the other locations; the other services in this location), so the pages form a silo. Requires a small additive nlp-api field. No hub pages in v1. |
| 4 | Execution + publishing | **Both execution modes, plus bulk publish.** (a) The existing bulk path — confirm-gated, count + est. cost + est. time, all selected cells enqueued as staggered background jobs; (b) a drip release schedule (N cells per day/week/month, generate then publish just-in-time, mirroring the Website Builder's release schedule); and (c) a matrix-level **"Publish all done cells"** action to one destination. |

> **Note on (c).** Publishing has deliberately stayed a synchronous per-page action across the suite ("Backgrounded tasks" ruling, 2026-08-08). A matrix-level publish of up to hundreds of pages cannot be synchronous, so this adds a **per-cell publish job** (`local_seo_matrix_publish`). It is scoped to matrix cells only — the per-page Publish button is unchanged. Recorded here as an owner-approved, matrix-scoped exception.

---

## 1. Context — what exists, and the gap

| Piece | What it does today | Reused how |
|---|---|---|
| **Plan Silo** (`services/local_seo_silo.py`) | Seed service + city → service-variation silos (Sonnet, ICP-grounded), a geocode-verified Neighborhoods silo, one silo per additional target city (`target_cities.resolve_target_cities`), each target marked `found` / `on_site` / `missing`. One-shot: the plan lives in the job result. | Its **suggestion engines** become the two "Suggest" buttons; its existing-page marking (`_to_items`) is extracted into a shared helper. |
| **Bulk-create** (`enqueue_generate_bulk`, `useBulkCreate`, `BulkCreateBar`) | One staggered `local_seo_generate` job per keyword; the UI polls and can leave. | The immediate execution mode enqueues cells through the same job type, with `matrix_cell_id` in the payload. |
| **nlp-api `/generate-page`** | Competitor SERP → Claude page → 8-engine scoring + corrective passes; accepts `page_template_url` / `reference_page_structure` / `notes`. **No internal-link input.** | Gains `internal_links` (additive, optional). |
| **Website Builder matrix** (`website_plan.matrix_pages`, `MATRIX_SIGNOFF_THRESHOLD`=200) | Plans `/{city}/{service}/` pages for a generated Astro site. | Sign-off threshold reused verbatim; the URL-pattern preset `/{location}/{service}/` matches it so a later matrix→site bridge is trivial. |
| **Website release schedule** (`services/website_release.py`) | Pure cadence math (`normalize_anchors`, `next_run_after`, `advance`) + a `released_at` claim + `publish_after` on the generate job. | The pure helpers are **imported** by the matrix release; the claim + `publish_after` patterns are mirrored. |
| **Publish** (`local_seo_service.publish_page`) | Per-page, synchronous, voice-gated (409 `voice_violation`), freeze-gated; Docs / WordPress / GitHub. | Called per cell by the publish job and by the drip's `publish_after`. |

**The gap:** nothing lets the team declare two lists and fill the grid. Plan Silo is one service in, cities discovered, and its output is a throwaway. The Website Builder plans a matrix but only for a site it generates.

---

## 2. Data model

Migration `2026MMDD_local_seo_matrix.sql` (also widens the `async_jobs` job_type CHECK — rebuilt from the LIVE constraint per the suite convention — with `local_seo_matrix_suggest` and `local_seo_matrix_publish`).

```sql
create table local_seo_matrices (
  id               uuid primary key default gen_random_uuid(),
  client_id        uuid not null references clients(id) on delete cascade,
  name             text not null,                     -- "Roof restoration × Melbourne suburbs"
  -- The metro anchor: a DataForSEO-resolved area every cell is generated against
  -- unless its location row carries its own code (see §3.2).
  location         text not null,
  location_code    int,
  services         jsonb not null default '[]',       -- [{label, slug}]
  locations        jsonb not null default '[]',       -- [{name, slug, location_code?, canonical?, source}]
  -- How a cell's URL is derived (sibling links + WP slug). Presets in §3.3.
  url_pattern      text not null default '/{service}-{location}/',
  base_url         text,                              -- defaults to clients.website_url at read
  page_template_url text,
  entity_provider  text,                              -- 'textrazor' | 'google' | null
  -- Publish defaults used by the drip's publish_after and by "Publish all".
  publish_destination text not null default 'google_docs'
                     check (publish_destination in ('google_docs','wordpress','github')),
  publish_status   text not null default 'draft' check (publish_status in ('draft','publish')),
  -- Drip release (one schedule per matrix; columns mirror website_releases).
  release_enabled  boolean not null default false,
  release_mode     text not null default 'daily' check (release_mode in ('daily','weekly','monthly')),
  release_weekday  int check (release_weekday between 0 and 6),
  release_day_of_month int check (release_day_of_month between 1 and 28),
  release_per_count int not null default 1 check (release_per_count >= 1),
  release_status   text not null default 'active' check (release_status in ('active','complete','paused')),
  release_next_run_at timestamptz,
  release_last_run_at timestamptz,
  created_by       uuid references profiles(id),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create table local_seo_matrix_cells (
  id               uuid primary key default gen_random_uuid(),
  matrix_id        uuid not null references local_seo_matrices(id) on delete cascade,
  client_id        uuid not null references clients(id) on delete cascade,
  service_label    text not null,
  service_slug     text not null,
  location_name    text not null,
  location_slug    text not null,
  keyword          text not null,                     -- "<service> <location>", deterministic
  path             text not null,                     -- from url_pattern
  -- Coverage state machine (§3.5). 'found'/'on_site' are pre-existing coverage.
  status           text not null default 'missing' check (status in (
                     'missing','found','on_site','queued','generating','done','failed',
                     'publishing','published','publish_failed','publish_blocked','skipped')),
  page_id          uuid references local_seo_pages(id) on delete set null,
  job_id           uuid,                              -- latest generate/publish job
  url              text,                              -- live/published URL when known
  released_at      timestamptz,                       -- the drip's claim (mirrors website_pages)
  link_coverage    jsonb,                             -- {expected, present, missing:[...]} (§4.3)
  error            text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (matrix_id, service_slug, location_slug)
);
create index on local_seo_matrix_cells (matrix_id, status);
create index on local_seo_matrix_cells (page_id);
```

RLS mirrors `local_seo_pages` (authenticated read; backend writes with the service role). No column is added to `local_seo_pages` — a page learns about its cell only through the cell's `page_id`, so the page tables stay untouched.

---

## 3. The planner (`services/local_seo_matrix.py`)

Pure core (unit-tested, no I/O) + an impure store half, per the suite convention.

### 3.1 Cells = the cross product, deterministically

- `slugify(label)` — shared with the Website Builder's slug rules (lowercase, hyphenated, ASCII).
- `compose_keyword(service, location)` → `"<service> <location>"` — the same shape the silo planner and Local SEO generation already use (`"roof restoration Hawthorn"`), so the existing-page check and the live-verified suburb SERP behaviour carry over unchanged.
- `build_cells(matrix)` → the N×M list; `diff_cells(existing, desired)` → `{add, remove}` so editing either axis **gap-fills**: new cells are inserted `missing`, removed cells are deleted only when they have no page (a cell with a page is marked `skipped`, never deleted, so a finished page is never orphaned by a typo edit).

### 3.2 Locations — metro anchor + optional per-row code

Each location row is `{name, slug, location_code?, canonical?, source}`. Generation for a cell uses **the row's own DataForSEO code when the user picked one** (typeahead per row, `LocationAutocomplete`), **else the matrix's metro anchor** with the location carried in the keyword. The metro default is the live-verified path (location pages, 2026-08-27: "the suburb rides in the keyword, queried at the metro"). Pasted plain names are resolved best-effort through `locations_service.resolve_location` and fall back to the metro with a per-row note rather than failing the save.

### 3.3 URL pattern → cell `path`

Tokens `{service}` and `{location}` (slugs). Presets: `/{service}-{location}/` (default — WordPress-flat, the most common client site), `/{location}/{service}/` (the Website Builder's location-first matrix), `/{service}/{location}/`, custom. `base_url` defaults to the client's website. The path is what sibling links point at (§4) and what the WordPress publish uses as the slug, so links resolve once pages are live. **Open question §8.1** — confirm the default.

### 3.4 Suggestions (async `local_seo_matrix_suggest`, payload `axis`)

- **Services** — reuse `local_seo_silo._generate_service_pages` (Sonnet, ICP-grounded). Small refactor: it currently composes `"<modifier> <service> <city>"`; expose the modifier list so the matrix receives `"<modifier> <service>"` labels (e.g. "tile roof restoration"). The seed service itself is always the first label.
- **Locations** — two sources, both returned tagged by `source` so the user sees why: (1) **target cities** via `target_cities.resolve_target_cities` (GBP service area, `clients.target_cities`, site place-names, Overpass nearby); (2) **suburbs of the metro** via `local_seo_silo._neighborhoods_for_city` (Haiku proposal + geocode containment). Melbourne's Hawthorn/Moorabbin come from (2), not (1) — a metro's suburbs are neighborhoods, not target cities, and a matrix over suburbs is the common AU/UK case.
- Both best-effort (degraded notes, never an aborted suggestion). Suggestions are merged into the axis lists as **unchecked chips** the user confirms.

### 3.5 Existing-page marking

Extract `local_seo_silo._to_items`'s marking into a shared `local_seo_existing.mark_existing(targets, client_id, site_index)` (step-zero split of the planner, per the refactoring policy — verbatim move, silo keeps calling it). A cell is `found` when a live `local_seo_pages` row matches its keyword (page linked via `page_id`), `on_site` when the live sitemap has a generic page for the location, else `missing`. Re-run on every matrix read that is older than a short TTL and on explicit "Re-check coverage".

### 3.6 Estimate + gates (pure)

`estimate(cells_to_run)` → `{count, est_cost_usd, est_minutes}` from `local_seo_matrix_cost_per_page_usd` (default 1.0, the same per-page figure the autonomy governor reserves) and `local_seo_matrix_minutes_per_page` (default 11 — current measured generation time). Gates: `local_seo_matrix_max_cells_per_run` (default 50 per immediate batch) and the Website Builder's `MATRIX_SIGNOFF_THRESHOLD` (200) reused as a **whole-matrix** sign-off flag (acknowledgeable, like the builder's). Freeze Protocol: every write route calls `assert_not_frozen`; `local_seo_generate` is already freeze-gated in the worker.

---

## 4. Sibling internal links

### 4.1 Selection (pure, platform-api)

`sibling_links(cell, cells, url_pattern, base_url)` → `[{anchor, url, relation}]`:
- `same_location_other_service` — every other service in this location (typically 2–6).
- `same_service_other_location` — up to `local_seo_matrix_sibling_location_cap` (4) other locations for this service, nearest-first when the rows carry geocodes, else axis order.
Hard cap 10 links per page (`local_seo_matrix_max_links`), so a 20-location matrix cannot link-stuff. Anchor = the sibling's keyword in natural case ("Tile roof restoration in Hawthorn"). URL = `base_url + sibling.path`. Links are computed from the matrix at enqueue time and stored on the job payload, so a cell generated before its siblings exist still links to their planned URLs.

### 4.2 nlp-api (additive)

`GeneratePageRequest.internal_links: Optional[List[dict]] = None` and the same on `ReoptimizePageRequest` (so a reoptimize pass preserves the silo instead of stripping it). Rendered as one late prompt block, below the voice card, above layout requirements:

> INTERNAL LINKS — this page is part of a service × location silo. Link to each of the following once, as a natural contextual link (URL verbatim; anchor may be lightly rephrased), inside the body, the related-services section, or an "Also serving nearby" paragraph. Never in the H1 or title. Do not invent any other internal links.

### 4.3 Deterministic guarantee (no extra LLM pass)

After generation, a pure `check_internal_links(html, links)` counts which URLs are present. Any missing are appended as a compact "Related services" / "Nearby areas" list block before the closing CTA — deterministic, like `_insert_required_phrases_inline` — so every cell always carries its full sibling set regardless of the writer. The result is stored as `cells.link_coverage` (advisory; never a scoring engine, never touches the composite). Structural-fidelity mirroring is unaffected: the appended block is a list, which the reference-structure eval already tolerates as a trailing block.

---

## 5. Execution

### 5.1 Immediate (the existing bulk path)

`POST /clients/{id}/local-seo/matrices/{mid}/generate {cell_ids?}` (default: every `missing` cell; `on_site`/`found` only when explicitly included). Returns the estimate first via `GET …/estimate`; the UI shows count / est. cost / est. time and a confirm. Enqueues one `local_seo_generate` job per cell through a matrix-aware twin of `enqueue_generate_bulk` — same staggered `scheduled_at`, payload gains `matrix_cell_id` + `internal_links` + the cell's resolved location/code — and flips each cell to `queued`.

**Cell reconciliation is read-side, not hook-side.** `reconcile(matrix_id)` reads the cells' `job_id`s against `async_jobs` (`running` → `generating`, `complete` → `done` + `page_id` from the job result, `failed` → `failed` + error) and is called by the matrix GET, by the release tick, and before a bulk publish. No worker change is required for status; a missed poll can never strand a cell. (`run_generate_job` gains one additive branch only for `publish_after`, §5.2.)

### 5.2 Drip release

Schedule columns on the matrix (§2). `set_release(matrix, body)` validates + normalizes anchors with `website_release.normalize_anchors`, fires `immediate_count` now, and clocks `release_next_run_at` with `website_release.next_run_after`. `enqueue_due_matrix_releases()` joins the shared scheduler's daily block beside `website_releases` (self-gated on `local_seo_matrix_enabled`). `run_release(matrix_id, count)` claims the next `count` releasable cells by stamping `released_at` **before** enqueuing (the exactly-once rule), orders them **location-major** (finish one location's services before the next, so a location's silo is complete sooner), and enqueues generate jobs with `publish_after: true` + the matrix's destination/status. `run_generate_job` gains: if `payload.publish_after`, call `publish_page(page_id, user_id, destination, status)` best-effort after persist — a publish failure marks the cell `publish_failed` (page kept), a voice block marks it `publish_blocked` with the offending words. `website_release.advance` decides complete-vs-reclock.

### 5.3 Publish all done cells

`POST …/matrices/{mid}/publish {destination?, status?, force_voice?, cell_ids?}` (default: every `done` cell). One `local_seo_matrix_publish` job per cell, staggered at a short spacing (`local_seo_matrix_publish_spacing_seconds`, 10 — publishing is seconds, not minutes), each calling `publish_page`. Cell states: `publishing` → `published` (+`url`) / `publish_failed` / `publish_blocked`. Freeze-gated; the voice gate is per page exactly as today, and `force_voice` is the same explicit override (a blocked cell shows the words and a "Publish anyway" for that cell). Idempotent: a cell already `published` to the same destination is skipped.

---

## 6. API (`routers/local_seo_matrix.py`)

| Route | Purpose |
|---|---|
| `GET/POST /clients/{id}/local-seo/matrices` | list / create (create builds cells + marks coverage) |
| `GET/PUT/DELETE …/matrices/{mid}` | read (reconciled + coverage-checked) / edit axes+settings (gap-fill diff) / delete (pages untouched) |
| `POST …/matrices/{mid}/suggest {axis}` + `GET …/suggest/{job_id}` | Suggest services / locations (async) |
| `POST …/matrices/{mid}/recheck` | re-run existing-page marking |
| `GET …/matrices/{mid}/estimate?cell_ids=` | count / cost / minutes + gate flags |
| `POST …/matrices/{mid}/generate` | immediate batch |
| `PUT/DELETE …/matrices/{mid}/release` | drip schedule set / pause+clear |
| `POST …/matrices/{mid}/publish` + `POST …/matrices/{mid}/publish/status` | bulk publish + poll |

Models in `models/local_seo_matrix.py`; all writes `require_auth` + `assert_not_frozen`; every job scoped to the client (`entity_id`) like the existing Local SEO jobs.

---

## 7. Frontend

A new **Matrix** tab in `pages/LocalSeoContent.tsx` (tab list gains `'matrix'`), components under `components/localseo/matrix/`:

- **`MatrixList`** — the client's saved matrices (name, N×M, coverage bar, release state); "New matrix".
- **`MatrixBuilder`** — name; metro anchor (`LocationAutocomplete`); **Services** chip editor (type/paste, one per line, + "Suggest services"); **Locations** chip editor (+ "Suggest locations" showing target-cities vs suburbs-of-metro groups, per-row optional typeahead to pin a DataForSEO code); URL pattern preset; page template + entity engine (reusing `EntityProviderSelect`); publish defaults.
- **`MatrixGrid`** — services as rows, locations as columns; each cell a status chip (`missing` selectable checkbox, `found`/`on_site` linked, `queued`/`generating` spinner, `done` → page link + score, `failed` → error via `ErrorDetails`, `published` → live link, `publish_blocked` → words + per-cell "Publish anyway"). Row/column select-all. Polls the matrix GET every 15 s while any cell is in flight — the durable cells make the UI trivially resumable, so no `useResumableBatch` state.
- **`MatrixRunBar`** — selected count → estimate (count · $ · minutes · sign-off flag) → **Generate now** / **Schedule…** (drip form: immediate N, then N per day/week/month) / **Leave & finish in the background** (jobs keep running).
- **`MatrixPublishBar`** — "Publish all done cells" to destination/status with progress.

Errors go through the shared `errorGuidance` registry (new codes: `matrix_signoff_required`, `matrix_cell_limit`, `matrix_location_unresolved`).

---

## 8. Open questions (non-blocking — defaults stated)

1. **URL pattern default.** `/{service}-{location}/` (WordPress-flat) vs `/{location}/{service}/` (Website Builder). Default: the former; it is a per-matrix setting either way. Also to verify: that `wordpress_publish` accepts a slug — if not, add it, else links only resolve by chance.
2. **Per-cell SERP location.** Metro anchor by default (the live-verified path). Should the planner auto-pin a suburb's own DataForSEO code when one exists? Default: no auto-pin; the per-row typeahead is the opt-in.
3. **`on_site` cells.** Today the silo planner never offers an `on_site` target for creation. Keep that, with an explicit "include anyway" per cell? Default: yes, explicit include only.
4. **Hub pages** (a page per service and per location) — declined for v1 (decision 3). Revisit once cells exist; the Website Builder already plans hubs for generated sites.
5. **Matrix → Website Builder bridge.** A client with a suite-built site should push cells into its site plan rather than generate separately. Natural follow-up, not v1.
6. **SerMaStr / PACE visibility.** A `_ctx_local_seo_matrix` context provider (coverage %, in-flight cells) is cheap and additive — follow-up.

---

## 9. Phasing

| Phase | Scope | Gate to next |
|---|---|---|
| **0 — Foundations** | Migration; `services/local_seo_matrix.py` pure core (`slugify`, `compose_keyword`, `build_cells`, `diff_cells`, `sibling_links`, `check_internal_links`, `estimate`, gates); `local_seo_existing.mark_existing` extracted from the silo planner (verbatim, silo tests green); unit tests. | Pure tests green; silo planner unchanged in behaviour. |
| **1 — Store + API + immediate run** | CRUD, suggest job, coverage marking, estimate, `generate` with cell tracking + read-side reconcile; config flags. | A 3×4 matrix generates end-to-end on PLATFORM with cells reconciling to `done` + page links. |
| **2 — Sibling links** | nlp-api `internal_links` on generate + reoptimize + prompt block; platform-side deterministic guarantee + `link_coverage`. | Live pages verified to carry the full sibling set; composite/voice scores unchanged vs a no-links run (links must not cost score). |
| **3 — Frontend** | Matrix tab: list, builder, grid, run bar. | Team can plan + fill a matrix without the API. |
| **4 — Drip release** | Schedule columns, `run_release`, scheduler tick, `publish_after` branch in `run_generate_job`. | A scheduled matrix releases N/day and auto-publishes to the configured destination. |
| **5 — Bulk publish** | `local_seo_matrix_publish` job, publish route + status, `MatrixPublishBar`, per-cell voice override. | "Publish all done cells" delivers to Docs / WP / GitHub with blocked cells surfaced, never skipped silently. |

Config (all in `config.py`): `local_seo_matrix_enabled` (default True — no dark launch needed, it creates nothing by itself), `local_seo_matrix_cost_per_page_usd` (1.0), `local_seo_matrix_minutes_per_page` (11), `local_seo_matrix_max_cells_per_run` (50), `local_seo_matrix_sibling_location_cap` (4), `local_seo_matrix_max_links` (10), `local_seo_matrix_publish_spacing_seconds` (10).

---

## 10. Cost + scale

Per cell: one Local SEO generation (~$1, ~11 min on the single worker). The example 3×4 matrix ≈ $12 and ~2¼ hours of background time; a 10×20 matrix (200 cells, the sign-off line) ≈ $200 and ~37 hours — which is exactly why the drip mode exists and why the per-run cap defaults to 50. Suggestions are one Sonnet call (services) plus geocoding/Overpass (locations), cents. Sibling links add prompt tokens only. Bulk publish is API calls, no LLM.

## 11. Testing

Pure core fully unit-tested (`tests/test_local_seo_matrix.py`): cross product + slugs; gap-fill diff (add / remove-without-page / skip-with-page); keyword composition parity with the silo planner; sibling selection caps + nearest-first; link check + deterministic append idempotence; estimate + gates; release batch ordering (location-major) and exactly-once claim; publish idempotence. The `mark_existing` extraction is pinned by the existing silo tests. nlp-api: `tests/test_internal_links.py` for the prompt block render (empty → "") and the request models. Frontend: `tsc -b` clean; grid state rendering covered by the reconcile contract.
