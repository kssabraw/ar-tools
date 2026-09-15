# PAA → SEO Neo — module plan v1.0

> **What this is.** The plan for adapting the external two-layer local-SEO
> methodology (**PAA content layer** + **SEO Neo authority layer**) into suite
> tooling. It is grounded in the de-branded domain reference
> (`docs/reference/paa-seo-neo-master-reference.md` — the authority for *how the
> methodology works*) and in the suite's existing code (verified, §7). Read the
> module orientation first: `docs/modules/paa-seo-neo/CLAUDE.md` +
> `HANDOFF.md`.
>
> **Confidence legend (carried from the reference).** **[PROVEN]** = case
> study / repeated result in the source transcripts · **[THEORY]** = a stated
> model, unproven or disputed · **[BELIEF/EVOLVING]** = a working assumption that
> shifts with Google. Any recommendation this module surfaces to a user MUST
> preserve these tags — the methodology is one group's working model, not Google
> guidance.
>
> **Scope decisions settled by the owner (2026-09-15), which shape this plan:**
> 1. **v1 = the content half first** — the PAA content layer only. Prove it before
>    building orchestration (mirrors the methodology's own "content before
>    authority" discipline).
> 2. **Off-platform boundary (load-bearing):** the suite **tracks / costs / QAs /
>    hands off a manifest** for the link layer — it **NEVER executes** link blasts
>    (SEO Neo, GMBB Blast, RD 100, Omega indexing, PBN/parasite building).
> 3. **Audio / video / influencer syndication stays manual** — checklist-tracked,
>    never suite-generated.
> 4. Delivered as this PRD doc.

---

## 0. Why this exists (and what it is NOT)

**The methodology in one sentence** (from the reference §1): *make one business
topically undeniable for one service in one place — across every content format a
machine can read — then make it trusted with links and real engagement, and repeat
per service.*

The suite already automates large parts of the **content** half of that sentence
(Blog Writer, Local SEO, GBP Posts, Content Syndication, Keyword Research). What it
lacks is (a) the **PAA discipline** that organizes that content — one exact-match
question per page, stated identically everywhere, linking high to the service page —
and (b) any first-class notion of the **campaign** that ties a service's PAA set,
its assets, and (eventually) its authority hand-off together.

**This module is NOT:**
- **NOT a link-blasting engine.** The suite never runs SEO Neo, GMBB Blast, RD 100,
  Omega, or builds PBNs/parasites. Its role at the authority layer is at most
  track / cost / QA / hand-off (§6, Phase 2 — and even that is not v1).
- **NOT an audio/video generator.** Podcast (07b), video (07c), and influencer
  footage (13b) are human-produced and human-proofed; the suite tracks their URLs
  as checklist rows, never generates them.
- **NOT a new content pipeline.** Everything downstream of a chosen PAA reuses
  existing writers (Blog Writer, GBP Posts, Content Syndication). v1 adds the PAA
  *organizing layer* and a small set of *writing constraints*, not a new generator.
- **NOT wired into any agent loader.** The domain reference lives in
  `docs/reference/` precisely so `sop_library` never ingests it; this plan keeps
  that boundary (§9).

## 1. The organizing insight (why the "PAA set" is the whole v1)

The methodology's atomic unit is **the PAA string as a universal join key**
(reference §3): one exact-match "People Also Ask" question is filed *identically* as
the blog title/H2, the image alt text, the GBP post, the (later) video/podcast
title, and the (later) Neo content bucket / RD-100 anchor. "Exact-match everywhere"
is the entity-resolution mechanism — get the PAA right once and it propagates; wrong
and the error propagates just as far. **[BELIEF/EVOLVING]** — it is the source
group's model, not confirmed Google behaviour, so v1 treats it as a strong default a
user can override, not a law.

So the smallest thing that captures the methodology's value is **a first-class,
persisted "PAA Set" per service-in-geo** — the ~4 exact-match buyer questions for
one high-revenue service in one place — plus the **three writing rules** that make
each PAA page pull its weight:

1. **One question → one post** (never blend two PAAs into one page).
2. **Exact-match everywhere** — the PAA string is the post title/an H2, and the
   same string seeds the matching GBP post + syndication title.
3. **Link HIGH to the service page** — each PAA post's primary internal link points
   at the client's *service page* (the money page), not the homepage, not the blog
   index. **[BELIEF]** service-level, per reference §4.

v1 delivers exactly this: the PAA Set as an output, and the three rules as
enforceable writer constraints — reusing the SERP-enrichment PAA pull the suite
already bills for, and the Blog Writer's `writer_notes` + a deterministic
internal-link check. Nothing more.

## 2. The two-layer model (and why v1 is only Layer 1)

| | **Layer 1 — Relevancy / content** | **Layer 2 — Authority / links** |
|---|---|---|
| **Job** | Make the page *deserve* to rank | Make the relevant page *trusted* enough to rank |
| **v1 role** | **BUILD** (the PAA set + writing rules + assets) | **out of v1** — tracked/costed/QA'd/handed-off in a later phase, **never executed** |

The reference's hard lesson (§2): **authority pointed at thin/off-topic content is
wasted** **[PROVEN by counter-example]**, and **content alone ranks only in easy
markets** **[PROVEN]**. That is *why* the owner chose content-first: build Layer 1
well, measure it single-variable, and only then decide what (tracked, off-platform)
authority work a service needs. v1 makes Layer 1 disciplined and measurable; it does
not touch Layer 2's execution.

## 3. The single-variable gate (the discipline v1 borrows, lightly)

The methodology's decision rule (reference §5.3): do the content layer, let it sit
~1 week, **scan** (Maps geo-grid, single-variable), then branch —
- **moved →** proceed to the next topically-related service;
- **no movement →** drill deeper (more sub-PAAs, ≤~4 levels);
- **main revenue service still stuck after drilling → HALT** and re-check
  on-page/entity (something upstream is wrong; more PAAs won't fix it).

v1 does **not** build an automated gate/state-machine (that is Phase 3). v1 reuses
what the suite already has: the **Maps geo-grid single-keyword scan** (already
single-variable) and **response-episode tracking** (the verify/refresh cadence loop)
so a user can run the scan and read the branch manually. The gate is documented as a
*recommended workflow*, wired as an *automated loop* only in Phase 3.

## 4. v1 scope — the content half (what actually gets built)

### 4.1 The PAA Set (net-new, first-class research output)

A **PAA Set** = the exact-match buyer questions for **one service, in one geo**,
selected per the methodology (reference §5, SOP 05): per service, in-geo, ~4 per
service, exact-match, buyer-intent. It reuses the suite's existing PAA pull rather
than adding a data source.

- **Source (reused, verified):** `services/keyword_research_serp.py` already pulls
  **People Also Ask** questions per seed from one live Google SERP
  (`fetch_serp` + `dedupe_paa`), geo-scoped by the client's
  `rank_tracking_location_code`, and persists them on
  `keyword_research_runs.serp_intel`. v1 promotes those PAA questions from a
  by-product into a **named, service-anchored, selectable set**.
- **Shape (LOCKED — own tables, §8.2):** two net-new tables (one migration at
  build):
  - **`paa_sets`** — per (client, service keyword, location): the service keyword
    ("metal roof repair," not "roofing" — reference §4), the geo, a
    **`geo_mode`** flag (**default `geo` — geo-modified — with `naked` as a
    per-set toggle**, §8.4), and an optional **`service_page_url`** (the "link
    high" target, §4.2 / §8.3).
  - **`paa_items`** — one row per PAA string in a set: the exact-match question,
    its DataForSEO volume/CPC (reused market enrichment), a `chosen`/`candidate`
    flag, a `slug` (for the cannibalization guard, §4.3), and a nullable
    `run_id`/`post_url` filled once a post is created.
- **UI (LOCKED — §8.1):** a **new card in the client workspace "Content Creation"
  section** (`frontend/src/pages/ClientWorkspace.tsx`, the `<Section
  title="Content Creation">` block — alongside Blog Writer, Local SEO, GBP Posts,
  Content Syndication), at its own route (e.g. `/clients/:id/paa-sets`). It is a
  **content-creation entry point**, not a Keyword Research tab: pick service →
  pull PAA (reuses the metered `keyword_research_serp` SERP call under the hood) →
  select ~4 → save the set → create the posts (§4.2, step 5 of §10). Deliberately
  thin: an organizer over an existing paid call that kicks off existing writers,
  not a new pipeline or a parallel research UI.

### 4.2 The three writing rules (net-new *constraints* over existing writers)

The rules are enforced where content is generated, reusing existing seams:

| Rule | Mechanism (reused) | Enforcement |
|---|---|---|
| One question → one post | Blog Writer run per PAA; the PAA is the run's seed keyword | Structural — one `run` per selected PAA |
| Exact-match everywhere | `writer_notes` seam (verified: `run_dispatch.create_run_and_snapshot(writer_notes=…)` → `orchestrator` `user_notes`) carries "title/an H2 must be this exact PAA string"; the same string seeds the GBP post + syndication title | `writer_notes` (soft, LLM) + a deterministic title/H2 check (net-new, small) |
| Link HIGH to the service page | `writer_notes` names the service-page URL as the primary internal link; a deterministic post-generation check guarantees the link is present, modeled on Local SEO's `local_seo_matrix.ensure_internal_links` / `check_internal_links` (verified). **URL resolution (LOCKED, §8.3): explicit `paa_sets.service_page_url` → auto-matched live page via `site_page_index` → prompt the user** (never silently guess) | Deterministic guarantee (reuse the `ensure_internal_links` pattern), not just a prompt |

> **Why deterministic checks, not just prompts:** the reference is explicit that
> exact-match and the service-page link are the *entity-resolution mechanism*, not
> style — an LLM can be talked out of them; a check cannot. This mirrors the suite's
> own precedent (voice-compliance regex caps, `ensure_internal_links`).

The PAA blog run stays a normal suite blog run (brief → sie → research → writer →
sources_cited); it is **not** a schema change — the constraints ride on
`writer_notes` + a post-check, exactly like the existing "Write this post" handoff
from Keyword Research. **[No Writer output-schema bump.]**

### 4.3 The cannibalization guard (reused, load-bearing)

The reference's single named failure (§10): **~1,000 near-identical neighborhood
pages inside one city** — and "never reuse an identical PAA slug across cities."
v1 reuses the suite's existing guards rather than inventing one:
- **`site_page_index.build_page_token_index` / `match_site_page_for_keyword`**
  (content-word-set existing-page matching, #951/#953, verified) — before a PAA
  post is created, check the client doesn't already have a page answering it.
- **`local_seo_matrix.scale_gates` + `MATRIX_SIGNOFF_THRESHOLD` (=200, verified)** —
  the scale sign-off precedent; a PAA set that would fan out past a threshold trips
  a human sign-off, not a silent bulk create.

### 4.4 What v1 explicitly does NOT include

- No prep-sheet manifest object (Phase 2).
- No link-layer tracking/costing/QA surface (Phase 2).
- No campaign orchestration object or automated gate/verify state machine (Phase 3).
- No audio/video/influencer rows or generators (Phase 2 checklist at the earliest;
  never a generator).
- No new agent wiring.

## 5. The seam — where Layer 1 hands off to Layer 2 (Phase 2 preview, boundary-gated)

The reference's central mechanism (§3, §5): **the prep sheet is the physical
hand-off** — one per client: NAP, CID, place ID, GBP URLs, and *every* blog / social
/ (later) podcast / video / image URL and embed. "Most tactics are just this sheet
routed to a different destination." The one organizational gap the source flags:
**agree explicitly who captures the asset URLs and hands them to the operator.**

**Phase 2** models the prep sheet as the suite's clearest net-new data object — a
per-campaign **manifest** that auto-collects the URLs of assets the suite already
produced (PAA posts, GBP posts, syndication copies, hosted images) plus manual rows
for human-produced assets (audio/video/influencer). It is a **read/export artifact +
a hand-off record**, gated by the off-platform boundary: the suite exports the
manifest for a human/vendor operator; it does not run anything against it.

## 6. Phasing (by ROI, boundary-respecting)

### Phase 1 — the content half (v1, this plan) — proves the discipline
PAA Set + the three writing rules + the reused cannibalization guard + the reused
single-variable scan/verify workflow (manual). Reuses Keyword Research PAA pull,
Blog Writer + `writer_notes`, GBP Posts, Content Syndication, Maps geo-grid,
response-episodes. **Net-new: the PAA-set object + the small deterministic writer
checks.**

### Phase 2 — the prep-sheet manifest + link-layer tracking (the seam)
The manifest object (§5); auto-collects suite-produced asset URLs; manual checklist
rows for audio/video/influencer (**tracked, never generated** — decision #3). The
link layer becomes **track / cost / QA / hand-off** only (decision #2): reuse the
**Recipe Engine** (verified: it already costs **GBP Blast**, **DAS**, and RD-family
work; **RD 100 is deliberately off its default menu**) to cost the authority bundle,
QA reuses the QA Agent, and the manifest is the export. **The suite still executes
nothing at Layer 2.**

### Phase 3 — the Service PAA Campaign object + automated gate/verify loop
The full orchestration the HANDOFF describes: target service → PAA set → blog runs →
GBP posts → syndication → prep-sheet manifest → **automated single-variable gate**
(scan → moved/drill/HALT) → link-layer task bundle (tracked) → re-scan on the
methodology's cadence. Reuses response-episodes for the verify loop; introduces the
campaign state machine. Only worth building after Phase 1 proves the content half
and Phase 2 proves the manifest.

### Never (non-goals, permanent) — see §9.

## 7. What this reuses (the "don't rebuild it" map — verified against code)

Every row below was checked against the current tree (2026-09-15):

| Methodology step | Suite module | Verified anchor |
|---|---|---|
| PAA research (People Also Ask, geo-set) | Keyword Research SERP enrichment | `services/keyword_research_serp.py` (`dedupe_paa`, `build_serp_intel`); `keyword_research.py` pulls `features["people_also_ask"]` per seed, geo via `rank_tracking_location_code`; persisted on `keyword_research_runs.serp_intel` ✓ |
| Blog per PAA + the writer constraints | Blog Writer + `writer_notes` seam | `run_dispatch.create_run_and_snapshot(writer_notes=…)` → `orchestrator.py` `user_notes` ✓ |
| "Link high to the service page" (deterministic) | Local SEO matrix internal-link guarantee | `local_seo_matrix.ensure_internal_links` / `check_internal_links` (pattern to reuse for blog) ✓ |
| GBP post per PAA | GBP Posts module (built, gated) | `services/gbp_posts_service.py` ✓ |
| Social / written syndication | Content Syndication module | `services/syndication_service.py` ✓ |
| Cannibalization guard (the ~1,000-page failure) | Content-word-set matching + matrix scale gate | `site_page_index.build_page_token_index` / `match_site_page_for_keyword`; `local_seo_matrix.scale_gates` + `MATRIX_SIGNOFF_THRESHOLD=200` ✓ |
| Single-variable re-scan / measurement | Maps geo-grid (Local Dominator) | `local_dominator.resolve_scan_keywords` (per-keyword scans already supported) ✓ |
| Verify / refresh cadence loop | Response-episode tracking | `response_episodes.evaluate_episode` / `episode_note` / `run_episode_sync` ✓ |
| Costing the (tracked) link-layer work | Recipe Engine | `recipe_engine.py` BASELINE_STACK costs GBP Blast + DAS; RD-family present, RD 100 off the default menu ✓ |
| Prep-sheet manifest (the URL hand-off) | **Not modeled** | The clearest net-new object — Phase 2 |
| Podcast / video / influencer production | **No suite equivalent** | Off-platform, human-proofed — checklist rows only, Phase 2 |

## 8. Decisions locked before build (owner, 2026-09-15)

The four design forks below are **settled** — reflected in §4.1 / §4.2. Item 5
stays a build-time confirmation (not a design fork).

1. **PAA Set home → a new card in the workspace "Content Creation" section** (LOCKED).
   Not a Keyword Research tab and not a standalone module — it lives beside the other
   content generators (`ClientWorkspace.tsx`, `<Section title="Content Creation">`),
   at its own route (e.g. `/clients/:id/paa-sets`), and reuses `keyword_research_serp`
   for the PAA pull under the hood. It is a content-creation entry point (pull →
   select → create posts), per §4.1.
2. **Data model → own tables `paa_sets` + `paa_items`** (LOCKED). First-class and
   sluggable (for the cannibalization guard), independent of any research run. One
   migration at build. Fields per §4.1.
3. **Service-page URL resolution → explicit `service_page_url` → auto-matched live
   page via `site_page_index` → prompt the user** (LOCKED). Human intent wins,
   auto-match is the fallback, never a silent guess. Per §4.2.
4. **Naked vs geo PAA → geo-modified default, `naked` as a per-set toggle** (LOCKED;
   `paa_sets.geo_mode`). Matches the suite's local-SEO grain; the contested point
   (reference §9) is surfaced, not hardcoded away.
5. **The `keyword_research_serp` per-run PAA cap / cost** *(build-time confirm, not a
   design fork):* one billed SERP call per seed already; confirm the PAA-set flow
   doesn't multiply that before wiring the pull.

## 9. Non-goals (v1 and permanent guardrails)

**v1 non-goals** (deferred, not rejected): the prep-sheet manifest; link-layer
tracking/costing/QA; the campaign object + automated gate; audio/video checklist
rows.

**Permanent guardrails** (never, regardless of phase):
- **The suite never executes link blasts** — SEO Neo runs, GMBB Blast, RD 100,
  Omega indexing, PBN/parasite building are off-platform vendor work. Track / cost /
  QA / hand off a manifest — never run.
- **No audio/video/influencer generator** — human-produced and human-proofed;
  tracked as checklist rows only.
- **Gray/black-hat tactics are out of scope for suite automation** — PBNs, spun tier
  content, directional-URL blasting, footprint management, parasites/EMDs. Prefer the
  white-hat path (real content, real citations, PRs, genuine engagement) where a
  choice exists.
- **No agent-loader ingestion** — the domain reference stays in `docs/reference/`;
  `sop_library` must never read it. Anything this module surfaces to a user carries
  the `[PROVEN]`/`[THEORY]`/`[BELIEF]` confidence tags.
- **The methodology's contested claims are surfaced, not enforced as truth** — e.g.
  the RD-100 "100:1" ratio is `[THEORY]` and openly disputed in the source (a common
  alternative default is ~50 referring domains); exact-match-on-the-money-site is a
  `[BELIEF]` with two camps. Where the reference marks a contradiction (§9), the
  suite defaults conservative and lets the user choose.

## 10. Rough build order (checklist — for the build PR, not this plan)

1. `paa_set` data model + migration (per §4.1; reconcile with Keyword Research).
2. PAA-set surface: pull (reuse `keyword_research_serp` PAA) → select → save.
3. The three writer constraints: `writer_notes` composition + the deterministic
   title/H2 + service-page-link checks (reuse the `ensure_internal_links` pattern).
4. Cannibalization guard wiring (reuse `site_page_index` matching + `scale_gates`).
5. "Create the PAA posts" action → N Blog Writer runs (one per PAA) + matching GBP
   posts + syndication, all seeded from the exact PAA string.
6. Document the manual single-variable scan/verify workflow (reuse Maps geo-grid +
   response-episodes) — no new state machine in v1.
7. Tests: pure helpers (PAA-set assembly, slug dedup, the deterministic checks) +
   the writer-constraint enforcement, mocked per the repo's testing conventions.

*(Phases 2–3 get their own build orders when the owner greenlights them.)*

## 11. Phase 2 build order — the prep-sheet manifest + link-layer track/cost/QA (GREENLIT 2026-09-15)

> v1 (the content half) is built + live (PR #1117). This is the **Phase 2** build
> order — the seam previewed in §5, scoped concretely. Design forks locked by the
> owner (2026-09-15) below; guardrails (§9) unchanged and load-bearing — the suite
> tracks / costs / QAs / hands off a manifest and **executes nothing** at the
> authority layer.

### 11.1 Phase 2 design forks — LOCKED (owner, 2026-09-15)

1. **Manifest grain → one manifest per `paa_set`** (per service-in-geo). Matches the
   topical-congruence discipline (one service per campaign, never mix) and evolves
   into Phase 3's per-service Campaign object. The client-identity header
   (NAP/CID/place ID/GBP URL) is read fresh from `clients.gbp` at build/export time,
   never stored, so it can't go stale.
2. **Data model → own tables `paa_manifests` + `paa_manifest_assets`** (assets
   first-class so a QA verdict + a cost attach per row; mirrors `paa_sets`/`paa_items`).
3. **Authority bundle → seed the standard bundle as tracked-only rows.** The manifest
   arrives pre-listing the 7 seam-bolt authority items (reference §5.1 — RD 100
   anchors, GMBB Blast, wiki/cloud stacks, PRs, Neo buckets) as `source='seed'`,
   `status='planned'`, mapped to a Recipe-Engine cost `task_type` where one exists,
   each carrying its `[PROVEN]`/`[THEORY]`/`[BELIEF]` tag. Operator edits/removes.
   **No execute affordance, ever.**
4. **QA → the QA Agent on live content URLs, async.** A `paa_manifest_qa` job runs
   `qa_service.review_url` per content asset that has a **live URL** (the thing
   authority amplifies — reference §2), gated on `qa_enabled`, rolled up onto the
   manifest. v1's free deterministic per-item checks (`verify_posts`) remain the
   always-available fallback. One new `async_jobs` type.
5. **Export → CSV + JSON download AND an optional Google Sheet** into the client's
   Drive folder (reuses `google_docs.create_google_sheet`; matches the reference's
   "the prep sheet IS a sheet").

Settled by recommendation (suite-consistent, reversible): surfaced as a **"Prep
Sheet" section on the PAA-set detail view** (anchored to the set it hands off, not a
new top-level card); **no new feature flag** (track/cost/QA/export, no execution —
manifest QA just rides `qa_enabled`); authority/media rows are **status-only**
(planned → handed_off → done, all human-set).

### 11.2 Build checklist (for the build PR)

1. **Data model + migration** — `paa_manifests` (one per set: status, `cost_summary`
   / `qa_summary` roll-ups, last Sheet-export refs) + `paa_manifest_assets` (one per
   asset: `category` content/authority/media, `source` auto/seed/manual, `kind`,
   `label`, `url`, `note`, `status`, `confidence_tag`, `cost_task_type`,
   `cost_quantity`, `qa_verdict`/`qa_review`, `paa_item_id`). New `async_jobs` type
   `paa_manifest_qa` (drift-proof CHECK widen). RLS service-role, matching the suite.
2. **Auto-collect (pure assembly over a DB read)** — from v1 linkage: a PAA post's
   live URL (`runs.published_url` via `paa_items.run_id`), a GBP post's `search_url`
   (via `gbp_post_id`), syndication copies (`syndication_items.doc_url`/`sheet_url`),
   hosted images (best-effort). Not-yet-published posts collect as `status='pending'`.
3. **Seed authority + manual-media rows** — the §11.1.3 bundle (once, never clobbered
   on rebuild) + audio/video/influencer manual rows.
4. **Cost** — `recipe_engine.cost_of` over the costable rows; honest "not estimated"
   for off-menu (RD 100). Roll up onto `paa_manifests.cost_summary`.
5. **QA** — the `paa_manifest_qa` job → `qa_service.review_url` per live content-asset
   URL → per-asset verdict + a manifest-level rollup. Gated on `qa_enabled`.
6. **Export / hand-off** — CSV + JSON download (deterministic, always) + optional
   Google Sheet into the client's Drive folder, each carrying the client-identity
   header + all rows with their confidence tags.
7. **Surface** — a Prep Sheet section on the PAA-set detail view (build/refresh, the
   asset table grouped by category, cost + QA rollups, Run QA, exports, editable
   status on authority/media rows).
8. **Tests** — pure helpers (auto-collect assembly, cost/QA rollups, export rendering,
   the seeded bundle) + the QA/build/export wiring, mocked per the repo's conventions.

*(Phase 3 — the Service PAA Campaign object + the automated single-variable gate —
gets its own build order when greenlit.)*

## 12. Phase 3 build order — the Service PAA Campaign object + the automated single-variable gate (GREENLIT 2026-09-15)

> v1 (the content half, PR #1117) and Phase 2 (the prep-sheet manifest, PR #1120)
> are built + live. This is the **Phase 3** build order — the campaign object +
> the automated gate previewed in §3/§6, scoped concretely. Design forks locked by
> the owner (2026-09-15) below; guardrails (§9) unchanged and load-bearing — the
> campaign **orchestrates and tracks** the content→settle→scan→gate loop and hands
> off the (Phase-2) manifest, but the suite still **executes nothing** at the
> authority layer.

### 12.1 What it automates (reference §5.2/§5.3 + the v1 manual workflow doc)

The v1 `single-variable-scan-verify-workflow.md` is a **manual** loop: create posts
→ settle ~1 wk → single-keyword Maps scan → read the branch (moved / drill / HALT)
→ rinse. Phase 3 makes that a **state machine with a clock and an automated gate
read** — a human no longer hand-tracks "has it been a week, should I scan, did it
move, do I drill." The **load-bearing settle wait** (reference §5.2 — "model the
waits as first-class steps, never fire the layers in parallel") becomes a real
`settling` state; the **gate branch** (reference §5.3) is computed, not eyeballed.

### 12.2 Phase 3 design forks — LOCKED (owner, 2026-09-15)

1. **Autonomy posture → hybrid propose-confirm.** The cheap/free steps are
   automatic (settle timer, scan-complete detection, the gate read, the drill/HALT
   decision, maintenance scheduling, manifest refresh, notifications). The two
   **paid/content** steps — kicking a paid Maps geo-grid scan, and creating a drill
   round of blog posts — advance the campaign to a `*_ready` state + emit a
   notification; a **human confirms** to proceed (reusing v1's create-posts path +
   the existing scan enqueue). Matches SerMaStr's propose-never-execute discipline
   and reinforces the "never parallel" wait rule. **Full per-campaign autopilot is
   deferred** behind a future flag (not built in Phase 3).
2. **Campaign ↔ set/manifest → 1:1 with one set; drilling adds `drill_level`
   items.** `paa_campaigns` is 1:1 with ONE `paa_set` (unique `set_id`, mirroring
   `paa_manifests`). Drilling adds `drill_level`-tagged `paa_items` to that **same
   set** (the measurement target — the service keyword — is constant across levels;
   drilling adds supporting content, it does not change what's scanned). ONE
   manifest per set (Phase 2 unchanged) = the campaign's asset ledger. Truest to
   "one service = one campaign = one prep sheet," and reuses Phase 2 untouched.
3. **Scan-target keyword → auto-add to the Maps tracker on campaign start.** The
   geo-grid only scans a client's **active** `maps_keywords`. On campaign start the
   service keyword is upserted into `maps_keywords`
   (`on_conflict=client_id,keyword, ignore_duplicates=True` — the same idempotent
   pattern the maps router uses), so the gate scan just works. (Owner ruling —
   smoother than blocking; it grows the tracked set by the one keyword the campaign
   measures.)
4. **Ship behind a new `paa_campaign_enabled` flag (default off — ships dark).**
   Unlike v1 (a plain content surface), Phase 3 adds scheduled automation + a paid
   scan step, so it gets a kill switch, dark by default (like Director/QA/autonomy).

**Smaller defaults, locked by recommendation (owner-approved):**
- **Maintenance re-scan piggybacks on the client's SCHEDULED geo-grid scans**
  ($0 extra): the rinse loop reads the latest **scheduled** scan's result for the
  service keyword rather than paying for its own. The *initial* post-settle
  measurement still uses a deliberate (confirmed) scan, since its timing (after the
  settle) is load-bearing.
- **Drill sub-PAAs via PAA re-pull** (no new data source, no LLM): a drill round
  re-`pull_paa` seeded from the current level's chosen questions — the natural PAA
  tree — surfaced for human confirmation before the posts are created.
- **HALT → a critical notification + best-effort SerMaStr escalation** (gated on
  `strategist_enabled`; the same hook `response_episodes` uses) — "content hasn't
  moved after N drill levels; STOP adding content and re-check on-page/entity"
  **[PROVEN model]**.

### 12.3 The state machine (states → transitions)

`draft → content → settling → scan_ready → scanning → evaluating →`
**`moved`** | **`drill_ready`** | **`halted`**, and `moved → maintenance` (rinse).

- **draft** — campaign created; the root `paa_set` exists; service keyword auto-added
  to `maps_keywords`; no posts yet.
- **content** — the PAA posts for the current drill level are dispatched (v1
  `create_posts`); waiting for the runs to finish + `verify_posts`. → `settling`.
- **settling** — first-class wait; `settle_until = now + settle_days` (default 7,
  reference §5.2). → `scan_ready` when `now ≥ settle_until`.
- **scan_ready** — *propose*: notify "campaign ready to scan"; a human confirms →
  enqueue a single-keyword `manual` geo-grid scan for the service keyword
  (`enqueue_maps_scan(..., keywords=[service_kw])`) → `scanning`.
- **scanning** — a scan is in flight; the sweep matches the client's newest
  completed `manual` `maps_scans` row (after the scan request) carrying a result for
  the service keyword. → `evaluating`.
- **evaluating** (transient) — read that scan's `maps_scan_results.average_rank` +
  `top3_pins` for the service keyword; `evaluate_gate(baseline, current,
  drill_level, cap)` branches: **moved** (improvement ≥ threshold) → `moved`;
  **no movement & `drill_level < cap` (~4)** → `drill_ready`; **no movement & at
  cap** → `halted`.
- **moved** — set `next_action_at = now + rinse_days` → `maintenance`. Surfaces the
  authority hand-off (build/refresh the Phase-2 manifest — track/cost/QA, never
  execute) and *suggests* (does not auto-create) a campaign for the next
  topically-related service.
- **drill_ready** — *propose*: pull sub-PAAs (seeded from this level's questions),
  notify + preview them; a human confirms → add them as `drill_level+1` items →
  `content`.
- **maintenance** — the rinse loop; when `now ≥ next_action_at`, read the latest
  scheduled scan's result → re-evaluate; a slip re-opens the surfaced action + resets
  `next_action_at`. (Maintenance declines still flow through the existing
  `maps_alerts → response_episodes` machinery, so the 6-week escalation still fires.)
- **halted** — terminal until a human acts; critical notification + best-effort
  strategist escalation. A human can reset (re-check on-page/entity done → re-run).

### 12.4 The gate (single-variable, deterministic, unit-tested)

Pure `evaluate_gate(baseline_rank, current_rank, top3_delta, drill_level, cap,
thresholds) → {branch, improved, reason}`. "Single-variable" holds because the only
thing the campaign changed since the baseline is **content** (the suite never runs
authority; one service per campaign). `[PROVEN model]` tag carried into the UI.

### 12.5 Honest note on the `response_episodes` reuse (spec-vs-reality)

`response_episodes` is **alert-keyed and decline-oriented** (opens from open
`rank_alerts`/`maps_alerts`, baseline at the drop, "recovered" when the alert
resolves, escalate at 42 days). A campaign measures **improvement after adding
content**, not decline-recovery — so the campaign carries its **own** settle/rinse
clock (borrowing episodes' cadence constants: ~7-day settle, 14-day recheck, 42-day
escalate) rather than force-fitting the alert table. Maintenance-loop *declines*
still route through the existing episode machinery (scheduled scans feed it), so the
6-week rule is not lost. This is a deliberate divergence from the HANDOFF's
one-line "reuses response-episodes," recorded here because the code doesn't fit the
loose description.

### 12.6 Build checklist (for the build PR)

1. **Data model + migration** — `paa_campaigns` (1:1 `set_id` unique: `state`,
   `drill_level`, `settle_until`, `next_action_at`, `baseline_rank`,
   `current_rank`, `last_scan_id`, `scan_requested_at`, `halted_reason`, `history`
   jsonb transition log, `created_by`, timestamps) + `paa_items.drill_level`
   (default 0). RLS service-role, matching the suite. **No new async-job type** —
   the campaign advance is an inline scheduler sweep; expensive steps reuse existing
   jobs/paths (`maps_scan`, the create-posts path).
2. **Pure core** `services/paa_campaign.py` — the transition function, `evaluate_gate`,
   the drill/HALT decision, cadence helpers, the "next action" descriptor, all pure +
   unit-tested; confidence tags in surfaced copy.
3. **I/O** `services/paa_campaign_service.py` — create campaign (auto-add the
   Maps keyword; create the root set + posts), `run_paa_campaign_sync()` (the inline
   sweep, best-effort per campaign, like `run_episode_sync`), the gate read over
   `maps_scan_results`, confirm-scan / confirm-drill (pull + preview sub-PAAs),
   moved→maintenance + manifest refresh, HALT notification + best-effort strategist
   escalation.
4. **Scheduler wiring** — `_safe("paa_campaigns", run_paa_campaign_sync)` in the
   daily block; the whole thing gated on `paa_campaign_enabled` (config, default
   False).
5. **Router + models** (`routers/paa.py` + `models/paa.py`) — campaign CRUD, get
   campaign (state + next action + timeline), confirm-scan, confirm-drill (with the
   sub-PAA preview), advance/refresh, HALT ack/reset. Freeze-gated where it creates
   content.
6. **Frontend** — a Campaign section/tab on the PAA-set detail view (`pages/PaaSets.tsx`):
   the state timeline, current state + next action + when, the gate read
   (baseline→current + moved/drill/HALT), the two confirm buttons, the drill
   preview, the HALT banner, a link to the manifest hand-off. Confidence tags carried.
7. **Tests** — pure state-machine transitions (every branch: content→settle→scan→
   moved / →drill→…→HALT / maintenance rinse), gate thresholds, cadence math, the
   drill cap, mocked service flow, per the repo's conventions.

### 12.7 Guardrails held (§9, load-bearing)

No authority execution (moved→handoff only builds/costs/QAs the Phase-2 manifest);
no audio/video/influencer generator; the master reference is never wired into
`sop_library`; confidence tags carried into the UI + exports; HALT is a **stop**
("more PAAs won't fix it"), never "keep writing."

---

*Plan only — no implementation until the owner approves. Defer to
`docs/reference/paa-seo-neo-master-reference.md` for methodology detail and to the
verified code anchors in §7 for the suite seams. Carry the confidence tags into
anything this module ever shows a user.*
