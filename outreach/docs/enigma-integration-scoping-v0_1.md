# Enigma integration — scoping & procurement ask (v0.1)

**Status:** PROBE BUILT (2026-08-27) — an eval API key is provisioned (`OUTREACH_ENIGMA_API_KEY` on
the Railway outreach service) and the §3 sample test is now runnable as the `probe-enigma` command
(PAID, confirm-gated). This doc frames (1) what to ask Enigma for and (2) the sample test to run
*before* committing the production features, so the decision is made on measured coverage against our
own prospects, not on a sales deck. Same "measure, don't infer" discipline that resolved the
Outscraper enrichment work (I-109). **Owner ruling 2026-08-27:** build both uses; the transactions
feature surfaces Enigma's native **1m / 3m / 12m** windows (there is no 6m period). Run the probe on
Railway (flip `OUTREACH_COMMAND=probe-enigma` + `OUTREACH_CONFIRM_SPEND=probe-enigma`, or run the CLI
there) to capture the real schema + yield, then build Phase 2 per §4. See DECISIONS.md 2026-08-27.

**Why Enigma is on the table.** After the enrichment fixes (async submit+poll + the correct
`leads_n_contacts` slug + per-person dedup), Outscraper reliably returns **emails** for small local
businesses and **decision-maker names** for businesses that have an Apollo/ZoomInfo/LinkedIn record.
The residual gap is small owner-operated businesses (a solo plumber) that have **no person named
anywhere** — Outscraper falls back to a role email, the free site scrape finds no name, and web
search may or may not surface a cited one. Enigma is proposed to fill that residual, and separately
to feed the Phase 4 scoring model with firmographic / business-activity signals.

Two intended uses (owner confirmed both, 2026-08-26):
1. **Contacts** — an owner/principal NAME for prospects the existing ladder can't name.
2. **Scoring signal** — firmographics + card-transaction-derived activity/health as features for the
   Phase 4 prospect-scoring model (pick which businesses are worth calling).

A single Enigma business lookup returns both, so this is one integration and one sample test.

---

## 1. What Enigma is (and isn't), for expectation-setting

- **Strong:** US SMB coverage — firmographics (industry, size, location, identity/verification) and
  **business activity & health** derived from card-transaction data (revenue estimates, growth,
  is-it-still-operating). It covers the small-business long tail that Apollo/ZoomInfo (tuned to
  larger/tech firms) miss. This is Enigma's differentiator and the strongest fit for our **scoring**
  use.
- **Secondary / uncertain for us:** decision-maker CONTACT data. Enigma surfaces some
  principal/owner names (often from registration/licensing/business-registry records), but it is not
  primarily a sales-contact database, and depth for a one-person local trade is genuinely unknown.
  This is exactly what the sample test must measure before we count on it for the **contacts** use.
- **Commitment:** enterprise API — contract + sales process + a meaningful annual cost, **not**
  self-serve pay-per-record like Outscraper/DataForSEO. So it needs a demonstrated payoff before
  signing, which is what this doc de-risks.

---

## 2. Procurement ask (what to get from Enigma before any build)

Send this to Enigma sales / partnerships. The goal is enough to run the §3 sample and to price a
production integration.

**Access**
- A **time-boxed evaluation API key** (or a sandbox) sufficient to run ~50 real business lookups.
  Explicitly for a build-vs-buy evaluation, not a signed commitment.
- The specific **product(s)** that carry: (a) business firmographics + identity, (b) business
  activity / health (the transaction-derived signals), (c) any principal / owner **contact** fields.
  Name the exact API endpoints and the response schema for each.

**Coverage questions (answer before the test, so we know what to expect)**
- Owner/principal **name** coverage for **micro-businesses** (1–5 employees, sole proprietors,
  home-service trades — plumbers, roofers, HVAC). What % have a named principal? Sourced from where
  (registry vs. self-reported vs. inferred)?
- **Match rate** on our identifiers. We can key a lookup by: business **name + full address**,
  **phone**, **website/domain**, and lat/lng. Which of these does Enigma match on, and what is the
  expected match rate for local businesses pulled from Google Maps? (Google-Maps place identity is
  our anchor; a poor name+address match rate kills the integration regardless of data depth.)
- Activity/health signal **freshness + coverage** for micro-businesses (many take only cash/limited
  card volume — is the transaction signal present or sparse at this size?).

**Commercial**
- Pricing model: **per-lookup** vs. tiered subscription vs. annual minimum. Per-lookup is far easier
  to fit our signed-order + budget-guard model; a large annual minimum needs a volume justification
  we don't have yet.
- Any **per-field** pricing (contacts often priced separately from firmographics).
- Rate limits / batch support (we enrich in bounded batches; a batch endpoint matters).
- Data-use / compliance terms for cold **outreach** use of any contact data (some providers restrict
  contact data to verification/underwriting, NOT marketing — confirm outreach is a permitted use).

**Compliance / legal**
- Permitted-use terms for contact data in **outbound sales** specifically.
- Any PII handling obligations (deletion, opt-out) we'd inherit.

---

## 3. Sample-test spec (run once access lands — decides build vs. no-build)

**Principle:** measure Enigma's real yield on *our* prospects, both uses at once, before any
integration code. Mirrors the `probe-enrich` spikes that settled the Outscraper questions on a
handful of billed calls.

**Sample selection (N ≈ 20, from the Outreacher `prospect` table)**
Pick a spread that stresses the two failure modes, all from a scanned market
(`market_id = 9238e737…`, LA emergency plumber — real Google-Maps prospects we already hold):
- **10 "un-named"** — prospects with NO person name after the current ladder (Outscraper
  `leads_n_contacts` + site scrape + web search). These are Enigma's target for the *contacts* use.
  Query: prospects in the market with no `prospect_contact` row carrying a real `first_name`/
  `last_name` (and not a site_scrape/web_search person).
- **5 "named"** — prospects we DO have a verified owner name for (controls: does Enigma agree?).
- **5 with strong signals** — high review count / clearly active, to test the activity/health data
  where it should be richest.

Include for each: business name, full address, phone, website (where present), lat/lng, place_id —
so we can test every match key Enigma offers.

**What to run**
For each of the 20, call the Enigma business-lookup (firmographics + activity + principal fields),
keyed by name+address (and separately by phone/domain if Enigma supports them, to compare match
rates). Log the FULL raw response per business (the `probe-enrich` discipline — one logged record so
the real schema is captured, not inferred).

**What to measure (the decision metrics)**
Contacts use:
- **Match rate** — % of the 20 Enigma returns *any* record for (by each key). Below ~70% and the
  integration is fragile regardless of depth.
- **Owner-name hit rate on the 10 un-named** — % that get a real principal/owner NAME. This is the
  headline number for the contacts decision. Compare against what the (cheaper) web-search rung
  already recovers on the same 10.
- **Agreement on the 5 named controls** — does Enigma's principal match the name we already have?
  (accuracy check.)

Scoring use:
- **Firmographic fill** — % with usable industry/size/revenue-band.
- **Activity/health fill** — % with a present (non-null) transaction-derived activity/health signal,
  and whether it's discriminating at micro-business size (or all "insufficient data").

Cost:
- **$ per lookup actually billed** (settles the I-111 unknown for this provider).

**Decision rule (write the answer before signing)**
- Contacts: build the Enigma rung **only if** owner-name hit-rate on the un-named clears a bar we set
  now (proposal: **≥ 40%** AND materially better than the web-search rung it would sit beside) AND
  match rate ≥ ~70% AND per-lookup cost is justified by the lead value. Otherwise contacts stay on
  the existing (cheaper) ladder and Enigma is not bought for contacts.
- Scoring: adopt the firmographic/activity feed **only if** the activity signal is present + varying
  at micro-business size (not uniformly "insufficient data"), AND Phase 4 is mature enough to consume
  a new feature (see §4 sequencing).

---

## 4. If we build — shape + sequencing (design sketch, not a commitment)

Mirror the patterns that already work in this module; do NOT invent new infra.

**Contacts rung (immediate value):**
- New enrichment source, `prospect_contact.source = 'enigma'`, a **signed order**
  (`enigma_request`) drained by `tick` — same model as `leads_n_contacts` (the order row is the
  spend confirmation; platform-api never spends).
- Positioned as the **last, most-expensive rung**: only run Enigma for prospects still un-named after
  Outscraper → free site scrape → web search, so we never pay Enigma for a name we already have.
- Admin-gated + per-user daily budget guard + `cost_ledger` write (mirror the `name_search` paid
  producer exactly).

**Firmographics / scoring feed (Phase 4 value):**
- A new `prospect_firmographics` store (revenue-band / size / activity-health / verification),
  captured in the same Enigma call so the contacts run also lands the scoring data for free.
- Feeds the **Phase 4 scoring model** as features — but see the caveat.

**Sequencing caveat (be honest about ROI timing):** the contacts value is immediate; the scoring
value is **Phase-4-gated**. Phase 4 Stage 1 (priors) is built, but Stages 2–3 need accumulated
`outcome` rows and the model does not yet consume external firmographic features. So Enigma's
activity/health data would be **stored now** but only **move the score** once Phase 4 matures. Store
it cheaply from day one (it rides the contacts call); don't promise scoring lift before the model can
use it.

**Coefficients / invariants:** any firmographic feature added to scoring loads its coefficient from
config (zero hardcoded βs — the module invariant) and only after the recalibration loop can fit it.

---

## 5. Open items / to fill after the §3 test

- Real per-lookup cost (I-111 for Enigma).
- Confirmed owner-name hit-rate on micro-businesses (the whole contacts decision).
- Confirmed name+address match rate on Google-Maps-sourced prospects.
- Whether outbound-sales use of Enigma contact data is contractually permitted.
- The residual name gap this fills — **being measured now** by the market-wide `leads_n_contacts`
  run (enrichment_request `53a6c99e…`); that number sizes the problem Enigma would solve and belongs
  in §3's decision math.
