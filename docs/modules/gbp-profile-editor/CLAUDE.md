# GBP Profile Editor — build orientation (module-scoped)

> **This is a module-scoped build brief, not the suite authority.** The root
> `/CLAUDE.md` remains the suite's authoritative context and conventions — read it
> first. This file orients a build session for the **GBP Profile Editor** module
> specifically: what to read, the verified reuse map, and the module's own
> guardrails. The behavioral spec is the PRD; current state + activation is the
> module `HANDOFF.md`.

## Read these first, in order

1. **`/CLAUDE.md`** (root) — suite context, stack decisions, conventions, the
   things-not-to-do list. Non-negotiable.
2. **`docs/modules/gbp-profile-editor-prd-v1_0.md`** — the authoritative spec for
   this module (Approved for build 2026-09-04). What/why/scope/phasing/API/data
   model/approval model/risks. **When in doubt, the PRD wins on behavior.**
3. **`docs/modules/gbp-profile-editor/HANDOFF.md`** (next to this file) — current
   state (what's already built), the phase-by-phase build plan, the gotchas, and
   config/activation.
4. **`docs/adr/0004-gbp-profile-edits-never-auto-applied.md`** — why v1 never
   auto-applies. Do not design around this; it's load-bearing.
5. **`docs/modules/gbp-posts-module-prd-v1_0.md`** + the Posts code (below) — the
   pattern template this module mirrors.
6. The **"GBP Profile Editor"** entry in the root `decisions.md` — the twelve
   settled decisions in terse form.

## What this module is (one paragraph)

A per-client tool to edit a client's Google Business Profile **description,
services, and operating hours** via the Business Information API v1
`locations.patch`, with every edit **AI-drafted → operator-reviewed → applied on
an explicit click** (never auto-applied — ADR 0004). It reuses the live GBP
connection layer wholesale; the only genuinely new Google surface is the write
path (`locations.get` + `locations.patch`), which is called nowhere today.

## Verified reuse map (checked against the code 2026-09-04)

Reuse these — do not re-implement. `writer/platform-api/` unless noted.

| Need | Reuse | Note |
|---|---|---|
| Credentials (`business.manage`) | `services/gbp_auth.py::credentials()` | OAuth-as-agency-account preferred, SA fallback |
| **v1 Business Information client** | `services/gbp_locations_service.py::_build("mybusinessbusinessinformation", creds)` | **hardcodes `"v1"` — use THIS one.** ⚠️ there is a *different* `_build(service_name, version="v1", creds=None)` in `gbp_performance_service.py` — don't cross them |
| Listing registry + client→listing match | `services/gbp_locations_service.py` (`gbp_locations` table, `access_status='ok'`, `resolve_client_match`, `register_location`) | reads (`accounts.locations.list`) already in production |
| Error → status classification | `gbp_performance_service.classify_access_error` + `gsc_service._extract_status_code` | reuse both for `classify_profile_error` |
| Freeze gating | `services/freeze.py` (`FREEZE_GATED_JOB_TYPES`, `assert_not_frozen`) + `job_worker.py` worker-side enforcement | add `gbp_profile_apply` **and** `gbp_profile_sync` to the set; call `assert_not_frozen` on the apply route |
| Voice/brand drafting | `build_client_context`, `render_voice_card_block`, `voice_forbidden_hits`, `voice_card_service.get_voice_card` | all used by GBP Posts drafting today |
| Services grounding | `clients.gbp` categories + the silo planner output | best-effort/degrading (decision Q10) |
| The whole module shape | GBP Posts: `services/gbp_posts_api.py` (⚠️ Posts is v4/httpx — this module is v1/discovery), `services/gbp_posts_service.py`, `routers/gbp_posts.py`, `models/gbp_posts.py`, `frontend/src/pages/GbpPosts.tsx` | mirror structure; the API client is the one real difference |
| Strategist loop endpoints | `slack_assistant/actions.py` `_ACTIONS` (mirror `update_client_profile`), `task_producers.py::sync_action_plan_tasks` | the action + producer both STAGE a draft, never apply |
| Resumable job UI | `frontend/src/lib/useResumableJob.ts` | for draft/apply/sync jobs |
| Error UI | `frontend/src/lib/errorGuidance.ts` (`ErrorDetails`) | add the new codes (PRD §8) |
| The loop's description trigger | `gbp_audit.description_quality` (**BUILT — PR #1009**) | `{ok, length, issues[]}` |

## Module-specific guardrails (on top of root /CLAUDE.md)

- **Never auto-apply.** ADR 0004. AI drafts; a human clicks Apply. The SerMaStr
  action and the Action-Plan producer stage a `status='draft'` edit only.
- **Re-read-and-diff at Apply.** Re-`get` the field, compare to the draft's
  `current_value`; if it drifted, abort into `live_changed` — never clobber an
  unseen dashboard edit.
- **One `updateMask` per field.** A description patch must not touch hours.
- **Always read live on page load** — no cached "current value" (it drifts when
  someone edits in the Google dashboard).
- **Declare every response field in the Pydantic models.** Pydantic silently
  strips undeclared keys before the frontend sees them (the repo's #844 lesson;
  it already bit `MapsGbpAuditResponse` in #1009 and was fixed there).
- **`async_jobs.job_type` CHECK is rebuilt from the LIVE constraint**, not copied
  from a repo migration (the live set is wider). Follow the
  `20260902180000_guide_sync.sql` pattern; add `gbp_profile_apply`,
  `gbp_profile_draft`, `gbp_profile_sync`.
- **Pure builders/validators are unit-tested without Google.** Hours mapping
  (closed/24h), description validation + linter, services dedup + category
  attach, error classification, re-read-and-diff abort, reconciler backoff.
- **The AI never invents hours.** It normalizes/flags; a human supplies values.
- **The description linter is advisory, never a gate** (decision Q9/Q12). Google's
  `rejected` verdict + the reconciler are the source of truth.
- **Private services stay private.** `nlp-api`/`pipeline-api` are not touched by
  this module; all code is `platform-api` + frontend.
- **Field-path re-verify at build time** — see the PRD §2 verification note and
  the HANDOFF; `developers.google.com` is egress-blocked from the sandbox but
  reachable from the Railway PLATFORM shell.

## Don't

- Don't edit any GBP field other than description / services / hours (categories,
  attributes, phone, etc. are out of v1 — PRD non-goals).
- Don't build the `gbp_audit` **service-gap** check yet (it needs this module's
  live `serviceItems` read; Phase 3).
- Don't wire keyword-research / page-inventory into the services draft (Phase 2.5).
- Don't expose the module until both `gbp_api_enabled` and `gbp_profile_enabled`
  are on (both default False).
