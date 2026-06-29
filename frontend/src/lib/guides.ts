// In-app Guides portal content. Static, developer-maintained instructions for how
// to use each module + suite workflows. Rendered by pages/Guides.tsx via the
// suite's Markdown component. To add a guide: append an entry here (the index and
// detail views pick it up automatically). Body uses the Markdown subset the
// components/Markdown.tsx renderer supports (#/##/###, **bold**, - bullets,
// pipe tables, --- rules).

export type GuideCategory = 'Start here' | 'Content' | 'Tracking' | 'Reporting' | 'Setup'

export interface Guide {
  slug: string
  title: string
  category: GuideCategory
  icon: string          // lucide icon key; mapped in pages/Guides.tsx
  summary: string
  body: string
}

export const GUIDES: Guide[] = [
  {
    slug: 'getting-started',
    title: 'Getting started',
    category: 'Start here',
    icon: 'Rocket',
    summary: 'How the suite is organised and the basic workflow: pick a client, then work across modules.',
    body: `# Getting started

AR Tools is an internal suite of SEO/content modules that all share **one login, one dashboard, and one database**. Almost everything is organised **per client**.

## The basic workflow
1. From **Home**, pick a client tile (or open **Clients** to add one).
2. You land in the client's **workspace** — a dashboard of cards grouped into sections (Content, Rank Trackers, Project Management, Reporting).
3. Click a card to open that module for the selected client.

## Setting a client up well
The more context a client has on file, the better every module performs:
- **Website + Google Business Profile** — drives local data, competitors, and reviews.
- **Brand voice + ICP** — shapes generated content and now the Action Plan's tailored recommendations.
- **Reference page structures** — let generated pages mirror the client's existing layout.

See the **Client setup** guide for where each of these lives.

## Tips
- The left nav has suite-wide shortcuts (Runs, Articles, Silos, Clients, Workload, Playbook, Guides).
- The **Dashboard** shortcut in the nav jumps back to the workspace of whatever client you're inside.`,
  },
  {
    slug: 'sops-playbook',
    title: 'SOPs & Playbook (upload your SOPs here)',
    category: 'Start here',
    icon: 'BookOpen',
    summary: 'Where to upload SOPs and strategic theories so the Action Plan tailors its recommendations to your methodology.',
    body: `# SOPs & Playbook

Upload your **standard operating procedures** and **strategic theories** here. Loaded SOPs are used to rewrite the **Action Plan's** recommendations in your own methodology and voice — turning generic advice into your team's actual playbook.

## Two layers
- **Agency-wide playbook** — applies to *every* client. Open **Playbook** in the left nav (or go to \`/playbook\`). This is the best place to start.
- **Per-client SOPs** — apply to one client and take precedence for them. Open the client's workspace → **SOPs & Playbook** card (under Rank Trackers), or go to \`/clients/<id>/sops\`. This view also shows the agency entries it inherits (read-only).

## How to upload
1. Give the SOP a **Title**.
2. Pick a **category**: general, reoptimization, link building, local, content, or theory.
3. Either **paste the text** into the box, **or** click **Upload a document** (PDF / DOCX / MD / TXT) — the file is parsed and its text dropped into the box for you to review.
4. Click **Add SOP**.

You can **enable/disable** or **delete** any entry later. Disabled entries are kept but not used.

## How it powers the Action Plan
When a client's Action Plan is built (weekly, after a ranking drop, or when you click **Rebuild**), one AI pass rewrites each task using your enabled SOPs + the client's context (ICP, differentiators, GBP). Tasks then show a **★ Tailored to your SOPs** badge with a *Why / What's needed / Based on* breakdown in their dropdown.

## Tips
- **No SOPs loaded?** The Action Plan still works — it falls back to a generic per-task guide, and no AI cost is incurred until you add a playbook.
- Uploading/editing is **admin-only** (matches the rest of client config).
- Good starters: a *ranking-drop recovery* SOP, a *link-building* SOP, a *quick-win reoptimization* SOP, and any *theories* about what drives rankings for your niches.`,
  },
  {
    slug: 'action-plan',
    title: 'Action Plan',
    category: 'Tracking',
    icon: 'ListChecks',
    summary: 'A prioritized, recommend-only to-do list built from a client\'s rank-tracker signals.',
    body: `# Action Plan

A prioritized **reoptimization to-do list** for a client, built automatically from signals the other trackers already produce. It's **recommend-only** — every task deep-links into the tool that does the work; nothing is auto-executed.

## What's in it
Each task shows the **channel** it came from (Organic search / Local pack · Maps / AI·LLM), the **keyword or target** it's for, a short diagnosis, and a recommendation. Sources include:
- Open **ranking drops** (organic) — diagnose & reoptimize, or confirm indexing.
- **Quick wins** — winnable, valuable keywords (Rankability).
- **GSC Research** — cannibalization and page-2 "hidden wins".
- **Local pack** — Maps geo-grid declines, weak coverage areas, GBP/review/backlink/content gaps.

## How to use it
1. Open a client's workspace → **Action Plan** card (or \`/clients/<id>/action-plan\`).
2. Click **Why this & what's needed** on any task to expand the detail.
3. Click the task's button to jump into the tool that fixes it.
4. Click **Rebuild** anytime to regenerate from current signals.

## Make it more detailed
Load **SOPs** (see the SOPs & Playbook guide). With a playbook on file, each task is rewritten into your methodology, with concrete steps and the SOPs they draw on.

## Cadence
- Rebuild on demand anytime.
- A **weekly digest** notification.
- A silent **rebuild on a new drop**.

## Tips
- The plan auto-refreshes the **competitor-GBP + backlink** data it needs (interval-gated), so the GBP benchmark and backlink recommendations populate over a cycle or two.
- Empty plan with a green check = no actions needed right now.`,
  },
  {
    slug: 'blog-writer',
    title: 'Blog Writer',
    category: 'Content',
    icon: 'FileText',
    summary: 'Generate a publication-ready, SEO + AEO-optimized article from a keyword.',
    body: `# Blog Writer

Generates a publication-ready Markdown article from a keyword, through a five-stage pipeline (brief → terms/entities → research → writer → sources cited).

## How to use it
1. Open a client's workspace → **Content** section.
2. Start a run with a **keyword** for the client.
3. The pipeline runs as a background job — track it under **Runs** (or the client's content view).
4. When complete, review the article, then **publish** it as a Google Doc into the client's Drive folder.

## What shapes the output
- The client's **brand voice** and **ICP**.
- **Reference page structures** (blog post type) so the intro + body mirror the client's style.
- SERP-driven outline, entity coverage, and external citations.

## Tips
- The blog brief is cached and client-agnostic, so it's reused across clients — the *client* flavour comes from voice/ICP/structure at the writing stage.
- Check **Articles** for everything generated across the suite.`,
  },
  {
    slug: 'local-seo',
    title: 'Local SEO content',
    category: 'Content',
    icon: 'Building2',
    summary: 'Generate, score, and reoptimize local landing/service/location pages — plus silo planning.',
    body: `# Local SEO content

Generates local landing, service, and location pages (competitor analysis → AI generation → 8-engine scoring/auto-reoptimization), with silo planning to scale coverage.

## Core flows
- **New page** — enter a service + area. A precheck first looks for an existing/ranking page on that topic; if found, it offers to **reoptimize** it or write a new one.
- **Plan Silo** — seed a service + area and get candidate page targets grouped into silos, each marked **found** (already in tool), **on_site** (exists on the live site), or **missing** (offered for creation). Multi-select → **bulk create**.
- **Reoptimize** — score and improve an existing URL (single or bulk).
- **Saved Pages / Drafts** — manage generated pages; deleting soft-deletes to Drafts (restore or purge).

## How to use it
1. Open a client's workspace → **Local SEO** card.
2. Pick a flow (New page, Plan Silo, or Reoptimize).
3. Long jobs run in the background — use **Leave & finish in the background** and the page lands in Saved Pages when done.

## Tips
- The silo planner discovers **other cities** the business serves (GBP service area, manual list, site, nearby) and verifies neighborhoods by geocoding.
- The existing-page check reads the client's **live site** (sitemap or Google index), so you don't duplicate pages.`,
  },
  {
    slug: 'keyword-research',
    title: 'Keyword Research & Content Scheduler',
    category: 'Content',
    icon: 'Sparkles',
    summary: 'Topic-fanout keyword clustering and a VA content scheduler for mass content creation.',
    body: `# Keyword Research & Content Scheduler

The Topic Fanout tool: expand a seed into clustered keyword silos, then schedule content (blog posts or Local SEO pages) to be produced on a cadence.

## How to use it
1. Open a client's workspace → **Content Scheduler** card.
2. Run a fanout from a seed topic to get clustered keywords.
3. Create a **schedule** — choose the content type (blog post or local SEO page) and, for local pages, a target **location** (DataForSEO typeahead).
4. The scheduler produces content on the cadence; local SEO pages land in the client's Saved Pages (first-class, scorable/publishable).

## Tips
- Link the session to a client + location to enable Local SEO page scheduling.
- This module is mounted under \`/fanout\`; it shares the same login and database.`,
  },
  {
    slug: 'rank-tracker',
    title: 'Organic Rank Tracker',
    category: 'Tracking',
    icon: 'TrendingUp',
    summary: 'Hybrid GSC + DataForSEO rank tracking, with SERP snapshots, rankability, and reports.',
    body: `# Organic Rank Tracker

Tracks organic rankings per client using **Google Search Console** where possible, falling back to **DataForSEO** when GSC can't cover a keyword.

## What it gives you
- Daily rank metrics with a computed status taxonomy and rank-drop alerts.
- **Pages view**, striking-distance discovery, canonical pinning, CSV export.
- **SERP snapshots** — a dated capture of the SERP landscape per keyword (AI Overview, top-10, backlinks, intent signals, topical focus).
- **SERP Trends**, **Rankability** (a 0–100 winnability score + Quick wins).
- On-demand + scheduled **client reports**.

## How to use it
1. Open a client's workspace → **Rankings** card.
2. Add/track keywords; review status, trends, and alerts.
3. Use the camera icon on a keyword to capture a SERP snapshot.

## Tips
- Full GSC features need a verified Search Console property + a service-account key configured. Until then it runs in DataForSEO-only mode.
- Rank drops feed the **Action Plan** automatically.`,
  },
  {
    slug: 'maps-geogrid',
    title: 'Maps Geo-Grid (Local Dominator)',
    category: 'Tracking',
    icon: 'MapPin',
    summary: 'Local-pack rankings across a geographic grid, with a Local Rank Analysis report.',
    body: `# Maps Geo-Grid

Measures how a business ranks in the Google **local pack** across a grid of points around its location — revealing where it's strong and where it fades.

## What it gives you
- A heatmap grid per keyword + ring/direction rollups.
- A **Local Rank Analysis report** (auto-generated when a scan completes), published as a Google Doc.
- **Weak coverage areas** reverse-geocoded to real nearby city names (targets for location pages).
- Competitor leaderboards, Share-of-Local-Voice trend, and alerts.

## How to use it
1. Open a client's workspace → **Maps** card.
2. **Run scan now** (or set a weekly schedule).
3. When complete, review the grid, the report, and the weak-area table.

## Tips
- Weak areas + local-pack declines feed the **Action Plan**.
- Run the **Competitors** fetch here to populate competitor GBP profiles — that powers the GBP benchmark and backlink comparisons.`,
  },
  {
    slug: 'ai-visibility',
    title: 'AI Visibility (Brand Strength)',
    category: 'Tracking',
    icon: 'Eye',
    summary: 'Track whether a brand appears in AI assistant answers across six engines, over time.',
    body: `# AI Visibility

Tracks whether a client's brand shows up when AI assistants answer its keywords — across **ChatGPT, Claude, Gemini, Perplexity, Google AI Overview, and Google AI Mode** — over time.

## What it gives you
- Per-engine visibility, an SVG trend line, and a keyword×engine **mention matrix**.
- Click a ✗ cell for an **invisibility diagnosis**.
- Competitor comparison, keyword suggestions, scheduling, and a published **report**.

## How to use it
1. Open a client's workspace → **AI Visibility** card.
2. Add keywords (and competitors), then **Run scan** — watch live progress.
3. Use the matrix + diagnosis to see where the brand is missing and why.
4. Set a weekly/monthly schedule and generate a report when needed.

## Tips
- Use the "Show visibility for" selector to view a competitor's results.
- Export the full scan history as CSV.`,
  },
  {
    slug: 'gsc-research',
    title: 'GSC Research',
    category: 'Tracking',
    icon: 'FileSearch',
    summary: 'Mine Search Console for cannibalization, quick wins, and hidden wins.',
    body: `# GSC Research

On-demand opportunity analysis from a live Search Console query×page pull (~90 days). Surfaces three opportunity types.

## What it finds
- **Cannibalization** — a query split across multiple URLs, none ranking well (Google can't pick a page).
- **Quick wins** — query×page at positions 6–10.
- **Hidden wins** — query×page at positions 11–30 with demand.

Quick/hidden wins are enriched with CPC / volume / competition.

## How to use it
1. Open a client's workspace → **GSC Research** card.
2. Run an analysis (it polls while in flight).
3. Review the three tabbed tables; export per-table CSV.

## Tips
- Requires a verified GSC property + service-account key. Without them it returns empty results.
- Runs automatically once a client is GSC-eligible, then refreshes monthly. Findings feed the **Action Plan**.`,
  },
  {
    slug: 'client-reports',
    title: 'Client Reports',
    category: 'Reporting',
    icon: 'FileBarChart',
    summary: 'Generate owner-friendly PDF reports assembled across the suite.',
    body: `# Client Reports

Generates a client-facing **PDF** report written for the business owner — plain, upbeat, wins-focused, no jargon, no health score.

## What's in it
- A KPI strip of hero numbers and 30/90-day comparisons.
- Organic rankings (top movers), Maps geo-grid, GBP profile + reviews.
- AI search visibility (once scans have run).
- A "Work delivered this period" section and an AI executive summary.
- White-labeled footer (your agency name).

## How to use it
1. Open a client's workspace → **Client Reports** card.
2. Generate on demand; watch status; download the PDF when ready.

## Tips
- Sections degrade gracefully — anything with no data is hidden.
- GA4/GBP time-series and email/Drive delivery + scheduling are on the roadmap.`,
  },
  {
    slug: 'asana-tasks',
    title: 'Asana Tasks',
    category: 'Reporting',
    icon: 'ClipboardList',
    summary: 'Define the monthly delivery tasks each client gets and dispatch them to Asana.',
    body: `# Asana Tasks

Define the set of tasks a client should get each month — name, assignee, and category — and the monthly job creates them in Asana under a new section.

## How to use it
1. Open a client's workspace → **Asana Tasks** card.
2. Define the client's task templates.
3. Tasks are created automatically each month, or on demand.

## Tips
- See **Workload** in the nav for team capacity across clients.`,
  },
  {
    slug: 'client-setup',
    title: 'Client setup & context',
    category: 'Setup',
    icon: 'Settings',
    summary: 'Where to set the website, GBP, brand voice, ICP, and reference structures that power every module.',
    body: `# Client setup & context

Every module performs better with more client context on file. Here's where each piece lives (open a client's workspace).

## The essentials
- **Website + Google Business Profile** — set on the client form (you can paste a GBP link to auto-resolve and auto-fill name/website). Powers local data, competitors, and reviews.
- **Brand voice** — the **Brand Voice** card. Distilled and used by content generation.
- **ICP & differentiators** — the **ICP** card. Auto-detected from the site, editable. Used by content *and* the Action Plan's tailored recommendations.
- **Reference page structures** — four per-client reference URLs whose structure is scraped so generated pages mirror the client's layout.
- **Logo** — shown on the dashboard tile and reports.
- **Target cities** — extra cities the business serves, used by the Local SEO silo planner.

## Tips
- Set GBP early — it unlocks Maps, reviews, and competitor data.
- For GSC features, a verified Search Console property + service-account key must be configured (an admin/infra step).`,
  },
]
