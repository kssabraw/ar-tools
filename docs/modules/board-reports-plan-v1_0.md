# Board Reports — SerMaStr / DORA / PACE as department heads (v1.0)

**Status:** built (behind `board_reports_enabled`, default off).
**Owner ask (2026-09-14):** the three agents should report to the Monday-noon
L10 "as department heads giving reports to a weekly board meeting of the C-suite."

A status *digest* lists exceptions. A department-head *board report* leads with a
verdict, puts every number in context, covers the whole portfolio (green
included), and ends with what the head needs from the board. These three reports
add that shape on top of the deterministic signals the suite already produces.

## The three heads and their remit

| Report | Head | Owns | Channel |
|---|---|---|---|
| PACE board report | VP of Delivery & Operations | Does committed work ship — on time, at sustainable capacity | `#pace` |
| DORA board report | Chief of Staff / COO of the agent operation | Is the four-agent machine reliable; where does automation need governance | `#dora` |
| Client Health board report (SerMaStr) | Chief Client Officer | Are clients getting results; who is at churn risk; where is the growth | strategy channel |

## The shared six-part skeleton

Every report renders the same shape (`services/board_reports/common.py::BoardReport`):

1. **Verdict** — one line + RAG (🟢/🟡/🔴), before any detail.
2. **Scorecard** — the 4–6 numbers that define the department, each with a delta
   and (where one exists) a target.
3. **Wins** — 2–4 highlights.
4. **Risks & actions** — each as *issue → severity → owner → action → ETA*, never a
   bare problem.
5. **Asks of the board** — decisions/resources needed, or "None this week."
6. **Outlook** — what to expect next period.

An optional LLM **department-head memo** (gated on `board_reports_narrative_enabled`,
best-effort via `report_llm` → degrades to the deterministic report) leads the
message in the head's own voice. The numbers are always deterministic; the memo
only phrases them.

## What fills each report (all reused, deterministic)

### PACE — delivery & capacity
- **Scorecard:** completed this week (Δ vs prior week) · overdue · stuck/blocked ·
  unassigned · behind-pace clients · team utilization (real logged hours from
  Everhour when present, else estimate) + over-capacity count.
- **Wins:** top throughput person / category; clients fully on pace.
- **Risks:** over-capacity people (→ rebalance/hire), behind-pace clients (→ review
  plan), overdue pile-ups (→ triage).
- **Asks:** capacity add / reprioritization when the team is over capacity.
- **Outlook:** open committed hours vs weekly capacity.
- Source: `pace_report.build_report` + `task_workload.build_team_workload`.
- **Dollar margin is deferred** until a loaded hourly cost is configured
  (`everhour_loaded_hourly_cost`); the engine (`recipe_engine.build_actual_labor`)
  already exists. v1 reports real utilization, not dollars.

### DORA — operating-model health
- **Scorecard:** open cross-agent seams · PACE reliability (approved %, reverted) ·
  SerMaStr reliability (approved %, worked %) · QA pass rate · autonomy
  executed/proposed/escalated · intervention effectiveness (worked/partial/no-effect).
- **Wins:** high approval/works rate; autonomy executed cleanly; zero unwatched seams.
- **Risks:** each seam (approved-unplaced, proposal-pending, qa-idle,
  content-degraded, duplicate-target, unwatched-source) with named clients + the
  action; open capacity holds.
- **Asks:** the governance calls — expand/restrict autonomy tiers, staff to clear holds.
- **Outlook:** reliability trend note.
- Source: `director.read_model.build_read_model(None, today)` (no fresh queries).

### Client Health (SerMaStr) — client results *(the new piece)*
The genuinely missing report: SerMaStr's per-client reviews are deep but
active-signal-gated (quiet clients vanish) and arrive as N messages. This is one
scannable scorecard, **every non-archived client, every week**, green included.
- **Per-client row:** RAG · goals on/off track · organic (page-1 count, avg
  position, top mover) · maps pack presence % · AI visibility % · GBP leads
  (calls Δ) · open alerts · FROZEN flag.
- **Portfolio scorecard:** clients 🟢/🟡/🔴 · goals on track · frozen · portfolio
  page-1 keywords · open alerts · quick wins (striking distance).
- **Wins:** biggest climbers; goals achieved.
- **Risks:** red accounts (frozen → escalate; overdue goals → recovery plan).
- **Opportunities:** quick-win count.
- **Asks:** budget reallocation to at-risk accounts (named).
- Source (all deterministic, no paid calls): `campaign_goals.assess_goals`,
  `rank_status.compute_keyword_summary` + `rank_summary.build_rank_summary`,
  `maps_scan_results` (reporting scans only), `brand_service.get_trends`,
  `gbp_metrics_read.build_growth_cards`, `rank_alerts`/`maps_alerts`,
  `freeze.is_frozen`.

### Per-client RAG (Client Health)
- **red** — frozen, OR any goal overdue, OR any keyword at deindex risk.
- **yellow** — any goal behind, OR organic net-declining, OR any open alert, OR
  maps/AI declining.
- **green** — otherwise.
Portfolio RAG = worst client RAG.

## Scheduling & delivery
- One weekly block on the shared `gsc_scheduler`, Monday (`board_reports_weekday`,
  default 0 = Mon), fired at the shared `gsc_ingest_hour_utc` (08:00 UTC ≈
  ~1am PT Mon — before the noon L10). Self-gated on `board_reports_enabled`.
- Runs off the event loop (`asyncio.to_thread`) so the N-client scorecard + any
  memo never block the scheduler.
- **Delivery is PDF-only by default** (owner ruling 2026-09-14): each report is
  rendered to PDF (`common.render_html` → `client_report.render_pdf` WeasyPrint)
  and uploaded to `board_reports_drive_folder_id` via the Apps Script webhook
  (`google_docs.upload_pdf`) — the sole output. Driven with `asyncio.run` since
  the report runs in the scheduler's worker thread. Gated on the folder id +
  `google_apps_script_url`.
- **Slack + in-app posting is off by default** (`board_reports_slack_enabled`):
  when on, the reports also post via `notifications.emit` — `pace_board_report` →
  `#pace`, `ops_board_report` → `#dora`, `client_board_report` → strategy channel,
  deduped per ISO week. The routing kinds exist regardless; they're just inert
  while the flag is off.
- **Runs every Monday including all-green weeks** (a board wants the full picture)
  — the deliberate opposite of the suppress-on-quiet exception digests.

## Overlap note (operational)
With PDF-only delivery the board reports post nothing to Slack, so there's no
double-post. The plain weekly PACE delivery report (`pace_report_weekday`) is now
redundant Slack content duplicating the PACE board report — unset
`PACE_REPORT_WEEKDAY` when the board reports go live. DORA's exception `ops_digest`
and the PACE daily digest are complementary (daily/exception) and can stay.

## Config (all in `config.py`)
- `board_reports_enabled` (bool, default False) — master gate.
- `board_reports_weekday` (int, default 0 = Monday).
- `board_reports_narrative_enabled` (bool, default True) — the LLM memo (best-effort).
- `board_reports_narrative_model` / `board_reports_narrative_provider` — memo LLM.
- `board_reports_drive_folder_id` — Drive folder for the PDF (empty ⇒ no PDF).
- `board_reports_slack_enabled` (bool, default False) — PDF-only when off; also
  post to Slack + the in-app feed when on.

## Deferred (fast-follow)
- Dollar margin on PACE once a loaded hourly cost is set.
- 30d/90d/since-start comparison horizons on the Client Health scorecard (the
  client-report module already has `build_multi_comparisons`).
- A web page rendering the same three reports (today they're Slack + in-app feed).
