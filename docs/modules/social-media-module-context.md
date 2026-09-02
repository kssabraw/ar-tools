# Social Media Module — Domain Glossary (CONTEXT)

> Bounded-context glossary for the Social Media Manager + Content Creator module.
> Glossary only — no implementation detail. Design decisions live in the module
> PRD / ADRs; this file only fixes the *language*. Terms are settled during the
> design grill (see the conversation that produced this file).

## The module

**Social Media module** — one suite module with **two surfaces** over **one
per-client data model**. It repurposes a client's existing content into
on-brand, platform-native social content and publishes it to the client's real
social accounts under human approval. Rides the standard suite rails
(per-client workspace, `async_jobs`, shared scheduler, notifications, voice-card
enforcement, freeze protocol, per-module paid-call budget meter, agent
legibility).

**Creator (surface)** — the generation half: turns a **Source** into
reviewable **Drafts** via a chosen **Angle**. Not a separate module.

**Manager (surface)** — the planning/operations half: the **Calendar**,
scheduling against a per-platform target **Cadence**, approval, publishing, and
performance. Not a separate module.

## Core objects

**Source** — the input a piece of content is repurposed *from*: an existing
client blog run, Local SEO / Ecommerce / Website page, a keyword-research idea, a
competitor top-performer, or a manually entered topic. The Source is *what to
talk about*; the **Angle** is *how to talk about it*.

**Angle** — a distinct editorial take on a Source (e.g. myth-bust, customer-pain
story, behind-the-scenes/authority, seasonal hook, tips-list, before/after
proof). 3–5 are proposed per Source (grounded in the Source + brand voice/ICP +
relevant **Competitor Signals** + keyword ideas); the user multi-selects and may
hand-write their own. Each selected Angle drives its own per-platform fan-out.
Stored on the Draft set it produces.

**Draft** — a single, unpublished, platform-native unit of content for **one
platform**, produced by fanning an Angle out across the target platforms. Copy is
**tailored per platform** (not one message reformatted). Carries platform copy,
optional image(s), and per-platform metadata (e.g. Pinterest board+title,
YouTube description). Editable by a human before it enters the Calendar. Brand
voice on a Draft is **enforced and scored** via the existing voice-card system,
not merely prompted.

**Post** — a Draft that has been approved and scheduled or published. The unit
the Calendar tracks and the publishing lifecycle acts on. (Lifecycle mirrors GBP
Posts: draft → approve → explicit publish → freeze-gated idempotent publish job →
async status reconciliation.)

**Calendar** — the Manager's per-client, cross-platform view of scheduled and
published Posts.

**Cadence** — a per-`(client, platform)` target posting frequency (e.g. IG
3×/week) that *suggests* Calendar slots for approved Drafts; a human confirms or
adjusts every slot.

## Accounts & competitors

**Social Account** — a connection to one of the client's *own* real platform
accounts (Twitter/X, Facebook, Instagram, Pinterest, YouTube), authorized by the
client through the posting provider's OAuth. Per `(client, platform)`. Distinct
from the suite's existing website/GSC/GBP connections.

**Posting provider / adapter** — the external service that holds the per-account
OAuth and publishes on the client's behalf. **PostPeer** is the v1 provider,
placed behind a swappable **adapter** interface (`connect_url` / `post` /
`status`) so it is not a single point of failure.

**Competitor (social identity)** — an entry in the existing client-competitor
registry extended with optional **per-platform social handles**, so a competitor
can be researched per platform. A competitor's *media is never re-hosted* by the
module.

**Competitor Signal** — the stored, per-`(client, competitor, platform)` result
of competitive research: dominant themes, formats, hook patterns, posting
cadence, and top-performers (kept as *links*, not re-hosted media), plus a
rolled-up "what's working." Feeds Angle proposals and the generator's prompts.
Produced by **analyze-in-place** research (public post data via scraping; video
analyzed from its public URL) — never by downloading competitor media.

## Boundary terms

**Analyze-in-place** — the competitor-research stance: read public competitor
content and analyze competitor video *from its public URL*, storing derived
signals and links only. The module never downloads, stores, or republishes a
competitor's media. Media download (cobalt) is reserved for the client's own or
licensed assets.

**Auto-publish** — publishing a Post to a client's real account with no human
click. Allowed **only** behind the top autonomy tier *and* an explicit per-client
opt-in; never a default. Absent that, publishing is always human-approved.

## Autonomy & control

The endgame is an **autonomous social department**: humans approve content and
tune the agents; the department otherwise plans, produces, schedules and (at the
top tier) publishes on its own. This is realized as a **domain executor reusing
the suite's existing autonomy guardrails** (autonomy tiers, the
`autonomy_policy.classify` auto/propose/escalate decision, the fail-closed budget
governor, freeze, the DORA veto) — **not** a new by-disposition persona.

**Social Manager (orchestrator)** — the autonomous orchestration *loop* (not a
chat persona): each cycle it reads the client's **Social Policy**, Cadence,
goals and **Competitor Signals**, plans the period, dispatches the **Social
Creator** to produce, routes results to approval, then schedules and (top-tier)
publishes. The org-chart "manager" that plans/organizes/coordinates. Distinct
from the **Manager surface** (the human's Calendar/approval UI), which is how a
person sees and steers the same work.

**Social Creator (worker)** — the bounded, tool-using production *loop* the
Social Manager dispatches (and that the **Creator surface** invokes on-demand):
research → **Angle** → design (copy + image) → self-critique against the
voice-card and **Platform Spec** → regenerate. One engine, two callers (human or
orchestrator). A *worker function*, not a persona you converse with.

**Social Policy (Playbook)** — the per-client object humans edit to *tune the
agents*: per-platform **Cadence** and on/off, allowed/blocked topics & claims,
tone/angle preferences, competitor focus, budget ceiling, the **autonomy tier /
approval strictness**, and **the generation prompt templates** (image and text
style). An edited prompt still passes the deterministic Platform-Spec + voice
validators — tuning steers output, never bypasses the brand/safety gates.

**Graduated approval** — approval strictness is a function of the client's
autonomy tier: new/low-trust → approve every Post; trusted → batch /
approve-by-exception; top tier → **Auto-publish** with post-hoc review. What lets
"minimal supervision" be real without abandoning control.

**Platform Spec** — the per-platform constraint data (character limits, image
aspect ratios, hashtag norms, CTA style, link policy) consumed by *both* the
generation prompt and a **deterministic validator**; a Draft violating a hard
constraint is flagged before it can be approved.
