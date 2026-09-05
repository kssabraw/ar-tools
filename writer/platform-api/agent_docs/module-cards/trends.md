# Module card — Trend Watch (algo events + seasonal demand)

**What it measures:** two portfolio-level context signals that reframe a
client's own movement — **suspected Google algorithm updates** (detected from
*cross-client* co-drops) and the client's **seasonal demand outlook** (from
12-month search-volume history). Neither is a client-specific problem detector;
both exist to stop you misattributing a drop.

**How to read the fields:**
- `algo_events` are **CROSS-CLIENT detections**: several clients opened ranking
  drops inside the same short window = a Google update, not this client's
  emergency. `clients_affected / clients_total` is the breadth; a high share is
  a strong update signal. A drop that falls inside an event window carries an
  `algo_note` on the Action Plan — **do not propose reoptimizing into a rolling
  update** (you'd be chasing a moving target and can't read the result). The
  correct posture during a live update is verify-and-wait, not act.
- `demand_outlook` is **seasonality**, not ranking: the projected next-period
  direction of *search demand* for the client's terms from their own 12-month
  volume history. **Falling demand explains falling impressions with no ranking
  problem at all** — and rising demand is *when* content/GBP pushes land
  hardest, a timing lever, not a threat.

**Known blind spots:** algo detection needs a portfolio to correlate against —
it can't confirm an update from one client, and a real update can still be
missed if too few tracked clients overlap its footprint; the demand outlook is
linear seasonality off historical volume, so it can't see a genuine demand
*shift* (a new competitor category, a market change), only the recurring cycle.
Both are context to read the client's numbers against — never a proposal on
their own.

**Worked misreading:** "Impressions fell 30% and rank slipped a point — the
client is declining, propose a reoptimization sprint." Check trends first: if an
`algo_event` covers the window, this is likely the update (wait and verify, per
the Rank Drop SOP §A); if `demand_outlook` shows the client's terms in seasonal
decline, the impression fall is demand, not a ranking loss — reoptimizing fixes
neither. Only after both are ruled out is it this client's own drop to work.
