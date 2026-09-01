# DORA — User Guide

*A guide to DORA (Director of Operations, Reconciliation & Awareness) — the read-only lens that
watches the other three agents for each other's blind spots.*

> **What this document is not.** This is not the engineering spec (that's
> `docs/modules/director-of-operations-plan-v1_0.md` and its Phase-1 spec sibling). This is a
> different flavor from the other guides in this set — DORA is an AI agent, not a UI module — so
> it follows `docs/sermastr-user-guide.md`'s style, scaled down to DORA's much smaller scope.

---

## 1. The one-paragraph version

**DORA is read-only.** It never resolves anything, never reassigns a task, never approves a
proposal, never runs a scan. Its whole job is to notice when the other agents' work has a gap
between them — an approved SerMaStr proposal nobody put on the board, a QA that's gone quiet, two
agents working the same keyword — and surface it as a plain board task or a weekly digest. On top
of that read-only lens, DORA also has its own conversational persona you can ask questions of, but
even in chat it has **zero tools** — it can explain a gap and point you at who owns fixing it; it
cannot fix anything itself.

---

## 2. Where to find it

| Surface | How to get there |
|---|---|
| **Dashboard chat** | Sidebar → **DORA** (Compass icon) → `/director`. Only shown once the module is enabled. |
| **Slack — #dora** | A dedicated Slack app and channel, separate from SerMaStr's and PACE's bots. |
| **Board tasks** | Any client's task board — look for a card titled **"Director seam: …"**. |

If the sidebar entry or `#dora` doesn't respond, the module may not be enabled yet on your
environment — ask an admin rather than assuming it's broken.

---

## 3. The seams it watches

Each row below is a **seam** — a specific, plain-language condition. Once tripped, DORA opens ONE
board task per client (auto-closing it the moment the condition clears) — except the one marked
portfolio-only, which posts a notification instead since there's no single client to file it
against.

| Seam | What it means |
|---|---|
| **A SerMaStr proposal was approved but never placed on the board** | Someone said yes to it, and it's been sitting a few days with no real task created from it. |
| **A SerMaStr proposal is stuck pending** | Nobody approved or dismissed it — it's just sitting there. |
| **An autonomy candidate was proposed but never acted on** | The autonomy layer suggested something and it's gone unaddressed. |
| **QA has gone idle** *(portfolio-only)* | Nothing has entered the QA review stage in a while — worth checking whether the board's checklists are routing work through QA at all. |
| **Content shipped in a degraded state** | A finished writer run or generated page shows signs the brand-voice/context pass didn't fully run. |
| **Two agents are working the same target** | A task and an intervention (or two tasks) from different producers both point at the same keyword or page — flagged, never auto-merged. |
| **An unrecognized task source** | A task exists whose `source` doesn't match anything DORA knows about — a signal something new is creating tasks outside the usual producers. |

---

## 4. The weekly digest

A deterministic (no-LLM) summary — named clients per seam, not just counts — plus autonomy
activity and the top open capacity holds. It's **silent on an all-clear week**: zero seams, zero
autonomy activity means nothing posts at all, so a quiet week never generates noise.

---

## 5. Talking to DORA

Ask it about a client, or ask agency-wide with no client named — same scoping pattern as
SerMaStr. It answers strictly from the same read-only data the reconciler uses; it won't invent a
flag that isn't actually there. Typical questions:

> **You:** *where are we bottlenecked this week?*
>
> **DORA:** *Two things stand out. Acme Roofing has a SerMaStr proposal that's been approved for 4
> days with no board task yet — worth checking with whoever approved it. And portfolio-wide, QA
> hasn't reviewed anything in over a week, which usually means finished work isn't being routed
> through the In QA status rather than that QA itself is broken.*

If you ask DORA to *fix* something — "reassign this," "approve that proposal" — it will decline
and name the agent that actually owns it (usually PACE or SerMaStr).

---

## 6. What DORA can NOT do

- **It never acts.** No confirm-gated actions exist for it at all — contrast SerMaStr and PACE,
  which both have a confirm-then-run action set.
- **It doesn't arbitrate.** It never touches the reoptimization planner's priority order, PACE's
  task-assignment logic, or the autonomy executor's decisions — those precedence engines are
  untouched by DORA's existence.
- **It doesn't block autonomy (yet).** A "pre-flight veto" that could stop an about-to-auto-run
  autonomy action exists in the code but ships **off** by default, as a separate flag from the one
  that turns DORA on at all. Don't assume DORA is currently preventing anything from executing.
- **It doesn't auto-merge duplicates.** A "two agents, same target" flag is informational only —
  a human decides what to do about it.

---

## 7. Quick reference

**Access:** Dashboard sidebar → **DORA** → `/director` · Slack **#dora**

**Scope:** name a client → per-client seams. Name none → the whole portfolio.

**A "Director seam" board task appeared:** DORA noticed a gap between agents. It will auto-close
itself once the underlying condition clears — you don't need to trash it, though you can.

**Never expect DORA to:** run a scan, approve anything, reassign a task, or resolve a flag it
raised. It names the gap; a human or the owning agent closes it.

---

## FAQ

**DORA flagged something — does it fix it?**
No. It opens a board task or notification naming the gap; a human, or the agent that actually owns
that kind of work, does the fixing.

**Can I ask DORA to run a scan / approve a proposal / move a task?**
No — it has zero tools. It will explain and point you at SerMaStr or PACE instead.

**Why did the same seam task reappear after I trashed it?**
The reconciler re-opens a seam's task each run as long as the underlying condition is still true —
trashing it manually doesn't fix the root cause; it closes on its own once the condition clears.

**DORA said something's snagged but I don't see it on any client's board.**
QA-idle and unrecognized-source seams are portfolio-level, not tied to one client — they show as
an agency-wide notification instead of a board task.

**Does DORA stop autonomy from doing something risky?**
Not currently — the pre-flight veto exists in code but ships off by default as a separate flag.
Turning DORA on does not arm it.
