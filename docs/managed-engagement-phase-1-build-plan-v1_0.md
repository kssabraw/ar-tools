# Managed Engagement / SerMaStr — Phase 1 Build Plan (v1.0)

> **Status:** First implementation plan derived from `docs/managed-engagement-and-strategy-engine-design-v1_0.md` (the authority for *what* and *why* — this doc is *how* and *in what order*). **Nothing built yet.** Phase 1 is the foundation: the engagement spine + onboarding wizard (with voice/ICP approval gates) + unified intake + first-party connectors. It is **recommend-only** — no audits, no strategy engine, no autonomous execution, no Asana (those are Phases 2–5).

## Phase 1 scope

**In:** the `engagements` state machine; the onboarding wizard wrapping existing GBP/website/voice/ICP with **approval gates**; the **Unified Keyword Portal** + intake extensions (geography, role-routing map); the **GA4** connector (+ ingest); the **GBP Performance** connector *conditionally* (gated on the §12 Q14 OAuth decision). GSC already exists.

**Out (later phases):** the four audits + performance-baseline computation (Phase 2/3), the Strategy Engine + plan (Phase 2), the monitor/optimizer/alerting/algo-timeline (Phase 5), the executor + internal-linking + consolidated report (Phase 4), Asana sync (Phase 5). In Phase 1 the connectors only **ingest** — the baseline that *consumes* them is Phase 2.

## Provisioning needed

- **PRs 1–4:** none — pure orchestration over existing trackers/data.
- **PR 5 (GA4):** enable the **GA4 Data API** on the GCP project that owns the agency service account; add the SA email as a **Viewer** on each client's GA4 property (per-client dashboard step, exactly like the GSC pattern). Config: add `analytics.readonly` scope; reuse `settings.google_service_account_key`. Free API.
- **PR 6 (GBP Performance):** **blocked on §12 Q14** (stand up an OAuth token store vs. stay on the existing Outscraper/DataForSEO scrape). **Defer-able** — Phase 1 is complete without it.

## PR sequence

Each PR is independently shippable, has its own tests, and follows repo conventions (services/routers/models/migrations; `async_jobs` + `gsc_scheduler`; pytest service-logic units with external calls mocked; TanStack Query frontend).

### PR 1 — Unified Keyword Portal *(ship first; standalone)*
**Why first:** self-contained, no engagement dependency, immediate value, lowest risk — the cleanest first brick.
- **Backend:** `routers/keyword_portal.py` (`POST /clients/{id}/keyword-portal/add`); `models/keyword_portal.py`; a **brand bulk-add** helper (`brand_service.add_keywords`) to match the rank/maps bulk shape; a per-target **result envelope**; "run first scans now" wiring (rank auto-enqueues already; trigger Maps + Brand scans for the new keywords; Maps returns **blocked-but-added** when no scan config).
- **Frontend:** a workspace **"Add Keywords"** card → `pages/KeywordPortal.tsx` (textarea + three target checkboxes + per-target results + a cost note, since scans are paid).
- **Tests:** fan-out unit (3 services mocked) — all-targets happy path; duplicate-skip; Maps-blocked-but-added; brand bulk returns ids; scan-scoping passes only *new* ids to Brand.
- **Acceptance:** enter keywords once → added (idempotent) to the selected trackers; first scans fire; per-target results show counts + the Maps "not configured" note when applicable.
- **Provisioning:** none.

### PR 2 — Engagement spine (data model + state machine + API)
- **Migration:** `engagements` (status enum per the design lifecycle, `autonomy_level` default `assisted`, `config` jsonb, `current_plan_id` nullable, `client_id`). RLS, service-role.
- **Backend:** `services/engagement_service.py` — `create` (enforce **one active engagement per client**), `get`, `transition` (a **pure valid-transition table** + guard helpers); `routers/engagements.py` (`POST` create, `GET`, `POST` transition); `models/engagement.py`.
- **Tests:** valid/invalid transition matrix; one-active-per-client; create defaults (`onboarding`, `assisted`).
- **Acceptance:** create an engagement → starts `onboarding`; transition through the lifecycle via API; invalid transitions rejected (4xx).
- **Provisioning:** none.

### PR 3 — Onboarding wizard + voice/ICP approval gates
- **Frontend:** `pages/OnboardingWizard.tsx` — steps Business → Voice → ICP → Reference pages → **Connect data** (placeholder until PR 5) → Targets — **reusing** the existing GBP picker, `ClientForm` pieces, `BrandVoice.tsx`, `Icp.tsx`.
- **Backend gate:** `engagement_service.transition(onboarding → intake)` allowed only when **brand voice approved + ICP approved** (reuse `brand_voice.recommended_accepted` / `detected_icp.source`; add explicit "approve" endpoints/flags).
- **Acceptance:** a new client walks the wizard; **cannot leave `onboarding`** until voice + ICP are approved; website scrape + page-structure scrape still fire on save.
- **Provisioning:** none.

### PR 4 — Intake wiring + geography + role-assignee map
- **Backend/Frontend:** tie the PR 1 portal to the engagement **intake** stage ("this is for engagement X"); transition `intake → auditing` on submit; capture per-target **geography** (reuse `target_cities` + multi-city discovery) + topic/service framing.
- **Migration:** `role_assignees` (`client_id` nullable → agency default, `role`, `asana_user_gid`, `email`) + a simple capture form. *(Asana wiring is Phase 5; here we only store the map so it's ready.)*
- **Acceptance:** intake records targets + geography + routing for the engagement and advances it to `auditing`.
- **Provisioning:** none.

### PR 5 — GA4 connector + ingest
- **Migration:** `clients.ga4_property_id`, `clients.ga4_access_status`; `ga4_*` ingest tables.
- **Backend:** `services/ga4_service.py` (connect/verify via the GA4 Data API + agency SA — pure helpers + lazy import, mirroring `gsc_service`); `services/ga4_ingest.py` (periodic pull on `gsc_scheduler` — `enqueue_due` + a `ga4_ingest` job) for sessions / channel mix / landing-page traffic / **key events (conversions)**.
- **Config:** widen scopes with `analytics.readonly`; reuse the service-account key.
- **Frontend:** GA4 connect/status in the wizard's **Connect data** step (enter property id → show the SA email to grant → verify button), mirroring the GSC connect UX.
- **Tests:** pure helpers (property normalize, verify-result mapping) with the Google client mocked.
- **Acceptance:** enter a property + grant the SA → verify-access passes → ingest lands rows in `ga4_*`; **degrades to "not configured"** without it.
- **Provisioning:** enable GA4 Data API + SA Viewer per property.

### PR 6 — GBP Performance connector *(CONDITIONAL — gated on §12 Q14)*
- **Only if OAuth is approved:** a minimal OAuth token store + `services/gbp_performance_service.py` + `services/gbp_performance_ingest.py` + migration (`clients.gbp_performance_location_id`, `*_access_status`, `gbp_performance_*` tables). **Else: skip** — keep the existing Outscraper/DataForSEO profile+reviews scrape.
- **Acceptance (if built):** connect a GBP location → daily performance metrics (impressions/calls/directions/website-clicks + search-keyword breakdown) ingest into `gbp_performance_*`.
- **Provisioning:** OAuth app + token store (the one deviation from the service-account rule — only if you green-light it).

## What Phase 1 delivers

A **guided onboarding** that yields an approved client profile + connected first-party data + a unified keyword intake feeding the **engagement spine** — i.e., everything the audits (Phase 2/3) need as input. Still **recommend-only**; no autonomy.

## Recommended order

**PR 1** (portal — ships value immediately) → **PR 2** (spine) → **PR 3** (wizard) → **PR 4** (intake wiring) → **PR 5** (GA4) → **PR 6** (GBP-Performance, only once Q14 is decided).

## Decisions needed before starting

1. **Keyword-portal placement** — workspace card (recommended) vs. modal vs. top-level page *(open since the first portal plan)*.
2. **GA4 provisioning go-ahead** — OK to enable the GA4 Data API + add the SA as a property Viewer? *(blocks only PR 5)*.
3. **GBP Performance OAuth (§12 Q14)** — token store vs. stay-on-scrape *(blocks only PR 6; defer-able)*.
4. **`role_assignees` fields (§12 Q13)** — confirm the captured roles before PR 4.

*Build plan v1.0 — nothing implemented. On approval, start with PR 1.*
