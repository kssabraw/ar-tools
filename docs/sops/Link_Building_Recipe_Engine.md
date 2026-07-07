# Link Building & Campaign Recipe Engine

**Current as of:** 03 July 2026
**Purpose:** Turn a client's inputs — page/site state, competition, diagnosis, and monthly retainer — into a **costed, assigned monthly task plan**. This is the decision engine that operates on the SOP library; it references the Link Building master table (costs/specs) and `_ORCHESTRATOR.md` (roles, prioritization, shared definitions) rather than duplicating them.

> **Cross-references:** costs/specs → Link Building SOP master table · assignment/priority → `_ORCHESTRATOR.md` §6 · competition definition, GBP rules → shared definitions · diagnosis → Maps SOP Part 4 / Link Building strategy.

---

## 1. The Allocation Formula

Run in order:

```
1. Deployable = Retainer × (1 − Margin)
     • Margin target = 66%  → Deployable = Retainer × 0.34
     • Stagnating / ranking drop → Margin may drop to 50% → Deployable = Retainer × 0.50
     • Below 50% margin (more spend) → STOP, escalate to Kyle/Ryan
2. Deployable −= $150 reporting (every client, every month)
3. Deployable −= special-project labor (web dev @ $150/hr 1hr min, extra meetings, redesigns) if any this month
4. Deployable −= Baseline Stack (below)
5. Remaining = Deployable − above → spent by Diagnose-and-Fund (§3)
6. If Remaining < 0 at any step → the baseline alone exceeds budget → flag: client under-funded, escalate
```

## 2. The Baseline Stack (every client, every month)

| Item | Cost | Assignee (per `_ORCHESTRATOR.md` §6) |
|---|---|---|
| Map Embeds (1 run) | $5 | Ivy |
| 40 Citations | $40 | Minda |
| 4× DAS v2 | $40 | Minda → Ivy |
| 1 Blog Post | $5 | Minda / Ivy |
| GBP Blast (physical/hybrid GBPs only — never SABs) | $5/mo | Minda → Ivy |
| GBP posting, 5×/wk (~20 posts @ $2) | $40/mo | Minda |
| **Baseline subtotal** | **$135** *($130 for SABs)* | |
| + Reporting (always) | $150 | — |
| **Fixed monthly floor** | **$285** *($280 SABs)* | |

*(Agency Assassin — $85/mo — is added to the baseline for clients ≥ $1,200/mo retainer when budget allows; it's flexible, not mandatory.)*

## 3. Diagnose-and-Fund

Spend `Remaining` on the **deficient variable** identified by diagnosis (Maps Part 4 / Link Building strategy), in priority order, until budget runs out.

**When multiple variables are deficient, fund in this order:**
- **Local clients → RD first**, then Link Juice, then Relevance, then Entity.
- **Enterprise / e-commerce → Entity first**, then Link Juice, then RD, then Relevance.

**Fund each deficient variable with its cheapest-effective tools first** (from the master table), respecting all SOP rules (tiering, velocity caps, overclock thresholds, never-disavow, deprecations):

| Deficient variable | Fund with (cheap → strong) |
|---|---|
| **Referring Domains** | DAS v2 $10 · Respect Mah Authoritay v2 $10 · RD100 $10 · Cloud Stack $10 · Citations $40/40 · PR $50 |
| **Link Juice (strength)** | Cloud Stack $10 · Niche edit $50–100 · Guest post >$150 · Google Stack $30 |
| **Contextual Relevance** | Cloud Stack $10 · Niche edit · Guest post (all high-relevance) |
| **Entity / Knowledge Graph** | Content pages $5 · Reddit/LinkedIn/Medium $10 · IFTTT ring $100 (once ever) · RDF-triple placements (via PR/guest post/G stack) · reviews $15 |
| **Reviews (below threshold — Maps Part 3)** | Reviews $15 each (GBP + Trustpilot) until ≥25 and ≥ lowest-in-pack |
| **Maps / GBP (proximity/engagement)** | GBP Blast $5/mo (physical/hybrid only) · Hyper Local GBP Blast $10/mo (weak areas) · GBP Sniper $10/run (campaign start + drops) · GBP posts $2 ea · Agency Assassin $85/mo (≥$1,200) |

**Knowledge-graph build-out** (when entity is the deficiency): fund service pages and blog posts ($5 each) on-vector, plus the entity procedure (Maps SOP Part 5) tools above.

## 4. Worked Example

**Client:** local plumber, $2,000/mo retainer, healthy (66% margin). Diagnosis: stuck at grid spots 4–5, all on-page solved, RD below competition (client true RD 80; SERP tool-avg 18 → true-avg 180 → target 270 = 180 × 1.5; the ~250-RD figure is a guideline, not a cap — Link Building SOP §Referring Domains), reviews at 22 (below 25 threshold).

```
Deployable      = 2000 × 0.34            = $680
− Reporting                              = $150  → $530
− Special projects (none)                = $0    → $530
− Baseline stack ($135)                  = $135  → $395  remaining
Diagnose-and-fund (reviews to threshold first — cheap and gating per Maps Part 3; then local → RD):
  Reviews to threshold: 3 × $15          = $45   → $350   (22→25)
  RD gap ~190 true domains, cheapest-effective:
    4× DAS v2 already in baseline (~400 RD potential)
    + 1× Respect Mah Authoritay v2 ($10, ~200 RD T1) = $10  → $340
    + 1× Cloud Stack ($10, +trust)        = $10   → $330
  GBP Sniper (drop → 1 run)               = $10   → $320
  Remaining $320 → on-vector content ($5 ea):
    up to ~64 pages, capped by production capacity → assign what the team can produce
  (GBP Blast + GBP posting already in the baseline)
```

Output: a task list, each line assigned per §6 roles, totalling ≤ deployable, at the target margin.

## 5. Output Contract (the task plan)

The engine emits a list of task objects:

```
{
  client, month,
  margin_used,               // 66% default / 50% if stagnating-or-drop
  deployable, spent, remaining,
  tasks: [
    { task_type, target_page_or_GBP, quantity, unit_cost, line_cost,
      tier?, anchor_type?, assignee, priority_rank, rationale }
  ],
  flags: []                  // under-funded, unstaffed task, escalation-required, etc.
}
```

**Halt/flag conditions (per `_ORCHESTRATOR.md` §3):** baseline exceeds budget · margin would fall below 50% · a task maps to no assignee · client under active freeze · required data missing.
