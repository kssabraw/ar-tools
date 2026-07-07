# Rank Drop Mitigation SOP — Organic Branch

**Current as of:** 03 July 2026 _(supersedes "How To Diagnose And Fix Organic Rankings Drops")_
**Goal:** Diagnose and mitigate organic ranking drops.
**Who this is for:** All clients.
**When:** Triggered by the **rank tracking agent** (the agent owns the drop definition and fires the signal — no manual weekly checking).
**Assigned to:** per `_ORCHESTRATOR.md` §6, escalating per below.
**Estimated time:** 4 hours or less to work the response.
**Scope:** Organic drops. Maps/geo-grid drops → Maps branch. Top-level triage (organic vs. maps) lives in `_ORCHESTRATOR.md`.

> **Cross-references:** detection & classification → **rank tracking agent** (drop trigger, GSC signal triage, cannibalization, SERP-shape/intent shift) and **offpage agent** (lost links, RD changes) · task assignment → `_ORCHESTRATOR.md` §6 · budget/links → **Recipe Engine** · competition gates (incl. ×10 tool-visibility discount) → Link Building SOP · schema → Architecture SOP templates · on-page criteria → On-Page Criteria & Coverage *(active)* · manual action/deindexing → **Freeze Protocol** (Link Building SOP §Risk Monitoring).

---

## How This Branch Works

The **rank tracking agent** fires a classified signal, not a raw drop. The signal includes:
- Scope: **sitewide** vs. **page/keyword-specific**
- GSC triage: **position drop** vs. **impressions drop** vs. **CTR drop**
- Flags: **cannibalization**, **SERP-shape / intent shift**, suspected **algo update**

The **offpage agent** supplies: lost referring domains / links, citation status, unnatural RD spikes.

This SOP is the **response procedure** for each classification. If a signal arrives unclassified or the agents are unavailable, fall back to working §A/§B top-to-bottom manually.

**Standing tripwires (any point in the flow):**
- **Manual action or deindexing found → stop, invoke the Freeze Protocol** (alert client card · pause all link building + content · notify Kyle/Ryan/Admins). *(Organic-side daily-check infrastructure pending; the protocol applies regardless.)*
- **Algo update confirmed/suspected → notify Senior SEO (Kyle/Ryan)** before continuing.

---

## §A — Sitewide Decline

Many keywords/pages down together. Work in order:

1. **Manual actions / security issues** (GSC) → Freeze Protocol.
2. **Algo update** → Senior SEO; hold major changes until the update settles.
3. **Sitewide technical accident** — robots.txt / noindex regressions, canonical breakage, migration/redesign side-effects, hosting/CDN issues, sitewide CWV regression.
4. **Entity-vector confusion** — heavy off-topic content pulling the site off-vector (Maps SOP Part 1 §Content volume & the entity vector). Remediate per the vector-confusion protocol: delete off-vector pages with no traffic-to-conversion and no conversions; noindex + nofollow internal links where they do have such traffic; whole off-vector services move to a new site/subdomain.
5. **Aggregate link loss / unnatural spike** — from the **offpage agent**. Loss → replacement plan via the **Recipe Engine**. Sudden unnatural spike → check for negative SEO or an unintended blast; MC4 judgment call, Senior SEO if unclear.
6. **Content decay / freshness** — *(procedure pending — not yet built out; placeholder so the slot exists).*

## §B — Page/Keyword-Specific Drop

Respond per the rank tracking agent's classification:

### B1 — Cannibalization flagged
Two (or more) of the client's own pages competing for the keyword — a structural risk of the L×S matrix by design. Response protocol:
1. Identify which page *should* own the keyword (per the site plan / silo structure — Architecture SOP).
2. Differentiate the competing page's targeting (title/H1/content) toward its own keyword.
3. If the pages are true duplicates serving no distinct intent → consolidate + 301 to the owning page.

### B2 — SERP-shape / intent shift flagged
Google changed what the SERP rewards (commercial ↔ informational; AIO/feature absorbing clicks; title rewrites). Response protocol:
1. Re-check intent per the vector test (what page *types* now rank?).
2. If intent flipped: **re-optimize the existing page to the new intent** (default). Building a sibling page for the new intent is the exception, not the rule.
3. If an AI Overview / SERP feature is absorbing clicks → route to the **AIO SOP** *(active)*.
4. If CTR collapsed from a Google title rewrite → rewrite title/meta to be rewrite-resistant (front-load, match query phrasing).

### B3 — CTR drop (position stable)
Title/snippet problem, not a ranking problem: rewrite title/meta; check SERP for new features pushing the result down the fold; confirm rich results (schema) still render.

### B4 — Impressions drop (position stable or absent)
Indexing/visibility problem: URL inspection (indexed? canonical honored?), sitemap presence, internal links (not orphaned — Screaming Frog), silo intact.

### B5 — Position drop (standard diagnostic)
Work in order; stop when cause found:
1. **Technical** — page returns 200 · not redirected · not orphaned · sufficient internal links · design/content not changed · speed/CWV on par with competitors.
2. **On-page** — **invoke the page-type on-page agent** (covered: blog posts, local landing, service, location pages). Uncovered page types → manual optimization with the internal on-page tools → Minda/Ivy per §6. Pass/fail criteria live in **On-Page Criteria & Coverage** *(active — composite bands + thresholds resolved)*. Fails → re-optimization task.
3. **Schema** — one check: the page's schema matches its **Architecture SOP template** for its page type (including the GBP-variant subtype where applicable).
4. **Silo** — silo built out and optimized? Related keywords per the **Seed Keyword SOP** (seeds) plus the writing apps' fanout/clustering (Topic Fanout — ownership per `_ORCHESTRATOR.md` §1). Not built → create silo + interlinking plan (Architecture SOP site plan).
5. **Backlinks vs. competition** — apply the Link Building SOP gates (×10 tool-visibility discount on competitor reads; within-25% = client ≥ comp × 0.75; RD rule with the 250 ceiling). Deficient → identify the variable and **build the plan through the Recipe Engine** (costed, assigned per §6).
6. **Competitor movement** — new pages/links on the competitors that took the spots (offpage agent data).

---

## Indexing & Follow-Through

- Updated pages → VA uploads (§6) → **request indexing via GSC URL Inspection** for money pages.
- **Tier-1 links → Omega Indexer. Never put money-page URLs into Omega** unless specifically directed. *(Consistent with the crawl-vs-index rule: money pages index via GSC; Tier-1 links via Omega; Tiers 2–5 crawl via Colinkri.)*
- Expect movement starting **~2 weeks after indexing**.
- No improvement and all on-page complete → another link round via the **Recipe Engine**.
- No improvement after **6 weeks** → Senior SEO (Kyle/Ryan) strategy review.
