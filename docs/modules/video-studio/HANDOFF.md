# Video Studio — handoff & state

> **State: PLANNING ONLY. No code, no migrations, no vendor accounts, nothing built.**
> This is the output of a design/thinking session. `CLAUDE.md` (same folder) is the design
> reference; this file is the state, the grounded economics, the decisions (locked + open),
> and the next steps. Pricing was grounded via web search on the dates noted and **moves
> monthly — re-verify before committing to a vendor.**

## Where we are

A design has been sketched for a **faceless VO-over-b-roll social video** module (30s / 1m,
9:16 + 16:9, delivered to Drive). The economics and format decisions are settled; the module
shape is sketched. Nothing is implemented. The immediate next artifact is either the brand
**video template spec** or a full house-format PRD (`docs/modules/video-studio-module-prd-v1_0.md`).

## Grounded economics (the load-bearing conclusion)

**This is a labor-bound product, not an AI-cost-bound one.** The AI is noise; human review
minutes are the real cost. Design and price around *reviewer touch-time*, not vendor cents.

### Fixed monthly overhead (subscriptions, shared across ALL clients/videos)

| Tool | ~Cost/mo | Role |
|---|---|---|
| Stock library (Storyblocks/Artgrid) | $21–30 | b-roll, unlimited downloads |
| json2video | $17–50 | assembly / render |
| ElevenLabs | $22 (Creator) | VO |
| Kling/Higgsfield *(only if generated clips on)* | $37 | generated accent |
| **Total** | **~$60–140/mo** | across the whole book |

### Per-video marginal hard cost (API spend)

| Component | 30s | 1m |
|---|---|---|
| Script (Claude, existing stack) | ~$0.03 | ~$0.05 |
| VO (ElevenLabs, $0.10/1k chars multilingual) | ~$0.05 | ~$0.09 |
| Stock b-roll | ~$0 (flat sub) | ~$0 |
| Assembly (json2video, 1 credit/sec/1080p, ×2 for 9:16+16:9) | ~$0.06–0.10 | ~$0.12–0.20 |
| **Subtotal — stock-only** | **~$0.15–0.20** | **~$0.25–0.35** |
| *+ Kling accent (~3 hero clips)* | +$2–3 | +$2–3 |
| *+ Fully Kling-generated* | +$4–6 | +$7–12 |

A stock faceless video costs **under $0.50 in API** — effectively free at the margin.

### All-in per finished video (incl. labor)

| Scenario | Hard cost | + Labor (15–30 min @ $15–25/hr VA) | **All-in** |
|---|---|---|---|
| **Stock-only** (default) | ~$0.30 | $4–12 | **~$4–12** |
| **Stock + Kling accent** | ~$3 | $5–14 | **~$8–17** |
| **Fully generated** | ~$5–12 | $8–20 (more curation) | **~$13–32** |

**Takeaways:** (1) optimize for *fewer human minutes*, not cheaper AI — margin lever is
template quality + Gate-1 tightness; (2) stock-only is the profit engine, generated clips are
a premium upsell; (3) the 10-videos/client ceiling is cheap on hard cost (~$3–5 API for 10
stock videos) — the real capacity constraint is *reviewer time*, so engineering effort goes
into making Gate 1 / Gate 2 low-touch (batch approvals, storyboard-at-a-glance, auto stock pick).

### Generated-video pricing comparison (Kling / Higgsfield / HeyGen)

These three **do not make the same video** — do not compare rows as equal. Assumptions:
Kling ≈ $1/usable 5–10s clip (~1 clip per 6s screen time, iterations baked in); Higgsfield
**extrapolated, low confidence — credit rates unpublished**; HeyGen from published API rates.

| Length | **Kling** (silent b-roll) | **Higgsfield Speak** (avatar, *est.*) | **HeyGen** (avatar) |
|---|---|---|---|
| 30s | $4–6 | ~$3–8 | **$0.50–2** |
| 1m | $7–12 | ~$6–15 | **$1–4** |
| 2m | $14–24 | ~$12–30 | **$2–8** |
| 3m | $21–36 | ~$18–45 | **$3–12** |
| Confidence | Medium | **Low (opaque)** | High |

- **Kling** = a *component* (silent b-roll; VO added separately), 5–10s clips stitched. This
  is the only column relevant to v1, and only as an optional accent.
- **HeyGen** = the avatar lane if it ever returns: transparent per-minute pricing, one
  sustained render, perfect lip-sync. **Cheaper and far more predictable than Higgsfield.**
- **Higgsfield** *does* have a Speak/lip-sync avatar feature (an earlier "it can't lip-sync"
  claim in-session was **wrong** and corrected). But its per-generation credit rates aren't
  published, so you **cannot quote a client a clean per-video cost** — that opacity, not a
  price blowout, is the reason to prefer HeyGen for avatars.

### The storyboard-first technique (how coherent generative video is actually made)

Generating N clips independently re-rolls the look every time = the "AI slop" coherence
problem. Fix it by solving consistency at the **cheap image stage**: generate 10–15
**Nano Banana** storyboard stills (its superpower is subject/style consistency — each frame
references the prior one / a hero anchor), then use **image-to-video** (hand each approved
still to Kling as the *start frame*) so the model animates *that exact image*. Far more
predictable than text-to-video, and it makes Gate 1 a real preview. **It fixes coherence, not
cost** — the i2v step is still ~$1/clip, so ~$12–18 per finished minute of fully-generated
video. Power-ups: first-frame+last-frame control; a per-client hero reference image on file.

## Decisions — LOCKED

1. **Faceless VO-over-b-roll** format (no avatars in v1).
2. **Two fixed lengths: 30s and 1m only.** Short-form only; **long-form YT/FB dropped from v1**
   (conscious scope cut, not an omission).
3. **VO is the spine** — generate ElevenLabs VO first, hang timeline + captions off its word timing.
4. **Stock b-roll default; generated clips (Kling) an opt-in per-segment accent** behind a flag.
5. **Two human-in-the-loop gates** — Gate 1 (approve storyboard, before spend) + Gate 2
   (approve render). **Publishing is HITL** (Phase 3), not auto.
6. **Vendors:** ElevenLabs (VO), stock library (b-roll), json2video (assembly), Nano Banana
   (storyboard stills), Kling (i2v accent). **Per-lane vendor abstraction** (`entity_provider`
   pattern).
7. **If avatars ever return → HeyGen, never Higgsfield** (predictable metering).
8. **The template is a durable, versioned, auto-inherited client asset** — the primary
   consistency mechanism.
9. **Cross-video consistency = the deterministic wrapper (template) + color grade**, not the
   b-roll content. Lock the wrapper, vary the content.
10. Files scoped to `docs/modules/video-studio/` (not appended to the root `CLAUDE.md`, which
    documents built state).

## Decisions — OPEN (need the owner)

1. **Who authors the brand video template first?** Auto-draft from existing brand assets
   (logo, colors, voice card) → human approve once *(recommended)*, vs. manual setup like the
   website theme.
2. **Recipe rigidity:** fixed 30s/1m recipes *(recommended — start rigid, loosen later, since
   labor is the constraint)* vs. LLM picks structural variants from a whitelist (website
   middle-path).
3. **Stock selection point:** does `video_generate` call the stock search API, rank, and pick
   the actual clip (so Gate 1 shows real footage — *recommended*), or just emit the query and
   let the render step grab the top match?
4. **Stock vendor** — Storyblocks vs Artgrid/Artlist vs Motion Array (licensing terms for
   client commercial use matter; verify before committing).
5. **json2video vs Creatomate** for assembly (both fit; json2video is cheaper/simpler).
6. **Music licensing** — where the beds come from (Storyblocks Unlimited/Artlist include music).

## Risks / watch-items

- **Reviewer touch-time is the whole ballgame.** If Gate 1/Gate 2 aren't genuinely a glance,
  the unit economics collapse. Build the batch/queue UX early, not last.
- **Stock/music commercial-use licensing for clients** — confirm the subscription tier grants
  client-facing commercial rights and covers per-client redistribution.
- **Generative-video pricing is opaque and moving** (esp. Higgsfield) — re-verify before Phase 2.
- **Social-publishing APIs (Phase 3)** are a real sub-project — per-platform OAuth, app review,
  rate limits, per-client tokens. Don't underestimate; keep it out of v1.
- **Long-form parked deliberately** — don't let it creep back into v1 scope.

## Next steps (in order)

1. Owner resolves the OPEN decisions above (esp. #1 template authoring, #2 recipe rigidity).
2. Spec the **brand video template** concretely (exact fields; auto-derive vs manual).
3. Promote to a house-format PRD: `docs/modules/video-studio-module-prd-v1_0.md`
   (scope, cut-list, data model, phasing, decision log) — then run the `adversarial-review`
   skill over it before building.
4. Phase 0 build: template + data model + vendor wrappers (stock, ElevenLabs, json2video).
5. Phase 1 build: the stock-only profit-engine pipeline end to end.

## Sources (grounded on the dates below; re-verify — pricing moves monthly)

Verified 2026-09-02:
- Kling pricing — eesel (https://www.eesel.ai/blog/kling-ai-pricing), vo3ai (https://www.vo3ai.com/kling-ai-pricing)
- Higgsfield pricing + Speak — Scopeful (https://www.scopeful.org/blog/higgsfield-pricing-2026),
  imagine.art (https://www.imagine.art/blogs/higgsfield-ai-pricing),
  Scribe lip-sync walkthrough (https://scribehow.com/page/How_to_Create_Talking_AI_Avatars_With_Higgsfields_Lip-Sync_Studio_in_2026__55RJhn-yTIi2yeS3EmookA),
  UGC cost comparison (https://spreshapp.com/article/comparing-higgsfield-openart-heygen-for-ugc)
- HeyGen pricing — eesel (https://www.eesel.ai/blog/heygen-pricing), Arcade (https://www.arcade.software/post/heygen-pricing)
- ElevenLabs pricing — Flexprice (https://flexprice.io/blog/elevenlabs-pricing-breakdown)
- json2video pricing — credit consumption (https://json2video.com/docs/v2/pricing/credit-consumption), pricing (https://json2video.com/pricing/)
- Stock — Archaius comparison (https://archaiuscreative.com/the-best-stock-footage-licensing-sites-w-pricing-comparison/)
