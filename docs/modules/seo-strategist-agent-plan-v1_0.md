# Search Marketing Strategist Agent — Module Plan v1.0

**Date:** 2026-07-04
**Status:** Proposed (spec for review — nothing built yet)
**Depends on:** the 24/7 agent phase 1 stack (PRs #215/#216 — all live), the SOP library (`docs/sops/`), the notifications service, SerMastr (`services/slack_assistant.py`).

> **Naming note.** This is the **search-marketing strategist** — its scope is
> the client's entire search surface: organic SERPs, the local pack / Maps,
> AI-answer visibility (AEO/AIO), content, links/offpage, and budget
> allocation. It is *not* "a strategist for LLM visibility" (that's one input
> among many — the LABS module), and the phrase "LLM strategist" is avoided
> throughout to keep the two ideas apart. Conversational surface: SerMastr's
> strategist mode.

---

## 1. Purpose & position

The **reasoning layer** on top of the deterministic agent loop. Everything the
SOPs made computable is already code (detection → classification → playbooks →
costing → verify loop → kill switch). What's left is the **middle tier of
judgment** — the calls the SOPs assign to "the SEO running the campaign" but
that don't require Kyle/Ryan's authority:

- Cross-domain synthesis: signals that only mean something together (organic +
  maps declining + heavy off-topic content = vector confusion, not three
  separate problems).
- Conflicting or unusual signal patterns the B1–B5 / playbook rules don't cover.
- "The plan says X but the context suggests Y" — e.g. the Recipe Engine funds
  RD, but the SERP deep-dive shows the gap is actually intent mismatch.
- **Escalation briefs**: when the 6-week rule fires, the strategist prepares
  the strategy-review brief (what was tried, what moved, what it recommends) so
  Kyle/Ryan review a case file, not a raw alert.

**Hard boundary: the strategist proposes; it never executes.** Every output is
a recommendation with an SOP citation, staged for human approval. It is not a
replacement for the humans at the SOPs' escalation points — it makes their
queue shorter and their decisions better-prepared.

### Explicitly rejected alternative (decision record)

Per-domain standing LLM monitors (on-page / geo-grid / offpage / LLM-tracking
agents) were considered and rejected: monitoring is already solved
deterministically (cheaper, testable, no drift), and strategy is precisely the
*cross-domain* part — one shared budget allocated across domains, SOPs that
route into each other, diagnoses that live in signal intersections. Multiple
reasoning agents would recreate the n² drift `_ORCHESTRATOR.md` exists to
prevent. The architecture is hierarchical instead: **one strategist per
client**, with **bounded drill-down tools** where depth is needed.

---

## 2. Architecture

```
deterministic monitors (built) → structured signals (built)
    → digest assembler (pure; reuses SerMastr's provider pattern)
        → ONE strategist run per client (Claude, tool-use loop)
            → drill-down tools on demand (bounded contexts)
                → strategy_reviews row → Action Plan card + Slack digest
                    → human approves / dismisses / asks follow-ups
```

### Triggers (event-driven — never always-on)

| Trigger | Cadence | Rationale |
|---|---|---|
| `scheduled` | Weekly, after the weekly reopt-plan build, **only for clients with active signals** (open alerts/episodes/flags) | Quiet clients skip → cost + noise control |
| `escalation` | On `episode_escalated`, `sitewide_decline`, `freeze_suspect`, Recipe Engine `escalate_margin_below_50` | Prepares the human-review brief while the alert is hot |
| `on_demand` | SerMastr ("strategy review for Acme") or the Action Plan page button | Human pulls a review whenever |

### Inputs (all pre-digested — the strategist never reads raw tables)

One `build_strategy_digest(client_id)` assembler (pure, unit-testable) produces
a token-budgeted context from data that already exists:

- Latest Action Plan items + B1–B5 classifications + episode clock notes
- Open episodes (status, age, baseline vs current)
- Latest monthly task plan (tasks, flags, diagnosis, margin, remaining)
- Open alerts across channels (rank / maps / offpage incl. citations, imbalance)
- Latest LABS rollup (per-engine visibility, invisible keywords)
- GBP snapshot (reviews vs threshold, categories), budget/client_type/SAB
- Client context: services, vector/theming notes, brand voice + ICP summaries
- **SOP retrieval**: the relevant `docs/sops/` sections + the DB `sop_store`
  entries, token-budgeted (reuse `sop_store.resolve_sops_text` budgeting;
  extend with a per-doc section index over `docs/sops/`)

Budget target: ≤ ~25k input tokens per run before drill-downs.

### Drill-down tools (where subagents plug in)

Exposed to the strategist as tool-use functions. v1 implements most as
**deterministic data assemblers** (cheap, no extra LLM); only the two that
summarize large corpora run as true LLM subagents:

| Tool | Type | Returns |
|---|---|---|
| `geogrid_history(keyword)` | LLM subagent | Trend narrative over the full scan series + octant/SoLV movement |
| `serp_deep_dive(keyword)` | LLM subagent | What the SERP rewards now vs then (snapshots + trends + rankability) |
| `audit_page(url, page_type)` | deterministic → nlp `score-page` | 8-engine verdict summary (composite, deficiencies) — **paid call, counted** |
| `episode_timeline(keyword)` | deterministic | Full check history for a response episode |
| `read_sop(doc, section)` | deterministic | SOP text beyond the budgeted digest |
| `client_capacity()` | deterministic | Team capacity + current plan load (workbook constants + open plans) |

Cap: ≤ 4 drill-downs per run (config), each returning ≤ ~2k tokens.

### Output contract

One **`strategy_reviews`** row per run:

```
{
  client_id, trigger, model,
  assessment: text,                 -- the 1-paragraph strategic read
  findings: [ {signal_refs[], synthesis, sop_citation} ],
  proposals: [ {
      title, action, rationale, sop_citation,
      est_cost_usd?, effort?, assignee_hint?,     -- roles-matrix aware
      status: proposed|approved|dismissed|expired,
      requires: none|approval|senior              -- senior = Kyle/Ryan only
  } ],
  questions: [ text ],              -- halt-and-ask items (no SOP owns it / conflict)
  input_digest: jsonb, token_usage: jsonb, created_at
}
```

Proposals are **advice objects**, not runnable actions. Approving one (v1)
marks it approved and surfaces it as a pinned Action Plan row
(`source="strategist"`); pushing approved proposals into Asana rides the
separate Asana-push build.

---

## 2b. Module legibility — how the strategist reads the instruments

LLM strategists fail on *misreading instruments* more than on reasoning: a
geo-grid `average_rank` of 2.0 over 3/25 pins read as "ranking #2," a null
GSC position read as a rank loss, one ChatGPT answer-flip read as a trend.
Five mechanisms make the measuring modules legible; the first two also
upgrade SerMastr's existing Q&A *before* the strategist ships.

1. **Module cards** — a compact "how to read this instrument" doc per
   measuring module, written for agents (what it measures, direction,
   field-by-field semantics, known blind spots, one worked misreading).
   Live at **`docs/agents/module-cards/`** (rank-tracker, geogrid-tracker,
   labs-ai-visibility; extend with gsc-research / offpage / episodes as the
   digest grows). Injected into every strategist run and loadable by
   SerMastr's context providers today.
2. **Standard signal envelope** — the digest normalizes every module's output
   to one shape:
   `{module, keyword, metric, value, baseline, delta, direction
   (lower_is_better|higher_is_better), status (improving|stable|declining|
   insufficient_data — computed deterministically, never by the LLM),
   coverage ("22/25 pins" | "14d GSC" | "6 engines"), measured_at, cadence,
   stale}`.
   `direction` kills position-vs-visibility mix-ups; `status` keeps trend
   arithmetic out of the LLM entirely.
3. **The keyword passport** — the digest groups by **keyword, not module**:
   one entry per keyword showing organic + maps + AI-answer state side by
   side. Cross-channel synthesis is the strategist's job; the passport makes
   the join free ("organic #4 stable · maps 22/25 pins declining, episode
   open 2wk · invisible in 4/6 AI engines").
4. **Explicit staleness** — every signal carries `measured_at` + expected
   cadence; the assembler flags violations ("grid scan 19 days old on a
   weekly cadence — stale") so the strategist can't reason confidently over
   dead data.
5. **Self-documenting drill-down tools** — each tool description restates its
   semantics and traps (e.g. "`average_rank` is over found pins only — check
   `found_pins` before comparing across scans").

All five are **Phase 0 deliverables** (the assembler implements 2–4; the cards
are 1; tool descriptions are 5). Feedback loop: deliberately tricky SerMastr
questions ("how are we doing on maps for X?") surface misreadings; each
misreading becomes a line in a module card.

---

## 3. Halt-and-ask boundaries (hard-coded, from `_ORCHESTRATOR.md` §3/§6)

The strategist's system prompt AND the surrounding code both enforce:

1. **Never executes.** No tool it holds mutates anything (all reads). Paid
   reads (`audit_page`) are capped per run.
2. **Mandatory human passthroughs** — it may *brief*, never *decide*:
   manual action / deindexing (Freeze Protocol), GBP suspension or duplicate
   listing, margin below 50%, separate-entity/DBA recommendations (vector),
   overclock diagrams outside the pre-push-gate thresholds, the 6-week
   strategy review itself.
3. **No SOP-territory improvisation.** A decision no SOP owns → emitted as a
   `question`, never a `proposal` (registry rule §1).
4. **Conflicts are reported, not resolved** (§3.2) — if two SOPs appear to
   collide on the case, that's a `question` for the humans + a note to fix the
   docs.
5. **Frozen client** → observation-only briefing; no proposals (freeze pauses
   decide+output, and the strategist is part of "decide").
6. **Working-model humility**: SOP claims labeled *(working model)* are cited
   as the agency's operating theory, not fact.

---

## 4. Surfaces

- **Action Plan page**: a "Strategist Review" card — latest assessment,
  proposals with Approve / Dismiss, open questions highlighted. (The Action
  Plan is already the team's to-do surface; strategy lives next to the tasks
  it shapes.)
- **Slack (SerMastr)**: weekly digest per reviewed client (only when the run
  produced non-obvious findings — an empty/confirmatory review posts nothing);
  `strategy review for <client>` runs one on demand; approvals reuse the
  existing reply-*yes* confirm pattern.
- **Escalation briefs**: on `episode_escalated`, the critical notification
  gains a link to the prepared brief instead of a bare alert.

---

## 5. Data model & config

- Migration: **`strategy_reviews`** (as in §2 output contract; proposals as
  JSONB with per-proposal status patched in place; RLS on, service-role only).
  Widen `async_jobs.job_type` with **`strategy_review`**.
- Config (`config.py`): `strategist_enabled` (default **false** until smoke-
  tested), `strategist_model` (default `claude-sonnet-4-6`; the escalation-
  brief trigger may warrant an Opus-class override later), `strategist_max_drilldowns`
  (4), `strategist_weekly_weekday`, `strategist_digest_budget_tokens` (25k).
- Runs as an `async_jobs` job (`strategy_review`), enqueued by the shared
  scheduler / SerMastr / the API — same infra as everything else. API:
  `POST /clients/{id}/strategy-review` + `GET /clients/{id}/strategy-reviews`
  + `POST /strategy-proposals/{review_id}/{idx}` (approve/dismiss).

---

## 6. Cost model (per client per month)

Assumptions: Sonnet-class pricing (~$3/M input, ~$15/M output); base run ≈ 25k
in / 3k out ≈ **$0.12**; drill-downs add ~5–10k in / 1k out each.

| Scenario | Runs/mo | Est. cost |
|---|---|---|
| Quiet client (no active signals) | 0 scheduled + 0 events | **$0** |
| Typical active client | 4 weekly + ~2 event/on-demand, ~1 drill-down avg | **≈ $1–2/mo** |
| Heavy month (sitewide episode, deep dives) | 8 runs, 3 drill-downs avg | **≈ $3–5/mo** |

Rounding error against any retainer; the deterministic layer stays free. An
Opus-class model for escalation briefs only would roughly 5× those per-run
numbers on the 1–2 briefs/mo they'd apply to.

---

## 7. Phasing

- **Phase 0** — migration + `build_strategy_digest` (pure: signal envelope,
  keyword passport, staleness flags — §2b) + SOP section retrieval over
  `docs/sops/` + module-card injection (`docs/agents/module-cards/`, written).
  Optional quick win: wire the cards into SerMastr's context providers now.
  Unit tests on the digest budgeting + envelope normalization.
- **Phase 1** — the strategist run (on-demand API only, `strategist_enabled`
  gate), output to `strategy_reviews`; Action Plan "Strategist Review" card
  with Approve/Dismiss.
- **Phase 2** — weekly scheduled runs (active-signal-gated) + Slack digest +
  SerMastr `strategy review for <client>`.
- **Phase 3** — drill-down tools (start with `serp_deep_dive` +
  `geogrid_history`; `audit_page` behind a per-run paid-call cap).
- **Phase 4** — escalation briefs riding `episode_escalated` /
  `sitewide_decline` notifications.
- **Phase 5** (rides the Asana-push build) — approved proposal → Asana task,
  assigned per the roles matrix.

**Smoke gate between Phase 1 and 2:** run on-demand reviews for 2–3 real
clients; Kyle/Ryan judge whether the proposals would have been *their* calls.
Only schedule it weekly once the judgment quality earns it.

## 8. Non-goals (v1 cut list)

- No auto-execution of anything, ever (not a v1 cut — a standing rule).
- No per-domain standing agents (decision record in §1).
- No autonomous SOP edits (it may *propose* doc fixes as `questions`).
- No client-facing output (the Client Reporting module owns that).
- Not a replacement for the 6-week human review — it preps the brief.

## 9. Open decisions (defaults chosen; flag to change)

1. **Model**: Sonnet-class for all runs (default) vs Opus-class for escalation
   briefs. *Default: Sonnet everywhere; revisit after the smoke gate.*
2. **Digest destination**: shared Slack channel (default, matches notifications
   v1) vs DM to Kyle/Ryan.
3. **Weekly scope**: active-signal clients only (default) vs all clients.
4. **Approval surface**: Action Plan card (default) vs Slack-first.
