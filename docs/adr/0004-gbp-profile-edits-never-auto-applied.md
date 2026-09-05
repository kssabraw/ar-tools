# GBP profile edits are never auto-applied (unlike GBP posts)

**Status:** accepted (2026-09-04)

The GBP Profile Editor module (`docs/modules/gbp-profile-editor-prd-v1_0.md`)
writes three **structured, persistent** fields of a client's Google Business
Profile — the business description, services, and operating hours — via the
Business Information API v1 `locations.patch`. Every edit is **AI-drafted →
operator-reviewed → applied on an explicit human click**, and **nothing is ever
auto-applied in v1**. This is a deliberate divergence from the sibling **GBP
Posts** module, which supports **opt-in auto-publish per schedule** (a schedule
with `auto_publish=True` drafts *and* publishes with no human in the loop, still
freeze-gated).

The two modules share a spine (auth, `gbp_locations`, the connect flow, the
draft→review pattern) but sit at different blast radii. A GBP **post** scrolls
away — a wrong or off-brand one is a transient embarrassment. A GBP **profile
field** *persists on the listing* until someone corrects it: a wrong
description, a mis-typed set of hours, or a bad services list is what the
client's customers see on Google for as long as it stands, and wrong hours can
trip a GBP suspension. Auto-applying a machine-drafted change to that surface is
a materially higher risk than auto-publishing a post, so the approval model is
stricter even though the machinery is nearly identical.

## Considered options

- **Mirror Posts exactly — allow opt-in auto-apply per client/field.** Rejected
  for v1: it puts machine-drafted, persistent, customer-facing changes onto the
  live listing with no human in the loop, on a field where a mistake is
  long-lived and (for hours) suspension-sensitive. The convenience does not
  justify the blast radius until the drafting quality is proven in review.
- **A tiered/graduated approval like the autonomy executor** (auto at a high
  client tier, propose otherwise). Rejected for v1 as premature: there is no
  track record of GBP-field drafting quality to tier on yet, and the module's
  own value (absorbing manual dashboard work) is fully realised by
  draft→review→apply. Revisit only after v1 proves the drafts are reliably good.
- **No auto-apply, ever, in v1 (chosen).** Every edit — manual, AI-drafted, or
  strategist-proposed — requires an explicit operator Apply click; AI *drafts*,
  a human *applies*. Even the strategist loop (a SerMaStr action + an
  Action-Plan producer) only *stages a draft* into the review queue; it never
  applies, which also keeps it consistent with the strategist's "propose, never
  execute" contract.

## Consequences

- The `update_gbp_profile` SerMaStr action and the Action-Plan producer stage a
  `status='draft'` edit; neither can write to Google. A human clicks Apply.
- Apply additionally **re-reads the live field and diffs it against the draft
  snapshot**, aborting into a `live_changed` re-review state rather than
  clobbering an out-of-band dashboard edit made after the draft — the careful
  posture the no-auto-apply stance implies, made concrete.
- A frozen client blocks all applies (`gbp_profile_apply` ∈
  `FREEZE_GATED_JOB_TYPES` + `assert_not_frozen`); drafting still runs during a
  freeze (observation), so nothing is lost.
- Google's asynchronous `pending_review` verdict is surfaced honestly and
  resolved by the `gbp_profile_sync` reconciler — an applied edit is never
  reported "live" until a re-read confirms it.
- If a future version wants auto-apply, it is a real design change (a tiered
  model, a quality track record, likely its own ADR) — not a config flip — and
  this ADR is the record of why v1 withheld it.
