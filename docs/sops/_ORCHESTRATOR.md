# _ORCHESTRATOR — SOP Library Router & Global Rules

**Current as of:** 02 July 2026
**Purpose:** The entry point for any agent (or human) operating across the SOP library. Read this first. It defines which SOP owns which decision, the definitions shared across SOPs, and the global rules that apply regardless of which SOP is executing.

---

## 1. SOP Registry & Decision Ownership

An agent must route every decision to the SOP that owns it — and never improvise in territory another SOP owns. If no SOP owns a decision, that is a **halt-and-ask** (see §3).

| Decision | Owning SOP | Status |
|---|---|---|
| Which pages a site needs; URLs, nav, hubs, schema, internal links | **Site Architecture, URL Structure & Internal Linking SOP** | ✅ Active |
| Link building strategy, task selection, tools, tiers, anchors, velocity | **Link Building SOP — Strategy & Execution** | ✅ Active |
| Manual action / deindexing response (freeze) | Link Building SOP → *Risk Monitoring & Freeze Protocol* | ✅ Active |
| Content creation (briefs, writing, publishing) | Content production pipeline (AR Tools) | External to SOP library |
| Costed monthly task plan (page + competition + budget → assigned tasks) | **Link Building & Campaign Recipe Engine** | ✅ Active |
| Maps/GBP ranking strategy, GBP optimization, review strategy, maps diagnostics | **How To Rank In Google Maps SOP** | ✅ Active (drafts pending confirmation) |
| Maps/geo-grid ranking-drop diagnosis & mitigation | **Rank Drop Mitigation SOP — Maps branch** | ✅ Active |
| Organic ranking-drop response | **Rank Drop Mitigation SOP — Organic branch** | ✅ Active (agent-fed) |
| Seed keyword selection (fanout/clustering owned by the writing apps) | **Seed Keyword SOP** | ✅ Active |
| On-page verdict schema, thresholds, routing, coverage | **On-Page Criteria & Coverage** | ✅ Active (thresholds resolved from the live scoring code) |
| AIO/LLM visibility (offense + click-absorption defense) | **AIO / AEO SOP** | ✅ Active |
| CTR software configuration & operation | **Agency Assassin SOP** | ⏸ Deferred — tool is not agent-accessible; config is human-only (Kyle, per §6). Agent involvement ends at recommending/confirming CTR per Maps SOP rules ($1,200 gate, CTR-stall play). Revisit if the tool gains an API/agent surface. |

**Handoffs already defined:**
- A confirmed **ranking drop** (defined by the internal trackers) → **top-level triage: organic or maps?** Maps/geo-grid drop → Rank Drop Mitigation SOP (Maps branch); organic drop → Organic branch (pending). Then within-branch triage lives in the SOP. The Link Building SOP does *not* own drop response.
- A confirmed **manual action or deindexing** → Freeze Protocol (Link Building SOP §Risk Monitoring): alert client card → pause all link building **and content creation** → notify Kyle Sabraw, Ryan Maizis, and other Admins (client-card tag: **Admin**).

### Agents (detection & execution layer)

Specialized agents own **detection/classification and execution**; the SOPs own **decisions and response procedures**. Signals arrive pre-classified; execution agents do the work within their coverage.

| Agent | Owns | Status |
|---|---|---|
| **Rank tracking agent** | Organic drop trigger (owns the drop definition) · GSC signal triage (position / impressions / CTR) · keyword cannibalization · SERP-shape & intent shifts · suspected algo updates | 🔧 In development |
| **Geo-grid tracker** | Maps drop trigger (owns the geo-grid drop definition) | ✅ Built into app |
| **Offpage agent** | Lost referring domains/links · citation status · unnatural RD spikes | 🔧 In development |
| **LABS (Local AI Brand Strength)** | Scheduled monitoring of AIO + LLM visibility per brand · suggests corrections when a brand isn't shown · win = **mention AND link** | ✅ Built into app |
| **On-page agents (×4)** | On-page optimization execution for: **blog posts · local landing pages · service pages · location pages**. Page types **outside** this coverage (home, About, bios, neighborhood, hub/archive pages) are manual — route to Minda/Ivy per §6 or flag. | ✅ Built |

If an agent is unavailable, the receiving SOP's checklists are worked manually top-to-bottom using the internal tools.

## 2. Shared Definitions

Defined once here; SOPs reference, not redefine. If an SOP's local text conflicts with this section, this section wins and the conflict should be reported.

- **Highly competitive** (used by: Architecture SOP third-level gate; Link Building SOP strategy) — a target keyword is highly competitive if ANY of:
  - Page-1 average **true** referring domains **≥ 250** (tool read × 10), or page-1 average DR **≥ 50**
  - DataForSEO **keyword_difficulty ≥ 50** (0–100 scale)
  - Vertical is **legal, finance, government, or health** (automatic)
- **Tool-visibility discount (×10)** — backlink tools (DataForSEO, Ahrefs, Majestic) see only ~10% of links actually built. **True RD ≈ tool RD × 10:** scale *competitor* RD reads ×10; client RD is known-true (our build records — don't scale); always compare true-to-true. All RD comparisons and targets are stated in **true RD** (Link Building SOP §Referring Domains). The RD "sweet spot" is a **guideline of ~250 true RD** (= the old tool-measured 25 × 10) — the ×1.5 target rule governs and may exceed it.
- **The Backlink Equation** — Referring Domains + Link Juice (link strength) + Contextual Relevance = Ranking Power (per page, not per domain).
- **No aggregate link cap** — links are built monthly; over-reliance on one tactic (MC4) is a judgment call, not a numeric cap.
- **Delivered Link Juice** = Host Juice (UR/DR) × Relevance% (0.10–1.00) × Follow multiplier (DF% + NF% × 0.15) × Modifiers (subdomain ×0.5). Master link-type table lives in the Link Building SOP.
- **GBP-linked page** — the page whose URL is set as the website link in a Google Business Profile. The **second most important page of the site after the home page**. Selection rules: Maps SOP §The GBP Landing Page (multi-location → dedicated top-level location page per GBP; single GBP, multi-city → the GBP city's local landing page for its most valuable keyword; single-city single-service → home if it ranks the main keyword; SAB → home; sharing only for same-city GBPs). Gets the LocalBusiness schema variant (Architecture SOP), privileged internal linking (Architecture SOP), and priority link building (Link Building SOP).
- **Hub threshold** — ≤7 items → nav dropdown / direct links; ≥8 → hub page (`/services/`, `/areas-we-serve/`). Governs nav shape, hub existence, and homepage body links.
- **Ranking drop** — defined by the internal trackers (organic rank tracker for organic; geo-grid tracker for maps). Response owned by the Rank Drop Mitigation SOP (both branches active).

## 3. Global Agent Rules

**Escalation owners:** Kyle Sabraw and Ryan Maizis. All freezes notify them plus other Admins (client-card tag: **Admin**).

**Standing rules (apply everywhere):**
- **We never disavow.**
- **Never build links to:** Contact Us, Privacy Policy, ToS, Bio pages, sitemaps, images, PDFs, PPC landing pages.
- **Deprecated — do not use:** Patch.com (permanent), PBNs (for now), POI pages (architecture).
- Content creation and link building **both stop** under an active freeze.
- **Every published article/page carries a separate `<title>` and H1** — two distinctly worded strings, never the same text: a meta title (`<title>` tag / WP post title; ≤60 chars, keyword-leading, no brand suffix — the site's SEO plugin appends that) and the on-page H1. Implemented in the writers (suite Blog Writer: brief `seo_title` vs `h1`; Topic Fanout writer: brief `seo_title` vs `title`/H1); WordPress publishes send the meta title as the post title with the H1 as the body's first element. A legacy article with no distinct meta title publishes with its H1 as the fallback — acceptable, but new content must generate both.

**Universal halt-and-ask triggers** — the agent stops and escalates instead of proceeding when:
1. A required input is missing and cannot be fetched (don't guess).
2. Two SOPs appear to conflict (report the conflict; don't pick a side silently).
3. No SOP owns the decision (see §1).
4. A client is under an active freeze.
5. An action is irreversible or high-risk and not explicitly authorized by an SOP threshold (e.g., overclock diagrams outside their gates).
6. The doc's own text conflicts with §2 shared definitions.

## 4. Workflow Chain

How the SOPs hand off across a client engagement:

```
Site Architecture SOP
  → emits the SITE PLAN (page list, URLs, nav, schema, internal links)
    → Content pipeline (AR Tools) fills the plan with pages
      → On-page agents optimize them (criteria spec pending)
        → Link Building SOP targets them (per page type, competition)
          → Geo-grid + organic rank trackers measure (apps)
            → Rank Drop Mitigation SOP responds to drops (Maps ✅ / Organic ✅)
            → AIO SOP optimizes for AI Overviews         ✅
```

Each SOP carries a short cross-reference block pointing here; SOPs do not point at each other directly (prevents n² drift).

## 5. Data Sources

| Data | Source | Used by |
|---|---|---|
| Page-1 avg RD / DR / UR | Ahrefs / Majestic SERP checks | Competitive gate, link strategy |
| Keyword competitiveness | DataForSEO | Competitive gate |
| Neighborhood qualification | Google Maps left-panel test (or Gemini verification) | Architecture Step 7; Rank Drop Maps §B |
| GBP data (reviews, hours, geo) | GBP / GBP Info | Schema generation |
| Rankings / drops | Organic rank tracker, GeoGrid tracker | Drop handoff, maps targeting |
| Manual actions / index status | GSC (checked daily) | Freeze Protocol |

---

## 6. Roles / Skills Matrix & Task Assignment

Small-shop team. This is the reference the rank-tracker/geo-grid apps and any orchestrating agent read to answer "who can be assigned this task, and what runs first."

### Team & capabilities

| Person | Role | Handles |
|---|---|---|
| **Kyle Sabraw** | Owner / Admin / Senior SEO | Deep strategy + escalation authority. Also hands-on: guest posts, niche edits, ordering PRs, Agency Assassin. *(Wears both hats — is both the escalation target and the operator for high-skill link tasks.)* |
| **Ryan Maizis** | Owner / Admin / Senior SEO | Deep strategy + escalation authority. Web dev tasks (schema implementation, site builds), review management. |
| **Minda** | Project Manager | Assigns/manages tasks, client comms. Content, orders citations, all SEO NEO tasks (incl. GBP Blasts / Hyper Local GBP Blasts / GBP Sniper), GBP posting cadence. Routes SEO NEO overflow to Ivy. |
| **Ivy** | Generalist VA | Content, SEO NEO, Map Embeds, initial GBP optimization. |

### Task → assignee

| Task | Primary assignee | Notes |
|---|---|---|
| Strategy decisions, sign-offs, escalations | Kyle / Ryan | Senior-only |
| Seed keyword selection (onboarding) | Kyle | Defines the entity vector — senior-owned |
| Guest posts, niche edits, PR orders | Kyle | |
| Agency Assassin | Kyle | Clients ≥ $1,200/mo only |
| All SEO NEO runs (diagrams, GBP Blast, Hyper Local GBP Blast, GBP Sniper) | **Minda** → overflow to Ivy | |
| Map Embeds | Ivy | |
| Citations | Minda | |
| Content production | Minda / Ivy | |
| Initial GBP optimization | Ivy | |
| Home page optimization | AI SEO agent (future); manual Minda/Ivy until it ships | Only uncovered page type that is a ranking target |
| Ongoing GBP posting (5×/wk) & photos (2×/wk) | Minda | |
| Web dev (schema implementation, site builds) | Ryan | |
| Review management | Ryan | |
| Task assignment & client comms | Minda | |
| Entity/social ring cadence (YouTube, TikTok, Reddit, etc.) | **Client** | Left to the client — not an agency task |
| GBP suspension / duplicate listing | Kyle / Ryan | Escalation-only; AI + Jr must not attempt |
| Overclock diagrams (Hydra / DAS v2 w/ RD100) | Self-serve if thresholds met (Link Building SOP); else Kyle / Ryan | |

**Unstaffed → flag, don't guess:** if a task maps to no assignee above, the agent flags it as unstaffed rather than assigning it.

### Prioritization (finite capacity)

Assign in this order:
1. **Active ranking drops** — worst-ranked / most-severe first.
2. **Optimization** — net-new ranking work.
3. **Maintenance** — standing tactics stack, ongoing GBP posting, keeping existing rankings.

**Tiebreaker within every tier: larger client budget first.**

---

## 7. Rate Limits & Caps

Consolidated limits (each owned by its SOP; listed here for one-stop agent reference):

| Limit | Value |
|---|---|
| Tier-1 velocity (manual links only) | ≤ 1/day per page — SEO NEO internal drip exempt |
| Tier 2–5 velocity | drip over 30 days |
| Press releases | once per 4–6 weeks |
| RD sweet-spot guideline | ~250 true RD when scaled SERP avg < 250 (the ×1.5 target rule governs — not a hard cap) |
| Hydra at a client page | page RD >100 · homepage >200 · SERP avg >100 |
| DAS v2 w/ RD100 | page UR 5–25 · homepage UR 15–45 |
| RD100 pacing | drip over 3–4 weeks |
| SEO NEO URLs per run | ≤ 5 |
| IFTTT ring | once per client, ever |
| GBP Blast / Sniper / Map Embeds | 1×/wk · per-keyword + on drops · 1×/mo |
| Spend | deployable = retainer × (1 − margin); < 50% margin → escalate |
| Reviews | steady cadence, faster than competitors; no numeric ceiling (deliberate) |

**No aggregate cross-tactic cap (deliberate ruling):** there is no numeric cap on total combined link activity per page per month. Links are built every month; **MC4 proportionality is a judgment call** made by the SEO running the campaign (senior review at escalation points). Agents apply the per-tactic limits above and flag — not block — unusually stacked months.
