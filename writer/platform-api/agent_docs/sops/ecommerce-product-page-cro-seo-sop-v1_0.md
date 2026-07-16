# SOP: Ecommerce Product Page — CRO + SEO + Max-Cosine Score (MCS)

**Status:** Authoritative writing spec for the **Ecommerce Product & Collection Writer** module.
**Scope:** Ecommerce product detail pages (PDPs) primarily; the MCS + AEO writing methodology (Parts A–B) also applies to collection/category pages (PLPs). Use as a build spec for new pages and an audit checklist for existing ones.
**Where it's enforced:** baked into the nlp-api ecommerce prompts — generation follows Parts A–B, and the 8-engine scorer (`_ECOMMERCE_SCORE_SYSTEM_PROMPT`) scores adherence within `aeo_llm_retrieval` / `product_content_depth` / `conversion_readiness`, with deterministic list/table/bold counts from `_detect_ecommerce_structure`. So every generated page is written this way and auto-reoptimized toward it.
**Directive key:** MUST = ship blocker. SHOULD = strong default. MAY = situational.

---

## Part A — Max-Cosine Score (MCS) writing methodology

The "main entity" is the product (PDP) or the category (PLP).

1. **Direct Definition.** The first sentence under the H1 is a plain `[Main entity] is [what it is] + [key benefit]` — standalone, high-confidence, quotable.
   - DO: "Lepidolite is a lilac-grey lithium-bearing mica used in crystal healing for its calming lithium content."
   - DON'T: "Lepidolite is one of those special stones people have loved for all sorts of reasons."
2. **Zero-Filler Protocol.** No conversational warm-up anywhere. Move straight to the substantive answer under every heading.
   - DON'T: "In today's fast-paced world, we could all use more calm. Have you ever wondered…"
3. **MCS headings — `[Main entity] + fact-forward topic`.** Every H2/H3 names the main entity and pairs it with a fact-forward topic, not a bare topic word. Naming the entity and immediately following it with a fact moves the heading measurably closer to the AI's preferred, "liftable" output.
   - DO: "Angel Number 327 Signifies Stability in Marriage", "Acme Trail Runner Grips Wet Rock with Vibram Megagrip".
   - DON'T: bare "Meaning", "Features", "Details", "Overview".
   - **Avoid the exact-match query (EMQ) verbatim in H2–H6** — front the entity + a fact instead (the only exception is the rare case where the EMQ and the main entity genuinely converge with no other wording).
4. **One Main-Entity EMQ in the body.** Include the primary search phrase verbatim **exactly once**, in normal `<p>` body text (never in a subheading).
5. **Extractable Snippets.** Every key claim is a standalone sentence, true and liftable without surrounding context (a machine could quote it verbatim).
   - DO: "Leave crystals in direct moonlight overnight — about 6 to 8 hours — for a full charge."
   - DON'T: "The amount of time really depends on a few things we'll get into."
6. **List-Top.** Place a scannable bulleted/numbered list high on the page, ideally immediately after the Direct Definition (key features/specs, or how-to steps). Outcome-first items.
7. **Tables (Fact-Sentence model).** Top pages average ~2 tables. Every row reads `[Main entity / choice] → [relationship] → [verifiable fact]`, under three constraints:
   - **No dangling adjectives** — the final cell MUST be a number or noun-entity ("8.5 Mohs", "$125/mo", "1.2 kg", "IP67"), never "High"/"Reliable"/"Best".
   - **Feature-to-use-case binding** — tie each spec to the scenario where it matters.
   - **Consensus alignment** — real measurements/prices in standard units.
   - Table columns: **Choice (main entity) · Technical spec (exact number/unit) · Decision-fit (use case) · Tradeoff (quantified delta).**
   - Never invent a number — if a spec is unknown, omit the row and record it in the content-gaps report.
8. **Pro tone.** Maintain strictly positive sentiment toward the product/category throughout (correlates with a higher citation rate).
9. **Bold/strong hygiene.** Median ~7 `<strong>` tags per page; **never exceed 15** (over-bolding is heavily associated with deindexing).

## Part B — AEO writing principles

- **Value proposition up top** — a specific, concrete outcome the buyer gets (not hype).
- **User intent over keywords** — answer what the buyer is trying to accomplish, in their language.
- **Featured-snippet / position-zero shape** — question → concise, direct answer.
- **Value-forward CTAs** — prefer "Start your 14-day trial", "Get the size guide" over a bare "Buy now" where natural.
- **Objection handling** — proactively answer the top pre-purchase concerns (sizing, compatibility, durability, "will this work for X").
- **Decision-fit mapping** — where a real situational choice exists, give a condition → option treatment ("if X, choose A; if Y, choose B").
- **Statistics with sources** — support claims with specific data and cite the source where one genuinely exists; never fabricate.
- **Actionable, outcome-specific headlines** — "…in 30 days (with examples)" over "…Tips".
- **Lists for scanning · consistent terminology · truthful power words · concrete examples · active voice.**

## Part C — PDP CRO + SEO elements (structure & commerce)

**1. Above-the-fold** — MUST: title, price, primary image, visible primary CTA in the first viewport (desktop + mobile); stock/availability near the CTA. SHOULD: a trust signal above the fold (review stars + count / "X sold" / guarantee); primary CTA visually dominant. MAY: a secondary CTA that never competes visually.

**2. Title & identifier** — MUST: human-readable first, keyword-informed second, front-loaded entity; unique H1 per product. SHOULD: distinguishing attributes (size, material, model) where they drive intent.

**3. Description & benefit architecture** — MUST: lead with benefits, specs in a secondary block/table; scannable formatting (short paragraphs, feature/benefit lists). SHOULD: real H2/H3 subheads in buyer language; answer the top 3–5 objections. MAY: a short brand story below the functional content.

**4. Imagery & media** — MUST: 3–5+ images (hero, angles, in-context, scale); unique descriptive alt text per image. SHOULD: zoom, video where feasible, compressed responsive images (Core Web Vitals).

**5. Social proof & trust** — MUST: review/rating summary near title/price; Review/AggregateRating structured data. SHOULD: sample review text; UGC where available. MAY: trust badges near the CTA.

**6. Pricing & offer clarity** — MUST: unambiguous price (discount as strikethrough-original + sale); shipping cost/timeline + return policy on-page or one click away. SHOULD: financing/installments if offered. SHOULD NOT: fake/unverifiable urgency or scarcity.

**7. CTAs & micro-conversions** — MUST: Add-to-Cart one click from the PDP for simple variants. SHOULD: sticky mobile Add-to-Cart; a low-commitment secondary action (wishlist, notify-in-stock, size guide). MAY: live chat / click-to-question for high-consideration products.

**8. SEO technical** — MUST: clean descriptive URL slug; unique meta title + description per product; Product + Review/AggregateRating schema. SHOULD: category → subcategory → product internal linking + contextual cross-links; canonicalize variant/parameter URLs; optimize Core Web Vitals.

**9. FAQ / objection block** — SHOULD: product-specific FAQ (sizing, compatibility, care, warranty) in real buyer language, eligible for FAQ schema. MAY: pull real questions from reviews/support tickets.

**10. Cross-sell / related** — SHOULD: related products below the fold. SHOULD NOT: cross-sells above the fold or above the primary CTA.

---

## Quick audit checklist

- [ ] Direct Definition ("X is Y + benefit") as the first sentence under the H1
- [ ] No conversational filler anywhere
- [ ] Every H2/H3 = main entity + a fact (no bare "Features"; no EMQ in subheads)
- [ ] Primary search phrase appears verbatim exactly once, in body text
- [ ] Key claims are standalone, liftable sentences
- [ ] A scannable list high on the page (list-top)
- [ ] ≥1 fact-model table; final cell is a number/noun-entity (no dangling adjectives)
- [ ] Pro/positive tone throughout
- [ ] ≤15 bold tags (target ~7)
- [ ] Title/price/image/CTA above the fold; stock near CTA; review stars near title
- [ ] Benefit-led copy above spec tables; top objections answered
- [ ] FAQ block (4–7 Q&A, answer-first)
- [ ] Product + Review schema; unique meta title/description; clean slug
- [ ] Cross-sells below fold only

## Common anti-patterns (flag on audit)

- Bare topic-word headings ("Features", "Meaning") or the EMQ used verbatim as a subheading
- Conversational warm-up before the substantive answer
- Tables ending in dangling adjectives ("High", "Best") instead of verifiable facts
- Over-bolding (> 15 `<strong>` tags)
- Keyword-stuffed titles; duplicate meta across variants; reviews present but unschemaed
- Specs-only description with no benefit framing; fake urgency; shipping revealed only at checkout
