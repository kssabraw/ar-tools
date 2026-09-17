# Cold-Caller CRM — Improvement Handoff

**Scope:** the caller-facing CRM surface of the Outreach module — the daily tool a cold caller uses
to work leads, dial, disposition, and book callbacks. NOT the scanning/scoring pipeline (that is
sound; see `START-HERE.md`).

**Status:** **Tier 1 BUILT (2026-09-17).** T1.2 + T1.3 + T1.4 landed in PR #1185 (structured
disposition, one-step next action, callback time + timezone); T1.1 + T1.5 landed in PR #1188
(v_call_queue / v_overdue_actions routes, score-ordered "Work the queue" list with auto-advance,
score/decile/vendor-failing + tel: + phone_type + business-hours on the card). Both migrations
applied live to the Outreacher project. §5 Q1 + Q2 answered (owner, 2026-09-17). **Tier 2 and
Tier 3 remain** — this doc stays the work order for them. Analysis for those is unchanged below.

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

- **T2.1 — Cadence on the card.** Show "attempt N/5 · last: voicemail Tue" from `touch_count` /
  `touch_number` / last disposition (`touches_per_sequence` = 5 is configured;
  `touch.touch_number`/`sequence_version` columns exist). Migration: none.
- **T2.2 — Caller scoreboard.** Dials today / conversations / connect rate / callbacks / meetings
  booked, aggregated from touches+dispositions. Needs T1.2 to be meaningful. Migration: none.
- **T2.3 — Owner assignment + "my leads".** `owner_id` is fully backend-wired (create, `list_leads`
  filter, patch) but has **no UI** and the DB is service-role-only with no RLS (`../CLAUDE.md`
  I-040). Blocked on the multi-user decision (§5).
- **T2.4 — Board/queue filters.** Expose the `list_leads` filters already there (stage/source/
  owner/overdue) + a sort control. Migration: none.
- **T2.5 — Wire `/promote` + enrich into the drawer.** Let a caller turn an inbound/manual lead
  into a scanned prospect (→ gains the hook + report + heatmap) from where they work. Route exists;
  UI doesn't. Migration: none.

### TIER 3 — bigger bets (defer unless prioritized)

- **T3.1 — Click-to-call / softphone** (Twilio/Aircall) with call recording → auto-`touch`. Vendor
  decision required (§5). Calendar lead time.
- **T3.2 — Script + objection/rebuttal library**, ideally fed by report data (competitor names,
  gaps) for dynamic rebuttals. The hook is the opener only; there is no talk track past line one.

---

## 4. What the next session must know (traps + head-starts)

- **The DB is ahead of the UI.** Already present, just unsurfaced: `touch.disposition`,
  `touch.touch_number`, `touch.sequence_version`, `prospect.phone_type` +
  `prospect_enrichment.phone_type` (mobile/landline/voip), `lead.owner_id`, the `list_leads`
  overdue/stage/source/owner filters, and the `v_call_queue`/`v_overdue_actions` **spec** (§6).
  Most of Tier 1 is UI + a value-set, not migrations.
- **The call hook / report / contacts all require `prospect_id`.** A `manual`/`inbound_call` lead
  has none until promoted, so it's a bare card — this is why T2.5 (wire `/promote`) matters.
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

## 5. Open decisions for the owner (get these before/while building Tier 1)

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
3. **Multi-user / RLS** (T2.3) — is this a solo caller or a team? If a team, the owner-assignment UI
   and per-owner RLS need designing now (adding RLS to a live table later is where disclosure bugs
   come from — `crm-layer-spec.md` §8a already flags this).
4. **Click-to-call vendor** (T3.1) — Twilio vs Aircall vs none-for-now. Has calendar lead time
   (number provisioning, caller-ID/local-presence).
5. **Scoreboard scope** (T2.2) — per-caller only, or team leaderboard?

---

## 6. Suggested build order

1. ~~Owner answers §5 Q1 (disposition set) and Q2 (callback shape).~~ ✅ done (2026-09-17).
2. ~~**T1.2 + T1.3 + T1.4** together (one coherent "log a call properly" change).~~ ✅ PR #1185.
3. ~~**T1.1** (queue view) + **T1.5** (score/tel on card) — the triage layer.~~ ✅ PR #1188.
4. **← NEXT: T2.1 / T2.2 / T2.4** (cadence, scoreboard, filters) — read-only, low risk.
5. **T2.5** then **T2.3** (needs the RLS decision).
6. Tier 3 as separately-scoped projects.

Ship T1 behind the existing `/outreach/leads` surface; don't gate it on Tier 2/3.

---

## 7. Kickoff prompt for the next session

> See the fenced block below — paste it verbatim to start the build session.

```
Read outreach/docs/cold-caller-crm-handoff.md first — it's the work order. Also read
outreach/docs/crm-layer-spec.md §6 (v_call_queue / v_overdue_actions) and ../CLAUDE.md invariants.

We're improving the cold-caller CRM surface of the Outreach module (NOT the scanning/scoring
pipeline). The data model is solid; the caller UI is thin. Work Tier 1 from the handoff.

Before writing code, ask me the §5 open decisions that block Tier 1 — specifically:
  (1) confirm the disposition enum values, and
  (2) how to represent a callback time + timezone (migrate next_action_due to timestamptz, or add
      next_action_at? derive timezone from address/submarket or store it?).

Then implement, in this order, each as its own PR against branch claude/cool-tesla-tlgbrk:
  1. T1.2 + T1.3 + T1.4 — structured disposition enum, disposition→next-action in one step,
     callback time + timezone with a business-hours indicator.
  2. T1.1 + T1.5 — expose v_call_queue / v_overdue_actions as routes; build a score-ordered
     "Work the queue" list view with auto-advance; surface score/decile/vendor-failing + a tel:
     link + phone_type on the card.

Remember: Outreach uses the Outreacher Supabase project — migrations go in outreach/migrations/,
never writer/supabase/migrations/. The API/UI live in writer/platform-api + frontend/. Most of
Tier 1 needs NO migration (touch.disposition, phone_type, owner_id, and the list_leads filters
already exist; the queue views are spec'd but unbuilt as routes) — the likely exception is the
callback-time column (§5 Q2). Keep the outcome/touch/lead_activity invariants intact. Update the
handoff's status and check off items as you land them.
```
