# Paid-placement Slice B — the money signal (design v0.1)

**Status:** design, partially built. Read `DECISIONS.md` (2026-08-08 paid-placement entries) and
`ISSUES.md` I-096/I-097/I-098 alongside this. Slice A (presence, parsed from the organic SERP) is
built and merged into the paid-placement PR; this is the second, bigger half.

**What Slice B measures that Slice A does not.** Slice A answers "is anyone running Google Ads / LSA
for this keyword" from the organic SERP already on disk. Slice B answers two harder questions that
need *the prospect's own site* and *a paid domain lookup*:

- **B1 — tech/tag PRESENCE** (Meta pixel, `AW-` conversion tag, GTM container, CallRail / Podium /
  Birdeye vendor tags, Google-Guaranteed badge) — PRD §B3. Source: a direct HTTP fetch of the
  prospect's site ("own request, not a paid service"). **Free**, keyed to the prospect.
- **B2 — ad-spend MAGNITUDE** (the >$2k / $500–2k bands) — scoring-spec.md §Proven spend. Source:
  DataForSEO **Labs** domain paid metrics. **Paid**, keyed to the prospect.

They are separate components with different providers, cost profiles and reliability, and ship as
separate builds behind separate spikes.

---

## The one risk to lead with (B2)

DataForSEO Labs' paid metrics come from its keyword/SERP database. A small local operator bidding on
hyper-local terms — and running **LSA**, which Labs does not index as paid search at all — will very
often return `paid.count = 0`. That is exactly the population this pipeline targets. **So the
magnitude band is likely sparse for our prospects**, and B2 is gated behind a yield spike
(below). The reliable money-signal core is PRESENCE: Slice A (LSA/Ads in the pack) + B1 (the tags).
Magnitude is a bonus, not the foundation. Owner ruling (2026-08-08): **build B1 now; gate B2 behind
the yield spike.**

---

## Spikes that MUST precede the build (measure-don't-infer — PRD §16a.1, ISSUES I-003)

Same discipline `dataforseo_client.py` enforces: measure the envelope on a real response before
writing a parser that trusts it.

1. **§16a.1 Outscraper pixel-field spike.** Does the Outscraper pull we *already run* carry Meta
   pixel presence? If yes, the Meta half of B1 is market-wide and near-free, and the site fetch
   drops to a GTM-false-negative backstop. Instrument: `probe-pixel-field` (built; gated, BILLS —
   an enriched pull of a small sample). Decides B1's primary source. **Run this first.**
2. **GTM-injected detection rate** (rides spike 1). Does an *inline* HTML scan miss GTM-injected
   pixels? If largely missed, the container fetch (`googletagmanager.com/gtm.js?id=GTM-…`) is
   promoted from optional to REQUIRED (§16a.1). The site-fetch producer ships the inline scan with
   the container follow behind `tech_follow_gtm` (config, default False) until this spike sets it.
3. **Labs paid-yield spike.** Confirm (a) Labs access on this account and (b) that paid
   `estimated_paid_traffic_cost` / `count` is populated for ~20 *small local* prospects, not just
   national brands. Instrument: the Labs endpoints are added to the free `probe-dataforseo` set now;
   a paid yield sample (`probe-labs-paid`, a follow-up build) confirms yield. **If near-zero, defer
   B2** and ship B1 alone.

None of these runs from the build sandbox (no Outscraper/DataForSEO egress) — they are gated
instruments the owner runs via a Railway Deploy + `OUTREACH_CONFIRM_SPEND`, exactly like the I-004
`probe-ai-granularity` instrument. **No spike is triggered from code.**

---

## B1 — tech/tag presence (built)

### Producer

`scan-tech` — a per-market batch over the surviving prospects (PRD §B3 "survivors only"). **FREE**
(own HTTP GETs), so NOT in `PAID_COMMANDS` — same reasoning as `collect`/`rollup`; a test asserts it.
Per-domain timeout + bounded concurrency + rate limit. Idempotent per prospect (re-fetch refreshes).
Resumable — one prospect's failure never ends the batch.

- **A failed fetch records `fetch_status ∈ {unreachable, timeout, blocked}` with signals NULL — never
  `absent`** (PRD §B3; unknown ≡ absent for the scorer, but stored distinctly so the report can say
  "couldn't read the site" instead of "no ad tech"). This is the same measured-vs-found discipline as
  the coverage denominator.
- All signals are **one-directional**: presence adds, absence never subtracts, unknown behaves as
  absent (scoring-spec.md §Buying intent, §Decision structure).

### Detection (pure, `api/services/tech_signals.py`)

Signature match over the fetched bytes, every match kept in `evidence` for replayability (the
`score_factors` discipline). Deterministic, fact-grounded — never asserts a tag not matched.

| Signal | Signatures |
|---|---|
| Meta pixel | `connect.facebook.net/…/fbevents.js`, `fbq('init','<id>')` → capture id |
| Google Ads conversion (`AW-`) | `gtag('config','AW-…')`, `googleadservices.com/pagead/conversion`, `AW-[0-9]+` → capture id |
| GTM container | `GTM-[A-Z0-9]+` → capture id(s); (if `tech_follow_gtm`) fetch the container JS and re-scan |
| Vendor tags | `callrail`/`cdn.callrail.com`, `podium.com`, `birdeye`/`birdeye.com` |
| Google Guaranteed badge | weak from HTML — **Slice A's LSA presence is authoritative**; the badge is corroboration only |

The GTM container follow is the §16a.1 false-negative fix, behind a flag until spike 2 sets it.

### Persistence (migration → `outreach/migrations/`, Outreacher only)

`prospect_tech_signal` — per-prospect, append-per-fetch, read-latest (the site is the prospect's, not
per-snapshot, so it does NOT ride `serp_result`). RLS-on / zero-policy.

```
prospect_tech_signal(id, prospect_id → prospect, fetched_at, fetch_status, final_url,
  meta_pixel bool, meta_pixel_ids text[], google_ads_conversion bool, aw_ids text[],
  gtm_container_ids text[], gtm_followed bool, vendor_tags text[], google_guaranteed bool,
  evidence jsonb)
```

---

## B2 — ad-spend magnitude (deferred behind the yield spike)

DataForSEO Labs `domain_rank_overview` (or bulk) → the domain's paid metrics
(`estimated_paid_traffic_cost`, `count`) → the spec's bands (>$2k / $500–2k / <$500). **PAID**,
`scan-adspend` in `PAID_COMMANDS`, `cost_ledger` stage `b4_adspend`, budget-checked, batched. Endpoint
MEASURED on first run (added to the free probe set now; the exact paid field logged from one sample).

`estimated_paid_traffic_cost` is estimated traffic *value* (clicks × CPC), a proxy for billed spend —
carried with a caveat, same as the RD ×10 note elsewhere. Persisted:

```
prospect_ad_spend(id, prospect_id → prospect, measured_at, source,  -- 'dataforseo_labs'|'cpc_floor'
  paid_keyword_count, estimated_spend_cents, band, evidence jsonb)
```

**Fallback proxy** if Labs yields poorly: Slice A already knows the prospect is in the paid block for
the scanned keyword, and we have that keyword's CPC — a floor ("paying ~$CPC/click on at least this
term"), enough for the *some spend vs none* distinction but NOT the >$2k band. Documented, not built.

---

## Report + hook surfacing — the strongest pitch in the model

Slice B enables the inverse of Slice A's talking point, and it is stronger: **the prospect is paying
AND still losing**. "Is this prospect advertising" is already known from Slice A
(`prospect_running_ads`/`_lsa`); B1's AW-tag and B2's band sharpen it.

- The report's "Paid placement" section gains the prospect's own ad-tech (Meta pixel, AW conversion,
  vendor tags, spend band when measured) — one-directional, "couldn't read the site" when the fetch
  failed, "no ad tech detected" on a clean-but-empty fetch.
- A new call-hook element **`paying_gap`** ("you're paying for Google Ads on '[keyword]' but you're
  invisible in the map pack — buying clicks your competitors get for free") fires when a *paying*
  signal (Slice A pack-ad / LSA, or B1 AW tag, or a B2 band) coincides with poor coverage. It ranks
  ABOVE the Slice-A competitor-gap paid point — it is the vendor-failing *shape* and the highest-intent
  opener available. Never fabricated: fires only on measured paying + measured poor coverage.

---

## Scoring integration (Phase 4 — stored + shown, not scored yet)

One-directional throughout (**unknown ≡ absent, never subtracts**):

- B1 → Model A buying-intent (AW +19, vendor +16, Meta +10) and decision-structure `likely_represented`
  −21 (2+ agency/vendor signals).
- B2 → Model B proven-spend (>$2k +66, $500–2k +34) and the Model C R-anchor (R ≈ 0.3–0.5 × spend).
- **Vendor-failing compound** (+79 A / +90 B) = vendor tag (B1) AND a negative delta — the delta half
  needs cycle-2 history that does not exist yet, so it is a future consumer, not part of Slice B.

Until the Phase-4 scorer exists: stored + shown, exactly like Slice A.

---

## Build order (cheapest-to-reverse first)

1. Spike 1 (§16a.1 pixel field) → decides B1's primary source. **Instrument built; owner runs it.**
2. **B1 `scan-tech`** (free): inline scan first, GTM follow behind `tech_follow_gtm`.
3. Report/hook surfacing of B1 + the "paying and losing" angle (reuses Slice A's `prospect_running_*`).
4. Spike 3 (Labs yield) → go/no-go on B2. **Labs endpoints added to the free probe set.**
5. **B2 `scan-adspend`** (paid) only if yield justifies it; else defer and document.

Each step is additive over Slice A's `payload_summary.paid` and rides the paid-placement branch/PR
(the designated branch; not a separate PR while that constraint holds).
