# Handover to Phase 3 — two constraints Phase 1b shaped for you

Phase 1b (the lead CRM) does not create `touch` or `outcome`; those are written
at emit, which is yours. It did ship two things you need to adopt. Neither is
optional, and one of them is a hard requirement from the brief.

---

## 1. `outcome` is outbound-only — enforce it structurally

**The requirement:** inbound and referral leads live in `lead` and must never
get `outcome` rows.

**Why the spec's shape does not give you this.** §10 keys `outcome` on
`prospect_id`. That leaves outbound-only as a convention — something a trigger
or an application check has to remember — and a promoted **inbound** lead does
get a `prospect_id`, so a future write can violate it silently. Nothing in the
schema would object.

**What Phase 1b shipped so you don't have to rely on a convention:**

```sql
-- already applied, in 20260731150000_lead_crm.sql
constraint lead_prospect_source_key unique (prospect_id, source)
```

Plus a partial unique index on `lead (prospect_id) where prospect_id is not
null`, so one prospect resolves to exactly one lead, and therefore to exactly
one `source`.

**What to adopt when you create `outcome`:**

```sql
create table outcome (
  prospect_id uuid primary key references prospect(id) on delete cascade,

  -- Denormalised so the FK below has something to constrain. It is never
  -- written by hand: the check pins it, and the FK proves it.
  lead_source text not null default 'outbound_scan'
    constraint outcome_outbound_only check (lead_source = 'outbound_scan'),

  first_contacted_at timestamptz,
  selection_reason text not null,
  sequence_version text not null,
  touches_per_sequence_at_send smallint not null,
  touch_count integer not null default 0,
  replied_at timestamptz,
  first_response_at timestamptz,
  closed_at timestamptz,
  retainer_actual numeric,
  churned_at timestamptz,

  constraint outcome_lead_fk foreign key (prospect_id, lead_source)
    references lead (prospect_id, source) on update cascade on delete cascade
);
```

**What that buys, verified live against the real key on 2026-07-31:**

| | |
|---|---|
| outcome on an outbound lead | accepted |
| outcome on an inbound lead **that has a `prospect_id`** | rejected, foreign-key violation |
| reclassifying a lead that already has an outcome | rejected, check violation via `on update cascade` |

The third one is the back door: without `on update cascade` you could flip a
lead to `inbound` and strand its outcomes. The cascade tries to rewrite
`lead_source`, the check refuses, and the update fails. Two lines, both doors.

⚠️ **`'outbound_scan'` must match `lead.source` exactly.** It is a string
literal in a check constraint, so a typo does not fail loudly — it makes the
table permanently unwritable. If the source vocabulary is ever renamed, this
constraint and `lead`'s check must change in the same migration.

## 2. `lead_activity.touch_id` is waiting for its foreign key

`lead_activity` carries `touch_id bigint` with **no FK**, because `touch` did
not exist when it was written. Add it:

```sql
alter table lead_activity
  add constraint lead_activity_touch_fk
  foreign key (touch_id) references touch(id) on delete set null;
```

Check for orphans first — nothing has enforced this in the meantime:

```sql
select count(*) from lead_activity a
 where a.touch_id is not null
   and not exists (select 1 from touch t where t.id = a.touch_id);
```

**Do not let `lead_activity` start recording sends.** `touch` is authoritative
for "a contact attempt happened"; `lead_activity` carries human commentary only.
This was a real defect caught in the audit — both tables originally logged sends
— which is why `email_sent` and `call` are absent from the `kind` check and a
`call_note` references the touch it comments on instead. A `check (touch_id is
null or kind = 'call_note')` keeps the two from re-merging by accident.

## 3. When you land, update the verification script

`outreach/tests/lead_crm_rls.sql` cases 1–3 currently run against a throwaway
`_phase3_probe` table standing in for `outcome`. Delete the probe and point them
at the real table; the assertions themselves do not change.
