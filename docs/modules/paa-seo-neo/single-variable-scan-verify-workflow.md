# PAA Content — the single-variable scan / verify workflow (v1, manual)

> **What this is.** The v1 way to measure whether a PAA set worked, using tools
> the suite already has. It is a **documented manual workflow, not a new state
> machine** — v1 deliberately does not automate the gate (that is Phase 3, PRD
> §6). Read it alongside the module orientation (`CLAUDE.md`) and the plan
> (`docs/modules/paa-seo-neo-prd-v1_0.md`).
>
> **Confidence legend (carried from `docs/reference/paa-seo-neo-master-reference.md`).**
> **[PROVEN]** = a case study / repeated result in the source transcripts ·
> **[THEORY]** = a stated model, unproven or disputed · **[BELIEF/EVOLVING]** = a
> working assumption that shifts with Google. This is one local-SEO group's working
> model, **not** official Google guidance — treat THEORY/BELIEF as heuristics.

## Why single-variable

The methodology's measurement discipline is **change one thing, then scan, so the
cause is attributable** **[PROVEN methodology]** (reference §4.11). In v1 the one
thing you changed is *the PAA content* — you created one exact-match post per buyer
question, each linking high to the service page, and did **no** link building. So a
movement (or a stall) after that is readable: it is the content layer's signal, not
a confound.

> **Hard prerequisite** **[PROVEN]** (reference §10): the client's **service page
> must already be optimized** before the PAA work, or the measurement is wasted —
> you would be reading a page that can't rank regardless of how many questions
> point at it.

## The loop (all reused suite tools — nothing new is built)

1. **Create the PAA posts.** From the PAA Content card: pull → pick ~4 → save the
   set → *Create PAA posts*. This creates one Blog Writer run per question (seeded
   from the exact PAA string), a best-effort GBP post, and refreshes syndication.
   *Verify posts* confirms each finished article states the exact question as its
   title/an H2 and links high to the service page (the deterministic checks).

2. **Let it settle ~1 week.** **[PROVEN methodology]** (reference §5.2/§5.3). The
   wait is not politeness — it is what makes the next scan attributable. Content
   moves are readable in roughly a week; do **not** stack any authority work on top
   during this window (there is none in v1 anyway — that layer is out of scope).

3. **Scan — single-keyword Maps geo-grid.** Run a **per-keyword** geo-grid scan for
   the service keyword (Rankings → Maps geo-grid; the suite already supports
   scanning a subset of keywords — see `local_dominator.resolve_scan_keywords` and
   the "Run scan now" keyword-scope picker). One keyword, one variable. The
   geo-grid is the suite's single-variable local-rank instrument, run exactly as
   the methodology's "scan" step intends.

   > A scan you run by hand is a **one-off** — by owner ruling it is deliberately
   > excluded from the client's reporting series and does **not** open rank/maps
   > alerts (it is measurement, not a tracked baseline). To make a scan the tracked
   > baseline the verify loop watches, use a **scheduled** geo-grid scan.

4. **Read the branch** **[PROVEN model]** (reference §5.3):
   - **Moved →** the content layer did its job. Proceed to the **next
     topically-related service** (a new PAA set for the next high-revenue service).
   - **No movement →** **drill deeper**: pull sub-questions (more specific PAAs
     under the same service), up to ~4 levels. Add them as another PAA set for the
     same service and repeat the loop.
   - **Main revenue service still stuck after drilling → HALT.** Something upstream
     is wrong (on-page, entity, the service page itself). **More PAAs will not fix
     it** — stop adding content and re-check on-page/entity. This is the
     methodology's explicit stop condition, not a suggestion to keep writing.

5. **Track the cadence with response-episodes.** The suite's **response-episode
   tracking** (`services/response_episodes.py`) is the verify/refresh clock: an
   episode opens on a scheduled scan's alert with the keyword's baseline, rechecks
   on its ~14-day cadence, marks **recovered** when the tracker resolves, and
   **escalates** if there is no movement after the escalation window. Use it as the
   "did it move, and by when" loop rather than eyeballing scans. **Re-scan cadence
   for content-only moves is weeks, not days** **[BELIEF/EVOLVING]** — link-based
   moves are slower still, but v1 has no link layer.

6. **Rinse per service, on maintenance cadence.** **[BELIEF/EVOLVING]** (reference
   §5.2): local rankings slip as Google shrinks map proximity, so the loop is a
   maintenance cycle (roughly every 6 weeks–3 months per service), not a one-shot.

## What v1 does NOT do here (on purpose)

- **No automated gate / state machine.** Steps 3–4 are read and decided by a human.
  The automated "scan → moved/drill/HALT" loop is **Phase 3** (PRD §6), built only
  after the content half is proven.
- **No authority-layer execution.** The methodology's next move after "moved" often
  involves the **SEO Neo authority layer** (links / RD 100 / GMBB Blast / PBNs).
  **The suite never runs any of that** (PRD §9, permanent guardrail) — it is
  off-platform vendor work, tracked/costed/handed-off at most, and not in v1 at all.
- **No new measurement infrastructure.** Everything above is the existing Maps
  geo-grid + response-episodes. This doc is the workflow; there is no new table,
  job, or agent behind it.
