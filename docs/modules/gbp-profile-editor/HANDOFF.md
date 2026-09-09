# GBP Profile Editor — build handoff (module-scoped)

> Operational state + build plan for the **GBP Profile Editor** module. The spec
> is `docs/modules/gbp-profile-editor-prd-v1_0.md`; the build orientation +
> reuse map is the sibling `CLAUDE.md`; the root `/HANDOFF.md` remains the suite
> handoff. This file is the "start here to build it" doc.

## Status (2026-09-04; scope expanded 2026-09-09; Phases 3a + 3b built 2026-09-09)

- **✅ PHASE 3b COMPLETE (2026-09-09) — categories + attributes, shipped dark.**
  `categories` (#1044, migration `20260909130000`) rides `locations.patch` like a
  Tier-A field + a live catalog SEARCH (`GET …/categories/search?q=`), extra-confirm
  on a PRIMARY-category change; it gives the `gbp_audit.category_gaps` finding a
  lever (the strategist loop's generic `stage_strategist_draft`, zero new wiring).
  **`attributes`** (this PR, migration `20260909140000_gbp_profile_attributes.sql`,
  **applied live** — relaxes the `field` CHECK; attributes REUSE the
  `gbp_profile_apply`/`gbp_profile_sync` job types, no new async_jobs type) is the
  one field that does NOT ride `locations.patch`: the **separate**
  `getAttributes`/`updateAttributes` endpoint pair + category-scoped `attributes.list`
  availability (`GET …/attributes/available`), value-typed values
  (BOOL/ENUM/URL/REPEATED_ENUM), a per-attribute `updateMask`, and a subset-edit model
  (the mask names only the changed attributes; a cleared attribute stays in the mask
  with an empty value). The service layer branches read/write for attributes
  (`_run_apply_attributes`/`_run_sync_attributes`, best-effort attributes read in
  `read_current` → `attributes_error` never breaks the page), keeping the generic
  single-`updateMask` path byte-identical for every other field. Pure
  `build_attributes_patch`/`parse_attributes`/`parse_attribute_metadata`/`attributes_diff`
  (whole-set drift, Q3)/`attributes_subset_applied` (per-proposed outcome). New
  `AttributesCard` (lazy availability + per-type control) + `ErrorDetails` codes. 16
  new unit tests (117 total pass); full platform-api suite green; frontend `tsc -b` +
  `vite build` clean. Still gated off. **The v1 attributes write shape (the
  `updateMask` = comma-joined `attributes/{id}`) is the one to re-verify live** at
  activation — a wrong shape surfaces as a `rejected` edit, never a silent bad write.
- **✅ PHASE 3a BUILT (2026-09-09) — six Tier-A fields shipped dark.** `website`,
  `labels`, `special_hours`, `more_hours`, `service_area`, `open_info` now ride the
  existing `gbp_profile_edits` machinery. Migration
  `20260909120000_gbp_profile_fields_phase3a.sql` (**applied live** — widens the
  `field` CHECK). Pure `build_*_patch`/`parse_*` in `gbp_profile_api.py` +
  `parse_more_hours_types`; the service's three switch points + `READ_MASK` +
  `read_current` extend to all six; two new read endpoints — `GET
  …/gbp/profile/more-hours-types` (type picker, reuses the batchGet) and `POST
  …/gbp/profile/resolve-places` (service-area place→placeId via `maps_geocode`); six
  new `GbpProfile.tsx` cards with the extra-confirm gate on `service_area` +
  `open_info=CLOSED_*`. New `ErrorDetails` codes. 17 new unit tests (95 total pass).
  Still gated off (`gbp_profile_enabled`). **`service_area`'s v1 write shape
  (placeInfos require placeId; regionCode) is the one to re-verify live** at Phase-3a
  activation — a wrong shape surfaces as a `rejected` edit, never a silent bad write.
- **📌 SCOPE EXPANDED (owner, 2026-09-09) — PRD bumped to v1.1, spec-first.** The
  editable-field surface grew from three fields to the full set **except the NAP
  triplet** (name/address/phone — held, ADR 0005). Media (v4 API) is in; NAP is
  out. Spec is updated (PRD v1.1 amendments block, `decisions.md`, ADR 0005). **3a
  is built (above); 3b (categories/attributes) + 3c (media) are NOT yet built** —
  see the Build plan below.
- **✅ BUILT + MERGED (Phases 0–2), shipped dark.** PR
  [#1011](https://github.com/kssabraw/ar-tools/pull/1011) (`feat(gbp): GBP
  Profile Editor module (description / services / hours)`) — squash-merged to
  `main` as `07e1038`. CI green (platform-api tests + lint/typecheck + Netlify
  preview). Migration `20260904120000_gbp_profile_edits.sql` **applied live**.
  The module is inert until both `gbp_api_enabled` and `gbp_profile_enabled` are
  on (both default False), so `main` ships it dark.
- **PRD: Approved for build** (owner). Twelve grilling decisions folded in;
  recorded in the root `decisions.md` and ADR 0004.
- **Sibling upgrade SHIPPED + MERGED:** the `gbp_audit` description-quality
  follow-up (**PR #1009**, on `main`) — the loop's real description trigger.
- **What shipped (Phases 0–2), gated off:**
  - **Phase 0:** `gbp_profile_enabled` + the `gbp_profile_*` config; the verify
    script extended with a `--edit-test` (v1 `locations.get` read + a **no-op**
    `profile.description` patch round-trip that proves the write path with zero
    visible change — point it at the agency's own listing).
  - **Phase 1:** migration `20260904120000_gbp_profile_edits.sql` (**applied
    live** — table + the 3 job types on the rebuilt `async_jobs` CHECK);
    `services/gbp_profile_api.py` (pure builders/validators + v1 get/patch),
    `services/gbp_profile_service.py` (read-current, apply job with
    re-read-and-diff, the self-continuing `gbp_profile_sync` reconciler),
    `routers/gbp_profile.py`, `models/gbp_profile.py`, worker dispatch, freeze
    gates (`gbp_profile_apply` + `gbp_profile_sync`), the per-cycle reconciler
    sweep on the shared scheduler, `pages/GbpProfile.tsx` + workspace card +
    `ErrorDetails` codes. The connection/listing picker was extracted to the
    shared `components/gbp/GbpConnection.tsx` (GBP Posts now reuses it too).
  - **Phase 2:** the `gbp_profile_draft` job (description + services drafted;
    hours never invented); the `update_gbp_profile` SerMaStr action (stages a
    draft, never applies); the Action-Plan producer deep-link (`build_gbp_action`
    retargets the `gbp_gap` CTA to the editor when the gap is a thin/missing
    description or missing hours and the module is enabled).
  - Tests: `tests/test_gbp_profile.py` (pure builders + apply/reconciler/draft
    flow). Full platform-api suite green locally (dep-limited sandbox aside).
- **STILL TO DO before flipping on (owner/Railway):** run
  `verify_gbp_api_access.py --edit-test locations/<agency>` from the PLATFORM
  shell to prove the write path + re-verify the v1 field paths (see Gotchas),
  then set `GBP_PROFILE_ENABLED=true` (+ confirm `GBP_API_ENABLED=true`).
- **Flags:** both `gbp_api_enabled` and `gbp_profile_enabled` default False, so
  nothing is user-visible until both are on.

## Next action — owner/Railway activation (the build is done)

The whole module is merged and dark. The remaining step is operational and can't
be done from the Claude Code sandbox (`developers.google.com` is egress-blocked):

1. From the **Railway PLATFORM shell**, re-verify the v1 field paths (see
   Gotchas) and run `python scripts/verify_gbp_api_access.py --edit-test
   locations/<agency>` against the **agency's own** listing — Phase 0 is a gate,
   prove the write path there before any client listing (decision Q9d). Green =
   auth + edit-right + field paths confirmed.
2. Set `GBP_PROFILE_ENABLED=true` on PLATFORM (confirm `GBP_API_ENABLED=true`).
   Both default False, so a fresh env still ships dark.
3. Pilot on one client: draft → apply → confirm live on all three fields.

## Build plan (phases — full detail in PRD §4) — ✅ Phases 0–2 BUILT + MERGED (#1011)

1. **Phase 0 — read+write proof.** Extend `scripts/verify_gbp_api_access.py` with a
   `locations.get(readMask=…)` and an `--edit-test` `locations.patch` round-trip on
   the agency listing. Add the `gbp_profile_enabled` config flag. Exit: write path
   proven on the agency listing.
2. **Phase 1 — core.** `gbp_profile_api.py` (pure builders/validators +
   get/patch), `gbp_profile_service.py`, `routers/gbp_profile.py`,
   `models/gbp_profile.py`, migration (`gbp_profile_edits` + the three job types),
   `pages/GbpProfile.tsx` + workspace card. Per-location picker; manual editors for
   all three fields (description w/ 750 counter + advisory linter; structured
   weekly hours; free-form services w/ operator category pick). Apply job with
   **re-read-and-diff** + the `gbp_profile_sync` reconciler. Freeze-gate
   `gbp_profile_apply` + `gbp_profile_sync`. History view.
3. **Phase 2 — AI drafting + strategist loop.** `gbp_profile_draft` job (per
   field; hours never invented). Services grounding = `clients.gbp` categories +
   silo plans. AI suggests a category per drafted service; operator confirms.
   Wire BOTH the `update_gbp_profile` SerMaStr action (stages a draft) and the
   Action-Plan producer (board task deep-linking into the pre-seeded editor).
4. **Phase 3 — field-scope expansion (owner, 2026-09-09; PRD v1.1).** The editable
   surface grew to the full set **except the NAP triplet** (title/address/phone —
   held, ADR 0005). Build order:
   - **3a — Tier A, same `locations.patch` — ✅ BUILT 2026-09-09.** `website`,
     `labels`, `special_hours`, `more_hours`, `service_area`, `open_info`. Each is a
     pure `build_*_patch` + validator + parser + a field card, riding the *existing*
     `gbp_profile_edits` row / apply job (re-read-and-diff) / reconciler / freeze
     gate / history unchanged. `more_hours` types come from the same batchGet as the
     services picker (`parse_more_hours_types` + `GET …/more-hours-types`);
     `service_area` places are resolved to Google placeIds via `maps_geocode`
     (`POST …/resolve-places`). Extra-confirm gate on `service_area` + any
     `open_info=CLOSED_*`; the AI never drafts hours/closures (unchanged). Note:
     `special_hours` ships as its OWN field (masks only `specialHours`), separate
     from the `hours` field (which masks only `regularHours` in practice) — no
     dual-write.
   - **3b — Tier B, category-gated. ✅ COMPLETE 2026-09-09 — `categories` (#1044) +
     `attributes` (this PR), both shipped dark.**
     - **`categories`** rides `locations.patch` like a Tier-A field
       (`updateMask=categories`), but the editor needs a live catalog SEARCH
       (`categories.list` → `GET …/categories/search?q=`) to pick valid gcids, and a
       PRIMARY-category change is gated behind an extra confirm (it shifts ranking).
       **Consumes the existing `gbp_audit.category_gaps` finding for free** —
       categories is now a valid `field`, so the strategist loop's generic
       `stage_strategist_draft` can stage a categories draft with zero new wiring.
       Pure `build_categories_patch`/`parse_categories_value`/`parse_category_search`
       + `search_categories`; the field's value rides under `categories_value` (the
       flat `categories` key stays the services picker list). Migration
       `20260909130000` (applied live). Card + `primary_category_required` /
       `invalid_category` codes.
     - **`attributes`** ✅ BUILT (this PR, migration `20260909140000`, applied live) —
       the one field that does NOT ride `locations.patch`: the **separate endpoint
       pair** `getAttributes`/`updateAttributes` (a per-attribute `updateMask` =
       comma-joined `attributes/{id}` resource names, an `Attributes` resource keyed at
       `locations/{id}/attributes`), a distinct read path (best-effort in
       `read_current` → `attributes_error`, not on the Location readMask),
       category-scoped availability (`attributes.list` → `GET …/attributes/available`)
       + value-typed values (BOOL/ENUM/URL/REPEATED_ENUM). The service layer branches
       read/write (`_run_apply_attributes`/`_run_sync_attributes`, `_is_attributes`) so
       the generic single-`updateMask` path stays byte-identical for every other field;
       an edit targets the changed **subset** (mask names only those; a cleared
       attribute stays in the mask with an empty value). Attributes REUSE the
       `gbp_profile_apply`/`gbp_profile_sync` job types (no new async_jobs type). Pure
       `build_attributes_patch`/`parse_attributes`/`parse_attribute_metadata`/`attributes_diff`
       (whole-set drift, Q3)/`attributes_subset_applied` (per-proposed outcome). Card +
       `invalid_attribute`/`invalid_attribute_url`/`invalid_attribute_value_type`/
       `attribute_id_required`/`no_attributes` codes. **The v1 `updateMask` shape is the
       one to re-verify live at activation** — a wrong shape → a `rejected` edit, never a
       silent bad write.
   - **3c — Tier C, media (v4 API):** photos/logo/cover via `accounts.locations.media`
     — **mirror GBP Posts (v4/httpx + the image upload/reuse path), NOT the v1
     discovery client**; it's a create/list/delete op, so give it its own storage,
     don't force it into `gbp_profile_edits`. Verify the media access grant on
     PLATFORM (distinct from the Business Information grant).
   - Still deferred: structured services + AI-assigned categories; a real
     `service_gap` `gbp_audit` check (rides this module's live-services read);
     scheduled periodic drift detection; a Client Report line + a strategy-digest
     `gbp_profile` provider.
   - **`gbp_profile_edits.field` widens** (add `website|labels|special_hours|
     more_hours|service_area|open_info|categories|attributes`). **Needs a
     migration** — the live column has `check (field in
     ('description','hours','services'))` (`20260904120000_gbp_profile_edits.sql:25`,
     verified 2026-09-09), so 3a/3b drop/rebuild that CHECK. `media` is NOT a
     `field` value. New `ErrorDetails` codes per PRD §8 + the v1.1 block.
   - **NAP is out** (ADR 0005). Do not add `title`/`storefrontAddress`/
     `phoneNumbers` to any `updateMask`.

## Gotchas (each one has cost real time in this repo)

- **Field paths need a build-time re-verify.** `developers.google.com` /
  `googleapis.dev` are egress-blocked from the Claude Code sandbox but reachable
  from the **Railway PLATFORM shell**. Re-check `profile.description`,
  `regularHours`/`TimeOfDay` (v1 uses structured `{hours, minutes}` objects, NOT
  v4 `"HHMM"` strings), `serviceItems`/`freeFormServiceItem`, and the
  `LocationState`/`metadata` pending-edit + `canModifyServiceList` fields against
  `developers.google.com/my-business/reference/businessinformation/rest/v1/accounts.locations`.
- **Two `_build` helpers.** Use `gbp_locations_service._build("mybusinessbusinessinformation", creds)`
  (hardcodes v1) — NOT `gbp_performance_service._build(...)`.
- **`async_jobs.job_type` CHECK is wider live than any repo migration.** Rebuild it
  from the LIVE constraint + the three new types; follow
  `20260902180000_guide_sync.sql`.
- **Pydantic strips undeclared response keys silently** (repo #844 lesson). Declare
  every field the frontend reads on `models/gbp_profile.py`. (Already bit
  `MapsGbpAuditResponse` in #1009 — fixed there.)
- **Edit rights ≠ read rights.** The connected account can *list* a listing it
  can't fully *edit* (or it's unverified). Read `LocationState`/`metadata`
  (`isVerified`, `canModifyServiceList`) before offering an edit; classify the
  patch's own 403/400 into `gbp_listing_read_only`/`cannot_modify_services`.
- **The 30-min stale-job reaper forbids a sleep-poll** — the reconciler must be
  self-continuing (do one `get`, enqueue the next check with a future
  `scheduled_at`), the `leadoff_geocode` pattern.
- **Deploys redeploy all three Railway services** (no per-service `watchPatterns`),
  and the private `nlp` service has no healthcheck — irrelevant here (this module
  is platform-api only) but worth knowing if a live run is in flight.

## Config to add (`config.py`)

- `gbp_profile_enabled` (False) — gates the module on top of `gbp_api_enabled`.
- `gbp_profile_draft_model` (`claude-sonnet-4-6`), `gbp_profile_draft_max_tokens`.
- `gbp_profile_description_max_chars` (750).
- `gbp_profile_sync_delay_seconds` (immediate post-apply re-read delay).
- `gbp_profile_sync_backoff` (the +2m/+30m/+2h/+12h/+24h reconciler ladder).

## Activation (when built)

1. Merge the build PR; run the migration (apply live via the Supabase MCP if
   working web-only).
2. From the Railway PLATFORM shell, re-verify the v1 field paths and run
   `verify_gbp_api_access.py --edit-test` against the **agency's own** listing.
3. Set `GBP_PROFILE_ENABLED=true` (and confirm `GBP_API_ENABLED=true`) on the
   PLATFORM service. Both default False, so a fresh env still ships dark.
4. Pilot on one client: draft → apply → confirm live on all three fields.

## Definition of done (v1)

- A client's description, services, and hours edited end-to-end through the app
  (draft → apply → confirmed live) with zero dashboard work.
- Every read-only-listing / pending-review / rejection / out-of-band-drift is
  surfaced with an actionable `ErrorDetails` code — never a green state that isn't
  true.
- No auto-apply anywhere; the strategist action + producer only stage drafts.
