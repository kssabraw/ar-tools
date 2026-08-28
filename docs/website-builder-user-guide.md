# Website Builder — User Guide

A step-by-step tutorial for building a client's website inside AR Tools. No code, no
terminal — everything here happens in the dashboard.

> **What "publish" means here.** In this module, *publishing a page commits it into the
> site's own private GitHub repository*. The repo builds and deploys itself. Nothing you
> do puts something on the public internet by hand — you fill a repo, and the repo is the
> site. Keep that in mind whenever you read "publish" below.

---

## Before you start

- **The module has to be switched on.** If you open a client and there's no **Website
  Builder** card, an admin needs to enable it. Ask in the team channel — it's a one-time
  toggle, not something you can turn on yourself.
- **Roles.** Creating, provisioning, planning, generating, and publishing are **staff/admin**
  actions. If a button is greyed out, hover it — it tells you exactly why (wrong role, or the
  client is frozen).
- **Frozen clients.** If a client is under a Freeze (manual action / deindexing), all content
  output is paused, including everything in this module. Buttons disable with that reason
  until the freeze lifts. That's expected, not a bug.

---

## The big picture

A site moves through these stages, left to right along the tab bar:

```
Create → Provision (Overview) → Theme → Plan → Pages → Schedule → Deploys → Settings
```

You don't have to do them all in one sitting — each stage is saved, and you can come back.
A rough order that always works:

1. **Create** the site (records intent, nothing more).
2. **Provision** it (mints the real GitHub repo — the deliberate second step).
3. Optionally upload a **Theme** (a site with none just uses the neutral house theme).
4. **Plan** the pages: services + cities for a local site, and/or the blog content plan.
5. **Approve** the plan.
6. **Generate** and **Publish** pages — either by hand on the Pages tab, or on a drip
   **Schedule**.
7. Watch **Deploys** go green.
8. Keep business facts correct on **Settings**.

---

## Step 1 — Create the site

Open the client → **Website Builder** card → **Create site**.

- **Site name** — e.g. "Acme Roofing".
- **Site type** — pick one:
  - **Local business** — service pages, city pages, and the service × city matrix. **Also has
    a blog** (see Step 4b).
  - **Informational** — a content property. Its whole inventory *is* the blog content plan.
  - **Lead generation** — agency-owned. No business schema, no NAP, no trust badges.

Creating a site records the intent and nothing else. It does **not** create a repository yet.

---

## Step 2 — Provision (Overview tab)

Provisioning is the deliberate second step that mints the real infrastructure — a private
GitHub repo from the house template and a Cloudflare project.

On the **Overview** tab, click **Provision**. It runs as a series of steps; the page refreshes
itself while it works. If a step errors, the button becomes **Resume** — click it again and it
picks up where it left off. Once done, you'll see the repo and a staging URL.

---

## Step 3 — Theme (optional, but do it early)

A site provisioned without a theme just builds in the neutral **house theme**, which is fine to
start. To match a client's design:

1. Go to the **Theme** tab → **Upload a design** (a `.dc.html` file from Claude Design, or a zip).
2. The compiler *measures* the design (its real colours, fonts, spacing, layout) and turns it
   into a theme. It will refuse anything it can't actually see in the file — so a colour that
   isn't in the design can't sneak in.
3. Review the compiled theme and click **Approve**. Use **Recompile** if you re-upload a
   revised design.

Do this before you look at the Plan — it's the first thing done to a new site.

---

## Step 4 — Plan the pages (Plan tab)

This is where you decide the site's page inventory. A local/lead-gen site has **two halves** that
compose: the **geo half** (services × cities) and the **blog half** (content plan). An
informational site has only the blog half.

### 4a — Geo pages (local business / lead gen only)

- **Service catalog** — the billable jobs, in the client's own words (never GBP categories).
  Each service gets its own page; ticking **In matrix** also gives it a service × city page for
  every city.
- **Cities** — one location page each, plus a service × city page per matrix service. Add
  neighborhoods if they pass the Maps entity test.
- **Service variations** (optional, under each top-level service) — auto-generate extra pages
  at `/{service}/{modifier}/`. See below.
- Click **Build plan** (or **Rebuild plan** after edits). The proposed service/city/matrix pages
  appear in the **Proposed pages** table below.

#### Service variations — one service, many pages

Under each **top-level** service there's a small **"Service variations"** editor. It bulk-creates a
page per modifier of that service, so you don't add each as its own catalog row. Each variation is
a **label** plus a **kind**:

- **Type** — a narrower version of the service. The label *is* the page. Great for things a trade
  splits by: tree species, materials, property types. Example: on "Tree Removal", add Type
  variations **Oak Trees**, **Maple Trees**, **Palm Trees** → `/tree-removal/oak-trees/`,
  `/tree-removal/maple-trees/`, … Each is written as a **sub-service** page, titled by the label
  ("Oak Trees" — not "Oak Trees Tree Removal").
- **Brand** — an equipment manufacturer you service. Example: on "AC Repair", add Brand variations
  **Carrier**, **Trane**, **Lennox** → `/ac-repair/carrier/` ("Carrier AC Repair"), etc. Written as
  **brand × service** pages, with the brand in front of the service.

Notes:
- Only **top-level** services take variations (sub-services don't — that depth is reserved).
- A service can mix Type and Brand variations.
- A very large variation set (over ~200 pages) pauses on a **link-equity sign-off** at approval —
  tick to acknowledge, same as a big service × city matrix.
- Variation pages are written by the same nlp writer as your service pages (brand voice + scoring).

### 4b — The blog (all site types) — "Blog content plan"

Scroll down on the same Plan tab to the **Blog content plan** editor. This is what fills a site's
blog — **including a local site's `/blog/`, alongside its service pages.** It's empty by default,
which is exactly why a brand-new local site shows only service/city/matrix pages in Proposed
pages: the blog only appears once you put topics here.

- **Silos (pillars)** — a topic group (e.g. "Roof Maintenance"). Add posts under each.
- **Each post** — a title, a **format**, and an optional target keyword. Formats:
  - **Cluster post (evergreen)** — the default, a standard informational post.
  - **Listicle / roundup**
  - **Comparison / "vs"**
  - **Local geo** — for local sites.
  - **News (non-evergreen)** — timely; **does not** count toward the hub trigger below.
- **Hubs** — when a silo has **5 or more evergreen posts**, it automatically earns a top-level
  **hub page** that links down to its posts. (News posts don't count toward the five.)
- Click **Save content plan**. The plan rebuilds and the blog posts (and any hub) now appear in
  **Proposed pages** next to your geo pages.

**Don't want to type them all in?** Use the two one-click **seed** buttons at the top of the
editor:

- **Seed from strategist** — imports the client's latest Topic-Strategist plan.
- **Seed from Fanout** — paste a finished **Topic Fanout session id** (from that session's URL) and
  it imports the session's silos and clusters. It always regenerates the posts fresh — it does not
  reuse the Fanout's already-written articles.

Both seeds ask you to confirm before replacing an existing plan. After seeding, the plan is the
**site's own data** — edit it freely; a later re-research won't clobber your edits.

### 4c — Approve the plan

Review the **Proposed pages** table. Two kinds of warning can appear:

- **Blocks approval (red)** — either a *planning error* (fix the catalog; a wrong URL is
  permanent once published) or a *scale gate* that needs a named sign-off (tick the checkbox to
  acknowledge it).
- **Advisory (amber)** — informational, doesn't block.

Clear or sign off every red item, then click **Approve plan**. Generation and scheduling are
locked until the plan is approved.

---

## Step 5 — Generate & publish (Pages tab)

With the plan approved, the **Pages** tab lists every planned page.

- **Generate (N)** — writes the page content. Blog posts and pages run through the suite's normal
  writers, so they get brand voice, ICP, and quality scoring like any other content.
- **Publish (N)** — commits the generated pages into the repo (this is the "publish = commit"
  step). A deploy kicks off automatically.
- Both run one background job per page, so you can **leave the tab** and the work keeps going; the
  progress bar reconnects when you return.
- **Publish anyway** appears only if a page is held by the brand-voice publish gate (a forbidden
  word). It's a deliberate override — one extra click, staff/admin only.

You don't have to publish everything at once — which leads to the Schedule tab.

---

## Step 6 — Release schedule (drip-publish) — Schedule tab

Instead of publishing the whole site in one go, you can **drip it out** on a cadence — the same
way the other content tools stagger their output.

On the **Schedule** tab (held until the plan is approved and the site is provisioned):

- **Publish immediately** — how many pages go out the moment you save (0 = wait for the first
  cadence slot).
- **Release each time** — how many pages are generated **and** published per tick.
- **Cadence** — **daily**, **weekly** (pick a weekday), or **monthly** (pick a day of the month).
- **Schedule enabled** — the on/off switch.

Each release **generates then publishes** the next planned pages just-in-time — nothing is
generated up front. It covers **every** content page, so a local site drips out both its
service/location pages **and** its blog posts, in a sensible order (foundation pages first, then
the matrix, then the long tail; a post never goes out before its hub).

The panel shows **pages left to release** and the **next/last run**, and updates while the schedule
is live. **Stop schedule** halts new releases — pages already released stay put.

---

## Step 7 — Deploys tab

Every publish (and theme/settings change) triggers a deploy. The **Deploys** tab shows each one:

- **queued / building** — in flight.
- **success** — live.
- **failed** — something broke; open it for the error.
- **superseded** (purple) / **unknown** (amber) — *not* failures. A superseded run's content
  shipped in the run that replaced it (a batch publish cancels earlier in-flight runs on purpose),
  and an unknown one is almost certainly serving fine.

---

## Step 8 — Settings tab (keep the facts right)

The **Settings** tab holds the site's business facts — name, address, phone, hours, service area,
etc. (the NAP). These auto-fill from the client's Google Business Profile where possible.

- Anything you type here is stamped as **your** value and **wins** — a later GBP re-scan can only
  fill in gaps you left blank, never overwrite what you entered.
- **Clearing a field** hands it back to GBP (it will re-fill from the profile).
- **Saving redeploys the live site**, because these facts render into the contact page and schema.

---

## Quick reference

| I want to… | Where |
|---|---|
| Start a new site | Website Builder card → **Create site** |
| Mint the real repo | **Overview** → Provision |
| Match the client's design | **Theme** → Upload a design → Approve |
| Add service / city pages | **Plan** → Service catalog + Cities → Build plan |
| Bulk-create service variations (species, materials, brands) | **Plan** → a top-level service → **Service variations** (Type or Brand) |
| Add blog posts (any site type) | **Plan** → **Blog content plan** → add silos/posts → Save |
| Pull blog topics from research | **Plan** → Blog content plan → **Seed from strategist / Fanout** |
| Let the plan go live | **Plan** → Approve plan |
| Write & commit pages now | **Pages** → Generate → Publish |
| Drip pages out over time | **Schedule** → set cadence → Start schedule |
| See what's live / building | **Deploys** |
| Fix the address / phone / hours | **Settings** |

---

## FAQ

**My local site's plan only shows service, city, and matrix pages — where are the blog posts?**
The blog is driven by the **Blog content plan** on the Plan tab, which starts empty. Add silos and
posts there (or use a seed button), click **Save content plan**, and the posts appear in Proposed
pages. Blog posts are an editorial choice, so they aren't invented from your service list.

**I don't see the "Blog content plan" card.**
Hard-refresh the page (Cmd/Ctrl-Shift-R). The dashboard caches the module's on/off status for a few
minutes. If it's still missing after a refresh, tell the team — the module may not be enabled.

**Does "publish" put the site on the internet?**
It commits the page into the site's GitHub repo, which then builds and deploys itself. So yes, the
site ends up live — but through the repo, not by a manual upload.

**A page won't publish — it says something about voice.**
The brand-voice gate found a forbidden word. Either fix the wording (regenerate) or, if you're sure,
use **Publish anyway** (staff/admin).

**Can I change a page's URL after it's published?**
Avoid it. A published slug is immutable — changing it costs a permanent redirect rather than an
edit. Get the plan right before you approve it.
