# Rank Drop Mitigation SOP — Maps Branch

**Current as of:** 02 July 2026 _(supersedes "How To Diagnose And Fix Geo Grid Rankings Drops")_
**Goal:** Diagnose and mitigate Google Maps (geo-grid) ranking drops.
**Who this is for:** Local clients with a GBP.
**When:** Triggered when the internal geo-grid tracker flags a drop (the tracker owns the drop definition — this SOP receives the signal).
**Assigned to:** per `_ORCHESTRATOR.md` §6, escalating per below.
**Estimated time:** 3 hours or less to diagnose.
**Scope:** Maps/geo-grid drops only. **Organic** drops are the Organic branch (active). Top-level triage (organic vs. maps) lives in `_ORCHESTRATOR.md`; this doc owns the within-maps diagnosis.

> **Cross-references:** drop definition & routing → internal tracker + `_ORCHESTRATOR.md` · task assignment → `_ORCHESTRATOR.md` §6 · budget/link decisions → **Recipe Engine** · competition & RD rules → Link Building SOP · CTR config → Agency Assassin SOP (deferred — `_ORCHESTRATOR.md` §1) · GBP/schema/neighborhood pages → Architecture SOP & Maps SOP · manual action → **Freeze Protocol** (Link Building SOP §Risk Monitoring).

---

## Step 0 — Within-Maps Triage

The tracker has already flagged a maps drop. First fork: **is the drop across the whole geo grid, or in a specific part of it?**
- **Whole grid, for a keyword** → §A.
- **Specific area/neighborhood** → §B.

**At any point, if a manual action or deindexing is found → stop and invoke the Freeze Protocol** (alert client card · pause all link building + content · notify Kyle/Ryan/Admins). Do not continue the checklist.

All task assignments below route to the roles in `_ORCHESTRATOR.md` §6. All link/budget decisions route through the **Recipe Engine** (respecting the client's margin).

---

## §A — Drops Across the Whole Grid (for a keyword)

Work the diagnostic in order; stop when you find and fix the cause.

**1. GBP relevance** — confirm the target city + service keyword appears in: GBP posts · GBP services · reviews (city or service mentioned).

**2. New competition** — check with the client / SERP for new competitors in the area.

**3. Reviews** (thresholds per Maps SOP Part 3, not this doc):
- Review velocity constant? Any in the last 30 days?
- Velocity vs. the competitors outranking them (last 30 days)?
- Review count on par with competition (per the Maps SOP floor: ≥25 and ≥ lowest-in-pack)?

**4. GBP integrity** — confirm none of these changed: still live (not suspended) · business name · primary/secondary categories · address (not hidden/changed) · no recent string of poor-sentiment reviews. *(Suspension → Freeze Protocol.)*

**5. Time-based** — are rankings only dropping off-hours? Have hours been changed (by owner/manager or by Google)?

**6. Technical (client site)** — site live · landing page returns 200 · not orphaned (check internal links in Screaming Frog) · not redirected · speed/CWV on par with or better than competitors · no manual actions. *(Manual action → Freeze Protocol.)*

**7. Content** — landing-page content not changed · no recent batch of low-quality pages/blog posts (vector-confusion risk — see Maps SOP Part 1 §Content volume & the entity vector).

**8. Off-page** — not a significant loss of referring domains · not a sudden dramatic *increase* in RD (unnatural spike) · citations still live.

**9. CTR setup** — is Agency Assassin running? radius/conversions/keywords changed? *(Tuning specifics live in the Agency Assassin SOP — route there rather than adjusting here.)*

**10. Algorithm update** — if an update occurred or is suspected → notify the Senior SEO (Kyle/Ryan). If none, continue.

**11. On-page optimization** — **invoke the page-type on-page agent** (covered: blog posts, local landing, service, location pages; uncovered types → manual with the internal on-page tools). Criteria live in **On-Page Criteria & Coverage** *(active)*. Fails → re-optimization/supplemental-content task → Minda / Ivy per §6. Passes → continue.

**12. Backlink profile vs. competition** — assess UR/DR (Ahrefs) and TF/CF (Majestic) against the SERP using the **Link Building SOP's current gates** (within-25% = client ≥ comp × 0.75; RD rule incl. the ×10 tool-visibility discount: scale competitor RD ×10, compare true-to-true, ceiling 250). If the profile is deficient, identify which variable (RD · link juice · relevance · anchor) and **create the link-building plan through the Recipe Engine** (which costs it against the client's margin and assigns it). Then:
- Assign lat/long manipulation → Minda (→ Ivy overflow) per §6 (SEO NEO task).
- Assign driving directions (GBP Blast) → Minda (→ Ivy overflow) per §6.
- Assign/confirm CTR via Agency Assassin → Kyle per §6 (clients ≥ $1,200/mo only).

---

## §B — Drops in a Specific Part of the Grid

Rebuilt around the **neighborhood-page model** (Architecture SOP — POI pages are deprecated).

**1. Is there a landing page for that city?** If not, it needs one (Architecture SOP site plan). Confirm the city landing page has: geo-relevant content · schema · inbound internal links · is indexed.

**2. Is the drop in a specific area/neighborhood of the city?**
- Confirm that area is **mentioned on the city's landing page.** If not, add it → content task to Minda / Ivy per §6. Verify the neighborhood via Google Maps / Gemini — named neighborhood, zip codes, and that it has entity/knowledge-panel presence (the Architecture SOP neighborhood-qualification test).

**3. Does a qualifying neighborhood page exist** (`/location/neighborhood/`, per the Architecture SOP)?
- If yes → confirm it's current, correctly linked to its parent location/city page, and covers the area's locally-relevant entities. Fill gaps → content task to Minda / Ivy per §6.
- If no, and the neighborhood qualifies → create it (Architecture SOP site plan; content via the pipeline).

**4. Build links to the neighborhood page** — create the plan through the **Recipe Engine** (which orders and costs it). Typical order for a neighborhood/location page: SEO NEO (location-page recipe) → Press Releases → Niche Edits → Guest Posts.

**5. Hyper Local GBP Blast** for that specific area → Minda (→ Ivy overflow) per §6, lat/longs hand-placed at the weak area (Maps SOP Part 7).

---

## Timelines & Escalation

- On-page optimizations completed within **7 calendar days** (Press Releases may take **10–14 days**).
- Completed on-page → VA uploads → crawl the pages via Search Console.
- Expect changes to begin **~2 weeks after indexing**.
- If rankings don't return and all on-page is done → run another round of link building (via the Recipe Engine).
- If after **6 weeks** rankings have not improved → notify the Senior SEO (Kyle/Ryan) for strategy review.
