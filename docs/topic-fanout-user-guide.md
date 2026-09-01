# Topic Fanout (Mass Posts) — User Guide

A step-by-step tutorial for the **Topic Fanout** tool inside AR Tools — the "Mass Posts" content
scheduler. No code, no terminal — everything here happens in the dashboard.

> **What this tool is for.** Generating a large, planned batch of content — dozens to thousands
> of blog posts (and Local SEO pages) — from one seed keyword, on a schedule, instead of writing
> one article at a time. For a single article, use the Blog Writer directly
> (`docs/blog-writer-user-guide.md`); for one-off local pages, use the Local SEO Writer
> (`docs/local-seo-writer-user-guide.md`). This tool is where you plan and schedule *volume*.

---

## Before you start

- **This is a separate app inside the dashboard** — it opens in its own tab/page (`/fanout`),
  distinct from the rest of AR Tools' navigation, but it shares the same login and client context.
- **What you see depends on your role, and it's not a choice you make.** The tool automatically
  gives an **Owner** (staff/admin) the full power-user surface described below, and a **VA**
  (team_member) a deliberately narrower **wizard** flow — no Articles tab, no free-form re-gating,
  a capped deep-mine, and a cost-approval step before anything spends real money. Every step below
  is marked **[Owner only]** where the two flows genuinely differ.
- **Local SEO page scheduling needs a client with a Google Business Profile.** Blog-post scheduling
  needs a **site base URL** — a client link is optional there, only used for auto-publish/WordPress.
  Service-page scheduling needs a client link but no location.
- **Nothing generates until you schedule it.** Discovering keywords and planning articles doesn't
  write anything — that only happens once you set up a release schedule (Step 5).
- **A run can hit an error mid-pipeline** (a deploy, a transient failure) — see the recovery note
  in Step 6 before assuming lost work.

---

## The big picture

```
New session → Discover silos → Run the keyword pipeline → Plan articles → Schedule → Articles generate
```

1. **Start a session** with a seed keyword (or a service, for local content) and review the topic
   silos it proposes.
2. **Run the keyword pipeline** — expands, filters, and clusters real search demand per silo.
3. **Plan articles** — turns the keyword clusters into an actual list of planned articles.
4. **Schedule** — decide the cadence (all at once, drip daily/weekly/monthly, or a specific date).
5. Watch content come out in **Articles**, and export data along the way.

---

## Step 1 — Start a new session

From the client workspace, click **Create Mass Posts**. Choose a content type up front:

- **Blog content** — standard articles.
- **Local SEO content** — location-targeted pages with competitor analysis and scoring. Requires
  the session to be linked to a client with a Google Business Profile.

Fill in the seed form:

- **Seed keyword** (or **Service**, for Local SEO) — the topic everything expands from.
- **Location** (Local SEO only) — via the location autocomplete.
- **Search market / Country**.
- **Silos** — how many topic silos to discover (3–10, via slider).
- **Coverage mode** — **Standard (top 5)** or **Comprehensive (top 10)**.
- **"Fetch volume / CPC / KD"** checkbox — on by default; adds a small real cost per run for
  market data.

Click **Discover silos**. If your seed is ambiguous, you'll be asked to pick or clarify the
intended meaning first.

---

## Step 2 — Review the discovered silos

You'll land on a review screen showing each proposed silo — edit or remove any that don't fit,
and add a custom one if something's missing. Click **Continue** when it looks right.

**[Owner]** Next, choose **what this run actually covers** — two independent checkbox columns per
silo:

- **Run** — which silos get expanded/clustered/planned at all.
- **Deep-mine** — which of those *additionally* get competitor research (the seed silo is always
  mined).

**[VA]** The wizard's equivalent step is simpler and has no Run-scope control at all — **every**
silo always runs; you only pick which *additional* silos get deep-mined, capped at 2.

Click **Run keyword pipeline**.

---

## Step 3 — Watch the pipeline work

The pipeline runs in two phases, each showing a live progress readout:

**Expansion** (~6–10 minutes) — pulling keyword ideas/suggestions/People-Also-Ask per silo,
mining competitor ranked keywords, scoring relevance, clustering. When it finishes you'll see
**"Keyword pipeline complete"** with counts of active keywords, silos, and how much was filtered
out as off-topic/junk/non-English. You can expand any silo to see its actual keywords.

From there, click **Plan articles** to move into the second phase (~1–4 minutes) — fetching SERPs
for candidate primary keywords, planning the actual articles per silo (merging, splitting,
promoting, or dropping candidates), and deduplicating across silos. You land on **"Article plan
ready"** with stats on articles planned, coverage gaps flagged, and duplicates merged.

---

## Step 4 — Review and tighten the plan

Once results exist, the session workspace has tabs for **Table** (a sortable/filterable full
keyword list) and **Cluster** (article units grouped by topic). Editing power here depends on
role:

- **[Owner]** Cluster is fully editable — merge, split, edit, delete — plus, for Owner-only
  sessions, a separate **Split** tab for architecture-level restructuring.
- **[VA]** You can rename articles and move keywords between them; merge/split/delete are
  Owner-only.

A gap-triage row (accept/dismiss a flagged coverage gap) can still appear, but it's largely
historical now — gaps are auto-accepted into keyword-named placeholder articles by default, so
only older, still-pending gaps from before that change actually show a row to act on.

**Not happy with the pool? [Owner only]** Open the **"Tighten the keyword pool"** panel and click
**Re-gate** — it re-runs the relevance gate and clustering on the keywords you already have, **at
no new spend**, using tuning knobs:

| Knob | What it controls |
|---|---|
| Relevance threshold | How strict the topical match has to be |
| Cluster granularity | How finely keywords are grouped |
| Keywords per silo | A cap on pool size per silo |
| Edge threshold | How similar two keywords must be to cluster together |
| Silo margin | Lets a keyword stay active in more than one silo when it's a close call |

This **clears the current article plan** — you'll need to click **Plan articles** again
afterward.

---

## Step 5 — Schedule content

Click **Schedule** (on the whole plan, or a selected subset of clusters). In the modal:

- **Content type** — **Blog post**, **Local SEO page**, or **Service page** (each with its own
  requirements — Local SEO needs a target area, both need a client link).
- Client-linked sessions can turn on **auto-publish to Google Drive**, and (if WordPress is
  configured) **publish to WordPress** as draft or live.
- **When**: **All at once**, drip **N/day**, **N/week**, **N/month** (by date or by weekday), or
  **a specific date**.
- **Maximum** — a production ceiling (defaults to 1000; blank = no limit). When capped, pillar
  pages get priority **only if the site architecture has already been generated** — otherwise
  there's nothing to prioritize by, and a warning banner tells you it's taking the first N in plan
  order instead.

The live preview shows the count, how long it'll take, and an estimated cost. **Large batches may
require owner approval before they'll actually run** — the modal tells you if that's the case.
**[VA]** the wizard shows this as an explicit **cost step**, and a batch over the approval
threshold is submitted with a **"Submit for approval"** button rather than scheduling directly —
you'll see a waiting state until an Owner approves it.

Click **Schedule N articles/pages**.

---

## Step 6 — Track generated articles [Owner only]

**The Articles tab doesn't exist for a VA session at all** — this whole step is Owner-only.

The **Articles** tab lists everything generated so far, with word count, cost, and a **Score**
column once scored.

Per article: **Read** to view it, and — for client-linked sessions — **Score** and **Reoptimize**
buttons (same pattern as the Blog Writer's own score/reoptimize: score checks it against the
blog/AEO rubric, reoptimize scores then rewrites the weak points). There's also a shared
**"Reoptimize articles"** panel (same tool used everywhere else in the suite) if you'd rather work
from a bulk view.

Toolbar actions: **Download all (.zip)**, **Push all to GitHub**, **Save N to Drive**, publish
to WordPress (with a Draft/Live selector), and **"Publish settings"** (the GitHub repo/branch/path
and Drive-folder config this tab publishes to).

**If a run hits an error partway through**, and the keyword pool it already collected was saved,
you'll see a **"Re-gate to recover"** option instead of just "start over" — it reuses everything
already gathered at no new spend and lands you back at "ready to plan." If nothing usable was
saved, your only option is a fresh session. (This recovery option is also Owner-only — a VA
session that errors always shows "Start a new session," regardless of whether the pool was
saved.)

---

## Step 7 — Exports

The **Exports** tab has two things:

- **Keyword research report (PDF)** — a client-facing deliverable: executive summary, topic
  silos, demand data, top opportunities, the content plan, and a full keyword appendix. Runs in
  the background ("Generating… (you can leave)") and saves to the client's Drive folder if
  linked.
- **Export data** — raw CSV/zip downloads: a flat keyword list, topic-grouped export, site
  architecture, or an internal-linking edge list (the last two need the site architecture
  generated first).

---

## Quick reference

| I want to… | Where |
|---|---|
| Start mass-generating content for a client | Client workspace → **Create Mass Posts** |
| Discover topic silos from a seed | The **new session** form → **Discover silos** |
| Control which silos get competitor research [Owner] / cap how many [VA] | The **Run** / **Deep-mine** checkboxes [Owner] · a capped deep-mine list [VA, no Run control] |
| Turn keyword clusters into an article list | **Plan articles** |
| Fix a pool that's too broad/narrow, for free [Owner only] | **"Tighten the keyword pool"** panel → **Re-gate** |
| Put content out on a schedule instead of all at once | **Schedule** → pick a cadence |
| Check or fix a generated article [Owner only] | **Articles** tab → **Score** / **Reoptimize** |
| Recover from a run that errored mid-pipeline [Owner only] | **Re-gate to recover** on the errored session |
| Get a client-facing research deliverable | **Exports** → **Generate report** |
| Get raw data | **Exports** → **Download CSV** |

---

## FAQ

**How is this different from the Keyword Research tool?**
Keyword Research is for understanding what to target and writing one-off drafts. Topic Fanout is
for turning a whole silo of keywords into a scheduled, mass-generated batch of content — it does
its own silo discovery and keyword pipeline from a seed; there's no built-in handoff that hands a
Keyword Research run straight into a Fanout session. (Keyword Research's own "Send to Content
Scheduler" goes to a *different* native bulk-creation tool, not to Topic Fanout — see
`docs/keyword-research-user-guide.md`.)

**My run errored out — did I lose everything?**
Check the errored session's card — if the keyword pool was already saved, you'll get a "Re-gate to
recover" option that reuses it at no new cost. Only a run that died before any keywords were saved
has nothing to recover.

**I scheduled a batch and nothing happened.**
Check whether it needed owner approval first — a large or costly batch is held until approved
rather than running silently.

**Can I edit the article plan before scheduling?**
Yes, with role-dependent depth — an Owner can merge, split, edit, or delete planned articles in
the **Cluster** view; a VA can rename articles and move keywords between them, but restructuring
(merge/split/delete) is Owner-only.

**Does "Deep-mine" cost more?**
Yes — it runs real competitor research per silo, so only mark the silos you actually want that
depth on. The seed silo is always deep-mined regardless.
