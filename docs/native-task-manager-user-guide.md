# Task Manager — User Guide

A step-by-step tutorial for using AR Tools' native task manager — the in-house
replacement for Asana. Covers the day-to-day: finding your board, creating and
working tasks, views and filters, My Tasks, and the Task Library. No code, no
terminal — everything here happens in the dashboard.

> **This guide is scoped to the task board itself.** AR Tools also has agents that
> watch this board for you (PACE keeps delivery moving, QA reviews finished work,
> DORA watches for things falling between the cracks). You don't need to know how
> they work to use the board day-to-day — this guide only covers what you click.

---

## Before you start

- **Where it lives.** There's no single global "Tasks" page — each client has their
  own board. Open a client, then click the **Tasks** card in their workspace.
  Two things *are* global, in the left sidebar: **My Tasks** (everything assigned
  to you, across every client) and **Task Library** (the standard-task templates
  admins maintain).
- **Assignees are your Everhour/Asana-linked team profile, not your login.**
  When you pick "who's on this," you're picking from the shared team-member
  roster (the same list used on the Workload page) — not AR Tools user accounts.
  If you don't see your own name in an assignee dropdown, ask an admin to link
  you on the Team page.
- **A few buttons are admin-only.** Auto-assigning a batch of unassigned tasks,
  and permanently deleting something from the trash, both require an admin.
  Everything else — creating tasks, dragging cards, commenting, checking things
  off — is open to everyone with access to the client.
- **Frozen clients pause task creation.** If a client is under a Freeze (manual
  action / deindexing), you can still work existing tasks, but some automated
  paths that create new tasks are paused until the freeze lifts.

---

## The big picture

Each client's board is organized into **sections** (almost always calendar
months — "July 2026", "August 2026" — plus any custom sections you add), and
each section holds **tasks**. A task can have **subtasks** (a checklist), and
carries assignee, due date, status, category, notes, comments, attachments, and
a running activity log.

You can look at the same board three ways — **Board**, **List**, or
**Calendar** — and slice it with filters or a saved view. Nothing about the
underlying data changes based on which view you're in; they're just different
lenses on the same tasks.

```
Client workspace → Tasks card → Board / List / Calendar, filtered however you like
```

---

## Step 1 — Open a client's board

From the client's workspace, click the **Tasks** card. You'll land on the Board
view. The subhead under the page title is a good one-line reminder: *"{Client}'s
delivery board — native tasks, organized by month. Drag cards between status
columns; click a card for details & checklist."*

---

## Step 2 — Start the month (Generate this month)

Most recurring work doesn't need to be typed in by hand every month. Click the
solid indigo **Generate this month** button (top right):

- It creates (or fills in) a section named for the current calendar month —
  e.g. "August 2026" — and populates it from the client's **monthly template**
  (the recurring standard tasks configured for that client).
- Each generated task picks up its default estimated hours, category, and
  starter checklist from the **Task Library** (Step 8) — so if a task's
  checklist looks wrong, the fix belongs in the Library, not on the task itself.
- **It's safe to click more than once.** Re-running it only fills gaps — it
  never duplicates tasks that already exist for the month.
- A banner tells you what happened: how many tasks were created, that the
  month was already fully generated, or that the client has no monthly
  template set up yet (an admin sets that up separately).

If you're an admin, there's a second button, **Auto-assign unassigned**, that
distributes any newly generated, unassigned tasks across the eligible team by
skill and current workload. Tasks it can't place (the eligible team is at
capacity) are left unassigned and called out in the result banner — that's a
capacity signal, not an error.

---

## Step 3 — Pick a view

Three toggle buttons, top left: **Board**, **List**, **Calendar**.

### Board
The familiar Kanban layout — one column per status (Not Started, In Progress,
In QA, Blocked, In Review, Sent to Client, Client Approved, Completed, by
default; an admin can add or rename statuses). Each card shows the task name,
a colored category chip, checklist progress ("☑ 2/5"), estimated hours, due
date (red if overdue), and the assignee's name.

**Drag a card to a different column to change its status.** Two special cases
happen automatically:
- Drop it in the **last ("done") column** → the task is marked complete.
- Drag a **completed** card back into any earlier column → it reopens, then
  moves to that column.

Each column has a quick **"Add a task…"** field at the bottom — type a name
and hit Enter to create a task with that column's status, dropped into the
newest month section.

### List
Grouped by section (newest month first), each group showing a "{done}/{total}"
count. Click the circle next to a task to complete/reopen it right from the
list. Each section also has its own quick-add row at the bottom.

### Calendar
A standard month grid. Tasks show as small chips on their due date — indigo
for upcoming, red for overdue, green (strikethrough) for completed. Use the
**‹ › Today** controls to move between months. Click any chip to open that
task. If a day has more than four tasks, it shows a "+N more" — switch to List
or Board to see the rest.

---

## Step 4 — Filter, or save a view

The filter bar (Board and List) gives you:

- **Search** — matches task name/description as you type.
- **Assignee** — narrow to one team member.
- **Service type** — narrow to one category (Content, Link Building, GBP
  Authority, Strategy, by default).
- **Section** — narrow to one month or custom section.

There's also a **Views…** dropdown with three always-available presets —
**Overdue**, **Due this week**, **Unassigned** — and, below a divider, any
**saved views** your team has created (views shared with everyone show a
"(team)" tag).

**To save your own combination of filters:** set up search/assignee/category/
section/view-mode the way you want, then pick **"＋ Save current view…"** at
the bottom of the Views dropdown. You'll be asked to name it, then whether to
share it with the whole team or keep it private to you. It'll reappear in the
dropdown from then on, with an "×" to delete it (you can delete your own
private views any time; deleting a shared one needs an admin).

---

## Step 5 — Work a task

Click any card, row, or calendar chip to open the **task drawer** on the
right. Everything here saves as you go — there's no separate Save button for
most fields.

**The basics**
- **Name** — click and edit directly at the top.
- **Status / Assignee / Service type** — dropdowns.
- **Est. hours** — a number; if the team logs time in Everhour, an "Actual: Xh"
  line appears underneath once real hours have been logged, colored green or
  red against your estimate.
- **Due date / Start date** — date pickers.
- **Description** — internal notes, links, acceptance criteria. Never shown to
  the client.
- **Client note** — a separate field, explicitly client-facing (it can surface
  in client-facing reporting). Write it in plain language — e.g. *"Rewrote the
  homepage intro to target 'roof repair Miami'."*

**Checklist** — add, check off, or remove subtasks under "Checklist." This is
what "☑ 2/5" on the card is counting.

> **Heads up — some status changes happen on their own.** Touching a checklist
> item (checking it, commenting, attaching a file) on a task that's "Not
> Started" moves it to "In Progress" automatically. Checking off the last real
> work item on the checklist moves the task to "In QA" automatically. This is
> intentional — it keeps the board honest without you having to remember to
> drag the card yourself. It never happens in reverse, and it never touches
> "Blocked" or "In Review."

**Attachments** — click **Attach file** to upload; uploaded files list with
their size and a delete option.

**Comments** — type below the thread, `@Name` to mention a teammate (they'll
get notified). You can edit or delete your own comments; admins can moderate
anyone's.

**Activity** — a running, timestamped log of everything that's happened to the
task (renamed, status changed, assignee changed, commented, attached, auto-
ticked, completed, etc.) — useful for reconstructing what happened without
asking around.

**Header buttons**
- **Complete / Reopen** — toggle.
- **Watch bell** — get notified on activity even if you're not the assignee.
- **Duplicate** — copies the task, including its checklist, as a new task.
- **Trash** — moves it to the trash (recoverable — see Step 9).
- **For QA** — on a finished top-level task, this moves it straight to the "In
  QA" status and kicks off an automatic quality check. You'll see a QA panel
  further down the drawer with a readiness check, the rubric being used, and —
  once it's run — a pass/fail verdict with a plain-language breakdown of what
  was checked. A "fail" bounces the task back to "In Progress" with new
  checklist items telling you exactly what to fix; fixing all of them re-queues
  it for QA automatically.

---

## Step 6 — My Tasks (your own queue, every client)

Click **My Tasks** in the sidebar for everything assigned to you, from every
client, in one list — no need to check board after board.

- **Viewing as** — a dropdown at the top listing every tracked team member,
  with **"(you)"** next to whichever one is linked to your login. Normally you
  leave this on yourself; switching it lets you check someone else's queue
  (useful for a PM doing a coverage check). Your choice is remembered the next
  time you visit.
- Tasks are grouped into buckets: **Overdue**, **Due today**, **This week**,
  **Later**, **No due date** — only non-empty buckets show. If everything's
  clear, you'll get a plain "All clear — nothing open."
- Click the circle to complete a task right from the list, or click anywhere
  else on the row to open the full drawer. The client-name pill on each row
  links straight to that client's board.

---

## Step 7 — Task Library (admins: keep the templates current)

**Task Library**, in the sidebar, is the master list of standard recurring
task names — the source of truth **Generate this month** reads from. For each
task name it stores:

- **Default hrs** — the estimate a new task of this name is created with.
- **Default category** — its Service Type (should match one of your active
  category options).
- **Client blurb** — plain-language client-facing copy explaining why this
  work matters (used in client reporting).
- **Active** — untick to retire a task name without deleting its history.

Click **Add task** for a new row, edit inline, then **Save library**. Renaming
a task and saving **detaches its checklist from the old name** — if you rename
something, re-add its checklist under the new name.

**Default checklist per task** — expand "Checklist · N items" under any saved
row to edit the starter subtasks that get copied onto every task of that name
when the month is generated. Add steps, reorder (up-arrow), or remove them,
then **Save checklist** (this saves independently of the main table).

---

## Step 8 — Trash and recovery

Click the **Trash** icon in a client's Tasks toolbar to see everything that's
been trashed for that client (subtasks are labeled "(subtask)").

- **Restore** — anyone can bring a task back.
- **Delete forever** — admin-only, asks for confirmation, cannot be undone.

---

## Step 9 — Custom sections

Need a bucket that isn't a calendar month — a backlog, a one-off project?
Click the **Section** button (plus icon) in the toolbar, name it, and it
appears alongside the month sections in List view and the Section filter.
Add tasks to it the same way as any other section.

---

## On your phone

The dashboard is installable as a mobile app (add it to your home screen from
your phone's browser). On a small screen the sidebar becomes a slide-over menu
— tap the hamburger icon top-left to open it, tap anywhere outside it to
close.

---

## Quick reference

| Want to… | Where |
|---|---|
| See everything assigned to me, across clients | **My Tasks** (sidebar) |
| See one client's whole delivery plan | Client → **Tasks** card |
| Start this month's recurring work | **Generate this month** button |
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
