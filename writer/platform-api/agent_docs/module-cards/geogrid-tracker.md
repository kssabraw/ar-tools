# Module card — Maps Geo-Grid Tracker (Local Dominator)

**What it measures:** where the client's **GBP** ranks in Google's *local
pack / Maps results*, sampled from a grid of pin locations around the business
(e.g. 5×5 = 25 simulated searcher positions). Channel: local pack only — a
completely different ranking system from organic (proximity, GBP signals,
reviews), with different fixes.

**Direction:** lower = better (rank 1–3 = the local pack).

**How to read the fields (per keyword, per scan — `maps_scan_results`):**
- `average_rank` is the mean **only over pins where the client appeared**.
  **Never read it without `found_pins/total_pins`.** 3/25 pins at average 2.0
  means *barely present* (found in a tiny island, invisible elsewhere) — not
  "ranking #2 across the area."
- `top3_pins` = pins where the client is in the local pack. `top3_pins /
  total_pins` is the honest "pack presence" number.
- **SoLV** (share of local voice) = the client's share of top-3 presence vs
  competitors across the grid — the market-share read.
- `rank_grid` is the spatial map; weak areas are geocoded to real nearby
  cities (`report_weak_locations`) — those names feed location-page targeting.
- Cadence: **weekly** scans (plus on-demand). A single scan-over-scan wobble
  of ±1 on a few pins is noise; `maps_alerts` already encode the real drops
  (`grid_rank_drop`, `coverage_drop`, `lost_pack`, `area_decline`,
  `competitor_surge`; `resolved_at = null` = open).

**Known blind spots:** the grid samples the configured radius — a client can
rank fine outside it; SABs (hidden address) have dampened proximity signals by
design; rankings vary by keyword — one keyword's grid says nothing about
another's.

**Worked misreading:** "average_rank improved 5.8 → 3.9, great progress."
Check coverage first: if `found_pins` also fell 22 → 9, the client *lost*
presence — the average improved only because the remaining pins are the easy
ones near the office. Coverage first, average second.
