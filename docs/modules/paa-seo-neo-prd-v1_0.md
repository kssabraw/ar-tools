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
- **Shape (proposed):** a persisted `paa_set` per (client, service, location) —
  the service keyword ("metal roof repair," not "roofing" — reference §4), the geo,
  and an ordered list of chosen PAA strings each with: the exact-match question,
  its DataForSEO volume/CPC (reused market enrichment), a `chosen`/`candidate`
  flag, and a `slug` (for the cannibalization guard, §4.3). **[No migration in
  this doc]** — the data model is proposed here and locked in the build step.
- **UI:** a "PAA Set" surface hung off the client workspace (or as a tab within
  Keyword Research, TBD in build) — pick service → pull PAA (reuses the metered
  SERP call) → select ~4 → save the set. Deliberately thin: it is an organizer over
  an existing paid call, not a new pipeline.

### 4.2 The three writing rules (net-new *constraints* over existing writers)

The rules are enforced where content is generated, reusing existing seams:

| Rule | Mechanism (reused) | Enforcement |
|---|---|---|
| One question → one post | Blog Writer run per PAA; the PAA is the run's seed keyword | Structural — one `run` per selected PAA |
| Exact-match everywhere | `writer_notes` seam (verified: `run_dispatch.create_run_and_snapshot(writer_notes=…)` → `orchestrator` `user_notes`) carries "title/an H2 must be this exact PAA string"; the same string seeds the GBP post + syndication title | `writer_notes` (soft, LLM) + a deterministic title/H2 check (net-new, small) |
| Link HIGH to the service page | `writer_notes` names the service-page URL as the primary internal link; a deterministic post-generation check guarantees the link is present, modeled on Local SEO's `local_seo_matrix.ensure_internal_links` / `check_internal_links` (verified) | Deterministic guarantee (reuse the `ensure_internal_links` pattern), not just a prompt |

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

## 8. Open items / decisions to lock before build

- **PAA Set home:** a new lightweight surface vs. a tab inside Keyword Research
  (which already owns the PAA pull). Leaning: a tab/output of Keyword Research to
  avoid a parallel research UI. *(Owner call at build.)*
- **Service-page URL source for the "link high" rule:** the client's own live
  service page (via `site_page_index`), a Local SEO page, or a Website-Builder page —
  need a resolution order (probably: explicit field → matched live page → prompt).
- **Naked vs geo PAA** — the reference flags this as an unresolved contradiction
  (§9). v1 default = geo-modified (matches the suite's local-SEO grain), but surface
  both and let the user choose; do not hardcode.
- **Data model specifics** (table names, whether `paa_set` is its own table or rides
  Keyword Research runs) — proposed in §4.1, locked in the migration at build.
- **The `keyword_research_serp` per-run PAA cap / cost** — one billed SERP call per
  seed already; confirm the PAA-set flow doesn't multiply that.

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

---

*Plan only — no implementation until the owner approves. Defer to
`docs/reference/paa-seo-neo-master-reference.md` for methodology detail and to the
verified code anchors in §7 for the suite seams. Carry the confidence tags into
anything this module ever shows a user.*
