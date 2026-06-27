# Brand Strength (AI Visibility) Module — Integration & Implementation Plan (v1.0)

**Authored:** 2026-06-26 · **Status:** Path B — **Phases 0–5 built** (notifications deferred) · **New suite module — "AI Visibility"**

> **Build status (2026-06-27).** Phases 0–4 + the Phase-2 follow-up + Phase-5 reporting are implemented on branch `claude/brand-strength-ai-ar-tools-i4ziih` (PR #149): data model (live), six-engine scan engine, full REST API, shared-scheduler recurring scans, the "AI Visibility" frontend, invisibility diagnosis + keyword suggestions, and the visibility report → Google Doc. **Deferred:** the in-app/email **notifications** half of Phase 5, pending the suite notifications-service + channel decision (§6 item 1). v1 UI follow-ups: competitor-result visualization in the matrix, history CSV export. Models: `chatgpt`=gpt-5.4 (web search), classifier=gpt-5.4-mini, diagnose/suggest=gpt-5.4, report narrative=claude-sonnet-4-6.

> **Decisions resolved (2026-06-27)** — see §6 for the original open items.
> 1. **Engines:** ship **all six** in v1 (requires `PERPLEXITY_API_KEY` + `GEMINI_API_KEY` to be provisioned before Phase 1 live-testing).
> 2. **Models** *(updated 2026-06-27)* — use the **latest OpenAI models** for the OpenAI touchpoints: the `chatgpt` engine → `gpt-5.4` (flagship, with web search), and the **mention classifier** → `gpt-5.4-mini` (cost-efficient `mini` tier, since it runs once per keyword×engine + once per competitor). This **supersedes** the earlier "auxiliary calls → suite-default Claude" choice — the classifier reverts to OpenAI function-calling. The other engines measure their own surface and keep their provider's model: `claude` → `claude-sonnet-4-6` (suite default), `gemini` → `gemini-2.0-flash`, `perplexity` → `sonar`. All are config-tunable in `config.py`.
> 3. **Placement/name:** its **own** client-workspace card + dashboard tile, labeled **"AI Visibility"** (internal code/table prefix: `brand_`).
> 4. **Notifications:** **deferred** (the schema decision was skipped). Phase 0 does **not** create the notification tables; revisit at Phase 5.
> 5. **Schema home (refinement):** tables go in the **`public` schema with a `brand_` prefix**, *not* a dedicated `brand` schema. This matches the Local SEO port (`local_seo_pages`) and reuses the suite's public-scoped service-role client unchanged — the `fanout` schema only exists because fanout was vendored with its own schema-scoped client. (Supersedes the "`brand` schema" wording below.)

> Read alongside **`docs/suite-architecture-and-roadmap-v1_0.md`** (decision log + shared infrastructure) and the source app at **`kssabraw/brand-strength-ai`** (cloned locally during planning). This document records the agreed scope and phasing for folding the standalone **brand-strength-ai** app into AR Tools as an in-suite module, following the same template as `local-seo-module-integration-plan-v1_0.md`.

---

## 1. Product summary

A **per-client AI-search visibility tracker** on each client's workspace. The team tracks a set of keywords for a client; a **scan** asks each selected AI answer engine that keyword's question and detects whether the client's brand appears in the answer — recording mention found/type, sentiment, confidence, the supporting citations, and the raw response. Results accrue as **mention history** so the team can chart visibility trends over time, compare against tracked competitors, diagnose *why* a brand is invisible for a keyword, and produce a client-facing visibility report.

Conceptually this is a **sibling to the rank trackers** (#4 Organic, #5 Maps): same "track keywords for a client and watch position over time" shape, but the surface is **LLM answer engines** rather than Google's organic SERP or local pack.

**Six scan engines** (the `ai_engine` taxonomy, ported verbatim):
- `chatgpt` (OpenAI Responses API, web search) · `claude` (Anthropic) · `gemini` (Google) · `perplexity` (`sonar`) — direct LLM calls.
- `google_ai_overview` · `google_ai_mode` — Google's AI answers, pulled via **DataForSEO** (already a suite dependency).

No billing, no credits, no customer signup, no per-tenant RLS — this is internal agency tooling anchored on `clients`, exactly like every other suite module.

---

## 2. Source app architecture (what we're porting *from*)

`brand-strength-ai` is a **Lovable-generated** app and is architecturally **unlike** the suite:

| Aspect | brand-strength-ai (source) | AR Tools (target) |
|---|---|---|
| Backend runtime | **11 Deno Supabase Edge Functions** (TypeScript) | Python 3.11 / FastAPI |
| Frontend ↔ backend | React talks **directly to Supabase** (RLS-enforced) | Thin React → FastAPI (service-role key) |
| Tenancy | Multi-tenant by `user_id` + RLS, **credits + Stripe billing** | Internal, anchored on `clients`, no billing |
| Auth | Own `profiles` / `user_roles` / signup / password reset | Suite JWT (`require_auth` / `require_admin`) |
| Scheduling | `execute-scheduled-scans` edge function (cron) | In-process asyncio scheduler (`gsc_scheduler.py`) + `async_jobs` |
| Supabase project | `chpcxrpbylsvclwfbelm` (separate) | `AR-Internal-Tools` (`wvcthtmmcmhkybcesirb`) |
| Reports | HTML report from an edge function | Google Doc in client's Drive folder (Apps Script webhook) |

Because the backend is **Deno edge functions, not Python**, this is **not** a "mount it like fanout" consolidation (fanout was already FastAPI). The correct precedent is the **Local SEO / nlp-api port**: lift the *logic*, re-implement it in a suite Python service, cut billing/auth, re-anchor to `clients`, and rebuild the UI in the suite's style. Hence **Path B (full port)**.

### Source edge functions (logic to port), by line count
| Function | LOC | Disposition |
|---|---|---|
| `run-scan` | 1461 | **Port** → the scan engine (six executors + GPT-4o-mini mention classifier + regex fallback + citation extraction). The heart of the module. |
| `fetch-keyword-metrics` | 638 | **Mostly reuse** — it's DataForSEO search-volume/CPC. The suite already has `services/keyword_market.py` (DataForSEO + cross-client cache); reuse it instead of porting. |
| `generate-visibility-report` | 620 | **Port + redirect** — re-implement report data assembly; render to a Google Doc via `services/google_docs.py` (the Maps-report precedent), not standalone HTML. |
| `diagnose-invisibility` | 481 | **Port** → "why is the brand invisible for this keyword" LLM diagnosis (multi-provider). |
| `execute-scheduled-scans` | 332 | **Replace** with the shared asyncio scheduler + an `async_jobs` job type. |
| `process-scan-alerts` | 272 | **Port, gated** — feeds the notifications layer (see §4, Phase 5). |
| `suggest-keywords` | 265 | **Port** → keyword suggestions (LLM). |
| `send-notification-email` | 264 | **Defer / gate** — email delivery (Resend) pending the notifications-channel decision (CLAUDE.md "ask before" #6). |
| `google-places-proxy` | 225 | **Port or reuse** — brand/place resolution. The suite already resolves GBP via `services/gbp_service.py`; prefer reusing it. |
| `decrypt-snippet` | 183 | **Drop** (see §3 — snippet encryption is dropped for internal-only). |
| `admin-reset-password` | 105 | **Drop** — suite auth owns this. |

---

## 3. Scope (final, agreed)

### ✅ Keep (the core that makes this module valuable)
- **The six-engine scan engine** — provider fan-out, the **GPT-4o-mini mention classifier** (eliminates false positives from query restatements like "I'll search for [brand]…"), the regex `fallbackAnalysis`, per-provider **citation extraction**, sentiment, confidence, and raw-response capture.
- **Tracked keywords** + **tracked competitors** per client; competitor scans and competitor visibility trends.
- **Mention history** over time + the visibility-trend charts (Recharts in source → dependency-free SVG in suite, matching `components/rankings/`).
- **Invisibility diagnosis**, **keyword suggestions**, **visibility report** (→ Google Doc).
- **Scheduled scans** (weekly/monthly) — re-platformed onto the shared scheduler.
- **In-app notification feed** (`notification_history` / `notification_preferences`) — built as the seed of the suite's notifications service.

### ❌ Cut from this version
| Cut | Why / where it lives in the source |
|---|---|
| **Stripe + credits billing** | `credit_transactions`, `reserve_scan_credits` / `refund_scan_credits` / `create_credit_transaction` RPCs, `credits_balance` / `tier` / `subscription_status` columns, `Billing.tsx`, `AdminApiCosts.tsx`. Internal-only suite has no billing. The scan path simply drops the credit-reservation gate. |
| **Signup / onboarding / own auth** | `Signup.tsx`, `Onboarding.tsx`, `ResetPassword.tsx`, `UpdatePassword.tsx`, `admin-reset-password`. Suite JWT + existing users own this. |
| **Standalone `profiles` / `user_roles`** | Suite already has `profiles` + roles. The source `app_role` (`user` / `super_admin`) maps to the suite's `admin`. |
| **Snippet encryption at rest** | `encrypt_snippet` / `decrypt_snippet` RPCs, `decrypt-snippet` function, `snippet_encrypted` column, `SNIPPET_ENCRYPTION_KEY`. The suite stores all module output (briefs, pages, raw SERP) plaintext behind the service-role key on a private network; encrypting only this module's snippets adds friction with no suite-consistent benefit. Keep a plaintext `snippet` / `raw_response`. |
| **Email delivery (initially)** | `send-notification-email` (Resend). Gated on the notifications-channel decision (§6). In-app feed ships first; email is a fast follow once channels are confirmed. |
| **Agency white-label branding fields** | `agency_name` / `agency_logo_url` on `business_profiles` — the suite already has per-client `logo_url` + branding; reuse that for reports. |

### ➕ Add / adapt for the suite
- **Re-anchor `business_profiles` → `clients`.** The client *is* the brand. `brand_name` ← client name, `website_url`/`google_place_id`/`google_rating`/`formatted_address` ← the client's existing GBP data (`clients.gbp`). No new "business profile" entity.
- **Reports → Google Doc** in the client's Drive folder (shared `services/google_docs.py`), like the Maps Local Rank Analysis report.
- **Scheduling → shared scheduler** (`gsc_scheduler.py` pattern) + `async_jobs` job type `brand_scan` (and `brand_report`).
- **Launch from a client-workspace card** ("AI Visibility" / "Brand Strength"), like every other module.

---

## 4. Integration path: **B — full port into the suite**

Re-implement the backend in platform-api (Python/FastAPI), fold the data model into the suite Supabase project under a dedicated **`brand` schema** (precedent: the `fanout` schema — keeps ~9 ported tables from colliding with suite tables like `profiles`, `notification_*`, `tracked_keywords`, `system_settings`), and rebuild the UI natively in the suite frontend. This is the only path consistent with the suite's locked decisions ("Python for both APIs", "don't change service topology", "reuse the shared scheduler", "publish to Google Docs").

> **Why not Path A (vendor the edge functions + frontend, bridge auth).** It would keep a *second backend paradigm* (Deno edge functions) alongside FastAPI and a separate scheduler — directly against the locked topology. Rejected for anything beyond a throwaway trial.

---

## 5. Phased build

> One PR per phase. Phases 0–2 are the spine (a scan you can trigger and see); 3–5 layer on scheduling, UI polish, and reporting/notifications.

### Phase 0 — Data model migration *(gating)*
- New migration in `writer/supabase/migrations/` creating the **`brand` schema** with the ported, trimmed tables, all FK'd to **`clients.id`** (replacing `business_profile_id`):
  - `brand.tracked_keywords` (client_id, keyword, category, is_active)
  - `brand.tracked_competitors` (client_id, competitor_name, website, google_place_id)
  - `brand.mention_history` (client_id, keyword_id, engine, mention_found, mention_type, sentiment, confidence_score, citations jsonb, competitor_results jsonb, reasoning, snippet, raw_response, status, scanned_brand_name, is_competitor_scan, invisibility_diagnosis, failure_reason, retry_count, timestamps)
  - `brand.scan_schedules` (client_id, cadence, day_of_week, day_of_month, hour_utc, selected_engines, include_competitors, next_run_at, last_run_at, is_active)
  - `brand.notification_history` + `brand.notification_preferences` (client_id-anchored) — or promote to a suite-level `notifications` schema if the notifications service is designed in parallel (see §6).
  - `brand.system_settings` — **only** if a kill-switch / global engine-enable toggle is wanted (the source `KillSwitchControl`); otherwise fold into suite config.
- **Drop** at migration time: `credit_transactions`, `business_profiles` (its useful fields live on `clients`/`clients.gbp`), `profiles`, `user_roles`, billing RPCs, the encryption RPCs/columns.
- Enums (`ai_engine`, `mention_type`, `scan_status`, `scan_cadence`, `alert_type`, `alert_urgency`, `delivery_status`) recreated under the `brand` schema; **dropped**: `subscription_tier`, `subscription_status`, `credit_transaction_type`, `app_role`.

### Phase 1 — The scan engine in platform-api *(highest risk — port the 1461-line `run-scan`)*
- `services/brand_scan.py` — port the six executors + classifier + fallback + citation extraction to Python/`httpx`:
  - `chatgpt` (OpenAI Responses API w/ web search), `claude` (Anthropic), `gemini` (Google), `perplexity` (`sonar`) — direct calls.
  - `google_ai_overview` / `google_ai_mode` — DataForSEO (reuse the suite's DataForSEO client/creds).
  - `analyze_with_gpt4o_mini()` mention classifier + `fallback_analysis()` regex path.
- `async_jobs` job type **`brand_scan`** handled in `services/job_worker.py` (one row per keyword×engine, like the source), persisting to `brand.mention_history`. **No credit reservation** (cut). Mirror the source's retry/`failure_reason` handling.
- **Models** (`models/brand.py`): `ScanRequest`, `ScanResult`, etc. mirroring the trimmed shapes.
- **Tests** (`tests/test_brand_scan.py`): mock all providers; cover the classifier's query-restatement rejection and the regex fallback (the source's exact failure cases make good fixtures).
- Model choices to confirm (CLAUDE.md "ask first" #1): classifier `gpt-4o-mini`, scan engines as listed, diagnosis/suggestion models — see §6.

### Phase 2 — Backend API in platform-api
- `routers/brand.py`:
  - `GET/POST/DELETE …/clients/{id}/brand/keywords` · `…/competitors`
  - `POST …/clients/{id}/brand/scan` (enqueue `brand_scan` jobs for selected engines/keywords) · poll status
  - `GET …/clients/{id}/brand/history` (+ trend rollups) · `GET …/brand/scans/{id}`
  - `POST …/clients/{id}/brand/diagnose` (port `diagnose-invisibility`)
  - `POST …/clients/{id}/brand/suggest-keywords` (port `suggest-keywords`)
- `services/brand_service.py` — keyword/competitor CRUD, history queries, trend aggregation (deterministic rollups, like `rank_materialize` / `maps_analytics`).
- Reuse `services/keyword_market.py` for keyword metrics instead of porting `fetch-keyword-metrics`.

### Phase 3 — Scheduled scans on the shared scheduler
- Extend `services/gsc_scheduler.py` (or a sibling registration) to enqueue due `brand.scan_schedules` as `brand_scan` jobs — **no new cron infra** (locked decision). Compute `next_run_at` from cadence; honor `selected_engines` / `include_competitors`.

### Phase 4 — Frontend in the shared app
- New suite pages in the **inline-style** system (not Tailwind/shadcn), launched from a new **client-workspace card**:
  - **Visibility dashboard** — health-score gauge, per-engine visibility, latest scan, "Run scan now".
  - **History** — daily scan groups + trend charts (dependency-free SVG, reusing the `components/rankings/` chart approach).
  - **Scan detail** — per keyword×engine: mention, sentiment, citations, snippet, diagnosis.
  - **Keyword manager** / **Competitor manager** (+ competitor comparison & trend charts).
  - **Scheduled-scan settings** + **report export** (triggers the Drive report).
- Recharts/shadcn from the source are **reference only** — rebuilt in the suite's component style.

### Phase 5 — Reporting + notifications
- **Report**: `services/brand_report.py` + `async_jobs` `brand_report` → assemble report data (port `generate-visibility-report`'s data layer) and publish a **Google Doc** to the client's Drive folder via `services/google_docs.py`.
- **Notifications (in-app)**: write `brand.notification_history` on scan completion / invisibility / reputation drops (port `process-scan-alerts`' logic). Surface in the suite UI. **Email (Resend) deferred** until channels are confirmed — this module is the natural seed for the suite-wide **notifications service**, so align with that rather than shipping a siloed emailer.

---

## 6. Open items to settle (before/within the relevant phase)
1. **Notifications service alignment** (CLAUDE.md "ask first" #6). This module ships an in-app feed and *wants* email. Decide now whether to (a) build a minimal `brand`-scoped feed and generalize later, or (b) design the suite `notifications` schema/service up front and have this module be its first consumer. Email provider/channel (Resend vs Slack vs in-app-only) is the gating decision for Phase 5's email path.
2. **Model selection per task** (CLAUDE.md "ask first" #1). Confirm: mention classifier `gpt-4o-mini`; scan engines (`chatgpt`=`gpt-4.1`, `claude`=`claude-sonnet-4`, `gemini`, `perplexity`=`sonar` in the source) — keep as-is or standardize on suite defaults?; diagnosis + keyword-suggestion models.
3. **New API keys / env on `PLATFORM`** — already present: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DATAFORSEO_LOGIN`/`PASSWORD`. **New, required:** `PERPLEXITY_API_KEY`, `GEMINI_API_KEY`. **Places:** the source uses `GOOGLE_PLACES_API_KEY`; the suite already has `GOOGLE_MAPS_API_KEY` (Geocoding) + Outscraper/DataForSEO GBP resolution — confirm whether to reuse GBP resolution (preferred) or add a Places key. **Email:** `RESEND_API_KEY` only if Phase 5 email ships.
4. **Schema home for notifications** — `brand` schema now vs a shared `notifications` schema (ties to item 1).
5. **Module placement / naming** — its own dashboard tile + workspace card ("AI Visibility" / "Brand Strength"), vs a tab inside the rank-tracker workspace. Product call; recommend its own card (it has its own keyword set, engines, and cadence).
6. **Snippet encryption** — confirm dropping at-rest encryption is acceptable (recommended for internal-only; consistent with how the suite stores all other generated output).
7. **Kill-switch / `system_settings`** — keep the global engine-disable toggle, or rely on config + the schedule's `selected_engines`?

---

## 7. Effort estimate
**Medium-to-large — comparable to the Local SEO / nlp-api port, not the fanout mount.** The spine (Phases 0–2: data model + the ported scan engine + the API) is the bulk of the risk and work, concentrated in re-implementing the 1461-line `run-scan` (six providers + classifier) in Python. Phases 3–5 reuse existing suite machinery (shared scheduler, Google Docs publish, inline-style frontend, `keyword_market`). Rough order: **~2–4 weeks** of focused work, one PR per phase.

What makes it *less* than it looks: ~5 of the 11 edge functions are dropped (billing/auth/encryption/email), `fetch-keyword-metrics` and Places are reuse-not-port, and the data model is a straightforward re-anchor to `clients` minus the billing/auth tables.

---

## 8. Notes / provenance
- Source: `kssabraw/brand-strength-ai` (Lovable app, separate Supabase project `chpcxrpbylsvclwfbelm`). Cloned locally during planning; **not** a suite source-of-truth — the suite re-implements rather than vendors it.
- This module is a **sibling to the rank trackers** and the natural **seed for the unbuilt notifications service** on the suite roadmap; building it should be coordinated with that roadmap item.
- When work starts, add a "Brand Strength / AI Visibility" entry to `CLAUDE.md`'s reference-docs list and the suite roadmap module table (as was done for Local SEO and the Organic Rank Tracker).
