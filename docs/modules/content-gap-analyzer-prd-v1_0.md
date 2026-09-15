# Content Gap Analyzer — Module PRD v1.0

**Status:** proposed (owner decisions locked 2026-09-15; not yet built)
**Authors:** owner + Claude
**Related:** `serp-snapshot` (in Organic Rank Tracker), `domain-intelligence-module-prd-v1_0.md`, `local-seo-module-integration-plan-v1_0.md` (the nlp-api SERP-analysis + scoring spine + reoptimize), `organic-rank-tracker-prd-v1_0.md`

---

## 1. What this is

A per-client module that answers one question for a chosen set of **keywords × money pages**: *are we winning the SERP, and if not, exactly what do the competitors above us have that we don't?*

For each keyword the module checks whether the client's page is **in the top-10 organic AND cited in the AI Overview (AIO)**. When either is missing, it identifies the competitors ranking above the client (and any registered competitor present in that SERP) and produces a structured, dated **gap report** across authority, traffic, entity, and on-page-content dimensions — the same measurements the suite already computes for content generation, assembled here as a *diff* instead of as generation input.

The report's output is deliberately shaped as the **deficiency input the reoptimization pipeline already accepts**, so a gap report is one click from "reoptimize this page against these gaps."

**This is an assembly/diff layer over existing paid calls, not a new analysis engine.** ~80% of the signals are already produced by `serp_snapshot`, `dataforseo_labs`, `page_structure_eval`, and the nlp-api SERP-analysis pass. The net-new work is orchestration, the on-page diff assembler, persistence, cadence, and the client surface.

---

## 2. Locked decisions (owner, 2026-09-15)

1. **Cadence:** monthly auto-run over the client's most important URLs + main keywords, **plus ad-hoc** on demand. Own daily paid-call budget meter (fail-closed reservation, mirrors `domain_intel_usage` + `reserve_domain_intel_calls`).
2. **Threshold:** top **10** organic. Target state = **both** top-10 organic **AND** AIO citation.
3. **Competitors analyzed:** those ranking **above the client** for the keyword — **union** of (a) organic results above the client and (b) `client_competitors` registry entries appearing in that SERP.
4. **DFS traffic estimates** are acceptable, including in client-facing output (directional, carry the "estimated" label).

### 2.1 Win/gap matrix (confirm the ⚠️ "no-AIO" row)

| Client state for a keyword | Verdict | Competitor set for the gap |
|---|---|---|
| Top-10 organic **and** in AIO | ✅ win — skip | — |
| Top-10 organic, **not** in AIO | ⚠️ AIO gap | who is **cited in AIO** that the client isn't |
| In AIO only (not top-10) — *"not ranking"* | ⚠️ organic gap | competitors ranking **above** (all top-10, client has no organic pos) |
| Neither | ⚠️ full gap | competitors above (all top-10) + AIO-cited set |

---

## 3. Gap dimensions

Marked **[reuse]** (already computed elsewhere), **[free]** (derivable from HTML the suite already scrapes), or **[+1 call]** (one extra billed call).

### 3.1 Owner's original 8

1. **Entity gap** — entities the competitors' pages carry that the client's doesn't. **[reuse]** nlp-api `_run_serp_analysis` entity extraction; `entity_provider` per-request (`textrazor` default | `google`), already built end-to-end.
2. **RD gap** — referring domains, page-level and domain-level. **[reuse]** `serp_snapshot.fetch_backlinks_summary` (per-page RD/UR) + domain-intel link-gap + `page_backlink_profiles`.
3. **DA / DFS-equivalent gap** — domain authority. **[reuse]** `serp_snapshot.collect_snapshot_domains` per-domain DR + `dataforseo_labs.parse_domain_rank_overview`. DR is the DA-equivalent — carry the standing **×10 RD** / "tool-read, not Moz DA" caveat used elsewhere in the suite.
4. **Headings / subtopic gap** — which H2/H3 subtopics competitors cover that the client doesn't. **[reuse]** `page_structure_eval.extract_outline_from_html` (outline + per-section word counts + block types) + the nlp `CONTENT_GAPS_REPORT`.
5. **Site traffic gap.** **[reuse]** `dataforseo_labs.fetch_bulk_traffic` (`bulk_traffic_estimation`).
6. **Page traffic gap.** **[reuse]** `dataforseo_labs.fetch_ranked_keywords` scoped to the competitor URL → summed estimated traffic for that page.
7. **Title diff.** **[free]** from scraped HTML (client + competitor `<title>`).
8. **Meta-description diff.** **[free]** from scraped HTML.

### 3.2 Easy additions (recommended for v1)

- **AIO citation gap** — *who is cited in the AI Overview that the client isn't.* **[reuse]** `serp_snapshot.extract_aio` already captures AIO cited sources; this is a set-diff. The single most on-brand signal for an "AIO + top-10" module.
- **Word-count gap.** **[reuse]** `page_structure_eval.word_count_of`; the `length_fit` engine already targets SERP-avg words.
- **Structured-data / schema gap** — FAQ / Product / HowTo / Article JSON-LD competitors have that the client doesn't. **[free]** parse `<script type="application/ld+json">` from HTML already scraped. (nlp scorer already has a `structured_data` engine.)
- **Content-element gap** — tables / lists / FAQ blocks / CTAs present per section. **[reuse]** `page_structure_eval.block_types_of`.
- **Heading-count + question-heading gap** — count of H2/H3 and how many are phrased as questions (AEO signal). **[free/reuse]**
- **Internal-link count**, **image count + alt coverage**, **URL/H1 keyword match**. **[free]** (QA already checks title/URL/H1 keyword presence).
- **PAA coverage gap** — People Also Ask questions in the SERP the client's page doesn't answer. **[reuse]** `serp_snapshot` / `keyword_research_serp` already pull PAA.
- **Freshness gap** — competitor `dateModified` (from schema) vs client last-updated. **[free]**

### 3.3 Deferred (v1.1+)

- Page topical breadth (count of keywords the competitor's *specific URL* ranks for) — **[+1 call]** per competitor URL.
- SERP-feature ownership (featured snippet / image pack / video). **[reuse]** `extract_serp_features`, but low priority.
- Core Web Vitals / page-speed gap (DFS on-page/Lighthouse) — **[+1 call]**, defer.
- Reading-level gap (deterministic, cheap) — nice-to-have.

---

## 4. The on-page diff (answers "how does our content stack up?")

The suite **already runs this exact analysis at generation time and discards it.** For every Local SEO / ecommerce page it generates, `_run_serp_analysis` scrapes the top competitors, extracts entities, runs `page_structure_eval`, and computes the 8-engine rubric + `serp_signal_coverage`.

The on-page gap is that same pass, but:
1. Run it against the **client's existing live URL** (scrape it the same way as competitors), and
2. Present a **side-by-side diff** (client column vs. competitor columns) instead of feeding it to a writer.

So the net-new code is a pure `build_onpage_diff(client_page, competitor_pages)` assembler over outputs the suite already trusts — **no new scoring engine.** It emits the per-dimension gaps in §3 plus a headline "content completeness vs. SERP" read.

---

## 5. Reuse map (the point of this doc)

| Concern | Existing surface |
|---|---|
| One billed SERP per keyword + parsers | `serp_snapshot.fetch_serp`, `extract_organic_results`, `find_client_organic`, `count_targeted` |
| AIO presence + cited sources | `serp_snapshot.extract_aio` |
| SERP features / intent | `serp_snapshot.extract_serp_features`, `classify_intent`, `derive_intent_signals` |
| Per-page RD/UR, per-domain DR | `serp_snapshot.fetch_backlinks_summary`, `collect_snapshot_domains`, `parse_backlinks_summary` |
| Domain rank / traffic estimates | `dataforseo_labs.fetch_domain_rank_overview`, `fetch_bulk_traffic`, `fetch_ranked_keywords` |
| Competitor discovery | `dataforseo_labs.fetch_competitors_domain` + `client_competitors` registry (`competitor_intel`) |
| Entity extraction (textrazor/google) | nlp-api `_run_serp_analysis` + `entity_provider` |
| Page outline / word count / blocks / structure diff | `page_structure_eval.*` |
| Competitor page scrape | the ScrapeOwl path inside `_run_serp_analysis` |
| Keyword market data (volume/CPC) | `keyword_market` |
| Metering pattern | `domain_intel_usage` + `reserve_domain_intel_calls` RPC |
| Reoptimize handoff | the existing reoptimize deficiency input (Local SEO / ecommerce / blog) |
| Snapshot-persistence pattern | `serp_snapshots` / `serp_snapshot_results` |

---

## 6. Competitor selection (locked: "both")

For a gapped keyword, the competitor set is the **union** of:
- **A. Organic-above** — organic results ranking above the client's position (all top-10 when the client isn't ranking).
- **B. Registered** — `client_competitors` entries whose domain appears in that SERP.

For the **AIO-gap** dimension specifically, the relevant set is instead **who is cited in the AIO** (which may include domains outside the organic top-10). Deep dimensions (entity/on-page scrape) run against a capped set (config `content_gap_max_competitors`, default ~5, strongest-first by position) to bound scrape cost.

---

## 7. Data model (proposed)

Mirrors the `serp_snapshots` shape so re-opening a run is a cheap re-read and each run is metered once.

- **`content_gap_runs`** — one per (client, trigger, created_at). `trigger ∈ {scheduled, manual}`, `location_code`, `language_code`, status, cost, `entity_provider`, summary rollups (keywords analyzed / wins / gaps).
- **`content_gap_keywords`** — one per (run, keyword × page). Client organic position, `in_aio` bool, `verdict` (win / aio_gap / organic_gap / full_gap), the resolved competitor set, per-dimension gap payload (jsonb), the on-page diff (jsonb).
- **`content_gap_usage`** — own daily paid-call meter + `reserve_content_gap_calls` RPC (fail-closed).

`async_jobs` CHECK += `content_gap_scan` (rebuild from the live constraint, per the standing migration rule).

The "most important URLs + main keywords" scope is resolved from existing data — `tracked_keywords` (+ their `canonical_url`) and/or an explicit per-run selection — not a new inventory table.

---

## 8. Cadence, jobs, API

- **Async job** `content_gap_scan` (`job_worker` dispatch). One run = the selected keyword×page set; per keyword: 1 SERP call (reused parsers for organic + AIO + features + PAA), backlink summaries for the capped competitor set, bulk-traffic for their domains, one scrape+entity pass per capped competitor + the client URL.
- **Monthly scheduler hook** `enqueue_due_content_gap_scans` on the shared `gsc_scheduler` (daily due-check, `content_gap_interval_days`=30, `content_gap_auto_enabled`), self-gated + budget-guarded.
- **API** `routers/content_gap.py`: `POST …/content-gap/scan` (ad-hoc), `GET …/content-gap/runs[/{id}]`, `GET …/content-gap/estimate` (free preflight), job-status poll, CSV export.
- **Reoptimize handoff:** a per-keyword "Reoptimize against these gaps" action that seeds the existing reoptimize flow (Local SEO / ecommerce / blog by page type) with the run's deficiencies.

---

## 9. Frontend

A "Content Gap" workspace card + `pages/ContentGap.tsx` (route `clients/:id/content-gap`): run-now + scope picker (keywords/URLs), a keyword table (verdict chip · client pos · AIO ✓/✗ · competitor count), and a per-keyword drill-in showing the competitor set and the per-dimension diff (authority / traffic / entity / on-page structure / title+meta), with a "Reoptimize" button per gapped page. Follows the `serp_snapshot` / rank-report modal precedent; dependency-free.

---

## 10. Cost

Dominated by, per gapped keyword: 1 SERP + N backlink summaries + N bulk-traffic + (N+1) scrapes + (N+1) entity passes, N capped at `content_gap_max_competitors`. Monthly × (main keywords) is a real recurring spend — hence the dedicated fail-closed meter and the free `estimate` preflight surfaced in the UI before every run. Wins short-circuit (no deep dimensions), so a healthy client is cheap.

---

## 11. Open items

- **Confirm the win/gap matrix §2.1** — specifically whether "top-10 organic but not in AIO" is a gap (assumed) or a win.
- Real DataForSEO daily ceiling for the meter default (placeholder pending owner's number, like domain-intel).
- Whether the on-page diff is client-facing verbatim or internal-only with a softened client summary (tone ruling, like the other client reports).
- "Most important URLs" definition for the monthly auto-scope — money pages from `tracked_keywords.canonical_url`, or an explicit per-client pin.
