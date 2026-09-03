# GBP Profile Editor Module — PRD v1.0

**Status:** Proposed (owner ask, 2026-09-03). Not yet approved for build. Authoritative for the GBP Profile Editor module once approved.

**Owner ask (2026-09-03):** "Could we use [the GBP API] to update/edit the business description, services, and operating hours? … I would like to build this. Edits can be AI drafted."

**Scope of this doc:** a per-client tool to **edit three fields of a client's Google Business Profile** — the **business description**, **services**, and **operating hours** — through the Business Profile API, with every edit **AI-drafted → operator-reviewed → applied** (never silently pushed). This is the suite's second **write** integration with GBP (after GBP Posts).

**Depends on:** the live GBP connection layer built for GBP Posts + GBP Insights — `services/gbp_auth.py` (OAuth-as-agency-account, service-account fallback, `business.manage` scope), `services/gbp_locations_service.py` (the v1 Business Information client + client→listing auto-match + `gbp_locations` registry), `services/gbp_performance_service._build` (the discovery-client builder), and the `gbp_oauth`/`gbp_invitations` connect flow. **This module reuses that layer wholesale — no new auth, no new scope, no new connection UI.**

**Sibling docs:** `docs/modules/gbp-posts-module-prd-v1_0.md` (the closest analog — same spine, different Google surface; this PRD deliberately mirrors its structure and reuses its patterns), `docs/modules/client-reporting-prd-v1_0.md`, `docs/modules/maps-geogrid-strategy-prd-v1_0.md`, the `docs/sops/` GBP Authority SOPs.

**Preflight tool:** the existing `writer/platform-api/scripts/verify_gbp_api_access.py` proves the connection chain (auth → account → location). Phase 0 extends it with a `locations.get` read + (optional) a `locations.patch` round-trip on a designated test listing (see §3).

---

## 1. What this is

A per-client tool that reads a client's current Google Business Profile **description, services, and operating hours**, proposes improved versions (AI-drafted from the client's stored context — brand voice, ICP, differentiators, services, reviews, keyword research), shows **current → proposed** side by side, and — only on an explicit operator **Apply** — writes the change to Google via the Business Information API (`locations.patch`). It keeps a full edit history, surfaces Google's asynchronous **pending-review / rejected** verdicts honestly, and is hard-gated by the Freeze Protocol.

Everything GBP so far is either read-only capture (Outscraper/DataForSEO profile + reviews on `clients.gbp`; the GBP Insights metrics layer) or a **Posts** write. This module adds the ability to change **structured profile fields** the client's customers see on the listing itself. That raises the blast radius above Posts (a wrong description/hours/services sits on the profile until corrected, versus a post that scrolls away), so the approval model (§5) is stricter: **nothing is auto-applied in v1.**

### Why (product rationale)

- **The strategist already diagnoses these gaps but can't act on them.** `services/gbp_audit.py` (used by the reopt planner and the strategy digest) flags description gaps, category gaps, and review deficits vs local-pack competitors. Today that produces advice a human executes by hand in the GBP dashboard. This module is the **lever** that closes the loop — a flagged gap becomes an AI-drafted, one-click-approvable fix (Phase 2).
- **Services + description are local-pack relevance signals.** Complete, keyword-relevant services and a well-written description feed the same local relevance the Maps geo-grid tracker and Action Plan measure. The suite already knows a client's real services (keyword research, silo plans, Local SEO pages) — drafting a strong services list and description from that is nearly free.
- **Hours accuracy is a trust + conversion signal** (and a GBP suspension risk when wrong). A structured editor with review beats hand-editing per client in the dashboard.
- **It's manual, per-client, dashboard work today** — exactly the standing GBP Authority work the suite is systematically absorbing.

### Non-goals (v1)

- **Editing anything other than description, services, and hours.** Categories, attributes, phone numbers, website URL, business name, address, service area, opening date, labels, photos, logo/cover — all separate GBP fields; out of scope for v1 (categories + attributes are the obvious Phase 3 extension since `gbp_audit` also flags category gaps — see §11).
- **Review replies / Q&A / product editor / posts** — separate surfaces (Posts is its own module).
- **Auto-apply.** Every edit requires an explicit human Apply in v1 (§5). AI *drafts*; a human *applies*.
- **Bulk cross-client apply.** v1 is per-client, per-field. (A "roll this hours change across N locations" flow is a possible follow-up but is not v1.)
- **Client-facing self-serve** — internal team use only, like the rest of the suite.

---

## 2. The Google API surface (facts the build must respect)

> **Verification note:** `developers.google.com` and `googleapis.dev` are egress-blocked from the Claude Code sandbox, so the exact field paths below were confirmed from web search + prior integration knowledge, **not** re-read against the canonical reference in this session. **Re-verify the field paths, the `RegularHours`/`TimeOfDay` shape, the `ServiceItem` shape, and the pending-edit/verification fields against the live reference at build time** (reachable from the Railway PLATFORM shell): `developers.google.com/my-business/reference/businessinformation/rest/v1/accounts.locations`. This mirrors how the Posts PRD handles the same "re-check at build time" caveat.

- **API:** the **My Business Business Information API v1** (`mybusinessbusinessinformation.googleapis.com/v1`). Unlike Posts (which live only on the legacy v4 REST API and are called with raw httpx), this API **is in Google's discovery service** and the app **already builds a client for it** — `gbp_locations_service._build("mybusinessbusinessinformation", creds)` → `googleapiclient.discovery.build(...)`. Reads (`accounts.locations.list`) are already in production for the client→listing auto-match; **this module adds the write path (`locations.get` + `locations.patch`)** on the same client.
- **Auth:** the same `business.manage` OAuth scope and the same credential selection (`gbp_auth.credentials()` — OAuth-as-agency-account preferred, service-account fallback). **No new scope or consent** — the connected account that already lists/manages these listings can also patch them, subject to per-listing edit rights (§9 risk 1).
- **Access gate:** the Business Profile API family defaults to **0 QPM** until Google approves the project; this project is **approved (~300 QPM, confirmed 2026-07-20)** and the grant covers the API family, including Business Information v1 (already exercised by the auto-match reads).
- **Read (get current):** `accounts.locations.get(name="locations/{id}", readMask=...)`. `readMask` is a `FieldMask` naming exactly the fields to return. For this module: `readMask=profile.description,regularHours,specialHours,serviceItems,title,categories,metadata`.
- **Write (apply an edit):** `accounts.locations.patch(name="locations/{id}", body=<Location>, updateMask=...)`. `updateMask` names exactly the fields being written; anything not in the mask is untouched. **One `updateMask` per field** we edit, so a description edit can never accidentally clobber hours.

| Field | `updateMask` path | Shape (v1) |
|---|---|---|
| **Business description** | `profile.description` | `Location.profile` is a `Profile` object; `profile.description` is a plain string. **Max 750 characters.** No URLs or phone numbers (content-policy rejection triggers). |
| **Operating hours** | `regularHours` | `RegularHours`/`BusinessHours` = `{periods: [TimePeriod]}`; each `TimePeriod` = `{openDay, closeDay (enum MONDAY…SUNDAY), openTime, closeTime}`. **`openTime`/`closeTime` are structured `TimeOfDay` objects `{hours: 0–23, minutes: 0–59}`** in v1 — NOT the v4 `"HHMM"` strings. A 24-hour day and closed days have specific encodings (re-verify exact conventions at build time). |
| **Holiday / special hours** | `specialHours` | `SpecialHours = {specialHourPeriods: [{startDate, endDate, openTime, closeTime, closed}]}`. Optional companion to regular hours. |
| **Services** | `serviceItems` | `serviceItems` is a `List[ServiceItem]` **on the Location object** (v1 moved these onto the location; there is no separate services endpoint). Each `ServiceItem` is **either** a `structuredServiceItem {serviceTypeId, description}` (the `serviceTypeId` must be one of the listing's category's Google-defined service types) **or** a `freeFormServiceItem {categoryId, label: {displayName, description, languageCode}}`. |

- **Pending-review / verification state:** an edit does not always publish instantly — Google may queue certain field edits for review, and an **unverified** listing has limited editability. The location's `metadata` / `LocationState` (e.g. `hasPendingEdits`, `isVerified`, `canModifyServiceList`, `canOperateLocalPost`) carry this. **The build must read this state and surface it honestly** (`google_pending`) rather than reporting "done" (see §5, §9).
- **Validation errors:** Google rejects a patch on content policy (description length/links/phone), a `serviceTypeId` that doesn't belong to the listing's categories, or malformed hours. These come back as 400s and must be classified into actionable codes (reuse `gbp_performance_service.classify_access_error` + the `ErrorDetails` registry, §8).
- **Edit rights ≠ read rights:** the connected account can *list* a listing it can't fully *edit*. `canModifyServiceList` / the patch's own error is the truth; per-listing failures must be handled, not assumed away (§9 risk 1).

---

## 3. Permissions & activation checklist (Phase 0)

The connection layer is **already live** (GBP Posts + Insights run on it), so most of this is satisfied. What's new is proving the **write** path for these fields specifically.

| # | Layer | What "correct" looks like | Status / how to fix |
|---|---|---|---|
| 1 | Auth + scope | `gbp_auth.credentials()` mints a token for `business.manage` | ✅ Live (Posts/Insights) |
| 2 | Business Information API v1 enabled + quota | `accounts.locations.list` returns 200 (~300 QPM) | ✅ Live (auto-match reads) |
| 3 | Listing registered to client | `gbp_locations` row with `access_status='ok'` | ✅ Reuses the existing auto-match/register flow |
| 4 | **Read current fields** | `locations.get(readMask=profile.description,regularHours,serviceItems,…)` returns 200 with the fields populated | **New — Phase 0 adds to `verify_gbp_api_access.py`** |
| 5 | **Edit rights on the fields** | `metadata`/`LocationState` shows `isVerified` + `canModifyServiceList`; a `locations.patch` of `profile.description` on a **test listing** (the agency's own, not a client's) round-trips and reads back | **New — Phase 0 `--edit-test` flag; use the agency listing** |

Phase 0 exit criteria: a `locations.get` returns the three fields for a pilot client, **and** a description patch on the agency's own listing round-trips (proving write access end-to-end) before any client listing is touched.

---

## 4. Product scope & phasing

### Phase 0 — Read + write proof (small code, mostly the verify script)
- Extend `verify_gbp_api_access.py` with the `readMask` get + an `--edit-test` patch/read-back on the agency listing.
- Add the config split: a new **`gbp_profile_enabled`** flag on top of the shared `gbp_api_enabled` (both default off), exactly like `gbp_posts_enabled`.
- Exit: write path proven on the agency's own listing; no client listing touched.

### Phase 1 — Read current + manual edit + apply + history (the core)
- **Read current** the three fields per registered location (`locations.get`) and display them.
- **Manual editor** per field:
  - Description: a textarea with a live 750-char counter + client-side content-policy hints (no URLs/phone).
  - Hours: a structured weekly editor (7 rows, open/close times, "closed" / "open 24h" toggles) mapping to `regularHours.periods`; optional special-hours rows.
  - Services: an add/remove/reorder list of **free-form** services (label + optional description) — see §2; structured services deferred to Phase 3.
- **Apply** runs as an `async_jobs` **`gbp_profile_apply`** job (freeze-gated): `locations.patch` with the single-field `updateMask`, persist the result + Google's pending state, then a short-delay sync re-read.
- **History**: every proposed/applied edit as a `gbp_profile_edits` row (current→proposed snapshot, status, who, when), with a per-field "current live value" always visible.
- **Freeze Protocol**: `gbp_profile_apply` joins `FREEZE_GATED_JOB_TYPES`; the apply route calls `assert_not_frozen`. Reads/drafts keep running (observation, not output).

### Phase 2 — AI drafting + the strategist loop
- **AI draft per field** (`gbp_profile_draft` job — runs during a freeze, drafting is observation):
  - **Description**: one bounded Claude call grounded in `build_client_context` (name, services, brand voice card, ICP, differentiators) + review themes + the current description. Guardrails: ≤750 chars, no URLs/phone, no regulated claims, obey the distilled Voice Card. Reuses `render_voice_card_block` + `voice_forbidden_hits` + the `voice_card_service` cache verbatim from GBP Posts.
  - **Services**: propose a services list from the client's real services (keyword research, silo plans, Local SEO page inventory, `clients.gbp` categories) — free-form labels + short descriptions, deduped against what's already live.
  - **Hours**: **conservative by default** — the model does NOT invent hours. It only *proposes normalizations* from data the suite already holds (e.g. `clients.gbp` captured hours, or flags "hours missing/incomplete" for a human to fill). Inventing operating hours is a hard prohibition.
- **Review UI**: current → proposed diff per field, Edit-the-draft, Apply / Discard.
- **Strategist loop (the payoff)**: `gbp_audit`'s description/category/service/review-deficit findings become **proposed `gbp_profile_edits`** for one-click approval — wired as (a) a **SerMaStr action** (`update_gbp_profile`, parameterized + staged + reply-*yes* confirm-gated, mirroring the campaign-edit actions) and/or (b) a **producer/Action-Plan deep link** into the editor pre-seeded with the drafted fix. Nothing auto-applies; a human still approves — exactly the SerMaStr "propose, never execute" contract.

### Phase 3 — Extensions (deferred)
- **Structured services** (`structuredServiceItem` + the category `serviceTypes` lookup) for richer Google-recognized services.
- **Categories + attributes editing** (the other half of what `gbp_audit` flags).
- **Sync-back drift detection** as a scheduled job (detect out-of-band edits made in the Google dashboard and reconcile `current_value`).
- **Client Report line** ("Profile updates this period") + strategy-digest `gbp_profile` provider.

---

## 5. Approval model (locked for v1)

Editing structured profile fields is a higher-blast-radius outward act than a post (the change persists on the listing). Therefore:

- **No auto-apply, ever, in v1.** Every edit — manual, AI-drafted, or strategist-proposed — requires an explicit operator **Apply** click. The click *is* the approval.
- AI drafts and strategist proposals land as `status='draft'`; a human reviews current→proposed and applies.
- A **frozen client blocks all applies** (`gbp_profile_apply` freeze-gated + `assert_not_frozen`). Drafting still runs during a freeze (marked "held by freeze"), so nothing is lost.
- Google's **pending-review** verdict is surfaced honestly: an applied edit that Google queues shows `pending_review`, not `applied`, until the sync re-read confirms it went live.

---

## 6. Data model (new migration; suite conventions — RLS enabled, no policies, service-role only)

```sql
gbp_profile_edits (
  id uuid pk,
  client_id uuid fk clients on delete cascade,
  location_row_id uuid fk gbp_locations on delete cascade,
  field text not null,                      -- 'description' | 'hours' | 'services'
  source text not null default 'manual',    -- manual | ai | strategist
  current_value jsonb,                      -- snapshot at draft time (what was live)
  proposed_value jsonb not null,            -- the edit to apply
  status text not null default 'draft',     -- draft | applying | applied | pending_review | rejected | failed
  google_pending boolean not null default false,  -- Google queued it for review
  error text,
  applied_at timestamptz,
  created_by uuid,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
)
-- index on (client_id, field, created_at desc) for the per-field history read
```

No separate "current values" table — the live values are read on demand via `locations.get` (cheap, and always authoritative vs a cached copy that drifts when someone edits in the Google dashboard). `current_value` on the edit row is only the point-in-time snapshot for the diff/audit trail.

`async_jobs.job_type` CHECK widened (additive, preserving the full live set — the live CHECK is wider than any single repo migration, same caveat as prior GBP migrations): `gbp_profile_apply`, `gbp_profile_draft`.

---

## 7. Services & code layout

| Piece | Path | Notes |
|---|---|---|
| API client | `services/gbp_profile_api.py` | Thin v1 wrapper over the existing discovery client (`gbp_locations_service._build("mybusinessbusinessinformation", creds)`): `get_location(name, read_mask)`, `patch_location(name, body, update_mask)`. **Pure builders/validators** — `build_description_patch`, `build_hours_patch` (weekly rows → `regularHours.periods` with `TimeOfDay`), `build_services_patch` (labels → `serviceItems` free-form), `validate_description` (≤750, no URL/phone), `parse_location_fields`, `classify_profile_error` — all unit-tested without Google. Reuses `gbp_performance_service.classify_access_error` + `gsc_service._extract_status_code` for error mapping. |
| Module service | `services/gbp_profile_service.py` | Read-current, draft (per-field), apply job runner, sync re-read; config + freeze gates. Reuses `build_client_context`, `render_voice_card_block`, `voice_forbidden_hits`, `voice_card_service.get_voice_card` from the Posts module. |
| Router | `routers/gbp_profile.py` | `GET /clients/{id}/gbp/profile` (current live values, per location), `POST …/profile/draft` (enqueue a draft), `GET …/profile/edits` (history), `PATCH …/profile/edits/{edit_id}` (edit the draft), `POST …/profile/edits/{edit_id}/apply`, `POST …/profile/edits/{edit_id}/discard`. Staff-gated; apply is `assert_not_frozen`. |
| Models | `models/gbp_profile.py` | `ProfileEditRequest`, `HoursRow`, `ServiceItemInput`, response schemas. |
| Frontend | `pages/GbpProfile.tsx` + a "Business Profile" workspace card | Three field cards (Description / Hours / Services), each showing current live value → proposed, with Draft-with-AI / Edit / Apply / Discard + `ErrorDetails` on failure. Reuses the GBP location picker (`RegisterLocations`) and `useResumableJob` for the draft/apply jobs. Renders an enablement notice when gated off (503). |
| Verify | `scripts/verify_gbp_api_access.py` | Extended with the `readMask` get + `--edit-test` patch round-trip. |
| Tests | `tests/test_gbp_profile.py` | Pure builders/validators (hours mapping incl. closed/24h, description validation, services dedup), error classification, apply-job idempotency, draft-prompt assembly. |

Config (`config.py`): `gbp_profile_enabled` (False), `gbp_profile_draft_model` (default `claude-sonnet-4-6`, same family as other client-facing copy), `gbp_profile_draft_max_tokens`, `gbp_profile_description_max_chars` (750), `gbp_profile_sync_delay_seconds` (the post-apply re-read delay).

---

## 8. Error handling & the `ErrorDetails` accordion

Every failure path returns a classified code the frontend `ErrorDetails` registry (`frontend/src/lib/errorGuidance.ts`) already renders as an actionable accordion. New codes to add:
- `gbp_profile_not_enabled` (503, module gated off)
- `gbp_listing_read_only` / `cannot_modify_services` (the connected account lists but can't edit this field — names the fix: verify the listing / check manager permissions)
- `gbp_listing_unverified`
- `description_too_long`, `description_contains_url`, `description_contains_phone` (client-side + server-side; carry the offending value)
- `invalid_service_type` (a structured serviceTypeId not in the listing's categories — Phase 3)
- `gbp_edit_pending_review` (informational — the apply succeeded but Google queued it)
- `client_frozen` (existing)

---

## 9. Risks / open questions

1. **Edit rights ≠ read rights (the main risk).** The connected agency account may manage a listing for reads/posts but lack full edit rights on a specific field (or the listing is unverified). Mitigation: read `LocationState`/`metadata` (`isVerified`, `canModifyServiceList`) before offering an edit, classify the patch's own 403/400 into `gbp_listing_read_only`/`cannot_modify_services`, and surface it — never silently swallow.
2. **Pending-review latency.** Some edits (description especially) don't go live instantly. Mitigation: the `pending_review` status + a short-delay sync re-read; the UI says "submitted to Google, pending review" rather than "live."
3. **Hours are high-trust + suspension-sensitive.** Wrong hours damage the client and can trip GBP suspension. Mitigation: the AI never invents hours (§4 Phase 2); hours are the one field where a human must supply/confirm the actual values, the AI only normalizes/flags.
4. **Structured vs free-form services.** Structured services need a category `serviceTypes` lookup and are constrained to the listing's categories; free-form works for any listing. **Locked recommendation: free-form first (Phase 1), structured in Phase 3.**
5. **Out-of-band edits.** Someone edits the listing in the Google dashboard; our snapshot drifts. Mitigation: always read live values on page load (no cached "current"); Phase 3 adds scheduled drift detection.
6. **Category editing is adjacent and tempting** — `gbp_audit` flags category gaps too. Deliberately out of v1 (categories change ranking behavior and have their own validation); Phase 3.

**Open — ask the owner:**
- (a) **Confirm no-auto-apply for v1** (recommended, §5) — agreed in the 2026-09-03 discussion, restate here for the record.
- (b) **Free-form services first**, structured deferred (recommended, §9.4) — agreed in discussion.
- (c) Should the strategist loop (Phase 2) be a **SerMaStr action**, an **Action-Plan producer**, or both?
- (d) Test listing for the `--edit-test` verify step — the **agency's own** GBP listing (not a client's), same as the Posts PRD's guidance.

---

## 10. Success metrics

- Pilot: a client's description, services, and hours edited end-to-end through the app (draft → apply → confirmed live) with zero dashboard work.
- Strategist loop: a `gbp_audit`-flagged description/service gap goes from finding → drafted fix → approved → live in one review pass.
- Zero silent failures: every read-only-listing / pending-review / rejection is surfaced with an actionable `ErrorDetails` code, never a green state that isn't true.

---

## 11. Relationship to existing GBP surfaces

| Surface | Direction | API | This module |
|---|---|---|---|
| GBP data capture (`gbp_service`) | read | DataForSEO/Outscraper | source of some draft grounding (categories, reviews, captured hours) |
| GBP Insights (`gbp_metrics_*`) | read | Business Profile Performance v1 | sibling; same connection layer |
| GBP Posts (`gbp_posts_*`) | write | My Business v4 `localPosts` | sibling; the pattern template this PRD mirrors |
| **GBP Profile Editor (this)** | **write** | **Business Information v1 `locations.patch`** | **new — description / hours / services** |

All four share `gbp_auth` + `gbp_locations` + the connect flow. This module is the second write integration and the first to change structured, persistent profile fields — hence the stricter, no-auto-apply approval model.
