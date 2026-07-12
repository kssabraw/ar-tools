# Client Onboarding Automation — Integration Plan v1.0

**Status:** Proposed (not built). Design note for a future build.
**Owner:** Kyle
**Last updated:** 2026-07-12
**Relationship to other work:** extends the client-creation flow and the Apps Script publishing path; supersedes the *creation* half of the Deliverables Sheet Sync module (`docs/modules/deliverables-sheet-sync-prd-v1_0.md`) — see §7.

> **One-line summary.** When a client is created in the suite, automatically build out their Google Drive workspace — the client's Drive folder (and any standard subfolders), their deliverables sheet, and the sharing that goes with them — so the team never sets up a client's Drive by hand. PACE surfaces/triggers it; the deterministic engine does the work.

---

## 0. Context for a reader new to this codebase

AR Tools is an internal agency SEO/content suite. A few existing pieces matter here; everything below is already built unless noted.

| Piece | What it is | Where |
|---|---|---|
| **Clients** | Each SMB client is a `clients` row. It carries a **manually-entered** Google Drive folder id (`google_drive_folder_id`) plus an optional per-content-type folder map (`drive_folders`). Today a human creates the Drive folder and pastes its id into the client form. | `clients` table, `routers/clients.py` |
| **Apps Script webhook** | The suite's Google **creation** path. A deployed Apps Script web app that runs **as the human Workspace account that deployed it**. It creates Google Docs, Sheets, and PDFs *into a given folder* and can set sharing (`private|link|public`). It does **not** currently create folders. Because it runs as a real human account, files it creates are human-owned with **no storage-quota limits**. | `writer/apps-script/publish_webhook.gs`, `services/google_docs.py`, `GOOGLE_APPS_SCRIPT_URL` |
| **Service account** | The backend's *direct* Google identity (Search Console + — as of the Deliverables module — Sheets read/append). **Cannot reliably create Drive files**: a service account creating files as itself hits *"Service Accounts do not have storage quota"*. Good for reading/appending existing sheets; bad for creation. | `services/gsc_service.py`, `services/google_sheets.py` |
| **Client-creation background jobs** | `routers/clients.create_client` already fire-and-forgets several best-effort async jobs at creation (`brand_voice_scan`, `icp_scan`, `page_structure_scrape`, backlink auto-track, `rank_location_derive`, and — from the Deliverables module — deliverables-sheet provisioning). This is the natural hook for onboarding automation. | `routers/clients.py` |
| **Shared scheduler + async_jobs** | In-process asyncio loop enqueuing jobs into the `async_jobs` table. New recurring/background work rides this — no new infra. | `services/gsc_scheduler.py`, `services/job_worker.py` |
| **Notifications service** | `notifications.emit(client_id, kind, title, …)` → in-app + Slack (live). The channel for "onboarding done" / "onboarding step failed". | `services/notifications.py` |
| **PACE** | The suite's operational agent (watches the task board, keeps delivery moving; Haiku persona, gated behind `pace_enabled`, default off). **PACE is not a Google identity** — it's orchestration that triggers the suite's Google plumbing and narrates the result. | `services/pace_*.py`, `docs/modules/project-manager-agent-plan-v1_0.md` |

**The identity model this plan rests on (the key decision):** *creation* of Drive folders/files runs through the **Apps Script webhook (human account)** — no quota limits, human-owned, and it already owns every client folder. The **service account** stays on what it's good at: reading/appending existing sheets. PACE triggers and reports; it owns no credentials of its own.

---

## 1. Problem

Setting up a new client's Google workspace is manual clerical work: create the client's Drive folder, (optionally) standard subfolders, create their deliverables sheet from the template, drop it in the right place, and share what needs sharing. Today the Drive folder is created by hand and its id pasted into the client form. This is exactly the kind of onboarding toil the suite should absorb — and it's the natural companion to the Deliverables Sheet Sync module, which assumes a sheet already exists.

## 2. What we're building

At client creation (and on-demand for existing clients), automatically:

1. **Create the client's Drive folder** under a standard parent, named for the client, and store its id on `clients.google_drive_folder_id` — so the manual "make a folder, paste the id" step disappears.
2. **(Optional) Create standard subfolders** (e.g. per-content-type folders that populate `drive_folders`).
3. **Create the client's deliverables sheet** from the master template, inside that folder.
4. **Apply sharing** per the rules in §5.
5. **Record what was created** on the client, **surface completion/failure** via notifications, and let PACE trigger/narrate it.

All of it runs through the **Apps Script (human-account) path**, so there is no service-account quota problem and no Shared Drive requirement.

## 3. Goals / non-goals

**Goals**
- Zero manual Drive setup for a new client.
- One identity for all creation (human account via Apps Script) → no quota caveats, no delegation, no Shared Drive dependency.
- Best-effort + idempotent: a partial failure is surfaced and re-runnable, never a broken client.
- Reuse existing rails (client-create hook, async_jobs, notifications, PACE). No new infra.
- Ship dark behind a flag; backfill existing clients on demand.

**Non-goals (v1)**
- Client-facing sharing of the deliverables sheet (stays manual — carried over from the Deliverables PRD's owner decision).
- Provisioning non-Google assets (Asana project, GSC property, etc.) — separate onboarding concerns.
- A general "Drive templating" engine — v1 creates a fixed, known set of things.

## 4. Folder structure & naming

Decisions to confirm at build time (defaults proposed):

- **Parent folder.** A single standard "Clients" parent folder (owned by the Apps Script's human account), its id in config (`ONBOARDING_PARENT_FOLDER_ID`). Every client folder is created inside it.
- **Client folder name.** The client's name (matching how the deliverables sheet is named). Collision handling: if a folder of that name already exists under the parent, **reuse it** rather than making a duplicate (the create action should look up first, or accept an "reuse if exists" flag).
- **Subfolders (optional).** If enabled, create the per-content-type subfolders that back `drive_folders` (e.g. `blog`, `service`, `local-landing`, `reports`). v1 can ship with just the client root folder + the deliverables sheet and add subfolders later.
- **Deliverables sheet name.** The client's name (as in the Deliverables module).

## 5. Sharing rules (v1)

- **Client folder + subfolders:** internal only (owned by the human account; team access via the account/Workspace as today). No external sharing.
- **Deliverables sheet:** **manual client sharing** (carried over from the Deliverables PRD — the VA shares it once). Auto-sharing to the client is a deferred follow-up; when built it can reuse `client_report_settings.recipients`.

## 6. Apps Script webhook additions

The webhook (`publish_webhook.gs`) gains two actions (both `DriveApp`, same authorization scope as its existing file creation — but a **redeploy is required**):

- **`createFolder`** — `{type:"folder", parent_folder_id, name, reuse_if_exists?}` → returns `{folder_id}`. `DriveApp.getFolderById(parent).createFolder(name)`, or return the existing folder's id when `reuse_if_exists` and a match is found.
- **`copyFile`** — `{type:"copy", file_id, name, folder_id, share?}` → returns `{id, url}`. `DriveApp.getFileById(templateId).makeCopy(name, DriveApp.getFolderById(folderId))`. A native-Sheet template copied this way keeps its tabs + dropdown validation (why the template must be native). This is the human-account replacement for the service-account `files.copy` used in the Deliverables module.

`services/google_docs.py` gains thin wrappers (`create_drive_folder`, `copy_drive_file`) around `_call_apps_script`, mirroring the existing `create_google_doc` / `create_google_sheet` helpers.

## 7. Relationship to the Deliverables Sheet Sync module (the one code decision)

The Deliverables module (PR #373) currently creates the deliverables sheet via the **service account** (`google_sheets.copy_template`, Drive `files.copy`) — which is *why* it needs a Shared Drive or domain-wide delegation (the SA-creation quota wall). This plan **unifies creation under the Apps Script human account**, which removes that requirement entirely.

**Recommended:** when this is built, **repoint the deliverables-sheet creation to the Apps Script `copyFile` action** (via `google_docs.copy_drive_file`) and retire `google_sheets.copy_template` + the Drive scope on the service account. The deliverables module's **read/append/watch path is unaffected** — the service account still does that (it only reads/appends existing sheets, no quota issue).

**Migration path:** PR #373 can ship as-is (dark, SA copy) without blocking this. When onboarding automation lands, it supersedes the creation half. Net effect once unified: **no Shared Drive and no domain-wide delegation needed anywhere** — the only Google prerequisites become (a) the Apps Script redeploy with the two new actions and (b) the native master template + parent-folder ids in config.

> **Open decision for the owner:** unify now (repoint deliverables creation to Apps Script as part of this work) vs. keep the SA copy in #373 and treat onboarding as a separate layer. This plan assumes **unify** — it's the design that eliminates the quota caveat.

## 8. Data model / config

**Schema:** likely no new table — store the created ids on `clients`:
- `google_drive_folder_id` (exists) — now populated by onboarding instead of manually.
- `drive_folders` (exists) — populated if subfolders are created.
- `deliverables_sheet_id` (exists, from the Deliverables module).
- Optionally an `onboarding_state` jsonb (per-step status) for observability, or reuse the `async_jobs` result rows.

**Config:**
- `ONBOARDING_PARENT_FOLDER_ID` — where client folders are created.
- `deliverables_template_sheet_id` (exists) — the native master template to copy.
- `onboarding_enabled` (master flag, default false) + optional per-step toggles.
- Reuses `GOOGLE_APPS_SCRIPT_URL`.

## 9. Flow

**At client creation** (`routers/clients.create_client`, best-effort like the existing auto-jobs), enqueue an `onboarding_provision` async job:
1. Create/reuse the client folder under the parent → store `google_drive_folder_id`.
2. (Optional) create subfolders → store `drive_folders`.
3. Copy the deliverables template into the client folder → store `deliverables_sheet_id`.
4. Apply §5 sharing.
5. Emit an `onboarding_complete` (or `onboarding_failed`, with the failing step) notification.

**Idempotency:** each step checks "already done?" (folder id / sheet id already stored, or folder-name lookup) and skips — a re-run gap-fills. Conditional writes on the id columns guard concurrent create-hook vs on-demand backfill (same pattern used in the Deliverables provision job).

**On-demand / backfill:** an admin endpoint (and a PACE-surfaced "client not onboarded" signal) enqueues the same job for an existing client — creating only the missing pieces.

**PACE's role:** surfaces "client X isn't fully onboarded" and can trigger provisioning; it does not perform the Drive calls. Narrates completion in its digest.

## 10. Failure modes to handle

- Apps Script webhook down / unauthorized → job fails, notification fires, re-runnable. No half-created client is left unrecoverable (ids are only stored on success per step).
- Duplicate folder (name already exists) → reuse, don't duplicate.
- Concurrent create-hook + backfill → conditional id writes; loser logs an orphan.
- Client created before the feature existed → backfill path.
- Template missing/misconfigured → step 3 fails loudly, steps 1–2 still succeed.

## 11. Open questions

1. **Unify vs. layer** (the §7 decision) — repoint deliverables creation to Apps Script now, or keep #373's SA copy?
2. **Subfolders in v1?** Just the client root + deliverables sheet, or the full per-content-type subfolder set?
3. **Folder naming/collision** — client name only, or a convention (client name + code / created date) to avoid collisions?
4. **Backfill trigger** — admin-only, PACE-triggered, or a one-time bulk pass over existing clients?
5. **Scope creep check** — should onboarding also seed non-Drive assets (Asana project, etc.), or stay Drive-only for v1?

## 12. Build order (rough)

1. Apps Script webhook: add `createFolder` + `copyFile` actions; redeploy; `google_docs` wrappers.
2. `onboarding_provision` job + client-create enqueue (behind `onboarding_enabled`).
3. Repoint deliverables-sheet creation to the Apps Script path; retire the SA `copy_template` + Drive scope (if unifying).
4. Admin/backfill endpoint + PACE "not onboarded" signal.
5. Config + docs + tests.

---

### Appendix — why not the service account for creation

A service account creating Drive files *as itself* has no storage quota and fails with `storageQuotaExceeded` even for tiny files. The two standard workarounds are a **Shared Drive** (org-owned files) or **domain-wide delegation** (impersonate a human). The suite already has a *third, simpler* option in production — the **Apps Script webhook running as a human Workspace account**, which owns every client folder today and creates all the suite's Docs/Sheets/PDFs with no quota limits. This plan standardizes on it for creation, keeping the service account for read/append only.
