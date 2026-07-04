# SerMaStr Chat Interface — Conversational Ops — Module Plan v1.0

**Date:** 2026-07-05
**Status:** Proposed (short spec for review — nothing built yet)
**Depends on:** SerMaStr strategist Phases 0–4 (PR #221, merged), the Slack assistant (`services/slack_assistant.py`), the drill-down tools (`services/strategist_tools.py`), the notifications service.

> **One sentence:** the Slack bot becomes **the way the team interfaces with
> SerMaStr and the suite** — a real conversation that can check on any client's
> campaign *and* tweak it (keywords, schedules, budgets, task-plan lines,
> proposal approvals), with every write staged behind a confirm.

---

## 1. What exists vs what this adds

Already built (don't rebuild): channel-mode Q&A with thread memory + DMs;
cross-module read context (`_CONTEXT_PROVIDERS`); five trigger actions
(rebuild plan, Maps scan, GSC Research, AI Visibility scan, strategist
review) with reply-*yes* confirms on paid ones.

This plan adds three things:

1. **Real conversation** — client stickiness across a thread, a bounded
   tool-use loop (the bot can drill down mid-answer instead of one-shotting a
   static context blob), and a warmer register.
2. **Parameterized write actions** — today's actions take no arguments;
   "add 'water heater repair anaheim' to Acme's tracker" needs typed args,
   a human-readable confirm summary, and staged execution.
3. **An audit trail** — every chat-driven write recorded.

## 2. Architecture

```
Slack message → resolve client (message OR thread history)
  → bounded Claude tool-use loop (Sonnet, ≤4 rounds):
       read tools   → answered inline (context providers + strategist drill-downs)
       write tools  → NEVER executed inline: staged to _pending with args
                      + a confirm summary ("I'll add 3 keywords to Acme's
                      rank tracker — reply *yes*")
  → reply in-thread; "yes" executes the staged action → result + audit row
```

- **Client stickiness:** `resolve_client` falls back to scanning the thread's
  prior turns for a client name before giving up and asking.
- **Tool loop:** the strategist run-loop pattern, reused. Read tools =
  existing context providers exposed as callable tools + the
  `strategist_tools` registry verbatim (all read-only, self-documenting,
  already capped/clipped). Paid reads (`audit_page`, scans) keep the confirm.
- **Write staging:** `_pending[(channel, thread_ts)]` grows from
  `{action, client_id}` to `{action, client_id, args, summary}`. A non-yes
  reply supersedes it (unchanged). Nothing executes without the confirm —
  including "free" writes, since writes are writes.
- **Multi-tweak messages** ("add these 3 keywords and turn on weekly Maps
  scans") stage as ONE combined confirm listing every change.

## 3. Action catalog (the write tools)

Grouped by risk; **all confirm-gated; channel stays open to the whole team**
(owner ruling — 4-person shop, trusted channel). Each action = name + JSON
input schema + `summarize(args)` for the confirm + `run(client_id, args)`
that calls an existing service (no new business logic in the bot).

| Group | Actions | Backing service (exists?) |
|---|---|---|
| Runs & checks | the 5 existing triggers, incl. `run_strategy_review` | ✅ built |
| Keywords & tracking | add/remove tracked keywords; add/remove AI-visibility keywords; add/remove tracked competitors | ✅ rank + brand CRUD services |
| Schedules & toggles | rank-fetch cadence (`rank_fetch_config`), Maps weekly on/off, AI-visibility schedules, syndication enable/interval, report cadence (`rank_report_config`) | ✅ config tables + services |
| Budget & campaign | set retainer / margin month / client_type / SAB; generate the monthly task plan (Recipe Engine) with margin + special-projects args | ✅ clients update + recipe service |
| Task-plan lines | **add/remove a line on the latest monthly task plan** ("add 2 more content pages", "drop the GBP Blast this month") — an edits layer over the stored `monthly_task_plans.plan` JSONB, recomputing spent/remaining and flagging manual lines `source="chat"` | 🆕 small service addition (`recipe_engine.apply_plan_edit`) |
| Proposal approvals | approve/dismiss strategist proposals by index ("approve proposal 2 for Acme") | ✅ router logic, called via service |

**Boundary carve-outs (the only closed doors in an otherwise open channel):**
- `requires="senior"` proposals **cannot be decided from Slack** — Slack has
  no user→role mapping under the open model, and the §3 passthrough gate must
  hold. The bot replies with a deep link to the Action Plan card, where the
  admin login enforces it.
- **Freeze / lift-freeze stays out of the catalog** (admin-gated UI endpoint;
  same reasoning).
- Frozen clients: write actions refuse with the freeze explanation
  (`assert_not_frozen` paths already exist); reads keep working.

## 4. Audit trail

Every executed write emits `notifications.emit(kind="chat_action",
severity="info")` — "Via Slack: added 3 tracked keywords (asked by @kyle)" —
so the in-app feed doubles as the audit log (no new table). The Slack user id
+ display name ride in the payload. Slack replies include what changed, so
the thread itself is a second record.

## 5. Config & cost

- `slack_assistant_max_tool_rounds` (4), `slack_assistant_tool_result_chars`
  (reuse the strategist clip), existing model settings unchanged (Sonnet).
- Cost: a conversational answer becomes 1–3 Sonnet calls instead of 1
  (~$0.01–0.05/message); write executions are DB calls. No new env vars.

## 6. Phasing

- **Phase 1 — conversational core:** thread client-stickiness, the tool-use
  loop with read tools (context providers + strategist drill-downs), tone
  pass on the system prompt. No new writes. *Ships useful immediately.*
- **Phase 2 — parameterized writes:** the staging upgrade (`args` +
  `summary` in `_pending`), keywords/tracking + schedules/toggles + runs.
  Audit rows from day one.
- **Phase 3 — money & task plans:** budget/campaign fields, Recipe Engine
  generate-with-args, and the `apply_plan_edit` service (add/remove plan
  lines with cost recompute).
- **Phase 4 — proposal approvals** ("approve proposal 2") with the
  senior-proposal carve-out, + a `list proposals for <client>` read.

Each phase is a separate PR with pure-logic unit tests (arg parsing, confirm
summaries, plan-edit math, stickiness resolution).

## 7. Non-goals

- No autonomous writes, ever — a confirm precedes every mutation.
- No Slack approval of senior-territory decisions (see §3 carve-outs).
- Not a replacement for the UI — deep links accompany every answer where a
  richer surface exists.
- No per-user roles in v1 (owner ruling: open channel). Revisit if the team
  or channel membership grows.

## 8. Open decisions (defaults chosen; flag to change)

1. **Confirm scope:** confirm ALL writes (default) vs skip confirms for
   trivially-reversible ones (keyword add). *Default: confirm everything —
   one pattern, no surprises.*
2. **Task-plan edits vs Recipe Engine authority:** manual chat edits mark the
   plan `manually_adjusted` and survive until the next monthly generate
   (default) vs re-applying on regenerate. *Default: don't survive a
   regenerate — the Engine stays the costing authority.*
3. **DM behavior for writes:** allowed (default, same confirms) vs
   channel-only so tweaks are visible to the team.
