# Reporting Layer Spec v0.4

**Module:** `outreach-pipeline` (AR Tools)
**Siblings:** `PRD-prospect-pipeline.md`, `scoring-spec.md`, `storage-retention-spec.md`
**Stack:** Postgres views on Supabase · Python renderer on FastAPI/Railway · Cloudflare R2 · WeasyPrint

---

## 1. Purpose and audiences

Three audiences with different needs, different access models, and — critically — different
trust levels. Conflating them is the main risk in this layer.

| Audience | Needs | Access | Auth |
|---|---|---|---|
| **Operator** (AR staff) | Cycle health, cost, queue, score explanation, data quality | Views via Supabase REST or SQL | Authenticated staff |
| **Client** (closed slot) | Their own coverage history and competitor movement | Restricted views | Authenticated + RLS |
| **Prospect** (not a customer) | A single audit asset | Signed URL to a rendered file | **None — must not require login** |

A prospect will not create an account to view an audit. Prospect-facing assets are therefore
**rendered artifacts behind expiring signed URLs**, never database access of any kind.

---

## 2. Provenance — what makes a report repeatable

Every report artifact MUST record what produced it, so a report shared in March regenerates
identically in June.

```sql
create table report_artifact (
  id              uuid primary key default gen_random_uuid(),
  kind            text not null check (kind in
                    ('heatmap','heatmap_pair','heatmap_delta','audit_bundle','client_report')),
  subject_type    text not null check (subject_type in ('prospect','submarket','market')),
  subject_id      uuid not null,
  snapshot_id     uuid references scan_snapshot(id),
  compare_snapshot_id uuid references scan_snapshot(id),
  score_run_id    uuid references score_run(id),
  generator_version text not null,
  geometry_version  text not null,
  storage_path    text not null,
  content_hash    text not null,
  generated_at    timestamptz not null default now(),
  expires_at      timestamptz
);
create index on report_artifact (subject_type, subject_id, generated_at desc);
```

- Reports MUST be snapshot-scoped, never "latest". A view that silently re-resolves to current
  data cannot be cited in a conversation with a prospect three weeks later.
- `generator_version` and `geometry_version` MUST both be stamped. A renderer change and a
  geometry-generator change produce different pictures from the same bytes.
- Regenerating an artifact with identical inputs MUST produce an identical `content_hash`.
  Renderers MUST be deterministic — no timestamps, random IDs, or unsorted iteration in output.

---

## 3. Read surface — views

Defined in migrations and version-controlled. Supabase exposes views over REST automatically with
RLS applied, so this covers most of the operator and client surface with no API layer.

### 3.1 Operator views

```sql
-- Cycle health: did the scan actually work?
create view v_cycle_health as
select
  m.id as market_id, m.name as market,
  s.cycle_number,
  count(*)                                        as snapshots,
  count(*) filter (where sn.complete)             as complete,
  round(avg(sn.actual_points::numeric / nullif(sn.expected_points,0)) * 100, 1) as pct_points,
  min(sn.scanned_at) as started_at,
  max(sn.scanned_at) as finished_at
from scan_snapshot sn
join submarket sm on sm.id = sn.submarket_id
join market m      on m.id = sm.market_id
join score_run s   on s.market_id = m.id
group by m.id, m.name, s.cycle_number;

-- Cost: reconciles against provider dashboards
create view v_cost_summary as
select market_id, cycle_number, stage, provider,
       sum(units) as units, sum(cost_cents)/100.0 as cost_usd
from cost_ledger
group by market_id, cycle_number, stage, provider;

-- The working queue
create view v_prospect_queue as
select p.id, p.name, p.category, p.phone, p.website,
       sm.name as submarket,
       ps.channel, ps.score, ps.decile, ps.primary_pitch,
       ps.evidence_age_days,
       e.email, e.email_confidence,
       cc.risk_level as conflict_risk,
       cs.match_type as case_study_match
from prospect p
join submarket sm       on sm.id = p.submarket_id
join prospect_score ps  on ps.prospect_id = p.id and ps.pass = 2 and ps.model = 'value'
left join enrichment e  on e.prospect_id = p.id
left join conflict_check cc on cc.prospect_id = p.id
left join case_study_match cs on cs.prospect_id = p.id
where not exists (select 1 from outcome o where o.prospect_id = p.id);

-- Why did this prospect score what it scored?
create view v_score_explain as
select ps.prospect_id, p.name, ps.model, ps.pass, ps.channel, ps.score,
       f->>'feature'   as feature,
       f->>'bin'       as bin,
       (f->>'points')::numeric as points,
       f->>'evidence_ref' as evidence_ref
from prospect_score ps
join prospect p on p.id = ps.prospect_id
cross join lateral jsonb_array_elements(ps.score_factors) f
order by ps.prospect_id, abs((f->>'points')::numeric) desc;

-- Slot inventory — how much runway is left
create view v_slot_status as
select sm.market_id, s.vertical, s.state, count(*) as slots,
       sum(s.attempts) as attempts
from slot s join submarket sm on sm.id = s.submarket_id
group by sm.market_id, s.vertical, s.state;

-- Data quality: the guards from PRD §9a, surfaced
create view v_data_quality as
select sm.market_id, sm.id as submarket_id, sm.name,
       count(*) filter (where not gps.land)          as dead_points,
       count(*)                                       as total_points,
       (select count(*) from scan_snapshot x
         where x.submarket_id = sm.id and not x.complete) as incomplete_snapshots,
       (select count(*) from prospect_delta d
         join prospect pr on pr.id = d.prospect_id
        where pr.submarket_id = sm.id and d.direction = 'unknown') as suppressed_deltas
from submarket sm
left join grid_point_status gps on gps.submarket_id = sm.id
group by sm.market_id, sm.id, sm.name;
```

### 3.2 Analysis views

```sql
-- Evidence effects: randomized rows only, segmented by confound
create view v_evidence_effects as
select ae.element, ae.slot,
       o.sequence_version, aa.template_version,
       count(*)                                      as sends,
       count(*) filter (where ae.included)           as included,
       count(*) filter (where o.replied_at is not null) as replies,
       round(100.0 * count(*) filter (where ae.included and o.replied_at is not null)
             / nullif(count(*) filter (where ae.included),0), 2) as reply_rate_included,
       round(100.0 * count(*) filter (where not ae.included and o.replied_at is not null)
             / nullif(count(*) filter (where not ae.included),0), 2) as reply_rate_excluded
from audit_evidence ae
join audit_asset aa on aa.id = ae.asset_id
join outcome o      on o.prospect_id = aa.prospect_id
where ae.assignment in ('randomized_in','randomized_out')
  and not ae.assignment_overridden
group by ae.element, ae.slot, o.sequence_version, aa.template_version;

-- Funnel by cohort — never pool across confound versions
create view v_outcome_funnel as
select o.sequence_version, o.touches_per_sequence_at_send, o.selection_reason,
       count(*)                                          as started,
       count(*) filter (where o.replied_at is not null)  as replied,
       count(*) filter (where o.closed_at  is not null)  as closed,
       round(avg(extract(epoch from (o.first_response_at - o.replied_at))/3600), 1)
                                                          as median_response_hours
from outcome o
group by 1,2,3;
```

### 3.3 Client views

```sql
create view v_client_coverage_history as
select pc.prospect_id, p.name, sm.id as submarket_id, sm.name as submarket,
       k.term as keyword, sn.scanned_at,
       pc.coverage_pct, pc.live_points, pc.avg_rank, pc.best_rank,
       pc.centroid_dist_at_loss
from prospect_coverage pc
join scan_snapshot sn on sn.id = pc.snapshot_id
join prospect p       on p.id = pc.prospect_id
join submarket sm     on sm.id = sn.submarket_id
join keyword k        on k.id = sn.keyword_id
where sn.complete
order by sn.scanned_at;
```

- Client views MUST expose **only** coverage and competitor movement. Scores, `score_factors`,
  conflict flags, deltas used for pitching, and `outcome` MUST be unreachable by client roles
  under any policy. A client seeing their own prospecting score — or a competitor's — is a
  serious disclosure.
- RLS MUST scope to submarkets where the requesting client holds the `filled` slot.

---

## 4. Heatmap renderer

The only genuinely new component. Input is `prospect_coverage.rank_vector` plus
`scan_snapshot` geometry — no raw `grid_result` required, so historical heatmaps render forever.

### 4.1 Coordinate regeneration

Coordinates are **not stored**. They regenerate deterministically:

```
lat_step = spacing_miles / 69.0
lng_step = spacing_miles / (69.0 * cos(radians(center_lat)))

Square lattice covering the bounding box, row-major from NW corner,
clipped to distance <= radius_miles from centre.
point_seq = index in that ordering, zero-based.
```

- The generator MUST be a pinned, versioned function. `geometry_version` on both
  `scan_snapshot` and `report_artifact` records which one produced a given vector.
- Ordering integrity is critical: a change to lattice ordering silently re-maps every historical
  vector onto wrong coordinates. Ordering changes MUST bump `geometry_version` and MUST NOT be
  applied retroactively.
- Round-trip test required: regenerate coordinates for an old snapshot and confirm the count and
  the first/last coordinates match stored values.

### 4.2 Encoding and colour scale

`rank_vector` bytes map to the standard local-SEO scale:

| Byte | Meaning | Colour |
|---|---|---|
| `1–3` | In the pack | Green |
| `4–10` | Page one, below pack | Yellow |
| `11–20` | Found, far down | Orange |
| `0` | Not found | Red |
| `255` | Dead point | Rendered faint grey, or omitted |

- Dead points MUST be visually distinguishable from "not found". Conflating them overstates pain
  and is the kind of error a prospect can catch.
- The business's own pin MUST be marked distinctly from grid points.
- A legend and a scale bar MUST be present on every prospect-facing render.

### 4.3 Three render types

**`heatmap`** — single snapshot, current state. The core audit visual.

**`heatmap_pair`** — two snapshots side by side, shared colour scale and extent. Used for
case-study drafts (PRD §7) and client before/after reporting. Both panels MUST label their
snapshot dates.

**`heatmap_delta`** — per-point change between two snapshots. Green where rank improved, red
where it worsened, neutral where unchanged. This is the visual form of the strongest pitch
signal, and it MUST honour every delta guard: no render across a provider boundary, across a gap
exceeding `max_delta_span_days`, or where drift suppression fired (PRD §9a.2).

### 4.4 Output format

- **SVG is primary.** Vector, small, deterministic, embeddable in HTML, and consumable directly
  by WeasyPrint for PDF.
- PNG rasterisation MAY be offered for channels that reject SVG (some email clients).
- Renderers MUST be deterministic: no embedded timestamps, no random element IDs, sorted
  iteration only. Non-determinism breaks `content_hash` and therefore reproducibility.

### 4.5 Map background

- **Internal renders default to no background** — points on a neutral field with a scale bar.
  Cheaper and clearer for operator use.
- **Prospect- and client-facing renders default to a map background.** Recognising their own
  neighbourhood is a large part of why the artifact lands.
- Backgrounds come from a static-tile provider. Tiles MUST be cached by
  `(centre, radius, zoom, geometry_version)` — geometry is immutable, so one fetch per submarket
  serves every render for that submarket forever.
- Tile fetch failure MUST fall back to the no-background render, never block generation.

---

## 4a. Generation is approval-gated

**PDFs and prospect-facing assets are never generated automatically.** The pipeline assembles
evidence and marks a prospect audit-ready; a human approves; generation happens then.

This is not primarily about cost — WeasyPrint is free and tiles are cached. Four better reasons:

1. **Send-time verification would go stale.** Any claim about a specific LLM's output must be
   re-verified at generation (PRD §4a). Generating fifty PDFs on Monday for a Thursday send makes
   that verification three days old, which defeats its purpose.
2. **Conflict decisions come first.** Client conflict is a flag requiring an explicit human
   decision (PRD §11). Generating assets before that decision wastes work and creates a real risk
   of an audit reaching a prospect who should never have been contacted.
3. **Falsifiable claims deserve a look.** The AI-absence line, the named-competitor callout, and
   anything near a suppressed drift are the statements a prospect can disprove in thirty seconds.
4. **Batch generation invites batch mistakes.** A template or coefficient error caught after
   fifty sends is far more expensive than one caught after one.

### State machine

```
evidence_ready → pending_approval → approved → generated → dispatched
                        ↓
                     rejected (reason recorded)
```

```sql
create table audit_approval (
  prospect_id   uuid primary key references prospect(id) on delete cascade,
  state         text not null default 'pending_approval'
                  check (state in ('evidence_ready','pending_approval','approved',
                                   'rejected','generated','dispatched')),
  review_flags  jsonb not null default '[]',
  decided_by    text,
  decided_at    timestamptz,
  rejection_reason text,
  updated_at    timestamptz not null default now()
);
```

### Requirements

- Generation MUST be triggered by an explicit approval action, never by cycle completion,
  schedule, or shortlist emission.
- The emit webhook (PRD §9) delivers an **audit-ready queue**, not generated assets.
- Send-time LLM verification MUST run at generation, i.e. after approval — not at scan time.
- Evidence randomization (PRD §14a) MUST also occur at generation, so approval does not bias
  assignment. A reviewer who then overrides an element sets `assignment_overridden`.
- `review_flags` MUST surface the items warranting judgment: low-confidence AI name matches,
  suppressed drift, conflict risk, incomplete snapshots, bootstrap-provisional evidence,
  first-scan `unknown` deltas.
- **Rejections MUST record a reason.** These are labels: "claim looks wrong", "business looks
  dead", "conflict concern" are exactly the signals that improve upstream filters, and they are
  free to collect at the moment a human is already looking.

### Approval fatigue — the failure mode to watch

At ~50 prospects per cycle, one-by-one review becomes theatre: someone approves fifty in two
minutes and the gate protects nothing.

- Batch approval MUST be supported, with `review_flags` items broken out individually so the
  clean ones can be cleared together and the flagged ones considered separately.
- `auto_approve_clean` (config, default **off**) MAY auto-approve prospects with zero
  `review_flags`, leaving humans only the judgment calls. Recommended once the flag logic has
  been observed to be trustworthy — but off at launch, since a gate nobody trusts yet should
  not be conditionally bypassed.
- Approval throughput SHOULD be monitored. Median seconds-per-approval falling toward zero is
  evidence the gate has become a rubber stamp.

### Call hooks are exempt

A hook is a sentence generated when a caller opens a prospect to dial — inherently
human-triggered, so no separate gate applies. Send-time verification requirements are
unchanged: a hook citing an LLM claim MUST verify at render.

---

## 5. Sharing and access

| Artifact | Delivery | Auth | Expiry |
|---|---|---|---|
| Operator views | Supabase REST / SQL / MCP | Staff | — |
| Client report | Authenticated view + rendered PDF | RLS-scoped | — |
| Prospect audit | Signed R2 URL | **None** | 90 days, configurable |

- Prospect URLs MUST be unguessable (random token, not sequential IDs) and MUST expire.
- Prospect artifacts MUST contain no competitor-prospect data, no scores, and no internal
  commentary. The manifest in `audit_evidence` governs what appears.
- Expired artifacts MUST return a neutral message and SHOULD offer a refresh path, not a 403.
- Artifact access SHOULD be logged as `asset_engagement` events (PRD §14a) — this is the
  engagement instrumentation that makes evidence attribution measurable, so it is not optional
  in practice.

---

## 6. Caching and cost

- Rendered artifacts are immutable for a given `(inputs, generator_version)`. Cache in R2 keyed
  by `content_hash`; never regenerate on identical inputs.
- Map tiles cached per submarket geometry — one fetch, unlimited reuse.
- At ~35 audits per cycle (70% of 50 prospect starts, email track only — the phone track takes
  call hooks, not PDFs), tile and render cost is negligible. The cost risk is accidental
  regeneration in a loop, which the `content_hash` cache prevents.

---

## 7. Acceptance criteria

- [ ] No prospect-facing asset generated without an explicit approval action
- [ ] Emit delivers an audit-ready queue, not generated assets
- [ ] Send-time LLM verification and evidence randomization both occur at generation
- [ ] `review_flags` populated for every judgment-worthy condition
- [ ] Rejections record a reason
- [ ] Batch approval supported with flagged items separable from clean ones
- [ ] `auto_approve_clean` defaults off
- [ ] Every artifact stamped with snapshot, score run, generator version, geometry version
- [ ] Identical inputs produce identical `content_hash`; renderers fully deterministic
- [ ] Heatmaps render from `prospect_coverage` alone, with no raw `grid_result` present
- [ ] Coordinate regeneration round-trips against stored geometry
- [ ] Dead points visually distinct from "not found"
- [ ] Legend and scale bar present on all external renders
- [ ] Delta heatmaps refuse to render across provider boundaries, span limits, or suppressed drift
- [ ] Client views expose coverage only — no scores, factors, conflicts, or outcomes
- [ ] RLS scopes client access to their own filled slots
- [ ] Prospect URLs unguessable, expiring at 30 days, and require no authentication
- [ ] `url_expiry_days` validated ≥ sequence duration at config load
- [ ] Expired links return a neutral refresh page, never a 403
- [ ] Client views and RLS policies built and tested now, not deferred with the dashboard
- [ ] Delta legend uses directional language only; no raw ranks or numeric deltas
- [ ] Points absent in both snapshots render neutral, never red
- [ ] Prospect artifacts contain no competitor-prospect data
- [ ] Artifact access logged as `asset_engagement`
- [ ] Evidence-effect view excludes overridden assignments and segments by confound version
- [ ] Map tile failure degrades to no-background render rather than failing

---

## 7a. Recorded decisions

**Client reporting — PDF now, dashboard later.**
Scheduled PDF ships first: no auth, no RLS testing, and it matches how local service businesses
actually consume reports. But because a dashboard is planned rather than ruled out, the client
views in §3.3 MUST be built now even though only the PDF renderer consumes them. That way the
dashboard is a UI layer over an existing, RLS-tested read surface rather than a new backend
later. RLS policies MUST also be written and tested now, not deferred — retrofitting row-level
security onto views already in production use is where disclosure bugs come from.

**Prospect audit URL expiry — 30 days.**

This is not arbitrary, and the alignment is worth preserving deliberately: it matches
`max_evidence_age_days = 30` (PRD §4.1). The link therefore dies at exactly the point the
evidence behind it would no longer be emittable. A prospect can never be looking at a heatmap
the pipeline itself would refuse to send.

> **Constraint this creates:** `url_expiry_days` MUST be ≥ the full sequence duration. A 5-touch
> sequence at typical spacing (day 0, 3, 8, 15, 25) fits inside 30 days with slack — but widening
> the spacing, or adding touches, would kill the link mid-sequence. Sequence duration and URL
> expiry MUST be validated against each other at config load, not discovered in production.

Expired links MUST return a neutral page with a refresh path, never a 403 — a late click is a
signal of interest arriving at the worst possible moment, and a wall converts it into nothing.

**Delta heatmap colours — green improved / red worsened, with an explicit legend.**

> **The trap:** rank is inverted. "Improved" means the rank *number went down*. A legend showing
> numeric ranges on a delta view will read backwards to anyone who glances at it.
>
> - The legend MUST use directional language — "rank improved" / "rank worsened" — and MUST NOT
>   display raw rank numbers or numeric deltas.
> - The delta view MUST be visually distinct from the state heatmap (different frame, title, or
>   background treatment) so the two are not confused when they appear on the same page.
> - Where a point was absent in both snapshots, render neutral, never red. "Still not ranking"
>   is not a decline and MUST NOT be presented as one.

---

## 8. Open decisions

1. **Tile provider** — Mapbox, MapTiler, or OSM-derived. Cost is negligible; **licensing is the
   open question**, and it is a reading task rather than a judgment call — see
   `PRD-prospect-pipeline.md` §16a.3. Attribution requirements affect heatmap layout, so
   resolve before the renderer is built.
