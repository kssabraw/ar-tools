# Module card — Campaign Goals

**What it measures:** per-client success targets the team defined ("'roof
repair' to top 3 by Q4", "800 organic clicks/mo") plus a deterministic read
of progress against them. The yardstick every other module's data gets
judged against in a strategy review — a target layered on measurements the
other modules already take, not a new one.

**Direction:** lower-is-better for `keyword_position` only; every other
goal type (`keywords_in_top`, `organic_clicks`, `organic_impressions`,
`ai_visibility`, `maps_pack_presence`, `gbp_calls`/`gbp_impressions`/
`gbp_website_clicks`) is higher-is-better.

**Status is computed fresh on every read** — nothing but `achieved_at` (a
first-achieved timestamp) is stored. Six values: `achieved` / `on_track` /
`behind` / `overdue` / `no_data` / `manual`.

**How to read the fields:**
- `manual` (`goal_type="custom"`) is **never auto-measured** — status reads
  `manual` forever regardless of real progress. A placeholder, not a stalled
  goal.
- `achieved_at` is a **one-time stamp, not a lock.** Status recomputes every
  read — a keyword that hit top 3 and slipped back shows `behind`/`on_track`
  again even with `achieved_at` still set. Read current `status`, not the
  presence of `achieved_at`.
- `no_data` has two causes that look identical: the underlying module truly
  has nothing yet (no GSC property, no AI-visibility scan), OR a
  `percent_increase` goal whose baseline was 0/negative — its target is
  permanently uncomputable by design (0 × any % stays 0, which would
  otherwise read as an instant win). The second case never resolves by
  waiting; the goal needs editing.
- `progress_pct` is percent of the **baseline→target span** covered, not
  percent of the target's raw value — position 15 → target 3, now at 9,
  reads `progress_pct: 50`, not "ranked 9th."
- `on_track`/`behind` is a **projected-pace** read (progress ÷ elapsed within
  15% of plan), not "any positive movement." Below 10% elapsed the goal
  always reads `on_track` regardless of actual movement.
- `overdue` fires purely on `today > due_date` — 95% progress one day past
  due still reads `overdue`.
- `maps_pack_presence` reads only the latest **scheduled** geo-grid scan — a
  manual/on-demand scan doesn't move it. `organic_clicks`/`impressions`/
  `gbp_*` all require their underlying connection (GSC property, GBP
  metrics) to be live, else permanent `no_data` regardless of real activity.
  `ai_visibility` reads a single latest batch — carries the LABS card's
  noise caveat.

**Known blind spots:** the baseline is captured once at creation and never
auto-recaptured — a goal created right after a big loss looks easier to
"win" than the client's real history suggests.

**Worked misreading:** "This AI-visibility goal has read `no_data` for three
months — the scan must be broken." Check `target_mode` first: a
`percent_increase` goal created at 0% visibility can never compute a target
(deliberately). It's stuck by design; the fix is editing the goal, not
debugging the scanner.
