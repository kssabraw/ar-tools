# GBP Profile Editor Module — PRD v1.0

**Status:** **Approved for build (owner, 2026-09-04).** Authoritative for the GBP Profile Editor module. The twelve design decisions from the 2026-09-04 grilling session are folded in below and recorded in the root `decisions.md` ("GBP Profile Editor") and `docs/adr/0004-gbp-profile-edits-never-auto-applied.md`.

**Owner ask (2026-09-03):** "Could we use [the GBP API] to update/edit the business description, services, and operating hours? … I would like to build this. Edits can be AI drafted."

**Scope of this doc:** a per-client tool to **edit three fields of a client's Google Business Profile** — the **business description**, **services**, and **operating hours** — through the Business Profile API, with every edit **AI-drafted → operator-reviewed → applied** (never silently pushed). This is the suite's second **write** integration with GBP (after GBP Posts).

**Depends on:** the live GBP connection layer built for GBP Posts + GBP Insights — `services/gbp_auth.py` (OAuth-as-agency-account, service-account fallback, `business.manage` scope), `services/gbp_locations_service.py` (the v1 Business Information client + client→listing auto-match + `gbp_locations` registry), `services/gbp_performance_service._build` / `classify_access_error`, and the `gbp_oauth`/`gbp_invitations` connect flow. **This module reuses that layer wholesale — no new auth, no new scope, no new connection UI.** (Verified against the code 2026-09-04 — see §12.)

**Sibling docs:** `docs/modules/gbp-posts-module-prd-v1_0.md` (the closest analog — same spine, different Google surface; this PRD deliberately mirrors its structure and reuses its patterns), `docs/modules/client-reporting-prd-v1_0.md`, `docs/modules/maps-geogrid-strategy-prd-v1_0.md`, the `docs/sops/` GBP Authority SOPs. **Module build docs:** `docs/modules/gbp-profile-editor/CLAUDE.md` (build orientation + the verified reuse map) and `docs/modules/gbp-profile-editor/HANDOFF.md` (current state, phase plan, gotchas, activation).

**Sibling code already shipped:** the **`gbp_audit` description-quality upgrade** (PR #1009) — the deferred follow-up that de-idles this module's strategist loop for the description field. `gbp_audit` now emits a `description_quality: {ok, length, issues[]}` finding (`too_short`/`missing_service_keyword`/`missing_location`) alongside the binary completeness check, so a mature client's present-but-thin description is diagnosable and this module's loop can act on it. See §1-Why and §4-Phase-2.

**Preflight tool:** the existing `writer/platform-api/scripts/verify_gbp_api_access.py` proves the connection chain (auth → account → location). Phase 0 extends it with a `locations.get` read + a `locations.patch` round-trip on a designated test listing (see §3).

---

## 1. What this is

A per-client tool that reads a client's current Google Business Profile **description, services, and operating hours**, proposes improved versions (AI-drafted from the client's stored context — brand voice, ICP, differentiators, services, reviews, keyword research), shows **current → proposed** side by side, and — only on an explicit operator **Apply** — writes the change to Google via the Business Information API (`locations.patch`). It keeps a full edit history, surfaces Google's asynchronous **pending-review / rejected** verdicts honestly, and is hard-gated by the Freeze Protocol.

Everything GBP so far is either read-only capture (Outscraper/DataForSEO profile + reviews on `clients.gbp`; the GBP Insights metrics layer) or a **Posts** write. This module adds the ability to change **structured profile fields** the client's customers see on the listing itself. That raises the blast radius above Posts (a wrong description/hours/services sits on the profile until corrected, versus a post that scrolls away), so the approval model (§5) is stricter: **nothing is auto-applied in v1** (locked — see ADR 0004).

### Why (product rationale — corrected 2026-09-04)

The honest justification is **absorbing manual GBP dashboard work** — editing a client's description, services, and hours is per-client, per-field work the team does by hand today, and it's exactly the standing GBP Authority work the suite is systematically absorbing. That stands on its own.

The **strategist loop is a genuine but narrow bonus, not the reason.** An earlier draft of this PRD claimed `gbp_audit` "already diagnoses description/category/service/review gaps" and this module is "the missing lever." A 2026-09-04 code audit corrected that:

| `gbp_audit` finding (verified) | This module's lever | Maps to a v1 lever? |
|---|---|---|
| `description_quality` (built in #1009: `too_short`/`missing_service_keyword`/`missing_location`) | description editor | ✅ **the one real, now-built loop trigger** |
| `hours` completeness (missing/incomplete) | hours editor | ✅ (fires mainly for new/thin listings) |
| `category` / `category_gaps` | — | ❌ categories are **out of scope in v1** (§4 Phase 3) |
| `review_gap` | — | ❌ reviews are a **separate surface** |
| "service gap" | services editor | ❌ **no such finding exists** — deferred, see below |

So the loop's **automatic** half (the Action-Plan producer) fires on **description quality** and **hours-missing** only. For the **services** field there is **no automatic trigger yet** — a real service gap needs the listing's *live* services to diff against, which nothing captures today (§2, §9.4). The loop's **on-demand** half (the SerMaStr action) is not gated by diagnosis and has day-one value. This narrowness is deliberate and documented (see §4-Phase-2 and `decisions.md`); the remedy for "more loop" is the named `gbp_audit` follow-up (a description-quality check — **shipped in #1009** — plus a future service-gap check that rides this module's own live-services read), never loosening a threshold.

- **Services + description are local-pack relevance signals.** Complete, keyword-relevant services and a well-written description feed the same local relevance the Maps geo-grid tracker and Action Plan measure. The suite already knows a client's real services (keyword research, silo plans, Local SEO pages) — drafting a strong services list and description from that is nearly free.
- **Hours accuracy is a trust + conversion signal** (and a GBP suspension risk when wrong). A structured editor with review beats hand-editing per client in the dashboard.

### Non-goals (v1)

- **Editing anything other than description, services, and hours.** Categories, attributes, phone numbers, website URL, business name, address, service area, opening date, labels, photos, logo/cover — all separate GBP fields; out of scope for v1 (categories + attributes are the obvious Phase 3 extension since `gbp_audit` also flags category gaps — see §4).
- **Review replies / Q&A / product editor / posts** — separate surfaces (Posts is its own module).
- **Auto-apply.** Every edit requires an explicit human Apply in v1 (§5, ADR 0004). AI *drafts*; a human *applies*.
- **Bulk cross-client / cross-location apply.** v1 is per-client, **per-location, one location at a time** (§4). (A "roll this hours change across N locations" flow is a possible follow-up but is not v1.)
- **Client-facing self-serve** — internal team use only, like the rest of the suite.

---

## 2. The Google API surface (facts the build must respect)

> **Verification note:** `developers.google.com` and `googleapis.dev` are egress-blocked from the Claude Code sandbox, so the exact field paths below were confirmed from web search + prior integration knowledge, **not** re-read against the canonical reference. **Re-verify the field paths, the `RegularHours`/`TimeOfDay` shape, the `ServiceItem` shape, and the pending-edit/verification fields against the live reference at build time** (reachable from the Railway PLATFORM shell): `developers.google.com/my-business/reference/businessinformation/rest/v1/accounts.locations`. This mirrors how the Posts PRD handles the same "re-check at build time" caveat.

- **API:** the **My Business Business Information API v1** (`mybusinessbusinessinformation.googleapis.com/v1`). Unlike Posts (which live only on the legacy v4 REST API and are called with raw httpx), this API **is in Google's discovery service** and the app **already builds a client for it** — `gbp_locations_service._build("mybusinessbusinessinformation", creds)` → `googleapiclient.discovery.build(...)`. Reads (`accounts.locations.list`) are already in production for the client→listing auto-match; **this module adds the write path (`locations.get` + `locations.patch`)** on the same client. (Confirmed 2026-09-04: neither `locations.get` nor `locations.patch` is called anywhere today — this is genuinely new.)
- **⚠️ Two `_build` helpers exist — use the right one.** `gbp_locations_service._build(service_name, creds)` hardcodes `"v1"` and is the one the auto-match reads already use → **use it for this module's v1 Business Information client.** `gbp_performance_service._build(service_name, version="v1", creds=None)` has a different signature (it serves the Performance API). Don't cross the wires.
- **Auth:** the same `business.manage` OAuth scope and the same credential selection (`gbp_auth.credentials()` — OAuth-as-agency-account preferred, service-account fallback). **No new scope or consent** — the connected account that already lists/manages these listings can also patch them, subject to per-listing edit rights (§9 risk 1).
- **Access gate:** the Business Profile API family defaults to **0 QPM** until Google approves the project; this project is **approved (~300 QPM, confirmed 2026-07-20)** and the grant covers the API family, including Business Information v1 (already exercised by the auto-match reads).
- **Read (get current):** `accounts.locations.get(name="locations/{id}", readMask=...)`. `readMask` is a `FieldMask` naming exactly the fields to return. For this module: `readMask=profile.description,regularHours,specialHours,serviceItems,title,categories,metadata`. **`categories` is required in the readMask** — the free-form services editor needs the listing's categories to attach each service to (§4 Phase 1, decision Q8).
- **Write (apply an edit):** `accounts.locations.patch(name="locations/{id}", body=<Location>, updateMask=...)`. `updateMask` names exactly the fields being written; anything not in the mask is untouched. **One `updateMask` per field** we edit, so a description edit can never accidentally clobber hours.

| Field | `updateMask` path | Shape (v1) |
|---|---|---|
| **Business description** | `profile.description` | `Location.profile` is a `Profile` object; `profile.description` is a plain string. **Max 750 characters.** No URLs or phone numbers (content-policy rejection triggers). |
| **Operating hours** | `regularHours` | `RegularHours`/`BusinessHours` = `{periods: [TimePeriod]}`; each `TimePeriod` = `{openDay, closeDay (enum MONDAY…SUNDAY), openTime, closeTime}`. **`openTime`/`closeTime` are structured `TimeOfDay` objects `{hours: 0–23, minutes: 0–59}`** in v1 — NOT the v4 `"HHMM"` strings. A 24-hour day and closed days have specific encodings (re-verify exact conventions at build time). |
| **Holiday / special hours** | `specialHours` | `SpecialHours = {specialHourPeriods: [{startDate, endDate, openTime, closeTime, closed}]}`. Optional companion to regular hours. |
| **Services** | `serviceItems` | `serviceItems` is a `List[ServiceItem]` **on the Location object** (v1 moved these onto the location; there is no separate services endpoint). Each `ServiceItem` is **either** a `structuredServiceItem {serviceTypeId, description}` (the `serviceTypeId` must be one of the listing's category's Google-defined service types — Phase 3) **or** a `freeFormServiceItem {categoryId, label: {displayName, description, languageCode}}`. **v1 uses free-form** (Q8): each free-form service carries a `categoryId` that must be one of the listing's categories. |

- **Pending-review / verification state:** an edit does not always publish instantly — Google may queue certain field edits for review, and an **unverified** listing has limited editability. The location's `metadata` / `LocationState` (e.g. `hasPendingEdits`, `isVerified`, `canModifyServiceList`, `canOperateLocalPost`) carry this. **The build must read this state and surface it honestly** (`gbp_edit_pending_review`) rather than reporting "done" (see §5, §9).
- **Validation errors:** Google rejects a patch on content policy (description length/links/phone/promotional), a `serviceTypeId`/`categoryId` that doesn't belong to the listing's categories, or malformed hours. These come back as 400s and must be classified into actionable codes (reuse `gbp_performance_service.classify_access_error` + `gsc_service._extract_status_code` + the `ErrorDetails` registry, §8).
- **Edit rights ≠ read rights:** the connected account can *list* a listing it can't fully *edit*. `canModifyServiceList` / the patch's own error is the truth; per-listing failures must be handled, not assumed away (§9 risk 1).

---

## 3. Permissions & activation checklist (Phase 0)

The connection layer is **already live** (GBP Posts + Insights run on it), so most of this is satisfied. What's new is proving the **write** path for these fields specifically.

| # | Layer | What "correct" looks like | Status / how to fix |
|---|---|---|---|
| 1 | Auth + scope | `gbp_auth.credentials()` mints a token for `business.manage` | ✅ Live (Posts/Insights) |
| 2 | Business Information API v1 enabled + quota | `accounts.locations.list` returns 200 (~300 QPM) | ✅ Live (auto-match reads) |
| 3 | Listing registered to client | `gbp_locations` row with `access_status='ok'` | ✅ Reuses the existing auto-match/register flow |
| 4 | **Read current fields** | `locations.get(readMask=profile.description,regularHours,serviceItems,categories,…)` returns 200 with the fields populated | **New — Phase 0 adds to `verify_gbp_api_access.py`** |
| 5 | **Edit rights on the fields** | `metadata`/`LocationState` shows `isVerified` + `canModifyServiceList`; a `locations.patch` of `profile.description` on a **test listing** (the agency's own, not a client's) round-trips and reads back | **New — Phase 0 `--edit-test` flag; use the agency listing (decision Q9d)** |

Phase 0 exit criteria: a `locations.get` returns the fields for a pilot client, **and** a description patch on the agency's own listing round-trips (proving write access end-to-end) before any client listing is touched.

---

## 4. Product scope & phasing

**Field sequencing (decision Q2):** ship the AI-draftable fields first — **description → services → hours**. Hours is manual-only (the AI never drafts it, §4 Phase 2) and carries GBP-suspension risk, so it lands last and behind an extra "confirm the values you typed are correct" step.

### Phase 0 — Read + write proof (small code, mostly the verify script)
- Extend `verify_gbp_api_access.py` with the `readMask` get + an `--edit-test` patch/read-back on the agency listing.
- Add the config split: a new **`gbp_profile_enabled`** flag on top of the shared `gbp_api_enabled` (both default off), exactly like `gbp_posts_enabled`.
- Exit: write path proven on the agency's own listing; no client listing touched.

### Phase 1 — Read current + manual edit + apply + history + reconciler (the core)
- **Per-location (decision Q5):** the editor is scoped to one registered location at a time via the existing location picker (`RegisterLocations`). No bulk, no cross-location apply.
- **Read current** the three fields per selected location (`locations.get`) and display them. **Always read live on page load** (no cached "current" — the live value is authoritative vs a copy that drifts when someone edits in the Google dashboard, §9.5).
- **Manual editor** per field:
  - Description: a textarea with a live 750-char counter + a **client-side content-policy linter (decision Q9/Q12)** — advisory **warnings only, never a gate** — flagging URLs, phone numbers, ALL-CAPS ratio, promotional phrasing ("best/#1/guaranteed"), excess punctuation/emoji, special chars. Google's `rejected` verdict + the reconciler remain the source of truth; the linter only reduces failed submits. Hard-block only the deterministic trio (length/URL/phone) if desired; everything fuzzy is a warning.
  - Hours: a structured weekly editor (7 rows, open/close times, "closed" / "open 24h" toggles) mapping to `regularHours.periods` with `TimeOfDay`; optional special-hours rows. Manual-only + the extra confirm step (Q2).
  - Services: an add/remove/reorder list of **free-form** services (label + optional description). **The operator picks the `categoryId` per service (decision Q8)** from the listing's own categories; Apply is blocked until every service has a valid category. Structured services deferred to Phase 3.
- **Apply (decision Q3 — re-read-and-diff):** Apply runs as an `async_jobs` **`gbp_profile_apply`** job (freeze-gated). It **re-reads the field via `locations.get` and compares to the draft's `current_value` snapshot; if the live value changed out-of-band since drafting, it aborts into a `live_changed` re-review state instead of patching** (never silently clobbers a dashboard edit it didn't see). Otherwise it `locations.patch`es with the single-field `updateMask`, persists the result + Google's pending state, then a short-delay sync re-read.
- **Reconciler (decision Q4/Q7):** a new `async_jobs` **`gbp_profile_sync`** type — a **self-continuing per-edit** job keyed to a `pending_review` edit row (does one `locations.get`; if still pending, enqueues the next check with a future `scheduled_at`, the `leadoff_geocode` pattern, since the 30-min reaper forbids a sleep-poll). Bounded backoff **+2 min / +30 min / +2 h / +12 h / +24 h → give up**. Terminal states: `applied` (live == proposed), `rejected` (Google rejected), or give-up → **stays `pending_review`** with a manual "Refresh status" available (never a fake terminal). **Distinct** from the Phase-3 periodic drift sweep.
- **History**: every proposed/applied edit as a `gbp_profile_edits` row (current→proposed snapshot, status, who, when), with a per-field "current live value" always visible.
- **Freeze Protocol**: `gbp_profile_apply` **and** `gbp_profile_sync` join `FREEZE_GATED_JOB_TYPES`; the apply route calls `assert_not_frozen`. Reads/drafts keep running (observation, not output).

### Phase 2 — AI drafting + the strategist loop
- **AI draft per field** (`gbp_profile_draft` job — runs during a freeze, drafting is observation):
  - **Description**: one bounded Claude call grounded in `build_client_context` (name, services, brand voice card, ICP, differentiators) + review themes + the current description. Guardrails: ≤750 chars, no URLs/phone, no regulated claims, obey the distilled Voice Card. Reuses `render_voice_card_block` + `voice_forbidden_hits` + `voice_card_service.get_voice_card` verbatim from GBP Posts.
  - **Services (grounding, decision Q10)**: propose a services list from **`clients.gbp` categories + silo plans** (both best-effort/degrading; no silo plan → fall back to categories + brand context). Keyword-research + Local-SEO-page-inventory mining is a deferred Phase 2.5 quality bump, not v1. Free-form labels + short descriptions, deduped against what's already live. **For each drafted service the AI suggests a `categoryId` from the listing's categories and the operator confirms/overrides (decision Q11)** — Apply stays blocked until every service has a valid category.
  - **Hours**: **conservative by default** — the model does NOT invent hours. It only *proposes normalizations* from data the suite already holds (e.g. `clients.gbp` captured hours) or flags "hours missing/incomplete" for a human to fill. Inventing operating hours is a hard prohibition.
- **Review UI**: current → proposed diff per field, Edit-the-draft, Apply / Discard.
- **Strategist loop (decision Q6 — build BOTH, honest about reach):** `gbp_audit`'s findings that map to a lever become **proposed `gbp_profile_edits`** (`status='draft'`, `source='strategist'`) for one-click approval — wired as **both**:
  - **(a) a SerMaStr action** `update_gbp_profile` (parameterized + staged + reply-*yes* confirm-gated, mirroring the campaign-edit actions like `update_client_profile`). **It stages a draft into the review queue — it does NOT apply** (consistent with no-auto-apply and the strategist's "propose, never execute" contract; a human still clicks Apply).
  - **(b) an Action-Plan producer** that creates a board task deep-linking into the editor pre-seeded with the drafted fix (the `cta_path` pattern; the existing `gbp_gap` action's CTA can also deep-link here).
  - **Honest reach:** today the loop's automatic producer fires on **`description_quality`** (built in #1009) and **hours-missing** only; **services has no automatic trigger** until `gbp_audit` gains a service-gap check (§9.4). The full wiring is built now so it lights up with zero integration work when that check lands; the on-demand action delivers value immediately regardless. **Nothing auto-applies.**

### Phase 3 — Extensions (deferred)
- **Structured services** (`structuredServiceItem` + the category `serviceTypes` lookup) for richer Google-recognized services, and **per-service category assignment by the AI** (Q8's B/C beyond the operator pick).
- **Service-gap check in `gbp_audit`** (the deferred half of the loop): once this module's live-services read exists, diff live `serviceItems` against the client's expected set (silos/categories) → a real `service_gaps` finding that gives the services lever an automatic trigger.
- **Categories + attributes editing** (the other half of what `gbp_audit` flags).
- **Sync-back drift detection** as a scheduled periodic job (detect out-of-band edits made in the Google dashboard and reconcile `current_value`) — distinct from the Phase-1 per-edit reconciler.
- **Client Report line** ("Profile updates this period") + strategy-digest `gbp_profile` provider.

---

## 5. Approval model (locked for v1 — see ADR 0004)

Editing structured profile fields is a higher-blast-radius outward act than a post (the change persists on the listing). Therefore:

- **No auto-apply, ever, in v1.** Every edit — manual, AI-drafted, or strategist-proposed — requires an explicit operator **Apply** click. The click *is* the approval. This is the deliberate divergence from GBP Posts (which supports opt-in auto-publish per schedule); the rationale, alternatives, and consequences are recorded in `docs/adr/0004-gbp-profile-edits-never-auto-applied.md`.
- AI drafts and strategist proposals land as `status='draft'`; a human reviews current→proposed and applies.
- **Re-read-and-diff at Apply (Q3):** Apply re-reads the live field and aborts into `live_changed` if it drifted since the draft, rather than clobbering an unseen dashboard edit.
- A **frozen client blocks all applies** (`gbp_profile_apply` freeze-gated + `assert_not_frozen`). Drafting still runs during a freeze (marked "held by freeze"), so nothing is lost.
- Google's **pending-review** verdict is surfaced honestly: an applied edit that Google queues shows `pending_review`, not `applied`, and the **`gbp_profile_sync` reconciler** (Q4/Q7) resolves it hands-free (bounded backoff) or leaves it honestly pending with a manual refresh.

---

## 6. Data model (new migration; suite conventions — RLS enabled, no policies, service-role only)

```sql
gbp_profile_edits (
  id uuid pk,
  client_id uuid fk clients on delete cascade,
  location_row_id uuid fk gbp_locations on delete cascade,
  field text not null,                      -- 'description' | 'hours' | 'services'
  source text not null default 'manual',    -- manual | ai | strategist
  current_value jsonb,                      -- snapshot at draft time (the re-read-and-diff baseline)
  proposed_value jsonb not null,            -- the edit to apply
  status text not null default 'draft',     -- draft | applying | applied | pending_review | rejected | live_changed | failed
  google_pending boolean not null default false,  -- Google queued it for review
  sync_attempts int not null default 0,     -- reconciler backoff progress
  next_sync_at timestamptz,                 -- reconciler self-continuation clock
  error text,
  applied_at timestamptz,
  created_by uuid,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
)
-- index on (client_id, field, created_at desc) for the per-field history read
-- partial index on (next_sync_at) where status = 'pending_review' for the reconciler sweep
```

No separate "current values" table — the live values are read on demand via `locations.get` (cheap, and always authoritative vs a cached copy that drifts when someone edits in the Google dashboard). `current_value` on the edit row is the point-in-time snapshot for the diff/audit trail **and** the re-read-and-diff baseline at Apply.

`async_jobs.job_type` CHECK widened (additive, **rebuilt from the LIVE constraint** — wider than any single repo migration, same caveat as prior GBP migrations; follow the `20260902180000_guide_sync.sql` pattern): `gbp_profile_apply`, `gbp_profile_draft`, **`gbp_profile_sync`**.

---

## 7. Services & code layout

| Piece | Path | Notes |
|---|---|---|
| API client | `services/gbp_profile_api.py` | Thin v1 wrapper over the existing discovery client (`gbp_locations_service._build("mybusinessbusinessinformation", creds)` — the v1-hardcoded one, NOT the performance-service `_build`): `get_location(name, read_mask)`, `patch_location(name, body, update_mask)`. **Pure builders/validators** — `build_description_patch`, `build_hours_patch` (weekly rows → `regularHours.periods` with `TimeOfDay`), `build_services_patch` (labels + operator-picked `categoryId` → `serviceItems` free-form), `validate_description` (≤750, no URL/phone), `lint_description` (advisory fuzzy warnings, Q9), `diff_field` (re-read-and-diff, Q3), `parse_location_fields`, `classify_profile_error` — all unit-tested without Google. Reuses `gbp_performance_service.classify_access_error` + `gsc_service._extract_status_code` for error mapping. |
| Module service | `services/gbp_profile_service.py` | Read-current, draft (per-field), apply job runner (with re-read-and-diff), the `gbp_profile_sync` reconciler (self-continuing backoff), config + freeze gates. Reuses `build_client_context`, `render_voice_card_block`, `voice_forbidden_hits`, `voice_card_service.get_voice_card` from the Posts module. Services grounding = `clients.gbp` categories + silo plans (Q10). |
| Router | `routers/gbp_profile.py` | `GET /clients/{id}/gbp/profile` (current live values, per selected location), `POST …/profile/draft` (enqueue a draft), `GET …/profile/edits` (history), `PATCH …/profile/edits/{edit_id}` (edit the draft), `POST …/profile/edits/{edit_id}/apply`, `POST …/profile/edits/{edit_id}/discard`, `POST …/profile/edits/{edit_id}/refresh` (manual reconciler kick). Staff-gated; apply is `assert_not_frozen`. |
| Models | `models/gbp_profile.py` | `ProfileEditRequest`, `HoursRow`, `ServiceItemInput` (label + `category_id`), response schemas. **Declare every field the frontend reads** — Pydantic strips undeclared keys silently (the #844 lesson; already bit `MapsGbpAuditResponse` in #1009). |
| SerMaStr action | `services/slack_assistant/actions.py` | `update_gbp_profile` — staged + reply-*yes* confirm-gated, mirroring `update_client_profile`. **Stages a `status='draft'` edit; never applies** (Q6). |
| Action-Plan producer | `services/task_producers.py` | A producer that turns a lever-mapped `gbp_audit` finding into a board task deep-linking into the pre-seeded editor (Q6). |
| Frontend | `pages/GbpProfile.tsx` + a "Business Profile" workspace card | Location picker (reuse `RegisterLocations`) → three field cards (Description / Hours / Services), each showing current live value → proposed, with Draft-with-AI / Edit / Apply / Discard + `ErrorDetails` on failure. Description card renders the advisory linter warnings; Services card renders the per-service category picker. Reuses `useResumableJob` for the draft/apply/sync jobs. Renders an enablement notice when gated off (503). |
| Verify | `scripts/verify_gbp_api_access.py` | Extended with the `readMask` get + `--edit-test` patch round-trip. |
| Tests | `tests/test_gbp_profile.py` | Pure builders/validators (hours mapping incl. closed/24h, description validation + linter, services dedup + category attach), error classification, apply-job idempotency + re-read-and-diff abort, reconciler backoff/terminal states, draft-prompt assembly. |

Config (`config.py`): `gbp_profile_enabled` (False), `gbp_profile_draft_model` (default `claude-sonnet-4-6`), `gbp_profile_draft_max_tokens`, `gbp_profile_description_max_chars` (750), `gbp_profile_sync_delay_seconds` (the immediate post-apply re-read delay), `gbp_profile_sync_backoff` (the +2m/+30m/+2h/+12h/+24h ladder).

---

## 8. Error handling & the `ErrorDetails` accordion

Every failure path returns a classified code the frontend `ErrorDetails` registry (`frontend/src/lib/errorGuidance.ts`) already renders as an actionable accordion. New codes to add:
- `gbp_profile_not_enabled` (503, module gated off)
- `gbp_listing_read_only` / `cannot_modify_services` (the connected account lists but can't edit this field — names the fix: verify the listing / check manager permissions)
- `gbp_listing_unverified`
- `description_too_long`, `description_contains_url`, `description_contains_phone` (deterministic; client-side + server-side; carry the offending value)
- `invalid_service_category` (a free-form `categoryId` not in the listing's categories; `invalid_service_type` for structured — Phase 3)
- `gbp_edit_pending_review` (informational — the apply succeeded but Google queued it)
- `gbp_edit_live_changed` (Q3 — the live value drifted since the draft; re-review before applying)
- `client_frozen` (existing)

---

## 9. Risks / open questions

1. **Edit rights ≠ read rights (the main risk).** The connected agency account may manage a listing for reads/posts but lack full edit rights on a specific field (or the listing is unverified). Mitigation: read `LocationState`/`metadata` (`isVerified`, `canModifyServiceList`) before offering an edit, classify the patch's own 403/400 into `gbp_listing_read_only`/`cannot_modify_services`, and surface it — never silently swallow.
2. **Pending-review latency.** Some edits (description especially) don't go live instantly. Mitigation: the `pending_review` status + the `gbp_profile_sync` reconciler (Q7) + the short-delay sync re-read; the UI says "submitted to Google, pending review" rather than "live."
3. **Hours are high-trust + suspension-sensitive.** Wrong hours damage the client and can trip GBP suspension. Mitigation: the AI never invents hours (§4 Phase 2); hours are the one field where a human must supply/confirm the actual values, behind the extra confirm step (Q2).
4. **Structured vs free-form services.** Structured services need a category `serviceTypes` lookup and are constrained to the listing's categories; free-form works for any listing. **Locked: free-form first (Phase 1, Q8), structured in Phase 3.** The **service-gap `gbp_audit` finding is deferred** (Phase 3) because it needs live `serviceItems` this module's read layer provides — building it earlier would mean a throwaway capture path.
5. **Out-of-band edits.** Someone edits the listing in the Google dashboard; our snapshot drifts. Mitigation: always read live values on page load (no cached "current"); **re-read-and-diff at Apply (Q3)**; Phase 3 adds scheduled periodic drift detection.
6. **Category editing is adjacent and tempting** — `gbp_audit` flags category gaps too. Deliberately out of v1 (categories change ranking behavior and have their own validation); Phase 3.

**Open questions — all resolved in the 2026-09-04 grilling (recorded in `decisions.md`):**
- (a) **No-auto-apply for v1** — confirmed (§5, ADR 0004).
- (b) **Free-form services first**, structured deferred — confirmed (§9.4).
- (c) Strategist loop wiring — **both** a SerMaStr action *and* an Action-Plan producer (Q6), honest that it fires on description-quality + hours-missing until a service-gap check lands.
- (d) Test listing for `--edit-test` — the **agency's own** GBP listing (Q9d).

---

## 10. Success metrics

- Pilot: a client's description, services, and hours edited end-to-end through the app (draft → apply → confirmed live) with zero dashboard work.
- Strategist loop: a `description_quality`-flagged (from #1009) or hours-missing gap goes from finding → drafted fix → approved → live in one review pass.
- Zero silent failures: every read-only-listing / pending-review / rejection / out-of-band-drift is surfaced with an actionable `ErrorDetails` code, never a green state that isn't true.

---

## 11. Relationship to existing GBP surfaces

| Surface | Direction | API | This module |
|---|---|---|---|
| GBP data capture (`gbp_service`) | read | DataForSEO/Outscraper | source of some draft grounding (categories, reviews, captured hours) |
| GBP Insights (`gbp_metrics_*`) | read | Business Profile Performance v1 | sibling; same connection layer |
| GBP Posts (`gbp_posts_*`) | write | My Business v4 `localPosts` | sibling; the pattern template this PRD mirrors (but stricter approval — ADR 0004) |
| **GBP Profile Editor (this)** | **write** | **Business Information v1 `locations.patch`** | **new — description / hours / services** |

All four share `gbp_auth` + `gbp_locations` + the connect flow. This module is the second write integration and the first to change structured, persistent profile fields — hence the stricter, no-auto-apply approval model.

---

## 12. Reuse claims verified against the code (2026-09-04)

Before approval, the PRD's load-bearing reuse claims were checked against the live code (three parallel audits):
- **Connection layer — all TRUE.** `gbp_auth.credentials()` (OAuth-preferred, SA fallback, `business.manage`); `gbp_locations_service._build("mybusinessbusinessinformation", creds)` (hardcodes v1) with `accounts.locations.list` in production for auto-match; `gbp_locations` registry + `access_status='ok'`; `gbp_performance_service._build`/`classify_access_error`; `gsc_service._extract_status_code`. **`locations.get`/`locations.patch` are called nowhere today** — the write path is genuinely new. One wrinkle: **two `_build` signatures** (see §2).
- **Posts pattern — all TRUE.** `gbp_posts_api.py` (httpx v4, no discovery client), `gbp_posts_service.py`, `routers/gbp_posts.py`, `models/gbp_posts.py`, `frontend/src/pages/GbpPosts.tsx`; `gbp_api_enabled`/`gbp_posts_enabled` both default False; `FREEZE_GATED_JOB_TYPES` in `services/freeze.py` with `gbp_post_publish` gated + `assert_not_frozen`; the voice/brand reuse fns. Posts **does** support opt-in auto-publish per schedule — the deliberate contrast with this module (ADR 0004).
- **`gbp_audit` / strategist loop — PARTIAL, corrected in §1.** `gbp_audit.audit()` is pure and emits `score/checks/gaps/category_gaps/review_gap/competitor_count` — **and now `description_quality` (#1009)**. It does **not** emit a service gap (never did). Consumed by `reopt_planner.build_gbp_action` + `strategy_digest._prov_gbp_audit`. The SerMaStr action registry (`slack_assistant/actions.py` `_ACTIONS`) and the Action-Plan producer pattern (`task_producers.sync_action_plan_tasks`) both exist and support what §4-Phase-2 proposes. The strategist "propose, never execute" contract is enforced in `strategist.sanitize_review`.
