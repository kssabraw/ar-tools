# Local Landing Page — Structure Guidelines

The page structure the AR Tools Local SEO writer (`writer/nlp-api`) produces for a
**local service / landing page**. The page is emitted as a single `<article>` of
numbered sections, followed by a JSON-LD `<script>` block, followed by a
deterministic **Contact & Find-Us** block and a **Content Gaps** report.

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
| 1 | **Intro / Direct Answer** | 100–150w | `<h1>` = keyword + 1–2 service/credential entities; brand + service + city + differentiator; **phone number (above the fold)**; city + ≥1 neighborhood. Split into short paragraphs. |
| 2 | **USP / Value Proposition** | 150–200w | First `<h2>` = full sentence naming the service + outcome + 1–2 entities (no city, no verbatim keyword stuffing); ≥3 differentiators with mechanisms, 1 contrast, 1 proof signal. |
| 3 | **Special Offers** | — | *Omit entirely if no offer data.* |
| 4 | **CTA — Primary (value/offer-led)** | 50–75w | Service-anchored action heading; lead with the core value/offer or a free quote; include phone. Not "Contact us today". |
| 5 | **Features & Benefits** | 150–200w | Benefit-focused `<h2>` + `<ul>` of ≥4 outcome-first feature/benefit pairs addressing ICP pain points. |
| 6 | **Main Service Body** | 800–1400w (or to length budget) | Multiple `<h2>`s (each ≤300w) built off competitor SERP headings + information gain; `<h3>`s for sub-services; answer-first; competitor 4-word phrases woven in verbatim. City stays out of these headings. |
| 7 | **Testimonials** | — | *Only if reviews provided.* Verbatim reviews (first name + last initial, stars, date, text). |
| 8 | **CTA — Secondary (proof/risk-reversal)** | 50–75w | Distinct angle from §4 — guarantee/warranty, licensing/insurance, or reviews callback (only if in business data); include phone. |
| 9 | **Getting Started** | 150–200w | Process `<h2>` + `<ol>` of 3–5 steps, closing with a CTA. |
| 10 | **Geographic / Local SEO + NAP** | 200–300w | City + ≥3 neighborhoods (in sentences) + ≥1 landmark + ≥2 streets + ≥3 ZIP codes (real/verifiable only); coverage area. **NAP required:** state business Name, full Address, and Phone verbatim (a "Find us / Visit us" line). Response time only if in business data. |
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

## Cross-cutting requirements

- **Phone number** in §1 (above the fold), repeated in the CTA blocks.
- **Geo signals** across ≥3 sections (§1, §6, §10, §12) — not bunched into §10.
- **Entity triplets** [Brand] + [service] + [city] co-occurring in ≥3 sections (intro, service body, local, FAQ).
- **ICP-matched CTA tone** (emergency / commercial / budget / general) repeated across the CTA blocks.
- **AEO structure** (one idea per paragraph, question-format H3s, lists for features/steps, tables only when genuinely comparative) governs layout; **brand voice** governs word choice within it.

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

**Not the same as `deficiencies`:** the response also carries per-engine
`deficiencies` — scoring-rubric misses in the *generated copy*, fixable by a
rewrite. Content gaps are missing *business facts* that no rewrite can conjure; they
need the team to add the fact to the client's GBP/website, then regenerate.
