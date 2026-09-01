# Module card — Forecasting

**What it measures:** not a new instrument — a deterministic projection layer
computed on read from data the rank tracker, GSC, and market cache already
hold. Four reads: rank **trajectories** (linear trend per keyword), **traffic
/ value** (clicks × CPC), a **quick-win scenario** (striking-distance
keywords moved to top 3), and **goal projections** (whether current pace
reaches a due-dated goal in time). Nothing is stored; every call recomputes.

**Direction:** `trend_per_week` is **negative = improving** (position number
falling). A positive value means the keyword is sliding — the opposite of
the plain-English sense of "positive trend."

**How to read the fields:**
- `confidence` (high/medium/low) is a **data-sufficiency** read (point count
  + span), not an accuracy guarantee.
- Under 4 points or a 14-day span → no trend fits, and the projection runs
  **flat** (unchanged) rather than omitting a number. A `projected_position_
  30d` equal to `current_position` can mean "genuinely stable" OR "too
  little data" — check `confidence`/whether `trend_per_week` is null.
- `clicks_source` is `gsc` (anchored to actual Search Console clicks) or
  `ctr_model` (volume × a standard industry CTR curve — a model, not this
  client's real CTR). Never present a `ctr_model` number as measured
  traffic.
- The **quick-win scenario is CTR-model math throughout**, even for keywords
  whose current clicks are GSC-anchored — treat it as directional ("worth
  pursuing"), not a budgeted revenue number. Keywords skipped for missing
  volume data are excluded from the total, not counted as zero — the total
  under-counts true upside.
- Projections clamp to [1, 100] rather than extrapolating to an absurd
  position.
- `goal_projections` only covers goal types with a deterministic trajectory
  (`keyword_position`, `organic_clicks`); every other type — and any goal
  already `achieved`/`manual` — is silently absent. Absence isn't a warning
  sign on its own; check the goal's own status first.
- A keyword's trend series uses one source only (GSC or DataForSEO, never
  spliced), chosen by whichever is currently primary for that keyword — that
  choice can flip between reads, so two forecasts for the same keyword
  aren't guaranteed to share a basis.
- `demand_outlook` (seasonal index) rides alongside the clicks trajectory on
  purpose — a flat/falling trajectory can be seasonal demand cooling, not a
  ranking problem. Read them together before diagnosing a decline.

**Known blind spots:** linear extrapolation only — no acceleration/
deceleration modeling, and no forecast history stored to check whether last
month's projection was right.

**Worked misreading:** "The quick-win scenario says +$850/mo — that's real
money on the table, fund it." It's a CTR-model estimate on a standard curve,
not this client's measured click behavior — evidence the opportunity is
worth pursuing, not a number for a client-facing revenue promise.
