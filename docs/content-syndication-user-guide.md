# Content Syndication — User Guide

A step-by-step tutorial for the **Content Syndication** tool inside AR Tools. No code, no
terminal — everything here happens in the dashboard.

> **What this tool does.** It scans a client's site for existing content (blog posts, pages,
> products), lets you pick which pages to turn into unique rewritten versions, and publishes
> those as **public, search-discoverable Google Docs and/or Sheets** — each one linking back to
> the original page. The originals on the client's site are never touched; this creates *extra*
> indexable Google properties that point traffic back home.

---

## Before you start

- **Scanning never publishes anything by itself.** A scan only discovers new pages and lists them
  for you to review. Nothing goes out — not even on the very first scan — until you actually
  select pages and hit **Publish**.
- **Public Sheets need the Apps Script webhook redeployed.** If your agency's Google Docs webhook
  is on an old deployment, publishing to a Sheet will fail with a `sheet_not_supported` error.
  This is an admin/one-time infra fix, not something you can work around per-item — flag it if you
  see it.
- **A frozen client blocks publishing** here too, same as everywhere else.

---

## The big picture

1. Turn the tool **on** for a client and set your publish preferences.
2. Either wait for the **daily background scan** or click **Scan now**.
3. Review the discovered pages and **select** the ones worth syndicating.
4. Click **Publish** — each selected page gets rewritten into a unique version and published.
5. Track status, retry failures, export a CSV of what's live.

---

## Step 1 — Turn it on and set preferences

Open the client → **Content Syndication**.

- **"Auto-scan daily for new content"** — the on/off switch. The helper text under it shows the
  last scan date and reminds you: *"never publishes on its own."*
- **Content types to include** — checkboxes for **Blog posts**, **Pages**, **Products** (all on by
  default).
- **"Publish to:"** — choose **Google Docs + Sheets**, **Google Docs only**, or **Google Sheets
  only**.
- **"Sharing:"** — choose **"Anyone can find & view (discoverable)"** (fully public/indexable) or
  **"Anyone with the link can view"** (not publicly discoverable, but shareable).

Every setting saves immediately when you change it — there's no separate Save button.

---

## Step 2 — Scan for content

Click **Scan now** at any point (button shows **"Starting…"** briefly), or just let the daily
auto-scan handle it if it's enabled. A scan reads the client's sitemap (falling back to a live
search-index lookup if the sitemap isn't usable), sorts pages into blog post / page / product, and
adds anything genuinely new as a **discovered** item. A **"Scanning…"** indicator shows near the
page title while it works.

---

## Step 3 — Review and select pages

The items table shows each discovered page's title, type, and status, with filter tabs — **All**,
**Published**, **Not published**, **Failed** — each labeled with a count.

Tick the checkbox next to any page you want to syndicate (only pages that aren't already fully
published are selectable), or use **Select all** in the bulk bar. The bulk bar also shows a live
count of what you've selected and a reminder of where it's headed (e.g. "→ Google Doc + Sheet ·
public").

If nothing's shown yet: *"No pages discovered yet. Hit Scan now…"*

---

## Step 4 — Publish

Click **Publish N** in the bulk bar. Each selected page is rewritten into a genuinely unique
version (not a copy-paste) and then published as a Doc and/or Sheet per your settings — each with
a backlink to the original page on the client's site.

**Item status, as it moves through the process:**

| Status | Meaning |
|---|---|
| Not published | Discovered, not yet published |
| Publishing… | Being rewritten and pushed out right now |
| Published | Live — a green **Doc** and/or **Sheet** chip appears, linking to it |
| Failed | Something broke — hover the red badge to see why |

Re-selecting a page whose `publish_target` you've since widened (say, Docs-only to Docs+Sheets)
only fills the missing output — it won't duplicate what's already published.

---

## Step 5 — Fixing failures and keeping records

- Any row marked **Failed** gets its own **Retry** button — click it to requeue just that item.
- Once you have published items, an **"Export published CSV"** button appears — a spreadsheet of
  title, source URL, type, Doc URL, Sheet URL, and publish date, for handing off or archiving.

---

## Quick reference

| I want to… | Where |
|---|---|
| Turn syndication on for a client | The **"Auto-scan daily"** toggle |
| Choose Docs, Sheets, or both | **"Publish to:"** selector |
| Control public vs link-only sharing | **"Sharing:"** selector |
| Find new content right now | **Scan now** |
| See only what's not yet live | **"Not published"** filter tab |
| Publish selected pages | Tick checkboxes → **Publish N** |
| Fix a failed item | Its row's **Retry** button |
| Get a record of what's live | **Export published CSV** |

---

## FAQ

**I turned syndication on — will it publish my whole site right now?**
No. Turning it on only enables the daily *scan*. Nothing publishes until you personally select
pages and click Publish — every time, not just the first.

**A Sheet publish keeps failing.**
If the error mentions `sheet_not_supported`, the agency's Google Docs Apps Script webhook needs to
be redeployed with Sheets support — this is a one-time admin task, not something a retry fixes.
Flag it to an admin.

**Can I un-publish something?**
Not from this tool — it publishes a rewritten copy elsewhere; it doesn't manage the lifecycle of
that Doc/Sheet after the fact. Delete it directly in Google Drive if needed.

**Does this touch the original page on the client's site?**
Never. It only reads the page to produce a rewritten copy elsewhere. The live site is untouched.
