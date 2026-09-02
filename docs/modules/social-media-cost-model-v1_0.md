# Social Media Module — Cost Model v1.1

**Status:** Companion to `social-media-module-prd-v1_0.md` (§11 Cost governance).
Resolves adversarial-review item **A3** ("autonomous-volume economics asserted, not
modeled"). **v1.1 (2026-09-02):** the X line is corrected from PostPeer's live pricing —
the link tax is a confirmed **pass-through in credits** (5 / 50), not absorbed; see
`social-media-vendor-confirm-postpeer-v1_0.md` §2. All figures are **assumption-driven estimates** for planning the budget
meter + Social Policy ceilings — not committed prices. Verify the starred vendor
rates before relying on a total (see §5).

## 1. Unit costs

| Item | Basis | Unit cost | Source / note |
|---|---|---|---|
| **Copy + Angle + self-critique** (Claude **Sonnet 5**) | per Draft | **~$0.02–0.04** | Sonnet 5 = $2/1M in, $10/1M out. A Draft is a few Sonnet calls (angle share + tailored copy + 1–2 self-critique/regurgitate passes); ~3–5k in / <1k out each. Small. |
| **Image** (**nano-banana Pro** / Gemini 3 Pro Image) | per image | **~$0.134** (1K/2K) | ★ Confirm current price. Batch mode ≈ half. This is the **dominant** per-Draft line. |
| **Publish** (PostPeer, non-X) | per post | **~$0.006–0.0085** | 1 credit; $8.50/1k (Starter) → $6/1k (Pro). Negligible. |
| **Publish on X, no link** | per X post | **~$0.03–0.043** | **5 credits** (confirmed, live docs). |
| **Publish on X with a link** | per X post whose body contains `http(s)://` | **~$0.30–0.43** | **50 credits** (confirmed pass-through of X's $0.20 per-request fee, plus PostPeer's margin). |
| **Analytics read** (PostPeer) | per call | **~$0.006–0.0085** | 1 credit per call regardless of posts returned (P4 read-back). |
| **Competitor scrape** (Apify) | per competitor · platform · refresh (~100 posts) | **~$0.04–0.24** | ★ per-result actor pricing (IG ~$1.50/1k, X ~$0.40/1k, FB ~$2/1k, YT ~$2.40/1k). |
| **Competitor video analysis** (TwelveLabs) | per minute indexed+analyzed | **~$0.06/min** | ★ ~$0.042 index + ~$0.021 analyze; output tokens trivial. Cap minutes/run. |

**Derived per-Draft *production* cost** (copy + image, image attached to ~80% of Drafts):
≈ **$0.14/Draft** — of which the **nano-banana Pro image is ~$0.11 (≈80%)**.

**Derived per-client *research* cost** (5 competitors × ~4 platforms scrape + a few
short videos, weekly): ≈ **$20/client/month**.

## 2. Formula

```
monthly_cost ≈  Σ_clients [  posts × (production + publish)
                            + x_plain_posts × $0.035 + x_link_posts × $0.37
                            + research_per_client ]
```
where `production ≈ $0.14/post`, `publish ≈ $0.008/post` (non-X), `research ≈ $20/client/mo`,
and the X figures are the midpoints of the credit-tier range.

## 3. Scenarios

| Scenario | Clients | Posts/day·client | Posts/mo (total) | Production | Publish | Research | X credits* | **Monthly total** | **/client** |
|---|---|---|---|---|---|---|---|---|---|
| **Pilot** | 5 | 2 | 300 | $42 | $2 | $100 | $12 | **~$156** | ~$31 |
| **Base** | 20 | 5 | 3,000 | $420 | $24 | $400 | $120 | **~$964** | ~$48 |
| **Scale** | 50 | 8 | 12,000 | $1,680 | $96 | $1,000 | $485 | **~$3,261** | ~$65 |

\* X rows assume **20% of posts go to X, half of them with a link** (so 10% of all posts
are X-link-posts at ~$0.37 and 10% are plain X posts at ~$0.035). This is the realistic
middle of §4. v1.0 had the Base X line at $60 on the assumption PostPeer absorbed the fee;
the confirmed pass-through roughly doubles it.

**Headline:** at realistic volume the **nano-banana Pro image (~$0.11/post) and
competitor research (~$20/client/mo) dominate — not the X link tax.** The image line
is a direct consequence of the review's Pro switch (§4 lever).

## 4. X-link-tax sensitivity (Base scenario, 3,000 posts/mo)

The tax is highly sensitive to *what fraction of posts are X posts carrying a link* —
which is why a single figure is misleading and the Social Policy needs a per-client
"avoid links on X" toggle. PostPeer's rule is mechanical — **any `http://` or `https://`
in the body** — so the toggle is enforceable by the Platform-Spec validator, and
"dropping the scheme" (a bare domain) takes the same tweet from 50 credits to 5.

| X-link-post share of all posts | X-link-posts/mo | X link credits/mo (@ ~$0.37) |
|---|---|---|
| 0% (no-link-on-X toggle on) | 0 | **$0** (plain X posts still ~$0.035 each) |
| 5% | 150 | $55 |
| **10% (base assumption)** | 300 | **$110** |
| 25% | 750 | $278 |
| 50% (half of *all* posts are X link-posts — unrealistic) | 1,500 | $555 |

> **Correction history:** an early draft said "3,000 link-posts × $0.20 ≈ $600" (it
> counted every post as an X link-post). v1.0 corrected the share to ~10% → ~$60/mo but
> assumed PostPeer absorbed the fee. v1.1 applies the **confirmed 50-credit pass-through
> (~$0.30–0.43/post)** → **~$110/mo** at the same 10% share. PRD §11 cites this.

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

nano-banana Pro per-image price; TwelveLabs current per-minute rate; Apify per-result
actor rates for the chosen actors. **PostPeer's per-post and X pricing are now confirmed
from the live docs** (vendor-confirm doc §2/§6) and no longer starred.
