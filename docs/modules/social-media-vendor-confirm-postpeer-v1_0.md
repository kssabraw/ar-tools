# PostPeer Vendor Confirm — Due Diligence v1.1

**Status:** Companion to `social-media-module-prd-v1_0.md` (§14) and ADR-0001. Resolves
adversarial-review item **A2** ("the publishing layer rests on unverified PostPeer
facts"). **v1.1 (2026-09-02): the P0 vendor gate is CLOSED** — the owner supplied
PostPeer's live docs (Getting Started, Twitter/X, Instagram) and ruled on the remaining
item. §1–§3 record the answers; §6 records the API facts the adapter build needs.

**Method note:** v1.0's findings came from web search because `postpeer.dev` is
egress-blocked in the Claude Code sandbox. v1.1's corrections come from the **live docs
pasted by the owner** (`/docs`, `/docs/platforms/twitter`, `/docs/platforms/instagram`),
so they supersede v1.0 wherever the two disagree.

## 1. Confirmed — the design's assumptions hold ✅

| Assumption | Finding | Source |
|---|---|---|
| **Managed OAuth under PostPeer's own reviewed apps** (the low-friction basis of ADR-0001) | **Confirmed.** "You don't need to create developer apps… App Review is done for you." Client authorizes via PostPeer's hosted callback. Instagram uses **Instagram Login**, so a linked Facebook Page is **not** required. | `/docs/connect-accounts`, `/docs/platforms/instagram` |
| **Platform coverage** (our five) | Confirmed Live: X, Facebook, Instagram, Pinterest ("Pins with images"), YouTube (+ Shorts). Also LinkedIn/TikTok/Threads/Bluesky. | `/docs` platform table |
| **Instagram professional-account requirement** | Confirmed — feed posts + Reels need a **Business or Creator** account; **Stories need a Business account** specifically. | `/docs/platforms/instagram` |
| **Pricing / billing shape** | Free 20 credits on signup; ~$8.50/1k (Starter) → ~$6/1k (Pro); PAYG packs never expire; **billed per post, unlimited accounts**; failed calls don't deduct. | pricing pages |

## 2. Corrections to v1.0 — act on these ⚠️

| Item | v1.0 said | Live docs say | Impact on the module |
|---|---|---|---|
| **Instagram carousels** | Not live (single-media adapter; "on the roadmap"). | **LIVE.** Up to **10** JPG/PNG/MP4/MOV items via multiple `mediaItems`; **one aspect ratio throughout**. | The v1 "single-image IG only" restriction was a vendor constraint, not a product choice. Whether a **carousel Draft type is in v1 scope** is now an **owner decision** (open, see HANDOFF) — it multiplies the dominant image cost by the slide count. |
| **X link-post tax** | PostPeer silent; "likely absorbed". | **Passed through, explicitly.** Post on X **without** a URL = **5 credits**; **with** a URL (body contains `http://` or `https://`) = **50 credits**; every other platform = **1 credit**; an **analytics request = 1 credit** per call. PostPeer states this mirrors X's own $0.015 / $0.200 per-request pricing. | At $6–8.50/1k credits an X link-post costs **$0.30–0.43** (above X's raw $0.20 — the markup rides along) and a plain X post **$0.03–0.04**. Cost model corrected (`social-media-cost-model-v1_0.md` §1/§3/§4). The **"avoid links on X"** Social Policy toggle is now a **precise rule** (a URL scheme in the body) the Platform-Spec validator enforces, and the approval UI must show the **10× credit cost** when X copy contains a scheme. P4 analytics read-back is metered at 1 credit/call. |
| **Reliability** | No status page/SLA/entity found. | **Confirmed by the founder: no SLA.** | Accepted for the pilot. The failure-handling spec already assumes nothing from the provider (status reconciled by our own polling sync job, never dependent on webhooks). **The swappable adapter (ADR-0001) is the mitigation and stays load-bearing.** |

## 3. The P0 gate — CLOSED ✅

| # | Question | Answer | Status |
|---|---|---|---|
| 1 | X link-post billing | Pass-through: 5 credits (no URL) / 50 credits (URL). | **Closed** (live docs) |
| 2 | IG carousel | Live, up to 10 items, single aspect ratio per carousel. | **Closed** (live docs) |
| 3 | SLA / status page / webhook guarantee | None. | **Closed** (founder, via Reddit) — design already tolerates it |
| 4 | Legal entity + support channel | — | **Waived by the owner** (internal tool, pilot scale; the founder is reachable on Reddit; the adapter covers the bus-factor risk) |

Nothing in P0 is blocked on PostPeer any more. Remaining pre-P0 items are **provisioning**
(`POSTPEER_API_KEY` etc. — see HANDOFF) and the **owner scope decisions** (HANDOFF).

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
The P0 smoke test still runs first so we learn PostPeer's real reliability before the
calendar is built on it.

## 5. Decision impact

- ADR-0001 (PostPeer behind an adapter): **holds.** Friction basis confirmed; no SLA
  confirmed → the adapter is non-negotiable; the X link tax is a confirmed pass-through.
- PRD §1: IG v1 scope re-opened — feed single-image is the floor; **carousel is an owner
  scope call**, no longer a vendor limit. Stories are Business-account-only, caption-less,
  no interactive stickers.
- PRD §11 / cost model: X line corrected upward (pass-through + markup); still not the
  dominant line — the nano-banana Pro image and competitor research remain the drivers.
- Social Policy: "avoid links on X" toggle kept and made precise (URL scheme in body).

## 6. API facts the adapter build needs (from the live docs)

- **Base URL** `https://api.postpeer.dev/v1`; auth header **`x-access-key`**; official
  SDK `pip install postpeer` (reads `POSTPEER_API_KEY`). Free tier = 20 credits, enough
  for the P0 smoke test.
- **Profiles map 1:1 onto suite clients.** `POST /profiles {name}` → `profile.id`, created
  **before** connect; `GET /connect/{platform}?profileId=` returns the OAuth `url` to
  redirect the client to; afterwards `GET /connect/integrations?profileId=` lists that
  client's integrations. **`integration.id` is the `adapter_account_id` the schema keeps**
  (plus `platform`, `platformUserId`). Store the PostPeer `profile.id` per client.
- **Post creation** `POST /posts {content, platforms:[{platform, accountId,
  platformSpecificData?}], mediaItems?:[{type, url}], publishNow | scheduledFor+timezone}`.
  Response: `{success, status, postId, platforms:[{platform, success, platformPostUrl}]}`.
  **Send one platform per call** — our model is one Post per platform and per-platform
  status must stay independent. `platformPostUrl` is the "view on platform" link;
  `postId` is the provider post id.
- **Use `publishNow: true` from OUR scheduler at slot time — do NOT hand PostPeer the
  schedule via `scheduledFor`.** The failure-handling spec puts the inline account-health
  check and the `source_changed` guard immediately before the post; PostPeer-side
  scheduling would bypass both and the freeze gate.
- **Media is passed by public URL** (`mediaItems[].url`, `coverUrl`) — generated images
  must land in a **public bucket** (the website-hero pattern), not the private `reports`
  bucket.
- **X Platform Spec:** 280 chars (`longPost` needs Premium — keep off by default; PostPeer
  pre-rejects >280 otherwise); ≤4 images / 1 video / 1 GIF per tweet; threads via
  `platformSpecificData.threadItems` (each item ≤280, own media); polls 2–4 options
  (not combinable with media/threads); `replySettings`. **Credit rule: any `http(s)://`
  in the body → 50 credits.**
- **Instagram Platform Spec:** **text-only posts are not supported** (≥1 media item —
  a Draft with no image is `needs_image`, never approvable, like Pinterest); feed image
  **aspect ratio 4:5 through 1.91:1** (JPG/PNG); carousel ≤10 items, **one aspect ratio
  throughout**; a `video` mediaItem publishes as a **Reel** by default (`shareToFeed`
  defaults true; `coverUrl`/`thumbOffset` for the cover, 9:16 recommended); Stories via
  `platformSpecificData.contentType="story"` — Business account only, exactly one
  image/video, **`content` is ignored** (no caption), no links/polls/stickers, gone in 24h;
  `collaborators` (≤3 usernames, feed/carousel/Reels only).
- **Facebook:** the live table lists "Posts, photos, photo carousels, videos, link previews"
  (v1.0's "Pages, not profiles" came from the platform page — re-confirm at P0).
- **Pinterest:** "Pins with images" — board selection details on its platform page
  (not yet read; needed for the Pinterest `platform_metadata`).
