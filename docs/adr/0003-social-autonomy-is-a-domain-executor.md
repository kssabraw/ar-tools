# Social autonomy is a domain executor reusing the autonomy guardrails, not a new persona

**Status:** accepted (2026-09-02)

The endgame for the Social Media module is an **autonomous social department** —
humans approve content and tune the agents; the department otherwise plans,
produces, schedules and (at the top tier) publishes on its own. The suite's
existing agents are split **by disposition, not by domain** (SerMaStr proposes,
PACE executes/coordinates, QA judges, DORA reconciles), and it already built the
autonomous-execution machinery — the **autonomy executor** with tiers,
`autonomy_policy.classify` (auto/propose/escalate), a fail-closed budget
governor, freeze, and the DORA pre-flight veto. So social autonomy is built as a
**domain executor that reuses those guardrails**, not as a new by-disposition
persona: a **Social Manager** orchestration *loop* (plan → dispatch creation →
route to approval → schedule → top-tier publish) that dispatches a **Social
Creator** *worker* loop. Neither is a new conversational persona; both stay
legible through SerMaStr/PACE/QA/DORA.

## Considered options

- **Two new standalone conversational personas** ("Social Manager" + "Social
  Creator" you chat with). Rejected: cuts the by-disposition architecture along a
  by-domain seam, substantially duplicates PACE (coordination) and the generation
  pipeline, and adds hands for DORA to reconcile — against the "build the eyes,
  defer the hands / not a new persona until a real gap forces it" ruling that
  justified DORA.
- **A bespoke social autonomy engine.** Rejected: re-implements tiers, budget
  governor, freeze, and veto that already exist and are proven.

## Consequences

- Social autonomy inherits every existing guardrail: autonomy tiers, fail-closed
  budget reservation, freeze gating, the DORA veto, and human approval by
  default.
- **Graduated approval** ties approval strictness to the client's autonomy tier
  (approve-every → batch/approve-by-exception → top-tier auto-publish with
  post-hoc review), so "minimal supervision" is real without abandoning control.
- Humans tune the executor through a per-client **Social Policy** (cadence,
  topics, tone/angle, competitor focus, budget, tier, and editable image/text
  generation prompts) — a tuned prompt still passes the deterministic Platform-Spec
  + voice-card validators; tuning steers output, never bypasses the brand/safety
  gates.
- This is the suite's first *domain-scoped* orchestration; a dedicated
  conversational "Social" persona remains a deferred, optional addition only if
  talking-to-it proves valuable.
