---
name: adversarial-review
description: Adversarially reviews a PRD, plan, or spec document against reality — the codebase, its own internal logic, and other repo docs. Hunts six failure classes (internal contradictions, spec-vs-reality drift, unfalsifiable claims, missing edge cases, smuggled assumptions, understated scope/complexity), weighted toward drift and missing edge cases. Every finding is grounded in live evidence gathered during the review, survives a falsification pass, and cites a concrete scenario — never a vague "this could fail." Use when asked to adversarially review, red-team, stress-test, or critique a PRD, plan, or spec doc. NOT for reviewing code diffs — use code-review for that.
---

# Adversarial Review

A PRD/plan review that hunts for defects the way `code-review` hunts for bugs: every claim gets checked against something real before it's reported, every finding shows its work, and silence about a category means it was checked and found clean — never that it was skipped.

## Target

Take the document path as an argument. If none is given and it isn't obvious from the conversation, ask which document — don't guess.

Read the **entire** target document before starting. Note any internal "status" markers it carries (e.g. "PROPOSED, not yet built," "owner ruling 2026-08-08," "SUPERSEDES v1_3") — they matter for scoping findings (see Weighting) and for the precedence rule below.

## The six categories

Hunt all six on every review — there is no effort dial. A PRD reviewed once and left alone accumulates drift silently; a shallow pass defeats the point.

1. **Internal contradictions** — the doc disagrees with itself (§3 says X is out of scope, §7 assumes X).
2. **Spec-vs-reality drift** — the doc claims a behavior, default, or decision that the actual code/config/migrations no longer match.
3. **Unfalsifiable / unmeasurable claims** — success criteria or assertions that can't actually be checked ("users will find this intuitive," "this improves quality").
4. **Missing edge cases / failure modes** — the happy path is specified; error, concurrency, partial-failure, or empty-state paths aren't.
5. **Smuggled assumptions** — claims stated as fact that are actually unvalidated guesses (market size, user behavior, "competitors don't do this," "this is rare").
6. **Scope-creep / hidden complexity** — a change described as simple that actually requires N other systems to change, understated in the doc.

**Weighting.** For a doc describing something already built (status markers like "built," "live," "merged," dated change history), weight toward **#2 (drift)** and **#4 (missing edge cases)** — these docs are living build logs, and the highest-yield failure is the doc no longer matching what's running. For a doc still describing something proposed or not yet built, weight toward **#5 (smuggled assumptions)** — that's where an unbuilt plan is most likely to be quietly resting on something nobody validated.

Weighting means *dig deepest here*, not *skip the others*. Every category still gets an explicit verdict (see Output).

## Grounding — mandatory

A finding in categories #1, #2, #4, or #6 must cite **live evidence gathered during this review**: an actual `Read`/`Grep`/`Glob` of the code, config, migration, test, or other doc it's checked against. Not memory. Not a re-reading of the target doc's own prose treated as its own proof.

For a large or cross-cutting doc, dispatch `Explore` or `general-purpose` subagents to do the grounding search rather than skimming — the review is only as good as what it actually checked.

If a claim can't be confirmed or refuted after a real search, it is **not** a confirmed finding. Report it as **"Unverifiable claim"** — say what you checked and why it was inconclusive — rather than asserting drift you didn't actually verify.

Categories #3 and #5 (unfalsifiable claims, smuggled assumptions) don't need code-grounding by nature — the finding *is* that nothing grounds them. State plainly that no evidence exists to check against, which is itself the finding.

## Precedence when sources disagree

When the target doc conflicts with the code, with another doc, or with itself across time:

1. Check whether the repo **documents** an authority order (a precedence table, "authoritative doc" language, a dated "owner ruling" or "reversed" note, a "supersedes" marker). If one exists, apply it and cite it in the finding.
2. If no documented precedence exists, **do not invent one**. Report the conflict as a conflict — name both sides and where they live — and let a human resolve it.

## Concreteness bar

"This could fail" is not a finding. Every finding needs a **specific scenario**: a real input, state, sequence of events, or example that walks to the actual failure. Show the trace — what happens, step by step, and where it breaks — not just that something might go wrong.

## Falsification pass

Before finalizing, go back over every drafted finding and try to break it:

- Search harder for evidence you might have missed.
- Check whether the doc actually reconciles the apparent contradiction elsewhere (a later section, a dated update, an explicit "reversed" note).
- Check whether what looks like an oversight is a documented, deliberate scope cut.
- Check whether the "drift" is actually the doc being *ahead* of stale evidence you grounded against (e.g., a migration file that predates a later one).

Drop findings that don't survive. Downgrade findings that partially survive (e.g., "Unverifiable claim" instead of "Confirmed drift"). Keep the pass lightweight — a prompted self-check, not a separate investigation per finding.

Also dedupe at this stage: if three findings are really one root cause wearing three hats, report the root cause once and note where it surfaces.

## Output

Plain ranked text, most severe first. If this session exposes a structured findings-reporting tool intended for reviews, you may use it *in addition to* — never instead of — the list below, mapping its fields onto this shape.

**Severity scale:**
- **Blocking** — the doc as written cannot be built/shipped correctly, or actively contradicts something already live.
- **Major** — a real gap or risk that will bite in production or mislead whoever builds from this.
- **Minor** — worth fixing, low material risk.
- **Advisory** — a genuine but soft concern (e.g., a smuggled assumption worth flagging to the doc's owner, not a defect per se).

**Per finding:**

```
[SEVERITY] Category — Title
Location: <doc section/line>
Evidence: <what was checked, where, and what it showed — file:line for code/config/other docs>
Scenario: <the concrete input/state/sequence that exposes it>
Recommendation: <optional — what would resolve it>
```

**Per category, always, even when severity list is empty:**

```
## <Category name> — <N findings | clean>
<If clean: state what was checked to reach that verdict, not just "none found.">
```

## What not to do

- Don't rewrite or fix the document — this is a review, not an edit.
- Don't report a finding without a cited grounding check (or an explicit "unverifiable").
- Don't invent a precedence ranking the repo doesn't document.
- Don't pad the list — restatements of one root cause are one finding.
- Don't silently skip a category because it turned up nothing.
