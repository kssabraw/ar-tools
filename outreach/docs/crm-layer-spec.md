# CRM Layer Spec v0.5

**Module:** `outreach-pipeline` (AR Tools)
**Siblings:** `PRD-prospect-pipeline.md`, `scoring-spec.md`, `storage-retention-spec.md`, `reporting-layer-spec.md`
**Scope:** Pre-client only — from scored prospect to signed or lost. Client management is out of scope.

---

## 1. Why this is small

The existing data model already carries most of a CRM: `prospect` is the record, `outcome`
tracks contacted/replied/closed/churned with retainer, `touch` logs individual sends and dials,
`conflict_check` and `audit_approval` carry reviewer decisions, `asset_engagement` records what
they looked at.

Five things are missing, and they are what make a database a CRM: **pipeline stage, owner,
notes, next action, and lost reason.**

---

## 2. Governing principle: separate the model record from the workflow record

`outcome` is the learning substrate. Every coefficient in the scoring spec will eventually be fit
against it, and it must stay clean, append-mostly, and free of workflow churn.

Workflow is different: stages get corrected, owners change, someone drags a card back a column.
Mixing the two means a salesperson correcting a mistake silently alters training data.

| Table | Purpose | Mutability |
|---|---|---|
| `outcome` | Modeling record — timestamps for contacted, replied, closed, churned | Append-mostly; corrections logged |
| `lead` | Workflow record — stage, owner, next action, lost reason | Freely mutable |

- Stage transitions that correspond to modelled events MUST write the matching `outcome`
  timestamp — but the reverse does not hold. Workflow-only stages (`in_conversation`,
  `nurture`) have no `outcome` field and MUST NOT invent one.
- Analysts read `outcome`. Operators read `lead`. Neither needs to reason about the other.

---

## 3. Schema

```sql
create type lead_stage as enum (
  'new', 'contacted', 'replied', 'in_conversation', 'won', 'lost', 'nurture'
);

create type lost_reason as enum (
  'no_response', 'not_interested', 'no_budget', 'has_agency', 'timing',
  'went_elsewhere', 'disqualified', 'unreachable', 'opted_out'
);

create type lead_source as enum (
  'outbound_scan', 'inbound_form', 'inbound_call', 'referral', 'manual', 'partner'
);

create table lead (
  id                uuid primary key default gen_random_uuid(),
  source            lead_source not null,
  prospect_id       uuid unique references prospect(id) on delete cascade,
  -- Contact fields for leads with no GBP listing behind them.
  -- When prospect_id is set, prospect data is authoritative and these stay null.
  contact_name      text,
  company_name      text,
  email             text,
  phone             text,
  notes_intake      text,
  stage             lead_stage not null default 'new',
  owner_id          uuid references auth.users(id),
  next_action       text,
  next_action_due   date,
  lost_reason       lost_reason,
  lost_to           text,                    -- named competitor, where known
  stage_changed_at  timestamptz not null default now(),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  constraint lost_requires_reason
    check (stage <> 'lost' or lost_reason is not null),
  constraint outbound_requires_prospect
    check (source <> 'outbound_scan' or prospect_id is not null),
  constraint non_prospect_needs_identity
    check (prospect_id is not null or company_name is not null)
);
create index on lead (stage, owner_id);
create index on lead (next_action_due) where next_action_due is not null;

create table lead_activity (
  id           bigserial primary key,
  lead_id      uuid not null references lead(id) on delete cascade,
  occurred_at  timestamptz not null default now(),
  actor        text not null,               -- staff identifier, or 'system'
  kind         text not null check (kind in
                 ('note','call_note','email_reply','meeting',
                  'proposal','stage_change','asset_viewed','system')),
  touch_id     bigint references touch(id),   -- links commentary to the send it concerns
  body         text,
  metadata     jsonb not null default '{}',
  from_stage   lead_stage,
  to_stage     lead_stage
);
create index on lead_activity (prospect_id, occurred_at desc);
create index on lead_activity (kind, occurred_at desc);

create table suppression (
  id            bigserial primary key,
  prospect_id   uuid references prospect(id) on delete set null,
  email         text,
  phone         text,
  scope         text not null check (scope in ('email','phone','all')),
  reason        text not null,
  source        text not null,               -- 'esp_unsubscribe','verbal','manual','bounce'
  suppressed_at timestamptz not null default now()
);
create unique index on suppression (lower(email)) where email is not null;
create unique index on suppression (phone) where phone is not null;
```

- `lost_requires_reason` is enforced at the database level deliberately. A lost lead without a
  reason is a lost label, and labels are the point (§5).
- `lead_activity` is append-only. Corrections are new rows, never edits.
- **`touch` is authoritative for "a contact attempt happened"; `lead_activity` carries the human
  commentary about it.** They MUST NOT duplicate. `email_sent` and `call` were removed as activity
  kinds — a dial writes a `touch` row, and what was said writes a `call_note` referencing it via
  `touch_id`. The activity timeline is a view that unions both, so operators see one stream while
  the modeling substrate stays clean.
- Stage changes MUST write a `lead_activity` row with `from_stage`/`to_stage`. That gives stage
  history without a separate table.

---

## 3a. Lead sources — one pipeline, two origins

**Scope: leads only.** Client management after `won` remains out of scope and hands off to AR's
existing systems.

| Source | `prospect_id` | Gets scored / audited | Feeds the model |
|---|---|---|---|
| `outbound_scan` | required | yes, automatically | **yes** |
| `inbound_form`, `inbound_call` | optional | only if looked up | **no** |
| `referral`, `partner`, `manual` | optional | only if looked up | **no** |

### The constraint that must not bend

**`outcome` stays strictly outbound-sourced.** It is the substrate every scoring coefficient is
fit against. Inbound and referral leads converted for entirely different reasons — they came to
you — so pooling them would inflate every coefficient's apparent effect. This is the same
treatment bootstrap contacts already receive.

- `outcome` rows MUST exist only for leads with `source = 'outbound_scan'`.
- **Business reporting reads `lead.stage`; model fitting reads `outcome`.** Both origins appear in
  pipeline views and forecasts; only outbound appears in refits.

### Promoting a non-outbound lead

An inbound lead is almost always a local business with a GBP listing, so it can be promoted into
a full prospect and gain everything the pipeline offers.

- **Single-business lookup** (Phase 5): given a name and city, run a targeted Outscraper query for
  that one record — about a third of a cent — creating a real `prospect` with a real `place_id`
  and `raw` payload, then link it via `prospect_id`.
- Never fabricate a `place_id`. Grid results join on it; an invented one silently matches nothing,
  leaving a prospect that can never be scored or audited.
- If the business sits outside a scanned market, an **ad-hoc submarket** can be created and
  scanned for ~$0.05, which makes an audit possible. That turns inbound into a strength: their
  heatmap is ready before the first call.
- Promotion does **not** make the lead outbound. `source` is immutable, and `outcome` still must
  not be written for it.

---

## 4. Suppression is a hard gate upstream of everything

- Suppression MUST be checked **before scoring, enrichment, or any contact**, not at send time.
  Enriching a suppressed prospect wastes money; scoring one wastes a slot attempt.
- `scope = 'all'` MUST suppress the phone track too. "Never contact us again" is not an email
  preference.
- Suppression records MUST NOT be deleted, ever. Deletion re-opens the prospect on the next
  cycle, which is both a compliance failure and a reputational one.
- ESP unsubscribes MUST sync back within one cycle. A prospect who unsubscribed in the email
  track and then gets a cold call has had the worst possible experience of AR.

---

## 5. Lost reasons are model feedback, not admin

This is the highest-value field in the layer and the one most likely to be skipped.

Each reason is a label that tests a specific coefficient:

| Reason | What it tests |
|---|---|
| `has_agency` | Whether the `likely_represented` penalty (−21) is correctly signed and sized |
| `no_budget` | Whether the money signals actually predict capacity |
| `unreachable` | Whether reachability scoring matches reality |
| `disqualified` | Whether the filter gates are letting bad fits through |
| `not_interested` | Baseline — the residual after the others |
| `went_elsewhere` + `lost_to` | Competitive intensity per market-vertical |

- If `has_agency` losses concentrate among prospects flagged `likely_represented`, the penalty is
  validated. If they concentrate among prospects **not** flagged, the site-signal detection is
  missing agencies and the flag needs work.
- If `disqualified` losses are common, the problem is upstream in §A2 filters, not in scoring.

Lost reasons are captured at the moment a human already knows the answer, cost nothing, and are
unrecoverable afterwards.

---

## 6. Working views

```sql
-- Today's call list: phone track, ready to dial, with the hook already rendered
create view v_call_queue as
select l.id as lead_id, l.prospect_id, coalesce(p.name, l.company_name) as name,
       coalesce(p.phone, l.phone) as phone, p.phone_type, sm.name as submarket,
       ps.score, ps.decile, ps.primary_pitch,
       l.owner_id, l.next_action, l.next_action_due,
       (select body from lead_activity a
         where a.lead_id = l.id and a.kind = 'call_note'
         order by a.occurred_at desc limit 1) as last_call_note
from lead l
left join prospect p        on p.id = l.prospect_id
left join submarket sm      on sm.id = p.submarket_id
left join prospect_score ps on ps.prospect_id = l.prospect_id
                      and ps.pass = 2 and ps.model = 'value' and ps.channel = 'phone'
where l.stage in ('new','contacted','replied','nurture')
  and not exists (select 1 from suppression s
                   where s.prospect_id = l.prospect_id and s.scope in ('phone','all'))
order by coalesce(l.next_action_due, current_date), ps.score desc;

-- Pipeline snapshot
create view v_pipeline as
select l.stage, l.source, l.owner_id, count(*) as leads,
       round(avg(ps.predicted_prob), 3) as avg_predicted_close
from lead l
left join prospect_score ps on ps.prospect_id = l.prospect_id
                          and ps.pass = 2 and ps.model = 'close'
group by l.stage, l.source, l.owner_id;

-- What's overdue
create view v_overdue_actions as
select l.id as lead_id, coalesce(p.name, l.company_name) as name, l.source,
       l.owner_id, l.stage, l.next_action, l.next_action_due,
       current_date - l.next_action_due as days_overdue
from lead l left join prospect p on p.id = l.prospect_id
where l.next_action_due < current_date
  and l.stage not in ('won','lost')
order by l.next_action_due;

-- Model feedback: do lost reasons align with what the score predicted?
create view v_lost_analysis as
select l.lost_reason, ps.decile,
       count(*) as leads,
       count(*) filter (where f.flagged) as flagged_represented
from lead l
join prospect_score ps on ps.prospect_id = l.prospect_id
                      and ps.pass = 2 and ps.model = 'close'
left join lateral (
  select true as flagged
  from jsonb_array_elements(ps.score_factors) x
  where x->>'feature' = 'likely_represented'
) f on true
where l.stage = 'lost'
group by l.lost_reason, ps.decile;
```

---

## 7. ESP boundary — the sender is dumb

State lives in Supabase. The ESP sends and reports; it never holds pipeline state.

Two reasons, and the second is decisive:

1. Outcome data is the learning substrate and must stay queryable alongside `score_factors`.
2. **The phone track has no ESP at all.** Fifty dials a day generates exactly the conversations a
   CRM exists to track, and none of it passes through an email tool. State in the ESP would leave
   half the pipeline homeless.

### Requirements

- Every contact pushed to the ESP MUST carry `prospect_id` in a custom field. That UUID is the
  join key for every event coming back.
- ESP webhooks MUST write to `lead_activity` (`email_sent`, `email_reply`) and set the
  corresponding `outcome` timestamps.
- Unsubscribes MUST write to `suppression` within one cycle.
- **ESP-side optimization MUST be disabled** — send-time optimization, built-in A/B testing, and
  "smart" delivery all introduce variation that was not assigned by the randomizer and cannot be
  observed. Any of them left on confounds the evidence-attribution experiment (PRD §14a).
- Arms MUST be carried as a contact field within one campaign, never as separate lists. Separate
  lists confound the assignment with list-level reputation and timing effects.
- **Reply detection does not come from the ESP.** Replies land in a mailbox, not the platform.
  `outcome.replied_at` requires inbox monitoring or manual logging regardless of vendor.
- Open tracking SHOULD be ignored. Privacy-protection features inflate it badly. Clicks and
  `asset_engagement` views — the latter on AR's own infrastructure via the signed R2 URL — are
  the reliable engagement signals.

> **Vendor caution.** GetResponse's anti-spam policy prohibits purchased and non-opt-in
> addresses, screening is automated and opaque, and suspension can be permanent. Outscraper-derived
> GBP emails fit that profile. Cold B2B email is legal under CAN-SPAM; the restriction here is
> contractual. Purpose-built cold outreach tools sending through owned mailboxes are the lower-risk
> path. Verify before building the integration.

---

## 8. Handoff at close

When `stage` moves to `won`:

- `outcome.closed_at` and `retainer_actual` MUST be set.
- `slot.state` MUST become `filled` with `filled_by_prospect_id` set.
- Scanning MUST continue uninterrupted (PRD §8) — the prospecting series becomes client tracking.
- The `lead` record MUST become read-only. Post-signature relationship management is out of scope
  and belongs in AR's existing client systems.
- A case-study draft MUST be queued for 90 days out (PRD §7).

---

## 8a. Recorded decisions

**Owner — `auth.users` reference, not free text.**
Chosen over text for future-proofing. Two consequences that MUST be honoured now rather than
retrofitted:

- Staff MUST exist as Supabase auth users before leads can be assigned. There is no
  assign-by-typing-a-name path.
- **Write the per-owner RLS policies now, even if every staff member currently sees everything.**
  Adding row-level security to a table already carrying production traffic is where disclosure
  bugs come from. A permissive policy that can be tightened later is safe; no policy is not.

**Nurture re-entry — manual promotion only.**
Automatic re-entry risks re-contacting someone who already declined, which spends the prospect
permanently. `nurture` leads MUST surface in a review queue with the reason they were parked and
the cycles elapsed, and MUST require an explicit action to return to the working queue.

Note this interacts with slot state: a submarket whose only viable prospects are all parked in
`nurture` should register as low-runway in `v_slot_status`, not as available inventory.

**Stage granularity — `qualified` and `proposal` collapsed into `in_conversation`.**
AR's sales cycle is short enough that the distinction was bookkeeping. Collapsing now is free;
collapsing after history accumulates means either rewriting past records or living with two
incompatible stage vocabularies in the same analysis.

Substages, if ever needed, SHOULD be expressed as `lead_activity` rows (`kind = 'proposal'`)
rather than by re-splitting the enum — activity is additive, enum changes are not.

---

## 9. Acceptance criteria

- [ ] `outcome` never mutated by workflow stage changes
- [ ] Workflow-only stages write no `outcome` timestamps
- [ ] Stage changes always write a `lead_activity` row with from/to
- [ ] `lead_activity` append-only; corrections are new rows
- [ ] Lost stage unreachable without a `lost_reason` (DB-enforced)
- [ ] Suppression checked before scoring and enrichment, not at send
- [ ] `scope = 'all'` suppresses phone as well as email
- [ ] Suppression records never deleted
- [ ] ESP unsubscribes synced within one cycle
- [ ] `prospect_id` present on every contact pushed to the ESP
- [ ] ESP send-time optimization and native A/B verified off
- [ ] Arms carried per-contact, never as separate lists
- [ ] Open-rate metrics excluded from all effect estimates
- [ ] Won leads flip the slot, freeze the lead record, and queue a case-study draft
- [ ] Per-owner RLS policies written and tested at launch, however permissive
- [ ] `nurture` leads require explicit promotion; no automatic re-entry
- [ ] Submarkets whose viable prospects are all parked register as low-runway
- [ ] Stage substages expressed as activity rows, never as enum additions

---

## 10. Open decisions

None. All decisions recorded in §8a.

3. ~~**Reply capture mechanism**~~ — **DECIDED: manual logging at launch**, IMAP polling at
   ~30 replies/month. The overdue-action view is the forcing function.
