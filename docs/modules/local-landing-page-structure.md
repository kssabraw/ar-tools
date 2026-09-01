# Local Landing Page — Structure Guidelines

The page structure the AR Tools Local SEO writer (`writer/nlp-api`) produces for a
**local service / landing page**. The page is emitted as a single `<article>` of
numbered sections, followed by a JSON-LD `<script>` block, followed by two
deterministic blocks — **Contact & Find-Us** and **Trust & Proof** — and a
**Content Gaps** report.

- **Section length:** keep each section ≤ 300 words (split into more H2s rather than lengthening one).
- **Answer-first:** open every section, paragraph, and FAQ answer with a direct claim.
- **Factual accuracy:** only assert facts present in the business data — never invent phone, address, hours, response times, certifications, pricing, or services not offered.

---

## Title tag

```
[Power Word]! [Exact-Match Keyword] | [Brand Name] | [Justification w/ entities] | [Persuasion + entities]
```

Power word (Trusted / Fast / Licensed…), the primary keyword verbatim, the brand, and 1–2 Google entities that validate the claim. Prioritise keyword + entity coverage over brevity.

---

## The sections

| # | Section | Length | Must contain |
|---|---------|--------|--------------|
| 1 | **Intro / Direct Answer** | 100–150w | `<h1>` = keyword + 1–2 service/credential entities; brand + service + city + differentiator; **phone number (above the fold)**; city + ≥1 neighborhood; years in business, if in business data (e.g. "since 1998"). Split into short paragraphs. |
| 2 | **USP / Value Proposition** | 150–200w | First `<h2>` = full sentence naming the service + outcome + 1–2 entities (no city, no verbatim keyword stuffing); ≥3 differentiators with mechanisms, 1 contrast, 1 proof signal. |
| 3 | **Special Offers** | — | *Omit entirely if no offer data.* |
| 4 | **CTA — Primary (value/offer-led)** | 50–75w | Service-anchored action heading; lead with the core value/offer or a free quote; include phone. Not "Contact us today". |
| 5 | **Features & Benefits** | 150–200w | Benefit-focused `<h2>` + `<ul>` of ≥4 outcome-first feature/benefit pairs addressing ICP pain points; if per-line-item pricing is in business data, work it into the relevant benefit line (e.g. "Drain cleaning — from $129") rather than a separate price list — never invent or round a figure that isn't stated. |
| 6 | **Main Service Body** | 800–1400w (or to length budget) | Multiple `<h2>`s (each ≤300w) built off competitor SERP headings + information gain; `<h3>`s for sub-services; answer-first; competitor 4-word phrases woven in verbatim. City stays out of these headings. If the service supports a symptom-diagnosis or DIY-vs-professional angle, one `<h2>` may present it as a comparison table (symptom → likely cause → DIY-safe? → call a pro?); table content counts against this section's existing word budget, it is not additive. |
| 7 | **Testimonials** | — | *Only if reviews provided.* Verbatim reviews (first name + last initial, stars, date, text). |
| 8 | **CTA — Secondary (proof/risk-reversal)** | 50–75w | Distinct angle from §4 — guarantee/warranty, licensing/insurance, or reviews callback (only if in business data); include phone. If a guarantee/warranty is used, state its specific terms when present in business data ("2-year parts & labor," not just "guaranteed") — a vague claim is a weaker proof signal than a specific one and risks reading as unverifiable. |
| 9 | **Getting Started** | 150–200w | Process `<h2>` + `<ol>` of 3–5 steps, closing with a CTA. If the business offers distinct service tiers/packages, the process may present them as a comparison table (tier → what's included → price, if stated); table content counts against this section's existing word budget, it is not additive. |
| 10 | **Geographic / Local SEO + NAP** | 200–300w | City + ≥3 neighborhoods (in sentences) + ≥1 landmark + ≥2 streets + ≥3 ZIP codes (real/verifiable only); coverage area. **NAP required:** state business Name, full Address, and Phone verbatim (a "Find us / Visit us" line). Response time only if in business data. License number, if in business data. |
| 11 | *(removed)* | — | No third CTA block — exactly two CTAs (§4, §8). |
| 12 | **FAQ** | 4–7 entries, 40–80w each | Answer-first; ≥2 proximity FAQs ("Do you serve X?" / "How quickly can you respond?"); cover coverage area, process, what to expect, pricing/emergency (only if stated). |
| 13 | **Schema (JSON-LD)** | after `</article>` | One `<script type="application/ld+json">` with 3 blocks: **Organization**, **Service**, **FAQPage**. (Use `Organization`, not `LocalBusiness`.) |

---

## Contact & Find-Us block (deterministic — injected, not written by the model)

Appended to the page automatically after generation so these are always exact and
never hallucinated. The model must **not** hand-write them (it would duplicate).

- **NAP** — canonical Name / Address / Phone (phone as a `tel:` link). *(Required)*
- **GBP map embed** — address-keyed Google Maps `<iframe>`. *(Required)*
- **Driving directions** — Google Maps directions deep link. *(Highly recommended; rendered when an address is available)*
- **Form fill** — a contact form (Name / Phone / Email / message → "Request a Quote"). *(Highly recommended)*

Graceful degradation: no address → the map embed + directions are omitted, NAP + form still render.

---

## Trust & Proof block (deterministic — injected, not written by the model)

A second injected block, sibling to Contact & Find-Us. Everything here is a
business-supplied asset or an objectively true-or-false fact (a badge either
exists or doesn't; a rating is either 4.9 or it isn't; a photo either exists or
doesn't) — the same category of thing as NAP, so it follows the same
deterministic-injection rule and the same reason: a model asked to describe a
BBB badge or a photo in prose ("we're BBB accredited!") risks asserting it
without it actually rendering, or duplicating it once it does. Narrative trust
elements that require synthesis rather than insertion — guarantee framing, the
DIY/symptom comparison, tier tables — stay model-written; see §6, §8, §9.

- **Trust badge strip** — BBB, Google Guaranteed, Angi/HomeAdvisor, trade
  association seals. Injected as logo images, sourced from a
  `certifications`/`affiliations` field in business data. *(Rendered when populated)*
- **Aggregate rating badge** — the GBP rating/review-count, sourced the same way
  the suite already captures it (Outscraper/DataForSEO GBP enrichment) —
  **never model-estimated**, same rule as NAP. *(Rendered when GBP rating data
  is available)*
- **Financing partner logos** — rendered when `financing_partners` is populated.
- **Media gallery** — team/owner photo, branded vehicle, before/after, video
  embed. Literal file assets, keyed off an `assets` field — they can't be
  "written," only inserted. *(Rendered per available asset)*

Graceful degradation: any of the four rendered independently — a missing field
omits only that element, never a placeholder or an invented substitute.

---

## Cross-cutting requirements

- **Phone number** in §1 (above the fold), repeated in the CTA blocks.
- **Geo signals** across ≥3 sections (§1, §6, §10, §12) — not bunched into §10.
- **Entity triplets** [Brand] + [service] + [city] co-occurring in ≥3 sections (intro, service body, local, FAQ).
- **ICP-matched CTA tone** (emergency / commercial / budget / general) repeated across the CTA blocks.
- **AEO structure** (one idea per paragraph, question-format H3s, lists for features/steps, tables only when genuinely comparative) governs layout; **brand voice** governs word choice within it.
- **Trust-signal consistency** — badges, rating, license, and guarantee must be consistent with what's stated on the business's GBP/website; no page-specific embellishment. Prevents city-page drift where one location page claims a guarantee (or a badge, or a license) another doesn't have.

## Content Gaps report

A structured list of facts the writer *wanted* on the page (they'd improve the
SEO/AEO score or conversions) but **couldn't** include because they weren't in the
business data — paired with why each matters and how to supply it.

**Why it exists:** the generator has a hard factual-accuracy rule — it must never
invent a phone number, address, response time, certification, price, or a service
the business doesn't offer. So when a high-value fact is missing, instead of
fabricating it or silently dropping it, the writer records it as a gap.

**Where it comes from:** the model emits it after the JSON-LD, wrapped in
`CONTENT_GAPS_REPORT_START` / `CONTENT_GAPS_REPORT_END` markers. The generator
parses it into the response's `content_gaps` array, platform-api persists it, and
the UI shows it as a "How to reach 100/100" panel. It is **not** rendered on the page.

**Shape** — each gap is an object:

```json
{
  "category": "Response Time",
  "missing": "Specific arrival window (e.g. 'within 2 hours')",
  "score_impact": "high",
  "why_important": "The nearme_intent scoring engine rewards explicit timeframes; without one the page can't score 90+.",
  "how_to_add": "Add your typical response time to your website (home/about/services), then regenerate the page."
}
```

**Always checked** (the common sub-90 culprits):

1. **Response time** — a specific arrival/response window (high impact).
2. **Service area / neighborhoods** — explicit coverage areas (medium).
3. **Certifications / licences** — when the GBP category implies them (plumber,
   electrician, HVAC, contractor) but none were stated (medium). Never assumed from
   the category alone — they're a trust signal that must be verifiable.
4. **Years in business / founding date** — e.g. "since 1998" (medium).
5. **License number** — the specific verifiable number, distinct from the
   certification/licensing claim above (medium).
6. **Guarantee/warranty terms** — the specific terms behind a guarantee/warranty
   claim, e.g. "2-year parts & labor" (high — a vague guarantee is a weak proof
   signal).
7. **Pricing / price range** — per-service or starting-from pricing (medium).
8. **Comparison-table source data** — tier/package pricing for §9, or a
   documented DIY-vs-professional baseline for §6 (medium).
9. **Trust badges / affiliations** — BBB, Google Guaranteed, Angi/HomeAdvisor,
   trade association seals, financing partners (medium).
10. **Photo/video assets** — team/owner photo, branded vehicle, before/after,
    video embed for the Trust & Proof media gallery (low–medium).

**Not the same as `deficiencies`:** the response also carries per-engine
`deficiencies` — scoring-rubric misses in the *generated copy*, fixable by a
rewrite. Content gaps are missing *business facts* that no rewrite can conjure; they
need the team to add the fact to the client's GBP/website, then regenerate.
