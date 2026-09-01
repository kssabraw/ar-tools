# Keyword Research — User Guide

A step-by-step tutorial for using the standalone **Keyword Research** tool inside AR Tools. No
code, no terminal — everything here happens in the dashboard.

> **What this tool is not.** This is not the Mass-Posts content generator (that's **Topic
> Fanout**, see `docs/topic-fanout-user-guide.md`) and it doesn't write anything by itself. This
> tool answers one question — *"what should we target, and why"* — and hands you a clean,
> filtered keyword universe plus a ranked list of topic ideas. Turning an idea into an actual
> article happens one click away, in the Blog Writer — or, for a batch, AR Tools' own **Content
> Scheduler** (a separate bulk page-creation tool, distinct from Topic Fanout — see the FAQ).

---

## Before you start

- **Budget.** Every research run spends a small daily budget of paid keyword-data calls, shared
  across the agency. The page shows **"Budget left today: N calls"** at the top, in red when it
  hits zero — if you're blocked, wait for tomorrow or ask an admin.
- **Better seeds make a better run.** The tool researches *around* what you type — it can't read
  your mind about a business it knows nothing about. If a client's website, GBP category, and
  location aren't filled in on their Setup page, the "Suggest topics" and "Topic Research"
  features have much less to work with (see the FAQ).
- **This tool doesn't write content.** It researches and organizes keywords/topics. The one
  bridge to actual content is the **"Write this post"** button (Step 8), which queues a real
  Blog Writer run.

---

## The big picture

1. Type one or more **seed keywords** (or let the tool suggest some) and hit **Research
   keywords**.
2. Read the **results** — a filtered, clustered keyword table with volume/CPC/competition/intent.
3. Check **what got filtered and why**, so you trust what's left.
4. If the run came back thin, follow the tool's own advice — broader seeds, or switch to **Topic
   Research**.
5. Optionally run the deeper **Topic Research (BETA)** panel for buyer-problem-first topic ideas,
   grounded in the client's own site and ICP.
6. Turn any keyword or topic card into a real draft with **Write this post**, or hand the whole
   set to the **Content Scheduler**.
7. Export a **CSV** for your own use, or generate a **client-facing PDF report**.

---

## Step 1 — Research keywords

Open the client → **Keyword Research**.

- Type into the seed box — **one seed per line, or comma-separated** (e.g. `emergency plumber` /
  `blocked drain`). Multiple seeds are fully supported and researched together.
- Don't know where to start? Click **Suggest topics** — it reads the client's GBP category,
  location, website, and ICP and proposes seed terms as clickable chips. Click a chip to drop it
  into the seed box.
- Click **Research keywords** (button reads **Researching…** while the run works). This kicks off
  a background job — you don't have to sit and wait.

If you get *"No topic suggestions yet"*, the client's Setup page is missing the website, GBP
category, or business location — fill those in first.

---

## Step 2 — Read the results

Once a run completes you get:

- A **cluster rail** at the top — one chip per topic cluster (auto-grouped, no manual tagging),
  each labeled `{cluster name} (count)`. Click **All** or a specific cluster to filter the table
  below. A **"Questions only"** checkbox narrows the table to question-form keywords.
- A **keyword table** with columns: **Keyword**, **Cluster**, **Volume**, **CPC**, **Comp**
  (competition), **KD** (keyword difficulty), **Intent**, **Relevance** (how closely it matches
  this client's actual topic/audience, as a %), and **Opportunity** (a blended value×ease×intent
  score — the closest thing to "which of these is worth the most").
- **Run-history chips** above the results let you flip between past runs for this client without
  re-researching.

---

## Step 3 — Understand what got filtered (and why)

Keyword Research doesn't just dump raw data — it runs the pool through several relevance,
audience, and drift filters before you ever see it, and it **shows its work**. When anything was
dropped, a **"What we filtered & why"** panel appears: a one-line summary (*"N candidates found ·
N kept · N filtered out"*) plus reason chips such as:

- Unrelated brand or namespace
- Only matched a generic word in your seed
- Off your seed topic (category drift)
- Not topically relevant to the seeds or business
- Wrong audience (job-seeker / off-audience)
- Navigational / competitor lookup (not a topic)

Click **"Show the N filtered-out keywords"** (the count is baked into the button label) to see the
actual dropped terms next to their reason.
**If a lot of what got cut looks genuinely on-topic to you, that's a real signal** — broaden your
seeds or add another one, per Step 4.

---

## Step 4 — When a run comes back thin

Fewer than ~20 keywords triggers a **thin-result callout** that tells you *why*, in plain
language:

- **Nothing came back at all** — your seed is too narrow or unusual. Try dropping a qualifier
  (a brand name, a model number, "software"/"company"/"platform").
- **Plenty came back, but almost everything got filtered** — points you at the filter panel from
  Step 3.
- **A generic thin result** — just try a broader term or add a second seed.

Below the explanation, the tool auto-fetches **broader topic suggestions** as click-to-add chips
— same mechanism as "Suggest topics" in Step 1. There's also a **"Research topics instead"**
button, which jumps straight into **Topic Research (Step 7)** using this run's seeds — genuinely
useful when a seed is a narrow product/service term rather than a topic a buyer would search
around.

---

## Step 5 — Manage your seeds

- **Remove a seed** from an existing run using the **×** on its chip (only available when a run
  has more than 2 seeds — a run always keeps at least 2). This deletes only the keywords that
  seed alone produced; anything shared with another seed stays.
- **Add People Also Ask questions as seeds** — every PAA card question has a **"+ seed"** link,
  and there's a bulk **"Add all as seeds"** link above the list, if a whole batch of real
  questions looks worth chasing.
- **Clear all runs** for a client with the **Clear all** button — this is permanent (runs,
  keywords, and reports all go), so it asks you to confirm.

---

## Step 6 — Competitors and real questions in the SERP

When available, two cards sit above the keyword table:

- **Top competitors in these SERPs** — the domains actually showing up for your analyzed seeds,
  ranked by how often they appear, with a small marker if they're cited in Google's AI Overview.
  Your own client's domain is called out in green if it's already ranking there.
- **People Also Ask** — real questions Google surfaces for your seeds. These are already folded
  into the keyword table (marked as questions), but this card is the fast way to scan and promote
  them as seeds (Step 5).

---

## Step 7 — Topic Research (BETA) — go beyond keyword variations

The **Topic Research** panel is a different, deeper kind of research: instead of expanding *your
seed's wording*, it starts from the client's real **buyer problems** — reading their ICP and the
themes already on their own site — validates each idea against **real search demand** (People
Also Ask + suggestion volume), and mines what **competitors** are actually publishing on the same
themes.

- Click **Research topics** (or **Re-research topics** to refresh). This takes roughly 30 seconds
  and spends more of the daily budget than a plain keyword run — it's doing real analysis, not
  just an API pull.
- Read the **Strategy** callout first — a short assessment of what the client should prioritize.
- Below it, **topic cards** are grouped under **pillars** (broad content themes), each card
  showing: the buyer problem, search intent + funnel stage, supporting keywords with volume, real
  reader questions, a priority badge, and a rationale line.
- A card marked **"covered"** means the client likely already has content addressing it — check
  **"Show gaps only"** to hide those and focus on genuinely missing topics.

If a client has no ICP and no site content on file, this panel has very little to work from — set
those up first (see the FAQ).

---

## Step 8 — Turn an idea into a real draft: "Write this post"

Every topic card has a **"Write this post"** button. Click it and a modal opens:

- **Seed keyword** — pre-filled with the card's highest-volume supporting keyword (a dropdown if
  there's more than one option); editable.
- **Writer guidance** — a full angle brief is auto-composed for you: the working title, the buyer
  problem, intent/funnel stage, the reader questions to answer, and the related keywords to work
  in naturally. Edit any of it before submitting.
- Click **Create draft**. This queues a genuine **Blog Writer run** — the same pipeline as
  starting a run from the Runs page — pre-loaded with your angle as writer notes. You'll get a
  **"View the draft"** link straight to it, or find it in **Runs** shortly after.

**Want ideas without going through Topic Research?** A **"Generate blog topics"** panel sits right
above the keyword table — click it (or **Regenerate**) to turn the run's buyer-fit keywords + the
client's ICP into title/angle/target-keyword cards directly, no Topic Research pass needed.

There's also a batch path: select keywords in the table and use **Send to Content Scheduler** —
this queues them into AR Tools' own native **Content Scheduler** (bulk creation of blog/service/
location/Local SEO/ecommerce pages, on-demand or drip-scheduled). This is a **different tool from
Topic Fanout** — see the FAQ if you're unsure which one you want.

---

## Step 9 — Export and reporting

- **Export CSV** — exports whatever's currently filtered/visible in the table (keyword, cluster,
  volume, CPC, competition, difficulty, intent, question flag, relevance, opportunity).
- **Client PDF report** — generates a polished, client-facing PDF (exec summary, KPIs, topic
  clusters, top opportunities, the real questions customers are asking) and saves it to the
  client's Drive folder. This runs as a background job too — the button shows **"Building… (you
  can leave)"** and the PDF opens automatically once it's ready. Past reports for the current run
  show up as chips with **Download** / **Drive** links.

---

## Quick reference

| I want to… | Where |
|---|---|
| Start a run | Type seed(s) → **Research keywords** |
| Get seed ideas from the client's own profile | **Suggest topics** |
| See only questions | **Questions only** checkbox above the table |
| Understand what got cut | **What we filtered & why** panel |
| Fix a thin/empty run | Follow the callout's suggestion, or click **Research topics instead** |
| Drop a seed that's polluting the run | **×** on its seed chip (needs ≥3 seeds) |
| Promote a real customer question | **+ seed** on any PAA question, or **Add all as seeds** |
| Go deeper than keyword variations | **Topic Research (BETA)** panel → **Research topics** |
| Skip topics the client already covers | **Show gaps only** checkbox |
| Turn an idea into a draft | **Write this post** on any topic card |
| Get quick blog title/angle ideas without Topic Research | **"Generate blog topics"** panel above the table |
| Queue a batch of keywords into the native Content Scheduler | Select rows → **Send to Content Scheduler** |
| Get a client-facing deliverable | **Client PDF report** |
| Get raw data for your own spreadsheet | **Export CSV** |
| Start over for a client | **Clear all** (run-history row) |

---

## FAQ

**Suggest topics / Topic Research gave me nothing useful.**
Both are grounded in the client's Setup-page data (website, GBP category, business location, ICP)
and the client's own site content. If any of those are missing or thin, fill them in first — the
tool won't invent a business profile.

**My run came back with almost nothing.**
Read the thin-result callout — it tells you whether the seed itself was too narrow (try
broadening it) or whether the filters cut most of what came back (open "What we filtered & why"
and judge for yourself whether the cuts look right).

**A relevant-looking keyword got filtered out. Is that a bug?**
Maybe not — the filters are deliberately aggressive about wrong-audience terms (job-seeker
searches, navigational "phone number" lookups, unrelated brand names) because those pollute a
content plan more than they help. Check the reason it was given in the filter panel before
assuming it's wrong.

**Does "Write this post" publish anything?**
No — it queues a Blog Writer **run** (a draft, generated through the normal pipeline). Publishing
is a separate, later step in the Blog Writer itself.

**What's the difference between this, the Content Scheduler, and Topic Fanout / Mass Posts?**
Keyword Research is for finding and understanding what to target — it produces ideas and one-off
drafts (via **Write this post**). **Send to Content Scheduler** hands a selected batch to AR
Tools' own native bulk page-creation tool (blog/service/location/Local SEO/ecommerce), which is
**not** Topic Fanout — that's a separate, larger tool (its own silo-discovery pipeline, its own
scheduling) reached from the client workspace's **Create Mass Posts** card, not from anywhere in
this tool. There's no built-in handoff from Keyword Research straight into a Topic Fanout session.

**Can I research more than one seed at once?**
Yes — one per line or comma-separated. A run must always keep at least 2 seeds once you've added
a second one, so removing seeds down to a single one isn't allowed (start a fresh run instead).
