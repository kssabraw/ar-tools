# SerMaStr — New Hire Tutorial

*A guide to take you from "never used it" to "reach for it before doing anything else." Written for
the whole team — VAs, strategists, account managers, admins. No code, no terminal — everything here
happens in Slack or the dashboard.*

> **What this document is not.** This is not the engineering spec for SerMaStr (that's
> `docs/modules/seo-strategist-agent-plan-v1_0.md`) and it is not the task-board manual (that's
> `docs/task-manager-user-manual-v1_0.md`, covering **PACE**). This is the practical, "how do I
> actually use this thing" guide for a person joining the team.

---

## 1. The one-paragraph version

**SerMaStr is the agency's AI Director of SEO.** It's a chat-based teammate — reachable in Slack
and on its own dashboard page — that has read access to *everything* the suite knows about a
client (rankings, Maps presence, AI-answer visibility, content produced, competitors, budget,
backlinks, alerts, the SOPs) and can answer strategy questions the way a senior strategist would:
opinionated, specific, citing the numbers and the playbook. It can also **take action** —
running scans, editing campaign settings, creating tasks, even commissioning a new page — but
anything that costs money or changes something real is confirmed with you first. It doesn't
schedule your day and it doesn't chase your team for status updates; that's **PACE**, its
sibling agent (§8). SerMaStr's job is judgment: *what should we do, and why.*

---

## 2. Where to find it

| Surface | How to get there |
|---|---|
| **Slack — dedicated channel** | Ask an admin which channel is wired up for SerMaStr. Just type your question in plain English — **no @mention needed.** SerMaStr answers every human message posted there. |
| **Slack — DM** | You can also DM the SerMaStr bot directly. Works the same as the channel. |
| **Dashboard** | Sidebar → **SerMaStr** (the sparkle ✨ icon) → `/assistant`. A full-page chat, same brain as Slack. |
| **In-thread memory** | Reply inside a Slack thread and SerMaStr reads the thread history — you don't have to re-explain context turn to turn. |
| **Conversation history (dashboard)** | The dashboard chat saves your threads server-side (not just in your browser) — a **conversation history** picker lets you reopen an old one or start a new chat. Only you (and admins, for troubleshooting) can read your own threads. |

If you don't see the SerMaStr sidebar entry or the Slack channel doesn't respond, ask an admin —
it's a one-time setup, not something you provision yourself.

---

## 3. What SerMaStr actually is

Under the hood, SerMaStr is given a system prompt that starts:

> *"You are SerMastr, the agency's Director of SEO — a senior strategist teammates come to for
> judgment, not just data."*

That framing matters, because it explains the tone you'll get and the behavior to expect:

- **It has opinions, and it commits to them.** Ask "what should we do about Acme's roof-repair
  keyword?" and you'll get a recommendation with a reason — not a bulleted list of neutral
  options. If your ask contradicts the data, it will push back and show you the number that
  changed its mind.
- **It decides instead of interrogating you.** SerMaStr is built to *not* act like an intake form.
  If you ask something underspecified, it makes the sensible professional call, states the
  assumption in one line so you can correct it, and moves on — it only stops to ask a real
  question when the answer would flip the whole recommendation and it genuinely can't infer it
  (a real budget fork, two service lines with different economics, an identifier that matches
  several real things).
- **It's not always running.** A full **strategist review** (the deepest, most expensive mode —
  see §11) runs weekly for clients with something worth reviewing, or on demand, or when
  something serious happens (a 6-week-unresolved drop, a sitewide decline). Day-to-day chat
  answers are a lighter-weight read of live data, not a full review every time.
- **It remembers, per client.** SerMaStr can save a short durable note about a client — a
  decision made in conversation, a commitment ("we'll fund a link round in August"), a fact the
  suite doesn't track — and it will bring that note back up in later conversations, including
  following up on commitments that look overdue.

---

## 4. How SerMaStr thinks — four ideas worth understanding before you rely on it

### 4.1 Everything is scoped to one client — unless you don't name one

Mention a client's name (or something that clearly resolves to one, e.g. their domain) and
SerMaStr pulls that client's full picture before answering. **Say no client name**, and it
switches to **portfolio mode** — an agency-wide view (open alerts, freezes, unread notifications,
open goals, across every client) so you can ask "who needs attention this week?" or "what's on
fire?" without naming anyone. If your portfolio-mode question is really about one client it can't
identify, it will ask which one — that's the one time it leads with a question.

**Why this matters:** without it, every morning check-in would mean naming clients one by one and
hoping you didn't skip the one that's actually on fire. Portfolio mode is how you triage the whole
book in one question instead.

> **You:** *who needs attention this week?*
>
> **SerMaStr:** *Three things stand out. **Coastal Plumbing** is frozen — Google flagged a manual
> action on their homepage 4 days ago, nothing else should move until that's lifted. **Acme
> Roofing** has two open alerts stacking: a rank drop on "roof repair Springfield" and a Maps
> decline in the north-side grid — worth a real look today. **BrightSmile Dental** has nothing
> tracked at all — no goals, no alerts — which usually means the setup got skipped, not that
> everything's fine. I'd start with the Coastal freeze since that's actively costing them
> visibility right now. Want the detail on any of these?*

Notice the order: freeze first, then the client stacking alerts, then the quiet client with
nothing tracked — that's the triage priority SerMaStr always applies in portfolio mode.

### 4.2 It only knows what's in the suite — plus two escape hatches

SerMaStr's campaign numbers (rank, visibility, clicks, alerts) come **only** from the suite's own
data or a live pull — never estimated, never guessed. If there's no data for something, it says
so rather than inventing a plausible-sounding answer. Two things extend its reach without
breaking that rule:

- **A `remember`-backed memory** of things you've told it (see §3).
- **Web search**, for *public* information the suite doesn't track — a competitor's reviews on
  Yelp/TrustPilot, a competitor's own website, industry/algorithm news. It will say where a
  fact came from when it uses this, and it never uses web search for the client's own campaign
  metrics.

**Why this matters:** a generic-sounding answer to "should we expand into City X" is worthless if
it's actually a guess. The whole point of grounding is that SerMaStr's confidence tracks its
evidence — so when it genuinely has nothing, it says so instead of papering over the gap with
plausible-sounding SEO advice. That gap-handling pattern looks like this:

> **You:** *should we push into Shelbyville for Acme?*
>
> **SerMaStr:** *Nothing for Shelbyville specifically — it's not a tracked keyword, hasn't had a
> geo-grid scan, and isn't in Acme's target cities. What I do have: Acme ranks #2 in Springfield
> for "roof repair," and the geo-grid there shows strong pin coverage, so the same play has
> worked nearby. Which service should Shelbyville lead with — roof repair, or something else? If
> it's roof repair, I can add "roof repair Shelbyville" to the tracker and run a geo-grid scan
> centered there to get a real read before we commit to a page. Want me to do that?*

That's the four-step pattern (§9.3, §13): name the gap specifically, answer from the nearest real
data, ask the one question that would let it be specific, then offer — never run — the step that
would close the gap.

### 4.3 It cites your playbook, not general SEO folklore

For any strategy-shaped question (priorities, drops, links, GBP/Maps, AI visibility, budgets,
on-page work), SerMaStr's advice is required to come from the agency's written SOP library, cited
inline (e.g. *"How_To_Rank_In_Google_Maps SOP §Relevance"*). If the SOPs are silent on something,
it says so explicitly rather than making something up. A claim the SOPs themselves label
"(working model)" gets cited as the agency's working theory, not as settled fact. Pure data
lookups ("what's our rank for X") don't need a citation — that rule is for advice.

### 4.4 It reads the instruments correctly, every time

A few rules SerMaStr never gets wrong that are easy for a person to misread:

- **Rank position: lower is better.** A missing GSC position for a day means *no data that day*
  (no impressions, or GSC isn't connected) — never "it dropped out."
- **Maps average rank is only over pins where the business was found.** 3 found pins out of 25 at
  an average rank of 2.0 is barely present, not "ranking #2." Always read it with pin coverage.
- **The GBP description is not a local-pack ranking factor** (relevance/distance/prominence are).
  It matters for **AI visibility** instead — that's where SerMaStr will point description advice.
- **A single AI-visibility engine flipping on one keyword is noise, not a trend.** It reads batch
  rollups and cross-batch trends, and treats engines as non-interchangeable (Google's AI answers
  lean on GBP + top organic; ChatGPT leans on Bing).

---

## 5. What SerMaStr can see — ask it about any of this

SerMaStr is handed one JSON snapshot per client, module by module. You don't need to know the
internal names — this table translates them into things you can actually ask:

| Ask about… | What it's reading — and why you'd check it |
|---|---|
| "How's the campaign going?" / goal progress | **Campaign Goals** — each goal's computed status: achieved / on_track / behind / overdue. Check this first on any client — it's the yardstick everything else gets measured against. |
| Rankings, ranking drops, striking-distance keywords | **Organic rank tracker** — tracked keywords, trend, open drop alerts, the latest reoptimization Action Plan, GSC opportunities. Your go-to when a client asks "why did we drop" or "what's the cheapest win right now." |
| Local pack / Google Maps presence | **Maps geo-grid** — average rank (with pin coverage), top-3/top-10 pin counts, weak coverage areas, recent trend. Use this for anything geo — "are we visible across the whole service area," not just at head office. |
| "Do we show up when someone asks ChatGPT/Gemini/AI Overviews about us?" | **AI Visibility** — per-engine visibility, invisible keywords. Increasingly where clients actually notice they're "missing," even when organic rank looks fine. |
| What's been written/published | **Content** (what the suite generated) vs. **Site inventory** (what's actually live on their site — the honest "do they already have a page for X?" check). Ask this *before* commissioning anything, so you never duplicate a page. |
| Competitors | **Competitors** — local-pack pins, GBP rating/reviews, referring domains, organic overlap, review velocity, new pages they published. Use it to answer "who's actually beating us, and how" with names and numbers instead of a guess. |
| "Who's beating us and on what keywords" | **Domain Intelligence** — keyword gaps (they rank, we don't/barely) and link gaps, opportunity-scored. This is where new content and outreach ideas come from — a ranked to-do list, not just a comparison. |
| Backlinks | **Backlink Explorer** snapshot — DR, referring domains, what changed since last week. Check this before recommending a link round, so the ask is grounded in an actual gap. |
| "Where will we be in 90 days?" | **Forecast** — deterministic rank/traffic projections, the quick-win scenario, per-goal trajectory. It cites these numbers verbatim rather than computing its own. Use it to make the value of a fix concrete before you pitch it (to a client or to yourself). |
| "Is this a Google update or just us?" | **Trends** — cross-client algorithm-update detection, plus this client's seasonal demand outlook. Check this before panicking about one client's drop — it might be everyone's drop, or just the season. |
| Budget / "can we afford this?" | **Budget** — this month's deployable retainer, the fixed costs already spoken for, and what's left (`discretionary`). Ask before proposing anything with a cost, so the plan is real, not aspirational. |
| The monthly task plan | **Task plan** (Recipe Engine) — budget, spend, flags, diagnosis, assigned lines. Use this to see whether a client's plan is actually staffed, not just funded. |
| "How did QA go this month?" | **QA** — the last 30 days of deliverable-review verdicts, and which tasks failed or need a human. Handy for spotting a pattern (one writer, one page type) before it becomes a client complaint. |
| Citations, syndication, reports, GBP performance, GA4 traffic | Each has its own module — ask plainly, e.g. "how are our GBP calls trending?" |
| Which SOPs apply / whether an Asana project is mapped | **SOPs** / **Asana** |
| **Is anything paused right now?** | **Health** — an active freeze (all content/link output paused — the single most urgent thing to know about a client), open response episodes, offpage alerts. Worth checking first on any client you don't work with daily — a freeze changes everything else you'd otherwise recommend. |
| The client's business profile | **Setup** — GBP listing, target cities, client type, brand voice summary, ICP summary. Check this before recommending a new keyword or city — it tells you what the client is actually set up to target. |
| Cross-agent friction | **Director of Operations** — read-only "seam" flags (an approved SerMaStr proposal nobody placed on the board, content shipped without full brand context, two agents working the same target). Insight, never an instruction — a prompt to go look, not a verdict. |

A module simply **isn't there** when nothing has been set up or run yet — SerMaStr says so rather
than guessing, and that's a legitimate answer, not a bug.

---

## 6. What SerMaStr can do — actions

SerMaStr doesn't just report — it can trigger real work. Every action falls into one of two
buckets.

### 6.1 Free — runs immediately, no confirmation

| Action | What it does |
|---|---|
| Rebuild the Action Plan | Free — no API spend, no side effects to guard |
| `fetch_live_gsc` | A live Search Console pull for current/latest performance |
| `cost_plan` | Prices a proposed set of tasks against the real cost catalog and checks it against the client's discretionary budget — always called before SerMaStr proposes anything that costs money |
| Web search | Public info only (§4.2), bounded to a few searches per question |
| `read_sop` | Pulls an SOP section not already loaded in context |
| Maps/keyword history lookups, LeadOff city lookups | Free reference reads |

### 6.2 Confirm-gated — SerMaStr stages it, you approve it

Anything that spends API budget **or** changes something real gets staged, not run. You'll see a
message like:

> *"This will run a Maps geo-grid scan for Acme Roofing (2 paid DataForSEO calls). Reply **yes**
> to proceed."*

Reply **yes** (or any clear affirmative) and it runs. Reply with anything else, and the pending
action is dropped — say what you actually meant instead. **Note:** the confirmation is
per-conversation-thread — a new question before you reply "yes" cancels the pending action.

| Group | Actions | You'd reach for this when… |
|---|---|---|
| **Run work** | Maps geo-grid scan · GSC Research · AI Visibility scan · a full strategist review · generate a client report · push the monthly task plan to Asana · a live SERP check (organic + local pack) · a backlink lookup · an RD/DR/UR authority report | The stored data is stale, or someone (a client, a PM) needs a formal read right now rather than the next scheduled refresh. |
| **Asana board** | Add a task · remove a task · mark a task complete (SerMaStr will extract the task name, assignee, and notes from your message — including a finding earlier in the same conversation, so the assignee knows *why*) | Work got decided in conversation and needs to actually land on the board, not just live in the chat log. |
| **Client profile** (Setup page scalars) | Website URL · GSC property · business location · monthly retainer · client type · service-area-business flag · add/remove target cities | A real-world fact changed (new GSC property, renegotiated retainer, a new city the client wants covered) and the record needs to catch up. |
| **Campaign management** | Add/remove tracked keywords (organic) · add/remove AI-visibility keywords or competitors · add/remove a campaign goal | You and the client (or PM) have agreed something should be tracked or measured going forward, not just discussed once. |
| **Commission content** (creates a real deliverable) | Start a content run (blog post or service page) · generate a Local SEO page for a keyword + city · reoptimize a live page by URL | A gap you've just confirmed (via the Content/Site inventory modules, §5) is worth turning into an actual deliverable now. |
| **Strategy** | Save a set of recommended steps to the client's Action Plan (recommend-only — nothing runs; this just writes the plan down where the team looks) | You just gave a recommendation in chat and want it to persist somewhere the whole team — not just this thread — will see it. |

### 6.3 Worked examples

**Commissioning content**

> **You:** *can we add "emergency roof tarping" as a tracked keyword for Acme, and also start a
> blog post on it*
>
> **SerMaStr:** *That's not yet a tracked keyword or a page for Acme — I checked the tracker and
> the site inventory, nothing on that term. I'll add it to rank tracking (backfills rank +
> market data via DataForSEO) and start a blog post targeting it. This will add 1 tracked
> keyword and start a content run for Acme Roofing (runs the full generation pipeline). Reply
> **yes** to proceed.*
>
> **You:** *yes*
>
> **SerMaStr:** *Done — "emergency roof tarping" is now tracked, and the blog run is queued.
> I'll ping you back on the run once it's ready, or check Runs in the dashboard.*

**Diagnosing a drop** — this is the "why," not just the alert:

> **You:** *why did "roof repair Springfield" drop for Acme?*
>
> **SerMaStr:** *It fell from #3 to #7 over the last 9 days. Two things line up: impressions on
> that query dropped too — not just position, so this isn't a measurement blip — and the latest
> SERP snapshot shows a competitor, Springfield Roof Pros, picked up a review spike and moved
> into the top 3. That's a straightforward position-drop diagnostic tracing to competitor
> movement (Rank_Drop_Mitigation_SOP_Organic §B5 step 6), not a technical or on-page issue on our
> side. I'd fund another link round on that page this month — Acme's discretionary budget has
> room for it. Want me to save that as a step on the Action Plan?*

**"What should we improve?"** — a full strategist-style answer, not a data dump:

> **You:** *what should we improve for Acme this month?*
>
> **SerMaStr:** *Three things, ranked by leverage:*
> 1. *Reoptimize "roof repair Springfield" — it's striking-distance at position 6, and the
>    geo-grid shows we're already found on 22 of 25 pins there, just not converting to page one.
>    Cheapest win on the board.*
> 2. *A location page for the north-side grid — average rank there is 9.4 across found pins,
>    well behind the rest of the city. That's a coverage gap, not a ranking problem
>    (How_To_Rank_In_Google_Maps SOP §Relevance).*
> 3. *Two AI-visibility keywords are invisible across every engine — "emergency roof repair near
>    me" and "storm damage roof Springfield." Worth a GBP profile pass; AI Overviews and AI Mode
>    lean heavily on GBP completeness (AIO_AEO_SOP).*
>
> *This month's task plan also has one unstaffed content line — I'd put a body on that before
> adding anything new. Want a full strategist review, or should I save these three as Action Plan
> steps?*

Notice what each of these does that a vague answer wouldn't: it names the specific page or
keyword, gives the number behind the claim, cites the SOP it's following, and ends with a
concrete next move rather than a summary.

---

## 7. What SerMaStr can NOT do

Read this section as carefully as §6 — a new hire's most common mistake is assuming SerMaStr is
more autonomous, or less capable, than it actually is.

- **It never publishes to a client's live site.** Commissioning content creates a *draft*
  deliverable in the suite (a run, a Local SEO page). Publishing is a separate, human step —
  SerMaStr will say so and point you at the page instead of pretending it can.
- **Some things are dashboard-only, on purpose:** creating or archiving a client, freezing/lifting
  a freeze, WordPress/Drive credentials, brand-voice or ICP long-form text, reference page
  structures, the GBP OAuth connection. SerMaStr will name the exact page for these instead of
  claiming it can't help.
- **A frozen client pauses content/link output — including SerMaStr's commission actions.** If a
  client has an open freeze (manual action / deindexing detected), SerMaStr will surface that
  prominently and won't try to route around it.
- **It doesn't override anyone else's precedence engine.** The Director of Operations context
  (§5) is read-only insight — SerMaStr can *cite* a cross-agent conflict and *offer* to raise it,
  but it has no authority over PACE's task assignment, the reoptimization planner's priority
  order, or the autonomy executor's decisions.
- **It doesn't run unattended.** Every side-effecting or paid action is confirm-gated (§6.2) —
  there's no way to make SerMaStr silently spend money or silently edit a campaign. A separate,
  much more conservative **autonomy** layer exists for a few narrow tasks on opted-in clients,
  and it is a different system with its own budget guardrails (ask an admin if you're curious —
  it's off for most clients).
- **It won't re-judge a QA verdict, and it won't re-derive a computed status.** Goal status,
  QA pass/fail, and rank-drop classification are all computed deterministically elsewhere in the
  suite; SerMaStr reports them, it doesn't second-guess them.
- **Anyone in the channel can trigger an action** — SerMaStr doesn't currently gate *who* can
  approve a confirm. Use judgment about what you commit to on a shared client.
- **It's not a search engine for the open web as a default behavior.** It only reaches outside
  the suite when a question genuinely needs public information, and it says when it has.

---

## 8. How SerMaStr fits with the other agents

The suite runs a small cast of AI teammates that share the same rails (Slack, the notifications
service, the scheduler) but do different jobs. Knowing which one to go to saves you a redirect:

| Agent | Job | Cadence | Executes? |
|---|---|---|---|
| **SerMaStr** | Strategy — what should we do and why | Chat on demand + a weekly deeper review | Proposes; executes only small, confirmed actions (§6) |
| **PACE** | Keeps delivery moving on the task board — reassigns, nudges, escalates stalled work | Daily Chase Plan + on-demand chat | Proposes a batch; a human replies "yes" (or "yes 1,3") to approve |
| **QA** | Judges whether a finished deliverable is actually good before it reaches the client | Automatic when a task enters *In QA*, or on demand | Verdicts only — never edits the deliverable itself |
| **DORA** (Director of Operations) | Cross-agent oversight — flags friction *between* the other three (an approved proposal nobody placed, content shipped degraded, two agents on the same target) | Daily reconciliation + a weekly digest | Read-only — opens a board task naming the gap, never resolves it |
| *(Autonomy executor)* | A narrow, budget-capped layer that can auto-commission a handful of pre-approved actions on opted-in clients | Weekly, per opted-in client | The one layer that can act with no human confirm — deliberately limited in scope |

**Rule of thumb:** ask SerMaStr "what should we do" questions and strategy. Ask PACE "is this
task on track / who has capacity" questions. Never expect SerMaStr to chase a stalled task, and
never expect PACE to explain *why* a ranking dropped.

---

## 9. Novice path — your first week

Do these in order. Each builds on the last.

1. **Say hello in the SerMaStr channel with a real client question**, no special syntax:
   *"How is Acme Roofing doing?"* Read the reply structure: it leads with goal progress (if goals
   exist), then 2–3 wins, then 2–3 concerns, each with a number.
2. **Ask a portfolio question with no client name**: *"Who needs attention this week?"* Notice it
   doesn't ask you to pick a client — it triages the whole book (freezes first, then clients
   stacking alerts, then quiet clients with nothing tracked).
3. **Ask something SerMaStr has no data for on purpose** — a city or keyword the client has never
   tracked. Read how it handles the gap: names the gap specifically, answers from the nearest
   real data, asks the one clarifying question, and offers (never runs) the step that would close
   the gap.
4. **Trigger your first free action**: *"Rebuild the Action Plan for Acme."* No confirmation
   needed — notice the difference from a paid action.
5. **Trigger your first confirm-gated action**: ask it to add a tracked keyword. Read the
   confirmation message closely — it names the client and exactly what will happen — then reply
   `yes`.
6. **Read a strategist review**, if one exists for a client you're on (dashboard → client
   workspace → Strategist Review card, or ask SerMaStr to summarize the latest one).

By the end of week one you should be comfortable asking questions and running the small stuff
without checking this doc.

---

## 10. Intermediate path — building real proficiency

1. **Ask a "what should we improve" question** and evaluate the answer against §4.3 — does it
   cite an SOP? Does it name the specific tool/page for each recommendation, or is it vague? A
   good SerMaStr answer never hand-waves; if it does, that's worth flagging.
2. **Give it a fact it should remember.** Tell it something in conversation ("we're holding off on
   link building for Acme until September — budget's tight"), then start a *new* conversation
   later and ask about Acme's link-building plan. It should surface that memory unprompted.
3. **Ask a forecast question**: *"Where will Acme's clicks be in 90 days if nothing changes?"* and
   a quick-win question: *"What's it worth if we get our striking-distance keywords into the top
   3?"* Compare the numbers it gives you against the Forecast page in the dashboard — they should
   match, because it's citing the same deterministic model, not computing its own.
4. **Have it commission a real deliverable** — a Local SEO page or a content run for a genuine
   opportunity — and follow it through to the draft landing in the dashboard. Confirm you
   understand that this is *not* the same as publishing.
5. **Practice the SOP-citation habit yourself.** When SerMaStr cites an SOP section you haven't
   read, go read it. The point of SOP grounding is that you and SerMaStr are working from the
   same playbook, not that you can skip reading it because SerMaStr already has.
6. **Watch what happens when you contradict the data.** Propose something the numbers argue
   against ("let's stop tracking rankings for Acme, nothing's moving") and see SerMaStr push
   back with the number that changes its mind. This is a designed behavior, not an error.

---

## 11. Advanced / proficient usage

1. **Run a full strategist review on purpose** and read the whole thing — assessment, findings
   with SOP citations, proposals (each tagged `proposed`/`approved`/`dismissed` and
   `none`/`approval`/`senior`), and open questions. Approve or dismiss a proposal from the Action
   Plan page and watch it become a real Asana/native task via the PACE rails — this is the loop
   SerMaStr → human approval → real work that the whole system is built around.
2. **Use portfolio mode as a standing morning habit** rather than a one-off: "what's on fire" as
   the first thing you ask each day, before diving into any one client.
3. **Learn to read a Director of Operations flag** (§5, last row) as a prompt to *investigate*,
   not as an alarm — it's evidence of friction between agents, not a verdict, and SerMaStr will
   never resolve it for you; it can only surface it and offer to open a task.
4. **Recognize the escalation triggers** — a response episode open 6+ weeks with no improvement,
   or a client transitioning into a sitewide decline, both auto-queue a strategist review and post
   an "Escalation brief ready" note next to the alert. Know to go read that brief rather than
   re-diagnosing from scratch.
5. **Understand budget-aware planning.** Before SerMaStr proposes anything with a cost, it should
   have called `cost_plan` internally — if you ever see a plan proposed with dollar figures that
   don't add up against the client's discretionary budget shown on the Task Plan page, flag it;
   that's the one arithmetic SerMaStr is supposed to never do "by feel."
6. **Know the boundary with autonomy.** For opted-in clients, a small set of actions can run
   *without* a confirm — this is a deliberately separate, tightly capped system (§7). If you're
   ever unsure whether something happened because you (or a teammate) approved it, or because
   autonomy ran on its own, check the client's activity/notifications feed rather than assuming.

At this point you should be able to onboard the *next* new hire on SerMaStr yourself.

---

## 12. Troubleshooting & common gotchas

| Symptom | Likely cause / what to do |
|---|---|
| SerMaStr doesn't respond in the Slack channel | It only answers plain human messages (no bot messages, no @mention required) in a channel that's actually been wired up — check with an admin that the integration is live for that channel. |
| It answered about the wrong client | Client resolution is name/domain matching against the client list — be more specific, or say the client's name exactly as it's set up in the dashboard. |
| It won't run something I asked for | It only calls an action tool when you're clearly asking it to run/start/change/create/delete something. A question about results won't trigger an action — that's intentional, not a bug. |
| I said "yes" and nothing happened | The confirmation only fires from the *same* conversation thread as the staged action, and any other message in between cancels the pending action. Re-ask, then reply "yes" immediately. |
| It refuses to change something and points me at a page instead | That field is dashboard-only by design (§7) — go to the page it names. |
| It says a client is frozen and won't commission content | Working as intended — a freeze pauses all content/link output. Check the freeze reason on the workspace banner; only an admin lifts it. |
| It gave me a recommendation with no SOP citation | Fine for a pure data lookup ("what's our rank for X"); for anything strategy-shaped it should cite one — if it consistently doesn't, that's worth a bug report, not something to just work around. |
| Its numbers don't match what I see on a dashboard page | Ask it which module it's reading from and compare — for computed things (goal status, forecasts, QA verdicts) it should always match exactly, since it reports the same deterministic values rather than recomputing them. |

---

## 13. Practice exercises

Work through these with a real (or sandbox) client. They're ordered novice → advanced; don't skip
ahead if an earlier one didn't go the way this guide describes.

**Novice**
- [ ] Ask "how is `<client>` doing?" and identify the goal-progress lead, the wins, and the concerns in the reply.
- [ ] Ask a portfolio question with no client named.
- [ ] Ask about a city/keyword you know isn't tracked and confirm it follows the four-step "no data" pattern (§4.2 / §9.3).
- [ ] Run the free `rebuild_action_plan` action.
- [ ] Run one confirm-gated action end to end (stage → read the confirm message → reply "yes").

**Intermediate**
- [ ] Get it to cite a specific SOP section, then go actually read that section.
- [ ] Teach it a memory, start a new conversation, and confirm it recalls the memory unprompted.
- [ ] Ask for a 90-day forecast and a quick-win value, and check both against the Forecast page.
- [ ] Commission a content run or Local SEO page and follow the deliverable from confirm → queued → drafted.
- [ ] Propose something the data contradicts and read how it pushes back.

**Advanced**
- [ ] Trigger and fully read a strategist review; approve one proposal and confirm it lands as a real task.
- [ ] Find (or wait for) a Director of Operations flag and decide, correctly, whether it needs action or just awareness.
- [ ] Explain to a teammate, without looking this doc up, the difference between SerMaStr, PACE, QA, and DORA.
- [ ] Identify a case where SerMaStr correctly said "the SOPs are silent on this" instead of improvising.

---

## 14. Quick reference

**Access:** Slack channel (no @mention) · Slack DM · dashboard sidebar → **SerMaStr** → `/assistant`

**Client scope:** name a client → single-client mode. Name none → portfolio (agency-wide) mode.

**To trigger anything:** ask in plain English ("run a Maps scan for Acme," "add this keyword,"
"start a blog post about X"). Free actions run immediately; anything paid or side-effecting stages
a confirmation — reply **yes** to proceed, anything else cancels it.

**Never expects you to:** know an internal action name, write structured input, or pick a module
by its technical key — describe what you want in plain language.

**Always remember:**
- It only reports what the suite actually knows, plus memory and public web search — never a
  guessed number.
- It advises and does small confirmed actions; it does not publish, does not override PACE/QA/the
  planner, and does not run unattended.
- For delivery/task-board questions, go to **PACE** instead — see `docs/task-manager-user-manual-v1_0.md` §6.
