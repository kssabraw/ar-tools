# Local SEO Writer — User Guide

A step-by-step tutorial for generating, planning, and reoptimizing local landing/location pages
inside AR Tools. No code, no terminal — everything here happens in the dashboard.

> **What this module is for.** This is the tool for **service × location** pages — "emergency
> plumber Springfield," a city-specific service landing page, a neighborhood page. For products
> and collections, see `docs/ecommerce-writer-user-guide.md`. For general blog content, see
> `docs/blog-writer-user-guide.md`.

---

## Before you start

- **Brand Voice and ICP are shared with the rest of the suite.** Set both on the client's pages
  before generating anything real — they drive tone, word choice, and audience targeting here
  exactly as they do for the Blog Writer. No guide set → the suite auto-generates one from the
  client's site/GBP, which works but isn't as good as your own.
- **A Google Business Profile makes everything better, but isn't required.** Without one, pages
  still generate — you just lose the map-pack check, easy service-area-business detection, and
  some auto-fill. Attach one on the client's GBP settings whenever possible.
- **Reference page structures are optional but worth setting.** On the client form, you can point
  each page type (local landing / service / location / blog post) at a real example URL — or
  write your own guidelines by hand — so generated pages mirror how the client actually organizes
  a page.
- **A frozen client can't generate or reoptimize.** Same rule as everywhere else in the suite —
  check the freeze banner if something's blocked. Plan Silo's own *research* step still runs while
  frozen (it's analysis, not output); only actually creating the missing pages is blocked.

---

## The big picture

```
New Page  ·  Plan Silo  ·  Score  ·  Reoptimize  ·  Saved Pages  ·  Drafts  ·  Score History
```

- **New Page** — write one page for a service + area.
- **Plan Silo** — research a whole silo of pages around a seed service + area, then bulk-create
  the missing ones.
- **Score / Reoptimize** — check or rewrite a page that already exists (in the tool, or live on
  the client's site).
- **Saved Pages / Drafts** — everything you've generated, and everything you've soft-deleted.
- **Score History** — the trail of scores over time.

---

## Step 1 — Write a single page (New Page tab)

1. **Service** — e.g. `emergency plumber`.
2. **Area / Location** — start typing and **pick a suggestion from the autocomplete**. A
   free-typed location that doesn't match a real suggestion will be rejected — this keeps the
   page's geo-targeting accurate.
3. *(Optional)* Expand **Advanced options** for: mirroring an existing page's structure by URL
   (and saving that as the client's default), forcing a fresh competitor-data scrape instead of
   the 14-day cache, and which entity-extraction engine to use.
4. For a service-area business with no fixed address, a **city** field appears — it feeds the
   optional **"Check map pack"** rankability check (below), not page generation itself.
5. Click **Create new page**.

**The precheck.** Before anything generates, the tool automatically checks whether a page for this
service + area might already exist — in your saved pages, live on the client's site, or already
ranking in search. If it finds candidates, you'll see each one tagged (**Ranking #N** / **Generated
in tool** / **On live site**, plus a **Blog post** flag if it looks like an article rather than a
landing page) with a **Reoptimize this page** button per match. If none of them are actually the
right page, there's an explicit **Write a new page anyway** option at the bottom — this precheck
never silently blocks you, it just makes sure you're not about to duplicate something that already
exists.

**Check map pack** — an optional button on the New Page form (uses the SAB city field above when
present) that runs a quick Maps rankability check before you commit to generating the page — worth
using when you're not sure this service + area is realistically winnable in the local pack.

**While it generates**, you'll see a progress screen (fetching top search results → scraping and
analyzing competitor pages → generating and scoring your page). This takes **10–12 minutes**.
Click **Leave & finish in the background** and go do something else — the finished page lands in
**Saved Pages** on its own, and you can come back and check on other clients in the meantime.

---

## Step 2 — Plan a whole silo of pages at once (Plan Silo tab)

Instead of one page at a time, describe a **seed service + area** and let the tool discover every
page a business like this should have.

1. Enter **Seed service** + **Area / Location**.
2. Click **Plan silo**. This takes **4–6 minutes** — it researches the topic, discovers related
   service silos, expands and clusters real search demand into candidate pages, and checks each
   candidate against what the client already has.
3. Read the summary: **N exist** (already generated in the tool), **N on site** (a generic
   location page for that place is already live — you don't need to make one), **N missing**
   (the actual opportunities).

If the client has no website on file, everything shows as "missing" — there's nothing to check
against.

**Bulk-create the missing pages**: tick the ones you want (or **Select all missing**), then click
**Create N selected page(s)**. Each one runs the same full generation as a single New Page — 10–12
minutes each, competitor SERP analysis included — but as **background jobs**, so you can leave and
watch a live counter (**"3 / 8 done"**) when you come back. Failures are called out separately so
you can re-select just those and retry.

---

## Step 3 — Score and reoptimize an existing page

Three ways to reach this:

- **Score tab** — check a page's composite score and per-engine breakdown, and its brand-voice
  scorecard, without rewriting anything. Good for a quick "is this actually a problem" check
  before committing to a reoptimize pass.
- **Reoptimize tab** — paste one or more live URLs (always a multi-line box — one URL per line
  handles a single page too; a bulk line can be `URL | keyword | area` to pin the keyword/area for
  that specific page). Each page is scored first; a page gets rewritten when it's below **75/100
  on SEO, or fails its brand-voice bar** — a page that clears both is skipped with a note, so
  you're not spending effort on pages that don't need it.
- **Related Pages** (inside a saved page's detail view) — the same silo-discovery machinery, scoped
  to that one page's own service + location, so you can quickly spot and generate its close
  relatives.

Destinations for a reoptimize pass: **Save in the app** (always happens) and optionally **publish
to Google Doc**. GitHub and WordPress destinations exist for this tool but are marked **"Coming
soon"** — not live yet for reoptimize. (Unlike Blog/Ecommerce reoptimize, there's no notes field
here at all — you can't steer a specific rewrite beyond what the scorer's own deficiencies drive.)

Results show **Reoptimized** with a **before → after** score, or **Skipped** with the reason. You
can leave and let a bulk reoptimize batch finish in the background, same as generation.

---

## Step 4 — Saved Pages and Drafts

- **Saved Pages** lists everything generated or reoptimized, with a composite score, a
  Generated/Reoptimized badge, and bulk-publish controls across Google Docs / WordPress / GitHub.
- Deleting a page here doesn't destroy it — it moves to **Drafts** (a soft delete). From Drafts you
  can **Restore** it back to Saved Pages, or **permanently delete** it. **Empty drafts** clears the
  whole bin at once (with a confirmation) if you want a clean slate.

---

## Step 5 — Publishing

Publish buttons live on a page's detail view:

- **Publish to Google Doc** — the client's Drive folder. Re-publishing updates the same doc.
- **Publish to WordPress** — pick **Draft** or **Publish** first.
- GitHub publish is available from the **bulk publisher** on Saved Pages (not as a single-page
  button on the detail view).

A generated page's detail view also has a **GBP Posts** tab (AI-suggested posts plus the full
composer) alongside **Related Pages** — worth a look if you're already there and want to turn the
new page into a Google Business Profile post.

**If publish is blocked** with a brand-guide message, the page used a forbidden word from the
client's voice card. Check the **brand voice panel** on the page (see below) for specifics, fix the
wording, or click **Publish anyway** to override deliberately. Regulated clients have a separate,
non-overridable compliance gate for dosing/claims language.

---

## Reading the brand voice panel

Every generated page (for a client with a brand guide on file) carries a **brand voice card**
right on its preview, plus a separate **"How to reach 100/100"** panel listing any remaining
content gaps that would raise the SEO score.

The voice card shows:

- A headline verdict — **"Sounds like this client,"** **"Mostly on voice — minor drift worth a
  read,"** **"Drifting from the guide. Review before publishing,"** or **"This does not sound
  like the client. Automatic rewrites could not fix it"** — plus a 0–100 score.
- Any **Must fix** issues (a forbidden word, wrong grammatical person) versus **review** issues
  (missing preferred phrasing, off-guide CTA wording).
- Eight scored dimensions, worst first. A dimension scoring below 80 shows a real quoted excerpt
  from the page proving where it drifted; a passing dimension shows no quote.

**If a client has no brand guide, this panel doesn't appear at all** — that's deliberate, so a
missing panel never gets mistaken for "checked and passed." If the client *does* have a guide but
the page genuinely couldn't be scored against it, you'll instead see a **"Brand voice not
checked"** warning card — different from "no guide," and worth a re-score rather than assuming
it's clean.

---

## Quick reference

| I want to… | Where |
|---|---|
| Write one page for a service + city | **New Page** |
| Check I'm not duplicating an existing page | Automatic — the precheck screen before generation |
| Research and bulk-create a whole silo | **Plan Silo** → **Create N selected page(s)** |
| Fix a live page that's underperforming | **Reoptimize** → paste URL(s) |
| Find close relatives of a page I already made | That page's **Related Pages** sub-tab |
| See everything I've generated | **Saved Pages** |
| Recover something I deleted | **Drafts** → **Restore** |
| Wipe the recycle bin | **Drafts** → **Empty drafts** |
| Ship a page | **Publish to Google Doc / WordPress** (bulk includes GitHub) |
| Get past a brand-guide block on purpose | **Publish anyway** |
| Check why a page doesn't sound like the client | The **brand voice** panel on the page |

---

## FAQ

**The precheck found a page but it's not actually the right one.**
Use **"Write a new page anyway"** at the bottom of that screen — the precheck is there to prevent
accidental duplicates, not to force a match.

**A city I typed for Area / Location got rejected.**
You have to pick from the autocomplete suggestions — a free-typed location that doesn't resolve to
a real place isn't accepted, since the geo-targeting has to be accurate.

**Plan Silo said everything is "missing," even pages I know exist.**
Check whether the client has a website URL on file — without one, there's nothing to check
existing pages against, so every candidate defaults to "missing."

**Reoptimize skipped a page I wanted rewritten.**
It only rewrites a page that fails its SEO threshold (75/100) **or** its brand-voice bar — a page
clearing both is skipped on purpose. There's no notes field to force a rewrite regardless of
score on this tool (unlike Blog/Ecommerce reoptimize); if the page genuinely needs a manual pass,
use New Page's "Write a new page anyway" instead.

**Why can't I publish reoptimized pages to GitHub or WordPress?**
Those destinations aren't live for the Reoptimize flow yet — "Coming soon." Use Google Doc for now,
or publish via the bulk publisher on Saved Pages (which does support GitHub).

**I don't see a brand voice panel on a page.**
The client has no brand guide on file — set one on the client's Brand Voice page, and it will
appear the next time that page is generated or reoptimized.
