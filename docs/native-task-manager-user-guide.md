# Task Manager — User Guide

A step-by-step tutorial for using AR Tools' native task manager — the in-house
replacement for Asana. Written for someone who has never opened it before:
where things live, what the words mean, what goes in which field, and a real
example worked start to finish. No code, no terminal — everything here
happens in the dashboard.

> **This guide is scoped to the task board itself.** AR Tools also has agents
> that watch this board for you (one keeps delivery moving, one reviews
> finished work, one watches for things falling between the cracks). You
> don't need to know how they work to use the board day-to-day — this guide
> only covers what you click.
>
> **See also:** the [PACE & QA User Guide](pace-qa-user-guide.md) covers the
> two of those agents you'll actually talk to — PACE (delivery, in `#pace` /
> `/pace`) and QA (the automatic reviewer + rubrics behind the "For QA"
> button below).

---

## Terms you'll see

Skim this once — the rest of the guide uses these words precisely.

| Term | What it means here |
|---|---|
| **Board** | One client's whole delivery plan — every task for that client, in one place. Each client has their own; there's no single company-wide board. |
| **Section** | A group of tasks within a board. Almost always a calendar month ("August 2026"), auto-created for you — see Step 2. |
| **Task** | One piece of work — e.g. this month's GBP posts for a client, or a batch of citations. |
| **Subtask / checklist item** | A single step inside a task. A task's "checklist" is its list of subtasks. |
| **Status** | Where a task is in the delivery pipeline — Not Started, In Progress, etc. One task has exactly one status at a time. |
| **Category (Service type)** | What *kind* of work the task is — Content, Link Building, GBP Authority, or Strategy. Used for filtering and reporting. |
| **Assignee** | Who's doing the task. Picked from the shared team roster, not your login (see below). |
| **Watcher** | Anyone who gets notified about a task's activity, whether or not they're the assignee. |
| **View** | A way of looking at a board — Board (columns), List (grouped rows), or Calendar (by due date). Same tasks, different layout. |
| **My Tasks** | Your own queue — every task assigned to you, from every client, in one place. |
| **Task Library** | The master list of standard recurring task names, and what each one defaults to (hours, category, checklist). |

---

## Before you start

- **Where it lives.** There's no single global "Tasks" page — each client has
  their own board. Open a client, then click the **Tasks** card in their
  workspace. Two things *are* global, in the left sidebar: **My Tasks**
  (everything assigned to you, across every client) and **Task Library**
  (the standard-task templates admins maintain).
- **Assignees are your team profile, not your login.** When you pick who's on
  a task, you're picking from the shared team-member roster — the same list
  used on the Workload page — not AR Tools user accounts. If you don't see
  your own name in an assignee dropdown, ask an admin to link you on the
  **Team** page. Until then, tasks can still be assigned to you by name, but
  the system won't know it's *you*.
- **A few buttons are gated.** Auto-assigning a batch of unassigned tasks and
  permanently deleting something from the trash both require an **admin**;
  **Generate this month** requires a **PACE PM** (Minda, Kyle, or Ryan — see
  Step 2) and is simply hidden if you're not one. Creating tasks, dragging
  cards, commenting, checking things off — all open to anyone with access to
  the client. **Why these are gated:** each can create, move, or remove a lot
  of the board in one go — Generate this month builds a whole month,
  auto-assign can staff dozens of tasks at once, and a permanent delete can't
  be undone the way Trash can. Everything else you'll do day to day only ever
  touches one task at a time. (The
  [PM Operations Addendum](pm-operations-addendum.md) covers the PM role and
  the admin-gated actions together.)
- **Frozen clients pause task creation.** If a client is under a Freeze
  (manual action / deindexing), you can still work existing tasks, but the
  automated paths that create new tasks are paused until the freeze lifts.

---

## Where your day starts

Two ways in, depending on what you're doing:

- **Checking everything on your plate, across every client** → click **My
  Tasks** in the sidebar. This is usually where your day should start (Step
  6 below has the details).
- **Working a specific client's whole plan** → from the sidebar, or from the
  **Home** page's grid of client tiles, open the client, then click their
  **Tasks** card.

**The bell icon** at the top of the sidebar is your notification center — it
badges with an unread count whenever you're assigned a task, `@mentioned` in
a comment, or nudged by someone. Click it for a dropdown list; clicking a
notification jumps straight to the task it's about and marks it read. A
small toast also pops in the corner if a new one arrives while you have the
tab open.

Those same alerts — a task assigned to you, an `@mention`, a comment on a
task you watch, a nudge — also reach you as a **Slack DM** (and post to the
client's own channel where one is set up), **not** the shared `#pace`
channel — so you get what concerns *you* without the whole team's traffic.
The bell is the always-on backstop if a DM can't be delivered (your Slack
isn't linked, or the app doesn't yet have DM permission).

---

## The big picture

Each client's board is organized into **sections** (almost always calendar
months, plus any custom sections you add), and each section holds **tasks**.
A task can have **subtasks** (a checklist), and carries an assignee, due
date, status, category, notes, comments, attachments, and a running activity
log.

You can look at the same board three ways — **Board**, **List**, or
**Calendar** — and slice it with filters or a saved view. Nothing about the
underlying data changes based on which view you're in; they're just
different lenses on the same tasks.

### The pipeline a task moves through

Left to right, this is the order columns appear in on the Board (Step 3):

```
Not Started → In Progress → In QA → Sent to Client → Client Approved → Completed
```

Two more statuses sit at the very end of the row rather than in the flow —
a task can drop into either one **from anywhere** when something stalls or
gets bounced, and comes back out the same way:

- **Blocked** — waiting on something outside your control (a client
  approval, another team's input).
- **In Review** — sent back, usually by the client, for changes.

**Why these two are separate from the main row, not just two more columns:**
everything else in the pipeline moves in a predictable order — the system
can tell "In QA" is a step forward from "In Progress." Blocked and In
Review aren't steps in that order at all; they're a *pause*, and pausing
can happen from wherever the task already was. Folding them into the main
row would force a fake position on them ("is Blocked before or after In
QA?") that doesn't mean anything. **What to do:** use them for exactly what
they say — something outside your control, or a client's changes request —
not as a general "not sure what to do with this" bucket. And move a task
*out* of one by hand once the blocker clears or the changes are done; the
checklist auto-advance described below deliberately never touches these
two, so nothing will do it for you.

You set a task's status by dragging its card between columns, or by hand in
the task drawer's **Status** dropdown — both are covered in Step 3 and 5.

---

## Step 1 — Open a client's board

From the client's workspace, click the **Tasks** card. You land on the Board
view. The subhead under the page title is a good one-line reminder of the
whole idea: *"{Client}'s delivery board — native tasks, organized by month.
Drag cards between status columns; click a card for details & checklist."*

---

## Step 2 — Start the month

Most recurring work doesn't need to be typed in by hand every month — and it
isn't: **every client's month is generated automatically on the 1st.** The
solid indigo **Generate this month** button (top right) is for doing it *on
demand* — a mid-month catch-up, or a client set up after the 1st. It's a
**PACE PM** action (Minda, Kyle, or Ryan), so the button only appears if
you're a PM; everyone else relies on the automatic run.

- It creates (or fills in) a section named for the current calendar month —
  e.g. **August 2026** — and populates it from the client's **monthly
  template** (the recurring standard tasks configured for that client, e.g.
  a set number of citations, a round of GBP posts, this month's blog posts).
- Each generated task picks up its default estimated hours, category, and
  starter checklist from the **Task Library** (Step 7) — so if a task's
  checklist looks wrong, fix it in the Library, not on the task itself.
- **It's safe to click more than once.** Re-running it only fills gaps — it
  never duplicates tasks that already exist for the month.
- A banner tells you what happened: how many tasks were created, that the
  month was already fully generated, or that the client has no monthly
  template set up yet (an admin sets that up separately).

  **Why it's safe to click twice:** each task it would create is keyed to
  its own client + month + template row, not to "this run." A second click
  checks that same key again and only fills in what's still missing — it
  isn't re-running a bulk import that could double up. **What to do:** if
  you're ever unsure whether this month's tasks already exist for a client,
  just click it — there's no "check first" step, and no harm in a redundant
  click. Don't work around a missing task by deleting and re-generating the
  whole month; that throws away anything already in progress on the tasks
  that *did* exist. Trash the one task you don't want and leave the rest.

If you're an admin, there's a second button, **Auto-assign unassigned**, that
distributes any newly generated, unassigned tasks across the eligible team by
skill and current workload. Tasks it can't place (the eligible team is at
capacity) are left unassigned and named in the result banner — that's a
capacity signal, not an error.

---

## Step 3 — Pick a view

Three toggle buttons, top left: **Board**, **List**, **Calendar**.

### Board
The Kanban layout — one column per status, in pipeline order (see above).
Each card shows the task name, a colored category chip, checklist progress
("☑ 2/5"), estimated hours, due date (red if overdue), and the assignee's
name.

**Drag a card to a different column to change its status.** Two special
cases happen automatically:
- Drop it in **Completed** → the task is marked complete.
- Drag a **completed** card back into any earlier column → it reopens, then
  moves to that column.

Each column has a quick **"Add a task…"** field at the bottom — type a name
and hit Enter to create a task with that column's status, dropped into the
newest month section.

### List
Grouped by section (newest month first), each group showing a "{done}/
{total}" count. Click the circle next to a task to complete/reopen it right
from the list. Each section also has its own quick-add row at the bottom.

### Calendar
A standard month grid. Tasks show as small chips on their due date — indigo
for upcoming, red for overdue, green (strikethrough) for completed. Use the
**‹ › Today** controls to move between months. Click any chip to open that
task. If a day has more than four tasks, it shows a "+N more" — switch to
List or Board to see the rest.

---

## Step 4 — Filter, or save a view

The filter bar (Board and List) gives you:

- **Search** — matches task name/description as you type.
- **Assignee** — narrow to one team member.
- **Service type** — narrow to one category (Content, Link Building, GBP
  Authority, Strategy — see Step 5 for what belongs in each).
- **Section** — narrow to one month or custom section.

There's also a **Views…** dropdown with three always-available presets —
**Overdue**, **Due this week**, **Unassigned** — and, below a divider, any
**saved views** your team has created (views shared with everyone show a
"(team)" tag).

**To save your own combination of filters:** set up search/assignee/
category/section/view-mode the way you want, then pick **"＋ Save current
view…"** at the bottom of the Views dropdown. You'll be asked to name it,
then whether to share it with the whole team or keep it private to you.
It'll reappear in the dropdown from then on, with an "×" to delete it (your
own private views any time; deleting a shared one needs an admin).

---

## Step 5 — Work a task

Click any card, row, or calendar chip to open the **task drawer** on the
right. Everything here saves as you go — there's no separate Save button for
most fields.

### The basics

- **Name** — click and edit directly at the top.
- **Status** — dropdown; see the pipeline above.
- **Assignee** — dropdown, from the shared team roster.
- **Service type** — which category this task belongs to. If it isn't
  obvious from the task name, here's the real breakdown in use today:

  | Category | What goes here | Real examples |
  |---|---|---|
  | **Content** | Writing and publishing on the client's own site or blog | Blog Post Title, Blog Post Scheduling, Website Pages Posted, Service Silo |
  | **Link Building** | Anything that earns a mention or link elsewhere | (Number) Citations, Guest Posts, Niche Edits, Press Release, Map Embeds |
  | **GBP Authority** | Google Business Profile activity | GBP Posts, GBP Blast, HyperLocal GBP Blast |
  | **Strategy** | Planning and account-level decisions, not a deliverable itself | — |

  A task generated by **Generate this month** already has its category set
  correctly from the Task Library — you only need to pick one by hand when
  creating something new.

  **Why it's worth getting right even when it "doesn't matter yet":** the
  category is also what the team's skill/competency system reads once it's
  in use — it's how a task ends up routed to someone who can actually do
  that kind of work, not just whoever's free. Picking the wrong category on
  a one-off task is invisible today; it stops being invisible the moment
  that routing turns on. (The [PM Operations Addendum](pm-operations-addendum.md)
  covers how that routing actually works.)
- **Est. hours** — a number; if the team logs time in Everhour, an "Actual:
  Xh" line appears underneath once real hours have been logged, colored
  green or red against your estimate. For a task generated from the month
  template, leave this as-is unless the work is turning out to be
  meaningfully bigger or smaller than usual.

  **Why an empty estimate isn't "neutral":** the Workload page's whole
  read of who's over capacity is built by summing this field across
  everyone's open tasks — and a blank one doesn't count as zero, it counts
  as the platform's default (currently 1h). A task that's really a 6-hour
  job but never got an estimate quietly understates that person's load by
  5 hours, every day it sits open. **What to do:** for a task generated
  from the Library, leaving the default is fine — that number came from
  real experience with that task type. For anything hand-created, or a
  task that's clearly running longer than usual, put in your best real
  number rather than leaving it blank "for now."
- **Due date / Start date** — date pickers.
- **Description** — internal notes, links, acceptance criteria. Never shown
  to the client. This is the right place for anything the *team* needs but
  the client doesn't.
- **Client note** — a separate field, explicitly client-facing (it can
  surface in the client-facing **Weekly Pulse** update). **You usually don't
  need to fill this in.** For a standard task generated from the Task
  Library, a good plain-language blurb is already defined centrally and used
  automatically — e.g. GBP Posts already reads *"Fresh posts on your Google
  Business Profile that keep your listing active and give searchers a reason
  to choose you."* Only write your own Client note when *this specific
  instance* of the work needs something different from the standard
  explanation — a one-off task with no library entry, or something unusual
  enough about this month's work that the client should know. Keep it in
  plain language, e.g. *"Rewrote the homepage intro to target 'roof repair
  Miami'."*

### Checklist

Add, check off, or remove subtasks under **Checklist** — this is what "☑
2/5" on the card is counting. A task generated from the Task Library already
comes with its standard checklist. For example, a **GBP Posts** task starts
with:

1. GBP Posts generated
2. GBP Posts added to deliverables sheet
3. GBP Posts sent to client for approval
4. GBP Posts scheduled

You work down the list and check items off as you actually complete them —
you don't need to do anything else to move the task along (see the callout
below).

**Why there's no hours field on a subtask:** the parent task's **Est.
hours** is meant to cover the whole checklist, not just the top-level task
name. If subtasks had their own separate estimates too, a well-checklisted
task would get double-counted in the Workload page's math. **What to do:**
put your realistic total on the parent task, not spread thin across steps —
a long, detailed checklist under one honest hour estimate is exactly how
it's supposed to work, not a sign you're missing a field.

> **Heads up — some status changes happen on their own.** Touching a
> checklist item (checking it, commenting, attaching a file) on a task
> that's "Not Started" moves it to "In Progress" automatically. Checking off
> the **last** item on the checklist moves the task to "In QA" automatically.
> This is intentional — it keeps the board honest without you having to
> remember to drag the card yourself. It never happens in reverse, and it
> never touches "Blocked" or "In Review."

### Attachments

Click **Attach file** to upload; uploaded files list with their size and a
delete option. If your work produces a link rather than a file — a
deliverables sheet, a live page, a citation URL — put it in a comment or a
checklist item rather than trying to attach it.

### Comments

Type below the thread, `@Name` to mention a teammate — they'll get notified
through the bell. You can edit or delete your own comments; admins can
moderate anyone's. Use comments for anything that needs a reply or a
record — handing work off, flagging a question, explaining why something
took a detour.

### Activity

A running, timestamped log of everything that's happened to the task
(renamed, status changed, assignee changed, commented, attached, auto-
ticked, completed, etc.) — useful for reconstructing what happened without
asking around.

### Header buttons

- **Complete / Reopen** — toggle.
- **Watch bell** — get notified on activity even if you're not the assignee.
- **Duplicate** — copies the task, including its checklist, as a new task.
- **Trash** — moves it to the trash (recoverable — see Step 8).
- **For QA** — on a finished task, this moves it straight to "In QA" and
  kicks off an automatic quality check. Normally you don't need to click
  this yourself — checking off a task's last checklist item does it for
  you — but it's here for the times you want to push something into review
  early. A QA panel further down the drawer shows a readiness check, the
  rubric being used, and — once it's run — a pass/fail verdict with a
  plain-language breakdown of what was checked. A **fail** bounces the task
  back to "In Progress" with new checklist items telling you exactly what to
  fix; checking all of them off re-queues it for QA automatically.

---

## Step 6 — My Tasks (your own queue, every client)

Click **My Tasks** in the sidebar for everything assigned to you, from every
client, in one list — no need to check board after board. This is the
fastest way to answer "what should I be working on right now?"

- **Viewing as** — a dropdown at the top listing every tracked team member,
  with **"(you)"** next to whichever one is linked to your login. Normally
  you leave this on yourself; switching it lets you check someone else's
  queue (useful for a PM doing a coverage check). Your choice is remembered
  the next time you visit.
- Tasks are grouped into buckets: **Overdue**, **Due today**, **This week**,
  **Later**, **No due date** — only non-empty buckets show. If everything's
  clear, you'll get a plain "All clear — nothing open."
- Click the circle to complete a task right from the list, or click anywhere
  else on the row to open the full drawer. The client-name pill on each row
  links straight to that client's board.

A reasonable daily habit: open My Tasks, work down from **Overdue**, then
**Due today**, checking things off as you go and opening the drawer whenever
you need the checklist or context.

---

## Step 7 — Task Library (admins: keep the templates current)

**Task Library**, in the sidebar, is the master list of standard recurring
task names — the source of truth **Generate this month** reads from. For
each task name it stores:

- **Default hrs** — the estimate a new task of this name is created with.
- **Default category** — its Service Type (should match one of your active
  category options).
- **Client blurb** — plain-language client-facing copy explaining why this
  work matters (used in the Weekly Pulse — see Step 5's Client note field
  for how the two relate).
- **Active** — untick to retire a task name without deleting its history.

Click **Add task** for a new row, edit inline, then **Save library**.
Renaming a task and saving **detaches its checklist from the old name** — if
you rename something, re-add its checklist under the new name.

**Why renaming does that:** the Library doesn't track a task type by some
hidden ID — it matches on the **name itself**. Rename "GBP Blast" to "GBP
Blast v2" and, as far as the Library's concerned, "GBP Blast v2" is a
different, brand-new task name with no checklist on file yet; the old
"GBP Blast" checklist stays exactly where it was, attached to the name you
moved away from.

**What to do — a real example:** say a client ends up with two open "GBP
Blast" tasks in the same month (one leftover from last month, one freshly
generated) and you want to tell them apart on a live board, not just in the
Library. Renaming the leftover one to "GBP Blast — carryover from July"
makes it addressable by name again — but it also detaches it from the
"GBP Blast" checklist template. If it still needs that standard checklist,
re-add it by hand under the new name (or copy it before renaming); if it's
mostly done already, this usually doesn't matter enough to bother.

**Default checklist per task** — expand "Checklist · N items" under any
saved row to edit the starter subtasks that get copied onto every task of
that name when the month is generated. Add steps, reorder (up-arrow), or
remove them, then **Save checklist** (this saves independently of the main
table).

---

## Step 8 — Trash and recovery

Click the **Trash** icon in a client's Tasks toolbar to see everything
that's been trashed for that client (subtasks are labeled "(subtask)").

- **Restore** — anyone can bring a task back.
- **Delete forever** — admin-only, asks for confirmation, cannot be undone.

---

## Step 9 — Custom sections

Need a bucket that isn't a calendar month — a backlog, a one-off project?
Click the **Section** button (plus icon) in the toolbar, name it, and it
appears alongside the month sections in List view and the Section filter.
Add tasks to it the same way as any other section.

---

## A day, start to finish

To tie it together, here's a realistic single task from open to done.

You open **My Tasks** and see **GBP Posts — Acme Roofing** in your **Due
this week** bucket. You click it. The drawer opens on:

- **Status:** Not Started · **Category:** GBP Authority · **Assignee:** you
- **Checklist (0/4):**
  1. GBP Posts generated
  2. GBP Posts added to deliverables sheet
  3. GBP Posts sent to client for approval
  4. GBP Posts scheduled
- **Client note:** blank — the Task Library's standard blurb already covers
  this in the Weekly Pulse, so you leave it alone.

You draft this month's posts and check off **"GBP Posts generated."** The
task quietly flips from **Not Started** to **In Progress** — you didn't have
to touch the Status dropdown or drag anything. You drop the posts into the
deliverables sheet and check off item 2, send them to the client for
approval and check off item 3. Once they're approved and scheduled, you
check off the last item, **"GBP Posts scheduled."**

Checking that last box automatically moves the task to **In QA** and kicks
off an automatic quality check — no action needed from you. If it comes back
clean, the task sits in In QA until someone sends it on to the client (or,
depending on the workflow, moves it further along by hand). If the check
finds something wrong, the task bounces back to **In Progress** with a new
checklist item spelling out exactly what to fix — you fix it, check it off,
and it re-queues for QA on its own.

That's the whole loop: open from My Tasks, work the checklist, let status
take care of itself, done.

---

## On your phone

The dashboard is installable as a mobile app (add it to your home screen
from your phone's browser). On a small screen the sidebar becomes a
slide-over menu — tap the hamburger icon top-left to open it, tap anywhere
outside it to close.

---

## Quick reference

| Want to… | Where |
|---|---|
| See everything assigned to me, across clients | **My Tasks** (sidebar) |
| See one client's whole delivery plan | Client → **Tasks** card |
| Get notified about mentions/assignments | Bell icon, top of the sidebar |
| Start this month's recurring work | Automatic on the 1st; on demand, **Generate this month** (a PACE PM only) |
| Change a task's status fast | Drag its card between Board columns |
| Change a task's status by hand | Open it → **Status** dropdown |
| Check something off a task | Open it → **Checklist** |
| Leave a note for a teammate | Open it → **Comments**, `@mention` them |
| Write something the client will see | Open it → **Client note** field |
| Send a task for quality review | Open it → **For QA** button |
| Get a task back after deleting it | Toolbar → **Trash** → **Restore** |
| Filter down to what's overdue / unassigned | **Views…** dropdown → built-in presets |
| Save my own filter combo for reuse | Set filters → **Views…** → **＋ Save current view…** |
| Fix a recurring task's default hours/checklist | **Task Library** (sidebar) |

---

*See also: the [PACE & QA User Guide](pace-qa-user-guide.md) for the two
agents that watch this board — PACE (delivery) and QA (quality) — and the
[PM Operations Addendum](pm-operations-addendum.md) for the judgment calls
behind capacity, duplicate task names, and Chase Plan triage.*
