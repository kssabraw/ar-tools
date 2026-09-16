# Content Gap Analyzer — Module PRD v1.0

**Status:** proposed (owner decisions locked 2026-09-15; not yet built)
**Authors:** owner + Claude
**Related:** `serp-snapshot` (in Organic Rank Tracker), `domain-intelligence-module-prd-v1_0.md`, `local-seo-module-integration-plan-v1_0.md` (the nlp-api `/analyze` + `/score-page` + reoptimize spine), `organic-rank-tracker-prd-v1_0.md`

> **Revision 2026-09-15 (post adversarial review).** The first draft's reuse map named several surfaces that don't do what it claimed. Corrected here: the reoptimize handoff routes through `/score-page` (it does **not** accept a free-form gap payload — §11.1); the trigger reads the **existing** `serp_snapshots` capture instead of re-buying it (§4, §8, §10); the win/gap matrix gained a **no-AIO-on-SERP** branch (§2.1); page-level traffic (#6) has **no** direct reuse and is now a labelled modeled estimate (§3.1); the entity gap (#1) uses `/score-page`'s existing entity engines for the client side, since no endpoint returns a raw client entity list (§3.1, §4). The optimistic "~80% already built" framing is replaced with a per-dimension reuse/build split (§5). Grounding evidence for each change is cited inline.

---

## 1. What this is

A per-client module that answers one question for a chosen set of **keywords × money pages**: *are we winning the SERP, and if not, exactly what do the competitors above us have that we don't?*

For each keyword the module checks whether the client's page is **in the top-10 organic AND cited in the AI Overview (AIO)** — when an AIO exists on that SERP. When either is missing, it identifies the competitors ranking above the client (and any registered competitor present in that SERP) and produces a structured, dated **gap report** across authority, traffic, entity, and on-page-content dimensions.

**This is an assembly / diff / presentation layer over surfaces the suite already runs** — the `serp_snapshots` capture, the nlp-api `/analyze` and `/score-page` endpoints, `dataforseo_labs`, and `page_structure_eval`. The net-new work is orchestration, an on-page diff assembler, persistence, cadence, metering, and the client surface. It builds **no new scoring engine**, and (per §11.1) it does not replace the reoptimize pipeline — it diagnoses; the existing `/score-page → /reoptimize-page` flow fixes.

---

## 2. Locked decisions (owner, 2026-09-15)

1. **Cadence:** monthly auto-run over the client's most important URLs + main keywords, **plus ad-hoc** on demand. Own daily paid-call budget meter (fail-closed reservation, mirrors `domain_intel_usage` + `reserve_domain_intel_calls` — verified pattern, `writer/supabase/migrations/20260712120000_domain_intelligence.sql`).
2. **Threshold:** top **10** organic. Target state = **both** top-10 organic **AND** AIO citation, *when an AIO is present on that SERP*.
3. **Competitors analyzed:** those ranking **above the client** for the keyword — **union** of (a) organic results above the client and (b) `client_competitors` registry entries appearing in that SERP.
4. **DFS traffic estimates** are acceptable, including in client-facing output (directional, carry the "estimated" label).

### 2.1 Win/gap matrix

`extract_aio` returns `{"present": bool, "sources": [...]}` — and returns `present: False` for the many SERPs that carry no AI Overview at all (`serp_snapshot.py:343`). So the AIO axis is **three-valued**, not binary:

| Client state for a keyword | Verdict | Competitor set for the gap |
|---|---|---|
| Top-10 organic **and** cited in AIO | ✅ win — skip | — |
| Top-10 organic; **AIO present** but client not cited | ⚠️ AIO gap | who is **cited in AIO** that the client isn't |
| Top-10 organic; **no AIO on this SERP** | ✅ win (organic-only judged) | — |
| In AIO only (not top-10) — *"not ranking"* | ⚠️ organic gap | competitors ranking **above** (all top-10, client has no organic pos) |
| Not top-10, **AIO present**, not cited | ⚠️ full gap | competitors above (all top-10) + AIO-cited set |
| Not top-10, **no AIO** | ⚠️ organic gap | competitors ranking above (all top-10) |

**Rule:** the AIO axis only ever produces a gap when `aio.present == True`. When no AIO exists on the SERP, the verdict is judged on organic position alone (top-10 = win). This prevents every no-AIO keyword the client ranks well for from being permanently flagged as an unfixable "AIO gap" with an empty competitor set.

---

## 3. Gap dimensions

Marked **[reuse]** (surface already produces it), **[free]** (derivable from HTML the suite already scrapes), **[+1 call]** (one extra billed call), or **[build]** (needs new code / wrapper work — no clean reuse).

### 3.1 Owner's original 8

1. **Entity gap** — entities the SERP/competitors carry that the client's page doesn't. **[reuse + build]** The SERP side is `/analyze`'s `google_entities` (already called by platform-api, `local_seo_service.py:531`; `entity_provider` = `textrazor` default | `google`). **Note:** these are **SERP-aggregated** (grouped by entity id with a `page_spread` count across competitors, `nlp-api/main.py:2372`), not per-competitor lists — which is actually the right shape for a gap ("how many of the top competitors carry this entity"). There is **no endpoint that returns the client page's own raw entity list**, so the *client side* of the diff is not free: use `/score-page` on the client URL, whose `entity_establishment` + deterministic `serp_signal_coverage` engines already compute client-vs-SERP entity coverage and emit it as deficiencies. Optionally enrich the display with `/analyze`'s aggregated entity list ("the SERP covers these entities; you're missing N").
2. **RD gap** — referring domains, page-level and domain-level. **[reuse]** already captured in the `serp_snapshots` run: `fetch_backlinks_summary`→per-page RD/UR (`referring_domains`/`url_rating`, `serp_snapshot.py:523`), `fetch_domain_summary`→per-domain RD (`serp_snapshot.py:633`).
3. **DA / DFS-equivalent gap** — domain authority. **[reuse]** per-domain DR from `fetch_domain_summary` (`domain_rating`, 0–1000). Carry the standing **×10 RD / "tool-read, not Moz DA"** caveat used elsewhere in the suite.
4. **Headings / subtopic gap** — which H2/H3 subtopics competitors cover that the client doesn't. **[reuse]** `page_structure_eval.extract_outline_from_html` (confirmed in platform-api, `writer/platform-api/services/page_structure_eval.py`) on the client's scraped HTML + the top competitors' scraped HTML (URLs come from the SERP snapshot; scrape via `website_scraper.scrapeowl_fetch`, `website_scraper.py:35`). Diff the outlines. (The nlp `/analyze` competitor scrape is **not** exposed standalone — `page_structure_eval` on separately-scraped HTML is the reuse path.)
5. **Site traffic gap.** **[reuse]** `dataforseo_labs.fetch_bulk_traffic` (domain ETV, `parse_bulk_traffic:179`) + `competitors_domain.organic_etv`.
6. **Page traffic gap.** **[build — no clean reuse].** `fetch_ranked_keywords` accepts a **domain** target only (`target_domain`, `dataforseo_labs.py:380`) with no page scoping, and its rows carry search **volume**, not ETV (`parse_ranked_keywords:141-149`) — so per-page traffic cannot be summed from it directly. v1 approach: a **labelled modeled estimate** — fetch the competitor domain's ranked keywords, filter to the target URL (rows carry `url`), and estimate page traffic as Σ(volume × position-CTR) using the existing `forecasting.CTR_CURVE`. Rendered explicitly as "estimated (modeled)". Deferred alternative (v1.1): extend the wrapper to accept a page target + parse `etv`.
7. **Title diff.** **[free]** client + competitor `<title>` from scraped HTML.
8. **Meta-description diff.** **[free]** from scraped HTML.

### 3.2 Easy additions (recommended for v1)

- **AIO citation gap** — *who is cited in the AI Overview that the client isn't.* **[reuse]** `serp_snapshot.extract_aio` already returns the cited sources (`{url, domain, title}`, `serp_snapshot.py:338`); set-diff against the client domain. Only computed when `aio.present`.
- **Word-count gap.** **[reuse]** `page_structure_eval.word_count_of`; the `length_fit` engine already targets SERP-avg words.
- **Structured-data / schema gap** — FAQ / Product / HowTo / Article JSON-LD competitors have that the client doesn't. **[free]** parse `<script type="application/ld+json">` from HTML already scraped.
- **Content-element gap** — tables / lists / FAQ blocks / CTAs per section. **[reuse]** `page_structure_eval.block_types_of`.
- **Heading-count + question-heading gap** (AEO signal). **[free/reuse]**
- **Internal-link count**, **image count + alt coverage**, **URL/H1 keyword match.** **[free]**
- **PAA coverage gap** — People Also Ask questions in the SERP the client's page doesn't answer. **[reuse]** already pulled in the SERP snapshot / `keyword_research_serp`.
- **Freshness gap** — competitor `dateModified` (from schema) vs client last-updated. **[free]**

### 3.3 Deferred (v1.1+)

- True page-level traffic via a wrapper extension (page target + ETV parsing) — replaces the #6 modeled estimate.
- Page topical breadth (keyword count the competitor's URL ranks for) — **[+1 call]** per competitor URL.
- SERP-feature ownership (`extract_serp_features`) — low priority.
- Core Web Vitals / page-speed gap — **[+1 call]**, defer.
- Reading-level gap (deterministic) — nice-to-have.

---

## 4. The on-page diff (answers "how does our content stack up?")

The suite already runs this analysis at generation time and discards it. The module reruns the reusable pieces against the **client's live URL** and presents a diff.

Concretely, per gapped keyword:
1. **Trigger + authority + AIO** come from the client's **latest `serp_snapshots` row** (see §8 — reused, not re-captured when fresh): AIO cited sources, top-10 organic + client position, per-page RD/UR, per-domain DR, topical focus.
2. **Entity + structure + signal deficiencies** come from **`/score-page` on the client URL** (it scrapes and scores the live page internally — `reoptimize_url` already sends `page_content: None, page_url: page_url`, `local_seo_service.py:1697`), which returns the client-vs-SERP entity, structural, and signal-coverage deficiencies directly.
3. **Competitor outlines** (for the headings/subtopic + word-count + element + title/meta diffs) come from `scrapeowl_fetch` on the top competitor URLs + `page_structure_eval`.
4. **Traffic + market columns** come from `bulk_traffic` / `competitors_domain` / `keyword_overview` (§3.1 #5, #6).

So the net-new code is a pure `build_onpage_diff(client_signals, competitor_signals)` assembler over outputs the suite already produces — **no new scoring engine.** Much of the entity/structure gap is *already* what `/score-page` returns; the module's value is assembling it into a competitor-anchored, client-facing diff and joining it to the authority/traffic columns.

### 4.1 Empty / failure states (each dimension degrades independently)

- **No AIO on the SERP** → AIO axis N/A, judge on organic (§2.1).
- **Client URL 404 / bot-blocked** (ScrapeOwl 401/429 — the suite records hard bot-blocks on some hosts) → the on-page diff's client column is marked `unavailable`, not "client has zero of everything"; authority/traffic dimensions still render.
- **Competitor page scrape fails** → that competitor's structure column is `unavailable`; it still counts for RD/DR/traffic.
- **Keyword has no mapped client page** (client isn't ranking and no `canonical_url`) → verdict is organic gap with the "create a page" framing; on-page diff is competitor-only.
- **`/score-page` or `/analyze` call fails** → the entity/structure dimensions degrade to the deterministic `page_structure_eval` diff only; the run completes with those dimensions flagged `unavailable`.

---

## 5. Reuse / build split (replaces the "~80%" framing)

| Dimension | Data source | Reuse or build |
|---|---|---|
| Trigger: AIO present + cited, organic position | latest `serp_snapshots` row (`extract_aio`, `find_client_organic`) | **reuse** (read existing capture) |
| #2 RD (page + domain) | `serp_snapshots` (`fetch_backlinks_summary`, `fetch_domain_summary`) | **reuse** |
| #3 DR | `serp_snapshots` (`domain_rating`) | **reuse** |
| #5 Site traffic | `dataforseo_labs.fetch_bulk_traffic` / `competitors_domain` | **reuse** |
| #7/#8 Title/meta | scraped HTML | **reuse (free)** |
| AIO citation gap, schema, word-count, elements, PAA, freshness, links/images | `serp_snapshots` + scraped HTML + `page_structure_eval` | **reuse (free)** |
| #4 Headings/subtopic | `scrapeowl_fetch` + `page_structure_eval` on client + competitors | **reuse (wiring)** |
| #1 Entity gap | `/analyze` (SERP side, aggregated) + `/score-page` (client side) | **reuse (wiring)** — client-side raw entity list has no endpoint; use the score engines |
| #6 Page traffic | modeled `Σ volume × CTR` via `forecasting.CTR_CURVE` | **build** (labelled estimate; true page ETV deferred) |
| On-page diff assembler | new `build_onpage_diff(...)` pure fn | **build** |
| Metering + job + tables + UI | new | **build** |

Supporting reuse verified: metering pattern (`reserve_domain_intel_calls`, `reserve_keyword_research_calls` — established, fail-closed), `client_competitors` (`20260707050000_competitor_registry.sql`) + `competitor_intel` service, `tracked_keywords.canonical_url` (`20260622183357_rank_tracker_keywords.sql:23`).

---

## 6. Competitor selection (locked: "both")

For a gapped keyword, the competitor set is the **union** of:
- **A. Organic-above** — organic results ranking above the client's position (all top-10 when the client isn't ranking).
- **B. Registered** — `client_competitors` entries whose domain appears in that SERP.

For the **AIO-gap** dimension specifically, the relevant set is instead **who is cited in the AIO** (which may include domains outside the organic top-10). Deep dimensions (entity/on-page scrape) run against a capped set (`content_gap_max_competitors`, default ~5, strongest-first by position) to bound scrape cost.

---

## 7. Data model (proposed)

- **`content_gap_runs`** — one per (client, trigger, created_at). `trigger ∈ {scheduled, manual}`, `location_code`, `language_code`, status, cost, `entity_provider`, summary rollups (keywords analyzed / wins / gaps).
- **`content_gap_keywords`** — one per (run, keyword × page). Client organic position, `aio_present` + `in_aio` (three-valued per §2.1), `verdict` (win / aio_gap / organic_gap / full_gap), the resolved competitor set, per-dimension gap payload (jsonb), the on-page diff (jsonb), the `serp_snapshot_id` it read from (or `captured_fresh: true`).
- **`content_gap_usage`** — own daily paid-call meter + `reserve_content_gap_calls` RPC (fail-closed, copied from `reserve_domain_intel_calls`).

`async_jobs` CHECK += `content_gap_scan` (rebuild from the live constraint, per the standing migration rule).

The "most important URLs + main keywords" scope resolves from existing data — `tracked_keywords` (+ their `canonical_url`) and/or an explicit per-run selection (§11.4) — not a new inventory table.

---

## 8. Cadence, jobs, API

- **Async job** `content_gap_scan` (`job_worker` dispatch).
- **Trigger data reuse (the cost-critical decision):** a full `serp_snapshots` capture fires **~20–25 DataForSEO calls per keyword** (SERP + intent + per-URL backlinks + per-domain summaries, `serp_snapshot.py:534` comment). The module therefore **reads the client's latest `serp_snapshots` row when it is within `content_gap_snapshot_max_age_days`** (default 30, matching the monthly cadence) and only **enqueues a fresh capture when the snapshot is stale or absent.** This reuses the rank tracker's weekly auto-capture instead of double-buying AIO/organic/RD/DR the suite already stored.
- **Per gapped keyword, net-new spend** (on top of a reused snapshot): `bulk_traffic` (batched over competitor domains) + `keyword_overview` (batched) + one `/analyze` nlp call (SERP entities — itself an nlp scrape+entity op) + one `/score-page` nlp call on the client URL + `scrapeowl_fetch` × capped competitors for the structure diff. **Wins short-circuit** (no deep dimensions), so a healthy client is cheap.
- **Monthly scheduler hook** `enqueue_due_content_gap_scans` on the shared `gsc_scheduler` (daily due-check, `content_gap_interval_days`=30, `content_gap_auto_enabled`), self-gated + budget-guarded.
- **API** `routers/content_gap.py`: `POST …/content-gap/scan` (ad-hoc), `GET …/content-gap/runs[/{id}]`, `GET …/content-gap/estimate` (free preflight), job-status poll, CSV export.

---

## 9. Frontend

A "Content Gap" workspace card + `pages/ContentGap.tsx` (route `clients/:id/content-gap`): run-now + scope picker (keywords/URLs), a keyword table (verdict chip · client pos · AIO ✓/✗/N-A · competitor count), and a per-keyword drill-in showing the competitor set and the per-dimension diff (authority / traffic / entity / on-page structure / title+meta), each dimension able to render an `unavailable` state (§4.1). A "Reoptimize this page" button per gapped page triggers the handoff in §11.1. Follows the `serp_snapshot` / rank-report modal precedent; dependency-free.

---

## 10. Cost

Dominated per gapped keyword by: a possibly-reused snapshot (0 new calls when fresh; ~20–25 DFS calls when stale) + `bulk_traffic` + `keyword_overview` (both batched) + one `/analyze` + one `/score-page` + up to `content_gap_max_competitors` scrapes. The snapshot-reuse rule (§8) is the main cost lever — a monthly run over keywords the rank tracker already snapshots weekly pays only the labs + on-page-score delta. Wins short-circuit to ~0. The dedicated fail-closed meter + the free `estimate` preflight (surfaced in the UI before every run) bound the spend.

---

## 11. Open items & handoff

### 11.1 Reoptimize handoff (corrected)

The reoptimize pipeline does **not** accept a free-form gap report. Its `deficiencies` are specifically `/score-page`'s 8-engine output — `{engine, engine_key, score, issues, recommendations}` — rendered with direct key access (`d['engine']`, `d['score']` → `KeyError` if absent, `nlp-api/main.py:9770`), and the rewrite also needs `serp_analysis` + `page_spec` + `voice_card` that only the real scoring path supplies (`local_seo_service.py:1757`). So the gap report is a **presentation layer**; the "Reoptimize this page" action routes the page through the existing **`page → /score-page → deficiencies → /reoptimize-page`** flow (Local SEO / ecommerce / blog by page type — the same flow the reoptimize tabs already use), which already targets the SERP entity/structure/signal gaps. Gap findings `/score-page` doesn't natively cover (e.g. a specific missing subtopic) can later be threaded as supplementary rewrite guidance (`writer_notes`-style), **not** as `deficiencies` — a v1.1 enhancement, not a v1 claim.

### 11.2 Other open questions

- Real DataForSEO daily ceiling for the meter default (placeholder pending owner's number, like domain-intel).
- Whether the on-page diff is client-facing verbatim or internal-only with a softened client summary (tone ruling, like the other client reports).
- **"Most important URLs" definition** for the monthly auto-scope — money pages from `tracked_keywords.canonical_url`, or an explicit per-client pin.
- `content_gap_snapshot_max_age_days` default (30 assumed to match cadence) — confirm the acceptable staleness for reusing a snapshot vs. forcing a fresh capture.
