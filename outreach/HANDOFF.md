# HANDOFF — Outreach Pipeline

**Read this first, then `CLAUDE.md` → `START-HERE.md` → `ISSUES.md` → `DECISIONS.md`.**

Status as of 2026-08-27 (**enrichment hardened + made reliable; the ORGANIC/paid-placement signal now runs automatically; the outreach worker finally has CI** — all MERGED to `main`; the four live geogrid scans below still stand).

### 2026-08-27 session — enrichment reliability, auto-organic, CI, LA data repair (all MERGED)

- **OUTREACH NOW HAS A CI TEST GATE (#770).** The worker (`outreach/api/`) had **no** automated test
  run — the three Python CI workflows are path-filtered to `writer/**`, so the only PR check was the
  Netlify *frontend* build. A change to a money-spending drain could go red with nothing failing.
  Added `.github/workflows/outreach-tests.yml` (`python -m pytest -q` from `outreach/` on any PR
  touching `outreach/**` + push to main; Python 3.11, deps from `api/requirements.txt`, no system
  libs). Fixed 4 long-standing red `test_onboard_queue` cases first (harness drift — the test
  `_Settings` stub was missing the `filter_*` fields `drain_one` STAGE 2 now reads; no production
  change). Full suite now **673 pass**; it gated (and validated) every drain change below.

- **ENRICHMENT I-109 RESOLVED + hardened (see the enrichment bullet in CLAUDE.md).** The Enrich button
  returned business names, not people, for two stacked reasons — sync mode + the wrong enricher slug —
  now fixed to **async `leads_n_contacts`** (#756/#763) with per-person dedup (#765). Then three
  reliability fixes:
  - **I-117 (data loss) FIXED + verified (#767).** `enrich_queue`'s replace-on-place delete had NO
    source scope, so re-enriching a prospect wiped its FREE site-scrape + PAID web-search **name**
    fallbacks too. Scoped the delete to `source='outscraper'`. Verified on LA: the wiped fallbacks
    were restored (site_scrape 1→20 free, web_search 0→3 paid ~9¢) — the surviving marker rows held
    the names through the wipe, so the restore was cheap.
  - **I-118 (cron-window kill) FIXED + PROD-VERIFIED (#769).** A market-wide enrichment order (118
    async lookups) overran Railway's `*/5` cron window (`restartPolicy: NEVER`) and the container was
    killed mid-tick, stranding the order `running` at 101/118 with no recovery. Fix mirrors
    `name_scrape`: a **per-tick place budget** (`enrich_per_tick`=40) with PENDING-resume + a
    **stuck-order reaper** (`recover_stuck_orders`). Re-ran the exact failure cleanly — 17 stranded
    places drained in **71 s, one tick, 0 failed**.
  - **I-119 — the same budget+reaper ported to the other two drains (#775 `name_search` PAID, #778
    `name_scrape` FREE).** **All three name/enrich drains (enrich / name_search / name_scrape) now
    carry BOTH the per-tick budget AND the reaper** — none can strand a `running` order on a mid-tick
    kill.

- **ORGANIC / PAID-PLACEMENT SIGNAL NOW RUNS ON EVERY SCAN (#777, owner ruling; DECISIONS 2026-08-27).**
  The report's strongest "is this prospect already paying to be visible / doing other marketing" read
  (Google Ad / LSA presence + organic rank for the keyword) was click-only, so most markets read
  `not_scanned`. Now `scan_runner.collect_ready` auto-enqueues an `organic_scan_request` when a snapshot
  finalizes (`organic_scan_queue.enqueue_for_snapshot`, gated `organic_auto_enabled`=True, idempotent
  per snapshot, drained ≤1/tick, budget-gated). Organic is ONE cheap DataForSEO SERP call per snapshot
  and the paid-placement parse rides it for free — ~one request per scanned submarket×keyword, not per
  prospect. Auto orders carry a sentinel `requested_by` (`00000000-…`) so they stay auditable apart
  from a click. `scan-ai` / `probe-pixel-field` stay click/flag-gated.

- **LA MARKET (Los Angeles, CA, USA) DATA REPAIRED + the generic-name gap measured.** Enrichment gap
  closed (17 stranded → 0). The "Enrich returns generic business names" complaint was traced to
  `leads_n_contacts` returning a **business-name fallback** for most small operators (only ~42/161 of
  its contacts were real people); the name-specific fallbacks (site-scrape, web-search) return real
  people but had barely run. A free site-scrape sweep (exhausted — 0 new) + a paid `web_search` sweep
  across the 83 generic-only prospects (~$2.49, 39% hit) lifted **person-name coverage 33 → 65 of
  118**. The residual **53 = the true public-web floor** (no source can name the owner) — the clean
  **Enigma sample-test baseline** (`docs/enigma-integration-scoping-v0_1.md`). **"Evidence of other
  marketing"** for a market lives in `prospect_tech_signal` (site tags: Meta pixel / Google-Ads `AW-`
  tag / GTM / CallRail-Podium-Birdeye / Google-Guaranteed, from the free auto `scan-tech`) + the
  paid-placement block now auto-captured per scan.

Status as of 2026-08-26 (**FOUR live geogrid scans are DONE and independently verified** — the pipeline is proven in production, not just built; heatmap slices 1–2, the any-city scan, **the per-prospect report — call hook + 3 signals + approval-gated client PDF**, **the paid-placement 4th signal**, **`outcome` + `touch` + the emit webhook**, and **lead enrichment + the report-signal UI triggers** — all MERGED to `main`):

- **FOUR LIVE SCANS COMPLETE + VERIFIED (through 2026-08-25).** The full scan → collect → rollup →
  coverage pipeline has now run end-to-end on real DataForSEO data four times, each 81/81 points
  collected, `complete=true`, rolled up with its `rank_vector`, cost-tracked in `cost_ledger` (stage
  `b1_geogrid`, 81¢/scan), zero month-straddle, zero duplicate grid rows:
  - **Los Angeles × `emergency plumber`** — 119 coverage rows (the first live scan, any-city onboard path).
  - **Whittier × `plumber`** — 90 coverage rows.
  - **Inglewood × `Plumbing contractor`** — 144 coverage rows.
  - **Van Nuys × `plumber`** — order `0771ac6c`, snapshot `27982fd0-624e-4f25-8eae-bb8635e6656d`,
    154 coverage rows (verified 2026-08-25: 81/81, 1,620 grid rows, rolled up, 81¢).
  Data-quality caveat (honest, not a defect): the placeholder "most invisible" lists are cluttered
  with non-target businesses (suppliers / remodelers / restoration). Measurement is correct; turning
  these into a clean call list needs category cleanup or Phase 4 scoring. The review-count / inferred-zero
  audit gap (scan keeps only place_id + rank, drops `rating.votes_count`; 105 inferred-zero flags still
  un-audited) is **I-045 — logged, still unbuilt** (§9).

- **CALL HOOK — LOSS-FRAMED + PER-PROSPECT (2026-08-10, draft PR).** The "Why call?" hook read
  generic/identical for prospects in one submarket (one template led with the shared coverage line).
  Fixed in two layers: (1) the deterministic assembler (`services/outreach_justification.py`) now
  LEADS with the most per-prospect-distinctive loss (paying-and-losing → named competitor → review
  deficit → coverage) and every template is loss-framed; (2) a grounded LLM phrasing pass
  (`services/outreach_call_hook.py`, `report_llm.run_forced_tool_sync`) rewrites it into compelling
  loss-framed prose using ONLY the assembled facts, with a deterministic **grounding guard** that
  rejects invented money/lead-volume numbers (fear-of-loss's failure mode) → falls back to the
  deterministic hook. Cached per (prospect, snapshot) in `prospect_call_hook` (migration
  `20260810160000`, **applied live**) keyed by a facts fingerprint, so determinism/replayability lives
  at the cache (identical re-reads, one paid call per prospect×snapshot). No frontend change (output
  shape unchanged). Config `outreach_call_hook_*`. Full design in DECISIONS.md 2026-08-10.
- **REPORT SIGNAL SCANS — RUN ORGANIC + AI PER-PROSPECT FROM THE REPORT (2026-08-10, draft PR).** The
  report always rendered four signals but only the geogrid could be TRIGGERED in-app; `scan-organic`
  and `scan-ai` were CLI-only, so their sections read `not_scanned` for every un-hand-run prospect.
  Owner request: let staff run organic + AI per prospect from the report. Two new signed-order queues
  on the `scan_request` rails — `organic_scan_request` + `ai_scan_request` (migration
  `20260810140000`, **applied live** to Outreacher). platform-api WRITES the order admin-only, the
  outreach `tick` DRAINS + runs it (`api/services/organic_scan_queue.py` / `ai_scan_queue.py`,
  ≤`organic_orders_per_tick`/`ai_orders_per_tick`=1 each); platform-api never spends. Organic resolves
  the EXACT snapshot the report reads (idempotent → a re-order/second prospect in the submarket is a
  free `done`); AI targets a human-seeded `ai_region`, so `create_ai_scan_request` 422s
  `ai_region_not_seeded` when none matches and the report UI opens a seed modal (`POST
  /outreach/ai-regions`, admin, name pre-filled to the prospect's area so the resolver matches, human
  picks name_level — the I-073 invariant intact). platform-api: `services/outreach.py` +
  `routers/outreach.py` (`/outreach/prospects/{id}/scan-organic|scan-ai`, `/outreach/{organic|ai}-scan-requests`
  list/detail/cancel, `/outreach/markets/{id}/ai-regions`, `/outreach/ai-regions`). UI:
  admin-only "Run organic scan" / "Run AI scan" buttons + the region-seed modal in
  `frontend/src/components/outreach/ProspectReport.tsx` (poll order → refetch report). No per-user
  budget ledger (each run ~1–3¢; the one-active index + admin gating suffice). Pure drain logic
  unit-tested (`test_organic_scan_queue.py` / `test_ai_scan_queue.py`, 25 tests) + platform-api
  gating/constants/validation. Full design in DECISIONS.md 2026-08-10.
- **LEAD ENRICHMENT IS BUILT (2026-08-10, draft PR) — contact NAMES / PHONES / EMAILS per prospect,
  one-by-one and select-all.** Enriches a prospect (or a selection) via Outscraper "Emails & Contacts"
  enrichers. **The mass-ingest enrichment invariant is intact** — `submit_maps_search` is untouched;
  enrichment builds its own by-place_id request in `api/services/enrich_client.py` (generalizing
  `pixel_probe.fetch_enriched_sample`). Order-driven like scans: a UI click (ADMIN, budget-guarded) writes
  an `enrichment_request` (migration `20260810120000`, **applied live** to Outreacher); the `tick` command
  drains it (`api/services/enrich_queue.py`) and bills — platform-api never spends. Batchable, so the drain
  does several orders/tick (not the ≤1 scan cadence) and is idempotent (already-enriched prospects skipped,
  no re-bill → a re-order is a cheap resume). Contact-aware: `prospect_contact` (one business → N contacts)
  + `prospect_enrichment` (status/provenance/idempotency marker); `prospect` left pristine. Free preflight
  estimate + per-user daily budget guard (order rows = the ledger). New commands: `enrich` (order-gated,
  drains) + `probe-enrich` (PAID, the measure-don't-infer spike); both wired into `run_market.py`, `enrich`
  drained in `tick`. platform-api: `services/outreach.py` + `routers/outreach.py`
  (`/outreach/enrichment/estimate`, `/outreach/prospects/{id}/enrich`, `/outreach/enrichment`, list/detail/
  cancel, `/outreach/prospects/{id}/contacts`). UI: `frontend/src/components/outreach/Enrichment.tsx`
  (per-row Enrich + select-all bulk bar + contact chips, `useResumableBatch`) in the coverage table + CRM
  lead drawer. Pure logic unit-tested (parser 26 + drain; platform-api estimate/budget/validation).
  **UNRUN + field names UNCONFIRMED:** run `probe-enrich` once (owner-authorized) to confirm the enrichment
  param value(s) + response shape before trusting output — ISSUES I-109/110/111. Config rates are
  placeholders (I-111). Full design in DECISIONS.md 2026-08-10.
- **`outcome` + `touch` + THE EMIT WEBHOOK ARE BUILT AND MERGED (2026-08-09, PR #625 → `8141629`).**
  The learning substrate (HANDOFF §12's named next build; the one Phase-3 item with a closing window,
  because `outcome` cannot be backfilled — scoring-spec §8). Migration `20260809170000_outcome_touch.sql`
  applied live to Outreacher (`touch` + `outcome` — outbound-only made structural via the composite FK,
  adopted verbatim from `PHASE3-outcome-constraint.md` — + `lead_activity.touch_id`'s FK), verified live
  by `tests/outcome_touch_constraints.sql` (12/12). platform-api `emit_prospect`/`record_touch` + pure
  `outreach_emit.py`; the SPA's Emit button + Log-contact/outcome UI. `selection_reason` on 100% of
  contacts (ISSUES I-102). **The emit webhook is a GENERIC, OPTIONAL integration** — the owner does NOT
  use n8n/Encharge (the PRD's example senders); the webhook-free `touch` path is the real capture, so
  the substrate fills from call one with no external sender. The teed-up hand-picked-backfill question
  is resolved: create-on-first-contact, no bulk backfill (DECISIONS 2026-08-09). See the dedicated
  section below and §12.
- **THE PAID-PLACEMENT SIGNAL IS BUILT AND MERGED (2026-08-08, PR #621 → `b4ca6da`).** The report's
  FOURTH competitive signal, and per `docs/scoring-spec.md` the highest-value one in the whole model:
  a business paying to solve its visibility problem while still losing organically has proven budget
  AND intent (LSA active +57, Ads + no organic/pack +46, spend >$2k +66).
  - **Slice A — presence, for NO new paid call.** The `scan-organic` capture already stores the full
    SERP, and that response carries the paid items the parser used to discard. `parse_organic_serp`
    now also reads `paid` (Google Ads) + `local_services` (LSA) and `summarize_serp` writes a `paid`
    block into `serp_result.payload_summary`. Surfaced as a "Paid placement" section in both report
    faces + the client PDF, and an `ELEM_PAID` call-hook talking point.
  - **Slice B1 — site tech, FREE.** `scan-tech` fetches each prospect's OWN site (PRD §B3, "own
    request, not a paid service") and stores Meta pixel / `AW-` conversion tag / GTM container /
    CallRail-Podium-Birdeye into **`prospect_tech_signal`** (migration `20260808200000`, applied
    live). Deliberately NOT in `PAID_COMMANDS` — a test pins it. A failed fetch stores a
    `fetch_status` (unknown), NEVER `absent`.
  - **Slice B2 — ad-spend MAGNITUDE — deliberately NOT built.** Gated behind a DataForSEO Labs yield
    spike (I-098): Labs paid data is keyword-SERP-derived, so a two-truck operator bidding
    hyper-locally — and running LSA, which Labs does not index as paid search at all — often returns
    zero. That is exactly this pipeline's population. Labs endpoints are in the free probe set.
  - **The strongest pitch it unlocks:** `prospect_is_paying` + poor coverage = "paying and losing"
    (the vendor-failing shape), an `ELEM_PAYING` element that LEADS the spoken hook when it fires.
  - **Read I-099 before touching this code.** An adversarial review found three real defects before
    anything ran: a shared `--limit` default that silently capped `scan-tech` at 20 of ~1,000 sites
    while exiting 0; a bidirectional LSA name match that asserted an ad the prospect wasn't running
    AND deleted a real competitor; and an `AW-` site tag that produced the spoken claim "you're
    paying for Google Ads on ⟨keyword⟩" with no ad in that SERP. All fixed, each pinned by a
    regression test. Design doc: `docs/paid-placement-slice-b-design-v0_1.md`.
  - **UNRUN:** `scan-tech` (free) and `probe-pixel-field` (PAID, §16a.1 spike) have never executed.

- **THE PER-PROSPECT REPORT IS BUILT AND MERGED — the "why this is a lead" call hook + a two-face
  competitive report (2026-08-08, PRs #615–#619).** Phase 3 §12 item 1 (the phone-call hook) plus the
  internal/client report the owner asked for, in five merged slices. All logic is DETERMINISTIC and
  fact-grounded — never an LLM guess, never a fabricated fact/competitor/number (DECISIONS 2026-08-08,
  the design-fork ruling), the same discipline as the heatmap renderer.
  - **Call-hook justification** (`writer/platform-api/services/outreach_justification.py` pure +
    `outreach.prospect_justification` I/O + `GET /outreach/prospects/{id}/justification`): the talking
    points a caller reads before dialing — coverage deficit, the radial pattern of invisibility, who
    holds the map pack where they're absent, reviews vs the local field, listing gaps — assembled only
    from stored scan data. A "Why call?" expander in `Outreach.tsx`'s coverage table + the CRM lead
    drawer. (I-093 compass-direction geography deferred to respect the geometry boundary; I-094
    competitor detail needs a hot `grid_result` partition.)
  - **The report** (`services/outreach_report.py` pure + `outreach.prospect_report` I/O +
    `GET …/report`): two faces over ONE document — an internal competitive brief and a client-facing
    draft. `components/outreach/ProspectReport.tsx` — two buttons in the coverage table + CRM drawer,
    a modal with a face toggle + print. A signal with no scan renders as an explicit `not_scanned`
    block, never an empty table that would read as "no competitors" (the I-076 lesson, per-section).
  - **Three competitive signals.** MAPS (rankings vs competitors, from the coverage the first scan
    produced — has LIVE data). ORGANIC (`scan-organic` command, PAID + gated; `api/services/organic_scan.py`,
    one live Google SERP per snapshot into `serp_result`; I-084 resolved — it attaches to the maps
    `scan_snapshot`). AI VISIBILITY (`scan-ai` command, PAID + gated; `api/services/ai_visibility.py` —
    **ChatGPT + Google AI Overview**, per region×keyword; new `ai_region` + `ai_scan_result` tables,
    `ai_region` seeded with the 11 validated LA place names from I-073; a prospect maps to a region by
    its submarket name; conservative mention detection that never manufactures invisibility).
  - **Client-facing PDF + approval gate + signed-URL delivery.** The client face is a DRAFT until an
    admin approves. `POST …/report/pdf` (ADMIN-gated — the click IS the approval; the no-unapproved-asset
    invariant) renders the report to PDF (WeasyPrint, reusing the suite's `client_report.render_pdf`),
    records a `report_approval` row (actor + content_hash + storage_path), stores the PDF in the private
    `outreach-reports` Supabase Storage bucket, and returns a **signed URL** (90-day expiry — reporting §5
    on Supabase Storage, NOT R2, DECISIONS 2026-08-08). `GET …/report/pdf` re-signs without re-approving.
  - **New migrations, all applied live:** `20260808140000_ai_visibility` (ai_region + ai_scan_result),
    `20260808160000_report_approval`, `20260808180000_report_pdf_storage` (+ the `outreach-reports` bucket).
    **New PAID commands:** `scan-organic`, `scan-ai` (both in `PAID_COMMANDS`, token/order-gated like `scan`).
    **I-095 is fully resolved.**
  - **STILL UNRUN — the organic and AI scans have never been run.** `scan-organic` and `scan-ai` are
    built, gated, and cost money; the report's organic + LLM sections read `not_scanned` until an admin
    authorizes them (the MAPS section already has live data from the first scan). `serp_result`,
    `ai_scan_result`, `report_approval` are all empty. This is the same "built ≠ run" state the scan
    layer sat in before the first maps scan.
- **THE FIRST LIVE SCAN IS COMPLETE AND VERIFIED (2026-08-08).** `emergency plumber` × the whole
  city of Los Angeles, run through the new **any-city onboard** path (not the seeded market): **122
  businesses discovered, 83 survived the filter, 81/81 grid points collected, snapshot rolled up,
  119 `prospect_coverage` rows.** onboard_request `91bde3cb-082f-478f-ab3c-d504fc03bca3` · snapshot
  `30455295-90a7-46ce-aae6-1845f3a856de` · submarket "Los Angeles, CA, USA" (the whole-city centre).
  This exercised submission → collection → finalization → rollup → placeholder score in one live
  pass. The scan tables are no longer empty: `scan_snapshot` 1, `scan_task` 81, `grid_result` 1,620,
  `prospect_coverage` 119, `snapshot_rollup` 1, `grid_point_status` 81. Top invisible businesses
  (0% coverage) surfaced for outreach: Major League Plumbing, USA Plumbing, Koreatown Handyman, and
  others. **The core loop is proven end-to-end against a live provider for the first time.**
  - **What run one still did NOT prove** (unchanged from §11b): the empty-pack path at scale (LA
    whole-city is dense — a coastal submarket is run two), land masking (needs 3 cycles), the
    fallback-by-id path (needs a task to age off `tasks_ready`), and tag recovery.
- **THE ANY-CITY SCAN IS BUILT AND MERGED — "City + what a customer searches" → discover → filter →
  scan** (2026-08-08). The scan is no longer confined to the pre-seeded LA market. A user types **any
  city** (Google-resolved) + an optional **Google-recognized sub-area** + a **free-text consumer
  search** (the phrase a real customer types — NOT a GBP category), and the platform discovers →
  filters → scans it. The consumer search drives BOTH the Outscraper ingest category AND the geogrid
  scan keyword. This closes I-092: `prospect_coverage` joins `grid_result` to *pre-ingested*
  `prospect` rows on place_id, so scanning a city nobody has ingested yields zero coverage — the
  onboard path therefore ingests-then-scans in one staged order.
  - **Signed-order model:** a new **`onboard_request`** row (migration `20260808120000_onboard_request.sql`,
    **applied live**; one-active partial-unique guard; RLS-on/zero-policy) is a single-use, admin-placed
    order whose existence is its spend confirmation — the same pattern as `scan_request`. The outreach
    `tick` cron drains **at most one `onboard_request` per heartbeat** (after collect + the scan-order
    drain), running ingest → filter → scan with staged asymmetric failure (`api/services/onboard_queue.py`,
    `OnboardDrainReport`, 15 tests). `tick` stays out of `PAID_COMMANDS` — the order row is the confirmation.
  - **Geo enumeration (platform-api side):** Google has no "list a city's neighborhoods" endpoint, so
    `services/outreach_geo.py` **OSM-enumerates** sub-areas (Overpass `place=suburb/neighbourhood/…` via
    the new generic `overpass.places_near`) then **Google-verifies** each with `place_is_within_city`
    (moved to the FastAPI-free `services/maps_geocode.py` so the sandbox can import it). `create_onboard_from_place`
    is get-or-create for market/submarket/keyword (geometry is immutable — a repeat pick reuses rows, never
    mints a drifted centre); `subarea=None` scans the whole-city centre. Routes: geo (`resolve-city`, `subareas`,
    staff-gated) + onboard (POST/GET/cancel, admin-gated) in `routers/outreach.py`. Tests in
    `tests/test_outreach_onboard.py`.
  - **UI (`frontend/src/pages/Outreach.tsx`):** `OnboardCityCard` (city + "What a customer searches" +
    Find city + sub-area / Whole-city select + Discover & scan), `OnboardOrdersCard` (expandable rows with
    live `OnboardProgress` X/81 and an inline "View results ▾" → `CoverageTable`), `BusinessesCard`. The
    two-market friction (the onboard mints its own market, distinct from the seeded LA-Plumbing one) is
    resolved by viewing a scan's results **inline from its City onboards row** rather than a second market
    selector (#611).
  - **platform-api is now CONFIGURED** — the Outreacher project's `OUTREACH_SUPABASE_URL` /
    `_SERVICE_ROLE_KEY` were set on the PLATFORM Railway service via cross-service **reference variables**
    (`${{outreach.VAR}}`, no secret exposed), so `/outreach` answers instead of `503 outreach_not_configured`.
  - **Merged:** #601 (`28f224c`, city+business-type → discover/filter/scan), #603 (`9cfeb12`, consumer
    search + optional sub-area), #606 (`0229e34`, live collection progress + "Businesses found" view),
    #611 (`2710729`, inline results). Migration applied live.
- **Phase 3 slice 2 — the comparison renderers — is BUILT and MERGED (#589, `c3b1b50`).**
  `heatmap_pair` (before/after side by side,
  shared colour scale + extent, both panels dated) and `heatmap_delta` (per-point change) —
  reporting §4.3 — added to `api/services/heatmap.py` on slice 1's deterministic footing. The
  delta's inverted-rank trap is handled: `delta_band` treats "not found" as worse than any real
  rank so `absent→ranking` is green and `ranking→absent` is red, but **absent-in-both renders
  neutral, never red**; the legend is directional words only (no numbers), and the view is made
  visually distinct from a state heatmap (tinted field + dashed frame). Guards
  (`assert_delta_renderable`, `DeltaNotRenderable`): **span enforced now** (both `scanned_at` +
  new `max_delta_span_days`=45 config); provider-boundary + drift-suppression are built seams
  awaiting a 2nd provider and `prospect_delta` (I-091). Slice-1 `render_heatmap` bytes proven
  **unchanged** across the shared-primitive extraction (reference hashes captured before the
  refactor). Free `render-delta` CLI command (explicit `--snapshot` after + `--compare-snapshot`
  before; writes `heatmap_delta` artifacts with `compare_snapshot_id`; refusals reported
  per-prospect, never a blank picture). +33 unit tests (suite **351**). Renders nothing until two
  scans of one submarket both roll up coverage. Interpretation choices in DECISIONS 2026-08-07.
- **Phase 3 slice 1 — the heatmap renderer — is BUILT and MERGED (#580, `7f7dd3c`).** `api/services/heatmap.py` renders a **deterministic** SVG from `prospect_coverage.rank_vector` + the snapshot's stored geometry alone (no `grid_result`), with the §4.2 colour scale, dead points as hollow grey rings distinct from red "not found", the business's own diamond pin, a legend and a 1-mile scale bar. `report_artifact` provenance table added (migration `20260807130000`, **applied live** — RLS-on/zero-policy, unique on `content_hash` = the §6 cache contract). A free `render-heatmap` CLI command (not in `PAID_COMMANDS`) renders one prospect or a whole snapshot. 25 new unit tests, determinism pinned (identical inputs → identical hash; input reordering can't change it). **Phase 3 is sliced — renderer first, then call hook → outcome/touch + emit webhook → approval gate + PDF → signed URLs/R2 + client views; see DECISIONS 2026-08-07.** Two spec gaps logged not resolved: rank >20 folds to "found, far down" never red (I-089); `score_run_id` FK deferred to Phase 4 (I-090). **No `report_artifact` rows exist yet — the renderer has a live snapshot to draw from now, but nothing has called it.**
- **Phase 1 (ingest + filter) is COMPLETE, verified against a real market, and MERGED to `main`** (#528, squashed as `67f235b`).
- **Phase 1b (lead CRM) is COMPLETE, applied live, and MERGED to `main`** (#534, squashed as `452a726`).
- **The platform-api `outreach` router, Phase 2 storage/partitioning and the pinned grid-geometry generator are MERGED** (#538, squashed as `a7acc05`). Migrations applied live.
- **I-041 is RESOLVED BY DECISION.** `review_count_inferred_zero` is set on **105 prospects**, `review_count` left NULL, with a trigger that records any future contradiction. See §9.
- **Paid runs are now gated in code, not by procedure** (§7.2, closed). `OUTREACH_COMMAND` resolves to `filter` when absent, and every paid command additionally requires `OUTREACH_CONFIRM_SPEND` to equal its own name.
- **I-069 is RESOLVED (#554, `b6700999`).** A partial rollup can no longer pass verification: `finalize_snapshot_rollup()` raises inside the rollup transaction and the retention guard requires its marker. Applied live and verified in both directions. See ISSUES I-069.
- **The LA `ai_region` candidates are drafted (I-073)** from evidence already in the data — 10 of 14 submarket names are unambiguous localities, 3 are not. No engine calls were needed. See ISSUES I-073.
- **The maps geogrid client + `tasks_ready` collector is BUILT and MERGED (#557, `29914108`).** Migration `20260804120000_scan_task.sql` applied live. Two commands — `scan` (paid, one submarket × one keyword) and `collect` (free, never spend-gated). See §8.1a for what it does and §11 for the two things standing between it and real rows.
- **The I-004 spike instrument is BUILT and MERGED (#556, `ccb7e912`)** — `probe-ai-granularity`, nine OpenAI calls, three place names × three samples. **It has not been run.** The key is set as a Railway reference; the run needs a Deploy plus `OUTREACH_CONFIRM_SPEND=probe-ai-granularity`.
- **The `prospect_coverage` rollup is BUILT and MERGED (#559, `d802dbf`; migration `20260805120000`, applied live, 18/18 live checks passing).** Land masking (`grid_point_status`) and dead-point exclusion land with it, because both change the coverage DENOMINATOR. One plpgsql function per snapshot ending in `finalize_snapshot_rollup()`, so `rank_vector` cannot be separated from the numbers it belongs to. A free `rollup` command, and `collect` now rolls up what it finalizes. See §8.0b.
- **The placeholder score is BUILT and MERGED (#561, `902be5f`)** — `v_prospect_placeholder_score` (migration `20260805150000`), a view over `prospect_coverage`. Deliberately NOT a `prospect_score` row: that table is the Phase 4 model's and `v_prospect_ranked` already reads it as a fitted score (ISSUES I-082). **I-078 is RESOLVED** — `scan_snapshot` now records its own grid centre, which had to land before the first snapshot rather than after.
- **THE UI IS BUILT (2026-08-06, owner ruling — see the DECISIONS.md signed-order entry; resolves I-072).** Three slices, all merged to the working branch: the `scan_request` signed-order table + the outreach `tick` command (collect + drain at most one order; NOT env-gated — the order row is its confirmation; closes I-086 with a `cost_ledger` write in `submit_scan`); six platform-api routes (place/cancel/list/detail/keywords/placeholder-scores — place and cancel are ADMIN-gated, the click is the spend authorization); and the suite SPA page `frontend/src/pages/Outreach.tsx` at `/outreach` (queue-a-scan with an explicit confirm step, order list with live progress x/81, coverage results honouring I-076's empty-means-not-measured). **What the Railway service needs now is ONE one-time change:** `OUTREACH_COMMAND=collect` replaced by `OUTREACH_COMMAND=tick` and a frequent `cronSchedule` (`*/15 * * * *`) — after which the §11b variable dance is never needed for a scan again; the env spend gate remains for CLI/emergency use. I-088 (auto-deploy suspected re-enabled) still wants a dashboard answer, though under `tick` an extra deploy is a free heartbeat.
- **The first scan is PREPARED, not run** (2026-08-06). Live Railway config read and recorded, the target picked (`Van Nuys` × `plumber`, with reasoning), the runbook written and the post-run read built as `queries/first-scan-verify.sql` — 14 checks, every statement executed against the live schema so it parses. **See §11b.** The three things it waits on are still the three in §11, and all three are the owner's. Five findings came out of reading the paths the run is about to execute: **I-083** (the first snapshot is the likeliest to be incomplete, which pins its partition forever), **I-084** (how `serp_result` attaches to a grid-shaped `scan_snapshot` — this blocks 2d's design), **I-085** (I-071 has half-fixed itself), **I-086** (**the geogrid spends money and writes no `cost_ledger` row, and the budget ceiling does not cover scans**) and **I-087** (`recovered_by_tag` exists only in a log line). None are fixed.
- ~~**NOTHING HAS BEEN SCANNED.**~~ **SUPERSEDED 2026-08-08 — the first scan is done (top of file).** The scan layer now has a producer, a consumer, AND data. The `tick` command is live on a 15-minute cron (since 2026-08-07) and drains scan + onboard orders; the env spend gate remains for CLI/emergency use only. The `filter`-then-set-back procedure this bullet described no longer governs the normal path — the signed-order model does (§11 note below).

**Two things changed on 2026-08-03 that will mislead you if you read the older sections first.** The spend gate above supersedes the "set it back to `filter` afterwards" procedure this file used to rely on (§7.2), and the Railway configuration recorded in §1 was found to be **stale in two ways that each cost money** — read `get-service-config`, not this file, for live values.

**The biggest structural thing remains architectural: this is an AR Tools suite module, not a standalone tool.** See §2. It supersedes parts of what Phase 1 recorded, and reading Phase 1's decisions without it will mislead you.

---

## 1. What exists right now

| Thing | Where | State |
|---|---|---|
| Code | `outreach/` in `kssabraw/ar-tools` | all merged to `main` — Phase 1, 1b, Phase 2 foundations (#538), I-069 (#554) |
| Phase 1 PR | [#528](https://github.com/kssabraw/ar-tools/pull/528) | **merged** 2026-07-31 |
| Phase 1b PR | [#534](https://github.com/kssabraw/ar-tools/pull/534) | **merged** 2026-07-31 as `452a726` |
| Phase 2 foundations PR | [#538](https://github.com/kssabraw/ar-tools/pull/538) | **merged** as `a7acc05` |
| Database | Supabase project **Outreacher**, ref `fkwhgvcggvsricuinuqy` | Phase 1 + 1b + Phase 2 storage + the report feature's tables (`ai_region`, `ai_scan_result`, `report_approval`, `report_pdf_storage` + the `outreach-reports` bucket) all applied; LA ingested, filtered, scanned |
| Job runner | Railway service **outreach**, id `928c84bc-d7ca-416a-bd61-39e91cc64872` in project `ar-tools` (`2c718e53-73c8-4de8-bef8-7136f06b6ead`) | no cron schedule; auto-deploy-on-push DISABLED (2026-08-01); source **actually** on `main` since 2026-08-03 (the 2026-08-01 repoint did not stick — I-065). Runs only on a manual Deploy |
| platform-api integration | `routers/outreach.py` + `services/outreach{,_db}.py` | **built** — read-only over the pipeline, read/write over the CRM, scan/onboard orders, and the report surface (justification / report / report-pdf). Nothing here spends; paid work stays on the Railway job |
| Suite UI | `frontend/src/pages/Outreach.tsx` at `/outreach` | **built + merged** (#571 scan trigger, #574 CRM board, #601/#603/#606/#611 any-city onboard). Queue a scan by city + consumer search; live progress; coverage + businesses views; CRM board with one-click promote |
| Grid geometry | `api/services/geometry.py` | **built**, version `v1`, **81 points** (I-025 resolved) |
| Geogrid scan client | `api/services/maps_scan.py` (pure) + `scan_runner.py` (I/O) | **built** (#557), **RUN LIVE 2026-08-08** — first scan collected 81/81 points |
| Scan bookkeeping | `scan_task` table, migration `20260804120000` | **applied live**; 81 rows (all `collected`) from the first scan |
| Coverage rollup | `rollup_snapshot_coverage()` + `grid_point_status`, migration `20260805120000`; `api/services/coverage_rollup.py` | **applied live**, verified by `tests/coverage_rollup.sql` (18 checks). **Run live 2026-08-08** — 1 snapshot rolled up, 119 coverage rows |
| Any-city onboard | `onboard_request` table (`20260808120000`) + `api/services/onboard_queue.py` + platform-api `services/outreach_geo.py` | **built + merged + run live** — discover→filter→scan any Google city + consumer search; drained by `tick` |
| Placeholder score | `v_prospect_placeholder_score`, migration `20260805150000` | **applied live**, **producing real rows** over the first scan's coverage. `prospect_score` stays empty until Phase 4 (I-082) |
| Report artifacts | `report_artifact` table (`20260807130000`) + `api/services/heatmap.py` | **built + merged** (#580/#589). Renderer has a live snapshot to draw from; **no artifacts rendered yet** |
| Per-prospect report | `services/outreach_justification.py` + `outreach_report.py` + `components/outreach/ProspectReport.tsx` | **built + merged** (#615–#619). Call hook ("Why call?") + internal/client report, 3 signals (maps/organic/AI), approval-gated client PDF + signed URL. Deterministic + fact-grounded |
| Organic scan | `api/services/organic_scan.py` + `scan-organic` command | **built + merged** (#616). PAID + gated; one live SERP per snapshot → `serp_result`. **Never run** |
| AI-visibility scan | `api/services/ai_visibility.py` + `scan-ai` + `ai_region`/`ai_scan_result` (`20260808140000`) | **built + merged** (#617). PAID + gated; ChatGPT + Google AIO per region×keyword; `ai_region` seeded with 11 LA names. **Never run** |
| Client-report storage | `report_approval` (`20260808160000`) + `report_pdf_storage` (`20260808180000`) + private `outreach-reports` bucket | **applied live**, empty. Approval record (actor + content_hash + storage_path) + signed-URL delivery on Supabase Storage (reporting §5, not R2) |
| Paid placement (Slice A) | `organic_scan.py` paid/LSA parse + `outreach_report.derive_paid_signal` | **built + merged** (#621). Presence from the SERP already on disk — no new paid call. Reads `not_scanned` until `scan-organic` runs |
| Site tech signals (Slice B1) | `api/services/tech_signals.py` + `scan_tech.py` + `prospect_tech_signal` (`20260808200000`) | **built + merged** (#621), migration applied live. FREE (`scan-tech` is NOT in PAID_COMMANDS). **Auto-runs each `tick`** (`run_tech_backlog`, throttled to `tech_scan_min_interval_seconds`; DECISIONS 2026-08-14); manual `scan-tech` remains for a single seeded market |
| §16a.1 pixel spike | `api/services/pixel_probe.py` + `probe-pixel-field` | **built** (#621). PAID + gated; decides whether the Outscraper pull supplies Meta pixel near-free (I-003). **Never run** |
| Ad-spend magnitude (Slice B2) | — | **NOT built**, deliberately — gated behind the Labs yield spike (I-098) |
| I-004 spike | `api/services/ai_granularity.py` + `probe-ai-granularity` | **built** (#556), **never run** — needs a Deploy + confirm token |
| First-scan runbook + read | `HANDOFF.md` §11b · `queries/first-scan-verify.sql` | **prepared 2026-08-06**, never executed. The scan itself still waits on the three owner-side steps in §11 |

**This is a SEPARATE Supabase project from AR-Internal-Tools.** Do not point outreach code at the suite's database, and do not put outreach migrations in `writer/supabase/migrations/`.

Live row counts (2026-08-08, after the first scan): `prospect` **1,407** (105 carrying `review_count_inferred_zero`, §9) · `submarket` **15** · `keyword` **6** · `market` **2** (the seeded LA-Plumbing market + the any-city onboard's "Los Angeles, CA, USA") · **`scan_snapshot` 1 · `scan_task` 81 · `grid_result` 1,620 · `prospect_coverage` 119 · `snapshot_rollup` 1 · `grid_point_status` 81** · `onboard_request` 1 (done) · `scan_request` 0 · `report_artifact` 0 · **`ai_region` 11 (LA, seeded from I-073) · `ai_scan_result` 0 · `serp_result` 0 · `report_approval` 0 · `prospect_tech_signal` 0** (the report feature's tables — the report reads the LIVE maps coverage, but its organic/AI scans and client-PDF approvals have not been run yet). **The scan layer has a producer, a consumer, and — for the first time — data.**

### Railway service configuration

```
source           kssabraw/ar-tools @ main   ← ACTUALLY repointed 2026-08-03. The 2026-08-01
                                             repoint did not stick: the service still tracked the
                                             merged phase-1 branch and a Deploy built its HEAD
                                             (I-065). Verify with get-service-config, not here.
rootDirectory    /outreach
railwayConfigFile  outreach/railway.toml   ← repo-root-relative, NOT relative to rootDirectory
builder          DOCKERFILE (from railway.toml)
restartPolicy    NEVER                     ← this is a job; ALWAYS would re-run the paid ingest in a loop
cronSchedule     (none yet)
startCommand     sh -c "exec python -m api.scripts.run_market ${OUTREACH_COMMAND:-filter} ${OUTREACH_MARKET:-markets/los-angeles-plumbing.json} ${OUTREACH_ARGS:-}"
                 ← ${OUTREACH_ARGS:-} added 2026-08-03. Its absence silently dropped every flag
                   ever set in OUTREACH_ARGS and cost ~$0.11 (I-064).
```

Variables set: `OUTREACH_SUPABASE_URL`, `OUTREACH_SUPABASE_SERVICE_ROLE_KEY`, `OUTREACH_OUTSCRAPER_API_KEY`, `OUTREACH_COMMAND` (currently `filter`), `OUTREACH_MARKET`, `OUTREACH_ARGS` (empty), `OUTREACH_CONFIRM_SPEND` (empty), and DataForSEO credentials as Railway reference variables.

**This block is a snapshot and has been wrong twice.** Both the source branch and the start command above were stale in ways that cost money. Read `get-service-config` and `list-variables` for the live values; see repo-root `CLAUDE.md` → "Railway: read the live config, do not infer it".

~~**There is no DataForSEO credential on this service.**~~ **Set 2026-08-01** as Railway reference variables, and **exercised for real 2026-08-03** — the `verify-reviews` control run completed against `my_business_info/live` (I-066). ~~The Phase 2 *scan* client is still not built.~~ **Built 2026-08-04 (#557); never run.** `OUTREACH_OPENAI_API_KEY` was added the same day as a reference to `${{PLATFORM.OPENAI_API_KEY}}` for the I-004 spike.

> The Outscraper key and the Supabase service-role key were pasted into a chat transcript during the Phase 1 build. Rotating both is cheap and worth doing.

---

## 2. THE RULING THAT CHANGES HOW YOU READ EVERYTHING ELSE

**The outreach pipeline is an AR Tools suite module** (owner ruling, 2026-07-31). Recorded in `DECISIONS.md`.

It **amends, without withdrawing,** Phase 1's decision that the code lives in this repo while the database is a separate Supabase project. The storage half of that reasoning stands — ~64M `grid_result` rows a year would eat the suite project's headroom, and the storage spec sized partitioning for a dedicated project.

What was wrong was the *inference*. Phase 1 recorded a consequence: *"a separate project means a separate `auth.users` pool… do not expect SSO with existing AR Tools users."* That let a decision about where the **data** lives decide where the **application** lives. Those are separable.

**So: the database stays in Outreacher; the API and UI move into `platform-api` and the suite SPA.**

This dissolves the SSO cost rather than paying it. platform-api holds the Outreacher service-role key and is the **only** client, so staff authenticate against the suite exactly as for every other module and never need an Outreacher account.

### What follows from it — do not undo these by accident

- **Retool is dropped.** So is the per-user RLS model built for it. §8a of the CRM spec says to write per-owner policies at launch; that instruction was aimed at a direct database connection which no longer exists. The policies are **removed**, not left permissive-and-tightened-later — a policy on a table nothing reaches through PostgREST is an access model that looks load-bearing and is not.
- **Access is service-role only**: RLS enabled, zero policies, no grants to `anon`/`authenticated`. Same posture as every other table in the estate.
- **Authorization belongs in platform-api**, beside the suite's existing role checks.
- **Identity columns have no foreign keys.** `lead.owner_id`, `lead_activity.actor_id`, `lead.created_by` carry the **AR Tools** profile id from AR-Internal-Tools. Postgres cannot enforce that across databases. Dropping the FKs loses real integrity; the alternative was a column pointing at a pool that will stay permanently empty.
- **No cross-database joins.** A won lead becomes an AR Tools client through an API call, not a foreign key. Worth knowing before designing a report that assumes otherwise.
- **Anything telling you to create Supabase auth users for this project is out of date** (`ISSUES.md` R-011).

---

## 3. The Los Angeles result (real, verified)

Market `Los Angeles, CA — Plumbing`, 14 submarkets, category `plumber`.

| | |
|---|---|
| Listings returned (billed) | 2,807 across 15 tile-pulls |
| Prospects after `place_id` dedup | **1,388** |
| Tile overlap rate | 14.7% |
| Cost recorded | $5.68 — **at the placeholder rate, see §7.1** |
| Survived the filter | **925** |
| Excluded | 463 |
| Flagged as possible franchise | 22 (all still in play — flag never excludes) |

Failures per rule: `review_count_min` 433 · `has_phone` 46 · `not_franchise` 22 · `business_status_open` 14 · `not_suppressed` 0 · `review_recency` 1,388 `not_evaluated`.

Every acceptance criterion in `docs/PHASE-1-BRIEF.md` §5 is met. Verified independently: 30 prospects failed more than one rule with every rule logged (not first-match-only); all 1,388 are in California (one distinct state); every prospect has a submarket; `prospect_score` was never written.

**2,807 listings cost roughly double what one clean run costs** — two full ingests ran (see §6.4). A single LA run is ~1,400 places.

---

## 4. Running it

```bash
# tests — no network, no database
cd outreach && python -m pytest api/tests -q      # 276 passing

# locally (needs OUTREACH_* env vars and network egress to Outscraper + Supabase)
python -m api.scripts.run_market seed      markets/los-angeles-plumbing.json
python -m api.scripts.run_market calibrate markets/los-angeles-plumbing.json   # 1 tile, ~20 places
python -m api.scripts.run_market ingest    markets/los-angeles-plumbing.json   # PAID
python -m api.scripts.run_market filter    markets/los-angeles-plumbing.json   # free
python -m api.scripts.run_market run       markets/los-angeles-plumbing.json   # seed+ingest+filter
python -m api.scripts.run_market collect   markets/los-angeles-plumbing.json   # free — and rolls up
python -m api.scripts.run_market rollup    markets/los-angeles-plumbing.json   # free — backlog only
python -m api.scripts.run_market rollup    markets/los-angeles-plumbing.json --verify   # writes nothing
```

On Railway, the run mode is `OUTREACH_COMMAND`. **Only `ingest` and `run` spend money.**

Success is the log line `OUTREACH_RESULT status=ok command=<cmd> exit=0`. **The Railway deployment status is NOT a success signal** — see §6.2.

Definition-of-done SQL: `queries/phase1-dod.sql`. Adding a market: copy `markets/EXAMPLE-kansas-city-plumbing.json`, fill it in, `seed`. Idempotent.

**The CRM verification script** is `tests/lead_crm_rls.sql` — paste into the Supabase SQL editor for Outreacher, or run through the MCP `execute_sql` tool. 17 checks, self-cleaning fixtures, every line prints `(correct)` or `(WRONG)`.

---

## 5. Phase 1b — the lead CRM

Applied live and verified. Detail in `PHASE1B-STATUS.md`; the reasoning is in `DECISIONS.md` and `ISSUES.md` R-011/R-012.

| Object | Notes |
|---|---|
| `lead` | spec §3 shape: six-value `source`, seven-stage workflow, `lost_reason` + `lost_to`, `next_action`/`next_action_due`, `stage_changed_at` |
| `lead_activity` | append-only commentary; real `from_stage`/`to_stage` columns; `touch_id` carried **without** its FK until Phase 3 creates `touch` |
| `lead_stage` | lookup table carrying the spec's seven stages, plus `sort_order`/`is_terminal` for the board |
| `suppression` | Phase 1's table, patched additively. **No delete path** — spec §4 says these records are never deleted |
| `lead_inbox`, `lead_detail`, `v_overdue_actions` | `security_invoker` views |
| `lead-intake` edge function | deployed, fails closed until `LEAD_INTAKE_SECRET` is set (§7.5) |

### Read the two migrations in order

`20260731150000_lead_crm.sql` then `20260731190000_lead_crm_spec_reconcile.sql`. The first is **deliberately left wrong** with comments explaining each mistake; the second corrects them. That history is the point — see §6.11.

### Invariants specific to this layer

- **`outcome` is outbound-only, and it is Phase 3's table.** Phase 1b creates neither `outcome` nor `touch`. It ships `lead.unique (prospect_id, source)` as the FK target that makes the rule structural rather than a trigger convention — because a *promoted inbound lead also carries a `prospect_id`*, so keying on prospect alone cannot distinguish them. Full DDL for Phase 3 in `PHASE3-outcome-constraint.md`. Verified live against the real key with a throwaway probe table.
- **Suppression flags, never rejects.** Matching lives in a `BEFORE INSERT` trigger so no write path can skip it, and a match sets `suppressed_at` rather than refusing the row. Discarding an inbound lead because a stale suppression matched is unrecoverable; a flagged row is visible and reversible.
- **`lead_activity` is human commentary only.** `touch` is authoritative for "a contact attempt happened". There is no `email_sent` or `call` kind; a call writes a `touch` and a `call_note` referencing it.

---

## 6. Traps — every one of these cost real time or money here

> **The Railway-specific ones now live in repo-root `CLAUDE.md` → "Railway: read the live config, do not infer it", which auto-loads every session.** Read that first. Its framing matters and is not cosmetic: on 2026-08-03 a plausible explanation *from this very section* was believed instead of measured, and cost ~$0.11 (I-064). The traps below are evidence that this environment's config diverges from what the repo implies — never a substitute for reading the live config.

### 6.1 Railway `redeploy` replays the OLD deployment's config
Changing `startCommand` and calling redeploy silently re-runs the *previous* command. Twice, and it looked identical each time. Only a **fresh deployment** picks up config changes. This is why run mode is driven by `OUTREACH_COMMAND` through one entrypoint.

Then a third time, and it cost money: a `verify-reviews --group control --limit 5` intent was set on the service, `redeploy` replayed the snapshot from before those variables existed, and the run executed the bare `verify-reviews` default — 20 lookups, ~$0.11, against a group that had already been measured. **This section existed and was not read first.** That is a discoverability failure rather than a discipline one, so the Railway-specific traps (this one, the auto-deploy pinning, `update-service` not handling source changes) now live in the repo-root **`CLAUDE.md` → "Railway: read the live config, do not infer it"**, which auto-loads every session. Note the framing changed deliberately: the trap list itself turned out to be the hazard — a plausible remembered explanation displaced a one-call measurement (I-064) — so CLAUDE.md now leads with *read the live config* and treats the traps as evidence that config diverges, not as a list to reason from. Keep this section; treat CLAUDE.md as the copy that gets read.

### 6.2 Railway reports a CRASHED job as deployment status SUCCESS
With `restartPolicy: NEVER`, a job that dies on an unhandled exception still shows SUCCESS and posts a green commit status to the PR. Trust `OUTREACH_RESULT`, not the badge.

### 6.3 The Railway log stream LAGS the container — do not diagnose from it
A run was concluded dead at 09:09:54 because logs stopped. It completed at 09:11:01. The Railway agent agreed with that diagnosis **because it was reading the same lagging stream** — that is not corroboration. **Check `cost_ledger` and `prospect` in the database**; those are written synchronously and are ground truth.

### 6.4 …and that misdiagnosis caused a duplicate paid ingest
Pushing the "fix" auto-deployed while `OUTREACH_COMMAND=run` was still set, firing a second full pull nobody asked for — about half the $5.68. **Set `OUTREACH_COMMAND` back to `filter` immediately after any paid run.** See §7.2.

### 6.5 PostgREST silently caps an unbounded `select()` at 1000 rows
No error, no header, nothing a caller notices. `run_filter` read 1,000 of 1,388 prospects and left 215 unfiltered; "how many survived" would have undercounted, confidently. **Every read that grows with the portfolio must go through `services/paging.fetch_all`.** Its argument is a *callable* — supabase-py builders are stateful, and reusing one compounds `.range()` instead of replacing it, which pages wrongly in a way that also looks fine.

### 6.6 A directory named `supabase/` shadows the installed `supabase` package
Migrations live in `outreach/migrations/`, not `outreach/supabase/`. Once `/outreach` is on `sys.path`, Python resolves `from supabase import Client` to the directory and fails as `cannot import name 'Client' from 'supabase' (unknown location)`, which reads like a version problem.

### 6.7 Tile geography must be pinned TWICE
A pull for `plumber, Downtown Los Angeles` with no coordinates and no region returned businesses in **Jersey City, New Jersey**. Both the `coordinates` bias *and* the `region` qualifier are required. The failure mode is the dangerous kind: a market full of the wrong state's businesses parses at 100%, passes every filter, and is worthless.

### 6.8 The AR Tools repo is a source of verified provider behaviour
`writer/platform-api/services/gbp_service.py` has been calling Outscraper with this same API key in production for months. **Check the repo before the vendor docs.**

### 6.9 Outscraper returns errors as HTTP 2xx
`{"error": true, "errorMessage": ...}` in the body with a 200 status. Status-code-only handling swallows them.

### 6.10 Railway's `railwayConfigFile` resolves against the REPO ROOT
Not against `rootDirectory`. Getting it wrong means the config is never read and the builder silently falls back to Railpack. It must be `outreach/railway.toml`.

### 6.11 Building from a plan *derived from* a spec is not building from the spec
Phase 1b's schema was built from a plan written against `crm-layer-spec.md` without the spec in context. Four vocabularies were guessed, and the worst — `source` — could not record a `manual` lead, which is the entire reason the CRM track runs in parallel with Phase 1. **If a spec exists, open it.** Corrected in `ISSUES.md` R-012.

### 6.12 Supabase grants ALL to `anon` and `authenticated` by default — REVOKE FIRST
A bare `grant select, insert` on a new `public` table **adds nothing and removes nothing**. It reads like a restriction while leaving UPDATE, DELETE and TRUNCATE in place. Two consequences, both live for a while here:
- **An UPDATE with no matching RLS policy is not an error — it silently affects zero rows.** Append-only on `lead_activity` was resting on the absence of a policy, so a "save note" button would have reported success and changed nothing. A silent wrong outcome is worse than a refusal.
- **TRUNCATE is not subject to RLS at all.** No policy can stop a role that holds it; only the grant can.

### 6.13 `SECURITY DEFINER` functions in `public` are callable as RPC
All three CRM trigger functions were reachable at `/rest/v1/rpc/<name>` by `anon`. Invoking a trigger function directly errors, so it was not exploitable — but that is a weak thing to rely on for a definer-rights function. **Revoke `execute`.** Found by the Supabase security advisor, *not* by the verification script: the two catch different classes of problem, so run both.

### 6.14 `now()` is TRANSACTION time — it will fake a test failure
Comparing `stage_changed_at` to `created_at` inside one transaction shows no movement whether the trigger fired or not, because both resolve to the same transaction timestamp. That false failure is exactly what invites someone to "fix" a working trigger. Backdate the column first, then act. Same reason `now()` is illegal in an index predicate (it is not immutable) — filter liveness at query time instead.

### 6.15 Two branches appending to the same `ISSUES.md` collide silently
Phase 1 and Phase 1b ran in parallel and both appended from the same `I-014` base. Both defined `I-015`…`I-019`, differently. Nothing in git flags it — the files merge cleanly and you end up with two `I-017`s. Phase 1b's were renumbered to **I-037+**. If you see a pre-2026-07-31 reference to "I-017", it means the CRM schema divergence, now **R-012**.

---

### 6.11 Railway's service-config API reports the DEPLOYED config, not the staged one
Changing the source branch through the Railway agent returned "applied — staged for deployment", and reading the config back through `get-service-config` still showed the **old** branch. Both were telling the truth about different things: the change was staged, and the API reports what is currently deployed. The dashboard (Settings → Source) showed the new branch immediately and is the tiebreak.

Worth knowing before someone concludes a write silently failed and applies it a second time. Same family as §6.3 — when two instruments disagree, find a third rather than trusting the more convenient one.

---

### 6.12 After a squash merge, RESTART the branch — do not keep committing on it
Hit twice in one session, both times as a merge conflict that looked like someone else had touched
the files. Nobody had.

A squash merge replays your commits onto `main` as ONE NEW commit with a different SHA. The branch
still holds the originals. Keep committing on it and the branch now contains the same content
twice — once as your commits, once as main's squash — and the next merge conflicts on every file
both sides touched. `ISSUES.md` and `HANDOFF.md` are the usual casualties because every change
appends to them.

The fix is mechanical and takes ten seconds:

```
git fetch origin main
git checkout -B <branch> origin/main
git cherry-pick <only the commits made SINCE the merge>
git push --force-with-lease
```

Cherry-picking applies cleanly because main already carries the earlier content — the conflict was
never a real disagreement, only two spellings of the same change. Verify with
`git log --oneline origin/main..HEAD`: it should list only work that has never been merged.

---

## 7. What is NOT done

### 7.1 The Outscraper billing rate is still a placeholder — do this first
`outscraper_cost_per_1000_places_cents` is **200¢/1000, a guess**. Every cost figure above and the `max_market_run_cost_cents` abort gate are only as honest as that number. 2,807 places have been pulled; divide the Outscraper dashboard charge for 2026-07-31 by 2,807, multiply by 1000, set the variable. (`ISSUES` I-033.)

### 7.2 A paid run should need more than a variable — AND THE BLAST RADIUS JUST GREW
`OUTREACH_COMMAND=run` plus deploy-on-push means **any push to the tracked branch fires a paid ingest**. This actually happened (§6.4). Before any cron schedule is set, gate paid runs behind something the deploy path cannot supply on its own.

**Repointing the source to `main` on 2026-08-01 made this materially worse, and the mitigation was not applied.** While the service tracked a dead feature branch, nothing ever pushed to it and the footgun was close to theoretical. Tracking `main` in a repo that merges several PRs a day means **every unrelated merge now deploys and runs this job.** At `OUTREACH_COMMAND=filter` that is free but noisy — a filter re-run over 1,388 prospects and a $0 ledger row per merge. If the command is ever set to `run` or `ingest` and not put back within minutes, the next merge by anyone, on any unrelated PR, spends money.

**DONE 2026-08-01: "Auto deploys when pushed to GitHub" is disabled.** Merges to `main` no longer deploy or run this job; it runs only on a deliberate Deploy click. The branch connection stays, so Railway still knows where to pull from.

> **⚠ CONTRADICTED 2026-08-06 — I-088.** The five most recent deployments track commits merging to
> `main`, two of them unrelated PRs. Either this was re-enabled or it never stuck (the same shape as
> I-065). **Confirm in the dashboard before setting `OUTREACH_COMMAND=scan`** — the runbook asks you
> to create exactly the state where every merge fires a paid run, and the spend gate does not cover
> it because the token would be legitimately set. Nothing has been spent: all of 2026-08-06's
> `cost_ledger` rows are `a2_filter / 0 cents` and the scan tables are still empty.

**That narrows the trigger. It does not close this item.** Two ways the risk returns, both foreseeable:
- **A manual Deploy while `OUTREACH_COMMAND` is `run` or `ingest`** still spends money — now the likeliest remaining path, because it is the same click used for a legitimate free `filter` run.
- **Setting a `cronSchedule`**, which is the plan once the first real ingest is validated, re-arms it twice over: a Railway cron service runs its start command **on every deploy as well as on schedule** (noted in `railway.toml`). Whatever gates paid runs must exist *before* that schedule is set, not after.

**CLOSED 2026-08-03 — the token exists.** `spend_denial` (`api/scripts/run_market.py`) implements exactly what this item asked for, and it was built because the procedural version failed: a `redeploy` ran `verify-reviews` and spent ~$0.11 that nobody approved, *after* the "set it back to `filter`" procedure had been followed (I-063, I-064).

- Absent, empty or whitespace `OUTREACH_COMMAND` resolves to `filter` (`resolve_command`). The safe command is what you get by omission.
- Every paid command (`ingest`, `run`, `calibrate`, `verify-reviews`) additionally requires **`OUTREACH_CONFIRM_SPEND` to equal that command's own name**, checked before the handler and before any credential is opened. `probe-dataforseo` is free and ungated until `--sample-place-id` makes it bill.
- The token names the command *deliberately*. A boolean would authorize whatever happens to be set, which is this incident exactly. A name-matched token means a replayed or half-updated config cannot spend: the leftover confirmation names a different command than the one about to run.
- The two variables fail safe independently — change the command and forget the token → refused; leave a token behind and the command reverts to `filter` → nothing paid to authorize.
- Line one of every run now reads `command=… PAID confirm=…` beside the SHA, and a refusal exits non-zero through the `OUTREACH_RESULT` marker.

**This is what must be in place before a `cronSchedule` is set**, per the paragraph above. It now is. Setting the schedule no longer re-arms the footgun on its own, because a scheduled deploy carries no confirmation token.

### 7.3 Grid geometry — SETTLED at 81, confirmed by the owner 2026-08-01
`ISSUES` I-025 is closed. `reporting-layer-spec.md` §4.1 is the only document that *defines* the generator — "square lattice covering the bounding box, row-major from NW corner, clipped to distance <= radius_miles" — and that construction holds exactly **81** points. Every alternative was computed rather than assumed: hexagonal **91** (π·25·2/√3 = 90.7, the likeliest origin of a remembered "89"), concentric rings **41**, unclipped 11×11 box **121**. Nothing produces 89, and the PRD hedges it as "~89" because it was an estimate.

Built as `api/services/geometry.py` version `v1`; `README.md`, PRD §8b and the storage spec's volume arithmetic corrected with markers rather than silently.

**Confirmed by the owner on 2026-08-01, with the cost lever considered and declined.** This is no longer an inference from the specs — it is a ruling. Treat `radius 5 / spacing 1 / 81 points` as fixed, and see DECISIONS.md for why coarser spacing was rejected as a cost lever.

**The recurring confusion, recorded so it is not relitigated:** a 5-mile *radius* is 10 miles across, so a 1-mile lattice has **11** points per row (5 west + centre + 5 east), not 5. 11 x 11 = 121 in the bounding box, 81 after clipping. "25" comes from reading the 5 as a side length rather than a radius; it would need ~1.67-mile spacing, and a 5x5 box at 2.5-mile spacing clips to 13, not 25.

### 7.4 `ai_region` does not exist
Not as a table, not as data. AI checks run per `ai_region`, which is a *different and coarser* geography than `submarket` — several submarkets share one region. Drafting the names is a Phase 0 manual task that was never done, and it needs human judgement about which place names an LLM actually recognises. Blocked on §8.2.

### 7.5 Smaller open items
- **I-037** — `LEAD_INTAKE_SECRET` unset; the intake function fails closed and has **never been invoked**. Under §2 it is also a candidate for retirement in favour of a platform-api route.
- **I-038** — Phase 1's live `suppression` (`id, scope, value, created_at`) does not match spec §3 (separate `email`/`phone` columns). Recommendation: amend the spec — scope/value generalises to `place_id` suppression, which fixed columns cannot express.
- **I-039** — spec §3 indexes `lead_activity (prospect_id, …)`, a column that does not exist in its own DDL. Logged rather than silently corrected, per the session protocol.
- **I-034** — nothing reads `OUTREACH_RESULT` yet. A log line nobody greps ≈ a green tick nobody questions.
- **I-020/I-026** — franchise pattern list is an unvalidated seed. 22 matched in LA. Improvable from data: a name at ≥3 distinct `place_id`s in one market is almost certainly a chain.
- **I-024** — the raw landing dir is on-disk and opt-in; it belongs in R2 in Phase 2.

---

## 8. What to do next

### 8.0 Done on 2026-08-01 — all three former §8.1 items (PR #538)

**The platform-api `outreach` router.** `routers/outreach.py` + `services/outreach.py` + `services/outreach_db.py`, 24 unit tests. The project-scoped client turned out to be the one real divergence from `leadoff_db.py`: that scopes to a second SCHEMA, this reaches a second **PROJECT**, so `ClientOptions(schema=…)` buys nothing and it needs its own URL, its own key, and an `outreach_configured()` predicate so an unprovisioned deploy answers `503 outreach_not_configured` instead of failing inside the first query. **Nothing in it can spend money** — ingestion stays on the Railway job.

Funnel aggregation runs in Postgres (`v_prospect_status`, `outreach_market_summary()`, migration `20260801100000`) — storage spec §9 requires it, and with 8,328 `filter_result` rows a Python-side funnel would have hit PostgREST's silent 1,000-row cap on day one (§6.5). Verified live against LA: 1,388 / 925 survived / 463 excluded / 22 flagged, matching §3 exactly.

**Phase 2 storage foundations** (migration `20260801120000`, applied live). `scan_snapshot`, `grid_result` (partitioned by month, no lat/lng), `serp_result` (partitioned identically), `grid_result_retained`, `prospect_coverage`, `grid_result_all`, `storage_retention_log`, `create_month_partitions()`, `verify_grid_result_months()`, `drop_cold_partitions()`, and two `pg_cron` schedules. Verified by `tests/storage_partitioning.sql` — **14 checks, run live, all passing** (a pass reports `ERROR: ROLLBACK — 14 checks passed`).

**No default partition**, deliberately: it never loses a row, but once a month's rows land in it that month's partition can never be attached, which surfaces months later on a huge table. The retention job **fails closed on everything it cannot verify**, including `audit_asset` and `slot`, which do not exist yet — so today it drops nothing but empty partitions. Correct, and not the same as finished.

**The pinned grid-geometry generator** — see §7.3. 81 points, version `v1`, 18 tests with hand-derived expectations.

**A defect fixed on the way (I-040).** `lead_log_changes` stamped `actor_id := auth.uid()`, which is NULL for the service role, so under §2 every stage change would have been logged anonymously. `lead.updated_by` added; the trigger prefers it. **The sweep for others came back clean:** one instance total. Swept as two lists, because the failure modes differ — expressions that RUN and receive null (defaults, generated columns, CHECKs, views, trigger bodies, `request.jwt` readers) versus RLS policies, which are bypassed silently and never evaluated. Zero of the former beyond `lead_log_changes`; zero policies exist at all. Re-run after any migration that adds a trigger or a default; only the first list can regress.

**And one found, not fixed (I-041).** `review_count_min` is 842 passed / 433 failed / **113 not evaluated** — Outscraper returned no review count for those 113 and they sit inside the 925 "survivors". Population evidence splits them: `review_count = 0` never occurs anywhere in 1,388 rows while counts of 1/2/3–5/6–9 occur 118/70/129/116 times, so null reads as the provider's encoding of zero; 105 of the 113 also have a null rating (consistent with genuinely zero reviews), and **8 have a rating but no count**, which cannot both be true and are genuinely unknown. The direct Google Maps spot-check **could not be run** — Google 403s every route and egress is blocked (I-027) — so this is strong circumstantial evidence, not confirmation. Ten place_ids plus all 8 anomalies are queued in `ISSUES`.

### 8.0a Done on 2026-08-04 — the geogrid producer (#557) and the I-004 instrument (#556)

**The maps geogrid client + `tasks_ready` collector.** `api/services/maps_scan.py` (pure: task bodies, `task_post`/`tasks_ready`/`task_get` parsing, completeness) + `api/services/scan_runner.py` (submission, collection, finalization) + the `scan_task` bookkeeping table. 42 tests; the suite is at **247**.

The endpoint is QUEUED — `task_post` bills and returns an id, the result is fetched later — so almost every decision is about **ordering**, each chosen so an interruption loses at most one point and always in the cheap direction:

- **`scan_task` rows are written `pending` BEFORE the post.** The naive order has a window where money is spent and no record exists. A row still `pending` afterwards just means "not yet posted": reposting an unposted point costs one point, losing a posted one costs the batch.
- **The tag is a recovery key, not a debug label.** `<snapshot_id>:<point_seq>`, echoed on `tasks_ready`, closes the one window ordering cannot: a request the provider accepted and billed whose response never reached us. This DIVERGES from the suite's `maps_dataforseo.py`, where the tag is explicitly a convenience and alignment is positional — sound there, because that code polls ids it holds. See DECISIONS.md.
- **Grid rows are written before the task is marked collected.** A crash between them re-collects something free to re-collect; the reverse finalizes a snapshot with a hole nothing downstream can detect.
- **`actual_points` counts points SCANNED, never rows written.** A point over water returns an empty pack, and "nobody ranks here" is a finding. Counting rows would mark a submarket's real dead zones as scan failures and exclude it from scoring every cycle — the same correction I-069 needed. DECISIONS.md records it because the mistake has now been made twice.
- **`tasks_ready` RAISES on a shape it cannot read** rather than returning `[]`. Nothing here has ever called that endpoint; an unreadable response reading as "nothing ready" would end the collector's loop, mark the run clean, and leave paid tasks to age off.
- **The month guard.** Collection lands hours or days after submission, so `scan_month` from the clock is right in every test and wrong twice a year (I-044). `assert_snapshot_month()` checks it per snapshot at finalization — one query, not a per-row trigger on a 58M-row/year table — and refuses rather than repairs.

**The I-004 spike instrument** (#556): `probe-ai-granularity`, nine OpenAI calls at temperature 0, three place names × three samples, reporting cross-level overlap, within-level stability, and error/empty counts kept separate. It gathers evidence and deliberately does **not** pick the granularity — that is a human decision recorded in `ai_region.name_level`, and the output says so in the payload rather than only in a docstring. The three place names are required rather than defaulted; I-073's free evidence run already narrowed which LA names are worth testing.

### 8.0b Done on 2026-08-05 — the `prospect_coverage` rollup, land masking, dead-point exclusion

Checklist §4 Phase 2, ISSUES I-042. Migration `20260805120000` applied live;
`api/services/coverage_rollup.py`; 29 new unit tests (suite at **276**) plus an 18-check live
script, `tests/coverage_rollup.sql`, which passes.

**It is one plpgsql function because it has to be.** `rank_vector` must be written in the same
transaction as the summary statistics — a rollup producing coverage percentages without vectors
must FAIL rather than partially succeed, because a vector written later or in the wrong
`point_seq` order renders every historical heatmap against coordinates that were never used to
collect it, with the picture still drawing. PostgREST gives one transaction per call, so a Python
loop that inserted rows and then called `finalize_snapshot_rollup()` physically cannot hold both
halves together. `rollup_snapshot_coverage()` does the whole snapshot and calls the finalizer as
its LAST statement; the finalizer re-derives its counts and raises on a mismatch, aborting
everything. There is a unit test asserting nothing follows that call.

**Geometry arrives as a parameter.** The caller regenerates points through the pinned registry
using the snapshot's **stored** `geometry_version` — never the default — and passes
`[{"seq", "dist"}]`; the function refuses a payload that does not cover `0..expected-1` exactly, or
whose version disagrees with the snapshot. Re-deriving the lattice in SQL would create the second
definition of point membership that `geometry.py` exists to prevent. Distances are
centre-independent, so the rollup never reads the mutable `submarket.center_*` (ISSUES I-078 —
Phase 3's heatmap will, and should not).

**The denominator counts what was MEASURED.** `live_points` = `scan_task.status = 'collected'`
intersected with `grid_point_status.land`. An empty pack stays in (it was measured; "nobody ranks
here" is a finding). An uncollected task leaves entirely (nobody observed that absence). A masked
point leaves the denominator but stays in the vector as `255`, because dead must render
differently from not-found. Third time this correction has been needed — see DECISIONS.md.

**Land masking self-calibrates** (PRD §9a.1): N consecutive null scans mask a point, any non-null
result reactivates it, the counter is shared across keywords, and the whole update happens inside
the rollup's transaction so `live_points` is contemporaneous with the claims made from it. `N` is
`land_mask_null_scans` in config, not a literal in the SQL.

**Cadence:** `collect` now rolls up the snapshots it finalizes — guarded, reported, never raised,
because collection is the paid work being rescued. `rollup` also stands alone for backfill and
`rollup --verify` recomputes every statistic from the stored vectors (storage spec §12). Both are
FREE and must stay out of `PAID_COMMANDS`. Storage spec §7's daily `rollup_coverage` **pg_cron**
job is not buildable — pg_cron cannot call the Python generator — and a third Railway schedule was
rejected for the reason §11 gives about the second one.

**Eight issues logged, not silently resolved** (I-074…I-081). Four matter before the next build:
the second land-masking criterion is **not computable** from stored data (I-074); an incomplete or
prospect-less snapshot pins its partition **forever**, fail-closed (I-075); a prospect present at
**zero** points gets **no row**, so downstream must read a missing row as zero coverage rather than
unknown (I-076); and `centroid_dist_at_loss` has **no formula in any spec** — one reading is
implemented and the other must be chosen deliberately before it reaches a prospect-facing claim
(I-080).

### 8.1 Unblocked, and the highest-regret thing to defer
1. ~~**Repoint the `outreach` Railway service at `main`.**~~ **DONE 2026-08-03.** It had been recorded as done on 2026-08-01 and was not: the service still tracked `claude/phase-1-outscraper-ingestion-llje34`, and a Deploy click faithfully built that branch's HEAD (`7f9430b`, 2026-08-01), failing with `invalid choice: 'verify-reviews'` — a commit old enough to predate both the build banner and the result marker, so it failed silently behind a green badge (I-065). *The lesson is not "repoint it" but "a config change recorded in a document is not a config change"*; verify with `get-service-config`.
2. ~~**The maps geogrid client + `tasks_ready` collector.**~~ **BUILT 2026-08-04 (#557)** — see §8.0a. Not run. The owner ruling stands: **first live run is ONE submarket × ONE keyword**, and `cmd_scan` refuses to do more.
2a. ~~**THE NEXT BUILD: the `prospect_coverage` rollup.**~~ **BUILT 2026-08-05** — see §8.0b. Applied live and verified in both directions; never run against real data, because there is none.
2b. ~~**THE NEXT BUILD: the placeholder score**~~ **BUILT 2026-08-05.** Was: (checklist §4 Phase 2, first item). "Raw geogrid coverage deficit, one SQL expression" — and it reads `prospect_coverage`, which now exists. It reads `prospect_coverage` through a LEFT JOIN gated on the `snapshot_rollup` marker, so a prospect present at zero grid points scores 100% deficit rather than vanishing (I-076), and an unrolled submarket produces no rows rather than reading as total invisibility. Both are asserted live.
2c. **THE NEXT THING IS NOT A BUILD — IT IS THE FIRST SCAN.** Recommended 2026-08-05, and the reasoning is about accumulated risk rather than about the queue.

**Five components are now built and have never been exercised**: the geogrid client, the collector, the rollup, the placeholder score and the I-004 probe. Every one is verified against fixtures and against Postgres; not one has met a live provider response. Each additional unrun layer raises the chance the first run surfaces several faults at once, interacting, in a batch that has been paid for — and the whole point of the one-submarket ruling is to meet them one at a time.

One submarket × one keyword exercises submission, collection, finalization, the rollup, land masking and the placeholder score in a single ~81-point pass. §11 has the three things it needs, none of which are code. **A sixth unrun layer is worth less than proving the five.**

*The checklist under-reports this state, and the discrepancy is not an error to correct blindly.* Four unticked Phase 2 boxes are code-complete but unrun — geometry parameters are persisted, partitioning and retention are in place, completeness marking exists. They stay unticked deliberately: "built" and "proven" are the two facts §11 exists to keep apart, and the `tasks_ready` box in particular cannot be ticked while the cron it names does not exist.

2d. **Then: organic SERP + AI Overview per submarket × keyword** (checklist §4 Phase 2) — the largest remaining Phase 2 build. `serp_result` already exists, partitioned. The AI half is blocked on `ai_region` names (§7.4, §8.2); the organic half is not. Free to build, paid to run, so it becomes the sixth unexercised component if it is built before the scan.

2e. **Cheap and useful either way: I-070**, enforcing `scan_snapshot` append-only. Listed as a Phase 2 requirement, nothing currently stops an `UPDATE`, and a silently mutated snapshot re-interprets every coverage figure computed against it rather than corrupting anything visibly. A trigger and a test. No closing window.

3. **Suite SPA pages.** Nothing in `frontend/` exists. The read surface they need is built and verified. Open question, see I-072 — decide rather than inherit. **NOT a prerequisite for the scan** — see §11a, which exists because that was asked directly and the file did not answer it.
4. ~~**The coverage rollup** (`ISSUES` I-042)~~ — **DONE.** The retention job now gets past the rollup guard and stops at the next one: `audit_asset` and `slot` do not exist, so a partition whose citations cannot be checked is still never dropped. Verified live (check 15 of `tests/coverage_rollup.sql`). Fail-closed remains the posture; what changed is which guard is doing the refusing.

### 8.2 Blocked on a human
- ~~**DataForSEO credentials on the `outreach` Railway service.**~~ **DONE 2026-08-01** — set as Railway reference variables (`OUTREACH_DATAFORSEO_LOGIN` = `${{PLATFORM.DATAFORSEO_LOGIN}}`, same for the password), so the secrets never left the platform and follow a rotation automatically. **Now wired and exercised for real:** `api/services/dataforseo_client.py` + `verify-reviews`, run live 2026-08-03 against `my_business_info/live` (I-066). The Phase 2 *scan* client is still not built.
- ~~**A public callback URL.**~~ **NO LONGER REQUIRED** — the postback MUST was over-specified and has been corrected to `tasks_ready` collection (PRD §B2, DECISIONS.md). The service stays a cron job: no domain, no receiver, no shape change. What it DOES need is a **second, frequent cron schedule** for the collector — see §7.6.
- **`ai_region` names for LA** (§7.4). A candidate list can be drafted from the 14 submarkets for a human to correct.
- **Two verification spikes.** `I-004` AI prompt granularity — **the instrument is built (#556); the RUN needs a Deploy plus `OUTREACH_CONFIRM_SPEND=probe-ai-granularity`.** `I-003` Outscraper pixel field (~1h) is still unbuilt and decides whether the site-fetch parse is optional or required, which changes the money-signal cost model.
- **Spend approval.** ~$3–6 per market-vertical per cycle, guarded at `max_market_run_cost_cents` 5000 — a gate that is only as honest as §7.1.

### 8.3 Do not
- Change grid radius, spacing or point count. §7.3 is settled by owner ruling and freezes at the first scan. Adding a submarket starts its own clean history; editing one orphans every snapshot it has.
- Derive `grid_result.scan_month` from `now()`. It must come from the snapshot being written, or one snapshot splits across two partitions and the retention job blames the rollup (`ISSUES` I-044).
- Add RLS policies to the CRM tables to silence the advisor's `rls_enabled_no_policy` INFO notices. That is the intended posture (§2).
- Point outreach code at AR-Internal-Tools, or file an outreach migration under `writer/supabase/migrations/`.
- Trigger a paid Outscraper or DataForSEO run without being asked. `OUTREACH_COMMAND` stays `filter` and `OUTREACH_CONFIRM_SPEND` stays empty between approved runs. The gate (§7.2) now refuses rather than trusting this instruction — but it bounds the damage, it does not grant permission.
- Set `review_count_inferred_zero` on further rows, or clear it, without an explicit decision. It is a human judgement about a vendor convention (§9) and the `prospect_preserve_decisions` trigger deliberately makes it non-re-derivable.
- "Fix" a `review_inferred_zero_audit` row by deleting it. That table is the falsification record for §9; a `contradicted` row is the system working.

---

## 8a. Also in §8.3 "do not", now that the collector exists

- **Do not gate `collect` behind `OUTREACH_CONFIRM_SPEND`.** `tasks_ready` and `task_get` are free; only `task_post` bills. Gating the collector would make every cron tick refuse and lose exactly the paid work it exists to save. There is a test asserting `collect` is not in `PAID_COMMANDS` — if it starts failing, read this line before "fixing" it.
- **Do not change the tag format** (`<snapshot_id>:<point_seq>`). It is part of the wire contract now: changing it orphans every task in flight for ~3 days after any submission.
- **Do not widen `cmd_scan` to a market sweep** before a real run has proven the envelope once. Its refusal to scan more than one submarket is the owner's ruling, not a placeholder.

---

## 9. The inferred-zero decision — read before touching review counts

**105 prospects carry `review_count_inferred_zero = true` with `review_count` still NULL.** Applied 2026-08-03 by owner decision (I-067). This is the single most easily misread piece of state in the database, so it gets its own section.

**What it means.** "This provider encodes *no reviews* as null." It is a claim about a **vendor convention**, not a measurement of any business. Nothing was written into `review_count` and nothing ever will be by this decision — a later real count comes only from a real measurement.

**Why it was safe to conclude.** Three independent lines, none of which is an opinion:

- **Mechanical.** A rating is an average of reviews, so zero reviews cannot produce one. All 105 have a null rating *and* a null count — the only internally coherent shape for a zero-review listing. The 7 rows with a rating but no count are NOT flagged: those two facts cannot both be true, so they are provider gaps.
- **Distributional.** `review_count = 0` appears **zero** times across all 1,388 prospects, while 1, 2, 3–5 and 6–9 appear 118 / 70 / 129 / 116 times. A provider that reports down to 1 and never emits 0 is encoding zero as null.
- **Corroborated.** An independent vendor was asked. DataForSEO returned no count for 20 of 20 sampled with no timeouts, and a control group proved the same call resolves down to a **single** review (Maximum Plumbing, `votes_count: 1`). Two vendors decline to report, and the instrument is known to work (I-061, I-066).

**Why it was decided rather than left open.** No source will ever affirmatively report zero — that *is* the convention under test — so waiting for an explicit `0` means waiting forever. An inference held open indefinitely is not caution; it is a decision never made.

> **⚠ CORRECTED 2026-08-25 — this is I-045, already logged and still unbuilt.** The paragraph
> below assumed the geo-grid scan would return `rating.votes_count` and audit the flag
> automatically. **It does not yet.** The scan parser (`maps_scan.GridRow` / `parse_grid_result`)
> keeps only `place_id` and map `rank`, and `grid_result` has no review column — so after four
> completed live scans covering these listings, `review_inferred_zero_audit` is still empty and
> all 105 flags stand un-audited. The audit mechanism below is real and correct; nothing ever
> trips it, because the scan writer does not yet capture the count. **ISSUES I-045** already
> records this as a binding obligation on the scan writer (capture `votes_count` from the item
> that already carries `place_id`, update `prospect.review_count` where null, re-evaluate the
> affected `filter_result` rows) — the four-scan verification just confirms it remains
> unimplemented. The flag is still doing its only load-bearing job (keeping the `review_count_min`
> filter honest); nothing downstream needs
> the 105 audited until Phase 4 scoring reads review counts as a feature.

**How it gets audited — this is the important part.** ~~The geo-grid scan will eventually return `rating.votes_count` for these same listings.~~ (See the correction above — it does not.) That is the first source that *could* contradict the flag, and the moment it does is the moment the contradiction is easiest to lose. So it is caught structurally, not by convention:

- `review_inferred_zero_audit` + the `prospect_audit_inferred_zero` BEFORE UPDATE trigger record any real count landing on a flagged row (`verdict: contradicted | confirmed`), `raise warning` to the server log, and clear the flag so the **measurement wins**.
- The `inferred_zero_requires_null_count` CHECK would otherwise have made that write ERROR — loud, but the wrong loud: it aborts the backfill instead of recording what was learned.
- Trigger ordering is load-bearing. `prospect_audit_inferred_zero` sorts before `prospect_preserve_decisions`, whose preservation branch is guarded on `new.review_count is null` and therefore correctly declines to re-set a flag cleared alongside a real count.

**What to do after the first scan:** `select verdict, count(*) from review_inferred_zero_audit group by 1;` A few `contradicted` rows means the inference was wrong for those listings and they have already self-corrected. A lot of them means the vendor-convention claim is wrong and the flag should be withdrawn wholesale — clear the boolean, never write 0.

**Migrations:** `20260803210000_inferred_zero_audit.sql` (mechanism), `20260803210100_set_inferred_zero_la.sql` (the write, guarded on `count = 105` so it refuses if the set has moved).

---

## 10. Layout

```
outreach/
├── HANDOFF.md                 this file
├── CLAUDE.md                  session protocol + invariants
├── START-HERE.md              build phases, table ownership, config reference
├── DECISIONS.md               settled decisions WITH reasoning — read before proposing changes
├── ISSUES.md                  open problems, corrections, unvalidated assumptions
├── PHASE1B-STATUS.md          the CRM layer: what exists, access model, what is left
├── PHASE3-outcome-constraint.md   the DDL Phase 3 must adopt for outbound-only `outcome`
├── docs/                      the six specs (PRD is Phase 2+; the Phase 1 brief is self-contained)
├── markets/                   one JSON per market-vertical; EXAMPLE-* is the template
├── migrations/                SQL, applied out-of-band via the Supabase MCP — never by the job
├── functions/lead-intake/     Supabase edge function (inbound leads)
├── queries/                   phase1-dod.sql, first-scan-verify.sql (the post-run read, §11b)
├── tests/
│   ├── lead_crm_rls.sql       17-check CRM verification (run in the SQL editor)
│   ├── storage_partitioning.sql  14-check partitioning/retention verification
│   ├── coverage_rollup.sql    18-check rollup + placeholder-score verification
│   └── fixtures/              golden scorecard fixtures — Phase 4, hand-computed, never regenerate
├── Dockerfile · railway.toml  the Railway job image and its restart policy
└── api/
    ├── config.py              every tunable; nothing hardcoded
    ├── db.py                  Supabase client (service role)
    ├── services/              outscraper_client, parser, tiling, filters, suppression,
    │                          cost, paging, seeding, pipeline, geometry, dataforseo_client,
    │                          review_verify, maps_scan, scan_runner, ai_granularity
    ├── scripts/               run_market (the entrypoint), calibrate, calibrate_standalone
    └── tests/                 247 tests, no network or database
```

---

## 11. The scan layer has run — this section is kept for the mechanics, no longer the status

> **UPDATED 2026-08-08.** The three owner-side steps below have all been taken: `tick` is live on a
> 15-minute cron, the collector schedule is that same tick, and the owner ran the first scan through
> the any-city UI. This section is now a record of the mechanics (the deploy/confirm/cron model, the
> collector-cadence trap) rather than a to-do list. The "nothing has been scanned" framing it opens
> with is historical — see the top of the file for live state.

This section exists because the previous version of this file said "Phase 2 scanning has not started" and that sentence covered two very different situations. It now means only one thing, and conflating them would send the next session to write code that already exists.

**What is built:** the geogrid submission and collection path, end to end, with 42 tests (§8.0a). **What has happened (as of 2026-08-08):** the first scan ran — 81/81 points collected, rolled up. The three owner-side steps below are done; they are kept as the mechanics of *how* a scan is triggered, which the any-city onboard path now automates through `tick`.

Three things stood in between, and none of them were code:

1. **A Railway deploy with the scan variables set.** `OUTREACH_COMMAND=scan`, `OUTREACH_CONFIRM_SPEND=scan`, `OUTREACH_ARGS=--submarket '<name>'`. It must be a **fresh Deploy, not a redeploy** — a redeploy replays the previous deployment's config snapshot (§6.1, and the ~$0.11 it cost). Line one of the logs prints the resolved command and the confirm token, so what a run is about to do is visible before it does it.

2. **A SECOND, FREQUENT CRON SCHEDULE for `collect`.** This is the one most likely to be skipped and the most expensive to skip. The ready list holds a task about **three days**; the scan cadence is **fifteen**. A collector on the scan schedule lets every task age off the list between runs, silently converting the normal path into the fallback-by-id path — which still works, which is exactly why nobody would notice, until the day the fallback window (30 days) is also missed. `collect` is free and safe to run on any tick; run it hourly or daily. It is deliberately not spend-gated.

   **This schedule now carries the rollup too** (§8.0b), which raises the cost of skipping it a second time: no collection means no finalized snapshots, which means no completion markers, which means the retention job drops nothing — and the storage ceiling the whole partitioning policy exists to avoid arrives on schedule while every run reports clean. `rollup` standalone clears any backlog, so a missed tick is recoverable; a missing schedule is not noticed.

3. **The owner's go-ahead on spend.** One submarket × one keyword is 81 points, ~1 batch, so a wrong envelope costs one batch rather than a market. `cmd_scan` refuses to do more than that.

### 11a. What is NOT on this path — the UI

Asked directly on 2026-08-05: *"we need to create the UI so we can do the run, correct?"* **No.**
Recorded because §11 lists what is missing and never said what is not, which is what let the
question form.

The run is a **Railway job**. `scan` and `collect` are subcommands of `api.scripts.run_market`,
executed by the service's start command with `OUTREACH_COMMAND`. Posting 81 tasks, collecting
them, rolling them up and scoring them touches no frontend at any point, and the spend gate is
built around the deploy path specifically — `OUTREACH_CONFIRM_SPEND` must match the command name
before any credential is opened.

The UI is for LOOKING at results, and even that is not the only way: `routers/outreach.py` is 14
tested routes over this data, and SQL reaches the rest. Nothing in Phase 2 requires a page.

**A UI that TRIGGERS a scan is not a convenience — it is an architectural change**, and it needs
deciding rather than assuming. The gate that makes paid runs safe (§7.2) assumes a deploy carries
the confirmation; a button would have to either replicate that or bypass it, and "bypass" is how
the ~$0.11 incident happened with a gate that was merely procedural. If a trigger button is
wanted, it gets its own decision.

**What the UI IS blocked on is a choice, not a dependency** — ISSUES I-072. The operator/CRM board
is buildable today against an API that already exists and has never been consumed. The valuable
surfaces (coverage, heatmap, delta) need scan data and the Phase 3 renderer, so building the shell
now means building the interesting half twice. I-072 asks the next session to *choose* between
"operator board now" and "after Phase 3" and to write the answer down, because HANDOFF §1 has
listed Suite UI as "the next build" across several sessions that each built something else.

### 11b. The runbook for the first scan (prepared 2026-08-06)

Nothing here has been executed. This section exists so the three owner-side steps in §11 are a
sequence to follow rather than a thing to reconstruct, and so the run is readable afterwards.

**Live config, read 2026-08-06** — per CLAUDE.md, measured rather than inferred:

| | |
|---|---|
| `source.branch` | `main` ✅ (the 2026-08-03 repoint held — I-065 has not recurred) |
| `rootDirectory` / `railwayConfigFile` | `/outreach` · `outreach/railway.toml` ✅ |
| `startCommand` | carries `${OUTREACH_ARGS:-}` ✅ — flags will reach the command (I-064's fix is still in place) |
| `restartPolicyType` | `NEVER` ✅ |
| **`cronSchedule`** | **absent — there is no schedule of any kind**, confirming §11 item 2 |
| `builder` | reports `RAILPACK`; `railway.toml` says `DOCKERFILE` and is what actually builds. **Known-stale field — do not "fix" it** (§1) |

> **The variable VALUES could not be read from here, and that is a gap in the "read the live
> config" rule rather than an oversight.** `list-variables` returned `valuesRedacted: true` — an
> OAuth-app connection receives variable *names* only. All ten expected names are present
> (`OUTREACH_COMMAND`, `OUTREACH_CONFIRM_SPEND`, `OUTREACH_ARGS`, `OUTREACH_MARKET`, the two
> DataForSEO references, the Supabase pair, Outscraper, OpenAI), but **what `OUTREACH_COMMAND` and
> `OUTREACH_CONFIRM_SPEND` currently hold is unverified.** Check them in the dashboard before
> deploying. The spend gate makes a stale pair fail safe in both directions (§7.2), so this is a
> visibility limit, not an exposure.

**The target: `Van Nuys` × `plumber`.** Chosen for the densest possible read of the response
envelope — 152 prospects and 92 survivors, the most of any LA submarket, so grid results have the
best chance of joining to businesses we already know. That matters beyond sample size: a snapshot
whose grid contains **no** known prospect makes `finalize_snapshot_rollup()` raise, and the marker
can never be written (I-075). Van Nuys is inland San Fernando Valley, so nearly every point should
return a full pack — the happy path, which is what run one is for. `plumber` is the market's
`is_primary` keyword and is what `cmd_scan` defaults to; pass it explicitly anyway, because every
config incident in §6 has been a value someone assumed rather than set.

**Step 1 — set the variables** (owner; do not let a session set these):

```
OUTREACH_COMMAND       = scan
OUTREACH_CONFIRM_SPEND = scan                              ← must equal the command's own name
OUTREACH_ARGS          = --submarket 'Van Nuys' --keyword plumber
OUTREACH_MARKET        = markets/los-angeles-plumbing.json (unchanged)
```

**Step 2 — a fresh Deploy, NOT a redeploy.** A redeploy replays the previous deployment's config
snapshot and would run whatever was set last time (§6.1, and the ~$0.11 it cost). Line one of the
logs prints the resolved command, the confirm token and the commit SHA — read it before reading
anything else. Expect `command=scan PAID confirm=scan`.

Then **immediately set `OUTREACH_COMMAND` back to `filter` and blank `OUTREACH_CONFIRM_SPEND`.**
The gate refuses rather than trusting this, but a manual Deploy while `scan` is still set is the
likeliest remaining way to spend money by accident (§7.2).

~81 tasks in one batch. At config's placeholder rate (`dataforseo_cost_per_request_cents`, 1¢)
that is ~$0.81; **the real figure has to come from the DataForSEO dashboard, because the scan
writes no `cost_ledger` row at all — I-086.**

**Step 3 — the collector's schedule, before walking away.** `OUTREACH_COMMAND=collect` on a
frequent `cronSchedule` (hourly is fine; `0 * * * *`). Free, never spend-gated, safe on any tick,
and it carries the rollup. The ready list holds a task ~3 days against a 15-day scan cadence, so a
collector that runs per scan cycle silently converts the normal path into the fallback-by-id path
— which still works, which is exactly why nobody would notice (§11 item 2).

> A Railway cron service runs its start command **on every deploy as well as on schedule**. With
> `collect` set that is free and idempotent. It is also why the schedule must be set while the
> command is `collect` and not while it is `scan`.

**Step 4 — read the run.** `queries/first-scan-verify.sql`, 14 checks, read-only; every statement
has been executed against the live schema so it parses. Run it after `scan` (checks 1–3) and again
after the first `collect` tick (all of it). Checks 4, 6 and 8 are assertions — a non-empty result
is a defect. The rest print what you want to see beside what you got, because a first run's
expected values are not all knowable in advance.

**Capture the `collect` command's JSON output.** `recovered_by_tag` is a counter in that output
and nowhere else — not a column, not reconstructible afterwards (I-087).

**What run one does NOT prove**, so it is not later assumed to have:

- **The empty-pack path.** Van Nuys is inland; points returning zero businesses are what exercise
  `result_count = 0`, the land-mask counter and the "measured, not found" denominator rule. A
  coastal submarket (Santa Monica, Long Beach, Torrance) is the natural run two.
- **Land masking itself**, which needs 3 consecutive null scans and therefore 3 cycles minimum.
- **The fallback-by-id path**, which only runs when a task ages off `tasks_ready` after ~3 days.
- **Tag recovery**, unless it happens to fire.

---

**After the first real run, the thing to check is not "did it succeed"** — it is whether `scan_task` rows moved `pending → submitted → collected`, whether `actual_points` matches `expected_points`, and whether any row is sitting on `recovered_by_tag`. A run that posts nothing and collects nothing reports clean, because there is nothing to report.

> **Corrected 2026-08-06:** there is no row and no column named `recovered_by_tag` — it is a
> counter printed once in the `collect` command's output (I-087). The rest of this paragraph
> stands, and `queries/first-scan-verify.sql` is the durable form of it.

---

## 12. What is left to build (owner briefing, 2026-08-06)

Written for a non-engineer reading, at the owner's request, after the UI + CRM shipped and the
scan engine went live. `START-HERE.md` §4 is the authoritative phase list with the acceptance
criteria; this section is the plain-English map of what those phases mean and the order they pay
off in. **Where they disagree, START-HERE wins.**

**The core loop is COMPLETE and running:** scan a submarket → rank the businesses by coverage
deficit (the placeholder score) → "Send to CRM" onto the seven-stage board → work the board →
Won leads become AR Tools clients. Everything below makes that loop *more persuasive* or
*smarter*; none of it is a prerequisite for using it.

**The standing recommendation (repeated from §8.1 2c, still true): the highest-value next thing
is NOT a build — it is running the first scan and making the first calls.** Items 2, 4 and 5
below are all tuned by outcomes that do not exist until real prospects have been contacted; the
whole project's stated posture is "treat rank order as a strong prior, not a prediction, until
~100 prospects have been contacted" (CLAUDE.md → What is unvalidated). Building the scoring model
or the email track before there is a single reply is dressing up a guess.

In rough value order:

1. **The audit / heatmap — Phase 3. Renderer, call hook, report, AND `outcome`/`touch`/emit are all
   BUILT.**
   The heatmap renderer (slices 1–2, #580/#589), the **call hook + the two-face competitive report +
   the approval-gated client PDF with signed-URL delivery** (PRs #615–#619), and — new 2026-08-09 —
   **`outcome` + `touch` + the emit webhook** (migration `20260809170000` applied live; PR #625,
   merged) are done. A prospect's invisibility is a picture and a script, and emitting one now writes
   the non-backfillable `outcome` row (and posts a webhook only if one is configured), while logging a
   call writes a `touch` that rolls up into the outcome — the webhook-free capture path. Two of the
   report's three signals (organic, AI) are built but never run. Also still open: the org/AI scan
   cadence, the reporting §5 delivery is on Supabase Storage rather than R2 (DECISIONS 2026-08-08 —
   reversible behind one seam), and the emit webhook is optional + unset (owner does not use
   n8n/Encharge — the touch path is the real capture; wire a URL only if a sender is adopted).
   `reporting-layer-spec.md` is the authority; every renderer is deterministic (identical inputs →
   identical `content_hash`).

2. **The real scoring model — Phase 4. STAGE 1 (priors) BUILT 2026-08-09.** Today the list is still
   ranked "most invisible first" (`v_prospect_placeholder_score`, ISSUES I-082) because the reporting
   reader is not yet repointed (I-108). Phase 4 replaces it with the sabermetric scorecard in
   `docs/scoring-spec.md`: ranked by *who is worth calling* (reply probability × close probability),
   all coefficients config-driven, `score_factors` fully replayable, golden fixtures green (local
   pytest — no CI here), per-channel offsets never pooled (phone 579.3 / email 705.0). **Built:**
   migration `20260809190000` (`score_run`/`prospect_score`/`conflict_check`/`v_prospect_ranked`,
   applied live); the pure engine (`api/services/scorecard.py` + `scorecard_config.py` registry); the
   feature extraction (`score_features.py`, unknown==absent / franchise-flags-not-excludes /
   reachability-excluded-not-defaulted); the score job + `score` command (phone/pass-1, free); the
   golden-fixture harness (`tests/test_scorecard.py`, all 7 independent fixtures green); the
   **empty-safe Stage-2 recalibration** (`recalibrate.py` + `recalibrate` command — fits alpha+gamma
   on real reply outcomes, per-channel, Thompson-guarded; 0 outcomes today = correct "insufficient").
   Verified live: `v_prospect_ranked` pivots reply/close/value and ranks the franchise last, the
   low-coverage non-franchise first. **The coefficients are ELICITED estimates until real replies
   exist** — rank order is a strong prior, not a prediction, until ~100 prospects are contacted.
   **Stages 2–3 (the recalibration FIT, then the hierarchical refit + Thompson sampler) wait on
   accumulated `outcome` rows** — Stage 3 needs a posterior only ~80+ reply outcomes produce.
   **Next Phase-4 steps:** run the free `scan-tech` + paid `scan-organic`/`scan-ai` (min scope) to
   fill the buying-intent/organic/AI signal columns the extraction already reads; repoint the
   platform-api reader to `v_prospect_ranked` (I-108); run `score --market-name "Los Angeles, CA,
   USA"` for the full production ranking (I-105).

3. **The other scan signals — organic + AI are now BUILT (2026-08-08); paid placement is the gap.**
   The Maps geo-grid, the **organic-search** layer (`scan-organic`) and the **AI-answer** layer
   (`scan-ai` — ChatGPT + Google AIO) are all built — they are the report's three signals. What every
   one of them measures is ORGANIC / earned visibility. The one channel none of them capture is
   **paid placement** — see 3a, the owner-requested next build.

3a. **PAID PLACEMENT — is the business (and its competitors) BUYING ads? — OWNER-REQUESTED NEXT BUILD
    (2026-08-08).** The single highest-value lead signal in the model, and currently unmeasured.
    `docs/scoring-spec.md` rates it above every organic signal: **LSA active +57, LSA present + absent
    from the pack +50, Google Ads + no organic/pack +46, est. ad spend >$2k/mo +66** — because a
    business *paying to solve the visibility problem while still losing organically* has proven budget
    AND intent, which is the ideal cold-outreach target. Two slices, cheapest first:
    - **Slice A — paid-placement PRESENCE — BUILT 2026-08-08 (draft PR).** The `scan-organic` capture
      already stores the FULL DataForSEO SERP response in `serp_result.payload`; the parser
      (`organic_scan.parse_organic_serp`) used to discard everything not `organic`/`ai_overview`. It now
      also collects `type=="paid"` (**Google Ads**) and `type∈{local_services,…}` (**LSA / Google
      Guaranteed**) from the SAME response — Google-Ads presence is derived from data already on disk
      with NO new call. `summarize_serp` writes a `paid` block into `payload_summary` (advertisers by
      domain, LSA by name, + `seen_item_types` for measure-don't-infer). The per-prospect facts
      (`outreach_report.derive_paid_signal`, pure) feed a **fourth report signal ("Paid placement")** in
      both report faces + a `paid` talking point in the call hook ("rivals are paying for this search and
      you're not" — the §Buying-intent pitch). Persisted in `payload_summary` keyed to the snapshot (no
      migration — mirrors the organic signal; the per-prospect flag is a read-time domain/name match).
      **LSA item type is unconfirmed against this account's organic response (I-096)** — parsed
      tolerantly + logged on first run; if LSA needs its own endpoint, a gated `scan-lsa` is the additive
      follow-up. Stored + shown, NOT scored until the Phase-4 scorer exists.
    - **Slice B — the MONEY SIGNAL. Designed + B1 BUILT 2026-08-08; B2 gated behind a yield spike.**
      Full design: `docs/paid-placement-slice-b-design-v0_1.md`. Splits into two providers with opposite
      cost profiles: **B1 tech/tag PRESENCE** (Meta pixel, `AW-` conversion tag, GTM container,
      CallRail/Podium/Birdeye) from a **free** direct site fetch (PRD §B3) — **BUILT** (`scan-tech`, NOT
      in PAID_COMMANDS; `services/tech_signals.py` pure + `scan_tech.py` producer + migration
      `20260808200000_prospect_tech_signal` applied live; a failed fetch stores `unknown`, never
      `absent`; GTM container-follow behind `tech_follow_gtm`, off until §16a.1 decides — I-097; now
      auto-runs each `tick` via `run_tech_backlog`, DECISIONS 2026-08-14). **B2
      ad-spend MAGNITUDE** (>$2k/mo bands) from DataForSEO Labs — **PAID and DEFERRED** behind a yield
      spike (Labs paid data is likely sparse for small local advertisers — I-098; Labs endpoints added to
      the free probe set). The **§16a.1 pixel spike** (`probe-pixel-field`, gated) is built to decide
      whether the Outscraper pull supplies the Meta half near-free. Surfaced: a new **"paying and losing"**
      call-hook element (proven budget + a visible problem — the strongest pitch) + the prospect's own ad
      tech in the report, both folded ADDITIVELY into the paid signal (Slice A semantics unchanged).
    Both are Phase-4 scoring inputs; until the scorer exists they are stored + shown, not scored. Same
    invariants as the three signals it joins: deterministic + fact-grounded (never assert an ad that is
    not in the response), paid runs gated, tests, DECISIONS/ISSUES entries.

4. **Email outreach + enrichment — Phase 5.** The whole design is phone-first; Phase 5 opens
   email as a second channel (find addresses, ESP integration, suppression sync). Its long pole
   is **not code**: a sending domain needs 3–4 weeks of warming that cannot be compressed, and
   the vendor is undecided (GetResponse likely disqualified — I-001). If email is ever wanted,
   that calendar clock should start early, independent of everything else.

5. **The learning loop — Phase 6.** Once ~30–50 outcomes exist, a recalibration job looks at who
   actually replied and re-tunes the model; evidence randomization and `sequence_version` /
   `template_version` stamping must be in place from Phase 3 or the early data is lost. Months
   out; pays off only after real outreach.

**Also outstanding, small and independent of the above:** I-070 (enforce `scan_snapshot`
append-only — a trigger + a test; cheap, do it after the first scan proves the finalize UPDATE),
I-086/I-087 (the geogrid cost_ledger row now EXISTS via the tick build, but the budget-ceiling
check on the scan path and a durable `recovered_by_tag` are still worth revisiting). (The
`ai_region` naming is DONE — 11 LA regions seeded from I-073; and the two scan-signal builds it used
to block, organic + AI, are merged.)

**3a — paid placement — is DONE and MERGED (PR #621, `b4ca6da`).** Slice A (presence) + Slice B1
(site tech) shipped; Slice B2 (spend magnitude) is deliberately deferred behind the Labs yield spike
(I-098). See the top-of-file bullet, and read I-099 before touching that code.

---

## `outcome` + `touch` + THE EMIT WEBHOOK — BUILT + MERGED (2026-08-09, PR #625 → `8141629`)

**This section's build is DONE and MERGED to `main`.** Migration `20260809170000_outcome_touch.sql`
(applied live to Outreacher): `touch` (authoritative for "a contact attempt happened", anchored on
lead, bigint identity), `outcome` (adopted verbatim from `PHASE3-outcome-constraint.md` —
outbound-only made structural via the composite FK), and `lead_activity.touch_id`'s foreign key (0
orphans verified). Verified live by `tests/outcome_touch_constraints.sql` (12 checks, all correct).
platform-api gained `services/outreach_emit.py` (pure) +
`emit_prospect`/`record_touch`/`get_outcome`/`list_touches` in `services/outreach.py` + four routes;
the SPA gained an Emit button (CoverageTable) and a Log-contact section + outcome summary
(LeadDrawer). Tests: platform-api outreach suite 75 passing; outreach api 411 passing (unchanged).
`selection_reason` is recorded on 100% of contacts (allowlist `{thompson, random_control, manual}`;
ISSUES I-102).

**What the emit does:** writes the lead (idempotent) + the `outcome` row (the non-backfillable
substrate) and — only if a webhook is configured — posts an audit-ready QUEUE to it. It never
triggers asset generation (the approval gate stays the only path to an asset), and it does not spend
(a webhook POST is not a paid provider call).

**The emit webhook is a GENERIC, OPTIONAL integration — owner does NOT use n8n/Encharge** (owner
clarification 2026-08-09; DECISIONS same date). Those two are only the PRD's *examples* of a
downstream sender; nothing depends on them. `outreach_emit_webhook_url` POSTs plain JSON to any HTTP
receiver (Zapier / Make / a custom endpoint) — or stays empty, which it is on PLATFORM. **The primary
capture path is webhook-free:** logging a call (the `touch` path) creates/rolls up the `outcome`, so
the substrate fills from call one for a manual phone workflow with no external sender at all. Wire a
URL only if/when the team adopts an automated sender; until then emit records the outcome and reports
`delivered:false, reason:webhook_not_configured`, which is the intended, harmless state.

**The teed-up 2026-08-06 question is RESOLVED** (DECISIONS 2026-08-09): an outcome is created by
whichever of emit / first-touch comes first (both idempotent); there is NO bulk backfill of
pre-existing hand-picked leads — a hand-picked lead becomes modellable when it is CONTACTED (a
touch), not when it is promoted, because recording an outcome for a prospect nobody called would
inject a fabricated contact event into the substrate.

**Deferred (ISSUES I-101):** the PRD §183/§198 emit cadence + evidence-age gates belong to the
Phase-4 selector; v1 emit requires only a rolled-up scan (bootstrap-gated).

---

## (historical) THE NEXT BUILD IS `outcome` + `touch` + THE EMIT WEBHOOK — and it is the only item with a deadline

**Superseded by the section above — this build is done.** Kept for the reasoning that drove it.

Everything else on this list can wait without cost. This one cannot, and the reason is not effort:

**`outcome` cannot be backfilled.** `scoring-spec.md` §8 is explicit — *"`outcome` MUST be written
from campaign one even though nothing reads it for months. Retrofitting it means the first hundred
data points are lost permanently."* Every call placed before the table exists is a prospect who was
contacted, may have replied, and whose result the Phase-4 model will never be able to fit against.

**This contradicts the standing recommendation, deliberately surfaced rather than left to be
discovered.** §12 has said for several sessions that the highest-value next thing is *making the
first calls* off the invisible businesses the first scan surfaced. Both statements are in this file
and they pull against each other: calling now generates revenue and destroys modelling data at the
same time. Somebody has to decide which, and the cheap resolution is to build `outcome` FIRST — the
DDL is already worked out in `PHASE3-outcome-constraint.md`, verified live against the real key with
a throwaway probe table, and it is a small build.

What it is:
- **`outcome`** — the modelling substrate, OUTBOUND-ONLY, keyed on `lead (prospect_id, source)` so
  the rule is structural rather than a trigger convention (a promoted INBOUND lead also carries a
  `prospect_id`, which is why keying on prospect alone cannot express it). Full DDL in
  `PHASE3-outcome-constraint.md`.
- **`touch`** — authoritative for "a contact attempt happened". `lead_activity` carries commentary
  only and must not be used for this (CLAUDE.md invariant).
- **the emit webhook** — writes `lead` rows with `source='outbound_scan'` and an `outcome` per
  emitted prospect (PRD §C Emit: an audit-ready QUEUE, never generated assets; asset generation
  stays behind the approval gate that already exists).
- **`selection_reason`** on every contact from day one (`thompson` | `random_control`,
  scoring-spec §7) — same closing-window argument as `outcome` itself.

One decision is already teed up and NOT yet made (DECISIONS 2026-08-06, hand-picked leads): whether
the emit path also backfills outcomes for the hand-picked `outbound_scan` leads that already exist,
or the model simply does not see them until they are re-emitted. Decide it when the emit machinery
gives it a concrete shape.

---

**FOUR producers are built and have NEVER RUN** — `scan-organic` (PAID), `scan-ai` (PAID),
`probe-pixel-field` (PAID), `scan-tech` (free). §8.1 2c argued once that each additional unrun layer
raises the chance the first run surfaces several faults at once, interacting, in a batch that has
been paid for. Two more layers have been added since. **Prefer running a built layer over building a
fifth**, and note the report's organic / AI / paid sections all read `not_scanned` until those runs
happen.

**Not on the list, because it is done:** ingest + filter (Phase 1), the lead CRM board and
one-click promote (Phase 1b, #574), the scan producer/consumer/rollup/placeholder-score, the
UI that triggers scans (#571), the **any-city onboard** path (#601/#603/#606/#611 — discover→filter→scan
any Google city by consumer search), the **Phase 3 heatmap renderers** (#580/#589), and — as of
2026-08-08 — **the first live scan itself** (emergency plumber × whole-city LA: 122 discovered / 83
survived / 81 collected / rolled up / 119 coverage rows), the **per-prospect report** (call hook + 3
signals + approval-gated client PDF, #615–#619), and the **paid-placement 4th signal** (#621). The
scan engine (`tick`) is live on a 15-minute cron since 2026-08-07 00:13 UTC and has now drained a
real onboard order end-to-end.

**The standing recommendation is now CONDITIONAL, and this supersedes the older phrasing.** It used
to read "the highest-value next thing is not a build — it is making the first calls, then Phase 3's
audit/heatmap PDF". Two things changed: the audit/heatmap PDF is **built** (#580/#589/#615–#619), and
`outcome` still does not exist.

So the sharpened version: **making the first calls is still the highest-value ACT — but every call
placed before `outcome` exists is a data point the model can never recover.** The two are not in
conflict for long, because `outcome` is a small build with its DDL already written. The cheap
sequence is: build `outcome` + `touch` + emit (above) → then call, with results landing in the
substrate from call one. Calling first is defensible; doing it *without noticing the trade* is not.
If you choose to call first, write down that the first N outcomes are lost, so the Phase-4 refit is
not later fitted against a set nobody knows is truncated.
