# Outreach Pipeline

A continuous market-monitoring and prospecting system for Amazing Rankings.

Point it at a city and a business category. It scans the local search landscape every two weeks,
scores every business in it, and produces a personalised audit showing a specific prospect exactly
where they are invisible — with a heatmap of their own service area to prove it.

---

## The problem it solves

Cold outreach for a local SEO agency has two hard parts: finding businesses that genuinely need
help *and can afford it*, and opening a conversation that doesn't get deleted.

Most prospecting tools solve the first badly — they hand you a list of businesses and leave you to
guess who's hurting. None solve the second at all.

This system does both from the same data. The scan that identifies a prospect also produces the
evidence that opens the conversation: *"I searched plumber near Lee's Summit this morning. You're
not in the top three anywhere more than two miles from your shop, and Anderson Plumbing is."*

That's not a pitch. It's a diagnosis the prospect can verify in thirty seconds.

---

## How it works

### The economic principle

**Scan at market level. Score at business level. Spend at shortlist level.**

A single geogrid scan of a submarket returns the full local pack at 89 points — which means one
scan measures *every* business in that area simultaneously. Scoring 400 businesses costs the same
as scoring one. Only the expensive per-record work (contact enrichment) is reserved for the
handful that make the shortlist.

The second principle matters as much: **never score more than you can work before the evidence
decays.** Rankings move, ads switch on and off, reviews accumulate. A queue larger than working
capacity is prepaid waste. It's cheaper to rescan a small area every two weeks than to scan a
large one once — and rescanning produces something a single scan cannot: **change**.

### The pipeline

```
Once per market
  1. Ingest    Pull every business listing in the category
  2. Filter    Drop the dead ones — closed, dormant, unreachable, franchises
  3. Match     Check against the case-study library for social proof

Every 15 days, per submarket
  4. Scan      89-point geogrid + organic SERP + AI Overview + LLM citation checks
  5. Delta     Diff against prior snapshots — who lost ground, who was overtaken
  6. Detect    Fetch each site for ad pixels, conversion tags, vendor tools
  7. Score     Pain × money × reachability, three ways

Per contact cycle
  8. Allocate  Spread across submarkets, diversified against correlated failure
  9. Enrich    Contact details, email track only
 10. Approve   A human reviews before any asset is generated
 11. Emit      Audit-ready queue to the outbound stack
```

### Two lead origins, one pipeline

The scanning pipeline generates **outbound** leads. The CRM layer also accepts **inbound,
referral, and manual** leads, which flow through the same stages, views, and suppression rules.

An inbound lead can be *promoted* — a single-business lookup pulls their real listing, and from
there they get scanned, scored, and audited like any outbound prospect. If they sit outside a
market you cover, spinning up a submarket and scanning it costs about five cents. So someone who
fills in your contact form can have their heatmap ready before the first call.

One rule holds the two apart where it matters: **only outbound leads feed the scoring model.**
Inbound leads converted because they came to you, so including them would inflate every
coefficient. Business reporting counts both; model fitting counts outbound only.

### What makes it different

**Change detection.** The strongest opener isn't "you rank poorly" — it's "you dropped out of the
pack in Overland Park last month." Because the system rescans continuously, every cycle produces
deltas. That's both a scoring signal and a first line, and it costs nothing extra.

**Vendor-failing detection.** A business paying for CallRail or Podium *while losing ground* is the
highest-intent moment in this market: proven budget, visible dissatisfaction, and the sale is
displacement rather than education.

**Slot-based allocation.** Under soft exclusivity, the unit of value isn't a client — it's a
submarket × vertical slot. Ten contacts in one submarket have a ceiling of one client. The system
spreads across slots rather than working any one to death.

**Unbroken history.** Scanning continues after a prospect signs. A client who closes in month six
arrives with six months of their own ranking history, collected before they ever spoke to you.
Nobody else can offer that, because nobody else was already scanning them.

---

## What it costs

| | |
|---|---|
| Per market-vertical, one-time | ~$2–4 |
| Per market-vertical, per cycle | ~$3–6 |
| Full portfolio (50 market-verticals), per cycle | $150–300 |
| **Annual, all-in** | **$3,600–7,200** |
| Database (Supabase Pro) | $25/month flat |

Roughly 25–35¢ per prospect contacted. One closed client at a typical retainer covers the entire
year of data.

The phone track costs **nothing** per prospect — phone numbers arrive in the base listing pull, so
no enrichment is required.

---

## Repository contents

| File | What it is |
|---|---|
| **`START-HERE.md`** | Build guide. Phases, table ownership, full config reference. Read first. |
| `CLAUDE.md` | Session continuity for Claude Code. Invariants and traps. |
| `DECISIONS.md` | Settled decisions with reasoning. Read before proposing changes. |
| `ISSUES.md` | Known problems, open questions, unvalidated assumptions. |
| `tests/fixtures/golden-fixtures.json` | Hand-computed scorecard test cases. Independent of the implementation. |
| `docs/PRD-prospect-pipeline.md` | Core spec — pipeline stages, data model, integrity guards. |
| `docs/scoring-spec.md` | Scorecard mathematics, coefficients, refit path. |
| `docs/storage-retention-spec.md` | Partitioning, rollup, retention. **Required before cycle two.** |
| `docs/reporting-layer-spec.md` | Views, heatmap renderer, sharing and access. |
| `docs/crm-layer-spec.md` | Lead pipeline — inbound and outbound, suppression, ESP boundary. |
| `docs/dataforseo-dependency-note.md` | Provider contingency. Not build input. |

---

## Key concepts

**Market-vertical** — one business category in one city (e.g. LA plumbing). The portfolio is
5 verticals × 10 cities = 50 market-verticals.

**Submarket** — a 5-mile-radius scan area with an 89-point grid at 1-mile spacing. A city has
roughly 6–10. Geometry is **immutable** once scanning begins; changing it invalidates all prior
snapshots.

**`ai_region`** — a recognised place name used to prompt AI assistants ("plumber in Los Feliz").
Distinct from submarkets and coarser: several submarkets may share one region. Real neighbourhoods
are smaller than scan areas, so the name anchors the prompt rather than bounding the grid.

**Lead source** — where a lead came from: `outbound_scan`, `inbound_form`, `inbound_call`,
`referral`, `partner`, `manual`. Determines whether it feeds the scoring model.

**Slot** — one submarket × vertical. Under exclusivity this is the unit of value: a filled slot is
a client, and no submarket yields more than one.

**Pack coverage** — the share of grid points where a business appears in the local pack. The
dominant scoring signal, because it's the only continuous one with real spread.

**Cycle** — one semi-monthly scan pass. 24 per year.

**Bootstrap** — cycle one, running on single-snapshot evidence because no history exists yet.
Flagged so its outcomes can be handled separately.

**Vendor-failing** — a compound signal: vendor tooling present *and* measurable ranking decline.
The largest positive coefficient in the model.

**Two-pass scoring** — pass 1 scores pain × money and selects who gets enriched; pass 2 adds
reachability after enrichment and produces the final order.

---

## Status

**Specification complete. Implementation not started.**

Every design decision is recorded in `DECISIONS.md` with its reasoning. Open work is in
`ISSUES.md` and falls into three groups:

- **Two blockers with calendar lead time** — email vendor decision and 3–4 weeks of domain
  warming. Start these now, in parallel with the build.
- **Three verification spikes** — about two hours total. Testing and reading, not judgment.
- **Unvalidated assumptions** — every scoring coefficient. See below.

Build order is in `START-HERE.md`. Phases 1–3 produce a working system that generates real audits;
that's roughly 15% of what's specified and where the revenue is.

**Two tracks run in parallel.** Phase 1 (ingest and filter) and Phase 1b (the lead CRM) have no
dependency on each other. The CRM is useful the day it exists — inbound and referral leads can be
tracked by hand while the scanning pipeline is still being built.

---

## An honest caveat

The pipeline mechanics are sound — ingestion, filtering, scanning, cost control, entity
resolution, storage. Those are engineering problems with known answers.

**The scoring is careful reasoning dressed in real mathematics, which makes it look more
authoritative than it has earned.** Every coefficient is an estimate. Nothing has been tested
against a single reply. The base reply rates are guesses about a channel that hasn't been run.

The structure is designed for this: the model starts from stated priors, recalibrates after ~30–50
outcomes, and refits properly at ~200. Until then, treat the ranking as a strong prior — useful for
deciding who to contact first — and not as a prediction of what will happen.

The fastest way to make it real is to contact a hundred people.
