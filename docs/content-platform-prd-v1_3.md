# PRD: [Product Name TBD] — Internal Content Generation Platform

**Version:** 1.4 (Draft)
**Status:** Draft — Ready for Implementation
**Last Updated:** 2026-05-01

> **v1.4 changes (2026-05-01):** Updated Goals and Out of Scope to reflect Content Quality PRD v1.0 R5 — the Brief Generator now optionally consumes per-client `client_context.icp_text` for topic-adherence downgrade. The Brief still does not inject brand voice into prompts. SIE and Research remain keyword-driven. See `/docs/content-quality-prd-v1_0.md`.
**Audience:** Internal team (no commercial release in v1)
**Modules in Scope:**
- Content Brief Generator (v1.7)
- Research & Citations Module (v1.1)
- SIE Term & Entity Module (v1.0 — production-ready)
- Content Writer Module (v1.4 → requires v1.5 update; see Section 14)
- Sources Cited Module (v1.1)
- Content Editor Module (referenced — out of scope for v1)

---

## 1. Problem Statement

Producing SEO and AEO-optimized blog content at scale for SMB clients across multiple verticals is slow, inconsistent, and expensive when done manually. A typical research-to-publish cycle requires keyword research, SERP analysis, competitor heading analysis, citation discovery, draft writing, and editorial polish — each step prone to drift, fabrication, or quality regression. Existing tools (Surfer, Frase, MarketMuse, Outranking) generate briefs or drafts but do not verify factual claims against sources, do not optimize for LLM citation surfaces (AEO), and do not produce content that reflects the specific tone, audience, and positioning of each SMB client.

The team has built a set of composable modules — Brief Generator, Research & Citations, SIE Term & Entity, Writer, and Sources Cited — that together produce a publication-ready, source-anchored, AEO-optimized blog post from a single keyword input. What's missing is the **platform layer** that:

1. Orchestrates these modules
2. Captures and persists per-client context (brand voice, ICP, website signals) so generated content reflects each client's identity
3. Provides a UI for the team to drive runs and review output
4. Persists run history for audit and re-export

This PRD specifies that platform.

---

## 2. Goals

- Provide a single internal web app where authenticated team members submit a keyword for a configured client and receive a complete, publication-ready Markdown blog post
- Capture per-client context (name, website, brand guide, ICP) once and reuse it across all runs for that client
- Inject brand guide and ICP into the **Content Writer Module** so generated content reflects each client's tone and audience. **Pass ICP into the Brief Generator** for topic-adherence downgrade only (Content Quality PRD v1.0 R5; Brief PRD v1.8). Keep SIE and Research keyword-driven and brand-agnostic.
- Scrape and analyze each client's website at setup time to extract structured signals (services, locations, existing tone) used to enrich generation
- Orchestrate the existing module pipeline (Brief → Research & Citations → SIE → Writer → Sources Cited) end-to-end with no manual handoff between stages
- Surface intermediate artifacts (brief JSON, citation pool, SIE term list, draft article) for human review at any stage of a run
- Persist every run with full input/output history — including the **snapshot of client context** used at run time — for auditability and debugging
- Support copy/paste export of the final article as Markdown for downstream publishing in any CMS
- Expose per-run cost and timing data so the team can monitor unit economics across pipeline runs
- Leverage SIE's 7-day keyword + location cache to reduce cost when generating content for the same keyword across multiple clients

### Out of Scope (v1)

- Public release, billing, pricing tiers, or customer onboarding
- Multi-user role permissions beyond simple authenticated team access
- CMS publishing integrations (WordPress, Webflow, Shopify, etc.)
- Schema markup injection (JSON-LD)
- Image generation, image selection, or alt-text
- Internal linking suggestions across the team's article archive
- **Structured parsing of brand guide / ICP into typed fields** (tone, banned words, demographics) — v1 passes raw text to the Writer; structured extraction is deferred to v2
- **Brand context injection into SIE or Research & Citations** — those modules remain keyword-driven; brand reconciliation happens in the Writer only. **As of Content Quality PRD v1.0 R5, the Brief Generator now optionally consumes `client_context` for ICP-based topic-adherence downgrade only** (it does not inject brand voice into prompts) — see Brief Generator PRD v1.8 §5 Step 8.
- Live (non-snapshot) brand context — every run snapshots client context at submission time; edits to a client do not retroactively affect past runs
- Rank tracking or post-publish citation monitoring
- Human editorial workflow / approval routing
- Content Editor Module integration (downstream of Sources Cited; deferred to v2)
- Automated keyword research / keyword discovery — the team supplies keywords manually in v1
- Multi-locale support — English / United States only (SIE `location_code` hardcoded to 2840, `language_code` to `en`)
- Mobile-optimized UI — desktop-only in v1
- Multi-page or full-site website scraping — v1 scrapes the homepage only

---

## 3. Target Users

The platform's only users in v1 are members of the internal content production team. Assumed personas:

| Persona | Role | Primary Actions |
|---|---|---|
| Content Strategist | Onboards new clients, configures brand context, selects keywords, configures intent overrides, assigns runs to clients | Create/edit clients, submit runs, review briefs |
| Content Producer | Reviews drafts, copy/edits final output, exports for publishing | Review article, export Markdown |
| Engineering / Ops | Monitors pipeline health, debugs failed runs, tracks costs | Inspect logs, view cost dashboard |

No external users. No customer-facing surfaces.

---

## 4. Success Metrics

Success in v1 is defined by pipeline reliability, output quality compliance, and team productivity gains — not commercial metrics.

| Metric | Target |
|---|---|
| End-to-end pipeline runs that complete without manual intervention | ≥90% |
| Final article passes all module-level schema validations | 100% |
| End-to-end run completes in under 5 minutes (P95) | ≥95% |
| Per-article pipeline cost stays under $1.50 | ≥95% |
| Client setup (form submit → website scrape complete) under 60s | ≥95% |
| Generated content perceptibly reflects client brand voice (qualitative team review) | ≥80% of articles approved as "on-brand" without edits |
| SIE cache hit rate (same keyword reused across clients within 7 days) | Tracked, no target in v1 |
| Team produces ≥10 publication-ready articles per day at steady state | Yes/No |
| Run history is queryable and re-runnable from UI | 100% |

The $1.50 ceiling is derived from the sum of module-level cost ceilings: Brief ($0.75) + Research & Citations ($0.50) + Writer ($0.75), with margin for SIE and Sources Cited. SIE cache hits reduce this further.

---

## 5. System Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                  Internal Web App (Lovable / React)                │
│  ┌──────────┐  ┌─────────────┐  ┌──────────┐  ┌─────────────────┐ │
│  │ Login    │  │ Client Mgmt │  │ New Run  │  │ Run Dashboard   │ │
│  │ Screen   │  │ (Setup/Edit)│  │ Form     │  │ + Article Review│ │
│  └──────────┘  └─────────────┘  └──────────┘  └─────────────────┘ │
└────────────────────────────────┬───────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│                  Orchestration API (FastAPI / Railway)             │
│  - Auth verification (Supabase JWT)                                │
│  - Client CRUD endpoints                                           │
│  - File parsing (PDF/DOCX/TXT/MD/JSON → text)                      │
│  - Website scraper (ScrapeOwl + LLM extraction)                    │
│  - Run dispatcher with client_context injection (Writer only)      │
└────────────────────────────────┬───────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│                       Supabase (Postgres + Auth)                   │
│  - users    - clients    - runs    - module_outputs                │
│  - client_context_snapshots (per-run frozen client context)        │
└────────────────────────────────┬───────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│                       Pipeline Modules (Railway)                   │
│                                                                    │
│  [Keyword + outlier_mode + force_refresh + intent_override]        │
│        │                                                           │
│        ├──► Brief Generator (keyword only) ──┐                     │
│        │                                     │                     │
│        └──► SIE Term & Entity ───────────────┤                     │
│             (keyword + outlier_mode +        │                     │
│              force_refresh; brand-agnostic;  │                     │
│              7-day cache by keyword+location)│                     │
│                                              ▼                     │
│                            Research & Citations (Brief output)     │
│                                              │                     │
│                                              ▼                     │
│        Content Writer ◄── Brief + Research + SIE + client_context  │
│        (reconciles SIE Required terms with client banned terms)    │
│                                              │                     │
│                                              ▼                     │
│                            Sources Cited (Writer + Research)       │
│                                              │                     │
│                                              ▼                     │
│                                  Final Article (JSON + Markdown)   │
└────────────────────────────────────────────────────────────────────┘
```

**Notes on parallelism:**
- Brief Generator and SIE Term & Entity Module run in **parallel** (both consume keyword-only inputs)
- Research & Citations runs **after** Brief Generator
- Writer runs **after** Brief, Research & Citations, and SIE all complete (requires all three plus client context)
- Sources Cited runs **after** Writer

**Client context injection point:**
- **Writer Module only** — receives `brand_guide_text`, `icp_text`, and `website_analysis` to apply tone, voice, audience-aware framing, and client-specific positioning during section writing. Also performs reconciliation between SIE-Required terms and client banned terms (see Section 8).

**Why SIE does not consume client context:**
- SIE's design contract grounds all entity recommendations in Google NLP API output from scraped SERP data; the LLM is permitted to categorize, deduplicate, and filter only — never invent or shape based on external context. Injecting brand voice would violate this guardrail.
- SIE caches results for 7 days by keyword + location code. Adding client context to SIE inputs would either invalidate the cache or require per-client cache keys, defeating the cache benefit.
- Brand reconciliation is a write-time concern — SIE produces SERP-grounded term lists, and the Writer chooses how to apply them within brand constraints.

**Brief Generator and Research & Citations** also do not consume client context — Brief is keyword-driven SERP research, and Research surfaces objectively authoritative sources independent of brand alignment. Sources Cited is purely a formatting module post-Writer.

---

## 6. User Journey

### 6.1 First-time team member journey

| Step | Actor | Action |
|---|---|---|
| 1 | Team member | Receives invitation email, sets password, logs in |
| 2 | Team member | Lands on Run Dashboard (empty state on first login) |
| 3 | Team member | Clicks "Manage Clients" to set up the first client |

### 6.2 Client onboarding journey

| Step | Actor | Action |
|---|---|---|
| 1 | Strategist | Clicks "New Client" |
| 2 | Strategist | Enters client name (required) and website URL (required) |
| 3 | Strategist | Provides brand guide via either: (a) free-form text area, or (b) file upload (PDF/DOCX/TXT/MD/JSON) |
| 4 | Strategist | Provides ICP via either: (a) free-form text area, or (b) file upload (PDF/DOCX/TXT/MD/JSON) |
| 5 | Strategist | Clicks "Save Client" |
| 6 | Platform | Validates inputs; parses any uploaded files into raw text; persists to Supabase |
| 7 | Platform | Asynchronously scrapes the website homepage and extracts services / locations / tone signals via LLM |
| 8 | Platform | Stores website analysis on the client record; marks client as "ready for runs" |
| 9 | Strategist | Sees the new client in the client list with website analysis preview; can edit anytime |

### 6.3 Article generation journey

| Step | Actor | Action |
|---|---|---|
| 1 | Strategist | Logs in, clicks "New Run" |
| 2 | Strategist | Selects client from dropdown, enters keyword, optionally configures advanced options (intent override, SIE outlier mode, SIE force-refresh) |
| 3 | Platform | Validates input, **snapshots client context** into `client_context_snapshots`, creates `runs` row, dispatches Brief + SIE in parallel (SIE receives keyword + outlier_mode + force_refresh — no client context) |
| 4 | Platform | When Brief completes, dispatches Research & Citations |
| 5 | Strategist | Optionally inspects Brief JSON in UI while Research & Citations and SIE run |
| 6 | Platform | When Brief, Research & Citations, and SIE all complete, dispatches Writer with all three module outputs + client context snapshot |
| 7 | Platform | When Writer completes, dispatches Sources Cited |
| 8 | Producer | Receives notification (in-app) that run is complete |
| 9 | Producer | Opens article review screen — sees rendered Markdown preview, citation list, client context snapshot used, brand-conflict log (any SIE-Required terms skipped due to client banned-word match), and metadata (word count, term coverage, cost, SIE cache hit/miss) |
| 10 | Producer | Copies Markdown to clipboard via "Copy" button |
| 11 | Producer | Pastes into target CMS for publishing (out-of-band) |
| 12 | Platform | Run remains queryable in dashboard for re-export, debugging, or audit |

**Failure-path branches** are documented in Section 12.

---

## 7. Functional Requirements

### 7.1 Authentication & Access Control

| Requirement | Detail |
|---|---|
| Login screen | Email + password form on the root domain; "Forgot password" link supported |
| Authentication method | Supabase Auth (email + password); magic link supported as alternative |
| Authorized users | Only team members on a Supabase-managed allowlist |
| Roles | Two roles: `admin` and `team_member` (see permissions table below) |
| Session length | 30 days, renewable on activity |
| Logout | Visible in top-nav user menu |
| Multi-factor authentication | Not required in v1 |
| Unauthenticated access | Redirected to login screen for all routes except `/login` and `/forgot-password` |

#### Role Permissions

| Action | `admin` | `team_member` |
|---|---|---|
| Submit new runs | ✅ | ✅ |
| View all runs | ✅ | ✅ |
| View run detail & artifacts | ✅ | ✅ |
| Export / copy article output | ✅ | ✅ |
| Re-run failed or completed runs | ✅ | ✅ |
| Create new clients | ✅ | ❌ |
| Edit existing clients | ✅ | ❌ |
| Archive clients | ✅ | ❌ |
| View client list | ✅ | ✅ |
| Invite new team members | ✅ | ❌ |
| Remove team members | ✅ | ❌ |
| Change team member roles | ✅ | ❌ |
| View cost dashboard | ✅ | ❌ |
| View failure / error logs | ✅ | ❌ |
| Trigger website re-analysis | ✅ | ❌ |

At least one admin must exist at all times. The platform must prevent the last admin from demoting themselves to `team_member`.

### 7.2 Client Management

The platform stores a **client** entity that captures everything the pipeline needs to produce on-brand content.

#### 7.2.1 Client data model

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | UUID | Yes | Primary key |
| `name` | string | Yes | Display name; unique per platform |
| `website_url` | string | Yes | Must be a valid URL; HTTPS preferred |
| `website_analysis` | JSON | No (populated async) | Output of website scrape — services, locations, and contact info only. Tone and brand voice come exclusively from `brand_guide_text`. |
| `website_analysis_status` | enum | Yes | `pending`, `complete`, `failed` |
| `website_analysis_error` | string | No | Populated if scrape fails; human-readable |
| `brand_guide_source_type` | enum | Yes | `text`, `file` |
| `brand_guide_text` | text | Yes | Content of brand guide — preserved in original format (JSON or Markdown preferred; extracted text for PDF/DOCX uploads). Max 150,000 characters. |
| `brand_guide_file_path` | string | No | Supabase Storage path (only when `source_type = file`) |
| `brand_guide_original_filename` | string | No | Original filename (only when `source_type = file`) |
| `icp_source_type` | enum | Yes | `text`, `file` |
| `icp_text` | text | Yes | Content of ICP document — preserved in original format (JSON or Markdown preferred; extracted text for PDF/DOCX uploads). Max 150,000 characters. |
| `icp_file_path` | string | No | Supabase Storage path (only when `source_type = file`) |
| `icp_original_filename` | string | No | Original filename (only when `source_type = file`) |
| `created_at` | timestamp | Yes | |
| `updated_at` | timestamp | Yes | Updated on every edit |
| `archived` | boolean | Yes | Default false; archived clients hidden from new-run dropdown but preserved for audit |

#### 7.2.2 Client setup form

| Requirement | Detail |
|---|---|
| Name field | Free text, ≤100 chars, required, unique |
| Website field | Valid URL, required; trailing slash normalized |
| Brand guide input | Tabbed UI — "Paste Text" (textarea) or "Upload File" |
| ICP input | Tabbed UI — "Paste Text" (textarea) or "Upload File" |
| Supported file formats | PDF, DOCX, TXT, MD, JSON |
| Max file size per upload | 10 MB |
| Max raw text size after parsing | 150,000 characters per field (truncated with warning if exceeded) |
| Save action | Synchronously persists client + parsed text; asynchronously triggers website scrape |
| Edit | All fields editable post-creation; updates do not retroactively affect past runs (snapshot rule) |
| Archive | Soft delete; archived clients hidden from new-run flow but visible in client management with filter |
| Hard delete | Not permitted in v1 (preserves audit trail of past runs) |

#### 7.2.3 File parsing rules

| Format | Parser | Notes |
|---|---|---|
| PDF | `pypdf` (or equivalent) | Extract text from all pages; reject if extracted text <50 chars (likely scanned image) |
| DOCX | `python-docx` | Extract text including paragraphs and table contents |
| TXT | Native read | UTF-8; reject if not decodable |
| MD | Native read | Treated as plain text; Markdown formatting preserved |
| JSON | `json.loads` then `json.dumps` with indent=2 | Validates JSON structure; pretty-prints for readability when injected into prompts |

If parsing fails, the client save fails with a user-readable error and no partial data is persisted.

#### 7.2.4 Website scraping & analysis

The website scrape serves a specific, narrow purpose: extract factual reference data (services, locations, contact information) that can be used to inform generated content. **It does not extract brand tone or positioning.** All tone and voice signals come exclusively from `brand_guide_text` and `icp_text`.

| Requirement | Detail |
|---|---|
| Trigger | Async job dispatched on client save (and on website URL edit) |
| Scope | Homepage only in v1 (no crawl, no sub-pages) |
| Scraper | ScrapeOwl (already in team's stack) |
| Extraction | LLM call (single shot) prompted to extract: list of services offered, list of service locations / service areas, and contact information (phone, address, email, business hours) |
| Output schema | Structured JSON stored in `website_analysis` field — see schema below |
| Timeout | 60 seconds total (scrape + extract); on timeout, mark `failed` and store error |
| Failure handling | Client remains usable for runs; runs proceed without website analysis (flag `website_analysis_unavailable: true` in client context snapshot). Brand guide and ICP still apply normally. |
| Re-trigger | "Re-analyze website" button on client edit screen |

**website_analysis output schema:**

```json
{
  "services": ["string"],
  "locations": ["string"],
  "contact_info": {
    "phone": "string or null",
    "email": "string or null",
    "address": "string or null",
    "hours": "string or null"
  }
}
```

### 7.3 Pipeline Execution

| Requirement | Detail |
|---|---|
| New run form fields (basic) | `keyword` (required, ≤150 chars), `client_id` (required, dropdown) |
| New run form fields (advanced, collapsed by default) | `intent_override` (optional dropdown of 8 intent types from Brief PRD), `sie_outlier_mode` (`safe` default / `aggressive`), `sie_force_refresh` (boolean default false — bypasses SIE 7-day cache) |
| Locale defaults (hardcoded) | `location_code: 2840` (US), `language_code: "en"`, `device: "desktop"`, SIE `depth: 20` |
| Client context snapshot | At run dispatch, the orchestrator copies the client's current `brand_guide_text`, `icp_text`, and `website_analysis` into a `client_context_snapshots` row tied to the `run_id` |
| Run state machine | `queued` → `brief_running` (parallel with `sie_running`) → `research_running` → `writer_running` → `sources_cited_running` → `complete` / `failed` |
| Concurrency | Up to 5 runs in flight at once |
| Cancellation | User can cancel a run from the dashboard at any state; cancelled runs do not consume further module budget |
| Re-run | User can re-run any completed or failed run with same inputs from the dashboard; re-runs create a **new** snapshot of current client context (not the old snapshot). Re-run honors current SIE cache state unless force_refresh is set. |

### 7.4 Run Dashboard

| Requirement | Detail |
|---|---|
| List view | All runs, sortable by date / state / client, filterable by client and state |
| Per-row info | Keyword, client, state, duration, cost-to-date, SIE cache hit indicator |
| Run detail page | Surfaces all intermediate artifacts: client context snapshot, Brief JSON, citation pool, SIE output, Writer output (including brand-conflict log), final article; per-stage timing and cost; module version numbers used |
| Search | Free-text search across keywords and client names |
| Pagination | 50 runs per page |

### 7.5 Article Review & Export

| Requirement | Detail |
|---|---|
| Markdown preview | Rendered view of final article with Sources Cited section formatted |
| Raw Markdown view | Toggle to show raw Markdown source |
| Copy to clipboard | One-click button copies raw Markdown including Sources Cited |
| Copy as HTML | One-click button copies rendered HTML (for paste into CMSes that prefer HTML over MD) |
| Download | Download button saves `{keyword-slug}.md` file |
| Article metadata panel | Word count, FAQ count, term coverage stats, citation count, total cost, total runtime, client context snapshot summary, brand-conflict log (terms skipped) |

### 7.6 Observability

| Requirement | Detail |
|---|---|
| Cost dashboard | Aggregate cost per day / per client / per module |
| SIE cache dashboard | Cache hit rate over time; cost savings attributable to cache hits |
| Failure log | List of failed runs with module that failed, error message, retry option |
| Module version tracking | Each run records which module versions executed |
| Logs | Per-run structured logs viewable in detail page (mirror what Railway emits) |
| File parsing logs | File upload history per client (filename, size, parse result, timestamp) |
| Website scrape logs | Per-client scrape history with success/failure status |

---

## 8. Module Orchestration

The platform orchestrates module calls and passes outputs forward, with **client context injected only into the Writer**.

| Rule | Detail |
|---|---|
| Module endpoints | Each module exposes a single FastAPI endpoint on Railway (e.g. `/brief`, `/research`, `/sie`, `/write`, `/sources-cited`) |
| Inter-module data exchange | JSON payloads matching each module's documented input schema; orchestrator does no transformation |
| **Client context payload** | Passed to **Writer endpoint only** as a new top-level `client_context` field containing `brand_guide_text`, `icp_text`, and `website_analysis` from the snapshot |
| **SIE input payload** | `keyword`, `location_code: 2840`, `language_code: "en"`, `device: "desktop"`, `depth: 20`, `outlier_mode` (from form), `force_refresh` (from form) — no client context |
| Failure isolation | If any module fails, downstream modules do not execute; run state goes to `failed` with the failing stage recorded |
| Retry policy | One automatic retry per module on transient failure (HTTP 5xx, timeout); no retry on validation failures |
| Idempotency | Each run has a unique `run_id`; modules accept `run_id` and de-dupe duplicate calls |
| Cross-validation | Per Writer Module v1.4, the orchestrator is responsible for ensuring the `keyword` field matches across Brief, Research, and SIE outputs before invoking Writer |
| SIE cache awareness | Orchestrator records whether SIE returned a cached result vs. fresh result; surfaced in run metadata |

### Brand vs. SIE reconciliation (Writer responsibility)

When SIE produces its `terms.required[]` list and a client's `brand_guide_text` indicates banned or avoid terms, the **Writer is responsible for resolving the conflict** at write time. The platform does not pre-process or reconcile term lists before invoking the Writer.

The Writer Module v1.5 must implement the following behavior:

| Scenario | Writer Behavior |
|---|---|
| SIE-Required term has no conflict with brand guide | Use term per SIE usage zone targets |
| SIE-Required term explicitly banned in brand guide | Skip term during section writing; record in Writer output as `excluded_due_to_brand_conflict` with the specific term and the brand-guide reasoning |
| SIE-Required term ambiguously discouraged in brand guide | Use term but at minimum-zone usage rather than target-zone usage; record in Writer output as `reduced_due_to_brand_preference` |
| SIE-Avoid term conflicts with brand guide preferred terminology | SIE-Avoid takes precedence (LLM hallucination guardrail trumps brand preference); record as `brand_preference_overridden_by_sie` |

Brand compliance generally trumps SERP coverage for explicitly banned terms, but SIE's authority guardrails trump brand preference for explicitly avoided terms. The Writer logs every reconciliation decision in its output for downstream review.

### Required module updates

The introduction of client context creates a breaking change for the Writer Module:

| Module | Required Change | Target Version |
|---|---|---|
| Content Writer | (1) Add `client_context` as a new input (in addition to Brief, Research, SIE inputs); (2) inject `brand_guide_text`, `icp_text`, and `website_analysis` into section-writing prompts and FAQ-writing prompt; (3) implement brand vs. SIE reconciliation logic above; (4) emit `brand_conflict_log` array in output | v1.5 |

This change must ship before the platform can run end-to-end. SIE, Brief, Research, and Sources Cited modules require no changes.

---

## 9. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Performance | End-to-end run completes in under 5 minutes (P95); UI page loads under 1s; client setup form submit under 2s (excluding async scrape) |
| Reliability | 99% uptime during business hours (no formal SLA needed for internal tool) |
| Security | All data encrypted at rest (Supabase default); HTTPS enforced; no public API surface; uploaded files stored in private Supabase Storage bucket with signed-URL access only |
| Privacy | No PII collection — inputs are keywords and client business data; no end-customer data flows through the system. Client brand guides may contain sensitive positioning info — treat as confidential. |
| Observability | Structured JSON logs from Railway; Supabase query logs; per-run cost trace |
| Scalability | Designed for 50 runs/day at peak (5x current volume estimate) and up to 100 active clients |
| Backups | Supabase point-in-time recovery enabled (default tier sufficient) |
| File handling | Uploaded files retained indefinitely in Supabase Storage; raw extracted text retained on the client record |

---

## 10. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Frontend | Lovable (React + Vite) | Existing team workflow; fast iteration |
| Backend / Orchestrator | FastAPI on Railway | Same stack as existing modules |
| Module hosting | Railway (one service per module, or shared service with multiple endpoints) | Existing infrastructure |
| Database | Supabase (Postgres) | Auth + storage + structured data in one provider |
| File storage | Supabase Storage (private bucket) | Native integration; signed URLs for retrieval |
| Auth | Supabase Auth | Native integration |
| File parsing | `pypdf`, `python-docx` (Python libs in orchestrator service) | No external service dependency |
| Website scraping | ScrapeOwl | Already used in team's stack |
| Website extraction | OpenAI or Anthropic LLM (single-shot) | Aligns with existing module choices |
| Source control | GitHub | Existing convention |

---

## 11. Performance & Cost Targets

### Pipeline-level targets

| Stage | Target (sec) | Max (sec) |
|---|---|---|
| Brief Generator | 60 | 120 |
| SIE Term & Entity (cache miss) | 60 | 120 |
| SIE Term & Entity (cache hit) | <5 | 10 |
| Research & Citations | 60 | 120 |
| Content Writer | 60 | 90 |
| Sources Cited | 10 | 15 |
| **End-to-end (with parallelism, SIE cache miss)** | **180** | **300** |
| **End-to-end (with parallelism, SIE cache hit)** | **150** | **270** |

### Client setup targets

| Stage | Target (sec) | Max (sec) |
|---|---|---|
| Form submit + file parse | 2 | 10 |
| Website scrape + LLM extraction (async) | 30 | 60 |

### Per-article cost ceiling

| Module | Estimated (cache miss) | Estimated (cache hit) | Ceiling |
|---|---|---|---|
| Brief Generator | $0.19–$0.53 | (no cache) | $0.75 |
| SIE Term & Entity | $0.20–$0.40 (estimate; precise figure TBD) | $0.00 | $0.50 |
| Research & Citations | $0.16–$0.28 | (no cache) | $0.50 |
| Content Writer | $0.30–$0.45 (slight increase from v1.4 due to client_context tokens) | (no cache) | $0.75 |
| Sources Cited | <$0.05 | (no cache) | $0.05 |
| **Total per article (SIE cache miss)** | **$0.85–$1.71** | — | **$2.55** |
| **Total per article (SIE cache hit)** | — | **$0.65–$1.31** | — |

**Cache hit benefit:** When the same keyword is run for multiple clients within a 7-day window, SIE returns cached results, saving ~$0.20–$0.40 and ~60s per run after the first. The cache is keyed on keyword + location, so it works across all clients sharing that keyword.

### Per-client setup cost (one-time per client)

| Component | Estimated |
|---|---|
| ScrapeOwl request | <$0.01 |
| LLM website extraction | $0.02–$0.05 |
| File parsing (compute only) | $0 |
| **Total per client setup** | **$0.03–$0.06** |

---

## 12. Failure Mode Handling

### Pipeline failures

| Scenario | Platform Behavior |
|---|---|
| Module returns HTTP 5xx | One automatic retry; on second failure, mark run as `failed` with stage recorded |
| Module returns schema-invalid output | Mark run as `failed` immediately (no retry) |
| Module times out | Mark run as `failed` with `timeout` reason |
| User cancels mid-run | Send cancellation signal to current module; do not invoke downstream modules |
| Cross-validation fails (keyword mismatch) | Mark run as `failed` with `cross_validation_error` |
| SIE returns degraded-confidence output (<5 content-eligible pages) | **Continue** — SIE never aborts silently per its PRD; surface the warning prominently in run metadata and article review |
| SIE force_refresh requested but cache write fails | Continue with fresh result; flag cache write failure in logs (does not block run) |
| Writer returns empty `brand_conflict_log` despite client banned terms | Run completes normally; flag for engineering review (likely Writer prompt issue, not a hard failure) |
| Supabase write fails | Retry 3x with exponential backoff; on final failure, log and alert |
| Authentication expired mid-run | Run continues server-side; user is prompted to re-auth on next page load |
| All modules pass but final Markdown is empty | Mark as `failed` with `empty_output_error` |

### Client setup failures

| Scenario | Platform Behavior |
|---|---|
| File upload exceeds 10 MB | Reject at upload time with user-readable error |
| Unsupported file format | Reject with allowlist message |
| File parsing fails (corrupt PDF, undecodable text) | Reject save with format-specific error; no partial save |
| PDF contains <50 chars after extraction | Reject as likely scanned-image PDF; suggest text-paste alternative |
| Parsed text exceeds 150,000 chars | Truncate with warning; allow save |
| Website URL invalid | Reject at form submission |
| Website scrape times out (>60s) | Mark `website_analysis_status: failed`; client remains usable; runs proceed with `website_analysis_unavailable: true` |
| Website blocks scraping (403, robots.txt) | Same as timeout — mark failed, allow runs without analysis |
| LLM extraction returns malformed JSON | One retry with stricter prompt; on second failure, mark failed |
| Duplicate client name on save | Reject with "Client name already exists" |

---

## 13. Business Rules Summary

| Rule | Value |
|---|---|
| Locale | English / United States only |
| SIE `location_code` | Hardcoded to 2840 (US) |
| SIE `language_code` | Hardcoded to `en` |
| SIE `device` | Hardcoded to `desktop` |
| SIE `depth` | Hardcoded to 20 |
| SIE `outlier_mode` | User-configurable per run; default `safe` |
| SIE `force_refresh` | User-configurable per run; default `false` |
| SIE cache TTL | 7 days (per SIE PRD) |
| SIE minimum pages | 5 (per SIE PRD); fewer pages → degraded-confidence warning, run continues |
| Auth method | Supabase Auth (email + password or magic link) |
| Authorized users | Internal team allowlist only |
| Roles | `admin` (full access including user management, client management, cost dashboard) and `team_member` (run submission, article review, export) |
| Minimum admins | At least one admin must exist at all times |
| Max client name length | 100 characters; unique |
| Client website | Required; valid URL |
| Brand guide input methods | Text paste OR file upload (PDF, DOCX, TXT, MD, JSON); JSON and Markdown are the preferred formats |
| ICP input methods | Text paste OR file upload (PDF, DOCX, TXT, MD, JSON); JSON and Markdown are the preferred formats |
| Brand guide / ICP format preservation | JSON and Markdown files stored in original format; PDF/DOCX converted to extracted text |
| Max upload file size | 10 MB |
| Max parsed text size | 150,000 characters per field |
| Website scrape purpose | Contact info and services extraction only — no tone or positioning extraction. Brand tone comes exclusively from brand_guide_text and icp_text. |
| Website scrape scope | Homepage only |
| Client edits affect past runs | No (snapshot rule) |
| Client deletion | Soft delete only (archive); admin-only action |
| Max keyword length | 150 characters (matches Brief Generator) |
| Max concurrent runs | 5 |
| Max active clients | 100 (soft limit) |
| Run history retention | Indefinite |
| Cancellation | Allowed at any pipeline stage |
| Re-run | Allowed; uses **current** client context (not original snapshot) |
| Default intent classification | Inherited from Brief Generator |
| Intent override | Optional dropdown of 8 intent types at submission |
| Client tagging | Required per run |
| Brand context injection | Writer only — Brief, Research, SIE, and Sources Cited are brand-agnostic |
| Brand vs. SIE conflict resolution | **Brand always wins.** Brand banned > SIE-Required (term excluded). Brand preferred > SIE-Avoid (term used despite SIE avoidance recommendation). All conflicts logged in `brand_conflict_log`. |
| Run completion notifications | In-app polling |
| CMS publishing | Manual copy/paste; no API integration in v1 |
| Cost ceiling per article | $2.55 (cache miss) / $1.31 (cache hit) |
| Cost ceiling per client setup | $0.10 |
| End-to-end latency ceiling | 5 minutes (P95) |

---

## 14. What This PRD Does Not Cover

To be addressed in dependent module PRDs or in the engineering implementation spec:

- **Content Writer Module v1.5** — change specification written (see `writer-module-v1_5-change-spec.md`); must be merged into master Writer PRD before engineering kickoff
- **Content Editor Module integration** — referenced as downstream of Sources Cited but explicitly out of scope for v1 MVP
- **Authentication and API key management for upstream services** (DataForSEO, OpenAI, Anthropic, Google NLP, ScrapeOwl) — handled in module specs; secret rotation policy needs platform-level definition
- **Specific Lovable component architecture and routing**
- **Specific Supabase schema** for `users`, `clients`, `runs`, `module_outputs`, `client_context_snapshots`, `file_uploads` — to be defined in implementation spec; must include `role` column on `users` table supporting `admin` and `team_member` values
- **Specific Supabase Storage bucket configuration** (signed URL TTL, ACLs)
- **File parsing service architecture** — single shared service vs. inline in orchestrator
- **Website scrape worker architecture** — sync vs. async queue (recommend Supabase pg_cron or simple task table)
- **Concurrency control implementation** (queue vs. semaphore vs. database lock)
- **Run completion notification** — resolved as in-app polling; implementation detail (polling interval, endpoint) left to engineering
- **Cost-tracking implementation** — distillation LLM cost and reconciliation LLM cost tracked separately from main Writer cost; attribution mechanism left to engineering
- **LLM prompt for website extraction** — must target services, locations, and contact info only (phone, address, email, hours); no tone or positioning extraction
- **SIE cache visibility surface** — how cache hit/miss data is plumbed from the SIE module into the platform's run metadata
- **Specific UI mockups, copy, and design system**
- **Disaster recovery / data migration procedures**
- **Rate limiting between team members** (likely unnecessary at internal volumes)

---

## 15. Open Questions / Assumptions to Validate

All major assumptions have been resolved through team review. The following minor items remain open:

| # | Question | Notes |
|---|---|---|
| 1 | Product name | Still TBD; cosmetic — does not block engineering |
| 2 | 30-item cap on `banned_terms` in brand voice card sufficient for SMB clients? | Likely yes; revisit if field breaches occur in practice |

---

## 16. Version History

| Version | Date | Notes |
|---|---|---|
| 1.0 | 2026-04-30 | Initial draft. Establishes platform-level scope tying together Brief Generator (v1.7), Research & Citations (v1.1), SIE Term & Entity (referenced), Content Writer (v1.4), and Sources Cited (v1.1) modules. MVP scope: pipeline + manual export. Internal use only — no commercial features. |
| 1.1 | 2026-04-30 | Added explicit login screen requirement; expanded Section 7.2 Client Management with full data model, setup form spec, file parsing rules, and website scraping spec. Brand guide and ICP flow into Writer (and tentatively SIE) as raw text via `client_context` payload. Added `client_context_snapshots` for run-time freezing of client context. Added file parsing infrastructure (PDF/DOCX/TXT/MD/JSON) and website scraper (ScrapeOwl + LLM extraction). |
| 1.3 | 2026-04-30 | Resolved all open questions through team review. Added two-role RBAC (`admin` / `team_member`) with full permissions table to Section 7.1; admin-only actions include client management, user management, and cost dashboard. Increased character cap for brand guide and ICP fields from 100,000 to 150,000. Updated website scraping purpose — scrape now extracts services, locations, and contact info only (phone, address, email, hours); tone and brand voice removed from website analysis schema as these come exclusively from `brand_guide_text` and `icp_text`. Clarified that JSON and Markdown are the preferred input formats for brand guides and ICPs; format is preserved on storage (not flattened to plain text). Reversed brand vs. SIE precedence rule — **brand always wins**: brand-banned > SIE-Required and brand-preferred > SIE-Avoid (previously SIE-Avoid overrode brand preference). Updated website_analysis output schema in Section 7.2.4 (removed `tone` and `positioning` fields, added `contact_info` object). Resolved notification mechanism as in-app polling. Resolved cost tracking as separate line items per LLM call type. Reduced open questions from 17 to 2. Status changed to "Ready for Implementation." | **Removed `client_context` injection into SIE** — SIE remains keyword-driven to preserve its 7-day keyword+location cache and respect its hallucination guardrails (LLM may only categorize/dedupe/filter SERP-grounded data, never invent). Brand reconciliation moved to Writer responsibility (v1.5). Added Writer reconciliation rules: banned terms > SIE-Required; SIE-Avoid > brand preference. Added SIE-specific run form fields (`outlier_mode`, `force_refresh`) and hardcoded locale parameters. Added SIE cache hit/miss tracking, cache-aware cost model, and observability surface. Added SIE degraded-confidence handling (continues on <5 pages with warning). Removed SIE module update from blocking dependencies; only Writer v1.5 remains blocking. SIE module status changed to "production-ready." |
