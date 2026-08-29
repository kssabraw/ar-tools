# PACE & QA — User Guide

A companion to the [Task Manager User Guide](native-task-manager-user-guide.md).
That guide covers the board itself — sections, statuses, checklists, views.
This one covers the two agents that sit on top of it: **PACE**, which keeps
delivery moving, and **QA**, which checks finished work before it reaches a
client. Read the board guide first if you haven't — this one assumes you
already know what a task, a section, and a status are.

> **Third agent, not covered here.** A third agent, **SerMaStr**, decides *what
> work should exist* — strategy, priorities, campaign health. PACE and QA both
> defer to it on those questions. This guide is only about PACE (moving work)
> and QA (judging work).

---

## Terms you'll see

| Term | What it means here |
|---|---|
| **PACE** | The delivery agent. Watches every board, nudges people, proposes fixes, and can act on your behalf when you ask (or when you confirm one of its own proposals). |
| **QA** | The quality agent. When a task's deliverable is finished, QA checks it against a fixed checklist and passes it, bounces it, or flags it for a human. |
| **Verdict** | QA's outcome for one review: **Passed**, **Failed**, **Needs a human**, or **Not QA-checked**. |
| **Rubric** | Which checklist QA grades a task against (GBP Posts, Citations, Website Pages Posted, …) — picked from the task's name, or set explicitly. |
| **Deliverable** | The actual thing QA is checking — a live page, a GBP post's copy, a citation listing, a guest post. |
| **Digest** | PACE's once-a-day read-only summary of what's overdue, stuck, or unassigned across every board. |
| **Chase Plan** | PACE's once-a-day *proposal* — a numbered list of fixes it wants to make, that you approve with a reply. |
| **Episode** | The clock PACE keeps on one flagged problem (one task, one issue) from when it's first noticed until it's fixed. |
| **Confirm-gated** | An action PACE (or QA) won't run until a person replies to approve it — nothing writes to the board without that reply. |
| **Actor-bound** | Only the person who asked for a confirm-gated action (or an admin) can approve it — someone else replying "yes" in the same thread doesn't count. |

---

## Before you start

- **Two separate places to talk to PACE:** the dedicated **`#pace`** Slack
  channel, and the **PACE** page in the dashboard sidebar (`/pace`). Both run
  the same brain and can do the same things.
- **QA mostly runs itself, inside the task drawer.** There's also a dedicated
  **QA** chat (sidebar, `/qa`) for asking questions or QA-ing a page on
  demand — it's live for the whole team.
- **Everything either agent writes to the board is confirm-gated**, except a
  few pure reads (a digest, a report, "what should I work on today"). PACE
  never reassigns, nudges, or changes a due date without a "yes" from a
  person; QA's automatic reviews are the one exception — those run and post
  their result the moment a task reaches **In QA**, because reviewing isn't a
  board write anyone needs to approve in advance.
- **All of it is live today.** PACE (including its daily Chase Plan), QA's
  automatic reviewer, and the `/qa` chat are all switched on for the whole
  team.

---

# Part 1 — PACE

## What PACE actually does for you

Think of PACE as the PM who's read every board before you have. Day to day,
that's three things:

1. It tells you (and the team) what's falling behind, once a day, without
   being asked.
2. It proposes fixes for those problems, once a day, and does them the moment
   you say yes.
3. It answers questions and takes one-off requests whenever you ask, in
   plain English, in `#pace` or on the `/pace` page.

It does **not** decide what work should exist — that's SerMaStr. It does
**not** judge whether finished work is good — that's QA. PACE's whole job is
*keeping things moving*.

## Where to find it

- **`#pace` in Slack.** PACE has its own bot identity here (not the SerMaStr
  bot). Inside this channel, PACE jumps into a **new** question only when
  you `@`-mention it — but if it's already asked you to confirm something
  (a Chase Plan, a single staged action), your reply doesn't need a mention;
  it's obviously talking to you back.
- **The `/pace` page** (sidebar → **PACE**). Same brain, web chat instead of
  Slack — answers every message you send it, no `@`-mention needed. Good for
  a longer back-and-forth, or when you'd rather not clutter the channel.
- **DMs.** If PACE nudges you directly (see below), that's a real Slack DM —
  you can reply to it like any other message.

You don't need to name a client to talk to PACE. Say a client's name and it
scopes to that board; say a person's name ("what does Ivy have overdue?") and
it scopes to that person across every client they work on; say neither and
it reads the whole agency.

## The daily digest

Once each workday, PACE posts a **read-only** summary — no confirm, nothing
to approve — of what needs a human's attention across every board: tasks
stuck past their normal time in a status, overdue tasks, and tasks a producer
created (a rank-drop alert, a completed content run, …) that nobody has
touched yet. It's silent on a genuinely clean day.

A real one from this account:

> **PACE daily · 74 items need a human**
> • *First Class Roofing* — "Map Embeds" blocked 48d (Ivy Gervacio) → `@PACE unblock Map Embeds on First Class Roofing`
> • *EML Calibration* — "4x DAS" in_progress 48d (Minda) → `@PACE unblock 4x DAS on EML Calibration`
> • *ZDSCS* — "Press Release" in_progress 48d (Kyle Sabraw) → `@PACE unblock Press Release on ZDSCS`
> … +66 more

Each line already gives you the exact thing to say back to PACE if you want
it handled right there.

## The daily Chase Plan (PACE's own proposals)

Once a day, PACE also posts a **numbered list of fixes it wants to make** —
nudges, auto-placements for unassigned work, due-date suggestions — built
from the same problems the digest reports. Nothing in it runs until you
reply.

> *PACE chase plan — 3 proposed actions* (reply *yes* for all, or `yes 1,3` to pick)
> 1. Nudge Minda — "Citations Audit" overdue — remind Minda — _Henson Architect_
> 2. Nudge Minda — "Cloud Stack" overdue — remind Minda — _Parallel Accounting_
> 3. Nudge Kyle Sabraw — "Press Release" overdue — remind Kyle Sabraw — _ZDSCS_

- Reply **`yes`** to run every item, or **`yes 1,3`** (or `yes 1-3`, `approve 2`)
  to run only some. Anything you don't select is dropped for today — if it's
  still a real problem tomorrow, it reappears in tomorrow's plan.
- **Whoever confirms authorizes it.** A junior teammate can approve a nudge
  (open to any team member); a reassignment needs a *staff* role or higher —
  if you're not authorized for one of the selected items, PACE tells you
  which one and why instead of silently skipping it.
- An unconfirmed plan is never run late — it's simply replaced by the next
  day's plan.
- **A flag line means PACE couldn't safely stage something on its own.** The
  most common one you'll see is an ambiguous task name — several tasks on the
  same client share a name (e.g. three separate "GBP Blast" tasks across
  different months), and PACE won't guess which one you mean. It lists them
  and waits for you to be specific instead.

## Follow-through: PACE doesn't forget

Every problem PACE flags gets a clock, not just a one-time mention:

- While a problem is open, PACE proposes a fix for it in **every** day's
  Chase Plan — so an unaddressed nudge keeps coming back, it doesn't quietly
  drop off after one try.
- If **3 business days** pass with genuinely no movement on it (no status
  change, no comment, no reassignment — anything counts as movement, even
  something unrelated to the fix PACE proposed), PACE posts **one public
  escalation**, naming the task, the assignee, the client, and how long it's
  been stuck. It never escalates the same problem twice.

A real escalation from this account:

> **PACE escalation — 2 items stuck ≥3 business days with nobody acting**
> • "Review & publish: what is a public adjuster" (BSA Claims) — Ryan Maizis, stale with no movement for 3 business days
> • "Review & publish: What does a third party claims administrator do?" (BSA Claims) — Ivy Gervacio, stale with no movement for 3 business days

The lesson here isn't "you got called out" — it's a nudge that a task has
been genuinely idle. Touching it (even just leaving a comment) resets the
clock.

## Nudges & DMs

You can ask PACE to nudge someone ("nudge Ivy about the roof-repair GBP
post"), or it'll propose a nudge itself in the Chase Plan or as part of
following through on an episode. Either way, once confirmed:

1. PACE tries a **direct Slack DM** to that person first.
2. If they're not linked to Slack, or DMs aren't working, it **@-mentions**
   them in the channel instead.
3. If neither is possible, it still writes an **in-app notification** to
   their bell — nothing about a nudge is ever silently lost.

## Per-person morning briefs

Each linked team member can also get their own overdue/today/this-week list
pushed to them as a Slack DM every workday morning — the same content as
asking PACE "what should I work on today?", just delivered without asking.
Unlinked members are skipped and named in a summary ("3 unreachable — link
them on the Team page") rather than silently missed — a real one from this
account: *"Morning briefs — 1 member briefed, 3 unreachable."* If you're not
getting yours, ask an admin to link your Slack account on the Team page.

## What you can ask PACE to do

Anything you'd ask a PM. A few real examples:

- **Status questions** — "what's overdue for Acme?", "what does Ivy have on
  her plate?", "are we behind pace this month?", "why is the GBP post
  stuck?" (PACE will pull the task's full history — subtasks, comments,
  activity — before answering that last one).
- **"What should I work on today?"** — answers from *your own* linked queue,
  no client needed.
- **One-off actions** — reassign a task, set or bump a due date, move a task
  forward *or back* through the workflow (including reopening something
  completed), unblock a task, nudge someone, fill in a task's missing
  due date/category/estimate ("triage"), generate this month's tasks for a
  client, kick off a QA review, or write this week's client-update email.
  Every one of these is confirm-gated: PACE stages exactly what it's about
  to do and names it in plain language before it happens.
- **Batches** — "nudge all of Ivy's overdue tasks", "bump every overdue due
  date on Acme by a week", "reassign the unassigned ones to Marcus" — PACE
  resolves the whole matching set from the board data (it can't hallucinate a
  task into the batch) and stages it as **one** confirm covering all of them.

## Who can ask PACE to do what

PACE reuses the same four roles the rest of the suite does: **client <
team_member < staff < admin**. If you're below the floor for something, PACE
tells you the role it needs rather than pretending it can't find the action.

| Action | Minimum role |
|---|---|
| Read any board / ask "what's overdue" | team_member |
| Move or set a due date on **your own** task | team_member |
| Nudge **yourself** about a task | team_member |
| Run a QA review on a task | team_member |
| Nudge **someone else** | staff |
| Reassign a task, or auto-assign an unassigned one | staff |
| Move or set a due date on **someone else's** task | staff |
| Unblock a task | staff |
| Fill in a task's missing due date/category/estimate | staff |
| Generate a delivery report | staff |
| Write the weekly client-update email | staff |
| Generate this month's tasks **by asking PACE** | admin |

That last row is a real gotcha: clicking **Generate this month** on the
Tasks page itself is open to anyone (per the board guide), but *asking PACE
to do it in chat* currently requires admin — the two paths aren't gated the
same way. If PACE tells you it needs an admin for that, use the button on
the board instead if you're not one.

An unlinked Slack account (no `profiles.slack_user_id` on file) can still
read the digest, but every write is refused until an admin links you on the
Team page.

## What PACE leaves on the task's Activity log

This is worth knowing so you're not confused later: **PACE doesn't leave its
own signature.** When it reassigns, unblocks, or moves a task, the activity
entry is the exact same kind you'd see from a manual edit — "changed the
assignee," "changed the status," "changed a date" — and it's attributed to
whoever typed **yes** to confirm it, not to "PACE" as a distinct actor. If you
see a task's status flip and don't remember doing it, it was probably a
Chase Plan or nudge you (or a teammate) confirmed earlier that day — check
the Slack thread, not the task, for the "why."

QA's entries are the one exception: a completed review always leaves its own
clearly labeled **"QA reviewed the deliverable"** row, described below.

---

# Part 2 — QA

## What QA actually does

QA is the gate between "a VA marked it done" and "it goes to the client."
When a task reaches **In QA**, QA finds the thing that was actually produced
— a page, a GBP post's text, a batch of citations, a guest post — runs a
fixed checklist for that *kind* of deliverable, and settles on one of four
outcomes. It's deliberately mechanical: **the pass/fail decision is always
computed in code**, never guessed by an LLM. An AI model is only used to
*phrase* the explanation, plus two narrow judgment calls (does a map-embed
page contain a real "we provide this service" sentence, and does a rendered
screenshot look visually broken) — and neither of those can flip a verdict
the deterministic checks already decided.

## How a review gets triggered

1. **Automatically**, the moment a task's status becomes **In QA** — including
   the board's own auto-advance when you check off the last checklist item
   (see the board guide's callout on this). This is the normal path: finish
   the work, and QA runs unprompted.
2. **The "For QA" button** in the task drawer header — moves the task to In
   QA and reviews it right away, for when you want a check before the
   checklist is technically finished.
3. **The "Run QA" button** inside the QA panel itself (see below) — reviews
   the task in place without changing its status.
4. **Ask PACE** — "run QA on the roof-repair GBP post for Acme" (or ask QA
   directly, below). Confirm-gated like any PACE action.

A task that just **passed** won't be re-reviewed automatically if it's
dragged out of In QA and back within 30 minutes — that flap guard only
applies to a clean pass; a bounced task re-entering In QA (the normal rework
loop) always re-runs.

## The QA panel (in the task drawer)

Every top-level task has a **QA** section in its drawer, below the
checklist:

- A **readiness banner** — plain English on whether QA can even run yet, and
  exactly what's missing if not ("Before QA can run, add: the page URL to
  review"). The Run QA button is disabled until readiness clears, so you
  never fire a review that's guaranteed to come back "needs a human."
- A **Rubric** dropdown, in case the task's name doesn't clearly say what
  kind of deliverable it is — pick one explicitly rather than renaming the
  task.
- For a website page, a **Page type** dropdown (service / local landing /
  location) — picks which of the client's stored reference-page layouts the
  design-fit check compares against.
- **Page URL to review** and **Target keyword** fields — the guided way to
  give QA what it needs, instead of relying on task-naming conventions (see
  below).
- The **Run QA** button, the latest verdict, a per-check breakdown, the
  URL(s) it actually opened, and a collapsible history of every past review.

## Reading a verdict

| Verdict | What it means | What happens to the task |
|---|---|---|
| ✅ **Passed** | Every blocking check cleared. | Stays in In QA — someone still moves it on to Sent to Client by hand (unless your team has configured pass to auto-advance). |
| ❌ **Failed** | At least one blocking check came back false. | Bounces to **In Progress**, and QA adds a **"Rework: …"** checklist item for each failed check, naming exactly what to fix. |
| ⚠️ **Needs a human** | A blocking check couldn't be verified at all — a blocked page, a missing link, an unknown keyword. | Stays exactly where it was. QA never guesses; a person has to look. |
| ⏭️ **Not QA-checked** | This deliverable type is out of QA's scope entirely (see below). | Stays where it was; nothing else happens. |

**Fail-open is the whole safety model.** Anything QA can't verify — a site
that blocked the fetch, a missing deliverable link, no keyword on the task,
an unreachable screenshot — reads as **Needs a human**, never as an
automatic fail. QA would rather ask a person than wrongly bounce good work.

### The self-closing rework loop

A failed review's "Rework: …" items are real checklist items, not just
notes — which means checking them all off **automatically moves the task
back to In QA**, exactly like finishing the checklist normally does, and QA
re-reviews it on its own. Fix → check the box → re-review → pass, with
nobody having to remember to re-run anything.

A real fail from this account, on a blog post:

> ❌ **Failed** — QA_Checklists §Blog Post (Title + body)
> - ✓ Key Takeaways section present
> - ✗ **CTA present**
> - ✓ No duplicate headings
> - (advisory) 0 external link(s)
>
> *"The deliverable fails because two blocking checks are unmet: no CTA is
> present (must point to the correct page), and no external citations are
> present (advisory, but the 0-link result indicates missing authority
> support). Rework the article to add a clear call-to-action linking to a
> relevant service page and incorporate at least one external link..."*

That task got two new checklist items — `Rework: A CTA is present` — wait,
in practice it's rendered as `Rework: <the failed check's label>` — and once
checked off, the article went back into the QA queue on its own.

### What to actually do about "Needs a human"

This is the most common outcome until the team's conventions below are
second nature, so here's the quick troubleshooting list:

| The panel says… | Usually means | Fix |
|---|---|---|
| "the page URL to review" is missing | No link on the task | Fill in the **Page URL to review** field, or add a `Deliverable links` subtask |
| "the target keyword" is missing | Keyword check couldn't run | Fill in **Target keyword**, or make sure it's in the task name (see below) |
| "could not verify" on a keyword check | Same as above | Same fix |
| "deliverable link can't be graded automatically" | You linked a **Google Doc/Slides/Forms draft**, not the live page | Link the actual live placement instead |
| "page unreachable/blocked" | The site timed out or bot-blocked the fetch | Open it yourself and confirm it's actually live; re-run QA |
| "screenshot unavailable" | The visual-render check couldn't capture the page | The rest of the review still stands — check manually if you're worried about the layout |
| Sheet read comes back empty | The Google Sheet isn't shared "anyone with the link," or has no obvious URL column | Fix sharing, or add a `Live URL` / `Citation URL` header column |

## The rubrics — every checklist QA can run

QA figures out which checklist applies by matching the task's (or its
library template's) name, case-insensitively, first match wins. A task
generated by **content_run** (a Blog Writer run) is always graded as a blog
article regardless of its name. If nothing matches, it's flagged **generic**
— QA never invents a standard for a task type it doesn't recognize.

### GBP Posts
*Blocking, all three, bounce if any fail:*
- Target keyword present in the body.
- A CTA is present (an imperative phrase like "call," "get a quote," or a
  `tel:` link).
- At least one emoji.

The post's copy is read from the task's `Deliverable links` subtask
description, then the task description, then — if the post was actually
published through the suite's GBP Posts tool — the real copy that went live,
with no paste needed at all.

### Citations
*Blocking:* the business's **name, address, and phone (NAP)** match the
client card, sampled from **3** citations pulled off the linked Google
Sheet (first / a middle one / last — the same three every re-run, so a
repeat review checks the same rows). A page that can't be fetched reads
"could not verify," never a fail.

### Guest Posts / Niche Edits
*Blocking, one check:* the placement's body content contains a **link back
to the client's own website**.

### Press Release
*Blocking, bounce if any of these four fail:*
- Target keyword in the **title**.
- Target keyword somewhere in the **body**.
- At least one link whose anchor text is **not** an exact match of the
  keyword (guards against over-optimized anchor text).
- **NAP included** on the page.

### Map Embeds
*Blocking, bounce if any missing:*
- A **grammatically correct, plain-English sentence** stating that the
  client provides the service (e.g. "Amazing Rankings provides SEO services
  in Sydney") — not structured data, a real sentence. This one's judged by a
  small AI model, the only place in QA where that happens.
- **NAP included.**
- A **Google Maps embed** actually present on the page.

### Website Pages Posted
The deepest rubric — it checks everything the automated SEO scorer can't
see. Blocking unless marked advisory:
- Meta title present.
- Target keyword in the **title tag**, the **URL slug**, and the **H1**.
- An **internal link** to the client's own site.
- **Images have alt text.**
- The client's **business name** actually appears on the page.
- *(advisory)* Meta description present.
- **Design fit — layout**: the page's section structure and heading order
  compared against the client's stored reference page for that page type.
  Below the fidelity floor it reads "could not verify," never a fail — and
  if the client has no reference page on file at all, this check reports
  itself as unavailable (advisory) instead of a meaningless score.
- **Design fit — visual, two layers**: every stylesheet and image on the
  page is checked for a hard 404 (a dead stylesheet is blocking — it breaks
  the whole render; a dead image is advisory), and, when nothing free
  already vouches for a clean render, a rendered screenshot is judged by a
  small AI model for obvious visual breakage. Only a high-confidence broken
  render fails; anything uncertain is "needs a human," never an auto-bounce.

If the page is one the suite itself generated (a Local SEO page, an
ecommerce page, a Website Builder page), its live URL is found automatically
— nothing to paste — and the page's own SEO quality score rides along in the
review as a bonus reference number.

### Blog Post (Title + body)
Reads the finished article text straight from the content run. Blocking
unless marked advisory:
- A **Key Takeaways** section present.
- A **CTA** present.
- **No duplicate headings.**
- *(advisory)* Paragraphs within the length cap; at least one external
  citation; the target keyword present.

### Not QA-checked / handed off
A few task types are deliberately **not** graded by QA at all:
- **GBP Blast**, **HyperLocal GBP Blast**, **Blog Post Scheduling** — owner
  ruling: not a deliverable QA checks.
- **Service Silo** — hands off to SerMaStr instead. Judging whether a silo
  plan picked the right services and groupings is a strategy call, not a
  presence check, so QA marks it out of scope rather than pretending to
  grade it.
- Anything QA doesn't recognize at all reads **"needs a human"** (the
  **generic** rubric) rather than being silently skipped.

## The "Deliverable links" convention

QA can only check a deliverable it can find. For anything living on a
third-party site (a guest post, a niche edit, a press release, a citation, a
map embed), give it a **`Deliverable links`** subtask before moving the
task to In QA:

| Deliverable | Where to put the link |
|---|---|
| Guest post / niche edit | The URL, in the subtask itself |
| Citations / press release | A **Google Sheet** link, shared "anyone with the link → Viewer," ideally with a `Live URL` / `Citation URL` header column |
| Map embeds | A **.txt file** attached to the task, listing the placement URL(s) |
| A website page you posted yourself | The **Page URL to review** field in the QA panel is the cleanest way — no subtask needed |

Never paste a **Google Doc/Slides/Forms** link as the deliverable — that's a
draft container, not a live placement, and its rendered HTML would false-fail
the checks; link the live page instead.

**The target keyword** normally just needs to be part of the task's name —
QA reads it as the name minus the standard template name (`GBP Posts —
emergency roof repair`, or a task fully renamed to just the keyword). A bare
template name with nothing added yields "could not verify," never a guess.
An explicit `Keyword: <term>` line in the description always overrides, and
the **Target keyword** field in the QA panel is the simplest option of all.

## Talking to QA directly

Beyond the automatic reviewer, there's a dedicated **QA chat** — a `/qa`
entry in the sidebar, live today. It's a friendly, plain-spoken reviewer
built for someone who's never QA'd anything before:

- **Paste a live URL** and say what it is ("QA this guest post," "check this
  citation," or just paste a link on the client's own site) — it runs the
  real checks inline and reports back, without touching the board at all.
- **Name a board task** ("QA the Inner West page") — it confirms before
  running the full task review, since that one *can* bounce the task.
- **Ask how QA's been going** — "what failed QA this week for Acme?" — it
  answers from the actual recorded verdicts, never re-judging anything
  itself.

If you paste a link to something on someone else's site (a guest post, a
press release, a directory listing), QA will ask which client it's for —
that's expected, not a bug, since a third-party link can't reveal the client
on its own the way a page on the client's own domain can.

## Where QA results show up

- **The task drawer's QA panel** — always the full history.
- **Notifications** — a fail or needs-human posts a warning to the client's
  feed (and Slack, when configured); a clean pass is silent by default so
  the channel isn't noisy. Repeated fails on the same task in one day post
  only once.
- **The task's Activity log** — a distinctly labeled **"QA reviewed the
  deliverable"** entry, every time (contrast this with PACE's writes, which
  look like ordinary edits — see Part 1).
- **SerMaStr and PACE** can both read recent QA verdicts when you ask them
  about a client's quality or delivery health — they cite the recorded
  verdict rather than re-judging anything.

## Who owns what, once QA is involved

- **QA** judges the deliverable and opens the finding — the bounce, the
  rework items. It doesn't chase anyone or decide what to do next.
- **PACE** owns getting the rework actually done — nudging, reassigning,
  keeping the bounced task moving.
- **SerMaStr** owns the judgment calls QA hands off (a Service Silo plan) and
  any systemic pattern QA's findings reveal (every page on a client failing
  the same check is a strategy signal, not just a string of one-off fails).

---

## Quick reference

| Want to… | Where |
|---|---|
| See what's overdue/stuck across every board | The daily digest, or ask PACE in `#pace` / `/pace` |
| Approve PACE's proposed fixes for the day | Reply `yes` (or `yes 1,3`) to the Chase Plan |
| Ask "what should I work on today?" | `#pace` or `/pace`, no client needed |
| Get PACE to reassign / due-date / unblock / nudge one task | Ask it in plain English — it confirms before acting |
| Fix several tasks at once | Ask PACE for a batch — "nudge all of X's overdue" |
| Find out why a task is stuck | Ask PACE — it reads the task's full history before answering |
| Generate this month's tasks via chat | Needs admin — use the board's own button otherwise |
| Check a specific task's deliverable | Task drawer → QA panel → **Run QA** |
| Fix a "needs a human" result | See the troubleshooting table above — usually a missing link or keyword |
| Work through a failed review | Check off the `Rework:` items QA added — it re-reviews itself |
| QA a page without a task | The `/qa` chat — paste the URL |
| See what QA has caught recently | Task's Activity log, the QA panel's history, or ask QA/PACE/SerMaStr |

---

*See also: the [Task Manager User Guide](native-task-manager-user-guide.md)
for the board itself — sections, statuses, checklists, views, and Task
Library — and the [PM Operations Addendum](pm-operations-addendum.md) for
the judgment calls behind capacity, duplicate task names, and Chase Plan
triage.*
