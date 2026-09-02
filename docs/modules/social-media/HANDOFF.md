# Social Media Module — Handoff

> Module-scoped handoff for the **Social Media Manager + Content Creator** module.
> Not the root `/HANDOFF.md` (the suite-wide one). Read `CLAUDE.md` (this folder) for the
> build primer; this file is **current state + what to do next**.

## Current state (2026-09-02)

- **Design complete; no code written.** The module has been fully designed via an owner grill +
  an adversarial review; all decisions are recorded.
- **Everything is on PR #952** (branch `claude/reload-skills-w3hzhd`), CI green. Docs only.
- Deliverables on the PR:
  - `docs/modules/social-media-module-context.md` (glossary)
  - `docs/modules/social-media-module-prd-v1_0.md` (PRD — authoritative)
  - `docs/adr/0001..0003` (PostPeer-adapter · analyze-in-place · autonomy-domain-executor)
  - `docs/modules/social-media-cost-model-v1_0.md` (A3)
  - `docs/modules/social-media-failure-handling-v1_0.md` (A4)
  - `docs/modules/social-media-vendor-confirm-postpeer-v1_0.md` (A2)
  - `docs/modules/social-media/CLAUDE.md` + this file
- **Adversarial review: all findings resolved or tracked.** 1 Blocking (image aspect ratio →
  nano-banana Pro), 1 Major (budget fail-open → fail-closed), 4 Minor, 4 Advisory — all applied
  or captured as sourced open items. See the PR commit history.

## The P0 gate — answer these with PostPeer BEFORE building the calendar

(Full context: `../social-media-vendor-confirm-postpeer-v1_0.md`.) The P0 smoke test is the go/no-go.
1. **X link-post billing** — is a post to X *containing a link* billed the same as a non-link post,
   or surcharged/capped? (PostPeer is silent; the underlying X fee is 13× — $0.20 vs $0.015.)
2. **IG carousel** — live yet, or still roadmap? ETA? (Currently roadmap → v1 ships single-image IG.)
3. **SLA / status page / webhook delivery guarantee** — do any exist? (None found publicly.)
4. **Legal entity + support channel** — undisclosed publicly; needed for a production dependency + DPA.

**Already confirmed (no longer open):** PostPeer publishes under its **own reviewed apps** (managed
OAuth — one-click client connect); platform coverage; IG Business/Creator requirement; pricing.

## Provisioning needed before P0 code runs

New credentials/accounts on the **PLATFORM** Railway service (none exist yet):
- **`POSTPEER_API_KEY`** — PostPeer account + API key.
- **`APIFY_API_TOKEN`** — Apify account (+ vet the specific per-platform actors).
- **`TWELVELABS_API_KEY`** — TwelveLabs account (free tier: 600 min).
- **`GEMINI_API_KEY`** — ⚠️ **currently dormant** (commented out in `.env.example`, defaults to `""`
  in `config.py`). Required for **nano-banana Pro** image generation; without it image gen no-ops.
- **cobalt** — self-hosted instance (Docker on Railway). **P5 only** — not needed for v1.
- New `config.py` settings: `postpeer_api_key`, `apify_api_token`, `twelvelabs_api_key`,
  `social_daily_call_budget`, `nano_banana_pro_model` (Gemini 3 Pro Image id), plus the module flags.

## Open decisions for the owner (not yet made)

- **Mixed image path** — build the 2.5-Flash-for-square / Pro-for-aspect-ratio renderer in v1 (halves
  the dominant image cost) or ship Pro-only first?
- **v1 Instagram scope** — feed-only, or include single-media Reels/Stories (PostPeer supports both as
  single-media)?
- **Default per-client monthly cost ceiling** in the Social Policy (the cost model says Base ≈ $45/client/mo).
- **Autonomy rollout** — which clients (if any) reach the top tier for auto-publish, and when.

## Next actions, in order

1. **Answer the four PostPeer questions** (owner/vendor call) — gates everything.
2. **P0 Foundations + the connect-and-post smoke test** — proves PostPeer end-to-end and de-risks the
   indie-vendor dependency before the calendar is built on it.
3. **P1 Competitor research**, then **P2 Creator**, **P3 Manager+publish**, **P4 autonomy**, **P5 video**.

## Gotchas discovered during design (don't re-learn these)

- **Budget meter:** `keyword_research.reserve_budget` is **fail-OPEN** on RPC error; the fail-closed
  one is `autonomy_budget.reserve`. Copy the latter for spend.
- **`nano_banana.py` (2.5 Flash) sends no `imageConfig`/`aspectRatio`** — 1:1 output only. A Pro-based
  renderer that passes `aspectRatio` is required, or the Platform-Spec validator flags every
  non-square Draft un-approvable.
- **IG carousels are not live in PostPeer** (single-media adapter). Don't design a carousel Draft type
  for v1.
- **PostPeer OAuth tokens are held by PostPeer, not us** — don't build a token store.
- **`client_competitors` has partial unique indexes** (`WHERE domain/place_id IS NOT NULL`) — social
  handle-only rows escape dedup; use a child `social_competitor_handles` table.
- **postpeer.dev is egress-blocked in the Claude Code sandbox** — direct WebFetch fails; use search or
  ask the owner to fetch. (This is why the four vendor questions couldn't be closed automatically.)
- **Cost:** the X link tax is ~$60/mo at realistic volume (~10% X-link share), NOT the ~$600 an early
  draft implied (it miscounted all posts as link-posts). The **nano-banana Pro image (~$0.11/post)** is
  the dominant cost line.

## References

Root `/CLAUDE.md` (suite authority) · this folder's `CLAUDE.md` (module primer) · the six design docs
listed above · PR #952.
