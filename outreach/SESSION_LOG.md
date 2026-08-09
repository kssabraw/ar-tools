# SESSION_LOG — Phase 3: outcome + touch + emit webhook

Append-only. One line per task started, commit made, dependency added, test run. UTC timestamps.

- 2026-08-09T16:06Z — session start. Restarted branch `claude/paid-placement-signal-1iqmd4` from origin/main (3740ad6). Read CLAUDE.md, HANDOFF §1/§12, DECISIONS, ISSUES, PHASE3-outcome-constraint.md, scoring-spec §7/§8/§10, PRD §C.
- 2026-08-09T16:06Z — baselines confirmed green: outreach `api/tests` 411 passed; platform-api `test_outreach_report.py` + `test_outreach_justification.py` 58 passed. Installed into sandbox system python: pydantic, httpx, pydantic-settings, pytest (test deps only; not added to any requirements).
- 2026-08-09T16:06Z — live DB probe (Outreacher fkwhgvcggvsricuinuqy): outcome/touch absent, lead_activity.touch_id bigint w/ no FK, 0 orphan touch_ids, lead(prospect_id,source) UNIQUE + 6-value source check present. `_phase3_probe` table referenced by PHASE3-outcome-constraint.md §3 does not exist anywhere → doc instruction stale (logged I-100).
- 2026-08-09T16:20Z — TASK migration: wrote migrations/20260809170000_outcome_touch.sql (touch + outcome + lead_activity.touch_id FK). Applied LIVE to Outreacher via Supabase MCP (success). Verified schema: composite FK, outbound check, touch FK, RLS on both, 0 anon/authenticated grants.
- 2026-08-09T16:20Z — wrote tests/outcome_touch_constraints.sql (12 checks). Ran LIVE against Outreacher: all 12 (correct); 0 leftover fixtures, outcome/touch empty, 1 real lead preserved.
- 2026-08-09T16:20Z — logged I-100 (stale _phase3_probe doc ref), I-101 (emit cadence/age gates deferred to Phase 4), I-102 (selection_reason 'manual' value). DECISIONS: outcome/touch DDL adopted verbatim + anchoring + app-owned rollup; teed-up hand-picked backfill question RESOLVED (create-on-first-contact, no bulk backfill); emit webhook design.
- 2026-08-09T16:45Z — TASK backend: added platform-api services/outreach_emit.py (pure: selection_reason/channel validation, outcome+touch row builders, touch rollup, emit payload, webhook headers) + emit_prospect/record_touch/_ensure_outcome/_post_emit_webhook/get_outcome/list_touches in services/outreach.py + 6 config knobs + 4 routes (POST emit, POST/GET touches, GET outcome) in routers/outreach.py.
- 2026-08-09T16:45Z — wrote tests/test_outreach_emit.py (17 cases). Ran platform-api: test_outreach_emit + test_outreach_report + test_outreach_justification = 75 passed. py_compile OK on outreach.py/outreach_emit.py/routers/outreach.py/config.py. config loads new settings.
- 2026-08-09T17:05Z — TASK frontend: added Emit button (per prospect) to CoverageTable in Outreach.tsx (writes outcome + posts webhook; shows delivered / outcome-saved / not-configured states); added "Log contact" section (channel + disposition + note → touch) + outcome summary (contact count / first contacted / replied) to LeadDrawer in OutreachLeads.tsx. Ran `npm install` + `npm run build` — tsc + vite clean (pre-existing chunk-size warning only).
- 2026-08-09T17:20Z — TASK docs: updated CLAUDE.md (unbuilt list + closing-window section → BUILT), HANDOFF.md (§12 item 1, new "outcome + touch + emit BUILT" section superseding the "NEXT BUILD" one), PHASE3-outcome-constraint.md §3 (stale _phase3_probe note resolved). No PR template in repo.
- 2026-08-09T17:30Z — pushed branch (force-with-lease: remote held only pre-squash 2ab1210 = already-merged PR #623, per HANDOFF §6.12). Opened DRAFT PR #625. PR status: only a Netlify deploy-preview (informational; no test CI in this repo). Final test run: outreach 411 passed, platform-api outreach 75 passed.

## Session Summary (2026-08-09)

**Objective:** Finish Phase 3 — `outcome` + `touch` + the emit webhook + `selection_reason`. DONE.

**Tasks completed (4 commits):**
1. 9c69a8a — migration 20260809170000_outcome_touch.sql (touch + outcome + lead_activity.touch_id FK), applied live; tests/outcome_touch_constraints.sql (12 checks, live-verified).
2. 0609a54 — platform-api emit + touch: services/outreach_emit.py (pure), emit_prospect/record_touch/etc in services/outreach.py, 4 routes, 6 config knobs, test_outreach_emit.py (17 cases).
3. efdf0e7 — frontend: Emit button (CoverageTable) + Log-contact/outcome UI (LeadDrawer).
4. d5f2c82 — docs: CLAUDE.md / HANDOFF.md / PHASE3-outcome-constraint.md marked built.

**Tasks blocked:** none.

**Decisions logged (DECISIONS.md):** outcome/touch DDL adopted verbatim + touch anchored on lead + app-owned rollup; teed-up hand-picked-backfill question RESOLVED (create-on-first-contact, no bulk backfill); emit webhook design (best-effort POST, audit queue, never triggers assets).

**Issues logged (ISSUES.md):** I-100 (stale _phase3_probe doc ref), I-101 (emit cadence/age gates deferred to Phase 4), I-102 (selection_reason 'manual' pre-Phase-4 value).

**Dependencies added:** none to any requirements file. (Sandbox-only test deps installed into system python: pydantic, httpx, pydantic-settings, pytest.)

**Test status:** outreach api 411 passed; platform-api outreach suite 75 passed; frontend npm run build clean; live SQL 12/12 correct.

**Look at first:** the emit webhook URL is UNSET on PLATFORM (outreach_emit_webhook_url) — emit records the outcome but reports delivered:false until the n8n/Encharge URL (+ optional token) is set. The touch path is webhook-independent, so outcomes capture from call one regardless. No paid run was triggered.
- 2026-08-09T17:45Z — owner feedback: "not using n8n, don't know Encharge" (PRD's example downstream senders). Reframed the emit webhook as a generic optional integration (config comment + Emit button tooltip) and logged DECISIONS entry; no behaviour change (code was always a generic JSON POST to any URL / none). Primary capture is the webhook-free touch path. Frontend build clean.
- 2026-08-09T18:00Z — owner: mark ready + merge #625, then update HANDOFF/CLAUDE. Marked PR #625 ready, squash-merged to main (8141629). Restarted branch from merged main. Post-merge docs: HANDOFF (top status bullet + §12 item 1 + dedicated section → MERGED #625; emit webhook reframed generic/optional, touch is primary capture) + CLAUDE.md (same). Opening a fresh draft PR for the docs (follow-up to a merged PR is a new PR).

## SESSION_LOG — Phase 4 Stage 1: the scoring model (priors)

- 2026-08-09T18:00Z — session start. Restarted branch `claude/outreach-scoring-phase-4-q7nyay` from origin/main (f49cfd8). Read CLAUDE.md, HANDOFF §1/§12, DECISIONS (placeholder + outcome/touch/emit), ISSUES I-082/I-101/I-102, scoring-spec.md IN FULL, START-HERE §4 Phase 4, reporting-layer-spec §3.1, PRD §DDL (score_run/prospect_score/conflict_check). Baseline: outreach api/tests 411 passed.
- 2026-08-09T18:00Z — live DB probe (Outreacher): score_run/prospect_score/v_prospect_ranked/conflict_check ABSENT (to_regclass null); outcome/touch/placeholder present. 1407 prospects (847 not excluded), 119 coverage rows, 1 rollup, 0 tech rows, phone_type all 'unknown', franchise {flagged,unknown}, 0 outcomes. Hand-verified all 7 golden fixtures against spec tables (F1=284/642/29.46, F5=268/634/68.1→60 clamp, F7=347/673.5/39.25) — fixtures correct.
- 2026-08-09T18:20Z — TASK migration: wrote migrations/20260809190000_phase4_scoring.sql (score_run + prospect_score + conflict_check per PRD DDL; v_prospect_ranked side-by-side 3-model read; placeholder subordinated via comment). Applied LIVE to Outreacher via Supabase MCP (success). Verified: 4 objects exist, v_prospect_ranked=0 rows (no run yet), 0 anon/authenticated grants. PK forces channel NOT NULL → close stamped per-channel (documented).
- 2026-08-09T18:35Z — TASK config+engine: added scoring config to api/config.py (pdo/target/lambda/offsets/base-rates/display-clamp/R_base/T_base/model_version/coeff-json-override/bin-boundaries/recal-floor); new api/services/scorecard_config.py (elicited-prior REGISTRY, 57 bins, ScorecardParams loader, derive_offset); new api/services/scorecard.py (pure engine: score_model/probability/display_prob/compose_value/replay_score/validate_selection/apply_calibration).
- 2026-08-09T18:40Z — TASK golden harness: api/tests/test_scorecard.py — all 7 golden fixtures green (score 2dp, prob 0.05pp), replay both forms, offsets-vs-base-rates consistency, phone/email never pooled, all-unknown=500=base-rate, JSON override, unknown-bin-raises. 26 passed.
- 2026-08-09T18:45Z — TASK features: api/services/score_features.py (FeatureInputs + reply_bins/close_bins/primary_pitch/review_distribution; unknown==absent, first-scan delta, franchise-flags-not-excludes, reachability-excluded-not-defaulted). api/tests/test_score_features.py 14 passed.
- 2026-08-09T18:50Z — TASK score job: api/services/scoring.py (build_inputs/score_one/assign_deciles/to_records + run_score I/O; phone/pass-1; calibration param) + `score` command in run_market.py (choices/handlers/identity, NOT in PAID_COMMANDS). api/tests/test_scoring.py 8 passed. Fixed assign_deciles single-element -> decile 10.
- 2026-08-09T18:55Z — TASK Stage-2: api/services/recalibrate.py (fit_calibration Fisher-scoring pure + run_recalibration empty-safe, per-channel, Thompson-guarded) + `recalibrate` command. api/tests/test_recalibrate.py 6 passed (recovers known alpha/gamma, near-identity on calibrated data, monotone, preserves score/decile). Added --market-name CLI override (I-105).
- 2026-08-09T19:05Z — FULL SUITE: outreach api/tests 465 passed (411 baseline + 54 new). All 7 outreach service files parse. score/recalibrate confirmed free (not in PAID_COMMANDS, spend_denial None).
- 2026-08-09T19:15Z — LIVE VERIFY: read Railway outreach config (builds main; cron */15 tick; OAuth REDACTS variable values -> can't run run_score locally). Fetched 83 real LA prospects (market 9238e737 "Los Angeles, CA, USA", NOT seeded plumbing market — I-105). Offline-computed full run via REAL pure fns: top reply = low-coverage non-franchise (decile 8-10), bottom = high-coverage (88.9%, geogrid_gt80) + flagged franchises (-87) decile 1 — correct. Wrote 4-prospect faithful sample live, verified v_prospect_ranked pivots reply/close/value + orders by value within channel (1415>1333>714>508, franchise value-decile 1) + display_prob clamp logic (alpha null) — all correct. DELETED demo run; DB clean (0 score_runs/scores/ranked), placeholder intact.
- 2026-08-09T19:20Z — Did NOT run paid producers (owner-away + smallest-scope discipline; Railway-job path, not sandbox). Did NOT repoint platform-api reader to v_prospect_ranked (frontend regression surface, deprioritized) — I-108. Logged DECISIONS (8 entries) + ISSUES I-103..I-108.
- 2026-08-09T19:00Z — Consolidated 4 commits (migration / engine+registry+golden / extraction+job+recal+CLI / docs), pushed branch, opened DRAFT PR #627. Only check is the Netlify deploy-preview (informational; no test CI). Scheduled an ~8-min self check-in to mark ready + squash-merge on green.

## Session Summary (2026-08-09) — Phase 4 Stage 1

**Objective:** Build the real sabermetric SCORING MODEL, Stage 1 (priors). DONE.

**Done:**
- Data model live (migration 20260809190000, applied to Outreacher): score_run / prospect_score / conflict_check (PRD DDL) + v_prospect_ranked (§10 side-by-side). Placeholder subordinated, not dropped.
- Pure scorecard engine (scorecard.py + scorecard_config.py registry): all coeffs config-loaded, zero hardcoded betas; Models A/B/C; replayable score_factors; per-channel pinned offsets; calibration transform.
- Golden-fixture harness: all 7 independent fixtures reproduced exactly. Feature extraction (unknown==absent / franchise-flags / reachability-excluded). Score job + free `score` CLI (phone/pass-1). Empty-safe Stage-2 recalibration + free `recalibrate` CLI. --market-name CLI override.
- 465 tests green (411 baseline + 54 new). v_prospect_ranked verified live on 4 real prospects (franchise value-decile 1; low-coverage non-franchise top), then deleted → DB clean.

**Blocked / not done (deliberate, logged):**
- Did NOT run paid producers scan-organic/scan-ai or free scan-tech (Railway-job path, not the sandbox; owner-away + smallest-scope discipline). Extraction wiring is in place; a producer run lights the bins up with no code change. HIGH-VALUE NEXT: run scan-tech (free) first, then scan-organic/scan-ai at min scope.
- Did NOT repoint the platform-api reader/frontend from the placeholder to v_prospect_ranked (I-108, frontend regression surface). So the UI still ranks by the placeholder until repointed + a `score` run populates the fitted tables.
- Stage 2 (recalibration FIT) and Stage 3 (hierarchical refit + Thompson) wait on accumulated `outcome` rows (0 today). MMR slot selection deferred (selection layer, I-101).

**Paid runs this session:** NONE. **Deploys:** NONE (branch push only). **Railway config:** READ ONLY — never armed a paid command; OUTREACH_CONFIRM_SPEND / OUTREACH_COMMAND untouched (values OAuth-redacted). Migrations applied via Supabase MCP only.

**Look at first next session:** run the free `scan-tech` on the LA market (market "Los Angeles, CA, USA", NOT the seeded plumbing market — I-105), then re-score; and repoint the platform-api reader to v_prospect_ranked (I-108). The scored ranking is a strong PRIOR, not a prediction, until ~100 prospects are contacted.
