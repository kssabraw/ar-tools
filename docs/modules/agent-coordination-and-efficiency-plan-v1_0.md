# Agent Coordination & Efficiency — plan v1.0

**Status:** BUILT (2026-09-01, PR #943 — Phases 0–4). All workstreams ship **dark** (default-off flags); merging changes nothing until the flags are set on PLATFORM. Enable order per workstream is in the PR body.

This is the authority doc for three linked capabilities the owner asked for on 2026-09-01, on top of the existing SerMaStr / PACE / DORA agents and the two audit-log learning loops (`sermastr_audit` #937, `pace_audit` #935):

1. **SerMaStr self-analysis** — SerMaStr sees which tactics work best, **reports that to humans directly** (its own campaign lane), and **leans into the winners** automatically.
2. **PACE process-efficiency detection** — PACE, as the project manager, proactively surfaces process inefficiencies. These are **addressed to DORA, not reported to humans by PACE.**
3. **DORA agency-wide process efficiency** — DORA sees the whole picture across every agent, **including how the agents coordinate/communicate**, synthesises where processes can be made more efficient, and **is the single voice that reports process efficiency to humans.**

## Locked framing (owner, 2026-09-01)

- **Reporting lanes stay separate.** SerMaStr reports campaign updates/successes/failures/recommendations (incl. tactic effectiveness). PACE reports PM issues/recommendations. DORA owns **process efficiency + inter-agent coordination** and reports that. Each agent keeps its own human-facing reporting; DORA does **not** replace SerMaStr/PACE reporting.
- **"Not human-in-the-loop" is scoped to process efficiencies only.** Individual SEO/PM actions keep their existing human-approval gates. Autonomy tiers, the freeze protocol, and DORA's read-only "eyes, not hands" framing are untouched. DORA *proposes* efficiency gains to humans; it never executes them.
- **Inter-agent communication = Both.** Analyse how work already flows between agents for inefficiency, AND stand up a real agent-to-agent handoff channel DORA oversees. v1 instruments four concrete handoffs rather than a free-form agent chat (below).
- **DORA delivers via LLM analysis** — weekly ops digest + on-demand `/director` chat + as-detected `ops_efficiency` alerts.

## Workstreams

### WS1 — SerMaStr tactic self-analysis (`sermastr_audit`)

Reads `sermastr_action_log` + reused `interventions` verdicts + `clients.client_type`. **No migration.**

- `tactic_performance(rows, client_types, min_samples)` — pure. Rolls the log into per-**kind**, per-**client_type** (local/enterprise), per-**trigger** (scheduled/escalation/monthly_plan_review/on_demand) buckets, each with `approval_rate`, `worked_rate`, `no_effect_rate`, and a `signal`: `measured` (≥ min graded outcomes), `approval-only` (≥ min decided but unproven), or `thin` (excluded from ranking). `leaders` = the working/approved tactics ranked by a `rank_score` (measured worked-rate; approval-only discounted ×0.7 as unproven).
- **Human report** — the existing weekly SerMaStr digest (`maybe_emit_weekly_learning`, kind `strategy_learning_digest`, gated on `sermastr_audit_digest_weekday`) is upgraded: when `sermastr_self_analysis_enabled`, its body becomes the richer "what's working best — lean in / what to retire" report (deterministic base, best-effort LLM narrative via `report_llm`, `sermastr_self_analysis_model`). Reports to the **strategy channel** (SerMaStr's own lane).
- **On-demand** — `_ctx_tactic_performance` context provider (per-client) + an agency-wide block in `build_portfolio_context`, so SerMaStr answers "what's working best right now?" grounded, in chat and Slack. Gated on `sermastr_self_analysis_enabled`.
- **Self-steer** — the existing `build_track_record_block` (in-review prompt) is the "lean into it" mechanism; unchanged.

Flags: `sermastr_self_analysis_enabled` (False), `sermastr_self_analysis_model`.

### WS2 — PACE process-efficiency detectors (`pace_efficiency`)

Migration `pace_efficiency_findings`. Deterministic detectors (no LLM) from data PACE already computes, run daily inline on the shared scheduler; upsert by a stable `finding_key`, auto-resolve when no longer detected. Categories: `slip_bottleneck`, `rework`, `cadence`, `producer_noise`, `duplicate_churn`. Findings are proposal-worded and **addressed to DORA** (WS3 notice + WS4 provider), never reported to humans by PACE.

Flag: `pace_efficiency_enabled` (False).

### WS3 — Agent-to-agent coordination bus (`agent_bus`)

Migration `agent_messages` — a DB-backed message/inbox log (no new infra; polled on each agent's scheduled run, consistent with the "no queue beyond async_jobs" rule). Fields: `from_agent`, `to_agent` (or `broadcast`), `client_id`, `kind` (handoff/request/notice/blocker/ack), `subject`, `body`, `ref`, `correlation_id` (threads a handoff), `status` (open/read/acted/dismissed), timestamps.

`services/agent_bus.py` — pure message/inbox/coordination-metric helpers (latency, unacted, back-and-forth loops, ignored messages) + best-effort post/read/ack.

**v1 instrumented handoffs** (make today's implicit handoffs explicit + measurable):
1. SerMaStr approved proposal → `handoff` to PACE; PACE placing it → `ack`.
2. PACE capacity blocker → `request` to SerMaStr.
3. PACE efficiency finding → `notice` to DORA.
4. QA repeated-fail pattern → `notice` to PACE + DORA.

Cadence reality: agents run on different clocks (PACE daily, SerMaStr weekly), so a reply lands on the recipient's next run — DORA measures that lag as a coordination signal. All posting is additive + best-effort (never breaks a hot path).

Flag: `agent_bus_enabled` (False).

### WS4 — DORA agency-wide process-efficiency analysis (`services/director/efficiency.py`)

New DORA providers `prov_pace_efficiency` (WS2 findings) + `prov_coordination` (WS3 metrics), reusing existing `prov_strategy`/`prov_autonomy`/`prov_duplicates`/`prov_interventions` (effort spent on `no_effect` tactics = a process leak). Pure synthesis of the whole picture → LLM pass (`director_efficiency_model`) → ranked, proposal-worded process-efficiency recommendations (read-only/advisory).

Delivery: weekly ops-digest section + on-demand `/director` chat + `ops_efficiency` alert on a significant new inefficiency (deduped, routed to #dora via `DIRECTOR_CHANNEL_KINDS`, falling back to #pace).

Flags: `director_efficiency_enabled` (False), `director_efficiency_model`. `ops_efficiency` added to the PACE + DORA notification frozensets.

## Phasing

- **Phase 0** — this doc.
- **Phase 1** — WS1 (independent; delivers alone).
- **Phase 2** — WS2 (detectors + findings table).
- **Phase 3** — WS3 (bus + four instrumented handoffs).
- **Phase 4** — WS4 (DORA consumes WS2+WS3, reports to humans).

Each phase: pure-logic unit tests; platform-api pytest green before the PR opens. All flags default-off; enable order documented in the PR.

## What this is NOT

Not recursive self-modification. Nothing retrains a model or rewrites code. The learning loops steer prompts / rank proposals; the efficiency layer analyses and proposes to humans. Every concrete SEO/PM action keeps its human-approval gate.
