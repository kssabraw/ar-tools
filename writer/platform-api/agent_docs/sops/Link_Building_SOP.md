# Link Building SOP — Strategy & Execution

**Current as of:** 02 July 2026 _(merged from Link Building SOP, 18 Nov 2024, + SEO NEO Strategy SOP, undated)_
**Goal:** Push PageRank and build a healthy, diversified backlink profile to clients' sites — and use SEO NEO to do it efficiently and effectively.
**Who this is for:** All SEO clients.
**When:** Monthly, for the duration of the contract, for all clients.
**Assigned to:** per `_ORCHESTRATOR.md` §6 (roles matrix).
**Estimated time:** Varies.

> **Review queue (recommended fixes, to be worked next — not yet applied):**
> 1. ~~**Penalty / abort protocol**~~ — ✅ done: see *Risk Monitoring & Freeze Protocol*.
> 2. **Aggregate anchor-text ratio ledger** — per-run anchor % exists, but nothing tracks the whole profile's ratios.
> 3. **Operating theories** — MC4, link echo, and the 250-RD tipping point now carry *working model* labels; crawl-not-index is resolved to one rule. External sourcing still open.
> 4. ~~**Contradictions to reconcile**~~ — ✅ all resolved: ⚠-IDX, ⚠-DAS, ⚠-RD25, ⚠-GSA, ⚠-TFCF, ⚠-25PCT.
> 5. ~~Cost/budget model~~ — ✅ resolved externally: owned by the **Link Building & Campaign Recipe Engine**. **Still missing: success KPIs + review cadence, glossary.**
> 6. **Restructure recipes into one decision matrix** (page type × competition × current RD/TF-CF → recipe + anchor % + tier plan).

---

> **Cross-references:** decision ownership, shared definitions ("highly competitive", the hub threshold, GBP-linked page), global rules (never disavow; never-build-to list; deprecations), and the workflow chain live in **`_ORCHESTRATOR.md`** — read it before executing this SOP. Page types targeted here are defined in the **Site Architecture SOP**; ranking drops route to the **Rank Drop Mitigation SOP** (both branches active).

---

# Part 1 — Strategy & Theory

## Risk Monitoring & Freeze Protocol

**Scope.** This protocol covers the two failure modes link building is directly responsible for detecting — **manual actions** and **deindexing** — plus two link-building-specific health checks. **Ranking drops are out of scope here** and route to the **Rankings Drop SOP** (a defined "drop" lives in the organic rank tracker).

**Standing rule — we never disavow.** Response levers are: dilute anchors · throttle velocity · stop building · let the page settle · tier existing links. We do **not** remove links via disavow under any circumstance.

### Daily checks
- **Manual actions** and **deindexing** — checked **daily**, per client.
- On confirmed occurrence of either → **freeze** (below).

### Link-building-specific health checks (ongoing, non-escalating)
These are routine hygiene. They do **not** trigger a freeze and do **not** escalate — the SEO NEO assignee (Minda → Ivy, per §6) self-corrects with more/rebalanced link building.
- **RD imbalance** — periodically compare each money page's referring-domain count against the **home page's**. No inner page should carry far more RD than the home page (entity-dilution / unnatural-profile risk). Correction: build more RD to the home page, or ease off the inner page, to rebalance.
- **Anchor-ratio drift** — track the **cumulative** anchor-text mix per money page (not per run) and watch for it drifting out of target ratios. Correction: dilute with branded/naked links to pull the ratio back. *(Target ratios defined in the anchor-ratio ledger — fix #2.)*

### Freeze — on confirmed manual action or deindexing
1. Add an **alert on the client's card**.
2. **Pause all link building and content creation** for that client. _(This freeze extends beyond link building; the content-creation SOP should cross-reference it.)_
3. **Notify Kyle Sabraw, Ryan Maizis, and other Admins** (client-card tag: **Admin**).

This is a **freeze, not a recovery procedure** — it stops activity and escalates. Recovery is owned by Kyle / Ryan / Admins.

### Pre-push gate (overclock-capable diagrams)
Overclock-capable diagrams are **threshold-gated self-serve** (ruling 04 Jul 2026; consolidated limits in `_ORCHESTRATOR.md` §7):
- **Hydra at a client page** — self-serve only when **page RD > 100 · homepage RD > 200 · SERP avg RD > 100** (true counts). Below any threshold → sign-off from **Kyle Sabraw or Ryan Maizis**.
- **DAS v2 with RD100** — self-serve only when **page UR 5–25 · homepage UR 15–45**. Outside those bands → sign-off from Kyle or Ryan.
- **GSA / Xrumer blasts** — no self-serve thresholds defined; **always** get sign-off from Kyle or Ryan.

When a required read is unavailable or the call is unclear, escalate rather than run (halt-and-ask rule #1).

---

## The Backlink Equation

A link building strategy can be thought of as a mathematical equation. The backlink profile for each page should solve for three variables:

**Referring Domains + Contextual Relevance + Link Juice (link strength) = Ranking Power**

- **Referring domains** — the number of different domains (sites) linking to a page.
- **Contextual relevance** — the content of the linking page should be relevant to the client's page.
- **Link juice (link strength)** — how much PageRank is being pushed to the client's page.

This is per **page**, not per domain.

## The Link Juice Model

How much value a single link actually delivers is computable:

> **Delivered Juice = Host Juice (UR/DR) × Relevance% × Follow multiplier × Modifiers**

- **Host Juice** — the raw strength of the linking page/domain: **UR** (page) and **DR** (domain). *(Rationale: this is the muscle — the potential force behind the punch.)*
- **Relevance%** — contextual relevance scales delivery from **100%** (fully on-topic) down to **10%** (completely irrelevant). *(Rationale: the kinetic chain — all the muscle in the world lands soft if the body isn't aligned behind the punch.)*
- **Follow multiplier** — DoFollow passes **100%**; NoFollow passes **15%**. Tools build a *mix*, so: `Follow = DF% + (NF% × 0.15)`. *(Rationale: trained fighter vs. untrained — same muscle, same alignment, technique decides how much lands.)*
- **Modifiers** — e.g., **subdomain properties = ×0.5** (applies to DAS v2 and DAS v2 with RD100).

**RD (referring domains) is a separate axis** — the count of linking domains — and is not part of the juice calculation. Both variables must be solved per the Backlink Equation.

### Master Link-Type Table

| Tool | Cost | UR/DR | Relev. | DoFollow | **Deliv. mult.** | RD T1 | RD T2–5 | Embed / NAP |
|---|---|---|---|---|---|---|---|---|
| Guest post | >$150 | 30/60 | 100% | 100% | **1.00** | 1 | — | ✗ / ✗ |
| Cloud stack (Elias Cloud) | $10/run | 50/80 | 100% | 90% | **0.92** | 30 | 900 | 100% / 100% |
| Niche edit | $50–100 | 30/50 | 65% | 100% | **0.65** | 1 | — | ✗ / ✗ |
| Press release | $50 | 40/80 | 100% | 33% | **0.43** | 400 | — | 25% / 100% |
| Contextual To Text Advanced | $10/run | 20/45 | 60% | 50% | **0.35** | 116 | 2,900 | 50% / 50% |
| Contextual To Text | $10/run | 20/45 | 60% | 50% | **0.35** | ~23 | ~580 | 50% / 50% |
| DAS v2 | $10/run | 10/25 | 90% | 50% | **0.26** *(×0.5 subdomain)* | 100 | 1,000+ | 90% / 90% |
| Money Robot | $20/blast | 20/50 | 90% | 10% | **0.21** | 200 | 1,000 | 90% / 90% |
| Respect Mah Authoritay v2 | $10/run | 30/60 | 33% | 40% | **0.16** | 200 | 7,500 | 10% / 10% |
| Citations | $40/40 · $75/80 · $140/150 (batch) | 10/80 | 100% | 0% | **0.15** | batch | — | ✗ / 100% |
| Hydra | $10/run | 10/30 | 33% | 20% | **0.11** | 730 | 28,000 | ✗ / ✗ |
| DAS v2 with RD100 | $10/run | 10/25 | 33% | 50% | **0.10** *(×0.5 subdomain)* | 100 | 3,600+ | 50% / 50% |
| RD100 | $10/run | 10/40 | 5% | 5% | **0.01** | 175 | 2,600 | 10% / 10% |
| GSA | $25/blast | 20/50 | 1% | 0% | **0.0015** | 10,000 | — | 5% / ✗ |
| Xrumer | $25/blast | 10/50 | 0% | 0% | **0.00** | 100,000 | — | 0% / 0% |
| G Sites / OffPage Agent | $25 | 90/100 | 100% | 100% | **1.00** | 4 | ×4 per tier (T2: each RD gets 4; T3/T4 likewise) | ✗ / ✗ |
| Google Stack | $30 | 90/90 | 100% | 100% | **1.00** | 1 | 100 (T2) | embed T1 G-Site only / 100% |
| PBN — **deprecated for now** | $25 | 5/10 | 100% | 90% | **0.92** | 1 | — | — |
| Patch.com — **deprecated, do not use** | — | — | — | — | — | — | — | — |
| T1 Booster | — | *(row deferred — to be specced later)* | | | | | | |
| **GBP Blast** (maps — SEO NEO) | $5/mo | — | — | — | *driving-direction signal, not a link* | — | — | — |
| **Hyper Local GBP Blast** (maps) | monthly | — | — | — | *targeted driving-direction signal* | — | — | — |
| **GBP Sniper** (maps — SEO NEO) | $10/run | 40/80 | Low (~10%) | 33% | **High juice / low RD** → the GBP (follow-mix 0.43; ×low relevance) | low | — | qualitative |
| **Maps Embeds** (maps) | $5/run | 20/50 (Money Robot) | High (100%) | 100% | **Low juice / high RD** → the GBP (low host UR/DR, but full relevance + dofollow) | high | — | embed = the tactic |

**Maps-side rows:** the last four target the **GBP**, not the website — usage rules, cadences, and mechanics live in the Maps SOP §Part 7 (Standard Maps Tactics Stack). GBP Blasts are a driving-direction popularity signal rather than links, so juice columns don't apply.

**Reading the table (rationale):**
- **Deliv. mult.** = Relevance × Follow-mix × Modifiers — the fraction of the host's UR/DR that actually lands on the target. Guest posts deliver 100% *because* we write the page around the link (full relevance, full dofollow); a niche edit on an equally strong host delivers 65% because the host page's topic is only partly ours.
- **High-juice, low-RD** tools (guest post, cloud stack, niche edit) solve the *strength* variable. **Low-juice, high-RD** tools (RD100, GSA, Hydra) solve the *domains* variable. Most pages need both, in the 3–5:1 (local) / 2–3:1 (global) ratios below.
- **GSA** is pure spam — use sparingly, only under an extreme dearth of RD. **Money Robot / Xrumer** are pure spam — Tier 2 links only unless otherwise specified.
- **Embed/NAP %** = share of properties where an embed / NAP can be included (embeds count as dofollow links; NAP creates unstructured citations).

## Referring Domains

The number of referring domains (RD) is important for a healthy backlink profile.

**Tool-visibility discount (apply first):** backlink tools (DataForSEO, Ahrefs, Majestic) see only **~10%** of links actually built. So **competitor RD read from tools ≈ 10% of reality — scale competitor RD reads up by 10×** before using them. Our own client's RD is known-true (we built them), so **compare true-to-true**: client's actual RD vs. competitor's (tool read × 10). Never assume a client is "done" on RD because tool-measured counts match — the competitor's true count is ~10× what you see.

**The RD targeting rule (computable, on true-count basis):**
1. **Minimum** = the lowest true RD among the page-1 results (tool read × 10 for competitors).
2. **Target** = page-1 average *true* RD × **1.5**.
3. **Guideline (not a hard cap)** — the **×1.5 target rule governs** and may exceed 250. ~**250 true RD** is the sweet-spot guideline: when the page-1 average is below 250, out-building the SERP well past the target risks the MC4 caution below — use judgment past 250 rather than treating it as a ceiling. *(Reworded from "ceiling" 04 Jul 2026.)*

*(Rationale: ~250 true RD is the tipping point where even poorly optimized pages can rank bottom-of-page-1 for many SERPs — this is the old "25" figure corrected for the 10× tool-visibility discount. Most local SERPs average far less, and out-linking the SERP looks unnatural. High-competition SERPs justify going past 250 because the competition itself is there.)*

**Worked RD example.** If the SERP looks like:

| Spot | RD | Spot | RD |
|---|---|---|---|
| 1 | 14 | 6 | 11 |
| 2 | 5 | 7 | 9 |
| 3 | 17 | 8 | 10 |
| 4 | 8 | 9 | 6 |
| 5 | 9 | 10 | 12 |

…these are tool reads: true values ≈ ×10. The page needs a **minimum of ~50 true RD** and should **aim for ~100–150 true RD** (tool avg 10 × 10 × 1.5). 250 would still be best, but isn't strictly necessary here since no competitor approaches it.

**Solving for RD.** Technically any link works; the best way is with cheaper links. YMYL keywords need a greater mix of niche edits and guest posts and fewer cheap links. Preferred links for RD, in order:

1. SEO NEO — Respect Mah Authoritay v2
2. SEO NEO — DAS v2
3. SEO NEO — Elias Cloud
4. SEO NEO — RD100
5. Press releases *(only once every 4–6 weeks)*
6. ~~PBNs~~ *(deprecated for now — do not order)*
7. Citations ~~(including Patch.com)~~ *(Patch deprecated — do not use)*
8. Reddit posts / subreddits
9. Google stacks
10. Niche edits
11. Guest posts

The **Citation Flow (CF)** is Majestic's metric for how many referring domains a page has. Most sites that have had SEO done already invest in cheap links and have largely solved this variable.

## Contextual Relevance

The content of the linking page should be relevant to the client's page. This does **not** mean the entire linking site must be about the same topic. Most important for **guest posts**, which push the most PageRank.

**Tier-1 anchor text, most-used to least-used:**

1. Branded
2. Quadgram
3. Entities
4. Partial match / keyword variation
5. Exact match
6. Naked
7. Generic

Relevance by link type:
- **Citations** — industry or geo relevance, but relatively weak; need Tier-2 links.
- ~~**Patch.com**~~ — **deprecated, do not use.** *(Was: geo relevance, weak on service; needed Tier-2 links.)*
- **Guest posts** — service relevance.
- **Cloud stacks & Google stacks** — both geo and service relevance.

## Link Strength

Link strength is the amount of PageRank passed to the client's page — what people mean by "good links." Google no longer publishes PageRank scores, so we can't concretely know how much is passed. Approximate with:

- DR and UR (Ahrefs)
- TF (Majestic)
- ~~DA/PA (Moz)~~ — poor metric, **not used**
- Organic traffic to the linking site

**Links to build for strength:**
- G Site PBNs (via G Site Genie, aka Off-Page Agent)
- Guest post
- Niche edit
- Cloud stack
- Google stack

**Traffic floor:** "High DA/DR" links — especially PBNs — do **not** qualify for strength if they lack organic traffic. Guest-post organic-traffic minimum is **500/month**. "High DA/DR" sites with <500 organic visits/month are treated as PBNs and used only for the RD variable.

## Tiered Linking

Link strength and contextual relevance can be boosted with tiered linking.

- Google follows links **5 tiers** down. PageRank can be pushed 5 tiers up (T5 → T4 → T3 → T2 → T1 → money page). The optimal tiering uses guest posts, niche edits, and cloud sites, though it's expensive. **T4/T5 can be GSA, Xrumer, Money Robot, or Scrapebox.**
- Contextual relevance helps for tiered links but matters less than for Tier 1.
- **Never** build tiered links to guest posts or niche edits — bloggers hate it, will remove posts/links, and refuse future business.

**Budget-friendly tiering order:** SEO NEO → G Site Genie (OffPage Agent) → Cloud Sites → ~~PBNs~~ *(deprecated for now)* → GSA → Money Robot → Xrumer.

**Anchor text by tier:**

| Tier | Anchor text |
|---|---|
| Tier 2 | Brand or Entities |
| Tier 3 | PMQ or Related Searches |
| Tier 4 | PMQ, EMQ, or Related Searches |
| Tier 5 | EMQ or Related Searches |

## Link Velocity

Google tracks how quickly links are built, both to a page (Tier 1) and at Tier 2–5.

- **Tier 1:** no more than **1/day** per page — **applies to manually built links only** (guest posts, niche edits, PRs, manually placed links). **SEO NEO's internal dripping is exempt/trusted** — a diagram's own Tier-1 pacing satisfies velocity requirements.
- **Tier 2–5:** drip-fed over **30 days**.

## Link Strength & Expected Outcomes

- Links typically take **6 weeks** to take full effect.
- Links start to lose power ("link decay") in **4–6 months** unless crawled again or continuously tiered.
- **Crawl vs. index — one rule:** **Crawling (Colinkri) is the floor for all tiers** — a crawled link is a credited link. **Indexing (Omega) is Tier-1 only** — its purpose is maximizing PageRank transfer to the money page, not credit. Indexing Tiers 2–5 is prohibited as cost-prohibitive.

- **Link echo** *(working model)*: if a link is created and crawled, the page gets credit for ~**4–6 months** even if the link is later removed.

## Anchor Text for Niche Edits & Guest Posts

- Niche-edit anchors should always be **quadgrams, partial-match keywords, or entities**. Exact-match or branded anchors risk longer posting times (harder to fit naturally).
- For guest posts, if **we** write the content we have more control over anchors. If we don't write it, use the same guidance as niche edits.

## When to Do Link Building

- Monthly, regardless of current rankings. Branded anchors to the **home page** are the safest to build.
- Link building should **not** be the focus of a campaign — links only bolster pages that already have optimized content, technical SEO, and internal links.
- Competitive local keywords (YMYL, water damage, fire damage, locksmith, garage door repair, etc.) need more niche edits, guest posts, and cloud stacks.
- Global-index keywords (e.g., blog posts) need a higher ratio of niche edits and guest posts.
- If organic rankings stick between **spots 5–10** (and on-page/technical/internal linking are solved), more links may be needed.

### Link Building Targets for Maps Rankings

If geo-grid rankings stick between **spots 3–6** (and on-page, technical, internal linking, and CTR are solved), more links may be needed. Determine where the rankings are stuck:

- **Stuck across an entire city contained within the 5×5 grid:**
  - Build links to the local landing page and the home page.
  - Check RD first, then link strength.
  - Tier-1 anchors: branded or quadgram.
- **Stuck in specific areas of a city contained within a 5×5 grid:**
  - Build links to the local landing page.
  - Check RD first, then niche edits / Google stacks / cloud stacks / guest posts.
  - Tier-1 anchors: quadgram or partial match.
- **Stuck in specific areas/neighborhoods of a city larger than a 5×5 grid:**
  - Build links to the silo page.
  - Check RD first, then niche edits / cloud stacks / Google stacks / guest posts.
  - Tier-1 anchors: branded or quadgram.

## Link Building Strategy Overview (audit → plan)

**1. Check the client's current backlink profile.**
- How many RD does the whole site have? How many do the money pages have — close to the competition's?
- Check RD in Ahrefs and/or Majestic. Majestic TF/CF quickly shows strength vs. sheer domain count.
- Target a **TF/CF ratio around ½** (TF ≈ half of CF). Rule of thumb, not gospel — check the SERPs and use judgment.
  - TF/CF **< ½** → enough RD; needs **stronger** backlinks.
  - TF/CF **> ½** and CF ≤ 15 → needs to focus on **RD**.

> **Scope rule:** use **URL-level TF/CF** for money-page decisions (the ½ rule above is a per-page diagnostic); use **domain-level TF/CF** for the site-wide profile audit in Step 1. Both get used — label which one you're reading.

**2. Check what the backlinks are** (Majestic/Ahrefs): mostly PBNs? Citations? Press releases? Guest posts? Niche edits? Web 2.0 mininets?

**3. Spot-check competitors.** Is the client's DR, UR, and TF **within 25%** of the competition?
- If not → they likely need stronger links.
- If yes and still not ranking → check on-page quality, RD, and contextual relevance.

> **Formula:** "within 25%" = **client metric ≥ competitor metric × 0.75** (the client's DR/UR/TF is at least 75% of the page-1 competition's). Example 3 below: client DR 30 vs. SERP avg 50 → 30 < 37.5 → *not* within 25% → stronger links required.

**4. Start the strategy.**
- Every client should have a **branded IFTTT ring** built, with SEO NEO or GSA links pointed at it.
- **Local SEO ratio (rule of thumb):** ~**3–5 RD links : 1 strength link** per page that needs links. Every client should have at least **1** strength link. Examples:
  - DAS v2 + 1 Guest Post
  - Respect Mah Authoritay v2 + 1 Cloud Stack
  - ~~5 PBN links~~ *(PBNs deprecated for now)* + 1 Niche Edit + 1 Google Stack
  - 1 Cloud Stack + 1 Guest Post
  - 1 PR + 2 Niche Edits
- Once RD is solved, move to strength.
- **Global-algorithm ratio** (blog posts / global keywords): ~**2–3 RD links : 1 strength link**. Examples:
  - SEO NEO DAS v2 + 1 Cloud Stack + 1 Google Stack
  - 5 PBN links + 1 Niche Edit + 1 Google Stack + 1 Guest Post
  - 1 Cloud Stack + 1 Guest Post
  - 1 PR + 2 Niche Edits + 2 Guest Posts
- Guest Posts, Cloud Stacks, Google News posts, and Press Releases should be **written as if they were a money page** on the client's site (solves contextual relevance).
- Citations are always contextually relevant as long as they're on an industry- or geo-specific directory.
- ~~Patch.com is local-SEO only.~~ **Patch is deprecated — do not use.**
- When in doubt, **build stronger links rather than more RD**.

**Build tiered links to:** Citations · ~~Patch.com posts~~ *(deprecated)* · Press releases · Reddit posts / subreddits · Google Sites / Stacks / Sheets · Cloud pages / stacks · (Guest posts & niche edits **only with Senior SEO approval**).

**Always build links to:** Home page · Top-level category pages (Service, Areas We Serve) · Local landing / city+service pages · Blog posts.

**Case-by-case (not automatic):** Silo pages · About Us pages.

**Never build links to:** Contact Us · Privacy Policy · Terms of Service · Bio pages · Sitemaps · Images · PDFs · PPC landing pages.

**Never build tiered links to** (unless Senior SEO instructs): Guest posts · Niche edits.

**Indexing/crawling (per the crawl-vs-index rule):** Tier-1 links (guest posts, niche edits, sites.google.com, SEO NEO Tier 1) → **indexer (Omega)** for full PageRank transfer. Tiers 2–5 → **crawler (Colinkri)** for credit.

## Link Building Notes

- **Legal & medical niches** need a large volume of stronger links. Priority order: Guest Posts → Niche Edits → Google Stacks → Cloud Stacks.
- **GSA / Money Robot / Xrumer / Scrapebox** are good for already-strong domains: Google Sites & Stacks, Cloud Sites & Stacks, YouTube, Citations.

> ✅ **[⚠-GSA — resolved]** Single rule: **GSA / Money Robot / Xrumer are allowed at Tier 2–5, never Tier 1.** Money Robot and Xrumer are pure spam — Tier 2 links only unless otherwise specified; GSA only under an extreme dearth of RD.

- **MC4** *(working model — agency term)*: Google's anti-SEO algorithm that triggers when a site or GBP **relies far too heavily on one tactic** — link building, CTR, content creation, or any other single lever pushed out of proportion. The defense is proportionality: solve the variable that's actually deficient (per the Backlink Equation), don't hammer one tactic past what the SERP supports. The RD ceiling above (250 true RD) is one specific application; the same over-reliance logic applies to CTR software and content volume. There is no numeric aggregate cap — proportionality is a judgment call.
  - **No hard aggregate cap.** There is deliberately **no fixed monthly ceiling** on combined links/tactics per page — links are built every month per the retainer. MC4 avoidance stays a **judgment call** guided by the RD ceiling (don't out-build the true-count SERP) and proportionality (fund the deficient variable, don't pile everything on one lever). Per-tactic cadences (velocity, PR frequency, overclock gates) still apply individually.

- **Embeds** are treated as dofollow links and are read as part of the page they're embedded on.

---

# Part 2 — Execution: SEO NEO

## What Is SEO NEO

SEO NEO is a powerful automated link-building tool that builds links on Web 2.0 properties, social media sites and profiles, forum profiles, PDF-upload sites, bookmarks, cloud storage, URL shorteners, and blog comments. We use it as a cost-effective way to build many mid-to-high "authority"/"trust" links.

It builds links by cycling through emails, using spun content (spintax), posting content on blogs, uploading PDFs with content and links, or using "personas" to create social/forum profiles that include a naked URL.

These are powerful for local SEO: the properties often include an NAP (unstructured citations), dofollow and nofollow links, embeds (e.g., a GBP), and "persona" profiles of client fans — all of which help Google trust the client.

**vs. GSA:** GSA is best for mass blog comments, forum profiles, pingbacks, and redirects (tens of thousands at a time); includes no content except Tumblr/WordPress.com; needs fresh forum/site lists monthly; no built-in OpenAI content; should be Tier 3–5, not Tier 1 (except rare cases).

**vs. Money Robot:** uses its own PBN (except Tumblr/WordPress.com), which is weaker than SEO NEO's public Web 2.0s; no social sites/profiles, cloud, URL shorteners, PDF uploads, bookmarks, or blog commenting; no built-in OpenAI content.

**vs. Ranker X:** fewer Web 2.0 properties; no blog comments, cloud sites, or PDF uploads; no built-in OpenAI content.

## SEO NEO Run Setup

Inputs the SEO NEO assignee (Minda → Ivy overflow, per `_ORCHESTRATOR.md` §6) needs:

- **Anchor text & topic** — for the Tier-1 links. Tier-2-and-below anchors are derived from the Tier-1 anchor/topic. Provide preferred anchor text per tier: Brand, Quadgram, Naked URL.
- **Main keyword for the topic** — the money-page keyword; guides Tier-2-and-below anchors.
- **URL(s) to link to** — the money page(s). Multiple allowed, but keep to **≤5** for max PageRank.
- **Content:**
  - Use the **internal content tools** (AR Tools content pipeline) — *unless* the target is the home page or About Us page.
  - Content must be relevant to the money page. (E.g., pushing "plumber in Los Angeles" → the content run is for that keyword.)
  - Home / About Us targets don't need keyword-optimized content — just branded content.
  - Content *can* use the built-in AI writer; it's slower and less optimized.
- **NAP.**
- **Embeds** — multiple allowed. All local clients get a **GBP embed**. Others: Google Sheet from a G Stack, Google Sheet from a PR, YouTube video, SoundCloud, Reddit post.
- **Diagram to run** — tell the assignee which diagram.
- **Daisy chaining** — tell the assignee if multiple runs are chained, and how many times.

## SEO NEO Strategy — Pages to Target

Run SEO NEO to: Home Page · Each Local Landing Page · Each Location Page · Each Service Page · About Us · Social Profiles.

Link building typically depends on: age of the site · current backlink profile · competition's backlink profile.

> **Entity-balance caution:** don't let inner pages accumulate far more referring domains than the home page. Inner pages out-linking the brand risks diluting the entity (why would a keyword page outrank the brand if done white-hat?) and looks unnatural to Google.

### Recommended Process (per page type)

*A guide, not set in stone.*

**Home Page**
- DAS v2, 4× daisy-chained. 90% Branded / 10% Naked URL
- Contextual To Text Advanced, 2× daisy-chained. 100% Branded
- Respect Mah Authoritay v2. 100% Branded
- DAS v2 with RD100. 100% Branded — **only** for ultra-competitive niches, only if ranking is stuck and all on-page is done. If not, start the process over.

**Local Landing Page**
- DAS v2, 4× daisy-chained. 100% Branded
- Elias Cloud, 2× daisy-chained. 100% Branded
- DAS v2, 4× daisy-chained. 75% Branded / 25% Quadgrams
- Elias Cloud, 2× daisy-chained. 75% Branded / 25% Quadgrams
- Respect Mah Authoritay v2, 4× daisy-chained. 75% Branded / 25% Quadgrams *(×2)*

**Location & Service Pages**
- DAS v2, 4× daisy-chained. 100% Branded
- Contextual To Text, 2× daisy-chained. 75% Branded / 25% Quadgram
- Elias Cloud, 2× daisy-chained. 75% Branded / 25% Quadgram *(×2)*
- Respect Mah Authoritay v2, 4× daisy-chained. 75% Branded / 25% Quadgrams *(×2)*

**About Us Pages**
- Contextual To Text. 100% Branded
- Respect Mah Authoritay v2. 100% Branded

**Social Profiles (incl. Reddit, Citations, Branded G Stacks)**
- Hydra. 100% Branded
- RD100. 100% Branded *(only if no effect from Hydra after 6 weeks)*

**Guest Post / Niche Edits / Benzinga / Barchart / Digital Journal / Globe and Mail / Press Synergy**
- T1 Booster. 50% Branded / 50% Exact Match Keyword *(T1 Booster spec pending — its master-table row is deferred; confirm setup with Kyle before first run)*

**Keyword G Stacks & all Cloud Stacks**
- Hydra. 50% Branded / 50% Exact Match Keyword
- RD100. 50% Branded / 50% Exact Match Keyword *(only if no effect from Hydra after 6 weeks)*

> ✅ **[⚠-DAS — resolved]** "DAS" = **DAS v2** (one diagram). Naming normalized to DAS v2 throughout.

### Brief Explanation of the Diagrams

- **Contextual To Text** — moderate power, fewer RD than others. Use where competition is weaker and RD isn't the goal but power is. Best used after DAS v2 (which has more RD, less power).
- **Contextual To Text Advanced** — the most pure power that can be safely pointed directly at most sites (Contextual To Text ×4, with different property sets as Tier 1). Best on the homepage to build entity. On inner pages only for highly competitive terms (e.g., "Bronx Car Accident Lawyer") and only after all other diagrams (except DAS v2 with RD100) have failed. Very powerful, lots of RD — can easily overclock a page.
- **Domain Authority Stack v2 (DAS v2)** — good all-around, safe on all pages. All Web 2.0. Good balance of power and RD. Usually the first diagram used. Daisy-chain 4 at a time for most power. "The Toyota Corolla of diagrams."
- **DAS v2 with RD100** — the most powerful diagram, for both power and RD (DAS + 100 extra referring domains). Use very sparingly — only very competitive niches or entity rebalancing. **Self-serve only within the pre-push-gate UR bands (page UR 5–25 · homepage UR 15–45); otherwise talk to Kyle Sabraw or Ryan Maizis first.**
- **Elias Cloud** — cloud stacks. Lots of authority; great for trust/entity. Use after DAS v2. Can be repeated to a page using different storage locations for a powerful effect.
- **Hydra** — the biggest diagram. Only for the most trusted/authoritative sites (e.g., social media); point at a client's site **only within the pre-push-gate thresholds (page RD > 100 · homepage RD > 200 · SERP avg RD > 100)** or as directed by Kyle Sabraw or Ryan Maizis. Can overclock a client's site in a single use. Usually not daisy-chained.
- **RD100** — one of the bigger diagrams. Lots of RD, less power than Contextual To Text or Hydra but more than T1 Booster. Only for social media, guest posts, niche edits, or citations.
- **Respect Mah Authoritay v2** — good for increasing RD; moderate power. Use after DAS v2 and cloud stacking, or in niches competing on sheer link/RD count (locksmiths, medspas) rather than link power.
- **T1 Booster** — weak links, lots of RD. Used so guest posts don't accidentally outrank the money site while still pushing power to them. Despite the RD count, **not** recommended for adding RD to the money site (properties are low quality).

> Typo note: "Hyda" in the source = **Hydra** (normalized here).

### Use Cases for the Diagrams

**Money page needs more link power** — Contextual To Text → Contextual To Text Advanced → DAS v2 with RD100 → Elias Cloud. *(Order balances posting speed with pure power. If time isn't a factor, DAS v2 with RD100 is the safest power push, but drip it over 3–4 weeks to avoid clogging the software.)*

**Money page needs more referring domains** — Respect Mah Authoritay v2 → DAS v2 → Elias Cloud → RD100.

**Brand-new site / little-to-no link building** — DAS v2 → Elias Cloud. *(Both allow an article, NAP, embeds, and optional schema embedding, from safe/trusted Web 2.0s or cloud storage.)*

**First links to a new page** — DAS v2.

**Weak entity / needs branding** — DAS v2 → Elias Cloud → Respect Mah Authoritay v2 → Hydra → RD100. *(Article/NAP/embeds/schema from DAS & Elias Cloud; social + forum + blog-comment Tier 2 from Respect Mah Authoritay v2; massive power to social from Hydra & RD100 — builds Google's trust in the entity.)*

## Crawling, Indexing, Captcha

Every SEO NEO run must include **crawling** and **captcha** to succeed. **Indexing** is optional and should only be done for Tier-1 links.

- **Crawling** — via **Colinkri**, which calls Googlebot to crawl each built link. Google doesn't need to index every link, just have a record of it.
- **Indexing** — via **Omega Indexer**. Ensures each link passes full PageRank to the money page. Only index **Tier-1** links (the ones pointing at the money page); indexing all tiers is prohibitively expensive.
- **Captchas** — required for posting; auto-solved to get past security.

---

# Part 3 — Worked Examples

### Example 1 — Mid Competition
Target: "dentist in los angeles" → `client.com/los-angeles/dentist` (newly published, no links). Site 3 yrs, DR 20; landing page UR 5.
Page-1 average: DR 22 · UR 7 · Avg RD 10 · lowest RD 5.
**Read:** mid-competition. Client is within 25% of DR/UR. Need ≥5 RD, ideally 10–15. Tier links and aim above the page-1 avg.

- **Tier 1:** 2× Niche Edits (quadgram/entity anchor) to local landing page · 1× Guest Post (1000 traffic/mo, branded) · SEO NEO (if home or local landing is the target) · 1× Branded Subreddit (naked)
- **Tier 2–4:** SEO NEO to the subreddit, guest posts, and niche edits

### Example 2 — Low Competition
Target: "all on four implants san clemente" → `client.com/san-clemente/dental-implants/all-on-four/` (new, no links). Site 5 yrs, DR 10; UR 1.
Page-1 average: DR 12 · UR 2 · Avg RD 2 · lowest RD 1.
**Read:** low competition, likely no tiering needed. Within 25% of DR/UR. Need ≥1 RD, ideally 2–4.

- **Tier 1:** 2× Niche Edits (quadgram/entity) · SEO NEO (if home or local landing) · 1× Branded Subreddit (naked)
- **Or:** SEO NEO (if home or local landing) · 1× Branded Subreddit (naked)

### Example 3 — High Competition
Target: "car accident lawyer los angeles" → `client.com/los-angeles/car-accident-lawyer/` (new, no links). Site 6 yrs, DR 30; UR 15.
Page-1 average: DR 50 · UR 20 · Avg RD 30 · lowest RD 20.
**Read:** high competition, needs tiering. Client **not** within 25% of DR/UR → focus on authoritative guest posts and niche edits with extensive tiering. Need ≥20 RD, ideally 30–45.

- **Tier 1:** 5× Niche Edits (quadgram/entity) · 5× Guest Post 1000 traffic (quadgram) · 5× Guest Post 500 traffic (quadgram) · 1× Cloud Trio (branded) · 1× Google Stack (branded) · 1× Google Stack (keyword) · SEO NEO (if home or local landing) · 1× Press Release (branded) · 1× Branded Subreddit (naked)
- **Tier 2:** 250 PBN links to Tier-2 cloud site in cloud trios (branded) · SEO NEO (entity anchor) to Branded Subreddit
- **Tier 3:** 250 PBN links to Tier-3 cloud site in cloud trios (branded) · 1000 PBN links to Google sheets/docs/slides in each Google stack
- **Tier 4 & 5:** GSA blast (min 15,000 links) **or** Xrumer blast (min 20,000 links)
