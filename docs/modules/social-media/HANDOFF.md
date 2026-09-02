# Social Media Module — Handoff

> Module-scoped handoff for the **Social Media Manager + Content Creator** module.
> Not the root `/HANDOFF.md` (the suite-wide one). Read `CLAUDE.md` (this folder) for the
> build primer; this file is **current state + what to do next**.

## Current state (2026-09-02)

- **Design complete; no code written.** The module has been fully designed via an owner grill +
  an adversarial review; all decisions are recorded.
- **The PostPeer P0 vendor gate closed 2026-09-02** (see below).
- The original design docs are on **PR #952** (branch `claude/reload-skills-w3hzhd`); the vendor-gate
  closure was made on `claude/social-media-manager-build-dwqtvi`, which carries #952's commits merged on
  top of current `main`. Docs only.
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

## The P0 vendor gate — CLOSED (2026-09-02)

(Full readout: `../social-media-vendor-confirm-postpeer-v1_0.md` v1.1 — §6 has the API facts the
adapter needs.) The owner supplied PostPeer's live docs and ruled on the rest:
1. **X link-post billing** — ✅ **pass-through**: 5 credits for a plain X post, **50 credits when the body
   contains `http(s)://`**, 1 credit on every other platform; analytics reads 1 credit/call. Cost model
   v1.1 raised the Base X line $60 → ~$120/mo.
2. **IG carousel** — ✅ **live** (≤10 items, one aspect ratio throughout). The v1 single-image restriction
   was a vendor limit; carousel scope is now an **owner decision** (below).
3. **SLA / status page / webhook guarantee** — ✅ **none** (founder). Accepted: status is reconciled by our
   own polling sync job, and the swappable adapter is the mitigation.
4. **Legal entity + support channel** — ✅ **waived by the owner** (internal pilot; founder reachable on Reddit).

The **P0 connect-and-post smoke test** is still the go/no-go on real reliability. Also confirmed:
managed OAuth under PostPeer's own reviewed apps; Instagram uses Instagram Login (no linked Facebook
Page needed); IG feed/Reels need Business **or** Creator, **Stories need Business**; IG has no text-only
posts; feed image aspect ratio 4:5–1.91:1.

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
- **v1 Instagram scope** — feed-only, or include single-media Reels/Stories? (Stories: Business account
  only, no caption, no link stickers — a weak fit for repurposed content.)
- **IG carousel Draft type in v1?** — PostPeer supports it (≤10 items). Each slide is another
  nano-banana Pro image (~$0.13), so a 5-slide carousel is ~5× the dominant cost line per post.
- **Default per-client monthly cost ceiling** in the Social Policy (the cost model says Base ≈ $45/client/mo).
- **Autonomy rollout** — which clients (if any) reach the top tier for auto-publish, and when.

## Next actions, in order

1. ~~Answer the four PostPeer questions~~ — **done** (see the gate section above).
2. **Owner scope decisions** (above) + **provisioning** (`POSTPEER_API_KEY` first — the free 20 credits
   cover the smoke test; then `GEMINI_API_KEY`, `APIFY_API_TOKEN`, `TWELVELABS_API_KEY`).
3. **P0 — smoke test FIRST, then foundations:** the adapter interface + PostPeer implementation +
   `social_accounts` + a connect-and-post against a sandbox account, *before* the full data model /
   budget meter / scheduler wiring, so a reliability failure costs a stub, not a schema. The Social
   Policy + autonomy-tier columns still land in P0's migration.
4. **P1 Competitor research**, then **P2 Creator**, **P3 Manager+publish**, **P4 autonomy**, **P5 video**.

## Gotchas discovered during design (don't re-learn these)

- **Budget meter:** `keyword_research.reserve_budget` is **fail-OPEN** on RPC error; the fail-closed
  one is `autonomy_budget.reserve`. Copy the latter for spend.
- **`nano_banana.py` (2.5 Flash) sends no `imageConfig`/`aspectRatio`** — 1:1 output only. A Pro-based
  renderer that passes `aspectRatio` is required, or the Platform-Spec validator flags every
  non-square Draft un-approvable.
- **IG carousels ARE live in PostPeer** (v1.0 of the vendor doc said otherwise — it read a stale blog
  post). Don't add a carousel Draft type until the owner scopes it, but don't design it out either.
- **PostPeer's X link rule is mechanical** — any `http://`/`https://` in the body = 50 credits. The
  "avoid links on X" toggle and the approval-time cost warning key on exactly that.
- **Don't use PostPeer's `scheduledFor`** — publish with `publishNow` from our own freeze-gated job at
  slot time so the inline health check + `source_changed` guard actually run.
- **PostPeer OAuth tokens are held by PostPeer, not us** — don't build a token store.
- **`client_competitors` has partial unique indexes** (`WHERE domain/place_id IS NOT NULL`) — social
  handle-only rows escape dedup; use a child `social_competitor_handles` table.
- **postpeer.dev is egress-blocked in the Claude Code sandbox** — direct WebFetch fails; use search or
  ask the owner to fetch. (This is why the four vendor questions couldn't be closed automatically.)
- **Cost:** the X line is ~$120/mo at realistic volume (~10% X-link share at the confirmed 50-credit
  pass-through, ~$0.30–0.43/link post) — not the ~$600 an early draft implied, and double v1.0's $60
  (which assumed PostPeer absorbed the fee). The **nano-banana Pro image (~$0.11/post)** is still the
  dominant cost line.

## References

Root `/CLAUDE.md` (suite authority) · this folder's `CLAUDE.md` (module primer) · the six design docs
listed above · PR #952.
