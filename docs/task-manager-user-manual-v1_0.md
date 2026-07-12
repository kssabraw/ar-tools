# AR Tools — Task Manager User Manual (v1.0)

*Last updated 2026-07-12. This is the operator's guide to the native task board that replaced Asana — how work flows, what moves automatically, who does what, and how to fix the things that commonly go sideways. Written for the whole team: VAs, PMs, and admins. Where a section is admin-only it says so.*

---

## 1. The one-paragraph version

Every client has a **task board**. Each month, the board fills itself with that client's recurring tasks, pre-assigned to the right person. A VA does the work and ticks off the checklist items as they go — and **the board moves the cards by itself**: starting a task moves it to *In Progress*, finishing the work moves it to *In QA*, publishing content closes it. The PM watches over the whole thing with the help of two agents (**PACE** keeps delivery moving, **SerMaStr** advises on strategy), and a **Weekly Pulse** writes a ready-to-send client update every Monday. The goal: your team does the actual SEO work and almost nothing else — the admin runs itself.

**What's live right now:** native board, monthly auto-generation, auto-tick, stage auto-advance, all four auto-producers, PACE (daily chase plan), Weekly Pulse.
**Not yet built:** the QA agent (auto-checks work in *In QA*) and the Inbox Agent (auto-detects client approval). Until those land, two card moves stay manual — see §4.

---

## 2. Where to find everything

| Thing | Where |
|---|---|
| A client's board | Client workspace → **Tasks** card → `/clients/:id/tasks` |
| Your own to-dos across all clients | Sidebar → **My Tasks** → `/my-tasks` |
| The monthly template for a client | Client workspace → **Asana Tasks** card → *Monthly task template* → `/clients/:id/asana-tasks` |
| Team capacity + who's overloaded | **Workload** page |
| The global standard-task list + default checklists | Sidebar → **Task Library** → `/asana/task-library` |
| Client update to send | Client workspace → **Weekly Pulse** panel |
| PACE (delivery agent) | Your team Slack channel + the assistant page |
| SerMaStr (strategy agent) | `/assistant` page + Slack |

---

## 3. The workflow — how a task flows

### 3.1 The status pipeline

A task moves left-to-right through six workflow statuses, plus two exception statuses that sit off to the side:

```
Not Started → In Progress → In QA → Sent to Client → Client Approved → Completed
                                                                    (exceptions:  Blocked · In Review)
```

| Status | Means | Category |
|---|---|---|
| **Not Started** | Nobody has touched it yet | not_started |
| **In Progress** | Someone is actively working on it | in_progress |
| **In QA** | The work is done and waiting to be quality-checked | in_progress |
| **Sent to Client** | QA passed; it's with the client for approval | in_progress |
| **Client Approved** | The client said yes | in_progress |
| **Completed** | Shipped / published / logged — done | done |
| **Blocked** *(exception)* | Can't be started yet — waiting on something external | blocked |
| **In Review** *(exception)* | The client rejected it; it needs redoing | in_progress |

**Why Blocked and In Review are "exceptions," not steps:** they're not part of the normal flow — they're detours. A human deliberately puts a task into one of them, and **the automation never moves a task into or out of an exception status**. If a task is Blocked or In Review, it stays there until a person moves it. (This is intentional: the system should never "un-block" something or decide a client's rework is done.)

### 3.2 What the pipeline replaced

In Asana there was one coarse status field, so the team tracked progress by ticking checklist boxes ("Citations QA'd", "Sent for approval", etc.). The native board has a real pipeline, so **the status column is now the single source of truth** and most of those checkboxes tick themselves (see §4). You should think in terms of *dragging the card* (or letting it drag itself) — not hand-ticking process boxes.

---

## 4. Automation — what moves by itself

This is the heart of the system. Five things happen automatically. Every automatic action is written to the task's **activity feed** (open the task → Activity), so you can always tell what the system did versus what a person did.

### 4.1 Auto-tick — checkboxes tick themselves when a card moves forward

When a card moves to a later status, the system ticks every checklist **process marker** that stage implies. You never hand-tick "Sent for approval" again — moving the card to *Sent to Client* ticks it for you.

| Move the card to… | Auto-ticks these markers |
|---|---|
| **In Progress** | "…Started", "…Created", "…Generated", "…Ordered", "…Received" |
| **In QA** | *(nothing new — QA hasn't happened yet)* |
| **Sent to Client** | "…QA'd", "…Complete", "Sent for approval", week-numbered starts ("Started (week 2)") |
| **Client Approved** | "Client approved" |
| **Completed** | "…posted", "…published", "…scheduled", "added to website" |

**Two rules that keep it honest:**
- **Late-never-early.** A box only ticks once its stage has *certainly* happened. "QA'd" ticks when the card moves *past* QA (to Sent to Client), not when it enters In QA — because entering In QA doesn't mean QA passed.
- **"Added to deliverables sheet" is NEVER auto-ticked.** That stays the PM's manual reminder until the deliverables automation is built. It's the one box a human always ticks.

Auto-tick **never un-ticks**. Dragging a card backward leaves all boxes as they are.

### 4.2 Stage auto-advance — the card moves itself forward

The reverse of auto-tick: the events the system already sees push the card forward, so you rarely drag at all.

- **Start-on-touch:** the first time anyone touches a *Not Started* task — ticks a checklist item, leaves a comment, or attaches a file — it moves to **In Progress** automatically.
- **Work-done → In QA:** when you tick the **last real work item** on the checklist, the card advances to **In QA** on its own.

**"Real work item" vs "process marker":** the system knows the difference. A *work item* is the actual deliverable — a page name ("Terracotta Tile Roof Restoration Melbourne"), a coordinate set, a blog topic. A *process marker* is a status-like step ("QA'd", "Sent for approval"). **Only real work items steer the card.** So you tick your way through the actual pages/items, and when the last one is done, the card slides to In QA — the process markers get ticked automatically by auto-tick, not by you.

Guardrails: auto-advance only ever moves a card *forward*, only from Not Started or In Progress, never from an exception status, never on a completed task. A manual drag always works too and does the same cascade.

### 4.3 Auto-producers — tasks that create and close themselves

Four kinds of task appear on the board without anyone creating them, and close themselves when their trigger resolves:

| Producer | Creates a task when… | Closes it when… |
|---|---|---|
| **Rank drop** | A tracked keyword drops (rank alert opens) | The alert resolves (ranking recovers) |
| **Maps alert** | A local-pack / geo-grid alert opens | The alert resolves |
| **Action plan** | The reoptimization planner surfaces a top-priority action | The action leaves the plan |
| **Content run** | A blog/service page finishes generating → "Review & publish" | The page is published |

These land in the client's current-month section, unassigned, for the PM to triage. A deindex-risk drop comes in as "Confirm indexing" instead of "diagnose."

### 4.4 Completion

Completing a top-level task (or dragging it to *Completed*) ticks every remaining process marker (except deliverables) and marks it done. Content tasks also complete themselves automatically when the page is published.

### 4.5 The scoreboard: who drives each transition

| Transition | Driver today |
|---|---|
| Not Started → In Progress | **Automatic** (first touch) |
| In Progress → In QA | **Automatic** (last work item ticked) |
| In QA → Sent to Client | **Human** (until the QA agent is built) |
| Sent to Client → Client Approved | **Human** (until the Inbox Agent is built) |
| Client Approved → Completed | **Automatic** for content (on publish); human otherwise |

So today a VA's job on a normal task is: **do the work, tick the real items.** The card handles its own early journey; the only manual drags left are the QA pass and the client-approval step.

---

## 5. The monthly cycle

### 5.1 How the month gets set up

Each client has a **Monthly task template** — the list of recurring tasks that client gets every month (they vary client to client). On the monthly generation day, the system creates that client's new "`<Month> <Year>`" section and fills it from the template: each task pre-assigned to the usual person, with its standard category, hours, and default checklist copied in.

This is **idempotent** — if it runs twice, it fills gaps rather than duplicating. And a client can't have two template tasks with the same name (the editor blocks it), so no task can double-generate.

### 5.2 Editing a client's template

Client workspace → **Asana Tasks** card → *Monthly task template*. Add/remove tasks, change the assignee. Do this when a client's recurring scope changes. Three clients (Nova Life Peptides, WheelHouse Online, Ubiquitous) have **no template yet** — they were never on Asana — so they generate nothing until someone builds their template here.

### 5.3 Editing the default checklists

Sidebar → **Task Library** → expand a task → edit its checklist. This is the checklist the monthly generator stamps onto every new instance of that task, for every client. Keep these **generic** (process steps + placeholders), never client-specific.

---

## 6. The agents (short version)

### 6.1 PACE — the delivery agent

PACE watches the board and keeps work moving. Once a day it posts **one Chase Plan** to your team Slack channel: a short numbered list of proposed actions (reassign this, this is slipping, this is stale, unblock that, nudge so-and-so). **Nothing happens until a human replies** `yes` (approve all) or `yes 1,3` (approve specific items). If a task sits stuck for **3 business days**, PACE escalates once, publicly, in the channel. PACE proposes; it doesn't act on its own — that's deliberate.

### 6.2 SerMaStr — the strategy agent

Ask SerMaStr (the `/assistant` page or Slack) anything about a client's search performance — "how's Acme doing?", "what should we improve?". It answers from live suite data and cites the SOPs. It can also take actions (run a scan, rebuild a plan, edit a campaign) — paid/impactful ones are confirm-gated with a "reply yes". SerMaStr advises; **PACE executes**.

### 6.3 Weekly Pulse — the client update

Every Monday, each client's workspace gets a **Weekly Pulse** — a short, ready-to-send "here's what we did last week and what's next" update, written for the client. A staff member **copies it, personalizes the greeting, and sends it** (nothing is ever auto-sent). Toggle between **Email** (narrative) and **List** (at-a-glance) views. A light week never says "nothing to report" — it leads with the always-on monitoring work.

---

## 7. Roles — what each person actually does

**VA (does the work):**
1. Open **My Tasks** → work your Overdue / Today / This week buckets.
2. On each task: do the actual work, tick the real work items as you finish them.
3. That's it — the card moves itself to In Progress and In QA. You only drag manually for QA hand-off if needed.
4. If you're stuck waiting on something external, drag the task to **Blocked** (and it'll show in PACE's radar).

**PM (keeps it moving):**
1. Each morning, read PACE's Chase Plan in Slack and reply `yes` / `yes 1,3`.
2. Triage the unassigned producer tasks (rank drops, content reviews) onto people.
3. Tick "Added to deliverables sheet" as deliverables are logged (until that's automated).
4. Move QA-passed tasks to *Sent to Client*; move client-approved ones to *Client Approved*.
5. Send the Weekly Pulse to each client.

**Admin (owns the system):**
- Manages statuses/categories, templates, the Task Library, team capacity, and the feature flags (§9).
- Approves PACE's senior-gated proposals and SerMaStr's senior proposals.

---

## 8. Troubleshooting — common issues & fixes

### 8.1 "I started a task but it didn't move to In Progress"
- **Is it a subtask?** Auto-advance only applies to top-level tasks, not checklist items.
- **Is it already past Not Started, or in Blocked/In Review?** Auto-advance only fires from *Not Started*, and never from an exception status.
- **Did you actually touch it?** The trigger is a checklist tick, a comment, or an attachment. Just opening the task doesn't count.
- **Always-works fallback:** drag the card to In Progress manually.

### 8.2 "A task jumped to In QA before I was finished"
This means the **last real work item got ticked**. Usually that's correct. If a work item was ticked prematurely:
- **Un-tick it** and drag the card back to In Progress. It will **not** immediately re-advance — Rule B only fires on a *new* tick, so backward moves are safe.
- If the item that's ticked is actually a process marker (not real work), the card shouldn't have advanced on it — check the Activity feed to see what triggered the move, and tell an admin if the checklist has a mislabeled item.

### 8.3 "Checkboxes ticked themselves / too many got ticked"
That's **auto-tick** reacting to a forward status move — expected. If *too many* ticked, the card was moved too far forward. Auto-tick never un-ticks, so:
- Drag the card back to the correct status (this won't un-tick anything), then **manually re-open** any checklist item that shouldn't be done.
- Check Activity → an `auto-ticked` entry shows exactly which boxes the system ticked and when.

### 8.4 "A client's monthly tasks didn't generate"
- **No template:** Nova Life Peptides, WheelHouse Online, and Ubiquitous have no template — build one in the Asana Tasks card. For any other client, check its *Monthly task template* isn't empty.
- **Generation day hasn't passed yet** for this month.
- **Fix on demand:** open the client's Tasks page → **Generate this month**. (Safe to click — it's idempotent, won't duplicate.)

### 8.5 "Duplicate tasks appeared"
This shouldn't happen — monthly generation is idempotent and templates can't hold duplicate names. If you see dupes, they're almost certainly one **producer** task plus one **template** task for the same work (e.g., a manual "GBP Blast" and an auto one) — that's two different sources, not a bug. Trash whichever you don't want.

### 8.6 "A task is stuck in Blocked (or In Review) forever"
**By design, the system will never move it out** — a human parked it there. When the blocker clears (or the client's rework is done), **a person must drag it back** into the workflow. PACE will keep flagging long-stuck Blocked tasks in its chase plan so they don't get forgotten.

### 8.7 "PACE didn't post anything today"
- **"All clear" is normal** — if there's nothing to chase, PACE posts nothing. A quiet board is a good sign.
- Check it's posting to the right channel (it uses your main SerMaStr channel — no dedicated PACE channel is set).
- If you expected an escalation: escalations fire at **3 business days** of no movement, not sooner.

### 8.8 "I replied 'yes' to PACE but nothing happened"
- Reply **in the same thread** as the chase plan.
- The plan is **superseded daily** — replying to yesterday's plan won't run it; act on today's.
- Confirmations are **actor-bound** — the person who replies should be a team member with the right role for those items (some actions are senior-gated).

### 8.9 "The Weekly Pulse looks thin / generic / blank"
- The client-facing narrative is generated by AI; if that call fails it **falls back to a plain bullet list** — still correct, just less polished. Hit **Regenerate**.
- **Task lines fill from completed native tasks** — a client with little completed work that week will lean on the always-on monitoring copy. That's intended (we never say "no deliverables").
- It's **never auto-sent** — if a client didn't get it, a staff member needs to copy-paste and send it.

### 8.10 "A content task didn't close when we published"
- The auto-close fires on the **publish action** in the app. If the page was published outside the app (or the run didn't actually reach "published"), the task won't close — complete it manually.

### 8.11 "A producer task won't go away even though the issue is resolved"
- Producer tasks close when their **underlying signal** resolves (the rank alert clears, the action leaves the plan). If a task is stale but the signal is genuinely gone, just **trash it** — trashing releases its key so it won't block a future one.

### 8.12 "Someone changed/deleted a status and the board looks wrong"
- Statuses are **admin-editable** (config → statuses). If the linear order or an exception status got moved, an admin can fix it there. The safe order is the one in §3.1. Keys and categories drive the automation — don't change a status's **key**; relabeling is fine.

### 8.13 "Tasks are unassigned and nobody's picking them up"
- Producer tasks land unassigned on purpose (PM triages them).
- WheelHouse IT's imported tasks came in unassigned (Asana had no assignee). Assign them in the board or set assignees on the template so next month's are pre-assigned.
- PACE flags untriaged/unassigned tasks in its chase plan after a short grace period.

### 8.14 "My Tasks is showing someone else's work / not mine"
- My Tasks opens on your linked team member if your suite login is linked to an Asana member gid (admin does this on the Workload page). If unlinked, it defaults to the first member — use the **"viewing as"** picker to select yourself, or ask an admin to link your account.

---

## 9. Admin reference — flags & where things live

*(Admin only. These are environment variables on the PLATFORM service in Railway. Flip with care.)*

| Flag | State | Controls |
|---|---|---|
| `NATIVE_TASKS_ENABLED` | **on** | The whole native board is live; Asana is read-only backstop |
| `PACE_ENABLED` | **on** | PACE persona + daily digest |
| `PACE_INITIATIVE_ENABLED` | **on** | PACE's Chase Plan, chase loop, triage, rebalancing, slip forecasting |
| `TASK_PRODUCER_CONTENT_RUN_ENABLED` | **on** | "Review & publish" tasks on content completion |
| Rank-drop / Maps-alert / Action-plan producers | **on** (default) | The other three auto-producers |
| `PULSE_ENABLED` | **on** (default) | Weekly Pulse generation |
| `PACE_DAILY_BRIEF_PUSH` | **off** | Per-person morning DM briefs (needs Slack `im:write` scope first) |
| `PACE_SLACK_CHANNEL` | **not set** | PACE posts to the default SerMaStr channel; set to give PACE its own |

**Data model, for reference:** statuses live in `task_statuses`, categories in `task_categories`, per-client templates in `asana_client_task_templates`, the global standard list in `asana_task_library`, default checklists in `task_library_subtasks`, and every task/subtask in `tasks` (subtasks are rows with a `parent_task_id`). The automation logic lives in `services/task_service.py` (auto-tick, auto-advance), `services/task_producers.py` (producers), and `services/task_monthly.py` (generation). Authoritative build doc: `docs/modules/in-app-task-manager-prd-v1_0.md` (see §20 for the automation + the deferred Inbox Agent).

---

## 10. What's coming next

- **QA agent** — will watch the *In QA* column, run automated quality checks (the 8-engine page scorer, structure eval, citation checks, content-quality gates) plus an AI review, post its findings as a task comment, and — once trusted — advance passing work to *Sent to Client* and bounce failures back to *In Progress* with notes. This automates the first of the two remaining manual drags.
- **Inbox Agent** *(deferred — needs mailbox access)* — will read client replies, detect approvals, and advance *Sent to Client → Client Approved* automatically; route revision requests into *In Review* with the client's feedback attached; and hand client questions to SerMaStr to draft replies. This automates the last manual drag. It's fully spec'd in the PRD §20 and gated on granting the system read access to the reply inbox.

When both land, the pipeline is event-driven end to end and there are **no routine manual drags left** — the team does the work, and the board runs itself.

---

*Questions or something behaving unexpectedly? Check the task's Activity feed first (it shows every automatic action), then this manual's §8, then ask an admin.*
