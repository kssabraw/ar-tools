# AR Tools — Handoff

## ⏩ Update — 2026-09-04 · **GBP Profile Editor module — ✅ BUILT + MERGED ([#1011](https://github.com/kssabraw/ar-tools/pull/1011), squash `07e1038`), shipped dark** (latest)

The suite's **second GBP write integration** (after Posts): a per-client tool to read + edit a client's Google Business Profile **description, services, and operating hours** via the Business Information API v1 `locations.patch`, every edit **AI-drafted → operator-reviewed → applied on an explicit click**. **Nothing is auto-applied** — the deliberate divergence from GBP Posts, recorded in `docs/adr/0004-gbp-profile-edits-never-auto-applied.md`. Scope was **Phases 0–2** per `docs/modules/gbp-profile-editor-prd-v1_0.md`; Phase 3 (structured services, a real `service_gap` `gbp_audit` check, categories/attributes, periodic drift) is deferred. `platform-api` + frontend only.

What shipped: config (`gbp_profile_enabled` + `gbp_profile_*`, both default off on top of `gbp_api_enabled`); `verify_gbp_api_access.py --edit-test` (a v1 `locations.get` read + a **no-op** `profile.description` patch round-trip that proves the write path with zero visible change); migration `20260904120000_gbp_profile_edits.sql` (**applied live** — `gbp_profile_edits` + the 3 job types `gbp_profile_apply`/`_draft`/`_sync` on the rebuilt-from-live `async_jobs` CHECK); `services/gbp_profile_api.py` (pure builders/validators + v1 get/patch via the v1-hardcoded `gbp_locations_service._build`); `services/gbp_profile_service.py` (always-live read; the **apply job with re-read-and-diff** — aborts into `live_changed` rather than clobbering an out-of-band dashboard edit; the **self-continuing `gbp_profile_sync` reconciler** — backoff lives on the edit-row clock since the worker has no `<=now` `scheduled_at` gate, so a per-cycle sweep honours the ladder); `routers/gbp_profile.py`, `models/gbp_profile.py`, worker dispatch, freeze gates (`gbp_profile_apply` + `gbp_profile_sync`), scheduler sweep; frontend `pages/GbpProfile.tsx` + a **Business Profile** workspace card + new `ErrorDetails` codes (the connection/listing picker was extracted to the shared `components/gbp/GbpConnection.tsx` and **GBP Posts migrated to reuse it**). **Phase 2:** the `gbp_profile_draft` job (description + services; **hours never AI-drafted**); the `update_gbp_profile` SerMaStr action (**stages a draft, never applies**); the Action-Plan producer deep-link (`build_gbp_action` retargets the `gbp_gap` CTA into the editor when the gap is a thin/missing description or missing hours **and** the module is enabled). Tests: `tests/test_gbp_profile.py` (pure builders + apply/reconciler/draft flow). The `gbp_audit.description_quality` loop trigger it depends on shipped earlier in #1009.

**Still to do before flipping on (owner / Railway — can't be done from the sandbox, `developers.google.com` is egress-blocked):** from the PLATFORM shell re-verify the v1 field paths + run `verify_gbp_api_access.py --edit-test locations/<agency>` on the **agency's own** listing (Phase 0 gate), then set `GBP_PROFILE_ENABLED=true` (confirm `GBP_API_ENABLED=true`) and pilot on one client. Both flags default False, so `main` ships the module dark. Module docs: `docs/modules/gbp-profile-editor/HANDOFF.md` + `CLAUDE.md`; decisions in the root `decisions.md` ("GBP Profile Editor module").

## ⏩ Update — 2026-09-03 · **DORA (Director of Operations) — ✅ VERIFIED LIVE end-to-end**

The DORA own-surface provisioning + verification is **complete**. All four surfaces confirmed working:
- **Deploy** — the DORA-code deploy went active (backlog drained past `79e449c`/#892); `gsc_scheduler.started`, no `director_reconcile` step failure.
- **Daily reconcile** — ran at **08:01 UTC** and opened **11 real `director_seam` `content_shipped_degraded` board tasks** (one client, 11 Local SEO pages that failed the brand-voice check in the 14-day lookback). `qa_idle` correctly did **not** trip (QA is actively used — 49 In-QA entries / 49 reviews in 30 days — and the seam fires only after 7+ idle days). The stale "expected qa_idle `ops_seam`" prediction was corrected in the docs (this branch / PR #1001).
- **Web** — `/director` page + DORA sidebar entry live (`director_enabled` true).
- **Slack inbound** — the one real blocker was a **misconfigured Event Request URL**: the DORA Slack app was pointing at `/slack/pace/events` (so #dora messages 403'd against PACE's signing secret). The owner repointed it to `https://platform-production-a5c5.up.railway.app/slack/director/events` (Socket Mode OFF, bot invited to #dora), posted in #dora, and **DORA replied in-thread under its own bot**. Outbound (`ops_seam`/`ops_digest`→#dora) was already confirmed.

Env on PLATFORM: `DIRECTOR_SLACK_BOT_TOKEN` / `_SIGNING_SECRET` / `DIRECTOR_SLACK_CHANNEL`=`C0BTJB2F8M8` set; `DIRECTOR_ENABLED` true; `DIRECTOR_AUTONOMY_VETO_ENABLED` deliberately absent (veto stays dark). **Diagnostic gotcha for next time:** `handle_director_message` is read-only and writes **nothing** to the DB — the only success signals for a Slack DORA turn are the reply itself and the `slack_director_events.hit` / `/slack/director/events` 200 in PLATFORM HTTP logs (no `assistant_store` row; only the web `/director` chat persists). Per `decisions.md`, the acting-agent scope stays trigger-gated (§8) — nothing more to build unless a trigger fires. Docs-only PR #1001 (the stale-QA-note fix) carries this update too.

## ⏩ Update — 2026-09-03 · **Local SEO page spec: feasibility floors, the client-length lift, and the deepen pass (owner ruling; rules 11–12 in `docs/modules/local-seo-adherence-learnings-2026-09-02.md`)**

The 2026-09-02 cross-client batch (First Class Roofing "roof restoration" in template mode: 1,344 words in band, structure ok, 85.0 / 79.4 — the clean win; Wheelhouse Fort Lauderdale run 5: 1,963 vs a 2,083 minimum, again under; Wheelhouse Orlando "IT Support Company Winter Park": in band but **7 structure issues**) exposed two general gaps, both fixed the same day:

- **Proportional scaling had no floor.** Client mode scaled Orlando's 2,287-word reference onto a 1,058-word suburb SERP, so testimonials got a 6–7-word band, the primary CTA 5–6, the local block 12–15, and the 13-item services block 22–28 words with 2–4 H3s. The writer obeyed the bands (testimonials shipped as a bare heading) and the audit failed every one of them. **Owner ruling: a client section's minimum is 80% of its own reference words** (`CLIENT_FLOOR_RATIO`), never below its **structural floor** (`page_spec.structural_floor` — items × 4, required H3s × 25, quotes × 20 with testimonials always two, the FAQ's words-per-item, + a 30-word prose baseline; applies in template mode too, where the template floors already dominate), and when the required floors add up to more than the SERP band the **page band lifts to them** (`lift_page_band`: min = Σ floors, target × 1.2, max × 1.1; SERP numbers kept on `total.serp_*`, `total.lifted_by`, flag `client_length_over_serp`; each required section's minimum is then its floor exactly so the sums close). **Consequence, accepted by the owner: the client's length beats the SERP average whenever the client's reference is the longer** — Winter Park goes from 882–1,164 to ~1,830–2,420 words, ~2× the competitor average by design; the SERP average is then a record on the spec, not the minimum. `validate_spec` rejects a band its structural floor can't fit; the spec block and `PageSpecPanel` explain the lift.
- **A floor nothing enforces is a wish.** The length loop only trimmed; five of five Fort Lauderdale runs landed under the minimum. `_enforce_spec_length` now runs a section-scoped **deepen pass** after the trim (`_spec_deepen_inline` / `_SECTION_DEEPEN_SYSTEM`, `PAGE_SPEC_DEEPEN_PASSES`=2, keep-best on the total shortfall, one closing trim on overshoot, not time-budget gated) that writes substance into REQUIRED under-band sections — competitor entities + related keywords from the SERP analysis (`_spec_topic_hints`), delivery specifics, local anchors, the client's list items — and never invents facts or pads. Expect in-band pages and one extra Sonnet call on most pages (~$0.10–0.20).

**Verify on PLATFORM after deploy:** regenerate Winter Park (expect spec v2, `client_length_over_serp`, testimonials ≥ 70 words, structure ok or ≤ 2 issues) and Fort Lauderdale (expect spec v5 with the industries floor, and a page AT or above 2,083 words). An edited spec still sticks — the lift only applies on a rebuild. Tests: `test_page_spec.py` (floors/lift/Orlando-like fixture), `nlp-api/tests/test_page_spec_enforcement.py` (deepen loop). Everything else in the 2026-09-02 entry below still holds.

## ⏩ Update — 2026-09-02 · **Local SEO writer: the day's adherence fixes are SUITE-WIDE, not Wheelhouse-specific (PRs [#975](https://github.com/kssabraw/ar-tools/pull/975) [#976](https://github.com/kssabraw/ar-tools/pull/976) [#983](https://github.com/kssabraw/ar-tools/pull/983) [#984](https://github.com/kssabraw/ar-tools/pull/984) [#986](https://github.com/kssabraw/ar-tools/pull/986) [#990](https://github.com/kssabraw/ar-tools/pull/990) [#992](https://github.com/kssabraw/ar-tools/pull/992), all merged + deployed)**

Owner question, answered so nobody re-asks it: *"all the fixes we just did with Wheelhouse — the tuning, tightening, optimizing — are those implemented on the Local SEO writer as a whole?"* **Yes — every one of them.** None of the day's changes lives on the Wheelhouse client record; they are all code in the Local SEO writer (`services/page_spec*.py`, `local_seo_service.py`, nlp `main.py` enforcement loops, `review_analytics.py`) and fire for **every client** on every `/generate-page` and `/reoptimize-page` run (so bulk-create, matrix cells and reoptimize-by-URL too). Wheelhouse IT Fort Lauderdale was the test bench (five live runs; trajectory in `docs/modules/local-seo-adherence-learnings-2026-09-02.md`).

What every client now gets, unconditionally: a kept page spec (page band + per-section bands, suspect-SERP clamp) measured after writing with section-scoped trims; structure checked per section and fixed in place (reorder, drop extras, write missing required sections in, rewrite only the drifting ones), saved honestly + notified on drift; a per-section intent + sentiment audit within each section's own band (only `positive` passes); the client's own list items handed to the writer by name; testimonials omitted (never faked) when no reviews are on file; the review pull storing ratings correctly and backfilling `clients.gbp.reviews`.

**Two prerequisites the code cannot supply — per client, operational:**
1. **A usable reference page** (live host, ≥300 words, ≥4 sections) on the client's Setup page → the client's OWN layout becomes the structure (`structure_mode: client`). Without one the page runs in template mode. **First Class Roofing's reference points at `staging3.firstclassroofing.com.au` → template mode until it is repointed at the live page.** The spec panel says which mode is in force.
2. **Reviews pulled once** (`review_intel` job — on-demand from Setup/the Reviews card) → real quotes in the testimonials block. Done today for Wheelhouse FL; queued for Wheelhouse Orlando.

Open (evidence-gated, see the learnings doc §3): an under-band "deepen" pass (four of four FL runs landed 0–2% under the band minimum; the loop only trims — decide after the cross-client batch), capturing list-item TEXT at reference-scrape time, and a cross-client acceptance rollup for plan §7.

## ⏩ Update — 2026-09-02 · **Bulk-throughput review fixes: idempotent Local SEO job retries, visible backoff, path-gated key rotation, cached SDK clients, pool retry budget (migration applied live)** (latest)

An adversarial re-read of #970 found eight issues; all fixed here. None changes the activation steps.

- **Duplicate page on a post-persist transient (the real one).** A Local SEO job whose page had ALREADY been persisted could still be re-queued — the completion write to `async_jobs` raising a transport error, or the reaper requeueing a running row — and the retry regenerated (and paid for) a second page. Now `local_seo_pages.generated_by_job_id` (migration `20260902190000_local_seo_pages_generated_by_job.sql`, **applied live**) is stamped by `_persist_page` (threaded as `job_id=` through `generate_page` / `reoptimize_page` / `reoptimize_url`), and every attempt of `run_generate_job` / `run_reoptimize_page_job` / `run_reoptimize_url_job` calls `_page_for_job(job_id)` FIRST — an existing live page is resumed (completion written, publish-after still runs) instead of regenerated. Best-effort: a lookup failure just generates.
- **Silent five-minute backoff.** `plan_job_retry` now resets `progress` and writes `progress_message = "Temporary provider error — retrying in N min"`; `get_generate_job` returns `retrying` + that message, and the single-generate "Creating…" screen shows it as an amber note instead of a frozen 90% spinner.
- **Rotation slot per generation, not per request.** nlp stamps a slot only on `/generate-page`, `/reoptimize-page`, `/generate-ecommerce-page`, `/reoptimize-ecommerce-page` (`anthropic_failover.should_rotate_path`); health checks / score calls no longer push two consecutive pages onto one account.
- **SDK clients cached per key** (`_sdk_client`, keyed by account key + transport kwargs) — the 16 nlp call sites no longer build N fresh httpx pools per call.
- **Pool retry budget.** With >1 account the per-account SDK `max_retries` is clamped to `ANTHROPIC_POOL_MAX_RETRIES` (default 2) so an all-limited call fails over instead of spending N full backoffs; a single account keeps `ANTHROPIC_MAX_RETRIES` (5).
- **BACKGROUND applied to the rest of the batch enqueuers:** syndication `publish_items`, content-batch items (mass posts), and website page generations (drip release + bulk generate). They now run on the bulk lanes + MAIN and yield to clicks like the Local SEO/Ecommerce batches.
- **Test brittleness:** the enqueue-site test asserts every staggered enqueue is stamped rather than an exact count.
- **Docs:** the `bulk_lane_workers` default is 3 (#977), corrected where the #970 notes still said 1.

## ⏩ Update — 2026-09-02 · **Strategist prose entity decode HARDENED — exact html5-key match, no corruption; extended to questions/findings (PR [#980](https://github.com/kssabraw/ar-tools/pull/980))**

Adversarial-review follow-up to #971 (which fixed the `&amp;` competitor names in recovery prose with a blanket `html.unescape`). The review found #971's `html.unescape` **also decodes the semicolon-LESS legacy entity set**, silently mangling ordinary prose — a real, if low-probability, corruption class the old `.strip()` didn't have. Three findings, all fixed in `services/strategist.py` (verified live: the FCR `goal_recovery` run's `budget.root_cause` still decodes `Melbourne Roof Restoration &amp; Repair` → `& ` correctly).

- **Finding 1 (corruption class):** `budget &pound500 for links` → `budget £500 for links`; a URL `?a=1&copy=2` → `?a=1©=2` / `?utm=x&reg=1` → `?utm=x®=1`; `we should &notindexed pages` → `¬indexed`. The common agency idioms (Q&A, R&D, AT&T, M&A) are all safe (single-letter/spaced), so real-world risk was low — but silent. Fix: `_clean_prose` now decodes **ONLY an exact, semicolon-terminated entity** — a verbatim `html.entities.html5` key (`&amp;`, `&pound;`) via `_HTML5_ENTITIES.get(name + ";")`, or a numeric ref (`&#215;`, `&#x2019;`). A `;`-terminated token whose *prefix* merely happens to be an entity (`&pound500;`) is **left intact** — the exact-key lookup can't prefix-bleed the way `html.unescape` does (that subtlety was caught by a test: `html.unescape("&pound500;")` → `£500;`). Every bare `&` is untouched. `import html` dropped for `from html.entities import html5 as _HTML5_ENTITIES`.
- **Finding 2 (incompleteness):** the `questions` field bypassed `_clean_prose` (it's the same prose class and can echo competitor names). Now `questions = [cq for q in raw.get("questions") or [] if (cq := _clean_prose(str(q)))]` — str-coerced first, so prior filtering/coercion is preserved.
- **Finding 3 (pre-existing latent crash, hardened):** the `findings` guard `(f.get("synthesis") or "").strip()` raised `AttributeError` on a non-str synthesis (model returns a list). It now cleans once via `_clean_prose` and skips a falsy/non-str synthesis without raising.
- **Tests:** exact-entity decode (named/numeric/hex), the no-corruption guarantee (bare `&`, the `&pound500;` prefix case, `&bogus;`/overflow untouched), cleaned questions, non-str `findings` skip. Full strategist blast radius green — **485 across the 19 test files that import `strategist`**; ruff 0.16.5 clean. Supersedes #971's approach (same real-world fix, zero corruption surface).

## ⏩ Update — 2026-09-02 · **DORA guide sync — every user-facing module change is reported to DORA, which rewrites the module's in-app guide when it stops being true (built; needs two secrets to activate)**

Owner ask: "every time a module gets changes that affect the user or output, DORA gets notified and updates the module's tutorial page if needed." Built end-to-end; ships gated on `director_enabled` (on in prod) and **fail-closed until `GUIDE_SYNC_SECRET` is set**. The "tutorial page" is the in-app **Guides** portal (the DB-backed `guides` row each module has — the same page an admin edits) — not the illustrated static field guides or `docs/*.md`, which stay hand-maintained.

- **How it flows.** `.github/workflows/guide-sync.yml` runs on every push to `main` → `writer/platform-api/scripts/report_module_changes.py` (stdlib + git only) diffs `before..after`, groups the changed files by module through the pure **`services/guide_registry.py`** (module → path patterns → `guides.slug`; tests/docs/CI/migrations/scripts/lockfiles/the seeded guides/the field guides are never user-facing; a path matching no module lands in an `unmapped` bucket that is logged, never dropped) and POSTs the commit messages + a bounded per-module diff to **`POST /director/module-changes`** (bearer secret, `hmac.compare_digest`; 503 `guide_sync_not_configured` without a secret, 401 on a mismatch). `services/guide_sync.py::ingest_module_changes` records ONE `guide_sync_runs` row per (commit, module) — the unique pair makes a re-run of the workflow a no-op — and enqueues a **`guide_sync`** async job per row. The job hands DORA (Sonnet, `guide_sync_model`, forced `emit_guide_review`) the current guide + the change; a not-user-visible verdict settles as `no_change` **silently**; a rewrite must clear `validate_revision` (leads with a heading, within `guide_sync_min_ratio`–`guide_sync_max_ratio` × the prior length, not identical, not fenced) or it's `rejected` (never written) and #dora is warned. With `guide_sync_auto_apply` (default **True**) the guide is rewritten in place with the **prior body kept on the run** → a **Revert** button on the guide page; off → a `proposed` run with **Preview / Apply / Dismiss** (staff). One `guide_sync` notification per settled run goes to **#dora** (`DIRECTOR_CHANNEL_KINDS`, PACE-channel fallback) naming the guide + what changed for users.
- **Surfaces.** Guides page (`frontend/src/pages/Guides.tsx` → `GuideSyncBanner`): "DORA updated this guide on … after ‹commit›" + Revert, proposal banners, an expandable sync history. API: `GET /guides/{slug}/sync-runs`, `GET /guides/sync-runs/{id}` (with bodies), `POST /guides/sync-runs/{id}/apply|revert|dismiss` (staff). DORA's read model gained a `guide_sync` block (`providers.prov_guide_sync` → `guide_sync.recent_activity`) + a persona paragraph, so "what changed in Rankings last week / is the Local SEO guide current" answers from it.
- **Scope ruling recorded in `decisions.md`:** this is DORA's ONE write — documentation only, never the board/plans/precedence engines, every applied rewrite revertible from the page. It does NOT loosen the "eyes, not hands" framing for operational state.
- **Migration `20260902180000_guide_sync.sql`** (`guide_sync_runs` + the `guide_sync` job type in the `async_jobs` CHECK, rebuilt from the live list) — **apply it live before/with the deploy**.
- **To activate (owner):** (1) apply the migration; (2) generate a random secret, set **`GUIDE_SYNC_SECRET`** on the PLATFORM Railway service (read the live config first per the CLAUDE.md rule) and the SAME value as a GitHub repo secret **`GUIDE_SYNC_SECRET`**, plus **`PLATFORM_API_URL`** = the public platform-api base URL; (3) merge anything user-facing — the workflow's log lists the modules it reported, and #dora gets one note per guide DORA changed. Until the secrets exist the workflow prints a `::notice::` and exits 0 (never a red check) and the endpoint answers 503. Rollback = unset `GUIDE_SYNC_ENABLED=false` (or the secret); nothing else is touched. `GUIDE_SYNC_AUTO_APPLY=false` switches to propose-only.
- **Self-demonstrating:** merging this PR itself touches `services/director*`/`routers/director.py` → the `dora` module → DORA will review its own guide (whose seeded copy was also updated here, but the prod row is DB-owned, so the sync is what updates it).
- **Tests:** `tests/test_guide_registry.py` (gate, grouping, shared-component multi-module, unmapped bucket, registry↔seed integrity, no-app-deps guard) + `tests/test_guide_sync.py` (normalization, sanity band, notification copy, the review flow with the LLM stubbed — auto-apply/no_change/rejected/proposed/failed/no_guide — apply→revert round trip, ingest idempotency on a fake Supabase, the read-model rollup, the dark job path). `test_director_channel.py` updated for the new kind. Reporter dry-run verified against real commits (`--dry-run`).
## ⏩ Update — 2026-09-02 · **Worker lanes: bulk per-client fairness + `/admin/worker-lanes` observability (PR #969, additive on top of #970)**

Two small additions on top of #970's priority/bulk-lane bulk-throughput work (which already solved the FCR "a reference analysis can't run during a bulk batch" contention via a `priority` column + dedicated bulk lanes). A parallel branch had built a competing *job-type* heavy-lane design for the same problem; #970 is better (priority is per-job, so a single user-clicked `local_seo_generate` stays fast while only bulk-batch items are demoted), so that branch was reworked down to just the two pieces #970 lacks.

- **Bulk-lane per-client fairness** — `job_worker.order_candidates_by_fairness` (pure, unit-tested) reorders bulk claim candidates so a client already holding `bulk_lane_max_per_client` (default 2) background slots is tried LAST, letting another client's batch through. Contention-only (a client alone still uses every slot) and best-effort (count + claim aren't atomic → brief overshoot self-corrects). Threaded through `_claim_next_job` → the BULK lane launch in `main.py`. **Only ENGAGES at `bulk_lane_workers > 1`** — at the default single bulk worker a client can hold at most one slot, so it is a no-op (future-proofing for when the bulk lane is widened).
- **`GET /admin/worker-lanes`** (admin, read-only) — live per-lane pending/running depth for MAIN/INTERACTIVE/FANOUT/BULK (under each lane's own claim filter + priority band) plus the bulk lane's per-client running breakdown, so you can SEE whether one client's batch is dominating and whether raising `bulk_lane_workers` is warranted. Advisory-safe (returns `-1`, never 500s). `services/worker_lanes.py` + `routers/worker_lanes.py`; the lane shapes mirror the `main.py` launcher (keep in sync).
- Config: `bulk_lane_max_per_client` (2). No migration. Pure helpers unit-tested (`tests/test_heavy_lane_fairness.py`, `tests/test_worker_lanes_status.py`); reaper loop mock signature updated for the new `max_per_client` param.
- **`bulk_lane_workers` default raised 1 → 3 (owner ruling 2026-09-02):** three bulk pages generate at once (plus the MAIN lane picking one up when idle), so batches drain ~3× faster — but 3 concurrent multi-pass generations lean hard on the single `nlp` service + Anthropic account, so **pair with `ANTHROPIC_API_KEY_SECONDARY`** (see the recipe below) and watch for 429 backoff + nlp memory. At 3 workers the `bulk_lane_max_per_client=2` fairness cap now ENGAGES (one client holds ≤2 of the 3 bulk slots). **Deploy caveat:** confirm PLATFORM has no `BULK_LANE_WORKERS` env override, or the new default is dead (Railway trap).

**Bulk-throughput tuning recipe (how to make batches drain faster — for whoever turns the knob).** The two async-job "backed up" symptoms have different fixes; don't confuse them.
- **Symptom A — a short/interactive task (a "create page" click, a reference-page `page_structure_scrape`) is stuck behind a running bulk batch.** Already fixed by #970's priority model (interactive priority beats BACKGROUND however old the batch), live once `main` is deployed. Nothing to tune. If you still see it, the fix is NOT more workers — check that a genuinely-interactive job wasn't enqueued at BACKGROUND priority.
- **Symptom B — the bulk batch itself takes hours to drain.** This is throughput-bound, and the ONLY levers are `bulk_lane_workers` + Anthropic capacity. Recipe, in order:
  1. **Watch the gauge first.** `GET /admin/worker-lanes` (admin). If the `bulk` lane's `pending` is deep while `running` == `bulk_lane_workers`, the bulk lane is the bottleneck and more workers will help. If `running` < `bulk_lane_workers`, workers are NOT the problem (nlp/Anthropic is starving them) — go to step 3.
  2. **Raise `bulk_lane_workers` ONE step** (env on PLATFORM; default 3 since #977). Confirm the deploy goes ACTIVE (Railway trap — don't assume). Re-watch the gauge under a real batch.
  3. **Confirm no 429 spike.** Each extra bulk worker is another concurrent multi-pass generation on the single `nlp` service + the single Anthropic account. Grep the `nlp`/`PLATFORM` logs for `anthropic_account_failover` / 429 backoff after raising. If generations start dragging (the ~12-min job creeping toward the ~27-min under-refined failure mode), you've hit the ceiling — back the workers down one, and/or give Anthropic headroom via the key pool (`ANTHROPIC_API_KEY_SECONDARY` on BOTH `nlp` and `PLATFORM`; `anthropic_api_keys` pool per #970). Also watch `nlp` container memory (every lane shares it).
  4. **Fairness rides along.** Once `bulk_lane_workers > 1`, `bulk_lane_max_per_client` (default 2) automatically stops one client's batch from holding every bulk slot — keep it `< bulk_lane_workers` or it never engages. It's a no-op at 1 worker.
- **Rule of thumb:** raise `bulk_lane_workers` only as far as the gauge shows a deep bulk backlog AND the logs show no sustained 429 backoff. It is not a throughput dial you can turn up freely — past the nlp/Anthropic ceiling more workers make every job slower, not the batch faster.

## ⏩ Update — 2026-09-02 · **SerMaStr recovery-plan follow-ups closed — HTML-entity unescape MERGED [#971](https://github.com/kssabraw/ar-tools/pull/971) (squash `13ac405`); the worker-lane follow-up needed no change**

The two loose ends flagged after the live First Class Roofing `goal_recovery` run are both resolved.

- **Fix 2 — HTML-escaped ampersand in recovery prose (MERGED #971).** The strategy digest carries scraped competitor names HTML-escaped (`Melbourne Roof Restoration &amp;amp; Repair`), and the model echoes them verbatim into its `assessment` / `root_cause` / findings `synthesis` / proposal `title`/`action`/`rationale`, so a persisted review — and the `goal_chronic` recovery notification built from it — read `&amp;amp;` instead of `&amp;`. A pure `_clean_prose` helper (strip + `html.unescape`) now runs over those free-text fields in `strategist.sanitize_review`, the single persist choke point, so both the stored review and every downstream notification/digest read clean text (handles named `&amp;` and numeric `&#215;` entities). New test `test_sanitize_unescapes_html_entities_in_prose`; ruff clean. CI green (platform-api tests + lint/typecheck + Netlify preview).
- **Fix 1 — worker-lane contention (NO code change; already fixed by #970).** The bulk `local_seo_generate` batch that delayed the FCR `goal_chronic` alert ~2 h can no longer starve it: #970 stamps bulk items `job_priority.BACKGROUND`, the INTERACTIVE lane claims only `priority >= 0` (fencing bulk out), and both the MAIN and interactive lanes order `priority DESC` so `notification_dispatch` (default priority 0) jumps ahead of every background bulk row. Verified both halves in code (the claim ordering/lane fences and the six BACKGROUND enqueue sites) — the exact scenario cannot recur.

## ⏩ Update — 2026-09-02 · **Bulk throughput: async_jobs priority + bulk lanes + Anthropic key pool + Local SEO transient retries (migration applied live; defaults = today's behaviour)**

Found while a First Class Roofing reference-page scrape sat `pending` behind a 32-page Local SEO bulk batch for what would have been ~3 hours. Four fixes, one PR; every piece is defaulted so deploying it changes nothing until the env vars are set.

- **Queue priority (the root cause).** Bulk flows stamped their per-item jobs 3 min apart so a now-dated interactive job would sort ahead of the rest of a batch — but a page generation takes 10–12 min across two lanes, so after ~7 jobs every remaining bulk timestamp is in the past and anything clicked from then on queues behind the whole batch. Migration `20260902140000_async_jobs_priority.sql` (**applied live**) adds `async_jobs.priority smallint not null default 0` (+ a partial index on pending rows); `services/job_priority.py` holds `INTERACTIVE=0` / `BACKGROUND=-1`; the six bulk enqueue sites (Local SEO generate/reoptimize bulk, Ecommerce ×2, Wheelhouse, the matrix store) stamp `BACKGROUND`; `job_worker._claim_next_job` orders `priority DESC, scheduled_at ASC` and takes `priority_min`/`priority_max` band fences. The INTERACTIVE lane claims only `>= 0` (never a bulk item), the MAIN lane still picks bulk up when nothing else is pending. The `scheduled_at` stagger stays as a mild throttle; it no longer carries priority.
- **BULK lanes = the throughput knob.** `bulk_lane_workers` (default **1** at merge; **raised to 3 in #977**) spawns N `lane="bulk"` workers that claim only `priority <= -1`. 1 keeps the old two-in-flight (bulk lane + MAIN); 4 runs four pages at once. The nlp container serves every lane — watch its memory on Railway as you raise it, and size the key pool to match.
- **Anthropic key pool (all three services).** `ANTHROPIC_API_KEYS` = comma-separated pool of further account keys, any length; the legacy `ANTHROPIC_API_KEY_SECONDARY` is still honoured and merged. Failover walks the pool in order on a transient 429/5xx. **nlp additionally ROTATES**: a pure-ASGI middleware stamps each request with a slot (`anthropic_failover.begin_request_slot`) and every client built during that request starts the pool there — sticky per request (the cached generation prompt stays warm on one account), spread across requests (a batch's concurrent pages divide over the pool from the first call, not after a backoff). `ANTHROPIC_KEY_ROTATION_ENABLED=false` restores reactive-only. Platform/pipeline are failover-only (their calls are short; no rotation). Keys on the SAME Anthropic org share one limit — each pool entry must be a separate account.
- **429 diagnostics.** nlp logs the `anthropic-ratelimit-*` + `retry-after` headers (`anthropic_account_failover` / `anthropic_account_exhausted` lines) whenever it fails an account over — grep those on the `nlp` service to see which limit actually binds (output tokens/min vs requests/min) before adding accounts.
- **Local SEO transient retries.** `run_generate_job` / `run_reoptimize_url_job` / `run_reoptimize_page_job` wrote `status='failed'` directly, so a 502 from nlp (the two 2026-09-02 batch failures at the scoring step, `attempts: 1`) never retried — Ecommerce/Wheelhouse already used the planner. They now settle via `job_worker.settle_job_failure` (5xx/transport ⇒ re-queue with backoff while attempts remain; 4xx ⇒ terminal).
- **To activate:** set `ANTHROPIC_API_KEYS` on `nlp` (and `PLATFORM`/`pipeline` if wanted), then `BULK_LANE_WORKERS=3` or `4` on `PLATFORM`. Read the live Railway config first (CLAUDE.md rule). Rollback = unset.
- **Not fixed here:** the worker sat idle 00:49–01:08 and 01:31–01:45 UTC with 32 jobs pending — not rate limiting; check the PLATFORM Railway logs around those windows (redeploy/restart pattern).
- **Tests:** `platform-api/tests/test_job_priority.py` (claim ordering + fences + the six enqueue stamps + the transient re-queue), pool/rotation/header cases in all three `test_anthropic_failover.py` / `test_llm_retry.py`.

## ⏩ Update — 2026-09-02 · **SerMaStr PR 2 — chronic-goal RECOVERY RUNS built (PRD §4–§9; `services/goal_recovery.py`; migration applied live; ships ON)**

The second half of `docs/modules/sermastr-autonomous-recovery-plans-prd-v1_0.md`: a goal that stays critically behind now gets a **costed, tiered, approvable recovery plan** delivered with the alarm — not just the alarm. **Propose-only** (owner ruling): nothing is handed to PACE; approval goes through the unchanged `strategist_proposals.apply_decision` path. As-built notes in the PRD §12.

- **Trigger + data:** `strategy_reviews.trigger` gains `goal_recovery`; `strategy_reviews.budget jsonb` (the snapshot the plan was costed against — envelope, cumulative tier ceilings over deployable, per-tier counts, root cause, the chronic goals); `sermastr_action_log.decision` gains `superseded`. Migration `20260902130000_strategy_reviews_goal_recovery.sql` — **applied live** + committed.
- **Sweep → run → message:** `goal_escalation._sweep_client` now only collects the due `(row, goal)` pairs; `_dispatch_due` orders clients oldest-behind first, enqueues up to **`goal_recovery_max_runs_per_tick`=5** recovery runs (`goal_recovery.enqueue_recovery_run` → `enqueued|in_flight|disabled|failed`), and falls back to the #949 bare alarm (`_escalate_bare`) only when a run is impossible. A capped or in-flight client is neither alarmed nor stamped — it rolls to the next tick. The **finished run** (`goal_recovery.after_persist`) supersedes the prior recovery plan's open proposals, stamps the `goal_escalations` rows (`last_escalated_at`/`escalation_count` — deferred from the sweep so a failed run retries next day), and emits the ONE `goal_chronic` message (STILL CRITICAL title + root cause + up to 5 proposals with cost + tier + the fundable line + link to the Action Plan card). Sweep stats: `recovery_enqueued/_deferred/_in_flight`.
- **The run:** full digest + a RECOVERY block (`build_recovery_block`: chronic goals with weeks-behind/worst/current/target, the prior plan's open proposals from the new `open_proposals` digest section, `recipe_engine.budget_envelope` over the client card, tier ceilings) + a recovery orientation in `build_run_prompt` (MUST emit proposals, MUST set the new optional `root_cause` emit field naming competitor + sector + what they built, may reallocate the current task plan at proposal level, one budget-adequacy proposal `requires=senior` when the fundable set is thin). Tiers assigned in code (`assign_tiers`: running total in the strategist's order → `within_budget`/`plus_25`/`plus_50`/`plus_100`/`over`, `unbudgeted` when the card has no retainer). Same drill-down caps.
- **Prompt (all runs):** the "empty review is valid" exit is now "EMPTY PROPOSALS ARE VALID ONLY when every behind goal has an OPEN proposal addressing it", backed by `strategy_digest._prov_open_proposals` (window `strategist_open_proposals_days`=60). The weekly review still runs after a recovery run.
- **Superseded is a system state:** `strategist_proposals` refuses to approve/dismiss one (`proposal_superseded` → 409) and excludes it from `open_proposal_indices` (the bulk plan→PACE handoff can't approve a stale plan); `sermastr_audit._tally_stats` counts it in its own bucket, outside the approve/dismiss learning rates; `record_superseded` logs it as `actor_source=system`.
- **API + UI:** `POST /clients/{id}/strategy-review` takes `{"trigger":"goal_recovery"}` (409 `goal_recovery_disabled` / 422 `invalid_trigger`); the list select carries `budget`. `StrategistReview.tsx`: a "Recovery plan" box (goals + root cause + budget line + **Approve tier** buttons — a client-side loop over the per-proposal endpoint, reporting senior-only refusals), tier pills, a **"Still open from earlier reviews"** section (60 days / 5 reviews) so a plan survives the next weekly review, superseded count; `types.ts` gains `StrategyReviewBudget`, `tier`, `superseded`, the two new triggers.
- **Config:** `goal_recovery_enabled` (True — rides `strategist_enabled` + `goal_escalation_enabled`), `goal_recovery_max_runs_per_tick` (5), `goal_recovery_tiers` ("0.25,0.50,1.00"), `strategist_open_proposals_days` (60).
- **Tests:** `tests/test_goal_recovery.py` (tiers, snapshot, block, notification, supersede, cap ordering, enqueue statuses, after_persist isolation) + new cases in `test_goal_escalation.py` (enqueue-not-alarm, bare fallback, in-flight, cap defers, gate-closed = #949 behaviour), `test_strategist.py` (trigger/root_cause/orientation/prompt rule + a scripted goal_recovery run asserting tiers, `budget`, one goal_chronic), `test_strategist_proposals.py`, `test_sermastr_audit.py`.
- **Verify after deploy:** `POST /clients/a121d78b-6d44-4e8d-aa99-892e2fadc7ab/strategy-review` with `{"trigger":"goal_recovery"}` (~$1) → the review's `budget.root_cause` names the competitor, proposals carry tiers, ONE `goal_chronic` lands in Slack + in-app; then watch the first 08:00 UTC tick for the day-one burst (`recovery_enqueued` ≤ 5, `recovery_deferred` for the rest, no bare alarms while the gate is open).

## ⏩ Update — 2026-09-02 · **SerMaStr PR 1 — the strategist emit-truncation fix MERGED #956 (all clients; PRD §3 PR 1)**

The measured root cause of the portfolio-wide 0-proposal strategist reviews (see the entry below + `docs/modules/sermastr-autonomous-recovery-plans-prd-v1_0.md` §2) is fixed at all three points. Code in `writer/platform-api/services/strategist.py` + `config.py`; tests in `tests/test_strategist.py`.

- **Cap:** `strategist_max_tokens` **4096 → 16000** (config default; worst-case output ≈ $0.25/review). ⚠️ If PLATFORM carries a `STRATEGIST_MAX_TOKENS` env override the default is dead — check `list-variables` before trusting the deploy (the Railway connector was unauthorised in this session).
- **Schema order:** `emit_strategy_review` now lists `assessment` → `proposals` → `questions` → `findings`, and its description tells the model to write them in that order, so a long output loses the least actionable part first.
- **`stop_reason` guard:** `is_truncated(resp)`; on `max_tokens` the run discards the partial turn, appends it (`_assistant_turn` — never an empty assistant message), answers it with `truncation_followup(tool_uses)` (one `tool_result` per cut-off `tool_use` block — API contract — or a plain text turn when the block was dropped) and forces the emit on the next round. **Exactly one retry** (`_MAX_TRUNCATION_RETRIES=1`; the loop bound grew by one round). Still truncated → stored `complete` with `token_usage.truncated=true` + `TRUNCATION_QUESTION` appended (findings kept; the `status` CHECK `running|complete|failed` untouched). Logs: `strategist.emit_truncated_retry` / `strategist.emit_truncated_final`; `strategy_review_complete` now carries `truncated` + `truncation_retries`.
- **Tests:** schema order, the pure helpers, and four scripted-response run-loop cases (retry-then-full keeps the full emit and answers `tu-1`; still-truncated flags + appends the question and never loops; a dropped tool block retries with a text turn; an untruncated emit is byte-for-byte the old path).
- **Verify after deploy:** one on-demand FCR review → `token_usage.output_tokens` well under 16k and `proposals > 0`; then the next weekly pass across all clients should show proposals/questions again (they were 0 across all 13 reviews the week of Aug 31).
- **Next:** PR 2 (the `goal_recovery` runs) per PRD §4–§9.

## ⏩ Update — 2026-09-02 · **SerMaStr autonomous recovery plans — PRD approved, root cause of the 0-proposal reviews MEASURED (docs-only, MERGED #955)**

The owner's brief: SerMaStr must autonomously produce suggested **solutions**, not just diagnoses — First Class Roofing's weekly strategist called the local-pack goal a critical emergency for ~8 weeks and emitted **0 proposals** every week, so the owner had to extract a recovery plan by chat. The brief's Step 0 said "confirm the real mechanism before coding". Done, and it is **not** the brief's hypothesis. PRD: **`docs/modules/sermastr-autonomous-recovery-plans-prd-v1_0.md`** (20 owner rulings in §11, from a grilling session 2026-09-02).

- **Root cause = emit truncation.** `strategist_max_tokens`=**4096**; the `emit_strategy_review` schema writes `findings` before `proposals`/`questions`; `run_strategy_review` never checks `stop_reason`, so the cut-off tool call is persisted as `complete`. Every zero-proposal review since mid-August has emit-round `token_usage.output_tokens` at **4096–4700** (cap + drill-down overhead); reviews that DID propose finished at 3566–3936 or had short findings. Two reviews stored zero findings (cut mid-array). **Portfolio-wide** — week of Aug 31: 13 reviews across all clients, all at cap, 0 proposals, 0 questions — and worsening as the digest grew (#945 competitor pages, GBP metrics, backlinks → longer findings).
- **Three more findings.** (1) #949's `goal_escalation` sweep has **never fired in prod** as of 2026-09-02 — `goal_escalations` 0 rows, `goal_chronic` 0 notifications (merged the evening before; likely no daily tick yet). (2) **FCR's notification feed looks wiped** — nothing for `strategy_review`/`maps_drop`/`reopt_plan` after 2026-07-07 despite weekly reviews and the Aug 7 collapse (the bulk-delete footgun #949 fixed), so whether Slack got those reviews can't be confirmed from the DB. (3) `StrategistReview.tsx` renders **only the latest completed review's** proposals — an unactioned proposal vanishes once a newer review lands (this would have hidden a recovery plan after the next weekly review).
- **PR 1 (ship first, all clients):** `strategist_max_tokens` 4096→16000 · reorder the emit schema so proposals+questions precede findings · a `stop_reason==max_tokens` guard with ONE forced re-emit retry ("cut off — proposals first, ≤5 findings ≤2 sentences") · still truncated → stored `complete` + `token_usage.truncated=true` + an appended question (the `status` CHECK `running|complete|failed` is untouched). **Deploy checklist:** confirm PLATFORM has no `STRATEGIST_MAX_TOKENS` env override (the Railway connector was unauthorised in the session — the data says the effective cap is 4096 regardless).
- **PR 2 — `goal_recovery` runs (propose-only, owner ruling: NO auto hand-off to PACE):** new trigger value (migration widens the CHECK + adds `strategy_reviews.budget jsonb`) · fired by the daily escalation sweep, **one run per client** covering all its chronic goals on the `goal_escalation_reescalate_days` cadence, **cap 5 runs/tick** (a capped client is not escalated that day — no bare alarm — and rolls forward; the first prod tick will open rows portfolio-wide since `initial_behind_since` seeds from baseline) · the **finished run** emits the single `goal_chronic` message (root cause + top proposals with cost + tier + fundable line + link); the sweep's bare alarm fires only when a run is impossible · run reads the full digest + a RECOVERY block (chronic goals w/ weeks-behind + worst value, prior recovery proposals, `recipe_engine.budget_envelope`, tier ceilings); emit gains optional `root_cause` (required in recovery mode: competitor + sector + what they built) · budget: proposal-level reallocation of this month's plan (the stored `monthly_task_plans` row is never rewritten) + **cumulative +25/+50/+100% tiers over deployable** assigned deterministically in code by running total in priority order; envelope/ceilings/root cause **snapshotted** on the review row — the client card stays the only budget input · prior `goal_recovery` proposals → `superseded` at persistence (own `sermastr_action_log` decision value, excluded from approve/dismiss rates) · prompt (all runs): "empty review is valid" → "empty proposals are valid only when every behind goal has an OPEN proposal addressing it" + an `open_proposals` digest section; the weekly review still runs after a recovery run · `POST /clients/{id}/strategy-review` gains a staff `trigger=goal_recovery` for validation (no button yet) · frontend: the card lists open proposals across 60 days / 5 reviews + an "Approve tier" client-side loop over the existing per-proposal endpoint · flag `goal_recovery_enabled` default **on**. Same drill-down caps.
- **Validation plan:** after PR 1, one on-demand FCR review (`output_tokens` < cap, proposals > 0) + watch the weekly pass; after PR 2, one on-demand `goal_recovery` run on FCR (~$1) checked against PRD §8, one `goal_chronic` in Slack AND in-app, then the first 08:00 UTC escalation tick for the burst/cap behaviour; and confirm FCR's weekly `strategy_review` notification actually reaches Slack now that the feed-wipe is fixed.
- Also recorded as DECIDED in root `decisions.md`.

## ⏩ Update — 2026-09-01 · **DORA sees the agent track records — PACE + SerMaStr action logs wired into the Director read model MERGED (PR [#939](https://github.com/kssabraw/ar-tools/pull/939), squash `1859db9`)**

Follow-up to #937: DORA's cross-agent read model surfaced seam flags, interventions and the autonomy ledger but NOT the two agents' OWN action logs, so it couldn't say how reliably each agent's work gets accepted (or, for SerMaStr, whether it moved the metric). Added as **read-only insight** — no new seam, no reconcile task, no change to reconcile/veto/digest. CI-green (pytest 4842 / ruff / mypy / Netlify), full suite verified locally.

- **`services/director/providers.py`** — `prov_pace_audit` + `prov_sermastr_audit` reuse the ledgers' own tested rollups (`pace_audit.stats_window` / `sermastr_audit.stats_window`) over `director_audit_window_days` (90); scoped to the model's client (scalar) or agency-wide (`None`; the ledgers keep rows after client deletion → a true track record, not board-scoped); gated on each ledger's `*_audit_enabled`; None when nothing logged; pure `_top_buckets` bounds the payload.
- **`services/director/read_model.py`** — two new keys (`pace_audit`, `sermastr_audit`), each `_isolate`-wrapped like every other provider.
- **`services/director_agent.py`** — `_DORA_SYSTEM` describes the two blocks as reliability signals (PACE approve/modify/deny/defer/cancel + revert; SerMaStr approve/dismiss/pending + worked/partial/no_effect), explicitly NOT seams. The read model is handed to DORA as JSON, so the blocks flow straight into its answers — ask "how's PACE doing / why does this kind of proposal keep getting rejected".
- **Config** `director_audit_window_days` (90). Tests: `test_director_providers.py` (reuse + `since` math + gating + `_top_buckets`) and `test_director_read_model.py` (wiring).

## ⏩ Update — 2026-09-01 · **SerMaStr action log — audit + self-learning ledger MERGED (PR [#937](https://github.com/kssabraw/ar-tools/pull/937), squash `4219874`)**

The strategist analogue of the PACE Action Log (#935): a best-effort, agent-attributed audit stream at SerMaStr's OWN seams + a dark learning loop, **reusing** `strategy_reviews` (proposal content) + `interventions` (outcome) rather than rebuilding them. CI-green (pytest 4837 / ruff / mypy / Netlify), full suite verified locally before the PR, migration applied live + verified (table + 5 indexes + unique constraint). Owner scope decisions confirmed up front via `AskUserQuestion`: **dedicated ledger table** (not reuse strategy_reviews) + **prompt-steering-only** auto-adjust (no hard proposal filter).

- **Logging (ON by default, `sermastr_audit_enabled`).** `sermastr_action_log` (migration `20260901150000`) — one row **per proposal**, keyed by a unique `source_ref = strategy_proposal:{review_id}:{idx}` (the SAME key `interventions.py` uses → outcome enrichment is a one-column join). Captures the proposal (title/action/SOP citation/rationale/`requires` gate/`target`), the human decision (`approved`/`dismissed`/null=pending), actor + when + role/source, the client, and the reused worked/partial/no_effect verdict. `client_id` on-delete-set-null (the `client_name` snapshot outlives the client); RLS service-role; keep forever. Core `services/sermastr_audit.py` (pure helpers unit-tested `tests/test_sermastr_audit.py` (25) + best-effort impure I/O). Seams: proposals logged at review completion (`strategist.run_strategy_review`); the decision at `routers/strategist.set_proposal_status`; a daily outcome sweep on the shared scheduler stamps `interventions.verdict`. A logging failure NEVER breaks a review.
- **Self-learning (DARK, `sermastr_audit_learning_enabled` default False).** Weekly `strategy_learning_digest` (default/strategy channel; also needs a configured `sermastr_audit_digest_weekday`, off by default) + **prompt steering** — a "YOUR TRACK RECORD (weigh, don't obey)" block injected into the strategist run prompt via a new optional `build_run_prompt(track_record=…)` (flag off/thin history → "" → prompt byte-identical). No hard proposal filter.
- **Surfaces.** Admin read API `GET /strategist/action-log` + `/stats` + `GET /strategist/status`; frontend `pages/SermastrLog.tsx` at `/strategist/log` (admin, nav-gated on strategist enabled — mirrors `/pace/log`); a passive `strategist_track_record` context provider (counts only) for conversational SerMaStr.
- **Adversarial-review fix folded in (squash `895e0b7`).** `record_decision` upsert-merge could NULL a pending row's snapshotted `client_name`/`trigger` on a re-decision after the client was deleted (review.client_id → null → client_name=None) — fixed by stripping None-valued keys before the upsert (create-if-missing unaffected); +1 regression test.
- **Config** `sermastr_audit_*` mirrors `pace_audit_*`: `_enabled` (True) / `_history_limit` (25) / `_learning_enabled` (False) / `_digest_weekday` (None) / `_outcome_window_days` (90) / `_learning_window_days` (90) / `_learning_min_samples` (3) / `_learning_dismiss_threshold` (0.6). **To activate learning:** set `SERMASTR_AUDIT_LEARNING_ENABLED=true` (turns on prompt steering) and/or `SERMASTR_AUDIT_DIGEST_WEEKDAY` (0–6, the weekly digest) on PLATFORM.

## ⏩ Update — 2026-09-01 · **Goal-driven audit COMPLETE — all five findings MERGED (#929/#930/#931/#932/#933)**

The "is SerMaStr actually goal-DRIVEN?" audit (does the client's real `campaign_goals` metric actually *cause* behaviour, or is it just referenced when a review happens to run?) is done — all five fixes are merged to `main`, CI-green each (pytest/ruff/mypy/Netlify), separate focused PRs, pure helpers unit-tested:

- **#1 (PR #929, squash `37257a5`) — behind-goal trigger.** `strategist.clients_with_behind_goals()` folds behind/overdue goals (baseline required) into `clients_with_active_signals()`, so a slipping goal *summons* the weekly review instead of waiting for the ~monthly sweep. Gated `strategist_goal_trigger_enabled` (default True).
- **#4 (PR #930, squash `ff49a97`) — Director `strategist_proposal_pending` seam.** A proposal left in `status:"proposed"` past `director_seam_proposal_pending_days` (default 5) now opens ONE auto-closing `director_seam` board task (mirrors `strategist_approved_unplaced`; nudge-to-a-human). `prov_strategy` emits a `proposed_pending` list; wired into `compute_flags`/reconcile/digest/`director_agent._SEAM_LABELS`.
- **#5 (PR #931, squash `079c160`) — no-goal nudge.** `strategy_digest._prov_campaign_goals` emits a `{"no_goals": True}` sentinel (no `goals` key, so goal-exist readers are untouched) + one `_SYSTEM` priority-0 line telling the strategist to flag a missing success metric. Does NOT touch the weekly active-signal gate.
- **#2 (PR #932, squash `a1e60e6`) — goal-aware Action Plan boost (owner-approved capped cross-tier).** `reopt_planner`: a NON-emergency action whose channel matches a behind goal is remapped into the fractional window `(_SORT_OFFPAGE-1, _SORT_OFFPAGE)` — above off-goal cannibalization/quick/hidden, below every emergency. Pure `action_channel`/`goal_channels`/`apply_goal_boost`; gated `reopt_goal_boost_enabled` (default True); no emergency tier touched.
- **#3 (PR #933, squash `7a5f153`) — proposal-only autonomy goal-lever routing (owner-approved, after #2).** `autonomy_executor.gather_candidates` now surfaces a behind maps/GBP goal's local/GBP Action Plan items as **PROPOSAL-ONLY** candidates (`requires="approval"`, `cost_usd=0`) via `_MAPS_KIND_LEVER`, reusing #2's pure helpers. Nothing auto-runs — `requires="approval"` classifies `"propose"` at policy rule 3; `AUTO_EXECUTE`/tiers untouched.

**#2 and #3 were owner-decision design changes** (load-bearing/guardrail): traced in real code, put to the owner via `AskUserQuestion` with options/tradeoffs/recommendation, who picked the recommended option for each. **NO autonomy guardrail was loosened** — `AUTO_EXECUTE`, the tier cap, and every emergency tier are untouched; the strategist still proposes-never-executes; #3's routed maps/GBP levers are all human-approved.

**Net effect on SerMaStr (the honest split):** the campaign goal is now a *causal input* to (a) whether a review runs, (b) how the Action Plan is prioritised, (c) which autonomy candidates surface, and (d) flagging missing metrics + stuck proposals — a **reasoning/proactivity** gain. It is **not** more powerful at unattended **execution** (no new auto action, autonomy still dark/pilot with the same tiny allowlist). Still-standing ceiling (deliberate, per `docs/modules/autonomous-seo-agent-plan-v1_0.md`): no closed loop that autonomously *moves* a goal metric end-to-end; the goal-aware routing/ordering changes *what surfaces*, not *what runs*.

## ⏩ Update — 2026-09-01 · **Goal-driven audit — finding #5 (no-goal nudge) MERGED (PR #931)**

**Finding #5 — no-goal nudge — MERGED** (PR #931): a client with zero campaign goals was permanently outside the goal-accountability machinery — `strategy_digest._prov_campaign_goals` returned `None` when a client had no active goals, so the digest omitted the `campaign_goals` section entirely and the strategist's priority-0 goal block never engaged; nothing flagged the missing success metric. Smallest additive fix: `_prov_campaign_goals` now returns a lightweight `{"no_goals": True}` sentinel instead of `None` when `assess_goals` comes back empty (the sentinel carries no `goals` key, so every "goals exist → lead with them" reader — the LeadOff-domain check + the strategist prompt — is untouched), and one line was added to `strategist._SYSTEM`'s priority-0 block: when `campaign_goals` reads `{"no_goals": true}`, raise the missing success metric as a finding/question and suggest a fitting metric from what the client is actually measured on. Best-effort, doesn't touch the weekly active-signal gate (`has_active_signals` never read goals) so a no-goal client isn't force-summoned to a review — the sentinel is purely informational for when a review does run.

## ⏩ Update — 2026-09-01 · **Goal-driven audit follow-ups — #929 (behind-goal trigger) + #4 stuck-proposal Director seam MERGED**

Continuation of the "is SerMaStr actually goal-DRIVEN?" audit below. **PR #929 (finding #1 — a behind/overdue campaign goal now summons the weekly strategist review) is MERGED to `main`** (squash `37257a5`, all CI green — pytest/ruff/mypy/Netlify — verified on the head docs SHA, not just the code commit).

**Finding #4 — stuck-proposal detector — MERGED** (PR #930): a strategist proposal nobody approves/dismisses sat in `status:"proposed"` forever, counted by the Director read model (`prov_strategy.status_counts`) but with no seam. Added a new **`strategist_proposal_pending`** Director seam mirroring `strategist_approved_unplaced`: `prov_strategy` now emits a `proposed_pending` list (per proposal: `review_id`, `proposal_index`, `title`, `requires`, `since`=review completed_at/created_at); a pure `seams.strategist_proposal_pending` predicate (fires past `director_seam_proposal_pending_days`, default **5**); wired into `compute_flags` + the `read_model` thresholds dict; a `_TITLES` entry + `_SEAM_ORDER` slot + a `director_agent._SEAM_LABELS` label (the drift-guard test forces this). It opens ONE `director_seam` board task via the existing producer contract, auto-closing when the proposal leaves "proposed" (approved/dismissed) — nudge-to-a-human only, no guardrail loosened. Same `ident` as approved_unplaced (`review:idx`) but the seam name in the `source_ref` keeps the two tasks distinct across a proposal's lifecycle. Unit-tested (`test_director_seams.py` predicate/threshold/ident-distinctness/compute_flags wiring; `test_director_providers.py` `prov_strategy` proposed_pending/status_counts/since-fallback).

## ⏩ Update — 2026-09-01 · **SerMaStr "is it actually goal-DRIVEN?" audit — 1 fix shipped (PR [#929](https://github.com/kssabraw/ar-tools/pull/929), MERGED), the rest is an evidenced blocker list**

A follow-on to the module-cards audit below, but a *different* question: the prior session confirmed SerMaStr's **read** coverage is near-total; this one asked whether SerMaStr is actually **equipped, instructed, and wired to BEHAVE like a proactive director whose job is moving each client's real campaign goal** (a rank position, or a `gbp_calls`/impression count — whatever `campaign_goals.py` says that client is measured on), not just answer well when asked. Traced the real code paths (grep'd call sites, read the actual prompt text sent to the model, followed a goal from creation to whatever closes the loop). **Honest finding: No, not as a system.** The interactive SerMaStr answers goal questions well and the strategist names goal accountability as priority-0 — but the goal barely *causes* anything; it's referenced when a review happens to run, not a force that makes reviews run, reprioritizes work, or routes effort to the right lever.

**Shipped this session (PR #929, branch `claude/sermastr-proactive-audit-vcpsyl`, draft, subscribed, Netlify ✅, local suites green):** the single highest-leverage in-bounds fix — **a behind/overdue campaign goal now summons the weekly strategist review.** `strategist.clients_with_active_signals()` (`services/strategist.py:696`) — which decides WHICH clients get a weekly review — only read `rank_alerts`/`maps_alerts`/`offpage_alerts`/`response_episodes`/`monthly_task_plans`; **`campaign_goals` was not in that set**, so a goal quietly slipping with no matching rank-drop alert only reached a review via the ~monthly opportunity sweep, never *because it was behind*. New `clients_with_behind_goals()` folds behind/overdue goals (with a captured `baseline_value` — a null-baseline goal reads "behind" as a measurement artifact per the campaign-goals module card, so excluded) into the active-signal set. Still proposes-only + human-approved (changes WHEN a review runs, never what it may do — no guardrail touched); gated on new `strategist_goal_trigger_enabled` (default True); best-effort (empty set on failure). 3 new unit tests (`TestClientsWithBehindGoals`); `test_strategist.py` (46) + campaign_goals/autonomy/strategy_digest green locally.

**The full evidenced blocker list (sorted by outcome impact) — the actual deliverable:**

- **#1 (HIGH — SHIPPED in #929):** a behind goal didn't summon the strategist (above).
- **#2 (HIGH — OWNER CALL, design change):** the **Action Plan is completely goal-blind.** `services/reopt_planner.py` has ZERO goal references; `build_plan` (`:1168`) sorts by a FIXED tier order (`_SORT_SITEWIDE > _SORT_DROP > _SORT_OFFPAGE > _SORT_CANNIBAL > _SORT_MAPS > _SORT_QUICK > _SORT_HIDDEN`, `:53–67`) — identical whether the client is measured on organic rank or GBP phone calls. This ranked to-do list is the most-consumed artifact (feeds autonomy candidates, PACE, digest, Slack answers). A pure-`gbp_calls` client gets an Action Plan topped by organic drops/cannibalization with GBP/Maps levers at tier 3, below cannibalization. Making tier weights goal-aware is a real change to the most load-bearing artifact — needs an owner decision on how to reweight.
- **#3 (MEDIUM, dark so limited blast radius — OWNER CALL):** the autonomy executor is **goal-TYPE-blind.** `autonomy_executor.gather_candidates` (`:55`) uses goals only as an on/off gate (`_BEHIND`, `:86`) then pulls quick_win/opportunity items off the (goal-blind) Action Plan and emits `generate_local_seo_page`/`reoptimize_page` — organic/local-page levers. A Tier-2 `gbp_calls` client, if behind, would get organic pages generated for a phone-calls goal; GBP posts/completeness are never candidates. Entangled with #2 + with expanding autonomy.
- **#4 (MEDIUM — CLEAN NEXT BUILD):** never-approved strategist proposals are **never chased.** A proposal nobody approves sits in `status:"proposed"` forever. The Director read model counts it (`director/providers.py::prov_strategy` → `status_counts`) but the only seam is `strategist_approved_unplaced` (`director/seams.py:40`) — approved-but-unplaced, NOT proposed-but-unactioned. Build a `strategist_proposal_pending` Director seam mirroring the existing pattern (surface "N proposals unactioned X days" → ops task/notification). Additive, no guardrail loosened.
- **#5 (MEDIUM — SMALL BUILD):** no goal → no proactive target, and **nothing nudges toward setting one.** `strategy_digest._prov_campaign_goals` returns None when a client has no goals (section omitted; strategist priority-0 never engages), client creation (`routers/clients.py`) has no goal nudge (auto-scans brand-voice/ICP only), and SerMaStr suggests goals only when directly asked "how is the campaign going" (`prompts.py:255`, reactive). Fix: a digest sentinel + one strategist prompt line, or an onboarding nudge.
- **#6 (LOW — mechanism not outcome):** off-track forecasts (`forecasting.goal_projection` → `on_trajectory:False`, `:234`) and `no_effect` interventions (`interventions.summarize_effectiveness`) are read-only numbers — neither emits/enqueues/escalates. Observational by design; #929 partly addresses it (a projected-off-track goal reading `behind` now summons a review that reads its own projection).

**Deliberate guardrails — do NOT loosen without an owner decision** (distinguished from the gaps above): SerMaStr proposes-never-executes (`strategist.py:230` + `sanitize_review`); autonomy ships dark (`autonomy_enabled=False`, `AUTO_EXECUTE` allowlist = `{rebuild_action_plan, generate_local_seo_page}` only, Tier-capped at 2, one-client pilot) — "almost nothing auto-executes" is the *intended* state and the real architectural reason a fully-autonomous goal-achieving director is impossible today, per `docs/modules/autonomous-seo-agent-plan-v1_0.md`; senior/freeze/disavow stripping in `sanitize_review`. **Next-build candidates (owner to greenlight):** #4 (stuck-proposal seam) and #5 (no-goal nudge) are clean/low-risk "just build it"; #2 and #3 (goal-type→lever routing / autonomy scope) are owner design/scope calls.

## ⏩ Update — 2026-09-01 · **SerMaStr module-cards expansion — Forecasting/Domain Intelligence/Campaign Goals cards MERGED ([#926](https://github.com/kssabraw/ar-tools/pull/926), squash `94a82e5`)**

A module-coverage audit of SerMaStr found its `_ctx_*` context-provider coverage already near-total (34 registered providers spanning organic rank, maps, AI visibility, forecasting, domain intel, competitive intel, keyword research, LeadOff, QA, budget, and more) — the real gap was one level deeper: only 3 of those modules had a **module card** (`docs/agents/module-cards/` — the "how to correctly read this data" layer, distinct from the SOP corpus: direction conventions, null-handling rules, known blind spots, a worked misreading example), while everything else had only light inline docstring notes on its context-provider function.

- **PR [#925](https://github.com/kssabraw/ar-tools/pull/925)** (open, draft, CI green, **awaiting owner review/merge** — not merged this session): fixed the one real gap the audit found in *existing* coverage — `_ctx_director` was computing but discarding `intervention_outcomes` (did past link-building/reoptimization proposals actually move the keyword) and `autonomy_loop` status, surfacing only `seam_flags`. Now surfaces all three.
- **PR [#926](https://github.com/kssabraw/ar-tools/pull/926)** (merged): wrote three new module cards for the modules judged most load-bearing in a strategy review among the uncovered set — `forecasting.md`, `domain-intelligence.md`, `campaign-goals.md` — each grounded directly against the owning service's code (`services/forecasting.py`/`domain_intel.py`/`campaign_goals.py`), not the CLAUDE.md prose. Notable per-card traps documented: forecasting's `trend_per_week` sign convention (negative = improving, the opposite of the plain-English reading) and the quick-win scenario being CTR-model math throughout even for GSC-anchored keywords; domain intelligence's ×10 competitor-RD discount applying to *any* domain snapshot (verified via a direct shared-function trace to `backlinks_api.fetch_summary`, not by analogy) and `gap_type: missing` conflating "no page targets this" with "ranks past the position-100 fetch depth"; campaign goals' `achieved_at` being a one-time stamp, not a status lock (a later regression still reads `behind` on the next read), and — found in an **adversarial re-review** after the first pass, not in the original draft — a previously-undocumented failure mode: a goal whose `baseline_value` fails to capture at creation (a keyword goal made before the keyword is tracked, a clicks goal made before GSC is verified) permanently reads `status: behind, progress_pct: null` — masquerading as active underperformance rather than the missing-data problem it actually is, since `create_goal()` swallows the failure into a stored `null` with no backfill anywhere in the codebase. Registered automatically (no manifest — `sop_library.load_module_cards()` globs the directory and injects every card whole, unconditionally, into every strategist run); vendored copies under `writer/platform-api/agent_docs/module-cards/` kept byte-identical per the existing sync-guard test; both module-card tests re-verified passing.

**Still uncovered by a card, deliberately** — per the audit's own scoping call, a card gets written when a real misreading trap is worth documenting, not preemptively for every module: keyword research, LeadOff, competitive intelligence, ecommerce, website builder, and others still have only inline notes.

## ⏩ Update — 2026-09-01 · **Local landing page structure doc — Trust & Proof architecture added (docs-only, MERGED [#919](https://github.com/kssabraw/ar-tools/pull/919))**

A documentation-only update to `docs/modules/local-landing-page-structure.md` (the Local SEO writer's local-landing-page structure guidelines) — **no code changed**, so nothing in `writer/nlp-api`'s actual page generation is different yet; this is a spec addition that a follow-up build would implement. Mapped a batch of trust-element requirements onto the doc's existing design logic (deterministic/injected vs. model-written, plus the Content Gaps mechanism) rather than bolting on a new section:

- **New deterministic block, "Trust & Proof"** (sibling to the existing Contact & Find-Us block): a trust badge strip (BBB/Google Guaranteed/Angi/trade-association seals, sourced from a `certifications`/`affiliations` field), an aggregate GBP rating badge (never model-estimated, same rule as NAP), financing partner logos (`financing_partners` field), and a media gallery (team/vehicle/before-after photos, video — keyed off an `assets` field). All are objectively true-or-false facts or literal file assets, so they're injected the same way NAP already is, for the same reason (a model risks describing/duplicating a badge instead of it just rendering).
- **Conditional "must contain" additions to existing model-written sections** (no renumbering, so nothing that references section numbers as IDs breaks): years in business (§1 Intro), per-line-item pricing (§5 Features & Benefits), a symptom/DIY comparison table (§6 Main Service Body), specific guarantee/warranty terms instead of vague framing (§8 CTA — Secondary), a tier/package comparison table (§9 Getting Started), and license number (§10 Geographic/NAP). Table content is called out explicitly as counting against each section's existing word budget, not additive.
- **Content Gaps "Always checked" expanded 3 → 10 categories** (years in business, license number, guarantee/warranty terms, pricing/price range, comparison-table source data, trust badges/affiliations, photo/video assets, alongside the existing response time / service area / certifications) — routes missing trust facts through the doc's existing `how_to_add` → "How to reach 100/100" UI panel with no new plumbing needed.
- **Cross-cutting requirement added:** trust signals (badges, rating, license, guarantee) must stay consistent with what's stated on the business's GBP/website — no page-specific embellishment, preventing city-page drift where one location page claims a guarantee/badge/license another doesn't have.

**Next step (not started):** implementing the actual generation-side support — new business-data fields (`certifications`/`affiliations`, `financing_partners`, `assets`), the deterministic injection logic for the new Trust & Proof block (mirroring how Contact & Find-Us is appended today), the comparison-table prompt guidance in §6/§9, and the 7 new Content Gaps categories in the writer's gap-detection prompt.

## ⏩ Update — 2026-08-29 · **DORA Slack app PROVISIONED — 3 creds set on PLATFORM; awaiting deploy-backlog drain for the end-to-end #dora test**

Follow-up to the DORA own-surface merge below ([#892](https://github.com/kssabraw/ar-tools/pull/892)). The owner created the **#dora** channel + a dedicated **DORA Slack app** (its own bot identity, **Socket Mode OFF** — confirmed) and handed over its three credentials; this session set them on the **PLATFORM** Railway service (env-level; secret values are not recorded here):
- `DIRECTOR_SLACK_BOT_TOKEN` (the DORA bot's `xoxb-…`)
- `DIRECTOR_SLACK_SIGNING_SECRET`
- `DIRECTOR_SLACK_CHANNEL` = `C0BTJB2F8M8` (#dora)

Env baseline re-verified on PLATFORM: `DIRECTOR_ENABLED` true; **`DIRECTOR_AUTONOMY_VETO_ENABLED` absent** (veto stays dark — deliberately untouched, per the locked framing). Because the three vars are **env-level**, **any** DORA-code deploy (`79e449c`/#892 or `eb728f9`/#895 — both carry the DORA surface) that reaches active will boot with the secrets injected; we don't have to wait for one specific deploy.

**Deploy state (~01:40 UTC):** Railway is slow-draining a large backlog of quick-succession merges (Everhour + docs PRs). The newest **SUCCESS** is still `60a8997` (#885 Director Phase 1, pre-DORA-surface), so `/director` + the DORA sidebar + `/slack/director/events` are **not active yet**. A FAILED build of the same `60a8997` died at `CREATE_CONTAINER` (a generic Railway infra hiccup, no code diagnosis) — **inert**, since the same commit succeeded in the serving deployment. Setting the vars queued a fresh `804a3532`/`eb728f9` deploy that will win to active via Railway's cancel-in-progress. **Did NOT force-accept** (needs owner OK; these are queued behind the builder, not `NEEDS_APPROVAL`).

**Verification split + open items** (nothing else is blocked on the owner until the deploy is active):
- **Deploy-active** — a DORA-code deploy (`79e449c` or later) becomes the SUCCESS serving deploy, booted healthy (`gsc_scheduler.started`, no `gsc_scheduler.step_failed step=director_reconcile`): **self check-in armed ~02:20 UTC** (re-arms itself if the backlog still hasn't drained).
- **Inbound #dora** — needs a **real human** message (a bot can't self-trigger). Once active, the **owner posts "where are we bottlenecked?" in #dora** → DORA replies in-thread under its own bot identity. If silent, the #1 cause is Socket Mode left ON; also grep PLATFORM deploy logs for `slack_director_events.hit` (expect `has_secret=true`, `director_enabled=true`).
- **Outbound** (`ops_seam`/`ops_digest` → #dora under the DORA bot) — confirmed at the **first daily reconcile** (~08:00 UTC, `gsc_ingest_hour_utc`): **self check-in armed ~08:20 UTC**. Expect one `ops_seam` (qa_idle — QA is armed-but-idle). A broken #dora (bot not invited) auto-falls-back to #pace (`channels_sent.slack="ok_master_fallback"`, the DB row unchanged).
- PR #895 (the prior docs follow-up) merged (`fd20e40`). This session's designated branch is `claude/dora-provisioning-verify-uhuipd`.

## ⏩ Update — 2026-08-29 · **DORA — Director of Operations gets its OWN surface (persona + /director page + #dora Slack app) — MERGED ([#892](https://github.com/kssabraw/ar-tools/pull/892), squash `79e449c`)**

**Status: merged to `main` with both CI gates green** (`pytest` platform-api suite + Netlify
preview). `main` auto-deploys to PLATFORM (`DIRECTOR_ENABLED` already true), so the `/director`
page + the DORA sidebar entry go live once that deploy is active (watch Railway status-lag —
trust deploy logs/DB, not list status). **The only owner step left is the DORA Slack app** (see
"Provisioning" below).

Owner ruling, mid-verify of the Director rollout: the Director of Operations should be its
own thing, not a lens you reach by asking SerMaStr. This **reverses the 2026-08-28 "surfaced
through SerMaStr, NOT a fifth persona" framing** (owner's call to make). Built additively — the
existing SerMaStr `_ctx_director`/portfolio lens stays; DORA is layered on top of the same
read-only `services/director/` read model (no new cross-agent logic).

Name: **DORA** — *Director of Operations, Reconciliation & Awareness* (owner-chosen).

What shipped (branch `claude/director-ops-phase1-verify-yuwn6h`):
- **Persona** `services/director_agent.py` — read-only, answer-only conversational wrapper over
  `read_model.build_read_model` (single Sonnet call, NO tools/actions/confirm machinery, unlike
  `pace_agent.py`). Portfolio + per-client scope; a deterministic no-LLM opening brief (the open
  seam flags). Conversation-persisted under a new `assistant_store` surface `"director"`.
- **Web page** `/director` — `routers/director.py` (`/director/chat` + SSE `/chat/stream` +
  `/conversations` CRUD + `/brief` + `/status`, gated on `director_enabled` → 503
  `director_not_enabled`), `pages/Director.tsx` + `components/DirectorChat.tsx` (indigo, Compass
  icon; a `PaceChat` clone minus confirm/pending), sidebar entry gated on `/director/status`.
- **Own Slack app** — outbound: `notifications.DIRECTOR_CHANNEL_KINDS`={ops_digest, ops_seam}
  route to `director_slack_channel` (#dora) under `director_bot_token()` when set; kept a subset
  of `PACE_CHANNEL_KINDS` so an unset DORA channel/token degrades to the PACE channel/bot (never
  the strategy channel). Inbound: `POST /slack/director/events` (fail-closed on
  `director_slack_signing_secret`, **Socket Mode OFF**) → `director_agent.handle_director_message`;
  the SerMaStr app steps out of #dora when the secret is set.
- Config: `director_model`/`director_max_tokens`/`director_slack_channel`/`director_slack_bot_token`/
  `director_slack_signing_secret`. Tests: `test_director_channel.py`, `test_director_agent.py`
  (+ existing notifications/assistant suites re-run green locally, 260 passed in the affected set).

**Provisioning left to the owner** (nothing blocks the web page): create #dora + a **DORA Slack
app** (its own bot token + signing secret; Event Request URL → `/slack/director/events`; **Socket
Mode OFF** — the PACE gotcha, or events never reach the endpoint), invite it to #dora, then set
`DIRECTOR_SLACK_CHANNEL` / `DIRECTOR_SLACK_BOT_TOKEN` / `DIRECTOR_SLACK_SIGNING_SECRET` on PLATFORM.
`DIRECTOR_ENABLED` is already true, so the /director page + sidebar entry light up as soon as the
post-merge deploy is active; the Slack side activates when those three vars are set. Until then,
DORA's seam flags + weekly ops digest fall back to the PACE channel (safe) and the /director web
page is the conversational surface.
## ⏩ Update — 2026-08-29 · **Everhour Phase 4 (consumers) BUILT + MERGED ([#899](https://github.com/kssabraw/ar-tools/pull/899), squash `c445f26`) — the integration is COMPLETE (Phases 0–4)**

The final phase — the consumers that turn the Phase-3 `time_entries` ledger + `tasks.actual_hours` into signal.
Built on branch `claude/everhour-phase-4-3u5vhu`, **merged to `main` green** (`platform-api tests` + Netlify preview
both passed on the code commit `b982de0`; `mergeable_state: clean`). Everything is additive + gated on `everhour_enabled`,
and every consumer degrades to today's `est_hours`-based behaviour when `actual_hours` is null (partial onboarding), so
the integration still ships **dark** until `EVERHOUR_API_KEY` + `everhour_enabled=true` are set on PLATFORM.

- **Three owner decisions confirmed before build (plan §9/§10):** (a) **margin shown side-by-side**, never switched —
  the conformance-tested `allocate()` is untouched; (b) **billing captured now, not split** — `list_team_time` now sends
  `opts_include_billing=1` so `time_entries.billable` populates from here on (it was always `None`), but nothing weights
  margin on it in v1; (c) ad-hoc/internal member time **counts** toward the utilization signal.
- **Read surface** (`services/everhour_sync.py` Phase-4 section + `routers/everhour.py` + `models/everhour.py`): pure
  `billable_split`/`build_client_time`/`utilization_hours` + windowed reads `client_time_summary`
  (→ `GET /clients/{id}/everhour/time`, the client "Time" card), `member_utilization` (team-wide {member_id: hours}),
  and `client_month_actual_hours` (the Recipe Engine's this-month labor input). Per-task actuals already ride on
  `tasks.actual_hours` (returned by the existing `.select("*")` board/detail reads — **no new endpoint**); per-member
  utilization is surfaced **through the workload report**, not a standalone endpoint.
- **Recipe Engine actual-margin** (`services/recipe_engine.py`): pure `actual_margin` + `build_actual_labor` (measured
  labor margin only when the new optional `everhour_loaded_hourly_cost` is set — else hours-only, never an invented
  dollar). `build_diagnosis` folds it into `signals["actual_labor"]` **best-effort — never touches `allocate`'s inputs**
  or the conformance-tested allocation.
- **PACE / workload** (`services/task_workload.py`): pure `attach_logged_hours` adds `logged_hours` + `utilization_pct`
  (vs pro-rated weekly capacity) to each `build_team_workload` member, gated; the estimate-based `open_hours`/`overloaded`
  verdict is untouched. `pm_signals.build_board_digest` embeds this report, so **PACE gets the signal with no change to
  `pm_signals.py`**.
- **Frontend:** `TaskDetail` actual-vs-estimate readout under Est. hours; a client-workspace `EverhourTimeCard`
  (`components/EverhourTimeCard.tsx`, dark until enabled + logged time exists); a Team-page per-member utilization line.
  New `lib/types.ts` fields (`actual_hours` on `TaskItem`, `EverhourClientTime`, `logged_hours`/`utilization_pct` on the
  workload member). Frontend `tsc -b` clean.
- **Config:** `everhour_loaded_hourly_cost` (0.0 = disabled, no invented cost), `everhour_client_time_window_days` (30),
  `everhour_utilization_window_days` (7). **No migration** — reads over the Phase-3 schema.
- **Tests:** new pure/flow units in `test_everhour_sync.py` (billable split, client-time assembly, utilization, month
  hours), `test_recipe_engine.py` (`actual_margin`/`build_actual_labor`), `test_task_manager.py` (`attach_logged_hours`
  additivity). Touched + consumer suites green locally (197 passed: everhour/recipe/task_manager/asana_workload/
  pm_signals/pace_agent/director_read_model).
- **Deferred (as agreed):** consuming `billable` in margin/reporting (captured, not split); a hardened per-member
  loaded-cost model (the `everhour_loaded_hourly_cost` scalar is a placeholder until per-member cost rates exist).

**The Everhour integration is now fully built (Phases 0–4), gated OFF.** Provisioning to go live (owner): set
`EVERHOUR_API_KEY` (Kyle's personal admin key) + `EVERHOUR_ENABLED=true` on PLATFORM, map each client's
`everhour_project_id` + roster `everhour_user_id`, then run the mirror backfill (`POST /everhour/backfill-mirror`).

## ⏩ Update — 2026-08-29 · **Everhour Phase 3 (time pull + rollups) BUILT + MERGED ([#896](https://github.com/kssabraw/ar-tools/pull/896), squash `9957a68`)**

Continuation of the Everhour entries below. Phase 3 is the **read side** — a daily whole-team time pull into a
new `time_entries` ledger, rolled up into `tasks.actual_hours`. Built on branch `claude/everhour-phase-3-time-pull-pvfdq7`,
**merged to `main` green** (`platform-api tests` on the code commit + Netlify preview; `mergeable_state: clean`).
Gated OFF (`everhour_enabled` default False).

- **Owner decision confirmed (plan §10):** ad-hoc / internal Everhour time (no native-task match, possibly no mapped
  project) → **member utilization only** — `time_entries.client_id` is **NULLABLE**; it's excluded from client/margin
  rollups (no client to bill it to) but still counts toward per-member hours. (Billable captured but unconsumed until
  Phase 4; a delete OLDER than the re-pull window is the one accepted residual gap — tunable via `everhour_sync_repull_days`.)
- **Migration `20260829140000` (applied live):** `tasks.actual_hours` (numeric, a derived recomputed rollup) + the
  **`time_entries`** table (keyed by `everhour_record_id` UNIQUE = the idempotency key; `client_id`/`member_id`/`task_id`
  all nullable FKs; `everhour_task_id` kept even when `task_id` is null for later re-join; `billable`/`comment` captured;
  indexes `(task_id)`/`(client_id,entry_date)`/`(member_id,entry_date)`; RLS on, service-role only). The `async_jobs`
  job_type CHECK widened to accept `everhour_sync` (rebuilt from the live constraint — the `everhour_mirror` list + the
  new value).
- **`services/everhour_service.py`:** `parse_time_record` now also surfaces `everhour_project_id` (first of the nested
  task's `projects`) — the fallback that resolves the client for ad-hoc time. Its exact-equality test was updated (+ the
  ad-hoc no-project case).
- **`services/everhour_sync.py` (Phase 3 half added):** pure `rollup_by_task`/`_client`/`_member` (shared `_rollup`,
  skips None keys/seconds) + `resolve_time_entries` (the join: a matched native task takes ITS client authoritatively;
  else the record's project→client; else None internal time; member via `everhour_user_id`) + `sync_window`.
  `run_everhour_sync` = paged whole-team pull over `[today − everhour_sync_repull_days, today]` → parse/validate →
  build the three lookup maps (chunked `.in_()` reads) → **upsert-by-`everhour_record_id`** (chunked) → recompute
  `actual_hours` for every touched task by re-summing ALL its `time_entries` (paged read, idempotent — never a delta).
  A **delete re-reads as `time: 0`** and zeroes the task's rollup — no reconciliation pass (plan §11.9).
  `enqueue_everhour_sync`/`enqueue_due_everhour_sync` (ONE whole-team job, deduped against an in-flight sync) +
  `run_everhour_sync_job`.
- **The READ gate is `everhour_enabled` only** — `sync_gate_open` deliberately does NOT require `everhour_mirror_enabled`
  (that sub-gate is write-only), so time can be pulled with the outbound mirror turned off during a read-first rollout.
- **Wiring:** `everhour_sync` dispatch in `job_worker.py`; `enqueue_due_everhour_sync` in the shared scheduler's daily
  block (self-gated, deduped; the daily durable marker covers once-per-day, so no separate date marker); manual admin
  `POST /everhour/sync` + `EverhourSyncResult` model (the on-demand trigger, the parallel of `.../asana/generate-month`).
- **Tests:** `tests/test_everhour_sync.py` grew the Phase-3 half — pure rollups/resolve/window, `sync_gate_open`
  (asserts reads ignore the mirror sub-gate), enqueue dedupe, and the full sync flow incl. the ad-hoc-no-task and
  delete-to-zero cases. **65 green** across `test_everhour_sync.py` + `test_everhour_service.py`. The fake Supabase
  gained `upsert`/`range` support (an upsert feeds reads so the recompute round-trips realistically).
- **Deliberately NOT in this PR (Phase 4):** the read endpoints for task/client/member actuals (they back the frontend
  surfaces, so they land with them — the pure `rollup_by_client`/`rollup_by_member` helpers are built + tested ready),
  the Recipe Engine actual-margin read, the PACE utilization consumer, and the frontend (task-drawer actual-vs-estimate,
  client "Time" card).

**Next: Phase 4** (consumers — Recipe Engine actual-margin, PACE per-member utilization, the read endpoints + frontend
surfaces). Nothing runs until `EVERHOUR_API_KEY` + `everhour_enabled=true` are set on PLATFORM (owner: Kyle's personal
admin key).

## ⏩ Update — 2026-08-29 · **Everhour Phase 2 (metadata-only task mirror) BUILT + MERGED ([#893](https://github.com/kssabraw/ar-tools/pull/893), squash `4ff5aed`)**

Continuation of the Everhour entries below. Phase 2 is the **task mirror (suite → Everhour, write, metadata-only)**:
give every native task a stable Everhour counterpart so time logged against it joins back to the exact `tasks`
row, without turning Everhour into a second task manager (locked decision #6 — name + optional assignee only).
Built on a fresh branch off `main` (`claude/everhour-time-tracking-9peruh`), **merged to `main` with both CI gates
green** (`platform-api tests` + Netlify preview). Gated OFF (`everhour_enabled` default False).

- **Migration `20260829130000` (applied live):** `tasks.everhour_task_id` (text, the opaque `"ev:…"` id) +
  `tasks.everhour_synced_at` (timestamptz, last successful mirror). A partial index `idx_tasks_everhour_unmirrored`
  supports the backfill scan. The `async_jobs` job_type CHECK widened to accept `everhour_mirror` (rebuilt from the
  live constraint — the score_external list + the new value). **`tasks.actual_hours` + `time_entries` are Phase 3,
  deliberately NOT added.**
- **`services/everhour_sync.py` (new):** the mirror. Pure `should_mirror` (top-level + client-scoped + unmirrored +
  live) and `mirror_user_id` (**gotcha #5** — casts the stored TEXT `everhour_user_id` to the `int` Everhour's
  `assignees[].userId` wants); `mirror_gate_open` (enabled + mirror sub-gate + configured); `enqueue_mirror`
  (best-effort, deduped against an in-flight job); async `mirror_task` (resolves the client's project + the assignee's
  Everhour id → `build_task_payload` → `create_task` → stamp the join key); `run_mirror_job` handler; `backfill_mirror`
  (enqueues one staggered `everhour_mirror` job per existing open, top-level, unmirrored task of a mapped client).
- **Design call — async, not inline** (plan §3 left it open): `task_service.create_task` is sync but called BOTH from
  threadpool routes AND directly on the event loop (`run_task_month_job` awaits the sync `generate_month_for_client`),
  so an inline `asyncio.run` of Everhour's async client would raise inside a running loop. A per-task `everhour_mirror`
  job is a plain sync insert that works from anywhere and gets the worker's retry/settle for free. The "task exists
  natively before its Everhour shadow" window is explicitly acceptable (no time can be logged in it anyway).
- **One funnel covers all of §3's hook points:** manual creation, the monthly generator, and every producer all pass
  through `task_service.create_task`, so `enqueue_mirror(created)` is hooked there once (best-effort, lazy import) —
  not in three places. Subtasks bypass it (they insert via `create_subtasks`) and are never mirrored (checklist
  markers, not billing targets).
- **Not freeze-gated (deliberate):** the mirror creates nothing in the suite and no client content — it mirrors an
  already-existing internal task's metadata outward. Freeze pauses content/link OUTPUT; internal PM task creation keeps
  running during a freeze (producers still open tasks). So `everhour_mirror` is NOT in `FREEZE_GATED_JOB_TYPES`.
- **Backfill endpoint:** `POST /everhour/backfill-mirror` (admin — the parallel of the Asana import). Fast (enqueues
  jobs; the outbound POSTs run staggered on the worker). Idempotent — re-running only picks up the unmirrored tail.
- **Tests:** `tests/test_everhour_sync.py` (pure helpers + gating + enqueue dedup/no-op + mirror success/skip/no-id +
  backfill) — 22 new, all green with the existing 24 `everhour_service` tests + 35 `test_task_manager`.
- **Config:** added `everhour_backfill_spacing_seconds` (1.0) for the backfill's rate-ceiling stagger (plan §11.7).

**Next: Phase 3** (time pull + rollups — `time_entries` table, the daily `everhour_sync` scheduled job over a rolling
re-pull window, `actual_hours`/per-client/per-member rollups). Then Phase 4 (Recipe Engine actual-margin + PACE
utilization consumers + frontend surfaces). **[Phase 3 now DONE — see the newer entry at the top of this file (#896).]**

## ⏩ Update — 2026-08-29 · **Everhour Phase 1 (identity/mapping) BUILT + MERGED (#890); Phase-0 gotcha doc reconciled with #888**

Continuation of the two Everhour entries below. This session was handed the merged PR #884 (Phase 0)
plus its adversarial review's still-unanswered open question ("fix the 4 bugs now, or defer?").

**The bug decision + merge.** The owner ruled **defer** — merge Phase 0 as-is and track the findings
as gotchas. So this session documented all 5 findings as a "Known Phase 0 code gotchas" table (plan
doc §12), resolved the `HANDOFF.md` conflict that had made #884 `dirty` (the Director #885 merge landed
after #884's base), and **merged PR #884 to `main`** (squash `0b074cc`). **Reconciliation note:** a
*parallel* session then fixed bugs 1–4 the same day in **[#888](https://github.com/kssabraw/ar-tools/pull/888)**
(the entry right below), so the "deferred" framing was superseded — plan doc §12 is now corrected to mark
bugs 1–4 **✅ fixed in #888** and keep only #5 (the `build_task_payload` int vs `parse_user` str assignee
cast) as an open **Phase-2** boundary note. Both accounts now agree.

**Phase 1 built + merged — [#890](https://github.com/kssabraw/ar-tools/pull/890) (squash `b465028`), on
branch `claude/everhour-integration-bugs-ws7iay`.** Migrations/identity/mapping per the plan's phasing:
- **Migration `20260829120000` (applied live):** `asana_team_members.everhour_user_id` (nullable text,
  a peer of `profile_id`) + `clients.everhour_project_id` (nullable text, mirrors `slack_channel_id`).
  **Re-checked the in-flight roster schema first** (the handoff warned about it): `asana_team_members`
  went through the Phase-2a identity migration — `id` is the PK now, `gid` nullable — so `everhour_user_id`
  went on as a plain additive peer, unaffected by that lineage. Verified both columns present live.
- **Backend:** `routers/everhour.py` + `models/everhour.py` — read-only pickers `GET /everhour/status`
  (`configured`/`enabled`), `/everhour/users`, `/everhour/projects`, each degrading to an empty picker
  when the key is absent (mirrors the Asana pickers, never 500s the UI). `everhour_user_id` threaded
  through `AsanaTeamMemberItem` / the `/asana/team-members` read / `partition_roster_write` (normalized
  to text, blank clears it). `everhour_project_id` on `ClientDetail`/`Create`/`Update` with the same
  explicit-set (empty clears) semantics as `slack_channel_id`. Registered in `main.py`.
- **Frontend:** the Team & capacity roster editor (`TeamWorkload.tsx`) gained an "Everhour user" column
  next to the Suite-user link; the client form (`ClientForm.tsx`) gained an "Everhour Project" field
  (a `/everhour/projects` picker when configured, else an id input). Both appear only once Everhour is
  `configured`; a stored-but-unknown id stays selectable so toggling the column never drops a link.
- **Tests/CI:** partition passthrough test (int→text, blank→None) + the existing 19/24 `everhour_service`
  tests; `platform-api tests` + Netlify preview both green; `tsc -b` + `vite build` clean.

**Provisioning ruling (owner, 2026-08-29): keep using Kyle's personal admin key** — no dedicated non-human
"Integration" Everhour user for now (recorded in plan §5/§8). Any admin-role key set as `EVERHOUR_API_KEY`
on PLATFORM works; the whole integration stays dormant until `everhour_enabled` is flipped on.

**Docs updated this pass:** `CLAUDE.md` Everhour bullet (Phases 0–1 complete, #888 fixes, the key ruling) +
its module-doc reference line; plan doc top status + §9 Phase 1 (→ COMPLETE) + §12 (→ #888-reconciled).

**Next: Phase 2** (the metadata-only task mirror — `tasks.everhour_task_id`/`_synced_at`, wired into
`task_monthly.py`/`task_producers.py`/`task_service.create_task` + a one-time backfill; remember gotcha #5's
`int(everhour_user_id)` cast when mirroring an assignee).

## ⏩ Update — 2026-08-29 · **Everhour Phase 0 — adversarial re-review + 4 fixes, follow-up to the merged PR #884**

PR #884 merged before its own adversarial code review's open question ("fix now or track as
known Phase 1+ gotchas?") got answered. Rather than leave verified, reproduced bugs sitting
in merged (if still `everhour_enabled=False`-gated, so currently inert) code, fixed all 4
findings in a same-day follow-up:

1. **`services/everhour_service.py::verify_api_key()`** — docstring claimed "Never raises,"
   but `except httpx.HTTPError` doesn't catch `json.JSONDecodeError` (a `ValueError`
   subclass) — a `200` with a malformed/non-JSON body raised straight through. Now catches
   `(httpx.HTTPError, ValueError)`.
2. **`scripts/verify_everhour_api_key.py`** — no handling for transport-level exceptions
   (timeout/DNS/connection-refused), only HTTP status codes, so a network failure crashed
   with a raw traceback instead of the intended `[FAIL]` diagnostic. Refactored around a new
   `_check()` helper (catches `httpx.RequestError` + malformed-JSON, prints one `[FAIL]` line,
   returns `None`) and switched to `with httpx.Client(...) as client:` so the client is always
   closed, on every exit path.
3. **`get_project()`** — docstring said it plays "the same role `asana_service.get_project`
   plays," but was missing that function's `or {}` fallback (re-read `asana_service.py:575`
   to confirm the discrepancy before fixing) — a `200` with a literal `null` body would have
   returned `None` from a function typed `-> dict`.
4. **`next_page()`** — crashed with `TypeError` on `limit=None`, and never terminated
   (returned non-`None` forever) on `limit=0`. Now guards `not limit or limit <= 0` first.

Each fix verified against the exact live repro that found it (re-ran all 4 after the fix,
confirmed the crash/hang no longer happens), plus 5 new regression tests (24 total in
`tests/test_everhour_service.py`, up from 19). `ruff`/`mypy`/`pytest` all clean. The CLI
script re-verified against both a bad key (still cleanly fails) and the real admin key (still
passes all 4 live checks — Kyle, 6 team members, 470 projects, 22 time records).

Branch `claude/everhour-time-tracking-me08ys` was reset onto the post-merge `main` (its own
PR history is closed) rather than stacked on the merged commits, per the "merged PR → fresh
branch off latest main" convention.

## ⏩ Update — 2026-08-29 · **Director of Operations — rollout verification in progress**

A verify session (00:22 UTC) checked the enablement against live state rather than list
status, per the Railway rule:
- **Env config confirmed:** `DIRECTOR_ENABLED` is set on PLATFORM; `DIRECTOR_AUTONOMY_VETO_ENABLED`
  is correctly **absent** (veto stays dark).
- **Deploy not yet active — queue still draining (not a failure):** the running PLATFORM
  code was still commit `144631d` (#883 Everhour docs, the last `SUCCESS`, 23:24 UTC) —
  **pre-Director**. The Director-code deploys (#885 `60a8997` + #886 docs `f515a88` on top)
  were `QUEUED`/`BUILDING`/`DEPLOYING` with **none booted** (no runtime logs yet); Railway
  will settle on the newest (`f515a88`). This is the documented status-lag/slow-drain, with
  ~7.5h of headroom before the 08:00 UTC first reconcile. No deploy was force-accepted
  (destructive — needs owner OK; the queue drains on its own).
- **No `ops_seam`/`ops_digest` notifications and no `director_seam` tasks yet — expected:**
  the daily reconcile fires once/day after 08:00 UTC and does **not** fire on redeploy;
  current time was 00:22 UTC.
- **Two self check-ins armed into the verify session:** ~03:04 UTC (confirm a Director
  commit reached active + `gsc_scheduler.started` + no `step_failed step=director_reconcile`)
  and ~08:59 UTC (confirm the first reconcile: the expected `qa_idle` → `ops_seam` to the
  PACE channel + in-app feed, no reconcile error; per-client `director_seam` tasks may be
  present or none). The prior session's ~09:15 UTC check-in fires into *that* session — both
  verify independently.

Still pending human sign-off after the first clean tick: calibrate the seam-day thresholds
from real data; keep `director_autonomy_veto_enabled` dark until autonomy content-gen runs
against more clients.

**Follow-up (00:29 UTC):** the owner asked to merge the verification note itself — PR
[kssabraw/ar-tools#887](https://github.com/kssabraw/ar-tools/pull/887) squash-merged to `main`
(`50a4540`; one merge-conflict resolution against #884 Everhour, keeping both top entries).
Re-checked live: the Director-code deploy **still had not gone active** — the running PLATFORM
code was still the pre-Director `144631d` (#883, last `SUCCESS`), with the #885 build still
`BUILDING`/`DEPLOYING` and a stack of docs/Everhour deploys (#884/#886/#887) queued behind it
(the #887 merge queued yet another). `ops_seam`/`director_seam` counts still 0 (expected,
pre-08:00 UTC). The two armed check-ins stand; no deploy force-accepted.

---

## ⏩ Update — 2026-08-29 · **Everhour time-tracking integration — blocker RESOLVED, Phase 0 COMPLETE (validated against a real key)**

Direct continuation of the entry just below. The owner used Claude in Chrome to fix the
root cause: the `ar-tools` Claude Code environment (`env_01CQmcKTLwnkKjFLW4ysuWWM`) had its
network egress policy set to **Trusted** (package registries only) — switched to **Custom**
with `api.everhour.com` / `developers.everhour.com` / `everhour.docs.apiary.io` allow-listed.
Verified live in-session (`curl` to all three now returns 200/308, no proxy rejection).

**Pulled the real API contract** from Everhour's published OpenAPI spec
(`https://developers.everhour.com/openapi.json` — 65 paths) rather than guessing: auth is
`X-Api-Key` (confirmed live — a bad key against `GET /users/me` returns exactly the documented
`403 {"code":403,"message":"Access denied"}`), team users at `GET /team/users`, projects at
`GET/POST /projects` (project ids are opaque `"as:..."`/`"ev:..."`-prefixed strings, not
numeric — `clients.everhour_project_id` must be `text`), tasks at
`POST /projects/{id}/tasks` (`assignees: [{userId}]` confirms the metadata-only mirror
shape), and — the important one — `GET /team/time` for the daily pull (`from`/`to`/`page`/
`limit`, max 50000/page, bare-array pagination with no total-count field, 100 req/10s rate
limit). The time-record `id` field is confirmed as the idempotency key. Bonus finding:
`DELETE /time/{id}` is documented as "set duration to zero," which means the existing
upsert-by-id design already handles staff deleting past entries correctly within the re-pull
window — no separate reconciliation pass needed (closes one of the handoff's open questions).
Full reference written into `docs/modules/everhour-time-tracking-integration-plan-v1_0.md`
§11 (rewritten from "verification needed" to "verified API reference").

**Phase 0 built** (`services/everhour_service.py`, mirrors `asana_service.py`'s shape): async
httpx wrapper (`get_current_user`/`verify_api_key`, `list_team_users`, `list_projects`/
`get_project`/`create_project`, `create_task`, `list_team_time`) + pure helpers
(`seconds_to_hours`, `build_task_payload` — name + optional assignee/description only, never
status/due-date, per the metadata-only-mirror decision — `parse_user`, `parse_project`,
`parse_time_record`, `is_valid_time_record`, `next_page` for the bare-array pagination). New
config block in `config.py` (`everhour_api_key`, `everhour_enabled` default False,
`everhour_mirror_enabled`, `everhour_sync_repull_days`=14, `everhour_sync_page_limit`=10000).
19 unit tests in `tests/test_everhour_service.py`, all green; `test_asana_service.py` (31
tests) confirmed unaffected. A standalone preflight script,
`scripts/verify_everhour_api_key.py` (mirrors `scripts/verify_gbp_api_access.py`), is ready
to run the moment a real key exists — smoke-tested this session against a deliberately bad
key and correctly reported the live `403`.

**Update, same session:** the owner supplied a real Everhour API key (an admin-role personal
key). Ran `scripts/verify_everhour_api_key.py` against it live — all four checks passed:
authenticated as an admin user (6-person team), 470 projects visible, 22 time records read
for today. **Phase 0 is now fully closed** — every endpoint shape matches production with no
surprises. The key was used transiently (env var / CLI arg only) and is not committed
anywhere. One provisioning note for Phase 1: Everhour has no separate service-account
concept (one key per user account), so using a real teammate's personal key works but ties
the integration's access to that person — worth minting a dedicated non-human "Integration"
Everhour user instead, flagged in the plan doc (§5) rather than decided.

**Also resolved in this push:** `main` advanced past this PR's base (PR #885, Director of
Operations Phase 1, merged) while this branch was open — both touched `HANDOFF.md` (this
file, both prepend at the top) and `config.py` (both append settings blocks, different
locations). Merged `origin/main` into the branch with a merge commit (no rebase — someone
else's history); `config.py` auto-merged cleanly, `HANDOFF.md` needed a one-line resolution
(both entries kept, mine first as newest). Full test suite (`test_everhour_service.py` +
`test_asana_service.py`, 50 tests) green post-merge.

Phases 1–4 (mapping/identity migrations, the task mirror, `time_entries` + rollups, Recipe
Engine/PACE consumers) are unstarted, per the plan doc's phasing — next up is Phase 1.

## ⏩ Update — 2026-08-29 · **Director of Operations — Phase 1 MERGED + ENABLED in production**

PR [kssabraw/ar-tools#885](https://github.com/kssabraw/ar-tools/pull/885) merged to `main`
(commit `60a8997`; CI green — pytest + Netlify preview). The owner then set
**`DIRECTOR_ENABLED=true`** on the PLATFORM Railway service, turning on the cross-agent
read model + the daily reconcile + the weekly ops digest. The code default stays `False`,
so a fresh environment still ships dark. **`DIRECTOR_AUTONOMY_VETO_ENABLED` is deliberately
left unset** (absent = `False`) — the autonomy pre-flight veto stays dark until autonomy
content-gen runs against more clients; it's an independent flag, so enabling the master
gate does NOT arm it.

**What to expect once the deploy is live (all read-only + reversible):**
- **First daily reconcile:** after `gsc_ingest_hour_utc`=08:00 UTC (first tick
  ~2026-08-29 08:00 UTC — today's daily marker had already advanced when the flag was
  flipped, so it doesn't fire on redeploy). Because **QA is armed-but-idle** (no task
  reaches In QA — the live gap the module was justified by), the reconcile is expected to
  trip **`qa_idle`** → one `ops_seam` notification (kind `ops_seam`, deduped per ISO week,
  title "QA idle — nothing has entered In QA in 7+ days") posted to the **PACE Slack
  channel** + the in-app feed. Any per-client seam that trips opens ONE `director_seam`
  board task in that client's current-month section (auto-closes when the seam clears);
  none tripping is a valid outcome.
- **First weekly ops digest:** Monday 2026-08-31 after 08:00 UTC (`director_digest_weekday`
  =0), **self-suppressed on an all-clear week**.

**Enable mechanics / gotcha:** setting the env var triggered a fresh PLATFORM deployment.
The merge-to-main push had also queued rebuilds of all four services, so Railway's status
API showed everything `BUILDING` for a while — but the PLATFORM image built from cache +
pushed in ~seconds (verified in the build logs). The lingering `BUILDING` status is the
documented Railway status-lag trap (CLAUDE.md "read the live config"), not a failure. The
healthy boot signal is `gsc_scheduler.started` in the PLATFORM deploy logs and no
`gsc_scheduler.step_failed step=director_reconcile`.

**Rollback:** delete/unset `DIRECTOR_ENABLED` (or set `false`) → redeploy → fully dark.
Everything the Director writes is reversible (trashable `director_seam` tasks + a deduped
notification); it never resolves, reassigns, or reorders anything.

**Open items (human):** (1) verify the first reconcile tick is clean once the deploy is
live (a self check-in is armed for ~09:15 UTC 2026-08-29 to auto-verify via Railway logs +
Supabase — `ops_seam` for `qa_idle`, no reconcile error); (2) calibrate the seam-day
thresholds from real data once flags accrue (`qa_idle` 7d / `strategist_approved_unplaced`
3d / `autonomy_proposed_unactioned` 7d); (3) optional owner sanity-check of the three spec
§15 defaults (Monday digest weekday, E2 gated on `pace_autoplace_producers`, `ops_digest`→
PACE channel — all resolved with the spec's suggested defaults). Phase 2 (B) and the
capacity arbiter stay trigger-gated per plan §8 — may never build, which is the intended
"build the eyes, defer the hands" outcome.

---


## ⏩ Update — 2026-08-28 · **Everhour time-tracking integration — full plan doc written, still BLOCKED on live API verification, no code**

Continuation of the prior session's handoff (`docs/modules/everhour-time-tracking-integration-handoff.md`).
Goal: staff keep tracking time in Everhour (extension/manual); it flows one-way INTO the
suite as `actual_hours` per native task + per-client + per-member, feeding real Recipe
Engine margin and PACE capacity instead of `est_hours` guesses. Project = client; the suite
mirrors native tasks → Everhour (metadata only, name/assignee) to create the join key —
time is still pull-only.

**Wrote `docs/modules/everhour-time-tracking-integration-plan-v1_0.md`** (full module plan,
same template as `asana-task-integration-plan-v1_0.md`): the 9 locked decisions (mirrors the
handoff's #1–#6, plus scheduler reuse / identity-join / gating), Feature A (thin task mirror,
suite→Everhour, metadata-only — hooked at `task_monthly.py`/`task_producers.py`/
`task_service.create_task` + a one-time backfill), Feature B (daily pull via the shared
`gsc_scheduler`, rolling re-pull window, upsert-by-Everhour-record-id into a new
`time_entries` table, recomputed rollups → `tasks.actual_hours` + per-client + per-member),
architecture/files, data model (`asana_team_members.everhour_user_id`,
`clients.everhour_project_id`, `tasks.everhour_task_id`/`_synced_at`/`actual_hours`,
`time_entries`), config, provisioning steps, phasing (0–4), and open questions.

**One correction to the prior handoff, caught while grounding the plan against the live
schema:** the handoff said `everhour_user_id` should sit "next to `profile_id` /
`slack_user_id`" on `asana_team_members` — `slack_user_id` actually lives on `profiles`
(migration `20260711210000`), not on the roster table. `everhour_user_id` is a peer of
`profile_id` only. Also confirmed the roster identity model has moved past what the handoff
cited: Phase 2a/2b (`20260828210000`/`220000`) already promoted `asana_team_members.id` to
the PK and dropped `tasks.assignee_gid` entirely — `everhour_user_id` joins on that `id`.

**Blocker re-verified, still standing:** `developers.everhour.com`, `everhour.docs.apiary.io`,
**and `api.everhour.com` itself** all fail the sandbox's egress proxy with `connect_rejected`
/ gateway 403 (org policy denial, confirmed via `__agentproxy/status`, not a transient
failure). The user's message this session named three unblock routes (allow-list the domain /
paste the docs / provide an API key to test live) but didn't actually pick one or paste
anything — flagged back to them that **a key alone won't unblock it**, since the proxy
currently rejects the `CONNECT` to `api.everhour.com` outright regardless of whether a valid
key is presented. Phase 0 (the `everhour_service.py` wrapper, validated against a real
key/response) cannot start until one of the three routes is actually resolved.

**Branch note:** developed on `claude/everhour-time-tracking-me08ys` (this session's
harness-designated branch), not `claude/everhour-project-management-6h1iuj` named in the
stale handoff-doc header — the handoff doc's own PR (#883) already merged to `main` before
this session started, and `claude/everhour-time-tracking-me08ys` is a fresh branch off that
merged `main`, so it already carries the handoff doc with no rebase needed.


## ⏩ Update — 2026-08-28 · **Director of Operations — Phase 1 (D) + Prerequisite E BUILT, PR #885 open (ships dark)**

Built the full Phase 1 scope from `docs/modules/director-of-operations-phase1-spec-v1_0.md`
(the prior entry below — read that first for the design authority + the owner's §11
decisions + the three grounded corrections that shaped this build). **Scope decision,
confirmed with the owner before writing code:** build the FULL spec as-is (E1 + E2 + D +
the weekly ops digest + the dark autonomy veto), not a trimmed-down MIN (E1 + `qa_idle`
alone) — because every piece ships behind its own flag defaulting off/False, so the
runtime-risk cost of the wider build is close to zero, and the owner's decisions 2
(weekly digest) and 4 (build the veto now) were already dated, explicit, deliberate
widenings of the plan's own minimalist lean, not something worth re-litigating.

**PR:** [kssabraw/ar-tools#885](https://github.com/kssabraw/ar-tools/pull/885) (draft,
branch `claude/director-operations-phase1-ycwhps`). CI (pytest + Netlify preview) run on
open; watched for the rest of the review cycle.

**E1 (fail-loud on unknown producer sources) + E2 (Recipe-Engine placement gap) — both
built exactly per the spec's corrected diagnosis:**
- **E1** — `services/director/providers.py::prov_producers` groups every open top-level
  task by `source`; anything outside `KNOWN_PRODUCER_SOURCES` (manual, monthly,
  asana_import, rank_drop, maps_alert, action_plan, content_run, scan_health, task_plan,
  strategy_proposal, director_seam) is counted into an `unwatched_seam` dict AND logged
  (`director.unwatched_source`) — never silently absorbed. `unwatched_seam` is itself one
  of the six seam predicates in `seams.py`, so a forgotten producer registration surfaces
  in both the SerMaStr context and the weekly digest.
- **E2** — `asana_push._push_task_plan_native` now calls `pm_assign.place_task(row["id"])`
  right after `task_service.create_task(...)`, gated on the pre-existing
  `pace_autoplace_producers` flag (default False, same flag `task_producers.py` and
  `push_proposal` already respect) and wrapped in the same best-effort
  try/except-log-never-raise shape `push_proposal` uses. `place_task`'s own guard ("never
  overwrite an existing assignment") means this can't disturb the name-match assignment
  that already runs — it only fills the gap when a task landed unassigned, recording the
  `placement_deferred` activity row that `strategist_approved_unplaced`-style
  observability depends on.

**The read model + reconciler — new package `services/director/` (7 files, ~1,300
lines):**
- `read_model.py` — `build_read_model(client_id: str | None, today) -> dict`. Portfolio
  (`client_id=None`) or single-client. Every one of the 8 providers below runs inside its
  own try/except (`director.provider_failed` on a catch), mirroring
  `slack_assistant/context.py::build_context`'s isolation contract exactly, so a broken
  module degrades the model to a gap and never breaks the read. `delivery` and
  `assignment` reuse ONE call to `pm_signals.build_board_digest` (the same read
  `pace_episodes`/`pace_digest` already share) instead of a fresh query; the rest
  batch-read once across the portfolio's client_ids and group in Python (the same pattern
  `build_portfolio_context`'s `_counts` helper already uses) rather than N+1 per client.
- `providers.py` — `prov_delivery`/`prov_assignment` (board state + open capacity holds,
  read from `task_activity.kind='placement_deferred'` joined to still-unassigned tasks),
  `prov_strategy` (the exact `not proposal.get("asana_task")` guard
  `routers/strategist.py:140` uses, aged from the review's `completed_at`/`created_at`),
  `prov_autonomy` (`autonomy_runs.decisions[]`, `outcome="propose"` and unexecuted, capped
  at `director_autonomy_ledger_lookback_runs`=8 runs per client), `prov_producers` (E1),
  `prov_interventions` (verdict mix + open rows), `prov_qa` (portfolio-only, per the
  plan's §2.3 correction — reads `task_activity` rows where
  `detail->>'to' == settings.qa_trigger_status` plus `qa_reviews` in the window),
  `prov_content` (a `module_outputs` writer row whose `module_version` ends
  `-degraded`/`-no-context`, or a Local SEO/Ecommerce page whose stored
  `voice_violations.passed is False`, within `director_content_degraded_lookback_days`=14
  — best-effort per table, a schema surprise degrades to an empty flag list not a crash),
  `prov_duplicates` (live tasks + open interventions grouped by a normalized
  `target->>'keyword'`/`->>'page_url'` key per client; ≥2 items with DIFFERENT `source`
  values on the same key = a flag).
- `seams.py` — pure, unit-tested predicates over the assembled model:
  `strategist_approved_unplaced`, `autonomy_proposed_unactioned`, `qa_idle` (portfolio
  ONLY — never blamed on a client), `content_shipped_degraded` (immediate, no dwell),
  `duplicate_target` (flag-only per decision 3), `unwatched_seam` (E1). Each resolves to
  `{seam, client_id, ident, evidence, since, threshold_days}` — evidence, never a verdict.
  `compute_flags` assembles all six into `model["flow"]`.
- `reconcile.py::run_daily(today)` — self-gated on `director_enabled`. For each
  newly-tripped per-client seam it opens ONE board task through the standard producer
  contract (`source="director_seam"`, `source_ref=f"{seam}:{client_id}:{ident}"`, lands in
  the current-month section like any other producer task) and auto-closes it via
  `task_service.close_task_by_source` the moment the seam stops firing (diffs the live
  flag set against currently-open `director_seam` tasks each run — idempotent by
  construction on the `(source, source_ref)` partial unique index). `duplicate_target`
  opens one task naming BOTH offending items (no merge). Portfolio `qa_idle` instead emits
  an `ops_seam` notification (`client_id=None`) since there's no client to file a task
  against.
- `digest.py::run_weekly(today)` — deterministic assembly, no LLM in v1 (a narrative pass
  is a deferred polish, never a source of fabricated numbers). Suppresses entirely
  (returns without emitting) on an all-clear week — zero seam flags AND zero autonomy
  activity — mirroring `pace_digest.run_daily_digest`'s `all_clear` short-circuit; this is
  the guard against the "weekly narrative is noisy" risk the plan flagged when it leaned
  toward riding the daily line instead. Enumerates named clients per seam (PACE's
  enumerate-don't-count rule), autonomy executed/proposed/escalated totals, and the top 5
  open capacity holds. `dedupe_key(today)` = `f"ops_digest:{iso_year}-W{iso_week:02d}"`
  (stable across a redeploy re-run).
- `veto.py::preflight_conflict(rec, client_id) -> bool` — fail-**open** by construction:
  any exception, or a candidate carrying no `keyword` (e.g. the free
  `rebuild_action_plan`), returns `False`. Joins the candidate's keyword against
  in-flight `async_jobs` (pending/running, matching payload keyword), live
  `tasks.target->>'keyword'`, and open (`verdict is null`) `interventions.target` for the
  client. Wired into `autonomy_executor.run_autonomy_for_client`'s act loop directly after
  the `AUTO_EXECUTE`/outcome gate and BEFORE `autonomy_budget.reserve` — a vetoed
  candidate never touches budget. Sets `outcome="propose"` + a `policy_reason`, the exact
  same shape as the pre-existing budget-refusal downgrade one line below it in the loop.
  Gated on `director_autonomy_veto_enabled` (default False) — independent of
  `director_enabled`, so flipping the master read-model gate on does NOT arm the veto.

**SerMaStr surface:** `_ctx_director(supabase, client_id, today)` registered in
`slack_assistant/context.py`'s `_CONTEXT_PROVIDERS` list (the only wiring change needed —
`build_context` picks it up automatically), returning per-client seam flags or `None` when
clean. `build_portfolio_context` gained a `director` block (agency-wide seam flags, for
"who's the bottleneck this week" / "show me every place two agents are acting on the same
target" with no client named) — isolated in its own try/except so a Director failure can't
break the rest of the portfolio snapshot. One new prompt block in
`slack_assistant/prompts.py`: the `director` context is read-only insight; SerMaStr may
*offer* to open a task or raise a proposal to PACE from it, but never silently acts on
delivery because of it — no authority over priority, scheduling, or which agent's
precedence engine wins.

**Scheduler wiring (`gsc_scheduler.py`):** `director_reconcile` runs daily right after
`pace_chase_plan`, inside the existing daily-cadence block (unconditional each tick, like
its siblings — no separate marker needed since it's naturally idempotent). The weekly
`ops_digest` block mirrors the `reopt_plans` weekly block exactly: weekday gate
(`director_digest_weekday`, default Monday) + `should_run` + marker-advance-only-on-
`_safe`-success (so a transient failure retries next tick, not next week), new marker key
`ops_digest_weekly`. `notifications.PACE_CHANNEL_KINDS` gained `ops_digest`/`ops_seam` so
both route to the master PACE channel via the existing `resolve_slack_channel` precedence
(no payload override needed, though `pace_slack_channel` is still passed through
`payload.slack_channel` for the digest, mirroring `pace_digest.py`'s own belt-and-braces
pattern).

**No migration.** Everything is computed on read or written through the existing
`tasks`/`notifications` producer contracts (`scheduler_state` carries the one new marker
key). A dedicated `director_seam_flags` table (durable flag history, resolve/ack, a UI) is
explicitly a Phase 2/B concern, per the plan's own graduation triggers — not built now.

**Config (`config.py`), all shipping at their dark/conservative default:**
`director_enabled=False` (master gate — read model + daily reconcile + weekly digest),
`director_digest_weekday=0` (Monday), `director_autonomy_veto_enabled=False` (independent
of the master gate), `director_seam_approved_unplaced_days=3`,
`director_seam_qa_idle_days=7`, `director_seam_autonomy_unactioned_days=7`,
`director_content_degraded_lookback_days=14`, `director_autonomy_ledger_lookback_runs=8`.

**Tests:** `test_director_seams.py` (each predicate: fires at threshold, silent below,
`qa_idle` portfolio-vs-per-client, `duplicate_target` shape, `compute_flags` assembly),
`test_director_providers.py` (the pure `_target_key` helper + `prov_producers`'s E1
unwatched-detection + `prov_qa`'s idle/entered logic against a fake Supabase),
`test_director_read_model.py` (provider isolation — a raising provider degrades the model
to a gap, never crashes the read — plus an end-to-end assertion that an unrecognized
`tasks.source` surfaces as `unwatched_seam` on the final assembled model, never silently
dropped), `test_director_veto.py` (every fail-open case + a wiring test proving the
downgrade to `outcome="propose"` happens BEFORE `autonomy_budget.reserve` is ever called,
and that disabling the flag lets execution through even when the predicate itself would
have vetoed), `test_director_digest.py` (dedupe_key stability across the same ISO week,
the all-clear suppression, enumerate-don't-count body formatting) — plus E2 coverage
folded into the existing `test_asana_push.py` (autoplace on/off, a placement failure
swallowed without failing the push). Full existing platform-api suite verified green
locally before opening the PR: **4528 passed**, 2 skipped, one pre-existing failure in
`test_fanout_llm_streaming.py` confirmed unrelated (an anthropic-SDK/httpx version
mismatch in the sandbox's installed packages — that file was never touched by this diff).

**Grounding note for whoever picks this up next:** a background research pass confirmed
several of the build spec's own cited line numbers had drifted slightly since it was
written (e.g. `asana_push.py:338-351` actually spans the function 306-374 with the
`create_task` call itself at 341-351; `context.py`'s provider naming convention is
`_ctx_<name>`, not the spec's `prov_<name>` — same contract, different name). None of
these affected the build; noted here so the next reader isn't confused finding the real
code at slightly different lines than the spec says.

**Next steps (not done here, left for the PR review cycle / a human before enabling):** a
live smoke test on Railway with `director_enabled` flipped in a non-prod check to watch one
real scheduler tick; then, only once real seam data exists, revisit whether the
conservative thresholds need recalibrating.

## ⏩ Update — 2026-08-28 · **Director of Operations (cross-agent orchestration) — plan + Phase 1 build spec MERGED to `main` (spec only, nothing built in code)**

Architecture review of "we have SerMaStr + PACE + QA + the task board — we need an
orchestrator making sure they work in concert," refined to wanting a **Director of
Operations for insight into how work flows.** Plan PR #879 (squash `7f6aea6`); Phase 1
build spec PR #882, both docs-only.

**Decision (locked; logged in `decisions.md`): build the eyes, defer the hands.** The
Director is a **read-only cross-agent read model + reconciler surfaced through SerMaStr**
— NOT a 5th persona, NOT a scheduling/priority authority. It never touches the three
tested precedence engines (`reopt_planner` tiers, `autonomy_policy.classify`, `pm_assign`
holds) — it escalates conflicts as proposals, never arbitrates. Capacity intake-arbitration
is deferred behind an observed trigger.

**Grounded findings:** no global cross-agent priority decider; no intake-time capacity
arbitration; no cross-agent health monitor. Incident record is thin — 2 real cross-agent
failures (neither an arbitration failure) + one live gap (QA armed-but-idle). The
strategist+autonomy+producer triple-collision has never occurred.

**Specs:** `docs/modules/director-of-operations-plan-v1_0.md` (the why) +
`docs/modules/director-of-operations-phase1-spec-v1_0.md` (the how — concrete Phase 1 (D)
+ Prerequisite E build spec, PR #882).

**§11 open questions RESOLVED (owner, 2026-08-28), folded into the build spec:** seam
thresholds = suggested defaults (`qa_idle` 7d · `strategist_approved_unplaced` 3d ·
`autonomy_proposed_unactioned` 7d · `content_shipped_degraded` immediate); a **separate
weekly** operations-flow digest (own scheduler weekday hook + all-clear suppression), NOT
a line on the daily PACE digest; duplicate-target = **flag-only** (no auto-merge yet); and
the **autonomy pre-flight veto built in Phase 1** (fail-open, ships dark behind
`director_autonomy_veto_enabled`). The last two deviate from the plan's leaning and widen
Phase 1 past the minimal D.

**Three grounded corrections to the plan (build spec §2):** (1) the Recipe-Engine gap is
**placement, not `source_ref`** — `_push_task_plan_native` (`asana_push.py:338-351`) does
stamp `source="task_plan"`/`source_ref`; it just skips `pm_assign.place_task`, so
`source_ref` is already uniform across every producer. Prerequisite E therefore reshapes to
**E1** (fail-loud on unknown producer `source`, mirroring `job_worker.py:994-1004`) + **E2**
(route monthly-plan tasks through `place_task`). (2) `duplicate_target` keys on
`tasks.target`, not `source_ref` equality (same `(source, source_ref)` is already
DB-prevented). (3) `qa_idle` reads `task_activity` and is agency-level.

**Still nothing built in code.** The build spec names the modules (`services/director/`),
seams, config keys, and tests; no migration (computed on read / existing contracts); every
piece ships behind its own flag (`director_enabled` master gate, default False). Next step
when picked up = write Phase 1 per the spec (E1 + `qa_idle` alone may correctly be the whole
build for a while). Deferred behind plan §8 triggers: capacity arbitration, duplicate
auto-merge, a distinct read-model subsystem.

## ⏩ Update — 2026-08-28 · **PACE Slack replies — mrkdwn formatting fix**

**PR #875 (merged to `main`, squash `21cc855`).** PACE's conversational Slack replies
(`services/pace_agent.py::interpret_pace`) were shipping as raw, unrendered Markdown in
`#pace` — `**bold**`, `##`/`###` headers, Markdown pipe tables, and `---` dividers all
showed up as literal punctuation, because Slack's own "mrkdwn" dialect doesn't understand
any of them. Root cause: PACE's system prompt (`_PACE_SYSTEM`) gave the LLM **no
formatting instructions at all**, so it defaulted to standard Markdown. SerMaStr already
solved this exact problem months earlier (`slack_assistant/prompts.py` — Slack mrkdwn by
default, standard Markdown only via `_WEB_STYLE` on the dashboard surface) — PACE even had
the identical `style="slack"|"web"` parameter plumbed end-to-end through
`interpret_pace`/`_answer`, it just never used it to change the prompt.

**Fix, in `services/pace_agent.py`:** an explicit FORMATTING block added to `_PACE_SYSTEM`
(Slack `*bold*` not `**bold**`, no `#` headers, no Markdown pipe tables — one bullet per
row instead since Slack renders neither tables nor `---`), plus a `_PACE_WEB_STYLE`
override (standard Markdown) appended only when `style == "web"`, mirroring SerMaStr's
pattern exactly. `style` is now actually wired into the prompt sent to the LLM.

**No migration, no config flag, no deploy gate** — this is a pure prompt-text change that
takes effect as soon as `PLATFORM` redeploys with the merged commit. The deterministic PACE
senders (`pace_digest.py`, `pace_proposals.py` / Chase Plan, `pace_briefs.py` morning
briefs, `pace_report.py` delivery reports) were already hand-built with correct `*bold*`
Slack syntax and needed no change — only PACE's LLM-generated conversational replies were
affected.

**Verified against three real PACE replies** before merging — two pulled from
`assistant_messages`, and one (the worst case: a full agency-wide status digest with 8
client overdue-task tables, ~58 tasks total) pasted straight from a live `#pace` thread.
All three confirmed the `FORMATTING` rule (bold/headers/tables/dividers, all generic) covers
the largest real message shape with no further changes needed.

**One thing the fix does *not* solve, by design:** Slack's `*bold*` has only one weight —
even after the fix, a top-level section title and a client-name subheading both render as
plain bold with no size hierarchy (`##` vs `###` had implied one, falsely). A true heading
look in Slack needs Block Kit rich-text blocks instead of a plain `text` message — a bigger
change, not attempted here.

## ⏩ Update — 2026-08-28 · **Intervention-outcome loop — v1, report-only, ENABLED in production + frontend card**

**PR #871 (backend) + PR #874 (frontend), both merged to `main`; `INTERVENTION_TRACKING_ENABLED=true` on PLATFORM (live).** The measurement half of SerMaStr's decide+assign flow: PR #862
closed *decide + assign* (monthly plan-review → human approve → PACE capacity-aware
assignment); this closes **"did it work"** — measure whether assigned link-building /
reoptimization work actually moved the campaign-goal metric it targeted, and surface a
per-tactic effectiveness rollup back to the strategist. **Report-only in v1** (the
strategist reads + cites it; it does NOT auto-adjust proposals). Full module detail is
in the CLAUDE.md "Intervention-outcome loop" entry.

### Enabled in production (2026-08-28)
**`INTERVENTION_TRACKING_ENABLED=true` is set on the PLATFORM Railway service** (deploy on
the merged commit succeeded — verified via Railway MCP). The registration hooks, the daily
`run_intervention_sync` sweep, and the `_prov_intervention_outcomes` digest provider are all
live. The **code default stays `False`** (config `intervention_tracking_enabled`), so a
fresh env still ships dark. No other env/setup — reuses the existing `async_jobs`/
`gsc_scheduler` infra and `campaign_goals` reads (no new paid calls, no LLM in the core).
**Accrual timeline:** interventions register on the next qualifying approval/task-done;
the per-client card + digest rollup stay empty until then; interim signals at ~2 weeks,
committed verdicts at ~6 weeks.

### What's live already
- **Migration `20260828240000_interventions.sql` applied live** (via Supabase MCP):
  the `interventions` ledger table + a nullable `tasks.target` jsonb carrier column.
  Verified (15 cols on `interventions`, `tasks.target` present).
- **Backend PR #871 + frontend PR #874 merged to `main`**, and the flag is flipped on
  PLATFORM — the loop is running in prod (no longer inert).

### Key files (for whoever picks this up)
- `services/interventions.py` — pure verdict/cadence/rollup helpers + registration
  hooks + the daily sweep.
- Registration: `routers/strategist.py` (proposal approval — runs on EVERY approve, so a
  transiently-failed first registration retries; idempotent per a shared `source_ref`) and
  the native-task done path — BOTH `task_service.complete_task` AND `update_task`'s
  drag-into-a-done-status branch (the board can PATCH status to done without hitting
  `/complete`). `asana_push.push_proposal` stamps `tasks.target`; `strategist.sanitize_review`
  passes the optional proposal `target` through.
- Surfacing: `strategy_digest._prov_intervention_outcomes` + one `strategist._SYSTEM` line;
  read API `GET /clients/{id}/interventions` (`routers/interventions.py`); **frontend
  `InterventionOutcomes` card** (`frontend/src/components/InterventionOutcomes.tsx`, PR #874)
  mounted in `ClientWorkspace` under the Strategist Review — per-tactic rollup + expandable
  per-intervention list, dark until the flag is on AND ≥1 intervention is registered.
- Tests: `tests/test_interventions.py` (pure logic + a drift guard pinning
  `strategist._INTERVENTION_TACTICS` to `interventions.TACTIC_TYPES`), target-passthrough
  cases in `tests/test_strategist.py`.
- **Adversarial-review hardening (folded in before merge):** the 6-week evaluator no longer
  fabricates `no_effect` for an unmeasurable target — a `None` verdict closes the row as
  `pending` (honest), never a false failure in the rollup. The daily sweep batch-loads the
  linked goals (no per-row N+1).

### Deliberately not built (v1 boundaries)
The strategist auto-adjusting proposals from effectiveness — the **next slice** (v2), and it
only becomes meaningful once verdicts accrue (~6 weeks after enablement). `applied_at` =
first-registration time (approval, in the common path) — measuring strictly from task-done
is a later refinement. (The frontend rollup surface — an earlier v1 boundary — is now built,
PR #874.)

## ⏩ Update — 2026-08-28 · **PACE — enabled in production + its own Slack bot**

**PACE is LIVE** (`PACE_ENABLED` + `PACE_INITIATIVE_ENABLED` = true on PLATFORM;
`PACE_SLACK_CHANNEL=C0BTJ9U5H5F` = the private `#pace` channel). PRs this session:
**#858** (route PM / native `task_*` notifications to the PACE channel), **#860**
(separate PACE Slack bot), **#861** (inbound diagnostic log), **#868** (Team-page
self-link), **#872** (per-client PACE channels — see below). First automated digest
+ Chase Plan fires the workday after enablement, after `gsc_ingest_hour_utc`
(**08:00 UTC**), delivered by the PACE bot in `#pace`.
Full module detail is in the CLAUDE.md PACE entry.

### Per-client PACE Slack channels (#872, draft)
PACE can now post a client's PM chatter to **that client's own Slack channel**
instead of only the master `#pace` channel. New nullable **`clients.slack_channel_id`**
(migration `20260828240000`, **applied live**), editable on the client form
("PACE Slack Channel" — accepts a channel id like `C0ABC123XY` or a `#name`).
Only the **client-scoped** PACE kinds route there — `task_assigned` /
`task_mention` / `task_comment` / `task_month_generated` / `task_nudge`
(`notifications.CLIENT_SCOPED_PACE_KINDS`). The portfolio rollups (daily digest,
Chase Plan, workload report, escalations) and the suite-wide `task_overload` /
`task_due` digests stay in the master channel. A client with **no channel set
falls back to the master channel**, so nothing is lost — the feature is inert
until a channel is set per-client. `resolve_slack_token` posts every PACE kind
under the PACE bot token, so **the PACE bot must be `/invite`d to each client
channel** you configure (same requirement as `#pace`) — but if it isn't (or the id
is wrong/archived), the message **retries on the master channel** rather than being
lost (recorded `channels_sent.slack="ok_master_fallback"` + a warning log), so a
misconfigured client channel degrades gracefully. Dispatch is also per-channel
idempotent (a reaper requeue never double-posts) and a PACE-only Slack setup (no
SerMaStr default channel) now delivers PACE kinds. Owner ruling: client-scoped
only + master fallback; splitting the digest/Chase Plan per-client is a deferred
follow-up.

### PACE has its own Slack app now (not SerMaStr) — App ID `A0BTJKE3BDX`
Config on PLATFORM: **`PACE_SLACK_BOT_TOKEN`** (`xoxb-…`) + **`PACE_SLACK_SIGNING_SECRET`**
(both set live). With both set: PACE posts under its own token (`notifications.pace_bot_token()`
+ `resolve_slack_token`), inbound events hit **`POST /slack/pace/events`** (verified with
the PACE signing secret), and the SerMaStr `/slack/events` handler **ignores `#pace`**
(no double-reply). Both empty ⇒ PACE falls back to the shared SerMaStr bot — the code is
inert until the vars are set.

### ⚠️⚠️ The setup gotcha that cost real debugging time: **DISABLE SOCKET MODE**
The #1 failure when wiring a Slack app to an HTTP Request URL. With **Socket Mode ON**,
Slack delivers every event over a WebSocket and **ignores your Request URL entirely** —
but the one-time `url_verification` challenge is a plain HTTP POST, so the URL still
shows **"Verified ✓"**. Symptom we hit: URL verified, events subscribed, `groups:history`
present, bot in the private channel, app reinstalled… and **zero events ever reached the
endpoint** (no logs, no reply). Fix: Slack app → **Settings → Socket Mode → OFF**, then
reinstall. The per-message **`slack_pace_events.hit`** log (#861) makes this diagnosable
next time — if it never appears in the PLATFORM logs when someone posts, Slack isn't
delivering (Socket Mode / subscription / reinstall), not our endpoint.

### Full setup runbook for the PACE Slack app (if re-doing it)
1. Create a Slack app named **PACE** (its own icon = the separate identity).
2. **Socket Mode → OFF** (do this first — see above).
3. **OAuth & Permissions → Bot Token Scopes:** `chat:write`, `channels:history`,
   **`groups:history`** (REQUIRED for private channels — public `channels:history` does
   NOT cover them), `im:history` + `im:write` (nudge/brief DMs). **Install to Workspace**
   → copy the `xoxb-…` Bot User OAuth Token.
4. **Basic Information → App Credentials → Signing Secret** → copy it.
5. **Event Subscriptions → Enable Events ON** → Request URL
   `https://platform-production-a5c5.up.railway.app/slack/pace/events` → verify →
   **Subscribe to bot events:** `message.channels`, `message.groups`, `message.im` →
   **Reinstall** if prompted (events don't deliver until you do).
6. In Slack, **`/invite` the PACE bot** to `#pace` (`C0BTJ9U5H5F`). Removing SerMaStr from
   that channel is optional (code already steps it out). *Redirect URLs / Interactivity
   are NOT needed — PACE confirms via plain-text "reply yes", no buttons/modals/shortcuts.*
7. Set `PACE_SLACK_BOT_TOKEN` + `PACE_SLACK_SIGNING_SECRET` on the PLATFORM Railway service.

### Team Slack linking (for nudges / morning DMs)
PACE routes personal DMs `member → profile → profiles.slack_user_id`. All three logins are
linked: Kyle `U0A6M999M1T`, Ryan `U02APLQCK6Z`, Minda `U05GC69MR4N`. Link on the **Team
page** (admin-only) → per-row **Link Slack**; get a member's id in Slack via avatar →
**Profile → ⋮ → Copy member ID** (`U…`). **#868** made that button appear on your **own**
row too (it was hidden for `isSelf`, so an admin previously couldn't self-link without a
DB edit; the backend `PATCH /users/{id}/slack-link` already allowed it).

## ⏩ Update — 2026-08-28 · **QA Agent — cut `needs_human` on machine work (auto-resolve deliverables + gate the paid visual check)**

**PR #870 (merged to `main` 2026-08-28; PRs 1–2, PR 3 parked).** Two improvements to reduce the QA Agent's `needs_human` rate and close more loops without a human. The deterministic verdict in `qa_signals.build_verdict` is **untouched**; everything is best-effort + fail-open.

- **PR 1 — auto-resolve suite-produced deliverables.** A VA no longer has to paste a `Deliverable links` subtask (URL) + target keyword for work the suite itself generated — those are already in our DB. `qa_service._suite_deliverable(task, rubric, keyword)` resolves them from the task's linkage **before** the paste convention: `website_page` → published `local_seo_pages`/`ecommerce_pages` (client_id + keyword → live `published_url`), then a Website-Builder page whose route slug carries the keyword; `gbp_posts` → the most-recent live `gbp_posts` copy; `content_run` → the run's keyword + live `published_url`. The selection is pure + unit-tested (`qa_signals.pick_published_page`/`pick_website_page`/`match_key`) and — critically — an **ambiguous** match (≥2 distinct live URLs) resolves to **nothing**, so QA never guesses a wrong page into a false FAIL. Readiness (`assess_readiness`, the drawer's "can QA run yet") reports the resolved URL/keyword/copy as auto-detected.
- **PR 2 — visual-check cost gate + nlp-score fold.** The paid DataForSEO `page_screenshot` + Claude vision call ran on **every** website_page review; now `qa_signals.should_run_visual` skips it when the FREE deterministic layers already vouch for the render (every checked asset loads AND structural fidelity ≥ `qa_structural_threshold + qa_visual_skip_structural_margin`). A skip is an **advisory** check, never a missing blocking one, so it can't create a `needs_human`. New config `qa_visual_skip_when_clean` (True) / `qa_visual_skip_structural_margin` (10). Also folds a suite page's already-computed nlp 8-engine `composite_score` (resolved in PR 1) into the review as the headline `composite` + an advisory `nlp_quality` check (guarded to the resolved suite page only).
- **PR 3 — auto-fix machine-generated fails — PARKED.** Recorded as an OPEN decision in the new root **`decisions.md`**. It would enqueue the existing reoptimize job (deficiencies from the failed checks) + re-QA on the autonomy rails instead of human `Rework:` subtasks — but a **"publish gap"** blocks the live-URL page rubrics: reoptimize updates the draft, and republishing to the live site QA checks is human (Tier-3, held), so only the blog rubric (reads the generated artifact) closes autonomously today. Locked sub-points: retry cap = 2; gate off by default + autonomy tier ≥ 2 + budget; human link-building stays Rework-only. **Not built** pending the owner's scope call (blog-only vs hybrid vs all-four).

**Efficiency follow-up (in the same PR):** the suite lookups are **lazy** — the DB queries fire only when the task lacks the link/copy, so a blog review never calls the resolver and a pasted-URL page review skips the local_seo/ecommerce/website queries entirely; the nlp fold is consequently scoped to a page the resolver produced (a pasted URL is never second-guessed with a DB-matched score). The `/qa` chat score line was relabeled `fidelity`→neutral `score`. Config additions in the `qa_*` block: `qa_visual_skip_when_clean`, `qa_visual_skip_structural_margin`. Tests: pure matcher + gate cases in `tests/test_qa_signals.py`; `_suite_deliverable` routing + `_website_page_checks` gate/fold + lazy-lookup wiring in `tests/test_qa_agent.py` (108 QA tests green; platform-api pytest gate green on the merge commit). **Nothing enabled by this PR** — the auto-resolve + gate are pure behaviour improvements to the existing (production-on) QA path; the LIVE-STATE caveat below (QA armed-but-idle until work is routed through **In QA**) is unchanged.

## ⏩ Update — 2026-08-28 · **QA Agent — "For QA" drawer button (activation gap closed)**

**PR #865 (merged to `main`, commit `5315266`).** Added a **For QA** button to the
task detail drawer (`frontend/src/components/tasks/TaskDetail.tsx`) — one click moves
a top-level task into the **In QA** status via the existing `patchField('status_key',
'in_qa')` path, which (with `QA_ENABLED` on) fires the automatic QA review through the
backend `on_task_status_change` hook. This is the direct fix for the "QA is enabled but
idle" gap below: the team now has a deliberate one-click way to send a finished
deliverable to QA without waiting on auto-advance Rule B (which never fires on the
imported process-marker checklists). Guards: shown only for **non-completed top-level**
tasks **not already in In QA**, and only when an active `in_qa` status exists on the
board; the move is audited in the activity feed like any other status edit. Frontend-only
change (typecheck clean; the Python test workflows don't gate it).

## ⏩ Update — 2026-08-28 · **QA Agent — ENABLED in production + business-name false-fail fixed**

The **QA Agent** (deliverable reviewer — full detail in the CLAUDE.md "QA Agent"
entry, `docs/modules/qa-agent-manual-v1_0.md`, and `docs/sops/QA_Checklists.md`)
was flipped **on in production**: `QA_ENABLED=true` set on the PLATFORM Railway
service (deploy `dc32f4d2` — SUCCESS). Both QA migrations are already applied live
(`qa_reviews` + the one-live-job-per-task unique index).

**PR #863 (merged):** fixed the one real defect an adversarial review found — the
now-blocking `client_name` website-page check required the client's **entire stored
name verbatim and contiguous**, which false-fails correct pages against the live
client names (`ABC Tree And Landscape Service` vs a page's "ABC Tree & Landscape";
`Southwestern Hearing Centers`; …). `qa_signals._name_present` now keeps an exact
fast path then falls back to distinctive-token matching (`&`↔`and`, corporate
suffixes dropped, reorder-tolerant); a genuinely wrong business still fails. A second
review finding (`internal_anchors` making the internal-link check near-always-pass)
was **deliberately NOT changed** — it's correct fail-open behavior and tightening it
reintroduces false-fails.

### ⚠️ The operational gap — QA is ENABLED but IDLE

Flipping the flag armed it; it is **not yet reviewing anything**, and won't until
the workflow feeds it. Confirmed from live data (2026-08-28):

- `NATIVE_TASKS_ENABLED` is **on** — the Asana→native task-board cutover happened
  ~2026-07-14 (last `asana_monthly` job 07-12; native `task_due_sweep` daily since
  07-14). So the native board IS the live system.
- **Zero tasks have ever entered the `in_qa` status** (`qa_reviews` total = 0). QA's
  auto-trigger fires on that transition, so it never runs. Two reasons: (1) nobody
  uses the **In QA** column manually; (2) the team's imported task checklists are all
  **process-markers** ("Citations QA'd", "Sent to client", "Added to deliverables
  sheet"), which `task_service.is_work_item` classifies as NOT work items — so the
  board's auto-advance-to-In-QA (Rule B, "last work item ticked → In QA") has nothing
  to fire on.

**To actually activate automatic QA (a workflow/process decision — no code):**
route finished work through the **In QA** column (the team already has a manual
"QA'd" step everywhere — that's the natural place), OR restructure the generated
checklists to contain real work-item subtasks so Rule B auto-advances. Meanwhile the
**"For QA" drawer button** (PR #865 — one click → In QA → automatic review), the
**Run QA button** (task drawer), and PACE's "run QA on X" all work on demand today.

**Conventions to socialize before automatic QA is useful** (else link-building
reviews return *needs-human*, which is harmless but unhelpful): a **`Deliverable
links` subtask** (paste the live URL / sheet link) on guest-post/niche-edit/citation/
PR/map-embed tasks, and a **`Live URL` column** in citation/PR Google Sheets (shared
"anyone with the link"). The **keyword** already lives in the task name, which QA reads.

**Recommended go-live sequence:** trial a few **Run QA** clicks on real deliverables
→ confirm verdicts look sane → tell the VAs to start using the In QA column. Tuning
(structural floor, citation sample, visual confidence) is all `qa_*` config, no code.

## ⏩ Update — 2026-08-28 · **SerMaStr monthly plan review → PACE assignment handoff (BUILT, ships dark)**

The flow the owner asked for: **once a month, a few days before task generation,
SerMaStr reviews the client's Recipe-Engine monthly task plan and proposes
additions/modifications; a human approves; PACE assigns each approved task to the
skilled, eligible, least-loaded member *under their weekly cap*.**

The **approval → capacity-aware assignment** half was already wired
(`asana_push.push_proposal` → `pm_assign.place_task`: creates the native task,
then places it, or holds it unassigned + flags `team_at_capacity` when the
eligible pool is full). So this build added only the **monthly cadence** that
feeds proposals into it:

- New strategist trigger **`monthly_plan_review`** (migration
  `20260828200000` widened the `strategy_reviews.trigger` CHECK; applied live).
  Behaves like every strategist run — **advice + proposals only**, human-gated,
  frozen clients get observation-only.
- **`strategist.enqueue_due_monthly_plan_reviews()`** — a daily due-check wired
  into `gsc_scheduler` that self-gates to the single day each month
  `strategist_monthly_plan_review_lead_days` (3) before `asana_month_generate_day`
  (pure `is_monthly_review_day`, month-boundary + short-month safe), enqueues one
  run per **non-archived retainer client** (`retainer_monthly > 0`), durable
  "already ran this month" guard (`clients_reviewed_within`), pilot allowlist via
  `strategist_monthly_plan_review_client_ids`.
- A `monthly_plan_review` **prompt orientation** (steers toward concrete,
  assignable task proposals within the plan's deployable budget) + its own
  notification title. The digest already carries the plan (`_prov_task_plan`).

**Double-gated / ships dark:** the whole cadence no-ops until BOTH
`strategist_enabled` (already **true** on PLATFORM) and
`strategist_monthly_plan_review_enabled` (default **False**) are on.

**To pilot on ONE client:** on PLATFORM set
`STRATEGIST_MONTHLY_PLAN_REVIEW_CLIENT_IDS=<client-uuid>` and
`STRATEGIST_MONTHLY_PLAN_REVIEW_ENABLED=true` (redeploy so the new container picks
up the vars — a running container predating the change won't have them). It fires
on the review day (default: 3 days before the 1st → ~the 29th). Verify: a
`monthly_plan_review` row in `strategy_reviews` + a "Monthly plan review" Slack
digest; approving a proposal creates the native task AND auto-places it (or holds
it flagged if everyone's capped). Remove the allowlist var to open it to the whole
book. Assignment respects caps only if team `weekly_hours` are set (Ivy 7, others
40 — already set).

## ⏩ Update — 2026-08-28 · **Native Task Manager cutover LIVE + scheduled Asana→native auto-import (PR #852, MERGED + LIVE)**

**The Asana replacement is cut over.** `NATIVE_TASKS_ENABLED=true` on PLATFORM,
confirmed live by a month of clean operation (`task_due_sweep` runs daily, native
monthly generation fired for all 9 clients on Aug 1, `asana_month_generate` is
dormant). The native board is the system of record; the suite no longer writes to
Asana. The profiles↔gid unification shipped in **#845** (Phase 1 additive + 2a
login-less-VA identity + 2b code) and the **Phase 2b migration**
(`20260828220000`) is applied — `tasks.assignee_gid` + `task_member_skills.member_gid`
dropped; every assignee is now the canonical roster-member `id` (verified: 1041
assignee_ids, 0 orphans).

**Scheduled Asana→native auto-import (PR #852, merged `616950b`, LIVE).** The team
is keeping Asana and migrating gradually, so people may still create/move tasks
*directly in Asana*. A daily job on the shared scheduler (`gsc_scheduler` daily
block, beside `task_due_sweep`) re-runs the idempotent Asana→native importer so
those changes flow into the native board automatically — no manual "Import Asana
boards" click. Engine: `services/task_import.py::enqueue_due_asana_import`.
- **Gated inert unless it should run:** `native_tasks_enabled` (native is the live
  board) AND `asana_auto_import_enabled` (default True) AND Asana configured
  (token + workspace) AND ≥1 `asana_client_projects` mapping. A fresh env does
  nothing; a rollback quiesces it; it **self-retires when Asana is cancelled**
  (remove `ASANA_TOKEN`).
- **Idempotent + guarded:** the import is `source='asana_import'` + gid gap-fill;
  the enqueue skips if a completed import ran within
  `asana_auto_import_interval_hours` (20) or one is already in flight, so a
  same-day scheduler re-fire can't double-import. Live smoke-tested 2026-08-28:
  ran across 9 clients, 0 errors, idempotent (0 new / 226 existing).
- **Kill switch:** `ASANA_AUTO_IMPORT_ENABLED=false`. Config:
  `asana_auto_import_enabled`, `asana_auto_import_interval_hours`. No migration.

**Still deferred (owner's timeline).** The two RETAINED Asana-path gid columns —
`asana_client_task_templates.assignee_gid` + `asana_client_projects.auto_assignee_gids`
— are kept (still dual-written) so a rollback to Asana-monthly generation stays
possible. Drop them (one small PR removing the writers + the staged SQL) only
after the Asana subscription is cancelled. Runbook:
`docs/modules/in-app-task-manager-gid-unification-cutover.md`.

## ⏩ Update — 2026-08-28 · **Action Plan detail pass + autonomy safe-slice pilot (MERGED + LIVE)**

Two threads this session, both on `services/reopt_planner.py` / the Action Plan.

**1 · Autonomy safe-slice — SerMaStr can now auto-commission ONE safe content type.**
PRs #827 → #830 → #832. `AUTO_EXECUTE` widened from `{rebuild_action_plan}` to
also include `generate_local_seo_page`, but **only** for a "Create page"
quick-win **whose keyword itself names a DataForSEO-resolvable city**
(`autonomy_executor._resolve_keyword_city` — longest trailing word-window that
exactly matches a real city via `locations_service.search_locations`,
fail-closed). This is Tier 2, so a client needs `autonomy_tier=2`. Live pilot on
**WheelHouse IT Fort Lauderdale** (tier 2): auto-committed one net-new
West Palm Beach Local SEO page draft ($1 reserved) + proposed 9 reoptimizes.
The **#827 first pilot failed** (`location_not_recognized`) because the executor
fed the client's *street address* as the generator's `location`; #830/#832 fixed
it to source the city from the keyword. **The lesson:** the Local SEO generator's
`location` must be a DataForSEO city name, never `clients.business_location`
(a free-form street address). `AUTONOMY_ENABLED=true` on PLATFORM.

**2 · Action Plan detail pass — every item now carries what you need to act.**
PRs #836/#838/#840/#841/#844, all merged + deployed. Driven by two coworker
questions ("why did I get a reoptimize for a keyword I'm #1 for?" and "it says
refresh the page but not which page"). What changed, all from already-loaded data
(no new paid calls):
- **#836** quick-win floor `STRIKING_DISTANCE_MIN=4`: a keyword you already rank
  **top-3** for is not a quick win (nothing to gain; reoptimising a #1 page is
  pure downside). 1–3 → no action, 4–20 → reoptimize, >20/unranked → create page.
- **#838/#840** existing-page actions name their page: hidden-win ranking `url`,
  quick-win reoptimize `url` (from `serp_snapshots.client_url`), cannibalization
  competing `pages` + canonical, content-gap `url`+`topics`, backlink-gap
  `target_link_count`+`target_domains` (from `domain_link_gaps`), rd-loss lost
  `target_domains`+count.
- **#841** create-page brief: winnable-keyword shows `search_volume`+`est_value`;
  maps weak-area shows `location` + how weak + a Google-Maps `url`.

**⚠️ The load-bearing gotcha (#844) — worth remembering.** These are STRUCTURED
fields on the action dict. `GET /action-plan` returns `ReoptPlan(**row)` under
`response_model=ReoptPlan`, and **Pydantic silently drops any key not declared on
`ReoptAction` (`models/reopt.py`)**. #838/#840/#841 added the fields to the dicts
and the frontend, but NOT to the model — so every structured field was stripped
before it reached the browser (the clickable links / chips / lists were dead
code; only the copies baked into `diagnosis`/`recommendation` text showed). The
DB-jsonb had them, which is why an early "verify" against Supabase looked fine —
**verify through the API response, not the stored row.** #844 declares all eight
fields + a model round-trip regression test. `ReoptAction`'s own
`assistant_action_id` comment had warned about exactly this.

Also in #844: `rankability.client_url` was derived from the per-result rows whose
query doesn't select `url` (always None) → now sourced from
`serp_snapshots.client_url`; plus hardening (cannibalization `... or 0` guards a
null-count `:,` TypeError, `search_volume` coerced to int, `target_domains`
deduped + capped).

## ⏩ Update — 2026-08-28 · **LeadOff — agency cost-to-win ROI replaces the $/review "ROI" (MERGED + LIVE)**

The market brief/board/tryout used to show **"ROI ($/mo per review)"** =
`exp_val / max(rev_win, 10)` — a value-per-effort ratio that **subtracts no
cost**, so a market read as cheap-to-win while being expensive. Owner ruling
(2026-08-28): make it a **real ROI** — expected monthly value vs. what the
**agency** pays to win and hold the ranking. Three PRs, all squash-merged to
`main` and live (the routes compute it on read; **no migration**):
**[#832](https://github.com/kssabraw/ar-tools/pull/832)** (the model + board/brief),
**[#834](https://github.com/kssabraw/ar-tools/pull/834)** (first-month 2× setup),
**[#835](https://github.com/kssabraw/ar-tools/pull/835)** (Tryout).

**The model** — `services/leadoff_roi.py` (pure `compute_roi` +
`estimate_ramp_months` + `estimate_maintenance` + `rd_gap_from_enrichment`;
impure `attach_roi`; unit-tested `tests/test_leadoff_roi.py`):

- **deliverables** = reviews-to-win × per-review + pages × per-page (+ RD gap ×
  per-link, **scouted markets only**). Unit prices come from the **Recipe Engine**
  catalog (`CONTENT_PAGE_COST` imported directly) so nothing is invented.
- **first-month setup surcharge** = (first_month_multiplier − 1) × monthly
  maintenance — the first month costs 2× (site build, initial citations, GBP
  config) the steady-state months.
- **ramp cost** = ramp_months × monthly maintenance — SEO doesn't rank instantly;
  you pay monthly labour through the climb before value arrives. This is what
  makes payback realistic (the first cut, with no ramp, gave a <1-month payback).
- **monthly profit** = expected $/mo − monthly maintenance (steady state).
- **payback (months)** = ramp_months + (deliverables + setup + ramp) ÷ monthly
  profit. `None` ⇒ never recoups (maintenance ≥ the market's value). Value is
  modelled as a step at end-of-ramp (conservative; a pre-client forecast).

**Everything slides per market on field difficulty** (Beatability — from
rev_win/holders/rating — preferred, win-likelihood `rankab` fallback, 0.5 ease
if neither):

- **ramp** between `leadoff_roi_ramp_min_months` (3, soft field) and
  `_max_months` (9, brutal), THEN adjusted by the review-velocity **momentum**
  (the "competition is still doing SEO" / moving-target factor, **scouted only**):
  accel ×`_ramp_accel_mult` (1.35), cooling/dead ×`_ramp_cooling_mult` (1.05 —
  even a cooling field is still building, so it mildly *extends*, not shortens).
- **maintenance** between `leadoff_roi_maint_min_month` (135, soft) and
  `_max_month` (600, brutal) — harder fields cost more to *hold*.

**Measured vs modelled** (carried as `roi_confidence`): the RD/link gap is only
captured on **scouted** markets (the brief, via `rd_gap_from_enrichment` on the
`enrichment.rd_med` ×10-true-RD field) → `measured`; **board-wide + tryout** have
no scouted RD → links omitted + flagged `modelled`. Same honesty split as the
rest of LeadOff.

**Wiring / surfaces:**
- `services/leadoff.py` — `attach_roi` over board rows (after `attach_beatability`,
  modelled) + on the brief (measured); new **`profit`/`payback` board sorts**
  (prefetch on `exp_val`, re-sorted in Python — no scanner column exists).
- `services/leadoff_actions.py::run_tryout_job` — Beatability + `attach_roi` on
  tryout rows before persist (best-effort; JSON `leadoff_tryouts.results`).
- `frontend/src/pages/LeadOff.tsx` — **Profit $/mo + Payback** columns (replacing
  ROI $/rev) on the board AND tryout tables, the two new sort options, a brief
  ROI block with the cost-to-win breakdown (reviews/pages/links/1st-mo setup/ramp)
  + measured/modelled note, CSV columns. The old `roi` field is kept for
  back-compat.

**Worked example (Little Rock water-damage, Beatability 71):** maintenance
~$212/mo, ramp ~4.7mo, first-month setup +$212, cost-to-win ~$1,388, monthly
profit ~$1,237, **payback ~5.8 months** — vs. the old nonsensical $/review 90.6.

**⚠ The unit-cost defaults are placeholders, not the agency's real economics** —
all config, tune without a rebuild: `leadoff_roi_cost_per_review` (10),
`_cost_per_link` (30), `_content_pages` (4), `_maint_min/max_month` (135/600),
`_ramp_min/max_months` (3/9), `_ramp_accel/cooling_mult` (1.35/1.05),
`_first_month_multiplier` (2.0), `_rd_target_mult` (1.0), `_enabled` (True).

**Gap-grows-during-the-ramp (BUILT — owner ruling 2026-08-28, Option B):** while
you close the review/RD gap, the incumbents keep building, so the **effective**
gap (and its cost) is larger than the static snapshot. `compute_roi` now inflates
the deliverable counts over the ramp horizon: **reviews** = `rev_win` +
review_rate × ramp, where the rate is the field's **measured** velocity on
scouted markets (`field_review_growth` = `field_vel30 / vel_matched` ≈ the #3's
monthly review gain) or a flat board default (`leadoff_roi_field_review_growth`,
2/mo); **RD** = the scouted RD gap × (1 + `leadoff_roi_rd_growth_pct_month` (0.055)
× ramp) — RD has no growth-rate data pre-client, so it's a flat %/month
assumption applied to the measured RD gap only (board/tryout have no RD gap → no
RD growth). Gated `leadoff_roi_gap_growth_enabled` (True). The cost breakdown
carries `reviews_growth`/`links_growth` and the brief annotates "+N during ramp".
**Note the deliberate compounding:** the momentum ramp-extension already
lengthens the *time* for an active field, and this adds *quantity* on top — an
accelerating field is penalised on both axes (owner accepted this). Little Rock:
+~9 reviews over the ramp ≈ +$94, a modest effect that grows in fast-moving
fields. **Still deferred:** swap in the real agency unit costs (the one change
that moves every number more than this refinement does).

---

## ⏩ Update — 2026-08-27 · **Website Builder — brand_service + hyper_local engines BUILT + generalized to service variations (MERGED)**

Tier A of the roadmap entry below is **done and on `main`**. Three PRs, all
squash-merged:

- **[#807](https://github.com/kssabraw/ar-tools/pull/807)** — the two Tier-A
  engines. `brand_service` (`/{service}/{brand}/`) + `hyper_local`
  (`/{city}/{service}/{subservice}/`) now generate through the **existing nlp
  writer** (`local_seo_service.generate_page`) — no new generator, just a
  `generation_inputs` branch each + both added to `NLP_PAGE_TYPES`.
  `brand_service` targets `"<Brand> <Service>"` geo-agnostically (city scopes the
  SERP only); `hyper_local` targets its need with the city as location and stays
  **engine-only** (SOP: escalation-only, never bulk-generated — the writer
  exists, the planner proposes none). `frontmatter_extra` fixed for
  `brand_service` (its service is `segs[0]`, the brand is `segs[-1]`).
- **[#810](https://github.com/kssabraw/ar-tools/pull/810)** — **generalized
  `brands` into service variations** so the auto-matrix works for any trade, not
  just equipment brands. A top-level service carries a `variations` list of
  `ServiceVariation{label, kind}` (`kind ∈ {brand, type}`);
  `service_variation_pages` emits **brand** → a brand × service page, **type** →
  a **sub-service** whose title is the label alone ("Oak Tree Removal", no "Oak
  Trees Tree Removal" doubling → `/tree-removal/oak-trees/`). `ServiceEntry.brands`
  is now a computed property; the store parser accepts both the new `variations`
  shape and the legacy `brands` field (→ `kind:"brand"`), so an older stored
  catalog keeps working and migrates forward on save. `variation_scale_gate`
  (>200 cells → acknowledgeable link-equity sign-off). Frontend: the Plan tab's
  brands input became a per-service **"Service variations"** editor (label +
  Type/Brand kind), normalizing legacy `brands` on load.
- **[#815](https://github.com/kssabraw/ar-tools/pull/815)** — the team user guide
  (`docs/website-builder-user-guide.md`) documents Service variations.
- **[#819](https://github.com/kssabraw/ar-tools/pull/819)** — adversarial-review
  fixes: (a) the store parser mirrors the frontend's "variations wins" rule —
  legacy `brands` are read ONLY when the `variations` key is absent (presence of
  the key, even `[]`, means the catalog is migrated), so the two can't double up
  server-side; (b) a synthetic `type`-variation's generation keyword is scoped by
  its parent service (`generation_inputs` → "Emergency AC Repair"), skipping the
  join when the service name is already in the label — so a bare label like
  "Emergency" on two services no longer generates identical keyword+location
  pages; the page TITLE stays bare and real catalog sub-services are unchanged.
  (Also caught a process gotcha worth repeating: `git checkout main` had landed
  on a **stale local `main`** and silently reverted the working tree to
  pre-change files — always `git reset --hard origin/main` before reviewing
  merged work.)

**Verification pattern held:** built BOTH `/ac-repair/carrier/` (brand) and
`/tree-removal/oak-trees/` (type → sub-service, clean "Oak Trees" title) in
`site-template`; 280 website unit tests pass; CI green (pytest + Netlify) on
#807 and #810. No template change for the generalization — `type` variations are
standard `sub_service` pages the template already renders (the synthetic
sub-service's keyword falls back to the page title). **What's left of the
roadmap:** only Tier B (the ⭐ extension types — cost/problem-symptom/FAQ/
projects/comparison), which still need both a template screen AND an engine; see
the entry below.

---

## ⏩ Update — 2026-08-27 · **Website Builder — future page-type engines (ROADMAP; Tier A now built above)**

**Why this entry exists.** The generation layer routes every planned page to
whichever suite writer owns its type (`website_generate.generation_inputs` →
`nlp` / `run` / `core_pages` / `template`). A handful of **reference page types
have no writer engine yet**: the planner is wired to *detect* them and record
`engine: None` (surfaced as `engine_unavailable:<type>` / the
`template_coverage_gate`) rather than fake them. **In practice today the planner
emits none of these**, so every currently-plannable page has a writer or renders
from data — this is a forward roadmap, not a live gap.

**The types, in two tiers (source of truth: `services/website_plan.py`
`NLP_PAGE_TYPES`, `services/website_content.py`
`_COLLECTION_BY_PAGE_TYPE`/`UNRENDERABLE_PAGE_TYPES`, `site-template`
`content.config.ts`):**

- **Tier A — template exists, only a writer engine is missing. ✅ BUILT (#807 +
  #810, see the entry above).**
  - **`brand_service`** (brand × service, e.g. `/ac-repair/carrier/`) — collection `services`.
  - **`hyper_local`** (a hyper-specific service×place page) — collection `local-landing`.
- **Tier B — ⭐ extension types with ratified URLs but NO template AND no engine.**
  `UNRENDERABLE_PAGE_TYPES` is an intentionally-empty frozenset today; the first
  plan that proposes one trips `template_coverage_gate` (blocking-but-
  acknowledgeable). Each needs **both** a new template screen (added in Claude
  Design + compiled, or mapped onto an existing collection) **and** a writer
  engine:
  - **cost / pricing**
  - **problem / symptom**
  - **standalone FAQ**
  - **projects** (portfolio / case-study)
  - **comparison** (X vs Y)

**What "add an engine" concretely means** (per type): (1) add the type to
`NLP_PAGE_TYPES` or give it a branch in `generation_inputs` returning a real
`engine` + keyword/location; (2) for Tier B, add its template screen +
`_COLLECTION_BY_PAGE_TYPE` mapping and remove it from `UNRENDERABLE_PAGE_TYPES`;
(3) point it at a writer — most reuse `local_seo_service.generate_page` with a
tuned prompt, `comparison`/`cost` may be better as a `run`-engine blog variant;
(4) teach the planner to actually EMIT it (an emitter in `website_plan.py`), since
today none are proposed.

**Also thin-but-not-broken (no roadmap action needed):** `blog_archive`,
`sitemap`, `services_index`, `areas_we_serve` are `template`-engine — they render
from the published-pages query with **no body writer**. Reference "Writer #6"
would add narrative depth to the two index hubs; until then they ship as accurate
hubs, not broken pages.

---

## ⏩ Update — 2026-08-27 · **Website Builder content creator — ALL MERGED + LIVE, frontend UI shipped, user guide added**

Everything the two sections below describe is now **merged to `main` and live in
production**. The "nothing is merged yet" / "frontend UI not built" caveats in
the 2026-08-26 (pm) entry are **superseded by this one** — read this first.

**What merged (all squash-merged to `main`):**
- **[#740](https://github.com/kssabraw/ar-tools/pull/740)** — the backend +
  template: content_plan model, post/pillar planner, `run` engine, effective-
  frontmatter publish gate, seed bridges (strategist + Fanout), the drip-release
  schedule (`website_releases`, migration `20260826140000`, applied live), and
  the cross-family fix (a local site's `/blog/` is planned + dripped alongside
  its geo pages).
- **[#796](https://github.com/kssabraw/ar-tools/pull/796)** — the **frontend UI**
  the #740 entry lists as "NOT built": `ContentPlanEditor.tsx` (Plan tab, **every
  site type**) with the two one-click **seed buttons** (strategist / Fanout
  session id) + `ScheduleTab.tsx` (the drip-release schedule) + PlanTab gating
  the service/city "Build plan" cards to **geo sites only** while the blog
  content-plan editor shows for all. So the whole feature is now editable in-app.
- **[#800](https://github.com/kssabraw/ar-tools/pull/800)** — a **team-facing
  user guide**, `docs/website-builder-user-guide.md`: a no-code, dashboard-only
  tutorial of the full lifecycle (create → provision → theme → plan (services/
  cities + the blog content plan) → approve → generate/publish → drip-release →
  deploys → settings), with a quick-reference table and an FAQ whose first entry
  answers the recurring "my local site's plan shows no blog posts" question (the
  blog is driven by the Blog content plan editor, which starts empty).
- **[#801](https://github.com/kssabraw/ar-tools/pull/801)** — CLAUDE.md now
  references the user guide and records the frontend UI as built.

**Production flag flipped ON (owner asked 2026-08-27):** `WEBSITE_BUILDER_ENABLED=true`
on the PLATFORM Railway service. **Railway gotcha that cost time:** `set-variables`
**staged** the value but did **not** roll a fresh container (the running deployment
kept serving the old value — confirmed by the container timestamp in logs
being unchanged after the variable write). A **`redeploy`** was what actually
applied it. `WEBSITE_IMAGES_ENABLED` was **deliberately left off** — it bills a
per-page image render, flip it separately when hero images are wanted. Both
Netlify (frontend) and PLATFORM (backend) are deployed; the **Website Builder
card** now appears on the client workspace (gated on `GET /websites/status`,
which the restarted container returns `{enabled:true}` for; TanStack caches it
~5 min, so a hard refresh surfaces it).

**Where to use it:** client workspace → **Website Builder** card (route
`clients/:id/website`), or the sidebar **Websites** fleet view (`/websites`).
The blog on a local site lives behind the **Blog content plan** editor on the
**Plan** tab (below Service catalog / Cities) — empty by default, which is why a
fresh local site's plan shows only service/city/matrix pages until you add silos
+ posts (or seed them) and Save.

---

## ⏩ Update — 2026-08-26 (pm) · **Website Builder — informational content creator + drip-publish release schedule BUILT (PR #740)**

> **Superseded by the 2026-08-27 entry above** — #740 (and the frontend, user
> guide, and flag-on that followed) are all merged and live now. Kept for the
> build detail; ignore its "nothing is merged yet" / "frontend UI not built"
> caveats.

The gap mapped in the section below is **built**. PR
[#740](https://github.com/kssabraw/ar-tools/pull/740) (draft, green CI,
`mergeable_state: clean`) is on branch
`claude/website-builder-content-creator-70iu8b`. Nothing is merged yet — it is
ready for the owner to review/merge. What follows is the "so the next chat
doesn't re-derive it" summary; CLAUDE.md's Website Builder bullet carries the
durable version.

### The decision that was surfaced first (owner-confirmed)

**Who owns an informational site's cluster inventory?** Confirmed: the **Website
Builder owns it** in `websites.config.content_plan` — editable, durable across a
re-research, reviewed/approved through the same plan flow as the geo matrix —
rather than reading a research run at build time. A **one-shot seed bridge**
copies a research plan in once; after that it is the site's own data. This keeps
informational sites inside the existing plan → approve → generate → publish
machinery instead of coupling site structure to a research run.

### What was built (5 commits on the branch)

1. **The five planning/generation pieces** (`website_plan.py`,
   `website_content.py`, `website_generate.py`, `website_publish.py`): the
   `content_plan` model (`PostEntry`/`PillarEntry`), posts at `/blog/{slug}/`, a
   **pillar/hub** at top-level `/{topic-slug}/` once a silo has ≥5 **evergreen**
   posts (`news` excluded), a **`run` engine** (a blog Writer run whose angle
   rides on `writer_notes`, linked back `content_source="run"`), the effective-
   frontmatter publish gate + first-paragraph meta description. **No migration**
   — reuses the `website_page_generate` job, `content_source='run'`, and the
   free-text `page_type` column.
2. **Template** (`site-template`): a `pillars` collection + top-level route via
   `[...path]`, pillars surfaced on home/nav/sitemap. Verified by **building both
   site types** (the rule that keeps earning its keep).
3. **Strategist seed bridge** — `import_from_strategist` maps the client's latest
   `keyword_topic_strategist` plan into `content_plan`.
4. **Fanout seed bridge** — `import_from_fanout(session_id)` maps a finished
   Topic Fanout session's silos/clusters in. **Owner ruling: OPTION 1, always
   regenerate fresh** — copies only the topics/keywords, never links the
   session's already-generated articles.
5. **Release (drip-publish) schedule** (`website_release.py` + `website_releases`
   table + `website_pages.released_at`, migration `20260826140000` applied live)
   — publish an immediate batch, then N per **day/week/month**. **Owner ruling:
   generate + publish on the drip** (Fanout-style, just-in-time), via a
   `publish_after` flag on the existing generate job — **no new job type**.
6. **Cross-family fix** (owner caught it): blog posts are planned for **every**
   site type, so a **local SEO site's `/blog/` is filled from its content plan**
   alongside its service/location pages, and the release schedule drips **both**
   its geo pages and its blog (acts on `NLP_PAGE_TYPES ∪ RUN_PAGE_TYPES`).

### What is NOT built (deliberate follow-ups)

- **Frontend UI** for the content plan, the two seed buttons, and the release
  schedule — backend + template only, consistent with the module's build so far.
- **Local-site pillar hubs** are reachable (home Guides grid + sitemap + own URL
  + they link down to posts) but a **post→pillar up-link** and **pillar-in-local-
  nav** are not wired.
- Local geo pages already drip; a per-page-type immediate-vs-drip split beyond
  ordering is not built.

### Verification rule that keeps earning its keep

Still true, and used again this pass: **build both site types in `site-template`**,
not just the unit tests. The local-with-a-blog build (geo pages + posts + a
pillar, 14 pages, no namespace conflict) is what confirmed the cross-family fix.

---

## ⏩ Update — 2026-08-26 · **The Apps Script publish webhook: which project, which deployment, and how to redeploy it**

**Why this entry exists.** Closing out the deploy-safety work needed one webhook
change, and finding *which script to edit* took longer than writing the change.
Nothing recorded the project name or the deployment id — only "the 2026-07-07
deployment". Two traps cost the time; both are written down here so they cost it
once.

**The live webhook.** Apps Script project **"AR Tools Google Docs Webhook"**,
script id `1EoBPm2VqU-GlloClByKq6BVqIs9-6AsZVbraw9DahEG_1NBBmHSiduep`
(https://script.google.com/d/1EoBPm2VqU-GlloClByKq6BVqIs9-6AsZVbraw9DahEG_1NBBmHSiduep/edit).
Source of truth in-repo: `writer/apps-script/publish_webhook.gs`. It serves the
doc / `type:"sheet"` / `type:"pdf"` branches, `share`, `format:"html"`, image
embedding, and (2026-08-26) `dedupe_by_name`.

**Trap 1 — the decoy project.** A second project, **"AR Tools Publisher"**
(created 2026-05-01, untouched since), is the *original markdown-only* script:
no `sheet`, no `pdf`, no `share`, no `format`. It is NOT the webhook. Editing it
changes nothing, and because it looks plausible it is the one you find first.
Consider renaming it `AR Tools Publisher (OLD — unused)`.

*How it was ruled out, if you ever need to redo this:* `upload_pdf` hard-fails
with `pdf_not_supported` unless the webhook returns a `file_id`, and the decoy
has no `pdf` branch — yet 20 of 26 `client_reports` rows carry successful Drive
delivery. So the live script could not be that one. The definitive check is
comparing a deployment's exec URL against `GOOGLE_APPS_SCRIPT_URL` on the
PLATFORM Railway service.

**Trap 2 — two active deployments.** The real project has two, differing only
after `/macros/s/`:

| Prefix | Was | Now |
|---|---|---|
| `AKfycbxTjwbZYB…` | Version 8 (Jul 6) — **PRIMARY: the one `GOOGLE_APPS_SCRIPT_URL` points at** | Version 10 |
| `AKfycbyfvDYYs…` | Version 1 (Jun 27) | Version 9 |

**Resolved 2026-08-26:** `GOOGLE_APPS_SCRIPT_URL` holds the
`AKfycbxTjwbZYB…` / Version 10 deployment — verified by revealing the value in
the Railway **dashboard** and full-string-matching it against the deployment id
(not just the prefix). Both deployments' descriptions now say which is which.
Note the value is readable ONLY in the dashboard: every API client (the Railway
MCP, an OAuth app) gets variable names with values redacted, which is what made
this take two attempts to settle.

Even so, **bumping BOTH on a redeploy stays the default** — webhook changes here
are additive and opt-in, so it is free insurance against this drifting again.

**Redeploy procedure.** Edit the code → save → **Deploy → Manage deployments →
pencil icon → Version: "New version" → Deploy**. ⚠️ **Never "New deployment"** —
that mints a *different* exec URL while `GOOGLE_APPS_SCRIPT_URL` keeps pointing
at the old one, so prod silently keeps running the old code with no error
anywhere. Authorization is only re-prompted when a change introduces a NEW
Google service (Sheets, UrlFetchApp did; `dedupe_by_name` did not — it reuses
`DriveApp`). If you drive this UI with a browser agent: the pencil icon
silently swallows clicks while the Manage-deployments dialog is still animating
open, and the dialog settles at two different sizes depending on timing — wait
for each control's position to stop moving before clicking, or the early clicks
land on nothing.

**Deployment labels vanish on every redeploy — this is expected.** The name shown
in the Manage-deployments list is just a mirror of the deployment's Description,
and **cutting a new version resets it to "Untitled"**. That is why the 2026-08-26
redeploy appeared to wipe the "AR Tools Google Docs Webhook" label, and it cost
confusion twice in one session. Two consequences: (1) after any redeploy, expect
to re-enter the descriptions; (2) **always identify a deployment by its version
number or its `AKfyc…` deployment ID, never by the list label** — the label may
be blank, stale, or duplicated across both. Editing a description alone does NOT
cut a version (verified: the list still topped out at Version 10 afterwards).

**Verifying a deploy landed.** Two options, in order of convenience:
1. Read the project source back through Drive (`download_file_content` with
   `exportMimeType: application/vnd.google-apps.script+json`) and confirm the
   code is present — this is how the 2026-08-26 change was verified, and it
   works from an agent session.
2. Exercise it: POST the same `{folder_id, title, …, dedupe_by_name: true}`
   twice against a scratch folder; the second reply should carry the SAME id
   plus `"reused": true`. **Note the sandbox cannot do this** — the agent proxy
   denies `script.google.com` (403 on CONNECT), so run it from a real terminal.

**Current state.** Both deployments serve the 2026-08-26 code; the syndication
duplicate-Doc guard (PR #758) is live. The un-run item is option 2 above — a
live round-trip test, which only matters on a retry path and is not blocking.

## ⏩ Update — 2026-08-26 · **Brand-voice QA: the judge was too generous — hardened the scoring rubric across both writers + turned on nlp/pipeline CI**

**Problem.** The separate brand-voice scorecard (the 8-dimension LLM judge, not
the deterministic checks) was scoring off-brand pages "fine." Pulled the real
distribution from `<page>.voice_violations` to confirm — across **all 17 pages
scored since the voice system shipped 2026-07-31** (the other 200 are pre-guide
and correctly unscored): composites clustered **81–87** (Local SEO avg 84.2,
Ecommerce 81.3), nothing ≥90, almost nothing <80. Textbook LLM-judge
central-tendency.

**The insight that wrote the fix.** Per-dimension, the **only** dimension
producing honest, well-spread scores was `distinctiveness` (avg **71.5**, range
55–82) — and it is the **only** dimension whose prompt line was already framed
adversarially ("could a competitor use this by swapping the name? score LOW").
The other seven ("score how faithfully it follows the guide") inflated: tone
86.8, writing_style 84.3, vocabulary 80.4. So it was a controlled experiment —
adversarial framing works; extend it to the other seven.

**What changed (PR #743, open).** Hardened **both** judge prompts — they are
separate and have **no sync-guard** (unlike `voice_card.py`):
- `nlp-api/main.py::_VOICE_SCORE_PROMPT_SUFFIX` — the page judge, consumed by all
  four page scorers (`_score_system_prompt_for` local/national,
  `_ecommerce_score_system_prompt_for`, `_blog_score_system_prompt_for`).
- `pipeline-api/modules/writer/voice_review.py::_SCORE_SYSTEM` — the blog/service
  **article** judge (its own rubric; would have stayed generous otherwise).

Each got: anchored 0–100 bands with **60–74 "competent but anonymous" as the
DEFAULT** for a page that reads fine but isn't distinctly the client; "never
award 75+ for the mere absence of errors"; **worst-section evidence** (quote
where it drifts, score to that); an 85+ justification guardrail; per-dimension
"what LOW looks like" cues. **Output contracts unchanged** (page: `brand_voice`
key; article: bare 8-dim object) → parsers, `voice_scorecard` math, weights,
`VOICE_PASS_THRESHOLD` (80), deterministic caps all untouched. Verified locally
as far as the sandbox allows (py_compile; `test_voice_card` 54 pass; isolated
article-path integration).

**Validation — the next real step, must run on PLATFORM.**
`platform-api/scripts/revalidate_voice_scores.py` re-scores the baseline pages
through the deployed nlp path and prints before→after distributions +
per-dimension means. Read-only w.r.t. the stored baseline (records a score-run
history row like a UI "Score", never overwrites `voice_score`/`voice_violations`;
`--write` persists once trusted; `--limit` smoke-tests). The **sandbox can't
reach the private nlp service**, so run it in a Railway shell on PLATFORM.
Expected: the 81–87 mass spreads to **~62–80**, on-brand pages still reaching
high 80s. Caveats it prints: re-score uses the client's *current* voice card
(clean rubric comparison only where the guide is unchanged); local pages with an
empty/unrecognized `location` error out (excluded, not scored 0).

**Deferred until that re-score is measured (do NOT guess now):** raise the
`distinctiveness` weight (.10→.15) and revisit `VOICE_PASS_THRESHOLD`. Scores are
stored, so recalibration needs no re-billing beyond the one re-score.

**CI coverage (PR #746, open).** Only platform-api ran in CI, so both prompt
changes above had **no automated gate**. Added `.github/workflows/
nlp-api-tests.yml` + `pipeline-api-tests.yml` (mirror `python-tests.yml`; nlp got
a CI-only `requirements-dev.txt`). nlp-api went green; **pipeline-api immediately
caught two pre-existing failures** (1327 passed, 2 failed) invisible because the
suite never ran — both fixed in the same PR:
1. `test_pipeline_metadata_threshold_echo` — stale assertion (0.55) vs
   `config.brief_relevance_floor` raised to 0.65 in #688.
2. **Real bug** in `brief/assembly.py::_apply_title_case` — it title-cased each
   content H2 but left child H3s' `parent_h2_text` on the old casing, so an H3
   referenced a "nonexistent" parent. Fixed by realigning H3 parent pointers to
   the re-cased H2 in the same pass (idempotent).

**Open items for the next session:** (1) run the re-score on PLATFORM and record
the spread; (2) recalibrate weight+threshold from it; (3) land #746 green (CI
re-running after the two fixes) then #743; (4) longer-term, fold the two judge
prompts into one seam so they can't drift again (the scorecard math is already
shared; the prompts are not); (5) 146 live pre-guide pages still carry no voice
verdict — a backfill via voice-aware reoptimization.

## ⏩ Update — 2026-08-26 · **Client Reporting — report-content upgrades (all merged + live)**

A run of improvements to the client-facing PDF report shipped this session — each
its own PR, squash-merged to `main`, auto-deployed to PLATFORM (each verified
`SUCCESS`), and gated by the platform-api `pytest` GitHub Actions workflow (five
code PRs #741/#742/#744/#745/#748 + a docs PR #747). All
are additive rendering changes in `services/client_report.py` +
`services/brand_report_html.py`; two carry additive migrations (applied live).
Toggles default off, so nothing changes for a client until an account manager
opts in on the ClientReports **Delivery & schedule** card.

- **#741 (`ad26fb1`) — scheduled standalone report types.** The recurring
  schedule (`client_report_schedule.enqueue_due_report_schedules`) now also
  emits, per opt-in, the **AI Visibility** report (`report_type="ai_visibility"`
  — the 2026-07-06 fold-in decision finally executed) and a **new Local Rank
  (Maps) report** (`report_type="maps"`, `_build_maps_report` — a self-contained
  geo-grid PDF reusing the combined report's own `_gather_geogrid` +
  `_section_geogrid`; deterministic, no LLM, on purpose). Opt-in via
  `client_report_settings.ai_visibility_enabled` / `maps_enabled` (migrations
  `20260826140000` + `20260826150000`; the latter also widened the
  `client_reports.report_type` CHECK to include `maps`). Gated on the client
  actually tracking the matching keywords (empty-report guard); the pending-report
  guard is now `report_type`-scoped so the three deliverables don't block each
  other; delivery reads the report row generically so both new PDFs email +
  Drive-copy unchanged. The per-keyword Maps **Local Rank Analysis Docs** stay a
  separate on-scan-completion deliverable — not folded in.
- **#742 (`779f670`) — clearer Rank trend + month-over-month + GBP Insights.**
  The organic "Trend" column is relabeled **"Rank trend (last 90 days)"** with a
  legend (the sparkline already plots better ranks higher — it just had no
  label). Maps + AI-visibility gained month-over-month callouts with
  **per-keyword deltas** (`_gather_geogrid` pulls the previous reporting scan's
  per-keyword rows; `_gather_ai_visibility` the previous batch's found-counts;
  standalone `brand_report_html` gained a prev-period overall + per-keyword
  column). The **GBP Insights** section (`_section_gbp` — rating + new reviews +
  highlights + the `_gather_gbp_metric_growth` performance table) was
  **re-enabled** in the combined report (it was built-but-disabled) and added to
  the standalone Maps report. Note: `gbp_metric_daily` is keyed by
  `location_row_id`, **not** `client_id` — a naive `client_id` count reads 0 even
  for clients that have data (it joins through `gbp_locations`).
- **#744 (`3f70b96`) — 30d / 90d / since-start comparison horizons.** A
  single-window comparison tied to the report period is volatile (a 30-day
  report only ever showed a 30-day delta), which the owner flagged as hiding
  wins. **Performance highlights** now shows **Now / vs prev 30d / vs prev 90d /
  since-we-started** columns — pure `build_multi_comparisons` anchored at
  `period_end`, each horizon **omitted ("—") when the data doesn't span both its
  windows** (no fabricated partial deltas). Maps (`presence_horizons`) and
  AI-visibility (`visibility_horizons`) get the same section-level three-horizon
  callout (vs the scan/batch nearest each horizon + the first scan/batch). The
  single-window `build_comparisons` is kept for the KPI strip.
- **#745 (`d3b3a55`) — executive summary longer time frame.** The `emit_summary`
  tool gained a required **`long_term_progress`** field rendered as a green
  **"The bigger picture"** callout under the headline; the exec context now
  carries the three horizon sets so the model cites the durable 90d/since-start
  trend positively, leading with the longer view when a single month dipped and
  saying "early and building momentum" (never an invented number) when long-term
  data isn't there yet.
- **#748 (`a79c0cc`) — every tracked keyword in Organic rankings.** The combined
  report's `_section_organic` trimmed to the top ~5 movers with a "remaining N —
  full list on request" note; owner wants the full table. It now renders **every**
  tracked keyword, sorted strongest current position first (unranked last), with
  per-row Movement + rank-trend intact — so a slip shows honestly now (the old
  design deliberately hid decliners). Dropped the top-movers selection + the
  now-unused `_TOP_MOVERS` constant; raised `_gather_organic`'s `_MAX_KEYWORDS`
  cap **40 → 250** (runaway ceiling, not a display trim) because several clients
  track 50–96 keywords (UMH 96, Southwestern Hearing 60, EML 58, WheelHouse FL 50)
  — those clients now get a **multi-page** organic table, which is the accepted
  cost of "all keywords" (flag if a cap/hybrid is wanted for the very large ones).
- **#747 (docs)** — recorded #741/#742/#744/#745 in CLAUDE.md + HANDOFF.md.

**Live-data caveat (tell whoever tests this):** the horizons + month-over-month
only render where the history supports them. **Organic rank** runs long, so
Performance shows all three horizons today (verified on First Class Roofing:
Feb→Aug). **Maps + AI-visibility** scan history is younger than 90 days for
every current client, so their 90d/since-start rows correctly read "—" and fill
in over the coming months. A good end-to-end test client is **First Class
Roofing** (real previous Maps scan for MoM + real GBP metric growth; its AI
scans are a single day so AI MoM won't show).

**Infra note — the pytest gate is intermittent.** The platform-api `pytest`
workflow (added 2026-08-15, path filter `writer/platform-api/**`) **triggered for
#744/#745/#748 but did NOT fire for #741/#742** despite matching the same filter
and firing normally on other `claude/*` PRs. All were validated locally (74–80
report tests green) and merged clean. Unresolved; worth a glance if a
platform-api PR merges without its Python tests having gated it.

## ⏩ Update — 2026-08-26 (am) · **Website Builder — where it stood before PR #740, and the informational gap that is now built above**

Nothing was built in this pass. This section records **what is finished**, the
one thing that was silently broken and is now fixed, and a precise map of the
**informational gap** — which is **now built (see the section above)**, kept here
for the reasoning trail.

### Finished since the 2026-08-07 section

- **PR #575 merged** (`6e12bbb`) — theme compiler, core-pages writer, imagery.
- **PR #577 merged** (`473feee`) — the **per-site business-facts Settings tab**
  (`services/website_settings.py` + `components/website/SettingsTab.tsx`). Seven
  editable NAP/business facts, each stamped `provenance:"user"` so a later GBP
  re-scan fills **gaps only** and never overwrites a typed value; clearing a
  field drops the value *and* its stamp so it hands back to GBP. Saving
  re-commits `site.config.json` via `record_deploy(..., trigger="config")`. The
  pure helpers are tested against the **real** `build_site_config` fill step,
  because the editor and the fill step are only correct together.
- **PR #622 merged** (`c0397f7`) — ten defects from an adversarial re-read.
- **PR #624 / #681** — flags-on record, then design-fidelity layout variants.
- **Flags ON in production** (`WEBSITE_BUILDER_ENABLED` +
  `WEBSITE_IMAGES_ENABLED` on PLATFORM). Code defaults stay `False`, so a fresh
  environment still ships dark. Verified **behaviourally** (Railway redacts
  variable values for OAuth callers): the logs show `enqueue_due_deploy_polls`
  running its query, which returns early when the flag is off.
- **Nothing has ever been created by the module.** `websites`, `website_themes`,
  `website_pages`, `website_deploys` are all **0 rows**. (The 16 `website_*`
  jobs in `async_jobs` are the unrelated `website_scrape` client-site scraper.)

### The two bugs worth remembering

**1 · The narrowed select.** `website_generate` fetched the site row with
`.select("id, client_id, name")`. Every downstream writer therefore saw
`config == {}` and `site_type == "informational"` — so a business fact typed into
the Settings tab was silently ignored in favour of GBP, the tagline never reached
the prompt, and **every local site would have been written with informational
framing**. Fixed to `.select("*")`.

The part worth keeping: **my first regression test passed against the broken
code.** The test fake ignored column projection and returned whole rows whatever
was asked for. A fake more generous than the real dependency cannot catch that
class of bug. `tests/test_website_generate.py::_supabase` now honours
`.select(...)`, and the fix was verified fail-on-old / pass-on-new.

**2 · The stale template repo.** `kssabraw/ar-site-template` — the repo every
site is minted from — had not been synced since 2026-08-03. It was missing the
`site.ts` crash fix, the `hubs.ts`/nav fix, both hub routes and
`[...path].astro`. **Every site provisioned from it would have failed its first
build.** Full tree replacement pushed as `24e8416`. There is no automation
keeping `site-template/` and the GitHub template repo in sync; that is a real
gap, and re-checking it is cheap.

The other eight fixes, briefly: fonts failing open when the census measured none
(the one case the model had nothing to copy from was the one case it was free to
invent — now `no_fonts_measured`); raw `website_deploys` inserts bypassing
`record_deploy`, so a deploy chip sat at `queued` until the next scheduler sweep;
`site_type` never reaching the core-pages prompt (it is live now, with an
explicit informational framing that forbids sales copy); `_clean` treating a JSON
*number* as a clear, which deleted a field and dropped its `user` stamp;
`business.hours`/`areaServed` missing from `build_site_config`, which would have
crashed the **first** contact-page build of any local site (fixed at both the
producer and the template layer); six reads per save; a provision/settings config
clobber; brand tone read from the wrong nesting level; and a dead
`website_image_provider` setting, removed.

### Is it usable end to end?

**Local / lead-gen: yes, on paper** — design → theme → provision → plan →
generate → publish → deploy is wired and each stage is tested. **It has never
been run against a real design for a real client**, so the first live run should
be treated as a smoke test, not a delivery.

**Informational: no.** A plan for an informational site contains four content
pages and a blog archive with nothing in it.

### The informational gap, precisely

The **rendering half is already complete** — this is the surprising part, and it
means the build is smaller than it looks:

| Already built | Where |
|---|---|
| `posts` collection, five formats (`informational_cluster`/`listicle`/`comparison`/`local_geo`/`news`) | `site-template/src/content.config.ts:100` |
| `/blog/[...slug]` route + archive | `site-template/src/pages/blog/` |
| `post` → `posts` collection mapping | `website_content.py:41` |
| Post-specific `entry_id` (entry id IS the slug — a full-path id would publish `/blog/blog-my-post/`) | `website_content.py:122` |
| The **strict** post publish gate | `website_content.py:272` |
| Post body assembled from a blog run's `module_outputs` markdown | `website_publish.resolve_source`, `kind == "run"` |
| `post` is hero-eligible and its image prompt is never geo-tagged | `website_images.py` |

The post gate is deliberately stricter than anywhere a human is in the loop,
because auto-publish means nobody reads a post before the public does: a critical
voice violation and a `-degraded` writer run are **non-overridable**; frontmatter
must carry title/description/format; a `news` post must carry `reviewBy`
(non-evergreen + auto-publish + no expiry is how a site ranks on stale
information indefinitely). Keep that; do not soften it to make the first post
ship.

**What is missing is the planning and generation half — five things:**

1. **`website_plan.build_plan` never plans a post.** Every non-geo site falls
   through the `else` branch, so an informational plan is home / about-us /
   contact-us / privacy-policy / sitemap / blog. No pillars, no clusters, no
   posts. (`website_plan.py:608`)
2. **No `post` engine.** `generation_inputs` returns `{"engine": None}` for any
   page type outside `NLP_PAGE_TYPES` ∪ `CORE_PAGE_TYPES` ∪
   `TEMPLATE_ONLY_PAGE_TYPES`, so a planned post would report
   `engine_unavailable:post`. (`website_plan.py:635`, `:717`)
3. **No post frontmatter.** `frontmatter_extra` has no `post` branch, so
   `format`/`silo`/`cluster` would be absent and the publish gate would —
   correctly — refuse the page. (`website_plan.py:645`)
4. **No generation branch.** `website_generate` has no path that starts a Blog
   Writer run and links it back as `content_source="run"` +
   `source_id=<run_id>`. The publish side of that contract already exists.
5. **Pillar / Hub does not exist at all.** Reference §5.3: `/{topic-slug}/`,
   2,000–4,000 words, Writer #6, planner trigger *a cluster of ≥ 5 posts*. No
   page type, no collection, no route — yet it is the parent every cluster post
   links up to, so a cluster of posts with no pillar is not the page type the
   reference describes.

**The cluster map already exists and is unwired.**
`keyword_topic_strategist` emits exactly the shape the planner needs:

```
{assessment, pillars: [{pillar, rationale,
  clusters: [{title, buyer_problem, search_intent, funnel_stage,
              target_keywords, questions, priority, rationale}]}]}
```

and `keyword_research_handoff` already turns selected keywords into a Fanout
session whose scheduler writes blog posts (`content_type` blog_post |
local_seo_page). `website_plan`'s own docstring records the standing assumption
that *"the fan-out owns an informational site's post plan"*.

**That assumption is the first decision of the next build**, and it should be
made explicitly rather than inherited: either the site plan *reads* an existing
strategist/Fanout plan (cheap, reuses a tested path, but couples site structure
to a research run), or the Website Builder owns its own cluster inventory
(more work, but the plan is then a property of the site and survives a
re-research). Both are defensible; picking silently is not.

Two reference rules the planner must encode either way: **blog posts are planned
per cluster, never ad hoc** — every post carries a silo and a target format
*before* generation — and the `news` format is **non-evergreen and excluded from
pillar-cluster math**.

### Verification rule that keeps earning its keep

Build **both** site types in `site-template/` — not just the unit tests. That is
what caught the variable-font duplication (same bytes downloaded 3× under 3
names, masked by the bundler's content hashing), the `sections` key missing from
the frontmatter order (home copy silently dropped while reporting success), and
the contact-page crash. Unit tests found none of the three.


## ⏩ Update — 2026-08-26 · **LeadOff GBP Placement Advisor — built + LIVE + prod-verified**

The demand-aware **"where should the GBP live"** module — the demand-side upgrade
of the competition-only Proximity signal (an empty octant can be empty of
*people*, not just of competitors). Shipped across **8 PRs, all merged to `main`
+ deployed** (#725 Phases 1+2, #728 + #730 prod-verification fixes, #731
calibration freeze, #732 Phase-0b probe, #733 + #735 docs), building on the
live-GBP market map (#719/#721). Authoritative doc:
**`docs/modules/leadoff-gbp-placement-plan-v1_0.md`** (owner decisions §1;
build-status + prod findings §9a). Full writeup is in that doc + CLAUDE.md's
LeadOff section — this is the operational handoff summary.

**What it does (deterministic, no LLM):** for any point `c`,
`placement_score(c) = 100 × norm(demand_access) × (1 − norm(pressure))` — `demand_access`
sums Census block-group **households** with a `1/(1+d/5mi)` decay; `pressure`
sums competitor GBPs review-weighted with proximity's verbatim `1/(1+d/2mi)`
decay; `norm()` is min-max over the market's OWN 1-mile lattice (market-relative,
never comparable across markets). It surfaces 3–5 ranked, ≥2-mi-apart,
locality-named zones ("Near Maumelle") on the market map + a "Best areas to plant
a GBP" card list, plus a **Phase 2 "Both"** score-any-location panel (click the
map / paste an address or GBP → scored against the zones, side-by-side compare,
optional octant re-anchor).

**Free, $0/market beyond captured pins.** Core: `services/leadoff_placement.py`
(pure) + `services/census_demand.py` (ACS block groups + TIGERweb centroids →
`census_block_demand` cache, filled by the `leadoff_placement` async job). API
`GET /leadoff/placement` + `POST /leadoff/placement/score-point`. Behind
**`leadoff_placement_enabled` (default True — ON in prod)**.

**Activation / env (already set on PLATFORM):** needs **`CENSUS_API_KEY`** (ACS)
+ **`GOOGLE_MAPS_API_KEY`** (zone naming + the static map) + the existing
DataForSEO creds (only for the map-refresh pin pull, not the advisor itself). No
dashboard setup needed. Opening a scouted market with ≥5 live pins auto-enqueues
the Census demand fill on first view (poll `job_id`); markets with <5 pins show
the honest `thin_field` state and a nudge to Refresh map (~$0.004).

**Prod verification earned its keep** — three real bugs, each caught live and
pinpointed by the self-diagnostic built into the job, none catchable by unit
tests:
1. `enqueue_placement` wrote a non-UUID `entity_id` (the column is UUID) → the
   auto-enqueue would throw. Fixed to `uuid4()` + dedupe by `payload->>city_id`.
2. The TIGERweb centroid query used `STATE=/COUNTY=` field names that returned 0
   features. Fixed to `GEOID LIKE '<fips>%'` + `outFields=*`, with a persisted
   `tigerweb_diag` on the job row.
3. `_resolve_bg_layer` matched **"Tribal Block Groups"** (layer 6, listed first)
   instead of **"Census Block Groups"** (layer 10) → all-null centroids. Fixed to
   select the Census layer specifically (`pick_bg_layer`, unit-tested).
After the third fix, a live KC run wrote **1,494 real ACS block groups** and
produced sensible zones — verified end-to-end.

**Phase 3 (paid per-ZIP demand layer) — PROBED & DROPPED.** The ~$0.05 Phase-0b
feasibility probe (`services/leadoff_zip_demand.py`, `leadoff_zip_demand` job) ran
live: 10 Chicago ZIPs (60601–60610) × "plumber" all queried cleanly but returned
`search_volume: null` (`null_share` 1.0 → `inconclusive`). Google thresholds Ads
search volume at ZIP granularity even for a high-demand trade in a major metro,
so a per-ZIP re-weight adds no signal over the free households surface → **not
built**; `leadoff_zip_demand_enabled` stays False, the probe is the record. Total
paid spend for the whole module: **~$0.05**, on the probe that prevented a wasted
build.

**Calibration freeze (§8, built):** the create-client handoff freezes the market's
zone set into `leadoff_predictions.placement` (jsonb) alongside the existing
`proximity` freeze, so the post-client geo-grid can later grade whether high-score
zones matched better pack outcomes — the loop that eventually earns the dollar
layer (still off). Read-only instrumentation; nothing feeds scoring.

**Grade safety is absolute:** placement reads only `leadoff_gbp_pins` +
`census_block_demand` and writes only its own cache — **never** the board grade,
`competitor_locations`, or `proximity_opportunity`.

**Demo market left in place (owner):** **Kansas City / pest_control_service** is
seeded as a working demo — 5 real competitor pins in `leadoff_gbp_pins` + 1,494
real ACS rows cached. To remove the pin seed later:
```sql
delete from public.leadoff_gbp_pins where city_id=4393217 and category_id='pest_control_service';
```
(The `census_block_demand` rows are legitimate real ACS cache — fine to keep.)

**Migrations (all applied live):** `20260825140000` (map refresh),
`20260825150000` (`census_block_demand`) + `20260825160000` (async_jobs CHECK),
`20260826120000` (`leadoff_predictions.placement`), `20260826130000` (async_jobs
CHECK + `leadoff_zip_demand`).

**Remaining (owner call, not started):** the **dollar layer** — gated on the §8
calibration loop showing signal (needs real post-client geo-grid outcomes to
accrue first).

---

## ⏩ Update — 2026-08-25 · **LeadOff market-map interactions + two-maps sync (PR #721, MERGED + DEPLOYED)**

Owner-driven UX polish on the live-GBP market map, shipped in the **same PR #721**
as the Refresh-map affordance below (squash-merged to `main` as `f2da79d`,
auto-deploys PLATFORM + rebuilds the Netlify frontend). All in
`frontend/src/components/leadoff/MarketMap.tsx` (+ a `place_id` field threaded
through `ProximityRead.pins` / `MarketMapPin` in `pages/LeadOff.tsx`).

**What changed, in order of how it landed:**
- **Per-pin interactivity.** Each competitor pin is a link to its **exact GBP**
  (`place_id` → `maps/place/?q=place_id:…`, else a name/coord search), and
  hovering shows a card with the business **name / ★ rating / reviews / distance**
  plus a "View on Google" link. The hover card flips below the pin for top-row
  pins and spills past the map edge (outer container `overflow: visible`; the
  image keeps its clipped rounded border). `place_id` was already captured for
  live pins by `_map_pins`; it just wasn't typed on the frontend.
- **Two-maps sync (owner: "users are going to get confused").** The map + pins
  show only the **ranked competitors we captured** (bounded: SERP depth ~20,
  coords-required, within the analysis radius, exact keyword). A Google Maps link
  can't be limited to that exact set — it always renders Google's **full live
  directory** — so a whole-map "Open in Maps" jump read as the two maps
  disagreeing. **Resolution (owner chose "exact links only"):** the base map is a
  **static snapshot, not a link**; the only place-level jump to Google is
  **per-pin** (place_id-exact, always in sync with what's plotted).
- **Separate "Browse all …" escape hatch (owner request).** A **clearly-distinct,
  labelled** link *below* the map — `Browse all "<category>" businesses on Google
  Maps` with a sub-note that it opens Google's full live directory (more listings
  than the ranked field above). Framed as its own action, never as "the same
  map". Driven by a new optional `browseQuery` prop (the market's humanized
  category slug).

**Why the counts differ (for future reference):** the tool map is the *ranked
competitive field for one keyword* (a curated, bounded snapshot from a single
DataForSEO Maps SERP), not the exhaustive local directory Google shows live. This
is by design; the per-pin `place_id` links are the only guaranteed-exact bridge
between the two.

Frontend-only; `tsc` + `vite build` clean; platform-api tests green on the merge.

---

## ⏩ Update — 2026-08-25 · **LeadOff market-map "Refresh map" affordance (follow-up #3)**

Follow-up to the live-GBP market map below. Closes the gap where a **fully-cached
scout can't (re)generate its map**: `fetch_market_pins` (the ~$0.004 Maps SERP
that captures GBP pins) only fired inside a full scout, and a fully-cached scout
returns `{job_id: null}` and runs nothing — so every market scouted before the
pins feature shipped (2026-08-21) showed octant bars but **no map**, with no way
to get one short of 90-day cache expiry.

**What it adds:** a lightweight **`leadoff_map_refresh`** async job that re-pulls
ONLY the market's live competitor GBP pins (one Maps SERP, `COST_MAP_REFRESH` =
$0.004), decoupled from the RD/velocity/trend/footprint enrichment. Surfaced as a
**"Refresh map (~$0.004)"** link on a market whose map is already showing, and as
**"Plot the live GBPs (~$0.004)"** on a not-yet-scouted market (the cheap
alternative to a full ~$0.70 scout just to get the map) — including the
`no_geocoded_competitors` empty state.

**Files:** `services/leadoff_actions.py` (`COST_MAP_REFRESH`, `market_display`,
`enqueue_map_refresh`, `run_map_refresh_job`), `services/job_worker.py` (dispatch),
`routers/leadoff.py` (`POST /leadoff/map-refresh`, staff-gated + budget-checked +
spend-recorded as `"map_refresh"`; job added to the `/leadoff/jobs/{id}`
allowlist), `frontend/src/pages/LeadOff.tsx` (`MapRefreshButton`, wired into
`ProximityCard`/`ProximityDetail`).

**Safety:** an empty/failed SERP (`fetch_market_pins` returns `[]` on any error)
**skips persist entirely** — `persist_gbp_pins_batch`'s delete-stale step would
otherwise wipe the market's prior pins on an empty batch, so a bad pull leaves the
existing map intact (unit-tested). Reuses the separate `leadoff_gbp_pins` table,
so a refresh still never shifts the board grade (Census pins unchanged).

**Migration `20260825140000_leadoff_map_refresh_job.sql`** (adds the job type to
the `async_jobs` CHECK) — **applied live** to `AR-Internal-Tools`. Tests:
`tests/test_leadoff_map_refresh.py` (persist-only-non-empty, empty-preserves,
unknown-market-fails); 115 leadoff tests green + frontend build clean.

**Still open (deliberately deferred, owner "v1 is a start"):** click-to-drop a
candidate pin (#1) + re-anchoring the octant math on a chosen point (#2), and the
sparse-category (<5 pin) read polish (#4).

---

## ⏩ Update — 2026-08-25 · **LeadOff live-GBP market map from Scout/Tryout + placement plan (PR #719, MERGED + DEPLOYED)**

The LeadOff market brief now shows a **map of the actual competitor Google
Business Profiles** for a market, plus a plain-English **placement plan**
("where should we plant a GBP"). Shipped in **PR #719**, squash-merged to `main`
as `d075d8d`, auto-deployed to `PLATFORM` (deploy SUCCESS on `d075d8d`), frontend
live via Netlify. **No feature flag — it's on.**

### What it does
- **Scout a market** (or run a **Tryout**) → the live competitor GBPs are plotted
  over a Google static map (teal dots sized by review count, ranked ones
  labelled), with the market centre, suggested placement zones, and an optional
  pasted-GBP reference pin. A deterministic **placement plan** names the weakest
  bearings + the best place to plant a GBP (near the nearest real town) + the
  nearest-competitor distance.
- **Where to see it:** LeadOff (sidebar Radar icon / `/leadoff`) → filter to a
  market → click its row → the **"Proximity (where the field sits)"** card. The
  map renders only **after** a scout/tryout (source `gbp_serp`); before that the
  card shows the octant bars + a "Scout this market" nudge. Also on the **Tryouts**
  tab: a per-result-row **Map** button.

### The cheap-win insight
Scout and Tryout **already fire a live Google Maps SERP** whose items carry each
competitor's GBP **coordinates / place_id / rating / review count** — the parsers
just kept name/domain/phone. So plotting the real GBPs needs **no new paid call**;
scout still fires a single Maps SERP (its phones also feed the existing NAP
footprint step).

### Architecture / decisions worth knowing
- **Grade safety.** Live pins live in a **new, separate** `public.leadoff_gbp_pins`
  table — deliberately NOT in `competitor_locations`, whose Census pins feed
  `proximity_opportunity` (a board grade input). So scouting improves a market's
  **map** without shifting its **grade**. The grade path
  (`leadoff_proximity.market_proximity_score`) still reads Census pins, unchanged.
- **`market_proximity(prefer_live=True)`** prefers live GBP pins → attaches the map
  layer only for the `gbp_serp` source. The **create-client handoff** calls it with
  `prefer_live=False` so the campaign-goal placement text + the calibration-frozen
  proximity stay aligned with the grade's Census read even on a scouted market.
- **Persistence is insert-then-delete-stale** (`services/leadoff_gbp_pins.py`,
  keyed on a per-batch `captured_at` stamp) so a failed insert never wipes a
  market's prior pins; tryout writes all categories in one batched insert + delete.
- **Rural fallback:** if every competitor sits beyond the 10-mi analysis radius
  (octant read empty), the map still shows all captured GBPs, framed by a
  `map_radius_miles`, instead of reading "unavailable".
- Migration **`20260821140000_leadoff_gbp_pins.sql`** (table + index + RLS-on,
  service-role-only like every sibling LeadOff table) — **applied live** to
  `AR-Internal-Tools`.

### Verified in production (2026-08-25)
Ran one real scout on the deployed worker for **Little Rock, AR / chimney_sweep**
(city_id `4119403`) — everything else cached, so ≈ one $0.004 Maps SERP. Result
`gbp_pins: 2`, no error; the two real GBPs (JMI Masonry Chimney Inspection ★3.8;
Clean Sweep Management ★5) persisted with coords/place_ids and the batch stamp,
both inside the 10-mi radius → the read flips to `source=gbp_serp` and serves the
map. (Those 2 rows are real scout output — left in place.)

### Known limits / follow-ups (owner: "not perfect, a start")
- Sparse categories (like the chimney_sweep test, 2 pins) correctly show a "thin
  data" note and **no** placement plan — you need ≥5 in-radius pins for the plan.
- **Re-generating the map on an already-fully-cached scout** isn't offerable yet
  (the first scout always captures pins; a later refresh needs cache expiry). A
  "refresh map" affordance is an easy follow-up.
- Deliberately not built (owner chose reference-pin-only for v1): **click-to-drop**
  a candidate pin anywhere, and **re-anchoring** the proximity math on a chosen
  location.
- The map image needs `VITE_GOOGLE_MAPS_API_KEY` in the Netlify build (same key
  the geo-grid map uses). Absent it, the card shows a "needs a Maps key" note +
  the octant bars (pins/logic still present).

---

## ⏩ Update — 2026-08-19 · **Second-Anthropic-account failover (concurrency headroom)**

Concurrency limits (429s) on the shared Anthropic account can now fail over to a
**second Anthropic account** — same Claude models, so output quality is
unchanged. This is distinct from the existing cross-*provider* fallback
(Anthropic→OpenAI→Gemini in `report_llm.py`), which swaps models; the second
account is tried **first**, before any provider swap. Reactive failover only
(the primary stays primary; the secondary is used only when the primary hits a
transient 429/5xx that outlasts its retry budget). Covers all four Anthropic
call surfaces: the report fan-out + brand/AI scans + agentic loops
(Slack/SerMastr, strategist, PACE, QA) in **platform-api**, blog/service
generation in **pipeline-api**, Local SEO/Ecommerce generation in **nlp-api**,
and the Topic Fanout backend.

**To activate — set ONE env var per service** (empty ⇒ no failover, so the code
ships dark until you set it). The var is a **second Anthropic account's API key**
(a genuinely separate account/org, not a second key on the same account — same
account shares the same concurrency limit):

| Railway service | Var to set |
|---|---|
| `PLATFORM` (platform-api + the vendored fanout) | `ANTHROPIC_API_KEY_SECONDARY` |
| `pipeline` (pipeline-api) | `ANTHROPIC_API_KEY_SECONDARY` |
| `nlp` (nlp-api) | `ANTHROPIC_API_KEY_SECONDARY` |

Each service also honours `ANTHROPIC_KEY_FAILOVER_ENABLED` (default `true`; set
`false` to disable without unsetting the key). Read the live Railway config
before/after setting these (see the CLAUDE.md "read the live config" rule). No
migration, no schema change, no new dependency.

---

## ⏩ Update — 2026-08-07 · **Website Builder — theme compiler + core-pages writer + imagery (PR #575, MERGED)**

Closes the owner's four-step arc — *upload a Claude design → write the pages →
generate images → push to a repo*. Three slices on **`claude/website-builder-slice-3-9an50d`**,
three commits, CI green, **merged to `main` 2026-08-07**. Still dark behind
`website_builder_enabled`; imagery additionally behind `website_images_enabled`
(both default False — unchanged, nothing has run).

**Read the earlier 2026-08-05/06 section below for the module's base state; this
is what those three "still unbuilt" items became.**

### 1 · Theme compiler (`services/website_theme.py` + `_precompile.py` + `_fonts.py`)

Upload a Claude Design export (`.dc.html` or the zip) → a compiled `tokens.css`
the template's `src/theme/` reads. **Split so the LLM only does the part it's
good at:** the precompile pass MEASURES everything countable (colour frequencies,
font families/sizes/weights/radii/spacing, the design's screens/collections/
image-slot seeds) with no network; the LLM pass NAMES — one forced tool call
answering *which measured value is which role*, shown a frequency table, never
the markup. **`validate_roles` refuses any value the census didn't see**, so a
hallucinated brand colour fails the compile instead of shipping as a client's
identity. **Fonts are self-hosted** (downloaded at the design's own measured
weights, committed beside `tokens.css`) so a site makes no third-party request;
best-effort — a font-CDN outage degrades to naming the family.

Themes are **fleet-level** (a design starts several sites): `GET/POST
/website-themes`, `…/{id}`, `…/recompile`, `…/approve`, `POST /websites/{id}/theme`.
Compiled bytes are stored and committed **verbatim** (what's approved is what
ships). Applying to a provisioned site commits `src/theme/*` + records a
`theme` deploy; applying before provisioning rides in with the **configure**
commit so the first build never deploys the house theme to a watched URL. Job
`website_theme_compile` (type already in the live CHECK). **Private
`website-themes` bucket** — migration `20260806120000_website_theme_bucket.sql`
**applied live**. Frontend: a **Theme** tab (upload / swatches / compiled CSS /
approve / use-on-site / recompile). Config `website_theme_model` (Sonnet),
`website_theme_max_mb` (25). *Build verification caught a bug unit tests
couldn't: variable fonts serve one file per subset with a `@font-face` per
weight, so naming files by weight downloaded the same bytes 3× under 3 names —
`resolve_filenames` now names a shared file without a weight (12→4 on the
reference design).*

### 2 · Core-pages writer (`services/website_core_pages.py`)

Home / about / contact — the pages no keyword targets, so **no SERP, no scoring
loop**: one Anthropic call each, in platform-api (nlp would only add its
brand-voice prose builder, which the suite already renders here). Each produces
exactly what its template slot reads: **home** → a `sections` frontmatter map
(hero copy + headings), no body; **about** → a Markdown narrative; **contact**
→ title + intro line only (NAP/hours/form render from verified data). **Privacy
is deterministic** — a legal template merged with business facts, recorded
`template_rendered`, never sent to an LLM. **The forced schema has no
phone/address/price field, so an invented business fact is structurally
impossible;** home draws real services/cities from the site's own planned pages.
Same brand-context gate as the service writer (refuses without a voice on file).
Wired into `website_generate.generate_page` (the `core_pages` engine, previously
`engine_not_built`). Config `website_core_pages_model` (Sonnet) / `_max_tokens`.
*Fix found while verifying: `sections` wasn't in `website_content`'s frontmatter
key order, so a home page's section copy would have been silently dropped —
added, with a round-trip test.*

### 3 · Imagery (`services/website_images.py`)

A hero image per hero-eligible page (home + service/location/matrix/post; about/
contact/privacy excluded) during the same generate job, landing in the page's
`heroImage`/`heroImageAlt` frontmatter — **already committed by `build_files`,
so publish needed no change.** Reuses the suite's one proven renderer
(`illustration.py`'s gpt-image-1); prompt art-directed from the page's own
subject + a photographic brand-style tail forbidding text/logos (no fake signs);
client tone rides along. **Delivered as a public-bucket URL, NOT committed to the
repo** — a 20 KB shared font earned self-hosting, a 1–2 MB hero × dozens of pages
would bloat every repo and re-upload to Cloudflare each deploy. Additive +
best-effort: double-gated on `website_images_enabled` (default off, its own axis
so enabling the builder never starts spending — a 40-page bulk-create is 40
renders) + an image key; every failure path returns None and ships the page
heroless. `website_image_provider` default corrected **gemini→openai** (gemini
names a renderer that doesn't exist yet).

### Inputs (where the four pages' content comes from)

Contact NAP auto-fills from the client's **GBP** into `site.config` (human-entered
values win, §4.5). Brand voice + ICP come from the client's auto-scan of
website/GBP at creation, or a typed guide (user-authored supersedes). **Not yet
built:** a dedicated per-site business-facts editor (the deferred Settings tab) —
today a per-site NAP override goes through the config, not a form.

### To run it end-to-end

Flip `website_builder_enabled=true` (and `website_images_enabled=true` for art)
on PLATFORM — **both set to `true` on 2026-08-08** (deployment `ea2b98b4`,
commit `b4ca6da`, SUCCESS; verified behaviourally in the running app's logs —
the scheduler is executing `enqueue_due_deploy_polls`, which returns early
unless the flag is on). Then the normal lifecycle: create a
`websites` row → upload+approve a theme → provision → build+approve a plan →
generate (now covers home/about/contact + hero images, not just nlp pages) →
publish. Testing: ~160 new unit tests across the three modules; full backend
suite 3288 passed (same 13 pre-existing sandbox failures as main).

---

## ⏩ Update — 2026-08-05 · **Website Builder module — slices 1–2 MERGED, slice 3 in flight**

Design in Claude Design → upload → the suite compiles it to an Astro theme,
provisions a private GitHub repo from a house template, generates pages with the
suite's existing engines, and Cloudflare serves it. **Ships dark behind
`website_builder_enabled` (default False)** — nothing can create a repo until
that flag is on.

### 🟢 Nothing has been created — and "publish" here is jargon

**As of 2026-08-05 no website exists.** `websites`, `website_pages`,
`website_deploys` and `website_themes` are all **empty**, and no
`website_provision` / `website_page_publish` job has ever run. (16 `website_scrape`
rows exist — that is the unrelated, pre-existing client-site scraper.)

**"Publish" in this module means "commit a generated page file into that site's
repo".** It is the name of a code path, not an outward-facing act, and the
function that does it is not written yet. Likewise "generate" means "call
nlp-api for body copy", not "put something on the internet". The docs and commit
messages use these words throughout; none of them describe anything that has
run.

**`kssabraw/ar-site-template` is the mould, not a site.** Private, containing
the template plus two sample blog posts. It exists because the provisioner
creates each site with `POST /repos/{template}/generate`, which needs a template
repo to point at. Nothing is deployed from it and it has no Cloudflare project.

**For a real website to exist, all of these must happen deliberately:**

1. `website_builder_enabled=true` set on PLATFORM (**done 2026-08-08**; was
   False before that, which is why nothing below had run)
2. a `websites` row created for a client
3. `POST /websites/{id}/provision` called by a staff+ user
4. a site plan built, reviewed and approved
5. content generated (this is the step that spends money — one nlp-api call per page)
6. pages published, i.e. committed, which triggers the Actions deploy

Steps 4–6 now have code behind them (2026-08-05), and **still nothing has run**:
every route 503s while the flag is off, and every step above needs a person to
take it. Building the machinery is **setup**; creating a site is a separate,
deliberate act that nobody has taken.

**Docs (read these first, in this order):**
- `docs/modules/website-builder-module-plan-v1_0.md` — engineering spec:
  architecture, data model, phasing, locked infrastructure rulings.
- `docs/modules/website-builder-prd-v1_0.md` — behaviour, permissions,
  lifecycle, quality gates, acceptance criteria. **Vendored from the owner's
  Google Doc; the Doc is the source of truth.** Owner rulings made after capture
  live in an **amendments block at the top**, not edited into the body — read it
  before trusting any section it names.
- `docs/reference/page-type-reference-v3_6.md` — **authoritative** for page
  types, planner triggers, URL patterns, page structure, the Shared Component
  Library, and content specs. Also vendored; subordinate to the AR Site
  Architecture SOP.

### What is built and merged (PR #545, squash `5c3ef95`)

- **`site-template/`** — the house Astro template, also published as the GitHub
  **template repository `kssabraw/ar-site-template`** (private, `is_template:
  true`). Astro 5 content collections with a zod frontmatter contract,
  deterministic JSON-LD, SEO plumbing, token-driven theme layer, push-to-main
  Actions → `wrangler` deploy to Cloudflare Workers static assets.
  **`site-template/` in this repo is the source of truth** — edit here, publish
  from here.
- **Backend**: 4 tables, a resumable provisioning step machine
  (`services/website_provision.py`), REST surface (`routers/websites.py`), job
  wiring. Migrations `20260803190000` + `20260803210000`, both **applied live**.

### Slice 3 — merged (#560) plus the wiring that finishes it

Merged in #560: `services/website_plan.py` (the site-plan inventory) and
`services/website_content.py` (content → repo files + publish gates), both pure.

The impure half is now built: `services/website_plan_store.py` (build / rebuild
/ approve a plan as `website_pages` rows), `services/website_generate.py`
(`website_page_generate` → `local_seo_service.generate_page`, unchanged),
`services/website_publish.py` (`website_page_publish` → one commit per page via
`github_publish.commit_files_to_github`), `services/website_deploy.py`
(`website_deploy_poll` + the scheduler sweep), and eight routes on
`routers/websites.py`. Migration `20260805120000` applied live. **206 tests
across the seven modules** (was 99).

**UI (built 2026-08-06).** Two entry points, per PRD §6.1, and **both are
hidden until `website_builder_enabled=true` on PLATFORM** — **set 2026-08-08**,
so the module is now visible in the dashboard (it was invisible by design until
then):

1. **Sidebar → Websites** (`pages/Websites.tsx`, route `/websites`) — the fleet
   across every client, with status/domain/last-deploy columns, a filter, the
   §7 counts, and Trash. Read-only apart from soft-delete and restore; rows link
   into the client's workspace, which is where work happens.
2. **Client workspace → Website Builder card** (route `clients/:id/website`).

Both gate on the same `GET /websites/status` (the PACE/QA pattern — a card that
503s on click is worse than no card), so the module appears in both places at
once or in neither.

`frontend/src/pages/WebsiteBuilder.tsx` + `components/website/*`. Four tabs:
**Overview** (the provisioning step machine with per-step state and a Resume,
URLs, repo, last deploy), **Plan** (catalog + cities editors, Build, the issue
list split into blocking vs advisory with per-gate sign-off checkboxes,
Approve), **Pages** (per-page status, engine, the gate reason in plain English,
select → Generate/Publish, per-row retry, a leaveable batch bar), **Deploys**
(history with `superseded`/`unknown` explained inline, Re-check, recorded gate
overrides). Actions above the user's role render **disabled with the reason**
rather than hidden, per §6.2.

**Still unbuilt in the module** *(as of this 2026-08-05 section; the theme
compiler, core-pages generator and imagery were built 2026-08-07 — see the top
section)*: custom domains, GSC auto-verify, and the Settings tab. The
suite-level fleet index shipped 2026-08-06 (Sidebar → Websites). Generation
originally covered the nlp-api page types only; a page type with no engine still
records `engine_unavailable:<type>` on its row rather than being silently
skipped.

**⚠ Three things the build found that reading the docs did not:**

- **The template's deploy workflow sets `concurrency: cancel-in-progress: true`,**
  so publishing a 20-page batch cancels 19 runs. The merged
  `deploy_status_from_run` read `cancelled` as **failed**, which would have
  painted a successful batch red 19 times. `cancelled` now maps to a new
  `superseded` status and raises no notification.
- **Post entry ids doubled the `blog` segment.** `/blog/[...slug]` uses the
  entry id AS the slug, so the full-path id from `entry_id` would have published
  `/blog/blog-my-post/`. Found by building the template with real generated
  files, not by reading the zod schema — do this every time.
- **`areas_we_serve` and `services_index` were listed as "template-rendered"
  but the template has no route for either** (they are Writer #6's page types).
  Publishing would have marked them live at a URL that 404s. They are now
  `UNRENDERABLE_PAGE_TYPES`, reported as a non-blocking `missing_template` plan
  issue, and a page with an empty body is held at `body_not_generated` rather
  than committed as an empty file.

**Where the catalog lives:** the plan is built from a catalog + cities posted to
`POST /websites/{id}/plan` and persisted onto `websites.config`. The
client-level Business Facts store (PRD §4.10) is a later slice; this is the
shape it will feed. Nothing is imported from GBP categories.

**Contradiction resolved against the PRD, not the plan:** a deploy whose Actions
run cannot be found past `website_deploy_timeout_minutes` is recorded as
**`unknown`** with a re-check action (PRD §6.3), not as failed — the old config
comment said failed and has been corrected.

### Provisioned (all live on PLATFORM)

`GITHUB_SITES_TOKEN`, `GITHUB_SITES_OWNER=kssabraw`, `CLOUDFLARE_API_TOKEN`,
`CLOUDFLARE_ACCOUNT_ID`.

### Owner rulings

Site repos under **`kssabraw`** (personal account, not an org) · existing
Cloudflare account · **Workers static assets**, not Pages · Namecheap domains
with NS pointed at Cloudflare · every site belongs to a client row · info sites
**auto-publish**, local sites get human review · themes reusable across
industries · AI imagery including realistic jobsite scenes · Web3Forms (one
shared key) · CallRail DNI · ~50 sites year one. Then **2026-08-04**: a lead-gen
property's matrix **may ship before its informational layer** (overrules PRD
§4.12.3b "neither ships alone"), and the **>40 links figure is too high** —
advisory only, pending a ratified number.

**v1 scope:** `local_business` + `lead_gen`, Tiers 1–3, `monetization: leads`.
Deferred: `ads`/`affiliate` and the consent stack, informational properties, and
the six unbuilt writers (§4.7).

- **The global nav was 404s, on every page of every site.** `default_nav()`
  wrote `/services`, `/locations`, `/about` and `/contact` into each site's
  config, and `CTABand`'s default CTA pointed at `/contact` — none of which are
  routes (the real ones are `/about-us/`, `/contact-us/`, and cities sit at
  root). Astro does not fail a build on a bad `href`, so it shipped silently.
  Fixed 2026-08-06: the template **derives** the SOP global nav/footer set from
  published pages (`src/lib/hubs.ts`), config `nav` is an override, and the
  provisioner writes none. **Verification now includes a link check** over the
  built `dist` — it found 13 broken links on the pre-fix build and 0 after.

### ⚠ Gotchas that cost real time

- **The root `.gitignore` has a Python `lib/` rule at line 13** that silently
  swallowed `site-template/src/lib/` — three essential files were missing from a
  commit with no warning, and the template would not have built. Fixed with
  `!site-template/src/lib/` (negate the **directory**; git will not descend into
  an ignored directory to re-include children). **Anything else added under a
  `lib/` path will hit this again.**
- **URL structure was wrong in slice 1** and had to be reworked. Reference §1.1
  R1: local top-level pages sit at **root**, not under `/services/` or
  `/locations/`, and the matrix is **location-first** `/{city}/{service}/`. The
  plan's pre-ruling text illustrated the wrong shape.
- **Page type is DECLARED, never inferred from the URL.** `/{city}/{x}/` may be
  a local landing, a neighborhood or a POI. Every routed entry carries `path`
  **and** `pageType`; one catch-all `[...path].astro` renders them. Do not add
  per-type route files.
- **PyNaCl is required** — GitHub's Actions-secrets API only accepts values
  sealed with the repo's libsodium key. Imported lazily, so a deploy without it
  starts and fails with `pynacl_not_installed` rather than an ImportError.
- **This session's GitHub credential cannot create repos** (App installation
  scoped to `ar-tools`; `POST /user/repos` → 403 "not accessible by
  integration"). The template repo was created by hand. `GITHUB_SITES_TOKEN` is
  a different credential and is what the provisioner uses — **whether it can
  create repos is still unverified**; if it cannot, swap for a classic PAT with
  `repo` + `workflow`.
- **PRs here are squash-merged**, so the branch's commits are never ancestors of
  `main`. After a merge, reset the branch from `origin/main` and
  **force-with-lease** — but verify by **content diff** first, because
  `git log branch ^main` will list every already-merged commit and look alarming.
- **Verify by building BOTH site types.** A stale component reference behind the
  `isLocal` branch passed the informational build and crashed the local one.

### Open items

- ~~The **ratified links-per-index figure**~~ — **ratified at 25** by the owner
  2026-08-05 and upstream in **Page Type Reference v3.6** §1.2 (body links only,
  excluding the global nav/footer set; the two agree). It now **blocks approval
  until acknowledged**, like the >200 matrix gate; both clear via `acknowledge`
  on the approve route, and planning errors never do. Remaining: fold the figure
  into the **SOP's** link-equity section — the reference half is done.
- **Reference is now v3.6** (`docs/reference/page-type-reference-v3_6.md`, the
  v3.4 capture is retired). Besides the 25, **v3.5 promoted Areas We Serve and
  Services Index to CORE-conditional (auto-triggered)** — Areas We Serve on any
  multi-city site (≥2 cities), Services Index above 8 top-level services. The
  planner already fired on exactly those thresholds; what changed is that they
  are *infrastructure, not optional*.
- **Areas We Serve triggers at ≥ 6 cities** (owner ruling 2026-08-06), settling
  reference R6's open threshold and **superseding the ≥ 2 in the vendored v3.6
  capture** — the capture is faithful, so the ruling lives in the PRD amendments
  block until the Doc is revised. A 2–5 city site therefore has location pages
  and a matrix but no location hub, and nothing in its global nav points at the
  location silo (those cities are reached from the homepage grid, the matrix
  pages' structural links, and the HTML sitemap). The number lives in
  `website_plan.AREAS_WE_SERVE_TRIGGER` **and** `site-template/src/lib/hubs.ts`
  — the planner decides whether to plan the hub, the template whether to render
  it, and if they disagree the symptom is a 404 in the global nav.
- **Component renaming is done**, but 13 library components remain unbuilt and
  are listed in `site-template/src/theme/manifest.ts::MISSING_COMPONENTS`; each
  gates a page type that has no writer anyway.
- **The two CORE-conditional hubs now render** (2026-08-06). `/areas-we-serve/`
  and `/services/` have routes in the template, built from the same
  published-pages query as structural linking — so the listing half needs no
  writer at all. Both are conditional on their reference triggers (>= 2 cities;
  > 8 top-level services) via a `getStaticPaths` that returns `[]`, because
  building a hub the reference says not to build would put a thin unlinked page
  in the XML sitemap. **Writer #6 still owns the narrative copy** that brings
  them up to the reference's depth band; until then they ship as accurate hubs
  with a factual lede rather than as pages that cannot ship at all. Thresholds
  live in `site-template/src/lib/hubs.ts` and mirror `website_plan.py` — the
  same rule evaluated in two places, so a change to one needs the other.
- **Client-side 404 search** (Pagefind) not built; the 404 points at the HTML
  sitemap.
- Core-pages prompt copy, pilot clients, and a local-business design export as a
  second compiler fixture are owner tasks.

## ⏩ Update — 2026-07-12 · **LeadOff v2 BUILT: paid tryout/scout, neighborhoods tab, SOP routing + the grants repair**

PRD §5 items 1/3/4 shipped (item 2, the create-client handoff, shipped earlier
the same day in #339). Detail in the CLAUDE.md LeadOff paragraph.

- **Paid actions**: `POST /leadoff/tryout` (~$0.20/city, async job →
  `leadoff_tryouts` + a Tryouts tab) and `POST /leadoff/scout` (~$0.10–1,
  cache-cheapened; free `GET /leadoff/scout/estimate` preflight) — ported from
  `docs/reference/leadoff-scanner/check_city.py` / `enrich_shortlist.py`
  (committed reference copies; the cache contracts MUST NOT drift — the
  PowerShell tools write the same `market_scanner` cache rows).
- **Budget guard**: `leadoff_spend` ledger + `leadoff_daily_budget_usd`
  (config, default **$5/user/day**) — raise it on PLATFORM if the team needs
  more headroom. Migration `20260712120000` applied live.
- **⚠ Grants gotcha (bit us in prod)**: the scanner's loader drop/recreates
  `market_scanner` tables on reload, which STRIPS `service_role` grants — the
  deployed board was permission-broken until 2026-07-12. Fixed live:
  `grant usage on schema market_scanner to service_role;`
  `grant select on all tables in schema market_scanner to service_role;`
  `grant insert on market_scanner.domain_backlinks, market_scanner.business_reviews, market_scanner.demand_trend to service_role;`
  and — so future reloads keep them —
  `grant market_scanner_loader to postgres;`
  `alter default privileges for role market_scanner_loader in schema market_scanner grant select on tables to service_role;`
  (Default privileges cover SELECT only; if the loader ever recreates the three
  cache tables, re-grant INSERT.)
- No new env vars (reuses `DATAFORSEO_LOGIN/PASSWORD`). DataForSEO 40203
  (daily money limit) aborts a job without recording; balance context lives
  in `docs/reference/leadoff-scanner/scanner-CLAUDE.md`.

## ⏩ Update — 2026-07-11 · **LeadOff market-intelligence module (v1 read-only) BUILT**

The suite's pre-client "which market do we enter" tool — the LeadOff scanner's
graded board (34,352 US city×category markets + neighborhood combos), served
from Supabase schema `market_scanner` into a new suite-level page.

**What exists (detail in the CLAUDE.md paragraph + `docs/modules/leadoff-prd-v1_0.md`):**
- Backend: `services/leadoff_db.py` (schema-scoped client, fanout pattern),
  `services/leadoff.py` (pure grade/economics logic), `routers/leadoff.py`
  (`GET /leadoff/board`, `GET /leadoff/market-brief`). Config:
  `leadoff_prefetch_rows`. No migration — the `market_scanner` tables are
  populated by the external scanner; `service_role` grants already applied.
- Frontend: `pages/LeadOff.tsx` at `/leadoff` + sidebar entry (Radar icon).
- Agent layer: `docs/sops/LeadOff_Market_Intelligence_SOP.md` (+ byte-identical
  vendored copy in `agent_docs/sops/`, registered in `docs/sops/README.md`).

**Verification done:** 15 new pytest green (`tests/test_leadoff.py`, pure
logic); `npm run build` clean. Full backend suite NOT run in this (Windows)
workspace — deps aren't installed locally; note `test_sop_library.py`'s
vendored-sync test fails on clean `main` here too (a cp1252 locale artifact
reading `_ORCHESTRATOR.md`, passes on Linux/CI) — pre-existing, not from this
change.

### 🚦 To activate
1. Supabase dashboard → API settings → **Exposed schemas** → add
   `market_scanner`. (Grants to `service_role` are already applied.) Without
   this, `/leadoff/*` returns PostgREST schema errors.
2. Deploy PLATFORM + frontend as usual. No env vars needed for v1 (read-only).
3. Smoke: open `/leadoff` → board renders with `data 2026-07`; click a row →
   brief shows top-5 competitors; Vancouver WA Locksmith should show cached
   scouting enrichment (RD/velocity from the shared caches).

## ⏩ Update — 2026-07-05 · **SerMaStr Phases 0–4 BUILT — dormant behind `strategist_enabled=false`**

The strategist agent from `docs/modules/seo-strategist-agent-plan-v1_0.md` is
**built end-to-end (Phases 0–4; Phase 5 Asana push deliberately out of scope)**
in one overnight autonomous run. Migration `20260704180000_strategy_reviews`
is **applied to the live Supabase project**. Nothing is active in production:
every trigger path (on-demand API, weekly scheduler pass, both escalation
hooks, the Slack action) checks `strategist_enabled`, which ships **FALSE**.

**What exists now (detail in the CLAUDE.md paragraph):**
- **Phase 0** — `services/strategy_digest.py` (signal envelope w/ deterministic
  `status`, keyword passports, staleness flags, isolated providers) +
  `services/sop_library.py` (active-domain SOP selection over `docs/sops/` +
  the DB `sop_store` layer + module cards; corpus **vendored** at
  `writer/platform-api/agent_docs/` because the Docker build context can't see
  repo-root `docs/` — a unit test keeps the copies byte-identical).
- **Phases 1+3** — `services/strategist.py` (bounded tool-use run →
  `strategy_reviews` row; `sanitize_review` enforces §3 in code) +
  `services/strategist_tools.py` (serp_deep_dive / geogrid_history LLM
  subagents; episode_timeline / read_sop / client_capacity deterministic;
  audit_page paid+capped) + `routers/strategist.py` + the Action Plan
  **Strategist Review card** (Approve/Dismiss; senior proposals need admin).
- **Phases 2+4** — weekly active-signal-only pass on the shared scheduler
  (Tuesday, day after the reopt build); SerMaStr Slack action
  ("strategy review for <client>", reply-*yes*); escalation briefs riding
  `episode_escalated` + the new sitewide-decline transition detector.

**Verification done:** 994 pytest green under the pinned `fastapi==0.115.0`
import-check; real `npm run build` clean; an 8-angle code review ran before
push — 6 confirmed findings fixed (senior-approval now enforced at the API,
per-trigger job dedup so escalation briefs can't be swallowed, DB sop_store
folded into the run, dead budget-domain read, orphaned-review cleanup,
completed_at timing). Also fixed 3 pre-existing drifted `test_run_dispatch`
assertions (fanout `generate_service_page_core` returns a run id now).

### 🚦 To activate (the smoke gate — spec §7)
1. Set `STRATEGIST_ENABLED=true` on the **PLATFORM** Railway service (env var
   → redeploy). Nothing else is needed — schema is live, Slack/notifications
   already provisioned.
2. Smoke-test: open a client's **Action Plan** page → "Strategist Review" card
   → **Run review** (or in Slack: "strategy review for <client>" → reply
   *yes*). Expect a review in 1–3 minutes: assessment, findings w/ SOP
   citations, proposals (senior-only badged), questions.
3. Judge 2–3 real clients' reviews (Kyle/Ryan). If they'd have been your
   calls, leave it on — the weekly pass (active-signal clients only) and the
   escalation briefs are then live automatically. If not, set the flag back
   to false; everything goes dormant again.

**Deferred / notes:** Phase 5 (approved proposal → Asana task) rides the
Asana-push build. `docs/sops/` + module-card edits must be re-copied into
`writer/platform-api/agent_docs/` (pytest fails loudly if you forget).
Weekly-scope/model/digest-destination/approval-surface all use the spec §9
defaults (Sonnet everywhere; shared Slack channel; active-signal only;
Action-Plan-first).

---

## ⏩ Update — 2026-07-04 · **SerMaStr — Search Marketing Strategist Agent, spec approved** — **MERGED to `main`** (PRs #218 `c7254fd` + #219 `2166a03`; spec only, nothing built yet)

The reasoning layer atop the deterministic agent loop now has an **approved
plan of record**: **`docs/modules/seo-strategist-agent-plan-v1_0.md`**. The
agent's name is **SerMaStr** — **SE**arch **MA**rketing **STR**ategist (owner
ruling, #219). The existing Slack assistant is this agent's conversational
surface — one identity: the Q&A/actions bot today, plus the strategist mode
the plan adds. Scope is the whole search surface (organic, local pack/maps,
AI-answer visibility, content, links/offpage, budget) — deliberately *not*
"a strategist for LLM visibility."

**Locked decisions (decision records in the spec):**
- **Per-domain standing LLM monitors rejected** — monitoring stays
  deterministic (already built); strategy is the cross-domain part (one
  shared budget, interlocking SOPs). Architecture: **one strategist run per
  client**, event-driven (weekly for active-signal clients + escalation
  events + on-demand), with **bounded drill-down tools** (≤4/run; only
  `serp_deep_dive` + `geogrid_history` are true LLM subagents).
- **Proposes, never executes.** Advice objects with SOP citations, staged for
  Approve/Dismiss; six hard-coded human passthroughs from `_ORCHESTRATOR.md`
  §3 (freeze, GBP suspension, sub-50% margin, separate-entity calls,
  overclock, the 6-week review itself). Unowned decisions → questions.
- **Escalation briefs:** the 6-week rule's critical notification gains a
  prepared case file (what was tried / what moved / recommendation) instead
  of a bare alert.
- **Module legibility (spec §2b):** module cards + a standard signal envelope
  (`direction` + deterministically-computed `status` — the LLM never does
  trend arithmetic) + the **keyword passport** (digest grouped by keyword
  across channels) + explicit staleness + self-documenting tools. First three
  **module cards written** at **`docs/agents/module-cards/`** (rank-tracker,
  geogrid-tracker, labs-ai-visibility — each with a worked misreading, e.g.
  "average_rank without found_pins", "null GSC position ≠ rank loss", "one
  AI answer-flip ≠ trend"). Cards can be wired into SerMaStr's Slack context
  providers immediately, before the strategist ships.
- **Cost:** ≈ $1–2/client/mo typical (Sonnet-class), $0 for quiet clients.
- **Smoke gate:** Phase 1 is on-demand only (`strategist_enabled` default
  false); weekly scheduling only after Kyle/Ryan judge 2–3 real reviews.

**Next build (on "go"):** Phase 0–1 — `build_strategy_digest` (signal
envelope + keyword passport + staleness + SOP/module-card retrieval),
`strategy_reviews` migration, the on-demand run, and the Action Plan
"Strategist Review" card. The **Asana task push** (plan lines → assigned
Asana tasks) remains queued as its own build and later becomes SerMaStr
Phase 5. Open §9 defaults to confirm at build time: Sonnet everywhere;
digests to the shared Slack channel; weekly = active-signal clients only;
approvals Action-Plan-first.

---

## ⏩ Update — 2026-07-04 · **SOP library + 24/7 SEO agent phase 1** — **MERGED to `main`** (PRs #215 `3e3c828` + #216 `73e6e15`, both deployed & live)

The session that turned the agency's SOP corpus into a running machine. Two
merged PRs: **#215** (the SOP library + the whole agent loop) and **#216** (the
Recipe Engine frontend + a production hotfix). Everything below is **live** —
all six migrations were applied to the live Supabase project during the build,
and the PLATFORM deploy of `main` is healthy.

**The agent loop (all built, all running on the shared scheduler):**

```
detect      trackers + daily freeze check + offpage/citation/imbalance sweeps
classify    B1–B5 + §A sitewide scope (drop_classifier.py)
decide      SOP response playbooks rendered in the Action Plan
cost/assign Recipe Engine → monthly task plan (margin-aware, roles-matrix)
verify      response episodes: 2-week rechecks / 6-week escalate → Kyle/Ryan
kill switch Freeze Protocol (freeze pauses all content + link output)
```

**What shipped, by module** (full detail in each CLAUDE.md paragraph):

1. **`docs/sops/`** — the 11-doc SOP library imported with a consistency pass:
   drift fixes across every doc, the On-Page thresholds resolved from the live
   nlp-api scoring code (bands ≥90/≥80/≥70/≥60; deficiency bar = engine < 80;
   operational pass line 90), four owner rulings (plan-time Step 8 gate;
   threshold-gated overclock self-serve; RD 250 = guideline not cap; LABS
   engine list aligned to the built module), and the capacity workbook's dead
   formulas wired. **Read `docs/sops/README.md` first** — `_ORCHESTRATOR.md`
   is the router.
2. **Freeze Protocol** — `client_freezes`, router/worker/fanout gates
   (409 `client_frozen`), daily `freeze_check` (GSC URL-Inspection → auto
   deindexing-freeze; DataForSEO `site:` probe warn-only), `FreezeBanner` on
   the workspace (admin freeze/lift). Manual actions have no Google API — a
   human confirms via the banner.
3. **Recipe Engine** — SOP §1–§5 as code, conformance-tested against the §4
   worked example ($2,000 → $0 remaining, exact). Auto-diagnosis from suite
   data. **Frontend:** workspace "Monthly Task Plan" card → generate (66%/50%
   margin), summary strip, flags, assigned task table, CSV, history.
4. **Drop classifier** — open rank alerts arrive classified (B1 cannibalization
   / B2 SERP-shift / B3 CTR / B4 indexing / B5 position; §A sitewide banner);
   the Action Plan renders each classification's SOP protocol + right-tool CTA.
5. **Response episodes** — every drop response has the SOP clock: baseline at
   open (organic weighted position / maps geo-grid `average_rank`), 14-day
   rechecks, recovered when the tracker resolves the alert, **escalated once
   at 6 weeks** with no improvement (critical notification; improving episodes
   never escalate). Clock notes append to Action Plan rows.
6. **Offpage agent** — RD loss / unnatural spike from `backlink_profiles`
   (both relative + absolute bars), **citation liveness** (paste-in list at
   `clients/:id/citations`; fail-open — only hard 404/410/DNS ×2 consecutive
   = dead; bot-blocks count alive), **per-page RD imbalance** (monthly page
   summaries, inner page > homepage RD × 1.5 → info-severity rebalance).
   Every new alert triggers a silent Action Plan rebuild (`trigger="offpage"`).

### ⚠️ Incident (resolved) — PLATFORM crash-loop after the #215 deploy

The `DELETE /citations/{id}` route used `status_code=204`, which the pinned
`fastapi==0.115.0` rejects **at import time** → the whole API crash-looped
~07:34–07:45 UTC ("client cards aren't loading"). Fixed in #216 (200 + JSON
body), verified by importing all 30 suite modules under the pinned FastAPI.
**Process rule going forward:** backend changes are import-checked under the
pinned requirements before push (the sandbox's newer FastAPI had masked it),
and frontend changes run the real `npm run build` (which also caught a React
19 `JSX` namespace break earlier).

### 🔧 Operator to-dos (the loop idles until these are done)

1. **Set each client's budget** — client form → "Budget & Campaign Type"
   (monthly budget with live 34%-deployable readout; local/enterprise funding
   order; SAB toggle → $130 baseline).
2. **Paste citation lists** — client workspace → Citations card → paste the
   URLs from vendor deliverables (weekly liveness sweep starts from there).
3. **Smoke-test one client** — generate a Monthly Task Plan and gut-check it;
   open + lift a manual freeze and confirm the Slack ping + the 409 gates.

No migrations to apply — unlike prior handoffs, **all schema is already live**
(`client_freezes`, `recipe_engine`, `response_episodes`, `offpage_alerts`,
`citations_page_backlinks`).

### Deferred / next builds (each a clean follow-up PR)

- **Asana task push** — one Asana task per plan line, assigned per the roles
  matrix (the Asana integration already exists). Highest-leverage next step:
  closes the loop from "plan generated" to "task in Minda's queue".
- Algo-update detection (cross-client drop correlation).
- On-page coverage audit (blog/service/location scoring parity with local).
- LABS "mention AND link" win rollup + AIO Fork A/B classification.
- Recipe Engine refinements: gap-sized funding quantities; cross-client
  capacity from the workbook; per-person escalation routing.
- SOP paper debt: anchor-ratio ledger (the freeze health check references it),
  T1 Booster spec, LB recipe decision matrix.

---

## ⏩ Update — 2026-06-29 · **Maps geo-grid strategy & Action Plan** — **MERGED to `main`** (PR #182, squash `35394ae`)

Brought the **Maps geo-grid tracker** to parity with the organic rank tracker's
reoptimization guidance, then layered on strategic competitive intelligence —
all feeding the **unified, deep-linked Action Plan** (`reopt_planner` →
`pages/ActionPlan.tsx`). Authoritative doc:
**`docs/modules/maps-geogrid-strategy-prd-v1_0.md`**.

**What shipped:**
- **Phase 1 — Maps Action Plan (hybrid).** Pure `build_maps_actions` (separate
  from organic `build_actions`) feeds the **shared** `reopt_plans` store + view +
  cadence (weekly digest + **silent on-drop rebuild** via `maps_analyzer`
  `trigger="maps_drop"`). Reuses `maps_alerts` + geocoded weak areas. Actions are
  tagged `source: organic|maps`; Maps declines are **not** deduped against organic
  drops (distinct channels).
- **Phase 2 — Tier A** (reuse existing data, no new fetch): **Share of Local
  Voice** (`services/maps_solv.py`, derived on read) + **brand-search analysis**
  (`services/brand_search.py`, branded vs non-branded GSC demand).
- **Phase 3 — Tier B** (competitor intelligence; each = a deterministic service +
  async job + migration + Maps-tab panel + an Action Plan action):
  **B1** competitor GBP intelligence (`competitor_gbp.py`), **B2** GBP profile
  audit (`gbp_audit.py`), **B3** review analytics (`review_analytics.py`), **B4**
  backlink authority (`backlink_intel.py`), **B5** on-site content comparison
  (`content_intel.py`), **B6** Local Relevance Scorecard (`local_relevance.py` —
  does each signal align with the tracked service/location?) incl. **business
  type** (SAB / physical / hybrid, `gbp_service.classify_business_type` via
  Outscraper's `area_service` hidden-address flag).

**New Action Plan action kinds:** `maps_decline`, `maps_competitor`,
`maps_weak_area`, `maps_solv_drop`, `gbp_gap`, `review_gap`, `backlink_gap`,
`content_gap`, `local_relevance`, `brand_search_decline` (all rendered generically
in `ActionPlan.tsx`).

**Verified:** ~105 pure-unit tests across the new services (mocked external
APIs); frontend `tsc -b` clean; every commit's Netlify preview built green.

**Deterministic trims (noted in the PRD, each a clean follow-up):** review
sentiment/themes (B3 — `reviews.sentiment` column reserved), per-referring-domain
backlink gap list (B4), semantic/entity content comparison (B5 — currently depth +
heading coverage). Competitor GBP/reviews/backlinks/content/relevance refreshes
are **on-demand** today (monthly auto-refresh via the scheduler is a follow-up).

### ⚠️ Maps-strategy provisioning still required (one-time)

The code is on `main` and deploy-ready, but inert until the migrations are applied.

1. **Apply these migrations** to the live Supabase project (all additive — new
   tables + a `job_type` CHECK widen), in order:
   `20260629160000_competitor_gbp_profiles`, `20260629180000_reviews`,
   `20260629190000_backlink_profiles`, `20260629200000_website_analyses`,
   `20260629210000_local_relevance_scores`, `20260629220000_business_type`.
   - **Note on the `async_jobs.job_type` CHECK:** each of the above rewrites it to
     a **superset**. The merge reconciled a drift where `main`'s Asana migration
     (`20260629130000`) had dropped `client_report` + `maps_analyze` from the list;
     these migrations **restore** those and add `asana_monthly` + the six new Maps
     job types (`competitor_gbp`, `review_intel`, `backlink_intel`, `content_intel`,
     `local_relevance`). The final constraint (after `…210000`) is the complete
     union — apply in timestamp order and the end state is correct.
2. **No new env vars.** Every layer reuses already-provisioned creds on
   **PLATFORM**: `DATAFORSEO_LOGIN/PASSWORD` (SoLV competitor data, backlinks,
   reviews, SERP for content), `OUTSCRAPER_API_KEY` (competitor GBP + business
   type), `SCRAPEOWL_API_KEY` (GBP-link + competitor page scrapes),
   `GOOGLE_SERVICE_ACCOUNT_KEY` (brand-search reads `gsc_query_daily`).
3. **Deferred — GBP engagement (#8):** profile views / calls / direction requests
   over time. Needs Google **OAuth 2.0** (`business.manage`) per listing owner +
   GCP provisioning — **incompatible** with the suite's service-account model.
   Parked as its own project (would add `GOOGLE_CLIENT_ID/SECRET` + a per-client
   refresh-token flow + a `gbp_engagement_metrics` table).

---

## ⏩ Update — 2026-06-29 · **Asana task integration**

Connects AR Tools to the team's Asana workspace. **Two features, one token**
(**PR #170 merged to `main`**, squash `5587b0c`; Phases 0–3 built; a by-name
field-resolution follow-up + optional Phase 4 ahead — see Provisioning progress
below):

- **A. Monthly section automation** — each client has an **app-defined task
  template** (its own editable monthly task list, edited in AR Tools). A job
  creates those tasks in the client's Asana project under a new **`<Month YYYY>`**
  section: assignee + category carried, **Status = Not Started**, **no due dates**,
  inserted above the backlog, **idempotent** (re-run = no-op). Runs **auto on the
  1st** (shared `gsc_scheduler` → `asana_monthly` job) **and** via a **"Generate
  this month"** button. UI: client workspace → **Project Management → Asana Tasks**
  (`/clients/:id/asana-tasks`) — the template editor (name + assignee + category
  pickers populated from Asana) + project-GID field + generate button.
- **B. Team Workload** — a suite-level **"Workload"** nav page (`/workload`,
  `GET /asana/workload`) showing each tracked member's open **hours** across all
  clients vs their **weekly capacity** (effort-weighted), with per-day due-hours
  chips + over-capacity flags + a **Team & capacity** editor (pick members from
  Asana, set weekly hours). A **daily** scheduler check
  (`asana_workload.run_workload_alert`) emits one suite notification (in-app +
  Slack) when anyone is over capacity. Effort per task = an **Asana number field**
  the monthly job stamps from each template row's **Est. hrs**.

**Code:** `services/asana_service.py` (REST client + pure helpers),
`services/asana_monthly.py` (Feature A), `services/asana_workload.py` (Feature B),
`routers/asana.py`, `models/asana.py`; frontend `pages/AsanaTasks.tsx` +
`pages/TeamWorkload.tsx`. Migrations `20260629120000_asana_client_projects.sql`
(client→project map) + `20260629130000_asana_task_templates.sql` (per-client
template + widens `async_jobs.job_type` for `asana_monthly`) +
`20260629140000_asana_effort_capacity.sql` (`est_hours` on templates +
`asana_team_members` team/capacity table). Everything **degrades gracefully** —
absent the token / mapping / team list, the relevant feature is skipped with a
note, never an error (the GSC/Slack pattern).

**Verified:** the Asana test suite is green (`test_asana_service`,
`test_asana_monthly`, `test_asana_workload`); frontend typechecks + builds clean.
Nothing runs live until the provisioning below is done.

### ⚠️ Asana provisioning still required (one-time)

The code is deployed-ready but inert until these are set. All secrets/vars go on
the **PLATFORM** Railway service.

1. **Apply the migrations** to the live Supabase project (all additive — new
   tables + columns + a `job_type` constraint widen): `20260629120000_asana_client_projects`,
   `20260629130000_asana_task_templates`, `20260629140000_asana_effort_capacity`.
2. **Token + workspace** — create an Asana **Personal Access Token**
   (developers.asana.com → *My access tokens*) → set **`ASANA_TOKEN`**. Set
   **`asana_workspace_gid`** = your workspace GID (`GET https://app.asana.com/api/1.0/workspaces`
   with `Authorization: Bearer <token>`).
3. **Custom-field GIDs** — for any client project, call
   `GET /projects/<project_gid>/custom_field_settings?opt_fields=custom_field.name,custom_field.gid,custom_field.resource_subtype,custom_field.enum_options.name,custom_field.enum_options.gid`
   and read off: the **Status** field GID + its **"Not Started"** option GID, the
   **category** field GID, and (for workload) a **number** field for effort. Set
   **`asana_status_field_gid`**, **`asana_status_not_started_option_gid`**,
   **`asana_category_field_gid`**, **`asana_effort_field_gid`**. (Absent these,
   tasks are still created — just without that field stamped. For effort: create a
   number custom field like "Est. hours" on the projects first if you don't have
   one.)
4. **Per-client project mapping** — in the app: open a client → **Asana Tasks** →
   paste the project GID (from the Asana project URL `app.asana.com/0/<project_gid>/…`)
   → **Save**. One per client.
5. **Per-client task templates** — fill each client's monthly task list in the
   **Asana Tasks** editor (no Asana "Template" section needed — the app is the
   source of truth).
6. **Team list + capacity (Feature B)** — add members in the **Workload** page
   ("Team & capacity": pick from Asana users, set each one's weekly hours). The
   env **`asana_team_member_gids`** is a fallback seed only (default capacity).
7. **Effort estimates** — set **Est. hrs** per task in each client's **Asana Tasks**
   editor. The monthly job stamps them into the effort field; the workload view is
   blind to effort until they're filled (unestimated tasks count as
   `asana_default_task_hours`, default 1h).
8. *(Optional, no code)* install Asana's official **Slack app** for the Slack ⇄
   Asana leg (task notifications in Slack + create-task-from-Slack).

**Cadence / tunables (config.py, optional):** `asana_month_generate_day` (default
`1`), `asana_month_target_offset` (default `0` = current month), feature toggles
`asana_monthly_enabled` / `asana_workload_enabled`; workload capacity
`asana_default_weekly_hours` (30), `asana_workload_daily_workdays` (5),
`asana_workload_backlog_weeks` (2), `asana_default_task_hours` (1).

**Next (optional Phase 4):** two-way sync (Asana webhook → close rank alerts /
mark Action Plan items done), per-client Asana-project mapping CRUD UI.

### 📍 Provisioning progress (2026-06-29) — where we are

**✅ Merged + deploying.** **PR #170 is merged to `main`** (squash `5587b0c`;
resolved conflicts with main's Client Reports / `maps_analyze` work, keeping both
sides). PLATFORM (deploys from `main`) + Netlify rebuilt from the merge commit, so
the `/asana/*` endpoints and the Asana Tasks / Workload pages are now in the
production build.

**🔑 Key decisions (2026-06-29) that shape per-client setup:**
- **One ongoing project per client** (decided with the user). Their Asana was
  organized as **per-quarter** projects (e.g. "WheelHouse IT Q2 2026"); going
  forward they move to a single long-lived project per client (months as
  sections). So the integration's **fixed** client→project mapping is correct —
  **no quarter-rollover logic needed**. (Team-side workflow change; no code impact.)
- **Custom fields are project-local.** The pilot's "Status" + "Service Type" fields
  are NOT workspace-library fields — each project has its own copies, so their GIDs
  very likely **differ per client project**. The global `asana_status_field_gid` /
  `asana_category_field_gid` therefore only match the pilot. **Planned next
  (follow-up PR): resolve these fields BY NAME per project** ("Status" + its "Not
  Started" option, "Service Type", + the hours number field) at task-creation time,
  so onboarding a client is just *map project + build template* with no GID lookups.
  Until that ships, only the pilot project's tasks get Status/Service Type stamped.

**✅ Migrations applied to live Supabase** (`wvcthtmmcmhkybcesirb`, via MCP):
`asana_client_projects`, `asana_client_task_templates` (+ `est_hours`),
`asana_team_members`, and `async_jobs.job_type` widened for `asana_monthly`.
NB: the live `job_type` CHECK had two values **not** in any repo migration
(`client_report`, `maps_analyze` — pre-existing drift); I preserved them when
widening (dropping them would fail constraint validation on existing rows).

**✅ Railway PLATFORM env set** (token by the user; the rest via the Railway MCP):
- `ASANA_TOKEN` ✅ (secret, set by user)
- `asana_workspace_gid` = `1143356380295200`
- `asana_status_field_gid` = `1214452613145654` ("Status")
- `asana_status_not_started_option_gid` = `1214452613145655` ("Not Started")
- `asana_category_field_gid` = `1214452613145672` ("Service Type": Content /
  Link Building / GBP Authority / Strategy)
- `asana_effort_field_gid` = **not set** — the pilot project has no number custom
  field. To enable effort-weighting: add an "Est. hours" **number** field to the
  client projects, re-run the per-project `custom_field_settings` call, and set
  this GID. Until then Workload treats every task as `asana_default_task_hours`
  (1h).

**Pilot project:** Asana project GID **`1214452202356916`** (Status field
`1214452613145654`, "Not Started" option `1214452613145655`, Service Type
`1214452613145672`). A second client checked ("WheelHouse IT") has the **same field
names** but project-local GIDs — hence the by-name-resolution plan above.

**Per-client onboarding flow (the end state):** (1) one ongoing Asana project per
client; (2) map it in the **Asana Tasks** page (paste project GID → Save); (3) build
its monthly **template** (tasks + assignee + Service Type [+ est. hrs]). Then the
monthly job adds a `<Month YYYY>` section automatically each month.

**Task-template instantiation (built, separate PR):** the team's recurring tasks
are **Asana task templates with subtasks**. The monthly job now **instantiates**
the matching Asana task template (by name) so subtasks come along, then sets
assignee/category/status + moves it into the month section; rows with no matching
template fall back to a plain task. The Asana Tasks editor marks matching rows
with **⊟**. No migration. Endpoint `…/asana/project-task-templates`.

**Task Library (built, separate PR):** a global `asana_task_library` (migration
`20260629170000`, **applied to live**) — the single source of truth for standard
task **durations** (+ default category), keyed by **task name**. Client template
rows inherit `default_hours` / category by name when blank (override per client by
filling the row). Managed at **`/asana/task-library`**; the template editor's
task-name input has a datalist of library names + an inherited "(lib)" hours hint.
Hours feed auto-distribution immediately; they reach Asana once the effort number
field exists. (The workload read also now sums the effort field **by name**, so
real hours work across project-local fields once that field is added + named.)

**Auto-distribution (built, separate PR):** a template row's assignee can be set to
**Auto-distribute** instead of a person; the monthly job spreads those tasks across
the client's **eligible team subset** ("Auto-assign team" picker on the Asana Tasks
page → `auto_assignee_gids`) by **remaining capacity** (weekly hours − current open
hours across all clients, weighted by est. hrs). Pinned rows stay pinned. Migration
`20260629160000` (`auto_assign` + `auto_assignee_gids`) — **applied to live
Supabase**. Needs tracked team members with capacities set (Workload page).

**⬜ Remaining:**
1. **Ship the by-name field resolution** (follow-up PR) so per-client setup needs no
   GID lookups — the next build step.
2. Smoke-test the token: open a client → **Asana Tasks**; the **Assignee** dropdown
   should populate from Asana (proves the live connection).
3. **Map clients → projects** (in-app, one ongoing project each). Pilot:
   `1214452202356916`.
4. **Build per-client task templates** and run **Generate this month** to verify.
5. **Team & capacity** (Workload page) — add tracked members + weekly hours.
6. *(optional)* add an "Est. hours" **number** field to projects + per-task est. hrs
   for hours-based workload (none on the pilot/WheelHouse projects today).

---

## ⏩ Update — 2026-06-28 · **Slack conversational assistant (SerMastr)**

Two-way Slack, **channel mode**: SerMastr lives in a **dedicated channel** and
answers **every plain human message there — no @mention needed** — a
natural-language question about a client's search performance, grounded in the
cross-module context (below), via Claude, posted back **in-thread** with thread
memory. Also works in **DMs**. It answers questions AND can **take actions**
(below). Anyone in the workspace can ask/act (product decision). Its own posts
(rank-drop alerts) + other bots + edits/joins are ignored, so it never loops.

- **Actions (NL → trigger work):** via Claude tool-use in `interpret()`. Tools =
  `_ACTIONS` (append to add one): `rebuild_action_plan` (free → runs immediately),
  `run_maps_scan` / `run_gsc_research` / `run_ai_visibility_scan` (**paid → staged
  behind an explicit confirm**). Each runner enqueues an EXISTING job
  (`reopt_planner.build_plan`, `local_dominator.enqueue_maps_scan`,
  `gsc_research.enqueue_gsc_research`, `brand_service.start_scan`). Confirm flow: a
  paid request stores a pending entry keyed by `(channel, thread_ts)` in the
  in-memory `_pending` (single-replica PLATFORM; a redeploy just drops pending →
  user re-asks) and replies "…reply *yes* to proceed"; the next `is_affirmative`
  message in that thread runs it (the pending carries its own `client_id`, so the
  "yes" needn't re-name the client). Read-only Q&A stays open; a paid action never
  runs without a confirm.

- **Inbound:** `routers/slack_events.py` → `POST /slack/events` (public; the only
  guard is Slack request-signature verification, fail-closed). Answers the
  url_verification handshake, acks within Slack's 3s window, runs the answer in a
  BackgroundTask (Claude > 3s). Handles `message` events with `subtype ∈ {None,
  thread_broadcast}` and **no `bot_id`** (skips the bot's own/alerts + other bots +
  retries). `message` events also cover @mentions (the mention is stripped), so we
  do **not** also handle `app_mention` — that would double-reply.
- **Logic:** the `services/slack_assistant/` package (helpers/prompts/context/actions/llm; split 2026-07-10) — pure helpers (`verify_slack_signature`,
  `strip_mention`, `resolve_client`, `format_context`, `format_history`, unit-tested)
  + `build_context` + `fetch_thread_history` (conversations.replies → prior turns)
  + `interpret` (Claude tool-use, `slack_assistant_model`=`claude-sonnet-4-6`, folds
  thread history into the prompt; returns `("action", tool)` or `("text", answer)`)
  + `is_affirmative` + `post_message`/`handle_message`. Every message gets a reply:
  an answer, an action/confirm, or a "which client?" prompt when none resolves.
- **Cross-module context (extensible registry):** `build_context` runs every
  provider in `_CONTEXT_PROVIDERS`, each isolated (one module failing/empty never
  breaks the answer) and keyed under its module name, so the LLM can tell "no data
  for this module" from real data. Current providers: `organic_rank` (keywords
  w/ `rank_status.compute_keyword_summary`, open `rank_alerts`, latest `reopt_plans`,
  `gsc_research_runs`), `maps_geogrid` (latest `maps_scans`/`maps_scan_results` —
  avg rank, pin coverage, weak areas), `ai_visibility` (`brand_tracked_keywords` +
  latest `brand_mention_history` per-engine visibility + invisible count), `content`
  (completed `runs` by content_type + `local_seo_pages` saved/published),
  `keyword_research` (fanout `sessions` via the fanout-schema service client),
  `setup` (GBP/brand-voice/ICP/target-cities presence on `clients`).
  **To add a future module:** write `_ctx_<module>(supabase, client_id, today)`
  returning a compact dict (or None) and append it to `_CONTEXT_PROVIDERS` — it
  flows into every answer automatically. (Reserved-LogRecord gotcha: don't use
  `extra={"module": …}` — it collides; we use `ctx_module`.)
- **Config on PLATFORM:** `SLACK_SIGNING_SECRET` (**required** — without it the
  endpoint fail-closes and answers nothing), `slack_assistant_enabled` (default
  on), `slack_assistant_model`, `slack_assistant_max_tokens`,
  `slack_assistant_max_keywords`. Reuses `SLACK_BOT_TOKEN` + `ANTHROPIC_API_KEY`.

### ⚠️ Slack dashboard provisioning (one-time)
**Signing secret + Request URL are already done** (live). For **channel mode**
(answer untagged messages) the remaining steps are:
1. **OAuth & Permissions → Bot Token Scopes** → add **`channels:history`** +
   **`groups:history`** (+ **`im:history`** for DMs) (keep `chat:write`;
   `app_mentions:read` is no longer needed but harmless) → **Reinstall to Workspace**.
2. **Event Subscriptions → Subscribe to bot events** → add **`message.channels`**
   (public) + **`message.groups`** (private) + **`message.im`** (DMs) → Save. (You
   can remove `app_mention` — `message.*` covers mentions too.) Request URL stays
   `https://platform-production-a5c5.up.railway.app/slack/events`.
3. Keep SerMastr in its dedicated channel.

(History scopes power the in-thread memory via `conversations.replies`. DM events
were a no-op until `im:history` + `message.im` are added; actions need no extra
Slack config — they reuse `chat:write`.)

Verified so far: import + **605 tests** (12 new), ruff clean (my files), frontend
unaffected. End-to-end Slack round-trip is **untested until the event
subscription + signing secret are provisioned** (above) — there's no way to
exercise the inbound path without a real signed Slack event.

**Next:** future levels if wanted — NL→action commands (trigger scans / rebuild
plans) with per-user authorization; DM support (`im:history` + `message.im`).

---

## ⏩ Update — 2026-06-28 · **Reoptimization planner / Action Plan** + notifications provisioning status

**Reoptimization planner — built & merged** (`#159`, squash `51f5237` → `main`).
PR 2 of 2 on the notifications pipe. Per-client, recommend-only **Action Plan**:
`build_actions` maps the rank tracker's existing signals (open rank-drop alerts,
rankability Quick wins, GSC-Research cannibalization/hidden-wins) to a strictly
tiered action list, each deep-linking into the tool that does the work; nothing
auto-executes. `services/reopt_planner.py` (+ `routers/reopt.py`, `models/reopt.py`,
`pages/ActionPlan.tsx`, workspace card, route `clients/:id/action-plan`,
migration `…060818_reopt_plans` + `reopt_plan` job type). **Cadence:** on-demand
Rebuild; **weekly digest** (`enqueue_due_reopt_plans` on `reopt_plan_weekday`) is
the only auto-notification trigger; **on-drop refresh** (`trigger="drop"`, silent)
from `rank_materialize`. Verified: **593 tests**, ruff clean, frontend build clean.

### ⚠️ Notifications channel provisioning — current status (PLATFORM Railway vars)

The notifications **pipe is built**; in-app card alerts work **today** with no
config. The outbound channels stay dormant until their creds are set on the
**PLATFORM** service. Status:

- **📧 Email (SMTP) — DEFERRED by user (2026-06-28), set up later.** Vars to set
  when ready: `SMTP_HOST` (`smtp.gmail.com`), `SMTP_PORT` (`587`), `SMTP_USER`
  (sending address), `SMTP_PASSWORD` (**Google App Password**, needs 2FA on the
  account), `SMTP_FROM` (optional), `NOTIFY_EMAIL_TO` (comma-separated
  recipients). Email fires only when host+user+password+recipients are all set.
- **💬 Slack — CONFIGURED & live-verified (2026-06-28).** App **SerMastr**
  (`ar_tools`/display "SerMastr", bot `B0BDP9BDXPU`, team "Amazing Rankings")
  with `chat:write`, installed + invited to channel `C0BDM8E9FJA`. `SLACK_BOT_TOKEN`
  + `SLACK_DEFAULT_CHANNEL` set on PLATFORM. Verified end-to-end through the live
  worker (`notification_dispatch` → `channels_sent.slack="ok"`), not just a raw
  API call. (Setup gotcha for next time: the scope must be **`chat:write`** under
  *Bot* Token Scopes — `calls:write` looks similar and yields `missing_scope`;
  private channels need the bot invited and addressed by **ID**, not `#name`.)
- **🔗 `APP_BASE_URL`** (e.g. `https://ar-internal.netlify.app`) — makes the
  email/Slack "Open in AR Tools" deep links clickable; copies still send without it.
- Master switch `NOTIFICATIONS_ENABLED` defaults `true`. Each channel is
  best-effort and records `channels_sent` (ok/failed/skipped) per notification.

---

## ⏩ Update — 2026-06-28 · **Notifications service (in-app + email + Slack)**

The suite's long-deferred **notifications service** — the shared delivery pipe for
in-app alerts, email, and Slack. Built as **PR 1 of 2** toward the reoptimization
planner (the planner is PR 2; this proves the pipe on the existing rank-drop
alerts first). On branch `claude/notifications-service` — **draft PR**.

**Decisions (user):** email = **SMTP (Gmail/Workspace)**; Slack = **app bot token**;
planner cadence = **weekly digest + on-drop** (planner build is PR 2).

- `services/notifications.py::emit(client_id, kind, title, summary, severity, payload)`
  — writes a `notifications` row (in-app feed) + enqueues a `notification_dispatch`
  async job that sends email (`smtplib`, via `asyncio.to_thread`) + Slack
  (`chat.postMessage`) **best-effort, each gated on its creds**. `emit` never
  raises into the producer. Pure format/gating helpers unit-tested.
- **First producer:** rank-drop alerts. `reconcile_alerts` now returns
  `opened_alerts`; `rank_materialize` calls `emit` with a batched digest
  (`summarize_drop_alerts`) when new alerts open (severity critical if a deindex
  is among them).
- **In-app surfaces:** a red unread badge per client tile on **Home**
  (`/notifications/unread-counts`) + an **Alerts panel** in the client workspace
  (`components/ClientNotifications.tsx`) with mark-read / dismiss / mark-all-read,
  deep-linking via `payload.link`.
- **API:** `routers/notifications.py` — unread-counts, per-client feed,
  read/dismiss/read-all.
- **Config on PLATFORM (to provision):** `SMTP_HOST/PORT/USER/PASSWORD/FROM`,
  `NOTIFY_EMAIL_TO`, `SLACK_BOT_TOKEN`, `SLACK_DEFAULT_CHANNEL`, `APP_BASE_URL`.
  Until set, in-app works and email/Slack are skipped (channels_sent records it).

**Migrations (applied; filenames = recorded versions):** `…054924_notifications`
(table + `notification_dispatch` job type) and `…055434_async_jobs_jobtype_complete`
— a **drift fix**: the `async_jobs.job_type` CHECK was missing `local_seo_generate`,
`local_seo_reoptimize_url/page`, `brand_scan`, `brand_report` (dispatched by the
worker but not allowed — latent, none enqueued yet); recreated as the full set.

**Verified:** import main + **576 tests** on pinned fastapi==0.115.0/pydantic==2.9.2
(8 new); ruff clean (my files); frontend build clean. Email/Slack only run on
Railway once creds are set — first real drop is the live proof.

**Next:** PR 2 — the reoptimization planner as the second producer (weekly digest
+ on-drop), emitting through this pipe.

---

## ⏩ Update — 2026-06-28 · **GSC Research auto-cadence (first run + monthly)**

GSC Research (cannibalization / quick wins / hidden wins — the n8n port) was
**on-demand only**; now it also runs **automatically on first GSC-eligibility and
monthly**. Same branch/PR as the capture-cadence change (`claude/rankability-
capture-cadence`, PR #157).

- `gsc_scheduler.enqueue_due_gsc_research` (daily due-check, in the daily block):
  for each client with a **verified GSC property**, enqueue a run if it has **never
  had a completed run** (first-entry) or its last is **≥ `gsc_research_interval_days`
  (30)** old. Reuses `enqueue_gsc_research(trigger="scheduled")` (dedupes in-flight).
- Gated on GSC being **provisioned** (`gsc_research_auto_enabled` + a service-
  account key); GSC Research can't produce anything without GSC, so until
  `GOOGLE_SERVICE_ACCOUNT_KEY` is set + a property verified, **no auto-runs fire**
  (on-demand also returns empty in that state — unchanged).
- Pure `is_gsc_research_due` unit-tested. **No migration** (reuses `gsc_research_runs`).

⚠️ Note: this is **dormant until the standing GSC provisioning gap is closed**
(service account + Search Console API). It activates automatically once that's done.

**Verified:** import main + **568 tests** on pinned fastapi==0.115.0/pydantic==2.9.2
(2 new); ruff clean.

---

## ⏩ Update — 2026-06-28 · **Rankability capture cadence (cost control)**

Replaced the blanket **weekly** SERP-snapshot auto-capture with an event-driven
model (the snapshot is the cost; rankability reads it for free). On a **new
branch off main** (`claude/rankability-capture-cadence`) after #156 merged — new
draft PR.

- **Weekly auto-capture OFF** by default (`serp_snapshot_auto_weekly=False`; the
  weekly enqueue in `gsc_scheduler` is gated behind it). Flip to restore dense
  SERP-trend history.
- **First-entry opt-in:** after keywords are added (typed/CSV/suggestion), a
  banner offers "Run rankability" → captures snapshots for just those keywords
  (`RankKeywords.tsx`).
- **Drop-triggered (≤1/mo):** when any `rank_alerts` rule newly opens (all four,
  incl. deindexed), `rank_materialize` calls
  `serp_snapshot.enqueue_drop_triggered_snapshots`, which captures only keywords
  with **no snapshot in the last 30 days** (`serp_snapshot_drop_min_days`) — so a
  flapping ranking can't re-capture. `reconcile_alerts` now returns
  `opened_keyword_ids`.
- **Manual:** the per-keyword camera + Rankability tab stay ungated.

**Trade-off (accepted):** SERP Trends/timelines now only have points at those
events (sparser). **Config-only, no migration.**

**Verified:** import main + **566 tests** on pinned fastapi==0.115.0/pydantic==2.9.2
(2 new gate cases); ruff clean; frontend build clean.

---

## ⏩ Update — 2026-06-28 · **Topical focus (specialist vs generalist)**

Added a **topical-specialization** signal to the SERP snapshot + rankability: a
niche site dedicated to the keyword's topic can out-rank generalist incumbents
*even with weaker backlinks*, so a generalist-dominated SERP is an opening for a
specialist client. Part of PR #156 (draft).

- **Classifier:** one best-effort **Claude Haiku** call per snapshot
  (`classify_topical_focus`, `serp_topic_model`) labels each ranking site +
  the client **specialist / generalist / unknown** from domain + title + snippet,
  and names the keyword's core topic. First LLM call in the snapshot pipeline
  (otherwise pure DataForSEO) — needs `ANTHROPIC_API_KEY` on PLATFORM (already
  present for maps/brand). Pure parser `parse_topical_classification` unit-tested.
- **Persisted:** `serp_snapshots.keyword_topic / generalist_count /
  client_topical_focus` + `serp_snapshot_results.topical_focus` (migration
  20260628040255).
- **Rankability:** new **topical-opening** sub-score (weight **0.25**, second only
  to competition weakness) — generalist SERP + specialist client boosts the score
  and **offsets weak backlinks**; weights renormalize when a snapshot has no
  topical data. Surfaces as a driving factor ("Incumbents are generalists; you're
  a topic specialist").
- **Viewer:** "generalist" row tags + a "Topic X · N of M incumbents are
  generalists · you're a specialist (an edge here)" summary.

**Verified:** import main + **562 tests** on pinned fastapi==0.115.0/pydantic==2.9.2
(6 new parser/scorer cases); ruff clean; frontend build clean. The Haiku call only
runs on Railway (sandbox has no key/egress) — first live snapshot is the proof.

---

## ⏩ Update — 2026-06-28 · **Rankability score + Quick wins**

A client-relative **rankability** score per tracked keyword — how realistically
*this* client can win it — on a new **"Rankability"** tab in the Rankings page.
Computed on read from each keyword's latest SERP snapshot (no migration). Part of
PR #156 (draft, awaiting merge).

- **Score 0–100 + band** (Easy / Moderate / Hard / Very hard; higher = winnable,
  inverse of difficulty), each with its 2–3 **driving factors**. Four blended
  sub-scores: competition weakness (0.40, backlink authority weighted **RD > UR >
  DR**, medians), client capability (0.25, authority gap + rank momentum),
  targeting gap (0.20, loose-match incumbents), SERP opportunity (0.15, AIO/
  shopping crowding).
- **Quick wins** sort = rankability × **potential value** (volume × CTR-at-top-3 ×
  CPC). Keywords without a snapshot are listed unscored with a capture prompt.
- `services/rankability.py` (pure `score_keyword` + `get_client_rankability`),
  `GET /clients/{id}/rank/rankability`, `components/rankings/Rankability.tsx`.
  Weights/thresholds are tunable module constants; pure scorer unit-tested.
- Heuristic, not ground truth (title/URL + DataForSEO authority, not page bodies).

**Verified:** import main + **558 tests** on pinned fastapi==0.115.0/pydantic==2.9.2
(8 new scorer cases); ruff clean; frontend build clean.

---

## ⏩ Update — 2026-06-28 · **SERP Landscape Trends**

Built on top of the SERP Snapshot work: an over-time + cross-keyword view of how
Google's SERP composition changes, from the dated snapshot archive. New **"SERP
Trends"** tab in the Rankings page. (All on PR #156, still draft, awaiting merge.)

**Three views** (`services/serp_trends.py` + `components/rankings/SerpTrends.tsx`):
- **Per-signal prevalence over time** — % of the client's keywords whose SERP
  shows each tracked signal (AIO, local pack, the SERP-feature + title-format
  signals), as an **as-of weekly series** (each keyword contributes its latest
  snapshot on-or-before each week-end, so weekly auto-capture + ad-hoc captures
  read cleanly). Per-signal sparkline + now/Δ table.
- **"What changed" digest** — keywords whose newest snapshot gained/lost a signal
  vs the prior capture.
- **Per-keyword timeline** — each dated snapshot with its signal chips, the
  client's rank/UR/DR, and the delta vs the previous capture.

**API:** `GET /clients/{id}/serp-trends?weeks=12`, `GET /tracked-keywords/{id}/serp-timeline`
(`routers/rank.py`). No new tables/migration — pure reads over `serp_snapshots` /
`serp_snapshot_results` / `serp_snapshot_domains`. Pure helpers (deltas, as-of
weekly prevalence, change digest, week-end generation) are unit-tested.

**Intended direction (user):** track SERP + competition change over time to drive
an **automated optimization/reoptimization planner** — these trend reads are that
planner's data foundation (not yet built).

**Verified:** import main + **546 tests** on pinned fastapi==0.115.0/pydantic==2.9.2
(8 new serp_trends cases); ruff clean; frontend build clean. Live providers not
exercised from the sandbox.

---

## ⏩ Update — 2026-06-28 · **Competitive SERP Snapshot — per-domain DR + viewer UI**

Closed out the rank tracker's **Competitive SERP Snapshot** (PRD §14). The capture
engine + retrieval API + weekly auto-capture already existed (PR #53, 2026-06-22) —
backend-only, covering AIO, SERP features, intent, top-10 organic, and **per-URL**
referring domains + UR. This pass added the two missing §14 pieces: **per-domain
Domain Rating (DR)** and an **on-demand viewer UI**. (Decisions confirmed before
building: extend the existing feature rather than rebuild; capture DR on **every**
snapshot including the weekly pass.)

**What's new:**
- **Per-domain DR (backend).** `services/serp_snapshot.py`: `fetch_domain_summary(domain)`
  (Backlinks summary, `target=<domain>`, `include_subdomains=True` → `rank` = DR) +
  a pure `collect_snapshot_domains(result_rows, client_domain)` helper (deduped,
  case-insensitive domain set; client domain always appended even when it doesn't
  rank). `_capture_and_store` now fetches DR per unique domain (competitors + client),
  isolated per-domain (a failure degrades the snapshot to `partial`), and stores rows
  in the new **`serp_snapshot_domains`** table.
- **API.** `SerpSnapshotDomainRow` model + `domains: [...]` on `SerpSnapshotDetail`;
  `GET /serp-snapshots/{id}` now returns the per-domain DR rows.
- **Viewer UI.** `components/rankings/SerpSnapshots.tsx` — a per-keyword camera button
  in `RankKeywords.tsx` opens a modal: dated-snapshot sidebar + "New snapshot" (enqueues
  the capture job, polls the list until it lands), and a detail view (AIO + cited sources,
  intent badge, top-10 table with RD/UR + the page's domain DR, a per-domain DR table,
  client rows highlighted).

**Cost:** ~24 DataForSEO lookups/snapshot (1 SERP + 1 intent + ~11 per-URL backlinks +
~11 per-domain backlinks). Confirmed acceptable. The weekly auto pass now also incurs the
per-domain calls across all keywords/clients (per the "DR everywhere" decision).

**Migration (applied to `wvcthtmmcmhkybcesirb`; filename = recorded version):**
`20260628015542_serp_snapshot_domains` — `serp_snapshot_domains` (snapshot_id FK,
domain, is_client, domain_rating, referring_domains, backlinks, backlinks_status).
RLS on, no policies.

**Verification:** full `import main` (under the pinned `fastapi==0.115.0` /
`pydantic==2.9.2`, with a local `community` stub since python-louvain won't build in the
sandbox — fanout-only, unrelated) + **528 passed** (incl. 3 new `collect_snapshot_domains`
unit tests); frontend `npm run build` clean. Live DataForSEO not exercised from the sandbox
(only runs on Railway) — first real on-demand capture with a competitor domain is the live
proof of the DR path.

---

## ⏩ Update — 2026-06-23 · **Module #5 — Maps geo-grid ranker (Local Dominator)**

**Module #5 is built, merged, deployed, and proven live** — a real scan ran end to
end against Local Dominator (PRs **#59, #61, #63, #64, #66, #68, #69**, all merged;
PLATFORM startups verified). Per-client geo-grid of the business's Google Maps rank,
with a heatmap + history.

**Field-learnings (the expensive ones — don't rediscover):**
- Local Dominator ranks in `content` are **0-indexed** (`0` = 1st place — the spec's
  "0 means ranks first"). Display is **+1** (`to_display_grid`); not-ranked pins come
  back **`-1`** (or null), **not** the `null` the OpenAPI example implied.
- The grid is **always a circle** (`shape='circle'` forced; square dropped — user
  decision). A circle returns ~`π/4 × grid_size²` pins (e.g. 95 for an 11×11), not
  the full square — handy as a circle-vs-square sanity check.
- LD's own heatmap image (`view_only_link`) is **not embeddable** — it's an
  `app.localdominator.co` URL needing an LD login, so it 403s/breaks in our app.
- `grid_size` is capped at **21** by the API (our 3/5/7-mile @ 1-mile presets =
  7/11/15 fit).

**Heatmap rendering (#68/#69):** primary view is a **Google Static Map** with small
color-coded pins at each in-circle pin's real lat/lng (built client-side from the
grid + scan center; row 0 = north — verify orientation vs LD's interactive link).
Gated on **`VITE_GOOGLE_MAPS_API_KEY`** (a **Netlify** build var — set via the
Netlify MCP; referrer-restricted Maps Static API key). Falls back to a
dependency-free **circular pin heatmap** when the key is absent or the image fails.

**Scan UX (#63/#66):** async create job + a per-tick scheduler poll **and** a
client-driven `POST …/maps/poll` (every ~10–15s while watching) so results land in
seconds, not the 5-min tick; idempotent result storage (`unique(scan_id,keyword)`);
a prominent **spinner + progress bar + elapsed timer** (the in-flight detection was
fixed to fire immediately on click, before the scan row exists).

---

## ⏩ Update — 2026-06-23 · Module #5 build detail

**Vendor change (logged):** Maps/local-pack geo-grid uses **Local Dominator**, not
DataForSEO — this **supersedes** the suite roadmap's locked "DataForSEO geo-grid /
no new SERP vendor" decision for #5 (user direction). Roadmap decision log + data
sources updated. `LOCAL_DOMINATOR_API_KEY` is set on the **PLATFORM** Railway service.

**The model.** Per client: a **3/5/7-mile radius, 1-mile pin spacing** grid around
the business → `grid_size` 7/11/15 (49/121/225 pins; the API caps `grid_size` at
**21**, which the 1-mile spacing respects). Tracked keywords are scanned across the
whole grid. **Async, decoupled from the worker:** a `maps_scan` job `POST`s
`/v1/scans` (returns `scan_uuid`, status `polling`); the **shared scheduler polls**
`GET /v1/scans/{uuid}` each tick (202=running, 200=done) and parses each keyword's
`content` (per-pin rank grid, `null`=not in top 20) + `average_rank` into results.
Weekly on `maps_scan_weekday` + an on-demand **"Run scan now"**.

**Code.** `services/local_dominator.py` (auth + `create_scan`/`get_scan_rows`; pure
`summarize_grid`/`build_scan_request`; create job + `poll_pending_maps_scans` +
`enqueue_due_maps_scans`) and `services/maps_grid.py` (pure radius→grid geometry).
Wired into `job_worker` (`maps_scan`) and `gsc_scheduler` (weekly enqueue + per-tick
poll). `routers/maps.py` + `models/maps.py`: config GET/PUT, keywords GET/POST/DELETE,
run-now, scans list/detail/latest. Frontend: a **separate workspace module**
(`pages/MapsGeogrid.tsx`, route `/clients/:id/maps`, workspace card activated) —
Heatmap (dependency-free colored rank grid + rollups), Setup (grid config + keywords),
History. Business id/center prefill from the client's `gbp_place_id` + `gbp` lat/lng.

**Migration (applied; filename = recorded version):** `…005340_maps_geogrid` —
`maps_scan_configs` / `maps_keywords` / `maps_scans` / `maps_scan_results` (+
`async_jobs` `maps_scan`). RLS on, no client-facing policies.

**Verification.** `import main` + full suite **243 passed** on pinned
`fastapi==0.115.0` / `pydantic==2.9.2`; frontend `npm run build` clean. Pure helpers
unit-tested (grid geometry, `summarize_grid`, `build_scan_request`). **Not yet live**
against Local Dominator.

**Open follow-ups.** Live smoke-test (config a client with Place ID + lat/lng, add a
keyword, Run now, confirm the heatmap). Defaults chosen: `resource_category`
`googleMaps` (Local Finder selectable), `serp_device` `desktop` (so `both`'s
desktop+mobile rows aren't disambiguated — first row per keyword wins). The
**rank-of-record `RANK_UNIVERSE=20`** sentinel + the `average_rank` semantics
("0 means first" per the spec) should be sanity-checked on the first real scan.

---

## ⏩ Update — 2026-06-23 · **Rank-drop alerting (in-app)**

The Organic Rank Tracker's **alerting** — M4's last open piece — is built. **In-app
only** (the channel decision the user made); email stays deferred to the
notifications service proper. **Merged to `main` and deployed** (PR **#55**, squash)
— PLATFORM redeploy **runtime startup verified clean** via Railway logs
(`job_worker.started` + `gsc_scheduler.started` + `Application startup complete`,
no Traceback), and the Netlify deploy preview was green pre-merge; migration
**applied** to `wvcthtmmcmhkybcesirb`. **This closes M4 — the Organic Rank Tracker
is now feature-complete per its PRD.** Alerts populate on the next daily
materialize run (GSC's 2–3 day lag applies).

**The four rules** (evaluated daily in the existing materialize job, per keyword,
on the keyword's **primary source** — GSC avg position where covered, else
DataForSEO weekly rank; never reconciling the two):
- **weekly_drop** — was ranking in spots **1–15** and dropped **≥6 spots in a week**.
- **page_one_exit** — was on **page 1** (≤10) a week ago, now **off it** (>10).
- **thirty_day_drop** — was in **~top 20** and dropped **≥6 spots over 30 days**
  (a top-20 floor, confirmed with the user, to cut deep-keyword noise).
- **deindexed** — reuses the existing **`deindex_risk`** signal (sustained NULL
  GSC days after an established baseline; GSC-only).

GSC paths compare **7-day rolling averages** (GSC position is a noisy decimal
aggregate); DataForSEO paths compare weekly **point** ranks. **Episode model:** at
most one *open* alert per (keyword, type) — opened when the condition first holds,
**auto-resolved** when it clears (so a flapping keyword doesn't spam). `status`
(unread/read/dismissed) is the user's read-state, separate from `resolved_at`.

**Surface:** a per-client **Rankings → Alerts tab** (the only surface the user
wanted — no global notification center), with an **unread count badge** on the tab
(sourced from `OverviewResponse.unread_alert_count`, already fetched). Mark-read /
mark-all-read / dismiss; recovered alerts show a "Recovered" tag.

**Code:** `services/rank_alerts.py` (pure `detect_alerts` + `reconcile_alerts`),
hooked into `services/rank_materialize.py` (collects signals per keyword in the
existing loop, reconciles once after — **no new job/scheduler**). API in
`routers/rank.py`: `GET /clients/{id}/rank/alerts`, `POST /rank-alerts/{id}/read`,
`POST /rank-alerts/{id}/dismiss`, `POST /clients/{id}/rank/alerts/read-all`; plus
`unread_alert_count` on the overview. Frontend `components/rankings/RankAlerts.tsx`
+ the Alerts tab in `pages/Rankings.tsx`.

**Migration (applied; filename = recorded version):** `…000343_rank_alerts` —
`rank_alerts` + the partial-unique open-episode index. RLS on, no policies.

**Verification:** `import main` + full suite **229 passed** on the **pinned**
`fastapi==0.115.0` / `pydantic==2.9.2`; frontend `npm run build` clean. Detection
is pure-unit-tested (9 cases: each rule, the top-20 floor, GSC + DataForSEO,
no-fire). Alerts populate on the next daily materialize run.

**Tunables (start conservative; PRD §12):** thresholds live as constants in
`rank_alerts.py` (`WEEKLY_DROP_SPOTS=6`, `WEEKLY_DROP_BASELINE_MAX=15`,
`THIRTY_DAY_BASELINE_MAX=20`, the GSC smoothing window, etc.) — promote to config
if they need per-client tuning.

---

## ⏩ Update — 2026-06-22 · **Competitive SERP Snapshot**

A diagnostic **SERP snapshot** store for the rank tracker — captured **weekly**
alongside the DataForSEO rank refresh so a pre-drop baseline always exists when
investigating a ranking drop later. **Backend-only** (no viewer UI by design —
retrieved on request via the API). **Merged to `main` and deployed** (PR **#53**,
squash) — PLATFORM redeploy **runtime startup verified clean** via Railway logs
(`job_worker.started` + `gsc_scheduler.started` + `Application startup complete`,
no Traceback); migration **applied** to `wvcthtmmcmhkybcesirb`. Runs on the
DataForSEO paths whose creds are already on PLATFORM, so it's **operational today**.

**What it captures**, per tracked keyword per capture: the **AI Overview**
(presence, text, cited sources); the **SERP feature inventory** ("enhancements":
local pack/GBP, PAA, discussions/forums, featured snippet, … — item types present
+ captured detail); the **query intent** (DataForSEO Labs search-intent); and the
**top organic results** (url / domain / rendered **title + description** /
position), each enriched with **referring domains + URL Rating** (DataForSEO
Backlinks page rank 0–1000, the UR-equivalent) — **including the client's own
ranking/canonical page** (an extra row if it ranks below the captured depth).

**Decisions (confirmed with user before building):** UR = DataForSEO page rank
(no new vendor); Backlinks API in scope, ~11 lookups/keyword, cost OK; stored
dated snapshots per keyword; **auto weekly capture**; **store-only + retrieval API**
(users don't need routine access).

**Data sources (all DataForSEO, reusing the `dataforseo_rank.py` Basic-auth
pattern):** SERP advanced (`serp/google/organic/live/advanced`) → AIO + organic +
features; Labs `search_intent/live` → intent; `backlinks/summary/live` per target
URL → referring domains + page rank. Per-URL / per-keyword failures are isolated
(snapshot degrades to `partial`; a SERP failure stores a `failed` marker row).

**Code:** `services/serp_snapshot.py` (pure parse helpers + async orchestrator +
`enqueue_serp_snapshot` / `run_serp_snapshot_job`); wired into
`gsc_scheduler.enqueue_due_serp_snapshots` (weekly branch) + `job_worker`
(`serp_snapshot` job type). Retrieval routes in `routers/rank.py`:
`GET /tracked-keywords/{id}/serp-snapshots`, `GET /serp-snapshots/{id}`, and an
on-demand `POST /tracked-keywords/{id}/serp-snapshot` (enqueues a single-keyword
capture). Models in `models/rank.py`. Config: `serp_snapshot_depth` (20),
`serp_snapshot_top_n` (10 — how many top results get the pricier Backlinks call).

**Migration (applied; filename = recorded version):** `…232017_serp_snapshots`
— `serp_snapshots` + `serp_snapshot_results`, widened `async_jobs.job_type`. RLS
on, no client-facing policies.

**Verification:** `import main` + full suite **220 passed** on the **pinned**
`fastapi==0.115.0` / `pydantic==2.9.2` (the #43 process). Live providers not
exercised from the sandbox (DataForSEO calls only run on Railway) — first real
weekly capture is the live proof.

**Note on cost:** the weekly pass snapshots **every** active keyword for every
client (≈1 SERP + 1 intent + up to 11 backlinks calls each). Cost was approved;
if it needs throttling later, gate `enqueue_due_serp_snapshots` (e.g. priority
keywords only) — the same tiering open question as the DataForSEO "Today" rank.

---

## ⏩ Update — 2026-06-22 · **Rank-tracker reports**

Client **reporting** is built on top of the rank tracker — on-demand, scheduled, and optionally delivered as a Google Doc. All merged to `main` and deployed (PRs **#47**, **#48**, **#50**), each verified live (PLATFORM clean startup, `gsc_scheduler.started`). Sits on the rank-tracker section below.

**What shipped:**
- **On-demand printable report (#47).** A **Reports** tab → "Generate now" / open any saved report → a clean, branded print view (`pages/RankReport.tsx`) with a **Print / Save as PDF** button (scoped `@media print` CSS isolates it from app chrome — no PDF dependency). Sections: branded header (logo + client + date + mode/location), KPI summary incl. **total estimated monthly value**, status rollup, GSC trend charts (avg position + clicks/impressions), Improving / Needs-attention highlights, top opportunities by est. value, full keyword table. Adapts for DataForSEO-only clients (drops GSC-only sections).
- **Scheduled reports + in-app archive (#48).** Per-client `rank_report_config`: **as_needed / weekly+weekday / monthly+day / every 7·14·30 days**. The shared scheduler (`gsc_scheduler.enqueue_due_reports`) checks daily via `rank_report.is_report_due` (month-end clamp; never twice a day) and enqueues a `rank_report` job that **snapshots** the report data into `rank_reports` (so a dated report keeps its as-of numbers). `RankReport` renders either live or a stored snapshot (`/clients/:id/rankings/report/:reportId`).
- **Google Doc delivery (#50).** Optional per-client toggle (`rank_report_config.deliver_google_doc`) auto-publishes scheduled + generated reports as a **Google Doc in the client's Drive folder**, reusing the Apps Script publish webhook (the locked delivery rail). `rank_report.render_report_markdown` (pure) → `publish_report_doc` POSTs `{folder_id, title, content}` to `GOOGLE_APPS_SCRIPT_URL`, stores `doc_url` on the report. Any saved report can be published on demand (`POST /rank-reports/{id}/publish`); UI shows **"To Doc" / "View Doc"**. Requires the client to have a Drive folder set (Client → Edit).

**Code:** `services/rank_report.py`; report routes in `routers/rank.py` (`report-schedule` GET/PUT, `reports` GET/POST, `rank-reports/{id}` GET/DELETE, `rank-reports/{id}/publish` POST); frontend `pages/RankReport.tsx` + `components/rankings/RankReports.tsx`.

**Migrations (applied to `wvcthtmmcmhkybcesirb`; filenames = recorded versions):** `…214725_rank_reports` (`rank_report_config` + `rank_reports` + job_type `rank_report`), `…215804_rank_report_delivery` (`deliver_google_doc` + `doc_id/doc_url/delivered_at`). RLS on, no client-facing policies.

**Delivery options status:** in-app archive + Google Doc = built. **Email = deliberately deferred** — needs the suite **notifications service** (unbuilt) + an email-provider/from-address decision. That same decision unblocks rank-drop **alerting**; building the notifications service once lights up both.

**Process note (carried from the #43 incident):** every backend change since is import-/test-verified against the **pinned** `fastapi==0.115.0` / `pydantic==2.9.2` before merge (latest suite run **206 passed**), and each merge's PLATFORM deploy is confirmed via Railway logs for a clean runtime startup — not just a green build.

---

## ⏩ Update — 2026-06-22 · **Organic Rank Tracker shipped** (supersedes the scheduler + `sie_cache` RLS items in §8)

The **Organic Rank Tracker (Module #4)** is **built and live in production** — M1–M4 complete **except alerting**. Hybrid **GSC + DataForSEO** with an automatic per-keyword fallback. All merged to `main` and deployed (PRs **#36**, **#43** hotfix, **#44**). Authoritative doc: **`docs/modules/organic-rank-tracker-prd-v1_0.md`**.


**The model.** Keywords are **client-anchored** (a GSC property is optional). Source is auto-selected **per keyword**: **GSC** where the site ranks *and* GSC is connected; **DataForSEO (weekly)** otherwise — no accessible property, or the site doesn't rank for the term so GSC has nothing. DataForSEO writes `tracked_rank` only; **never reconciled** with GSC's averaged `gsc_position`. The weekly DataForSEO job skips GSC-covered keywords, so spend scales with the gaps.

**What shipped (PR #36):**
- **M1 connection** — service-account GSC (`gsc_properties`, verify-access). **M2 sync** — daily ingest → `gsc_query_daily` + `sync_runs`; the **in-process asyncio scheduler** (`services/gsc_scheduler.py`) is the **decided shared-scheduler mechanism** — enqueues jobs into `async_jobs`, reuse it for future trackers. **M3** — materialized null date-axis `rank_keyword_metrics` + computed status taxonomy (`rank_status.py` / `rank_materialize.py`); tabbed Overview/Keywords/Settings UI; **dependency-free SVG charts** (inverted-Y with visible gaps — no charting lib, React-19-safe). **M4** — `keyword_market` (CPC/volume/competition + est-monthly-value ROI), weekly query×page `gsc_query_page_daily` → canonical-URL resolution + Pages view, striking-distance discovery, deindex **URL Inspection** confirmation (`tracked_keywords.index_status`).
- New services: `gsc_service, gsc_ingest, gsc_scheduler, rank_status, rank_materialize, dataforseo_rank, keyword_market`; routers `gsc`, `rank`. Frontend `pages/Rankings.tsx` + `components/rankings/`.

**Follow-ups shipped same session:** historical GSC backfill (Settings, ~16mo), per-keyword **page breakdown** + "+N pages" chip, **canonical-URL pinning** UI, **CSV export**, **all actions opened to any authenticated team member** (no admin gates), keyword add via type/paste/**CSV import**, and a **per-client tracking location** (city/region/country via the existing `LocationAutocomplete` — `clients.rank_tracking_location[_code]`, PR #44) that drives the DataForSEO ranks + market data. GSC metrics stay national-aggregate (Google limitation); geo-grid local-pack is Module #5.

**⚠️ Production incident (PR #43) — lesson logged.** Merging #36 crash-looped **all of platform-api** on startup: two `DELETE` endpoints used `status_code=204` with a `-> None` return, which **FastAPI 0.115.0 (the pinned prod version)** rejects at import (`AssertionError: Status code 204 must not have a response body`). The sandbox's *newer* FastAPI didn't surface it. Fixed to match the codebase's working pattern (`routers/users.py`: `response_class=Response`, return `Response(status_code=204)`). **Lesson: verify imports/tests against the *pinned* `requirements.txt` versions, not whatever the sandbox happens to have** — done for all later work (198 tests pass on `fastapi==0.115.0` / `pydantic==2.9.2`). Prod recovery confirmed via Railway logs (clean startup, `gsc_scheduler.started`).

**Migrations (all applied to `wvcthtmmcmhkybcesirb`; filenames reconciled to the apply-time recorded versions per `MIGRATIONS.md`):** `…181919_gsc_properties`, `…181933_gsc_ingest_storage`, `…183357_rank_tracker_keywords`, `…185307_keywords_client_anchor`, `…185948_keyword_market`, `…191240_gsc_query_page_daily`, `…191831_keyword_index_status`, `…203200_sie_cache_enable_rls`, `…211331_clients_rank_tracking_location`. All RLS-on, **no client-facing policies** (service-role only — the `async_jobs` pattern).

**Housekeeping done:** `CLAUDE.md` updated (rank-tracker current state, services/routers, the resolved scheduler decision, `GOOGLE_SERVICE_ACCOUNT_KEY` note); **`public.sie_cache` RLS enabled** — closes the long-standing §8 advisory item (was disabled on the live DB despite the original migration; service-role-only, no policies); migration ledger + reconciliation log updated in `writer/supabase/MIGRATIONS.md`.

**⚠️ Provisioning still required for the GSC path:** set **`GOOGLE_SERVICE_ACCOUNT_KEY`** (full service-account key JSON) on the **PLATFORM** Railway service, and create the GCP service account + enable the **Search Console API** (a dashboard step — confirm with the user). Until then the tracker runs **DataForSEO-only** (works **today** — DataForSEO creds were already set on PLATFORM); GSC verify/ingest/URL-Inspection show a "not configured" state.

**Still pending by design:**
- **Alerting** (deindex/drop → email/Slack/in-app) — gated on the **notifications-channel decision** (in-app feed vs email/Slack + provider/webhook details). The detection (`deindex_risk`/`dropping` status) already runs; only the outbound hook is unbuilt.
- **Module #5 — Maps / local-pack ranker** (geo-grid). This is the *only* thing the per-client tracking location does **not** cover — the organic tracker is national/city point-in-time SERP, not a grid of points around a business.

**Verified & deployed:** backend **198 tests** on the pinned stack; frontend `npm run build` clean. Production confirmed live from the latest commit — PLATFORM (Railway) clean startup, `ar-internal.netlify.app` deploy `ready` on `d353afa`. (Tell users to **hard-refresh** to clear the cached bundle.)

---

## ⏩ Update — 2026-06-22 (supersedes the TextRazor open items in §3/§6/§7 below)

TextRazor is **live, calibrated, and secured**, and the **Local SEO module is feature-complete** (location autocomplete, SERP caching, page templates, Google-Doc publishing). All of today's work is merged to `main` and deployed (PRs #23–#33).

**TextRazor — done.**
- **Activated:** `TEXTRAZOR_API_KEY` had been *staged* (not committed) — committed via Railway `accept-deploy` + redeploy. nlp startup now logs `TEXTRAZOR_API_KEY is set`.
- **Concurrency bug fixed (#25):** live runs returned 0 entities — TextRazor's per-plan concurrent-request cap rejected all-but-~2 of the per-page fan-out with `401`. `fetch_textrazor_entities` now runs behind an `asyncio.Semaphore` (`TEXTRAZOR_MAX_CONCURRENCY`, default 2) + retries 401/403/429 with backoff. A real `roof restoration` / Melbourne analyze then returned all 13 pages `200` → **5 entities**.
- **Calibration:** distribution `[0.93, 0.53, 0.44, 0.35, 0.12]`. `TEXTRAZOR_MIN_RELEVANCE` **kept at the default 0.1** — the page-spread filter is the dominant signal and 5 is a healthy, focused set; no env change needed. (One-keyword sample; revisit if more keywords show noise.)
- **Key NOT rotated** — user deferred (§6.2 still open if desired).

**Security / cost (§6) — closed.**
- nlp **public domain removed** → private-only (`nlp.railway.internal`; PLATFORM already used that). No more internet-exposed auth-less nlp.
- `GOOGLE_NLP_API_KEY` **removed** from nlp (unused post-swap). Redeploy verified healthy.

**Local SEO location robustness (#23, #24) — new.** Mistyped areas silently degraded generation (DataForSEO `200` + 0 results → no competitors, no TextRazor). Fixed with: an **area typeahead** (`GET /clients/{id}/local-seo/locations`, DataForSEO `locations/{country}` scoped to the client's country, in-memory cached — `services/locations_service.py`); a **server-side validation backstop** (`resolve_location`: trust a picked `location_code`, else match the typed name → attach code, else `400` + suggestions); and `location_code` threaded through the **generate** path (`GeneratePageRequest` + its inline analysis — previously dropped). Frontend `LocationAutocomplete` combobox + DataForSEO task-error diagnostics. Tests: platform-api **91 passing**.

**UI (#26).** The localseo `Spinner` never animated because `index.css` (which declares the `spin` keyframe) **isn't imported anywhere** in the app; the Spinner now injects its own keyframe. Analyze/check buttons show "Analyzing competitors…".

**SERP analysis caching (#29) + review hardening (#30).** SERP analysis (DataForSEO+ScrapeOwl+TextRazor, ~20 pages, 2–4 min) was re-run on every analyze/score/generate. It depends only on (keyword, location), so it's now cached and **shared across clients**. `keyword_analyses` table (migration `20260622120000`, RLS-on/service-role-only); `services/analysis_cache.py` with a **14-day TTL** (`analysis_cache_ttl_days`, 0 disables); `_get_or_compute_analysis` used by analyze/generate/score (generate & score pass the cached analysis to nlp so it skips its inline re-scrape); a **`force_refresh`** flag + "Refresh competitor data" checkbox. Review hardening (#30): generate/score **degrade gracefully** when analysis can't be computed (don't hard-fail — `required=False`), `analyze` still propagates; **single-flight** lock collapses concurrent identical misses; cache hits flagged `from_cache` with cost zeroed; idempotent migration; `score` forwards `user_id`.

**Local SEO Phase 3 — page template (#31).** Mirror an existing page's section structure: per-page field + optional **per-client default** (`clients.local_seo_page_template_url`, migration `20260622140000`). nlp `GeneratePageRequest.page_template_url`/`_html`; `_extract_template_outline` scrapes the reference (SSRF-guarded) → H1/H2/H3 outline → injected as a STRUCTURE-OVERRIDE block that supersedes the default 13 sections while keeping AEO rules + JSON-LD; degrades to default if unfetchable. `PUT /clients/{id}/local-seo/page-template-default`.

**Local SEO publishing (#33).** Generated pages now **publish to a Google Doc in the client's Drive folder**, reusing the blog writer's Apps Script webhook (the locked publish destination). `services/html_to_markdown.py` (stdlib HTML→Markdown, no new dep) → `publish_page` POSTs to `GOOGLE_APPS_SCRIPT_URL` with the client's `google_drive_folder_id` → persists `published_doc_id/url/at` (migration `20260622150000`, additive — the in-app page is the source of truth and is unchanged). `POST /local-seo/pages/{id}/publish`; "Publish to Google Doc" / "View Google Doc" in the page view. Prereq: client must have a Drive folder set (Client → Edit), accessible to the Apps Script's Google account.

**Local SEO module is now feature-complete.** Verified our nlp `/generate-page` writer matches the ShowUP Local `CONTENT_WRITER` spec (13 sections, 14 AEO rules, Sonnet 4.6 @ 16k, 8-engine 85/15 scoring, RDFa/JSON-LD) — only deltas are the intentional suite adaptations (TextRazor, no billing, auth at platform layer, caching, location_code). Reoptimizer + GBP-social-posts paths traced end-to-end and confirmed wired (GBP posts are **generate-only** — not auto-posted to Google Business Profile).

**Tests:** platform-api **118 passing** (analysis_cache, locations, page-template, html_to_markdown, publish, degrade/single-flight units).

**New debt / still open.**
- `index.css` unimported → base resets (`box-sizing`, `margin:0`) don't apply suite-wide — left as-is (importing would shift layouts); decide separately.
- TextRazor key rotation still deferred.
- **Local SEO live-verification debt:** only `analyze` + `generate` are live-proven. Not yet live-tested: score, reoptimize, find-page, related-pages, GBP social posts, page-template, **publish**.
- Reoptimize doesn't reuse the SERP cache; some entry paths reoptimize without SERP context (degrades, not breaks). `score` force-refresh not exposed in UI. No DOMPurify on rendered HTML (first-party).
- Not built (out of v1 / separate): **GBP post auto-publishing**, live-CMS/WordPress publishing.
- Everything in §8 below still stands.

---

**Date:** 2026-06-21
**State:** everything below is **merged to `main` and deployed** (PRs #20, #21, #22). No feature branch is left in flight; the only open work is the TextRazor *activation/calibration* and the standing items in §6–§8.
**Scope of this handoff:** this session shipped four things — (1) **Brand Voice** + (2) **ICP/Differentiators** as converged client-level assets, (3) repaired a set of **nlp constants dropped in the Phase-0 rehome** that were silently 502'ing score/generate/reoptimize/press-release, and (4) swapped the entity provider **Google Cloud NLP → TextRazor**.

> Read `CLAUDE.md` first for conventions + current-state summary, `docs/suite-architecture-and-roadmap-v1_0.md` for suite scope/decisions, and `docs/modules/local-seo-module-integration-plan-v1_0.md` for the Local SEO plan. This file ties them to the latest state.

---

## 1. What this session shipped (all merged to `main`)

| PR | Title | What |
|---|---|---|
| **#20** | `Fix nlp-api: restore constants dropped in the Phase-0 rehome` | Restored `SCORE_MODEL`, `_SCORE_SYSTEM_PROMPT`, `_MODEL_PRICING`, `GENERATION_MODEL`, `_GEN_SYSTEM_PROMPT`, `_REOPT_SYSTEM_PROMPT`, `_PRESS_RELEASE_SYSTEM_PROMPT` (verbatim from `local-seo-writer/services/nlp/main.py`); added the missing `import anthropic` in `/find-page-for-keyword`; built `seo_checklist` in the reoptimize loop. **F821 in nlp-api → 0.** |
| **#21** | `Brand Voice + ICP/Differentiators — converged client-level assets` | Two new client-knowledge modules, end-to-end (store + generation + convergence bridge + UI). |
| **#22** | `Swap entity provider: Google Cloud NLP → TextRazor` | Full replacement of the entity pipeline. |

**The nlp repairs (#20) are the most important takeaway.** The Phase-0 rehome (`00ae38e`) carried the *functions* but dropped a block of module-level constants, so `/score-page`, `/generate-page`, `/reoptimize-page`, `/augment-page`, and `/press-release` raised `NameError → HTTP 502` on every call. This was latent because nlp-api has no test harness. Proven via AST (no assignment), `ruff F821`, and `git log -S` (never in the file's history). **If anyone reports "Local SEO scoring/generation was broken before 2026-06-21," this is why.**

---

## 2. Brand Voice + ICP — the convergence model (Option A)

These two re-add capabilities the Local SEO v1 plan had **cut** (`brand-voice`/`ICP` scraping) — done deliberately, per the user, and **converged** so one client-level asset feeds **both** the Blog Writer and Local SEO.

**Decision (Option A):** the structured JSON is the single source of truth; the legacy free-text columns become a *rendered view*.
- `clients.brand_voice` JSONB — `{ source, raw_text, current_voice, recommended_voice, recommended_accepted, writer_execution_guide, generated_at, edited_at }`.
- `clients.detected_icp` JSONB — `{ source, raw_text, segments, reasoning, generated_at, edited_at }`; `clients.differentiators` JSONB (array). One `detected_icp.source` governs supersede for both.
- **Provenance/supersede:** `source: "user" | "app"`. A user-authored *structured* voice/ICP blocks an auto-scan unless `force=true`; a `raw_text`-only entry can still be enriched (the scan preserves it). The UI badge treats any `raw_text` as user-authored.
- **Migrations (live + verified):** `20260621120000_clients_brand_voice.sql`, `20260621130000_clients_icp_differentiators.sql` — both applied to `wvcthtmmcmhkybcesirb` and seeded from existing `brand_guide_text` / `icp_text`.

**Wiring:**
- nlp-api: `POST /analyze-brand-voice` + `POST /analyze-business` (these *engines* already existed but were orphaned — no endpoint/persistence/UI). ICP scan includes opt-in **title/H1 enrichment** (`_enrich_pages_with_titles`, time-bounded). `_build_brand_voice_text` / `_build_icp_text` now also render `raw_text`.
- platform-api: `services/brand_voice_service.py` + `routers/brand_voice.py`; `services/icp_service.py` + `routers/icp.py`. Routes: `GET` / `POST …/scan` (heartbeat-SSE) / `PUT`, all behind `require_auth`, per-user rate-limited via a forwarded `X-User-ID` (added to `_post_nlp`).
- **Convergence bridge:** `resolve_brand_guide_text` / `resolve_icp_text` render the structured asset into the Blog Writer's run-snapshot `brand_guide_text` / `icp_text` (differentiators folded into the ICP text), at all three snapshot sites (`runs.py` dispatch + rerun, `silo_promotion.py`). **No Writer-internals change.** The clients router keeps the structured asset in sync when the legacy free-text fields change.
- **Local SEO generate/social payloads** now pass `brand_voice` / `detected_icp` / `differentiators` to the generator (they were previously omitted — this completes the Local-SEO side of convergence).
- Frontend: `pages/BrandVoice.tsx`, `pages/Icp.tsx`, `components/{brandvoice,icp}/api.ts`, ClientWorkspace "Client setup" cards, routes `/clients/:id/brand-voice` and `/clients/:id/icp`.

---

## 3. TextRazor swap (entity analysis) — **NOT FULLY LIVE YET**

Replaced Google Cloud NLP with TextRazor in the SERP pipeline (cost + Wikipedia/Wikidata linking). **Structure preserved** — per-page de-dup → page-spread + relevance filter — only the source/field mapping changed, and the downstream `google_entities` field name is **kept** so zone targets / rubric / deterministic engine / ICP are untouched.

- Mapping: `relevanceScore` → the `mean_salience` slot; `entityId` = grouping key; `matchedText` (most common) = `name`; `wikidataId` → `mid` (+ new `wiki_link`); mentions grouped by `entityId`.
- Thresholds: `ENTITY_MIN_PAGE_SPREAD` unchanged (the dominant, provider-agnostic filter). The old `0.40` salience cutoff **does not transfer** → replaced by `ENTITY_MIN_RELEVANCE` (env `TEXTRAZOR_MIN_RELEVANCE`, default lenient **`0.1`**) + optional `ENTITY_MIN_CONFIDENCE`. `get_textrazor_entities` **logs the relevance distribution** of page-spread-qualifying entities for calibration.

### ⚠️ Two things are NOT done — pick these up next
1. **The key is staged, not applied.** `TEXTRAZOR_API_KEY` was set on the `nlp` service via the Railway agent but only *staged* — the post-merge deploy log still shows `WARNING - TEXTRAZOR_API_KEY not set`. **Until it's committed (via `accept-deploy`, or re-set + redeploy), TextRazor is inert: `get_textrazor_entities` returns `[]`, so the entity signal is missing entirely** (graceful — scoring/generation still run, entity coverage defaults to its neutral value, no crash). **This was awaiting user go-ahead to redeploy when the session ended.**
2. **Threshold not calibrated.** `0.1` is a placeholder. Once the key is live, run one real Local SEO `/analyze` (or score), read the `nlp` log line `TextRazor calibration: N page-spread-qualifying entities; mean relevance (desc): [...]`, and set a tuned `TEXTRAZOR_MIN_RELEVANCE`.

---

## 4. Verification status (read this before trusting anything live)

- **All checks were static/offline:** `py_compile`, `ruff` (F821=0 in nlp-api), `mypy`/`eslint` on new code, the platform-api pytest suite (**83 passing**), `tsc -b` + `vite build`, and AST byte-identity checks on the restored nlp constants. New aggregation logic (TextRazor) was exercised against a **mocked** response.
- **Nothing was live-tested.** The build sandbox has **no `ANTHROPIC_API_KEY` and an egress allowlist** (e.g. `api.textrazor.com` is blocked, returns `403 Host not in allowlist`). Real provider calls only happen on Railway. So: the nlp repairs, the brand-voice/ICP scans, and the TextRazor swap have **not** been exercised against live providers from here.
- **Sandbox dep gaps** (not bugs): `openai`, `supabase`, `python-multipart` aren't installed in the build env, so some imports/tests fail here but pass with `pip install -r requirements.txt`. `pip install --ignore-installed PyJWT supabase` was needed for the platform tests.

---

## 5. Infra / deploy state

- **Railway (`ar-tools`): 4 services** — `nlp`, `PLATFORM`, `pipeline`, `info-site-kw-research-cluster` (the separate keyword-research app), env `production` (`7bd2e88e-…`), project `2c718e53-…`.
- **All three suite services redeployed** off the merges and reported **SUCCESS** (latest `nlp` deploy = `6025459`, the #22 merge). The TextRazor *code* is live; the *key* is not (see §3).
- **`nlp` keys present:** `ANTHROPIC_API_KEY`, `SCRAPEOWL_API_KEY`, `DATAFORSEO_LOGIN/PASSWORD`, `GOOGLE_NLP_API_KEY` (now unused — removable after TextRazor is confirmed), `TEXTRAZOR_API_KEY` (**staged, not applied**). `SCORE_MODEL`/`GENERATION_MODEL` are **not** env vars (code constants → sonnet default); their absence is expected.
- Railway gotchas still apply (from the prior handoff): private-only `nlp` ⇒ **keep `healthcheckPath` empty**; Dockerfile binds `::`; don't double-trigger deploys; SSE routes need buffering off.

---

## 6. ⚠️ Open security / cost items (flagged, not yet actioned)

1. **`nlp` has a PUBLIC domain** — `nlp-production-0e3c.up.railway.app:8080` — but the service is **auth-less by design** ("private network only" per CLAUDE.md). If that domain is internet-reachable, anyone who finds it can hit `/generate-page`, `/score-page`, `/analyze`, etc. and **burn Anthropic + DataForSEO + ScrapeOwl + TextRazor credits**. The #20 repairs made those endpoints *more* functional, so this matters more now. **Verify reachability and remove the public domain (or add auth) — highest-priority loose end.**
2. **Rotate the TextRazor key** — it was pasted into the chat transcript this session. The working value is in Railway; rotate once cutover is confirmed.
3. After TextRazor is confirmed working, **remove `GOOGLE_NLP_API_KEY`** from `nlp` (no longer read).

---

## 7. Immediate next steps

1. **Finish TextRazor (§3):** apply the staged `TEXTRAZOR_API_KEY` (redeploy `nlp`), run one real `/analyze`, read the calibration log line, set a tuned `TEXTRAZOR_MIN_RELEVANCE`, confirm entity counts are sane. Then rotate the key + drop `GOOGLE_NLP_API_KEY`.
2. **Close the `nlp` public-domain exposure (§6.1).**
3. **Live smoke-test the repaired nlp endpoints** — `/score-page` + `/generate-page` against the deployed PLATFORM→nlp path with an authenticated request. These were 502'ing before #20; a real call is the only true proof they're fixed (couldn't be done from the sandbox).
4. **Click-test Brand Voice + ICP** end-to-end (scan → review → accept → generate) — built/typed-clean but not exercised live.

---

## 8. Open decisions / standing debt (carried forward)

- **SERP analysis cache (`keyword_analyses`) still does not exist.** Every `/analyze` and `run_analysis:true` generate re-runs the full DataForSEO→ScrapeOwl→(now TextRazor) pipeline (2–4 min, recurring cost). SYSTEM_OVERVIEW/Foundation calls for caching `AnalysisResponse` by `(keyword, location)`; this is the highest-value infra still unbuilt and would speed up Score My Page + generation.
- **Vertical wording** — the brand-voice/ICP/score prompts say "local service business" verbatim. Fine for local clients, slightly off for non-local Blog-Writer clients; left verbatim per the "keep prompts exact" rule. Parameterizable later.
- **Manual editing is freeform `raw_text`** for both brand voice + ICP; per-field structured editing is a future enhancement.
- **`seo_checklist` in `/reoptimize-page`** was a latent bug present in the reference copy too; fixed by mirroring generate-page's `_build_seo_checklist(...)` call — worth a sanity check on a live reoptimize run.
- **Scheduler mechanism**, **Maps geo-grid density**, **notification channels**, **Keyword-research repo migration**, **CI on push** — all still open from prior handoffs.
- **Local SEO Phase 3 — page-template field** — still not started (the original request from the prior session).
- Pre-existing: `public.sie_cache` has RLS disabled (advisory); migration-timestamp convention mismatch; `README.md` references a non-existent `/kw-research` path.
