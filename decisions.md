# decisions.md

A running log of open/pending product decisions to discuss, and settled ones with
their reasoning. Append new entries; don't edit or delete old ones.

Status legend: **OPEN** (needs an owner decision) · **DECIDED** · **DEFERRED**.

---

## QA Agent — auto-fix machine-generated fails (PR 3 of the QA improvement work)

**Status: OPEN** — scope parked for later discussion (owner, 2026-08-28). PRs 1 & 2 of the
QA improvement work shipped (auto-resolve suite deliverables; gate the paid visual check +
fold the nlp score — see PR #870). PR 3 is **not built** pending this decision.

**Context — what PR 3 would do.** Today a QA `fail` creates `Rework: <check>` subtasks for a
human (the self-closing rework loop). For deliverables the suite can regenerate, a fail could
instead enqueue the existing reoptimize job (deficiencies built from QA's failed checks) and
re-QA the result — no human in the loop. It would ride the autonomy rails that already exist:
`autonomy_policy.classify` (freeze/tier/budget/rate-cap in one pure call), `autonomy_budget.reserve`
(atomic spend gate), and the reoptimize jobs (`blog_reoptimize`, `local_seo_reoptimize_url`,
`ecommerce_reoptimize_url`).

**The blocking discovery — the "publish gap".** QA rubrics split by what they read:

- **Blog** (`blog_article`) reads the *generated artifact* — the run's `sources_cited` markdown.
  `blog_reoptimize` regenerates that artifact, so re-QA reads the new version and **the loop
  fully closes with no publish step.** Genuinely autonomous.
- **local_seo / ecommerce / website_page** read the **live URL**. Reoptimize updates the *stored
  draft*, but **republishing to the live site is human (Tier 3 auto-publish, deliberately held by
  the owner).** So auto-fix → re-QA on the live URL would re-read the *old* page and loop to the
  retry cap — the rewrite happens but never reaches what QA checks.

**The scope options (the OPEN decision):**
1. **Blog only (v1).** Only blog fails auto-fix; the loop fully closes without any publish. Page
   rubrics stay Rework-only until Tier-3 auto-publish is decided. Cleanest, no publish risk.
2. **Blog + hybrid pages.** Blog fully closes; for Local SEO/ecommerce/website a fail also
   auto-reoptimizes the draft, then creates ONE human "Republish the improved page" Rework task
   (machine rewrites, human clicks publish).
3. **All four incl. auto-republish.** Requires enabling Tier-3 client-site auto-publish, which the
   owner has explicitly held. Not recommended for v1.

**Decided sub-points (locked, to fold in whenever PR 3 is built):**
- **Retry cap = 2** autonomous reoptimize→re-QA cycles per task (counted from `qa_reviews`
  history), then fall back to human `Rework:` subtasks. (owner, 2026-08-28)
- **Gating (proposed default, confirm at build):** double flag `qa_enabled` AND a new
  `qa_autofix_enabled` (default False, ships dark); each fix classified through
  `autonomy_policy.classify` so it only auto-runs for a client opted into autonomy **tier ≥ 2**,
  with budget reserved via the governor and freeze-awareness for free; refusal / not-opted-in /
  frozen → human Rework subtasks.
- **Human deliverables stay Rework-only.** Guest posts / niche edits / citations / press releases /
  map embeds live on third-party sites the suite can't regenerate — never auto-fixed.

**What must be decided to unblock:** the scope option (1/2/3), and — if 3 — whether Tier-3
client-site auto-publish is unheld.
