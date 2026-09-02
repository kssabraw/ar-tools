# PostPeer Vendor Confirm — Due Diligence v1.0

**Status:** Companion to `social-media-module-prd-v1_0.md` (§14) and ADR-0001. Resolves
adversarial-review item **A2** ("the publishing layer rests on unverified PostPeer
facts"). This is a due-diligence readout + the questions that still need a direct answer
from PostPeer before/at P0.

**Method caveat:** `postpeer.dev` is **egress-blocked for direct fetch** from this
environment, so facts below come from PostPeer's own pages **as surfaced through web
search** (reliable for substance; treat wording as close paraphrase, not verbatim) and
from third-party sources where noted. Re-confirm the amber items against the live site
or PostPeer directly.

## 1. Confirmed — the design's assumptions hold ✅

| Assumption | Finding | Source |
|---|---|---|
| **Managed OAuth under PostPeer's own reviewed apps** (the low-friction basis of ADR-0001) | **Confirmed.** "You don't need to create developer apps… **App Review is done for you.**" Client authorizes via PostPeer's hosted callback; managed-by-default, BYOK optional; OAuth on every plan incl. free. | postpeer.dev `/docs/connect-accounts` |
| **Platform coverage** (our five) | Confirmed: X, Facebook (**Pages, not profiles**), Instagram, Pinterest (pins **and** boards), YouTube (+ auto-Shorts). Also LinkedIn/TikTok/Threads/Bluesky. | `/social-media-posting-api`, per-platform pages |
| **Instagram Business/Creator requirement** | Confirmed — personal accounts cannot connect. Stories supported. | `/blog/best-instagram-posting-api` |
| **Pricing / billing shape** | Free 20; ~$8.50/1k (Starter) → ~$6/1k (Pro); PAYG credit packs never expire; **billed per post, unlimited accounts**; AI caption = 2 credits, AI image = 10, failed calls don't deduct. | pricing pages |

**Net:** the biggest A2 risk — that we or the client would face weeks of platform
app-review — is **retired**. PostPeer's managed-app model is exactly the one-click-connect
the design assumed.

## 2. Corrections & caveats — act on these ⚠️

| Item | Finding | Impact on the module |
|---|---|---|
| **Instagram carousels** | **NOT live.** PostPeer's own blog says the IG adapter currently accepts **one image OR one video per post**; multi-image carousels are "on the roadmap." | **PRD §1 corrected:** v1 Instagram = **feed single-image** (+ Reels/Stories as single-media); **carousel deferred** until PostPeer ships it. Don't build a carousel Draft type in v1. |
| **X link-post tax** | PostPeer is **silent** — flat 1-credit-per-post model, no documented per-link surcharge. The underlying X fee is real ($0.015/post, **$0.20 if it contains a link** — 13×, third-party-confirmed). | **Likely absorbed-and-silent**, which is itself a risk: a flat-priced reseller either eats the X link fee (margin risk → possible future price change/throttle) or has an undocumented cap. **Direct question #1 below.** Keep the "avoid links on X" Social Policy toggle regardless. |
| **Reliability** | **No status page, SLA, uptime commitment, or legal entity** found. Indie/bootstrapped profile (PeerPush listing, heavy programmatic-SEO footprint, Trustpilot/ProvenExpert). | **Confirms the ADR-0001 swappable-adapter decision is load-bearing** — do not couple module code to PostPeer directly. |

## 3. Still open — ask PostPeer directly (P0 gate)

1. **X link-post billing** — is a post to X *containing a link* billed the same 1 credit as a non-link post, or surcharged/capped? (Their site is silent; the underlying X fee is 13×.)
2. **IG carousel** — live yet, or still roadmap? If roadmap, what's the ETA?
3. **SLA / status page / uptime** — do any exist non-publicly? What's the delivery/retry guarantee behind the advertised webhooks?
4. **Legal entity + support channel** — undisclosed publicly; needed for a production dependency + a DPA (we'll be handling clients' connected-account publishing).

## 4. The fallback (Ayrshare) is real but not a cheap drop-in

The design names Ayrshare as the adapter's fallback. Diligence shows it's a genuine
**maturity/coverage vs cost/friction trade**, not a near-equivalent:

- **Coverage:** materially **broader** — adds Reddit, Telegram, **Google Business
  Profile**, Bluesky. If GBP/Reddit ever matter, Ayrshare wins.
- **Maturity:** materially **higher** — enterprise-grade docs, webhooks, analytics; a
  "safe pick if budget isn't a concern" (per PostPeer's own comparison page).
- **Cost/billing:** **enterprise-priced, no free tier — ~$299/mo (10 profiles), ~$599/mo
  (30)** and **billed per connected profile** (vs PostPeer's per-post, unlimited
  accounts). For a multi-client agency, per-profile pricing scales **badly** — ~20–35×
  PostPeer's entry cost and a different billing shape.

**Implication:** the swappable adapter is the right call, but a mid-project swap to
Ayrshare is a **cost/architecture event** (per-profile budgeting), not a config change.
Weight the P0 smoke test accordingly — we want to learn PostPeer's real reliability
before we've built the calendar on it.

## 5. Decision impact

- ADR-0001 (PostPeer behind an adapter): **holds, strengthened.** The friction basis is
  confirmed; the indie-reliability risk is confirmed → the adapter is non-negotiable.
- PRD §1: **corrected** — IG carousel out of v1 (PostPeer single-media).
- PRD §14: managed-OAuth confirm **closed**; the four questions above remain the P0 gate.
- Social Policy: keep the "avoid links on X" toggle (the X tax may bite even if PostPeer
  is currently silent on it).
