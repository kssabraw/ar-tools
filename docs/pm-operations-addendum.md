# PM Operations Addendum — User Guide

A companion to the [Task Manager User Guide](native-task-manager-user-guide.md)
and the [PACE & QA User Guide](pace-qa-user-guide.md). Those two get a new
teammate operating the board and talking to the agents. This one is for
whoever is actually **running delivery** — a PM, a lead, an owner covering
for one — and covers the judgment those two guides deliberately leave out:
who has room for more work, why a task's name can make PACE (or you) guess
wrong, when to wave a Chase Plan through versus stop and look, and what
happens once PACE escalates something publicly.

> **Read the other two first.** This guide assumes you already know what a
> section, a status, and a checklist are (guide 1), and what PACE's daily
> digest, Chase Plan, and follow-through episodes are (guide 2, Part 1). It
> doesn't repeat those mechanics — it tells you what to *do* with them.

Every number and example below is pulled live from the production board as
of **2026-08-29**, not invented — some of it is a genuinely messy real
situation, left in on purpose because "the board is a bit of a mess" is
exactly the state this guide is for.

---

## Terms you'll see

On top of guide 1's and guide 2's terms:

| Term | What it means here |
|---|---|
| **Weekly capacity** | A team member's `weekly_hours` — how much work they're expected to carry per week. Set on the Workload page. |
| **Open hours** | The sum of estimated hours across every open (not completed, not trashed) top-level task currently assigned to someone — their whole visible backlog, not just this week's due work. |
| **Skill / competency** | A category (Content, Link Building, GBP Authority, Strategy) a member is marked able to do. Set on the Workload page's Skills editor. |
| **Generalist** | A member with **no** skill rows at all — eligible for *any* category. The default for a brand-new member, and, as you'll see below, the default for this whole team today. |
| **Eligible** | For a given client, the members allowed to be auto-assigned that client's work at all (`asana_client_projects.auto_assignee_ids` — empty means everyone's eligible). Separate from skill. |
| **Held** | Placement's fallback when nobody in the eligible/skilled pool has room: the task is left unassigned on purpose, with a note on its Activity log explaining why. Not an error. |
| **Rebalance** | A Chase Plan proposal that moves a **not-yet-started** task off someone overloaded and onto someone with room. Never touches in-flight work. |
| **Triage** | A Chase Plan proposal that fills in a task's missing due date, category, or hour estimate from the Task Library — never a guess, only what the Library or the section actually has on file. |
| **Slip** | A task PACE's forecaster thinks will miss its due date, flagged *before* it's actually late. |
| **Episode** | (from guide 2) The clock on one flagged problem. Below, you'll see what an episode looks like after it's been open for weeks. |

---

## Part 1 — Capacity & workload management

### Where it lives

The **Workload** page (sidebar) is command central for this. Top to bottom:
a **Delivery report** card (throughput, overdue/stuck counts, who's over
capacity — the same numbers PACE's own delivery-report action reads), a
per-member **workload row**, the **Team & capacity** editor, and the
**Skills & competencies** editor. Nothing here is agent-only — it's the same
page a human PM would use to eyeball who's drowning.

### What "open hours" actually is — and isn't

Each member's row shows something like *"208h open · 104 tasks · 40h/wk"*.
That **208h** is not "208 hours due this week" — it's the sum of estimated
hours across **every open task currently assigned to them**, due date or no
due date, this month's section or last month's. It's their whole visible
backlog, not a weekly commitment.

A member is flagged **Overloaded** for one of two separate reasons, and the
row's flag text tells you which:
- **A single day's due-work exceeds their daily capacity** (weekly hours ÷ 5
  workdays) — too much is piling up on one date.
- **Their whole open backlog exceeds roughly two weeks of their weekly
  capacity** (config `asana_workload_backlog_weeks`, default 2) — even with
  nothing due tomorrow, they're carrying more than they could plausibly work
  through soon.

That second threshold is the one that matters for the numbers below, and
it's the reason a very large "open hours" figure doesn't automatically mean
"panic" — it partly reflects how much of the board has no due date yet. It
does mean the backlog needs *some* attention.

### A real snapshot — and the two traps it shows

The live roster today:

| Member | Weekly capacity | Open hours (all clients) | Suite login linked |
|---|---|---|---|
| Ivy Gervacio | **7h/wk** | 68h | No |
| Kyle Sabraw | 40h/wk | 68h | Yes |
| Minda | 40h/wk | 208h | Yes |
| Ryan Maizis | 40h/wk | 68h | Yes |

Two things worth stopping on:

**Trap 1 — a capacity number that doesn't match the person.** Ivy's weekly
capacity is set to **7 hours** — presumably because she's genuinely
part-time, but with 68 open hours against a 7h/wk cap she reads as roughly
**10× over** on paper. That's not a crisis by itself (see above — it's
backlog, not this-week work), but it has a real mechanical consequence:
`pick_assignee` (the placement engine both PACE and the auto-assign button
use) ranks candidates by *remaining* weekly capacity, and Ivy's remaining
capacity is now deeply negative. She will effectively never be picked for a
new task until either her open backlog drops or her weekly-hours figure is
corrected to reflect her real availability. **If a number like this looks
wrong for the person, fix it here first** — it silently removes someone from
consideration for new work, which looks like "PACE keeps skipping Ivy" when
it's really "Ivy's capacity is misconfigured."

**Trap 2 — a genuine overload with nowhere for the work to go.** Minda is
carrying **208h** against a 40h/wk cap (over 5× the backlog threshold) — a
real, not a config, overload. This is the one the Rebalancing engine (below)
tries to fix automatically, but only within what the team can actually
absorb: with three other members and Ivy effectively capacity-locked, there
may simply not be enough spare room to redistribute Minda's whole backlog
away. A rebalance proposal will move what it can and say so honestly
("frees 4h of 9h over") rather than pretending it solved it.

### Skills — today, everyone is a generalist

The Skills & competencies editor lets you mark which of the four categories
(Content, Link Building, GBP Authority, Strategy) each member can take, with
a ★ for their primary one. **As of today, nobody on the roster has a single
skill row set** — every member is a **generalist**, eligible for any
category. That's not a bug; it's the documented day-one default, and with a
four-person team it may be exactly right. The moment it stops being right
(someone should only get GBP Authority work, or someone's the only one who
should touch Strategy tasks) — this is where you say so. Until then,
placement decisions come down entirely to **who has room**, not who's
"supposed" to do what kind of task.

### How a placement decision actually gets made

Whether it's the auto-assign button, PACE's `assign_task`, or the approval
hook on an approved SerMaStr proposal, the same engine runs:

1. Start from **active members**, narrow to the client's **eligible** list
   (empty list = everyone), narrow again to whoever's **skilled** for the
   task's category (or every generalist, if nobody's specialized in it).
2. **Rank** the survivors by remaining weekly capacity — most room first —
   then by whether it's their ★ primary category, then a stable tie-break.
3. **Pick the top one** — unless even they don't have enough remaining
   capacity for this task's estimate, in which case the whole pool is
   **held**: nothing gets force-assigned to an over-capacity person. A
   `placement_deferred` note lands on the task's Activity log explaining
   why, and it joins the digest's "unassigned" count.

That "hold" outcome is common right now: **106 tasks are currently sitting
in an open "unassigned" episode** portfolio-wide (see Part 3) — that's the
scale of what a four-person team, one of whom is capacity-locked, can't
currently absorb on its own. Some of that is real headroom you need to plan
for (more hours, another hire); some of it will clear the moment the
duplicate-name problem in Part 2 stops making individual tasks unreachable
by name.

### Rebalancing — PACE proposing the fix, not just the fact

When the daily workload check flags someone overloaded, the rebalance
generator looks at their **not-yet-started** tasks only (anything already
in progress is never yanked mid-work), and tries to move the smallest ones
first to whoever has genuine spare room — same skilled/eligible/least-loaded
pool as above, just excluding the overloaded person. Each move becomes one
line in the Chase Plan:

> *Rebalance: move "Location page — Inner West" (4h) from Minda (520%) → Kyle Sabraw*

If it can only place some of the overage, it says so ("frees 4h of 9h
over") instead of quietly declaring victory. **This is where your judgment
adds something the algorithm can't**: it will only ever propose a move to
someone who genuinely has room *today* — it has no idea that Kyle is about
to go on leave, or that a particular client's work really shouldn't go to
whoever's newest. Read a rebalance line before you `yes` it, same as any
other Chase Plan item.

### The two admin-only capacity tools

- **Auto-assign unassigned** (the button next to *Generate this month*, on
  a client's Tasks page — guide 1, Step 2) staffs every currently-unassigned
  monthly-template task for that one client through the exact same engine,
  in one click. It's idempotent — it never overwrites an existing
  assignment, so running it twice is harmless.
- The same thing is available as an API call
  (`POST /clients/{id}/tasks/autoplace-unassigned`) if you ever need it
  scripted rather than clicked — same engine, same guardrails, admin-only
  either way.

---

## Part 2 — Task Library curation & duplicate-name hygiene

### Why a duplicate name is a real problem, not a cosmetic one

Every time you (or PACE) refer to a task by name — "reassign the GBP Blast
task," "PACE, unblock Map Embeds on First Class Roofing" — the resolution
rule is the same everywhere: match against that client's **currently open**
tasks, exact name wins outright, otherwise anything containing the text you
typed. If **two open tasks share the exact same name**, being precise
doesn't help — typing the full, exact name still returns both. The system
won't guess which one you mean; it lists them and asks.

That's the right behavior for safety. But it means **a duplicate task name
is a standing tax on every future reference to that task** — by you, by a
teammate, and by PACE's own daily Chase Plan and episode-chasing, which hit
the exact same ambiguity a human would.

### A duplicate causing a real problem, right now

`IHBS` currently has **five** open tasks all named exactly **"Map Embeds"**
— this is the same example guide 2 uses to explain the ambiguity mechanic,
because it's the most extreme live case. It's not a one-off:
`Henson Architect` has five open **"DAS"** tasks and five **"Blog Post
Title"** tasks; `EML Calibration` has five **"4x DAS"**; `First Class
Roofing` and `ZDSCS` both have multiple open **"Service Silo"** /
**"Service Page Silo"** tasks. In every one of these, referring to the task
by its name alone — which is how the Task Library names it, how "Generate
this month" creates it, and how a person naturally types it — is ambiguous
the instant a second one is still open.

Here's what that looks like landing in an actual Chase Plan (from this
morning, 2026-08-29):

> **PACE chase plan — 3 proposed actions**
> 1. Nudge Minda — "Citations Audit" overdue — remind Minda — _Henson Architect_
> 2. Nudge Minda — "Cloud Stack" overdue — remind Minda — _Parallel Accounting_
> 3. Nudge Kyle Sabraw — "Press Release" overdue — remind Kyle Sabraw — _ZDSCS_
> • ⚠️ Nudge Minda — "Service Silo" overdue — remind Minda — "Service Silo" matches 2 tasks — which one?
>   • Service Silo
>   • Service Silo
> • ⚠️ Nudge Minda — "GBP Blast" overdue — remind Minda — "GBP Blast" matches 2 tasks — which one?
>   • GBP Blast
>   • GBP Blast

Both flagged items are real, current work on Henson Architect that PACE
*wants* to nudge Minda about — but can't, because the name alone doesn't
say which one. Pulling the actual rows shows why: Henson Architect has one
"GBP Blast" sitting `not_started` with no due date in the August 2026
section, **and a second, separate "GBP Blast"** `in_progress`, due
2026-08-31, also filed under August 2026 — two live tasks, same name, same
month, same client. That plan has looked almost identical for **six
straight days** (2026-08-24 through today) precisely because nobody has
resolved which "GBP Blast" is which — the flag just keeps re-appearing, and
the real, addressable nudges (items 1–3) are the only part of the plan that
actually moves.

### What to actually do about it

1. **When you see a flag like this, don't skip it — go look at the client's
   board.** Open the client's Tasks page, filter or scroll to the ambiguous
   name, and read the two (or five) rows: due date, status, which section.
   Usually one is genuinely done in every way but the checkbox (complete or
   trash it), one is stale leftover from a prior month that should never
   have stayed open (same), or they're both real and one needs a
   distinguishing rename.
2. **If a task legitimately needs to persist as a separate, addressable
   thing, rename it to say so** — append the month, the specific keyword, or
   whatever makes it unique in a glance ("GBP Blast — carryover from July").
   Renaming a task **detaches it from the Task Library's default checklist**
   for that name (guide 1, Step 7) — if you rename something that still
   needs its standard checklist, re-add it under the new name, or just leave
   the rename until the checklist's already been worked through.
3. **Prefer closing the loop over letting it pile up.** "Generate this
   month" is safe to re-run and never duplicates — but it also never
   *deduplicates* an old unfinished task against a fresh one of the same
   name. That reconciliation is a human call, every month, for any
   recurring task name that tends to run long.
4. **A light weekly habit pays for itself here**: scan for any client
   carrying the same task name open across more than one section. It's a
   two-minute check that keeps every future PACE nudge, every teammate's
   typed request, and your own search from hitting the same wall.

---

## Part 3 — Chase Plan judgment & triaging a messy board

### What's usually safe to wave through

Most Chase Plan items are low-risk by construction: a **nudge** just pings
someone, a **triage** fill-in only ever writes a value the Task Library or
the section already had on file (never a guess), and most **reassigns**
move a not-yet-started task between two people who are both actually
capable of the work (today, that's everyone — see Part 1). Replying bare
`yes` to a normal day's plan is a reasonable default.

### What's worth a second look before you approve

- **A rebalance move** — is the target really free, or about to not be?
  (PACE can't see PTO, a second client's fire drill, or "actually give
  Ivy's stuff a wide berth this week.")
- **A slip fix that moves a due date** — does the new date still work for
  the client, or does someone need to say something first?
- **Anything you don't immediately recognize** — ask PACE ("why is this
  proposed?") before confirming; it can walk the task's history for you
  (guide 2's `drill_task` capability), same as it would if you asked
  directly.

### A worked case: what the board actually looks like today

As of this morning, the portfolio has **106 open "unassigned" episodes, 68
"overdue," and 43 "stale"** — a real, sizeable backlog, and a fair stand-in
for "the board is a mess, where do I even start." Here's the actual
walk-through a PM would do:

**Step 1 — clear the noise that's blocking real signal.** The recurring
"Service Silo"/"GBP Blast" flags on Henson Architect (Part 2) have shown up
in **every single Chase Plan for six days running** without resolving,
because nobody's gone in and disambiguated the two same-named tasks. That's
not PACE failing to do its job — it's doing exactly what it's supposed to,
proposing the same fix every day until the underlying ambiguity clears.
Fixing the duplicate names (rename or close one of each pair) is the single
highest-leverage five minutes available: it turns two permanently-stuck
flag lines back into two normal, nudgeable, `yes`-able Chase Plan items.

**Step 2 — separate "genuinely overloaded" from "capacity is
misconfigured."** Minda's 208 open hours (Part 1) is a real overload the
Rebalance engine is already chipping away at, a little each day, as far as
the roster's spare capacity allows. Ivy's apparent overload is really a
7h/wk setting doing exactly what it's told — before assuming either of them
needs the same fix, check which kind of "over capacity" you're looking at.

**Step 3 — let the escalation list tell you what's actually urgent.** A
recent escalation (below) named **34 items** stuck ≥3 business days with
zero movement — that's the list to act on directly, not the daily Chase
Plan noise, because those are the ones a plan alone hasn't fixed.

**Step 4 — approve the routine stuff, then move on.** Once the duplicate
names are cleaned up and you understand the two capacity situations, the
rest of a normal day's plan — nudges, triage, the reassigns that make
sense — is exactly what `yes` is for. You don't need to re-litigate every
Chase Plan from scratch once the structural problems underneath it are
fixed.

### Selective confirms, and what "no" actually does

`yes 1,3` runs only those items; anything you don't pick is simply **not
run today** — it isn't lost, and if it's still a real problem tomorrow it
reappears in tomorrow's plan on its own. There's no separate "decline"
action to remember: silence (or picking around an item) is the decline.

---

## Part 4 — Escalations, the SerMaStr handoff, and admin-only actions

### When PACE escalates publicly

Once an episode has gone **3 business days with genuinely no movement**
(guide 2, Part 1), PACE posts one public escalation and never repeats it for
that same problem. A real one from last week:

> **PACE escalation — 34 items stuck ≥3 business days with nobody acting**
> • "Create a purpose-built page — the SERP is winnable and you don't have a strong page yet." (ZDSCS) — unassigned, no movement for 3 business days
> • "Confirm indexing: calibration company utah" (EML Calibration) — unassigned, no movement for 3 business days
> • "Diagnose & reoptimize: manufactured homes altoona pa" (UMH) — unassigned, no movement for 3 business days
> …

Notice the pattern in that list: nearly every line is `unassigned`. An
escalation this size is less "34 individual crises" and more "the placement
pool doesn't currently have room to absorb this much unassigned work" — the
same capacity story as Part 1, just now loud enough that it's a named,
public list instead of a quiet count. **What a PM actually does with this
isn't to work all 34 by hand one at a time** — it's to ask why so much work
is landing unassigned in the first place (a client with no eligible members
configured? a category nobody's marked skilled for? genuinely not enough
hours on the roster this month?), fix the structural cause, and let
placement catch up. For the individual items that really do need a person
right now, touching the task — reassigning it, commenting, changing its
status — is what resets its clock; leaving it alone means it stays flagged
but silent until it resolves.

### Where the PACE / SerMaStr line actually sits, day to day

Guide 2 already covers the rule ("PACE moves work, SerMaStr decides what
work should exist"). In practice, here's what that looks like from a PM's
seat:

- **PACE owns**: task state, who's assigned, due dates, whether the month's
  work exists yet, "what's stuck," "what should I work on today." If the
  question is *operational* — is it late, who has it, can we move it — ask
  PACE.
- **SerMaStr owns**: whether the *work itself* is right — is this the
  correct strategy for this client, is a keyword worth continuing to chase,
  should the campaign's priorities change. If the honest answer to "why is
  this stuck" is "because the underlying approach isn't working, not
  because nobody's doing it," that's not a delivery problem anymore — it's
  a strategy one.
- **The handoff**: PACE can offer `run_strategy_review` when a delivery
  problem smells like a strategy problem, but it never decides that call
  itself — it surfaces the option and you (or SerMaStr, once asked) take it
  from there.
- **The loop closes through approval, not automatically**: when a SerMaStr
  proposal is *approved*, it becomes a real task and is auto-placed through
  the exact same skilled/eligible/least-loaded engine described in Part 1
  — or held, with the same honest "the team's at capacity" note, if there's
  nowhere for it to go. The human approval step stays in the middle either
  way; nothing SerMaStr proposes ships onto the board without someone
  saying yes to it first.

### The admin-only floor, all three of them together

Guide 2 already named one of these (generating a month **via chat** needs
admin, even though the board's own button doesn't). Here are all three in
one place, since they share a theme — anything **bulk**, **irreversible**,
or that can create a lot of work at once sits behind the admin role:

| Action | Where | Why it's admin-only |
|---|---|---|
| **Auto-assign unassigned** (bulk-place a whole client's unassigned tasks) | Tasks page button, or `POST /clients/{id}/tasks/autoplace-unassigned` | One click distributes potentially dozens of tasks at once — worth a second-tier check before that much of the board moves in one go. |
| **Delete forever** from Trash | Client Tasks → Trash toolbar | Genuinely irreversible — Restore only works while it's still in the trash. |
| **Generate this month, via chat** ("PACE, generate August for Acme") | `#pace` / `/pace` | The button-vs-chat gotcha from guide 2 — clicking the board's own **Generate this month** button is open to anyone, but *asking PACE to do the same thing in words* currently needs admin. If PACE tells you it needs an admin here, use the button instead. |

If you're not an admin and need one of these, that's the message to relay —
"needs an admin" isn't a dead end, it's PACE telling you exactly what to ask
for.

---

## Quick reference

| Want to… | Where |
|---|---|
| See who's over capacity, and why | Workload page — member rows + the flag text |
| Fix a capacity number that looks wrong for the person | Workload page → Team & capacity editor |
| Mark someone as specialized in a category | Workload page → Skills & competencies editor |
| Understand why a placement was held | The task's Activity log — a `placement_deferred` entry names the reason |
| Bulk-place a client's unassigned monthly tasks | Tasks page → **Auto-assign unassigned** (admin) |
| Fix a "matches N tasks" ambiguity | Open the client's board, disambiguate by completing/trashing/renaming |
| See which duplicate names are currently live | Filter/scan a client's board for a repeated task name across sections |
| Decide whether to `yes` a rebalance or slip fix | Read the reason line — does the target/date actually make sense today |
| Approve only part of a Chase Plan | `yes 1,3` (unpicked items simply aren't lost — they return tomorrow) |
| Reset an episode's clock | Touch the task — status, comment, reassignment, anything |
| Escalate a delivery problem that's really a strategy problem | Ask PACE for `run_strategy_review`, or ask SerMaStr directly |
| Delete something from Trash permanently | Trash toolbar → **Delete forever** (admin) |
| Generate a month by asking in chat | Needs admin — use the board's own button if you're not one |

---

*See also: the [Task Manager User Guide](native-task-manager-user-guide.md)
for the board itself, and the [PACE & QA User Guide](pace-qa-user-guide.md)
for how the two agents work day to day.*
