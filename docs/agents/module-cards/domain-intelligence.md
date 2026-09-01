# Module card — Domain Intelligence

**What it measures:** the competitive keyword + backlink landscape for ANY
domain (client's own site, a competitor, a prospect) — a Domain Overview
snapshot (traffic estimate, ranked-keyword count, DR/RD, traffic value) plus,
scoped to the client, a **Keyword Gap** (competitor keywords the client
doesn't rank for, or ranks weakly on) and a **Backlink Gap** (referring
domains linking to competitors but not the client). Snapshots are point-in-time
captures from DataForSEO Labs — cheap re-reads between refreshes, not a live
feed.

**Direction:** higher `organic_traffic_est` / `ranked_keyword_count` /
`traffic_value_est` / `dr` / `rd` = stronger. Higher `opportunity_score` on a
gap row = pursue first.

**How to read the fields:**
- `dr`/`rd` are **raw DataForSEO tool reads**. On a **competitor** snapshot,
  apply the suite-wide ×10 authority-target discount (SOP shared definition —
  same rule as the rank tracker and backlink modules) before treating it as a
  real threshold. The client's own snapshot is NOT rescaled (compared
  apples-to-apples elsewhere, e.g. Recipe Engine, which flags this as an
  approximation). **Never subtract a client's raw `rd` from a competitor's
  raw `rd` and call it "the real link gap."**
- `gap_type` `missing`/`weak` requires the **competitor** to rank within a
  strong threshold AND the client to be absent/weak — two sides both ranking
  poorly produces no gap row at all. Rows also require a minimum search
  volume; a real but low-volume gap is excluded, not scored zero.
- A gap set is scoped to whichever competitors were queried that run (an
  explicit list, or the client's active registry) — not automatically every
  known competitor. Check who fed the run before reading "N gaps" as the
  whole picture.
- Both sides cap at position 100 in the fetch — a client that genuinely
  ranks for a gap keyword, just past position 100, reads `gap_type: missing`
  identically to a keyword the client has no page for at all. `missing`
  means "not found within the fetch depth," not "nothing targets this."
- `captured_at` can be stale — snapshots serve from cache and refresh
  on-demand or via the weekly scheduled job; a daily paid-call budget cap
  silently skips a scheduled refresh, which looks identical to "nothing
  changed."

**Known blind spots:** competitor discovery only suggests domains from SERP
overlap on the client's own ranked terms — a competitor on different
keywords never surfaces. Backlink-gap domains come through the same
visibility-limited tool as the rest of the suite.

**Worked misreading:** "Competitor X shows `rd:38`, we show `rd:22` — we need
16 more referring domains to catch up." Wrong twice: the competitor's 38 is
tool-discounted (real target ≈×10, ~380 true referring domains), and the
client's raw 22 isn't on that corrected scale. Read `rd` gaps as directional
("meaningfully more/fewer"), not an exact link count to close.
