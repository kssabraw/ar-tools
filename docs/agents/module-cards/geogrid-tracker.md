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

**Keyword hygiene — never bake a city into a geo-grid keyword (query-artifact
trap):** a geo-grid already supplies the geography by *moving the search pin*
across the grid — that is the entire mechanism. Putting an explicit city in the
tracked keyword ("Manufactured Home **Navarre OH**" instead of "Manufactured
Home") double-specifies location and can distort Google's Maps response: Google
starts **entity-matching on the city token** and, near a competitor whose name
contains that token, collapses the result to a single best-name-match business —
so the client drops out of a one-slot pack and the grid paints **false
"not-ranking" pins, often right at the center** (the business's own location).
This is NOT a scan failure and NOT a real visibility gap; every pin returned
data. It is a bad-keyword artifact. It is also **unpredictable** — the same city
qualifier is harmless on a query with no like-named competitor — which is exactly
why the rule is "don't do it," not "watch for it."

- **Tell:** "not ranking" pins clustered at/near the center for a *city-in-name*
  keyword, while the client ranks fine elsewhere and where it does appear it's
  top-1–3.
- **Diagnose (before calling it a real gap):** compare the same scan's bare /
  "near me" sibling keyword at the same pins; if that sibling shows the client
  in a full pack there, the city qualifier is the cause. (At the pin level the
  distorted keyword returns a 1-business pack that is the like-named competitor.)
- **Fix:** track the bare service term ("Manufactured Home", "Housing
  Development", optionally "… Near Me"); the pins carry the geography.

**Worked example (Lake Sherman Village, Navarre OH, 2026-09-10):** a completed,
fully-successful scan (all 388 pins returned data, 0 failures). Keyword
"Manufactured Home Navarre OH" showed the client not-ranking at the center and
to the west; at those pins DataForSEO returned a single-business pack containing
only "Navarre Village" (a competitor community physically west of center whose
name matches "Navarre"). The sibling "Manufactured Home Near Me" — *same scan,
same center coordinates* — returned full 4–5-business packs with the client at
**#1** at the exact same center pins. Same run, same place ID, opposite reading:
the city-in-keyword collapsed the pack. Correct interpretation: the center
gap was a query artifact, not lost visibility.

**GBP levers — what actually moves the local pack:** relevance (categories,
business name), distance/proximity, and prominence (review count / velocity /
quality, links). The GBP **business description is NOT a local-pack ranking
factor** — never present it as a Maps relevance signal. A complete description
(and overall GBP completeness) matters for **AI visibility** instead (AIO/AEO
SOP: GBP completeness ≈ 40% of local AI visibility factors, working model) —
attribute description advice there, not to pack rank.

**Worked misreading:** "average_rank improved 5.8 → 3.9, great progress."
Check coverage first: if `found_pins` also fell 22 → 9, the client *lost*
presence — the average improved only because the remaining pins are the easy
ones near the office. Coverage first, average second.
