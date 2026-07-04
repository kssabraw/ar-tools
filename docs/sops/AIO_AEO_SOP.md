# AIO / AEO SOP — Ranking In & Defending Against AI Overviews and LLM Answers

**Current as of:** 03 July 2026
**Goal:** Get client brands mentioned and cited in Google AI Overviews / AI Mode (AIO) and in LLM answers (AEO), and defend against AIO click absorption.
**Who this is for:** All local SEO clients.
**When:** Offensive signals are built into standard content/GBP work; the defensive protocol triggers on LABS findings or the Organic branch's B2 handoff.
**Assigned to:** Per §6 (writers own on-page execution; Minda/Ivy content; Kyle strategy).
**Scope:** AIO/LLM visibility strategy and response. On-page execution → writers/on-page agents. Monitoring → LABS.

> **Cross-references:** B2 click-absorption handoff → Rank Drop Organic branch · entity building → Maps SOP Part 5 · GBP completeness → Maps SOP Part 2 · reviews → Maps SOP Part 3 · G Stacks & tactics costs → Link Building master table · roles → `_ORCHESTRATOR.md` §6 · monitoring → **LABS agent**.

---

# Part 1 — How AIO and AEO Work (Theory)

## Definitions

- **AIO — AI Overviews Optimization:** getting brand mentions and citations (links) in Google's AI Overviews and AI Mode.
- **AEO — Answer Engine Optimization:** getting brand mentions and citations in LLMs — ChatGPT, Claude, Gemini, Perplexity, Copilot, etc.

They overlap but draw from **different ranking factors** and surface answers differently (see the platform-influence matrix, Part 2).

## How Consumers Use LLMs and AIO vs. Classic Search

**Problem-aware stage.** Customers increasingly start in an LLM with a full conversational question ("my kitchen sink is backing up — what could cause this, do I need a plumber?") rather than a keyword search. ~60% of LLM users phrase complete questions. Content must answer "what's wrong and what fixes it" *before* the searcher knows the service category. On Google, this stage is still short keyword hunts plus click-throughs.

**Solution-aware / comparison stage.** LLMs shift into recommendation mode — ~40% of users ask AI to compare options, ~35% use it for best price/value. Only ~12% of LLM users click through to websites, so the **LLM's synthesized shortlist effectively replaces the ten blue links.** Google users still do classic multi-source comparison (~73% check multiple sources).

**Trust.** ~68% of consumers say they trust an LLM recommendation over a raw Google result. Gemini and Google AI Mode **heavily favor GBP data** as the source of truth for local businesses, while also crawling the business's own site to verify it truly offers the queried service. ChatGPT leans on **Bing** data — making Bing Places matter there. NAP consistency across website/GBP/Yelp/directories remains a foundational cross-referenced trust signal.

**Where the journey ends.** Only ~14% transact inside the LLM. The LLM narrows "hire a plumber" to two or three names; the customer then **searches the brand on Google or goes straight to the GBP/website** to check reviews and call. **The GBP and website are the closing touchpoint even when an LLM did the recommending** — this fact drives the defensive protocol in Part 3.

**AIO's place.** AI Overviews sit inside Google results and behave more like an LLM than a link list. They trigger on ~98% of purely informational queries vs. ~40% of commercial ones, and ~68% of local business searches (especially hybrid queries like "best way to remove a dead tree near me"). AIO can cut organic CTR by up to ~70%; only ~1% of searches with an AI summary produce a click on a link inside it; ~60% of AI-influenced searches end with **no website visit at all**.

## How AIO Selects Sources (Local)

*(Working model — from our testing, labeled per convention.)*

- AIO answers by combining source types: business sites, GBPs, local landing pages, review platforms, directories, local news, industry/government pages, forums, social mentions.
- **No AI-specific markup exists.** Pages need to be crawlable, indexable, snippet-eligible. Standard controls (`nosnippet`, `max-snippet`) affect AI availability.
- **Entity clarity dominates** — who the business is, where it operates, what it offers, whether it's trustworthy — closely tied to relevance/distance/prominence.
- **Query fan-out:** one local query is decomposed into related sub-questions (emergency availability, coverage, reviews, pricing, licensing, response time), and AIO cites the sources that best support each part — not simply the top blue link.
- **Top-20 eligibility** *(working model)*: AIO sources typically come from the **top 20 organic results**. You don't need #1 — you need to be Google's most trusted, extractable source for the specific question.
- **Backlinks are not a primary driver** *(working model)*: pages with few or zero measurable backlinks appear in AIO when entity strength, brand understanding, topical completeness, and Knowledge Graph confidence are high.
- Most likely local source candidates: GBP, location/service-area/service pages, review profiles, directories, local press, chamber pages, BBB, niche directories, Yelp, Trustpilot, Reddit, social profiles — **trust rises when the same core facts are consistent across many sources.**

## How Other LLMs Select Sources (Local)

- LLMs **synthesize** — retrieve, compare, summarize. The winning source is the clearest, most specific, most verifiable — not necessarily the Google #1.
- **Entity clarity and cross-platform consistency** drive selection: identical facts across website, GBP, Bing Places, Apple Maps, Yelp, Trustpilot, BBB, socials, citations.
- **GBP completeness ≈ 40% of local AI visibility factors** *(working model — internal testing)*: categories, description, services, products, service areas, hours, attributes, photos, posts, review count/velocity/quality, keyword-rich reviews, owner responses. This makes GBP optimization the single highest-priority AEO task.
- **GBP Q&A is discontinued** — move Q&A-style content to visible website FAQs, GBP posts, service descriptions, and review responses.
- **JSON-LD is not an LLM selection factor** *(working model — no measurable impact in our testing)*: treat LLMs as unable to rely on schema. **Never hide important facts in schema alone — every important fact must appear in visible body text.** (Schema still serves Google organic/maps/AIO eligibility — Architecture SOP unchanged.)
- Reviews are extraction fuel: "ABC Plumbing fixed our leaking water heater in Anaheim the same day" beats "Great service." Prompt customers to describe **service, location, problem, outcome** — without scripting them.

## Writing for Extraction (applies to both AIO and LLMs)

1. **Active voice** — clear subject-verb-object; no vague marketing copy.
2. **RDF-style triples in body content** — entity → relationship → attribute: "ABC Plumbing provides emergency drain cleaning in Anaheim." / "ABC Plumbing serves homeowners in Anaheim, Fullerton, and Orange."
3. **Question-type subheadings** matching real decision queries: "How much does drain cleaning cost in Anaheim?" / "Is ABC Plumbing licensed and insured?"
4. **Decision-fit fan-out** — cover the surrounding decision points: availability, areas served, emergency/same-day, pricing factors, licensing/insurance, experience with specific problems, customer types, reviews, process/timeline, guarantees, comparisons, objections, FAQs, before/after proof.
5. **First-hand local proof** — photos, projects, staff bios, landmarks, neighborhoods, customer stories.
6. **Freshness** — hours, services, pricing context, photos, staff, service areas kept current.

**The goal is not to trick AIO/LLMs — it's to make the client the clearest, most verifiable, most corroborated local entity for the target service and location.**

---

# Part 2 — Offensive: Getting Cited/Included

**On-page execution is owned by the writers** (on-page agents / content pipeline) — the extraction-writing rules above are their spec.

## Platform-Influence Matrix

| Lever | AIO | LLMs |
|---|---|---|
| Google Sites, Google Docs, Google Sheets (G Stacks) | **Huge** | ✗ |
| Site size + on-site knowledge-graph completeness | **Huge** | ✗ |
| Medium, Vocal.Media, LinkedIn Pulse | ✗ | **Huge** |
| Trustpilot, Reddit comments, directory citations | ✗ | **Huge** |
| Yelp · GBP · sheer volume of off-page brand mentions · Yext citations · YouTube | **Shared** | **Shared** |

**Cross-wiring:** G Stacks ($30, Link Building master table) are therefore an **AIO tactic**, not just link building. Medium/LinkedIn/Reddit posts ($10 each, master table) are **AEO tactics**. The Maps SOP Part 5 entity procedure and Part 2 GBP procedure are the shared foundation for both.

---

# Part 3 — Defensive: The Click-Absorption Response

**Triggers:** (a) the Organic branch's **B2** handoff — *AI Overview appeared, position stable, clicks collapsed*; or (b) **LABS** flags a visibility loss on its scheduled run.

**Step 1 — Classify via LABS:** is the client **cited/mentioned** in the Overview, or **excluded** from it?

## Fork A — Excluded from the Overview

Run the offensive play at this page/query, in order:
1. **Confirm top-20 organic** for the query. Not top-20 → this is a normal ranking problem first (Rank Drop Organic branch), not an AIO problem.
2. **Extractability rewrite** — RDF triples, question headings, decision-fit fan-out, active voice (writers execute).
3. **Entity/corroboration push** — cross-platform consistency signals (Maps SOP Part 5), review depth (Part 3), third-party corroboration.
4. **AIO-specific lever:** Google Sites / Docs / Sheets (G Stacks) supporting the page/entity.

## Fork B — Cited, but clicks still down

The click cannot be won back — this is the zero-click reality (CTR −70%, ~60% of AI-touched searches end with no visit). The play follows "Where the Journey Ends":
1. **Harden the closing touchpoint** — GBP completeness (Maps Part 2), branded SERP, review depth and recency, accurate hours/photos/services.
2. **KPI reframe (committed):** success for AIO-affected queries is measured by **mentions + links (the LABS win definition), branded-search lift, and GBP actions (calls, direction requests, website clicks)** — not organic sessions. The 6-week escalation judges *these* metrics for AIO-affected pages, not traffic.

## The Client Conversation

Standard explanation for "traffic dropped, rankings didn't": *an AI Overview now answers this query above the results and absorbs most clicks — this is happening across the whole web. Here is your AIO citation status (LABS), your brand-mention trend, and your calls/direction requests — the numbers that still map to revenue. Our job is being the business the AI recommends and the profile that closes the customer.*

---

# Part 4 — Measurement: LABS

**LABS (Local AI Brand Strength)** — internal app, runs on a **schedule** (like the organic rank tracker). It continually monitors LLM and AIO visibility and **suggests corrections** when a brand is not being shown.

- **Win definition:** the brand gets a **mention AND a link.**
- Track across query types: service+city, "near me," best-of, cost, emergency, comparison, problem-based, review-based — across the **six tracked engines**: ChatGPT, Claude, Gemini, Perplexity, Google AI Overview, and Google AI Mode. *(Copilot: possible future engine — not currently tracked by LABS.)*
- Per test, record: AIO/LLM present? client mentioned? cited with link? competitors mentioned? which third-party sources are cited? any incorrect/outdated information in the answer?
- One-time checks are insufficient — answers vary by platform, model, retrieval, wording, location, and freshness.

---

# Part 5 — Diagnostics

| Symptom (LABS / analytics) | Likely cause | Action |
|---|---|---|
| Clicks collapsed, position stable, AIO on SERP | Click absorption | **Part 3** (B2 handoff): Fork A or B per citation status |
| Client excluded from AIO; not top-20 organic | Ranking, not AIO | Rank Drop Organic branch |
| Client excluded; top-20 but never cited | Extractability / entity | Fork A steps 2–4 |
| Cited in AIO but not in LLM answers | LLM-side gaps | LLM levers: Medium/LinkedIn Pulse/Reddit/directories, Bing Places, cross-platform consistency |
| In LLM answers but not AIO | AIO-side gaps | G Stacks, site size/KG completeness, top-20 confirmation |
| LLM answer contains wrong/outdated facts | Stale or inconsistent entity data | Correct at the source LABS identifies (GBP, site, directories); freshness pass |
| Competitors mentioned, client absent, all above solved | Corroboration/prominence gap | Third-party mention push (Recipe Engine: brand-mention tactics, reviews, PR) |
