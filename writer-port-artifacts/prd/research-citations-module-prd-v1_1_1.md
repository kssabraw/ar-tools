# PRD: Research & Citations Module

**Version:** 1.1
**Status:** Draft
**Last Updated:** April 29, 2026
**Part of:** [Parent Content Creation Platform — TBD name]
**Upstream Dependency:** Content Brief Generator Module (v1.7+)
**Downstream Dependency:** Content Writer Module

---

## 1. Problem Statement

AI-generated content is prone to hallucinated statistics, fabricated studies, and unverified claims. Even when a content brief provides a strong structural foundation, the Content Writer Module has no mechanism to ground factual assertions in real, verifiable sources — leaving both readers and site owners exposed to credibility risk. This module sits between the Content Brief Generator and the Content Writer to solve that problem: for every content section, it discovers authoritative real-world sources, extracts specific quotable claims and data points, **verifies each claim against the source text before accepting it**, and maps the verified claims back to the heading structure. The Writer Module receives a citations-enriched brief where every factual assertion has a real, verified source attached before a single word is written.

---

## 2. Goals

- Accept the full content brief JSON output from the Content Brief Generator and return a citations-enriched version
- Map at least one authoritative citation to every content H2 (excluding conclusion and FAQ sections)
- Provide dedicated citations for the highest-priority authority gap H3s (up to 3 per article) — these sections carry the highest novel-claim risk
- Extract specific quotable claims and data points from each source — and verify each claim appears in the source text before accepting it
- Tier sources by authority (government/academic > major publications > general web)
- Exclude competitor SERP URLs from citation candidates
- Prevent hallucinated claims in downstream content by providing the Writer Module with verified, source-anchored data points for every section
- Enable inline hyperlink references in the final article by including full publication metadata alongside each citation

### Out of Scope (v1)

- Citation formatting for style guides (APA, MLA, Chicago) — downstream Writer Module responsibility
- Inline link placement decisions within prose — Writer Module responsibility
- Citation monitoring or link rot detection post-publish
- Paywalled content access
- Non-English sources — English-only in v1
- Multi-locale support — English / United States only
- User-facing citation management UI
- Academic database API integrations (PubMed, CrossRef) — web search only in v1

---

## 3. Success Metrics

Success in v1 is defined by structural validity, claim verification rates, and operational discipline. All metrics are measurable from the module's own output and logs.

| Metric | Target |
|---|---|
| Output validates against JSON schema | 100% |
| Every content H2 has ≥1 citation | 100% |
| 100% of accepted claims pass verification against source text | 100% |
| Minimum 1 Tier 1 or Tier 2 citation per article | 100% |
| All returned citations are accessible (non-paywalled, non-404, non-bot-blocked) at time of generation | ≥90% |
| End-to-end generation completes within 120s | ≥95% |
| Cost per article stays under $0.50 | ≥95% |

---

## 4. System Architecture Overview

```
[Content Brief JSON (from Brief Generator)]
      │
      ▼
┌─────────────────────┐
│  Step 0: Input      │  ◄── Validate incoming brief against schema
│  Validation         │  ◄── Extract content H2s, top 3 authority gap H3s,
│                     │      and competitor domains
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 1: Research   │  ◄── LLM generates 2–3 search queries per H2
│  Query Generation   │      and per selected authority gap H3
│  (Parallel)         │  ◄── Queries target statistics, studies, data
└─────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: Source Discovery (Parallel per heading)             │
│  ◄── DataForSEO Web Search                                  │
│  ◄── Top 5 results per query, deduped per heading           │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 3: Source     │  ◄── Apply tier classification (1–3)
│  Filtering &        │  ◄── Exclude competitor domains
│  Tiering            │  ◄── Apply recency rules; hard exclude >5 years
│                     │  ◄── Exclude sources with no detectable date
└─────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4: Content Fetching (Parallel per candidate)           │
│  ◄── Scrape HTML / Extract text from PDFs                   │
│  ◄── Detect paywalls, bot-block challenges, non-English     │
│  ◄── Top 3 accessible candidates per heading proceed        │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 5: Winner     │  ◄── Pre-LLM ranking by tier + recency
│  Selection &        │      + meta snippet relevance
│  Verified Claim     │  ◄── LLM extracts claims from winner only
│  Extraction         │  ◄── Verify each claim against source text
│                     │  ◄── Fall back to next candidate on failure
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 6: Citation   │  ◄── Final score (tier + recency + max claim relevance)
│  Scoring &          │  ◄── Threshold 0.45; flag below
│  Finalization       │  ◄── Flag shared citations
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 7: Supple-    │  ◄── Add up to 4 article-level citations
│  mental Citations   │      to enrich the citation pool
│                     │  ◄── No minimum requirement; accept what's available
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Step 8: Output     │  ◄── citation_ids on all heading items
│  Assembly           │  ◄── Build citations array (heading + authority_gap + article)
│                     │  ◄── Extend metadata with citations_metadata block
└─────────────────────┘
      │
      ▼
[Citations-Enriched Brief JSON → Content Writer Module]
```

---

## 5. Functional Requirements

### Step 0 — Input Validation

| Rule | Action |
|---|---|
| Input is not valid JSON | Reject with structured error |
| Input does not conform to content brief schema v1.7+ | Reject with structured error |
| `heading_structure` is empty or missing | Reject with structured error |
| `heading_structure` contains 0 content H2s | Reject with structured error |
| `metadata.competitor_domains` is missing | Proceed without exclusion list; flag `competitor_exclusion_unavailable: true` |

**Content H2 extraction rules:**

From `heading_structure`, extract all items where `level: "H2"` AND `type: "content"`. Explicitly exclude items typed `faq-header`, `faq-question`, or `conclusion`, and any H2 with text matching "Frequently Asked Questions".

**Authority gap H3 selection rules:**

From `heading_structure`, extract all items where `level: "H3"` AND `source: "authority_gap_sme"`. If more than 3 such items exist, select the top 3 by `heading_priority`. These selected H3s become independent citation targets — they receive dedicated citations in addition to inheriting the parent H2's citation.

**Upstream schema dependency:**

This module requires `metadata.competitor_domains` in the Brief Generator output (see Section 12).

---

### Step 1 — Research Query Generation

**Method:** Single LLM call per citation target (each content H2 and each selected authority gap H3), all calls run in parallel

**Inputs per call:**
- Seed keyword (`brief.keyword`)
- Heading text (H2 or authority gap H3)
- Intent type (`brief.intent_type`)
- For H2 calls only: any non-authority-gap H3 heading texts nested under this H2 (for additional context)
- For authority gap H3 calls only: parent H2 text (for context)

**LLM prompt template (H2 variant):**

```
You are a research assistant helping find authoritative citations for a blog post section.

Keyword: {keyword}
Section heading: {h2_text}
Supporting subheadings: {h3_texts_or_none}
Content intent: {intent_type}

Generate 2–3 search queries specifically designed to find:
- Statistics, data points, or quantified research findings relevant to this section
- Official government guidance, regulatory information, or peer-reviewed studies
- Credible expert analysis, industry data, or named institutional reports

Return a JSON array of query strings only. Queries must be specific and factual in nature, designed to surface authoritative sources rather than opinion pieces or competitor blog posts. Do not include the domain name of any specific site in the queries.
```

**LLM prompt template (authority gap H3 variant):**

```
You are a research assistant helping find authoritative citations for a specific informational gap in a blog post.

Keyword: {keyword}
Parent section: {h2_text}
Specific subheading addressing an information gap: {h3_text}
Content intent: {intent_type}

This subheading was identified as missing from competing content — it represents a specific informational gap that needs strong, verified sources.

Generate 2–3 search queries specifically designed to find:
- Statistics or data points directly relevant to this specific subtopic
- Authoritative sources (government, academic, regulatory) addressing this exact angle
- Expert analysis or research findings on this niche aspect

Return a JSON array of query strings only.
```

**Output:** 2–3 search query strings per citation target

**Per-call timeout:** 25 seconds. On timeout, retry once. On second timeout, fall back to a generic query: `"{keyword}" "{heading_text}" statistics OR study OR report`.

---

### Step 2 — Source Discovery

**Provider:** DataForSEO Web Search API (Standard Queue)
**Locale:** English / United States

**Process per citation target:**
1. Execute all 2–3 queries generated in Step 1
2. Collect top 5 organic results per query
3. Deduplicate URLs across queries for the same target (retain highest position)
4. Up to 15 unique candidate URLs per target

**Execution:** All search batches run in parallel

**Captured per result:** URL, page title, meta description, root domain

---

### Step 3 — Source Filtering & Tiering

**Competitor domain exclusion:**
Strip any candidate URL whose root domain appears in `metadata.competitor_domains`.

**Tier classification:**

| Tier | Label | Criteria |
|---|---|---|
| Tier 1 | Authoritative | `.gov` domains; `.edu` domains; WHO, CDC, FDA, NIH, NIST, EPA, and recognized international health/regulatory bodies; indexed peer-reviewed academic journals |
| Tier 2 | Credible | Major news organizations (Reuters, AP, BBC, Washington Post, NYT, WSJ); established industry trade publications; recognized research and data firms (Pew, Gartner, McKinsey, Statista, Forrester, IBISWorld) |
| Tier 3 | General | All other HTTPS sources passing basic quality heuristics |
| Excluded | — | Competitor SERP domains; social media platforms (Twitter/X, Facebook, Instagram, TikTok, Reddit); Wikipedia; HTTP-only domains; content farms (blocklist in engineering spec); redirect chains where final destination is unreachable |

**Tier 3 quality heuristics — all must pass:** HTTPS only; final destination resolves; not a content farm; not a social or forum site.

**Recency classification:**

| Label | Age Range | Score |
|---|---|---|
| `fresh` | <1 year | 1.00 |
| `dated` | 1–3 years | 0.65 |
| `stale` | 3–5 years | 0.30 |
| Hard excluded | >5 years | — |

**Recency exception:** Tier 1 sources older than 5 years are permitted only if they represent foundational law, legislation, landmark studies, or established scientific consensus. Flag `recency_exception: true`. Flat score of 0.50.

**Date detection rule:** If a publication or last-updated date cannot be reliably extracted from the source (meta tags, JSON-LD, or body), the source is excluded from the candidate pool. Sources without a verifiable date are not eligible for citation.

**Sort order:** Tier 1 → Tier 2 → Tier 3; within each tier: `fresh` → `dated` → `stale`. Top 5 candidates per target pass to Step 4.

---

### Step 4 — Content Fetching & Extraction

**Provider:** ScrapeOwl (consistent with upstream scraping infrastructure) or equivalent
**Execution:** All fetches run in parallel across all citation targets

**Content type handling:**

| Source Type | Detection | Extraction |
|---|---|---|
| HTML | Default `Content-Type: text/html` | Standard ScrapeOwl scrape; strip nav/footer/sidebar/boilerplate |
| PDF | `Content-Type: application/pdf` OR URL ending `.pdf` | PDF text extractor (pypdf or equivalent); extract body text plus PDF metadata for date/author |
| Other (DOCX, etc.) | Any other content type | Skip; treat as fetch failure |

PDFs are common for Tier 1 sources (government reports, academic papers, regulatory documents). PDF text extraction is required, not optional.

**Extracted per source:**
- Body text (cleaned)
- Canonical title
- Author name (byline, meta tags, JSON-LD, or PDF metadata)
- Publication name (meta, JSON-LD, or masthead)
- Published or last-updated date (meta tags, JSON-LD, body, or PDF metadata — prefer `datePublished`)

**Paywall detection:**
Flag `paywall_detected: true` if any of:
- Login wall or subscription gate in rendered page
- Body content <300 words AND subscription CTA language present
- Page redirects to account/login URL

**Bot-block / challenge detection:**
Flag `bot_block_detected: true` if the response is HTTP 200 OK but the body matches any of:
- Cloudflare challenge markers ("Just a moment...", "Verifying you are human", "Checking your browser")
- CAPTCHA challenge markers ("verify you're not a robot", reCAPTCHA fingerprints)
- Body content <200 words AND challenge-related JavaScript fingerprints present
- Akamai / DataDome / PerimeterX challenge page signatures

Bot-blocked sources are removed from the candidate pool. Treat as fetch failure; move to next candidate.

**Language detection:**
Run a lightweight language detector (e.g., `langdetect` or `cld3`) on the extracted body text. If detected language is not English (`en`), exclude the source. Flag `language_excluded: true` for observability.

**Fetch cap:** Top 3 accessible candidates per citation target proceed to Step 5. "Accessible" means: non-paywalled, non-bot-blocked, English-language, with detectable date.

---

### Step 5 — Winner Selection & Verified Claim Extraction

This step is restructured from v1.0 to extract claims only from the winning candidate, then verify each claim against the source text before accepting it.

**Stage 5a — Pre-LLM winner selection:**

For each citation target, rank the 3 accessible candidates by a pre-LLM score using only metadata available without an LLM call:

```
pre_llm_score = (0.50 × tier_score) + (0.35 × recency_score) + (0.15 × meta_snippet_match)

Where:
  meta_snippet_match = cosine similarity between heading text and meta description (using OpenAI text-embedding-3-small, reusing infrastructure from upstream brief module)
```

The candidate with the highest `pre_llm_score` is the provisional winner.

**Stage 5b — Claim extraction (winner only):**

Run a single LLM claim extraction call on the provisional winner.

**LLM prompt template:**

```
You are extracting specific, quotable factual claims from a source document to support a blog post section.

Blog post keyword: {keyword}
Section heading: {heading_text}

From the source text below, extract up to 5 specific, quotable claims or data points that:
- Are factual and specific (statistics, percentages, named study findings, official regulatory guidance, or direct expert quotes with attribution)
- Directly support the topic of the section heading above
- Are self-contained — understandable without the surrounding paragraph
- Are not editorial opinion, vague generalizations, or unquantified assertions

CRITICAL: Use the source's exact words and exact numbers. Do not paraphrase. Do not round. Do not infer values not stated in the text. If a claim cannot be quoted verbatim, do not include it.

Return a JSON array of objects only, with no preamble or markdown formatting:
[
  {
    "claim_text": "<the exact quoted text from the source — verbatim, including numbers>",
    "relevance_score": <float 0.0–1.0>
  }
]

Source text:
{source_text}
```

Source text is truncated to 6,000 tokens if needed (prioritize first 4,000 tokens).

**Per-call timeout:** 25 seconds. On timeout, treat as extraction failure.

**Stage 5c — Claim verification (deterministic, no LLM cost):**

For each extracted claim, run a verification pass against the full fetched source text:

1. **Verbatim match:** Exact substring match of `claim_text` (case-insensitive, whitespace-normalized) in the source body. Pass.
2. **Fuzzy match:** If verbatim fails, sliding-window fuzzy match using Levenshtein ratio ≥ 0.90 over windows the length of the claim. Pass.
3. **Number integrity check:** Extract all numeric tokens from `claim_text` (digits, percentages, currency values, dates). Every numeric token must appear in the source text exactly. If any numeric token in the claim is not present in the source, the claim **fails verification regardless of fuzzy match score** — number alteration is the most common hallucination pattern.
4. If verification fails: discard the claim. Log `verification_failed: true` with reason.

Only verified claims are retained. Discard any claim with `relevance_score < 0.50` after verification.

**Stage 5d — Fallback handling:**

| Outcome | Action |
|---|---|
| ≥1 verified claim above 0.50 relevance from winner | Accept; proceed to Step 6 |
| 0 verified claims from winner | Move to next candidate (rank 2). Re-run Stages 5b–5c. |
| 0 verified claims from rank 2 candidate | Move to rank 3. Re-run Stages 5b–5c. |
| 0 verified claims from any of top 3 candidates | Use the highest-scoring candidate's title + meta description as a fallback stub claim with `extraction_method: "fallback_stub"`, `relevance_score: 0.30`. Flag `citation_quality_low: true`. |

---

### Step 6 — Citation Scoring & Finalization

**Final scoring formula:**

```
citation_score = (0.40 × tier_score) + (0.30 × recency_score) + (0.30 × max_verified_claim_relevance)

Where:
  tier_score:       Tier 1 = 1.00, Tier 2 = 0.65, Tier 3 = 0.35
  recency_score:    fresh = 1.00, dated = 0.65, stale = 0.30, recency_exception = 0.50
  max_verified_claim_relevance = highest relevance_score among verified claims; if fallback stub, = 0.30
```

**Selection rules:**
- Minimum acceptable `citation_score`: **0.45** (raised from 0.30 in v1.0)
- Below threshold: accept the citation but flag `citation_quality_low: true`

**Deduplication:**
- The same URL may be selected for multiple citation targets — permitted
- When two candidates for the same target have a score difference of ≤0.05, prefer the candidate whose URL has not already been selected elsewhere
- Flag `shared_citation: true` on any URL assigned to more than one target

---

### Step 7 — Supplemental Citations

**Rule:** Supplemental article-level citations may be added to enrich the citation pool. **Maximum of 4 supplemental citations per article.** There is no minimum citation count required — accept whatever the pipeline produces.

**Process:**
1. Generate 2–3 search queries targeting the seed keyword broadly (not tied to a specific heading)
2. Run the full pipeline: search → filter/tier (Step 3) → fetch (Step 4) → winner selection + verified extraction (Step 5) → scoring (Step 6)
3. Add up to 4 selected sources as `scope: "article"` citations
4. Stop when: 4 supplementals added, or no more qualifying candidates exist

Supplemental citations are tagged `heading_order: null` and `scope: "article"` in the output.

---

### Step 8 — Output Assembly

The output is the complete content brief JSON passed through unchanged, with the following additions:

1. **Every** `heading_structure` item gains a `citation_ids` array (empty array `[]` for items with no citations — H1, FAQ items, conclusion, content H3s)
2. A top-level `citations` array is added
3. The `metadata` object is extended with a `citations_metadata` block

No existing fields from the content brief are modified or removed.

---

## 6. Output Schema

```json
{
  "keyword": "string",
  "intent_type": "...",
  "intent_confidence": 0.0,
  "intent_review_required": false,

  "heading_structure": [
    {
      "level": "H1 | H2 | H3",
      "text": "string",
      "type": "content | faq-header | faq-question | conclusion",
      "source": "...",
      "original_source": "string | null",
      "semantic_score": 0.0,
      "exempt": false,
      "serp_frequency": 0,
      "avg_serp_position": 0.0,
      "llm_fanout_consensus": 0,
      "heading_priority": 0.0,
      "order": 0,
      "citation_ids": []
    }
  ],

  "faqs": [ "..." ],
  "structural_constants": { "..." },
  "format_directives": { "..." },
  "discarded_headings": [ "..." ],
  "silo_candidates": [ "..." ],

  "citations": [
    {
      "citation_id": "cit_001",
      "heading_order": 2,
      "heading_text": "string",
      "scope": "heading | authority_gap | article",
      "url": "string",
      "title": "string",
      "author": "string | null",
      "publication": "string | null",
      "published_date": "string | null",
      "tier": 1,
      "recency_label": "fresh | dated | stale",
      "recency_exception": false,
      "pdf_source": false,
      "language_detected": "en",
      "citation_score": 0.0,
      "shared_citation": false,
      "citation_quality_low": false,
      "paywall_detected": false,
      "bot_block_detected": false,
      "claim_extraction_failed": false,
      "claims": [
        {
          "claim_text": "string",
          "relevance_score": 0.0,
          "extraction_method": "verbatim_extraction | fallback_stub",
          "verification_method": "verbatim_match | fuzzy_match | none"
        }
      ]
    }
  ],

  "metadata": {
    "...": "all existing brief metadata fields pass through unchanged",
    "competitor_domains": ["example.com"],

    "citations_metadata": {
      "total_citations": 0,
      "unique_urls": 0,
      "citations_by_scope": {
        "heading": 0,
        "authority_gap": 0,
        "article": 0
      },
      "citations_by_tier": {
        "tier_1": 0,
        "tier_2": 0,
        "tier_3": 0
      },
      "h2s_with_citations": 0,
      "h2s_without_citations": 0,
      "authority_gap_h3s_with_citations": 0,
      "supplemental_citations_added": 0,
      "competitor_exclusion_unavailable": false,
      "citations_schema_version": "1.1"
    }
  }
}
```

**Schema notes:**
- `citation_ids` is now present (as an empty array if applicable) on **every** heading item, eliminating the need for consumers to check field existence
- `scope: "heading"` = mapped to a content H2; `scope: "authority_gap"` = mapped to an authority gap H3; `scope: "article"` = supplemental, no heading mapping
- `extraction_method` distinguishes verbatim LLM extraction from fallback stubs derived from title + meta description — the Writer Module should not treat fallback stubs as basis for specific factual assertions
- `verification_method` records how each claim was verified against source text; `none` only appears for fallback stubs

---

## 7. Failure Mode Handling

| Scenario | Behavior |
|---|---|
| Incoming brief JSON fails schema validation | Abort with structured error |
| `heading_structure` contains 0 content H2s | Abort with structured error |
| Query generation LLM call times out (25s) twice | Fall back to generic query: `"{keyword}" "{heading_text}" statistics OR study OR report` |
| DataForSEO returns 0 results for all queries for a target | Flag `no_sources_found: true`; leave `citation_ids: []` for that heading |
| All candidates for a target are paywalled | Try next-tier candidates; if all fail, leave `citation_ids: []`; flag `all_candidates_paywalled: true` |
| All candidates for a target are bot-blocked | Same as paywalled; flag `all_candidates_bot_blocked: true` |
| All candidates for a target are non-English | Same as above; flag `all_candidates_excluded_by_language: true` |
| All candidates have no detectable date | Same as above; flag `all_candidates_undated: true` |
| PDF extraction fails | Treat as fetch failure; move to next candidate |
| Claim extraction LLM call times out (25s) | Treat as extraction failure; move to next candidate per Stage 5d |
| Claim extraction returns malformed JSON | Retry once with stricter prompt; on second failure, treat as extraction failure |
| All extracted claims fail verification | Treat as extraction failure; move to next candidate |
| All 3 candidates fail (no verified claims) | Use fallback stub from rank-1 title + meta; flag `citation_quality_low: true` |
| No candidate scores above 0.45 | Accept best available; flag `citation_quality_low: true` |
| ScrapeOwl fetch times out | Retry once with backoff; on failure, skip to next candidate |
| End-to-end exceeds 120s | Abort and notify user |
| `metadata.competitor_domains` absent | Continue without exclusion; flag `competitor_exclusion_unavailable: true` |

---

## 8. Performance Targets

**Trigger model:** Synchronous — fires immediately upon receiving the completed content brief JSON.

| Stage | Target | Max |
|---|---|---|
| End-to-end | 60s | 120s |
| Input validation + heading extraction | <1s | 2s |
| Research query generation (parallel) | 5s | 10s |
| Source discovery — DataForSEO searches (parallel) | 10s | 20s |
| Source filtering and tiering | 2s | 5s |
| Content fetching (HTML + PDF, parallel) | 15s | 30s |
| Winner selection + verified claim extraction (parallel per target, sequential within target on retry) | 20s | 40s |
| Citation scoring, supplementals, and output assembly | 5s | 12s |

All citation targets process in parallel. The slowest single target's chain determines stage time. **Per-LLM-call timeout: 25 seconds**, with one retry on timeout for query generation. Claim extraction failures fall through to the next candidate rather than retrying the same call.

---

## 9. Cost Model

| Component | Cost per Article |
|---|---|
| Research query generation (LLM, ~6 H2s + up to 3 authority gap H3s = ~9 calls, parallel) | ~$0.03 |
| DataForSEO Web Search (~24 queries) | ~$0.02–$0.03 |
| Content fetching — ScrapeOwl + PDF (3 candidates × 9 targets = ~27 fetches) | ~$0.05–$0.09 |
| Winner-only claim extraction (~9 calls + ~3 retries) | ~$0.05–$0.10 |
| Supplemental citation pipeline (if added) | ~$0.01–$0.03 |
| **Estimated total per article** | **$0.16–$0.28** |
| **Budget ceiling** | **$0.50** |

The shift to winner-only claim extraction (v1.0 ran extraction on all 3 candidates per target) cuts LLM extraction calls by ~60% versus a naive implementation, more than offsetting the addition of authority gap H3 citations.

**Monthly operational cost at 10–20 articles/day:** ~$50–$170/month

Combined with the upstream Brief Generator ($0.19–$0.53/brief), the combined pipeline cost per article is **$0.35–$0.81**, with a combined budget ceiling of **$1.25**.

---

## 10. Volume and Scale Assumptions

- **Current volume:** 10–20 articles/day (mirrors upstream Brief Generator)
- **Trigger source:** Automatic, synchronous — fires when Brief Generator completes
- **Concurrency:** Sequential per-user in v1, consistent with upstream module

---

## 11. Business Rules Summary

| Rule | Value |
|---|---|
| Locale | English / United States |
| Source language | English only — non-English sources excluded |
| Citation target scope | Content H2s + up to 3 highest-priority authority gap H3s |
| Maximum dedicated authority gap H3 citations | 3 per article |
| Maximum supplemental article-level citations | 4 per article |
| Minimum citations per content H2 | 1 |
| Minimum total citations per article | None (no hard floor; accept what pipeline produces) |
| Citation mapping granularity | H2 + selected authority gap H3s; other H3s inherit via parent H2 |
| Claim verification required | Yes — every claim must verbatim or fuzzy-match the source body, with all numeric tokens appearing exactly |
| Source tiers | 3 (Tier 1: Gov/Academic, Tier 2: Major Publications/Research Firms, Tier 3: General Web) |
| Competitor SERP domains | Excluded |
| Wikipedia | Excluded |
| Social media platforms | Excluded |
| Reddit | Excluded |
| Paywalled content | Excluded; flagged |
| Bot-blocked content | Excluded; flagged |
| Sources with no detectable date | Excluded |
| PDF sources | Supported via PDF text extraction |
| Recency hard exclude | >5 years (Tier 1 foundational sources excepted) |
| Claims per source | Up to 5; minimum verified `relevance_score` 0.50 |
| Candidate sources fetched per target | Top 3 accessible after filtering |
| Citation score minimum threshold | 0.45 (accept with `citation_quality_low: true` flag below this) |
| Shared citations | Permitted; flagged |
| Per-LLM-call timeout | 25 seconds |

---

## 12. Upstream Schema Dependency

This module requires one addition to the Content Brief Generator output schema (v1.7 → v1.8):

```json
"competitor_domains": ["example.com", "competitor.com"]
```

Root domains of all URLs returned in the SERP scrape (Step 1 of the Brief Generator). Until this field is added to the brief schema, the Research & Citations Module proceeds without competitor exclusion and flags `competitor_exclusion_unavailable: true`. This is a degraded state, not a hard failure.

The Brief Generator's `schema_version` should be incremented to `1.8` when this field is added.

---

## 13. What This PRD Does Not Cover

To be addressed in the engineering implementation spec:

- LLM model selection for query generation and claim extraction calls
- Content farm blocklist definition, hosting, and update process
- Tier 2 domain allowlist — specific enumeration of qualifying publications and research firms
- ScrapeOwl rate limiting, retry logic, session/concurrency management, and **robots.txt compliance verification**
- DataForSEO authentication, quota management, and cost tracking
- PDF extraction library selection (pypdf, PyMuPDF, etc.) and OCR fallback for scanned PDFs
- Language detection library selection (langdetect, cld3, fasttext)
- Caching strategy — citation results for a given keyword may be partially reused across briefs
- Schema versioning compatibility with Writer Module
- Citation link rot detection — deferred to a future monitoring module
- Academic database integrations (PubMed, CrossRef) — deferred to v2
- Coordination with Brief Generator team for `competitor_domains` field addition to schema v1.8

---

## 14. Version History

| Version | Date | Notes |
|---|---|---|
| 1.0 | 2026-04-29 | Initial draft |
| 1.1 | 2026-04-29 | Added claim verification pass (verbatim + fuzzy + numeric integrity check); restructured Step 5 to extract claims from winner only (with fallback chain); added dedicated authority gap H3 citations (max 3/article); added PDF source handling; added bot-block detection; added English-only language detection; replaced minimum-4 citation requirement with maximum-4 supplemental citations cap; raised citation score threshold from 0.30 to 0.45; added 25s per-LLM-call timeout; `citation_ids` now present on all heading items; added `extraction_method` and `verification_method` fields on claims; sources without detectable dates now excluded |
