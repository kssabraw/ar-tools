# Cold-Caller CRM — Improvement Handoff

**Scope:** the caller-facing CRM surface of the Outreach module — the daily tool a cold caller uses
to work leads, dial, disposition, and book callbacks. NOT the scanning/scoring pipeline (that is
sound; see `START-HERE.md`).

**Status:** **Tiers 1 + 2 BUILT and MERGED to `main` (2026-09-17)** — the caller cockpit is done bar
one deliberately-deferred item (T2.3). **Tier 3: T3.2 (script + rebuttal library) BUILT (this
session, draft PR to `main`); T3.1 (click-to-call) DEFERRED — owner ruled §5 Q4 "none for now" on
2026-09-17, so no vendor / no code / no spend.** With T3.2 shipped and T3.1 deferred, Tier 3 is
complete for now (T2.3 + T3.1 are the two standing deferrals). This doc drives Tier 3 (§3/§5/§6/§7
below are the live parts — everything above §3 is background).

- **Tier 1** (merged #1185 + #1188 → promotion #1190): T1.2/T1.3/T1.4 (structured disposition,
  one-step next action, callback time + timezone) and T1.1/T1.5 (`v_call_queue` / `v_overdue_actions`
  routes, score-ordered "Work the queue" with auto-advance, score/decile/vendor-failing + `tel:` +
  `phone_type` + business-hours on the card). §5 Q1 + Q2 answered.
- **Tier 2** (merged #1191 → squash `1b1cd37`): T2.1 (cadence "attempt N of 5 · last: …" on
  queue/board cards + drawer), T2.2 (caller scoreboard — per-caller card **and** team leaderboard,
  Today/7d/30d, `GET /outreach/scoreboard`), T2.4 (board source/overdue filters + sort control),
  T2.5 (link a manual/inbound lead to an already-scanned prospect, the light no-spend path,
  `POST /outreach/leads/{id}/link-prospect`). Migration `20260917140000_cadence_and_scoreboard.sql`
  applied live (`v_lead_cadence` + cadence columns on the two queue views + the
  `outreach_caller_scoreboard(since)` function). §5 Q3 + Q5 answered.
- **T2.3 DEFERRED** (owner ruling 2026-09-17: solo caller) — `owner_id` stays backend-only, no
  owner-assignment UI, no per-owner RLS until the CRM goes multi-user. Design the isolation model
  *before* a second caller, not after (`crm-layer-spec.md` §8a).

**Sibling docs:** `crm-layer-spec.md` (the data model — authoritative), `START-HERE.md` (phases),
`../CLAUDE.md` (invariants). This doc does not restate them; it points at the gap between the CRM
*backbone* (robust) and the caller *cockpit* (thin).

---

## 1. The one-line problem

The data model is a genuinely good CRM. The **UI is a lead tracker, not a calling tool.** A caller
today gets a kanban board → click a card → a drawer with a stage dropdown, a **free-text**
disposition box, a date-only next-action field, and a notes field. The scoring model — the whole
reason to call one prospect before another — **never reaches the person dialing.**

The highest-leverage fixes are small because the database is already ahead of the UI (see §4).

---

## 2. Verified current state (with evidence)

### What exists and is strong — do not rebuild
- **"Why call?" call hook** — `writer/platform-api/services/outreach_call_hook.py` +
  `outreach_justification.py`. Deterministic, fact-grounded, loss-framed opener with a regex
  fabrication guard (no invented $/lead-counts/competitor names) and a deterministic fallback.
  Surfaced behind the "Why call?" toggle in the drawer.
- **Suppression / DNC** — hard upstream gate, `scope='all'` covers phone, never deleted, shown on
  card + drawer (`OutreachLeads.tsx`, `crm-layer-spec.md` §4).
- **Model/workflow split** — `outcome` (append-mostly, outbound-only modelling substrate) vs `lead`
  (freely mutable workflow); `touch` authoritative for "a contact happened"; `lost_reason`
  DB-enforced (`crm-layer-spec.md` §2, §3).
- **Enrichment / contacts** — per-lead contacts wired into the drawer (`Enrichment.tsx`
  `LeadContacts`); `leads_n_contacts` returns emails/phones/socials + decision-maker names where
  they exist.

### The caller-facing UI as built
- `frontend/src/pages/OutreachLeads.tsx` — kanban board (cards grouped client-side by stage) +
  right-side `LeadDrawer`. Route registered at `frontend/src/App.tsx:116` (`/outreach/leads`).
- The board fetches `/outreach/leads?limit=200&search=…` only — **no stage/owner/overdue filter,
  no sort control** (`OutreachLeads.tsx:96`).
- Leads come back ordered `created_at DESC` (`services/outreach.py` `list_leads`, ~line 502) —
  **newest-first, not best-first or most-overdue-first.**
- Disposition is a free-text `<input placeholder="Disposition (e.g. voicemail)">`
  (`OutreachLeads.tsx:443`), passed through as `Optional[str]` (`record_touch`,
  `services/outreach.py:3001`; `build_touch_row`, `outreach_emit.py`).
- `next_action_due` is **date-only** (`crm-layer-spec.md:73`). No time, no timezone.
- Score / decile / vendor-failing flag appear **nowhere** on the card or drawer.

### Spec'd but not surfaced
- `v_call_queue` and `v_overdue_actions` are defined in `crm-layer-spec.md` §6 — "today's call
  list, phone track, ready to dial, ordered by due-date then score, hook pre-rendered." **Neither
  is exposed as an API route** (`routers/outreach.py` has no call-queue route). `list_leads` has an
  `overdue` param (`services/outreach.py:490`) the UI never sends.
- `POST /outreach/prospects/{id}/promote` exists (`routers/outreach.py:371`) — turns an inbound/
  manual lead into a scanned prospect — but is **not wired into the drawer.**

---

## 3. Prioritized workstreams

Ordered by (impact ÷ effort). Each carries evidence, whether it needs a migration, and acceptance.

### TIER 1 — cheap, high-impact (the daily experience)

**T1.1 — Score-ordered "Work the queue" view.** ✅ **BUILT (PR #1188).** *The single biggest miss.*
- Problem: caller works newest-first; the scoring model is invisible to them.
- Build: expose `v_call_queue` (+ `v_overdue_actions`) as read routes; add a list view
  (alternative to the board) sorted by due-date-then-score, showing name · phone · score/decile ·
  next-action · last-disposition, with **auto-advance to the next lead** after a disposition is
  logged. The hook renders inline.
- Migration: **none** — views are spec'd (`crm-layer-spec.md` §6), just unbuilt as routes.
- Acceptance: a caller can open one screen, see the top-priority uncalled/overdue lead, dial,
  disposition, and land on the next without hunting the board.
- **As built (PR #1188):** `v_call_queue` + `v_overdue_actions` are real views exposed at
  `GET /outreach/call-queue` and `GET /outreach/overdue-actions`; "Work the queue" is the default
  view on `/outreach/leads` (Board toggle beside it) and auto-advances after a disposition. Two
  deliberate corrections to the spec §6 SQL, forced by the live schema (see the migration header
  + DECISIONS 2026-09-17): score/decile/pitch come from `v_prospect_ranked` (not the spec's
  `pass=2/model=value` join, which returns null because Stage 1 scores phone at pass 1), and the
  suppression gate is `lead.suppressed_at` (the live `suppression` table has no `prospect_id`).

**T1.2 — Structured disposition enum.** ✅ **BUILT (PR #1185).** *Mirror the `lost_reason` treatment.*
- Problem: free text → no connect-rate reporting, no automation, inconsistent data on the field
  generated 50×/day.
- Build: a fixed value set — `no_answer, voicemail_left, gatekeeper, wrong_number, bad_number,
  dm_reached, not_interested, callback_requested, meeting_booked, dnc` (final list = owner
  decision, §5). Replace the free-text input with a select; keep the note field for prose.
- Migration: the `touch.disposition` **column already exists** (free text). Optional: add a CHECK
  constraint. Mostly a UI + value-set change.
- Acceptance: dispositions are pickable; a scoreboard can count them (T2.2).

**T1.3 — Disposition → next action, in one step.** ✅ **BUILT (PR #1185).**
- Problem: logging a call and setting the callback are separate manual edits.
- Build: `callback_requested` (and `dm_reached`) reveals a date(+time) field inline; one save
  writes the touch *and* sets `next_action` / `next_action_due`. `dnc` offers a one-click
  suppression write.
- Migration: none (unless T1.4 time component is included).
- Acceptance: booking a callback is one action from the disposition.

**T1.4 — Callback time + timezone.** ✅ **BUILT (PR #1185).**
- Problem: `next_action_due` is date-only; callers dial across timezones (LA/KC/…) with no
  business-hours signal.
- Build: add a time component; derive the prospect's timezone from its address/submarket (or the
  already-present enrichment data) and show a "local time / in business hours" indicator on the
  card and queue.
- Migration: **likely needed** — `next_action_due` is `date`; adding time = a new `timestamptz`
  column (or a companion `next_action_at`). Owner decision on shape (§5).
- Acceptance: "Tuesday 2pm their time" is representable and the queue respects it.

**T1.5 — Surface score + signals + `tel:` on the card.** ✅ **BUILT (PR #1188).**
- Problem: no triage signal; phone isn't even a link.
- Build: show score/decile and the vendor-failing/pain flag on the card and drawer (read from
  `v_prospect_ranked` / `v_prospect_placeholder_score`); make phone a `tel:` link; show `phone_type`
  (mobile vs landline — **already stored**, §4).
- Migration: none.
- Acceptance: a caller can eyeball priority and click-to-dial from the OS.

### TIER 2 — medium (management + throughput)

- **T2.1 — Cadence on the card.** ✅ **BUILT (this session).** Shows "attempt N of 5 · last:
  voicemail" on the queue card, the board card, and the drawer's Log-contact section. A per-lead
  rollup view `v_lead_cadence` (attempt_count / last_touched_at / last_disposition) is joined onto
  the queue/overdue views and read per-page for the board (one batched `.in_()`, never per-lead).
  The "/5" is `outreach_touches_per_sequence` (config, mirrored as a frontend constant). Distinct
  from the outbound-only `outcome` rollup, so an inbound lead shows cadence too. Migration:
  `20260917140000` (view only). **As decided, `touch_count`/`touch_number` were NOT the source —
  a direct `count(*)` over `touch` per lead is authoritative for all sources, where the `outcome`
  rollup is outbound-only.**
- **T2.2 — Caller scoreboard.** ✅ **BUILT (this session).** A third view ("Scoreboard") beside
  Work-the-queue / Board: a per-caller "your numbers" card (dials / conversations / connect rate /
  callbacks / DMs reached / voicemails / not-interested / DNC) AND a team leaderboard (owner ruling
  §5 Q5: **both**), over a Today / 7-day / 30-day window. Aggregated server-side by
  `outreach_caller_scoreboard(since)` (one row per `actor_id`, so the read never truncates on touch
  volume); connect_rate computed app-side; caller names resolved best-effort from AR-Internal-Tools
  `profiles` (a different project). **No "meetings booked" metric** — there is no such disposition
  in the set, and inferring one from stage would mix the outbound-only touch substrate with
  workflow state. `GET /outreach/scoreboard?days=N`. Migration: `20260917140000` (function only).
- **T2.3 — Owner assignment + "my leads".** ⏸ **DEFERRED (owner ruling 2026-09-17: solo caller).**
  `owner_id` stays backend-only (create / `list_leads` filter / patch all still work); no
  owner-assignment UI, no RLS this tier. Revisit when the CRM goes multi-user — adding RLS to the
  live table then is where disclosure bugs come from (`crm-layer-spec.md` §8a), so design it before
  a second caller, not after.
- **T2.4 — Board/queue filters.** ✅ **BUILT (this session).** The board gained a filter bar:
  **source** dropdown, **overdue-only** toggle, and a **sort** control (Newest / Oldest / Recently
  updated / Due soonest / Company A–Z) — the sort maps to a backend whitelist (`_LEAD_SORTS`;
  `due`/`name` are nulls-last). Stage isn't a board filter (the columns already are stages) and
  owner isn't (solo caller, T2.3); both params stay exposed on `GET /outreach/leads` for later.
  Migration: none.
- **T2.5 — Link a manual/inbound lead to a scanned prospect.** ✅ **BUILT (this session, light-link
  path — owner ruling 2026-09-17).** *The handoff's original framing was inaccurate:* both things it
  named were already wired — the prospect→lead `/promote` lives on the prospect **coverage table**
  (`Outreach.tsx` "Send to CRM"), and enrich (`LeadContacts`) was already in the drawer for
  prospect-linked leads. The genuine gap was the reverse: a **manual/inbound lead has no
  `prospect_id`**, so its drawer shows no hook/report/heatmap/enrich, and there was **no route** to
  attach one (and `prospect_id` is deliberately immutable). Built as a **pure link, no spend**: a new
  `POST /outreach/leads/{id}/link-prospect` (`link_lead_prospect`) sets `prospect_id` from null when
  the business was **already scanned** — reusing the existing prospect search (`GET
  /outreach/prospects?search=`) in a new drawer control (`LinkProspect`). No paid call, no ingest
  (the "ingestion is the Railway job's business" invariant is untouched — a business with no scan
  simply isn't found to link). Guards: refuses a lead already linked (re-pointing the model's join
  isn't a caller action; same id → idempotent), a prospect another live lead owns
  (`prospect_already_linked`, also the graceful map for the trashed-lead `UNIQUE(prospect_id,source)`
  collision), a missing/soft-deleted lead, a missing prospect. `source` is left as-is, so a linked
  `manual` lead gains the audit surface but never enters the outbound-only `outcome` substrate.
  Staff-gated. Migration: none. **The heavier lead→prospect ingest (single-business lookup + scan)
  was NOT built** — deferred as a separate paid feature if ever wanted.

### TIER 3 — bigger bets (← THE CURRENT WORK ORDER)

Two independent tracks. **T3.2 has no external dependency and is the recommended first build;**
**T3.1 is blocked on the §5 Q4 vendor decision** (and carries provider lead time), so it should not
start until the owner picks Twilio vs Aircall vs none-for-now.

- **T3.1 — Click-to-call / softphone.** ⏸ **DEFERRED (owner ruling 2026-09-17, §5 Q4: none for
  now).** Not built — no vendor, no code, no spend; revisit when call volume justifies the per-minute
  cost + provider setup. The scope below is the record for that future build. Dial from the
  queue/drawer through a telephony provider
  (Twilio Voice / Aircall), with **call recording → an automatic `touch`** (so a dialed call logs
  itself instead of relying on the caller to hit "Log call"). **Blocked on §5 Q4** (vendor). Real
  scope beyond a button: number provisioning + caller-ID / local-presence, a webhook that maps a
  completed call back to its lead and writes the `touch` (channel `phone`, `actor_id` = the caller),
  recording storage + a link on the timeline, and cost/consent handling. Keep the invariants: the
  auto-`touch` is still authoritative for "a contact happened" (don't also write a `call` activity —
  that kind doesn't exist, by design); a recording note is a `call_note` carrying the `touch_id`
  (the only activity kind allowed to). Migration: likely a `call`/recording table + a `touch`
  provenance column. **Confirm the outreach `tick`/signed-order + per-user-budget model** if the
  provider bills per minute — a paid dial should be as auditable as a scan.
- **T3.2 — Script + objection/rebuttal library.** ✅ **BUILT (this session, draft PR).** The call
  hook is the opener only (one line); there is now a talk track past it plus rebuttals to what a
  local-business owner says back, **fed by the report data the pipeline already produces**
  (competitor names, the MAPS/ORGANIC/paid-placement gaps, review deltas) so a rebuttal names the
  prospect's real situation. Same discipline as the hook: **deterministic + fact-grounded, never a
  fabricated competitor/number** (outreach DECISIONS 2026-08-08 design-fork ruling). **No vendor
  dependency. No migration** (renders from the existing report/justification).
  - **As built:** pure assembler `writer/platform-api/services/outreach_script.py` —
    `build_script(justification, signals)` produces a 5-part talk track (open → discovery →
    evidence → value → close) + a fixed, ordered 9-objection rebuttal library
    (`already_ranking`/`has_agency`/`already_ads`/`not_interested`/`too_busy`/`price`/`email_me`/
    `tried_before`/`referral_only`). It **re-grounds nothing**: the opener is `justification.hook`
    verbatim (shares the "Why call?" opener + its cached loss-framed phrasing pass), the evidence
    section is its `talking_points` verbatim, the value line is the deterministic `valuation.line`.
    Each grounded rebuttal uses ONLY numbers/names in the facts it was handed and carries those
    `facts` (replayability); an absent fact degrades to a generic-but-honest line (never omitted,
    never fabricated, never a promise). The paid `conversion_tag` claim is evidence-gated (I-099 —
    a site tag never asserts a keyword bid).
  - **I/O + route:** `services/outreach.prospect_script` reuses `prospect_report` as the single
    source (so it can't disagree with the report/hook); `GET /outreach/prospects/{id}/script`.
  - **UI:** `frontend/src/components/outreach/Script.tsx` + a "Script & rebuttals" toggle beside
    "Why call?" in the lead drawer (`OutreachLeads.tsx`). Rebuttals are a click-to-expand accordion
    with a "grounded" badge.
  - **Tests:** `tests/test_outreach_script.py` (17, pure) — opener/evidence/value passthrough, the
    fixed rebuttal set + ordering, deficit/competitor/review/organic grounding, the conversion-tag
    evidence gate, and the unmeasured generic-fallback path. ruff + tsc + eslint + build all clean.

---

## 4. What the next session must know (traps + head-starts)

- **The DB is ahead of the UI.** Already present, just unsurfaced: `touch.disposition`,
  `touch.touch_number`, `touch.sequence_version`, `prospect.phone_type` +
  `prospect_enrichment.phone_type` (mobile/landline/voip), `lead.owner_id`, the `list_leads`
  overdue/stage/source/owner filters, and the `v_call_queue`/`v_overdue_actions` **spec** (§6).
  Most of Tier 1 is UI + a value-set, not migrations.
- **The call hook / report / contacts all require `prospect_id`.** A `manual`/`inbound_call` lead
  has none unless it's linked (T2.5 `POST /outreach/leads/{id}/link-prospect`, built) or promoted
  from a scan — an unlinked lead is a bare card with no report behind it. **This matters for T3.2:**
  the script/rebuttal library is fed by the report, so an unlinked lead has nothing to feed it (fall
  back to a generic script, or prompt the caller to link a scanned prospect first).
- **Two databases.** Outreach lives in the **Outreacher** Supabase project
  (`fkwhgvcggvsricuinuqy`); migrations go in `outreach/migrations/`, **never**
  `writer/supabase/migrations/`. The API/UI live in `writer/platform-api` + `frontend/` (suite
  module ruling, `../CLAUDE.md`).
- **Invariants that constrain this work** (`../CLAUDE.md`, `crm-layer-spec.md`):
  - `outcome` is the modelling substrate — workflow/UI changes never mutate it; it is outbound-only.
  - `touch` is authoritative for "a contact happened"; `lead_activity` is commentary. Don't
    duplicate. A `call_note` is the only activity kind that may carry a `touch_id`.
  - `lead_activity` is append-only; corrections are new rows. Stage/reassignment rows are written
    by the DB trigger (`lead_log_changes`), not the app — don't double-write.
  - Suppression is a hard gate, never deleted, `scope='all'` covers phone.
  - No prospect-facing asset without explicit human approval.
- **`lost_reason` is the template for T1.2** — a DB-enforced enum captured at the moment of loss.
  Disposition should get the same treatment.

---

## 5. Open decisions for the owner (Q1–Q3, Q5 answered; **Q4 is the live Tier-3 blocker**)

1. ~~**Disposition value set**~~ — **ANSWERED (owner, 2026-09-17): the full set** — phone:
   `no_answer, voicemail, busy, wrong_number, gatekeeper, connected, decision_maker,
   callback_requested, not_interested, do_not_call`; email: `sent, bounced, replied, auto_reply,
   unsubscribe`. Kept app-level (a select + `GET /outreach/dispositions`), NOT a DB CHECK, so the
   vocabulary grows with a deploy not a migration (the column stays free text). Built in PR #1185.
2. ~~**Callback time shape**~~ — **ANSWERED (owner, 2026-09-17): a separate `next_action_at`**
   (timestamptz) + `next_action_tz`, additive, leaving `next_action_due` (date) as the unchanged
   day-level overdue/queue driver — NOT a `timestamptz` migration of `next_action_due` (that would
   change "overdue" semantics + break the `< current_date` readers). Timezone is **stored** per
   lead (`next_action_tz`), defaulted from a longitude guess then a config default, caller-editable
   — not derived at display (no lat/lng→tz lib exists in platform-api). Built in PR #1185.
3. ~~**Multi-user / RLS**~~ (T2.3) — **ANSWERED (owner, 2026-09-17): solo caller.** T2.3 deferred;
   `owner_id` stays backend-only, no owner-assignment UI, no RLS. Revisit at multi-user (design the
   isolation model before a second caller — `crm-layer-spec.md` §8a).
4. ~~**Click-to-call vendor**~~ (T3.1) — **ANSWERED (owner, 2026-09-17): none for now.** No
   telephony provider yet — callers keep dialing via the `tel:` link and hitting "Log contact".
   **T3.1 is not built** (no code, no provider account, no per-minute billing, no webhook receiver).
   Revisit when call volume justifies the setup + per-minute cost; when picked (Twilio Voice vs
   Aircall), the build is: dial from the queue/drawer, a completed-call webhook → an automatic
   `touch` (channel `phone`, actor = the caller) mapping the call back to its lead, recording as a
   `call_note` carrying the `touch_id`, and the paid dial fit into the signed-order/per-user-budget
   model. The invariants in §3's T3.1 bullet still govern that future build.
5. ~~**Scoreboard scope**~~ (T2.2) — **ANSWERED (owner, 2026-09-17): both** — a per-caller "your
   numbers" card AND a team leaderboard. Built in #1191.

---

## 6. Suggested build order

1. ~~Owner answers §5 Q1 (disposition set) and Q2 (callback shape).~~ ✅ done (2026-09-17).
2. ~~**T1.2 + T1.3 + T1.4** together (one coherent "log a call properly" change).~~ ✅ PR #1185.
3. ~~**T1.1** (queue view) + **T1.5** (score/tel on card) — the triage layer.~~ ✅ PR #1188.
4. ~~**T2.1 / T2.2 / T2.4** (cadence, scoreboard, filters) — read-only, low risk.~~ ✅ this session.
5. ~~**T2.5** (link a manual lead to a scanned prospect, light path).~~ ✅ #1191. **T2.3 deferred**
   — solo caller (§5 Q3). **Tiers 1 + 2 complete** except deferred T2.3.
6. **Tier 3, as separately-scoped projects:**
   a. ~~**T3.2** (script + objection/rebuttal library) first — no vendor dependency; reuses the
      existing report/justification assembly; deterministic + fact-grounded.~~ ✅ BUILT (this
      session, draft PR).
   b. ~~**T3.1** (click-to-call + auto-`touch`)~~ **DEFERRED — owner ruled §5 Q4 "none for now"
      (2026-09-17).** Not built. Revisit when call volume justifies a telephony vendor; the build
      scope + invariants are preserved in §3's T3.1 bullet.

Ship each tier behind the existing `/outreach/leads` surface; don't gate one on the next.

---

## 7. Kickoff prompt for the next session (Tier 3)

> Tiers 1 + 2 are merged. Paste the fenced block below verbatim to start the Tier-3 build session.

```
Read outreach/docs/cold-caller-crm-handoff.md first — it's the work order (Tiers 1 + 2 are BUILT and
merged; Tier 3 §3 is the live scope). Also read ../CLAUDE.md invariants, outreach/DECISIONS.md (esp.
the 2026-08-08 design-fork ruling: prospect-facing text is deterministic + fact-grounded, never a
fabricated competitor/number), and skim services/outreach_justification.py + outreach_report.py (the
call-hook / report assembly Tier 3 builds on).

We're building Tier 3 of the cold-caller CRM surface of the Outreach module (NOT the scanning/scoring
pipeline). Two independent tracks:

  T3.2 — Script + objection/rebuttal library. FIRST (no vendor dependency). The call hook is only the
  opener; there's no talk track past line one. Build a per-call script + rebuttals FED BY the report
  data we already produce (competitor names, the MAPS/ORGANIC/paid-placement gaps, review deltas) so
  a rebuttal names the prospect's real situation. Reuse outreach_justification.py / outreach_report.py
  — deterministic + fact-grounded, never an LLM guess, never a fabricated fact/competitor/number
  (same discipline as the hook + heatmap). Surface it in the lead drawer beside "Why call?". v1
  likely needs NO migration (render from the existing report); persist templates only if we decide to.

  T3.1 — Click-to-call / softphone + auto-touch. DO NOT START until I answer §5 Q4 (Twilio vs Aircall
  vs none-for-now) — ask me first. When unblocked: dial from the queue/drawer through the chosen
  provider, and on call completion write an AUTOMATIC `touch` (channel phone, actor = the caller) via
  a provider webhook that maps the call back to its lead. Keep the invariants: the touch is
  authoritative (do NOT also write a `call` activity — that kind doesn't exist); a recording note is a
  `call_note` carrying the touch_id. If it bills per minute, fit the paid dial into the outreach
  signed-order + per-user-budget model so a dial is as auditable as a scan.

Remember: Outreach uses the Outreacher Supabase project (fkwhgvcggvsricuinuqy) — migrations go in
outreach/migrations/, NEVER writer/supabase/migrations/, and are applied live via the Supabase MCP.
The API/UI live in writer/platform-api + frontend/. Keep the outcome/touch/lead_activity invariants
intact (outcome is outbound-only; touch is authoritative; lead_activity is append-only, DB-trigger
owns stage/owner rows). Ship each track as its own PR (draft) to main; run ruff + the outreach pytest
suite + tsc/eslint/build before pushing; update this handoff's status and check off items as you land
them. T2.3 (owner-assignment UI + per-owner RLS) stays deferred — solo caller.
```
