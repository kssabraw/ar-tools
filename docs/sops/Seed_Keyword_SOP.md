# Seed Keyword SOP

**Current as of:** 03 July 2026
**Goal:** Produce the cleaned, deduplicated list of services and sub-services (the seed keywords) that defines a client's topical footprint.
**Who this is for:** All clients, at onboarding; revisit when the client's services change.
**Assigned to:** **Kyle Sabraw** (seed selection defines the entity vector — senior-owned).
**Scope:** Seeds only. **Fanout and clustering are owned by the writing apps** (Topic Fanout, brief generators, local SEO writer) — this SOP feeds them.

> **Position in the onboarding chain:** Seed Keyword SOP → Site Planning Algorithm (Architecture SOP — the cleaned service list is its required input) → Topic Fanout (blog calendar) + local SEO writer (service/location content). This SOP is step one of onboarding; its output defines the client's entire topical footprint.

---

## 1. Gather seed sources

Collect candidates from, in order:

1. **Client's service list** from intake — each service and sub-service is a seed.
2. **GBP categories** (primary + secondary) — per the GBP↔site mirror rule (Maps SOP §Site Theming), each category implies seeds.
3. **Competitor services** — what category-peer GBPs/sites rank for that the client doesn't list (the vector test run in reverse: if peers rank for it, it's a candidate service).
4. **DataForSEO expansion** from the above.
5. **Client interview** — differentiators, money services, "what do you want the phone to ring for."

## 2. Fan out with Opus

Feed the gathered list to **Opus 4.8** to fan out **highly related sub-services** for each service. Then **clean and dedup** the combined list to produce the complete set of services and sub-services.

## 3. Qualify each seed

A seed enters the apps only if it passes:

- **On-vector** — the vector test (Maps SOP Part 1): category-peer GBPs rank for it.
- **Commercial intent** for money-page seeds — no informational seeds as money targets (the informational-vs-commercial mismatch flagged in the entity audit).
- **No volume floor** — any on-vector, commercial service keyword is a valid seed regardless of search volume.

## 4. Hand off

- The cleaned services/sub-services list → the **Site Planning Algorithm** (Architecture SOP) as its services input.
- Seed keywords → **Topic Fanout** to build the silo and the **blog creation calendar**.
- Each **seed keyword + location** pair → the **local SEO writer** to produce the content. The local SEO writer creates its own fanout of sub-services within each piece.
