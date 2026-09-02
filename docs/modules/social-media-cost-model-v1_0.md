# Social Media Module — Cost Model v1.0

**Status:** Companion to `social-media-module-prd-v1_0.md` (§11 Cost governance).
Resolves adversarial-review item **A3** ("autonomous-volume economics asserted, not
modeled"). All figures are **assumption-driven estimates** for planning the budget
meter + Social Policy ceilings — not committed prices. Verify the starred vendor
rates before relying on a total (see §5).

## 1. Unit costs

| Item | Basis | Unit cost | Source / note |
|---|---|---|---|
| **Copy + Angle + self-critique** (Claude **Sonnet 5**) | per Draft | **~$0.02–0.04** | Sonnet 5 = $2/1M in, $10/1M out. A Draft is a few Sonnet calls (angle share + tailored copy + 1–2 self-critique/regurgitate passes); ~3–5k in / <1k out each. Small. |
| **Image** (**nano-banana Pro** / Gemini 3 Pro Image) | per image | **~$0.134** (1K/2K) | ★ Confirm current price. Batch mode ≈ half. This is the **dominant** per-Draft line. |
| **Publish** (PostPeer) | per post | **~$0.006–0.0085** | ★ PostPeer tiers. Negligible. |
| **X link tax** | per X post **containing a link** | **$0.20** | ★ X API pricing; **pass-through vs absorbed by PostPeer is an open vendor-confirm** (ADR-0001). Non-link X post ≈ $0.015. |
| **Competitor scrape** (Apify) | per competitor · platform · refresh (~100 posts) | **~$0.04–0.24** | ★ per-result actor pricing (IG ~$1.50/1k, X ~$0.40/1k, FB ~$2/1k, YT ~$2.40/1k). |
| **Competitor video analysis** (TwelveLabs) | per minute indexed+analyzed | **~$0.06/min** | ★ ~$0.042 index + ~$0.021 analyze; output tokens trivial. Cap minutes/run. |

**Derived per-Draft *production* cost** (copy + image, image attached to ~80% of Drafts):
≈ **$0.14/Draft** — of which the **nano-banana Pro image is ~$0.11 (≈80%)**.

**Derived per-client *research* cost** (5 competitors × ~4 platforms scrape + a few
short videos, weekly): ≈ **$20/client/month**.

## 2. Formula

```
monthly_cost ≈  Σ_clients [  posts × (production + publish)
                            + x_link_posts × $0.20
                            + research_per_client ]
```
where `production ≈ $0.14/post`, `publish ≈ $0.008/post`, `research ≈ $20/client/mo`.

## 3. Scenarios

| Scenario | Clients | Posts/day·client | Posts/mo (total) | Production | Publish | Research | X tax* | **Monthly total** | **/client** |
|---|---|---|---|---|---|---|---|---|---|
| **Pilot** | 5 | 2 | 300 | $42 | $2 | $100 | $12 | **~$156** | ~$31 |
| **Base** | 20 | 5 | 3,000 | $420 | $24 | $400 | $60 | **~$904** | ~$45 |
| **Scale** | 50 | 8 | 12,000 | $1,680 | $96 | $1,000 | $360 | **~$3,136** | ~$63 |

\* X tax rows assume **10% of posts are X-link-posts** (X is one of ~5 platforms and
only some X posts carry a link). This is the realistic middle of §4.

**Headline:** at realistic volume the **nano-banana Pro image (~$0.11/post) and
competitor research (~$20/client/mo) dominate — not the X link tax.** The image line
is a direct consequence of the review's Pro switch (§4 lever).

## 4. X-link-tax sensitivity (Base scenario, 3,000 posts/mo)

The tax is highly sensitive to *what fraction of posts are X posts carrying a link* —
which is why a single figure is misleading and the Social Policy needs a per-client
"avoid links on X" toggle.

| X-link-post share of all posts | X-link-posts/mo | X tax/mo |
|---|---|---|
| 0% (no-link-on-X toggle on) | 0 | **$0** |
| 5% | 150 | $30 |
| **10% (base assumption)** | 300 | **$60** |
| 25% | 750 | $150 |
| 50% (half of *all* posts are X link-posts — unrealistic) | 1,500 | $300 |

> **Correction to PRD §11:** an earlier draft said "3,000 link-posts × $0.20 ≈ $600."
> 3,000 is *total posts*, not link-posts; even "half with links" is 1,500 → $300, and
> the realistic X-link share (~10%) is **~$60/mo**. §11 now cites this range.

## 5. Cost levers (before committing budgets)

1. **Mixed image model** — use nano-banana **2.5 Flash** (~$0.039, 1:1) for platforms
   that accept square (X, Facebook, IG feed) and reserve **Pro** (~$0.134, aspect
   ratios + in-image text) for Pinterest / 9:16 / text-heavy graphics. Roughly halves
   the dominant line. (Requires the renderer to select per platform — a P2 option.)
2. **Batch image mode** (~half price) where latency isn't critical (scheduled Drafts).
3. **Per-client monthly hard ceiling** in the Social Policy, enforced by the
   **fail-closed** meter (`autonomy_budget.reserve` pattern) — the backstop against a
   runaway autonomous loop.
4. **Cap TwelveLabs minutes/run** and competitor-refresh cadence (weekly, not daily).
5. **Reuse** the client's existing suite-generated images (the reusable-image picker)
   instead of always generating — free.

## 6. What must be verified before these numbers are trusted (★)

nano-banana Pro per-image price; PostPeer per-post price **and who pays the X link
tax**; TwelveLabs current per-minute rate; Apify per-result actor rates for the
chosen actors. These are the same vendor-confirms gating P0 (PRD §14).
