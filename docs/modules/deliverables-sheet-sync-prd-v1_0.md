# Deliverables Sheet Sync — PRD v1.0

**Status:** Proposed (not built). Ships behind a disabled feature flag.
**Owner:** Kyle
**Last updated:** 2026-07-12
**Authoring branch:** `claude/pace-google-sheet-links-a28jhh`

> **One-line summary.** Automatically keep each client's Google "deliverables" sheet up to date: when a task is completed on the native task board, append a row recording what was delivered (type, keyword, link, date); and watch each sheet's client-facing **Notes** column so that when a client leaves a note, a staff member is alerted in Slack. The goal is to eliminate the VA's manual upkeep of these sheets.

---

## 0. Context for a reader new to this codebase

This module sits inside **AR Tools**, an internal multi-module SEO/content suite for an agency (Amazing Rankings). You do not need deep suite knowledge to understand this PRD, but you do need a handful of existing pieces it builds on. Everything below is already built and live unless stated otherwise.

| Piece | What it is | Where |
|---|---|---|
| **Clients** | The agency's SMB clients. Each has a `clients` row with a Google Drive folder (`google_drive_folder_id`), business details, etc. | `clients` table |
| **Native Task Manager** | The suite's in-app task system (an Asana replacement). Tasks live in a `tasks` table, grouped into monthly/backlog sections per client. Each task has a **category** (`Content`, `Link Building`, `GBP Authority`, `Strategy`), a **status** (Not Started → In Progress → Blocked → In Review → Sent to Client → Client Approved → **Complete**), an assignee, and optional attachments. | `services/task_service.py`, `docs/modules/in-app-task-manager-prd-v1_0.md` |
| **Task producers** | A layer that auto-creates/auto-closes tasks from suite signals, made idempotent by a `(source, source_ref)` key on each task. This module adds a *consumer* that reacts to task completion, not a producer, but it reuses the same hook points. | `services/task_producers.py` |
| **Published content** | When the suite generates content (Blog Writer runs, Local SEO pages) and publishes it, the resulting Google Doc URL is stored (`runs.published_doc_url`, `local_seo_pages.published_doc_url`). Content-producing tasks reference their run via `source_ref`. | `routers/publish.py`, `services/local_seo_service.py` |
| **Service account** | The suite authenticates to Google as a service account (`settings.google_service_account_key`; email via `gsc_service.get_service_account_email()`). It is currently scoped **read-only** for Search Console (`webmasters.readonly`). Writing to Sheets requires building a second credential from the same key with the Sheets scope. | `services/gsc_service.py` |
| **Apps Script webhook** | The suite's *existing* way to create Google Docs/Sheets, via a create-only Apps Script web app. **This module does NOT use it** — it needs read + append on existing sheets, which the webhook cannot do. We call the Google Sheets API directly instead. | `services/google_docs.py`, `writer/apps-script/publish_webhook.gs` |
| **Notifications service** | Shared delivery layer. `notifications.emit(client_id, kind, title, …, dedupe_key=…)` writes an in-app notification and dispatches Slack (live) + email (dormant) copies best-effort. Slack posts to the agency channel. | `services/notifications.py` |
| **Shared scheduler** | An in-process asyncio loop that enqueues due jobs on an interval. New recurring work is added as an `enqueue_due_*` function here — no new infrastructure. | `services/gsc_scheduler.py` |
| **PACE** | The suite's operational **P**roject **A**ssignment, **C**oordination & **E**xecution agent — a Haiku-based persona that watches the native task board and keeps delivery moving (surfacing stale/overdue/unassigned work, and taking confirm-gated write actions on tasks). It is the sibling to the strategist agent ("SerMaStr decides *what* should be done; PACE keeps it moving"). Currently gated behind `pace_enabled` (default off). | `services/pace_*.py`, `services/pm_signals.py`, `docs/modules/project-manager-agent-plan-v1_0.md` |

**Why this is framed as a PACE feature.** The trigger is task-board activity and the surfacing rides PACE's daily digest, so it lives in PACE's world. But the actual engine is deterministic bookkeeping (a producer-style hook + a scheduled poller), **not** a conversational PACE action. PACE narrates it; it does not execute it. This distinction matters for the build: no LLM is in the write or watch path.

---

## 1. Problem

Every client has a Google Sheet ("deliverables sheet") that a VA maintains by hand. Each time a piece of work is delivered — a blog post, a landing page, a batch of citations, a tier-2 link push, a niche edit — the VA opens the client's sheet and manually records it: pick the content/link **type** from a dropdown, paste the **link**, type the **date**. Separately, clients leave feedback in a **Notes** column, and someone has to notice it and act.

This is repetitive, error-prone, and easy to fall behind on. It is exactly the kind of clerical work the suite should absorb.

## 2. What we're building

A background module that does two things, per client, with no VA involvement:

1. **Write (auto-log deliverables).** When a task is marked **Complete** on the native task board, append a row to that client's deliverables sheet describing what was delivered.
2. **Watch (auto-alert on client notes).** Poll each client's deliverables sheet for new entries in the client-facing **Notes** column and, when a client leaves a note, alert a staff member in Slack.

PACE surfaces a one-line summary of new client notes in its daily digest.

## 3. Goals / non-goals

**Goals**
- Eliminate manual maintenance of the deliverables sheet for anything the suite can determine automatically.
- Never silently lose a deliverable or a client note.
- Reuse existing suite rails (service account, task board, notifications, scheduler, PACE digest). No new infrastructure.
- Ship dark (feature-flagged off) and enable per client.

**Non-goals (v1)**
- Two-way editing of anything except appending rows and reading the Notes column. We never modify the client-owned **Status** or **Notes** columns.
- The third "Other" tab (see §4) — ignored in v1.
- Generating the vendor deliverables themselves (citations files, tier-2 boosters, niche edits). Those come from outside the suite; we only *log* them.
- Backfilling historical deliverables into the sheet. Sync begins at go-live going forward.
- Per-client Slack routing. v1 alerts go to the agency channel (matching the rest of the notifications service).

## 4. Background: the deliverables sheet

The canonical template is titled **"DELIVERABLES TEMPLATE — MAKE A COPY!"**; each client gets a copy (e.g. "UMH Properties, Inc"). A populated real example (UMH Properties) informed this spec.

The sheet has **three tabs**:

### Tab 1 — Content (content deliverables)

| Col | Header | Meaning |
|---|---|---|
| A | **Content Type** | Dropdown (see §6). |
| B | Keyword | The target keyword/topic. Usually filled. |
| C | Google Doc Link | The deliverable, as a **titled hyperlink** (display text = doc title, target = the Google Doc / Drive file URL). |
| D | Date | Delivery date (free text, e.g. "May 14, 2026"). |
| E | **Status** | Client/staff approval workflow (e.g. "Approved"). **Client/staff-owned — we never write this.** |
| F | **Notes** | Client-facing feedback column. **We read this to detect new notes; we never write it.** |

### Tab 2 — Links (link-building deliverables)

| Col | Header | Meaning |
|---|---|---|
| A | **Links Type** | Dropdown (see §6). |
| B | Keyword | Often blank on this tab. |
| C | Google Doc Link | The deliverable link/file, as a titled hyperlink. Frequently a **Drive file** (a citations `.xlsx`, a tier-2 booster `.xlsx`, an authority-links `.txt`) rather than a web URL; sometimes a real published URL (a niche edit / guest post). |
| D | Date | Delivery date. |
| E | **Notes** | Client-facing feedback column. Same watch/never-write rule as tab 1. (Note: on this tab Notes is column E, since there is no Status column.) |

### Tab 3 — Other (`Description | Google Doc Link | Date | Notes`)

A rarely-used catch-all. **Out of scope for v1** — left to manual entry.

### Observations from the real (UMH) sheet that shaped the design

- **Column C is a titled hyperlink, not a bare URL**, and on the links tab it often points to a Drive *file*. Deliverable names follow a convention like `MM-YYYY_<CLIENTCODE>_<type>_<name>` (e.g. `05-2026_UMH_Citations_Oak Tree.xlsx`). When we append, we replicate the titled-hyperlink style (display text + underlying URL).
- **The live dropdown values can differ slightly from any hardcoded list** — the real links tab uses **"Other Links"** (with a space), not "Otherlinks." Therefore the mapper **reads each sheet's actual dropdown/data-validation values at runtime** and matches against them, falling back to the sheet's own "Other"/"Other Links" value. This keeps us robust to per-sheet drift.
- **Status is an approval workflow** (only some rows are "Approved"). Confirmed: leave it untouched.
- **Keyword is optional** (blank throughout the links tab).
- The example sheet is an uploaded `.xlsx` owned by a team member (`amazingrankings.ca`) inside a Drive folder — informing the access model (§7).

## 5. Core behavior

### 5.1 The one rule (write side)

> When a task transitions to **Complete**, append one row to its client's deliverables sheet. The deliverable **link** comes from the suite-published content the task is linked to, if any; otherwise from the file/URL the VA attached to the task. The same logic serves both tabs.

Content production is a **mix**: some content flows through the suite (Blog Writer / Local SEO → we already hold the Doc URL → fully automatic), and some is produced externally (the VA attaches the link to the task). Link-building deliverables are **always** external (vendor files/URLs) — the VA attaches them to the task, and we log whatever is attached. So there is a single, uniform resolution path:

1. **Suite-published content linked to the task** → use its `published_doc_url` + title. (Zero human effort.)
2. **Else, a link attached to the task** → the task's delivery-link field, or its first attachment. (Human attaches once, on the task they're already completing.)
3. **Else, no link found** → append the row anyway with a blank link **and flag it** (see §8, missing-link policy). Never silently drop.

### 5.2 Per-task write flow (in detail)

On a task reaching **Complete**:

1. **Resolve the sheet.** `task → client_id → clients.deliverables_sheet_id`. If the client has no sheet configured, skip silently.
2. **Choose the tab.** By task **category**: `Content` → Content tab; `Link Building` → Links tab. `GBP Authority` with a GBP-post-shaped task → Content tab ("GBP Post"). `Strategy` and anything else → skip (not a client deliverable).
3. **Choose the column-A value.** Read the tab's live dropdown values; map from the task (§6) with fallback to the sheet's "Other" / "Other Links".
4. **Assemble the row:**
   - **A** = dropdown value.
   - **B** = keyword (from linked content, else a task field; blank allowed).
   - **C** = titled hyperlink — for suite-published content, display = Doc title, target = `published_doc_url`; for an attached deliverable, display = file/link name, target = its URL.
   - **D** = completion date (formatted like the sheet's existing dates, e.g. "July 12, 2026").
   - **E/F** = untouched (Status / Notes are client-owned).
5. **Append** via the Sheets API (`spreadsheets.values.append`, or a `batchUpdate` when writing a rich hyperlink), targeting the correct tab's table.
6. **Mark synced.** Record that this task has been written so a reopen→re-complete cycle never double-appends (see §8, idempotency).

### 5.3 Notes watcher (read side)

1. On the shared scheduler (default every ~15 min, configurable), for each client with a configured sheet and the watcher enabled:
2. Read the Notes column of each watched tab.
3. Diff against the stored per-row snapshot of Notes values for that sheet.
4. For each cell that newly gained (or changed to) non-empty text, emit a Slack alert via `notifications.emit(client_id, kind="deliverable_note", …)` naming the client, the deliverable row (its type + keyword + link), and the note text. Use a `dedupe_key` per (sheet, row, note-hash) so a transient re-read cannot double-alert.
5. Update the stored snapshot.

### 5.4 PACE surfacing

PACE's daily digest (`services/pace_digest.py`) gains a line: "N new client notes across M clients (last 24h)", derived from the `deliverable_note` notifications. PACE does not perform the sync or the watch — it only reports.

## 6. Dropdown mapping (task → column A)

The mapper reads the tab's **actual** dropdown values and matches case-insensitively; the values below are the expected vocabulary. Any task that falls through to the fallback is **logged** (structured log) so the rules can be tuned rather than silently mislabeling.

### Content tab — Content Type

| Task signal | → dropdown value |
|---|---|
| Linked content type = blog post | Blog Post |
| = local landing page | Local Landing Page |
| = service page | Service Page |
| = location page | Location Page |
| GBP-post task | GBP Post |
| = ecommerce | Ecommerce |
| anything unmapped | **Other** |

(The template's "GBP Services" / "GBP Products" values are intentionally **not** targeted — per owner direction they are being removed from the sheet.)

### Links tab — Links Type

| Task signal | → dropdown value |
|---|---|
| **Task is an SEO NEO task (assignee/role)** | **Tiered Link Pyramid** (explicit rule — overrides all others) |
| task name contains "niche edit" | Niche Edit |
| "guest post" | Guest Post |
| "cloud stack" | Cloud Stack |
| "google stack" | Google Stack |
| "tier 2" | Tier 2 |
| "citation" | Citations |
| "press release" | Press Release |
| anything unmapped | **Other Links** (match the sheet's exact value) |

## 7. Google access model

The suite authenticates to Google as its **service account**. The identity making the API call must have edit access to each client sheet. Options, in recommended order:

1. **Shared Drive (recommended).** Put all client deliverables sheets in one agency Shared Drive and add the service account as a member **once**. Every sheet inside is then readable/writable with no per-client sharing, and a new client just means creating its sheet in that Drive. Best fit given the sheets already live under the `amazingrankings.ca` Workspace.
2. **Per-sheet share.** Share each client sheet with the service-account email individually. Simple but adds a per-client step.
3. **Domain-wide delegation.** Authorize the service account to act as a real Workspace user; it then edits anything that user can, no sharing needed. More one-time admin setup.
4. **Apps Script webhook (as a human account).** Extend the existing create-only webhook (which runs as the deploying user's Google account) to append/read. Avoids the service account entirely but means Apps Script code + a redeploy, and reads are clunkier. Fallback only.

**Scopes.** The service account key is already provisioned, but its current credential is built with the read-only Search Console scope. This module builds a **separate credential from the same key** with `https://www.googleapis.com/auth/spreadsheets` (write) and, for the Shared-Drive/native-Sheet handling, `https://www.googleapis.com/auth/drive` as needed. This is additive; the existing GSC path is unchanged.

**Native Sheets requirement.** The Sheets API operates on native Google Sheets, not uploaded `.xlsx` files. Each client's deliverables copy must be a native Google Sheet (a one-time "Save as Google Sheets" for any `.xlsx` copy). The stored `deliverables_sheet_id` is that native sheet's ID.

## 8. Edge cases & decisions

- **Missing link on completion (default: append-and-flag).** If a task completes with no resolvable link, append the row with a blank Column C and emit a warning notification ("delivered, link missing") so staff can fill it in. (Alternative, if preferred later: block completion until a link is present. v1 uses append-and-flag to avoid interfering with the task workflow.)
- **Idempotency / reopen.** A task that is completed, reopened, and completed again must not append twice. A per-task synced marker (keyed by the task's stable ID, analogous to producers' `(source, source_ref)`) guards this. Re-completing an already-synced task is a no-op.
- **Titled hyperlinks.** To match the VA's style, Column C is written as a hyperlink (display text + target URL), not a bare URL, using a Sheets `batchUpdate` rich-text/hyperlink write. A bare URL is an acceptable degraded fallback if rich write fails.
- **Live dropdown read + fallback.** The mapper reads each sheet's real data-validation list and matches against it; unmatched → the sheet's own "Other"/"Other Links". Every fallback is logged.
- **Date formatting.** Match the sheet's human-readable style ("July 12, 2026"). Not a machine date.
- **Best-effort, never raises.** Both the write hook and the poller are wrapped so a Sheets/API failure logs and moves on without breaking task completion or the scheduler tick (same discipline as the existing producers and sweeps).
- **Notes we wrote vs client notes.** We never write the Notes column, so any content there is the client's — no risk of alerting on our own writes. New appended rows start with an empty Notes cell in the snapshot.

## 9. Data model (schema changes)

Migration under `writer/supabase/migrations/`:

- `clients.deliverables_sheet_id` (text, nullable) — the native Google Sheet ID for this client. Null = sync disabled for this client.
- A per-task **synced marker** for write idempotency. Either a nullable `deliverables_synced_at` on `tasks`, or a small `deliverables_sync_log(task_id, sheet_id, row_ref, written_at)` table if we want an audit trail (leaning to the log table for observability).
- A per-sheet **Notes snapshot** for the watcher — a small table `deliverables_notes_state(sheet_id, tab, row_index, note_hash, seen_at)` (or a JSONB snapshot per client). Keyed so the diff is per row.

No changes to the `tasks` schema beyond the optional synced marker.

## 10. Integration points (where the code lands)

- **New service** `services/deliverables_sheet.py` — pure mapping helpers (tab + dropdown resolution, row assembly) that are unit-tested, plus the impure Sheets read/append and the notes-diff. Pure/impure split mirrors the suite's convention.
- **Sheets client** — a small authenticated Sheets API helper (new credential build with the write scope) beside `services/google_docs.py`, or folded into it.
- **Write hook** — invoked when a task reaches Complete. The native task manager already has completion paths (`task_service` complete/reopen, and `task_producers` close-on-resolve hooks); the append fires from there, double-gated (see §11).
- **Poller** — `gsc_scheduler.enqueue_due_deliverable_note_scans()` (interval-gated), enqueuing a `deliverable_notes_scan` async job per due client; the job reads Notes and emits alerts.
- **PACE digest** — one added section in `services/pace_digest.py`.
- **Admin action** — a small endpoint to set/validate a client's `deliverables_sheet_id` (verifies the service account can open the sheet and reports the tabs/dropdowns found).
- **Tests** — mapper (each content/link case + SEO NEO rule + fallback), append idempotency (reopen→re-complete), notes-diff (new note fires once, unchanged note silent).

## 11. Feature flags & rollout

- `deliverables_sheet_enabled` (config, default **False**) — master gate; while off, the write hook and the poller are dormant.
- Optional per-side toggles (`deliverables_write_enabled`, `deliverables_notes_watch_enabled`) so either half can run alone.
- `deliverables_notes_scan_interval_minutes` (default ~15).
- Per-client enablement is implicit: a client with no `deliverables_sheet_id` is skipped, so we roll out by setting the sheet ID one client at a time even with the master flag on.

**Setup steps (owner side, done at rollout, not blockers to building):**
1. Create the agency Shared Drive (or choose the access model in §7) and add the service-account email.
2. For each client, ensure the deliverables sheet is a **native Google Sheet** and record its ID via the admin action.

## 12. Out of scope / future

- The third "Other" tab.
- Historical backfill.
- Per-client Slack routing / per-recipient notification prefs (waits on the profiles-unification work noted in the task manager PRD).
- Blocking task completion on a missing link (v1 flags instead).
- Auto-setting the Status column or any client-owned field.

## 13. Open questions

1. **Access model** — confirm Shared Drive (recommended) vs per-sheet share vs delegation vs webhook.
2. **Synced marker shape** — column on `tasks` vs a dedicated sync-log table (leaning log table).
3. **SEO NEO detection** — is "SEO NEO" identified by assignee, by a role/team mapping, or by task-name convention? Needs the exact signal to implement the override rule reliably.
4. **Real client note format** — the sample sheet's Notes column was empty; if notes are ever multi-line or dated entries, confirm we alert on any change to the cell (current assumption) vs only on net-new lines.

## Appendix A — Real sheet sample (UMH Properties, abridged)

Content tab (A–F): `Blog Post | Manufactured Homes in Millville, NJ | 05-2026_UMH_blog_… (titled hyperlink) | May 14, 2026 | Approved | (empty)`

Links tab (A–E): `Niche Edit | (blank) | https://drhomey.com/crunching-the-numbers-are-manufactured-homes-worth-the-low-cost/ | May 22, 2026 | (empty)` … `Citations | (blank) | 05-2026_UMH_Citations_Oak Tree.xlsx (Drive file) | May 22, 2026 | (empty)` … `Tier 2 | (blank) | UMH-052026_T2Booster-Fairview Manor.xlsx | May 22, 2026 | (empty)` … `Other Links | (blank) | UMH-052026-Authority Links-Oak Tree.xlsx | May 25, 2024 | (empty)`

Illustrates: titled hyperlinks in Column C, Drive files as links on the Links tab, "Other Links" as the real fallback value, blank keywords on the Links tab, and Status used only occasionally on the Content tab.
