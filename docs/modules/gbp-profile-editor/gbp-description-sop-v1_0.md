# GBP Business Description SOP (v1.0)

The agency standard for **writing and auditing** a client's Google Business
Profile "from the business" description. This is the source of truth the GBP
Profile Editor implements — both when it **rewrites/AI-drafts** a description and
when it **audits** one.

## Where this is enforced in code

| SOP concern | Code |
|---|---|
| Rewrite / AI draft follows the SOP architecture + rules | `services/gbp_profile_service.py::_DESC_SYSTEM` (draft system prompt) |
| Drafted output is corrected against the SOP trip-wires | `services/gbp_profile_service.py::_content_violations` (feeds the corrective rewrite loop) |
| Audit flags a present-but-weak description | `services/gbp_audit.py::audit` → `description_quality.issues` |
| SOP trip-wire detectors (pure) | `services/gbp_audit.py`: `find_superlatives`, `find_marketing_filler`, `has_generic_opening`, `overused_terms` |
| Inline editor advisories while composing | `services/gbp_profile_api.py::lint_description` |
| Audit recommendations / Action Plan / strategist hints | `services/gbp_profile_audit.py::_recommendations`, `services/reopt_planner.py` (`_dq_hint`), `services/strategy_digest.py` |

`description_quality.issues` keys: `too_short`, `missing_service_keyword`,
`missing_location`, `keyword_stuffed`, `promotional_superlatives`,
`marketing_filler`, `generic_opening`. Every check is **best-effort and
high-precision** — it fires only when its input exists (e.g. the location checks
need captured location terms) so a naturally-written description is never
false-flagged. The verdict is deterministic; the LLM only phrases the rewrite.

---

## Purpose

A GBP description should give customers and Google a clear, accurate
understanding of what the business is, what it does, where it operates, who it
serves, and what differentiates it. The goal is **not** to stuff keywords — it is
a compact, natural-language representation of the business entity. It should read
well both to a prospective customer and to a search engine / language model.

## Recommended architecture (adapt to the facts)

1. **Business + category + primary geography** in the first sentence —
   `<Name> is a <category> serving <city> and <broader area>.` Never open with
   fluff ("Welcome to…", "Looking for…").
2. **Core services** — prioritize the most important; build natural topical
   breadth (roof repair, roof replacement, leak detection, inspections) rather
   than repeating one phrase.
3. **One meaningful, factual differentiator** — years in business, specialization,
   licensing, family/local ownership, residential vs commercial.
4. **Customer use cases / who is served** — connect a service to a real situation
   ("from emergency repairs to full replacements") and name the audience
   (homeowners, businesses, property managers) when it applies.
5. **Geographic reinforcement** — a few important nearby areas, never a long list.

## Hard rules

- Under 750 characters; 3–5 plain, natural sentences.
- Ground everything in real facts. **Never invent** services, awards, years in
  business, certifications, licenses, warranties, guarantees, review counts, or
  customer numbers.
- **No keyword stuffing** — establish the city and each service once; don't repeat
  the city name or an exact-match `<service> <city>` phrase.
- **No long city lists** and **no exhaustive service lists** (the rest of the
  profile and the website carry the detail).
- **No generic marketing filler** ("customer satisfaction is our #1 priority",
  "we pride ourselves", "we go above and beyond", "treat you like family") —
  replace with a specific fact.
- No promotional superlatives (best / #1 / top-rated / guaranteed), no ALL-CAPS,
  no emoji, no exclamation-heavy copy.
- **No URLs and no phone numbers** (both get the description rejected by Google).
- No medical, legal, or other regulated claims.
- Match the client's brand voice when one is on file.
- It should sound natural read aloud to a customer — not like SEO copy.

## Think in entities and relationships

Rather than "how many times should we put `<city> <service>` in?", model the
description as the set of true relationships to convey: the business **is a**
`<category>`, **serves** `<city>` / `<region>`, **provides** `<service A>` /
`<service B>`, **works on** `<materials>`, **serves** `<audiences>`. Convey them
comprehensively, accurately, and naturally.

## Ranking caveat

Google understanding the description does not, by itself, prove description
content moves Maps rankings. Optimize primarily for business clarity, service
relevance, geographic clarity, semantic completeness, customer comprehension,
conversion, and accuracy — treat any direct ranking effect as an open empirical
question, not an assumed fact. (This is why the GBP module card frames the
description as an AI-visibility factor, not a local-pack ranking factor.)

---

*Adapted from the SED Society GBP Description guide provided by the owner
(2026-09-09).*
