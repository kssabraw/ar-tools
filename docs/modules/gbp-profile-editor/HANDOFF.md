# GBP Profile Editor — build handoff (module-scoped)

> Operational state + build plan for the **GBP Profile Editor** module. The spec
> is `docs/modules/gbp-profile-editor-prd-v1_0.md`; the build orientation +
> reuse map is the sibling `CLAUDE.md`; the root `/HANDOFF.md` remains the suite
> handoff. This file is the "start here to build it" doc.

## Status (2026-09-04)

- **PRD: Approved for build** (owner). Twelve grilling decisions folded in;
  recorded in the root `decisions.md` and ADR 0004.
- **Sibling upgrade SHIPPED + MERGED:** the `gbp_audit` description-quality
  follow-up (**PR #1009**, on `main`) — the loop's real description trigger.
- **BUILT (Phases 0–2), gated off.** On the build branch
  `claude/gbp-profile-editor-build-hi2lpo`:
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

## Before you start (branch + prerequisites)

- **Merge #1009 and #1008 first** (or branch off them). #1009 gives you
  `gbp_audit.description_quality` (the loop trigger). #1008 carries this doc set +
  the approved PRD. A fresh build branch off `main` after both merge is cleanest.
- Develop on the branch your session was assigned; open a **draft PR** and let it
  ride the drive-to-green PR watch.
- **Phase 0 is a gate:** prove the write path on the **agency's own** GBP listing
  (not a client's) before touching any client listing (decision Q9d).

## Build plan (phases — full detail in PRD §4)

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
4. **Phase 3 — deferred.** Structured services; a real `service_gap` `gbp_audit`
   check (rides this module's live-services read); categories/attributes editing;
   scheduled periodic drift detection; a Client Report line + a strategy-digest
   `gbp_profile` provider.

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
