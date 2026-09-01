# Everhour Time Tracking — New Hire Tutorial

*A hands-on guide to take you from "never opened Everhour" to tracking your time correctly, every
day, without thinking about it. Written for anyone doing billable client work — VAs, strategists,
writers, account managers. No code, no terminal. Budget 30–45 minutes to read and set up; after
that the habit runs itself.*

> **What this document is not.** This isn't the engineering spec for the integration (that's
> `docs/modules/everhour-time-tracking-integration-plan-v1_0.md`) and it isn't Everhour's own help
> center (everhour.com has full docs for power features like invoicing and budgets, which we don't
> use here). This is the practical "what do I actually click, and why does it matter" guide for a
> person joining the team.

---

## 1. The one-paragraph version

**Everhour is the stopwatch. The suite is the brain.** You track your hours in Everhour — a
lightweight time-tracking tool with a Chrome extension and a web app — against the clients and
tasks you're working on. Once a day, the suite automatically pulls everyone's logged time and
turns it into three things the agency actually uses: how much a client's work really costs (feeds
the Recipe Engine's budget math), how full or empty each person's plate is (feeds PACE's workload
view), and how a task's actual time compared to what was estimated (shown right on the task
itself). You don't manage your to-do list in Everhour — that's still the suite's Task board.
Everhour's only job is the clock.

---

## 2. Terms you'll see

| Term | Means |
|---|---|
| **Everhour** | The third-party time-tracking tool (everhour.com) the whole agency uses to log hours. |
| **Project** (in Everhour) | Everhour's word for a client. Every client we work with has exactly one matching Everhour project — same name, one-to-one. |
| **Task** (in Everhour) | A to-do item inside a project. Ours are created *for* you automatically — see §4. |
| **Timer** | Click once to start, click once to stop — Everhour counts the seconds while it runs. |
| **Manual entry** | Typing in a number of hours after the fact instead of running a live timer. |
| **The suite** | Our own dashboard — clients, the Task board, SerMaStr, PACE, Reports, everything else in this repo. |
| **Task board / native tasks** | The suite's own to-do list per client (`/clients/:id/tasks` and `/my-tasks`) — where status, due dates, comments, and checklists live. Covered in `docs/native-task-manager-user-guide.md`. |
| **Sync** | The once-a-day automatic pull that copies your Everhour hours into the suite. |
| **Actual hours** | How long a task really took, per the sync — shown next to the estimate on the task itself. |
| **Utilization** | What percentage of your expected weekly hours you've actually logged — shown on the Team/Workload page. |
| **Recipe Engine** | The suite's monthly-budget calculator for a client (`/clients/:id/task-plan`). Its "actual margin" reads Everhour hours once an admin has entered a loaded cost rate. |
| **Billable** | A flag on a time entry — is this client-chargeable work or not. We capture it; ask your PM if your role should be marking it. |

---

## 3. The big picture — how the pieces connect

Before the how-to, it's worth seeing the whole shape once, because every "why" below traces back
to this:

```
You (Chrome extension or Everhour web app)
        │
        │  start/stop a timer, or type a manual entry,
        │  against a PROJECT (=client) and a TASK
        ▼
   Everhour  ──── stores every time entry with your name, the date, the hours
        │
        │  once a day, automatically — you don't trigger this
        ▼
   The suite pulls your team's time and rolls it up three ways:
        │
        ├──▶ Per task:      "actual_hours" shown next to the task's estimate
        ├──▶ Per client:    a Time card on the client workspace + real margin
        │                   in the Recipe Engine (vs. guessing from estimates)
        └──▶ Per person:    your utilization % on the Team/Workload page,
                             which is how PACE knows who has room and who's
                             at capacity before handing out new work
```

Three things fall out of that diagram that are worth understanding up front:

1. **It's one-way.** Everhour never tells you what to work on, and the suite never writes anything
   back into Everhour except the task names themselves (see §4). All the thinking — status, due
   dates, priority — happens on the Task board, not in Everhour. Don't go looking for your
   checklist in Everhour; it isn't there.
2. **The project = the client, always.** If you're doing work for Acme Roofing, you track it under
   the Acme Roofing project in Everhour — never a personal or made-up project name.
3. **This isn't a surveillance tool — it's a planning input.** Nobody is watching a live feed of
   your timer. The numbers exist so the agency can (a) know what a client's work actually costs,
   (b) spot when someone's overloaded *before* they burn out, and (c) make next month's task-plan
   estimates more accurate than a guess. Logging your time accurately is what makes all three of
   those honest.

---

## 4. Where your tasks come from (read this before you go looking for them)

This is the one Everhour-specific quirk worth understanding on day one — it saves you a "why can't
I find my task" message to your PM.

Everhour normally works by plugging into tools like Asana or Trello — you install its extension,
and it draws a little "start timer" button right next to each task on those sites. **Our Task
board is our own custom-built tool, so Everhour can't do that trick here.** Instead, the suite does
the opposite: **the moment a task is created for you on the Task board, a lightweight copy of it —
just the name and who it's assigned to — is automatically pushed into Everhour as a real Everhour
task**, sitting inside that client's project. That copy is what you click into and track time
against.

What this means in practice:

- **Don't create your own tasks in Everhour.** If you don't see the task you're looking for, it
  either hasn't synced yet (give it a minute), isn't assigned to you on the Task board, or is a
  **subtask/checklist item** — only top-level tasks get an Everhour copy, so track time against
  the parent task, not the individual checklist line.
- **Search by the exact task name** from the Task board — the Everhour copy uses the same name.
- **If a task predates you or predates this integration**, it may not have a copy yet. That's
  fine — log it as time against the client's project without a specific task, and mention it to
  your PM.
- The copy is metadata-only. Marking it "done" in Everhour does **nothing** to the real task — you
  still complete it on the Task board.

---

## 5. Day-one setup

Do this once, in order, before you track your first real hour.

### 5.1 Get your account

Everhour accounts are provisioned by an admin, not self-serve. If you don't already have an invite
email from Everhour, ask your PM or admin to add you to the team. You'll set a password (or sign in
with Google, if that's how the team is set up) the first time you log in at
[my.everhour.com](https://my.everhour.com).

### 5.2 Get linked to your suite profile

**This step is the one that's easy to miss and breaks everything downstream if it's skipped.** The
suite ties your Everhour identity to your dashboard login so your logged hours land on the right
person's utilization number and the right client's margin. This link is set up by an admin on the
**Team page** (Team & Capacity → your row → "Everhour user"), not by you — but it's worth
confirming out loud with your PM in your first week: *"Am I linked yet?"* If you're not, your time
is still tracked correctly in Everhour itself, but it won't show up correctly inside the suite
until someone links you.

### 5.3 Install the Chrome extension

1. Go to the official listing: **[Everhour — Time Tracking, Budgets, Expenses](https://chromewebstore.google.com/detail/everhour-%E2%80%94-time-tracking/dnebklifojaaecmheejjopgjdljebpeo)**
   on the Chrome Web Store (or search "Everhour" there yourself — make sure the publisher is
   Everhour and the icon matches the one in your invite email, since extension names get copied).
2. Click **Add to Chrome** → **Add extension**.
3. Click the puzzle-piece icon in Chrome's toolbar and **pin** the Everhour icon so it's always
   visible — you'll use it constantly.
4. Click the pinned icon and sign in with the same account from §5.1.

You don't strictly need the extension — everything below also works from
[my.everhour.com](https://my.everhour.com) in a browser tab — but the extension is faster for the
daily habit because it's always one click away, no matter what tab you're on.

> Install trouble, or on a Chromium browser other than Chrome (Edge, Brave)? Everhour's own
> install walkthrough is at
> [support.everhour.com/article/441](https://support.everhour.com/article/441-how-to-install-everhour-extension-in-chrome)
> (Edge has its own version at
> [support.everhour.com/article/302](https://support.everhour.com/article/302-how-to-install-everhour-browser-extensions-on-microsoft-edge)).

### 5.4 Take a lap around the web app

Log into [my.everhour.com](https://my.everhour.com) once and find:

- **Projects** — the list of clients. Confirm you can see the clients you'll be working on. (If a
  client you're assigned to is missing, tell your PM — every client should have a matching
  project.)
- **My Timesheet** (or "Time") — your own personal log, day by day.
- **Reports** — you generally won't need this as a new hire (PMs and admins use it more), but it's
  where totals live if you're ever asked to double-check something.

That's it — day-one setup is done.

---

## 6. The daily habit — step by step

This is the part you'll do dozens of times a week. There are two ways to log time: a **live
timer** (start it, do the work, stop it) and a **manual entry** (type in a number after the fact).
Use whichever fits the moment — Everhour doesn't care which one you use, and both count exactly
the same on the suite side.

### 6.1 Starting a live timer (the normal case)

1. Open the Everhour extension popup (or the web app).
2. Pick the **project** — this is the client you're about to work on.
3. Pick the **task** — the Everhour copy of your Task-board item (see §4). If you're doing
   general/non-task-specific work for that client, some teams allow logging straight against the
   project with no task — check with your PM if that's expected of you.
4. Click **Start**. The extension icon changes to show a timer is running, and the popup shows
   the live count.
5. Do the work.
6. When you switch to something else — a different client, a different task, or you're stepping
   away — click **Stop** (or just start a new timer; Everhour stops the old one for you
   automatically when you start a new one).

**Why it matters:** a live timer is the most accurate record there is — no guessing later "was
that 45 minutes or an hour?" It's the best habit to build, especially for focused, single-task
work.

### 6.2 Logging time after the fact (manual entry)

You'll forget to start the timer sometimes. That's fine — don't skip logging the time, just add it
manually:

1. Open **My Timesheet** in the web app (or the extension's day view).
2. Find the day and the project/task row (or add a new row if it isn't there).
3. Type in the number of hours (e.g., `1.5` for an hour and a half).
4. Confirm/save.

**Why it matters:** a missing entry isn't neutral — it looks like zero time was spent, which
understates that client's real cost and makes your utilization number look artificially low (like
you had room for more work when you didn't). Log it even if it's a rough estimate; a good estimate
logged is far better than nothing logged.

### 6.3 Switching tasks mid-day

Just start the new timer — you never have to remember to stop the old one first, Everhour handles
the handoff. But get in the habit of glancing at the extension icon before you start something
new; if it shows a timer already running against yesterday's task, you probably forgot to stop it
at the end of the day (see §6.6).

### 6.4 Logging non-client / internal time

Team meetings, training, internal admin, and other overhead still count toward *your* utilization
number even though they don't belong to a client — they just shouldn't be logged under a client's
project. Ask your PM which project or category the team uses for this (many teams keep a dedicated
"Internal" project for exactly this reason). The important thing: **don't leave internal time
untracked, and don't log it under a client by mistake** — the second one quietly inflates that
client's real cost.

### 6.5 Fixing a mistake

Everyone logs something wrong eventually — wrong project, wrong day, wrong duration. In **My
Timesheet**, click into the entry and edit or delete it directly; there's no approval step and no
need to ask permission. Fix it as soon as you notice — the sooner it's corrected, the less likely
it's already been pulled into that day's sync (§7).

### 6.6 End of your work session

Before you close your laptop: check the extension icon. If a timer is still running, stop it — a
timer left running overnight logs hours you didn't actually work, which is the single most common
Everhour mistake. A quick end-of-day scan of **My Timesheet** against what you remember doing is
worth the 60 seconds.

### 6.7 Billable vs. non-billable

Some entries have a billable toggle. If your role involves marking this, your PM will tell you the
convention to follow — as a new hire, default to leaving it as your team's standard setting unless
told otherwise. (Under the hood, the suite currently *captures* this flag but doesn't yet split it
into separate reporting — so getting it exactly right isn't yet mission-critical, but forming the
habit correctly now means it's ready the day it does matter.)

---

## 7. What happens after you log time (and why it's worth doing right)

You never have to trigger anything — once a day, the suite quietly pulls the whole team's Everhour
entries and turns them into things people actually look at:

| Where it shows up | What it looks like | Why it exists |
|---|---|---|
| **On the task itself** (Task board, task drawer) | "Estimated 3h · Actual 4.5h" | Lets a PM see at a glance which tasks are running over, and makes next month's estimates more honest. |
| **Client workspace → Time card** | A rolling total of hours logged for that client | Gives account managers a real read on how much time a client is actually taking, not a guess. |
| **Team / Workload page** | Your logged hours vs. your weekly capacity, as a percentage | This is how PACE (the agent that hands out and chases work) knows who has room for more and who's already stretched — so new work goes to someone with capacity instead of piling onto whoever's already full. |
| **Recipe Engine → Actual margin** (client task-plan page) | A real profitability number next to the budgeted one, once an admin has entered a cost rate | Turns "we think this client is profitable" into "we know," which is what the whole monthly budget-allocation process is trying to get right. |

None of this is about watching any one person — it's the difference between the agency planning
capacity and budgets off guesses versus off what actually happened. Accurate logging is what makes
every one of those numbers trustworthy.

---

## 8. Common mistakes (and the fix)

| Mistake | What it causes | Fix |
|---|---|---|
| Timer left running overnight/over a break | Inflated hours on a task and on your utilization | Stop it as soon as you notice; edit the entry down to the real duration (§6.5). |
| Logging time under the wrong client's project | That client's cost looks wrong; your real client's cost looks understated | Edit the entry, move it to the correct project. |
| Creating a brand-new task in Everhour instead of using the mirrored one | Your hours land on a task the suite doesn't recognize, so they never show up on the real task | Search for the existing (mirrored) task by its Task-board name instead; ask your PM if it's missing. |
| Tracking time on a subtask/checklist line | Same as above — only top-level tasks get a mirrored Everhour copy | Track time on the parent task. |
| Not logging internal/admin time at all | Your utilization looks artificially low, like you have more capacity than you do | Log it under your team's internal/non-client category — don't skip it. |
| Waiting days to log time, then guessing | Estimates get worse, not better, over time | Log daily, even roughly — same-day memory beats end-of-week reconstruction. |
| Assuming Everhour is where you manage your to-do list | You'll miss due dates, statuses, comments — none of that lives here | The Task board (`/clients/:id/tasks`, `/my-tasks`) is where task management happens. Everhour is the clock, not the list. |

---

## 9. Quick reference card

**Every work session:**
1. Open the extension → pick the client's project → pick the mirrored task → **Start**.
2. Switching work? Just start the next timer — no need to stop the old one first.
3. Forgot to start it? Log it manually in **My Timesheet** the same day, don't skip it.
4. End of day: check the icon — no timer should still be running.

**Once, on day one:**
- Confirm your Everhour account exists and you can log in.
- Confirm your admin has linked your Everhour account to your suite profile (Team page).
- Install + pin the Chrome extension, sign in.

**Never:**
- Create your own tasks in Everhour.
- Log client work under the wrong project.
- Manage your actual to-do list from inside Everhour — that's the Task board.

---

## 10. FAQ

**Do I need to track every minute of my day?**
Track your actual working time on client and internal work. You don't need to account for a
bathroom break down to the second — the goal is an honest, close-enough picture, not a stopwatch
on your whole life.

**What if I genuinely don't remember how long something took?**
Log your best honest estimate rather than nothing. Nothing reads as zero, which is worse than an
approximate number.

**My task isn't in Everhour yet — what do I do?**
Give it a little time (the copy is created automatically when the task is made, but you may be
looking before it's synced), then check you're searching the right client's project. Still missing
after that? Ask your PM — it may be a subtask (which never gets mirrored) or an older task that
predates the sync.

**Can I see my own utilization number?**
Ask your PM — the Team/Workload view is generally a PM/admin surface, but there's no reason you
can't ask how you're tracking.

**Does marking something "done" in Everhour close it out on the Task board?**
No. They're not connected in that direction. Complete the task on the Task board itself.

**Is this used to check up on me?**
It's used to plan — client cost, team capacity, and estimate accuracy. Nobody is watching a live
feed of your timer. Log honestly and it does its job quietly in the background.

---

*Questions this guide doesn't answer? Ask your PM or admin — Everhour setup (accounts, project
mapping, the suite link) is admin-side and usually a two-minute fix.*
