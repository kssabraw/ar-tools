# GBP Business Description SOP

Owns: how to **write and audit** a client's Google Business Profile "from the
business" description. Defers to `_ORCHESTRATOR.md` for global rules and decision
ownership; where this leaf conflicts with `_ORCHESTRATOR.md` §2, §2 wins.

Scope: the free-text GBP description only. GBP categories, services, hours,
reviews, and Maps ranking tactics are covered by
`How_To_Rank_In_Google_Maps_SOP.md`.

## Principle

A GBP description is a **compact, natural-language representation of the business
entity** — not a place to insert keywords. A strong description establishes, in
order: **who** the business is → **what** it does → **where** it operates → **who**
it serves → **what** makes it different. Do that comprehensively, accurately, and
naturally, and it reads well both to a prospective customer and to a search
engine / language model.

## Recommended architecture (adapt to the facts; not every sentence is mandatory)

1. **Business + category + primary geography — first sentence.**
   `<Name> is a <category> serving <city> and <broader area>.` Establish what the
   business is and where it operates immediately. Never open with fluff
   ("Welcome to…", "Looking for a company you can trust?").
2. **Core services.** Prioritize the most important, revenue-driving services and
   use the real terms for the work. Build natural **topical breadth** (roof
   repair, roof replacement, leak detection, inspections, tile / shingle / flat
   roofing) rather than repeating one phrase. Do not turn it into a full service
   catalog — the Services section and the website carry the rest.
3. **One meaningful, factual differentiator.** Years in business, specialization,
   licensing, family / local ownership, residential vs commercial, warranties,
   emergency availability — **only if it is a real, supportable fact.**
4. **Customer use cases / audience.** Optionally connect a service to a real
   situation ("from emergency repairs to full replacements…") and name who is
   served (homeowners, businesses, property managers) when it genuinely applies.
5. **Geographic reinforcement.** Optionally name a **few** important nearby
   markets — never a long city list.

## Hard rules

- Under 750 characters; 3–5 plain, natural sentences.
- **Ground everything in real facts. Never invent** services, awards, years in
  business, certifications, licenses, warranties, guarantees, review counts, or
  customer numbers. Every factual claim must be verifiable.
- **No keyword stuffing.** Establish the city and each service **once**; do not
  repeat the city name or an exact-match `<service> <city>` phrase. Natural
  breadth (several distinct services that happen to share a word) is good;
  repetition of the same phrase is not.
- **No long city lists** and **no exhaustive service lists.**
- **No generic marketing filler** ("customer satisfaction is our #1 priority",
  "we pride ourselves on quality", "we go above and beyond", "we treat you like
  family"). Replace every generic claim with a specific fact.
- **No promotional superlatives** (best / #1 / top-rated / guaranteed), no
  ALL-CAPS, no emoji, no exclamation-heavy copy.
- **No URLs and no phone numbers** — both get the description rejected by Google.
- No medical, legal, or other regulated claims.
- Match the client's brand voice when one is on file.
- **Read it aloud test:** if it sounds like SEO copy rather than a description of
  a real business, rewrite it.

## Audit checklist (score a live description against this)

- **Business clarity:** the category is obvious and the first sentence says what
  the business is.
- **Service coverage:** primary and specialty services represented with real
  breadth; no needless repetition.
- **Geographic relevance:** primary market clear; a few important secondary areas;
  no city-list stuffing.
- **Differentiation:** at least one meaningful, factual reason to choose it.
- **Customer relevance:** customer type / use cases addressed when it matters.
- **Writing quality:** natural read-aloud; no filler, no superlatives, no
  keyword/city repetition, no fluff opening.
- **Accuracy:** every claim, service, location, and credential is verifiable.

## Think in entities and relationships

Model the description as the true relationships to convey — the business **is a**
`<category>`, **serves** `<city>` / `<region>`, **provides** `<service A/B/C>`,
**works on** `<materials>`, **serves** `<audiences>` — rather than asking "how many
times should I put `<city> <service>` in?". Convey those relationships
comprehensively and naturally.

## Ranking caveat

Google being able to read the description does not, by itself, prove description
content moves Maps rankings. Optimize primarily for business clarity, service
relevance, geographic clarity, semantic completeness, customer comprehension,
conversion, and accuracy — treat any direct local-pack ranking effect as an open
empirical question, not an assumed fact. (In suite terms: the GBP description is
an AI-visibility factor, not a confirmed local-pack ranking factor — see the
geogrid module card.)

## Where the suite enforces this

The GBP Profile Editor implements this SOP both when it AI-drafts a description
and when it audits one; the deterministic `description_quality` audit surfaces
`too_short` / `missing_service_keyword` / `missing_location` / `keyword_stuffed` /
`promotional_superlatives` / `marketing_filler` / `generic_opening`. The
concern→code map lives in
`docs/modules/gbp-profile-editor/gbp-description-sop-v1_0.md`.
