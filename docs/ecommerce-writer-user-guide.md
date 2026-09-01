# Ecommerce Writer — User Guide

A step-by-step tutorial for generating and reoptimizing product and collection pages inside AR
Tools. No code, no terminal — everything here happens in the dashboard.

> **What this module is for.** Product description pages (PDPs) and collection/category pages
> (PLPs) — national scope, no geo-targeting. For location-targeted service pages, see
> `docs/local-seo-writer-user-guide.md`. For blog content, see `docs/blog-writer-user-guide.md`.

---

## Before you start

- **Brand Voice and ICP** are the same client-level settings used everywhere else in the suite —
  set them once, they apply here too.
- **A house template makes product pages consistent.** If the client has an existing product page
  whose layout you like, point the tool at it (Step 1) and every new product page will mirror its
  section structure — adapting the copy to each product rather than reusing generic boilerplate.
  Collections don't use a house template.
- **Public specs get auto-researched — verify them anyway.** For genuinely public, invariant facts
  — identity and handling specs (CAS number, molecular formula/weight, solubility, standard
  reconstitution/storage) and receptor-pharmacology facts (binding targets, in-vitro EC50/Kd) —
  the writer researches and cites sources rather than leaving a gap. It deliberately does **not**
  research clinical efficacy, dosing/administration, therapeutic claims, or regulatory/FDA status —
  those stay gaps rather than invented facts, on purpose. Always double-check the cited source
  before publishing; it's flagged for exactly that reason.
- **A frozen client can't generate or reoptimize.**

---

## The big picture

```
New Page  ·  Score  ·  Reoptimize  ·  Saved Pages  ·  Drafts
```

Same shape as Local SEO's tabs: write, check, fix, keep track of what you've made and what you've
deleted.

---

## Step 1 — Write a new page

Open the client → **Ecommerce Writer** → **New Page**. Pick **Product** or **Collection** at the
top — this changes the form and the writing rubric underneath it.

Fields:
- **Target keyword** — e.g. `wireless noise-cancelling headphones`.
- **Source URL (optional)** — a live page to scrape for real product facts (specs, price,
  variants) so the writer isn't inventing details.
- **Product details (optional)** — a free-text box to paste specs, price, variants, materials,
  dimensions, key features directly, if you don't have (or don't trust) a source URL.
- **Notes (optional)** — freeform guidance for the writer, e.g. "remove the Research Use Only
  designation."

**House template (products only)** — a collapsible panel at the top of the form. If the client has
a saved default template, you'll see it noted; otherwise, paste a reference product page's URL and
click **Save** to set it as the client's default going forward (or leave it one-off — a per-call
override is available via the API, just not exposed in this form). The writer reproduces that
page's section structure, order, and blocks for every product page you generate after.

Click **Create product/collection page**. Generation takes **10–12 minutes** — click **Leave &
finish in the background** and it lands in **Saved Pages** when ready.

**Bulk-create**: click **"Bulk from a keyword list"** to switch modes — paste one keyword per
line, add a batch-wide notes field (applies to every page in the batch), and submit. Each keyword
becomes its own background job with a live done/failed counter.

---

## Step 2 — Review the auto-sourced facts

If the writer researched any public specs for you, a green **"Auto-sourced public specs —
verify"** panel appears on the generated page: each fact with its value, unit, and a source link.
**These are invariant, publicly-documented facts** (not vendor-specific claims like price or
review counts, which are never auto-researched) — but always click through and confirm the source
actually says what the page claims before shipping.

The same page also shows a **Search coverage** panel (entity/keyword/bolded-term coverage) and the
**brand voice** panel (see the Local SEO Writer guide for how to read it — it's the identical
component), plus a **"How to reach 100/100"** card listing any remaining content gaps — facts that
would raise the score but weren't verified — each tagged High/Medium/Low impact with a note on why
it matters and how to add it. The page itself has **Preview / HTML / JSON-LD Schema** view tabs,
plus a featured-image picker at the bottom.

---

## Step 3 — Score and reoptimize

Three entry points:

- **Score tab** — check a page's composite score and per-engine breakdown without rewriting
  anything. A freshly-generated page also has a one-click **"Score & Improve"** button that jumps
  straight in here with the page pre-filled.
- **Reoptimize tab** — a **"Page URLs — one per line"** box (there's no separate single-vs-bulk
  toggle; pasting just one URL works fine). Each line can optionally carry `URL | keyword | area`
  to pin the keyword/area for that page. To find URLs instead of typing them, switch the mode
  pills to **"Discover from site"** and click **Discover product pages / Discover collection
  pages** — it crawls the client's own sitemap and classifies what it finds by URL pattern.
- Both Score and Reoptimize carry an **Entity engine** selector (TextRazor by default, or Google
  NLP).

Same threshold behavior as Local SEO: pages score first, and a page gets rewritten when it's below
**75/100 on SEO, or fails its brand-voice bar** — a page clearing both is skipped with a note (add
your own notes to force a rewrite regardless — unlike Local SEO, Ecommerce reoptimize does have a
notes field). Under the hood it runs up to 3 rewrite-and-rescore passes, keeping the best result,
not just the last one.

Results show **Queued / Working… / Skipped / Failed / Reoptimized**, with a before → after score
on anything actually rewritten. There's a single **"Publish each reoptimized page to a Google Doc"**
checkbox if you want that to happen automatically as pages finish. Bulk runs support **Leave &
finish in the background**.

---

## Step 4 — Saved Pages and Drafts

Same soft-delete pattern as Local SEO: deleting a page from **Saved Pages** moves it to **Drafts**,
where you can **Restore** it or delete it permanently. **Empty drafts** clears everything at once.

Saved Pages rows show a composite score and a Generated/Reoptimized badge, with bulk-publish
controls.

---

## Step 5 — Publishing

From a page's detail view: **Publish to Google Doc** (the client's Drive folder) and **Publish to
WordPress** (Draft or Publish). **Re-publishing creates a new Doc/post each time** — it does not
update the previous one, so avoid clicking Publish repeatedly on the same page once it's live.

Blocked by a brand-guide violation? Same rule as everywhere else — a forbidden word is a hard,
provable block; fix the wording or click **Publish anyway** to override deliberately. The
**brand voice panel** on the page shows exactly what tripped it (identical to the Local SEO one —
see `docs/local-seo-writer-user-guide.md` for how to read it).

---

## What's not built yet

Worth knowing so you don't go looking for it:

- **Per-item pasted facts in bulk generate.** Bulk generation is keyword-only — the source URL /
  product-details paste box only exists on the single-page New form.
- **A Score History tab.** Local SEO has one; Ecommerce doesn't yet, even though the data exists
  behind the scenes.
- **GitHub or WordPress as Reoptimize destinations.** Only Google Doc auto-publish is wired into
  the Reoptimize flow; use the Saved Pages publish buttons for WordPress after the fact.

---

## Quick reference

| I want to… | Where |
|---|---|
| Write one product or collection page | **New Page** → pick Product/Collection |
| Make every product mirror a reference layout | **New Page** → House template panel |
| Ground the copy in real specs | **Source URL** or **Product details** paste box |
| Verify a researched spec before shipping | The **"Auto-sourced public specs — verify"** panel |
| Write many pages at once | **New Page** → **"Bulk from a keyword list"** |
| Check a page without rewriting it | **Score** |
| Fix an underperforming page | **Reoptimize** → paste URL, or **Discover** from the sitemap |
| Recover a deleted page | **Drafts** → **Restore** |
| Ship a page | **Publish to Google Doc / WordPress** |
| Get past a brand-guide block on purpose | **Publish anyway** |

---

## FAQ

**A product's specs look generic / invented.**
Give it a **Source URL** to scrape or paste real details into **Product details** — without either,
the writer has less to ground the copy in beyond public-spec research.

**Why didn't Reoptimize touch this page?**
It only rewrites a page that's under 75/100 on SEO **or** failing its brand-voice bar — a page
clearing both is skipped on purpose. Add a note before running it if you want it rewritten
regardless of score.

**Can I set a house template per-generation instead of a client default?**
Not from this form today — only the persistent client default is exposed in the UI. The
capability exists at the API level if you ever need it done manually.

**Where's the Score History tab?**
Not built for Ecommerce yet — it exists for Local SEO. Use the Score tab to check current state in
the meantime.
