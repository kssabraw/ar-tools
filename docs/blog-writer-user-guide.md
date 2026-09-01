# Blog Writer — User Guide

A step-by-step tutorial for generating, scoring, and publishing blog articles inside AR Tools.
No code, no terminal — everything here happens in the dashboard.

> **What this document is not.** This is not the engineering spec for the five-module pipeline
> (that's `docs/engineering-implementation-spec-v1_1.md` and the module PRDs under
> `docs/modules/`). This is the practical, "how do I actually use this" guide for a person who
> needs to produce and ship a blog post.

---

## Before you start

- **Brand Voice and ICP are shared across content tools.** Set both on the client's **Brand
  Voice** and **ICP** pages before writing anything real — every generator (Blog Writer, Local
  SEO, Ecommerce) reads the same client record. Your own typed text always wins over the
  auto-generated version; if you don't set one, the app generates one for you.
- **Five runs at a time, per the whole suite.** Only 5 generation jobs can be in flight
  simultaneously. If you hit the cap, wait a minute — it clears fast. Bulk jobs and
  "reoptimize existing article" runs deliberately skip this cap — they don't count against your
  5, they just process sequentially in the background, one at a time.
- **A frozen client can't generate or publish content.** Publish, Score, and Reoptimize all show a
  clear "This client is frozen" explanation when blocked. The **New Run** form itself is blunter —
  it just prints the raw `client_frozen` error as plain text — so the real tell to check first is
  the red freeze banner on the client's workspace page. Only an admin lifts a freeze.
- **Keyword and notes have length limits.** Keyword: 150 characters. Notes for the writer: 4,000
  characters.

---

## The big picture

Every article moves through **five pipeline modules**, in order:

```
Brief Generator → Search Intent Engine → Research & Citations → Content Writer → Sources Cited
```

(The Brief and Search Intent Engine actually run in parallel under the hood — you'll just see one
combined "running" state for both.)

A rough order that always works:

1. Open **Runs** for the client and click **New Run**.
2. Type a **keyword**, optionally pick a **format** and add **notes for the writer**.
3. Click **Start** and watch the **Pipeline Progress** card move through the five modules.
4. Review the finished **article**, its **QA checks**, and its **score**.
5. **Publish** it — to a Google Doc, WordPress, or GitHub.
6. Optionally **score/reoptimize** it later, or score/reoptimize a URL that isn't a suite run at
   all.

---

## Step 1 — Start a run

Open the client → **Runs** → **New Run**.

- **Client** — shown read-only; you're always creating a run for the client whose Runs page
  you're on.
- **Keyword** — required. e.g. `best hvac systems 2026`.
- **Format** — an optional override on top of the brief's own auto-classifier:
  - **Auto (detect from keyword)** — the default; let the pipeline decide.
  - **Standard blog post**
  - **Listicle (ranked / "Best X")**
  - **How-to guide**
  - **Comparison (X vs Y)**
  - **Buying guide (commercial)**
- **Notes for the writer (optional)** — freeform guidance for the Content Writer module only
  (e.g. "mention Zero Down Supply Chain Services as one of the top 10 best"). **This never enters
  the cached brief** — it's a per-run instruction, not a permanent change to how that keyword gets
  briefed in the future.
- Click **Start**.

**If a cached brief already exists** for that exact keyword, a dialog pops up letting you choose
whether to reuse the cached brief (faster, cheaper) or force a fresh one (if something's changed
since it was last researched — a new SERP landscape, a different angle).

---

## Step 2 — Watch it run

The **Pipeline Progress** card lists the five modules with live status — a spinner + elapsed time
while running, a checkmark + duration + cost once done, or a clock + typical time range while
waiting its turn:

| Module | What it's doing | Typical time |
|---|---|---|
| Brief Generator | Analyzing search intent and building the content outline | ~20–40s |
| Search Intent Engine | Fetching competitor SERP data and ranking signals | ~15–30s |
| Research & Citations | Gathering sources, scraping pages, extracting citations | ~30–60s |
| Content Writer | Drafting the full article with brand voice and SEO structure | ~2–5 min |
| Sources Cited | Embedding inline citations and assembling the references section | ~5–15s |

You don't have to babysit this page — it polls itself and reconnects if you navigate away and
come back. While it's running, a **Cancel** button lets you stop it (confirms first — "in-progress
modules will finish, but no further stages will run").

**If a step fails:** an amber box with "Auto-retry" text means it's automatically retrying, not
broken — leave it. A genuine failure shows "Failed at the \<stage\> stage" plus an expandable
**error accordion** ("What to do" / "Hide") — expand it for a plain-English explanation, numbered
fix steps, and (when there is one) a one-click fix button. From here you have three different
buttons, and they're not interchangeable:

- **Resume** — picks up from the last completed module, reusing everything already done. Use this
  first; it's the cheapest option.
- **Restart** (failed/cancelled runs) / **Rerun** (complete runs) — both spawn a **brand-new run**
  rather than continuing this one, and both default to regenerating the brief and SIE from
  scratch rather than reusing the cache (you still get the usual cache-decision dialog first).
  Reach for these when Resume isn't enough — something about the keyword's brief itself needs to
  change, not just the run.

---

## Step 3 — Review the finished article

Once the run completes you'll see:

- **QA Checks** — a green "All QA checks passed" line, or an amber list flagging things like a
  format mismatch, a writer note that wasn't honored, thin entity coverage, keyword-stuffing, or a
  low-confidence intent read. Worth a glance before publishing, especially on a client you haven't
  worked with before.
- **Title & H1** — the SEO/meta title and the on-page H1, each separately copyable (they're often
  intentionally different).
- **Generated Article** — the full piece, toggleable between Markdown and HTML, with **Copy**,
  **Download**, and a **Featured image** picker.
- **Term Usage by Zone** — a breakdown of which related keywords/entities/phrases actually landed
  in the title, H1, subheadings, and body — useful for spot-checking SEO coverage without
  re-reading the whole article.

---

## Step 4 — Publish

Three destinations, each its own button on the article card:

- **Publish to Google Docs** (the default) — drops it into the client's configured Drive folder.
  On success the button becomes **Open Doc**.
- **Publish to WP** — pick **Draft** or **Publish** from the dropdown first, then click. Draft
  saves to WordPress unpublished; Publish goes live immediately.
- **Publish to GitHub** — commits the markdown into the client's repo. If hero/body-image
  generation is configured for this client, it runs as a background job — the button shows
  "Generating images…" and a status line ("Queued — N job(s) ahead of this publish…" or
  "Generating hero + body images and committing to GitHub… you can leave this page…") — and
  you'll get a notification when it's live. If image generation isn't configured, it just commits
  the markdown synchronously with no images, no background job.

**A run has to be Complete before any publish button works.**

**If publish is blocked by the client's brand guide:** the article used a word from the client's
"never use" list. This is a hard, provable gate — a low voice *score* alone never blocks publish,
only a forbidden word does. Fix the wording and regenerate, or, if you're confident it's fine,
click **Publish anyway** — a deliberate one-extra-click override.

**Regulated clients** (anything touching dosing, branded-drug claims, or guaranteed-results
language) have a separate compliance gate that is **not** overridable from the UI — that one needs
an actual rewrite.

---

## Step 5 — Score and reoptimize an existing run

On any **complete** run, an **Article score** card sits below the article. Click **Score**
(becomes **Re-score** after the first pass) to check it against the blog/AEO rubric — Organic
Ranking, AEO/LLM Retrieval, Content Depth, Entity & Topic Coverage, E-E-A-T & Citations, ICP
Alignment, Structural AEO, SERP Signal Coverage.

Scoring surfaces per-engine deficiencies as checkboxes. Tick the ones you want fixed (or leave
none ticked to fix everything) and click **Reoptimize** — it rewrites the article against exactly
those issues, then re-scores automatically. This runs in the background too, so a page refresh or
a server update mid-rewrite won't lose your work.

Both the Score and Reoptimize panels also carry an **Entity engine** selector (TextRazor by
default, or Google NLP) — leave it on the default unless a lead tells you otherwise.

---

## Step 6 — Score or reoptimize a URL that isn't a suite run

Sometimes you want to check (or rewrite) a piece of content that didn't come from this pipeline —
an old post, something published years ago, or a competitor's article for comparison. On the
**Runs** page (not inside a specific run) there are two toggle buttons:

- **Score an article** — point at a live URL or paste content in directly, plus a **keyword**
  (required for both Score and Reoptimize — the rubric needs something to measure relevance
  against). Nothing gets rewritten — you just get the composite score, per-engine breakdown, and
  entity coverage/gaps.
- **Reoptimize an article** — same inputs, plus optional writer notes. Accepts either a single URL
  or a **pasted list of multiple URLs** to reoptimize as a batch. Unlike scoring, this **spawns a
  genuine new run** — full brief → research → writer pipeline — that you review and publish like
  any other run. (To rewrite an article that's *already* a suite run, use Step 5 instead —
  reoptimizing there is much cheaper since it reuses the cached brief/research.)

---

## Content Silos

As briefs get generated, the suite automatically groups related keywords into **content silos** —
topic clusters it noticed recurring across your briefs, without you tagging anything. Check the
**Silos** page (sidebar) periodically:

- A banner flags topics that have shown up across many briefs and are worth a real look.
- Each candidate row has icon buttons (hover for the tooltip) to **Approve**, **Reject**, or
  approve-and-immediately-dispatch a full run for it. The bulk toolbar has the same three actions
  as buttons: **"Approve & generate,"** **"Approve only,"** and **"Reject."**
- Silos tied to a specific run also show up right on that run's card under "Content Silos," with a
  link back to the full Silos page.

This is how the suite surfaces "you've been writing around this topic a lot — maybe formalize it"
without anyone manually tracking it.

---

## Quick reference

| I want to… | Where |
|---|---|
| Write a new post | Runs → **New Run** |
| Force a fresh brief instead of reusing a cached one | The cache-decision dialog on run creation |
| Steer the writer without changing the permanent brief | **Notes for the writer** field |
| See what stage a run is on | The **Pipeline Progress** card |
| Understand a failure | Expand the run's **error accordion** ("What to do") |
| Continue a failed/cancelled run without losing progress | **Resume** |
| Check quality before publishing | The **QA Checks** card |
| Ship it | **Publish to Google Docs / WP / GitHub** |
| Get past a brand-guide block (deliberately) | **Publish anyway** |
| Improve a run you already generated | **Score** → tick deficiencies → **Reoptimize** |
| Check or rewrite content that isn't a suite run | Runs page → **Score an article** / **Reoptimize an article** |
| See recurring topics across briefs | Sidebar → **Silos** |
| Turn a keyword-research idea straight into a draft | Keyword Research page → topic card → **Write this post** |

---

## FAQ

**My run is stuck on "Retrying."**
That's not a failure — it's an automatic retry on a transient upstream error. Leave it; it'll
either succeed or eventually surface a real failure with the error accordion.

**Can I edit the article after it's generated, before publishing?**
The generated content is what publishes as-is — use the **Notes for the writer** field on the next
run, or **Score → Reoptimize**, rather than hand-editing in the dashboard.

**Why did "Reoptimize" spawn a whole new run instead of editing this one?**
That only happens from the "Reoptimize an article" path on the Runs page, for content that isn't
already a suite run — there's no existing brief/research to reuse, so it has to build one from
scratch. Reoptimizing a run you already generated (Step 5) rewrites in place and is much cheaper.

**I hit the 5-run cap.** Wait a minute for something in flight to finish, then retry. If you're
running a big batch, it's normal for a smaller ad-hoc run to queue briefly behind it.

**A client's brand voice or ICP isn't showing up in the writing.**
Check the client's **Brand Voice** and **ICP** pages — if neither is set, the suite auto-generates
one from the client's site/GBP, which is a reasonable default but not the same as your own
guidance. Type your own to make it authoritative.
