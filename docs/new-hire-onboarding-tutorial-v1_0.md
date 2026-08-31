# New Hire Onboarding — Set Up a Client, Start to Finish

*A hands-on tutorial for a brand-new account manager. By the end of this document you will have
taken one client from "doesn't exist yet" to fully configured: profile, brand voice, ICP, every
integration, both trackers, goals, reporting, and a live task board. Nothing here is hard — it's
mostly filling in forms in the right order and knowing why each one matters. Budget a day.*

> **What this document is not.** This is the *setup* tutorial — one pass through every screen you
> touch when onboarding a client. It is deliberately light on any one tool's day-to-day depth.
> Once you've done this once, go deeper on the tools you'll use most:
> - **`docs/sermastr-user-guide.md`** — SerMaStr, the AI strategist you'll talk to constantly.
> - **`docs/native-task-manager-user-guide.md`** — the task board, once it's full of real work.
> - **`docs/pace-qa-user-guide.md`** — PACE (delivery-chasing) and QA (deliverable review).
> - **`docs/website-builder-user-guide.md`** — building a client a whole new website (a separate,
>   optional module — not part of standard onboarding).
>
> This tutorial covers **one client's setup**, using integrations the agency has already
> provisioned (Google API access, Apps Script, GitHub, Slack apps, DataForSEO). You are not
> setting any of that up — you're the person who *uses* it, per client.

---

## Terms you'll see

| Term | Means |
|---|---|
| **Client workspace** | The one page per client (`/clients/:id`) that every tool in this tutorial hangs off of — a grid of "cards," each opening one tool. |
| **GBP** | Google Business Profile — a client's Google Maps/Search listing. Two *unrelated* things share this name in the app; §4 exists specifically to untangle them. |
| **GSC** | Google Search Console — Google's own analytics for a website's search performance. |
| **GA4** | Google Analytics 4 — website traffic analytics (separate product from GSC). |
| **ICP** | Ideal Customer Profile — who the client's content should be written for. |
| **Geo-grid** | A grid of simulated searches around a business, used to measure Google Maps / local-pack rank at every point on the map, not just one. |
| **DataForSEO** | The third-party data provider behind rank checks, keyword volume, and SERP data — you'll never touch it directly, just know it's the engine under several tools. |
| **Recipe Engine** | The budget→task-plan calculator (Monthly Task Plan). Not the same thing as the task board. |
| **PACE** | The agent that keeps the task board moving day to day (§13). |
| **SerMaStr** | The agent that reasons about strategy and campaign health across everything in this tutorial. |
| **Staff / admin** | Account roles. Creating or editing a client requires **staff** or **admin**. A **team_member** account can view most of this but can't create a client. |

---

## Before you start

- **You need a staff or admin login.** If you can't see a **"+ New Client"** button on the
  **Clients** page, ask an admin to raise your role — client creation is gated to staff+.
- **Nothing in this tutorial requires you to set up an integration from scratch.** Every Google
  connection (Business Profile, Search Console, Analytics), the GitHub/Apps Script publishing
  plumbing, and the Slack apps are agency-level, one-time setup an admin already did. Your job is
  the **per-client** half of each — pointing an already-working pipe at *this* client.
- **A few external steps need someone with access to the client's own accounts** (their Search
  Console, their Google Analytics, their WordPress admin). This tutorial flags each one clearly —
  they're the only steps you truly cannot do by yourself inside the dashboard.
- **Keep this order.** Some steps quietly depend on earlier ones (Goals reads keywords you tracked
  in §8–10; Reporting reads almost everything). Skipping around works, but following the order
  below means nothing you set up is empty when you get to it.

---

## The big picture

"Setting up a client" is really four kinds of work, roughly in this order:

1. **Identity** (§1–3) — who they are, how they sound, who they're selling to.
2. **Connections** (§4–7) — wiring the dashboard to the client's own Google accounts, and telling
   it where finished content should land (a Doc, WordPress, GitHub).
3. **Instruments** (§8–11) — the trackers that measure the campaign, and the goals that judge it.
4. **Operations** (§12–13) — the report the client sees, and the board your team works from.

Every step below happens from the **client workspace**. Once the client is created, its workspace
is organized into sections you'll recognize by name as you go: **Client setup**, **Content**,
**Rank Trackers**, **Reporting**, and **Project Management**. Each card in those sections is one
step in this tutorial.

---

## Step 1 — Create the client (Business Profile)

**Where:** Sidebar → **Clients** → **+ New Client** (`/clients/new`).

This one form does a lot — take it section by section. Nothing here is a dead end; every optional
section you skip today, you can come back and fill in later from **Edit** on the same client.

### Basic Info

| Field | Required? | What it's for |
|---|---|---|
| **Client Name** | Yes | Must be unique — the system rejects an exact duplicate name. |
| **Website URL** | Yes, on this form | The moment you save, the homepage is automatically scraped and analyzed to extract services and locations. This is what kicks off most of the automation described below — see "What fires automatically," at the end of this step. |
| **Logo** | No | JPG/PNG, up to 2MB. Shows on the client's tile and workspace header. |

### Google Business Profile

> ⚠️ **This is a data snapshot, not a live connection.** Attaching a GBP here just pulls a
> one-time copy of the client's public listing (address, category, rating, top reviews) to feed
> content generation. It needs no Google login and grants no ongoing access. The *live* connection
> that lets you post to GBP or pull performance metrics is a completely separate step — **§4**.
> Conflating these two is the single most common new-hire mix-up in this tutorial.

- Search box: type the business name + city, pick from the dropdown. **Or**, below the "or paste a
  link" divider, paste a Google Maps URL / share link / place ID and click **Fetch**.
- Once attached, it shows as a card (name, address, rating, category, phone, "N reviews
  captured") with a **Remove** (✕) option.
- If **Client Name** or **Website URL** were still blank, attaching a GBP auto-fills them from the
  listing — it never overwrites something you already typed.

### Brand Guide / ICP (the seed text)

Two plain textareas — **Brand Guide Text** and **ICP Text**. Paste in anything the client gave
you (a style guide, a description of their customer) if you have it; leave blank if you don't. This
is only the *seed* — the polished, structured versions live on their own pages, **§2** and **§3**,
and an automatic scan fills them in either way. Whatever you type here is never silently
overwritten by that scan.

### Search Console & Local Rankings

| Field | Note |
|---|---|
| Search Console Property | ⚠️ **Ignore this field.** It's marked *Roadmap* in the UI for a reason — nothing reads it. The real GSC connection is **§5**. |
| Primary Business Location | A fallback street address, only used for local-SEO page generation *if* no GBP is attached above. |
| Target Cities | Comma-separated extra cities for the Local SEO silo planner, on top of what it already auto-derives from the GBP service area, the client's own site, and a ~10-mile radius. Leave blank unless you already know of specific extra cities to target. |

### Budget & Campaign Type

| Field | What it drives |
|---|---|
| **Monthly Budget (retainer)** | Feeds the **Recipe Engine** (§13e) — a live hint shows how much of it is "deployable" on tasks once you type a number. |
| **Client Type** — *Local* / *Enterprise / e-commerce* | Sets which category the Recipe Engine funds first when money is tight. |
| **Service-Area Business (SAB)** checkbox | Check this for a client with a hidden address (no storefront) — it changes which baseline tasks are funded. |
| **Auto-illustrate content** checkbox | Off by default. Turn on if you want every finished blog post to automatically get a hero image + inline visuals. |
| **Strategist Review Day** | Which weekday SerMaStr's weekly review runs for this client. Leave on Default unless you're deliberately staggering clients across the week. |
| **PACE Slack Channel** | Optional. If this client has its own Slack channel, paste its ID/name here so PACE posts task notifications there instead of the shared team channel — the PACE bot needs to be invited to that channel first. |
| **Everhour Project** | Optional, only relevant if the agency tracks time in Everhour for this client. Leave blank otherwise. |

### Reference Page Structures (optional — skip for Day 1)

Six page types (Local Landing, Service, Location, Blog Post, Product, Solutions) where you can
point at a live example URL — or type written guidelines — so generated pages mirror an existing
layout. Not required to get a client running; come back to it later if a client cares about a
specific page structure.

### Google Drive / WordPress / GitHub Publishing

Three more sections at the bottom of this same form — where finished content is allowed to be
published to. **§7** below covers all three in depth (they're worth understanding properly, not
rushing through); it's fine to leave them blank now and fill them in when you get there.

### Save it

Click **Save Client**. Here's exactly what happens automatically the moment you do (nothing here
needs a click from you):

| Always fires (website URL is required) | Only if you filled in the optional field |
|---|---|
| Homepage scrape + analysis | GitHub content-repo inference (needs a GitHub repo set) |
| Brand voice auto-scan | Reference-page-structure scrape/parse (needs at least one of those six URLs/guidelines) |
| ICP auto-scan | Rank-tracking location auto-derive (needs a GBP attached) |
| Backlink domain tracking (best-effort) | |
| Deliverables-sheet provisioning (best-effort) | |

None of this is an "agent" acting — it's plain background automation. Give it a few minutes before
you move to §2, so there's something to review instead of an empty page.

---

## Step 2 — Brand Voice

**Where:** Client workspace → **Client setup** → **Brand Voice** card (`/clients/:id/brand-voice`).

One voice, used by every writer in the suite (Blog, Local SEO, Ecommerce). The page's own
subtitle says it best: *"Your own input always wins; if you don't set it, the app generates one."*

- **Nothing yet?** A card reads **"No brand voice yet"** with two buttons: **Scan website** (or
  **Generate from category** if the client has no website) and **Write your own**.
- **Scanned already** (from Step 1's automatic job): you'll see a badge — **"AI-generated"** — and
  a distilled card: Tone, Personality, Writing style, Words to use / Words to avoid, Messaging
  themes, Sample phrases, Writer instructions.
- **Review it.** If it reads right, you're done — move on. If it's off, click **Write your own**
  and paste in the client's real brand guide as plain text; that becomes the new source of truth
  (badge flips to **"Set by you"**) and nothing auto-generated ever overwrites it again.
- **Regenerate** re-runs the scan — if a user-set voice exists, it asks you to confirm before
  replacing it.
- If the system proposes an updated voice later (say, after a site redesign), you'll see a
  **"Recommended voice"** card with **Use this** / **Keep current** — nothing changes until you
  pick one.

You can only *edit* the free-text version here, not hand-tweak individual fields of the distilled
card — if a specific field is wrong, rewrite the whole thing as your own text.

---

## Step 3 — ICP & Differentiators

**Where:** Client workspace → **Client setup** → **ICP & Differentiators** card (`/clients/:id/icp`).

Same pattern as Brand Voice, one page over:

- Empty state: **"No ICP yet"** → **Detect ICP** or **Write your own**.
- Detected/scanned: one card per customer **segment** (label + a **PRIMARY** badge on the main
  one + a confidence %), each showing Demographics, Situation, Search trigger, Fears,
  Motivations, Buying behavior, Messaging tone, Headline hooks, Trust signals — plus a **"Why
  these segments"** box explaining the reasoning, and a separate **Differentiators** card (what
  makes this client different, and why that claim actually holds up).
- Same **Edit / Regenerate** pattern, same "your text always wins" rule, same confirm-before-
  overwrite on Regenerate.

Both Brand Voice and ICP quietly power every piece of content this client's tools will ever
generate — worth actually reading before moving on, not just clicking through.

---

## Step 4 — Connect Google Business Profile (the live connection)

This is the other "GBP" — the real one. Two things happen here, and they are genuinely separate:

### 4a. The agency-wide connection (check this once, don't repeat it per client)

Both the **GBP Posts** card (`/clients/:id/gbp-posts`, in **Content**) and the **GBP Insights**
card (`/clients/:id/gbp-metrics`, in **Reporting**) show the same connection bar at the top:

- **Green bar, "Connected to Google Business Profile as {email}"** → already done, agency-wide.
  Skip straight to §4b.
- **Blue bar, button "Connect Google Business Profile"** → not connected yet. Anyone staff+ can
  click it, sign in as the agency's Google account on the consent screen, and it's done — for
  every client, forever, until someone disconnects it. You will very rarely be the person doing
  this; check with an admin before you do.
- **Grey/no button, "isn't available yet"** → the server-side OAuth app itself isn't configured.
  Not your problem to fix — flag it to an admin.

### 4b. Register *this client's* location — on both pages, separately

Even with the agency-wide connection live, each client's specific Google listing has to be
matched and switched on — **once for Posts, once for Insights**, in two unrelated tables. Doing
one does not do the other.

- **GBP Posts page:** it auto-matches "This client's Business Profile" from the connected
  account's managed listings. If the match looks right, click **Use this profile**. If not, click
  **Show all** to pick manually.
- **GBP Insights page:** click **Find locations**, then **Connect** next to the right one, then
  **Verify** (a live test pull). Once it shows verified, a **Backfill** button appears — click it
  to pull ~18 months of history instead of waiting for it to accumulate day by day.

If either page shows a "not enabled yet" notice instead of any of this, the whole module is off
agency-wide — again, an admin problem, not something to debug yourself.

---

## Step 5 — Connect Search Console (GSC)

**Where:** Client workspace → **Rank Trackers** → **Organic Rank Tracker** card → **Settings** tab
(`/clients/:id/rankings`).

### The one truly external step

Card **"1 · Grant the service account access"** shows a service-account email address with a
**Copy** button. **Someone with access to the client's own Search Console** — you, if you have
it, or the client — needs to:

1. Open the client's Search Console → **Settings → Users and permissions**.
2. Add that copied email as a user (**Restricted** is enough).

There is no way to do this from inside AR Tools — it happens entirely on Google's side.

### Back in the dashboard

- Card **"2 · Properties"** → **Add property** → **Property URL** field. Use the exact right
  format: a URL-prefix property needs the full `https://…/` with a trailing slash; a domain
  property needs the `sc-domain:` prefix.
- Each property row shows a status pill: **Pending** → **Connected** (green) or **No access**
  (red). Click **Verify access** to run a live check.
- Once verified, click **Sync now** to pull data immediately (don't just wait for the nightly
  job), and **Backfill history** (confirms via a dialog) to pull ~16 months of past data so the
  client doesn't start from a blank chart.

### Two adjacent cards on the same Settings tab, worth setting at the same time

- **Tracking location** — auto-set from the GBP if one's attached, or set manually. This drives
  the *local* rank checks (DataForSEO), not Search Console — GSC's own numbers stay national no
  matter what you put here.
- **Rank-data refresh schedule** — cadence for the DataForSEO live-rank pull, independent of GSC's
  own daily sync.

### If you don't have GSC access yet

The rank tracker still works — it shows a blue **"DataForSEO"** pill instead of green **"Search
Console"** and lands on the Keywords tab instead of an Overview. Connecting GSC later unlocks the
Overview, Pages, and Brand-search tabs and real click/impression numbers; it isn't a hard
prerequisite to start tracking keywords (§8).

---

## Step 6 — Connect Google Analytics (GA4)

**Where:** Client workspace → **Reporting** → **Client Reports** card (`/clients/:id/reports`) —
a **"Google Analytics (GA4)"** card sits on that same page.

Same shape as GSC: copy the shown service-account email, have the client add it as a **Viewer**
under GA4 → **Admin → Property Access Management**, then click **Connect a property** (it lists
properties the service account can see, or you can paste a numeric property ID by hand), then
**Verify**.

> **Where this stands today:** the connect/verify flow itself works. Whether the generated PDF
> report is already pulling real GA4 traffic numbers into its Website Traffic section is newer and
> still settling — check with your lead before telling a client their report includes analytics.
> Connecting it now is still worth doing (it's live the moment the report side catches up); just
> don't treat "connected" as "showing up in the PDF" yet.

---

## Step 7 — Set up publish destinations

Three optional sections on the client's **Edit** page (the same form from Step 1) decide *where*
finished content is allowed to land. You can set any, all, or none — nothing here is required to
generate content, only to publish it once it's done.

### 7a. Google Drive

- **Drive Folder ID** — paste the ID from the folder's URL (the part right after `/folders/`).
  Before this works, grant the Apps Script account **Editor** access to that folder in Google
  Drive itself — a one-time, per-client external step.
- Below it, optional **per-content-type folders** (Blog posts / Service pages / Location pages /
  Local SEO pages / Ecom pages / Use cases) — each falls back to the default folder above if left
  blank. There's no documented reason you'd need these split apart — it's purely a routing
  convenience, not a permissions or approval-workflow feature. Skip this and use just the one
  default folder unless the client (or your team) specifically wants different content types
  organized into separate Drive folders.
- ⚠️ **Known gap:** the **Ecom pages** field doesn't currently do anything — ecommerce content
  always publishes to the *default* folder regardless of what's typed there. Don't rely on it;
  just make sure the default Drive Folder ID is set.
- **If no folder is set at all, publishing to Google Docs fails outright** (nothing auto-creates a
  folder). This is the single most common "why won't this publish" cause — check this first.

### 7b. WordPress

- **Site URL** (must be HTTPS), **Username**, **Application Password**. The client creates that
  password once in their own WordPress admin: **Users → Profile → Application Passwords** — copy
  it in exactly as shown, spaces included. Leaving the password field blank on a later edit keeps
  whatever is already stored; typing a new one replaces it.
- Once set, any finished blog post, service page, location page, local-SEO page, or ecommerce page
  shows a **"Publish to WP"** button on its own view — alongside **"Publish to Google Docs"** and
  **"Publish to GitHub."** These are independent — publishing to one destination doesn't use up or
  block the others; you can publish the same piece to more than one place.
- The unrelated **"Enable the WheelHouse IT page poster"** checkbox lives in this same section —
  ignore it unless a lead specifically tells you this client needs that separate bulk-page tool.

### 7c. GitHub — two different things share this name, on purpose keep them apart

- **Content-publish destination** ("GitHub Publishing" section, same Edit page: Repository,
  Branch, Content path, plus per-type overrides). ⚠️ Marked *Roadmap* in the UI, and whether the
  agency-level token that makes it actually run is live isn't something to assume — confirm with
  an admin before relying on it for a real client's publish flow.
- **Website Builder's per-site repo** — a completely different, confirmed-live feature: if you
  build a client a full generated marketing site (a separate, optional module — see
  `docs/website-builder-user-guide.md`), that site gets its own private GitHub repo automatically
  the moment you click **Provision** on the site's Overview tab. There's nothing to type on the
  client form for this one; it's not part of standard onboarding.

---

## Step 8 — Organic Rankings (the rank tracker)

**Where:** Client workspace → **Rank Trackers** → **Organic Rank Tracker** (`/clients/:id/rankings`).

1. **Keywords** tab → **Track keywords** → paste one keyword per line (or comma-separated) →
   **Add keywords**.
2. Click **Refresh live ranks** to pull a DataForSEO rank check right now (this works whether or
   not GSC is connected — §5).
3. If GSC is connected, an **Overview** tab appears: a plain-English headline + narrative, a
   triage table of every keyword sorted by how urgently it needs attention, and top-gainer /
   top-decliner callouts.
4. The **Alerts** tab is what feeds a rank-drop into the client's Action Plan (and eventually
   SerMaStr's weekly review) — nothing to configure, just know it's watching once keywords exist.

---

## Step 9 — Maps Geo-Grid

**Where:** Client workspace → **Rank Trackers** → **Maps Ranker** card (`/clients/:id/maps`).

1. **Setup** tab → fill in **Google Place ID**, **Business name**, and **Center latitude /
   longitude** — all three are required before any scan can run (a warning banner says so if
   they're missing). Then:
   - **Radius, miles** (1–10, shows a live pin-count estimate) — how far out from the center point
     to lay the grid. Bigger isn't automatically better: a wider radius costs more pins per scan
     and dilutes the average with far-out pins the client was never realistically going to rank at.
   - **Surface** — **Google Maps** measures rank inside the Maps app itself; **Local Finder (local
     pack)** measures the 3-pack block that shows under a normal Google search. The tool has no
     rule for which to pick; as a practical default, most clients care more about **Local Finder**
     (it's what shows up on an ordinary search), and you'd reach for **Google Maps** specifically if
     this client's customers are known to search from inside the Maps app (already driving, using
     in-car navigation).
   - **Data source** — **Local Dominator** is the suite's own default (it deliberately replaced
     DataForSEO for this job); leave it selected unless a lead specifically tells you this client
     needs the DataForSEO path instead — there's no documented cost or accuracy difference to weigh
     yourself.
   - **Schedule** — **Weekly** is what an active retainer client wants: it's what feeds the alerts,
     the Local Rank Analysis report, and the client PDF report (§12) automatically. **Manual only**
     turns that off — reach for it only when you deliberately don't want ongoing tracking (a one-time
     audit, a client not paying for Maps work).
   - **Save setup**.
2. Same tab, separate **Keywords** card → one per line → **Add**.
3. Go to **Heatmap** (or **One-offs**, for scanning just a subset of keywords) → **Run scan now**.
4. A completed scan gives you a per-keyword heatmap, an at-a-glance stat panel (average rank,
   top-3/top-10 coverage, strongest/weakest directions, top competitor), and an auto-generated
   **Local Rank Analysis** report — a ranked list of nearby weak-coverage areas with suggested
   hyper-local page targets, downloadable and regeneratable.

**Gotcha:** if Weekly scheduling is on but the client has zero *active* keywords, the scheduled
scan silently skips that client — the Setup tab shows an explicit warning if this is the case.

---

## Step 10 — AI Visibility

**Where:** Client workspace → **Rank Trackers** → **AI Visibility** card (`/clients/:id/ai-visibility`).

Measures whether the client shows up when someone asks ChatGPT, Claude, Gemini, Perplexity, or
Google's AI Overviews about their keywords — a newer kind of "ranking."

1. **Keywords** tab — type + **Add**, or click **Suggest AI queries**, or (fastest, if you already
   did §8) **Import from rank tracker** to pull in what's already being tracked.
2. **Competitors** tab — type a competitor name + **Add**. They ride along on the same AI answers
   the brand is checked against, at no extra cost.
3. **Overview** tab → **Run scan** → pick which engines to check + whether to include competitors.
4. **Schedule** tab — Off / Weekly / Monthly, a day + hour, **Save schedule**.

**Which engines, and why leave them all checked:** each one genuinely pulls from a different
source, not just a different logo — ChatGPT and Claude each run their own web search, Gemini uses
Google's own search grounding, Perplexity uses its own Sonar search, and Google AI Overview / AI
Mode read Google's AI-answer block directly. The tool's own default is to run **all six, every
time** — unlike tools where each engine costs a separate credit, there's no cost reason to narrow
it here, so leave everything checked unless you're deliberately isolating one engine to debug why
it looks wrong.

**Include competitors** is genuinely free — it rides the same scan calls. Leave it on; the only
reason it'd show "none tracked yet" is that you haven't added any on the Competitors tab.

No dependency on GSC or GBP — this tool is fully independent.

---

## Step 11 — Goals

**Where:** Client workspace → **Rank Trackers** → **Campaign Goals** card (`/clients/:id/goals`).

Set these *after* §8–10 — most goal types measure something those trackers produce, so they mean
nothing until there's data behind them.

Click **Add goal**, pick a **Goal type**. The tool has no built-in rule for which type to reach
for — the column below is this tutorial's own guidance on matching a type to what the client
actually cares about, not something the app enforces:

| Type | Needs | Reach for it when… |
|---|---|---|
| Keyword to position | a tracked keyword (§8) + target position | the client is fixated on one specific term — their business name, their #1 service — and wants one trackable promise. |
| Keywords in top N | a target count + the top-N position bar | the client cares about overall breadth ("most of what we track should be on page 1"), not any single keyword. |
| Organic clicks / 30 days | a target click count (needs GSC, §5) | the client cares about traffic itself more than where any one keyword sits. |
| Organic impressions / 30 days | a target impression count (needs GSC) | it's early in the campaign — impressions move first as new pages get indexed, before rank or clicks catch up. |
| AI visibility % | a target percentage (needs §10) | the client is worried about being invisible to ChatGPT/Gemini-style answers, not just Google's blue links. |
| Local-pack presence % | a target percentage (needs §9) | the client's business genuinely lives or dies by the local 3-pack (most home-service or storefront clients). |
| Custom (manual) | free text — nothing auto-measures this one | the real goal doesn't fit any of the above — SerMaStr can still read it, but nothing here checks it automatically. |

Optional Label / Due date / Notes, then **Create goal**. Status (Achieved / On track / Behind /
Overdue / No data / Manual) is computed live every time anyone looks at it — it's never a stored,
stale number.

---

## Step 12 — Reporting

**Where:** Client workspace → **Reporting** → **Client Reports** card (`/clients/:id/reports`).

### Generate one right now

**Report type** (Monthly SEO / AI Visibility) → **Period** (30/60/90/120 days, 1 year, or since
campaign start) → optionally check **"Email & save to Drive when done"** → **Generate report** →
once it's marked complete, **Download**.

### Set up the standing schedule

The **Delivery & schedule** card above the report list:

- **Recipients** — comma-separated emails.
- **Schedule** — Off / Weekly / Monthly, with a day and an hour (UTC). No rule in the tool for
  which cadence to pick — Monthly matches how most clients expect a report; Weekly suits one who
  wants to see week-by-week movement (or one you're actively walking through a recovery).
- **Report covers** — the period each scheduled report should span. Leaving this on **Auto**
  matches it to whatever cadence you just picked (weekly → last 7 days, monthly → last 30) — the
  point is nothing gets double-reported or skipped between deliveries. Only override it with a
  fixed period (say, "Last 90 days") if you deliberately want each report to look further back
  than its own delivery interval.
- Channel toggles: **Email** (needs SMTP configured agency-wide — check with your lead if this
  isn't firing), **Drive copy** (needs §7a's Drive folder to actually be set), plus two opt-in
  extras on the same clock: **AI Visibility report** and **Local Rank (Maps) report** — these only
  fire for a client actually tracking the matching keywords, so it's safe to leave both on.

A section with no connected data behind it (no GA4, say) just doesn't populate in the PDF — it
never breaks the rest of the report.

---

## Step 13 — Project Management Board (monthly tasks)

Four related but distinct pages, easy to conflate — read this whole step before touching any of
them.

### 13a. Task Library (global — you won't usually touch this per client)

`/asana/task-library`, sidebar item **Task Library**. The master catalog: every standard task
name, with a default hours estimate, category, client-facing blurb, and a default checklist.
Admin-maintained; per-client templates (next) just inherit from it by name.

### 13b. Monthly Template — *defines* the recurring list, per client

Client workspace → **Project Management** → **Monthly Template** card (`/clients/:id/asana-tasks`).

- Optional **Asana project** field, if the agency still runs Asana alongside the native board —
  check with your lead which system is authoritative today.
- **Auto-assign team** — toggle which team members are eligible to receive tasks marked
  **🔀 Auto-distribute**.
- The **Monthly task template** table itself: **Add task** → per row, a task name (autocompletes
  against the Task Library), an assignee (a named person, Unassigned, or Auto-distribute), a
  category, an hours estimate (inherits the library default if left blank), and an Active
  checkbox → **Save template**. Two of these fields do real work downstream, not just labeling:
  - **Est. hrs** directly decides who an **Auto-distribute** task actually goes to — each month it's
    handed to whoever on the auto-assign list has the most spare capacity that month (capacity is
    set on the **Workload** page). The same number also rolls up, once the task exists, into that
    person's total on Team Workload — it's what the "overloaded" warning is watching. A row you
    leave blank still counts as *something* toward someone's load (it falls back to a sitewide
    default), not zero — don't leave it blank assuming it's a freebie.
  - **Category** does double duty: it's the filter dropdown on the Tasks board itself, and (if this
    client is also mapped in Asana) it's the value written into that client's Asana project's own
    category custom field.
- **Generate this month** — creates this month's section and its tasks on the actual board
  (§13c) right now. Safe to click more than once; it won't duplicate what already exists.

### 13c. Tasks — the board itself, where work actually happens

Client workspace → **Project Management** → **Tasks** card (`/clients/:id/tasks`).

- Three views: **Board** (drag a card between status columns — dropping it in a "done" column
  completes it), **List** (grouped by month section), **Calendar**.
- **Generate this month** lives here too, as a shortcut to §13b's same action.
- Click any card to open its detail drawer — checklist, comments, attachments, activity log.
- This is the page **PACE** and **QA** actually operate on day to day (see the agent table below)
  — once you've generated a month, this is where your team lives.

### 13d. My Tasks — a personal, cross-client queue

Sidebar → **My Tasks** (`/my-tasks` — not client-scoped). Every team member's own open tasks
across *every* client, bucketed Overdue / Today / This week / Later / No date. Point new hires
here as their own daily home base, separate from any one client's board.

### 13e. Monthly Task Plan (Recipe Engine) — budget planning, not the board

Client workspace → **Rank Trackers** → **Monthly Task Plan** card (`/clients/:id/task-plan`).

> ⚠️ Do **not** confuse this with 13b/13c — it lives in a different workspace section on purpose.

Pick a **Margin** (66% target, or 50% for a drop month), type any **Special projects** cost, click
**Generate plan** — it reads the client's retainer (§1) and produces a costed, prioritized,
assigned table of work the budget can actually fund. **Push to Asana** turns it into real tasks.
Nothing here appears on the Tasks board (§13c) until you explicitly push it — this page only
*recommends*, it doesn't execute.

---

## A day, start to finish

A realistic single-day pass, in the order this document presents it. Steps marked *(background)*
are things you kick off and can leave running while you do the next step.

| Time | Do |
|---|---|
| 9:00 | §1 — Create the client. Save it. *(background: scrape + brand voice + ICP scans start)* |
| 9:20 | §4a — Confirm the agency-wide GBP connection is live (usually already is — 30 seconds). §4b — Register this client's location on both GBP Posts and GBP Insights. |
| 9:35 | §5 — Copy the GSC service-account email, send it to whoever has the client's Search Console access, ask them to add it. Don't wait — move on. |
| 9:40 | §6 — Same for GA4: copy the service-account email, send it along, move on. |
| 9:45 | §2 — Review the (by-now-scanned) Brand Voice card. Accept it or write your own. |
| 10:00 | §3 — Same for ICP & Differentiators. |
| 10:15 | §7 — Set up whichever of Drive / WordPress publishing this client actually needs. |
| 10:30 | Check back on §5/§6 — if the service account's been added, finish verifying + syncing/backfilling both. |
| 11:00 | §8 — Add tracked keywords, refresh live ranks. |
| 11:20 | §9 — Fill in the Maps Setup tab, add keywords, run the first geo-grid scan (takes a few minutes to complete). |
| 11:40 | §10 — Add AI Visibility keywords + competitors, run the first scan. |
| 12:00 | Lunch — let the Maps + AI Visibility scans finish. |
| 1:00 | §11 — Set Campaign Goals now that trackers have real data. |
| 1:20 | §12 — Generate a first report, set the standing schedule. |
| 1:45 | §13b — Build the Monthly Template. §13c — Generate this month, take a look at the board. |
| 2:15 | §13e — Run the Recipe Engine once, just to see what it recommends (push it to Asana only if your lead says to). |
| 2:30 | Done. The client is fully set up — hand it off or start working it. |

---

## Which agent touches what

Five things in this suite get called "an agent" — none of them are something *you* configure per
client in this tutorial; they simply start paying attention the moment a client and its data
exist. Worth knowing what each one is watching, though, since several of them will start talking
to you about this exact client within a day or two.

| Agent | What it actually does | Where you'll see it | What in this tutorial it touches |
|---|---|---|---|
| **SerMaStr** | The strategist. Chat-based, opinionated, cites your SOPs, reasons over everything the suite knows about a client. Runs a weekly review per client (or on demand), and can take confirm-gated actions. | Slack (dedicated channel or DM) and `/assistant`. | Reads Brand Voice/ICP (§2–3) when judging content quality; reads every tracker (§8–10) and Goals (§11) for its weekly review; can run and adjust the Monthly Task Plan (§13e) when asked. |
| **PACE** | Keeps the task board moving day to day — nudges stalled tasks, posts a daily digest, generates the month, chases follow-through. Confirm-gated for anything it does on your behalf. | Slack `#pace` (or the client's own channel if set in §1) and `/pace`. | Lives entirely inside §13 (Monthly Template, Tasks board, My Tasks). Doesn't touch anything before that. |
| **QA** | Judges a finished deliverable against a checklist before a client sees it (e.g., does a GBP post have the right keyword, does a page mention the client's actual business name) — deterministic checks, not vibes. | The task drawer's QA panel, and `/qa`. | Only fires on work moving through the Tasks board (§13c) — specifically when a task is moved into the **In QA** status. |
| **DORA** | The Director of Operations — a read-only lens across SerMaStr, PACE, and QA together. Flags gaps *between* them (an approved proposal nobody placed on the board, QA sitting idle, two agents targeting the same keyword) as its own weekly digest. It never acts on its own. | Slack `#dora` and `/director`. | Nothing to set up — it's watching the same data every other step in this tutorial produces, agency-wide. |
| **Autonomy executor** | An opt-in, per-client setting (off by default, pilot-only) that lets the system auto-execute certain low-risk proposals — e.g., commissioning a Local SEO page — inside a budget, instead of only proposing them. | No dedicated UI in this tutorial; ask a lead if a specific client should be opted in. | Not part of standard onboarding — mentioned here so the name doesn't surprise you later. |

---

## Quick reference — routes

| Tool | Route |
|---|---|
| New client | `/clients/new` |
| Client edit (Drive/WordPress/GitHub sections included) | `/clients/:id/edit` |
| Brand Voice | `/clients/:id/brand-voice` |
| ICP & Differentiators | `/clients/:id/icp` |
| GBP Posts (agency connect + this client's location) | `/clients/:id/gbp-posts` |
| GBP Insights (agency connect + this client's location) | `/clients/:id/gbp-metrics` |
| Organic Rank Tracker (GSC connect lives on its Settings tab) | `/clients/:id/rankings` |
| Maps Ranker (geo-grid) | `/clients/:id/maps` |
| AI Visibility | `/clients/:id/ai-visibility` |
| Campaign Goals | `/clients/:id/goals` |
| Client Reports (GA4 connect lives here too) | `/clients/:id/reports` |
| Monthly Template | `/clients/:id/asana-tasks` |
| Tasks (the board) | `/clients/:id/tasks` |
| My Tasks (personal, cross-client) | `/my-tasks` |
| Monthly Task Plan (Recipe Engine) | `/clients/:id/task-plan` |
| Task Library (global, admin-maintained) | `/asana/task-library` |

---

## FAQ / gotchas worth remembering

**"Publish to Google Docs" is failing.** Almost always §7a — no Drive Folder ID set on the client,
or the Apps Script account never got Editor access on that folder.

**GSC/GA4 verification keeps failing.** The service-account email almost certainly wasn't actually
added on the client's side yet — that's a step someone else has to take, not a bug.

**A rank-drop / Maps alert / task didn't happen when I expected.** Check that keywords are marked
**active** (§8/§9) and that scheduling is actually turned on, not just configured.

**Two GBP-related buttons on two different pages both say "Connect," am I doing this twice?** Yes,
on purpose — §4b explains why GBP Posts and GBP Insights each need their own per-client
registration even though they share one agency-wide login.

**Someone mentions "the Recipe Engine" and I don't see it on the Tasks board.** It's §13e, a
separate budget-planning page — its output doesn't appear on the actual board until someone clicks
**Push to Asana**.

**A field on the client form is greyed-out / labeled "Roadmap."** That's the app being honest that
the field is saved but not read by anything yet (Search Console Property on the Basic Info
section is the one you'll hit first). Don't spend time on it; the real version is elsewhere in
this tutorial.
